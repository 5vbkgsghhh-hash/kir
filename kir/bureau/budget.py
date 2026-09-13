"""Attempt-addressed budget entries in the existing team task checkpoints.

`tokens` is backward-compatible exposure: reported + estimated + reserved +
unknown units. It is not an invoice or a measurement of a responder's thinking.
Unknown delivery never refunds a reservation; actual overrun is never clipped.
"""
from collections.abc import Mapping
from dataclasses import replace

from kir.bureau.provider import CompletionResponse, ProviderRefusal, _checked_usage_basis
from kir.project import _canonical
from kir.project_store import StoreConflict, StoreNotFound
from kir.project_tasks import checkpoint_task, read_task, task_history


def entries(store):
    from kir.bureau import runner as R
    try:
        events = task_history(store, R.TEAM_TASK)
    except StoreNotFound:
        return {}, [], False
    attempts, legacy, legacy_unknown = {}, [], False
    legacy_calls_balance = legacy_tokens_balance = 0
    for event in events:
        notes = event['body'].get('notes', {})
        if not isinstance(notes, Mapping) or R._SPEND not in notes:
            continue
        row = notes[R._SPEND]
        if type(row) is not dict:
            raise R.BureauRefusal('budget_ledger_invalid', 'accounting entry must be an object, not absent usage')
        if 'attempt_id' not in row:
            states = ('reserved', 'actual', 'after_stop', 'provider_failed', 'overrun_refused')
            if (row.get('state') not in states or type(row.get('calls')) is not int
                    or type(row.get('tokens')) is not int
                    or set(row) - {'calls', 'tokens', 'state', 'detail', 'provider_id'}):
                raise R.BureauRefusal('budget_ledger_invalid', 'malformed or unknown legacy accounting')
            # Historical actual-minus-reserved deltas may legally be negative.
            if row['state'] == 'reserved' and (row['calls'] != 1 or row['tokens'] < 0):
                raise R.BureauRefusal('budget_ledger_invalid', 'invalid legacy reservation')
            if row['state'] == 'provider_failed' and (row['calls'] != 0 or row['tokens'] > 0):
                raise R.BureauRefusal('budget_ledger_invalid', 'invalid legacy failure correction')
            legacy_calls_balance += row['calls']
            legacy_tokens_balance += row['tokens']
            if legacy_calls_balance < 0 or legacy_tokens_balance < 0:
                raise R.BureauRefusal('budget_ledger_invalid', 'legacy accounting prefix spent an absent reservation')
            legacy.append(row)
            legacy_unknown |= row.get('state') == 'provider_failed'
            overrun = notes.get('bureau_overrun')
            if 'bureau_overrun' in notes:
                if (type(overrun) is not dict or set(overrun) != {'actual_tokens', 'ceiling'}
                        or any(type(v) is not int or v < 0 for v in overrun.values())
                        or overrun['actual_tokens'] < overrun['ceiling']):
                    raise R.BureauRefusal('budget_ledger_invalid', 'malformed legacy overrun')
                extra = overrun['actual_tokens'] - overrun['ceiling']
                legacy_tokens_balance += extra
                legacy.append({'calls': 0, 'tokens': extra})
            continue
        key = row['attempt_id']
        if (type(key) is not str or not key or row.get('state') not in ('reserved', 'unknown', 'actual')
                or type(row.get('tokens')) is not int or row['tokens'] < 0 or row.get('calls') != 1
                or type(row.get('calls')) is not int):
            raise R.BureauRefusal('budget_ledger_invalid', 'invalid attempt accounting entry')
        fields = {'attempt_id', 'state', 'calls', 'tokens'}
        if row['state'] == 'actual':
            fields |= {'usage_basis', 'provider_id'}
            try:
                _checked_usage_basis(row.get('usage_basis'))
            except ProviderRefusal as error:
                raise R.BureauRefusal('budget_ledger_invalid', 'unknown actual usage basis') from error
            if type(row.get('provider_id')) is not str or not row['provider_id'].strip():
                raise R.BureauRefusal('budget_ledger_invalid', 'actual usage must name its reporting provider')
        if set(row) != fields:
            raise R.BureauRefusal('budget_ledger_invalid', 'unknown accounting fields')
        previous = attempts.get(key)
        if previous is None and row['state'] != 'reserved':
            raise R.BureauRefusal('budget_ledger_invalid', 'attempt has no initial reservation')
        if previous is not None:
            if row['state'] == 'reserved' or previous['state'] == 'actual' and _canonical(previous) != _canonical(row):
                raise R.BureauRefusal('budget_ledger_invalid', 'attempt accounting cannot be reset')
            if row['state'] == 'unknown' and row['tokens'] != previous['tokens']:
                raise R.BureauRefusal('budget_ledger_invalid', 'unknown attempt cannot release its reserve')
        attempts[key] = dict(row)
    return attempts, legacy, legacy_unknown


def spend(store):
    attempts, legacy, legacy_unknown = entries(store)
    result = {'calls': 0, 'tokens': 0, 'reported_tokens': 0, 'estimated_tokens': 0,
              'reserved_tokens': 0, 'unknown_tokens': 0, 'legacy_tokens': 0,
              'unknown_calls': 0,
              'legacy_unknown_usage': legacy_unknown, 'accounting': 'exposure_not_money_or_total_model_compute'}
    for row in legacy:
        result['calls'] += int(row.get('calls', 0))
        result['legacy_tokens'] += int(row.get('tokens', 0))
        if row.get('state') == 'provider_failed':
            # Restore the old refunded allocation as UNKNOWN, not measured use.
            result['unknown_tokens'] += -row['tokens']
            result['unknown_calls'] += 1
    if result['calls'] < 0 or result['legacy_tokens'] < 0:
        from kir.bureau.runner import BureauRefusal
        raise BureauRefusal('budget_ledger_invalid', 'negative legacy accounting')
    for row in attempts.values():
        result['calls'] += 1
        if row['state'] == 'unknown':
            result['unknown_calls'] += 1
        category = (row['state'] + '_tokens' if row['state'] != 'actual' else
                    'estimated_tokens' if row.get('usage_basis') == 'estimated_response_units' else 'reported_tokens')
        result[category] += row['tokens']
    result['tokens'] = sum(result[key] for key in
        ('reported_tokens', 'estimated_tokens', 'reserved_tokens', 'unknown_tokens', 'legacy_tokens'))
    return result


def reserve(store, budget, planned, *, attempt_id, expected_task_versions=None):
    """Only the inserting caller may invoke. Existing reservation means lookup."""
    from kir.bureau import runner as R
    for _ in range(R._RESERVE_ATTEMPTS):
        team = R._ensure_team(store)
        previous = entries(store)[0].get(attempt_id)
        if previous is not None:
            return False
        R._gate(store, budget, planned)
        if spend(store)['legacy_unknown_usage']:
            raise R.BureauRefusal('legacy_budget_reconciliation_required',
                                  'old refunded failures need explicit budget review; no new call')
        try:
            checkpoint_task(store, R.TEAM_TASK, request_id=R._ticket(), expected_version=team['version'],
                generation=team['generation'], actor='bureau-coordinator', expected_task_versions=expected_task_versions,
                notes={R._SPEND: {'attempt_id': attempt_id, 'state': 'reserved', 'calls': 1, 'tokens': planned}})
            return True
        except StoreConflict:
            if expected_task_versions:
                for key, version in expected_task_versions.items():
                    if read_task(store, key)['version'] != version:
                        raise
    raise R.BureauRefusal('budget_contended', 'budget reservation contention; no provider call')


def settle(store, attempt_id, response=None):
    """Facts may be retained after Stop; this never permits another action."""
    from kir.bureau import runner as R
    if response is not None:
        if type(response) is not CompletionResponse:
            raise R.BureauRefusal('provider_response_invalid', 'typed completion response required')
        # Recheck mutable usage dictionaries without weakening the provider codec.
        response = CompletionResponse(**response.to_dict())
    for _ in range(R._RESERVE_ATTEMPTS):
        team = R._ensure_team(store)
        prior = entries(store)[0].get(attempt_id)
        if prior is None:
            raise R.BureauRefusal('budget_ledger_invalid', 'completion has no budget reservation')
        if response is None:
            if prior['state'] == 'actual':
                return
            row = {**prior, 'state': 'unknown'}
        else:
            row = {'attempt_id': attempt_id, 'state': 'actual', 'calls': 1, 'tokens': response.tokens,
                   'usage_basis': response.usage_basis, 'provider_id': response.provider_id}
        if _canonical(row) == _canonical(prior):
            return
        if prior['state'] == 'actual':
            raise R.BureauRefusal('provider_response_changed', 'one attempt cannot acquire another usage result')
        try:
            checkpoint_task(store, R.TEAM_TASK, request_id=R._ticket(), expected_version=team['version'],
                generation=team['generation'], actor='bureau-coordinator', notes={R._SPEND: row})
            return
        except StoreConflict:
            continue
    raise R.BureauRefusal('journal_contended', 'usage not settled; reservation retained')


def bounded_request(store, request, budget):
    from kir.bureau import runner as R
    if R.is_stopped(store):
        raise R.BureauRefusal('team_stopped', 'the team is stopped; no provider call is made')
    remaining = budget.max_tokens - spend(store)['tokens']
    if remaining <= 0:
        raise R.BureauRefusal('token_budget_exhausted', 'no unreserved response budget remains')
    return replace(request, max_tokens=min(request.max_tokens, remaining))


def ask(store, provider, request, budget):
    """Compatibility one-shot API; durable work uses a task-bound attempt ID."""
    from kir.bureau import runner as R
    request = bounded_request(store, request, budget)
    key = R._ticket()
    reserve(store, budget, request.max_tokens, attempt_id=key)
    try:
        response = provider.complete(request)
    except Exception as error:
        settle(store, key, getattr(error, 'response', None))
        raise
    settle(store, key, response)
    if response.tokens > request.max_tokens:
        raise R.BureauRefusal('token_budget_overrun', 'reported usage exceeded reserve; result refused, usage retained',
                              calls=1, tokens=response.tokens)
    if R.is_stopped(store):
        raise R.BureauRefusal('stopped_during_call', 'response retained as usage; no further action', calls=1, tokens=response.tokens)
    return response
