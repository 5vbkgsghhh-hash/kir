"""Refuting tests for TYPE FINGERPRINTS in the dependency manifest.

Every test here reproduces a defect measured on the stored corpus
(``backend/backend/data/decompile``, 67 runs with ``L0.jsonl``, 2026-08-11)
and fails on the code as it stood before the fingerprint landed.

The measurements the fixtures below imitate, so the numbers are not lost:

* A type NAME is not unique even inside ONE document.  275 of the corpus's
  ``(category, type_name)`` cells hold more than one ``ElementType``, covering
  1029 ids.  The worst cell is ``k2_ar_rd_v15`` / ``13A-RD-AR-K2_v33_kuklev.d.s``
  -- 18 in-place wall types all named "Pilastre", one instance each.
  ``snowdon_plumb_v5`` (whose ``doc_name`` is *Snowdon Towers Sample
  Architectural*, not a fifth Plumbing revision) holds two DIFFERENT doors
  both named ``36" x 96"``.
* Grouping by the name merged 8700 real ElementType ids into 7945 manifest
  records: 755 definitions were silently lost.
* The family axis (``family_placement.index.json``) separates 115 of the 275
  cells completely and 0 partially; 692 ids stay indistinguishable, 216 of
  them ``OST_Walls``.
* ``snowdon_elec_v1`` proves the side index can be FOREIGN: 1837
  ``element_unresolved`` failures, 20 surviving rows, and all 20 carry a
  ``symbol_id`` that disagrees with the L0 ``type_id`` of the same element
  (an ``OST_LightingFixtures`` element labelled family "Round Elbow").
  Across the other 57 runs that carry the index, 242 020 of 242 020 rows
  agree.  A fingerprint built on those 20 rows would match the WRONG type.
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kukai.ir.decompile.dependencies import (
    FINGERPRINT_BLIND_INDEX_ABSENT,
    FINGERPRINT_BLIND_INDEX_REJECTED,
    FINGERPRINT_BLIND_NO_ROW,
    FINGERPRINT_BLIND_NO_TYPE_ID,
    TYPE_FINGERPRINT_SCHEMA_VERSION,
    TYPE_FINGERPRINT_SCOPE,
    DependencyIdentity,
    DependencyManifestError,
    DependencyDefinition,
    DependencyKind,
    DependencyResolution,
    TypeFingerprint,
    TypeIdentityState,
    build_dependency_manifest,
)
from kukai.ir.decompile.honesty import BuildStageState, BuildStatuses
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)


def _document(
    elements: list[dict[str, Any]],
    *,
    name: str = "type-fingerprint",
    links: list[dict[str, Any]] | None = None,
) -> L0Document:
    metadata = copy.deepcopy(project1_metadata())
    metadata.update({
        "doc_name": name,
        "change_stamp": f"{name}-v1",
        "levels": [metadata["levels"][0]],
        "grids": [],
        "rooms": [],
        "elements": copy.deepcopy(elements),
        "category_status": [],
        "links": copy.deepcopy(links or []),
    })
    return L0Document.from_dict(metadata)


def _pilastre_pair() -> L0Document:
    """Two DIFFERENT wall types sharing one name -- `Pilastre` in miniature."""

    first = make_element("OST_Walls", 11_851_533, ordinal=0)
    second = make_element("OST_Walls", 11_865_824, ordinal=1)
    first.update({"type_id": "11851531", "type_name": "Pilastre"})
    second.update({"type_id": "11865822", "type_name": "Pilastre"})
    return _document([first, second], name="pilastre")


def _placement_row(symbol_id: str, family_name: str) -> dict[str, Any]:
    return {"symbol_id": symbol_id, "family_name": family_name}


class TypeNameIsNotAnIdentityTests(unittest.TestCase):
    def test_two_types_with_one_name_are_two_definitions(self) -> None:
        """REFUTING.  The manifest merged them into ONE record.

        Measured: 755 definitions lost corpus-wide, 18 in a single cell.
        Grounding one merged record picks ONE type for all of them, silently.
        """

        manifest = build_dependency_manifest(_pilastre_pair())

        walls = [
            value for value in manifest.definitions
            if value.identity.category == "OST_Walls"
        ]
        self.assertEqual(len(walls), 2)
        self.assertEqual(
            sorted(value.source_type_id for value in walls),
            ["11851531", "11865822"],
        )
        self.assertEqual(len({value.key for value in walls}), 2)
        for definition in walls:
            self.assertEqual(len(definition.required_by), 1)

    def test_the_collision_is_reported_ambiguous_with_its_rivals_named(
            self) -> None:
        """REFUTING.  A merged record could not report ambiguity at all."""

        manifest = build_dependency_manifest(_pilastre_pair())
        walls = {
            value.key: value for value in manifest.definitions
            if value.identity.category == "OST_Walls"
        }

        for key, definition in walls.items():
            fingerprint = definition.type_identity
            self.assertIsNotNone(fingerprint)
            assert fingerprint is not None
            self.assertIs(fingerprint.state, TypeIdentityState.AMBIGUOUS)
            self.assertEqual(
                fingerprint.candidates,
                tuple(sorted(other for other in walls if other != key)),
            )
            self.assertEqual(fingerprint.scope, TYPE_FINGERPRINT_SCOPE)
            self.assertEqual(
                fingerprint.schema_version, TYPE_FINGERPRINT_SCHEMA_VERSION)
            self.assertEqual(
                fingerprint.blind_reason, FINGERPRINT_BLIND_INDEX_ABSENT)

        detail = {
            value.key: value.detail for value in manifest.unresolved
        }
        for key in walls:
            self.assertIn("rival definition", detail[key])

    def test_the_family_axis_separates_the_collision(self) -> None:
        """REFUTING.  Two doors named `36" x 96"` were indistinguishable.

        Measured on *Snowdon Towers Sample Architectural*: the family axis
        separates all 10 of that document's colliding cells, and 115 of the
        corpus's 275.
        """

        document = _pilastre_pair()
        index = {
            "11851533": _placement_row("11851531", "A_WALL_PilastreFlat"),
            "11865824": _placement_row("11865822", "A_WALL_PilastreRound"),
        }

        manifest = build_dependency_manifest(
            document, family_placement=index)

        walls = [
            value for value in manifest.definitions
            if value.identity.category == "OST_Walls"
        ]
        self.assertEqual(len(walls), 2)
        for definition in walls:
            fingerprint = definition.type_identity
            assert fingerprint is not None
            self.assertIs(fingerprint.state, TypeIdentityState.IDENTIFIED)
            self.assertEqual(fingerprint.candidates, ())
            self.assertIsNone(fingerprint.blind_reason)
            self.assertIn("family_name", dict(fingerprint.axes))
        self.assertNotEqual(
            walls[0].type_identity.digest, walls[1].type_identity.digest)

    def test_a_type_with_no_family_row_says_so_by_name(self) -> None:
        """A present index that simply has no row is NOT the same fact as an
        absent index, and neither is a guess."""

        document = _pilastre_pair()
        index = {"11851533": _placement_row("11851531", "A_WALL_PilastreFlat")}

        manifest = build_dependency_manifest(
            document, family_placement=index)

        by_type = {
            value.source_type_id: value.type_identity
            for value in manifest.definitions
            if value.identity.category == "OST_Walls"
        }
        self.assertIsNone(by_type["11851531"].blind_reason)
        self.assertEqual(
            by_type["11865822"].blind_reason, FINGERPRINT_BLIND_NO_ROW)


class ForeignSideIndexTests(unittest.TestCase):
    def test_an_index_read_from_another_document_is_refused_whole(
            self) -> None:
        """REFUTING.  Nothing checked the index's provenance, so 20 rows of a
        FOREIGN model would have supplied the family axis.

        `symbol_id` is the FamilySymbol's ElementId and must equal the L0
        `type_id` of the same element.  Measured: 242 020 of 242 020 rows
        agree in 57 runs; all 20 rows of `snowdon_elec_v1` disagree.
        """

        document = _pilastre_pair()
        foreign = {
            # The right element id, a symbol id belonging to another document.
            "11851533": _placement_row("213622", "Tee - Generic"),
            "11865824": _placement_row("11865822", "A_WALL_PilastreRound"),
        }

        manifest = build_dependency_manifest(
            document, family_placement=foreign)

        for definition in manifest.definitions:
            fingerprint = definition.type_identity
            assert fingerprint is not None
            self.assertNotIn("family_name", dict(fingerprint.axes))
            self.assertEqual(
                fingerprint.blind_reason, FINGERPRINT_BLIND_INDEX_REJECTED)

        provenance = [
            value for value in manifest.unresolved
            if value.key == "family_placement_index:provenance"
        ]
        self.assertEqual(len(provenance), 1)
        self.assertIn("1 row(s)", provenance[0].detail)
        self.assertEqual(provenance[0].affected_source_ids, ())


class ElementWithoutATypeTests(unittest.TestCase):
    def test_an_element_with_no_type_is_not_dressed_up_as_one(self) -> None:
        """Measured: 123 758 of 1 139 477 corpus elements carry no `type_id`
        -- rooms, lines, curtain grids, room separation lines.  A definition
        that names them anyway invents a dependency the document lacks."""

        row = make_element("OST_Walls", 12_000_001, ordinal=0)
        row.update({"type_id": "", "type_name": ""})

        manifest = build_dependency_manifest(_document([row]))

        definition = next(
            value for value in manifest.definitions
            if value.identity.category == "OST_Walls"
        )
        fingerprint = definition.type_identity
        assert fingerprint is not None
        self.assertIs(fingerprint.state, TypeIdentityState.UNIDENTIFIED)
        self.assertIsNone(fingerprint.digest)
        self.assertEqual(fingerprint.candidates, ())
        self.assertEqual(
            fingerprint.blind_reason, FINGERPRINT_BLIND_NO_TYPE_ID)
        detail = next(
            value.detail for value in manifest.unresolved
            if value.key == definition.key
        )
        self.assertIn(FINGERPRINT_BLIND_NO_TYPE_ID, detail)


class FingerprintCannotOverclaimTests(unittest.TestCase):
    def test_identified_in_the_source_is_not_resolved_in_a_target(
            self) -> None:
        """The whole hazard in one assertion.  `identified` says the SOURCE
        separates this definition from its neighbours; it says nothing about
        any target document, and frozen L0 1.0 holds no content digest of a
        Revit definition."""

        document = _pilastre_pair()
        index = {
            "11851533": _placement_row("11851531", "A_WALL_PilastreFlat"),
            "11865824": _placement_row("11865822", "A_WALL_PilastreRound"),
        }
        manifest = build_dependency_manifest(
            document, family_placement=index)

        unresolved_keys = {value.key for value in manifest.unresolved}
        for definition in manifest.definitions:
            assert definition.type_identity is not None
            if definition.type_identity.state is TypeIdentityState.IDENTIFIED:
                self.assertIsNone(definition.fingerprint)
                self.assertFalse(definition.resolved)
                self.assertEqual(
                    definition.resolution, DependencyResolution.TARGET_MATCH)
                self.assertIn(definition.key, unresolved_keys)

    def test_an_identified_definition_cannot_be_declared_resolved(
            self) -> None:
        identified = TypeFingerprint(
            schema_version=TYPE_FINGERPRINT_SCHEMA_VERSION,
            state=TypeIdentityState.IDENTIFIED,
            digest="0" * 64,
            axes=(("category", "OST_Walls"), ("type_name", "Pilastre")),
            scope=TYPE_FINGERPRINT_SCOPE,
        )
        with self.assertRaises(DependencyManifestError):
            DependencyDefinition(
                key="definition:overclaim",
                kind=DependencyKind.ELEMENT_TYPE,
                identity=DependencyIdentity(
                    category="OST_Walls", type_name="Pilastre"),
                fingerprint=None,
                required_by=("1",),
                requires=(),
                resolution=DependencyResolution.EMBEDDED,
                identity_note="note",
                embedded_store_ref="store",
                type_identity=identified,
            )

    def test_unidentified_must_name_its_reason(self) -> None:
        with self.assertRaises(DependencyManifestError):
            TypeFingerprint(
                schema_version=TYPE_FINGERPRINT_SCHEMA_VERSION,
                state=TypeIdentityState.UNIDENTIFIED,
                digest=None,
                axes=(),
                scope=TYPE_FINGERPRINT_SCOPE,
            )

    def test_ambiguous_must_list_its_rivals(self) -> None:
        with self.assertRaises(DependencyManifestError):
            TypeFingerprint(
                schema_version=TYPE_FINGERPRINT_SCHEMA_VERSION,
                state=TypeIdentityState.AMBIGUOUS,
                digest="0" * 64,
                axes=(("category", "OST_Walls"),),
                scope=TYPE_FINGERPRINT_SCOPE,
            )

    def test_a_digest_never_travels_without_its_axes(self) -> None:
        with self.assertRaises(DependencyManifestError):
            TypeFingerprint(
                schema_version=TYPE_FINGERPRINT_SCHEMA_VERSION,
                state=TypeIdentityState.IDENTIFIED,
                digest="0" * 64,
                axes=(),
                scope=TYPE_FINGERPRINT_SCOPE,
            )

    def test_a_blind_reason_outside_the_closed_vocabulary_refuses(
            self) -> None:
        with self.assertRaises(DependencyManifestError):
            TypeFingerprint(
                schema_version=TYPE_FINGERPRINT_SCHEMA_VERSION,
                state=TypeIdentityState.UNIDENTIFIED,
                digest=None,
                axes=(),
                scope=TYPE_FINGERPRINT_SCOPE,
                blind_reason="probably fine",
            )


class GroundableIsNotReachableByFingerprintsTests(unittest.TestCase):
    """A PIN, not a fix: it passes on the old code too.

    It exists because the obvious next sentence -- "fingerprint the types and
    `groundable` turns green" -- is FALSE for three independent reasons, and
    the next reader deserves to be stopped by a test rather than by a rebuild.
    """

    def test_every_type_identified_still_leaves_groundable_blocked(
            self) -> None:
        document = _pilastre_pair()
        index = {
            "11851533": _placement_row("11851531", "A_WALL_PilastreFlat"),
            "11865824": _placement_row("11865822", "A_WALL_PilastreRound"),
        }
        manifest = build_dependency_manifest(
            document, family_placement=index)

        self.assertEqual(
            manifest.type_identity_counts["ambiguous"], 0)
        self.assertEqual(
            manifest.type_identity_counts["unidentified"], 0)

        # (1) Two document-scope records are emitted unconditionally, so the
        #     unresolved count can never reach zero from a snapshot.
        self.assertGreaterEqual(manifest.unresolved_count, 2)
        self.assertLessEqual(
            {"source_environment:l0_1_0", "document_state:l0_1_0"},
            {value.key for value in manifest.unresolved},
        )

        status = BuildStatuses.initial(
            unresolved_dependencies=manifest.unresolved_count)
        self.assertIs(status.groundable.state, BuildStageState.BLOCKED)

        # (2) Even at zero the initial status is NOT_ATTEMPTED, never PASSED:
        #     an offline decompile has no target document to inspect, and
        #     nothing in the pipeline builds a BuildStatuses any other way.
        self.assertIs(
            BuildStatuses.initial(unresolved_dependencies=0).groundable.state,
            BuildStageState.NOT_ATTEMPTED,
        )

    def test_dependency_resolved_for_is_false_for_every_element(self) -> None:
        """Measured: `dependency_resolved` is 0 and `dependency_resolved_pct`
        is 0.0 in ALL 52 stored `verify.json`.  The cause is not the types --
        the two document-scope unresolved records list EVERY source id, so the
        per-element predicate is constant-false by construction."""

        document = _pilastre_pair()
        index = {
            "11851533": _placement_row("11851531", "A_WALL_PilastreFlat"),
            "11865824": _placement_row("11865822", "A_WALL_PilastreRound"),
        }
        manifest = build_dependency_manifest(
            document, family_placement=index)

        for element in document.elements:
            self.assertFalse(
                manifest.dependency_resolved_for(element.element_id))


if __name__ == "__main__":
    unittest.main()
