"""Open-model profile: compatibility, identity and pre-transaction refusal."""
from __future__ import annotations

import copy
import json
import unittest

from kir.contracts import RevisionProof
from kir.compiler import _TYPE_POOL_COLLECTOR_CS, compile_program
from kir.midend import GroundingContext
from kir.open_model import (
    GROUND_SNAPSHOT_CS,
    OpenModelProfile,
    OpenModelProfileError,
    TypeSection,
    PreflightIssueCode,
    preflight_programs,
    required_grounding_pools,
)
from kir.tests.fixtures import GROUND_SNAPSHOT


def _live_snapshot() -> dict:
    snapshot = copy.deepcopy(GROUND_SNAPSHOT)
    for pool_name in required_grounding_pools():
        rows = snapshot.setdefault(pool_name, [])
        for row in rows:
            element_id = int(row["id"])
            row["unique_id"] = f"{pool_name}:uid:{element_id}"
            row["version_guid"] = f"{element_id:032x}"
            row["class_name"] = "Autodesk.Revit.DB.ElementType"
        snapshot[pool_name + "__total"] = len(rows)
    snapshot.update({
        "__profile_schema_version": "open-model-profile/1",
        "__profile_required_pools": list(required_grounding_pools()),
        "__document_fingerprint": {
            "title": "Tower — COPY",
            "path_name": r"C:\models\tower-copy.rvt",
            "project_uid": "tower-project-uid",
        },
        "__revit_version": "2026",
        "__revit_build": "26.0.4.0",
    })
    return snapshot


def _profile(snapshot: dict | None = None) -> OpenModelProfile:
    return OpenModelProfile.from_ground_snapshot(
        _live_snapshot() if snapshot is None else snapshot,
        revision_proof=RevisionProof(
            "tower-revision",
            "1200:0123456789abcdef:fedcba9876543210"),
    )


def _wall_program(*, level_id: int = 42, type_id: int = 100) -> dict:
    return {
        "ir_version": "1.0",
        "ops": [{
            "op": "create_wall",
            "id": "W1",
            "p0_mm": [0, 0],
            "p1_mm": [6000, 0],
            "height_mm": 3000,
            "level": {"by": "element_id", "value": level_id},
            "type": {"by": "element_id", "value": type_id},
        }],
    }


class OpenModelProfileContractTests(unittest.TestCase):
    def test_registry_is_the_pool_source_of_truth_and_probe_proves_counts(
            self) -> None:
        pools = required_grounding_pools()

        # 17 -> 19: wave/arch added ceiling_types and railing_types
        # (create_ceiling / create_railing). The number is held by hand
        # deliberately — a new pool drags a collector into
        # GROUND_SNAPSHOT_CS along with it, and a figure that silently grew
        # would mean a pool nobody collects.
        # 19 -> 20: wave/wall-foundation added wall_foundation_types
        # (create_wall_foundation), collected via OfClass(WallFoundationType).
        # 20 -> 23: wave/mep-electrical added conduit_types,
        # flex_duct_types, and flex_pipe_types (create_conduit /
        # create_flex_duct / create_flex_pipe). THE NUMBER WAS RE-MEASURED
        # WITH AN INSTRUMENT AFTER THE MERGE
        # (open_model.required_grounding_pools()), not added up from the two
        # branches: each of them counted from its own 19, and either of
        # their figures, taken as is, would lose the other wave's pools.
        # 23 -> 27: wave/analysis added load_cases, point_load_types,
        # line_load_types, and area_load_types (create_point_load /
        # create_line_load / create_area_load). Three of them are types
        # collected via OfClass, the fourth is a pool of INSTANCES (load
        # cases), and it is mandatory for all three loads. A pool of load
        # natures (LoadNature) is deliberately ABSENT here: nothing grounds
        # against them, and this list is exactly what the registry's
        # selectors ground against.
        # 27 -> 28: wave/framing added truss_types (create_truss). Live
        # Revit rejects OfClass(TrussType), even though it compiles; so the
        # pool collects FamilySymbol + OST_Truss instead. ONE pool for TWO
        # operations — create_beam_system has no pool of its own: its
        # `symbol` grounds against the same beam_types as create_beam,
        # along with its filter by placement type.
        # AGAIN RE-MEASURED WITH THE INSTRUMENT, NOT ADDED UP: both waves
        # counted from 23 (27 and 24), and either of their figures, taken as
        # is, would lose the other's pools. 28 is
        # `len(required_grounding_pools())` after the merge.
        # 28 -> 30: wave/site added toposolid_types and building_pad_types
        # (create_topography(toposolid) / create_building_pad). The
        # thickness collector is SPECIAL — by the CLR type name on
        # HostObjAttributes, because a ToposolidType class does not exist on
        # 2021-2023, while the snapshot's body is one and the same across
        # all six versions (see the comment in open_model.py).
        # RE-MEASURED FOR THE THIRD TIME IN ONE MERGE: three waves named 27,
        # 24, and 21, each counting from its own slice. Not one of the
        # figures is fit to use.
        # 30 -> 32 (09.08): wave/sweep added wall_sweep_types and
        # slab_edge_types. The cornice collector is SPECIAL — by TWO
        # CATEGORIES, not by class, and this is the only possible way: a
        # `WallSweepType`-as-ElementType class does not exist in the API at
        # all (`WallSweepType` is an enum {Sweep, Reveal}, measured by
        # compiling against six versions), while the profile type lives as
        # an ordinary ElementType under OST_Cornices or OST_Reveals.
        # RE-MEASURED AS `len(required_grounding_pools())` ON THIS TREE.
        # 32 -> 33: wave/detail added filled_region_types
        # (create_filled_region), collected via OfClass(FilledRegionType).
        # A category-based collector here would be wrong on the merits:
        # OST_FilledRegion holds both the fills themselves and their types
        # (see the comment in open_model.py). The number was re-measured as
        # `len(required_grounding_pools())` on THIS tree, not added up from
        # a foreign branch — exactly what the three lines above warn
        # against.
        # 33 -> 36 (10.08): wave/reinforcement added
        # area_reinforcement_types, rebar_bar_types, and rebar_hook_types
        # (create_area_reinforcement). THREE, not one: `AreaReinforcement.
        # Create` checks EACH of the three arguments against its own class
        # separately and throws ArgumentException on a foreign id, meaning
        # a single shared "reinforcement types pool" would replace a typed
        # refusal with a runtime exception inside a transaction. All three
        # are collected via OfClass — a category-based collector here is
        # wrong on the merits, exactly as with the fill: OST_Rebar holds
        # both the bars and their types, and OST_AreaRein holds both the
        # systems and their types. The number was re-measured as
        # `len(required_grounding_pools())` on THIS tree.
        self.assertEqual(len(pools), 36)
        for pool in pools:
            if pool == "grids":
                self.assertIn('__snap["grids__total"]', GROUND_SNAPSHOT_CS)
            else:
                self.assertIn(f'__AddPool("{pool}"', GROUND_SNAPSHOT_CS)
        self.assertIn('__r["unique_id"]', GROUND_SNAPSHOT_CS)
        self.assertIn('__r["version_guid"]', GROUND_SNAPSHOT_CS)
        self.assertIn('__snap["__document_fingerprint"]', GROUND_SNAPSHOT_CS)
        self.assertIn(
            '__snap[__pool + "__total"] = __total', GROUND_SNAPSHOT_CS)
        # The rule is the same as before — "do not mention a
        # version-fragile name" — but it is now held by a CLOSED LIST WITH
        # MEASUREMENTS, rather than a bare substring: that one turned red on
        # the lawful `WorksetId.IntegerValue` (compiles on all six) right
        # along with the dangerous `ElementId.IntegerValue` (fails to
        # compile on 2026, CS1061). Details and both measurements are in
        # `open_model_guard.INTEGER_VALUE_EXCEPTIONS`.
        from kir.tests.open_model_guard import integer_value_offenders
        self.assertEqual(integer_value_offenders(GROUND_SNAPSHOT_CS), [])

    def test_truss_pool_uses_native_family_symbols_in_both_collectors(
            self) -> None:
        """TrussType compiles but FilteredElementCollector rejects it live."""
        snapshot_lines = [
            line for line in GROUND_SNAPSHOT_CS.splitlines()
            if line.startswith('__AddPool("truss_types", ')
        ]
        self.assertEqual(len(snapshot_lines), 1)

        collectors = {
            "grounding": _TYPE_POOL_COLLECTOR_CS["truss_types"],
            "open_model": snapshot_lines[0],
        }
        for owner, collector in collectors.items():
            with self.subTest(owner=owner):
                self.assertIn("OfClass(typeof(FamilySymbol))", collector)
                self.assertIn(
                    "OfCategory(BuiltInCategory.OST_Truss)", collector)
                self.assertNotIn("OfClass(typeof(TrussType))", collector)
                self.assertNotIn(
                    "OfClass(typeof(Autodesk.Revit.DB.Structure.TrussType))",
                    collector)

    def test_live_profile_is_revision_bound_authoritative_and_round_trips(
            self) -> None:
        profile = _profile()
        encoded = profile.to_dict()

        self.assertTrue(profile.identity_bound)
        self.assertTrue(profile.grounding_complete)
        self.assertTrue(profile.identity_complete)
        self.assertTrue(profile.authoritative)
        self.assertEqual(len(profile.digest), 64)
        self.assertEqual(
            OpenModelProfile.from_dict(
                json.loads(json.dumps(encoded, ensure_ascii=False))),
            profile,
        )

    def test_order_is_canonical_and_digest_is_deterministic(self) -> None:
        forward = _live_snapshot()
        reverse = copy.deepcopy(forward)
        for pool in required_grounding_pools():
            reverse[pool] = list(reversed(reverse[pool]))

        a = _profile(forward)
        b = _profile(reverse)

        self.assertEqual(a, b)
        self.assertEqual(a.digest, b.digest)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_legacy_snapshot_remains_groundable_but_not_authoritative(
            self) -> None:
        legacy = copy.deepcopy(GROUND_SNAPSHOT)
        before = copy.deepcopy(legacy)
        profile = OpenModelProfile.from_ground_snapshot(legacy)
        report = preflight_programs(_wall_program(), profile)

        self.assertFalse(profile.authoritative)
        self.assertFalse(profile.grounding_complete)
        self.assertFalse(profile.identity_complete)
        self.assertTrue(report.ready)
        self.assertEqual(len(report.bindings), 2)
        self.assertEqual(legacy, before)

    def test_unknown_explicit_version_is_refused(self) -> None:
        snapshot = _live_snapshot()
        snapshot["__profile_schema_version"] = "open-model-profile/99"
        with self.assertRaisesRegex(
                OpenModelProfileError, "unsupported"):
            OpenModelProfile.from_ground_snapshot(snapshot)

        row = _profile().to_dict()
        row["schema_version"] = "open-model-profile/99"
        with self.assertRaisesRegex(
                OpenModelProfileError, "unsupported"):
            OpenModelProfile.from_dict(row)

    def test_truncation_and_missing_total_never_become_authoritative(
            self) -> None:
        truncated = _live_snapshot()
        truncated["levels"] = truncated["levels"][:1]
        truncated["levels__truncated"] = True
        # The observed total remains two.
        profile = _profile(truncated)
        self.assertFalse(profile.grounding_complete)
        self.assertFalse(profile.authoritative)

        unproven = _live_snapshot()
        unproven.pop("levels__total")
        profile = _profile(unproven)
        self.assertFalse(profile.grounding_complete)
        self.assertFalse(profile.authoritative)

    def test_derived_flags_and_digest_cannot_lie(self) -> None:
        row = _profile().to_dict()
        row["authoritative"] = False
        with self.assertRaisesRegex(OpenModelProfileError, "mismatch"):
            OpenModelProfile.from_dict(row)

        row = _profile().to_dict()
        row["digest"] = "0" * 64
        with self.assertRaisesRegex(OpenModelProfileError, "digest mismatch"):
            OpenModelProfile.from_dict(row)

    def test_duplicate_ids_and_contradictory_counts_are_refused(self) -> None:
        duplicate = _live_snapshot()
        duplicate["levels"].append(copy.deepcopy(duplicate["levels"][0]))
        duplicate["levels__total"] += 1
        with self.assertRaisesRegex(OpenModelProfileError, "unique ElementId"):
            _profile(duplicate)

        contradictory = _live_snapshot()
        contradictory["levels__total"] = 1
        with self.assertRaisesRegex(OpenModelProfileError, "below captured"):
            _profile(contradictory)


class OpenModelPreflightTests(unittest.TestCase):
    def test_compiler_refuses_profile_from_another_snapshot(self) -> None:
        source_snapshot = _live_snapshot()
        source_profile = _profile(source_snapshot)
        other_snapshot = _live_snapshot()
        other_snapshot["__document_fingerprint"]["project_uid"] = "other"

        result = compile_program(
            _wall_program(),
            snapshot=other_snapshot,
            open_model_profile=source_profile,
            revit_version="2026",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.diagnostics[0].code, "KIR-G107")
        self.assertIn(
            "другому профилю открытой модели",
            result.diagnostics[0].message_ru,
        )

    def test_compiler_refuses_ground_context_from_another_snapshot(self) -> None:
        snapshot = _live_snapshot()
        profile = _profile(snapshot)
        other = copy.deepcopy(snapshot)
        other["levels"][0]["name"] = "Other level"
        context = GroundingContext.from_snapshot(
            other,
            source="trusted_bridge",
            trusted_source=True,
            profile_digest=profile.digest,
            profile_authoritative=profile.authoritative,
            revision_proof=profile.revision_proof,
        )

        result = compile_program(
            _wall_program(), snapshot=snapshot,
            open_model_profile=profile, ground_context=context,
            revit_version="2026",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.diagnostics[0].code, "KIR-G107")
        self.assertNotEqual(result.diagnostics[0].code, "KIR-P000")

    def test_compiler_refuses_context_with_foreign_profile_digest(self) -> None:
        snapshot = _live_snapshot()
        profile = _profile(snapshot)
        context = GroundingContext.from_snapshot(
            snapshot,
            source="trusted_bridge",
            trusted_source=True,
            profile_digest="0" * 64,
            profile_authoritative=profile.authoritative,
            revision_proof=profile.revision_proof,
        )

        result = compile_program(
            _wall_program(), snapshot=snapshot,
            open_model_profile=profile, ground_context=context,
            revit_version="2026",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.diagnostics[0].code, "KIR-G107")

    def test_compiler_refuses_context_with_foreign_revision_digest(self) -> None:
        snapshot = _live_snapshot()
        profile = _profile(snapshot)
        context = GroundingContext.from_snapshot(
            snapshot,
            source="trusted_bridge",
            trusted_source=True,
            profile_digest=profile.digest,
            profile_authoritative=profile.authoritative,
            revision_proof=RevisionProof(
                "other-revision",
                "1201:aaaaaaaaaaaaaaaa:bbbbbbbbbbbbbbbb"),
        )

        result = compile_program(
            _wall_program(), snapshot=snapshot,
            open_model_profile=profile, ground_context=context,
            revit_version="2026",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.diagnostics[0].code, "KIR-G107")

    def test_compiler_refuses_profile_claim_without_typed_profile(self) -> None:
        snapshot = _live_snapshot()
        context = GroundingContext.from_snapshot(
            snapshot,
            source="trusted_bridge",
            trusted_source=True,
            profile_digest="1" * 64,
            profile_authoritative=True,
        )

        result = compile_program(
            _wall_program(), snapshot=snapshot,
            ground_context=context, revit_version="2026",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.diagnostics[0].code, "KIR-G107")

    def test_pinned_level_and_type_are_bound_before_transaction(self) -> None:
        report = preflight_programs(
            _wall_program(), _profile(), require_exact_identity=True)

        self.assertTrue(report.ready)
        self.assertEqual(
            [(item.pool, item.element_id) for item in report.bindings],
            [("levels", 42), ("wall_types", 100)],
        )
        self.assertEqual(
            [proof.element_id for proof in report.exact_identity_proofs()],
            [42, 100],
        )
        self.assertEqual(report.to_dict()["binding_count"], 2)

    def test_missing_pinned_element_refuses(self) -> None:
        report = preflight_programs(
            _wall_program(level_id=999_999), _profile(),
            require_exact_identity=True,
        )

        self.assertFalse(report.ready)
        self.assertEqual(
            report.issues[0].code,
            PreflightIssueCode.PINNED_ELEMENT_MISSING,
        )
        self.assertEqual(report.issues[0].pool, "levels")

    def test_incomplete_pool_refuses_exact_same_document_preflight(self) -> None:
        legacy = OpenModelProfile.from_ground_snapshot(
            copy.deepcopy(GROUND_SNAPSHOT))
        report = preflight_programs(
            _wall_program(), legacy, require_exact_identity=True)

        self.assertFalse(report.ready)
        self.assertEqual(
            {item.code for item in report.issues},
            {PreflightIssueCode.PROFILE_POOL_INCOMPLETE},
        )
        with self.assertRaisesRegex(
                OpenModelProfileError, "refused preflight"):
            report.exact_identity_proofs()

    def test_malformed_version_guid_is_not_exact_evidence(self) -> None:
        snapshot = _live_snapshot()
        snapshot["levels"][0]["version_guid"] = "not-a-revit-guid"
        report = preflight_programs(
            _wall_program(), _profile(snapshot), require_exact_identity=True)

        self.assertFalse(report.ready)
        self.assertEqual(
            report.issues[0].code,
            PreflightIssueCode.PINNED_IDENTITY_UNPROVEN,
        )

    def test_element_id_reuse_or_type_edit_is_detected(self) -> None:
        source = _profile()
        changed_snapshot = _live_snapshot()
        changed = next(
            row for row in changed_snapshot["wall_types"]
            if row["id"] == 100)
        changed["version_guid"] = "f" * 32
        target = _profile(changed_snapshot)

        report = preflight_programs(
            _wall_program(),
            target,
            expected_profile=source,
            require_exact_identity=True,
        )

        self.assertFalse(report.ready)
        self.assertEqual(
            [item.code for item in report.issues],
            [PreflightIssueCode.PINNED_IDENTITY_CHANGED],
        )

    def test_wrong_open_document_is_detected_even_when_ids_match(self) -> None:
        source = _profile()
        other_snapshot = _live_snapshot()
        other_snapshot["__document_fingerprint"]["project_uid"] = "other"
        target = _profile(other_snapshot)

        report = preflight_programs(
            _wall_program(),
            target,
            expected_profile=source,
            require_exact_identity=True,
        )

        self.assertFalse(report.ready)
        self.assertEqual(
            report.issues[0].code,
            PreflightIssueCode.DOCUMENT_IDENTITY_CHANGED,
        )

    def test_name_selectors_remain_owned_by_ground_stage(self) -> None:
        program = _wall_program()
        program["ops"][0]["level"] = {"by": "name", "value": "Этаж 1"}
        program["ops"][0]["type"] = {"by": "default"}

        report = preflight_programs(
            program, _profile(), require_exact_identity=True)

        self.assertTrue(report.ready)
        self.assertFalse(report.bindings)


class GateModelBindingGuardTests(unittest.TestCase):
    """The GATE's own guard inputs — the consumer nobody measured.

    `test_compiler_refuses_profile_from_another_snapshot` above proves the
    compiler catches an incoherent (profile, snapshot) pair. Nothing proved
    that the gate does not HAND it one, and from before `aecf6cff` until
    2026-08-11 it did: the profile came from a mutated copy and the
    unmutated original was passed to `compile_program`. The refusal was
    correct; the harness was wrong; and because the gate `continue`s on a
    refusal, the open-model transaction guard body — explicitly outside the
    legacy byte corpus — was compiled on ZERO of the six versions while the
    gate counted six checks for it.

    A green here is only worth what its mutant is worth: replace the
    returned snapshot with the unmutated `GROUND_SNAPSHOT` and this test
    must go red on all six versions.
    """

    def test_gate_guard_inputs_compile_on_every_version(self) -> None:
        from kir import spec
        from kir.gate_runner import model_binding_guard_inputs
        # The gate's own `auth_wall`, not this module's `_wall_program`:
        # the latter pins a wall `type`, which demands an exact
        # `wall_types` pool the guard profile never stamps, and would
        # refuse for a reason that has nothing to do with the pair. A test
        # of the harness must compile what the harness compiles.
        from kir.tests.test_authoring import _prog, _wall

        snapshot, profile, document = model_binding_guard_inputs()

        for version in spec.REVIT_VERSIONS:
            with self.subTest(version=version):
                result = compile_program(
                    _prog([_wall()], intent="стена 6м"),
                    revit_version=version,
                    snapshot=snapshot,
                    expected_document=document,
                    open_model_profile=profile,
                )
                codes = [d.code for d in result.diagnostics]
                self.assertTrue(
                    result.ok,
                    f"the gate's own guard inputs refuse on {version}: "
                    f"{codes} — the body it reports six checks for is "
                    f"never compiled",
                )
                self.assertNotIn("KIR-G107", codes)

    def test_guard_profile_is_derived_from_the_returned_snapshot(self) -> None:
        """The pair cannot be split: one is computable from the other."""
        from kir.gate_runner import model_binding_guard_inputs

        snapshot, profile, _ = model_binding_guard_inputs()

        recomputed = OpenModelProfile.from_ground_snapshot(
            snapshot,
            revision_proof=profile.revision_proof,
            required_pools=profile.required_pools,
        )

        self.assertEqual(recomputed.digest, profile.digest)


if __name__ == "__main__":
    unittest.main()


class WorksetIdIsItsOwnSpace(unittest.TestCase):
    """🔴 A WORKSET IS NOT AN ELEMENT, AND ITS ZERO IS LEGITIMATE (measured 18.08.2026).

    Decompiling `13A-RD-AR-K2_v33` — the owner's live shared document, Revit
    2023 — failed COMPLETELY at the very first step:

        open_model_profile_invalid
        ground_snapshot.worksets[0].id must be an ElementId within 1..…

    We asked the live Revit instead of guessing a fix: **3142 worksets, the
    first user one carries id = 0** (`!00_Связи_Base`, `UserWorkset`), min=0,
    max=28560, zero negative ones. It was not the model that failed but our
    KIND-level mistake: the `ElementId` lower bound had been imposed on
    `WorksetId`. Sharing is the norm for a real project, so the cost was
    "cannot decompile the working model at all".

    🔴 WHY THE POOL IS DECLARED HERE EXPLICITLY, NOT TAKEN FROM THE REFERENCE.
    `worksets` is NOT part of `required_grounding_pools()` (36 pools, it is
    not among them), so the first edition of this test was GREEN BY
    CONSTRUCTION: the pool was never decompiled at all, and "zero accepted"
    meant "zero was never checked". The live snapshot carries its own list in
    `__profile_required_pools`, and decompilation follows THAT list — the
    test is obligated to reproduce this path, or it guards emptiness.
    """

    @staticmethod
    def _snapshot_with_worksets() -> dict:
        snapshot = _live_snapshot()
        rows = snapshot.get("worksets")
        assert rows, "в эталоне нет строк worksets — тест беспредметен"
        for row in rows:
            element_id = int(row["id"])
            row["unique_id"] = f"worksets:uid:{element_id}"
            row["version_guid"] = f"{element_id:032x}"
            row["class_name"] = "Autodesk.Revit.DB.Workset"
        snapshot["worksets__total"] = len(rows)
        snapshot["__profile_required_pools"] = (
            list(required_grounding_pools()) + ["worksets"])
        return snapshot

    def test_the_pool_is_actually_parsed(self) -> None:
        # Guard on the test itself: if the pool stops being decompiled, the
        # other three would turn green while checking nothing. That is
        # exactly what happened in the first edition.
        profile = _profile(self._snapshot_with_worksets())
        names = [p.name for p in profile.pools]
        self.assertIn("worksets", names,
                      "пул не разобран — три проверки ниже беспредметны")

    def test_zero_is_accepted_for_worksets(self) -> None:
        snapshot = self._snapshot_with_worksets()
        snapshot["worksets"][0]["id"] = 0
        snapshot["worksets"][0]["unique_id"] = "worksets:uid:0"
        snapshot["worksets"][0]["version_guid"] = f"{0:032x}"
        profile = _profile(snapshot)
        ids = [e.element_id
               for pool in profile.pools if pool.name == "worksets"
               for e in pool.entries]
        self.assertIn(0, ids, "ноль воркcета не доехал до профиля")

    def test_minus_one_is_refused_because_it_means_absence(self) -> None:
        snapshot = self._snapshot_with_worksets()
        snapshot["worksets"][0]["id"] = -1
        with self.assertRaises(OpenModelProfileError) as caught:
            _profile(snapshot)
        self.assertIn("InvalidWorksetId", str(caught.exception),
                      "отказ обязан НАЗВАТЬ, почему именно -1 не адрес")

    def test_zero_is_still_refused_everywhere_else(self) -> None:
        # This is the CONTROL, and it is the main one here: the first checks
        # are also green under a GLOBAL relaxation of "allow zero everywhere".
        # The only thing that tells a fix apart from a weakened contract is
        # that zero is still rejected for every other pool.
        base = _live_snapshot()
        other = [n for n in required_grounding_pools() if base.get(n)]
        self.assertTrue(other, "не на чем показать разницу — контроль вырожден")
        for name in other[:3]:
            snapshot = self._snapshot_with_worksets()
            snapshot[name][0]["id"] = 0
            with self.assertRaises(OpenModelProfileError, msg=name):
                _profile(snapshot)


# ═════════════════════════════════════════════════════════════════════════
# WALL LAYER COMPOSITION (type wave, 23.08.2026)
#
# Why these checks are shaped exactly this way. The wall type was
# unreproducible in a foreign document because decompilation knew only the
# TOTAL thickness. An op that built a type from a single number would give
# the correct name and the correct volume with the WRONG layer stack — and
# no instrument in the tree would be able to catch it. So the composition is
# read; and once it is read, it must have guards against whatever it COULD
# damage.
# ═════════════════════════════════════════════════════════════════════════


class WallLayers(unittest.TestCase):

    def test_old_profile_without_layers_round_trips_byte_identical(self):
        """A snapshot taken BEFORE the layer wave is read and written
        VERBATIM.

        This is not courtesy toward old files: the profile fingerprint feeds
        the run-to-run comparison, and an extra `layers: []` key would shift
        the whole corpus — the 23.08 measurement on disk: 1,623 type sections
        across 81 profiles, zero discrepancies.
        """
        row = {"kind": "plate", "source": "WallType.Width",
               "thickness_mm": 80.0, "uniform": True}
        self.assertEqual(TypeSection.from_dict(row).to_dict(), row)

    def test_layers_and_unreadable_cannot_both_be_true(self):
        """"Here is the composition" and "the composition could not be read"
        are two different answers to one question.

        Same disease as `uniform` alongside `blockers`, and forbidden the
        same way.
        """
        with self.assertRaises(OpenModelProfileError):
            TypeSection(kind="plate", source="WallType.Width",
                        thickness_mm=200.0, uniform=True,
                        layers=((20.0, "Finish1", "Мет"),),
                        layers_unreadable=True)

    def test_layer_without_material_is_none_and_key_is_omitted(self):
        """A layer without a material is a LEGITIMATE Revit state, not "we
        failed to read it".

        `MaterialId == InvalidElementId` occurs on real types. An empty
        string instead of `None` would turn a fact about the model into a
        gap of ours.
        """
        section = TypeSection.from_dict({
            "kind": "plate", "source": "WallType.Width",
            "thickness_mm": 200.0, "uniform": True,
            "layers": [{"width_mm": 160.0, "function": "Insulation"}],
        })
        self.assertEqual(section.layers, ((160.0, "Insulation", None),))
        self.assertNotIn("material", section.to_dict()["layers"][0])

    def test_reading_layers_never_adds_a_blocker(self):
        """🔴 THE MAIN GUARD OF THIS WAVE, AND IT IS STRUCTURAL.

        `blockers` decide `uniform`, and `uniform` decides whether the clash
        builds a prism by thickness alone. If a cause like
        `layers_unreadable` showed up here, types that are `uniform` today
        would retroactively become blocked: it would shift both the whole
        corpus's profile and the clash's behavior, for the sake of a field
        that has nothing to do with the body.

        What is being checked is the EMISSION, not the intent: on the wall
        branch, a layer-read failure is obligated to write ITS OWN field,
        not call `__blk.Add`.
        """
        start = GROUND_SNAPSHOT_CS.index("var __wt = __e as WallType;")
        end = GROUND_SNAPSHOT_CS.index("var __ho = __e as HostObjAttributes;")
        tail = GROUND_SNAPSHOT_CS[start:end]
        tail = tail[tail.index("GetLayers()"):]
        self.assertNotIn("__blk.Add", tail,
                         "чтение слоёв добавило блокер — это задним числом "
                         "сделает не-uniform типы, которые сегодня uniform")
        self.assertIn('__sec["layers_unreadable"] = true', tail,
                      "провал чтения слоёв обязан быть НАЗВАН своим полем")


class PoolRowsCarryPlacementType(unittest.TestCase):
    """A pool cannot filter out an unfit candidate if it has no feature to
    filter on.

    🔴 MEASURED LIVE ON 24.08.2026, document "Проект2", prod path `revit_ir`:
    `create_adaptive_component` on `{"by":"default"}` got a `KIR-G102`
    with **323 candidates** from the `family_symbols` pool, and every one
    shown was a curtain-wall mullion. Any one of them yields a runtime
    failure: the adaptive op needs `FamilyPlacementType.Adaptive`, while the
    pool hands back EVERY symbol in the document.

    A relative recorded earlier in the canon, on a different op:
    `place_family` only places point-based families
    (`OneLevelBased`/`OneLevelBasedHosted`), and `OST_TelephoneDevices` —
    4479 elements, **55% of the tower's effective gap** — never gets raised
    precisely because they are `TwoLevelsBased`.

    Eight pools stand on `FamilySymbol`; only ONE filters — `beam_types` —
    and it filters INSIDE the collector, meaning the feature never reaches
    Python at all. Hence: fixing the filter in `ground.py` is useless, what
    needs fixing is the CAPTURE.

    That the feature exists is proven not by the index but by the compiler:
    the `data/api_surface/` index carries no PROPERTIES at all (`Wall.Width`,
    `Family.Name`, `FamilySymbol.FamilyName` — all absent, `Family` only has
    methods there), while `beam_types` calls
    `Family.FamilyPlacementType` and compiles 6/6 against the reference
    assemblies.
    """

    def test_family_symbol_rows_carry_placement_type(self) -> None:
        self.assertIn(
            "FamilyPlacementType", GROUND_SNAPSHOT_CS,
            "тип размещения не читается при сборке строк пула",
        )
        self.assertIn(
            '"placement_type"', GROUND_SNAPSHOT_CS,
            "строка пула не несёт ключа placement_type: заземлению нечем "
            "отличить годного кандидата от негодного",
        )

    def test_placement_type_is_read_for_every_symbol_pool_not_only_beams(self) -> None:
        # `beam_types` filters INSIDE its own collector — that is not
        # enough: the feature is needed on the ROW, otherwise the other
        # seven pools do not have it.
        # 🔴 THE FIRST EDITION OF THIS CHECK WAS GREEN BY LUCK.
        # It searched for "FamilyPlacementType" before `__AddPool("beam_types"`
        # — and found it in a COMMENT one line above, not in the code. The
        # guard was matching prose and could never turn red. The anchor is
        # now on the row-ASSEMBLY BLOCK, the only place all eight pools pass
        # through.
        body = GROUND_SNAPSHOT_CS
        anchor = "var __fs = __e as FamilySymbol;"
        self.assertIn(anchor, body, "блок сборки строки FamilySymbol не найден")
        block = body.split(anchor, 1)[1].split("if (__ParamNames.Length", 1)[0]
        self.assertIn(
            "FamilyPlacementType", block,
            "тип размещения читается ТОЛЬКО в коллекторе beam_types; "
            "остальные семь пулов на FamilySymbol признака не получают",
        )


class СписокТребуемыхПуловОдин(unittest.TestCase):
    """🔴 MEASURED 25.08.2026: THE LIST OF REQUIRED POOLS HAD TWO CARRIERS.

    Python DERIVES it from the live registry (`required_grounding_pools` —
    "the exact pool universe declared by the live OpSpec registry"), while
    the emitted C# carried a HANDWRITTEN literal. They diverged by three
    names:

        in C# 39 · in the registry 36 · extras: materials, phases, worksets

    And this is not harmless: the list arrives IN THE SNAPSHOT
    (`__profile_required_pools`), and `from_ground_snapshot` takes THAT one,
    not the registry. That is, on a LIVE model, the C# version is truth.

    A run on a snapshot shaped like live C#, three cases:

        as C# writes it (39, worksets without __total)  authoritative=False
        + worksets__total                        grounding=True,
                                                 authoritative STILL False
        list from the registry (36)                     authoritative=True

    The second case revealed a second cause: workset rows have no
    `unique_id`/`version_guid`/`class_name`, so `identity_complete` is also
    false. But both causes trace back to ONE thing: a pool that no op
    grounds against is declared mandatory for grounding.

    THE COST. `a5_contract` requires `authoritative`, otherwise
    `A5JournalError("A5 open model profile is non-authoritative")`:
    reassembly into the same document failed on EVERY live model.

    THE BOUNDARY. The snapshot is built in the shape of the emitted C#, not
    captured from a live Revit: that the bridge actually hands back exactly
    these keys — is read, not measured.
    """

    @staticmethod
    def _пулы_из_cs() -> list[str]:
        import re
        from kir.open_model import GROUND_SNAPSHOT_CS
        m = re.search(r'__profile_required_pools[^;]{0,4000}', GROUND_SNAPSHOT_CS)
        assert m, "C# больше не пишет список требуемых пулов"
        return [n for n in re.findall(r'"(\w+)"', m.group(0))
                if n != "__profile_required_pools"]

    def test_список_в_C_совпадает_с_реестром(self):
        из_cs = self._пулы_из_cs()
        из_реестра = list(required_grounding_pools())
        self.assertEqual(
            sorted(из_cs), sorted(из_реестра),
            f"два носителя одного списка разошлись: в C# {len(из_cs)}, "
            f"в реестре {len(из_реестра)}; лишние в C# — "
            f"{sorted(set(из_cs) - set(из_реестра))}")

    def test_снимок_по_форме_живого_C_даёт_авторитетный_профиль(self):
        """An end-to-end check: if there were only one list, there would be
        no failure."""
        снимок = _live_snapshot()
        снимок["__profile_required_pools"] = self._пулы_из_cs()
        профиль = OpenModelProfile.from_ground_snapshot(
            снимок, revision_proof=RevisionProof("rev", "fp"))
        по = {p.name: p for p in профиль.pools}
        неполные = [n for n in профиль.required_pools
                    if n not in по or not по[n].complete]
        self.assertEqual(неполные, [], f"неполные требуемые пулы: {неполные}")
        self.assertTrue(профиль.authoritative,
                        "профиль не авторитетен — пересборка A5 откажет")

    def test_КОНТРОЛЬ_настоящая_неполнота_по_прежнему_видна(self):
        """The instrument must be able to say "no". Otherwise narrowing the
        list would not be a fix but a removal of the check."""
        снимок = _live_snapshot()
        имя = required_grounding_pools()[0]
        снимок.pop(имя + "__total", None)
        профиль = OpenModelProfile.from_ground_snapshot(
            снимок, revision_proof=RevisionProof("rev", "fp"))
        self.assertFalse(профиль.grounding_complete,
                         f"пул {имя} без __total объявлен полным")
        self.assertFalse(профиль.authoritative)


class ПотолокНоминаловОдин(unittest.TestCase):
    """🔴 MEASURED 25.08.2026: A CONSTANT NEVER REACHED C#, AND THIS IS THE
    SECOND SUCH CASE IN ONE FILE.

    `SECTION_MAX_SIZES = 64` is declared, exported in `__all__` — and read by
    nobody: a full grep across the tree gives TWO lines, the declaration and
    the export. The real ceiling stood as a bare literal in the emitted C#:

        if (__pairs.Count >= 64) { __trunc = true; break; }

    Confirmed by a run: raising the constant to 256 — C# still says 64.
    Whoever raised it would get exactly nothing, and a program with a 65th
    nominal size would get "nominal not found", even though this same
    section's docstring says such an answer must read as "data exists but
    was truncated".

    The first case — the list of required pools (same file, same hour):
    Python derived 36 from the registry, C# carried a handwritten 39. The
    shape is the same: a value declared in Python and REPEATED as a literal
    in C#.
    """

    def test_потолок_в_C_приходит_из_константы(self):
        import re
        from kir.open_model import GROUND_SNAPSHOT_CS, SECTION_MAX_SIZES
        потолки = re.findall(r'__pairs\.Count\s*>=\s*(\d+)', GROUND_SNAPSHOT_CS)
        self.assertTrue(потолки, "потолок номиналов исчез из эмиссии вовсе")
        for найден in потолки:
            self.assertEqual(
                int(найден), SECTION_MAX_SIZES,
                f"в C# потолок {найден}, в константе {SECTION_MAX_SIZES}: "
                f"два носителя одной величины")

    def test_КОНТРОЛЬ_смена_константы_двигает_эмиссию(self):
        """A matching number could be a coincidence. The instrument must
        show the LINK: raise the constant and watch whether C# moves."""
        import importlib
        import re

        from kir import open_model as om
        было = om.SECTION_MAX_SIZES
        try:
            om.SECTION_MAX_SIZES = 256
            новый = om._ground_snapshot_cs()
            потолки = {int(x) for x in
                       re.findall(r'__pairs\.Count\s*>=\s*(\d+)', новый)}
            self.assertEqual(
                потолки, {256},
                f"константа поднята до 256, а C# несёт {потолки}: связи нет")
        finally:
            om.SECTION_MAX_SIZES = было
            importlib.reload(om)

    def test_ни_одна_константа_модуля_не_повторена_литералом_в_шаблоне(self):
        """A guard on the KIND, not on the instance.

        Within one hour on 25.08, this file turned up TWO values declared in
        Python and repeated as a literal in C#: the list of required pools
        (36 vs 39) and the nominal-size ceiling (constant 64, literal 64). A
        third one need not be hunted by eye — let it turn red on its own.

        What is being asked for is the PATTERN, not ready-made text: in the
        finished text, the substituted number stands legitimately, and a
        check against it would be green forever.
        """
        import re

        from kir import open_model as om

        шаблон = re.sub(r'//[^\n]*', '', om._GROUND_SNAPSHOT_CS_TEMPLATE)
        числа = {int(x) for x in
                 re.findall(r'(?<![\w.])(\d{2,7})(?![\w.])', шаблон)}
        константы = {имя: знач for имя, знач in vars(om).items()
                     if имя.isupper() and isinstance(знач, int)
                     and not isinstance(знач, bool) and знач > 1}
        нарушители = {имя: знач for имя, знач in константы.items()
                      if знач in числа}
        self.assertEqual(
            нарушители, {},
            f"величина объявлена в питоне и ПОВТОРЕНА литералом в шаблоне "
            f"C#: {нарушители}. Подставляй её, как `__SECTION_MAX_SIZES__`, "
            f"иначе носителей снова станет два.")
