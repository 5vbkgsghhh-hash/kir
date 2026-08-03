"""Recording proxies that mirror BridgeClient / CompileClient / LLMClient
and append every (request, response) pair to JSONL under
`<corpus_dir>/<project_id>/<utc-iso-timestamp>.jsonl`. Inspired by Waymo
replay testing + Braintrust trace-to-dataset. Recordings become permanent
regressions via the Replay* wrappers.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from kukai.modeling.schemas.execution import CompileResult
from kukai.modeling.schemas.llm import CodeProposal, LLMPromptInputs


class BridgeClientProtocol(Protocol):
    async def list_sessions(self) -> list[str]: ...
    async def execute_code(self, session_id: str, csharp_code: str, expected_count: int = 1) -> dict[str, Any]: ...


class CompileClientProtocol(Protocol):
    async def compile(self, csharp_code: str, revit_version: str = ...) -> CompileResult: ...
    async def health(self) -> bool: ...


class LLMClientProtocol(Protocol):
    async def generate_code_proposal(self, inputs: LLMPromptInputs) -> CodeProposal: ...


def _new_log_path(corpus_dir: Path, project_id: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    path = corpus_dir / project_id / f"{stamp}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def _append(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        fh.write("\n")


class RecordingBridgeClient:
    def __init__(self, upstream: BridgeClientProtocol, project_id: str, corpus_dir: Path):
        self._upstream = upstream
        self._project_id = project_id
        self._log_path = _new_log_path(corpus_dir, project_id)

    @property
    def log_path(self) -> Path:
        return self._log_path

    async def list_sessions(self) -> list[str]:
        result = await self._upstream.list_sessions()
        _append(self._log_path, {"kind": "list_sessions", "request": {}, "response": {"sessions": list(result)}})
        return result

    async def execute_code(self, session_id: str, csharp_code: str, expected_count: int = 1) -> dict[str, Any]:
        response = await self._upstream.execute_code(session_id, csharp_code, expected_count)
        _append(self._log_path, {
            "kind": "execute_code",
            "request": {"session_id": session_id, "code": csharp_code, "expected_count": expected_count},
            "response": dict(response),
        })
        return response


class RecordingCompileClient:
    def __init__(self, upstream: CompileClientProtocol, project_id: str, corpus_dir: Path):
        self._upstream = upstream
        self._project_id = project_id
        self._log_path = _new_log_path(corpus_dir, project_id)

    @property
    def log_path(self) -> Path:
        return self._log_path

    async def compile(self, csharp_code: str, revit_version: str = "2026") -> CompileResult:
        # Fix D (Wave 1) added `revit_version` to every CompileClient.compile signature
        # so multi-version tasks route to the right Roslyn reference set. The recording
        # client now mirrors that — the kwarg is forwarded to the upstream client and
        # captured in the JSONL record for audit + downstream replay.
        result = await self._upstream.compile(csharp_code, revit_version=revit_version)
        _append(self._log_path, {
            "kind": "compile",
            "request": {"code": csharp_code, "revit_version": revit_version},
            "response": {"success": result.success, "assembly_id": result.assembly_id,
                         "error": result.error, "code": result.code},
        })
        return result

    async def health(self) -> bool:
        return await self._upstream.health()


class RecordingLLMClient:
    def __init__(self, upstream: LLMClientProtocol, project_id: str, corpus_dir: Path):
        self._upstream = upstream
        self._project_id = project_id
        self._log_path = _new_log_path(corpus_dir, project_id)

    @property
    def log_path(self) -> Path:
        return self._log_path

    async def generate_code_proposal(self, inputs: LLMPromptInputs) -> CodeProposal:
        proposal = await self._upstream.generate_code_proposal(inputs)
        _append(self._log_path, {
            "kind": "generate_code_proposal",
            "request": {
                "task_brief_json": inputs.task_brief_json,
                "skill_content_len": len(inputs.skill_content),
                "rag_snippet_ids": [sid for sid, _, _ in inputs.rag_snippets],
            },
            "response": json.loads(proposal.model_dump_json()),
        })
        return proposal
