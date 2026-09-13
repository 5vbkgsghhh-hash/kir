"""Whole sandbox script: three-storey schematic section, not faithful refinement.

Inputs retain the conceptual twist as an explicitly inactive parameter. The
host/binder retains the historical refinement record; this script does not
invent provenance, invoke Revit, or load another generator from the repository.
"""
import math

project_id = param("project_id", "residential-foundation")
instance_key = param("instance_key", "tower-a")
ir_version = param("project_ir_version", "1.0")
intent = param("project_intent", "")
representation = param("representation", "section", choices=["section"])
x = param("x_mm", 0.0)
width = param("width_mm", 14000.0)
depth = param("depth_mm", 9000.0)
storeys = param("storeys", 3, min=3, max=3)
height = param("storey_height_mm", 4500.0)
setback = param("terrace_setback_mm", 1200.0)
twist_deg = param("twist_deg", 12.0, doc="Historical concept input, inactive in schematic section")

if (any(not math.isfinite(value) for value in (x, width, depth, height, setback, twist_deg))
        or min(width, depth, height) <= 0 or not 0 <= setback < width / 2):
    raise ValueError("invalid residential dimensions")
if width - setback <= 7000 or depth <= 5000:
    raise ValueError("shaft must be strictly inside every section floor")


def ring(current_width):
    return [[x, 0.0], [x + current_width, 0.0],
            [x + current_width, depth], [x, depth]]


program = {"ir_version": ir_version, "intent": intent, "ops": []}


def emit(key, operation, **fields):
    program["ops"].append({"op": operation,
                           "id": project_output_id(project_id, instance_key, key), **fields})


for number in range(1, storeys + 1):
    prefix = f"storey-{number:02d}"
    level_key = prefix + "-level"
    level_ref = {"by": "ref", "value": project_output_id(project_id, instance_key, level_key)}
    emit(level_key, "create_level", elev_mm=(number - 1) * height,
         name=f"{instance_key}: этаж {number}")
    corners = ring(width - (setback if number == storeys else 0))
    shaft = [[x + 5000, 3000], [x + 7000, 3000],
             [x + 7000, 5000], [x + 5000, 5000]]
    contour = {"outer": {"shape": "poly", "points_mm": corners},
               "holes": [{"shape": "poly", "points_mm": shaft}]}
    emit(prefix + "-slab", "create_floor_by_contour", contour=contour, level=level_ref)
    for side, (start, end) in enumerate(zip(corners, corners[1:] + corners[:1])):
        emit(prefix + f"-wall-{side}", "create_wall", p0_mm=start, p1_mm=end,
             height_mm=height, level=level_ref)
    emit(prefix + "-space", "create_room", xy=[x + 2500, 2000],
         name=f"{instance_key}: пространство {number}", level=level_ref)
