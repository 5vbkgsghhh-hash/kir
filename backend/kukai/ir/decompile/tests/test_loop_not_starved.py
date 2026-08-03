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
import threading
import unittest
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
        """Прямая проверка смысла: цикл жив, пока тяжёлый шаг занят.

        Тяжёлый шаг подменяется на заведомо блокирующий (полсекунды сна в
        ПОТОКЕ, не await). Часовой тикает каждые 10 мс. Если шаг поедет по
        циклу событий, часовой не тикнет ни разу.
        """
        original = pipe.fold_document

        def slow(*args, **kwargs):
            threading.Event().wait(0.5)
            return original(*args, **kwargs)

        marks: list[float] = []

        async def scenario():
            stop = asyncio.Event()

            async def sentry():
                loop = asyncio.get_running_loop()
                while not stop.is_set():
                    await asyncio.sleep(0.01)
                    marks.append(loop.time())

            watch = asyncio.ensure_future(sentry())
            try:
                with TemporaryDirectory() as tmp:
                    return await pipe.run_decompile(
                        FakePipelineBridge(), out_dir=tmp,
                        change_stamp="pipeline-mini-v1")
            finally:
                stop.set()
                await watch

        pipe.fold_document = slow
        try:
            result = asyncio.run(scenario())
        finally:
            pipe.fold_document = original

        self.assertTrue(result.ok, msg=result.to_dict())
        self.assertGreater(len(marks), 5, "часовой не тикнул почти ни разу")
        # Мерится САМАЯ ДЛИННАЯ пауза между тиками, а не их число: сумма тиков
        # растёт за счёт спокойных участков прогона и прячет ровно то, что
        # ищем — один длинный провал. Шаг подменён на блокирующие 0.5 с;
        # порог 0.3 с ловит его и не срабатывает на дрожании планировщика.
        gaps = [b - a for a, b in zip(marks, marks[1:])]
        self.assertLess(
            max(gaps), 0.3,
            f"цикл событий стоял {max(gaps):.2f} с, пока тяжёлый шаг работал")


if __name__ == "__main__":
    unittest.main()
