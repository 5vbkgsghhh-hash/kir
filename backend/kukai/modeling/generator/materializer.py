"""Materializer (write-side): turn a generated SpatialModel into REAL Revit elements via the
op_revit operator channel. Python emits a self-contained C# body (coords inlined — no JSON
parsing in the sandbox) that, in ONE transaction, creates levels + boundary walls (one per unique
room edge) + placed, named Rooms + wall-hosted doors (on the edge each door sits on) + windows
(on an exterior edge of their room), collecting every created element id so the write is fully
REVERSIBLE (cleanup deletes exactly those ids).

SAFETY: only the operator-authorized device; geometry can be written to an isolated region (far
X/Z offset) or, for an empty scratch project, at the origin (x_off=0, z_off=0). Nothing is deleted.
NOTE: the live write must be run by the operator on the server (the agent's harness blocks writes
to the multi-tenant Revit endpoint); this module just builds the C# and runs it via op_revit.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile

VPY = "/opt/kukai-rebuild1/backend/venv/bin/python"
OP = "/opt/kukai-rebuild1/scripts/op_revit.py"
AUTHORIZED = {"a6d7d14340bc599817ae7e6896182ca0"}
X_OFFSET_MM = 300_000.0
Z_OFFSET_MM = 100_000.0
_FT = 304.8


def _mm(v: float) -> str:
    """mm -> Revit internal (feet) literal."""
    return repr(round(v / _FT, 6))


def _edge_key(p, q):
    a = (round(p[0], 1), round(p[1], 1))
    b = (round(q[0], 1), round(q[1], 1))
    return tuple(sorted([a, b]))


def _seg_contains(pt, p, q, tol: float = 90.0) -> bool:
    """True if pt lies on segment p->q (within tol mm)."""
    px, py = pt
    ax, ay = p
    bx, by = q
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(px - ax, py - ay) <= tol
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    if t < -0.05 or t > 1.05:
        return False
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy) <= tol


_NST = "Autodesk.Revit.DB.Structure.StructuralType.NonStructural"


def build_cs(model: dict, *, x_off: float = X_OFFSET_MM, z_off: float = Z_OFFSET_MM) -> str:
    """Emit the C# body that materializes `model`. Returns created ids + placed room names."""
    lines: list[str] = []
    a = lines.append
    a("var created = new List<object>();")
    a("var roomNames = new List<object>();")
    a("var wt = new FilteredElementCollector(doc).OfClass(typeof(WallType)).Cast<WallType>()"
      ".FirstOrDefault(t => t.Kind == WallKind.Basic);")
    a("if (wt == null) return new Dictionary<string,object>{{\"error\",true},{\"message\",\"no basic wall type\"}};")
    a("var dsym = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors)"
      ".WhereElementIsElementType().Cast<FamilySymbol>().FirstOrDefault();")
    a("var wsym = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Windows)"
      ".WhereElementIsElementType().Cast<FamilySymbol>().FirstOrDefault();")
    a("double H = " + _mm(3000.0) + ";")
    a("using (var t = new Transaction(doc, \"kukai materialize\")) {")
    a("t.Start();")
    a("if (dsym != null && !dsym.IsActive) dsym.Activate();")
    a("if (wsym != null && !wsym.IsActive) wsym.Activate();")

    # --- levels ---
    lvl_var: dict[str, str] = {}
    lvl_z: dict[str, float] = {}
    for i, lv in enumerate(model.get("levels", [])):
        v = f"lv{i}"
        lvl_var[lv["id"]] = v
        lvl_z[lv["id"]] = lv["elevation_mm"] + z_off
        a(f"var {v} = Level.Create(doc, {_mm(lv['elevation_mm'] + z_off)});")
        a(f"{v}.Name = {json.dumps('KUKAI ' + str(lv['name']) + ' ' + str(lv['id']))};")
        a(f"created.Add({v}.Id.ToString());")
    a("doc.Regenerate();")

    # --- collect unique edges per level + which rooms each edge touches ---
    edges_by_level: dict[str, dict] = {}
    edge_rooms: dict[tuple, list] = {}
    for r in model.get("rooms", []):
        lid = r["level_id"]
        b = r.get("boundary") or []
        if len(b) < 3:
            continue
        d = edges_by_level.setdefault(lid, {})
        n = len(b)
        for i in range(n):
            p, q = b[i], b[(i + 1) % n]
            ek = _edge_key(p, q)
            d.setdefault(ek, (p, q))
            edge_rooms.setdefault((lid, ek), []).append(r["id"])

    # --- walls (one per unique edge) ---
    edge_wall: dict[tuple, str] = {}
    wi = 0
    for lid, edict in edges_by_level.items():
        if lid not in lvl_var:
            continue
        for ek, (p, q) in edict.items():
            a(f"var w{wi} = Wall.Create(doc, Line.CreateBound("
              f"new XYZ({_mm(p[0] + x_off)},{_mm(p[1])},0), "
              f"new XYZ({_mm(q[0] + x_off)},{_mm(q[1])},0)), wt.Id, {lvl_var[lid]}.Id, H, 0, false, false);")
            a(f"created.Add(w{wi}.Id.ToString());")
            edge_wall[(lid, ek)] = f"w{wi}"
            wi += 1
    a("doc.Regenerate();")

    # --- rooms (placed at centroid, named) ---
    ri = 0
    for r in model.get("rooms", []):
        lid = r["level_id"]
        if lid not in lvl_var:
            continue
        b = r.get("boundary") or []
        if len(b) < 3:
            continue
        cx = sum(p[0] for p in b) / len(b) + x_off
        cy = sum(p[1] for p in b) / len(b)
        a(f"var r{ri} = doc.Create.NewRoom({lvl_var[lid]}, new UV({_mm(cx)}, {_mm(cy)}));")
        a(f"if (r{ri} != null) {{ r{ri}.Name = {json.dumps(str(r['name']))}; "
          # ceiling 3000mm: bind the upper limit to the room's own level + 3000 offset (HAB022)
          f"try {{ r{ri}.UpperLimit = {lvl_var[lid]}; r{ri}.LimitOffset = {_mm(3000.0)}; }} catch {{}} "
          f"created.Add(r{ri}.Id.ToString()); roomNames.Add(r{ri}.Name); }}")
        ri += 1
    a("doc.Regenerate();")

    # --- doors (wall-hosted on the edge the door sits on) ---
    di = 0
    for door in model.get("doors", []):
        lid = door.get("level_id")
        if lid not in lvl_var:
            continue
        loc = door.get("location") or [0.0, 0.0]
        host = None
        for ek, (p, q) in edges_by_level.get(lid, {}).items():
            if _seg_contains((loc[0], loc[1]), p, q):
                host = edge_wall.get((lid, ek))
                if host:
                    break
        if host is None:
            continue
        z = lvl_z[lid]
        a(f"if (dsym != null) {{ var d{di} = doc.Create.NewFamilyInstance("
          f"new XYZ({_mm(loc[0] + x_off)},{_mm(loc[1])},{_mm(z)}), dsym, {host}, {lvl_var[lid]}, {_NST}); "
          f"created.Add(d{di}.Id.ToString()); }}")
        di += 1

    # --- windows (on an exterior edge of the window's room; sill ~1 m) ---
    wii = 0
    rooms_by_id = {r["id"]: r for r in model.get("rooms", [])}
    for win in model.get("windows", []):
        rid = win.get("room_id")
        room = rooms_by_id.get(rid)
        if not room:
            continue
        lid = room["level_id"]
        if lid not in lvl_var:
            continue
        b = room.get("boundary") or []
        n = len(b)
        chosen = None
        for i in range(n):
            p, q = b[i], b[(i + 1) % n]
            ek = _edge_key(p, q)
            if len(edge_rooms.get((lid, ek), [])) == 1 and (lid, ek) in edge_wall:
                chosen = (ek, p, q)
                break
        if not chosen:
            continue
        ek, p, q = chosen
        host = edge_wall[(lid, ek)]
        mx = (p[0] + q[0]) / 2.0 + x_off
        my = (p[1] + q[1]) / 2.0
        z = lvl_z[lid] + 1000.0
        a(f"if (wsym != null) {{ var win{wii} = doc.Create.NewFamilyInstance("
          f"new XYZ({_mm(mx)},{_mm(my)},{_mm(z)}), wsym, {host}, {lvl_var[lid]}, {_NST}); "
          f"created.Add(win{wii}.Id.ToString()); }}")
        wii += 1

    a("doc.Regenerate();")
    a("t.Commit();")
    a("}")
    a("return new Dictionary<string,object>{{\"created\",created},{\"n_created\",created.Count},"
      "{\"room_names\",roomNames}};")
    return "\n".join(lines)


def _run(device: str, code: str, timeout_ms: int = 180000) -> dict:
    if device not in AUTHORIZED:
        raise PermissionError(f"device {device} not authorized")
    fd, path = tempfile.mkstemp(suffix=".cs", prefix="kukai_mat_")
    with os.fdopen(fd, "w") as fh:
        fh.write(code)
    try:
        p = subprocess.run([VPY, OP, "exec", device, "--code-file", path, "--timeout-ms", str(timeout_ms)],
                           capture_output=True, text=True, timeout=timeout_ms / 1000 + 40)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    r = json.loads(p.stdout)
    if r.get("status") != 200:
        raise RuntimeError(f"materialize exec failed: {json.dumps(r)[:400]}")
    return (r.get("body") or {}).get("result") or {}


def materialize(model: dict, device: str, *, x_off: float = X_OFFSET_MM,
                z_off: float = Z_OFFSET_MM) -> dict:
    """Create the model's geometry on `device`. Returns {created:[ids], ...}. Pass x_off=0,z_off=0
    to build at the origin (e.g. an empty scratch project)."""
    return _run(device, build_cs(model, x_off=x_off, z_off=z_off))


def cleanup(device: str, created_ids: list, timeout_ms: int = 120000) -> dict:
    """Delete exactly the elements created by a prior materialize() — leaves the model as found."""
    ids_csv = ",".join(str(i) for i in created_ids if str(i).lstrip("-").isdigit())
    code = (
        "var ids = new long[]{" + ids_csv + "};\n"
        "int n = 0;\n"
        "using (var t = new Transaction(doc, \"kukai cleanup\")) { t.Start();\n"
        "foreach (var idv in ids) { var e = doc.GetElement(new ElementId(idv)); "
        "if (e != null) { try { doc.Delete(e.Id); n++; } catch {} } }\n"
        "t.Commit(); }\n"
        "return new Dictionary<string,object>{{\"deleted\", n}};"
    )
    return _run(device, code)
