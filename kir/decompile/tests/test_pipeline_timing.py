"""THE TIME INSTRUMENT: duration is recorded, and recorded in THE RIGHT BUCKET.

The measurement that started the wave: a live K2 extraction ran an hour and a half, and
`run.json` carried no duration for NOT ONE of the 78 snapshots on disk.  There was
nothing to compare against — "became twice as fast" and "became twice as slow" looked
the same.

What is checked here is not "the artifact has a number" (that would pass even on zeros), but
ATTRIBUTION: exactly ONE section is made slow, and exactly its bucket must
grow.  The test turns red if the measurement boundaries are swapped, if
`bridge_ms` starts being counted from the beginning of parsing, if the breakdown stops
being reported in run.json/status.json, or if it does not survive a resume.
"""
from __future__ import annotations

import json
import time as _real_time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock

from kir.decompile import extract as _extract
from kir.decompile import pipeline as pipe
from kir.decompile.extract import _timing_totals
from kir.decompile.tests.test_pipeline import FakePipelineBridge, _run

#: The step of the virtual clock inside each paginated bridge call.
SLOW_MS = 400.0


class _Clock:
    """A clock that runs only inside the fake bridge call."""

    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _ClockShim:
    """The `time` substitution only in the extract namespace; loop.time is untouched."""

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock

    def monotonic(self) -> float:
        return self._clock.now

    def __getattr__(self, name: str) -> Any:
        return getattr(_real_time, name)


class _SlowBridge(FakePipelineBridge):
    """A bridge that answers category pages SLOWLY.

    The delay is hung only on the paginated call (it has ``long __After``
    in its body), not on the probe and not on the side stages: then the growth must
    appear in extraction's ``bridge_ms`` and NOWHERE ELSE.
    """

    def __init__(self, *, delay_s: float, clock: _Clock, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.delay_s = delay_s
        self.clock = clock
        self.slow_calls = 0

    async def __call__(self, code: str, *, timeout_ms: int) -> dict[str, Any]:
        if "long __After = " in code:
            self.slow_calls += 1
            self.clock.advance(self.delay_s)
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

            # The stages are named individually — otherwise the "hour" cannot be attributed.
            stage_ms = timing["stage_ms"]
            for stage in ("extract", "lift", "fold", "name", "verify",
                          "passport", "curve", "sketch", "curtain"):
                self.assertIn(stage, stage_ms, f"стадия {stage} не замерена")
                self.assertGreaterEqual(stage_ms[stage], 0.0)

            # The run total is not less than the sum of the stages: the stages are PARTS of the run.
            self.assertGreaterEqual(
                timing["elapsed_ms"], max(stage_ms.values()))

            # The measurement boundary is declared IN THE ARTIFACT ITSELF, not only in
            # the report: an instrument whose coverage is known only to its author reads as
            # complete.
            self.assertIn("НЕ ДЕЛИТСЯ", timing["boundary"])

            # The extraction breakdown made it into run.json in full.
            extract = timing["extract"]
            for key in ("bridge_ms", "parse_ms", "write_ms", "probe_ms",
                        "our_ms", "pages", "elements", "bridge_ms_share"):
                self.assertIn(key, extract)
            self.assertGreater(extract["pages"], 0)
            self.assertGreater(extract["elements"], 0)
            self.assertTrue(extract["by_category"])

            # The same thing is visible DURING the run, not only afterward.
            status = json.loads((Path(tmp) / "status.json").read_bytes())
            self.assertIn("timing", status)
            self.assertIn("extract", status["timing"]["stage_ms"])

    def test_slow_bridge_moves_bridge_ms_and_not_our_side(self) -> None:
        """ATTRIBUTION. A slow bridge must make the BRIDGE more expensive, not our parsing.

        The measurement is SINGLE-RUN, and this is essential: the box is shared with prod,
        the spread of `our_ms` between two identical runs reached 300 ms,
        and a test based on the difference between runs would be flaky — that is, an instrument
        that cannot be trusted, in a wave that is about the instrument.

        Instead, the delay is taken to be knowingly GREATER than the real work
        of the fake; the virtual clock runs only in the bridge. Two boundaries of the run
        are checked: the bridge must ACCOMMODATE the inserted time, and our side
        must NOT SPILL INTO it.
        """

        clock = _Clock()
        with TemporaryDirectory() as tmp:
            slow = _SlowBridge(delay_s=SLOW_MS / 1000.0, clock=clock)
            with mock.patch.object(_extract, "time", _ClockShim(clock)):
                self.assertTrue(_decompile(tmp, slow).ok)
            timing = json.loads(
                (Path(tmp) / "run.json").read_bytes())["timing"]

        extract = timing["extract"]
        self.assertGreater(slow.slow_calls, 0, "задержка не сработала")
        injected = SLOW_MS * slow.slow_calls

        # 1. The bridge's bucket ACCOMMODATED the inserted time.  Red if the bridge's
        #    measurement is closed before the response comes back.
        self.assertAlmostEqual(
            extract["bridge_ms"], injected, places=2,
            msg=(f"вставлено {injected:.0f} мс, а bridge_ms = "
                 f"{extract['bridge_ms']:.3f} мс — время утекло мимо ведра моста"))

        # 2. Our side did NOT SPILL INTO it.  Red if parse_ms or
        #    write_ms start being counted from a mark BEFORE the bridge call — it is exactly this
        #    swap of boundaries that turns the breakdown into a lie.
        self.assertEqual(
            extract["our_ms"], 0.0,
            f"our_ms = {extract['our_ms']:.3f} мс при неподвижных часах вне моста")

        # 3. The bridge's share, when the bridge is slow, is overwhelming.
        self.assertAlmostEqual(extract["bridge_ms_share"], 1.0, places=6)

    def test_breakdown_is_per_category_and_survives_resume(self) -> None:
        """The breakdown lives in the checkpoint — a resume does not zero it out."""

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

            # A resume over an already-complete stream hands back the breakdown of THE READ
            # that filled it, not an empty one — otherwise a repeat run would look
            # free.
            again = _decompile(tmp, FakePipelineBridge())
            self.assertTrue(again.ok, again.error)
            self.assertTrue(
                again.timing["extract"]["by_category"],
                "резюм потерял разбивку извлечения")

    def test_totals_do_not_invent_a_split_we_cannot_make(self) -> None:
        """`our_ms` is exactly parse+write, and nothing beyond that."""

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
        # The bridge's share is computed from bridge+ours, not from the run's wall-clock
        # time: between calls there is window waiting and yielding to the loop, and
        # attributing those to the bridge would mean passing off an estimate as a measurement.
        self.assertAlmostEqual(totals["bridge_ms_share"], 1000 / 1200, places=3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
