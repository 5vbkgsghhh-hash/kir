"""CONTOUR SHAPE — ONE AUTHORITY FOR THREE CONSUMERS.

THE MEASUREMENT THAT BOUGHT THIS FILE (16.08.2026). A live run produced the refusal
`KIR-T001 profile.outer: форма — rect | l | poly` — it named three shapes and showed
NOT ONE of them. The agent spent three attempts and still never landed `rect`: there
it is `size_mm`, not `w`/`h`. At a turn cost of 17–18 s (measured the same day), a refusal without
a shape costs a full turn and one chance out of the budget.

The cause runs deeper than the text: the shape specification was written THREE TIMES — in the
docstring of `contour.py`, in the literals of `_validate_shape`, and by hand in `schema_gen.py`. Nothing
forced them to agree, and they had ALREADY diverged. Measured BY EXECUTION: three
of three checked programs were LEGAL according to the schema the model receives, and
REJECTED by the compiler — `size_mm=[50,50]`, `rotation_deg=720`,
`cut_mm=[10,10]`. The model was judged not by what it was actually shown.

The control holds three assertions:

  1. the refusal SHOWS each shape, and the list is checked AGAINST THE AUTHORITY, not against
     prose (otherwise the test would just be pinning down the same hand-written copy, only a fourth one);
  2. the schema and the validator AGREE on the measured cases — this is a re-measurement, not
     a reading of the code;
  3. the validator's set of legal fields is the same as declared in the authority, and
     this is checked BY BEHAVIOR: an extra field must be rejected.

Each has an opposite pole: the text does not invent shapes that do not exist; a legal
program remains legal; an optional field remains optional.
"""
from __future__ import annotations

import jsonschema
import pytest

from kir import compiler, contour, schema_gen


def _program(outer: dict) -> dict:
    """The input is built by PROD CODE: the same shape the gate lays down.

    The sample is taken from `gate_runner.programs['auth_stairs_landing']` — a test
    that builds its input bypassing prod code is green on a shape the product does not produce.
    """
    return {"ir_version": "1.0", "intent": "контроль форм",
            "ops": [{"op": "create_stairs_landing", "id": "LG1",
                     "stairs": {"by": "element_id", "value": 4242},
                     "contour": {"outer": outer},
                     "elevation_mm": 1500.0}]}


def _refusal_for(outer: dict) -> str:
    out = compiler.compile_program(_program(outer))
    for diag in getattr(out, "diagnostics", ()) or ():
        if "outer" in str(diag.field_name or ""):
            return diag.message_ru or ""
    pytest.fail(f"компилятор не отказал на {outer!r} — предмет не достигнут")


def test_the_control_reaches_its_subject():
    """Premise: the authority is non-empty and carries all three shapes."""
    assert set(contour.SHAPE_FORMS) == {"rect", "l", "poly"}
    for kind, slots in contour.SHAPE_FORMS.items():
        assert slots, f"форма {kind} объявлена без единого слота"


def test_the_refusal_shows_every_form_not_just_their_names():
    """The main assertion: the refusal shows the shape, it does not just list names."""
    text = _refusal_for({"shape": "circle", "origin": [0.0, 0.0]})

    for kind, slots in contour.SHAPE_FORMS.items():
        assert f'"shape":"{kind}"' in text, (
            f"форма {kind} объявлена в реестре и НЕ показана в отказе"
        )
        for slot in slots:
            assert slot.name in text, (
                f"слот {kind}.{slot.name} есть в авторитете и отсутствует в "
                f"тексте — значит текст рукописный и уже разошёлся"
            )
    assert "СЛЕДУЮЩИЙ ХОД" in text, (
        "отказ обязан называть причину И следующий ход (конституция проекта)"
    )


def test_the_refusal_invents_no_form(monkeypatch):
    """The opposite pole: the text is derived, not made up.

    Without it, the fix would come down to "print more", and an invented shape is worse than
    silence: it gets checked by a turn.
    """
    monkeypatch.setitem(contour.SHAPE_FORMS, "rect", contour.SHAPE_FORMS["rect"])
    text = contour.shape_forms_text("profile.outer")
    for invented in ("circle", "ellipse", "arc_ring"):
        assert invented not in text


def test_the_schema_and_the_compiler_agree_on_the_measured_cases():
    """Re-measurement of the discrepancy that bought this wave.

    Each case was captured by execution on 16.08: the schema said "legal", the compiler
    answered with a refusal. Here they must give ONE AND THE SAME answer.
    """
    validator = jsonschema.Draft202012Validator(schema_gen.program_schema())
    cases = [
        ({"shape": "rect", "origin": [0.0, 0.0], "size_mm": [2400.0, 1200.0]}, True),
        ({"shape": "rect", "origin": [0.0, 0.0], "size_mm": [50.0, 50.0]}, False),
        ({"shape": "rect", "origin": [0.0, 0.0], "size_mm": [2400.0, 1200.0],
          "rotation_deg": 720.0}, False),
        ({"shape": "l", "origin": [0.0, 0.0], "size_mm": [4000.0, 3000.0],
          "cut_mm": [10.0, 10.0]}, False),
    ]
    for outer, expected_ok in cases:
        program = _program(outer)
        schema_ok = not list(validator.iter_errors(program))
        compiler_ok = bool(compiler.compile_program(program).ok)
        assert compiler_ok is expected_ok, f"компилятор изменил вердикт на {outer!r}"
        assert schema_ok == compiler_ok, (
            f"РАСХОЖДЕНИЕ на {outer!r}: схема={'законно' if schema_ok else 'отказ'}, "
            f"компилятор={'ok' if compiler_ok else 'отказ'}. Модель судят не по "
            f"тому, что ей показали — это именной дефект проекта"
        )


def test_the_legal_field_set_is_the_authority_and_it_is_behavioural():
    """The set of fields is checked BY BEHAVIOR, not by comparing two lists."""
    assert contour.shape_fields("rect") == {
        "shape", "origin", "size_mm", "rotation_deg"}

    ok = _program({"shape": "rect", "origin": [0.0, 0.0],
                   "size_mm": [2400.0, 1200.0], "rotation_deg": 30.0})
    assert compiler.compile_program(ok).ok, (
        "необязательный слот авторитета отвергнут — авторитет и валидатор "
        "разошлись"
    )

    text = _refusal_for({"shape": "rect", "origin": [0.0, 0.0],
                         "size_mm": [2400.0, 1200.0], "w": 2400})
    assert "'w'" in text or '"w"' in text or "w" in text
    assert "size_mm" in text, (
        "отказ о лишнем поле обязан показать, КАКОЕ имя правильное: `w` вместо "
        "`size_mm` — ровно та ошибка, что стоила агенту трёх попыток"
    )
