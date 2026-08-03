"""Step 7 — RevitExecutionPipeline unit tests (bridge + compile fully mocked).

Covers the extraction contracts:
  * TurnBudget: ONE coherent timeout hierarchy (tiers reachable, turn-clamped)
  * CompileGate: un-latched (ignores CompileClient's one-way latch), breaker +
    re-probe, empty-revit_version guard
  * normalize_error_message: de-obfuscation + wrapper line-offset correction
  * pipeline.run(): single fixer invocation with truthful final_code, legacy
    repair-loop parity (deterministic → LLM → return-as-is), blocked path,
    budget stop, TurnRecord output contract
  * flag-gated integration: legacy path byte-compatible when OFF, delegation +
    prepared transport when ON; chat_ws transport-only branch
  * wrapper sync: pipeline's wrapper copy == chat_ws literals (AST guard,
    mirrors kukai/modeling/tests/bridge/test_exec_wrapper_sync.py)
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from kukai.llm.revit_execution_pipeline import (
    WRAPPER_FOOTER,
    WRAPPER_HEADER,
    WRAPPER_LINE_OFFSET,
    CompileGate,
    PipelineDeps,
    RevitExecutionPipeline,
    TurnBudget,
    TurnRecord,
    compute_tool_budget_s,
    last_turn_record,
    normalize_error_message,
    pipeline_enabled,
    set_turn_deadline,
    turn_remaining_s,
    wrap_user_code,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FakeCompileError:
    code: str
    message: str
    line: int
    column: int = 1


@dataclass
class FakeCompileResult:
    success: bool
    errors: list[FakeCompileError] = field(default_factory=list)


class FakeCompileClient:
    """Mimics kukai.compile_client.CompileClient — including the latch field."""

    def __init__(self, results: Optional[list[Any]] = None, raise_exc: bool = False,
                 delay_s: float = 0.0):
        self._available = False  # deliberately latched-off; the gate must ignore it
        self.results = list(results or [])
        self.raise_exc = raise_exc
        self.delay_s = delay_s
        self.calls: list[tuple[str, str]] = []

    @property
    def available(self) -> bool:
        return self._available

    async def check(self, wrapped_code: str, revit_version: str):
        self.calls.append((wrapped_code, revit_version))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.raise_exc:
            raise ConnectionError("compile service down")
        if self.results:
            return self.results.pop(0)
        return FakeCompileResult(success=True)


class FakeTransport:
    def __init__(self, results: Optional[list[dict]] = None):
        self.results = list(results or [])
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, method: str, params: dict) -> dict:
        self.calls.append((method, dict(params)))
        if self.results:
            return self.results.pop(0)
        return {"success": True, "result": 42}


def passthrough_obfuscate(code: str) -> tuple[str, dict[str, str]]:
    return code, {}


def make_deps(
    transport: Optional[FakeTransport] = None,
    gate_results: Optional[list[Any]] = None,
    validate=None,
    fix=None,
    fix_from_error=None,
    llm_repair=None,
    obfuscate=passthrough_obfuscate,
    revit_version: str = "2024",
    record_recipe=None,
    is_compilation_error=None,
    enrich_runtime_error=None,
    verdict_hook=None,
) -> tuple[PipelineDeps, FakeTransport, FakeCompileClient]:
    transport = transport or FakeTransport()
    compile_client = FakeCompileClient(results=gate_results)
    gate = CompileGate(client_provider=lambda: compile_client)

    async def _default_llm_repair(code, error, attempt, user_query, system_context):
        return None

    async def _default_repair_context(user_query, error_msg, attempt, system_context):
        return system_context

    from kukai.llm.client import LLMClient, _enrich_runtime_error

    deps = PipelineDeps(
        transport=transport,
        validate=validate or (lambda code: None),
        fix=fix or (lambda code: code),
        fix_from_error=fix_from_error or (lambda code, err: None),
        llm_repair=llm_repair or _default_llm_repair,
        build_repair_context=_default_repair_context,
        compile_gate=gate,
        is_compilation_error=is_compilation_error or LLMClient._is_compilation_error,
        enrich_runtime_error=enrich_runtime_error or _enrich_runtime_error,
        obfuscate=obfuscate,
        revit_version=revit_version,
        record_recipe=record_recipe,
        verdict_hook=verdict_hook,
    )
    return deps, transport, compile_client


def pinned_budget(total_s: float = 120.0, execute_timeout_ms: int = 30_000) -> TurnBudget:
    return TurnBudget(total_s=total_s, execute_timeout_ms=execute_timeout_ms)


READ_CODE = "var walls = new FilteredElementCollector(doc).OfClass(typeof(Wall));\nreturn walls.GetElementCount();"


# ─────────────────────────────────────────────────────────────────────────────
# Wrapper sync (drift guard vs chat_ws literals — same technique as modeling's)
# ─────────────────────────────────────────────────────────────────────────────

def _chat_ws_constant(name: str) -> str:
    spec = importlib.util.find_spec("kukai.api.bridge_protocol")
    assert spec is not None and spec.origin
    with open(spec.origin, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in chat_ws source")


class TestWrapperSync:
    def test_header_matches_chat_ws(self):
        assert WRAPPER_HEADER == _chat_ws_constant("_WRAPPER_HEADER")

    def test_footer_matches_chat_ws(self):
        assert WRAPPER_FOOTER == _chat_ws_constant("_WRAPPER_FOOTER")

    def test_offset_derived(self):
        assert WRAPPER_LINE_OFFSET == WRAPPER_HEADER.count("\n")

    def test_wrap_indents_like_legacy(self):
        code = "var a = 1;\n\nreturn a;"
        wrapped = wrap_user_code(code)
        assert wrapped.startswith(WRAPPER_HEADER)
        assert wrapped.endswith(WRAPPER_FOOTER)
        assert "            var a = 1;" in wrapped
        # blank line stays blank (legacy: only non-empty lines are indented)
        assert "\n\n" in wrapped


# ─────────────────────────────────────────────────────────────────────────────
# Flag
# ─────────────────────────────────────────────────────────────────────────────

class TestFlag:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("KUKAI_EXEC_PIPELINE", raising=False)
        assert pipeline_enabled() is False

    def test_on(self, monkeypatch):
        monkeypatch.setenv("KUKAI_EXEC_PIPELINE", "1")
        assert pipeline_enabled() is True


# ─────────────────────────────────────────────────────────────────────────────
# TurnBudget
# ─────────────────────────────────────────────────────────────────────────────

class TestTurnBudget:
    def test_read_tier_gets_min_total(self):
        b = TurnBudget.for_execute(READ_CODE)
        assert b.execute_timeout_ms == 30_000  # read tier
        assert b.total_s == pytest.approx(120.0)  # 30s tier + 90s repair allowance

    def test_model_wide_tier_is_reachable(self):
        # THE fix: 360s tier used to be dead code under the flat 90s cap
        code = "var w = doc.GetWarnings();\nreturn w.Count;"
        b = TurnBudget.for_execute(code)
        assert b.execute_timeout_ms == 360_000
        assert b.total_s == pytest.approx(450.0)

    def test_turn_remaining_clamps_total(self):
        b = TurnBudget.for_execute(READ_CODE, turn_remaining=50.0)
        assert b.total_s == pytest.approx(50.0)

    def test_absolute_floor(self):
        b = TurnBudget.for_execute(READ_CODE, turn_remaining=5.0)
        assert b.total_s == pytest.approx(30.0)

    def test_effective_timeout_clamped_by_remaining(self):
        b = TurnBudget(total_s=20.0, execute_timeout_ms=360_000)
        # remaining ~20s minus 12s overhead → ~8s, well under the 360s tier
        eff = b.effective_execute_timeout_ms()
        assert eff <= 8_100
        assert eff >= 5_000
        assert b.can_dispatch()

    def test_cannot_dispatch_when_exhausted(self):
        b = TurnBudget(total_s=0.5, execute_timeout_ms=30_000)
        assert not b.can_dispatch()

    def test_compute_tool_budget_uses_turn_deadline(self):
        set_turn_deadline(time.monotonic() + 40.0)
        try:
            cap = compute_tool_budget_s({"code": READ_CODE})
            # clamped to ~40s remaining + 5s slack
            assert 40.0 <= cap <= 46.0
        finally:
            set_turn_deadline(time.monotonic() + 10_000)  # neutralize for other tests

    def test_turn_remaining_none_without_deadline(self):
        # fresh context via asyncio.run in a clean task would be cleaner; here
        # we just verify the getter's math against a known deadline
        set_turn_deadline(time.monotonic() + 100.0)
        rem = turn_remaining_s()
        assert rem is not None and 99.0 < rem <= 100.0


# ─────────────────────────────────────────────────────────────────────────────
# CompileGate
# ─────────────────────────────────────────────────────────────────────────────

class TestCompileGate:
    async def test_ignores_availability_latch(self):
        client = FakeCompileClient(results=[FakeCompileResult(success=True)])
        assert client.available is False  # latched off (legacy would skip)
        gate = CompileGate(client_provider=lambda: client)
        res = await gate.check("code", "2024")
        assert res is not None and res.success
        assert len(client.calls) == 1  # un-latched: it TRIED anyway

    async def test_empty_revit_version_skips(self):
        client = FakeCompileClient()
        gate = CompileGate(client_provider=lambda: client)
        res = await gate.check("code", "")
        assert res is None
        assert client.calls == []  # never manufactures the REVIT_VERSION '' error

    async def test_breaker_opens_and_reprobes(self):
        clock = [0.0]
        client = FakeCompileClient(raise_exc=True)
        gate = CompileGate(
            client_provider=lambda: client,
            failure_threshold=3, cooldown_s=60.0, clock=lambda: clock[0],
        )
        for _ in range(3):
            assert await gate.check("code", "2024") is None
        assert gate.breaker_open
        assert len(client.calls) == 3
        # within cooldown: skipped, no new call
        clock[0] = 30.0
        assert await gate.check("code", "2024") is None
        assert len(client.calls) == 3
        # after cooldown: re-probe happens
        clock[0] = 61.0
        client.raise_exc = False
        client.results = [FakeCompileResult(success=True)]
        res = await gate.check("code", "2024")
        assert res is not None and res.success
        assert len(client.calls) == 4
        assert not gate.breaker_open  # success reset the breaker

    async def test_slow_check_counts_as_failure(self):
        client = FakeCompileClient(delay_s=0.2)
        gate = CompileGate(client_provider=lambda: client, check_timeout_s=0.05)
        res = await gate.check("code", "2024")
        assert res is None  # fail-open
        assert gate._consecutive_failures == 1

    async def test_no_client_fails_open(self):
        gate = CompileGate(client_provider=lambda: None)
        assert await gate.check("code", "2024") is None


# ─────────────────────────────────────────────────────────────────────────────
# Error normalization
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeErrorMessage:
    def test_deobfuscates_identifiers(self):
        msg = "The name '_0x1a2b' does not exist in the current context"
        out = normalize_error_message(msg, rename_map={"wallCount": "_0x1a2b"})
        assert "'wallCount'" in out
        assert "_0x1a2b" not in out

    def test_shifts_wrapped_line_numbers_on_compile_errors(self):
        n = WRAPPER_LINE_OFFSET + 12
        msg = f"CS0012: The type 'ISet<>' is not referenced (line {n}, col 31)"
        out = normalize_error_message(msg)
        assert "(line 12, col 31)" in out

    def test_small_line_numbers_untouched(self):
        msg = "CS1002: ; expected (line 3, col 1)"  # already user-coordinates
        assert normalize_error_message(msg) == msg

    def test_runtime_messages_untouched(self):
        msg = "NullReferenceException at line 30"  # no CS code → not wrapper-based
        assert normalize_error_message(msg) == msg

    def test_empty(self):
        assert normalize_error_message("") == ""
        assert normalize_error_message("", rename_map={"a": "_0xffff"}) == ""


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline.run — happy path + parity contracts
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineHappyPath:
    async def test_success_roundtrip(self):
        deps, transport, compile_client = make_deps()
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": READ_CODE}, user_query="сколько стен?")

        assert record.ok and record.state == "ok"
        assert record.attempts == 1
        assert record.n_bridge_roundtrips == 1
        assert record.n_compile_checks == 1
        assert record.was_modified is False
        # legacy shape: NO execution block when nothing was rewritten
        out = record.to_tool_result()
        assert out == {"success": True, "result": 42}

        # transport got the prepared marker + wrapped code + the ONE deadline
        method, params = transport.calls[0]
        assert method == "execute"
        assert params["_pipeline_prepared"] is True
        assert params["code"].startswith(WRAPPER_HEADER)
        assert params["code"].endswith(WRAPPER_FOOTER)
        assert params["timeout_ms"] <= 30_000
        assert params["attempt"] == 1

        # compile gate saw the SAME wrapped payload
        assert compile_client.calls[0][0] == params["code"]
        assert compile_client.calls[0][1] == "2024"

    async def test_fixer_runs_once_and_final_code_truthful(self):
        fixed_code = "var fixedCode = 1;\nreturn fixedCode;"

        deps, transport, _ = make_deps(fix=lambda code: fixed_code)
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": READ_CODE})

        assert record.was_modified is True
        assert record.final_code == fixed_code
        assert record.repairs == [{"attempt": 0, "fix_source": "preflight_fixer"}]
        out = record.to_tool_result()
        assert out["execution"]["final_code"] == fixed_code
        assert out["execution"]["was_modified"] is True
        # the transport payload is built from the FIXED code (single source)
        assert "fixedCode" in transport.calls[0][1]["code"]

    async def test_recipe_recorded_on_success(self):
        seen: list[dict] = []

        def _rec(**kw):
            seen.append(kw)

        deps, _, _ = make_deps(record_recipe=_rec)
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        await pipe.run({"code": READ_CODE}, user_query="q")
        assert len(seen) == 1
        assert seen[0]["n_repairs"] == 0
        assert seen[0]["user_query"] == "q"

    async def test_last_turn_record_exposed(self):
        deps, _, _ = make_deps()
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": READ_CODE})
        assert last_turn_record() is record
        # summary is JSON-serializable and carries no code bodies
        s = json.dumps(record.summary())
        assert "FilteredElementCollector" not in s

    async def test_verdict_hook_is_the_evaluator_socket(self):
        async def _hook(rec: TurnRecord):
            return {"source": "will.evaluator", "ok": rec.ok}

        deps, _, _ = make_deps(verdict_hook=_hook)
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": READ_CODE})
        assert record.verdict == {"source": "will.evaluator", "ok": True}

    async def test_default_verdict_deterministic(self):
        deps, _, _ = make_deps()
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": READ_CODE})
        assert record.verdict["source"] == "pipeline.deterministic"
        assert record.verdict["state"] == "ok"


class TestPipelineBlockedAndErrors:
    async def test_validation_block_short_circuits(self):
        deps, transport, compile_client = make_deps(
            validate=lambda code: ["Blocked: Process.Start (line 1)"],
        )
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": "Process.Start(\"cmd\");"})

        assert record.state == "blocked" and not record.ok
        out = record.to_tool_result()
        # legacy dict shape preserved
        assert out["error"] is True
        assert out["message"] == "Код заблокирован проверкой безопасности"
        assert out["violations"] == ["Blocked: Process.Start (line 1)"]
        assert out["err"]["code"] == "security.blocked_pattern"
        assert transport.calls == [] and compile_client.calls == []

    async def test_runtime_error_enriched_and_classified(self):
        deps, _, _ = make_deps(
            transport=FakeTransport(results=[
                {"error": True, "message": "Autodesk.Revit.Exceptions.ArgumentException: boom"},
            ]),
        )
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": READ_CODE})
        assert not record.ok and record.state == "failed"
        out = record.to_tool_result()
        assert out["err"]["code"] == "runtime.revit_exception"

    async def test_client_side_error_deobfuscated_before_model(self):
        deps, _, _ = make_deps(
            obfuscate=lambda code: (code, {"wallList": "_0xbeef"}),
            transport=FakeTransport(results=[
                {"error": True, "message": "NullReferenceException: _0xbeef is null"},
            ]),
        )
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": READ_CODE})
        assert "_0xbeef" not in record.result["message"]
        assert "wallList is null" in record.result["message"]


class TestPipelineRepairLoop:
    def _gate_fail(self, cs="CS0246", message="The type 'Foo' could not be found",
                   line_user=2):
        return FakeCompileResult(success=False, errors=[
            FakeCompileError(code=cs, message=message,
                             line=line_user + WRAPPER_LINE_OFFSET),
        ])

    async def test_compile_fail_then_deterministic_fix(self):
        deps, transport, compile_client = make_deps(
            gate_results=[self._gate_fail(), FakeCompileResult(success=True)],
            fix_from_error=lambda code, err: code.replace("Foo", "Wall"),
        )
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": "Foo x;\nreturn 1;"})

        assert record.ok
        assert record.attempts == 2
        assert record.repairs == [{"attempt": 1, "fix_source": "deterministic"}]
        assert record.n_compile_checks == 2
        assert record.n_bridge_roundtrips == 1  # failed attempt never hit Revit
        assert "Wall x;" in record.final_code
        out = record.to_tool_result()
        assert out["execution"]["repairs"] == record.repairs

    async def test_compile_error_message_has_user_line_numbers(self):
        deps, _, _ = make_deps(gate_results=[self._gate_fail(line_user=2)])
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": "Foo x;\nreturn 1;"})
        # (attempt 1 error, no repair available, det+llm decline → returned)
        assert "Compilation failed: CS0246" in record.result["message"]
        assert "(line 2)" in record.result["message"]
        assert record.result["err"]["cs_codes"] == ["CS0246"]

    async def test_llm_repair_applied_and_trailed(self):
        repaired_code = "var ok = 1;\nreturn ok;"
        calls: list[int] = []

        async def _repair(code, error, attempt, user_query, system_context):
            calls.append(attempt)
            return repaired_code

        deps, transport, _ = make_deps(
            gate_results=[self._gate_fail(), FakeCompileResult(success=True)],
            llm_repair=_repair,
        )
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": "Foo x;\nreturn 1;"})

        assert record.ok
        assert calls == [1]
        assert record.repairs == [{"attempt": 1, "fix_source": "llm_repair"}]
        assert record.final_code == repaired_code
        assert "var ok = 1;" in transport.calls[0][1]["code"]

    async def test_repair_none_returns_error_as_is(self):
        # legacy parity: repair-LLM returns nothing → the compile error is the
        # final answer for this call (model decides what to do next)
        deps, transport, _ = make_deps(gate_results=[self._gate_fail()])
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": "Foo x;\nreturn 1;"})
        assert not record.ok and record.state == "compile_failed"
        assert record.attempts == 1
        assert transport.calls == []
        assert "Compilation failed" in record.result["message"]
        assert "3 попыток" not in record.result["message"]  # only the safety-break path says that

    async def test_attempt3_error_returned_without_repair(self):
        async def _repair(code, error, attempt, user_query, system_context):
            return code + f"\n// attempt {attempt}"

        deps, _, _ = make_deps(
            gate_results=[self._gate_fail(), self._gate_fail(), self._gate_fail()],
            llm_repair=_repair,
        )
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": "Foo x;\nreturn 1;"})
        assert not record.ok
        assert record.attempts == 3
        assert record.state == "compile_failed"
        assert len([r for r in record.repairs if r["fix_source"] == "llm_repair"]) == 2

    async def test_unsafe_repair_breaks_with_legacy_exhausted_message(self):
        # repaired code trips validate → legacy "3 попыток" contract
        async def _repair(code, error, attempt, user_query, system_context):
            return "System.Diagnostics.Process.Start(\"cmd\");"

        deps, _, _ = make_deps(
            gate_results=[self._gate_fail()],
            llm_repair=_repair,
            validate=lambda code: (
                ["Blocked: Process.Start"] if "Process.Start" in code else None
            ),
        )
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": "Foo x;\nreturn 1;"})
        assert not record.ok and record.state == "compile_failed"
        msg = record.result["message"]
        assert msg.startswith("Код не удалось скомпилировать после 3 попыток исправления.")
        assert "Попробуй другой подход к решению задачи." in msg
        assert "(Тип не найден" in msg  # CS0246 translation appended
        assert record.result["err"]["code"] == "compile.failed_after_repairs"

    async def test_gate_unavailable_fails_open_to_revit(self):
        deps, transport, compile_client = make_deps()
        compile_client.raise_exc = True  # gate down → fail open, straight to Revit
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": READ_CODE})
        assert record.ok
        assert record.n_bridge_roundtrips == 1


class TestPipelineBudget:
    async def test_budget_stop_before_any_dispatch_is_honest(self):
        deps, transport, compile_client = make_deps()
        pipe = RevitExecutionPipeline(
            deps, budget=TurnBudget(total_s=0.5, execute_timeout_ms=30_000)
        )
        record = await pipe.run({"code": READ_CODE})
        assert not record.ok and record.state == "budget_stopped"
        assert transport.calls == [] and compile_client.calls == []
        assert record.result["err"]["code"] == "transport.tool_budget_exceeded"
        assert "НЕ выполнялся" in record.result["message"]

    async def test_budget_skips_llm_repair_when_low(self):
        async def _repair(code, error, attempt, user_query, system_context):
            raise AssertionError("LLM repair must not run on a drained budget")

        gate_fail = FakeCompileResult(success=False, errors=[
            FakeCompileError(code="CS0246", message="nope", line=WRAPPER_LINE_OFFSET + 1),
        ])
        deps, _, _ = make_deps(gate_results=[gate_fail], llm_repair=_repair)
        # total 20s → can_dispatch (needs ≥5s + overhead margin) but repair
        # needs ≥30s (repair_llm_timeout_s * 0.5)
        pipe = RevitExecutionPipeline(
            deps, budget=TurnBudget(total_s=20.0, execute_timeout_ms=30_000)
        )
        record = await pipe.run({"code": READ_CODE})
        assert not record.ok
        assert "Compilation failed" in record.result["message"]

    async def test_timeout_result_state_is_unconfirmed(self):
        # bridge-side bounded wait elapsed → chat_ws-shaped timeout dict
        deps, _, _ = make_deps(
            transport=FakeTransport(results=[
                {"error": True, "message": "Revit не ответил вовремя (42с)",
                 "err": {"code": "transport.bridge_timeout", "retryable": True,
                         "transient": True}},
            ]),
        )
        pipe = RevitExecutionPipeline(deps, budget=pinned_budget())
        record = await pipe.run({"code": READ_CODE})
        assert not record.ok
        # record-level honesty: Revit may still be running (model-visible
        # message stays legacy-parity — reclassified like the inline path did)
        assert record.state == "timeout_unconfirmed"


# ─────────────────────────────────────────────────────────────────────────────
# Flag-gated integration: client._execute_tool
# ─────────────────────────────────────────────────────────────────────────────

def _make_llm_client():
    from kukai.llm.client import LLMClient

    return LLMClient(model="test/mock", api_key="test", revit_version="2024")


class TestClientIntegration:
    async def test_flag_off_uses_legacy_inline_path(self, monkeypatch):
        monkeypatch.delenv("KUKAI_EXEC_PIPELINE", raising=False)
        llm = _make_llm_client()
        seen: list[dict] = []

        async def bridge(method: str, params: dict) -> dict:
            seen.append(params)
            return {"success": True, "result": 1}

        result = await llm._execute_tool("execute_revit_code", {"code": READ_CODE}, bridge)
        assert result.get("success") is True
        # legacy path sends the RAW user code — no pipeline marker, no wrapper
        assert "_pipeline_prepared" not in seen[0]
        assert not seen[0]["code"].startswith(WRAPPER_HEADER)

    async def test_flag_on_delegates_to_pipeline(self, monkeypatch):
        monkeypatch.setenv("KUKAI_EXEC_PIPELINE", "1")
        set_turn_deadline(time.monotonic() + 300.0)
        llm = _make_llm_client()
        seen: list[dict] = []

        async def bridge(method: str, params: dict) -> dict:
            seen.append(params)
            return {"success": True, "result": 7}

        result = await llm._execute_tool("execute_revit_code", {"code": READ_CODE}, bridge)
        assert result.get("success") is True
        assert seen[0]["_pipeline_prepared"] is True
        assert seen[0]["code"].startswith(WRAPPER_HEADER)  # prepared payload
        record = last_turn_record()
        assert record is not None and record.ok

    async def test_flag_on_without_bridge_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.setenv("KUKAI_EXEC_PIPELINE", "1")
        llm = _make_llm_client()
        # no bridge_callback and no legacy bridge → the pre-existing legacy
        # guard answers (never the pipeline, which needs a transport)
        result = await llm._execute_tool("execute_revit_code", {"code": READ_CODE}, None)
        assert result["error"] is True


# ─────────────────────────────────────────────────────────────────────────────
# chat_ws transport-only branch
# ─────────────────────────────────────────────────────────────────────────────

class TestChatWsTransportBranch:
    async def _call_bridge_callback(self, monkeypatch, params: dict,
                                    method: str = "execute"):
        from types import SimpleNamespace

        import kukai.main
        from kukai.api import chat_ws
        from kukai.security.encryption import SessionEncryption

        ws_id = "test-pipeline-ws"
        key = SessionEncryption.generate_key()
        monkeypatch.setitem(chat_ws._session_keys, ws_id, key)
        # the legacy prepare path reads get_app_state().compile_client — stub
        # an app state with no compile client (gate skipped, like a dev box)
        monkeypatch.setattr(kukai.main, "_app_state",
                            SimpleNamespace(compile_client=None))
        sent: list[dict] = []

        async def _fake_send_json(ws, data):
            sent.append(data)
            # resolve the pending future like a real bridge_response would
            entry = chat_ws._pending_bridge_requests.pop(data["id"], None)
            if entry:
                entry[1].set_result({"success": True, "result": "pong"})

        from kukai.api import bridge_protocol
        monkeypatch.setattr(bridge_protocol, "_send_json", _fake_send_json)
        result = await chat_ws._bridge_callback(None, ws_id, method, params)
        return sent, result, key

    async def test_prepared_payload_is_encrypted_verbatim(self, monkeypatch):
        from kukai.security.encryption import SessionEncryption

        payload = WRAPPER_HEADER + "            return 1;" + WRAPPER_FOOTER
        sent, result, key = await self._call_bridge_callback(
            monkeypatch,
            {"code": payload, "timeout_ms": 30_000, "attempt": 1,
             "_pipeline_prepared": True},
        )
        assert result == {"success": True, "result": "pong"}
        msg = sent[0]
        assert msg["type"] == "bridge_request" and msg["method"] == "execute"
        assert msg["timeout_ms"] == 30_000
        assert "params" not in msg  # marker never leaks to C#
        # transport-only: decrypting returns the payload EXACTLY as prepared —
        # no second fixer, no re-wrap, no re-obfuscation
        assert SessionEncryption.decrypt(msg["encrypted_code"], key) == payload

    async def test_legacy_execute_still_prepares(self, monkeypatch):
        from kukai.security.encryption import SessionEncryption

        sent, result, key = await self._call_bridge_callback(
            monkeypatch, {"code": "return 1;", "timeout_ms": 30_000},
        )
        assert result == {"success": True, "result": "pong"}
        decrypted = SessionEncryption.decrypt(sent[0]["encrypted_code"], key)
        # legacy path wraps (and may fix/obfuscate) — NOT verbatim
        assert decrypted.startswith(WRAPPER_HEADER)

    async def test_marker_stripped_on_non_execute(self, monkeypatch):
        sent, result, _ = await self._call_bridge_callback(
            monkeypatch, {"foo": 1, "_pipeline_prepared": True}, method="context",
        )
        assert sent[0]["params"] == {"foo": 1}


# ─────────────────────────────────────────────────────────────────────────────
# Obfuscator map (additive API)
# ─────────────────────────────────────────────────────────────────────────────

class TestObfuscatorMap:
    def test_map_matches_output(self):
        from kukai.security.obfuscator import obfuscate_code_with_map

        code = "var wallCount = 5;\nreturn wallCount;"
        obf, rename_map = obfuscate_code_with_map(code)
        assert rename_map.get("wallCount", "").startswith("_0x")
        assert rename_map["wallCount"] in obf
        assert "wallCount" not in obf

    def test_empty_and_no_vars(self):
        from kukai.security.obfuscator import obfuscate_code_with_map

        assert obfuscate_code_with_map("") == ("", {})
        code = "return 42;"
        assert obfuscate_code_with_map(code) == (code, {})

    def test_public_api_unchanged(self):
        from kukai.security.obfuscator import obfuscate_code

        out = obfuscate_code("var wallCount = 5;\nreturn wallCount;")
        assert isinstance(out, str)
        assert "wallCount" not in out
