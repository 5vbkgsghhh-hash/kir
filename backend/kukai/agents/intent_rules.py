"""Deterministic intent pre-classifier — the always-available backbone for the
router (Milestone 2). Pure keyword/length heuristics, no network, microseconds.

Returns the same metadata shape as the LLM ``IntentClassifier`` so the router
consumes one type. When the (DeepSeek-homed) LLM classifier runs and succeeds,
its result overlays this guess; on failure/timeout this is what the router uses
— so a request is NEVER blocked on classification, and the default tier is
deliberately CONSERVATIVE (modify/composite → generous rounds + high effort)
so a misclassification can never starve a real task.

Plan: /root/.claude/plans/recursive-inventing-lecun.md (Milestone 2).

Capability-first RAG, Stage 2 (/root/kukai-rag-audit/CAPABILITY_FIRST_RAG.md
§6 step 2): ``quick_classify`` also emits a best-effort OperationFrame
``action`` — derived from the SAME deterministic intent guess via
``kukai.agents.capability_vocab.derive_action_from_intent`` (the identical
map the LLM ``IntentClassifier`` falls back to when it omits `action`) — and
an empty ``object_kinds`` (no cheap rules-based object normalization at this
layer; left to the LLM classifier or the generation-time recipe slots). This
gives the offline harness and every fail-open path (LLM classifier down/slow)
an `action` without ever needing an LLM call.

Stage 2.1 (architect refinement, 2026-07-08, see STAGE2_1_REPORT.md): Stage
2's own measurement found quick_classify's 9 intent buckets can only ever
emit 9 of the 28 closed-vocab actions in practice (list/export are in the
map but unreachable; isolate/quantify/dimension/override_graphics/
create_view/join/transform/purge have no intent-bucket path to them at
all). `_refine_action` adds a second, additive pass over the raw query text
(checked AFTER the coarse intent->action derivation) that recognizes these
finer action verbs directly and overrides the coarse guess. It never
touches `intent` itself (still the validated 11-way enum every other
consumer -- router.py, converse_gate.py, grounding_gate.py,
recipes_collector.py -- depends on): `action` is documented as ADDITIVE and
FINER than `intent` (intent_classifier.py's own module docstring), so it is
free to diverge from the coarse per-intent default whenever the query names
a sharper verb.
"""
from __future__ import annotations

from typing import Any

from .capability_vocab import derive_action_from_intent

_CONVERSE = ("привет", "здравств", "спасибо", "кто ты", "что ты умеешь",
             "как дела", "hello", "hi ", "thanks")
_COUNT = ("сколько", "кол-во", "количество", "count", "how many")
_DIAGNOSE = ("почему", "ошибк", "не работает", "не видно", "проверь", "диагност")
_DELETE = ("удали", "удалить", "delete", "убери")
# Stage 2.1: export-flavoured keywords SPLIT OUT of _SCHEDULE into their own
# bucket (checked before _SCHEDULE below) — previously "выгрузи спецификацию
# в эксель" fell into intent="schedule" (action="schedule") because the
# export words lived inside the schedule tuple; `export` is itself a valid
# 11-way intent (and already in `derive_action_from_intent`'s map) that
# quick_classify simply never had a branch for.
_EXPORT = ("выгруз", "экспорт", "excel", "эксель", "pdf")
_SCHEDULE = ("спецификац", "ведомость", " вор")
_TAG = ("марк", "tag", "аннотац", "обознач")
_CREATE = ("создай", "создать", "построй", "добавь", "начерти", "нарисуй",
           "размести", "сделай лист", "create")
_FILTER = ("покажи", "список", "найди", "выдели", "перечисли", "выбери",
           "которые", "list", "select", "изолируй")
# Stage 2.1: "скопируй"/"массив" (transform verbs) added — previously
# neither was recognized as an action verb at all (a bare "скопируй колонну"
# fell through every bucket to the generic default AND was invisible to
# `_has_action_verb`, risking a converse misclassification for something
# like «привет, скопируй колонну»).
_MODIFY = ("измени", "покрась", "соедини", "перемести", "поверни",
           "переименуй", "закрепи", "modify", "join", "скопируй", "массив")

_COMPOUND_MARKERS = (" и ", "затем", "потом", "после чего", "а также", ";")

# ---------------------------------------------------------------------------
# Stage 2.1: action-only keyword groups — finer than the intent buckets
# above, with no natural 11-way `intent` counterpart (isolate/quantify/
# dimension/override_graphics/create_view/join/transform/purge aren't valid
# `intent` values), so `_refine_action` matches these directly against the
# query text and overrides the coarse per-intent `action` default WITHOUT
# touching `intent`. `_FIND_SELECT_STRONG` also fixes a real bucket-order
# collision: TAG is checked before FILTER below, so «найди стены с маркой
# СВ-1.1» lands in the `tag` bucket on the substring "марк" (inside
# "маркой") even though the query's actual verb is "найди" — an explicit
# find/select verb should win the ACTION regardless of which coarse intent
# bucket the noun collision produced.
# ---------------------------------------------------------------------------
_FIND_SELECT_STRONG = ("найди", "выдели", "найти", "выбери")
_ISOLATE_KW = ("изолир", "оставь только", "покажи только",
               "скрой всё кроме", "скрой все кроме",
               "спрячь всё кроме", "спрячь все кроме")
_QUANTIFY_QTY_KW = ("объём", "объем", "площад", "сумма")
_QUANTIFY_GROUP_KW = ("групп",)
_CREATE_VIEW_VERB_KW = ("созда", "сделай", "построй")
_CREATE_VIEW_NOUN_KW = (
    "вид", "разрез", "фасад", "аксонометр",
    "план этажа", "план потолка",
)
_CREATE_SHEET_NOUN_KW = ("лист", "sheet")
_JOIN_KW = ("соедини", "join geometry", "joingeometry")
_OVERRIDE_GFX_KW = ("покрась", "цвет", "невидим", "фильтр")
_DIMENSION_KW = ("образмерь", "размер")
_TRANSFORM_KW = ("перемести", "поверни", "скопируй", "массив")
_PURGE_KW = ("очисти", "неиспользуем")
_RENAME_KW = ("переимен", "перенумер", "rename", "renumber")
_SET_PARAM_VERB_KW = (
    "запиши", "установи", "задай", "присвой", "заполни", "пропиши",
    "измени параметр", "поменяй параметр",
)
_LINK_VERB_KW = ("подгруз", "загруз", "встав", "подключ", "свяж")
_LINK_NOUN_KW = ("связ", "revit link", "rvt")

# Action-verb groups: converse means the ABSENCE of an action, so a query that
# carries any of these must never be classified converse even if it also contains
# a greeting/meta substring (audit H4 — 'что ты умеешь'/'кто ты' were substring
# matches that silently disabled tools for real action requests).
#
# Stage 2.1: unioned with every action-only refinement group too (widening
# recall, never narrowing it — a query that additionally matches one of
# these only ever pushes a borderline turn from "converse" toward the safe
# "task" default, never the other way). Literal "привет" alone still
# matches no group here, so it stays converse exactly as before.
_ACTION_GROUPS = (
    _COUNT, _DIAGNOSE, _DELETE, _EXPORT, _SCHEDULE, _TAG, _CREATE, _FILTER, _MODIFY,
    _FIND_SELECT_STRONG, _ISOLATE_KW, _QUANTIFY_QTY_KW, _QUANTIFY_GROUP_KW,
    _CREATE_VIEW_NOUN_KW, _CREATE_SHEET_NOUN_KW, _JOIN_KW,
    _OVERRIDE_GFX_KW, _DIMENSION_KW,
    _TRANSFORM_KW, _PURGE_KW, _RENAME_KW, _SET_PARAM_VERB_KW,
    _LINK_VERB_KW,
)


def _has_action_verb(q: str) -> bool:
    return any(w in q for grp in _ACTION_GROUPS for w in grp)


def _compound(q: str) -> bool:
    return len(q) > 40 and any(m in q for m in _COMPOUND_MARKERS)


def _refine_action(action: str, q: str) -> str:
    """Stage 2.1: override the coarse intent-derived ``action`` with a
    sharper, directly-matched verb when the query names one — see the
    keyword-group block comment above. Checked in a fixed priority order
    (most specific / combined patterns first) so a real, narrow match always
    wins over a broader one; falls through to ``action`` unchanged if
    nothing more specific hits (the existing 9-action floor is always the
    worst case, never regressed).
    """
    if any(w in q for w in _SET_PARAM_VERB_KW) and "параметр" in q:
        return "set_param"
    if any(w in q for w in _LINK_VERB_KW) and any(w in q for w in _LINK_NOUN_KW):
        return "link"
    # A sheet is a ViewSheet container, not a model/drafting view.  Treating
    # every occurrence of ``лист`` as create_view made compound requests such
    # as "create a sheet and place a plan" route to the view-creation page and
    # hide the ViewSheet/Viewport recipe.  Preserve the coarse ``create``
    # action here; page evidence then distinguishes sheet creation from other
    # create operations without a model call.
    if any(w in q for w in _CREATE_VIEW_VERB_KW) and any(
        w in q for w in _CREATE_SHEET_NOUN_KW
    ):
        return "create"
    # create_view: needs BOTH a create-verb AND a view-ish noun — checked
    # first because "созда" alone is already claimed by the coarser CREATE
    # intent bucket, and this pattern must win over it when the noun is
    # present (e.g. «создай разрез по лестнице»).
    if any(w in q for w in _CREATE_VIEW_VERB_KW) and any(
        w in q for w in _CREATE_VIEW_NOUN_KW
    ):
        return "create_view"
    # find_select: an explicit find/select verb beats any noun-only bucket
    # collision (TAG's "марк" substring inside "маркой" etc.) — see
    # _FIND_SELECT_STRONG's docstring above.
    if any(w in q for w in _FIND_SELECT_STRONG):
        return "find_select"
    if any(w in q for w in _RENAME_KW):
        return "rename"
    if any(w in q for w in _ISOLATE_KW):
        return "isolate"
    if any(w in q for w in _QUANTIFY_QTY_KW) and (
        " по " in f" {q} " or any(w in q for w in _QUANTIFY_GROUP_KW)
    ):
        return "quantify"
    if any(w in q for w in _PURGE_KW):
        return "purge"
    if any(w in q for w in _JOIN_KW):
        return "join"
    if any(w in q for w in _OVERRIDE_GFX_KW):
        return "override_graphics"
    if any(w in q for w in _DIMENSION_KW):
        return "dimension"
    if any(w in q for w in _TRANSFORM_KW):
        return "transform"
    return action


def _bump(meta: dict[str, Any], q: str) -> dict[str, Any]:
    """Uplift complexity for long/compound requests.

    Also the common tail every ``quick_classify`` return path runs through —
    used here (Stage 2) to finalize the best-effort OperationFrame `action`
    from whatever `intent` bucket was just decided, and to default
    `object_kinds` to `[]` (no rules-based object normalization at this
    layer). One place, so every branch gets it for free instead of repeating
    the derivation at each `meta.update(...)` call site.

    Stage 2.1: the coarse per-intent `action` is then refined by
    ``_refine_action`` (see its docstring) — an additive, finer pass over
    the SAME query text that can reach action verbs no intent bucket maps
    to. `intent` itself is never touched by this refinement.
    """
    if len(q) > 200 or _compound(q):
        if meta["complexity"] in ("trivial", "simple"):
            meta["complexity"] = "composite"
        elif meta["complexity"] == "composite":
            meta["complexity"] = "hard"
    meta["action"] = _refine_action(
        derive_action_from_intent(meta.get("intent")), q,
    )
    # A direct literal/value write is unambiguously data/parameter I/O.  Do
    # not apply this to computed transfers such as "write room area into a
    # parameter": those need the source-domain recipe (and, in an LLM frame,
    # may become a composite operation).  The narrow value+parameter pair
    # gives the offline fallback enough domain evidence to distinguish a
    # write from read-only "find walls by Mark" recipes.
    if meta["action"] == "set_param" and "значен" in q and "параметр" in q:
        meta["domain"] = "data"
    meta.setdefault("object_kinds", [])
    return meta


def quick_classify(query: str) -> dict[str, Any]:
    """Best-effort deterministic intent metadata (always full-shaped)."""
    q = (query or "").lower().strip()
    meta: dict[str, Any] = {
        "intent": "modify", "complexity": "composite", "domain": "OTHER",
        "primary_class_hint": None, "should_emit_code": True,
        "entities": [], "source": "rules",
        "action": "set_param", "object_kinds": [],
    }
    if not q:
        return meta
    if any(w in q for w in _CONVERSE) and not _has_action_verb(q):
        meta.update(intent="converse", complexity="trivial", should_emit_code=False)
        return _bump(meta, q)
    if any(w in q for w in _COUNT):
        meta.update(intent="count", complexity="simple")
        return _bump(meta, q)
    if any(w in q for w in _DIAGNOSE):
        meta.update(intent="diagnose", complexity="composite")
        return _bump(meta, q)
    if any(w in q for w in _DELETE):
        meta.update(intent="delete", complexity="simple")
        return _bump(meta, q)
    if any(w in q for w in _EXPORT):
        meta.update(intent="export", complexity="simple")
        return _bump(meta, q)
    if any(w in q for w in _SCHEDULE):
        meta.update(intent="schedule", complexity="composite")
        return _bump(meta, q)
    if any(w in q for w in _TAG):
        meta.update(intent="tag", complexity="simple")
        return _bump(meta, q)
    if any(w in q for w in _CREATE):
        meta.update(intent="create", complexity="composite")
        return _bump(meta, q)
    if any(w in q for w in _FILTER):
        meta.update(intent="filter", complexity="simple")
        return _bump(meta, q)
    if any(w in q for w in _MODIFY):
        meta.update(intent="modify", complexity="composite")
        return _bump(meta, q)
    # No clear verb → conservative default (modify/composite): generous routing.
    return _bump(meta, q)


def overlay(rules_meta: dict[str, Any], llm_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Merge the LLM classifier over the deterministic guess: the LLM wins on any
    present key, rules fill gaps. This is the documented design — quick_classify
    is the FALLBACK, the LLM is primary (fixes the audit bug where the router ran
    on the keyword dictionary alone). LLM unavailable/empty → rules unchanged.
    """
    if not llm_meta:
        return rules_meta
    merged = dict(rules_meta)
    for k, v in llm_meta.items():
        if v is not None and v != "" and v != []:
            merged[k] = v
    merged["source"] = "llm+rules"
    return merged
