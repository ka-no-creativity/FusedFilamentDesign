"""Native sketch profiles shared by the Hole and face bridge commands."""

import math

import FreeCAD as App
import Part
import Sketcher


def make_parametric_square(sketch, hole_loc, size_expr: str):
    assert sketch.TypeId == "Sketcher::SketchObject"

    last_geo_id = len(sketch.Geometry)
    new_geo = [
        Part.LineSegment(App.Vector(-1, 1, 0), App.Vector(1, 1, 0)),
        Part.LineSegment(App.Vector(1, 1, 0), App.Vector(1, -1, 0)),
        Part.LineSegment(App.Vector(1, -1, 0), App.Vector(-1, -1, 0)),
        Part.LineSegment(App.Vector(-1, -1, 0), App.Vector(-1, 1, 0)),
    ]
    sketch.addGeometry(new_geo, False)
    new_constraints = [
        Sketcher.Constraint("Coincident", last_geo_id + 0, 2, last_geo_id + 1, 1),
        Sketcher.Constraint("Coincident", last_geo_id + 1, 2, last_geo_id + 2, 1),
        Sketcher.Constraint("Coincident", last_geo_id + 2, 2, last_geo_id + 3, 1),
        Sketcher.Constraint("Coincident", last_geo_id + 3, 2, last_geo_id + 0, 1),
        Sketcher.Constraint("Horizontal", last_geo_id + 0),
        Sketcher.Constraint("Horizontal", last_geo_id + 2),
        Sketcher.Constraint("Vertical", last_geo_id + 1),
        Sketcher.Constraint("Vertical", last_geo_id + 3),
    ]
    sketch.addConstraint(new_constraints)
    last_c = len(sketch.Constraints)
    new_constraints = [
        Sketcher.Constraint("DistanceX", last_geo_id + 0, 1, -1),
        Sketcher.Constraint("DistanceY", last_geo_id + 0, 1, 1),
        Sketcher.Constraint("DistanceX", last_geo_id + 2, 1, 1),
        Sketcher.Constraint("DistanceY", last_geo_id + 2, 1, -1),
    ]
    sketch.addConstraint(new_constraints)
    sketch.setExpression(f"Constraints[{last_c + 0}]", f"{hole_loc.x_expr} - {size_expr} / 2")
    sketch.setExpression(f"Constraints[{last_c + 1}]", f"{hole_loc.y_expr} + {size_expr} / 2")
    sketch.setExpression(f"Constraints[{last_c + 2}]", f"{hole_loc.x_expr} + {size_expr} / 2")
    sketch.setExpression(f"Constraints[{last_c + 3}]", f"{hole_loc.y_expr} - {size_expr} / 2")
    sketch.recompute()


def make_parametric_y_cutout(sketch, hole_loc, size_inner_expr: str, size_outer_expr: str):
    assert sketch.TypeId == "Sketcher::SketchObject"

    last_geo_id = len(sketch.Geometry)
    new_geo = [
        Part.ArcOfCircle(
            Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 1),
            math.pi / 4 * 1,
            math.pi / 4 * 3,
        ),
        Part.ArcOfCircle(
            Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 1),
            math.pi / 4 * 5,
            math.pi / 4 * 7,
        ),
        Part.LineSegment(App.Vector(-1, 1, 0), App.Vector(-1, -1, 0)),
        Part.LineSegment(App.Vector(1, 1, 0), App.Vector(1, -1, 0)),
    ]
    sketch.addGeometry(new_geo, False)
    new_constraints = [
        Sketcher.Constraint("Coincident", last_geo_id + 0, 1, last_geo_id + 3, 1),
        Sketcher.Constraint("Coincident", last_geo_id + 0, 2, last_geo_id + 2, 1),
        Sketcher.Constraint("Coincident", last_geo_id + 1, 1, last_geo_id + 2, 2),
        Sketcher.Constraint("Coincident", last_geo_id + 1, 2, last_geo_id + 3, 2),
    ]
    sketch.addConstraint(new_constraints)
    last_c = len(sketch.Constraints)
    new_constraints = [
        Sketcher.Constraint("DistanceX", last_geo_id + 0, 1, 1),
        Sketcher.Constraint("DistanceX", last_geo_id + 1, 1, 1),
        Sketcher.Constraint("DistanceX", last_geo_id + 0, 2, 1),
        Sketcher.Constraint("DistanceX", last_geo_id + 1, 2, 1),
        Sketcher.Constraint("DistanceY", last_geo_id + 0, 1, 1),
        Sketcher.Constraint("DistanceY", last_geo_id + 0, 2, 1),
        Sketcher.Constraint("DistanceY", last_geo_id + 1, 1, -1),
        Sketcher.Constraint("DistanceY", last_geo_id + 1, 2, -1),
        Sketcher.Constraint("DistanceY", last_geo_id + 0, 3, 0),
        Sketcher.Constraint("DistanceY", last_geo_id + 1, 3, 0),
    ]
    sketch.addConstraint(new_constraints)
    y_offset_expr = f"sqrt(({size_outer_expr} / 2)^2 - ({size_inner_expr} / 2)^2)"
    sketch.setExpression(f"Constraints[{last_c + 0}]", f"{hole_loc.x_expr} + {size_inner_expr} / 2")
    sketch.setExpression(f"Constraints[{last_c + 1}]", f"{hole_loc.x_expr} - {size_inner_expr} / 2")
    sketch.setExpression(f"Constraints[{last_c + 2}]", f"{hole_loc.x_expr} - {size_inner_expr} / 2")
    sketch.setExpression(f"Constraints[{last_c + 3}]", f"{hole_loc.x_expr} + {size_inner_expr} / 2")
    sketch.setExpression(f"Constraints[{last_c + 4}]", f"{hole_loc.y_expr} + {y_offset_expr}")
    sketch.setExpression(f"Constraints[{last_c + 5}]", f"{hole_loc.y_expr} + {y_offset_expr}")
    sketch.setExpression(f"Constraints[{last_c + 6}]", f"{hole_loc.y_expr} - {y_offset_expr}")
    sketch.setExpression(f"Constraints[{last_c + 7}]", f"{hole_loc.y_expr} - {y_offset_expr}")
    sketch.setExpression(f"Constraints[{last_c + 8}]", f"{hole_loc.y_expr}")
    sketch.setExpression(f"Constraints[{last_c + 9}]", f"{hole_loc.y_expr}")
    sketch.recompute()


