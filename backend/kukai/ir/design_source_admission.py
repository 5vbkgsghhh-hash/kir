"""Offline admission of canonical Design Source candidates into current KIR.

This is an intentionally unreachable seam.  It re-derives candidate bytes from
one exact :class:`BuildResultV0`, passes every member through the real current
KIR planner and snapshot-free grounder, and returns immutable evidence.  It
does not lower, emit, compile, dispatch, call serving, or contact Revit.

``KirCandidateSetV0.status == COMPLETE`` means source-coverage completeness;
only an ``ACCEPTED`` receipt from this module means that those canonical bytes
were admitted by the current plan/ground boundary.  Even that receipt has
offline-only scope and is never publish authority.
"""
from __future__ import annotations

import builtins
from dataclasses import dataclass, field
import dis
from hashlib import sha256
from importlib import import_module
import re
import sys
from types import CodeType, FunctionType, ModuleType
from typing import Any, Callable, ClassVar, Literal

from kukai.design_source.canonical import (
    canonical_bytes,
    canonical_digest,
    digest_text,
    identifier,
    stable_logical_id,
)
from kukai.design_source.contracts import BuildResultV0
from kukai.design_source.errors import DesignSourceError
from kukai.design_source.kir_candidates import (
    KirCandidateMemberV0,
    KirCandidateSetV0,
    plan_kir_candidates,
)
from kukai.design_source.lowering import plan_dry_lowering
from kukai.ir import spec
from kukai.ir.compiler import (
    BUDGET_AUTHORED,
    MAX_VALIDATED_OPS,
    plan_program,
    pre_macro_budget,
)
from kukai.ir.diag import KirRefusal
from kukai.ir.ground import ground_program
from kukai.ir.midend import GroundedProgram, PlannedProgram, ProgramFamily
from kukai.ir import authoring as _authoring_module
from kukai.ir import authoring_validation as _authoring_validation_module


ADMISSION_ALGORITHM_VERSION = "kir-design-source-admission/0"
AUTHORITY_SCOPE = "OFFLINE_PLAN_GROUND_ONLY"
GROUNDING_POLICY = "snapshot_none_local_refs_and_declared_doc_defaults"
EVIDENCE_LIFETIME = "EPHEMERAL_PROCESS_LOCAL_NO_READBACK"

STATUS_ACCEPTED = "ACCEPTED"
STATUS_REFUSED = "REFUSED"

INVALID_CONTRACT = "KIR-ADM-001"
STALE_CANDIDATE_BUILD = "KIR-ADM-002"
NONCANONICAL_CANDIDATE_SET = "KIR-ADM-003"
SOURCE_LOWERING_REFUSED = "KIR-ADM-004"
KIR_PLAN_REFUSED = "KIR-ADM-005"
KIR_GROUND_REFUSED = "KIR-ADM-006"
EVIDENCE_MISMATCH = "KIR-ADM-007"
INTERNAL_REFUSED = "KIR-ADM-999"

_REFUSAL_CODES = frozenset({
    INVALID_CONTRACT,
    STALE_CANDIDATE_BUILD,
    NONCANONICAL_CANDIDATE_SET,
    SOURCE_LOWERING_REFUSED,
    KIR_PLAN_REFUSED,
    KIR_GROUND_REFUSED,
    EVIDENCE_MISMATCH,
    INTERNAL_REFUSED,
})
_STAGES = frozenset({"input", "source", "canonical", "plan", "ground", "evidence"})
_KIR_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")
_BUDGET_CLASS, _AUTHORED_LIMIT = pre_macro_budget(bulk=False)
if _BUDGET_CLASS != BUDGET_AUTHORED:  # import-time policy drift is not admissible
    raise RuntimeError("current non-bulk KIR budget is not the authored budget")


class _RuntimeBindingDrift(RuntimeError):
    pass


def _code_constant(value: Any) -> Any:
    if isinstance(value, CodeType):
        return {"code": _code_data(value)}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, float):
        return {"float_hex": value.hex()}
    if isinstance(value, complex):
        return {"complex_hex": (value.real.hex(), value.imag.hex())}
    if isinstance(value, tuple):
        return {"tuple": tuple(_code_constant(item) for item in value)}
    if isinstance(value, list):
        return {"list": tuple(_code_constant(item) for item in value)}
    if isinstance(value, dict):
        items = [
            (_code_constant(key), _code_constant(item))
            for key, item in value.items()
        ]
        return {"dict": tuple(sorted(items, key=canonical_bytes))}
    if isinstance(value, set):
        items = [_code_constant(item) for item in value]
        return {"set": tuple(sorted(items, key=canonical_bytes))}
    if isinstance(value, frozenset):
        items = [_code_constant(item) for item in value]
        return {"frozenset": tuple(sorted(items, key=canonical_bytes))}
    if value is Ellipsis:
        return {"ellipsis": True}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    return {"constant_type": f"{type(value).__module__}:{type(value).__qualname__}"}


def _code_data(code: CodeType) -> dict[str, Any]:
    return {
        "argcount": code.co_argcount,
        "cellvars": code.co_cellvars,
        "code_hex": code.co_code.hex(),
        "consts": tuple(_code_constant(item) for item in code.co_consts),
        "exceptiontable_hex": getattr(code, "co_exceptiontable", b"").hex(),
        "flags": code.co_flags,
        "freevars": code.co_freevars,
        "kwonlyargcount": code.co_kwonlyargcount,
        "names": code.co_names,
        "nlocals": code.co_nlocals,
        "posonlyargcount": getattr(code, "co_posonlyargcount", 0),
        "stacksize": code.co_stacksize,
        "varnames": code.co_varnames,
    }


def _global_load_names(code: CodeType) -> frozenset[str]:
    names = {
        instruction.argval
        for instruction in dis.get_instructions(code)
        if instruction.opname == "LOAD_GLOBAL"
        and isinstance(instruction.argval, str)
    }
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            names.update(_global_load_names(constant))
    return frozenset(names)


def _import_requests(code: CodeType) -> frozenset[tuple[str, tuple[str, ...]]]:
    requests: set[tuple[str, tuple[str, ...]]] = set()
    instructions = tuple(dis.get_instructions(code))
    for index, instruction in enumerate(instructions):
        if instruction.opname != "IMPORT_NAME" or not isinstance(
            instruction.argval, str
        ):
            continue
        imported_names: list[str] = []
        for following in instructions[index + 1:]:
            if following.opname in {"IMPORT_NAME", "POP_TOP"}:
                break
            if (
                following.opname == "IMPORT_FROM"
                and isinstance(following.argval, str)
            ):
                imported_names.append(following.argval)
        requests.add((instruction.argval, tuple(sorted(set(imported_names)))))
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            requests.update(_import_requests(constant))
    return frozenset(requests)


def _module_attribute_chains(
    code: CodeType,
) -> frozenset[tuple[str, tuple[str, ...]]]:
    chains: set[tuple[str, tuple[str, ...]]] = set()
    instructions = tuple(dis.get_instructions(code))
    for index, instruction in enumerate(instructions):
        if instruction.opname != "LOAD_GLOBAL" or not isinstance(
            instruction.argval, str
        ):
            continue
        attributes: list[str] = []
        for following in instructions[index + 1:]:
            if following.opname not in {"LOAD_ATTR", "LOAD_METHOD"}:
                break
            if not isinstance(following.argval, str):
                break
            attributes.append(following.argval)
            chains.add((instruction.argval, tuple(attributes)))
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            chains.update(_module_attribute_chains(constant))
    return frozenset(chains)


def _import_alias_module_attribute_chains(
    code: CodeType,
    inherited: tuple[tuple[str, tuple[str, tuple[str, ...]]], ...] = (),
) -> frozenset[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    """Return statically exact module paths reached through import aliases.

    The reachable admission graph uses ordinary local imports, including
    ``import copy as _copy`` and ``from kukai.ir import macros``.  Merely
    sealing ``sys.modules`` or the imported package attribute does not bind a
    later ``_copy.deepcopy``/``macros.expand_with_origins`` lookup.  This
    deliberately small data-flow accepts the compiler forms emitted for
    ``IMPORT_NAME``/``IMPORT_FROM`` followed by a local/name/cell/global store,
    then records every contiguous ``LOAD_ATTR``/``LOAD_METHOD`` prefix.

    Ambiguous rebinding is rejected instead of being silently under-counted.
    Imported functions/classes may be loaded directly with an empty chain;
    the caller distinguishes those exact import bindings from a module object
    escaping without a statically visible attribute lookup.
    """

    store_ops = frozenset({
        "STORE_DEREF", "STORE_FAST", "STORE_GLOBAL", "STORE_NAME",
    })
    delete_ops = frozenset({
        "DELETE_DEREF", "DELETE_FAST", "DELETE_GLOBAL", "DELETE_NAME",
    })
    load_ops = frozenset({
        "LOAD_CLASSDEREF", "LOAD_DEREF", "LOAD_FAST", "LOAD_GLOBAL", "LOAD_NAME",
    })
    instructions = tuple(dis.get_instructions(code))
    aliases: dict[str, tuple[str, tuple[str, ...]]] = {
        name: source
        for name, source in inherited
        if name in code.co_freevars
    }
    import_store_indexes: set[int] = set()

    def bind_alias(
        instruction_index: int,
        alias_name: str,
        source: tuple[str, tuple[str, ...]],
    ) -> None:
        prior = aliases.get(alias_name)
        if prior is not None and prior != source:
            raise RuntimeError(
                "ambiguous imported module alias in admission graph: "
                f"{alias_name}")
        aliases[alias_name] = source
        import_store_indexes.add(instruction_index)

    for index, instruction in enumerate(instructions):
        if instruction.opname != "IMPORT_NAME" or not isinstance(
            instruction.argval, str
        ):
            continue
        module_name = instruction.argval
        if not module_name:
            raise RuntimeError(
                "relative imported module alias is unsupported in admission graph")
        plain_import = (
            index > 0
            and instructions[index - 1].opname == "LOAD_CONST"
            and instructions[index - 1].argval is None
        )
        pending_from: list[str] = []
        stored = False
        for following_index in range(index + 1, len(instructions)):
            following = instructions[following_index]
            if following.opname == "IMPORT_NAME":
                break
            if following.opname == "IMPORT_FROM" and isinstance(
                following.argval, str
            ):
                pending_from.append(following.argval)
                continue
            if following.opname in store_ops and isinstance(
                following.argval, str
            ):
                if pending_from:
                    source = (
                        (module_name, ())
                        if plain_import
                        else (module_name, (pending_from[-1],))
                    )
                    pending_from.clear()
                elif not stored and plain_import:
                    source = (module_name.split(".", 1)[0], ())
                else:
                    raise RuntimeError(
                        "unsupported imported module store in admission graph: "
                        f"{module_name}")
                bind_alias(following_index, following.argval, source)
                stored = True
                continue
            if following.opname in {"COPY", "NOP", "POP_TOP", "SWAP"}:
                continue
            if stored:
                break
            raise RuntimeError(
                "unsupported imported module flow in admission graph: "
                f"{module_name}:{following.opname}")
        if not stored or pending_from:
            raise RuntimeError(
                "incomplete imported module flow in admission graph: "
                f"{module_name}")

    for index, instruction in enumerate(instructions):
        name = instruction.argval
        if not isinstance(name, str) or name not in aliases:
            continue
        if instruction.opname in store_ops:
            if index not in import_store_indexes:
                raise RuntimeError(
                    "imported module alias is rebound in admission graph: "
                    f"{name}")
            continue
        if instruction.opname in delete_ops:
            raise RuntimeError(
                "imported module alias is deleted in admission graph: "
                f"{name}")

    chains: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    for index, instruction in enumerate(instructions):
        if instruction.opname not in load_ops or not isinstance(
            instruction.argval, str
        ):
            continue
        source = aliases.get(instruction.argval)
        if source is None:
            continue
        module_name, imported_path = source
        attributes: list[str] = []
        for following in instructions[index + 1:]:
            if following.opname not in {"LOAD_ATTR", "LOAD_METHOD"}:
                break
            if not isinstance(following.argval, str):
                break
            attributes.append(following.argval)
            chains.add((module_name, imported_path, tuple(attributes)))
        if not attributes:
            chains.add((module_name, imported_path, ()))

    child_inherited = tuple(sorted(aliases.items()))
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            chains.update(_import_alias_module_attribute_chains(
                constant, child_inherited))
    return frozenset(chains)


def _class_method_functions(
    value: Any,
) -> tuple[tuple[str, FunctionType], ...]:
    if isinstance(value, FunctionType):
        return (("function", value),)
    if isinstance(value, (staticmethod, classmethod)):
        return (
            (("descriptor", value.__func__),)
            if isinstance(value.__func__, FunctionType)
            else ()
        )
    if isinstance(value, property):
        return tuple(
            (accessor, function)
            for accessor, function in (
                ("get", value.fget),
                ("set", value.fset),
                ("delete", value.fdel),
            )
            if isinstance(function, FunctionType)
        )
    return ()


def _binding_token(value: Any) -> Any:
    if isinstance(value, FunctionType):
        return {
            "code": _code_data(value.__code__),
            "defaults": _code_constant(value.__defaults__),
            "kwdefaults": tuple(
                (name, _code_constant(default))
                for name, default in sorted((value.__kwdefaults__ or {}).items())
            ),
            "module": value.__module__,
            "qualname": value.__qualname__,
        }
    if isinstance(value, type):
        methods = {}
        for name, member in sorted(value.__dict__.items()):
            for accessor, function in _class_method_functions(member):
                methods[f"{name}:{accessor}"] = _binding_token(function)
        return {
            "class": f"{value.__module__}:{value.__qualname__}",
            "methods": methods,
        }
    if isinstance(value, ModuleType):
        return {"module": value.__name__}
    if hasattr(value, "pattern") and hasattr(value, "flags"):
        return {"flags": int(value.flags), "regex": value.pattern}
    if value is None or isinstance(value, (str, bool, int)):
        return {"literal": value}
    if isinstance(value, (tuple, frozenset)):
        return {
            "collection": tuple(sorted(
                (_binding_token(item) for item in value), key=canonical_bytes)),
            "kind": type(value).__name__,
        }
    return {
        "object_type": f"{type(value).__module__}:{type(value).__qualname__}",
        "qualname": getattr(value, "__qualname__", None),
    }


def _make_own_runtime_binding_seal(
    root_names: tuple[str, ...],
    *,
    deferred_names: frozenset[str],
) -> tuple[Callable[[], Callable[[], None]], str]:
    """Prepare a deterministic seal for this module's own admission graph.

    The two evidence constants are deliberately finalized after the graph
    digest breaks their otherwise circular dependency.  Their names and lookup
    sites are part of the digest; ``finalize`` then captures their exact final
    values before the public admission closure is created.
    """

    namespace = globals()
    missing = object()
    records: list[tuple[str, str, dict[str, Any], Any, Any, str]] = []
    absent_records: list[tuple[str, str, dict[str, Any]]] = []
    deferred_records: list[tuple[str, str, dict[str, Any]]] = []
    module_attribute_records: list[
        tuple[str, str, tuple[str, ...], Any, str, bool, Any, Any, str | None, bool]
    ] = []
    seen: set[tuple[int, str]] = set()
    seen_module_attributes: set[tuple[int, str]] = set()
    walked_functions: set[int] = set()
    walked_classes: set[int] = set()

    def admit(scope: str, name: str, owner: dict[str, Any], expected: Any) -> None:
        key = (id(owner), name)
        if key in seen:
            return
        seen.add(key)
        token = _binding_token(expected)
        token_digest = canonical_digest("kir.admission-own-binding.v0", token)
        records.append((scope, name, owner, expected, token, token_digest))

    def admit_absent(scope: str, name: str, owner: dict[str, Any]) -> None:
        key = (id(owner), name)
        if key in seen:
            return
        seen.add(key)
        absent_records.append((scope, name, owner))

    def admit_deferred(scope: str, name: str, owner: dict[str, Any]) -> None:
        key = (id(owner), name)
        if key in seen:
            return
        seen.add(key)
        deferred_records.append((scope, name, owner))

    def admit_module_chain(
        scope: str,
        root_name: str,
        root_module: ModuleType,
        chain: tuple[str, ...],
    ) -> None:
        current_owner: Any = root_module
        traversed: list[str] = []
        for attribute_name in chain:
            key = (id(current_owner), attribute_name)
            traversed.append(attribute_name)
            if key in seen_module_attributes:
                current_owner = getattr(current_owner, attribute_name, missing)
                if current_owner is missing:
                    break
                continue
            seen_module_attributes.add(key)
            identity_required = isinstance(current_owner, ModuleType)
            expected = getattr(current_owner, attribute_name, missing)
            if expected is missing:
                module_attribute_records.append((
                    scope,
                    root_name,
                    tuple(traversed),
                    current_owner,
                    attribute_name,
                    False,
                    missing,
                    None,
                    None,
                    identity_required,
                ))
                break
            token = _binding_token(expected)
            token_digest = canonical_digest(
                "kir.admission-own-module-attribute.v0", token)
            module_attribute_records.append((
                scope,
                root_name,
                tuple(traversed),
                current_owner,
                attribute_name,
                True,
                expected,
                token,
                token_digest,
                identity_required,
            ))
            current_owner = expected

    def walk_class(class_value: type) -> None:
        if id(class_value) in walked_classes:
            return
        walked_classes.add(id(class_value))
        for _name, member in sorted(class_value.__dict__.items()):
            for _accessor, function in _class_method_functions(member):
                walk(function)

    def walk(function: FunctionType) -> None:
        if id(function) in walked_functions:
            return
        walked_functions.add(id(function))
        owner = function.__globals__
        scope = function.__module__
        for module_name, imported_path, chain in sorted(
            _import_alias_module_attribute_chains(function.__code__)
        ):
            root_module = sys.modules.get(module_name)
            if not isinstance(root_module, ModuleType):
                if chain:
                    raise RuntimeError(
                        "imported module attribute root is unavailable in own "
                        f"admission graph: {module_name}")
                continue
            current: Any = root_module
            for attribute_name in imported_path:
                current = getattr(current, attribute_name, missing)
                if current is missing:
                    break
            if chain:
                admit_module_chain(
                    scope, module_name, root_module, (*imported_path, *chain))
            elif isinstance(current, ModuleType):
                raise RuntimeError(
                    "imported module escapes without an exact attribute chain in "
                    f"own admission graph: {module_name}")
        for root_name, chain in sorted(
            _module_attribute_chains(function.__code__)
        ):
            root_value = owner.get(root_name, missing)
            if isinstance(root_value, ModuleType):
                admit_module_chain(scope, root_name, root_value, chain)
        for name in sorted(_global_load_names(function.__code__)):
            if name in owner:
                expected = owner[name]
                admit(scope, name, owner, expected)
                if isinstance(expected, FunctionType) and expected.__module__ == __name__:
                    walk(expected)
                elif isinstance(expected, type) and expected.__module__ == __name__:
                    walk_class(expected)
            elif owner is namespace and name in deferred_names:
                admit_deferred(scope, name, owner)
            else:
                admit_absent(scope, name, owner)
                if hasattr(builtins, name):
                    admit("builtins", name, vars(builtins), getattr(builtins, name))

    for name in root_names:
        expected = namespace.get(name, missing)
        if expected is missing:
            raise RuntimeError(f"own admission seal root is absent: {name}")
        admit("admission", name, namespace, expected)
        if isinstance(expected, FunctionType):
            walk(expected)
        elif isinstance(expected, type):
            walk_class(expected)

    admitted = tuple(records)
    admitted_absent = tuple(absent_records)
    admitted_deferred = tuple(deferred_records)
    admitted_module_attributes = tuple(module_attribute_records)
    profile_digest = canonical_digest(
        "kir.admission-own-runtime-bindings.v0",
        {
            "absent_globals": tuple({"name": name, "scope": scope}
                                    for scope, name, _owner in admitted_absent),
            "bindings": tuple({
                "name": name,
                "scope": scope,
                "token_digest": token_digest,
            } for scope, name, _owner, _expected, _token, token_digest in admitted),
            "deferred_globals": tuple({"name": name, "scope": scope}
                                      for scope, name, _owner in admitted_deferred),
            "module_attribute_census": len(admitted_module_attributes),
            "module_attributes": tuple({
                "path": (root_name, *chain),
                "scope": scope,
                "state": "present" if present else "absent",
                "token_digest": token_digest,
            } for (
                scope,
                root_name,
                chain,
                _owner,
                _attribute_name,
                present,
                _expected,
                _token,
                token_digest,
                _identity_required,
            ) in admitted_module_attributes),
            "python_cache_tag": sys.implementation.cache_tag or "unknown",
            "roots": root_names,
        },
    )
    token_function = _binding_token

    def finalize() -> Callable[[], None]:
        deferred_bindings: list[
            tuple[str, str, dict[str, Any], Any, Any]
        ] = []
        for scope, name, owner in admitted_deferred:
            expected = owner.get(name, missing)
            if expected is missing:
                raise RuntimeError(
                    f"deferred admission binding was not finalized: {scope}:{name}")
            deferred_bindings.append(
                (scope, name, owner, expected, token_function(expected)))
        finalized_deferred = tuple(deferred_bindings)

        def verify() -> None:
            for (
                scope,
                root_name,
                chain,
                owner,
                attribute_name,
                present,
                expected,
                token,
                _digest,
                identity_required,
            ) in admitted_module_attributes:
                current = getattr(owner, attribute_name, missing)
                if not present:
                    if current is not missing:
                        raise _RuntimeBindingDrift(
                            "sealed own module attribute appeared: "
                            f"{scope}:{root_name}.{'.'.join(chain)}")
                    continue
                if identity_required and current is not expected:
                    raise _RuntimeBindingDrift(
                        "sealed own module attribute drift: "
                        f"{scope}:{root_name}.{'.'.join(chain)}")
                if current is missing or token_function(current) != token:
                    raise _RuntimeBindingDrift(
                        "sealed own module attribute object drift: "
                        f"{scope}:{root_name}.{'.'.join(chain)}")
            for scope, name, owner in admitted_absent:
                if name in owner:
                    raise _RuntimeBindingDrift(
                        f"new global shadows own admission lookup: {scope}:{name}")
            for scope, name, owner, expected, _token, _digest in admitted:
                if owner.get(name, missing) is not expected:
                    raise _RuntimeBindingDrift(
                        f"sealed own admission binding drift: {scope}:{name}")
            for scope, name, owner, _expected, token, _digest in admitted:
                if token_function(owner[name]) != token:
                    raise _RuntimeBindingDrift(
                        f"sealed own admission object drift: {scope}:{name}")
            for scope, name, owner, expected, token in finalized_deferred:
                if owner.get(name, missing) is not expected:
                    raise _RuntimeBindingDrift(
                        f"sealed evidence binding drift: {scope}:{name}")
                if token_function(owner[name]) != token:
                    raise _RuntimeBindingDrift(
                        f"sealed evidence object drift: {scope}:{name}")

        verify()
        return verify

    return finalize, profile_digest


def _make_runtime_binding_seal() -> tuple[
    Callable[..., None],
    str,
    FunctionType,
    FunctionType,
    tuple[tuple[str, tuple[str, ...]], ...],
    tuple[tuple[str, tuple[str, ...]], ...],
]:
    """Seal the exact pure plan/ground call graph used by offline admission.

    Besides ordinary rebinding and code/default drift, every absent global
    lookup is recorded.  Adding e.g. a module-global ``len`` later therefore
    refuses instead of silently changing an already-profiled admission result.
    Exact source bytes for this seam and the three current KIR stages are also
    bound and re-read by the outer pre/post checks.  This is trusted-host cache
    safety, not a sandbox against arbitrary Python object introspection or an
    ABA mutation entirely between the two checks.
    """

    compiler_module = sys.modules[plan_program.__module__]
    ground_module = sys.modules[ground_program.__module__]
    source_lowering_module = sys.modules[plan_dry_lowering.__module__]
    candidate_module = sys.modules[plan_kir_candidates.__module__]
    missing = object()
    records: list[tuple[str, str, dict[str, Any], Any, Any, str]] = []
    absent_records: list[tuple[str, str, dict[str, Any]]] = []
    module_attribute_records: list[
        tuple[str, str, tuple[str, ...], Any, str, bool, Any, Any, str | None, bool]
    ] = []
    seen: set[tuple[int, str]] = set()
    seen_module_attributes: set[tuple[int, str]] = set()
    module_attribute_manifest: set[tuple[str, tuple[str, ...]]] = set()
    walked_functions: set[int] = set()
    walked_classes: set[int] = set()
    walked_internal_modules: set[str] = set()
    requested_imports: set[tuple[str, tuple[str, ...]]] = set()
    requested_import_module_attributes: set[
        tuple[str, str, tuple[str, ...], tuple[str, ...]]
    ] = set()

    def admit(scope: str, name: str, namespace: dict[str, Any], expected: Any) -> None:
        key = (id(namespace), name)
        if key in seen:
            return
        seen.add(key)
        token = _binding_token(expected)
        token_digest = canonical_digest("kir.admission-binding.v0", token)
        records.append((scope, name, namespace, expected, token, token_digest))

    def admit_absent(scope: str, name: str, namespace: dict[str, Any]) -> None:
        key = (id(namespace), name)
        if key in seen:
            return
        seen.add(key)
        absent_records.append((scope, name, namespace))

    def admit_module_chain(
        scope: str,
        root_name: str,
        root_module: ModuleType,
        chain: tuple[str, ...],
    ) -> None:
        current_owner: Any = root_module
        traversed: list[str] = []
        for attribute_name in chain:
            key = (id(current_owner), attribute_name)
            traversed.append(attribute_name)
            module_attribute_manifest.add(
                (root_module.__name__, tuple(traversed)))
            if key in seen_module_attributes:
                current_owner = getattr(current_owner, attribute_name, missing)
                if current_owner is missing:
                    break
                continue
            seen_module_attributes.add(key)
            identity_required = isinstance(current_owner, ModuleType)
            expected = getattr(current_owner, attribute_name, missing)
            if expected is missing:
                module_attribute_records.append((
                    scope,
                    root_name,
                    tuple(traversed),
                    current_owner,
                    attribute_name,
                    False,
                    missing,
                    None,
                    None,
                    identity_required,
                ))
                break
            token = _binding_token(expected)
            token_digest = canonical_digest(
                "kir.admission-module-attribute.v0", token)
            module_attribute_records.append((
                scope,
                root_name,
                tuple(traversed),
                current_owner,
                attribute_name,
                True,
                expected,
                token,
                token_digest,
                identity_required,
            ))
            current_owner = expected

    def allowed_module(module_name: str) -> bool:
        return (
            module_name == "kukai.design_source"
            or module_name.startswith("kukai.design_source.")
            or module_name == "kukai.ir"
            or module_name.startswith("kukai.ir.")
        )

    def walk_class(class_value: type) -> None:
        if id(class_value) in walked_classes:
            return
        walked_classes.add(id(class_value))
        if allowed_module(class_value.__module__):
            walked_internal_modules.add(class_value.__module__)
        for _name, member in sorted(class_value.__dict__.items()):
            for _accessor, function in _class_method_functions(member):
                walk(function)

    def walk(function: FunctionType) -> None:
        if id(function) in walked_functions:
            return
        walked_functions.add(id(function))
        if allowed_module(function.__module__):
            walked_internal_modules.add(function.__module__)
        requested_imports.update(_import_requests(function.__code__))
        namespace = function.__globals__
        scope = function.__module__
        requested_import_module_attributes.update(
            (scope, module_name, imported_path, chain)
            for module_name, imported_path, chain
            in _import_alias_module_attribute_chains(function.__code__)
        )
        for root_name, chain in sorted(
            _module_attribute_chains(function.__code__)
        ):
            root_value = namespace.get(root_name, missing)
            if isinstance(root_value, ModuleType):
                admit_module_chain(scope, root_name, root_value, chain)
        for name in sorted(_global_load_names(function.__code__)):
            if name in namespace:
                expected = namespace[name]
                admit(scope, name, namespace, expected)
                if isinstance(expected, FunctionType) and allowed_module(
                    expected.__module__
                ):
                    walk(expected)
                elif isinstance(expected, type) and allowed_module(
                    expected.__module__
                ):
                    walk_class(expected)
            else:
                admit_absent(scope, name, namespace)
                if hasattr(builtins, name):
                    admit("builtins", name, vars(builtins), getattr(builtins, name))

    admission_namespace = globals()
    explicit = (
        ("admission", "plan_program", admission_namespace, plan_program),
        ("admission", "ground_program", admission_namespace, ground_program),
        ("admission", "plan_dry_lowering", admission_namespace, plan_dry_lowering),
        ("admission", "plan_kir_candidates", admission_namespace, plan_kir_candidates),
        ("compiler", "plan_program", vars(compiler_module), plan_program),
        ("ground", "ground_program", vars(ground_module), ground_program),
        ("source.lowering", "plan_dry_lowering", vars(source_lowering_module),
         plan_dry_lowering),
        ("source.candidates", "plan_kir_candidates", vars(candidate_module),
         plan_kir_candidates),
        ("authoring", "validate", vars(_authoring_module),
         _authoring_module.validate),
        ("authoring_validation", "validate", vars(_authoring_validation_module),
         _authoring_validation_module.validate),
    )
    for scope, name, namespace, expected in explicit:
        admit(scope, name, namespace, expected)
    for root in (
        plan_program,
        ground_program,
        plan_dry_lowering,
        plan_kir_candidates,
        _authoring_validation_module.validate,
    ):
        walk(root)

    module_registry = sys.modules
    import_exact = import_module
    processed_import_requests: set[tuple[str, tuple[str, ...]]] = set()
    while True:
        pending = tuple(sorted(requested_imports - processed_import_requests))
        if not pending:
            break
        for module_name, imported_names in pending:
            processed_import_requests.add((module_name, imported_names))
            candidates = (module_name, *(
                f"{module_name}.{imported_name}"
                for imported_name in imported_names
            ))
            for candidate in candidates:
                if not candidate.startswith("kukai.") or candidate in module_registry:
                    continue
                try:
                    import_exact(candidate)
                except ModuleNotFoundError as exc:
                    if exc.name != candidate:
                        raise
            imported_module = module_registry.get(module_name)
            if not isinstance(imported_module, ModuleType):
                continue
            for imported_name in imported_names:
                expected = getattr(imported_module, imported_name, None)
                if isinstance(expected, FunctionType) and allowed_module(
                    expected.__module__
                ):
                    walk(expected)
                elif isinstance(expected, type) and allowed_module(
                    expected.__module__
                ):
                    walk_class(expected)

    for scope, module_name, imported_path, chain in sorted(
        requested_import_module_attributes
    ):
        root_module = module_registry.get(module_name)
        if not isinstance(root_module, ModuleType):
            if chain:
                raise RuntimeError(
                    "imported module attribute root is unavailable in admission "
                    f"graph: {module_name}")
            continue
        current: Any = root_module
        for attribute_name in imported_path:
            current = getattr(current, attribute_name, missing)
            if current is missing:
                break
        if chain:
            admit_module_chain(
                scope, module_name, root_module, (*imported_path, *chain))
        elif isinstance(current, ModuleType):
            raise RuntimeError(
                "imported module escapes without an exact attribute chain in "
                f"admission graph: {module_name}")

    admitted = tuple(records)
    admitted_absent = tuple(absent_records)
    admitted_module_attributes = tuple(module_attribute_records)
    admitted_module_attribute_manifest = tuple(sorted(module_attribute_manifest))
    admitted_import_requests = tuple(sorted(requested_imports))
    import_module_records: list[
        tuple[str, bool, ModuleType | None, Any, str | None]
    ] = []
    import_attribute_records: list[
        tuple[str, ModuleType, str, bool, Any, Any, str | None]
    ] = []
    recorded_import_modules: set[str] = set()
    recorded_import_attributes: set[tuple[str, str]] = set()

    def admit_import_attribute(parent_name: str, attribute_name: str) -> None:
        key = (parent_name, attribute_name)
        if key in recorded_import_attributes:
            return
        recorded_import_attributes.add(key)
        parent = module_registry.get(parent_name)
        if not isinstance(parent, ModuleType):
            return
        if hasattr(parent, attribute_name):
            expected = getattr(parent, attribute_name)
            token = _binding_token(expected)
            token_digest = canonical_digest(
                "kir.admission-import-binding.v0", token)
            import_attribute_records.append((
                parent_name,
                parent,
                attribute_name,
                True,
                expected,
                token,
                token_digest,
            ))
        else:
            import_attribute_records.append((
                parent_name,
                parent,
                attribute_name,
                False,
                missing,
                None,
                None,
            ))

    def admit_import_module(module_name: str) -> None:
        if not module_name or module_name in recorded_import_modules:
            return
        recorded_import_modules.add(module_name)
        expected = module_registry.get(module_name, missing)
        if isinstance(expected, ModuleType):
            token = _binding_token(expected)
            token_digest = canonical_digest(
                "kir.admission-import-binding.v0", token)
            import_module_records.append(
                (module_name, True, expected, token, token_digest))
        else:
            import_module_records.append(
                (module_name, False, None, None, None))
        parent_name, separator, attribute_name = module_name.rpartition(".")
        if separator:
            admit_import_module(parent_name)
            admit_import_attribute(parent_name, attribute_name)

    for module_name, imported_names in admitted_import_requests:
        admit_import_module(module_name)
        for imported_name in imported_names:
            admit_import_attribute(module_name, imported_name)
            admit_import_module(f"{module_name}.{imported_name}")

    admitted_import_modules = tuple(sorted(
        import_module_records, key=lambda item: item[0]))
    admitted_import_attributes = tuple(sorted(
        import_attribute_records, key=lambda item: (item[0], item[2])))

    source_modules_by_name: dict[str, ModuleType] = {
        module.__name__: module
        for module in (
            sys.modules[__name__],
            compiler_module,
            ground_module,
            _authoring_validation_module,
        )
    }
    source_module_names = set(walked_internal_modules)
    source_module_names.update(
        module_name
        for module_name, present, _expected, _token, _token_digest
        in admitted_import_modules
        if present
    )
    source_module_names.update(
        value.__module__
        for _scope, _name, _owner, value, _token, _token_digest in admitted
        if isinstance(value, (FunctionType, type))
    )
    for module_name in sorted(source_module_names):
        module = module_registry.get(module_name)
        path = getattr(module, "__file__", None)
        if isinstance(module, ModuleType) and isinstance(path, str) and path.endswith(
            (".py", ".pyw")
        ):
            source_modules_by_name[module_name] = module
    source_modules = tuple(
        source_modules_by_name[name] for name in sorted(source_modules_by_name))
    open_file = open
    hash_constructor = sha256

    def source_sha256(path: str) -> str:
        digest = hash_constructor()
        with open_file(path, "rb") as source:
            for chunk in iter(lambda: source.read(131072), b""):
                digest.update(chunk)
        return digest.hexdigest()

    source_artifacts: list[tuple[str, ModuleType, str, str]] = []
    for module in source_modules:
        path = getattr(module, "__file__", None)
        if not isinstance(path, str) or not path:
            raise RuntimeError(
                f"sealed admission module has no source path: {module.__name__}")
        source_artifacts.append(
            (module.__name__, module, path, source_sha256(path)))
    admitted_source_artifacts = tuple(source_artifacts)
    profile_digest = canonical_digest(
        "kir.admission-runtime-bindings.v0",
        {
            "absent_globals": tuple({"name": name, "scope": scope}
                                    for scope, name, _namespace in admitted_absent),
            "bindings": tuple({
                "name": name,
                "scope": scope,
                "token_digest": token_digest,
            } for scope, name, _namespace, _expected, _token, token_digest in admitted),
            "import_attributes": tuple({
                "attribute": attribute_name,
                "parent_module": parent_name,
                "state": "present" if present else "absent",
                "token_digest": token_digest,
            } for (
                parent_name,
                _parent,
                attribute_name,
                present,
                _expected,
                _token,
                token_digest,
            ) in admitted_import_attributes),
            "import_modules": tuple({
                "module": module_name,
                "state": "present" if present else "absent",
                "token_digest": token_digest,
            } for module_name, present, _expected, _token, token_digest
                in admitted_import_modules),
            "import_requests": tuple({
                "from": module_name,
                "names": imported_names,
            } for module_name, imported_names in admitted_import_requests),
            "module_attribute_census": len(admitted_module_attributes),
            "module_attributes": tuple({
                "path": (root_name, *chain),
                "scope": scope,
                "state": "present" if present else "absent",
                "token_digest": token_digest,
            } for (
                scope,
                root_name,
                chain,
                _owner,
                _attribute_name,
                present,
                _expected,
                _token,
                token_digest,
                _identity_required,
            ) in admitted_module_attributes),
            "python_cache_tag": sys.implementation.cache_tag or "unknown",
            "source_artifacts": tuple({
                "module": module_name,
                "sha256": source_digest,
            } for module_name, _module, _path, source_digest
                in admitted_source_artifacts),
        },
    )
    token_function = _binding_token

    def verify(*, source_bytes: bool = True) -> None:
        if source_bytes:
            for module_name, module, path, source_digest in admitted_source_artifacts:
                if module_registry.get(module_name, missing) is not module:
                    raise _RuntimeBindingDrift(
                        f"sealed admission module drift: {module_name}")
                if getattr(module, "__file__", None) != path:
                    raise _RuntimeBindingDrift(
                        f"sealed admission source path drift: {module_name}")
                try:
                    current_source_digest = source_sha256(path)
                except (OSError, ValueError) as exc:
                    raise _RuntimeBindingDrift(
                        f"sealed admission source unreadable: {module_name}") from exc
                if current_source_digest != source_digest:
                    raise _RuntimeBindingDrift(
                        f"sealed admission source bytes drift: {module_name}")
        for (
            scope,
            root_name,
            chain,
            owner,
            attribute_name,
            present,
            expected,
            token,
            _digest,
            identity_required,
        ) in admitted_module_attributes:
            current = getattr(owner, attribute_name, missing)
            if not present:
                if current is not missing:
                    raise _RuntimeBindingDrift(
                        "sealed module attribute appeared: "
                        f"{scope}:{root_name}.{'.'.join(chain)}")
                continue
            if identity_required and current is not expected:
                raise _RuntimeBindingDrift(
                    "sealed module attribute drift: "
                    f"{scope}:{root_name}.{'.'.join(chain)}")
            if current is missing or token_function(current) != token:
                raise _RuntimeBindingDrift(
                    "sealed module attribute object drift: "
                    f"{scope}:{root_name}.{'.'.join(chain)}")
        for module_name, present, expected, token, _digest in admitted_import_modules:
            current = module_registry.get(module_name, missing)
            if not present:
                if current is not missing:
                    raise _RuntimeBindingDrift(
                        f"sealed import module appeared: {module_name}")
                continue
            if current is not expected:
                raise _RuntimeBindingDrift(
                    f"sealed import module drift: {module_name}")
            if token_function(current) != token:
                raise _RuntimeBindingDrift(
                    f"sealed import module object drift: {module_name}")
        for (
            parent_name,
            parent,
            attribute_name,
            present,
            expected,
            token,
            _digest,
        ) in admitted_import_attributes:
            current = getattr(parent, attribute_name, missing)
            if not present:
                if current is not missing:
                    raise _RuntimeBindingDrift(
                        "sealed import attribute appeared: "
                        f"{parent_name}:{attribute_name}")
                continue
            if current is not expected:
                raise _RuntimeBindingDrift(
                    "sealed import attribute drift: "
                    f"{parent_name}:{attribute_name}")
            if token_function(current) != token:
                raise _RuntimeBindingDrift(
                    "sealed import attribute object drift: "
                    f"{parent_name}:{attribute_name}")
        for scope, name, namespace in admitted_absent:
            if name in namespace:
                raise _RuntimeBindingDrift(
                    f"new global shadows sealed lookup: {scope}:{name}")
        for scope, name, namespace, expected, _token, _digest in admitted:
            if namespace.get(name, missing) is not expected:
                raise _RuntimeBindingDrift(
                    f"sealed admission binding drift: {scope}:{name}")
        for scope, name, namespace, _expected, token, _digest in admitted:
            if token_function(namespace[name]) != token:
                raise _RuntimeBindingDrift(
                    f"sealed admission object drift: {scope}:{name}")

    verify()
    return (
        verify,
        profile_digest,
        plan_program,
        ground_program,
        admitted_import_requests,
        admitted_module_attribute_manifest,
    )


(
    _RUNTIME_BINDINGS_VERIFY,
    RUNTIME_BINDINGS_DIGEST,
    _CAPTURED_PLAN_PROGRAM,
    _CAPTURED_GROUND_PROGRAM,
    RUNTIME_IMPORT_MANIFEST,
    RUNTIME_MODULE_ATTRIBUTE_MANIFEST,
) = _make_runtime_binding_seal()


def _make_stage_calls(
    verify,
    planner: FunctionType,
    grounder: FunctionType,
):
    def execute_plan(program: dict[str, Any]) -> PlannedProgram:
        verify(source_bytes=False)
        try:
            return planner(program, bulk=False)
        finally:
            verify(source_bytes=False)

    def execute_ground(planned: PlannedProgram) -> GroundedProgram:
        verify(source_bytes=False)
        try:
            return grounder(planned, None)
        finally:
            verify(source_bytes=False)

    return execute_plan, execute_ground


_EXECUTE_PLAN, _EXECUTE_GROUND = _make_stage_calls(
    _RUNTIME_BINDINGS_VERIFY,
    _CAPTURED_PLAN_PROGRAM,
    _CAPTURED_GROUND_PROGRAM,
)


def _design_digest(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        return digest_text(value, field_name)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def _required_design_digest(value: str, field_name: str) -> str:
    admitted = _design_digest(value, field_name)
    if admitted is None:
        raise ValueError(f"{field_name} is required")
    return admitted


def _kir_digest(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _KIR_HEX_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be 64 lowercase hex characters")
    return value


@dataclass(frozen=True, slots=True)
class KirAdmissionRefusalV0:
    """Stable, non-payload-bearing reason for an atomic admission refusal."""

    code: str
    stage: str
    member_id: str | None = None
    underlying_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.code not in _REFUSAL_CODES:
            raise ValueError(f"unknown KIR admission refusal code {self.code!r}")
        if self.stage not in _STAGES:
            raise ValueError(f"unknown KIR admission stage {self.stage!r}")
        if self.member_id is not None:
            object.__setattr__(
                self, "member_id", identifier(self.member_id, "refusal member_id"))
        codes = tuple(sorted(set(self.underlying_codes)))
        if any(not isinstance(code, str) or not code for code in codes):
            raise ValueError("underlying refusal codes must be non-empty strings")
        object.__setattr__(self, "underlying_codes", codes)

    def to_data(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "member_id": self.member_id,
            "stage": self.stage,
            "underlying_codes": self.underlying_codes,
        }


@dataclass(frozen=True, slots=True)
class KirAdmissionMemberReceiptV0:
    """Plan/ground evidence for one exact canonical candidate member."""

    member_id: str
    source_instance_id: str
    candidate_digest: str
    program_digest: str
    trace_digest: str
    entity_count: int
    authored_op_count: int
    planned_op_count: int
    grounded_op_count: int
    plan_digest: str
    ground_digest: str
    resolution_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "member_id", identifier(self.member_id, "member_id"))
        object.__setattr__(
            self,
            "source_instance_id",
            identifier(self.source_instance_id, "source_instance_id"),
        )
        for name in ("candidate_digest", "program_digest", "trace_digest"):
            object.__setattr__(
                self, name, _required_design_digest(getattr(self, name), name))
        object.__setattr__(
            self, "plan_digest", _kir_digest(self.plan_digest, "plan_digest"))
        object.__setattr__(
            self, "ground_digest", _kir_digest(self.ground_digest, "ground_digest"))
        for name in (
            "entity_count",
            "authored_op_count",
            "planned_op_count",
            "grounded_op_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.resolution_count) is not int or self.resolution_count < 0:
            raise ValueError("resolution_count must be a non-negative integer")
        if not (
            self.entity_count
            == self.authored_op_count
            == self.planned_op_count
            == self.grounded_op_count
        ):
            raise ValueError("V0 member admission counts disagree")
        if self.authored_op_count > _AUTHORED_LIMIT:
            raise ValueError("member exceeds current authored operation limit")
        if self.planned_op_count > MAX_VALIDATED_OPS:
            raise ValueError("member exceeds current expanded operation limit")

    def to_data(self) -> dict[str, Any]:
        return {
            "authored_op_count": self.authored_op_count,
            "candidate_digest": self.candidate_digest,
            "entity_count": self.entity_count,
            "ground_digest": self.ground_digest,
            "grounded_op_count": self.grounded_op_count,
            "member_id": self.member_id,
            "plan_digest": self.plan_digest,
            "planned_op_count": self.planned_op_count,
            "program_digest": self.program_digest,
            "resolution_count": self.resolution_count,
            "source_instance_id": self.source_instance_id,
            "trace_digest": self.trace_digest,
        }


@dataclass(frozen=True, slots=True, init=False)
class KirAdmissionReceiptV0:
    """Ephemeral, non-authoritative outcome for one in-process admission.

    There is deliberately no public constructor, pickle/copy reconstruction or
    canonical JSON readback contract.  ``to_data`` is a diagnostic snapshot,
    not a parser format.  Persisted bytes must never be trusted as admission
    evidence; future readback would have to re-run and compare the complete
    admission.  This does not claim to defend against hostile same-process use
    of primitives such as ``object.__new__``.
    """

    SCHEMA: ClassVar[str] = "kir-design-source-admission-receipt/0"

    status: Literal["ACCEPTED", "REFUSED"]
    build_digest: str | None
    requested_candidate_set_digest: str | None
    canonical_partition_plan_digest: str | None
    canonical_candidate_set_digest: str | None
    member_count: int
    entity_count: int
    total_authored_ops: int
    total_planned_ops: int
    total_grounded_ops: int
    members: tuple[KirAdmissionMemberReceiptV0, ...]
    refusal: KirAdmissionRefusalV0 | None
    admission_profile_digest: str
    runtime_bindings_digest: str
    own_runtime_bindings_digest: str
    authority_scope: Literal["OFFLINE_PLAN_GROUND_ONLY"] = AUTHORITY_SCOPE
    evidence_lifetime: Literal[
        "EPHEMERAL_PROCESS_LOCAL_NO_READBACK"
    ] = EVIDENCE_LIFETIME
    ir_version: str = spec.IR_VERSION
    budget_class: Literal["authored"] = BUDGET_AUTHORED
    bulk: Literal[False] = False
    authored_limit: int = _AUTHORED_LIMIT
    expanded_limit: int = MAX_VALIDATED_OPS
    grounding_policy: str = GROUNDING_POLICY
    _receipt_digest: str = field(init=False, repr=False, compare=False)

    def __new__(cls, *_args: Any, **_kwargs: Any) -> KirAdmissionReceiptV0:
        raise ValueError(
            "KIR admission receipts are ephemeral and have no public "
            "constructor or readback")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise ValueError(
            "KIR admission receipts are ephemeral and have no public constructor")

    def __copy__(self) -> Any:
        raise TypeError(
            "KIR admission receipts cannot be copied or reconstructed")

    def __deepcopy__(self, _memo: dict[int, Any]) -> Any:
        raise TypeError(
            "KIR admission receipts cannot be copied or reconstructed")

    def __reduce__(self) -> Any:
        raise TypeError(
            "KIR admission receipts cannot be serialized or reconstructed")

    def __reduce_ex__(self, _protocol: int) -> Any:
        raise TypeError(
            "KIR admission receipts cannot be serialized or reconstructed")

    def __getstate__(self) -> Any:
        raise TypeError(
            "KIR admission receipts cannot be serialized or reconstructed")

    def __setstate__(self, _state: Any) -> None:
        raise TypeError(
            "KIR admission receipts cannot be deserialized or reconstructed")

    def __post_init__(self) -> None:
        if self.status not in {STATUS_ACCEPTED, STATUS_REFUSED}:
            raise ValueError("admission status must be ACCEPTED or REFUSED")
        for name in (
            "build_digest",
            "requested_candidate_set_digest",
            "canonical_partition_plan_digest",
            "canonical_candidate_set_digest",
        ):
            object.__setattr__(self, name, _design_digest(getattr(self, name), name))
        if self.admission_profile_digest != ADMISSION_PROFILE_DIGEST:
            raise ValueError("admission profile digest drift")
        if self.runtime_bindings_digest != RUNTIME_BINDINGS_DIGEST:
            raise ValueError("admission runtime bindings digest drift")
        if self.own_runtime_bindings_digest != OWN_RUNTIME_BINDINGS_DIGEST:
            raise ValueError("own admission runtime bindings digest drift")
        if (
            self.authority_scope != AUTHORITY_SCOPE
            or self.evidence_lifetime != EVIDENCE_LIFETIME
            or self.ir_version != spec.IR_VERSION
            or self.budget_class != BUDGET_AUTHORED
            or self.bulk is not False
            or self.authored_limit != _AUTHORED_LIMIT
            or self.expanded_limit != MAX_VALIDATED_OPS
            or self.grounding_policy != GROUNDING_POLICY
        ):
            raise ValueError("admission policy fields drifted from the current profile")
        members = tuple(self.members)
        if any(type(item) is not KirAdmissionMemberReceiptV0 for item in members):
            raise TypeError("admission members must be exact member receipts")
        members = tuple(sorted(members, key=lambda item: item.member_id))
        if len(members) != len({item.member_id for item in members}):
            raise ValueError("duplicate admitted member_id")
        object.__setattr__(self, "members", members)
        for name in (
            "member_count",
            "entity_count",
            "total_authored_ops",
            "total_planned_ops",
            "total_grounded_ops",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.status == STATUS_ACCEPTED:
            if self.build_digest is None:
                raise ValueError("accepted admission must bind a BuildResult digest")
            if (
                self.canonical_partition_plan_digest is None
                or self.canonical_candidate_set_digest is None
            ):
                raise ValueError("accepted admission must bind canonical candidates")
            if self.refusal is not None:
                raise ValueError("accepted admission cannot carry a refusal")
            if not members or self.member_count != len(members):
                raise ValueError("accepted admission member census mismatch")
            expected = (
                sum(item.entity_count for item in members),
                sum(item.authored_op_count for item in members),
                sum(item.planned_op_count for item in members),
                sum(item.grounded_op_count for item in members),
            )
            got = (
                self.entity_count,
                self.total_authored_ops,
                self.total_planned_ops,
                self.total_grounded_ops,
            )
            if got != expected:
                raise ValueError("accepted admission aggregate census mismatch")
        else:
            if type(self.refusal) is not KirAdmissionRefusalV0:
                raise ValueError("refused admission needs one exact refusal")
            if members or any((
                self.member_count,
                self.entity_count,
                self.total_authored_ops,
                self.total_planned_ops,
                self.total_grounded_ops,
            )):
                raise ValueError("refused pack admission cannot admit partial members")
        object.__setattr__(
            self,
            "_receipt_digest",
            canonical_digest("kir.admission-receipt.v0", self.to_data()),
        )

    @property
    def receipt_digest(self) -> str:
        return self._receipt_digest

    @property
    def accepted(self) -> bool:
        return self.status == STATUS_ACCEPTED

    def to_data(self) -> dict[str, Any]:
        """Return diagnostic data with deliberately no inverse/readback API."""

        return {
            "admission_profile_digest": self.admission_profile_digest,
            "authored_limit": self.authored_limit,
            "authority_scope": self.authority_scope,
            "budget_class": self.budget_class,
            "build_digest": self.build_digest,
            "bulk": self.bulk,
            "canonical_candidate_set_digest": self.canonical_candidate_set_digest,
            "canonical_partition_plan_digest": self.canonical_partition_plan_digest,
            "entity_count": self.entity_count,
            "evidence_lifetime": self.evidence_lifetime,
            "expanded_limit": self.expanded_limit,
            "grounding_policy": self.grounding_policy,
            "ir_version": self.ir_version,
            "member_count": self.member_count,
            "members": tuple(item.to_data() for item in self.members),
            "own_runtime_bindings_digest": self.own_runtime_bindings_digest,
            "refusal": None if self.refusal is None else self.refusal.to_data(),
            "requested_candidate_set_digest": self.requested_candidate_set_digest,
            "runtime_bindings_digest": self.runtime_bindings_digest,
            "schema": self.SCHEMA,
            "status": self.status,
            "total_authored_ops": self.total_authored_ops,
            "total_grounded_ops": self.total_grounded_ops,
            "total_planned_ops": self.total_planned_ops,
        }


def _make_receipt_minter(receipt_type: type[KirAdmissionReceiptV0]):
    """Create the one closure that can initialize the non-public contract."""

    new_instance = object.__new__
    set_attribute = object.__setattr__
    validate = receipt_type.__post_init__
    required = frozenset({
        "admission_profile_digest",
        "build_digest",
        "canonical_candidate_set_digest",
        "canonical_partition_plan_digest",
        "entity_count",
        "member_count",
        "members",
        "own_runtime_bindings_digest",
        "refusal",
        "requested_candidate_set_digest",
        "runtime_bindings_digest",
        "status",
        "total_authored_ops",
        "total_grounded_ops",
        "total_planned_ops",
    })
    defaults = {
        "authority_scope": AUTHORITY_SCOPE,
        "authored_limit": _AUTHORED_LIMIT,
        "budget_class": BUDGET_AUTHORED,
        "bulk": False,
        "evidence_lifetime": EVIDENCE_LIFETIME,
        "expanded_limit": MAX_VALIDATED_OPS,
        "grounding_policy": GROUNDING_POLICY,
        "ir_version": spec.IR_VERSION,
    }
    admitted_names = required | frozenset(defaults)

    def mint(**values: Any) -> KirAdmissionReceiptV0:
        names = frozenset(values)
        if names - admitted_names:
            raise TypeError("unknown internal admission receipt fields")
        missing = required - names
        if missing:
            raise TypeError("missing internal admission receipt fields")
        instance = new_instance(receipt_type)
        for name, value in {**defaults, **values}.items():
            set_attribute(instance, name, value)
        validate(instance)
        return instance

    return mint


class _EvidenceMismatch(ValueError):
    pass


class _StageRefusal(ValueError):
    def __init__(self, stage: Literal["plan", "ground"], refusal: KirRefusal):
        super().__init__(stage)
        self.stage = stage
        self.refusal = refusal


def _recomputed_candidate_digest(candidate_set: KirCandidateSetV0) -> str:
    return canonical_digest("kir.candidate-set.v0", candidate_set.to_data())


def _recomputed_member_digest(member: KirCandidateMemberV0) -> str:
    return canonical_digest("kir.candidate-member.v0", member.to_data())


def _refused(
    *,
    receipt_factory,
    code: str,
    stage: str,
    build_digest: str | None,
    requested_digest: str | None,
    partition_digest: str | None = None,
    canonical_digest_value: str | None = None,
    member_id: str | None = None,
    underlying_codes: tuple[str, ...] = (),
) -> KirAdmissionReceiptV0:
    return receipt_factory(
        status=STATUS_REFUSED,
        build_digest=build_digest,
        requested_candidate_set_digest=requested_digest,
        canonical_partition_plan_digest=partition_digest,
        canonical_candidate_set_digest=canonical_digest_value,
        member_count=0,
        entity_count=0,
        total_authored_ops=0,
        total_planned_ops=0,
        total_grounded_ops=0,
        members=(),
        refusal=KirAdmissionRefusalV0(
            code=code,
            stage=stage,
            member_id=member_id,
            underlying_codes=underlying_codes,
        ),
        admission_profile_digest=ADMISSION_PROFILE_DIGEST,
        runtime_bindings_digest=RUNTIME_BINDINGS_DIGEST,
        own_runtime_bindings_digest=OWN_RUNTIME_BINDINGS_DIGEST,
    )


def _design_error_codes(exc: BaseException) -> tuple[str, ...]:
    code = getattr(exc, "code", None)
    return (code,) if isinstance(code, str) and code else ()


def _kir_error_codes(exc: KirRefusal) -> tuple[str, ...]:
    return tuple(
        diagnostic.code
        for diagnostic in exc.diagnostics
        if isinstance(diagnostic.code, str) and diagnostic.code
    )


def _verify_candidate_against_build(
    build: BuildResultV0,
    candidate_set: KirCandidateSetV0,
) -> None:
    if candidate_set.build_digest != build.manifest.build_digest:
        raise _EvidenceMismatch("canonical candidate does not bind BuildResult")
    if candidate_set.entity_count != build.manifest.entity_count:
        raise _EvidenceMismatch("canonical candidate entity census mismatch")
    if set(candidate_set.accounting) != set(build.manifest.entity_ids):
        raise _EvidenceMismatch("canonical candidate accounting mismatch")
    by_id = {item.logical_id: item for item in build.entities}
    instance_ids = set(build.manifest.instance_ids)
    for member in candidate_set.members:
        if member.member_id != stable_logical_id("member", member.source_instance_id):
            raise _EvidenceMismatch("candidate member identity is not canonical")
        if member.source_instance_id not in instance_ids:
            raise _EvidenceMismatch("candidate names an unknown source instance")
        if _recomputed_member_digest(member) != member.candidate_digest:
            raise _EvidenceMismatch("candidate member cached digest mismatch")
        for entity_id in member.entity_ids:
            entity = by_id.get(entity_id)
            if entity is None:
                raise _EvidenceMismatch("candidate names an unknown BuildEntity")
            if (
                member.entity_content_digests[entity_id]
                != build.manifest.entity_content_digests[entity_id]
            ):
                raise _EvidenceMismatch("candidate content digest mismatch")
            if candidate_set.accounting[entity_id] != member.member_id:
                raise _EvidenceMismatch("candidate accounting/member mismatch")
            if member.entity_to_op[entity_id] != stable_logical_id("op", entity_id):
                raise _EvidenceMismatch("candidate operation identity is not canonical")
        dependent_origins = {
            by_id[entity_id].origin.instance_id
            for entity_id in member.entity_ids
            if by_id[entity_id].dependencies
        }
        if dependent_origins != {member.source_instance_id}:
            raise _EvidenceMismatch("candidate source instance disagrees with closure origins")


def _member_receipt(
    member: KirCandidateMemberV0,
    *,
    _plan_stage=_EXECUTE_PLAN,
    _ground_stage=_EXECUTE_GROUND,
) -> KirAdmissionMemberReceiptV0:
    program = member.to_program()
    try:
        planned = _plan_stage(program)
    except KirRefusal as exc:
        raise _StageRefusal("plan", exc) from exc
    if type(planned) is not PlannedProgram:
        raise _EvidenceMismatch("planner returned the wrong concrete type")
    if planned.family is not ProgramFamily.WRITE or planned.bulk is not False:
        raise _EvidenceMismatch("candidate entered the wrong KIR policy family")
    if (
        planned.source_op_count != member.authored_op_count
        or planned.source_op_count > _AUTHORED_LIMIT
        or len(planned.ops) != member.expanded_op_count
        or len(planned.ops) > MAX_VALIDATED_OPS
    ):
        raise _EvidenceMismatch("candidate/planned operation census mismatch")
    if planned.to_ops() != program["ops"]:
        raise _EvidenceMismatch("planned payload differs from canonical candidate bytes")
    program_op_ids = tuple(op["id"] for op in program["ops"])
    planned_op_ids = tuple(op.op_id for op in planned.ops)
    if planned_op_ids != program_op_ids:
        raise _EvidenceMismatch("planner changed candidate operation identity/order")
    if set(planned_op_ids) != set(member.op_to_entity):
        raise _EvidenceMismatch("planned operations disagree with source trace")

    try:
        grounded = _ground_stage(planned)
    except KirRefusal as exc:
        raise _StageRefusal("ground", exc) from exc
    if type(grounded) is not GroundedProgram or grounded.planned is not planned:
        raise _EvidenceMismatch("grounder returned an unrelated typed parent")
    grounded_op_ids = tuple(op.op_id for op in grounded.ops)
    if grounded_op_ids != planned_op_ids or len(grounded.ops) != member.expanded_op_count:
        raise _EvidenceMismatch("grounded operations disagree with planned identity")
    if any(item.via not in {"ref", "doc_default"} for item in grounded.resolutions):
        raise _EvidenceMismatch("V0 admission unexpectedly required a model snapshot")

    trace_digest = canonical_digest(
        "kir.candidate-trace.v0",
        {
            "entity_content_digests": member.entity_content_digests,
            "entity_ids": member.entity_ids,
            "entity_to_op": member.entity_to_op,
            "op_to_entity": member.op_to_entity,
        },
    )
    return KirAdmissionMemberReceiptV0(
        member_id=member.member_id,
        source_instance_id=member.source_instance_id,
        candidate_digest=member.candidate_digest,
        program_digest=canonical_digest("kir.candidate-program.v0", member.program),
        trace_digest=trace_digest,
        entity_count=len(member.entity_ids),
        authored_op_count=member.authored_op_count,
        planned_op_count=len(planned.ops),
        grounded_op_count=len(grounded.ops),
        plan_digest=planned.plan_digest,
        ground_digest=grounded.ground_digest,
        resolution_count=len(grounded.resolutions),
    )


def _admit_kir_candidates_core(
    build: BuildResultV0,
    supplied: KirCandidateSetV0 | None,
    *,
    canonical_hash,
    dry_planner,
    candidate_planner,
    candidate_verifier,
    member_admitter,
    refused_factory,
    receipt_factory,
    design_error_codes,
    kir_error_codes,
) -> KirAdmissionReceiptV0:
    """Atomically re-derive, plan and ground one complete candidate pack.

    Expected input/source/KIR refusals are returned as deterministic ``REFUSED``
    receipts.  A refused pack has no admitted member receipts, even when the
    failure occurred after earlier members had been evaluated.
    """

    if type(build) is not BuildResultV0:
        return refused_factory(
            code=INVALID_CONTRACT,
            stage="input",
            build_digest=None,
            requested_digest=None,
        )
    build_digest = build.manifest.build_digest
    try:
        recomputed_build_digest = canonical_hash(
            "kir.build-manifest.v0", build.manifest.to_data())
    except Exception:
        return refused_factory(
            code=INVALID_CONTRACT,
            stage="input",
            build_digest=build_digest,
            requested_digest=None,
        )
    if recomputed_build_digest != build_digest:
        return refused_factory(
            code=INVALID_CONTRACT,
            stage="input",
            build_digest=build_digest,
            requested_digest=None,
        )
    if supplied is not None and type(supplied) is not KirCandidateSetV0:
        return refused_factory(
            code=INVALID_CONTRACT,
            stage="input",
            build_digest=build_digest,
            requested_digest=None,
        )

    requested_digest: str | None = None
    if supplied is not None:
        try:
            requested_digest = canonical_hash(
                "kir.candidate-set.v0", supplied.to_data())
        except Exception:
            return refused_factory(
                code=INVALID_CONTRACT,
                stage="input",
                build_digest=build_digest,
                requested_digest=None,
            )
        if requested_digest != supplied.candidate_set_digest:
            return refused_factory(
                code=INVALID_CONTRACT,
                stage="input",
                build_digest=build_digest,
                requested_digest=requested_digest,
            )
        if supplied.build_digest != build_digest:
            return refused_factory(
                code=STALE_CANDIDATE_BUILD,
                stage="canonical",
                build_digest=build_digest,
                requested_digest=requested_digest,
            )

    try:
        partition = dry_planner(build)
        canonical_set = candidate_planner(build, partition=partition)
    except DesignSourceError as exc:
        return refused_factory(
            code=SOURCE_LOWERING_REFUSED,
            stage="source",
            build_digest=build_digest,
            requested_digest=requested_digest,
            underlying_codes=design_error_codes(exc),
        )
    except Exception:
        return refused_factory(
            code=INTERNAL_REFUSED,
            stage="source",
            build_digest=build_digest,
            requested_digest=requested_digest,
        )

    partition_digest = partition.plan_digest
    canonical_set_digest = canonical_hash(
        "kir.candidate-set.v0", canonical_set.to_data())
    if (
        canonical_set_digest != canonical_set.candidate_set_digest
        or canonical_set.partition_plan_digest != partition_digest
    ):
        return refused_factory(
            code=EVIDENCE_MISMATCH,
            stage="evidence",
            build_digest=build_digest,
            requested_digest=requested_digest,
            partition_digest=partition_digest,
            canonical_digest_value=canonical_set_digest,
        )
    if supplied is not None and requested_digest != canonical_set_digest:
        return refused_factory(
            code=NONCANONICAL_CANDIDATE_SET,
            stage="canonical",
            build_digest=build_digest,
            requested_digest=requested_digest,
            partition_digest=partition_digest,
            canonical_digest_value=canonical_set_digest,
        )

    try:
        candidate_verifier(build, canonical_set)
    except _EvidenceMismatch:
        return refused_factory(
            code=EVIDENCE_MISMATCH,
            stage="evidence",
            build_digest=build_digest,
            requested_digest=requested_digest,
            partition_digest=partition_digest,
            canonical_digest_value=canonical_set_digest,
        )

    staged: list[KirAdmissionMemberReceiptV0] = []
    for member in canonical_set.members:
        try:
            staged.append(member_admitter(member))
        except _StageRefusal as exc:
            refusal_code = (
                KIR_PLAN_REFUSED if exc.stage == "plan" else KIR_GROUND_REFUSED)
            return refused_factory(
                code=refusal_code,
                stage=exc.stage,
                build_digest=build_digest,
                requested_digest=requested_digest,
                partition_digest=partition_digest,
                canonical_digest_value=canonical_set_digest,
                member_id=member.member_id,
                underlying_codes=kir_error_codes(exc.refusal),
            )
        except _EvidenceMismatch:
            return refused_factory(
                code=EVIDENCE_MISMATCH,
                stage="evidence",
                build_digest=build_digest,
                requested_digest=requested_digest,
                partition_digest=partition_digest,
                canonical_digest_value=canonical_set_digest,
                member_id=member.member_id,
            )
        except Exception:
            return refused_factory(
                code=INTERNAL_REFUSED,
                stage="evidence",
                build_digest=build_digest,
                requested_digest=requested_digest,
                partition_digest=partition_digest,
                canonical_digest_value=canonical_set_digest,
                member_id=member.member_id,
            )

    entity_count = sum(item.entity_count for item in staged)
    if entity_count != build.manifest.entity_count:
        return refused_factory(
            code=EVIDENCE_MISMATCH,
            stage="evidence",
            build_digest=build_digest,
            requested_digest=requested_digest,
            partition_digest=partition_digest,
            canonical_digest_value=canonical_set_digest,
        )
    return receipt_factory(
        status=STATUS_ACCEPTED,
        build_digest=build_digest,
        requested_candidate_set_digest=requested_digest,
        canonical_partition_plan_digest=partition_digest,
        canonical_candidate_set_digest=canonical_set_digest,
        member_count=len(staged),
        entity_count=entity_count,
        total_authored_ops=sum(item.authored_op_count for item in staged),
        total_planned_ops=sum(item.planned_op_count for item in staged),
        total_grounded_ops=sum(item.grounded_op_count for item in staged),
        members=tuple(staged),
        refusal=None,
        admission_profile_digest=ADMISSION_PROFILE_DIGEST,
        runtime_bindings_digest=RUNTIME_BINDINGS_DIGEST,
        own_runtime_bindings_digest=OWN_RUNTIME_BINDINGS_DIGEST,
    )


def _make_public_admitter(
    core,
    member_admitter,
    runtime_verifiers,
    refused_builder,
    receipt_factory,
    canonical_hash,
    dry_planner,
    candidate_planner,
    candidate_verifier,
    design_error_codes,
    kir_error_codes,
    build_type,
    candidate_type,
):
    def verify_runtime() -> None:
        for verifier in runtime_verifiers:
            verifier()

    def refused_factory(**values) -> KirAdmissionReceiptV0:
        return refused_builder(receipt_factory=receipt_factory, **values)

    def runtime_refusal(
        build: Any,
        supplied: Any,
        prior: KirAdmissionReceiptV0 | None = None,
    ) -> KirAdmissionReceiptV0:
        build_digest = (
            build.manifest.build_digest if type(build) is build_type else None)
        requested_digest = (
            supplied.candidate_set_digest
            if type(supplied) is candidate_type
            else None
        )
        return refused_factory(
            code=INTERNAL_REFUSED,
            stage="evidence",
            build_digest=build_digest,
            requested_digest=requested_digest,
            partition_digest=(
                None if prior is None else prior.canonical_partition_plan_digest),
            canonical_digest_value=(
                None if prior is None else prior.canonical_candidate_set_digest),
        )

    def admit(
        build: BuildResultV0,
        supplied: KirCandidateSetV0 | None = None,
    ) -> KirAdmissionReceiptV0:
        try:
            verify_runtime()
        except Exception:
            return runtime_refusal(build, supplied)
        receipt = core(
            build,
            supplied,
            canonical_hash=canonical_hash,
            dry_planner=dry_planner,
            candidate_planner=candidate_planner,
            candidate_verifier=candidate_verifier,
            member_admitter=member_admitter,
            refused_factory=refused_factory,
            receipt_factory=receipt_factory,
            design_error_codes=design_error_codes,
            kir_error_codes=kir_error_codes,
        )
        try:
            verify_runtime()
        except Exception:
            return runtime_refusal(build, supplied, receipt)
        return receipt

    admit.__name__ = "admit_kir_candidates"
    admit.__qualname__ = "admit_kir_candidates"
    admit.__doc__ = core.__doc__
    return admit


_RECEIPT_MINTER = _make_receipt_minter(KirAdmissionReceiptV0)
_OWN_SEAL_ROOT_NAMES = tuple(sorted(
    name
    for name, value in globals().items()
    if (
        isinstance(value, (FunctionType, type))
        and getattr(value, "__module__", None) == __name__
        and name not in {"_make_receipt_minter", "_RECEIPT_MINTER"}
    )
))
(
    _OWN_BINDINGS_FINALIZE,
    OWN_RUNTIME_BINDINGS_DIGEST,
) = _make_own_runtime_binding_seal(
    _OWN_SEAL_ROOT_NAMES,
    deferred_names=frozenset({
        "ADMISSION_PROFILE_DIGEST",
        "OWN_RUNTIME_BINDINGS_DIGEST",
    }),
)

ADMISSION_PROFILE_DIGEST = canonical_digest(
    "kir.admission-profile.v0",
    {
        "algorithm_version": ADMISSION_ALGORITHM_VERSION,
        "authority_scope": AUTHORITY_SCOPE,
        "authored_limit": _AUTHORED_LIMIT,
        "budget_class": _BUDGET_CLASS,
        "bulk": False,
        "expanded_limit": MAX_VALIDATED_OPS,
        "evidence_lifetime": EVIDENCE_LIFETIME,
        "grounding_policy": GROUNDING_POLICY,
        "ir_version": spec.IR_VERSION,
        "own_runtime_bindings_digest": OWN_RUNTIME_BINDINGS_DIGEST,
        "runtime_bindings_digest": RUNTIME_BINDINGS_DIGEST,
    },
)
_OWN_RUNTIME_BINDINGS_VERIFY = _OWN_BINDINGS_FINALIZE()


admit_kir_candidates = _make_public_admitter(
    _admit_kir_candidates_core,
    _member_receipt,
    (_RUNTIME_BINDINGS_VERIFY, _OWN_RUNTIME_BINDINGS_VERIFY),
    _refused,
    _RECEIPT_MINTER,
    canonical_digest,
    plan_dry_lowering,
    plan_kir_candidates,
    _verify_candidate_against_build,
    _design_error_codes,
    _kir_error_codes,
    BuildResultV0,
    KirCandidateSetV0,
)
del _RECEIPT_MINTER
del _make_receipt_minter


__all__ = [
    "ADMISSION_ALGORITHM_VERSION",
    "ADMISSION_PROFILE_DIGEST",
    "AUTHORITY_SCOPE",
    "EVIDENCE_LIFETIME",
    "EVIDENCE_MISMATCH",
    "GROUNDING_POLICY",
    "INTERNAL_REFUSED",
    "INVALID_CONTRACT",
    "KIR_GROUND_REFUSED",
    "KIR_PLAN_REFUSED",
    "KirAdmissionMemberReceiptV0",
    "KirAdmissionReceiptV0",
    "KirAdmissionRefusalV0",
    "NONCANONICAL_CANDIDATE_SET",
    "OWN_RUNTIME_BINDINGS_DIGEST",
    "RUNTIME_BINDINGS_DIGEST",
    "RUNTIME_IMPORT_MANIFEST",
    "RUNTIME_MODULE_ATTRIBUTE_MANIFEST",
    "SOURCE_LOWERING_REFUSED",
    "STALE_CANDIDATE_BUILD",
    "STATUS_ACCEPTED",
    "STATUS_REFUSED",
    "admit_kir_candidates",
]
