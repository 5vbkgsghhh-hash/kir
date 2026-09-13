"""A WALL HAS A CEILING ON ITS LENGTH, NOT JUST A FLOOR.

🔴 WHY THIS FILE EXISTS. On 08.24 the author was building an 8x5 meter
apartment and typed the far corner as `6008000` instead of `608000` — one
extra digit. The result was an "apartment" 5404 meters LONG at a width of
five, repeated across four samples. EVERYTHING passed: compilation, the
witness, acceptance (`accepted`), `built=True`. It was found by the OWNER'S
OWN EYE opening the document — not one of our instruments said a word.

The symmetry was broken: we had rejected a wall of ZERO length since 08.04,
while accepting a five-kilometer wall in silence; height is bounded
(`height_mm` ≤ 100 000), length is not.
"""
from __future__ import annotations

from kir import contour as contour_mod
from kir.authoring_validation import (_MAX_SEGMENT_MM,
                                           _MIN_SEGMENT_MM,
                                           reject_segment_length,
                                           reject_zero_length)
from kir.compiler import compile_program


def _wall(p1, p0=(600000.0, 0.0)):
    return {"ir_version": "1.0", "intent": "проба",
            "ops": [{"op": "create_wall", "id": "W1",
                     "p0_mm": list(p0), "p1_mm": list(p1),
                     "level": {"name": "Уровень 1"}, "height_mm": 3000}]}


def _codes(out):
    return [(d.code, d.message_ru or "") for d in out.diagnostics]


def test_the_live_kilometre_apartment_is_refused():
    """The very program that built the five-kilometer apartment."""
    out = compile_program(_wall((6008000.0, 0.0)), "2026", snapshot={})
    assert not out.ok
    hit = [m for c, m in _codes(out) if "потолке сцены" in m]
    assert hit, _codes(out)
    assert "5408 м" in hit[0]
    # The refusal must name the LIKELY CAUSE, not just the boundary: an
    # extra digit is what the author looks for with their eyes, and
    # ">500000" is not an address for them.
    assert "ЛИШНИЙ РАЗРЯД" in hit[0]


def test_a_long_but_real_wall_still_passes():
    """🔴 CONTROL-FAIL. The ceiling must let real lengths through. The
    longest wall among six decompiled buildings is 58.5 m out of 49,857
    read; four hundred meters is four times any real one and still
    legitimate."""
    out = compile_program(_wall((1000000.0, 0.0), p0=(600000.0, 0.0)),
                          "2026", snapshot={})
    assert not any("потолке сцены" in m for _, m in _codes(out)), _codes(out)


def test_zero_length_law_is_unchanged():
    """The lower bound bought on 08.04 must stay in place.

    🔴 2026-08-25 — the mission's instrument (`refusal_actionability.py`)
    caught that this refusal carried a CODE and an ADDRESS but not a FORM:
    there was no `expected`, no measured length, no points themselves. The
    check was updated to the INVARIANT (code, field, measured length,
    boundary), not to the literal old phrase, which the fix removed along
    with the muteness."""
    diags: list = []
    assert reject_segment_length([0, 0], [0, 0.5], "create_wall", 0, "W1",
                                 diags) is False
    d = diags[0]
    assert d.code == "KIR-T002" and d.field_name == "p1_mm"
    assert d.expected == f">= {_MIN_SEGMENT_MM:.0f} мм"
    assert d.got == 0.5
    assert "[0, 0]" in d.message_ru and "[0, 0.5]" in d.message_ru


def test_both_stages_call_the_same_law():
    """The name by which the law calls `ground` must lead to THE SAME
    function: a rule written twice diverges at one of the two places."""
    assert reject_zero_length is reject_segment_length


def test_the_ceiling_is_not_a_third_carrier_of_the_same_number():
    """🔴 A NAMED CLASS OF TREE DEFECT: a quantity declared in two places
    diverges at the first edit. The segment's ceiling is THE SAME quantity
    as the shape's side ceiling, not a copy of it."""
    assert _MAX_SEGMENT_MM is contour_mod.SHAPE_SIDE_MAX_MM
