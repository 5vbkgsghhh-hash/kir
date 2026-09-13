"""A mass has geometry, but its category cannot authorize a BIM intervention.

Production hull construction and the real detector produce every finding below.
The additional certified cases use the existing analytic test-body issuer, not
fabricated finding dictionaries and not a claim about native Revit extraction.
Even proven overlap of the fixture bodies cannot supply the missing purpose.
"""
from dataclasses import replace

import pytest

from kir import clash_judgement as J
from kir.clash import detect as D, geom as G, hulls as H, snapshot as S


def snapshot(other_category, *, certified=False):
    elements = [
        {"element_id": "mass-a", "category": "OST_Mass", "level_id": "L0",
         "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [1000, 1000, 1000]},
        {"element_id": "other-b", "category": other_category, "level_id": "L0",
         "bbox_min_mm": [500, 0, 0], "bbox_max_mm": [1500, 1000, 1000]},
    ]
    found = S.build_from_elements(elements, origin={"fixture": "mass-purpose-not-known"})
    assert len(found.records) == 2 and found.refusals == []
    if not certified:
        return found
    records = []
    for record, start in zip(found.records, (0.0, 500.0)):
        # Fully specified prismatic fixture bodies; the category is an input to
        # role classification, not proof of a native family's physical profile.
        body = G.Prism(((start, 0.0), (start + 1000.0, 0.0),
                        (start + 1000.0, 1000.0), (start, 1000.0)), 0.0, 1000.0)
        inner = H.certify_analytic_inner_for_test(
            inner=body, body=body, outer=body, subject_source_id=record.source_id,
            body_source_digest=H.analytic_hull_digest(body),
            body_source_revision="fixture-body-v1:" + record.source_id)
        records.append(replace(record, hull=body, grade="exact",
                               hull_source="analytic_test_body", inner=inner))
    return S.ClashGeometrySnapshot(records=records, census=found.census,
                                   origin=found.origin, refusals=found.refusals, hosted=found.hosted)


def judged(other_category, *, certified=False):
    source = snapshot(other_category, certified=certified)
    found = D.search(source, pair_filter=D.any_physical_pair_filter)
    assert len(found.findings) == 1
    finding = found.findings[0]
    assert finding.hull_relation == "overlap" and finding.hull_overlap_depth_mm > 0
    result = J.judge([finding.as_dict()], hulls={r.source_id: r for r in source.records},
                     hosted=source.hosted)
    return source, found, result


@pytest.mark.parametrize("other_category", ["OST_Walls", "OST_PipeCurves", "OST_Mass"])
@pytest.mark.parametrize("certified", [False, True])
def test_mass_pairs_are_retained_without_an_invented_purpose_or_repair(other_category, certified):
    source, found, result = judged(other_category, certified=certified)
    assert J.role_of("mass") == "opaque"
    assert all(record.mvp_side is None for record in source.records if record.label == "mass")
    assert len(result.judged) == len(found.findings) == 1
    row = result.judged[0]
    assert row.finding_id == found.findings[0].finding_id
    assert row.kind == row.rule_id == "unclassified"
    assert row.rung not in {"agree", "fix"}
    assert "create_opening" not in row.next_move_ru
    assert "сдвинуть" not in row.next_move_ru
    assert row.as_dict()["a_label"] == "mass"
    if certified:
        assert found.findings[0].verdict == "confirmed"
        assert row.proven is True  # lack of geometry proof is not what prevents the intervention
    else:
        assert found.findings[0].verdict == "possible"
        assert row.proven is not True


@pytest.mark.parametrize("wrong_role,expected_rule", [("envelope", "run_through_envelope"),
                                                     ("bearing", "run_through_bearing")])
def test_giving_mass_a_structural_role_wrongly_authorizes_an_intervention(monkeypatch, wrong_role, expected_rule):
    # A control for the semantic boundary: with the wrong role, the same proven
    # overlap really does become an opening or a separating-move recommendation.
    monkeypatch.setitem(J.ROLE_BY_LABEL, "mass", wrong_role)
    _, _, result = judged("OST_PipeCurves", certified=True)
    row = result.judged[0]
    assert row.proven is True and row.rule_id == expected_rule
    if wrong_role == "envelope":
        assert "create_opening" in row.next_move_ru
    else:
        assert row.rung == "fix" and "сдвинуть" in row.next_move_ru


@pytest.mark.parametrize("other_category", ["OST_Walls", "OST_PipeCurves", "OST_Mass"])
def test_a_move_budget_does_not_supply_the_missing_mass_purpose(monkeypatch, other_category):
    from kir.clash import resolve

    def forbidden(*args, **kwargs):
        raise AssertionError("an opaque mass must not be sent to the automatic move solver")

    monkeypatch.setattr(resolve, "propose", forbidden)
    source = snapshot(other_category, certified=True)
    found = D.search(source, pair_filter=D.any_physical_pair_filter)
    result = J.judge([row.as_dict() for row in found.findings],
                     hulls={row.source_id: row for row in source.records},
                     hosted=source.hosted, propose_budget_ms=50.0)
    assert len(result.judged) == 1 and result.judged[0].proven is True
    assert result.judged[0].kind == "unclassified"
    assert result.proposals["computed"] == 0
    assert result.proposals["refused"] == 0
