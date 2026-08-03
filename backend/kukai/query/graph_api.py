"""ModelGraph v2 — the queryable graph API (the tool-palette contract).

One pure entry point, ``graph_query(op, args) -> dict``, that serves structured
answers about the model from the CACHED perception graph + detailed passport —
NO live Revit round-trip in v1. When the cache is empty it answers honestly
(``{"error": "graph not built yet — use query_model"}``) instead of guessing,
so a caller (tool handler / parallel tool-palette agent) can fall back to the
live query tools.

Contract:
  * ``op`` — one of OPS below.
  * ``args`` — dict. Session resolution, in priority order:
      1. explicit ``args["basic_ctx"]`` (+ optional ``args["detailed"]``) —
         the pure/testable form;
      2. ``args["ws_id"]`` — resolved lazily from the chat session stores
         (kukai.api.chat_ws), which is what a tool handler passes.
    Op-specific args: ``level``/``name`` for op="level"; ``query`` for
    op="find_type".
  * Returns a JSON-safe dict. ``{"ok": True, "op": ..., ...}`` on success,
    ``{"error": "...", ...}`` otherwise. NEVER raises, never blocks.

The function itself is not flag-gated: it only reads caches that are populated
under KUKAI_PERCEPTION / KUKAI_GESTALT_V2, so with the flags off it simply
reports "graph not built yet". Gate the TOOL exposure, not the API.
"""
from __future__ import annotations

from typing import Any, Optional

from kukai.query import model_cache

OPS = ("overview", "level", "links", "systems", "find_type", "stats",
       # v3 orientation ops (require a KUKAI_GRAPH_V3 graph in cache):
       "storeys", "storey", "typical", "grid", "where", "footprint",
       # Stage 3 relation ops (require a cached 'relations' slot — lazily built
       # at the palette graph-dispatch site through the bridge, see palette_v2):
       "hosted", "room_boundaries", "rooms_without")

# The relation ops read the model_cache 'relations' slot (NOT the graph slot).
# The palette lazy-builds that slot on demand for exactly these ops.
RELATION_OPS = frozenset({"hosted", "room_boundaries", "rooms_without"})

_ERR_NO_GRAPH = "graph not built yet — use query_model"
_ERR_NO_V3 = ("graph v3 not built — enable KUKAI_GRAPH_V3 "
              "(op needs geometry-attributed storeys)")
_FIND_TYPE_MAX = 40
_HOSTED_IDS_MAX = 50       # ids list cap for op=hosted
_ROOM_BOUNDS_MAX = 200     # boundary rows cap for op=room_boundaries
_ROOM_LIST_MAX = 60        # known-room candidate cap in error/ambiguity replies


# ── session / cache resolution ───────────────────────────────────────────────

def _active_ws_id() -> Optional[str]:
    """The current turn's ws_id from the per-turn ``_active_ws`` ContextVar
    (bound in client.stream_chat) via the ws-object→ws_id registry. This lets a
    tool call resolve its own session WITHOUT the LLM ever passing ws_id in args
    — the same seam admin_remote/files_excel use. Fail-open to None."""
    try:
        from kukai.llm.turn_context import _active_ws
        from kukai.api.ws_registry import _ws_object_to_ws_id
        ws = _active_ws.get()
        if ws is None:
            return None
        return _ws_object_to_ws_id.get(id(ws))
    except Exception:  # noqa: BLE001 — fail-open (no bound turn / import shape)
        return None


def _resolve_session(args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(basic_ctx, detailed) for this call — explicit args win; else the chat
    session stores by ws_id (lazy import, call-time only). ws_id resolution order:
    explicit args → the per-turn ``_active_ws`` ContextVar (production path, no
    ws_id in the LLM's args). Fail-open to ({}, {})."""
    basic = args.get("basic_ctx")
    if isinstance(basic, dict) and basic:
        detailed = args.get("detailed")
        return basic, detailed if isinstance(detailed, dict) else {}
    ws_id = args.get("ws_id") or args.get("session_id") or _active_ws_id()
    if ws_id:
        try:
            from kukai.api import chat_ws as _cw  # lazy — no import cycle at module load
            basic = _cw._session_contexts.get(str(ws_id)) or {}
            detailed = _cw._session_detailed_passports.get(str(ws_id)) or {}
            return (basic if isinstance(basic, dict) else {},
                    detailed if isinstance(detailed, dict) else {})
        except Exception:  # noqa: BLE001 — fail-open
            return {}, {}
    return {}, {}


def _relations_fp(basic: dict[str, Any]) -> Optional[str]:
    """The model_cache fingerprint of the 'relations' slot for this session —
    ``world_version(basic, {})`` (the SAME key family as the census, so a write
    invalidation drops both). None when the session can't be resolved."""
    if not basic:
        return None
    return model_cache.world_version(basic, {})


def _cached_relations(basic: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The cached relations payload (hosting edges + room boundaries) for this
    model, or None when it hasn't been built. NEVER fabricates — a missing slot
    stays missing so a relation op falls open to the live query path, exactly
    like the no-graph case."""
    fp = _relations_fp(basic)
    if not fp:
        return None
    rel = model_cache.peek(fp, "relations")
    return rel if isinstance(rel, dict) and rel else None


def relations_fingerprint(args: Optional[dict[str, Any]] = None) -> Optional[str]:
    """PUBLIC: the 'relations' cache fingerprint for this call's session, or None
    when the session can't be resolved. The palette graph-dispatch uses it to
    peek/stash the lazy relations build under the SAME key the relation ops read.
    Pure, fail-open, never raises."""
    try:
        args = args if isinstance(args, dict) else {}
        basic, _ = _resolve_session(args)
        return _relations_fp(basic)
    except Exception:  # noqa: BLE001
        return None


def _cached_graph(basic: dict[str, Any], detailed: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The summarized graph for this model, from the content-fingerprint cache.
    Prefers the v2 graph; falls back to v1; also accepts a graph already merged
    into the detailed passport (the passport-injection path). Last resort: the
    model_snapshot census (the KUKAI_SNAPSHOT_PASSPORT path fills a 'census' slot
    but no graph_* slot) adapted to the graph shape for the ops it can honestly
    answer — see _census_to_graph."""
    if not basic:
        return None
    fp = model_cache.world_version(basic, detailed if detailed else None)
    graph = (model_cache.peek(fp, "graph_v3") or model_cache.peek(fp, "graph_v2")
             or model_cache.peek(fp, "graph"))
    if isinstance(graph, dict) and graph:
        return graph
    g = detailed.get("graph") if isinstance(detailed, dict) else None
    if isinstance(g, dict) and g:
        return g
    census = model_cache.peek(fp, "census")
    if isinstance(census, dict) and census:
        return _census_to_graph(census)
    return None


def _census_to_graph(census: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Adapt a model_snapshot census (model_cache kind 'census') to the graph
    shape, for the ops it can HONESTLY answer: levels/storeys (op=overview,
    op=level), rooms-by-level, grids, and per-category-by-level counts. NEVER
    fabricates — a census field that is absent stays absent, so ops the census
    cannot answer (op=systems, op=links, the v3 spine) see no data and fall open
    to the live path exactly as with no graph at all. Tagged source='census'."""
    if not isinstance(census, dict) or not census:
        return None
    from kukai.query.model_snapshot import _is_physical

    out: dict[str, Any] = {"source": "census"}

    # levels — census levels already carry name + elev_m (the shape _op_level reads)
    levels = [{"name": l["name"], "elev_m": l.get("elev_m", 0.0)}
              for l in (census.get("levels") or [])
              if isinstance(l, dict) and l.get("name")]
    if levels:
        out["levels"] = levels

    cats = census.get("categories") if isinstance(census.get("categories"), dict) else {}
    # rooms-by-level from the Rooms category's own by_level counts (never fabricate:
    # absent → the key is simply omitted, not zero)
    for c in cats.values():
        if isinstance(c, dict) and c.get("bic") == "OST_Rooms":
            rooms = {}
            for lv, d in (c.get("by_level") or {}).items():
                cnt = d.get("count") if isinstance(d, dict) else d
                if isinstance(cnt, int) and cnt:
                    rooms[lv] = cnt
            if rooms:
                out["rooms_by_level"] = rooms
            break
    # per-category by-level counts (physical categories only, real display names)
    cbl: dict[str, dict[str, int]] = {}
    for name, c in cats.items():
        if not (isinstance(c, dict) and _is_physical(name, c)):
            continue
        for lv, d in (c.get("by_level") or {}).items():
            cnt = d.get("count") if isinstance(d, dict) else d
            if isinstance(cnt, int) and cnt:
                cbl.setdefault(lv, {})[name] = cnt
    if cbl:
        out["cat_by_level"] = cbl

    # grids — census carries a flat name list → the {count,names} graph shape
    grids = [str(g) for g in (census.get("grids") or []) if g]
    if grids:
        out["grids"] = {"count": len(grids), "names": grids}

    # Nothing mappable (no levels/rooms/cats/grids) ⇒ behave like no graph.
    return out if len(out) > 1 else None


def _v3(graph: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The graph when it carries the v3 spine (bands/runs), else None."""
    return graph if isinstance(graph, dict) and graph.get("v3") else None


def _hier(detailed: dict[str, Any]) -> dict[str, Any]:
    h = detailed.get("family_type_hierarchy") or detailed.get("family_types") or {}
    return h if isinstance(h, dict) else {}


# ── ops ──────────────────────────────────────────────────────────────────────

def _op_overview(basic, detailed, graph, args):
    if graph is None:
        return {"error": _ERR_NO_GRAPH}
    cats = basic.get("categories") or []
    return {
        "ok": True, "op": "overview",
        "document": basic.get("document_name", ""),
        "elements": sum(c.get("count", 0) for c in cats if isinstance(c, dict)),
        # graph-first: the graph's self-collected levels are the truth even when
        # the pushed context is thin/stale (the Муза "2 уровней" head bug)
        "levels": len(graph.get("levels") or []) or len(basic.get("levels") or []),
        "graph": graph,
    }


def _op_level(basic, detailed, graph, args):
    if graph is None:
        return {"error": _ERR_NO_GRAPH}
    name = str(args.get("name") or args.get("level") or "").strip()
    if not name:
        return {"error": "op=level requires args.name (level name)"}
    # elevation: pushed context first, then the graph's self-collected levels
    known: dict[str, float] = {}
    for lv in (basic.get("levels") or []):
        if isinstance(lv, dict) and lv.get("name"):
            known[str(lv["name"])] = lv.get("elevation_m", 0.0)
    for lv in (graph.get("levels") or []):
        if isinstance(lv, dict) and lv.get("name"):
            known.setdefault(str(lv["name"]), lv.get("elev_m", 0.0))
    match = name if name in known else next(
        (k for k in known if k.lower() == name.lower()), None)
    if match is None:
        return {"error": f"level '{name}' not found", "known_levels": sorted(known)}
    counts = (graph.get("cat_by_level") or {}).get(match) \
        or (detailed.get("distribution_by_level") or {}).get(match) or {}
    out = {
        "ok": True, "op": "level",
        "name": match,
        "elevation_m": known[match],
        "rooms": (graph.get("rooms_by_level") or {}).get(match),
        "counts": counts,
    }
    grids = graph.get("grids") or {}
    if grids.get("count"):
        # LOD-0 collects grids model-wide (per-level crossing needs geometry — v2+)
        out["grids"] = {**grids, "scope": "model-wide"}
    return out


def _op_links(basic, detailed, graph, args):
    links = (graph or {}).get("links")
    if links is None and isinstance(detailed, dict):
        links = detailed.get("linked_models")
    if links is None:
        if graph is None:
            return {"error": _ERR_NO_GRAPH}
        # a v1 graph exists but carries no link data — absence of data ≠ zero links
        return {"error": "no link data in cached graph — "
                         "enable KUKAI_GESTALT_V2 or use get_model_details"}
    return {"ok": True, "op": "links", "links": links, "count": len(links)}


def _op_systems(basic, detailed, graph, args):
    if graph is None:
        return {"error": _ERR_NO_GRAPH}
    # A census-derived graph never traversed MEP systems, so the key is ABSENT
    # (a real v1/v2/v3 graph always carries "mep_systems", even as []). Absent ≠
    # zero: fall open to the live query path instead of reporting a fabricated 0.
    if "mep_systems" not in graph:
        return {"error": _ERR_NO_GRAPH}
    systems = graph.get("mep_systems") or []
    return {"ok": True, "op": "systems", "systems": systems, "count": len(systems)}


def _op_find_type(basic, detailed, graph, args):
    q = str(args.get("query") or args.get("q") or args.get("substring") or "").strip()
    if not q:
        return {"error": "op=find_type requires args.query (substring)"}
    hier = _hier(detailed)
    if not hier:
        return {"error": "detailed passport not available yet — use get_model_details"}
    ql = q.lower()
    matches: list[dict[str, Any]] = []
    truncated = False
    for cat, fams in hier.items():
        if not isinstance(fams, list):
            continue
        for fam in fams:
            if not isinstance(fam, dict):
                continue
            fam_name = str(fam.get("family_name") or "")
            for t in (fam.get("types") or []):
                if not isinstance(t, dict) or not t.get("name"):
                    continue
                tname = str(t["name"])
                if ql in tname.lower() or ql in fam_name.lower() or ql in str(cat).lower():
                    if len(matches) >= _FIND_TYPE_MAX:
                        truncated = True
                        break
                    matches.append({"category": str(cat), "family": fam_name,
                                    "type": tname, "count": t.get("count", 0)})
            if truncated:
                break
        if truncated:
            break
    out = {"ok": True, "op": "find_type", "query": q,
           "matches": matches, "count": len(matches)}
    if truncated:
        out["truncated"] = True
    return out


def _op_stats(basic, detailed, graph, args):
    cats = [c for c in (basic.get("categories") or []) if isinstance(c, dict)]
    if not cats:
        return {"error": _ERR_NO_GRAPH}
    listing = sorted(
        ({"name": c.get("name_ru") or c.get("name") or "?", "count": c.get("count", 0)}
         for c in cats),
        key=lambda x: x["count"], reverse=True,
    )
    return {
        "ok": True, "op": "stats",
        "document": basic.get("document_name", ""),
        "total": sum(x["count"] for x in listing),
        "categories": listing,
    }


# ── v3 ops: cheap orientation over the geometry-attributed storey bands ─────

def _band_summary(b: dict[str, Any], top: int = 5) -> dict[str, Any]:
    prof = b.get("profile") or {}
    cats = dict(sorted(prof.items(), key=lambda kv: -kv[1])[:top])
    return {"i": b.get("i"), "name": b.get("name"), "elev_m": b.get("elev_m"),
            "height_m": b.get("height_m"), "total": b.get("total", 0),
            "cats": cats}


def _op_storeys(basic, detailed, graph, args):
    if graph is None:
        return {"error": _ERR_NO_GRAPH}
    g3 = _v3(graph)
    if g3 is None:
        return {"error": _ERR_NO_V3}
    return {
        "ok": True, "op": "storeys",
        "storeys": [_band_summary(b) for b in (g3.get("bands") or [])],
        "below": g3.get("below"),
        "unplaced": g3.get("unplaced"),
        "spanners": g3.get("spanners") or {},
    }


def _op_storey(basic, detailed, graph, args):
    if graph is None:
        return {"error": _ERR_NO_GRAPH}
    g3 = _v3(graph)
    if g3 is None:
        return {"error": _ERR_NO_V3}
    bands = g3.get("bands") or []
    band = None
    n = args.get("n")
    if n is not None:
        try:
            n = int(n)
        except (TypeError, ValueError):
            return {"error": "op=storey: args.n must be an integer (1 = lowest)"}
        band = next((b for b in bands if b.get("i") == n), None)
    else:
        name = str(args.get("name") or args.get("level") or "").strip().lower()
        if not name:
            return {"error": "op=storey requires args.n (index) or args.name"}
        band = next((b for b in bands
                     if any(name == str(nm).lower() for nm in (b.get("names") or []))),
                    None)
    if band is None:
        return {"error": "storey not found",
                "storeys": [{"i": b.get("i"), "name": b.get("name")} for b in bands]}
    return {"ok": True, "op": "storey", **{k: band.get(k) for k in
            ("i", "name", "names", "elev_m", "height_m", "total", "profile", "rooms")}}


def _op_typical(basic, detailed, graph, args):
    if graph is None:
        return {"error": _ERR_NO_GRAPH}
    g3 = _v3(graph)
    if g3 is None:
        return {"error": _ERR_NO_V3}
    typical = g3.get("typical")
    if not typical:
        return {"error": "no typical-floor run detected (storeys are all distinct)",
                "runs": g3.get("runs") or []}
    return {"ok": True, "op": "typical", "typical": typical,
            "runs": g3.get("runs") or []}


def _op_grid(basic, detailed, graph, args):
    if graph is None:
        return {"error": _ERR_NO_GRAPH}
    g3 = _v3(graph)
    if g3 is None:
        return {"error": _ERR_NO_V3}
    ga = g3.get("grid_axes") or {}
    return {"ok": True, "op": "grid", "total": ga.get("total", 0),
            "x": ga.get("x"), "y": ga.get("y"), "other": ga.get("other", 0),
            "names": (g3.get("grids") or {}).get("names") or []}


def _resolve_where_key(q: str, g3: dict[str, Any]) -> Optional[str]:
    from kukai.query.model_graph_v3 import _WHERE_STEMS, CAT_LABELS_V3
    ql = q.strip().lower()
    if not ql:
        return None
    if ql in CAT_LABELS_V3:                       # exact census key
        return ql
    for key, label in CAT_LABELS_V3.items():      # exact RU label
        if ql == label:
            return key
    for stem, key in _WHERE_STEMS:                # RU stem ("колонн" in "колонны")
        if stem in ql:
            return key
    return None


def _op_where(basic, detailed, graph, args):
    if graph is None:
        return {"error": _ERR_NO_GRAPH}
    g3 = _v3(graph)
    if g3 is None:
        return {"error": _ERR_NO_V3}
    q = str(args.get("category") or args.get("key") or args.get("query") or "")
    key = _resolve_where_key(q, g3)
    if key is None:
        from kukai.query.model_graph_v3 import CAT_LABELS_V3
        present = sorted({k for b in (g3.get("bands") or [])
                          for k in (b.get("profile") or {})})
        return {"error": f"unknown category '{q}'",
                "known": [CAT_LABELS_V3.get(k, k) for k in present]}
    by_storey = [{"i": b["i"], "name": b["name"],
                  "count": (b.get("profile") or {}).get(key, 0)}
                 for b in (g3.get("bands") or [])
                 if (b.get("profile") or {}).get(key)]
    below = ((g3.get("below") or {}).get("profile") or {}).get(key, 0)
    unplaced = ((g3.get("unplaced") or {}).get("profile") or {}).get(key, 0)
    total = sum(r["count"] for r in by_storey) + below + unplaced
    out = {"ok": True, "op": "where", "key": key, "query": q, "total": total,
           "by_storey": by_storey}
    if below:
        out["below"] = below
    if unplaced:
        out["unplaced"] = unplaced
    if key in (g3.get("spanners") or {}):
        out["spanners"] = g3["spanners"][key]
    return out


def _op_footprint(basic, detailed, graph, args):
    if graph is None:
        return {"error": _ERR_NO_GRAPH}
    g3 = _v3(graph)
    if g3 is None:
        return {"error": _ERR_NO_V3}
    bbox = g3.get("bbox_m") or {}
    ga = g3.get("grid_axes") or {}
    return {
        "ok": True, "op": "footprint",
        "bbox_m": bbox,
        "height_m": bbox.get("dz_m"),
        "storeys": g3.get("storeys", 0),
        "grid": {"x": ga.get("x"), "y": ga.get("y"), "total": ga.get("total", 0)},
    }


# ── Stage 3 relation ops: hosting edges + room boundaries (cache-only) ──────
# These read the 'relations' cache slot (built lazily at the palette dispatch
# through the bridge). Never-fabricate: no slot → the no-graph error so the
# model falls back to the live query tools; absent/unhosted → disclosed, NOT 0.

def _norm_cat(raw: Any) -> str:
    """Normalize a door/window category token (RU/EN, singular/plural) → the
    stable 'door'/'window' tag the C# emits. Unknown → '' (no filter)."""
    v = str(raw or "").strip().lower()
    if v in ("door", "doors", "дверь", "двери", "дверей"):
        return "door"
    if v in ("window", "windows", "окно", "окна", "окон"):
        return "window"
    return ""


def _resolve_room(rooms: list, q: str):
    """(room|None, candidates). Match by exact id → exact name (ci) → UNIQUE
    substring. Ambiguous substring → (None, [names]) so the op can disclose the
    candidates instead of silently picking one."""
    ql = q.strip().lower()
    for r in rooms:
        if str(r.get("id")) == q:
            return r, []
    for r in rooms:
        if str(r.get("name") or "").strip().lower() == ql:
            return r, []
    subs = [r for r in rooms if ql and ql in str(r.get("name") or "").strip().lower()]
    if len(subs) == 1:
        return subs[0], []
    if len(subs) > 1:
        return None, sorted({str(r.get("name")) for r in subs if r.get("name")})
    return None, []


def _op_hosted(basic, detailed, graph, args):
    rel = _cached_relations(basic)
    if rel is None:
        return {"error": _ERR_NO_GRAPH}
    hosted = [h for h in (rel.get("hosted") or []) if isinstance(h, dict)]
    cat = _norm_cat(args.get("cat"))
    host_type = str(args.get("host_type") or "").strip()
    level = str(args.get("level") or "").strip()

    def _match(h) -> bool:
        if cat and str(h.get("cat") or "").lower() != cat:
            return False
        if host_type and str(h.get("host_type") or "") != host_type:
            return False
        if level and str(h.get("level") or "") != level:
            return False
        return True

    sel = [h for h in hosted if _match(h)]
    by_host: dict[str, int] = {}
    unhosted = 0
    for h in sel:
        ht = h.get("host_type")
        if ht:
            by_host[str(ht)] = by_host.get(str(ht), 0) + 1
        else:
            unhosted += 1
    out: dict[str, Any] = {
        "ok": True, "op": "hosted", "cat": cat or "all", "total": len(sel),
        "by_host_type": dict(sorted(by_host.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
    if host_type:
        out["host_type"] = host_type
    if level:
        out["level"] = level
    if unhosted:
        # door/window with no Host element — disclosed, NEVER folded into a host.
        out["unhosted"] = unhosted
    # ids when asked for, or when the set is small enough to list cheaply.
    if bool(args.get("ids")) or len(sel) <= _HOSTED_IDS_MAX:
        out["ids"] = [str(h["id"]) for h in sel[:_HOSTED_IDS_MAX] if h.get("id")]
        if len(sel) > _HOSTED_IDS_MAX:
            out["ids_truncated"] = True
    return out


def _op_room_boundaries(basic, detailed, graph, args):
    rel = _cached_relations(basic)
    if rel is None:
        return {"error": _ERR_NO_GRAPH}
    q = str(args.get("room") or args.get("name") or args.get("id") or "").strip()
    if not q:
        return {"error": "op=room_boundaries requires args.room (name or id)"}
    rooms = [r for r in (rel.get("rooms") or []) if isinstance(r, dict)]
    room, candidates = _resolve_room(rooms, q)
    if room is None:
        err = {"error": (f"room '{q}' is ambiguous" if candidates
                         else f"room '{q}' not found")}
        err["candidates" if candidates else "known_rooms"] = (
            candidates or sorted({str(r.get("name")) for r in rooms
                                  if r.get("name")})[:_ROOM_LIST_MAX])
        return err
    bids = [str(b) for b in (room.get("boundary_ids") or []) if b]

    # index the hosting edges by host wall id (only honest per-id join available:
    # the census is aggregated, so it cannot map a boundary id → a category).
    host_type_by_id: dict[str, str] = {}
    openings_by_host: dict[str, list] = {}
    for h in (rel.get("hosted") or []):
        if not isinstance(h, dict):
            continue
        hid = h.get("host_id")
        if not hid:
            continue
        hid = str(hid)
        if h.get("host_type") and hid not in host_type_by_id:
            host_type_by_id[hid] = str(h["host_type"])
        entry = {"id": str(h.get("id")), "cat": h.get("cat")}
        if h.get("type"):
            entry["type"] = h["type"]
        openings_by_host.setdefault(hid, []).append(entry)

    boundaries = []
    for bid in bids[:_ROOM_BOUNDS_MAX]:
        b: dict[str, Any] = {"id": bid}
        if bid in host_type_by_id:
            b["host_type"] = host_type_by_id[bid]
        if bid in openings_by_host:
            b["hosts"] = openings_by_host[bid]
        boundaries.append(b)

    out: dict[str, Any] = {
        "ok": True, "op": "room_boundaries",
        "room": {"id": room.get("id"), "name": room.get("name"),
                 "level": room.get("level")},
        "boundary_count": len(bids),
        "boundaries": boundaries,
    }
    if len(bids) > _ROOM_BOUNDS_MAX:
        out["boundaries_truncated"] = True
    if not bids:
        # unplaced / unenclosed room — no boundary segments to reason over.
        out["unassessed"] = True
    return out


def _op_rooms_without(basic, detailed, graph, args):
    rel = _cached_relations(basic)
    if rel is None:
        return {"error": _ERR_NO_GRAPH}
    cat = _norm_cat(args.get("cat"))
    if cat not in ("window", "door"):
        return {"error": "op=rooms_without requires args.cat ('window' or 'door')"}
    hosting_ids = {str(h["host_id"]) for h in (rel.get("hosted") or [])
                   if isinstance(h, dict) and str(h.get("cat") or "").lower() == cat
                   and h.get("host_id")}
    rooms = [r for r in (rel.get("rooms") or []) if isinstance(r, dict)]

    def _ref(r) -> dict[str, Any]:
        return {"id": r.get("id"), "name": r.get("name"), "level": r.get("level")}

    def _sort_key(d) -> tuple:
        return (str(d.get("level") or ""), str(d.get("name") or ""), str(d.get("id") or ""))

    without: list = []
    unassessed: list = []
    for r in rooms:
        bids = {str(b) for b in (r.get("boundary_ids") or []) if b}
        if not bids:
            # NEVER counted as "without": absence of boundaries ≠ absence of cat.
            unassessed.append(_ref(r))
            continue
        if not (bids & hosting_ids):
            without.append(_ref(r))
    without.sort(key=_sort_key)
    unassessed.sort(key=_sort_key)

    out: dict[str, Any] = {
        "ok": True, "op": "rooms_without", "cat": cat,
        "without": without, "without_n": len(without),
        "rooms_total": len(rooms),
    }
    if unassessed:
        out["unassessed"] = unassessed
        out["unassessed_n"] = len(unassessed)
        out["note"] = ("помещения без границ (не размещены/не замкнуты) вынесены "
                       "в unassessed — наличие окон/дверей у них НЕ проверялось")
    return out


_OP_TABLE = {
    "overview": _op_overview,
    "level": _op_level,
    "links": _op_links,
    "systems": _op_systems,
    "find_type": _op_find_type,
    "stats": _op_stats,
    "storeys": _op_storeys,
    "storey": _op_storey,
    "typical": _op_typical,
    "grid": _op_grid,
    "where": _op_where,
    "footprint": _op_footprint,
    "hosted": _op_hosted,
    "room_boundaries": _op_room_boundaries,
    "rooms_without": _op_rooms_without,
}


# ── entry point ──────────────────────────────────────────────────────────────

def graph_query(op: str, args: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Query the cached model graph/passport. Pure, fail-open, never raises."""
    try:
        args = args if isinstance(args, dict) else {}
        handler = _OP_TABLE.get(str(op or "").strip().lower())
        if handler is None:
            return {"error": f"unknown op '{op}'", "ops": list(OPS)}
        basic, detailed = _resolve_session(args)
        if not basic:
            return {"error": _ERR_NO_GRAPH}
        graph = _cached_graph(basic, detailed)
        return handler(basic, detailed, graph, args)
    except Exception as exc:  # noqa: BLE001 — the contract: never raises
        return {"error": f"graph_query failed: {exc}"}
