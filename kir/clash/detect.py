"""Two search phases and a flat, deterministic report.

The broad phase (review #11): a hull is placed into ALL the cells its AABB
touches, not into one at the center. "Neighboring cells from the median
bounding size" is correct only given a proven upper bound on hull size — and
a long wall and a short pipe intersect when their centers sit tens of cells
apart. Giants that touch too many cells go into a separate list and are
compared against everything — without this the grid either lies or blows
up.

The narrow phase gives a formal output (review #13): `signed_distance`
(negative = penetration), `physical_penetration_mm`, `clearance_deficit_mm`,
an MTV as A's translation with B held fixed. The verdict is
`confirmed | possible` (review #14): the intersection of two conservative
hulls means "a clash is possible," not a clash, because it is the HULLS
being judged, not the bodies.
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import pathlib
import time
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping, Sequence

from kir.clash import exact as _EXACT
from kir.clash import geom as G
from kir.clash import hulls as H
from kir.clash.exact import EXACT_BASIS
from kir.clash.snapshot import ClashGeometrySnapshot, SnapshotIntegrityError
from kir.clash.spatial_index import (
    SpatialIndex,
    choose_cell_size as _index_cell_size,
    nonnegative_finite as _index_nonnegative_finite,
)

REPORT_SCHEMA = "clash-report/3"

#: The limit on cells per hull lives with the HULLS
#: (`hulls.MAX_CELLS_PER_HULL`), not here: `resolve.py` computes exactly the
#: same quantity by the same arithmetic, and two carriers of one piece of
#: knowledge drift apart silently.
MAX_CELLS_PER_HULL = H.MAX_CELLS_PER_HULL

#: Review #14. The hulls' RELATION is a separate axis from PROVABILITY. The
#: previous `tol_grade` solved both problems at once and muted proven
#: contacts: at sd=0 there was no finding even for an exact pair, while a
#: coarse pair with sd=-1…-25 mm was suppressed by a threshold that was
#: never a proven AABB margin of error.
HULL_RELATIONS = ("overlap", "contact", "separated")
#: 🔴 A THIRD VERDICT WAS SET UP BY STAGE B (06.09.2026), AND HERE IS WHY.
#: Before it, the vocabulary of provability consisted of two words, and
#: there was no way to say "the hulls intersected, but the BODIES did not"
#: at ANY threshold whatsoever: a pair stayed `possible` forever.
#: Measurement on the live corpus: 3506 findings, all `possible`, `exact`
#: grades 0 out of 1271. `refuted` is issued ONLY by the exact phase against
#: real bodies (`kir.clash.exact`) and ONLY as `clear`; neither a hull, nor
#: a threshold, nor a kernel refusal can issue it.
VERDICTS = ("confirmed", "possible", "refuted")

#: Numerical noise from the feet→mm conversion, and NOT a physical
#: tolerance. An 1800 mm elevation arrives as 1799.9999999998602 — for
#: exactly this and nothing else.
EPS_NUMERIC_MM = 1e-6

#: What the published distance means (review #7). For a pair of prisms this
#: is a LOWER BOUND along the best separating axis, not the Euclidean
#: distance: it is never above the true value, so it produces extra
#: findings, but never misses.
SEPARATION_SEMANTICS = (
    "signed_distance_mm: <0 — глубина перекрытия ОБОЛОЧЕК; >0 — расстояние. "
    "С волны DECOMPOSE положительная величина ТОЧНА для всех видов оболочек: "
    "зазор пары выпуклых подошв считается перебором «вершина–ребро», а не "
    "лучшей разделяющей осью SAT (прежнее lower_bound давало 1.0 там, где "
    "истинное расстояние √2). Нижней оценкой осталась РОВНО ОДНА величина, и "
    "она помечена флагом separation_is_lower_bound: глубина перекрытия двух "
    "ОБЪЕДИНЕНИЙ выпуклых кусков (hull_source=profile с вырезами/вогнутостью). "
    "Развести два объединения обязан ОДИН перенос, гасящий все пересекающиеся "
    "пары кусков разом, поэтому требуемый ход не меньше самой глубокой пары и "
    "вообще говоря больше неё; публикуется именно самая глубокая пара."
)

#: Review #13: the search domain is obligated to be named in the canon. An
#: arbitrary callable filter made it indeterminable — "6/236" cannot be
#: attributed to either MVP or diagnostics.
SCOPES: dict[str, str] = {
    "mvp_v2": "{труба, воздуховод, лоток, кабель-канал} × "
              "{стена, пол, колонна, балка, фундамент, кровля}",
    "all_physical_diagnostic": "ВСЕ физические пары — диагностика, не MVP: "
                               "внутрираздельные примыкания законны сплошь и рядом",
    "cross_model_federation": "пары РАЗНЫХ моделей сводной: «мешают ли модели "
                              "друг другу»; пары внутри одной модели — законные "
                              "примыкания и в область не входят",
    "bundle_vs_document": "пары, где хотя бы одна сторона — из пачки сессии: "
                          "«что внесла ЭТА пачка в уже стоящее здание». Пары "
                          "стоящее×стоящее существовали до хода и в область "
                          "не входят; отношение `separated` против стоящего "
                          "не публикуется — иначе в находки уедет всё здание",
}


#: The old name is kept as a compatible type: external readers use
#: ``grid.cell/buckets/oversized/stats/slack``.  The implementation is now
#: one for both the detector and the resolver, but the grid itself remains
#: only a supplier of candidates — the narrow phase and the independent
#: checks do not trust it for the truth.
Grid = SpatialIndex


def _nonnegative_finite(value: object, name: str) -> float:
    """Validate a geometric distance before it can shape candidate search."""
    return _index_nonnegative_finite(value, name)


def choose_cell_size(records: list[H.HullRecord]) -> float:
    """A cell's edge — 2× the hull's median bounding size, but not zero."""
    return _index_cell_size(records)


def build_grid(records: list[H.HullRecord], cell: float | None = None, *,
               slack: float = 0.0) -> Grid:
    """Laying hulls out into cells.

    Review #9: `slack` (a positive clearance) was applied ONLY after a
    meeting in a shared cell, while the layout ran on the un-inflated
    bounding size. Counterexample: cell=10, boxes x=[8,9] and [10.1,11],
    clearance=2 — a full sweep gives a pair, the grid gave []. We inflate
    EVERY hull's bounding size by slack during layout: if two bounding
    boxes converge within slack, their inflated versions are obligated to
    intersect, and therefore to share at least one cell.
    """
    return Grid(records, cell=cell, slack=slack,
                max_cells_per_hull=MAX_CELLS_PER_HULL)


def _boxes_overlap(a: H.HullRecord, b: H.HullRecord, slack: float) -> bool:
    alo, ahi = a.bounds()
    blo, bhi = b.bounds()
    return all(alo[k] - slack <= bhi[k] and blo[k] - slack <= ahi[k]
               for k in range(3))


def candidate_pairs(records: list[H.HullRecord], grid: Grid, *,
                    slack: float = 0.0,
                    pair_filter=None) -> list[tuple[int, int]]:
    """Broad-phase candidates — a SUPERSET of the real intersections.

    Deduplication is global: one pair lands in the result exactly once, no
    matter how many cells it shares.

    The grid is obligated to be built with the same (or a larger) `slack`
    — otherwise the layout did not see the clearance, and the superset
    stops being one (review #9).
    """
    # The public function remains a materializing adapter with the former
    # sort by indices.  The streaming path below takes the same iterator
    # without this list and therefore does not hold O(candidate_pairs) keys.
    return sorted(grid.iter_candidate_pairs(
        slack=slack, pair_filter=pair_filter, records=records))


def brute_pairs(records: list[H.HullRecord], *, slack: float = 0.0,
                pair_filter=None) -> list[tuple[int, int]]:
    """A full sweep — the reference for the broad phase's property test."""
    slack = _nonnegative_finite(slack, "slack")
    out = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            a, b = records[i], records[j]
            if pair_filter is not None and not pair_filter(a, b):
                continue
            if _boxes_overlap(a, b, slack):
                out.append((i, j))
    return out


def mvp_pair_filter(a: H.HullRecord, b: H.HullRecord) -> bool:
    """MVP pairs: {pipe, duct, tray} × {wall, floor, column, ...}."""
    return {a.mvp_side, b.mvp_side} == set(H.MVP_PAIR)


#: The source address separator `<model>::<source id>`. The literal is kept
#: HERE, not imported from `existing`: that one pulls in
#: `kir.model.snapshot_io` (reading the corpus), so
#: `bundle_vs_document_pair_filter` goes there LAZILY, while the federation
#: filter is called on EVERY pair — 59 937 times on one live run of
#: 14.08.2026. Two literals for one convention is a second address space
#: for one question, our own named defect, so the divergence is pinned by a
#: number: `tests/test_an_address_without_a_model_is_not_a_model.py`
#: requires `MODEL_SEPARATOR == existing.SOURCE_SEPARATOR`.
MODEL_SEPARATOR = "::"


def model_key_of(source_id: str) -> str | None:
    """A model's name from the address `<model>::<id>`; `None` — the address does NOT carry one.

    🔴 THE ABSENCE OF A SEPARATOR IS THE ABSENCE OF AN ANSWER, NOT AN
    ANSWER. The prior edition asked `source_id.split("::", 1)[0]`, and
    `split` on a string WITHOUT a separator returns THE STRING ITSELF:
    ordinary Revit ids `100` and `101` each got their own "model," and the
    "only different models" filter let pairs INSIDE one building through as
    cross-model. Measurement of 03.09.2026 on a four-wall snapshot assembled
    by `snapshot.build_from_elements`: the `cross_model_federation` domain
    yielded 6 findings out of 6 — exactly as many as
    `all_physical_diagnostic`, that is, the scope had collapsed into
    "everything," and the report stayed silent about it.

    An empty model name (`::100`) is also `None`: an empty string differs
    from another empty string in nothing, and the equality of two
    "unknowns" is not the equality of models.
    """
    head, separator, _rest = source_id.partition(MODEL_SEPARATOR)
    if not separator or not head:
        return None
    return head


def cross_model_pair_filter(a: H.HullRecord, b: H.HullRecord) -> bool:
    """FEDERATED MODEL: only pairs of DIFFERENT KNOWN models (14.08.2026).

    The owner: "the way I made a federation out of them in Navis... so that
    I can run clashes." The federation is defined by the question "do the
    models interfere with EACH OTHER"; a pair within one model is a
    legitimate adjacency that does not answer this question, and it
    produces so much noise that the answer drowns in it.

    THE MODEL LIVES IN THE ELEMENT'S ADDRESS (`<model>::<source id>`), and
    this is not decoration: two parses easily carry identical `source_id`
    values, and without the prefix a pair from two different buildings
    would be indistinguishable from a pair within one.

    AN ELEMENT WITH NO MODEL PREFIX HAS NO MODEL — neither its own nor an
    "empty" one. Its key is `None`, and a pair where even one side is like
    this does NOT enter the domain: there is nothing to say "different
    models" with about it, yet saying so anyway would mean inventing a
    membership. The skip, however, does not stay silent: `detect` prints
    into `notes` how many hulls arrived with no model name — "zero findings
    because there are no addresses" and "zero findings because the models
    do not interfere" are obligated to be readable from the report, not
    from intonation.
    """
    key_a = model_key_of(a.source_id)
    key_b = model_key_of(b.source_id)
    return key_a is not None and key_b is not None and key_a != key_b


def any_physical_pair_filter(a: H.HullRecord, b: H.HullRecord) -> bool:
    """All physical pairs — NOT MVP; fit only for diagnostics, because
    intra-partition adjacencies are legitimate more often than not."""
    return True


def bundle_vs_document_pair_filter(a: H.HullRecord, b: H.HullRecord) -> bool:
    """WHAT THE BATCH INTRODUCED: pairs where at least one side is from the session's batch.

    The source address follows the same `<source>::<id>` convention as the
    federated model; the `document` prefix marks what already stands
    (`existing.EXISTING_SOURCE`), an element with no prefix belongs to the
    batch.

    A PAIR OF "EXISTING × EXISTING" IS DISCARDED, and this is not a work
    saving. Such a finding existed in the building BEFORE our turn; passing
    it off as a result of checking the batch would mean claiming someone
    else's defect as our own and drowning what we introduced in someone
    else's noise. The domain's question is exactly one: "what did THIS
    batch introduce."
    """
    from kir.clash.existing import is_existing

    return not (is_existing(a.source_id) and is_existing(b.source_id))


# ─────────────────────────────────────────────────────────── the narrow phase

PHYSICAL_OVERLAP_PROOF_SCHEMA = "clash-certified-inner-overlap/2"


def _freeze_proof_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({
            str(key): _freeze_proof_json(item)
            for key, item in value.items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_proof_json(item) for item in value)
    return value


def _thaw_proof_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_proof_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_proof_json(item) for item in value]
    return value


@dataclass(frozen=True)
class PhysicalOverlapProof:
    """Pair-level proof kept separate from the outer-hull finding."""

    status: str                   # confirmed | not_proven
    basis: str | None
    reason: str | None
    subject_a: str
    subject_b: str
    a: Mapping[str, Any]
    b: Mapping[str, Any]
    inner_relation: str | None = None
    inner_signed_distance_mm: float | None = None
    inner_overlap_depth_mm: float | None = None
    required_margin_mm: float | None = None
    #: The EXACT phase's numbers (stage B). They live as separate fields,
    #: not under `inner_*`: "the inner hulls' depth" and "the bodies'
    #: intersection volume" are different quantities, and one name for both
    #: would make the report indistinguishable.
    exact_relation: str | None = None
    exact_overlap_volume_mm3: float | None = None
    exact_depth_mm: float | None = None
    exact_gap_mm: float | None = None
    tolerance_policy_digest: str | None = None
    schema_version: str = PHYSICAL_OVERLAP_PROOF_SCHEMA
    _authority: object | None = field(
        default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.status not in ("confirmed", "not_proven", "refuted"):
            raise ValueError("physical proof status is unsupported")
        # `refuted` is just as much a claim about the world as `confirmed`,
        # and therefore demands the same authorship: a refutation that any
        # arbitrary caller could issue would erase findings with no proof.
        if (self.status in ("confirmed", "refuted")
                and self._authority is not H._PAIR_PROOF_ISSUANCE_AUTHORITY):
            raise PermissionError(
                "confirmed physical proof must be issued by the narrow kernel")
        object.__setattr__(self, "a", _freeze_proof_json(self.a))
        object.__setattr__(self, "b", _freeze_proof_json(self.b))

    def as_dict(self) -> dict:
        def finite_or_none(value: float | None, digits: int = 9):
            if value is None or not math.isfinite(value):
                return None
            return G._norm_zero(round(float(value), digits))

        payload = {
            "schema_version": self.schema_version,
            "status": self.status,
            "basis": self.basis,
            "reason": self.reason,
            "subject_a": self.subject_a,
            "subject_b": self.subject_b,
            "a": _thaw_proof_json(self.a),
            "b": _thaw_proof_json(self.b),
            "inner_relation": self.inner_relation,
            "inner_signed_distance_mm": finite_or_none(
                self.inner_signed_distance_mm),
            "inner_overlap_depth_mm": finite_or_none(
                self.inner_overlap_depth_mm, 6),
            "required_margin_mm": finite_or_none(
                self.required_margin_mm, 6),
        }
        # 🔴 THE EXACT PHASE'S FIELDS ARE PRINTED ONLY FOR IT, AND THIS IS
        # NOT AN ECONOMY. Printing them unconditionally would have shifted
        # EVERY existing report: measurement of 06.09.2026 —
        # `test_the_canonical_golden_does_not_move` turned red over five new
        # keys with a `null` value. Keys that the baseline does not have do
        # not belong to it; the set of keys is chosen by the baseline.
        if self.basis == EXACT_BASIS or self.exact_relation is not None:
            payload.update({
                "exact_relation": self.exact_relation,
                "exact_overlap_volume_mm3": finite_or_none(
                    self.exact_overlap_volume_mm3, 6),
                "exact_depth_mm": finite_or_none(self.exact_depth_mm, 6),
                "exact_gap_mm": finite_or_none(self.exact_gap_mm, 6),
                "tolerance_policy_digest": self.tolerance_policy_digest,
            })
        # Only a confirmed claim carries authority.  A ``not_proven`` packet
        # is diagnostic data, not a capability, and keeping it unsigned also
        # keeps ordinary outer-only production reports deterministic across
        # process restarts.  The verifier below never accepts that state.
        if self.status not in ("confirmed", "refuted"):
            return payload
        return H.seal_serialized_pair_proof(
            payload, authority=self._authority)


_PAIR_PROOF_PAYLOAD_KEYS = frozenset({
    "schema_version", "status", "basis", "reason", "subject_a",
    "subject_b", "a", "b", "inner_relation",
    "inner_signed_distance_mm", "inner_overlap_depth_mm",
    "required_margin_mm",
})
#: The key set of the EXACT basis is a superset. The two bases print different
#: payloads, so their HMAC stamp runs over different sets too: a stamp
#: covering the wrong keys covers nothing.
_EXACT_PAIR_PROOF_PAYLOAD_KEYS = _PAIR_PROOF_PAYLOAD_KEYS | frozenset({
    "exact_relation", "exact_overlap_volume_mm3", "exact_depth_mm",
    "exact_gap_mm", "tolerance_policy_digest",
})
_PAIR_SIDE_KEYS = frozenset({
    "status", "reason", "certificate", "hull_type",
})


def _proof_number(value: object) -> float | None:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value))):
        return None
    return float(value)


def verify_serialized_physical_overlap_proof(
        proof: Mapping[str, Any], *, subject_a: str,
        subject_b: str) -> bool:
    """Verify a complete confirmed pair chain from untrusted JSON.

    Both certificate HMACs and the pair HMAC are required.  The pair seal
    binds subjects, the full side payloads (including certificate tags), and
    every verdict/geometric number.  Replaying a certificate for another
    element or editing depth/margin therefore fails closed.  Tags are
    intentionally process-local: persistence across restart is not authority
    for this test-only producer.
    """

    if not isinstance(proof, Mapping):
        return False
    # The key set is chosen BY BASIS, before the stamp is checked: a forged
    # basis will pick the wrong set and fail the digest comparison, not pass.
    keys = (_EXACT_PAIR_PROOF_PAYLOAD_KEYS if proof.get("basis") == EXACT_BASIS
            else _PAIR_PROOF_PAYLOAD_KEYS)
    if not H.verify_serialized_pair_proof_integrity(proof, payload_keys=keys):
        return False
    if (proof.get("schema_version") != PHYSICAL_OVERLAP_PROOF_SCHEMA
            or proof.get("reason") is not None
            or proof.get("subject_a") != subject_a
            or proof.get("subject_b") != subject_b):
        return False
    # 🔴 TWO BASES — TWO CHAINS, AND THEY DO NOT MIX. For inner hulls the
    # proof rests on TWO certificates and margin arithmetic; for the exact
    # phase it rests on the intersection volume of the real bodies and the
    # tolerance-policy digest. Accepting one proof under the other's rules
    # would mean checking something other than what is claimed.
    if proof.get("basis") == EXACT_BASIS:
        return _verify_exact_pair_payload(proof)
    if (proof.get("status") != "confirmed"
            or proof.get("basis") != "certified_inner_overlap"
            or proof.get("inner_relation") != "overlap"):
        return False
    for side_name, expected_subject in (
            ("a", subject_a), ("b", subject_b)):
        side = proof.get(side_name)
        if (not isinstance(side, Mapping)
                or set(side) != _PAIR_SIDE_KEYS
                or side.get("status") != "valid"
                or side.get("reason") is not None
                or side.get("hull_type") not in ("Aabb", "Prism")):
            return False
        certificate = side.get("certificate")
        if (not isinstance(certificate, Mapping)
                or not H.verify_serialized_inner_certificate(
                    certificate,
                    expected_subject_source_id=expected_subject)):
            return False
    signed_distance = _proof_number(proof.get("inner_signed_distance_mm"))
    depth = _proof_number(proof.get("inner_overlap_depth_mm"))
    margin = _proof_number(proof.get("required_margin_mm"))
    if (signed_distance is None or depth is None or margin is None
            or signed_distance >= -EPS_NUMERIC_MM
            or depth <= margin or margin < EPS_NUMERIC_MM):
        return False
    expected_depth = max(0.0, -signed_distance)
    if not math.isclose(
            depth, expected_depth, rel_tol=1e-12, abs_tol=1.1e-6):
        return False
    expected_margin = EPS_NUMERIC_MM
    for side_name in ("a", "b"):
        certificate = proof[side_name]["certificate"]
        expected_margin += (
            float(certificate["error_bound_mm"])
            + float(certificate["tolerance_mm"]))
    if not math.isclose(
            margin, expected_margin, rel_tol=1e-12, abs_tol=1.1e-6):
        return False
    return True

@dataclass
class Finding:
    finding_id: str
    a: dict
    b: dict
    pair_class: str
    signed_distance_mm: float
    #: Review #6/#14: this is the overlap depth of the HULLS, not of body
    #: penetration. The former name `physical_penetration_mm` promised a fact
    #: about the building.
    hull_overlap_depth_mm: float
    clearance_mm: float
    clearance_deficit_mm: float
    #: For ranking and UI only (review #14). NOT a completeness gate: 25 mm
    #: was never a proven tolerance of the bounding hull.
    ranking_tol_mm: float
    hull_grade: str
    #: The KIND of the pair: an ordinary intersection or a DUPLICATE (two
    #: elements in the same place). This is a geometric diagnostic of the
    #: model, not permission to delete an element: semantics and
    #: dependencies lie outside this detector.
    pair_kind: str
    #: Axis of RELATION: overlap | contact | separated.
    hull_relation: str
    #: Axis of PROOF-STRENGTH: confirmed | possible. `confirmed` is derived
    #: ONLY from `physical_overlap_proof`, not from the outer-hull grade.
    verdict: str
    physical_overlap_proof: PhysicalOverlapProof
    #: Exact-body equality has a separate proof: physical overlap (including
    #: certified inner overlap) does not imply equality.  Even equality is not
    #: a BIM-deletion capability.
    exact_body_equality_proof: dict[str, Any]
    #: Review #6: a certified separating translation, NOT a minimal vector.
    certified_separating_translation_mm: tuple[float, float, float] | None
    separation_is_lower_bound: bool
    ranking_significant: bool
    translation_unavailable_reason: str | None = None

    def as_dict(self) -> dict:
        def r(x):
            return G._norm_zero(round(float(x), 3))

        def rsd(x):
            """The signed distance is rounded MORE PRECISELY than the other fields.

            Measurement 10.08.2026: when rounded to 3 digits, 1 490 findings out of
            209 395 (`sklnk_eom_r26_v8`) published `signed_distance_mm: 0.0`
            while at the same time publishing `hull_relation: overlap` — the reader
            could not reproduce the relation from the published number, even though
            the relation is in fact derived from it (`relation_of`). The actual
            values there are -1.6e-05…-3.9e-04 mm, i.e. the relation was decided by
            digits that were no longer present in the report.

            Nine digits cover the `EPS_NUMERIC_MM` = 1e-6 threshold with a margin of
            three orders of magnitude, so `relation_of(опубликованное)` matches the
            published `hull_relation` identically. The other fields are still
            rounded to 3 digits as before: the relation does not depend on them.
            """
            return G._norm_zero(round(float(x), 9))

        #: 🔴 THE SAME REASON AS FOR `rsd`, NOW ALSO FOR TWO FIELDS (F-088,
        #: 29.08.2026). The 10.08 fix gave `signed_distance_mm` nine digits,
        #: but `hull_overlap_depth_mm` is the SAME `-sd` (`max(0.0, -sd)`), and
        #: `certified_separating_translation_mm` is checked against
        #: `geom.SEP_EPS_MM = 1e-6` and is built RIGHT UP AGAINST that boundary
        #: (`geom.py`, the fallback bounding-box candidate `bhi[k] - alo[k] + EPS`).
        #: Three digits lose up to 5e-4 mm — 500 times more than the certificate's
        #: tolerance, and the vector (0, 0, -0.0004), which SEPARATES the pair,
        #: was published as [0, 0, 0], which does NOT separate it, with
        #: `translation_unavailable_reason = None`, i.e. "a move exists". The same
        #: rounding printed the depth as `0.0` while `hull_relation: "overlap"` —
        #: two fields about ONE quantity silently diverged. The nine digits are
        #: taken from `rsd`, not invented anew: the same justification, the same
        #: threshold, the same three-order-of-magnitude margin. The other fields
        #: (`clearance_mm`, `clearance_deficit_mm`, `ranking_tol_mm`) have no
        #: certificate and are still rounded as before.
        rcert = rsd
        v = self.certified_separating_translation_mm
        return {
            "finding_id": self.finding_id,
            "a": self.a, "b": self.b,
            "pair_class": self.pair_class,
            "signed_distance_mm": rsd(self.signed_distance_mm),
            "separation_is_lower_bound": self.separation_is_lower_bound,
            "hull_overlap_depth_mm": rcert(self.hull_overlap_depth_mm),
            "clearance_mm": r(self.clearance_mm),
            "clearance_deficit_mm": r(self.clearance_deficit_mm),
            "ranking_tol_mm": r(self.ranking_tol_mm),
            "ranking_significant": self.ranking_significant,
            "hull_grade": self.hull_grade,
            "pair_kind": self.pair_kind,
            "hull_relation": self.hull_relation,
            "verdict": self.verdict,
            "physical_overlap_proof": self.physical_overlap_proof.as_dict(),
            "exact_body_equality_proof": self.exact_body_equality_proof,
            "certified_separating_translation_mm": (
                None if v is None else [rcert(c) for c in v]),
            "translation_unavailable_reason": self.translation_unavailable_reason,
        }


def _verify_exact_pair_payload(proof: Mapping[str, Any]) -> bool:
    """Check the chain of the EXACT phase: volume, relation, tolerance policy.

    Inner certificates are neither required nor read here: the exact phase
    judges BODIES, not second hulls, and it has no right to assert another
    basis's claim. The numbers are cross-checked against each other so that
    an edited JSON does not pass: `clear` must carry zero volume,
    `contained`/`intersect` a positive one, and `refuted` is possible ONLY
    for `clear`.
    """
    status = proof.get("status")
    relation = proof.get("exact_relation")
    volume = _proof_number(proof.get("exact_overlap_volume_mm3"))
    digest = proof.get("tolerance_policy_digest")
    if (status not in ("confirmed", "refuted")
            or relation not in _EXACT.RELATIONS
            or volume is None or volume < 0.0
            or not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or proof.get("inner_relation") is not None):
        return False
    if relation == "clear":
        return status == "refuted" and volume == 0.0 and proof.get("exact_depth_mm") is None
    return status == "confirmed" and volume > 0.0 and proof.get("exact_gap_mm") is None


def _side(rec: H.HullRecord) -> dict:
    """Both sides of a finding are addressed the same way (review #15): what
    exactly names the element is visible without guessing."""
    return {"source_element_id": rec.source_id, "category": rec.category,
            "label": rec.label, "hull_grade": rec.grade,
            "hull_source": rec.hull_source, "level_id": rec.level_id,
            "type_name": rec.type_name,
            # Wave D2-A: `hull_source: axis_section` does not say WHERE the
            # number was taken from. A pipe's diameter and a tray's half-diagonal
            # are different justifications for the same capsule, and the
            # finding is obliged to distinguish them.
            "section_source": rec.section_source,
            "section_radius_mm": (
                None if rec.section_radius_mm is None
                else G._norm_zero(round(float(rec.section_radius_mm), 3)))}


def pair_grade(a: H.HullRecord, b: H.HullRecord) -> str:
    """The pair's grade follows the worse side: the proof strength can never
    exceed the coarser of the two hulls."""
    order = {g: i for i, g in enumerate(H.GRADES)}
    return H.GRADES[max(order[a.grade], order[b.grade])]


#: Tolerance for hull coincidence: numeric noise from the feet-to-mm
#: conversion, and nothing more. Two elements whose bounding boxes coincide
#: within it stand in the same place — a STRUCTURAL sign, no type names
#: involved.
#:
#: The same tolerance is used to compare AXES and BASES (below): these are
#: the same millimeters from the same feet conversion, they have no separate
#: threshold and none could arise for them.
DUPLICATE_EPS_MM = 1.0
# ``DUPLICATE_EPS_MM`` is deliberately a UI/classification tolerance: it may
# group nearly coincident hulls for review.  Destructive equality is a
# different proposition.  Reusing one millimetre there would allow deleting
# an exact body displaced by 0.5 mm, so the sealed capability uses only the
# numeric kernel epsilon.
EXACT_BODY_EQUALITY_EPS_MM = EPS_NUMERIC_MM

PAIR_KINDS = ("interference", "coincident_duplicate")

EXACT_BODY_EQUALITY_SCHEMA = "clash-exact-body-equality/1"
_EXACT_BODY_EQUALITY_PAYLOAD_KEYS = frozenset({
    "schema_version", "status", "outcome", "reason", "comparison",
    "tolerance_mm", "subject_a", "subject_b", "a", "b",
})
_EXACT_BODY_SIDE_KEYS = frozenset({
    "subject_source_id", "category", "grade", "hull_source",
    "hull_evidence", "hull_digest",
})
_EXACT_BODY_AUTHORITY_SIDE_KEYS = frozenset({
    "body_source_digest", "body_source_revision", "certificate_digest",
})


def _points_match(pa, pb, eps: float) -> bool:
    """Two sequences of points — coordinate-wise and in the same order."""
    return len(pa) == len(pb) and all(
        len(u) == len(v) and all(abs(x - y) <= eps for x, y in zip(u, v))
        for u, v in zip(pa, pb))


def hulls_coincide(a: H.HullRecord, b: H.HullRecord, *,
                   eps: float = DUPLICATE_EPS_MM) -> bool | None:
    """Whether the hull BODIES coincide. `None` — the hulls do not know.

    The bounding box does not answer this question: for the two diagonals of
    a square it is the SAME ONE (reproduced 09.08 — capsules (0,0,0)→(4000,4000,0)
    and (4000,0,0)→(0,4000,0) with r=200 both give ((-200,-200,-200),(4200,4200,200))).
    But where the hull is built from something other than a box, the missing
    piece already lies within it:

    * a capsule carries an AXIS and a radius — the body is fully defined by
      them; traversing the axis in the opposite direction gives the same
      body, so the comparison is symmetric;
    * a prism carries a BASE and [z0, z1]; the base is convex, so it is
      defined by the SET of vertices, not by their order — we compare sets.

    `None` (a bounding box on both sides, or hulls of different kinds) means
    exactly "nothing to say", not "they do not match": inventing an axis for
    a box is forbidden. What to do with this answer is decided by
    `pair_kind_of`, and how loudly to speak of it — by
    `duplicate_claim_is_proven`.
    """
    ha, hb = a.hull, b.hull
    if isinstance(ha, G.Capsule) and isinstance(hb, G.Capsule):
        if abs(ha.radius - hb.radius) > eps:
            return False
        return (_points_match(ha.path, hb.path, eps)
                or _points_match(ha.path, tuple(reversed(hb.path)), eps))
    za, zb = G.z_span(ha), G.z_span(hb)
    fa, fb = G.footprint_pieces(ha), G.footprint_pieces(hb)
    prism_like = (isinstance(ha, (G.Prism, G.PrismSet))
                  and isinstance(hb, (G.Prism, G.PrismSet)))
    if prism_like and za is not None and zb is not None:
        if abs(za[0] - zb[0]) > eps or abs(za[1] - zb[1]) > eps:
            return False
        # For a union the body is defined by a SET of pieces, so the sets
        # are compared: piece order is a trace of the sweep, not a fact about
        # the body, and sorting removes it the same way sorting vertices
        # removes the traversal order of a convex base. Without this branch,
        # two slabs with matching bounding boxes and DIFFERENT voids would get
        # `None`, i.e. "nothing to say", and `pair_kind_of` would declare them
        # a duplicate — advice to delete a real element.
        if len(fa) != len(fb):
            return False
        # 🔴 PIECES ARE COMPARED, NOT THEIR MERGER (03.09.2026). The previous
        # revision sorted the pieces and then MERGED all their vertices into
        # one list — and the piece boundary took no part in the comparison at
        # all. Two DIFFERENT bodies, whose pieces are different blocks of the
        # same sorted vertex sequence, were declared coincident: eight
        # vertices in convex position, split 4+4 versus 3+5, each piece convex
        # per `decompose.loop_is_convex` — `True`, and `pair_kind_of` answered
        # `coincident_duplicate`, i.e. advice to delete a real element. Exactly
        # the outcome the branch above was written against. Piece order is
        # still NOT a fact about the body, and `sorted` removes it; the piece
        # BOUNDARY is a fact, and it is preserved.
        #
        # WHAT IS STILL NOT CLOSED HERE, AND IS NOT FIXED BY THIS CHANGE:
        # the sort is EXACT, while the comparison uses `eps`. Two nearly equal
        # vertices can end up in different order and produce a false "no". The
        # defect is pre-existing, one-directional (toward a spurious
        # `interference` rather than a spurious duplicate), and did not arise
        # on this branch.
        canonical_a = sorted(sorted(f) for f in fa)
        canonical_b = sorted(sorted(f) for f in fb)
        return all(_points_match(piece_a, piece_b, eps)
                   for piece_a, piece_b in zip(canonical_a, canonical_b))
    return None


def _canonical_exact_hull(hull: G.Hull) -> dict[str, Any] | None:
    """Canonical evidence for hull types whose equality kernel is explicit."""

    if isinstance(hull, G.Capsule):
        if (not math.isfinite(float(hull.radius)) or hull.radius <= 0.0
                or not hull.path):
            return None
        path = tuple(tuple(G._norm_zero(float(value)) for value in point)
                     for point in hull.path)
        if any(len(point) != 3 or any(not math.isfinite(v) for v in point)
               for point in path):
            return None
        reverse = tuple(reversed(path))
        canonical_path = min(path, reverse)
        return {
            "kind": "capsule",
            "path_mm": [list(point) for point in canonical_path],
            "radius_mm": G._norm_zero(float(hull.radius)),
        }
    if isinstance(hull, (G.Prism, G.PrismSet)):
        span = G.z_span(hull)
        pieces = G.footprint_pieces(hull)
        if span is None or not pieces or any(
                not math.isfinite(float(value)) for value in span):
            return None
        canonical_pieces = []
        for piece in pieces:
            points = [
                [G._norm_zero(float(x)), G._norm_zero(float(y))]
                for x, y in piece]
            if (len(points) < 3
                    or any(not math.isfinite(v) for point in points
                           for v in point)):
                return None
            canonical_pieces.append(sorted(points))
        canonical_pieces.sort()
        return {
            "kind": "prismatic",
            "pieces_mm": canonical_pieces,
            "z0_mm": G._norm_zero(float(span[0])),
            "z1_mm": G._norm_zero(float(span[1])),
        }
    return None


def _evidence_digest(evidence: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_evidence_coincides(
        a: Mapping[str, Any], b: Mapping[str, Any], *, eps: float) -> bool:
    """Re-evaluate the equality relation over sealed canonical evidence."""

    if a.get("kind") != b.get("kind"):
        return False
    if a.get("kind") == "capsule":
        ra, rb = _proof_number(a.get("radius_mm")), _proof_number(
            b.get("radius_mm"))
        pa, pb = a.get("path_mm"), b.get("path_mm")
        return (ra is not None and rb is not None and abs(ra - rb) <= eps
                and isinstance(pa, list) and isinstance(pb, list)
                and _points_match(pa, pb, eps))
    if a.get("kind") == "prismatic":
        za0, za1 = _proof_number(a.get("z0_mm")), _proof_number(a.get("z1_mm"))
        zb0, zb1 = _proof_number(b.get("z0_mm")), _proof_number(b.get("z1_mm"))
        pa, pb = a.get("pieces_mm"), b.get("pieces_mm")
        if (None in (za0, za1, zb0, zb1)
                or not isinstance(pa, list) or not isinstance(pb, list)
                or len(pa) != len(pb)
                or abs(za0 - zb0) > eps or abs(za1 - zb1) > eps):
            return False
        # THE SAME BOUNDARY AS IN `hulls_coincide`, FOR THE SAME REASON:
        # merging the pieces erased the one fact that distinguishes two
        # partitions of the same vertex set. HERE THIS WAS UNREACHABLE FROM
        # PROD — printing the evidence requires an analytic digest, and its
        # closed table (`hulls._canonical_analytic_hull`) knows exactly two
        # kinds, Aabb and Prism, i.e. EXACTLY ONE piece, for which merging and
        # piecewise comparison are identical. But unreachability is a property
        # of the NEIGHBORING module, not of this comparison: it cannot be
        # relied on as a guard, and the closed table will open before anyone
        # remembers this line.
        if (not all(isinstance(piece, list) for piece in pa)
                or not all(isinstance(piece, list) for piece in pb)):
            return False
        return all(_points_match(piece_a, piece_b, eps)
                   for piece_a, piece_b in zip(pa, pb))
    return False


def _exact_body_side(
        record: H.HullRecord, *, include_evidence: bool) -> dict[str, Any]:
    evidence = _canonical_exact_hull(record.hull) if include_evidence else None
    digest = None
    if evidence is not None:
        try:
            digest = _evidence_digest(evidence)
        except (TypeError, ValueError, OverflowError):
            evidence = None
    side = {
        "subject_source_id": record.source_id,
        "category": record.category,
        "grade": record.grade,
        "hull_source": record.hull_source,
        "hull_evidence": evidence,
        "hull_digest": digest,
    }
    if include_evidence:
        assessment = H.assess_inner_hull(record)
        certificate = assessment.certificate
        side.update({
            "body_source_digest": (
                None if certificate is None
                else certificate.body_source_digest),
            "body_source_revision": (
                None if certificate is None
                else certificate.body_source_revision),
            "certificate_digest": (
                None if certificate is None
                else certificate.certificate_digest),
        })
    return side


def _exact_body_authority_reason(record: H.HullRecord) -> str | None:
    """Require issued evidence that the advertised exact hull is the body."""

    assessment = H.assess_inner_hull(record)
    if assessment.status == "absent":
        return "exact_body_authority_absent"
    if assessment.status != "valid":
        return f"exact_body_authority_invalid:{assessment.reason}"
    certificate = assessment.certificate
    if certificate is None or assessment.hull is None:
        return "exact_body_authority_invalid"
    try:
        outer_digest = H.analytic_hull_digest(record.hull)
        inner_digest = H.analytic_hull_digest(assessment.hull)
    except ValueError:
        return "exact_body_authority_geometry_unsupported"
    if (inner_digest != outer_digest
            or certificate.inner_digest != outer_digest
            or certificate.outer_digest != outer_digest
            or certificate.body_source_digest != outer_digest):
        return "exact_body_authority_not_equal_to_hull"
    return None


def exact_body_equality_proof(
        a: H.HullRecord, b: H.HullRecord, *,
        eps: float = EXACT_BODY_EQUALITY_EPS_MM) -> dict[str, Any]:
    """Issue sealed equality only when both hulls are the exact bodies.

    ``grade=exact`` is the producer contract ``Hull == Body``.  Inner-overlap
    evidence is deliberately irrelevant: two bodies can overlap without
    being equal.  Ordinary production producers currently emit no exact
    grade, so destructive duplicate advice remains unreachable there.
    """

    reason = None
    if a.grade != "exact" or b.grade != "exact":
        reason = "exact_body_contract_absent"
    elif a.category != b.category:
        reason = "category_mismatch"
    else:
        authority_a = _exact_body_authority_reason(a)
        authority_b = _exact_body_authority_reason(b)
        if authority_a is not None or authority_b is not None:
            reason = ";".join(filter(None, (
                None if authority_a is None else f"a:{authority_a}",
                None if authority_b is None else f"b:{authority_b}",
            )))
    if reason is None and hulls_coincide(a, b, eps=eps) is not True:
        reason = "exact_hulls_not_equal"
    # Do not duplicate hull geometry into every ordinary finding.  Canonical
    # body evidence is materialized only after the cheap exact/category/
    # equality gates have all passed; current production (no exact producer)
    # therefore pays only a small named not-proven packet.
    side_a = _exact_body_side(a, include_evidence=reason is None)
    side_b = _exact_body_side(b, include_evidence=reason is None)
    if (reason is None
            and (side_a["hull_evidence"] is None
                 or side_b["hull_evidence"] is None)):
        reason = "exact_hull_evidence_unavailable"
    elif (reason is None and not _canonical_evidence_coincides(
            side_a["hull_evidence"], side_b["hull_evidence"], eps=eps)):
        reason = "canonical_exact_hulls_not_equal"
    payload = {
        "schema_version": EXACT_BODY_EQUALITY_SCHEMA,
        "status": "proven" if reason is None else "not_proven",
        "outcome": "equal" if reason is None else "unknown",
        "reason": reason,
        "comparison": "hulls_coincide/v1",
        "tolerance_mm": G._norm_zero(float(eps)),
        "subject_a": a.source_id,
        "subject_b": b.source_id,
        "a": side_a,
        "b": side_b,
    }
    if reason is not None:
        return payload
    return H.seal_serialized_exact_body_equality_proof(
        payload, authority=H._EXACT_BODY_EQUALITY_ISSUANCE_AUTHORITY)


def verify_serialized_exact_body_equality_proof(
        proof: Mapping[str, Any], *, subject_a: str, subject_b: str,
        category_a: str, category_b: str) -> bool:
    """Verify sealed exact-body equality from untrusted serialized data."""

    if (not isinstance(proof, Mapping)
            or not H.verify_serialized_exact_body_equality_integrity(
                proof, payload_keys=_EXACT_BODY_EQUALITY_PAYLOAD_KEYS)):
        return False
    tolerance = _proof_number(proof.get("tolerance_mm"))
    if (proof.get("schema_version") != EXACT_BODY_EQUALITY_SCHEMA
            or proof.get("status") != "proven"
            or proof.get("outcome") != "equal"
            or proof.get("reason") is not None
            or proof.get("comparison") != "hulls_coincide/v1"
            or tolerance != EXACT_BODY_EQUALITY_EPS_MM
            or proof.get("subject_a") != subject_a
            or proof.get("subject_b") != subject_b
            or category_a != category_b):
        return False
    for side_name, expected_subject, expected_category in (
            ("a", subject_a, category_a), ("b", subject_b, category_b)):
        side = proof.get(side_name)
        if (not isinstance(side, Mapping)
                or set(side) != (
                    _EXACT_BODY_SIDE_KEYS | _EXACT_BODY_AUTHORITY_SIDE_KEYS)
                or side.get("subject_source_id") != expected_subject
                or side.get("category") != expected_category
                or side.get("grade") != "exact"
                or not isinstance(side.get("hull_source"), str)
                or not side["hull_source"].strip()
                or not isinstance(side.get("hull_evidence"), Mapping)
                or not isinstance(side.get("hull_digest"), str)
                or len(side["hull_digest"]) != 64
                or not H._is_sha256_digest(side.get("body_source_digest"))
                or not isinstance(side.get("body_source_revision"), str)
                or not side["body_source_revision"].strip()
                or not isinstance(side.get("certificate_digest"), str)
                or len(side["certificate_digest"]) != 64):
            return False
        try:
            digest = _evidence_digest(side["hull_evidence"])
        except (TypeError, ValueError, OverflowError):
            return False
        if digest != side["hull_digest"]:
            return False
    return _canonical_evidence_coincides(
        proof["a"]["hull_evidence"], proof["b"]["hull_evidence"],
        eps=tolerance)


def pair_kind_of(a: H.HullRecord, b: H.HullRecord, *,
                 eps: float = DUPLICATE_EPS_MM) -> str:
    """Duplicate or ordinary intersection. Measurement v19 found two such
    pairs — one axis, one bounding box, different ids.

    Bounding-box coincidence is a NECESSARY condition (bodies coincide ⇒
    their boxes coincide too), but not a sufficient one. So where the hull
    knows more than the box, we ask it: different axes with a shared bounding
    box is not a duplicate, and the advice "delete one of them" on such a
    pair erases a real element.
    """
    if a.category != b.category:
        return "interference"
    alo, ahi = a.bounds()
    blo, bhi = b.bounds()
    if not all(abs(alo[k] - blo[k]) <= eps and abs(ahi[k] - bhi[k]) <= eps
               for k in range(3)):
        return "interference"
    if hulls_coincide(a, b, eps=eps) is False:
        return "interference"
    return "coincident_duplicate"


def duplicate_claim_is_proven(finding: dict) -> bool:
    """Whether the geometric duplicate claim has sealed body-equality proof.

    Public ``pair_kind``, grades and sources are labels, not authority.  Only
    a process-local sealed proof issued from two ``grade=exact`` records can
    return true.  Replayed/tampered JSON and evidence loaded after restart
    fail closed.  Certified inner *overlap* never proves body equality.  This
    predicate deliberately says nothing about semantic/dependency equivalence
    and therefore cannot authorize deletion.
    """

    if finding.get("pair_kind") != "coincident_duplicate":
        return False
    a = finding.get("a")
    b = finding.get("b")
    proof = finding.get("exact_body_equality_proof")
    if (not isinstance(a, Mapping) or not isinstance(b, Mapping)
            or not isinstance(proof, Mapping)):
        return False
    subject_a, subject_b = a.get("source_element_id"), b.get(
        "source_element_id")
    category_a, category_b = a.get("category"), b.get("category")
    if not all(isinstance(value, str) for value in (
            subject_a, subject_b, category_a, category_b)):
        return False
    return verify_serialized_exact_body_equality_proof(
        proof, subject_a=subject_a, subject_b=subject_b,
        category_a=category_a, category_b=category_b)


def relation_of(sd: float, *, eps: float = EPS_NUMERIC_MM) -> str:
    """Hull relation by signed distance (review #14)."""
    if sd < -eps:
        return "overlap"
    if sd <= eps:
        return "contact"
    return "separated"


def certified_inner_overlap_proof(
        a: H.HullRecord, b: H.HullRecord) -> PhysicalOverlapProof:
    """Prove body overlap only through two validated ``Inner ⊆ Body`` hulls.

    A rejected or absent inner witness is evidence about the proof boundary,
    not a narrow-phase failure: the outer finding remains useful and is
    downgraded to ``possible`` with the named reason serialized here.
    """

    aa = H.assess_inner_hull(a)
    bb = H.assess_inner_hull(b)
    if aa.status != "valid" or bb.status != "valid":
        reasons = []
        if aa.status != "valid":
            reasons.append(f"a:{aa.reason}")
        if bb.status != "valid":
            reasons.append(f"b:{bb.reason}")
        return PhysicalOverlapProof(
            status="not_proven", basis=None,
            reason=";".join(reasons) or "inner_evidence_unavailable",
            subject_a=a.source_id, subject_b=b.source_id,
            a=aa.as_dict(), b=bb.as_dict())

    assert aa.hull is not None and bb.hull is not None
    assert aa.certificate is not None and bb.certificate is not None
    sd = G.signed_distance(aa.hull, bb.hull)
    if not math.isfinite(sd):
        return PhysicalOverlapProof(
            status="not_proven", basis=None,
            reason="inner_narrow_unsupported",
            subject_a=a.source_id, subject_b=b.source_id,
            a=aa.as_dict(), b=bb.as_dict())
    relation = relation_of(sd)
    depth = max(0.0, -sd)
    # Certificate uncertainty can only make proof harder.  Tolerances are
    # added rather than used as geometric slack, so no caller can buy a
    # confirmation by widening one.
    margin = (
        float(aa.certificate.error_bound_mm)
        + float(bb.certificate.error_bound_mm)
        + float(aa.certificate.tolerance_mm)
        + float(bb.certificate.tolerance_mm)
        + EPS_NUMERIC_MM)
    if relation == "overlap" and depth > margin:
        return PhysicalOverlapProof(
            status="confirmed", basis="certified_inner_overlap",
            reason=None, subject_a=a.source_id, subject_b=b.source_id,
            a=aa.as_dict(), b=bb.as_dict(),
            inner_relation=relation, inner_signed_distance_mm=sd,
            inner_overlap_depth_mm=depth, required_margin_mm=margin,
            _authority=H._PAIR_PROOF_ISSUANCE_AUTHORITY)
    reason = {
        "contact": "certified_inners_touch_only",
        "separated": "certified_inners_separated",
    }.get(relation, "certified_inner_overlap_within_error_margin")
    return PhysicalOverlapProof(
        status="not_proven", basis=None, reason=reason,
        subject_a=a.source_id, subject_b=b.source_id,
        a=aa.as_dict(), b=bb.as_dict(), inner_relation=relation,
        inner_signed_distance_mm=sd, inner_overlap_depth_mm=depth,
        required_margin_mm=margin)


def exact_overlap_proof(
        a_id: str, b_id: str,
        bodies: Mapping[str, tuple[Any, Any]], *,
        policy: "_EXACT.TolerancePolicy | None" = None,
        budget_ms: float | None = None) -> PhysicalOverlapProof:
    """Sibling of `certified_inner_overlap_proof`: judges BODIES, not hulls.

    The difference from its neighbor is not in strength but in the KIND of
    claim. Inner hulls give only a sufficient condition: overlapping means
    the bodies intersect; not overlapping means nothing. The exact phase
    answers the question in both directions, and so it has a third outcome:
    `refuted`.

    Bodies arrive FROM OUTSIDE (`bodies`, contract `CONTRACT-AB.md`): this
    module does not read the store, does not parse BRep bytes, and does not
    look at previews. Absence of a body is a named refusal, not a silent
    "not found".
    """
    policy = policy or _EXACT.DEFAULT_POLICY
    sides = {"a": bodies.get(a_id), "b": bodies.get(b_id)}
    if sides["a"] is None or sides["b"] is None:
        missing = ",".join(name for name, item in sides.items() if item is None)
        return PhysicalOverlapProof(
            status="not_proven", basis=None,
            reason=f"exact_no_persisted_body:{missing}",
            subject_a=a_id, subject_b=b_id, a={}, b={},
            tolerance_policy_digest=policy.digest)
    verdict = _EXACT.verify_pair(sides["a"][0], sides["b"][0],
                                 sides["a"][1], sides["b"][1],
                                 policy=policy, budget_ms=budget_ms)
    if not verdict.ok:
        # A kernel refusal is NEITHER a refutation NOR a confirmation: the
        # pair remains as the hull phase left it, and the reason is named.
        return PhysicalOverlapProof(
            status="not_proven", basis=None, reason="exact_" + str(verdict.refusal),
            subject_a=a_id, subject_b=b_id, a={}, b={},
            tolerance_policy_digest=policy.digest)
    shared = dict(subject_a=a_id, subject_b=b_id, a={}, b={},
                  exact_relation=verdict.relation,
                  exact_overlap_volume_mm3=verdict.overlap_volume_mm3,
                  exact_depth_mm=verdict.depth_mm,
                  exact_gap_mm=verdict.gap_mm,
                  tolerance_policy_digest=verdict.tolerance_policy_digest,
                  _authority=H._PAIR_PROOF_ISSUANCE_AUTHORITY)
    if verdict.relation == "clear":
        return PhysicalOverlapProof(status="refuted", basis=EXACT_BASIS,
                                    reason=None, **shared)
    return PhysicalOverlapProof(status="confirmed", basis=EXACT_BASIS,
                                reason=None, **shared)


#: Stage B calls the exact phase ONLY on an explicit list of pairs. The
#: default is the broad-phase candidates whose BOTH sides have a stored body.
def exact_eligible_pairs(records: Sequence[H.HullRecord],
                         bodies: Mapping[str, tuple[Any, Any]],
                         pairs: Iterable[tuple[int, int]]
                         ) -> list[tuple[int, int]]:
    return [(i, j) for i, j in pairs
            if records[i].hull_source == "brep" and records[j].hull_source == "brep"
            and records[i].source_id in bodies and records[j].source_id in bodies]


def apply_exact_phase(findings: Sequence[Finding],
                      bodies: Mapping[str, tuple[Any, Any]], *,
                      policy: "_EXACT.TolerancePolicy | None" = None,
                      budget_ms: float | None = None,
                      max_pairs: int | None = None,
                      records: Mapping[str, H.HullRecord] | None = None
                      ) -> tuple[list[Finding], list[str]]:
    """Re-judge ready findings with bodies. The remainder NEVER stays silent.

    Returns `(findings, analysis_limits)`. Finding order is preserved
    byte-for-byte; a pair the exact phase did not touch remains itself.
    The cost is named up front: one check costs 6…1400 ms against 97 µs for
    the hull phase, so a cap on the number of pairs and on time is
    mandatory, not an option.
    """
    policy = policy or _EXACT.DEFAULT_POLICY
    started = time.perf_counter()
    limits: list[str] = []
    out: list[Finding] = []
    checked = 0
    for index, finding in enumerate(findings):
        # The sides of a finding are already PRINTED dicts (`_side`), not
        # hull records: the address is taken from the same place the
        # consumer reads it from.
        a_id = finding.a["source_element_id"]
        b_id = finding.b["source_element_id"]
        if a_id not in bodies or b_id not in bodies:
            out.append(finding)
            continue
        if max_pairs is not None and checked >= max_pairs:
            limits.append(f"exact_pair_limit_reached: проверено {checked}, "
                          f"осталось {len(findings) - index}")
            out.extend(findings[index:])
            break
        spent = (time.perf_counter() - started) * 1000
        if budget_ms is not None and spent >= float(budget_ms):
            limits.append(f"exact_budget_exhausted: потрачено {spent:.1f} мс, "
                          f"осталось {len(findings) - index}")
            out.extend(findings[index:])
            break
        left = None if budget_ms is None else float(budget_ms) - spent
        proof = exact_overlap_proof(a_id, b_id, bodies,
                                    policy=policy, budget_ms=left)
        checked += 1
        if proof.status == "not_proven":
            limits.append(f"{a_id}~{b_id}: {proof.reason}")
            out.append(finding)
            continue
        verdict = "refuted" if proof.status == "refuted" else "confirmed"
        out.append(replace(finding, verdict=verdict, physical_overlap_proof=proof))
    else:
        pass
    if checked:
        limits.append(f"exact_pairs_checked: {checked} из {len(findings)}")
    return out, limits


def evaluate_with_reason(a: H.HullRecord, b: H.HullRecord, *,
                         clearance_mm: float = 0.0
                         ) -> tuple[Finding | None, str | None]:
    """One pair -> (finding or None, reason for the finding's absence).

    Review #11: the non-numeric narrow phase returned `None` SILENTLY,
    indistinguishable from "the pair is clean". Now every None has a name,
    and it is counted.

    Review #14: the grade threshold no longer decides whether there is a
    finding. Hull relation (overlap/contact/separated) is a geometric fact;
    `ranking_tol_mm` remains only for sorting and the UI.
    """
    clearance_mm = _nonnegative_finite(clearance_mm, "clearance_mm")
    sd = G.signed_distance(a.hull, b.hull)
    if not math.isfinite(sd):
        return None, "narrow_unsupported"
    grade = pair_grade(a, b)
    tol = H.TOL_GRADE_MM[grade]
    relation = relation_of(sd)
    deficit = max(0.0, clearance_mm - sd)
    clearance_violation = sd < clearance_mm - EPS_NUMERIC_MM
    if relation == "separated" and not clearance_violation:
        return None, None
    ends = sorted((a, b), key=lambda r: r.source_id)
    lo, hi = ends[0], ends[1]
    physical_proof = certified_inner_overlap_proof(lo, hi)
    equality_proof = exact_body_equality_proof(lo, hi)
    verdict = ("confirmed" if physical_proof.status == "confirmed"
               else "possible")
    # The translation is not published for coarse pairs: the direction of
    # exit from the bounding box proves nothing about the body.
    vec, why = None, None
    if grade in ("exact", "conservative") and relation == "overlap":
        vec = G.certified_separating_translation(lo.hull, hi.hull)
        if vec is None:
            why = G.mtv_unavailable_reason(lo.hull, hi.hull)
        # For a union the translation is NEITHER invented NOR suppressed: it
        # is VERIFIED by the translation (`geom.separates`) in exactly the
        # same way as for a convex pair, and is therefore legitimate. The
        # reason is not written here — the field is called
        # `translation_unavailable_reason` and answers the question "why
        # there is NO move"; filling it in when there IS one would bring back
        # the conflation of two axes into one field, which review #14 was
        # written to remove. How the union's move is worse is stated in
        # `SEPARATION_SEMANTICS` and in
        # `geom.certified_separating_translation`: it separates, but is NOT
        # minimal, and minimality for a non-convex body is no longer proven
        # by bisection.
    # Review #7 is closed by a formula, not by the field's name: in the
    # SEPARATED case the exact Euclidean distance is published
    # (`geom.poly_poly_gap`). The flag remains attached exactly to the
    # quantity that DID NOT STOP being an estimate — the overlap depth of two
    # UNIONS: |MTV(A,B)| ≥ maxᵢⱼ|MTV(Aᵢ,Bⱼ)|, and equality here is guaranteed
    # by nothing.
    union_depth = (relation == "overlap"
                   and any(isinstance(r.hull, G.PrismSet) for r in (lo, hi)))
    return Finding(
        finding_id=f"{lo.source_id}~{hi.source_id}", a=_side(lo), b=_side(hi),
        # The pair's class is an UNORDERED key: sides A/B are ordered by
        # source_id (this is address determinism), but `wall~mullion` and
        # `mullion~wall` are one class, and putting them into two report rows
        # means splitting one number in half at random.
        pair_class="~".join(sorted((lo.label, hi.label))),
        signed_distance_mm=sd,
        separation_is_lower_bound=union_depth,
        hull_overlap_depth_mm=max(0.0, -sd),
        clearance_mm=clearance_mm, clearance_deficit_mm=deficit,
        ranking_tol_mm=tol, ranking_significant=(sd < -tol or deficit > tol),
        hull_grade=grade, pair_kind=pair_kind_of(lo, hi),
        hull_relation=relation, verdict=verdict,
        physical_overlap_proof=physical_proof,
        exact_body_equality_proof=equality_proof,
        certified_separating_translation_mm=vec,
        translation_unavailable_reason=why), None


def evaluate(a: H.HullRecord, b: H.HullRecord, *, clearance_mm: float = 0.0
             ) -> Finding | None:
    return evaluate_with_reason(a, b, clearance_mm=clearance_mm)[0]


# ────────────────────────────────────────────────────────────── orchestration

#: The only permitted pair filters and their names in the canon (review #13).
_SCOPE_BY_FILTER = {
    mvp_pair_filter: "mvp_v2",
    any_physical_pair_filter: "all_physical_diagnostic",
    # The scope of the summary is named here, not substituted at the call
    # site: a report that cannot name its own coverage claims more than it
    # searched.
    cross_model_pair_filter: "cross_model_federation",
    # The scope "what the batch contributed" is named here for the same
    # reason as the summary: a report that cannot name its own coverage
    # claims more than it searched. The count of compared pairs for it is
    # served by `existing.pairs_compared` — an exact formula from two known
    # counts, not a reduction by class, which is unavailable to this filter
    # (see below).
    bundle_vs_document_pair_filter: "bundle_vs_document",
}

#: Filters whose verdict depends ONLY on the record's class
#: `(label, mvp_side)`. Exactly for these is the reduction of
#: `pairs_in_scope` by class representatives legitimate (see `detect`). The
#: list is a precondition, not decoration: a filter that decides based on
#: something else (for example, the model name in `source_id`) must be
#: ABSENT here, otherwise the aggregate will return a plausible wrong number.
_CLASS_DETERMINED_FILTERS = frozenset({mvp_pair_filter, any_physical_pair_filter})

_GEOMETRY_SCOPE_BY_QUERY = {
    "mvp_v2": "mvp",
    "all_physical_diagnostic": "all_eligible",
    "cross_model_federation": "all_eligible",
    "bundle_vs_document": "all_eligible",
}


def scope_id_of(pair_filter) -> str:
    name = getattr(pair_filter, "__name__", "")
    # Function names are labels, not capability identity.  A different
    # callable can freely advertise ``__name__ = 'mvp_pair_filter'`` while
    # dropping every pair, yielding a green completeness report over an empty
    # search.  Only the two canonical function objects own these scopes.
    scope = _SCOPE_BY_FILTER.get(pair_filter)
    if scope is None:
        raise ValueError(
            f"неизвестный фильтр пар {name!r}: область поиска обязана "
            "называться в каноне (ревью №13). Допустимо: "
            f"{sorted(fn.__name__ for fn in _SCOPE_BY_FILTER)}")
    return scope


def completeness_of(
        snapshot: ClashGeometrySnapshot, *, scope_id: str = "mvp_v2",
        candidate_pairs: int | None = None,
        narrow_evaluations: int | None = None,
        narrow_refusals: dict[str, int] | None = None) -> dict:
    """Independent completeness vector for one declared clash query.

    A single boolean used to mean only "no missing MVP hulls".  It therefore
    stayed green when most of the host document was outside extraction, when
    linked geometry was not federated, and when the narrow phase refused a
    candidate.  The four axes below are independent evidence.  The legacy
    ``complete`` bit remains for readers that cannot consume the vector, but
    it is now the conservative AND of every axis and can never hide a gap.

    Without execution counters ``query_scope`` asserts only that the scope is
    canonical and named.  ``detect`` calls this again after the narrow phase,
    proving in the serialized report that every candidate was adjudicated.
    """
    geometry_scope = _GEOMETRY_SCOPE_BY_QUERY.get(scope_id)
    if geometry_scope is None:
        raise ValueError(
            f"unknown clash scope {scope_id!r}; expected one of "
            f"{sorted(_GEOMETRY_SCOPE_BY_QUERY)}")

    c = snapshot.census
    axes = snapshot.coverage_axes(geometry_scope=geometry_scope)
    refusals = dict(sorted((narrow_refusals or {}).items()))
    refused_pairs = sum(refusals.values())
    executed = candidate_pairs is not None or narrow_evaluations is not None
    candidates = 0 if candidate_pairs is None else candidate_pairs
    evaluations = 0 if narrow_evaluations is None else narrow_evaluations
    query_complete = (not executed or (
        candidates == evaluations and refused_pairs == 0))
    axes["query_scope"] = {
        "complete": query_complete,
        "scope_id": scope_id,
        "scope_definition": SCOPES[scope_id],
        "declared": True,
        "evaluation_status": (
            "not_run" if not executed else
            "complete" if query_complete else "incomplete"),
        "candidate_pairs": candidates if executed else None,
        "narrow_evaluations": evaluations if executed else None,
        "narrow_refusals": refusals,
        "refused_pairs": refused_pairs,
        "note": (
            "complete means the query boundary is canonical and every "
            "broad-phase candidate was adjudicated without a narrow-phase "
            "refusal"),
    }

    incomplete_axes = sorted(
        name for name, axis in axes.items() if not axis["complete"])
    without = sum(c.no_hull_mvp_side.values())
    return {
        "schema_version": "clash-completeness/1",
        "complete": not incomplete_axes,
        "incomplete_axes": incomplete_axes,
        "axes": axes,
        # Backward-compatible MVP diagnostics.  They are not the full proof;
        # new callers must inspect ``axes``.
        "without_hull_on_mvp_side": without,
        "by_side": {side: c.no_hull_mvp_side.get(side, 0)
                    for side in ("mep", "struct")},
        "by_category": dict(sorted(c.no_hull_by_category.items())),
        "note": (
            "legacy complete is the conservative AND of extraction, "
            "federation, query_scope and geometry; inspect axes for causes"),
    }


@dataclass(frozen=True, slots=True)
class Search:
    """A SEARCH THAT HAS NOT YET BECOME A REPORT — with TYPED findings.

    🔴 WHY THIS WAS SET UP, BY THE 19.08.2026 MEASUREMENT. `detect()` builds
    typed `Finding` objects, sorts them — and at the report boundary
    (`"findings": [f.as_dict() for f in findings]`) DISCARDS the types,
    leaving dicts. And the only bridge from clash to the building graph,
    `decompile/graph_clash_query.edge_from_finding`, accepts EXACTLY a typed
    `Finding` and refuses a dict.

    Hence a consequence that read as "a shelved module": `graph_clash_query`
    has zero prod importers not because someone forgot to wire it in, but
    because **its input is unreachable from the detector's prod entry point
    BY CONSTRUCTION**. Verified by execution on `sob62_r23_v5`: the addresses
    match exactly (298 of 298 subjects of the first 400 findings are in the
    graph), and `edge_from_finding` still refuses with `GraphBuildError`.

    WHY THIS IS FIXED HERE, NOT AT THE ADAPTER'S DOOR. The temptation was to
    open a second door on the adapter, "from a dict": its body is wired that
    way anyway (`wire = finding.as_dict()`), and the proof is checked by a
    SERIALIZED verifier. But the `SEPARATED` branch carries a deliberate
    guarantee, spelled out there in words: `PROVEN/SEPARATED` is stamped
    "from the live typed detector object, not from a deserialized mapping".
    The door on types is LOAD-BEARING — accepting a dict there would let a
    forged record stamp a proven separation. So it is this side's obligation
    to hand over types.

    NO SECOND SEARCH WAS SET UP. `search()` and `detect()` both gather from
    one `iter_findings()`: the former keeps types and candidates for
    compatibility, the latter serializes the findings directly. Byte-for-byte
    equality of the report before and after is pinned by a control.
    """

    findings: tuple["Finding", ...]
    records: tuple
    grid: Any
    candidate_pairs: tuple
    narrow_refusals: Mapping[str, int]
    scope_id: str
    clearance_mm: float
    preflight_completeness: Mapping[str, Any]
    timings: Mapping[str, float]


class FindingStream(Iterator["Finding"]):
    """A lazy pass over the broad and narrow phases without a list of all
    candidates.

    The grid and the pair order are deterministic from the start, but the
    next pair and its narrow check execute only on the consumer's request.
    So an early consumer holds an index and one neighborhood in memory, not
    the full report. Completeness after the narrow phase is known only after
    ``exhausted=True``.
    """

    def __init__(self, snapshot: ClashGeometrySnapshot, *,
                 clearance_mm: float = 0.0,
                 pair_filter=mvp_pair_filter,
                 cell_mm: float | None = None,
                 require_complete: bool = False,
                 capture_candidates: bool = False):
        self.snapshot = snapshot
        self.clearance_mm = _nonnegative_finite(
            clearance_mm, "clearance_mm")
        self.scope_id = scope_id_of(pair_filter)
        snapshot.validate()
        self.preflight_completeness = completeness_of(
            snapshot, scope_id=self.scope_id)
        if require_complete and not self.preflight_completeness["complete"]:
            raise SnapshotIntegrityError(
                "поиск неполон по построению; неполные оси: "
                f"{self.preflight_completeness['incomplete_axes']}")

        self.records = tuple(snapshot.records)
        self._t0 = time.perf_counter()
        self.grid = build_grid(
            snapshot.records, cell_mm, slack=self.clearance_mm)
        self._grid_seconds = time.perf_counter() - self._t0
        self._pair_iter = self.grid.iter_candidate_pairs(
            slack=self.clearance_mm, pair_filter=pair_filter,
            records=self.records)
        self._capture_candidates = bool(capture_candidates)
        self._captured_candidates: list[tuple[int, int]] = []
        self.candidate_count = 0
        self.narrow_evaluations = 0
        self.narrow_refusals: dict[str, int] = {}
        self._broad_seconds = 0.0
        self._narrow_seconds = 0.0
        self.exhausted = False
        self.completeness: Mapping[str, Any] | None = None
        self._require_complete = bool(require_complete)
        self._terminal_error: SnapshotIntegrityError | None = None
        self._terminal_error_reported = False

    def __iter__(self) -> "FindingStream":
        return self

    def _finish(self) -> None:
        if self.exhausted:
            return
        self.exhausted = True
        self.completeness = completeness_of(
            self.snapshot, scope_id=self.scope_id,
            candidate_pairs=self.candidate_count,
            narrow_evaluations=self.narrow_evaluations,
            narrow_refusals=self.narrow_refusals)
        if self._require_complete and not self.completeness["complete"]:
            self._terminal_error = SnapshotIntegrityError(
                "поиск неполон после узкой фазы; неполные оси: "
                f"{self.completeness['incomplete_axes']}")

    def __next__(self) -> "Finding":
        if self.exhausted:
            if (self._terminal_error is not None
                    and not self._terminal_error_reported):
                self._terminal_error_reported = True
                raise self._terminal_error
            raise StopIteration
        while True:
            broad_started = time.perf_counter()
            try:
                pair = next(self._pair_iter)
            except StopIteration:
                self._broad_seconds += time.perf_counter() - broad_started
                self._finish()
                if self._terminal_error is not None:
                    self._terminal_error_reported = True
                    raise self._terminal_error
                raise
            self._broad_seconds += time.perf_counter() - broad_started
            self.candidate_count += 1
            self.narrow_evaluations += 1
            if self._capture_candidates:
                self._captured_candidates.append(pair)

            narrow_started = time.perf_counter()
            try:
                i, j = pair
                finding, why = evaluate_with_reason(
                    self.records[i], self.records[j],
                    clearance_mm=self.clearance_mm)
            finally:
                self._narrow_seconds += time.perf_counter() - narrow_started
            if finding is not None:
                return finding
            if why:
                self.narrow_refusals[why] = (
                    self.narrow_refusals.get(why, 0) + 1)

    @property
    def captured_candidate_pairs(self) -> tuple[tuple[int, int], ...]:
        if not self._capture_candidates:
            raise RuntimeError("candidate capture was not requested")
        return tuple(sorted(self._captured_candidates))

    @property
    def timings(self) -> Mapping[str, float]:
        # The old Search published four marks and consumers took their
        # differences.  The stream interleaves broad/narrow, so we build
        # equivalent cumulative marks from separately measured durations.
        t_grid = self._t0 + self._grid_seconds
        t_broad = t_grid + self._broad_seconds
        t_narrow = t_broad + self._narrow_seconds
        return MappingProxyType({"t0": self._t0, "grid": t_grid,
                                 "broad": t_broad, "narrow": t_narrow})


def iter_findings(snapshot: ClashGeometrySnapshot, *,
                  clearance_mm: float = 0.0,
                  pair_filter=mvp_pair_filter,
                  cell_mm: float | None = None,
                  require_complete: bool = False,
                  capture_candidates: bool = False) -> FindingStream:
    """Return a lazy typed stream of findings in canonical order."""
    return FindingStream(
        snapshot, clearance_mm=clearance_mm, pair_filter=pair_filter,
        cell_mm=cell_mm, require_complete=require_complete,
        capture_candidates=capture_candidates)


def search(snapshot: ClashGeometrySnapshot, *, clearance_mm: float = 0.0,
           pair_filter=mvp_pair_filter, cell_mm: float | None = None,
           require_complete: bool = False) -> Search:
    """The same stream as `detect()`, but gathered with types and pairs."""
    stream = iter_findings(
        snapshot, clearance_mm=clearance_mm, pair_filter=pair_filter,
        cell_mm=cell_mm, require_complete=require_complete,
        capture_candidates=True)
    findings = list(stream)
    findings.sort(key=lambda f: (f.finding_id, f.pair_class))
    return Search(
        findings=tuple(findings),
        records=stream.records,
        grid=stream.grid,
        candidate_pairs=stream.captured_candidate_pairs,
        narrow_refusals=MappingProxyType(dict(stream.narrow_refusals)),
        scope_id=stream.scope_id,
        clearance_mm=stream.clearance_mm,
        preflight_completeness=stream.preflight_completeness,
        timings=stream.timings,
    )


def detect(snapshot: ClashGeometrySnapshot, *, clearance_mm: float = 0.0,
           pair_filter=mvp_pair_filter, cell_mm: float | None = None,
           require_complete: bool = False) -> dict:
    """Snapshot -> report. Read-only from start to finish.

    Review #11: the snapshot is checked ON INPUT. A detector that keeps
    working on a census that has not converged will find zero clashes and
    look healthy.

    `require_complete` (R5 reds): a caller that needs a COMPLETE search must
    have a way to demand it. By default the report prints incompleteness
    loudly but does not stop the work — otherwise today's facade would stop
    counting entirely, and diagnostics along with it.

    THE ONLY ENUMERATION lives in `iter_findings()`: this function only
    gathers it into the old report. `search()` gathers the same stream
    together with types and the pair list for compatibility; see the
    `Search` docstring.
    """
    stream = iter_findings(
        snapshot, clearance_mm=clearance_mm, pair_filter=pair_filter,
        cell_mm=cell_mm, require_complete=require_complete)
    findings = list(stream)
    findings.sort(key=lambda f: (f.finding_id, f.pair_class))
    clearance_mm = stream.clearance_mm
    scope = stream.scope_id
    preflight_completeness = stream.preflight_completeness
    records = stream.records
    grid = stream.grid
    candidate_count = stream.candidate_count
    narrow_refusals = dict(stream.narrow_refusals)
    timings = stream.timings
    t0 = timings["t0"]
    t_grid = timings["grid"]
    t_broad = timings["broad"]
    t_narrow = timings["narrow"]
    completeness = stream.completeness
    if completeness is None:  # list(stream) exhausts the stream by contract
        raise RuntimeError("finding stream did not publish completeness")
    if require_complete and not completeness["complete"]:
        raise SnapshotIntegrityError(
            "поиск неполон после узкой фазы; неполные оси: "
            f"{completeness['incomplete_axes']}")

    # pairs_in_scope by a class aggregate, NOT by full enumeration:
    # acceptance measurement 28.07 — on the demo tower (90 758 elements,
    # ~50k hulls) a pairwise loop is ~1.25e9 filter calls, the detector did
    # not survive to an answer in 570 s. Both filters are determined by the
    # record's class (label/mvp_side) — the contract is pinned by a test
    # against full enumeration; the counter is the same one, the number in
    # the report does not change.
    #
    # 🔴 THE REDUCTION HAS A PRECONDITION, AND IT IS NOW DECLARED (14.08.2026).
    # The reduction asks the filter about a class REPRESENTATIVE, not about a
    # pair of records, and is legitimate exactly for filters whose verdict
    # depends only on `(label, mvp_side)`. `cross_model_pair_filter` decides
    # by the MODEL NAME in `source_id`; the representatives of both sides
    # come from whichever parse happened to be first — and the aggregate
    # honestly answered ZERO next to 58 280 findings and 59 937 pairs
    # considered. A zero born of a violated precondition is indistinguishable
    # from an honest zero: the very silently-wrong result the whole detector
    # is built against. So a filter not declared class-based gets `None` and
    # a NAMED reason instead of a number — the reader must see "not counted",
    # not "none at all".
    class_counts: dict = {}
    class_rep: dict = {}
    for r in records:
        key = (r.label, r.mvp_side)
        class_counts[key] = class_counts.get(key, 0) + 1
        class_rep.setdefault(key, r)
    class_keys = sorted(class_counts)
    eligible_pairs: int | None = 0
    eligible_reason: str | None = None
    if pair_filter is not None and pair_filter not in _CLASS_DETERMINED_FILTERS:
        eligible_pairs = None
        eligible_reason = (
            f"агрегат по классам неприменим к {getattr(pair_filter, '__name__', '?')}: "
            "его вердикт зависит не только от (label, mvp_side), а полный "
            "перебор пар на этих объёмах не считается")
    else:
        for i, ka in enumerate(class_keys):
            for kb in class_keys[i:]:
                if pair_filter is not None and not pair_filter(
                        class_rep[ka], class_rep[kb]):
                    continue
                if ka == kb:
                    n = class_counts[ka]
                    eligible_pairs += n * (n - 1) // 2
                else:
                    eligible_pairs += class_counts[ka] * class_counts[kb]

    # 🔴 A SKIP DUE TO A MISSING ADDRESS DOES NOT STAY SILENT (03.09.2026).
    # `cross_model_pair_filter` drops a pair where even one side carries no
    # model name — otherwise it would invent a membership for it. But "zero
    # findings because there are no addresses" and "zero findings because the
    # models do not interfere with each other" are DIFFERENT facts, and
    # before this line they printed identically. Fixing the filter without
    # this note would simply have moved the silently-wrong result from one
    # edge to the other.
    addressless_reason: str | None = None
    if pair_filter is cross_model_pair_filter:
        addressless = sum(1 for r in records
                          if model_key_of(r.source_id) is None)
        if addressless:
            addressless_reason = (
                f"cross_model_federation: {addressless} из {len(records)} "
                "оболочек пришли с адресом БЕЗ имени модели "
                f"(`<модель>{MODEL_SEPARATOR}<id>`); пары с такой стороной в "
                "область НЕ входят — это названное отсутствие адреса, а не "
                "«модели не мешают друг другу»")
    return {
        "schema_version": REPORT_SCHEMA,
        "origin": snapshot.origin,
        "census": snapshot.census.as_dict(),
        "by_grade": snapshot.by_grade(),
        "coverage_matrix": H.coverage_matrix(),
        "vocabulary": vocabulary_audit(clearance_mm=clearance_mm),
        "search": {
            "scope_id": scope,
            "scope_definition": SCOPES[scope],
            "completeness": completeness,
            "clearance_mm": clearance_mm,
            "hulls": len(records),
            "pairs_in_scope": eligible_pairs,
            "candidate_pairs": candidate_count,
            "narrow_evaluations": stream.narrow_evaluations,
            "narrow_refusals": dict(sorted(narrow_refusals.items())),
            "separation_semantics": SEPARATION_SEMANTICS,
            "grid": grid.stats,
        },
        "join_manifest": snapshot.join_manifest(),
        # Run telemetry, NOT a fact about the building: one input must
        # produce byte-for-byte one canonical report, and a wall clock gives
        # that only by accident (acceptance measurement 28.07: the agent's
        # golden carried 0.1 ms, the lead's run — 0.0). `dumps()` does not
        # serialize an underscore-prefixed key.
        "_timings_ms": {"grid": round((t_grid - t0) * 1000, 1),
                        "broad": round((t_broad - t_grid) * 1000, 1),
                        "narrow": round((t_narrow - t_broad) * 1000, 1)},
        "overlap_depth": overlap_depth_histogram(f.as_dict() for f in findings),
        "verdict_counts": dict(collections.Counter(f.verdict for f in findings)),
        "pair_kind_counts": dict(sorted(
            collections.Counter(f.pair_kind for f in findings).items())),
        "relation_counts": dict(sorted(
            collections.Counter(f.hull_relation for f in findings).items())),
        "pair_class_counts": dict(sorted(
            collections.Counter(f.pair_class for f in findings).items())),
        "findings": [f.as_dict() for f in findings],
        "notes": [
            "raw_interference: легальные отверстия, гильзы и соединения НЕ "
            "исключены — legal_relation_index появится в D2 (ревью №20).",
            "verdict=possible означает пересечение ОБОЛОЧЕК, а не тел; "
            "ход ремонта из него строить нельзя (ревью №14).",
            "Это не оракульный замер: recall/precision против "
            "ElementIntersectsElementFilter — волна D2 (§6).",
            "КОРПУС ОДНОРАЗДЕЛЬНЫЙ, и это ограничивает КАЖДОЕ число точности "
            "ниже. В сохранённых разборах стороны MVP почти никогда не "
            "встречаются в одной модели: `snowdon_plumb_v4` — 31 000 оболочек "
            "`mep` против 5 `struct`, фасад и `k2_ar_rd` — 0 `mep`. Поэтому "
            "область `mvp_v2` на этом складе почти пуста, а все замеры "
            "точности сняты в `all_physical_diagnostic`, где ПОДАВЛЯЮЩЕЕ "
            "большинство перекрытий — законные узлы сборки (дверь в стене, "
            "панель в витраже, примыкание плиты к стене), а не конфликты. "
            "МЕЖРАЗДЕЛЬНЫЙ клеш на этом корпусе НЕ ИЗМЕРЕН: для него нужны "
            "связанные модели, а их элементы оболочек не получают "
            "(`census.linked_elements_unscored`).",
        # THE REASON TRAVELS IN `notes`, NOT AS A SEPARATE KEY: `search` is
        # part of the canonical report, and a new key would shift the
        # baseline for every reader for the sake of a field that is almost
        # always empty. An empty reason is never visible — the list remains
        # byte-for-byte unchanged.
        ] + ([eligible_reason] if eligible_reason else [])
          + ([addressless_reason] if addressless_reason else []),
    }



#: `confirmed` is structurally reachable through the dual certificate
#: contract, while automatic production extraction of inner hulls is still a
#: named gap.  This distinction matters: the word exists and is executable,
#: but ordinary outer-only snapshots continue to produce zero confirmations.
VERDICT_REQUIREMENTS: dict[str, str] = {
    "confirmed": (
        "requires positive-volume overlap of two validated certified inner "
        "subsets (`physical_overlap_proof.basis=certified_inner_overlap`); "
        "production builders do not mint inner certificates yet"),
}

#: Relations that are not always reachable. `separated` enters a finding
#: only when a positive `clearance_mm` is given: without it a separated
#: pair never becomes a finding at all (`evaluate_with_reason`).
CONDITIONAL_RELATIONS: dict[str, str] = {
    "separated": "только при clearance_mm > 0: это нарушение ЗАЗОРА, а не "
                 "пересечение",
}


def vocabulary_audit(*, clearance_mm: float = 0.0) -> dict:
    """What is REACHABLE from the report dict, and what is not, and why.

    This exists because a schema that promises an outcome the code cannot
    produce lies silently: the reader sees `confirmed` in the list of
    verdicts and expects proven clashes that will never come. A zero that
    cannot be told apart from an impossibility is not a fact but a
    decoration.
    """
    grades = H.grade_reachability()
    verdicts = {
        v: {"reachable": True, "reason": VERDICT_REQUIREMENTS.get(v, "")}
        for v in VERDICTS
    }
    relations = {}
    for r in HULL_RELATIONS:
        cond = CONDITIONAL_RELATIONS.get(r)
        relations[r] = {"reachable": True if cond is None else clearance_mm > 0.0,
                        "reason": cond or ""}
    return {
        "hull_grades": grades,
        "verdicts": verdicts,
        "hull_relations": relations,
        "pair_kinds": {k: {"reachable": True, "reason": ""} for k in PAIR_KINDS},
        "note": ("недостижимое НЕ удалено из словаря намеренно: удаление "
                 "сделало бы старые отчёты нечитаемыми, а молчание — "
                 "неотличимым от нуля. Схема обязана называть невозможность "
                 "невозможностью."),
    }


# ─────────────────────────────────────────── overlap depth as a DISTRIBUTION

#: WHY THERE IS NO THRESHOLD FOR "SHALLOW" OVERLAP HERE, ALTHOUGH IT WAS
#: TEMPTING.
#:
#: Measurement 10.08.2026 found on `sklnk_eom_r26_v8` 1 542 findings (1.13% of
#: all overlaps) with depth less than 0.01 mm — fractions of a micrometer that
#: do not exist on a construction site. The temptation to call this "model
#: dust" and draw a line is very strong, and on three buildings it even
#: looked obvious: an empty decade gaped between 1e-3 and 1e-1 mm.
#:
#: THE LINE WAS NOT DRAWN, BECAUSE ON FIVE BUILDINGS THE DATA DOES NOT TEAR.
#: The method is taken from `ground.MOST_USED_MIN_RATIO` — the largest GAP
#: between observations — and it gave the following (the largest
#: multiplicative gap in the sub-millimeter region):
#:
#:   building             overlaps <1mm    gap      at depth
#:   sob62_fas_r23_v19            66        267.8x   0.00015 -> 0.0403 mm
#:   sklnk_eom_r26_v8          1 602         30.1x   0.00487 -> 0.1464 mm
#:   sob62_r23_v5                 18         11.1x   0.0357  -> 0.3953 mm
#:   snowdon_plumb_v5            299          3.5x   0.00778 -> 0.0269 mm
#:   k2_ar_rd_v15             11 001          1.2x   3.46e-05 -> 4.32e-05 mm
#:   POOL (506 137 overlaps)                 1.2x
#:
#: The gaps sit in DIFFERENT places and differ by a factor of 200, and on the
#: building with the richest statistics (`k2_ar_rd_v15`, 11 001 observations)
#: the distribution is CONTINUOUS: the largest gap is 1.2x. The pool is also
#: continuous. The "empty decade" from the first three buildings was an
#: artifact of a small sample, not a property of the data.
#:
#: So what is published here is a DISTRIBUTION, not a verdict: the reader
#: sees that they have 1 542 findings in the sub-micron decade and 95 052 in
#: the 100 mm decade, and judges for themselves. No finding is suppressed or
#: labeled "shallow" — that line would be drawn by our taste, not by
#: measurement, and taste does not count as numbers in this module.
OVERLAP_DEPTH_NOTE = (
    "распределение глубин перекрытия ОБОЛОЧЕК по декадам. Порога «мелкого» "
    "перекрытия модуль не проводит: на пяти зданиях наибольший разрыв в "
    "данных стоит в разных местах (267.8x…1.2x), а на самом обильном "
    "(k2_ar_rd_v15, 11 001 наблюдение) распределение непрерывно. Черта здесь "
    "была бы вкусом, а не замером."
)


def overlap_depth_histogram(findings: Iterable) -> dict:
    """How many overlaps are in each depth DECADE.

    A decade, not a linear bucket: depths span nine orders of magnitude
    (1e-6 … 1e3 mm), and a linear grid would merge all the model dust into
    one bucket together with real conflicts.
    """
    hist: dict[str, int] = {}
    total = 0
    for f in findings:
        rel = f.get("hull_relation") if isinstance(f, dict) else f.hull_relation
        if rel != "overlap":
            continue
        sd = float(f["signed_distance_mm"] if isinstance(f, dict)
                   else f.signed_distance_mm)
        d = -sd
        if d <= 0:
            continue
        total += 1
        key = "1e%d" % math.floor(math.log10(d))
        hist[key] = hist.get(key, 0) + 1
    return {"overlaps": total,
            "by_decade_mm": {k: hist[k] for k in
                             sorted(hist, key=lambda x: int(x[2:]))},
            "note": OVERLAP_DEPTH_NOTE}

def migrate_report(old: dict) -> dict:
    """`clash-report/1` -> `/2`. Review #14: the canon cannot be kept
    byte-for-byte while adding a fact — it must be versioned AND able to read
    history. The migration invents nothing: the relation is derived from the
    already-recorded distance, old names are carried over to new ones
    without changing the NUMBERS.
    """
    if old.get("schema_version") == REPORT_SCHEMA:
        return old
    was = old.get("schema_version")
    if was not in ("clash-report/1", "clash-report/2"):
        raise ValueError(f"неизвестная схема отчёта: {was!r}")
    rep = dict(old)
    rep["schema_version"] = REPORT_SCHEMA
    # /2 -> /3: `vocabulary` added. Nothing is recomputed — a vocabulary
    # audit is a fact about the CODE, not about the building, so it is the
    # same for any report read by this version of the module.
    rep.setdefault("vocabulary", vocabulary_audit(
        clearance_mm=float((old.get("search") or {}).get("clearance_mm") or 0.0)))
    if was == "clash-report/2":
        rep.setdefault("notes", []).append(
            "МИГРАЦИЯ clash-report/2 -> /3: добавлен `vocabulary` — "
            "достижимость словаря отчёта. Числа не пересчитывались.")
        return rep
    out = []
    for f in old.get("findings") or []:
        g = dict(f)
        sd = float(g.get("signed_distance_mm", 0.0))
        g["hull_overlap_depth_mm"] = g.pop("physical_penetration_mm", max(0.0, -sd))
        g["certified_separating_translation_mm"] = g.pop("mtv_mm", None)
        g["ranking_tol_mm"] = g.pop("tol_grade_mm", 0.0)
        g["hull_relation"] = relation_of(sd)
        g.setdefault("separation_is_lower_bound", False)
        g.setdefault("ranking_significant", True)
        g.setdefault("translation_unavailable_reason", None)
        g.setdefault("pair_kind", "interference")
        out.append(g)
    rep["findings"] = out
    rep["relation_counts"] = dict(sorted(
        collections.Counter(f["hull_relation"] for f in out).items()))
    rep.setdefault("notes", []).append(
        "МИГРАЦИЯ clash-report/1 -> /2: отношение выведено из записанного "
        "signed_distance_mm; поля переименованы, числа не пересчитывались.")
    return rep


def dumps(report: dict) -> str:
    """Canonical serialization: the same input gives byte-for-byte the same
    file. Without this the golden is meaningless, and two runs are
    indistinguishable.

    Keys starting with ``_`` are run telemetry (timings and the like) and
    are not part of the canon: the canon is a function of the INPUT, the
    clock is not part of it."""
    canon = {k: v for k, v in report.items() if not k.startswith("_")}
    return json.dumps(canon, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sections_markdown(sec: dict) -> list[str]:
    """Sections IN THE REPORT. Zero hulls raised must be STATED together
    with a reason: "there are no such categories in the model" and "reading
    is forbidden by the table" are different diagnoses, yet in the grade
    table both look like `exact=0`."""
    if not sec:
        return []
    t = sec.get("totals") or {}
    out = ["## Сечения", ""]
    rows = sec.get("by_category") or {}
    if rows:
        out += ["| категория | элементов | сечение есть | сечения нет | "
                "оболочек по сечению |", "|---|---|---|---|---|"]
        for cat, r in sorted(rows.items()):
            out.append(f"| {cat} | {r['eligible']} | {r['present']} | "
                       f"{r['absent']} | {r['hulled']} |")
        out.append("")
    out.append(
        f"Итого: сечение прочитано у {t.get('present', 0)} элементов, "
        f"оболочек по сечению построено {t.get('hulled', 0)}; "
        f"типов без сечения {sec.get('types_without_section_count', 0)}.")
    blocked = sec.get("blocked_by_table") or {}
    if blocked:
        out += ["", "Сечение снято, но **запрещён таблицей** источник "
                    "`axis_section` (ревью №2, №3, №10) — "
                + ", ".join(f"{c}: {n}" for c, n in sorted(blocked.items()))
                + f" (всего {sec.get('blocked_total', 0)}). Это ЗАПРЕТ, а не "
                  "отсутствие данных: оболочкой у них остаётся габарит."]
    elif not t.get("present"):
        out += ["", "Ни одной оболочки по сечению: в модели нет элементов "
                    "категорий, которым источник `axis_section` разрешён. "
                    "Знаменатель выше публикуется нулями намеренно — «0 из 0» "
                    "и «не спрашивали» обязаны выглядеть по-разному."]
    out.append("")
    return out


def to_markdown(report: dict) -> str:
    s = report["search"]
    c = report["census"]["totals"]
    org = report["origin"]
    out = [
        "# CLASH D1 — плоский отчёт (raw_interference)",
        "",
        "**Не оракульный замер.** Судятся ОБОЛОЧКИ, а не тела; recall и "
        "precision против `ElementIntersectsElementFilter` — волна D2. "
        "Легальные отверстия и гильзы не исключены: `legal_relation_index` "
        "тоже D2.",
        "",
        f"Источник: `{org.get('run_dir', '?')}` · L0 SHA `{org.get('l0_sha', '?')}` "
        f"· ревизия `{(org.get('revision') or {}).get('fingerprint', '?')}`",
        "",
        "## Перепись",
        "",
        f"| eligible | hulled | unsupported | missing_geometry | сходится |",
        "|---|---|---|---|---|",
        f"| {c['eligible']} | {c['hulled']} | {c['unsupported']} | "
        f"{c['missing_geometry']} | {'да' if report['census']['balanced'] else 'НЕТ'} |",
        "",
        "Грейды оболочек: " + ", ".join(
            f"{g}={n}" for g, n in sorted(report["by_grade"].items())),
        "",
    ]
    comp = (report["search"].get("completeness") or {})
    cov = (report["census"].get("mvp_side_coverage") or {})
    if comp and not comp.get("complete", True):
        axes = comp.get("axes") or {}
        gaps = []
        extraction = axes.get("extraction") or {}
        federation = axes.get("federation") or {}
        geometry = axes.get("geometry") or {}
        query = axes.get("query_scope") or {}
        if not extraction.get("complete", True):
            gaps.append(
                f"extraction: вне L0 {extraction.get('outside_extraction_scope', 0)}")
        if not federation.get("complete", True):
            gaps.append(
                "federation: linked без геометрии "
                f"{federation.get('linked_elements_unscored', 0)}")
        if not geometry.get("complete", True):
            gaps.append(
                f"geometry: без оболочки {geometry.get('without_hull', 0)}, "
                f"вырожденных {geometry.get('degenerate_hulls', 0)}")
        if not query.get("complete", True):
            gaps.append(
                f"query_scope: отказано пар {query.get('refused_pairs', 0)}")
        # Old reports did not contain axes.  Preserve a useful explanation
        # for them without letting the legacy MVP counter explain new gaps.
        if not gaps:
            gaps.append(
                "geometry: без оболочки MVP "
                f"{comp.get('without_hull_on_mvp_side', 0)}")
        out += [
            "> **ПОИСК НЕПОЛОН ПО ПОСТРОЕНИЮ.** "
            + "; ".join(gaps) + ". Неполнота относится к доказанности "
            "области поиска, а не к порогу. Список находок ниже читать как "
            "НИЖНЮЮ оценку.",
            "",
        ]
    if cov:
        out += ["Покрытие сторон MVP: " + ", ".join(
            f"{side}: {v['hulled']}/{v['eligible']}"
            + (f" (без оболочки {v['without_hull']})" if v["without_hull"] else "")
            for side, v in sorted(cov.items())), ""]
    out += _sections_markdown(report["census"].get("sections") or {})
    out += [
        "## Поиск",
        "",
        f"- область: `{s['scope_id']}` — {s['scope_definition']}",
        f"- оболочек: {s['hulls']}, пар в области `{s['scope_id']}`: "
        f"{s['pairs_in_scope']}",
        f"- кандидатов широкой фазы: {s['candidate_pairs']}",
        f"- ячейка {s['grid']['cell_mm']} мм, ячеек {s['grid']['cells']}, "
        f"максимум в ячейке {s['grid']['max_bucket']}, "
        f"гигантов {s['grid']['oversized_hulls']}",
        "",
    ]
    ms = report.get("_timings_ms")
    if ms:  # run telemetry; not present in the canonical JSON
        out += [f"- время, мс: сетка {ms['grid']}, широкая {ms['broad']}, "
                f"узкая {ms['narrow']}", ""]
    out += [
        "## Находки",
        "",
    ]
    if not report["findings"]:
        out += ["Ни одной. Счётчики выше показывают, что поиск шёл: "
                "детектор, который «нашёл 0», обязан доказать, что искал.", ""]
    else:
        out += ["| # | A | B | класс | перекрытие оболочек, мм | отношение "
                "| грейд | вердикт |",
                "|---|---|---|---|---|---|---|---|"]
        for i, f in enumerate(report["findings"][:200], 1):
            out.append(
                f"| {i} | {f['a']['source_element_id']} ({f['a']['label']}) "
                f"| {f['b']['source_element_id']} ({f['b']['label']}) "
                f"| {f['pair_class']} | {f['hull_overlap_depth_mm']} "
                f"| {f['hull_relation']} | {f['hull_grade']} | {f['verdict']} |")
        if len(report["findings"]) > 200:
            out.append(f"| … | ещё {len(report['findings']) - 200} | | | | | |")
        out.append("")
    out += ["## Оговорки", ""] + [f"- {n}" for n in report["notes"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from kir.clash.snapshot import build_from_decompile

    ap = argparse.ArgumentParser(description="CLASH D1 — детектор поверх KIR")
    ap.add_argument("run_dir", help="каталог декомпайла (L0.jsonl + индексы)")
    ap.add_argument("--clearance-mm", type=float, default=0.0)
    ap.add_argument("--cell-mm", type=float, default=None)
    ap.add_argument("--all-pairs", action="store_true",
                    help="ДИАГНОСТИКА: все физические пары, не только MVP")
    ap.add_argument("--out", default=None, help="префикс: <out>.json + <out>.md")
    a = ap.parse_args(argv)

    snap = build_from_decompile(a.run_dir)
    rep = detect(snap, clearance_mm=a.clearance_mm, cell_mm=a.cell_mm,
                 pair_filter=any_physical_pair_filter if a.all_pairs
                 else mvp_pair_filter)
    if a.all_pairs:
        rep["notes"].insert(0, "ДИАГНОСТИКА: --all-pairs, пары вне MVP; "
                               "внутрираздельные примыкания законны и здесь НЕ "
                               "отфильтрованы.")
    if a.out:
        p = pathlib.Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.with_suffix(".json").write_text(dumps(rep) + "\n", encoding="utf-8")
        p.with_suffix(".md").write_text(to_markdown(rep), encoding="utf-8")
    print(to_markdown(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
