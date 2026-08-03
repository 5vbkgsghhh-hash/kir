"""RecordingBridgeClient / RecordingCompileClient / RecordingLLMClient unit tests."""
from __future__ import annotations
import json
from pathlib import Path
import pytest

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient
from kukai.modeling.bridge.recording_client import (
    RecordingBridgeClient, RecordingCompileClient, RecordingLLMClient,
)
from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult, InlineRagCitation,
    LLMPromptInputs,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec


def _checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _sample_proposal(task_id: str = "tid_a") -> CodeProposal:
    return CodeProposal(
        task_id=task_id,
        csharp_code="// RAG:#snip_a\n__result__ = new int[] { 1 };",
        explanation="ok",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Place column",
        revit_version="2026",
        failure_mode_checks=_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip_a", api_called="NewFamilyInstance")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
    )


@pytest.mark.asyncio
async def test_recording_bridge_writes_jsonl(tmp_path: Path):
    rec = RecordingBridgeClient(upstream=MockBridgeClient(), project_id="proj_X", corpus_dir=tmp_path)
    out = await rec.execute_code("sess_1", "// some C#", expected_count=1)
    assert out["success"] is True
    files = list((tmp_path / "proj_X").glob("*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text("utf-8").strip().splitlines()[0])
    assert record["kind"] == "execute_code"
    assert record["request"]["session_id"] == "sess_1"


@pytest.mark.asyncio
async def test_recording_compile_writes_jsonl(tmp_path: Path):
    rec = RecordingCompileClient(upstream=MockCompileClient(), project_id="proj_X", corpus_dir=tmp_path)
    assert (await rec.compile("class C {}")).success is True
    record = json.loads(list((tmp_path / "proj_X").glob("*.jsonl"))[0].read_text("utf-8").strip().splitlines()[0])
    assert record["kind"] == "compile"
    assert record["request"]["code"] == "class C {}"


@pytest.mark.asyncio
async def test_recording_llm_writes_jsonl(tmp_path: Path):
    upstream = MockLLMClient()
    upstream.queue_proposal(_sample_proposal("tid_a"))
    rec = RecordingLLMClient(upstream=upstream, project_id="proj_X", corpus_dir=tmp_path)
    inputs = LLMPromptInputs(
        persona_prompt="P", skill_content="S",
        task_brief_json='{"task_id":"tid_a"}',
        rag_snippets=[], failure_catalog_summary="F",
    )
    out = await rec.generate_code_proposal(inputs)
    assert out.task_id == "tid_a"
    record = json.loads(list((tmp_path / "proj_X").glob("*.jsonl"))[0].read_text("utf-8").strip().splitlines()[0])
    assert record["kind"] == "generate_code_proposal"
    assert record["response"]["task_id"] == "tid_a"


from kukai.modeling.bridge.replay_client import (
    ReplayBridgeClient, ReplayCompileClient, ReplayLLMClient, ReplayMissError,
)


@pytest.mark.asyncio
async def test_replay_bridge_returns_recorded(tmp_path: Path):
    rec = RecordingBridgeClient(upstream=MockBridgeClient(), project_id="p", corpus_dir=tmp_path)
    await rec.execute_code("s1", "// code A", expected_count=1)
    replay = ReplayBridgeClient(log_path=rec.log_path)
    out = await replay.execute_code("s1", "// code A", expected_count=1)
    assert out["success"] is True


@pytest.mark.asyncio
async def test_replay_bridge_miss_raises(tmp_path: Path):
    rec = RecordingBridgeClient(upstream=MockBridgeClient(), project_id="p", corpus_dir=tmp_path)
    await rec.execute_code("s1", "// code A", expected_count=1)
    replay = ReplayBridgeClient(log_path=rec.log_path)
    with pytest.raises(ReplayMissError):
        await replay.execute_code("s1", "// code B", expected_count=1)


@pytest.mark.asyncio
async def test_replay_compile_roundtrip(tmp_path: Path):
    rec = RecordingCompileClient(upstream=MockCompileClient(), project_id="p", corpus_dir=tmp_path)
    await rec.compile("class C {}")
    replay = ReplayCompileClient(log_path=rec.log_path)
    assert (await replay.compile("class C {}")).success is True


@pytest.mark.asyncio
async def test_replay_compile_preserves_error_message(tmp_path: Path):
    """Fix E: ReplayCompileClient must reconstruct the typed CompileError
    list from the recorded legacy `error` string. Previously the constructor
    passed `error=...` to CompileResult — but `error` is a @property, not a
    pydantic field, so pydantic v2 silently dropped it and every replayed
    failure surfaced as `result.error == None`. Repair loops couldn't reflect
    and corpus regression suites asserted the wrong invariant.
    """
    # Record a failure response. MockCompileClient with a scripted
    # `error="..."` produces a typed errors list internally; the recorder
    # serializes back to the legacy `error` field on disk (see recording_client
    # line 85). Replay must re-inflate it as a typed CompileError.
    upstream = MockCompileClient(responses=[
        {"success": False, "error": "CS1002: ; expected"},
    ])
    rec = RecordingCompileClient(upstream=upstream, project_id="p", corpus_dir=tmp_path)
    out = await rec.compile("bad code")
    assert out.success is False
    assert out.error == "CS1002: ; expected"          # round-trip sanity

    replay = ReplayCompileClient(log_path=rec.log_path)
    result = await replay.compile("bad code")
    assert result.success is False
    assert len(result.errors) == 1
    assert result.errors[0].code == "REPLAY"
    assert result.errors[0].message == "CS1002: ; expected"
    # Back-compat @property must still resolve to the first error's message.
    assert result.error == "CS1002: ; expected"


@pytest.mark.asyncio
async def test_replay_llm_roundtrip(tmp_path: Path):
    upstream = MockLLMClient()
    upstream.queue_proposal(_sample_proposal("tid_a"))
    rec = RecordingLLMClient(upstream=upstream, project_id="p", corpus_dir=tmp_path)
    inputs = LLMPromptInputs(persona_prompt="P", skill_content="S",
                              task_brief_json='{"task_id":"tid_a"}', rag_snippets=[],
                              failure_catalog_summary="F")
    await rec.generate_code_proposal(inputs)
    replay = ReplayLLMClient(log_path=rec.log_path)
    assert (await replay.generate_code_proposal(inputs)).task_id == "tid_a"
