"""FOLDING REPETITION IN THE RECEIPT: identical — once, different —
still kept apart.

The module under test was set up by a measurement on 21.08.2026: a
receipt for 100 walls weighs 85 046 characters, and 44 of 85 kilobytes
are one fact repeated a hundred times (`resolved_refs`, 100 records,
substantively ONE different; the same for `grounding_report`;
`defaults_note_ru` — one phrase a hundred times).

Three assertions are guarded here, and the second matters more than the
first:

1. the identical is folded;
2. 🔴 **THE DIFFERENT IS NEVER FOLDED** — a fold that eats a difference
   is worse than a long receipt: a long one is read diagonally, while a
   short and wrong one reads as the truth;
3. not a single `op_id` disappears — the canon forbids silent
   truncation.
"""
from __future__ import annotations

import json
import unittest

from kir import receipt_fold as RF


def _row(oid: str, **kw):
    row = {"op_id": oid}
    row.update(kw)
    return row


class FoldsTheRepeat(unittest.TestCase):

    def test_identical_rows_become_one_with_the_count(self):
        rows = [_row(f"w{i}", param="level", name="Уровень 1") for i in range(100)]
        out, stats = RF.fold_rows(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["applies_to"], 100)
        self.assertEqual(stats, {"rows_in": 100, "rows_out": 1, "folded": 99})

    def test_no_op_id_is_lost(self):
        rows = [_row(f"w{i}", param="level") for i in range(50)]
        out, _ = RF.fold_rows(rows)
        self.assertEqual(sorted(out[0]["op_ids"]),
                         sorted(f"w{i}" for i in range(50)),
                         "канон запрещает молчаливое усечение: свёртка обязана "
                         "перечислить ВСЕ опы, к которым факт относится")
        self.assertNotIn("op_id", out[0],
                         "у свёрнутой записи одного op_id нет — их много")

    def test_a_name_of_the_op_inside_a_string_does_not_block_folding(self):
        """🔴 THE SIGNATURE IS BUILT BY SUBSTITUTION, NOT BY A LIST OF
        FIELDS TO DISCARD.

        For `grounding_report` the `read_from` field carries
        `result.wall1.type_name` — the op's name sits INSIDE the string,
        and letter for letter such records are all different. A
        handwritten list of fields to discard would go out of sync with
        the data on the very first new field that also mentions the op.
        """
        rows = [_row(f"wall{i}", rule="doc_default",
                     read_from=f"result.wall{i}.type_name") for i in range(30)]
        out, stats = RF.fold_rows(rows)
        self.assertEqual(len(out), 1, json.dumps(out, ensure_ascii=False)[:400])
        self.assertEqual(stats["folded"], 29)


class ЧужаяФормаДержитСВОЁМесто(unittest.TestCase):
    """🔴 ORDER IS PART OF THE CONTRACT, AND IT WAS BEING VIOLATED (F-368,
    30.08.2026).

    The `fold_rows` header declares: "order is preserved by FIRST
    occurrence: the author reads the receipt top to bottom, and
    reordering records would change the story about the program."
    Records of a foreign shape, however, were being accumulated into a
    separate list and appended AFTER all the groups — meaning a note
    that stood BETWEEN two folded ones would move to the end.

    🔴 THE DEFECT WAS INVISIBLE BY THE COUNTERS: `rows_in == rows_out`,
    `folded == 0`, not a single record lost. Only the MEANING changed —
    and so no existing test caught it.
    """

    @staticmethod
    def _вид(out):
        return [r if isinstance(r, str)
                else ("группа:" + ",".join(r.get("op_ids", []))
                      if r.get("op_ids") else "одна:" + str(r.get("op_id")))
                for r in out]

    def test_a_note_between_two_rows_stays_between_them(self):
        вход = [{"op_id": "A", "m": 1}, "ПРИМЕЧАНИЕ-МЕЖДУ", {"op_id": "B", "m": 2}]
        out, stats = RF.fold_rows(вход)
        self.assertEqual(self._вид(out),
                         ["одна:A", "ПРИМЕЧАНИЕ-МЕЖДУ", "одна:B"])
        # And the counters are the same — exactly why the defect was invisible.
        self.assertEqual(stats, {"rows_in": 3, "rows_out": 3, "folded": 0})

    def test_a_group_takes_the_place_of_its_FIRST_member(self):
        """A group lands where it FIRST occurred — this is what "by
        first occurrence" means, not "at the end" and not "wherever the
        last one is"."""
        вход = [_row("W1", param="type", name="Т"), "ЗАМЕТКА",
                _row("W2", param="type", name="Т"), _row("W3", param="type", name="Т")]
        out, stats = RF.fold_rows(вход)
        self.assertEqual(self._вид(out), ["группа:W1,W2,W3", "ЗАМЕТКА"])
        self.assertEqual(stats["folded"], 2)

    def test_a_foreign_row_first_and_last_keeps_its_end(self):
        сверху, _ = RF.fold_rows(["ШАПКА", _row("W1", param="type", name="Т"),
                                  _row("W2", param="type", name="Т")])
        снизу, _ = RF.fold_rows([_row("W1", param="type", name="Т"),
                                 _row("W2", param="type", name="Т"), "ХВОСТ"])
        self.assertEqual(self._вид(сверху)[0], "ШАПКА")
        self.assertEqual(self._вид(снизу)[-1], "ХВОСТ")

    def test_nothing_is_dropped_or_duplicated(self):
        """NARROWNESS CONTROL: keeping the order does not mean losing or duplicating."""
        вход = ["A", _row("W1", param="type", name="Т"), "B",
                _row("W2", param="type", name="Т"), "C"]
        out, stats = RF.fold_rows(вход)
        self.assertEqual([r for r in out if isinstance(r, str)], ["A", "B", "C"])
        self.assertEqual(stats["rows_in"], 5)


class СвёрнутаяЗаписьЕстьШаблонИОнаОбратима(unittest.TestCase):
    """🔴 THE SIGNATURE WAS COMPARING TEMPLATES, WHILE AN INSTANCE WAS
    BEING PRINTED (F-367, 29.08.2026).

    Where a record's own `op_id` sits INSIDE the value, two records
    about DIFFERENT facts produced one signature, and the raw body of
    the FIRST one traveled into the receipt. The live form is
    `grounding_report`: `chosen.name` carries a type name READ FROM THE
    BUILT ELEMENT. A human would read one type where Revit had applied
    two, while right next to it stood "not a single op_id is lost" — a
    truth about a DIFFERENT subject.
    """

    @staticmethod
    def _строка(oid, имя):
        return {"op_id": oid, "field": "type", "rule": "doc_default",
                "chosen": {"id": None, "name": имя, "resolved_at": "revit",
                           "source": "readback",
                           "read_from": f"result.{oid}.type_name"}}

    @staticmethod
    def _развернуть(body, oid):
        """Substituting `op_ids[i]` for the marker must give back the original string."""
        def sub(v):
            if isinstance(v, str):
                return v.replace(RF.OP_PLACEHOLDER, oid)
            if isinstance(v, dict):
                return {k: sub(x) for k, x in v.items()}
            if isinstance(v, list):
                return [sub(x) for x in v]
            return v
        out = {k: sub(v) for k, v in body.items()
               if k not in ("applies_to", "op_ids", "op_id_placeholder")}
        out["op_id"] = oid
        return out

    def test_a_collision_prints_a_template_not_the_first_instance(self):
        """THE MARK: the op is named by a mark, and the same mark sits in the type name."""
        rows = [self._строка("S1", "Стеклопакет S1-2100"),
                self._строка("S2", "Стеклопакет S2-2100")]
        out, _ = RF.fold_rows(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["chosen"]["name"], "Стеклопакет «op_id»-2100")
        self.assertNotIn("S1-2100", json.dumps(out, ensure_ascii=False),
                         "в квитанцию уехало имя ОДНОГО опа как общее")

    def test_the_template_is_reversible_for_every_op(self):
        """The header's promise "nothing is lost" is a PROPERTY, not an intention."""
        for имя, пары in (
            ("МАРКА", (("S1", "Стеклопакет S1-2100"),
                       ("S2", "Стеклопакет S2-2100"))),
            ("ЦИФРА", (("1", "Кирпич 100мм"), ("2", "Кирпич 200мм"))),
        ):
            rows = [self._строка(o, n) for o, n in пары]
            out, _ = RF.fold_rows(rows)
            self.assertEqual(len(out), 1, имя)
            for i, oid in enumerate(out[0]["op_ids"]):
                with self.subTest(случай=имя, op_id=oid):
                    self.assertEqual(self._развернуть(out[0], oid), rows[i])

    def test_a_folded_row_says_that_it_is_a_template(self):
        """A reader must learn about the substitution FROM THE RECORD
        ITSELF: the module's docstring is not in front of their eyes."""
        rows = [self._строка("S1", "Стеклопакет S1-2100"),
                self._строка("S2", "Стеклопакет S2-2100")]
        out, _ = RF.fold_rows(rows)
        self.assertEqual(out[0]["op_id_placeholder"], RF.OP_PLACEHOLDER)

    def test_a_TRUE_repeat_reads_exactly_as_before(self):
        """🔴 A NARROWNESS CONTROL, and it matters more than the others: a
        hundred walls of ONE type is exactly what this module was
        written for. Its text must stay unchanged, otherwise fixing the
        lie was paid for by breaking what already worked."""
        rows = [self._строка(f"W{i}", "Типовой - 200мм") for i in range(100)]
        out, stats = RF.fold_rows(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["chosen"]["name"], "Типовой - 200мм")
        self.assertEqual(out[0]["applies_to"], 100)
        self.assertEqual(stats["folded"], 99)

    def test_a_single_row_carries_no_placeholder(self):
        """A record encountered once is returned AS IS — the branch is
        untouched, and there should be no mark in it."""
        out, _ = RF.fold_rows([self._строка("S1", "Стеклопакет S1-2100")])
        self.assertEqual(out[0]["chosen"]["name"], "Стеклопакет S1-2100")
        self.assertNotIn("op_id_placeholder", out[0])


class DoesNotFoldWhatDiffers(unittest.TestCase):
    """The second half of the fix — its own control."""

    def test_two_different_choices_stay_two_records(self):
        rows = ([_row(f"a{i}", param="type", name="Кирпич 380") for i in range(40)]
                + [_row(f"b{i}", param="type", name="Гипс 100") for i in range(60)])
        out, stats = RF.fold_rows(rows)
        self.assertEqual(len(out), 2,
                         "два разных выбора обязаны остаться двумя записями, "
                         "сколько бы их ни было")
        self.assertEqual({o["applies_to"] for o in out}, {40, 60})
        self.assertEqual(stats["rows_out"], 2)

    def test_a_single_row_is_returned_untouched(self):
        rows = [_row("w1", param="level", name="Уровень 1")]
        out, stats = RF.fold_rows(rows)
        self.assertEqual(out, rows)
        self.assertNotIn("applies_to", out[0],
                         "запись, встретившаяся один раз, не обязана нести "
                         "счётчик — он был бы шумом")
        self.assertEqual(stats["folded"], 0)

    def test_order_follows_the_first_appearance(self):
        rows = [_row("a", k="первый"), _row("b", k="второй"),
                _row("c", k="первый")]
        out, _ = RF.fold_rows(rows)
        self.assertEqual([o["k"] for o in out], ["первый", "второй"],
                         "автор читает квитанцию сверху вниз; перестановка "
                         "записей меняла бы рассказ о программе")

    def test_a_foreign_shape_is_neither_folded_nor_dropped(self):
        rows = [_row("a", k="x"), "чужая форма", _row("b", k="x")]
        out, _ = RF.fold_rows(rows)
        self.assertIn("чужая форма", out,
                      "форма чужая — значит и правило чужое, но выбрасывать "
                      "её нельзя")


class FoldsTheHumanNote(unittest.TestCase):

    def test_a_sentence_repeated_gets_a_count(self):
        note = "; ".join(["type: «Типовой - 200мм» (умолчание)"] * 100)
        out, stats = RF.fold_sentences(note)
        self.assertIn("×100", out)
        self.assertEqual(stats, {"parts_in": 100, "parts_out": 1})
        self.assertLess(len(out), len(note) / 20)

    def test_different_sentences_survive_and_keep_order(self):
        note = "первое; второе; первое; третье"
        out, stats = RF.fold_sentences(note)
        self.assertEqual(out, "первое ×2; второе; третье")
        self.assertEqual(stats["parts_out"], 3)

    def test_an_empty_note_is_returned_as_is(self):
        for value in ("", "   ", None):
            out, _ = RF.fold_sentences(value)  # type: ignore[arg-type]
            self.assertEqual(out, value)


class TheFoldAnnouncesItself(unittest.TestCase):
    """A reader must learn about the fold FROM THE RECEIPT, not from knowledge of the code."""

    def test_the_note_names_what_was_folded(self):
        note = RF.fold_note_ru([
            ("resolved_refs", {"rows_in": 100, "rows_out": 1, "folded": 99}),
            ("grounding_report", {"rows_in": 100, "rows_out": 1, "folded": 99}),
        ])
        self.assertIn("resolved_refs 100→1", note)
        self.assertIn("grounding_report 100→1", note)
        self.assertIn("ни один op_id не потерян", note)

    def test_nothing_folded_means_no_note(self):
        self.assertEqual(
            RF.fold_note_ru([("resolved_refs",
                              {"rows_in": 3, "rows_out": 3, "folded": 0})]),
            "",
            "примечание о свёртке там, где не свёрнуто ничего, — это шум, "
            "который читается как «квитанция сокращена»")


if __name__ == "__main__":
    unittest.main()
