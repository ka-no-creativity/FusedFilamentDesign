"""Geometry detection and native features for counterbore bridges.

This module deliberately has no GUI imports or FeaturePython classes. Saved
documents recompute through native attachments, external geometry and expressions.
"""

import math
from dataclasses import dataclass
from types import SimpleNamespace

import FreeCAD as App
import Part
import Sketcher

from ffDesign_BridgeProfiles import make_parametric_square, make_parametric_y_cutout


KIND = "CounterboreBridgesFromFace/v1"
GROUP = "Counterbore Bridges"


class BridgeError(ValueError):
    """An unsupported selection or an invalid bridge configuration."""


@dataclass
class Counterbore:
    source: object
    face_name: str
    face: object
    solid: object
    centre: object
    opening: object
    inner_radius: float
    outer_radius: float
    inner_edge: str
    outer_edge: str
    tolerance: float


@dataclass
class BridgeChain:
    settings: object
    result: object
    body: object
    objects: tuple


def resolve_source(source, face_name, *, require_tip=True):
    if source is None or not source.Document:
        raise BridgeError("The source object no longer exists. Select the shoulder again.")
    if source.isDerivedFrom("App::Link"):
        raise BridgeError("Linked instances are unsupported. Select the original solid instead.")
    if source.TypeId == "PartDesign::Body":
        source = source.Tip
        if source is None:
            raise BridgeError("The selected Body has no Tip solid.")
    if face_name.startswith("?"):
        raise BridgeError("The referenced shoulder face is missing. Select a valid shoulder again.")
    if not face_name.startswith("Face") or "." in face_name:
        raise BridgeError("Select exactly one shoulder face on a solid, rather than an object or edge.")
    if not hasattr(source, "Shape") or source.Shape.isNull():
        raise BridgeError("The selected object has no solid shape.")
    parent = source.getParentGeoFeatureGroup()
    if require_tip and parent and parent.TypeId == "PartDesign::Body" and parent.Tip != source:
        raise BridgeError("Select the shoulder on the current Body Tip; historical features are unsupported.")
    return source


def _circle(wire, tolerance):
    # Native external geometry must retain a complete circle, not a collection
    # of independently trimmed arcs whose topology could change on recompute.
    if len(wire.Edges) != 1:
        raise BridgeError("Each shoulder boundary must be one complete circular edge; split arcs are unsupported.")
    edge = wire.Edges[0]
    if not isinstance(edge.Curve, Part.Circle) or not edge.isClosed():
        raise BridgeError("Both shoulder boundaries must be complete circles, without slots or interruptions.")
    if abs(edge.Length - 2 * math.pi * edge.Curve.Radius) > tolerance * 10:
        raise BridgeError("A shoulder boundary is not a complete circle.")
    return edge, edge.Curve


def detect_counterbore(source, face_name, *, require_tip=True):
    source = resolve_source(source, face_name, require_tip=require_tip)
    shape = source.Shape
    if len(shape.Solids) != 1 or not shape.isValid():
        raise BridgeError("Select a valid single solid. Separate multi-solid compounds before adding bridges.")
    try:
        face = shape.getElement(face_name)
    except (Part.OCCError, IndexError, ValueError) as error:
        raise BridgeError("The referenced shoulder face is missing. Select a valid shoulder again.") from error
    if face.ShapeType != "Face" or not isinstance(face.Surface, Part.Plane):
        raise BridgeError("The shoulder must be planar; countersinks and curved seats are unsupported.")
    if len(face.Wires) != 2:
        raise BridgeError("Select the ring-shaped shoulder with exactly two circular boundaries.")
    tolerance = max(1e-7, shape.BoundBox.DiagonalLength * 1e-8)
    boundaries = sorted((_circle(w, tolerance) for w in face.Wires), key=lambda item: item[1].Radius)
    (inner_edge, inner), (outer_edge, outer) = boundaries
    if (inner.Center - outer.Center).Length > tolerance:
        raise BridgeError("The shoulder circles must be concentric.")
    if abs(abs(inner.Axis.dot(outer.Axis)) - 1) > 1e-7:
        raise BridgeError("The shoulder circles must share an axis.")
    if inner.Radius <= tolerance or outer.Radius - inner.Radius <= tolerance:
        raise BridgeError("The shoulder must have distinct, positive inner and outer diameters.")
    if outer.Radius + tolerance < math.sqrt(2) * inner.Radius:
        raise BridgeError("The counterbore is too narrow for the square bridge: outer diameter must be at least "
                          "sqrt(2) times the inner diameter.")

    def wall_side(edge, circle):
        adjacent = [f for f in shape.Faces if not f.isSame(face) and any(edge.isSame(e) for e in f.Edges)]
        if len(adjacent) != 1 or not isinstance(adjacent[0].Surface, Part.Cylinder):
            raise BridgeError("Each circle must adjoin one cylindrical bore wall; "
                              "fillets and chamfers are unsupported.")
        wall = adjacent[0]
        cylinder = wall.Surface
        axis = outer.Axis
        offset = cylinder.Center - outer.Center
        if (abs(cylinder.Radius - circle.Radius) > tolerance
                or abs(abs(cylinder.Axis.dot(axis)) - 1) > 1e-7
                or offset.cross(axis).Length > tolerance):
            raise BridgeError("The adjacent bore walls must be coaxial cylinders matching the shoulder circles.")
        offsets = [(v.Point - outer.Center).dot(axis) for v in wall.Vertexes]
        lo, hi = min(offsets), max(offsets)
        if lo >= -tolerance and hi > tolerance:
            return 1
        if hi <= tolerance and lo < -tolerance:
            return -1
        raise BridgeError("The adjacent wall crosses the shoulder; the counterbore opening direction is ambiguous.")

    outer_side = wall_side(outer_edge, outer)
    if wall_side(inner_edge, inner) != -outer_side:
        raise BridgeError("The larger and smaller bore walls must extend on opposite sides of the shoulder.")
    opening = outer.Axis * outer_side
    if face.normalAt(0, 0).dot(opening) < 1 - 1e-7:
        raise BridgeError("The solid's shoulder orientation is inconsistent with its bore walls. "
                          "Repair the solid first.")

    def edge_name(edge):
        return next(f"Edge{i}" for i, candidate in enumerate(shape.Edges, 1) if edge.isSame(candidate))

    return Counterbore(source, face_name, face, shape.Solids[0], outer.Center, opening,
                       inner.Radius, outer.Radius, edge_name(inner_edge), edge_name(outer_edge), tolerance)


def length_mm(value):
    quantity = App.Units.Quantity(value)
    if quantity.Unit not in (App.Units.Unit(), App.Units.Length) or not math.isfinite(quantity.Value):
        raise BridgeError("Layer height must be a finite length.")
    return quantity.Value


def angle_degrees(value):
    quantity = App.Units.Quantity(value)
    if quantity.Unit not in (App.Units.Unit(), App.Units.Angle) or not math.isfinite(quantity.Value):
        raise BridgeError("Bridge rotation must be a finite angle.")
    return quantity.Value


def validate_material(info, layer_height):
    height = length_mm(layer_height)
    if height <= info.tolerance * 10:
        raise BridgeError("Layer height must be positive and larger than the geometry tolerance.")
    # Require backing beyond the deepest cut, including around its outer edge.
    clearance = max(info.tolerance * 20, height * 1e-5)
    depth = 2 * height + clearance
    start = info.centre - info.opening * depth
    inner = info.inner_radius + info.tolerance * 4
    outer = info.outer_radius - info.tolerance * 4
    sleeve = Part.makeCylinder(outer, depth, start, info.opening).cut(
        Part.makeCylinder(inner, depth, start, info.opening))
    volume_tolerance = max(1e-9, sleeve.Volume * 1e-7)
    if sleeve.cut(info.solid).Volume > volume_tolerance:
        raise BridgeError(f"Insufficient material behind the shoulder: two {height:g} mm bridge layers "
                          "need continuous backing with material remaining beyond the deepest cut.")
    bore = Part.makeCylinder(info.inner_radius - info.tolerance * 4, depth, start, info.opening)
    if bore.common(info.solid).Volume > volume_tolerance:
        raise BridgeError("The smaller bore does not continue through both bridge layers. Reduce the layer height.")
    opening_probe = Part.makeCylinder(outer, clearance, info.centre, info.opening)
    if opening_probe.common(info.solid).Volume > volume_tolerance:
        raise BridgeError("The counterbore opening is obstructed immediately above the shoulder.")
    return height


def _property(obj, type_name, name, value, *, readonly=False):
    obj.addProperty(type_name, name, GROUP)
    setattr(obj, name, value)
    if readonly:
        obj.setEditorMode(name, 1)


def world_shape(obj):
    """Return a shape in world coordinates, including containing App::Parts."""
    shape = obj.Shape.copy()
    parent_placement = obj.getGlobalPlacement().multiply(obj.Placement.inverse())
    shape.Placement = parent_placement.multiply(shape.Placement)
    return shape


def _world_opening(info):
    parent = info.source.getGlobalPlacement().multiply(info.source.Placement.inverse())
    return parent.Rotation.multVec(info.opening)


def _check_native(objects):
    for obj in objects:
        if "Invalid" in obj.State:
            raise BridgeError(f"Cannot build {obj.Label}: {obj.getStatusString()}")


def create_bridges(source, face_name, layer_height=0.2, rotation=0, *, transaction=True):
    """Create only native objects; return transient Python handles to the chain.

    The GUI owns a longer transaction while previewing. Other callers get an
    atomic operation by default.
    """
    info = detect_counterbore(source, face_name)
    height = validate_material(info, layer_height)
    rotation = angle_degrees(rotation)
    source = info.source
    doc = source.Document
    if transaction:
        doc.openTransaction("Counterbore Bridges from Face")
    try:
        chain = _create_native(info, height, rotation)
        if transaction:
            doc.commitTransaction()
        return chain
    except Exception:
        if transaction:
            doc.abortTransaction()
        raise


def _create_native(info, height, rotation):
    source, doc = info.source, info.source.Document
    parent = source.getParentGeoFeatureGroup()
    body = parent if parent and parent.TypeId == "PartDesign::Body" else None
    objects = []
    if body is None:
        body = doc.addObject("PartDesign::Body", "CounterboreBridges")
        objects.append(body)
        if parent and parent.TypeId == "App::Part":
            parent.addObject(body)
        cut_base = body.newObject("PartDesign::FeatureBase", "BaseFeature")
        cut_base.BaseFeature = source
        objects.append(cut_base)
        body.Tip = cut_base
        # BaseFeature copies geometry in source-local coordinates. Keep the
        # result in the same parent frame, with a live placement dependency.
        body.setExpression("Placement", f"{source.Name}.Placement")
        doc.recompute()
    else:
        cut_base = source

    shoulder = body.newObject("PartDesign::SubShapeBinder", "BridgeShoulder")
    shoulder.Support = [(cut_base, [info.face_name])]
    # Keep subelement locations as well as the owning object's placement. Hole
    # faces can have an internal location even when Hole.Placement is identity.
    shoulder.Relative = True
    doc.recompute()
    _check_native([shoulder])
    objects.append(shoulder)
    dimensions = body.newObject("Sketcher::SketchObject", "BridgeDimensions")
    dimensions.AttachmentSupport = [(shoulder, ["Face1"])]
    dimensions.MapMode = "FlatFace"
    doc.recompute()
    # Bind the two native external circles by radius, independent of wire order.
    edges = sorted(enumerate(shoulder.Shape.Edges, 1), key=lambda item: item[1].Curve.Radius)
    for index, _ in edges:
        dimensions.addExternal(shoulder.Name, f"Edge{index}")
    doc.recompute()
    for index, name in enumerate(("InnerDiameter", "OuterDiameter")):
        constraint = dimensions.addConstraint(Sketcher.Constraint("Diameter", -3 - index, 1))
        dimensions.setDriving(constraint, False)
        dimensions.renameConstraint(constraint, name)
    # A reference dimension cannot drive another property on its own sketch.
    # A native VarSet keeps the measurement -> settings -> cutout graph acyclic.
    settings = body.newObject("App::VarSet", "CounterboreBridgeParameters")
    settings.Label = "Counterbore Bridges — Parameters"
    _property(settings, "App::PropertyString", "BridgeKind", KIND, readonly=True)
    settings.setEditorMode("BridgeKind", 2)
    _property(settings, "App::PropertyLinkSubGlobal", "SourceFace", (source, [info.face_name]), readonly=True)
    _property(settings, "App::PropertyLength", "LayerHeight", height)
    _property(settings, "App::PropertyAngle", "BridgeRotation", rotation)
    for name in ("InnerDiameter", "OuterDiameter"):
        _property(settings, "App::PropertyLength", name, 0, readonly=True)
        settings.setExpression(name, f"{dimensions.Name}.Constraints.{name}")
    _property(settings, "App::PropertyString", "ValidationStatus", "Valid", readonly=True)
    settings.setPropertyStatus("ValidationStatus", "NoRecompute")
    _property(settings, "App::PropertyString", "ResultName", "", readonly=True)
    settings.setEditorMode("ResultName", 2)
    objects.extend([dimensions, settings])
    doc.recompute()

    # ExternalGeo begins with the sketch's two axes, followed by our circles.
    # Move the profiles' origin to the measured centre BEFORE rotating them.
    location = SimpleNamespace(x_expr="0 mm", y_expr="0 mm")
    body.Tip = cut_base
    for suffix, multiplier in (("Y", 1), ("X", 2)):
        sketch = body.newObject("Sketcher::SketchObject", f"FaceBridges{suffix}Profile")
        sketch.AttachmentSupport = [(dimensions, [""])]
        sketch.MapMode = "ObjectXY"
        for component in ("x", "y"):
            sketch.setExpression(f"AttachmentOffset.Base.{component}",
                                 f"{dimensions.Name}.ExternalGeo[2].Center.{component} * 1mm")
        sketch.setExpression("AttachmentOffset.Rotation.Angle", f"{settings.Name}.BridgeRotation")
        doc.recompute()
        if suffix == "Y":
            make_parametric_y_cutout(sketch, location, f"{settings.Name}.InnerDiameter",
                                     f"{settings.Name}.OuterDiameter")
        else:
            make_parametric_square(sketch, location, f"{settings.Name}.InnerDiameter")
        pocket = body.newObject("PartDesign::Pocket", f"FaceBridges{suffix}")
        pocket.Label = f"Counterbore Bridges — Layer {multiplier}"
        pocket.Profile = (sketch, [""])
        pocket.ReferenceAxis = (sketch, ["N_Axis"])
        pocket.Reversed = sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1)).dot(
            _world_opening(info)) < 0
        pocket.setExpression("Length", f"{settings.Name}.LayerHeight * {multiplier}")
        objects.extend([sketch, pocket])
        doc.recompute()
        _check_native(objects)
        if pocket.Shape.isNull() or len(pocket.Shape.Solids) != 1:
            raise BridgeError("The bridge cutouts did not produce a single valid solid.")

    settings.ResultName = pocket.Name
    for obj in objects:
        if obj.TypeId != "PartDesign::Body" and hasattr(obj, "ViewObject") and obj.ViewObject:
            obj.Visibility = False
    if App.GuiUp:
        source.Visibility = False
        body.Visibility = True
        pocket.Visibility = True
    doc.recompute()
    status = validate_settings(settings)
    if status != "Valid":
        raise BridgeError(status)
    return BridgeChain(settings, pocket, body, tuple(objects))


def validate_settings(settings):
    """Return an actionable error without repairing or retargeting geometry."""
    try:
        reference = settings.SourceFace
        if not reference or reference[0] is None or len(reference[1]) != 1:
            raise BridgeError("The referenced source face is missing. Recreate bridges from a valid shoulder.")
        info = detect_counterbore(reference[0], reference[1][0], require_tip=False)
        validate_material(info, settings.LayerHeight)
        angle_degrees(settings.BridgeRotation)
        _check_native([settings])
        result = settings.Document.getObject(settings.ResultName)
        if result is None:
            raise BridgeError("The final bridge Pocket is missing. Recreate the bridge feature chain.")
        _check_native([result, result.Profile[0]])
        profile_placement = result.Profile[0].getGlobalPlacement()
        parent = info.source.getGlobalPlacement().multiply(info.source.Placement.inverse())
        if (profile_placement.Base - parent.multVec(info.centre)).Length > info.tolerance * 10:
            raise BridgeError("The attached bridge profiles no longer match the shoulder centre. "
                              "Recreate bridges from the current face.")
        direction = result.Profile[0].getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
        if (direction.dot(_world_opening(info)) < 0) != result.Reversed:
            raise BridgeError("The shoulder's attachment direction changed. Recreate bridges from the current face.")
        if result.Shape.isNull() or not result.Shape.isValid():
            raise BridgeError("The bridge Pockets have no valid result. Check their attachments and profiles.")
        if info.source.Shape.Volume - result.Shape.Volume <= 1e-9:
            raise BridgeError("The bridge Pockets remove no material. Check their placement and direction.")
        for name, radius in (("InnerDiameter", info.inner_radius), ("OuterDiameter", info.outer_radius)):
            if abs(getattr(settings, name).Value - 2 * radius) > info.tolerance * 10:
                raise BridgeError("The measured circles no longer match the shoulder. Recreate its bridge chain.")
        return "Valid"
    except Exception as error:
        return f"Invalid counterbore bridges: {error}"


class BridgeValidationObserver:
    """Supplement native errors with geometry checks while the addon is loaded."""

    def __init__(self):
        self.busy = False

    def slotRecomputedDocument(self, doc):
        if self.busy or getattr(doc, "Restoring", False):
            return
        self.busy = True
        try:
            for obj in doc.Objects:
                if getattr(obj, "BridgeKind", None) != KIND or not getattr(obj, "ResultName", None):
                    continue
                status = validate_settings(obj)
                if status != obj.ValidationStatus:
                    obj.ValidationStatus = status
                    if status != "Valid":
                        App.Console.PrintError(f"[FusedFilamentDesign] {obj.Label}: {status}\n")
        finally:
            self.busy = False

    def slotFinishRestoreDocument(self, doc):
        self.slotRecomputedDocument(doc)


def register_observer():
    # Keep one live observer across GUI/headless imports and module reloads.
    attribute = "_ffDesignCounterboreBridgeObserver"
    if not hasattr(App, attribute):
        observer = BridgeValidationObserver()
        setattr(App, attribute, observer)
        App.addDocumentObserver(observer)
