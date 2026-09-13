"""AN UNREAD INDEX IS NOT "NOTHING TO ISOLATE" (the MUTE_SOURCES debt).

🔴 WHY THIS IS COSTLY. Isolation exists so that the blast radius of a
refusal equals ONE group. `_isolation_from_artifacts` returned an empty
set for FOUR different reasons, all under ONE appearance; two of the four
were not really an answer. Silently failing to isolate means silently
falling back to the radius of the entire package, and in the report
`isolated_groups: 0` is indistinguishable from an honest zero: it is a
NUMBER, and it cannot name the reason for the emptiness.

🔴 THE QUESTION ASKED HERE FIRST: is the bare value itself the ANSWER. Of
the four reasons, TWO are — yes, and they remain mute BY RIGHT:

    the caller named the composition itself     -> AN ANSWER
    the index was read, nothing to isolate      -> AN ANSWER
    no decompile directory was supplied         -> "was not asked"
    the index was NOT READ (OSError/ValueError) -> NOT an answer, and it is costly

So TWO of the four reasons are fixed, not all of them: a blind fix of
"always name the reason" would turn a legitimate answer into noise.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

import kir.idempotence as K


class НепрочитанныйИндексНеЕстьПустаяИзоляция(unittest.TestCase):

    def test_явный_состав_остаётся_немым_по_праву(self):
        множество, причина = K._isolation_source("/nonexistent", ["A", "B"])
        self.assertEqual(множество, frozenset({"A", "B"}))
        self.assertEqual(причина, "", "у ответа не должно быть оговорки")

    def test_прочитанный_индекс_без_витражей_остаётся_немым_по_праву(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "curtain.index.json").write_text(json.dumps({"rows": []}),
                                              encoding="utf-8")
        множество, причина = K._isolation_source(str(d), None)
        self.assertEqual(множество, frozenset())
        self.assertEqual(причина, "",
                         "прочитанный индекс — ОТВЕТ, оговорка тут лишняя")

    def test_непрочитанный_индекс_называет_причину(self):
        """THE MAIN ASSERTION: a read failure must SPEAK."""
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "curtain.index.json").write_text("{это не json", encoding="utf-8")
        множество, причина = K._isolation_source(str(d), None)
        self.assertEqual(множество, frozenset())
        self.assertTrue(причина, "провал чтения индекса промолчал")
        self.assertIn("НЕ ПРОЧИТАН", причина)
        self.assertIn("радиус отказа", причина,
                      "причина не называет ЦЕНЫ: читатель не поймёт, чем "
                      "молчание ему обошлось")

    def test_отсутствующий_индекс_не_выдаёт_себя_за_замер(self):
        d = pathlib.Path(tempfile.mkdtemp())
        множество, причина = K._isolation_source(str(d), None)
        self.assertEqual(множество, frozenset())
        self.assertIn("НЕ РАЗЛИЧИТЬ", причина,
                      "«витражей нет» и «ступень не снималась» слиты в один "
                      "факт о здании")

    def test_две_пустоты_различимы_ТЕКСТОМ_а_не_только_наличием(self):
        """Without this, "a reason is present" would be satisfied by one
        phrase for every cause — the same mute value, just in words."""
        d = pathlib.Path(tempfile.mkdtemp())
        нет_файла = K._isolation_source(str(d), None)[1]
        (d / "curtain.index.json").write_text("{битый", encoding="utf-8")
        не_прочитан = K._isolation_source(str(d), None)[1]
        self.assertNotEqual(нет_файла, не_прочитан,
                            "два разных повода печатаются одной фразой")

    def test_подпись_обёртки_не_менялась(self):
        """Neighbors (`test_isolated_chunk`) call the old name and cut the
        source by it. The wrapper is kept ON PURPOSE, and this assertion
        is its guard."""
        self.assertEqual(K._isolation_from_artifacts(None, None), frozenset())
        self.assertEqual(
            K._isolation_from_artifacts("/nonexistent", ["A", "B"]),
            frozenset({"A", "B"}))


if __name__ == "__main__":
    unittest.main()
