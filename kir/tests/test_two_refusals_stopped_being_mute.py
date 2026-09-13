"""TWO REFUSALS WHERE THE KNOWLEDGE LAY IN A FIELD, WHILE THE TEXT STAYED SILENT.

A measurement by `tools/refusal_muteness.py` on a probe of 47 real refusals (23.08.2026)
found 8 mute ones. Six of them are Python sandbox errors, and almost all of them already
name the move in their own words. But two were our own named form:

    KIR-P002  `candidates` was filled with ALL the names in the language,
              the text — «неизвестный op 'x'» and nothing more;
    KIR-P006  `op_id` and `field_name` are filled in, the text — the two words «дубликат id».

After the fix: 8 → 6 mute (17.0% → 12.8%) on the same probe.

🔴 WHAT IS GUARDED HERE IS NOT THE WORDING, BUT THREE THINGS: the CULPRIT is named,
THE NEXT MOVE is named, and the knowledge from the fields MADE IT into the text. A test on the
verbatim text would forbid improving the wording — and that is exactly what we are engaged in.
"""
import unittest

from kir import compiler, spec


def _refuse(ops):
    out = compiler.compile_program({"ops": ops})
    assert not out.ok, "программа обязана быть отвергнута"
    return out.diagnostics


class UnknownOpNamesWhereToLook(unittest.TestCase):
    def test_it_offers_names_instead_of_only_refusing(self):
        d = next(x for x in _refuse([{"op": "create_wal", "id": "a"}])
                 if str(x.code) == "KIR-P002")
        msg = d.message_ru or ""
        self.assertIn("create_wall", msg,
                      "ближайшее по написанию имя не названо")
        self.assertIn("СЛЕДУЮЩИЙ ХОД", msg)
        self.assertIn("op_names()", msg,
                      "не сказано, чем взять ПОЛНЫЙ перечень")
        self.assertIn(str(len(spec.OPS)), msg,
                      "число имён должно считаться, а не быть литералом")

    def test_the_full_roster_stays_in_the_field_not_in_the_text(self):
        """A CONTROL AGAINST THE OPPOSITE EXTREME: dumping all the names as a wall is also bad.
        The full roster stays in `candidates`, only the closest matches go into the text."""
        d = next(x for x in _refuse([{"op": "no_such_op", "id": "a"}])
                 if str(x.code) == "KIR-P002")
        self.assertEqual(sorted(d.candidates or []), sorted(spec.OPS))
        named = sum(1 for n in spec.OPS if n in (d.message_ru or ""))
        self.assertLessEqual(named, 8, "имена вывалены стеной вместо ближайших")


class DuplicateIdNamesBothPlaces(unittest.TestCase):
    def test_it_names_the_id_the_first_op_and_the_move(self):
        d = next(x for x in _refuse([
            {"op": "create_level", "id": "L", "name": "Э1", "elevation_mm": 0},
            {"op": "create_level", "id": "L", "name": "Э2", "elevation_mm": 3300},
        ]) if str(x.code) == "KIR-P006")
        msg = d.message_ru or ""
        self.assertIn("'L'", msg, "не назван сам дублирующийся id")
        self.assertIn("0", msg, "не назван индекс ПЕРВОГО опа с этим id")
        self.assertIn("СЛЕДУЮЩИЙ ХОД", msg)
        self.assertIn("by_ref", msg,
                      "не сказано, ЧЕМ дубликат опасен — а он ломает адресацию")

    def test_the_first_index_is_the_first_one_not_the_last(self):
        """Three ops with one id: both refusals must point at the FIRST one (#0),
        otherwise the author fixes in a circle — the second one will point at the second."""
        ds = [x for x in _refuse([
            {"op": "create_level", "id": "L", "name": "Э1", "elevation_mm": 0},
            {"op": "create_level", "id": "L", "name": "Э2", "elevation_mm": 3300},
            {"op": "create_level", "id": "L", "name": "Э3", "elevation_mm": 6600},
        ]) if str(x.code) == "KIR-P006"]
        self.assertEqual(len(ds), 2)
        for d in ds:
            self.assertIn("№0", d.message_ru or "")


if __name__ == "__main__":
    unittest.main()


class MixingQueryAndWriteNamesTheSplit(unittest.TestCase):
    """THE THIRD MUTE ONE, CAUGHT BY A LIVE TURN ON 23.08.2026.

    A modify-existing program carried two queries and three writes. The refusal
    said «смешение query и write-опов в одной программе не поддерживается в v1» and fell silent. From this the author learned
    neither what to do, nor that a query does NOT CONSUME a turn: it is the third legitimate kind of response (KIR-B013) and
    costs zero. The refusal sent the author off to rewrite the program where what was needed was
    to split it into two turns.
    """

    def test_it_names_both_sides_and_the_split(self):
        d = next(x for x in _refuse([
            {"op": "query_count", "id": "q", "kind": "wall"},
            {"op": "create_level", "id": "l", "name": "Э1", "elev_mm": 0},
        ]) if str(x.code) == "KIR-L002")
        msg = d.message_ru or ""
        self.assertIn("query_count", msg, "не названо, ЧТО именно читает")
        self.assertIn("create_level", msg, "не названо, ЧТО именно пишет")
        self.assertIn("СЛЕДУЮЩИЙ ХОД", msg)
        self.assertIn("ОТДЕЛЬНЫМ ходом", msg, "не сказано, что делать")
        self.assertIn("не требует", msg,
                      "не сказано, что разведочный ход программы не требует — "
                      "а именно это удерживает автора от лишней переписки")
