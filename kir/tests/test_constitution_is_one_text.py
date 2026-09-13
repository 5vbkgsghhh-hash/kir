"""THE CONSTITUTION LIVES IN TWO CANONS AND MUST MATCH BYTE FOR BYTE.

    cd /opt/kir && PYTHONPATH=/opt/kir python3.12 -m pytest -q \\
        kir/tests/test_constitution_is_one_text.py

🔴 WHY THIS FILE IS HERE, AND HOW IT DIFFERS FROM THE TWIN AT THE HOST
(27.08.2026, after the split).

Before the split, both copies of the constitution lived in ONE repository,
and a guard compared them directly. Now the language is a separate
repository (`/opt/kir`), and the second copy stayed in the product's tree.
A consequence that cannot be silenced: **for someone who cloned only KIR,
the second copy DOES NOT EXIST AT ALL**, and there is nothing to compare
against.

The obligation itself has not gone anywhere — it simply split in two:

* **WHAT IS ALWAYS CHECKED** — the structure of ITS OWN copy: the block is
  in place, the law and the metric inside it are alive, the constitution
  stands BEFORE rule zero, the reminder closes the file. This is a
  property of THIS repository and concerns no one else;
* **WHAT IS CHECKED WHEN A NEIGHBOR EXISTS** — a byte-for-byte match. No
  neighbor — A SKIP WITH A NAMED REASON, not a silent green.

🔴 THE DIFFERENCE BETWEEN A SKIP AND A GREEN IS THE ENTIRE POINT OF THIS
SPLIT. A guard that quietly turns green when the neighbor is absent
reports an absence of findings exactly where it went blind; this is form
34 ("fail-open turns a measurement of the refusal into a measurement of
the subject"). A skip IS VISIBLE in the summary, a vacuous green is not.

WHERE THE NEIGHBOR IS SEARCHED FOR (in order, first found wins):

    $KIR_SIBLING_CANON        an explicit pointer — the only portable way
    /opt/kukai-rebuild1/CLAUDE.md   the MACHINE-LOCAL path for this station;
                                    its absence is NOT a defect

IF THE COMPARISON IS RED — edit BOTH files identically. The block is
bounded by the markers `<!-- КОНСТИТУЦИЯ: НАЧАЛО … -->` / `<!-- КОНСТИТУЦИЯ:
КОНЕЦ -->`, and the copy should be made between them, inclusive.

What this test does NOT check: that the text of the constitution is
CORRECT. Correctness is the owner's subject, not the test suite's. Exactly
one thing is checked — that there are not two different copies.
"""
from __future__ import annotations

import os
import unittest


def _kir_canon() -> str:
    """The KIR canon is IN THE PACKAGE, not next to the test.

    The path is asked of the package itself: a constant would mean "we
    remember where it is", and remembering and knowing are different
    things. It was exactly on "steps upward" that the sandbox burned after
    the split (`f518b05`).
    """
    import kir
    return os.path.join(os.path.dirname(os.path.abspath(kir.__file__)),
                        "CLAUDE.md")


KIR_CANON = _kir_canon()

#: The machine-local path to the second copy. Marked as machine-local
#: DELIBERATELY (canon rule: such a path is a station artifact, not part
#: of the project, and its absence is not a defect).
_SIBLING_DEFAULT = "/opt/kukai-rebuild1/CLAUDE.md"


def sibling_canon() -> str | None:
    """The second copy, if one exists on this machine."""
    named = os.environ.get("KIR_SIBLING_CANON")
    if named:
        return named if os.path.isfile(named) else None
    return _SIBLING_DEFAULT if os.path.isfile(_SIBLING_DEFAULT) else None


BEGIN = "<!-- КОНСТИТУЦИЯ: НАЧАЛО"
END = "<!-- КОНСТИТУЦИЯ: КОНЕЦ -->"
REMINDER_BEGIN = "<!-- НАПОМИНАНИЕ КОНСТИТУЦИИ: НАЧАЛО"
REMINDER_END = "<!-- НАПОМИНАНИЕ КОНСТИТУЦИИ: КОНЕЦ -->"

#: The distinguishing law. It stands here IN FULL, because the test must
#: catch its disappearance, not the disappearance of the heading above it.
LAW = ("Всё, что в Ревите устроено так ПОТОМУ ЧТО так устроен ЧЕЛОВЕК, — "
       "для ЛЛМ")
METRIC = "проверяемость ИЗМЕНИЛА решение модели"


def _slice(path: str, begin: str, end: str) -> str | None:
    """The text between the markers, inclusive; `None` means there are no
    markers.

    The absence of the block and a match between blocks are DIFFERENT
    facts, and the first must be visible as a refusal, not as a silent
    "no discrepancies".
    """
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    if begin not in text or end not in text:
        return None
    start = text.index(begin)
    return text[start:text.index(end, start) + len(end)]


class СвояКопияЦелаИСтоитГдеВелено(unittest.TestCase):
    """A property of THIS repository. Always checked, requires no
    neighbor."""

    def test_the_canon_carries_the_block(self):
        self.assertIsNotNone(
            _slice(KIR_CANON, BEGIN, END),
            f"в {KIR_CANON} нет блока конституции между маркерами")

    def test_the_canon_carries_the_tail_reminder(self):
        self.assertIsNotNone(
            _slice(KIR_CANON, REMINDER_BEGIN, REMINDER_END),
            f"в {KIR_CANON} нет хвостового напоминания")

    def test_the_constitution_stands_before_rule_zero(self):
        """«Чтобы было всегда в фокусе»: the constitution is the first
        thing a session reads. What is checked is POSITION, not presence:
        a block that has drifted to the middle remains present, yet
        violates the requirement."""
        text = open(KIR_CANON, encoding="utf-8").read()
        self.assertIn("## RULE ZERO", text, KIR_CANON)
        self.assertLess(text.index(BEGIN), text.index("## RULE ZERO"),
                        f"в {KIR_CANON} конституция стоит ПОСЛЕ правила зеро")

    def test_the_reminder_is_the_last_block_of_the_file(self):
        text = open(KIR_CANON, encoding="utf-8").read().rstrip()
        self.assertTrue(
            text.endswith(REMINDER_END),
            f"{KIR_CANON} не заканчивается напоминанием конституции")

    def test_the_law_and_the_metric_survive_in_the_block(self):
        """A match between the two copies does not help if the law was
        pulled out of BOTH. What is pinned is the subject, not merely
        equality."""
        block = _slice(KIR_CANON, BEGIN, END) or ""
        self.assertIn(LAW, block, "закон-различитель пропал")
        self.assertIn(METRIC, block, "главная метрика пропала")
        reminder = _slice(KIR_CANON, REMINDER_BEGIN, REMINDER_END) or ""
        self.assertIn(LAW, reminder, "в напоминании нет закона")

    def test_the_block_is_not_vacuously_short(self):
        """An empty sample would match itself. Length here is not a
        measure of quality — it is a measure of whether the sample
        captured anything at all."""
        self.assertGreater(len(_slice(KIR_CANON, BEGIN, END) or ""), 2000)


class ДвеКопииСовпадаютПобайтово(unittest.TestCase):
    """🔴 REQUIRES A NEIGHBOR. No neighbor — A SKIP WITH A REASON, not a
    green."""

    def setUp(self):
        self.sibling = sibling_canon()
        if self.sibling is None:
            self.skipTest(
                "второй копии конституции на этой машине нет: она принадлежит "
                "дереву ХОЗЯИНА, а KIR — отдельный репозиторий. Укажи путь "
                "через $KIR_SIBLING_CANON, если сравнение нужно. Пропуск здесь "
                "ЧЕСТНЕЕ зелёного: сравнивать не с чем, и это видно.")

    def test_both_canons_carry_the_block(self):
        self.assertIsNotNone(
            _slice(self.sibling, BEGIN, END),
            f"в {self.sibling} нет блока конституции между маркерами")

    def test_the_two_copies_are_byte_identical(self):
        root = _slice(self.sibling, BEGIN, END)
        kir = _slice(KIR_CANON, BEGIN, END)
        self.assertEqual(root, kir,
                         "копии конституции разошлись — правь ОБА файла")

    def test_the_two_reminders_are_byte_identical(self):
        self.assertEqual(_slice(self.sibling, REMINDER_BEGIN, REMINDER_END),
                         _slice(KIR_CANON, REMINDER_BEGIN, REMINDER_END))


class ТестУмеетПокраснеть(unittest.TestCase):
    """FAIL CONTROL. A comparison that is always green guards nothing."""

    def test_a_single_changed_character_is_caught(self):
        """The mutation is taken from the block ITSELF, not written as a
        literal: a discrepancy between two carriers would make the
        control green by construction (form 8)."""
        block = _slice(KIR_CANON, BEGIN, END)
        self.assertIsNotNone(block)
        mutated = block.replace("ЛЛМ", "ллм", 1)
        self.assertNotEqual(mutated, block, "нечего было менять")

    def test_a_missing_file_is_a_refusal_not_a_match(self):
        """Two absent blocks must NOT read as "the copies matched":
        `None == None` is true, and without this control an empty check
        would be green by construction."""
        self.assertIsNone(_slice("/nonexistent/CLAUDE.md", BEGIN, END))

    def test_the_sibling_probe_says_no_on_a_missing_path(self):
        """A CONTROL ON THE NEIGHBOR SEARCH ITSELF: it must be able to
        answer "no". A resolver that always hands back a path would turn
        an honest skip into a red on an empty file."""
        saved = os.environ.get("KIR_SIBLING_CANON")
        os.environ["KIR_SIBLING_CANON"] = "/nonexistent/CLAUDE.md"
        try:
            self.assertIsNone(sibling_canon())
        finally:
            if saved is None:
                os.environ.pop("KIR_SIBLING_CANON", None)
            else:
                os.environ["KIR_SIBLING_CANON"] = saved


class РукописноеПереживаетПорождаемое(unittest.TestCase):
    """🔴 ONE FILE IS WRITTEN TO BY BOTH A GENERATING INSTRUMENT AND A
    HUMAN.

    `tools/kir_canon_state.py` writes STATE into `kir/CLAUDE.md`, while the
    constitution stands there too, by hand. The instrument replaces the
    text BETWEEN its own markers and is obligated to preserve the `head`
    and `tail` — but this is a property of its implementation, not a law,
    and the very first edit toward "rewrite the whole file" would silently
    wipe out the constitution.

    What is pinned here is exactly the mechanism. `build()` is replaced
    with a stub: the subject of the check is PRESERVING SOMEONE ELSE'S
    TEXT, not the content of the state.
    """

    def test_a_generated_write_preserves_the_handwritten_blocks(self):
        import shutil
        import sys
        import tempfile

        # 🔴 TWO STEPS, NOT THREE, AND THIS WAS PAID FOR RIGHT HERE
        # (27.08.2026). `KIR_CANON` is a FILE: /opt/kir/kir/CLAUDE.md. The
        # first dirname yields the package, the second the repository. A
        # third yielded `/opt`, there is no `tools/` there, the import
        # failed, and the test SILENTLY SKIPPED instead of guarding.
        # Exactly the form on which the sandbox burned after the split
        # (`f518b05`): the root was counted in STEPS UPWARD. We count from
        # where the package actually sits.
        repo = os.path.dirname(os.path.dirname(os.path.abspath(KIR_CANON)))
        tools = os.path.join(repo, "tools")
        assert os.path.isdir(tools), (
            "каталога приборов нет по адресу %r — пропуск здесь скрыл бы "
            "неработающего сторожа" % tools)
        if tools not in sys.path:
            sys.path.insert(0, tools)
        try:
            from kir.instruments import canon_state as state
        except Exception as exc:            # noqa: BLE001
            self.skipTest(f"прибор состояния недоступен: {type(exc).__name__}")

        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "CLAUDE.md")
            shutil.copy(KIR_CANON, copy)
            original_build = state.build
            state.build = lambda: (state.BEGIN + "\nЗАГЛУШКА\n" + state.END)
            try:
                state.write_into(copy)
            finally:
                state.build = original_build

            text = open(copy, encoding="utf-8").read()
            self.assertIn("ЗАГЛУШКА", text, "прибор не вписал свой блок")
            self.assertIn(BEGIN, text, "порождаемая запись снесла конституцию")
            self.assertTrue(text.rstrip().endswith(REMINDER_END),
                            "порождаемая запись снесла напоминание")
            # The order is the owner's requirement, not a matter of taste.
            self.assertLess(text.index(BEGIN), text.index("ЗАГЛУШКА"))
            self.assertLess(text.index("ЗАГЛУШКА"), text.index("## RULE ZERO"))


if __name__ == "__main__":
    unittest.main()
