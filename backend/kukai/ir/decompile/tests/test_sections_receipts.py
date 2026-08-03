"""Квитанции fail-open сечений — ревью кодекса №12.

До этой волны `null`, `HasValue=false`, чужой `StorageType` и исключение внутри
`__PutLengthParam` схлопывались в ОДИН отсутствующий ключ. Замер на v13
показывает, чего это стоит: ширина снята у 992 стен из 1189, а 197 пропусков
ТОЧНО совпадают с витражными носителями (`curtain.index.json`:
`curtain_available=True` ровно у 197, пересечение с пропусками — 197, разность
в обе стороны — 0). Совпадение идеальное, и всё равно доказательством не
является: код не мог отличить «у витражного типа параметра нет» от «параметр
есть, а прочитать не вышло». Квитанция это различает по построению.

Закон переписи здесь буквальный: сумма шести счётчиков КАЖДОГО параметра
обязана равняться числу опрошенных элементов категории.

**Живьём не проверено:** офлайн доказана проводка (эмиссия → страница →
агрегат → `category_status` → закон). Какие именно из шести исходов даёт живой
Revit на витражной стене — замер v14.

    venv/bin/pytest kukai/ir/decompile/tests/test_sections_receipts.py -q
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from kukai.ir.decompile.extract import (
    SECTION_PARAM_NAMES,
    ExtractionProtocolError,
    _parse_page,
    _Scope,
    build_category_batch_cs,
)
from kukai.ir.decompile.schema import (
    SECTION_RECEIPT_OUTCOMES,
    CategoryState,
    CategoryStatus,
    L0SchemaError,
    SectionReceipt,
)
from kukai.ir.decompile.tests.fixtures_decompile import make_element

LIVE_V13 = (pathlib.Path(__file__).resolve().parents[4]
            / "backend" / "data" / "decompile" / "sob62_fas_r23_v13")


# ── эмиссия ────────────────────────────────────────────────────────────────

def test_the_emission_counts_every_outcome_of_a_section_read():
    """Шесть исходов обязаны быть РАЗНЫМИ ветками генерируемого C#.

    Проверяется не текст ради текста: каждая строка ниже — это исход, который
    прежде был неотличим от остальных пяти.
    """
    cs = build_category_batch_cs("OST_Walls")
    assert "__PutSectionParam" in cs, "квитанционного чтения сечений нет"
    assert "__sectionReceipts" in cs
    # instance_hit / type_hit — разные слоты, потому что толщина живёт на типе,
    # и «прочитали у типа» это другой факт, чем «прочитали у экземпляра».
    assert "__fromType ? 1 : 0" in cs
    # not_applicable (параметра нет вовсе) против no_value (есть, пуст).
    assert "__exists ? 3 : 2" in cs
    assert "__p.StorageType != StorageType.Double" in cs
    assert "if (!__counted) __BumpSection(__name, 5)" in cs
    for name in SECTION_RECEIPT_OUTCOMES:
        assert f'"{name}"' in cs, name


@pytest.mark.parametrize("param", SECTION_PARAM_NAMES)
def test_every_section_parameter_goes_through_the_receipt_helper(param):
    """Ни один параметр сечения не смеет остаться на молчаливом
    `__PutLengthParam`: одна забытая строка вернёт неразличимый пропуск."""
    cs = build_category_batch_cs("OST_Walls")
    # WALL_CROSS_SECTION — перечисление (Integer), а не длина: у него свой
    # читатель, но квитанция ОБЩАЯ, поэтому закон переписи один на всех.
    from kukai.clash.hulls import SECTION_ENUM_PARAM_NAMES
    # Перечисления и флаги (Integer) читаются своим helper'ом, но КВИТАНЦИЯ
    # у них общая с длинами — закон переписи один на всех.
    helper = ("__PutSectionIntParam" if param in SECTION_ENUM_PARAM_NAMES
              else "__PutSectionParam")
    assert f"{helper}(__e, BuiltInParameter.{param}" in cs
    assert f"__PutLengthParam(__e, BuiltInParameter.{param}" not in cs


def test_sections_are_still_read_through_the_type():
    """Толщина живёт на `WallType`, диаметр — на типе трубы. Квитанция не смеет
    отменить падение на тип, иначе она аккуратно посчитает нули."""
    cs = build_category_batch_cs("OST_Walls")
    assert "var __type = doc.GetElement(__e.GetTypeId());" in cs
    assert "__tp = __type.get_Parameter(__bip);" in cs


def test_the_page_returns_its_receipts():
    cs = build_category_batch_cs("OST_PipeCurves")
    assert '{"section_receipts", __receipts}' in cs
    assert ".OrderBy(" in cs, "порядок квитанций обязан быть детерминированным"


# ── страница ───────────────────────────────────────────────────────────────

def _receipt_rows(count: int, *, slot: str = "instance_hit",
                  names=SECTION_PARAM_NAMES) -> list[dict]:
    rows = []
    for name in names:
        row = {"parameter": name}
        for outcome in SECTION_RECEIPT_OUTCOMES:
            row[outcome] = count if outcome == slot else 0
        rows.append(row)
    return rows


def _page(elements: list[dict], receipts) -> dict:
    return {"elements": elements, "has_more": False, "next_cursor": None,
            "section_receipts": receipts}


def _element(eid: str, category: str) -> dict:
    """Строка ровно той формы, какую отдаёт мост (общая подделка волны A)."""
    row = make_element(category, int(eid))
    row["level_id"] = None
    row["level_name"] = None
    return row


def test_a_page_without_receipts_is_refused():
    """Мост, не приславший квитанций на запрошенное чтение, — это ровно тот
    молчаливый провал, ради которого квитанции и заводились."""
    page = {"elements": [_element("1", "OST_Walls")], "has_more": False,
            "next_cursor": None}
    with pytest.raises(ExtractionProtocolError, match="section_receipts"):
        _parse_page(page, category="OST_Walls", scope=_Scope("__all__", 1),
                    after_element_id=None)


def test_a_page_whose_receipts_do_not_add_up_is_refused():
    """Закон переписи: сумма шести счётчиков = число опрошенных."""
    page = _page([_element("1", "OST_Walls")], _receipt_rows(2))
    with pytest.raises(ExtractionProtocolError, match="не сходится"):
        _parse_page(page, category="OST_Walls", scope=_Scope("__all__", 1),
                    after_element_id=None)


def test_a_page_missing_one_parameter_row_is_refused():
    """Пропавшая строка параметра означала бы, что его перестали спрашивать —
    и «сечения нет» опять стало бы неотличимо от «не спрашивали»."""
    page = _page([_element("1", "OST_Walls")],
                 _receipt_rows(1, names=SECTION_PARAM_NAMES[:-1]))
    with pytest.raises(ExtractionProtocolError, match="параметр"):
        _parse_page(page, category="OST_Walls", scope=_Scope("__all__", 1),
                    after_element_id=None)


def test_a_good_page_carries_its_receipts_through():
    page = _page([_element("1", "OST_Walls")], _receipt_rows(1, slot="type_hit"))
    elements, has_more, cursor, receipts = _parse_page(
        page, category="OST_Walls", scope=_Scope("__all__", 1),
        after_element_id=None)
    assert len(elements) == 1 and has_more is False and cursor is None
    by_name = {r.parameter: r for r in receipts}
    assert by_name["WALL_ATTR_WIDTH_PARAM"].type_hit == 1
    assert by_name["WALL_ATTR_WIDTH_PARAM"].total() == 1


def test_an_empty_page_carries_no_receipt_rows():
    """Нулевая страница никого не опрашивала — и не смеет утверждать обратное."""
    elements, _, _, receipts = _parse_page(
        _page([], []), category="OST_Walls", scope=_Scope("__all__", 0),
        after_element_id=None)
    assert elements == () and receipts == ()


# ── квитанция как тип ──────────────────────────────────────────────────────

def test_the_six_outcomes_are_the_ones_the_review_asked_for():
    assert SECTION_RECEIPT_OUTCOMES == (
        "instance_hit", "type_hit", "not_applicable", "no_value",
        "wrong_storage", "exception")


def test_a_status_whose_receipts_contradict_its_count_is_a_schema_error():
    """Закон переписи живёт в ТИПЕ, а не в вызывающем коде: иначе его обойдёт
    первый же новый путь записи."""
    good = CategoryStatus(
        category="OST_Walls", state=CategoryState.COMPLETE,
        extracted_count=3, expected_count=3,
        section_receipts=(SectionReceipt("WALL_ATTR_WIDTH_PARAM",
                                         instance_hit=1, type_hit=2),))
    assert good.section_receipts[0].total() == 3
    with pytest.raises(L0SchemaError, match="не сходится"):
        CategoryStatus(category="OST_Walls", state=CategoryState.COMPLETE,
                       extracted_count=3, expected_count=3,
                       section_receipts=(SectionReceipt(
                           "WALL_ATTR_WIDTH_PARAM", instance_hit=1),))


def test_an_older_stream_says_receipts_are_absent_instead_of_zero():
    """L0, записанный до этой волны, обязан сказать «квитанций нет», а не
    показать шесть нулей: ноль — это утверждение, которого он не делал."""
    row = {"category": "OST_Walls", "state": "complete", "extracted_count": 2,
           "expected_count": 2, "error": None}
    assert CategoryStatus.from_dict(row).section_receipts is None
    with_receipts = CategoryStatus.from_dict({
        **row, "section_receipts": _receipt_rows(2)})
    assert len(with_receipts.section_receipts) == len(SECTION_PARAM_NAMES)


def test_receipts_survive_the_json_round_trip():
    status = CategoryStatus(
        category="OST_PipeCurves", state=CategoryState.COMPLETE,
        extracted_count=1, expected_count=1,
        section_receipts=tuple(
            SectionReceipt(name, not_applicable=1) for name in SECTION_PARAM_NAMES))
    back = CategoryStatus.from_dict(json.loads(json.dumps(status.to_dict())))
    assert back == status


# ── v13: гипотеза «197 пропусков = витражные носители», числом ──────────────

@pytest.mark.skipif(not LIVE_V13.exists(),
                    reason="живой декомпайл только на прод-боксе")
def test_v13_wall_width_gaps_coincide_exactly_with_curtain_hosts():
    """Числом, а не на глаз: 1189 стен, ширина у 992, пропусков 197; витражных
    носителей ровно 197; пересечение 197, разность в ОБЕ стороны 0.

    Совпадение идеальное — и всё-таки это КОРРЕЛЯЦИЯ. Квитанция превращает её
    в поэлементный диагноз (`not_applicable` против `no_value`/`exception`), но
    сам диагноз придёт только с живого прогона v14: в v13 квитанций ещё нет.
    """
    walls = {}
    for line in (LIVE_V13 / "L0.jsonl").open(encoding="utf-8"):
        line = line.strip()
        if not line or '"OST_Walls"' not in line:
            continue
        row = json.loads(line)
        if row.get("record") != "element":
            continue
        el = row["element"]
        if el.get("category") == "OST_Walls":
            walls[str(el["element_id"])] = el
    no_width = {k for k, v in walls.items()
                if "WALL_ATTR_WIDTH_PARAM" not in (v.get("params") or {})}
    index = json.loads(
        (LIVE_V13 / "curtain.index.json").read_text(encoding="utf-8"))["curtain_index"]
    curtain = {k for k, v in index.items() if v.get("curtain_available")}
    assert (len(walls), len(no_width), len(curtain)) == (1189, 197, 197)
    assert no_width == curtain, "гипотеза «пропуск ширины = витраж» опровергнута"


@pytest.mark.skipif(not LIVE_V13.exists(),
                    reason="живой декомпайл только на прод-боксе")
def test_v13_predates_the_receipts_and_says_so():
    """v13 записан ДО этой волны: `category_status` в нём квитанций не несёт,
    и читатель обязан увидеть `None`, а не молчаливый ноль."""
    for line in (LIVE_V13 / "L0.jsonl").open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("record") == "category_status":
            assert CategoryStatus.from_dict(row["status"]).section_receipts is None
            return
    pytest.fail("в v13 нет ни одной строки category_status")
