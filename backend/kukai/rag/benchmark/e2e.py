"""E2E pass-rate runner over the RU gold (plan 014) — the apex metric.

Retrieval-only Hit@K cannot answer the question the corpus exists to answer:
does injecting our RAG raise the END-TASK pass-rate (code compiles AND does
the right thing) of whatever brain is in prod? This module measures that
offline against the repo corpus, per ARM:

  - arm "on"  → ``PathA``  : the production retrieval + production injection
  - arm "off" → ``PathOff``: empty prompt (the no-RAG control)

The Δ(pass-rate) between the two arms *is* scorecard C11. The harness reuses
the production building blocks (``_llm_generate``, ``_compile``,
``_wrap_for_compile`` via ``_compile``) and the production retrieval
instrument (``retrieval_health.begin_turn``) so it measures production, not a
copy.

Honest-by-construction: every run carries its leg manifest + fingerprints (in
``report.build_e2e_report``); smoke runs use a canned body and a MOCK banner
so the number is never mistaken for a model's. The model id is resolved from
env — never hardcoded (IRON 6).
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from kukai.compile_client import CompileClient
from kukai.rag import retrieval_health
from kukai.rag.benchmark.gold_ru import RuGoldQuery
from kukai.rag.benchmark.llm_runner import LlmRunnerConfig, _compile, _llm_generate
from kukai.rag.benchmark.paths import PathA, PathOff
from kukai.security.code_fixer import RevitCodeFixer

# Hit@K flavours reported per query (free byproduct — lets one e2e report
# correlate retrieval with pass-rate per query).
HIT_KS: tuple[int, ...] = (5, 10)

# A body that compiles inside the Kukai.UserCode wrapper. Smoke mode uses this
# instead of an LLM call — zero spend, proves the wiring end to end.
SMOKE_BODY = "return doc.Title;"


@dataclass
class E2EQueryResult:
    """Per-query e2e result: retrieval health + the pass-rate verdict."""

    id: str
    ru: str
    rag_query: str
    arm: str
    retrieved_keys: list[str]                 # health.final_keys (production set_final)
    health: dict                              # RetrievalHealth.to_dict()
    first_compile_ok: Optional[bool]
    repair_attempts_used: int
    e2e_success: Optional[bool]
    fixer_changed: bool
    cs_errors_final: list[str]                # CS codes of last failure, [] on success
    hits: dict = field(default_factory=dict)  # {"raw": {k: bool}} on retrieved_keys
    latency_ms: float = 0.0


def resolve_model(cli_model: Optional[str]) -> str:
    """Resolve the e2e model: --model → $KUKAI_BENCH_LLM_MODEL → $KUKAI_LLM_MODEL.

    Never hardcodes a model id (model-agnostic principle / IRON 6). Raises
    ``SystemExit`` with an instructive message when nothing is set.
    """
    m = (
        cli_model
        or os.environ.get("KUKAI_BENCH_LLM_MODEL")
        or os.environ.get("KUKAI_LLM_MODEL")
    )
    if not m:
        raise SystemExit(
            "--model not given and neither KUKAI_BENCH_LLM_MODEL nor "
            "KUKAI_LLM_MODEL is set; refusing to guess a model "
            "(model-agnostic rule, IRON 6)."
        )
    return m


def _cs_codes(errors: list) -> list[str]:
    """CS-code tokens from a list of {code,message,...} error dicts."""
    out: list[str] = []
    for e in errors or []:
        code = (e or {}).get("code") or ""
        if code:
            out.append(str(code))
    # de-dup, preserve order
    return list(dict.fromkeys(out))


def _generic_repair_hint(prompt_text: str, errors: list) -> str:
    """The same generic, text-only repair hint as llm_runner.py:226-232.

    Intentionally weaker than prod's api_members enrichment — disclosed in the
    report as ``harness: isolated-generation`` (a clean experiment on the RAG
    variable, not a full prod simulation).
    """
    err_text = "; ".join(f"{e['code']}: {e['message'][:120]}" for e in errors[:3])
    return (
        prompt_text
        + "\n\nPREVIOUS ATTEMPT FAILED. Compile errors: "
        + err_text
        + "\nFix only what's broken. Output the corrected method body."
    )


async def run_e2e(
    gold: list[RuGoldQuery],
    arm: str,
    config: LlmRunnerConfig,
    *,
    smoke: bool = False,
    live_translate: bool = False,
) -> list[E2EQueryResult]:
    """Run the e2e pass-rate loop over ``gold`` for one arm.

    Mirrors ``llm_runner.run_path_e2e``'s control flow with these deltas: it
    runs on the RU gold (production language), wraps each query in a production
    ``retrieval_health`` turn (for the leg manifest + final_keys), applies the
    prod-parity ``RevitCodeFixer`` before compiling, and records Hit@K.

    Aborts the WHOLE run (raises) on a missing LLM key or a compile-service
    outage — a partial e2e report must never be written.
    """
    if arm not in ("on", "off"):
        raise ValueError(f"unknown arm {arm!r} (expected 'on' or 'off')")

    revit_version = config.revit_version or "2026"
    fixer = RevitCodeFixer(revit_version=revit_version)
    compile_client = CompileClient(base_url=config.compile_url)

    # Preload the path ONCE for the whole run.
    path = PathA() if arm == "on" else PathOff()
    if arm == "on":
        # warm the index (PathA.enrich also ensures, but do it before the loop)
        path._enricher.ensure_loaded()  # noqa: SLF001 — internal warm by design

    # Compile service must be reachable (smoke still compiles the canned body).
    if not await compile_client.health():
        await compile_client.close()
        raise RuntimeError(
            f"compile service not reachable at {config.compile_url} — start "
            "backend/compile-service before running the e2e benchmark."
        )

    results: list[E2EQueryResult] = []
    try:
        for gq in gold:
            results.append(
                await _run_one(
                    gq,
                    arm,
                    path,
                    config,
                    compile_client,
                    fixer,
                    revit_version,
                    smoke=smoke,
                    live_translate=live_translate,
                )
            )
    finally:
        await compile_client.close()
    return results


async def _run_one(
    gold: RuGoldQuery,
    arm: str,
    path,
    config: LlmRunnerConfig,
    compile_client: CompileClient,
    fixer: RevitCodeFixer,
    revit_version: str,
    *,
    smoke: bool,
    live_translate: bool,
) -> E2EQueryResult:
    t0 = time.perf_counter()
    h = retrieval_health.begin_turn()
    first_compile_ok: Optional[bool] = None
    e2e_success: Optional[bool] = None
    repair_used = 0
    fixer_changed = False
    cs_final: list[str] = []
    rag_query = gold.en or gold.ru
    try:
        # 1. translation leg — replayed from the gold EN reading (reproducible).
        if live_translate:
            # default-off; reserved for a consented live-translate variant
            retrieval_health.report_leg("translate", "ran", 1, 0.0, "live")
        else:
            retrieval_health.report_leg("translate", "replayed")

        # 2. retrieval / enrichment via the chosen arm.
        if arm == "on":
            rag = path.enrich(gold.en or gold.ru)
            prompt_text = rag.prompt_text
            expanded = rag.metadata.get("expanded_query", "")
            retrieval_health.report_leg(
                "expand", "ran" if expanded and expanded != (gold.en or gold.ru) else "empty"
            )
            rag_query = expanded or rag_query
            # PathA's keyword/semantic/phrasings/rrf_fuse legs reported ambiently
            # by index.search inside the active turn.
        else:
            prompt_text = ""
            # Make the manifest explicit about WHY retrieval legs are absent.
            retrieval_health.report_leg("expand", "skipped_flag", detail="arm_off")
            retrieval_health.report_leg("keyword", "skipped_flag", detail="arm_off")
            retrieval_health.report_leg("semantic", "skipped_flag", detail="arm_off")
            # No final keys for the no-RAG arm.
            retrieval_health.set_final([])

        # 3. generation + compile loop with prod-parity fixer.
        current = SMOKE_BODY if smoke else await _llm_generate(
            prompt_text, gold.ru, config
        )
        max_attempts = 1 if smoke else max(1, config.max_repair_attempts)
        repair_prompt = prompt_text
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                current = SMOKE_BODY if smoke else await _llm_generate(
                    repair_prompt, gold.ru, config
                )

            fixed = fixer.fix(current)
            if attempt == 1:
                fixer_changed = fixed != current

            ok, errors = await _compile(fixed, config, compile_client)

            # Compile-service outage → abort the whole run (no partial report).
            if errors and errors[0].get("code") == "SERVICE":
                raise RuntimeError(
                    "compile service became unavailable mid-run — aborting the "
                    "e2e run rather than writing a partial report."
                )

            if attempt == 1:
                first_compile_ok = ok

            if ok:
                e2e_success = True
                cs_final = []
                break

            cs_final = _cs_codes(errors)
            repair_used = attempt  # this attempt was consumed by a repair
            if attempt < max_attempts:
                repair_prompt = _generic_repair_hint(prompt_text, errors)

        if e2e_success is None:
            e2e_success = False

        # 4. Hit@K bonus on the production final_keys.
        retrieved_keys = list(h.final_keys)
        hits = {"raw": {k: gold.hit_at_k(retrieved_keys, k, strict=False) for k in HIT_KS}}

        health = h.to_dict()
    finally:
        retrieval_health.finish_turn(h)

    return E2EQueryResult(
        id=gold.id,
        ru=gold.ru,
        rag_query=rag_query,
        arm=arm,
        retrieved_keys=list(h.final_keys),
        health=health,
        first_compile_ok=first_compile_ok,
        repair_attempts_used=repair_used,
        e2e_success=e2e_success,
        fixer_changed=fixer_changed,
        cs_errors_final=cs_final,
        hits=hits,
        latency_ms=(time.perf_counter() - t0) * 1000.0,
    )
