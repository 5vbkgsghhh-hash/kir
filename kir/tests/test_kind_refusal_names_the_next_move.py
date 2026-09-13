"""A REFUSAL ON `kind` MUST NAME THE NEXT MOVE — INCLUDING THE CASE "FIELD
NOT WRITTEN."

THE MEASUREMENT THIS FILE GREW FROM (16.08.2026, the night rig + the
production corpus `data/telemetry/kir_rejections.jsonl`, 1959 lines, 295 of
them in night windows):

* a refusal repeated within ONE turn in **38 of 164 turns** — almost a
  quarter of turns, the refusal taught nothing;
* the champion of failing to teach — `KIR-G001 count.kind`, **16 repeats**,
  and **11 of 21** night refusals of this kind carry `kind None`, meaning
  the field was not written at all;
* the text was exactly "unknown kind None": three words, no cause, no move.

The cause lay in one line: the whole name-resolution ladder and the whole
closed list hung on `isinstance(kind, str)`. The hint worked when the
author made a TYPO, and stayed silent when they SIMPLY DIDN'T WRITE the
field.

Four inputs — four DIFFERENT answers, and that is an act of distinguishing,
not one green:

    field not written    -> "field kind not written" + the whole closed list + a move
    field not a string   -> the received TYPE is named + the same list
    a different spelling -> NO REFUSAL, the ladder resolves it ("walls" -> "wall")
    unfamiliar name       -> the NEIGHBOR is named, not the whole list

THE FAIL CONTROL WAS RUN NOT BY MUTATION, BUT ON AN UNTOUCHED PROD COPY
(`/opt/kukai-rebuild1/backend`, 16.08.2026) — nothing in the tree was moved
for it, which matters more than convenience in the shared tree:

    1 field not written    prod: "unknown kind None"         -> TURNS RED
    2 field not a string   prod: "unknown kind 7"             -> TURNS RED
    3 a different spelling prod: no refusal, ladder resolves  -> green on both
    4 unfamiliar name      prod: "unknown kind 'стенка'", no move -> TURNS RED

The first attempt at this control DID NOT REACH ITS SUBJECT, and that is
worth recording: `pytest`, given a test file from our tree, injected OUR
package into `sys.path`, and "prod" produced the same 4 passed. A control
that measures itself is green by construction; it was resolved by asking
`kir.compiler.__file__` directly.
"""
from __future__ import annotations

import unittest

from kir import spec
from kir.compiler import plan_program
from kir.diag import KirRefusal


def _refusal(op: dict) -> str:
    """The compiler's refusal text for a single-op program, or an empty
    string.

    🔴 WE READ `.diagnostics`, NOT `args[0]`. The first draft of this file
    read `exc.args[0]` — and that is a STRING (`KirRefusal.__init__`
    assembles a header from the first three diagnostics), so iterating over
    it produced a character-by-character split, and three tests turned red
    against a perfectly sound compiler. The same defect the test catches in
    prod: the wrong authority was asked.
    """
    try:
        plan_program({"ir_version": "1.0", "ops": [op]})
    except KirRefusal as exc:
        return " | ".join(
            str(getattr(item, "message_ru", "") or item)
            for item in exc.diagnostics)
    return ""


class KindRefusalNamesTheNextMove(unittest.TestCase):

    def test_absent_field_names_the_next_move_and_the_whole_closed_list(self):
        text = _refusal({"op": "query_count", "id": "q1"})
        self.assertIn("не написано", text)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", text)
        # The list is printed IN FULL, and that is a requirement, not
        # decoration: from a truncated list the model cannot know whether
        # the name it needs is hiding behind the ellipsis, and will spend a
        # move checking.
        for name in sorted(spec.KINDS):
            self.assertIn(name, text)

    def test_non_string_names_the_type_it_got(self):
        text = _refusal({"op": "query_count", "id": "q1", "kind": 7})
        self.assertIn("строкой", text)
        self.assertIn("int", text)
        self.assertNotIn("не написано", text)

    def test_another_spelling_is_resolved_and_never_refused(self):
        # Exactly the input the night subject typed live: `walls`.
        self.assertEqual("", _refusal(
            {"op": "query_count", "id": "q1", "kind": "walls"}))

    def test_unknown_name_names_a_neighbour_rather_than_a_list(self):
        text = _refusal({"op": "query_count", "id": "q1", "kind": "стенка"})
        self.assertIn("неизвестный kind", text)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", text)


if __name__ == "__main__":
    unittest.main()
