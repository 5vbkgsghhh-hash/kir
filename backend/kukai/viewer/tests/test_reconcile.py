"""СВЕРКА ПЛАНА И ОБЪЁМА: две переписи одного здания.

ЗАМЕР 11.08.2026, ради которого модуль написан и ради которого переписи
РЕШЕНО НЕ СВОДИТЬ:

| разбор              | оба    | только план | только объём | ни один |
|---------------------|-------:|------------:|-------------:|--------:|
| `sob62_fas_r23_v19` |  3 948 |         337 |          270 |     663 |
| `snowdon_plumb_v4`  | 26 203 |          55 |        5 701 |     226 |

Разобрано поимённо, и все три класса расхождений оказались ЗАКОННЫМИ:

  * датумы, аннотации, помещения, пространства — план рисует, тела нет;
  * вертикальные участки — 5 506 труб и 195 воздуховодов (21 % здания):
    объём рисует капсулой, план честно объявляет `degenerate`, потому что
    стояк проецируется в точку;
  * стены с осью, но без габарита — 291 из 2 360 (12.3 %): у всех 291 нет
    `bbox_*` в L0 и у всех 291 есть ось в `curve.index.json`. План проводит
    линию с меткой `thickness_unknown`; оболочка обязана СОДЕРЖАТЬ тело, а
    ось без толщины его не содержит.

Общий знаменатель заставил бы одну из переписей отвечать на чужой вопрос.
Поэтому здесь не третья перепись, а раскладка по четырём корзинам, где
причину даёт та перепись, которая её назвала.
"""

import unittest

from kukai.viewer import reconcile as R


class TheBucketsAreClosedAndBalance(unittest.TestCase):

    def test_every_bucket_has_a_russian_sentence(self):
        """Корзина без объяснения — число, которое нечем прочитать."""
        for name in (R.Bucket.BOTH, R.Bucket.PLAN_ONLY, R.Bucket.SCENE_ONLY,
                     R.Bucket.NEITHER):
            self.assertTrue(R.BUCKET_RU.get(name, "").strip(), name)

    def test_the_law_is_checked_not_promised(self):
        """`объединение = оба + только_план + только_объём + ни_один`.
        Элемент, не попавший ни в одну корзину, — ровно тот случай, ради
        которого сверка написана."""
        result = R.Reconciliation(union=10, buckets={"both": 4, "plan_only": 3,
                                                     "scene_only": 2,
                                                     "neither": 1})
        self.assertTrue(result.balanced())
        result.buckets["neither"] = 0
        self.assertFalse(result.balanced())

    def test_an_unbalanced_reconciliation_says_so_in_its_payload(self):
        payload = R.Reconciliation(union=5, buckets={"both": 1}).to_dict()
        self.assertFalse(payload["balanced"])


class ItRefusesToInventPerElementReasons(unittest.TestCase):
    """`PreviewCensus` группирует опущенное по (причина, категория) и хранит
    до пяти примеров. Поимённой причины плана у элемента поэтому НЕТ, и
    приписать её по категории было бы догадкой, надетой на элемент, — а
    догадка на элементе читается как измерение."""

    def test_the_limitation_is_stated_in_the_payload(self):
        payload = R.Reconciliation(
            note="причины для `scene_only` даны РАСПРЕДЕЛЕНИЕМ").to_dict()
        self.assertIn("РАСПРЕДЕЛЕНИЕМ", payload["note"])

    def test_the_module_says_why_it_does_not_merge_the_censuses(self):
        payload = R.Reconciliation().to_dict()
        self.assertIn("НЕ СВОДЯТСЯ", payload["verdict_ru"])
        self.assertIn("знаменатель", payload["verdict_ru"])


class ItIsNotAThirdCensus(unittest.TestCase):
    """Своего счёта здесь нет: обе переписи публикуются целиком и рядом,
    чтобы их можно было прочитать порознь, а не только в сумме."""

    def test_both_parent_censuses_ride_along(self):
        payload = R.Reconciliation(
            plan_census={"considered": 1}, scene_census={"eligible": 1}
        ).to_dict()
        self.assertIn("plan_census", payload)
        self.assertIn("scene_census", payload)

    def test_it_does_not_reimplement_either_census(self):
        import inspect
        source = inspect.getsource(R.reconcile_run)
        # Считают родители; здесь только раскладка.
        self.assertIn("preview_snapshot", source)
        self.assertIn("build_from_decompile", source)
        self.assertIn("building.census.to_dict()", source)
        self.assertIn("snap.census.as_dict()", source)


class TheSceneAdmitsItDidNotAsk(unittest.TestCase):
    """Молчание сцены о расхождении читается как «расхождений нет». Замер
    говорит обратное: на фасаде 663 элемента не показывает НИ ОДИН экран."""

    def test_a_scene_publishes_that_reconciliation_was_not_requested(self):
        import inspect
        from kukai.viewer import scene as S
        source = inspect.getsource(S.scene_from_decompile)
        self.assertIn('"reconcile"', source)
        self.assertIn("available", source)


class TheCostIsWhyItIsASeparateEntry(unittest.TestCase):
    """Сверка строит ОБЕ переписи целиком: 0.99 с фасад, 4.9 с инженерия.
    Возить это в кадре значило бы вернуть сцене стоимость, которую с неё
    только что сняли дельтами."""

    def test_it_is_not_called_from_the_scene_path(self):
        import inspect
        from kukai.viewer import live_scene as L
        from kukai.viewer import scene as S
        for module in (S, L):
            self.assertNotIn("reconcile_run", inspect.getsource(module))


# ═══════════════════════════════════════════════════════════════════════════
# ЖИВАЯ СВЕРКА
# ═══════════════════════════════════════════════════════════════════════════

class TheLiveDivergenceIsOfADifferentNature(unittest.TestCase):
    """Разбор смотрят при открытии архива; живую сцену — три часа.

    ЗАМЕР 11.08.2026, 300 программ / 6 000 элементов:

        снимок ЕСТЬ:  оба 4 200, только план 1 800
        снимок НЕТ:   только план 6 000, оба 0     <- план ПОЛОН, объём ПУСТ

    Вторая строка — тот самый исход: обе стороны честны поодиночке, план
    показывает всё здание, объём не показывает ничего, и никто не говорит,
    что это одно здание.
    """

    SNAPSHOT = {"levels": [{"id": 1, "name": "L1", "elevation_mm": 0.0}],
                "pipe_types": [{"id": 30, "name": "Сталь",
                                "section": {"kind": "nominal_table",
                                            "source": "PipeSegment.GetSizes",
                                            "sizes": [[100.0, 114.3]]}}]}

    def _session(self, with_snapshot):
        from kukai.live import journal as _journal
        from kukai.live import showroom as _showroom
        from kukai.viewer import live_scene as L
        key = _journal.key_for("тест-сверка", "тест-док")
        _journal.reset(key)
        _showroom.forget(key)
        R.live_reset(key)
        if with_snapshot:
            _journal.remember_sections(key, self.SNAPSHOT)
        _journal.append(key, {"ops": [{"op": "create_level", "id": "lv",
                                       "name": "L1", "elev_mm": 0.0}]})
        _journal.append(key, {"ops": [
            {"op": "create_pipe", "id": "p0",
             "p0_mm": [0.0, 0.0, 2800.0], "p1_mm": [12000.0, 0.0, 2800.0],
             "diameter_mm": 100.0,
             "pipe_type": {"by": "name", "value": "Сталь"},
             "level": {"by": "name", "value": "L1"}}]})
        return L.scene_from_session("тест-сверка", "тест-док", 0)[1]

    def test_without_a_snapshot_the_plan_is_full_and_the_volume_is_empty(self):
        buckets = self._session(False)["reconcile"]["buckets"]
        self.assertEqual(buckets.get("both", 0), 0)
        self.assertGreater(buckets.get("plan_only", 0), 0)

    def test_with_a_snapshot_the_same_element_appears_in_both(self):
        buckets = self._session(True)["reconcile"]["buckets"]
        self.assertGreater(buckets.get("both", 0), 0)

    def test_the_plan_only_sentence_sends_the_operator_not_the_author(self):
        """Без снимка чинит ОПЕРАТОР — открыв модель, — а не автор программы.
        Отправить автора править операнды значило бы послать не туда."""
        self.assertIn("ОПЕРАТОР", R.LIVE_BUCKET_RU[R.Bucket.PLAN_ONLY])

    def test_the_live_sentences_differ_from_the_decompile_ones(self):
        """Четвёртая корзина в живой сессии значит другое: «оп написан, а
        элемента нет ни на одном экране»."""
        self.assertNotEqual(R.LIVE_BUCKET_RU[R.Bucket.NEITHER],
                            R.BUCKET_RU[R.Bucket.NEITHER])


class TheDenominatorIsEveryWrittenOperation(unittest.TestCase):
    """Иначе четвёртая корзина пуста ПО ПОСТРОЕНИЮ: элемент, которого не создал
    никто, в объединение «нарисованных и оболоченных» не попадёт.

    Замер на пятиоперационной программе: `neither` — 4 из 5
    (`create_level`, `create_grid`, `create_room`, `set_param`)."""

    def test_an_op_that_makes_no_element_lands_in_neither(self):
        key = ("живая", "знаменатель")
        R.live_reset(key)
        out = R.live_frame(
            key, ops_by_id={"p1/sp": "set_param", "p1/w0": "create_wall"},
            drawn={"p1/w0"}, datums=set(), bodied=set(),
            refused={"p1/w0": "нет габарита"},
            no_body_ops={"set_param": 1}, whole=True)
        self.assertEqual(out["buckets"], {"neither": 1, "plan_only": 1})
        self.assertTrue(out["balanced"])

    def test_datums_count_as_drawn_by_the_plan(self):
        """`preview` держит их отдельным списком. Не заглянуть туда значило бы
        объявить ось невидимой ровно там, где план её показывает."""
        key = ("живая", "датумы")
        R.live_reset(key)
        out = R.live_frame(key, ops_by_id={"p1/g0": "create_grid"},
                           drawn=set(), datums={"p1/g0"}, bodied=set(),
                           refused={}, no_body_ops={"create_grid": 1},
                           whole=True)
        self.assertEqual(out["buckets"], {"plan_only": 1})

    def test_the_reason_for_a_bodiless_op_is_keyed_by_op_name(self):
        """`no_body` кейован ИМЕНЕМ операции, и «оп тела не создаёт» —
        свойство операции, а не её экземпляра. Поэтому это не догадка."""
        key = ("живая", "причина")
        R.live_reset(key)
        out = R.live_frame(key, ops_by_id={"p1/sp": "set_param"},
                           drawn=set(), datums=set(), bodied=set(),
                           refused={}, no_body_ops={"set_param": 1},
                           whole=True)
        self.assertIn("set_param",
                      " ".join(out["by_reason"]["neither"].keys()))

    def test_plan_reasons_are_never_attributed_per_element(self):
        """У элемента, которого не нарисовал план, поимённой причины НЕТ."""
        payload = R.live_frame(("живая", "план"), ops_by_id={},
                               drawn=set(), datums=set(), bodied=set(),
                               refused={}, no_body_ops={}, whole=True)
        self.assertIn("до пяти примеров", payload["plan_reason_ru"])


class AccumulationIsIdempotent(unittest.TestCase):
    """ОПРОВЕРГАЮЩИЙ ТЕСТ ДЕФЕКТА, НАЙДЕННОГО СВОИМ ЖЕ ЗАМЕРОМ.

    Замер цены кадра гонял одну и ту же дельту семь раз (брал минимум по
    времени), и накопление сложило её семь раз: 6 148 операций там, где их
    6 021. Панель повторяет запрос при ретрае, при потере ответа и при двух
    вкладках на одну сессию.

    Раздутая перепись СХОДИТСЯ САМА С СОБОЙ — корзины и знаменатель растут
    вместе, — поэтому закон сходимости её не ловит.
    """

    def _twice(self):
        key = ("живая", "повтор")
        R.live_reset(key)
        args = dict(ops_by_id={"p1/w0": "create_wall"}, drawn={"p1/w0"},
                    datums=set(), bodied=set(), refused={}, no_body_ops={})
        R.live_frame(key, whole=True, **args)
        return R.live_frame(key, whole=False, **args)

    def test_the_same_frame_twice_counts_once(self):
        out = self._twice()
        self.assertEqual(out["ops"], 1)
        self.assertEqual(sum(out["buckets"].values()), 1)

    def test_the_repeat_is_counted_and_named(self):
        """Молча пропустить повтор значило бы спрятать факт, что панель
        переспрашивает одно и то же."""
        out = self._twice()
        self.assertEqual(out["repeats"], 1)
        self.assertTrue(out["repeats_ru"])

    def test_a_whole_scene_resets_the_accumulation(self):
        key = ("живая", "обнуление")
        R.live_reset(key)
        args = dict(ops_by_id={"p1/w0": "create_wall"}, drawn={"p1/w0"},
                    datums=set(), bodied=set(), refused={}, no_body_ops={})
        R.live_frame(key, whole=True, **args)
        out = R.live_frame(key, whole=True, **args)
        self.assertEqual(out["ops"], 1)
        self.assertEqual(out["repeats"], 0)


class TheLiveCostStaysOffTheFrame(unittest.TestCase):
    """Замер 11.08: целое 800 мс со сверкой против 787-791 без; ДЕЛЬТА 2.0 мс
    со сверкой против 1.9-2.0 без. Живая сверка едет в кадре именно потому,
    что обе переписи там уже построены; у разбора она стоила их суммы
    (0.99 с и 4.9 с) и потому живёт отдельным входом."""

    def test_the_live_path_does_not_rebuild_either_census(self):
        import inspect
        source = inspect.getsource(R.live_frame)
        self.assertNotIn("preview_snapshot", source)
        self.assertNotIn("build_from_decompile", source)
        self.assertNotIn("build_program_preview", source)

    def test_context_datums_are_excluded_from_the_denominator(self):
        """Датумы едут с КАЖДОЙ дельтой и каждый раз получают новый адрес.
        Найдено своим замером: `neither` рос на единицу с каждой дельтой, а за
        трёхчасовую сессию набрал бы сотни призраков."""
        import inspect
        from kukai.viewer import live_scene as L
        source = inspect.getsource(L.scene_from_programs)
        self.assertIn("context_ids", source)
        self.assertIn("oid not in context_ids", source)
