"""PUSH — толчок вместо опроса. БУДИЛЬНИК, а не данные.

ЗАМЕР 11.08.2026, задержка от ЗАПИСИ программы до её появления на экране:

    БЫЛО (опрос раз в 1.5 с):  0…1500 мс, в среднем 750
    СТАЛО:                     доставка будильника 0.09 мс (медиана, макс 0.23)
                               + выборка дельты 4.6 мс = ~4.7 мс

То есть ~160x. И задержка перестала быть протокольной: сервер знает про новую
программу в тот момент, когда её записал, и теперь говорит об этом сразу.
"""

import asyncio
import unittest

from kukai.live import journal as _journal
from kukai.live import plan_stream as _plan_stream
from kukai.viewer import push as P


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
    """По каналу не ездят данные. Толчок несёт номер, а сцену клиент забирает
    своим курсором и своей подписью базы — поэтому ослабить договор дельты
    ему нечем: подменять нечего."""

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
        # СЦЕНЫ В НЁМ НЕТ, и это проверяется, а не подразумевается.
        for forbidden in ("elements", "buffers", "honesty", "proposals"):
            self.assertNotIn(forbidden, payload)


class PollingIsNotThrownAway(PushBase):
    """Клиент с упавшим сокетом обязан догнать курсором, а не остаться со
    старым зданием. Push — ускорение, а не единственный путь."""

    def test_publishing_without_a_subscriber_is_counted_not_lost(self):
        _plan_stream.publish(device_id=self.DEVICE, doc_key=self.DOC,
                             program={"ops": [_wall(0)]})
        stats = P.stats()
        self.assertEqual(stats["notified"], 0)
        self.assertGreater(stats["no_subscriber"], 0)

    def test_the_program_still_reaches_the_journal(self):
        """Толчок не дошёл — программа всё равно записана. Иначе push стал бы
        единственным путём, а он им быть не должен."""
        _plan_stream.publish(device_id=self.DEVICE, doc_key=self.DOC,
                             program={"ops": [_wall(0)]})
        session = _journal.get(self.key)
        self.assertIsNotNone(session)
        self.assertEqual(session.next_seq, 1)

    def test_the_switch_off_leaves_the_old_behaviour(self):
        """Выключенный push = поведение до этой волны: клиент опрашивает и
        ничего не теряет, только ждёт дольше."""
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
    """`seq` растёт ровно в одном месте — `journal.append` внутри
    `plan_stream.publish`. Здесь номер только ПЕРЕДАЁТСЯ."""

    def test_push_is_notified_from_the_single_place_seq_grows(self):
        import inspect
        source = inspect.getsource(_plan_stream.publish)
        self.assertIn("_push.notify", source)
        self.assertIn("record.seq", source)

    def test_push_does_not_keep_its_own_cursor(self):
        """Своего курсора у толчка нет и быть не должно: два курсора на одну
        сессию — ровно та пара, которую мы весь марафон убирали."""
        import inspect
        source = inspect.getsource(P)
        self.assertNotIn("next_seq", source)
        self.assertNotIn("indexed_upto", source)

    def test_the_session_key_is_the_journal_one(self):
        """Третий способ назвать одну сессию разъехался бы с первыми двумя."""
        import inspect
        self.assertIn("key_for", inspect.getsource(
            __import__("kukai.api.viewer", fromlist=["viewer_socket"]
                       ).viewer_socket))


class BoundednessFollowsTheDrawersLaw(PushBase):
    """Очередь с потолком; переполнилась — толчок ВЫБРАСЫВАЕТСЯ и считается.
    Выброшенный толчок стоит задержки до следующего опроса, а не программы."""

    def test_the_queue_has_a_ceiling(self):
        self.assertGreaterEqual(P._queue_max(), 1)
        self.assertLessEqual(P._queue_max(), 1024)

    def test_notify_never_raises_on_junk(self):
        """Толчок не имеет права стоить хода — те же три свойства, что у
        самого `publish`: синхронный, ограниченный, fail-open."""
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
