"""Explicit stored CREATE commands; existing owners control all native effects.

No credentials, generated source, raw responses or native error text leave this
adapter. Status reads retained facts only. Receipt/recover contact the selected
runtime but cannot execute the archived program. No implicit schema upgrade.
"""
from datetime import datetime, timezone
import json


ACTIONS = frozenset({"create-upgrade", "create-publish", "create-status", "create-receipt", "create-recover",
                     "create-cancel-before-start", "create-resolve-not-started", "create-readback-types"})
ARCHIVE_ACTIONS = frozenset({"create-receipt", "create-recover", "create-cancel-before-start", "create-resolve-not-started",
                             "create-readback-types"})
MAX_COMPILER_DIAGNOSTICS = 20


def _compiler_diagnostics(error):
    """Bounded local Diagnostic whitelist, never native/free-form error text.

    Index is a compiled operation index, NOT an authored project position. A
    missing/invalid index is omitted. Withheld malformed rows and a capped tail
    make the truncation flag true; no arbitrary object is stringified.
    """
    from kir.diag import Diagnostic, spec_of
    from kir.compiler import MAX_VALIDATED_OPS
    values = getattr(error, "diagnostics", ())
    if type(values) not in (tuple, list):
        return {"compiler_diagnostics": [], "diagnostics_truncated": True}
    rows = []
    omitted = len(values) > MAX_COMPILER_DIAGNOSTICS
    for diagnostic in values[:MAX_COMPILER_DIAGNOSTICS]:
        if type(diagnostic) is not Diagnostic:
            omitted = True
            continue
        code = getattr(diagnostic, "code", None)
        if type(code) is not str or spec_of(code) is None:
            omitted = True
            continue
        row = {"code": code, "stage": "local_compile"}
        index = getattr(diagnostic, "op_index", None)
        if type(index) is int and 0 <= index < MAX_VALIDATED_OPS:
            row["compiled_op_index"] = index
        rows.append(row)
    return {"compiler_diagnostics": rows, "diagnostics_truncated": omitted}


def output(action, **fields):
    print(json.dumps({"schema": "kir-project-publication-cli/1", "action": action,
        "may_retry": False, "intent_verified": False, "dispatch_permission": "none",
        **fields}, ensure_ascii=True, allow_nan=False, indent=2))


def register(project_sub):
    for action in sorted(ACTIONS):
        parser = project_sub.add_parser(action, help={
            "create-upgrade": "явно обновить store до /6; без публикации",
            "create-publish": "первичная CREATE публикация выбранного scope; не update",
            "create-status": "найти сохранённый CREATE input по ID операции; без Revit",
            "create-receipt": "прочитать native receipt исходного runtime; без повторного CREATE",
            "create-recover": "явно восстановить receipt через выбранный runtime; без CREATE",
            "create-cancel-before-start": "отменить ещё не начавшуюся операцию в исходном journal; не rollback",
            "create-resolve-not-started": "fresh receipt lookup и освобождение scope только при доказанном no-start",
            "create-readback-types": "прочитать назначенные типы для архивной публикации; не BIM acceptance",
        }[action])
        parser.add_argument("database", help="существующее SQLite хранилище проекта")
        if action in {"create-upgrade", "create-publish"}:
            parser.add_argument("--expected", required=True, metavar="REVISION")
        if action == "create-upgrade":
            parser.add_argument("--enable-no-start-resolution", action="store_true",
                                help="явно обновить до /7 для безопасного освобождения CREATE scope")
        if action == "create-status":
            parser.add_argument("--journal-id", required=True)
            parser.add_argument("--operation-id", required=True)
        if action in ARCHIVE_ACTIONS:
            parser.add_argument("--archive", required=True, metavar="SHA256")
        if action == "create-resolve-not-started":
            parser.add_argument("--via-recovery", action="store_true",
                                help="lookup исходного receipt через другой явно выбранный runtime")
        if action == "create-readback-types":
            parser.add_argument("--document-key", required=True)
            parser.add_argument("--bind-view", choices=("yes", "no"), required=True)
            parser.add_argument("--bind-selection", choices=("yes", "no"), required=True)
        if action == "create-publish" or action in ARCHIVE_ACTIONS:
            parser.add_argument("--directory", required=True, help="явный каталог v4/discovery")
            for field in ("journal-id", "instance-id", "revit-version", "session-id", "client"):
                parser.add_argument("--" + field, required=True)
            parser.add_argument("--timeout-ms", type=int, default=30000)
        if action == "create-publish":
            choice = parser.add_mutually_exclusive_group(required=True)
            choice.add_argument("--instance", action="append", help="корневой instance; зависимости включаются автоматически")
            choice.add_argument("--all-instances", action="store_true")
            parser.add_argument("--operation-id", required=True, help="новый UUID; сохраняй для поиска после потери ответа")
            parser.add_argument("--document-key", required=True, help="точный документ из connector context")
            parser.add_argument("--bind-view", choices=("yes", "no"), required=True)
            parser.add_argument("--bind-selection", choices=("yes", "no"), required=True)
            parser.add_argument("--bulk", action="store_true", help="увеличенный внутренний бюджет операций; не режим транзакций")
            parser.add_argument("--isolation", choices=("atomic", "per_op"), default="atomic",
                                help="atomic по умолчанию; per_op допускает частичное исполнение")
            parser.add_argument("--confirm-create", action="store_true", required=True,
                                help="явно разрешить одну первичную native CREATE отправку")
        parser.set_defaults(func=run)


def _selection_materialization(store, project, args):
    from kir.geometry_materialization import materialize_project, materialize_selection
    from kir.project_selection import select_project_instances
    selection = (None if args.all_instances else
                 select_project_instances(project, instance_keys=tuple(args.instance)))
    addresses = project.addressed_outputs()
    chosen = (addresses if selection is None else
              tuple(addresses[index] for index in selection.project_source_indices))
    digests = {output.geometry.bundle_sha256 for _, output, _ in chosen if output.geometry is not None}
    bundles = {digest: store.get_asset(digest) for digest in sorted(digests)}
    return (materialize_project(project, bundles, bulk=args.bulk) if selection is None else
            materialize_selection(project, selection, bundles, bulk=args.bulk))


def run(args):
    from kir.__main__ import ANSWERED, REFUSED, NOT_DONE
    from kir.project_store import (ProjectStore, CREATE_STORE_SCHEMA, CREATE_RESOLUTION_STORE_SCHEMA,
        _CREATE_SCHEMAS, ProjectStoreError,
        StoreConflict, StoreCorrupt, StoreNotFound, StoreUpgradeRequired, StoreCommitUnknown)
    from kir.revit_connector import RuntimeTarget, ConnectorPreparationError
    from kir.revit_discovery import scan_discovery, DiscoveryError
    from kir.revit_transport import ConnectorTransportError
    from kir.standalone_publish import (PublicationRefusal, publish_stored_project, recover_stored_create,
        cancel_stored_create, resolve_stored_create_not_started)
    from kir.create_publication import CreatePublicationError
    from kir.saved_execution import SavedExecutionError
    from kir.stored_type_readback import StoredTypeReadbackError, readback_stored_create_types
    from kir.outcome import ExecutionState
    from kir.project_selection import ProjectSelectionError
    from kir.occt_geometry import GeometryRefusal

    action = args.project_action
    try:
        store = ProjectStore.open(args.database, readonly=action == "create-status")
        if action == "create-upgrade":
            schema = CREATE_RESOLUTION_STORE_SCHEMA if args.enable_no_start_resolution else CREATE_STORE_SCHEMA
            inserted = store.upgrade_schema(schema, expected_revision=args.expected)
            output(action, status="upgraded", store_schema=store.schema, changed=inserted,
                   native_request="none", author_head_changed=False)
            return ANSWERED
        if store.schema not in _CREATE_SCHEMAS:
            raise StoreUpgradeRequired("explicit CREATE schema upgrade required")
        if action == "create-status":
            publication = store.find_create_publication(journal_id=args.journal_id, operation_id=args.operation_id)
            receipts = store.get_create_receipts(publication.archive_digest).to_dict()
            resolution = (store.get_create_resolution(publication.archive_digest)
                          if store.schema == CREATE_RESOLUTION_STORE_SCHEMA else None)
            output(action, status="retained", archive_digest=publication.archive_digest,
                   source_revision=publication.source_revision, output_ids=list(publication.output_ids),
                   reservation_state=publication.state, receipt_count=len(receipts["receipts"]),
                   terminal_receipt_digest=receipts["terminal_receipt_digest"],
                   resolution_receipt_digest=resolution.receipt_digest if resolution is not None else None,
                   native_request="none", observation="retained_not_fresh",
                   native_acceptance="not_established",
                   scope_ownership="released_not_started" if publication.state == "released_not_started" else "retained")
            return ANSWERED

        target = RuntimeTarget(args.journal_id, args.instance_id, args.revit_version)
        catalog = scan_discovery(args.directory)
        advertisement = catalog.select(target=target, session_id=args.session_id, now=datetime.now(timezone.utc))
        if action == "create-readback-types":
            readback = readback_stored_create_types(store, args.archive, advertisement=advertisement,
                client_path=args.client, expected_target=target, expected_document_key=args.document_key,
                bind_view=args.bind_view == "yes", bind_selection=args.bind_selection == "yes",
                timeout_ms=args.timeout_ms)
            output(action, status="readback" if readback.discrepancy is not None else "unavailable",
                   native_request="receipt_lookup_then_read_only_queries", readback=readback.to_dict(),
                   catalog_complete=not catalog.issues, issues=[{"code": issue.code} for issue in catalog.issues])
            return ANSWERED if readback.discrepancy is not None else REFUSED
        if action == "create-publish":
            project = store.head()
            if project.revision_id != args.expected:
                raise StoreConflict("authored head changed")
            materialized = _selection_materialization(store, project, args)
            attempt = publish_stored_project(store, materialized, expected_revision=args.expected,
                advertisement=advertisement, client_path=args.client,
                expected_document_key=args.document_key, operation_id=args.operation_id,
                bind_view=args.bind_view == "yes", bind_selection=args.bind_selection == "yes",
                timeout_ms=args.timeout_ms, isolation=args.isolation)
        elif action == "create-cancel-before-start":
            attempt = cancel_stored_create(store, args.archive, advertisement=advertisement,
                client_path=args.client, timeout_ms=args.timeout_ms)
        elif action == "create-resolve-not-started":
            attempt = resolve_stored_create_not_started(store, args.archive, advertisement=advertisement,
                client_path=args.client, recovery=args.via_recovery, timeout_ms=args.timeout_ms)
        else:
            attempt = recover_stored_create(store, args.archive, advertisement=advertisement,
                client_path=args.client, recovery=action == "create-recover", timeout_ms=args.timeout_ms)
        output(action, status="assessed", archive_digest=attempt.record.digest,
               retained_receipt_digest=attempt.retained_receipt_digest,
               resolution_receipt_digest=attempt.resolution_receipt_digest,
               no_start_confirmed=attempt.result.outcome.execution is ExecutionState.NOT_STARTED,
               execution_contract_satisfied=attempt.execution_contract_satisfied,
               outcome=attempt.result.outcome.to_dict(), diagnostic_code=attempt.result.diagnostic_code,
               native_request=("execute_once" if action == "create-publish" else
                               "cancel_before_start" if action == "create-cancel-before-start" else "lookup_only"),
               catalog_complete=not catalog.issues, issues=[{"code": issue.code} for issue in catalog.issues])
        completed = (attempt.resolution_receipt_digest is not None if action == "create-resolve-not-started" else
                     attempt.result.outcome.execution is ExecutionState.NOT_STARTED if action == "create-cancel-before-start" else
                     attempt.execution_contract_satisfied)
        return ANSWERED if completed else REFUSED
    except ConnectorTransportError as error:
        output(action, status="not_done", diagnostic_code=error.code,
               phase=error.phase, delivery=error.delivery, next_step="inspect_retained_input_before_any_new_publication")
        return NOT_DONE
    except StoreCommitUnknown:
        output(action, status="not_done", diagnostic_code="store_commit_unknown",
               next_step="inspect_retained_input_before_any_new_publication")
        return NOT_DONE
    except StoreCorrupt:
        output(action, status="not_done", diagnostic_code="store_corrupt")
        return NOT_DONE
    except (StoreConflict, StoreUpgradeRequired, StoreNotFound) as error:
        code = {StoreConflict: "store_conflict", StoreUpgradeRequired: "explicit_create_upgrade_required",
                StoreNotFound: "stored_input_not_found"}.get(type(error), "store_refused")
        output(action, status="refused", diagnostic_code=code)
        return REFUSED
    except ConnectorPreparationError as error:
        output(action, status="refused", diagnostic_code=error.code, **_compiler_diagnostics(error))
        return REFUSED
    except (PublicationRefusal, DiscoveryError, CreatePublicationError, SavedExecutionError, StoredTypeReadbackError,
            ProjectSelectionError, GeometryRefusal) as error:
        output(action, status="refused", diagnostic_code=error.code)
        return REFUSED
    except (ProjectStoreError, ValueError, TypeError, OSError, UnicodeError):
        # Native/model/file exception strings are never terminal-safe diagnostics.
        output(action, status="not_done", diagnostic_code="publication_unavailable",
               next_step="inspect_retained_input_before_any_new_publication")
        return NOT_DONE
