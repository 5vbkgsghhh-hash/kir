"""Inert shared authored dependencies, not native reuse or dispatch evidence."""
from copy import copy
from dataclasses import FrozenInstanceError

import pytest

from kir.geometry_materialization import materialize_project, materialize_selection
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, _hash, output_id
from kir.project_selection import select_project_instances
from kir.project import NamedOutput, _thaw, _object


def shared_project(*, floor=False):
    pid = 'partition-shared-source'
    lid, tid = (output_id(pid, 'shared', name) for name in ('level', 'type'))
    def consumer(y):
        base = {'op': 'create_floor' if floor else 'create_wall',
            'level': {'by': 'ref', 'value': lid}, 'type': {'by': 'ref', 'value': tid}}
        if floor:
            base['outline'] = [[0, y], [5000, y], [5000, y + 3000], [0, y + 3000]]
        else:
            base.update(p0_mm=[0, y], p1_mm=[5000, y], height_mm=3000)
        return base
    return ProjectRevision(pid, [ModuleDefinition('m')], [
        ModuleInstance('shared', 'm', {
            'level': {'op': 'create_level', 'elev_mm': 0},
            'type': {'op': 'create_wall_type', 'host_kind': 'floor' if floor else 'wall',
                'source_type': {'by': 'element_id', 'value': 400 if floor else 100},
                'new_name': 'AuthoredSharedType', 'layers': [{'width_mm': 200, 'function': 'Structure'}]}}),
        ModuleInstance('A', 'm', {'body': consumer(0)}),
        ModuleInstance('B', 'm', {'body': consumer(5000)}),
    ])


def selected(project=None):
    project = project or shared_project()
    choice = select_project_instances(project, instance_keys=['B'])
    materialized = materialize_selection(project, choice, {})
    imports = [output_id(project.project_id, 'shared', key) for key in ('level', 'type')]
    return project, materialized, imports


def partition(project=None):
    from kir.project_execution_partition import partition_project_execution
    project, materialized, imports = selected(project)
    return partition_project_execution(project, materialized, import_output_ids=imports)


@pytest.mark.parametrize('floor', [False, True])
def test_shared_A_to_B_preserves_fullsource_closure_and_symbolic_exports(floor):
    value = partition(shared_project(floor=floor))
    data = value.to_dict()
    assert len(value.project.addressed_outputs()) == 4
    assert value.materialization.planned.source_op_count == 3
    assert data['source_output_count'] == 4
    assert data['closure_output_count'] == 3 and data['export_output_count'] == 1
    assert [d['project_source_index'] for d in data['scoped_outputs']] == [0, 1, 3]
    assert [d['source_index'] for d in data['scoped_outputs']] == [0, 1, 2]
    assert [d['reference_kind'] for d in data['imports']] == ['level', 'floor_type' if floor else 'wall_type']
    original = value.materialization.to_program()['ops'][-1]
    assert data['symbolic_export_ops'] == [original]
    assert original['type']['by'] == original['level']['by'] == 'ref'
    assert not hasattr(value, 'execute') and not hasattr(value, 'to_prepared')
    assert not hasattr(value, 'planned') and not hasattr(value, 'to_program')
    assert data['claims']['execution_permission'] == 'not_granted'
    assert data['claims']['native_identity'] == 'not_observed'
    assert data['claims']['closed_compilable_program'] == 'not_claimed'
    assert data['partition_digest'] == _hash({k: v for k, v in data.items() if k != 'partition_digest'})
    value.validate()


def test_first_stage_without_imports_keeps_all_new_outputs():
    from kir.project_execution_partition import partition_project_execution
    project = shared_project()
    materialized = materialize_selection(project, select_project_instances(project, instance_keys=['A']), {})
    value = partition_project_execution(project, materialized, import_output_ids=[])
    assert value.to_dict()['imports'] == []
    assert value.to_dict()['export_output_count'] == 3


def test_full_materialization_is_not_silently_selected():
    from kir.project_execution_partition import partition_project_execution
    project = shared_project()
    materialized = materialize_project(project, {})
    value = partition_project_execution(project, materialized,
        import_output_ids=[output_id(project.project_id, 'shared', key) for key in ('type', 'level')])
    assert value.selection is None
    assert value.to_dict()['closure_output_count'] == 4
    assert value.to_dict()['export_output_count'] == 2


def test_detached_serialization_and_constructor_do_not_grant_partition_authority():
    from kir.project_execution_partition import ProjectExecutionPartition, ProjectPartitionError
    value = partition()
    before = value.to_dict()
    detached = value.to_dict()
    detached['symbolic_export_ops'][0]['level']['value'] = 'foreign'
    detached['imports'].clear()
    assert value.to_dict() == before
    with pytest.raises(TypeError): ProjectExecutionPartition()
    with pytest.raises(FrozenInstanceError): value.digest = 'f' * 64
    forged = copy(value)
    object.__setattr__(forged, 'digest', 'f' * 64)
    with pytest.raises(ProjectPartitionError): forged.validate()


@pytest.mark.parametrize('fault', ['unknown', 'duplicate', 'all_imports', 'wall_import', 'wrong_source'])
def test_refuses_invalid_or_unsupported_import_scope(fault):
    from kir.project_execution_partition import partition_project_execution, ProjectPartitionError
    project, materialized, imports = selected()
    if fault == 'unknown': imports.append('unknown-output')
    elif fault == 'duplicate': imports.append(imports[0])
    elif fault == 'all_imports': imports.append(output_id(project.project_id, 'B', 'body'))
    elif fault == 'wall_import': imports = [output_id(project.project_id, 'B', 'body')]
    else: project = project.revise(expected_revision=project.revision_id, metadata={'changed': True})
    with pytest.raises(ProjectPartitionError):
        partition_project_execution(project, materialized, import_output_ids=imports)


def test_unneeded_import_is_not_an_execution_dependency():
    from kir.project_execution_partition import partition_project_execution, ProjectPartitionError
    project = shared_project()
    extra = ModuleInstance('unused', 'm', {'level': {'op': 'create_level', 'elev_mm': 8000}})
    project = project.revise(expected_revision=project.revision_id, instances=(*project.instances, extra))
    materialized = materialize_project(project, {})
    with pytest.raises(ProjectPartitionError, match='partition_unused_import'):
        partition_project_execution(project, materialized,
            import_output_ids=[output_id(project.project_id, 'unused', 'level')])


def test_native_seed_operands_remain_unbound_and_full_source_never_changes():
    project, materialized, _ = selected()
    original_project, original_program = project.dumps(), materialized.to_program()
    value = partition(project)
    assert value.materialization.to_program() == original_program
    assert project.dumps() == original_project
    source_type = original_program['ops'][1]['source_type']
    assert source_type == {'by': 'element_id', 'value': 100}
    data = value.to_dict()
    assert data['unbound_selectors'] == [{'op_id': original_program['ops'][1]['id'],
        'field': 'source_type', 'kind': 'selector_requires_grounding', 'value': 'element_id'}]
    assert data['claims']['numeric_selector_binding'] == 'not_performed'
    assert data['claims']['materialization_plan'] == 'full_source_revalidated'


@pytest.mark.parametrize('mutate', ['program', 'plan', 'extra_source', 'selection_index', 'selection_drop'])
def test_public_materialization_or_selection_tampering_cannot_supply_partition(mutate):
    from kir.project_execution_partition import partition_project_execution, ProjectPartitionError
    project, materialized, imports = selected()
    forged = copy(materialized)
    if mutate == 'program':
        program = materialized.to_program()
        program['ops'][-1]['height_mm'] += 1
        object.__setattr__(forged, 'program', _object(program, 'forged'))
    elif mutate == 'plan':
        other = materialize_selection(shared_project(floor=True),
            select_project_instances(shared_project(floor=True), instance_keys=['B']), {})
        object.__setattr__(forged, 'planned', other.planned)
    elif mutate == 'extra_source':
        object.__setattr__(forged, 'sources', ({'op_id': imports[0]},))
    else:
        choice = copy(materialized.selection)
        if mutate == 'selection_index': object.__setattr__(choice, 'project_source_indices', (False, 1, 3))
        else: object.__setattr__(choice, 'output_ids', choice.output_ids[:-1])
        object.__setattr__(forged, 'selection', choice)
    with pytest.raises(ProjectPartitionError):
        partition_project_execution(project, forged, import_output_ids=imports)


def counterfeit_changed_output(operation):
    """Deliberately stale public carrier; never fabricate a partial Plan."""
    project, materialized, imports = selected()
    old = project.instances[-1]
    new = ModuleInstance(old.key, old.module_key, {'body': operation})
    project = project.revise(expected_revision=project.revision_id, instances=(*project.instances[:-1], new))
    forged = copy(materialized)
    object.__setattr__(forged, 'project', project)
    object.__setattr__(forged, 'selection', None)
    return project, forged, imports


@pytest.mark.parametrize('operation,code', [
    ({'op': 'create_group', 'members': []}, 'partition_operation_unsupported'),
    ({'op': 'macro_not_registered'}, 'partition_operation_unsupported'),
    ({'op': 'create_type', 'source_type': {'by': 'element_id', 'value': 1},
      'new_name': 'NoFamilyImport', 'width_mm': 200}, 'partition_operation_unsupported'),
    ({'op': 'create_wall_type', 'host_kind': 'roof'}, 'partition_operation_unsupported'),
    ({'op': 'create_wall_type', 'host_kind': []}, 'partition_result_unresolved'),
    ({'op': 'create_wall', 'p0_mm': {'at_element': {'by': 'ref', 'value': 'other'}},
      'p1_mm': [1, 0], 'height_mm': 3000, 'level': {'by': 'ref', 'value': 'other'}},
      'partition_address_unsupported'),
    ({'op': 'create_wall', 'p0_mm': [0, 0], 'p1_mm': [1, 0], 'height_mm': 3000,
      'level': {'by': 'ref', 'value': 'other', 'nested': {'by': 'ref', 'value': 'hidden'}}},
      'partition_selector_unsupported'),
])
def test_unsupported_and_ambiguous_profiles_refuse_before_revalidation(operation, code):
    from kir.project_execution_partition import partition_project_execution, ProjectPartitionError
    project, materialized, imports = counterfeit_changed_output(operation)
    with pytest.raises(ProjectPartitionError, match=code):
        partition_project_execution(project, materialized, import_output_ids=imports)


@pytest.mark.parametrize('kind', ['future', 'missing', 'wrong_kind'])
def test_invalid_reference_never_becomes_a_closed_stage(kind):
    from kir.project_execution_partition import partition_project_execution, ProjectPartitionError
    project, materialized, imports = selected()
    operation = _thaw(project.instances[-1].outputs[0].operation)
    operation['level']['value'] = {'future': output_id(project.project_id, 'B', 'body'),
        'missing': 'absent', 'wrong_kind': imports[1]}[kind]
    project, forged, imports = counterfeit_changed_output(operation)
    object.__setattr__(forged, 'program', _object(project.to_program(), 'forged'))
    with pytest.raises(ProjectPartitionError):
        partition_project_execution(project, forged, import_output_ids=imports)


@pytest.mark.parametrize('whole', [False, True])
def test_declared_result_contract_is_rechecked_from_current_registry(monkeypatch, whole):
    from dataclasses import replace
    from kir import spec
    from kir.registry_base import RESULT_QUERY
    from kir.project_execution_partition import partition_project_execution, ProjectPartitionError
    project, materialized, imports = selected()
    if whole: materialized = materialize_project(project, {})
    monkeypatch.setitem(spec.OPS, 'create_level', replace(spec.OPS['create_level'], result=RESULT_QUERY))
    with pytest.raises(ProjectPartitionError, match='partition_result_unsupported' if whole else 'partition_selection_mismatch'):
        partition_project_execution(project, materialized, import_output_ids=imports)


def test_validate_rejects_forged_order_or_payload_even_with_rehashed_claims():
    from kir.project_execution_partition import ProjectPartitionError
    value = partition()
    forged = copy(value)
    object.__setattr__(forged, 'import_output_ids', tuple(reversed(value.import_output_ids)))
    with pytest.raises(ProjectPartitionError): forged.validate()
    forged = copy(value)
    data = _thaw(forged._payload)
    data['imports'][0]['source_operation_digest'] = 'f' * 64
    object.__setattr__(forged, '_payload', _object(data, 'forged'))
    object.__setattr__(forged, 'digest', _hash(data))
    with pytest.raises(ProjectPartitionError): forged.validate()


def test_factory_uses_existing_full_materialization_owner_not_partial_plan(monkeypatch):
    import kir.compiler as compiler
    from kir.project_execution_partition import partition_project_execution
    project, materialized, imports = selected()
    original = compiler.plan_program
    calls = []
    def plan(program, **kwargs):
        calls.append(program)
        assert program == materialized.to_program()
        assert len(program['ops']) == 3
        return original(program, **kwargs)
    monkeypatch.setattr(compiler, 'plan_program', plan)
    value = partition_project_execution(project, materialized, import_output_ids=imports)
    value.validate()
    assert len(calls) == 2
    assert value.materialization is materialized and value.project is project


def test_contour_floor_keeps_declared_hole_and_original_symbolic_refs():
    from kir.contour import region
    from kir.project_execution_partition import partition_project_execution
    project = shared_project(floor=True)
    operation = _thaw(project.instances[-1].outputs[0].operation)
    outline = operation.pop('outline')
    operation.update(op='create_floor_by_contour', contour=region(outline,
        holes=[[[1000, 5500], [2000, 5500], [2000, 6500], [1000, 6500]]]))
    replacement = ModuleInstance('B', 'm', {'body': operation})
    project = project.revise(expected_revision=project.revision_id, instances=(*project.instances[:-1], replacement))
    project, materialized, imports = selected(project)
    value = partition_project_execution(project, materialized, import_output_ids=imports)
    actual = value.to_dict()['symbolic_export_ops'][0]
    assert actual['contour'] == operation['contour']
    assert actual['level'] == operation['level'] and actual['type'] == operation['type']


def test_unselected_body_remains_in_full_source_without_geometry_resolution(monkeypatch):
    from kir.project import BodyRepresentation
    from kir.project_execution_partition import partition_project_execution, ProjectPartitionError
    from kir.occt_geometry import GeometryBundle
    project = shared_project()
    project = project.upgrade_schema('kir-authoring-project/2', expected_revision=project.revision_id)
    body = ModuleInstance('body', 'm', [NamedOutput('shape', {'op': 'create_directshape', 'name': 'inert'},
        BodyRepresentation('a' * 64, 'b' * 64))])
    project = project.revise(expected_revision=project.revision_id, instances=(*project.instances, body))
    monkeypatch.setattr(GeometryBundle, 'read_body', lambda *_: pytest.fail('unexpected kernel read'))
    project, materialized, imports = selected(project)
    value = partition_project_execution(project, materialized, import_output_ids=imports)
    assert value.to_dict()['source_output_count'] == 5
    assert value.to_dict()['closure_output_count'] == 3
    assert len(value.project.geometry_references()) == 1
    forged = copy(materialized)
    object.__setattr__(forged, 'selection', None)
    with pytest.raises(ProjectPartitionError, match='partition_body_output_unsupported'):
        partition_project_execution(project, forged, import_output_ids=imports)
