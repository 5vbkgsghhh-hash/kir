from __future__ import annotations

from kukai.ai_protocol.authoring_benchmark_v0.contracts import WireExchangeV0
from kukai.ai_protocol.authoring_benchmark_v0.harness import (
    _budget_state,
    _budget_terminal,
)
from kukai.design_source import canonical_bytes


_STATE = "sha256:" + "0" * 64


def _exchange(response, *, visible=True, request=b"{}"):
    return WireExchangeV0.create(
        seq=1, actor="MODEL", model_visible=visible, provider_invocation=1,
        request=request, response=canonical_bytes(response),
        before_state_digest=_STATE, after_state_digest=_STATE,
        previous_exchange_digest=None,
    )


def test_recursive_unique_build_entity_census_is_cumulative() -> None:
    entities = tuple({
        "logical_id": f"ent_{index:03d}",
        "schema": "kir-build-entity/0",
    } for index in range(65))
    exchange = _exchange({"nested": {"items": entities}})
    assert _budget_state([exchange])[-1] == 65
    assert _budget_terminal([exchange]) == "DISQUALIFIED_CONTEXT_BYPASS"


def test_hidden_environment_responses_do_not_enter_model_budget() -> None:
    entity = {"logical_id": "ent_hidden", "schema": "kir-build-entity/0"}
    exchange = _exchange({"result": entity}, visible=False)
    assert _budget_state([exchange]) == (1, 2, 0, 0)


def test_crossing_request_budget_is_preserved_then_failed() -> None:
    exchange = _exchange({"ok": True}, request=b"x" * 512_001)
    assert exchange.request_bytes == 512_001
    assert _budget_terminal([exchange]) == "FAILED"
