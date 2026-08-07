"""Parity of the pure-offline and live detailed-lift boundaries."""

from __future__ import annotations

import math
import tempfile
import unittest

from kukai.ir.decompile.annotation_extract import (
    AnnotationExtraction,
    TextNoteRecord,
)
from kukai.ir.decompile.curve_extract import (
    CurveExtraction,
    CurveKind,
    CurveRecord,
)
from kukai.ir.decompile.lift_cache import cached_lift_document_detailed
from kukai.ir.decompile.mep_system_extract import (
    MepSystemExtraction,
    MepSystemRecord,
)
from kukai.ir.decompile.orchestrator import decompile
from kukai.ir.decompile.recompile import ArcCurve
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)
from kukai.ir.decompile.tag_extract import TagExtraction, TagRecord


WALL_ID = "100"
TEXT_ID = "200"
TAG_ID = "300"
PIPE_ID = "400"
LEVEL_ID = "10"
RADIUS_MM = 8_000.0


def _element(
    element_id: str,
    category: str,
    *,
    type_id: str,
    type_name: str,
    geom_kind: GeometryKind = GeometryKind.BBOX_ONLY,
    p0_mm: tuple[float, float, float] | None = None,
    p1_mm: tuple[float, float, float] | None = None,
    params: dict[str, float] | None = None,
) -> L0Element:
    return L0Element(
        element_id=element_id,
        category=category,
        category_ru=category,
        type_id=type_id,
        type_name=type_name,
        level_id=LEVEL_ID if geom_kind is GeometryKind.CURVE else None,
        level_name="L1" if geom_kind is GeometryKind.CURVE else None,
        geom_kind=geom_kind,
        p0_mm=p0_mm,
        p1_mm=p1_mm,
        rotation_deg=None,
        bbox_min_mm=None,
        bbox_max_mm=None,
        host_id=None,
        params=params or {},
    )


def _document() -> L0Document:
    wall = _element(
        WALL_ID,
        "OST_Walls",
        type_id="wall-type",
        type_name="W200",
        geom_kind=GeometryKind.CURVE,
        p0_mm=(RADIUS_MM, 0.0, 0.0),
        p1_mm=(0.0, RADIUS_MM, 0.0),
        params={"WALL_USER_HEIGHT_PARAM": 3_000.0},
    )
    text = _element(
        TEXT_ID,
        "OST_TextNotes",
        type_id="text-type",
        type_name="Text 2.5 mm",
    )
    tag = _element(
        TAG_ID,
        "OST_WallTags",
        type_id="tag-type",
        type_name="Wall tag",
    )
    pipe = _element(
        PIPE_ID,
        "OST_PipeCurves",
        type_id="pipe-type",
        type_name="Pipe 100",
        geom_kind=GeometryKind.CURVE,
        p0_mm=(0.0, 0.0, 0.0),
        p1_mm=(5_000.0, 0.0, 0.0),
        params={"RBS_PIPE_DIAMETER_PARAM": 100.0},
    )
    return L0Document(
        doc_name="offline-live-lift-parity",
        revit_version="2024",
        units="mm",
        change_stamp="offline-live-lift-parity-v1",
        levels=(LevelInfo(LEVEL_ID, "L1", 0.0),),
        grids=(),
        rooms=(),
        project_info=ProjectInfo(),
        elements=(wall, text, tag, pipe),
    )


def _curve_index() -> CurveExtraction:
    return CurveExtraction(records=(CurveRecord(
        element_id=WALL_ID,
        curve_kind=CurveKind.ARC,
        category="OST_Walls",
        p0_mm=(RADIUS_MM, 0.0, 0.0),
        p1_mm=(0.0, RADIUS_MM, 0.0),
        arc=ArcCurve(
            center_mm=(0.0, 0.0, 0.0),
            radius_mm=RADIUS_MM,
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
            start_angle_rad=0.0,
            end_angle_rad=math.pi / 2.0,
        ),
        normal=(0.0, 0.0, 1.0),
    ),))


def _annotation_index() -> AnnotationExtraction:
    return AnnotationExtraction(text_notes=(TextNoteRecord(
        element_id=TEXT_ID,
        owner_view_id="view-1",
        owner_view_name="Plan L1",
        at_view_mm=(1_000.0, 2_000.0),
        content="Parity note",
        type_id="text-type",
        type_name="Text 2.5 mm",
    ),))


def _tag_index() -> TagExtraction:
    return TagExtraction(tags=(TagRecord(
        element_id=TAG_ID,
        owner_view_id="view-1",
        owner_view_name="Plan L1",
        at_view_mm=(1_500.0, 2_500.0),
        tagged_element_id=WALL_ID,
        tag_family="independent",
        leader=False,
        orientation="Horizontal",
        type_id="tag-type",
        type_name="Wall tag",
    ),))


def _mep_system_index() -> MepSystemExtraction:
    return MepSystemExtraction(systems=(MepSystemRecord(
        element_id=PIPE_ID,
        system_type_id="system-type",
        system_type_name="Domestic Cold Water",
    ),))


class OfflineLiveDetailedLiftParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = _document()
        self.side_indexes = {
            "wall_curve_index": _curve_index(),
            "annotation_index": _annotation_index(),
            "tag_index": _tag_index(),
            "mep_system_index": _mep_system_index(),
        }

    def test_same_document_and_side_indexes_produce_identical_l1(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir:
            live_lift = cached_lift_document_detailed(
                self.document,
                **self.side_indexes,
                enabled=True,
                cache_dir=cache_dir,
            )
        offline = decompile(
            self.document,
            **self.side_indexes,
        )

        self.assertEqual(offline.l1_nodes, live_lift.nodes)

    def test_parity_fixture_proves_all_four_side_indexes_reach_lift(self) -> None:
        result = decompile(self.document, **self.side_indexes)
        by_source = {
            node["source_element_id"]: node for node in result.l1_nodes
        }

        self.assertIn("arc", by_source[WALL_ID]["params"])
        self.assertEqual(by_source[TEXT_ID]["op_name"], "create_text")
        self.assertEqual(by_source[TAG_ID]["op_name"], "create_tag")
        self.assertEqual(
            by_source[PIPE_ID]["params"]["system_type"],
            {
                "by": "name",
                "value": "Domestic Cold Water",
                "_id": "system-type",
            },
        )


if __name__ == "__main__":
    unittest.main()
