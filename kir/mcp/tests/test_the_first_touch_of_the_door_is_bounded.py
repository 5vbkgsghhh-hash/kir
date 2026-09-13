"""WHAT THE DOOR COSTS AN AGENT BEFORE IT HAS SAID ONE WORD.

🔴 WHY A NUMBER AND NOT A JUDGEMENT. Audit of section H, 13.09.2026,
measured the cold start of this door: `tools/list` 75 602 B, of which
`kir_compile`'s schema alone was 65 969 B, plus `instructions()` 48 070 B
— 123 672 B, about 41 000 tokens, spent before the agent reads the task.
On a 200k-token model that is a fifth of the context, and it is paid again
on every fresh session by every client. Nothing in the tree held that
number, so it grew unwatched from the day the surface was built.

The saving is not compression: the per-op parameter detail moved to
`kir_spec`, the door built for exactly that question
(`surface._program_outline` carries the full argument). This file holds
the result so it cannot drift back, and — just as important — holds the
CHECKS that the saving was not bought by gutting the schema. A ceiling
alone would be passed by an empty surface.
"""
from __future__ import annotations

import json

import pytest

from kir.mcp import surface

#: The measurement this ceiling was set from (13.09.2026, this tree):
#:
#:     tools/list      17 346 B   (was 75 602)
#:     instructions    48 070 B   (unchanged — its subject is the LANGUAGE)
#:     FIRST TOUCH     65 416 B   ~= 21 800 tokens (was ~41 200)
#:
#: The ceiling leaves room for the registry and the prose to grow, and
#: stands far below the 123 672 B it replaced. Like every ratchet in this
#: tree it moves DOWN only: a rise means the per-op detail came back into
#: the listing.
FIRST_TOUCH_MAX_BYTES = 80_000

#: What it was before, kept as a number and not as a memory. A pin that
#: says only "small enough" cannot tell a saving from a rewrite.
FIRST_TOUCH_BEFORE_BYTES = 123_672


def _first_touch_bytes() -> int:
    """Exactly what a client receives on connect: the tool listing plus the
    server's instructions. Measured the same way as the audit's §1.1."""
    tools = sum(
        len(t["description"].encode())
        + len(json.dumps(t["input_schema"], ensure_ascii=False).encode())
        for t in surface.tools())
    return tools + len(surface.instructions().encode())


def test_the_first_touch_stays_under_the_ratchet():
    size = _first_touch_bytes()
    assert size <= FIRST_TOUCH_MAX_BYTES, (
        f"первое касание двери {size} Б превысило храповик "
        f"{FIRST_TOUCH_MAX_BYTES} Б — проверь, не вернулись ли параметры "
        f"опов в `tools/list` вместо `kir_spec`")


#: The measured share, and it is NOT "less than half". First draft of this
#: file asserted `size * 2 < before` and went RED at 65 416 * 2 = 130 832
#: against 123 672 — the claim was a round number, the measurement was
#: 52.9 %. Kept as written provenance: the instrument caught its author
#: overstating by 6 %, which is exactly what it is for.
FIRST_TOUCH_SHARE_CEILING = 0.60

#: `kir_compile`'s own schema is where the saving actually happened:
#: 65 969 -> 6 743 B, that is 10.2 % of what it was.
COMPILE_SCHEMA_BEFORE_BYTES = 65_969
COMPILE_SCHEMA_SHARE_CEILING = 0.20


def test_the_saving_is_real_and_not_a_rounding():
    """Stated as a share of a measured number, so that a change that quietly
    gives it back is red here and not in someone's context window."""
    size = _first_touch_bytes()
    share = size / FIRST_TOUCH_BEFORE_BYTES
    assert share <= FIRST_TOUCH_SHARE_CEILING, (
        f"первое касание {size} Б = {share:.1%} от прежних "
        f"{FIRST_TOUCH_BEFORE_BYTES} Б — экономия ушла")


def test_the_saving_is_where_it_was_claimed_to_be():
    """Not "the surface got smaller somehow": the schema of `kir_compile` is
    the thing that was 65 969 B, and it is the thing that must be small."""
    size = len(json.dumps(_compile_program_schema(), ensure_ascii=False).encode())
    tool = next(t for t in surface.tools() if t["name"] == "kir_compile")
    whole = len(json.dumps(tool["input_schema"], ensure_ascii=False).encode())
    share = whole / COMPILE_SCHEMA_BEFORE_BYTES
    assert share <= COMPILE_SCHEMA_SHARE_CEILING, (
        f"схема `kir_compile` {whole} Б = {share:.1%} от прежних "
        f"{COMPILE_SCHEMA_BEFORE_BYTES} Б (поле `program` — {size} Б)")


def _compile_program_schema() -> dict:
    tool = next(t for t in surface.tools() if t["name"] == "kir_compile")
    return tool["input_schema"]["properties"]["program"]


def test_the_op_name_is_still_checked_on_the_wire():
    """THE CONTROL FOR THE CEILING. The cheap way to pass a byte ceiling is
    to stop checking. The op NAME is the one thing the listing must keep:
    without it an invented op reaches the compiler as a typed refusal
    instead of being rejected where the model can see it."""
    program = _compile_program_schema()
    item = program["properties"]["ops"]["items"]
    names = item["properties"]["op"]["enum"]
    from kir import spec
    assert set(names) >= set(spec.OPS), (
        "перечень имён опов в схеме разошёлся с реестром")
    assert "invented" not in names


def test_the_bounds_that_refuse_are_all_still_there():
    """The envelope keeps every bound that REFUSES — only documentation
    left. `lineage` is a signed field of plan /5, and its pattern is not
    decoration (see `test_public_lineage_schema`)."""
    program = _compile_program_schema()
    assert program["additionalProperties"] is False
    assert set(program["required"]) == {"ir_version", "ops"}
    lineage = program["properties"]["lineage"]
    assert lineage["maxLength"] == 64 and lineage["minLength"] == 1
    assert lineage["pattern"]
    assert program["properties"]["ops"]["minItems"] == 1


def test_the_per_op_detail_is_genuinely_gone_from_the_listing():
    """The mechanism, not the byte count: the listing must not spell out one
    branch per op any more. A surface that shrank for some other reason
    while keeping 86 branches would pass the ceiling and miss the point."""
    item = _compile_program_schema()["properties"]["ops"]["items"]
    assert "oneOf" not in item and "anyOf" not in item


def test_the_contract_door_that_took_the_detail_over_still_answers():
    """`kir_spec` is where the detail went. If it stopped being a tool, the
    saving would be a loss."""
    assert "kir_spec" in surface.names()
    spec_tool = next(t for t in surface.tools() if t["name"] == "kir_spec")
    assert "op" in spec_tool["input_schema"]["properties"]


def test_a_real_program_still_validates_against_the_reduced_envelope():
    """A shrunken schema that rejects legal programs would be worse than the
    cost it saved."""
    pytest.importorskip("jsonschema")
    from jsonschema import Draft202012Validator
    from kir.tests.test_public_program_lineage import program

    tool = next(t for t in surface.tools() if t["name"] == "kir_compile")
    validator = Draft202012Validator(tool["input_schema"])
    validator.validate({"program": program(), "versions": ["2023"]})
    bad = {"program": {**program(), "ops": [{"op": "invented"}]}}
    assert list(validator.iter_errors(bad))
