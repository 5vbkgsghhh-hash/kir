"""PUSH — a nudge instead of polling. AN ALARM, not data.

MEASURED 11.08.2026, latency from WRITING a program to its appearance on
screen:

    BEFORE (polling once per 1.5 s):  0…1500 ms, average 750
    AFTER:                             alarm delivery 0.09 ms (median,
                                       max 0.23) + delta fetch 4.6 ms =
                                       ~4.7 ms

That is, ~160x. And the latency stopped being a protocol property: the
server knows about a new program the instant it wrote it, and now says
so immediately.
"""

import asyncio
import unittest

from kir.live import journal as _journal
from kir.live import plan_stream as _plan_stream
from kir.viewer import push as P


def _wall(i):
    return {"op": "create_wall", "id": f"w{i}", "p0_mm": [0.0, i * 300.0],
            "p1_mm": [9000.0, i * 300.0], "height_mm": 3200.0,
            "level": {"by": "name", "value": "L1"}}


class _Sock:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class PushBase(unittest.TestCase):
    DEVICE, DOC = "тест-толчок", "тест-док"

    def setUp(self):
        self.key = _journal.key_for(self.DEVICE, self.DOC)
        _journal.reset(self.key)
        P.reset()


class TheWakeUpCarriesANumberNotAScene(PushBase):
    """No data travels over the channel. The nudge carries a number, and
    the client fetches the scene with its own cursor and its own base
    signature — so there is nothing it could use to weaken the delta
    contract: there is nothing to substitute."""

    def test_the_payload_says_it_is_only_a_wake_up(self):
        async def run():
            sock = _Sock()
            P.connect(self.key, sock)
            _plan_stream.publish(device_id=self.DEVICE, doc_key=self.DOC,
                                 program={"ops": [_wall(0)]})
            for _ in range(500):
                if sock.sent:
                    break
                await asyncio.sleep(0.001)
            return sock.sent
        sent = asyncio.run(run())
        self.assertTrue(sent, "будильник не доехал")
        payload = sent[-1]
        self.assertEqual(payload["type"], "kir_scene")
        self.assertTrue(payload["wake_only"])
        self.assertIn("seq", payload)
        # THE SCENE IS NOT IN IT, and this is checked, not assumed.
        for forbidden in ("elements", "buffers", "honesty", "proposals"):
            self.assertNotIn(forbidden, payload)


class PollingIsNotThrownAway(PushBase):
    """A client with a dropped socket must catch up by cursor, not stay
    with the old building. Push is an acceleration, not the only path."""

    def test_publishing_without_a_subscriber_is_counted_not_lost(self):
        _plan_stream.publish(device_id=self.DEVICE, doc_key=self.DOC,
                             program={"ops": [_wall(0)]})
        stats = P.stats()
        self.assertEqual(stats["notified"], 0)
        self.assertGreater(stats["no_subscriber"], 0)

    def test_the_program_still_reaches_the_journal(self):
        """The nudge didn't arrive — the program is written regardless.
        Otherwise push would become the only path, and it must not be."""
        _plan_stream.publish(device_id=self.DEVICE, doc_key=self.DOC,
                             program={"ops": [_wall(0)]})
        session = _journal.get(self.key)
        self.assertIsNotNone(session)
        self.assertEqual(session.next_seq, 1)

    def test_the_switch_off_leaves_the_old_behaviour(self):
        """Push turned off = the behavior before this wave: the client
        polls and loses nothing, it just waits longer."""
        import os
        previous = os.environ.get(P._FLAG)
        os.environ[P._FLAG] = "0"
        try:
            P.connect(self.key, _Sock())
            P.notify(self.DEVICE, self.DOC, 7)
            self.assertGreater(P.stats()["disabled"], 0)
            self.assertEqual(P.stats()["notified"], 0)
        finally:
            if previous is None:
                os.environ.pop(P._FLAG, None)
            else:
                os.environ[P._FLAG] = previous


class ThereIsOnlyOneCursor(PushBase):
    """`seq` grows in exactly one place — `journal.append` inside
    `plan_stream.publish`. Here the number is only PASSED ALONG."""

    def test_push_is_notified_from_the_single_place_seq_grows(self):
        import inspect
        source = inspect.getsource(_plan_stream.publish)
        self.assertIn("_push.notify", source)
        self.assertIn("record.seq", source)

    def test_push_does_not_keep_its_own_cursor(self):
        """The nudge has no cursor of its own and must not have one: two
        cursors for one session is exactly the pair we spent the whole
        marathon removing."""
        import inspect
        source = inspect.getsource(P)
        self.assertNotIn("next_seq", source)
        self.assertNotIn("indexed_upto", source)

    def test_the_session_key_is_the_journal_one(self):
        """A third way to name one session would drift from the first two."""
        # 27.08.2026: the viewer socket is a HOST route, the language
        # does not have one. A port, not a product name; without a
        # host — a SKIP with a named reason, not a vacuous green "no
        # third way to name the session was found".
        import inspect
        from kir import ports as _п
        try:
            _вьюер = _п.need(_п.VIEWER_ROUTE)
        except _п.PortMissing as _exc:                      # pragma: no cover
            self.skipTest("маршрут вьюера — у хоста: " + str(_exc))
        self.assertIn("key_for", inspect.getsource(_вьюер.viewer_socket))


class BoundednessFollowsTheDrawersLaw(PushBase):
    """A queue with a cap; once it overflows, a nudge is DROPPED and
    counted. A dropped nudge costs a delay until the next poll, not a
    program."""

    def test_the_queue_has_a_ceiling(self):
        self.assertGreaterEqual(P._queue_max(), 1)
        self.assertLessEqual(P._queue_max(), 1024)

    def test_notify_never_raises_on_junk(self):
        """A nudge has no right to cost a turn — the same three
        properties as `publish` itself: synchronous, bounded, fail-open."""
        for junk in (None, "", object()):
            P.notify(junk, "док", 1)
        P.notify("d", "k", "не число")

    def test_stats_name_every_way_a_wake_up_can_be_lost(self):
        stats = P.stats()
        for key in ("notified", "sent", "dropped", "send_errors",
                    "no_subscriber", "disabled"):
            self.assertIn(key, stats)


class ADeadSocketIsDroppedNotRetriedForever(PushBase):

    def test_a_failing_socket_is_disconnected(self):
        class Broken:
            async def send_json(self, payload):
                raise RuntimeError("сокет закрыт")

        async def run():
            P.connect(self.key, Broken())
            _plan_stream.publish(device_id=self.DEVICE, doc_key=self.DOC,
                                 program={"ops": [_wall(0)]})
            for _ in range(500):
                if P.stats()["send_errors"]:
                    break
                await asyncio.sleep(0.001)
        asyncio.run(run())
        self.assertGreater(P.stats()["send_errors"], 0)
        self.assertEqual(P.subscribers(self.key), 0)
