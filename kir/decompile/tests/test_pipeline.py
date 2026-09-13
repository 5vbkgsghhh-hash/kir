"""Offline acceptance for the Wave A1 live-decompile orchestrator.

A ``FakePipelineBridge`` composes the shared ``FakeExtractBridge`` (metadata /
probe / category batch) with valid side-index payloads (curve / sketch /
curtain) keyed off the schema literal each builder embeds in its C#.  No Revit,
no network — the executor is a plain async callable.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from kir.decompile import pipeline as pipe
from kir.decompile.curve_extract import CURVE_EXTRACT_SCHEMA_VERSION
from kir.decompile.curtain_extract import CURTAIN_EXTRACT_SCHEMA_VERSION
from kir.decompile.family_placement_extract import (
    FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION,
)
from kir.decompile.group_extract import GROUP_EXTRACT_SCHEMA_VERSION
from kir.decompile.join_extract import JOIN_EXTRACT_SCHEMA_VERSION
from kir.decompile.geom_extract import GEOMETRY_EXTRACT_SCHEMA_VERSION
from kir.decompile.sketch_extract import SKETCH_EXTRACT_SCHEMA_VERSION
from kir.open_model import (
    OPEN_MODEL_PROFILE_SCHEMA_VERSION,
    required_grounding_pools,
)
from kir.decompile.tests.fixtures_decompile import (
    FakeExtractBridge,
    make_element,
    project1_metadata,
)


def _family_wire_row(element_id: str) -> dict[str, Any]:
    """One valid placement row in the shape the family emitter produces."""
    return {
        "element_id": element_id,
        "symbol_id": "800",
        "type_name": "Дверь 900",
        "family_name": "Одностворчатая",
        "placement_type": "OneLevelBasedHosted",
        "in_place": False,
        "mirrored": False,
        "hand_flipped": False,
        "facing_flipped": False,
        "super_component_id": None,
        "group_id": None,
        "host_id": "1001",
        "host_class": "Wall",
        "hand_orientation": [1, 0, 0],
        "facing_orientation": [0, 1, 0],
        "point_ft": [1, 2, 3],
        "rotation_rad": 0.0,
        "status": "ok",
    }


_ID_LITERAL = re.compile(r'"(-?[0-9]+)"')


def _requested_ids(code: str) -> list[str]:
    """The ids that the emitter wrote into its page — IN BOTH LITERAL FORMS.

    §18.2 made the side-stage contract checkable: the response must cover
    EVERY requested id with either a string or a receipt. As long as the fake bridge answered
    every request with an empty list, it was modeling exactly the stage that
    the law forbids — and so it is no longer fit to serve as the backdrop for
    the rest of the tests.

    🔴 EXTENDED ON 18.08, AND THIS WAS INSTRUMENT BLINDNESS, NOT AN OVERSIGHT OF ONE
    STAGE. The function promises "the ids the emitter wrote," but it read only ONE
    spelling — ``new string[]``. The census of emitters that day:

        new string[]        curve · curtain · sketch · family_placement · geom
        new List<string>    annotation · tag · dimension · mep_system · join

    Five stages out of ten were invisible, and nobody noticed, because
    for four of the five the categories (pipes, tags, dimensions, annotation) are
    absent from the mini-model — the stage simply never ran. The first stage
    whose categories ARE present in the mini-model immediately got
    ``side_stage_count_mismatch: requested 4, with neither string nor receipt 4``.

    The named defect of this tree: the instrument ASSERTS the phenomenon but READS
    a naming convention. The fix is to widen the reading, not to bend
    the stage to match the spelling: the same response to "the stage returned no strings" and
    "I could not parse its page" is exactly the silence that §18.2 was
    written against.
    """
    match = re.search(r"new (?:string\[\]|List<string>) \{([^}]*)\}", code)
    if match is None:
        return []
    return _ID_LITERAL.findall(match.group(1))


def _curve_payload(code: str) -> dict[str, Any]:
    """One honest string per requested id (without LocationCurve)."""
    return {
        "schema_version": CURVE_EXTRACT_SCHEMA_VERSION,
        "elements": [
            {
                "element_id": element_id, "status": "ok", "reason": None,
                "typed_reason": None, "elapsed_ms": None, "category": None,
                "curve_kind": "no_location_curve",
                "p0_mm": None, "p1_mm": None, "arc": None, "normal": None,
            }
            for element_id in _requested_ids(code)
        ],
    }


def _curtain_payload(code: str) -> dict[str, Any]:
    """Every requested wall is not a curtain wall; this is a fact, and it is named."""
    return {
        "schema_version": CURTAIN_EXTRACT_SCHEMA_VERSION,
        "walls": [
            {
                "wall_id": element_id, "status": "not_curtain",
                "reason": None, "typed_reason": None, "elapsed_ms": None,
                "host_kind": "wall",
                "default_panel_type_id": None,
                "default_panel_type_name": None,
                "default_panel_state": "not_captured",
                "default_panel_source": None,
                "auto_mullion_types": {"slots": {}, "state": "not_captured"},
                "grid_layout": {"slots": {}, "state": "not_captured"},
                "u_grid_lines": [], "v_grid_lines": [],
                "panels": [], "mullions": [],
            }
            for element_id in _requested_ids(code)
        ],
    }


def _sketch_payload(code: str) -> dict[str, Any]:
    """One inaccessible profile string per requested id."""
    return {
        "schema_version": SKETCH_EXTRACT_SCHEMA_VERSION,
        "elements": [
            {
                "element_id": element_id, "category": "OST_Floors",
                "profile_available": False, "loops": [], "slopes": None,
                "reason": "profile unavailable (fake bridge)",
                "stairs_run_paths": [],
            }
            for element_id in _requested_ids(code)
        ],
        "failures": [],
    }


def _join_payload(code: str) -> dict[str, Any]:
    """The joins-stage response — ONE STRING PER requested id.

    🔴 THIS FUNCTION WAS BOUGHT BY A FALSE MEASUREMENT, and that is why it is here rather than a raised
    budget. As long as the stage mock did not know, the request fell into the general extraction branch,
    the response was not parsed, and `_side_or_resume` went into a retry with a timeout:
    ``stage_ms['join'] = 25 626.7`` against 200–1 000 ms for its neighbors. A live measurement on the
    owner's tower (Revit 2023, `13A-RD-AR-K2_v33`, 18.08.2026) gave
    **332 ms for 200 ids** — a **77-fold** discrepancy, and it was entirely
    a property of the MOCK, not of the stage.

    Raising the ceiling would have been cheaper and would have made the next real
    regression of the stage invisible: a silent mock is an instrument that answers the same to
    "slow" and to "we did not ask."

    An empty `joined_to` here is NOT a stub but a working case: the mini-model joins
    nothing, and the stage must return this as a STRING. A receipt would mean
    "we did not look" — a different statement.
    """
    return {
        "schema_version": JOIN_EXTRACT_SCHEMA_VERSION,
        "elements": [
            # The third kind is fed TOO, otherwise the pipeline path never touches it
            # at all, and "the stage is green" would mean "two kinds out of three are green."
            # One end is read and empty, the other is NOT read for a named
            # reason: the mock must be able to show both halves of the distinction
            # for which the kind was introduced.
            {"element_id": element_id, "joined_to": [],
             "elements_at_end_join": [
                 {"read": True, "elements": []},
                 {"read": False, "why": "fake bridge does not model ends"}]}
            for element_id in _requested_ids(code)
        ],
        "failures": [],
    }


def _geometry_payload_for_code(
    code: str,
    elements: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Account for every requested atom without inventing fake geometry."""

    categories = {
        str(element["element_id"]): category
        for category, rows in elements.items()
        for element in rows
    }
    return {
        "schema_version": GEOMETRY_EXTRACT_SCHEMA_VERSION,
        "elements": [
            {
                "element_id": element_id,
                "category": (
                    categories.get(element_id, "")
                    if categories.get(element_id, "").startswith("OST_")
                    else "OST_GenericModel"
                ),
                "status": "empty",
                "parts": [],
                "errors": [],
            }
            for element_id in _requested_ids(code)
        ],
    }


def _mini_elements() -> dict[str, list[dict[str, Any]]]:
    """A 5-element mini model: two walls, a floor, a door, a column."""
    return {
        "OST_Walls": [
            make_element("OST_Walls", 1001, ordinal=0),
            make_element("OST_Walls", 1002, ordinal=1),
        ],
        "OST_Floors": [make_element("OST_Floors", 2001, ordinal=0)],
        "OST_Doors": [make_element("OST_Doors", 3001, ordinal=0)],
        "OST_Columns": [make_element("OST_Columns", 4001, ordinal=0)],
    }


def _mini_metadata() -> dict[str, Any]:
    meta = copy.deepcopy(project1_metadata())
    meta["doc_name"] = "pipeline-mini"
    meta["change_stamp"] = "pipeline-mini-v1"
    return meta


def _open_model_snapshot(
    metadata: dict[str, Any],
    elements: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Synthetic exact profile for the already-open mini document."""

    snapshot: dict[str, Any] = {
        pool: [] for pool in required_grounding_pools()}

    def add(pool: str, row: dict[str, Any]) -> None:
        if any(existing["id"] == row["id"] for existing in snapshot[pool]):
            return
        snapshot[pool].append(row)

    for level in metadata.get("levels", []):
        element_id = int(level["id"])
        add("levels", {
            "id": element_id,
            "name": level["name"],
            "unique_id": f"level:uid:{element_id}",
            "version_guid": f"{element_id:032x}",
            "class_name": "Autodesk.Revit.DB.Level",
            "category": "OST_Levels",
        })
    for grid in metadata.get("grids", []):
        element_id = int(grid["id"])
        add("grids", {
            "id": element_id,
            "name": grid["name"],
            "unique_id": f"grid:uid:{element_id}",
            "version_guid": f"{element_id:032x}",
            "class_name": "Autodesk.Revit.DB.Grid",
            "category": "OST_Grids",
            "p0_mm": grid["p0_mm"][:2],
            "p1_mm": grid["p1_mm"][:2],
        })

    category_pools = {
        "OST_Walls": ("wall_types",),
        "OST_Floors": ("floor_types",),
        "OST_Roofs": ("roof_types",),
        "OST_PipeCurves": ("pipe_types",),
        "OST_DuctCurves": ("duct_types",),
        "OST_CableTray": ("cable_tray_types",),
        "OST_Columns": (
            "column_symbols_architectural", "family_symbols"),
        "OST_StructuralColumns": (
            "column_symbols_structural", "family_symbols"),
        "OST_Doors": ("door_symbols", "family_symbols"),
        "OST_Windows": ("window_symbols", "family_symbols"),
        "OST_StructuralFraming": ("beam_types", "family_symbols"),
        "OST_StructuralFoundation": (
            "foundation_symbols", "family_symbols"),
        "OST_Furniture": ("family_symbols",),
        "OST_GenericModel": ("family_symbols",),
    }
    for category, rows in elements.items():
        for element in rows:
            raw_type_id = element.get("type_id")
            if raw_type_id in (None, ""):
                continue
            type_id = int(raw_type_id)
            entry = {
                "id": type_id,
                "name": element.get("type_name", ""),
                "unique_id": f"type:uid:{type_id}",
                "version_guid": f"{type_id:032x}",
                "class_name": "Autodesk.Revit.DB.ElementType",
                "category": category,
            }
            for pool in category_pools.get(category, ()):
                add(pool, copy.deepcopy(entry))

    for pool in required_grounding_pools():
        snapshot[pool].sort(key=lambda row: row["id"])
        snapshot[pool + "__total"] = len(snapshot[pool])
    snapshot.update({
        "__profile_schema_version": OPEN_MODEL_PROFILE_SCHEMA_VERSION,
        "__profile_required_pools": list(required_grounding_pools()),
        "__document_fingerprint": {
            "title": metadata["doc_name"],
            "path_name": "",
            "project_uid": f"synthetic:{metadata['doc_name']}",
        },
        "__revit_version": metadata["revit_version"],
        "__revit_build": "synthetic-build",
    })
    return snapshot


class FakePipelineBridge:
    """Extend ``FakeExtractBridge`` with valid side-index payloads."""

    def __init__(
        self,
        *,
        elements: dict[str, list[dict[str, Any]]] | None = None,
        metadata: dict[str, Any] | None = None,
        edit_after_stage: str | None = None,
        crash_batch_for: str | None = None,
        timeout_probe_for: str | None = None,
        link_title: str | None = None,
    ) -> None:
        self._elements = elements or _mini_elements()
        self.link_title = link_title
        self._extract = FakeExtractBridge(
            metadata=metadata or _mini_metadata(),
            elements=self._elements,
            crash_batch_for=crash_batch_for,
            timeout_probe_for=timeout_probe_for,
            link_title=link_title,
        )
        self.edit_after_stage = edit_after_stage
        self.side_calls: list[str] = []
        self._edited = False
        self.revision = "5:synthetic-revision-a:synthetic-revision-b"

    async def __call__(self, code: str, *, timeout_ms: int) -> dict[str, Any]:
        before = self.revision
        result = await self._dispatch(code, timeout_ms=timeout_ms)
        if pipe._REVISION_GUARD_MARKER in code:
            payload = result.get("result", result)
            return {"ok": True, "result": {
                "revision_before": before,
                "revision_after": self.revision,
                "payload": payload,
            }}
        return result

    async def _dispatch(self, code: str, *, timeout_ms: int) -> dict[str, Any]:
        # Side-index bodies carry their schema literal; dispatch on it first.
        if OPEN_MODEL_PROFILE_SCHEMA_VERSION in code:
            self.side_calls.append("open_model_profile")
            return {"ok": True, "result": _open_model_snapshot(
                self._extract.metadata_payload, self._elements)}
        if CURVE_EXTRACT_SCHEMA_VERSION in code:
            self.side_calls.append("curve")
            return {"ok": True, "result": _curve_payload(code)}
        if CURTAIN_EXTRACT_SCHEMA_VERSION in code:
            self.side_calls.append("curtain")
            return {"ok": True, "result": _curtain_payload(code)}
        if SKETCH_EXTRACT_SCHEMA_VERSION in code:
            self.side_calls.append("sketch")
            return {"ok": True, "result": _sketch_payload(code)}
        if FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION in code:
            self.side_calls.append("family_placement")
            # One valid ok-row per requested door/column id that the emitter
            # embedded as a string literal in the C# body (fail-closed shape:
            # only fully-read placements are emitted).  §18.2: every OTHER
            # requested id leaves a typed receipt — the fake bridge honours the
            # same contract the live emitter does.
            known = {"3001", "4001"}
            requested = _requested_ids(code)
            placements = [
                _family_wire_row(element_id)
                for element_id in requested if element_id in known
            ]
            failures = [
                {"element_id": element_id,
                 "reason": "not a FamilyInstance (fake bridge)",
                 "typed_reason": "element_kind_mismatch",
                 "elapsed_ms": None}
                for element_id in requested if element_id not in known
            ]
            return {"ok": True, "result": {
                "schema_version": FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION,
                "placements": placements, "failures": failures}}
        if GROUP_EXTRACT_SCHEMA_VERSION in code:
            self.side_calls.append("group")
            # Whole-model collector: the mini model has no groups, so an empty
            # (but valid) group payload.
            return {"ok": True, "result": {
                "schema_version": GROUP_EXTRACT_SCHEMA_VERSION,
                "groups": [], "failures": []}}
        if JOIN_EXTRACT_SCHEMA_VERSION in code:
            self.side_calls.append("join")
            return {"ok": True, "result": _join_payload(code)}
        if GEOMETRY_EXTRACT_SCHEMA_VERSION in code:
            self.side_calls.append("geometry")
            return {"ok": True, "result": _geometry_payload_for_code(
                code, self._elements)}
        # Everything else is an extract-phase body (metadata/probe/batch).  The
        # optional mid-run edit mutates the probe fingerprint to simulate a
        # concurrent model edit for the probe-divergence test.
        result = await self._extract(code, timeout_ms=timeout_ms)
        return result


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class PipelineHappyPathTests(unittest.TestCase):
    def test_full_run_reaches_passport_and_persists_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            bridge = FakePipelineBridge()
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            self.assertEqual(result.elements_total, 5)
            out = Path(tmp)
            for name in ("L0.jsonl", "curve.index.json", "sketch.index.json",
                         "curtain.index.json", "verify.json", "passport.json",
                         "passport.md", "tree.json", "run.json", "status.json",
                         "revision.proof.json", "open_model.profile.json",
                         "geometry.bundle.json", "geometry.proof.json"):
                self.assertTrue((out / name).is_file(), f"missing {name}")
            profile = json.loads(
                (out / "open_model.profile.json").read_text("utf-8"))
            self.assertTrue(profile["authoritative"])
            self.assertEqual(
                profile["revision_proof"]["change_stamp"],
                "pipeline-mini-v1")
            passport = json.loads((out / "passport.json").read_text("utf-8"))
            self.assertEqual(passport["doc_name"], "pipeline-mini")
            self.assertIn("geometry", passport)
            status = json.loads((out / "status.json").read_text("utf-8"))
            self.assertEqual(status["stage"], "done")
            # Lift cache directory was populated (cached_lift enabled).
            self.assertTrue((out / "lift_cache").is_dir())

    def test_geometry_stage_requests_only_non_generated_atoms(self) -> None:
        with TemporaryDirectory() as tmp:
            bridge = FakePipelineBridge()
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())

            named = json.loads(
                (Path(tmp) / "named.json").read_text("utf-8"))

            def walk(value: Any):
                if isinstance(value, dict):
                    yield value
                    for child in value.values():
                        yield from walk(child)
                elif isinstance(value, list):
                    for child in value:
                        yield from walk(child)

            expected = {
                source_id
                for node in walk(named)
                if node.get("kind") == "atom"
                and (node.get("reason") or {}).get("code")
                != "generator_child"
                and isinstance(
                    (source_id := node.get("source_element_id")), str)
            }
            bundle = json.loads(
                (Path(tmp) / "geometry.bundle.json").read_text("utf-8"))
            self.assertEqual(set(bundle["geometry_index"]), expected)
            proof = json.loads(
                (Path(tmp) / "geometry.proof.json").read_text("utf-8"))
            self.assertEqual(proof["atom_count"], len(expected))
            self.assertEqual(
                proof["geometry_bundle_sha256"],
                hashlib.sha256(
                    (Path(tmp) / "geometry.bundle.json").read_bytes()
                ).hexdigest(),
            )
            revision = json.loads(
                (Path(tmp) / "revision.proof.json").read_text("utf-8"))
            self.assertEqual(
                proof["revision_fingerprint"], revision["fingerprint"])
            self.assertEqual(
                bridge.side_calls.count("geometry"),
                0 if not expected else (len(expected) + pipe._SIDE_BATCH - 1)
                // pipe._SIDE_BATCH,
            )
            manifest = json.loads(
                (Path(tmp) / pipe._SIDE_MANIFEST_NAME).read_text("utf-8"))
            self.assertEqual(
                manifest["stages"]["geometry"]["requested_ids_count"],
                len(expected),
            )

    def test_live_tier_g_geometry_reaches_the_passport(self) -> None:
        class _GeometryBridge(FakePipelineBridge):
            async def _dispatch(self, code: str, *, timeout_ms: int) -> Any:
                if GEOMETRY_EXTRACT_SCHEMA_VERSION in code:
                    self.side_calls.append("geometry")
                    requested = _requested_ids(code)
                    categories = {
                        str(element["element_id"]): category
                        for category, rows in self._elements.items()
                        for element in rows
                    }
                    elements = []
                    for index, element_id in enumerate(requested):
                        category = categories[element_id]
                        if index == 0:
                            elements.append({
                                "element_id": element_id,
                                "category": category,
                                "status": "ok",
                                "parts": [{
                                    "geometry": {
                                        "tier": "Gm",
                                        "vertices_mm": [
                                            [0.0, 0.0, 0.0],
                                            [1000.0, 0.0, 0.0],
                                            [0.0, 1000.0, 0.0],
                                        ],
                                        "triangles": [[0, 1, 2]],
                                    },
                                    "transform": [
                                        1.0, 0.0, 0.0, 0.0,
                                        0.0, 1.0, 0.0, 0.0,
                                        0.0, 0.0, 1.0, 0.0,
                                        0.0, 0.0, 0.0, 1.0,
                                    ],
                                    "gb_error": None,
                                }],
                                "errors": [],
                            })
                        else:
                            elements.append({
                                "element_id": element_id,
                                "category": category,
                                "status": "empty",
                                "parts": [],
                                "errors": [],
                            })
                    return {"ok": True, "result": {
                        "schema_version": GEOMETRY_EXTRACT_SCHEMA_VERSION,
                        "elements": elements,
                    }}
                return await super()._dispatch(code, timeout_ms=timeout_ms)

        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                _GeometryBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            bundle = json.loads(
                (Path(tmp) / "geometry.bundle.json").read_text("utf-8"))
            passport = json.loads(
                (Path(tmp) / "passport.json").read_text("utf-8"))

            tier_g = {
                element_id: row for element_id, row
                in bundle["geometry_index"].items()
                if row["tier"] == "Gm"
            }
            self.assertEqual(len(tier_g), 1)
            self.assertEqual(
                passport["geometry"]["geometry_index"],
                bundle["geometry_index"],
            )
            self.assertEqual(len(passport["geometry"]["geometry_store"]), 1)
            self.assertEqual(len(passport["geometry"]["nodes"]), 1)

    def test_extract_stage_reports_itself_while_it_runs(self) -> None:
        """The read stage must be visible FROM OUTSIDE while it is running.

        Live measurement on 30.07: the read ran for 41 minutes, L0 grew to 88 MB, and
        status.json said `stage=open_model_profile, done 0/0` the whole time.
        A run that cannot be asked "is it alive" differs from one that has hung
        only by the asker's faith.
        """
        seen: list[dict] = []
        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1", status_cb=seen.append))
            self.assertTrue(result.ok, msg=result.to_dict())

        extract_reports = [s for s in seen if s["stage"] == "extract"]
        self.assertTrue(extract_reports, "стадия чтения не назвала себя ни разу")
        # A report carrying the elements already accumulated must exist — otherwise from outside
        # all that is visible is "started," which was exactly the defect.
        self.assertTrue(
            any(s["elements_total"] > 0 and s["done"] > 0
                for s in extract_reports),
            "ни один доклад чтения не нёс прогресса")
        # The counter of progress does not step backward.
        done = [s["done"] for s in extract_reports]
        self.assertEqual(done, sorted(done))
        # And by the end of the stage it reaches the full category table.
        self.assertEqual(extract_reports[-1]["done"],
                         extract_reports[-1]["total"])

    def test_family_and_group_stages_run_and_persist_with_default_builders(
            self) -> None:
        # Wave A1b: family_placement/group builders ship by default, so these
        # stages now run (no more skipped_no_builder) and persist their index.
        with TemporaryDirectory() as tmp:
            bridge = FakePipelineBridge()
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            self.assertIn("family_placement", bridge.side_calls)
            self.assertIn("group", bridge.side_calls)
            out = Path(tmp)
            self.assertTrue(
                # raw on purpose: asserts that the stage produced RAW
                (out / "family_placement.index.json").is_file())
            # raw on purpose: asserts that the stage produced RAW
            self.assertTrue((out / "group.index.json").is_file())
            status = json.loads((out / "status.json").read_text("utf-8"))
            self.assertNotIn("skipped_no_builder", " ".join(status["errors"]))
            # The door placement round-tripped through the REAL parser into the
            # persisted index (a hosted family with a host_class).
            family_index = json.loads(
                (out / "family_placement.index.json").read_text("utf-8"))
            door = family_index["family_placement_index"]["3001"]
            self.assertEqual(door["host_class"], "Wall")
            self.assertEqual(door["placement_type"], "OneLevelBasedHosted")

    def test_family_stage_skips_when_builder_explicitly_absent(self) -> None:
        # The honest skip path still works when a builder is genuinely absent.
        # Monkeypatch the default-builder factory to drop the family builder,
        # proving the skipped_no_builder note is emitted (not a crash).
        original = pipe._default_cs_builders

        def _no_family(*args, **kwargs) -> dict:
            # The substitute must accept the SAME arguments as the real
            # factory: since 30.07 the pipeline reports to it the SOURCE (host or
            # link), and a substitute that silently swallows it would bring back builders
            # reading someone else's document.
            builders = dict(original(*args, **kwargs))
            builders.pop("family_placement", None)
            return builders

        with TemporaryDirectory() as tmp:
            pipe._default_cs_builders = _no_family  # type: ignore[assignment]
            try:
                result = _run(pipe.run_decompile(
                    FakePipelineBridge(), out_dir=tmp,
                    change_stamp="pipeline-mini-v1"))
            finally:
                pipe._default_cs_builders = original  # type: ignore[assignment]
            self.assertTrue(result.ok, msg=result.to_dict())
            self.assertFalse(
                # raw on purpose: asserts that the stage produced RAW
                (Path(tmp) / "family_placement.index.json").exists())
            status = json.loads((Path(tmp) / "status.json").read_text("utf-8"))
            self.assertIn("skipped_no_builder", " ".join(status["errors"]))

    def test_partial_l0_is_persisted_but_blocked_before_lift(self) -> None:
        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                FakePipelineBridge(timeout_probe_for="OST_Roofs"),
                out_dir=tmp, change_stamp="pipeline-mini-v1"))

            self.assertFalse(result.ok)
            self.assertEqual(
                result.error["code"], "snapshot_non_authoritative")
            # raw on purpose: asserts that the stage produced RAW
            self.assertTrue((Path(tmp) / "L0.jsonl").is_file())
            from kir.decompile.snapshot_io import snapshot_file_exists
            # STRICTER than bare `exists`: it asserts that the tree does not exist EITHER RAW
            # or compressed — otherwise a `.gz` alongside it would pass for "did not produce."
            self.assertFalse(snapshot_file_exists(Path(tmp) / "tree.json"))


class PipelineWholeModelBatchingTests(unittest.TestCase):
    """Regression (live 2026-07-21, "demo" 40 floors) + §18.2/M9.

    Previously ``sketch`` was whole-model: its collector ignored the page and
    read the entire document, so paging through ``_SIDE_BATCH`` re-read everything
    from scratch on every batch, and ``_merge_profiles`` glued identical records into
    a duplicate element_id — the stage failed on the very first building with >200 floors.
    This was fixed by NOT paging the stage (one call per model), and in exchange
    we got the only side reader with no budget: three whole-model
    passes within a single 30-second call at ``retries=0``.

    The §18.2 wave lifted the compromise from the other end: the collector takes a page
    of ids and reads ONLY those. A duplicate became impossible by construction
    (batches do not overlap), and budget and receipts appeared in the same place as
    they exist for curve/curtain. The invariant the pin protects therefore changed:
    not "exactly one call," but "no duplicate while paging."
    """

    def test_paged_sketch_never_duplicates_an_element(self) -> None:
        # 201 floors > _SIDE_BATCH(200): two batches, non-overlapping.
        floors = [make_element("OST_Floors", 2000 + i, ordinal=i)
                  for i in range(pipe._SIDE_BATCH + 1)]
        elements = {
            "OST_Walls": [make_element("OST_Walls", 1001, ordinal=0)],
            "OST_Floors": floors,
        }

        class _SketchRecordBridge(FakePipelineBridge):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.sketch_pages: list[list[str]] = []

            async def _dispatch(self, code: str, *, timeout_ms: int) -> Any:
                if SKETCH_EXTRACT_SCHEMA_VERSION in code:
                    self.side_calls.append("sketch")
                    self.sketch_pages.append(_requested_ids(code))
                    return {"ok": True, "result": _sketch_payload(code)}
                return await super()._dispatch(code, timeout_ms=timeout_ms)

        with TemporaryDirectory() as tmp:
            bridge = _SketchRecordBridge(
                elements=elements, metadata=_mini_metadata())
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="whole-model-batch-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            self.assertEqual(bridge.side_calls.count("sketch"), 2)
            seen = [eid for page in bridge.sketch_pages for eid in page]
            self.assertEqual(len(seen), len(set(seen)),
                             "paged sketch must not re-request an element")
            index = json.loads(
                (Path(tmp) / "sketch.index.json").read_text("utf-8"))
            self.assertEqual(
                len(index["profile_index"]), pipe._SIDE_BATCH + 1)


class PipelineResumeTests(unittest.TestCase):
    def test_resume_reuses_side_artifacts_and_completes(self) -> None:
        with TemporaryDirectory() as tmp:
            # First full run.
            _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            # Second run: a bridge that REFUSES any side call — proving the
            # curve/sketch/curtain artifacts are reused from disk on resume.
            class _NoSideBridge(FakePipelineBridge):
                async def _dispatch(self, code: str, *, timeout_ms: int) -> Any:
                    for marker in (CURVE_EXTRACT_SCHEMA_VERSION,
                                   CURTAIN_EXTRACT_SCHEMA_VERSION,
                                   SKETCH_EXTRACT_SCHEMA_VERSION,
                                   GEOMETRY_EXTRACT_SCHEMA_VERSION):
                        if marker in code:
                            raise AssertionError(
                                "side stage recomputed instead of resumed")
                    return await super()._dispatch(
                        code, timeout_ms=timeout_ms)

            result = _run(pipe.run_decompile(
                _NoSideBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())

    def test_resume_after_extract_crash_completes(self) -> None:
        with TemporaryDirectory() as tmp:
            # A hard crash mid-extract (BaseException — models an abrupt process
            # kill that bypasses the retry budget).  The extract checkpoint must
            # survive so a fresh run resumes from it.
            crashed = FakePipelineBridge(crash_batch_for="OST_Walls")
            from kir.decompile.tests.fixtures_decompile import (
                SyntheticBridgeCrash,
            )
            with self.assertRaises(SyntheticBridgeCrash):
                _run(pipe.run_decompile(
                    crashed, out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertTrue((Path(tmp) / "L0.checkpoint.json").is_file())
            # Fresh healthy bridge resumes from the checkpoint to completion.
            second = _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertTrue(second.ok, msg=second.to_dict())

    def test_geometry_resume_is_bound_to_the_exact_atom_request(self) -> None:
        with TemporaryDirectory() as tmp:
            first = _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertTrue(first.ok, msg=first.to_dict())
            manifest_path = Path(tmp) / pipe._SIDE_MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text("utf-8"))
            manifest["stages"]["geometry"]["requested_ids_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            bridge = FakePipelineBridge()
            resumed = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-mini-v1"))

            self.assertTrue(resumed.ok, msg=resumed.to_dict())
            self.assertIn("geometry", bridge.side_calls)


class PipelineProbeTests(unittest.TestCase):
    def test_probe_divergence_retries_then_refuses(self) -> None:
        # Extract runs cleanly (walls land in L0); then the OST_Walls probe
        # fingerprint keeps shifting during the curve stage — modelling a
        # document edited mid-run.  Д2: one retry, then a typed refusal.
        from kir.decompile.extract import build_category_probe_cs
        wall_probe = build_category_probe_cs("OST_Walls")

        class _ShiftingProbeBridge(FakePipelineBridge):
            def __init__(self) -> None:
                super().__init__()
                self._wall_probes = 0

            async def _dispatch(self, code: str, *, timeout_ms: int) -> Any:
                if CURVE_EXTRACT_SCHEMA_VERSION in code:
                    return {"ok": True, "result": _curve_payload(code)}
                if SKETCH_EXTRACT_SCHEMA_VERSION in code:
                    return {"ok": True, "result": _sketch_payload(code)}
                if CURTAIN_EXTRACT_SCHEMA_VERSION in code:
                    return {"ok": True, "result": _curtain_payload(code)}
                result = await super()._dispatch(
                    code, timeout_ms=timeout_ms)
                if wall_probe in code:
                    self._wall_probes += 1
                    # Leave the FIRST probe (extract's own) untouched; shift
                    # every later probe so the curve stage's before != after.
                    if self._wall_probes > 1:
                        payload = result.get("result", {})
                        if isinstance(payload, dict):
                            payload["count"] = 100 + self._wall_probes
                return result

        with TemporaryDirectory() as tmp:
            bridge = _ShiftingProbeBridge()
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertFalse(result.ok)
            self.assertEqual(result.error["code"],
                             "model_edited_during_decompile")

    def test_same_count_geometry_edit_is_caught_by_revision_guard(self) -> None:
        """F4: count/level probes alone cannot see a geometry-only edit."""

        class _SameCountEditBridge(FakePipelineBridge):
            def __init__(self) -> None:
                super().__init__()
                self._changed = False

            async def _dispatch(self, code: str, *, timeout_ms: int) -> Any:
                result = await super()._dispatch(code, timeout_ms=timeout_ms)
                if (not self._changed
                        and 'string __Category = "OST_Walls";' in code):
                    # Element population and level distribution stay exactly
                    # the same; only the revision witness changes.
                    self._changed = True
                    self.revision = (
                        "5:synthetic-revision-after-edit:second-stream")
                return result

        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                _SameCountEditBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertFalse(result.ok)
            self.assertEqual(
                result.error["code"], "model_edited_during_decompile")
            from kir.decompile.snapshot_io import snapshot_file_exists
            self.assertFalse(snapshot_file_exists(Path(tmp) / "tree.json"))

    def test_resume_refuses_committed_l0_without_revision_proof(self) -> None:
        with TemporaryDirectory() as tmp:
            first = _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertTrue(first.ok, msg=first.to_dict())
            (Path(tmp) / "revision.proof.json").unlink()

            resumed = _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertFalse(resumed.ok)
            self.assertEqual(
                resumed.error["code"], "revision_proof_missing")


class PipelineCancelTests(unittest.TestCase):
    def test_cancel_between_batches_stops_cleanly(self) -> None:
        # Set the cancel flag as soon as the extract stage finishes so the
        # first side stage observes it between batches.
        class _CancelBridge(FakePipelineBridge):
            def __init__(self, out_dir: str) -> None:
                super().__init__()
                self._out = out_dir

            async def _dispatch(self, code: str, *, timeout_ms: int) -> Any:
                if CURVE_EXTRACT_SCHEMA_VERSION in code:
                    pipe.request_cancel(self._out)  # cancel mid side-stage
                    return {"ok": True, "result": _curve_payload(code)}
                return await super()._dispatch(
                    code, timeout_ms=timeout_ms)

        with TemporaryDirectory() as tmp:
            # Pre-create status so request_cancel has a file to flip.
            bridge = _CancelBridge(tmp)
            # Seed a status.json by starting; the curve stage flips cancel.
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-mini-v1"))
            self.assertFalse(result.ok)
            self.assertTrue(result.cancelled)
            self.assertEqual(result.error["code"], "cancelled")
            # A subsequent resume (cancel cleared) completes from checkpoints.
            pipe.request_cancel  # noqa: B018 — referenced for clarity
            status = json.loads((Path(tmp) / "status.json").read_text("utf-8"))
            status["cancel_requested"] = False
            (Path(tmp) / "status.json").write_text(
                json.dumps(status), encoding="utf-8")
            result2 = _run(pipe.run_decompile(
                FakePipelineBridge(), out_dir=tmp,
                change_stamp="pipeline-mini-v1"))
            self.assertTrue(result2.ok, msg=result2.to_dict())


class StageCategoriesTests(unittest.TestCase):
    def test_curtain_stage_feeds_curta_system(self) -> None:
        """Tail of wave aaa44b45 (28.07): the third kind of curtain-grid host.

        There are three kinds of curtain-grid hosts — wall, curtain system,
        roof. ``curtain_extract.py`` already knows how to walk
        ``CurtainSystem.CurtainGrids``, but as long as OST_CurtaSystem was not part of
        ``_STAGE_CATEGORIES["curtain"]``, the stage had nowhere to get the ids of curtain
        systems from — panels of this host were not getting addresses on
        read, even though emission (``set_curtain_panel``) does handle it.
        """
        self.assertIn("OST_CurtaSystem", pipe._STAGE_CATEGORIES["curtain"])
        # Both previously-read kinds (wall, roof) remain — adding
        # the third did not displace them.
        self.assertIn("OST_Walls", pipe._STAGE_CATEGORIES["curtain"])
        self.assertIn("OST_Roofs", pipe._STAGE_CATEGORIES["curtain"])


if __name__ == "__main__":
    unittest.main()
