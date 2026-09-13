"""AN ADDRESS WITH A DECLARED SPACE — and a map between two spaces.

WHY. A building in this tree does not have one address but three, and all
three are bare `str`:

    op_id        `w1`, `p0/wall1`  — the OPERATION identifier that the model
                                     wrote; the PROGRAM path addresses
                                     everything by it (`design_check._program_
                                     nodes`: «`source_element_id` is the `id`
                                     of the operation itself»)
    element_id   `9001`            — what Revit addresses by; the PARSE path,
                                     `SpatialModel` from `checker/extractor`,
                                     `building_graph`, the `fold` tree
    synthetic    `apt_0_0_hall`    — what the generator made up
                                     (`modeling/generator/*`), not the
                                     address of anything existing in the
                                     document

All three share the same type, and nothing distinguishes them. Measured
15.08: `SpatialModel.id` is `str` in six classes, `design/coherence.Elem.oid`
is `str`, and it holds the OPERATION's id, while `generator/*` holds
synthetics.

WHAT THIS COST, IN NUMBERS. `design_check.compare_geometry` intersects the
`id` sets of two models. On a REBUILD, both sides carry `element_id` and the
intersection is meaningful. On an AUTHORIAL program, one side carries `w1`,
the other `9001`, **the intersection is EMPTY — and the comparator silently
returns an empty list of discrepancies, which reads as "everything
matched"**. This is our named class in pure form: a value is declared in one
place, read in another, and nothing forces them to agree.

WHAT THIS MODULE DOES NOT DO. It does NOT rewrite the four worlds onto a new
type: that would be a change of thousands of lines for a type needed exactly
at the boundaries. It declares a space WHERE THE TWO WORLDS MEET, and
refuses when they are reconciled silently.

## WHY `__eq__` DOES NOT REFUSE, BUT `same_as` DOES

The requirement "comparing addresses from different spaces must REFUSE" is
correct in substance and unenforceable in `__eq__`: `Address` objects are put
into a `set`/`dict`, and there `__eq__` is called on a HASH COLLISION between
arbitrary elements, and an exception from there would bring down an ordinary
dictionary lookup out of the blue. Hence:

* `__eq__` is structural (the space is part of equality, different spaces
  are simply unequal). Containers work;
* `same_as()` is an EXPLICIT comparison that refuses with
  `AddressSpaceError`, and it is exactly this that stands at the
  boundaries where a mistake is costly;
* `assert_one_space()` is the same for sets: two sets of addresses can be
  reconciled only after naming their space.

The separation is named here, rather than in someone's memory, because "why
doesn't this refuse" is the reader's first question.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

from kir.registry_base import EffectKind, IdentityCardinality

__all__ = [
    "Address",
    "AddressSpace",
    "AddressSpaceError",
    "IdentityMissingError",
    "assert_one_space",
    "created_identity_fields",
    "element_addresses",
    "identity_field_reasons",
    "receipt_map",
]


class AddressSpace(str, Enum):
    """Address spaces occurring in this tree. COMPLETE BY CONSTRUCTION.

    Completeness is not held by a promise: there is no fourth space in the
    tree, because an address is born in exactly three places — the author
    writes it (`op_id`), Revit returns it (`element_id`), the generator
    makes it up (`synthetic`). Should a fourth appear, it MUST appear HERE,
    otherwise `Address` cannot express it and the code will not build.
    """

    OP_ID = "op_id"
    ELEMENT_ID = "element_id"
    SYNTHETIC = "synthetic"


class AddressSpaceError(TypeError):
    """Two addresses were reconciled silently. This is a REFUSAL, not "did not match"."""


class IdentityMissingError(ValueError):
    """A writing op brought no identity. An empty map would be a lie."""


@dataclass(frozen=True)
class Address:
    """An element's address TOGETHER WITH its space.

    `value` is always a string: `element_id` comes from Revit sometimes as
    a number, sometimes as a digit string (see
    `registry_base._result_element_id`), and storing two forms of the same
    address would mean keeping two keys for one thing.
    """

    space: AddressSpace
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.space, AddressSpace):
            raise AddressSpaceError(
                "пространство адреса обязано быть типизированным, "
                f"получено {type(self.space).__name__}")
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("адрес не бывает пустым")

    def same_as(self, other: "Address") -> bool:
        """Compare EXPLICITLY. Different spaces are a refusal, not `False`.

        `w1` and `9001` are not "different elements" — they are claims of a
        DIFFERENT KIND, and an answer of `False` to such a question is
        indistinguishable from an honest mismatch.
        """

        if not isinstance(other, Address):
            raise AddressSpaceError("сравнивать адрес можно только с адресом")
        if self.space is not other.space:
            raise AddressSpaceError(
                f"адреса из РАЗНЫХ пространств: {self.space.value} против "
                f"{other.space.value}. Их нельзя сравнивать — их надо "
                f"ПЕРЕВЕСТИ (`receipt_map`)")
        return self.value == other.value

    def __str__(self) -> str:
        return f"{self.space.value}:{self.value}"


def assert_one_space(addresses: Iterable[Address],
                     expected: AddressSpace | None = None) -> AddressSpace:
    """The space of a set of addresses, or a REFUSAL. An empty set is a refusal.

    An empty set refuses deliberately: "the space of an empty set" is a
    zero of a quantity nobody counted here, and taking it for agreement
    would mean repeating exactly the defect this module was written
    against.
    """

    seen = {a.space for a in addresses}
    if not seen:
        raise AddressSpaceError(
            "пространство пустого множества адресов не определено")
    if len(seen) > 1:
        raise AddressSpaceError(
            "множество смешивает пространства: "
            + ", ".join(sorted(s.value for s in seen)))
    only = seen.pop()
    if expected is not None and only is not expected:
        raise AddressSpaceError(
            f"ожидалось пространство {expected.value}, получено {only.value}")
    return only


# ─── THE `op_id → element_id` MAP, DERIVED FROM THE REGISTRY ─────────────────
#
# The identity field DIFFERS between ops, and a handwritten list of these
# names is a second table that must match the registry. Measured 15.08 on
# 65 writing ops: `id` for 59, `segment_ids` for 4, `deleted_id` for 1,
# `moved_ids` for 1. Anyone who writes these names by hand misses exactly on
# the rare ones — and the miss is silent.


@lru_cache(maxsize=1)
def created_identity_fields() -> tuple[str, ...]:
    """Fields carrying the identity of the CREATED. COMPLETE BY CONSTRUCTION.

    The authority is the registry: the `ResultSpec.identity_field` of every
    op with `EffectKind.CREATE` is taken. A new creating op lands here BY
    ITSELF; it cannot be forgotten, because there is no longer a list that
    could be forgotten.

    THE CACHE IS NOT DECORATION. `witness_feed.outcome_label` calls this
    function on EVERY result row, and there can be up to
    `_MAX_OPS_PER_RECORD` rows per record: without the cache this is a scan
    of 69 registry ops per row, i.e. a cost growing with n, inside a body
    that runs in a loop. The registry does not change during the process's
    lifetime, so the answer is computed once.

    Whoever replaces `spec.OPS` (registry tests) must call
    `created_identity_fields.cache_clear()` — otherwise they get the answer
    for the previous registry and mistake it for a property of the
    replacement.
    """

    from kir import spec

    return tuple(sorted({
        op.result.identity_field
        for op in spec.OPS.values()
        if op.effect is EffectKind.CREATE and op.result.identity_field}))


def identity_field_reasons() -> dict[str, str]:
    """Fields that carry the created for NO op at all — each with a reason.

    The counterpart to `created_identity_fields`: together they cover all
    the registry's identity fields WITHOUT GAPS and WITHOUT OVERLAP, and a
    test holds this.

    🔴 THE "WITHOUT OVERLAP" CONDITION IS NOT PEDANTRY — IT CAUGHT AN ERROR
    BY THIS FUNCTION'S OWN AUTHOR. The first version took "fields of
    non-CREATE ops" and returned `id` among the non-creating ones:
    `change_type` is `MUTATE` and carries `id`, the very same `id` by which
    59 creating ops name what they created. The field belongs to BOTH
    sets, and the pair stopped covering the registry as a partition. So
    here it is subtracted instead: non-creating means a field that never
    once carries the created.
    """

    from kir import spec

    created = set(created_identity_fields())
    reasons: dict[str, str] = {}
    for op in spec.OPS.values():
        field = op.result.identity_field
        if not field or field in created:
            continue
        if op.effect is EffectKind.DELETE:
            reasons[field] = (
                "удалённого элемента в модели уже нет — следить не за чем")
        elif op.effect is EffectKind.MUTATE:
            reasons[field] = (
                "элемент существовал до хода: правка не оставляет НОВОГО "
                "следа, а реестр отвечает на «что я оставил»")
        else:
            reasons[field] = f"эффект {op.effect.value}: созданного нет"
    return reasons


def element_addresses(ops: Sequence[Mapping[str, Any]],
                      payload: Mapping[str, Any],
                      *, strict: bool = True) -> dict[str, tuple[Address, ...]]:
    """The map "operation id → addresses of the Revit elements it created".

    The sole producer of this map in the tree. The identity field is taken
    FROM THE REGISTRY per operation (`OpSpec.result.identity_field`), not
    guessed by name: for `create_wall` it is `id`, for `route_pipe_system`
    it is `segment_ids`, for `delete` it is `deleted_id`. A reader that
    knows only `"id"` loses six operations out of 65 and never learns of
    it.

    `ops` is the program AS WRITTEN (`{"op": ..., "id": ...}`); `payload`
    is the receipt's `result`, a dict keyed by operation id.

    `strict=True` (the default): a writing op with no identity raises
    `IdentityMissingError` with the names. An empty map on a successful
    program would be a lie of the same kind as a silent intersection of
    empty sets. `strict=False` exists for readers of already-saved
    receipts, where some rows were recorded before the contract existed;
    such a reader must name what it softened.
    """

    from kir import spec

    out: dict[str, tuple[Address, ...]] = {}
    missing: list[str] = []
    for index, op in enumerate(ops):
        name = str(op.get("op", ""))
        ospec = spec.OPS.get(name)
        if ospec is None:
            continue
        result = ospec.result
        if result.identity_cardinality is IdentityCardinality.NONE:
            continue                      # query: there is no identity by contract
        raw_id = op.get("id")
        oid = str(raw_id) if raw_id not in (None, "") else f"#{index}"
        row = payload.get(oid)
        if not isinstance(row, Mapping) or not result.identity_present(row):
            missing.append(f"{oid} ({name}, ждали `{result.identity_field}`)")
            continue
        value = row[result.identity_field]
        values = ([value] if result.identity_cardinality is IdentityCardinality.ONE
                  else list(value))
        out[oid] = tuple(Address(AddressSpace.ELEMENT_ID, str(v)) for v in values)
    if missing and strict:
        raise IdentityMissingError(
            "идентичности нет у операций: " + "; ".join(missing)
            + ". Успешная пишущая программа обязана нести её у КАЖДОЙ "
              "(`serving._result_contract_diagnostic`, KIR-X008)")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 🔴 THERE USED TO BE A SECOND FORM OF THE MAP HERE — `op_to_element_ids` —
# AND IT WAS REMOVED ON 15.08.
#
# Two functions doing one job, born ON THE SAME DAY by two parallel waves: a
# flat `dict[str, str]` (earlier) and a list-valued `dict[str, list[str]]`
# (later). The live path called the list-valued one; the flat one had NOT A
# SINGLE product consumer — only its own tests and two lines of prose in
# `design_check`.
#
# WHY IT WAS REMOVED RATHER THAN LEFT AS A WRAPPER. A flat dict physically
# cannot carry multiple identity, so translating into it SILENTLY dropped
# operations — measured on the registry 15.08: **5 writing ops out of 66
# have arity MANY** (`create_pipe_system`, `create_room_separator`,
# `move_elements`, `route_duct_system`, `route_pipe_system`), and all five
# vanished from the map with not a single diagnostic. Leaving such a
# function as a wrapper with an honest docstring would have meant keeping
# exactly the silent outcome the whole compiler is built against — only
# with documentation. Documented data loss remains data loss: the docstring
# is read by the function's author, not by whoever writes
# `for oid, eid in map.items()` a month later.
#
# WHAT REPLACES IT. Nothing: `receipt_map` yields a LIST at any arity, and
# a caller that needs exactly one element must say so explicitly —
# `addrs, = receipt_map(...)[oid]` will refuse where there turn out to be
# two.
#
# This block stands here, and not in git history, because "why isn't there
# a flat form here" is the first question of whoever comes to add it back.
# ─────────────────────────────────────────────────────────────────────────────


def receipt_map(ops: Sequence[Mapping[str, Any]],
                payload: Mapping[str, Any],
                *, strict: bool = False) -> dict[str, list[str]]:
    """The map for the RECEIPT the model reads: `op_id → [element_id, …]`.

    A LIST ALWAYS, EVEN WHEN THERE IS ONE ELEMENT, and this is not
    formatting. The temptation to yield a scalar at arity ONE and a list at
    MANY is exactly the defect this module closed one floor down: a reader
    will write `map[oid]` expecting a scalar, and on six operations out of
    65 (`create_pipe_system`, `create_room_separator`, `route_duct_system`,
    `route_pipe_system`, `move_elements`, `delete`… — the exact list is in
    `created_identity_fields`) will get something other than what it
    expected, WITH NOT A SINGLE ERROR. One form for every arity forces the
    decision about multiplicity to be made explicitly.

    The ONLY map form in the tree: the flat `op_to_element_ids` was removed
    15.08 together with its assertions (the argument is in the block above
    this function). Whoever needs exactly one element writes that
    EXPLICITLY and gets a refusal if there turn out to be two:
    `element_id, = receipt_map(ops, payload)[oid]`.

    `strict=False` by default: the receipt is built AFTER
    `serving._result_contract_diagnostic` would already have refused
    (KIR-X008) on any missing identity, so a second refusal here would add
    nothing to the protection and could bring down an ALREADY COMPLETED
    record.
    """

    return {oid: [a.value for a in addrs]
            for oid, addrs in element_addresses(
                ops, payload, strict=strict).items()}
