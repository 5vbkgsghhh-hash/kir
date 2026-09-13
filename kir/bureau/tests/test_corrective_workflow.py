"""Product regressions: preserve authored fields, honest usage and resumed work."""
import json
from dataclasses import replace

import pytest

from kir.bureau import runner as R
from kir.bureau.provider import CompletionRequest, CompletionResponse, ProviderRefusal
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id
from kir.project_store import ProjectStore, TASK_STORE_SCHEMA, StoreConflict
from kir.project_tasks import read_task, task_history, checkpoint_task, submit_task, decide_task


@pytest.fixture
def store(tmp_path):
    level = output_id('bureau-correction', 'datum', 'level')
    source = ProjectRevision('bureau-correction', [ModuleDefinition('explicit')], [
        ModuleInstance('datum', 'explicit', {'level': {'op': 'create_level', 'elev_mm': 0}}),
        ModuleInstance('section', 'explicit', {
            'wall': {'op': 'create_wall', 'p0_mm': [1200, 2300], 'p1_mm': [6200, 2300],
                     'height_mm': 3000, 'level': {'by': 'ref', 'value': level}, 'base_offset_mm': 200},
            'other': {'op': 'create_level', 'elev_mm': 9000}})])
    return ProjectStore.create(tmp_path / 'project.sqlite', source, schema=TASK_STORE_SCHEMA)


class Provider:
    provider_id = 'synthetic-test'
    def __init__(self, source="program={'ops':[{'op':'create_wall','id':'wall','height_mm':4100}]}", tokens=12):
        self.source, self.tokens, self.calls = source, tokens, 0
        self.requests = []
        self.response = None
    def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        self.response = CompletionResponse(self.source,
            {'input_tokens': 2, 'output_tokens': self.tokens - 2, 'calls': 1}, self.provider_id)
        return self.response
    def lookup(self, request):
        return self.response


def assign(store, **kwargs):
    return R.assign(store, 'Change only wall height; preserve geometry and dependencies', worker_id='worker',
        base_revision=store.head().revision_id, instance_key='section', outputs=('wall',), **kwargs)


def test_full_target_values_and_referenced_level_reach_provider(store):
    task = assign(store)
    request = R._request_for(read_task(store, task), store).to_dict()
    context = json.loads(request['messages'][1]['content'].removeprefix('проект: '))
    wall = next(row for row in context['target_instance']['outputs'] if row['key'] == 'wall')
    assert wall['operation']['p0_mm'] == [1200, 2300]
    assert wall['operation']['base_offset_mm'] == 200
    assert any(row['operation']['op'] == 'create_level' and row['operation']['elev_mm'] == 0
               for row in context['dependencies'])
    assert 'ProjectStore' not in json.dumps(request)


def test_partial_operation_patch_preserves_omitted_fields_and_other_output(store):
    original = store.head().instances[1].to_dict()
    task, provider = assign(store), Provider()
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(1, 2048))
    assert result.refusal is None
    R.coordinate(store)
    current = store.head().instances[1].to_dict()
    expected = original['outputs'][0]['operation'].copy()
    expected['height_mm'] = 4100
    assert current['outputs'][0]['operation'] == expected
    assert current['outputs'][1] == original['outputs'][1]


def test_overrun_retains_all_reported_usage_not_clipped(store):
    provider = Provider(tokens=2148)
    with pytest.raises(R.BureauRefusal, match='token_budget_overrun'):
        R._ask(store, provider, CompletionRequest(({'role':'user','content':'request'},)), R.TeamBudget(2,2048))
    spent = R.spend(store)
    assert spent['tokens'] == spent['reported_tokens'] == 2148
    assert spent['unknown_tokens'] == 0


def test_failed_provider_keeps_unknown_reserve(store):
    class Lost(Provider):
        def complete(self, request):
            raise ProviderRefusal('response_lost', 'execution may already have occurred')
    with pytest.raises(ProviderRefusal):
        R._ask(store, Lost(), CompletionRequest(({'role':'user','content':'request'},)), R.TeamBudget(2,2048))
    spent = R.spend(store)
    assert spent['tokens'] == spent['unknown_tokens'] == 2048
    assert spent['reported_tokens'] == 0


def test_response_retained_before_sandbox_and_replay_has_no_call_or_execution(store, monkeypatch):
    import kir.sandbox
    task, provider = assign(store), Provider()
    real = kir.sandbox.execute_author_script
    def inspect(source, **kwargs):
        calls = read_task(store, task)['tool_calls']
        assert any(c['tool'] == 'llm.complete' and c['state'] == 'recorded' for c in calls)
        assert any(c['tool'] == 'author.python' and c['state'] == 'reserved' for c in calls)
        return real(source, **kwargs)
    monkeypatch.setattr(kir.sandbox, 'execute_author_script', inspect)
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert result.refusal is None
    before = R.spend(store)
    monkeypatch.setattr(kir.sandbox, 'execute_author_script', lambda *a, **k: pytest.fail('sandbox replayed'))
    again = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert again.proposal_id == result.proposal_id and again.refusal is None
    assert provider.calls == 1 and R.spend(store) == before


def test_stop_epoch_guard_is_atomic_for_new_event_but_not_exact_replay(store):
    task = assign(store)
    R._ensure_team(store)
    team = read_task(store, R.TEAM_TASK)
    current = read_task(store, task)
    command = dict(request_id='before-stop', expected_version=current['version'], generation=current['generation'],
        actor=current['actor'], notes={'saved': True}, expected_task_versions={R.TEAM_TASK: team['version']})
    checkpoint_task(store, task, **command)
    R.stop(store)
    assert not checkpoint_task(store, task, **command)['inserted']
    later = read_task(store, task)
    with pytest.raises(StoreConflict):
        checkpoint_task(store, task, request_id='after-stop', expected_version=later['version'],
            generation=later['generation'], actor=later['actor'], notes={'wrong': True},
            expected_task_versions={R.TEAM_TASK: team['version']})


@pytest.mark.parametrize('when', ['after_response', 'after_sandbox'])
def test_process_crash_resumes_retained_attempt_with_one_call_budget(store, tmp_path, monkeypatch, when):
    import os
    import subprocess
    import sys
    import kir.sandbox
    from kir.bureau.exchange import FileExchangeProvider
    task = assign(store)
    exchange = tmp_path / 'exchange'
    script = r'''
import json, os, sys
from kir.bureau import runner as R, attempt as A
from kir.bureau.exchange import FileExchangeProvider, REQUEST_SCHEMA
from kir.bureau.provider import request_key
from kir.project_store import ProjectStore
store=ProjectStore.open(sys.argv[1], readonly=False)
provider=FileExchangeProvider(sys.argv[3], timeout_s=1)
original=provider.complete
def fixture_reply(request):
    key=request_key(request)
    (provider.requests/(key+'.json')).write_text(json.dumps({'schema':REQUEST_SCHEMA,'request_id':key,**request.to_dict()}))
    (provider.responses/(key+'.json')).write_text(json.dumps({'request_id':key,'text':"program={'ops':[{'op':'create_wall','id':'wall','height_mm':4100}]}",'usage':{'input_tokens':2,'output_tokens':10,'calls':1},'provider_id':'claude-code-agent'}))
    return original(request)
provider.complete=fixture_reply
if sys.argv[4]=='after_response':
    def crash(*args, **kwargs): os._exit(81)
    A._finish=crash
else:
    guarded=A.guarded
    def crash(store, task, action, **kwargs):
        if action.__name__=='submit_task': os._exit(82)
        return guarded(store, task, action, **kwargs)
    A.guarded=crash
R.work(store,sys.argv[2],provider=provider,budget=R.TeamBudget(1,2048))
raise AssertionError('crash boundary not reached')
'''
    child = subprocess.run([sys.executable, '-c', script, str(store.path), task, str(exchange), when],
        capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), timeout=45)
    assert child.returncode == (81 if when == 'after_response' else 82), child.stdout + child.stderr
    reopened = ProjectStore.open(store.path, readonly=False)
    assert R.spend(reopened)['calls'] == 1
    provider = FileExchangeProvider(exchange)
    monkeypatch.setattr(provider, 'complete', lambda *_: pytest.fail('provider was invoked again'))
    if when == 'after_sandbox':
        monkeypatch.setattr(kir.sandbox, 'execute_author_script', lambda *a, **k: pytest.fail('sandbox was invoked again'))
    result = R.work(reopened, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert result.refusal is None and result.calls == 0 and result.replayed
    assert R.spend(reopened)['calls'] == 1 and R.spend(reopened)['estimated_tokens'] == 12
    assert len(read_task(reopened, task)['tool_calls']) == 2


def test_unknown_provider_outcome_only_looks_up_and_never_frees_reserve(store):
    class Lost(Provider):
        def complete(self, request):
            self.calls += 1
            raise ProviderRefusal('lost', 'unknown')
    task, provider = assign(store), Lost()
    first = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    second = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert first.refusal['code'] == second.refusal['code'] == 'provider_outcome_unresolved'
    assert provider.calls == 1 and R.spend(store)['unknown_tokens'] == 2048


def test_reply_after_Stop_is_retained_but_no_sandbox_starts(store, monkeypatch):
    import kir.sandbox
    task = assign(store)
    class Stopper(Provider):
        def complete(self, request):
            response = super().complete(request)
            R.stop(store)
            return response
    provider = Stopper()
    monkeypatch.setattr(kir.sandbox, 'execute_author_script', lambda *a, **k: pytest.fail('sandbox after Stop'))
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert result.refusal['code'] == 'team_stopped'
    calls = read_task(store, task)['tool_calls']
    assert len(calls) == 1 and calls[0]['state'] == 'recorded'
    assert calls[0]['output']['response']['text'] == provider.source
    assert R.spend(store)['reported_tokens'] == 12


@pytest.mark.parametrize('boundary', ['submit', 'decide'])
def test_Stop_commits_between_precheck_and_SQL_prevents_new_effect(store, monkeypatch, boundary):
    import kir.project_tasks as tasks
    task, provider = assign(store), Provider()
    original = tasks._mutate
    fired = []
    def stop_first(*args, **kwargs):
        if kwargs['kind'] == boundary and not fired:
            fired.append(True)
            R.stop(store)
        return original(*args, **kwargs)
    monkeypatch.setattr(tasks, '_mutate', stop_first)
    head = store.head().revision_id
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    if boundary == 'submit':
        assert result.refusal['code'] == 'team_stopped'
        assert read_task(store, task)['state'] == 'assigned'
    else:
        assert result.refusal is None
        decision = R.coordinate(store)
        assert decision.stopped and not decision.accepted
        assert read_task(store, task)['state'] == 'submitted'
    assert fired and store.head().revision_id == head
    R.resume(store, reason='Continue retained, already computed work')
    resumed = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert resumed.refusal is None
    assert R.coordinate(store).accepted == (task,)
    assert provider.calls == 1


def test_unrelated_epoch_change_retries_without_repeating_provider_or_sandbox(store, monkeypatch):
    import kir.project_tasks as tasks
    task, provider = assign(store), Provider()
    original = tasks._mutate
    fired = []
    def race(*args, **kwargs):
        if kwargs['kind'] == 'submit' and not fired:
            fired.append(True)
            R._append(store, {'independent_worker_note': 'no Stop, but epoch advanced'})
        return original(*args, **kwargs)
    monkeypatch.setattr(tasks, '_mutate', race)
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert result.refusal is None and provider.calls == 1
    assert len(read_task(store, task)['tool_calls']) == 2
    R.coordinate(store)
    head = store.head().revision_id
    R.stop(store)
    assert R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048)).replayed
    assert store.head().revision_id == head


def test_sealed_target_refuses_before_provider_or_charge(store):
    from kir.project import RecipePin
    head = store.head()
    module = ModuleDefinition('sealed', 'sealed_evaluation', RecipePin('historical_recipe()', 'a'*64))
    section = replace(head.instances[1], module_key='sealed', module_digest=None)
    candidate = head.revise(expected_revision=head.revision_id, modules=(*head.modules, module),
        instances=(head.instances[0], section))
    store.commit(candidate, expected_revision=head.revision_id)
    task, provider = assign(store), Provider()
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert result.refusal['code'] == 'sealed_target_requires_handoff'
    assert provider.calls == 0 and R.spend(store)['calls'] == 0


def test_explicit_field_removal_and_nested_field_preservation(store):
    task = assign(store, remove_fields={'wall': ['base_offset_mm']})
    provider = Provider()
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert result.refusal is None
    R.coordinate(store)
    wall = store.head().instances[1].outputs[0].operation
    assert 'base_offset_mm' not in wall and tuple(wall['p0_mm']) == (1200,2300)


def test_progress_checkpoint_cannot_erase_original_output_grant(store):
    task = assign(store)
    current = read_task(store, task)
    checkpoint_task(store, task, request_id='progress', expected_version=current['version'], generation=0,
        actor='worker', notes={'progress': 'read source; not a replacement grant'})
    result = R.work(store, task, provider=Provider("program={'ops':[{'op':'create_level','id':'foreign','elev_mm':0}]}"),
        budget=R.TeamBudget(1,2048))
    assert result.refusal['code'] == 'undeclared_output'
    python_call = next(call for call in read_task(store, task)['tool_calls'] if call['tool'] == 'author.python')
    assert python_call['state'] == 'recorded'
    assert python_call['output']['program']['ops'][0]['id'] == 'foreign'


def test_reassigned_generation_retains_spend_and_cannot_start_sandbox(store, monkeypatch):
    import kir.sandbox
    from kir.project_tasks import reassign_task
    task = assign(store)
    class Superseded(Provider):
        def complete(self, request):
            response = super().complete(request)
            current = read_task(store, task)
            reassign_task(store, task, request_id='handover', expected_version=current['version'], generation=0,
                actor='coordinator', new_actor='replacement', reason='Explicit reassignment')
            return response
    provider = Superseded()
    monkeypatch.setattr(kir.sandbox, 'execute_author_script', lambda *a, **k: pytest.fail('old generation computed'))
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(2,4096))
    assert result.refusal['code'] == 'generation_changed'
    assert R.spend(store)['reported_tokens'] == 12
    assert read_task(store, task)['tool_calls'][0]['state'] == 'superseded_unresolved'
    next_worker = Provider()
    result = R.work(store, task, provider=next_worker, budget=R.TeamBudget(2,4096))
    assert result.refusal['code'] == 'task_tool_budget_exhausted' and next_worker.calls == 0


def test_replanning_contains_full_before_current_and_proposed_values(store):
    base = store.head().revision_id
    first = assign(store)
    assert R.work(store, first, provider=Provider(), budget=R.TeamBudget(3,8192)).refusal is None
    R.coordinate(store)
    stale = R.assign(store, 'Alternative height 4300', worker_id='second', base_revision=base,
        instance_key='section', outputs=('wall',))
    provider = Provider("program={'ops':[{'op':'create_wall','id':'wall','height_mm':4300}]}")
    assert R.work(store, stale, provider=provider, budget=R.TeamBudget(3,8192)).refusal is None
    decided = R.coordinate(store)
    assert decided.conflicted == (stale,) and len(decided.replanned) == 1
    request = R._request_for(read_task(store, decided.replanned[0]), store)
    context = json.loads(request.messages[1]['content'].removeprefix('проект: '))
    conflict = context['conflict']
    def height(side):
        return next(row['operation']['height_mm'] for row in conflict[side]['outputs'] if row['key']=='wall')
    assert (height('before'), height('current'), height('proposed')) == (3000,4100,4300)


def test_legacy_assigned_task_does_not_get_new_grants_silently(store):
    from kir.project_tasks import create_task
    from kir.project_merge import ProposalScope
    create_task(store, task_id='legacy', base_revision=store.head().revision_id, actor='worker', objective='Old task',
        scope=ProposalScope(instances=('section',)), tools=('author.python',), budgets={'max_tool_calls':1})
    provider = Provider()
    result = R.work(store, 'legacy', provider=provider, budget=R.TeamBudget(1,2048))
    assert result.refusal['code'] == 'legacy_task_requires_new_assignment'
    assert provider.calls == 0 and R.spend(store)['calls'] == 0


def test_reassignment_after_sandbox_receipt_returns_named_generation_refusal(store, monkeypatch):
    import kir.bureau.attempt as A
    from kir.project_tasks import reassign_task
    task, provider = assign(store), Provider()
    original = A._finish
    def reassign_after_finish(store, prior, identifier, output):
        result = original(store, prior, identifier, output)
        if identifier.startswith('bureau-python-'):
            reassign_task(store, task, request_id='same-actor-new-generation',
                expected_version=result['version'], generation=result['generation'], actor='coordinator',
                new_actor='worker', reason='Generation changed after the sandbox fact was retained')
        return result
    monkeypatch.setattr(A, '_finish', reassign_after_finish)
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert result.refusal['code'] == 'generation_changed' and result.proposal_id is None
    assert read_task(store, task)['state'] == 'assigned'
    assert provider.calls == 1 and R.spend(store)['reported_tokens'] == 12


def test_a_reassigned_task_refuses_by_generation_even_when_the_sandbox_output_is_not_a_program(store, monkeypatch):
    """🔴 FLAKE MECHANISM 07.09.2026, MADE DETERMINISTIC.

    In strip G2 under swap (available < 1 GB, reopen 10 000 bodies nearby) the test
    above expected `generation_changed` but got `answer_is_not_a_program`: the sandbox
    did not make it within its limit, the output was "not a program", and the code returned this
    refusal BEFORE the generation check. Eight runs without swap did not show it —
    here the same thing is achieved without swap: the model's answer is deliberately not a program,
    and the assignment is reassigned after the sandbox fact is held. Generation is judged
    BEFORE content: the held output belongs to the old assignment, whatever it
    may be.
    """
    import kir.bureau.attempt as A
    from kir.project_tasks import reassign_task
    task, provider = assign(store), Provider(source="это проза, а не программа")
    original = A._finish
    def reassign_after_finish(store, prior, identifier, output):
        result = original(store, prior, identifier, output)
        if identifier.startswith('bureau-python-'):
            assert output['refusal']['code'] == 'answer_is_not_a_program', output['refusal']
        # the sandbox's refusal name travels alongside it: prose and limit (cpu/wall) are distinguishable
            assert output['refusal']['sandbox'], output['refusal']
            reassign_task(store, task, request_id='same-actor-new-generation',
                expected_version=result['version'], generation=result['generation'], actor='coordinator',
                new_actor='worker', reason='Generation changed after the sandbox fact was retained')
        return result
    monkeypatch.setattr(A, '_finish', reassign_after_finish)
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert result.refusal['code'] == 'generation_changed', result.refusal
    assert result.proposal_id is None and read_task(store, task)['state'] == 'assigned'


@pytest.mark.parametrize('row', [None, {}, {'calls':'0','tokens':0,'state':'actual'},
    {'calls':0,'tokens':0,'state':'unrecognized'}, {'calls':False,'tokens':0,'state':'actual'}])
def test_malformed_legacy_usage_is_not_known_zero(store, row):
    R._append(store, {'bureau_spend': row})
    with pytest.raises(R.BureauRefusal, match='budget_ledger_invalid'):
        R.spend(store)


@pytest.mark.parametrize('basis', [None, 'money', '', 17])
def test_unknown_attempt_basis_is_not_reported_tokens(store, basis):
    R._append(store, {'bureau_spend': {'attempt_id':'a'*64,'calls':1,'tokens':100,'state':'reserved'}})
    R._append(store, {'bureau_spend': {'attempt_id':'a'*64,'calls':1,'tokens':12,'state':'actual',
                                      'usage_basis':basis,'provider_id':'test'}})
    with pytest.raises(R.BureauRefusal, match='budget_ledger_invalid'):
        R.spend(store)


def test_legal_legacy_negative_correction_is_retained_without_writes(store):
    R._append(store, {'bureau_spend': {'calls':1,'tokens':2048,'state':'reserved'}})
    R._append(store, {'bureau_spend': {'calls':0,'tokens':-1948,'state':'actual','provider_id':'historical'}})
    before = store.path.read_bytes()
    used = R.spend(store)
    assert used['calls'] == 1 and used['tokens'] == used['legacy_tokens'] == 100
    assert store.path.read_bytes() == before


def test_impossible_legacy_prefix_cannot_be_hidden_by_a_later_reservation(store):
    for row in ({'calls':1,'tokens':100,'state':'reserved'},
                {'calls':0,'tokens':-101,'state':'actual','provider_id':'historical'},
                {'calls':1,'tokens':100,'state':'reserved'}):
        R._append(store, {'bureau_spend': row})
    with pytest.raises(R.BureauRefusal, match='budget_ledger_invalid'):
        R.spend(store)


def test_sensitive_context_keys_are_redacted_but_geometry_stays_exact(store):
    head = store.head()
    section = replace(head.instances[1], parameters={'client_secret':'SENTINEL-SECRET',
        'AZURE_OPENAI_API_KEY':'SENTINEL-AZURE', 'nested':{'anthropic_api_key':'SENTINEL-ANTHROPIC'}, 'height_mm':3000})
    candidate = head.replace_instance(section, expected_revision=head.revision_id)
    store.commit(candidate, expected_revision=head.revision_id)
    request = R._request_for(read_task(store, assign(store)), store).to_dict()
    text = json.dumps(request)
    assert 'SENTINEL' not in text
    context = json.loads(request['messages'][1]['content'].removeprefix('проект: '))
    assert context['target_instance']['parameters']['height_mm'] == 3000


def test_explicit_admin_assignment_may_queue_while_Stop_without_computation(store):
    R.stop(store)
    task, provider = assign(store), Provider()
    assert read_task(store, task)['state'] == 'assigned' and R.is_stopped(store)
    result = R.work(store, task, provider=provider, budget=R.TeamBudget(1,2048))
    assert result.refusal['code'] == 'team_stopped' and provider.calls == 0
    assert R.spend(store)['calls'] == 0
