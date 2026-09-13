# -*- coding: utf-8 -*-
"""A real provider WITH NO KEY: the request is a file, the answer is a file, a live agent answers.

🔴 WHAT THESE TESTS PROVE, AND WHAT THEY DO NOT. Here, in place of a Claude
Code agent, a stub process answers: it reads the request file and writes
the answer file using the same protocol. This proves the EXCHANGE — its
form, validation, ceiling, timeout, retry — but not the quality of a live
model's design decisions. Real acceptance (`--real`) runs with live agents,
and there is no substitution by a cassette in it by construction: this
class of cassette does not read at all.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kir.bureau import exchange as X
from kir.bureau import provider as P
from kir.bureau import runner as R

ROOT = Path(__file__).resolve().parents[3]
CHILD_ENV = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")

RESPONDER = """
import json, sys, time
from pathlib import Path
root = Path(sys.argv[1]); text = sys.argv[2]; deadline = time.time() + float(sys.argv[3])
requests, responses = root / "requests", root / "responses"
while time.time() < deadline:
    for path in sorted(requests.glob("*.json")):
        answer = responses / path.name
        if answer.exists():
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        payload = {"schema": "kir-bureau-exchange-response/1", "text": text,
                   "usage": {"input_tokens": 40, "output_tokens": 120, "calls": 1},
                   "provider_id": "claude-code-agent", "model": "claude-sonnet",
                   "agent_note": "ответ живого агента, а не кассеты"}
        temporary = answer.with_suffix(".part")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(answer)
        print(json.dumps({"answered": path.stem[:16], "max_tokens": row.get("max_tokens")}))
        sys.exit(0)
    time.sleep(0.05)
print(json.dumps({"answered": None}))
"""

ANSWER = ("program = {'ir_version': '1.0', 'intent': 'bureau: живой агент', 'ops': [\n"
          "    {'op': 'create_level', 'id': 'LA', 'elev_mm': 300, 'name': 'LA'},\n"
          "    {'op': 'create_wall', 'id': 'WA', 'p0_mm': [0, 0], 'p1_mm': [6000, 0],\n"
          "     'height_mm': 3000, 'level': {'by': 'ref', 'value': 'LA'}},\n"
          "]}\n")


@pytest.fixture
def scene(tmp_path):
    from examples.residential_project import concept
    from examples.residential_refinement import develop_section
    from kir.project_store import ProjectStore, TASK_STORE_SCHEMA

    root = concept()
    store = ProjectStore.create(tmp_path / "bureau.sqlite", root)
    store.commit(develop_section(root, height_mm=4200., setback_mm=1800.),
                 expected_revision=root.revision_id)
    store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=store.head().revision_id)
    from kir.project_handoff import handoff_instance_to_explicit
    for key in ('tower-a', 'tower-b', 'tower-c'):
        head = store.head()
        instance = next(item for item in head.instances if item.key == key)
        module = next(item for item in head.modules if item.key == instance.module_key)
        if module.owner == 'sealed_evaluation':
            changed = handoff_instance_to_explicit(head, key, new_module_key='bureau-' + key,
                expected_revision=head.revision_id)
            store.commit(changed, expected_revision=head.revision_id)
    exchange = tmp_path / "exchange"
    return store, exchange


def _request(content="поручение: проверка", max_tokens=2048):
    return P.CompletionRequest(messages=({"role": "user", "content": content},),
                               max_tokens=max_tokens)


def _responder(root: Path, text: str, seconds: float = 60.0):
    return subprocess.Popen([sys.executable, "-c", RESPONDER, str(root), text, str(seconds)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=CHILD_ENV)


def test_a_missing_answer_is_a_named_timeout_and_the_request_stays(scene):
    _store, exchange = scene
    provider = X.FileExchangeProvider(exchange, timeout_s=1.0, poll_s=0.05)
    with pytest.raises(P.ProviderRefusal) as caught:
        provider.complete(_request())
    assert caught.value.code == "provider_timeout"
    waiting = provider.pending()
    assert len(waiting) == 1, "запрос обязан остаться на диске"
    # A retry does NOT create a second file and picks up the answer once it arrives.
    key = waiting[0]
    (exchange / "responses" / f"{key}.json").write_text(json.dumps(
        {"text": "поздний ответ", "usage": {"input_tokens": 1, "output_tokens": 2, "calls": 1},
         "provider_id": X.PROVIDER_ID}), encoding="utf-8")
    response = provider.complete(_request())
    assert response.text == "поздний ответ" and response.provider_id == X.PROVIDER_ID
    assert len(list((exchange / "requests").glob("*.json"))) == 1
    assert provider.pending() == ()


def test_an_answer_over_the_ceiling_is_refused_by_name(scene):
    _store, exchange = scene
    provider = X.FileExchangeProvider(exchange, timeout_s=1.0, poll_s=0.05)
    request = _request(max_tokens=2048)
    key = P.request_key(request)
    (exchange / "requests").mkdir(parents=True, exist_ok=True)
    (exchange / "responses").mkdir(parents=True, exist_ok=True)
    (exchange / "responses" / f"{key}.json").write_text(json.dumps(
        {"text": "слишком длинно", "usage": {"input_tokens": 100, "output_tokens": 2148,
                                             "calls": 1}, "provider_id": X.PROVIDER_ID}), encoding="utf-8")
    with pytest.raises(P.ProviderRefusal) as caught:
        provider.complete(request)
    assert caught.value.code == "budget_overrun"
    # A corrupt answer is distinguished from an overrun BY NAME.
    (exchange / "responses" / f"{key}.json").write_text("{это не json}", encoding="utf-8")
    with pytest.raises(P.ProviderRefusal) as broken:
        provider.complete(request)
    assert broken.value.code == "provider_response_corrupt"


def test_real_provider_is_named_by_the_environment_and_never_falls_back_to_a_cassette(scene):
    _store, exchange = scene
    saved = os.environ.pop(X.EXCHANGE_ENV, None)
    try:
        with pytest.raises(P.RealProviderUnavailable) as caught:
            P.real_provider()
        assert caught.value.code == "real_provider_unavailable"
        os.environ[X.EXCHANGE_ENV] = str(exchange)
        provider = P.real_provider()
        assert isinstance(provider, X.FileExchangeProvider)
        assert provider.provider_id == "claude-code-agent"
    finally:
        os.environ.pop(X.EXCHANGE_ENV, None)
        if saved is not None:
            os.environ[X.EXCHANGE_ENV] = saved


def test_a_live_agent_answers_and_the_work_becomes_a_proposal(scene):
    """The full circle: request-file -> responder -> sandbox -> proposal."""
    store, exchange = scene
    provider = X.FileExchangeProvider(exchange, timeout_s=60.0, poll_s=0.05)
    child = _responder(exchange, ANSWER)
    try:
        task_id = R.assign(store, "Башня B: стена от живого агента", worker_id="worker-b",
                           base_revision=store.head().revision_id, instance_key="tower-b",
                           outputs=("LA", "WA"))
        result = R.work(store, task_id, provider=provider,
                        budget=R.TeamBudget(max_calls=4, max_tokens=20_000))
    finally:
        child.wait(timeout=120)
    assert result.refusal is None, result.refusal
    assert result.proposal_id and result.author_digest
    assert provider.calls == 1 and R.spend(store)["calls"] == 1
    decisions = R.coordinate(store, provider=provider,
                             budget=R.TeamBudget(max_calls=4, max_tokens=20_000))
    assert decisions.accepted == (task_id,)
    instance = next(item for item in store.head().instances if item.key == "tower-b")
    written = {output.key for output in instance.outputs}
    assert {"LA", "WA"} <= written
    assert (dict(instance.metadata) or {}).get("provider") in ("tape", X.PROVIDER_ID)
    # The request CARRIED the project: the agent saw what it was writing into.
    row = json.loads(next((exchange / "requests").glob("*.json")).read_text(encoding="utf-8"))
    body = "\n".join(message["content"] for message in row["messages"])
    context = json.loads(row['messages'][1]['content'].removeprefix('проект: '))
    assert context['target_instance']['key'] == 'tower-b' and context['you_may_write'] == ['LA', 'WA']


def test_the_history_names_the_provider_that_actually_answered(scene, tmp_path):
    """🔴 THE METADATA CARRIED A HARDCODED "tape" STRING — WITH A LIVE AGENT, THAT IS A LIE.

    An accepted revision is the project's history: it must name whoever
    ACTUALLY answered. Checked with both providers: the stand-in and the
    live-agent exchange; before the fix, the second case is red by
    construction.
    """
    store, exchange = scene
    budget = R.TeamBudget(max_calls=8, max_tokens=40_000)

    tape_dir = tmp_path / "tape"
    tape_dir.mkdir()
    tape = P.TapeProvider(tape_dir / "cassette.json", mode="record",
                          generator=lambda request: ANSWER)
    task = R.assign(store, "Башня B: подстава", worker_id="worker-b",
                    base_revision=store.head().revision_id, instance_key="tower-b",
                    outputs=("LA", "WA"))
    result = R.work(store, task, provider=tape, budget=budget)
    assert result.refusal is None and result.provider_id == "tape/deterministic"
    assert result.to_dict()["provider_id"] == "tape/deterministic"
    assert R.coordinate(store, provider=tape, budget=budget).accepted == (task,)
    instance = next(item for item in store.head().instances if item.key == "tower-b")
    assert (dict(instance.metadata) or {})["provider"] == "tape/deterministic"

    live = X.FileExchangeProvider(exchange, timeout_s=60.0, poll_s=0.05)
    child = _responder(exchange, ANSWER.replace("LA", "LB").replace("WA", "WB"))
    try:
        second = R.assign(store, "Башня C: живой агент", worker_id="worker-c",
                          base_revision=store.head().revision_id, instance_key="tower-c",
                          outputs=("LB", "WB"))
        answered = R.work(store, second, provider=live, budget=budget)
    finally:
        child.wait(timeout=120)
    assert answered.refusal is None, answered.refusal
    assert answered.provider_id == X.PROVIDER_ID
    assert R.coordinate(store, provider=live, budget=budget).accepted == (second,)
    tower_c = next(item for item in store.head().instances if item.key == "tower-c")
    assert (dict(tower_c.metadata) or {})["provider"] == X.PROVIDER_ID, \
        "история проекта назвала не того, кто ответил"


SLOW_WRITER = """
import json, sys, time
from pathlib import Path
root = Path(sys.argv[1]); pause = float(sys.argv[2])
requests, responses = root / "requests", root / "responses"
while True:
    found = sorted(requests.glob("*.json"))
    if found:
        break
    time.sleep(0.05)
payload = json.dumps({"text": "ops = []\\n",
                      "usage": {"input_tokens": 10, "output_tokens": 20, "calls": 1},
                      "provider_id": "claude-code-agent"})
answer = responses / found[0].name
half = len(payload) // 2
with open(answer, "w", encoding="utf-8") as handle:      # НЕ атомарно, нарочно
    handle.write(payload[:half]); handle.flush()
    time.sleep(pause)
    handle.write(payload[half:])
print("written")
"""


def test_a_slowly_written_answer_is_awaited_and_not_called_corrupt(scene):
    """🔴 A HALF-WRITTEN ANSWER IS "STILL BEING WRITTEN," NOT "CORRUPT."

    Review 6 measured: an ordinary `open(...,'w')` with the second half
    arriving 1.5 s later produced `provider_response_corrupt` at second 2.1
    with a timeout of 6 — a refusal AHEAD OF SCHEDULE, and it cost the team
    a call from the budget.
    """
    _store, exchange = scene
    provider = X.FileExchangeProvider(exchange, timeout_s=8.0, poll_s=0.05)
    child = subprocess.Popen([sys.executable, "-c", SLOW_WRITER, str(exchange), "1.0"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=CHILD_ENV)
    try:
        started = time.monotonic()
        response = provider.complete(_request())
    finally:
        child.wait(timeout=60)
    assert response.text.strip() == "ops = []"
    assert time.monotonic() - started >= 1.0, "ответ пришёл раньше, чем его дописали"
    assert provider.calls == 1

    # And an answer that is unparseable FOREVER does refuse — but ONLY on
    # timeout, and with the last parse cause.
    slow = X.FileExchangeProvider(exchange, timeout_s=1.0, poll_s=0.05)
    key = P.request_key(_request("поручение: битый"))
    (exchange / "responses" / f"{key}.json").write_text("{половина", encoding="utf-8")
    with pytest.raises(P.ProviderRefusal) as caught:
        slow.complete(_request("поручение: битый"))
    assert caught.value.code == "provider_response_corrupt"
    assert "последняя причина" in str(caught.value)


def test_a_response_names_its_request_its_provider_and_fits_the_size_limit(scene):
    """The answer must say WHAT it is answering and WHO answered, and must fit within the limit."""
    _store, exchange = scene
    provider = X.FileExchangeProvider(exchange, timeout_s=1.0, poll_s=0.05)
    request = _request("поручение: сверка")
    key = P.request_key(request)
    (exchange / "requests").mkdir(parents=True, exist_ok=True)
    (exchange / "responses").mkdir(parents=True, exist_ok=True)
    good = {"text": "ops = []\n", "usage": {"input_tokens": 1, "output_tokens": 2, "calls": 1},
            "provider_id": "claude-code-agent"}
    (exchange / "responses" / f"{key}.json").write_text(
        json.dumps({**good, "request_id": "0" * 64}), encoding="utf-8")
    with pytest.raises(P.ProviderRefusal) as mismatched:
        provider.complete(request)
    assert mismatched.value.code == "response_request_mismatch"

    (exchange / "responses" / f"{key}.json").write_text(
        json.dumps({key: value for key, value in good.items() if key != "provider_id"}),
        encoding="utf-8")
    with pytest.raises(P.ProviderRefusal) as nameless:
        provider.complete(request)
    assert nameless.value.code == "provider_response_corrupt"
    assert "provider_id" in str(nameless.value)

    (exchange / "responses" / f"{key}.json").write_text(
        json.dumps({**good, "text": "x" * (X.MAX_RESPONSE_BYTES + 1024)}), encoding="utf-8")
    with pytest.raises(P.ProviderRefusal) as huge:
        provider.complete(request)
    assert huge.value.code == "response_too_large"

    (exchange / "responses" / f"{key}.json").write_text(
        json.dumps({**good, "request_id": key}), encoding="utf-8")
    assert provider.complete(request).provider_id == "claude-code-agent"


def test_a_foreign_provider_id_is_refused_and_the_limit_is_named(scene):
    """🔴 A FOREIGN NAME IN `provider_id` IS A WRONG COUNT, NOT A TYPO.

    The instrument counts external calls by this field, and review 6 (E2)
    measured an accepted answer with `provider_id: "tape"`. What is checked
    is FORM (the channel's name), not the responder's authenticity: only
    the exchange directory itself and its permissions provide that.
    """
    _store, exchange = scene
    provider = X.FileExchangeProvider(exchange, timeout_s=1.0, poll_s=0.05)
    request = _request("поручение: чей ответ")
    key = P.request_key(request)
    (exchange / "requests").mkdir(parents=True, exist_ok=True)
    (exchange / "responses").mkdir(parents=True, exist_ok=True)
    body = {"text": "ops = []\n", "usage": {"input_tokens": 1, "output_tokens": 2, "calls": 1}}
    (exchange / "responses" / f"{key}.json").write_text(
        json.dumps({**body, "provider_id": "tape"}), encoding="utf-8")
    with pytest.raises(P.ProviderRefusal) as foreign:
        provider.complete(request)
    assert foreign.value.code == "provider_id_mismatch"
    assert "tape" in str(foreign.value) and X.PROVIDER_ID in str(foreign.value)
    assert provider.calls == 0, "чужой ответ не вправе считаться вызовом"

    (exchange / "responses" / f"{key}.json").write_text(
        json.dumps({**body, "provider_id": X.PROVIDER_ID}), encoding="utf-8")
    assert provider.complete(request).provider_id == X.PROVIDER_ID
    assert provider.calls == 1
