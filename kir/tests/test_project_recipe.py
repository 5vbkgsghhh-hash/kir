"""Required-policy benign sandbox runs, then inert one-instance projection."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from kir.compiler import plan_program
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision, _canonical, _hash, output_id
from kir.project_merge import ChangeProposal, ProposalScope, merge_proposal
from kir.project_recipe import (RecipeBindingError, RECIPE_LANGUAGE, bind_recipe_result)
from kir.sandbox import SandboxPolicy, execute_author_script, params_digest


SOURCE = '''
pid = param('project_id', 'unused')
iid = param('instance_key', 'unused')
program(intent='')
level_id = project_output_id(pid, iid, 'level')
wall_id = project_output_id(pid, iid, 'wall')
create_level(id=level_id, elev_mm=param('elevation', 3000.0))
create_wall(id=wall_id, p0_mm=[0, 0], p1_mm=[4000, 0], height_mm=2800,
            level={'by': 'ref', 'value': level_id})
'''
POLICY = SandboxPolicy(dsl_module=RECIPE_LANGUAGE)


def base():
    return ProjectRevision('recipe-project', [ModuleDefinition('old')], [
        ModuleInstance('a', 'old', [NamedOutput('old', {'op': 'create_level', 'elev_mm': 0})]),
        ModuleInstance('b', 'old', [NamedOutput('other', {'op': 'create_level', 'elev_mm': -3000})]),
    ])


def inputs(project):
    return {'project_id': project.project_id, 'instance_key': 'a', 'elevation': 3000.0}


def names(project, *keys):
    return {key: output_id(project.project_id, 'a', key) for key in keys}


@pytest.fixture(scope='module')
def observed():
    project = base()
    result = execute_author_script(SOURCE, policy=POLICY, params=inputs(project))
    assert result.ok, result.as_dict()
    return project, result


def bind(observed, **kwargs):
    project, result = observed
    values = dict(instance_key='a', module_key='recipe-a', source=SOURCE,
                  parameters=inputs(project), output_bindings=names(project, 'level', 'wall'),
                  result=result, author='worker-a', reason='evaluated one complete instance')
    values.update(kwargs)
    return bind_recipe_result(project, **values)


def test_actual_required_sandbox_result_becomes_a_lossless_named_instance_proposal(observed):
    project, result = observed
    before = project.dumps()
    bound = bind(observed)
    assert bound.projection_refusal is None and bound.proposal is not None
    candidate = bound.proposal.candidate
    assert candidate.parent_revision == project.revision_id and project.dumps() == before
    assert candidate.instances[1].to_dict() == project.instances[1].to_dict()
    assert candidate.to_program()['ops'][:2] == result.to_program()['ops']
    assert candidate.to_program()['ops'][1]['level']['value'] == names(project, 'level')['level']
    assert [o.key for o in candidate.instances[0].outputs] == ['level', 'wall']
    definition = candidate.modules[-1]
    assert definition.key == 'recipe-a' and definition.owner == 'sealed_evaluation'
    assert definition.recipe.source == SOURCE and definition.recipe.entrypoint == 'script'
    assert definition.recipe.source_digest == result.author_digest
    assert definition.recipe.environment_digest == result.env_digest
    assert candidate.instances[0].to_dict()['parameters'] == inputs(project)
    assert bound.proposal.scope == ProposalScope(instances=('a',), modules=('recipe-a',), project_fields=('module_order',))
    assert plan_program(candidate.to_program()).ops  # actual compiler, not a native execution
    assert bound.evaluation['program'] == result.to_program()
    assert bound.evaluation['source'] == SOURCE and bound.evaluation['parameters'] == inputs(project)
    assert bound.evaluation['sandbox_receipt']['lineage'] == result.lineage
    assert bound.evaluation['sandbox_receipt']['environment'] == result.environment
    assert 'ops' not in bound.evaluation['sandbox_receipt'] and 'envelope' not in bound.evaluation['sandbox_receipt']
    assert bound.evaluation['claims']['binding_replay'] == 'not_run'


def test_recipe_language_preserves_all_existing_names_and_harvest_hooks():
    from kir.course import language
    from kir import recipe_language
    assert set(recipe_language.__all__) == set(language.__all__) | {'project_output_id'}
    assert all(getattr(recipe_language, name) is getattr(language, name) for name in language.__all__)
    assert recipe_language.take_ops is language.take_ops
    assert recipe_language.warm_for_source is language.warm_for_source
    assert recipe_language.project_output_id('p', 'i', 'o') == output_id('p', 'i', 'o')


def test_ids_do_not_consume_one_scalar_parameter_per_output():
    source = '''
pid = param('project_id', 'unused')
iid = param('instance_key', 'unused')
program(intent='')
for number in range(70):
    create_level(id=project_output_id(pid, iid, 'level_' + str(number)), elev_mm=number * 3000)
'''
    project = base()
    parameters = {'project_id': project.project_id, 'instance_key': 'a'}
    result = execute_author_script(source, policy=POLICY, params=parameters)
    assert result.ok, result.as_dict()
    assert len(result.params) == 2 and len(result.ops) == 70
    bound = bind_recipe_result(project, instance_key='a', module_key='many-levels', source=source,
        parameters=parameters, output_bindings=names(project, *(f'level_{n}' for n in range(70))),
        result=result, author='worker-a', reason='seventy named outputs from two namespace parameters')
    assert bound.projection_refusal is None and len(bound.proposal.candidate.instances[0].outputs) == 70
    assert len(plan_program(bound.proposal.candidate.to_program(), bulk=True).ops) == 71


def test_existing_phase_language_preserves_cross_phase_refs_and_refuses_instance_projection():
    source = '''
pid = param('project_id', 'unused')
iid = param('instance_key', 'unused')
program(intent='')
with phase('levels'):
    level = create_level(id=project_output_id(pid, iid, 'level'), elev_mm=param('elevation', 3000.0))
with phase('walls'):
    create_wall(id=project_output_id(pid, iid, 'wall'), p0_mm=[0, 0], p1_mm=[4000, 0], height_mm=2800, level=level)
'''
    project = base()
    result = execute_author_script(source, policy=POLICY, params=inputs(project))
    assert result.ok, result.as_dict()
    program = result.to_program()
    assert len(program['phases']) == 2
    assert program['ops'][1]['level']['by'] == 'phase_result'
    assert program['ops'][1]['level']['value'] == output_id(project.project_id, 'a', 'level')
    bound = bind_recipe_result(project, instance_key='a', module_key='phased', source=source,
        parameters=inputs(project), output_bindings=names(project, 'level', 'wall'), result=result,
        author='worker-a', reason='phase contract remains intact')
    assert bound.proposal is None and bound.projection_refusal.code == 'recipe_envelope_unsupported'
    assert bound.evaluation['program'] == program


@pytest.mark.parametrize('field,value', [
    ('defaults', {'level': {'by': 'element_id', 'value': 123}}),
    ('phases', [{'name': 'phase-one', 'ops': []}]),
    ('units', [{'id': 'unit-one', 'ops': []}]),
    ('allow_destructive', False), ('metadata', {'retain': [True, 1, 1.0]}),
])
def test_unsupported_envelope_survives_actual_sandbox_and_projection_refusal(field, value):
    project = base()
    source = "pid=param('project_id','unused')\niid=param('instance_key','unused')\n" + (
        "result={'ir_version':'1.0','intent':'','ops':[{'op':'create_level',"
        "'id':project_output_id(pid,iid,'level'),'elev_mm':3000}]," + repr(field) + ':' + repr(value) + '}\n')
    parameters = {'project_id': project.project_id, 'instance_key': 'a'}
    result = execute_author_script(source, policy=POLICY, params=parameters)
    assert result.ok, result.as_dict()
    bound = bind_recipe_result(project, instance_key='a', module_key='recipe-a', source=source,
        parameters=parameters, output_bindings=names(project, 'level'), result=result, author='a', reason='full IR retained')
    assert bound.proposal is None and bound.projection_refusal.code == 'recipe_envelope_unsupported'
    assert bound.evaluation['program'] == result.to_program()
    assert _canonical(bound.evaluation['program'][field]) == _canonical(value)


def test_actual_refused_execution_is_retained_without_an_invented_program():
    project = base()
    source = "raise ValueError('controlled recipe refusal')"
    result = execute_author_script(source, policy=POLICY, params=inputs(project))
    assert not result.ok
    bound = bind_recipe_result(project, instance_key='a', module_key='recipe-a', source=source,
        parameters=inputs(project), output_bindings=names(project, 'level'), result=result, author='a', reason='refusal')
    assert bound.proposal is None and bound.projection_refusal.code == 'recipe_execution_refused'
    assert bound.evaluation['program'] is None and bound.evaluation['sandbox_receipt']['refusal'] == result.refusal.as_dict()


@pytest.mark.parametrize('fault,code', [
    ('source', 'recipe_source_mismatch'), ('params', 'recipe_parameters_mismatch'),
    ('namespace', 'recipe_namespace_mismatch'), ('language', 'recipe_language_mismatch'),
    ('environment', 'recipe_environment_unavailable'), ('drift', 'recipe_environment_changed'),
    ('left_behind', 'recipe_left_behind_programs'), ('model', 'recipe_context_unsupported'),
    ('building', 'recipe_context_unsupported'),
])
def test_association_failures_do_not_change_or_discard_the_observed_program(observed, fault, code):
    project, original = observed
    result, parameters, source = deepcopy(original), inputs(project), SOURCE
    if fault == 'source': source += '\n# changed source\n'
    elif fault == 'params': parameters['elevation'] = 3100.0
    elif fault == 'namespace':
        parameters['instance_key'] = 'foreign'
        result.params_digest = params_digest(parameters)
    elif fault == 'language': result.isolation['dsl_module'] = 'kir.course.language'
    elif fault == 'environment': result.environment['python'] = 'changed'
    elif fault == 'drift': result.isolation['environment_replay'] = 'CHANGED'
    elif fault == 'left_behind': result.left_behind = [{'ops': 1, 'intent': 'earlier'}]
    elif fault == 'model': result.model_digest = 'model-input'
    else: result.building_digest = 'building-input'
    bound = bind((project, result), source=source, parameters=parameters)
    assert bound.proposal is None and bound.projection_refusal.code == code
    assert bound.evaluation['program'] == original.to_program()


@pytest.mark.parametrize('fault', ['missing', 'extra', 'noncanonical', 'unhashable', 'empty'])
def test_exact_named_output_coverage_is_required(observed, fault):
    project, _ = observed
    mapping = names(project, 'level', 'wall')
    if fault == 'missing': mapping.pop('wall')
    elif fault == 'extra': mapping.update(names(project, 'extra'))
    elif fault == 'noncanonical': mapping['level'] = 'local-level'
    elif fault == 'unhashable': mapping['level'] = []
    else: mapping = {}
    bound = bind(observed, output_bindings=mapping)
    assert bound.proposal is None and bound.projection_refusal.code == 'recipe_output_bindings_mismatch'


def test_shared_changed_module_refuses_and_new_module_requires_an_independent_grant(observed):
    project, _ = observed
    refused = bind(observed, module_key='old')
    assert refused.projection_refusal.code == 'recipe_shared_module_change' and refused.proposal is None
    proposal = bind(observed).proposal
    with pytest.raises(ValueError, match='write grant'):
        merge_proposal(proposal, project, authorized_scope=ProposalScope(instances=('a',)))
    assert merge_proposal(proposal, project, authorized_scope=proposal.scope).clean


def test_same_observed_pin_can_be_reused_without_module_or_order_scope(observed):
    project, result = observed
    first = bind(observed)
    second = bind((first.proposal.candidate, result))
    assert second.projection_refusal is None
    assert second.proposal.scope == ProposalScope(instances=('a',))
    assert second.proposal.candidate.modules == first.proposal.candidate.modules


def test_evaluation_and_proposal_roundtrip_are_inert_and_detached(observed, monkeypatch):
    bound = bind(observed)
    before = bound.to_dict()
    detached = bound.evaluation
    detached['program']['ops'][0]['elev_mm'] = 9999
    detached['sandbox_receipt']['environment'].clear()
    assert bound.to_dict() == before
    import kir.sandbox
    monkeypatch.setattr(kir.sandbox, 'execute_author_script', lambda *_a, **_k: pytest.fail('load executed recipe'))
    loaded = ChangeProposal.loads(bound.proposal.dumps())
    assert loaded.candidate.dumps() == bound.proposal.candidate.dumps()
    assert json.loads(json.dumps(bound.to_dict())) == bound.to_dict()


def test_existing_unrelated_metadata_is_not_overwritten(observed):
    project, result = observed
    altered = project.replace_instance(replace(project.instances[0], metadata={'recipe_evaluation': 'user data'}),
                                       expected_revision=project.revision_id)
    bound = bind((altered, result))
    assert bound.projection_refusal.code == 'recipe_metadata_occupied'


def test_mutated_digest_bearing_result_is_not_relabelled_as_evaluated(observed):
    project, result = observed
    mutated = deepcopy(result)
    mutated.ops[0]['elev_mm'] = 4000
    with pytest.raises(RecipeBindingError): bind((project, mutated))
