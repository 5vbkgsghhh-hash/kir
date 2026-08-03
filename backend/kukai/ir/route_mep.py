"""route_mep — wave/mep support module for route_pipe_system / route_duct_system
(KIR CONNECT tiled onto full ВК/ОВ networks, 2026-07-17).

This module is MINE (wave/mep own zone): it does not touch connect.py,
ops_connect.py's siblings, or spec.py. It supplies exactly the two deltas the
CONNECT template (KIR_CONNECT_SPEC.md "Шаблон эмиттера") calls domain-specific
("Домен-специфика (Pipe vs Duct vs Conduit) = только имена типов Create/
Fitting; граф-логика общая") plus ONE extra thing the shared connect.py
graph_validate doesn't do: validate + carry the checked (non-generative)
slope_min_pct postcondition described in ops_connect.py's module docstring.

Reused from connect.py UNCHANGED (the hard-won, proven part): graph_validate
(connectivity BFS, degree cap, zero-edge/dup-edge/self-loop laws),
emit_fittings_cs (elbow/tee-by-degree, connector proximity), and
emit_connectivity_witness_cs (the live topology witness — already
domain-agnostic over MEPCurve/FamilyInstance, no changes needed).

NOT reused unchanged: connect.emit_segments_cs hardcodes
RBS_PIPE_DIAMETER_PARAM (correct for pipes, wrong/no-op for ducts — silently
swallowed by its own try/catch, meaning duct diameter would never actually
land on the element). emit_segments_route_cs below is the same shape with the
diameter BIP as a parameter, so duct diameter is genuinely set, not silently
dropped. See ops_connect.py's module docstring for why this file exists
instead of editing connect.py directly (that file is off-limits for this
wave).
"""
from __future__ import annotations

import json
import math
from typing import Optional

from kukai.ir.diag import Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS
from kukai.ir.emit_utils import (cs_line_comment_fragment,
                                 is_finite_number, refuse_stmt)

# Diagnostic code for a failed CHECKED (not generated) slope requirement.
# Filed alongside connect.py's own ad-hoc "KIR-L003" precedent (a code used
# directly by string literal in that module, not centrally registered in
# diag.py either) rather than inventing a new central constant for a
# wave-local, narrowly-scoped check.
SLOPE_TOO_SHALLOW = "KIR-L004"

_MIN_SLOPE_PCT, _MAX_SLOPE_PCT = 0.0, 100.0   # sanity bounds on the REQUIREMENT itself


def _num(x) -> bool:
    return is_finite_number(x)


def edge_key(a: str, b: str) -> str:
    """Canonical, ORDER-INDEPENDENT, JSON-safe edge key (a plain str, not a
    frozenset — frozenset dict keys blow up authoring.program_hash's
    json.dumps(..., sort_keys=True): json dict keys must be str/int/float/
    bool/None, and `default=str` only rescues values, never keys)."""
    x, y = sorted((a, b))
    # A delimiter cannot be made collision-free because node ids are
    # arbitrary strings. A two-item JSON array is injective and remains a
    # plain string key for program_hash/json.dumps.
    return json.dumps([x, y], ensure_ascii=False, separators=(",", ":"))


def extract_slope_requirements(op: dict, oid, diags: list) -> Optional[dict]:
    """Validates segments[].slope_min_pct (optional, checked-not-generated —
    see ops_connect.py module docstring) and returns {edge_key(a,b):
    slope_min_pct} or None with typed diagnostics on failure. Runs BEFORE
    connect.graph_validate against the RAW op (graph_validate's own strict
    segment-shape check is `set(seg) - {"from","to","diameter_mm"}` and would
    reject any segment carrying an extra slope_min_pct key) — so this wave's
    ground-hook calls this FIRST, then hands connect.graph_validate a
    slope-stripped copy of the op. See ground.py's route_pipe_system/
    route_duct_system branch.
    """
    segs_raw = op.get("segments")
    if not isinstance(segs_raw, list):
        return {}   # connect.graph_validate will raise the real typed error
    reqs: dict = {}
    for si, seg in enumerate(segs_raw):
        if not isinstance(seg, dict) or "slope_min_pct" not in seg:
            continue
        a, b = seg.get("from"), seg.get("to")
        v = seg.get("slope_min_pct")
        if not _num(v) or not (_MIN_SLOPE_PCT <= v <= _MAX_SLOPE_PCT):
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=f"segments[{si}].slope_min_pct",
                got=v, expected=f"{_MIN_SLOPE_PCT}..{_MAX_SLOPE_PCT}",
                message_ru=f"segments[{si}].slope_min_pct — процент 0..100"))
            return None
        if not isinstance(a, str) or not isinstance(b, str):
            # malformed from/to; connect.graph_validate will raise the typed
            # error for this — nothing more useful to say here.
            continue
        reqs[edge_key(a, b)] = float(v)
    return reqs


def strip_slope_keys(op: dict) -> dict:
    """Returns a shallow copy of op with segments[].slope_min_pct removed, so
    the result satisfies connect.graph_validate's closed segment-key set."""
    out = dict(op)
    segs = op.get("segments")
    if isinstance(segs, list):
        out["segments"] = [
            {k: v for k, v in seg.items() if k != "slope_min_pct"}
            if isinstance(seg, dict) else seg
            for seg in segs
        ]
    return out


# ── emit: domain-specific segment creation (the CONNECT template's declared
# per-domain delta — Create() call name + diameter BIP name only) ───────────

def emit_segments_route_cs(graph: dict, seg_var: str, create_call, sys_var: str,
                           type_var: str, lvl_var: str, cs_pt, cs_str,
                           diameter_bip: str,
                           isolation: str = "atomic") -> tuple[str, list]:
    """Same shape/contract as connect.emit_segments_cs (segment creation lines
    + (var, a, b, dia) metadata for fittings/witness), parametrized on the
    diameter BuiltInParameter so duct segments actually get their diameter
    set (RBS_CURVE_DIAMETER_PARAM) instead of silently no-op'ing on the
    pipe-only BIP connect.py hardcodes."""
    lines = []
    seg_meta = []
    for i, (a, b, dia) in enumerate(graph["edges"]):
        var = f"{seg_var}_{i}"
        pa, pb = graph["nodes"][a], graph["nodes"][b]
        lines.append(f"var {var} = {create_call(sys_var, type_var, lvl_var, cs_pt(pa), cs_pt(pb))};")
        lines.append(f"if ({var} == null) {{ {refuse_stmt('seg-' + str(i), cs_str('создание сегмента вернуло null'), isolation)} }}")
        if dia is not None:
            lines.append(f"try {{ var __d{i} = {var}.get_Parameter(BuiltInParameter.{diameter_bip}); "
                         f"if (__d{i} != null && !__d{i}.IsReadOnly) __d{i}.Set(U({dia})); }} catch {{ }}")
        seg_meta.append((var, a, b, dia))
    return "\n".join(lines), seg_meta


def emit_slope_witness_cs(seg_meta: list, slope_reqs: dict, oid, cs_str) -> str:
    """Checked (not generated) slope postcondition: for every segment whose
    edge carries a slope_min_pct requirement, read back its LIVE
    LocationCurve endpoints and verify |dz|/horizontal_run*100 >=
    slope_min_pct. horizontal_run == 0 (a vertical riser) with a slope floor
    requested is a typed refusal (a riser has no meaningful ВК/ОВ slope —
    KIR-L004), not a divide-by-zero or a silent pass."""
    if not slope_reqs:
        return ""
    lines = [f"// slope witness {cs_line_comment_fragment(oid)} (checked, not generated — see ops_connect.py note)"]
    for var, a, b, _dia in seg_meta:
        req = slope_reqs.get(edge_key(a, b))
        if req is None:
            continue
        lines.append(f"{{ var __slc = {var}.Location as LocationCurve;")
        lines.append(f"  if (__slc == null) __post.Add({cs_str(oid + ': ' + var + ' no curve for slope check')});")
        lines.append("  else {")
        lines.append("    var __sa = __slc.Curve.GetEndPoint(0); var __sb = __slc.Curve.GetEndPoint(1);")
        lines.append("    double __dz = Math.Abs(MM(__sb.Z) - MM(__sa.Z));")
        lines.append("    double __run = Math.Sqrt(Math.Pow(MM(__sb.X)-MM(__sa.X),2) + Math.Pow(MM(__sb.Y)-MM(__sa.Y),2));")
        lines.append(f"    if (__run < 1.0) __post.Add({cs_str(oid + ': ' + var + ': vertical riser, slope_min_pct undefined (KIR-L004)')});")
        lines.append(f"    else if ((__dz / __run * 100.0) < {req} - 1e-6)")
        lines.append(f"      __post.Add({cs_str(oid + ': ' + var + f': slope below required {req}% (KIR-L004)')});")
        lines.append("  } }")
    return "\n".join(lines)
