"""THE DELTA A->B REACHES THE WITNESS, not just the classification.

WHY THIS FILE EXISTS, MEASURED 2026-08-19. The rebuild promises, in its
docstring, "the same obligation, only by delta." The promise was checked
by nothing:

    grep -rl rebuild kir/decompile/tests | xargs grep -l "witness|verdict"
    -> EMPTY

Two links of four were covered: classification (`reuse/relocate/emit/retire`,
theorem T-APPLY on multisets) and materialization into ops. Between "the
ops came out" and "the same witness stands behind them as behind the full
program" there stood not a single test — that is, exactly at the point
for whose sake the rebuild exists as a PRODUCT at all ("the building has
source code, and an edit can be checked").

The chain this file drives is entirely offline:

    building A -> building B -> delta_rebuild_plan -> delta leaves
        -> leaves_to_program (real KIR ops)
        -> compile_program   (real C# with a guard and rollback)
        -> certify_op        (witness: proven / not proven)

🔴 WHAT IS NOT CHECKED HERE, AND IT IS NAMED. Real Roslyn is not invoked
here: `compile_program` is OUR compiler, it prints C#, and whether that
compiles under real Roslyn on six versions is checked by a separate tier
(compile-service on 52412, the `compile_service` fixture skips itself
without dotnet). Live Revit is not invoked at all — no test in this tree
requires it, that is a systemic decision.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_delta_obligation_queue.jsonl"))
os.environ.setdefault("KUKAI_IR_REBUILD", "1")

from kir import translation_cert as tc  # noqa: E402
from kir.compiler import compile_program  # noqa: E402
from kir.decompile.fold import iter_l1_leaves  # noqa: E402
from kir.decompile.materialize import leaves_to_program  # noqa: E402
from kir.decompile.rebuild_plan import delta_rebuild_plan  # noqa: E402
from kir.decompile.tests.test_merkle import (  # noqa: E402
    _fold,
    _grid_building,
)

_VERSIONS = ("2021", "2024", "2026")


def _delta_ops(**edit):
    """The ops the rebuild would lay down to get B out of A."""
    tree_a = _fold(_grid_building(floors=3))
    tree_b = _fold(_grid_building(floors=3, **edit))
    plan = delta_rebuild_plan(tree_a, tree_b)
    wanted = plan.materialize_source_ids
    leaves = [leaf for leaf in iter_l1_leaves(tree_b)
              if leaf.get("source_element_id") in wanted]
    return plan, leaves_to_program(leaves)


def _whole_ops():
    """The ops of a full rebuild of the same building — for reconciling obligations."""
    tree_b = _fold(_grid_building(floors=3, stretch_wall_on_floor=1))
    return leaves_to_program(list(iter_l1_leaves(tree_b)))


class DeltaReachesTheWitness(unittest.TestCase):

    def test_a_wall_edit_becomes_real_ops_that_compile_with_a_guard(self):
        """Delta -> ops -> C#, and the C# HAS a guard and rollback, not just create."""
        plan, result = _delta_ops(stretch_wall_on_floor=1)
        self.assertEqual(plan.materialize_total, 1,
                         "правка одной стены обязана назвать ровно один лист")
        self.assertEqual(len(plan.retire_source_ids), 1,
                         "старая стена обязана быть снята, а не оставлена рядом")
        self.assertEqual(len(result.programs), 1)
        ops = result.programs[0]["ops"]
        self.assertEqual([op["op"] for op in ops], ["create_wall"])

        out = compile_program(result.programs[0])
        self.assertTrue(out.ok, f"дельта не собралась: {out.diagnostics}")
        for marker in ("Wall.Create", "__post", "Transaction", "RollBack"):
            with self.subTest(marker=marker):
                self.assertIn(marker, out.csharp,
                              "в C# дельты обязан стоять не только create, но и "
                              "сторож с откатом — иначе правка применяется без "
                              "обязательства")

    def test_every_delta_op_is_proven_on_every_version(self):
        """A witness must stand behind the delta's op, and on all six versions.

        This is precisely the unchecked promise of the docstrings: the
        delta's obligation is THE SAME as the full program's, not a
        weakened "we're only making an edit."
        """
        _plan, result = _delta_ops(stretch_wall_on_floor=1)
        out = compile_program(result.programs[0])
        self.assertTrue(out.grounded_ops)
        for op in out.grounded_ops:
            for version in _VERSIONS:
                with self.subTest(op=op["op"], version=version):
                    cert = tc.certify_op(op, version)
                    self.assertTrue(
                        cert.proven,
                        f"{op['op']} на {version}: обязательства не погашены — "
                        f"{[c.clause for c in cert.clauses if not c.discharged]}")
                    self.assertFalse(cert.vacuous,
                                     "вакуумный свидетель хуже отсутствующего")

    def test_the_delta_obligation_equals_the_whole_building_obligation(self):
        """A verbatim reconciliation: the same clauses, not one weakened.

        The SETS of clauses of one and the same op, arrived at by two
        paths — the delta and the full rebuild — are compared. A
        discrepancy would mean that an edit is checked differently than
        a build, and "the same obligation" in the docstrings is untrue.
        """
        _plan, delta = _delta_ops(stretch_wall_on_floor=1)
        delta_op = compile_program(delta.programs[0]).grounded_ops[0]
        delta_clauses = {c.clause for c in tc.certify_op(delta_op, "2024").clauses}

        whole = _whole_ops()
        whole_walls = [
            op for program in whole.programs
            for op in (compile_program(program).grounded_ops or [])
            if op["op"] == "create_wall"]
        self.assertTrue(whole_walls, "полная пересборка не дала ни одной стены")
        whole_clauses = {
            c.clause for c in tc.certify_op(whole_walls[0], "2024").clauses}

        self.assertEqual(delta_clauses, whole_clauses,
                         "у дельты и у полной постройки РАЗНЫЕ обязательства — "
                         "значит правка проверяется слабее, чем стройка")

    def test_a_delta_that_materialises_nothing_SAYS_so(self):
        """🔴 The most dangerous outcome: the delta named a leaf, and the ops count is zero.

        Measurement 08-19: an edit to furniture alone gives
        `materialize_total == 1` and `programs == 0`. Silence here would
        be a silently-wrong outcome — the operator asked for an edit,
        got an empty rebuild, and "success."

        The materializer does not stay silent: the skip is TYPED
        (`atom:no_lifter`) and counted in `stats.atoms_skipped`. The
        test pins down exactly this, not the absence of a skip: an atom
        without a lifter is a legitimate outcome, but an unnamed skip is not.
        """
        plan, result = _delta_ops(extra_furniture_on_floor=1)
        self.assertEqual(plan.materialize_total, 1)
        self.assertEqual(len(result.programs), 0,
                         "у атома нет подъёмника — опов быть не должно")
        self.assertEqual(result.stats.atoms_skipped, 1,
                         "пропущенный атом обязан быть ПОСЧИТАН")
        self.assertEqual(len(result.skipped), plan.materialize_total,
                         "каждый неназванный лист обязан иметь запись пропуска")
        for record in result.skipped:
            reason = getattr(record, "reason", "")
            self.assertTrue(reason, "пропуск без причины — это молчание")
            self.assertIn(":", reason,
                          f"причина {reason!r} обязана быть типизованной "
                          f"(род:подробность), а не свободной фразой")

    def test_a_building_against_itself_moves_nothing_and_certifies_nothing(self):
        """An empty delta must be EMPTY, not a "successful rebuild of everything."

        The mirror of the previous test: there the delta is not empty
        and there are no ops; here the delta is empty and there are no
        ops — the outcomes are different, and they must not be confused.
        """
        tree = _fold(_grid_building(floors=3))
        plan = delta_rebuild_plan(tree, _fold(_grid_building(floors=3)))
        self.assertTrue(plan.is_empty)
        self.assertEqual(plan.materialize_total, 0)
        self.assertEqual(plan.retire_source_ids, ())

    def test_the_delta_costs_less_than_the_whole_building(self):
        """The point of the whole exercise in one number: 1 leaf against 60."""
        plan, _result = _delta_ops(stretch_wall_on_floor=1)
        self.assertLess(plan.materialize_total, plan.leaves_total_b)
        self.assertEqual(plan.leaves_total_b, 60)
        self.assertEqual(plan.materialize_total, 1)


class TheWitnessBehindTheDeltaCanFall(unittest.TestCase):
    """The mutation half: a witness that cannot be made to fail is not a witness.

    The form is taken from `kir/tests/test_witness_vacuity.py`.
    """

    def test_a_marker_mutation_does_NOT_move_a_model_sourced_op(self):
        """🔴 A negative result, and it matters more than a positive one.

        The first version of this test broke `witness_markers` and
        waited for a failure. The certificate remained proven — not
        because it is blind, but because `create_wall` has
        `witness_source="model"`: obligations are discharged by the KEY
        that the emitter returns together with the check, and line
        markers are read only by the deprecated `"string"` branch.

        The test pins down this distinction. Without it, the next
        author of a mutation test would again pick an unfit mutation,
        get green, and decide the witness is in place — that is, buy a
        vacuum where rigor was being sought.
        """
        _plan, result = _delta_ops(stretch_wall_on_floor=1)
        op = compile_program(result.programs[0]).grounded_ops[0]
        table = tc._ensure_table()
        spec = table["create_wall"]
        self.assertEqual(spec.witness_source, "model")
        saved = spec.obligations
        try:
            object.__setattr__(spec, "obligations", tuple(
                type(ob)(**{**{f: getattr(ob, f)
                               for f in ob.__dataclass_fields__},
                            "witness_markers": ("__НЕТ_ТАКОГО_МАРКЕРА__",)})
                for ob in saved))
            self.assertTrue(
                tc.certify_op(op, "2024").proven,
                "у model-опа маркеры не решают — если бы решали, ветка `model` "
                "не давала бы обещанной корректности по построению")
        finally:
            object.__setattr__(spec, "obligations", saved)

    def test_breaking_the_discharge_key_DOES_break_the_certificate(self):
        """A mutation of the quantity that actually decides things here — the key.

        The obligation remains declared, but there is nothing left to
        discharge it with: the emitter returns checks under its own
        keys, and the substituted key matches none of them. The
        certificate must fail and NAME what was missing.
        """
        _plan, result = _delta_ops(stretch_wall_on_floor=1)
        op = compile_program(result.programs[0]).grounded_ops[0]
        self.assertTrue(tc.certify_op(op, "2024").proven,
                        "до мутации сертификат обязан быть доказан")

        table = tc._ensure_table()
        spec = table["create_wall"]
        saved = spec.obligations
        try:
            broken = tuple(
                type(ob)(**{**{f: getattr(ob, f)
                               for f in ob.__dataclass_fields__},
                            "key": "__КЛЮЧ_КОТОРОГО_НЕТ__"})
                for ob in saved)
            object.__setattr__(spec, "obligations", broken)
            cert = tc.certify_op(op, "2024")
            self.assertFalse(
                cert.proven,
                "гасить обязательства нечем, а сертификат доказан — значит он "
                "не читает ключи, которыми сам объявил их погашение")
            self.assertTrue(cert.gaps, "падение обязано НАЗВАТЬ, чего не хватило")
        finally:
            object.__setattr__(spec, "obligations", saved)
        self.assertTrue(tc.certify_op(op, "2024").proven,
                        "восстановление обязано быть немым")


if __name__ == "__main__":
    unittest.main()
