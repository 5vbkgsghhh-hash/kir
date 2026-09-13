#!/usr/bin/env python3
"""bounds_audit.py — a census of KIR's numeric bounds and a MEASUREMENT of their harm.

The tool answers one question about every bound in the compiler:
**how many REAL elements it rejects.**

Two sections:

* ``--census`` — the census: every numeric bound in the ``kukai/ir``
  package (op registry + module constants + witness tolerances), with its
  place of declaration. The verdict (MEASURED / ASSIGNED / UNCLEAR) is set
  by a human from the nearby comment; the tool gives the FULL list, so that
  "not found" cannot be mistaken for "there is none".
* ``--measure <dir>...`` — the measurement: from saved parses (L0.jsonl +
  side indices) it counts how many elements each measurable bound would
  have rejected.

THE MEASUREMENT REPRODUCES THE LIFTER'S PATH, IT DOES NOT APPROXIMATE IT.
The value checked against a bound is computed exactly the way
``decompile/lift.py`` computes it (``_bounded_param`` — an L0 parameter
directly; ``_bounded_number`` — a computed quantity: the projection onto
the wall's axis, the elevation from the HOST WALL's level, the curtain-cell
address). Otherwise the number would be measuring the instrument, not the
compiler.

Run (from backend/):
    PYTHONPATH=. venv/bin/python tools/bounds_audit.py --census
    PYTHONPATH=. venv/bin/python tools/bounds_audit.py --measure backend/data/decompile/k2_ar_rd_v7
    PYTHONPATH=. venv/bin/python tools/bounds_audit.py --measure-all
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import os
from kir import env  # noqa: E402  (a submodule with no dependencies — creates no import cycle)
import pathlib
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Iterable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kir import spec  # noqa: E402

# 🔴 THERE IS NO MORE DEFAULT VIA THE HOST'S PATH (28.08.2026). The literal
# `/opt/kukai-rebuild1/backend` used to stand here, and the
# `test_authority_boundaries` guard caught it rightfully: a package
# published separately has no right to carry the address of someone else's
# install inside it. An empty root is a NAMED absence, not a guess: whoever
# wants to measure the host's tree names it via the `KIR_HOST_ROOT`
# variable.
#
# 🔴 CORRECTION 30.08.2026 (a stranger's rig, `--measure-all`). "An empty
# root is a NAMED absence" was SAID, not DONE: the placeholder
# `"<корень хозяина не назван>"` is still a STRING, not a refusal. Nothing
# here stopped it from reaching `pathlib.Path(...).iterdir()` and landing
# in someone else's program as a raw `FileNotFoundError` — the same class
# as the old default path, just without an address inside it.
# `HOST_ROOT_KNOWN` is the one place where this KNOWLEDGE is read; `main()`
# must ask it BEFORE touching the filesystem (see `--measure-all` below),
# not after the filesystem call refuses on its own.
_HOST_ROOT_ENV = env.get("KIR_HOST_ROOT")
_BACKEND = pathlib.Path(_HOST_ROOT_ENV or "<корень хозяина не назван>")
HOST_ROOT_KNOWN = bool(_HOST_ROOT_ENV)
try:
    if (pathlib.Path(__file__).resolve().parent.parent
            / "pyproject.toml").is_file():
        _BACKEND = pathlib.Path(__file__).resolve().parent.parent
        HOST_ROOT_KNOWN = True
except OSError:
    pass
# 27.08.2026: KIR is a separate package; the root is asked of the package,
# not assembled from memory of a past layout.
import kir as _kir
IR_ROOT = pathlib.Path(_kir.__file__).resolve().parent
DATA_ROOT = _BACKEND / "backend" / "data" / "decompile"

# Names by which a module constant is counted as a BOUND or a TOLERANCE.
BOUNDISH = re.compile(
    r"TOL|LIMIT|MAX|MIN|MARGIN|EPS|THRESH|CAP|BUDGET|STEP|SIZE|COUNT|"
    r"_MM|_S$|_MS$|DEG|RATIO|FACTOR|BATCH|ROUNDS|SAMPLES|TOKENS|DECIMALS|"
    r"LEVELS|AXIS|OPS|ROW|ARRAY|COVERAGE|DEGREE|VERTICES|TRIANGLES|N_PBT",
)


# ─────────────────────────── CENSUS ────────────────────────────────────────

def registry_bounds() -> list[dict[str, Any]]:
    rows = []
    for op_name, op in sorted(spec.OPS.items()):
        for p in op.params:
            if p.min_val is None and p.max_val is None:
                continue
            rows.append({
                "where": "registry",
                "id": f"{op_name}.{p.name}",
                "kind": p.kind,
                "min": p.min_val,
                "max": p.max_val,
            })
    return rows


def registry_tolerances() -> list[dict[str, Any]]:
    rows = []
    for op_name, op in sorted(spec.OPS.items()):
        for key, value in sorted(op.tolerances.items()):
            rows.append({
                "where": "registry.tolerances",
                "id": f"{op_name}.{key}",
                "kind": "tolerance",
                "min": None,
                "max": value,
            })
    return rows


def module_constants() -> list[dict[str, Any]]:
    """All numeric constants of the package's modules (module/class/function scope)."""
    rows: list[dict[str, Any]] = []
    for path in sorted(IR_ROOT.rglob("*.py")):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(IR_ROOT.parent.parent))

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.scope: list[str] = []

            def visit_FunctionDef(self, node):  # noqa: N802
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node):  # noqa: N802
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            def record(self, node, names, value_node):
                if value_node is None:
                    return
                try:
                    value = ast.literal_eval(value_node)
                except Exception:
                    try:
                        value = eval(  # noqa: S307 - literal arithmetic only
                            compile(ast.Expression(value_node), "<c>", "eval"),
                            {"__builtins__": {}}, {})
                    except Exception:
                        # A THIRD KIND: a bound derived from ANOTHER bound
                        # (`_CONTOUR_MAX_POINTS = geom.MAX_RING_POINTS`,
                        # `MIN_RING_POINTS + 1`). It cannot be counted — it
                        # has no value of its own; but it cannot be SKIPPED
                        # either, and this is not nitpicking: the 10.08
                        # naming wave rewrote some literals into
                        # references, and an instrument that only knows
                        # `literal_eval` would have reported a SHRINKING of
                        # the surface where it simply gained an owner. An
                        # instrument that goes blind precisely from the fix
                        # it was built for is worse than none at all.
                        if isinstance(value_node, (ast.Name, ast.Attribute,
                                                   ast.BinOp)):
                            for name in names:
                                rows.append({
                                    "where": rel, "line": node.lineno,
                                    "scope": ".".join(self.scope), "id": name,
                                    "kind": "reference",
                                    "value": ast.unparse(value_node),
                                    "boundish": bool(BOUNDISH.search(name)),
                                })
                        return
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    return
                for name in names:
                    rows.append({
                        "where": rel,
                        "line": node.lineno,
                        "scope": ".".join(self.scope),
                        "id": name,
                        "kind": "constant",
                        "value": value,
                        "boundish": bool(BOUNDISH.search(name)),
                    })

            def visit_Assign(self, node):  # noqa: N802
                self.record(
                    node,
                    [t.id for t in node.targets if isinstance(t, ast.Name)],
                    node.value)
                self.generic_visit(node)

            def visit_AnnAssign(self, node):  # noqa: N802
                if isinstance(node.target, ast.Name):
                    self.record(node, [node.target.id], node.value)
                self.generic_visit(node)

        Visitor().visit(tree)
    return rows


# ─────────────────────────── READING THE PARSE ──────────────────────────────

class Dump:
    """A saved parse: L0 + side indices. Read-only."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.name = path.name
        self.header: dict[str, Any] = {}
        self.elements: list[dict[str, Any]] = []
        # 🔴 Via `snapshot_io`, not a bare `open` (19.08.2026): the cleaner
        # compresses `L0.jsonl` and five side indices, and on a
        # cooled-down parse the instrument would have said "zero bounds"
        # instead of "file compressed". Zero for a quantity the instrument
        # did not count here is a refusal of the instrument, not a
        # finding.
        # `touch=False` — otherwise the measurement would leave a
        # `.last_access` mark on the subject.
        # 🔴 A BROKEN L0 ROW IS COUNTED AND NAMED (04.09.2026, RT-10).
        # `except Exception: continue` used to stand here, and this is THE
        # SAME form already closed twice elsewhere in this file (`side`,
        # `scan_runs`): an element whose row failed to parse disappeared
        # FROM THE DENOMINATOR — that is, the share "the bound rejects N
        # of M" IMPROVED FROM LOSING DATA, and the report on the remainder
        # looked complete. Measured with a synthetic parse: three broken
        # rows — "1 element", not a word about the three.
        #
        # The answer is unchanged (a measurement over an incomplete L0
        # must not be dropped — refusing an entire building over one
        # broken row is worse), but the loss now has a NUMBER and a LINE
        # NUMBER, and `print_measurement` prints them BEFORE the numbers.
        #: line number -> why it is not a parse row.
        self.broken_lines: dict[int, str] = {}
        from kir.decompile.snapshot_io import open_snapshot
        with open_snapshot(path / "L0.jsonl", "rt",
                           encoding="utf-8", touch=False) as handle:
            for lineno, line in enumerate(handle, start=1):
                try:
                    record = json.loads(line)
                except Exception as exc:          # noqa: BLE001 — we do not blow up the measurement
                    self.broken_lines[lineno] = f"{type(exc).__name__}: {exc}"
                    continue
                if not isinstance(record, dict):
                    self.broken_lines[lineno] = (
                        f"строка разобралась, но это {type(record).__name__}, "
                        f"а не запись разбора")
                    continue
                kind = record.get("record")
                if kind == "header" or (not kind and "document" in record):
                    self.header = record.get("document", {})
                elif kind == "element":
                    # A row CLAIMED to be an element and carries none:
                    # before, this was a `KeyError` in the middle of
                    # reading — the other end of the same road: silence
                    # and a crash. The answer is one: count it.
                    element = record.get("element")
                    if isinstance(element, dict):
                        self.elements.append(element)
                    else:
                        self.broken_lines[lineno] = (
                            "record=element, но поля `element` нет "
                            "или оно не объект")
                elif "document" in record and not self.header:
                    self.header = record["document"]
        self.by_id = {e["element_id"]: e for e in self.elements}
        self.levels = {
            str(lv["id"]): lv for lv in (self.header.get("levels") or [])}
        self.rooms = self.header.get("rooms") or []
        self.grids = self.header.get("grids") or []
        self.doc_name = self.header.get("doc_name", path.name)
        #: side index -> why it EXISTS but did not read. Empty means
        #: everything that was there did read; a missing file does not
        #: land here, that is a different answer.
        self.side_refusals: dict[str, str] = {}
        #: side index -> why it is NOT PRESENT AT ALL. The second kind of
        #: silence in this class, and it is MORE COMMON than the first:
        #: measured 29.08.2026 on the live corpus — `annotation.index.json`
        #: is absent from 63 parses out of 81, `curtain.index.json` from
        #: 13, `sketch.index.json` from 11.
        self.side_absences: dict[str, str] = {}

    def side(self, filename: str) -> dict[str, Any]:
        # 🔴 A SIDE INDEX IS THE QUIETEST SPOT IN THIS CLASS: a compressed
        # file would read as MISSING, and `{}` is indistinguishable from
        # "the stage was never captured". Hence `snapshot_file_exists`,
        # which also asks about `.gz`.
        #
        # 🔴 HALF OF THIS WAS DONE, THE OTHER HALF WAS NOT (fix 29.08.2026,
        # F-130). The comment above NAMED the defect verbatim, and
        # `snapshot_file_exists` closed the branch of ABSENCE. But
        # `except Exception: return {}` one line below left the branch of
        # UNREADABILITY in exactly the same state: broken JSON, a
        # truncated gzip, and a permissions refusal all gave the same
        # `{}` as "the stage was never captured". An instrument claiming
        # coverage over real buildings would print "no one violates the
        # bound" exactly where there was simply nothing to measure it
        # with.
        #
        # `{}` is still returned — a measurement must not be dropped over
        # one broken index — but the reason is NOW RECORDED and printed in
        # a separate section of the report. "The answer does not change,
        # but the SILENCE gains a REASON that can be asked" — the law of
        # this tree, recorded in `install_paths.install_root_refusal`.
        #
        # 🔴 A CORRECTION TO THE PARAGRAPH ABOVE (fix 29.08.2026, phase 5).
        # "Closed the branch of ABSENCE" was SAID INCORRECTLY:
        # `snapshot_file_exists` closed only the confusion around a
        # COMPRESSED file (`.gz` now counts as existing), while the
        # silence itself remained — `{}` still meant, at once, "there are
        # no such objects in the building" and "the stage was never
        # captured". The second is MORE COMMON than the first on the live
        # corpus: `annotation.index.json` is missing from 63 parses out of
        # 81. The cost of this silence is worse than a zero in a cell:
        # `print_measurement` skips a `Result` with `denominator == 0`,
        # meaning a bound's row, readable ONLY from a side index,
        # disappeared from the report ENTIRELY — a silent VALUE became a
        # silent OMISSION. The absence branch now writes `side_absences`,
        # and the report names it BEFORE the numbers.
        from kir.decompile.snapshot_io import (
            open_snapshot, snapshot_file_exists)
        p = self.path / filename
        if not snapshot_file_exists(p):
            self.side_absences[filename] = (
                f"{filename} не лежит рядом с разбором: «стадия не "
                f"запускалась» и «индекс удалён» отсюда неотличимы")
            return {}
        try:
            with open_snapshot(p, "rt", encoding="utf-8",
                               touch=False) as handle:
                return json.load(handle)
        except Exception as exc:                  # noqa: BLE001 — we do not blow up the measurement
            self.side_refusals[filename] = f"{type(exc).__name__}: {exc}"
            return {}

    def of_category(self, *cats: str) -> Iterable[dict[str, Any]]:
        wanted = set(cats)
        for e in self.elements:
            if e.get("category") in wanted:
                yield e


# ─────────────────────────── MEASUREMENT ─────────────────────────────────────

def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


def _bound_of(op: str, param: str) -> tuple[float | None, float | None]:
    p = next(x for x in spec.OPS[op].params if x.name == param)
    return p.min_val, p.max_val


#: The default string ceiling. The ONE number in this file that has NO name
#: in the tree: `authoring_validation` writes it as a literal
#: (`cap = p.max_val if p.max_val is not None else 64`). It is named here,
#: rather than scattered across report rows: there is no one to ask, but
#: saying WHERE it comes from is still possible, and then the next move is
#: caught by a grep on a single spot.
_STR_CAP_DEFAULT = 64.0


def _str_cap(op: str, param: str) -> float:
    """The length ceiling of a string parameter — the SAME ONE the validator applies.

    An op is free to take a wider ceiling (`ParamSpec(..., max_val=N)`,
    `load_family.path`), and the instrument must follow the registry, not
    a memory of what the ceiling used to be.
    """
    p = next(x for x in spec.OPS[op].params if x.name == param)
    return float(p.max_val) if p.max_val is not None else _STR_CAP_DEFAULT


class Result:
    """One measured bound on one building.

    🔴 `unmeasured` is a NAMED UNMEASURABILITY (04.09.2026, RT-09). A
    report row where it is filled in speaks about REFUSALS, not about the
    quantity: this many objects the bound rejected, while the quantity
    that the bound compares against the threshold is unavailable to the
    instrument. Without this field, the row printed on a par with genuine
    measurements — "observed [0 … 1]" about a count of cells nobody
    counted.
    """

    def __init__(self, bound_id: str, bound_repr: str, *,
                 unmeasured: str = "") -> None:
        self.bound_id = bound_id
        self.bound_repr = bound_repr
        self.unmeasured = unmeasured
        self.denominator = 0     # how many elements are in scope at all
        self.below = 0
        self.above = 0
        self.worst_low: float | None = None
        self.worst_high: float | None = None
        self.observed_min: float | None = None
        self.observed_max: float | None = None

    def feed(self, value: float, lo: float | None, hi: float | None) -> None:
        self.denominator += 1
        self.observed_min = (value if self.observed_min is None
                             else min(self.observed_min, value))
        self.observed_max = (value if self.observed_max is None
                             else max(self.observed_max, value))
        if lo is not None and value < lo:
            self.below += 1
            self.worst_low = (value if self.worst_low is None
                              else min(self.worst_low, value))
        if hi is not None and value > hi:
            self.above += 1
            self.worst_high = (value if self.worst_high is None
                               else max(self.worst_high, value))

    @property
    def rejected(self) -> int:
        return self.below + self.above


def _param_bound(dump: Dump, out: dict[str, Result], *, categories: tuple[str, ...],
                 source: str, op: str, param: str) -> None:
    """Exactly the lift._bounded_param path: an L0 parameter's value against the bound."""
    lo, hi = _bound_of(op, param)
    key = f"{op}.{param}"
    res = out.setdefault(key, Result(key, f"[{lo}, {hi}]  ← L0 {source}"))
    for e in dump.of_category(*categories):
        value = _finite((e.get("params") or {}).get(source))
        if value is None:
            continue
        res.feed(value, lo, hi)


def _host_level_elev(dump: Dump, element: dict[str, Any]) -> float | None:
    host = dump.by_id.get(element.get("host_id") or "")
    if host is None:
        return None
    level = dump.levels.get(str(host.get("level_id") or ""))
    if level is None or not host.get("level_name"):
        return None
    return _finite(level.get("elevation_mm"))


def _hosted_sill(dump: Dump, element: dict[str, Any]) -> float | None:
    """lift._host_level_sill: the insert's z minus the elevation of the WALL's level."""
    p0 = element.get("p0_mm")
    if not (isinstance(p0, list) and len(p0) == 3):
        return None
    z = _finite(p0[2])
    elev = _host_level_elev(dump, element)
    if z is None or elev is None:
        return None
    sill = z - elev
    if -1.0 < sill < 0.0:          # the same clamp on sub-millimeter noise
        sill = 0.0
    return sill


def _hosted_offset(dump: Dump, element: dict[str, Any]) -> float | None:
    """lift._host_offset: the insert's projection onto the wall's axis (the straight case)."""
    host = dump.by_id.get(element.get("host_id") or "")
    if host is None or host.get("category") != "OST_Walls":
        return None
    hp0, hp1 = host.get("p0_mm"), host.get("p1_mm")
    p0 = element.get("p0_mm")
    if not all(isinstance(x, list) and len(x) >= 2 for x in (hp0, hp1, p0)):
        return None
    dx, dy = hp1[0] - hp0[0], hp1[1] - hp0[1]
    length = math.hypot(dx, dy)
    if length < 1.0:
        return None
    return ((p0[0] - hp0[0]) * dx + (p0[1] - hp0[1]) * dy) / length



from kir import geom as _geom          # the limit is queried, not rewritten
# 🔴 THE VALUE IS QUERIED FROM THE NAME — ALL OF IT, NOT THE ONE SOMEONE
# HAPPENED TO REMEMBER (04.09.2026, RT-08). On 02.09 this very file caught
# itself using `64` against `geom.MAX_RING_POINTS` and recorded the lesson
# verbatim; that fix closed ONE limit, while the same shape remained in
# neighboring rows and rotted the same way:
#
#     report row                       instrument said  name says    when it drifted
#     geom.MIN_RING_AREA_MM2           >= 10,000 mm²    100.0        21.08 (see test_opening.py:711)
#     mesh._COORD_MAX_MM               <= 10,000,000    16,000,000   25.08 (one home for the coordinate limit)
#
# The cost of the first row was measured with a synthetic parse: a ring of
# 400 mm² — LEGAL under the live law — the instrument declared rejected (1
# of 1), that is, a hundredth of the law printed as harm from the bound.
# The name IS the address: below there is not a single number that has a
# name in the tree.
from kir import authoring as _authoring    # _COORD_LIMIT_MM
from kir import contour as _contour        # MAX_ARC_BULGE, SHAPE_SIDE_MAX_MM
from kir import docspace as _docspace      # _SHEET_LIMIT_MM
from kir import macros as _macros          # MAX_STACK_LEVELS, MAX_GRID_AXIS
from kir import mesh as _mesh              # _COORD_MAX_MM


def measure_dump(dump: Dump) -> dict[str, Result]:
    out: dict[str, Result] = {}

    # ── 1. Registry bounds that the LIFTER applies to an L0 parameter ──────
    _param_bound(dump, out, categories=("OST_Walls",),
                 source="WALL_USER_HEIGHT_PARAM",
                 op="create_wall", param="height_mm")
    _param_bound(dump, out, categories=("OST_Walls",),
                 source="WALL_BASE_OFFSET",
                 op="create_wall", param="base_offset_mm")
    _param_bound(dump, out, categories=("OST_Walls",),
                 source="WALL_TOP_OFFSET",
                 op="create_wall", param="top_offset_mm")
    _param_bound(dump, out, categories=("OST_Floors",),
                 source="FLOOR_HEIGHTABOVELEVEL_PARAM",
                 op="create_floor", param="height_offset_mm")
    _param_bound(dump, out, categories=("OST_Ceilings",),
                 source="CEILING_HEIGHTABOVELEVEL_PARAM",
                 op="create_ceiling", param="height_offset_mm")
    _param_bound(dump, out, categories=("OST_StructuralColumns", "OST_Columns"),
                 source="FAMILY_BASE_LEVEL_OFFSET_PARAM",
                 op="create_column", param="base_offset_mm")
    _param_bound(dump, out, categories=("OST_StructuralColumns", "OST_Columns"),
                 source="FAMILY_TOP_LEVEL_OFFSET_PARAM",
                 op="create_column", param="top_offset_mm")
    _param_bound(dump, out, categories=("OST_PipeCurves",),
                 source="RBS_PIPE_DIAMETER_PARAM",
                 op="create_pipe", param="diameter_mm")
    _param_bound(dump, out, categories=("OST_DuctCurves",),
                 source="RBS_CURVE_DIAMETER_PARAM",
                 op="create_duct", param="diameter_mm")

    # ── 2. Registry bounds on a COMPUTED quantity (_bounded_number) ─────────
    for category, op in (("OST_Doors", "create_door"),
                         ("OST_Windows", "create_window")):
        lo_s, hi_s = _bound_of(op, "sill_mm")
        lo_o, hi_o = _bound_of(op, "offset_mm")
        ks = f"{op}.sill_mm"
        ko = f"{op}.offset_mm"
        rs = out.setdefault(ks, Result(
            ks, f"[{lo_s}, {hi_s}]  ← z вставки − отметка уровня стены"))
        ro = out.setdefault(ko, Result(
            ko, f"[{lo_o}, {hi_o}]  ← проекция вставки на ось стены"))
        for e in dump.of_category(category):
            sill = _hosted_sill(dump, e)
            # For a door, sill lands in the parameters only when
            # |sill| >= 1 mm.
            if sill is not None and (op == "create_window" or abs(sill) >= 1.0):
                rs.feed(sill, lo_s, hi_s)
            offset = _hosted_offset(dump, e)
            if offset is not None:
                ro.feed(offset, lo_o, hi_o)

    lo, hi = _bound_of("create_level", "elev_mm")
    res = out.setdefault("create_level.elev_mm", Result(
        "create_level.elev_mm", f"[{lo}, {hi}]  ← отметка уровня"))
    for level in dump.levels.values():
        value = _finite(level.get("elevation_mm"))
        if value is not None:
            res.feed(value, lo, hi)

    # set_curtain_panel.u/v — the cell address from the curtain-wall side index
    curtain = dump.side("curtain.index.json").get("curtain_index") or {}
    for axis in ("u", "v"):
        lo, hi = _bound_of("set_curtain_panel", axis)
        key = f"set_curtain_panel.{axis}"
        res = out.setdefault(key, Result(key, f"[{lo}, {hi}]  ← адрес ячейки"))
        for row in curtain.values():
            if not isinstance(row, dict) or not row.get("curtain_available"):
                continue
            for panel in row.get("panels") or []:
                value = _finite(panel.get(f"{axis}_index"))
                if value is not None:
                    res.feed(value, lo, hi)

    # ── 3. String ceilings: ONLY parameters of kind `str`. ─────────────────
    # Selectors (`{"by":"name","value":...}`) have NO ceiling — checked
    # against the `p.kind == "sel"` branch in authoring.py, which has no
    # length check. Measuring type_name's length against "64" would mean
    # measuring a bound that does not exist. The ceiling is queried FROM
    # THE REGISTRY (`_str_cap`), not written in three places: an op is
    # free to take a wider ceiling, and the instrument must follow it.
    _cap_lvl = _str_cap("create_level", "name")
    res_lvl = out.setdefault(f"create_level.name (str cap {_cap_lvl:g})", Result(
        "create_level.name", f"len <= {_cap_lvl:g}  ← имя уровня"))
    for level in dump.levels.values():
        n = level.get("name")
        if isinstance(n, str) and n:
            res_lvl.feed(float(len(n)), None, _cap_lvl)
    _cap_grid = _str_cap("create_grid", "name")
    res_grid = out.setdefault(f"create_grid.name (str cap {_cap_grid:g})", Result(
        "create_grid.name", f"len <= {_cap_grid:g}  ← имя оси"))
    for grid in dump.grids:
        n = grid.get("name")
        if isinstance(n, str) and n:
            res_grid.feed(float(len(n)), None, _cap_grid)
    _cap_room = _str_cap("create_room", "name")
    res_room = out.setdefault(f"create_room.name (str cap {_cap_room:g})", Result(
        "create_room.name", f"len <= {_cap_room:g}  ← имя помещения"))
    for room in dump.rooms:
        n = room.get("name")
        if isinstance(n, str) and n:
            res_room.feed(float(len(n)), None, _cap_room)

    # ── 4. Non-modular (constant) bounds that see data ──────────────────────
    # 4.1 contour limits: ring point count and area
    sketch = dump.side("sketch.index.json").get("profile_index") or {}
    res_pts = out.setdefault("lift._CONTOUR_MAX_POINTS", Result(
        "lift._CONTOUR_MAX_POINTS",
        f"len(ring) <= {_geom.MAX_RING_POINTS}  ← кольцо контура"))
    res_area = out.setdefault("geom.MIN_RING_AREA_MM2", Result(
        "geom.MIN_RING_AREA_MM2",
        f">= {_geom.MIN_RING_AREA_MM2:g} мм²  ← площадь кольца"))
    res_edge = out.setdefault("contour/_EDGE_TOL", Result(
        "contour/geom._EDGE_TOL",
        f">= {_geom._EDGE_TOL:g} мм  ← кратчайшее ребро кольца"))
    res_bulge = out.setdefault("contour.MAX_ARC_BULGE", Result(
        "contour.MAX_ARC_BULGE",
        f"|bulge| <= {_contour.MAX_ARC_BULGE:g}  ← дуга контура"))
    for row in sketch.values():
        if not isinstance(row, dict) or not row.get("profile_available"):
            continue
        rings = [row.get("exterior_loop") or []]
        rings.extend(row.get("holes") or [])
        for ring in rings:
            pts = [p for p in ring if isinstance(p, list) and len(p) >= 2]
            if len(pts) < 3:
                continue
            res_pts.feed(float(len(pts)), None, float(_geom.MAX_RING_POINTS))
            area2 = 0.0
            shortest = float("inf")
            for i in range(len(pts)):
                x0, y0 = float(pts[i][0]), float(pts[i][1])
                x1, y1 = float(pts[(i + 1) % len(pts)][0]), float(pts[(i + 1) % len(pts)][1])
                area2 += x0 * y1 - x1 * y0
                shortest = min(shortest, math.hypot(x1 - x0, y1 - y0))
            res_area.feed(abs(area2) / 2.0, _geom.MIN_RING_AREA_MM2, None)
            if math.isfinite(shortest):
                res_edge.feed(shortest, _geom._EDGE_TOL, None)
        # the bulge of profile arcs — the same formula as in
        # lift._bulge_from_midpoint
        loops = [row.get("exterior_loop") or []] + list(row.get("holes") or [])
        mids_all = row.get("arc_midpoints") or []
        for loop, mids in zip(loops, mids_all):
            pts = [p for p in loop if isinstance(p, list) and len(p) >= 2]
            if len(pts) < 3 or not isinstance(mids, list):
                continue
            for i, mid in enumerate(mids):
                if not (isinstance(mid, list) and len(mid) >= 2):
                    continue
                p0, p1 = pts[i % len(pts)], pts[(i + 1) % len(pts)]
                dx, dy = float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1])
                chord = math.hypot(dx, dy)
                if chord < 1e-9:
                    continue
                nx, ny = -dy / chord, dx / chord
                cx = (float(p0[0]) + float(p1[0])) / 2.0
                cy = (float(p0[1]) + float(p1[1])) / 2.0
                sagitta = -((float(mid[0]) - cx) * nx + (float(mid[1]) - cy) * ny)
                res_bulge.feed(abs(2.0 * sagitta / chord), None,
                               float(_contour.MAX_ARC_BULGE))

    # 4.1b Profile limits — NAMED since 10.08.2026 and declared once in
    # `geom` (`lift._lift_*_by_profile` reads them, rather than rewriting
    # them). The address is held by NAME, not by line number: notes like
    # "lift.py:1118-1120" stood here since 31.07 and by 10.08 pointed into
    # someone else's code — the same class as file:line in prose.
    # 🔴 THE LIMIT IS QUERIED FROM `geom`, NOT REWRITTEN AS A NUMBER
    # (02.09.2026). The literals `64.0`, `32.0`, `8.0` used to stand here —
    # in the `feed` thresholds, in row keys, and in descriptions — even
    # though the ADDRESS right next to them was correctly named
    # (`geom.MAX_RING_POINTS`). Naming the address and not asking it is
    # exactly the class this whole instrument is written against: on
    # 02.09 the limit was raised from 64 to 256, and the instrument kept
    # printing "<= 64  REJECTS 67" — that is, the harm of a limit that no
    # longer exists. The instrument was RIGHT about a subject that does
    # not exist.
    _g_holes, _g_hole_pts, _g_ext_pts = (
        float(_geom.MAX_HOLES), float(_geom.MAX_HOLE_RING_POINTS),
        float(_geom.MAX_RING_POINTS))
    res_holes = out.setdefault(f"lift: len(holes) <= {_geom.MAX_HOLES}", Result(
        "geom.MAX_HOLES  (lift._lift_floor_by_profile)",
        f"отверстий в профиле <= {_geom.MAX_HOLES}"))
    res_hole_pts = out.setdefault(
        f"lift: len(hole ring) <= {_geom.MAX_HOLE_RING_POINTS}", Result(
            "geom.MAX_HOLE_RING_POINTS",
            f"точек в отверстии <= {_geom.MAX_HOLE_RING_POINTS}"))
    res_ext_pts = out.setdefault(
        f"lift: len(exterior) <= {_geom.MAX_RING_POINTS}", Result(
            "geom.MAX_RING_POINTS",
            f"точек во внешнем кольце <= {_geom.MAX_RING_POINTS}"))
    for row in sketch.values():
        if not isinstance(row, dict) or not row.get("profile_available"):
            continue
        ext = row.get("exterior_loop") or []
        holes = row.get("holes") or []
        res_ext_pts.feed(float(len(ext)), None, _g_ext_pts)
        res_holes.feed(float(len(holes)), None, _g_holes)
        for hole in holes:
            res_hole_pts.feed(float(len(hole)), None, _g_hole_pts)

    # 4.1c macro limits, checked against the building's real geometry
    res_h = out.setdefault("macros.stack.h_mm", Result(
        "macros stack.h_mm [1000, 10000]", "высота этажа, мм"))
    elevations = sorted(
        v for v in (_finite(lv.get("elevation_mm")) for lv in dump.levels.values())
        if v is not None)
    for a, b in zip(elevations, elevations[1:]):
        delta = b - a
        if delta > 0.5:                      # we do not count duplicate elevations as a floor
            res_h.feed(delta, 1000.0, 10000.0)

    # The address is a NAME, not a file line: `contour.py:250` moved
    # (today it is `contour.SHAPE_SIDE_MAX_MM`, line 74), and a number
    # next to a stale address is exactly the shape this file has been
    # catching in itself since 10.08.
    res_rect = out.setdefault("contour.SHAPE_SIDE_MAX_MM", Result(
        "contour.SHAPE_SIDE_MAX_MM",
        f"габарит элемента <= {_contour.SHAPE_SIDE_MAX_MM:.0f} мм"))
    for e in dump.elements:
        lo_b, hi_b = e.get("bbox_min_mm"), e.get("bbox_max_mm")
        if not (isinstance(lo_b, list) and isinstance(hi_b, list)
                and len(lo_b) == 3 and len(hi_b) == 3):
            continue
        for i in range(2):
            span = _finite(hi_b[i]) or 0.0
            base = _finite(lo_b[i]) or 0.0
            res_rect.feed(abs(span - base), None,
                          float(_contour.SHAPE_SIDE_MAX_MM))

    # 🔴 THESE TWO HAVE NO NAME, AND THIS IS STATED, NOT HIDDEN: `120` in
    # `serving` and `64` for the string parameter are bare literals (the
    # `inline_literals` census counts them as exactly this third kind).
    # There is no one to ask; so a note stands next to the number, so the
    # reader does not mistake a literal for a queried value. The
    # `serving.py:964` address is REMOVED: it moved to 7148.
    res_doc = out.setdefault("serving: len(doc_name) <= 120", Result(
        "serving._doc_stamp  len(doc_name) <= 120  (литерал без имени)",
        "длина имени документа"))
    res_doc.feed(float(len(dump.doc_name)), None, 120.0)

    # 4.2 coordinate ceilings
    res_coord16 = out.setdefault("authoring._COORD_LIMIT_MM", Result(
        "authoring._COORD_LIMIT_MM",
        f"|коорд| <= {_authoring._COORD_LIMIT_MM:.0f} мм"))
    # Today both rows give ONE ceiling, and this is not a duplicate in the
    # report but a fact of the tree: `mesh._COORD_MAX_MM =
    # registry_base.COORD_LIMIT_MM`, the coordinate limit has one home
    # (`test_coordinate_limit_has_one_home`). If the names drift apart, the
    # rows will drift apart too, because they are queried BY NAME.
    res_coord10 = out.setdefault("mesh._COORD_MAX_MM", Result(
        "mesh._COORD_MAX_MM",
        f"|коорд| <= {_mesh._COORD_MAX_MM:.0f} мм"))
    for e in dump.elements:
        for key in ("p0_mm", "p1_mm", "bbox_min_mm", "bbox_max_mm"):
            v = e.get(key)
            if not isinstance(v, list):
                continue
            for component in v:
                value = _finite(component)
                if value is None:
                    continue
                res_coord16.feed(abs(value), None,
                                 float(_authoring._COORD_LIMIT_MM))
                res_coord10.feed(abs(value), None, float(_mesh._COORD_MAX_MM))

    # 4.3 the length limit of a host wall (create_door/window.offset_mm max)
    _offset_max = _bound_of("create_door", "offset_mm")[1]
    res_wall_len = out.setdefault("wall_length_vs_offset_max", Result(
        "wall_length_vs_offset_max",
        f"длина стены <= {float(_offset_max):.0f} мм  "
        f"← create_door.offset_mm max"))
    for e in dump.of_category("OST_Walls"):
        p0, p1 = e.get("p0_mm"), e.get("p1_mm")
        if not (isinstance(p0, list) and isinstance(p1, list)
                and len(p0) >= 2 and len(p1) >= 2):
            continue
        res_wall_len.feed(math.hypot(p1[0] - p0[0], p1[1] - p0[1]),
                          None, float(_offset_max))

    # 4.4 macro ceilings: floors and grids
    res_lv = out.setdefault("macros.MAX_STACK_LEVELS", Result(
        "macros.MAX_STACK_LEVELS",
        f"<= {_macros.MAX_STACK_LEVELS} этажей в одном stack"))
    res_lv.feed(float(len(dump.levels)), None, float(_macros.MAX_STACK_LEVELS))
    res_gr = out.setdefault("macros.MAX_GRID_AXIS", Result(
        "macros.MAX_GRID_AXIS",
        f"<= {_macros.MAX_GRID_AXIS} осей в одном grid"))
    res_gr.feed(float(len(dump.grids)), None, float(_macros.MAX_GRID_AXIS))

    # 4.5 text annotations: create_text.width_mm and the sheet limit
    ann = dump.side("annotation.index.json").get("text_note_index") or {}
    lo, hi = _bound_of("create_text", "width_mm")
    res_sheet = out.setdefault("docspace._SHEET_LIMIT_MM", Result(
        "docspace._SHEET_LIMIT_MM",
        f"|u|,|v| <= {_docspace._SHEET_LIMIT_MM:.0f} мм  ← точка вида"))
    res_sheet10k = out.setdefault("docspace._SHEET_LIMIT_MM (старое 10 000)", Result(
        "docspace._SHEET_LIMIT_MM (снятое значение 10 000)",
        "|u|,|v| <= 10 000 мм  ← точка вида"))
    for row in ann.values():
        at = row.get("at_view_mm") if isinstance(row, dict) else None
        if isinstance(at, list) and len(at) == 2:
            for component in at:
                value = _finite(component)
                if value is not None:
                    res_sheet.feed(abs(value), None,
                                   float(_docspace._SHEET_LIMIT_MM))
                    res_sheet10k.feed(abs(value), None, 10_000.0)

    # 4.6 WITNESS TOLERANCES — the flip side of a bound: they do not
    # reject the truth, they ACCEPT error. We count how many elements have
    # a tolerance eating more than a tenth of their own size: for such an
    # element the witness signs off on a match where the discrepancy is
    # visible to the eye. The size the tolerance is compared against is
    # THE ONE THE WITNESS READS: bbox_extents_witness checks ONLY X and Y
    # (it does not look at a slab's thickness at all), while endpoint_mm
    # checks a CURVE's endpoints, so the characteristic size there is
    # length, not a bounding-box extent.
    key = "допуск свидетеля bbox_mm=50 (пол/кровля/потолок)"
    res = out.setdefault(key, Result(
        key, "допуск <= 10% меньшей стороны В ПЛАНЕ (сторона >= 500 мм)"))
    for e in dump.of_category("OST_Floors", "OST_Roofs", "OST_Ceilings"):
        lo_b, hi_b = e.get("bbox_min_mm"), e.get("bbox_max_mm")
        if not (isinstance(lo_b, list) and isinstance(hi_b, list)
                and len(lo_b) == 3 and len(hi_b) == 3):
            continue
        spans = []
        for i in range(2):                    # ONLY X and Y
            a, b = _finite(lo_b[i]), _finite(hi_b[i])
            if a is None or b is None:
                spans = []
                break
            spans.append(abs(b - a))
        spans = [s for s in spans if s > 1e-6]
        if spans:
            res.feed(min(spans), 500.0, None)

    key = "допуск свидетеля endpoint_mm=5 (стена/труба/воздуховод)"
    res = out.setdefault(key, Result(
        key, "допуск <= 10% длины кривой (длина >= 50 мм)"))
    for e in dump.of_category("OST_Walls", "OST_PipeCurves", "OST_DuctCurves",
                              "OST_Conduit", "OST_CableTray"):
        p0, p1 = e.get("p0_mm"), e.get("p1_mm")
        if not (isinstance(p0, list) and isinstance(p1, list)
                and len(p0) == 3 and len(p1) == 3):
            continue
        length = math.dist(
            [float(c) for c in p0], [float(c) for c in p1])
        if length > 1e-6:
            res.feed(length, 50.0, None)

    # 4.7 rooms: margin _ROOM_INTERIOR_MARGIN_MM
    _measure_rooms(dump, out)

    return out


def _room_clearance(point, exterior, holes) -> float:
    """Distance to the nearest boundary; negative — outside the contour."""
    def seg_dist(px, py, ax, ay, bx, by) -> float:
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        if length2 <= 0.0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def inside(px, py, ring) -> bool:
        result = False
        n = len(ring)
        for i in range(n):
            ax, ay = ring[i]
            bx, by = ring[(i + 1) % n]
            if (ay > py) != (by > py):
                x = ax + (py - ay) * (bx - ax) / (by - ay)
                if x > px:
                    result = not result
        return result

    px, py = point
    best = min(
        seg_dist(px, py, *ring[i], *ring[(i + 1) % len(ring)])
        for ring in (exterior,) + tuple(holes)
        for i in range(len(ring)))
    if not inside(px, py, exterior):
        return -best
    for hole in holes:
        if inside(px, py, hole):
            return -best
    return best


def _measure_rooms(dump: Dump, out: dict[str, Result]) -> None:
    """Room-point search limits — BY CALLING THE LIFTER ITSELF.

    Approximating this logic by hand already turned out to be wrong: the
    first version counted the initial grid's ``count_x*count_y`` and got
    2..9 cells, whereas the ``_ROOM_INTERIOR_MAX_CELLS`` limit sits on the
    branch-and-bound TRAVERSAL COUNTER. That is why ``lift._room_interior_point``
    is called here, and the verdict is read off the refusal type.
    """
    from kir.decompile import lift as _lift

    res_margin = out.setdefault("lift._ROOM_INTERIOR_MARGIN_MM", Result(
        "lift._ROOM_INTERIOR_MARGIN_MM",
        "зазор точки помещения от границы >= 10 мм"))
    # 🔴 THE NUMBER OF CELLS THIS INSTRUMENT DOES NOT MEASURE, AND NOW SAYS
    # SO OUT LOUD (2026-09-04, RT-09). The row was called «клеток обхода
    # ветвей-и-границ <= 50 000» and printed «наблюдалось [0 … 1]»: the
    # number of lines in the body that count CELLS is zero — the outcome was
    # derived from the exception TEXT, and the report cell held a 0/1 flag.
    # The reader saw a measurement of a quantity where there was only a
    # refusal marker.
    #
    # It cannot be counted honestly by ANY method available from here, and
    # this is verified, not assumed: the real limit sits on the `visited`
    # counter inside `_room_interior_point` (`lift.py:3594`); it does not
    # escape outward either by return value or by exception. The SECOND
    # budget check (`count_x * count_y`, line 3551) is not it, and the first
    # edition of this instrument already bought a substitution of one for
    # the other (see the docstring below). Recomputing the traversal by hand
    # is a direct prohibition from the file header: "MEASUREMENT REPRODUCES
    # THE LIFTER'S PATH, IT DOES NOT APPROXIMATE IT."
    #
    # The row is therefore declared UNMEASURABLE and renamed to what it
    # actually counts: how many ROOMS the budget rejected. A judgment about
    # the quantity itself is not being passed off as a measurement.
    res_cells = out.setdefault("lift._ROOM_INTERIOR_MAX_CELLS", Result(
        "lift._ROOM_INTERIOR_MAX_CELLS",
        f"комнат, отвергнутых БЮДЖЕТОМ обхода "
        f"(предел {_lift._ROOM_INTERIOR_MAX_CELLS} клеток)",
        unmeasured=(
            "число клеток обхода не измеряется: счётчик `visited` живёт "
            "внутри `_room_interior_point` и наружу не выходит. Считается "
            "ТОЛЬКО признак отказа по тексту `_CannotLift`")))
    #: Rooms whose refusal the instrument did NOT RECOGNIZE. A `continue`
    #: used to stand here, and such a room disappeared from BOTH
    #: denominators at once — the share of both boundaries improved exactly
    #: because the refusal turned out to be unfamiliar.
    res_other = out.setdefault("room lift: отказ ДРУГОГО рода", Result(
        "lift._room_interior_point: отказ, не опознанный прибором",
        "комнат, чей отказ не разложен ни на бюджет, ни на запас",
        unmeasured=("это не граница, а ЗНАМЕНАТЕЛЬ двух соседних рядов: "
                    "такая комната не судится ни бюджетом, ни запасом")))
    res_ring = out.setdefault("room ring: >= 3 различных вершин", Result(
        "lift._clean_ring", ">= 3 различных вершин в кольце помещения"))

    for room in dump.rooms:
        loops = room.get("boundary_loops_mm") or []
        rings = []
        bad_ring = False
        for loop in loops:
            pts = [(float(p[0]), float(p[1]))
                   for p in loop if isinstance(p, list) and len(p) >= 2]
            while len(pts) > 1 and pts[0] == pts[-1]:
                pts = pts[:-1]
            if len(set(pts)) < 3:
                bad_ring = True
                continue
            rings.append(tuple(pts))
        res_ring.feed(0.0 if bad_ring else 1.0, 1.0, None)
        if not rings:
            continue

        def area_of(ring):
            a = 0.0
            for i in range(len(ring)):
                x0, y0 = ring[i]
                x1, y1 = ring[(i + 1) % len(ring)]
                a += x0 * y1 - x1 * y0
            return abs(a) / 2.0

        rings.sort(key=area_of, reverse=True)
        exterior, holes = rings[0], tuple(rings[1:])
        try:
            _lift._room_interior_point(exterior, holes)
        except Exception as exc:                       # _CannotLift
            detail = str(getattr(exc, "detail", exc))
            if "cell budget" in detail:
                res_cells.feed(1.0, None, 0.0)         # rejected by the limit
                res_margin.feed(1.0, 0.0, None)
                res_other.feed(0.0, None, 0.0)
            elif "clearance" in detail:
                res_margin.feed(-1.0, 0.0, None)       # rejected by the margin
                res_cells.feed(0.0, None, 0.0)
                res_other.feed(0.0, None, 0.0)
            else:
                # 🔴 USED TO BE `continue` (2026-09-04, RT-09). A room with
                # an unfamiliar refusal disappeared from the denominator of
                # BOTH boundaries, and the share of each grew because the
                # subject was lost. The verdict is unchanged — the room is
                # judged neither by the budget nor by the margin — but the
                # loss is now COUNTED and printed in its own row.
                res_other.feed(1.0, None, 0.0)
        else:
            res_margin.feed(1.0, 0.0, None)
            res_cells.feed(0.0, None, 0.0)
            res_other.feed(0.0, None, 0.0)


# ─────────────────────────── OUTPUT ──────────────────────────────────────────

# Width of the machine type. This is NOT a threshold chosen by someone, but
# the edge of the value range of the type itself: ElementId in Revit is
# int32, while the track identifier and the millisecond budget are int64.
# Such a number cannot be "moved": it is moved not by the author, but by
# the platform.
_TYPE_WIDTHS = {2**31 - 1, -(2**31), 2**63 - 1, -(2**63)}


def _modular_names(tree: ast.AST) -> set[str]:
    """Names whose value comes from the remainder of division (`n % 100`).

    Needed to tell a BOUNDARY apart from GRAMMAR. `11 <= last_two <= 14` in
    `name._russian_count` looks like a range, but the 11 and 14 there are a
    rule of Russian numeral grammar («11..14 плеч»), not a threshold that
    rejects something. A comparison against a remainder of division lives in
    the ring of residues; moving such a number means breaking the language,
    not weakening a check.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        value = getattr(node, "value", None)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
                value, ast.BinOp) and isinstance(value.op, ast.Mod):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            out.update(t.id for t in targets if isinstance(t, ast.Name))
    return out


def _is_modular(node: ast.AST, modular: set[str]) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return True
    return isinstance(node, ast.Name) and node.id in modular


def _calls_named(node: ast.AST, names: set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            attr = getattr(func, "attr", None) or getattr(func, "id", None)
            if attr in names:
                return True
    return False


def _mentions(node: ast.AST, needles: tuple[str, ...]) -> bool:
    for sub in ast.walk(node):
        name = None
        if isinstance(sub, ast.Name):
            name = sub.id
        elif isinstance(sub, ast.Attribute):
            name = sub.attr
        if name and any(n in name for n in needles):
            return True
    return False


def _not_a_bound(node: ast.Compare, value: Any, other: ast.AST,
                 modular: set[str]) -> str | None:
    """The FOURTH kind: a number in a comparison that is NOT a boundary.

    The census before 10.08 counted as a boundary everything standing to
    the right of `<`, and so it declared as boundaries the width of int64,
    the length of a hex digest, and the rule of Russian plural. This is not
    a nitpick about the report: as long as such numbers sit in the same
    list as real thresholds, "parsing the unnamed literals" means inventing
    a name for something that has no provenance — and a name without
    provenance is exactly as nameless, only longer.

    The trait of each kind is STRUCTURAL, not by a list of files, so that a
    new case of the same kind filters itself out.
    """
    # 1. Width of the machine type — moved by the platform, not the author.
    if value in _TYPE_WIDTHS:
        return "ширина типа"
    # 2. Grammar: the comparison lives in the ring of residues (`n % 100`).
    if _is_modular(node.left, modular) or any(
            _is_modular(c, modular) for c in node.comparators):
        return "грамматика"
    # 3. Chance: the threshold for random() is a WEIGHT in the gate
    #    generator's mix, not a boundary someone can violate.
    if _calls_named(node, {"random", "uniform"}):
        return "вес жребия"
    # 4. Revit version — a point on the release axis, not a magnitude threshold.
    if _mentions(node, ("revit_version", "version_int")):
        return "версия"
    # 5. ARITY and FORMAT: equality is never a boundary. `len(v)
    #    == 16` is a 4x4 matrix, `!= 6` is a six-number bbox, `== 64` is a
    #    hex encoding of sha256. Such a number describes the SHAPE of a
    #    value; it cannot be loosened or tightened, only have its format
    #    replaced wholesale.
    if all(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
        if _calls_named(node, {"len"}):
            return "арность/формат"
    return None


def inline_literals() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Numbers standing DIRECTLY IN A COMPARISON, unnamed: boundaries and
    non-boundaries.

    The third kind of boundary, and it cannot be skipped: `len(exterior) >
    64` in `lift.py` (line 1295 as of 10.08; in the 07 version of this file
    it was 1118 — an example of why an address is held by function name,
    not by line number) rejects tower elements SILENTLY, turning them into
    an atom, and this number has no name — no search over named constants
    would find it. Trivial 0/1/2/3 and −1 are dropped as structural
    (emptiness, uniqueness, dimensionality).

    Returns TWO lists, not one: real boundaries and those filtered out by
    provenance (see `_not_a_bound`). The filtered-out ones ARE PRINTED —
    «не нашёл» and «нет» must remain distinct facts.
    """
    trivial = {0, 1, 2, 3, -1, 0.0, 1.0}
    bounds: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for path in sorted(IR_ROOT.rglob("*.py")):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        lines = src.splitlines()
        rel = str(path.relative_to(IR_ROOT.parent.parent))
        modular = _modular_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left] + list(node.comparators)
            for operand in operands:
                if not (isinstance(operand, ast.Constant)
                        and isinstance(operand.value, (int, float))
                        and not isinstance(operand.value, bool)):
                    continue
                if operand.value in trivial:
                    continue
                row = {
                    "where": rel, "line": node.lineno,
                    "value": operand.value,
                    "source": lines[node.lineno - 1].strip()[:110],
                }
                reason = _not_a_bound(node, operand.value, operand, modular)
                if reason:
                    row["reason"] = reason
                    dropped.append(row)
                else:
                    bounds.append(row)
    return bounds, dropped


def print_census() -> None:
    reg = registry_bounds()
    tol = registry_tolerances()
    consts = module_constants()
    named = [c for c in consts if c["boundish"] and not c["scope"]]
    boundish = [c for c in named if c["kind"] == "constant"]
    derived = [c for c in named if c["kind"] == "reference"]
    other = [c for c in consts if not (c["boundish"] and not c["scope"])
             and c["kind"] == "constant"]

    print(f"РЕЕСТР: границ параметров {len(reg)}")
    for r in reg:
        print(f"  {r['id']:38s} {r['kind']:5s} [{r['min']}, {r['max']}]")
    print(f"\nРЕЕСТР: допусков свидетелей {len(tol)}")
    for r in tol:
        print(f"  {r['id']:38s} = {r['max']}")
    print(f"\nМОДУЛЬНЫЕ КОНСТАНТЫ, похожие на границу: {len(boundish)}")
    for c in boundish:
        print(f"  {c['where']:46s} :{c['line']:<5d} {c['id']:36s} = {c['value']}")
    print(f"\nИМЕНОВАННЫЕ ССЫЛКИ на другую границу (значения своего нет): "
          f"{len(derived)}")
    for c in derived:
        print(f"  {c['where']:46s} :{c['line']:<5d} {c['id']:36s} = {c['value']}")
    inline, dropped = inline_literals()
    print(f"\nБЕЗЫМЯННЫЕ ЧИСЛА-ГРАНИЦЫ (литерал прямо в сравнении): {len(inline)}")
    for c in inline:
        print(f"  {c['where']:46s} :{c['line']:<5d} {str(c['value']):>18s}  {c['source']}")
    print(f"\nВ СРАВНЕНИИ, НО ГРАНИЦЕЙ НЕ ЯВЛЯЕТСЯ: {len(dropped)}")
    for reason in sorted({c["reason"] for c in dropped}):
        same = [c for c in dropped if c["reason"] == reason]
        print(f"  — {reason}: {len(same)}")
        for c in same:
            print(f"      {c['where']:44s} :{c['line']:<5d} "
                  f"{str(c['value']):>20s}  {c['source'][:78]}")
    print(f"\nПРОЧИЕ ЧИСЛОВЫЕ КОНСТАНТЫ (не границы): {len(other)}")
    for c in other:
        scope = f"[{c['scope']}]" if c["scope"] else ""
        print(f"  {c['where']:46s} :{c['line']:<5d} {scope}{c['id']:34s} = {c['value']}")
    total = len(reg) + len(tol) + len(boundish) + len(derived) + len(inline)
    print(f"\nПОВЕРХНОСТЬ ГРАНИЦ: реестр {len(reg)} + допуски {len(tol)} "
          f"+ именованные константы {len(boundish)} + ссылки {len(derived)} "
          f"+ безымянные литералы {len(inline)} = {total}")
    print(f"(и ещё {len(other)} числовых констант, границами не являющихся; "
          f"отсеяно по происхождению из сравнений: {len(dropped)})")


def print_measurement(dumps: list[pathlib.Path]) -> None:
    per_building: dict[str, dict[str, Result]] = {}
    #: building -> {side index: reason unreadable}. Printed FIRST, before
    #: the numbers: «границу никто не нарушает» and «мерить было нечем»
    #: look the same, and telling them apart is the report's job, not the
    #: reader's.
    unread: dict[str, dict[str, str]] = {}
    #: building -> {side index: why it is ABSENT}. Separate from `unread`:
    #: «есть, но не прочёлся» and «нет вовсе» are different reader moves.
    absent: dict[str, dict[str, str]] = {}
    #: building -> {L0 line number: why it is not a decompile line}. The
    #: third kind of silence, and the most expensive one: a lost ELEMENT
    #: shrinks the denominator of EVERY boundary at once, and the share
    #: grows from the loss.
    broken: dict[str, dict[int, str]] = {}
    for path in dumps:
        dump = Dump(path)
        name = f"{dump.name} ({dump.doc_name})"
        per_building[name] = measure_dump(dump)
        if dump.side_refusals:
            unread[name] = dict(dump.side_refusals)
        if dump.side_absences:
            absent[name] = dict(dump.side_absences)
        if dump.broken_lines:
            broken[name] = dict(dump.broken_lines)

    if broken:
        total_broken = sum(len(v) for v in broken.values())
        print("=" * 100)
        print(f"🔴 СТРОКИ L0, КОТОРЫЕ НЕ ПРОЧЛИСЬ: {total_broken} "
              f"в {len(broken)} здании(ях) из {len(dumps)}")
        print("=" * 100)
        print("Элемент такой строки не попал НИ В ЧИСЛИТЕЛЬ, НИ В ЗНАМЕНАТЕЛЬ "
              "ни одной границы:\nдоли ниже сняты с того, что прочлось.")
        for name, lines in sorted(broken.items()):
            print(f"  {name}: строк {len(lines)}")
            for lineno, why in sorted(lines.items())[:5]:
                print(f"      L0.jsonl:{lineno}  {why[:96]}")
            if len(lines) > 5:
                print(f"      … и ещё {len(lines) - 5}")
        print()

    if unread:
        print("=" * 100)
        print("🔴 БОКОВЫЕ ИНДЕКСЫ, КОТОРЫЕ ЕСТЬ, НО НЕ ПРОЧЛИСЬ")
        print("=" * 100)
        print("Числа ниже сняты БЕЗ них. Пустая граница у такого здания "
              "означает «мерить было нечем», а не «никто не нарушает».")
        for name, refusals in sorted(unread.items()):
            for filename, why in sorted(refusals.items()):
                print(f"  {name:44s} {filename:28s} {why}")
        print()

    if absent:
        print("=" * 100)
        print("\U0001f534 БОКОВЫЕ ИНДЕКСЫ, КОТОРЫХ НЕТ РЯДОМ С РАЗБОРОМ")
        print("=" * 100)
        print("Ряды границ, читаемые ТОЛЬКО из них, ниже НЕ ПОЯВЯТСЯ вовсе: "
              "пропавший ряд молчит так же, как пропавшее число.")
        for name, missing in sorted(absent.items()):
            for filename, why in sorted(missing.items()):
                print(f"  {name:44s} {filename:28s} {why}")
        print()

    keys = sorted({k for r in per_building.values() for k in r})
    rows = []
    for key in keys:
        total_rej = 0
        buildings_hit = 0
        detail = []
        repr_ = ""
        for building, results in per_building.items():
            res = results.get(key)
            if res is None or res.denominator == 0:
                continue
            repr_ = res.bound_repr
            if res.rejected:
                buildings_hit += 1
                total_rej += res.rejected
            detail.append((building, res))
        rows.append((total_rej, buildings_hit, key, repr_, detail))

    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
    print("=" * 100)
    print("ЗАМЕР ГРАНИЦ ПО НАСТОЯЩИМ ЗДАНИЯМ")
    print("=" * 100)
    for total, hit, key, repr_, detail in rows:
        print(f"\n### {key}   {repr_}")
        # 🔴 UNMEASURABILITY IS DECLARED BEFORE THE NUMBERS AND INSTEAD OF A
        # RANGE (RT-09): «наблюдалось [0 … 1]» about a quantity nobody
        # counted reads as a measurement and is refuted only by reading the
        # code.
        unmeasured = next((r.unmeasured for _b, r in detail if r.unmeasured), "")
        if unmeasured:
            print(f"    ⚠ ВЕЛИЧИНА НЕ ИЗМЕРЯЕТСЯ: {unmeasured}")
        print(f"    ОТВЕРГНУТО ВСЕГО: {total}   зданий затронуто: {hit}")
        for building, res in detail:
            mark = "  ОТВЕРГАЕТ" if res.rejected else ""
            observed = ("диапазон не снят — величина не измеряется"
                        if res.unmeasured else
                        f"наблюдалось [{_fmt(res.observed_min)} … "
                        f"{_fmt(res.observed_max)}]")
            print(f"      {building:44s} {res.rejected:6d} / {res.denominator:<7d}"
                  f"  {observed}{mark}")
            if res.below:
                print(f"          ниже нижней границы: {res.below}, худшее {_fmt(res.worst_low)}")
            if res.above:
                print(f"          выше верхней границы: {res.above}, худшее {_fmt(res.worst_high)}")


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1e6 or (value and abs(value) < 1e-3):
        return f"{value:.4g}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def scan_runs(root: pathlib.Path) -> "tuple[list[pathlib.Path], dict[str, str]]":
    """Decompiles fit for measuring boundaries, AND THE REASONS the rest
    did not qualify.

    🔴 ONE TRAVERSAL — TWO ANSWERS, and this is not a convenience. The same
    loop used to live inside `main` and skipped directories with TWO silent
    `continue`s; the measurement's denominator quietly shrank, and the
    shares rode upward exactly because a source was not found (the same
    shape as F-129).

    The two skips are DIFFERENT, and they cannot be merged:
      · no L0.jsonl — this is not a decompile, it never asked to be in the
        denominator;
      · L0 exists, the header did not read — the decompile WAS SUPPOSED to
        go in and did not.
    The first is a fact about layout, the second about CORRUPTION, and
    their next move is different.

    The choice of the largest among same-named ones is left as before: by
    the raw file's bytes, with the same argument that stood here before the
    function was extracted.
    """
    from kir.decompile.snapshot_io import (
        gz_path, open_snapshot, snapshot_file_exists)

    seen: dict[str, pathlib.Path] = {}
    skipped: dict[str, str] = {}
    for d in sorted(root.iterdir()):
        l0 = d / "L0.jsonl"
        if not snapshot_file_exists(l0):
            skipped[d.name] = "нет L0.jsonl — каталог не разбор"
            continue
        try:
            with open_snapshot(l0, "rt", encoding="utf-8",
                               touch=False) as handle:
                header = json.loads(handle.readline())
        except Exception as exc:  # noqa: BLE001 — the reason travels to the reader
            skipped[d.name] = (f"L0 есть, но заголовок не прочёлся: "
                               f"{type(exc).__name__}: {exc}")
            continue
        name = header.get("document", {}).get("doc_name", d.name)
        # raw is deliberate: the cleaner already chose: RAW is specifically needed, so as not to read twice
        actual = l0 if l0.is_file() else gz_path(l0)
        size = actual.stat().st_size
        if name not in seen or size > seen[name].stat().st_size:
            seen[name] = actual
    return [p.parent for p in seen.values()], skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", action="store_true")
    parser.add_argument("--measure", nargs="*", default=None)
    parser.add_argument("--measure-all", action="store_true")
    args = parser.parse_args()

    if args.census:
        print_census()
    targets: list[pathlib.Path] = []
    if args.measure:
        targets = [pathlib.Path(p) for p in args.measure]
    elif args.measure_all:
        # 🔴 REFUSAL BY NAME BEFORE THE FILE SYSTEM (2026-08-30, another
        # person's bench). Without it, `DATA_ROOT` carried the placeholder
        # `<корень хозяина не назван>` straight into
        # `scan_runs -> Path.iterdir()`, and the other person got a raw
        # `FileNotFoundError` with that line INSTEAD OF an answer about the
        # cause. The chain is "lie silently -> lose silently -> name the
        # refusal -> finish the work": there is nothing to finish here —
        # without `KIR_HOST_ROOT` the corpus simply does not exist on this
        # machine — so the third step: name it BEFORE the access, with a
        # code distinct from both success (0) and gate findings (1) — the
        # same code `2` with which the neighboring instruments in this
        # directory already answer "nothing to judge by".
        if not HOST_ROOT_KNOWN:
            print(f"🔴 ОТКАЗ: корень дерева хозяина не назван — переменная "
                  f"KIR_HOST_ROOT не задана, и рядом с пакетом нет "
                  f"pyproject.toml (признак дерева разработки).")
            print(f"   --measure-all не может назвать каталог с разборами и "
                  f"НЕ подставляет вместо него заполнитель.")
            print(f"   Назвать корень:  KIR_HOST_ROOT=<путь к дереву хозяина> "
                  f"... -m kir.instruments.bounds_audit --measure-all")
            print(f"   Либо измерить явно названные разборы: "
                  f"--measure <каталог> [<каталог> ...]")
            return 2
        seen: dict[str, pathlib.Path] = {}
        # 🔴 A SECOND SPOT OF THE SAME CLASS IN THIS FILE, found by the
        # guard after I had declared the file fixed based on the first one.
        # Here the refusal would be QUIETER than the first: `exists()`
        # would return False on a compressed decompile, and it would
        # silently drop out of the boundary census — not a refusal, an
        # undercount.
        #
        # A BOUNDARY I AM NAMING, NOT FIXING: the size of a compressed file
        # and the size of a plain one are quantities of DIFFERENT units,
        # and choosing "the largest run" between them is unreliable. As
        # long as the corpus is homogeneous (0 of 75 compressed), this
        # settles nothing; in a mixed corpus the choice has to be made by
        # element count, not by bytes on disk.
        targets, skipped_runs = scan_runs(DATA_ROOT)
        if skipped_runs:
            print(f"🔴 В ЗНАМЕНАТЕЛЬ НЕ ВОШЛИ {len(skipped_runs)} каталог(ов) "
                  f"из {len(skipped_runs) + len(targets)}:")
            for _name, _why in sorted(skipped_runs.items()):
                print(f"   · {_name}: {_why}")
            print("   доли ниже сняты с того, что осталось")
    if targets:
        print_measurement(targets)
    if not args.census and not targets:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
