"""Offline AP03 authoring harness; no serving or runtime registration.

Passing the scripted suite proves ``HARNESS_CONFORMANCE`` only.  It never
constitutes an ``AI_BENCHMARK_PASS``.
"""

from .case_tower54 import (
    initial_prompt,
    initial_source,
    scripted_run_header,
    tower54_case,
)
from .contracts import (
    BenchmarkCaseV0,
    BenchmarkContractError,
    BenchmarkReportV0,
    BenchmarkSuiteReportV0,
    ModelOutputV0,
    PromptEventV0,
    RunHeaderV0,
    TranscriptV0,
    WireExchangeV0,
)
from .harness import run_scripted_conformance
from .verifier import (
    TranscriptVerificationError,
    verify_transcript,
    verify_transcript_data,
)


__all__ = [
    "BenchmarkCaseV0", "BenchmarkContractError", "BenchmarkReportV0",
    "BenchmarkSuiteReportV0", "ModelOutputV0", "PromptEventV0",
    "RunHeaderV0", "TranscriptV0", "TranscriptVerificationError",
    "WireExchangeV0", "initial_prompt", "initial_source", "scripted_run_header",
    "run_scripted_conformance", "tower54_case", "verify_transcript",
    "verify_transcript_data",
]
