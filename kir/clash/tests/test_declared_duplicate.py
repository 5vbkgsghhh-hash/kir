"""A DECLARATION DUPLICATE: a fact about the PROGRAM'S TEXT, not about bodies.

THE MEASUREMENT THIS FILE COMES FROM (2026-08-11). Clash cannot say "fix"
about anything: the top stage requires `proven is True`, which requires a
certified internal overlap, and the certificate is unreachable TWICE OVER
(there is no production emitter; the proof kernel does not handle bodies of
revolution — see `test_declared_section_certificate.py`). The same ban
covered duplicates a third time, in its own words in
`exact_body_equality_proof`: "Ordinary production producers currently emit
no exact grade, so destructive duplicate advice remains unreachable there".

BUT FOR A DUPLICATE, THIS BAN ANSWERS THE WRONG QUESTION. A geometric
coincidence of hulls is a hypothesis about bodies, and caution there is
legitimate. But "the same element DECLARED TWICE" is a fact about TEXT: the
program said the same thing twice. There is no hull in this fact at all,
nothing to coarsen, and nothing for the proof kernel to do. Measured: two
identical operations in a batch give two elements that agree byte-for-byte
in EVERYTHING except the address (`p1/duct1` versus `p2/duct1`).

THAT IS WHY THIS IS THE CHEAPEST OF THE THREE ROADS AND THE ONLY ONE THAT
DOES NOT RUN INTO THE KERNEL. And it is also the one that builds the
machinery both others need: a second kind of evidence whose provenance is a
DECLARATION, not a body.

WHAT THIS FILE DOES NOT COVER, named by name:
  * it says nothing about the BUILT building: two identical declarations
    might build into one element or into two — that is a fact about the
    program, and the receipt names its provenance right in the finding;
  * it does not decide whether two operations of a different kind that
    produce the same geometry are SEMANTICALLY equivalent: the whole
    declaration is compared, and different text is not a duplicate, even if
    the bodies coincide;
  * it does not cover duplicates that something REFERENCES: deleting
    something that serves as support for another op is not allowed, and
    such a pair stays on `look` with a named reason.
"""
from __future__ import annotations

from kir import clash_bundle as CB


def _duct(oid: str = "duct1", *, y_mm: float = 0.0,
          diameter_mm: float = 400.0) -> dict:
    return {"op": "create_duct", "id": oid,
            "p0_mm": [0.0, y_mm, 2700.0], "p1_mm": [5000.0, y_mm, 2700.0],
            "level": {"by": "name", "value": "Этаж 1"},
            "diameter_mm": diameter_mm}


def _pack(*programs: list[dict]) -> list[dict]:
    return [{"ops": list(ops)} for ops in programs]


def test_two_identical_declarations_carry_the_same_declaration_digest():
    """THE MAIN COUNTEREXAMPLE: before the fix, an element carried NO
    declaration fingerprint at all, and "the same thing said twice" was
    inexpressible."""
    geometry = CB.bundle_elements(_pack([_duct()], [_duct()]), snapshot=None)
    a, b = geometry.elements
    assert a["element_id"] != b["element_id"]
    assert a.get("declaration_digest"), a
    assert a["declaration_digest"] == b["declaration_digest"], (
        "два одинаковых объявления получили разные отпечатки")


def test_the_address_is_not_part_of_the_declaration():
    """A batch address (`p1/duct1`) is OUR bookkeeping, not something the
    author said. Were it part of the fingerprint, a duplicate would become
    impossible by construction."""
    geometry = CB.bundle_elements(_pack([_duct("a")], [_duct("b")]),
                                  snapshot=None)
    a, b = geometry.elements
    assert a["element_id"] != b["element_id"]
    assert a["declaration_digest"] == b["declaration_digest"]


def test_a_different_declaration_is_not_a_duplicate():
    """The flip side, without which the first test would be green even for
    a constant fingerprint."""
    geometry = CB.bundle_elements(
        _pack([_duct()], [_duct(diameter_mm=300.0)]), snapshot=None)
    a, b = geometry.elements
    assert a["declaration_digest"] != b["declaration_digest"]

    geometry = CB.bundle_elements(
        _pack([_duct()], [_duct(y_mm=1500.0)]), snapshot=None)
    a, b = geometry.elements
    assert a["declaration_digest"] != b["declaration_digest"]


def test_declared_duplicates_are_reported_as_certain_with_their_provenance():
    """RULING 3, applied to the declaration: the provenance travels IN THE
    FINDING.

    "Fix" based on a fact about text and "fix" based on a Revit measurement
    are different claims, and they would otherwise share one stage.
    """
    report = CB.declared_duplicates(
        CB.bundle_elements(_pack([_duct()], [_duct()]), snapshot=None))
    assert len(report) == 1, report
    row = report[0]
    assert set(row["pair"]) == {"p1/duct1", "p2/duct1"}
    assert row["certain"] is True
    assert row["provenance"] == CB.DECLARATION_PROVENANCE
    assert "объявлен" in row["text_ru"].lower()


def test_a_referenced_declaration_is_refused_BY_NAME():
    """Deleting something that serves as SUPPORT for another op is not
    allowed: the duplicate has an external dependency, and the pair
    remains non-destructive with a named reason.

    A default of zero here would be a lie told with a number: "there are
    no references" and "references were not counted" are different claims.
    """
    duct = _duct()
    referrer = {"op": "create_duct", "id": "branch",
                "p0_mm": [2500.0, 0.0, 2700.0], "p1_mm": [2500.0, 3000.0, 2700.0],
                "level": {"by": "ref", "value": "duct1"},
                "diameter_mm": 200.0}
    report = CB.declared_duplicates(CB.bundle_elements(
        _pack([duct, referrer], [_duct()]), snapshot=None))
    assert len(report) == 1, report
    row = report[0]
    assert row["certain"] is False
    assert row["refused"] == "declaration_is_referenced"


def test_a_single_declaration_produces_nothing():
    """An instrument that finds a duplicate in a single declaration is useless."""
    assert CB.declared_duplicates(
        CB.bundle_elements(_pack([_duct()]), snapshot=None)) == []
