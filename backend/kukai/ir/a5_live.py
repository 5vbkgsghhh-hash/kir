"""Live A5 document guard, cleanup protocol, and durable recovery adapter.

This module owns the write-bearing boundary between the pure idempotence
orchestrator and one live Revit document.  It deliberately does not expose a
tool handler or choose request scope; ``kukai.ir.serving`` retains dispatch,
while ``kukai.ir.a5_contract`` owns request identity.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import replace
from typing import Any, Mapping, Optional, Sequence

from kukai.ir.a5_recovery import (
    A5Journal,
    A5JournalError,
    A5Lease,
    A5Phase,
    phase_at_least,
    stamp_scope as _a5_stamp_scope,
)
from kukai.ir.bridge_result import extract_error as _extract_error
from kukai.ir.contracts import (
    CleanupReceipt,
    CommitReceipt,
    DocumentFingerprint,
    IdempotenceMetrics,
    RunId,
    SnapshotManifest,
)
from kukai.ir.document_guard import (
    DOCUMENT_PROBE_CS as _DOCUMENT_PROBE_CS,
    bind_read_to_document as _bind_read_to_document,
    document_mismatch_expr as _document_mismatch_expr,
    document_refusal_cs as _document_refusal_cs,
)

# Backward-compatible name for diagnostics/tests that only care about title.
_TITLE_PROBE_CS = _DOCUMENT_PROBE_CS

# A5 orphan cleanup is generated for one exact run-owned prefix.  There is no
# global ``kir:`` mode: unrelated KIR output and a prior keep-run are out of
# scope.  Its proof payload is explicitly ``a5-stamp-sweep/3``; any generated
# C# wire-shape change must bump that version and its parser gate together.
#
# v3 (task #69): TYPES ARE FOUND, NEVER DELETED.  ``create_type`` stamps its
# duplicated FamilySymbol on ``ALL_MODEL_TYPE_COMMENTS`` (measured:
# authoring._emit_create_type -> _stamp_type_block; a compiled program's
# emission puts the stamp on the FamilySymbol itself), and
# ``WhereElementIsNotElementType()`` below structurally never enumerates it —
# the instance census cannot see a type no matter what its stamp says.  That
# gap gets its OWN separate census (``WhereElementIsElementType()`` +
# ``ALL_MODEL_TYPE_COMMENTS``) so a caller sees the type and its name, but it
# is deliberately never a delete candidate: Element.Delete() on a type deletes
# every instance of that type, including ones THIS PROGRAM DID NOT CREATE —
# consenting to "undo what I built" is not consent to delete someone else's
# elements, and no amount of stamp bookkeeping on our side changes who else
# is using that type.  See ``kir_idempotence.py``/task #69 notes for the
# decision record.
_A5_SWEEP_SCHEMA_VERSION = "a5-stamp-sweep/3"
_ORPHAN_SWEEP_TEMPLATE = r"""
__DOC_GUARD_PREVIEW__
string __prefix = __PREFIX__;
bool __delete = __DELETE__;
var __found = new List<ElementId>();
foreach (var __e in new FilteredElementCollector(doc).WhereElementIsNotElementType().Cast<Element>())
{
    try
    {
        var __p = __e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
        if (__p != null)
        {
            var __v = __p.AsString();
            if (__v != null && __v.StartsWith(__prefix, StringComparison.Ordinal)) __found.Add(__e.Id);
        }
    }
    catch { }
}
var __typesFound = new List<ElementId>();
var __typesFoundNames = new List<string>();
foreach (var __ty in new FilteredElementCollector(doc).WhereElementIsElementType().Cast<Element>())
{
    try
    {
        var __tp = __ty.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS);
        if (__tp != null)
        {
            var __tv = __tp.AsString();
            if (__tv != null && __tv.StartsWith(__prefix, StringComparison.Ordinal))
            {
                __typesFound.Add(__ty.Id);
                string __tn = "";
                try { __tn = __ty.Name ?? ""; } catch { }
                __typesFoundNames.Add(__tn);
            }
        }
    }
    catch { }
}
int __n = 0;
var __deleted = new List<string>();
string __commitStatus = "NotStarted";
if (__delete && __found.Count > 0)
{
    using (Transaction __t = new Transaction(doc, "KIR run cleanup"))
    {
        var __startStatus = __t.Start();
        if (__startStatus != TransactionStatus.Started)
            return new Dictionary<string, object> {
                {"schema_version", __SCHEMA_VERSION__},
                {"preview", false}, {"found", __found.Count}, {"deleted", 0},
                {"remaining", __found.Count}, {"commit_status", __startStatus.ToString()}
            };
        __DOC_GUARD_TXN__
        foreach (var __id in __found)
        {
            try
            {
                if (doc.GetElement(__id) != null)
                {
                    doc.Delete(__id); __n++; __deleted.Add(__id.ToString());
                }
            }
            catch { }
        }
        __commitStatus = __t.Commit().ToString();
    }
}
var __remaining = new List<string>();
foreach (var __e in new FilteredElementCollector(doc).WhereElementIsNotElementType().Cast<Element>())
{
    try
    {
        var __p = __e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
        var __v = __p == null ? null : __p.AsString();
        if (__v != null && __v.StartsWith(__prefix, StringComparison.Ordinal))
            __remaining.Add(__e.Id.ToString());
    }
    catch { }
}
return new Dictionary<string, object> {
    {"schema_version", __SCHEMA_VERSION__},
    {"preview", __PREVIEW__},
    {"prefix", __prefix},
    {"found", __found.Count},
    {"found_ids", __found.Select(__id => __id.ToString()).ToList()},
    {"deleted", __n},
    {"deleted_ids", __deleted},
    {"remaining", __remaining.Count},
    {"remaining_ids", __remaining},
    {"types_found", __typesFound.Count},
    {"types_found_ids", __typesFound.Select(__id => __id.ToString()).ToList()},
    {"types_found_names", __typesFoundNames},
    {"witnesses_complete", true},
    {"commit_status", __commitStatus}
};
""".strip()


def _orphan_sweep_cs(
    stamp_prefix: str,
    *,
    delete: bool,
    document_fingerprint: DocumentFingerprint | None = None,
) -> str:
    """Emit the C# ownership sweep for one exact, closed stamp prefix.

    Exactly two prefix grammars are accepted (``fullmatch`` — no shorter or
    longer variant, and there is no open/global ``kir:`` mode):

    * ``kir:a5:<doc12>:<run16>:`` — one A5 run, scoped to both the document
      stamp and the run id (task #69's original form).
    * ``kir:<hash8>:`` — task #69's addition: every element any REGULAR
      program (chat authoring or ``/admin/kir/run``) with that exact content
      hash ever stamped. ``hash8`` is ``authoring.program_hash`` — a hash of
      the grounded op list, i.e. of WHAT the program built, not of a run
      instance and not of a document. Two consequences a caller of this
      sweep must not be surprised by:

      1. Running the identical program twice against the same document
         yields the identical prefix, so sweeping it removes elements from
         BOTH runs — "undo everything this program ever built", not "undo
         only the last run". Defensible, but the opposite of what a caller
         typically expects from "undo", so it is written here where the
         acceptance check lives rather than left implicit.
      2. The prefix itself carries no document identity (unlike the A5
         form, which embeds ``doc12``). The only thing stopping this sweep
         from reaching a same-hash program built in a DIFFERENT document is
         the live ``document_fingerprint`` guard below
         (``_document_refusal_cs``) — call this without that argument and
         the prefix alone will not protect a sibling document.

    Selection in the generated C# is a plain ``StartsWith`` on the prefix
    string (``_ORPHAN_SWEEP_TEMPLATE``); it is indifferent to which of the
    two grammars produced it. All the safety lives in this gate.
    """
    import re as _re
    if not isinstance(delete, bool):
        raise ValueError("delete must be a bool")
    if not (_re.fullmatch(r"kir:a5:[0-9a-f]{12}:[0-9a-f]{16}:", stamp_prefix)
            or _re.fullmatch(r"kir:[0-9a-f]{8}:", stamp_prefix)):
        raise ValueError(
            "invalid stamp prefix: must be exactly one of "
            "'kir:a5:<12 hex digits>:<16 hex digits>:' (one A5 run) or "
            "'kir:<8 hex digits>:' (one program's content hash) — got "
            f"{stamp_prefix!r}")
    preview_guard = ("" if document_fingerprint is None else
                     _document_refusal_cs(document_fingerprint).strip())
    transaction_guard = ("" if document_fingerprint is None else
                         _document_refusal_cs(
                             document_fingerprint,
                             rollback="__t.RollBack(); ").strip())
    return (_ORPHAN_SWEEP_TEMPLATE
            .replace("__SCHEMA_VERSION__", json.dumps(
                _A5_SWEEP_SCHEMA_VERSION, ensure_ascii=True))
            .replace("__PREFIX__", json.dumps(stamp_prefix, ensure_ascii=True), 1)
            .replace("__DELETE__", "true" if delete else "false", 1)
            .replace("__PREVIEW__", "false" if delete else "true", 1)
            .replace("__DOC_GUARD_PREVIEW__", preview_guard, 1)
            .replace("__DOC_GUARD_TXN__", transaction_guard, 1))


def _new_a5_stamp_scope(doc_stamp: str) -> tuple[str, str]:
    """Return ``(compiler_scope, full_prefix)`` for one live A5 run."""

    return _a5_stamp_scope(doc_stamp, RunId.new())


_active_a5_runs: set[str] = set()
_active_a5_runs_guard = threading.Lock()


def _claim_a5_document(doc_stamp: str) -> bool:
    """Process-wide single-flight claim, safe across asyncio event loops."""

    with _active_a5_runs_guard:
        if doc_stamp in _active_a5_runs:
            return False
        _active_a5_runs.add(doc_stamp)
        return True


def _release_a5_document(doc_stamp: str) -> None:
    with _active_a5_runs_guard:
        _active_a5_runs.discard(doc_stamp)


def _a5_payload(envelope: Any) -> Optional[dict[str, Any]]:
    """Unwrap one serving envelope without guessing non-object payloads."""

    current = envelope
    for _ in range(3):
        if not isinstance(current, dict):
            return None
        nested = current.get("result")
        if not isinstance(nested, dict):
            return current
        current = nested
    return current if isinstance(current, dict) else None


def _op_results(exec_res: Any) -> dict[str, Any]:
    """Пооперационная выдача чанка (``__results``), или пусто.

    Разворот ОДНОУРОВНЕВЫЙ и намеренно повторяет ``collect_created_ids``:
    отказы обязаны читаться из ТОЙ ЖЕ карты, что и id, иначе два читателя
    одного конверта разойдутся в том, какие опы вообще существуют, и закон
    переписи станет проверять свою же ошибку разбора.  ``_a5_payload`` здесь
    не годится — он спускается до трёх уровней и на конверте
    ``{"ok":.., "result":{op_id:..}}`` вернул бы саму карту опов, после чего
    второй ``.get("result")`` дал бы пусто.
    """

    if not isinstance(exec_res, Mapping):
        return {}
    payload = exec_res.get("result", exec_res)
    return dict(payload) if isinstance(payload, Mapping) else {}


def collect_op_refusals(
    exec_res: Any,
    program: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Пооперационные отказы — из того же ``result``, откуда берутся id.

    В ``isolation="per_op"`` эмиссия кладёт отказ рядом с успехами:
    ``__results[oid] = {"refused": <текст>, "refused_op_id": oid}``.  До /3
    его никто не читал: ``collect_created_ids`` пропускает строку без ``id``,
    а квитанция хранила только ``element_ids`` — и 113 отказавших линий
    разрезки (пересборка №11) остались без единого слова о причине.

    По ``op_id`` дотягивается ИМЯ опа и то, КАК он адресовал цель: строка
    «G отказал» читателю бесполезна, ему нужно «create_curtain_grid_line на
    носителе e8152799».  Текст причины НЕ РЕЖЕТСЯ — именно он назвал виновный
    элемент в разборе чанка 9.
    """

    by_id = {
        str(op.get("id")): op
        for op in (program.get("ops") or ())
        if isinstance(op, Mapping) and op.get("id") is not None
    }
    rows: list[dict[str, Any]] = []
    for op_id, row in _op_results(exec_res).items():
        if not (isinstance(row, Mapping) and row.get("refused")):
            continue
        op = by_id.get(str(op_id)) or {}
        intent = op.get("host") or op.get("target") or op.get("type")
        rows.append({
            "op_id": str(op_id),
            "op_name": op.get("op"),
            "intent": intent if isinstance(intent, (str, int, dict)) else None,
            "reason": str(row.get("refused")),
        })
    return tuple(sorted(rows, key=lambda item: item["op_id"]))


def count_ops_without_element(exec_res: Any) -> int:
    """Опы, закрывшиеся БЕЗ рождения элемента ПО СЕМАНТИКЕ.

    Только явное ``created: false`` (смена типа панели на месте).  Строка без
    ``id``, без ``created:false`` и без ``refused`` сюда НЕ идёт намеренно:
    это неизвестность, и закон переписи обязан её поймать, а не спрятать —
    ровно тот класс «молча не создано», ради которого закон и заводится.
    """

    return sum(
        1 for row in _op_results(exec_res).values()
        if isinstance(row, Mapping)
        and row.get("created") is False
        and not row.get("refused")
    )


def _a5_sweep_payload(
    envelope: Any,
    *,
    stamp_prefix: str,
) -> dict[str, Any]:
    payload = _a5_payload(envelope)
    if (payload is None or payload.get("schema_version")
            != _A5_SWEEP_SCHEMA_VERSION):
        raise A5JournalError(
            f"A5 stamp census has no {_A5_SWEEP_SCHEMA_VERSION} proof payload")
    if payload.get("prefix") != stamp_prefix:
        raise A5JournalError("A5 stamp census is bound to another prefix")
    for count_key, ids_key in (
        ("found", "found_ids"), ("deleted", "deleted_ids"),
        ("remaining", "remaining_ids"),
        # v3 (task #69): types are CENSUSED like any other witness set (same
        # id-uniqueness contract) — they are simply never a member of
        # __deleted, because the emitter never attempts to delete them.
        ("types_found", "types_found_ids"),
    ):
        count = payload.get(count_key)
        ids = payload.get(ids_key, [])
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise A5JournalError(f"A5 stamp census has invalid {count_key}")
        if (not isinstance(ids, list)
                or any(not isinstance(item, str) or not item for item in ids)
                or len(ids) != count or len(set(ids)) != len(ids)):
            raise A5JournalError(
                f"A5 stamp census has incomplete {ids_key} witnesses")
    # Names are cosmetic, shape-checked only: Revit allows the same type
    # name to repeat across different families, so — unlike ids — they are
    # never treated as a uniqueness witness.
    names = payload.get("types_found_names")
    if (not isinstance(names, list)
            or any(not isinstance(item, str) for item in names)
            or len(names) != payload["types_found"]):
        raise A5JournalError(
            "A5 stamp census has incomplete types_found_names")
    if payload.get("witnesses_complete") is not True:
        raise A5JournalError("A5 stamp census witnesses are incomplete")
    return payload


def build_sweep_payload(
    *,
    prefix: str,
    found_ids: Sequence[str] = (),
    deleted_ids: Sequence[str] = (),
    remaining_ids: Sequence[str] = (),
    types_found_ids: Sequence[str] = (),
    types_found_names: Optional[Sequence[str]] = None,
    preview: bool = True,
    commit_status: str = "NotStarted",
    witnesses_complete: bool = True,
    schema_version: Optional[str] = None,
    wrap_result: bool = False,
    omit: Sequence[str] = (),
    **overrides: Any,
) -> dict[str, Any]:
    """The ONE builder for the ``_ORPHAN_SWEEP_TEMPLATE`` wire shape.

    Three same-day incidents (task #69) were the same disease: tests and
    mocks hand-typed this envelope in at least four places
    (``test_rebuilt_phase_coverage.py``, ``test_serving_idempotence.py``
    x3, ``test_audit_fixes.py`` x2), and every copy described what the
    OTHER side — the C# sweep — is supposed to produce, rather than
    importing that contract from here. Two hardcoded the schema-version
    literal (stale the moment it bumps); two silently dropped the v3
    ``types_found*`` triple. Seventh law: a two-component contract gets
    checked against a fixture, not re-typed at each call site — this
    function IS that fixture.

    Counts are DERIVED from the id lists (``found=len(found_ids)`` etc.), so
    a caller cannot produce a mismatched count/id-list pair the way an
    ad-hoc dict literal could — that exact mismatch is what
    ``_a5_sweep_payload`` exists to catch, and a builder able to produce it
    would defeat the point. ``schema_version`` defaults to
    ``_A5_SWEEP_SCHEMA_VERSION`` read live from this module, never a string
    literal a future schema bump would leave stale. ``types_found_names``
    defaults to one empty string per id when not given.

    ``omit``/``**overrides`` exist for the DISPROVING side of a fixture: a
    payload that ``_a5_sweep_payload`` must REJECT (missing field, wrong
    type, foreign prefix) is built by omitting/overriding from this same
    source of truth, not by hand-writing a second, independently-wrong
    dict.  ``wrap_result=True`` returns the ``{"ok": True, "result": ...}``
    bridge envelope shape instead of the flat payload — both shapes are
    real: the flat one is what a completely unwrapped bridge result looks
    like, the wrapped one is what ``_a5_payload``'s nesting-unwrap exists
    to see through (measured live in ``test_census_unwraps_a_nested_bridge_envelope``).
    """
    names = (list(types_found_names) if types_found_names is not None
              else ["" for _ in types_found_ids])
    payload: dict[str, Any] = {
        "schema_version": schema_version or _A5_SWEEP_SCHEMA_VERSION,
        "preview": preview,
        "prefix": prefix,
        "found": len(found_ids), "found_ids": list(found_ids),
        "deleted": len(deleted_ids), "deleted_ids": list(deleted_ids),
        "remaining": len(remaining_ids),
        "remaining_ids": list(remaining_ids),
        "types_found": len(types_found_ids),
        "types_found_ids": list(types_found_ids),
        "types_found_names": names,
        "witnesses_complete": witnesses_complete,
        "commit_status": commit_status,
    }
    payload.update(overrides)
    for key in omit:
        payload.pop(key, None)
    return {"ok": True, "result": payload} if wrap_result else payload


def _cleanup_receipt_from_sweep(
    payload: Mapping[str, Any],
    *,
    run_id: RunId,
    stamp_prefix: str,
) -> CleanupReceipt:
    found_ids = tuple(sorted(payload["found_ids"]))
    deleted_ids = tuple(sorted(payload["deleted_ids"]))
    remaining_ids = tuple(sorted(payload["remaining_ids"]))
    found = int(payload["found"])
    deleted = int(payload["deleted"])
    remaining = int(payload["remaining"])
    return CleanupReceipt(
        run_id=run_id,
        stamp_prefix=stamp_prefix,
        found_count=found,
        deleted_count=deleted,
        remaining_count=remaining,
        found_ids=found_ids,
        deleted_ids=deleted_ids,
        remaining_ids=remaining_ids,
        commit_status=str(payload.get("commit_status") or "NotStarted"),
        reconciled=(remaining == 0 and found == deleted
                    and set(found_ids) == set(deleted_ids)),
        witnesses_complete=True,
    )


def _cleanup_covers(
    created: Sequence[str],
    delete_receipts: Sequence[CommitReceipt],
    final_preview: Mapping[str, Any],
) -> bool:
    """Покрыт ли каждый созданный элемент — удалением ЛИБО отсутствием.

    Поштучный витнес удаления ложно-отрицателен на КАСКАДЕ: ячейка витража
    уходит из модели вместе со своим носителем, и когда очередь доходит до
    её id, удалять уже нечего. ЗАМЕР 28.07 (прогоны №4 и №5): ровно 12 из
    1236 созданных элементов возвращали «элемент не найден», при том что
    финальная перепись штампа обоих прогонов показывала ноль остатков.

    Строгость сохранена и даже уточнена: ВЫЖИВШИЙ созданный элемент — по-
    прежнему провал уборки, потому что перепись его видит. Не покрывается
    только то, чего в модели нет и что при этом не было удалено нами; такое
    состояние и есть цель уборки, а не её нарушение.
    """

    deleted = {
        item for receipt in delete_receipts for item in receipt.element_ids}
    survivors = {str(item) for item in final_preview.get("found_ids", ())}
    unaccounted = (set(str(item) for item in created) - deleted) & survivors
    return not unaccounted


def _receipt_from_journal(
    raw: Mapping[str, Any], run_id: RunId,
) -> Optional[CommitReceipt]:
    """Квитанция эффекта, включая ПЕРЕХОДНУЮ форму отказа.

    С 568349f6 по эту правку отказ писался самодельным словарём
    ``{outcome, program_id, bridge_detail}`` — без схемы и без операции.
    Журнал прогона №4 (v9) такой записью и обладает, и читать его как «этой
    программы вообще не было» значило бы объявить непокрытым план, который
    на самом деле закрыт: Revit ответил, транзакция откатена, элементов нет.

    Форма однозначна (есть outcome и program_id, нет витнесов), поэтому она
    поднимается в тот же CommitReceipt. Всё прочее — уборочные и
    reconciliation-квитанции — по-прежнему не квитанции коммита.
    """

    if not isinstance(raw, Mapping):
        return None
    try:
        return CommitReceipt.from_dict(raw)
    except Exception:  # cleanup/reconciliation receipts are different
        pass
    if raw.get("outcome") != "refused_without_commit":
        return None
    program_id = raw.get("program_id")
    if not isinstance(program_id, str):
        return None
    try:
        return CommitReceipt(
            run_id=run_id, operation="rebuild", element_ids=(),
            bridge_error=True, commit_confirmed=False,
            commit_status="RolledBack", program_id=program_id)
    except Exception:  # noqa: BLE001 — чужая форма остаётся чужой
        return None


class _A5Recovery:
    """Bind the pure idempotence orchestrator to one durable A5 journal."""

    def __init__(
        self,
        journal: A5Journal,
        lease: A5Lease,
        *,
        stamp_prefix: str,
        preview_runner,
        sweep_runner,
        revision_runner,
    ) -> None:
        self.journal = journal
        self.lease = lease
        self.stamp_prefix = stamp_prefix
        self.preview_runner = preview_runner
        self.sweep_runner = sweep_runner
        self.revision_runner = revision_runner
        self.completed_during_recovery = False
        self._planned_program_ids: tuple[str, ...] | None = None

    @property
    def resume_created_ids(self) -> tuple[str, ...]:
        if phase_at_least(self.journal.state.phase, A5Phase.REBUILT):
            proof = self.journal.state.proofs[A5Phase.REBUILT]
            return tuple(str(item) for item in proof["created_ids"])
        return tuple(sorted({
            element_id
            for _effect_id, receipt in self._current_rebuild_receipts()
            for element_id in receipt.element_ids
        }, key=lambda value: (
            int(value) if value.isdigit() else 0, value)))

    def _current_rebuild_receipts(
        self,
    ) -> list[tuple[str, CommitReceipt]]:
        receipts: list[tuple[str, CommitReceipt]] = []
        for effect_id in sorted(self.journal.state.effect_receipts):
            if self.journal.state.effect_epochs.get(effect_id) \
                    != self.journal.state.rebuild_epoch:
                continue
            raw = self.journal.state.effect_receipts[effect_id]
            receipt = _receipt_from_journal(raw, self.journal.state.run_id)
            if receipt is None:
                continue
            # РЕШЁННЫЕ исходы, а не только коммиты: отказ закрывает свою
            # программу так же надёжно. Неизвестность (timeout) сюда не
            # попадает — её эффект вообще не финишируется.
            if receipt.operation == "rebuild" and receipt.decided:
                receipts.append((effect_id, receipt))
        return receipts

    def _decided_receipts(self, operation: str) -> list[CommitReceipt]:
        """Квитанции с ИЗВЕСТНЫМ исходом — подтверждённые и отказные."""

        return [
            receipt for receipt in self._receipts(operation)
            if receipt.decided
        ]

    def _receipts(self, operation: str) -> list[CommitReceipt]:
        receipts: list[CommitReceipt] = []
        for effect_id in sorted(self.journal.state.effect_receipts):
            if self.journal.state.effect_epochs.get(effect_id) \
                    != self.journal.state.rebuild_epoch:
                continue
            raw = self.journal.state.effect_receipts[effect_id]
            receipt = _receipt_from_journal(raw, self.journal.state.run_id)
            if receipt is None:
                continue
            if receipt.operation == operation:
                receipts.append(receipt)
        return receipts

    def _confirmed_receipts(self, operation: str) -> list[CommitReceipt]:
        return [
            receipt for receipt in self._receipts(operation)
            if receipt.confirmed
        ]

    @property
    def _snapshot_revision(self) -> str:
        manifest = SnapshotManifest.from_dict(
            self.journal.state.proofs[
                A5Phase.SNAPSHOT_VERIFIED]["snapshot_manifest"])
        return manifest.revision_proof.fingerprint

    @property
    def _rebuilt_revision(self) -> str:
        value = self.journal.state.proofs[A5Phase.REBUILT].get(
            "document_revision")
        if not isinstance(value, str) or not value:
            raise A5JournalError("Rebuilt state has no document revision")
        return value

    @property
    def expected_document_revision(self) -> str:
        """Exact revision the active model must have at the resume boundary."""

        if phase_at_least(self.journal.state.phase, A5Phase.REBUILT):
            if self.journal.state.phase is A5Phase.COMPLETED:
                value = self.journal.state.proofs[
                    A5Phase.COMPLETED]["document_revision"]
                if isinstance(value, str) and value:
                    return value
            return self._rebuilt_revision
        receipts = self._current_rebuild_receipts()
        if receipts:
            revision = receipts[-1][1].document_revision
            if not isinstance(revision, str) or not revision:
                raise A5JournalError(
                    "partial rebuild receipt has no document revision")
            return revision
        return self._snapshot_revision

    async def _require_revision(self, expected: str) -> str:
        current = await self.revision_runner()
        if current != expected:
            raise A5JournalError(
                "active document revision differs from confirmed A5 state")
        return expected

    async def _preview(self) -> dict[str, Any]:
        await self.lease.ensure_held()
        envelope = await self.preview_runner()
        if _extract_error(envelope) is not None:
            raise A5JournalError("A5 stamp preview bridge call failed")
        return _a5_sweep_payload(envelope, stamp_prefix=self.stamp_prefix)

    async def _reset_partial_rebuild_epoch(self) -> None:
        """Delete only this run's stamped delta and restart from the snapshot."""

        preview = await self._preview()
        if preview["found"]:
            envelope = await self.sweep_runner()
            if not isinstance(envelope, Mapping) or envelope.get("ok") is not True:
                raise A5JournalError(
                    "partial rebuild reset cleanup is unconfirmed")
            payload = _a5_sweep_payload(
                envelope, stamp_prefix=self.stamp_prefix)
            receipt = _cleanup_receipt_from_sweep(
                payload,
                run_id=self.journal.state.run_id,
                stamp_prefix=self.stamp_prefix,
            )
            if not receipt.confirmed:
                raise A5JournalError(
                    "partial rebuild reset left stamped elements")
        else:
            receipt = CleanupReceipt(
                run_id=self.journal.state.run_id,
                stamp_prefix=self.stamp_prefix,
                found_count=0, deleted_count=0, remaining_count=0,
                found_ids=(), deleted_ids=(), remaining_ids=(),
                commit_status="NotStarted", reconciled=True,
                witnesses_complete=True,
            )
        final_preview = await self._preview()
        if final_preview["found"] != 0:
            raise A5JournalError(
                "partial rebuild reset has stamped survivors")
        await self._require_revision(self._snapshot_revision)
        self.journal.start_rebuild_epoch(receipt)

    async def prepare_rebuild_plan(
        self,
        program_ids: Sequence[str],
    ) -> Mapping[str, Sequence[str]]:
        """Return confirmed prefix receipts for this exact deterministic plan."""

        normalized = tuple(program_ids)
        if (len(set(normalized)) != len(normalized)
                or any(re.fullmatch(r"[0-9a-f]{64}", item) is None
                       for item in normalized)):
            raise A5JournalError("A5 rebuild plan ids are invalid")
        self._planned_program_ids = normalized

        if phase_at_least(self.journal.state.phase, A5Phase.REBUILT):
            proof_ids = self.journal.state.proofs[
                A5Phase.REBUILT].get("program_ids")
            if proof_ids != list(normalized):
                raise A5JournalError(
                    "confirmed Rebuilt phase belongs to another/legacy plan")

        receipts = self._current_rebuild_receipts()
        receipt_programs = tuple(
            receipt.program_id for _effect_id, receipt in receipts)
        if receipt_programs != normalized[:len(receipt_programs)]:
            if self.journal.state.phase is not A5Phase.SNAPSHOT_VERIFIED:
                raise A5JournalError(
                    "confirmed A5 phases have a non-prefix rebuild plan")
            await self._reset_partial_rebuild_epoch()
            return {}

        return {
            str(receipt.program_id): tuple(receipt.element_ids)
            for _effect_id, receipt in receipts
        }

    async def recover_pending_effects(self) -> None:
        """Reconcile unknown write outcomes before replaying confirmed state."""

        pending = tuple(self.journal.state.pending_effects)
        if pending:
            preview = await self._preview()
            if preview["found"]:
                envelope = await self.sweep_runner()
                if not isinstance(envelope, Mapping) or envelope.get("ok") is not True:
                    raise A5JournalError("unknown A5 effect cleanup is unconfirmed")
                raw_receipt = envelope.get("cleanup_receipt")
                receipt = CleanupReceipt.from_dict(raw_receipt)
                if not receipt.confirmed:
                    raise A5JournalError("unknown A5 effect left stamped elements")
            else:
                receipt = CleanupReceipt(
                    run_id=self.journal.state.run_id,
                    stamp_prefix=self.stamp_prefix,
                    found_count=0, deleted_count=0, remaining_count=0,
                    found_ids=(), deleted_ids=(), remaining_ids=(),
                    commit_status="NotStarted", reconciled=True,
                    witnesses_complete=True)
            for effect_id in pending:
                if effect_id in self.journal.state.pending_effects:
                    self.journal.finish_effect(effect_id, {
                        "outcome": "reconciled_after_unknown_commit",
                        "cleanup_receipt": receipt.to_dict(),
                    })
            if self.journal.state.phase is A5Phase.SNAPSHOT_VERIFIED:
                self.journal.start_rebuild_epoch(receipt)

        # A kill after a chunk receipt was fsynced is the normal resumable
        # boundary.  Prove that every stamped element is covered by those
        # receipts and that the active document still has the exact last
        # post-chunk revision.  Legacy/non-authoritative receipts are safely
        # swept and start a new epoch rather than being guessed.
        if self.journal.state.phase is A5Phase.SNAPSHOT_VERIFIED:
            receipts = self._current_rebuild_receipts()
            if receipts:
                authoritative = all(
                    receipt.resumable_rebuild
                    and self.journal.state.effect_definitions.get(
                        effect_id, {}).get("program_id") == receipt.program_id
                    for effect_id, receipt in receipts
                )
                if not authoritative:
                    await self._reset_partial_rebuild_epoch()
                else:
                    witnessed = {
                        element_id
                        for _effect_id, receipt in receipts
                        for element_id in receipt.element_ids
                    }
                    if sum(len(receipt.element_ids)
                           for _effect_id, receipt in receipts) \
                            != len(witnessed):
                        raise A5JournalError(
                            "partial rebuild receipts duplicate ElementIds")
                    preview = await self._preview()
                    if set(preview["found_ids"]) != witnessed:
                        await self._reset_partial_rebuild_epoch()
                    else:
                        await self._require_revision(
                            str(receipts[-1][1].document_revision))

        # A process may die after all cleanup receipts were fsynced but before
        # the terminal transition.  At CleanupPreviewed, finish cleanup only;
        # never rebuild or recompute a comparison already proven durable.
        if self.journal.state.phase is A5Phase.CLEANUP_PREVIEWED:
            proof = self.journal.state.proofs[A5Phase.CLEANUP_PREVIEWED]
            expected = tuple(str(item) for item in proof["element_ids"])
            if proof.get("retain") is True:
                preview = await self._preview()
                if set(preview["found_ids"]) != set(expected):
                    raise A5JournalError("retained A5 elements changed during restart")
                revision = await self._require_revision(self._rebuilt_revision)
                self.journal.transition(A5Phase.COMPLETED, {
                    "retained": True, "retained_ids": list(expected),
                    "document_revision": revision})
                self.completed_during_recovery = True
                return
            preview = await self._preview()
            if preview["found"]:
                envelope = await self.sweep_runner()
                if not isinstance(envelope, Mapping) or envelope.get("ok") is not True:
                    raise A5JournalError("restart cleanup sweep is unconfirmed")
            final_preview = await self._preview()
            if final_preview["found"] != 0:
                raise A5JournalError("restart cleanup left stamped elements")
            revision = await self._require_revision(self._snapshot_revision)
            receipt = CleanupReceipt(
                run_id=self.journal.state.run_id,
                stamp_prefix=self.stamp_prefix,
                found_count=len(expected), deleted_count=len(expected),
                remaining_count=0,
                found_ids=tuple(sorted(expected)),
                deleted_ids=tuple(sorted(expected)), remaining_ids=(),
                commit_status="Committed" if expected else "NotStarted",
                reconciled=True, witnesses_complete=True)
            self.journal.transition(
                A5Phase.COMPLETED,
                {"retained": False, "cleanup_receipt": receipt.to_dict(),
                 "document_revision": revision})
            self.completed_during_recovery = True

    async def after_rebuilt(self, created_ids) -> None:
        created = tuple(sorted({str(item) for item in created_ids}))
        if not phase_at_least(self.journal.state.phase, A5Phase.REBUILT):
            # ПОКРЫТИЕ ПЛАНА — по множеству программ с сохранением
            # строгости: у каждой программы ровно один ИЗВЕСТНЫЙ исход.
            # Коммит и отказ покрывают одинаково; неизвестность не
            # покрывает ничего и по-прежнему валит переход.
            receipts = self._decided_receipts("rebuild")
            receipt_programs = [receipt.program_id for receipt in receipts]
            planned = self._planned_program_ids
            if (planned is None
                    or len(receipt_programs) != len(set(receipt_programs))
                    or set(receipt_programs) != set(planned)):
                raise A5JournalError(
                    "rebuild receipts do not cover the complete plan")
            # Порядок квитанций в доказательстве — план, а не порядок
            # эффектов: доказательство обязано читаться против плана.
            by_program = {
                receipt.program_id: receipt for receipt in receipts}
            receipts = [by_program[program_id] for program_id in planned]
            witnessed = {
                item for receipt in receipts
                if receipt.confirmed for item in receipt.element_ids}
            if set(created) != witnessed:
                raise A5JournalError(
                    "rebuild ids disagree with durable commit receipts")
            document_revision = await self.revision_runner()
            if not isinstance(document_revision, str) or not document_revision:
                raise A5JournalError(
                    "post-rebuild document revision is unavailable")
            proof_receipts = receipts
            if not any(receipt.confirmed for receipt in receipts):
                # A plan made only of witnessed rollbacks did execute to a
                # closed state, but it wrote nothing.  Bind that negative
                # outcome to the unchanged source revision; otherwise an
                # external document edit could masquerade as a valid 0% run.
                if document_revision != self._snapshot_revision:
                    raise A5JournalError(
                        "all-refused A5 plan changed the source revision")
                proof_receipts = [
                    replace(receipt, document_revision=document_revision)
                    for receipt in receipts
                ]
            self.journal.transition(A5Phase.REBUILT, {
                "commit_receipts": [
                    receipt.to_dict() for receipt in proof_receipts],
                "program_ids": list(self._planned_program_ids),
                "created_ids": list(created),
                "document_revision": document_revision,
            })
        else:
            durable = set(self.resume_created_ids)
            if durable != set(created):
                raise A5JournalError("resume created ids changed")
        if not phase_at_least(self.journal.state.phase, A5Phase.RECONCILED):
            preview = await self._preview()
            if set(preview["found_ids"]) != set(created):
                raise A5JournalError(
                    "run-prefix reconciliation disagrees with commit receipts")
            revision = await self._require_revision(self._rebuilt_revision)
            self.journal.transition(A5Phase.RECONCILED, {
                "stamp_prefix": self.stamp_prefix,
                "element_count": len(created),
                "element_ids": list(created),
                "witnesses_complete": True,
                "document_revision": revision,
            })

    async def after_compared(self, report) -> None:
        metrics = IdempotenceMetrics.from_dict(report)
        revision = await self._require_revision(self._rebuilt_revision)
        proof = {
            "metrics": metrics.to_dict(), "report": dict(report),
            "document_revision": revision}
        if phase_at_least(self.journal.state.phase, A5Phase.COMPARED):
            if self.journal.state.proofs[A5Phase.COMPARED] != proof:
                raise A5JournalError("replayed A5 comparison changed")
            return
        self.journal.transition(A5Phase.COMPARED, proof)

    async def before_cleanup(self, created_ids, *, retain: bool) -> None:
        if phase_at_least(
                self.journal.state.phase, A5Phase.CLEANUP_PREVIEWED):
            return
        preview = await self._preview()
        created = tuple(sorted({str(item) for item in created_ids}))
        if set(preview["found_ids"]) != set(created):
            raise A5JournalError("cleanup preview disagrees with run ownership")
        revision = await self._require_revision(self._rebuilt_revision)
        self.journal.transition(A5Phase.CLEANUP_PREVIEWED, {
            "stamp_prefix": self.stamp_prefix,
            "element_count": len(created),
            "element_ids": list(created),
            "witnesses_complete": True,
            "retain": bool(retain),
            "document_revision": revision,
        })

    async def after_cleanup(
        self, created_ids, *, retain: bool, cleanup_ok: bool,
        cleanup_detail: str,
    ) -> None:
        if self.journal.state.phase is not A5Phase.CLEANUP_PREVIEWED:
            if cleanup_ok and not self.journal.state.pending_effects:
                final_preview = await self._preview()
                if final_preview["found"] != 0:
                    raise A5JournalError(
                        "failed A5 run cleanup left stamped survivors")
                created = tuple(sorted({str(item) for item in created_ids}))
                if not _cleanup_covers(
                        created, self._confirmed_receipts("delete"),
                        final_preview):
                    raise A5JournalError(
                        "failed A5 cleanup receipts do not cover created ids")
                await self._require_revision(self._snapshot_revision)
                receipt = CleanupReceipt(
                    run_id=self.journal.state.run_id,
                    stamp_prefix=self.stamp_prefix,
                    found_count=len(created), deleted_count=len(created),
                    remaining_count=0, found_ids=created,
                    deleted_ids=created, remaining_ids=(),
                    commit_status="Committed" if created else "NotStarted",
                    reconciled=True, witnesses_complete=True)
                self.journal.abandon(
                    receipt, reason="run failed after creating live elements")
            return
        created = tuple(sorted({str(item) for item in created_ids}))
        if retain:
            revision = await self._require_revision(self._rebuilt_revision)
            self.journal.transition(A5Phase.COMPLETED, {
                "retained": True, "retained_ids": list(created),
                "document_revision": revision})
            return
        if not cleanup_ok:
            return
        final_preview = await self._preview()
        if final_preview["found"] != 0:
            raise A5JournalError("cleanup claimed success with stamped survivors")
        if not _cleanup_covers(
                created, self._confirmed_receipts("delete"), final_preview):
            raise A5JournalError(
                "cleanup delete receipts do not cover created ids")
        revision = await self._require_revision(self._snapshot_revision)
        receipt = CleanupReceipt(
            run_id=self.journal.state.run_id,
            stamp_prefix=self.stamp_prefix,
            found_count=len(created), deleted_count=len(created),
            remaining_count=0,
            found_ids=created, deleted_ids=created, remaining_ids=(),
            commit_status="Committed" if created else "NotStarted",
            reconciled=True, witnesses_complete=True)
        self.journal.transition(A5Phase.COMPLETED, {
            "retained": False, "cleanup_receipt": receipt.to_dict(),
            "document_revision": revision})

    def recovered_report(self):
        if self.journal.state.phase is not A5Phase.COMPLETED:
            raise A5JournalError("A5 recovery is not complete")
        from kukai.ir.idempotence_report import (
            IdempotenceReport, KindComparison,
        )

        compared = self.journal.state.proofs[A5Phase.COMPARED]["report"]
        raw_kinds = compared.get("per_kind")
        if not isinstance(raw_kinds, list):
            raise A5JournalError("Compared report has no per-kind evidence")
        if any(not isinstance(row, Mapping) for row in raw_kinds):
            raise A5JournalError("Compared per-kind evidence is malformed")
        per_kind = tuple(KindComparison(
            op_name=str(row["op_name"]),
            expected=int(row["expected"]), actual=int(row["actual"]),
            matched=int(row["matched"]),
            excluded_expected=int(row.get("excluded_expected", 0)),
            excluded_actual=int(row.get("excluded_actual", 0)),
            excluded_matched=int(row.get("excluded_matched", 0)),
        ) for row in raw_kinds)
        delta = compared.get("delta_mm")
        if not isinstance(delta, list) or len(delta) != 3:
            raise A5JournalError("Compared report has no delta vector")
        completed = self.journal.state.proofs[A5Phase.COMPLETED]
        retained = completed.get("retained") is True
        report = IdempotenceReport(
            doc_stamp=str(compared["doc_stamp"]),
            delta_mm=(float(delta[0]), float(delta[1]), float(delta[2])),
            multiset_match=bool(compared["multiset_match"]),
            expected_hash=str(compared["expected_hash"]),
            actual_hash=str(compared["actual_hash"]),
            total_expected=int(compared["total_expected"]),
            total_actual=int(compared["total_actual"]),
            total_matched=int(compared["total_matched"]),
            total_extra=int(compared["total_extra"]),
            raw_exact_pct=compared.get("raw_recall_pct"),
            adjusted_exact_pct=compared.get("adjusted_recall_pct"),
            raw_precision_pct=compared.get("raw_precision_pct"),
            raw_recall_pct=compared.get("raw_recall_pct"),
            adjusted_precision_pct=compared.get("adjusted_precision_pct"),
            adjusted_recall_pct=compared.get("adjusted_recall_pct"),
            per_kind=per_kind,
            discrepancies=tuple(compared.get("discrepancies") or ()),
            datums_skipped=int(compared.get("datums_skipped", 0)),
            atoms_excluded=int(compared.get("atoms_excluded", 0)),
            atoms_escrowed=int(compared.get("atoms_escrowed", 0)),
            atoms_form_accepted=int(
                compared.get("atoms_form_accepted", 0)),
            atoms_form_rejected=int(
                compared.get("atoms_form_rejected", 0)),
            atoms_form_inconclusive=int(
                compared.get("atoms_form_inconclusive", 0)),
            form_expectations=tuple(
                compared.get("form_expectations") or ()),
            form_acceptance=tuple(
                compared.get("form_acceptance") or ()),
            form_read_error=str(compared.get("form_read_error") or ""),
            non_datum_total=int(compared["non_datum_total"]),
            comparable_coverage_pct=compared.get(
                "comparable_coverage_pct"),
            canon_version=str(compared["canon_version"]),
            created_ids=self.resume_created_ids,
            cleanup_ok=True,
            cleanup_detail=(
                "completed retained A5 replay" if retained
                else "completed from durable A5 cleanup replay"),
            dry_run=False,
        )
        return report
