"""WHAT shape of schema the model gets — and WHY exactly this one.

`schema_gen.program_schema()` spells out every selector verbatim, so two
thirds of the schema is repetition. `schema_dedup.hoist` hoists that
repetition into `$defs`, hiding nothing from view. Only ONE question is
decided here: does `$ref` arrive at the model intact on THIS deployment. The
answer must be measured, not assumed, so the list of safe transports is a
table of measurements, not a list of hopes.

MEASURED LIVE ON 09.08.2026, both arms with the same request (max_tokens=1,
tool_choice=auto), the number taken from the PROVIDER's `usage.prompt_tokens`,
not from our own tokenizer:

    transport                        flat      collapsed    factor
    openrouter/deepseek-v4-flash     42 390     11 751       3.61x   HTTP 200 both
    openai/gpt-5.6-sol (CLIProxy)    20 628      3 633       5.68x   HTTP 200 both

The same measurement on the FULL `revit_ir` tool (description + program +
program_py), with the same provider held fixed: 53 914 → 23 275 tokens, a
saving of 30 639 on EVERY turn.

WHY CONDITIONAL, NOT ALWAYS. The cost of an error is asymmetric and already
named in `serving.inject_revit_ir_schema`: a provider that rejects the whole
tool bundle breaks the TURN — that is, all capabilities at once, not just
one. So the transformation is applied only where acceptance of `$ref` is
MEASURED, and everywhere else the schema stays exactly as it was, with the
reason NAMED (the law "nothing silently").

TWO KINDS OF "CANNOT," AND THEY MUST BE TOLD APART:
  * UNKNOWN — the transport has not been measured. We stay silent and leave
    the schema alone.
  * POINTLESS — litellm itself expands `$defs` back before sending
    (`llms/vertex_ai/common_utils.py::_build_vertex_schema` → `unpack_defs`,
    called on the `parameters` of EVERY function declaration, line 584 in
    the installed version). On gemini/vertex the hoist saves not a single
    token — meaning doing it there is not "unsafe," it is simply pointless.

WHAT IS NOT HERE AND WHAT HONESTLY REMAINS OPEN. It is measured that `$ref`
ARRIVES and that it is CHEAPER. It is NOT measured whether the working model
reads a schema with references as well as it reads a flat one: that is an
A/B on `tools/design/mission_bench.py`, and nobody has run it yet.
Therefore the hoist has a named switch `KUKAI_KIR_SCHEMA_DEDUP=0`, which
brings back the previous schema in full, and the decision is recorded here
in words, not dissolved into the code.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from kir import schema_dedup
from kir.schema_gen import program_schema
from kir import env  # noqa: E402

logger = logging.getLogger(__name__)

#: The switch. `0` — the previous flat schema; `1` — hoist regardless of
#: transport (for the test rig); unset — the transport measurement decides.
_FLAG = "KIR_SCHEMA_DEDUP"

#: THE SECOND SWITCH, AND IT IS ABOUT A DIFFERENT QUESTION: not "in what
#: FORM to carry the dictionary of operations," but "whether to carry it AT
#: ALL on every turn."
#:
#: MEASURED 17.08.2026, tree `prod-live` `7fb8b8b8`, the environment taken
#: from the live process (`/proc/<MainPID>/environ`), so `transport_verdict()`
#: is True here and the hoist into `$defs` is already applied:
#:
#:     the revit_ir tool as a whole   99 825 B  ≈ 24 956 tokens ON EVERY TURN
#:       description (prose)          47 357 B   47%
#:       program    (JSON shape)      51 365 B   51%
#:       program_py (SCRIPT)             238 B    0%
#:                                    RATIO      216x
#:
#: WHAT THIS SKEW MEANS FOR THE PRODUCT. The compiler's constitution declares
#: it a terminal state that EVERY write to the model goes through KIR
#: (`kir/CLAUDE.md`: "go through KIR with no alternative; free-form C#
#: stays for exotic reads"). A live measurement from the same day gives 0.9%:
#: `design/review.py` over the shadow-judge corpus (512 lines, 02.07→14.08)
#: shows, out of 423 calls to writing tools, `execute_revit_code` 362,
#: `apply_revit_write` 57, `revit_ir` — 4.
#:
#: 🔴 A CORRECTION ON 20.08.2026, AND IT IS NOT COSMETIC: THE WRONG PAIR WAS
#: COMPARED HERE, AND A STALE NUMBER WOULD HAVE FLIPPED THE CONCLUSION. It
#: used to say "5000 against `MAX_VALIDATED_OPS = 320`." First, 320 is dead:
#: the live value is 22000 (asked of `compiler`). Second — and this is more
#: expensive — with the live number the comparison would read "5000 against
#: 22000," meaning the expensive half would turn out not WEAKER but four
#: times narrower, and the whole argument of the paragraph would flip. The
#: pair was wrong from the very start: the scripted door must be measured
#: against the AUTHORED budget (`MAX_OPS_PER_PROGRAM`), because its entire
#: value is the margin OVER what the model would write by hand (form 32: an
#: order lifts a bound, not an invariant).
#:
#: The reason for the gap is measurable, not ideological: `revit_ir_enabled()`
#: requires an EXPLICIT KIR mode and an admin device, and requires them
#: because the surface costs a quarter of the context. The expensive half is
#: at the same time WEAKER: a script computes up to `MAX_SCRIPT_OPS` = 5000
#: operations against the authored `MAX_OPS_PER_PROGRAM` = 1000, that is, a
#: FIVEFOLD margin, and its space already holds
#: `preview` / `design_check` / `score` / `phase` — meaning the loop "wrote →
#: saw → judged → fixed" closes OFFLINE, before a single trip to Revit.
#:
#: WHAT THE SWITCH DOES AND DOES NOT DO. It collapses the DECLARATION of the
#: `program` field, not the capability: the runtime accepts JSON exactly as
#: it did before, `_authored_input` does not change, not a single new
#: refusal is introduced. The dictionary of operations does NOT DISAPPEAR in
#: the process — it stays in the tool's description
#: (`tool_doc.build_tool_description()` generates the listing from
#: `spec.OPS`) and is available by name inside the sandbox through
#: `spec("<op>")`. What disappears is exactly the repetition: the expanded
#: signature of EVERY parameter of EVERY op on EVERY turn.
#:
#: 🔴 THE DEFAULT IS OFF, AND NOW THAT IS NOT CAUTION, IT IS A MEASUREMENT.
#: The line above used to say for years "unknown whether the working model
#: can handle it"; on 18.08.2026 it became known, and the answer is NEGATIVE
#: on the model that is actually in use.
#:
#: MEASUREMENT: `tools/design/mission_bench.py`, task `house`, tree
#: `60e72f55`, 16 cells out of 18 (cut short by a one-dollar ceiling, the cut
#: is named). Breaking it down along TWO axes — something pilots 1 and 2 did
#: not do, which is why they attributed everything to the collapse:
#:
#:     axis         what it isolates   gpt-5.6-sol   deepseek-v4-flash
#:     A <-> C      ADVICE               0 -> 7          1 -> 1
#:     C <-> D      SCHEMA VOLUME        7 -> 8          1 -> 4.5
#:
#: On the flash model, ADVICE costs nothing, and SCHEMA VOLUME costs
#: everything — that is, exactly the opposite of the strong model. The
#: collapsed arm reached an accepted program in 4 blocks out of 6, against 5
#: out of 5 for the expanded arm; in block 0 — not a single one in 13 turns,
#: and you can see WHAT it is busy doing:
#:
#:     D block 0:  refusal recon refusal recon recon refusal recon ...
#:     A block 0:  recon ok ok ok ok
#:
#: The collapsed arm OSCILLATES between "ask" and a sandbox refusal; the
#: expanded arm asks once and builds.
#:
#: THE VERDICT, AND IT CARRIES THE MODEL AS A CONDITION, NOT AS A FOOTNOTE:
#: **do not enable on `deepseek-v4-flash-0731`.** A change of the working
#: model MUST reopen the question, not inherit this answer: pilot-3 was run
#: on `gpt-5.6-sol`, gave the opposite picture, and on it the flag nearly
#: shipped to prod. The condition is part of the verdict.
#:
#: 🔴 AND THE SAVING HERE IS NOT THE ONE PEOPLE QUOTE. "99.62%" is about the
#: `program` FIELD, not about the door. Under prod conditions (with `$defs`
#: hoisting on, see the table above) the tool AS A WHOLE goes from 27 861 to
#: 14 608 tokens, that is, **47.6%**: the collapse does not touch the
#: description (~47 KB of prose), and `$defs` has already compressed the
#: schema before sending. Quoting 99.62% as the TURN's gain is comparing a
#: part with the whole.
#:
#: WHAT THIS SWITCH LACKS, UNLIKE ITS NEIGHBOR: `transport_verdict()` has A
#: TABLE OF MEASUREMENTS by transport (`_REF_MEASURED`), while here there is
#: no table — only the switch and this prose measurement. The questions
#: differ even in their failure mechanism: the transport breaks the schema,
#: the collapse yields a valid but SPARSER one. They cannot be folded into
#: one justification — these are two quantities under one name.
_SCRIPT_FIRST_FLAG = "KIR_SCRIPT_FIRST"

#: litellm prefixes on which acceptance of `$ref` is MEASURED live (table in
#: the header). `openai/` also covers proxy arms: `codex_route` sends
#: `model=f"openai/{...}"`, and so does agy/antigravity — and it is exactly
#: that endpoint that was polled.
_REF_MEASURED = ("openrouter/", "openai/")

#: Prefixes where litellm expands `$defs` back ⇒ there will be no saving.
_REF_POINTLESS = ("vertex_ai/", "gemini/")

#: The primary move. If the model is not named — the transport is unknown,
#: and that is a REFUSAL to transform, not an invitation to guess.
_PRIMARY_ENV = "KUKAI_LLM_MODEL"

#: The other arms of ONE turn: the tool bundle is built once and survives
#: the whole fallback chain, so EVERY one of them must be safe.
_LEG_ENV = (
    "KUKAI_LLM_THINKING_MODEL",
    "KUKAI_LLM_FALLBACK_MODEL",
    "KUKAI_LLM_LAST_RESORT_MODEL",
    "KUKAI_MODELING_LLM_MODEL",
)

#: Arms that litellm sees as `openai/<name>` (the prefix is set by our own
#: code, not the environment) — `codex_route.py:406`, `client.py` for agy.
_OPENAI_PREFIXED_ENV = (
    "KUKAI_CODEXPROXY_MODEL",
    "KUKAI_CODEXPROXY_MODEL_FALLBACK",
    "KUKAI_AGY_MODEL",
    "KUKAI_ANTIGRAVITY_MODEL",
)

#: Tiers of fallback models travel as one JSON — `transport._parse_fallback_tiers`.
_TIERS_ENV = "KUKAI_FALLBACK_TIERS"


def _tier_models() -> list[str]:
    raw = (env.get(_TIERS_ENV) or "").strip()
    if not raw:
        return []
    try:
        tiers = json.loads(raw)
    except Exception:  # noqa: BLE001 — parsing tiers is not our concern, but it is no excuse to lie
        return ["<нечитаемый KUKAI_FALLBACK_TIERS>"]
    out: list[str] = []
    if isinstance(tiers, list):
        for tier in tiers:
            if isinstance(tier, dict) and isinstance(tier.get("model"), str):
                out.append(tier["model"].strip())
    return [m for m in out if m]


def configured_models() -> list[str]:
    """All models that CAN carry this tool bundle in one turn."""
    models: list[str] = []
    primary = (env.get(_PRIMARY_ENV) or "").strip()
    if primary:
        models.append(primary)
    for name in _LEG_ENV:
        value = (env.get(name) or "").strip()
        if value:
            models.append(value)
    for name in _OPENAI_PREFIXED_ENV:
        value = (env.get(name) or "").strip()
        if value:
            models.append(value if "/" in value else f"openai/{value}")
    models.extend(_tier_models())
    seen: set[str] = set()
    return [m for m in models if not (m in seen or seen.add(m))]


def transport_verdict() -> tuple[bool, str]:
    """(whether to hoist, WHY) — the reason is in Russian and always names the culprit."""
    flag = (env.get(_FLAG) or "").strip()
    if flag == "0":
        return False, f"выключено рубильником {_FLAG}=0"
    if flag == "1":
        return True, f"включено рубильником {_FLAG}=1 (транспорт не проверялся)"

    primary = (env.get(_PRIMARY_ENV) or "").strip()
    if not primary:
        return False, (f"транспорт неизвестен: {_PRIMARY_ENV} не задан — схема "
                       f"остаётся плоской, пока приём $ref не замерен")

    models = configured_models()
    pointless = [m for m in models if m.startswith(_REF_POINTLESS)]
    unknown = [m for m in models
               if not m.startswith(_REF_MEASURED) and m not in pointless]
    if pointless:
        return False, (f"litellm разворачивает $defs обратно перед отправкой на "
                       f"{', '.join(sorted(pointless))} — вынос не сэкономил бы "
                       f"ни токена")
    if unknown:
        return False, (f"приём $ref не замерен на {', '.join(sorted(unknown))} — "
                       f"схема остаётся плоской (замерь и внеси в _REF_MEASURED)")
    return True, (f"$ref замерен живьём на {_plural_legs(len(models))} хода "
                  f"({', '.join(models[:3])}{'…' if len(models) > 3 else ''})")


def _plural_legs(n: int) -> str:
    return f"{n} плече" if n % 10 == 1 and n % 100 != 11 else f"{n} плечах"


#: Hoisting costs 45 ms per schema (measured 09.08), and `_resolve_tools` is
#: called on every request. The key is the canonical bytes of the FLAT
#: schema, so an edit to the registry invalidates the cache by itself,
#: without a manual reset.
_CACHE: dict[str, dict] = {}
_CACHE_MAX = 2
_announced: set[str] = set()


def _hoist_cached(flat: dict) -> dict:
    key = json.dumps(flat, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    packed = schema_dedup.hoist(flat)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = packed
    return packed


def script_first_verdict() -> tuple[bool, str]:
    """(whether to collapse the `program` declaration, WHY) — the reason is always named.

    The default is OFF: the unknown here must mean the previous behavior.
    """
    flag = (env.get(_SCRIPT_FIRST_FLAG) or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True, (f"включено рубильником {_SCRIPT_FIRST_FLAG}={flag}: "
                      f"словарь операций едет описанием и по запросу "
                      f"(`spec()` в песочнице), а не развёрнутой схемой")
    if flag in {"0", "false", "no", "off"}:
        return False, f"выключено рубильником {_SCRIPT_FIRST_FLAG}={flag}"
    return False, (f"{_SCRIPT_FIRST_FLAG} не задан — объявление `program` "
                   f"остаётся развёрнутым (прежнее поведение)")


#: The collapsed declaration. NOT a refusal and NOT a prohibition: the field
#: stays, the runtime accepts it exactly as before.
#:
#: 🔴 AND THIS ONLY BECAME TRUE ON 18.08.2026. THE PREVIOUS EDITION LIED TO
#: THE RUNTIME, AND THIS VERY LINE ASSERTED THE OPPOSITE. It declared
#: `{"type": "array"}` — that is, A PROGRAM AS A LIST — while the runtime
#: requires an envelope object:
#:
#:     the collapsed form declared   type: array
#:     the runtime requires          type: object, required ["ir_version", "ops"]
#:     a list                        -> KIR-P001 «программа должна быть JSON-объектом»
#:     an object                     -> ok
#:
#: A model that OBEYED the declaration got a typed refusal. Caught by the
#: A/B pilot: `KIR-P001` **14 times over 6 runs, and only on the arm** that
#: was actually given the collapsed schema. Without that run the switch
#: would have shipped to prod, and "the writing surface moved to the
#: script" would have stayed a judgment resting on a broken artifact.
#:
#: WHAT THIS TEACHES, BEYOND THE FIX ITSELF. Collapsing must touch the
#: DECLARATION, not the SHAPE: the top level, `required`, and
#: `additionalProperties` are the contract the runtime checks, and swapping
#: them out for "simplification" means building a second grammar of the
#: language that nobody follows. What gets collapsed is exactly what is
#: expensive and recoverable on request: the expanded signatures of
#: operations and the dictionary of defaults.
#:
#: THE COST OF HONESTY IS MEASURED AND IT IS NEGLIGIBLE — see
#: `_collapsed_cost_note`.
def _collapsed_program_schema() -> dict:
    flat = program_schema()
    props = dict(flat.get("properties") or {})
    ops_desc = (
        "Операции IR списком объектов. РАЗВЁРНУТЫЕ СИГНАТУРЫ ЗДЕСЬ НЕ "
        "ПРИВЕДЕНЫ — они стоили бы четверть контекста на каждом ходе. "
        "Перечень операций — в описании инструмента выше; сигнатуру "
        "конкретной операции спрашивай в `program_py` вызовом "
        "`spec(\"create_wall\")` — он ПЕЧАТАЕТ контракт, и печать приезжает "
        "обратно в квитанции. Предпочитай `program_py`: там же лежат "
        "`preview`, `design_check`, `score` и каталог документа, то есть "
        "программу можно посчитать, УВИДЕТЬ и осудить до записи в Revit.")
    if isinstance(props.get("ops"), dict):
        props["ops"] = {"type": "array", "items": {"type": "object"},
                        "description": ops_desc}
    if isinstance(props.get("defaults"), dict):
        props["defaults"] = {
            "type": "object",
            "description": (
                "Умолчания программы (уровень, тип и прочее, что иначе "
                "повторяется в каждом опе). Раскладка полей ЗДЕСЬ НЕ "
                "ПРИВЕДЕНА по той же причине, что у `ops`; спрашивай "
                "`spec(\"<оп>\")` — умолчание применимо там, где у опа есть "
                "одноимённый параметр."),
        }
    # THE ENVELOPE'S SHAPE IS NOT TOUCHED BY A SINGLE KEY: `type`, `required`,
    # `additionalProperties` travel as is. Swapping exactly those was the defect.
    return {**flat, "properties": props}


def _collapsed_cost_note() -> dict[str, int]:
    """What honesty cost — as a number, not a promise (measured 18.08.2026).

    The lying collapse weighed 484 B, the honest one — about 700. The
    addition goes onto the envelope, which the runtime checks anyway, and
    against the flat schema's backdrop (299 775 B) it amounts to fractions
    of a percent: the saving stays above 99.7%.
    """
    def _n(value: Any) -> int:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")))
    flat = program_schema()
    return {"flat": _n(flat), "collapsed": _n(_collapsed_program_schema())}


def program_schema_for_tool() -> tuple[dict, str]:
    """The `program` field's schema for the tool + the NAMED reason for its shape.

    Nothing silently: a path where the extraction was not applied must say
    so, rather than quietly return the previous form — otherwise "we saved"
    and "we did not save" look identical, and a regression lives unnoticed
    right up to the next count.
    """
    collapse, why_collapse = script_first_verdict()
    if collapse:
        note = f"объявление `program` СВЁРНУТО: {why_collapse}"
        if why_collapse not in _announced:
            _announced.add(why_collapse)
            logger.info("KIR script-first ON — %s", note)
        return _collapsed_program_schema(), note

    flat = program_schema()
    hoist_it, why = transport_verdict()
    if not hoist_it:
        note = f"схема KIR плоская: {why}"
        if why not in _announced:
            _announced.add(why)
            logger.info("KIR schema dedup OFF — %s", why)
        return flat, note

    packed = _hoist_cached(flat)
    stats = _measure(flat, packed)
    note = (f"схема KIR свёрнута в $defs ({stats['ratio']}x, "
            f"{stats['flat_bytes']}→{stats['packed_bytes']} байт, "
            f"{stats['defs']} форм): {why}")
    if why not in _announced:
        _announced.add(why)
        logger.info("KIR schema dedup ON — %s", note)
    return packed, note


def _measure(flat: dict, packed: dict) -> dict[str, Any]:
    def canon(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    a, b = len(canon(flat)), len(canon(packed))
    return {"flat_bytes": a, "packed_bytes": b,
            "ratio": round(a / b, 3) if b else 0.0,
            "defs": len(packed.get("$defs", {}))}


def describe_ru() -> str:
    """One line for a human: exactly what the model will see, and why."""
    return program_schema_for_tool()[1]


__all__ = ["configured_models", "describe_ru", "program_schema_for_tool",
           "script_first_verdict", "transport_verdict"]
