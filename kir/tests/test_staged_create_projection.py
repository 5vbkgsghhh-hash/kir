"""A -> B pure preparation: real compiler/archive codecs, synthetic native facts."""
from copy import copy, deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from uuid import uuid4

import pytest

from kir.contracts import ElementIdentityProof
from kir.create_publication import bind_create_receipt
from kir.element_query import TYPE_DEFINITION_STATE_SCHEMA
from kir.geometry_materialization import materialize_selection
from kir.project import ModuleInstance, _hash, _object, _thaw, output_id
from kir.project_execution_partition import partition_project_execution
from kir.project_selection import select_project_instances
from kir.project_submission import bind_selected_project_submission
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution
from kir.saved_execution import SavedExecutionRecord
from kir.staged_create_projection import (StagedCreateProjection, StagedProjectionError,
    bind_staged_create_projection, prepare_staged_create)
from kir.tests.test_project_execution_partition import shared_project
from kir.tests.test_revit_level_update import response_for
from kir.tests.test_revit_observation import row as base_row, unavailable
from kir.type_definition_observation import prepare_type_definition_observation, parse_type_definition_observation


def case(*, floor=False, mutate_observed=None, revision=9, original_reused=False, material=False, level_name=None):
    project = shared_project(floor=floor)
    outputs = list(project.instances[0].outputs)
    if material:
        op = _thaw(outputs[1].operation)
        op['layers'][0]['material'] = 'Concrete'
        outputs[1] = replace(outputs[1], operation=op)
    if level_name is not None:
        outputs[0] = replace(outputs[0], operation={**_thaw(outputs[0].operation), 'name': level_name})
    if material or level_name is not None:
        instance = replace(project.instances[0], outputs=tuple(outputs))
        project = project.replace_instance(instance, expected_revision=project.revision_id)
    target = RuntimeTarget(str(uuid4()), str(uuid4()), '2023')
    credentials = SessionCredentials(target, str(uuid4()), 'synthetic-private-not-in-core')
    source = materialize_selection(project, select_project_instances(project, instance_keys=['A']), {})
    prepared = prepare_execution(source.planned, target=target, precondition=ContextPrecondition('native-doc', 8),
        operation_id=str(uuid4()))
    submission = bind_selected_project_submission(project, source, prepared)
    archive = SavedExecutionRecord.capture_project(prepared, submission)
    result = {'ok': True}
    for index, operation in enumerate(source.planned.to_ops()):
        row = {'id': str(700 + index),
            'element_identity': ElementIdentityProof(700 + index, f'uid-{index}', 'a' * 32).to_dict(),
            'element_identity_status': 'captured', 'element_identity_reason': None}
        if operation['op'] == 'create_wall_type': row['duplicated'] = not original_reused
        result[operation['id']] = row
    response = response_for(prepared, credentials, result, changes={'added': [700, 702] if original_reused else [700, 701, 702],
        'modified': [], 'deleted': [], 'transaction_names': ['KIR'], 'truncated': False})
    bound = bind_create_receipt(archive, json.dumps(response), credentials=credentials, request_id=response['request_id'])
    selected = materialize_selection(project, select_project_instances(project, instance_keys=['B']), {})
    imports = [operation['id'] for operation in source.to_program()['ops'][:2]]
    partition = partition_project_execution(project, selected, import_output_ids=imports)
    observed = {}
    level = base_row('uid-0', is_level=True)
    level.update(schema_version=TYPE_DEFINITION_STATE_SCHEMA,
        element_identity=ElementIdentityProof(1700, 'uid-0', 'b' * 32).to_dict(),
        type_definition={'status': 'not_applicable', 'reason': 'unsupported_element_kind', 'value': None})
    level['level'].update(project_elevation_mm=0, reported_elevation_mm=0)
    level['level']['elevation_parameter']['value_internal_feet'] = 0
    if level_name is not None: level['name'] = level_name
    observed['uid-0'] = level
    kind = 'floor' if floor else 'wall'
    typed = base_row('uid-1', is_level=False)
    typed.update(schema_version=TYPE_DEFINITION_STATE_SCHEMA, name='AuthoredSharedType',
        element_identity=ElementIdentityProof(1701, 'uid-1', 'b' * 32).to_dict(),
        type_state={'status': 'none', **unavailable()},
        type_definition={'status': 'observed', 'reason': None, 'value': {
            'host_kind': kind, 'wall_kind': 'Basic' if kind == 'wall' else None,
            'is_vertically_compound': False, 'is_vertically_homogeneous': True,
            'name': 'AuthoredSharedType', 'total_width_mm': 200,
            'layers': [{'width_mm': 200, 'function': 'Structure', 'material_id': -1,
                'material_name': None, 'material_identity': None, 'material_name_match_count': None}]}})
    observed['uid-1'] = typed
    if material:
        typed['type_definition']['value']['layers'][0].update(material_id=5000, material_name='Concrete',
            material_identity=ElementIdentityProof(5000, 'material-uid', 'c' * 32).to_dict(), material_name_match_count=1)
    if mutate_observed: mutate_observed(observed)
    observation = observe_rows(observed, credentials, revision)
    return {'project': project, 'partition': partition, 'archive': archive, 'bound': bound,
        'imports': {oid: (project, archive, bound) for oid in imports}, 'observation': observation,
        'credentials': credentials, 'observed_rows': observed, 'response': response}


def observe_rows(rows, credentials, revision=9, *, target=None, document='native-doc'):
    query = prepare_type_definition_observation(list(rows), target=target or credentials.target,
        precondition=ContextPrecondition(document, revision), operation_id=str(uuid4()))
    auth = SessionCredentials(query.target, credentials.session_id, credentials.token)
    response = response_for(query, auth, {f'type_definition_{i}': row for i, row in enumerate(rows.values())},
        changes={'added': [], 'modified': [], 'deleted': [], 'transaction_names': [], 'truncated': False})
    return parse_type_definition_observation(query, json.dumps(response), credentials=auth, request_id=response['request_id'])


def project(value, **kwargs):
    args = {'import_sources': value['imports'], 'observation': value['observation']}
    args.update(kwargs)
    return bind_staged_create_projection(value['partition'], **args)


@pytest.mark.parametrize('floor', [False, True])
@pytest.mark.parametrize('isolation', ['atomic', 'per_op'])
def test_A_to_B_compiles_only_new_consumer_and_guards_original_UIDs_at_exact_C0(floor, isolation):
    value = case(floor=floor)
    before = value['partition'].to_dict(), value['archive']._raw, value['bound'].to_dict()
    projection = project(value, isolation=isolation)
    assert projection.partition.materialization.planned.source_op_count == 3
    assert projection.runtime_plan.source_op_count == len(projection.runtime_program['ops']) == 1
    operation = projection.runtime_program['ops'][0]
    assert operation['level'] == {'by': 'element_id', 'value': 1700}
    assert operation['type'] == {'by': 'element_id', 'value': 1701}
    assert operation['id'] == output_id(value['project'].project_id, 'B', 'body')
    original = value['partition'].to_dict()['symbolic_export_ops'][0]
    assert {k: v for k, v in original.items() if k not in ('level', 'type')} == {
        k: v for k, v in operation.items() if k not in ('level', 'type')}
    assert len(projection.core['projection_table']) == 2
    assert {p.unique_id for p in projection.expected_identities} == {'uid-0', 'uid-1', 'type-uid'}
    assert projection.core['observation'] == value['observation'].to_dict()
    assert projection.core['required_import_unique_ids'] == ['uid-0', 'uid-1']
    assert projection.association_digest == _hash(projection.core)
    prepared = prepare_staged_create(projection, operation_id=str(uuid4()))
    assert prepared.precondition is value['observation'].precondition
    assert prepared.precondition.revision == 9
    assert prepared.association_digest == projection.association_digest
    assert prepared.expected_identities == projection.expected_identities
    assert prepared.planned.source_op_count == 1
    assert ('new SubTransaction(' in prepared.source) == (isolation == 'per_op')
    assert 'synthetic-private' not in json.dumps(projection.to_dict())
    assert before == (value['partition'].to_dict(), value['archive']._raw, value['bound'].to_dict())


@pytest.mark.parametrize('fault', ['width', 'total', 'function', 'name', 'kind', 'unavailable'])
def test_each_required_type_clause_must_match(fault):
    def mutate(rows):
        definition = rows['uid-1']['type_definition']
        value = definition['value']
        if fault == 'width': value['layers'][0]['width_mm'] = 250; value['total_width_mm'] = 250
        elif fault == 'total': value['total_width_mm'] = 201
        elif fault == 'function': value['layers'][0]['function'] = 'Finish1'
        elif fault == 'name': value['name'] = rows['uid-1']['name'] = 'Renamed'
        elif fault == 'kind': value.update(host_kind='floor', wall_kind=None)
        else: definition.update(status='unavailable', reason='definition_getter_failed', value=None)
    with pytest.raises(StagedProjectionError, match='staged_import_definition_mismatch'):
        project(case(mutate_observed=mutate))


def test_level_project_elevation_drift_refuses_even_with_matching_type():
    def mutate(rows): rows['uid-0']['level'].update(project_elevation_mm=3, reported_elevation_mm=3)
    with pytest.raises(StagedProjectionError, match='staged_import_level_mismatch'):
        project(case(mutate_observed=mutate))


@pytest.mark.parametrize('revision', [7, 8])
def test_created_import_requires_observation_after_original_input(revision):
    with pytest.raises(StagedProjectionError, match='staged_import_observation_too_old'):
        project(case(revision=revision))


@pytest.mark.parametrize('fault', ['runtime', 'document'])
def test_foreign_C0_never_rebinds_original_import(fault):
    value = case()
    observation = observe_rows(value['observed_rows'], value['credentials'],
        target=replace(value['credentials'].target, instance_id=str(uuid4())) if fault == 'runtime' else None,
        document='foreign' if fault == 'document' else 'native-doc')
    with pytest.raises(StagedProjectionError, match='staged_import_context_mismatch'):
        project(value, observation=observation)


@pytest.mark.parametrize('fault', ['extra', 'missing', 'dictionary_not_original_tuple'])
def test_import_mapping_is_explicit_exact_and_typed(fault):
    value = case()
    imports = dict(value['imports'])
    if fault == 'extra': imports['unknown'] = next(iter(imports.values()))
    elif fault == 'missing': imports.pop(next(iter(imports)))
    else: imports[next(iter(imports))] = {'claimed': 'original'}
    with pytest.raises(StagedProjectionError): project(value, import_sources=imports)


def test_missing_type_check_is_not_vacuous_acceptance(monkeypatch):
    import kir.staged_create_projection as owner
    value = case()
    actual = owner.compare_type_definition
    def incomplete(*args, **kwargs):
        result = actual(*args, **kwargs)
        del result['checks']['layers[0].material']
        return result
    monkeypatch.setattr(owner, 'compare_type_definition', incomplete)
    with pytest.raises(StagedProjectionError, match='staged_import_definition_mismatch'): project(value)


@pytest.mark.parametrize('fault', ['guard_omission', 'runtime_selector', 'core_rehash', 'runtime_plan'])
def test_public_projection_changes_cannot_prepare_new_source(fault):
    value = case()
    projection = project(value)
    forged = copy(projection)
    if fault == 'guard_omission': object.__setattr__(forged, 'expected_identities', projection.expected_identities[1:])
    elif fault == 'runtime_selector':
        program = projection.runtime_program
        program['ops'][0]['type']['value'] = 99999
        object.__setattr__(forged, '_runtime_program', _object(program, 'forged'))
    elif fault == 'core_rehash':
        core = projection.core
        core['expected_identities'].clear()
        object.__setattr__(forged, '_core', _object(core, 'forged'))
        object.__setattr__(forged, 'association_digest', _hash(core))
    else: object.__setattr__(forged, 'runtime_plan', value['partition'].materialization.planned)
    with pytest.raises(StagedProjectionError, match='staged_projection_mismatch'):
        prepare_staged_create(forged, operation_id=str(uuid4()))


def test_projection_constructor_is_closed_and_returned_values_are_detached():
    with pytest.raises(TypeError): StagedCreateProjection()
    projection = project(case())
    before = projection.to_dict()
    projection.core['expected_identities'].clear()
    projection.runtime_program['ops'].clear()
    assert projection.to_dict() == before
    with pytest.raises(FrozenInstanceError): projection.association_digest = 'f' * 64


def test_extra_valid_observation_rows_are_retained_not_hidden():
    def mutate(rows):
        extra = deepcopy(rows['uid-1'])
        extra['requested_unique_id'] = 'extra-uid'
        extra['element_identity'] = ElementIdentityProof(3333, 'extra-uid', 'c' * 32).to_dict()
        extra['name'] = extra['type_definition']['value']['name'] = 'ExtraUnimportedType'
        rows['extra-uid'] = extra
    value = case(mutate_observed=mutate)
    projection = project(value)
    assert 'extra-uid' in projection.core['observation']['rows']
    assert 'extra-uid' not in projection.core['required_import_unique_ids']
    assert 'extra-uid' not in {proof.unique_id for proof in projection.expected_identities}


@pytest.mark.parametrize('fault', ['operation', 'pin', 'parameters'])
def test_changed_import_source_or_module_pin_cannot_reuse_old_mapping(fault):
    from kir.project import ModuleDefinition, RecipePin, ProjectRevision
    value = case()
    original = value['project']
    instances, modules = list(original.instances), list(original.modules)
    if fault == 'operation':
        outputs = list(instances[0].outputs)
        operation = _thaw(outputs[0].operation)
        operation['elev_mm'] = 100
        outputs[0] = replace(outputs[0], operation=operation)
        instances[0] = replace(instances[0], outputs=tuple(outputs))
    elif fault == 'parameters':
        instances[0] = replace(instances[0], parameters={'new_declared_height': 100})
    else:
        modules = [ModuleDefinition('m', 'sealed_evaluation', RecipePin('not_executed()', 'c' * 64))]
        instances = [replace(instance, module_digest=None) for instance in instances]
    current = ProjectRevision(original.project_id, modules, instances)
    materialized = materialize_selection(current, select_project_instances(current, instance_keys=['B']), {})
    partition = partition_project_execution(current, materialized, import_output_ids=list(value['imports']))
    with pytest.raises(StagedProjectionError, match='staged_import_source_mismatch'):
        bind_staged_create_projection(partition, import_sources=value['imports'], observation=value['observation'])


def test_missing_original_UID_row_is_not_replaced_by_another_observation():
    """'The address was NOT REQUESTED' has its own name, not a generic
    'something is missing'.

    Until 07.09 the refusal was named `staged_import_observation_missing`
    and was also spoken for two other cases: the model answered "no such
    thing", and an element was replaced on a type change. Three causes
    require three different actions — request it again, deal with a
    deletion, or produce a replacement schedule — and one name allowed none
    of them to be chosen. The distinction lives in
    `test_identity_replacement_after_change_type`.
    """
    value = case()
    rows = deepcopy(value['observed_rows'])
    del rows['uid-1']
    observed = observe_rows(rows, value['credentials'])
    with pytest.raises(StagedProjectionError, match='staged_import_observation_absent'):
        project(value, observation=observed)


@pytest.mark.parametrize('fault', ['refused', 'conflicting', 'missing'])
def test_original_import_qualification_uses_shared_CREATE_assessment(fault):
    value = case()
    response = deepcopy(value['response'])
    payload = json.loads(response['receipt']['result_json'])
    lid, tid = list(value['imports'])
    if fault == 'refused': payload[tid] = {'refused': 'type_failed'}
    elif fault == 'missing': del payload[tid]
    else: payload[tid] = deepcopy(payload[lid]); payload[tid]['duplicated'] = True
    response['receipt']['result_json'] = json.dumps(payload)
    bound = bind_create_receipt(value['archive'], json.dumps(response), credentials=value['credentials'],
        request_id=response['request_id'])
    imports = {oid: (value['project'], value['archive'], bound) for oid in value['imports']}
    with pytest.raises(StagedProjectionError, match='staged_import_identity_unqualified'):
        project(value, import_sources=imports)


def test_reused_type_does_not_justify_equal_C0_when_original_receipt_changed_other_elements():
    value = case(original_reused=True, revision=8)
    # Make only the type an import; the current level is a new stage export.
    imports = {oid: source for oid, source in value['imports'].items()
               if oid == output_id(value['project'].project_id, 'shared', 'type')}
    partition = partition_project_execution(value['project'], value['partition'].materialization,
        import_output_ids=list(imports))
    with pytest.raises(StagedProjectionError, match='staged_import_observation_too_old'):
        bind_staged_create_projection(partition, import_sources=imports, observation=value['observation'])


@pytest.mark.parametrize('transaction_names', [[], ['KIR'], ['']])
@pytest.mark.parametrize('revision', [8, 9])
def test_readonly_reused_type_equal_C0_needs_complete_empty_change_manifest(transaction_names, revision):
    value = case(original_reused=True, revision=revision)
    pid = value['project'].project_id
    type_id = output_id(pid, 'shared', 'type')
    # Retain the same full source but select an original type-only publication
    # using a separate source instance would change its address. Instead use an
    # inert historical full-source fixture with only the type row qualified and
    # the remaining original operation rows explicitly refused, zero changes.
    response = deepcopy(value['response'])
    payload = json.loads(response['receipt']['result_json'])
    for key in tuple(payload):
        if key not in ('ok', type_id): payload[key] = {'refused': 'not_run_in_this_publication'}
    response['receipt']['result_json'] = json.dumps(payload)
    response['receipt']['changes']['added'] = []
    response['receipt']['changes']['transaction_names'] = transaction_names
    response['receipt']['transaction_evidence'] = 'changes_not_observed'
    bound = bind_create_receipt(value['archive'], json.dumps(response), credentials=value['credentials'],
        request_id=response['request_id'])
    imports = {type_id: (value['project'], value['archive'], bound)}
    partition = partition_project_execution(value['project'], value['partition'].materialization,
        import_output_ids=list(imports))
    if transaction_names and revision == 8:
        with pytest.raises(StagedProjectionError, match='staged_import_observation_too_old'):
            bind_staged_create_projection(partition, import_sources=imports, observation=value['observation'])
        return
    projection = bind_staged_create_projection(partition, import_sources=imports, observation=value['observation'])
    assert projection.precondition.revision == revision
    assert projection.runtime_plan.source_op_count == 2
    assert projection.core['import_lineage'][0]['original_identity_state'] == 'reused_existing'


def test_preparation_never_uses_transport_or_refreshes_observation(monkeypatch):
    value = case()
    import kir.revit_transport
    monkeypatch.setattr(kir.revit_transport, 'exchange', lambda *a, **k: pytest.fail('unexpected transport'))
    projection = project(value)
    prepared = prepare_staged_create(projection, operation_id=str(uuid4()))
    assert prepared.precondition is value['observation'].precondition


def test_declared_layer_material_identity_is_part_of_the_guard_set():
    projection = project(case(material=True))
    assert {p.unique_id for p in projection.expected_identities} == {'uid-0', 'uid-1', 'type-uid', 'material-uid'}
    prepared = prepare_staged_create(projection, operation_id=str(uuid4()))
    assert any(p.element_id == 5000 and p.version_guid == 'c' * 32 for p in prepared.expected_identities)
    assert 'material-uid' in prepared.source


def test_missing_level_type_dependency_proof_cannot_be_omitted_from_guards():
    def mutate(rows): rows['uid-0']['type_state'] = {'status': 'unavailable', **unavailable()}
    with pytest.raises(StagedProjectionError, match='staged_import_level_unavailable'):
        project(case(mutate_observed=mutate))


def test_declared_level_name_is_compared_exactly_without_forcing_undeclared_autoname():
    assert project(case(level_name='Level zero')).runtime_plan.source_op_count == 1
    def mutate(rows): rows['uid-0']['name'] = 'level ZERO'
    with pytest.raises(StagedProjectionError, match='staged_import_level_mismatch'):
        project(case(level_name='Level zero', mutate_observed=mutate))


@pytest.mark.parametrize('isolation', [None, True, 'per_chunk', ''])
def test_invalid_isolation_is_not_a_silent_default(isolation):
    with pytest.raises(StagedProjectionError, match='staged_isolation_invalid'):
        project(case(), isolation=isolation)


def test_full_observation_claims_can_be_checked_without_constructing_fresh_carrier():
    from kir.type_definition_observation import validate_type_definition_claims
    projection = project(case())
    assert validate_type_definition_claims(projection.core['observation']) is None


def test_shared_basis_level_with_different_reported_elevation_cannot_match_project_zero():
    def mutate(rows):
        rows['uid-0']['level'].update(elevation_base=1, project_elevation_mm=0, reported_elevation_mm=1000)
    with pytest.raises(StagedProjectionError, match='staged_import_level_mismatch'):
        project(case(mutate_observed=mutate))


@pytest.mark.parametrize('elevation_base', [0, 1])
@pytest.mark.parametrize('readonly', [False, True])
def test_matching_level_is_usable_without_requiring_writable_parameter(elevation_base, readonly):
    def mutate(rows):
        rows['uid-0']['level'].update(elevation_base=elevation_base, project_elevation_mm=0, reported_elevation_mm=0)
        rows['uid-0']['level']['elevation_parameter']['is_read_only'] = readonly
    assert project(case(mutate_observed=mutate)).runtime_plan.source_op_count == 1
