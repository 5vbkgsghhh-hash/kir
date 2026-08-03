"""Execution-lifecycle contract for decompile CPU offloads."""
from __future__ import annotations

import asyncio
import threading
import time
import unittest

from kukai.ir.decompile.pipeline import _offload


def _observe_thread(
    value: str,
    *,
    suffix: str,
    delay: float = 0.0,
) -> tuple[str, int]:
    time.sleep(delay)
    return value + suffix, threading.get_ident()


class PipelineOffloadLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_sequential_steps_both_finish_off_loop(self) -> None:
        """A sleeping worker from step one must not strand step two."""

        event_loop_thread = threading.get_ident()
        first = await asyncio.wait_for(
            _offload(
                _observe_thread, "first", suffix="-ok", delay=0.05,
            ),
            timeout=2.0,
        )
        second = await asyncio.wait_for(
            _offload(
                _observe_thread, "second", suffix="-ok", delay=0.05,
            ),
            timeout=2.0,
        )

        self.assertEqual(first[0], "first-ok")
        self.assertEqual(second[0], "second-ok")
        self.assertNotEqual(first[1], event_loop_thread)
        self.assertNotEqual(second[1], event_loop_thread)


if __name__ == "__main__":
    unittest.main()
