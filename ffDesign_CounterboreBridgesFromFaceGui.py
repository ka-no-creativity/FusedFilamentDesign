"""Task panel for the native, geometry-based counterbore bridges command."""

import FreeCAD as App
import FreeCADGui as Gui

import ffDesign_Utils as Utils
import ffDesign_CounterboreBridgesFromFace as Bridges


def get_selection():
    if not App.ActiveDocument:
        raise Bridges.BridgeError("Open a document and select one counterbore shoulder face.")
    selection = Gui.Selection.getSelectionEx()
    if len(selection) != 1 or len(selection[0].SubElementNames) != 1:
        raise Bridges.BridgeError("Select exactly one flat, ring-shaped counterbore shoulder face.")
    selected = selection[0]
    if selected.Object.Document != App.ActiveDocument:
        raise Bridges.BridgeError("Select a shoulder in the active document.")
    name = selected.SubElementNames[0]
    return Bridges.resolve_source(selected.Object, name), name


class CounterboreBridgesFromFaceTaskPanel:
    def __init__(self, source, face_name):
        info = Bridges.detect_counterbore(source, face_name)
        self.source, self.face_name = info.source, info.face_name
        self.source_name = self.source.Name
        self.doc = self.source.Document
        self.chain = None
        self.cut_preview = None
        self.transaction_open = False
        self.closed = False
        self.visibility = {obj.Name: obj.Visibility for obj in self.doc.Objects if obj.ViewObject}
        self.form = Gui.PySideUic.loadUi(Utils.Resources.get_panel("ffDesign_CounterboreBridgesFromFace.ui"))
        self.form.LayerHeight.setProperty("rawValue", 0.2)
        self.form.BridgeRotation.setProperty("rawValue", 0)
        self.form.Preview.clicked.connect(self.update_preview)
        self.form.ShowCutouts.toggled.connect(self._show_cutouts)
        self._show_dimensions(info)

    def _show_dimensions(self, info):
        self.form.Dimensions.setText(
            f"Inner diameter: {App.Units.Quantity(info.inner_radius * 2, App.Units.Length).UserString}\n"
            f"Outer diameter: {App.Units.Quantity(info.outer_radius * 2, App.Units.Length).UserString}\n"
            f"Centre (source frame): {info.centre.x:g}, {info.centre.y:g}, {info.centre.z:g} mm\n"
            f"Opening axis: {info.opening.x:.4g}, {info.opening.y:.4g}, {info.opening.z:.4g}"
        )

    def _show_cutouts(self, checked):
        if self.cut_preview:
            self.cut_preview.Visibility = bool(checked)

    def update_preview(self):
        try:
            if self.chain:
                self.source, names = self.chain.settings.SourceFace
                if not self.source or len(names) != 1:
                    raise Bridges.BridgeError("The referenced shoulder is missing. Cancel and select a new shoulder.")
                self.face_name = names[0]
            info = Bridges.detect_counterbore(self.source, self.face_name, require_tip=self.chain is None)
            height = Bridges.validate_material(info, self.form.LayerHeight.property("value"))
            rotation = Bridges.angle_degrees(self.form.BridgeRotation.property("value"))
            if self.chain is None:
                self.doc.openTransaction("Counterbore Bridges from Face")
                self.transaction_open = True
                try:
                    self.chain = Bridges.create_bridges(
                        self.source, self.face_name, height, rotation, transaction=False)
                except Exception:
                    self.doc.abortTransaction()
                    self.transaction_open = False
                    raise
            else:
                self.chain.settings.LayerHeight = height
                self.chain.settings.BridgeRotation = rotation
                self.doc.recompute()
            status = Bridges.validate_settings(self.chain.settings)
            if status != "Valid":
                raise Bridges.BridgeError(status)
            removed = Bridges.world_shape(self.source).cut(Bridges.world_shape(self.chain.result))
            if removed.isNull() or removed.Volume <= 0:
                raise Bridges.BridgeError("The bridge Pockets remove no material from the source.")
            if self.cut_preview is None:
                self.cut_preview = self.doc.addObject("Part::Feature", "CounterboreBridgeCutPreview")
                self.cut_preview.Label = "Bridge cutouts (preview only)"
                self.cut_preview.ViewObject.ShapeColor = (1.0, 0.25, 0.1)
                self.cut_preview.ViewObject.Transparency = 35
                self.cut_preview.ViewObject.Selectable = False
            self.cut_preview.Shape = removed
            self.cut_preview.Visibility = self.form.ShowCutouts.isChecked()
            self.source.Visibility = False
            self.chain.body.Visibility = True
            self.chain.result.Visibility = True
            self._show_dimensions(info)
            self.form.Status.setText(
                "Preview ready. Orange shows removed material. Confirm to keep the native features.")
            return True
        except Exception as error:
            self.form.Status.setText(str(error))
            if self.cut_preview:
                self.cut_preview.Visibility = False
            source = self.doc.getObject(self.source_name)
            if self.chain:
                self.chain.result.Visibility = False
                if source is None or self.chain.body != source.getParentGeoFeatureGroup():
                    self.chain.body.Visibility = False
            if source:
                source.Visibility = True
            return False

    def accept(self):
        if self.closed or not self.update_preview():
            return False
        if self.cut_preview:
            self.doc.removeObject(self.cut_preview.Name)
            self.cut_preview = None
        self.doc.recompute()
        self.doc.commitTransaction()
        self.transaction_open = False
        self.closed = True
        Gui.Control.closeDialog()
        return True

    def reject(self):
        if self.closed:
            return True
        if self.transaction_open:
            self.doc.abortTransaction()
            self.transaction_open = False
        self.chain = None
        self.cut_preview = None
        for name, visible in self.visibility.items():
            obj = self.doc.getObject(name)
            if obj is not None:
                obj.Visibility = visible
        self.doc.recompute()
        self.closed = True
        Gui.Control.closeDialog()
        return True

    def isAllowedAlterDocument(self):
        return False

    def isAllowedAlterSelection(self):
        return False

    def isAllowedAlterView(self):
        return True


class CounterboreBridgesFromFaceCommand:
    def GetResources(self):
        return {
            "Pixmap": "icons:ffDesign_CounterboreBridges.svg",
            "MenuText": App.Qt.translate("ffDesign", "Counterbore Bridges from Face"),
            "ToolTip": App.Qt.translate(
                "ffDesign", "Select a flat, circular counterbore shoulder on a solid.\n"
                "Preview two native bridge cutouts with editable layer height and rotation.\n"
                "Works with Hole features, Pockets, Boolean cuts and imported STEP solids."
            ),
        }

    def IsActive(self):
        try:
            get_selection()
            return not Gui.Control.activeDialog()
        except Bridges.BridgeError:
            return False

    def Activated(self):
        try:
            if Gui.Control.activeDialog():
                raise Bridges.BridgeError("Close the current task panel before adding counterbore bridges.")
            source, face_name = get_selection()
            panel = CounterboreBridgesFromFaceTaskPanel(source, face_name)
            Gui.Control.showDialog(panel)
            panel.update_preview()
        except Bridges.BridgeError as error:
            Utils.ffDesignError(str(error)).emit_to_user()


Bridges.register_observer()
Gui.addCommand("ffDesign_CounterboreBridgesFromFace", CounterboreBridgesFromFaceCommand())
