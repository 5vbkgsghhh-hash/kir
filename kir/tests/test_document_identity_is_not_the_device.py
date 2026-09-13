"""THE LIVE JOURNAL'S KEY IS (DEVICE, DOCUMENT), NOT A SINGLE DEVICE.

🔴 WHY THIS FILE. The owner ROUTINELY has two Revits open on one machine —
this is recorded in the mandate's p.19 and has already been paid for twice: first by the window
choice ("a coin flip"), then by a building index that was assembled from the title of the WRONG
window. Both times the fix was the same — ask whoever CHOSE the document. The live journal
was NOT wired to this carrier: `journal.key_for(device_id, doc_key="")`
accepts a document, but `serving` was not passing it, and two programs for different buildings
were landing in ONE record.

WHY THIS CLASS IS MORE EXPENSIVE THAN THE OTHERS. Every other refusal in this tree is LOUD:
typed code, a cause, a next move. The wrong-address error is the only one
that gives a confident, correctly-looking answer about the WRONG building. None of
the defenses built so far work against it, because all of them check whether it was done
right, and none of them check whether it was done for the right thing.

TWO OUTCOMES OF ONE CAUSE, and the second was found only by measurement:
  * TWO BUILDINGS IN ONE RECORD — the verdict about building B counts building A's programs;
  * AN EMPTY SCENE ON A NON-EMPTY GRANT — the readers (`viewer/live_scene.py:217,811`,
    `viewer/compilability.py:297`) pass `doc_key` HONESTLY, the writer wrote with an
    empty one. A reader with the real document name found NOTHING and honestly
    stayed silent — meaning the refusal looked like «здание пустое».

THE FAIL CONTROL WAS RUN BY HAND, AND WITHOUT IT THIS FILE WOULD MEAN NOTHING:
on the code before the fix, `test_two_documents_do_not_share_one_key` gives
`('dev-1', '') == ('dev-1', '')` — meaning it turns red FOR THE RIGHT REASON, not for
the function's absence.
"""
from __future__ import annotations

import unittest

from kir import ports
from kir import serving
from kir.live import journal as live_journal


class _ХодОдногоДокумента:
    """The `TURN_CONTEXT` port provider — exactly the two facts a turn asks for.

    The shape repeats the REAL provider, not the reader's shape: `serving`
    asks `get_active_device_id()` and `turn_document_title()`, and the double
    is required to answer the same calls. A double that repeats the reader's shape is green
    for any value on either side (form 48).
    """

    def __init__(self, device: str, document: str) -> None:
        self._device = device
        self._document = document

    def get_active_device_id(self) -> str:
        return self._device

    def turn_document_title(self) -> str:
        return self._document


class ДокументВходитВКлюч(unittest.TestCase):
    """The key must distinguish documents belonging to the same device."""

    DEVICE = "dev-1"

    def setUp(self) -> None:
        self.addCleanup(ports.unregister, ports.TURN_CONTEXT)
        live_journal.reset()
        self.addCleanup(live_journal.reset)

    def _ключ_хода(self, document: str):
        ports.register(
            ports.TURN_CONTEXT,
            lambda: _ХодОдногоДокумента(self.DEVICE, document))
        key, _seen = serving._building_watch()
        return key

    def test_two_documents_do_not_share_one_key(self) -> None:
        """TWO DOCUMENTS — TWO KEYS. That is the entire defect class."""
        a = self._ключ_хода("K3_АР.rvt")
        b = self._ключ_хода("K6_КР.rvt")
        self.assertNotEqual(
            a, b,
            "ключ журнала не различает документы одного устройства: "
            f"{a} == {b} — программы двух зданий лягут в одну запись")

    def test_the_key_carries_the_document_the_turn_declared(self) -> None:
        """The key carries EXACTLY the declared document, not just any difference.

        Without this assertion, the previous test would also pass on a mere counter: two different
        keys are not the same thing as two CORRECT keys.
        """
        self.assertEqual(self._ключ_хода("K3_АР.rvt"),
                         (self.DEVICE, "K3_АР.rvt"))

    def test_a_turn_without_a_document_still_yields_a_key(self) -> None:
        """The absence of a name does NOT break the turn — it produces the previous empty key.

        This is not a relaxation: a chat path without a declared document already existed
        before the fix, and a turn has no right to fail because of the showroom. An empty name here is
        an honest "didn't name one," distinguishable from "named a different one."
        """
        self.assertEqual(self._ключ_хода(""), (self.DEVICE, ""))


class ЖурналРазделяетЗдания(unittest.TestCase):
    """A consequence of the key: one building's record is not visible from another."""

    DEVICE = "dev-1"

    def setUp(self) -> None:
        live_journal.reset()
        self.addCleanup(live_journal.reset)

    def test_a_program_of_one_document_is_invisible_from_the_other(self) -> None:
        программа = [{"op": "create_wall", "id": "W1"}]
        ключ_a = live_journal.key_for(self.DEVICE, "K3_АР.rvt")
        ключ_b = live_journal.key_for(self.DEVICE, "K6_КР.rvt")

        live_journal.append(ключ_a, программа, source="test")

        сессия_b = live_journal.get(ключ_b)
        держит_b = 0 if сессия_b is None else len(сессия_b.records)
        self.assertEqual(
            держит_b, 0,
            "программа здания A видна из здания B — ключ не разделяет")

        сессия_a = live_journal.get(ключ_a)
        self.assertIsNotNone(сессия_a)
        self.assertEqual(len(сессия_a.records), 1)


class КлючСчитаетсяВОДНОММЕСТЕ(unittest.TestCase):
    """CLOSING THE LIST: the turn's key has ONE author, or the defect will CHANGE SHAPE.

    🔴 WHY SEPARATELY. Fixing `publish` while leaving `_TURN_JOURNAL_SLOT`
    to compute the key its own way would mean splitting WRITE apart from READ: the write would land
    under the document, while the outcome would keep being appended under an empty key, and the stage
    would stay `planned` forever. This is not a hypothesis — this is exactly how `key_for` describes
    its own meaning in its docstring: "the writer and the readers are required to land in one
    record… they would drift apart SILENTLY."

    THE BOUNDARY OF THIS TEST IS NAMED, NOT LEFT UNSAID: it reads the SOURCE and therefore
    sees only static calls. It will not catch a dynamic call. It
    closes the list, it does not prove behavior — behavior is proven by the tests
    above.
    """

    def test_serving_computes_the_journal_key_in_exactly_one_place(self) -> None:
        import inspect
        import re

        источник = inspect.getsource(serving)
        # Calls to `key_for(` outside the body of the sole author — that is a second author.
        строки = [
            (n, s) for n, s in enumerate(источник.splitlines(), 1)
            if re.search(r"\bkey_for\s*\(", s)
        ]
        внутри_автора = [
            n for n, _ in строки
            if _в_теле_автора(источник, n)
        ]
        чужие = [(n, s.strip()) for n, s in строки
                 if n not in внутри_автора]
        self.assertEqual(
            чужие, [],
            "ключ журнала считается не только в `_turn_journal_key`: "
            f"{чужие} — второй автор разъедется с первым молча")


def _в_теле_автора(источник: str, номер: int) -> bool:
    """Whether the line lies inside `def _turn_journal_key`."""
    строки = источник.splitlines()
    начало = None
    for i, s in enumerate(строки, 1):
        if s.startswith("def _turn_journal_key"):
            начало = i
            break
    if начало is None:
        return False
    for i in range(начало + 1, len(строки) + 1):
        s = строки[i - 1]
        if s and not s[0].isspace() and not s.startswith(")"):
            конец = i
            break
    else:
        конец = len(строки) + 1
    return начало <= номер < конец


if __name__ == "__main__":
    unittest.main()
