"""Closed names and limits for the offline AP03 authoring harness."""
from __future__ import annotations


CASE_SCHEMA = "kir-ai-authoring-benchmark-case/0"
RUN_HEADER_SCHEMA = "kir-ai-authoring-benchmark-run-header/0"
PROMPT_EVENT_SCHEMA = "kir-ai-authoring-benchmark-prompt-event/0"
MODEL_OUTPUT_SCHEMA = "kir-ai-authoring-benchmark-model-output/0"
WIRE_EXCHANGE_SCHEMA = "kir-ai-authoring-benchmark-wire-exchange/0"
TRANSCRIPT_SCHEMA = "kir-ai-authoring-benchmark-transcript/0"
REPORT_SCHEMA = "kir-ai-authoring-benchmark-report/0"
SUITE_REPORT_SCHEMA = "kir-ai-authoring-benchmark-suite-report/0"

HARNESS_VERSION = "kir-ai-authoring-harness/0"
CASE_ID = "tower-reshape-54-v0"
PROTOCOL_VERSION = "kir-ai/0"

REGISTRY_DIGEST = (
    "sha256:6e52099b84124ddc56d60759ef49a005"
    "fb7d0a12334cf00455785eec7e63fea7"
)
REGISTRY_CANONICAL_BYTES = 172_899

MAX_MODEL_ATTEMPTS = 32
MAX_CUMULATIVE_REQUEST_BYTES = 512_000
MAX_MODEL_VISIBLE_RESPONSE_BYTES = 1_000_000
MAX_UNIQUE_BUILD_ENTITIES = 64

ACTORS = ("ENVIRONMENT", "MODEL")
TERMINAL_STATES = (
    "COMPLETED",
    "DISQUALIFIED_CONTEXT_BYPASS",
    "FAILED",
)
REPORT_STATUSES = (
    "HARNESS_CONFORMANCE",
    "DISQUALIFIED_CONTEXT_BYPASS",
    "FAILED",
)

INITIAL_SOURCE_DIGEST = (
    "sha256:48cd30ce5226ca702990acfb3de6c097"
    "1dc0bec6d02bcfe806fa378aff891d4f"
)
INITIAL_BUILD_DIGEST = (
    "sha256:6b6374105fd5fd80e0103381b73dc266"
    "c9de9019ebdb8d2d7a8555582f7bb796"
)
PHASE_A_SOURCE_DIGEST = (
    "sha256:b548378b2049893ab6b867ffa3cd9296"
    "d2ade95349210bb28e4ef8d8c313c8a4"
)
PHASE_A_BUILD_DIGEST = (
    "sha256:1e74bcd2520425d8cdb3d208c882df43"
    "c2845e986a199e46ddb7145272e67c0d"
)
FINAL_SOURCE_DIGEST = (
    "sha256:caa3ec3ed9d0fb8a58363557c39edad2"
    "730f543d41918695b2d9dc1bdbbdabf3"
)
FINAL_BUILD_DIGEST = (
    "sha256:789a91fb9168a03fc12c9ca6b2aab9b"
    "790b0dfecbca0a700ced07be3d197a59d"
)


__all__ = [name for name in globals() if name.isupper()]
