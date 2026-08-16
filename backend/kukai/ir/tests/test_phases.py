"""ФАЗЫ — план строительства внутри ОДНОГО авторского скрипта.

ЧТО ЭТОТ НАБОР ДЕРЖИТ, И ПОЧЕМУ ИМЕННО ЭТО.

1. ОТСУТСТВИЕ ОСТАЁТСЯ ОТСУТСТВИЕМ. Скрипт, не зовущий `phase()`, обязан
   давать ТУ ЖЕ программу и ТОТ ЖЕ дайджест, что до появления фаз. Проверяется
   не на глаз, а тремя способами сразу: тем же дайджестом, что у чистого языка
   (`kukai.ir.dsl` без курса), пришпиленным числом и отсутствием ключа.
2. ГРАНИЦА, КОТОРУЮ АВТОР НЕ РИСОВАЛ, НЕ ВЫДУМЫВАЕТСЯ. Каждое место, где
   разметка становится неоднозначной (оп вне фазы, вложенная фаза, второе имя,
   пустая фаза, фаза внутри `unit()`), — типизированный отказ, а не догадка в
   чью-то пользу.
3. ССЫЛКА ЧЕРЕЗ ГРАНИЦУ НАЗЫВАЕТСЯ, А НЕ МОЛЧИТ. Внутри фазы — `by=ref`, как
   было; через границу — метка `phase_result`, которую подставит исполнитель
   по свидетелю произведшей фазы; НАЗАД через границу — отказ.
4. ШОВ СО СЛЕДУЮЩИМ ШАГОМ ЗАКРЫТ FAIL-CLOSED. Пофазного исполнения ещё нет,
   поэтому и программа с фазами, и неподставленная метка обязаны получать
   типизированный отказ компилятора. Тихое исполнение фаз одной транзакцией —
   это отсутствие чекпойнта под видом его наличия, и такой тест дороже
   красивого.

ЦЕНА НАБОРА: ~20 прогонов песочницы по ~0.3 с. Дорого намеренно — дешёвая
проверка проверяла бы разметку, а не работу: имя, недостижимое из настоящей
политики, стоит модели раунда (закон достижимости, `test_course`).
"""
from __future__ import annotations

import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import compiler             # noqa: E402
from kukai.ir import course as C          # noqa: E402
from kukai.ir import dsl, sandbox, spec   # noqa: E402
from kukai.ir.compiler import (  # noqa: E402
    MAX_BULK_OPS, MAX_OPS_PER_PROGRAM, plan_program)
from kukai.ir.diag import KirRefusal      # noqa: E402
from kukai.ir.emit_utils import ELEMENT_ID_MAX  # noqa: E402

#: РОВНО тот состав имён, который получает модель в проде. Ни одного
#: послабления: фаза, работающая только из тестового процесса, — не фаза.
POLICY = sandbox.SandboxPolicy(dsl_module="kukai.ir.course.language")


def run(source: str, **kw) -> sandbox.SandboxResult:
    policy = sandbox.SandboxPolicy(dsl_module="kukai.ir.course.language", **kw)
    return sandbox.execute_author_script(source, policy=policy)


def refusal_of(result: sandbox.SandboxResult) -> str:
    assert not result.ok, "ожидался отказ, а скрипт собрался"
    return result.refusal.render()


class _InProcess(unittest.TestCase):
    """Разметка без песочницы: то же самое, но без 0.3 с на случай."""

    def setUp(self) -> None:
        dsl.reset()

    def tearDown(self) -> None:
        dsl.reset()

    def level(self, k: int = 0):
        return dsl.OP_FUNCTIONS["create_level"](elev_mm=k * 3000,
                                                name=f"Этаж {k + 1}")

    def wall(self, level, k: int = 0):
        return dsl.OP_FUNCTIONS["create_wall"](
            p0_mm=(0, k * 1000), p1_mm=(6000, k * 1000), level=level,
            height_mm=3000)


# ═════════════════════════════════════════════════════════════════════════
# 1. ФАЗЫ ПО ПОРЯДКУ
# ═════════════════════════════════════════════════════════════════════════

class PhasesComeOutInOrder(_InProcess):

    def test_the_table_names_every_op_exactly_once_in_written_order(self) -> None:
        """Разбиение, а не пометка: порядок фаз — порядок скрипта, и каждый оп
        лежит РОВНО в одной фазе."""
        with C.phase("уровни"):
            lvl = self.level()
        with C.phase("стены"):
            self.wall(lvl, 0)
            self.wall(lvl, 1)
        with C.phase("помещение"):
            dsl.OP_FUNCTIONS["create_room"](xy=(1500, 1500), level=lvl,
                                            name="Кабинет")
        out = C.take_ops()
        phases = out["phases"]
        self.assertEqual([p["index"] for p in phases], [0, 1, 2])
        self.assertEqual([p["name"] for p in phases],
                         ["уровни", "стены", "помещение"])
        flat = [oid for p in phases for oid in p["op_ids"]]
        self.assertEqual(flat, [op["id"] for op in out["ops"]])
        self.assertEqual(len(flat), len(set(flat)))

    def test_a_reference_inside_one_phase_is_still_by_ref(self) -> None:
        """Внутри фазы язык не меняется НИ НА БАЙТ: та же программа, что и без
        фаз, — иначе фаза была бы вторым диалектом ссылок."""
        with C.phase("этаж целиком"):
            lvl = self.level()
            self.wall(lvl)
        out = C.take_ops()
        self.assertEqual(out["ops"][1]["level"], {"by": "ref", "value": "level1"})

    def test_a_reference_across_the_boundary_is_marked_for_the_witness(self) -> None:
        """ТО, НА ЧЁМ СТОИТ ШАГ 2. Форма метки проверяется дословно: её читает
        подстановка, а не человек."""
        with C.phase("уровни"):
            lvl = self.level()
        with C.phase("стены"):
            self.wall(lvl)
        out = C.take_ops()
        self.assertEqual(
            out["ops"][1]["level"],
            {"by": C.CROSS_PHASE_BY, "value": "level1", "phase": 0})
        self.assertEqual(C.CROSS_PHASE_BY, "phase_result")

    def test_no_by_ref_survives_a_boundary(self) -> None:
        """Закон, который уже сказан в другом месте системы: кросс-программный
        `by=ref` отказан `design_check._merge_bundle` («соседняя программа —
        отдельная транзакция»). Фазы обязаны не создавать таких ссылок ВООБЩЕ,
        а не полагаться на то, что кто-то потом откажет."""
        with C.phase("уровни"):
            lvl = self.level()
        with C.phase("стены"):
            wall = self.wall(lvl)
        with C.phase("проёмы"):
            dsl.OP_FUNCTIONS["create_door"](host=wall, offset_mm=3000,
                                            symbol="Дверь 900x2100")
        out = C.take_ops()
        owner = {oid: p["index"] for p in out["phases"] for oid in p["op_ids"]}
        for op in out["ops"]:
            for sel in _selectors(op):
                if sel.get("by") == "ref":
                    self.assertEqual(owner[str(sel["value"])], owner[op["id"]],
                                     f"{op['id']}: by=ref пересёк границу фазы")
                if sel.get("by") == C.CROSS_PHASE_BY:
                    self.assertLess(sel["phase"], owner[op["id"]])

    def test_a_unit_inside_a_phase_is_one_op_of_that_phase(self) -> None:
        """Единица внутри фазы законна: группа — ОДИН оп, и он принадлежит
        фазе, в которой написан."""
        with C.phase("санузлы"):
            with C.unit("Кабинка", placements=[(1600, 0)]):
                dsl.OP_FUNCTIONS["create_wall"](
                    p0_mm=(0, 0), p1_mm=(1600, 0),
                    level={"by": "name", "value": "Этаж 1"}, height_mm=2500)
        out = C.take_ops()
        self.assertEqual([op["op"] for op in out["ops"]], ["create_group"])
        self.assertEqual(out["phases"],
                         [{"index": 0, "name": "санузлы",
                           "op_ids": ["group1"]}])

    def test_the_self_check_is_not_blinded_by_phase_boundaries(self) -> None:
        """ЗАМЕР 09.08, ПОЙМАННЫЙ ЭТИМ ТЕСТОМ И ПОЧИНЕННЫЙ. Первая версия
        разметки ослепляла план: метка `phase_result` не сводится к уровню, и
        на скрипте из двух фаз печаталось «рассмотрено 6, нарисовано 0 (0%)» —
        прибор, покрывающий часть диапазона, опаснее отсутствующего. План и
        вердикт судят ЗАМЫСЕЛ, поэтому видят программу такой, какой её написал
        автор (`_as_authored`)."""
        script = (
            'with phase("уровни"):\n'
            '    lvl = create_level(elev_mm=0, name="Этаж 1")\n'
            'with phase("стены"):\n'
            '    for a, b in [((0,0),(6000,0)), ((6000,0),(6000,4000)),\n'
            '                 ((6000,4000),(0,4000)), ((0,4000),(0,0))]:\n'
            '        create_wall(p0_mm=a, p1_mm=b, level=lvl, height_mm=3000)\n'
            '    create_room(xy=(3000, 2000), level=lvl, name="Кабинет")\n'
            'preview()\n')
        result = run(script)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertIn("нарисовано 5", result.stdout)
        self.assertNotIn("НЕ НАРИСОВАНО НИЧЕГО", result.stdout)
        # И при этом наружу уходит именно МЕТКА, а не восстановленный `ref`:
        # обратное превращение живёт только внутри двух печатающих функций.
        self.assertEqual(result.ops[1]["level"]["by"], C.CROSS_PHASE_BY)

    def test_the_phase_object_says_what_it_is(self) -> None:
        with C.phase("каркас") as ph:
            self.level()
            self.assertEqual((ph.name, ph.index), ("каркас", 0))
        self.assertIn("каркас", repr(ph))
        C.take_ops()


def _selectors(value):
    """Все словари-селекторы внутри операции, как угодно вложенные."""
    if isinstance(value, dict):
        if "by" in value:
            yield value
        for item in value.values():
            yield from _selectors(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _selectors(item)


# ═════════════════════════════════════════════════════════════════════════
# 2. ОТКАЗЫ — КАЖДЫЙ НАЗЫВАЕТ ФАЗУ И СЛЕДУЮЩИЙ ХОД
# ═════════════════════════════════════════════════════════════════════════

class EveryAmbiguityIsATypedRefusal(unittest.TestCase):

    def test_a_handle_used_before_its_producing_phase_names_both(self) -> None:
        """ЗАКОН ПОРЯДКА, ПОДНЯТЫЙ НА ФАЗЫ. Ручкой так промахнуться нельзя (она
        существует только после своего опа) — промахиваются явной формой
        `by_ref("level1")`, где id угадан по детерминированной схеме имён."""
        result = run(
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0),\n'
            '                level=by_ref("level1"), height_mm=3000)\n'
            'with phase("уровни"):\n'
            '    create_level(elev_mm=0, name="Этаж 1")\n')
        text = refusal_of(result)
        self.assertIn("KIR-L003", text)
        self.assertIn("level1", text)          # сама ручка
        self.assertIn("«стены»", text)         # кто пользуется
        self.assertIn("«уровни»", text)        # кто производит
        self.assertIn("строка", text)          # место в скрипте автора

    def test_a_phase_over_the_authored_budget_names_the_phase(self) -> None:
        result = run(
            'with phase("частокол"):\n'
            f'    for i in range({MAX_OPS_PER_PROGRAM + 1}):\n'
            '        create_wall(p0_mm=(i * 100, 0), p1_mm=(i * 100, 4000),\n'
            '                    level="Этаж 1", height_mm=3000)\n')
        text = refusal_of(result)
        self.assertIn("KIR-L001", text)
        self.assertIn("«частокол»", text)
        self.assertIn(str(MAX_OPS_PER_PROGRAM), text)
        self.assertIn(str(MAX_OPS_PER_PROGRAM + 1), text)

    def test_the_budget_measures_the_phase_not_the_script(self) -> None:
        """ГРАНИЦА ПРОВЕРЯЕТСЯ С ОБЕИХ СТОРОН. Ровно бюджет — законно, и ДВЕ
        такие фазы подряд тоже: до фаз столько опов уместилось бы только в две
        программы, то есть в два хода модели."""
        result = run(
            'for k in range(2):\n'
            '    with phase("ярус %d" % k):\n'
            f'        for i in range({MAX_OPS_PER_PROGRAM}):\n'
            '            create_wall(p0_mm=(i * 100, 0), p1_mm=(i * 100, 4000),\n'
            '                        level="Этаж 1", height_mm=3000)\n')
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(len(result.ops), 2 * MAX_OPS_PER_PROGRAM)
        self.assertEqual([len(p["op_ids"]) for p in result.envelope["phases"]],
                         [MAX_OPS_PER_PROGRAM, MAX_OPS_PER_PROGRAM])

    def test_a_solo_op_alone_in_its_phase_is_legal(self) -> None:
        """ТО, РАДИ ЧЕГО СОЛО-ПРАВИЛО СТАЛО ПРАВИЛОМ ФАЗЫ: здание с лестницей
        стало выразимо ОДНИМ скриптом. Соло-оп берётся из реестра, а не из
        имени: второй список соло-опов разошёлся бы с первым."""
        solo = sorted(spec.SOLO_OPS)[0]
        self.assertEqual(solo, "create_stairs")
        result = run(
            'with phase("тело"):\n'
            '    create_level(elev_mm=0, name="Этаж 1")\n'
            '    create_level(elev_mm=3000, name="Этаж 2")\n'
            'with phase("лестница"):\n'
            '    create_stairs(base_level="Этаж 1", top_level="Этаж 2",\n'
            '                  p0_mm=(0, 0), p1_mm=(3000, 0), width_mm=1200)\n')
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual([p["name"] for p in result.envelope["phases"]],
                         ["тело", "лестница"])
        self.assertEqual(result.envelope["phases"][1]["op_ids"], ["stairs1"])

    def test_a_solo_op_with_a_neighbour_in_its_phase_refuses(self) -> None:
        result = run(
            'with phase("этаж и лестница"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level="Этаж 1",\n'
            '                height_mm=3000)\n'
            '    create_stairs(base_level="Этаж 1", top_level="Этаж 2",\n'
            '                  p0_mm=(0, 0), p1_mm=(3000, 0), width_mm=1200)\n')
        text = refusal_of(result)
        self.assertIn("KIR-L002", text)
        self.assertIn("«этаж и лестница»", text)
        self.assertIn("create_stairs", text)

    def test_an_op_before_the_first_phase_refuses(self) -> None:
        """РЕШЕНИЕ, КОТОРОЕ ЗДЕСЬ ПРИНЯТО: смешение размеченного и
        неразмеченного — ОТКАЗ, а не молчаливая фаза 0."""
        text = refusal_of(run(
            'create_level(elev_mm=0, name="Этаж 1")\n'
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level="Этаж 1",\n'
            '                height_mm=3000)\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("ВНЕ фазы", text)
        self.assertIn("create_level", text)

    def test_an_op_between_two_phases_refuses(self) -> None:
        text = refusal_of(run(
            'with phase("уровни"):\n'
            '    create_level(elev_mm=0, name="Этаж 1")\n'
            'create_room(xy=(1500, 1500), level="Этаж 1", name="Между")\n'
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level="Этаж 1",\n'
            '                height_mm=3000)\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("create_room", text)
        self.assertIn("«уровни»", text)

    def test_an_op_after_the_last_phase_refuses(self) -> None:
        """ЕДИНСТВЕННАЯ ПРОВЕРКА БЕЗ НОМЕРА СТРОКИ, и это сказано честно: хвост
        становится хвостом только когда скрипт кончился. Взамен отказ называет
        сами опы и последнюю фазу."""
        text = refusal_of(run(
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level="Этаж 1",\n'
            '                height_mm=3000)\n'
            'create_room(xy=(1500, 1500), level="Этаж 1", name="После")\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("ПОСЛЕ последней фазы", text)
        self.assertIn("room1", text)

    def test_a_phase_inside_a_phase_refuses(self) -> None:
        text = refusal_of(run(
            'with phase("а"):\n'
            '    with phase("б"):\n'
            '        create_level(elev_mm=0, name="Этаж 1")\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("ПОСЛЕДОВАТЕЛЬНОСТЬ", text)

    def test_a_repeated_phase_name_refuses(self) -> None:
        """Ни второй фазы с тем же адресом, ни дописывания в закрытую: и то и
        другое сделало бы порядок исполнения не порядком скрипта."""
        text = refusal_of(run(
            'with phase("а"):\n'
            '    create_level(elev_mm=0, name="Этаж 1")\n'
            'with phase("а"):\n'
            '    create_level(elev_mm=3000, name="Этаж 2")\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("уже была", text)

    def test_a_phase_inside_a_unit_refuses(self) -> None:
        text = refusal_of(run(
            'with unit("Кабинка"):\n'
            '    with phase("а"):\n'
            '        create_wall(p0_mm=(0, 0), p1_mm=(1000, 0),\n'
            '                    level="Этаж 1", height_mm=3000)\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("unit()", text)

    def test_an_empty_phase_refuses(self) -> None:
        text = refusal_of(run(
            'with phase("пусто"):\n'
            '    pass\n'
            'create_level(elev_mm=0, name="Этаж 1")\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("«пусто»", text)

    def test_a_nameless_phase_refuses(self) -> None:
        text = refusal_of(run(
            'with phase(""):\n'
            '    create_level(elev_mm=0, name="Этаж 1")\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("ИМЯ", text)

    def test_a_refusal_never_escapes_as_a_traceback(self) -> None:
        """ЗАКОН ПЕСОЧНИЦЫ: сырой трейсбек не выходит наружу никогда. У всех
        отказов фазы одна дверь (KIR-B006), и вина — авторская."""
        for source in (
            'with phase("а"):\n    pass\ncreate_level(elev_mm=0, name="L")\n',
            'with phase("а"):\n    with phase("б"):\n'
            '        create_level(elev_mm=0, name="L")\n',
        ):
            with self.subTest(source=source.splitlines()[1].strip()):
                result = run(source)
                self.assertFalse(result.ok)
                self.assertEqual(result.refusal.code, "KIR-B006")
                self.assertEqual(result.refusal.blame, "author")
                self.assertNotIn("Traceback", result.refusal.message_ru)
                self.assertNotIn("kukai/ir", result.refusal.message_ru)


# ═════════════════════════════════════════════════════════════════════════
# 3. ОТСУТСТВИЕ ОСТАЁТСЯ ОТСУТСТВИЕМ
# ═════════════════════════════════════════════════════════════════════════

#: Скрипт БЕЗ единого `phase()`. Правится только вместе с пришпиленным
#: дайджестом ниже — в этом и смысл.
UNPHASED = ('envelope(intent="коробка")\n'
            'lvl = create_level(elev_mm=0, name="Этаж 1")\n'
            'create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level=lvl, height_mm=3000)\n'
            'create_wall(p0_mm=(6000, 0), p1_mm=(6000, 4000), level=lvl,'
            ' height_mm=3000)\n')

#: ЗАМЕР 09.08.2026: `program_digest` этого скрипта, снятый ОБОИМИ модулями
#: языка. Число пришпилено намеренно: расхождение здесь значит, что программа
#: скрипта БЕЗ фаз сдвинулась — то есть фазы взяли плату с тех, кто их не
#: звал. Это ровно тот дефект, ради которого таблица едет в конверте, а не в
#: каждом опе.
UNPHASED_DIGEST = ("c2106fc0e0ac07e505e9f8b7469ac498"
                   "f9d631e88e818a804cdf69fcd79bfe51")


class AbsentStaysAbsent(unittest.TestCase):

    def test_a_script_without_phases_is_byte_identical_to_the_bare_language(self) -> None:
        """Сильнейшая из трёх формулировок: программа со ВСЕМ курсом обязана
        совпасть с программой ЧИСТОГО языка, который о фазах не слышал."""
        bare = sandbox.execute_author_script(
            UNPHASED, policy=sandbox.SandboxPolicy(dsl_module="kukai.ir.dsl"))
        full = run(UNPHASED)
        self.assertTrue(bare.ok, bare.refusal and bare.refusal.render())
        self.assertTrue(full.ok, full.refusal and full.refusal.render())
        self.assertEqual(full.ops, bare.ops)
        self.assertEqual(full.envelope, bare.envelope)
        self.assertEqual(full.program_digest, bare.program_digest)

    def test_the_digest_of_a_script_without_phases_has_not_moved(self) -> None:
        full = run(UNPHASED)
        self.assertEqual(full.program_digest, UNPHASED_DIGEST)

    def test_a_script_without_phases_carries_no_phases_key(self) -> None:
        """Отсутствие — это ОТСУТСТВИЕ ключа, а не пустой список: пустая
        таблица читалась бы как «автор нарисовал ноль фаз»."""
        full = run(UNPHASED)
        self.assertNotIn("phases", full.envelope)
        self.assertNotIn("phases", full.as_dict().get("envelope", {}))

    def test_the_phased_program_is_deterministic(self) -> None:
        """`replay_check` — не строгость ради строгости: подпись исходника не
        удостоверяет ничего, если две прогонки дают разные программы. Таблица
        фаз обязана быть такой же воспроизводимой, как сами опы."""
        result = run(
            'with phase("уровни"):\n'
            '    lvl = create_level(elev_mm=0, name="Этаж 1")\n'
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level=lvl,\n'
            '                height_mm=3000)\n', replay_check=True)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertTrue(result.isolation.get("replay_checked"))
        self.assertEqual(len(result.envelope["phases"]), 2)


# ═════════════════════════════════════════════════════════════════════════
# 4. СВОЙСТВО: РАЗБИЕНИЕ ОСТАЁТСЯ РАЗБИЕНИЕМ ПРИ ЛЮБОМ ЧИСЛЕ ФАЗ
# ═════════════════════════════════════════════════════════════════════════

class PhaseCountsHoldTheInvariants(_InProcess):
    """Семенованный PRNG, а не hypothesis: её нет в прод-venv (`test_pbt`)."""

    TRIALS = 40

    def test_every_generated_plan_is_a_partition_with_forward_only_refs(self) -> None:
        rng = random.Random(20260809)
        seen_counts: set[int] = set()
        for trial in range(self.TRIALS):
            with self.subTest(trial=trial):
                dsl.reset()
                n_phases = rng.randint(1, 6)
                seen_counts.add(n_phases)
                handles: list = []
                # ПОТОЛОК ЗДЕСЬ — СКРИПТОВЫЙ, А НЕ ПРОГРАММНЫЙ, и до
                # 15.08.2026 разница не проявлялась: при авторском бюджете 20
                # шесть фаз давали максимум 120 опов, то есть генератор не мог
                # дотянуться до потолка накопителя `dsl` (`MAX_BULK_OPS`=300).
                # После подъёма бюджета до 100 шесть фаз дают до 600, и два
                # прогона из сорока упёрлись в накопитель — отказом ПРОДУКТА,
                # верным по существу. Чинить надо генератор: он обязан
                # оставаться внутри той же границы, что и настоящий скрипт.
                # Свойство, которое файл проверяет (разбиение остаётся
                # разбиением при любом числе фаз), от величины draw не зависит.
                per_phase = max(1, min(MAX_OPS_PER_PROGRAM,
                                       (MAX_BULK_OPS - 1) // n_phases))
                for index in range(n_phases):
                    with C.phase(f"фаза {index}"):
                        for k in range(rng.randint(1, per_phase)):
                            if handles and rng.random() < 0.4:
                                self.wall(rng.choice(handles), k)
                            else:
                                handles.append(self.level(len(handles)))
                out = C.take_ops()
                self._assert_partition(out, n_phases)

    def _assert_partition(self, out: dict, n_phases: int) -> None:
        phases = out["phases"]
        self.assertEqual(len(phases), n_phases)
        self.assertEqual([p["index"] for p in phases], list(range(n_phases)))
        flat = [oid for p in phases for oid in p["op_ids"]]
        # РАЗБИЕНИЕ: те же адреса, в том же порядке, каждый ровно один раз.
        self.assertEqual(flat, [op["id"] for op in out["ops"]])
        self.assertEqual(len(flat), len(set(flat)))
        owner = {oid: p["index"] for p in phases for oid in p["op_ids"]}
        for phase in phases:
            self.assertTrue(1 <= len(phase["op_ids"]) <= MAX_OPS_PER_PROGRAM)
        for op in out["ops"]:
            for sel in _selectors(op):
                if sel.get("by") == "ref":
                    self.assertEqual(owner[str(sel["value"])], owner[op["id"]])
                elif sel.get("by") == C.CROSS_PHASE_BY:
                    self.assertEqual(owner[str(sel["value"])], sel["phase"])
                    self.assertLess(sel["phase"], owner[op["id"]])


# ═════════════════════════════════════════════════════════════════════════
# 5. ШОВ СО ШАГОМ 2 — ЗАКРЫТ FAIL-CLOSED, А НЕ ОБЕЩАНИЕМ
# ═════════════════════════════════════════════════════════════════════════

class NothingExecutesAsOneTransactionByAccident(unittest.TestCase):
    """Оба теста ОСТАЮТСЯ ПОСЛЕ ШАГА 2, и это несогласие с прошлым автором,
    записанное вместе с причиной.

    Он оставил их как «контракт для того, кто будет писать шаг 2: он снимет их
    вместе с подстановкой». Снимать нечего: `plan_program` исполняет ОДНУ
    транзакцию, а фаза обещает чекпойнт МЕЖДУ транзакциями. План, отданный ей
    целиком, обязан отказывать сегодня ровно так же, как вчера, — иначе фазы
    тихо склеились бы в одну транзакцию, то есть чекпойнт был бы объявлен и не
    существовал. Шаг 2 не отменил этот отказ, а поставил ВЫШЕ него функцию,
    которая режет план на пачку (`serving._run_plan` -> `split_phases`), и
    сюда план доезжает только у того, кто резать не стал.

    Изменился ровно ТЕКСТ отказа: он называет план и говорит, чем его резать.
    Это проверяется здесь же — «неизвестное поле конверта» посылало читателя
    убирать `phases`, то есть терять чекпойнты."""

    def test_a_phased_program_handed_over_whole_is_refused_by_name(self) -> None:
        result = run(
            'with phase("уровни"):\n'
            '    lvl = create_level(elev_mm=0, name="Этаж 1")\n'
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level=lvl,\n'
            '                height_mm=3000)\n')
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        # Ровно то, что делает с конвертом живая дверь (`serving.py`).
        program = {**result.envelope, "ops": result.ops}
        with self.assertRaises(KirRefusal) as caught:
            plan_program(program, bulk=False)
        codes = {d.code for d in caught.exception.diagnostics}
        fields = {d.field_name for d in caught.exception.diagnostics}
        self.assertIn("KIR-P003", codes)
        self.assertIn("phases", fields)
        text = " ".join(d.message_ru for d in caught.exception.diagnostics
                        if d.field_name == "phases")
        # ОТКАЗ НАЗЫВАЕТ ПОЧИНКУ, А НЕ ПОЛЕ. «Неизвестное поле конверта»
        # читается как «убери его» — то есть «потеряй чекпойнты».
        self.assertIn("split_phases", text)
        self.assertNotIn("неизвестное поле", text)

    def test_an_unsubstituted_cross_phase_marker_never_compiles(self) -> None:
        """Метка — это ОБЯЗАТЕЛЬСТВО подставить, а не форма селектора. Дойдя до
        компилятора неподставленной, она обязана отказать, а не быть понятой
        как-нибудь."""
        program = {"ir_version": spec.IR_VERSION, "ops": [
            {"op": "create_level", "id": "level1", "elev_mm": 0,
             "name": "Этаж 1"},
            {"op": "create_wall", "id": "wall1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": C.CROSS_PHASE_BY, "value": "level1", "phase": 0}},
        ]}
        with self.assertRaises(KirRefusal) as caught:
            plan_program(program, bulk=False)
        self.assertIn("level", {d.field_name for d in caught.exception.diagnostics})


# ═════════════════════════════════════════════════════════════════════════
# 6. ШАГ 2 — ПЛАН РЕЖЕТСЯ НА ПАЧКУ, И КАЖДОЕ ЗВЕНО ЕСТЬ ПРОГРАММА
# ═════════════════════════════════════════════════════════════════════════

class ThePlanBecomesAPackOfPrograms(_InProcess):
    """ГЛАВНОЕ УТВЕРЖДЕНИЕ ЭТОГО НАБОРА, и оно проверяется прогоном, а не
    рассуждением: здание, которое сегодня НЕЛЬЗЯ написать одной программой,
    после разреза становится пачкой программ, КАЖДУЮ из которых `plan_program`
    принимает. Именно эта пара — «одной нельзя, пачкой можно» — и есть работа,
    снятая с модели: раньше границу считала она, теперь компилятор.
    """

    def _house_with_stairs(self) -> dict:
        with C.phase("уровни"):
            lvl = self.level(0)
            self.level(1)
        with C.phase("каркас"):
            self.wall(lvl, 0)
            self.wall(lvl, 1)
        with C.phase("лестница"):
            dsl.OP_FUNCTIONS["create_stairs"](
                base_level="Этаж 1", top_level="Этаж 2",
                p0_mm=(1000, 1000), p1_mm=(4000, 1000), width_mm=1200)
        out = C.take_ops()
        out.setdefault("ir_version", spec.IR_VERSION)
        return out

    def test_the_building_one_program_cannot_hold_splits_into_ones_it_can(self) -> None:
        program = self._house_with_stairs()
        # ОДНОЙ ПРОГРАММОЙ — НЕЛЬЗЯ, и отказов ТРИ, каждый о своём:
        #   P003 — план в конверте (одна транзакция не исполняет план),
        #   L002 — create_stairs владеет своими транзакциями,
        #   T001 — метка `phase_result` не является селектором языка.
        # Три причины сразу — это и есть та работа, которую модель считала в
        # уме: ни одна из них не про геометрию.
        with self.assertRaises(KirRefusal) as caught:
            plan_program(program, bulk=False)
        self.assertLessEqual({"KIR-P003", "KIR-L002", "KIR-T001"},
                             {d.code for d in caught.exception.diagnostics})
        # ПАЧКОЙ — МОЖНО, и это тот же самый `plan_program`. Метки
        # подставляются ровно так же, как их подставит исполнитель: продуктом
        # прошлой фазы. Иначе звено «каркас» законно не спланировалось бы —
        # уровень ему ещё никто не назвал.
        links = compiler.split_phases(program)
        self.assertEqual([link.name for link in links],
                         ["уровни", "каркас", "лестница"])
        products: dict = {}
        for index, link in enumerate(links):
            body = compiler.substitute_phase_results(link.program, products)
            plan_program(body, bulk=False)
            products.update(compiler.phase_products(
                body["ops"],
                {op["id"]: {"id": str(900000 + index * 10 + k)}
                 for k, op in enumerate(body["ops"])}))

    def test_a_link_is_a_program_and_carries_no_trace_of_the_plan(self) -> None:
        """Звено обязано быть НЕОТЛИЧИМО от программы, написанной руками:
        конверт закрыт (`known_top`), и любое наше поле в нём — KIR-P003."""
        links = compiler.split_phases(self._house_with_stairs())
        for link in links:
            self.assertNotIn("phases", link.program)
            self.assertLessEqual(set(link.program),
                                 {"ir_version", "intent", "allow_destructive",
                                  "defaults", "ops"})

    def test_the_ops_travel_byte_for_byte(self) -> None:
        """Дайджест подписывает ЗАМЫСЕЛ; переписанный по дороге оп сделал бы
        подпись подписью не того."""
        program = self._house_with_stairs()
        links = compiler.split_phases(program)
        flat = [op for link in links for op in link.program["ops"]]
        self.assertEqual(flat, program["ops"])

    def test_the_budget_is_not_raised_by_a_single_unit(self) -> None:
        """ПРОВЕРЯЕТСЯ ИМЕННО ПРЕДОХРАНИТЕЛЬ. План даёт написать ЗДАНИЕ, а не
        программу больше двадцати операций: звено на 21 оп отказывает тем же
        KIR-L001, что и раньше."""
        program = {"ir_version": spec.IR_VERSION,
                   "ops": [{"op": "create_level", "id": f"l{i}",
                            "elev_mm": i * 3000, "name": f"Этаж {i}"}
                           for i in range(MAX_OPS_PER_PROGRAM + 1)],
                   "phases": [{"index": 0, "name": "всё сразу",
                               "op_ids": [f"l{i}" for i in
                                          range(MAX_OPS_PER_PROGRAM + 1)]}]}
        links = compiler.split_phases(program)
        self.assertEqual(len(links), 1)
        with self.assertRaises(KirRefusal) as caught:
            plan_program(links[0].program, bulk=False)
        self.assertIn("KIR-L001", {d.code for d in caught.exception.diagnostics})

    def test_a_table_that_is_not_a_partition_refuses_and_names_the_gap(self) -> None:
        """Таблица приезжает В КОНВЕРТЕ, и конверт может прислать кто угодно:
        `serving` не отличает собранный песочницей от набранного руками.
        Молча съеденный оп — это элемент, который никто не построит и о
        котором никто не скажет."""
        base = {"ir_version": spec.IR_VERSION, "ops": [
            {"op": "create_level", "id": "l0", "elev_mm": 0, "name": "Этаж 1"},
            {"op": "create_level", "id": "l1", "elev_mm": 3000, "name": "Этаж 2"},
        ]}
        for table, needle in (
                ([{"index": 0, "name": "часть", "op_ids": ["l0"]}], "l1"),
                ([{"index": 0, "name": "дважды", "op_ids": ["l0", "l0", "l1"]}],
                 "l0"),
                ([{"index": 0, "name": "чужой", "op_ids": ["l0", "l9"]}], "l9"),
                ([{"index": 1, "name": "не с нуля", "op_ids": ["l0", "l1"]}],
                 "нумеруются"),
                ([{"index": 0, "name": "", "op_ids": ["l0", "l1"]}], "имени"),
                ([{"index": 0, "name": "пусто", "op_ids": []}], "ни одной"),
        ):
            with self.subTest(name=table[0]["name"]):
                with self.assertRaises(KirRefusal) as caught:
                    compiler.split_phases({**base, "phases": table})
                diags = caught.exception.diagnostics
                self.assertEqual({"KIR-L006"}, {d.code for d in diags})
                self.assertIn(needle,
                              " ".join(d.message_ru for d in diags))

    def test_the_order_of_phases_is_the_order_of_the_script(self) -> None:
        """Переставленные местами фазы — не «другой план», а РАСХОЖДЕНИЕ с
        порядком, в котором автор написал операции; сортировать за него
        нечем."""
        base = {"ir_version": spec.IR_VERSION, "ops": [
            {"op": "create_level", "id": "l0", "elev_mm": 0, "name": "Этаж 1"},
            {"op": "create_level", "id": "l1", "elev_mm": 3000, "name": "Этаж 2"},
        ]}
        with self.assertRaises(KirRefusal) as caught:
            compiler.split_phases({**base, "phases": [
                {"index": 0, "name": "вторая", "op_ids": ["l1"]},
                {"index": 1, "name": "первая", "op_ids": ["l0"]}]})
        self.assertIn("порядок",
                      " ".join(d.message_ru for d in caught.exception.diagnostics))


class TheWitnessOfOnePhaseFeedsTheNext(_InProcess):
    """ЕДИНСТВЕННОЕ, ЧТО ПЕРЕСЕКАЕТ ГРАНИЦУ ПРОГРАММЫ, — ПОДСТАВЛЕННЫЙ
    ElementId. `by=ref` через границу не проходит и не будет: соседняя фаза
    исполнена ОТДЕЛЬНОЙ транзакцией. Что существует — настоящий id в квитанции
    той фазы, и перепечатывание его руками из прошлого хода снимается здесь."""

    def _two_phases(self):
        with C.phase("уровень"):
            lvl = self.level(0)
        with C.phase("стена"):
            self.wall(lvl, 0)
        out = C.take_ops()
        out.setdefault("ir_version", spec.IR_VERSION)
        return compiler.split_phases(out)

    def test_the_marker_becomes_a_real_element_id(self) -> None:
        links = self._two_phases()
        self.assertEqual(links[1].program["ops"][0]["level"],
                         {"by": C.CROSS_PHASE_BY, "value": "level1",
                          "phase": 0})
        products = compiler.phase_products(
            links[0].program["ops"], {"level1": {"id": "483911"}})
        self.assertEqual(products, {"level1": 483911})
        body = compiler.substitute_phase_results(links[1].program, products)
        self.assertEqual(body["ops"][0]["level"],
                         {"by": "element_id", "value": 483911})
        # И ЭТО ПРОГРАММА, А НЕ ПОХОЖАЯ НА НЕЁ ФОРМА.
        plan_program(body, bulk=False)

    def test_the_bridge_may_answer_with_a_number_or_a_string(self) -> None:
        """Мост шлёт и `42`, и `"42"`; догадка о типе стоила бы фазы."""
        links = self._two_phases()
        for wire in ("483911", 483911):
            with self.subTest(wire=type(wire).__name__):
                self.assertEqual(
                    compiler.phase_products(links[0].program["ops"],
                                            {"level1": {"id": wire}}),
                    {"level1": 483911})

    def test_a_missing_product_refuses_and_never_passes_the_marker_down(self) -> None:
        """Метка — ОБЯЗАТЕЛЬСТВО подставить. Оставить её значило бы отправить
        вниз форму селектора, которой в языке нет, и получить отказ, указующий
        не на ту причину."""
        links = self._two_phases()
        with self.assertRaises(KirRefusal) as caught:
            compiler.substitute_phase_results(links[1].program, {})
        diags = caught.exception.diagnostics
        self.assertEqual({"KIR-L006"}, {d.code for d in diags})
        self.assertIn("level1", " ".join(d.message_ru for d in diags))

    def test_only_a_referenceable_result_becomes_a_product(self) -> None:
        """Группа и удаление несут идентичность и ссылаемыми НЕ являются —
        это записано в докстроке самого `ResultSpec`. Подставить их id через
        границу значило бы разрешить снаружи больше, чем внутри программы."""
        wrong = [name for name, ospec in spec.OPS.items()
                 if ospec.result.identity_field and not ospec.result.referenceable]
        self.assertTrue(wrong, "в реестре не осталось неcсылаемых результатов")
        for name in wrong:
            with self.subTest(op=name):
                self.assertEqual(
                    compiler.phase_products([{"op": name, "id": "x"}],
                                            {"x": {"id": "77"}}),
                    {})

    def test_a_bogus_element_id_never_becomes_a_product(self) -> None:
        """ГРАНИЦА БЕРЁТСЯ У ЯЗЫКА (`emit_utils.ELEMENT_ID_MAX` = максимум
        int64), а не назначается здесь: `10**12` — ЗАКОННЫЙ ElementId, и
        отвергнуть его «на глазок как слишком большой» значило бы завести
        второй предел рядом с настоящим. Отвергается то, что не является
        положительным целым."""
        links = self._two_phases()
        for wire in (0, -3, True, None, "", "нет", ELEMENT_ID_MAX + 1):
            with self.subTest(wire=repr(wire)):
                self.assertEqual(
                    compiler.phase_products(links[0].program["ops"],
                                            {"level1": {"id": wire}}),
                    {})


class ThePlanIsLedPhaseByPhase(_InProcess):
    """ИСПОЛНИТЕЛЬ. Мост здесь подменён, и это ГРАНИЦА ЭТОГО КЛАССА: он
    проверяет ПОРЯДОК, ПОДСТАНОВКУ и ЧЕСТНОСТЬ КВИТАНЦИИ, а не то, что Revit
    построил. Второе доказывается только живым устройством, и заявлять его
    отсюда было бы ровно тем `ok:true` без независимой приёмки, ради запрета
    которого стоит весь дом."""

    def _plan_of(self, *, phases: int = 3) -> dict:
        with C.phase("уровни"):
            lvl = self.level(0)
        with C.phase("каркас"):
            self.wall(lvl, 0)
        if phases > 2:
            with C.phase("лестница"):
                dsl.OP_FUNCTIONS["create_stairs"](
                    base_level="Этаж 1", top_level="Этаж 2",
                    p0_mm=(1000, 1000), p1_mm=(4000, 1000), width_mm=1200)
        out = C.take_ops()
        out.setdefault("ir_version", spec.IR_VERSION)
        return out

    def _run(self, program, inner):
        import asyncio

        from kukai.ir import serving

        original = serving._handle_revit_ir_inner
        serving._handle_revit_ir_inner = inner
        try:
            authored = serving._AuthoredInput(args={"program": program},
                                              from_script=True)
            return asyncio.run(serving._run_plan(
                program, None, None, query_id="t", authored=authored))
        finally:
            serving._handle_revit_ir_inner = original

    @staticmethod
    def _green(seen: list, first_id: int = 600001):
        async def inner(args, llm, bridge, *, query_id="", bulk=False, **kw):
            body = args["program"]
            seen.append(body)
            payload = {op["id"]: {"id": str(first_id + i)}
                       for i, op in enumerate(body["ops"])}
            payload["ok"] = True
            return {"ok": True, "kir": True, "result": {"result": payload},
                    "outcome": {"execution": "committed", "retry": "forbidden"},
                    "message_ru": "записано"}
        return inner

    def test_one_script_becomes_one_program_per_phase_in_written_order(self) -> None:
        seen: list = []
        result = self._run(self._plan_of(), self._green(seen))
        self.assertTrue(result["ok"], result.get("message_ru"))
        self.assertEqual([len(body["ops"]) for body in seen], [1, 1, 1])
        self.assertEqual(result["plan"]["phases"], 3)
        self.assertEqual(result["plan"]["committed"], 3)
        self.assertNotIn("resume_from", result["plan"])
        self.assertEqual([step["name"] for step in result["plan"]["steps"]],
                         ["уровни", "каркас", "лестница"])

    def test_the_second_phase_is_sent_with_a_real_element_id(self) -> None:
        seen: list = []
        self._run(self._plan_of(), self._green(seen, first_id=700007))
        self.assertEqual(seen[1]["ops"][0]["level"],
                         {"by": "element_id", "value": 700007})

    def test_a_failed_phase_stops_the_plan_and_names_where_to_resume(self) -> None:
        """ЧЕКПОЙНТ — ОБЕЩАНИЕ, И ОНО ВЫПОЛНЯЕТСЯ БУКВАЛЬНО. Фаза атомарна,
        план нет: провал второй НЕ откатывает первую. Значит квитанция обязана
        сказать, с какой фазы продолжать, — план, повторённый целиком,
        построил бы построенное второй раз."""
        seen: list = []
        green = self._green(seen)
        calls = [0]

        async def inner(args, llm, bridge, **kw):
            calls[0] += 1
            if calls[0] == 2:
                return {"ok": False, "kir": True, "stage": "execute",
                        "message_ru": "постусловие стены не сошлось",
                        "outcome": {"execution": "rolled_back",
                                    "retry": "safe"},
                        "handoff": "recipe-path"}
            return await green(args, llm, bridge, **kw)

        result = self._run(self._plan_of(), inner)
        self.assertFalse(result["ok"])
        # ТРЕТЬЯ ФАЗА НЕ ОТПРАВЛЯЛАСЬ: она могла ссылаться на результат второй.
        self.assertEqual(calls[0], 2)
        self.assertEqual(result["plan"]["committed"], 1)
        self.assertEqual(result["plan"]["resume_from"], 1)
        self.assertIn("ПЛАН ВСТАЛ НА ФАЗЕ №1", result["message_ru"])
        self.assertIn("постусловие стены не сошлось", result["message_ru"])
        # ПОВТОР ПЛАНА ЦЕЛИКОМ ПРОДУБЛИРОВАЛ БЫ ПОСТРОЕННОЕ.
        self.assertIsNone(result["handoff"])
        self.assertIs(result["err"]["retryable"], False)

    def test_a_failure_in_the_first_phase_stays_retryable(self) -> None:
        """Обратная сторона того же правила: пока НИЧЕГО не построено,
        повторять план целиком безопасно, и отнимать это у модели значило бы
        отказывать по чужой причине."""
        async def inner(args, llm, bridge, **kw):
            return {"ok": False, "kir": True, "stage": "plan",
                    "message_ru": "селектор уровня не сведён",
                    "outcome": {"execution": "not_started", "retry": "safe"},
                    "handoff": "recipe-path"}

        result = self._run(self._plan_of(), inner)
        self.assertFalse(result["ok"])
        self.assertEqual(result["plan"]["committed"], 0)
        self.assertEqual(result["plan"]["resume_from"], 0)
        self.assertIsNot((result.get("err") or {}).get("retryable"), False)

    def _route(self, program) -> str:
        """Куда чат-дверь отправила программу: «план» или «тело». ОБЕ стороны
        одним прибором — тест «не позвали план» в одиночку прошёл бы и на
        мёртвом крючке."""
        import asyncio

        from kukai.ir import serving

        where: list = []

        async def inner(args, llm, bridge, **kw):
            where.append("тело")
            return {"ok": True, "kir": True, "outcome": {}}

        async def plan(*a, **kw):
            where.append("план")
            return {"ok": True, "kir": True, "outcome": {}}

        originals = (serving._handle_revit_ir_inner, serving._run_plan)
        serving._handle_revit_ir_inner, serving._run_plan = inner, plan
        try:
            asyncio.run(serving.handle_revit_ir({"program": program},
                                                None, None, query_id="t"))
        finally:
            serving._handle_revit_ir_inner, serving._run_plan = originals
        self.assertEqual(len(where), 1, where)
        return where[0]

    def test_a_program_without_phases_never_reaches_the_plan_executor(self) -> None:
        """ОТСУТСТВИЕ ОСТАЁТСЯ ОТСУТСТВИЕМ — на двери, а не только в языке."""
        self.level(0)
        program = {**C.take_ops(), "ir_version": spec.IR_VERSION}
        self.assertNotIn("phases", program)
        self.assertEqual(self._route(program), "тело")

    def test_a_phased_program_reaches_the_plan_executor(self) -> None:
        """ВТОРАЯ ПОЛОВИНА ТОГО ЖЕ УТВЕРЖДЕНИЯ. Крючок, который никого не
        ловит, неотличим от отсутствующего — ровно так `sdk.py` пролежал
        отличным и недостижимым пять недель."""
        self.assertEqual(self._route(self._plan_of()), "план")


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
