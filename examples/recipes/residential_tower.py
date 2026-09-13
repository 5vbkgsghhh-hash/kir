"""Whole sandbox script: one tapered/twisted conceptual native blend request.

This reproduces the original example's two-profile math. It does not claim
native blend equivalence to a mesh proxy or completed BIM semantics.
"""
import math

project_id = param("project_id", "residential-foundation")
instance_key = param("instance_key", "tower-b")
ir_version = param("project_ir_version", "1.0")
intent = param("project_intent", "")
representation = param("representation", "concept", choices=["concept"])
x = param("x_mm", 24000.0)
width = param("width_mm", 14000.0)
depth = param("depth_mm", 9000.0)
storeys = param("storeys", 8, min=1)
height = param("storey_height_mm", 4100.0)
setback = param("terrace_setback_mm", 900.0, doc="Retained section input; inactive in concept")
twist_deg = param("twist_deg", -24.0)

if (any(not math.isfinite(value) for value in (x, width, depth, height, setback, twist_deg))
        or min(width, depth, height) <= 0 or not 0 <= setback < width / 2
        or not math.isfinite(storeys * height)):
    raise ValueError("invalid residential dimensions")

footprint = [[x, 0.0], [x + width, 0.0], [x + width, depth], [x, depth]]
angle = math.radians(twist_deg)
cx, cy = x + width / 2, depth / 2
top = [[cx + 0.82 * ((px - cx) * math.cos(angle) - (py - cy) * math.sin(angle)),
        cy + 0.82 * ((px - cx) * math.sin(angle) + (py - cy) * math.cos(angle))]
       for px, py in footprint]
program = {"ir_version": ir_version, "intent": intent, "ops": [{
    "op": "create_solid_blend", "id": project_output_id(project_id, instance_key, "concept-volume"),
    "profile": {"outer": {"shape": "poly", "points_mm": footprint}},
    "profile_top": {"outer": {"shape": "poly", "points_mm": top}},
    "height_mm": storeys * height, "base_z_mm": 0,
    "category": "mass", "name": instance_key,
}]}
