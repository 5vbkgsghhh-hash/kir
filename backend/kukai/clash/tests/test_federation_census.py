"""СВЯЗАННЫЕ ДОКУМЕНТЫ: сколько именно поиск НЕ ВИДЕЛ.

Клеш связанные документы не видит вовсе, и это честно: строки `link` в L0
считаются, их элементы оболочек не получают, ось `federation` объявляет
`complete=false`. Спорна не полнота, а ЧИСЛО, которым неполнота названа.

    snapshot.py:  snap.census.linked_elements_unscored = origin["links_in_l0"]

Имя объявляет ЭЛЕМЕНТЫ связанных файлов («в потоке есть, оболочек им никто не
строил» — комментарий у самого поля), код читает ЧИСЛО СТРОК-СВЯЗЕЙ. Модель с
тремя связями по сорок тысяч элементов отчитывается тройкой. Это наш главный
класс дефекта: величина объявлена в одном месте и прочитана в другом, и ничто
не заставляет их совпасть.

ОТЯГЧАЮЩЕЕ, И ОНО ЖЕ ЛЕКАРСТВО: настоящее число ЗАМЕРЕНО и выброшено на
соседней строке. Экстрактор кладёт в строку связи `element_count`, снятый с
`GetLinkDocument()` (`ir/decompile/extract.py`), а `read_decompile` строку
связи не открывает вовсе — только `links += 1`. Спросить авторитет здесь
буквально дешевле, чем объявить.

ЧЕГО ЭТИ ТЕСТЫ НЕ ПОКРЫВАЮТ. Они доказывают, что число неполноты названо
верно, и НИЧЕГО не говорят о том, найдёт ли клеш коллизию в связанном файле:
он их по-прежнему не видит по построению, оболочки связанным элементам не
строятся, и приведения в одну систему координат в этом пути нет. Громкая и
точная неполнота — это не федеративный клеш, это честный отчёт о его
отсутствии.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from kukai.clash import detect as D
from kukai.clash import snapshot as S


def _l0(tmp: pathlib.Path, links: list[dict], *,
        declared_link_count: int | None = None) -> pathlib.Path:
    """Синтетический L0 в ЗАМЕРЕННОЙ форме живого артефакта.

    Форма строки связи взята у эмиттера (`extract.py`, цикл по
    `RevitLinkInstance`), а не выдумана: `element_count` заполняется только
    когда `GetLinkDocument()` вернул документ, иначе остаётся `null`.
    """
    d = tmp / "run"
    d.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = [
        {"record": "header", "schema_version": "1.0",
         "document": {"census": [{"key": "OST_Walls", "count": 2,
                                  "name": "Стены"}],
                      "doc_name": "t", "change_stamp": "t"}}]
    for i in range(2):
        rows.append({"record": "element", "element": {
            "element_id": str(100 + i), "category": "OST_Walls",
            "bbox_min_mm": [i, 0, 0], "bbox_max_mm": [i + 1, 1, 1]}})
    for row in links:
        rows.append({"record": "link", "link": row})
    rows.append({"record": "category_status",
                 "status": {"category": "OST_Walls", "expected_count": 2,
                            "extracted_count": 2, "state": "complete",
                            "error": None}})
    rows.append({"record": "footer", "element_count": 2, "category_count": 1,
                 "link_count": (len(links) if declared_link_count is None
                                else declared_link_count),
                 "stream_complete": True})
    (d / "L0.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return d


def _link(name: str, count: int | None) -> dict:
    return {"element_id": name, "name": name, "loaded": count is not None,
            "element_count": count, "bbox_min_mm": None, "bbox_max_mm": None,
            "discipline": "ar"}


def test_the_number_of_unscored_elements_is_not_the_number_of_links(tmp_path):
    """ГЛАВНЫЙ КОНТРПРИМЕР. Три связи, сорок тысяч элементов, отчёт «3»."""
    d = _l0(tmp_path, [_link("ar", 12_000), _link("kr", 20_000),
                       _link("ov", 8_000)])
    snap = S.build_from_decompile(d)
    assert snap.origin["links_in_l0"] == 3
    assert snap.census.linked_elements_unscored == 40_000, (
        "число названо ЭЛЕМЕНТАМИ, а посчитаны строки-связи")


def test_a_count_that_was_not_read_is_named_never_guessed(tmp_path):
    """Связь не загружена — `GetLinkDocument()` пуст, числа НЕТ.

    Подставить сюда ноль значило бы заменить одну ложь другой: «в связи ноль
    элементов» и «число элементов связи не прочитано» — разные утверждения, и
    второе честно.
    """
    d = _l0(tmp_path, [_link("ar", 12_000), _link("kr", None),
                       _link("ov", None)])
    snap = S.build_from_decompile(d)
    assert snap.census.linked_elements_unscored == 12_000
    assert snap.census.links_without_element_count == 2
    assert snap.origin["links_in_l0"] == 3
    manifest = snap.join_manifest()
    assert manifest["linked_elements_unscored"] == 12_000
    assert manifest["links_without_element_count"] == 2


def test_a_sum_of_zero_must_not_read_as_a_model_without_links(tmp_path):
    """ЛОВУШКА ТОГО ЖЕ КЛАССА, И ОНА ХУЖЕ ИСХОДНОЙ.

    Если полноту федерации решать по СУММЕ элементов, модель, у которой все
    связи выгружены, даст сумму 0 и прочитается как модель БЕЗ связей — то
    есть отчёт станет зелёным ровно там, где видел меньше всего. Различить их
    можно только тремя числами разом, поэтому все три и публикуются.
    """
    d = _l0(tmp_path, [_link("ar", None), _link("kr", None)])
    snap = S.build_from_decompile(d)
    assert snap.census.linked_elements_unscored == 0
    assert snap.census.links_without_element_count == 2
    assert snap.origin["links_in_l0"] == 2

    clean = S.build_from_decompile(_l0(tmp_path / "clean", []))
    assert clean.census.linked_elements_unscored == 0
    assert clean.census.links_without_element_count == 0
    assert clean.origin["links_in_l0"] == 0


def test_a_model_without_links_publishes_three_zeroes(tmp_path):
    """Обратная сторона: без связей все три числа обязаны быть нулями, иначе
    новый счётчик просто красит всё в красный и перестаёт что-либо значить."""
    snap = S.build_from_decompile(_l0(tmp_path, []))
    assert snap.census.linked_elements_unscored == 0
    assert snap.census.links_without_element_count == 0
    assert snap.origin["links_in_l0"] == 0


def test_the_footer_link_count_must_match_the_stream(tmp_path):
    """Футер объявляет `link_count`, и до сих пор его не читал НИКТО — при
    том что `element_count` и `category_count` из того же футера сверяются с
    потоком и роняют прогон. Связь, потерянная при записи, оставляла перепись
    сходящейся сама с собой — ровно та дыра, ради которой сверка футера и
    заведена (ревью №10)."""
    d = _l0(tmp_path, [_link("ar", 12_000)], declared_link_count=4)
    with pytest.raises(S.SnapshotIntegrityError):
        S.build_from_decompile(d)


def test_the_federation_axis_is_wired_to_all_three_corrected_numbers(tmp_path):
    """РАТЧЕТ СРАБОТАЛ — И ЭТО ЕГО ПРАВИЛЬНЫЙ ИСХОД, А НЕ РЕГРЕССИЯ.

    Здесь стоял `test_completeness_still_ignores_federation_and_this_is_the_
    open_gap`: он утверждал сегодняшнюю правду — оси федерации у
    `completeness_of()` НЕТ, поэтому `detect(require_complete=True)` объявляет
    полным поиск на модели со связями — и был обязан покраснеть, когда ось
    приедет. Ось приехала волной 11.08.2026, ратчет покраснел, и его отказ
    указал ровно на проводку. Это и было его назначение.

    Теперь проверяется проводка: ось обязана публиковать ВСЕ ТРИ числа, потому
    что порознь они не заменяют друг друга.
    """
    d = _l0(tmp_path, [_link("ar", 12_000), _link("kr", 20_000),
                       _link("ov", None)])
    axis = S.build_from_decompile(d).coverage_axes(
        geometry_scope="mvp")["federation"]
    assert axis["linked_elements_unscored"] == 32_000
    assert axis["links_without_element_count"] == 1
    assert axis["links_in_l0"] == 3
    assert axis["complete"] is False
    assert D.completeness_of(S.build_from_decompile(d))["complete"] is False


def test_completeness_keys_on_links_not_on_the_sum_of_their_elements(tmp_path):
    """УСЛОВИЕ СЛИЯНИЯ, И БЕЗ НЕГО ВОЛНА ВЫПУСКАЛА БЫ НОВЫЙ МОЛЧАЛИВО-НЕВЕРНЫЙ
    ИСХОД.

    Ось написана, когда `linked_elements_unscored` держал ЧИСЛО СВЯЗЕЙ: тогда
    `linked == 0` значило «связей нет» и было верно СЛУЧАЙНО. Счётчик
    исправлен и держит ЭЛЕМЕНТЫ — и то же выражение стало ложью ровно на
    худших моделях: у здания, все связи которого выгружены, `element_count` не
    прочитан ни у одной, сумма равна нулю, и поиск объявил бы себя ПОЛНЫМ там,
    где не видел ВООБЩЕ НИЧЕГО.

    По корпусу это не край, а правило: 316 связей из 386 числа не имеют.
    """
    d = _l0(tmp_path, [_link("ar", None), _link("kr", None)])
    axis = S.build_from_decompile(d).coverage_axes(
        geometry_scope="mvp")["federation"]
    assert axis["linked_elements_unscored"] == 0
    assert axis["links_in_l0"] == 2
    assert axis["complete"] is False, (
        "поиск объявлен полным на здании, все связи которого выгружены — "
        "сумма элементов равна нулю ПОТОМУ ЧТО не прочитана ни одна")


def test_the_axis_stays_green_on_a_document_with_no_links(tmp_path):
    """Обратная сторона: без связей ось обязана быть зелёной, иначе она просто
    красит всё в красный и перестаёт что-либо значить.

    ЧЕГО ЭТИ ТРИ ТЕСТА НЕ ПОКРЫВАЮТ: они ничего не говорят о том, ПРАВИЛЬНО ли
    считать неполную федерацию поводом для ОТКАЗА. Связи есть у 54 разборов из
    67, поэтому отказ на построении снапшота отключил бы клеш на восьми
    зданиях из десяти, и направление выбрано «громко и точно», а не
    «запретительно». Это РЕШЕНИЕ, а не свойство кода, и следующий читатель
    вправе его пересмотреть, если число изменится.
    """
    axis = S.build_from_decompile(_l0(tmp_path, [])).coverage_axes(
        geometry_scope="mvp")["federation"]
    assert axis["complete"] is True
    assert axis["linked_elements_unscored"] == 0
    assert axis["links_without_element_count"] == 0
    assert axis["links_in_l0"] == 0
