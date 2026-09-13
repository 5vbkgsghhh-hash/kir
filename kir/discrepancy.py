"""One report: authored revision against ONE observed model.

A pure consumer. No transport, no planning, no materialization, no native
execution, no writing to disk. Both sides are brought by the caller, and both
are already checked by their own owners: authored addresses — `ProjectRevision`
(`output_id`), qualified native identity — `assess_create_identities`,
the observed model — `BuildingGraph` from capture.

WHAT JOINS THE TWO SIDES, AND IT IS NOT A NAME. The only bridge is the Revit
`UniqueId`: on the left it comes from the RECEIPT of the original creation
(`element_identity.unique_id`, states `created_here` / `reused_existing`), on
the right — the graph node's own `DefinitionIdentity` (`document +
element_unique_id`). Matching names, categories, `ElementId` numbers, and
geometric proximity are NOT a bridge and are not used anywhere here.

═══════════════════════════════════════════════════════════════════════════
THE MANDATE'S FIVE OUTCOMES, AND A SIXTH WITHOUT WHICH THEY LIE
═══════════════════════════════════════════════════════════════════════════

    authored_only     an authored address for which observation has NO element
    observed_only     an observed element that no address claimed
    both_agree        the FIELD was compared, and the values are equal
    both_differ       the field was compared, the values diverged: field, both
                      values, units
    identity_unknown  the address exists but there is no identity — NOTHING to
                      compare against
    both_unmeasured   identities matched but the field could not be compared,
                      and the reason is NAMED

🔴 THE SIXTH WAS ESTABLISHED BY MEASUREMENT, NOT FOR ELEGANCE.
`WALL_USER_HEIGHT_PARAM` stops being the truth about a wall's top the moment
the top is constrained to a level — measured 2026-07-29, and the same fact
lives in `design_check._wall_span`. Over the corpus (MNVNK 2026-08-22, 10 646
walls) that is **7 007 walls, i.e. 65.8%**, and a further **2 801** wall block
never had the parameter read at all. Folding these in with the measured ones
and declaring `both_agree` would say "they matched" where nothing was
compared; declaring `both_differ` would blame the building for our own
blindness. So the outcome is named separately, and the reason travels as a
string.

═══════════════════════════════════════════════════════════════════════════
ABSENCE IS PROVABLE ONLY BY FULL COVERAGE
═══════════════════════════════════════════════════════════════════════════

`authored_only` is a claim OF ABSENCE, and it requires the graph to be read
in full: `BuildingGraph.identity_authoritative`. Even one node with an
incomplete identity, and "not found" becomes indistinguishable from "could
not be read" — so the address gets `identity_unknown`, not an accusation
against the model.

Recon measurement, 2026-09-07, on a demo capture
(`capture_api.write_demo_capture`): without an explicit identity context the
graph gives **4 nodes, 0 authoritative, 4 incomplete**, the sole gap being
`legacy_context_absent`. The same snapshot with `DocumentIdentity`/
`FederationContext` supplied — **4 of 4 authoritative** with real UniqueIds.
So here the difference between "compared" and "nothing to compare against"
is not an opinion but an input, and the report must show it rather than
smooth it over.

═══════════════════════════════════════════════════════════════════════════
THE OBSERVATION FINGERPRINT IS AN EXPLICIT INPUT, AND IT IS A CLAIM
═══════════════════════════════════════════════════════════════════════════

`BuildingGraph` CARRIES neither a revision nor a fingerprint: its
representation is the schema, `doc_name`, the document identity, the
federation context, the census, nodes, and edges. `change_stamp` lives in
the L0 header, the snapshot's sha256 is computed by
`capture_edit._snapshot_digest`, and neither of them reaches the graph.
So `ObservedRevision` is supplied EXPLICITLY — the same way `document_identity`
is for `graph_from_l0`, and for the same reason: a fingerprint derived from a
directory name or from the graph itself would be a fingerprint of our own
assumption.

What of this IS CHECKED here: the claimed document identity must be the
identity of the submitted graph, otherwise `observation_revision_mismatch`.
What is NOT checked, and is therefore named in `claims`: the link between the
observation and the publication DOCUMENT. On the authored side sits the
opaque `document_key` of the open document; on the capture side there is none
at all — there is nothing to compare, and the report will not invent that
link.
"""
from dataclasses import dataclass, field
from typing import Mapping

from kir.create_publication import BoundCreateReceipt, assess_create_identities
from kir.decompile.building_graph import (
    REFUTED_TOP_IS_UNCONNECTED_HEIGHT, BuildingGraph, Modality, Relation,
)
from kir.model.identity import DefinitionIdentity, DocumentIdentity
from kir.project import ProjectRevision, _hash, _object, _thaw
from kir.saved_execution import SavedExecutionRecord


DISCREPANCY_SCHEMA = "kir-authored-observed-discrepancy/1"

#: Outcomes. The order is fixed: it is also the report's column order.
_STATES = ("both_agree", "both_differ", "both_unmeasured",
           "authored_only", "observed_only", "identity_unknown")

#: Qualified receipt states: only these yield a UniqueId address.
_QUALIFIED = ("created_here", "reused_existing")

#: Where the observation fingerprint came from. Three values, none of them
#: redundant: MEASURED while building the graph, DECLARED by the caller, and
#: ABSENT. Merging the last two would say "there is a date" about a `/1`
#: artifact.
FINGERPRINT_DERIVED = "derived"
FINGERPRINT_DECLARED = "declared"
FINGERPRINT_ABSENT = "absent"

#: The identity-replacement ledger: an old Revit UniqueId gave way to a new
#: one.
#:
#: 🔴 WHY IT MATTERS TO THE BRIDGE. Without it, replacing an element yields A
#: PAIR of rows — `authored_only` for the old address and `observed_only` for
#: the new one — so the report reports two discrepancies where there is no
#: discrepancy at all, only one replacement. A pair is worse than silence: it
#: accuses the model twice.
IDENTITY_REPLACEMENT_SCHEMA = "kir-create-identity-replacement/1"

#: The observation has no fingerprint — and the report SAYS so, rather than
#: staying silent or substituting a plausible-looking date. A `/1` artifact
#: falls entirely into this case.
OBSERVATION_FINGERPRINT_ABSENT = "observation_fingerprint_absent"

#: THE CLOSED PROFILE OF COMPARABLE FIELDS. `op -> ((authored field, L0
#: parameter, units), ...)`. The pair is not invented out of thin air: it is
#: exactly the one the lift wires together (`lift._lift_wall`: `height_mm` <-
#: `WALL_USER_HEIGHT_PARAM`), and it is exactly the one that arrives in
#: `GraphNode.section` through the closed list `extract.
#: SECTION_PARAM_NAMES`. The profile is narrow ON PURPOSE: a field nobody
#: compares is better named uncovered than compared approximately.
_COMPARABLE = {"create_wall": (("height_mm", "WALL_USER_HEIGHT_PARAM", "mm"),)}

#: The category the op is required to produce. Needed not for lookup (the
#: bridge is UniqueId alone), but to catch a match against an element of a
#: DIFFERENT kind.
_OP_CATEGORY = {"create_wall": "OST_Walls"}

_CLAIMS = {
    "scope": "authored_revision_outputs_vs_one_observed_building_graph",
    "join": "qualified_original_create_unique_id_only",
    "observation_revision": "declared_by_caller_not_derived_from_the_graph",
    "observation_to_publication_document_binding": "not_established",
    # 🔴 THE REASON IS MECHANICAL, NOT "NOT DONE YET". The publication key is
    # produced by `DocumentRevisionTracker`: `Guid.NewGuid()` on EVERY launch
    # of the add-in plus a counter, and its own comment says exactly this — "a
    # snapshot of one open native document, NOT a file or a persisted BIM
    # identity". The snapshot's document identity, by contrast, is STABLE
    # (`revit:<source>:<value>`, `extract._parse_metadata`). Neither is
    # derivable from the other, and the link will not appear from trying
    # harder.
    "observation_to_publication_document_binding_reason":
        "publication document_key is a per-session runtime handle; "
        "the observed document identity is a persisted BIM identity",
    "current_model_state": "not_established",
    "absence_claim": "requires_fully_authoritative_graph_identity",
    "geometry": "not_evaluated", "layers": "not_evaluated",
    "engineering": "not_evaluated", "type_definition": "not_evaluated",
    "whole_bim_acceptance": "not_established",
    "dispatch_permission": "none", "update_permission": "none",
    "retry_permission": "none",
}


class DiscrepancyError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ObservedRevision:
    """The observation fingerprint. A CLAIM by the caller, not derived from the graph.

    `change_stamp` — the document's change stamp from the L0 header;
    `l0_sha256` — the sha256 of the snapshot's BYTES
    (`capture_edit._snapshot_digest`), i.e. the identity of the building this
    observation is bound to. Both travel into the report as claimed, and
    neither is recomputed here: a pure consumer has no snapshot file and
    should not have one.
    """

    document_identity: DocumentIdentity
    change_stamp: str
    l0_sha256: str

    def __post_init__(self):
        if type(self.document_identity) is not DocumentIdentity:
            raise DiscrepancyError("typed_observed_revision_required")
        if type(self.change_stamp) is not str or not self.change_stamp.strip():
            raise DiscrepancyError("observation_change_stamp_required")
        if (type(self.l0_sha256) is not str or len(self.l0_sha256) != 64
                or any(char not in "0123456789abcdef" for char in self.l0_sha256)):
            raise DiscrepancyError("observation_snapshot_digest_required")

    def to_dict(self):
        return {"document_identity": self.document_identity.as_dict(),
                "change_stamp": self.change_stamp, "l0_sha256": self.l0_sha256}

    @classmethod
    def from_graph(cls, graph) -> "ObservedRevision | None":
        """The fingerprint DERIVED by the graph, or `None` if the graph is not dated.

        `None` is returned in exactly two cases: a version-`/1` artifact
        (which never carried a fingerprint) and a graph built without a
        snapshot. There is nothing to reconstruct it from here, and it must
        not be reconstructed: see `FINGERPRINT_ABSENT`.
        """
        if type(graph) is not BuildingGraph:
            raise DiscrepancyError("typed_discrepancy_inputs_required")
        if graph.observation is None or graph.document_identity is None:
            return None
        return cls(graph.document_identity, graph.observation.change_stamp,
                   graph.observation.l0_sha256)


@dataclass(frozen=True, slots=True, init=False)
class DiscrepancyReport:
    digest: str
    _payload: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use assess_authored_observed_discrepancies; "
                        "a serialized report is not an observation")

    def to_dict(self):
        return {**_thaw(self._payload), "report_digest": self.digest}


def _replacement_pairs(payload):
    """(old, new) from EITHER of the two forms. Strictness beyond this point is shared.

    🔴 THE CARRIER IS RECOGNIZED BY WHAT IT CAN ANSWER, NOT BY ITS CLASS NAME.
    `IdentityReplacementLedger` lives in a foreign holding
    (`kir/create_publication`), and importing it here for a single type check
    would tie the discrepancy report to publication forever — when our
    question is exactly one: can this value name a replacement. Hence
    `effective_unique_id` and `.replacements`, the two capabilities that make
    up a ledger.

    Pairs are taken from the ROWS, not from `effective_unique_id`: the chain
    and the cycle below are resolved by our own law, the same one for both
    forms. Otherwise the dict form and the ledger would refuse differently on
    the same defect — i.e. strictness would depend on who called.
    """
    if payload is None:
        return ()
    if hasattr(payload, "effective_unique_id") and hasattr(payload, "replacements"):
        rows = payload.replacements
        if not isinstance(rows, (list, tuple)):
            raise DiscrepancyError("invalid_identity_replacement_ledger")
        pairs = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise DiscrepancyError("invalid_identity_replacement_ledger")
            original = row.get("original_identity")
            if not isinstance(original, Mapping):
                raise DiscrepancyError("invalid_identity_replacement_ledger")
            pairs.append((original.get("unique_id"), row.get("superseded_by")))
        return tuple(pairs)
    if not isinstance(payload, Mapping):
        raise DiscrepancyError("invalid_identity_replacement_ledger")
    if payload.get("schema") != IDENTITY_REPLACEMENT_SCHEMA:
        raise DiscrepancyError("unsupported_identity_replacement_schema")
    rows = payload.get("replacements")
    if not isinstance(rows, (list, tuple)):
        raise DiscrepancyError("invalid_identity_replacement_ledger")
    pairs = []
    for row in rows:
        if not isinstance(row, Mapping) or not {"superseded_uid", "superseded_by"} <= set(row):
            raise DiscrepancyError("invalid_identity_replacement_ledger")
        if set(row) - {"superseded_uid", "superseded_by", "reason"}:
            raise DiscrepancyError("invalid_identity_replacement_ledger")
        pairs.append((row["superseded_uid"], row["superseded_by"]))
    return tuple(pairs)


def _replacement_source(payload):
    """What the ledger was supplied as. `None` — none was supplied; this is not an empty ledger."""
    if payload is None:
        return None
    return ("confirmed_ledger"
            if hasattr(payload, "effective_unique_id") else "declared_pairs")


def _resolve_replacements(payload):
    """Replacement ledger -> `{old uid: FINAL uid}`. A refusal instead of a guess.

    A chain A->B->C resolves to C: a replacement of a replacement is still
    one thing. Anything that makes the answer ambiguous refuses BY NAME
    rather than being decided by a pick:

        two `superseded_by` for one old uid    `identity_replacement_forks`
        a cycle A->B->A                        `identity_replacement_cycle`
        `superseded_by == superseded_uid`      `identity_replacement_self`

    🔴 TWO FORMS, ONE STRICTNESS (unified 2026-09-07). Both an
    `IdentityReplacementLedger` from `kir/create_publication.py` — a carrier
    BUILT FROM CONFIRMATION (old uid `not_found`, new one `observed` in one
    snapshot of one revision) — and the dict form
    `{superseded_uid, superseded_by, reason}` for callers without a
    publication are accepted. Parsing the two forms diverges only up to the
    pairs; beyond that the law is one, and this is a requirement, not a
    convenience: refusing the two forms differently would make strictness
    depend on who called, not on what was supplied.

    A confirmed ledger outranks a declared one by provenance, but NOT by
    trust: a cycle and a fork are rejected for both, even if the carrier
    insists it has already checked them itself. A report that takes someone
    else's check on faith is not an instrument.
    """
    direct = {}
    for old_uid, new_uid in _replacement_pairs(payload):
        if (type(old_uid) is not str or not old_uid.strip()
                or type(new_uid) is not str or not new_uid.strip()):
            raise DiscrepancyError("invalid_identity_replacement_ledger")
        if old_uid == new_uid:
            raise DiscrepancyError("identity_replacement_self")
        if old_uid in direct and direct[old_uid] != new_uid:
            raise DiscrepancyError("identity_replacement_forks")
        direct[old_uid] = new_uid
    final = {}
    for old_uid in direct:
        seen, current = {old_uid}, direct[old_uid]
        while current in direct:
            if current in seen:
                raise DiscrepancyError("identity_replacement_cycle")
            seen.add(current)
            current = direct[current]
        final[old_uid] = current
    return final


def _address(output):
    return {key: output[key]
            for key in ("instance_key", "output_key", "output_id", "source_op")}


def _direct(output, operation):
    """One authored output — one compiled op with the same address."""
    compiled = output["compiled_ops"]
    return (len(compiled) == 1 and compiled[0]["op_id"] == output["output_id"]
            and compiled[0]["op"] == output["source_op"] and operation is not None)


def _number(value):
    """A finite number, or None. `bool` does not count as a number here."""
    if type(value) is bool or type(value) not in (int, float):
        return None
    value = float(value)
    return None if value != value or value in (float("inf"), float("-inf")) else value


def _height_is_the_truth(graph, node):
    """None — the height parameter is fit to be the truth; otherwise a NAMED reason.

    Computes nothing new: reads the `top_constrained_to_level` edge, whose
    four outcomes are already named by the graph. A top given as a NUMBER is
    marked by the graph with the `top_is_unconnected_height` refutation —
    only then, and only then, is "Unconnected Height" the wall's height.
    """
    edges = graph.out_edges(node.node_id, Relation.TOP_CONSTRAINED_TO_LEVEL)
    if not edges:
        # There is no edge at all: the row had NO parameter whatsoever, or
        # the node is not a wall. There is no evidence about the top at all.
        return "wall_top_constraint_not_witnessed"
    edge = edges[0]
    if (edge.modality is Modality.REFUTED
            and edge.refuted_by == REFUTED_TOP_IS_UNCONNECTED_HEIGHT):
        return None
    if edge.modality is Modality.PROVEN:
        return "top_constrained_height_is_not_the_truth"
    if edge.modality is Modality.UNRESOLVED_TARGET:
        # The top IS CONSTRAINED, the level is simply absent from the
        # snapshot. The height still is not the truth.
        return "top_constrained_to_a_level_outside_the_snapshot"
    if edge.modality is Modality.REFUTED:
        return str(edge.refuted_by)
    return str(edge.evidence.get("why") or "top_constraint_unresolved")


def _compare_fields(graph, source_op, authored_op, node):
    """(state, diagnostic, field, units, authored, observed)."""
    category = _OP_CATEGORY.get(source_op)
    if category is not None and node.category != category:
        # The identities matched, but the element's kind differs. This is not
        # a trivial "field diverged", nor is it silence: the discrepancy is
        # NAMED by the `category` field.
        return ("both_differ", "observed_category_contradicts_source",
                "category", None, category, node.category)
    for name, parameter, units in _COMPARABLE[source_op]:
        authored = _number(authored_op.get(name))
        if authored is None:
            return ("both_unmeasured", "authored_value_is_not_a_number",
                    name, units, None, None)
        if name == "height_mm":
            why = _height_is_the_truth(graph, node)
            if why is not None:
                return ("both_unmeasured", why, name, units, authored, None)
        observed = _number(node.section.get(parameter))
        if observed is None:
            return ("both_unmeasured", "observed_parameter_absent",
                    name, units, authored, None)
        state = "both_agree" if authored == observed else "both_differ"
        return (state, f"revision_bound_{state}", name, units, authored, observed)
    return ("both_unmeasured", "no_comparable_field_in_profile", None, None, None, None)


def assess_authored_observed_discrepancies(
        project, record, bound_receipt, graph, observed=None, *,
        replacements=None) -> DiscrepancyReport:
    """Reconcile an authored revision and one observed graph by their shared address.

    No editing, publication, republication, or write permission arises here.
    `both_agree` pertains to the CLAIMED observation fingerprint and is not a
    statement about the model's current state. An observation taken later
    proves ordering within one document, not the absence of someone else's
    edits between the two.
    """
    if (type(project) is not ProjectRevision
            or type(record) is not SavedExecutionRecord
            or type(bound_receipt) is not BoundCreateReceipt
            or type(graph) is not BuildingGraph
            or (observed is not None and type(observed) is not ObservedRevision)):
        raise DiscrepancyError("typed_discrepancy_inputs_required")

    # THE FINGERPRINT IS TAKEN FROM THE GRAPH, NOT FROM THE CALLER. A `/2`
    # graph is dated by itself, and the measured outranks the claimed. The
    # explicit input remains — it is used where the graph is not dated — but
    # it has no right to dispute the measured one.
    derived = ObservedRevision.from_graph(graph)
    if observed is None:
        observed, fingerprint_status = derived, (
            FINGERPRINT_ABSENT if derived is None else FINGERPRINT_DERIVED)
    elif derived is None:
        fingerprint_status = FINGERPRINT_DECLARED
    elif derived != observed:
        # One thing was claimed, another was measured — this is exactly "an
        # observation from a different revision", and the dispute cannot be
        # resolved in favor of the claim either way: the measurement IS the
        # subject here.
        raise DiscrepancyError("observation_revision_mismatch")
    else:
        fingerprint_status = FINGERPRINT_DERIVED

    # The document identity is checked BEFORE any work: a report that glued
    # an authored revision to the fingerprint of SOMEONE ELSE's snapshot
    # would lie in every row.
    if (observed is not None and graph.document_identity is not None
            and graph.document_identity != observed.document_identity):
        raise DiscrepancyError("observation_revision_mismatch")

    superseded = _resolve_replacements(replacements)

    # The shared owner reconciles source/archive/receipt and qualifies
    # creation vs. reuse. There is no second parsing pass here.
    identities = assess_create_identities(project, record, bound_receipt)
    historical = identities.to_dict()
    submission = record.project_submission
    authored = {oid: output for _, output, oid in project.addressed_outputs()}
    retained = {row["payload"]["id"]: row["payload"]
                for row in record.to_dict()["plan_evidence"]["ops"]}
    facts = {output["output_id"]: output for output in historical["outputs"]}

    # ── THE OBSERVED SIDE: an index by UniqueId and NAMED node refusals ──
    by_uid, ambiguous, incomplete = {}, set(), 0
    for node in graph.nodes.values():
        if node.definition_identity is None or not node.identity_authoritative:
            incomplete += 1
            continue
        uid = node.definition_identity.element_unique_id
        if uid in by_uid:
            ambiguous.add(uid)
            continue
        by_uid[uid] = node
    # A repeated address removes BOTH sides of the pair: there is nothing to
    # say which of the two nodes is the real one, and picking the first would
    # be a coin flip.
    for uid in ambiguous:
        by_uid.pop(uid, None)
    full_coverage = graph.identity_authoritative

    rows, excluded, claimed = [], [], set()
    for output in submission["outputs"]:
        oid = output["output_id"]
        fact = facts[oid]
        uid = (fact["element_identity"]["unique_id"]
               if fact["state"] in _QUALIFIED else None)
        # A REPLACEMENT IS STILL ONE THING. The old address stops being the
        # one sought, but does NOT become an absence either; the new one
        # stops being unclaimed. Otherwise one replacement would print as two
        # discrepancies.
        resolved = superseded.get(uid, uid) if uid is not None else None
        if uid is not None:
            claimed.add(uid)
            claimed.add(resolved)
        if output["source_op"] not in _COMPARABLE:
            excluded.append({**_address(output), "publication_state": fact["state"],
                             "reason": "not_in_comparable_field_profile"})
            continue

        row = {**_address(output), "state": "identity_unknown", "diagnostic": None,
               "publication_state": fact["state"], "unique_id": uid,
               "resolved_unique_id": resolved,
               "superseded": uid is not None and resolved != uid,
               "observed_node_id": None, "observed_definition_key": None,
               "field": None, "units": None,
               "authored_value": None, "observed_value": None}
        rows.append(row)

        source = authored[oid]
        operation = retained.get(oid)
        if source.geometry is not None or not _direct(output, operation):
            row["diagnostic"] = "direct_authored_profile_unsupported"
            continue
        if fact["state"] == "refused":
            # The receipt says the op REFUSED: no element was created, and
            # this is positive evidence of absence, not our own blindness.
            row.update(state="authored_only",
                       diagnostic="operation_refused_no_element_created")
            continue
        if uid is None:
            # There is no address: `unavailable` or `conflict`. The receipt's
            # silence does NOT prove the element does not exist — there is
            # nothing to prove it with.
            row["diagnostic"] = fact["diagnostic"] or "publication_identity_unqualified"
            continue
        if resolved in ambiguous:
            row["diagnostic"] = "observed_identity_ambiguous"
            continue
        node = by_uid.get(resolved)
        if node is None:
            if not full_coverage:
                row["diagnostic"] = "observed_identity_incomplete"
                continue
            row.update(state="authored_only",
                       diagnostic="qualified_identity_absent_from_observation")
            continue
        expected_document = (observed.document_identity if observed is not None
                             else graph.document_identity)
        if (expected_document is not None
                and node.definition_identity != DefinitionIdentity(
                    expected_document, resolved)):
            # The node was found by UniqueId, but it lives in A DIFFERENT
            # document.
            row["diagnostic"] = "observed_definition_document_differs"
            continue
        row["observed_node_id"] = node.node_id
        row["observed_definition_key"] = node.definition_identity.key
        state, diagnostic, name, units, left, right = _compare_fields(
            graph, output["source_op"], _thaw(source.operation), node)
        row.update(state=state, diagnostic=diagnostic, field=name, units=units,
                   authored_value=left, observed_value=right)

    observed_only = [
        {"node_id": node.node_id, "unique_id": uid,
         "definition_key": node.definition_identity.key, "category": node.category,
         "state": "observed_only",
         "diagnostic": "no_authored_address_claims_this_identity"}
        for uid, node in sorted(by_uid.items()) if uid not in claimed]

    counts = {state: sum(row["state"] == state for row in rows) for state in _STATES}
    counts["observed_only"] += len(observed_only)
    matched = sum(1 for uid in by_uid if uid in claimed)
    refusals = {"node_identity_incomplete": incomplete,
                "observed_identity_ambiguous": len(graph) - incomplete - len(by_uid)}
    census = {
        "authored_addresses": len(submission["outputs"]),
        "compared_rows": len(rows), "excluded_outputs": len(excluded),
        "observed_nodes": len(graph), "observed_matched": matched,
        "observed_only": len(observed_only), "observed_refusals": refusals,
        "graph_identity_authoritative": full_coverage,
    }
    _assert_census(census, counts, len(rows) + len(observed_only))

    body = {
        "schema": DISCREPANCY_SCHEMA, "project": submission["project"],
        "submission_digest": submission["submission_digest"],
        "archive_digest": record.digest,
        "authored": {
            "revision_id": submission["project"]["revision_id"],
            "receipt_digest": bound_receipt.receipt_digest,
            "identity_assessment_digest": identities.digest,
            "execution": historical["execution"], "outcome": historical["outcome"],
            "manifest_complete": historical["manifest_complete"],
            "timestamp_utc": bound_receipt.receipt["timestamp_utc"],
            "diagnostics": historical["diagnostics"]},
        "observation": {
            **({"document_identity": None, "change_stamp": None,
                "l0_sha256": None} if observed is None else observed.to_dict()),
            "fingerprint_status": fingerprint_status,
            "diagnostic": (OBSERVATION_FINGERPRINT_ABSENT
                           if fingerprint_status == FINGERPRINT_ABSENT else None),
            "identity_replacements": len(superseded),
            "identity_replacement_source": _replacement_source(replacements),
            "doc_name": graph.doc_name,
            "graph_document_identity": (None if graph.document_identity is None
                                        else graph.document_identity.as_dict()),
            "identity_gaps": dict(graph.census.identity_gaps),
            "sources_absent": list(graph.census.sources_absent)},
        "counts": counts, "outputs": rows, "observed_only": observed_only,
        "excluded_outputs": excluded, "census": census, "claims": dict(_CLAIMS),
    }
    report = object.__new__(DiscrepancyReport)
    object.__setattr__(report, "_payload", _object(body, "discrepancy"))
    object.__setattr__(report, "digest", _hash(body))
    return report


def _assert_census(census, counts, stated):
    """The same law as the graph's: an address must receive a NAMED outcome.

    Without it, a report with a silent drop would look like a report with
    fewer discrepancies — i.e. it would err in the pleasant direction.
    """
    if census["authored_addresses"] != census["compared_rows"] + census["excluded_outputs"]:
        raise DiscrepancyError("authored_census_does_not_balance")
    if sum(counts.values()) != stated:
        raise DiscrepancyError("state_census_does_not_balance")
    if (census["observed_nodes"] != census["observed_matched"] + census["observed_only"]
            + sum(census["observed_refusals"].values())):
        raise DiscrepancyError("observed_census_does_not_balance")


__all__ = ["DISCREPANCY_SCHEMA", "IDENTITY_REPLACEMENT_SCHEMA",
           "OBSERVATION_FINGERPRINT_ABSENT", "FINGERPRINT_DERIVED",
           "FINGERPRINT_DECLARED", "FINGERPRINT_ABSENT",
           "DiscrepancyError", "DiscrepancyReport",
           "ObservedRevision", "assess_authored_observed_discrepancies"]
