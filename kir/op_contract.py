"""Canonical, content-addressed contract for one KIR operation.

The registry, grounder and translation certificate historically described
different faces of the same operation.  This module does not introduce a
second registry.  It projects those existing authorities into one immutable
artifact whose digest can be bound by the compiler plan.

Changing an operand, grounding rule, result identity, tolerance or refinement
obligation must therefore change the operation contract digest even when the
authored payload is byte-identical.

🔴 THIS PROMISE DID NOT HOLD FOR FIVE FIELDS (2026-08-26, mutation experiment).
`authority`, `omission_transfers`, `caveat`, `result_by_param` and
`grounded_pool_by_param` were not part of the signature: the meaning changed,
the digest did not. The defect was in the EVIDENCE, not in the ENFORCEMENT —
the compiler still rejected the wrong kind of reference — but "the contract
is the same" was said about a different contract. As of this edit the
coverage list is declared as a list, and the `_lint_contract_coverage`
instrument keeps the list matching the registry and the serializer, failing
the module on import. A registry field can no longer fall out of the
signature silently.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from kir import spec
from kir.registry_base import OpSpec, ParamSpec, ResultSpec


#: 🔴 BUMPED FROM `/1` TO `/2` (2026-08-26). What is bumped is the document's
#: FORM, not its content: keys appeared in the signature that no op had had
#: before — `caveat`, `result_by_param`, `grounded_pool_by_param` on the
#: operation, and `authority`, `omission_transfers` on the parameter. A
#: reader parsing `/1` will meet unfamiliar keys, and the version must say so.
OP_CONTRACT_SCHEMA = "kir-op-contract/2"


# ═══════════════════════════════════════════════════════════════════════
# WHAT IS PART OF THE MEANING. ONE AUTHORITY, AND COVERAGE IS CHECKED BY TRAVERSAL.
# ═══════════════════════════════════════════════════════════════════════
#
# 🔴 WHAT THIS COST, 2026-08-26, A MUTATION EXPERIMENT. One registry field
# was swapped and the signature was taken before and after:
#
#     create_beam.level.authority   DERIVED_BY_REVIT -> AUTHORED
#     contract digest:              UNCHANGED
#
# A sweep over every carrier of meaning gave FIVE BLIND OUT OF FIVE:
# `authority`, `omission_transfers`, `caveat`, `result_by_param`,
# `grounded_pool_by_param`. And `caveat` was edited THAT SAME DAY (`e2bf5adc`)
# — the edit left no trace.
#
# 🔴 THIS IS A DEFECT OF EVIDENCE, NOT OF ENFORCEMENT. The enforcement path is
# intact and verified: the wrong kind of reference will not build a wall,
# `accepts_reference` rejects it at compile time. What is broken is exactly
# provability: the contract became DIFFERENT and the signature said "the
# same." The module promised the opposite in the first line of its docstring
# and did not keep the promise.
#
# WHY A LIST, NOT SIMPLY A FIXED `_param_row`. A hand-written enumeration of
# fields INSIDE the function is a second carrier of the notion "what is part
# of the meaning," and it drifted apart from `ParamSpec` on the very first
# new field. This is exactly how the present defect was born: the
# `authority` and `omission_transfers` fields were added to the registry on
# 08-19, and no one added them here, and nothing forced anyone to.
#
# Hence there are TWO declarations here and an INSTRUMENT between them:
# coverage is derived by traversing `dataclasses.fields`, and a field that
# lands in neither the signature nor the exceptions FAILS THE MODULE ON
# IMPORT. The idiom is borrowed from `read_bodies.py`, where it was set up
# for the same reason and at the same cost.

#: `ParamSpec` fields that are part of the signature. The order here carries
#: no weight (JSON is canonicalized by sorting keys), but is kept readable.
PARAM_SIGNED_FIELDS: tuple[str, ...] = (
    "name", "kind", "required", "default", "min_val", "max_val",
    "choices", "ref_kinds", "exact_string",
    # ↓ THESE TWO WERE MISSING AND CONSTITUTED THE DEFECT
    "authority", "omission_transfers",
)

#: `ParamSpec` fields DELIBERATELY not part of the signature, each with a reason.
#:
#: 🔴 THE TABLE IS EMPTY, AND THIS IS A STATEMENT, NOT AN OMISSION. `ParamSpec`
#: has not a single field that would leave the contract's meaning for the
#: model unchanged: all eleven either describe what the slot accepts, or who
#: decides the value. An empty cell here means "there are no exceptions," and
#: the very first new field will have to receive a decision rather than
#: inherit silence.
PARAM_UNSIGNED_FIELDS: dict[str, str] = {}

#: `OpSpec` fields that are part of the signature.
OP_SIGNED_FIELDS: tuple[str, ...] = (
    "name", "family", "params", "capability", "post", "effect", "result",
    "reads_model", "writes_model", "grounded", "tolerances",
    # ↓ THESE THREE WERE MISSING AND CONSTITUTED THE DEFECT
    "caveat", "result_by_param", "grounded_pool_by_param",
)

#: `OpSpec` fields DELIBERATELY not part of the signature. Empty for the same reason.
OP_UNSIGNED_FIELDS: dict[str, str] = {}

#: `OpSpec` field name -> key in the signed document. Anything not listed
#: here travels under its own name. Exists exactly for `name`/`op_name`:
#: without the map, the coverage instrument would be comparing different
#: dictionaries and would lie to both sides.
_OP_FIELD_TO_KEY: dict[str, str] = {"name": "op_name"}

#: Keys of the signed document that are NOT among `OpSpec`'s fields — each
#: with a reason. This is not a projection of the registry but its
#: surrounding context.
_PAYLOAD_ONLY_KEYS: dict[str, str] = {
    "schema": "версия формы самого документа, а не свойство операции",
    "refinement": ("обязательства понижения берутся у `translation_cert`, "
                   "а не у `OpSpec`: это второй авторитет, и он проецируется "
                   "сюда намеренно"),
}


class OpContractError(ValueError):
    """The existing operation authorities cannot form one honest contract."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise OpContractError(f"operation contract is not canonical JSON: {exc}") from exc


def _param_row(param: ParamSpec) -> dict[str, Any]:
    """One parameter -> the signable row. Keys = `PARAM_SIGNED_FIELDS`.

    The correspondence is held not by a promise but by an instrument:
    `_lint_contract_coverage` builds this row on a trial parameter and checks
    its keys against the list.
    """
    return {
        "name": param.name,
        "kind": param.kind,
        "required": param.required,
        "default": param.default,
        "min_val": param.min_val,
        "max_val": param.max_val,
        "choices": list(param.choices),
        "ref_kinds": [item.value for item in param.ref_kinds],
        "exact_string": param.exact_string,
        #: WHO DECIDES THE VALUE. `DERIVED_BY_REVIT` means what was sent
        #: decides nothing — and before 08-26 the signature did not distinguish this.
        "authority": param.authority,
        #: WHAT SILENTLY TAKES OVER AUTHORITY WHEN OMITTED. An empty string
        #: means "nothing," and it is distinguishable from a non-empty one
        #: exactly because it travels in the signature.
        "omission_transfers": param.omission_transfers,
    }


def _result_spec_row(result: ResultSpec) -> dict[str, Any]:
    """ONE result kind -> a row. Factored out of `_result_row` deliberately.

    An operation can have several kinds (`result_by_param`), and before 08-26
    only the static one traveled in the signature. Two copies of this
    serialization would drift apart silently — this tree's own named defect —
    so there is a single carrier.
    """
    return {
        "identity_cardinality": result.identity_cardinality.value,
        "identity_field": result.identity_field,
        "reference_kind": (
            result.reference_kind.value if result.reference_kind is not None else None
        ),
    }


def _result_row(op_spec: OpSpec) -> dict[str, Any]:
    return _result_spec_row(op_spec.result)


def _result_by_param_row(op_spec: OpSpec) -> dict[str, Any] | None:
    """THE RESULT KIND DECIDED BY A PARAMETER — or `None` if there is none.

    `None` and "the table is empty" are distinguishable: the registry does
    not allow an empty table (`__post_init__` requires it non-empty), so
    `None` unambiguously means "the operation has one kind," not "the ask failed."
    """
    if op_spec.result_by_param is None:
        return None
    param_name, table = op_spec.result_by_param
    return {
        "param": param_name,
        "table": {value: _result_spec_row(rspec)
                  for value, rspec in sorted(table.items())},
    }


def _grounded_pool_by_param_row(op_spec: OpSpec) -> dict[str, Any] | None:
    """THE GROUNDING POOL DECIDED BY A PARAMETER — or `None`."""
    if op_spec.grounded_pool_by_param is None:
        return None
    param_name, table = op_spec.grounded_pool_by_param
    return {
        "param": param_name,
        "table": {value: dict(sorted(pools.items()))
                  for value, pools in sorted(table.items())},
    }


def _refinement_row(op_spec: OpSpec) -> dict[str, Any] | None:
    if op_spec.family not in spec.WRITE_FAMILIES:
        return None

    # Lazy import keeps the registry usable by schema generation without
    # importing the emitter.  At planning time a write contract must include
    # the exact certificate semantics that will judge its lowering.
    from kir import translation_cert

    refinement = translation_cert._ensure_table().get(op_spec.name)
    if refinement is None:
        raise OpContractError(
            f"{op_spec.name}: write operation has no translation refinement")
    return {
        "materializer": list(refinement.materializer),
        "refuse_on_null": refinement.refuse_on_null,
        "witness_source": refinement.witness_source,
        "obligations": [
            {
                "clause": obligation.clause,
                "kind": obligation.kind,
                "block": obligation.block,
                "witness_markers": list(obligation.witness_markers),
                "param": obligation.param,
                "conditional": obligation.conditional,
                "unless_param": obligation.unless_param,
                "param_truthy": obligation.param_truthy,
                "key": obligation.key,
            }
            for obligation in refinement.obligations
        ],
    }


@dataclass(frozen=True, slots=True)
class OpContract:
    """Canonical projection of registry and lowering-proof semantics."""

    op_name: str
    _payload_json: str
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.op_name, str) or not self.op_name:
            raise OpContractError("operation contract needs a non-empty name")
        try:
            payload = json.loads(self._payload_json)
        except (TypeError, ValueError) as exc:
            raise OpContractError("operation contract payload is invalid JSON") from exc
        if _canonical_json(payload) != self._payload_json:
            raise OpContractError("operation contract payload is not canonical")
        if payload.get("op_name") != self.op_name:
            raise OpContractError("operation contract identity disagrees with payload")
        expected = hashlib.sha256(self._payload_json.encode("utf-8")).hexdigest()
        if self.digest != expected:
            raise OpContractError("operation contract digest disagrees with payload")

    @classmethod
    def from_spec(cls, op_spec: OpSpec) -> "OpContract":
        if not isinstance(op_spec, OpSpec):
            raise TypeError("op_spec must be OpSpec")
        payload = {
            "schema": OP_CONTRACT_SCHEMA,
            "op_name": op_spec.name,
            "family": op_spec.family,
            "effect": op_spec.effect.value,
            "reads_model": op_spec.reads_model,
            "writes_model": op_spec.writes_model,
            "capability": [list(cell) for cell in op_spec.capability],
            "params": [_param_row(param) for param in op_spec.params],
            "grounded": [list(item) for item in op_spec.grounded],
            "post": op_spec.post,
            "tolerances": dict(sorted(op_spec.tolerances.items())),
            "result": _result_row(op_spec),
            # THE RUNTIME OBSERVATION THAT TRAVELS TO THE MODEL via `course.spec`.
            # Editing this text on 08-26 (`e2bf5adc`) left no trace in the
            # signature — as of this line, it does.
            "caveat": op_spec.caveat,
            "result_by_param": _result_by_param_row(op_spec),
            "grounded_pool_by_param": _grounded_pool_by_param_row(op_spec),
            "refinement": _refinement_row(op_spec),
        }
        encoded = _canonical_json(payload)
        return cls(
            op_name=op_spec.name,
            _payload_json=encoded,
            digest=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = json.loads(self._payload_json)
        payload["contract_digest"] = self.digest
        return payload


def contract_for(op_name: str) -> OpContract:
    try:
        op_spec = spec.OPS[op_name]
    except KeyError as exc:
        raise OpContractError(f"unknown operation {op_name!r}") from exc
    return OpContract.from_spec(op_spec)


def audit_contract_kernel() -> tuple[str, ...]:
    """Check the seams that used to drift independently.

    This is deliberately structural.  Dynamic witness mutation tests remain
    the stronger proof that an emitted check can actually fail.
    """

    problems: list[str] = []
    from kir import translation_cert

    problems.extend(translation_cert.audit_registry_coverage())
    # The "declared versus laid" seam, the operation's side. Called from
    # here, not from import: building the document pulls in `translation_cert`.
    problems.extend(audit_contract_payload_keys())
    table = translation_cert._ensure_table()

    for op_name, op_spec in sorted(spec.OPS.items()):
        param_names = {param.name for param in op_spec.params}
        grounded_names: set[str] = set()
        for field_name, _pool, required in op_spec.grounded:
            if field_name in grounded_names:
                problems.append(f"{op_name}: duplicate grounded field {field_name!r}")
            grounded_names.add(field_name)
            param = next((item for item in op_spec.params
                          if item.name == field_name), None)
            if param is None:
                problems.append(
                    f"{op_name}: grounded field {field_name!r} is not a parameter")
            elif required and not param.required:
                problems.append(
                    f"{op_name}: grounded field {field_name!r} is required by "
                    "grounding but optional in the registry")

        refinement = table.get(op_name)
        if refinement is not None:
            for obligation in refinement.obligations:
                for gate_name in (obligation.param, obligation.unless_param):
                    if (gate_name is not None
                            and gate_name not in param_names
                            and not gate_name.startswith("__")):
                        problems.append(
                            f"{op_name}: obligation gate {gate_name!r} is not "
                            "a registry parameter or named compiler-derived field")
        try:
            contract_for(op_name)
        except (OpContractError, TypeError, ValueError) as exc:
            problems.append(f"{op_name}: cannot build canonical contract: {exc}")

    return tuple(problems)


def _lint_contract_coverage() -> None:
    """A REGISTRY FIELD THAT RECEIVED NO DECISION FAILS THE MODULE ON IMPORT.

    The instrument closes THREE seams at once, and each of them had already
    drifted apart silently:

    1. `ParamSpec`/`OpSpec` grew a field and it was not added here — exactly
       how the `authority` defect was born (a registry field since 08-19, in
       the signature since 08-26);
    2. a field is declared as signed but the serializer does not put it in —
       then the list would lie to the reader, promising coverage that does not exist;
    3. a field is declared both signed and excluded at once — two decisions
       about one subject.

    The check is done BY CONSTRUCTION, not by comparing two lists: a row is
    built on a trial input and its keys are compared against the
    declaration. A list checked against a list would be a third carrier of
    the same notion.
    """
    problems: list[str] = []

    for cls, signed, unsigned, where in (
            (ParamSpec, PARAM_SIGNED_FIELDS, PARAM_UNSIGNED_FIELDS, "ParamSpec"),
            (OpSpec, OP_SIGNED_FIELDS, OP_UNSIGNED_FIELDS, "OpSpec")):
        actual = {f.name for f in dataclasses.fields(cls)}
        both = sorted(set(signed) & set(unsigned))
        if both:
            problems.append(
                f"{where}: поля объявлены и подписанными, и исключёнными: {both}")
        stray = sorted(actual - set(signed) - set(unsigned))
        if stray:
            problems.append(
                f"{where}: поля не получили решения — ни в подписи, ни в "
                f"исключениях: {stray}. Заведи в подпись либо назови причину.")
        phantom = sorted((set(signed) | set(unsigned)) - actual)
        if phantom:
            problems.append(
                f"{where}: объявлены поля, которых у класса нет: {phantom}")
        for name, reason in unsigned.items():
            if not isinstance(reason, str) or len(reason) < 20:
                problems.append(
                    f"{where}.{name}: исключение без внятной причины")

    # SEAM 2, THE PARAMETER'S SIDE: what the list promises must be present in the row.
    probe_param = ParamSpec("__probe__", "str")
    emitted = set(_param_row(probe_param))
    missing = sorted(set(PARAM_SIGNED_FIELDS) - emitted)
    if missing:
        problems.append(
            f"_param_row не кладёт объявленные подписанными поля: {missing}")
    extra = sorted(emitted - set(PARAM_SIGNED_FIELDS))
    if extra:
        problems.append(
            f"_param_row кладёт необъявленные ключи: {extra}")

    if problems:
        raise OpContractError(
            "покрытие подписи контракта разошлось с реестром:\n  "
            + "\n  ".join(problems))


_lint_contract_coverage()


def audit_contract_payload_keys() -> tuple[str, ...]:
    """SEAM 2, THE OPERATION'S SIDE: the document's keys against the declaration.

    Separate from `_lint_contract_coverage` and deliberately NOT on import:
    building the document needs a real op, and a real op for the write family
    pulls in `translation_cert`. An import pulling in the emitter would
    unfold a dependency cycle, which `_refinement_row` avoids with a lazy
    import. Hence it is here — and is called from `audit_contract_kernel`,
    i.e. from the gate.
    """
    problems: list[str] = []
    expected = {_OP_FIELD_TO_KEY.get(name, name) for name in OP_SIGNED_FIELDS}
    expected |= set(_PAYLOAD_ONLY_KEYS)
    for op_name in sorted(spec.OPS):
        keys = set(contract_for(op_name).to_dict()) - {"contract_digest"}
        missing = sorted(expected - keys)
        if missing:
            problems.append(f"{op_name}: в подписи нет объявленных ключей: {missing}")
        extra = sorted(keys - expected)
        if extra:
            problems.append(f"{op_name}: в подписи необъявленные ключи: {extra}")
        if problems:
            break     # one op answers for all: the document is built the same way
    return tuple(problems)


__all__ = [
    "OP_CONTRACT_SCHEMA",
    "OP_SIGNED_FIELDS",
    "OP_UNSIGNED_FIELDS",
    "PARAM_SIGNED_FIELDS",
    "PARAM_UNSIGNED_FIELDS",
    "OpContract",
    "OpContractError",
    "audit_contract_kernel",
    "audit_contract_payload_keys",
    "contract_for",
]
