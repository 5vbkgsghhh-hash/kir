"""Subprocess-isolated CadQuery executor.

Why subprocess + not in-process eval:
1. CadQuery code from LLM is untrusted (even though Gemini is well-aligned,
   the prompt is user-influenced — treat as adversarial).
2. CadQuery imports take ~1.5s the first time; running in main process would
   make every chat turn pay that cost.
3. Subprocess gives a hard timeout via asyncio.wait_for. In-process Python
   has no clean way to kill an infinite loop.
4. Subprocess memory limits via resource.setrlimit (Linux only — best-effort).

Safety model:
- Uses asyncio.subprocess (the equivalent of execFileNoThrow in Node-land):
  argument list is passed as a vector, NOT a shell string. No shell injection
  surface.
- The Python interpreter path is fixed (sys.executable). User code is written
  to a tempfile and passed by path; arguments are not interpolated into a
  shell line.
- If we ever need stronger isolation (seccomp, namespaces): dockerize this.
"""
from __future__ import annotations

import asyncio
import logging
import os
import resource
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Hard caps — picked to prevent runaway resources without limiting legit work.
DEFAULT_TIMEOUT_S = 60.0
MAX_STL_BYTES = 10 * 1024 * 1024     # 10 MB — covers any reasonable family solid
MAX_OUTPUT_TRIANGLES = 100_000        # Revit TessellatedShapeBuilder handles ~50k cleanly
# Cadquery + numpy + ezdxf + OCP needs a LOT of virtual address space, easily
# over 2 GB even for tiny boxes. Set the cap high enough not to wedge legit
# work; the wall-clock timeout is the real protection against runaway code.
MAX_RSS_BYTES = 8 * 1024 * 1024 * 1024    # 8 GB virtual address cap


class CadQueryError(Exception):
    """Wraps any failure inside the subprocess (syntax, runtime, timeout, oversize)."""

    def __init__(self, message: str, kind: str = "runtime"):
        super().__init__(message)
        self.kind = kind          # "syntax" | "runtime" | "timeout" | "oversize" | "no_result"


@dataclass
class CadQueryPart:
    """One part of a multi-part result (from `cq.Assembly` or `result_parts` list).

    Both STL and STEP are produced per part. The handler picks one for dispatch:
    - STL → TessellatedShape via Roslyn C# (fast, faceted, every Revit version).
    - STEP → bridge `import_step` method (smoother NURBS curves, Revit 2024+).
    """
    name: str
    stl_bytes: bytes
    step_bytes: bytes = b""                                  # empty if STEP export failed (legit STEP files are >100B)
    color_rgb: tuple[float, float, float] | None = None     # 0..1 each, or None for default
    material_hint: str = ""                                  # e.g. "metal", "glass" — passed to Revit


@dataclass
class CadQueryResult:
    """Successful run output.

    `parts` is the canonical multi-part form. For single-result code the runner
    still populates parts=[CadQueryPart(name="solid", stl_bytes=...)] so the
    caller path stays uniform.

    `svg_preview` is a 2D isometric projection of the FULL combined result —
    rendered server-side via cq.exporters.export(..., '.svg'). Cheap (<50ms),
    small (~30 KB), and surfaces back to Gemini as a multimodal artifact so it
    can visually verify what it built before the next round.
    """
    parts: list[CadQueryPart]
    svg_preview: bytes               # SVG of combined geometry (may be empty if rendering failed)
    bbox_mm: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]   # ((xmin,xmax),(ymin,ymax),(zmin,zmax))
    stdout: str
    duration_s: float

    @property
    def stl_bytes(self) -> bytes:
        """Legacy single-STL accessor (concatenates parts implicitly — use parts[] directly for materials)."""
        # Note: real STL concat isn't valid (multiple solid blocks); use only when a single part is expected.
        return self.parts[0].stl_bytes if len(self.parts) == 1 else b""


# Template wrapping the user's CadQuery code. The wrapper:
#   1. Runs user code with cq pre-imported.
#   2. Discovers the result — supports three shapes:
#        a. `result = cq.Workplane(...).box(...)` — single solid.
#        b. `result = cq.Assembly().add(..., name=..., color=...)` — multi-part.
#        c. `result_parts = [{"name": "body", "solid": wp, "color": (r,g,b)}, ...]`
#           — explicit multi-part list (escape hatch when Assembly is awkward).
#   3. Writes each part's STL to ./parts/part_<i>.stl
#   4. Writes a combined SVG preview to ./preview.svg
#   5. Writes a manifest.json with parts metadata + bbox
#
# Output dir is sys.argv[1] (created by parent).
_WRAPPER_TEMPLATE = '''\
import sys
import os
import json
import traceback
import resource as _res

try:
    _res.setrlimit(_res.RLIMIT_AS, ({rss_cap}, {rss_cap}))
except (ValueError, OSError):
    pass

import cadquery as cq  # noqa: F401 — user code uses cq.*

_OUT_DIR = sys.argv[1]
_PARTS_DIR = os.path.join(_OUT_DIR, "parts")
_MANIFEST = os.path.join(_OUT_DIR, "manifest.json")
_PREVIEW = os.path.join(_OUT_DIR, "preview.svg")
os.makedirs(_PARTS_DIR, exist_ok=True)

try:
{user_code_indented}
except SystemExit:
    raise
except BaseException:
    print("--- CADQUERY USER CODE ERROR ---", file=sys.stderr)
    traceback.print_exc()
    sys.exit(2)


def _normalize_color(c):
    if c is None:
        return None
    if hasattr(c, "toTuple"):
        t = c.toTuple()
    elif isinstance(c, (tuple, list)):
        t = tuple(c)
    else:
        return None
    # Drop alpha if present, clamp 0..1
    r, g, b = t[0], t[1], t[2]
    return (max(0.0, min(1.0, float(r))),
            max(0.0, min(1.0, float(g))),
            max(0.0, min(1.0, float(b))))


def _shape_for_export(obj):
    """Return a cq.Shape (or Workplane) suitable for exportStl / bbox."""
    if hasattr(obj, "val"):                     # Workplane
        return obj.val()
    return obj                                  # Shape / Compound


def _collect_parts():
    """Inspect user namespace; return list[dict(name, shape, color)]."""
    ns = dict(locals())
    ns.update(globals())
    parts = []

    # (c) Explicit `result_parts = [...]`
    rp = ns.get("result_parts")
    if isinstance(rp, list) and rp:
        for i, p in enumerate(rp):
            if isinstance(p, dict) and "solid" in p:
                parts.append({{
                    "name": str(p.get("name") or f"part_{{i}}"),
                    "shape": _shape_for_export(p["solid"]),
                    "color": _normalize_color(p.get("color")),
                    "material_hint": str(p.get("material_hint") or ""),
                }})
            else:
                # Bare shape in the list — accept it.
                parts.append({{
                    "name": f"part_{{i}}",
                    "shape": _shape_for_export(p),
                    "color": None,
                    "material_hint": "",
                }})
        return parts

    # (b) cq.Assembly
    for vname in ("result", "model", "final", "output", "shape", "assembly", "asm"):
        v = ns.get(vname)
        if v is None:
            continue
        if isinstance(v, cq.Assembly):
            for child in v.children:
                if child.obj is None:
                    continue
                parts.append({{
                    "name": child.name or "part",
                    "shape": _shape_for_export(child.obj),
                    "color": _normalize_color(child.color),
                    "material_hint": "",
                }})
            if parts:
                return parts

    # (a) Single Workplane / Shape
    for vname in ("result", "model", "final", "output", "shape"):
        v = ns.get(vname)
        if v is not None and (hasattr(v, "val") or hasattr(v, "exportStl") or hasattr(v, "BoundingBox")):
            parts.append({{
                "name": vname,
                "shape": _shape_for_export(v),
                "color": None,
                "material_hint": "",
            }})
            return parts

    return []


_parts = _collect_parts()
if not _parts:
    print("CADQUERY ERROR: code did not produce a usable result. Assign the final "
          "Workplane/Shape to `result = ...`, or use cq.Assembly, or a "
          "`result_parts = [{{'name': ..., 'solid': ..., 'color': (r,g,b)}}, ...]` list.",
          file=sys.stderr)
    sys.exit(3)

# Export each part — STL (always) + STEP (best-effort; failure is non-fatal).
_manifest_parts = []
for _i, _p in enumerate(_parts):
    _stl_path = os.path.join(_PARTS_DIR, f"part_{{_i}}.stl")
    _step_path = os.path.join(_PARTS_DIR, f"part_{{_i}}.step")

    # STL — required (fallback path for older Revit versions / quick imports).
    try:
        _p["shape"].exportStl(_stl_path, tolerance={tol}, angularTolerance={angtol})
    except AttributeError:
        cq.exporters.export(_p["shape"], _stl_path, tolerance={tol}, angularTolerance={angtol})

    # STEP — best-effort. Preserves NURBS curves (lossless vs STL faceting).
    # Imported via Revit's ACIS/STEP translator on the bridge side (2024+).
    _step_ok = False
    try:
        cq.exporters.export(_p["shape"], _step_path)
        _step_ok = os.path.exists(_step_path) and os.path.getsize(_step_path) > 100
    except Exception as _step_err:
        print(f"STEP export failed for part {{_p['name']!r}} (non-fatal): {{_step_err}}", file=sys.stderr)
        _step_ok = False

    _manifest_parts.append({{
        "name": _p["name"],
        "stl_file": os.path.relpath(_stl_path, _OUT_DIR),
        "step_file": os.path.relpath(_step_path, _OUT_DIR) if _step_ok else None,
        "color": list(_p["color"]) if _p["color"] else None,
        "material_hint": _p["material_hint"],
    }})

# Combined bbox.
_combined_bbox = None
try:
    _xmin, _ymin, _zmin = float("inf"), float("inf"), float("inf")
    _xmax, _ymax, _zmax = float("-inf"), float("-inf"), float("-inf")
    for _p in _parts:
        _bb = _p["shape"].BoundingBox()
        _xmin = min(_xmin, _bb.xmin); _xmax = max(_xmax, _bb.xmax)
        _ymin = min(_ymin, _bb.ymin); _ymax = max(_ymax, _bb.ymax)
        _zmin = min(_zmin, _bb.zmin); _zmax = max(_zmax, _bb.zmax)
    _combined_bbox = [[_xmin, _xmax], [_ymin, _ymax], [_zmin, _zmax]]
except Exception:
    pass

# Combined SVG preview (isometric) of the FIRST shape — sufficient as thumbnail.
# For multi-part: render the first part; details on others come via the next
# refinement turn if user wants.
try:
    cq.exporters.export(_parts[0]["shape"], _PREVIEW, opt={{"width": 600, "height": 400}})
except Exception as _e:
    # Preview is best-effort; never fail the whole job because of it.
    print(f"SVG preview failed (non-fatal): {{_e}}", file=sys.stderr)

# Manifest
with open(_MANIFEST, "w") as _f:
    json.dump({{
        "parts": _manifest_parts,
        "bbox_mm": _combined_bbox,
    }}, _f)

print(f"OK: parts={{len(_manifest_parts)}}, preview_exists={{os.path.exists(_PREVIEW)}}, bbox={{_combined_bbox}}")
'''


def _build_script(user_code: str, *, tol: float, angtol: float, rss_cap: int) -> str:
    indented = "\n".join("    " + line if line.strip() else line
                         for line in user_code.splitlines())
    return _WRAPPER_TEMPLATE.format(
        user_code_indented=indented,
        tol=tol,
        angtol=angtol,
        rss_cap=rss_cap,
    )


async def run(
    user_code: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    stl_tolerance: float = 0.1,
    stl_angular_tolerance: float = 0.1,
    python_exe: Optional[str] = None,
    rss_cap: int = MAX_RSS_BYTES,
) -> CadQueryResult:
    """Run user-supplied CadQuery code, return parts + SVG preview + bbox.

    The result canonically uses `parts` even when the user code produced a
    single Workplane — callers can iterate `result.parts` uniformly.

    Raises CadQueryError on any failure path. Captures stdout/stderr for
    surfacing back to the LLM so it can debug its own code.
    """
    if not user_code or not user_code.strip():
        raise CadQueryError("empty CadQuery code", kind="syntax")

    python_exe = python_exe or sys.executable

    script_body = _build_script(
        user_code,
        tol=stl_tolerance,
        angtol=stl_angular_tolerance,
        rss_cap=rss_cap,
    )

    with tempfile.TemporaryDirectory(prefix="kuki_cq_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        script_path = tmpdir / "cq_script.py"
        out_dir = tmpdir / "out"
        out_dir.mkdir(exist_ok=True)
        script_path.write_text(script_body, encoding="utf-8")

        start = asyncio.get_running_loop().time()
        run_args = [python_exe, str(script_path), str(out_dir)]
        proc = await asyncio.subprocess.create_subprocess_exec(
            run_args[0], *run_args[1:],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(tmpdir),
            env={"PATH": os.environ.get("PATH", ""),
                 "PYTHONIOENCODING": "utf-8"},
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
            raise CadQueryError(
                f"CadQuery subprocess exceeded {timeout_s}s timeout",
                kind="timeout",
            )

        duration = asyncio.get_running_loop().time() - start
        stdout = stdout_b.decode("utf-8", "replace")
        stderr = stderr_b.decode("utf-8", "replace")

        if proc.returncode != 0:
            tail = stderr[-1500:] if len(stderr) > 1500 else stderr
            kind = {
                2: "runtime",
                3: "no_result",
                4: "no_result",
                5: "runtime",
            }.get(proc.returncode, "runtime")
            raise CadQueryError(
                f"CadQuery exited with code {proc.returncode}.\n{tail}",
                kind=kind,
            )

        manifest_path = out_dir / "manifest.json"
        if not manifest_path.exists():
            raise CadQueryError(
                "Subprocess succeeded but produced no manifest — code path "
                "may have exited early. stdout: " + stdout[-500:],
                kind="no_result",
            )

        import json as _json
        manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))

        parts: list[CadQueryPart] = []
        total_size = 0
        for entry in manifest.get("parts", []):
            stl_file = out_dir / entry["stl_file"]
            if not stl_file.exists():
                continue
            blob = stl_file.read_bytes()
            total_size += len(blob)
            if total_size > MAX_STL_BYTES:
                raise CadQueryError(
                    f"Combined STL output exceeds {MAX_STL_BYTES} bytes — "
                    f"raise tolerance or simplify the model.",
                    kind="oversize",
                )
            # STEP is optional — present when CadQuery export succeeded.
            step_bytes = b""
            step_rel = entry.get("step_file")
            if step_rel:
                step_file = out_dir / step_rel
                if step_file.exists():
                    step_bytes = step_file.read_bytes()
            color = entry.get("color")
            parts.append(CadQueryPart(
                name=entry.get("name") or "part",
                stl_bytes=blob,
                step_bytes=step_bytes,
                color_rgb=tuple(color) if color else None,
                material_hint=entry.get("material_hint") or "",
            ))

        if not parts:
            raise CadQueryError("Subprocess emitted no usable parts.", kind="no_result")

        preview_path = out_dir / "preview.svg"
        svg_preview = preview_path.read_bytes() if preview_path.exists() else b""

        bbox_raw = manifest.get("bbox_mm") or [[0, 0], [0, 0], [0, 0]]
        bbox = (
            (float(bbox_raw[0][0]), float(bbox_raw[0][1])),
            (float(bbox_raw[1][0]), float(bbox_raw[1][1])),
            (float(bbox_raw[2][0]), float(bbox_raw[2][1])),
        )

        return CadQueryResult(
            parts=parts,
            svg_preview=svg_preview,
            bbox_mm=bbox,
            stdout=stdout,
            duration_s=duration,
        )


# Legacy alias — keep until callers migrate to `run`.
run_to_stl = run


def _suppress_unused_warning_for_resource() -> None:
    # `resource` is used inside the wrapper template string — keep the import
    # active to avoid lint flagging it as unused while preventing a noqa that
    # would hide future genuine issues.
    _ = resource.RLIMIT_AS
