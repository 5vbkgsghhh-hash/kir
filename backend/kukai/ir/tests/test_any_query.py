"""Any-Query acceptance test (SPEC §14.2, operator directive 2026-07-16).

The product invariant: for ANY request the system returns exactly one of
(a) a structurally-correct answer, (b) a typed refusal WITH a tail route.
Out-of-coverage kinds (MEP internals, worksharing, exotics — the §10
anti-scope) must produce 100% typed handoffs, zero exceptions, zero silent
degradations, and each must land in the rejection telemetry
(contract /root/kukai-cube/KIR_QUEUE_CONTRACT.md — schema v1, RAW kinds).
"""
import json
import os
import tempfile
import unittest

# A process-unique directory keeps the suite hermetic across users, parallel
# workers and stale files from a killed prior run.  A fixed /tmp filename made
# the test fail before exercising KIR whenever another user owned that file.
_TEST_DIR = tempfile.TemporaryDirectory(prefix="kir-anyquery-test-")
_QUEUE = os.path.join(_TEST_DIR.name, "rejections.jsonl")
os.environ["KIR_REJECTIONS_PATH"] = _QUEUE

from kukai.ir.compiler import compile_program  # noqa: E402

# Виды, ВЫШЕДШИЕ из анти-скоупа 27.07. Работа ведётся по разделам, у каждого
# свой исполнитель, поэтому реестр видов дорос с 21 до 51 — КР/ОВ/ВК/ЭОМ в нём
# были представлены одной строкой на раздел. Перенос сюда законен ровно при
# одном условии: на вид теперь можно ответить ЧЕСТНО, то есть у него есть
# коллектор, дающий верный счёт. Ниже — те, у кого он появился; проверяются
# положительно (`test_newly_covered_kinds_answer_instead_of_handing_off`),
# чтобы список не превратился в способ тихо выносить виды из-под инварианта.
NEWLY_COVERED_KINDS = [
    "conduit", "sprinkler", "curtain_panel", "area", "space",
    "railing", "ramp", "furniture",
    # group_by-волна (28.07): вышедшие из анти-скоупа в 0a16e8f5 («разделы в
    # таблицах», 21->51 вид), но не занесённые тогда в этот список — сама
    # регистрация в KINDS не проверялась тестом. Подтверждено историей:
    # `git show 440a8afe:.../registry_base.py` их не знает,
    # `git show 0a16e8f5:.../registry_base.py` — знает (0 -> 1 KindSpec
    # каждый). Живые отказы с этими же словами лежат в
    # data/telemetry/kir_rejections.jsonl (UNSUPPORTED_KIND до 27.07 19:03).
    "structural_framing",    # «Каркас несущий»
    "mechanical_equipment",  # «Мех. оборудование»
    "plumbing_fixture",      # «Сантехника»
    "specialty_equipment",   # «Спец. оборудование» / «Специальное оборудование»
    "generic_model",         # «Обобщённые модели»
]

OUT_OF_COVERAGE_KINDS = [
    # anti-scope / not-yet-covered, every one must hand off — never guess:
    "mep_system", "fitting",
    "workset", "revision", "schedule", "schedule_field", "topography",
    "toposolid", "mass", "mullion", "rebar",
    "point_cloud", "rvt_link", "keynote", "filled_region",
    "zone", "parking",
    "design_option", "phase", "material_asset", "other",
    # 9-й вид из живого разбора 27.07 («Опоры», data/telemetry/kir_rejections
    # .jsonl, query_id 30614d9c185ec17c) ОСТАВЛЕН здесь намеренно, не
    # угадан: живых кандидатов несколько (OST_RailingSupport по совпадению
    # в той же пачке с «Перила», OST_BridgeBearings, структурные анкеры
    # соединений) и ни один не подтверждён живой проверкой — этой волной
    # Revit трогать нельзя (см. коммит), а молчащий неверный счёт хуже
    # типизированного отказа. Следующий живой заход должен спросить
    # оператора/контекст запроса, а не подставить наугад.
    "Опоры",
    # nonsense / adversarial (must stay RAW in telemetry — they ARE the signal):
    "unicorn", "стена", "wall​", "OST_ImportInstances",
]

#: 🔴 ПЕРЕЕХАЛИ ИЗ СОСТЯЗАТЕЛЬНЫХ 15.08.2026, И ЭТО НЕ ОСЛАБЛЕНИЕ ИНВАРИАНТА.
#:
#: `"Wall "` и `"WALL"` стояли выше как доказательство «компилятор не
#: угадывает». Слиянием приехала ЛЕСТНИЦА РАЗРЕШЕНИЯ ИМЕНИ ВИДА
#: (`compiler._check_kind`, `_canon_kind`, `_kind_canon_index`), и она приняла
#: осознанное решение: одно совпадение в ЗАКРЫТОМ множестве — это то же имя,
#: набранное иначе, а не выбор из двух. На столкновении она ОТКАЗЫВАЕТ (индекс
#: держит список, а не первое имя), и отказ называет соседа.
#:
#: Поэтому эти два больше не «вне охвата»: они В охвате, просто написаны
#: иначе. Инвариант анти-скоупа не тронут — состязательные, которые обязаны
#: отказывать, остались наверху, и среди них `"wall​"` с нулевой шириной:
#: `\s` его не снимает, лестница его не сводит, отказ на месте.
#:
#: 🔴 НАЗВАННЫЙ ДОЛГ, КОТОРЫЙ ЭТОТ ТЕСТ НЕ ЗАКРЫВАЕТ. Лестница срабатывает
#: МОЛЧА: `_check_kind` возвращает исправленное имя и ничего не кладёт в
#: квитанцию. По закону этого дерева «выбор, которого вызывающий не видит, —
#: это `.FirstOrDefault()` с хорошей репутацией» (тот же довод, по которому
#: `ground` обязан печатать `grounding_report`). Здесь пишется, что исправление
#: ПРОИСХОДИТ; что оно ВИДНО автору — не проверяется, потому что канала пока
#: нет. Закрывается вместе с каналом, а не отдельным тестом.
RESOLVED_BY_THE_NAME_LADDER = ["Wall ", "WALL"]


class AnyQueryInvariant(unittest.TestCase):
    # ОКРУЖЕНИЕ ПИННИТСЯ ПОТЕСТОВО, А НЕ ОДИН РАЗ НА ИМПОРТЕ (12.08.2026).
    #
    # Тесты ниже читают и пишут ИМЕННО `_QUEUE` (строки 72/118/126), но ключ
    # выставлялся только на строке 20, при импорте модуля.  `test_shadow.py:17`
    # присваивает тот же ключ НАПРЯМУЮ (остальные ~80 модулей делают
    # `setdefault`, который на занятом ключе не делает ничего), а pytest
    # импортирует ВСЕ модули на сборе, до первого теста.  Значит побеждает тот,
    # кого импортировали последним, и это зависит от порядка аргументов:
    #
    #   pytest test_any_query.py test_shadow.py   -> победил shadow, модуль слеп
    #   pytest test_shadow.py test_any_query.py   -> победил свой, всё зелено
    #
    # Отсюда «в одиночку проходит, в наборе ошибается»: величина утверждалась
    # на импорте и читалась в тестах, и сойтись их не заставляло ничто.
    # Лечится не восстановлением константы, а тем, что каждый тест сам
    # устанавливает нужное ему состояние и возвращает НАБЛЮДЁННОЕ.
    def setUp(self):
        self._previous_queue = os.environ.get("KIR_REJECTIONS_PATH")
        os.environ["KIR_REJECTIONS_PATH"] = _QUEUE

    def tearDown(self):
        if self._previous_queue is None:
            os.environ.pop("KIR_REJECTIONS_PATH", None)
        else:
            os.environ["KIR_REJECTIONS_PATH"] = self._previous_queue

    def test_out_of_coverage_is_typed_handoff(self):
        if os.path.exists(_QUEUE):
            os.remove(_QUEUE)
        for kind in OUT_OF_COVERAGE_KINDS:
            with self.subTest(kind=kind):
                out = compile_program({
                    "ir_version": "1.0",
                    "intent": f"count {kind} in model",
                    "ops": [{"op": "query_count", "kind": kind}],
                }, query_id=f"anyq-{kind!r}")
                self.assertFalse(out.ok, f"{kind!r} must not silently compile")
                self.assertIsNone(out.csharp)
                codes = [d.code for d in out.diagnostics]
                self.assertNotIn("KIR-P000", codes, "panic is forbidden")
                self.assertIn("KIR-G001", codes, f"{kind!r}: want typed unsupported-kind")
                self.assertIsNotNone(out.handoff, f"{kind!r}: refusal must carry a route")
                self.assertEqual(out.handoff["route"], "recipe-path")

    def test_a_spelling_variant_resolves_and_does_not_hand_off(self):
        """Написание того же вида РАЗРЕШАЕТСЯ, а не уезжает в рецепт.

        Контроль с обеих сторон, иначе утверждение вырождено: вариант написания
        обязан СОБРАТЬСЯ, а состязательный мусор из `OUT_OF_COVERAGE_KINDS` —
        нет. Оба конца в одном тесте, чтобы «зелено, потому что принимаем всё»
        не выглядело как «зелено, потому что различаем»."""
        for kind in RESOLVED_BY_THE_NAME_LADDER:
            with self.subTest(kind=kind):
                out = compile_program({
                    "ir_version": "1.0",
                    "intent": f"count {kind} in model",
                    "ops": [{"op": "query_count", "kind": kind}],
                }, query_id=f"ladder-{kind!r}")
                self.assertTrue(
                    out.ok,
                    f"{kind!r}: одно совпадение в закрытом множестве — то же "
                    f"имя; диагностики: {[d.code for d in out.diagnostics]}")
                self.assertNotIn("KIR-G001", [d.code for d in out.diagnostics])

        # ОБРАТНЫЙ КОНЕЦ: лестница не всеядна. Ноль совпадений — отказ.
        out = compile_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "kind": "unicorn"}],
        }, query_id="ladder-negative")
        self.assertFalse(out.ok, "лестница приняла бессмыслицу — она всеядна")
        self.assertIn("KIR-G001", [d.code for d in out.diagnostics])

    def test_newly_covered_kinds_answer_instead_of_handing_off(self):
        """Вышедший из анти-скоупа вид обязан ОТВЕЧАТЬ, а не молчать.

        Перенос вида из `OUT_OF_COVERAGE_KINDS` в `NEWLY_COVERED_KINDS` иначе
        был бы способом убрать его из-под инварианта, ничего не сделав: тест
        на отказ перестал бы его видеть, а тест на ответ не появился бы.
        Здесь второй конец: каждый перенесённый вид компилируется в C# и
        собирает СВОЮ категорию — не «что-нибудь».
        """
        from kukai.ir import spec
        for kind in NEWLY_COVERED_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(kind, spec.KINDS, f"{kind!r} нет в реестре видов")
                out = compile_program({
                    "ir_version": "1.0",
                    "intent": f"count {kind} in model",
                    "ops": [{"op": "query_count", "kind": kind}],
                }, query_id=f"covered-{kind!r}")
                self.assertTrue(
                    out.ok, f"{kind!r}: {[d.code for d in out.diagnostics]}")
                self.assertIsNotNone(out.csharp)
                collector = spec.KINDS[kind].collector_cs
                self.assertIn(collector, out.csharp,
                              f"{kind!r}: собран не свой коллектор")
                self.assertTrue(
                    spec.KINDS[kind].discipline,
                    f"{kind!r}: вид без раздела")

    def test_telemetry_contract_v1(self):
        if os.path.exists(_QUEUE):
            os.remove(_QUEUE)
        compile_program({"ir_version": "1.0", "intent": "x",
                         "ops": [{"op": "query_count", "kind": "OST_ImportInstances"}]},
                        query_id="join-key-1")
        compile_program({"ir_version": "1.0",
                         "ops": [{"op": "query_inspect", "target": {"by": "vibe", "value": 1}}]},
                        query_id="join-key-2")
        with open(_QUEUE, encoding="utf-8") as f:
            recs = [json.loads(line) for line in f]
        self.assertEqual(len(recs), 2)
        r0, r1 = recs
        self.assertEqual(r0["v"], 1)
        self.assertEqual(r0["source"], "kir")
        self.assertEqual(r0["reject_code"], "UNSUPPORTED_KIND")
        self.assertEqual(r0["kind_requested"], "OST_ImportInstances")   # RAW, unnormalized
        self.assertEqual(r0["op_requested"], "count")
        self.assertEqual(r0["query_id"], "join-key-1")
        self.assertIn("×", r0["cell"])
        self.assertEqual(r1["reject_code"], "SLOT_RESOLUTION_FAILED")
        self.assertEqual(r1["query_id"], "join-key-2")

    def test_queue_failure_is_fail_open(self):
        # ВОССТАНАВЛИВАЕМ НАБЛЮДЁННОЕ, А НЕ ЗАПОМНЕННОЕ (12.08.2026).
        # Здесь стояло `= _QUEUE` — константа этого модуля, выставленная им на
        # строке 20 при импорте.  Но `test_shadow.py:17` тоже присваивает этот
        # ключ НАПРЯМУЮ (не `setdefault`, как остальные ~80 модулей), а pytest
        # импортирует всё на сборе, до первого теста, — так что к моменту
        # запуска здесь лежит ЧУЖОЙ путь.  `finally` возвращал свой, страж
        # окружения ловил подмену в teardown, и в наборе это читалось как
        # `ERROR` именно у этого теста, хотя в одиночку файл зелёный.
        # Величина УТВЕРЖДАЛАСЬ на строке 20 и ЧИТАЛАСЬ здесь; сойтись их не
        # заставляло ничто.  Минимальное воспроизведение — два файла:
        #   pytest kukai/ir/tests/test_any_query.py kukai/ir/tests/test_shadow.py
        previous = os.environ.get("KIR_REJECTIONS_PATH")
        os.environ["KIR_REJECTIONS_PATH"] = "/proc/definitely/not/writable/q.jsonl"
        try:
            out = compile_program({"ir_version": "1.0",
                                   "ops": [{"op": "query_count", "kind": "unicorn"}]})
            self.assertFalse(out.ok)           # refusal still typed
            self.assertIsNotNone(out.handoff)  # route still present
        finally:
            if previous is None:
                os.environ.pop("KIR_REJECTIONS_PATH", None)
            else:
                os.environ["KIR_REJECTIONS_PATH"] = previous


if __name__ == "__main__":
    unittest.main()
