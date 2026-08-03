"""Dispatch-layer lowering for Tool Palette v2 + the request_more_tools meta-tool.

Called from ONE surgical hook at the top of ``LLMClient._execute_tool``.
Returns None whenever this module has nothing to do — the legacy dispatch
below the hook then runs untouched (both flags OFF ⇒ always None ⇒
byte-identical dispatch).

Design decision — LOWER, don't re-implement: every merged v2 tool
(show_elements / edit_excel / export / query_model-v2) is translated into
calls to the EXISTING legacy handlers via ``client._execute_tool(old_name, …)``
recursion. The legacy branches in client.py stay the single source of truth
(premium gate, bridge fallbacks, instance-level test stubbing all keep
working), and HANDLER COMPAT is structural: the old names remain first-class
at the dispatch layer — an LLM continuing an old conversation or a cached
prompt never breaks. When an absorbed old name is called while v2 is active
we only emit a deprecation DEBUG log and fall through.

The recursion cannot loop: lowered args are always v1-shaped, and v1 names
return None from maybe_dispatch immediately.
"""

from __future__ import annotations

import inspect
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Keys that mark a v2-shaped query_model call. Their absence means a legacy
# (v1-shaped) call — served by the unchanged legacy handler.
_QM_V2_KEYS = ("categories", "scope", "filter", "summary_of", "graph", "section")


async def maybe_dispatch(
    client: Any,
    tool_name: str,
    args: dict[str, Any],
    bridge_callback: Any = None,
    *,
    active_extension: Optional[str] = None,
    user_query: str = "",
    system_context: str = "",
    user_tier: str = "free",
) -> Optional[dict[str, Any]]:
    """v2/meta dispatch. None ⇒ caller falls through to legacy dispatch."""
    # request_more_tools is the MASKING flag's meta-tool — independent of v2.
    if tool_name == "request_more_tools":
        from kukai.llm.tool_masking import masking_enabled
        if not masking_enabled():
            return None  # flag off → "Неизвестный инструмент" (byte-identical)
        return _request_more_tools(client, args)

    from kukai.llm.tools import V2_MERGES, tools_v2_enabled
    if not tools_v2_enabled():
        return None

    if tool_name in V2_MERGES and tool_name != "query_model":
        # Old merged-away name on an active-v2 turn (old conversation / cached
        # prompt). The legacy branch below the hook still serves it — that IS
        # the same handler the new name lowers onto.
        logger.debug(
            "v2 palette: deprecated tool alias %r called (merged into %r) — "
            "serving via legacy handler", tool_name, V2_MERGES[tool_name],
        )
        return None

    kw = dict(
        active_extension=active_extension, user_query=user_query,
        system_context=system_context, user_tier=user_tier,
    )
    if tool_name == "show_elements":
        return await _show_elements(client, args, bridge_callback, kw)
    if tool_name == "edit_excel":
        return await _edit_excel(client, args, bridge_callback, kw)
    if tool_name == "export":
        return await _export(client, args, bridge_callback, kw)
    if tool_name == "query_model":
        return await _query_model_v2(client, args, bridge_callback, kw)
    if tool_name == "inspect":
        return await _inspect_v3(client, args, bridge_callback, kw)
    return None


async def _lower(client, name, args, bridge_callback, kw) -> dict[str, Any]:
    """Recurse into the legacy dispatcher under the OLD tool name."""
    return await client._execute_tool(name, args, bridge_callback, **kw)


# ─── inspect(scope) = get_model_info (scope=model) + inspect element ─────────
async def _inspect_v3(client, args, bridge_callback, kw) -> Optional[dict[str, Any]]:
    """v3 read merge. A call WITHOUT 'scope' is legacy-shaped (old conversation
    / cached prompt calling inspect(element_id=...)) → return None so the legacy
    element handler serves it byte-identically. With 'scope', lower to the right
    legacy handler, STRIPPING the marker so re-entry falls through (no loop)."""
    if "scope" not in args:
        return None
    scope = (args.get("scope") or "element").strip().lower()
    if scope == "model":
        return await _lower(client, "get_model_info", {}, bridge_callback, kw)
    if scope == "element":
        eid = args.get("element_id")
        if eid is None:
            return {"error": True,
                    "message": "inspect(scope='element'): нужен element_id"}
        return await _lower(client, "inspect", {"element_id": eid}, bridge_callback, kw)
    return {"error": True,
            "message": f"inspect: неизвестный scope '{scope}' (model|element)"}


# ─── show_elements = select_elements + highlight_elements ───────────────────

async def _show_elements(client, args, bridge_callback, kw) -> dict[str, Any]:
    mode = (args.get("mode") or "select").strip().lower()
    element_ids = args.get("element_ids", [])
    if mode == "highlight":
        lowered: dict[str, Any] = {"element_ids": element_ids}
        if args.get("color") is not None:
            lowered["color"] = args["color"]
        if args.get("clear_previous") is not None:
            lowered["clear_previous"] = args["clear_previous"]
        return await _lower(client, "highlight_elements", lowered, bridge_callback, kw)
    if mode != "select":
        return {"error": True,
                "message": f"show_elements: неизвестный mode '{mode}' (select|highlight)"}
    return await _lower(client, "select_elements", {"element_ids": element_ids},
                        bridge_callback, kw)


# ─── edit_excel = excel_script (general) + modify_excel (fast path) ─────────

async def _edit_excel(client, args, bridge_callback, kw) -> dict[str, Any]:
    script = args.get("script")
    operations = args.get("operations")
    filename = args.get("filename")
    if script:  # general case wins
        lowered = {"script": script}
        if filename:
            lowered["filename"] = filename
        return await _lower(client, "excel_script", lowered, bridge_callback, kw)
    if operations:
        lowered = {"operations": operations}
        if filename:
            lowered["filename"] = filename
        return await _lower(client, "modify_excel", lowered, bridge_callback, kw)
    return {"error": True,
            "message": "edit_excel: передай `script` (openpyxl) или `operations` (типовые операции)"}


# ─── export = export_view + export_sheets_pdf + send_local_file(deliver) ────

async def _export(client, args, bridge_callback, kw) -> dict[str, Any]:
    what = (args.get("what") or "").strip().lower()
    deliver = args.get("deliver", True)

    if what == "view":
        lowered: dict[str, Any] = {
            "filename": args.get("filename", "kukai_export.png"),
            "format": args.get("format", "png"),
        }
        result = await _lower(client, "export_view", lowered, bridge_callback, kw)
        if deliver and isinstance(result, dict) and not result.get("error"):
            result = await _deliver_files(client, result, kw)
        return result

    if what == "sheets_pdf":
        lowered = {
            "sheet_ids": args.get("sheet_ids", []),
            "combine": args.get("combine", False),
            "quality": args.get("quality", "standard"),
        }
        result = await _lower(client, "export_sheets_pdf", lowered, bridge_callback, kw)
        if deliver and isinstance(result, dict) and not result.get("error"):
            result = await _deliver_files(client, result, kw)
        return result

    return {"error": True,
            "message": f"export: неизвестный what '{what}' (view|sheets_pdf)"}


async def _deliver_files(client, result: dict[str, Any], kw) -> dict[str, Any]:
    """Fold the send_local_file follow-up into export itself. Best-effort:
    delivery failure never destroys a successful export result."""
    candidates: list[dict[str, Any]] = []
    files = result.get("files")
    if isinstance(files, list):
        candidates = [f for f in files if isinstance(f, dict) and f.get("path")]
    elif result.get("path") or result.get("file_path"):
        candidates = [{"path": result.get("path") or result.get("file_path"),
                       "name": result.get("filename") or result.get("name")}]
    if not candidates:
        return result  # nothing server-side to deliver (e.g. addin saved locally)
    delivered = 0
    for f in candidates:
        try:
            send_args = {"file_path": f["path"]}
            if f.get("name"):
                send_args["filename"] = f["name"]
            sent = await client._execute_tool("send_local_file", send_args, None, **kw)
            if isinstance(sent, dict) and not sent.get("error"):
                delivered += 1
        except Exception:  # noqa: BLE001 — best-effort delivery
            logger.exception("export: delivery of %s failed", f.get("path"))
    result["delivered"] = delivered
    result["message"] = (
        f"Экспорт готов: файлов {len(candidates)}, отправлено пользователю {delivered}."
    )
    return result


# ─── query_model v2 → v1 lowering ────────────────────────────────────────────

_CENSUS_FLAG = "KUKAI_QUERY_FROM_CENSUS"
# What the census already holds per category, and the summary_of it can answer.
_CENSUS_METRICS = {"count", "area_m2", "volume_m3", "by_level", "by_type"}


def _census_for_this_turn() -> Optional[dict[str, Any]]:
    """The census this turn's passport was rendered from, or None.

    Same fingerprint the passport build uses, so it is a cache HIT whenever the
    turn already has a passport — no bridge call, no Revit UI thread.
    """
    try:
        from kukai import turn_ledger as _tl  # noqa: PLC0415

        led = _tl.current()
        ws_id = getattr(led, "ws_id", "") if led is not None else ""
        if not ws_id:
            return None
        from kukai.api.ws_registry import _session_contexts  # noqa: PLC0415
        from kukai.query import model_cache as _mc  # noqa: PLC0415

        basic_ctx = _session_contexts.get(ws_id, {})
        if not basic_ctx:
            return None
        census = _mc.peek(_mc.world_version(basic_ctx, {}), "census")
        return census if isinstance(census, dict) and census.get("categories") else None
    except Exception:  # noqa: BLE001 — a cache shortcut may never break the tool
        return None


def _census_category(census: dict[str, Any], name: Optional[str]) -> Optional[dict[str, Any]]:
    """Find a category in the census by display name, OST_ id, or alias."""
    if not name:
        return None
    cats = census.get("categories") or {}
    if name in cats:
        return cats[name]
    low = str(name).strip().lower()
    for key, val in cats.items():
        if str(key).strip().lower() == low:
            return val
    # A raw BuiltInCategory id is not in the alias table — match it directly.
    bic: Optional[str] = str(name).strip() if low.startswith("ost_") else None
    if bic is None:
        try:
            from kukai.categories import resolve_category  # noqa: PLC0415

            bic = resolve_category(str(name))
        except Exception:  # noqa: BLE001
            bic = None
    if bic:
        for val in cats.values():
            if isinstance(val, dict) and val.get("bic") == bic:
                return val
    return None


def _types_as_groups(types_top: Any) -> Optional[dict[str, Any]]:
    """Census `types_top` → the {name: count} shape a group answer uses.

    It is a LIST of rows ({type, count, area_m2, material, function, …}) — not
    the mapping this used to assume, which silently sent every by_type call
    back to the bridge (found 2026-07-27 by probing why the shortcut never
    fired). Both shapes are accepted; anything else declines.
    """
    if isinstance(types_top, dict):
        return types_top
    if not isinstance(types_top, list) or not types_top:
        return None
    groups: dict[str, Any] = {}
    for row in types_top:
        if not isinstance(row, dict):
            return None
        name = row.get("type") or row.get("name")
        count = row.get("count")
        if name is None or count is None:
            return None
        groups[str(name)] = count
    return groups or None


def _summary_from_census(args: dict[str, Any],
                         categories: list[Optional[str]]) -> Optional[dict[str, Any]]:
    """Answer an UNFILTERED multi-category summary from the cached census.

    The fan-out this replaces: ``_query_model_v2`` issues one bridge execute per
    (category × metric) pair, and each one is a full FilteredElementCollector
    sweep on Revit's UI thread. Measured on prod 2026-07-27: 81 bridge calls for
    a single turn's 3 tool calls; 6 categories × 3 metrics = 18 round trips for
    numbers the census already carries (count, area_m2, volume_m3, by_level,
    types_top). A filtered query still goes live — the census knows totals, not
    predicates.
    """
    if os.environ.get(_CENSUS_FLAG, "1") == "0":
        return None
    if args.get("filter") or args.get("action", "none") not in ("none", "", None):
        logger.info("census shortcut declined: filtered/action call")
        return None
    wanted = [m for m in (args.get("summary_of") or ["count"])]
    if not wanted or not set(wanted).issubset(_CENSUS_METRICS):
        logger.info("census shortcut declined: summary_of=%s not all cacheable", wanted)
        return None
    census = _census_for_this_turn()
    if census is None:
        logger.info("census shortcut declined: no census in this turn's cache")
        return None

    results: dict[str, Any] = {}
    for cat in categories:
        row = _census_category(census, cat)
        if row is None:
            logger.info("census shortcut declined: category %r not in census", cat)
            return None  # one miss ⇒ answer the whole call live, never half-stale
        out: dict[str, Any] = {}
        for metric in wanted:
            if metric == "by_type":
                groups = _types_as_groups(row.get("types_top"))
                if groups is None:
                    logger.info("census shortcut declined: no usable types_top for %r", cat)
                    return None
                out["by_type"] = {"groups": groups, "group_by": "type",
                                  "count": row.get("types_total")}
            elif metric == "by_level":
                by_level = row.get("by_level")
                if not isinstance(by_level, dict):
                    logger.info("census shortcut declined: no by_level for %r", cat)
                    return None
                out["by_level"] = {"groups": by_level, "group_by": "level"}
            else:
                if row.get(metric) is None:
                    logger.info("census shortcut declined: %r has no %s", cat, metric)
                    return None
                out[metric] = row.get(metric)
        results[str(cat) if cat else "все"] = out if len(wanted) > 1 else out[wanted[0]]

    logger.info("query_model served from census (%d categories, %s) — no bridge call",
                len(categories), ",".join(wanted))
    return {
        "success": True, "scope": "summary", "results": results,
        "source": "census",
        "note": "Числа из снимка модели, посчитанного при загрузке (без связей). "
                "Нужен фильтр или свежий срез — вызови с filter.",
    }


def _v1_filter_args(args: dict[str, Any]) -> dict[str, Any]:
    """Compact typed `filter` object → the proven v1 loose props."""
    f = args.get("filter") or {}
    # The model occasionally emits `filter` as a bare string (a type name /
    # substring) instead of the typed object — treat it as a type-contains hint
    # rather than crashing the whole tool call.
    if isinstance(f, str):
        return {"type_contains": f} if f.strip() else {}
    if not isinstance(f, dict):
        return {}
    v1: dict[str, Any] = {}
    types_f = f.get("types") or {}
    if isinstance(types_f, str):
        types_f = {"contains": types_f}
    elif not isinstance(types_f, dict):
        types_f = {}
    if types_f.get("contains"):
        v1["type_contains"] = types_f["contains"]
    if types_f.get("names"):
        v1["type_names"] = types_f["names"]
    if f.get("param"):
        v1["param"] = f["param"]
    if f.get("function"):
        v1["function"] = f["function"]
    if f.get("width_mm"):
        v1["width_mm"] = f["width_mm"]
    if f.get("material_contains"):
        v1["layer_material_contains"] = f["material_contains"]
    if f.get("level"):
        v1["level"] = f["level"]
    if f.get("selected") is not None:
        v1["selected"] = f["selected"]
    return v1


def _summary_kinds(args: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """summary_of → the v1 template calls that produce those metrics."""
    summary_of = args.get("summary_of") or ["count"]
    kinds: list[tuple[str, dict[str, Any]]] = []
    metrics = [m for m in summary_of if m in ("count", "area_m2", "volume_m3")]
    # by_level delivers area/volume PER LEVEL below — drop them from the
    # whole-model total so we don't issue a redundant second bridge call.
    if "by_level" in summary_of:
        metrics = [m for m in metrics if m == "count"]
    if metrics == ["count"]:
        kinds.append(("count", {"return": "count"}))
    elif metrics:
        kinds.append(("aggregate", {"return": "aggregate", "aggregate": metrics}))
    if "by_type" in summary_of:
        kinds.append(("by_type", {"return": "group", "group_by": "type"}))
    if "by_level" in summary_of:
        # 2026-07-12: "площадь/объём ПО УРОВНЯМ" as ONE structured query_model
        # call (the exec-gravity lever) — folds any requested area_m2/volume_m3
        # per level; bare by_level → count per level.
        _spec: dict[str, Any] = {"return": "group", "group_by": "level"}
        _lm = [m for m in summary_of if m in ("area_m2", "volume_m3")]
        if _lm:
            _spec["aggregate"] = _lm
        kinds.append(("by_level", _spec))
    if "coverage" in summary_of:
        kinds.append(("coverage", {"return": "coverage"}))
    return kinds or [("count", {"return": "count"})]


async def _query_model_v2(client, args, bridge_callback, kw) -> Optional[dict[str, Any]]:
    if not any(k in args for k in _QM_V2_KEYS):
        return None  # legacy-shaped call (old conversation) → legacy handler

    scope = (args.get("scope") or "summary").strip().lower()

    # details — absorbs get_model_details: same cached passport section.
    if scope == "details":
        return await _lower(client, "get_model_details",
                            {"section": args.get("section") or "full"},
                            bridge_callback, kw)

    # graph — LAZY import; kukai/query/graph_api owns the cache-only query ops.
    # Contract: graph_query(op: str, args: dict) -> dict.
    if scope == "graph":
        gspec = args.get("graph") or {}
        op = str(gspec.get("op") or "")
        gargs = dict(gspec.get("args") or {})
        try:
            # `from … import` (not `import … as`) so a test/build that swaps the
            # module in sys.modules is honoured — the byte-for-byte resolution the
            # graph-unavailable / call-contract tests rely on.
            from kukai.query.graph_api import graph_query  # noqa: PLC0415
        except Exception:  # noqa: BLE001 — module/function absent → graceful
            return {
                "error": True,
                "graph_unavailable": True,
                "message": (
                    "Граф модели недоступен в этой сборке — используй "
                    "scope='summary'/'elements' или execute_revit_code."
                ),
            }
        # The module object (via sys.modules, honouring any monkeypatch) for the
        # OPTIONAL Stage-3 relation helpers — older/patched builds may lack them.
        import sys as _sys  # noqa: PLC0415
        _ga = _sys.modules.get("kukai.query.graph_api")
        # Stage 3 LAZY relations build — the relation ops read a 'relations' cache
        # slot that is NOT injected at connect (token discipline). This is the ONE
        # place the bridge lives, so if the slot is empty we build it here (once)
        # through the bridge and stash it under the SAME fingerprint the op peeks.
        # No bridge / no session → skip: the op then honestly returns no-data and
        # the model falls back to live query_model (never a fabricated answer).
        try:
            _rel_ops = getattr(_ga, "RELATION_OPS", frozenset()) if _ga else frozenset()
            _fp_fn = getattr(_ga, "relations_fingerprint", None) if _ga else None
            if op.strip().lower() in _rel_ops and _fp_fn is not None \
                    and bridge_callback is not None:
                from kukai.query import model_cache as _mc  # noqa: PLC0415
                from kukai.query.model_snapshot import build_relations_cs  # noqa: PLC0415
                _fp = _fp_fn(gargs)
                if _fp and not _mc.peek(_fp, "relations"):
                    async def _compute_relations():
                        _r = await bridge_callback(
                            "execute",
                            {"code": build_relations_cs(), "timeout_ms": 45000},
                        )
                        return _r if (isinstance(_r, dict) and not _r.get("error")) else None
                    await _mc.get_or_compute(_fp, "relations", _compute_relations)
        except Exception:  # noqa: BLE001 — lazy build must never break the query;
            # the op falls open to no-data on any failure here.
            logger.exception("query_model scope=graph: lazy relations build failed")
        try:
            res = graph_query(op, gargs)
            if inspect.isawaitable(res):
                res = await res
            return res if isinstance(res, dict) else {"success": True, "result": res}
        except Exception as exc:  # noqa: BLE001
            logger.exception("query_model scope=graph failed")
            return {"error": True, "message": f"graph_query: {exc}"}

    if scope not in ("summary", "elements", "table"):
        return {"error": True,
                "message": f"query_model: неизвестный scope '{scope}' "
                           "(summary|elements|table|details|graph)"}

    base_v1 = _v1_filter_args(args)
    categories: list[Optional[str]] = list(args.get("categories") or [])
    if not categories:
        categories = [args.get("category")]  # None ⇒ v1 handler's own validation

    if scope == "summary":
        _cached = _summary_from_census(args, categories)
        if _cached is not None:
            return _cached

    if scope == "elements":
        kinds: list[tuple[str, dict[str, Any]]] = [("ids", {"return": "ids"})]
        if args.get("limit") is not None:
            kinds = [("ids", {"return": "ids", "limit": args["limit"]})]
    elif scope == "table":
        # GAP-1/GAP-3: one row per element with the asked-for columns, optionally
        # ordered. Everything else (categories fan-out, action, census shortcut)
        # behaves exactly as for the other scopes — this is a new RETURN SHAPE,
        # not a new query path. Validation of fields/order_by lives in
        # build_query_code, the single place that knows the column vocabulary.
        _tbl: dict[str, Any] = {"return": "table"}
        _tspec = args.get("table") or {}
        if not isinstance(_tspec, dict):
            return {"error": True,
                    "message": "query_model: 'table' должен быть объектом "
                               "{fields, order_by, order}"}
        for _k in ("fields", "order_by", "order"):
            if _tspec.get(_k) is not None:
                _tbl[_k] = _tspec[_k]
        # limit stays top-level: it means the same thing for every scope.
        if args.get("limit") is not None:
            _tbl["limit"] = args["limit"]
        kinds = [("table", _tbl)]
    else:
        kinds = _summary_kinds(args)

    action = (args.get("action") or "none").strip().lower()
    action_applied = action != "none" and len(categories) == 1
    note: Optional[str] = None
    if action != "none" and not action_applied:
        note = ("action пропущен при нескольких категориях — собери ids и "
                "вызови show_elements")

    results: dict[str, Any] = {}
    ok = True
    for cat in categories:
        per_kind: dict[str, Any] = {}
        for i, (kind, kind_args) in enumerate(kinds):
            v1_args = {**base_v1, **kind_args}
            if cat:
                v1_args["category"] = cat
            if action_applied and i == 0:
                v1_args["action"] = action
            raw = await _lower(client, "query_model", v1_args, bridge_callback, kw)
            if isinstance(raw, dict) and raw.get("error"):
                ok = False
            per_kind[kind] = raw
        key = cat or "все"
        results[key] = per_kind[kinds[0][0]] if len(kinds) == 1 else per_kind

    out: dict[str, Any] = {"success": ok, "scope": scope, "results": results}
    if note:
        out["note"] = note
    return out


# ─── request_more_tools (masking meta-tool) ─────────────────────────────────

def _request_more_tools(client, args: dict[str, Any]) -> dict[str, Any]:
    """Return the full catalog (names + one-liners) AND unmask the panel for
    the rest of the turn — the model can never be hard-locked out."""
    from kukai.llm.tool_masking import catalog, mark_unmasked
    from kukai.llm.tools import get_tool_definitions

    mark_unmasked()
    reason = str(args.get("reason") or "")[:500]
    logger.info("request_more_tools: %r — panel unmasked for the rest of the turn",
                reason)
    tools = get_tool_definitions(
        module_registry=getattr(client, "_module_registry", None))
    return {
        "success": True,
        "message": ("Полный каталог инструментов открыт до конца этого хода — "
                    "вызывай нужный инструмент напрямую."),
        "tools": catalog(tools),
    }
