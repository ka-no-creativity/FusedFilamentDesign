import FreeCADGui as Gui
import FreeCAD as App

import ffDesign_Utils as Utils
from ffDesign_BridgeProfiles import make_parametric_square, make_parametric_y_cutout


def make_upside_down_counterbores(body, hole):
    Utils.assert_body(body)
    Utils.assert_hole(hole)

    if not Utils.hole_has_counterbore_sure(hole):
        Utils.warning_confirm_proceed("Selected Hole does not seem to have a known counterbore type.")

    profile_sketch, profile_partial = Utils.get_hole_profile_sketch(hole)

    sketch_bridges_y = Utils.make_derived_sketch(body, profile_sketch, "_BridgesY")
    sketch_bridges_x = Utils.make_derived_sketch(body, profile_sketch, "_BridgesX")

    for hole_loc in Utils.get_sketch_locations(profile_sketch, Utils.get_hole_profile_type(hole), profile_partial):
        # Create parametric y bridges cutout for this circle
        make_parametric_y_cutout(
            sketch_bridges_y,
            hole_loc,
            f"{hole.Name}.Diameter",
            f"{hole.Name}.HoleCutDiameter",
        )

        # Create parametric x bridges cutout for this circle
        make_parametric_square(
            sketch_bridges_x,
            hole_loc,
            f"{hole.Name}.Diameter",
        )

    Utils.hole_prepare_layer_height_property(hole)

    pocket_bridges_y = body.newObject("PartDesign::Pocket", f"{hole.Name}_BridgesY")
    pocket_bridges_y.Profile = (sketch_bridges_y, "")
    pocket_bridges_y.ReferenceAxis = (sketch_bridges_y, ["N_Axis"])
    pocket_bridges_y.Reversed = hole.Reversed
    sketch_bridges_y.Visibility = False
    pocket_bridges_y.setExpression("Length", f"{hole.Name}.HoleCutDepth + {hole.Name}.LayerHeight")
    pocket_bridges_y.Label = f"{hole.Label}_BridgesY"
    pocket_bridges_y.recompute()

    pocket_bridges_x = body.newObject("PartDesign::Pocket", f"{hole.Name}_BridgesX")
    pocket_bridges_x.Profile = (sketch_bridges_x, "")
    pocket_bridges_x.ReferenceAxis = (sketch_bridges_x, ["N_Axis"])
    pocket_bridges_x.Reversed = hole.Reversed
    sketch_bridges_x.Visibility = False
    pocket_bridges_x.setExpression("Length", f"{hole.Name}.HoleCutDepth + {hole.Name}.LayerHeight * 2")
    pocket_bridges_x.Label = f"{hole.Label}_BridgesX"
    pocket_bridges_x.recompute()


class CounterboreBridgesCommand:
    def GetResources(self):
        return {
            "Pixmap": "icons:ffDesign_CounterboreBridges.svg",
            "MenuText": App.Qt.translate("ffDesign", "Add counterbore bridges"),
            "ToolTip": App.Qt.translate(
                "ffDesign",
                "Add bridges to a counterbored Hole so it can be printed upside down.\n"
                "1. Select a Hole feature in the active body.\n"
                "2. The Hole must have a counterbore of some kind.\n"
                "3. Run this command.\n",
            ),
        }

    def Activated(self):
        try:
            hole = Utils.get_selected_hole()
            body = Utils.get_active_part_design_body_for_feature(hole)

            try:
                App.ActiveDocument.openTransaction("Add counterbores bridges")
                make_upside_down_counterbores(body, hole)
                App.ActiveDocument.recompute()
            except Exception as e:
                App.ActiveDocument.abortTransaction()
                raise e from None
            else:
                App.ActiveDocument.commitTransaction()
        except Utils.ffDesignError as e:
            e.emit_to_user()

    def IsActive(self):
        try:
            hole = Utils.get_selected_hole()
            return Utils.hole_has_counterbore_maybe(hole)
        except Utils.ffDesignPreconditionError:
            return False


Gui.addCommand("ffDesign_CounterboreBridges", CounterboreBridgesCommand())
