# -*- coding: utf-8 -*-
"""A republication receipt becomes a `SavedExecutionRecord`, so the store can hold it.

    record = saved_record_from_receipt(receipt, project=…, materialized=…,
                                       target=…, precondition=…, operation_id=…)
    store.reserve_create_publication(record, expected_revision=project.revision_id)

🔴 THE GAP THIS CLOSES, NAMED TWICE BY S. `plan_republish` decides,
`republish_program` emits, `republish_receipt` says what came back — and the
ledger could not hold any of it, because every writer into the store
(`reserve(...)`, `record_receipt(...)`) demands an exact Archive/2
`SavedExecutionRecord`, and building one is section N's business: it is the
archive of an EMISSION. Without this the next `plan_republish` reads nothing,
plans everything as `create`, and the duplicate arrives by the back door —
measured live on 13.09.2026: three publications of one program, walls 4 → 8 → 12,
floors 1 → 2 → 3, +25 instances per repeat.

🔴 WHAT IS CHECKED HERE AND WHY HERE. `republish_receipt` already refuses an
execution that returned no identity (`identity_after_missing`). This function
checks it AGAIN, and that is not duplication: a receipt can also arrive from a
file, a replay or another process, and the store is the last place before the
fact becomes permanent. A record written from an identity-less receipt would let
the NEXT plan create an element over a live one — the exact failure the whole
loop exists to prevent — and it would do so quietly, months later.

NOTHING IS EMITTED, COMPILED AGAINST REVIT OR DISPATCHED here, and no new store
schema is introduced: the record is the shape `create_imports` / `create_inputs`
already read.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

RECEIPT_SCHEMA = "kir-republish-receipt/1"
IDENTITY_SCHEMA = "revit-element-identity/1"


class RepublishArchiveError(ValueError):
    """A named refusal; no record is built."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _rows_of(receipt: Any) -> Sequence[Mapping[str, Any]]:
    body = receipt.to_dict() if hasattr(receipt, "to_dict") else receipt
    if not isinstance(body, Mapping):
        raise RepublishArchiveError(
            "not_a_republish_receipt",
            f"ожидалась квитанция {RECEIPT_SCHEMA}, пришло {type(receipt).__name__}")
    if body.get("schema") != RECEIPT_SCHEMA:
        raise RepublishArchiveError(
            "not_a_republish_receipt",
            f"ожидалась схема {RECEIPT_SCHEMA}, пришла {body.get('schema')!r}")
    rows = body.get("outputs")
    if not isinstance(rows, list) or not rows:
        raise RepublishArchiveError(
            "republish_receipt_has_no_outputs",
            "квитанция без выходов не описывает публикацию: записывать в реестр нечего")
    return rows


def check_identities(receipt: Any) -> tuple[str, ...]:
    """Every output carries a full identity, or a named refusal. Returns the ids.

    The check is on the TRIPLE, not on presence: `element_id` alone is an address
    inside one document and Revit reuses it after a deletion, so a row that has
    only a number would let the next plan address whatever now holds it.
    """
    seen: list[str] = []
    for index, row in enumerate(_rows_of(receipt)):
        oid = row.get("output_id") if isinstance(row, Mapping) else None
        if not isinstance(oid, str) or not oid:
            raise RepublishArchiveError("output_without_id",
                                        f"строка {index} не называет output_id")
        identity = row.get("element_identity")
        if not isinstance(identity, Mapping) or not identity.get("unique_id"):
            raise RepublishArchiveError(
                "identity_after_missing",
                f"{oid}: квитанция не несёт личность после исполнения. Записать её в "
                "реестр без личности значит дать СЛЕДУЮЩЕМУ плану основание создать "
                "элемент заново поверх живого. СЛЕДУЮЩИЙ ХОД: перечитай элемент "
                "(query_element_state) и подай личность, либо не записывай эту "
                "публикацию вовсе")
        if identity.get("element_id") is None:
            raise RepublishArchiveError(
                "identity_after_incomplete",
                f"{oid}: есть unique_id, нет element_id — адресовать элемент "
                "мутирующим опом будет нечем (ни один из них не принимает UniqueId)")
        if oid in seen:
            raise RepublishArchiveError("output_repeated",
                                        f"{oid}: один выход назван дважды")
        seen.append(oid)
    return tuple(seen)


def saved_record_from_receipt(receipt: Any, *, project: Any, materialized: Any,
                              target: Any, precondition: Any, operation_id: str):
    """The receipt's publication as an Archive/2 record the store can reserve.

    `project` / `materialized` — the authored revision of THIS round and its
    materialization; the record's submission is built from them by the existing
    `bind_project_submission`, never by a second binder written here.

    The receipt is not embedded in the record: the record archives the EMISSION,
    and the receipt travels beside it, in the shape the ledger already reads
    (`retained_payload` → `record_create_receipt`). Two carriers of one fact is
    what this tree pays for most often; this is deliberately not a third.
    """
    outputs = check_identities(receipt)

    from kir.project_submission import bind_project_submission
    from kir.revit_connector import prepare_execution
    from kir.saved_execution import SavedExecutionRecord

    planned = getattr(materialized, "planned", None)
    if planned is None:
        raise RepublishArchiveError(
            "materialization_required",
            "нужна материализация авторской ревизии: из неё берётся план, а "
            "программу-дельту (четыре set_param) в реестр писать нельзя — "
            "следующий план сверяет АВТОРСКИЕ значения, а не дельту")
    prepared = prepare_execution(planned, target=target, precondition=precondition,
                                 operation_id=operation_id)
    submission = bind_project_submission(project, materialized, prepared)
    record = SavedExecutionRecord.capture_project(prepared, submission)

    declared = {row["output_id"] for row in submission.to_dict()["outputs"]}
    unknown = sorted(set(outputs) - declared)
    if unknown:
        raise RepublishArchiveError(
            "receipt_names_outputs_the_submission_does_not",
            f"{', '.join(unknown)} — квитанция и запись описывают разные публикации; "
            "связать их значило бы приписать личности чужому входу")
    return record


# ───────────────────────── the way back out of the store ─────────────────────

def _terminal_receipt(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    from kir.connector_result import native_receipt_terminal_state
    terminal = [row for row in rows
                if native_receipt_terminal_state(row["native_receipt"]) is not None]
    if not terminal:
        raise RepublishArchiveError(
            "publication_has_no_terminal_receipt",
            f"публикация удержала {len(rows)} промежуточных квитанций и ни одной "
            "терминальной: чем кончилось исполнение — не установлено, и строить "
            "на этом план нельзя. СЛЕДУЮЩИЙ ХОД: восстанови исполнение "
            "(`recover_stored_create`) и запиши терминальную квитанцию")
    return terminal[-1]


def program_as_published(record: Any) -> dict:
    """The program the archive itself holds — not a delta, not a remembered copy.

    🔴 WHY FROM `plan_evidence` AND NOT FROM THE CALLER. The next plan compares
    AUTHORED VALUES (`expected_current`), so it needs the program as it was
    published, and the only copy that outlived the process is the one inside the
    record. A caller-supplied program would be a second carrier of that fact, and
    a WRONG one the day the caller edits before replanning.
    """
    data = record.to_dict()["plan_evidence"]
    return {"ir_version": data["ir_version"], "intent": data["intent"],
            "lineage": data["lineage"], "ops": [row["payload"] for row in data["ops"]]}


def previous_from_stored_publication(store: Any, archive_digest: str) -> dict:
    """The ledger of one earlier publication, from a REAL store and nothing else.

    Returns `{"program": …, "identity": …}` — exactly what `plan_republish`
    accepts as `previous`.

    🔴 WHY THIS EXISTS BESIDE `project_republish.previous_from_store`. That
    reader looks for a retained `identity_assessment` blob INSIDE a stored
    receipt row, and no product writer puts one there: a stored CREATE receipt's
    fields are closed by `create_publication.validate_create_receipt_claims` to
    exactly {schema, archive_digest, native_receipt, claims, receipt_digest}.
    Measured 13.09.2026 on a real SQLite store, after a real reservation and a
    real bound receipt: `previous_publication_unreadable` — «retains 1 receipt(s)
    but no identity assessment». It is green only against a fake store.

    So this reader does not ask for a blob nobody writes. It RE-DERIVES the
    assessment from what the store does retain, with the product's own
    `retained_create_identity_claims` — the same call `project_create_store`
    already makes at line 435 when auditing staged links. One carrier (the
    native receipt), one deriver, no new schema and no new table.
    """
    from kir.create_publication import retained_create_identity_claims

    if not isinstance(archive_digest, str) or len(archive_digest) != 64:
        raise RepublishArchiveError("previous_publication_unreadable",
                                    "адрес публикации — 64 шестнадцатеричных знака")
    publication = store.get_create_publication(archive_digest)
    receipts = store.get_create_receipts(archive_digest).to_dict()["receipts"]
    if not receipts:
        raise RepublishArchiveError(
            "publication_has_no_receipt",
            f"публикация {archive_digest[:12]} зарезервирована, но ни одной "
            "квитанции не удержала: что стало с её выходами — неизвестно, и "
            "считать их несуществующими значит построить их заново")
    project = store.get(publication.source_revision)
    identity = retained_create_identity_claims(project, publication.record,
                                               _terminal_receipt(receipts))
    return {"program": program_as_published(publication.record), "identity": identity}


__all__ = ["RepublishArchiveError", "check_identities", "previous_from_stored_publication",
           "program_as_published", "saved_record_from_receipt"]
