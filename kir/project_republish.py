# -*- coding: utf-8 -*-
"""Plan a REPEAT publication of a program that was published before.

    plan_republish(store, program, previous) -> RepublishPlan

🔴 THE DEFECT THIS EXISTS FOR, MEASURED ON A LIVE REVIT 2023 ON 13.09.2026.
A repeat publication today has no middle: it either REFUSES ENTIRELY or
DUPLICATES ENTIRELY.

* `/root/kir-live-20260909/live-20260913-slice-receipt.json` — the program
  carries `create_wall_type` and `create_level`, neither of which has a reuse
  branch, so `publish_2` answers `stale_or_failed` ("тип с этим адресом уже
  существует с другим составом") and `atomic` rolls the whole publication back.
  Six counters stand still: walls 4/4/4, floors 1/1/1, instances 3915/3915/3915.
  No duplicates — because nothing happened.
* `/root/kir-live-20260909/live-20260913-slice-opening-receipt.json` — the same
  shape WITHOUT those two ops. Nothing refuses, `ok: true`, and each repeat adds
  +4 walls, +1 floor, **+25 instances**: walls 4→8→12, floors 1→2→3,
  instances 3913→3938→3968.

This module is that missing middle. It reads what the ledger already knows about
the previous publication, compares the two programs BY OUTPUT ADDRESS, and emits
a closed list of actions for the emitter to execute. It writes nothing to Revit
and gives no permission to send: `dispatch_permission: "none"`.

🔴 A DUPLICATE IS NOT CAUGHT HERE — IT IS UNSPEAKABLE. `action="create"` for an
output whose `uid_before` is known is refused when the plan is built
(`create_over_known_identity`), so the emitter cannot be handed one.

The contract with the emitter is `.work/prod-20260913/republish/CONTRACT.md`
(schema `kir-republish-plan/1`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from kir.project import ProjectError, _thaw

#: The plan's schema. A new STORE schema is deliberately NOT introduced: the
#: edge "this output continues that publication" already exists as the table
#: `create_imports` (`kir/project_create_store.py:60-66`).
REPUBLISH_PLAN_SCHEMA = "kir-republish-plan/1"

#: The five actions. Closed on purpose: an emitter that meets an unknown verb
#: has to guess, and guessing is how a duplicate is born.
ACTIONS = ("keep", "update", "replace", "delete", "create")

#: The identity vocabulary is BORROWED, not invented: `created_here` and
#: `reused_existing` come from `kir/create_publication.py:354-358`.
IDENTITY_STATES = ("created_here", "reused_existing", "refused", "not_started", "unknown")

#: Reasons, closed list (CONTRACT.md §3). A reason outside it is a refusal.
REASONS = ("unchanged", "parameter_changed", "geometry_moved", "type_changed",
           "replace_no_update_op", "replace_sketch_unsupported",
           "removed_from_program", "new_in_program", "no_previous_publication")

#: 🔴 WHAT THE LANGUAGE CAN ACTUALLY CHANGE IN PLACE, and nothing more.
#: `kir.spec.OPS` holds exactly four mutating operations —
#: `set_param`, `move_elements`, `change_type`, `delete` (measured 13.09.2026:
#: `[n for n in spec.OPS if re.search(r'set_|move|change|delete', n)]`).
#: So a field may be planned as `update` ONLY if one of them can carry it.
#: Everything else is an honest `replace` with a written identity replacement —
#: never a silent re-create.
_PARAMETER_FIELDS = {
    "create_wall": ("height_mm", "base_offset_mm", "top_offset_mm"),
    "create_level": ("elev_mm",),
    "create_floor": ("height_offset_mm",),
    "create_floor_by_contour": ("height_offset_mm",),
    "create_room": ("name", "number"),
}
#: A rigid translation is the only geometry change `move_elements` can carry.
_POSITION_FIELDS = {
    "create_wall": ("p0_mm", "p1_mm"),
}
#: `change_type` owns exactly this field.
_TYPE_FIELD = "type"
#: Sketch-shaped fields: a contour edit is a sketch operation, and the language
#: has one only for a floor opening (`floor_sketch_opening`). Anything else here
#: is `replace_sketch_unsupported`, said out loud.
_SKETCH_FIELDS = ("outline", "contour", "holes", "profile", "profile_top", "points_mm")

#: Fields that are addresses/bookkeeping, not authored values: they move with the
#: program and must not be read as a change of the built element.
_ADDRESS_FIELDS = ("id", "op")

#: 🔴 HOW A PARAMETER IS ADDRESSED (review point П2, accepted 13.09.2026).
#: `set_param` in the emitter takes a DISPLAY name (`kir/authoring.py:1057-1063`
#: calls `GetParameters(<pname>)`), and the owner's Revit is RUSSIAN — its own
#: receipt came back with `Стены`, `Перекрытия`
#: (`live-20260913-slice-cleanup-receipt.json`). A plan that named a display
#: name would be refused there as "параметр не найден" and would not know it.
#: A BuiltInParameter identifier does not depend on the document's language, so
#: for every field KIR knows the plan must say `builtin_parameter`.
UPDATE_VIA = ("builtin_parameter", "shared_guid", "localized_name")

#: The closed table, and NOT ONE NAME IS INVENTED: each constant is already
#: named by this tree's own readers, at the address beside it.
_BUILTIN_PARAMETER = {
    ("create_wall", "height_mm"): "WALL_USER_HEIGHT_PARAM",        # design_check.py:182,758,770
    ("create_wall", "base_offset_mm"): "WALL_BASE_OFFSET",          # design_check.py:765
    ("create_wall", "top_offset_mm"): "WALL_TOP_OFFSET",            # design_check.py:768
    ("create_level", "elev_mm"): "LEVEL_ELEV",                      # element_query.py:249,254
    ("create_room", "name"): "ROOM_NAME",                           # ops_room.py:225,258
    ("create_room", "number"): "ROOM_NUMBER",                       # ops_room.py:225
    ("create_floor", "height_offset_mm"): "FLOOR_HEIGHTABOVELEVEL_PARAM",
    ("create_floor_by_contour", "height_offset_mm"): "FLOOR_HEIGHTABOVELEVEL_PARAM",
}

#: The identity a plan row carries. One UniqueId is NOT enough: none of
#: `set_param`, `move_elements`, `change_type`, `delete` accepts it — they
#: address by `ElementId`, and the UniqueId is what the guard pins
#: (review point П1). The capture already returns exactly these three fields.
IDENTITY_SCHEMA = "revit-element-identity/1"


class RepublishError(ProjectError):
    """A plan could not be built. Carries a code from CONTRACT.md §4."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value) -> str:
    return sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class RepublishPlan:
    """An inert plan. Holding it executes nothing and permits nothing."""

    rows: tuple
    project_id: str
    base_revision: str | None
    previous_receipt_digest: str | None
    ledger_source: str
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", _digest(self._body()))

    def _body(self) -> dict:
        return {"schema": REPUBLISH_PLAN_SCHEMA, "project_id": self.project_id,
                "base_revision": self.base_revision,
                "previous_receipt_digest": self.previous_receipt_digest,
                "ledger_source": self.ledger_source,
                "destructive": self.destructive(),
                "rows": [dict(row) for row in self.rows], "counts": self.counts()}

    def destructive(self) -> bool:
        """`allow_destructive` is a PROGRAM-level flag (review point П4).

        `{"op": "delete"}` without it is `KIR-D001`, measured by N. S raises it
        if and only if the plan actually removes something — otherwise the
        emitter would be deciding on the author's behalf.
        """
        return any(row["action"] in ("delete", "replace") for row in self.rows)

    def counts(self) -> dict:
        return {action: sum(1 for row in self.rows if row["action"] == action)
                for action in ACTIONS}

    def to_dict(self) -> dict:
        return {**self._body(), "plan_digest": self.digest,
                "claims": {"native_execution": "not_run",
                           "engineering_acceptance": "not_established",
                           "dispatch_permission": "none",
                           "preservation": "not_checked_before_to_after"}}

    def creates_over_known_identity(self) -> tuple:
        """The property the whole module exists for; always empty by construction."""
        return tuple(row["output_id"] for row in self.rows
                     if row["action"] == "create" and row.get("identity_before"))


# ── reading what the previous publication left behind ──────────────────────
@dataclass(frozen=True, slots=True)
class PreviousPublication:
    """One shape for three existing carriers of the same fact.

    `create_imports`/identity assessment (`kir/create_publication.py:196`),
    `staged_submission.import_lineage` (`kir/staged_submission.py:286-315`) and
    the Level baseline (`kir/project_realization_store.py:401`) all answer
    "which element is this output". They are read here, never re-derived.
    """

    outputs: dict
    ledger_source: str
    receipt_digest: str | None


def _identity_of(value) -> tuple:
    """(identity triple, state) out of whatever the carrier calls its identity.

    🔴 THE TRIPLE, NOT THE UniqueId (review point П1). The emitter addresses by
    `ElementId` and pins by `UniqueId`; a plan that carried only the UniqueId
    would force a second live pass "UniqueId → ElementId", and the brief allows
    ONE live run. The capture already returns all three fields — live receipt
    `live-20260913-slice-receipt.json`, `acceptance.identities_1[*].uid`.
    """
    if not isinstance(value, dict):
        return None, "unknown"
    proof = value.get("element_identity") or value.get("original_identity") or {}
    state = value.get("state") or value.get("original_identity_state") or "unknown"
    if not isinstance(proof, dict) or not proof.get("unique_id"):
        return None, (state if state in IDENTITY_STATES else "unknown")
    identity = {"schema_version": proof.get("schema_version") or IDENTITY_SCHEMA,
                "element_id": proof.get("element_id"),
                "unique_id": proof.get("unique_id"),
                # 🔴 On an UNSAVED document `VersionGuid` is the DOCUMENT's
                # episode, not the element's version: live, all eight outputs
                # carried ONE value equal to the head of every `unique_id`
                # (review point П6). Carried, never read as "and it did not
                # change either".
                "version_guid": proof.get("version_guid")}
    return identity, (state if state in IDENTITY_STATES else "unknown")


def read_previous_publication(previous, *, program=None) -> PreviousPublication:
    """Normalise a ledger view. Three accepted shapes, each NAMED in the result.

    The name matters: a plan that cannot say WHICH carrier gave it a UID is a
    plan whose numbers have no address.
    """
    if previous is None:
        return PreviousPublication({}, "none", None)
    if hasattr(previous, "to_dict"):
        previous = previous.to_dict()
    payloads = _payloads_of(program) if program is not None else {}
    rows, source, receipt = {}, None, None

    if isinstance(previous, dict) and previous.get("schema") == "kir-create-identity-assessment/1":
        source, receipt = "create_imports", previous.get("receipt_digest")
        entries = previous.get("outputs") or ()
    elif isinstance(previous, dict) and "import_lineage" in previous:
        source, entries = "import_lineage", previous["import_lineage"] or ()
        receipt = previous.get("receipt_digest")
    elif isinstance(previous, (list, tuple)):
        source, entries = "import_lineage", previous
    elif isinstance(previous, dict):
        # A bare mapping is the Level-baseline shape: {output address: identity}.
        # Its KEYS must look like output addresses, or this is some other dict
        # that would otherwise be read as one bogus output with no identity —
        # measured 13.09.2026, when `{"identity": …}` slipped through here and
        # came out as `ledger_has_no_identity_for_output`.
        keys = list(previous)
        if not keys or not all(isinstance(key, str) and len(key) == 64 for key in keys):
            raise RepublishError("previous_publication_unreadable",
                                 "a bare ledger mapping must be keyed by 64-character "
                                 "output addresses")
        source, entries = "level_streams", [
            {"output_id": key, **(value if isinstance(value, dict) else {})}
            for key, value in previous.items()]
    else:
        raise RepublishError("previous_publication_unreadable",
                             "previous publication is neither an assessment, a lineage nor a mapping")

    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("output_id"), str):
            raise RepublishError("previous_publication_unreadable",
                                 "a ledger row carries no output address")
        oid = entry["output_id"]
        identity, state = _identity_of(entry)
        rows[oid] = {"identity": identity, "state": state,
                     "source_op": entry.get("source_op") or (payloads.get(oid) or {}).get("op"),
                     "payload": payloads.get(oid),
                     "evidence": f"{source}:{entry.get('output_id')}"}
    return PreviousPublication(rows, source or "none", receipt)


def _payloads_of(program) -> dict:
    """A program -> {output address: operation payload}, addresses only.

    A flat KIR program addresses its outputs by `op["id"]` — the same value the
    submission calls `output_id` (`kir/project_submission.py:138`). A
    `ProjectRevision` is lowered by its own `to_program`, never re-implemented.
    """
    if program is None:
        return {}
    if hasattr(program, "to_program"):
        program = program.to_program()
    if not isinstance(program, dict) or not isinstance(program.get("ops"), list):
        raise RepublishError("previous_publication_unreadable",
                             "program is not a KIR envelope with an ops array")
    payloads = {}
    for op in program["ops"]:
        if not isinstance(op, dict) or not isinstance(op.get("id"), str):
            raise RepublishError("previous_publication_unreadable",
                                 "an operation carries no address")
        if op["id"] in payloads:
            raise RepublishError("previous_publication_unreadable",
                                 f"two operations share the address {op['id']}")
        payloads[op["id"]] = _thaw(op)
    return payloads


# ── the plan itself ────────────────────────────────────────────────────────
def _changed_fields(before: dict, after: dict) -> dict:
    names = (set(before) | set(after)) - set(_ADDRESS_FIELDS)
    changes = {}
    for name in sorted(names):
        was, now = before.get(name), after.get(name)
        if _canonical(was) != _canonical(now):
            changes[name] = [was, now]
    return changes


def _is_rigid_translation(before: dict, after: dict, fields) -> bool:
    """Both ends moved by the SAME vector — the only thing `move_elements` does."""
    deltas = set()
    for name in fields:
        old, new = before.get(name), after.get(name)
        if not (isinstance(old, (list, tuple)) and isinstance(new, (list, tuple))
                and len(old) == len(new)):
            return False
        deltas.add(tuple(round(float(b) - float(a), 6) for a, b in zip(old, new)))
    return len(deltas) == 1 and any(value for value in next(iter(deltas), ()))


def _decide(source_op: str, changes: dict) -> str:
    """Field changes -> a reason from the closed list. Never a guess."""
    if not changes:
        return "unchanged"
    names = set(changes)
    if names & set(_SKETCH_FIELDS):
        return "replace_sketch_unsupported"
    if names == {_TYPE_FIELD}:
        return "type_changed"
    position = set(_POSITION_FIELDS.get(source_op, ()))
    if position and names <= position:
        return "geometry_moved"
    parameters = set(_PARAMETER_FIELDS.get(source_op, ()))
    if parameters and names <= parameters:
        return "parameter_changed"
    if parameters and names <= parameters | {_TYPE_FIELD}:
        return "parameter_changed"
    return "replace_no_update_op"


_ACTION_OF_REASON = {"unchanged": "keep", "parameter_changed": "update",
                     "geometry_moved": "update", "type_changed": "update",
                     "replace_no_update_op": "replace",
                     "replace_sketch_unsupported": "replace",
                     "removed_from_program": "delete", "new_in_program": "create",
                     "no_previous_publication": "create"}


def previous_from_store(store, archive_digest: str) -> dict:
    """The ledger view of one earlier publication, read from the EXISTING tables.

    No new schema (the brief forbids one, and none is needed): the edge "this
    output continues that publication" is already `create_imports`, and the
    readers are already public —
    `ProjectStore.get_create_publication` / `.get_create_receipts`
    (`kir/project_store.py:1392,1386`).

    🔴 WHAT IS NOT INVENTED HERE. Deriving identities from a raw native receipt
    is `create_publication.assess_create_identities`'s job and needs the project
    and the bound receipt; this reader does NOT re-derive them. If a retained
    assessment is not there, the answer is a NAMED refusal that says which piece
    is missing — never a guess that becomes a UID in a plan.
    """
    if not isinstance(archive_digest, str) or len(archive_digest) != 64:
        raise RepublishError("previous_publication_unreadable",
                             "an archive digest is 64 hex characters")
    reader = getattr(store, "get_create_publication", None)
    if not callable(reader):
        raise RepublishError("previous_publication_unreadable",
                             "this store has no CREATE publication reader")
    try:
        publication = reader(archive_digest)
        receipts = store.get_create_receipts(archive_digest).to_dict()
    except Exception as failure:  # noqa: BLE001 — the boundary is named, not traced
        raise RepublishError("previous_publication_unreadable",
                             f"{type(failure).__name__} while reading {archive_digest[:12]}") from failure
    assessment = None
    for receipt in receipts.get("receipts") or ():
        held = (receipt or {}).get("identity_assessment")
        if isinstance(held, dict) and held.get("schema") == "kir-create-identity-assessment/1":
            assessment = held
    if assessment is None:
        # 🔴 MEASURED BY SECTION N ON A REAL SQLITE STORE, 13.09.2026: no product
        # writer ever puts an `identity_assessment` blob into a stored receipt
        # row — `create_publication.validate_create_receipt_claims` closes those
        # rows to exactly five fields. This reader was green only against a FAKE
        # store, and that is the worst kind of green.
        #
        # So the absence of the blob is no longer a refusal: it is the NORMAL
        # case, and the identities are RE-DERIVED from what the store does hold,
        # by the product's own path. One deriver, not two
        # (`kir/republish_archive.py::previous_from_stored_publication`).
        from kir.republish_archive import (RepublishArchiveError,
                                           previous_from_stored_publication)
        try:
            return previous_from_stored_publication(store, archive_digest)
        except RepublishArchiveError as failure:
            raise RepublishError(getattr(failure, "code", "previous_publication_unreadable"),
                                 str(failure)) from failure
    # 🔴 THE VALUES TRAVEL WITH THE IDENTITIES WHEN THE RETAINED BLOB CARRIES
    # THEM. A republication receipt keeps `program_as_published` inside the very
    # same assessment (`kir/project_republish_receipt.py::retained_payload`) —
    # not a new table, a value. Without it the next plan knows WHICH element
    # each output became but not WITH WHAT it was published, and that is the
    # named refusal `previous_payload_unavailable`.
    published = assessment.get("program_as_published")
    if published is not None:
        return {"identity": assessment, "program": published}
    return {"identity": assessment}


def _dependants(payloads: dict) -> dict:
    """{output address -> the outputs that REFER to it}, from `{by: ref}` only.

    Explicit registry references, never a guess about geometry or catalogs. This
    is what makes `replace` an ORDER (create new → rebind the dependants →
    delete the old) instead of a delete that silently takes them along.
    """
    edges: dict = {}

    def walk(value, holder):
        if isinstance(value, dict):
            if value.get("by") == "ref" and isinstance(value.get("value"), str):
                edges.setdefault(value["value"], set()).add(holder)
            for item in value.values():
                walk(item, holder)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item, holder)

    for oid, payload in payloads.items():
        walk(payload, oid)
    return {key: tuple(sorted(value)) for key, value in edges.items()}


def _cascade_of(oid: str, payloads: dict, dependants: dict) -> dict:
    """What this row's deletion would take with it — NAMED, in output addresses.

    Offline the native element ids are unknown, so the cascade is named by the
    addresses KIR owns; N turns them into ids. Saying `named: true` with an
    empty list is a real answer ("nothing refers to it"), and it is different
    from `named: false`.
    """
    touched = dependants.get(oid, ())
    return {"named": True, "outputs": list(touched), "ids": [],
            "ids_source": "resolved_by_the_emitter_from_identity_before"}


def plan_republish(store, program, previous) -> RepublishPlan:
    """The previous publication + the new program -> a closed list of actions.

    `previous` is either an already-read ledger view (an assessment, an import
    lineage, or a mapping — see `read_previous_publication`), or the 64-hex
    ARCHIVE DIGEST of an earlier publication, which is read from `store` through
    its existing public readers. Nothing is ever written here: building a plan
    must not be an effect.
    """
    if isinstance(previous, str):
        previous = previous_from_store(store, previous)
    after = _payloads_of(program)
    previous_program = None
    if isinstance(previous, dict) and ("program" in previous or "identity" in previous):
        previous_program = previous.get("program")
        rest = {key: value for key, value in previous.items() if key != "program"}
        previous = rest.get("identity", rest)
    ledger = read_previous_publication(previous, program=previous_program)

    project_id = ""
    if hasattr(program, "project_id"):
        project_id = program.project_id
    elif isinstance(program, dict):
        project_id = str(program.get("lineage") or program.get("intent") or "")
    base_revision = getattr(program, "revision_id", None)

    dependants = _dependants(after)
    rows = []
    for oid in sorted(set(after) | set(ledger.outputs)):
        known = ledger.outputs.get(oid)
        new_payload = after.get(oid)
        if known is None:
            rows.append(_row(oid, (new_payload or {}).get("op"), "new_in_program",
                             None, "unknown", {}, "program:new"))
            continue
        source_op = known.get("source_op") or (new_payload or {}).get("op")
        if new_payload is None:
            rows.append(_row(oid, source_op, "removed_from_program", known["identity"],
                             known["state"], {}, known["evidence"],
                             cascade=_cascade_of(oid, after, dependants)))
            continue
        if source_op and new_payload.get("op") and source_op != new_payload["op"]:
            raise RepublishError("output_op_kind_changed",
                                 f"{oid}: was {source_op}, now {new_payload['op']}; "
                                 "this is another program, not a repeat publication")
        before = known.get("payload")
        if before is None:
            raise RepublishError("previous_payload_unavailable",
                                 f"{oid}: the ledger carries an identity but not the values it "
                                 "was published with; pass the previous program to name the changes")
        changes = _changed_fields(before, new_payload)
        reason = _decide(source_op, changes)
        if reason == "geometry_moved" and not _is_rigid_translation(
                before, new_payload, _POSITION_FIELDS.get(source_op, ())):
            reason = "replace_no_update_op"
        if reason == "parameter_changed" and _parameter_route(source_op, changes)[0] is None:
            # П2: no route, no promise — an honest replace instead of an update
            # the emitter could not perform on a Russian document.
            reason = "replace_no_update_op"
        rows.append(_row(oid, source_op, reason, known["identity"], known["state"],
                         changes, known["evidence"],
                         depends_on=dependants.get(oid, ()),
                         cascade=_cascade_of(oid, after, dependants)))

    plan = RepublishPlan(tuple(rows), project_id, base_revision,
                         ledger.receipt_digest, ledger.ledger_source)
    _guard(plan)
    return plan


def _parameter_route(source_op: str, changes: dict) -> tuple:
    """(update_via, parameter) for a parameter change, or (None, None).

    A field absent from the closed table gets NO route — and a row with no route
    may not be planned as `update` (review point П2): a promise S cannot have N
    keep is worse than an honest `replace`.
    """
    names = [name for name in changes if (source_op, name) in _BUILTIN_PARAMETER]
    if len(names) != len(changes) or not names:
        return None, None
    parameters = sorted({_BUILTIN_PARAMETER[(source_op, name)] for name in names})
    return "builtin_parameter", parameters[0] if len(parameters) == 1 else ",".join(parameters)


def _row(output_id, source_op, reason, identity, state, changes, evidence, *,
         depends_on=(), cascade=None) -> dict:
    if reason not in REASONS:
        raise RepublishError("republish_reason_unknown", f"{output_id}: {reason}")
    action = _ACTION_OF_REASON[reason]
    row = {"output_id": output_id, "source_op": source_op, "action": action,
           "identity_before": identity,
           # A convenience mirror; the plan is EXECUTED by the triple (П1).
           "uid_before": (identity or {}).get("unique_id"),
           "identity_state_before": state if state in IDENTITY_STATES else "unknown",
           "changes": changes, "reason": reason, "evidence": evidence,
           "update_via": None, "parameter": None}
    if reason == "parameter_changed":
        row["update_via"], row["parameter"] = _parameter_route(source_op, changes)
    if action in ("delete", "replace"):
        # 🔴 THE CASCADE IS NAMED BEFORE THE EFFECT, NOT DISCOVERED AFTER (П5).
        # Live, one deletion took 10 / 13 / 12 / **38** ids with it
        # (`live-20260913-slice-cleanup-receipt.json`). `named: false` is itself
        # a reason not to execute the row.
        row["cascade"] = cascade or {"named": False, "ids": [],
                                     "diagnostic": "dependants_not_enumerated_offline"}
    if action == "replace":
        row["depends_on"] = sorted(depends_on)
        row["identity_replacement"] = {"old": (identity or {}).get("unique_id"),
                                       "new": None, "reason": reason}
    return row


def _guard(plan: RepublishPlan) -> None:
    """The plan's own laws, checked before anyone is handed it."""
    offenders = plan.creates_over_known_identity()
    if offenders:
        raise RepublishError("create_over_known_identity",
                             f"{len(offenders)} outputs would be created over a known "
                             f"element: {', '.join(sorted(offenders)[:4])}")
    for row in plan.rows:
        if row["action"] in ("keep", "delete") and row["changes"]:
            raise RepublishError("republish_reason_unknown",
                                 f"{row['output_id']}: {row['action']} carries field changes")
        if row["action"] in ("update", "replace") and not row["changes"]:
            raise RepublishError("republish_reason_unknown",
                                 f"{row['output_id']}: {row['action']} names no change")
        if row["action"] != "create" and not row.get("identity_before"):
            raise RepublishError("ledger_has_no_identity_for_output",
                                 f"{row['output_id']}: {row['action']} without a previous identity")
        if row["reason"] == "parameter_changed" and row.get("update_via") not in UPDATE_VIA:
            raise RepublishError("republish_reason_unknown",
                                 f"{row['output_id']}: a parameter update without a route; "
                                 "a display name would be refused on a non-English document")
        if row["action"] in ("delete", "replace") and not (row.get("cascade") or {}).get("named"):
            raise RepublishError("cascade_not_named",
                                 f"{row['output_id']}: {row['action']} without a named cascade")
    counted = sum(plan.counts().values())
    if counted != len(plan.rows):
        raise RepublishError("plan_counts_disagree",
                             f"{counted} counted against {len(plan.rows)} rows")
