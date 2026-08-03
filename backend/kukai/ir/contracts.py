"""Versioned value contracts shared by the KIR runtime boundaries.

This module is deliberately free of bridge, filesystem, database, and compiler
effects.  It gives later orchestration/state-machine work one typed vocabulary
for document identity, snapshot authority, run ownership, durable receipts,
and A5 metrics.

Compatibility rules are uniform:

* ``to_dict`` always writes the current explicit ``schema_version``;
* ``from_dict`` accepts the current version and the pre-versioned legacy shape;
* unknown fields are ignored so additive producers remain readable;
* an explicit unknown version is refused rather than guessed;
* legacy evidence which cannot prove a safety invariant remains readable, but
  its ``confirmed``/``authoritative`` property is false (fail closed).

PR1 only defines value types.  It does not introduce orchestration, I/O, a run
state machine, or a new persistence path.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
from dataclasses import dataclass
from typing import Any, ClassVar, Mapping, Sequence


class ContractSchemaError(ValueError):
    """A persisted or boundary-supplied contract is malformed/unsupported."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractSchemaError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ContractSchemaError(f"{field_name} keys must be strings")
    return dict(value)


def _version(row: Mapping[str, Any], current: str, field_name: str) -> None:
    """Accept current or legacy-unversioned input; reject explicit strangers."""

    if "schema_version" not in row:
        return
    value = row["schema_version"]
    if value != current:
        raise ContractSchemaError(
            f"unsupported {field_name} schema_version {value!r}; "
            f"expected {current!r}")


def _compatible_version(
    row: Mapping[str, Any],
    current: str,
    previous: frozenset[str],
    field_name: str,
) -> str | None:
    """Return an accepted explicit version, or ``None`` for legacy-unversioned.

    This is used only by contracts whose current writer version has advanced.
    Explicitly enumerating readable predecessors preserves the global rule:
    old artifacts remain readable, unknown future semantics are refused.
    """

    if "schema_version" not in row:
        return None
    value = row["schema_version"]
    if value != current and value not in previous:
        accepted = ", ".join(repr(item) for item in (current, *sorted(previous)))
        raise ContractSchemaError(
            f"unsupported {field_name} schema_version {value!r}; "
            f"accepted: {accepted}")
    return value


def _string(value: Any, field_name: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        suffix = "a non-empty string" if nonempty else "a string"
        raise ContractSchemaError(f"{field_name} must be {suffix}")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _string(value, field_name, nonempty=True)


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractSchemaError(f"{field_name} must be a JSON boolean")
    return value


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractSchemaError(
            f"{field_name} must be a non-negative integer")
    return value


def _optional_nonnegative_int(value: Any, field_name: str) -> int | None:
    return None if value is None else _nonnegative_int(value, field_name)


def _percentage(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractSchemaError(f"{field_name} must be a percentage or null")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        raise ContractSchemaError(f"{field_name} must be within [0, 100]")
    return number


def _strings(
    value: Any,
    field_name: str,
    *,
    nonempty_items: bool = True,
) -> tuple[str, ...]:
    if (not isinstance(value, Sequence)
            or isinstance(value, (str, bytes, bytearray))):
        raise ContractSchemaError(f"{field_name} must be a list of strings")
    result = tuple(
        _string(item, f"{field_name}[{index}]", nonempty=nonempty_items)
        for index, item in enumerate(value)
    )
    if len(set(result)) != len(result):
        raise ContractSchemaError(f"{field_name} must not contain duplicates")
    return result


_RUN_ID_RE = re.compile(r"[0-9a-f]{16}\Z")
_STAMP_PREFIX_RE = re.compile(
    r"kir:a5:[0-9a-f]{12}:(?P<run_id>[0-9a-f]{16}):\Z")
_VERSION_GUID_RE = re.compile(r"[0-9a-f]{32}\Z")
_ELEMENT_ID_MAX = 0x7FFFFFFFFFFFFFFF


@dataclass(frozen=True, slots=True)
class DocumentFingerprint:
    """Exact active-document identity used by every guarded Revit operation."""

    SCHEMA_VERSION: ClassVar[str] = "document-fingerprint/1"

    title: str
    path_name: str
    project_uid: str

    def __post_init__(self) -> None:
        # Preserve the serving contract's existing exception and permissive
        # empty-string semantics (an unsaved document has an empty PathName).
        if any(not isinstance(value, str) for value in (
                self.title, self.path_name, self.project_uid)):
            raise TypeError("document fingerprint fields must be strings")

    def compiler_guard(self) -> dict[str, str]:
        """The byte-stable, unversioned map embedded into generated C#."""

        return {
            "title": self.title,
            "path_name": self.path_name,
            "project_uid": self.project_uid,
        }

    @property
    def digest(self) -> str:
        stable = json.dumps(
            self.compiler_guard(), sort_keys=True, ensure_ascii=False,
            separators=(",", ":"))
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            **self.compiler_guard(),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "DocumentFingerprint":
        row = _mapping(value, "document_fingerprint")
        _version(row, cls.SCHEMA_VERSION, "document_fingerprint")
        return cls(
            title=_string(row.get("title"), "document_fingerprint.title"),
            path_name=_string(
                row.get("path_name"), "document_fingerprint.path_name"),
            project_uid=_string(
                row.get("project_uid"), "document_fingerprint.project_uid"),
        )


@dataclass(frozen=True, slots=True)
class ElementIdentityProof:
    """Exact identity of one live Revit element used by an emitted write.

    ``ElementId`` is only an address inside the current document.  ``UniqueId``
    prevents address reuse and ``VersionGuid`` changes when the addressed
    element changes.  The three values are therefore inseparable at the
    transaction boundary.
    """

    SCHEMA_VERSION: ClassVar[str] = "revit-element-identity/1"

    element_id: int
    unique_id: str
    version_guid: str

    def __post_init__(self) -> None:
        if (isinstance(self.element_id, bool)
                or not isinstance(self.element_id, int)
                or not 1 <= self.element_id <= _ELEMENT_ID_MAX):
            raise ContractSchemaError(
                "element_identity.element_id must be a positive int64")
        _string(
            self.unique_id, "element_identity.unique_id", nonempty=True)
        version_guid = _string(
            self.version_guid,
            "element_identity.version_guid",
            nonempty=True,
        )
        if not _VERSION_GUID_RE.fullmatch(version_guid):
            raise ContractSchemaError(
                "element_identity.version_guid must be 32 lowercase hex chars")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "element_id": self.element_id,
            "unique_id": self.unique_id,
            "version_guid": self.version_guid,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ElementIdentityProof":
        row = _mapping(value, "element_identity")
        _version(row, cls.SCHEMA_VERSION, "element_identity")
        return cls(
            element_id=row.get("element_id"),
            unique_id=_string(
                row.get("unique_id"),
                "element_identity.unique_id",
                nonempty=True,
            ),
            version_guid=_string(
                row.get("version_guid"),
                "element_identity.version_guid",
                nonempty=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class RevisionProof:
    """A decompile snapshot's exact document-revision witness."""

    SCHEMA_VERSION: ClassVar[str] = "document-revision/1"

    change_stamp: str
    fingerprint: str

    def __post_init__(self) -> None:
        _string(self.change_stamp, "revision_proof.change_stamp", nonempty=True)
        _string(self.fingerprint, "revision_proof.fingerprint", nonempty=True)

    def to_dict(self) -> dict[str, str]:
        # This is byte-for-field compatible with revision.proof.json.
        return {
            "schema_version": self.SCHEMA_VERSION,
            "change_stamp": self.change_stamp,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "RevisionProof":
        row = _mapping(value, "revision_proof")
        _version(row, cls.SCHEMA_VERSION, "revision_proof")
        return cls(
            change_stamp=_string(
                row.get("change_stamp"), "revision_proof.change_stamp",
                nonempty=True),
            fingerprint=_string(
                row.get("fingerprint"), "revision_proof.fingerprint",
                nonempty=True),
        )


@dataclass(frozen=True, slots=True)
class RunId:
    """Validated 128-bit A5 run ownership identifier (lowercase hex)."""

    SCHEMA_VERSION: ClassVar[str] = "a5-run-id/1"

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _RUN_ID_RE.fullmatch(self.value):
            raise ContractSchemaError(
                "run_id must be exactly 16 lowercase hexadecimal characters")

    @classmethod
    def new(cls) -> "RunId":
        return cls(secrets.token_hex(8))

    @classmethod
    def from_value(cls, value: Any) -> "RunId":
        return cls(_string(value, "run_id", nonempty=True))

    def to_dict(self) -> dict[str, str]:
        return {"schema_version": self.SCHEMA_VERSION, "run_id": self.value}

    @classmethod
    def from_dict(cls, value: Any) -> "RunId":
        row = _mapping(value, "run_id")
        _version(row, cls.SCHEMA_VERSION, "run_id")
        raw = row.get("run_id", row.get("value"))
        return cls.from_value(raw)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CoverageProof:
    """Named category coverage plus the committed L0 footer evidence."""

    SCHEMA_VERSION: ClassVar[str] = "snapshot-coverage/1"

    stream_complete: bool
    required_categories: tuple[str, ...]
    complete_categories: tuple[str, ...]
    partial_categories: tuple[str, ...]
    element_count: int
    link_count: int = 0

    def __post_init__(self) -> None:
        _strict_bool(self.stream_complete, "coverage.stream_complete")
        required = _strings(self.required_categories, "coverage.required_categories")
        complete = _strings(self.complete_categories, "coverage.complete_categories")
        partial = _strings(self.partial_categories, "coverage.partial_categories")
        object.__setattr__(self, "required_categories", required)
        object.__setattr__(self, "complete_categories", complete)
        object.__setattr__(self, "partial_categories", partial)
        if set(complete) & set(partial):
            raise ContractSchemaError(
                "coverage complete/partial categories must be disjoint")
        observed = set(complete) | set(partial)
        # Empty required_categories is the explicit legacy/unbound state: the
        # row remains inspectable but authoritative stays false.  Once the
        # caller supplies the known category universe, enforce it exactly.
        if required and not observed.issubset(set(required)):
            raise ContractSchemaError(
                "coverage contains categories outside required_categories")
        _nonnegative_int(self.element_count, "coverage.element_count")
        _nonnegative_int(self.link_count, "coverage.link_count")

    @property
    def category_count(self) -> int:
        return len(self.complete_categories) + len(self.partial_categories)

    @property
    def authoritative(self) -> bool:
        required = set(self.required_categories)
        observed = set(self.complete_categories) | set(self.partial_categories)
        return (
            self.stream_complete
            and bool(required)
            and not self.partial_categories
            and observed == required
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "stream_complete": self.stream_complete,
            "element_count": self.element_count,
            "link_count": self.link_count,
            "category_count": self.category_count,
            "required_categories": list(self.required_categories),
            "complete_categories": list(self.complete_categories),
            "partial_categories": list(self.partial_categories),
            "authoritative": self.authoritative,
        }

    @classmethod
    def from_dict(
        cls,
        value: Any,
        *,
        required_categories: Sequence[str] | None = None,
    ) -> "CoverageProof":
        row = _mapping(value, "coverage")
        _version(row, cls.SCHEMA_VERSION, "coverage")

        explicit_required = row.get("required_categories")
        if explicit_required is not None and required_categories is not None:
            parsed_explicit = _strings(
                explicit_required, "coverage.required_categories")
            parsed_argument = _strings(
                required_categories, "required_categories")
            if parsed_explicit != parsed_argument:
                raise ContractSchemaError(
                    "coverage required_categories disagree with caller")
            required = parsed_explicit
        elif explicit_required is not None:
            required = _strings(
                explicit_required, "coverage.required_categories")
        elif required_categories is not None:
            required = _strings(required_categories, "required_categories")
        else:
            # A legacy record can be inspected, but without the caller's known
            # category universe it cannot become authoritative by accident.
            required = ()

        states = row.get("category_states")
        if states is not None:
            state_map = _mapping(states, "coverage.category_states")
            legacy_complete: list[str] = []
            legacy_partial: list[str] = []
            for category, state in state_map.items():
                _string(category, "coverage.category_states key", nonempty=True)
                if state == "complete":
                    legacy_complete.append(category)
                elif state == "partial":
                    legacy_partial.append(category)
                else:
                    raise ContractSchemaError(
                        f"unknown coverage state {state!r} for {category!r}")
            legacy_complete.sort()
            legacy_partial.sort()
        else:
            legacy_complete = []
            legacy_partial = []

        has_lists = any(key in row for key in (
            "complete_categories", "partial_categories"))
        complete = _strings(
            row.get("complete_categories", []),
            "coverage.complete_categories")
        partial = _strings(
            row.get("partial_categories", []),
            "coverage.partial_categories")
        if states is not None:
            from_states = (tuple(legacy_complete), tuple(legacy_partial))
            if has_lists and (complete, partial) != from_states:
                raise ContractSchemaError(
                    "coverage category lists disagree with category_states")
            if not has_lists:
                complete, partial = from_states

        proof = cls(
            stream_complete=_strict_bool(
                row.get("stream_complete", False),
                "coverage.stream_complete"),
            required_categories=required,
            complete_categories=complete,
            partial_categories=partial,
            element_count=_nonnegative_int(
                row.get("element_count", 0), "coverage.element_count"),
            link_count=_nonnegative_int(
                row.get("link_count", 0), "coverage.link_count"),
        )
        if "category_count" in row and _nonnegative_int(
                row["category_count"], "coverage.category_count") \
                != proof.category_count:
            raise ContractSchemaError("coverage category_count mismatch")
        if "authoritative" in row and _strict_bool(
                row["authoritative"], "coverage.authoritative") \
                != proof.authoritative:
            raise ContractSchemaError("coverage authoritative flag mismatch")
        return proof


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """One snapshot bound to document identity, revision, and exact coverage."""

    SCHEMA_VERSION: ClassVar[str] = "snapshot-manifest/1"

    doc_stamp: str
    document_fingerprint: DocumentFingerprint
    revision_proof: RevisionProof
    coverage: CoverageProof
    l0_path: str = "L0.jsonl"

    def __post_init__(self) -> None:
        _string(self.doc_stamp, "snapshot.doc_stamp", nonempty=True)
        if not isinstance(self.document_fingerprint, DocumentFingerprint):
            raise ContractSchemaError(
                "snapshot.document_fingerprint must be DocumentFingerprint")
        if not isinstance(self.revision_proof, RevisionProof):
            raise ContractSchemaError(
                "snapshot.revision_proof must be RevisionProof")
        if not isinstance(self.coverage, CoverageProof):
            raise ContractSchemaError("snapshot.coverage must be CoverageProof")
        _string(self.l0_path, "snapshot.l0_path", nonempty=True)
        if self.revision_proof.change_stamp != self.doc_stamp:
            raise ContractSchemaError(
                "snapshot revision proof is bound to another change_stamp")

    @property
    def authoritative(self) -> bool:
        return self.coverage.authoritative

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "doc_stamp": self.doc_stamp,
            "l0_path": self.l0_path,
            "document_fingerprint": self.document_fingerprint.to_dict(),
            "revision_proof": self.revision_proof.to_dict(),
            "coverage": self.coverage.to_dict(),
            "authoritative": self.authoritative,
        }

    @classmethod
    def from_dict(
        cls,
        value: Any,
        *,
        required_categories: Sequence[str] | None = None,
    ) -> "SnapshotManifest":
        row = _mapping(value, "snapshot")
        _version(row, cls.SCHEMA_VERSION, "snapshot")
        document = row.get("document_fingerprint", row.get("document"))
        revision = row.get("revision_proof", row.get("revision"))
        manifest = cls(
            doc_stamp=_string(
                row.get("doc_stamp"), "snapshot.doc_stamp", nonempty=True),
            document_fingerprint=DocumentFingerprint.from_dict(document),
            revision_proof=RevisionProof.from_dict(revision),
            coverage=CoverageProof.from_dict(
                row.get("coverage"),
                required_categories=required_categories),
            l0_path=_string(
                row.get("l0_path", "L0.jsonl"), "snapshot.l0_path",
                nonempty=True),
        )
        if "authoritative" in row and _strict_bool(
                row["authoritative"], "snapshot.authoritative") \
                != manifest.authoritative:
            raise ContractSchemaError("snapshot authoritative flag mismatch")
        return manifest


@dataclass(frozen=True, slots=True)
class CommitReceipt:
    """Durable witness receipt for one rebuild or delete transaction."""

    SCHEMA_VERSION: ClassVar[str] = "a5-commit-receipt/3"
    PREVIOUS_SCHEMA_VERSIONS: ClassVar[frozenset[str]] = frozenset({
        "a5-commit-receipt/1",
        "a5-commit-receipt/2",
    })
    OPERATIONS: ClassVar[frozenset[str]] = frozenset({"rebuild", "delete"})

    run_id: RunId
    operation: str
    element_ids: tuple[str, ...]
    bridge_error: bool
    commit_confirmed: bool
    commit_status: str | None = None
    program_id: str | None = None
    document_revision: str | None = None
    #: Пооперационные отказы ВНУТРИ закоммиченной транзакции (/3, 29.07).
    #: Каждая строка: {"op_id", "op_name", "intent", "reason"}. `reason` —
    #: дословный текст моста, без урезания.
    #:
    #: ПОВОД ЗАМЕРЕН (пересборка №11, v18): 113 линий разрезки витража
    #: отказали пооперационно ВНУТРИ успешных транзакций. Прогон отчитался
    #: «Committed», линии попали в missing, и ни одного слова о причине не
    #: сохранилось — квитанция несла только element_ids. Причина при этом
    #: приходила наружу с самого начала: в isolation="per_op" эмиссия кладёт
    #: её в тот же `result`, откуда берутся id (`__rf["refused"]`).
    op_refusals: tuple[Mapping[str, Any], ...] = ()
    #: Опов в программе чанка ВСЕГО и опов, закрывшихся без рождения элемента
    #: ПО СЕМАНТИКЕ (`created:false` — смена типа панели на месте). Ноль в
    #: ``ops_total`` = закон переписи выключен: так читаются журналы, писанные
    #: до /3.
    ops_total: int = 0
    ops_no_element: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise ContractSchemaError("commit_receipt.run_id must be RunId")
        if self.operation not in self.OPERATIONS:
            raise ContractSchemaError(
                "commit_receipt.operation must be rebuild or delete")
        element_ids = _strings(
            self.element_ids, "commit_receipt.element_ids")
        object.__setattr__(self, "element_ids", element_ids)
        _strict_bool(self.bridge_error, "commit_receipt.bridge_error")
        _strict_bool(
            self.commit_confirmed, "commit_receipt.commit_confirmed")
        _optional_string(self.commit_status, "commit_receipt.commit_status")
        program_id = _optional_string(
            self.program_id, "commit_receipt.program_id")
        if program_id is not None and re.fullmatch(
                r"[0-9a-f]{64}", program_id) is None:
            raise ContractSchemaError(
                "commit_receipt.program_id must be 64 lowercase hex chars")
        _optional_string(
            self.document_revision, "commit_receipt.document_revision")
        if self.commit_confirmed and self.bridge_error:
            raise ContractSchemaError(
                "a bridge-error receipt cannot confirm a commit")
        if (self.commit_confirmed and self.commit_status is not None
                and self.commit_status != "Committed"):
            raise ContractSchemaError(
                "confirmed receipt has a non-Committed status")
        refusals = tuple(
            _mapping(row, "commit_receipt.op_refusals[]")
            for row in (self.op_refusals or ()))
        for row in refusals:
            _string(row.get("op_id"), "commit_receipt.op_refusals[].op_id",
                    nonempty=True)
            _string(row.get("reason"), "commit_receipt.op_refusals[].reason",
                    nonempty=True)
        object.__setattr__(self, "op_refusals", refusals)
        _nonnegative_int(self.ops_total, "commit_receipt.ops_total")
        _nonnegative_int(
            self.ops_no_element, "commit_receipt.ops_no_element")
        # ЗАКОН ПЕРЕПИСИ ЧАНКА: у каждого опа обязан быть ИСХОД.
        #
        #     созданные + отказавшие + закрывшиеся-без-элемента == опов
        #
        # Расхождение — это не мелочь отчёта, это класс «молча не создано»:
        # оп, о котором никто ничего не знает. Замер v18: чанк 6 = 198 + 37 +
        # 15 = 250 сходится, и ровно эти 37 были невидимы без закона.
        #
        # ДОПУЩЕНИЕ, КОТОРОЕ ЗДЕСЬ ЗАШИТО: ОДИН ОП СОЗДАЁТ НЕ БОЛЬШЕ ОДНОГО
        # ЭЛЕМЕНТА, поэтому число созданных id можно приравнивать к числу
        # успешных опов. Сегодня в пересборке это так (ретро-баланс v18
        # сошёлся на всех закоммиченных чанках), но это СВОЙСТВО НЫНЕШНЕГО
        # НАБОРА ОПОВ, а не закон природы: многоэлементный оп (move_elements
        # с набором целей — уже рядом) сломает равенство, и сломает ЧЕСТНО,
        # красным. Автору такого опа: закон надо считать по ОПАМ, а не по id
        # (нести в квитанции ops_created), а не ослаблять сравнение. См.
        # test_law_assumes_one_element_per_op.
        if self.ops_total:
            accounted = (len(self.element_ids) + len(refusals)
                         + self.ops_no_element)
            if accounted != self.ops_total:
                raise ContractSchemaError(
                    "commit_receipt: опы чанка не сходятся — учтено "
                    f"{accounted} из {self.ops_total} "
                    f"(создано {len(self.element_ids)}, отказало "
                    f"{len(refusals)}, без элемента {self.ops_no_element})")

    @property
    def confirmed(self) -> bool:
        return self.commit_confirmed and not self.bridge_error

    @property
    def refused_without_commit(self) -> bool:
        """Известный ОТРИЦАТЕЛЬНЫЙ исход: Revit ответил, ничего не создано.

        Отказ — тоже свидетельство. Отличать его от НЕИЗВЕСТНОСТИ обязательно:
        при `timeout_unconfirmed` ответа нет вовсе, Revit мог зафиксировать, и
        такой эффект остаётся дырой в покрытии плана. Здесь же ответ получен,
        транзакция откатена, витнесов элементов нет — программа закрыта.
        """

        return (
            self.bridge_error
            and not self.commit_confirmed
            and not self.element_ids
            and self.program_id is not None
        )

    @property
    def decided(self) -> bool:
        """Исход ИЗВЕСТЕН: либо коммит подтверждён, либо отказ засвидетельствован."""

        return self.confirmed or self.refused_without_commit

    @property
    def resumable_rebuild(self) -> bool:
        """Whether this receipt can prove one exact restart boundary."""

        return (
            self.operation == "rebuild"
            and self.confirmed
            and self.program_id is not None
            and self.document_revision is not None
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": self.run_id.value,
            "operation": self.operation,
            "element_ids": list(self.element_ids),
            "element_count": len(self.element_ids),
            "bridge_error": self.bridge_error,
            "commit_confirmed": self.commit_confirmed,
        }
        if self.commit_status is not None:
            result["commit_status"] = self.commit_status
        if self.program_id is not None:
            result["program_id"] = self.program_id
        if self.document_revision is not None:
            result["document_revision"] = self.document_revision
        if self.op_refusals:
            result["op_refusals"] = [dict(row) for row in self.op_refusals]
        if self.ops_total:
            result["ops_total"] = self.ops_total
            result["ops_no_element"] = self.ops_no_element
            result["ops_refused"] = len(self.op_refusals)
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "CommitReceipt":
        row = _mapping(value, "commit_receipt")
        _compatible_version(
            row,
            cls.SCHEMA_VERSION,
            cls.PREVIOUS_SCHEMA_VERSIONS,
            "commit_receipt",
        )
        event = row.get("event")
        operation = row.get("operation")
        legacy_ids_key: str | None = None
        legacy_count_key: str | None = None
        if operation is None and event == "rebuild_commit_receipt":
            operation = "rebuild"
            legacy_ids_key = "created_ids"
            legacy_count_key = "created_ids_count"
        elif operation is None and event == "delete_commit_receipt":
            operation = "delete"
            legacy_ids_key = "deleted_ids"
            legacy_count_key = "deleted_ids_count"
        ids_key = "element_ids" if "element_ids" in row else legacy_ids_key
        if ids_key is None:
            raise ContractSchemaError("commit_receipt has no element witnesses")
        ids = _strings(row.get(ids_key), f"commit_receipt.{ids_key}")
        count_key = "element_count" if "element_count" in row else legacy_count_key
        if count_key is not None and count_key in row:
            count = _nonnegative_int(
                row[count_key], f"commit_receipt.{count_key}")
            if count != len(ids):
                raise ContractSchemaError("commit_receipt element count mismatch")
        raw_run_id = row.get("run_id")
        run_id = (RunId.from_dict(raw_run_id)
                  if isinstance(raw_run_id, Mapping)
                  else RunId.from_value(raw_run_id))
        return cls(
            run_id=run_id,
            operation=_string(
                operation, "commit_receipt.operation", nonempty=True),
            element_ids=ids,
            # Missing legacy evidence is pessimistic, never inferred as safe.
            bridge_error=_strict_bool(
                row.get("bridge_error", True),
                "commit_receipt.bridge_error"),
            commit_confirmed=_strict_bool(
                row.get("commit_confirmed", False),
                "commit_receipt.commit_confirmed"),
            commit_status=_optional_string(
                row.get("commit_status"), "commit_receipt.commit_status"),
            program_id=_optional_string(
                row.get("program_id"), "commit_receipt.program_id"),
            document_revision=_optional_string(
                row.get("document_revision"),
                "commit_receipt.document_revision"),
            # /3-поля НЕОБЯЗАТЕЛЬНЫ: журналы прогонов №9-№11 их не имеют, и
            # ``ops_total=0`` выключает закон переписи — старое доказательство
            # остаётся читаемым, как того требует общее правило контрактов.
            op_refusals=tuple(
                _mapping(item, "commit_receipt.op_refusals[]")
                for item in (row.get("op_refusals") or ())),
            ops_total=_nonnegative_int(
                row.get("ops_total", 0), "commit_receipt.ops_total"),
            ops_no_element=_nonnegative_int(
                row.get("ops_no_element", 0),
                "commit_receipt.ops_no_element"),
        )


@dataclass(frozen=True, slots=True)
class CleanupReceipt:
    """Run-scoped stamp reconciliation evidence.

    Old ``stamp_reconciliation`` ledger rows did not persist the prefix or the
    complete ID witnesses.  They remain parseable, but ``confirmed`` remains
    false until both ownership and complete witnesses are present.
    """

    SCHEMA_VERSION: ClassVar[str] = "a5-cleanup-receipt/1"

    run_id: RunId
    stamp_prefix: str | None
    found_count: int
    deleted_count: int
    remaining_count: int
    found_ids: tuple[str, ...]
    deleted_ids: tuple[str, ...]
    remaining_ids: tuple[str, ...]
    commit_status: str | None
    reconciled: bool
    witnesses_complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            raise ContractSchemaError("cleanup_receipt.run_id must be RunId")
        prefix = _optional_string(
            self.stamp_prefix, "cleanup_receipt.stamp_prefix")
        if prefix is not None:
            match = _STAMP_PREFIX_RE.fullmatch(prefix)
            if match is None or match.group("run_id") != self.run_id.value:
                raise ContractSchemaError(
                    "cleanup stamp_prefix is invalid or bound to another run")
        _nonnegative_int(self.found_count, "cleanup_receipt.found_count")
        _nonnegative_int(self.deleted_count, "cleanup_receipt.deleted_count")
        _nonnegative_int(
            self.remaining_count, "cleanup_receipt.remaining_count")
        found = _strings(self.found_ids, "cleanup_receipt.found_ids")
        deleted = _strings(self.deleted_ids, "cleanup_receipt.deleted_ids")
        remaining = _strings(
            self.remaining_ids, "cleanup_receipt.remaining_ids")
        object.__setattr__(self, "found_ids", found)
        object.__setattr__(self, "deleted_ids", deleted)
        object.__setattr__(self, "remaining_ids", remaining)
        _optional_string(self.commit_status, "cleanup_receipt.commit_status")
        _strict_bool(self.reconciled, "cleanup_receipt.reconciled")
        _strict_bool(
            self.witnesses_complete, "cleanup_receipt.witnesses_complete")
        for count, values, name in (
            (self.found_count, found, "found"),
            (self.deleted_count, deleted, "deleted"),
            (self.remaining_count, remaining, "remaining"),
        ):
            if count < len(values):
                raise ContractSchemaError(
                    f"cleanup {name}_count is smaller than its witnesses")
            if self.witnesses_complete and count != len(values):
                raise ContractSchemaError(
                    f"cleanup complete {name} witnesses do not match count")

    @property
    def ownership_bound(self) -> bool:
        return self.stamp_prefix is not None

    @property
    def confirmed(self) -> bool:
        committed = (
            self.found_count == 0
            or self.commit_status == "Committed"
        )
        return (
            self.ownership_bound
            and self.witnesses_complete
            and self.reconciled
            and committed
            and self.remaining_count == 0
            and not self.remaining_ids
            and self.found_count == self.deleted_count
            and set(self.found_ids) == set(self.deleted_ids)
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": self.run_id.value,
            "stamp_prefix": self.stamp_prefix,
            "found_count": self.found_count,
            "deleted_count": self.deleted_count,
            "remaining_count": self.remaining_count,
            "found_ids": list(self.found_ids),
            "deleted_ids": list(self.deleted_ids),
            "remaining_ids": list(self.remaining_ids),
            "commit_status": self.commit_status,
            "reconciled": self.reconciled,
            "witnesses_complete": self.witnesses_complete,
            "confirmed": self.confirmed,
        }
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "CleanupReceipt":
        row = _mapping(value, "cleanup_receipt")
        _version(row, cls.SCHEMA_VERSION, "cleanup_receipt")
        legacy = row.get("event") == "stamp_reconciliation"
        found_key = "found_count" if "found_count" in row else "found"
        remaining_key = (
            "remaining_count" if "remaining_count" in row else "remaining")
        found_count = _nonnegative_int(
            row.get(found_key, 0), f"cleanup_receipt.{found_key}")
        remaining_count = _nonnegative_int(
            row.get(remaining_key, 0), f"cleanup_receipt.{remaining_key}")
        # Legacy reconciliation recorded no exact delete count.  Keep it
        # unknown-as-zero with witnesses_complete=false, never infer proof.
        deleted_count = _nonnegative_int(
            row.get("deleted_count", 0), "cleanup_receipt.deleted_count")
        raw_run_id = row.get("run_id")
        run_id = (RunId.from_dict(raw_run_id)
                  if isinstance(raw_run_id, Mapping)
                  else RunId.from_value(raw_run_id))
        receipt = cls(
            run_id=run_id,
            stamp_prefix=_optional_string(
                row.get("stamp_prefix"), "cleanup_receipt.stamp_prefix"),
            found_count=found_count,
            deleted_count=deleted_count,
            remaining_count=remaining_count,
            found_ids=_strings(
                row.get("found_ids", []), "cleanup_receipt.found_ids"),
            deleted_ids=_strings(
                row.get("deleted_ids", []), "cleanup_receipt.deleted_ids"),
            remaining_ids=_strings(
                row.get("remaining_ids", []),
                "cleanup_receipt.remaining_ids"),
            commit_status=_optional_string(
                row.get("commit_status"), "cleanup_receipt.commit_status"),
            reconciled=_strict_bool(
                row.get("reconciled", False),
                "cleanup_receipt.reconciled"),
            witnesses_complete=_strict_bool(
                row.get("witnesses_complete", False),
                "cleanup_receipt.witnesses_complete"),
        )
        if "confirmed" in row and not legacy and _strict_bool(
                row["confirmed"], "cleanup_receipt.confirmed") \
                != receipt.confirmed:
            raise ContractSchemaError("cleanup confirmed flag mismatch")
        return receipt


@dataclass(frozen=True, slots=True)
class IdempotenceMetrics:
    """Honest, versioned A5 metric payload independent of report prose."""

    SCHEMA_VERSION: ClassVar[str] = "idempotence-metrics/1"

    comparison_performed: bool
    multiset_match: bool | None
    total_expected: int
    total_actual: int | None
    total_matched: int
    total_extra: int | None
    raw_precision_pct: float | None
    raw_recall_pct: float | None
    adjusted_precision_pct: float | None
    adjusted_recall_pct: float | None
    atoms_excluded: int
    non_datum_total: int
    comparable_coverage_pct: float | None
    canon_version: str

    def __post_init__(self) -> None:
        _strict_bool(
            self.comparison_performed, "metrics.comparison_performed")
        if self.multiset_match is not None and not isinstance(
                self.multiset_match, bool):
            raise ContractSchemaError("metrics.multiset_match must be bool/null")
        if self.comparison_performed != (self.multiset_match is not None):
            raise ContractSchemaError(
                "metrics comparison_performed/multiset_match disagree")
        expected = _nonnegative_int(
            self.total_expected, "metrics.total_expected")
        actual = _optional_nonnegative_int(
            self.total_actual, "metrics.total_actual")
        matched = _nonnegative_int(
            self.total_matched, "metrics.total_matched")
        extra = _optional_nonnegative_int(
            self.total_extra, "metrics.total_extra")
        if matched > expected or (actual is not None and matched > actual):
            raise ContractSchemaError("metrics matched exceeds a denominator")
        if actual is not None and extra is not None \
                and extra != actual - matched:
            raise ContractSchemaError("metrics total_extra mismatch")
        for attribute, name in (
            ("raw_precision_pct", "raw_precision_pct"),
            ("raw_recall_pct", "raw_recall_pct"),
            ("adjusted_precision_pct", "adjusted_precision_pct"),
            ("adjusted_recall_pct", "adjusted_recall_pct"),
            ("comparable_coverage_pct", "comparable_coverage_pct"),
        ):
            object.__setattr__(
                self, attribute,
                _percentage(getattr(self, attribute), f"metrics.{name}"))
        atoms = _nonnegative_int(
            self.atoms_excluded, "metrics.atoms_excluded")
        non_datum = _nonnegative_int(
            self.non_datum_total, "metrics.non_datum_total")
        if atoms > non_datum or expected > non_datum:
            raise ContractSchemaError(
                "metrics coverage counts exceed non_datum_total")
        _string(self.canon_version, "metrics.canon_version", nonempty=True)
        if not self.comparison_performed and any(value is not None for value in (
                self.raw_precision_pct, self.raw_recall_pct,
                self.adjusted_precision_pct, self.adjusted_recall_pct,
                self.comparable_coverage_pct)):
            raise ContractSchemaError(
                "unperformed comparison cannot carry measured percentages")

    @property
    def precision_available(self) -> bool:
        return self.total_actual is not None and self.raw_precision_pct is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "comparison_performed": self.comparison_performed,
            "multiset_match": self.multiset_match,
            "total_expected": self.total_expected,
            "total_actual": self.total_actual,
            "total_matched": self.total_matched,
            "total_extra": self.total_extra,
            # Keep the historical aliases on the wire for old consumers.
            "raw_exact_pct": self.raw_recall_pct,
            "adjusted_exact_pct": self.adjusted_recall_pct,
            "raw_precision_pct": self.raw_precision_pct,
            "raw_recall_pct": self.raw_recall_pct,
            "adjusted_precision_pct": self.adjusted_precision_pct,
            "adjusted_recall_pct": self.adjusted_recall_pct,
            "atoms_excluded": self.atoms_excluded,
            "non_datum_total": self.non_datum_total,
            "comparable_coverage_pct": self.comparable_coverage_pct,
            "canon_version": self.canon_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "IdempotenceMetrics":
        row = _mapping(value, "metrics")
        _version(row, cls.SCHEMA_VERSION, "metrics")
        multiset_match = row.get("multiset_match")
        if multiset_match is not None and not isinstance(multiset_match, bool):
            raise ContractSchemaError("metrics.multiset_match must be bool/null")
        comparison = row.get(
            "comparison_performed", multiset_match is not None)
        comparison_performed = _strict_bool(
            comparison, "metrics.comparison_performed")
        total_expected = _nonnegative_int(
            row.get("total_expected", 0), "metrics.total_expected")
        atoms = _nonnegative_int(
            row.get("atoms_excluded", 0), "metrics.atoms_excluded")
        non_datum = _nonnegative_int(
            row.get("non_datum_total", total_expected + atoms),
            "metrics.non_datum_total")

        raw_recall = row.get("raw_recall_pct", row.get("raw_exact_pct"))
        adjusted_recall = row.get(
            "adjusted_recall_pct", row.get("adjusted_exact_pct"))
        return cls(
            comparison_performed=comparison_performed,
            multiset_match=multiset_match,
            total_expected=total_expected,
            total_actual=_optional_nonnegative_int(
                row.get("total_actual"), "metrics.total_actual"),
            total_matched=_nonnegative_int(
                row.get("total_matched", 0), "metrics.total_matched"),
            total_extra=_optional_nonnegative_int(
                row.get("total_extra"), "metrics.total_extra"),
            raw_precision_pct=_percentage(
                row.get("raw_precision_pct"), "metrics.raw_precision_pct"),
            raw_recall_pct=_percentage(
                raw_recall, "metrics.raw_recall_pct"),
            adjusted_precision_pct=_percentage(
                row.get("adjusted_precision_pct"),
                "metrics.adjusted_precision_pct"),
            adjusted_recall_pct=_percentage(
                adjusted_recall, "metrics.adjusted_recall_pct"),
            atoms_excluded=atoms,
            non_datum_total=non_datum,
            comparable_coverage_pct=_percentage(
                row.get("comparable_coverage_pct"),
                "metrics.comparable_coverage_pct"),
            canon_version=_string(
                row.get("canon_version", "legacy/unknown"),
                "metrics.canon_version", nonempty=True),
        )


__all__ = [
    "CleanupReceipt",
    "CommitReceipt",
    "ContractSchemaError",
    "CoverageProof",
    "DocumentFingerprint",
    "ElementIdentityProof",
    "IdempotenceMetrics",
    "RevisionProof",
    "RunId",
    "SnapshotManifest",
]
