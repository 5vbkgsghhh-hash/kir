"""KIR shadow observer — rollout stage (1) of INTEGRATION_PLAN_D5 §2(в).

Observe-only: on every query_model tool-call, attempt to express the same
request as a KIR program and log the outcome. The model never sees KIR; the
main turn is NEVER affected (absolute fail-open, wiki-adapter discipline —
every public entry is wrapped, any exception degrades to a no-op).

Flag: KUKAI_KIR_TOOL (env, read at call time — create_element convention).
  off (default) -> no-op;  shadow -> observe+log.
The serving hook in kukai/llm/client.py stays a 5-line try/except; ALL logic
lives here so the llm-layer diff is minimal.

Output: backend/data/telemetry/kir_shadow.jsonl (override: KIR_SHADOW_PATH).
Side effect by design: unmappable kinds flow through compile_program into
kir_rejections.jsonl (the cube's queue) — shadow traffic starts feeding the
coverage flywheel with REAL production signals before the tool is ever live.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from kir.install_paths import install_data_path
from kir import env  # noqa: E402

logger = logging.getLogger(__name__)

_FLAG = "KIR_TOOL"
_PATH_ENV = "KIR_SHADOW_PATH"
# §18.5: an absent path = the feed is OFF, not a write into someone else's FS.
_PATH_DEFAULT = None
# The fallback addresses the install the module was imported from
# (install_paths). The previous test — isdir() of an absolute path —
# answered "does the path exist ON THE MACHINE", not "are we running from
# it", and in production any worktree resolved to the production file
# (measured 08-02).


def _shadow_path():
    path = env.get(_PATH_ENV)
    if path:
        return path
    if path is None:
        owned = install_data_path("telemetry", "kir_shadow.jsonl")
        if owned is not None:
            return str(owned)
    return _PATH_DEFAULT

# RU/EN category aliases -> KIR kinds (best-effort; a miss passes the RAW
# string into compile_program, whose typed refusal feeds kir_rejections —
# raw invented names ARE the coverage signal, per the queue contract).
_CATEGORY_TO_KIND = {
    "walls": "wall", "wall": "wall", "стены": "wall", "стена": "wall",
    "doors": "door", "door": "door", "двери": "door", "дверь": "door",
    "windows": "window", "window": "window", "окна": "window", "окно": "window",
    "floors": "floor", "floor": "floor", "перекрытия": "floor", "полы": "floor",
    "ceilings": "ceiling", "потолки": "ceiling",
    "roofs": "roof", "крыши": "roof", "кровля": "roof",
    "rooms": "room", "помещения": "room", "комнаты": "room",
    "levels": "level", "уровни": "level", "этажи": "level",
    "grids": "grid", "оси": "grid", "сетки": "grid",
    "columns": "column_architectural", "колонны": "column_architectural",
    "structural columns": "column_structural", "несущие колонны": "column_structural",
    "stairs": "stair", "лестницы": "stair",
    "pipes": "pipe", "трубы": "pipe",
    "ducts": "duct", "воздуховоды": "duct",
    "views": "view", "виды": "view",
    "sheets": "sheet", "листы": "sheet",
    "images": "image", "изображения": "image",
    "pdf": "pdf_underlay", "пдф": "pdf_underlay", "подложки": "pdf_underlay",
    "cad": "cad_import", "dwg": "cad_import",

    # group_by wave (07-28): the 51-kind table (0a16e8f5, "sections in
    # tables") fixes nothing here by itself — this map is separate, and
    # without its own keys mappable=False would keep lying about kinds
    # already closed. The forms come ONLY from live data/telemetry rows
    # (kir_rejections.jsonl UNSUPPORTED_KIND, kir_shadow.jsonl kind_raw),
    # not invented.
    "каркас несущий": "structural_framing", "structural framing": "structural_framing",
    "балки": "structural_framing", "beam": "structural_framing", "beams": "structural_framing",
    "ограждения": "railing", "railings": "railing", "перила": "railing",
    "обобщённые модели": "generic_model", "generic models": "generic_model",
    "мех. оборудование": "mechanical_equipment", "mechanical equipment": "mechanical_equipment",
    "сантехника": "plumbing_fixture", "plumbing fixtures": "plumbing_fixture",
    "специальное оборудование": "specialty_equipment", "спец. оборудование": "specialty_equipment",
    "specialty equipment": "specialty_equipment",
    "мебель": "furniture",
    "кабельные лотки": "cable_tray", "cable trays": "cable_tray", "cable tray": "cable_tray",
    # "Опоры" (supports) is DELIBERATELY not entered — a live decompile
    # (query_id 30614d9c185ec17c) gives no unambiguous BuiltInCategory
    # (candidates: OST_RailingSupport, OST_BridgeBearings, structural
    # anchors); a silently wrong count is worse than a no_category/RAW pass
    # further into kir_rejections. Decide with the next live pass, not from
    # here.
}

# query_model features KIR family B v1 cannot express yet. Their frequency in
# shadow logs = the empirical priority list for the next opcodes.
_UNSUPPORTED_ARGS = ("type_contains", "type_names", "param", "group_by",
                     "aggregate", "action_select")

#: 🔴 WHAT TO RETURN IS `return`, NOT `action` (2026-08-29, an F-352 audit
#: finding). Before this fix, the choice between `query_count` and
#: `query_list` was made from `action`, whose enumeration does NOT contain
#: the word `count` AT ALL: for the `query_model` tool, `action` says WHAT
#: TO DO with what was found (none / select / isolate / highlight), while
#: `return` says WHAT TO RETURN (count / ids / aggregate / group / coverage
#: / bbox, default count).
#:
#: The outcome was MEASURED, not derived: the same request, written two
#: legitimate ways, was measured as TWO DIFFERENT operations ("walls" with
#: no fields -> query_count, "walls, action=none, return=count" ->
#: query_list); "give me the identifiers" (`return=ids`) was measured as a
#: COUNT; and `coverage` and `bbox` — kinds KIR does NOT have — were
#: declared expressible with an empty `unsupported_features`. That is, an
#: entire KIND of request was struck from the list of what KIR cannot do,
#: and could never reach the coverage queue — and the coverage queue is the
#: one and only reason this file exists.
#:
#: THE DICTIONARY IS CLOSED AND ADMITTEDLY INCOMPLETE. An unknown value is
#: not "similar to a list" but INEXPRESSIBLE: something not understood must
#: land in the queue, not dissolve into `query_list`.
_RETURN_TO_OP = {
    "count": "query_count",
    "ids": "query_list",
}

#: `return` values that have no operation in the KIR registry. Named
#: explicitly, not as "everything else": a list that cannot be enumerated
#: is not a list. (`aggregate` and `group` are also caught by
#: `_UNSUPPORTED_ARGS` via THEIR OWN arguments, but only when the author
#: filled them in; here it is the response kind itself that is caught.)
_RETURN_UNSUPPORTED = ("aggregate", "group", "coverage", "bbox")

#: `action` values that are NOT an action on what was found.
_ACTION_NONE = ("", "none")


def _norm_version(raw: str) -> tuple[str, str]:
    """`(version, WHAT IT BECAME)`. The second value is PROVENANCE, not
    decoration.

    🔴 FIVE FACTS WERE ONE NUMBER (2026-08-30, an F-351 audit finding). "No
    version arrived", "unparsed", "older than supported", "newer than
    supported" and "genuinely 2026" all gave the same `"2026"`, and a
    measurement taken on Revit 2019 landed in the corpus as a measurement on
    2026 — while right next to it `kir_ok` said "we can do this" about a
    version nobody had ever tried it on.

    THE SUBSTITUTION ITSELF IS LEGITIMATE: an observer has no right to crash
    because the environment stayed silent. What is illegitimate is STAYING
    SILENT about it — so the answer stays the same, and the reason rides
    alongside it.

    🔴 THE SUBSTITUTION NOW HAS ONE SITE, WHERE THERE USED TO BE TWO, and
    this reduction is honest, not a weakening of the version ratchet
    (`test_revit_version_has_one_source.py`, entry
    `kir/shadow.py::_norm_version`): before, "2026" was produced by TWO
    ternaries — on a regex miss and on an unsupported year — now it sits in
    one expression, and PROVENANCE tells the cases apart.
    """
    from kir import spec
    text = (raw or "").strip()
    m = re.search(r"20\d\d", text)
    if not text:
        source = "not_supplied"
    elif not m:
        source = "unparsed"
    elif m.group(0) not in spec.REVIT_VERSIONS:
        source = "unsupported:%s" % m.group(0)
    else:
        source = "as_supplied"
    return (m.group(0) if source == "as_supplied" else "2026"), source


def _map_to_program(args: dict) -> tuple[Optional[dict], list[str], Optional[str]]:
    """(program, unsupported_features, kind_raw). Conservative: any feature KIR
    can't express -> mappable=False; no lossy translation, no guessing.

    🔴 THE RESPONSE KIND IS TAKEN FROM `return`, NOT FROM `action` (F-352).
    The docstring promised "no lossy translation, no guessing" and did
    exactly that guessing: it compared `action` against the string
    `"count"`, which is not in its enumeration, and silently emitted
    `query_list` on everything else. The breakdown is in `_RETURN_TO_OP`
    and `_RETURN_UNSUPPORTED`.
    """
    unsupported = []
    for feat in ("type_contains", "type_names", "param", "group_by", "aggregate"):
        if args.get(feat):
            unsupported.append(feat)
    action = (args.get("action") or "").strip().lower()
    if action not in _ACTION_NONE:
        # KIR today expresses no ACTION on what was found — neither a known
        # one (select/isolate/highlight) nor an unfamiliar one. An
        # unfamiliar one is named BY ITS OWN NAME, so the coverage queue
        # sees it specifically, not a generic label.
        unsupported.append("action_select" if action in
                           ("select", "isolate", "highlight")
                           else f"action:{action}")
    want = (args.get("return") or "count").strip().lower()
    if want in _RETURN_UNSUPPORTED:
        # We KNOW this response kind and we know KIR does not express it.
        unsupported.append(f"return:{want}")
    elif want not in _RETURN_TO_OP:
        # We do NOT know it AT ALL — and this is a DIFFERENT fact, not a
        # variety of the first: the host may have grown a new response kind
        # the observer has not heard of yet. Something not understood must
        # BE HEARD by its own name, or it dissolves into "simply
        # inexpressible" and the coverage queue never sees that the list of
        # kinds has drifted.
        unsupported.append(f"return_unknown:{want}")
    cat_raw = str(args.get("category") or "").strip()
    kind = _CATEGORY_TO_KIND.get(cat_raw.lower(), cat_raw or None)
    if kind is None:
        unsupported.append("no_category")
    if unsupported:
        return None, unsupported, cat_raw or None
    op = _RETURN_TO_OP[want]
    return ({"ir_version": "1.0",
             "intent": f"shadow:query_model return={want} "
                       f"action={action or 'none'}",
             "ops": [{"op": op, "id": "shadow", "kind": kind}]},
            [], cat_raw or None)


def observe_query_model(args: Any, revit_version: str = "",
                        user_query: str = "") -> None:
    """Public entry — MUST never raise, MUST be near-zero cost when flag=off."""
    try:
        if env.get(_FLAG, "off") not in ("shadow", "stage2"):
            return  # stage2 is a superset: the tool goes live, telemetry keeps flowing
        if not isinstance(args, dict):
            args = {}
        t0 = time.perf_counter()
        ver, ver_source = _norm_version(revit_version)
        qid = hashlib.sha1((user_query or "").encode("utf-8", "replace")).hexdigest()[:16]
        program, unsupported, kind_raw = _map_to_program(args)
        rec: dict[str, Any] = {
            "v": 1,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source": "kir-shadow",
            "query_id": qid,
            "revit_version": ver,
            #: Where the version came from. `as_supplied` means from the
            #: environment; anything else means the number was SUBSTITUTED,
            #: and the measurement describes 2026, not what the user
            #: actually had (F-351).
            "revit_version_source": ver_source,
            "mappable": program is not None,
            "unsupported_features": unsupported,
            "kind_raw": kind_raw,
        }
        if program is not None:
            from kir.compiler import compile_program
            out = compile_program(program, revit_version=ver, query_id=qid)
            rec["kir_ok"] = out.ok
            rec["op"] = program["ops"][0]["op"]
            rec["kind_mapped"] = program["ops"][0]["kind"]
            if not out.ok:
                rec["diag_codes"] = [d.code for d in out.diagnostics][:5]
                if out.handoff:
                    rec["handoff"] = out.handoff["route"]
        rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        _write(rec)
    except Exception:  # noqa: BLE001 — absolute fail-open: shadow never touches the turn
        logger.debug("KIR shadow observe failed (fail-open)", exc_info=True)


def _write(rec: dict) -> None:
    path = _shadow_path()
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ── Frame-level applicability observer (coordinator directive 2026-07-16) ────
# The query_model hook starves: even count-intents flow through
# execute_revit_code. Real applicability must be measured at the FRAME level,
# once per turn, regardless of which tool the model picks.

def _action_op_map() -> dict:
    """Action -> {ops, capability FACETS}. The `OpSpec.capability` axis.

    🔴 THIS IS NOT THE SAME AXIS AS `frame.object_kinds`'s (2026-08-29, an
    F-353 audit finding), and the function is kept exactly so this stays
    visible: the second half of `capability` is a capability FACET
    (`element`, `geometry`, `type`, `family`, `material`), while a frame
    carries an OBJECT KIND (`wall`, `door`, `pipe`). Comparing them directly
    means measuring word coincidence. `_op_kind_map` below builds the
    kind-to-ops crosswalk; the name is kept because a core change must be
    additive.
    """
    from kir import spec
    m: dict = {}
    for op in spec.OPS.values():
        for action, kind in op.capability:
            m.setdefault(action, {"ops": set(), "kinds": set()})
            m[action]["ops"].add(op.name)
            m[action]["kinds"].add(kind)
    return m


def _op_kind_map() -> tuple[dict, list[str]]:
    """(action -> {object kind -> [ops]}), plus the UNRESOLVED remainder.

    🔴 KIR HAS ITS OWN, SINGLE AXIS OF KINDS: `spec.KINDS` — the very dict
    that `query_count`/`query_list` take their `kind_enum` from. Comparing the
    frame against `capability` FACETS produced two opposite lies from ONE
    instrument (measured 29.08.2026):

        {create, [wall]}    -> "action-only", wall among the uncovered,
                               matched_ops: ALL 70 creation names
                               — even though `create_wall` exists;
        {create, [element]} -> "covered", matched_ops: the same 70
                               — even though `element` is not an object kind
                               at all.

    The crosswalk is built from TWO registry carriers, and both are honest:

      (a) the kind is baked into the op's NAME: `create_wall` -> `wall`;
      (b) the kind arrives as a PARAMETER, `kind_enum`: such an op expresses
          ALL kinds in the registry (`query_count`, `query_list`).

    🔴 THE REMAINDER DOES NOT STAY SILENT. Names resolved by neither (a) nor
    (b) are counted and go into the record as a number
    (`crosswalk_undecided_ops`). An instrument for which UNCOVERED is
    indistinguishable from UNRESOLVED lies silently; here it states exactly
    how many it could not resolve.
    """
    from kir import spec
    kinds = set(spec.KINDS)
    m: dict = {}
    undecided: list[str] = []
    for op in spec.OPS.values():
        takes_kind = any(getattr(pspec, "kind", None) == "kind_enum"
                         for pspec in op.params)
        for action, _facet in op.capability:
            if takes_kind:
                per = m.setdefault(action, {})
                for k in kinds:
                    per.setdefault(k, set()).add(op.name)
                continue
            prefix = action + "_"
            tail = (op.name[len(prefix):]
                    if op.name.startswith(prefix) else None)
            if tail in kinds:
                m.setdefault(action, {}).setdefault(tail, set()).add(op.name)
            else:
                undecided.append(op.name)
    # 🔴 A SET, NOT A LIST, AND THIS IS NOT A STYLE CHOICE. An op can have
    # SEVERAL facets for one action (`create_wall`: element and category), and
    # a list would give one name twice — a reader counting the length would
    # get an inflated number of ops per kind.
    return ({a: {k: sorted(v) for k, v in per.items()} for a, per in m.items()},
            sorted(set(undecided)))


def observe_frame(frame: Any, user_query: str = "", revit_version: str = "") -> None:
    """Once-per-turn applicability probe over the intent frame. Same flag,
    same log, same absolute fail-open as observe_query_model."""
    try:
        if env.get(_FLAG, "off") not in ("shadow", "stage2"):
            return  # stage2 is a superset: the tool goes live, telemetry keeps flowing
        from kir import spec
        qid = hashlib.sha1((user_query or "").encode("utf-8", "replace")).hexdigest()[:16]
        _frame_ver, _frame_ver_source = _norm_version(revit_version)
        rec: dict[str, Any] = {
            "v": 1,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source": "kir-frame-shadow",
            "query_id": qid,
            "revit_version": _frame_ver,
            "revit_version_source": _frame_ver_source,
        }
        if not isinstance(frame, dict) or not frame.get("action"):
            rec["applicability"] = "no_frame"
            _write(rec)
            return
        action = str(frame.get("action"))
        kinds = [str(k) for k in (frame.get("object_kinds") or [])]
        rec["action"] = action
        rec["object_kinds"] = kinds
        rec["domain"] = frame.get("domain")
        amap, undecided = _op_kind_map()
        facets = _action_op_map()
        if action in spec.ROUTE_ONLY_ACTIONS:
            rec["applicability"] = "route-only"
        elif action in facets and action not in amap:
            # 🔴 THE REGISTRY KNOWS THE ACTION, BUT THE KIND AXIS FOR IT IS
            # UNRESOLVED. This is NOT "uncovered": the action does have ops
            # (`delete`, `move`, `place`, `join`, `set_param`, `set_type`,
            # `load`, `inspect` — eight actions, measured 30.08.2026), their
            # names simply don't yield a kind and they don't take
            # `kind_enum`. Calling them "uncovered" would mean replacing one
            # lie with another: the old instrument lied toward coverage, this
            # one would lie toward failure.
            rec["applicability"] = "kinds_undecided"
            rec["matched_ops"] = sorted(facets[action]["ops"])
            rec["crosswalk_undecided_ops"] = len(undecided)
        elif action in amap:
            per = amap[action]
            expressible = [k for k in kinds if k in per]
            # The registry KNOWS the kind, but there is no op for this action.
            not_expressible = [k for k in kinds
                               if k not in per and k in spec.KINDS]
            # The registry does not know the kind AT ALL — this is an entry
            # in the coverage queue, not a negative verdict on the compiler.
            # Two different facts.
            unknown = [k for k in kinds if k not in spec.KINDS]
            rec["kinds_expressible"] = expressible
            rec["kinds_not_expressible"] = not_expressible
            rec["kinds_unknown"] = unknown
            # EXACTLY the ops that answer for the requested kinds, not all 70.
            rec["matched_ops"] = sorted({o for k in expressible for o in per[k]})
            rec["crosswalk_undecided_ops"] = len(undecided)
            # 🔴 THE HEADER REQUIRES ALL REQUESTED KINDS. It used to be set by
            # a SINGLE match (`covered if overlap`), and a frame for "create a
            # wall and a retaining wall" was declared half-covered. `partial`
            # is a FOURTH value alongside the previous three; none of them
            # disappeared.
            rec["applicability"] = (
                "action-only" if not kinds else
                "covered" if (expressible and not not_expressible
                              and not unknown)
                else "partial")
            if kinds:
                # The old keys REMAIN synonyms: the log is read by eye and by
                # ready-made queries, and a core change is obligated to add,
                # not remove.
                rec["kinds_covered"] = expressible
                rec["kinds_uncovered"] = not_expressible + unknown
        else:
            rec["applicability"] = "uncovered"
        _write(rec)
    except Exception:  # noqa: BLE001 — absolute fail-open
        logger.debug("KIR frame shadow failed (fail-open)", exc_info=True)
