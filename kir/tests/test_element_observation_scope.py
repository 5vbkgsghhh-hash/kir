"""Batched real compiler/query parser, synthetic exchange; no Revit execution."""
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
from uuid import uuid4

import pytest

from kir.contracts import ElementIdentityProof
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials
from kir.revit_discovery import load_discovery
import kir.revit_observation as owner
from kir.revit_transport import ConnectorTransportError
from kir.tests.test_revit_observation import row


def native_row(uid, index):
    value = row(uid, is_level=False)
    value['element_identity'] = ElementIdentityProof(10000 + index, uid, 'a' * 32).to_dict()
    return value


def receipt(binding, rows):
    return {**binding, 'document_key': binding['precondition']['document_key'],
        'state': 'invocation_completed', 'started': True, 'may_retry': False,
        'transaction_evidence': 'changes_not_observed', 'semantic_evidence': 'unverified',
        'error': None, 'result_json': json.dumps(rows), 'result_truncated': False, 'result_error': None,
        'changes': {'added': [], 'modified': [], 'deleted': [], 'transaction_names': [], 'truncated': False},
        'timestamp_utc': '2026-09-06T12:00:00Z'}


def response(credentials, request_id, native):
    return {'protocol': 'kir-revit-connector/4', 'target': credentials.target.to_dict(),
        'session_id': credentials.session_id, 'request_id': request_id, 'ok': True, 'error': None,
        'context': None, 'status': 'receipt', 'receipt': native}


@pytest.fixture
def carriers():
    target = RuntimeTarget(str(uuid4()), str(uuid4()), '2023')
    credentials = SessionCredentials(target, str(uuid4()), 'synthetic-not-output')
    precondition = ContextPrecondition('chosen-doc', 10, 11, 'd' * 64)

    def make(uids, *, start=0, mutate=None, context=precondition, runtime=target):
        prepared = owner.prepare_element_observation(uids, target=runtime,
            precondition=context, operation_id=str(uuid4()))
        creds = credentials if runtime == target else SessionCredentials(runtime, str(uuid4()), 'synthetic')
        rows = {f'observe_{i}': native_row(uid, start + i) for i, uid in enumerate(uids)}
        if mutate:
            mutate(rows)
        request_id = str(uuid4())
        wire = response(creds, request_id, receipt(prepared.binding_dict(), rows))
        return owner.parse_element_observation(prepared, json.dumps(wire), credentials=creds, request_id=request_id)
    return make, target, precondition


def test_join_preserves_inputs_order_context_and_indexed_immutable_proofs(carriers, monkeypatch):
    make, target, context = carriers
    a, b = make(['a']), make(['b'], start=1)
    combined = owner.combine_element_observations([b, a], expected_unique_ids=['a', 'b'])
    assert type(combined) is owner.ElementObservationSet
    assert combined.target == target and combined.precondition is context
    assert list(combined.rows) == ['a', 'b']
    expected = [{'operation_id': p.operation_id, 'source_sha256': p.source_sha256,
                 'requested_unique_ids': list(p.rows)} for p in (b, a)]
    assert combined.query_inputs == expected
    canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    assert combined.query_inputs_digest == sha256(canonical).hexdigest()
    assert not hasattr(combined, 'operation_id') and not hasattr(combined, 'source_sha256')
    assert not hasattr(combined, 'current') and not hasattr(combined, 'accepted')
    detached = combined.rows
    detached['a']['element_identity']['element_id'] = 42
    combined.query_inputs[0]['requested_unique_ids'].clear()
    assert combined.require_identity('a').element_id == 10000
    assert combined.query_inputs == expected
    with pytest.raises(TypeError):
        combined._indexed_rows['a'] = '{}'
    with pytest.raises(FrozenInstanceError):
        combined.query_inputs_digest = 'f' * 64
    with pytest.raises(TypeError):
        owner.ElementObservationSet()
    monkeypatch.setattr(owner.json, 'loads', lambda *_: pytest.fail('require_identity decoded JSON'))
    for _ in range(100):
        assert combined.require_identity('a').element_id == 10000
        assert combined.require_identity('b').element_id == 10001


@pytest.mark.parametrize('scope,parts,code', [
    (['a', 'a'], 'one', 'duplicate_observation_identity'),
    (['a', 'b'], 'one', 'observation_scope_mismatch'),
    (['b'], 'one', 'observation_scope_mismatch'),
    (['a', 'b'], 'overlap', 'duplicate_observation_identity'),
    (['a'], 'dict', 'element_observation_required'),
    ([], 'one', 'observation_aggregate_budget'),
])
def test_exact_scope_and_existing_carriers_required(carriers, scope, parts, code):
    make, _, _ = carriers
    a = make(['a'])
    values = [a] if parts == 'one' else [a, make(['a'])] if parts == 'overlap' else [a.rows]
    with pytest.raises(owner.ObservationRefusal, match=code):
        owner.combine_element_observations(values, expected_unique_ids=scope)


@pytest.mark.parametrize('field,value', [('revision', 11), ('document_key', 'other'),
    ('active_view_id', 12), ('selection_digest', 'e' * 64)])
def test_every_precondition_dimension_must_agree(carriers, field, value):
    make, _, precondition = carriers
    a = make(['a'])
    b = make(['b'], start=1, context=replace(precondition, **{field: value}))
    with pytest.raises(owner.ObservationRefusal, match='observation_context_mismatch'):
        owner.combine_element_observations([a, b], expected_unique_ids=['a', 'b'])


def test_runtime_target_must_agree(carriers):
    make, target, _ = carriers
    a = make(['a'])
    b = make(['b'], start=1, runtime=replace(target, instance_id=str(uuid4())))
    with pytest.raises(owner.ObservationRefusal, match='observation_context_mismatch'):
        owner.combine_element_observations([a, b], expected_unique_ids=['a', 'b'])


@pytest.mark.parametrize('conflict', ['id', 'type_version', 'type_id', 'type_uid', 'element_as_type'])
def test_cross_chunk_identity_contradictions_are_not_hidden(carriers, conflict):
    make, _, _ = carriers
    a = make(['a'])
    def change(rows):
        value = rows['observe_0']
        if conflict == 'id':
            value['element_identity']['element_id'] = 10000
        elif conflict == 'element_as_type':
            value['type_state']['element_identity'] = ElementIdentityProof(10000, 'a', 'b' * 32).to_dict()
        else:
            key, replacement = {'type_version': ('version_guid', 'b' * 32),
                'type_id': ('element_id', 901), 'type_uid': ('unique_id', 'different-type')}[conflict]
            value['type_state']['element_identity'][key] = replacement
    b = make(['b'], start=1, mutate=change)
    with pytest.raises(owner.ObservationRefusal, match='conflicting_element_identity'):
        owner.combine_element_observations([a, b], expected_unique_ids=['a', 'b'])


def test_missing_element_is_explicit_not_complete_identity_or_currentness(carriers):
    make, _, _ = carriers
    def missing(rows):
        rows['observe_0'].update(status='not_found', name=None, category_id=None, is_level=None,
            type_state=None, level_status='not_evaluated', element_identity=None,
            element_identity_status='unavailable', element_identity_reason='element_missing')
    combined = owner.combine_element_observations([make(['a']), make(['b'], mutate=missing)],
        expected_unique_ids=['a', 'b'])
    assert combined.rows['b']['status'] == 'not_found'
    assert combined.require_identity('a').element_id == 10000
    with pytest.raises(owner.ObservationRefusal, match='element_identity_unavailable'):
        combined.require_identity('b')


def test_aggregate_budget_checked_before_decoding_carriers(carriers, monkeypatch):
    make, _, _ = carriers
    a, b = make(['a']), make(['b'], start=1)
    monkeypatch.setattr(owner, 'MAX_OBSERVATION_AGGREGATE_BYTES', len(a._rows_json.encode()) + 10)
    monkeypatch.setattr(owner.ElementObservation, 'rows', property(lambda _: pytest.fail('decoded oversized aggregate')))
    with pytest.raises(owner.ObservationRefusal, match='observation_aggregate_budget'):
        owner.combine_element_observations([a, b], expected_unique_ids=['a', 'b'])


def test_known_shared_type_cannot_be_reported_not_found_by_another_chunk(carriers):
    make, _, _ = carriers
    def missing(rows):
        rows['observe_0'].update(status='not_found', name=None, category_id=None, is_level=None,
            type_state=None, level_status='not_evaluated', element_identity=None,
            element_identity_status='unavailable', element_identity_reason='element_missing')
    with pytest.raises(owner.ObservationRefusal, match='conflicting_element_identity'):
        owner.combine_element_observations([make(['a']), make(['type-uid'], mutate=missing)],
            expected_unique_ids=['a', 'type-uid'])


def test_metadata_bytes_count_toward_retained_budget(carriers, monkeypatch):
    make, _, _ = carriers
    a = make(['a'])
    monkeypatch.setattr(owner, 'MAX_OBSERVATION_AGGREGATE_BYTES', len(a._rows_json.encode()) + 1)
    with pytest.raises(owner.ObservationRefusal, match='observation_aggregate_budget'):
        owner.combine_element_observations([a], expected_unique_ids=['a'])


def batched(monkeypatch, count, fault=None, **options):
    target = RuntimeTarget(str(uuid4()), str(uuid4()), '2023')
    advertisement = load_discovery(json.dumps({'protocol': 'kir-revit-connector/4', 'target': target.to_dict(),
        'session_id': str(uuid4()), 'token': 'synthetic-private', 'pipe_name': 'unused', 'process_id': 123,
        'expires_utc': '2099-01-01T00:00:00.0000000Z'}).encode())
    events, prepared = [], []
    actual_prepare = owner.prepare_element_observation
    def prepare(*args, **kwargs):
        value = actual_prepare(*args, **kwargs)
        prepared.append(value)
        return value
    monkeypatch.setattr(owner, 'prepare_element_observation', prepare)
    def exchange(ad, wire, **kwargs):
        request = json.loads(wire)
        events.append(request)
        answer = response(ad.credentials, request['request_id'], None)
        if request['kind'] == 'context':
            answer.update(status='context', context={'has_document': True, 'document_key': 'chosen-doc',
                'document_title': 'Not identity', 'revit_version': '2023', 'revision': 10,
                'active_view_id': 11, 'selection_digest': 'd' * 64, 'selection_count': 2,
                'is_family_document': False, 'is_read_only': False, 'is_modifiable': False, 'complete': True})
        else:
            artifact = prepared[-1]
            ops = artifact.planned.to_ops()
            assert 1 <= len(ops) <= 128
            assert all(op['op'] == 'query_element_state' for op in ops)
            assert 'new Transaction(' not in request['source']
            rows = {op['id']: native_row(op['unique_id'], int(op['unique_id'].split('-')[1])) for op in ops}
            native = receipt(artifact.binding_dict(), rows)
            if len(prepared) == 2:
                if fault == 'drift': native['precondition'] = {**native['precondition'], 'revision': 11}
                elif fault == 'incomplete': native['result_truncated'] = True
                elif fault == 'missing': native['result_json'] = '{}'
                elif fault == 'refused': native.update(state='context_changed_before_start', started=False,
                    may_retry=True, transaction_evidence='not_observed', changes=None, result_json=None, error='changed')
                elif fault == 'lost': raise ConnectorTransportError('synthetic_lost_read', 'response', delivery='unknown')
                elif fault == 'type_conflict':
                    for value in rows.values(): value['type_state']['element_identity']['version_guid'] = 'b' * 32
                    native['result_json'] = json.dumps(rows)
            answer['receipt'] = native
        return json.dumps(answer).encode()
    monkeypatch.setattr('kir.revit_transport.exchange', exchange)
    try:
        observed = owner.observe_element_scope([f'uid-{i}' for i in range(count)], advertisement=advertisement,
            client_path='/not-called', expected_target=target, expected_document_key='chosen-doc',
            bind_view=True, bind_selection=True, **options)
    except (owner.ObservationRefusal, ConnectorTransportError) as error:
        return error, events, prepared
    return observed, events, prepared


@pytest.mark.parametrize('count', [129, 257])
def test_large_scope_real_compiler_retains_original_context_for_every_chunk(monkeypatch, count):
    result, events, prepared = batched(monkeypatch, count)
    assert type(result) is owner.ElementObservationSet
    assert [event['kind'] for event in events] == ['context'] + ['execute'] * ((count + 127) // 128)
    assert len(result.rows) == count and len(result.query_inputs) == len(prepared)
    assert len({p.operation_id for p in prepared}) == len(prepared)
    assert len({e['request_id'] for e in events}) == len(events)
    assert all(p.precondition is prepared[0].precondition for p in prepared)
    assert result.precondition is prepared[0].precondition
    assert result.precondition.to_dict() == {'document_key': 'chosen-doc', 'revision': 10,
        'active_view_id': 11, 'selection_digest': 'd' * 64}
    assert result.require_identity(f'uid-{count - 1}').element_id == 10000 + count - 1
    for event in events[1:]: assert event['precondition'] == result.precondition.to_dict()


@pytest.mark.parametrize('fault', ['drift', 'incomplete', 'missing', 'refused', 'lost'])
def test_second_query_failure_never_refreshes_retries_or_sends_third(monkeypatch, fault):
    result, events, prepared = batched(monkeypatch, 257, fault)
    assert isinstance(result, Exception)
    assert [e['kind'] for e in events] == ['context', 'execute', 'execute']
    assert len(prepared) == 2 and prepared[0].precondition is prepared[1].precondition


def test_successful_chunks_with_conflicting_type_version_produce_no_aggregate(monkeypatch):
    result, events, _ = batched(monkeypatch, 129, 'type_conflict')
    assert isinstance(result, owner.ObservationRefusal) and result.code == 'conflicting_element_identity'
    assert len(events) == 3


def test_scope_byte_budget_precedes_any_context_exchange(monkeypatch):
    monkeypatch.setattr(owner, 'MAX_OBSERVATION_AGGREGATE_BYTES', 15)
    result, events, prepared = batched(monkeypatch, 129)
    assert isinstance(result, owner.ObservationRefusal) and result.code == 'observation_aggregate_budget'
    assert not events and not prepared


def test_aggregate_growth_stops_before_third_query_without_partial_result(monkeypatch):
    # One 128-row query fits; two individually valid query responses do not.
    one = sum(len(json.dumps(native_row(f'uid-{i}', i), ensure_ascii=False,
        separators=(',', ':')).encode()) + len(f'uid-{i}') + 4 for i in range(128))
    monkeypatch.setattr(owner, 'MAX_OBSERVATION_AGGREGATE_BYTES', one + 8000)
    result, events, prepared = batched(monkeypatch, 257)
    assert isinstance(result, owner.ObservationRefusal) and result.code == 'observation_aggregate_budget'
    assert [e['kind'] for e in events] == ['context', 'execute', 'execute']
    assert len(prepared) == 2


@pytest.mark.parametrize('scope', ['', b'uid', ['a', 1], [''], ['a', 'a']])
def test_invalid_scope_never_reaches_transport(monkeypatch, scope):
    monkeypatch.setattr('kir.revit_transport.exchange', lambda *a, **k: pytest.fail('unexpected exchange'))
    with pytest.raises(owner.ObservationRefusal):
        owner.observe_element_scope(scope, advertisement=None, client_path='/unused', expected_target=None,
            expected_document_key='doc', bind_view=False, bind_selection=False)
