"""One durable bureau work attempt, using existing task tool events only.

No executor or database is introduced. A pending invocation is never permission
to invoke again; only an already retained response may be looked up. Stop guards
new actions, while completed facts remain recordable at the original generation.
"""
from dataclasses import asdict
import hashlib

from kir import spec
from kir.bureau.provider import CompletionRequest, CompletionResponse, ProviderRefusal, request_key
from kir.bureau import budget as accounting
from kir.project import ModuleInstance, NamedOutput, _canonical, _hash, _thaw, output_id
from kir.diag import KirRefusal
from kir.project_merge import ChangeProposal, ProposalScope
from kir.project_store import StoreConflict, StoreNotFound
from kir.project_tasks import (begin_task_tool, finish_task_tool, read_task, submit_task,
                               tool_result_request_id, MAX_EVENT_BYTES, TaskError)


#: 🔴 A RETRY WITH A STALE ARGUMENT IS NOT A RETRY, IT'S A LIVELOCK. Measured
#: with two processes (8 runs, 3 failures IN A ROW at both 8 and 40
#: attempts) showed: the conflict came not from the team epoch, but from
#: `expected_revision`, taken ONCE before the loop. The neighbor's proposal
#: would be accepted, the head would move on, and every next attempt
#: brought the same stale head — no matter how many times it retried.
#: `refresh` gives the action fresh arguments on EVERY attempt; a decision
#: made on a fresh head is a legitimate merge, not a weakening of the guard.
#:
#: How many times the action is allowed to lose to the team epoch. The
#: number isn't out of thin air: one plan turn writes to the team's book
#: five times (booking, assignment, reservation, settlement, turn record),
#: so with TWO workers the number of foreign writes between my reading the
#: version and my writing can be just as many. Eight attempts (measured
#: 07.09: 3 failures out of 8 runs) was not enough; the limit remains a
#: limit.
EPOCH_ATTEMPTS = 40


def guarded(store, task, action, refresh=None, **kwargs):
    """TEAM epoch and target task fence checked in the action's SQL transaction.

    🔴 AN EVEN RETRY WITH NO PAUSE LOSES TO A BUSY NEIGHBOR. Measured 07.09
    with two processes on one plan: eight attempts in a row with no delay
    ran into `team_epoch_contended` on level ground — the team book's
    version moved between the read and the write almost every time, because
    the neighbor was writing its own notes and settlement at the same
    moment. The limit remains a LIMIT (no "wait forever"), but attempts are
    spread apart by a random pause, otherwise two processes fall into
    lockstep with each other and both lose.
    """
    import random
    import time

    from kir.bureau import runner as R
    for attempt in range(EPOCH_ATTEMPTS):
        team = R._ensure_team(store)
        if R.is_stopped(store):
            raise R.BureauRefusal('team_stopped', 'Stop forbids this new action')
        try:
            return action(store, task['task_id'], expected_version=task['version'],
                generation=task['generation'], actor=task['actor'],
                expected_task_versions={R.TEAM_TASK: team['version']},
                **(refresh(kwargs) if refresh is not None else kwargs))
        except StoreConflict:
            current = read_task(store, task['task_id'])
            if current['version'] != task['version']:
                raise
            time.sleep(min(0.05, 0.004 * 2 ** min(attempt, 4)) * (0.5 + random.random()))
    raise R.BureauRefusal('team_epoch_contended', 'no effect after bounded epoch retries')


def _call(task, identifier):
    return next((row for row in task['tool_calls'] if row['request_id'] == identifier), None)


def _finish(store, original, identifier, output):
    """Persist finished facts after Stop, never relabel a superseded generation."""
    from kir.bureau import runner as R
    for _ in range(R._RESERVE_ATTEMPTS):
        task = read_task(store, original['task_id'])
        call = _call(task, identifier)
        if call is not None and call['state'] == 'recorded':
            if _canonical(call['output']) != _canonical(output):
                raise R.BureauRefusal('completion_changed', 'one attempt has different completion facts')
            return task
        if task['generation'] != original['generation'] or task['actor'] != original['actor']:
            raise R.BureauRefusal('generation_changed', 'finished work belongs to a superseded assignment')
        try:
            return finish_task_tool(store, task['task_id'], request_id=tool_result_request_id(identifier),
                expected_version=task['version'], generation=task['generation'], actor=task['actor'],
                tool_request_id=identifier, output=output)['task']
        except StoreConflict:
            continue
    raise R.BureauRefusal('completion_contended', 'finished facts not retained; never invoke again automatically')


def _patch(before, proposed):
    if isinstance(before, dict) and isinstance(proposed, dict):
        result = dict(before)
        for key, value in proposed.items():
            result[key] = _patch(before.get(key), value)
        return result
    return _thaw(proposed)


def _candidate(store, task, response, evaluated):
    from kir.bureau import runner as R
    head = store.get(task['assignment']['base_revision'])
    instance_key = task['assignment']['scope']['instances'][0]
    previous = next(item for item in head.instances if item.key == instance_key)
    original = {item.key: item for item in previous.outputs}
    ops = evaluated.to_program()['ops']
    local_ids = {op.get('id') for op in ops}
    if not ops or None in local_ids or len(local_ids) != len(ops):
        raise R.BureauRefusal('invalid_output_ids', 'model must name distinct outputs')
    declared = R._declared_outputs(task)
    if declared is not None and set(declared) != local_ids:
        extra = local_ids - set(declared)
        raise R.BureauRefusal('undeclared_output' if extra else 'missing_declared_output',
                              'response outputs differ from the explicit grant')
    removals = R._task_notes(task).get('bureau_remove_fields', {})
    if set(removals) - local_ids:
        raise R.BureauRefusal('field_removal_not_applied', 'removal decision requires that output in the response')
    written = {}
    for op in ops:
        key = op['id']
        patch = {name: _thaw(value) for name, value in op.items() if name != 'id'}
        old = original.get(key)
        if old is not None:
            if old.geometry is not None:
                raise R.BureauRefusal('body_owned_edit_unsupported', 'use the geometry owner to change a body')
            if patch.get('op') != old.operation['op']:
                raise R.BureauRefusal('operation_kind_change_requires_decision', 'field patch cannot replace an operation kind')
        definition = spec.OPS.get(patch.get('op'))
        if definition is None:
            raise R.BureauRefusal('operation_profile_unsupported', 'bureau field patches require direct registered operations')
        # Rewrite only model-supplied typed selector slots, never retained fields
        # or arbitrary metadata dictionaries that happen to say by:ref.
        #
        # 🔴 A REFERENCE CAN POINT TO AN OUTPUT THAT THIS RESPONSE DOES NOT
        # REWRITE (run-4, item (b), 07.09). A live responder sent ONE op — a
        # patch to wall `BW` with `level: {'by':'ref','value':'B0'}`, where
        # `B0` is an existing level of that same target. The `local_ids` set
        # only knows the `id` of the RESPONSE, the address was never
        # substituted, the reference stayed a name — and a legitimate
        # response went into `project_selection_unresolved`, with
        # acceptance reading this as "the decision was not changed." The
        # bureau knows the target's output keys: the `id` in the response IS
        # the output key. Substituting one's own address is not a guess,
        # it's arithmetic.
        known = local_ids | set(original)
        for parameter in definition.params:
            selector = patch.get(parameter.name)
            if parameter.kind in ('sel', 'target_w') and isinstance(selector, dict) and selector.get('by') == 'ref':
                if selector.get('value') in known:
                    patch[parameter.name] = {**selector, 'value': output_id(head.project_id, instance_key, selector['value'])}
        operation = _patch(_thaw(old.operation) if old is not None else {}, patch)
        for name in removals.get(key, ()):
            if old is None or name not in old.operation or name in patch:
                raise R.BureauRefusal('field_removal_conflict', 'remove only an existing, unsupplied field by explicit decision')
            operation.pop(name)
        written[key] = NamedOutput(key, operation)
    outputs = [written.pop(item.key, item) for item in previous.outputs]
    outputs.extend(written[key] for key in sorted(written))
    answer_sha = hashlib.sha256(response.text.encode()).hexdigest()
    preservation = {'mode': 'recursive_field_patch_by_output_key', 'base_revision': head.revision_id,
                    'omitted_fields': 'preserved', 'removed_fields': removals, 'supplied_arrays': 'replaced_explicitly'}
    candidate = head.replace_instance(ModuleInstance(instance_key, previous.module_key, outputs,
        _thaw(previous.parameters), metadata={**_thaw(previous.metadata), 'author': 'llm-worker',
            'provider': response.provider_id, 'usage_basis': response.usage_basis,
            'answer_sha256': answer_sha, 'author_digest': evaluated.author_digest,
            'field_preservation': preservation, 'native_execution': 'not_run'}), expected_revision=head.revision_id)
    # A partial model patch is not itself a closed program. Validate the merged
    # authored dependency closure with the existing owners, outside SQL locks.
    from kir.compiler import plan_program
    from kir.project_selection import selected_instance_program
    plan_program(selected_instance_program(candidate, instance_key), bulk=True)
    return ChangeProposal(head, candidate, ProposalScope(instances=(instance_key,)), task['actor'],
                          ('bureau: ' + task['assignment']['objective'])[:200])


def _preflight(store, task):
    from kir.bureau import runner as R
    if R._task_notes(task).get('bureau_profile') != 'durable_work/1':
        raise R.BureauRefusal('legacy_task_requires_new_assignment',
                              'old assigned tasks retain their grants; create an explicit new bureau assignment')
    source = store.get(task['assignment']['base_revision'])
    target = next((item for item in source.instances if item.key == task['assignment']['scope']['instances'][0]), None)
    if target is None:
        raise R.BureauRefusal('unknown_instance', 'target is absent from assigned source')
    module = next(item for item in source.modules if item.key == target.module_key)
    if module.owner != 'explicit':
        raise R.BureauRefusal('sealed_target_requires_handoff',
                              'use explicit handoff, or re-evaluate the actual recipe; no provider call made')


def _response(value):
    return CompletionResponse(**value)


def answer_sha256_of(response):
    return hashlib.sha256(response.text.encode()).hexdigest()


def work(store, task_id, *, provider, budget):
    from kir.bureau import runner as R
    response = None
    charged = 0
    resumed = False
    try:
        task = R._configured_task(store, read_task(store, task_id))
    except StoreNotFound:
        return R.WorkResult(task_id, None, {'code': 'task_not_found'}, 0, 0)
    # Successful replay is a retained fact, even if Stop or a later head exists.
    if task['state'] in ('submitted', 'accepted', 'conflicted') and task.get('proposal'):
        return R.WorkResult(task_id, task['proposal']['proposal_id'], None, 0, 0, replayed=True)
    try:
        if task['state'] != 'assigned':
            raise R.BureauRefusal('task_not_assigned', 'assignment is not active')
        _preflight(store, task)
        generation = task['generation']
        provider_id, sandbox_id = f'bureau-provider-{generation}', f'bureau-python-{generation}'
        attempt_id = _hash([store.store_id, task_id, generation, 'llm.complete'])
        call = _call(task, provider_id)
        needed = int(call is None) + int(_call(task, sandbox_id) is None)
        limit = task['assignment']['budgets'].get('max_tool_calls', 0)
        if len(task['tool_calls']) + needed > limit:
            raise R.BureauRefusal('task_tool_budget_exhausted',
                                  'remaining task slots cannot finish this attempt; create an explicit new assignment')
        resumed = call is not None
        if call is None:
            request = accounting.bounded_request(store, R._request_for(task, store), budget)
            binding = getattr(provider, 'recovery_binding', {'provider_id': getattr(provider, 'provider_id', 'unspecified')})
            arguments = {'attempt_id': attempt_id, 'request': request.to_dict(), 'request_key': request_key(request),
                         'provider_binding': binding}
            task = guarded(store, task, begin_task_tool, request_id=provider_id, tool='llm.complete', arguments=arguments)['task']
            call = _call(task, provider_id)
        request = CompletionRequest(**call['arguments']['request'])
        if call['state'] == 'recorded':
            response = _response(call['output']['response'])
            accounting.settle(store, attempt_id, response)
        elif call['state'] == 'reserved':
            binding = getattr(provider, 'recovery_binding', {'provider_id': getattr(provider, 'provider_id', 'unspecified')})
            if _canonical(binding) != _canonical(call['arguments']['provider_binding']):
                raise R.BureauRefusal('provider_binding_changed', 'resume must use the original response channel')
            invoke = accounting.reserve(store, budget, request.max_tokens, attempt_id=attempt_id,
                expected_task_versions={task_id: task['version']})
            charged = int(invoke)
            try:
                response = provider.complete(request) if invoke else getattr(provider, 'lookup', lambda _request: None)(request)
            except Exception as error:
                response = getattr(error, 'response', None)
                if response is None:
                    accounting.settle(store, attempt_id)
                    raise R.BureauRefusal('provider_outcome_unresolved',
                        'lookup an existing response later; reservation is not permission to resend') from error
            if response is None:
                accounting.settle(store, attempt_id)
                raise R.BureauRefusal('provider_outcome_unresolved', 'no retained response; no provider reinvocation')
            response = _response(response.to_dict())
            try:
                task = _finish(store, task, provider_id, {'response': response.to_dict()})
            finally:
                # A superseded generation cannot submit, but its observed spend
                # did occur and must not remain clipped to a reserve.
                accounting.settle(store, attempt_id, response)
        else:
            raise R.BureauRefusal('provider_attempt_unresolved', 'old attempt was superseded or abandoned; no reinvocation')
        if response.tokens > request.max_tokens:
            raise R.BureauRefusal('token_budget_overrun', 'full usage retained; oversized response is not applied', calls=1, tokens=response.tokens)
        task = R._configured_task(store, read_task(store, task_id))
        if task['generation'] != generation:
            raise R.BureauRefusal('generation_changed', 'response belongs to an older assignment')
        # 🔴 A REQUEST TO READ THE PROJECT IS A SEPARATE BUREAU STEP, NOT A
        # PROGRAM. It is checked BEFORE reserving the sandbox: running
        # Python on the request would mean spending a tool slot and naming
        # the refusal `answer_is_not_a_program` in a place where the model
        # never promised anything. The provider call is already recorded,
        # so it cannot be asked again; the bureau answers with data, and
        # the data rides into the NEXT context.
        asked = R.read_request(response.text)
        if asked is not None:
            served = R.serve_read(store, task, asked)
            return R.WorkResult(task_id, None, {'code': 'read_requested', 'read': served},
                                charged, response.tokens, None, answer_sha256_of(response),
                                response.provider_id, response.usage_basis, resumed)
        call = _call(task, sandbox_id)
        if call is None:
            from kir.task_recipe_runner import RECIPE_POLICY
            arguments = {'provider_request_id': provider_id, 'source_sha256': hashlib.sha256(response.text.encode()).hexdigest(),
                         'base_revision': task['assignment']['base_revision'], 'policy': asdict(RECIPE_POLICY)}
            reserved = guarded(store, task, begin_task_tool, request_id=sandbox_id, tool='author.python', arguments=arguments)
            task = R._configured_task(store, reserved['task'])
            call = _call(task, sandbox_id)
            if reserved['inserted']:
                from kir.sandbox import execute_author_script
                evaluated = execute_author_script(response.text, policy=RECIPE_POLICY)
                output = {'sandbox': evaluated.as_dict(), 'program': evaluated.to_program() if evaluated.ok else None,
                          'proposal': None, 'refusal': None}
                if evaluated.ok:
                    try:
                        proposal = _candidate(store, task, response, evaluated)
                        output['proposal'] = proposal.to_dict()
                    except (TaskError, ValueError, TypeError, KeyError, KirRefusal) as error:
                        output['refusal'] = {'code': getattr(error, 'code', 'candidate_refused'), 'detail': type(error).__name__}
                else:
                    # The sandbox refusal's name rides alongside: "not a
                    # program" because of a limit (cpu/wall under load) and
                    # because of prose are different causes, and the receipt
                    # reader must tell them apart without digging into
                    # `sandbox`.
                    output['refusal'] = {'code': 'answer_is_not_a_program',
                                         'sandbox': getattr(evaluated.refusal, 'code', None),
                                         'sandbox_kind': getattr(evaluated.refusal, 'kind', None)}
                if len(_canonical(output).encode()) > MAX_EVENT_BYTES - 8192:
                    output = {'sandbox': None, 'program': None, 'proposal': None,
                              'refusal': {'code': 'sandbox_retention_budget_exceeded'}}
                task = _finish(store, task, sandbox_id, output)
                call = _call(task, sandbox_id)
        if call['state'] != 'recorded':
            raise R.BureauRefusal('sandbox_outcome_unresolved', 'sandbox reservation is not permission to run Python again')
        output = call['output']
        answer_sha = hashlib.sha256(response.text.encode()).hexdigest()
        author_digest = (output.get('sandbox') or {}).get('author_digest')
        # 🔴 GENERATION IS JUDGED BEFORE CONTENT (08.09.2026). A held
        # sandbox output belongs to the ASSIGNMENT; if the assignment was
        # reissued, its content is not judged at all — neither the proposal
        # nor the refusal. Previously a refusal (`answer_is_not_a_program`,
        # including from a sandbox that didn't make its own limit under
        # swap pressure) was returned BEFORE the generation check, and the
        # same scenario produced two different codes depending on load — a
        # flake in strip G2 on 07.09.2026, reproduced deterministically by
        # the test
        # `test_a_reassigned_task_refuses_by_generation_even_when_the_sandbox_output_is_not_a_program`.
        task = R._configured_task(store, read_task(store, task_id))
        if task['generation'] != generation:
            raise R.BureauRefusal('generation_changed', 'retained sandbox output belongs to an older assignment')
        if output['proposal'] is None:
            return R.WorkResult(task_id, None, output['refusal'], charged, response.tokens, author_digest, answer_sha,
                               response.provider_id, response.usage_basis, resumed)
        proposal = ChangeProposal.from_dict(output['proposal'])
        guarded(store, task, submit_task, request_id=f'bureau-submit-{generation}', proposal=proposal, source_tool=sandbox_id)
        return R.WorkResult(task_id, proposal.proposal_id, None, charged, response.tokens, author_digest, answer_sha,
                           response.provider_id, response.usage_basis, resumed)
    except (TaskError, StoreConflict) as error:
        fallback = 'task_version_changed' if isinstance(error, StoreConflict) else 'task_transition_refused'
        return R.WorkResult(task_id, None, {'code': getattr(error, 'code', fallback), 'detail': str(error)},
            charged, response.tokens if response is not None else 0,
            provider_id=response.provider_id if response is not None else None,
            usage_basis=response.usage_basis if response is not None else 'unknown', replayed=resumed)
