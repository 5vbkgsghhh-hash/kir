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

from kir import ground as ground_mod  # noqa: E402
from kir import spec  # noqa: E402
from kir.compiler import (  # noqa: E402
    MAX_BULK_OPS,
    MAX_OPS_PER_PROGRAM,
    _parse_and_check,
    compile_program,
    plan_program,
)
from kir.diag import Diagnostic, KirRefusal  # noqa: E402
from kir.decompile.fold import iter_l1_leaves  # noqa: E402
from kir.decompile.geom_extract import extract_geometry  # noqa: E402
from kir.decompile.l1_schema import stable_l1_id, validate_l1_nodes  # noqa: E402
from kir.decompile.materialize import (  # noqa: E402
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
from kir.decompile.recompile import IDENTITY_TRANSFORM, GmMesh  # noqa: E402
from kir.decompile.tests.test_geom_extract import (  # noqa: E402
    _element as _geometry_element,
    _part as _geometry_part,
    _payload as _geometry_payload,
    _triangle_mesh,
    _translated,
)

_LOT31_TREE = Path("/home/claude/lot31_full/_tree_cache.pkl")
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
                "kir.decompile.materialize.plan_program",
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


class TMatReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            source = _LOT31_TREE.read_bytes()
        except (FileNotFoundError, PermissionError) as error:
            raise unittest.SkipTest(
                f"optional lot31 corpus unavailable ({type(error).__name__}): {_LOT31_TREE}") from error
        cls.leaves = list(iter_l1_leaves(
            pickle.loads(source)))

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
        """The tower's verbatim failure of 02.08: a tag on a door was
        landing in a different chunk.

        `create_tag.target` is a reference, but NOT a host, so the old
        `host`-based grouping treated the tag as its own root and packed
        it apart from the door. `_translate_reference` resolves refs
        against the whole run's map, so the program received a
        reference to an op that was not in it, and the compiler
        rightfully refused with `KIR-L003`. On `k2_ar_rd_v8` this cost
        39 chunks out of 133; Snowdon does not show the defect — it fits
        in a single chunk.
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
        """The second half of the same defect: membership is correct,
        ORDER is not.

        The compiler requires that a ref name an EARLIER op. Topological
        sorting went by a single `host` parent, so it did not see the
        "tag → door" edge, and order was decided by a fallback sort on
        `source_element_id`. Here the tag's id is SMALLER than its
        target's — exactly the case where the live measurement of 02.08
        put the tag at index 219 and its door at 227 in ONE chunk:
        grouped correctly, and still a `KIR-L003` refusal.
        """

        # the wall's id is DELIBERATELY larger than the tag's: in the old
        # traversal the tag — a ready-made root with the smaller id —
        # would come out FIRST, and the door would be freed later, as a
        # descendant of the wall. With a small-id wall the order came out
        # right by accident, and the test checked nothing.
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
        tag = _op_leaf(                      # id SMALLER than its target's
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

        # The intent is unchanged: a cycle is REJECTED, not silently
        # lost. What changed is the layer that catches it. Grouping is
        # now undirected (connected components over all refs, law D5a),
        # and "no root" stopped being a sign of a cycle: order within a
        # chunk is the job of law D5d, and it is exactly that,
        # `_toposort_chunk`, that catches the cycle. Catching it in two
        # places would mean holding two answers to one question —
        # exactly the seam this file was suffering from.
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
        # host + MAX_BULK_OPS children = the budget plus one: pre-fix
        # materialize emitted a program compile_rebuild_chunk necessarily
        # refused. The count is ASKED, never spelled: it read 300 until
        # 18.08.2026 and reads 10000 now.
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
        """🔴 A GRID LAYOUT, NOT A ROW — otherwise the ruler breaks
        before the subject does.

        The old fixture lined up walls in a single row with a 6 m step.
        At a budget of 300 that is 1.8 km and bothered nobody; after the
        raise to 10 000 (18.08) the row runs past 60 KM, and the test
        fails on `KIR-T001` (a point outside the model's bounds), i.e.
        on its OWN layout, not on the budget it is checking.

        A grid of 100 per row gives 600x600 m for any n up to 10 000 —
        the subject stays the budget."""
        per_row = 100
        return [
            {
                "op": "create_wall", "id": f"e{i}",
                "p0_mm": [float(i % per_row) * 6000.0,
                          float(i // per_row) * 6000.0],
                "p1_mm": [float(i % per_row) * 6000.0 + 5000.0,
                          float(i // per_row) * 6000.0],
                "level": {"by": "element_id", "value": 500},
                "height_mm": 2800.0,
                "type": {"by": "element_id", "value": 600},
            }
            for i in range(n)
        ]

    def test_one_over_the_authored_budget_is_refused_without_bulk(self):
        """THE CEILING IS TAKEN FROM THE AUTHORITY, NOT WRITTEN AS A
        NUMBER.

        The previous version was called
        `test_twentyone_ops_without_bulk_refused` and submitted 21 ops
        because the budget was 20. The owner raised it to 100 (15.08),
        and the test silently turned green in the other direction: 21
        ops no longer refuses, and the "the ceiling works" check stopped
        checking anything while staying green. A numeric pin on the
        ceiling is the same named defect of this tree: the value is
        declared in `compiler`, read here, and nothing forced them to
        match.

        Now the boundary is derived from `MAX_OPS_PER_PROGRAM`, and the
        test will survive the next budget raise, whatever it turns out
        to be.
        """
        over = MAX_OPS_PER_PROGRAM + 1
        program = {"ir_version": "1.0", "ops": self._wall_ops(over)}
        with self.assertRaises(KirRefusal) as ctx:
            _parse_and_check(program)          # bulk defaults to False
        codes = {d.code for d in ctx.exception.diagnostics}
        self.assertIn("KIR-L001", codes)

    def test_exactly_the_authored_budget_is_accepted(self):
        """A CONTROL FROM THE OTHER SIDE OF THE BOUNDARY.

        Without it, the refusal above proves only that something
        refused — and "it always refuses" looks exactly the same. The
        pair "exactly the ceiling passes, the ceiling+1 refuses" is the
        act of distinction."""
        program = {"ir_version": "1.0",
                   "ops": self._wall_ops(MAX_OPS_PER_PROGRAM)}
        normed = _parse_and_check(program)
        self.assertEqual(len(normed), MAX_OPS_PER_PROGRAM)

    def test_exactly_the_internal_budget_with_bulk_ok(self):
        """🔴 THE NAME AND THE NUMBER ARE DERIVED FROM THE AUTHORITY —
        THE SAME LESSON AS ABOVE.

        It used to be called `test_threehundred_ops_with_bulk_ok` and
        submitted 300 because the budget was 300. The owner raised it on
        18.08 (internal -> 10 000), and the test turned red NOT on a
        defect but on its own ruler. A neighboring test of the same
        class already bought this exact lesson on 15.08 and was
        rewritten against the constant — but these two were left as they
        were, and they repeated it verbatim.

        The shape: one half of the file learned the lesson, the other
        did not; curing half does not protect the whole."""
        n = MAX_BULK_OPS
        program = {"ir_version": "1.0", "ops": self._wall_ops(n)}
        normed = _parse_and_check(program, bulk=True)
        self.assertEqual(len(normed), n)
        self.assertGreater(MAX_BULK_OPS, MAX_OPS_PER_PROGRAM,
                           "запас внутренней двери над авторской — несущий "
                           "инвариант, а не разница чисел")
        # full compile path also honours bulk
        out = compile_program(program, "2026", snapshot=None, bulk=True)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

    def test_one_over_the_internal_budget_refused_even_with_bulk(self):
        """A ruler taken from the constant: the literal 301 stopped
        exceeding the budget on 18.08."""
        program = {"ir_version": "1.0", "ops": self._wall_ops(MAX_BULK_OPS + 1)}
        with self.assertRaises(KirRefusal) as ctx:
            _parse_and_check(program, bulk=True)
        codes = {d.code for d in ctx.exception.diagnostics}
        self.assertIn("KIR-L001", codes)

    def test_bulk_flag_not_in_llm_schema(self):
        # `bulk` is internal-only: it must not appear as an envelope field the
        # user-facing parser accepts.
        #
        # THERE IS NO LONGER `assertEqual(MAX_OPS_PER_PROGRAM, 20)` HERE,
        # and this is not a weakening. This test's subject is THE
        # ENVELOPE'S SHAPE: bulk cannot be requested as a program field.
        # The size of the budget is the subject of neighboring tests, and
        # attached here it did exactly one thing: it broke the envelope
        # check on every change of the budget, i.e. it painted a subject
        # that was not its own.
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
        """🔴 23.08.2026: `fresh_document` WAS REMOVED FROM HERE BECAUSE
        IT HAS BEEN BUILT.

        `leaves_to_program([], mode="fresh_document")` used to stand
        here in the list of refusals — as the THIRD carrier of the same
        fact (the other two: `test_reverse_to_l1_contract` and the
        module's docstring). The mode is built, and a record of its
        refusal would instantly become a lie in a third place.

        The guard is not weakened by this: it is about the GRAMMAR of
        the input, and an unknown mode must still refuse. The dialect of
        names is checked by its own file —
        `test_fresh_document_dialect.py`.
        """
        with self.assertRaises(MaterializeError):
            leaves_to_program([], mode="b4_future")
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
                "kir.decompile.materialize.plan_program",
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

        from kir.decompile.component import (
            ComponentDefinition,
            ComponentFidelityProof,
            ComponentInstance,
            PlaceGroupOp,
        )
        from kir.decompile.fold import FidelityCanon

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
        """C-RT ON THE BRIDGE IS NOW CALLED (13.08.2026) — A FAIL
        CONTROL.

        `assert_group_matches_place_op` was written in full: it checks
        the multiset of the group's absolute expansion ops against the
        piecewise one IN BOTH DIRECTIONS and separately requires proven
        source accuracy. NOBODY called it except the tests — the bridge
        assembled the `create_group` IR without ever asking whether the
        expansion matched. The same thing as with the bridge itself, one
        floor down: written, declared in `__all__`, never called.

        We corrupt exactly what LOT31 corrupted: deltas in relative form
        (`occ_origin_k − def_origin` instead of `− occ_origin_0`). Before
        the fix, such an op would have assembled into the IR and shipped
        to the emitter.
        """
        from kir.decompile import materialize as _m
        from kir.decompile import native_group as _ng

        place_op = self._place_op()
        os.environ["KUKAI_IR_NATIVE_GROUP"] = "1"
        _m.reset_group_refusals()
        try:
            good = _ng.group_op_from_place_op(place_op)
            self.assertIsNotNone(good)
            # THE CORRUPTION DOES NOT DEPEND ON THE FIXTURE. The first
            # revision shifted the deltas by the definition's origin —
            # the shape of the LOT31 bug — and on the synthetic pair of
            # walls that origin is ZERO: the corruption became a no-op,
            # and the control was SKIPPED. A skip is honest and useless:
            # a guard that did not run guards nothing. A shift of one
            # meter always diverges.
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
        """THE REFUSALS STOPPED BEING SILENT.

        Each one used to be `return None`: the caller fell back to N
        piecewise elements and had no idea why the group did not happen.
        "There is no group" and "the group was refused for a named
        reason" must be different facts — the same class of defect as a
        silent list truncation and the quenching of a coverage
        inversion.

        Behavior does NOT change and must not change: falling back to
        the piecewise path is the correct answer, geometry is not lost.
        What changes is that WHY can now be asked.
        """
        from kir.decompile import materialize as _m

        os.environ["KUKAI_IR_NATIVE_GROUP"] = "1"
        _m.reset_group_refusals()
        try:
            # We patch GROUNDING: it is called inside a `try`, and its
            # refusal is exactly the path that, before 13.08, returned a
            # bare None.
            from kir import ground as _ground
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
