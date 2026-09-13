"""AN ASSEMBLY SUMMARY ADDRESS MUST NAME ITS OWN PROGRAM (`F-174`).

An operation's `id` is unique WITHIN a program — that is the contract, and
a name collision BETWEEN programs is LEGITIMATE: two independently written
programs will both name their first wall `w_s`. The summary, however,
speaks of a BATCH, and a bare `w_s` in it is not an address, but a
coincidence.

🔴 WHAT AN EXECUTED RUN OF PRODUCTION CODE SHOWED ON 30.08.2026. The same
`AssemblyView` was carrying TWO DIFFERENT ADDRESS FORMS under one declared
`op_id` namespace:

    hab:HAB060      at=["p1/r1"]      <- QUALIFIED by the batch judge
    enclosure_ok    at=["w_s","w_e","w_n","w_w","w_s","w_e","w_n","w_w"]
                                      <- BARE: eight different walls, four names

    observe_units([A, B]), each carrying ribbon d1,d2 and unit u1
    BEFORE: two `unit_not_continuous` observations, BYTE-FOR-BYTE IDENTICAL
            (1 of 2 addresses distinguishable)
    AFTER:  `p1/d1,p1/d2` and `p2/d1,p2/d2` (2 of 2)

The defect is not that the name repeats. The defect is that the reader has
nothing with which to choose which of the two to fix — and that RIGHT
THERE, in the very same answer, lay an address that CAN be chosen.

WHY THE FORM ISN'T NEW. The batch judge adopted it earlier, and with an
argument (`design_check._bundle_oid`): the program's position is single-
based, placed up front, separated by `/`, and is qualified ALWAYS, not
only on collision — otherwise the address would drift depending on what is
written in a NEIGHBORING program. Here it is ADOPTED, and the repetition is
guarded by a number: `test_our_form_is_the_judges_form` turns red if the
forms drift apart.

WHAT THIS GUARD DOES NOT PROVE is stated so that it is not read more
broadly than it is. It checks the FORM of the address, not that the
program's position is stable over time: a live session's batch is
`entry.standing()`, and eviction of the journal's head shifts positions
without shifting `seq`. Within ONE receipt this does not matter (the batch
is named in full); between receipts it does matter, and this guard does
not touch that question.
"""
from __future__ import annotations

import os
import re
import unittest
from unittest import mock

from kir import assembly_view as AV
from kir import ports

_V2 = {"KIR_CHECKER_V2": "1", "KUKAI_CHECKER_V2": "1"}

_LVL = {"by": "name", "value": "Этаж 1"}

#: The form of a qualified address. `p?` is a NAMED not-knowing of a
#: merged source, not a position: the sieve MUST accept it on equal
#: footing with a number, otherwise an honest refusal would read as a
#: violation of the form.
_QUALIFIED = re.compile(r"^p(\d+|\?)/")


def _box(name: str = "Жилая комната") -> dict:
    """A closed box with a room. The operation names are THE SAME across
    all copies — exactly what is legitimate and exactly what was breaking
    the address."""
    return {"ops": [
        {"op": "create_level", "id": "L0", "elev_mm": 0, "name": "Этаж 1"},
        {"op": "create_wall", "id": "w_s", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "height_mm": 3300, "level": _LVL},
        {"op": "create_wall", "id": "w_e", "p0_mm": [6000, 0],
         "p1_mm": [6000, 4000], "height_mm": 3300, "level": _LVL},
        {"op": "create_wall", "id": "w_n", "p0_mm": [6000, 4000],
         "p1_mm": [0, 4000], "height_mm": 3300, "level": _LVL},
        {"op": "create_wall", "id": "w_w", "p0_mm": [0, 4000], "p1_mm": [0, 0],
         "height_mm": 3300, "level": _LVL},
        {"op": "create_room", "id": "r1", "xy": [3000, 2000], "name": name,
         "level": _LVL},
    ]}


def _band(unit_id: str = "u1") -> dict:
    """A "ribbon" unit with a GAP: the predicate MUST reject it."""
    return {
        "ops": [
            {"op": "create_wall", "id": "d1", "p0_mm": [0, 0],
             "p1_mm": [1000, 0], "type": "T", "height_mm": 3000},
            {"op": "create_wall", "id": "d2", "p0_mm": [5000, 0],
             "p1_mm": [6000, 0], "type": "T", "height_mm": 3000},
        ],
        "units": [{"unit_id": unit_id, "reads_as": "continuous",
                   "member_ids": ["d1", "d2"]}],
    }


class _MergedCoherence:
    """A merged source is just like the real one: it counts over the WHOLE
    batch and returns BARE ids, because by this point it has lost the
    program."""

    def flatten(self, programs):
        return [str(op.get("id")) for program in programs
                for op in (program.get("ops") or ())]

    def check(self, elements):
        return {"плит": 1, "колонн_вне_плиты_адреса": list(elements)}


class AddressNamesItsProgram(unittest.TestCase):

    def test_two_programs_do_not_share_an_observation_address(self) -> None:
        """The headline case of `F-174`, reproduced verbatim."""
        observations, silent = AV.observe_units([_band(), _band()])
        self.assertEqual(2, len(observations), silent)
        addresses = [tuple(o.address) for o in observations]
        self.assertEqual(2, len(set(addresses)),
                         "два наблюдения о РАЗНЫХ программах несут один адрес: "
                         "читателю нечем выбрать, какую чинить — %r" % addresses)
        self.assertEqual([("p1/d1", "p1/d2"), ("p2/d1", "p2/d2")], addresses)

    def test_the_bundle_walls_are_addressed_program_by_program(self) -> None:
        """A flat list of the batch's walls — eight walls, not four repeated."""
        from kir import design_check as DC

        pack = [_box(), _box()]
        with mock.patch.dict(os.environ, _V2):
            verdict = DC.check_bundle(pack, building_id="пачка")
        walls = [str(op["id"]) for p in pack for op in p["ops"]
                 if op["op"] == "create_wall"]
        view = AV.observe_verdict(verdict, walls, programs=pack)
        enclosure = [o for o in view.observations
                     if o.code.startswith("enclosure_")]
        self.assertEqual(1, len(enclosure))
        got = list(enclosure[0].address)
        self.assertEqual(8, len(set(got)),
                         "восемь разных стен обязаны иметь восемь адресов: %r"
                         % (got,))
        self.assertEqual(["p1/w_s", "p1/w_e", "p1/w_n", "p1/w_w",
                          "p2/w_s", "p2/w_e", "p2/w_n", "p2/w_w"], got)

    def test_one_view_speaks_one_address_space(self) -> None:
        """🔴 THE DEFECT ITSELF, PINNED BY THE RATCHET: one answer cannot
        carry two address forms. The judge already qualifies its own
        `hab:*`; the summary MUST speak the same language with it,
        otherwise its `address_space` lies about half its own observations."""
        from kir import design_check as DC

        pack = [_box(), _box()]
        previous = ports.ask(ports.DESIGN_COHERENCE)
        ports.register(ports.DESIGN_COHERENCE, _MergedCoherence)
        try:
            with mock.patch.dict(os.environ, _V2):
                verdict = DC.check_bundle(pack, building_id="пачка")
            view = AV.observe_verdict(verdict, [], programs=pack)
        finally:
            if previous is None:
                ports.unregister(ports.DESIGN_COHERENCE)
            else:
                ports.register(ports.DESIGN_COHERENCE, lambda: previous)

        self.assertEqual(AV.ADDRESS_SPACE_PROGRAM_OP, view.address_space)
        seen_hab = False
        for obs in view.observations:
            for address in obs.address:
                if address == "(программа)":
                    continue  # the wall-less branch addresses the whole program
                self.assertRegex(
                    address, _QUALIFIED,
                    "наблюдение %r несёт ГОЛЫЙ адрес %r, а сводка объявила "
                    "пространство %r" % (obs.code, address, view.address_space))
            seen_hab = seen_hab or obs.code.startswith("hab:")
        self.assertTrue(seen_hab, "судья не высказался — сравнивать не с чем")

    def test_our_form_is_the_judges_form(self) -> None:
        """A SECOND CARRIER OF ONE PIECE OF KNOWLEDGE IS GUARDED BY A
        NUMBER, NOT A PROMISE.

        The batch judge adopted the form; we repeated it. If they drift
        apart, this test turns red, and the drift is named by its subject,
        rather than found a month later on a live receipt.
        """
        from kir import design_check as DC

        judge_form = getattr(DC, "_bundle_oid", None)
        self.assertTrue(callable(judge_form),
                        "у судьи пропала функция формы адреса пачки: сверять "
                        "не с чем, и повтор в assembly_view остался без хозяина")
        for position, oid in ((1, "w1"), (2, "стена-1"), (17, "#3")):
            self.assertEqual(judge_form(position, oid),
                             AV.program_address(position, oid))

        # AND BY THE PATH, NOT ONLY BY THE HELPER: what the judge actually
        # put into `refs` MUST match what we would have built ourselves.
        pack = [_box(), _box()]
        with mock.patch.dict(os.environ, _V2):
            verdict = DC.check_bundle(pack, building_id="пачка")
        refs = {r for bucket in ("blocking", "warnings")
                for v in list(getattr(getattr(verdict, "report", None),
                                      bucket, ()) or ())
                for r in (getattr(v, "refs", ()) or ())}
        self.assertTrue(refs, "судья не назвал ни одного адреса")
        self.assertIn(AV.program_address(1, "r1"), refs)
        self.assertIn(AV.program_address(2, "r1"), refs)

    def test_a_merged_source_names_what_it_cannot_resolve(self) -> None:
        """A merged source: where there is a single owner — an exact
        address; where there are several — a NAMED not-knowing `p?`,
        rather than a silent choice in favor of the first one."""
        one = {"ops": [{"op": "create_column", "id": "c1"},
                       {"op": "create_column", "id": "общая"}]}
        two = {"ops": [{"op": "create_column", "id": "c2"},
                       {"op": "create_column", "id": "общая"}]}
        previous = ports.ask(ports.DESIGN_COHERENCE)
        ports.register(ports.DESIGN_COHERENCE, _MergedCoherence)
        try:
            observations, silent = AV.observe_coherence([one, two])
        finally:
            if previous is None:
                ports.unregister(ports.DESIGN_COHERENCE)
            else:
                ports.register(ports.DESIGN_COHERENCE, lambda: previous)
        self.assertEqual({}, silent)
        self.assertEqual(1, len(observations))
        self.assertEqual(("p1/c1", "p?/общая", "p2/c2", "p?/общая"),
                         observations[0].address)

    def test_without_a_pack_the_callers_list_is_not_substituted(self) -> None:
        """The `observe_l0` door supplies `element_id` and does NOT supply a
        batch. Ascribing a program position to them would mean inventing
        one: there is no program there at all."""

        class _Witness:
            source = "parse"
            partition_faces = 0

        class _Verdict:
            building_id = "здание"
            witness = _Witness()
            report = None

        view = AV.observe_verdict(_Verdict(), ["4001", "4002"])
        self.assertEqual(AV.ADDRESS_SPACE_OP, view.address_space)
        for obs in view.observations:
            for address in obs.address:
                self.assertNotRegex(address, _QUALIFIED)

    def test_the_digest_does_not_make_the_separator_a_homonym(self) -> None:
        """🔴 THE SLASH IS TAKEN BY THE ADDRESS, SO THE UNIT TAKES A
        DIFFERENT MARK.

        Before the fix, the digest glued the unit on with `/`, and the
        string `unit_not_continuous@p1/d1,p1/d2/u1` could not be parsed by
        anything: where the address ends and the unit begins cannot be
        derived from it. A separator that becomes a homonym loses both
        meanings.
        """
        observations, _ = AV.observe_units([_band("лента-1")])
        view = AV.AssemblyView(observations=tuple(observations),
                               sources_asked=("units",),
                               address_space=AV.ADDRESS_SPACE_PROGRAM_OP)
        line = AV.digest(view)
        self.assertIn("[лента-1]", line)
        self.assertNotIn("/лента-1", line)
        self.assertLessEqual(len(line), AV.DIGEST_LIMIT)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
