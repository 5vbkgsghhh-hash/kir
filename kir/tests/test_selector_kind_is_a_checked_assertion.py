"""`kind` in a selector is a REDUNDANT ASSERTION, and it must agree.

What is pinned is a PROPERTY, not a one-off case: a parameter's kind
is declared by the registry (`ref_kinds`), and when the author writes
the same kind via a second carrier, the two carriers must agree. If
they agree — confirmation, the program moves on and `kind` does NOT
enter the normalized form. If they disagree — a refusal naming BOTH
kinds. Nothing to check against — a refusal, not silent agreement.

The measurement that bought the rule (25–26.08.2026): 17 refusals out
of 188 fresh ones — the corpus's top cause — is
`{"by": "name", "value": "Уровень 1", "kind": "level"}`.

The property is checked ACROSS THE WHOLE REGISTRY, not on one
operation: the rule is about a parameter's kind, and it must hold for
every parameter whose kind is declared.
"""
import pytest

from kir import authoring_validation as av
from kir import spec


def _селекторные_параметры():
    """All (op, parameter) pairs of kind `sel`/`sel_list` with a
    DECLARED reference kind."""
    for имя, ospec in sorted(spec.OPS.items()):
        for p in ospec.params:
            if p.kind in ("sel", "sel_list") and p.ref_kinds:
                yield имя, p


def test_совпавший_kind_принят_и_снят_у_каждого_параметра_реестра():
    проверено = 0
    for имя, p in _селекторные_параметры():
        род = str(getattr(p.ref_kinds[0], "value", p.ref_kinds[0]))
        sel = {"by": "name", "value": "X", "kind": род}
        out, note = av._kind_asserted_selector(sel, p)
        assert note is None, f"{имя}.{p.name}: совпавший род дал отказ «{note}»"
        assert "kind" not in out, (
            f"{имя}.{p.name}: `kind` доехал до нормализованного селектора — "
            "подтверждение обязано СНИМАТЬСЯ, иначе оно поедет в заземление")
        assert out == {"by": "name", "value": "X"}
        проверено += 1
    assert проверено >= 20, (
        f"проверено всего {проверено} параметров — реестр не мог так усохнуть; "
        "скорее сломался отбор, и тогда зелёный цвет ничего не значит")


def test_разошедшийся_kind_отказывает_и_называет_оба_рода():
    for имя, p in _селекторные_параметры():
        рода = {str(getattr(k, "value", k)) for k in p.ref_kinds}
        чужой = next(r for r in ("level", "wall_type", "family_symbol",
                                 "ceiling_type") if r not in рода)
        out, note = av._kind_asserted_selector(
            {"by": "name", "value": "X", "kind": чужой}, p)
        assert note, f"{имя}.{p.name}: расхождение родов прошло молча"
        assert чужой in note and p.name in note, (
            f"{имя}.{p.name}: отказ не называет оба носителя: {note}")
        assert "kind" in out, "при расхождении селектор обязан остаться как был"


def test_без_объявленного_рода_сверять_нечем_и_это_отказ():
    p = next((p for _, ospec in spec.OPS.items() for p in ospec.params
              if p.kind == "sel" and not p.ref_kinds), None)
    if p is None:
        pytest.skip("в реестре нет селектора без объявленного рода")
    out, note = av._kind_asserted_selector(
        {"by": "name", "value": "X", "kind": "level"}, p)
    assert note and "сверить не с чем" in note
    assert "kind" in out


def test_закрытый_набор_ключей_не_ослаблен():
    p = next(p for _, p in _селекторные_параметры())
    род = str(getattr(p.ref_kinds[0], "value", p.ref_kinds[0]))
    # `kind` next to ANY other extra key is still a refusal: exactly
    # one key is removed, and only when the form is legal without it.
    out, note = av._kind_asserted_selector(
        {"by": "name", "value": "X", "kind": род, "чужое": 1}, p)
    assert note is None and out.get("чужое") == 1 and "kind" in out
    assert not av._sel_shape_ok(out)


def test_живая_программа_из_корпуса_собирается():
    """The very form refused live on 26.08 at 08:15 (ox-alpha, Revit
    2026)."""
    from kir import compiler
    компилируется = {
        "defaults": {"level": {"by": "name", "kind": "level",
                               "value": "Уровень 1"}},
        "ir_version": "1.0",
        "ops": [{"op": "create_wall", "id": "w1", "height_mm": 3000,
                 "p0_mm": [1500, 0], "p1_mm": [7500, 0]}]}
    план = compiler.plan_program(компилируется)
    assert план is not None
