from __future__ import annotations

import json

import pytest

from kukai.ai_protocol.authoring_benchmark_v0.harness import (
    run_scripted_conformance,
)
from kukai.ai_protocol.authoring_benchmark_v0.verifier import (
    verify_transcript_data,
)
from kukai.design_source import canonical_bytes


@pytest.fixture(scope="session")
def conformance_transcript():
    return run_scripted_conformance()


@pytest.fixture(scope="session")
def conformance_report(conformance_transcript):
    return verify_transcript_data(conformance_transcript.to_data())


@pytest.fixture
def transcript_data(conformance_transcript):
    return json.loads(canonical_bytes(conformance_transcript.to_data()))
