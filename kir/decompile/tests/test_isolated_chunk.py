"""Blast radius: a host with an auto-panel takes its whole program down with
it.

MEASUREMENT of 28.07, a live rebuild of the SOB6.2 facade (run v7). A chunk
of 250 ops rolled back ENTIRELY, creating not a single element:

    transaction commit status: RolledBack | Revit: Error: Не удалось
    сформировать тип "ATR_Панель витража с решеткой : Интегрированная
    Вентиляционная решетка". [элементы: 11401364, 11402544]

Both named elements are auto-panels that Revit generates ITSELF when
creating a curtain-type wall whose "Curtain Panel" parameter (AUTO_PANEL_WALL)
points to a loadable family. Probe P1 showed that ONE such wall builds; the
failed chunk had five of them.

Why this is cured by chunk size, not by isolating the op: per the assembly
documentation for ``SubTransaction.Commit`` — "the changes are not
permanently committed … only when the active transaction is committed", and
the regeneration failure arrives deferred, on the parent's Commit. A per-op
wrapper cannot hold this BY CONSTRUCTION; only the program's boundary can
hold it.

What gets isolated is the GROUP, not the op: a host can have attached ops
(cells), and pulling the host out without them would tear host-atomicity
(D5a).
"""
from __future__ import annotations

import copy
import json
import pathlib
import unittest
from typing import Any

from kir import idempotence as K
from kir.decompile.curtain_extract import CURTAIN_INDEX_SCHEMA_VERSION
from kir.decompile.lift import lift_document_detailed
from kir.decompile.materialize import leaves_to_program
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)


GRILLE_A, GRILLE_B = "10006233", "10014126"
PLAIN = "8145901"
FAMILY_DEFAULT = "7924568"       # a type from a LOADABLE grille family
WALL_DEFAULT = "7469627"         # a WALL type — the cell is occupied by a wall-body


def _host_row(*, default_type: str, family_default: bool,
              panel_suffix: str = "") -> dict[str, Any]:
    """A host row in the shape of the live index /3.

    ``panel_suffix`` distinguishes the panel_id for GRILLE_A/GRILLE_B (codex
    #4, 2026-07-29): both call this helper with the SAME default_type
    (FAMILY_DEFAULT), and without the suffix they got a LITERALLY shared
    panel_id — global injectivity (`_curtain_side_index`) now honestly
    catches this as a collision between hosts and isolates both. In a real
    document element_id is globally unique; here it was a fixture
    coincidence, not what the test intended to check.
    """

    panel: dict[str, Any] = {
        "panel_id": f"p{default_type}{panel_suffix}",
        "is_family_instance": True,
        "family_name": "Семейство панели",
        "type_name": "тип ячейки",
        "type_id": default_type,
        "host_panel_id": None if family_default else "body-1",
        "host_panel_type_id": None if family_default else default_type,
        "host_panel_type_name": None if family_default else "тип стены",
        "u_index": 0, "v_index": 0, "address_state": "ok", "is_door": False,
    }
    return {
        "curtain_available": True,
        "host_kind": "wall",
        "default_panel_type_id": default_type,
        "default_panel_type_name": "тип разрезки",
        "default_panel_state": "ok",
        "default_panel_source": "AUTO_PANEL_WALL",
        "u_grid_lines": [], "v_grid_lines": [], "mullions": [],
        "panels": [panel],
    }


def _index() -> dict[str, Any]:
    return {
        "schema_version": CURTAIN_INDEX_SCHEMA_VERSION,
        "curtain_index": {
            GRILLE_A: _host_row(default_type=FAMILY_DEFAULT,
                                family_default=True, panel_suffix="A"),
            GRILLE_B: _host_row(default_type=FAMILY_DEFAULT,
                                family_default=True, panel_suffix="B"),
            PLAIN: _host_row(default_type=WALL_DEFAULT, family_default=False),
        },
        "failures": [],
    }


def _document() -> L0Document:
    elements = []
    for ordinal, host in enumerate((GRILLE_A, GRILLE_B, PLAIN)):
        wall = make_element("OST_Walls", 900 + ordinal, ordinal=ordinal)
        wall["element_id"] = host
        elements.append(wall)
    # a few more ordinary walls — "the rest of the chunk"
    for ordinal in range(3, 9):
        wall = make_element("OST_Walls", 900 + ordinal, ordinal=ordinal)
        elements.append(wall)
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "isolation-v1"
    row["elements"] = elements
    row["category_status"] = []
    return L0Document.from_dict(row)


def _leaves():
    return lift_document_detailed(_document(), curtain_index=_index()).nodes


class TheRiskyHostGetsItsOwnProgram(unittest.TestCase):
    def test_today_both_grille_hosts_share_one_chunk(self) -> None:
        """Pre-state: one refusal carries off its neighbors."""

        programs = leaves_to_program(_leaves(), chunk_target=250).programs
        holders = [i for i, program in enumerate(programs)
                   if {op["id"][1:] for op in program["ops"]}
                   & {GRILLE_A, GRILLE_B}]
        self.assertEqual(len(holders), 1, "оба носителя в одной программе")
        self.assertGreater(len(programs[holders[0]]["ops"]), 2,
                           "и вместе с ними — соседи, которым отказ не свой")

    def test_isolated_hosts_leave_with_their_own_program_each(self) -> None:
        leaves = _leaves()
        isolate = K.curtain_hosts_needing_isolation(_index())
        self.assertEqual(isolate, frozenset({GRILLE_A, GRILLE_B}))

        result = leaves_to_program(
            leaves, chunk_target=250, solo_source_ids=isolate)
        self.assertEqual(result.stats.isolated_groups, 2)
        for host in (GRILLE_A, GRILLE_B):
            with self.subTest(host=host):
                owning = [program for program in result.programs
                          if any(op["id"][1:] == host
                                 for op in program["ops"])]
                self.assertEqual(len(owning), 1)
                self.assertEqual(
                    [op["id"][1:] for op in owning[0]["ops"]], [host],
                    "изолированная группа не тащит соседей")
        # the remaining walls still travel together
        rest = [program for program in result.programs
                if len(program["ops"]) > 1]
        self.assertTrue(rest, "обычные стены остались в общем чанке")

    def test_no_op_is_lost_or_duplicated_by_isolation(self) -> None:
        """Isolation is a reordering, not a filter."""

        leaves = _leaves()
        plain = leaves_to_program(leaves, chunk_target=250)
        isolated = leaves_to_program(
            leaves, chunk_target=250,
            solo_source_ids=K.curtain_hosts_needing_isolation(_index()))
        before = sorted(op["id"] for program in plain.programs
                        for op in program["ops"])
        after = sorted(op["id"] for program in isolated.programs
                       for op in program["ops"])
        self.assertEqual(before, after)
        self.assertEqual(plain.stats.materialized_ops,
                         isolated.stats.materialized_ops)


class ThePredicateIsStructuralNotANameList(unittest.TestCase):
    def test_a_wall_type_default_is_not_isolated(self) -> None:
        """When "Curtain Panel" is a WALL type, the cell is occupied by a
        wall-body: there is no arbitrary family code in the generation,
        nothing to isolate."""

        self.assertNotIn(PLAIN, K.curtain_hosts_needing_isolation(_index()))

    def test_an_unread_default_is_not_isolated(self) -> None:
        """Nothing is known about an unread panelization type — and we have
        no right to invent riskiness."""

        index = _index()
        index["curtain_index"][GRILLE_A]["default_panel_state"] = "not_captured"
        index["curtain_index"][GRILLE_A]["default_panel_type_id"] = None
        self.assertNotIn(GRILLE_A, K.curtain_hosts_needing_isolation(index))

    def test_the_predicate_reads_no_name(self) -> None:
        """INVARIANT #1: not a single measurement model name in the rule."""

        source = pathlib.Path(K.__file__).read_text(encoding="utf-8")
        start = source.index("def curtain_hosts_needing_isolation")
        end = source.index("def _isolation_from_artifacts", start)
        code = "\n".join(
            line for line in source[start:end].splitlines()
            if not line.lstrip().startswith("#"))
        body = code[code.index('"""', code.index('"""') + 3) + 3:]
        for token in ("ATR_", "НР_ВТ", "Вентрешетка", "Системная"):
            with self.subTest(token=token):
                self.assertNotIn(token, body)

    def test_an_empty_or_absent_index_isolates_nothing(self) -> None:
        self.assertEqual(K.curtain_hosts_needing_isolation(None), frozenset())
        self.assertEqual(K.curtain_hosts_needing_isolation({}), frozenset())
        self.assertEqual(
            K._isolation_from_artifacts(None, None), frozenset())

    def test_an_explicit_list_wins_over_the_artifact(self) -> None:
        self.assertEqual(
            K._isolation_from_artifacts("/nonexistent", ["A", "B"]),
            frozenset({"A", "B"}))


class TheHostGroupStaysWhole(unittest.TestCase):
    def test_a_cell_op_travels_with_its_isolated_host(self) -> None:
        """D5a: an attached op has no right to be left in another chunk —
        otherwise its ``ref`` will not resolve and the chunk will refuse
        entirely."""

        index = _index()
        # the grille host A gets a REPLACED cell
        index["curtain_index"][GRILLE_A]["panels"].append({
            "panel_id": "cell-A", "is_family_instance": True,
            "family_name": "Семейство панели", "type_name": "другой тип",
            "type_id": "999999", "host_panel_id": None,
            "host_panel_type_id": None, "host_panel_type_name": None,
            "u_index": 0, "v_index": 0, "address_state": "ok",
            "is_door": False,
        })
        document = _document()
        row = json.loads(json.dumps(document.to_dict(), ensure_ascii=False))
        cell = make_element("OST_CurtainWallPanels", 4242, ordinal=1)
        cell["element_id"] = "cell-A"
        cell["host_id"] = GRILLE_A
        cell["geom_kind"] = "bbox_only"
        cell["p0_mm"] = cell["p1_mm"] = None
        cell["bbox_min_mm"] = cell["bbox_max_mm"] = None
        cell["type_id"] = "999999"
        cell["type_name"] = "другой тип"
        row["elements"].append(cell)
        document = L0Document.from_dict(row)

        leaves = lift_document_detailed(
            document, curtain_index=index).nodes
        cell_ops = [n for n in leaves
                    if n.get("op_name") == "set_curtain_panel"]
        self.assertEqual(len(cell_ops), 1, "ячейка обязана подняться")

        result = leaves_to_program(
            leaves, chunk_target=250,
            solo_source_ids=K.curtain_hosts_needing_isolation(index))
        owning = [program for program in result.programs
                  if any(op["id"][1:] == GRILLE_A for op in program["ops"])]
        self.assertEqual(len(owning), 1)
        ids = [op["id"][1:] for op in owning[0]["ops"]]
        self.assertIn("cell-A", ids,
                      "ячейка уехала вместе с носителем, а не осталась одна")


if __name__ == "__main__":
    unittest.main()
