# Counterbore Bridges from Face

Create two-layer bridge cutouts by selecting the flat ring where a screw head
rests inside an existing counterbore. The source can be a PartDesign Hole,
Pockets, Boolean cuts, or an imported STEP solid. No source sketch is required.

## Usage

1. Select exactly one counterbore shoulder face on the solid's current shape.
2. In the PartDesign FusedFilamentDesign toolbar, run **Counterbore Bridges from Face**.
3. Check the detected inner/outer diameters, centre and opening axis.
4. Set **Print layer height** (default 0.2 mm) and **Bridge rotation** (default 0°).
5. Click **Update preview** after editing values. Orange highlights removed
   material; uncheck **Highlight removed material** to inspect the finished solid.
6. Confirm with **OK**, or **Cancel** to restore the original document.

Confirmation always refreshes the preview using the current values. The entire
operation is one undo step. Other counterbores remain unchanged; repeat the
command on another shoulder of the resulting solid to process it independently.

The existing Hole-based command and Hole Wizard remain available.

## Native feature tree and parameters

The command creates a native SubShapeBinder referencing the shoulder, a
measurement sketch with external circular geometry, a native **VarSet** labelled
**Counterbore Bridges — Parameters**, and two sketch/Pocket pairs. An existing
PartDesign Body receives the Pockets directly. Standalone solids receive a new
Body with a linked native BaseFeature and an expression tracking source placement.
Containing App::Part placements are preserved.

Select **Counterbore Bridges — Parameters** to edit:

- `LayerHeight`: thickness of each bridge layer, in millimetres.
- `BridgeRotation`: rotation in the attached sketch plane, in degrees.

The VarSet also exposes read-only `SourceFace`, `InnerDiameter`, `OuterDiameter`,
and `ValidationStatus`. The first Pocket cuts the circular strip one layer into
the backing material. The second cuts the square two layers into it. The
rotation origin is the detected circle centre, including for off-origin holes.

All stored features are native FreeCAD types. Geometry recomputes through native
attachments, external circles, reference dimensions and expressions. The addon
does not need to be installed to view, edit or recompute the saved geometry.

With the addon installed, a document observer additionally checks the shoulder
and backing material after recomputation and document restoration. It reports
errors in `ValidationStatus` and the Report view; it never repairs or guesses a
replacement reference. FreeCAD's native attachment and expression errors remain
available independently of the addon. If topology changes invalidate a shoulder,
recreate its bridge chain from a valid face. A validation error can leave the
last computed shape displayed: inspect `ValidationStatus` after source edits.

## Supported geometry and limits

- One valid solid and one selected shoulder per invocation, in the same document.
- A planar ring with two complete concentric circular edges and coaxial cylindrical
  walls extending on opposite sides of the shoulder. Direction is derived from
  these walls and solid occupancy, independently of global Z.
- Enough continuous annular backing for two bridge layers, with material remaining
  beyond the deepest cut; the smaller bore must continue through both layers.
- An outer diameter of at least `sqrt(2) × inner diameter`, so the existing square
  bridge profile fits inside the counterbore.

Split circular arcs, slots, fillets/chamfers at the shoulder, countersinks,
nonconcentric boundaries, ambiguous wall directions, linked instances and
multi-solid compounds are rejected with an explanation. Split a compound into
single-solid objects or select an instance's original solid first. Select the
current Body Tip rather than a historical feature.

Source-face references use FreeCAD's native topology tracking. Arbitrary STEP
replacement or major topology changes may invalidate those references; the
command does not search for a nearby replacement counterbore. Extra geometry
validation requires the addon to be loaded.
