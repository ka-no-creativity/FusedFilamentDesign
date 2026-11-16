"""Procedural geometry tests; no downloaded FCStd fixtures are required."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import FreeCAD as App
import Part
import Sketcher

import ffDesign_CounterboreBridgesFromFace as Bridges


def shoulder_name(source, x=None):
    for index, face in enumerate(source.Shape.Faces, 1):
        if (isinstance(face.Surface, Part.Plane) and len(face.Wires) == 2
                and all(len(w.Edges) == 1 and isinstance(w.Edges[0].Curve, Part.Circle) for w in face.Wires)):
            if x is None or abs(face.CenterOfMass.x - x) < 1e-5:
                return f"Face{index}"
    raise AssertionError("Fixture has no annular shoulder")


def boolean_source(doc, *, outer_radius=4, depth=4, offset=0):
    block = doc.addObject("Part::Box", "Block")
    block.Length, block.Width, block.Height = 20, 20, 10
    bore = doc.addObject("Part::Cylinder", "Bore")
    bore.Radius, bore.Height = 2, 10
    bore.Placement.Base = App.Vector(10, 10, 0)
    drilled = doc.addObject("Part::Cut", "Drilled")
    drilled.Base, drilled.Tool = block, bore
    counterbore = doc.addObject("Part::Cylinder", "Counterbore")
    counterbore.Radius, counterbore.Height = outer_radius, depth
    counterbore.Placement.Base = App.Vector(10 + offset, 10, 10 - depth)
    source = doc.addObject("Part::Cut", "Source")
    source.Base, source.Tool = drilled, counterbore
    doc.recompute()
    return source, bore, counterbore


def partdesign_source(doc, *, hole=False):
    body = doc.addObject("PartDesign::Body", "Body")
    base = body.newObject("PartDesign::Feature", "Base")
    base.Shape = Part.makeBox(20, 20, 10)
    profile = body.newObject("Sketcher::SketchObject", "BoreProfile")
    profile.Placement.Base = App.Vector(0, 0, 10)
    profile.addGeometry(Part.Circle(App.Vector(10, 10, 0), App.Vector(0, 0, 1), 2), False)
    doc.recompute()
    if hole:
        source = body.newObject("PartDesign::Hole", "Hole")
        source.Profile = (profile, [""])
        source.Diameter, source.Depth = 4, 10
        source.HoleCutType = "Counterbore"
        source.HoleCutDiameter, source.HoleCutDepth = 8, 4
    else:
        drilled = body.newObject("PartDesign::Pocket", "BorePocket")
        drilled.Profile, drilled.Length = (profile, [""]), 10
        doc.recompute()
        cb_profile = body.newObject("Sketcher::SketchObject", "CounterboreProfile")
        cb_profile.Placement.Base = App.Vector(0, 0, 10)
        cb_profile.addGeometry(Part.Circle(App.Vector(10, 10, 0), App.Vector(0, 0, 1), 4), False)
        source = body.newObject("PartDesign::Pocket", "CounterborePocket")
        source.Profile, source.Length = (cb_profile, [""]), 4
    doc.recompute()
    if source.Shape.isNull():
        raise AssertionError(source.getStatusString())
    return source


def reference_shape(source, face_name, height=0.2, rotation=0):
    """Independent Boolean construction, without sketches or Pocket features."""
    info = Bridges.detect_counterbore(source, face_name, require_tip=False)
    r, radius = info.inner_radius, info.outer_radius
    first = Part.makeCylinder(radius, height, App.Vector(0, 0, -height)).common(
        Part.makeBox(2 * r, 2 * radius, height, App.Vector(-r, -radius, -height)))
    second = Part.makeBox(2 * r, 2 * r, 2 * height, App.Vector(-r, -r, -2 * height))
    frame = info.face.Surface.Rotation
    if info.face.Surface.Axis.dot(info.opening) < 0:
        frame = frame.multiply(App.Rotation(App.Vector(1, 0, 0), 180))
    placement = App.Placement(info.centre, frame.multiply(App.Rotation(App.Vector(0, 0, 1), rotation)))
    parent = source.getGlobalPlacement().multiply(source.Placement.inverse())
    for tool in (first, second):
        tool.Placement = parent.multiply(placement.multiply(tool.Placement))
    return Bridges.world_shape(source).cut(first.fuse(second))


class NativeCounterboreBridges(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("FaceBridgeTests")
        self.doc.UndoMode = 1
        Bridges.register_observer()

    def tearDown(self):
        if App.getDocument(self.doc.Name):
            App.closeDocument(self.doc.Name)

    def assertSameShape(self, actual, expected):
        self.assertTrue(actual.isValid())
        self.assertAlmostEqual(actual.Volume, expected.Volume, places=6)
        self.assertLess(actual.cut(expected).Volume + expected.cut(actual).Volume, 1e-6)

    def test_boolean_sources_and_orientations(self):
        for angle in (0, 180, 57):
            with self.subTest(angle=angle):
                source, _, _ = boolean_source(self.doc)
                source.Placement = App.Placement(App.Vector(12, 7, 3), App.Rotation(App.Vector(1, 1, 0), angle))
                self.doc.recompute()
                name = shoulder_name(source)
                expected = reference_shape(source, name, rotation=31)
                chain = Bridges.create_bridges(source, name, rotation=31)
                self.assertSameShape(Bridges.world_shape(chain.result), expected)
                self.assertEqual(Bridges.validate_settings(chain.settings), "Valid")
                self.assertTrue(all(not obj.TypeId.endswith("Python") for obj in self.doc.Objects))

    def test_hole_and_pocket_sources(self):
        for hole in (True, False):
            with self.subTest(hole=hole):
                source = partdesign_source(self.doc, hole=hole)
                name = shoulder_name(source)
                expected = reference_shape(source, name)
                chain = Bridges.create_bridges(source.getParentGeoFeatureGroup(), name)
                self.assertEqual(chain.body, source.getParentGeoFeatureGroup())
                self.assertEqual(chain.body.Tip, chain.result)
                self.assertSameShape(Bridges.world_shape(chain.result), expected)

    def test_counterbore_opening_toward_negative_z(self):
        source = self.doc.addObject("Part::Feature", "BottomCounterbore")
        source.Shape = Part.makeBox(20, 20, 10).cut(
            Part.makeCylinder(2, 10, App.Vector(10, 10, 0))).cut(
            Part.makeCylinder(4, 4, App.Vector(10, 10, 0)))
        name = shoulder_name(source)
        info = Bridges.detect_counterbore(source, name)
        self.assertLess(info.opening.z, -0.99)
        expected = reference_shape(source, name, rotation=24)
        chain = Bridges.create_bridges(source, name, rotation=24)
        self.assertSameShape(Bridges.world_shape(chain.result), expected)

    def test_parent_part_and_body_placements(self):
        for in_body in (False, True):
            with self.subTest(in_body=in_body):
                part = self.doc.addObject("App::Part", "Assembly")
                part.Placement = App.Placement(App.Vector(-13, 4, 9), App.Rotation(App.Vector(0, 1, 0), 23))
                if in_body:
                    source = partdesign_source(self.doc, hole=True)
                    body = source.getParentGeoFeatureGroup()
                    part.addObject(body)
                    body.Placement = App.Placement(App.Vector(6, 2, -5), App.Rotation(App.Vector(1, 0, 0), 180))
                else:
                    source, _, _ = boolean_source(self.doc)
                    part.addObject(source)
                    source.Placement = App.Placement(App.Vector(6, 2, -5), App.Rotation(App.Vector(1, 0, 0), 57))
                self.doc.recompute()
                name = shoulder_name(source)
                expected = reference_shape(source, name, rotation=67)
                chain = Bridges.create_bridges(source, name, rotation=67)
                self.assertSameShape(Bridges.world_shape(chain.result), expected)

    def test_step_round_trip(self):
        source, _, _ = boolean_source(self.doc)
        with tempfile.TemporaryDirectory() as directory:
            filename = str(Path(directory) / "counterbore.step")
            Part.export([source], filename)
            shape = Part.read(filename)
        imported = self.doc.addObject("Part::Feature", "ImportedSTEP")
        imported.Shape = shape
        self.doc.recompute()
        name = shoulder_name(imported)
        expected = reference_shape(imported, name)
        chain = Bridges.create_bridges(imported, name)
        self.assertSameShape(Bridges.world_shape(chain.result), expected)

    def test_recompute_source_and_settings(self):
        source, bore, counterbore = boolean_source(self.doc)
        chain = Bridges.create_bridges(source, shoulder_name(source))
        bore.Radius = 2.2
        counterbore.Radius = 5
        counterbore.Height = 5
        counterbore.Placement.Base.z = 5
        chain.settings.LayerHeight = 0.31
        chain.settings.BridgeRotation = 48
        self.doc.recompute()
        self.assertAlmostEqual(chain.settings.InnerDiameter.Value, 4.4, places=6)
        self.assertAlmostEqual(chain.settings.OuterDiameter.Value, 10, places=6)
        expected = reference_shape(source, shoulder_name(source), 0.31, 48)
        self.assertSameShape(Bridges.world_shape(chain.result), expected)
        self.assertEqual(chain.settings.ValidationStatus, "Valid")
        source.Placement = App.Placement(App.Vector(3, -9, 2), App.Rotation(App.Vector(1, 0, 0), 180))
        self.doc.recompute()
        self.assertSameShape(Bridges.world_shape(chain.result),
                             reference_shape(source, shoulder_name(source), 0.31, 48))

    def test_hole_source_updates(self):
        source = partdesign_source(self.doc, hole=True)
        chain = Bridges.create_bridges(source, shoulder_name(source))
        source.Diameter = 4.4
        source.HoleCutDiameter = 10
        source.HoleCutDepth = 5
        source.Profile[0].Placement.Base = App.Vector(1, -1, 10)
        chain.settings.LayerHeight = 0.25
        chain.settings.BridgeRotation = 27
        self.doc.recompute()
        self.assertEqual(chain.settings.ValidationStatus, "Valid")
        self.assertSameShape(Bridges.world_shape(chain.result),
                             reference_shape(source, shoulder_name(source), 0.25, 27))

    def test_multiple_counterbores(self):
        shape = Part.makeBox(40, 20, 10)
        for x in (10, 30):
            shape = shape.cut(Part.makeCylinder(2, 10, App.Vector(x, 10, 0)))
            shape = shape.cut(Part.makeCylinder(4, 4, App.Vector(x, 10, 6)))
        source = self.doc.addObject("PartDesign::Feature", "TwoCounterbores")
        source.Shape = shape
        first_name = shoulder_name(source, 10)
        expected_first = reference_shape(source, first_name)
        first = Bridges.create_bridges(source, first_name)
        self.assertSameShape(Bridges.world_shape(first.result), expected_first)
        second_name = shoulder_name(first.result, 30)
        expected_second = reference_shape(first.result, second_name, 0.15, 90)
        second = Bridges.create_bridges(first.result, second_name, 0.15, 90)
        self.assertEqual(first.body, second.body)
        self.assertSameShape(Bridges.world_shape(second.result), expected_second)
        self.assertEqual(first.settings.ValidationStatus, "Valid")
        self.assertEqual(second.settings.ValidationStatus, "Valid")

    def test_insufficient_material_and_bore_depth(self):
        source, _, _ = boolean_source(self.doc, depth=9.7)
        objects = len(self.doc.Objects)
        with self.assertRaisesRegex(Bridges.BridgeError, "Insufficient material"):
            Bridges.create_bridges(source, shoulder_name(source))
        self.assertEqual(len(self.doc.Objects), objects)
        chain = Bridges.create_bridges(source, shoulder_name(source), 0.1)
        chain.settings.LayerHeight = 0.2
        self.doc.recompute()
        self.assertIn("Insufficient material", chain.settings.ValidationStatus)
        chain.settings.LayerHeight = 0.1
        self.doc.recompute()
        self.assertEqual(chain.settings.ValidationStatus, "Valid")
        # Blind small bore ending within the two bridge layers.
        blind = self.doc.addObject("PartDesign::Feature", "BlindBore")
        blind.Shape = Part.makeBox(20, 20, 10).cut(Part.makeCylinder(2, 4.2, App.Vector(10, 10, 5.8))).cut(
            Part.makeCylinder(4, 4, App.Vector(10, 10, 6)))
        with self.assertRaisesRegex(Bridges.BridgeError, "smaller bore"):
            Bridges.create_bridges(blind, shoulder_name(blind))

    def test_invalid_geometry_and_selection(self):
        source, _, _ = boolean_source(self.doc, offset=0.2)
        with self.assertRaisesRegex(Bridges.BridgeError, "concentric"):
            Bridges.create_bridges(source, shoulder_name(source))
        narrow, _, _ = boolean_source(self.doc, outer_radius=2.5)
        with self.assertRaisesRegex(Bridges.BridgeError, "too narrow"):
            Bridges.create_bridges(narrow, shoulder_name(narrow))
        valid, _, _ = boolean_source(self.doc)
        for name in ("Edge1", "", "Body.Face9", "Face999"):
            with self.subTest(name=name), self.assertRaises(Bridges.BridgeError):
                Bridges.create_bridges(valid, name)
        for height in (0, -0.2, "1 deg", float("inf")):
            with self.subTest(height=height), self.assertRaises(Bridges.BridgeError):
                Bridges.create_bridges(valid, shoulder_name(valid), height)
        with self.assertRaisesRegex(Bridges.BridgeError, "ring-shaped"):
            Bridges.create_bridges(valid, "Face1")
        compound = self.doc.addObject("PartDesign::Feature", "Compound")
        compound.Shape = Part.makeCompound([valid.Shape, Part.makeBox(2, 2, 2, App.Vector(30, 0, 0))])
        with self.assertRaisesRegex(Bridges.BridgeError, "single solid"):
            Bridges.create_bridges(compound, shoulder_name(compound))
        link = self.doc.addObject("App::Link", "Instance")
        link.setLink(valid)
        with self.assertRaisesRegex(Bridges.BridgeError, "Linked instances"):
            Bridges.create_bridges(link, shoulder_name(valid))
        source = partdesign_source(self.doc, hole=True)
        chain = Bridges.create_bridges(source, shoulder_name(source))
        with self.assertRaisesRegex(Bridges.BridgeError, "current Body Tip"):
            Bridges.create_bridges(source, shoulder_name(source))
        self.assertEqual(Bridges.validate_settings(chain.settings), "Valid")

    def test_changed_or_deleted_face_reports_error(self):
        source, _, _ = boolean_source(self.doc)
        chain = Bridges.create_bridges(source, shoulder_name(source))
        chain.settings.SourceFace = (source, ["Face999"])
        self.doc.recompute()
        self.assertIn("referenced shoulder face is missing", chain.settings.ValidationStatus)
        self.doc.removeObject(source.Name)
        self.doc.recompute()
        self.assertIn("missing", chain.settings.ValidationStatus)

    def test_source_edit_removes_shoulder(self):
        source, bore, counterbore = boolean_source(self.doc)
        chain = Bridges.create_bridges(source, shoulder_name(source))
        counterbore.Radius = bore.Radius
        self.doc.recompute()
        self.assertIn("Invalid counterbore bridges", chain.settings.ValidationStatus)
        self.assertNotEqual(Bridges.validate_settings(chain.settings), "Valid")

    def test_unsupported_seats_and_walls(self):
        source, _, _ = boolean_source(self.doc)
        shoulder = Bridges.detect_counterbore(source, shoulder_name(source))
        filleted = self.doc.addObject("PartDesign::Feature", "FilletedSeat")
        filleted.Shape = source.Shape.makeFillet(0.2, [source.Shape.getElement(shoulder.inner_edge)])
        with self.assertRaisesRegex(Bridges.BridgeError, "cylindrical bore wall"):
            Bridges.create_bridges(filleted, shoulder_name(filleted))
        washer = self.doc.addObject("PartDesign::Feature", "Washer")
        washer.Shape = Part.makeCylinder(4, 4).cut(Part.makeCylinder(2, 4))
        with self.assertRaisesRegex(Bridges.BridgeError, "opposite sides"):
            Bridges.create_bridges(washer, shoulder_name(washer))
        interrupted = self.doc.addObject("PartDesign::Feature", "SlottedShoulder")
        interrupted.Shape = source.Shape.cut(Part.makeBox(2, 10, 6, App.Vector(9, 10, 4)))
        for index, face in enumerate(interrupted.Shape.Faces, 1):
            if isinstance(face.Surface, Part.Plane) and abs(face.CenterOfMass.z - 6) < 1e-6:
                with self.assertRaises(Bridges.BridgeError):
                    Bridges.create_bridges(interrupted, f"Face{index}")
                break
        else:
            self.fail("Missing slotted shoulder fixture")
        countersink = self.doc.addObject("PartDesign::Feature", "Countersink")
        countersink.Shape = Part.makeBox(20, 20, 10).cut(Part.makeCylinder(2, 10, App.Vector(10, 10, 0))).cut(
            Part.makeCone(2, 4, 4, App.Vector(10, 10, 6)))
        conical_face = next(f"Face{i}" for i, face in enumerate(countersink.Shape.Faces, 1)
                            if isinstance(face.Surface, Part.Cone))
        with self.assertRaisesRegex(Bridges.BridgeError, "planar"):
            Bridges.create_bridges(countersink, conical_face)

    def test_undo_redo(self):
        source, _, _ = boolean_source(self.doc)
        original_names = {o.Name for o in self.doc.Objects}
        chain = Bridges.create_bridges(source, shoulder_name(source))
        result_name, settings_name = chain.result.Name, chain.settings.Name
        expected = Bridges.world_shape(chain.result)
        self.doc.undo()
        self.assertEqual({o.Name for o in self.doc.Objects}, original_names)
        self.doc.redo()
        self.doc.recompute()
        self.assertSameShape(Bridges.world_shape(self.doc.getObject(result_name)), expected)
        self.assertEqual(Bridges.validate_settings(self.doc.getObject(settings_name)), "Valid")

    def test_save_reopen_native_recompute(self):
        source, _, _ = boolean_source(self.doc)
        chain = Bridges.create_bridges(source, shoulder_name(source))
        settings_name = chain.settings.Name
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "NativeBridges.FCStd")
            self.doc.saveAs(path)
            name = self.doc.Name
            App.closeDocument(name)
            self.doc = App.openDocument(path)
            settings = self.doc.getObject(settings_name)
            settings.LayerHeight = 0.27
            settings.BridgeRotation = 17
            self.doc.recompute()
            self.assertEqual(settings.ValidationStatus, "Valid")
            if not App.GuiUp and Path(sys.executable).name.lower().startswith("python"):
                # Fresh interpreter with no addon on sys.path: no observer or
                # custom feature class can participate in this recomputation.
                script = """
import sys
sys.path.insert(0, sys.argv[1])
import FreeCAD as A
import Part, Sketcher
d=A.openDocument(sys.argv[2])
p=d.getObject(sys.argv[3]); before=d.getObject(p.ResultName).Shape.Volume
p.LayerHeight=0.27; p.BridgeRotation=17
d.recompute()
r=d.getObject(p.ResultName)
assert r.Shape.isValid() and 'Invalid' not in r.State
assert abs(r.Length.Value-0.54)<1e-8
assert r.Shape.Volume < before-1e-6
assert all(not o.TypeId.endswith('Python') for o in d.Objects)
assert 'ffDesign_CounterboreBridgesFromFace' not in sys.modules
A.closeDocument(d.Name)
"""
                subprocess.run([sys.executable, "-c", script, str(Path(App.__file__).parent), path, settings.Name],
                               cwd=directory, check=True, capture_output=True, text=True)


class _PanelCase(unittest.TestCase):
    setUp = NativeCounterboreBridges.setUp
    tearDown = NativeCounterboreBridges.tearDown
    assertSameShape = NativeCounterboreBridges.assertSameShape


@unittest.skipUnless(App.GuiUp, "Requires the FreeCAD GUI task panel")
class CounterboreBridgesTaskPanelTests(_PanelCase):
    def tearDown(self):
        import FreeCADGui as Gui
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        super().tearDown()

    def make_panel(self, *, depth=4):
        import FreeCADGui as Gui
        from ffDesign_CounterboreBridgesFromFaceGui import CounterboreBridgesFromFaceTaskPanel
        source, _, _ = boolean_source(self.doc, depth=depth)
        panel = CounterboreBridgesFromFaceTaskPanel(source, shoulder_name(source))
        Gui.Control.showDialog(panel)
        return source, panel

    def test_cancel_restores_document(self):
        source, panel = self.make_panel()
        original = {o.Name for o in self.doc.Objects}
        visible = source.Visibility
        self.assertTrue(panel.update_preview(), panel.form.Status.text())
        self.assertFalse(source.Visibility)
        self.assertTrue(panel.reject())
        self.assertEqual({o.Name for o in self.doc.Objects}, original)
        self.assertEqual(source.Visibility, visible)

    def test_preview_matches_confirmation_and_undo(self):
        source, panel = self.make_panel()
        self.assertTrue(panel.update_preview(), panel.form.Status.text())
        panel.form.LayerHeight.setProperty("rawValue", 0.3)
        panel.form.BridgeRotation.setProperty("rawValue", 33)
        self.assertTrue(panel.update_preview(), panel.form.Status.text())
        expected = Bridges.world_shape(panel.chain.result)
        removed_volume = panel.cut_preview.Shape.Volume
        result_name = panel.chain.result.Name
        self.assertTrue(panel.accept())
        self.assertSameShape(Bridges.world_shape(self.doc.getObject(result_name)), expected)
        self.assertAlmostEqual(source.Shape.Volume - expected.Volume, removed_volume, places=6)
        self.assertFalse(any(o.Name.startswith("CounterboreBridgeCutPreview") for o in self.doc.Objects))
        self.doc.undo()
        self.assertIsNone(self.doc.getObject(result_name))
        self.doc.redo()
        self.doc.recompute()
        self.assertSameShape(Bridges.world_shape(self.doc.getObject(result_name)), expected)

    def test_invalid_height_can_be_corrected(self):
        source, panel = self.make_panel(depth=9.7)
        original = {o.Name for o in self.doc.Objects}
        self.assertFalse(panel.update_preview())
        self.assertIn("Insufficient material", panel.form.Status.text())
        self.assertEqual({o.Name for o in self.doc.Objects}, original)
        panel.form.LayerHeight.setProperty("rawValue", 0.1)
        self.assertTrue(panel.update_preview(), panel.form.Status.text())
        panel.form.LayerHeight.setProperty("rawValue", 0.2)
        self.assertFalse(panel.accept())
        self.assertTrue(source.Visibility)
        panel.reject()
        self.assertEqual({o.Name for o in self.doc.Objects}, original)

    def test_face_selection_required(self):
        import FreeCADGui as Gui
        from ffDesign_CounterboreBridgesFromFaceGui import get_selection
        source, _, _ = boolean_source(self.doc)
        Gui.Selection.clearSelection()
        with self.assertRaises(Bridges.BridgeError):
            get_selection()
        Gui.Selection.addSelection(source)
        with self.assertRaises(Bridges.BridgeError):
            get_selection()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(source, shoulder_name(source))
        self.assertEqual(get_selection(), (source, shoulder_name(source)))

    def test_legacy_hole_bridges(self):
        import ffDesign_CounterboreBridges as Legacy
        source = partdesign_source(self.doc, hole=True)
        expected = reference_shape(source, shoulder_name(source))
        body = source.getParentGeoFeatureGroup()
        Legacy.make_upside_down_counterbores(body, source)
        self.doc.recompute()
        self.assertSameShape(Bridges.world_shape(body.Tip), expected)


if __name__ == "__main__":
    unittest.main()
