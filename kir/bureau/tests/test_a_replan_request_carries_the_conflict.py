"""Mandate F7: replanning carries the conflict's content to the MODEL, not just a paraphrase of it.

🔴 WHAT EXACTLY WAS MEASURED AND WHY. Live run run-3 (07.09.2026, respondent —
a Sonnet agent): "the replan request's `conflict` field was in fact
absent." Reading the two exchange files split apart TWO different subjects:

* `requests/d7cdf7b4*.json` — an instrument assignment from `FX.OBJECTIVES["replan"]`,
  set up by a plain `assign()` WITHOUT `conflict=`. This is the instrument's own scene, not the product.
* `requests/22baccc7*.json` — the ACTUAL product replanning: `conflict`
  is present, with `issues`/`before`/`current`/`proposed` inside it.

But even for a genuine conflict the model still cannot name the subject EXACTLY:
the three sides' values arrive WITHOUT a revision name (which of them won and
which was rejected — only by key order), and the outputs are WITHOUT a project
address, even though `target_instance` has an address. The model replies with a patch keyed by
output and refers to it by address; a nameless side and an addressless output are
an invitation to guess, and F7 demands CONTENT.
"""
import json

import pytest

from kir.bureau import runner as R
from kir.bureau.provider import CompletionResponse
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id
from kir.project_store import ProjectStore, TASK_STORE_SCHEMA
from kir.project_tasks import read_task


@pytest.fixture
def store(tmp_path):
    source = ProjectRevision('bureau-replan', [ModuleDefinition('explicit')], [
        ModuleInstance('datum', 'explicit', {'level': {'op': 'create_level', 'elev_mm': 0}}),
        ModuleInstance('section', 'explicit', {
            'wall': {'op': 'create_wall', 'p0_mm': [0, 0], 'p1_mm': [6000, 0],
                     'height_mm': 3000, 'level': {'by': 'ref', 'value': output_id(
                         'bureau-replan', 'datum', 'level')}}})])
    return ProjectStore.create(tmp_path / 'project.sqlite', source, schema=TASK_STORE_SCHEMA)


class Provider:
    provider_id = 'synthetic-test'

    def __init__(self, height):
        self.source = ("program={'ops':[{'op':'create_wall','id':'wall','height_mm':%d}]}" % height)
        self.calls, self.response = 0, None

    def complete(self, request):
        self.calls += 1
        self.response = CompletionResponse(
            self.source, {'input_tokens': 2, 'output_tokens': 10, 'calls': 1}, self.provider_id)
        return self.response

    def lookup(self, request):
        return self.response


def _replanned_context(store):
    """Two workers from ONE head -> one accepted, the other conflicts -> replan."""
    budget = R.TeamBudget(max_calls=8, max_tokens=8000)
    base = store.head().revision_id
    first = R.assign(store, 'Поднять стену до 4100', worker_id='worker-a',
                     base_revision=base, instance_key='section', outputs=('wall',))
    second = R.assign(store, 'Поднять стену до 5200', worker_id='worker-b',
                      base_revision=base, instance_key='section', outputs=('wall',))
    assert R.work(store, first, provider=Provider(4100), budget=budget).refusal is None
    assert R.work(store, second, provider=Provider(5200), budget=budget).refusal is None
    decisions = R.coordinate(store)
    assert len(decisions.accepted) == 1 and len(decisions.conflicted) == 1
    assert len(decisions.replanned) == 1, 'перепланирование обязано завестись'
    task = read_task(store, str(decisions.replanned[0]))
    request = R._request_for(R._configured_task(store, task), store).to_dict()
    return json.loads(request['messages'][1]['content'].removeprefix('проект: ')), store.head()


def test_replan_context_names_the_reason_and_the_base_revision(store):
    context, head = _replanned_context(store)
    conflict = context.get('conflict')
    assert conflict, 'F7: перепланирование обязано нести структурированный конфликт'
    kinds = [issue.get('kind') for issue in conflict['issues']]
    assert 'modify_modify' in kinds, kinds
    assert conflict['issues'][0]['path'] == 'instances/section'
    # The new assignment is counted FROM THE HEAD AFTER the conflict, not from the one
    # the worker was wrong about — and the model must see exactly which one.
    assert context['base_revision'] == head.revision_id


def test_each_conflict_side_names_its_revision(store):
    """The winning and rejected sides are distinguishable BY NAME, not by key order."""
    context, head = _replanned_context(store)
    conflict = context['conflict']
    for side in ('before', 'current', 'proposed'):
        assert 'revision_id' in conflict[side], f'сторона `{side}` не назвала свою ревизию'
        assert len(conflict[side]['revision_id']) == 64
    assert conflict['current']['revision_id'] == head.revision_id, 'победившая сторона — голова'
    assert conflict['proposed']['revision_id'] != conflict['current']['revision_id']
    assert conflict['before']['revision_id'] != conflict['current']['revision_id']
    # Both sides' values are in place: the dispute is about the wall's height.
    won = next(row for row in conflict['current']['outputs'] if row['key'] == 'wall')
    lost = next(row for row in conflict['proposed']['outputs'] if row['key'] == 'wall')
    assert won['operation']['height_mm'] != lost['operation']['height_mm']


def test_conflicting_outputs_carry_their_project_addresses(store):
    """The model refers by ADDRESS; an addressless output in the conflict is an invitation to guess."""
    context, _ = _replanned_context(store)
    conflict = context['conflict']
    address = output_id('bureau-replan', 'section', 'wall')
    for side in ('before', 'current', 'proposed'):
        row = next(item for item in conflict[side]['outputs'] if item['key'] == 'wall')
        assert row.get('output_id') == address, f'сторона `{side}`: выход без проектного адреса'
    # The same address is already printed at the target — the conflict must speak the same language.
    target = next(item for item in context['target_instance']['outputs'] if item['key'] == 'wall')
    assert target['output_id'] == address
