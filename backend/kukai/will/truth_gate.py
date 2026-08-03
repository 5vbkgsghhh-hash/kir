"""Step 8 (server half) — the "готово truth layer": Tier-0 fake-готово detector.

The disease (the project's root problem): on an ACTION-intent turn the model
asserts success — "готово / сделал / нашёл N стен, скопирую…" — while calling
ZERO world tools. Success is ASSERTED, never WITNESSED (~42% of action turns
historically). This module is the MEASUREMENT (shadow) + the optional
correction (enforce) for that failure mode.

Flag ``KUKAI_TRUTH_GATE`` — read from the environment AT CALL TIME
(:func:`gate_mode`), exactly like ``KUKAI_EXEC_PIPELINE`` in client.py:

  * unset / "0" / anything else (default) — OFF. The detector never runs; the
    turn is byte-identical to today.
  * ``"shadow"`` (alias ``"1"``)          — detect + RECORD only. One row per
    detection to ``data/telemetry/truth_gate.jsonl`` (via the plan-020
    telemetry_rag writer), one internal ``truth_gate`` StreamEvent (folded
    into the reasoning trace by chat_ws, never forwarded to the plugin), one
    audit_trace stage for audit sessions. The turn's behavior is UNCHANGED.
  * ``"enforce"``                         — after recording, the client loop
    forces EXACTLY ONE corrective round with ``tool_choice="required"``.
    Guards (all enforced at the client socket, client.py):
      - at most ONE corrective round per turn (``_truth_gate_corrections``);
      - never fires when code-salvage fired this turn (mutually exclusive);
      - the ``` code-fence veto below ALSO makes the two detectors disjoint
        by construction (code-in-text → code-salvage's cue, not ours);
      - if the corrective round still yields 0 tools → record "gave_up", stop.

The Tier-0 fire condition (ALL must hold — see :func:`detect`):
  1. the turn's ROUTER intent is an ACTION intent (``LLMClient._MUST_ACT_INTENTS``
     — the same set/value that drove the round-0 tool forcing), AND
  2. the turn made ZERO SUCCESSFUL world-tool calls (see :func:`is_world_tool`
     — everything except pure-knowledge lookups counts as "world"), AND
  3. the final assistant text makes a COMPLETION/OBSERVATION claim (the
     conservative RU+EN cue set below) and no veto matches.

Design bias: CONSERVATIVE. False positives are cheap in shadow but must be low
if enforce is ever flipped — hence word-boundary cues, an explicit veto list
(honest failure reports, clarifying questions, code fences), and "unknown
intent → never fire". Fail-open everywhere: this module never raises into the
turn (the client socket additionally wraps every call).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flag (read at call time — never frozen at import)
# ---------------------------------------------------------------------------


def gate_mode() -> str:
    """Return "" (off) / "shadow" / "enforce" from KUKAI_TRUTH_GATE.

    Read from os.environ on EVERY call so ops can flip the flag on a live
    process the same way KUKAI_EXEC_PIPELINE is read (client.py:2325).
    "1" aliases to "shadow" (the safe interpretation of a bare flag flip);
    any unrecognized value is OFF — a typo can never accidentally enforce.
    """
    v = os.environ.get("KUKAI_TRUTH_GATE", "0").strip().lower()
    if v in ("shadow", "1"):
        return "shadow"
    if v == "enforce":
        return "enforce"
    return ""


# ---------------------------------------------------------------------------
# World tools — what counts as WITNESSING/ACTING on the world
# ---------------------------------------------------------------------------

# Classified by EXCLUSION on purpose: an unknown/new tool defaults to "world",
# which can only SUPPRESS a detection (world_tool_successes > 0 → no fire).
# That is the conservative direction — a too-narrow world set would create
# false positives; a too-broad one only costs recall.
#   lookup_norm — pure knowledge-base lookup; it witnesses nothing about the
#   user's model and performs no action, so a turn that ONLY looked up norms
#   and then claimed "готово" is still unwitnessed.
_NON_WORLD_TOOLS = frozenset({"lookup_norm"})


def is_world_tool(tool_name: str) -> bool:
    """True iff a SUCCESSFUL call of this tool witnesses or acts on the world
    (Revit model, files, user-visible artifacts) — i.e. it can honestly back a
    completion/observation claim."""
    return bool(tool_name) and tool_name not in _NON_WORLD_TOOLS


# ---------------------------------------------------------------------------
# Action intents — single source of truth is LLMClient._MUST_ACT_INTENTS
# ---------------------------------------------------------------------------

# Defensive literal copy used ONLY if the client import fails (e.g. partial
# deployment). MUST mirror client.py:1386.
_FALLBACK_ACTION_INTENTS = frozenset(
    {"create", "modify", "delete", "schedule", "tag", "filter", "count", "list", "export"}
)


def _action_intents() -> frozenset:
    """The action-intent set, read from the client (the SAME set that drives
    round-0 tool forcing) so the two mechanisms can never drift apart."""
    try:
        from kukai.llm.client import LLMClient
        return LLMClient._MUST_ACT_INTENTS
    except Exception:  # noqa: BLE001 — fail-open to the mirrored literal
        return _FALLBACK_ACTION_INTENTS


# ---------------------------------------------------------------------------
# Cue set — conservative RU+EN completion/observation claims
# ---------------------------------------------------------------------------

# Each cue is (id, compiled regex). Word-boundary anchored (\b works for
# Cyrillic in Python's unicode str patterns) so "готовое"/"готовности" never
# match. Perfective past forms + the canonical future-promise "скопирую"
# (the exact prod shape: "нашёл N стен, скопирую…" and stops).
_CUES: list[tuple[str, re.Pattern]] = [
    ("gotovo",       re.compile(r"\bготово\b", re.IGNORECASE)),
    ("sdelal",       re.compile(r"\bсдела(?:л|ла|ли|но)\b", re.IGNORECASE)),
    ("vypolnil",     re.compile(r"\bвыполн(?:ил|ила|или|ено|ены)\b", re.IGNORECASE)),
    ("zavershil",    re.compile(r"\bзаверш(?:ил|ила|или|ено|ена)\b", re.IGNORECASE)),
    ("sozdal",       re.compile(r"\bсозда(?:л|ла|ли|но|ны)\b", re.IGNORECASE)),
    ("skopiroval",   re.compile(r"\bскопир(?:овал|овала|овали|овано|ованы|ую)\b", re.IGNORECASE)),
    ("udalil",       re.compile(r"\bудал(?:ил|ила|или|ено|ены|ён|ёны)\b", re.IGNORECASE)),
    ("izmenil",      re.compile(r"\bизмен(?:ил|ила|или|ено|ены|ён)\b", re.IGNORECASE)),
    ("pereimenoval", re.compile(r"\bпереименова(?:л|ла|ли|но|ны)\b", re.IGNORECASE)),
    ("dobavil",      re.compile(r"\bдобав(?:ил|ила|или|лено|лены)\b", re.IGNORECASE)),
    ("razmestil",    re.compile(r"\bразмест(?:ил|ила|или)\b|\bразмещ(?:ено|ены|ён)\b", re.IGNORECASE)),
    ("postroil",     re.compile(r"\bпостро(?:ил|ила|или|ено|ены)\b", re.IGNORECASE)),
    # Observation claims — "нашёл N …" with zero tools is a FABRICATED count.
    # (Known Tier-0 blind spot: a claim backed by a PREVIOUS turn's tool result
    # is invisible per-turn — see REVIEW NOTES; acceptable for shadow.)
    ("nashel",       re.compile(r"\bнаш(?:ёл|ел|ла|ли)\b|\bнайден[оыа]?\b|\bобнаруж(?:ил|ила|или|ено|ены)\b", re.IGNORECASE)),
    # English (the model occasionally answers in EN).
    ("en_done",      re.compile(r"\b(?:done|completed)\b", re.IGNORECASE)),
    ("en_did",       re.compile(r"\bi(?:'ve| have)? (?:created|copied|deleted|added|placed|built|renamed|modified)\b", re.IGNORECASE)),
    ("en_found",     re.compile(r"\bfound \d+\b", re.IGNORECASE)),
]

# Vetoes — ANY match anywhere in the text suppresses the detection. These are
# the "model is being honest / asking / writing code" shapes; punishing them
# would be a false positive even in shadow statistics.
_VETOES: list[tuple[str, re.Pattern]] = [
    # Honest failure report ("не удалось…", "ошибка CS…", "failed").
    ("failure", re.compile(
        r"не\s+(?:удалось|получилось|смог|смогла|могу|вышло)"
        r"|ошибк|исключени|failed|error|unable|cannot|can['’]t",
        re.IGNORECASE)),
    # Physically impossible right now (no document / bridge down) — honest.
    ("impossible", re.compile(
        r"невозможно|нельзя\b|нет открытого документа|документ не открыт"
        r"|не подключ|подключите",
        re.IGNORECASE)),
    # Code fence — code-in-text is the code-salvage detector's territory
    # (client.py:2764); staying out keeps the two correctives disjoint.
    ("code_fence", re.compile(r"```")),
]

# A trailing question is (usually) the model ASKING before acting — correct
# behavior. But only when the cue itself sits inside that final question;
# "Готово! Ещё что-то?" claims completion in an earlier sentence and must
# still fire. Sentence boundary = last . ! ? or newline BEFORE the tail "?".
_SENTENCE_SPLIT = re.compile(r"[.!?\n]")


def _find_claim(text: str) -> Optional[tuple[str, int]]:
    """Return (cue_id, match_start) of the first matching cue, else None."""
    for cue_id, rx in _CUES:
        m = rx.search(text)
        if m:
            return cue_id, m.start()
    return None


def _vetoed(text: str) -> Optional[str]:
    """Return the id of the first matching veto, else None."""
    for veto_id, rx in _VETOES:
        if rx.search(text):
            return veto_id
    return None


def _claim_inside_trailing_question(text: str, claim_start: int) -> bool:
    """True iff the text ends with '?' AND the matched claim lies in that final
    question sentence (→ treat as a clarifying question, do not fire)."""
    stripped = text.rstrip()
    if not stripped.endswith("?"):
        return False
    # Start of the final sentence = one past the previous sentence terminator.
    last_boundary = 0
    for m in _SENTENCE_SPLIT.finditer(stripped[:-1]):
        last_boundary = m.end()
    return claim_start >= last_boundary


# ---------------------------------------------------------------------------
# The Tier-0 detector
# ---------------------------------------------------------------------------


def detect(
    *,
    intent: Optional[str],
    world_tool_successes: int,
    tool_calls_total: int,
    final_text: Optional[str],
) -> Optional[dict]:
    """The Tier-0 fire condition. Returns a signal row (dict) or None.

    Fires iff ALL hold:
      * ``intent`` is a known ACTION intent (unknown/None → never fire);
      * ``world_tool_successes == 0`` (nothing witnessed this turn);
      * ``final_text`` contains a completion/observation cue;
      * no veto matches (honest failure / clarifying question / code fence).

    Pure and synchronous — no I/O, no env reads (the caller gates on
    :func:`gate_mode`). Never raises on any str input.
    """
    if not final_text or not intent:
        return None
    if intent not in _action_intents():
        return None
    if world_tool_successes > 0:
        return None

    claim = _find_claim(final_text)
    if claim is None:
        return None
    cue_id, claim_start = claim

    veto = _vetoed(final_text)
    if veto is not None:
        return None
    if _claim_inside_trailing_question(final_text, claim_start):
        return None

    return {
        "signal": "fake_gotovo",
        "intent": intent,
        "world_tool_successes": int(world_tool_successes),
        "tool_calls_total": int(tool_calls_total),
        "cue": cue_id,
        "text_preview": final_text[:300],
    }


# ---------------------------------------------------------------------------
# Tier-1 — claim-witness reconciliation ("fabricated_count"), IQ moment #4
#
# The other half of fake-готово: the model DID run tools but MISREPORTS them —
# "нашёл 42 стены" when the tool returned 17; "создано 5 колонн" when no
# result mentions any such count. Tier-0 is structurally blind here
# (world_tool_successes > 0 suppresses it); Tier-1 reconciles the numeric
# claims in the final TEXT against the set of numbers actually present in
# this turn's tool RESULTS (see the REVIEW-NOTES blind spot above).
#
# Deterministic and LLM-free (IRON 3): regex + lexicon only. SHADOW-ONLY by
# design — even under KUKAI_TRUTH_GATE=enforce Tier-1 never injects a
# corrective round and never mutates the turn; it only emits a signal row
# (enforcement is a later operator decision, gated on measured precision).
#
# Design bias: PRECISION over recall — a noisy Tier-1 can never be promoted.
# A claim is "fabricated_count" ONLY if ALL hold:
#   (a) count-of-elements claim: NUMBER immediately followed by a countable
#       element noun (lexicon below, stem-matched for RU morphology), with an
#       action/finding verb (нашёл/создано/удалено/…) in the same sentence;
#   (b) the number appears in NO tool result text of this turn — literal
#       digits (incl. RU thousands grouping) AND structural witnesses (JSON
#       list lengths + their sums: an honestly COUNTED list is witnessed);
#   (c) world tools actually succeeded this turn (else Tier-0's territory).
# Everything ambiguous is skipped: dimensions («400x400», «толщиной 200»),
# storey/level names («на 3 этаже», «уровень 2»), ordinals («3-й»), grid axes
# («оси 1–80»), element ids (id follows the noun — wrong word order), dates/
# times/percent (glued suffix), approximations («примерно 40»), numbers in
# code fences, honest failure reports (Tier-0 veto lexicon reused).
# ---------------------------------------------------------------------------

# Code is never a claim: fenced/inline code is stripped BEFORE extraction
# (Tier-0 vetoes the whole text on a fence — Tier-1 evaluates the prose).
_T1_FENCE_RX = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
_T1_INLINE_CODE_RX = re.compile(r"`[^`\n]{1,300}`")

# RU thousands grouping («1 234», NBSP variants) preferred over bare digits.
_T1_GROUPED_NUM = r"\d{1,3}(?:[   ]\d{3})+"
_T1_GROUPED_RX = re.compile(_T1_GROUPED_NUM)
_T1_DIGITS_RX = re.compile(r"\d+")

# Candidate claim: NUMBER + same-line whitespace + a following word. The word
# must pass the countable-noun lexicon; same-line ([ \t]) so a claim never
# spans sentences/bullets.
_T1_CLAIM_RX = re.compile(
    r"(?P<num>" + _T1_GROUPED_NUM + r"|\d+)"
    r"[ \t]+(?P<noun>[A-Za-zА-Яа-яЁё]+)"
)

# Countable element nouns — stem match (first-chars, ≤5 trailing chars of
# inflection: стен→стены/стен/стенах, помещен→помещений/помещения…). All
# stems are ё→е normalized. Deliberately EXCLUDED: шаг/пункт/вариант/способ
# (model meta-talk), units (мм/см/м/градус), время/минут (durations).
_T1_NOUN_STEMS = (
    "шт",
    # generic
    "элемент", "объект", "экземпляр", "единиц",
    # structure / architecture
    "стен", "колонн", "балк", "балок", "перекрыт", "плит", "фундамент",
    "кровел", "крыш", "лестниц", "ступен", "витраж", "панел",
    "проем", "отверст", "помещен", "комнат", "уровн", "этаж",
    "двер", "окон", "окн",
    # MEP
    "труб", "воздуховод", "светильник", "розетк", "выключател",
    "прибор", "стояк", "фитинг", "соединен",
    # documentation / data
    "вид", "лист", "спецификац", "марк", "аннотац", "размер",
    "семейств", "тип", "категор", "параметр", "материал", "значен",
    "групп", "фильтр",
    # english
    "wall", "column", "door", "window", "element", "item", "room",
    "level", "pipe", "duct", "view", "sheet", "famil", "instance",
    "parameter", "object", "beam", "floor", "ceiling",
)

# Action/finding verbs that turn "N noun" into a WORLD claim. Perfective past
# + short passive participles (RU), simple past (EN). Futures/infinitives/
# imperatives deliberately absent — promises and plans are not claims.
_T1_VERB_RX = re.compile(
    r"\b(?:"
    r"наш(?:ёл|ел|ла|ли)|найден(?:а|о|ы)?|"
    r"обнаружил(?:а|и)?|обнаружен(?:а|о|ы)?|"
    r"созда(?:л|ла|ли|н|на|но|ны)|"
    r"удал(?:ил|ила|или|ён|ен|ена|ено|ены)|"
    r"измен(?:ил|ила|или|ён|ен|ена|ено|ены)|"
    r"скопирова(?:л|ла|ли|н|на|но|ны)|"
    r"добав(?:ил|ила|или|лен|лена|лено|лены)|"
    r"размест(?:ил|ила|или)|размещ(?:ён|ен|ена|ено|ены)|"
    r"постро(?:ил|ила|или|ен|ена|ено|ены)|"
    r"переименова(?:л|ла|ли|н|на|но|ны)|"
    r"насчит(?:ал|ала|али|ано)|насчитыва(?:ю|е)тся|"
    r"получ(?:илось|ен|ена|ено|ены)|"
    r"выбра(?:л|ла|ли|н|на|но|ны)|"
    r"выдел(?:ил|ила|или|ен|ена|ено|ены)|"
    r"обработа(?:л|ла|ли|н|на|но|ны)|"
    r"перемещ(?:ён|ен|ена|ено|ены)|перен(?:ёс|ес)|перенес(?:ла|ли)|перенесен(?:а|о|ы)?|"
    r"вставил(?:а|и)?|вставлен(?:а|о|ы)?|"
    r"содержит(?:ся)?|содержат(?:ся)?|имеется|имеются|"
    r"found|created|deleted|removed|added|copied|placed|modified|"
    r"changed|renamed|moved|detected|counted|identified|contains|there\s+are"
    r")\b",
    re.IGNORECASE,
)

# Number glued to the previous char → part of a larger token, never a count:
# decimals/ranges/dimensions/times/ratios («400x400», «1-80», «17:30», «2.5»).
_T1_GLUED_CHARS = frozenset("0123456789.,:;-–—/\\×xх*+^%№#")

# Word immediately before the number that DISQUALIFIES the claim: locative
# prepositions (storey/level/axis names), approximations (rounded talk is not
# an exact count), and name/dimension carriers. ё→е normalized, lowercase.
_T1_PREV_BLACKLIST = frozenset({
    # prepositions → «на 3 этаже», «в 2 корпусе», «с 5 стенами»
    "на", "в", "во", "с", "со", "по", "до", "от", "за", "к", "ко", "у",
    "о", "об", "при", "под", "над", "между", "через",
    # approximations / bounds
    "около", "примерно", "почти", "более", "менее", "свыше", "минимум",
    "максимум", "порядка", "чем",
    # names / ids / versions / dimensions
    "№", "номер", "уровень", "уровня", "уровне", "этаж", "этажа", "этаже",
    "ось", "оси", "осях", "id", "ид", "версия", "версии", "версию", "revit",
    "страница", "стр", "шаг", "шагом", "радиус", "радиусом", "диаметр",
    "диаметром", "толщина", "толщиной", "высота", "высотой", "ширина",
    "шириной", "длина", "длиной", "сечение", "сечением", "отметка",
    "отметке", "отметку",
    # english
    "on", "at", "in", "to", "of", "from", "by", "with", "than", "about",
    "approximately", "around", "over", "under", "level", "floor", "storey",
    "page", "axis", "grid", "version", "least",
})

_T1_SENT_BOUNDARY = re.compile(r"[.!?\n]")

# Tier-1 reuses the honest-failure/impossible vetoes; the code-fence veto is
# replaced by fence STRIPPING (a prose claim next to a code block is still a
# claim — but code contents never are).
_T1_VETO_IDS = frozenset({"failure", "impossible"})

_T1_MAX_CLAIMS = 20          # bound work + row size on pathological text
_T1_MAX_WITNESS_TEXTS = 200  # bound work on pathological turns
_T1_MAX_COUNT = 1_000_000    # bigger numbers are ids/areas, never counts


def _t1_noun_ok(noun: str) -> bool:
    """True iff `noun` stem-matches a countable element noun (≤5 chars of
    inflection after the stem — «стенах» yes, «стенография» no)."""
    n = noun.lower().replace("ё", "е")
    for stem in _T1_NOUN_STEMS:
        if n.startswith(stem) and len(n) <= len(stem) + 5:
            return True
    return False


def _t1_prev_token(text: str, pos: int) -> Optional[str]:
    """The word (or terminal punctuation char) immediately before `pos`,
    lowercased and ё→е normalized. None at start of text."""
    prefix = text[:pos].rstrip()
    if not prefix:
        return None
    m = re.search(r"([\w№#]+)\Z", prefix)
    if m is None:
        return prefix[-1]
    return m.group(1).lower().replace("ё", "е")


def _t1_verb_near(text: str, num_start: int, noun_end: int) -> Optional[str]:
    """The claim verb near the number, or None. Search the SAME sentence:
    ≤90 chars before the number («Нашёл … 42 стены», «Найдено: 42 стены»),
    else ≤40 chars after the noun («42 стены созданы»)."""
    sent_start = 0
    for m in _T1_SENT_BOUNDARY.finditer(text, 0, num_start):
        sent_start = m.end()
    before = text[max(sent_start, num_start - 90):num_start]
    m = _T1_VERB_RX.search(before)
    if m:
        return m.group(0)
    b = _T1_SENT_BOUNDARY.search(text, noun_end)
    sent_end = b.start() if b else len(text)
    after = text[noun_end:min(sent_end, noun_end + 40)]
    m = _T1_VERB_RX.search(after)
    return m.group(0) if m else None


def _extract_count_claims(final_text: str) -> list[dict]:
    """Extract count-of-elements claims from the final answer text.

    Returns [{"number", "noun", "verb", "quote"}] — deduped by (number, noun),
    capped at _T1_MAX_CLAIMS. Every guard errs toward NOT claiming.
    """
    text = _T1_FENCE_RX.sub(" ", final_text)
    text = _T1_INLINE_CODE_RX.sub(" ", text)
    claims: list[dict] = []
    seen: set = set()
    for m in _T1_CLAIM_RX.finditer(text):
        noun = m.group("noun")
        if not _t1_noun_ok(noun):
            continue
        num_start = m.start("num")
        # Part of a larger token? («400x400», «1–80», «17:30», «2.5», «№42»)
        if num_start > 0 and text[num_start - 1] in _T1_GLUED_CHARS:
            continue
        value = int(re.sub(r"\D", "", m.group("num")))
        if value > _T1_MAX_COUNT:
            continue
        prev = _t1_prev_token(text, num_start)
        if prev is not None and (prev.isdigit() or prev in _T1_PREV_BLACKLIST):
            continue
        verb = _t1_verb_near(text, num_start, m.end("noun"))
        if verb is None:
            continue
        key = (value, noun.lower())
        if key in seen:
            continue
        seen.add(key)
        claims.append({
            "number": value,
            "noun": noun,
            "verb": verb,
            "quote": text[max(0, num_start - 40):m.end("noun") + 20].strip(),
        })
        if len(claims) >= _T1_MAX_CLAIMS:
            break
    return claims


# JSON keys whose numeric values are element COUNTS — the model may honestly
# SUM them («содержится 1231 элементов» = Σ per-category counts; «все 19
# фильтров» = Σ step totals). Calibration 2026-07-05: this derived-sum class
# was 15 of 16 raw fires — derived sums MUST be witnessed numbers.
_T1_COUNT_KEYS = frozenset({
    "count", "total", "qty", "quantity", "num", "n", "size", "amount",
    "found", "created", "deleted", "removed", "modified", "copied",
    "placed", "moved", "renamed", "added",
})


# Relative tolerance applied to DERIVED SUMS only (never to literal numbers):
# the model aggregates per-category counts with subset arithmetic («241
# элемент» vs Σcounts=242 — calibration fires #7/#8) — a hair off a witnessed
# sum is honest math, not fabrication. 42-vs-17 stays a fire (147% off).
_T1_SUM_TOLERANCE = 0.03


def _witness_numbers(texts: list) -> tuple:
    """(numbers, sums) a tool result could honestly back: literal digit runs
    (incl. RU thousands grouping) + structural witnesses from JSON — each
    list's length, sums of count-like fields (see _T1_COUNT_KEYS), and the
    per-result + grand totals of both (an honestly COUNTED list or an
    honestly SUMMED set of counts is a witnessed number). ``sums`` carries
    the aggregate values separately so the caller can apply
    _T1_SUM_TOLERANCE to them alone."""
    nums: set = set()
    sums: set = set()
    grand_list_total = 0
    grand_count_total = 0
    for t in texts[:_T1_MAX_WITNESS_TEXTS]:
        if not isinstance(t, str) or not t:
            continue
        for gm in _T1_GROUPED_RX.finditer(t):
            nums.add(int(re.sub(r"\D", "", gm.group(0))))
        for dm in _T1_DIGITS_RX.finditer(t):
            g = dm.group(0)
            if len(g) <= 12:
                nums.add(int(g))
        list_total = 0
        count_total = 0
        try:
            obj = json.loads(t)
        except Exception:  # noqa: BLE001 — non-JSON text: literal scan only
            obj = None
        if obj is not None:
            budget = 100_000  # node cap on pathological payloads
            stack = [obj]
            while stack and budget > 0:
                budget -= 1
                cur = stack.pop()
                if isinstance(cur, list):
                    nums.add(len(cur))
                    list_total += len(cur)
                    stack.extend(cur)
                elif isinstance(cur, dict):
                    for k, v in cur.items():
                        if (
                            isinstance(v, (int, float))
                            and not isinstance(v, bool)
                            and str(k).lower() in _T1_COUNT_KEYS
                        ):
                            try:
                                count_total += int(v)
                            except (OverflowError, ValueError):
                                pass
                    stack.extend(cur.values())
                elif isinstance(cur, bool):
                    continue
                elif isinstance(cur, (int, float)):
                    try:
                        iv = int(cur)
                        if float(iv) == float(cur):
                            nums.add(abs(iv))
                    except (OverflowError, ValueError):
                        pass
        nums.add(list_total)
        nums.add(count_total)
        sums.add(list_total)
        sums.add(count_total)
        grand_list_total += list_total
        grand_count_total += count_total
    nums.add(grand_list_total)
    nums.add(grand_count_total)
    sums.add(grand_list_total)
    sums.add(grand_count_total)
    return nums, sums


def _approx_sum_match(value: int, sums: set) -> bool:
    """True iff ``value`` is within _T1_SUM_TOLERANCE of any witnessed SUM
    (relative-only: a zero/absent sum never matches anything but itself)."""
    for s in sums:
        if s > 0 and abs(value - s) <= _T1_SUM_TOLERANCE * s:
            return True
    return False


def detect_tier1(
    *,
    intent: Optional[str],
    world_tool_successes: int,
    tool_calls_total: int,
    final_text: Optional[str],
    tool_result_texts: Optional[list],
    context_texts: Optional[list] = None,
) -> Optional[dict]:
    """The Tier-1 fire condition. Returns a signal row (dict) or None.

    Fires iff ALL hold:
      * world tools SUCCEEDED this turn (zero-tool turns are Tier-0's
        territory — the two tiers are disjoint by construction);
      * the final text makes ≥1 count-of-elements claim (number + countable
        noun + action/finding verb in the same sentence);
      * ≥1 claimed number is witnessed by NO tool result of this turn AND
        not by ``context_texts`` (the pushed model context / system prompt —
        the gestalt's numbers are real world state; echoing them is honest);
      * no honest-failure/impossible veto matches.

    No intent gate: a fabricated count is a fabricated count on any routed
    intent — the claim grammar itself is the precision device (intent is
    still recorded for slicing). Fail-open: never raises, never mutates.
    """
    try:
        if not final_text:
            return None
        if world_tool_successes <= 0:
            return None
        if not tool_result_texts:
            return None
        if _vetoed_tier1(final_text) is not None:
            return None
        claims = _extract_count_claims(final_text)
        if not claims:
            return None
        witness, sums = _witness_numbers(list(tool_result_texts))
        if context_texts:
            ctx_nums, ctx_sums = _witness_numbers(list(context_texts))
            witness |= ctx_nums
            sums |= ctx_sums
        unwitnessed = [
            c for c in claims
            if c["number"] not in witness
            and not _approx_sum_match(c["number"], sums)
        ]
        if not unwitnessed:
            return None
        return {
            "signal": "fabricated_count",
            "tier": 1,
            "intent": intent,
            "world_tool_successes": int(world_tool_successes),
            "tool_calls_total": int(tool_calls_total),
            "claims_total": len(claims),
            "claims_witnessed": len(claims) - len(unwitnessed),
            "unwitnessed": [dict(c) for c in unwitnessed[:5]],
            "witness_numbers_count": len(witness),
            "text_preview": final_text[:300],
        }
    except Exception:  # noqa: BLE001 — the truth gate must never break a turn
        logger.debug("truth_gate.detect_tier1 failed (fail-open)", exc_info=True)
        return None


def _vetoed_tier1(text: str) -> Optional[str]:
    """Tier-1 veto = Tier-0's honest-failure/impossible cues only (the code
    fence is handled by stripping, not vetoing)."""
    for veto_id, rx in _VETOES:
        if veto_id in _T1_VETO_IDS and rx.search(text):
            return veto_id
    return None


# ---------------------------------------------------------------------------
# Recording (fire-and-forget; reuses the plan-020 telemetry_rag JSONL writer)
# ---------------------------------------------------------------------------


def _current_query_id() -> Optional[str]:
    """The ambient turn's query_id (joins truth_gate.jsonl to rag_retrieval /
    eval_verdicts rows). Mirrors kukai/will/shadow.py:57. Never raises."""
    try:
        from kukai.rag import retrieval_health
        h = retrieval_health.current()
        return h.query_id if h is not None else None
    except Exception:  # noqa: BLE001 — telemetry helper must never break a turn
        return None


def record(signal: dict) -> None:
    """Append one detection row to data/telemetry/truth_gate.jsonl.

    Non-blocking (background writer thread), PII-scrubbed preview, NEVER
    raises — recording failure must never break or delay the user's turn.
    """
    try:
        row = dict(signal)
        try:
            from kukai.telemetry_rag import _scrub_pii
            if isinstance(row.get("text_preview"), str):
                row["text_preview"] = _scrub_pii(row["text_preview"])
            # Tier-1 claim quotes are answer-text excerpts — scrub them too.
            # Rebuild (don't mutate) so the already-emitted StreamEvent /
            # audit copies of the same nested dicts are untouched.
            if isinstance(row.get("unwitnessed"), list):
                row["unwitnessed"] = [
                    {**c, "quote": _scrub_pii(c["quote"])}
                    if isinstance(c, dict) and isinstance(c.get("quote"), str)
                    else c
                    for c in row["unwitnessed"]
                ]
        except Exception:  # noqa: BLE001 — scrubbing is best-effort
            pass
        from kukai.telemetry_rag import log_truth_gate
        log_truth_gate(_current_query_id(), row)
    except Exception as e:  # noqa: BLE001 — fail-open, but visibly
        logger.debug("truth_gate.record failed (non-fatal)", exc_info=True)
        try:
            from kukai.telemetry import note_telemetry_failure
            note_telemetry_failure(e)
        except Exception:  # noqa: BLE001
            pass


# The ONE corrective nudge used by enforce mode (client.py socket). Mirrors
# the code-salvage message shape (client.py:2772) — imperative, tool-only.
CORRECTIVE_PROMPT = (
    "Ты сообщил пользователю о результате действия, но НЕ вызвал ни одного "
    "инструмента — в Revit ничего не выполнено и не проверено. НЕ повторяй "
    "текст ответа. ВЫПОЛНИ действие сейчас: вызови подходящий инструмент "
    "(execute_revit_code / query_model / get_model_info и т.д.). Если действие "
    "выполнить невозможно — вызови инструмент проверки состояния модели и "
    "честно опиши пользователю, что именно не удалось."
)


def evaluate(
    *,
    intent: Optional[str],
    world_tool_successes: int,
    tool_calls_total: int,
    final_text: Optional[str],
    tool_result_texts: Optional[list] = None,
    context_texts: Optional[list] = None,
) -> dict:
    """The ONE combined truth-gate pass (2026-07-10) — replaces the separate
    detect()/detect_tier1() hook calls so a turn runs a SINGLE pure evaluation
    and makes AT MOST ONE corrective-round decision (no latency stacking).

    Runs, in one pass:
      * Tier-0 (fake-готово)      → can CORRECT (force a tool round);
      * Tier-1 (fabricated_count) → SHADOW only, never corrects.

    (An arithmetic-consistency "Tier-2" was prototyped 2026-07-10 and dropped:
    modern models don't self-contradict on "X из Y" / percentages, and the real
    error class — plausible-but-wrong numbers — is internally consistent, so it
    needs a second-method re-derivation, not this pure text check.)

    Returns ``{"signals": [<signal dict>, ...], "correction": None | {...}}``.
    ``correction`` (at most one, Tier-0 wins the slot) is
    ``{"tier", "reason", "prompt", "force_tools"}``; the client socket decides
    whether to APPLY it (enforce mode + its guards). Pure / fail-open."""
    signals: list[dict] = []
    correction: Optional[dict] = None
    try:
        t0 = detect(
            intent=intent, world_tool_successes=world_tool_successes,
            tool_calls_total=tool_calls_total, final_text=final_text)
        if t0 is not None:
            signals.append(t0)
            correction = {"tier": 0, "reason": t0.get("signal", "fake_gotovo"),
                          "prompt": CORRECTIVE_PROMPT, "force_tools": True}

        t1 = detect_tier1(
            intent=intent, world_tool_successes=world_tool_successes,
            tool_calls_total=tool_calls_total, final_text=final_text,
            tool_result_texts=tool_result_texts, context_texts=context_texts)
        if t1 is not None:
            signals.append(t1)                       # Tier-1 never corrects
    except Exception:  # noqa: BLE001 — the truth gate must never break a turn
        logger.debug("truth_gate.evaluate failed (fail-open)", exc_info=True)
    return {"signals": signals, "correction": correction}
