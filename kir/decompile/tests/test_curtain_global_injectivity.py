"""Global injectivity of panel_id ↔ host_panel_id (codex #4,
2026-07-29, tasks/b8f3v4r97.output of session eeccfb91).

``CurtainWallRecord.__post_init__`` already requires panel_id to be unique
WITHIN one host (``_require_unique``). But panel_id and host_panel_id live
in a SHARED, global identity space of the document — and the global side of
injectivity was not checked at all: ``_curtain_side_index`` built
``cells``/``bodies`` last-write, with no check whatsoever for collisions
between hosts or between the panel_id/host_panel_id roles.

The danger is NOT that last-write creates a duplicate sheet (there will not
be two ops — the body is intercepted by ``curtain_cell_bodies`` EARLIER
than the element reaches its own ``curtain_cells`` check, see
``_lift_one``). The danger is LOSS: if a body-id coincides with the REAL
panel_id of someone else's cell, that very earlier body guard intercepts a
foreign legitimate cell and permanently hides its own identity — it gets
generator_child, whatever its real status may be.

Four adversarial forms (codex verbatim): duplicate body, body = someone
else's panel_id, self-alias, a nested curtain-host. All four must ISOLATE
the affected hosts — their elements fall into the honest (non-curtain-
specific) path, rather than silently corrupting the graph.
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kir.decompile.curtain_extract import CURTAIN_INDEX_SCHEMA_VERSION
from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import _curtain_side_index, lift_document_detailed
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)

GLAZING_TYPE_ID = "7001"
WALL_BODY_TYPE_ID = "7002"


def _panel_row(panel_id: str, *, host_panel_id: str | None = None,
               u_index: int = 0, v_index: int = 0) -> dict[str, Any]:
    return {
        "panel_id": panel_id,
        "is_family_instance": True,
        "family_name": "Системная панель",
        "type_name": "Стеклопакет 30мм",
        "type_id": GLAZING_TYPE_ID,
        "host_panel_id": host_panel_id,
        "host_panel_type_id": WALL_BODY_TYPE_ID if host_panel_id else None,
        "host_panel_type_name": (
            "НР_ВТ_Сэндвич панель_30мм" if host_panel_id else None),
        "u_index": u_index,
        "v_index": v_index,
        "address_state": "ok",
        "is_door": False,
    }


def _host_row(panels: list[dict[str, Any]], *,
              default_panel_type_id: str = "9999") -> dict[str, Any]:
    return {
        "curtain_available": True,
        "host_kind": "wall",
        "default_panel_type_id": default_panel_type_id,
        "default_panel_type_name": "Системная панель по умолчанию",
        "default_panel_state": "ok",
        "default_panel_source": "AUTO_PANEL_WALL",
        "u_grid_lines": [],
        "v_grid_lines": [],
        "panels": panels,
        "mullions": [],
    }


def _envelope(hosts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": CURTAIN_INDEX_SCHEMA_VERSION,
        "curtain_index": hosts,
        "failures": [],
    }


class DirectInjectivityChecks(unittest.TestCase):
    """Direct check of ``_curtain_side_index`` — faster and more precise
    than the full ``lift_document_detailed``, suited for enumerating forms."""

    def test_clean_two_hosts_no_conflict(self) -> None:
        """Negative control: two hosts, different panel_id/
        host_panel_id — nothing gets isolated."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="B1")]),
            "H2": _host_row([_panel_row("P2", host_panel_id="B2")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertIn("P1", cells)
        self.assertIn("P2", cells)
        self.assertEqual(bodies.get("B1"), "P1")
        self.assertEqual(bodies.get("B2"), "P2")

    def test_duplicate_body_two_cells_claim_the_same_occupant(self) -> None:
        """Two DIFFERENT hosts, two cells claim the SAME occupant B1 —
        both hosts are isolated entirely, neither of the two cells
        takes part in cells/bodies via the short-path."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="B1")]),
            "H2": _host_row([_panel_row("P2", host_panel_id="B1")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertNotIn("P1", cells)
        self.assertNotIn("P2", cells)
        self.assertNotIn("B1", bodies)

    def test_body_equals_a_foreign_real_panel_id(self) -> None:
        """H1's cell P1 is occupied by B, but B is the REAL panel_id of
        cell P2 belonging to a foreign host H2. Both sides are isolated:
        without this, the earlier body-guard in _lift_one would hide the
        legitimate P2."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="P2")]),
            "H2": _host_row([_panel_row("P2")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertNotIn("P1", cells)
        self.assertNotIn("P2", cells, "чужая легитимная ячейка не должна пострадать МОЛЧА")
        self.assertNotIn("P2", bodies)

    def test_self_alias(self) -> None:
        """Cell P1, occupied "by itself" (host_panel_id == panel_id) —
        there is no physical meaning, the host is isolated."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="P1")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertNotIn("P1", cells)
        self.assertNotIn("P1", bodies)

    def test_nested_curtain_host_as_body(self) -> None:
        """The occupant of cell P1 of host H1 is host H2 ITSELF (its
        wall_id). Undefined territory — H1 is isolated, H2 as a
        standalone host is left untouched."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="H2")]),
            "H2": _host_row([_panel_row("P2")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertNotIn("P1", cells)
        self.assertNotIn("H2", bodies)
        # H2 on its own remains a CLEAN host — its own
        # cell P2 is unaffected, isolation does not spread beyond
        # the hosts REALLY involved.
        self.assertIn("P2", cells)

    def test_conflict_does_not_bleed_into_unrelated_hosts(self) -> None:
        """A third, completely unrelated host is not isolated from a
        foreign conflict — the block is not a global panic, but a
        targeted one."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="B1")]),
            "H2": _host_row([_panel_row("P2", host_panel_id="B1")]),
            "H3": _host_row([_panel_row("P3", host_panel_id="B3")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertNotIn("P1", cells)
        self.assertNotIn("P2", cells)
        self.assertIn("P3", cells)
        self.assertEqual(bodies.get("B3"), "P3")


def _wall(element_id: str, ordinal: int) -> dict[str, Any]:
    wall = make_element("OST_Walls", int(element_id), ordinal=ordinal)
    wall["element_id"] = element_id
    wall["type_name"] = "Витраж НР_ВТ"
    return wall


def _cell(element_id: str, host_id: str, ordinal: int) -> dict[str, Any]:
    cell = make_element("OST_CurtainWallPanels", int(element_id), ordinal=ordinal)
    cell["element_id"] = element_id
    cell["host_id"] = host_id
    cell["geom_kind"] = "bbox_only"
    cell["p0_mm"] = cell["p1_mm"] = None
    cell["bbox_min_mm"] = cell["bbox_max_mm"] = None
    cell["type_id"] = GLAZING_TYPE_ID
    cell["type_name"] = "Стеклопакет 30мм"
    return cell


def _body(element_id: str, ordinal: int) -> dict[str, Any]:
    body = make_element("OST_CurtainWallPanels", int(element_id), ordinal=ordinal)
    body["element_id"] = element_id
    body["host_id"] = None
    body["geom_kind"] = "curve"
    body["p0_mm"] = [0.0, 0.0, 0.0]
    body["p1_mm"] = [1500.0, 0.0, 0.0]
    body["type_id"] = WALL_BODY_TYPE_ID
    body["type_name"] = "НР_ВТ_Сэндвич панель_30мм"
    return body


def _lift(elements: list[dict[str, Any]], curtain_index: dict[str, Any]):
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "curtain-injectivity-v1"
    row["elements"] = elements
    row["category_status"] = []
    document = L0Document.from_dict(row)
    result = lift_document_detailed(document, curtain_index=curtain_index)
    return {node["source_element_id"]: node for node in result.nodes}


class EndToEndMultisetIsPreserved(unittest.TestCase):
    """The full ``lift_document_detailed``: proves not only the shape of
    cells/bodies, but also the REAL outcome — exactly one sheet per
    element, none lost, no foreign cell eaten by a body."""

    H1, P1, H2, P2, B1 = "9101", "9102", "9111", "9112", "9103"

    def test_duplicate_body_end_to_end_no_loss_no_double(self) -> None:
        """P1 (H1) and P2 (H2) both claim B1 as their occupant. All
        three elements must get EXACTLY one sheet each — isolation does
        not drop them from the multiset, it just removes the short-path."""
        elements = [
            _wall(self.H1, 0), _cell(self.P1, self.H1, 1),
            _wall(self.H2, 2), _cell(self.P2, self.H2, 3),
            _body(self.B1, 4),
        ]
        curtain_index = _envelope({
            self.H1: _host_row([_panel_row(self.P1, host_panel_id=self.B1)]),
            self.H2: _host_row([_panel_row(self.P2, host_panel_id=self.B1)]),
        })
        nodes = _lift(elements, curtain_index)
        source_ids = list(nodes.keys())
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertEqual(
            set(source_ids), {self.H1, self.P1, self.H2, self.P2, self.B1})
        # B1 itself is claimed by TWO different cells — neither of them
        # can be trusted, so B1 must not be silently assigned
        # generator_child by EITHER of them: both hosts are isolated,
        # B1 goes through the general placement path as a standalone element.
        b1 = nodes[self.B1]
        self.assertFalse(
            b1["kind"] == "atom"
            and b1.get("reason", {}).get("code")
            == AtomReason.GENERATOR_CHILD.value,
            f"B1 must not be silently assigned as generator_child of "
            f"either conflicting claimant: {b1}")

    def test_body_equals_foreign_panel_keeps_the_foreign_cell_alive(
            self) -> None:
        """P2 (H2) is a legitimate, addressed cell. P1 (H1) declares its
        ID as its own host_panel_id. WITHOUT the fix, P2 would become
        unreachable (the earlier body-guard would intercept it as the
        body of a foreign cell P1). WITH the fix, P2 remains a REAL cell
        (or an honest atom for its own reasons), but NOT a
        generator_child by someone else's reference."""
        elements = [
            _wall(self.H1, 0), _cell(self.P1, self.H1, 1),
            _wall(self.H2, 2), _cell(self.P2, self.H2, 3),
        ]
        curtain_index = _envelope({
            self.H1: _host_row([_panel_row(self.P1, host_panel_id=self.P2)]),
            self.H2: _host_row([_panel_row(self.P2)]),
        })
        nodes = _lift(elements, curtain_index)
        source_ids = list(nodes.keys())
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertEqual(set(source_ids), {self.H1, self.P1, self.H2, self.P2})
        p2 = nodes[self.P2]
        self.assertFalse(
            p2["kind"] == "atom"
            and p2.get("reason", {}).get("code")
            == AtomReason.GENERATOR_CHILD.value,
            f"P2 must not be silently suppressed as somebody else's body: {p2}")


if __name__ == "__main__":
    unittest.main()
