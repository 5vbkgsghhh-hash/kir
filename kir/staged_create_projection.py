"""Fresh guarded CREATE preparation from historical imports and one read C0.

No transport, archive creation, storage, context refresh or dispatch occurs.
The association core commits to authored lineage, runtime projection and guards;
it excludes the later C# source hash to avoid a circular commitment. Imported
types are matched only on declared clauses, never full BIM/type preservation.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from kir import spec
from kir.compiler import plan_program
from kir.contracts import ElementIdentityProof
from kir.create_publication import (BoundCreateReceipt, IdentityReplacementLedger,
                                    assess_create_identities)
from kir.project import ProjectRevision, _canonical, _hash, _object, _thaw
from kir.project_execution_partition import ProjectExecutionPartition
from kir.revit_connector import ContextPrecondition, RuntimeTarget, prepare_execution
from kir.revit_observation import _identity
from kir.saved_execution import PROJECT_ARCHIVE_SCHEMA, SavedExecutionRecord
from kir.type_definition_observation import TypeDefinitionObservation, compare_type_definition


STAGED_PROJECTION_SCHEMA = 'kir-staged-create-projection/1'
STAGED_ASSOCIATION_SCHEMA = 'kir-staged-create-association-core/1'


class StagedProjectionError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'{code}: {message}')


def _require(condition, code, message):
    if not condition:
        raise StagedProjectionError(code, message)


def _source_address(project, oid):
    found = next(((instance, output) for instance, output, identifier in project.addressed_outputs()
                  if identifier == oid), None)
    _require(found is not None, 'staged_import_source_mismatch', 'original output address is absent')
    instance, output = found
    module = next(module for module in project.modules if module.key == instance.module_key)
    return instance, output, module


def _type_comparison(observation, uid, operation):
    comparison = compare_type_definition(observation, unique_id=uid, factory_op=operation)
    # Expected operations are already normalized by the full source plan. An
    # empty/incomplete public comparison must not make all([]) an acceptance.
    required = {'host_kind', 'type_name', 'layer_count', 'total_width'}
    required.update(f'layers[{i}].{field}' for i in range(len(operation['layers']))
                    for field in ('width_mm', 'function', 'material'))
    checks = comparison.get('checks')
    _require(type(checks) is dict and set(checks) == required
             and all(type(check) is dict and check.get('status') == 'matched' for check in checks.values()),
             'staged_import_definition_mismatch', 'every declared type clause must be observed and matched')
    return comparison


def _level_comparison(row, operation):
    _require(row['is_level'] is True and row['level_status'] == 'observed'
             and row['type_state']['status'] == 'observed',
             'staged_import_level_unavailable', 'level elevation and its type dependency must be observed')
    tolerance = spec.OPS['create_level'].tolerances['elevation_mm']
    # ProjectElevation binds the authored frame; emitted Level witnesses and
    # constrained-wall checks also consume Level.Elevation. Shared-coordinate
    # bases must not make those two obligations appear interchangeable.
    checks = {'project_elevation': {'status': 'matched' if
        abs(row['level']['project_elevation_mm'] - operation['elev_mm']) <= tolerance else 'mismatch'},
        'reported_elevation': {'status': 'matched' if
        abs(row['level']['reported_elevation_mm'] - operation['elev_mm']) <= tolerance else 'mismatch'}}
    if 'name' in operation:
        checks['declared_name'] = {'status': 'matched' if row['name'] == operation['name'] else 'mismatch'}
    _require(all(check['status'] == 'matched' for check in checks.values()),
             'staged_import_level_mismatch', 'declared normalized Level elevation/name differs')
    return {'schema': 'kir-staged-level-comparison/1', 'checks': checks, 'tolerance_mm': tolerance,
        'expected_elevation_mm': operation['elev_mm'],
        'observed_project_elevation_mm': row['level']['project_elevation_mm'],
        'observed_reported_elevation_mm': row['level']['reported_elevation_mm'],
        'claims': {'scope': 'declared_level_elevation_and_optional_name', 'ownership': 'not_established'}}


@dataclass(frozen=True, slots=True, init=False)
class StagedCreateProjection:
    partition: ProjectExecutionPartition
    observation: TypeDefinitionObservation
    target: RuntimeTarget
    precondition: ContextPrecondition
    isolation: str
    runtime_plan: object
    expected_identities: tuple[ElementIdentityProof, ...]
    association_digest: str
    replacements: tuple = field(repr=False)
    _runtime_program: object = field(repr=False)
    _core: object = field(repr=False)
    _sources: tuple = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('use bind_staged_create_projection with typed original and observation evidence')

    @property
    def runtime_program(self):
        return _thaw(self._runtime_program)

    @property
    def core(self):
        return _thaw(self._core)

    def to_dict(self):
        return {'schema': STAGED_PROJECTION_SCHEMA, 'association_core': self.core,
            'association_digest': self.association_digest, 'runtime_program': self.runtime_program,
            'runtime_plan_evidence': self.runtime_plan.to_evidence_dict(),
            'claims': {'scope': 'fresh_guarded_preparation_only', 'dispatch_permission': 'none',
                'native_execution': 'not_run', 'native_birth': 'not_established',
                'import_preservation': 'declared_clauses_only', 'full_type_definition': 'not_evaluated',
                'geometry': 'not_evaluated', 'engineering': 'not_evaluated'}}

    def validate(self):
        _require(type(self._sources) is tuple and len({key for key, _ in self._sources}) == len(self._sources),
                 'staged_projection_mismatch', 'original import carriers must be unique')
        expected = bind_staged_create_projection(self.partition, import_sources=dict(self._sources),
            observation=self.observation, isolation=self.isolation,
            replacements=dict(self.replacements) or None)
        _require(self.target == expected.target and self.precondition == expected.precondition
                 and self.expected_identities == expected.expected_identities
                 and self.association_digest == expected.association_digest
                 and _canonical(self._core) == _canonical(expected._core)
                 and _canonical(self._runtime_program) == _canonical(expected._runtime_program)
                 and self.runtime_plan.to_evidence_dict() == expected.runtime_plan.to_evidence_dict(),
                 'staged_projection_mismatch', 'runtime projection, guard set or lineage differs')


def bind_staged_create_projection(partition, *, import_sources, observation, isolation='atomic',
                                  replacements=None) -> StagedCreateProjection:
    """A re-publish on top of what is ALREADY built; the replacement is read from the statement.

    🔴 THERE WAS ONE REFUSAL FOR THREE DIFFERENT CASES. `staged_import_observation_missing`
    was raised both when the uid was never requested, and when the model answered "no
    such thing", and when the element was replaced on a type change. Three causes require
    three different actions — re-query, deal with the deletion, submit the statement — and
    one name did not let you pick any of them. Now there are three:

        staged_import_observation_absent        the address was never requested
        staged_import_observation_unavailable   could not be read
        staged_import_element_not_found         the model says: no such thing
        staged_import_replacement_unconfirmed   a statement was submitted, but it does not
                                                account for this address

    The statement (`kir-create-identity-replacement/1`) is submitted ON OUTPUT and
    must belong to the same publication and the same observation: someone else's snapshot
    would explain a replacement that did not occur in this snapshot. No duplicate arises —
    a confirmed replacement points to an ALREADY EXISTING element, and a repeat
    publish still only links, it does not build a second one.
    """
    _require(type(partition) is ProjectExecutionPartition, 'staged_partition_required', 'exact authored partition required')
    partition.validate()
    _require(type(isolation) is str and isolation in ('atomic', 'per_op'),
             'staged_isolation_invalid', 'explicit atomic or per_op isolation required')
    _require(isinstance(import_sources, Mapping) and set(import_sources) == set(partition.import_output_ids),
             'staged_import_scope_mismatch', 'exact explicit import source mapping required')
    _require(type(observation) is TypeDefinitionObservation and type(observation.target) is RuntimeTarget
             and type(observation.precondition) is ContextPrecondition
             and type(observation.precondition.revision) is int,
             'staged_observation_required', 'one typed revision-bound definition observation required')
    ledgers = {} if replacements is None else dict(replacements)
    _require(isinstance(ledgers, dict) and set(ledgers) <= set(partition.import_output_ids)
             and all(type(value) is IdentityReplacementLedger for value in ledgers.values()),
             'staged_replacement_ledger_required',
             'replacement ledgers are addressed by import output id and must be confirmed carriers')
    observation.validate()
    c0, target, observed_rows = observation.precondition, observation.target, observation.rows
    _require(c0.revision >= 0, 'staged_observation_required', 'nonnegative exact C0 revision required')
    normalized = {op['id']: op for op in partition.materialization.planned.to_ops()}
    guards_by_id, guards_by_uid, current_imports, lineage, sources = {}, {}, {}, [], []

    def guard(proof):
        if proof is None:
            return
        _require(guards_by_id.get(proof.element_id, proof) == proof and guards_by_uid.get(proof.unique_id, proof) == proof,
                 'staged_import_identity_conflict', 'guard dependency identities conflict')
        guards_by_id[proof.element_id] = guards_by_uid[proof.unique_id] = proof

    for oid in partition.import_output_ids:
        original = import_sources[oid]
        _require(type(original) is tuple and len(original) == 3 and type(original[0]) is ProjectRevision
                 and type(original[1]) is SavedExecutionRecord and type(original[2]) is BoundCreateReceipt,
                 'staged_import_source_required', 'each import requires original project, Archive/2 and bound receipt')
        project, archive, bound = original
        _require(archive.to_dict()['schema'] == PROJECT_ARCHIVE_SCHEMA,
                 'staged_import_archive_required', 'original project Archive/2 required')
        assessment = assess_create_identities(project, archive, bound)
        identity_report = assessment.to_dict()
        old = next((row for row in identity_report['outputs'] if row['output_id'] == oid), None)
        _require(old is not None and old['state'] in ('created_here', 'reused_existing'),
                 'staged_import_identity_unqualified', 'historical import identity is missing, refused or conflicting')
        instance, output, module = _source_address(partition.project, oid)
        old_instance, old_output, old_module = _source_address(project, oid)
        _require(project.project_id == partition.project.project_id
                 and instance.key == old_instance.key and output.key == old_output.key
                 and instance.module_key == old_instance.module_key
                 and _canonical(output.to_dict()) == _canonical(old_output.to_dict())
                 and _canonical(module.to_dict()) == _canonical(old_module.to_dict())
                 and _canonical(instance.parameters) == _canonical(old_instance.parameters),
                 'staged_import_source_mismatch', 'original address, operation, module pin or parameters changed')
        binding = archive.binding_dict()
        _require(binding['target'] == target.to_dict() and binding['precondition']['document_key'] == c0.document_key,
                 'staged_import_context_mismatch', 'original import belongs to another runtime/document')
        original_revision = binding['precondition']['revision']
        changes = bound.receipt['changes']
        # Even without changed element IDs, recorded transaction names prove a
        # DocumentChanged event; the runtime tracker increments on that event.
        unchanged_reuse = (old['state'] == 'reused_existing' and changes['truncated'] is False
                           and all(not changes[field] for field in ('added', 'modified', 'deleted', 'transaction_names')))
        _require(type(original_revision) is int and (c0.revision > original_revision
                    or c0.revision == original_revision and unchanged_reuse),
                 'staged_import_observation_too_old', 'C0 must follow creation, or not precede read-only type reuse')
        old_proof = ElementIdentityProof.from_dict(old['element_identity'])
        ledger = ledgers.get(oid)
        replacement, current_uid = None, old_proof.unique_id
        if ledger is not None:
            body = ledger.to_dict()
            _require(body['archive_digest'] == archive.digest
                     and body['receipt_digest'] == bound.receipt_digest,
                     'staged_replacement_publication_mismatch',
                     'replacement ledger belongs to another publication')
            _require(body['observation']['target'] == target.to_dict()
                     and body['observation']['precondition'] == c0.to_dict(),
                     'staged_replacement_observation_mismatch',
                     'replacement ledger was confirmed against another snapshot')
            current_uid = ledger.effective_unique_id(old_proof.unique_id)
            if current_uid != old_proof.unique_id:
                replacement = {'original_unique_id': old_proof.unique_id, 'effective_unique_id': current_uid,
                               'reason': next(entry['reason'] for entry in ledger.replacements
                                              if entry['original_identity']['unique_id'] == old_proof.unique_id),
                               'ledger_digest': ledger.digest}
        row = observed_rows.get(current_uid)
        _require(type(row) is dict, 'staged_import_observation_absent',
                 'the current import address was not requested in this observation')
        _require(row['status'] != 'unavailable', 'staged_import_observation_unavailable',
                 'the current import address could not be read at this revision')
        _require(row['status'] == 'observed',
                 'staged_import_replacement_unconfirmed' if ledger is not None else 'staged_import_element_not_found',
                 'the model reports no element at the current import address')
        proof = _identity(row)
        _require(proof is not None and proof.unique_id == current_uid,
                 'staged_import_observation_mismatch', 'current proof must preserve the current import UID')
        _require(proof.unique_id not in {value.unique_id for value in current_imports.values()},
                 'staged_import_identity_conflict', 'distinct imports cannot claim one native identity')
        operation = normalized[oid]
        comparison = (_level_comparison(row, operation) if operation['op'] == 'create_level'
                      else _type_comparison(observation, proof.unique_id, operation))
        guard(proof)
        if row['type_state'] is not None:
            guard(_identity(row['type_state']))
        if row['type_definition']['status'] == 'observed':
            for layer in row['type_definition']['value']['layers']:
                if layer['material_identity'] is not None:
                    guard(ElementIdentityProof.from_dict(layer['material_identity']))
        current_imports[oid] = proof
        sources.append((oid, original))
        lineage.append({'output_id': oid, 'instance_key': instance.key, 'output_key': output.key,
            'reference_kind': next(row['reference_kind'] for row in partition.to_dict()['imports'] if row['output_id'] == oid),
            'source_operation_digest': _hash({**_thaw(output.operation), 'id': oid}),
            'module_definition_digest': module.definition_digest, 'instance_parameters_digest': _hash(instance.parameters),
            'original_project_revision': project.revision_id, 'original_archive_digest': archive.digest,
            'original_receipt_digest': bound.receipt_digest, 'original_identity_assessment_digest': assessment.digest,
            'original_precondition': binding['precondition'], 'original_identity_state': old['state'],
            'original_identity': old_proof.to_dict(), 'observed_identity': proof.to_dict(),
            'identity_replacement': replacement,
            'observation_row': row, 'declared_comparison': comparison})
    runtime_ops, table = [], []
    for operation in partition.to_dict()['symbolic_export_ops']:
        runtime = _thaw(operation)
        for param in spec.OPS[operation['op']].params:
            selector = operation.get(param.name)
            if param.kind not in ('sel', 'target_w') or type(selector) is not dict or selector.get('by') != 'ref':
                continue
            imported_id = selector['value'].strip()
            if imported_id not in current_imports:
                continue
            projected = {**selector, 'by': 'element_id', 'value': current_imports[imported_id].element_id}
            runtime[param.name] = projected
            table.append({'export_output_id': operation['id'], 'field': param.name, 'import_output_id': imported_id,
                          'source_selector': selector, 'runtime_selector': projected})
        runtime_ops.append(runtime)
    program = {'ir_version': partition.project.ir_version, 'intent': partition.project.intent,
               'lineage': partition.project.project_id, 'ops': runtime_ops}
    plan = plan_program(program, bulk=partition.materialization.planned.bulk)
    guards = tuple(sorted(guards_by_id.values(), key=lambda proof: (proof.element_id, proof.unique_id)))
    core = {'schema': STAGED_ASSOCIATION_SCHEMA, 'partition_digest': partition.digest,
        'runtime_program_digest': _hash(program), 'runtime_plan_digest': plan.plan_digest,
        'target': target.to_dict(), 'precondition': c0.to_dict(), 'isolation': isolation,
        'import_lineage': lineage, 'projection_table': table,
        'expected_identities': [proof.to_dict() for proof in guards],
        'required_import_unique_ids': [current_imports[oid].unique_id for oid in partition.import_output_ids],
        'observation': observation.to_dict(),
        'claims': {'scope': 'fresh_guarded_preparation_only', 'guard_proofs': 'identity_dependencies_not_ownership',
                   'import_preservation': 'declared_clauses_only', 'dispatch_permission': 'none'}}
    result = object.__new__(StagedCreateProjection)
    for name, value in {'partition': partition, 'observation': observation, 'target': target, 'precondition': c0,
        'isolation': isolation, 'runtime_plan': plan, 'expected_identities': guards, 'association_digest': _hash(core),
        'replacements': tuple(sorted(ledgers.items())),
        '_runtime_program': _object(program, 'staged_runtime_program'), '_core': _object(core, 'staged_association_core'),
        '_sources': tuple(sources)}.items():
        object.__setattr__(result, name, value)
    return result


def prepare_staged_create(projection, *, operation_id):
    _require(type(projection) is StagedCreateProjection, 'staged_projection_required', 'fresh typed projection required')
    projection.validate()
    return prepare_execution(projection.runtime_plan, target=projection.target, precondition=projection.precondition,
        operation_id=operation_id, bulk=projection.runtime_plan.bulk, isolation=projection.isolation,
        association_digest=projection.association_digest, expected_identities=projection.expected_identities)


__all__ = ['STAGED_PROJECTION_SCHEMA', 'STAGED_ASSOCIATION_SCHEMA', 'StagedProjectionError',
           'StagedCreateProjection', 'bind_staged_create_projection', 'prepare_staged_create']
