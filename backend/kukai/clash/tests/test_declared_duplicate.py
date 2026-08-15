"""ДУБЛИКАТ ОБЪЯВЛЕНИЯ: факт о ТЕКСТЕ ПРОГРАММЫ, а не о телах.

ЗАМЕР, ОТ КОТОРОГО ЭТОТ ФАЙЛ (11.08.2026). Клеш не может сказать «чинить» ни о
чём: верхняя ступень требует `proven is True`, та — сертифицированного
внутреннего перекрытия, а сертификат недостижим ДВАЖДЫ (нет производственного
издателя; ядро доказательства не умеет тела вращения — см.
`test_declared_section_certificate.py`). Тот же запрет накрыл и дубликаты
третий раз, своими словами в `exact_body_equality_proof`: «Ordinary production
producers currently emit no exact grade, so destructive duplicate advice
remains unreachable there».

НО ДЛЯ ДУБЛИКАТА ЭТОТ ЗАПРЕТ ОТВЕЧАЕТ НЕ НА ТОТ ВОПРОС. Геометрическое
совпадение оболочек — гипотеза о телах, и осторожность там законна. А «один и
тот же элемент ОБЪЯВЛЕН ДВАЖДЫ» — факт о ТЕКСТЕ: программа сказала одно и то
же два раза. Никакой оболочки в этом факте нет, огрублять нечего, ядру
доказательства делать нечего. Замер: две одинаковые операции в пачке дают два
элемента, побайтно совпадающих во ВСЁМ, кроме адреса (`p1/duct1` против
`p2/duct1`).

ПОЭТОМУ ЭТО САМАЯ ДЕШЁВАЯ ИЗ ТРЁХ ДОРОГ И ЕДИНСТВЕННАЯ, НЕ УПИРАЮЩАЯСЯ В
ЯДРО. И она же строит машинерию, нужную обеим остальным: второй род
свидетельства, чьё происхождение — ОБЪЯВЛЕНИЕ, а не тело.

ЧЕГО ЭТОТ ФАЙЛ НЕ ПОКРЫВАЕТ, названо поимённо:
  * он ничего не говорит о ПОСТРОЕННОМ здании: два одинаковых объявления могут
    построиться в один элемент или в два — это факт о программе, и квитанция
    называет его происхождение прямо в находке;
  * он не решает, СЕМАНТИЧЕСКИ ли эквивалентны две операции разного вида,
    дающие одинаковую геометрию: сравнивается объявление целиком, и разный
    текст — не дубликат, даже если тела совпали;
  * он не покрывает дубликаты, на которые кто-то ССЫЛАЕТСЯ: удалять то, что
    служит опорой другому опу, нельзя, и такая пара остаётся на `look` с
    названной причиной.
"""
from __future__ import annotations

from kukai.ir import clash_bundle as CB


def _duct(oid: str = "duct1", *, y_mm: float = 0.0,
          diameter_mm: float = 400.0) -> dict:
    return {"op": "create_duct", "id": oid,
            "p0_mm": [0.0, y_mm, 2700.0], "p1_mm": [5000.0, y_mm, 2700.0],
            "level": {"by": "name", "value": "Этаж 1"},
            "diameter_mm": diameter_mm}


def _pack(*programs: list[dict]) -> list[dict]:
    return [{"ops": list(ops)} for ops in programs]


def test_two_identical_declarations_carry_the_same_declaration_digest():
    """ГЛАВНЫЙ КОНТРПРИМЕР: до правки элемент не нёс НИКАКОГО отпечатка
    объявления, и «то же самое сказано дважды» было невыразимо."""
    geometry = CB.bundle_elements(_pack([_duct()], [_duct()]), snapshot=None)
    a, b = geometry.elements
    assert a["element_id"] != b["element_id"]
    assert a.get("declaration_digest"), a
    assert a["declaration_digest"] == b["declaration_digest"], (
        "два одинаковых объявления получили разные отпечатки")


def test_the_address_is_not_part_of_the_declaration():
    """Адрес пачки (`p1/duct1`) — НАШ учёт, а не то, что сказал автор. Войди он
    в отпечаток, дубликат стал бы невозможен по построению."""
    geometry = CB.bundle_elements(_pack([_duct("a")], [_duct("b")]),
                                  snapshot=None)
    a, b = geometry.elements
    assert a["element_id"] != b["element_id"]
    assert a["declaration_digest"] == b["declaration_digest"]


def test_a_different_declaration_is_not_a_duplicate():
    """Обратная сторона, без которой первый тест зелен и у отпечатка-константы."""
    geometry = CB.bundle_elements(
        _pack([_duct()], [_duct(diameter_mm=300.0)]), snapshot=None)
    a, b = geometry.elements
    assert a["declaration_digest"] != b["declaration_digest"]

    geometry = CB.bundle_elements(
        _pack([_duct()], [_duct(y_mm=1500.0)]), snapshot=None)
    a, b = geometry.elements
    assert a["declaration_digest"] != b["declaration_digest"]


def test_declared_duplicates_are_reported_as_certain_with_their_provenance():
    """РУЛИНГ 3, применённый к объявлению: происхождение едет В НАХОДКЕ.

    «Чинить» по факту о тексте и «чинить» по обмеру в Revit — разные
    утверждения, и ступень у них была бы одна.
    """
    report = CB.declared_duplicates(
        CB.bundle_elements(_pack([_duct()], [_duct()]), snapshot=None))
    assert len(report) == 1, report
    row = report[0]
    assert set(row["pair"]) == {"p1/duct1", "p2/duct1"}
    assert row["certain"] is True
    assert row["provenance"] == CB.DECLARATION_PROVENANCE
    assert "объявлен" in row["text_ru"].lower()


def test_a_referenced_declaration_is_refused_BY_NAME():
    """Удалять то, что служит ОПОРОЙ другому опу, нельзя: у дубликата есть
    внешняя зависимость, и пара остаётся неразрушающей с названной причиной.

    Ноль по умолчанию здесь был бы ложью с числом: «ссылок нет» и «ссылки не
    считали» — разные утверждения.
    """
    duct = _duct()
    referrer = {"op": "create_duct", "id": "branch",
                "p0_mm": [2500.0, 0.0, 2700.0], "p1_mm": [2500.0, 3000.0, 2700.0],
                "level": {"by": "ref", "value": "duct1"},
                "diameter_mm": 200.0}
    report = CB.declared_duplicates(CB.bundle_elements(
        _pack([duct, referrer], [_duct()]), snapshot=None))
    assert len(report) == 1, report
    row = report[0]
    assert row["certain"] is False
    assert row["refused"] == "declaration_is_referenced"


def test_a_single_declaration_produces_nothing():
    """Прибор, находящий дубликат в одиночном объявлении, бесполезен."""
    assert CB.declared_duplicates(
        CB.bundle_elements(_pack([_duct()]), snapshot=None)) == []
