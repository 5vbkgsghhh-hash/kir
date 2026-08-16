"""Property tests for the DECOMPILE A3 materializer (materialize.py).

The materializer turns frozen L1 op-leaves back into RAW compiler-input programs
that the ordinary KIR front consumes with no new trust surface.  Its central
theorem is T-MAT: materializing op-leaves and running them back through the
compiler front (``_parse_and_check`` + ``ground(snapshot=None)``) reproduces the
EXACT canonical op multiset of the source op-leaves (selectors compared by id).

Coverage:
  T-MAT-REAL   whole-lot31 tree: canon-multiset(source op-leaves) ==
               canon-multiset(re-lifted materialized programs)
  T-MAT-SYNTH  synthetic non-zero-origin hosted chain (wall + door + window
               with sill): same theorem, plus the ``offset_mm`` translation
  CHUNK        Д5 laws: host-atomicity (a wall + its hosted stay in one chunk,
               wall first), rooms in the tail, stairs solo, chunk size ~target
  DATUM        Д3: levels/grids skipped by default, materialized when asked
  BULK         compiler bulk flag: 21 -> KIR-L001, 300 -> ok, 321 -> refused
  GROUP        native_group bridge produces a compilable create_group program
  DET          identical leaves -> byte-identical programs (I4)
"""
from __future__ import annotations

import json
import os
import pickle
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest import mock

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_mat_queue.jsonl"))

from kukai.ir import ground as ground_mod  # noqa: E402
from kukai.ir import spec  # noqa: E402
from kukai.ir.compiler import (  # noqa: E402
    MAX_BULK_OPS,
    MAX_OPS_PER_PROGRAM,
    _parse_and_check,
    compile_program,
    plan_program,
)
from kukai.ir.diag import Diagnostic, KirRefusal  # noqa: E402
from kukai.ir.decompile.fold import iter_l1_leaves  # noqa: E402
from kukai.ir.decompile.geom_extract import extract_geometry  # noqa: E402
from kukai.ir.decompile.l1_schema import stable_l1_id, validate_l1_nodes  # noqa: E402
from kukai.ir.decompile.materialize import (  # noqa: E402
    MATERIALIZATION_ACCOUNTING_SCHEMA,
    MaterializeError,
    MaterializationAccounting,
    MaterializeResult,
    ProgramPlanCheck,
    SkipRecord,
    _op_id,
    component_to_group_program,
    leaves_to_program,
)
from kukai.ir.decompile.recompile import IDENTITY_TRANSFORM, GmMesh  # noqa: E402
from kukai.ir.decompile.tests.test_geom_extract import (  # noqa: E402
    _element as _geometry_element,
    _part as _geometry_part,
    _payload as _geometry_payload,
    _triangle_mesh,
    _translated,
)

_LOT31_TREE = Path.home() / "lot31_full" / "_tree_cache.pkl"
_DATUM_OPS = {"create_level", "create_grid"}


# ---------------------------------------------------------------------------
# Canonical id-form used by T-MAT (selectors compared by id, coords by mm-grid)
# ---------------------------------------------------------------------------


def _round3(value: float) -> float:
    # The materializer's mm-grid rounding and the compiler's float coercion both
    # act at sub-mm scale; 3 decimals is below CANON_MM and above fp noise.
    return round(float(value), 3)


def _selector_to_id(value):
    """Reduce ANY selector dialect (source or grounded/materialized) to a token.

    The source leaf carries ``{"by": ..., "_id": ID}`` / ``{"ref": l1_id}``; the
    materialized+grounded op carries ``{"__grounded__": {"id": ID, ...}}`` /
    ``{"by": "ref", "value": op_id}``.  Both reduce to the same id/host token so
    the multisets are directly comparable.
    """

    if isinstance(value, list):
        return [_selector_to_id(item) for item in value]
    if isinstance(value, dict):
        grounded = value.get("__grounded__")
        if isinstance(grounded, dict):
            if "ref" in grounded:
                return {"__hostref__": grounded["ref"]}
            return {"__idref__": int(grounded["id"])}
        if "by" in value and "_id" in value:           # source named/family ref
            return {"__idref__": int(value["_id"])}
        if value.get("by") == "element_id":            # materialized element_id
            return {"__idref__": int(value["value"])}
        if value.get("by") == "ref":                   # materialized host ref
            return {"__hostref__": value["value"]}
        if "ref" in value and "by" not in value:       # source host ref
            return value                               # handled by caller
        return {key: _selector_to_id(item) for key, item in sorted(value.items())}
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _round3(value)
    return value


def _canon_source(leaf, host_op_id_by_l1_id) -> tuple[str, str]:
    """Canonical id-form of a source op-leaf (host l1-ref -> host op id)."""

    def rewrite(value):
        if isinstance(value, dict):
            if "ref" in value and "by" not in value:
                op_id = host_op_id_by_l1_id.get(value["ref"], value["ref"])
                return {"__hostref__": op_id}
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        return value

    params = _selector_to_id(rewrite(dict(leaf["params"])))
    return (leaf["op_name"],
            json.dumps(params, sort_keys=True, ensure_ascii=False))


def _canon_materialized(op) -> tuple[str, str]:
    """Canonical id-form of a grounded materialized op-dict."""

    params = {k: v for k, v in op.items()
              if k not in ("op", "id", "__host_wall__")}
    return (op["op"],
            json.dumps(_selector_to_id(params), sort_keys=True,
                       ensure_ascii=False))


def _relift_programs(programs) -> Counter:
    """Run every materialized program back through the compiler front.

    Returns the canonical id-multiset of the grounded ops — the RHS of T-MAT.
    ``ground(snapshot=None)`` is used because element_id/ref programs need no
    census; a program that DID need one would raise (a translation bug).
    """

    multiset: Counter = Counter()
    for program in programs:
        normed = _parse_and_check(program, bulk=True)
        grounded = ground_mod.ground(normed, None)
        for op in grounded:
            multiset[_canon_materialized(op)] += 1
    return multiset


# ---------------------------------------------------------------------------
# Synthetic L1 op-leaf builders (direct L1 dicts, schema-valid)
# ---------------------------------------------------------------------------


def _op_leaf(op_name, source_id, params, *, level_name=None, anchor=None):
    return {
        "kind": "op",
        "op_name": op_name,
        "_id": stable_l1_id("op", source_id),
        "type_name": "T",
        "params": params,
        "source_element_id": source_id,
        "level_name": level_name,
        "anchor_mm": list(anchor) if anchor is not None else None,
    }


def _atom_leaf(source_id, category="OST_Furniture"):
    return {
        "kind": "atom",
        "_id": stable_l1_id("atom", source_id),
        "category": category,
        "category_ru": "мебель",
        "type_name": "T",
        "bbox_min_mm": [0.0, 0.0, 0.0],
        "bbox_max_mm": [100.0, 100.0, 100.0],
        "source_element_id": source_id,
        "level_name": "L1",
        "anchor_mm": [50.0, 50.0, 0.0],
        "reason": {"code": "no_lifter", "detail": "synthetic atom"},
    }


def _hosted_chain(origin=(0.0, 0.0, 0.0)):
    """A wall hosting a door and a window (with sill), all at ``origin``.

    Returns the three L1 op-leaves; the door/window ``host`` refs point at the
    wall's L1 ``_id`` (the frozen dialect), exactly as ``lift.py`` emits them.
    """

    ox, oy, oz = origin
    wall = _op_leaf(
        "create_wall", "1001",
        {
            "p0_mm": [ox, oy],
            "p1_mm": [ox + 5000.0, oy],
            "level": {"by": "name", "value": "L1", "_id": "500"},
            "height_mm": 2800.0,
            "type": {"by": "name", "value": "W200", "_id": "600"},
        },
        level_name="L1", anchor=(ox + 2500.0, oy, oz))
    wall_l1 = wall["_id"]
    door = _op_leaf(
        "create_door", "1002",
        {
            "host": {"ref": wall_l1},
            "offset_mm": 1000.0,
            "symbol": {"by": "name", "value": "D900", "_id": "700"},
        },
        level_name="L1", anchor=(ox + 1000.0, oy, oz))
    window = _op_leaf(
        "create_window", "1003",
        {
            "host": {"ref": wall_l1},
            "offset_mm": 3000.0,
            "sill_mm": 900.0,
            "symbol": {"by": "name", "value": "Win1200", "_id": "800"},
        },
        level_name="L1", anchor=(ox + 3000.0, oy, oz + 900.0))
    return [wall, door, window]


# ---------------------------------------------------------------------------
# T-MAT — synthetic
# ---------------------------------------------------------------------------


class TMatSynthetic(unittest.TestCase):
    def test_hosted_chain_nonzero_origin_roundtrips(self):
        leaves = _hosted_chain(origin=(123000.0, -45000.0, 7000.0))
        validate_l1_nodes(leaves)  # schema-valid fixtures
        result = leaves_to_program(leaves, chunk_target=250)
        self.assertEqual(len(result.programs), 1)     # host-atomic single chunk
        self.assertEqual(result.stats.materialized_ops, 3)
        self.assertFalse(result.skipped)

        host_map = {leaf["_id"]: _op_id(leaf["source_element_id"])
                    for leaf in leaves}
        lhs = Counter(_canon_source(leaf, host_map) for leaf in leaves)
        rhs = _relift_programs(result.programs)
        self.assertEqual(lhs, rhs)

    def test_offset_translates_coordinates_faithfully(self):
        base = _hosted_chain(origin=(0.0, 0.0, 0.0))
        shifted = _hosted_chain(origin=(200000.0, 0.0, 0.0))
        offset = (200000.0, 0.0, 0.0)

        base_result = leaves_to_program(base, offset_mm=offset)
        shifted_result = leaves_to_program(shifted)
        # Translating base by +offset must equal materializing the pre-shifted
        # leaves (coords move, ids/selectors do not) — proves offset uses the
        # canonical _translate_leaf and touches only coordinate fields.
        self.assertEqual(base_result.programs, shifted_result.programs)

    def test_door_after_wall_within_chunk(self):
        leaves = _hosted_chain()
        program = leaves_to_program(leaves).programs[0]
        op_ids = [op["id"] for op in program["ops"]]
        wall_id = _op_id("1001")
        self.assertEqual(op_ids[0], wall_id)          # host first (Д5d)
        # the hosted ops' host ref resolves to the wall's op id
        for op in program["ops"]:
            if op["op"] in ("create_door", "create_window"):
                self.assertEqual(op["host"], {"by": "ref", "value": wall_id})
        # and the whole thing compiles end-to-end (parse+ground)
        normed = _parse_and_check(program, bulk=True)
        ground_mod.ground(normed, None)

    def test_retains_one_immutable_typed_plan_per_program(self):
        result = leaves_to_program(_hosted_chain(), chunk_target=250)
        self.assertTrue(result.compiler_ready)
        self.assertEqual(len(result.plans), len(result.programs))
        self.assertEqual(len(result.plan_checks), len(result.programs))
        for plan, check in zip(result.plans, result.plan_checks):
            self.assertIsNotNone(plan)
            self.assertTrue(check.accepted)
            self.assertRegex(check.source_digest, r"^[0-9a-f]{64}$")
            self.assertEqual(check.plan_digest, plan.plan_digest)
            self.assertEqual(check.diagnostic_codes, ())
            self.assertEqual(check.as_dict()["plan_digest"], plan.plan_digest)

    def test_detached_programs_cannot_mutate_an_accepted_plan(self):
        result = leaves_to_program(_hosted_chain(), chunk_target=250)
        self.assertTrue(result.compiler_ready)
        original_id = result.programs[0]["ops"][0]["id"]
        plan_digest = result.plans[0].plan_digest

        detached = result.programs
        detached[0]["ops"][0]["id"] = "forged"
        detached.append({"ir_version": "1.0", "ops": []})

        self.assertEqual(result.programs[0]["ops"][0]["id"], original_id)
        self.assertEqual(len(result.programs), len(result.plans))
        self.assertEqual(result.plans[0].plan_digest, plan_digest)
        self.assertEqual(
            plan_program(result.programs[0], bulk=True).plan_digest,
            plan_digest,
        )

    def test_constructor_defensively_copies_programs_and_record_lists(self):
        source = leaves_to_program(_hosted_chain(), chunk_target=250)
        programs = source.programs
        skipped = source.skipped
        clone = MaterializeResult(
            programs=programs,
            skipped=skipped,
            escrowed=source.escrowed,
            stats=source.stats,
            accounting=source.accounting,
            plans=source.plans,
            plan_checks=source.plan_checks,
        )

        programs[0]["ops"][0]["id"] = "forged"
        skipped.append(SkipRecord("x", "atom", "forged"))

        self.assertNotEqual(clone.programs[0]["ops"][0]["id"], "forged")
        self.assertFalse(clone.skipped)

    def test_plan_refusal_is_evidence_and_does_not_erase_raw_program(self):
        refusal = KirRefusal([Diagnostic(
            code="KIR-T001",
            message_ru="synthetic planning refusal",
        )])
        with mock.patch(
                "kukai.ir.decompile.materialize.plan_program",
                side_effect=refusal):
            result = leaves_to_program(_hosted_chain(), chunk_target=250)

        self.assertEqual(len(result.programs), 1)
        self.assertFalse(result.compiler_ready)
        self.assertEqual(result.plans, (None,))
        self.assertEqual(result.plan_checks[0].diagnostic_codes,
                         ("KIR-T001",))
        self.assertFalse(result.plan_checks[0].accepted)

    def test_plan_evidence_cannot_claim_acceptance_without_a_digest(self):
        with self.assertRaises(ValueError):
            ProgramPlanCheck(
                program_index=0, accepted=True, source_digest="0" * 64)
        with self.assertRaises(ValueError):
            ProgramPlanCheck(
                program_index=0, accepted=False, source_digest="0" * 64)
        with self.assertRaises(ValueError):
            MaterializeResult(programs=[{
                "ir_version": "1.0", "ops": [],
            }])

    def test_plan_check_is_bound_to_exact_raw_program(self):
        result = leaves_to_program(_hosted_chain(), chunk_target=250)
        forged_check = replace(
            result.plan_checks[0],
            source_digest="0" * 64,
        )
        with self.assertRaisesRegex(ValueError, "source digest"):
            MaterializeResult(
                programs=result.programs,
                skipped=result.skipped,
                escrowed=result.escrowed,
                stats=result.stats,
                accounting=result.accounting,
                plans=result.plans,
                plan_checks=(forged_check,),
            )

    def test_v2_accounting_has_exact_shape_and_total_unique_rows(self):
        leaves = _hosted_chain()
        result = leaves_to_program(leaves)
        payload = result.accounting.as_dict()

        self.assertEqual(
            payload["schema_version"], MATERIALIZATION_ACCOUNTING_SCHEMA)
        self.assertEqual(set(payload), {
            "schema_version", "input_digest", "programs_digest", "counts",
            "records", "receipt_digest",
        })
        self.assertEqual(payload["counts"]["input_leaves"], len(leaves))
        self.assertEqual(payload["counts"]["emitted_semantic_ops"], 3)
        self.assertEqual(
            {row["source_id"] for row in payload["records"]},
            {leaf["source_element_id"] for leaf in leaves})
        self.assertTrue(all(set(row) == {
            "source_id", "leaf_id", "leaf_kind", "category",
            "disposition", "reason", "op_id", "program_index",
            "element_id", "evidence_state",
        } for row in payload["records"]))

    def test_duplicate_source_or_l1_identity_is_refused_before_indexing(self):
        first = _op_leaf("query_count", "9700", {"kind": "wall"})
        repeated_source = _op_leaf(
            "query_count", "9700", {"kind": "door"})
        repeated_source["_id"] = "different-leaf-id"
        with self.assertRaisesRegex(MaterializeError, "duplicate source"):
            leaves_to_program([first, repeated_source])

        repeated_leaf_id = _op_leaf(
            "query_count", "9701", {"kind": "door"})
        repeated_leaf_id["_id"] = first["_id"]
        with self.assertRaisesRegex(MaterializeError, "duplicate L1"):
            leaves_to_program([first, repeated_leaf_id])

    def test_unknown_atom_reason_is_refused_not_residualized(self):
        atom = _atom_leaf("9702")
        atom["reason"] = {"code": "alien_reason", "detail": "forged"}

        with self.assertRaisesRegex(MaterializeError, "closed AtomReason"):
            leaves_to_program([atom])

    def test_missing_accounting_row_cannot_cover_an_emitted_wire_op(self):
        result = leaves_to_program(_hosted_chain())
        records = result.accounting.records[:-1]
        forged_accounting = MaterializationAccounting(
            input_digest=result.accounting.input_digest,
            programs_digest=result.accounting.programs_digest,
            records=records,
            programs_count=result.accounting.programs_count,
            emitted_ops_count=result.accounting.emitted_ops_count - 1,
        )

        with self.assertRaisesRegex(ValueError, "accounting.*wire"):
            MaterializeResult(
                programs=result.programs,
                skipped=result.skipped,
                escrowed=result.escrowed,
                stats=result.stats,
                accounting=forged_accounting,
                plans=result.plans,
                plan_checks=result.plan_checks,
            )

    def test_stats_cannot_disagree_with_authoritative_accounting(self):
        result = leaves_to_program(_hosted_chain())
        forged_stats = replace(result.stats, materialized_ops=0)

        with self.assertRaisesRegex(ValueError, "stats.materialized_ops"):
            MaterializeResult(
                programs=result.programs,
                skipped=result.skipped,
                escrowed=result.escrowed,
                stats=forged_stats,
                accounting=result.accounting,
                plans=result.plans,
                plan_checks=result.plan_checks,
            )


# ---------------------------------------------------------------------------
# T-MAT — real building
# ---------------------------------------------------------------------------


@unittest.skipUnless(_LOT31_TREE.exists(), "lot31 tree cache absent")
class TMatReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.leaves = list(iter_l1_leaves(
            pickle.loads(_LOT31_TREE.read_bytes())))

    def test_theorem_holds_on_whole_building(self):
        result = leaves_to_program(self.leaves, chunk_target=250)
        host_map = {
            leaf["_id"]: _op_id(leaf["source_element_id"])
            for leaf in self.leaves
            if leaf["kind"] == "op" and leaf["op_name"] not in _DATUM_OPS
        }
        source_ops = [
            leaf for leaf in self.leaves
            if leaf["kind"] == "op" and leaf["op_name"] not in _DATUM_OPS
        ]
        lhs = Counter(_canon_source(leaf, host_map) for leaf in source_ops)
        rhs = _relift_programs(result.programs)
        self.assertEqual(
            lhs, rhs,
            f"T-MAT divergence: missing={sum((lhs - rhs).values())} "
            f"extra={sum((rhs - lhs).values())}")

    def test_every_program_grounds_without_snapshot(self):
        result = leaves_to_program(self.leaves, chunk_target=250)
        for program in result.programs:
            normed = _parse_and_check(program, bulk=True)
            # snapshot=None: pure element_id/ref programs must not need a census
            ground_mod.ground(normed, None)

    def test_all_op_leaves_accounted(self):
        result = leaves_to_program(self.leaves)
        atoms = sum(1 for lf in self.leaves if lf["kind"] == "atom")
        datums = sum(1 for lf in self.leaves
                     if lf["kind"] == "op" and lf["op_name"] in _DATUM_OPS)
        non_datum_ops = result.stats.op_leaves - datums
        self.assertEqual(result.stats.materialized_ops, non_datum_ops)
        self.assertEqual(result.stats.atoms_skipped, atoms)
        self.assertEqual(result.stats.datums_skipped, datums)
        # nothing silently lost: skips + materialized == every leaf
        self.assertEqual(
            len(result.skipped) + result.stats.materialized_ops,
            len(self.leaves))


# ---------------------------------------------------------------------------
# Chunk laws (Д5)
# ---------------------------------------------------------------------------


class ChunkLaws(unittest.TestCase):
    def _many_walls(self, count, base_id=2000):
        leaves = []
        for i in range(count):
            x = float(i) * 6000.0
            leaves.append(_op_leaf(
                "create_wall", str(base_id + i),
                {
                    "p0_mm": [x, 0.0],
                    "p1_mm": [x + 5000.0, 0.0],
                    "level": {"by": "name", "value": "L1", "_id": "500"},
                    "height_mm": 2800.0,
                    "type": {"by": "name", "value": "W200", "_id": "600"},
                },
                level_name="L1", anchor=(x + 2500.0, 0.0, 0.0)))
        return leaves

    def test_chunk_size_near_target(self):
        leaves = self._many_walls(1000)
        result = leaves_to_program(leaves, chunk_target=250)
        sizes = [len(p["ops"]) for p in result.programs]
        self.assertTrue(all(size <= 250 for size in sizes))
        self.assertGreaterEqual(min(sizes[:-1] or sizes), 1)
        self.assertEqual(sum(sizes), 1000)

    def test_host_group_never_split_across_boundary(self):
        # A wall whose hosted door would land in the next chunk must pull the
        # door into the SAME chunk (host-atomicity Д5a).
        leaves = self._many_walls(3)          # 3 walls
        # add a door hosted on the LAST wall, id-sorted after the walls
        last_wall = leaves[-1]
        door = _op_leaf(
            "create_door", "9999",
            {
                "host": {"ref": last_wall["_id"]},
                "offset_mm": 1000.0,
                "symbol": {"by": "name", "value": "D", "_id": "700"},
            },
            level_name="L1", anchor=(0.0, 0.0, 0.0))
        result = leaves_to_program(leaves + [door], chunk_target=2)
        # find the chunk containing the door; its host wall must be present too
        wall_op_id = _op_id(last_wall["source_element_id"])
        for program in result.programs:
            ids = [op["id"] for op in program["ops"]]
            if _op_id("9999") in ids:
                self.assertIn(wall_op_id, ids)
                self.assertLess(ids.index(wall_op_id), ids.index(_op_id("9999")))
                break
        else:
            self.fail("door op not found in any chunk")

    def test_non_host_ref_never_crosses_a_chunk_boundary(self):
        """Дословный провал башни 02.08: марка на двери уезжала в чужой чанк.

        `create_tag.target` — ссылка, но НЕ host, поэтому старая группировка по
        `host` считала марку собственным корнем и паковала отдельно от двери.
        `_translate_reference` разрешает ref по карте всего прогона, так что
        программа получала ссылку на оп, которого в ней нет, и компилятор
        законно отказывал `KIR-L003`. На `k2_ar_rd_v8` это стоило 39 чанков
        из 133; Snowdon дефекта не показывает — помещается в один чанк.
        """

        leaves = self._many_walls(3)
        last_wall = leaves[-1]
        door = _op_leaf(
            "create_door", "9990",
            {
                "host": {"ref": last_wall["_id"]},
                "offset_mm": 1000.0,
                "symbol": {"by": "name", "value": "D", "_id": "700"},
            },
            level_name="L1", anchor=(0.0, 0.0, 0.0))
        tag = _op_leaf(
            "create_tag", "9991",
            {
                "target": {"ref": door["_id"]},
                "in_view": {"by": "name", "value": "V", "_id": "701"},
            },
            level_name="L1", anchor=(0.0, 0.0, 0.0))

        result = leaves_to_program(leaves + [door, tag], chunk_target=2)
        for program in result.programs:
            ids = [op["id"] for op in program["ops"]]
            if _op_id("9991") in ids:
                self.assertIn(
                    _op_id("9990"), ids,
                    "марка и её цель обязаны быть в ОДНОЙ программе")
                self.assertLess(
                    ids.index(_op_id("9990")), ids.index(_op_id("9991")),
                    "цель обязана стоять РАНЬШЕ ссылающейся на неё марки")
                break
        else:
            self.fail("tag op not found in any chunk")

    def test_ref_target_precedes_referrer_even_with_a_smaller_source_id(self):
        """Вторая половина того же дефекта: членство верное, ПОРЯДОК — нет.

        Компилятор требует, чтобы ref называл БОЛЕЕ РАННИЙ оп. Топосортировка
        шла по одному `host`-родителю, поэтому ребро «марка → дверь» не видела,
        и порядок решала подстановочная сортировка по `source_element_id`.
        Здесь id марки МЕНЬШЕ id её цели — ровно случай, на котором живой замер
        02.08 дал марку на индексе 219 и её дверь на 227 в ОДНОМ чанке: сгруппи-
        рованы правильно и всё равно отказ `KIR-L003`.
        """

        # id стены НАМЕРЕННО больше id марки: тогда в старом обходе марка —
        # готовый корень с меньшим id — выходила ПЕРВОЙ, а дверь освобождалась
        # позже, как потомок стены. При стене с малым id порядок получался
        # верным случайно, и тест ничего не проверял.
        walls = self._many_walls(1, base_id=9000)
        host = walls[0]
        door = _op_leaf(
            "create_door", "8500",
            {
                "host": {"ref": host["_id"]},
                "offset_mm": 1000.0,
                "symbol": {"by": "name", "value": "D", "_id": "700"},
            },
            level_name="L1", anchor=(0.0, 0.0, 0.0))
        tag = _op_leaf(                      # id МЕНЬШЕ, чем у цели
            "create_tag", "8400",
            {
                "target": {"ref": door["_id"]},
                "in_view": {"by": "name", "value": "V", "_id": "701"},
            },
            level_name="L1", anchor=(0.0, 0.0, 0.0))

        result = leaves_to_program(walls + [door, tag], chunk_target=250)
        for program in result.programs:
            ids = [op["id"] for op in program["ops"]]
            if _op_id("8400") in ids:
                self.assertIn(_op_id("8500"), ids)
                self.assertLess(
                    ids.index(_op_id("8500")), ids.index(_op_id("8400")),
                    "цель обязана стоять раньше ссылающейся марки, даже когда "
                    "её source_element_id больше")
                break
        else:
            self.fail("tag op not found in any chunk")

    def test_cyclic_host_graph_is_refused_not_silently_dropped(self):
        left = _op_leaf(
            "create_door", "8101", {"host": {"ref": "pending"}},
            level_name="L1", anchor=(0.0, 0.0, 0.0))
        right = _op_leaf(
            "create_window", "8102", {"host": {"ref": left["_id"]}},
            level_name="L1", anchor=(1000.0, 0.0, 0.0))
        left["params"]["host"] = {"ref": right["_id"]}

        # Замысел прежний: цикл ОТВЕРГАЕТСЯ, а не теряется молча. Сменился слой,
        # который его ловит. Группировка теперь undirected (связные компоненты
        # по всем ref, закон Д5a), и «нет корня» перестало быть признаком цикла:
        # порядок внутри чанка — работа закона Д5d, и цикл ловит именно он,
        # `_toposort_chunk`. Ловить в двух местах значило бы держать два ответа
        # на один вопрос — ровно тот шов, которым этот файл и болел.
        with self.assertRaisesRegex(
                MaterializeError, "cyclic host ref"):
            leaves_to_program([left, right])

    def test_host_group_over_compiler_limit_is_refused_before_emission(self):
        host = self._many_walls(1)[0]
        doors = [
            _op_leaf(
                "create_door", str(10_000 + index),
                {
                    "host": {"ref": host["_id"]},
                    "offset_mm": float(index + 1),
                    "symbol": {"by": "name", "value": "D", "_id": "700"},
                },
                level_name="L1", anchor=(0.0, 0.0, 0.0),
            )
            for index in range(MAX_BULK_OPS)
        ]
        # host + 300 children = 301: pre-fix materialize emitted a program
        # that compile_rebuild_chunk necessarily refused at MAX_BULK_OPS=300.
        with self.assertRaisesRegex(
                MaterializeError, "host-atomic group exceeds compiler"):
            leaves_to_program([host, *doors], chunk_target=250)

    def test_large_chunk_target_is_still_capped_to_compiler_budget(self):
        result = leaves_to_program(
            self._many_walls(MAX_BULK_OPS + 1), chunk_target=10**9)
        self.assertEqual(
            [len(program["ops"]) for program in result.programs],
            [MAX_BULK_OPS, 1],
        )

    def test_rooms_in_tail_after_all_walls(self):
        walls = self._many_walls(300)
        room = _op_leaf(
            "create_room", "7000",
            {
                "xy": [1000.0, 1000.0],
                "level": {"by": "name", "value": "L1", "_id": "500"},
                "name": "R1",
            },
            level_name="L1", anchor=(1000.0, 1000.0, 0.0))
        result = leaves_to_program(walls + [room], chunk_target=250)
        # the room lives in the LAST program, and no wall shares it
        last = result.programs[-1]
        self.assertEqual([op["op"] for op in last["ops"]], ["create_room"])
        # every earlier program is walls only
        for program in result.programs[:-1]:
            self.assertTrue(all(op["op"] == "create_wall" for op in program["ops"]))
        self.assertEqual(result.stats.tail_ops, 1)

    def test_stairs_is_solo_program(self):
        walls = self._many_walls(2)
        stairs = _op_leaf(
            "create_stairs", "8000",
            {
                "p0_mm": [0.0, 0.0],
                "p1_mm": [3000.0, 0.0],
                "base_level": {"by": "name", "value": "L1", "_id": "500"},
                "top_level": {"by": "name", "value": "L2", "_id": "501"},
            },
            level_name="L1", anchor=(1500.0, 0.0, 0.0))
        result = leaves_to_program(walls + [stairs], chunk_target=250)
        solo = [p for p in result.programs
                if len(p["ops"]) == 1 and p["ops"][0]["op"] == "create_stairs"]
        self.assertEqual(len(solo), 1)
        self.assertEqual(result.stats.solo_programs, 1)
        # a solo stairs program compiles (KIR-L002 would trip if mixed)
        out = compile_program(solo[0], "2026", snapshot=None, bulk=True)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])


# ---------------------------------------------------------------------------
# Datum policy (Д3)
# ---------------------------------------------------------------------------


class DatumPolicy(unittest.TestCase):
    def _leaves(self):
        level = _op_leaf(
            "create_level", "3000",
            {"elev_mm": 3000.0, "name": "L2"}, level_name="L2")
        grid = _op_leaf(
            "create_grid", "3001",
            {"p0_mm": [0.0, 0.0], "p1_mm": [10000.0, 0.0], "name": "A"},
            anchor=(5000.0, 0.0, 0.0))
        wall = _op_leaf(
            "create_wall", "3002",
            {
                "p0_mm": [0.0, 0.0],
                "p1_mm": [5000.0, 0.0],
                "level": {"by": "name", "value": "L1", "_id": "500"},
                "height_mm": 2800.0,
                "type": {"by": "name", "value": "W200", "_id": "600"},
            },
            level_name="L1", anchor=(2500.0, 0.0, 0.0))
        return [level, grid, wall]

    def test_datums_skipped_by_default(self):
        result = leaves_to_program(self._leaves())
        materialized_ops = [op["op"] for p in result.programs for op in p["ops"]]
        self.assertNotIn("create_level", materialized_ops)
        self.assertNotIn("create_grid", materialized_ops)
        self.assertEqual(result.stats.datums_skipped, 2)
        reasons = {s.reason for s in result.skipped}
        self.assertIn("datum_pinned_existing", reasons)
        pins = [
            row for row in result.accounting.records
            if row.disposition == "datum_policy_pin"]
        self.assertEqual(len(pins), 2)
        self.assertTrue(all(
            row.evidence_state == "same_document_unproven"
            and row.element_id == int(row.source_id)
            for row in pins))

    def test_datums_materialized_when_included(self):
        result = leaves_to_program(self._leaves(), include_datums=True)
        materialized_ops = {op["op"] for p in result.programs for op in p["ops"]}
        self.assertIn("create_level", materialized_ops)
        self.assertIn("create_grid", materialized_ops)
        self.assertEqual(result.stats.datums_skipped, 0)

    @staticmethod
    def _dimension_between(kind):
        if kind == "grid":
            first = _op_leaf(
                "create_grid", "3100",
                {"p0_mm": [0.0, 0.0], "p1_mm": [0.0, 10000.0],
                 "name": "A"})
            second = _op_leaf(
                "create_grid", "3101",
                {"p0_mm": [5000.0, 0.0],
                 "p1_mm": [5000.0, 10000.0], "name": "B"})
        else:
            first = _op_leaf(
                "create_level", "3200",
                {"elev_mm": 0.0, "name": "L0"})
            second = _op_leaf(
                "create_level", "3201",
                {"elev_mm": 3000.0, "name": "L1"})
        dimension = _op_leaf(
            "create_dimension", "3300",
            {
                "in_view": {
                    "by": "name", "value": "Plan", "_id": "9000"},
                "refs": [
                    {"ref": first["_id"]},
                    {"ref": second["_id"]},
                ],
                "line_at": [1000.0, 1000.0],
            })
        return first, second, dimension

    def test_dimension_refs_pin_existing_datums_in_same_document(self):
        """A policy-skipped datum remains an explicit existing dependency;
        its consumer must not become an orphan and disappear."""
        for kind, ids in (("grid", [3100, 3101]),
                          ("level", [3200, 3201])):
            with self.subTest(kind=kind):
                result = leaves_to_program(self._dimension_between(kind))
                ops = [op for program in result.programs
                       for op in program["ops"]]
                self.assertEqual([op["op"] for op in ops],
                                 ["create_dimension"])
                self.assertEqual(
                    ops[0]["refs"],
                    [{"by": "element_id", "value": value}
                     for value in ids])
                self.assertEqual(result.stats.op_leaves, 3)
                self.assertEqual(result.stats.materialized_ops, 1)
                self.assertEqual(result.stats.datums_skipped, 2)
                self.assertEqual(result.stats.semantic_ops_skipped, 0)
                self.assertEqual(
                    {record.reason for record in result.skipped},
                    {"datum_pinned_existing"})
                self.assertTrue(all(check.accepted
                                    for check in result.plan_checks))

    def test_dimension_refs_follow_materialized_datums_when_included(self):
        """Fresh-document policy keeps the same L1 edges intra-program, so
        topo order and the compiler DAG prove datum creation before dimension."""
        for kind, source_ids in (("grid", ["3100", "3101"]),
                                 ("level", ["3200", "3201"])):
            with self.subTest(kind=kind):
                result = leaves_to_program(
                    self._dimension_between(kind), include_datums=True)
                ops = [op for program in result.programs
                       for op in program["ops"]]
                self.assertEqual(
                    [op["op"] for op in ops],
                    ["create_" + kind, "create_" + kind,
                     "create_dimension"])
                self.assertEqual(
                    ops[-1]["refs"],
                    [{"by": "ref", "value": _op_id(source_id)}
                     for source_id in source_ids])
                self.assertEqual(result.stats.materialized_ops, 3)
                self.assertEqual(result.stats.datums_skipped, 0)
                self.assertEqual(result.stats.semantic_ops_skipped, 0)
                self.assertEqual(result.skipped, [])
                self.assertTrue(all(check.accepted
                                    for check in result.plan_checks))


# ---------------------------------------------------------------------------
# Bulk flag on the compiler
# ---------------------------------------------------------------------------


class BulkFlag(unittest.TestCase):
    def _wall_ops(self, n):
        return [
            {
                "op": "create_wall", "id": f"e{i}",
                "p0_mm": [float(i) * 6000.0, 0.0],
                "p1_mm": [float(i) * 6000.0 + 5000.0, 0.0],
                "level": {"by": "element_id", "value": 500},
                "height_mm": 2800.0,
                "type": {"by": "element_id", "value": 600},
            }
            for i in range(n)
        ]

    def test_one_over_the_authored_budget_is_refused_without_bulk(self):
        """ПОТОЛОК БЕРЁТСЯ У АВТОРИТЕТА, А НЕ ПИШЕТСЯ ЧИСЛОМ.

        Прежняя редакция звалась `test_twentyone_ops_without_bulk_refused` и
        подавала 21 оп, потому что бюджет был 20. Владелец поднял его до 100
        (15.08), и тест позеленел молча в другую сторону: 21 оп больше не
        отказывает, а проверка «потолок работает» перестала что-либо проверять,
        оставшись зелёной. Числовой пин потолка — тот же именной дефект дерева:
        величина объявлена в `compiler`, прочитана здесь, и ничто не заставляло
        их совпасть.

        Теперь граница выводится из `MAX_OPS_PER_PROGRAM`, и тест переживёт
        следующий подъём бюджета, каким бы он ни был.
        """
        over = MAX_OPS_PER_PROGRAM + 1
        program = {"ir_version": "1.0", "ops": self._wall_ops(over)}
        with self.assertRaises(KirRefusal) as ctx:
            _parse_and_check(program)          # bulk defaults to False
        codes = {d.code for d in ctx.exception.diagnostics}
        self.assertIn("KIR-L001", codes)

    def test_exactly_the_authored_budget_is_accepted(self):
        """КОНТРОЛЬ С ДРУГОЙ СТОРОНЫ ГРАНИЦЫ.

        Без него отказ выше доказывает лишь, что что-то отказало, — а «отказ
        всегда» выглядит точно так же. Пара «ровно потолок проходит, потолок+1
        отказывает» и есть акт различения."""
        program = {"ir_version": "1.0",
                   "ops": self._wall_ops(MAX_OPS_PER_PROGRAM)}
        normed = _parse_and_check(program)
        self.assertEqual(len(normed), MAX_OPS_PER_PROGRAM)

    def test_threehundred_ops_with_bulk_ok(self):
        program = {"ir_version": "1.0", "ops": self._wall_ops(300)}
        normed = _parse_and_check(program, bulk=True)
        self.assertEqual(len(normed), 300)
        self.assertEqual(MAX_BULK_OPS, 300)
        # full compile path also honours bulk
        out = compile_program(program, "2026", snapshot=None, bulk=True)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

    def test_threehundredone_ops_refused_even_with_bulk(self):
        program = {"ir_version": "1.0", "ops": self._wall_ops(301)}
        with self.assertRaises(KirRefusal) as ctx:
            _parse_and_check(program, bulk=True)
        codes = {d.code for d in ctx.exception.diagnostics}
        self.assertIn("KIR-L001", codes)

    def test_bulk_flag_not_in_llm_schema(self):
        # `bulk` is internal-only: it must not appear as an envelope field the
        # user-facing parser accepts.
        #
        # ЗДЕСЬ БОЛЬШЕ НЕТ `assertEqual(MAX_OPS_PER_PROGRAM, 20)`, и это не
        # ослабление. Предмет этого теста — ФОРМА КОНВЕРТА: нельзя попросить
        # bulk полем программы. Величина бюджета — предмет соседних тестов, и
        # приписанная сюда, она делала ровно одно: роняла проверку конверта
        # при каждой смене бюджета, то есть красила чужой предмет.
        self.assertGreater(MAX_OPS_PER_PROGRAM, 0)
        program = {"ir_version": "1.0", "bulk": True, "ops": self._wall_ops(1)}
        with self.assertRaises(KirRefusal) as ctx:
            _parse_and_check(program)
        # a "bulk" field inside the program envelope is an unknown-field refusal:
        # the flag is a Python kwarg only, never part of the JSON schema.
        bulk_diag = [d for d in ctx.exception.diagnostics
                     if d.field_name == "bulk"]
        self.assertTrue(bulk_diag)
        self.assertEqual(bulk_diag[0].code, "KIR-P003")

    def test_program_id_is_internal_bulk_metadata_only(self):
        base = {"ir_version": "1.0", "ops": self._wall_ops(1)}
        planned = {**base, "program_id": "a" * 64}

        # The LLM/user surface remains closed.
        with self.assertRaises(KirRefusal) as ctx:
            _parse_and_check(planned)
        self.assertTrue(any(
            diagnostic.field_name == "program_id"
            and diagnostic.code == "KIR-P003"
            for diagnostic in ctx.exception.diagnostics))

        # The trusted rebuild path accepts the receipt identity but produces
        # the exact same normalized ops; program_id has no emission semantics.
        self.assertEqual(
            _parse_and_check(planned, bulk=True),
            _parse_and_check(base, bulk=True),
        )

    def test_bulk_program_id_requires_sha256_shape(self):
        program = {
            "ir_version": "1.0",
            "program_id": "friendly-name",
            "ops": self._wall_ops(1),
        }
        with self.assertRaises(KirRefusal) as ctx:
            _parse_and_check(program, bulk=True)
        self.assertTrue(any(
            diagnostic.field_name == "program_id"
            and diagnostic.code == "KIR-T001"
            for diagnostic in ctx.exception.diagnostics))


# ---------------------------------------------------------------------------
# Determinism (I4)
# ---------------------------------------------------------------------------


class Determinism(unittest.TestCase):
    def test_identical_leaves_byte_identical_programs(self):
        leaves = _hosted_chain(origin=(1000.0, 2000.0, 0.0))
        a = leaves_to_program(leaves, chunk_target=250)
        b = leaves_to_program(list(reversed(leaves)), chunk_target=250)
        self.assertEqual(a.programs, b.programs)      # order-independent (I4)
        self.assertEqual(a.stats.as_dict(), b.stats.as_dict())

    def test_mode_and_chunk_target_validated(self):
        with self.assertRaises(MaterializeError):
            leaves_to_program([], mode="fresh_document")
        with self.assertRaises(MaterializeError):
            leaves_to_program([], chunk_target=0)


# ---------------------------------------------------------------------------
# Tier-G atom escrow (A4; geometry-only, never a semantic fidelity claim)
# ---------------------------------------------------------------------------


class AtomEscrow(unittest.TestCase):
    @staticmethod
    def _geometry(
        source_id: str = "9001",
        category: str = "OST_Walls",
        *,
        mesh=None,
        transform=IDENTITY_TRANSFORM,
    ):
        return extract_geometry(_geometry_payload([
            _geometry_element(
                source_id,
                category,
                [_geometry_part(mesh or _triangle_mesh(), transform)],
            ),
        ]))

    def test_escrow_is_explicit_and_requires_typed_geometry(self):
        atom = _atom_leaf("9001", "OST_Walls")
        geometry = self._geometry()

        with self.assertRaisesRegex(MaterializeError, "requires"):
            leaves_to_program([atom], mode="escrow")
        with self.assertRaisesRegex(MaterializeError, "explicit mode"):
            leaves_to_program([atom], geometry=geometry)
        with self.assertRaisesRegex(MaterializeError, "explicit mode"):
            leaves_to_program([atom], escrow_source_ids=["9001"])

    def test_exact_escrow_scope_keeps_unselected_atom_as_typed_skip(self):
        selected = _atom_leaf("9001", "OST_Walls")
        held = _atom_leaf("9002", "OST_Furniture")
        geometry = extract_geometry(_geometry_payload([
            _geometry_element(
                "9001", "OST_Walls", [_geometry_part(_triangle_mesh())]),
            _geometry_element(
                "9002", "OST_Furniture", [_geometry_part(_triangle_mesh())]),
        ]))

        result = leaves_to_program(
            [held, selected],
            mode="escrow",
            geometry=geometry,
            escrow_source_ids=["9001"],
        )

        self.assertEqual([row.source_id for row in result.escrowed], ["9001"])
        self.assertEqual(result.stats.atoms_escrowed, 1)
        self.assertEqual(result.stats.atoms_skipped, 1)
        self.assertEqual(
            [(row.source_id, row.reason) for row in result.skipped],
            [("9002", "atom_escrow:not_selected")],
        )

    def test_escrow_scope_refuses_unknown_or_duplicate_identities(self):
        atom = _atom_leaf("9001", "OST_Walls")
        geometry = self._geometry()

        with self.assertRaisesRegex(MaterializeError, "not atom leaves"):
            leaves_to_program(
                [atom], mode="escrow", geometry=geometry,
                escrow_source_ids=["missing"])
        with self.assertRaisesRegex(MaterializeError, "duplicates"):
            leaves_to_program(
                [atom], mode="escrow", geometry=geometry,
                escrow_source_ids=["9001", "9001"])

    def test_wall_atom_becomes_neutral_directshape_candidate(self):
        atom = _atom_leaf("9001", "OST_Walls")

        result = leaves_to_program(
            [atom], mode="escrow", geometry=self._geometry())

        self.assertTrue(result.compiler_ready)
        self.assertEqual(len(result.programs), 1)
        op = result.programs[0]["ops"][0]
        self.assertEqual(op["op"], "create_directshape")
        self.assertEqual(op["id"], "e9001")
        self.assertEqual(op["category"], "generic_model")
        self.assertIn("OST_Walls", op["name"])
        self.assertEqual(result.skipped, [])
        self.assertEqual(result.stats.atoms_escrowed, 1)
        self.assertEqual(result.stats.atoms_skipped, 0)
        self.assertEqual(result.stats.materialized_ops, 1)
        self.assertEqual(len(result.escrowed), 1)
        evidence = result.escrowed[0]
        self.assertEqual(evidence.source_id, "9001")
        self.assertEqual(evidence.directshape_category, "generic_model")
        self.assertEqual(
            evidence.acceptance_state, "pending_runtime_witness")
        accounting_row = result.accounting.records[0]
        self.assertEqual(accounting_row.disposition, "atom_escrow")
        self.assertEqual(
            accounting_row.evidence_state, "pending_runtime_witness")
        self.assertEqual(evidence.program_index, 0)
        self.assertEqual(evidence.plan_digest, result.plans[0].plan_digest)
        self.assertEqual(len(evidence.form_digest), 64)
        self.assertEqual(len(evidence.expectation.expectation_digest), 64)
        self.assertEqual(len(evidence.geometry_hash), 64)
        self.assertEqual(len(evidence.materialized_geometry_hash), 64)

    def test_escrow_typed_plan_refusal_cannot_leave_pending_evidence(self):
        refusal = KirRefusal([Diagnostic(
            code="KIR-T001",
            message_ru="synthetic planning refusal",
        )])
        with mock.patch(
                "kukai.ir.decompile.materialize.plan_program",
                side_effect=refusal):
            with self.assertRaisesRegex(
                    MaterializeError, "escrow program was refused"):
                leaves_to_program(
                    [_atom_leaf("9001", "OST_Walls")],
                    mode="escrow",
                    geometry=self._geometry(),
                )

    def test_escrow_expectation_cannot_be_rebound_to_a_different_mesh(self):
        result = leaves_to_program(
            [_atom_leaf("9001", "OST_Walls")],
            mode="escrow",
            geometry=self._geometry(),
        )
        record = result.escrowed[0]
        forged = replace(
            record,
            expectation=replace(
                record.expectation,
                surface_digest="c" * 64,
            ),
        )
        with self.assertRaisesRegex(ValueError, "exact mesh"):
            MaterializeResult(
                programs=result.programs,
                skipped=result.skipped,
                escrowed=[forged],
                stats=result.stats,
                accounting=result.accounting,
                plans=result.plans,
                plan_checks=result.plan_checks,
            )

    def test_already_neutral_category_is_preserved(self):
        atom = _atom_leaf("9002", "OST_Furniture")
        geometry = self._geometry("9002", "OST_Furniture")

        result = leaves_to_program(
            [atom], mode="escrow", geometry=geometry)

        self.assertEqual(
            result.programs[0]["ops"][0]["category"], "furniture")
        self.assertEqual(
            result.escrowed[0].directshape_category, "furniture")

    def test_geometry_category_must_match_source_identity(self):
        atom = _atom_leaf("9008", "OST_Furniture")
        mismatched = self._geometry("9008", "OST_Mass")

        result = leaves_to_program(
            [atom], mode="escrow", geometry=mismatched)

        self.assertEqual(result.programs, [])
        self.assertEqual(
            result.skipped[0].reason,
            "atom_escrow:category_identity_mismatch",
        )

    def test_world_transform_and_rebuild_offset_both_move_mesh_vertices(self):
        atom = _atom_leaf("9003", "OST_Furniture")
        geometry = self._geometry(
            "9003", "OST_Furniture",
            transform=_translated(2500.0, -400.0, 75.0),
        )

        result = leaves_to_program(
            [atom], mode="escrow", geometry=geometry,
            offset_mm=(100.0, 200.0, -25.0),
        )

        vertices = result.programs[0]["ops"][0]["mesh"]["vertices_mm"]
        self.assertEqual(vertices[0], [2600.0, -200.0, 50.0])
        self.assertEqual(vertices[1], [3600.0, -200.0, 50.0])
        self.assertNotEqual(
            result.escrowed[0].geometry_hash,
            result.escrowed[0].materialized_geometry_hash,
        )

    def test_generator_child_is_never_duplicated_as_escrow(self):
        atom = _atom_leaf("9004", "OST_CurtainWallPanels")
        atom["reason"] = {
            "code": "generator_child",
            "detail": "parent regenerates this child",
        }
        geometry = self._geometry("9004", "OST_CurtainWallPanels")

        result = leaves_to_program(
            [atom], mode="escrow", geometry=geometry)

        self.assertEqual(result.programs, [])
        self.assertEqual(result.escrowed, [])
        self.assertEqual(result.stats.atoms_escrowed, 0)
        self.assertEqual(result.stats.atoms_skipped, 1)
        self.assertEqual(result.skipped[0].reason, "atom:generator_child")

    def test_tier_a_and_missing_geometry_are_typed_skips(self):
        tier_a = _atom_leaf("9005", "OST_Furniture")
        missing = _atom_leaf("9006", "OST_Furniture")
        geometry = extract_geometry(_geometry_payload([
            _geometry_element(
                "9005", "OST_Furniture", [], status="empty"),
        ]))

        result = leaves_to_program(
            [tier_a, missing], mode="escrow", geometry=geometry)

        self.assertEqual(result.programs, [])
        self.assertEqual(result.stats.atoms_skipped, 2)
        self.assertEqual(
            {record.source_id: record.reason for record in result.skipped},
            {
                "9005": "atom_escrow:tier_a_no_geometry",
                "9006": "atom_escrow:missing_geometry_evidence",
            },
        )

    def test_mesh_outside_forward_contract_is_skipped_not_silently_fixed(
            self):
        atom = _atom_leaf("9007", "OST_Furniture")
        # Gm accepts this non-degenerate triangle; the forward DirectShape
        # contract intentionally rejects its sub-millimetre short edge.
        tiny_edge = GmMesh(
            ((0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 10.0, 0.0)),
            ((0, 1, 2),),
        )
        geometry = self._geometry(
            "9007", "OST_Furniture", mesh=tiny_edge)

        result = leaves_to_program(
            [atom], mode="escrow", geometry=geometry)

        self.assertEqual(result.programs, [])
        self.assertEqual(result.stats.atoms_escrowed, 0)
        self.assertEqual(result.stats.atoms_skipped, 1)
        self.assertEqual(
            result.skipped[0].reason, "atom_escrow:mesh_refused")

    def test_escrow_order_and_evidence_are_input_order_independent(self):
        first = _atom_leaf("9010", "OST_Furniture")
        second = _atom_leaf("9009", "OST_Walls")
        geometry = extract_geometry(_geometry_payload([
            _geometry_element(
                "9010", "OST_Furniture", [_geometry_part(_triangle_mesh())]),
            _geometry_element(
                "9009", "OST_Walls", [_geometry_part(
                    _triangle_mesh(), _translated(2000.0, 0.0, 0.0))]),
        ]))

        a = leaves_to_program(
            [first, second], mode="escrow", geometry=geometry)
        b = leaves_to_program(
            [second, first], mode="escrow", geometry=geometry)

        self.assertEqual(a.programs, b.programs)
        self.assertEqual(a.escrowed, b.escrowed)
        self.assertEqual(
            [record.source_id for record in a.escrowed], ["9009", "9010"])


# ---------------------------------------------------------------------------
# Group bridge (KUKAI_IR_NATIVE_GROUP)
# ---------------------------------------------------------------------------


class GroupBridge(unittest.TestCase):
    def _place_op(self):
        """A synthetic wall-only PlaceGroupOp (2 members, 3 occurrences).

        A definition made purely of op-leaves is the case the bridge can group;
        a definition containing atoms is (correctly) refused, so we build a
        clean wall-pair component directly rather than depend on which fixture
        happens to yield an atom-free repeat.
        """

        from kukai.ir.decompile.component import (
            ComponentDefinition,
            ComponentFidelityProof,
            ComponentInstance,
            PlaceGroupOp,
        )
        from kukai.ir.decompile.fold import FidelityCanon

        def wall(source_id, x0, x1):
            return _op_leaf(
                "create_wall", source_id,
                {
                    "p0_mm": [x0, 0.0],
                    "p1_mm": [x1, 0.0],
                    "level": {"by": "name", "value": "L1", "_id": "500"},
                    "height_mm": 2800.0,
                    "type": {"by": "name", "value": "W200", "_id": "600"},
                },
                level_name="L1", anchor=((x0 + x1) / 2.0, 0.0, 0.0))

        definition = ComponentDefinition(
            def_hash="a" * 40, kind="group", origin_mm=(0.0, 0.0, 0.0),
            leaves=(wall("m1", 0.0, 3000.0), wall("m2", 0.0, 4000.0)),
            leaf_count=2, label="unit")
        origins = [(0.0, 0.0, 0.0), (10000.0, 0.0, 0.0), (20000.0, 0.0, 0.0)]
        instances = tuple(
            ComponentInstance(
                def_hash=definition.def_hash, instance_index=idx,
                offset_mm=origin, origin_mm=origin, rel_mm=origin)
            for idx, origin in enumerate(origins))
        hashes = tuple(f"{idx + 1:040x}" for idx in range(len(instances)))
        return PlaceGroupOp(
            def_hash=definition.def_hash, definition=definition,
            instances=instances,
            fidelity_proof=ComponentFidelityProof(
                canon_version=FidelityCanon.VERSION,
                instantiated_hashes=hashes,
                source_hashes=hashes,
            ))

    def test_disabled_by_default_returns_none(self):
        os.environ.pop("KUKAI_IR_NATIVE_GROUP", None)
        self.assertIsNone(component_to_group_program(self._place_op()))

    def test_the_bridge_asks_the_round_trip_before_building_the_ir(self):
        """C-RT НА МОСТУ ПОЗВАНА (13.08.2026) — КОНТРОЛЬ-FAIL.

        `assert_group_matches_place_op` была написана целиком: сверяет
        мультимножество абсолютных опов развёртки группы с поштучной В ОБЕ
        СТОРОНЫ и отдельно требует доказанной исходной точности. Её не звал
        НИКТО, кроме тестов, — мост собирал IR `create_group`, ни разу не
        спросив, совпадает ли развёртка. То же, что с самим мостом, этажом
        ниже: написано, объявлено в `__all__`, не позвано.

        Портим ровно то, что портил LOT31: дельты в относительной форме
        (`occ_origin_k − def_origin` вместо `− occ_origin_0`). До правки такой
        оп собрался бы в IR и уехал к эмиттеру.
        """
        from kukai.ir.decompile import materialize as _m
        from kukai.ir.decompile import native_group as _ng

        place_op = self._place_op()
        os.environ["KUKAI_IR_NATIVE_GROUP"] = "1"
        _m.reset_group_refusals()
        try:
            good = _ng.group_op_from_place_op(place_op)
            self.assertIsNotNone(good)
            # ПОРЧА НЕ ЗАВИСИТ ОТ ФИКСТУРЫ. Первая редакция сдвигала дельты
            # на начало определения — форму бага LOT31, — и на синтетической
            # паре стен это начало НУЛЕВОЕ: порча становилась тождественной, а
            # контроль СКИПАЛСЯ. Скип честен и бесполезен: сторож, который не
            # выполнился, ничего не сторожит. Сдвиг на метр расходится всегда.
            self.assertTrue(good.placement_deltas_mm,
                            "размещений нет — расхождение невыразимо")
            shifted = list(good.placement_deltas_mm)
            shifted[0] = (shifted[0][0] + 1000.0, shifted[0][1], shifted[0][2])
            bad = _ng.NativeGroupOp(
                def_hash=good.def_hash, definition=good.definition,
                base_origin_mm=good.base_origin_mm,
                placement_deltas_mm=tuple(shifted),
                label=good.label)
            with mock.patch.object(_ng, "group_op_from_place_op",
                                   return_value=bad):
                program = component_to_group_program(place_op)
            self.assertIsNone(program, "расходящаяся группа собралась в IR")
            self.assertEqual(
                [r["reason"] for r in _m.last_group_refusals()],
                ["expansion_mismatch"])
        finally:
            os.environ.pop("KUKAI_IR_NATIVE_GROUP", None)
            _m.reset_group_refusals()

    def test_a_refusal_carries_its_reason_instead_of_a_bare_none(self):
        """ОТКАЗЫ ПЕРЕСТАЛИ МОЛЧАТЬ.

        Каждый был `return None`: вызывающий уходил на N поштучных элементов и
        не знал, почему группы не случилось. «Группы нет» и «группа отказана по
        названной причине» обязаны быть разными фактами — тот же класс, что
        молчаливая отсечка списка и гашение инверсии покрытия.

        Поведение НЕ меняется и меняться не должно: откат на поштучный путь —
        правильный ответ, геометрия не теряется. Меняется то, что теперь можно
        спросить ПОЧЕМУ.
        """
        from kukai.ir.decompile import materialize as _m

        os.environ["KUKAI_IR_NATIVE_GROUP"] = "1"
        _m.reset_group_refusals()
        try:
            # Патчим ЗАЗЕМЛЕНИЕ: оно вызывается внутри `try`, и его отказ —
            # ровно тот путь, который до 13.08 возвращал голый None.
            from kukai.ir import ground as _ground
            with mock.patch.object(
                    _ground, "ground",
                    side_effect=RuntimeError("подложный отказ заземления")):
                self.assertIsNone(component_to_group_program(self._place_op()))
        finally:
            os.environ.pop("KUKAI_IR_NATIVE_GROUP", None)
        refusals = _m.last_group_refusals()
        _m.reset_group_refusals()
        self.assertEqual([r["reason"] for r in refusals],
                         ["grounding_refused"], refusals)

    def test_enabled_produces_compilable_group_program(self):
        place_op = self._place_op()
        os.environ["KUKAI_IR_NATIVE_GROUP"] = "1"
        try:
            program = component_to_group_program(place_op)
        finally:
            os.environ.pop("KUKAI_IR_NATIVE_GROUP", None)
        self.assertIsNotNone(program)
        self.assertEqual(program["ops"][0]["op"], "create_group")
        group = program["ops"][0]
        # placements = one per ADDITIONAL occurrence (occurrence 0 is the members)
        self.assertEqual(len(group["placements"]),
                         place_op.occurrence_count - 1)
        # members are PRE-GROUNDED (element_id selectors -> __grounded__ dicts)
        for member in group["members"]:
            self.assertIn("__grounded__", member["level"])
        # the whole create_group program compiles
        out = compile_program(program, "2026", snapshot=None, bulk=True)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])


if __name__ == "__main__":
    unittest.main()
