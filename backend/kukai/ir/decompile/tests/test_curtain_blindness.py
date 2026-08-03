"""Почему сторона сравнения не видит ячеек витража — замер, а не гипотеза.

Пересборка №6 (артефакты `sob62_fas_r23_v11`): `set_curtain_panel` expected 54,
actual 0, при том что RECONCILED прошёл и все 1236 созданных элементов
проштампованы — то есть ячейки живьём СТОЯТ.

Рабочая гипотеза была «закон занявшего»: ячейку занимает стена, `GetPanelIds`
занявшего не показывает, и он уходит в `create_wall`. Тогда лишних стен было бы
около полусотни. В отчёте их девять, а недостающих десять — и это не сходится.

Эти тесты — опровергающие. Они читают ТОЛЬКО сохранённые артефакты (никакого
Revit, никакой сети) и фиксируют настоящую картину:

* 44 из 54 ячеек меняют тип НА МЕСТЕ — новый элемент не рождается, id не
  попадает в `created_ids`, а вселенная переизвлечения — это ровно
  `created_ids`. Такой эффект невидим по построению, сколько лифт ни чини;
* 10 из 54 (тип `_Пустая_`) элемент ПОРОЖДАЮТ, попадают в переизвлечение — и
  всё равно не дают ни одного `set_curtain_panel`-листа. Вот это настоящая
  дыра лифта, и прятать её нельзя;
* стен, чей тип совпадает с назначаемым типом ячейки, ровно ОДНА — «закон
  занявшего» объясняет 1 случай из 54, а не 44.

    venv/bin/pytest kukai/ir/decompile/tests/test_curtain_blindness.py -q
"""
from __future__ import annotations

import collections
import json
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[4]
V11 = BACKEND / "backend" / "data" / "decompile" / "sob62_fas_r23_v11"
DEBUG = V11 / "idempotence_debug.json"

pytestmark = pytest.mark.skipif(
    not DEBUG.exists(), reason="нет артефактов пересборки №6 (v11)")


@pytest.fixture(scope="module")
def debug() -> dict:
    return json.loads(DEBUG.read_text(encoding="utf-8"))


def _leaves(debug: dict, side: str) -> list[dict]:
    return [x["leaf"] for x in debug[side]]


def _scp(debug: dict) -> list[dict]:
    return [l for l in _leaves(debug, "expected")
            if l.get("op_name") == "set_curtain_panel"]


# ── пред-состояние: сравнение слепо ─────────────────────────────────────────

def test_the_comparison_side_produces_no_curtain_cell_leaves_at_all(debug):
    """Пред-состояние волны, зафиксированное дословно: ожидалось 54, вышло 0."""
    expected = collections.Counter(
        l.get("op_name") for l in _leaves(debug, "expected"))
    relifted = collections.Counter(
        l.get("op_name") for l in _leaves(debug, "relifted"))
    assert expected["set_curtain_panel"] == 54
    assert relifted["set_curtain_panel"] == 0


def test_the_occupant_wall_hypothesis_does_not_survive_the_numbers(debug):
    """Если бы ячейки уходили в стены, лишних стен было бы под полсотни.

    Их девять, и ни одна из них не про витраж: стен, чей тип совпадает с
    назначаемым типом ячейки, ровно одна.
    """
    rows = debug["reextracted_rows"]
    walls = [r for r in rows if r["category"] == "OST_Walls"]
    panel_types = {l["params"]["panel_type"]["value"] for l in _scp(debug)}
    occupants = [r for r in walls if r.get("type_name") in panel_types]
    assert len(occupants) <= 1, "закон занявшего объяснил бы куда больше"

    relifted_walls = sum(1 for l in _leaves(debug, "relifted")
                         if l.get("op_name") == "create_wall")
    expected_walls = sum(1 for l in _leaves(debug, "expected")
                         if l.get("op_name") == "create_wall")
    # Стен НЕ прибавилось — их даже на одну меньше. Сорок четыре ячейки не
    # превратились в стены ни в каком виде.
    assert relifted_walls <= expected_walls


# ── настоящая причина, разложенная на две ───────────────────────────────────

def test_forty_four_cells_change_type_in_place_and_create_nothing(debug):
    """Главная причина: `set_curtain_panel` — оп семейства MODIFY.

    Он меняет тип существующей ячейки; Revit сохраняет id; id не попадает в
    `created_ids`; переизвлечение спрашивает ровно про `created_ids`. Эффект
    невидим ПО ПОСТРОЕНИЮ вселенной сравнения, а не по слабости лифта.
    """
    from kukai.ir import spec
    assert spec.OPS["set_curtain_panel"].family == "modify"

    by_type = collections.Counter(
        l["params"]["panel_type"]["value"] for l in _scp(debug))
    in_place = by_type["ПН_ВТ_Стеклопакет_ теплый_30 мм"]
    creating = by_type["_Пустая_ Не учитывать_200мм"]
    assert in_place == 44 and creating == 10

    panels = [r for r in debug["reextracted_rows"]
              if r["category"] == "OST_CurtainWallPanels"]
    # В переизвлечении ровно те десять, что породили элемент, и ни одной из
    # сорока четырёх, сменивших тип на месте.
    assert len(panels) == creating
    assert {r.get("type_name") for r in panels} == {"_Пустая_ Не учитывать_200мм"}


def test_the_ten_cells_that_did_create_elements_are_still_dropped(debug):
    """Вторая причина, и она — настоящая дыра лифта, а не свойство вселенной.

    ПОДОЗРЕВАЕМЫЙ (чинить вслепую нельзя, ждём артефакт пересборки №7):
    `_lift_curtain_panel` доходит до листа только при
    `panel.address_state is CellAddressState.OK`, а адрес ячейки читается через
    `GetRefGridLines`, который живёт ТОЛЬКО на Panel. У копии ячейку занимает
    стена (`type_name` этих десяти листьев — "Стена"), поэтому адреса у неё
    может не быть вовсе. Проверить это посмертно сегодня нечем: индекс витражей
    копии в артефакты не попадал. С этой волны он дампится в
    `idempotence_debug.json` -> `curtain_index`, и после следующей живой
    пересборки подозреваемый станет доказуемым или отпадёт.

    Десять ячеек ЕСТЬ в переизвлечении как `OST_CurtainWallPanels`, но листьев
    из них не вышло: 1236 строк дали 1226 листьев, и недостающие десять —
    ровно они. Прятать это под карв-аутом нельзя: так уже прятались 15 живых
    промахов flip-guard под adjusted%.
    """
    rows = debug["reextracted_rows"]
    panels = [r for r in rows if r["category"] == "OST_CurtainWallPanels"]
    assert len(rows) - len(_leaves(debug, "relifted")) == len(panels) == 10


def test_the_missing_reason_is_uniform_and_says_nothing_useful_today(debug):
    """Сегодня все 54 попадают в одну безымянную кучу «лист не найден» — по
    ней невозможно отличить невидимое по построению от настоящей дыры."""
    report = json.loads(
        (pathlib.Path(__file__).resolve().parents[4] / "backend" / "data"
         / "decompile" / "sob62_fas_r23_v11" / "idempotence.json")
        .read_text(encoding="utf-8")) if (V11 / "idempotence.json").exists() else None
    if report is None:
        pytest.skip("нет idempotence.json")
    disc = report.get("discrepancies") or []
    scp = [d for d in disc if d.get("op_name") == "set_curtain_panel"]
    assert len(scp) == 54
    assert {d["reason"] for d in scp} == {
        "re-lifted leaf not found for this translated original"}
    assert all(d["expected_discrepancy_class"] is False for d in scp)


# ── правило вселенной: 44 вынесены, 10 остались видимыми ────────────────────

def test_the_structural_rule_carves_out_exactly_the_unobservable_44(debug):
    """Счётчик берётся из СТРОЕНИЯ, а не из списка имён: оп семейства
    `modify`, чей назначаемый тип не появился ни на одном переизвлечённом
    элементе, эффекта в created-ids не оставил и проверен быть не может."""
    import kir_idempotence as K

    expected = _leaves(debug, "expected")
    outside = K.modify_outside_universe(expected, debug["reextracted_rows"])
    assert len(outside) == 44
    assert {expected[i]["op_name"] for i in outside} == {"set_curtain_panel"}


def test_missing_shrinks_to_ten_and_those_ten_stay_visible(debug):
    """Ровно та граница, ради которой правило и писалось: 44 уходят из
    знаменателя, 10 остаются НЕДОСТАЧЕЙ. Карв-аут по имени опа унёс бы все 54 —
    так `place_family` уносил 15 живых промахов flip-guard."""
    import kir_idempotence as K

    expected = _leaves(debug, "expected")
    relifted = _leaves(debug, "relifted")
    outside = K.modify_outside_universe(expected, debug["reextracted_rows"])
    _m, _e, _a, per_kind, disc = K._compare(expected, relifted, outside)

    row = next(k.to_dict() for k in per_kind
               if k.op_name == "set_curtain_panel")
    assert row["outside_universe"] == 44
    assert row["expected"] == 10 and row["missing"] == 10
    assert sum(1 for d in disc if d["op_name"] == "set_curtain_panel") == 10


def test_nothing_was_added_to_the_adjusted_carve_out(debug):
    """В adjusted% не заведено ничего: вынос из вселенной — это не поблажка
    качеству, а честная граница проверяемости."""
    import kir_idempotence as K

    assert "set_curtain_panel" not in K.EXPECTED_DISCREPANCY_OPS
    expected = _leaves(debug, "expected")
    outside = K.modify_outside_universe(expected, debug["reextracted_rows"])
    _m, _e, _a, per_kind, _d = K._compare(
        expected, _leaves(debug, "relifted"), outside)
    row = next(k.to_dict() for k in per_kind if k.op_name == "set_curtain_panel")
    assert row["excluded_expected"] == 0
    assert row["expected_discrepancy_class"] is False


def test_a_modify_effect_that_did_create_an_element_is_never_carved_out(debug):
    """Обратная сторона правила: как только эффект породил элемент, он обязан
    проверяться. Иначе счётчик станет мусорным ведром для всего modify."""
    import kir_idempotence as K

    expected = _leaves(debug, "expected")
    rows = debug["reextracted_rows"]
    # Добавим элемент, несущий тип, который назначают те самые 44 ячейки.
    faked = rows + [{"category": "OST_CurtainWallPanels",
                     "type_name": "ПН_ВТ_Стеклопакет_ теплый_30 мм"}]
    assert K.modify_outside_universe(expected, faked) == []


def test_the_report_publishes_the_carve_out_as_a_number(debug):
    """Вынос обязан быть виден числом и списком опов, а не молчаливо
    уменьшенным знаменателем."""
    import kir_idempotence as K

    rep = K.IdempotenceReport(
        doc_stamp="t", delta_mm=(0, 0, 0), multiset_match=False,
        expected_hash="a", actual_hash="b", total_expected=10,
        total_matched=0, raw_exact_pct=0.0, adjusted_exact_pct=0.0,
        per_kind=(), discrepancies=(), datums_skipped=0, created_ids=(),
        cleanup_ok=True, cleanup_detail="", non_datum_total=100,
        comparable_coverage_pct=10.0,
        modify_outside_universe=44,
        modify_outside_universe_by_op=({"op_name": "set_curtain_panel",
                                        "count": 44},))
    d = rep.to_dict()
    assert d["modify_outside_universe"] == 44
    assert d["modify_outside_universe_by_op"] == [
        {"op_name": "set_curtain_panel", "count": 44}]
    assert "modify-эффектов вне вселенной created-ids" in \
        d["comparable_coverage_summary"]
    assert "set_curtain_panel×44" in d["comparable_coverage_summary"]
