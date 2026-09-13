"""THE REGISTRY OWNS THE CAPABILITIES — AND THIS IS CHECKED BY MEASUREMENT, NOT BY PROSE.

Mandate F1/C02: "A capability contract for operation × backend × preview ×
witness × reverse; a single registry remains the owner of
operations/types/effects/capabilities, and is not manually duplicated per
instrument." A fifth axis — `clash` (does the op give the building a
body) — is added here on the same grounds: it has the same shape and the
same way of lying.

WHAT IS PINNED DOWN HERE, IN THREE LAWS:

  L1 A CLOSED OUTCOME. For EVERY registry op and EVERY axis, an answer
     exists: either "can", or "cannot BECAUSE ...". There is no silence.

  L2 AGREEMENT WITH THE FACT. The declaration (`kir.capability.limits`)
     must match a LIVE measurement of the axis, name for name. A mismatch
     is either a name that fell out of the hand-copied list, or a
     declaration wider than the fact; each is fixed in a DIFFERENT place,
     which is why the report prints both sides.

  L3 THE REGISTRY'S VETO. An axis has no right to declare a capability
     impossible according to the registry: an op that writes nothing gives
     no body, does not lift back, and is not checked by a witness. This
     law is needed because a complement ("anything not in the table —
     can do it") cannot tell "no reason was named" apart from "can do
     it": a name that fell out of the hand-copied list silently becomes a
     capability.

🔴 WHAT L3 WAS PAID FOR WITH, MEASURED 07.09.2026.
`clash_bundle.body_making_ops()` is `set(spec.OPS) - set(OP_NO_BODY)`, i.e.
the COMPLEMENT of a hand-written table. The op `query_element_state`
(family `query`, effect `READ`) is absent from the table — and is
therefore declared to GIVE A BODY. A reading operation, which a collision
search expects to have a shell. This is not a new kind of defect, but the
THIRD occurrence of it in one table: `query_surface` fell out the same way
(found 21.08.2026 by the closedness law), `create_space` and
`create_curtain_grid_line` — 11.08.2026. A complement is fixed not by
memory, but by a question put to the registry.

🔴 WHY THE AXIS IS MEASURED BY BEHAVIOR, NOT BY READING SOURCE. Parsing
the text of `preview._program_shape` or `compiler._emit_op` would lie on
the very first reshuffle of branches — this kind of defect has already
been paid for by this tree ("a source-reading test lies about foreign
code", 26.08.2026). So the dispatcher is ASKED instead: the drawer
answers `OmitReason.OP_NOT_DRAWN`, the compiler answers
`AssertionError("unreachable")`, and both answers are declared honest by
their own authors, not derived here.
"""
from __future__ import annotations

import unittest

from kir import capability, spec


class TheOutcomeIsClosed(unittest.TestCase):
    """L1: not a single op falls out on any axis."""

    def test_every_op_has_an_outcome_on_every_axis(self) -> None:
        silent: list[str] = []
        for name in sorted(spec.OPS):
            can = capability.capabilities(name)
            cannot = capability.limits(name)
            self.assertEqual(
                can | frozenset(cannot), frozenset(capability.AXES),
                f"{name}: оси разошлись с закрытым списком")
            self.assertFalse(
                can & frozenset(cannot),
                f"{name}: ось одновременно умеет и не умеет")
            for axis, why in cannot.items():
                if not (why or "").strip():
                    silent.append(f"{name}/{axis}")
        self.assertEqual(
            silent, [],
            "ограничение без причины — слепое пятно, о котором не сказано: "
            f"{silent}")

    def test_the_axis_list_is_the_only_carrier(self) -> None:
        """An axis with no measurement is a promise with no instrument."""
        self.assertEqual(
            frozenset(capability.AXES), frozenset(capability._FACT),
            "объявленные оси и замеряемые оси разошлись")


class TheDeclarationAgreesWithTheFact(unittest.TestCase):
    """L2: the registry's declaration == a live measurement of the axis, name for name."""

    def _one_axis(self, axis: str) -> None:
        declared = capability.declared_axis(axis)
        fact = capability.axis_fact(axis)
        direction, why_one_sided = capability.AXIS_LAW[axis]
        promised_but_absent = sorted(declared - fact)
        present_but_denied = sorted(fact - declared)
        if direction == "declared_subset_of_fact":
            present_but_denied = []
        elif direction == "fact_subset_of_declared":
            promised_but_absent = []
        elif direction != "both":
            self.fail(f"ось {axis}: неизвестное направление {direction!r}")
        self.assertEqual(
            (promised_but_absent, present_but_denied), ([], []),
            f"\nось {axis} (закон {direction}"
            f"{'; ' + why_one_sided if why_one_sided else ''}):\n"
            f"  ОБЪЯВЛЕНО, НО ФАКТА НЕТ ({len(promised_but_absent)}): "
            f"{promised_but_absent}\n"
            f"    — либо оп выпал из ручной копии инструмента, либо "
            f"объявление обязано честно сузиться с причиной\n"
            f"  ФАКТ ЕСТЬ, НО ОБЪЯВЛЕНО «НЕ УМЕЕТ» ({len(present_but_denied)}): "
            f"{present_but_denied}\n"
            f"    — инструмент научился, а реестр об этом не сказал: снять "
            f"ограничение")

    def test_every_axis_names_its_law(self) -> None:
        """An axis without a declared direction would be checked by taste."""
        self.assertEqual(frozenset(capability.AXIS_LAW),
                         frozenset(capability.AXES))
        for axis, (direction, why) in capability.AXIS_LAW.items():
            self.assertIn(direction, ("both", "declared_subset_of_fact",
                                      "fact_subset_of_declared"))
            if direction != "both":
                self.assertTrue(
                    why.strip(),
                    f"{axis}: односторонний закон обязан НАЗВАТЬ, почему "
                    f"вторая сторона не дефект")

    def test_a_name_dropped_from_a_manual_copy_turns_the_axis_red(self) -> None:
        """🔴 A DISTURBING ORACLE. A LAW PAID FOR BY A CONTROL MUTATION ON 07.09.

        The first edition of this file checked the `clash` axis against
        `clash_bundle.body_making_ops()`, while the declaration read
        `clash_bundle.OP_NO_BODY` — that is, the COMPLEMENT of the same
        table checked against itself. A mutation "drop `create_room` from
        the hand-copied list" the instrument SURVIVED GREEN: 14 passed
        before the mutation, 14 passed after. Exactly the kind this tree
        has already paid for in `test_clash_in_the_receipt.py` (a check
        that cannot fail, 11.08.2026) — and it paid for it AGAIN.

        This is fixed not by memory and not by a "the carriers are
        different" measurement (there is nothing to compare the carriers
        with: for `backend` the declaration is honestly equal to the whole
        registry, and forbidding the match would declare the entire axis a
        defect). It is fixed by DISTURBANCE: the name is removed from the
        hand-copied list RIGHT HERE, in the process, and the law must go
        red. Precedent — `tests/test_tolerance_provenance.py`, law L6.

        `create_room` was not chosen at random: a room is a VOLUME, not a
        body, and it has no category at all, so removing its name does
        exactly what makes a complement dangerous — it silently declares
        something a body when it has no body at all.
        """
        from kir import clash_bundle

        victim = "create_room"
        saved = clash_bundle.OP_NO_BODY.pop(victim)
        try:
            with self.assertRaises(AssertionError, msg=(
                    f"снятие {victim!r} из ручной копии OP_NO_BODY прибор "
                    f"пережил — закон оси clash не может упасть")):
                self._one_axis("clash")
        finally:
            clash_bundle.OP_NO_BODY[victim] = saved
        self._one_axis("clash")

    def test_a_lifter_the_manifest_never_declared_turns_the_axis_red(self) -> None:
        """The same disturbance for the `reverse` axis, from its own side of the law.

        Here the law is one-sided, "the live lifter ⊆ the declared forward
        pass," so what is mutated is NOT the declaration but the
        MEASUREMENT: a category is planted into the lifter dispatcher that
        lifts an op the manifest does not name as a forward pass. The
        instrument must see this.
        """
        from kir.decompile import lift

        victim = "create_surface"      # manifest: CAPTURE_GAP, not a forward pass
        self.assertNotIn(victim, capability.declared_axis("reverse"))
        table = dict(lift.LIFTER_TABLE)
        table["OST_ProbeCategory"] = ("probe", victim)
        saved = lift.LIFTER_TABLE
        lift.LIFTER_TABLE = table
        try:
            with self.assertRaises(AssertionError, msg=(
                    "лифтер, о котором манифест молчит, прибор пережил")):
                self._one_axis("reverse")
        finally:
            lift.LIFTER_TABLE = saved
        self._one_axis("reverse")

    def test_backend(self) -> None:
        self._one_axis("backend")

    def test_preview(self) -> None:
        self._one_axis("preview")

    def test_witness(self) -> None:
        self._one_axis("witness")

    def test_reverse(self) -> None:
        self._one_axis("reverse")

    def test_clash(self) -> None:
        self._one_axis("clash")


class TheRegistryHasAVeto(unittest.TestCase):
    """L3: what the registry makes impossible has no right to be declared a capability."""

    def _reading_ops(self) -> list[str]:
        return sorted(n for n, o in spec.OPS.items()
                      if o.family not in spec.WRITE_FAMILIES)

    def test_a_reading_op_makes_no_body(self) -> None:
        from kir import clash_bundle

        bodied = set(clash_bundle.body_making_ops())
        wrong = [n for n in self._reading_ops() if n in bodied]
        self.assertEqual(
            wrong, [],
            "читающая операция объявлена дающей ТЕЛО — имя выпало из "
            f"clash_bundle.OP_NO_BODY, и дополнение сделало это молча: {wrong}")

    def test_a_reading_op_carries_no_witness(self) -> None:
        from kir import translation_cert

        table = set(translation_cert._ensure_table())
        wrong = [n for n in self._reading_ops()
                 if n in table and n not in spec.SOLO_OPS]
        self.assertEqual(
            wrong, [],
            f"читающая операция объявлена имеющей свидетеля коммита: {wrong}")

    def test_a_reading_op_is_not_lifted_back(self) -> None:
        from kir import reverse_contract

        wrong = [n for n in self._reading_ops()
                 if n in reverse_contract.REVERSE_CONTRACTS]
        self.assertEqual(
            wrong, [],
            f"читающая операция стоит в манифесте обратного хода: {wrong}")

    def test_a_reading_op_is_not_drawn_as_a_body_in_plan(self) -> None:
        drawn = capability.axis_fact("preview")
        wrong = [n for n in self._reading_ops() if n in drawn]
        self.assertEqual(
            wrong, [],
            f"читающая операция рисуется в плане телом: {wrong}")


class TheToolsAskTheRegistry(unittest.TestCase):
    """Capabilities are asked FROM THE REGISTRY, not typed in by an instrument."""

    def test_the_preview_carrier_is_exhaustive_over_the_registry(self) -> None:
        drawn = capability.axis_fact("preview")
        uncovered = sorted(set(spec.OPS) - drawn - set(capability.PREVIEW_LIMITS))
        self.assertEqual(
            uncovered, [],
            "оп не рисуется и причины не назвал — молчание читается как "
            f"«нарисовано»: {uncovered}")

    def test_no_name_outside_the_registry(self) -> None:
        self.assertEqual(capability.audit_capability_axes(), ())
        stray = sorted(set(capability.PREVIEW_LIMITS) - set(spec.OPS))
        self.assertEqual(stray, [], f"имя вне реестра: {stray}")

    def test_limits_refuses_a_name_the_registry_does_not_know(self) -> None:
        with self.assertRaises(KeyError):
            capability.limits("create_stenka")


if __name__ == "__main__":
    unittest.main()
