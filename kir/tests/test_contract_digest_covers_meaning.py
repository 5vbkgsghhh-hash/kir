"""THE CONTRACT SIGNATURE MUST CHANGE WHEN THE MEANING CHANGES.

WHAT THIS COST, 26.08.2026, an experiment-MUTATION. One registry field was
substituted, and the signature was taken before and after:

    create_beam.level.authority   DERIVED_BY_REVIT -> AUTHORED
    contract digest:              DID NOT CHANGE

A run across all five carriers of meaning not covered by the signature
scored five out of five:

    authority · omission_transfers · caveat · result_by_param ·
    grounded_pool_by_param        — ALL BLIND

🔴 A BOUNDARY THAT MUST NOT BE MISREPRESENTED. This is a defect of
EVIDENCE, not of ENFORCEMENT. The enforcement path is intact and
verified: the wrong kind of reference will not build the wall,
`accepts_reference` rejects it at compile time. What is broken is only
provability: the contract became DIFFERENT, and the signature said "the
same". The module itself promises the opposite in its own docstring —
«Changing an operand, grounding rule, result identity, tolerance or
refinement obligation must therefore change the operation contract
digest» — and did not keep that promise for five fields.

WHY EXACTLY THESE FIVE MATTER TO THE MODEL, AND NOT ONLY TO THE
PROGRAMMER:

* `authority`              — whether the model writes this field or Revit
                             derives it itself. Introduced by
                             measurement: 540 of 540 beams landed at z=0
                             while "Floor 5" was written;
* `omission_transfers`     — what silently takes over if the field is
                             omitted. 420 columns landed at 2500 instead
                             of 3600–4500, not a single refusal, three
                             audits missed it;
* `caveat`                 — a runtime observation that would otherwise
                             be paid for in time. Introduced 26.08 after a
                             curtain wall: 22 calls, 630 s, the task not
                             closed. And the VERY FIRST edit to this
                             field's text (`e2bf5adc`, the same day) left
                             no trace in the signature;
* `result_by_param`        — the result kind, decided by a parameter.
                             Reading the static `result` for such an op
                             means getting the kind "wall" for a roof
                             type;
* `grounded_pool_by_param` — the grounding pool, decided by a parameter.

HOW THIS TEST DIFFERS FROM ENUMERATING FIELDS BY HAND. A field list
written into the test would be a SECOND CARRIER of the notion "what
belongs to meaning" and would drift apart from `ParamSpec` at the very
first new field — exactly how the present defect was born. That is why
coverage is DERIVED by walking `dataclasses.fields`, and the only
hand-written thing here is the EXCLUSION LIST, and every exclusion must
carry a reason.
"""
from __future__ import annotations

import dataclasses

import pytest

from kir import op_contract as OC
from kir import spec
from kir.registry_base import OpSpec, ParamSpec


def _digest(op_spec: OpSpec) -> str:
    return OC.OpContract.from_spec(op_spec).digest


def _with_param(op_spec: OpSpec, param_name: str, **changes) -> OpSpec:
    """The same op, with ONE parameter changed by one field."""
    return dataclasses.replace(op_spec, params=tuple(
        dataclasses.replace(p, **changes) if p.name == param_name else p
        for p in op_spec.params))


# ─────────────────────────────────────────────────────────────────────
# MUTATIONS. Each is exactly the change in meaning that the signature
# slept through.
# ─────────────────────────────────────────────────────────────────────

def test_смена_authority_меняет_подпись():
    """The exact experiment that caught the defect: create_beam.level."""
    base = spec.OPS["create_beam"]
    assert any(p.name == "level" and p.authority == "DERIVED_BY_REVIT"
               for p in base.params), "предпосылка опыта уехала из реестра"
    mutated = _with_param(base, "level", authority="AUTHORED")
    assert _digest(base) != _digest(mutated), (
        "AUTHORED и DERIVED_BY_REVIT дали ОДНУ подпись — модель не отличит "
        "поле, которое решает, от поля, которое не решает ничего")


def test_смена_omission_transfers_меняет_подпись():
    base = spec.OPS["create_column"]
    assert any(p.name == "top_level" and p.omission_transfers
               for p in base.params), "предпосылка опыта уехала из реестра"
    mutated = _with_param(base, "top_level", omission_transfers="")
    assert _digest(base) != _digest(mutated), (
        "снятие omission_transfers не тронуло подпись — исчезло объявление "
        "того, что молча берёт власть при пропуске поля")


def test_смена_caveat_меняет_подпись():
    """🔴 This field was edited on 26.08 (`e2bf5adc`) — the edit left no
    trace."""
    base = spec.OPS["create_curtain_grid_line"]
    assert base.caveat, "предпосылка опыта уехала из реестра"
    mutated = dataclasses.replace(base, caveat="СОВСЕМ ДРУГОЕ НАБЛЮДЕНИЕ")
    assert _digest(base) != _digest(mutated), (
        "переписали наблюдение о рантайме, которое едет МОДЕЛИ, "
        "и подпись сказала «контракт тот же»")


def test_снятие_result_by_param_меняет_подпись():
    base = spec.OPS["create_wall_type"]
    assert base.result_by_param is not None, "предпосылка уехала из реестра"
    mutated = dataclasses.replace(base, result_by_param=None)
    assert _digest(base) != _digest(mutated), (
        "род результата, решаемый параметром, в подпись не входит — "
        "статический `result` описывает лишь один из четырёх исходов")


def test_снятие_grounded_pool_by_param_меняет_подпись():
    base = spec.OPS["create_wall_type"]
    assert base.grounded_pool_by_param is not None, "предпосылка уехала"
    mutated = dataclasses.replace(base, grounded_pool_by_param=None)
    assert _digest(base) != _digest(mutated), (
        "пул заземления, решаемый параметром, в подпись не входит")


# ─────────────────────────────────────────────────────────────────────
# CONTROLS. Without them, the mutations' green means nothing.
# ─────────────────────────────────────────────────────────────────────

def test_контроль_pass_подпись_устойчива():
    """Twice in a row on the SAME registry — must match.

    Without this, "the signature changes" would be achieved by chance,
    and every mutation above would be green by construction.
    """
    for name in ("create_beam", "create_wall_type", "create_curtain_grid_line"):
        op_spec = spec.OPS[name]
        assert _digest(op_spec) == _digest(op_spec), f"{name}: подпись плывёт"


def test_контроль_pass_разные_опы_разные_подписи():
    digests = {name: _digest(op) for name, op in spec.OPS.items()}
    assert len(set(digests.values())) == len(digests), (
        "два опа получили одну подпись — подпись перестала опознавать оп")


def test_вырожденный_вход_оп_без_нового_смысла_подписывается():
    """An op that has none of the five fields must still get a signature,
    not crash.

    This is checked EXPLICITLY: without it, the fix could require the
    field's presence and crash 78 of the 82 ops that lack it.
    """
    plain = [name for name, o in spec.OPS.items()
             if not o.caveat and o.result_by_param is None
             and o.grounded_pool_by_param is None
             and all(p.authority == "AUTHORED" and not p.omission_transfers
                     for p in o.params)]
    assert len(plain) > 50, "вырожденных опов почти нет — контроль бессилен"
    for name in plain:
        digest = _digest(spec.OPS[name])
        assert len(digest) == 64, f"{name}: подпись не 64 hex"


# ─────────────────────────────────────────────────────────────────────
# COVERAGE IS DERIVED, NOT ENUMERATED.
# ─────────────────────────────────────────────────────────────────────

def test_каждое_поле_ParamSpec_или_в_подписи_или_в_исключениях():
    """A new `ParamSpec` field must MAKE THE INSTRUMENT FAIL, not fall
    through silently."""
    covered = set(OC.PARAM_SIGNED_FIELDS)
    excused = set(OC.PARAM_UNSIGNED_FIELDS)
    actual = {f.name for f in dataclasses.fields(ParamSpec)}
    stray = sorted(actual - covered - excused)
    assert not stray, (
        f"поля ParamSpec не объявлены ни подписанными, ни исключёнными: "
        f"{stray} — заведи в подпись либо назови причину исключения")
    phantom = sorted((covered | excused) - actual)
    assert not phantom, f"объявлены поля, которых у ParamSpec нет: {phantom}"


def test_каждое_поле_OpSpec_или_в_подписи_или_в_исключениях():
    covered = set(OC.OP_SIGNED_FIELDS)
    excused = set(OC.OP_UNSIGNED_FIELDS)
    actual = {f.name for f in dataclasses.fields(OpSpec)}
    stray = sorted(actual - covered - excused)
    assert not stray, (
        f"поля OpSpec не объявлены ни подписанными, ни исключёнными: {stray}")
    phantom = sorted((covered | excused) - actual)
    assert not phantom, f"объявлены поля, которых у OpSpec нет: {phantom}"


def test_каждое_исключение_несёт_причину():
    """A cell in the exclusion list is an ASSERTION, not a skip.

    🔴 TODAY THIS TEST IS VACUOUS, AND THAT IS SAID OUT LOUD. Both
    exclusion tables are EMPTY: neither `ParamSpec` nor `OpSpec` has a
    single field that would not change the contract's meaning for the
    model. The loop below performs ZERO checks, and passing off its green
    as proof would be "green by construction" — a named defect of this
    tree.

    The test is kept here not for today's green, but for the first field
    someone decides to exclude: then the loop will stop being empty. The
    live protection right now is in `_lint_contract_coverage`, and it has
    been verified by perturbation (five edits, five reds).
    """
    пусто = not OC.PARAM_UNSIGNED_FIELDS and not OC.OP_UNSIGNED_FIELDS
    for table, where in ((OC.PARAM_UNSIGNED_FIELDS, "ParamSpec"),
                         (OC.OP_UNSIGNED_FIELDS, "OpSpec")):
        for field_name, reason in table.items():
            assert isinstance(reason, str) and len(reason) > 20, (
                f"{where}.{field_name}: исключение без внятной причины")
    if пусто:
        pytest.skip("исключений нет — проверять нечего, и это утверждение")


def test_прибор_покрытия_КРАСНЕЕТ_на_возмущении():
    """Without this, the entire coverage mechanism would be green by
    construction.

    What is perturbed is the DECLARATION, not the registry: the field is
    removed from the signature, and the instrument must name it. The
    restoration is checked in a `finally` — otherwise a failing test
    would leave the module broken for the file's neighboring tests.
    """
    было = OC.PARAM_SIGNED_FIELDS
    try:
        OC.PARAM_SIGNED_FIELDS = tuple(
            f for f in было if f != "authority")
        with pytest.raises(OC.OpContractError) as поймано:
            OC._lint_contract_coverage()
        assert "authority" in str(поймано.value)
    finally:
        OC.PARAM_SIGNED_FIELDS = было
    OC._lint_contract_coverage()   # control: the instrument came back green
