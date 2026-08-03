from __future__ import annotations

import unittest

from kukai.ir.decompile.geom_extract import extract_geometry, geometry_hash
from kukai.ir.decompile.geometry_acceptance import (
    FormAcceptanceState,
    FormExpectation,
    FormMismatchCode,
    check_form_acceptance,
    mesh_surface_digest,
)
from kukai.ir.decompile.recompile import GmMesh
from kukai.ir.decompile.tests.test_geom_extract import (
    _element,
    _part,
    _payload,
)


def _square() -> GmMesh:
    return GmMesh(
        vertices_mm=(
            (0.0, 0.0, 0.0),
            (1000.0, 0.0, 0.0),
            (0.0, 1000.0, 0.0),
            (1000.0, 1000.0, 0.0),
        ),
        triangles=((0, 1, 2), (1, 3, 2)),
    )


def _expectation(mesh: GmMesh | None = None) -> FormExpectation:
    value = mesh or _square()
    return FormExpectation.from_mesh(
        source_id="source-42",
        op_id="e42",
        program_index=3,
        plan_digest="a" * 64,
        source_geometry_hash="b" * 64,
        directshape_category="generic_model",
        geometry_tier="Gm",
        mesh=value,
    )


def _read(mesh: GmMesh, *, category: str = "OST_GenericModel"):
    return extract_geometry(_payload([
        _element("7001", category, [_part(mesh)]),
    ]))


class SurfaceCanonTests(unittest.TestCase):
    def test_vertex_number_triangle_order_and_winding_do_not_change_form(self):
        base = _square()
        # old -> new vertex positions: 0->2, 1->0, 2->3, 3->1
        reordered = GmMesh(
            vertices_mm=(
                base.vertices_mm[1],
                base.vertices_mm[3],
                base.vertices_mm[0],
                base.vertices_mm[2],
            ),
            triangles=((3, 1, 0), (3, 0, 2)),
        )
        self.assertEqual(
            mesh_surface_digest(base), mesh_surface_digest(reordered))
        # The content-store identity intentionally remains representation
        # sensitive; form acceptance is the separate geometric equivalence.
        self.assertNotEqual(geometry_hash(base), geometry_hash(reordered))

    def test_moving_an_interior_bbox_corner_changes_form_digest(self):
        base = _square()
        moved = GmMesh(
            vertices_mm=(
                (10.0, 10.0, 0.0),
                *base.vertices_mm[1:],
            ),
            triangles=base.triangles,
        )
        self.assertNotEqual(
            mesh_surface_digest(base), mesh_surface_digest(moved))


class IndependentFormAcceptanceTests(unittest.TestCase):
    def test_exact_separate_geometry_read_is_accepted(self):
        expectation = _expectation()
        verdict = check_form_acceptance(
            expectation, _read(_square()), created_element_id="7001")

        self.assertTrue(verdict.accepted)
        self.assertEqual(verdict.state, FormAcceptanceState.ACCEPTED)
        self.assertEqual(verdict.mismatches, ())
        self.assertEqual(len(verdict.evidence_digest), 64)
        self.assertEqual(
            verdict.to_dict()["expectation_digest"],
            expectation.expectation_digest,
        )

    def test_vertex_change_with_same_bbox_and_count_is_rejected(self):
        base = _square()
        changed = GmMesh(
            vertices_mm=((10.0, 10.0, 0.0), *base.vertices_mm[1:]),
            triangles=base.triangles,
        )
        verdict = check_form_acceptance(
            _expectation(base), _read(changed), created_element_id="7001")

        self.assertEqual(verdict.state, FormAcceptanceState.REJECTED)
        self.assertEqual(
            {row.code for row in verdict.mismatches},
            {FormMismatchCode.SURFACE_MISMATCH},
        )

    def test_missing_triangle_is_named_and_rejected(self):
        changed = GmMesh(
            vertices_mm=_square().vertices_mm[:3],
            triangles=((0, 1, 2),),
        )
        verdict = check_form_acceptance(
            _expectation(), _read(changed), created_element_id="7001")
        codes = {row.code for row in verdict.mismatches}

        self.assertEqual(verdict.state, FormAcceptanceState.REJECTED)
        self.assertIn(FormMismatchCode.TRIANGLE_COUNT_MISMATCH, codes)
        self.assertIn(FormMismatchCode.SURFACE_MISMATCH, codes)

    def test_shifted_surface_names_bbox_mismatch(self):
        shifted = GmMesh(
            vertices_mm=tuple(
                (x + 100.0, y, z) for x, y, z in _square().vertices_mm),
            triangles=_square().triangles,
        )
        verdict = check_form_acceptance(
            _expectation(), _read(shifted), created_element_id="7001")
        codes = {row.code for row in verdict.mismatches}

        self.assertEqual(verdict.state, FormAcceptanceState.REJECTED)
        self.assertIn(FormMismatchCode.BBOX_MISMATCH, codes)
        self.assertIn(FormMismatchCode.SURFACE_MISMATCH, codes)

    def test_wrong_created_category_is_rejected(self):
        verdict = check_form_acceptance(
            _expectation(),
            _read(_square(), category="OST_Furniture"),
            created_element_id="7001",
        )
        self.assertEqual(verdict.state, FormAcceptanceState.REJECTED)
        self.assertIn(
            FormMismatchCode.CATEGORY_MISMATCH,
            {row.code for row in verdict.mismatches},
        )

    def test_no_created_identity_is_inconclusive_not_success(self):
        verdict = check_form_acceptance(
            _expectation(), _read(_square()), created_element_id=None)
        self.assertEqual(verdict.state, FormAcceptanceState.INCONCLUSIVE)
        self.assertEqual(
            verdict.mismatches[0].code,
            FormMismatchCode.OBSERVATION_MISSING,
        )

    def test_missing_post_commit_geometry_is_inconclusive(self):
        unrelated = extract_geometry(_payload([
            _element("7999", "OST_GenericModel", [_part(_square())]),
        ]))
        verdict = check_form_acceptance(
            _expectation(), unrelated, created_element_id="7001")
        self.assertEqual(verdict.state, FormAcceptanceState.INCONCLUSIVE)
        self.assertEqual(
            verdict.mismatches[0].code,
            FormMismatchCode.GEOMETRY_UNAVAILABLE,
        )

    def test_expectation_digest_binds_exact_typed_plan(self):
        first = _expectation()
        second = FormExpectation.from_mesh(
            source_id=first.source_id,
            op_id=first.op_id,
            program_index=first.program_index,
            plan_digest="c" * 64,
            source_geometry_hash=first.source_geometry_hash,
            directshape_category=first.directshape_category,
            geometry_tier=first.geometry_tier,
            mesh=_square(),
        )
        self.assertNotEqual(
            first.expectation_digest, second.expectation_digest)


if __name__ == "__main__":
    unittest.main()
