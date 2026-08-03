"""Replay proxies that read a JSONL recording and re-emit responses.

Replay key construction is narrow: hash only fields that materially affect
the response (no timestamps, no token counts). A miss raises ReplayMissError
— never falls through to a live call.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any

from kukai.modeling.schemas.execution import CompileError, CompileResult
from kukai.modeling.schemas.llm import CodeProposal, LLMPromptInputs


class ReplayMissError(RuntimeError):
    """Raised when a request has no recorded response."""


def _h(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8")); h.update(b"\x1f")
    return h.hexdigest()


def _load(log_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log_path.read_text("utf-8").splitlines() if line.strip()]


class ReplayBridgeClient:
    def __init__(self, log_path: Path):
        self._records = _load(log_path)
        self._log_path = log_path

    async def list_sessions(self) -> list[str]:
        for rec in self._records:
            if rec["kind"] == "list_sessions":
                return list(rec["response"].get("sessions", []))
        raise ReplayMissError(f"no list_sessions record in {self._log_path}")

    async def execute_code(self, session_id: str, csharp_code: str, expected_count: int = 1) -> dict[str, Any]:
        key = _h("execute_code", session_id, csharp_code, str(expected_count))
        for rec in self._records:
            if rec["kind"] != "execute_code":
                continue
            r = rec["request"]
            if _h("execute_code", r["session_id"], r["code"], str(r["expected_count"])) == key:
                return dict(rec["response"])
        raise ReplayMissError(
            f"execute_code miss session={session_id!r} expected={expected_count} "
            f"code_hash={hashlib.sha256(csharp_code.encode()).hexdigest()[:16]}"
        )


class ReplayCompileClient:
    def __init__(self, log_path: Path):
        self._records = _load(log_path)

    async def compile(self, csharp_code: str, revit_version: str = "2026") -> CompileResult:
        key = _h("compile", csharp_code)
        for rec in self._records:
            if rec["kind"] != "compile":
                continue
            if _h("compile", rec["request"]["code"]) == key:
                r = rec["response"]
                # Fix E: CompileResult.error is a @property, not a settable
                # field — passing `error=...` is silently dropped by pydantic
                # v2, so every replayed failure used to surface as "no error".
                # Mirror the pattern from MockCompileClient: legacy `error`
                # string -> typed CompileError list under the new `errors` field.
                errors_data = r.get("errors")
                if errors_data is None and r.get("error"):
                    errors_data = [{"code": "REPLAY", "message": r["error"],
                                    "line": 0, "column": 0}]
                errors_data = errors_data or []
                return CompileResult(
                    success=bool(r["success"]),
                    code=r.get("code"),
                    assembly_id=r.get("assembly_id"),
                    errors=[CompileError.model_validate(e) for e in errors_data],
                )
        raise ReplayMissError(f"compile miss code_hash={hashlib.sha256(csharp_code.encode()).hexdigest()[:16]}")

    async def health(self) -> bool:
        return True


class ReplayLLMClient:
    def __init__(self, log_path: Path):
        self._records = _load(log_path)

    async def generate_code_proposal(self, inputs: LLMPromptInputs) -> CodeProposal:
        key = _h("llm", inputs.task_brief_json, ",".join(sid for sid, _, _ in inputs.rag_snippets))
        for rec in self._records:
            if rec["kind"] != "generate_code_proposal":
                continue
            r = rec["request"]
            if _h("llm", r["task_brief_json"], ",".join(r.get("rag_snippet_ids", []))) == key:
                return CodeProposal.model_validate(rec["response"])
        raise ReplayMissError(
            f"llm miss task_brief_hash={hashlib.sha256(inputs.task_brief_json.encode()).hexdigest()[:16]}"
        )
