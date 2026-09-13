"""ClashGeometrySnapshot — the detector's input, not "the program plus
ground".

Review P0 #1: as long as the input is called "KIR + the existing ground",
it is unclear exactly what is being judged and what has been left out of
frame. The snapshot answers this explicitly — it carries (a) hulls, (b)
counters of the uncovered, (c) a fingerprint of provenance, and its census
must reconcile:

    eligible = hulled + unsupported + missing_geometry

A discrepancy is not a warning but an error: a detector for which half the
building has silently dropped out will find zero clashes and will look
sound.
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import pathlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from kir.clash import geom as G
from kir.clash import hulls as H

SCHEMA_VERSION = "clash-geometry-snapshot/2"


class SnapshotIntegrityError(RuntimeError):
    """The input is unprovable: the census does not reconcile, the stream
    is truncated, ids are duplicated.

    Review #10/#11: both used to be silent. A file truncated at a VALID
    json line was giving an internally-reconciling census — "everything is
    fine" for half the building. A detector for which half the model has
    silently dropped out will find zero clashes and will look sound, which
    is why this is an exception, not a warning.
    """


FEDERATION_COVERAGE_SCHEMA = "clash-federation-coverage/1"


def _sha256_json(value: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SnapshotIntegrityError(
            "federation coverage is not canonical JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def _typed_string_list(value: Any, name: str) -> list[str]:
    if (not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or value != sorted(value)
            or len(value) != len(set(value))):
        raise SnapshotIntegrityError(
            f"federation coverage {name} must be sorted unique strings")
    return value


def _federation_coverage_axis(
    coverage: Any,
    *,
    records: Iterable[H.HullRecord],
    refusals: Iterable[H.Refusal],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the sealed graph/hull accounting before exposing green axes."""

    if not isinstance(coverage, Mapping):
        raise SnapshotIntegrityError(
            "origin.federation_coverage must be an object")
    wire = dict(coverage)
    digest = wire.pop("content_digest", None)
    if (not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or _sha256_json(wire) != digest):
        raise SnapshotIntegrityError(
            "federation coverage content digest mismatch")
    required = {
        "schema_version", "federation_root", "graph_content_digest",
        "hull_set_content_digest", "scope_id", "scope_occurrences",
        "hulled_occurrences", "geometry_refusal_occurrences",
        "scope_census", "graph_complete", "complete", "graph_gaps",
        "node_refusals", "graph_refusals", "source_row_refusals",
        "incomplete_link_resolutions", "geometry_transform_gaps",
    }
    if set(wire) != required:
        raise SnapshotIntegrityError(
            "federation coverage has an unsupported field set")
    if wire["schema_version"] != FEDERATION_COVERAGE_SCHEMA:
        raise SnapshotIntegrityError(
            "unsupported federation coverage schema")
    for name in ("federation_root", "scope_id"):
        if not isinstance(wire[name], str) or not wire[name]:
            raise SnapshotIntegrityError(
                f"federation coverage {name} must be non-empty")
    for name in ("graph_content_digest", "hull_set_content_digest"):
        value = wire[name]
        if (not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)):
            raise SnapshotIntegrityError(
                f"federation coverage {name} must be sha256")
    scope = _typed_string_list(
        wire["scope_occurrences"], "scope_occurrences")
    hulled = _typed_string_list(
        wire["hulled_occurrences"], "hulled_occurrences")
    refused_occurrences = _typed_string_list(
        wire["geometry_refusal_occurrences"],
        "geometry_refusal_occurrences")
    if set(hulled).intersection(refused_occurrences) \
            or set(scope) != set(hulled).union(refused_occurrences):
        raise SnapshotIntegrityError(
            "federation scope is not exactly hull-or-refusal accounted")
    census = wire["scope_census"]
    if not isinstance(census, Mapping) or set(census) != {
            "occurrences", "hulled", "refused"}:
        raise SnapshotIntegrityError(
            "federation coverage scope_census is malformed")
    for name, expected in (
        ("occurrences", len(scope)),
        ("hulled", len(hulled)),
        ("refused", len(refused_occurrences)),
    ):
        value = census[name]
        if (isinstance(value, bool) or not isinstance(value, int)
                or value < 0 or value != expected):
            raise SnapshotIntegrityError(
                "federation coverage scope census does not balance")

    list_fields = (
        "graph_gaps", "node_refusals", "graph_refusals",
        "source_row_refusals", "incomplete_link_resolutions",
        "geometry_transform_gaps",
    )
    for name in list_fields:
        if not isinstance(wire[name], list):
            raise SnapshotIntegrityError(
                f"federation coverage {name} must be an array")
    graph_complete = not any(wire[name] for name in list_fields[:-1])
    if (not isinstance(wire["graph_complete"], bool)
            or wire["graph_complete"] != graph_complete):
        raise SnapshotIntegrityError(
            "federation graph completeness contradicts named gaps")
    complete = graph_complete and not wire["geometry_transform_gaps"]
    if not isinstance(wire["complete"], bool) or wire["complete"] != complete:
        raise SnapshotIntegrityError(
            "federation completeness contradicts named gaps")

    actual_records = sorted(record.source_id for record in records)
    if actual_records != hulled:
        raise SnapshotIntegrityError(
            "federation coverage hulled occurrences differ from snapshot")
    expected_refusals: dict[str, tuple[str, str]] = {}
    keyed_gap_occurrences: list[str] = []
    for index, row in enumerate(wire["geometry_transform_gaps"]):
        if not isinstance(row, Mapping) or set(row) != {
                "snapshot_refusal_id", "gap"}:
            raise SnapshotIntegrityError(
                "federation geometry gap row is malformed")
        refusal_id = row["snapshot_refusal_id"]
        gap = row["gap"]
        if (not isinstance(refusal_id, str) or not refusal_id
                or refusal_id in expected_refusals
                or not isinstance(gap, Mapping)):
            raise SnapshotIntegrityError(
                "federation geometry gap refusal identity is invalid")
        category = gap.get("category")
        reason = gap.get("reason")
        occurrence = gap.get("occurrence_key")
        if (not isinstance(category, str) or not category
                or not isinstance(reason, str) or not reason):
            raise SnapshotIntegrityError(
                "federation geometry gap lost category or reason")
        if occurrence is not None:
            if not isinstance(occurrence, str) or not occurrence:
                raise SnapshotIntegrityError(
                    "federation geometry gap occurrence key is invalid")
            keyed_gap_occurrences.append(occurrence)
        expected_refusals[refusal_id] = (
            category, f"federation:{reason}")
    if sorted(keyed_gap_occurrences) != refused_occurrences:
        raise SnapshotIntegrityError(
            "federation coverage keyed geometry refusals disagree")
    actual_refusals: dict[str, tuple[str, str]] = {}
    for refusal in refusals:
        if refusal.source_id in actual_refusals:
            raise SnapshotIntegrityError(
                "federation snapshot has duplicate refusal identities")
        if refusal.bucket != "missing_geometry":
            raise SnapshotIntegrityError(
                "federation geometry gaps must stay missing_geometry refusals")
        actual_refusals[refusal.source_id] = (
            refusal.category, refusal.reason)
    if actual_refusals != expected_refusals:
        raise SnapshotIntegrityError(
            "federation geometry gaps differ from snapshot refusals")

    extraction_complete = not any(wire[name] for name in (
        "node_refusals", "graph_refusals", "source_row_refusals"))
    extraction_axis = {
        "complete": extraction_complete,
        "graph_refusals": wire["graph_refusals"],
        "node_refusals": wire["node_refusals"],
        "source_row_refusals": wire["source_row_refusals"],
        "note": (
            "complete only when every source graph and node entering the "
            "federation has an authoritative occurrence address"),
    }
    federation_axis = {
        **wire,
        "content_digest": digest,
        "note": (
            "complete only when graph assembly, expected links, occurrence "
            "scope accounting, and source-to-root geometry transforms have "
            "no named gaps"),
    }
    return extraction_axis, federation_axis


@dataclass
class Census:
    """Counters by class. All four are always published, zeros included."""
    eligible: collections.Counter = field(default_factory=collections.Counter)
    hulled: collections.Counter = field(default_factory=collections.Counter)
    unsupported: collections.Counter = field(default_factory=collections.Counter)
    missing_geometry: collections.Counter = field(default_factory=collections.Counter)
    not_eligible: collections.Counter = field(default_factory=collections.Counter)
    reasons: collections.Counter = field(default_factory=collections.Counter)
    #: Review #10. A live measurement of the facade: header census =
    #: 30 489 elements, while the element rows in L0 number 3 153. The
    #: difference is not required to be eligible for the search, but it
    #: must be NAMED: otherwise the denominator of any percentage is
    #: unproven.
    outside_extraction_scope: int = 0
    #: ELEMENTS of linked files that did not receive a hull. The sum of
    #: `element_count` over `link` rows, NOT the number of the rows
    #: themselves.
    #:
    #: BEFORE 11.08.2026 THE NUMBER OF LINKS WAS STORED HERE. The name said
    #: "elements", the code was assigning `origin["links_in_l0"]`, and a
    #: model with three links of forty thousand elements each was reporting
    #: a three — the quantity was declared in one place, read in another,
    #: and nothing forced them to agree. The real number, meanwhile, had
    #: been MEASURED and discarded, right next to it in a row: the
    #: extractor puts the link's `element_count` from `GetLinkDocument()`
    #: into the row, and the reader was not opening the row at all.
    linked_elements_unscored: int = 0
    #: Links for which the element counts COULD NOT BE READ (the file is
    #: not loaded — `GetLinkDocument()` is empty, `element_count` stays
    #: `null`).
    #:
    #: A SEPARATE NUMBER, NOT A ZERO IN THE SUM. "The link has zero
    #: elements" and "the link's element count was not read" are different
    #: assertions; adding them together means replacing one lie with
    #: another, by exactly the same trick the counter above was lying with
    #: until today.
    links_without_element_count: int = 0
    #: ── sections (wave D2-A). The denominator is the `eligible` count of
    #: those categories for which the `axis_section` source is ALLOWED.
    #: Walls are not included here: they have the number but not the
    #: permission, and adding one to the other would mean hiding a
    #: prohibition behind an absence of data.
    section_present: collections.Counter = field(default_factory=collections.Counter)
    section_absent: collections.Counter = field(default_factory=collections.Counter)
    #: How many hulls were ACTUALLY built by section. Always `<= present`:
    #: the difference is elements with a number but an unusable axis (zero
    #: length, a broken arc), and it is already named in
    #: `reasons`/`downgraded_from`.
    section_hulled: collections.Counter = field(default_factory=collections.Counter)
    #: Elements for which the section number IS PRESENT in L0, but the
    #: table forbids using it (a wall, a beam, a column, a flexible run —
    #: review #2/#3/#10). On the SOB6.2 facade this is the wave's headline
    #: number: the section is read, there is no uplift, and the reason is a
    #: PROHIBITION, not an absence of data.
    section_blocked: collections.Counter = field(default_factory=collections.Counter)
    #: R3 of the red findings: only the NOMINAL diameter was read for the
    #: element. A capsule built from it does not contain the body (DN100:
    #: 50.0 against an outer diameter of 57.15), so the hull becomes the
    #: bounding box. The number must be NAMED: without it, "few capsules"
    #: is indistinguishable from "few pipes".
    section_nominal_only: collections.Counter = field(
        default_factory=collections.Counter)
    #: R5 of the red findings: elements on the MVP side that ended up
    #: WITHOUT a hull. A wall that is not in the search is a guaranteed
    #: miss of everything that passes through it; a report with 783
    #: invisible elements was looking sound.
    no_hull_mvp_side: collections.Counter = field(
        default_factory=collections.Counter)
    #: Coverage on the MVP side: how much is eligible and how much actually
    #: got a hull.
    mvp_eligible: collections.Counter = field(default_factory=collections.Counter)
    mvp_hulled: collections.Counter = field(default_factory=collections.Counter)
    #: The same hull-less elements, but by CATEGORY — so that "the search
    #: is incomplete" names the culprit, not just a number.
    no_hull_by_category: collections.Counter = field(
        default_factory=collections.Counter)
    #: DEGENERATE hulls: a body of zero volume (`hulls.hull_degeneracy`). A
    #: zero-volume hull cannot prove a clash — its pairs mean nothing — but
    #: neither is it a violation of the law of containment, as long as the
    #: data has no independent witness of extent. Hence a counter, not a
    #: refusal: 9.7 % of the store (measurement of 10.08.2026) must be
    #: VISIBLE.
    degenerate_hulls: collections.Counter = field(
        default_factory=collections.Counter)
    degenerate_by_category: dict = field(
        default_factory=lambda: collections.defaultdict(collections.Counter))
    #: Types for which no section was found: `category -> {type_name}`.
    #: One broken element and an entire type with no parameter are
    #: different diagnoses, and an element counter does not distinguish
    #: them.
    types_without_section: dict = field(
        default_factory=lambda: collections.defaultdict(set))

    def totals(self) -> dict[str, int]:
        return {"eligible": sum(self.eligible.values()),
                "hulled": sum(self.hulled.values()),
                "unsupported": sum(self.unsupported.values()),
                "missing_geometry": sum(self.missing_geometry.values()),
                "not_eligible": sum(self.not_eligible.values()),
                "outside_extraction_scope": self.outside_extraction_scope,
                "linked_elements_unscored": self.linked_elements_unscored,
                "links_without_element_count": self.links_without_element_count}

    def balanced(self) -> bool:
        t = self.totals()
        return t["eligible"] == t["hulled"] + t["unsupported"] + t["missing_geometry"]

    def unbalanced_categories(self) -> dict[str, dict]:
        """Review #11: the global balance let a deficit in one category
        be offset by a surplus in another. EVERY row must reconcile."""
        bad = {}
        for cat in (set(self.eligible) | set(self.hulled) | set(self.unsupported)
                    | set(self.missing_geometry)):
            e = self.eligible.get(cat, 0)
            got = (self.hulled.get(cat, 0) + self.unsupported.get(cat, 0)
                   + self.missing_geometry.get(cat, 0))
            if e != got:
                bad[cat] = {"eligible": e, "accounted": got}
        return bad

    def section_categories(self) -> list[str]:
        """Categories for which asking about a cross-section makes sense at all.

        The list is CLOSED by a table, not by observation: a model without a
        single pipe must show "0 of 0", not an empty block that reads as
        "wasn't asked".
        """
        return sorted(set(H.SECTION_RULES) | set(self.section_present)
                      | set(self.section_absent))

    def unbalanced_section_categories(self) -> dict[str, dict]:
        """The same census law as for hulls: `present + absent` must equal
        `eligible` for EVERY category where a cross-section is allowed.
        Otherwise "no cross-sections" is indistinguishable from "wasn't
        asked"."""
        bad = {}
        for cat in self.section_categories():
            e = self.eligible.get(cat, 0)
            got = self.section_present.get(cat, 0) + self.section_absent.get(cat, 0)
            if e != got:
                bad[cat] = {"eligible": e, "asked": got}
        return bad

    def sections_as_dict(self) -> dict:
        cats = self.section_categories()
        return {
            "totals": {"present": sum(self.section_present.values()),
                       "absent": sum(self.section_absent.values()),
                       "hulled": sum(self.section_hulled.values())},
            "balanced": not self.unbalanced_section_categories(),
            "unbalanced_categories": self.unbalanced_section_categories(),
            "by_category": {
                cat: {"present": self.section_present.get(cat, 0),
                      "absent": self.section_absent.get(cat, 0),
                      "hulled": self.section_hulled.get(cat, 0),
                      "eligible": self.eligible.get(cat, 0)}
                for cat in cats},
            "nominal_only_total": sum(self.section_nominal_only.values()),
            "nominal_only_by_category": dict(
                sorted(self.section_nominal_only.items())),
            "nominal_only_note": (
                "прочитан только НОМИНАЛЬНЫЙ диаметр (R3 красных): капсула по "
                "нему тела не содержит, поэтому оболочкой стал габарит. "
                "Наружный — RBS_PIPE_OUTER_DIAMETER / "
                "RBS_CONDUIT_OUTER_DIAM_PARAM."),
            "blocked_by_table": dict(sorted(self.section_blocked.items())),
            "blocked_total": sum(self.section_blocked.values()),
            "blocked_note": (
                "число сечения в L0 ЕСТЬ, но таблица запрещает категории им "
                "обосновывать оболочку (стена/балка/колонна/гибкая трасса — "
                "ревью №2, №3, №10). Ноль подъёмов здесь означает ЗАПРЕТ, "
                "а не отсутствие данных."),
            "types_without_section_count": sum(
                len(v) for v in self.types_without_section.values()),
            "types_without_section": {
                cat: sorted(names)
                for cat, names in sorted(self.types_without_section.items())
                if names},
        }

    def as_dict(self) -> dict:
        return {
            "totals": self.totals(),
            "balanced": self.balanced(),
            "unbalanced_categories": self.unbalanced_categories(),
            "by_category": {
                cat: {"eligible": self.eligible.get(cat, 0),
                      "hulled": self.hulled.get(cat, 0),
                      "unsupported": self.unsupported.get(cat, 0),
                      "missing_geometry": self.missing_geometry.get(cat, 0),
                      "not_eligible": self.not_eligible.get(cat, 0)}
                for cat in sorted(set(self.eligible) | set(self.not_eligible)
                                  | set(self.unsupported) | set(self.missing_geometry))
            },
            "reasons": dict(sorted(self.reasons.items())),
            "degenerate_hulls": self.degeneracy_as_dict(),
            "sections": self.sections_as_dict(),
            "mvp_side_coverage": self.mvp_side_coverage(),
        }

    def degeneracy_as_dict(self) -> dict:
        """Zero-volume hulls. Published ALWAYS, zero included:
        "no degenerate ones" and "wasn't counted" must look different."""
        total = sum(v for k, v in self.degenerate_hulls.items() if k != "ok")
        hulled = sum(self.hulled.values())
        return {
            "total": total,
            "hulled": hulled,
            "share": round(total / hulled, 6) if hulled else 0.0,
            "by_kind": {k: self.degenerate_hulls.get(k, 0)
                        for k in H.DEGENERACIES if k != "ok"},
            "by_category": {cat: dict(sorted(v.items()))
                            for cat, v in sorted(self.degenerate_by_category.items())
                            if v},
            "note": ("оболочка нулевого объёма НЕ МОЖЕТ доказать клеш. "
                     "Нарушением закона содержания она при этом не является: "
                     "независимого свидетеля протяжённости у этих элементов в "
                     "данных нет (замер 10.08.2026: 67 108 из 67 108 без "
                     "свидетеля), поэтому здесь счётчик, а не отказ."),
        }

    def mvp_side_coverage(self) -> dict:
        """Hull coverage ON THE MVP SIDE (R5 reds).

        Deliberately separate from the overall census: "share of the route
        without a hull" is the number that could not be obtained from the
        report at all, and it is exactly this number that decides whether it
        makes sense to read the list of findings.
        """
        return {
            side: {"eligible": self.mvp_eligible.get(side, 0),
                   "hulled": self.mvp_hulled.get(side, 0),
                   "without_hull": self.no_hull_mvp_side.get(side, 0)}
            for side in ("mep", "struct")
        }


@dataclass
class ClashGeometrySnapshot:
    records: list[H.HullRecord]
    census: Census
    origin: dict
    refusals: list[H.Refusal] = field(default_factory=list)
    #: HOST INDEX IN DECOMPILE TERMS — `element_id -> {host_element_id, ...}`.
    #: The same shape that `clash_judgement.hosted_from_ops` returns for the
    #: program path; the same `clash_judgement.host_relation` reads it.
    #:
    #: WHY A SEPARATE FIELD, NOT INSIDE `HullRecord`. A host exists even for
    #: elements WITHOUT a hull (a geometry failure does not cancel a declared
    #: host), while `HullRecord` by construction exists only for hulled ones:
    #: 189 of the 1,510 elements of `sob62_r23_v5` carry `host_id`, while
    #: there are 1,326 hulls. An index living inside the records would lose
    #: exactly those whose geometry didn't come together — and the loss
    #: would be silent.
    #:
    #: AN EMPTY DICTIONARY MEANS "ASKED, NO HOSTS". There is no absence
    #: here: there is one construction path, and it always asks.
    hosted: dict[str, dict] = field(default_factory=dict)

    def by_grade(self) -> dict[str, int]:
        c = collections.Counter(r.grade for r in self.records)
        return {g: c.get(g, 0) for g in H.GRADES}

    def mvp_records(self) -> list[H.HullRecord]:
        return [r for r in self.records if r.mvp_side in H.MVP_PAIR]

    def coverage_axes(self, *, geometry_scope: str) -> dict[str, dict]:
        """Independent input-coverage facts for a clash query.

        A balanced hull census proves only that every *extracted* eligible
        row was accounted for.  It does not prove that the extractor saw the
        whole host document, that linked-model geometry was federated, or
        that every element relevant to the requested query received a usable
        hull.  Keep those claims separate so that one green counter cannot
        mask a red one.

        ``geometry_scope`` is deliberately small and typed.  ``mvp`` means
        the two sides of the production MEP-vs-structure query;
        ``all_eligible`` means every physical row admitted by the category
        table (the diagnostic all-pairs query).
        """
        if geometry_scope == "mvp":
            eligible = sum(self.census.mvp_eligible.values())
            hulled = sum(self.census.mvp_hulled.values())
            without_hull = sum(self.census.no_hull_mvp_side.values())
            by_side = {
                side: {
                    "eligible": self.census.mvp_eligible.get(side, 0),
                    "hulled": self.census.mvp_hulled.get(side, 0),
                    "without_hull": self.census.no_hull_mvp_side.get(side, 0),
                }
                for side in ("mep", "struct")
            }
            by_category_without_hull = dict(
                sorted(self.census.no_hull_by_category.items()))
            degenerate = sum(
                count
                for category, by_kind in self.census.degenerate_by_category.items()
                if ((H.KIND_TABLE.get(category) is not None)
                    and H.KIND_TABLE[category].mvp_side in H.MVP_PAIR)
                for count in by_kind.values())
        elif geometry_scope == "all_eligible":
            totals = self.census.totals()
            eligible = totals["eligible"]
            hulled = totals["hulled"]
            without_hull = totals["unsupported"] + totals["missing_geometry"]
            by_side = {}
            by_category_without_hull = {
                category: (self.census.unsupported.get(category, 0)
                           + self.census.missing_geometry.get(category, 0))
                for category in sorted(
                    set(self.census.unsupported)
                    | set(self.census.missing_geometry))
                if (self.census.unsupported.get(category, 0)
                    + self.census.missing_geometry.get(category, 0))
            }
            degenerate = sum(
                value for kind, value in self.census.degenerate_hulls.items()
                if kind != "ok")
        else:
            raise ValueError(
                f"unknown clash geometry scope {geometry_scope!r}; "
                "expected 'mvp' or 'all_eligible'")

        outside = self.census.outside_extraction_scope
        linked = self.census.linked_elements_unscored
        extraction_axis = {
                "complete": outside == 0,
                "outside_extraction_scope": outside,
                "elements_in_l0": self.origin.get("elements_in_l0"),
                "header_census_total": self.origin.get("header_census_total"),
                "note": (
                    "complete only when the document census has no rows "
                    "outside the extracted L0 stream"),
            }
        # COMPLETENESS IS DECIDED BY LINKS, NOT BY THE SUM OF THEIR ELEMENTS.
        # A merge condition from the federation wave with the fixed counter
        # (11.08.2026), and without it the merge would ship a new, silently
        # wrong outcome.
        #
        # The clause was written when `linked_elements_unscored` held the
        # NUMBER OF LINKS, and back then `linked == 0` meant "no links" —
        # right by accident. The counter has been fixed and now holds
        # ELEMENTS, and the same expression turned false on exactly the
        # worst models: for a building all of whose links are UNLOADED,
        # `element_count` is unread for every single one, the sum equals
        # zero, and the search would declare itself COMPLETE where it saw
        # nothing at all. Across the corpus this is not an edge case: 316 of
        # 386 links (82%) have no number.
        #
        # The same class as the fixed counter itself: a value is declared
        # in one place (federation completeness), read in another (sum of
        # elements), and nothing forced them to agree.
        links_in_l0 = self.origin.get("links_in_l0") or 0
        federation_axis = {
                "complete": links_in_l0 == 0,
                "linked_elements_unscored": linked,
                "links_without_element_count":
                    self.census.links_without_element_count,
                "links_in_l0": links_in_l0,
                "note": (
                    "complete only when the document declares no links at all; "
                    "linked_elements_unscored is a LOWER BOUND — "
                    "links_without_element_count links carry no readable count"),
            }
        coverage = self.origin.get("federation_coverage")
        if coverage is not None:
            extraction_axis, federation_axis = _federation_coverage_axis(
                coverage, records=self.records, refusals=self.refusals)
        return {
            "extraction": extraction_axis,
            "federation": federation_axis,
            "geometry": {
                "complete": without_hull == 0 and degenerate == 0,
                "scope": geometry_scope,
                "eligible": eligible,
                "hulled": hulled,
                "without_hull": without_hull,
                "degenerate_hulls": degenerate,
                "by_side": by_side,
                "by_category_without_hull": by_category_without_hull,
                "note": (
                    "complete only when every element relevant to the query "
                    "has a non-degenerate conservative hull"),
            },
        }

    def as_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "origin": self.origin,
                "census": self.census.as_dict(), "by_grade": self.by_grade(),
                "records": len(self.records)}

    def validate(self) -> None:
        """Detector entry gate (review #11). Every violation is an exception.

        What is checked is exactly what, if absent, would make "zero
        clashes" indistinguishable from "didn't search": the balance of
        EVERY category, uniqueness and non-emptiness of addresses,
        finiteness of hulls, presence of provenance.
        """
        counter_fields = (
            "eligible", "hulled", "unsupported", "missing_geometry",
            "not_eligible", "reasons", "section_present", "section_absent",
            "section_hulled", "section_blocked", "section_nominal_only",
            "no_hull_mvp_side", "mvp_eligible", "mvp_hulled",
            "no_hull_by_category", "degenerate_hulls",
        )
        for field_name in counter_fields:
            counter = getattr(self.census, field_name)
            if not isinstance(counter, collections.Counter):
                raise SnapshotIntegrityError(
                    f"census.{field_name} не является Counter")
            invalid = {
                key: value for key, value in counter.items()
                if (not isinstance(key, str) or not key
                    or isinstance(value, bool) or not isinstance(value, int)
                    or value < 0)
            }
            if invalid:
                raise SnapshotIntegrityError(
                    f"census.{field_name} содержит неверные счётчики: "
                    f"{invalid}")
        for field_name in ("outside_extraction_scope",
                           "linked_elements_unscored"):
            value = getattr(self.census, field_name)
            if (isinstance(value, bool) or not isinstance(value, int)
                    or value < 0):
                raise SnapshotIntegrityError(
                    f"census.{field_name} должен быть неотрицательным int")
        if not isinstance(self.census.degenerate_by_category, dict):
            raise SnapshotIntegrityError(
                "census.degenerate_by_category должен быть mapping")
        for category, counts in self.census.degenerate_by_category.items():
            if (not isinstance(category, str) or not category
                    or not isinstance(counts, collections.Counter)
                    or any(not isinstance(kind, str) or not kind
                           or isinstance(value, bool)
                           or not isinstance(value, int) or value < 0
                           for kind, value in counts.items())):
                raise SnapshotIntegrityError(
                    "census.degenerate_by_category содержит неверные данные")

        bad = self.census.unbalanced_categories()
        if bad:
            raise SnapshotIntegrityError(
                f"перепись не сходится по категориям: {sorted(bad)} ({bad})")
        if not self.census.balanced():
            raise SnapshotIntegrityError(
                f"перепись не сходится: {self.census.totals()}")
        bad_sec = self.census.unbalanced_section_categories()
        if bad_sec:
            raise SnapshotIntegrityError(
                f"перепись сечений не сходится: {sorted(bad_sec)} ({bad_sec})")
        seen: set[str] = set()
        actual_hulled: collections.Counter = collections.Counter()
        actual_mvp_hulled: collections.Counter = collections.Counter()
        actual_degeneracy: collections.Counter = collections.Counter()
        actual_degeneracy_by_category: dict[str, collections.Counter] = (
            collections.defaultdict(collections.Counter))
        for r in self.records:
            if not r.source_id or r.source_id in ("None", "?"):
                raise SnapshotIntegrityError(f"пустой адрес элемента: {r!r}")
            if r.source_id in seen:
                raise SnapshotIntegrityError(f"дублирующийся source_id: {r.source_id}")
            seen.add(r.source_id)
            actual_hulled[r.category] += 1
            if r.mvp_side in H.MVP_PAIR:
                actual_mvp_hulled[r.mvp_side] += 1
            degeneracy = H.hull_degeneracy(r.hull)
            actual_degeneracy[degeneracy] += 1
            if degeneracy != "ok":
                actual_degeneracy_by_category[r.category][degeneracy] += 1
            lo, hi = r.bounds()
            if not all(isinstance(c, (int, float)) and math.isfinite(c)
                       for c in (*lo, *hi)):
                raise SnapshotIntegrityError(
                    f"неконечная оболочка у {r.source_id}: {lo} {hi}")
        normalized = lambda counter: collections.Counter({
            key: value for key, value in counter.items() if value})
        if normalized(actual_hulled) != normalized(self.census.hulled):
            raise SnapshotIntegrityError(
                "перепись hulled не совпадает с записями: "
                f"records={dict(actual_hulled)} "
                f"census={dict(self.census.hulled)}")
        if normalized(actual_mvp_hulled) != normalized(self.census.mvp_hulled):
            raise SnapshotIntegrityError(
                "перепись mvp_hulled не совпадает с записями")
        if normalized(actual_degeneracy) != normalized(
                self.census.degenerate_hulls):
            raise SnapshotIntegrityError(
                "перепись вырожденности не совпадает с записями")
        declared_degeneracy_by_category = {
            category: normalized(counts)
            for category, counts in self.census.degenerate_by_category.items()
            if normalized(counts)
        }
        if ({category: normalized(counts)
             for category, counts in actual_degeneracy_by_category.items()
             if normalized(counts)} != declared_degeneracy_by_category):
            raise SnapshotIntegrityError(
                "перепись вырожденности по категориям не совпадает")

        refusal_by_bucket: dict[str, collections.Counter] = {
            "unsupported": collections.Counter(),
            "missing_geometry": collections.Counter(),
            "not_eligible": collections.Counter(),
        }
        refusal_reasons: collections.Counter = collections.Counter()
        actual_no_hull_mvp_side: collections.Counter = collections.Counter()
        actual_no_hull_by_category: collections.Counter = collections.Counter()
        for refusal in self.refusals:
            if (not isinstance(refusal, H.Refusal)
                    or not isinstance(refusal.source_id, str)
                    or not refusal.source_id
                    or refusal.source_id in seen
                    or refusal.bucket not in refusal_by_bucket
                    or not isinstance(refusal.category, str)
                    or not refusal.category
                    or not isinstance(refusal.reason, str)
                    or not refusal.reason):
                raise SnapshotIntegrityError(
                    f"неверная или дублирующаяся строка refusal: {refusal!r}")
            seen.add(refusal.source_id)
            refusal_by_bucket[refusal.bucket][refusal.category] += 1
            refusal_reasons[refusal.reason] += 1
            rule = H.KIND_TABLE.get(refusal.category)
            if (refusal.bucket != "not_eligible" and rule is not None
                    and rule.mvp_side in H.MVP_PAIR):
                actual_no_hull_mvp_side[rule.mvp_side] += 1
                actual_no_hull_by_category[refusal.category] += 1
        for bucket, actual in refusal_by_bucket.items():
            declared = getattr(self.census, bucket)
            if normalized(actual) != normalized(declared):
                raise SnapshotIntegrityError(
                    f"перепись {bucket} не совпадает с refusals")
        if normalized(refusal_reasons) != normalized(self.census.reasons):
            raise SnapshotIntegrityError(
                "перепись причин отказа не совпадает с refusals")
        if normalized(actual_no_hull_mvp_side) != normalized(
                self.census.no_hull_mvp_side):
            raise SnapshotIntegrityError(
                "перепись no_hull_mvp_side не совпадает с refusals")
        if normalized(actual_no_hull_by_category) != normalized(
                self.census.no_hull_by_category):
            raise SnapshotIntegrityError(
                "перепись no_hull_by_category не совпадает с refusals")
        expected_mvp_eligible = actual_mvp_hulled + actual_no_hull_mvp_side
        if normalized(expected_mvp_eligible) != normalized(
                self.census.mvp_eligible):
            raise SnapshotIntegrityError(
                "перепись mvp_eligible не совпадает с records + refusals")

        elements_in_l0 = self.origin.get("elements_in_l0")
        if (elements_in_l0 is not None
                and (isinstance(elements_in_l0, bool)
                     or not isinstance(elements_in_l0, int)
                     or elements_in_l0 < 0
                     or elements_in_l0 != len(self.records) + len(self.refusals))):
            raise SnapshotIntegrityError(
                "origin.elements_in_l0 не совпадает с records + refusals")
        if not self.origin:
            raise SnapshotIntegrityError("снапшот без происхождения")
        coverage = self.origin.get("federation_coverage")
        if coverage is not None:
            _federation_coverage_axis(
                coverage, records=self.records, refusals=self.refusals)

    def join_manifest(self) -> dict:
        """Review #15: what from the model did NOT reach the search at all.

        The full L0↔L1↔ground join (op_id, lift_status) in D1 is not built
        yet — and this is said by the `l1_join` field, not by a default.
        The equality below is checkable already today and keeps the
        denominator honest.
        """
        t = self.census.totals()
        scored = t["hulled"]
        not_scored = t["unsupported"] + t["missing_geometry"]
        return {
            "eligible": t["eligible"],
            "scored": scored,
            "not_scored": not_scored,
            "not_eligible": t["not_eligible"],
            "outside_extraction_scope": t["outside_extraction_scope"],
            "linked_elements_unscored": t["linked_elements_unscored"],
            "links_without_element_count": t["links_without_element_count"],
            "l1_join": "absent",
            "l1_join_note": ("op_id/lift_status/ground-размеры в D1 не "
                             "присоединены: матрица op×category из §6 этим "
                             "модулем НЕ воспроизводится (ревью №15)."),
        }


def _sha(data: bytes) -> str:
    """FULL sha256 (review #16): truncated to 16 hex chars, it saved a line
    in the report at the cost of provability, and the sha of side indexes
    wasn't computed at all — a profile edit changed the findings while the
    fingerprint stayed the same."""
    return hashlib.sha256(data).hexdigest()


def _open_snapshot(path, mode="rt", *, encoding=None):
    """Snapshot door. Import is lazy: `clash` does not pull `ir.decompile`
    in at module load."""
    from kir.model.snapshot_io import open_snapshot

    return open_snapshot(path, mode, encoding=encoding)


def _snapshot_exists(path) -> bool:
    """`exists()` on a bare path answers False on the compressed one — that
    is, it LOSES the index."""
    from kir.model.snapshot_io import snapshot_file_exists

    return snapshot_file_exists(path)


def _snapshot_bytes(path) -> bytes:
    """UNPACKED content: the fingerprint must survive the cleanup."""
    with _open_snapshot(path, "rb") as handle:
        return handle.read()


#: Whose words these are. The value is NOT equal to
#: `clash_judgement.AUTHORED_SOURCE`, and this is a load-bearing distinction:
#: for decompile words, an unresolved reference means "host in a linked
#: file" (`host_out_of_scope`); for program words it means "the author
#: referenced an op that doesn't exist" (`contradicts`). Corpus measurement,
#: 08-11: dangling edges 1,263 of 213,811, of which 1,010 lead into a
#: linked file and 86 into `ReferencePlane`. Blaming the author for them
#: would mean, 959 times in a row, calling a limit of OUR reading someone
#: else's mistake.
L0_HOST_SOURCE = "l0_host_id"


def hosted_from_l0(elements: Iterable[dict]) -> dict[str, dict]:
    """L0 elements -> host index in the shape that `host_relation` reads.

    A paired twin of `clash_judgement.hosted_from_ops`, and deliberately NOT
    a copy of it: there the host is a reference to an op inside a single
    program, here it is `host_id` read from Revit. What they share is
    exactly one thing — the OUTPUT SHAPE — and it is shared because the
    reader is one and the same.

    There is nothing here to resolve the reference with, and no need to:
    `host_relation` compares `host_element_id` against the other side of
    the pair itself. An element that declared itself its own host does not
    make it into the index — such an edge would say nothing, and
    `confirms` on it would be false.
    """
    out: dict[str, dict] = {}
    for el in elements:
        if not isinstance(el, dict):
            continue
        host = el.get("host_id")
        if host in (None, "", 0, "0"):
            continue
        eid = str(el.get("element_id") or "")
        if not eid or str(host) == eid:
            continue
        out[eid] = {"host_element_id": str(host),
                    "host_ref": str(host),
                    "host_class": None,
                    "source": L0_HOST_SOURCE}
    return out


def build_from_elements(elements: Iterable[dict], *, origin: dict,
                        profiles: dict | None = None,
                        curves: dict | None = None) -> ClashGeometrySnapshot:
    """Elements (L0 record shape) -> snapshot. The single construction path:
    both real decompiles and synthetic test scenes go through here."""
    profiles = profiles or {}
    curves = curves or {}
    # THE INPUT IS AN ITERABLE: it cannot be walked twice, and the host
    # index must see EVERYONE, including those whose hull didn't come
    # together. We materialize once, here, rather than in every caller.
    elements = list(elements)
    hosted = hosted_from_l0(elements)
    census = Census()
    records: list[H.HullRecord] = []
    refusals: list[H.Refusal] = []
    for el in elements:
        cat = el.get("category") or "?"
        sid = str(el.get("element_id"))
        rec, ref = H.build_hull(el, profile=profiles.get(sid),
                                curve=curves.get(sid))
        # The cross-section is computed BEFORE and INDEPENDENTLY of the
        # hull outcome: an element that has a cross-section but a broken
        # axis must stay in the denominator, otherwise the "no
        # cross-sections" percentage is computed over a sample.
        if H.category_allows_sections(cat):
            sec, why, nominal = H.section_from_params(cat, el.get("params"))
            explicit = el.get("section_radius_mm")
            if sec is not None or (G._finite(explicit) and explicit > 0):
                census.section_present[cat] += 1
            else:
                census.section_absent[cat] += 1
                census.types_without_section[cat].add(
                    el.get("type_name") or "__без_имени_типа__")
            if why == "section_nominal_only" or (
                    sec is None and nominal is not None):
                census.section_nominal_only[cat] += 1
            if rec is not None and rec.hull_source == "axis_section":
                census.section_hulled[cat] += 1
        elif H.carries_section_number(el.get("params")):
            rule = H.KIND_TABLE.get(cat)
            if rule is not None and rule.eligible:
                census.section_blocked[cat] += 1
        rule = H.KIND_TABLE.get(cat)
        if rule is not None and rule.eligible and rule.mvp_side:
            census.mvp_eligible[rule.mvp_side] += 1
            if rec is not None:
                census.mvp_hulled[rule.mvp_side] += 1
            else:
                census.no_hull_mvp_side[rule.mvp_side] += 1
                census.no_hull_by_category[cat] += 1
        if rec is not None:
            census.eligible[cat] += 1
            census.hulled[cat] += 1
            degen = H.hull_degeneracy(rec.hull)
            census.degenerate_hulls[degen] += 1
            if degen != "ok":
                census.degenerate_by_category[cat][degen] += 1
            records.append(rec)
            continue
        assert ref is not None
        refusals.append(ref)
        census.reasons[ref.reason] += 1
        if ref.bucket == "not_eligible":
            census.not_eligible[cat] += 1
        else:
            census.eligible[cat] += 1
            getattr(census, ref.bucket)[cat] += 1
    records.sort(key=lambda r: r.source_id)
    refusals.sort(key=lambda r: r.source_id)
    return ClashGeometrySnapshot(records, census, origin, refusals, hosted)


# ─────────────────────────────────────────────── real decompile on disk

def read_decompile(run_dir: str | pathlib.Path) -> tuple[list[dict], dict, dict, dict]:
    """L0 + side indexes -> (elements, profiles, curves, fingerprint).

    Review #10: the reader ignored the header census, `category_status`,
    the footer, and link records — so a file truncated at a valid JSON
    line looked whole. Now the stream must prove its own completeness, and
    everything that didn't make it in must be NAMED by a number.
    """
    d = pathlib.Path(run_dir)
    elements: list[dict] = []
    origin: dict[str, Any] = {"run_dir": d.name}
    header: dict = {}
    footer: dict = {}
    statuses: list[dict] = []
    links = 0
    linked_elements = 0
    links_unread = 0
    seen_categories: collections.Counter = collections.Counter()
    l0 = d / "L0.jsonl"
    # 🔴 RECORD ORDER IS PART OF THE FORMAT, NOT A WISH (F-115, 29.08.2026).
    # The header promises: "the stream must PROVE its own completeness."
    # The promise was kept only halfway: order wasn't checked at all, a
    # second header SILENTLY OVERWROTE the first, records AFTER the footer
    # kept being counted into the elements, and an unknown record kind
    # simply fell through past every branch. The canonical
    # `extract.L0JSONLReader` rejects all of this by name ("record after
    # footer", "duplicate JSONL header", "unknown JSONL record kind") —
    # meaning the input that used to be accepted here is ALREADY invalid
    # under the format's law, and the refusal cannot fire on something
    # lawful.
    header_seen = False
    footer_seen = False
    with _open_snapshot(l0, "rt", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SnapshotIntegrityError(
                    f"L0 строка {lineno} нечитаема: {exc}") from exc
            kind = r.get("record")
            if footer_seen:
                raise SnapshotIntegrityError(
                    f"L0 строка {lineno}: запись ПОСЛЕ футера — поток "
                    f"дописан после объявления полноты")
            if kind == "element":
                elements.append(r["element"])
                seen_categories[r["element"].get("category") or "?"] += 1
            elif kind == "header":
                if header_seen:
                    raise SnapshotIntegrityError(
                        f"L0 строка {lineno}: ВТОРОЙ заголовок — снимок не "
                        f"знает, о каком документе он говорит")
                header_seen = True
                header = r
            elif kind == "footer":
                footer_seen = True
                footer = r
            elif kind == "category_status":
                # The shape is measured off a live L0 (SOB6.2 facade v10),
                # not invented: {"record":"category_status","status":{...}}.
                statuses.append(r.get("status") or {})
            elif kind == "link":
                # A LINK RECORD IS OPENED, NOT JUST COUNTED (11.08.2026).
                # There used to be a single `links += 1` here, and
                # `census.linked_elements_
                # unscored` — a field whose NAME promises elements — was
                # receiving exactly that number. The real value lay inside
                # the record itself: the extractor puts `element_count`
                # from `GetLinkDocument()` (`extract.py`, the loop over
                # `RevitLinkInstance`) and leaves it `null` when the
                # document isn't loaded. Both cases are now DISTINCT and
                # both are named.
                links += 1
                count = (r.get("link") or {}).get("element_count")
                if isinstance(count, int) and not isinstance(count, bool) \
                        and count >= 0:
                    linked_elements += count
                else:
                    links_unread += 1
            else:
                # An unknown kind FELL THROUGH PAST EVERY BRANCH and was
                # counted nowhere: a record this reader doesn't understand
                # could carry anything at all, and the census reconciled
                # with itself.
                raise SnapshotIntegrityError(
                    f"L0 строка {lineno}: неизвестный род записи {kind!r}")
    if not footer:
        raise SnapshotIntegrityError(
            "L0 без footer: поток обрезан, а перепись на обрезанном потоке "
            "сходится сама с собой (ревью №10)")
    if footer.get("stream_complete") is False:
        raise SnapshotIntegrityError("L0 объявил stream_complete=false")
    # 🔴 A CHECK THAT A TYPE CAN SWITCH OFF CHECKS NOTHING (F-115, 29.08.2026).
    # All three footer checks stood under `isinstance(..., int)`, meaning
    # an ABSENT or NON-NUMERIC promise silently went unchecked. The
    # costliest case was `element_count: "99"` with one element: the
    # promise is knowingly wrong, and the check exists precisely to catch
    # it (review #10), yet it stayed silent only because the number
    # arrived as a STRING. The emitter (`extract.py`) always writes all
    # three numbers, and the canonical reader requires all three via
    # `_require_int` — so this is not a new requirement but the old one
    # carried through to the end.
    def _declared(field: str, actual: int) -> None:
        value = footer.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise SnapshotIntegrityError(
                f"footer.{field} отсутствует или не целое: {value!r} — "
                f"поток не доказал полноту, а сверка, выключаемая типом, "
                f"не сверяет ничего")
        if value != actual:
            raise SnapshotIntegrityError(
                f"footer обещал {value} ({field}), в потоке {actual}")

    _declared("element_count", len(elements))
    _declared("category_count", len(statuses))
    # THE THIRD NUMBER OF THE SAME FOOTER, AND NOBODY READ IT.
    # `element_count` and `category_count` are checked against the stream
    # and fail the run; `link_count` was declared right next to them and
    # ignored, so a link lost during writing left the census reconciling
    # WITH ITSELF — exactly the hole the footer check exists to catch
    # (review #10). This is not new strictness but the already-accepted
    # law carried through to its third term.
    _declared("link_count", links)
    # header.document.census — a LIST of {key, count, name}; measured, not
    # assumed: on the facade that is 30,489 elements against 3,153 in the
    # stream.
    census_rows = ((header.get("document") or {}).get("census") or []) if header else []
    if census_rows and not statuses:
        raise SnapshotIntegrityError(
            "header census есть, а ни одной строки category_status нет: "
            "закрытость модели не доказана (ревью №10)")
    for st in statuses:
        cat = st.get("category")
        exp, got = st.get("expected_count"), st.get("extracted_count")
        if isinstance(got, int) and got != seen_categories.get(cat, 0):
            raise SnapshotIntegrityError(
                f"category_status[{cat}]: обещано извлечь {got}, в потоке "
                f"{seen_categories.get(cat, 0)}")
        if isinstance(exp, int) and isinstance(got, int) and got > exp:
            raise SnapshotIntegrityError(
                f"category_status[{cat}]: извлечено {got} > заявленных {exp}")
    origin["stream_complete"] = True
    origin["header_census_total"] = sum(
        row.get("count", 0) for row in census_rows
        if isinstance(row.get("count"), int))
    origin["category_status_rows"] = len(statuses)
    origin["links_in_l0"] = links
    #: Three numbers, not one, and separately they do not substitute for
    #: one another: this many links, this many elements in them, and for
    #: this many links the element count COULD NOT BE READ. A sum of 0
    #: with `links_in_l0 > 0` means "all links are unloaded," not "there
    #: are no links".
    origin["linked_elements_in_l0"] = linked_elements
    origin["links_without_element_count"] = links_unread
    origin["elements_in_l0"] = len(elements)

    # THE FINGERPRINT IS TAKEN OF THE CONTENT, NOT OF THE BYTES ON DISK,
    # and this is not nitpicking: the cleanup compresses `L0.jsonl`,
    # `sketch.index.json`, and `curve.index.json` IN PLACE. Were we to hash
    # the compressed file, compressing a cooled-down decompile would
    # change the input's fingerprint without changing a single element,
    # and every report would stop reconciling with its source.
    # `open_snapshot` returns the UNPACKED content, so the fingerprint is
    # the same before and after the cleanup. And `exists()` on the
    # compressed file returns False, meaning indexes would silently drop
    # out of the snapshot — hence `snapshot_file_exists`.
    inputs: dict[str, str] = {"L0.jsonl": _sha(_snapshot_bytes(l0))}
    proof = d / "revision.proof.json"
    if proof.exists():
        # The cleanup does NOT touch `revision.proof.json` (its list is
        # closed to six names), so a bare read here is correct, not an
        # oversight.
        origin["revision"] = json.loads(proof.read_text(encoding="utf-8"))
        inputs["revision.proof.json"] = _sha(proof.read_bytes())
    profiles: dict[str, dict] = {}
    sk = d / "sketch.index.json"
    if _snapshot_exists(sk):
        blob = _snapshot_bytes(sk)
        raw = json.loads(blob.decode("utf-8"))
        profiles = raw.get("profile_index") or {}
        origin["sketch_failures"] = len(raw.get("failures") or [])
        inputs["sketch.index.json"] = _sha(blob)
    curves: dict[str, dict] = {}
    cv = d / "curve.index.json"
    if _snapshot_exists(cv):
        blob = _snapshot_bytes(cv)
        raw = json.loads(blob.decode("utf-8"))
        curves = raw.get("curve_index") or {}
        inputs["curve.index.json"] = _sha(blob)
    # Input fingerprint: content, not the directory name. A report not
    # tied to the source's SHA can be neither reproduced nor refuted.
    origin["inputs_sha256"] = dict(sorted(inputs.items()))
    origin["l0_sha"] = inputs["L0.jsonl"]
    origin["schema_versions"] = {"snapshot": SCHEMA_VERSION}
    origin["snapshot_sha256"] = _sha(json.dumps(
        {"inputs": origin["inputs_sha256"],
         "schema_versions": origin["schema_versions"]},
        sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return elements, profiles, curves, origin


def build_from_decompile(run_dir: str | pathlib.Path) -> ClashGeometrySnapshot:
    elements, profiles, curves, origin = read_decompile(run_dir)
    snap = build_from_elements(elements, origin=origin, profiles=profiles,
                               curves=curves)
    header_total = origin.get("header_census_total") or 0
    if header_total:
        snap.census.outside_extraction_scope = max(
            0, header_total - origin["elements_in_l0"])
    # AN AUTHORITY WAS ASKED, NOT A VALUE DECLARED. There used to be
    # `= origin.get("links_in_l0", 0)` here: a field named ELEMENTS was
    # receiving the number of LINK RECORDS, and three links of forty
    # thousand each were reported as a three.
    snap.census.linked_elements_unscored = origin.get(
        "linked_elements_in_l0", 0)
    snap.census.links_without_element_count = origin.get(
        "links_without_element_count", 0)
    snap.validate()
    return snap
