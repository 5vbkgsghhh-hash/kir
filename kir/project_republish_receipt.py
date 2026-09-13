# -*- coding: utf-8 -*-
"""The receipt of a derived republication — written so the NEXT plan reads it.

    receipt = republish_receipt(plan, derived, results, published_program=program)
    store_blob = retained_payload(receipt)      # ложится рядом с квитанцией
    previous = receipt_as_previous(receipt)     # вход plan_republish

🔴 THE LOOP THIS CLOSES. `plan_republish` decides, `republish_program` emits —
and until now nothing carried the RESULT back, so the second republication
started from nothing and planned everything as `create`. That is the duplicate
arriving by the back door: measured live on 13.09.2026, three publications of
one program gave walls 4→8→12, floors 1→2→3, **+25 instances per repeat**
(`/root/kir-live-20260909/live-20260913-slice-opening-receipt.json`).

🔴 NO NEW STORE SCHEMA — the rule the planner set in its own header, kept here.
The receipt is retained in the shape the tree ALREADY has a reader for:
`kir-create-identity-assessment/1` (`kir/create_publication.py:363`), which
`kir.project_republish.read_previous_publication` understands, and whose edge
"this output continues that publication" is the existing table `create_imports`
(`kir/project_create_store.py:60-66`). The only addition is one key INSIDE that
retained blob, `program_as_published` — a value, not a table.

🔴 WHAT EACH ACTION LEAVES BEHIND, and why the next plan needs exactly this:
* `keep`   — identity unchanged; the output must still be there next time;
* `update` — identity unchanged BY CONSTRUCTION (that is what "in place" means),
             and the VALUES move to the new ones;
* `replace`— a NEW identity, plus an `identity_replacement {old, new, reason}`;
* `delete` — the output LEAVES the ledger, so the next plan cannot delete it
             twice or, worse, plan a `create` over a живого element;
* `create` — a new identity.

Revit is not launched here and nothing is emitted: this module turns what the
emitter reported into what the planner can read.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256

from kir.project import ProjectError
from kir.project_republish import IDENTITY_SCHEMA, REPUBLISH_PLAN_SCHEMA

#: The retained shape. Not ours — the tree's, and the planner already reads it.
ASSESSMENT_SCHEMA = "kir-create-identity-assessment/1"
RECEIPT_SCHEMA = "kir-republish-receipt/1"


class RepublishReceiptError(ProjectError):
    """The receipt could not be built. Named code, never a guess."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _identity(value, *, owner: str) -> dict:
    """An identity the emitter reported — all three fields or a named refusal.

    A "lost" identity is the dangerous case: if it silently became `None`, the
    next plan would see no previous identity and plan `create` — a duplicate
    over a live element. So it is refused HERE, where the fact is still fresh.
    """
    if not isinstance(value, dict) or not value.get("unique_id"):
        raise RepublishReceiptError(
            "identity_after_missing",
            f"{owner}: исполнение не вернуло личность. Пропустить её значит "
            "дать СЛЕДУЮЩЕМУ плану основание создать элемент заново поверх "
            "живого. СЛЕДУЮЩИЙ ХОД: перечитай элемент (query_element_state) "
            "и подай личность, либо пометь строку как неисполненную")
    return {"schema_version": value.get("schema_version") or IDENTITY_SCHEMA,
            "element_id": value.get("element_id"),
            "unique_id": value["unique_id"],
            "version_guid": value.get("version_guid")}


@dataclass(frozen=True, slots=True)
class RepublishReceipt:
    """What the ledger must know after one republication. Inert."""

    outputs: tuple
    replacements: tuple
    program_as_published: dict
    plan_digest: str
    counts: dict
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", sha256(_canonical(self._body())).hexdigest())

    def _body(self) -> dict:
        return {"schema": RECEIPT_SCHEMA, "plan_digest": self.plan_digest,
                "outputs": [dict(row) for row in self.outputs],
                "identity_replacements": [dict(row) for row in self.replacements],
                "program_as_published": self.program_as_published,
                "counts": dict(self.counts)}

    def to_dict(self) -> dict:
        return {**self._body(), "receipt_digest": self.digest,
                "claims": {"native_execution": "reported_by_the_emitter",
                           "engineering_acceptance": "not_established",
                           "dispatch_permission": "none"}}

    def surviving(self) -> tuple:
        return tuple(row["output_id"] for row in self.outputs)


def republish_receipt(plan, derived, results, *, published_program) -> RepublishReceipt:
    """plan + derived program + what the emitter reported -> the ledger's next state.

    `results` — `{output_id: {"identity": {...}, "ok": bool}}` for the rows that
    produced or moved an element. `keep` and `update` need no entry: their
    identity is the one the plan already carried, and inventing a second source
    for it is how two carriers of one fact begin.

    🔴 `published_program` IS THE AUTHOR'S PROGRAM OF THIS ROUND, NOT THE
    DERIVED ONE, and the first version of this module got that wrong. The
    derived program is a DELTA — four `set_param`s carry no wall. The next plan
    diffs the author's values against the author's values; handed a delta it
    answered `previous_payload_unavailable`, which is how the mistake was
    caught, in the first round trip.
    """
    body = plan.to_dict() if hasattr(plan, "to_dict") else plan
    if not isinstance(body, dict) or body.get("schema") != REPUBLISH_PLAN_SCHEMA:
        raise RepublishReceiptError("not_a_republish_plan",
                                    f"ожидалась схема {REPUBLISH_PLAN_SCHEMA}")
    program = derived.program if hasattr(derived, "program") else (derived or {}).get("program")
    if not isinstance(program, dict) or "ops" not in program:
        raise RepublishReceiptError("not_a_derived_program",
                                    "нужна производная программа с массивом ops")
    authored = (published_program.to_program() if hasattr(published_program, "to_program")
                else published_program)
    if not isinstance(authored, dict) or not isinstance(authored.get("ops"), list):
        raise RepublishReceiptError(
            "not_an_authored_program",
            "нужна АВТОРСКАЯ программа этого круга: ledger хранит значения, "
            "с которыми выходы опубликованы, а производная программа — дельта")
    reported = dict(results or {})
    outputs, replacements, counts = [], [], {}
    for row in body.get("rows") or ():
        action, oid = row["action"], row["output_id"]
        counts[action] = counts.get(action, 0) + 1
        result = reported.get(oid) or {}
        if result.get("ok") is False:
            raise RepublishReceiptError(
                "row_reported_failed",
                f"{oid}: исполнение строки {action} не удалось; квитанция такой "
                "строки не записывается — иначе ledger соврёт следующему плану")
        if action == "delete":
            # 🔴 IT LEAVES. A deleted output that stayed in the ledger would be
            # deleted again next time, or — worse — its stale identity would be
            # read as "this element exists".
            continue
        if action in ("keep", "update"):
            identity = row.get("identity_before")
            if not identity:
                raise RepublishReceiptError("row_without_identity",
                                            f"{oid}: {action} без прежней личности")
            outputs.append({"output_id": oid, "source_op": row.get("source_op"),
                            "state": row.get("identity_state_before") or "created_here",
                            "element_identity": dict(identity)})
            continue
        identity = _identity(result.get("identity"), owner=f"{oid} ({action})")
        outputs.append({"output_id": oid, "source_op": row.get("source_op"),
                        "state": "created_here", "element_identity": identity})
        if action == "replace":
            replacements.append({"output_id": oid,
                                 "old": (row.get("identity_before") or {}).get("unique_id"),
                                 "new": identity["unique_id"],
                                 "reason": row.get("reason")})
    published = {op["id"] for op in authored["ops"] if isinstance(op.get("id"), str)}
    missing = sorted(row["output_id"] for row in outputs if row["output_id"] not in published)
    if missing:
        raise RepublishReceiptError(
            "authored_program_does_not_cover_the_receipt",
            f"выходы {missing[:3]} остались в ledger'е, но их нет в авторской "
            "программе этого круга — значения взять неоткуда")
    return RepublishReceipt(tuple(outputs), tuple(replacements), authored,
                            body.get("plan_digest") or "", counts)


def retained_payload(receipt: RepublishReceipt) -> dict:
    """The blob that rides with the stored receipt, in the EXISTING shape.

    `kir-create-identity-assessment/1` is what `read_previous_publication`
    already understands (`kir/project_republish.py`), so nothing new has to be
    taught to the reader. `program_as_published` rides INSIDE it because the
    next plan cannot name `changes` without the values that were published —
    that absence is otherwise the named refusal `previous_payload_unavailable`.
    """
    return {"schema": ASSESSMENT_SCHEMA, "receipt_digest": receipt.digest,
            "outputs": [dict(row) for row in receipt.outputs],
            "identity_replacements": [dict(row) for row in receipt.replacements],
            "program_as_published": receipt.program_as_published}


def receipt_as_previous(receipt: RepublishReceipt) -> dict:
    """Exactly what `plan_republish(..., previous=…)` takes."""
    blob = retained_payload(receipt)
    return {"identity": blob, "program": blob["program_as_published"]}


def import_edges(receipt: RepublishReceipt, *, archive_digest: str,
                 original_archive_digest: str, original_receipt_digest: str) -> tuple:
    """The rows for the EXISTING table `create_imports` — no new table.

    `(archive_digest, output_id, original_archive_digest, original_receipt_digest)`
    is `kir/project_create_store.py:60-66` verbatim: the edge "this output
    CONTINUES that publication", which is what E3 was opened for. The writer of
    those rows is `reserve(...)` (`:517,552`) and it needs a real
    `SavedExecutionRecord`; that record's shape is section N's emission, so this
    function hands the rows over ready rather than inventing a second writer.
    """
    for name, value in (("archive_digest", archive_digest),
                        ("original_archive_digest", original_archive_digest),
                        ("original_receipt_digest", original_receipt_digest)):
        if not isinstance(value, str) or len(value) != 64:
            raise RepublishReceiptError("digest_is_not_a_digest",
                                        f"{name}: ожидалось 64 hex-символа")
    return tuple(sorted((archive_digest, row["output_id"], original_archive_digest,
                         original_receipt_digest) for row in receipt.outputs))
