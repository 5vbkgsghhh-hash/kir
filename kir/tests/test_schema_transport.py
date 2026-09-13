"""WHAT EXACTLY THE MODEL RECEIVES — and proof that it's THE SAME
LANGUAGE.

The KIR schema at 41 ops costs 42,390 tokens on the provider's bill for
EVERY turn (measurement 09.08.2026, a live openrouter/deepseek-v4-flash,
`usage.prompt_tokens`). Collapsed into `$defs` — 11,751. The savings
are not free in exactly one place: a schema with references MUST
accept and reject exactly the same programs as the flat one. If that's
not so, we saved tokens and changed the language, which is the worst
trade in this house.

There are three proofs here, and they differ in nature:

  1. IDENTITY OF FORM      — `expand(hoist(s))` equals `s`
     byte-for-byte;
  2. IDENTITY OF BEHAVIOR  — a corpus of real programs (assembled from
     the test suite itself) plus deliberately invalid ones: each one
     gets the SAME verdict from both schemas, and what must agree is
     not just yes/no but the error PATHS too;
  3. A PROPERTY ON GENERATED COMBINATIONS — samples from every branch
     of every op, both valid and corrupted, checked by the same
     comparison.

The first catches data loss, the second catches a loss of meaning on
what people actually wrote, the third catches a lost constraint in a
branch the corpus never looked into.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import random
import tempfile
from typing import Any

import pytest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import schema_dedup, schema_transport, spec  # noqa: E402
from kir.schema_gen import program_schema  # noqa: E402

jsonschema = pytest.importorskip("jsonschema")


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


@pytest.fixture(scope="module")
def flat() -> dict:
    return program_schema()


@pytest.fixture(scope="module")
def packed(flat: dict) -> dict:
    return schema_dedup.hoist(flat)


@pytest.fixture(scope="module")
def validators(flat: dict, packed: dict):
    return (jsonschema.Draft202012Validator(flat),
            jsonschema.Draft202012Validator(packed))


def _verdict(validator, program) -> tuple[bool, list[str]]:
    """The verdict together with its PATHS — "rejected" is not
    enough, WHERE and BY WHAT matters."""
    errors = sorted("/".join(str(p) for p in e.absolute_path) + "|" + e.validator
                    for e in validator.iter_errors(program))
    return (not errors, errors)


def _same(validators, program, label: str) -> bool:
    flat_v, packed_v = validators
    a, ea = _verdict(flat_v, program)
    b, eb = _verdict(packed_v, program)
    assert a == b, (f"{label}: плоская схема сказала {a}, свёрнутая {b} — "
                    f"это РАЗНЫЕ языки, экономия не имеет значения")
    assert ea == eb, (f"{label}: вердикт совпал, а причины разошлись\n"
                      f"  плоская:  {ea[:3]}\n  свёрнутая: {eb[:3]}")
    return a


# ─── PROOF 1: identity of form ──────────────────────────────────────────────

def test_proof_1_round_trip_is_byte_exact(flat: dict, packed: dict) -> None:
    """`expand(hoist(s)) == s` — both as objects and byte-for-byte in
    canonical form."""
    back = schema_dedup.expand(packed)
    assert back == flat, "разворот вернул не ту схему"
    assert _canon(back) == _canon(flat), "разворот совпал по смыслу, но не по байтам"


# ─── PROOF 2: identity of behavior on a real corpus ─────────────────────────

#: 🔴 THE ROOT AFTER THE SPLIT (28.08.2026). `parents[3]` from
#: `kir/kir/tests/x.py` gives `/opt` — the directory where our package
#: sits next to other trees. Before 27.08 the same count from
#: `backend/kukai/ir/tests/x.py` gave the install root. The correct
#: root is the one the package sits INSIDE.
_TEST_TREE = pathlib.Path(__file__).resolve().parents[2]


def _harvest_programs() -> list[tuple[str, Any]]:
    """All literal KIR programs from the test tree — WITHOUT importing
    modules.

    The corpus is assembled by parsing the sources, not from a
    hand-written list: a hand-written one falls behind the test suite
    on the very first new wave, and "ran the corpus" starts meaning
    "ran what someone once wrote down."
    """
    out: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for root in ("kir", "tools/design", "tests"):
        base = _TEST_TREE / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Dict, ast.List)):
                    continue
                try:
                    value = ast.literal_eval(node)
                except (ValueError, TypeError, SyntaxError, MemoryError,
                        RecursionError):
                    continue
                program: Any = None
                if (isinstance(value, dict) and isinstance(value.get("ops"), list)
                        and value["ops"]
                        and all(isinstance(o, dict) for o in value["ops"])):
                    program = value
                elif (isinstance(value, list) and value
                      and all(isinstance(o, dict) and isinstance(o.get("op"), str)
                              for o in value)):
                    program = {"ir_version": spec.IR_VERSION, "ops": value}
                if program is None:
                    continue
                key = _canon(program)
                if key not in seen:
                    seen.add(key)
                    out.append((path.name, program))
    return out


#: Deliberately INVALID programs, aimed exactly at the places where a
#: reference could lose a constraint: selectors, number bounds, point
#: arity, an address from grids, and — separately — data that itself
#: LOOKS like a reference.
INVALID: list[tuple[str, Any]] = [
    ("нет ir_version", {"ops": [{"op": "query_count", "id": "a", "kind": "wall"}]}),
    ("чужой ir_version", {"ir_version": "9.9",
                          "ops": [{"op": "query_count", "id": "a", "kind": "wall"}]}),
    ("пустой ops", {"ir_version": spec.IR_VERSION, "ops": []}),
    ("несуществующий оп", {"ir_version": spec.IR_VERSION,
                           "ops": [{"op": "make_coffee"}]}),
    ("лишний ключ конверта", {"ir_version": spec.IR_VERSION, "junk": 1,
                              "ops": [{"op": "query_count", "id": "a", "kind": "wall"}]}),
    ("селектор неизвестного рода", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [1000, 0],
         "level": {"by": "vibe", "value": "x"}, "height_mm": 3000}]}),
    ("селектор без value", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [1000, 0],
         "level": {"by": "name"}, "height_mm": 3000}]}),
    ("селектор с лишним ключом", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [1000, 0],
         "level": {"by": "name", "value": "Этаж 1", "colour": "red"},
         "height_mm": 3000}]}),
    ("element_id вне границ", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "query_inspect", "id": "q",
         "target": {"by": "element_id", "value": -5}}]}),
    ("element_id ноль", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "query_inspect", "id": "q",
         "target": {"by": "element_id", "value": 0}}]}),
    ("точка не той арности", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0, 0, 0], "p1_mm": [1000, 0],
         "level": {"by": "name", "value": "Этаж 1"}, "height_mm": 3000}]}),
    ("точка не того типа", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": ["a", "b"], "p1_mm": [1000, 0],
         "level": {"by": "name", "value": "Этаж 1"}, "height_mm": 3000}]}),
    ("адрес от осей сломан", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": {"at_grid": ["1"]},
         "p1_mm": [1000, 0], "level": {"by": "name", "value": "Этаж 1"},
         "height_mm": 3000}]}),
    ("род не из словаря", {"ir_version": spec.IR_VERSION,
                           "ops": [{"op": "query_count", "id": "a", "kind": "🦄"}]}),
    ("число ниже минимума", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [1000, 0],
         "level": {"by": "name", "value": "Этаж 1"}, "height_mm": -1}]}),
    ("intent длиннее предела", {"ir_version": spec.IR_VERSION, "intent": "ы" * 5000,
                                "ops": [{"op": "query_count", "id": "a", "kind": "wall"}]}),
    ("оп — это $ref", {"ir_version": spec.IR_VERSION,
                       "ops": [{"$ref": "#/$defs/sel_by_name"}]}),
    ("не объект вовсе", None),
    ("строка вместо программы", "wall"),
    ("список вместо программы", [{"op": "query_count"}]),
    ("пустой объект", {}),
]


#: VALID programs where the DATA looks like a reference. An expansion
#: that reaches wider than the hoist would mistake such a field for a
#: `$ref` and substitute the form's body for it — and that would not
#: be a rejected program, but a SILENTLY DIFFERENT one. So these are
#: checked as a separate list, where "accepted by both" is expected.
REF_LOOKALIKE: list[tuple[str, Any]] = [
    ("имя выглядит как ссылка", {"ir_version": spec.IR_VERSION, "ops": [
        {"op": "query_inspect", "id": "q", "target": {
            "by": "name", "value": "#/$defs/sel_by_name", "kind": "wall"}}]}),
    ("замысел выглядит как ссылка", {
        "ir_version": spec.IR_VERSION, "intent": "{\"$ref\": \"#/$defs/pt_xy\"}",
        "ops": [{"op": "query_count", "id": "a", "kind": "wall"}]}),
]


def test_proof_2_the_corpus_gets_identical_verdicts(validators) -> None:
    """The test-suite corpus plus the deliberately invalid ones: the
    verdict must agree."""
    harvested = _harvest_programs()
    assert len(harvested) >= 100, (
        f"корпус усох до {len(harvested)} программ — сбор сломался, "
        f"а не тесты похудели")
    accepted = rejected = 0
    for name, program in harvested:
        accepted += _same(validators, program, f"корпус {name}")
    for label, program in INVALID:
        rejected += not _same(validators, program, f"неверная «{label}»")
    assert accepted, "корпус не содержит ни одной ПРИНЯТОЙ программы"
    assert rejected == len(INVALID), (
        "часть заведомо неверных программ прошла ОБЕ схемы — тогда они не "
        "проверяют то, ради чего написаны")
    for label, program in REF_LOOKALIKE:
        assert _same(validators, program, f"похожая на ссылку «{label}»"), (
            f"«{label}» обязана быть ПРИНЯТА: это данные, а не ссылка")


# ─── PROOF 3: a property on generated combinations ──────────────────────────

def _sample(schema: dict, rng: random.Random, valid: bool, depth: int = 0) -> Any:
    """A sample drawn from the schema. Each `oneOf` branch is equally
    likely, so the hoisted subtree gets both valid values and ones
    that violate exactly its constraint."""
    if depth > 10:
        return None
    if "const" in schema:
        return schema["const"] if valid else "___не_та_константа___"
    if "enum" in schema:
        return rng.choice(schema["enum"]) if valid else "___не_из_словаря___"
    for key in ("oneOf", "anyOf"):
        if key in schema:
            return _sample(rng.choice(schema[key]), rng, valid, depth + 1)
    kind = schema.get("type")
    if kind == "object":
        props = schema.get("properties") or {}
        required = set(schema.get("required") or ())
        out: dict = {}
        for name, sub in props.items():
            if name in required or rng.random() < 0.55:
                out[name] = _sample(sub, rng, valid, depth + 1)
        if not valid and rng.random() < 0.35:
            out["___сюрприз___"] = 1
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            for i in range(schema.get("minProperties") or 1):
                out[f"k{i}"] = _sample(extra, rng, valid, depth + 1)
        return out
    if kind == "array":
        lo = schema.get("minItems", 1)
        hi = schema.get("maxItems", max(lo, 3))
        n = rng.randint(lo, min(hi, lo + 2))
        if not valid and rng.random() < 0.5:
            n = hi + 1
        items = schema.get("items")
        return [_sample(items, rng, valid, depth + 1) if isinstance(items, dict)
                else 0 for _ in range(n)]
    if kind in ("number", "integer"):
        lo, hi = schema.get("minimum"), schema.get("maximum")
        if not valid:
            return lo - 1 if lo is not None else (hi + 1 if hi is not None
                                                  else "не число")
        if lo is not None and hi is not None:
            value = rng.choice([lo, hi, (lo + hi) / 2])
        elif lo is not None:
            value = rng.choice([lo, lo + 1000])
        elif hi is not None:
            value = rng.choice([hi, hi - 1000])
        else:
            value = rng.choice([0, 1, -1, 1234.5])
        if kind == "integer":
            value = int(value)
        floor = schema.get("exclusiveMinimum")
        if floor is not None and value <= floor:
            value = floor + 1
        return value
    if kind == "string":
        hi = schema.get("maxLength", 24)
        if not valid:
            return "ы" * (hi + 1)
        body = rng.choice(["Этаж 1", "Кирпич 250", "А", "w1", "x"])
        low = schema.get("minLength", 0)
        if len(body) < low:
            body += "y" * (low - len(body))
        return body[:hi] if hi else body
    if kind == "boolean":
        return rng.choice([True, False]) if valid else "да"
    return rng.choice([1, "x", True, None, [], {}])


def test_proof_3_generated_op_combinations_agree(flat: dict, validators) -> None:
    """Every branch of every op — by samples, both valid and
    corrupted.

    The corpus shows that we haven't broken what was already written;
    what is checked here is what no one has written yet. Branches are
    enumerated EXPLICITLY, not left to chance: otherwise a rare op
    would stay unchecked, and the test would report that with
    silence.
    """
    branches = flat["properties"]["ops"]["items"]["oneOf"]
    assert len(branches) >= len(spec.OPS), "ветки опов пропали из схемы"
    accepted = rejected = 0
    for index, branch in enumerate(branches):
        for shot in range(6):
            rng = random.Random(index * 1000 + shot)
            valid = shot < 3
            program = {"ir_version": spec.IR_VERSION,
                       "ops": [_sample(branch, rng, valid)]}
            if shot % 2:
                program["intent"] = "проба"
            hit = _same(validators, program, f"ветка {index} образец {shot}")
            accepted += hit
            rejected += not hit
    # Combinations: one branch can be legal on its own and not legal
    # in company.
    for seed in range(120):
        rng = random.Random(90_000 + seed)
        ops = [_sample(rng.choice(branches), rng, rng.random() < 0.6)
               for _ in range(rng.randint(2, 4))]
        program = {"ir_version": spec.IR_VERSION, "ops": ops}
        if rng.random() < 0.2:
            program["defaults"] = _sample(flat["properties"]["defaults"], rng,
                                          rng.random() < 0.6)
        hit = _same(validators, program, f"сочетание {seed}")
        accepted += hit
        rejected += not hit
    assert accepted and rejected, (
        f"порождение вырождено: принято {accepted}, отвергнуто {rejected} — "
        f"тест, который всё принимает или всё отвергает, ничего не проверяет")


# ─── RATCHET: the win must survive the waves that follow ───────────────────

#: Bytes of the collapsed schema PER OP — the only number that
#: survives registry growth, and therefore the only one a limit can be
#: set on.
#:
#: DERIVED, NOT ASSIGNED. Measurement 09.08.2026 on 41 ops: flat
#: schema — 118,543 bytes, collapsed — 30,626, that is, 747 bytes per
#: op. The registry is growing toward ~120 ops, and the limit is
#: chosen from a requirement that can be stated plainly: **at ANY
#: registry size up to 120 ops, the collapsed schema must not cost
#: more than TODAY's flat schema costs at 41 ops** — 118,543 / 120 =
#: 988 bytes per op. Today's 747 leaves 24% margin; going past 988
#: would mean tripling the registry has brought us back to the very
#: cost the hoist was wired in to escape.
MAX_SHIPPED_BYTES_PER_OP = 988

#: The weakest compression we have ever OBSERVED HOLD: 3.871x by
#: bytes, 3.61x by provider tokens on openrouter, 5.68x on
#: openai/gpt-5.6-sol (measurements 09.08). The threshold is set BELOW
#: the weakest measurement, not below today's number: the test must
#: catch regression, not pin a record.
MIN_RATIO = 3.5


def test_the_saving_does_not_rot_back(flat: dict, packed: dict) -> None:
    stats = schema_dedup.measure(flat)
    assert stats["ratio"] >= MIN_RATIO, (
        f"сжатие упало до {stats['ratio']}x при пороге {MIN_RATIO}x — {stats}")
    per_op = len(_canon(packed)) / max(len(spec.OPS), 1)
    assert per_op <= MAX_SHIPPED_BYTES_PER_OP, (
        f"свёрнутая схема стоит {per_op:.0f} байт на оп при потолке "
        f"{MAX_SHIPPED_BYTES_PER_OP}; на 120 опах это "
        f"{per_op * 120:,.0f} байт — дороже сегодняшней ПЛОСКОЙ схемы, то есть "
        f"вынос перестал решать задачу, ради которой подключён")


def test_the_live_tool_actually_ships_the_deduped_schema(monkeypatch) -> None:
    """THE MAIN RATCHET: the references must reach the TURN PANEL, not
    stop at the module.

    The number in the test above is fixed by editing one line; but
    this check goes red exactly when the hoist gets disconnected from
    the live path — and that is exactly how expensive work dies in
    this house: the code exists, the tests are green, and prod keeps
    paying the old price.
    """
    from kir import serving

    monkeypatch.setenv("KUKAI_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    monkeypatch.delenv("KUKAI_KIR_SCHEMA_DEDUP", raising=False)
    for name in schema_transport._LEG_ENV + schema_transport._OPENAI_PREFIXED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("KUKAI_FALLBACK_TIERS", raising=False)

    tools: list = []
    serving.inject_revit_ir_schema(tools)
    arguments = tools[0]["function"]["parameters"]
    program = arguments["properties"]["program"]
    assert "$defs" in arguments and "$defs" not in program, (
        "инструмент уехал бы с плоской схемой — вынос отключился от живого пути")
    # And it is THE SAME schema: expansion happens at the panel, not
    # in the module.
    assert _canon(schema_dedup.expand(arguments)["properties"]["program"]) == _canon(program_schema())
    # Not a single op has disappeared from view — that is exactly what
    # distinguishes hoisting from tiered delivery.
    text = _canon(program)
    missing = sorted(name for name in spec.OPS if f'"{name}"' not in text)
    assert not missing, f"опы пропали из схемы инструмента: {missing}"


def test_an_unverified_transport_keeps_todays_schema_and_says_so(monkeypatch) -> None:
    """The law of "nothing in silence": wherever something wasn't
    collapsed, the reason is named."""
    monkeypatch.setenv("KUKAI_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    monkeypatch.setenv("KUKAI_LLM_THINKING_MODEL", "мой-личный-прокси/model-x")
    for name in schema_transport._OPENAI_PREFIXED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("KUKAI_FALLBACK_TIERS", raising=False)
    monkeypatch.delenv("KUKAI_KIR_SCHEMA_DEDUP", raising=False)

    hoist_it, why = schema_transport.transport_verdict()
    assert hoist_it is False
    assert "мой-личный-прокси/model-x" in why, (
        "причина обязана НАЗЫВАТЬ виновника, иначе её нельзя проверить")
    schema, note = schema_transport.program_schema_for_tool()
    assert "$defs" not in schema, "неизвестный транспорт получил ссылки"
    assert _canon(schema) == _canon(program_schema()), (
        "отсутствующее осталось отсутствующим не полностью — схема изменилась")
    assert why in note


def test_gemini_is_refused_for_a_named_reason_not_silence(monkeypatch) -> None:
    """On vertex/gemini litellm expands `$defs` on its own — there is
    no saving.

    This is a SECOND kind of refusal, and it must differ from "we
    haven't checked": saying "unknown" where the exact opposite is
    known is the same lie, just a polite one.
    """
    monkeypatch.setenv("KUKAI_LLM_MODEL", "vertex_ai/gemini-3-flash-preview")
    for name in (schema_transport._LEG_ENV
                 + schema_transport._OPENAI_PREFIXED_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("KUKAI_FALLBACK_TIERS", raising=False)
    monkeypatch.delenv("KUKAI_KIR_SCHEMA_DEDUP", raising=False)

    hoist_it, why = schema_transport.transport_verdict()
    assert hoist_it is False
    assert "разворачивает" in why and "vertex_ai/gemini-3-flash-preview" in why


def test_the_kill_switch_is_honoured_in_both_directions(monkeypatch) -> None:
    monkeypatch.setenv("KUKAI_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    for name in (schema_transport._LEG_ENV
                 + schema_transport._OPENAI_PREFIXED_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("KUKAI_FALLBACK_TIERS", raising=False)

    monkeypatch.setenv("KUKAI_KIR_SCHEMA_DEDUP", "0")
    assert schema_transport.transport_verdict()[0] is False
    monkeypatch.setenv("KUKAI_KIR_SCHEMA_DEDUP", "1")
    monkeypatch.setenv("KUKAI_LLM_MODEL", "какой-то/невиданный-транспорт")
    assert schema_transport.transport_verdict()[0] is True


def test_a_missing_model_is_unknown_not_assumed(monkeypatch) -> None:
    monkeypatch.delenv("KUKAI_LLM_MODEL", raising=False)
    monkeypatch.delenv("KUKAI_KIR_SCHEMA_DEDUP", raising=False)
    hoist_it, why = schema_transport.transport_verdict()
    assert hoist_it is False and "KUKAI_LLM_MODEL" in why


def test_every_leg_of_the_turn_is_weighed_not_only_the_primary(monkeypatch) -> None:
    """The tool bundle is built ONCE and outlives the entire fallback
    chain.

    That means every tier must be safe, not just the main path:
    otherwise the very first switch to a fallback model hands it a
    schema it wasn't expecting.
    """
    monkeypatch.setenv("KUKAI_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    for name in (schema_transport._LEG_ENV
                 + schema_transport._OPENAI_PREFIXED_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KUKAI_FALLBACK_TIERS",
                       json.dumps([{"model": "неизвестный/ярус-2"}]))
    hoist_it, why = schema_transport.transport_verdict()
    assert hoist_it is False and "неизвестный/ярус-2" in why
    assert "неизвестный/ярус-2" in schema_transport.configured_models()
