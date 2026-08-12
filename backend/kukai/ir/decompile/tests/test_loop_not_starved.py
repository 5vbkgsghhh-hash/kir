"""Прогон разбора не имеет права делать сервер мёртвым для всех остальных.

ЖИВОЙ ЗАМЕР 30.07. Во время выемки башни ``/health`` не ответил ДВЕНАДЦАТЬ раз
подряд, по 25 секунд каждый — минутой раньше тот же запрос отвечал за 2 мс.
Бэкенд поднят одним воркером (``uvicorn --workers 1``), а конвейер после чтения
делает тяжёлую СИНХРОННУЮ работу прямо в цикле событий: материализация 88 МБ
L0, разбор 18 МБ бокового индекса, лифт, свёртка, verify, сериализация
паспорта. На эти минуты сервер не отвечает НИКОМУ: чат-сокеты не получают
ответа на пинг и отваливаются с close_code=1006 (62 обрыва за 12 часов у десяти
разных устройств), HTTP висит.

Жалоба оператора звучала как «нет нет да сервер отлетает». Это не «нет нет да»
— это каждый раз, когда кто-то гоняет разбор.

Тесты ниже не мерят время (на синтетике из пяти элементов мерить нечего) — они
требуют СТРУКТУРНОГО свойства: тяжёлый шаг обязан исполняться НЕ в потоке
цикла событий. Свойство проверяемо и не зависит от размера модели.
"""
from __future__ import annotations

import asyncio
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kukai.ir.decompile import pipeline as pipe
from kukai.ir.decompile.tests.test_pipeline import FakePipelineBridge, _run


class LoopNotStarvedTests(unittest.TestCase):
    """Каждый тяжёлый шаг называется по имени: забыть один — значит вернуть дефект."""

    #: Имя в ``pipeline`` -> человеческое название шага. Список ОТКРЫТЫЙ по
    #: смыслу: появится новый тяжёлый шаг — добавь строку, иначе он поедет по
    #: циклу событий и никто не заметит, пока не отвалятся сокеты.
    HEAVY_STEPS = {
        "cached_lift_document_detailed": "лифт",
        "fold_document": "свёртка",
        "name_document": "именование",
        "verify_document": "verify",
        "build_passport": "паспорт",
        "_persist_core_artifacts": "сериализация артефактов",
        "build_dependency_manifest": "манифест зависимостей",
        "reconcile_census": "перепись",
    }

    def _threads_of(self, step: str) -> list[str]:
        seen: list[str] = []
        original = getattr(pipe, step)

        def spy(*args, **kwargs):
            seen.append(threading.current_thread().name)
            return original(*args, **kwargs)

        setattr(pipe, step, spy)
        try:
            with TemporaryDirectory() as tmp:
                result = _run(pipe.run_decompile(
                    FakePipelineBridge(), out_dir=tmp,
                    change_stamp="pipeline-mini-v1"))
                self.assertTrue(result.ok, msg=result.to_dict())
        finally:
            setattr(pipe, step, original)
        return seen

    def test_every_heavy_step_runs_off_the_event_loop_thread(self) -> None:
        main = threading.main_thread().name
        for step, human in self.HEAVY_STEPS.items():
            with self.subTest(step=step):
                threads = self._threads_of(step)
                self.assertTrue(threads, f"{human}: шаг не вызвался вовсе")
                for name in threads:
                    self.assertNotEqual(
                        name, main,
                        f"{human} исполняется в потоке цикла событий — "
                        f"на большой модели это минуты мёртвого сервера")

    def test_l0_materialize_runs_off_the_event_loop_thread(self) -> None:
        """Разбор 88 МБ JSONL — самый долгий из шагов, и он был первым."""
        seen: list[str] = []
        original = pipe.L0JSONLReader.materialize

        def spy(self_reader, *args, **kwargs):
            seen.append(threading.current_thread().name)
            return original(self_reader, *args, **kwargs)

        pipe.L0JSONLReader.materialize = spy
        try:
            with TemporaryDirectory() as tmp:
                result = _run(pipe.run_decompile(
                    FakePipelineBridge(), out_dir=tmp,
                    change_stamp="pipeline-mini-v1"))
                self.assertTrue(result.ok, msg=result.to_dict())
        finally:
            pipe.L0JSONLReader.materialize = original

        self.assertTrue(seen, "материализация не вызвалась")
        self.assertNotIn(threading.main_thread().name, seen)

    def test_the_loop_keeps_ticking_while_a_heavy_step_blocks(self) -> None:
        """Цикл причинно освобождает тяжёлый шаг, а не просто успевает рядом.

        Подменённая свёртка ждёт сигнал, который может выставить ТОЛЬКО
        часовой в event loop после нескольких своих тиков. Если свёртка
        случайно вернётся в loop thread, часовой не сможет её освободить и
        сработает аварийный таймаут worker-а. Это проверяет тот же инвариант,
        но не делает состояние системного планировщика частью контракта.
        """
        original = pipe.fold_document
        worker_started = threading.Event()
        release_worker = threading.Event()
        worker_timed_out = threading.Event()
        worker_threads: list[int] = []

        def slow(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            worker_started.set()
            if not release_worker.wait(2.0):
                worker_timed_out.set()
            return original(*args, **kwargs)

        ticks_while_worker_waited: list[int] = []

        async def scenario():
            stop = asyncio.Event()
            loop_thread = threading.get_ident()

            async def sentry():
                while not stop.is_set():
                    await asyncio.sleep(0)
                    if (worker_started.is_set()
                            and not release_worker.is_set()):
                        ticks_while_worker_waited.append(
                            threading.get_ident())
                        if len(ticks_while_worker_waited) >= 10:
                            release_worker.set()

            watch = asyncio.ensure_future(sentry())
            try:
                with TemporaryDirectory() as tmp:
                    result = await pipe.run_decompile(
                        FakePipelineBridge(), out_dir=tmp,
                        change_stamp="pipeline-mini-v1")
                    return result, loop_thread
            finally:
                stop.set()
                # Не оставлять worker до собственного таймаута, даже если
                # pipeline завершился исключением до причинного сигнала.
                release_worker.set()
                await watch

        pipe.fold_document = slow
        try:
            result, loop_thread = asyncio.run(scenario())
        finally:
            pipe.fold_document = original

        self.assertTrue(result.ok, msg=result.to_dict())
        self.assertTrue(worker_threads, "свёртка не вызвалась")
        self.assertNotEqual(worker_threads[0], loop_thread)
        self.assertFalse(
            worker_timed_out.is_set(),
            "event loop не освободил блокирующую свёртку")
        self.assertEqual(len(ticks_while_worker_waited), 10)
        self.assertEqual(set(ticks_while_worker_waited), {loop_thread})

    def test_core_artifact_offload_preserves_exact_bytes_and_names(self) -> None:
        passport = {
            "doc_name": "мини-здание",
            "revit_version": "2023",
            "change_stamp": "stable-v1",
            "gestalt": "mixed",
            "stats": {
                "elements_total": 2,
                "ops_lifted": 1,
                "atoms": 1,
                "floors": 1,
                "rooms": 0,
                "apartments": 0,
            },
            "verify_summary": {"failed_count": 0, "reversible": True},
        }
        tree = {
            "kind": "building",
            "name": "Корпус А",
            "children": [{"kind": "floor", "name": "Этаж 1"}],
        }
        named_tree = {
            "kind": "building",
            "name": "Именованный корпус",
            "children": [],
        }

        def atomic_json_bytes(value):
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            passport_md = pipe._persist_core_artifacts(
                out, passport, tree, {"tree": named_tree})

            self.assertEqual(
                {path.name for path in out.iterdir()},
                {"passport.json", "passport.md", "tree.json", "named.json"},
            )
            self.assertEqual(
                (out / "passport.json").read_bytes(),
                pipe.passport_bytes(passport),
            )
            self.assertEqual(
                (out / "passport.md").read_bytes(),
                pipe._passport_markdown(passport).encode("utf-8"),
            )
            self.assertEqual(
                (out / "tree.json").read_bytes(), atomic_json_bytes(tree))
            self.assertEqual(
                (out / "named.json").read_bytes(),
                atomic_json_bytes(named_tree),
            )
            self.assertEqual(passport_md, out / "passport.md")


if __name__ == "__main__":
    unittest.main()
