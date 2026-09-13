"""Capturing ceilings and railings by the ``sketch`` stage (wave/capture, 2026-07-29).

WHY THIS FILE EXISTS. On 29.07 ``create_ceiling`` and ``create_railing``
arrived in the registry — the gate went 6/6 green, and coverage did not
move on a single building. The reason is not in the operations, but in the
fact that there is NOTHING to lift: on a snapshot of working documentation
(13A-RD-AR-K2, 55,293 elements) all 81 ceilings sit as ``bbox_only`` with an
empty ``params``, all 203 railings are ``bbox_only``/``point``, and not one
of them occurs in either ``sketch.index.json`` or ``curve.index.json``. The
operation exists — there is no source data.

The tests below were written BEFORE the fix and failed red on it: they name
exactly the capture that did not exist. The order of assertions runs from
"does the stage even look at the category" to "an unreadable field comes
out as a typed refusal, not a default."

THE BOUNDARY THIS FILE DOES NOT CROSS. The railing placement position
(``RailingPlacementPosition``) is not checked here, because there is
NOTHING to capture it with: the full member set of
``Autodesk.Revit.DB.Architecture.Railing`` across all six versions is 20
members, and ``RailingPlacementPosition`` occurs ONLY as a parameter of two
``Create`` overloads and as three fields of its own enum. No getter exists.
So the ``_lift_railing`` refusal on position is legitimate and stays; it is
closed not by a capture, but by the fact that the path overload
``Railing.Create(doc, CurveLoop, typeId, baseLevelId)`` does not require a
position at all.
"""

from __future__ import annotations

import unittest

from kir.decompile.pipeline import _STAGE_CATEGORIES
from kir.decompile.sketch_extract import (
    SKETCH_EXTRACT_SCHEMA_VERSION,
    SketchPayloadError,
    build_sketch_extract_cs,
    extract_sketch_profiles,
)


def _loop(points: list[list[float]]) -> dict:
    count = len(points)
    return {
        "points_mm": points,
        "curve_kinds": ["line"] * count,
        "arc_midpoints_mm": [None] * count,
    }


RECTANGLE = _loop([[0, 0], [6000, 0], [6000, 4000], [0, 4000]])


def _element(
    element_id: str,
    *,
    category: str,
    loops: list[dict] | None = None,
    available: bool = False,
    reason: str | None = None,
    stairs_run_paths: list[dict] | None = None,
    railing: dict | None = None,
) -> dict:
    row: dict = {
        "element_id": element_id,
        "category": category,
        "profile_available": available,
        "loops": loops if loops is not None else [],
        "reason": reason,
        "stairs_run_paths": (
            stairs_run_paths if stairs_run_paths is not None else []),
    }
    if railing is not None:
        row["railing"] = railing
    return row


def _payload(*elements: dict) -> dict:
    return {
        "schema_version": SKETCH_EXTRACT_SCHEMA_VERSION,
        "elements": list(elements),
    }


#: Verbatim what the emitter writes: a row for an inaccessible profile MUST
#: carry a non-empty reason, and for a railing it is always the same one.
RAILING_NO_PROFILE = (
    "railing is a path element and has no closed Sketch profile")


def _railing_element(element_id: str, **kwargs) -> dict:
    return _element(
        element_id,
        category=kwargs.pop("category", "OST_StairsRailing"),
        reason=kwargs.pop("reason", RAILING_NO_PROFILE),
        **kwargs,
    )


def _railing(
    *,
    path_available: bool = True,
    points: list[list[float]] | None = None,
    plane_z_mm: float | None = 141380.0,
    path_reason: str | None = None,
    host_available: bool = True,
    has_host: bool | None = False,
    host_id: str | None = None,
    host_reason: str | None = None,
    base_available: bool = True,
    base_level_id: str | None = "11835839",
    base_reason: str | None = None,
) -> dict:
    pts = points if points is not None else [[0, 0], [4000, 0], [4000, 2500]]
    return {
        "path": {
            "available": path_available,
            "points_mm": pts if path_available else [],
            # An open chain: N points ⇒ N-1 curves.
            "curve_kinds": ["line"] * (len(pts) - 1) if path_available else [],
            "arc_midpoints_mm": (
                [None] * (len(pts) - 1) if path_available else []),
            "plane_z_mm": plane_z_mm if path_available else None,
            "reason": path_reason,
        },
        "host": {
            "available": host_available,
            "has_host": has_host if host_available else None,
            "host_id": host_id if host_available else None,
            "reason": host_reason,
        },
        "base_level": {
            "available": base_available,
            "level_id": base_level_id if base_available else None,
            "reason": base_reason,
        },
    }


class CeilingCaptureTests(unittest.TestCase):
    """A ceiling is the same sketch-based element as a floor and a roof."""

    def test_sketch_stage_selects_ceilings(self) -> None:
        # Without this row the pipeline will never send a ceiling's id to
        # the stage, and however correct the C# is, it will remain dead
        # code.
        self.assertIn("OST_Ceilings", _STAGE_CATEGORIES["sketch"])

    def test_emitter_collects_ceilings(self) -> None:
        body = build_sketch_extract_cs(["101"])
        self.assertIn("OST_Ceilings", body)
        # A ceiling must travel the SAME path as a floor: a single
        # dependent Sketch. A separate branch here would mean a second
        # truth about the profile.
        self.assertIn("__ProfileRow(__ceiling, \"OST_Ceilings\")", body)

    def test_parser_accepts_a_ceiling_profile(self) -> None:
        extraction = extract_sketch_profiles(_payload(_element(
            "15972657",
            category="OST_Ceilings",
            loops=[RECTANGLE],
            available=True,
        )))
        row = extraction.profile_index["15972657"]
        self.assertTrue(row["profile_available"])
        self.assertEqual(row["exterior_loop"], [
            [0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0],
        ])
        self.assertEqual(row["holes"], [])

    def test_ceiling_with_a_courtyard_keeps_the_hole(self) -> None:
        courtyard = _loop([
            [2000, 1000], [4000, 1000], [4000, 3000], [2000, 3000]])
        extraction = extract_sketch_profiles(_payload(_element(
            "15972658",
            category="OST_Ceilings",
            loops=[courtyard, RECTANGLE],
            available=True,
        )))
        row = extraction.profile_index["15972658"]
        self.assertEqual(len(row["holes"]), 1)

    def test_unreadable_ceiling_profile_is_a_named_refusal(self) -> None:
        # A silent loss is forbidden: an unread profile must name itself,
        # rather than pretend to be an empty outline.
        extraction = extract_sketch_profiles(_payload(_element(
            "15972659",
            category="OST_Ceilings",
            available=False,
            reason="dependent Sketch count is 0",
        )))
        row = extraction.profile_index["15972659"]
        self.assertFalse(row["profile_available"])
        self.assertTrue(any(
            "dependent Sketch count is 0" in failure.reason
            for failure in extraction.failures))


class RailingCaptureTests(unittest.TestCase):
    """Railing: the path is an open chain, the host and the base level are separate."""

    def test_sketch_stage_selects_railings(self) -> None:
        self.assertIn("OST_StairsRailing", _STAGE_CATEGORIES["sketch"])

    def test_emitter_collects_railings_via_getpath(self) -> None:
        body = build_sketch_extract_cs(["101"])
        self.assertIn("OST_StairsRailing", body)
        self.assertIn("GetPath()", body)
        # A railing's path is an OPEN chain. Close it, and the very first
        # straight staircase run becomes an "unclosed loop" and goes to
        # refusal.
        self.assertIn("__ReadChain(__railCurves, false)", body)

    def test_parser_keeps_an_open_railing_path(self) -> None:
        extraction = extract_sketch_profiles(_payload(_railing_element("11842713", railing=_railing())))
        record = extraction.railing_path_index["11842713"]
        self.assertTrue(record["path_available"])
        self.assertEqual(record["points_mm"], [
            [0.0, 0.0], [4000.0, 0.0], [4000.0, 2500.0]])
        self.assertEqual(record["curve_kinds"], ["line", "line"])

    def test_railing_path_keeps_its_elevation(self) -> None:
        # The chain is planar, but NOT at zero. Silently dropping Z would
        # mean laying the railing of a 59-story tower on the ground.
        extraction = extract_sketch_profiles(_payload(_railing_element(
            "11842713", railing=_railing(plane_z_mm=141380.0))))
        self.assertEqual(
            extraction.railing_path_index["11842713"]["plane_z_mm"], 141380.0)

    def test_railing_host_is_captured_separately_from_path(self) -> None:
        extraction = extract_sketch_profiles(_payload(_railing_element(
            "11842714", railing=_railing(has_host=True, host_id="777"))))
        record = extraction.railing_path_index["11842714"]
        self.assertTrue(record["has_host"])
        self.assertEqual(record["host_id"], "777")

    def test_railing_base_level_is_captured(self) -> None:
        extraction = extract_sketch_profiles(_payload(_railing_element(
            "11842715", railing=_railing(base_level_id="11835839"))))
        self.assertEqual(
            extraction.railing_path_index["11842715"]["base_level_id"],
            "11835839")

    def test_unreadable_path_refuses_and_does_not_default(self) -> None:
        extraction = extract_sketch_profiles(_payload(_railing_element(
            "11842716", railing=_railing(
                path_available=False,
                path_reason="Railing.GetPath failed: InapplicableDataException",
            ))))
        record = extraction.railing_path_index["11842716"]
        self.assertFalse(record["path_available"])
        self.assertEqual(record["points_mm"], [])
        self.assertTrue(any(
            "InapplicableDataException" in failure.reason
            for failure in extraction.failures))

    def test_each_optional_read_fails_on_its_own(self) -> None:
        # The host failed to be read — the path must still survive. A
        # single try around the whole element is exactly the bug that cost
        # rooms their point.
        extraction = extract_sketch_profiles(_payload(_railing_element(
            "11842717", railing=_railing(
                host_available=False,
                host_reason="Railing.HostId failed: InvalidOperationException",
            ))))
        record = extraction.railing_path_index["11842717"]
        self.assertTrue(record["path_available"])
        self.assertEqual(record["points_mm"], [
            [0.0, 0.0], [4000.0, 0.0], [4000.0, 2500.0]])
        self.assertIsNone(record["has_host"])
        self.assertTrue(any(
            "InvalidOperationException" in failure.reason
            for failure in extraction.failures))

    def test_unavailable_host_cannot_smuggle_a_value(self) -> None:
        broken = _railing()
        broken["host"] = {
            "available": False, "has_host": True, "host_id": "777",
            "reason": "unreadable",
        }
        with self.assertRaises(SketchPayloadError):
            extract_sketch_profiles(_payload(_railing_element("11842718", railing=broken)))

    def test_railing_cannot_claim_a_closed_profile(self) -> None:
        with self.assertRaises(SketchPayloadError):
            extract_sketch_profiles(_payload(_railing_element(
                "11842719", loops=[RECTANGLE], available=True,
                reason=None, railing=_railing())))


class FrozenFormatTests(unittest.TestCase):
    """The old dialect must be read exactly as before."""

    def test_floor_payload_without_the_new_field_still_parses(self) -> None:
        extraction = extract_sketch_profiles(_payload(_element(
            "101", category="OST_Floors", loops=[RECTANGLE], available=True)))
        self.assertTrue(extraction.profile_index["101"]["profile_available"])
        self.assertEqual(extraction.railing_path_index, {})

    def test_non_railing_cannot_carry_a_railing_block(self) -> None:
        with self.assertRaises(SketchPayloadError):
            extract_sketch_profiles(_payload(_element(
                "101", category="OST_Floors", loops=[RECTANGLE],
                available=True, railing=_railing())))

    def test_stage_category_prefix_is_untouched(self) -> None:
        # The resume format is frozen: append only to the end.
        # Floor/roof/staircase must remain in the stage.
        for category in ("OST_Floors", "OST_Roofs", "OST_Stairs"):
            self.assertIn(category, _STAGE_CATEGORIES["sketch"])


class TheRefusalActuallyDisappears(unittest.TestCase):
    """The wave's acceptance signal, carried through from the shape of the
    bridge's response all the way to the lift.

    The tests above check the capture piece by piece. This one is the only
    one that answers the task's question as a whole: if the bridge answers
    with exactly what OUR emitter prints, does the reason "no ceiling
    sketch profile" disappear? The intermediate links here are real: the
    same ``extract_sketch_profiles``, the same ``profile_index``, the same
    ``lift_document_detailed``.

    WHAT THIS TEST DOES NOT PROVE: that a live Revit will answer exactly
    this way. The wave had no live Revit; what is proved is that a
    response of this SHAPE passes all the way through, and that the C#
    that prints it compiles on six versions.
    """

    def _lift_with(self, payload: dict, category: str, element_id: str):
        import copy

        from kir.decompile.lift import lift_document_detailed
        from kir.decompile.schema import L0Document
        from kir.decompile.tests.fixtures_decompile import (
            make_element, project1_metadata)

        extraction = extract_sketch_profiles(payload)
        element = make_element(category, 4100, ordinal=0)
        element["element_id"] = element_id
        row = copy.deepcopy(project1_metadata())
        row["change_stamp"] = "capture-v1"
        row["elements"] = [element]
        row["category_status"] = []
        result = lift_document_detailed(
            L0Document.from_dict(row), extraction.profile_index)
        return {node["source_element_id"]: node
                for node in result.nodes}[element_id], extraction

    def test_a_captured_ceiling_stops_being_an_atom(self) -> None:
        # Exactly the row __ProfileRow prints for a ceiling, including the
        # slopes key (the emitter always writes it).
        emitted = {
            "element_id": "15972657",
            "category": "OST_Ceilings",
            "profile_available": True,
            "loops": [RECTANGLE],
            "slopes": None,
            "reason": None,
            "stairs_run_paths": [],
        }
        node, _ = self._lift_with(
            _payload(emitted), "OST_Ceilings", "15972657")
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_ceiling")
        self.assertEqual(len(node["params"]["outline"]), 4)

    def test_the_same_ceiling_without_capture_is_still_an_atom(self) -> None:
        # Control: without the capture the reason must stay in place,
        # otherwise the previous test would be proving something other than
        # what we think.
        node, _ = self._lift_with(
            _payload(), "OST_Ceilings", "15972657")
        self.assertEqual(node["kind"], "atom")

    def test_a_captured_railing_still_refuses_until_the_lift_reads_it(
            self) -> None:
        """THE WAVE'S HONEST BOUNDARY, recorded by a test, not only by a report.

        The railing path is now CAPTURED and sits in ``railing_path_index``.
        But ``_lift_railing`` does not read this index — it lives in
        ``lift.py``, owned by a neighboring wave, and it must not be touched
        here. So railings STILL DO NOT GET LIFTED, and claiming otherwise
        would be a lie. The test will record the exact day the lift learns
        how.
        """
        node, extraction = self._lift_with(
            _payload(_railing_element("11842713", railing=_railing())),
            "OST_StairsRailing", "11842713")
        # The capture happened…
        self.assertTrue(
            extraction.railing_path_index["11842713"]["path_available"])
        # …but the lift did not, and the reason still names the geometry.
        self.assertEqual(node["kind"], "atom")


if __name__ == "__main__":
    unittest.main()
