"""One explicit sandbox recipe step with durable reservation and retained result.

Not an LLM scheduler. The trusted host chooses the SandboxPolicy and separates
this adapter from coordinator authority. Retrying an existing reservation never
invokes Python again, including when its execution outcome is unresolved.
"""
from collections.abc import Mapping
from dataclasses import asdict, replace
import json

from kir.project import _canonical, _hash, _key, _object, _thaw, output_id
from kir.project_merge import ChangeProposal, ProposalScope
from kir.project_tasks import (TaskError, begin_task_tool, finish_task_tool, read_task,
                               submit_task, tool_result_request_id, MAX_EVENT_BYTES, MAX_EVENTS)
from kir.project_store import StoreConflict
from kir.sandbox import DEFAULT_POLICY, SandboxPolicy, execute_author_script


RECIPE_POLICY = replace(DEFAULT_POLICY, dsl_module="kir.recipe_language")
TOOL_NAME = "author.python"
RECIPE_PLAN_SCHEMA = "kir-task-recipe-plan/1"
PLAN_STEP_SCHEMA = "kir-task-recipe-plan-step/1"
PLAN_RUN_SCHEMA = "kir-task-recipe-plan-run/1"
#: How many PERMITTED retries a single step has. Each retry is a NEW hold
#: with a NEW request_id, and it is taken only after the previous hold has
#: already been named unresolved by an explicit event
#: (`tool_abandon`/`reassign`/`revoke`).
#: AN UNRESOLVED hold NEVER grants the right to call Python again — this is
#: the pin `test_pending_resume_after_hard_process_exit_never_invokes_again`.
MAX_PLAN_ATTEMPTS = 8
_STEP_FIELDS = frozenset({"instance_key", "module_key", "output_keys", "source", "parameters", "reason"})
_STEP_REQUIRED = frozenset({"instance_key", "module_key", "output_keys", "source"})


def _require(condition, message):
    if not condition:
        raise TaskError(message)


def _call(task, request_id):
    return next(call for call in task["tool_calls"] if call["request_id"] == request_id)


def evaluate_task_recipe(store, task_id, *, source, instance_key, module_key, output_keys,
                         request_id, expected_version, generation, actor, parameters=None,
                         reason="Explicit recipe evaluation", policy=RECIPE_POLICY, pins=None):
    """Evaluate once, retain full program/evidence and optional authored proposal.

    A source/refusal/result is not a native effect or a design acceptance. This
    function never submits its proposal or advances authored head automatically.
    """
    _key(instance_key, "instance_key")
    _key(module_key, "module_key")
    _require(type(source) is str and bool(source.strip()), "recipe source must be nonempty text")
    source.encode("utf-8", errors="strict")
    _require(type(policy) is SandboxPolicy, "trusted host must supply an exact SandboxPolicy")
    policy = SandboxPolicy(**asdict(policy))  # Revalidate even a mutated frozen instance.
    _require(policy.dsl_module == "kir.recipe_language", "recipe tool requires its explicit language profile")
    _require(type(output_keys) in (tuple, list) and bool(output_keys), "explicit ordered output keys required")
    for key in output_keys:
        _key(key, "output_key")
    _require(len(output_keys) == len(set(output_keys)), "duplicate output key")
    _require(type(reason) is str and bool(reason.strip()), "proposal reason required")
    task = read_task(store, task_id)
    _require(instance_key in task["assignment"]["scope"]["instances"], "target instance is outside assigned grant")
    params = _thaw(_object({} if parameters is None else parameters, "parameters"))
    for key, value in (("project_id", task["project_id"]), ("instance_key", instance_key)):
        _require(key not in params or params[key] == value, "recipe address parameter differs from assigned target")
        params[key] = value
    bindings = {key: output_id(task["project_id"], instance_key, key) for key in output_keys}
    arguments = {"source": source, "parameters": params, "instance_key": instance_key,
        "module_key": module_key, "output_bindings": bindings, "reason": reason,
        "policy": json.loads(_canonical(asdict(policy)))}
    if pins is not None:
        # 🔴 PINS ARE NOT PART OF THE SANDBOX CONTRACT. The recipe language
        # refuses on an UNDECLARED parameter (`KIR-B014`), and mixing
        # seed/chain into the inputs would break EVERY existing recipe. So
        # the pins ride in the durable `arguments`, and only the names the
        # step ITSELF DECLARED reach the script. A redelivery checks those
        # too: a different seed is a different input, "request ID reused
        # for different input."
        arguments["pins"] = _thaw(_object(pins, "recipe.pins"))
    from kir.project_recipe import bind_recipe_result
    reserved = begin_task_tool(store, task_id, request_id=request_id, expected_version=expected_version,
        generation=generation, actor=actor, tool=TOOL_NAME, arguments=arguments)
    if not reserved["inserted"]:
        return {"schema": "kir-task-recipe-step/1", "invoked": False,
                "task": reserved["task"], "call": _call(reserved["task"], request_id)}
    # No SQLite transaction is held across execution. A crash here leaves a
    # charged reservation, NOT permission to invoke again on resume.
    invoked = False
    try:
        base = store.get(task["assignment"]["base_revision"])
        invoked = True
        result = execute_author_script(source, policy=policy, params=params)
        bound = bind_recipe_result(base, instance_key=instance_key, module_key=module_key,
            source=source, parameters=params, output_bindings=bindings, result=result,
            author=actor, reason=reason)
        output = bound.to_dict()
        if output["proposal"] is not None:
            proposal = ChangeProposal.from_dict(output["proposal"])
            if not ProposalScope.from_dict(task["assignment"]["scope"]).covers(proposal.scope):
                output["proposal"] = None
                output["projection_refusal"] = {"code": "assigned_grant_insufficient",
                    "message": "Evaluated program retained; generated module/instance changes exceed the task grant."}
        # Reserve room for the task event envelope as well as the result.
        if len(_canonical(output).encode("utf-8")) > MAX_EVENT_BYTES - 8192:
            output = {"evaluation": None, "proposal": None, "projection_refusal": {
                "code": "result_exceeds_task_event_budget", "message": "Python completed; its result was not retained within the event budget."}}
    except Exception as error:
        output = {"evaluation": None, "proposal": None, "projection_refusal": {
            "code": "recipe_adapter_failed", "message": type(error).__name__}}
    current = read_task(store, task_id)
    if current["generation"] != generation or current["pending_tool"] != request_id:
        return {"schema": "kir-task-recipe-step/1", "invoked": invoked, "recorded": False,
                "task": current, "call": _call(current, request_id), "unrecorded_output": output}
    try:
        finished = finish_task_tool(store, task_id, request_id=tool_result_request_id(request_id),
            expected_version=current["version"], generation=generation, actor=actor,
            tool_request_id=request_id, output=output)
    except StoreConflict:
        current = read_task(store, task_id)
        return {"schema": "kir-task-recipe-step/1", "invoked": invoked, "recorded": False,
                "task": current, "call": _call(current, request_id), "unrecorded_output": output}
    return {"schema": "kir-task-recipe-step/1", "invoked": invoked, "recorded": True,
            "task": finished["task"], "call": _call(finished["task"], request_id)}


def submit_evaluated_recipe(store, task_id, *, tool_request_id, request_id,
                            expected_version, generation, actor):
    """Submit the exact retained derived proposal, never regenerate it."""
    task = read_task(store, task_id)
    call = next((c for c in task["tool_calls"] if c["request_id"] == tool_request_id), None)
    _require(call is not None and call["tool"] == TOOL_NAME and call["state"] == "recorded"
             and call["output"].get("proposal") is not None, "no retained projected recipe proposal")
    return submit_task(store, task_id, ChangeProposal.from_dict(call["output"]["proposal"]),
        request_id=request_id, expected_version=expected_version, generation=generation,
        actor=actor, source_tool=tool_request_id)


def recipe_plan(steps, *, seed, plan_id="plan"):
    """One ORDERING of steps, whose identity pins down the seed, the inputs,
    and the chain.

    An inert JSON is returned: no step is executed here. `plan_digest` is
    computed over ALL the steps, so a changed order/source/parameter is a
    DIFFERENT plan with different step addresses, not "the same plan,
    continued."
    """
    _key(plan_id, "plan_id")
    _require(type(seed) is str and bool(seed.strip()) and len(seed) <= 256,
             "recipe plan requires one explicit bounded seed")
    _require(type(steps) in (tuple, list) and 1 <= len(steps) <= 200,
             "recipe plan requires 1..200 ordered steps")
    prepared = []
    for index, step in enumerate(steps):
        _require(isinstance(step, Mapping) and not (set(step) - _STEP_FIELDS)
                 and _STEP_REQUIRED <= set(step),
                 "each plan step names instance_key/module_key/output_keys/source")
        _key(step["instance_key"], "instance_key")
        _key(step["module_key"], "module_key")
        keys = step["output_keys"]
        _require(type(keys) in (tuple, list) and bool(keys), "explicit ordered output keys required")
        for key in keys:
            _key(key, "output_key")
        _require(len(set(keys)) == len(keys), "duplicate output key")
        source = step["source"]
        _require(type(source) is str and bool(source.strip()), "recipe source must be nonempty text")
        reason = step.get("reason") or "Explicit recipe plan step"
        _require(type(reason) is str and bool(reason.strip()), "proposal reason required")
        prepared.append({"schema": PLAN_STEP_SCHEMA, "index": index,
            "instance_key": step["instance_key"], "module_key": step["module_key"],
            "output_keys": list(keys), "source": source, "reason": reason,
            "parameters": _thaw(_object(step.get("parameters") or {}, "step parameters"))})
    plan = {"schema": RECIPE_PLAN_SCHEMA, "plan_id": plan_id, "seed": seed, "steps": prepared}
    plan["plan_digest"] = _hash(plan)
    return json.loads(_canonical(plan))


def _step_request_id(plan, index, attempt):
    return f"{plan['plan_id']}-s{index}-a{attempt}-{plan['plan_digest'][:12]}"


def _step_outcome(step, output):
    """What the step ANSWERS the next one with. No attempt number and no process."""
    evaluation = output.get("evaluation")
    refusal = output.get("projection_refusal")
    proposal = output.get("proposal")
    return {"index": step["index"], "instance_key": step["instance_key"],
            "step_digest": _hash(step),
            "evaluation_digest": None if evaluation is None else evaluation["evaluation_digest"],
            "program_sha256": None if evaluation is None else evaluation["program_sha256"],
            "proposal_id": None if proposal is None else proposal["proposal_id"],
            "refusal": None if refusal is None else refusal["code"]}


_CONTENT_FIELDS = ("index", "instance_key", "step_digest", "program_sha256", "refusal")


def _step_content(outcome):
    """What the step COMPUTED, without this execution's receipt.

    🔴 THE CHAIN OF STEPS MUST HANG ON CONTENT, NOT ON DURATION.
    `evaluation_digest` carries the full sandbox receipt, including
    `duration_s` and `peak_rss_kb`; had I hung `depends_on` on it, I would
    have made the next step's input depend on HOW MANY MILLISECONDS the
    previous one took — and then no interrupted run would ever match an
    uninterrupted one. The measurement showed exactly that.
    """
    return {key: outcome[key] for key in _CONTENT_FIELDS}


def evaluate_task_recipe_plan(store, task_id, *, plan, actor, generation, policy=RECIPE_POLICY,
                              max_steps=None, task=None):
    """Continue the plan from the SAVED step; do not recompute what is
    already done.

    🔴 WHAT HOLDS THE TRUTH HERE IS THE TASK JOURNAL, NOT THIS PROCESS'S
    MEMORY. A Stop, a process dying mid-step, and an exhausted budget all
    leave the SAME durable state: finished steps are recorded by
    `tool_begin`/`tool_finish` events, an unfinished one by a hold. A
    different process reads these events and continues from the first step
    the journal does not hold; `result["result_digest"]` is THE SAME for an
    interrupted and an uninterrupted run, because it does not include the
    attempt number, the actor's name, or the order of the processes.

    The seed, the inputs, and the dependency on the previous step ride IN
    THE STEP ITSELF: they live in the hold's `parameters`
    (`recipe_seed`/`plan_digest`/`step_index`/`depends_on`), i.e. in
    `tool_begin.arguments`. A redelivery of the same step is checked against
    those bytes: a different seed or a different chain is a different input,
    and `_mutate` will refuse with "request ID reused for different input"
    rather than silently swap out what was done.

    An unresolved hold (the process died mid-step) does NOT resume by
    itself: Python's outcome is unknown, and calling it again is not
    allowed. `stopped="step_outcome_unresolved"` is returned; the next
    attempt at the same step is taken only after an EXPLICIT
    `abandon_task_tool`/`reassign_task`.
    """
    _require(isinstance(plan, Mapping) and plan.get("schema") == RECIPE_PLAN_SCHEMA
             and type(plan.get("plan_digest")) is str
             and _hash({k: v for k, v in plan.items() if k != "plan_digest"}) == plan["plan_digest"],
             "expected an exact recipe_plan() value")
    _require(max_steps is None or (type(max_steps) is int and max_steps >= 0),
             "max_steps must be a nonnegative integer run budget")
    current = read_task(store, task_id) if task is None else task
    _require(isinstance(current, Mapping) and current.get("task_id") == task_id, "expected this task's snapshot")
    outcomes, delivery, stopped, invoked, attempted = [], [], None, 0, 0
    depends_on = ""
    # 🔴 CAPACITY IS CHECKED BEFORE THE FIRST STEP, NOT PARTWAY THROUGH THE
    # PLAN. The task journal is bounded by `MAX_EVENTS`, and each step costs
    # TWO events (`tool_begin` + `tool_finish`), plus `_mutate` keeps a
    # terminal reserve of 3. A plan that is known in advance not to fit must
    # be NAMED as a refusal, not silently truncated partway through: a
    # truncated plan would leave half its effect unnamed.
    finished = {call["request_id"] for call in current["tool_calls"] if call["state"] == "recorded"}
    pending = sum(1 for step in plan["steps"] if not any(
        _step_request_id(plan, step["index"], attempt) in finished
        for attempt in range(1, MAX_PLAN_ATTEMPTS + 1)))
    limit = current["assignment"]["budgets"].get("max_tool_calls")
    if current["sequence"] + 1 + 2 * pending > MAX_EVENTS - 3:
        stopped = "plan_exceeds_task_journal"
    elif type(limit) is not int or len(current["tool_calls"]) + pending > limit:
        stopped = "plan_exceeds_tool_call_budget"
    steps = () if stopped is not None else plan["steps"]
    for step in steps:
        calls = {call["request_id"]: call for call in current["tool_calls"]}
        attempt, recorded = 1, None
        while True:
            found = calls.get(_step_request_id(plan, step["index"], attempt))
            if found is None:
                break
            if found["state"] == "recorded":
                recorded = found
                break
            if found["state"] == "reserved":
                stopped = "step_outcome_unresolved"
                break
            attempt += 1
            if attempt > MAX_PLAN_ATTEMPTS:
                stopped = "step_attempts_exhausted"
                break
        if stopped is not None:
            break
        if recorded is not None:
            outcome = _step_outcome(step, recorded["output"])
            delivery.append({"index": step["index"], "attempt": attempt, "delivered": "already_delivered"})
        else:
            # The run's budget counts DELIVERIES, not Python invocations: a
            # retry of someone else's step is also this process's work, and
            # it must stop at the same boundary as a first one.
            if max_steps is not None and attempted >= max_steps:
                stopped = "run_step_budget_exhausted"
                break
            live = current["assignment"]["budgets"].get("max_tool_calls")
            if type(live) is not int or len(current["tool_calls"]) + 1 > live:
                stopped = "tool_call_budget_exhausted"
                break
            attempted += 1
            pins = {"recipe_seed": plan["seed"], "plan_digest": plan["plan_digest"],
                    "step_index": step["index"], "depends_on": depends_on}
            evaluated = evaluate_task_recipe(store, task_id, source=step["source"],
                instance_key=step["instance_key"], module_key=step["module_key"],
                output_keys=tuple(step["output_keys"]),
                request_id=_step_request_id(plan, step["index"], attempt),
                expected_version=current["version"], generation=generation, actor=actor,
                parameters={**step["parameters"],
                            **{k: v for k, v in pins.items() if k in step["parameters"]}},
                reason=step["reason"], policy=policy, pins=pins)
            current = evaluated["task"]
            call = evaluated["call"]
            if call["state"] != "recorded":
                # 🔴 "SOMEONE ELSE TOOK THE STEP" AND "THE OUTCOME IS
                # UNKNOWN" ARE DIFFERENT FACTS. While this process was
                # computing, the coordinator could have released the hold
                # (`tool_abandon`) or changed the owner (`reassign`), and
                # then recording the result is refused BY NAME, not lost.
                stopped = ("step_taken_by_another_attempt"
                           if call["state"] in ("abandoned_unresolved", "superseded_unresolved")
                           else "step_outcome_unresolved" if evaluated["invoked"]
                           else "step_not_delivered")
                break
            invoked += 1 if evaluated["invoked"] else 0
            delivery.append({"index": step["index"], "attempt": attempt,
                             "delivered": "evaluated" if evaluated["invoked"] else "already_delivered_on_replay"})
            outcome = _step_outcome(step, call["output"])
        outcomes.append(outcome)
        depends_on = _hash(_step_content(outcome))
    # 🔴 TWO SIGNATURES, AND THEY SPEAK OF DIFFERENT THINGS (found by
    # measurement on 07.09.2026).
    # `evaluation_digest` and `proposal_id` carry the FULL sandbox receipt,
    # and it contains `duration_s` and `peak_rss_kb`: two independent
    # EXECUTIONS of the same source give different bytes. Therefore:
    #   `result_digest`  — the JOURNAL's identity: the same for any number of
    #                      processes reading the same recorded steps;
    #   `content_digest` — the CONTENT's identity (what exactly was
    #                      computed): equal for both an interrupted and an
    #                      uninterrupted run, even if the steps were computed
    #                      in different processes at different times.
    # Declaring one signature "byte-identical" while silently folding
    # duration into it would be an instrument's lie.
    result = {"schema": RECIPE_PLAN_SCHEMA, "plan_digest": plan["plan_digest"], "seed": plan["seed"],
              "planned": len(plan["steps"]), "completed": len(outcomes), "steps": outcomes}
    result["content_digest"] = _hash({**result, "steps": [_step_content(o) for o in outcomes]})
    result["result_digest"] = _hash(result)
    return {"schema": PLAN_RUN_SCHEMA, "result": json.loads(_canonical(result)), "delivery": delivery,
            "invoked": invoked, "attempted": attempted, "stopped": stopped, "task": current,
            "complete": stopped is None and len(outcomes) == len(plan["steps"])}
