"""Scoped proposals for authored snapshots, not observed-model/native patches.

The atomic edit unit is a complete module or instance. A sealed evaluation's
parameters, outputs and recipe pin are never field-merged into a result nobody
produced. Collection order and project context are separately owned fields.
Explicit-reference impact comes from project_diff, not arbitrary JSON scanning.

Unlike decompile.merge3, this layer retains authored identity/order/provenance;
it does not merge canonical-operation multisets or bypass BuildingJournal's
decision guard. Neither mechanism proves geometric/engineering preservation.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
from typing import Any, Mapping, Sequence

from kir.project import (
    ProjectError, ProjectRevision, _canonical, _digest, _fields, _freeze,
    _hash, _key, _object, _thaw,
)
from kir.project_diff import diff_projects
from kir.project_store import CommitResult, ProjectStore, StoreConflict


PROPOSAL_SCHEMA = "kir-authoring-proposal/1"
MERGE_SCHEMA = "kir-authoring-merge/1"
_CONTEXT = ("intent", "metadata", "module_order", "instance_order")
_MISSING = object()


class ProposalError(ProjectError):
    """Malformed proposal or missing caller-granted write scope."""


def _keys(values: Sequence[str], name: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise ProposalError(f"{name}: expected an explicit key sequence")
    checked = tuple(_key(value, name) for value in values)
    if len(set(checked)) != len(checked):
        raise ProposalError(f"{name}: duplicate scope key")
    return tuple(sorted(checked))


@dataclass(frozen=True, slots=True)
class ProposalScope:
    """Write grant, not authentication or a claim that effects stay in scope.

    The accepting caller supplies its own grant; a proposal cannot grant itself
    authority by changing its serialized scope. Actor authentication/assignment
    storage remains the caller's responsibility.
    """

    instances: Sequence[str] = ()
    modules: Sequence[str] = ()
    project_fields: Sequence[str] = ()

    def __post_init__(self) -> None:
        for name in ("instances", "modules", "project_fields"):
            object.__setattr__(self, name, _keys(getattr(self, name), name))
        if set(self.project_fields) - set(_CONTEXT):
            raise ProposalError("project_fields: unknown field; schema/IR migration is not a merge")

    def to_dict(self) -> dict:
        return {key: list(getattr(self, key)) for key in ("instances", "modules", "project_fields")}

    @classmethod
    def from_dict(cls, value: Any) -> ProposalScope:
        return cls(**_fields(value, {"instances", "modules", "project_fields"}, "scope"))

    def covers(self, other: ProposalScope) -> bool:
        return all(set(getattr(other, key)) <= set(getattr(self, key))
                   for key in ("instances", "modules", "project_fields"))


def _parts(project: ProjectRevision) -> dict:
    data = project.to_dict()
    return {
        "modules": {row["key"]: row for row in data["modules"]},
        "instances": {row["key"]: row for row in data["instances"]},
        "intent": data["intent"], "metadata": data["metadata"],
        "module_order": [row["key"] for row in data["modules"]],
        "instance_order": [row["key"] for row in data["instances"]],
    }


def _same(left: Any, right: Any) -> bool:
    if left is _MISSING or right is _MISSING:
        return left is right
    return _canonical(left) == _canonical(right)


def _changed_scope(base: dict, target: dict) -> ProposalScope:
    collections = {}
    for name in ("instances", "modules"):
        collections[name] = tuple(key for key in base[name].keys() | target[name].keys()
                                  if not _same(base[name].get(key, _MISSING),
                                               target[name].get(key, _MISSING)))
    return ProposalScope(**collections, project_fields=tuple(
        name for name in _CONTEXT if not _same(base[name], target[name])))


#: The reason the dependency walk below gives BY ITSELF; unfit as a premise.
_DERIVED_REASON = "dependency_changed"
#: The reason "the instance's passport changed": description/names/tags, not the operation.
_METADATA_REASON = "instance_metadata_changed"
#: The reason "this op's reference could not be grounded". A property of the
#: PROJECT when a side's `dependency_issues` stand byte-identical before and
#: after; then it says nothing about that side's edit (see `_only_passports_moved`).
_INCOMPLETE_REASON = "dependency_analysis_incomplete"


#: Instance-passport keys that the PRODUCT code READS (not the tests), and are
#: therefore NOT inert. The list is closed and is guarded by the instrument
#: `kir/tests/test_a_metadata_only_change_is_not_a_conflict.py`
#: (`test_the_closed_list_of_load_bearing_metadata_keys_is_not_stale`), which
#: rereads the product sources: a new reader of the passport reddens the suite.
#: refinement — project_diff.py:247, project_refinement.py:225/278/952 (edge);
#: refines — project_refinement.py:252/291/293 (source address);
#: recipe_evaluation — project_recipe.py:171-180 (evaluation pin);
#: ownership_handoff — project_handoff.py:54/78 (ownership transfer);
#: pending_source_change — project_refinement.py:1206/1239/1260/1285 and
#: viewer/standalone_export.py:324 (open questions on a source edit);
#: refinement_decisions — project_refinement.py:1282 (`_DECISIONS_KEY`),
#: read at 1198/1334 (`answered_decisions`) and appended to at 1396: accepted
#: decisions live until the project ends, so editing them is not a passport edit;
#: category, source_category — clash/repair_profile.py:189 (`classify`), :213-215 (category parsing) (`classify`):
#: the instance's category decides whether repair refuses on the MEP trait, so
#: changing the word in the passport changes the repair decision, not just the label.
#: refinement_baseline — project_refinement.py:1161 (`_BASELINE_KEY`), read at
#: 1184 (`_baseline_row`), written at 1464/1509: this is the R0 measurement
#: baseline from which the ACCUMULATED deviation is computed, so editing it
#: changes the number, not just the label.
_LOAD_BEARING_METADATA = ("refinement", "refines", "recipe_evaluation",
                          "ownership_handoff", "pending_source_change",
                          "refinement_decisions", "category", "source_category",
                          "refinement_baseline")


def _inert_metadata_instances(delta: dict) -> set[str]:
    """Instances where ONLY the passport changed, and ONLY in its non-read part.

    `instance.metadata` is the author's description: names, notes, tags. No
    operation is recomputed from them, and editing the description alone
    cannot invalidate someone else's branch. But part of the passport the
    product DOES READ — provenance, the evaluation pin, ownership, open
    questions (see `_LOAD_BEARING_METADATA`); an edit there remains a full
    edit.
    The `fields` row gives exactly the fields of the instance row that
    changed, so "passport only" here is a measured fact, not a guess about
    intent.
    """
    inert = set()
    for entry in (delta.get("instances") or {}).get("entries") or ():
        fields = entry.get("fields")
        if not fields or set(fields) != {"metadata"} or entry.get("key") is None:
            continue
        before, after = fields["metadata"].get("before"), fields["metadata"].get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        if all(_same(before.get(key, _MISSING), after.get(key, _MISSING))
               for key in _LOAD_BEARING_METADATA):
            inert.add(entry["key"])
    return inert


def _only_passports_moved(delta: dict) -> bool:
    """This side changed NOTHING BUT instance passports, and not one operation.

    Used to disarm `dependency_analysis_incomplete` — and ONLY it. The premise
    of that refusal is "divergent edits must not independently alter a shared
    explicit dependency". An edit that adds, removes, changes or re-keys no
    operation, no module and no project field cannot alter any dependency,
    resolvable or not; and `dependency_issues` standing byte-identical before
    and after says the unresolved region was not touched either. So on such a
    side the premise is vacuous, and the merge may go on to the overlap walk —
    where `_inert_metadata_instances` already knows what a passport is worth.

    Anything beyond a passport keeps the conservative refusal: there a missing
    dependency edge could hide a real overlap, and this function returns False.

    Measured 13.09.2026 on the saved complex of
    `examples/final_result_walkthrough.py` (9 instances): two renames of
    DIFFERENT instances were refused `dependency_analysis_incomplete` while
    both sides carried the same two pre-existing `selector_requires_grounding`
    issues, before == after. `added/removed/changed/rekeyed` were all empty.
    """
    if any(delta.get(name) for name in ("added", "removed", "changed", "rekeyed")):
        return False
    if (delta.get("modules") or {}).get("entries"):
        return False
    # `parent_revision` moves on every child revision; it is bookkeeping, not
    # authored content, and it is not part of `_CONTEXT`.
    if set(delta.get("project_changes") or {}) - {"parent_revision"}:
        return False
    issues = delta.get("dependency_issues") or {}
    if issues.get("before") != issues.get("after"):
        return False
    changed = set((delta.get("instances") or {}).get("changed") or ())
    return bool(changed) and changed <= _inert_metadata_instances(delta)


def _typed_revision(value: Any) -> None:
    if type(value) is not ProjectRevision:
        raise ProposalError("expected an exact immutable ProjectRevision")


@dataclass(frozen=True, slots=True)
class ChangeProposal:
    """Portable inert branch: exact base, one proposed child, scope and reason.

    Hashes detect changes, not authorship. Loading never plans KIR, resolves a
    body asset, imports recipe source or writes to a project store.
    """

    base: ProjectRevision
    candidate: ProjectRevision
    scope: ProposalScope
    author: str
    reason: str
    proposal_id: str = field(init=False)

    def __post_init__(self) -> None:
        for revision in (self.base, self.candidate):
            _typed_revision(revision)
        if type(self.scope) is not ProposalScope:
            raise ProposalError("scope must be ProposalScope")
        for name in ("author", "reason"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ProposalError(f"{name}: expected nonempty text")
            _freeze(value, name)
        for name in ("project_id", "schema", "ir_version"):
            if getattr(self.base, name) != getattr(self.candidate, name):
                raise ProposalError(f"proposal cannot change {name}")
        if (self.candidate.revision_id != self.base.revision_id
                and self.candidate.parent_revision != self.base.revision_id):
            raise ProposalError("candidate must be the exact base or its direct authored child")
        if not self.scope.covers(_changed_scope(_parts(self.base), _parts(self.candidate))):
            raise ProposalError("proposal changes data outside its declared write scope")
        object.__setattr__(self, "proposal_id", _hash(self._body()))

    def _body(self) -> dict:
        return {"schema": PROPOSAL_SCHEMA, "base": self.base.to_dict(),
                "candidate": self.candidate.to_dict(), "scope": self.scope.to_dict(),
                "author": self.author, "reason": self.reason}

    def to_dict(self) -> dict:
        return {**self._body(), "proposal_id": self.proposal_id}

    def dumps(self) -> str:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: Any) -> ChangeProposal:
        data = _fields(value, {"schema", "base", "candidate", "scope", "author",
                               "reason", "proposal_id"}, "proposal")
        if data["schema"] != PROPOSAL_SCHEMA:
            raise ProposalError("unsupported proposal schema")
        proposal = cls(ProjectRevision.from_dict(data["base"]),
                       ProjectRevision.from_dict(data["candidate"]),
                       ProposalScope.from_dict(data["scope"]), data["author"], data["reason"])
        if _digest(data["proposal_id"], "proposal_id") != proposal.proposal_id:
            raise ProposalError("proposal integrity mismatch")
        return proposal

    @classmethod
    def loads(cls, source: str) -> ChangeProposal:
        if not isinstance(source, str):
            raise ProposalError("proposal JSON must be a string")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ProposalError(f"duplicate proposal JSON key: {key}")
                result[key] = value
            return result

        def constant(value):
            raise ProposalError(f"non-finite JSON scalar: {value}")

        try:
            return cls.from_dict(json.loads(source, object_pairs_hook=pairs, parse_constant=constant))
        except (ValueError, TypeError, RecursionError) as error:
            raise ProposalError(f"invalid proposal JSON: {error}") from error


@dataclass(frozen=True, slots=True)
class AuthoringMerge:
    revision: ProjectRevision | None
    _report: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_report", _object(self._report, "merge_report"))

    @property
    def clean(self) -> bool:
        """No AUTHORING conflicts; never a semantic/native acceptance verdict."""
        return self.revision is not None

    def to_dict(self) -> dict:
        return _thaw(self._report)


def merge_proposal(proposal: ChangeProposal, current: ProjectRevision, *,
                   authorized_scope: ProposalScope) -> AuthoringMerge:
    """Pure three-way authoring merge, with caller-asserted common ancestry.

    Use accept_proposal for stored ancestry + expected-head CAS. No ours/theirs
    overwrite policy exists: conflicting results contain NO candidate revision.
    Unknown explicit dependency analysis blocks a divergent merge. No compiler,
    implicit spatial/catalog dependency or native reconciliation is implied.
    """
    if type(proposal) is not ChangeProposal or type(authorized_scope) is not ProposalScope:
        raise ProposalError("expected typed proposal and caller-granted scope")
    _typed_revision(current)
    if not authorized_scope.covers(proposal.scope):
        raise ProposalError("proposal scope exceeds the caller's write grant")
    base, candidate = proposal.base, proposal.candidate
    if current.project_id != base.project_id:
        raise ProposalError("cannot merge another project")
    conflicts: list[dict] = []
    report = {"schema": MERGE_SCHEMA, "scope": "authoring_only",
              "proposal_id": proposal.proposal_id, "project_id": base.project_id,
              "base_revision": base.revision_id, "proposed_revision": candidate.revision_id,
              "current_revision": current.revision_id, "result_revision": None,
              "ancestry": "caller_asserted", "semantic_validation": "not_run",
              "geometry_validation": "not_run", "native_execution": "not_run",
              "conflicts": conflicts, "impact": None,
              "limitations": ["Only explicit registry reference dependencies are analyzed.",
                              "Implicit spatial/catalog dependencies and protected engineering decisions are not proved.",
                              "Atomic instances and conservative impact may require manual agent re-planning."]}

    def finish(revision=None):
        report["result_revision"] = revision.revision_id if revision is not None else None
        report["status"] = ("conflict" if revision is None else "unchanged"
                            if revision.revision_id == current.revision_id else "merged")
        return AuthoringMerge(revision, report)

    for name in ("schema", "ir_version"):
        if getattr(current, name) != getattr(base, name):
            conflicts.append({"kind": "version_diverged", "path": name})
    if conflicts:
        return finish()
    old, ours, theirs = _parts(base), _parts(current), _parts(candidate)

    def choose(path, before, now, proposed):
        if _same(now, proposed) or _same(proposed, before):
            return now
        if _same(now, before):
            return proposed
        kind = ("add_add" if before is _MISSING else "delete_modify"
                if now is _MISSING or proposed is _MISSING else "modify_modify")
        conflicts.append({"kind": kind, "path": path, **{
            name: None if value is _MISSING else _hash(value)
            for name, value in (("base_sha256", before), ("current_sha256", now),
                                ("proposed_sha256", proposed))}})
        return now  # Used only to collect conflicts, never returned as a revision.

    merged = {name: choose(name, old[name], ours[name], theirs[name]) for name in _CONTEXT}
    for name in ("modules", "instances"):
        rows = {}
        for key in sorted(old[name].keys() | ours[name].keys() | theirs[name].keys()):
            value = choose(f"{name}/{key}", old[name].get(key, _MISSING),
                           ours[name].get(key, _MISSING), theirs[name].get(key, _MISSING))
            if value is not _MISSING:
                rows[key] = value
        merged[name] = rows
    if conflicts:
        return finish()
    if _same(merged, ours):
        report["impact"] = diff_projects(current, current).to_dict()
        return finish(current)

    # Divergent edits must not independently alter a shared explicit dependency.
    # Complete identical result was handled above; overlap remains conservative.
    divergent = not _same(old, ours) and not _same(old, theirs)
    passports_only = False
    if divergent:
        left = diff_projects(base, current).to_dict()
        right = diff_projects(base, candidate).to_dict()
        # Judged ONCE per side and carried into the walk: the same question is
        # asked at the gate and inside `impacted`, and two answers would be two
        # carriers of one fact.
        only_passports = (_only_passports_moved(left), _only_passports_moved(right))
        passports_only = all(only_passports)
        incomplete = not all(delta["analysis"]["explicit_reference_analysis_complete"]
                             for delta in (left, right))
        if incomplete and not passports_only:
            conflicts.append({"kind": "dependency_analysis_incomplete", "path": "dependencies",
                              "current": left["dependency_issues"], "proposed": right["dependency_issues"]})
        else:
            # A ref introduced on one side must also propagate the OTHER
            # side's changes. Per-branch closures alone miss a moved/deleted
            # level newly referenced by the proposed wall.
            downstream = defaultdict(set)
            for delta in (left, right):
                for edges in delta["dependencies"].values():
                    for edge in edges:
                        downstream[edge["source"]].add(edge["dependent"])
            def impacted(delta, passports):
                # The walk's premise is the REASONS for outputs, not a ready-
                # made `affected`: that is already a closure itself, and it
                # cannot distinguish a real change from a consequence of
                # someone else's. Three reasons are lifted: the one derived by
                # the walk; the passport one (for inert instances); and, for a
                # side that moved NOTHING BUT passports, the project's own
                # ungrounded-reference gap — that side cannot have created a
                # gap that its `dependency_issues` show unchanged, so the
                # reason carries no fact about its edit. A side that touched an
                # operation keeps that reason: there the gap may be its own.
                # A delta with no reason (a different producer, stale data) is
                # NOT counted as inert: the premise taken is the previous, full one.
                inert = _inert_metadata_instances(delta)
                lifted = {_DERIVED_REASON} | ({_INCOMPLETE_REASON} if passports else set())
                seen = set()
                for row in delta["outputs"]:
                    if not {"op_id", "reasons", "instance_key"} <= set(row):
                        seen = set().union(*(delta[name] for name in
                                             ("added", "removed", "changed", "affected")))
                        break
                    if set(row["reasons"]) - lifted - (
                            {_METADATA_REASON} if row["instance_key"] in inert else set()):
                        seen.add(row["op_id"])
                queue = deque(seen)
                while queue:
                    for dependent in downstream.get(queue.popleft(), ()):
                        if dependent not in seen:
                            seen.add(dependent)
                            queue.append(dependent)
                return seen
            overlap = sorted(impacted(left, only_passports[0])
                             & impacted(right, only_passports[1]))
            if overlap:
                conflicts.append({"kind": "dependency_overlap", "path": "dependencies", "op_ids": overlap})
        if conflicts:
            return finish()

    try:
        for collection, order in (("modules", "module_order"), ("instances", "instance_order")):
            if set(merged[collection]) != set(merged[order]):
                raise ProposalError(f"{order} does not cover the merged collection")
        body = {**current.to_dict(), "parent_revision": current.revision_id,
                "intent": merged["intent"], "metadata": merged["metadata"],
                "modules": [merged["modules"][key] for key in merged["module_order"]],
                "instances": [merged["instances"][key] for key in merged["instance_order"]]}
        body.pop("revision_id")
        body["revision_id"] = _hash(body)
        revision = ProjectRevision.from_dict(body)
    except ProjectError as error:
        conflicts.append({"kind": "structural_incompatibility", "path": "project", "message": str(error)})
        return finish()
    report["impact"] = diff_projects(current, revision).to_dict()
    # The same reasoning as at the first gate: when both sides moved only
    # passports, the merged result inherits the project's PRE-EXISTING analysis
    # gap, which neither side created. Refusing here would put the false
    # conflict back one line further down.
    if (divergent and not passports_only
            and not report["impact"]["analysis"]["explicit_reference_analysis_complete"]):
        conflicts.append({"kind": "merged_dependency_analysis_incomplete", "path": "dependencies",
                          "issues": report["impact"]["dependency_issues"]})
        return finish()
    return finish(revision)


@dataclass(frozen=True, slots=True)
class ProposalAcceptance:
    merge: AuthoringMerge
    commit: CommitResult | None


def accept_proposal(store: ProjectStore, proposal: ChangeProposal, *,
                    expected_revision: str, authorized_scope: ProposalScope,
                    assets: tuple | list = ()) -> ProposalAcceptance:
    """Verify stored ancestry, merge and CAS-append. Never dispatch native work.

    The linear store keeps the accepted revision; the proposal/report are
    separate serializable artifacts, NOT an automatically durable branch log.
    History audit is intentionally O(history), including inert asset integrity.
    A new divergent append racing after that read is refused by atomic commit.
    Exact already-stored redelivery may instead acknowledge the earlier write
    and report a later head, following ProjectStore's existing retry contract.
    """
    if type(store) is not ProjectStore or type(proposal) is not ChangeProposal:
        raise ProposalError("expected typed store and proposal")
    _digest(expected_revision, "expected_revision")
    history = store.history()
    current = history[-1]
    if current.revision_id != expected_revision:
        raise StoreConflict("proposal acceptance expected a different current head")
    ancestors = {revision.revision_id: revision for revision in history}
    ancestor = ancestors.get(proposal.base.revision_id)
    if ancestor is None or ancestor.dumps() != proposal.base.dumps():
        raise StoreConflict("proposal base is not an exact revision in this stored history")
    result = merge_proposal(proposal, current, authorized_scope=authorized_scope)
    report = result.to_dict()
    report["ancestry"] = "verified_stored_history"
    result = AuthoringMerge(result.revision, report)
    if not result.clean:
        return ProposalAcceptance(result, None)
    committed = store.commit(result.revision, expected_revision=result.revision.parent_revision, assets=assets)
    if result.revision.revision_id == current.revision_id and committed.head_revision != expected_revision:
        raise StoreConflict("head changed during unchanged proposal acceptance")
    return ProposalAcceptance(result, committed)


__all__ = ["PROPOSAL_SCHEMA", "MERGE_SCHEMA", "ProposalError", "ProposalScope",
           "ChangeProposal", "AuthoringMerge", "ProposalAcceptance", "merge_proposal", "accept_proposal"]
