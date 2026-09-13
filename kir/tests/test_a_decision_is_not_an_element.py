"""A DECISION IS NOT AN ELEMENT, AND THEREFORE DOES NOT SURVIVE REBUILD IN ANY FORM.

🔴 WHY THIS FILE WAS CREATED (02.09.2026), AND THIS IS A REFUTATION, NOT A BUILD.

Owner's amendment of 02.09: "**the multi-agent environment will build in
KIR**, but for now will execute in Revit via KUKAI." Hence a requirement
that was not in the plan: **one agent's decisions must survive another
agent's work** — the КР agent has no right to demolish a decision made by
the АР agent.

The assignment was the form `{"by": "hole", "section": "КР", "constraint": {...}}`
— a "legitimate, stored, NON-EXECUTABLE program." Reconnaissance by running
BEFORE building found three things, and each one changes the work.

FIRST: SUCH STATE IS ALREADY BUILT, AND TWICE OVER.

    `phases`         envelope key: collected by `course.phase()`, consumed
                     by `compiler.split_phases`, and `plan_program` FAILS
                     by name and states the next move
    `phase_result`   selector label (`spec.CROSS_PHASE_BY`): sets the
                     course, substituted by
                     `compiler.substitute_phase_results`, and if left
                     unsubstituted it must fail — as its own docstring
                     itself says (`spec.py:333`)

Both are stored (plain JSON) and both are non-executable. Neither has the
third property — "the parser accepts it": the grammar is fail-closed on
both sides.

SECOND: THE COST OF THE THIRD PROPERTY HAS BEEN MEASURED, AND IT DIFFERS
BETWEEN THE TWO CARRIERS.

    SELECTOR carrier   `_sel_shape_ok` (`authoring_validation.py:640`) ends
                     with `return False`; there are FIVE valid `by` values
                     (family_type · default · name · ref · element_id); the
                     key set is CLOSED to six names. Plus 36 `by` parsers
                     outside the tests, grounding, fold canonicalization,
                     and the reverse pass — seven boundaries
    ENVELOPE carrier   `known_top` (`compiler.py:1359`) — ONE place, six
                     names; the selector grammar does not move at all

THIRD, AND IT CANCELS BOTH: NEITHER OF THE TWO SURVIVES REBUILD.

`BuildingState` is a multiset of canonical OPS taken from L1 leaves
(`rebuild.py:99-112`), and `canon_op` returns "stable JSON for one
localized L1 operation/atom" — that is, a string about ONE op. There is no
envelope in the state at all, and there is nowhere for it to come from:
both state constructors accept LEAVES, not a program. Measured at the
producer: `materialize.leaves_to_program` puts ZERO envelope keys.

So a decision placed into the program — whether as a selector or as an
envelope key — is demolished by the neighbor not through ill will and not
through a code defect, but BY CONSTRUCTION: rebuild restores the building
from the OBSERVED model, and a decision was never an element in the model.

WHAT FOLLOWS FROM THIS FOR THE NEXT PERSON, SO THEY DO NOT BUILD THE SAME
THING AGAIN. A durable carrier for a decision must live where rebuild READS
FROM, not where it REBUILDS. Such a carrier already exists in the tree, and
there is exactly one — the revision journal (`decompile/journal.py`): it is
not derived from the model, so rebuild does not erase it, and
`serving._resolve_base_from_journal` already reads it as the delta's base.
The envelope key, meanwhile, remains a legitimate PASS for one program
("here КР is awaited"), but it cannot be the decision's storage.

WHAT THIS FILE DOES NOT ASSERT. It does not say the `by: hole` form is
unneeded, and it does not forbid adding an envelope key: it holds the COST
and the BOUNDARY, so the next person does not pay for seven boundaries only
to get a state that the neighbor demolishes by construction. Should someone
add `holes` to `known_top`, these tests will remain green, while the one
guarding rebuild will turn red.
"""
from __future__ import annotations

import inspect
import json
import unittest

from kir import compiler, spec
from kir.decompile import materialize, rebuild


def _program(**envelope):
    """A deliberately LEGITIMATE program plus what is asked to be checked."""
    prog = {"ir_version": "1.0", "intent": "проба носителя решения",
            "ops": [{"op": "create_level", "id": "L1",
                     "elev_mm": 0.0, "name": "Этаж 1"}]}
    prog.update(envelope)
    return prog


class ТриСвойстваУжеПостроеныДважды(unittest.TestCase):
    """"Legitimate, stored, non-executable" — not a new state of the language."""

    def test_phases_refuses_by_name_and_says_the_next_move(self) -> None:
        """The envelope precedent: the failure NAMES the next move, not the field.

        This is exactly the difference between "unknown field" and "not
        executable here": the former sends the reader to REMOVE the field
        (that is, to lose checkpoints), the latter to change doors. Mutating
        the message to a generic one erases this difference, and the test
        must go red.
        """
        with self.assertRaises(Exception) as поймано:
            compiler.plan_program(_program(phases=[]))
        текст = str(поймано.exception)
        self.assertIn("split_phases", текст,
                      "отказ обязан назвать СЛЕДУЮЩИЙ ХОД, а не только поле")
        self.assertNotIn("неизвестное поле конверта", текст,
                         "`phases` — законная часть конверта, а не опечатка")

    def test_the_phase_label_is_storable_but_unexecutable(self) -> None:
        """Selector label: the JSON round-trip holds it, `plan_program` fails."""
        метка = {"by": spec.CROSS_PHASE_BY, "value": "L1"}
        s = json.dumps(метка, ensure_ascii=False, sort_keys=True)
        self.assertEqual(json.loads(s), метка, "метка не пережила круг JSON")

        программа = _program()
        программа["ops"].append(
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000, "level": метка})
        with self.assertRaises(Exception):
            compiler.plan_program(программа)


class ЦенаТретьегоСвойстваИзмерена(unittest.TestCase):
    """Both grammars are fail-closed, and closed at different costs."""

    def test_the_selector_grammar_is_closed_and_names_the_extra_keys(self) -> None:
        """The SELECTOR carrier: extraneous keys are named by name.

        The pin holds the COST: `section` and `constraint` are exactly the
        two keys because of which the `by: hole` form fails parsing, and
        the failure must name both, not just dump the whole input received.
        """
        программа = _program()
        программа["ops"].append(
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "hole", "section": "КР",
                       "constraint": {"max_width_mm": 400}}})
        with self.assertRaises(Exception) as поймано:
            compiler.plan_program(программа)
        текст = str(поймано.exception)
        self.assertIn("constraint", текст)
        self.assertIn("section", текст)

    def test_the_envelope_grammar_is_closed_and_lists_its_known_keys(self) -> None:
        """The ENVELOPE carrier: the failure carries the LIST of known keys.

        A property, not a list: should someone add `holes` to `known_top`,
        this test will remain green, because it asks "is the closed set
        named," not "what is it."
        """
        with self.assertRaises(Exception) as поймано:
            compiler.plan_program(_program(выдуманный_ключ=[]))
        отказ = поймано.exception
        self.assertIn("неизвестное поле конверта", str(отказ))
        # 🔴 THE LIST OF KNOWNS LIVES IN THE `candidates` FIELD, NOT IN THE
        # TEXT, and this was caught by a run: the first draft of the test
        # searched for names in the message and went red. One must query
        # the carrier that holds them — otherwise the test guards the
        # wording, not the property.
        свои = [d for d in отказ.diagnostics if d.code == "KIR-P003"]
        self.assertTrue(свои, "отказ конверта обязан нести диагностику")
        for известный in ("ir_version", "intent", "ops"):
            self.assertIn(известный, свои[0].candidates or (),
                          "отказ обязан назвать, что БЫВАЕТ в конверте")


class РешениеНеПереживаетПересборку(unittest.TestCase):
    """LOAD-BEARING. Rebuild reads the MODEL, and the decision was never in the model."""

    def test_building_state_is_built_from_leaves_and_never_from_a_program(self) -> None:
        """Asked of the constructors THEMSELVES, not of the text next to them.

        The building state has two entry points, and both accept leaves or
        a tree. As long as this holds, ANY program-level decision is lost
        on rebuild by construction — and arguing with this via the `by`
        form is pointless.
        """
        for имя in ("of_leaves", "of_tree"):
            параметры = list(inspect.signature(
                getattr(rebuild.BuildingState, имя)).parameters)
            self.assertNotIn("program", параметры,
                             f"BuildingState.{имя} стал принимать программу — "
                             "перечитай шапку этого файла, вывод изменился")
            self.assertNotIn("envelope", параметры)

    def test_the_rebuilt_program_carries_no_decision_in_its_envelope(self) -> None:
        """Measured at the PRODUCER: what rebuild puts into the envelope.

        What is asked here is not "is there a decision key" (nobody has one
        today), but how many envelope keys the producer puts AT ALL. Zero
        means there is no channel for a decision, and one will not appear
        just because the decision is named somewhere else.
        """
        итог = materialize.leaves_to_program([])
        for программа in итог.programs:
            конверт = {k: v for k, v in программа.items() if k != "ops"}
            for опасный in ("phases", "holes", "decisions", "constraints"):
                self.assertNotIn(опасный, конверт,
                                 "у пересборки появился канал для решения — "
                                 "значит вывод этого файла устарел, перемерь")
        # 🔴 AN EMPTY INPUT GIVES AN EMPTY OUTPUT, AND THAT IS NOT A
        # MEASUREMENT. Zero programs above proves nothing (form 4: zero
        # from the corpus is about the corpus), so the property is asked of
        # the PRODUCER ITSELF: how many envelope keys it is even capable of
        # setting. The signature answers without any input at all.
        параметры = list(inspect.signature(
            materialize.leaves_to_program).parameters)
        for опасный in ("holes", "decisions", "constraints", "envelope"):
            self.assertNotIn(опасный, параметры,
                             "производителю дельты стали передавать решение — "
                             "перемерь вывод этого файла")
