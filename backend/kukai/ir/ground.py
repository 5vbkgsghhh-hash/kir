"""KIR ground stage — selector resolution against a model snapshot (SPEC §5, R4).

The create_element GROUND discipline, generalized: *no ungrounded C# is ever
emitted*. Every Sel<K> resolves to a pinned ElementId here, in ONE pass over a
snapshot (census-style dict; at serving time built from one batched bridge
round-trip — this module never talks to the bridge itself, which keeps it
fully testable with fixtures).

Resolution rules (silent-fallback ban, SPEC §2):
  by=element_id  -> pinned as-is (existence re-checked by the emitted
                    null-guard: model may drift between ground and execute).
  by=name        -> exact match after trim; if none, ONE case-insensitive
                    match is accepted; zero -> NOT_FOUND with the 5 nearest
                    names as candidates; several -> AMBIGUOUS with candidates.
  by=default     -> only where the op declares a deterministic rule:
                      * wall.type: doc default wall type, resolved IN-EMIT via
                        GetDefaultElementTypeId (echoed in the witness readback);
                      * pipe.system_type / pipe.pipe_type: the SOLE snapshot
                        entry; more than one -> AMBIGUOUS (never "first").
                    Every default resolution is echoed in the grounding record.

Snapshot shape: {"levels": [{"id": int, "name": str}, ...],
                 "wall_types": [...], "pipe_types": [...],
                 "piping_system_types": [...]}
"""
from __future__ import annotations

import difflib
import math
from typing import Any, Optional

from kukai.ir import spec
from kukai.ir.diag import Diagnostic, KirRefusal, GROUND_BAD_SELECTOR
from kukai.ir.emit_utils import ELEMENT_ID_MAX

GROUND_NOT_FOUND = "KIR-G101"
GROUND_AMBIGUOUS = "KIR-G102"
GROUND_NO_SNAPSHOT = "KIR-G103"
GROUND_EMPTY_POOL = "KIR-G104"
GROUND_BAD_SNAPSHOT = "KIR-G106"

# Sentinel a grounded op carries when the default is resolved in-emit
# (wall type via GetDefaultElementTypeId) rather than from the snapshot.
IN_EMIT_DEFAULT = "__doc_default__"
_MISSING = object()


def _validate_snapshot_pool(snapshot: dict, pool_name: str,
                            diags: list[Diagnostic]) -> list[dict]:
    """Return structurally safe rows for one externally supplied pool.

    The census is a bridge result, not trusted compiler state.  A malformed
    row must become a typed grounding refusal rather than an AttributeError,
    ValueError, or an out-of-range ElementId literal during emission.
    Category-specific extra fields (grid endpoints) are deliberately kept;
    their consumers validate those fields when needed.
    """
    raw = snapshot.get(pool_name)
    if raw is None:
        return []
    if not isinstance(raw, list):
        diags.append(Diagnostic(
            code=GROUND_BAD_SNAPSHOT, field_name=pool_name,
            expected="список строк {id, name}", got=type(raw).__name__,
            message_ru=f"снапшот: пул {pool_name} должен быть списком"))
        return []
    rows: list[dict] = []
    seen_ids: set[int] = set()
    for index, row in enumerate(raw):
        field = f"{pool_name}[{index}]"
        if not isinstance(row, dict):
            diags.append(Diagnostic(
                code=GROUND_BAD_SNAPSHOT, field_name=field,
                expected="{id, name}", got=type(row).__name__,
                message_ru=f"снапшот: {field} должен быть объектом"))
            continue
        element_id, name = row.get("id"), row.get("name")
        if (isinstance(element_id, bool) or not isinstance(element_id, int)
                or not (1 <= element_id <= ELEMENT_ID_MAX)):
            diags.append(Diagnostic(
                code=GROUND_BAD_SNAPSHOT, field_name=f"{field}.id",
                expected=f"целое 1..{ELEMENT_ID_MAX}", got=element_id,
                message_ru=f"снапшот: {field}.id — положительный 64-битный ElementId"))
            continue
        if not isinstance(name, str):
            diags.append(Diagnostic(
                code=GROUND_BAD_SNAPSHOT, field_name=f"{field}.name",
                expected="строка", got=type(name).__name__,
                message_ru=f"снапшот: {field}.name должен быть строкой"))
            continue
        if pool_name == "family_symbols":
            family_fields = ("category", "family_name", "type_name")
            # Legacy name/element-id selectors remain valid against old
            # snapshots. Once any v1.1 identity field is present, however,
            # the triple is inseparable and must be fully well-formed.
            bad_family_field = next((
                key for key in family_fields
                if any(candidate in row for candidate in family_fields)
                and (not isinstance(row.get(key), str)
                     or not row[key].strip())
            ), None)
            if bad_family_field is not None:
                diags.append(Diagnostic(
                    code=GROUND_BAD_SNAPSHOT,
                    field_name=f"{field}.{bad_family_field}",
                    expected="непустая строка",
                    got=row.get(bad_family_field),
                    message_ru=(f"снапшот: {field}.{bad_family_field} "
                                "обязателен для family selector")))
                continue
        params = row.get("params")
        if params is not None and (
                not isinstance(params, dict)
                or not all(isinstance(key, str) for key in params)):
            diags.append(Diagnostic(
                code=GROUND_BAD_SNAPSHOT, field_name=f"{field}.params",
                expected="объект {имя параметра: значение}",
                got=type(params).__name__,
                message_ru=(f"снапшот: {field}.params должен быть объектом "
                            "со строковыми именами параметров")))
            continue
        if element_id in seen_ids:
            diags.append(Diagnostic(
                code=GROUND_BAD_SNAPSHOT, field_name=f"{field}.id", got=element_id,
                message_ru=f"снапшот: ElementId {element_id} повторяется в пуле {pool_name}"))
            continue
        seen_ids.add(element_id)
        rows.append(row)
    return rows


def _nearest(name: str, pool: list[dict]) -> list[str]:
    names = [str(p.get("name", "")) for p in pool]
    return difflib.get_close_matches(name, names, n=5, cutoff=0.0)


def _disambiguator(sel: dict, op_index: int, op_id: str, param: str,
                   diags: list[Diagnostic]) -> Optional[dict]:
    """Return a normalized disambiguator, or None.

    ``None`` means either "not requested" or "malformed and diagnosed".  The
    latter is safe because the caller sees the appended typed diagnostic and
    the ground stage refuses the complete program.
    """
    raw = sel.get("disambiguate_by")
    if raw is None:
        return None
    if sel.get("by") not in ("name", "default"):
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
            field_name=f"{param}.disambiguate_by", got=raw,
            message_ru="disambiguate_by допустим только для name/default"))
        return None
    if not isinstance(raw, dict) or set(raw) != {"param", "value"}:
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
            field_name=f"{param}.disambiguate_by",
            expected={"param": "непустое имя", "value": "скаляр"}, got=raw,
            message_ru="disambiguate_by — объект {param, value}"))
        return None
    pname, value = raw.get("param"), raw.get("value")
    scalar = (value is None or isinstance(value, (str, bool, int, float)))
    if (not isinstance(pname, str) or not pname.strip() or not scalar
            or (isinstance(value, float) and not math.isfinite(value))):
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
            field_name=f"{param}.disambiguate_by",
            expected={"param": "непустое имя", "value": "JSON-скаляр"}, got=raw,
            message_ru="disambiguate_by требует имя параметра и конечное скалярное значение"))
        return None
    return {"param": pname.strip(), "value": value}


def _parameter_equals(actual: Any, expected: Any) -> bool:
    """Exact, non-coercive equality for externally supplied parameter data."""
    if isinstance(actual, dict):
        # The bridge may preserve both a typed/raw value and Revit's display
        # string for unit-bearing parameters.  Either representation must
        # still match exactly; no locale parsing or unit guessing happens here.
        return any(_parameter_equals(actual[key], expected)
                   for key in ("value", "raw", "display") if key in actual)
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if (isinstance(actual, (int, float))
            and isinstance(expected, (int, float))):
        return (not isinstance(actual, bool) and not isinstance(expected, bool)
                and math.isfinite(float(actual))
                and math.isfinite(float(expected))
                and actual == expected)
    return type(actual) is type(expected) and actual == expected


def _narrow_by_parameter(pool: list[dict], disambiguate_by: Optional[dict]) -> list[dict]:
    # An explicit predicate is a constraint, not merely a tie-breaker.  It
    # must therefore be checked even when the name/default stage happened to
    # leave one row; otherwise a caller asking for Diameter=100 could silently
    # receive the sole Diameter=200 type.
    if disambiguate_by is None:
        return pool
    pname, expected = disambiguate_by["param"], disambiguate_by["value"]
    narrowed = []
    for row in pool:
        params = row.get("params")
        actual = params.get(pname, _MISSING) if isinstance(params, dict) else _MISSING
        if actual is not _MISSING and _parameter_equals(actual, expected):
            narrowed.append(row)
    return narrowed


def _candidate_rows(pool: list[dict]) -> list[dict]:
    rows = []
    for item in pool[:5]:
        row = {"id": int(item["id"]), "name": str(item.get("name"))}
        for key in ("category", "family_name", "type_name"):
            if isinstance(item.get(key), str):
                row[key] = item[key]
        rows.append(row)
    return rows


def _resolve_one(sel: Any, pool_name: str, pool: list[dict], op_index: int,
                 op_id: str, param: str, op_name: str,
                 diags: list, truncated: bool = False) -> Optional[dict]:
    """Returns {"id": int, "name": str, "via": ...} or None (diag appended).

    ``truncated`` (audit F7): the snapshot pool was capped by the collector and
    the model holds MORE rows than were sent.  A by=name/exact match inside the
    slice is still accepted (id-ordered slice; the residual same-name-twin risk
    is documented), but a not-found says so, and default/sole-entry resolution
    is refused outright — "the sole visible entry" proves nothing about an
    invisible remainder.
    """
    if not isinstance(sel, dict) or sel.get("by") not in (
            "name", "element_id", "default", "family_type"):
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id, field_name=param,
            expected={"by": "name|element_id|default|family_type"}, got=sel,
            message_ru=f"{param} — селектор {{by, value}}"))
        return None
    by = sel["by"]
    if by == "family_type":
        expected_fields = {"by", "category", "family_name", "type_name"}
        if set(sel) != expected_fields or any(
                not isinstance(sel.get(key), str) or not sel[key].strip()
                for key in ("category", "family_name", "type_name")):
            diags.append(Diagnostic(
                code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
                field_name=param,
                expected={
                    "by": "family_type", "category": "OST_...",
                    "family_name": "...", "type_name": "...",
                },
                got=sel,
                message_ru=(f"{param}: family_type требует category+family_name+"
                            "type_name")))
            return None
        want = {
            key: sel[key].strip()
            for key in ("category", "family_name", "type_name")
        }
        exact = [
            row for row in pool
            if all(row.get(key) == value for key, value in want.items())
        ]
        if len(exact) == 1:
            return {
                "id": int(exact[0]["id"]),
                "name": str(exact[0]["name"]),
                "via": "family_type",
                **want,
            }
        diags.append(Diagnostic(
            code=(GROUND_NOT_FOUND if not exact else GROUND_AMBIGUOUS),
            op_index=op_index,
            op_id=op_id,
            field_name=param,
            got=want,
            candidates=_candidate_rows(exact if exact else pool),
            message_ru=(
                f"{pool_name}: family selector не найден"
                if not exact else
                f"{pool_name}: family selector неоднозначен — "
                f"{len(exact)} совпадений"),
        ))
        return None
    disambiguate_by = _disambiguator(sel, op_index, op_id, param, diags)
    if "disambiguate_by" in sel and disambiguate_by is None:
        return None
    if by == "element_id":
        val = sel.get("value")
        if (isinstance(val, bool) or not isinstance(val, int)
                or not (1 <= val <= ELEMENT_ID_MAX)):
            diags.append(Diagnostic(
                code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
                field_name=f"{param}.value",
                expected=f"целое 1..{ELEMENT_ID_MAX}", got=val,
                message_ru="element_id — положительное 64-битное целое"))
            return None
        return {"id": val, "name": None, "via": "element_id"}
    if by == "name":
        val = sel.get("value")
        if not isinstance(val, str) or not val.strip():
            diags.append(Diagnostic(
                code=GROUND_BAD_SELECTOR, op_index=op_index, op_id=op_id,
                field_name=f"{param}.value", expected="непустая строка", got=val,
                message_ru="имя — непустая строка"))
            return None
        want = val.strip()
        exact = [p for p in pool if str(p.get("name", "")).strip() == want]
        if not exact:
            ci = [p for p in pool
                  if str(p.get("name", "")).strip().lower() == want.lower()]
            # One case-insensitive match may resolve, several are AMBIGUOUS.
            # Keeping ``exact=[]`` for the latter used to misreport a real
            # ambiguity as NOT_FOUND (F31).
            exact = ci
        initial_matches = exact
        exact = _narrow_by_parameter(exact, disambiguate_by)
        if len(exact) == 1:
            return {"id": int(exact[0]["id"]), "name": str(exact[0]["name"]),
                    "via": ("name+disambiguate_by"
                            if disambiguate_by is not None else "name"),
                    **({"disambiguate_by": disambiguate_by}
                       if disambiguate_by is not None else {})}
        if not initial_matches:
            trunc_note = ("; снапшот-пул обрезан коллектором — тип может "
                          "существовать за пределами среза, используйте "
                          "element_id" if truncated else "")
            diags.append(Diagnostic(
                code=GROUND_NOT_FOUND, op_index=op_index, op_id=op_id,
                field_name=param, got=want, candidates=_nearest(want, pool),
                message_ru=f"{pool_name}: «{want}» не найден" + trunc_note))
        else:
            # KIR-G102 disambiguation path (2026-07-17): several pool entries
            # share `want` verbatim (e.g. several duct/cable-tray types named
            # "По умолчанию" — routine in real projects, see fix report).
            # Surface each candidate's element_id alongside its name so the
            # caller's NEXT program can re-select deterministically via
            # {"by": "element_id", "value": <id>} instead of retrying the
            # same ambiguous name. The ids were already sitting in `pool`
            # (same dicts _resolve_one reads `id`/`name` off of two branches
            # above) — only the AMBIGUOUS diagnostic used to throw them away.
            diags.append(Diagnostic(
                code=GROUND_AMBIGUOUS, op_index=op_index, op_id=op_id,
                field_name=param,
                got=({"name": want, "disambiguate_by": disambiguate_by}
                     if disambiguate_by is not None else want),
                candidates=_candidate_rows(
                    exact if exact or disambiguate_by is None
                    else initial_matches),
                message_ru=(
                    f"{pool_name}: «{want}» неоднозначен — после "
                    f"disambiguate_by осталось {len(exact)} совпадений"
                    if disambiguate_by is not None else
                    f"{pool_name}: «{want}» неоднозначен — "
                    f"{len(exact)} совпадений; уточни через "
                    f"{{\"by\": \"element_id\", \"value\": <id из candidates>}}")))
        return None
    # by == "default"
    if (op_name == "create_wall" and param == "type"
            and disambiguate_by is None):
        return {"id": None, "name": None, "via": "doc_default",
                "in_emit": IN_EMIT_DEFAULT}
    initial_pool = pool
    if truncated and initial_pool:
        # A truncated pool cannot prove sole-entry-ness (audit F7): the sole
        # VISIBLE row may have invisible siblings beyond the cap.
        diags.append(Diagnostic(
            code=GROUND_AMBIGUOUS, op_index=op_index, op_id=op_id,
            field_name=param, candidates=_candidate_rows(initial_pool),
            message_ru=(f"{pool_name}: снапшот-пул обрезан коллектором — "
                        "default/sole-entry невозможен, укажите element_id")))
        return None
    pool = _narrow_by_parameter(pool, disambiguate_by)
    if len(pool) == 1:
        return {"id": int(pool[0]["id"]), "name": str(pool[0].get("name")),
                "via": ("sole_entry+disambiguate_by"
                        if disambiguate_by is not None else "sole_entry"),
                **({"disambiguate_by": disambiguate_by}
                   if disambiguate_by is not None else {})}
    code = GROUND_EMPTY_POOL if not initial_pool else GROUND_AMBIGUOUS
    # Same id-surfacing fix as the by=name AMBIGUOUS branch above, for the
    # by=default path (omitted param, several pool entries -> AMBIGUOUS never
    # "first"): EMPTY_POOL has no candidates by construction (pool is empty),
    # AMBIGUOUS gets {id, name} pairs so the caller can re-issue with an
    # explicit element_id selector instead of retrying default.
    diags.append(Diagnostic(
        code=code, op_index=op_index, op_id=op_id, field_name=param,
        got=({"disambiguate_by": disambiguate_by}
             if disambiguate_by is not None else None),
        candidates=_candidate_rows(
            pool if pool or disambiguate_by is None else initial_pool),
        message_ru=(
            f"{pool_name}: пусто в модели" if not initial_pool else
            f"{pool_name}: после disambiguate_by осталось {len(pool)} вариантов"
            if disambiguate_by is not None else
            f"{pool_name}: несколько вариантов — default невозможен, уточните "
            f"через {{\"by\": \"element_id\", \"value\": <id из candidates>}}")))
    return None


def _is_grounded(member: Any) -> bool:
    """Already carries the internal shape — the component-library bridge builds
    members pre-grounded, and re-resolving them would be both wasted work and a
    chance to change bytes the rebuild path depends on."""
    if not isinstance(member, dict):
        return False
    ospec = spec.OPS.get(member.get("op"))
    if ospec is None:
        return False
    present = [member.get(p) for p, _pool, _req in ospec.grounded
               if member.get(p) is not None]
    return bool(present) and all(
        isinstance(sel, dict) and "__grounded__" in sel for sel in present)


def _ground_members(members: list, snapshot: Any, gid: str,
                    diags: list[Diagnostic]) -> list:
    """Ground a group's members like any other ops.

    `create_group` was authored for the rebuild bridge, which hands it members
    that are already grounded, so `ground()` never looked inside `members` — and
    the emitter, which requires the internal `{"__grounded__": ...}` shape,
    raised a bare KeyError on anything else. That was reported as "члены должны
    быть pre-grounded", blaming the caller for a shape no caller can write: the
    form the message recommends (`by: element_id`) failed identically. Measured
    2026-07-27 — it is why `create_group` was called 0 times in 51 574 lifted
    ops. Grounding them makes the op reachable, which matters beyond the bug:
    members + placements is KIR's only way to say "this cluster, repeated",
    and without it a lattice is N literal beams the model must unroll by hand.
    """
    raw = [m for m in members if not _is_grounded(m)]
    if not raw:
        return members
    try:
        resolved = {id(m): g for m, g in zip(raw, ground(raw, snapshot))}
    except KirRefusal as refusal:
        # Re-badge so a member failure points at the group op the model wrote,
        # naming the member by ITS id — an op index into a nested list is not
        # something the author can address.
        index_of = {m.get("id"): i for i, m in enumerate(raw) if isinstance(m, dict)}
        for d in refusal.diagnostics:
            member_id = d.op_id
            d.op_id = gid
            d.op_index = index_of.get(member_id)
            d.field_name = (f"members[{member_id or '?'}]"
                            f"{'.' + d.field_name if d.field_name else ''}")
        diags.extend(refusal.diagnostics)
        return members
    return [resolved.get(id(m), m) for m in members]


def ground(normed_ops: list[dict], snapshot: Any) -> list[dict]:
    """Grounded copy of ops: every grounded param becomes
    {"__grounded__": {"id": ..., "name": ..., "via": ...}}. Raises KirRefusal
    with ALL resolution failures at once (one round of typed feedback beats
    a drip of single errors — SPEC 12.7 economy)."""
    if not any(spec.OPS[op["op"]].family in spec.WRITE_FAMILIES for op in normed_ops):
        return normed_ops
    # snapshot is needed only when something must resolve FROM it: by-name /
    # by-default selectors or omitted-with-pool-default params. Pure
    # element_id/ref programs ground without one.
    def _needs_pool(op, ospec):
        for param, _pool, required in ospec.grounded:
            sel = op.get(param)
            if sel is None:
                # wave/struct: mirrors the same variety-discriminated skip as
                # the main resolution loop below — an irrelevant omitted
                # param (symbol when variety!=isolated, type when
                # variety!=slab) must not force a snapshot requirement either.
                if ospec.name == "create_foundation" and (
                        (param == "symbol" and op.get("variety") != "isolated") or
                        (param == "type" and op.get("variety") != "slab")):
                    continue
                if (ospec.name == "create_railing" and param == "level"
                        and op.get("variety") != "path"):
                    # wave/arch: тот же зеркальный пропуск, что и в основном
                    # цикле разрешения ниже — нерелевантный пропущенный
                    # параметр не должен ТРЕБОВАТЬ снапшот.
                    continue
                if param == "top_level":
                    # audit F6 (generalized, P1 2026-07-21): omitted top_level
                    # = no top attach for ANY op (wall unconnected height,
                    # column as-placed height).  A top constraint is opt-in by
                    # construction — default-resolving one from the pool is
                    # never meaningful.  No pool read.
                    continue
                if not required and not (op["op"] in ("create_wall", "create_floor", "create_roof", "create_floor_by_contour") and param == "type"):
                    return True            # default rule reads the pool
                continue
            if isinstance(sel, dict) and sel.get("by") in (
                    "name", "default", "family_type"):
                return True
        # at_grid anchors read the grids pool (CONTOUR sublanguage)
        if op["op"] == "create_floor_by_contour" and "at_grid" in repr(op.get("contour")):
            return True
        return False
    needs_snapshot = any(_needs_pool(op, spec.OPS[op["op"]]) for op in normed_ops)
    if needs_snapshot and not isinstance(snapshot, dict):
        raise KirRefusal([Diagnostic(
            code=GROUND_NO_SNAPSHOT,
            message_ru="программа требует снапшот модели (census) для ground-стадии (резолв по имени/default)")])
    if not isinstance(snapshot, dict):
        snapshot = {}
    diags: list[Diagnostic] = []
    pool_cache: dict[str, list[dict]] = {}

    def snapshot_pool(pool_name: str) -> list[dict]:
        if pool_name not in pool_cache:
            pool_cache[pool_name] = _validate_snapshot_pool(
                snapshot, pool_name, diags)
        return pool_cache[pool_name]

    def pool_truncated(pool_name: str) -> bool:
        return snapshot.get(pool_name + "__truncated") is True

    out = []
    for i, op in enumerate(normed_ops):
        ospec = spec.OPS[op["op"]]
        g = dict(op)
        diameter_spec = next((p for p in ospec.params if p.name == "diameter_mm"), None)
        diameter_bounds = ((diameter_spec.min_val, diameter_spec.max_val)
                           if diameter_spec is not None else None)
        if ospec.name == "create_floor_by_contour":
            from kukai.ir import contour as contour_mod
            grids = (snapshot_pool("grids")
                     if "at_grid" in repr(op.get("contour")) else [])
            region = contour_mod.validate_region(
                op.get("contour"), grids,
                op["id"], "contour", diags)
            if region is not None:
                g["__region__"] = region
        if ospec.name == "create_group" and isinstance(op.get("members"), list):
            g["members"] = _ground_members(op["members"], snapshot, op["id"], diags)
        if ospec.name == "create_pipe_system":
            from kukai.ir import connect as connect_mod
            graph = connect_mod.graph_validate(
                op, op["id"], diags, op.get("diameter_mm"), diameter_bounds)
            if graph is not None:
                g["__graph__"] = graph
        if ospec.name in ("route_pipe_system", "route_duct_system"):
            # wave/mep: same connect.graph_validate reuse as create_pipe_system,
            # plus the checked (not generative) slope_min_pct extraction —
            # see ops_connect.py's module docstring and route_mep.py.
            from kukai.ir import connect as connect_mod
            from kukai.ir import route_mep as route_mep_mod
            slope_reqs = route_mep_mod.extract_slope_requirements(op, op["id"], diags)
            if slope_reqs is not None:
                stripped = route_mep_mod.strip_slope_keys(op)
                graph = connect_mod.graph_validate(
                    stripped, op["id"], diags, op.get("diameter_mm"), diameter_bounds)
                if graph is not None:
                    g["__graph__"] = graph
                    g["__slope_reqs__"] = slope_reqs
        for param, pool_name, required in ospec.grounded:
            sel = op.get(param)
            if isinstance(sel, dict) and sel.get("by") == "ref":
                # intra-program DAG reference: resolved by the plan stage, not
                # against the snapshot (validity checked by the DAG walk).
                g[param] = {"__grounded__": {"ref": str(sel.get("value")), "via": "ref"}}
                continue
            if sel is None:
                # wave/struct (2026-07-17): create_foundation is the first op
                # whose grounded params are VARIETY-DISCRIMINATED — "symbol"
                # (FamilySymbol for the isolated footing) is irrelevant when
                # variety="slab", and "type" (FloorType for the slab) is
                # irrelevant when variety="isolated". The generic omitted-
                # optional rule below has no per-branch concept and would
                # otherwise speculatively resolve BOTH against their pools on
                # every create_foundation op regardless of variety — refusing
                # a perfectly well-formed program because the OTHER branch's
                # pool happens to be empty/ambiguous (a real bug caught live:
                # variety=isolated failed on empty floor_types, variety=slab
                # failed on empty foundation_symbols, neither pool being
                # relevant to the branch actually used). Skip silently (no
                # diagnostic, no __grounded__ entry) exactly when the branch
                # doesn't use the param — struct_emit.py's emit_foundation
                # dispatch never reads that key on the branch where it's
                # skipped, so this is
                # a true no-op for the irrelevant param, not a silent
                # substitute for a real resolution.
                if required:
                    diags.append(Diagnostic(
                        code=GROUND_BAD_SELECTOR, op_index=i, op_id=op["id"],
                        field_name=param, message_ru=f"{param} обязателен"))
                elif ospec.name == "create_foundation" and (
                        (param == "symbol" and op.get("variety") != "isolated") or
                        (param == "type" and op.get("variety") != "slab")):
                    pass
                elif (ospec.name == "create_railing" and param == "level"
                        and op.get("variety") != "path"):
                    # wave/arch: ровно тот же шов, что у create_foundation
                    # строкой выше. Базовый уровень нужен ТОЛЬКО свободному
                    # ограждению (Railing.Create по пути его требует);
                    # ограждение на лестнице берёт уровень у хозяина, и
                    # перегрузка Railing.Create(doc, hostId, typeId, position)
                    # уровня не принимает вовсе. Без этой ветки общее правило
                    # «единственный в пуле» подставило бы уровень проекта в
                    # операцию, которая его не использует, а в проекте с двумя
                    # уровнями (то есть в любом настоящем) просто отказало бы
                    # KIR-G102 — потеряв ограждение ни за что.
                    pass
                elif (ospec.name == "place_family" and param == "level"
                        and "p0_mm" in op):
                    # Кривой вариант place_family уровня НЕ ИМЕЕТ, и это
                    # замер, а не упрощение: у всех 79 кожухов модели ЭОМ
                    # LevelId = -1, а перегрузка NewFamilyInstance по ссылке
                    # на грань хоста уровня не принимает вовсе. Общее
                    # правило ниже подставило бы «единственный уровень
                    # проекта», то есть привязку, которой у оригинала нет, —
                    # и свидетель начал бы проверять выдуманное. В проекте с
                    # двумя уровнями оно к тому же просто отказывает
                    # (KIR-G102), теряя элемент ни за что.
                    pass
                elif param == "top_level":
                    # audit F6 (generalized, P1 2026-07-21): omitted top_level
                    # MEANS «no top attach» for ANY op — wall keeps its
                    # unconnected height, column its as-placed height.  It must
                    # not speculatively resolve a "default level" from the pool
                    # (a sole-level model would silently attach every top).
                    # Skip: no diagnostic, no __grounded__ key; the emitter's
                    # absent-branch is the byte-stable historical emission.
                    pass
                elif ospec.name in ("create_wall", "create_floor", "create_roof", "create_floor_by_contour") and param == "type":
                    g[param] = {"__grounded__": {"id": None, "name": None,
                                                 "via": "doc_default",
                                                 "in_emit": IN_EMIT_DEFAULT}}
                else:
                    # generic omitted-optional rule: the SOLE snapshot entry,
                    # several -> AMBIGUOUS (never first), none -> EMPTY_POOL
                    real_pool = (pool_name.format(category=op.get("category", "structural"))
                                 if "{category}" in pool_name else pool_name)
                    res = _resolve_one({"by": "default"}, real_pool,
                                       snapshot_pool(real_pool),
                                       i, op["id"], param, ospec.name, diags,
                                       truncated=pool_truncated(real_pool))
                    if res:
                        g[param] = {"__grounded__": res}
                continue
            real_pool = (pool_name.format(category=op.get("category", "structural"))
                         if "{category}" in pool_name else pool_name)
            selected_pool = (snapshot_pool(real_pool)
                             if sel.get("by") in (
                                 "name", "default", "family_type") else [])
            res = _resolve_one(sel, real_pool, selected_pool,
                               i, op["id"], param, ospec.name, diags,
                               truncated=pool_truncated(real_pool))
            if res:
                g[param] = {"__grounded__": res}
        out.append(g)
    if diags:
        raise KirRefusal(diags)
    return out
