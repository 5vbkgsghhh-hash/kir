"""ЧИТАЮЩАЯ СТОРОНА ОБЯЗАНА ОТЧИТАТЬСЯ ПЕРЕД ПИШУЩЕЙ, А НЕ НАОБОРОТ.

ПОВОД — ЗАМЕР 12.08.2026, И ОН ОПРОВЕРГ СВОЮ СОБСТВЕННУЮ ПОСТАНОВКУ. Задача
пришла как «судья приёмки не знает категорий семи опов КР». Спросили самого
судью (`derive_expectation` на программах, уже принятых воротами 6/6) — и семь
распались на ДВЕ разные причины, из которых заявленной была только одна:

  * ТРИ нагрузки (точечная, линейная, площадная) — судья знает категорию
    ТОЧНО: одна строка, `exact`, верхние и нижние границы целы. Третья опора
    кардинального инварианта у них НЕ потеряна;
  * ЧЕТЫРЕ (ферма, балочная система, армирование площади, ленточный
    фундамент) — слепота НАЗВАНА в `acceptance._OPS_BLIND`, с причиной,
    вердиктом и датой, и она поднимает `upper_bounds_valid=False`. Это
    объявленная потеря, а не молчание.

Неназванных пишущих опов ноль — это держит `test_registry_category_accounting`.
А раздела не получают 22 опа из 65, и вот ЭТО настоящий пробел: он не у судьи,
а у ЧИТАЮЩЕЙ стороны. Пишущие опы порождают 61 категорию переписи; носители
словаря разделов (`KINDS[*].collector_cs`, `extract._CATEGORY_SPECS`) называют
42. Девятнадцать оставшихся и есть всё расхождение.

ЭТО ТОТ ЖЕ КЛАСС, ЧТО И `query_types.pool`, В ДРУГОЙ ВАЛЮТЕ: там KIR пишет в
шесть пулов, которых не читает, здесь — в 19 категорий, которых не называет ни
один читающий носитель. Оба списка вели порознь, и ничто не заставляло их
сойтись. Правило одно на оба: **множество, которое обязана покрыть читающая
сторона, ВЫВОДИТСЯ из пишущей, а всякий непокрытый член — ИМЕНОВАННЫЙ отказ с
причиной и сроком. Пустого третьего варианта нет.**

ЧЕГО ЭТОТ ТЕСТ НЕ ТРЕБУЕТ. Он не требует ПОКРЫТИЯ — дописать строку в таблицу
извлечения без экстрактора значит утверждать чтение, которого нет, то есть
завести ровно тот дефект, ради запрета которого журнал и существует. Он
требует РЕШЁННОСТИ: покрыто либо названо.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_parity_queue.jsonl"))

from kukai.ir import acceptance, spec  # noqa: E402


def _categories_the_compiler_can_write() -> set[str]:
    """Спрашиваем РЕЕСТР, а не список. Новый оп попадает сюда сам."""
    found: set[str] = set()
    for op in spec.OPS.values():
        if op.family in spec.WRITE_FAMILIES:
            found.update(spec.op_census_categories(op))
    return found


class ReadSideAnswersToWriteSide(unittest.TestCase):

    def test_the_registry_is_reachable_before_any_zero_below(self):
        """Всякий ноль ниже был бы ложью, если реестр пуст или сузился.

        Прямое следствие правила «любой ноль из корпуса нуждается в
        доказательстве достижимости»: здесь корпус — сам реестр.
        """
        writing = {n for n, o in spec.OPS.items()
                   if o.family in spec.WRITE_FAMILIES}
        self.assertGreater(len(writing), 50, "реестр пишущих опов подозрительно мал")
        self.assertTrue(_categories_the_compiler_can_write(),
                        "ни одной категории у пишущих опов — прибор сломан, "
                        "а не расхождение закрыто")
        self.assertTrue(spec._category_disciplines(),
                        "носители словаря разделов не отдали ни одной строки")

    def test_every_written_category_is_either_read_or_named(self):
        """Третьего варианта — молчания — нет.

        Категория, в которую компилятор умеет писать и о которой не говорит ни
        один читающий носитель И ни одна строка журнала, невидима: оп с нею не
        получает раздела, и снаружи это неотличимо от «раздел ему не нужен».
        """
        covered = set(spec._category_disciplines())
        named = set(spec.CATEGORIES_WITHOUT_DISCIPLINE)
        silent = _categories_the_compiler_can_write() - covered - named
        self.assertEqual(
            silent, set(),
            "категории, в которые компилятор ПИШЕТ, но о которых читающая "
            "сторона молчит: " + ", ".join(sorted(silent)) + ". Либо строка "
            "у носителя (только вместе с настоящим экстрактором), либо "
            "запись в spec.CATEGORIES_WITHOUT_DISCIPLINE с причиной и сроком")

    def test_the_ledger_does_not_rot(self):
        """Запись про категорию, которую носители УЖЕ называют, — враньё.

        Журнал пробелов, из которого не убирают закрытые строки, через месяц
        описывает не дерево, а прошлое; и хуже того, он делает вид, что работа
        не сделана, — то есть её сделают второй раз.
        """
        covered = set(spec._category_disciplines())
        stale = covered & set(spec.CATEGORIES_WITHOUT_DISCIPLINE)
        self.assertEqual(
            stale, set(),
            "строки журнала про уже покрытые категории: " +
            ", ".join(sorted(stale)) + " — удалить")

    def test_the_ledger_speaks_only_about_categories_that_exist(self):
        """Строка про категорию, которую НИ ОДИН оп не пишет, — тоже пробел
        учёта: она вечно зелёная и вечно бесполезная."""
        writable = _categories_the_compiler_can_write()
        orphan = set(spec.CATEGORIES_WITHOUT_DISCIPLINE) - writable
        self.assertEqual(
            orphan, set(),
            "журнал говорит о категориях, которых не пишет ни один оп: " +
            ", ".join(sorted(orphan)))


def _pools_the_compiler_grounds_against() -> set[str]:
    """Пулы заземления — у РЕЕСТРА (`OpSpec.grounded`), а не из списка.

    Шаблонное имя (`column_symbols_{category}`) разворачивается по ЗАКРЫТОМУ
    перечислению того самого параметра, который его подставляет: подставить
    вместо этого догадку значило бы мерить свой шаблонизатор, а не реестр.
    """
    found: set[str] = set()
    for op in spec.OPS.values():
        choices = {p.name: p.choices for p in op.params if p.choices}
        for _param, pool, _required in op.grounded:
            if "{" not in pool:
                found.add(pool)
                continue
            key = pool[pool.index("{") + 1:pool.index("}")]
            for value in choices.get(key, ()):
                found.add(pool.replace("{" + key + "}", str(value)))
    return found


class EveryGroundedPoolCanBeAsked(unittest.TestCase):
    """ВТОРАЯ ВАЛЮТА ТОГО ЖЕ КЛАССА: пулы вместо категорий.

    Замер 12.08.2026: компилятор заземляется в 35 пулов, а `query_types.pool`
    читал 27 — ВОСЕМЬ пулов, в которые KIR умеет писать, спросить было нельзя.
    Прежняя запись называла ШЕСТЬ: она выводилась из нужд тридцати
    НЕПРОВЕРЕННЫХ опов, а `create_ceiling` и `create_railing` давно проверены и
    в тот срез не попали. Ответ по части множества снова оказался меньше ответа
    по всему множеству.

    И цена решения, из-за которой оно откладывалось, оказалась НУЛЕВОЙ: все
    восемь снимок уже собирает (`open_model.__profile_required_pools`), идиома
    коллектора у каждого уже написана там же, а описание инструмента не
    выросло ни на символ — 27 185 до и после, потому что перечисление пулов в
    описание не печатается вовсе.
    """

    def test_the_registry_is_reachable_before_any_zero_below(self):
        self.assertGreater(len(_pools_the_compiler_grounds_against()), 20)
        self.assertTrue(_readable_pools())

    def test_every_pool_the_compiler_writes_into_can_be_asked(self):
        """Пул, в который оп заземляется и которого нельзя перечислить, —
        `KIR-G102` ходом позже, и автор об этом не узнает заранее."""
        unaskable = _pools_the_compiler_grounds_against() - _readable_pools()
        self.assertEqual(
            unaskable, set(),
            "компилятор пишет в пулы, которых модель не может спросить: " +
            ", ".join(sorted(unaskable)) + ". Либо строка в "
            "`query_types.pool` вместе с коллектором в "
            "`compiler._TYPE_POOL_COLLECTOR_CS`, либо ИМЕНОВАННЫЙ отказ")

    def test_an_answer_that_gets_cut_must_say_so(self):
        """ТРЕТЬЯ ВАЛЮТА ТОГО ЖЕ КЛАССА, И САМАЯ ДОРОГАЯ ИЗ ТРЁХ.

        Печать контракта резалась по длине и теряла допуски — починено 12.08.
        Канал ОТВЕТА `query_types` — второй такой же канал, и режь его кто-то
        по длине, модель получила бы список типов, ЧИТАЕМЫЙ КАК ПОЛНЫЙ, и
        выбрала бы из усечённого множества. Там резалась проза, здесь резалось
        бы МНОЖЕСТВО, из которого делается выбор.

        Сегодня резака нет: эмиссия отдаёт все строки и везёт `total`. Тест
        держит именно это — не «ответ маленький» (это свойство здания), а «в
        ответе нет молчаливого отсечения» (свойство кода). Появится потолок —
        он обязан приехать вместе с флагом усечения, ровно как у пулов снимка
        (`open_model.CatalogPool`: неполный пул ОБЯЗАН объявить `truncated`).

        Размеры замерены на 69 профилях корпуса: `ceiling_types` максимум 8,
        `railing_types` максимум 22, усечений ноль, крупнейший пул вообще —
        `family_symbols` 741 и он читаем давно.
        """
        from kukai.ir import compiler
        for pool in sorted(_readable_pools()):
            with self.subTest(pool=pool):
                emitted = compiler.emit(
                    [{"op": "query_types", "id": "Q1", "pool": pool}],
                    revit_version="2026")
                self.assertIn('__r["total"] = __rows.Count', emitted,
                              "ответ не называет своего размера")
                for cut in (".Take(", ".Skip(", "__limit", "maxRows"):
                    self.assertNotIn(
                        cut, emitted,
                        f"в ответе появилось отсечение ({cut}) без флага "
                        f"усечения: усечённый список неотличим от полного, а "
                        f"выбор делается ИЗ НЕГО")

    def test_every_askable_pool_has_a_collector(self):
        """Имя в перечислении без коллектора — обещание, которое отказывает
        на эмиссии; это хуже отсутствия имени, потому что видно только в
        программе."""
        from kukai.ir import compiler
        promised = _readable_pools() - set(compiler._TYPE_POOL_COLLECTOR_CS)
        self.assertEqual(
            promised, set(),
            "перечисление обещает пулы без идиомы сбора: " +
            ", ".join(sorted(promised)))


def _readable_pools() -> set[str]:
    return set(next(p.choices for p in spec.OPS["query_types"].params
                    if p.name == "pool"))


class TheJudgeIsNotTheGapForLoads(unittest.TestCase):
    """ПРИБИТО НАМЕРЕННО: постановка задачи утверждала обратное.

    Без этого теста «судья не знает нагрузок» вернётся — оно звучит правдоподобно
    (раздела у нагрузок правда нет) и опровергается только замером самого судьи.
    """

    #: Программы, уже принятые воротами 6/6 (`tools/live_programme_d.py`).
    LOADS = {
        "create_point_load": {
            "op": "create_point_load", "id": "P13",
            "xyz": [0.0, 0.0, 0.0], "fz_n": -1000.0,
            "load_case": {"by": "name", "value": "ЛС1"}},
        "create_line_load": {
            "op": "create_line_load", "id": "P14",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [4000.0, 0.0, 0.0],
            "fz_n_per_m": -500.0, "load_case": {"by": "name", "value": "ЛС1"}},
        "create_area_load": {
            "op": "create_area_load", "id": "P15",
            "outline": [[0.0, 0.0], [4000.0, 0.0], [4000.0, 4000.0],
                        [0.0, 4000.0]],
            "elev_mm": 0.0, "fz_n_per_m2": -250.0,
            "load_case": {"by": "name", "value": "ЛС1"}},
    }

    EXPECTED = {"create_point_load": "OST_PointLoads",
                "create_line_load": "OST_LineLoads",
                "create_area_load": "OST_AreaLoads"}

    def test_control_a_known_op_yields_a_checkable_row(self):
        """КОНТРОЛЬ, ОБЯЗАННЫЙ ПРОЙТИ. Без него зелень ниже не значит ничего:
        программа, не прошедшая план, даёт ПУСТОЕ ожидание, и «нет строки»
        читалось бы как «судья слеп»."""
        e = acceptance.derive_expectation([{
            "op": "create_wall", "id": "W",
            "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0], "height_mm": 3000.0,
            "type": {"by": "name", "value": "т"},
            "level": {"by": "name", "value": "У1"}}])
        self.assertEqual(e.notes, (), "контрольная программа не прошла план")
        self.assertTrue(e.rows)
        self.assertTrue(e.checkable)

    def test_control_a_program_that_fails_the_plan_says_so(self):
        """КОНТРОЛЬ, ОБЯЗАННЫЙ УПАСТЬ. Пустое ожидание без записки было бы
        молчанием — тем самым, которое этот файл и ловит."""
        e = acceptance.derive_expectation([{"op": "create_wall", "id": "W"}])
        self.assertEqual(e.rows, ())
        self.assertTrue(e.notes, "план отвергнут молча — записки нет")

    def test_the_judge_knows_each_load_exactly(self):
        for name, program in self.LOADS.items():
            with self.subTest(op=name):
                e = acceptance.derive_expectation([program])
                self.assertEqual(e.notes, (), f"{name}: программа не прошла план")
                self.assertEqual(len(e.rows), 1, f"{name}: не одна строка")
                row = e.rows[0]
                self.assertEqual(row.categories, (self.EXPECTED[name],))
                self.assertEqual(row.count, 1)
                self.assertEqual(row.certainty, acceptance.Certainty.EXACT)
                self.assertTrue(e.upper_bounds_valid, f"{name}: верхние границы сняты")
                self.assertTrue(e.lower_bounds_valid, f"{name}: нижние границы сняты")
                self.assertEqual(e.blind_ops, (), f"{name}: судья объявил слепоту")

    def test_the_loads_lack_a_discipline_and_that_is_the_whole_gap(self):
        """Вторая половина того же факта: категория известна, раздел — нет.

        Держится вместе с первой намеренно. Порознь каждая половина
        подталкивает к неверному выводу: «раздела нет» -> «судья слеп»
        (неправда), «судья знает» -> «пробела нет» (тоже неправда).
        """
        for name, category in self.EXPECTED.items():
            with self.subTest(op=name):
                disciplines, why = spec.op_disciplines(spec.OPS[name])
                self.assertEqual(disciplines, ())
                self.assertIn(category, why)
                self.assertIn(category, spec.CATEGORIES_WITHOUT_DISCIPLINE)


if __name__ == "__main__":
    unittest.main()
