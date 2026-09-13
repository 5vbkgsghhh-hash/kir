"""REFERENCE VALUE OF `set_param`: material and phase are set by REFERENCE, not by string.

WHY. The value set of `set_param` was closed over `str | bool | число`, and
therefore every parameter whose value IS A REFERENCE was UNREACHABLE: material, phase,
room, level. `Parameter.Set(ElementId)` compiles on all six
versions — the ceiling was OURS, not Revit's.

THE BOUNDARY IS NAMED: three kinds are opened — material, phase (references) and workset
(NOT a reference, its own mechanism), one at a time.
Doing all four at once would have given four unproven claims instead of one proven one. The order
is not alphabetical but follows what gets in the way of the MODEL: phase comes second because
every real project is phased, and an element left in the wrong phase does not show up on the
right views — the building LOOKS built and is not. What remains is the mark, and its
defect is of another kind: parameter addressing by a LOCALIZED display name.

ONE TECHNIQUE FOR ALL KINDS. Exactly two things differ — the Revit class and the
refusal word with its participle; everything else (resolution, refusal, `Set(<el>.Id)`,
the witness) is shared. A second way of doing the same thing would have diverged from the first on the
kind that would arrive third. The file name is left over from the first kind.

AND ON EXACTLY THE THIRD ONE THIS NEARLY COST DEARLY. The workset looks like a fourth
kind of reference and is not one: `Parameter.Set(WorksetId)` does not exist,
`Workset` does not inherit `Element`, the collector is its own, the witness is whole. A line
added to the table by analogy would have produced a capability that LOOKS like two
proven ones. **Checking applicability is the PRICE of generalization**, and it comes before
the technique, not after.

WHAT EXACTLY IS PROVEN HERE, besides "compiles":

* the refusal arrives OFFLINE. The sample (`create_type.material`) resolves the name
  with a collector INSIDE the transaction: the refusal is honest and typed, but it arrives
  where a round trip costs the most. The pool moves that same check to AUTHORING TIME;
* the live check is nonetheless RETAINED. The pool is a snapshot, the document could have changed
  between the snapshot and execution, and dropping the live witness for the offline one would mean
  trading proof for convenience;
* THE WITNESS EXISTS. A capability added without its own witness is not "incomplete"
  — it is FORBIDDEN: the execution has taken place, and there is nothing left to confirm it with.
  That is why the write branch (`Set(<el>.Id)`) and the read-back branch (`AsElementId()`) were
  introduced by ONE and the same edit;
* THERE IS NO DEFAULT, BY CONSTRUCTION. An omitted material would have been resolved by the
  `sole_entry` rule, which does not CHOOSE but states the absence of an alternative
  (measured 12.08.2026: on the fixture this way resolves 46 pairs out of 47, on real
  buildings 42 out of 91 defaults stop working). Here this choice is not
  created, rather than merely "not recommended".

THE POOL'S CARDINALITY IN THE FIXTURE IS TWO, AND THIS IS NOT DECORATION: with a single material
"the right one was chosen" would be proven by the absence of a second candidate, not by
comparison.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program
from kir.tests.fixtures import GROUND_SNAPSHOT

KNOWN = "Бетон М300"
OTHER = "Кирпич керамический"


def program(value):
    return {"ir_version": "1.0", "intent": "материал несущей конструкции",
            "ops": [{"op": "set_param", "id": "SP1",
                     "target": {"by": "element_id", "value": 9001},
                     "param": "Материал несущих конструкций",
                     "value": value}]}


def codes(result):
    return [getattr(d, "code", "") for d in (result.diagnostics or [])]


class AReferenceValueCompiles(unittest.TestCase):

    def test_the_emission_resolves_writes_and_witnesses(self):
        r = compile_program(program({"material": KNOWN}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(r.ok, codes(r))
        cs = r.csharp
        self.assertIn("OfClass(typeof(Material))", cs)   # resolution
        self.assertIn(KNOWN, cs)
        self.assertIn("Set(__rf_SP1.Id)", cs)            # WRITE by reference
        self.assertIn("AsElementId()", cs)               # WITNESS
        self.assertIn("не найден в документе", cs)       # the live refusal REMAINS

    def test_the_pool_has_more_than_one_entry(self):
        """Otherwise "the right one was chosen" is proven by the absence of a competitor."""
        self.assertGreaterEqual(len(GROUND_SNAPSHOT["materials"]), 2)


class TheRefusalArrivesOffline(unittest.TestCase):
    """The FAIL control, without which the green result above means nothing."""

    def test_an_unknown_material_refuses_before_revit(self):
        r = compile_program(program({"material": "Такого материала нет"}),
                            "2024", snapshot=GROUND_SNAPSHOT)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G101", codes(r))
        self.assertIn("известно", r.diagnostics[0].message_ru,
                      "отказ обязан печатать ЗНАМЕНАТЕЛЬ — сколько материалов "
                      "он вообще видел")

    def test_an_empty_pool_refuses_and_does_not_pass_silently(self):
        snap = {**GROUND_SNAPSHOT, "materials": []}
        r = compile_program(program({"material": KNOWN}), "2024", snapshot=snap)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G104", codes(r))

    def test_both_pool_entries_are_reachable_not_just_the_first(self):
        for name in (KNOWN, OTHER):
            with self.subTest(material=name):
                r = compile_program(program({"material": name}), "2024",
                                    snapshot=GROUND_SNAPSHOT)
                self.assertTrue(r.ok, codes(r))
                self.assertIn(name, r.csharp)


class PhaseIsTheSecondKindAndUsesTheSameMachinery(unittest.TestCase):
    """The second kind of reference. There is ONE technique; what differs is the Revit class and the refusal word.

    Phase is taken second because of what gets in the way of the MODEL, not alphabetically: every
    real project is phased, and an element that ends up in the wrong phase is not shown
    on the right views — the building LOOKS built and is not.
    """

    def test_a_known_phase_compiles_with_its_own_revit_class(self):
        r = compile_program(program({"phase": "Новая конструкция"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(r.ok, codes(r))
        self.assertIn("OfClass(typeof(Phase))", r.csharp)
        self.assertIn("Set(__rf_SP1.Id)", r.csharp)
        self.assertIn("AsElementId()", r.csharp)

    def test_an_unknown_phase_refuses_offline(self):
        r = compile_program(program({"phase": "Такой фазы нет"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G101", codes(r))

    def test_an_empty_phase_pool_refuses(self):
        r = compile_program(program({"phase": "Новая конструкция"}), "2024",
                            snapshot={**GROUND_SNAPSHOT, "phases": []})
        self.assertFalse(r.ok)
        self.assertIn("KIR-G104", codes(r))

    def test_the_refusal_agrees_with_the_gender_of_the_thing_it_names(self):
        """«фаза не найден» is not a typo but English grammar leaking into a Russian
        product. It is checked because the participle is written RIGHT NEXT TO the gender and
        drifts out of agreement silently."""
        r = compile_program(program({"phase": "Нет такой"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertIn("не найдена", r.diagnostics[0].message_ru)
        r = compile_program(program({"material": "Нет такого"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertIn("не найден", r.diagnostics[0].message_ru)

    def test_the_two_kinds_do_not_leak_into_each_other(self):
        mat = compile_program(program({"material": KNOWN}), "2024",
                              snapshot=GROUND_SNAPSHOT)
        pha = compile_program(program({"phase": "Существующие"}), "2024",
                              snapshot=GROUND_SNAPSHOT)
        self.assertNotIn("typeof(Phase)", mat.csharp)
        self.assertNotIn("typeof(Material)", pha.csharp)


class AWorksetIsNotAReferenceAndUsesItsOwnMachinery(unittest.TestCase):
    """THE THIRD KIND — AND IT IS NOT A THIRD KIND OF REFERENCE.

    Measured against the trap index on 13.08.2026 and confirmed by Roslyn on six
    versions in the "gate" zone: `Parameter.Set(WorksetId)` does not exist (CS1503
    6/6), `Workset` does not inherit `Element`, it has no `.Id`, the collector is its own,
    the address is `WorksetId.IntegerValue`. The reference technique does not apply at ANY of the
    four steps, so the workset has its own kind of value, its own write `Set(int)`
    and its own witness `AsInteger()`.

    WHY THIS MATTERS MORE THAN THE CAPABILITY ITSELF: the `_REF_POOLS` table made the second
    kind cheap and, for exactly that reason, is dangerous on the third — a line added by
    analogy would have produced a capability that LOOKS like two proven ones.
    Checking applicability is the PRICE of generalization.
    """

    def test_the_emission_uses_the_workset_collector_not_the_element_one(self):
        r = compile_program(program({"workset": "АР_Стены"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(r.ok, codes(r))
        cs = r.csharp
        self.assertIn("FilteredWorksetCollector", cs)
        self.assertIn("Id.IntegerValue", cs)
        self.assertIn("AsInteger()", cs)          # witness OF THE SAME kind
        self.assertNotIn("typeof(Workset)", cs,   # Workset не Element
                         "набор не собирается коллектором ЭЛЕМЕНТОВ")

    def test_the_document_must_be_workshared_and_the_guard_is_emitted(self):
        r = compile_program(program({"workset": "АР_Стены"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertIn("!doc.IsWorkshared", r.csharp,
                      "живая проверка разделённости обязана остаться: снимок "
                      "мог устареть между съёмкой и исполнением")

    def test_an_unshared_document_refuses_with_its_own_reason(self):
        """An empty pool for two outcomes — form 11. Here a flag distinguishes them."""
        snap = {**GROUND_SNAPSHOT, "worksets__workshared": False,
                "worksets": []}
        r = compile_program(program({"workset": "АР_Стены"}), "2024",
                            snapshot=snap)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G104", codes(r))
        self.assertIn("не разделён", r.diagnostics[0].message_ru)

    def test_a_workset_with_id_zero_is_reachable(self):
        """`WorksetId.IntegerValue` starts at ZERO, while the element pool starts at 1.

        This is exactly where the compiler caught the first draft: `snapshot_pool`
        requires `1 <= id`, because "pool" here means a pool of ELEMENTS.
        The check was right; what was wrong was the attempt to declare the workset a pool.
        """
        r = compile_program(program({"workset": "Общие уровни и оси"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(r.ok, codes(r))

    def test_an_unknown_workset_refuses_offline(self):
        r = compile_program(program({"workset": "Нет такого"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G101", codes(r))

    def test_a_malformed_workset_row_is_refused_not_silently_skipped(self):
        snap = {**GROUND_SNAPSHOT,
                "worksets": [{"id": -1, "name": "битый"}]}
        r = compile_program(program({"workset": "битый"}), "2024",
                            snapshot=snap)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G106", codes(r))


class TheOldValueKindsAreUntouched(unittest.TestCase):
    """The branch is added ALONGSIDE, not in place of: the three earlier kinds must keep working."""

    def test_string_number_and_flag_still_compile(self):
        for value, label in (("МаркаТекстом", "строка"),
                             ({"value": 250.0, "unit": "mm"}, "мм"),
                             (True, "флаг")):
            with self.subTest(kind=label):
                r = compile_program(program(value), "2024",
                                    snapshot=GROUND_SNAPSHOT)
                self.assertTrue(r.ok, f"{label}: {codes(r)}")
                self.assertNotIn("__rf_SP1", r.csharp,
                                 "не-ссылочное значение не должно тянуть "
                                 "разрешение материала")


class TheShapeIsRefusedLoudlyWhenMalformed(unittest.TestCase):

    def test_an_empty_material_name_is_refused_not_coerced(self):
        r = compile_program(program({"material": "   "}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(r.ok)


if __name__ == "__main__":
    unittest.main()
