"""Inert staged CREATE scope over the original full authored project.

This is not a PlannedProgram, numeric selector mapper, native identity binding,
publication archive, or execution permission. Symbolic exports can reference
imports absent from that export list, so the list is NOT a compilable program.
Existing materialization remains untouched. Its owner revalidates the full
closed source plan; no partial plan, native geometry or binding is fabricated.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Mapping

from kir import relate, spec
from kir.diag import KirRefusal
from kir.geometry_materialization import GeometryMaterialization
from kir.project import ProjectError, ProjectRevision, _canonical, _hash, _object, _thaw
from kir.project_diff import _dependencies, _outputs
from kir.project_selection import ProjectSelection, validate_project_selection
from kir.registry_base import EffectKind, IdentityCardinality, ReferenceKind


PARTITION_SCHEMA = 'kir-project-execution-partition/1'
PARTITION_PROFILE = 'direct_level_host_type_wall_floor/1'
_PRODUCERS = frozenset({'create_level', 'create_wall_type'})
_CONSUMERS = frozenset({'create_wall', 'create_floor', 'create_floor_by_contour'})
_IMPORT_KINDS = frozenset({ReferenceKind.LEVEL, ReferenceKind.WALL_TYPE, ReferenceKind.FLOOR_TYPE})


class ProjectPartitionError(ProjectError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'{code}: {message}')


def _require(condition, code, message):
    if not condition:
        raise ProjectPartitionError(code, message)


def _result(operation):
    name = operation['op']
    definition = spec.OPS.get(name)
    _require(name in _PRODUCERS | _CONSUMERS and definition is not None,
             'partition_operation_unsupported', 'profile supports only direct Level, host types, walls and floors')
    if definition.result_by_param is not None:
        discriminator, _ = definition.result_by_param
        parameter = next(p for p in definition.params if p.name == discriminator)
        value = operation.get(discriminator, parameter.default)
        _require(type(value) is str and value in parameter.choices,
                 'partition_result_unresolved', 'registry result discriminator is invalid')
    result = definition.result_for(operation)
    _require(definition.effect is EffectKind.CREATE
             and result.identity_cardinality is IdentityCardinality.ONE and result.referenceable,
             'partition_result_unsupported', 'a direct referenceable single-identity CREATE producer is required')
    if name in _PRODUCERS:
        _require(result.reference_kind in _IMPORT_KINDS, 'partition_operation_unsupported',
                 'only Level and wall/floor host types are in the initial profile')
    for param in definition.params:
        _require(param.kind != 'member_ops', 'partition_nested_scope_unsupported', 'nested operation scopes are unsupported')
        if param.kind in ('sel', 'target_w') and isinstance(operation.get(param.name), dict):
            selector = operation[param.name]
            _require(set(selector) <= {'by', 'value', 'kind'}, 'partition_selector_unsupported',
                     'ambiguous selector payload cannot define an import edge')
    for name in relate.addressable_params(operation['op']):
        _require(not relate.is_address(operation.get(name)), 'partition_address_unsupported',
                 'element/grid-relative addressing requires a separate qualified lowering profile')
    return result


@dataclass(frozen=True, slots=True, init=False)
class ProjectExecutionPartition:
    """Immutable authored partition; its checksum is not native authority."""

    project: ProjectRevision
    materialization: GeometryMaterialization
    selection: ProjectSelection | None
    import_output_ids: tuple[str, ...]
    digest: str
    _payload: Mapping = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('use partition_project_execution with the full authored project')

    def to_dict(self) -> dict:
        return {**_thaw(self._payload), 'partition_digest': self.digest}

    def validate(self) -> None:
        """Recheck current authored association/profile, without native queries.

        Not a historical persistence loader or a compiler admission boundary.
        The retained materialization plan checksum remains a declaration; this
        owner revalidates the full closed source plan, not the partial exports.
        This does not prove kernel execution or native identity.
        """
        _require(type(self.import_output_ids) is tuple, 'partition_claims_mismatch', 'immutable import IDs required')
        expected = partition_project_execution(self.project, self.materialization,
            import_output_ids=self.import_output_ids)
        _require(self.selection is self.materialization.selection and self.digest == expected.digest
                 and self.import_output_ids == expected.import_output_ids
                 and _canonical(self._payload) == _canonical(expected._payload),
                 'partition_claims_mismatch', 'retained claims differ from current full source partition')


def partition_project_execution(project: ProjectRevision, materialized: GeometryMaterialization, *,
                                import_output_ids: Sequence[str]) -> ProjectExecutionPartition:
    """Partition existing scoped source into declared imports and new exports.

    Coverage, references and result kinds come from existing authored/registry
    owners. Full closed materialization is revalidated by its existing owner;
    nothing is grounded, observed, executed, persisted or partially compiled.
    Only ordinary direct outputs are supported initially. Unselected body-owned
    outputs stay in the full source but are neither materialized nor interpreted.
    Native name/ID selectors remain unchanged and explicitly unbound.
    """
    _require(type(project) is ProjectRevision and type(materialized) is GeometryMaterialization,
             'partition_input_invalid', 'exact full project and materialization required')
    _require(type(materialized.project) is ProjectRevision and materialized.project.dumps() == project.dumps(),
             'partition_source_mismatch', 'materialization must retain the actual full authored revision')
    selection = materialized.selection
    try:
        if selection is not None:
            validate_project_selection(project, selection)
    except ProjectError as error:
        raise ProjectPartitionError('partition_selection_mismatch', 'selected dependency closure differs') from error
    operations, addresses = _outputs(project)
    indices = tuple(range(len(operations))) if selection is None else selection.project_source_indices
    all_ids = tuple(operations)
    scoped_ids = tuple(all_ids[index] for index in indices)
    scoped = set(scoped_ids)
    _require(isinstance(import_output_ids, Sequence) and not isinstance(import_output_ids, (str, bytes))
             and all(type(oid) is str for oid in import_output_ids),
             'partition_imports_invalid', 'explicit distinct output IDs required')
    imported = set(import_output_ids)
    _require(len(imported) == len(import_output_ids), 'partition_imports_invalid', 'duplicate import IDs')
    _require(imported <= scoped, 'partition_import_unknown', 'import lies outside the selected authored closure')
    exports = scoped - imported
    _require(bool(exports), 'partition_exports_empty', 'a stage must contain at least one new export')
    full_addresses = project.addressed_outputs()
    _require(not any(full_addresses[index][1].geometry is not None for index in indices),
             'partition_body_output_unsupported', 'body-owned outputs need a later explicit partition profile')
    kinds = {oid: _result(operations[oid]).reference_kind for oid in scoped_ids}
    # The existing owner is the only materialized-source/plan validator. Use a
    # fresh carrier to avoid even reassignment of fields on the caller's object.
    try:
        GeometryMaterialization(materialized.project, materialized.program, materialized.planned,
                                materialized.sources, selection)
    except (ValueError, TypeError, KirRefusal) as error:
        raise ProjectPartitionError('partition_materialization_mismatch', 'full closed materialization validation failed') from error
    for oid in imported:
        _require(operations[oid]['op'] in _PRODUCERS and kinds[oid] in _IMPORT_KINDS,
                 'partition_import_unsupported', 'only direct Level and wall/floor types may be imported')
    edges, issues = _dependencies(project, operations)
    relevant = [issue for issue in issues if issue['op_id'] is None or issue['op_id'] in scoped]
    _require(all(issue['kind'] == 'selector_requires_grounding' for issue in relevant),
             'partition_dependencies_unresolved', 'authored dependency analysis reported an unresolved or unsupported edge')
    selected_edges = [edge for edge in edges if edge['dependent'] in scoped]
    _require(all(edge['source'] in scoped for edge in selected_edges),
             'partition_dependency_missing', 'a selected dependency was dropped from the scope')
    # Imports denote existing objects, not re-executed creation procedures. Do
    # not pretend that a template dependency of an imported type is a new-stage
    # runtime prerequisite; that more general profile is deliberately deferred.
    _require(not any(edge['dependent'] in imported for edge in selected_edges),
             'partition_import_dependency_unsupported', 'imports with authored ref dependencies are unsupported')
    used_imports = {edge['source'] for edge in selected_edges if edge['dependent'] in exports and edge['source'] in imported}
    _require(used_imports == imported, 'partition_unused_import', 'each import must be needed by a new export')
    descriptors = []
    for source_index, (project_source_index, oid) in enumerate(zip(indices, scoped_ids, strict=True)):
        descriptors.append({'output_id': oid, **addresses[oid], 'source_index': source_index,
            'project_source_index': project_source_index, 'operation': operations[oid]['op'],
            'source_operation_digest': _hash(operations[oid]), 'reference_kind': kinds[oid].value})
    payload = {'schema': PARTITION_SCHEMA, 'profile': PARTITION_PROFILE,
        'project': {'project_id': project.project_id, 'revision_id': project.revision_id, 'schema': project.schema},
        'selection': selection.to_dict() if selection is not None else None,
        'materialization_digest': materialized.to_dict()['materialization_digest'],
        'source_output_count': len(operations), 'closure_output_count': len(scoped_ids), 'export_output_count': len(exports),
        'scoped_outputs': descriptors,
        'imports': [row for row in descriptors if row['output_id'] in imported],
        'exports': [row for row in descriptors if row['output_id'] in exports],
        'dependency_edges': selected_edges,
        'unbound_selectors': [issue for issue in relevant if issue['kind'] == 'selector_requires_grounding'],
        'symbolic_export_ops': [operations[oid] for oid in scoped_ids if oid in exports],
        'claims': {'scope': 'authored_partition_only', 'native_identity': 'not_observed',
            'native_birth': 'not_established', 'observed_match': 'not_evaluated', 'execution_permission': 'not_granted',
            'closed_compilable_program': 'not_claimed', 'materialization_plan': 'full_source_revalidated',
            'numeric_selector_binding': 'not_performed', 'native_execution': 'not_run'}}
    result = object.__new__(ProjectExecutionPartition)
    for name, value in {'project': project, 'materialization': materialized, 'selection': selection,
        'import_output_ids': tuple(oid for oid in scoped_ids if oid in imported),
        'digest': _hash(payload), '_payload': _object(payload, 'project_execution_partition')}.items():
        object.__setattr__(result, name, value)
    return result


__all__ = ['PARTITION_SCHEMA', 'PARTITION_PROFILE', 'ProjectPartitionError', 'ProjectExecutionPartition',
           'partition_project_execution']
