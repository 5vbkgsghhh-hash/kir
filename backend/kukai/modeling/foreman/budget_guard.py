"""ForemanBudgetGuard — retry-spiral tripwire for offline tests and prod.

Wraps a Foreman run with hard caps on LLM, compile, and execute call counts,
plus aggregate USD spend (Wave 7.5 Fix #4).

Reads `.calls` attribute off client instances — MockLLMClient, MockCompileClient,
MockBridgeClient, HttpCompileClient (Plan 5+), VertexGeminiClient,
WebSocketBridgeClient all expose this. For a non-mock client without `.calls`,
supply an adapter that counts.

USD-cost tracking contract (Wave 7.5 Fix #4 — Audit B11):
  Each entry in client.calls MAY include a "usd" float field. ForemanBudgetGuard
  sums these across all clients to enforce `BudgetCaps.max_usd`. Clients that
  don't populate "usd" contribute 0.0 — opt-in. Production clients
  (VertexGeminiClient, OpenRouterClient) SHOULD populate "usd" with the
  per-call cost estimate (input_tokens * input_price + output_tokens *
  output_price). Mock clients leave "usd" absent — sandbox costs are $0.

  Pricing source of truth lives in the client (e.g. VertexGeminiClient knows
  Gemini Flash is $0.075/M input + $0.30/M output). BudgetGuard is
  client-agnostic — it just sums whatever clients self-report.
"""
from __future__ import annotations
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BudgetExceededError(RuntimeError):
    """Raised when guard.check() detects an over-budget run."""


class BudgetCaps(BaseModel):
    """Hard caps for a single Foreman.run_phase invocation.

    Wave 7.5 Fix #4: `max_usd` IS enforced when clients self-report cost
    in their `.calls[*]["usd"]` field. Set max_usd=0.0 to forbid any paid
    calls (sandbox default); set conservative caps for production live tests.
    """
    model_config = ConfigDict(frozen=True)

    max_llm_calls: int = Field(100, ge=1)
    max_compile_calls: int = Field(200, ge=1)
    max_execute_calls: int = Field(200, ge=1)
    # Wave 7.5 Fix #4: enforced via per-call "usd" entries in client.calls.
    # See module docstring for the contract. Clients without "usd" field
    # contribute 0.0 (so mock test caps of 0.0 stay non-blocking).
    max_usd: float = Field(5.0, ge=0.0)


class ForemanBudgetGuard:
    """Context manager that monitors client `.calls` lists against `BudgetCaps`.

    Usage:
        with ForemanBudgetGuard(caps, llm, compile_c, bridge) as guard:
            await foreman.run_phase(plan)
            guard.check()  # raises BudgetExceededError if any cap exceeded
    """

    def __init__(self, caps: BudgetCaps, llm_client: Any, compile_client: Any, bridge_client: Any):
        self._caps = caps
        self._clients = {"llm": llm_client, "compile": compile_client, "execute": bridge_client}
        self._call_baselines: dict[str, int] = {}
        self._cost_baselines: dict[str, float] = {}

    def __enter__(self) -> "ForemanBudgetGuard":
        self._call_baselines = {k: _count(c) for k, c in self._clients.items()}
        self._cost_baselines = {k: _cost_sum(c) for k, c in self._clients.items()}
        return self

    def __exit__(self, *a) -> None:
        return None

    def check(self) -> None:
        caps_map = {
            "llm": self._caps.max_llm_calls,
            "compile": self._caps.max_compile_calls,
            "execute": self._caps.max_execute_calls,
        }
        # Per-channel call-count caps (Wave 6B mechanism)
        for kind, client in self._clients.items():
            used = _count(client) - self._call_baselines[kind]
            cap = caps_map[kind]
            if used > cap:
                raise BudgetExceededError(f"{kind} calls {used} exceeded cap {cap}")

        # Wave 7.5 Fix #4: aggregate USD across all channels
        total_usd = sum(
            _cost_sum(c) - self._cost_baselines[k]
            for k, c in self._clients.items()
        )
        if total_usd > self._caps.max_usd:
            # Report per-channel breakdown for easier post-mortem.
            per_channel = {
                k: round(_cost_sum(c) - self._cost_baselines[k], 4)
                for k, c in self._clients.items()
            }
            raise BudgetExceededError(
                f"aggregate USD ${total_usd:.4f} exceeded cap ${self._caps.max_usd:.2f} "
                f"(per-channel: {per_channel})"
            )


def _count(client: Any) -> int:
    calls = getattr(client, "calls", None)
    return 0 if calls is None else len(calls)


def _cost_sum(client: Any) -> float:
    """Sum the optional 'usd' field across client.calls entries.

    Wave 7.5 Fix #4: clients self-report per-call cost via a "usd" float in
    their `.calls[i]` dict. Entries without "usd" contribute 0.0 (opt-in
    contract — mock clients stay free; production clients populate it).
    Non-dict entries or missing `.calls` contribute 0.0.
    """
    calls = getattr(client, "calls", None)
    if not calls:
        return 0.0
    total = 0.0
    for entry in calls:
        if isinstance(entry, dict):
            v = entry.get("usd")
            if isinstance(v, (int, float)):
                total += float(v)
    return total
