"""Open-model profile: compatibility, identity and pre-transaction refusal."""
from __future__ import annotations

import copy
import json
import unittest

from kukai.ir.contracts import RevisionProof
from kukai.ir.compiler import _TYPE_POOL_COLLECTOR_CS, compile_program
from kukai.ir.midend import GroundingContext
from kukai.ir.open_model import (
    GROUND_SNAPSHOT_CS,
    OpenModelProfile,
    OpenModelProfileError,
    PreflightIssueCode,
    preflight_programs,
    required_grounding_pools,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


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

        # 17 -> 19: wave/arch добавила ceiling_types и railing_types
        # (create_ceiling / create_railing). Число держится руками намеренно —
        # новый пул тянет за собой сборщик в GROUND_SNAPSHOT_CS, и молча
        # выросшая цифра означала бы пул, который никто не собирает.
        # 19 -> 20: wave/wall-foundation добавила wall_foundation_types
        # (create_wall_foundation), собирается OfClass(WallFoundationType).
        # 20 -> 23: wave/mep-electrical добавила conduit_types,
        # flex_duct_types и flex_pipe_types (create_conduit /
        # create_flex_duct / create_flex_pipe). ЧИСЛО ПЕРЕСНЯТО ПРИБОРОМ ПОСЛЕ
        # СЛИЯНИЯ (open_model.required_grounding_pools()), а не сложено из
        # двух веток: каждая из них считала от своего 19, и любая из их цифр,
        # взятая как есть, потеряла бы пулы другой волны.
        # 23 -> 27: wave/analysis добавила load_cases, point_load_types,
        # line_load_types и area_load_types (create_point_load /
        # create_line_load / create_area_load). Три из них — типы, собираемые
        # OfClass, четвёртый — пул ЭКЗЕМПЛЯРОВ (случаи загружения), и он
        # обязателен у всех трёх нагрузок. Пула природ нагрузки (LoadNature)
        # здесь НЕТ намеренно: им никто не заземляется, а этот список — ровно
        # то, чем заземляются селекторы реестра.
        # 27 -> 28: wave/framing добавила truss_types (create_truss).
        # Живой Revit отвергает OfClass(TrussType), хотя он компилируется;
        # поэтому пул собирает FamilySymbol + OST_Truss. ОДИН пул на ДВЕ
        # операции — у
        # create_beam_system своего пула нет: её `symbol` грунтуется тем же
        # beam_types, что и create_beam, вместе с его фильтром по типу
        # размещения.
        # И СНОВА ПЕРЕСНЯТО ПРИБОРОМ, А НЕ СЛОЖЕНО: обе волны считали от 23
        # (27 и 24), и любая их цифра, взятая как есть, потеряла бы пулы
        # другой. 28 — это `len(required_grounding_pools())` после слияния.
        # 28 -> 30: wave/site добавила toposolid_types и building_pad_types
        # (create_topography(toposolid) / create_building_pad). Сборщик толщи
        # ОСОБЫЙ — по имени типа CLR у HostObjAttributes, потому что класса
        # ToposolidType на 2021-2023 не существует, а тело снапшота одно на
        # все шесть версий (см. комментарий в open_model.py).
        # ПЕРЕСНЯТО В ТРЕТИЙ РАЗ ЗА ОДНО СЛИЯНИЕ: три волны назвали 27, 24 и
        # 21, считая каждая от своего среза. Ни одна цифра не годится.
        # 30 -> 32 (09.08): wave/sweep добавила wall_sweep_types и
        # slab_edge_types. Сборщик карнизов ОСОБЫЙ — по ДВУМ КАТЕГОРИЯМ, а не
        # по классу, и это единственно возможный способ: класса
        # `WallSweepType`-как-ElementType в API не существует вовсе
        # (`WallSweepType` — перечисление {Sweep, Reveal}, замерено
        # компиляцией на шести версиях), а тип профиля живёт обычным
        # ElementType в OST_Cornices либо OST_Reveals.
        # ПЕРЕСНЯТО `len(required_grounding_pools())` НА ЭТОМ ДЕРЕВЕ.
        # 32 -> 33: wave/detail добавила filled_region_types
        # (create_filled_region), собирается OfClass(FilledRegionType).
        # Категорийный сборщик здесь был бы неверен по существу:
        # OST_FilledRegion держит и сами заливки, и их типы (см. комментарий
        # в open_model.py). Число переснято `len(required_grounding_pools())`
        # на ЭТОМ дереве, а не сложено с чужой ветки — ровно то, о чём
        # предупреждают три строки выше.
        # 33 -> 36 (10.08): wave/reinforcement добавила area_reinforcement_types,
        # rebar_bar_types и rebar_hook_types (create_area_reinforcement). ТРИ, а
        # не один: `AreaReinforcement.Create` проверяет КАЖДЫЙ из трёх
        # аргументов на свой класс отдельно и бросает ArgumentException на
        # чужом id, то есть общий «пул арматурных типов» заменил бы
        # типизированный отказ рантайм-исключением внутри транзакции. Все три
        # собираются OfClass — категорийный сборщик здесь неверен по существу
        # ровно как у заливки: OST_Rebar держит и стержни, и их типы, а
        # OST_AreaRein — и системы, и типы. Число переснято
        # `len(required_grounding_pools())` на ЭТОМ дереве.
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
        # Правило прежнее — «версионно-хрупкое имя не упоминать», — но
        # держится оно теперь ЗАКРЫТЫМ СПИСКОМ С ЗАМЕРАМИ, а не голой
        # подстрокой: та краснела на законном `WorksetId.IntegerValue`
        # (собирается на всех шести) вместе с опасным `ElementId.IntegerValue`
        # (отказ на 2026, CS1061). Подробности и оба замера — в
        # `open_model_guard.INTEGER_VALUE_EXCEPTIONS`.
        from kukai.ir.tests.open_model_guard import integer_value_offenders
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
        from kukai.ir import spec
        from kukai.ir.gate_runner import model_binding_guard_inputs
        # The gate's own `auth_wall`, not this module's `_wall_program`:
        # the latter pins a wall `type`, which demands an exact
        # `wall_types` pool the guard profile never stamps, and would
        # refuse for a reason that has nothing to do with the pair. A test
        # of the harness must compile what the harness compiles.
        from kukai.ir.tests.test_authoring import _prog, _wall

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
        from kukai.ir.gate_runner import model_binding_guard_inputs

        snapshot, profile, _ = model_binding_guard_inputs()

        recomputed = OpenModelProfile.from_ground_snapshot(
            snapshot,
            revision_proof=profile.revision_proof,
            required_pools=profile.required_pools,
        )

        self.assertEqual(recomputed.digest, profile.digest)


if __name__ == "__main__":
    unittest.main()
