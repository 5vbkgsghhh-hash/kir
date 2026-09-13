"""ORDERED VS. BUILT — AN AXIS NO INSTRUMENT EVER HAD.

🔴 WHY THIS FILE EXISTS. On 24.08 the author was building an 8×5 m
apartment and typed one extra digit into a coordinate. Up came an
«apartment» 5404 METERS long, repeated across four samples. All four legs
of the record came back green: the commit was confirmed, the witness was
satisfied, acceptance was `accepted`, the built-form judge was `judged`.
It was found by the OWNER'S EYE, opening the document.

There was nothing NOT to compare it with: the built-form judge computes
`stage_shape.cells[…].bbox_mm` on EVERY turn and puts it in the receipt.
The dimension had been sitting there the whole time — nobody had simply
picked it up. The sixth finding of this kind in two days: built, sitting
in the receipt, NOT CONNECTED.

🔴 THE AXIS LIVES IN THE HOST'S TREE, AND THIS IS SAID OUT LOUD
(04.09.2026). `summarise` and `_stage_bbox` are HOST instruments: zero
definitions in `/opt/kir`, both live in `/opt/kukai-rebuild1/backend/tools`.
So the claims below are SEAM claims, and the root MUST BE NAMED as a
variable, not baked in as a literal (the same reasoning as in
`test_stand_does_not_starve_the_author.py`; the form is the canon
`test_the_package_does_not_know_the_host.py`, with precedents in
`test_plural_operand_authority.py` and `test_record_ratchet.py`). Without
the root, the module is SKIPPED WITH A REASON, rather than turning green.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from kir import env

#: The HOST's root is optional: KIR stands without it too.
_HOST_ROOT = Path(env.get("KIR_HOST_ROOT", "/opt/kukai-rebuild1/backend"))
TOOLS = _HOST_ROOT / "tools"

if not (TOOLS / "author_loop_baseline.py").is_file():
    pytest.skip(
        f"ось «заказано против построенного» считают приборы ХОЗЯИНА "
        f"({TOOLS}); отсюда они непроверяемы, и зелёный здесь читался бы как "
        f"улика о KIR. Назвать корень: KIR_HOST_ROOT",
        allow_module_level=True)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


meter = _load("loop_meter")
alb = _load("author_loop_baseline")


def _tape(bbox, key="room"):
    """A single-task tape for `room`: ordered 6 000 × 4 000 mm."""
    return [{"key": key, "rounds": [
        {"n": 1, "built": True, "stage_bbox": bbox, "codes": [],
         "op_names": ["create_wall"], "reread": "judged"}]}]


def test_an_extra_digit_in_a_coordinate_is_named_by_numbers():
    """The exact mistake: an extra digit in the far corner."""
    s = alb.summarise(_tape([320000, -100, 0, 3206100, 4100, 3000]))
    size = s["tasks"][0]["size"]
    assert size["off"] is True
    # Order of magnitude is what distinguishes a DIGIT mistake from a
    # one-meter mistake.
    assert size["ratio"][0] > 100


def test_a_correct_build_is_not_cried_over():
    """🔴 FAIL CONTROL. The same design, built CORRECTLY: 6×4 m plus wall
    thickness. An instrument that screams at a correct build will be
    switched off on the second day."""
    s = alb.summarise(_tape([320000, -100, 0, 326100, 4100, 3000]))
    assert s["tasks"][0]["size"]["off"] is False


def test_the_unjudgeable_task_is_named_not_forgotten():
    """🔴 THE SAMPLE WITH OFFSETS HAS TWO LEGITIMATE DIMENSIONS, and a
    single expectation cannot distinguish correct from incorrect. Such a
    task must be TAKEN OUT from under the axis WITH A REASON in the
    source, not silently left without an expectation: silence here is
    indistinguishable from «forgot»."""
    keys = {t["key"] for t in alb.TASKS if t.get("expect_mm")}
    assert "unit_group" not in keys and "compute_py" not in keys
    src = (TOOLS / "author_loop_baseline.py").read_text(encoding="utf-8")
    assert "ГАБАРИТ ЭТОЙ ЗАДАЧИ НЕ СУДИМ" in src
    # And it is caught by a different instrument, rather than being left
    # completely unsupervised.
    assert "потолок длины стены" in src


def test_wall_thickness_is_not_a_discrepancy():
    """Grid lines and wall thickness produce a legitimate spread of
    hundreds of mm.

    🔴 THERE WAS A TAUTOLOGY HERE, AND IT WAS REMOVED ON 04.09.2026. The
    first assertion was `assert s["tasks"][0]["size"] is None or True` —
    true for ANY value: for `None` («not measured») and for `off is True`
    («the instrument screams at a correct build») alike. The instrument
    about wall thickness could not turn red NO MATTER WHAT, so its green
    was evidence of nothing.

    What is asserted is exactly what the tolerance was named as a number
    for (`0.15·a + 400` in `author_loop_baseline.summarise`), and all
    three halves carry weight:

      * the value is COMPUTED — without this, «not measured» would read
        as «matched», and that is exactly the law recorded below in
        `test_unmeasured_is_not_zero`;
      * the spread is REAL and it is in the HUNDREDS of mm — otherwise the
        sample isn't about wall thickness at all, but about an exact
        match, on which the tolerance is never exercised;
      * and yet it is NOT called a discrepancy.

    The edge of the tolerance is guarded by
    `test_the_named_tolerance_has_an_edge` below: without it, «wall
    thickness is not a discrepancy» would be proved by a tolerance of
    infinity.
    """
    s = alb.summarise(_tape([320000, -100, 0, 326100, 4100, 3000]))
    size = s["tasks"][0]["size"]
    assert size is not None, "величина не посчитана — судить нечего"
    assert size["asked_mm"] == [6000.0, 4000.0], size
    assert size["built_mm"] == [6100, 4200], size
    разброс = [abs(b - a) for a, b in zip(size["asked_mm"], size["built_mm"])]
    assert 100 <= min(разброс) and max(разброс) < 1000, (
        f"образец обязан нести разброс В СОТНЯХ мм, иначе он не про толщину "
        f"стены, а про точное совпадение: {разброс}")
    assert size["off"] is False, (
        f"законный разброс {разброс} мм названы расхождением: {size}")
    s2 = alb.summarise([{"key": "room", "rounds": [
        {"n": 1, "built": True, "codes": [], "op_names": ["create_wall"],
         "stage_bbox": [320000, -100, 0, 326100, 4100, 3000]}]}])
    assert s2["tasks"][0]["size"]["off"] is False


def test_the_named_tolerance_has_an_edge():
    """🔴 FAIL CONTROL FOR ITS NEIGHBOR ABOVE: the tolerance is not
    «generous», it has an EDGE.

    The tolerance is named as a number — `0.15·a + 400`, and for an order
    of 6 000 mm that is exactly 1 300 mm. The pair was taken from an
    actual build, not derived: a built 7 300 mm (`ratio` 1.22) passes,
    7 301 mm is already a discrepancy. One millimeter separates green from
    red, which means the instrument about wall thickness IS CAPABLE of
    turning red, and «not a discrepancy» above is a statement about the
    tolerance, not about its absence.
    """
    край = alb.summarise(_tape([0, 0, 0, 7300, 4000, 3000]))
    assert край["tasks"][0]["size"]["off"] is False, (
        f"край названного допуска обязан проходить: {край['tasks'][0]['size']}")
    за_краем = alb.summarise(_tape([0, 0, 0, 7301, 4000, 3000]))
    assert за_краем["tasks"][0]["size"]["off"] is True, (
        f"один мм за названным допуском обязан краснеть, иначе допуска нет "
        f"вовсе: {за_краем['tasks'][0]['size']}")


def test_unmeasured_is_not_zero():
    """The judge might not have judged at all. «Not measured» must differ
    from «matched»: a silent zero here would mean «built correctly»
    without a single measurement."""
    s = alb.summarise([{"key": "room", "rounds": [
        {"n": 1, "built": True, "codes": [], "op_names": ["create_wall"]}]}])
    assert s["tasks"][0]["size"] is None


def test_the_bbox_comes_from_the_judge_not_from_a_second_reading():
    """The dimension is taken from the judge's receipt, not read on a
    second trip into Revit: a second carrier of the same quantity would
    drift from the first."""
    v = {"stage_shape": {"cells": {
        "L1 · OST_Walls": {"bbox_mm": [0, 0, 0, 100, 10, 3000]},
        "L1 · OST_Floors": {"bbox_mm": [-50, -5, 0, 80, 20, 200]}}}}
    assert meter._stage_bbox(v) == [-50, -5, 0, 100, 20, 3000]
    assert meter._stage_bbox({"stage_shape": {"cells": {}}}) is None


def test_height_is_deliberately_not_judged():
    """🔴 HEIGHT IS NOT JUDGED, AND THIS IS A DECISION, NOT AN OVERSIGHT.

    `elevation_mm` is born from TWO different Revit calls under one name:
    `decompile/extract.py:1673` takes `ProjectElevation`,
    `open_model.py:1846` takes `Elevation`. On K3 they diverge by exactly
    3800 mm, 24 levels out of 24, and there is no argument for either of
    the two.

    🔴 THE GEOMETRY DID NOT DRIFT IN THE PROCESS — measured by a
    neighboring session on 24.08: the sets of floor-bottom elevations
    align at a shift of +0 mm, 27 of 27; sweeping shifts from −6000 to
    +6000 gave the best alignment at zero. The frame holds together
    because both halves are read within ONE frame.

    So this test is not guarding against today's discrepancy but against
    TOMORROW'S ONE-SIDED FIX: on the day someone reconciles one carrier
    and leaves the other untouched, the frames will genuinely drift
    apart, and the Z axis will start turning red on a correct build. As
    long as the quantity lives in two carriers with no argument between
    them, height is not judged.
    """
    s = alb.summarise(_tape([320000, -100, 3800, 326100, 4100, 6800]))
    assert s["tasks"][0]["size"]["off"] is False
    src = (TOOLS / "author_loop_baseline.py").read_text(encoding="utf-8")
    assert "ProjectElevation" in src and "3800" in src


# ── 🔴 F-125: A COMPARISON THAT NEVER HAPPENED IS NOT AGREEMENT ────────────
# (confirmed by execution on 04.09.2026)
#
# A failure of either comparator was replaced with an EMPTY discrepancy
# list, the block stayed `judged`, and the line shown to the human was
# WORD-FOR-WORD the same as for a healthy turn: «Расхождений между
# заявленным и построенным НЕ НАЙДЕНО.» The errors were already sitting in
# the block (`compare_error`, `compare_geometry_error`) — nobody ever asked
# for them. This is the same law recorded elsewhere in this file about the
# zero of the unread value: a zero for an UNCOMPUTED quantity is printed as
# a WORD, not as a number.

_ПУСТОЙ = {"elements_asked": 5, "elements_read": 5,
           "divergences": [], "divergences_total": 0,
           "geometry_divergences": [], "geometry_divergences_total": 0}


def _строка(**лишнее):
    from kir import built_verdict as bv
    return bv._message({**_ПУСТОЙ, **лишнее}, [], [])


def test_здоровый_ход_говорит_что_расхождений_нет():
    """CONTROL IN THE OTHER DIRECTION: without failures the line must stay
    unchanged."""
    текст = _строка()
    assert "НЕ НАЙДЕНО" in текст
    assert "СРАВНЕНИЕ НЕ ВЫПОЛНЯЛОСЬ" not in текст


def test_сорвавшийся_сравнитель_не_читается_как_согласие():
    for ключ in ("compare_error", "compare_geometry_error"):
        текст = _строка(**{ключ: "ValueError: сравнитель упал"})
        assert "НЕ НАЙДЕНО" not in текст, (
            f"{ключ}: сорвавшееся сравнение печатается как согласие")
        assert "СРАВНЕНИЕ НЕ ВЫПОЛНЯЛОСЬ" in текст
        assert "ValueError" in текст, "причина обязана быть названа дословно"


def test_уцелевший_сравнитель_назван_отдельно():
    """One failed, the other succeeded — the reader must know which one to
    trust."""
    текст = _строка(compare_error="ValueError: упал")
    assert "второй сравнитель (геометрии) отработал" in текст
    оба = _строка(compare_error="ValueError: упал",
                  compare_geometry_error="KeyError: и этот")
    assert "второй сравнитель" not in оба, (
        "когда сорвались оба, обещать уцелевшего нельзя")
