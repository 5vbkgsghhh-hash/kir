"""End-to-end benchmark runner — RAGPath + LLM + Roslyn compile-check.

Measures the metrics that retrieval-only mode cannot:
- first_compile_ok: did the LLM's first attempt compile?
- repair_attempts_used: how many repair iterations consumed?
- e2e_success: did final code compile within 3 attempts?

The runner is a faithful reproduction of the production execute_revit_code
flow, minus the bridge round-trip (compile only — never executes in Revit).

LLM provider: OpenRouter only (per project policy for tests). Reads
KUKAI_LLM_FALLBACK_API_KEY and KUKAI_LLM_API_BASE from env. No fallbacks —
if OpenRouter is unavailable, the runner errors out cleanly.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from kukai.compile_client import CompileClient
from kukai.rag.benchmark.gold_set import GoldQuery
from kukai.rag.benchmark.metrics import QueryResult, summarize
from kukai.rag.benchmark.paths.base import RAGPath
from kukai.rag.benchmark.runner import BenchmarkRun

logger = logging.getLogger(__name__)


# Wrapper for compile-check — must match chat_ws.py production wrapper.
_WRAPPER_HEADER = (
    "using System;\n"
    "using System.Linq;\n"
    "using System.Collections.Generic;\n"
    "using System.Text;\n"
    "using System.Text.RegularExpressions;\n"
    "using Autodesk.Revit.DB;\n"
    "using Autodesk.Revit.DB.Architecture;\n"
    "using Autodesk.Revit.DB.Structure;\n"
    "using Autodesk.Revit.DB.Mechanical;\n"
    "using Autodesk.Revit.DB.Electrical;\n"
    "using Autodesk.Revit.DB.Plumbing;\n"
    "using Autodesk.Revit.UI;\n"
    "\n"
    "namespace Kukai\n"
    "{\n"
    "    public class UserCode\n"
    "    {\n"
    "        public static object Execute(Document doc, UIDocument uidoc)\n"
    "        {\n"
)
_WRAPPER_FOOTER = "\n        }\n    }\n}\n"


@dataclass
class LlmRunnerConfig:
    revit_version: str = "2026"
    max_repair_attempts: int = 3
    # Model-agnostic by policy (IRON 6): never bake a provider/model id into the
    # tissue. None means "resolve from env at call time" — see
    # ``e2e.resolve_model`` ($KUKAI_BENCH_LLM_MODEL → $KUKAI_LLM_MODEL). A run
    # that never sets a model fails loudly rather than silently picking one.
    llm_model: Optional[str] = None
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096
    llm_timeout: float = 60.0
    compile_url: str = "http://localhost:52412"


def _wrap_for_compile(code: str) -> str:
    """Wrap user-method-body code in the same Kukai.UserCode shell production uses."""
    indented = "\n".join(
        "            " + line if line.strip() else line for line in code.split("\n")
    )
    return _WRAPPER_HEADER + indented + _WRAPPER_FOOTER


async def _llm_generate(
    prompt: str,
    user_query: str,
    config: LlmRunnerConfig,
) -> str:
    """One LLM call via OpenRouter — returns C# code (method body only).

    System prompt = path's enrichment text + minimal instructions.
    User message = user query.
    No tool-calling — bench measures retrieval-quality-driven generation, not agent loops.
    """
    import litellm

    model = config.llm_model or os.environ.get("KUKAI_BENCH_LLM_MODEL") or os.environ.get(
        "KUKAI_LLM_MODEL"
    )
    if not model:
        raise RuntimeError(
            "no benchmark model resolved — set LlmRunnerConfig.llm_model or "
            "$KUKAI_BENCH_LLM_MODEL / $KUKAI_LLM_MODEL. Refusing to guess a "
            "model id (model-agnostic rule, IRON 6)."
        )

    api_key = os.environ.get("KUKAI_LLM_FALLBACK_API_KEY", "")
    api_base = os.environ.get("KUKAI_LLM_API_BASE", "https://openrouter.ai/api/v1")
    if not api_key:
        raise RuntimeError(
            "KUKAI_LLM_FALLBACK_API_KEY missing — required for benchmark LLM calls."
        )

    system = (
        "You write Revit API C# code. Output ONLY the method body (no using, "
        "no namespace, no class, no markdown fences). The method signature is "
        "`public static object Execute(Document doc, UIDocument uidoc)`. "
        "Always end with a return statement.\n\n"
        + prompt
    )

    response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_query},
        ],
        temperature=config.llm_temperature,
        max_tokens=config.llm_max_tokens,
        timeout=config.llm_timeout,
        api_key=api_key,
        api_base=api_base,
        stream=False,
    )

    text = response.choices[0].message.content or ""
    # Strip markdown fences if model leaks them
    text = text.strip()
    if text.startswith("```"):
        # Find first newline after the fence and drop it
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1 :]
    if text.endswith("```"):
        text = text[: -3].rstrip()
    return text


async def _compile(
    code: str,
    config: LlmRunnerConfig,
    client: CompileClient,
) -> tuple[bool, list[dict[str, Any]]]:
    """Wrap + compile via Roslyn service. Returns (success, errors_list)."""
    wrapped = _wrap_for_compile(code)
    result = await client.check(wrapped, config.revit_version)
    if result is None:
        # Service unavailable — treat as ambiguous (caller should detect)
        return False, [{"code": "SERVICE", "message": "Compile service unavailable", "line": 0}]
    if result.success:
        return True, []
    errors = [
        {"code": e.code, "message": e.message, "line": e.line, "column": e.column}
        for e in result.errors
    ]
    return False, errors


async def run_path_e2e(
    path: RAGPath,
    gold: list[GoldQuery],
    config: Optional[LlmRunnerConfig] = None,
    context: Optional[dict[str, Any]] = None,
) -> BenchmarkRun:
    """Full E2E: enrich → LLM → compile → repair_hint loop → record metrics.

    Slow (~30s/query), expensive (LLM tokens), but the only way to measure
    first_compile_ok and e2e_success — the metrics that ultimately matter.
    """
    config = config or LlmRunnerConfig()
    compile_client = CompileClient(base_url=config.compile_url)

    if not await compile_client.health():
        raise RuntimeError(
            f"Compile service not reachable at {config.compile_url} — "
            "start backend/compile-service before running E2E benchmark."
        )

    per_query: list[QueryResult] = []

    for q in gold:
        t_start = time.perf_counter()

        # Stage 1: retrieve + enrich
        try:
            rag_result = path.enrich(q.query, context=context)
        except Exception as exc:
            logger.exception("Path %s enrich failed on query: %s", path.name, q.query)
            per_query.append(_failed_result(q, path.name, str(exc), t_start))
            continue

        retrieval_ms = float(rag_result.metadata.get("latency_ms", 0.0))

        # Stage 2: generation + compile loop with repair
        first_compile_ok: Optional[bool] = None
        repair_iters = 0
        e2e_success = False
        final_code: Optional[str] = None
        final_error: Optional[str] = None

        current_code: Optional[str] = None
        last_errors: list[dict[str, Any]] = []
        repair_extra = ""  # appended to system prompt on repair iterations

        for attempt in range(1, config.max_repair_attempts + 1):
            try:
                full_prompt = rag_result.prompt_text
                if repair_extra:
                    full_prompt = full_prompt + "\n\n" + repair_extra

                current_code = await _llm_generate(full_prompt, q.query, config)
                ok, errors = await _compile(current_code, config, compile_client)

                if attempt == 1:
                    first_compile_ok = ok

                if ok:
                    e2e_success = True
                    break

                last_errors = errors
                # Try repair_hint if path provides it (Path C does, A and B return None)
                hint = path.repair_hint(
                    query=q.query,
                    failed_code=current_code,
                    compile_errors=errors,
                    context=context,
                )
                if hint:
                    repair_extra = hint.extra_context
                else:
                    # Generic text-only repair hint
                    err_text = "; ".join(
                        f"{e['code']}: {e['message'][:120]}" for e in errors[:3]
                    )
                    repair_extra = (
                        f"PREVIOUS ATTEMPT FAILED. Compile errors: {err_text}\n"
                        "Fix only what's broken. Output the corrected method body."
                    )
                repair_iters = attempt  # consumed this attempt for repair

            except Exception as exc:
                final_error = f"LLM/compile error on attempt {attempt}: {exc}"
                logger.exception("LLM run failed on query: %s", q.query)
                break

        if not e2e_success and last_errors:
            final_error = "; ".join(
                f"{e['code']}: {e['message'][:80]}" for e in last_errors[:2]
            )

        total_ms = (time.perf_counter() - t_start) * 1000.0

        # Reuse retrieval-only Hit@K + api_coverage logic
        hit_at_1 = False
        hit_at_5 = False
        if q.expected_snippet_ids:
            top1 = rag_result.retrieved_ids[:1]
            top5 = rag_result.retrieved_ids[:5]
            hit_at_1 = any(q.matches_id(rid) for rid in top1)
            hit_at_5 = any(q.matches_id(rid) for rid in top5)

        if q.expected_apis:
            retrieved_set = {a.lower() for a in rag_result.retrieved_apis}
            matched = sum(1 for api in q.expected_apis if api.lower() in retrieved_set)
            api_cov = matched / len(q.expected_apis)
        else:
            api_cov = 0.0

        per_query.append(
            QueryResult(
                query=q.query,
                path_name=path.name,
                hit_at_1=hit_at_1,
                hit_at_5=hit_at_5,
                api_coverage=api_cov,
                first_compile_ok=first_compile_ok,
                repair_attempts_used=repair_iters,
                e2e_success=e2e_success,
                retrieval_latency_ms=retrieval_ms,
                total_latency_ms=total_ms,
                retrieved_ids=rag_result.retrieved_ids[:10],
                final_code=current_code,
                final_error=final_error,
            )
        )

    await compile_client.close()

    return BenchmarkRun(
        path_name=path.name,
        summary=summarize(path.name, per_query),
        per_query=per_query,
    )


def _failed_result(
    q: GoldQuery, path_name: str, error: str, t_start: float
) -> QueryResult:
    total_ms = (time.perf_counter() - t_start) * 1000.0
    return QueryResult(
        query=q.query,
        path_name=path_name,
        hit_at_1=False,
        hit_at_5=False,
        api_coverage=0.0,
        first_compile_ok=False,
        repair_attempts_used=0,
        e2e_success=False,
        retrieval_latency_ms=0.0,
        total_latency_ms=total_ms,
        final_error=error[:300],
    )
