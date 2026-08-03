"""NAV-V2 — "Show-Your-Work": deterministic post-write navigation (KUKAI_NAV_V2).

Product insight (operator, 2026-07-10): the result of every successful write should
be SHOWN, not just claimed — select (blue) + Zoom-to-Fit after each write action AND
at the end of the turn; a view/schedule/sheet the turn just created is OPENED as the
active view; isolation is downgraded to a plain select unless the user explicitly
asked for it ("изолир"/"isolate" in their turn text). Nothing here reads model text
to decide WHAT to do — every verb is derived from tool RESULTS (deterministic).

This module is the PURE, testable core, mirroring kukai/llm/reveal.py's shape (same
author, same "small pure module + two thin wiring sites" architecture):
  1. harvest  — at the tool_end fold (chat_ws), fold each successful WRITE
     observation's result into the turn's running nav targets.
  2. codegen  — build the single _NAV_V2_CS snippet (final, end-of-turn) or the
     lightweight per-action mid-turn zoom snippet (delegates to reveal.build_reveal_code
     — same "select then ShowElements" primitive, no isolate/view-open side effects).
  3. throttle — pure gate for the mid-turn zoom (>= KUKAI_NAV_V2_THROTTLE_S apart).
  4. coercion — pure predicate: was isolation EXPLICITLY requested in the user's turn
     text? Two thin call sites (client.py::_execute_tool, the single funnel through
     which BOTH isolate paths — apply_revit_write/hide_or_isolate and
     query_model/action=isolate — already dispatch with `user_query` in scope) use it
     to downgrade an implicit isolate to a select. The isolate-guards themselves
     (empty-set refusal in revit_verbs.py / query_builder.py) are untouched.

Flag: KUKAI_NAV_V2 = "0"/off (default) | "1"/on. Default OFF ⇒ every call site below
is skipped ⇒ the turn is byte-identical to pre-NAV-V2 behavior (the legacy _NAV_CS /
autoshow_should_fire gate in chat_ws is completely untouched).
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional

# ── flags ─────────────────────────────────────────────────────────────────────

def nav_v2_enabled() -> bool:
    return (os.environ.get("KUKAI_NAV_V2", "0") or "0").strip() == "1"


def mini_nav_throttle_s() -> float:
    """Minimum spacing between per-action mid-turn zooms (spec: 2.5s)."""
    try:
        return max(0.0, float(os.environ.get("KUKAI_NAV_V2_THROTTLE_S", "2.5")))
    except (ValueError, TypeError):
        return 2.5


def nav_v2_id_cap() -> int:
    """Cap on harvested element ids — ShowElements on thousands is slow."""
    try:
        return max(1, int(os.environ.get("KUKAI_NAV_V2_ID_CAP", "500")))
    except (ValueError, TypeError):
        return 500


# ── harvest layer ─────────────────────────────────────────────────────────────

# Keys whose value may carry element ids created/touched by a WRITE result — scalar
# or list, int or numeric-string. "nav" covers model-authored execute_revit_code
# snippets that stash ids there (an observed convention in real transcripts); the
# rest are the structured tool result keys used across kukai/write/*.
_ID_KEYS = ("element_ids", "ids", "id", "new_ids", "created_ids", "nav")
# schedule_id (create_schedule) / view_id / sheet_id — a view/spec/sheet the turn
# created. LAST one wins (a turn that creates several views opens the final one).
_VIEW_KEYS = ("schedule_id", "view_id", "sheet_id")
# An isolate that survived coercion (part 4) actually ran — the result discloses it
# via the `action` key (query_model: "isolated"; hide_or_isolate: the raw verb,
# "isolate"). Used to keep the final hook's promise: an EXPLICIT isolate this turn
# must not be silently undone by the un-isolate-all-views cleanup (see build_nav_v2_code).
_ISOLATE_ACTION_VALUES = ("isolated", "isolate")


def _coerce_id(x: Any) -> Optional[int]:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, str):
        s = x.strip()
        if s:
            try:
                return int(s)
            except ValueError:
                return None
    return None


def _fold_ids(value: Any, out: list[int], seen: set[int], cap: int) -> None:
    if len(out) >= cap:
        return
    items = value if isinstance(value, list) else [value]
    for item in items:
        if len(out) >= cap:
            return
        iid = _coerce_id(item)
        if iid is not None and iid not in seen:
            seen.add(iid)
            out.append(iid)


def _fold_result(
    result: Any,
    element_ids: list[int],
    seen: set[int],
    cap: int,
) -> tuple[Optional[int], list[str], bool]:
    """Fold ONE write result into element_ids (in place). Returns
    (view_id_from_this_result, file_paths_from_this_result, isolate_active_here)."""
    if not isinstance(result, dict):
        return None, [], False
    for k in _ID_KEYS:
        if k in result:
            _fold_ids(result[k], element_ids, seen, cap)
    view_id: Optional[int] = None
    for k in _VIEW_KEYS:
        if k in result:
            iid = _coerce_id(result.get(k))
            if iid is not None:
                view_id = iid
    file_paths: list[str] = []
    files = result.get("files")
    if isinstance(files, list):
        for f in files:
            if isinstance(f, dict) and f.get("path"):
                file_paths.append(str(f["path"]))
    else:
        p = result.get("path") or result.get("file_path")
        if p:
            file_paths.append(str(p))
    isolate_active = str(result.get("action", "")).strip().lower() in _ISOLATE_ACTION_VALUES
    return view_id, file_paths, isolate_active


def harvest_nav_targets(observations: Iterable[Any], cap: Optional[int] = None) -> dict[str, Any]:
    """_harvest_nav_targets — union element ids from every successful WRITE
    observation's result (only ok writes contribute — a failed write is never
    zoomed to), the LAST open_view_id seen (schedule/view/sheet — a created view
    takes priority over zooming), export file paths, and whether an isolate
    survived coercion this turn (explicit_isolate_active).

    ``observations`` duck-types kukai.llm.tool_observation.ToolObservation:
    ``.is_write``, ``.ok``, ``.result`` (a parsed dict for write tools — see the
    ``is_write`` branch added to tool_observation.observe()).
    """
    cap = cap if cap is not None else nav_v2_id_cap()
    element_ids: list[int] = []
    seen: set[int] = set()
    open_view_id: Optional[int] = None
    file_paths: list[str] = []
    explicit_isolate_active = False
    for o in observations:
        _ok = getattr(o, "ok", False)
        _is_write = getattr(o, "is_write", False)
        # File-producing tools (export_view/generate_report/…) are NOT write
        # tools, but their ok-result carries file_path — tool_observation keeps
        # their parsed result (_NAV_FILE_TOOLS), so harvest must not skip a
        # non-write observation that actually has a kept dict result.
        _has_result = isinstance(getattr(o, "result", None), dict)
        if not (_ok and (_is_write or _has_result)):
            continue
        v, fps, isolated = _fold_result(getattr(o, "result", None), element_ids, seen, cap)
        if v is not None:
            open_view_id = v
        if fps:
            file_paths.extend(fps)
        if isolated:
            explicit_isolate_active = True
    return {
        "element_ids": element_ids,
        "open_view_id": open_view_id,
        "file_paths": file_paths,
        "explicit_isolate_active": explicit_isolate_active,
    }


# ── final-navigation codegen (_NAV_V2_CS) ──────────────────────────────────────

def build_nav_v2_code(
    element_ids: list[int],
    open_view_id: Optional[int],
    skip_unisolate: bool = False,
    cap: Optional[int] = None,
) -> Optional[str]:
    """Build the end-of-turn navigation C# snippet, or None if there is nothing to
    open/zoom to (verification 3c: an empty turn — no harvested ids, no created
    view — executes nothing; the un-isolate-all-views cleanup below is bundled into
    the same snippet, gated on there being real navigation work to show).

    Order (all in try/catch, mirrors the existing _NAV_CS style in chat_ws):
      1. Un-isolate on EVERY open UIView (not just the active one) — closes the
         "isolation stuck on a non-active view" incident. Skipped when
         ``skip_unisolate`` (an isolate survived coercion THIS turn — an explicit
         user ask must not be silently undone by the cleanup it shares a snippet
         with; part 4's contract is "isolated AND zoomed", not "isolated then
         immediately un-isolated").
      2. If open_view_id is given, open it (RequestViewChange, falling back to
         ActiveView= — both are the codebase's own documented pair, see
         kukai/llm/prompts.py's "ОТКРЫТЬ/показать вид" guidance).
      3. Else, if element_ids are non-empty, select + ShowElements them. Skipped
         entirely when a view was opened (step 2) — nothing to zoom to INSIDE a
         freshly opened schedule/sheet.
      4. Returns {"nav_opened": id|null, "nav_zoomed": count, "unisolated": n}.
    """
    cap = cap if cap is not None else nav_v2_id_cap()
    ids = [i for i in element_ids if isinstance(i, int)][:cap]
    if not ids and open_view_id is None:
        return None

    parts: list[str] = [
        "var __navRes=new Dictionary<string,object>();",
        "int __unisolated=0;",
    ]
    if skip_unisolate:
        parts.append("__navRes[\"unisolated\"]=0;")
    else:
        parts.append(
            "try{"
            "foreach(var __uv in uidoc.GetOpenUIViews()){"
            "try{"
            "var __v=doc.GetElement(__uv.ViewId) as View;"
            "if(__v!=null && __v.IsTemporaryHideIsolateActive()){"
            "using(var __t=new Transaction(doc,\"kukai_nav_v2_unisolate\")){"
            "__t.Start();"
            "__v.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate);"
            "__t.Commit();}"
            "__unisolated++;"
            "}"
            "}catch{}"
            "}"
            "}catch{}"
            "__navRes[\"unisolated\"]=__unisolated;"
        )

    if open_view_id is not None:
        parts.append(
            "try{"
            f"var __tv=doc.GetElement(new ElementId({int(open_view_id)})) as View;"
            "if(__tv!=null){"
            "try{uidoc.RequestViewChange(__tv);}"
            "catch{try{uidoc.ActiveView=__tv;}catch{}}"
            f"__navRes[\"nav_opened\"]={int(open_view_id)};"
            "}else{__navRes[\"nav_opened\"]=null;}"
            "}catch{__navRes[\"nav_opened\"]=null;}"
            "__navRes[\"nav_zoomed\"]=0;"
        )
    elif ids:
        ids_arr = ",".join(str(i) for i in ids)
        parts.append("__navRes[\"nav_opened\"]=null;")
        parts.append(
            "try{"
            "var __ids=new List<ElementId>();"
            f"foreach(var __n in new int[]{{{ids_arr}}}){{try{{__ids.Add(new ElementId(__n));}}catch{{}}}}"
            "if(__ids.Count>0){"
            "try{uidoc.Selection.SetElementIds(__ids);}catch{}"
            "try{uidoc.ShowElements(__ids);}catch{}"
            "__navRes[\"nav_zoomed\"]=__ids.Count;"
            "}else{__navRes[\"nav_zoomed\"]=0;}"
            "}catch{__navRes[\"nav_zoomed\"]=0;}"
        )
    else:
        parts.append("__navRes[\"nav_opened\"]=null;")
        parts.append("__navRes[\"nav_zoomed\"]=0;")

    parts.append("return __navRes;")
    return "".join(parts)


# ── per-action mid-turn zoom (throttled) ───────────────────────────────────────

def should_fire_mini_nav(last_fire_ts: Optional[float], now: float, min_interval_s: Optional[float] = None) -> bool:
    """Pure throttle gate — fire at most once per ``min_interval_s`` (turn-scoped
    monotonic clock in the caller). ``last_fire_ts=None`` (never fired yet) always
    fires."""
    min_interval_s = min_interval_s if min_interval_s is not None else mini_nav_throttle_s()
    if last_fire_ts is None:
        return True
    return (now - last_fire_ts) >= min_interval_s


def build_mini_nav_code(element_ids: list[int], cap: Optional[int] = None) -> Optional[str]:
    """Mid-turn zoom for ONE freshly-written tool result — select+ShowElements only
    (no un-isolate, no view-open: consolidation happens once at the end of the turn
    via build_nav_v2_code). Delegates to reveal.build_reveal_code — the exact same
    proven "select then ShowElements" primitive, avoiding a second implementation."""
    cap = cap if cap is not None else nav_v2_id_cap()
    ids = [i for i in element_ids if isinstance(i, int)][:cap]
    if not ids:
        return None
    from kukai.llm.reveal import build_reveal_code
    return build_reveal_code(ids)


# ── isolate → select coercion (part 4) ─────────────────────────────────────────

_ISOLATE_MARKERS = ("изолир", "isolate")


def user_requested_isolation(user_query: str) -> bool:
    q = (user_query or "").lower()
    return any(m in q for m in _ISOLATE_MARKERS)


def coerce_query_model_action(action: str, user_query: str) -> tuple[str, bool]:
    """query_model(action=isolate) → select, unless the user's turn text explicitly
    asked for isolation. Both values are valid `action`s for build_query_code, so
    this is a pure string swap. Returns (possibly-coerced action, was_coerced)."""
    if action == "isolate" and not user_requested_isolation(user_query):
        return "select", True
    return action, False


def should_coerce_hide_or_isolate(view_action: str, element_ids: Any, user_query: str) -> bool:
    """apply_revit_write(operation=hide_or_isolate, view_action=isolate) has no
    'select' verb of its own (generate_hide_or_isolate_code only emits
    HideElements/IsolateElementsTemporary) — so coercion REDIRECTS the whole call
    to a plain select (mirrors the select_elements tool) instead of relabeling an
    argument. Only coerces a non-empty element set — an empty set already hits the
    existing hide_or_isolate empty-set guard, untouched here."""
    return bool(
        view_action == "isolate"
        and element_ids
        and not user_requested_isolation(user_query)
    )
