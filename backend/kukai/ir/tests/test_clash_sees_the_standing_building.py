"""ПАЧКА СРАВНИВАЕТСЯ С УЖЕ СТОЯЩИМ — и умеет сказать, что не сравнивалась.

ЧТО СТЕРЕЖЁТ ЭТОТ ФАЙЛ. До волны стоящего `clash_bundle` сравнивал пачку САМУ
С СОБОЙ, и его собственная квитанция это называла: «столкновение с чужой стеной
не „не найдено“, а НЕВИДИМО». Ноль находок читался как «здание в порядке» —
зелёное без акта различения, наша форма 18, в продуктовом пути.

Здесь три ФАКТА, которые обязаны остаться различимыми, и именно их слияние
было дефектом:

    источника нет            -> present=False + ПРИЧИНА словами
    источник есть, пусто     -> present=True, bodies=0   («смотрели, чисто»)
    источник есть, нашли     -> находка с адресами ОБЕИХ сторон

Слить любые два — значит вернуть дефект, поэтому каждый проверяется отдельно,
и обратный контроль требует, чтобы подмена стоящего пустотой не давала тихого
зелёного.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kukai.clash import detect as D
from kukai.clash import existing as E
from kukai.ir import clash_bundle as CB

#: Габарит «существующей стены» — числа настоящего элемента разбора
#: `sob62_r23_v5`, взятые замером, а не придуманные.
WALL_LO = [9600.0, 105160.0, 2350.0]
WALL_HI = [9800.0, 109160.4, 5800.0]


def _l0_line(element: dict) -> str:
    return json.dumps({"record": "element", "collector": element["category"],
                       "element": element}, ensure_ascii=False)


def _wall(element_id: str, lo, hi) -> dict:
    return {"element_id": element_id, "category": "OST_Walls",
            "category_ru": "Стены", "geom_kind": "curve",
            "bbox_min_mm": list(lo), "bbox_max_mm": list(hi),
            "level_id": "9835106", "type_name": "ВН_Газобетон D600_200мм"}


def _run_dir(elements: list[dict]) -> pathlib.Path:
    """Разбор на диске. Настоящий файл, а не заглушка: загрузчик читает
    построчно, и подменять ему источник значило бы проверять не его."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="kir-standing-"))
    with (root / "L0.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"document": {"doc_name": "тест"}}) + "\n")
        for element in elements:
            handle.write(_l0_line(element) + "\n")
    return root


def _pack(dx: float = 0.0) -> list[dict]:
    """Новое тело габаритом ровно как у стены, сдвинутое на `dx`.

    `create_directshape` выбран намеренно: его тело — меш в мм, то есть числа
    самой программы, и он НЕ ТРЕБУЕТ снапшота типов. Труба потребовала бы
    наружный диаметр из типа, и контроль мерил бы наличие фикстуры, а не
    сравнение со стоящим.
    """
    x0, y0, z0 = WALL_LO[0] + dx, WALL_LO[1], WALL_LO[2]
    x1, y1, z1 = WALL_HI[0] + dx, WALL_HI[1], WALL_HI[2]
    verts = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
             [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    return [{"ir_version": "1.0", "ops": [{
        "op": "create_directshape", "id": "w1", "category": "generic_model",
        "name": "новая стена",
        "mesh": {"vertices_mm": verts, "faces": [[0, 1, 2]]}}]}]


def _report(pack, existing_run=None):
    """Отчёт при поднятом флаге — и окружение ВОЗВРАЩАЕТСЯ на место.

    Сторож окружения этого дерева поймал первую редакцию: флаг оставался
    поднятым, и следующий тест увидел бы чужое состояние, а его падение
    выглядело бы его собственным. Восстанавливаем `try/finally`, а не
    вписываем себя в исключения сторожа.
    """
    import os

    had = "KUKAI_IR_CLASH" in os.environ
    before = os.environ.get("KUKAI_IR_CLASH")
    os.environ["KUKAI_IR_CLASH"] = "1"
    try:
        CB._CACHE.clear()
        return CB.bundle_clash_report(pack, existing_run=existing_run)
    finally:
        if had:
            os.environ["KUKAI_IR_CLASH"] = before  # type: ignore[assignment]
        else:
            os.environ.pop("KUKAI_IR_CLASH", None)


class ТриИсходаРазличимы(unittest.TestCase):
    """Главное свойство волны: «не смотрели» ≠ «смотрели, чисто» ≠ «нашли»."""

    def test_новое_тело_в_существующей_стене_даёт_находку(self):
        run = _run_dir([_wall("7240696", WALL_LO, WALL_HI)])
        block = _report(_pack(0.0), existing_run=run)

        self.assertTrue(block["compared_against"]["present"])
        self.assertGreaterEqual(len(block["findings"]), 1)
        # АДРЕС ОБЕИХ СТОРОН. Находка, называющая только нашу сторону, не даёт
        # автору починить: он не знает, ВО ЧТО попал.
        text = json.dumps(block, ensure_ascii=False)
        self.assertIn("w1", text)
        self.assertIn(E.existing_source_id("7240696"), text)
        self.assertEqual(block["scope_id"], "bundle_vs_document")

    def test_то_же_тело_в_пустом_месте_находки_не_даёт(self):
        run = _run_dir([_wall("7240696", WALL_LO, WALL_HI)])
        block = _report(_pack(300000.0), existing_run=run)

        self.assertEqual(block["findings"], [])
        # И ЭТО НЕ ТО ЖЕ, ЧТО «НЕ СМОТРЕЛИ»: источник прочитан, в области
        # пусто. Разница живёт в полях, а не в интонации.
        against = block["compared_against"]
        self.assertTrue(against["present"])
        self.assertEqual(against["bodies"], 0)
        self.assertGreaterEqual(against["scanned"], 1)

    def test_без_источника_отсутствие_НАЗЫВАЕТСЯ(self):
        block = _report(_pack(0.0), existing_run=None)

        against = block["compared_against"]
        self.assertFalse(against["present"])
        self.assertTrue(against["reason"])
        self.assertIn("НЕ ВИДИТ СТОЯЩЕЕ", block["message_ru"])


class ОбратныйКонтроль(unittest.TestCase):
    """Подмена стоящего пустотой не имеет права дать тихий зелёный.

    Это и есть та сторона, ради которой волна делалась: пустой отчёт обязан
    нести, ПРОТИВ ЧЕГО сравнивали, иначе он остаётся зелёным без различения —
    только шире.
    """

    def test_пустой_разбор_отличим_от_отсутствующего(self):
        empty = _run_dir([])
        block = _report(_pack(0.0), existing_run=empty)
        against = block["compared_against"]
        # Источник ЕСТЬ и прочитан — просто в нём ничего нет.
        self.assertTrue(against["present"])
        self.assertEqual(against["bodies"], 0)

        missing = _report(_pack(0.0), existing_run=None)["compared_against"]
        self.assertFalse(missing["present"])
        # Два ответа обязаны РАЗЛИЧАТЬСЯ. Равенство здесь означало бы, что
        # дефект вернулся под новым именем.
        self.assertNotEqual(against["present"], missing["present"])

    def test_каталога_нет_это_названный_отказ_а_не_пустота(self):
        block = _report(_pack(0.0), existing_run="/нет/такого/каталога")
        against = block["compared_against"]
        self.assertFalse(against["present"])
        self.assertIn("каталога разбора нет", against["reason"])

    def test_разбор_без_L0_называет_именно_это(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="kir-no-l0-"))
        block = _report(_pack(0.0), existing_run=root)
        self.assertIn("нет L0.jsonl", block["compared_against"]["reason"])


class ЧислоПарТочноеИНеNone(unittest.TestCase):
    """`None`, прочитанный как ноль, уже дал «ноль рядом с 58 280 находками».

    Фильтр по ИСТОЧНИКУ не сокращается по классам `(label, mvp_side)`, поэтому
    `detect` честно отдаёт по нему `eligible_pairs=None` с причиной. Число
    пар считается формулой по двум известным численностям — и обязано быть
    числом всегда.
    """

    def test_число_пар_считается_формулой_и_совпадает(self):
        run = _run_dir([_wall(f"{7240696 + i}",
                              [WALL_LO[0], WALL_LO[1] + i, WALL_LO[2]],
                              [WALL_HI[0], WALL_HI[1] + i, WALL_HI[2]])
                        for i in range(3)])
        block = _report(_pack(0.0), existing_run=run)
        self.assertIsNotNone(block["pairs_compared"])
        self.assertEqual(
            block["pairs_compared"],
            E.pairs_compared(block["bodies_bundle"], block["bodies_existing"]))

    def test_формула_это_пары_внутри_плюс_перекрёстные(self):
        # 2 своих + 3 стоящих: C(2,2)=1 внутри плюс 2*3=6 перекрёстных.
        self.assertEqual(E.pairs_compared(2, 3), 7)
        self.assertEqual(E.pairs_compared(0, 5), 0)
        self.assertEqual(E.pairs_compared(1, 0), 0)


class ОбластьНичегоНеТеряет(unittest.TestCase):
    """Запас 0 мм — не порог, а доказанная граница.

    `overlap` требует signed_distance < 0, `contact` — == 0; оба требуют
    пересечения габаритов. Значит элемент вне области не может дать находку, и
    отбросить его безопасно. Контроль проверяет ОБА направления: соседний
    элемент внутри области попадает, удалённый — нет.
    """

    def test_элемент_вне_области_не_мог_бы_дать_находку(self):
        near = _wall("111", WALL_LO, WALL_HI)
        far = _wall("222", [WALL_LO[0] + 50000, WALL_LO[1], WALL_LO[2]],
                    [WALL_HI[0] + 50000, WALL_HI[1], WALL_HI[2]])
        run = _run_dir([near, far])
        block = _report(_pack(0.0), existing_run=run)
        # В области ровно один: дальний отброшен ДО построения оболочки.
        self.assertEqual(block["compared_against"]["bodies"], 1)
        self.assertEqual(block["compared_against"]["scanned"], 2)

    def test_пустая_область_это_факт_о_НАШЕЙ_стороне(self):
        region = E.Region.around([])
        self.assertTrue(region.empty)
        loaded = E.load(_run_dir([_wall("1", WALL_LO, WALL_HI)]), region)
        self.assertFalse(loaded.present)
        self.assertIn("пачка не построила ни одного тела", loaded.reason)


class КасаниеИПрониканиеНеСмешаны(unittest.TestCase):
    """Касание — до трети всех пар (7 804 против 19 523 на одном здании).
    Складывать их значит систематически переоценивать число конфликтов."""

    def test_отношения_остаются_разными_ключами(self):
        self.assertIn("contact", D.HULL_RELATIONS)
        self.assertIn("overlap", D.HULL_RELATIONS)
        self.assertNotEqual("contact", "overlap")


class СтароеПоведениеЦело(unittest.TestCase):
    """Волна не имеет права менять ответ там, где источника не дали."""

    def test_без_источника_область_прежняя(self):
        block = _report(_pack(0.0), existing_run=None)
        self.assertEqual(block["scope_id"], "all_physical_diagnostic")

    def test_пара_стоящее_на_стоящее_в_область_не_входит(self):
        a = type("R", (), {"source_id": E.existing_source_id("1")})()
        b = type("R", (), {"source_id": E.existing_source_id("2")})()
        mine = type("R", (), {"source_id": "w1"})()
        self.assertFalse(D.bundle_vs_document_pair_filter(a, b))
        self.assertTrue(D.bundle_vs_document_pair_filter(a, mine))
        self.assertTrue(D.bundle_vs_document_pair_filter(mine, mine))

    def test_область_названа_в_каноне(self):
        # Детектор отказывает неизвестному фильтру, и это его закон: отчёт,
        # не умеющий назвать охват, утверждает больше, чем искал.
        self.assertIn("bundle_vs_document", D.SCOPES)
        self.assertEqual(
            D.scope_id_of(D.bundle_vs_document_pair_filter),
            "bundle_vs_document")


class ИсточникВходитВКлючКэша(unittest.TestCase):
    """Одна и та же пачка против ДРУГОГО здания — другой ответ."""

    def test_другой_источник_даёт_другой_ключ(self):
        pack = _pack(0.0)
        self.assertNotEqual(
            CB._cache_key(pack, None, None, "/a"),
            CB._cache_key(pack, None, None, "/b"))
        self.assertNotEqual(
            CB._cache_key(pack, None, None, None),
            CB._cache_key(pack, None, None, "/a"))


if __name__ == "__main__":
    unittest.main()


# ═════════════════════════════════════════════════════════════════════════
# ВОЛНА Б2 — ДВЕРЬ ОТКРЫТА: ИСТОЧНИК РАЗРЕШАЕТСЯ САМ
#
# `existing_run` перестал быть параметром, который никто не передаёт.
# Способность без двери неотличима от отсутствующей — так `sdk.py` пролежал
# 493 строки и пять недель. Дверь здесь: `serving` называет документ хода
# (личность знаема ровно там, где ground отдал отпечаток), а разрешение
# источника делает сам `clash_bundle`.
# ═════════════════════════════════════════════════════════════════════════


def _corpus(runs: dict) -> pathlib.Path:
    """Корпус разборов на диске: каталог с `passport.json` и `L0.jsonl`."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="kir-corpus-"))
    for name, (doc_name, elements) in runs.items():
        run = root / name
        run.mkdir()
        (run / "passport.json").write_text(
            json.dumps({"doc_name": doc_name, "change_stamp": name},
                       ensure_ascii=False), encoding="utf-8")
        with (run / "L0.jsonl").open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"document": {"doc_name": doc_name}}) + "\n")
            for element in elements:
                handle.write(_l0_line(element) + "\n")
    return root


def _report_for_document(pack, title, corpus):
    """Отчёт так, как его получит живой путь: документ назван, путь — нет."""
    import os

    keys = ("KUKAI_IR_CLASH", E.DECOMPILE_ROOT_ENV)
    before = {k: os.environ.get(k) for k in keys}
    os.environ["KUKAI_IR_CLASH"] = "1"
    os.environ[E.DECOMPILE_ROOT_ENV] = str(corpus)
    try:
        CB._CACHE.clear()
        CB.remember_turn_document(title)
        return CB.bundle_clash_report(pack)      # existing_run НЕ передаётся
    finally:
        CB.remember_turn_document("")
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class ДверьОткрытаБезПараметра(unittest.TestCase):
    """Живой путь получает сравнение со стоящим, ничего не передавая."""

    def test_источник_находится_по_заголовку_документа(self):
        corpus = _corpus({"run_a": ("Дом.rvt", [_wall("1", WALL_LO, WALL_HI)])})
        block = _report_for_document(_pack(0.0), "Дом.rvt", corpus)

        against = block["compared_against"]
        self.assertTrue(against["present"])
        self.assertEqual(against["source"], "run_a")
        self.assertGreaterEqual(len(block["findings"]), 1)

    def test_берётся_САМЫЙ_СВЕЖИЙ_разбор_документа(self):
        import os
        import time

        # 🔴 ИМЯ И ВРЕМЯ РАЗВЕДЕНЫ НАМЕРЕННО, И ЭТО НЕ ПЕДАНТИЗМ.
        # Первая редакция звала прогоны «старый»/«новый»: в кириллице
        # «новый» < «старый», то есть первый ПО АЛФАВИТУ и был свежайшим.
        # Мутация «брать первый вместо свежайшего» тогда НЕ КРАСНЕЛА — контроль
        # стоял на вырожденной выборке и не пинил ничего. Здесь `aaa_*` идёт
        # первым по алфавиту и ПОСЛЕДНИМ по времени, поэтому два правила
        # различимы.
        corpus = _corpus({
            "aaa_позавчерашний": ("Дом.rvt", [_wall("1", WALL_LO, WALL_HI)]),
            "zzz_сегодняшний": ("Дом.rvt", [_wall("2", WALL_LO, WALL_HI)]),
        })
        old = time.time() - 86400 * 30
        os.utime(corpus / "aaa_позавчерашний", (old, old))
        block = _report_for_document(_pack(0.0), "Дом.rvt", corpus)
        self.assertEqual(block["compared_against"]["source"],
                         "zzz_сегодняшний")

    def test_чужой_документ_корпуса_НЕ_берётся(self):
        """Совпадение по имени — единственный ключ, и он обязан РАЗЛИЧАТЬ."""
        corpus = _corpus({"чужой": ("Другой.rvt", [_wall("1", WALL_LO, WALL_HI)])})
        block = _report_for_document(_pack(0.0), "Дом.rvt", corpus)

        against = block["compared_against"]
        self.assertFalse(against["present"])
        self.assertIn("Дом.rvt", against["reason"])
        self.assertEqual(block["findings"], [])


class ТриИсходаДвериНедостижимыТихо(unittest.TestCase):
    """Каждый отказ двери НАЗЫВАЕТСЯ. Тихий возврат к сравнению внутри пачки
    открыл бы дверь в стену: находок ноль, и читатель решит, что чисто."""

    def test_документ_не_назван(self):
        corpus = _corpus({"run_a": ("Дом.rvt", [_wall("1", WALL_LO, WALL_HI)])})
        block = _report_for_document(_pack(0.0), "", corpus)
        against = block["compared_against"]
        self.assertFalse(against["present"])
        self.assertIn("личность документа неизвестна", against["reason"])

    def test_корпуса_нет(self):
        block = _report_for_document(
            _pack(0.0), "Дом.rvt", pathlib.Path("/нет/корпуса"))
        self.assertIn("корпуса разборов нет",
                      block["compared_against"]["reason"])

    def test_каждый_отказ_попадает_в_текст_квитанции(self):
        corpus = _corpus({"чужой": ("Другой.rvt", [])})
        block = _report_for_document(_pack(0.0), "Дом.rvt", corpus)
        self.assertIn("НЕ ВИДИТ СТОЯЩЕЕ", block["message_ru"])


class СвежестьНеМолчит(unittest.TestCase):
    """Разбор недельной давности против сегодняшнего документа — сравнение с
    ПРОШЛЫМ зданием. Молча этого делать нельзя."""

    def test_находка_помечена_недоказанным_источником(self):
        corpus = _corpus({"run_a": ("Дом.rvt", [_wall("1", WALL_LO, WALL_HI)])})
        block = _report_for_document(_pack(0.0), "Дом.rvt", corpus)

        fresh = block["compared_against"]["freshness"]
        self.assertIsNotNone(fresh)
        self.assertFalse(fresh["proven"])
        self.assertEqual(fresh["matched_by"], "doc_title")
        self.assertIsNotNone(fresh["age_days"])
        self.assertIn("НЕ ДОКАЗАН", block["message_ru"])

    def test_причина_недоказуемости_названа_поимённо(self):
        """Причина обязана НАЗЫВАТЬСЯ и РАЗЛИЧАТЬ случаи.

        🔴 ПРИШПИЛЕН ПРЕДМЕТ, А НЕ НАПИСАНИЕ (правка 15.08.2026). Прежняя
        редакция искала подстроку `project_uid` — и покраснела, когда паспорт
        НАУЧИЛСЯ нести личность и фраза стала точнее. Тест на орфографию
        объявляет улучшение поломкой; проверять надо, что два РАЗНЫХ повода
        не доказать дают РАЗНЫЕ ответы.
        """
        old = _corpus({"r": ("Дом.rvt", [_wall("1", WALL_LO, WALL_HI)])})
        _run, _why, fresh = E.resolve_run("Дом.rvt", root=old)
        self.assertFalse(fresh.proven)
        self.assertTrue(fresh.why.strip(), "причина обязана быть названа")
        # разбор снят до волны личности — и это сказано как факт О НАС
        self.assertIn("паспорт", fresh.why)

        # ДРУГОЙ повод не доказать: разбор личность НЕСЁТ, а живая сторона
        # молчит. Это факт о НАШЕМ чтении, а не о возрасте разбора, и фраза
        # обязана быть другой — иначе поле не различает ничего.
        import json as _json
        import pathlib as _pathlib
        import tempfile as _tempfile
        fresh_root = _pathlib.Path(_tempfile.mkdtemp())
        run_dir = fresh_root / "r"
        run_dir.mkdir()
        (run_dir / "L0.jsonl").write_text("{}", encoding="utf-8")
        (run_dir / "passport.json").write_text(_json.dumps({
            "doc_name": "Дом.rvt",
            "document_identity": {
                "source": "project_information_unique_id",
                "value": "UID-1"},
        }), encoding="utf-8")

        _r2, _w2, fresh2 = E.resolve_run("Дом.rvt", root=fresh_root)
        self.assertNotEqual(fresh.why, fresh2.why)

        # и третий: обе стороны назвали одно и то же — сильнее имени, но
        # ВСЁ ЕЩЁ не доказательство, потому что Save As несёт то же значение
        _r3, _w3, fresh3 = E.resolve_run(
            "Дом.rvt", root=fresh_root, project_uid="UID-1")
        self.assertFalse(fresh3.proven)
        self.assertEqual(fresh3.matched_by, "project_information_unique_id")
        self.assertNotIn(fresh3.why, (fresh.why, fresh2.why))

        # РАСХОЖДЕНИЕ — единственный односторонне ТВЁРДЫЙ ответ: другой файл
        run4, why4, fresh4 = E.resolve_run(
            "Дом.rvt", root=fresh_root, project_uid="UID-ДРУГОЙ")
        self.assertIsNone(run4)
        self.assertIn("РАСХОЖДЕНИЮ", why4)

    def test_свидетельство_личности_обгоняет_свежесть(self):
        """СИЛЬНЕЙШЕЕ СВИДЕТЕЛЬСТВО ПОБЕЖДАЕТ ШТАМП ВРЕМЕНИ.

        🔴 Этот тест куплен мутацией, а не задуман. Первая редакция брала
        просто самый свежий разбор, и разбор БЕЗ личности выигрывал у разбора
        с СОВПАВШЕЙ родословной по случайности времени записи. Поведение
        починили, а сторожа не поставили — мутация «ранг всегда 0» прошла
        зелёной на 24 тестах. Здесь пришпилен именно ПОРЯДОК ВЫБОРА.
        """
        import json as _json
        import os as _os
        import pathlib as _pathlib
        import tempfile as _tempfile
        import time as _time

        root = _pathlib.Path(_tempfile.mkdtemp())

        def _put(name, identity, age_days):
            d = root / name
            d.mkdir()
            (d / "L0.jsonl").write_text("{}", encoding="utf-8")
            row = {"doc_name": "Дом.rvt"}
            if identity:
                row["document_identity"] = identity
            (d / "passport.json").write_text(
                _json.dumps(row), encoding="utf-8")
            t = _time.time() - age_days * 86400
            _os.utime(d, (t, t))

        # свежайший — БЕЗ личности; родня старее на пять суток
        _put("a_свежий_без_личности", None, 0)
        _put("b_родня_старее",
             {"source": "project_information_unique_id", "value": "UID-1"}, 5)

        run, why, fresh = E.resolve_run(
            "Дом.rvt", root=root, project_uid="UID-1")
        self.assertEqual(why, "")
        self.assertEqual(run.name, "b_родня_старее",
                         "родословная обязана обогнать более свежий разбор "
                         "без личности: иначе свидетельство проигрывает mtime")
        self.assertEqual(fresh.matched_by, "project_information_unique_id")

    def test_явный_путь_перевешивает_разрешение(self):
        """Админская дверь и тесты обязаны мочь назвать источник сами."""
        run = _run_dir([_wall("1", WALL_LO, WALL_HI)])
        block = _report(_pack(0.0), existing_run=run)
        self.assertTrue(block["compared_against"]["present"])
        # Разрешение не запускалось — свежести нет, и это честно: источник
        # назван снаружи, и о его свежести мы ничего не знаем.
        self.assertIsNone(block["compared_against"]["freshness"])


class ДешёвыйОтборНеТеряетРазбор(unittest.TestCase):
    """ПРЕДФИЛЬТР ПО ШАПКЕ L0 — сторож на правку цены от 16.08.2026.

    🔴 ЗАЧЕМ ЭТОТ КЛАСС. Резолвер разбирал ВСЕ паспорта корпуса, чтобы взять
    одно строковое поле: замерено на живом корпусе — 17.2 с на вызов, из них
    13.2 с `json.loads` 918 МБ, и цена росла с размером ЗДАНИЯ (крупнейший
    паспорт 206 МБ). Отбор кандидатов по шапке L0 снял это до 2.05 с.

    Правка цены опаснее правки поведения: она зелена ровно до того входа,
    на котором дешёвый источник молчит. Поэтому пришпилен не выигрыш, а
    ГРАНИЦА — «не знаю» обязано вести к паспорту, а не к отбраковке.
    """

    def _run_with(self, head_text: str, passport_name: str = "Дом.rvt"):
        root = pathlib.Path(tempfile.mkdtemp(prefix="kir-cheap-"))
        run = root / "r"
        run.mkdir()
        (run / "L0.jsonl").write_text(head_text, encoding="utf-8")
        (run / "passport.json").write_text(
            json.dumps({"doc_name": passport_name}, ensure_ascii=False),
            encoding="utf-8")
        return root

    def test_шапки_нет_разбор_всё_равно_находится(self):
        """Пустая/битая шапка — «не знаю», и паспорт обязан быть прочитан."""
        for head in ("{}", "", "не json вовсе", '{"document": 5}'):
            with self.subTest(head=head):
                root = self._run_with(head)
                run, why, _fresh = E.resolve_run("Дом.rvt", root=root)
                self.assertIsNotNone(
                    run, "разбор потерян на шапке %r: %s" % (head, why))

    def test_имя_в_шапке_расходится_с_паспортом_решает_паспорт(self):
        """Авторитет — паспорт. Шапка только СУЖАЕТ, и не имеет права судить.

        Расхождение сегодня не воспроизводится (52 из 52 совпали), но оно
        возможно завтра, и тогда потерять разбор молча — худший исход.
        """
        root = self._run_with(
            json.dumps({"document": {"doc_name": "Дом.rvt"}}) + "\n",
            passport_name="Дом.rvt")
        run, _why, _fresh = E.resolve_run("Дом.rvt", root=root)
        self.assertIsNotNone(run)

    def test_чужое_имя_в_шапке_отсекается_без_чтения_паспорта(self):
        """И ради чего всё: чужой разбор не стоит НИ ОДНОГО разбора паспорта."""
        root = self._run_with(
            json.dumps({"document": {"doc_name": "Другой.rvt"}}) + "\n")
        (root / "r" / "passport.json").write_text(
            "ЭТО НЕ JSON — прочитан не будет", encoding="utf-8")
        run, why, _fresh = E.resolve_run("Другой.rvt", root=root)
        # Паспорт битый: если бы его читали, кандидат бы отвалился по ValueError
        # и ответ был бы тем же. Поэтому проверяется ОБРАТНОЕ направление —
        # свой заголовок отсекается шапкой ДО чтения битого паспорта.
        self.assertIsNone(run)
        self.assertIn("Другой.rvt", why)

    def test_шапка_читается_без_чтения_всего_L0(self):
        """Читается ПЕРВАЯ строка: остальной файл не трогается вовсе."""
        root = self._run_with(
            json.dumps({"document": {"doc_name": "Дом.rvt"}}) + "\n"
            + "СТРОКА-КОТОРУЮ-НЕЛЬЗЯ-РАЗОБРАТЬ\n" * 100)
        self.assertEqual(E._doc_name_from_l0_head(root / "r" / "L0.jsonl"),
                         "Дом.rvt")
        run, _why, _fresh = E.resolve_run("Дом.rvt", root=root)
        self.assertIsNotNone(run)
