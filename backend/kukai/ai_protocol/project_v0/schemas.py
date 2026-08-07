"""Closed schema names and resource limits for AP02-K.

These constants describe a transport-neutral kernel.  They are deliberately
not registered in the AP-01 wire registry.
"""
from __future__ import annotations


PROJECT_READ_COMMAND_SCHEMA = "kir-ai-project-read-command/0"
MODEL_QUERY_COMMAND_SCHEMA = "kir-ai-model-query-command/0"
SOURCE_PATCH_COMMAND_SCHEMA = "kir-ai-source-patch-command/0"

MODULE_PUT_SCHEMA = "kir-ai-module-put/0"
ROOT_PUT_SCHEMA = "kir-ai-root-put/0"
EXCEPTION_PUT_SCHEMA = "kir-ai-exception-put/0"
EXCEPTION_REMOVE_SCHEMA = "kir-ai-exception-remove/0"

PROJECT_READ_RESULT_SCHEMA = "kir-ai-project-read-result/0"
MODEL_QUERY_RESULT_SCHEMA = "kir-ai-model-query-result/0"
SOURCE_PATCH_RESULT_SCHEMA = "kir-ai-source-patch-result/0"
COVERAGE_SCHEMA = "kir-ai-project-coverage/0"
READ_RECEIPT_SCHEMA = "kir-ai-project-read-receipt/0"
RECEIPT_REF_SCHEMA = "kir-ai-project-read-receipt-ref/0"
CURSOR_RECORD_SCHEMA = "kir-ai-model-query-cursor/0"
CURSOR_REF_SCHEMA = "kir-ai-model-query-cursor-ref/0"
PROJECT_STATE_SCHEMA = "kir-ai-project-state/0"
PATCH_OUTCOME_SCHEMA = "kir-ai-patch-outcome-record/0"
SEMANTIC_PATCH_SCHEMA = "kir-ai-semantic-patch/0"

MAX_LOGICAL_WIRE_BYTES = 4_000_000
MAX_LOGICAL_DEPTH = 128
MAX_ARGUMENT_BYTES = 1_000_000
MAX_RESULT_BYTES = 2_000_000
MAX_PAGE_ITEMS = 128
MAX_PAGE_BYTES = 1_000_000
MAX_PATCH_OPS = 128
MAX_RECEIPT_REFS = 256
MAX_REVISIONS = 256
MAX_RECEIPTS = 8_192
MAX_CURSORS = 4_096
MAX_PATCH_OUTCOMES = 256

PROJECT_READ_SCOPES = (
    "exception",
    "exception.index",
    "manifest",
    "module",
    "module.index",
    "root_instance",
)
MODEL_QUERY_SCOPES = ("logical_id", "origin", "summary")
ORIGIN_FILTER_FIELDS = (
    "call_id",
    "instance_id",
    "module_id",
    "occurrence_key",
    "slot_id",
)
PATCH_OPERATION_SCHEMAS = (
    MODULE_PUT_SCHEMA,
    ROOT_PUT_SCHEMA,
    EXCEPTION_PUT_SCHEMA,
    EXCEPTION_REMOVE_SCHEMA,
)


__all__ = [name for name in globals() if name.isupper()]
