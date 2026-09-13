"""The product layer of the report: the `clash-review/2` contract.

This layer is DERIVED from `clash-report/3` by a pure function and is
versioned separately — proof and presentation live on different
tracks. The tests hold exactly this boundary: the canon must not
depend on status, and the presentation must not promise more than the
detector proved.
"""
from __future__ import annotations

import copy

import pytest

from kir.clash import detect as D
from kir.clash import geom as G
from kir.clash import hulls as H
from kir.clash import review as R
from kir.clash import snapshot as S


def _rep(els):
    return D.detect(S.build_from_elements(els, origin={"run_dir": "t"}),
                    pair_filter=D.any_physical_pair_filter)


TWO_WALLS = [{"element_id": "1", "category": "OST_Walls",
              "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
             {"element_id": "2", "category": "OST_Walls",
              "bbox_min_mm": [100, 0, 0], "bbox_max_mm": [5000, 200, 3000]}]


def _exact_record(element_id: str, x0: float = 0.0) -> H.HullRecord:
    hull = G.Prism(
        ((x0, 0.0), (x0 + 10.0, 0.0),
         (x0 + 10.0, 10.0), (x0, 10.0)), 0.0, 10.0)
    inner = H.certify_analytic_inner_for_test(
        inner=hull, body=hull, outer=hull,
        subject_source_id=element_id,
        body_source_digest=H.analytic_hull_digest(hull),
        body_source_revision=f"fixture:{element_id}:body-r1")
    return H.HullRecord(
        source_id=element_id, category="OST_Floors", label="floor",
        mvp_side="struct", hull=hull, grade="exact",
        hull_source="analytic_exact_fixture", inner=inner)


def _report_with_finding(finding: dict) -> dict:
    report = _rep(TWO_WALLS)
    report["findings"] = [finding]
    return report


def test_review_is_derived_and_does_not_touch_the_canon():
    """The canon must remain byte-for-byte the same after building the
    review."""
    rep = _rep(TWO_WALLS)
    before = D.dumps(rep)
    R.build_review(rep)
    assert D.dumps(rep) == before, "обзор изменил доказательство"


def test_status_is_reserved_but_empty():
    """The "discussed → closed" cycle hasn't arrived yet, but the schema
    IS WAITING for it."""
    v = R.build_review(_rep(TWO_WALLS))
    st = v["top_findings"][0]["status"]
    assert st["state"] == "open"
    assert st["changed_by"] is None and st["changed_at"] is None
    assert v["schema_version"] == "clash-review/2"
    assert v["status_vocabulary"] == ["open", "discussed", "dismissed", "fixed"]


def test_a_coarse_pair_never_gets_the_top_severity():
    """A coarse pair does NOT prove that the bodies penetrate. Promising
    the designer «критично» on something unproven is the same Goodhart
    as `exact` on a capsule."""
    els = [{"element_id": "1", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
           {"element_id": "2", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 199, 3000]}]
    v = R.build_review(_rep(els))
    for row in v["top_findings"]:
        if row["hull_grade"] == "coarse" and row["pair_kind"] == "interference":
            assert row["severity"] in ("средняя", "низкая"), row


def test_conservative_equal_axes_remain_a_possible_duplicate_to_verify():
    """Equal conservative axes are not exact-body equality authority."""
    els = [{"element_id": "1", "category": "OST_PipeCurves",
            "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0],
            "section_radius_mm": 100.0, "section_round": True,
            "bbox_min_mm": [-100, -100, -100], "bbox_max_mm": [5100, 100, 100]},
           {"element_id": "2", "category": "OST_PipeCurves",
            "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0],
            "section_radius_mm": 100.0, "section_round": True,
            "bbox_min_mm": [-100, -100, -100], "bbox_max_mm": [5100, 100, 100]}]
    v = R.build_review(_rep(els))
    row = v["top_findings"][0]
    assert row["pair_kind"] == "coincident_duplicate"
    assert row["evidence_state"] == "possible"
    assert row["impact_severity"] == "unknown"
    assert row["severity"] == "средняя"
    assert row["actionability"] == "verify"
    assert row["verification_required"] is True
    assert "удал" not in row["text"].lower()
    assert v["summary"]["duplicates"] == 1
    assert v["summary"]["duplicates_possible"] == 1


def test_sealed_exact_duplicate_is_critical_but_not_delete_actionable():
    finding = D.evaluate(_exact_record("a"), _exact_record("b"))
    assert finding is not None
    v = R.build_review(_report_with_finding(finding.as_dict()))
    row = v["top_findings"][0]
    assert row["evidence_state"] == "confirmed"
    assert row["impact_severity"] == "critical"
    assert row["severity"] == "критично"
    assert row["duplicate_equality_proven"] is True
    assert row["actionability"] == "verify"
    assert row["verification_required"] is True
    assert row["deletion_safe"] is False
    assert row["deletion_blockers"] == [
        "semantic_equivalence_unproven",
        "dependency_equivalence_unproven",
    ]
    assert "автоматически удалять нельзя" in row["text"].lower()
    assert v["summary"]["duplicates_confirmed"] == 1
    assert v["summary"]["duplicates_geometry_confirmed"] == 1
    assert v["summary"]["duplicates_delete_safe"] == 0


def test_exact_geometry_does_not_prove_phase_or_dependency_equivalence():
    finding = D.evaluate(_exact_record("a"), _exact_record("b"))
    assert finding is not None
    wire = finding.as_dict()
    # These are deliberately not part of the geometric proof.  Their very
    # absence from that contract is why the review layer cannot authorize a
    # destructive BIM operation.
    wire["a"]["phase_created"] = "Existing"
    wire["b"]["phase_created"] = "New Construction"
    row = R.build_review(_report_with_finding(wire))["top_findings"][0]
    assert row["duplicate_equality_proven"] is True
    assert row["actionability"] == "verify"
    assert row["verification_required"] is True
    assert row["deletion_safe"] is False
    assert "автоматически удалять нельзя" in row["text"].lower()


def test_tampered_duplicate_proof_cannot_leave_delete_wording():
    finding = D.evaluate(_exact_record("a"), _exact_record("b"))
    assert finding is not None
    tampered = copy.deepcopy(finding.as_dict())
    tampered["exact_body_equality_proof"]["equality_integrity_tag"] = "0" * 64
    v = R.build_review(_report_with_finding(tampered))
    row = v["top_findings"][0]
    assert row["evidence_state"] == "confirmed"
    assert row["duplicate_equality_proven"] is False
    assert row["actionability"] == "verify"
    assert row["verification_required"] is True
    assert "удал" not in row["text"].lower()
    assert v["summary"]["duplicates_confirmed"] == 0
    assert v["summary"]["duplicates_possible"] == 1


def test_confirmed_nonduplicate_is_repair_actionable_with_factual_wording():
    finding = D.evaluate(_exact_record("a", 0.0), _exact_record("b", 5.0))
    assert finding is not None
    v = R.build_review(_report_with_finding(finding.as_dict()))
    row = v["top_findings"][0]
    assert row["pair_kind"] == "interference"
    assert row["evidence_state"] == "confirmed"
    assert row["actionability"] == "repair"
    assert row["verification_required"] is False
    assert "пересечение тел" in row["text"].lower()
    assert "возмож" not in row["text"].lower()
    assert v["summary"]["overlaps_confirmed"] == 1
    assert v["summary"]["overlaps_possible"] == 0


def test_possible_wording_and_axes_never_claim_a_fact_or_repair():
    v = R.build_review(_rep(TWO_WALLS))
    row = v["top_findings"][0]
    assert row["evidence_state"] == "possible"
    assert row["impact_severity"] == "unknown"
    assert row["actionability"] == "verify"
    assert row["verification_required"] is True
    assert row["severity"] not in ("критично", "высокая")
    assert "внешн" in row["text"].lower()
    assert "возмож" in row["text"].lower()
    assert "требуется проверка" in row["text"].lower()
    assert "требуется исправление" not in row["text"].lower()
    assert v["summary"]["confirmed"] == 0
    assert v["summary"]["possible"] == 1
    assert v["summary"]["by_evidence_state"] == {
        "confirmed": 0, "possible": 1}
    assert v["summary"]["by_actionability"]["verify"] == 1


def test_a_bbox_only_duplicate_never_tells_you_to_delete():
    """A wall is banned from having an axis (review #2), its hull is a
    bounding box. Coinciding boxes remain the best guess at a duplicate,
    but we have NO PROOF that the bodies coincide: two diagonals of a
    square give exactly the same box. So the line must not carry a
    destructive instruction.
    """
    els = [{"element_id": "1", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
           {"element_id": "2", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]}]
    v = R.build_review(_rep(els))
    row = v["top_findings"][0]
    assert row["pair_kind"] == "coincident_duplicate"
    assert row["severity"] == "средняя"
    assert row["evidence_state"] == "possible"
    assert row["actionability"] == "verify"
    assert row["verification_required"] is True
    assert v["summary"]["duplicates"] == 1
    assert "удал" not in row["text"].lower(), row["text"]
    assert "внешн" in row["text"].lower(), row["text"]
    assert "провер" in row["text"].lower(), row["text"]


def test_the_summary_hint_does_not_promise_deletion_for_every_duplicate():
    """The same law at the summary level: "duplicates are fixed by
    deletion" was standing over a counter that also catches unproven
    pairs."""
    els = [{"element_id": "1", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
           {"element_id": "2", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]}]
    hint = R.build_review(_rep(els))["summary"]["duplicates_hint"]
    assert "удален" in hint.lower() and "провер" in hint.lower(), hint


def test_no_row_ever_orders_a_deletion_without_the_proof():
    """A law, not an example: a destructive instruction is allowed ONLY
    where the detector has proven that the bodies coincide. The scene is
    deliberately mixed — proven duplicates, unproven ones, diagonals,
    and ordinary intersections all at once."""
    def pipe(eid, p0, p1, r=100.0):
        xs, ys, zs = (p0[0], p1[0]), (p0[1], p1[1]), (p0[2], p1[2])
        return {"element_id": eid, "category": "OST_PipeCurves",
                "p0_mm": list(p0), "p1_mm": list(p1),
                "section_radius_mm": r, "section_round": True,
                "bbox_min_mm": [min(xs) - r, min(ys) - r, min(zs) - r],
                "bbox_max_mm": [max(xs) + r, max(ys) + r, max(zs) + r]}

    els = [pipe("1", (0, 0, 0), (5000, 0, 0)),          # a proven duplicate…
           pipe("2", (0, 0, 0), (5000, 0, 0)),          # …the other half of the pair
           pipe("3", (0, 8000, 0), (4000, 12000, 0), 200.0),   # diagonals
           pipe("4", (4000, 8000, 0), (0, 12000, 0), 200.0),
           {"element_id": "5", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
           {"element_id": "6", "category": "OST_Walls",   # a box-based duplicate
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
           {"element_id": "7", "category": "OST_Walls",   # an ordinary intersection
            "bbox_min_mm": [100, 0, 0], "bbox_max_mm": [5000, 200, 3000]}]
    rep = _rep(els)
    by_id = {f["finding_id"]: f for f in rep["findings"]}
    v = R.build_review(rep)
    assert len(v["top_findings"]) == len(by_id) > 5, "сцена обеднела"
    for row in v["top_findings"]:
        if "удал" in row["text"].lower():
            assert D.duplicate_claim_is_proven(by_id[row["finding_id"]]), row
    assert all(r["actionability"] == "verify" for r in v["top_findings"])
    assert all(r["evidence_state"] == "possible" for r in v["top_findings"])


def test_every_row_carries_both_element_ids_for_the_frontend():
    els = [{"element_id": "10", "category": "OST_CableTray",
            "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
            "params": {"RBS_CABLETRAY_WIDTH_PARAM": 200.0,
                       "RBS_CABLETRAY_HEIGHT_PARAM": 100.0},
            "bbox_min_mm": [-10, -110, -60], "bbox_max_mm": [1010, 110, 60]},
           {"element_id": "20", "category": "OST_Walls",
            "bbox_min_mm": [400, -200, -200], "bbox_max_mm": [600, 200, 200]}]
    v = R.build_review(_rep(els))
    assert v["top_findings"], "лоток сквозь стену не найден"
    for row in v["top_findings"]:
        assert row["a_element_id"] and row["b_element_id"]
    assert "Лоток 10" in v["top_findings"][0]["text"]


def test_grouping_is_by_element_because_that_is_what_is_worked_on():
    """The designer works with an ELEMENT, not a pair: an element
    carries a list of ITS OWN conflicts, and both sides of a pair end up
    in the grouping."""
    els = TWO_WALLS + [{"element_id": "3", "category": "OST_Walls",
                        "bbox_min_mm": [200, 0, 0],
                        "bbox_max_mm": [5000, 200, 3000]}]
    v = R.build_review(_rep(els))
    by_id = {e["element_id"]: e for e in v["elements"]}
    assert set(by_id) == {"1", "2", "3"}
    assert by_id["1"]["conflict_total"] == 2
    assert all(c["with_element_id"] != "1" for c in by_id["1"]["conflicts"])


def test_incomplete_search_is_shouted_not_whispered():
    """A report with invisible elements must not look exhaustive."""
    els = [{"element_id": "w", "category": "OST_Walls",
            "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0], "params": {}},
           {"element_id": "p", "category": "OST_PipeCurves",
            "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
            "params": {"RBS_PIPE_OUTER_DIAMETER": 114.3},
            "bbox_min_mm": [-58, -58, -58], "bbox_max_mm": [1058, 58, 58]}]
    v = R.build_review(_rep(els))
    assert v["summary"]["search_complete"] is False
    assert v["summary"]["search_completeness_contract_valid"] is True
    assert "неполон" in v["summary"]["search_incomplete_note"]
    assert "ВНИМАНИЕ" in R.to_markdown(v)


def test_missing_completeness_contract_fails_closed_instead_of_default_true():
    report = _rep(TWO_WALLS)
    report["search"].pop("completeness")
    v = R.build_review(report)
    assert v["summary"]["search_complete"] is False
    assert v["summary"]["search_completeness_contract_valid"] is False
    assert "контракт" in v["summary"]["search_incomplete_note"].lower()
    assert "нельзя считать полным" in v["summary"][
        "search_incomplete_note"].lower()


def test_labels_are_class_names_not_family_names():
    """The dictionary is closed to the classes of `KIND_TABLE`. There
    are no type or family names in it, and there cannot be — this is
    the operator's ban, not a matter of style."""
    from kir.clash import hulls as H
    labels = {v.label for v in H.KIND_TABLE.values() if v.eligible and v.label}
    missing = sorted(l for l in labels if l not in R.LABEL_RU)
    assert not missing, f"пригодные классы без русского имени: {missing}"
    assert not any("НР_" in v or "_ВТ_" in v for v in R.LABEL_RU.values()), (
        "в словаре имя типа/семейства — это хардкод под одну модель")
