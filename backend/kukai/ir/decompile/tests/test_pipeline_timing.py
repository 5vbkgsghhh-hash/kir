"""ПРИБОР ВРЕМЕНИ: длительность записывается, и записывается В ВЕРНОЕ ВЕДРО.

Замер, с которого волна началась: живое извлечение К2 шло полтора часа, а
`run.json` не нёс длительности НИ У ОДНОГО из 78 слепков на диске.  Сравнивать
было не с чем — «стало вдвое быстрее» и «стало вдвое медленнее» выглядели
одинаково.

Здесь проверяется не «в артефакте есть число» (это прошло бы и на нулях), а
АТРИБУЦИЯ: медленным делается ровно ОДИН участок, и ровно его ведро обязано
вырасти.  Тест краснеет, если границы замера переставить местами, если
`bridge_ms` начнут считать от начала разбора, если разбивку перестать
докладывать в run.json/status.json или если она не переживёт резюм.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from kukai.ir.decompile import pipeline as pipe
from kukai.ir.decompile.extract import _timing_totals
from kukai.ir.decompile.tests.test_pipeline import FakePipelineBridge, _run

#: Задержка, которую тест вставляет в мост.  Заметно больше любой настоящей
#: работы подделки (микросекунды), чтобы вывод не зависел от нагрузки коробки.
SLOW_MS = 400.0


class _SlowBridge(FakePipelineBridge):
    """Мост, который МЕДЛЕННО отвечает на страницы категорий.

    Задержка вешается только на постраничный вызов (у него в теле есть
    ``long __After``), а не на пробу и не на боковые стадии: тогда рост обязан
    появиться в ``bridge_ms`` извлечения и НИГДЕ БОЛЬШЕ.
    """

    def __init__(self, *, delay_s: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.delay_s = delay_s
        self.slow_calls = 0

    async def __call__(self, code: str, *, timeout_ms: int) -> dict[str, Any]:
        if "long __After = " in code:
            self.slow_calls += 1
            await asyncio.sleep(self.delay_s)
        return await super().__call__(code, timeout_ms=timeout_ms)


def _decompile(tmp: str, bridge: Any) -> Any:
    return _run(pipe.run_decompile(
        bridge, out_dir=tmp, change_stamp="timing-stamp"))


class TimingIsRecordedTests(unittest.TestCase):
    def test_run_json_and_status_carry_a_stage_breakdown(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _decompile(tmp, FakePipelineBridge())
            self.assertTrue(result.ok, result.error)

            run = json.loads((Path(tmp) / "run.json").read_bytes())
            self.assertIn("timing", run)
            timing = run["timing"]

            # Стадии названы поимённо — иначе «час» невозможно приписать.
            stage_ms = timing["stage_ms"]
            for stage in ("extract", "lift", "fold", "name", "verify",
                          "passport", "curve", "sketch", "curtain"):
                self.assertIn(stage, stage_ms, f"стадия {stage} не замерена")
                self.assertGreaterEqual(stage_ms[stage], 0.0)

            # Итог прогона не меньше суммы стадий: стадии — ЧАСТИ прогона.
            self.assertGreaterEqual(
                timing["elapsed_ms"], max(stage_ms.values()))

            # Граница замера объявлена В САМОМ АРТЕФАКТЕ, а не только в
            # докладе: прибор, чей охват известен лишь автору, читается как
            # полный.
            self.assertIn("НЕ ДЕЛИТСЯ", timing["boundary"])

            # Разбивка извлечения доехала до run.json целиком.
            extract = timing["extract"]
            for key in ("bridge_ms", "parse_ms", "write_ms", "probe_ms",
                        "our_ms", "pages", "elements", "bridge_ms_share"):
                self.assertIn(key, extract)
            self.assertGreater(extract["pages"], 0)
            self.assertGreater(extract["elements"], 0)
            self.assertTrue(extract["by_category"])

            # То же самое видно ВО ВРЕМЯ прогона, а не только после.
            status = json.loads((Path(tmp) / "status.json").read_bytes())
            self.assertIn("timing", status)
            self.assertIn("extract", status["timing"]["stage_ms"])

    def test_slow_bridge_moves_bridge_ms_and_not_our_side(self) -> None:
        """АТРИБУЦИЯ. Медленный мост обязан удорожать МОСТ, а не наш разбор.

        Замер ОДНОПРОГОННЫЙ, и это принципиально: коробка делится с продом,
        разброс `our_ms` между двумя одинаковыми прогонами доходил до 300 мс,
        и тест на разности прогонов был бы мигающим — то есть прибором,
        которому нельзя верить, в волне про прибор.

        Вместо этого задержка берётся заведомо БОЛЬШЕ настоящей работы
        подделки (~430 мс на fsync), и проверяются две границы внутри одного
        прогона: мост обязан ВМЕСТИТЬ вставленное время, а наша сторона
        обязана в него НЕ ВЛЕЗТЬ.
        """

        with TemporaryDirectory() as tmp:
            slow = _SlowBridge(delay_s=SLOW_MS / 1000.0)
            self.assertTrue(_decompile(tmp, slow).ok)
            timing = json.loads(
                (Path(tmp) / "run.json").read_bytes())["timing"]

        extract = timing["extract"]
        pages = extract["pages"]
        self.assertGreater(slow.slow_calls, 0, "задержка не сработала")
        injected = SLOW_MS * pages

        # 1. Ведро моста ВМЕСТИЛО вставленное время.  Красное, если замер
        #    моста закрыть раньше, чем вернулся ответ.
        self.assertGreaterEqual(
            extract["bridge_ms"], injected * 0.9,
            f"вставлено {injected:.0f} мс задержки, а bridge_ms = "
            f"{extract['bridge_ms']:.0f} мс — время утекло мимо ведра моста")

        # 2. Наша сторона в него НЕ ВЛЕЗЛА.  Красное, если parse_ms или
        #    write_ms начать считать от отметки ДО вызова моста, — именно эта
        #    перестановка границ и делает разбивку враньём.
        self.assertLess(
            extract["our_ms"], injected * 0.5,
            f"our_ms = {extract['our_ms']:.0f} мс при вставленных "
            f"{injected:.0f} мс сна в МОСТУ — ведра перепутаны")

        # 3. Доля моста при медленном мосте — подавляющая.
        self.assertGreater(extract["bridge_ms_share"], 0.6)

    def test_breakdown_is_per_category_and_survives_resume(self) -> None:
        """Разбивка живёт в чекпойнте — резюм её не обнуляет."""

        with TemporaryDirectory() as tmp:
            bridge = FakePipelineBridge()
            self.assertTrue(_decompile(tmp, bridge).ok)

            ckpt = json.loads(
                (Path(tmp) / "L0.checkpoint.json").read_bytes())
            self.assertIn("timing", ckpt)
            self.assertTrue(ckpt["timing"], "покатегорийная разбивка пуста")
            for category, slot in ckpt["timing"].items():
                for key in ("probe_ms", "bridge_ms", "parse_ms", "write_ms",
                            "pages", "bytes", "elements"):
                    self.assertIn(key, slot, f"{category}: нет {key}")

            # Резюм по готовому потоку отдаёт разбивку ТОГО чтения, которое
            # его наполнило, а не пустую — иначе повторный прогон выглядел
            # бы бесплатным.
            again = _decompile(tmp, FakePipelineBridge())
            self.assertTrue(again.ok, again.error)
            self.assertTrue(
                again.timing["extract"]["by_category"],
                "резюм потерял разбивку извлечения")

    def test_totals_do_not_invent_a_split_we_cannot_make(self) -> None:
        """`our_ms` — это ровно parse+write, и ничего сверх того."""

        totals = _timing_totals({
            "OST_Walls": {"probe_ms": 5, "bridge_ms": 900, "parse_ms": 60,
                          "write_ms": 40, "pages": 2, "bytes": 10,
                          "elements": 7},
            "OST_Doors": {"probe_ms": 5, "bridge_ms": 100, "parse_ms": 40,
                          "write_ms": 60, "pages": 1, "bytes": 5,
                          "elements": 3},
        })
        self.assertEqual(totals["bridge_ms"], 1000.0)
        self.assertEqual(totals["our_ms"], 200.0)
        self.assertEqual(totals["pages"], 3.0)
        self.assertEqual(totals["elements"], 10.0)
        # Доля моста считается от bridge+наше, а не от календарного времени
        # прогона: между вызовами есть ожидание окна и уступки циклу, и
        # приписывать их мосту значило бы выдать оценку за замер.
        self.assertAlmostEqual(totals["bridge_ms_share"], 1000 / 1200, places=3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
