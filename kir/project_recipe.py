"""Associate an observed author-script result with one sealed instance proposal.

No script/kernel/compiler/Store execution occurs here. SandboxResult is mutable
and publicly constructible: this matches supplied values, not authenticates a
run. The trusted tool runner owns calling execute_author_script exactly once.
Full evaluated IR survives even when this narrow Project projection refuses.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import hashlib
import json

from kir.project import (ModuleDefinition, NamedOutput, ProjectError, ProjectRevision, RecipePin,
                         _canonical, _digest, _hash, _key, _object, _thaw, output_id)
from kir.project_merge import ChangeProposal, ProposalScope
from kir.sandbox import SandboxResult, SandboxResultContradiction, params_digest


EVALUATION_SCHEMA = "kir-project-recipe-evaluation/1"
EVALUATION_REF_SCHEMA = "kir-project-recipe-evaluation-ref/1"
RECIPE_LANGUAGE = "kir.recipe_language"


class RecipeBindingError(ProjectError):
    """Malformed inputs cannot form an inert JSON evaluation record."""


@dataclass(frozen=True, slots=True)
class RecipeProjectionRefusal:
    code: str
    message: str

    def to_dict(self):
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class RecipeBindingResult:
    _evaluation_json: str = field(repr=False)
    proposal: ChangeProposal | None
    projection_refusal: RecipeProjectionRefusal | None

    @property
    def evaluation(self) -> dict:
        return json.loads(self._evaluation_json)

    def to_dict(self) -> dict:
        return {"evaluation": self.evaluation,
                "proposal": self.proposal.to_dict() if self.proposal is not None else None,
                "projection_refusal": self.projection_refusal.to_dict() if self.projection_refusal is not None else None}


def bind_recipe_result(base, *, instance_key, module_key, source, parameters,
                       output_bindings, result, author, reason) -> RecipeBindingResult:
    """Build one inert ChangeProposal, without discarding unsupported IR fields.

    ``parameters`` is EXACTLY the input sent to the sandbox, including scalar
    project_id/instance_key. ``output_bindings`` maps every desired output key
    to its canonical Project ID. Script order wins; the mapping is not an order.
    IDs/refs are not remapped: only the redundant top-level operation id is
    removed when making NamedOutput, whose Project projection reinstates it.

    Only {ir_version, intent, ops}, with intent matching base, is projectable in
    this first profile. Defaults, phases, units and unknown envelope fields are
    retained in evaluation.program but receive a named projection refusal.
    A returned proposal is not compiler/native/engineering acceptance or grant.
    """
    if (type(base) is not ProjectRevision or type(result) is not SandboxResult
            or type(result.ok) is not bool or type(source) is not str or not source.strip()
            or not isinstance(parameters, Mapping) or not isinstance(output_bindings, Mapping)):
        raise RecipeBindingError("expected exact base/result, source text and JSON input/output mappings")
    try:
        _key(instance_key, "instance_key")
        _key(module_key, "module_key")
        inputs = _thaw(_object(parameters, "recipe.parameters"))
        declared = _thaw(_object(output_bindings, "recipe.output_bindings"))
        source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
        receipt = result.as_dict()
        observed_ok = receipt["ok"]
        if type(observed_ok) is not bool:
            raise ValueError("invalid result flag")
        program = result.to_program() if observed_ok else None
        if observed_ok and _canonical({**receipt.get("envelope", {}), "ops": receipt["ops"]}) != _canonical(program):
            raise ValueError("mutable result changed while binding")
        # The full program lives ONCE. The remaining receipt still keeps stdout,
        # declared/resolved params, lineage, isolation, environment and refusals.
        receipt.pop("ops", None)
        receipt.pop("envelope", None)
        evaluation = {"schema": EVALUATION_SCHEMA, "base_revision": base.revision_id,
            "project_id": base.project_id, "instance_key": instance_key, "module_key": module_key,
            "source": source, "source_sha256": source_sha, "parameters": inputs,
            "parameters_digest": params_digest(inputs), "output_bindings": declared,
            "program": program, "program_sha256": _hash(program) if program is not None else None,
            "sandbox_receipt": receipt,
            "claims": {"association": "supplied_sandbox_result_not_authenticated_execution",
                "dependency_coverage": "sandbox_reported_environment_not_complete_import_closure",
                "compiler_validation": "not_run", "native_execution": "not_run",
                "proposal_acceptance": "not_run", "binding_replay": "not_run"}}
        evaluation["evaluation_digest"] = _hash(evaluation)
        encoded = _canonical(evaluation)
    except (ProjectError, SandboxResultContradiction, ValueError, TypeError, UnicodeError) as error:
        raise RecipeBindingError("recipe inputs/result cannot form a consistent JSON evaluation") from error

    def refused(code, message):
        return RecipeBindingResult(encoded, None, RecipeProjectionRefusal(code, message))

    if not observed_ok:
        return refused("recipe_execution_refused", "Sandbox reported a refusal; its full receipt is retained.")
    if receipt["author_digest"] != source_sha:
        return refused("recipe_source_mismatch", "Supplied source differs from the observed author digest.")
    if receipt.get("params_digest", "") != evaluation["parameters_digest"]:
        return refused("recipe_parameters_mismatch", "Supplied parameters differ from the observed input digest.")
    if inputs.get("project_id") != base.project_id or inputs.get("instance_key") != instance_key:
        return refused("recipe_namespace_mismatch", "project_id/instance_key input parameters must name this exact instance.")
    isolation = receipt.get("isolation")
    if type(isolation) is not dict or isolation.get("dsl_module") != RECIPE_LANGUAGE:
        return refused("recipe_language_mismatch", "Trusted runner must explicitly select kir.recipe_language.")
    if receipt.get("model_digest") or receipt.get("building_digest"):
        return refused("recipe_context_unsupported", "This first binding profile has no external model/building input payloads.")
    environment = receipt.get("environment")
    try:
        if (type(environment) is not dict or "error" in environment
                or any(type(environment.get(key)) is not str or not environment[key]
                       for key in ("python", "python_build", "implementation"))
                or type(environment.get("modules")) is not list):
            raise ValueError("environment structure differs")
        env_digest = environment.get("digest")
        _digest(env_digest, "environment.digest")
        _digest(receipt.get("program_digest"), "program_digest")
        if _hash({key: value for key, value in environment.items() if key != "digest"}) != env_digest:
            raise ValueError("environment differs")
    except (ProjectError, ValueError, TypeError):
        return refused("recipe_environment_unavailable", "A consistent observed environment/program digest is required.")
    if isolation.get("environment_replay") == "CHANGED":
        return refused("recipe_environment_changed", "Sandbox observed environment drift during replay.")
    if receipt.get("left_behind"):
        return refused("recipe_left_behind_programs", "Sandbox reported discarded programs; the loss report is retained.")
    if set(program) != {"ir_version", "intent", "ops"}:
        return refused("recipe_envelope_unsupported", "Only explicit ir_version/intent/ops can project to one instance; full IR is retained.")
    if program["ir_version"] != base.ir_version or program["intent"] != base.intent:
        return refused("recipe_envelope_mismatch", "Recipe cannot silently change the containing project's IR version or intent.")
    previous = next((item for item in base.instances if item.key == instance_key), None)
    if previous is None:
        return refused("recipe_instance_missing", "The first profile replaces one existing complete instance.")
    try:
        if not declared:
            raise ValueError("empty binding map")
        for key, oid in declared.items():
            _key(key, "output_key")
            if oid != output_id(base.project_id, instance_key, key):
                raise ValueError("noncanonical output id")
        by_id = {oid: key for key, oid in declared.items()}
        operations = program["ops"]
        if (len(by_id) != len(declared) or type(operations) is not list or len(operations) != len(by_id)
                or any(type(op) is not dict or type(op.get("id")) is not str for op in operations)
                or len({op["id"] for op in operations}) != len(operations)
                or {op["id"] for op in operations} != set(by_id)):
            raise ValueError("incomplete output mapping")
        outputs = tuple(NamedOutput(by_id[op["id"]], {key: value for key, value in op.items() if key != "id"})
                        for op in operations)
    except (ProjectError, TypeError, ValueError):
        return refused("recipe_output_bindings_mismatch", "Every emitted output must map exactly once to its canonical named Project address.")
    pin = RecipePin(source, env_digest, entrypoint="script")
    definition = ModuleDefinition(module_key, "sealed_evaluation", pin)
    existing = next((module for module in base.modules if module.key == module_key), None)
    changed_definition = existing is None or existing.definition_digest != definition.definition_digest
    if changed_definition and any(item.key != instance_key and item.module_key == module_key for item in base.instances):
        return refused("recipe_shared_module_change", "Changed source/environment requires a dedicated module; other instances keep their pins.")
    metadata = _thaw(previous.metadata)
    if "recipe_evaluation" in metadata:
        old = metadata["recipe_evaluation"]
        try:
            if type(old) is not dict or set(old) != {"schema", "evaluation_digest"} or old["schema"] != EVALUATION_REF_SCHEMA:
                raise ValueError("occupied metadata slot")
            _digest(old["evaluation_digest"], "evaluation_digest")
        except (ProjectError, ValueError, TypeError):
            return refused("recipe_metadata_occupied", "An unrelated recipe_evaluation declaration is not overwritten.")
    metadata["recipe_evaluation"] = {"schema": EVALUATION_REF_SCHEMA, "evaluation_digest": evaluation["evaluation_digest"]}
    replacement = replace(previous, module_key=module_key, module_digest=definition.definition_digest,
                          outputs=outputs, parameters=inputs, metadata=metadata)
    modules = tuple(definition if module.key == module_key else module for module in base.modules)
    if existing is None:
        modules += (definition,)
    candidate = base.revise(expected_revision=base.revision_id, modules=modules,
        instances=tuple(replacement if item.key == instance_key else item for item in base.instances))
    scope = ProposalScope(instances=(instance_key,), modules=(module_key,) if changed_definition else (),
                          project_fields=("module_order",) if existing is None else ())
    proposal = ChangeProposal(base, candidate, scope, author, reason)
    return RecipeBindingResult(encoded, proposal, None)


__all__ = ["EVALUATION_SCHEMA", "EVALUATION_REF_SCHEMA", "RECIPE_LANGUAGE", "RecipeBindingError",
           "RecipeProjectionRefusal", "RecipeBindingResult", "bind_recipe_result"]
