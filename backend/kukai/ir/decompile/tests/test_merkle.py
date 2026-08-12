"""Property tests for the Merkle-DAG layer (merkle.py).

Convention follows ``kukai/ir/tests/test_pbt.py``: hypothesis is not in the
prod venv, so properties run over seeded deterministic PRNG corpora.  All
buildings go through the REAL pipeline (``lift_document`` →
``fold_document``) — the layer is tested on genuine folded trees, not mocks.

Properties (numbering matches MERKLE_SPEC §6):
  P1 hash stability + child-order independence
  P2 translation invariance at integral-mm shifts
  P3 volatile fields out of the hash; shape changes in the hash
  P4 dedup correctness: corpus put never collides; distinct shapes distinct
  P5 diff soundness: diff(A,A)=∅; edits covered exactly; unchanged clean
  P6 early cutoff: no entries inside hash-equal subtrees; pruning happens
  P7 incremental ≡ full rebuild (canonical absolute op multiset equality)
  P8 persistence: deterministic bytes, fail-closed on tamper/corruption
  P9 dedup report: within- and cross-building repeats, DAG sharing
"""
from __future__ import annotations

import copy
import json
import os
import random
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from kukai.ir.decompile.fold import (
    TreeNode,
    canon_op,
    fold_document,
    iter_l1_leaves,
)
from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.merkle import (
    MerkleCollisionError,
    MerkleEdge,
    MerkleIntegrityError,
    MerkleNode,
    MerkleNodeMissingError,
    MerkleStore,
    build_index,
    dedup_report,
    diff_trees,
    incremental_plan,
    merkle_enabled,
    merkle_hash,
    node_origin,
)
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)

_ZERO = (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Deterministic synthetic buildings (real lift -> real fold)
# ---------------------------------------------------------------------------


def _document(
    levels: list[tuple[str, str, float]],
    elements: list[dict[str, Any]],
    *,
    name: str = "merkle-synthetic",
) -> L0Document:
    metadata = project1_metadata()
    metadata.update({
        "doc_name": name,
        "change_stamp": "synthetic-merkle-v1",
        "levels": [
            {"id": level_id, "name": level_name, "elevation_mm": elevation}
            for level_id, level_name, elevation in levels
        ],
        "grids": [],
        "rooms": [],
        "elements": copy.deepcopy(elements),
        "category_status": [],
        "links": [],
    })
    return L0Document.from_dict(metadata)


def _on_level(
    row: dict[str, Any], level: tuple[str, str, float],
) -> dict[str, Any]:
    row["level_id"] = level[0]
    row["level_name"] = level[1]
    return row


def _wall(
    element_id: int,
    level: tuple[str, str, float],
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
) -> dict[str, Any]:
    row = _on_level(make_element("OST_Walls", element_id, ordinal=0), level)
    row.update({
        "geom_kind": "curve",
        "p0_mm": list(p0),
        "p1_mm": list(p1),
        "rotation_deg": None,
        "bbox_min_mm": [
            min(p0[0], p1[0]), min(p0[1], p1[1]), min(p0[2], p1[2])],
        "bbox_max_mm": [
            max(p0[0], p1[0]), max(p0[1], p1[1]),
            max(p0[2], p1[2]) + 2_800.0],
        "params": {"WALL_USER_HEIGHT_PARAM": 2_800.0},
    })
    return row


def _furniture(
    element_id: int,
    level: tuple[str, str, float],
    point: tuple[float, float, float],
) -> dict[str, Any]:
    row = _on_level(
        make_element("OST_Furniture", element_id, ordinal=0), level)
    row.update({
        "geom_kind": "point",
        "p0_mm": list(point),
        "p1_mm": None,
        "rotation_deg": 0.0,
        "bbox_min_mm": [point[0] - 200.0, point[1] - 200.0, point[2]],
        "bbox_max_mm": [point[0] + 200.0, point[1] + 200.0, point[2] + 800.0],
    })
    return row


def _column(
    element_id: int,
    level: tuple[str, str, float],
    point: tuple[float, float, float],
) -> dict[str, Any]:
    row = _on_level(make_element("OST_Columns", element_id, ordinal=0), level)
    row.update({
        "geom_kind": "point",
        "p0_mm": list(point),
        "p1_mm": None,
        "rotation_deg": 0.0,
        "bbox_min_mm": [point[0] - 150.0, point[1] - 150.0, point[2]],
        "bbox_max_mm": [
            point[0] + 150.0, point[1] + 150.0, point[2] + 2_800.0],
    })
    return row


def _grid_building_elements(
    levels: list[tuple[str, str, float]],
    *,
    dx: float = 0.0,
    dy: float = 0.0,
    id_base: int = 10_000,
    wall_len: float = 6_000.0,
    stretch_wall_on_floor: int | None = None,
    drop_wall_on_floor: int | None = None,
    extra_furniture_on_floor: int | None = None,
) -> list[dict[str, Any]]:
    """One deterministic layout repeated per floor, with optional edits."""

    elements: list[dict[str, Any]] = []
    eid = id_base
    for floor_index, level in enumerate(levels):
        z = level[2]
        stretch = 500.0 if stretch_wall_on_floor == floor_index else 0.0
        corners = [
            ((0.0, 0.0), (wall_len + stretch, 0.0)),
            ((wall_len, 0.0), (wall_len, 4_000.0)),
            ((wall_len, 4_000.0), (0.0, 4_000.0)),
            ((0.0, 4_000.0), (0.0, 0.0)),
        ]
        for wall_index, ((x0, y0), (x1, y1)) in enumerate(corners):
            if drop_wall_on_floor == floor_index and wall_index == 2:
                eid += 1
                continue
            elements.append(_wall(
                eid, level,
                (x0 + dx, y0 + dy, z), (x1 + dx, y1 + dy, z)))
            eid += 1
        for cx in range(2):
            for cy in range(2):
                elements.append(_column(
                    eid, level,
                    (1_000.0 + cx * 3_000.0 + dx,
                     1_000.0 + cy * 2_000.0 + dy, z)))
                eid += 1
        # 12 furniture leaves keep a single-edit floor within the fold's
        # SIM_THRESHOLD (0.90) so the vertical stack survives the edit and
        # the diff exercises deep recursion instead of a stack collapse.
        count = 12 + (1 if extra_furniture_on_floor == floor_index else 0)
        for item in range(count):
            elements.append(_furniture(
                eid, level,
                (200.0 + item * 200.0 + dx, 300.0 + dy, z)))
            eid += 1
    return elements


def _grid_building(
    *,
    floors: int = 3,
    dx: float = 0.0,
    dy: float = 0.0,
    dz: float = 0.0,
    id_base: int = 10_000,
    wall_len: float = 6_000.0,
    name: str = "grid-building",
    stretch_wall_on_floor: int | None = None,
    drop_wall_on_floor: int | None = None,
    extra_furniture_on_floor: int | None = None,
) -> L0Document:
    levels = [
        (str(100 + index), f"Этаж {index + 1}", dz + index * 3_000.0)
        for index in range(floors)
    ]
    elements = _grid_building_elements(
        levels,
        dx=dx, dy=dy, id_base=id_base, wall_len=wall_len,
        stretch_wall_on_floor=stretch_wall_on_floor,
        drop_wall_on_floor=drop_wall_on_floor,
        extra_furniture_on_floor=extra_furniture_on_floor,
    )
    return _document(levels, elements, name=name)


def _cluster_building(
    *,
    clusters: int = 3,
    spacing: float = 16_000.0,
    id_base: int = 40_000,
    name: str = "cluster-building",
    move_cluster: tuple[int, float] | None = None,
) -> L0Document:
    """K identical wall+furniture clusters, one zone each (drawn once, ×K)."""

    level = ("100", "Этаж 1", 0.0)
    elements: list[dict[str, Any]] = []
    eid = id_base
    for cluster in range(clusters):
        base_x = cluster * spacing
        if move_cluster is not None and move_cluster[0] == cluster:
            base_x = move_cluster[1]
        elements.append(_wall(
            eid, level, (base_x, 0.0, 0.0), (base_x + 4_000.0, 0.0, 0.0)))
        eid += 1
        elements.append(_wall(
            eid, level,
            (base_x, 2_000.0, 0.0), (base_x + 4_000.0, 2_000.0, 0.0)))
        eid += 1
        for item in range(5):
            elements.append(_furniture(
                eid, level, (base_x + 200.0 + item * 200.0, 500.0, 0.0)))
            eid += 1
    return _document([level], elements, name=name)


def _fold(document: L0Document) -> TreeNode:
    return fold_document(document, lift_document(document))


def _absolute_multiset(leaves: Iterable[Any]) -> Counter[str]:
    return Counter(canon_op(leaf, _ZERO) for leaf in leaves)


def _tree_node_total(tree: TreeNode) -> int:
    total = 1
    for child in tree["children"]:
        total += _tree_node_total(child)
    return total


def _shuffle_children(tree: TreeNode, rng: random.Random) -> None:
    rng.shuffle(tree["children"])
    for child in tree["children"]:
        _shuffle_children(child, rng)


class MerkleHashProperties(unittest.TestCase):
    def test_p1_same_document_same_hash_and_child_order_independence(
            self) -> None:
        document = _grid_building(floors=3)
        tree_one = _fold(document)
        tree_two = _fold(_grid_building(floors=3))
        self.assertEqual(merkle_hash(tree_one), merkle_hash(tree_two))

        shuffled = copy.deepcopy(tree_one)
        for seed in range(5):
            _shuffle_children(shuffled, random.Random(seed))
            self.assertEqual(merkle_hash(shuffled), merkle_hash(tree_one))

    def test_p1_index_store_and_direct_hash_agree(self) -> None:
        tree = _fold(_grid_building(floors=2))
        store = MerkleStore()
        index = build_index(tree, label="a", store=store)
        self.assertEqual(index.root_hash, merkle_hash(tree))
        self.assertEqual(store.put(tree), index.root_hash)
        self.assertTrue(store.has(index.root_hash))

    def test_p2_translation_invariance_integral_mm(self) -> None:
        base = _fold(_grid_building(floors=3))
        # x/y shifts stay multiples of both grid cells (zone 8 m, atom 5 m)
        # so the fold's own absolute-grid partitioning keeps its structure;
        # z is free (level elevations shift with the building).
        for dx, dy, dz in [
            (40_000.0, 0.0, 0.0),
            (-80_000.0, 40_000.0, 0.0),
            (0.0, 0.0, 7_000.0),
            (40_000.0, -40_000.0, -3_000.0),
        ]:
            shifted = _fold(_grid_building(floors=3, dx=dx, dy=dy, dz=dz))
            self.assertEqual(
                merkle_hash(base), merkle_hash(shifted),
                f"shift ({dx},{dy},{dz}) must not change the shape hash")

    def test_p2_store_content_identical_after_translation(self) -> None:
        store_a = MerkleStore()
        store_b = MerkleStore()
        build_index(_fold(_grid_building(floors=2)), store=store_a)
        build_index(
            _fold(_grid_building(floors=2, dx=40_000.0, dz=6_000.0)),
            store=store_b)
        self.assertEqual(store_a.hashes(), store_b.hashes())

    def test_p3_ids_and_doc_name_are_volatile(self) -> None:
        base = _fold(_grid_building(floors=2, id_base=10_000, name="one"))
        renumbered = _fold(
            _grid_building(floors=2, id_base=50_000, name="two"))
        self.assertEqual(merkle_hash(base), merkle_hash(renumbered))

    def test_p3_shape_changes_change_the_hash(self) -> None:
        base = merkle_hash(_fold(_grid_building(floors=2)))
        longer_walls = merkle_hash(
            _fold(_grid_building(floors=2, wall_len=6_500.0)))
        more_floors = merkle_hash(_fold(_grid_building(floors=3)))
        self.assertNotEqual(base, longer_walls)
        self.assertNotEqual(base, more_floors)
        self.assertNotEqual(longer_walls, more_floors)

    def test_identical_floors_share_one_dag_node(self) -> None:
        tree = _fold(_grid_building(floors=4))
        store = MerkleStore()
        index = build_index(tree, store=store)
        # Four identical floors -> one stored floor subtree; the DAG store
        # holds strictly fewer nodes than the tree has positions.
        self.assertLess(len(store), index.node_count)
        floor_occurrences = [
            occs for occs in index.occurrences.values()
            if occs[0].tree_node["kind"] == "floor"
        ]
        self.assertTrue(
            any(len(occs) == 4 for occs in floor_occurrences),
            "identical floors must collapse onto one hash")

    def test_node_origin_is_not_bbox_min_where_they_must_differ(self) -> None:
        # ЭТОТ ТЕСТ БЫЛ ИМЕНОВАН `..._is_rounded_bbox_min` И УТВЕРЖДАЛ РАВЕНСТВО
        # РОВНО С ТЕМ, ЧТО ДОКСТРОКА `node_origin` НАЗЫВАЕТ НЕПРИГОДНЫМ.
        # Он проходил не по контракту, а по совпадению фикстуры: один этаж на
        # отметке 0, где обе величины нули. Замер 09.08.2026 на трёх этажах:
        # у подеревьев на 3000 и 6000 мм `facts.bbox_min_mm` == (0,0,0) —
        # fold зануляет z двумерных точек параметров, — а `node_origin` даёт
        # (0,0,3000) и (0,0,6000). Если кто-нибудь «починит» `node_origin` на
        # `bbox_min`, прежний тест позеленеет, а локализация содержимого
        # относительно начала перестанет быть инвариантной к переносу по
        # высоте: все поднятые этажи прижмутся к мировому нулю и перестанут
        # совпадать по хешу с таким же этажом на другой отметке.
        tree = _fold(_grid_building(floors=3))
        floors = tree["children"][0]["children"]
        elevations = [0.0, 3_000.0, 6_000.0]
        for floor, elevation in zip(floors, elevations, strict=True):
            with self.subTest(elevation=elevation):
                origin = node_origin(floor)
                bbox_min = floor["facts"]["bbox_min_mm"]
                assert bbox_min is not None
                self.assertEqual(
                    origin[2], elevation,
                    "начало узла обязано следовать за отметкой этажа")
                self.assertEqual(
                    bbox_min[2], 0.0,
                    "предпосылка теста: bbox_min зануляет z — если это "
                    "изменилось, тест нужно перемерить, а не подправить")
                if elevation:
                    self.assertNotEqual(
                        (origin[0], origin[1], origin[2]),
                        (bbox_min[0], bbox_min[1], bbox_min[2]))

    def test_node_origin_equals_bbox_min_only_on_the_ground_floor(self) -> None:
        # Сохранённая половина прежнего утверждения — но названная тем, чем она
        # является: совпадением на отметке 0, а не определением величины.
        tree = _fold(_grid_building(floors=1))
        origin = node_origin(tree)
        bbox_min = tree["facts"]["bbox_min_mm"]
        assert bbox_min is not None
        self.assertEqual(
            origin, (bbox_min[0], bbox_min[1], bbox_min[2]))

    def test_empty_building_hashes_deterministically(self) -> None:
        document = _document([("100", "Этаж 1", 0.0)], [])
        tree_one = _fold(document)
        tree_two = _fold(_document([("100", "Этаж 1", 0.0)], []))
        self.assertEqual(merkle_hash(tree_one), merkle_hash(tree_two))
        self.assertEqual(node_origin(tree_one), (0.0, 0.0, 0.0))


class StoreProperties(unittest.TestCase):
    def test_p4_generated_corpus_never_collides(self) -> None:
        rng = random.Random(20260720)
        store = MerkleStore()
        roots: list[str] = []
        grid_params: set[tuple[int, float]] = set()
        while len(grid_params) < 6:
            grid_params.add((
                rng.randint(1, 4),
                rng.choice([4_000.0, 5_000.0, 6_000.0]),
            ))
        for floors, wall_len in sorted(grid_params):
            index = build_index(
                _fold(_grid_building(floors=floors, wall_len=wall_len)),
                store=store)
            roots.append(index.root_hash)
        for clusters in (2, 3, 4):
            index = build_index(
                _fold(_cluster_building(clusters=clusters)),
                store=store)
            roots.append(index.root_hash)
        # Distinct structures -> distinct roots (and no put() ever raised).
        self.assertEqual(len(roots), len(set(roots)))

    def test_p4_reinserting_the_same_building_is_idempotent(self) -> None:
        store = MerkleStore()
        tree = _fold(_grid_building(floors=2))
        first = store.put(tree)
        size = len(store)
        second = store.put(_fold(_grid_building(floors=2)))
        self.assertEqual(first, second)
        self.assertEqual(len(store), size)

    def test_get_missing_hash_fails_closed(self) -> None:
        store = MerkleStore()
        with self.assertRaises(MerkleNodeMissingError):
            store.get("0" * 64)

    def test_orphan_edge_fails_closed(self) -> None:
        store = MerkleStore()
        with self.assertRaises(MerkleIntegrityError):
            store._put_merkle_node(MerkleNode(
                hash="f" * 64,
                kind="floor",
                content_json='{"kind":"floor"}',
                edges=(MerkleEdge("e" * 64, (0.0, 0.0, 0.0)),),
                leaf_count=1,
            ))

    def test_forged_collision_fails_closed(self) -> None:
        store = MerkleStore()
        root = store.put(_fold(_grid_building(floors=1)))
        stored = store.get(root)
        forged = MerkleNode(
            hash=stored.hash,
            kind=stored.kind,
            content_json=stored.content_json,
            edges=stored.edges,
            leaf_count=stored.leaf_count + 1,
        )
        with self.assertRaises(MerkleCollisionError):
            store._put_merkle_node(forged)

    def test_reconstruct_is_deterministic(self) -> None:
        tree = _fold(_grid_building(floors=2))
        store_a = MerkleStore()
        store_b = MerkleStore()
        root_a = store_a.put(tree)
        root_b = store_b.put(_fold(_grid_building(floors=2)))
        self.assertEqual(
            store_a.reconstruct(root_a), store_b.reconstruct(root_b))


class PersistenceProperties(unittest.TestCase):
    def _dumped(self) -> tuple[MerkleStore, str, Path]:
        store = MerkleStore()
        root = store.put(_fold(_grid_building(floors=2)))
        directory = Path(tempfile.mkdtemp(prefix="merkle-test-"))
        path = directory / "store.jsonl"
        store.dump_jsonl(path)
        return store, root, path

    def test_p8_round_trip_and_byte_determinism(self) -> None:
        store, root, path = self._dumped()
        first_bytes = path.read_bytes()
        store.dump_jsonl(path)
        self.assertEqual(first_bytes, path.read_bytes())

        loaded = MerkleStore()
        added = loaded.load_jsonl(path)
        self.assertEqual(added, len(store))
        self.assertEqual(loaded.hashes(), store.hashes())
        for node_hash in store.hashes():
            self.assertEqual(loaded.get(node_hash), store.get(node_hash))
        self.assertEqual(loaded.reconstruct(root), store.reconstruct(root))

    def test_p8_tampered_content_fails_closed(self) -> None:
        _store, _root, path = self._dumped()
        lines = path.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[0])
        row["kind"] = row["kind"] + "-tampered"
        lines[0] = json.dumps(row, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(MerkleIntegrityError):
            MerkleStore().load_jsonl(path)

    def test_p8_tampered_leaf_count_fails_closed(self) -> None:
        _store, _root, path = self._dumped()
        lines = path.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[-1])
        row["leaf_count"] = row["leaf_count"] + 7
        lines[-1] = json.dumps(row, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(MerkleIntegrityError):
            MerkleStore().load_jsonl(path)

    def test_p8_missing_child_line_fails_closed(self) -> None:
        store, root, path = self._dumped()
        keep = [
            node_hash for node_hash in store.hashes() if node_hash != root]
        removed_child = next(
            edge.child_hash for edge in store.get(root).edges)
        lines = [
            line for line in path.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["hash"] != removed_child
        ]
        self.assertLess(len(lines), len(keep) + 1)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(MerkleIntegrityError):
            MerkleStore().load_jsonl(path)

    def test_p8_duplicate_hash_different_content_fails_closed(self) -> None:
        _store, _root, path = self._dumped()
        lines = path.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[0])
        row["leaf_count"] = row["leaf_count"] + 1
        lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(MerkleCollisionError):
            MerkleStore().load_jsonl(path)

    def test_p8_garbage_line_fails_closed(self) -> None:
        _store, _root, path = self._dumped()
        with path.open("a", encoding="utf-8") as handle:
            handle.write("{not json}\n")
        with self.assertRaises(MerkleIntegrityError):
            MerkleStore().load_jsonl(path)


def _truth_delta(
    tree_a: TreeNode, tree_b: TreeNode,
) -> tuple[Counter[str], Counter[str]]:
    """Ground-truth canonical-absolute leaf delta, independent of the layer."""

    multiset_a = _absolute_multiset(iter_l1_leaves(tree_a))
    multiset_b = _absolute_multiset(iter_l1_leaves(tree_b))
    removed = multiset_a - multiset_b
    added = multiset_b - multiset_a
    return removed, added


def _single_edit_scenarios() -> list[
        tuple[str, TreeNode, TreeNode, set[str], set[str]]]:
    """Structure-stable A -> B pairs with exact ground-truth edited ids.

    Generator id layout per floor (sequential): 4 walls, 4 columns, then 12
    furniture — 20 ids per floor, base 10_000.  Each edit is small enough
    for the fold's near-match threshold, so the floor stack survives and
    the diff must find the change deep inside it.
    """

    per_floor = 4 + 4 + 12
    scenarios: list[tuple[str, TreeNode, TreeNode, set[str], set[str]]] = []

    stretched_wall = str(10_000 + 1 * per_floor + 0)       # floor 1, wall 0
    scenarios.append((
        "stretch-wall",
        _fold(_grid_building(floors=3, name="A")),
        _fold(_grid_building(floors=3, name="B", stretch_wall_on_floor=1)),
        {stretched_wall},
        {stretched_wall},
    ))

    added_furniture = str(10_000 + 8 + 12)                 # floor 0, extra
    scenarios.append((
        "add-furniture",
        _fold(_grid_building(floors=3, name="A")),
        _fold(_grid_building(
            floors=3, name="B", extra_furniture_on_floor=0)),
        set(),
        {added_furniture},
    ))

    dropped_wall = str(10_000 + 2 * per_floor + 2)         # floor 2, wall 2
    scenarios.append((
        "drop-wall",
        _fold(_grid_building(floors=3, name="A")),
        _fold(_grid_building(floors=3, name="B", drop_wall_on_floor=2)),
        {dropped_wall},
        set(),
    ))
    return scenarios


class DiffProperties(unittest.TestCase):
    def test_p5_diff_of_identical_buildings_is_empty(self) -> None:
        index_a = build_index(_fold(_grid_building(floors=3)), label="a")
        index_b = build_index(_fold(_grid_building(floors=3)), label="b")
        diff = diff_trees(index_a, index_b)
        self.assertTrue(diff.is_empty)
        self.assertEqual(diff.entries, ())
        self.assertGreaterEqual(diff.pruned, 1)

    def test_p5_single_edits_are_covered_exactly(self) -> None:
        for name, tree_a, tree_b, truth_a, truth_b in \
                _single_edit_scenarios():
            with self.subTest(scenario=name):
                # Layer-independent ground truth: the edit really changed
                # the canonical absolute leaf multiset.
                removed_truth, added_truth = _truth_delta(tree_a, tree_b)
                self.assertTrue(removed_truth or added_truth)
                diff = diff_trees(
                    build_index(tree_a, label="a"),
                    build_index(tree_b, label="b"))
                self.assertEqual(
                    set(diff.changed_source_ids_a), truth_a, name)
                self.assertEqual(
                    set(diff.changed_source_ids_b), truth_b, name)

    def test_p5_unchanged_subtrees_contain_no_edited_leaf(self) -> None:
        for name, tree_a, tree_b, truth_a, truth_b in \
                _single_edit_scenarios():
            with self.subTest(scenario=name):
                index_a = build_index(tree_a, label="a")
                index_b = build_index(tree_b, label="b")
                diff = diff_trees(index_a, index_b)
                for pair in diff.unchanged:
                    occ_a = index_a.by_path[pair.path_a]
                    occ_b = index_b.by_path[pair.path_b]
                    ids_a = {
                        leaf["source_element_id"]
                        for leaf in iter_l1_leaves(occ_a.tree_node)}
                    ids_b = {
                        leaf["source_element_id"]
                        for leaf in iter_l1_leaves(occ_b.tree_node)}
                    self.assertFalse(ids_a & truth_a)
                    self.assertFalse(ids_b & truth_b)
                    # The shared subtree really is byte-identical at
                    # absolute coordinates (the reuse guarantee).
                    self.assertEqual(
                        _absolute_multiset(iter_l1_leaves(occ_a.tree_node)),
                        _absolute_multiset(iter_l1_leaves(occ_b.tree_node)))

    def test_p6_local_edit_prunes_far_subtrees(self) -> None:
        _name, tree_a, tree_b, _ta, _tb = _single_edit_scenarios()[0]
        diff = diff_trees(
            build_index(tree_a, label="a"), build_index(tree_b, label="b"))
        self.assertGreaterEqual(diff.pruned, 2)
        # No diff entry may live strictly inside an unchanged boundary.
        unchanged_b = [pair.path_b for pair in diff.unchanged]
        for entry in diff.entries:
            if entry.path_b is None:
                continue
            for boundary in unchanged_b:
                self.assertFalse(
                    len(boundary) < len(entry.path_b)
                    and entry.path_b[:len(boundary)] == boundary,
                    "diff entry inside an unchanged subtree")

    def test_moved_cluster_is_reported_moved_not_rebuilt(self) -> None:
        tree_a = _fold(_cluster_building(clusters=3, name="A"))
        tree_b = _fold(_cluster_building(
            clusters=3, name="B", move_cluster=(2, 48_000.0)))
        diff = diff_trees(
            build_index(tree_a, label="a"), build_index(tree_b, label="b"))
        moved = [e for e in diff.entries if e.status == "moved"]
        self.assertEqual(len(moved), 1)
        # Ancestors of the move are reported changed (their edge offsets
        # changed) but carry NO own-level leaf changes.
        for entry in diff.entries:
            if entry.status == "moved":
                continue
            self.assertEqual(entry.status, "changed")
            self.assertEqual(entry.leaf_source_ids_a, ())
            self.assertEqual(entry.leaf_source_ids_b, ())

    def test_structural_reshape_stays_sound(self) -> None:
        # Removing one column collapses a 2x2 grid pattern into loose
        # leaves: subtree-granular diff may over-report inside that group,
        # but must stay sound (cover the removal, never invent leaves
        # outside the reshaped group) and must not disturb other floors.
        tree_a = _fold(_grid_building(floors=2, name="A"))
        levels = [
            (str(100 + index), f"Этаж {index + 1}", index * 3_000.0)
            for index in range(2)
        ]
        elements = _grid_building_elements(levels)
        removed_column = elements[4 + 1]  # floor 0: 4 walls, then columns
        assert removed_column["category"] == "OST_Columns"
        elements = [
            row for row in elements
            if row["element_id"] != removed_column["element_id"]
        ]
        tree_b = _fold(_document(levels, elements, name="B"))

        removed_truth, added_truth = _truth_delta(tree_a, tree_b)
        diff = diff_trees(
            build_index(tree_a, label="a"), build_index(tree_b, label="b"))
        self.assertIn(
            removed_column["element_id"], diff.changed_source_ids_a)
        per_floor_ids = {
            str(10_000 + offset) for offset in range(4, 8)}  # floor-0 columns
        self.assertLessEqual(set(diff.changed_source_ids_a), per_floor_ids)
        self.assertLessEqual(set(diff.changed_source_ids_b), per_floor_ids)


class IncrementalPlanProperties(unittest.TestCase):
    def _plan(
        self, tree_a: TreeNode, tree_b: TreeNode,
    ) -> tuple[Any, Any, Any]:
        index_a = build_index(tree_a, label="a")
        index_b = build_index(tree_b, label="b")
        diff = diff_trees(index_a, index_b)
        return incremental_plan(diff, index_a, index_b), index_a, index_b

    def _assert_equivalent(self, tree_a: TreeNode, tree_b: TreeNode) -> None:
        plan, index_a, index_b = self._plan(tree_a, tree_b)

        # (1) Exact partition: every leaf of B is covered exactly once.
        covered_b: list[str] = []
        for entry in plan.reuse:
            covered_b.extend(entry.source_ids_b)
        covered_b.extend(item.source_id_b for item in plan.leaf_reuse)
        for entry in plan.relocate:
            covered_b.extend(
                leaf["source_element_id"] for leaf in entry.payloads_b)
        for entry in plan.emit:
            covered_b.extend(
                leaf["source_element_id"] for leaf in entry.payloads_b)
        all_b = sorted(
            leaf["source_element_id"] for leaf in iter_l1_leaves(tree_b))
        self.assertEqual(sorted(covered_b), all_b)

        # (2) Multiset equivalence: reused A-leaves + relocated/emitted
        # B-leaves reproduce a full rebuild of B byte-for-byte (canonical
        # ops at absolute coordinates).
        produced: Counter[str] = Counter()
        for entry in plan.reuse:
            occ_a = index_a.by_path[entry.path_a]
            produced += _absolute_multiset(iter_l1_leaves(occ_a.tree_node))
        leaves_a_by_id = {
            leaf["source_element_id"]: leaf for leaf in iter_l1_leaves(tree_a)}
        for item in plan.leaf_reuse:
            produced += _absolute_multiset([leaves_a_by_id[item.source_id_a]])
        for entry in plan.relocate:
            produced += _absolute_multiset(entry.payloads_b)
        for entry in plan.emit:
            produced += _absolute_multiset(entry.payloads_b)
        self.assertEqual(
            produced, _absolute_multiset(iter_l1_leaves(tree_b)),
            "incremental rebuild must equal a full rebuild of B")

    def test_p7_incremental_equals_full_rebuild_after_edits(self) -> None:
        tree_a = _fold(_grid_building(floors=3, name="A"))
        tree_b = _fold(_grid_building(
            floors=3, name="B",
            stretch_wall_on_floor=1,
            extra_furniture_on_floor=0,
            drop_wall_on_floor=2,
        ))
        self._assert_equivalent(tree_a, tree_b)

    def test_p7_identical_buildings_reuse_everything(self) -> None:
        tree_a = _fold(_grid_building(floors=3))
        tree_b = _fold(_grid_building(floors=3))
        plan, _index_a, _index_b = self._plan(tree_a, tree_b)
        self.assertEqual(plan.emit, ())
        self.assertEqual(plan.retire, ())
        self.assertEqual(plan.relocate, ())
        total = sum(1 for _ in iter_l1_leaves(tree_b))
        self.assertEqual(plan.reused_leaf_total, total)
        self._assert_equivalent(tree_a, tree_b)

    def test_p7_moved_cluster_relocates_not_reemits(self) -> None:
        tree_a = _fold(_cluster_building(clusters=3, name="A"))
        tree_b = _fold(_cluster_building(
            clusters=3, name="B", move_cluster=(2, 48_000.0)))
        plan, _index_a, _index_b = self._plan(tree_a, tree_b)
        self.assertEqual(len(plan.relocate), 1)
        self.assertEqual(plan.emit, ())
        self.assertEqual(plan.retire, ())
        self.assertEqual(plan.relocate[0].offset_mm, (16_000.0, 0.0, 0.0))
        self._assert_equivalent(tree_a, tree_b)

    def test_p7_structural_reshape_still_equivalent(self) -> None:
        levels = [
            (str(100 + index), f"Этаж {index + 1}", index * 3_000.0)
            for index in range(2)
        ]
        elements = _grid_building_elements(levels)
        tree_a = _fold(_grid_building(floors=2, name="A"))
        removed = elements[5]["element_id"]
        tree_b = _fold(_document(
            levels,
            [row for row in elements if row["element_id"] != removed],
            name="B"))
        self._assert_equivalent(tree_a, tree_b)

    def test_p7_seeded_random_edit_scripts_stay_equivalent(self) -> None:
        rng = random.Random(1234)
        for _case in range(4):
            floors = rng.randint(2, 3)
            tree_a = _fold(_grid_building(floors=floors, name="A"))
            tree_b = _fold(_grid_building(
                floors=floors, name="B",
                stretch_wall_on_floor=(
                    rng.randrange(floors) if rng.random() < 0.7 else None),
                extra_furniture_on_floor=(
                    rng.randrange(floors) if rng.random() < 0.7 else None),
                drop_wall_on_floor=(
                    rng.randrange(floors) if rng.random() < 0.7 else None),
            ))
            self._assert_equivalent(tree_a, tree_b)


class DedupProperties(unittest.TestCase):
    def test_p9_repeated_clusters_within_one_building(self) -> None:
        index = build_index(
            _fold(_cluster_building(clusters=3)), label="lot")
        report = dedup_report([index])
        self.assertTrue(report)
        best = report[0]
        self.assertEqual(best.occurrence_count, 3)
        self.assertEqual(best.by_building, (("lot", 3),))
        self.assertGreaterEqual(best.leaf_count, 7)

    def test_p9_typical_floors_are_reported(self) -> None:
        index = build_index(_fold(_grid_building(floors=4)), label="lot")
        report = dedup_report([index])
        floor_entries = [
            entry for entry in report if entry.kind == "floor"]
        self.assertEqual(len(floor_entries), 1)
        self.assertEqual(floor_entries[0].occurrence_count, 4)

    def test_p9_cross_building_dedup_and_dag_sharing(self) -> None:
        # Different buildings (2 vs 3 clusters) sharing one drawn-once
        # component; identical whole buildings would legitimately dedup at
        # the building root instead (dominance).
        store = MerkleStore()
        index_a = build_index(
            _fold(_cluster_building(clusters=2, id_base=40_000, name="A")),
            label="A", store=store)
        index_b = build_index(
            _fold(_cluster_building(clusters=3, id_base=70_000, name="B")),
            label="B", store=store)
        self.assertLess(
            len(store), index_a.node_count + index_b.node_count)
        report = dedup_report([index_a, index_b])
        best = report[0]
        self.assertEqual(best.occurrence_count, 5)
        self.assertEqual(best.by_building, (("A", 2), ("B", 3)))

    def test_p9_two_identical_buildings_dedup_at_the_root(self) -> None:
        index_a = build_index(
            _fold(_cluster_building(clusters=2, id_base=40_000, name="A")),
            label="A")
        index_b = build_index(
            _fold(_cluster_building(clusters=2, id_base=70_000, name="B")),
            label="B")
        report = dedup_report([index_a, index_b])
        self.assertTrue(report)
        self.assertEqual(report[0].kind, "building")
        self.assertEqual(report[0].occurrence_count, 2)

    def test_p9_dominated_nested_repeats_are_hidden_by_default(self) -> None:
        index = build_index(
            _fold(_cluster_building(clusters=3)), label="lot")
        report = dedup_report([index])
        shown_paths = {entry.hash for entry in report}
        full = dedup_report([index], include_dominated=True)
        hidden = [entry for entry in full if entry.dominated]
        # The furniture cluster inside each repeated zone is dominated.
        self.assertTrue(hidden)
        for entry in hidden:
            self.assertNotIn(entry.hash, shown_paths)

    def test_min_occurrences_guard(self) -> None:
        index = build_index(_fold(_grid_building(floors=1)), label="lot")
        with self.assertRaises(ValueError):
            dedup_report([index], min_occurrences=1)


class FlagTests(unittest.TestCase):
    def test_default_off(self) -> None:
        previous = os.environ.pop("KUKAI_IR_MERKLE", None)
        try:
            self.assertFalse(merkle_enabled())
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_MERKLE"] = previous

    def test_opt_in(self) -> None:
        previous = os.environ.get("KUKAI_IR_MERKLE")
        os.environ["KUKAI_IR_MERKLE"] = "1"
        try:
            self.assertTrue(merkle_enabled())
        finally:
            if previous is None:
                del os.environ["KUKAI_IR_MERKLE"]
            else:
                os.environ["KUKAI_IR_MERKLE"] = previous

    def test_malformed_tree_fails_closed(self) -> None:
        with self.assertRaises(MerkleIntegrityError):
            merkle_hash({"kind": "building"})  # type: ignore[arg-type]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
