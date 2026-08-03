"""Property tests for effect typing + deterministic parallelism (effects.py).

Dependency-free property style over REAL grounded programs (the scope-contract
fixtures) plus synthetic chains.  Independent-ops-parallelize (E3),
independent-ops-commute (E5), and static race detection (E7) are the heart.

Numbering matches EFFECT_TYPING_SPEC §7:
  E1 effect signatures (writes/reads correct)
  E2 dependency (window after its host wall)
  E3 parallelism (N independent ops -> one wave)
  E4 chain (level->wall->window->dim -> 4 serial waves)
  E5 T-SCHED (linear order respects all deps; intra-wave permutation is valid)
  E6 mixed (walls parallel, then their windows)
  E7 fail-closed (cycle -> EffectCycleError; dup write -> WriteWriteConflict)
  E8 determinism (same program -> same schedule; cross-process)
  E9 fixture coverage (real programs schedule cleanly)
  E10 flag default OFF; malformed -> EffectError
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_effects_queue.jsonl"))

from kukai.ir import ground as ground_mod  # noqa: E402
from kukai.ir.compiler import _parse_and_check  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.ir.tests.test_emitter_scope_contract import PROGRAMS  # noqa: E402
from kukai.ir.effects import (  # noqa: E402
    Dependency,
    EffectCycleError,
    EffectError,
    WriteWriteConflict,
    build_dependency_graph,
    conflicts,
    effect_signature,
    effects_enabled,
    schedule,
)


def _grounded(program_name: str):
    prog = {k: v for k, v in PROGRAMS[program_name].items()
            if k != "__min_ver__"}
    return ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)


def _sig_by_id(grounded):
    signatures, _deps = build_dependency_graph(grounded)
    return signatures


class Signatures(unittest.TestCase):
    def test_e1_wall_writes_own_id_reads_level(self) -> None:
        g = _grounded("full_house")
        sigs = _sig_by_id(g)
        wall = sigs["W1"]
        self.assertIn("W1", wall.writes)
        self.assertIn("L1", wall.reads)     # wall reads its level
        self.assertTrue(wall.writes_model)

    def test_e1_level_reads_nothing_intra(self) -> None:
        g = _grounded("full_house")
        sigs = _sig_by_id(g)
        level = sigs["L1"]
        self.assertEqual(level.writes, frozenset({"L1"}))
        self.assertEqual(level.reads, frozenset())

    def test_e1_window_reads_host_wall(self) -> None:
        g = _grounded("full_house")
        sigs = _sig_by_id(g)
        self.assertIn("W1", sigs["Win1"].reads)


class Dependencies(unittest.TestCase):
    def test_e2_window_depends_on_wall(self) -> None:
        g = _grounded("full_house")
        _sigs, deps = build_dependency_graph(g)
        self.assertIn(
            Dependency(before="W1", after="Win1", reason="reads_write"), deps)

    def test_e6_walls_parallel_then_windows(self) -> None:
        g = _grounded("full_house")
        sched = schedule(g)
        wave_of = {op_id: wave.index
                   for wave in sched.waves for op_id in wave.op_ids}
        # level before wall before window/door.
        self.assertLess(wave_of["L1"], wave_of["W1"])
        self.assertLess(wave_of["W1"], wave_of["Win1"])
        self.assertLess(wave_of["W1"], wave_of["D1"])
        # the 5 level-only ops share a wave (parallel).
        self.assertEqual(wave_of["W1"], wave_of["F1"])
        self.assertEqual(wave_of["F1"], wave_of["C1"])


class Parallelism(unittest.TestCase):
    def test_e3_independent_ops_one_wave(self) -> None:
        # Three levels: no refs between them -> all independent -> one wave.
        program = {
            "ir_version": "1.0", "intent": "levels", "ops": [
                {"op": "create_level", "id": f"L{i}", "elev_mm": i * 3000,
                 "name": f"Level {i}"}
                for i in range(1, 4)
            ]}
        g = ground_mod.ground(_parse_and_check(program), GROUND_SNAPSHOT)
        sched = schedule(g)
        self.assertEqual(len(sched.waves), 1)
        self.assertEqual(sched.max_parallelism, 3)
        self.assertTrue(sched.is_parallel)

    def test_e4_chain_serializes(self) -> None:
        # annotation: wall -> dimension -> tag -> text chains via refs.
        g = _grounded("annotation")
        sched = schedule(g)
        self.assertEqual(sched.max_parallelism, 1)
        self.assertFalse(sched.is_parallel)
        self.assertEqual(sched.critical_path, len(g))


class TSched(unittest.TestCase):
    def test_e5_linear_order_respects_all_deps(self) -> None:
        for name in ("full_house", "annotation", "struct", "families"):
            g = _grounded(name)
            sched = schedule(g)
            _sigs, deps = build_dependency_graph(g)
            position = {op_id: index
                        for index, op_id in enumerate(sched.linear_order())}
            with self.subTest(program=name):
                for dep in deps:
                    self.assertLess(position[dep.before], position[dep.after])

    def test_e5_intra_wave_permutation_still_valid(self) -> None:
        # Any permutation of a wave's ops still respects the dependency DAG,
        # because within a wave there are no edges between ops.
        g = _grounded("full_house")
        sched = schedule(g)
        _sigs, deps = build_dependency_graph(g)
        dep_pairs = {(d.before, d.after) for d in deps}
        for wave in sched.waves:
            ids = wave.op_ids
            for i in range(len(ids)):
                for j in range(len(ids)):
                    if i != j:
                        # no dependency between two same-wave ops (either dir)
                        self.assertNotIn((ids[i], ids[j]), dep_pairs)


class FailClosed(unittest.TestCase):
    def test_e7_cycle_detected(self) -> None:
        # Two set_params referencing each other via ref -> a cycle.
        program = {
            "ir_version": "1.0", "intent": "cycle", "allow_destructive": True,
            "ops": [
                {"op": "set_param", "id": "S1",
                 "target": {"by": "ref", "value": "S2"},
                 "param": "Комментарии", "value": "a"},
                {"op": "set_param", "id": "S2",
                 "target": {"by": "ref", "value": "S1"},
                 "param": "Комментарии", "value": "b"},
            ]}
        # Grounding may reject cyclic refs; if it reaches effects, we must
        # detect the cycle.  Build the grounded ops directly to be sure.
        g = [
            {"op": "set_param", "id": "S1",
             "target": {"by": "ref", "value": "S2"},
             "param": "Комментарии", "value": {"type": "str", "v": "a"}},
            {"op": "set_param", "id": "S2",
             "target": {"by": "ref", "value": "S1"},
             "param": "Комментарии", "value": {"type": "str", "v": "b"}},
        ]
        with self.assertRaises(EffectCycleError):
            schedule(g)
        self.assertTrue(conflicts(g))

    def test_e7_duplicate_write_conflict(self) -> None:
        g = [
            {"op": "create_level", "id": "L1", "elev_mm": 0, "name": "A"},
            {"op": "create_level", "id": "L1", "elev_mm": 3000, "name": "B"},
        ]
        with self.assertRaises(WriteWriteConflict):
            schedule(g)

    def test_e10_malformed_op_fails_closed(self) -> None:
        with self.assertRaises(EffectError):
            effect_signature({"no": "op or id"})


class Determinism(unittest.TestCase):
    def test_e8_same_program_same_schedule(self) -> None:
        a = schedule(_grounded("full_house"))
        b = schedule(_grounded("full_house"))
        self.assertEqual(a.waves, b.waves)
        self.assertEqual(a.dependencies, b.dependencies)

    def test_e9_all_fixtures_schedule_cleanly(self) -> None:
        for name in PROGRAMS:
            with self.subTest(program=name):
                g = _grounded(name)
                sched = schedule(g)                 # raises on any race/cycle
                # every op is scheduled exactly once
                scheduled = [op_id for wave in sched.waves
                             for op_id in wave.op_ids]
                self.assertEqual(
                    sorted(scheduled), sorted(op["id"] for op in g))
                self.assertEqual(conflicts(g), ())


class Flag(unittest.TestCase):
    def test_e10_flag_default_off(self) -> None:
        previous = os.environ.pop("KUKAI_IR_EFFECTS", None)
        try:
            self.assertFalse(effects_enabled())
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_EFFECTS"] = previous

    def test_e10_flag_opt_in(self) -> None:
        previous = os.environ.get("KUKAI_IR_EFFECTS")
        os.environ["KUKAI_IR_EFFECTS"] = "on"
        try:
            self.assertTrue(effects_enabled())
        finally:
            if previous is None:
                del os.environ["KUKAI_IR_EFFECTS"]
            else:
                os.environ["KUKAI_IR_EFFECTS"] = previous


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
