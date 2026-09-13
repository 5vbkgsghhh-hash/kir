# -*- coding: utf-8 -*-
"""The bureau of models: spending limit, stopping, coordination — BY THE NUMBERS.

🔴 WHAT THESE TESTS DO NOT PROVE. There is no real provider in this tree:
every call here is a cassette stand-in, and the "autonomous bureau" mission
is NOT closed by them (the owner's word). What is checked is the
mechanism: that the limit really is a limit, that Stop really stops, that
the program is born from the answer and not from a repository file, and
that a conflict creates a NEW assignment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kir.bureau import provider as P
from kir.bureau import runner as R
from kir.project_tasks import checkpoint_task, read_task

ROOT = Path(__file__).resolve().parents[3]
CHILD_ENV = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")

#: The "model's" answer: an independent, author-written program, not an example file.
ANSWER = (
    "program = {{'ir_version': '1.0', 'intent': 'bureau: {tag}', 'ops': [\n"
    "    {{'op': 'create_level', 'id': 'L{n}', 'elev_mm': {n}00, 'name': 'L{n}'}},\n"
    "    {{'op': 'create_wall', 'id': 'W{n}', 'p0_mm': [0, 0], 'p1_mm': [{n}000, 0],\n"
    "     'height_mm': 3000, 'level': {{'by': 'ref', 'value': 'L{n}'}}}},\n"
    "]}}\n")


def _generator():
    """A deterministic "author": one program per one assignment text."""
    seen = {}

    def generate(request):
        text = request.messages[0]["content"]
        number = seen.setdefault(text, len(seen) + 1)
        return ANSWER.format(tag=text[:24], n=number)

    return generate


@pytest.fixture
def scene(tmp_path):
    """The scene: a saved project + a cassette IN ITS OWN directory (not next to the journal)."""
    from examples.residential_project import concept
    from examples.residential_refinement import develop_section
    from kir.project_store import ProjectStore, TASK_STORE_SCHEMA

    root = concept()
    store = ProjectStore.create(tmp_path / "bureau.sqlite", root)
    store.commit(develop_section(root, height_mm=4200., setback_mm=1800.),
                 expected_revision=root.revision_id)
    store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=store.head().revision_id)
    # Explicit coordinator handoff; bureau never silently edits a sealed recipe.
    from kir.project_handoff import handoff_instance_to_explicit
    for key in ('tower-a', 'tower-b', 'tower-c'):
        head = store.head()
        instance = next(item for item in head.instances if item.key == key)
        module = next(item for item in head.modules if item.key == instance.module_key)
        if module.owner == 'sealed_evaluation':
            changed = handoff_instance_to_explicit(head, key, new_module_key='bureau-' + key,
                expected_revision=head.revision_id)
            store.commit(changed, expected_revision=head.revision_id)
    tape = tmp_path / "tape"
    tape.mkdir()
    provider = P.TapeProvider(tape / "cassette.json", mode="record", generator=_generator())
    return store, provider, tape / "cassette.json"


def _request(content="поручение: проверка", max_tokens=2048):
    return P.CompletionRequest(messages=({"role": "user", "content": content},),
                               max_tokens=max_tokens)


# ── port ─────────────────────────────────────────────────────────────────────
def test_the_provider_takes_no_store_and_the_request_carries_only_words(scene):
    """🔴 "NO ACCESS BY CONSTRUCTION" IS ABOUT THE SIGNATURE AND ABOUT THE REQUEST'S TYPES.

    Review A3-2 put a live `ProjectStore` into `tags` and into `content`:
    the previous check looked at the set of keys and let the object through,
    and it broke later with an unnamed `TypeError`. A signature with no
    store is one necessary condition; the request's types are the second.
    """
    import inspect

    store, provider, _path = scene
    names = set(inspect.signature(P.TapeProvider.__init__).parameters)
    assert not {"store", "project", "revision"} & names
    with pytest.raises(P.ProviderRefusal) as carried:
        P.CompletionRequest(messages=({"role": "user", "content": store},), max_tokens=16)
    assert carried.value.code == "bad_message"
    with pytest.raises(P.ProviderRefusal) as tagged:
        P.CompletionRequest(messages=({"role": "user", "content": "текст"},),
                            max_tokens=16, tags=(store,))
    assert tagged.value.code == "bad_tags"
    # `bool` is a subclass of `int`: `max_tokens=True` would share a cassette record with `1`.
    with pytest.raises(P.ProviderRefusal) as flagged:
        P.CompletionRequest(messages=({"role": "user", "content": "текст"},), max_tokens=True)
    assert flagged.value.code == "bad_budget"
    assert P.request_key(_request(max_tokens=1)) != P.request_key(_request(max_tokens=2))


def test_a_cassette_miss_refuses_instead_of_inventing(tmp_path):
    (tmp_path / "cassette.json").write_text("{}", encoding="utf-8")
    tape = P.TapeProvider(tmp_path / "cassette.json", mode="replay")
    with pytest.raises(P.ProviderRefusal) as caught:
        tape.complete(_request())
    assert caught.value.code == "cassette_miss" and tape.misses == 1
    with pytest.raises(P.ProviderRefusal) as unavailable:
        P.real_provider()
    assert unavailable.value.code == "real_provider_unavailable"


def test_a_cassette_in_the_store_directory_is_refused(scene):
    """A cassette is a trace of someone else's answers; in the journal's directory its provenance is lost."""
    store, _provider, _path = scene
    beside = Path(store.path).parent / "cassette.json"
    with pytest.raises(P.ProviderRefusal) as caught:
        P.TapeProvider(beside, mode="record", generator=_generator())
    assert caught.value.code == "cassette_inside_store"
    assert not beside.exists()


def test_two_writers_do_not_lose_each_others_cassette_rows(tmp_path):
    """A3-8: the provider rewrote the whole file, and the first writer's record disappeared."""
    path = tmp_path / "tape" / "cassette.json"
    path.parent.mkdir()
    first = P.TapeProvider(path, mode="record", generator=lambda request: "первый")
    second = P.TapeProvider(path, mode="record", generator=lambda request: "второй")
    first.complete(_request("поручение: один"))
    second.complete(_request("поручение: два"))
    tape = json.loads(path.read_text(encoding="utf-8"))
    assert len(tape) == 2, "второй писатель затёр запись первого"
    assert {row["text"] for row in tape.values()} == {"первый", "второй"}


# ── budget and stop ──────────────────────────────────────────────────────────
def test_stop_is_checked_before_money_and_is_monotonic(scene):
    """The order is not decoration: a stopped team does not spend even what is allowed."""
    store, provider, _path = scene
    budget = R.TeamBudget(max_calls=0, max_tokens=0)
    R.stop(store)
    with pytest.raises(R.BureauRefusal) as caught:
        R._ask(store, provider, _request(), budget)
    assert caught.value.code == "team_stopped", "деньги ответили раньше остановки"
    assert provider.calls == 0
    # A3-4: `{bureau_stop: False}` through the same journal does NOT lift
    # the stop. Only the team's own actor is entitled to write to the team
    # book (`worker no longer owns an assigned attempt` for anyone else) —
    # all the more reason that even it lifts Stop only through `resume`.
    task = read_task(store, R.TEAM_TASK)
    checkpoint_task(store, R.TEAM_TASK, request_id="odna-stroka-false",
                    generation=task["generation"], expected_version=task["version"],
                    actor="bureau-coordinator", notes={"bureau_stop": False})
    assert R.is_stopped(store) is True
    with pytest.raises(R.BureauRefusal):
        R.resume(store, reason="")
    R.resume(store, reason="владелец разрешил продолжить")
    assert R.is_stopped(store) is False


def test_a_failed_provider_call_still_costs_a_call(scene):
    """A3-5: a failed call cost the team nothing — the journal understated spending."""
    store, _provider, _path = scene

    class Failing:
        def complete(self, request):
            raise P.ProviderRefusal("upstream_down", "провайдер отвалился")

    before = R.spend(store)
    with pytest.raises(P.ProviderRefusal):
        R._ask(store, Failing(), _request(), R.TeamBudget(max_calls=5, max_tokens=10_000))
    after = R.spend(store)
    assert after["calls"] == before["calls"] + 1
    assert after["tokens"] == before["tokens"] + 2048
    assert after["unknown_tokens"] == before["unknown_tokens"] + 2048


def test_the_budget_is_durable_and_reserved_before_the_call(scene, tmp_path):
    """🔴 A3-1: CHECKING IS NOT THE SAME AS RESERVING.

    Four processes at `max_calls=2` made FOUR calls: the gate read the
    journal, called the provider, and wrote the spending AFTER. Here the
    write comes first, through CAS, so the number of successful calls does
    not exceed the limit, and the spending is visible to the other process.
    """
    store, provider, cassette = scene
    provider.complete(_request("поручение: разогрев кассеты"))
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json, sys, time\n"
        "from kir.bureau import provider as P, runner as R\n"
        "from kir.project_store import ProjectStore\n"
        "store = ProjectStore.open(sys.argv[1], readonly=False)\n"
        "tape = P.TapeProvider(sys.argv[2], mode='replay')\n"
        "budget = R.TeamBudget(max_calls=2, max_tokens=10**9)\n"
        "request = P.CompletionRequest(messages=({'role': 'user',\n"
        "    'content': 'поручение: разогрев кассеты'},), max_tokens=2048)\n"
        "while time.time() < float(sys.argv[3]):\n"
        "    time.sleep(0.005)\n"
        "try:\n"
        "    R._ask(store, tape, request, budget)\n"
        "    print(json.dumps({'ok': True}))\n"
        "except Exception as exc:\n"
        "    print(json.dumps({'ok': False, 'code': getattr(exc, 'code', type(exc).__name__)}))\n",
        encoding="utf-8")
    import time as _time

    barrier = _time.time() + 3.0
    children = [subprocess.Popen([sys.executable, str(worker), str(store.path), str(cassette),
                                  str(barrier)], stdout=subprocess.PIPE, text=True,
                                 env=CHILD_ENV) for _ in range(4)]
    rows = [json.loads(child.communicate(timeout=600)[0].strip().splitlines()[-1])
            for child in children]
    succeeded = [row for row in rows if row.get("ok")]
    assert len(succeeded) <= 2, f"предел 2, а вызовов прошло {len(succeeded)}"
    assert R.spend(store)["calls"] <= 2
    assert all(row.get("code") in ("call_budget_exhausted", "budget_contended",
                                   "journal_contended")
               for row in rows if not row.get("ok")), rows
    # durable: the other process sees the same spending
    child = subprocess.run(
        [sys.executable, "-c",
         "import json, sys\n"
         "from kir.bureau import runner as R\n"
         "from kir.project_store import ProjectStore\n"
         "store = ProjectStore.open(sys.argv[1], readonly=False)\n"
         "print(json.dumps({'spend': R.spend(store), 'stopped': R.is_stopped(store)}))\n",
         str(store.path)], capture_output=True, text=True, timeout=600, env=CHILD_ENV)
    assert child.returncode == 0, child.stderr[-500:]
    assert json.loads(child.stdout)["spend"] == R.spend(store)


# ── coordination ──────────────────────────────────────────────────────────
def _assign_and_work(store, provider, budget, *, text, worker, instance, base):
    task_id = R.assign(store, text, worker_id=worker, base_revision=base, instance_key=instance)
    return task_id, R.work(store, task_id, provider=provider, budget=budget)


def test_two_disjoint_workers_are_both_accepted(scene):
    """🔴 THE CAUSE OF THE EARLIER CONFLICT WAS NOT IN THE DATABASE, BUT IN THE REFERENCE.

    Measured before the fix: `принято 1 · конфликтов 1` for two workers
    whose holdings don't overlap at all. The merge report named the
    subject: `dependency_analysis_incomplete` + `unresolved_reference` on
    the `level` field — the model refers to things by its own ids, while
    the project resolves references by output address. An incomplete
    dependency analysis forbids ANY divergent merge.
    """
    store, provider, _path = scene
    budget = R.TeamBudget(max_calls=20, max_tokens=200_000)
    base = store.head().revision_id
    _b, work_b = _assign_and_work(store, provider, budget, text="Башня B: стена 6000",
                                  worker="worker-b", instance="tower-b", base=base)
    _c, work_c = _assign_and_work(store, provider, budget, text="Башня C: стена 4500",
                                  worker="worker-c", instance="tower-c", base=base)
    assert work_b.refusal is None and work_c.refusal is None
    decisions = R.coordinate(store, provider=provider, budget=budget)
    assert len(decisions.accepted) == 2, decisions.to_dict()
    assert decisions.conflicted == ()
    # (f): the program's digest makes it all the way to the ACCEPTED
    # revision, not only to `work`
    digests = {instance.key: (dict(instance.metadata) or {}).get("author_digest")
               for instance in store.head().instances}
    assert digests["tower-b"] == work_b.author_digest
    assert digests["tower-c"] == work_c.author_digest


def test_a_stale_worker_conflicts_and_the_replan_is_a_new_assignment(scene):
    """A conflict creates a NEW assignment, and it is carried through to acceptance."""
    store, provider, _path = scene
    budget = R.TeamBudget(max_calls=20, max_tokens=200_000)
    base = store.head().revision_id
    _assign_and_work(store, provider, budget, text="Башня B: стена 6000",
                     worker="worker-b", instance="tower-b", base=base)
    first = R.coordinate(store, provider=provider, budget=budget)
    assert len(first.accepted) == 1
    # A worker that started BEFORE acceptance: its base is the earlier head.
    stale, _result = _assign_and_work(store, provider, budget, text="Башня B: ещё раз, 600",
                                      worker="worker-b", instance="tower-b", base=base)
    second = R.coordinate(store, provider=provider, budget=budget)
    assert second.accepted == () and len(second.conflicted) == 1
    assert [row["kind"] for row in read_task(store, stale)["decision"]["merge"]["conflicts"]] \
        == ["modify_modify"]
    assert len(second.replanned) == 1
    replan = second.replanned[0]
    task = read_task(store, replan)
    assert replan != stale, "перепланирование обязано быть НОВЫМ поручением"
    assert task["assignment"]["base_revision"] == store.head().revision_id
    assert task["assignment"]["objective"] != read_task(store, stale)["assignment"]["objective"]
    result = R.work(store, replan, provider=provider, budget=budget)
    assert result.refusal is None and result.proposal_id
    third = R.coordinate(store, provider=provider, budget=budget)
    assert third.accepted == (replan,), third.to_dict()
    digests = {instance.key: (dict(instance.metadata) or {}).get("author_digest")
               for instance in store.head().instances}
    assert digests["tower-b"] == result.author_digest


def test_work_on_an_unknown_task_refuses_by_name(scene):
    """A3-7: it was `StoreNotFound` with no code, even though a neighboring miss answered with one."""
    store, provider, _path = scene
    result = R.work(store, "no-such-task", provider=provider,
                    budget=R.TeamBudget(max_calls=2, max_tokens=1000))
    assert result.refusal["code"] == "task_not_found"
    assert result.proposal_id is None and provider.calls == 0


def test_the_program_comes_from_the_answer_and_not_from_the_repository(scene):
    """(f): the program's digest must match the sandbox's digest for the same text."""
    from kir.sandbox import execute_author_script
    from kir.task_recipe_runner import RECIPE_POLICY

    store, provider, cassette = scene
    budget = R.TeamBudget(max_calls=5, max_tokens=50_000)
    _task, result = _assign_and_work(store, provider, budget, text="Башня B: стена 6000",
                                     worker="worker-b", instance="tower-b",
                                     base=store.head().revision_id)
    tape = json.loads(cassette.read_text(encoding="utf-8"))
    answer = next(row["text"] for row in tape.values() if "Башня B" in row["text"])
    sandbox = execute_author_script(answer, policy=RECIPE_POLICY).as_dict()
    assert result.author_digest == sandbox["author_digest"]
    examples = {path.read_text(encoding="utf-8") for path in (ROOT / "examples").glob("*.py")}
    assert answer not in examples, "программа обязана родиться из ответа, а не из файла"


# ── CLI ────────────────────────────────────────────────────────────────────
def _cli(*argv):
    child = subprocess.run([sys.executable, "-m", "kir.bureau", *argv],
                           capture_output=True, text=True, timeout=600, env=CHILD_ENV)
    return child


def test_the_cli_carries_the_honesty_line_on_every_path(scene, tmp_path):
    """A3-6: on two ordinary error paths, the honesty line was missing entirely."""
    store, _provider, cassette = scene
    for argv in (("status", str(store.path)),
                 ("status", str(tmp_path / "нет-такого-хранилища")),
                 ("work", str(store.path), "--cassette", str(cassette), "--task", "no-such-task")):
        child = _cli(*argv)
        assert child.stdout.strip(), f"{argv}: пустой вывод\n{child.stderr[-400:]}"
        payload = json.loads(child.stdout.strip().splitlines()[-1])
        assert "honesty" in payload, argv
        assert payload["honesty"].startswith("настоящий LLM:"), payload


# ── correction package 07.09: context, projection, Stop, hard budget ───────
def test_the_request_carries_the_project_and_the_conflict(scene):
    """🔴 THE MODEL WAS WRITING BLIND: the request carried only the assignment's text.

    The owner's word: "it isn't given the project's content." Now the
    request carries the instance names, the parameters, and the COMPOSITION
    of the target's outputs, and on replanning, also exactly what didn't
    match.
    """
    store, provider, _path = scene
    budget = R.TeamBudget(max_calls=20, max_tokens=200_000)
    base = store.head().revision_id
    task_id = R.assign(store, "Башня B: стена 6000", worker_id="worker-b",
                       base_revision=base, instance_key="tower-b", outputs=("L1", "W1"))
    request = R._request_for(read_task(store, task_id), store)
    body = "\n".join(message["content"] for message in request.messages)
    assert "поручение: Башня B" in body
    context = json.loads(request.messages[1]['content'].removeprefix('проект: '))
    assert context['target_instance']['key'] == 'tower-b'
    assert next(item for item in context['instances'] if item['key'] == 'tower-b')['role'] == 'цель'
    assert context['you_may_write'] == ['L1', 'W1']
    assert "target_instance" in body and "parameters" in body
    # Every message is TEXT: a process object cannot sneak into the request.
    assert all(isinstance(message["content"], str) for message in request.messages)

    R.work(store, task_id, provider=provider, budget=budget)
    first = R.coordinate(store, provider=provider, budget=budget)
    assert len(first.accepted) == 1
    # A worker on an OLD base: a real collision, not a manufactured one.
    _assign_and_work(store, provider, budget, text="Башня B: ещё раз, 600",
                     worker="worker-b", instance="tower-b", base=base)
    decisions = R.coordinate(store, provider=provider, budget=budget)
    assert len(decisions.conflicted) == 1 and len(decisions.replanned) == 1
    replan_request = R._request_for(read_task(store, decisions.replanned[0]), store)
    text = "\n".join(message["content"] for message in replan_request.messages)
    assert "не сошлось" in text and "modify_modify" in text
    assert "conflict" in text


def test_an_answer_projects_only_onto_the_outputs_it_was_granted(scene):
    """🔴 THE ANSWER WAS REPLACING THE INSTANCE'S ENTIRE SET OF OUTPUTS — silently erasing someone else's."""
    store, provider, _path = scene
    budget = R.TeamBudget(max_calls=20, max_tokens=200_000)
    base = store.head().revision_id
    instance = next(item for item in store.head().instances if item.key == "tower-b")
    before = {output.key: json.dumps(dict(output.operation), sort_keys=True, default=str)
              for output in instance.outputs}
    task_id, result = _assign_and_work(store, provider, budget, text="Башня B: стена 6000",
                                       worker="worker-b", instance="tower-b", base=base)
    assert result.refusal is None
    R.coordinate(store, provider=provider, budget=budget)
    after = next(item for item in store.head().instances if item.key == "tower-b")
    kept = {output.key: json.dumps(dict(output.operation), sort_keys=True, default=str)
            for output in after.outputs}
    assert set(before) <= set(kept), "выходы, которых ответ не касался, исчезли"
    for key, payload in before.items():
        assert kept[key] == payload, f"{key}: чужой выход переписан ответом модели"

    # A declared list makes the check strict in both directions.
    strict = R.assign(store, "Башня C: ровно два выхода", worker_id="worker-c",
                      base_revision=store.head().revision_id, instance_key="tower-c",
                      outputs=("ABSENT",))
    refused = R.work(store, strict, provider=provider, budget=budget)
    assert refused.refusal["code"] in ("undeclared_output", "missing_declared_output")
    assert refused.proposal_id is None
    with pytest.raises(R.BureauRefusal, match="no_declared_outputs"):
        R.assign(store, "пустой список", worker_id="worker-c",
                 base_revision=store.head().revision_id, instance_key="tower-c", outputs=())


def test_the_token_budget_is_hard_and_a_bigger_answer_is_refused(scene):
    """The owner's probe: budget 2048, answer 100 + 2048 — WAS ACCEPTED."""
    store, _provider, _path = scene

    class Fat:
        calls = 0

        def complete(self, request):
            Fat.calls += 1
            return P.CompletionResponse(
                text="program = {'ir_version': '1.0', 'intent': 'fat', 'ops': []}",
                usage={"input_tokens": 100, "output_tokens": 2048, "calls": 1},
                provider_id="fat/test")

    budget = R.TeamBudget(max_calls=5, max_tokens=2048)
    with pytest.raises(R.BureauRefusal) as caught:
        R._ask(store, Fat(), _request(max_tokens=4096), budget)
    assert caught.value.code == "token_budget_overrun"
    spent = R.spend(store)
    assert spent["tokens"] == spent["reported_tokens"] == 2148  # refusal cannot undo reported expenditure
    # The ceiling rode out to the provider TRIMMED to the remaining budget, not as requested.
    assert Fat.calls == 1
    # The second attempt runs into the exhausted budget BEFORE the call.
    with pytest.raises(R.BureauRefusal) as second:
        R._ask(store, Fat(), _request(max_tokens=4096), budget)
    assert second.value.code in ("token_budget_exhausted", "call_budget_exhausted")
    assert Fat.calls == 1


def test_coordinate_does_not_accept_anything_while_the_team_is_stopped(scene):
    """Accepting the project is an action: a stopped team does not perform it."""
    store, provider, _path = scene
    budget = R.TeamBudget(max_calls=20, max_tokens=200_000)
    base = store.head().revision_id
    _assign_and_work(store, provider, budget, text="Башня B: стена 6000",
                     worker="worker-b", instance="tower-b", base=base)
    head = store.head().revision_id
    R.stop(store)
    with pytest.raises(R.BureauRefusal) as caught:
        R.coordinate(store, provider=provider, budget=budget)
    assert caught.value.code == "team_stopped"
    assert store.head().revision_id == head, "остановленная команда изменила проект"
    R.resume(store, reason="владелец разрешил продолжить")
    decisions = R.coordinate(store, provider=provider, budget=budget)
    assert len(decisions.accepted) == 1 and decisions.stopped is False


def test_stop_between_the_answer_and_the_write_leaves_no_proposal(scene):
    """🔴 THE THIRD Stop CHECKPOINT: between the model's answer and recording the proposal.

    Review 6 measured: Stop raised in this window — `refusal` is empty,
    `proposal_id` is created, the task went into `submitted`. A durable
    proposal from a stopped team is exactly "the project keeps changing
    anyway."
    """
    store, provider, _path = scene
    budget = R.TeamBudget(max_calls=8, max_tokens=40_000)

    class StopsWhileThinking:
        def __init__(self, inner):
            self.inner = inner

        def complete(self, request):
            answer = self.inner.complete(request)
            R.stop(store)          # Stop is raised AFTER the answer, before the write
            return answer

    task_id = R.assign(store, "Башня B: стена 6000", worker_id="worker-b",
                       base_revision=store.head().revision_id, instance_key="tower-b")
    result = R.work(store, task_id, provider=StopsWhileThinking(provider), budget=budget)
    assert result.refusal["code"] in ("stopped_during_call", "stopped_before_submit", "team_stopped")
    assert result.proposal_id is None
    assert read_task(store, task_id)["state"] == "assigned", "предложение всё-таки заведено"


def test_the_context_says_plainly_when_no_output_list_was_declared(scene):
    """`you_may_write: []` was read by the model as "nothing is allowed" — when in fact everything is."""
    store, _provider, _path = scene
    task_id = R.assign(store, "Башня B: без объявленного списка", worker_id="worker-b",
                       base_revision=store.head().revision_id, instance_key="tower-b")
    body = "\n".join(message["content"]
                     for message in R._request_for(read_task(store, task_id), store).messages)
    assert '"you_may_write": []' not in body
    assert "список не объявлен: разрешены любые выходы tower-b" in body
