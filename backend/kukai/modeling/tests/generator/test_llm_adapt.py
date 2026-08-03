"""LLM-adaptation loop tested with a MOCK LLM (no network): the loop parses the proposal,
validates the schema, runs the checker, feeds BLOCKING violations back, and converges to a
passing building — or gives up honestly. The real DeepSeek call is exercised by a live smoke
test, not here."""
import json

from kukai.modeling.generator.building import building
from kukai.modeling.generator.llm_adapt import adapt, _extract_json


def test_extract_json_strips_think_and_fences():
    assert _extract_json("<think>reasoning</think> {\"a\": 1}") == {"a": 1}
    assert _extract_json("```json\n{\"a\": 2}\n```") == {"a": 2}
    assert _extract_json("no json here") is None


def test_adapt_converges_when_llm_returns_valid_building():
    good = building(1, 1)
    res = adapt(building(1, 1), "raise ceilings", complete=lambda m: json.dumps(good))
    assert res.passed
    assert res.iterations == 1


def _break_window(b: dict) -> dict:
    for r in b["rooms"]:
        if r["id"] == "apt_0_0_bed":
            r["has_window"] = False
            r["window_area_m2"] = 0.0
    b["windows"] = [w for w in b["windows"] if w["room_id"] != "apt_0_0_bed"]
    return b


def test_adapt_feeds_violations_back_then_converges():
    broken = _break_window(building(1, 1))
    fixed = building(1, 1)
    calls = {"n": 0}

    def mock(messages):
        calls["n"] += 1
        return json.dumps(broken if calls["n"] == 1 else fixed)

    res = adapt(building(1, 1), "make a 1BR", complete=mock, max_iters=3)
    assert res.passed
    assert res.iterations == 2                          # broken first, fixed after feedback
    assert any("blocking" in h for h in res.history)    # the checker's violations were fed back


def test_adapt_gives_up_when_llm_never_fixes():
    broken = _break_window(building(1, 1))
    res = adapt(building(1, 1), "x", complete=lambda m: json.dumps(broken), max_iters=2)
    assert res.passed is False
    assert res.iterations == 2


def test_adapt_handles_unparseable_then_recovers():
    good = building(1, 1)
    calls = {"n": 0}

    def mock(messages):
        calls["n"] += 1
        return "I cannot do that" if calls["n"] == 1 else json.dumps(good)

    res = adapt(building(1, 1), "x", complete=mock, max_iters=3)
    assert res.passed
    assert "unparseable" in res.history
