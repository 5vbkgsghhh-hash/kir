"""The field ledger: what from L0 did NOT make it into L1, for whom exactly,
and why.

🔴 WHY IT WAS BUILT, AND THIS IS A MEASUREMENT, NOT A DESIGN INTENT. The
07.09.2026 recon (`sob62_r23_v3`, 1455 elements) measured the
`L0 → lift → L1` loop BY FIELD, not by element:

    total non-empty L0 fields: 20,482 · DID NOT MAKE IT to L1: 11,625 (56.8%)
       op   : non-empty 15,304 · lost 9,226 (60.3%)   ← OPS LOSE MORE ATOMS
       atom : non-empty  5,178 · lost 2,399 (46.3%)

This refutes the convenient framing "loss is a property of the fallback
atom": enriching the atom would fix 46%, not 57%. The loss is a property of
TRANSLATION INTO THE OPERATIONS LANGUAGE, and `host_id` ("which wall this
door is in") is lost in 187 of 187. Exactly three fields are lost by
nobody: `element_id`, `level_name`, `type_name`.

🔴 WHAT THIS MODULE DOES NOT DO. It stores nothing and fixes nothing: L1
will not become a complete archive, because it speaks the language of
operations, not of Revit fields. The archive IS L0 itself on disk, already
addressed by `element_id`. What is printed here is the DIFFERENCE, with an
address on every row, so that "the field was lost" stops being
indistinguishable from "the field never existed".

🔴 THE COUNTING LAW, VERBATIM (rewritten 07.09.2026, mandate F5 part 3). A
field counts as REPRESENTED if it has a NAMED CARRIER in the node — an
operation parameter, a node's type slot, or a registry reference — and the
carrier's value matches the source BY VALUE, UNITS, REFERENCE, AND
COORDINATE SYSTEM. An empty field counts as neither surviving nor lost:
"never existed" and "lost" are different facts.

🔴 THE PREVIOUS LAW PROVED SOMETHING OTHER THAN WHAT IT ASKED, AND THIS IS A
MEASUREMENT. It stated: "the name exists in the node OR the value appears
in the node's TEXT." A measurement of eight probes on 07.09.2026 against
the old code: `type_name="Плита 225"` against `"СОВСЕМ ДРУГОЙ ТИП"` in the
node — counted as surviving; `rotation_deg=0.0` against a zero in a
COMPLETELY UNRELATED `p0_mm` — counted as surviving; the opaque `params`
block — counted as surviving (the `params` key exists on any operation
node); `unique_id` that happened to land in the text of `reason.detail` —
counted as surviving; `p0_mm=3048` against `p0_ft=3048.0` (DIFFERENT UNITS,
different field) — counted as surviving. And conversely: a correct
conversion `3048 mm → 10.0 ft` and a `host_id` translated into a NODE
REFERENCE — counted as lost. Six wrong verdicts out of eight.

🔴 FOUR STATES INSTEAD OF TWO, because each calls for a different fix:

    represented   a named IR carrier holds the same value;
    approximate   the same fact is recoverable, but not byte-for-byte: a
                  named counterpart (`level_id` ← `level_name`), a
                  projected point (z dropped), a rounded number;
    source_data   the value survives only as SOURCE DATA — an opaque L0
                  block, or a node field with no operational meaning.
                  Storing the opaque blob is NOT proof of BIM
                  reconstruction;
    unknown       there is no carrier at all, or the carrier holds a
                  DIFFERENT value.

`kept` is exactly `represented`. `lost` is all three others: "definitely
did not make it"; the state says how much of the fact survived, and `why`
says whose job the fix is.

🔴 WHAT IS NOT FIXED HERE, AND THIS IS A NAMED BOUNDARY, NOT UNFINISHED WORK
(07.09.2026). The 06–07.09 ledger named three major losses. Two are closed
(`anchor_mm` as a point carrier; the host via the addressable entity). The
third was CHECKED AND LEFT OPEN, because closing it would mean EXTENDING
THE LANGUAGE, which the mandate forbids:

    `p0_mm`/`p1_mm` for walls — 476 (`bench_A`) and 683 (`sob62_r23_v3`)
    are in the `approximate` state, because the node carries two of three
    components.

This is NOT the lifter's debt. Measuring the contract: `create_wall.p0_mm`
is declared as `pt_xy` — the operations language deliberately takes a
wall's point as PLANAR, since a wall lives on a level. The third component
is expressed by a DIFFERENT pair of words, and the lifter already writes
it: `level` + `base_offset_mm` (632 of 683 walls in `sob62_r23_v3` carry
`base_offset_mm` in the node). In other words the fact is recoverable —
but not byte-for-byte and not under the same name, and that is exactly the
definition of `approximate`. Bringing it up to `represented` would take
either changing `pt_xy` to `pt_xyz` (extending the language) or a composite
carrier of "an L0 field = a function of TWO op parameters" (a second proof
system layered on the measurement). Neither is done here, and the number
stays visible.

A second boundary is named the same way: `create_column.category` is an
ENUM `structural|architectural`, while `L0.category` is a Revit category.
One word, two subjects; see :data:`COLLIDING_OP_PARAMS`.

🔴 THE SUM OF THE KINDS MUST RECONCILE WITH THE LOSS COUNT. A classifier
that drops whatever fits no branch reports its kinds and lies more
plausibly than silence would. That is why `totals["unclassified"]` is
ALWAYS printed and must be 0, while elements for which no node was found
at all are counted as a separate number, `elements_without_node`, rather
than falling out of the denominator.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

FIELD_LEDGER_SCHEMA = "kir-field-ledger/1"

#: A closed list of reasons. There is no fourth: "other" would mean the
#: reason was not named, and `unclassified` must be zero.
WHY = ("atom", "op_language", "derived")

#: A field -> its counterpart field, from which the SAME FACT is
#: recoverable. The pairs are not invented: the operations language
#: addresses a level and a type BY NAME (`{"by": "name"}`), meaning the
#: substitution "id -> name" is exactly what the translation itself does.
#: `category_ru` is the localized name of the same category.
#:
#: 🔴 THE COUNTERPART IS CHECKED, NOT ASSUMED. The `derived` reason is set
#: ONLY if the counterpart actually made it into this node. Otherwise the
#: loss remains a loss: "a name instead of an id" saves the fact only when
#: the name is present.
RECOVERABLE_FROM = {
    "level_id": "level_name",
    "type_id": "type_name",
    "category_ru": "category",
}

_EMPTY = (None, (), [], {}, "")

#: A closed list of field states. There is no fifth: "other" would mean the
#: state was not named.
STATES = ("represented", "approximate", "source_data", "unknown")

#: States in which the field DEFINITELY did not make it, and falls into
#: `lost`.
LOST_STATES = tuple(name for name in STATES if name != "represented")

#: Node fields WITH NO operational meaning: a value found only here is
#: preserved as source data, but is not reconstructed in the BIM.
OPAQUE_NODE_KEYS = ("reason", "detail", "raw", "opaque", "payload",
                    "source_params", "l0_params")

#: L0 fields that are THEMSELVES opaque source data: the raw dictionary of
#: Revit parameters. It stays in L0 on disk and is addressed by
#: `element_id`, but no KIR operation reconstructs it.
SOURCE_DATA_FIELDS = ("params",)

#: The reference roles by which the operations language addresses other
#: entities. The names are taken from a MEASUREMENT of a real L1's
#: parameters (`bench_A`), not out of thin air.
REFERENCE_ROLES = {
    "level": ("level",),
    "type": ("type", "symbol", "pipe_type", "duct_type", "tray_type",
             "panel_type", "wall_type", "floor_type"),
    "host": ("host",),
}

#: An L0 field -> (reference role, exactly what to compare within it).
#: `_id` is the addressed entity's identifier, `value` is its name, `node`
#: is a reference to a NODE that must be resolved and asked for its source
#: element.
FIELD_AS_REFERENCE = {
    "level_id": ("level", "_id"), "level_name": ("level", "value"),
    "type_id": ("type", "_id"), "type_name": ("type", "value"),
    "host_id": ("host", "node"),
}

#: (operation, parameter) -> WHAT THIS PARAMETER ACTUALLY MEANS. A matching
#: name is not a carrier if the SUBJECT is different, and a 07.09.2026
#: measurement says how much this costs: of the 1,708 `bench_A` losses
#: attributed to "the op has the word, the lifter didn't deliver it", 756
#: are exactly this case. `create_column.category` is an enum
#: `structural|architectural` (a load-bearing or an architectural column),
#: while `L0.category` is the REVIT CATEGORY `OST_StructuralColumns`. Two
#: different facts under one word; counting them as one accused the lifter
#: of a debt that does not exist, and the fix belongs to the language, not
#: the lifter.
#:
#: The list is deliberately closed and short: it lifts an accusation rather
#: than adding evidence — no field becomes `represented` by landing here,
#: its state stays unchanged.
COLLIDING_OP_PARAMS = {
    ("create_column", "category"):
        "перечисление structural|architectural, а не категория Ревита",
}

#: Typical node slots under a different name. The list is closed and short
#: deliberately: a map "field -> carrier" for every field would be exactly
#: that certificate system which the mandate forbids substituting for the
#: measurement.
#:
#: 🔴 `anchor_mm` WAS INTRODUCED ON 07.09.2026 BY MEASUREMENT, AND IT IS A
#: CARRIER, NOT A CONCESSION.
#: The L1 node carries the placement point in the slot `anchor_mm`, next to
#: `level_name` and `type_name` — the very slots the ledger already treats
#: as carriers. For door `bench_A` 286533, `create_door` names the HOST and
#: the OFFSET, and the point itself is held by `anchor_mm` = [24000.0,
#: 5000.0, 0.0] — byte-for-byte the `p0_mm` from L0.
#: The previous law looked for a carrier ONLY by name match and declared
#: the point lost for 126 doors and 756 columns of `bench_A`, even though
#: it lies in the node.
#:
#: This is not a concession, because the comparison remained BY VALUE: for
#: a wall, `anchor_mm` is the MIDPOINT of the segment (18000 vs. p0
#: 12000), and it does not count as `p0_mm` for any of the 476 walls of
#: `bench_A`.
IR_SLOT_ALIAS = {"element_id": ("source_element_id",),
                 "p0_mm": ("anchor_mm",)}

#: L0 fields whose value the node carries not in ONE slot but in SEVERAL,
#: IN ORDER. The slot address is a dotted path.
#:
#: 🔴 `opening_boundary_mm` WAS INTRODUCED ON 08.09.2026 BY MEASUREMENT,
#: AND IT IS A CARRIER, NOT A CONCESSION. The boundary of a rectangular
#: opening in a wall is EXACTLY TWO corners (`Opening.BoundaryRect` is
#: documented as a pair), and the lifter places them into the node
#: byte-for-byte, with the same numbers, but as TWO op parameters:
#: `create_opening.p0_mm` and `.p1_mm` (`lift._lift_opening`: `p0, p1 =
#: boundary`). The previous law looked for a carrier by ONE name and
#: declared the boundary `unknown` — lost — even though it lies in the
#: node whole. A false loss is worse than a missed one: it calls finished
#: work unfinished and sends it to be redone.
#:
#: THIS IS NOT A CONCESSION, BECAUSE THE COMPARISON REMAINED BY VALUE. The
#: pair of slots is only ASSEMBLED; whether `_compare` counts it or not is
#: decided by whether the numbers match. For an opening whose boundary the
#: lifter would raise differently (a polyline of N points of the
#: `host_face` kind), the assembled pair will not match the original
#: boundary, and the field stays lost — as it should.
#:
#: The list is closed and short for exactly the same reason as
#: `IR_SLOT_ALIAS`: a map "field -> carrier" for every field would be
#: exactly that certificate system which the mandate forbids substituting
#: for the measurement.
COMPOSED_SLOT_CARRIER = {"opening_boundary_mm": ("params.p0_mm", "params.p1_mm")}

#: Node slots that carry the value EXACTLY, but are DERIVED by the lifter,
#: rather than being the operation's authored input.
#:
#: 🔴 THIS IS A CAVEAT AGAINST ITS OWN NUMBER, AND IT IS ENTERED AGAINST
#: ITSELF.
#: `anchor_mm` is a typical L1 schema slot (`l1_schema`, checked as vec3,
#: part of the closed list of keys), and the value in it matches
#: byte-for-byte — that is, by the law of counting, the field IS
#: REPRESENTED. But `fold` calls it DERIVED and DISCARDS it from the
#: canonical form (`canonical.pop("anchor_mm")`): reassembly places the
#: door by `host` and `offset_mm`, not by this point.
#:
#: Therefore the "represented" number MUST be readable together with how
#: much of it rests on a derived slot:
#: `totals["represented_via_derived_slot"]`. Otherwise a cleared loss
#: would read as proven reconstruction, and those are different facts —
#: exactly the substitution the law was rewritten to forbid.
DERIVED_SLOTS = ("anchor_mm",)

#: Units are read FROM THE FIELD NAME — that is how both L0 and the
#: operation language write them. Order matters: the longest suffix is
#: matched first.
_UNIT_SUFFIXES = ("n_per_m2", "n_per_m", "nm", "mm", "cm", "ft", "deg", "rad",
                  "m2", "m", "n")

#: Family -> {unit: multiplier to the family's base unit}. Conversion is
#: possible ONLY within a family: meters and degrees are not comparable,
#: and silently comparing their numbers is exactly the defect the law was
#: rewritten for.
_UNIT_FAMILIES = (
    {"mm": 1.0, "cm": 10.0, "m": 1000.0, "ft": 304.8},
    {"deg": 1.0, "rad": 57.29577951308232},
    {"n": 1.0}, {"nm": 1.0}, {"n_per_m": 1.0}, {"n_per_m2": 1.0}, {"m2": 1.0},
)

#: A "byte-for-byte" match and an "eyeballed" match are different states,
#: and the threshold is what separates them.
_TIGHT_REL, _TIGHT_ABS = 1e-9, 1e-6
_COARSE_REL, _COARSE_ABS = 1e-3, 1.0


class FieldLedgerError(ValueError):
    """The ledger cannot be built; the reason is named."""


@dataclass(frozen=True)
class LostField:
    """One lost field of one element."""

    field: str
    why: str
    #: One of :data:`LOST_STATES`. `why` answers "whose repair is this"
    #: (registry/lifter/atom); `state` answers "how much of the fact
    #: survived." These are different questions, and folding them into
    #: one would be guessing.
    state: str = "unknown"
    #: Exactly where the carrier was found, if it was found: the address
    #: inside the node.
    carrier: str | None = None
    #: Whether the operation the element became has a PARAMETER of this
    #: name.
    #:
    #: 🔴 THIS IS NOT A FOURTH CAUSE, BUT A MEASUREMENT WITHIN THE THIRD.
    #: "The language cannot say it" and "the language can, but it never
    #: reached the node" are different repairs: the first is fixed in
    #: the operation registry, the second in the lifter. Telling them
    #: apart by a word would be guessing; telling them apart by a number
    #: is possible, and here it is.
    in_op_contract: bool | None = None
    recovered_from: str | None = None

    def __post_init__(self) -> None:
        if self.why not in WHY:
            raise FieldLedgerError(f"{self.why}: причина вне закрытого списка WHY")
        if (self.why == "derived") != (self.recovered_from is not None):
            raise FieldLedgerError("derived обязан назвать напарника, и только он")
        if self.state not in LOST_STATES:
            raise FieldLedgerError(
                f"{self.state}: состояние потери вне закрытого списка "
                f"{LOST_STATES}; `represented` в потери попасть не может")

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "why": self.why, "state": self.state,
                "carrier": self.carrier,
                "in_op_contract": self.in_op_contract,
                "recovered_from": self.recovered_from}


@dataclass(frozen=True)
class ElementFields:
    """The field diff of ONE element, with an address."""

    element_id: str
    unique_id: str | None
    category: str
    node_kind: str | None
    op_name: str | None
    kept: tuple[str, ...]
    lost: tuple[LostField, ...]

    @property
    def nonempty(self) -> int:
        return len(self.kept) + len(self.lost)

    @property
    def address(self) -> dict[str, str | None]:
        """The row's address. It can never be empty: without it the row
        is useless."""
        return {"element_id": self.element_id, "unique_id": self.unique_id}

    def to_dict(self) -> dict[str, Any]:
        return {"element_id": self.element_id, "unique_id": self.unique_id,
                "category": self.category, "node_kind": self.node_kind,
                "op_name": self.op_name, "kept": list(self.kept),
                "lost": [row.to_dict() for row in self.lost],
                "nonempty": self.nonempty, "lost_count": len(self.lost)}


@dataclass(frozen=True)
class FieldLedger:
    """The whole ledger: rows with an address, and totals that are
    required to add up."""

    rows: tuple[ElementFields, ...]
    totals: Mapping[str, Any]
    schema_version: str = FIELD_LEDGER_SCHEMA

    def __post_init__(self) -> None:
        by_why = self.totals["by_why"]
        if sum(by_why.values()) + self.totals["unclassified"] != self.totals["lost"]:
            raise FieldLedgerError(
                "сумма родов не сходится с числом потерь — классификатор "
                "молча уронил род")
        by_state = self.totals.get("by_state")
        if by_state is not None:
            if sorted(by_state) != sorted(STATES):
                raise FieldLedgerError(
                    "состояния вне закрытого списка STATES")
            if (sum(by_state.values()) + self.totals["unclassified"]
                    != self.totals["nonempty"]):
                raise FieldLedgerError(
                    "сумма состояний не сходится с числом непустых полей — "
                    "классификатор молча уронил поле")
            if by_state["represented"] + self.totals["lost"] != self.totals["nonempty"]:
                raise FieldLedgerError(
                    "`kept` обязан быть ровно `represented`: два разных числа "
                    "об одном предмете")
        if self.totals["unclassified"]:
            raise FieldLedgerError(
                f"НЕ РАЗОБРАНО {self.totals['unclassified']} потерь: причина "
                f"обязана быть названа, а не отнесена к «прочему»")

    @property
    def addressed(self) -> int:
        """Rows with a non-empty address. A row without an address does
        not count at all."""
        return sum(1 for row in self.rows if row.element_id)

    def lost_rows(self) -> tuple[ElementFields, ...]:
        return tuple(row for row in self.rows if row.lost)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema_version,
                "rows": [row.to_dict() for row in self.rows],
                "totals": dict(self.totals)}


def _nodes_of(l1) -> list[Mapping[str, Any]]:
    if l1 is None:
        raise FieldLedgerError("L1 не передан: ведомость строить не из чего")
    nodes = getattr(l1, "nodes", l1)
    if isinstance(nodes, Mapping):
        raise FieldLedgerError("ожидалась последовательность узлов L1")
    if not isinstance(nodes, Sequence):
        nodes = list(nodes)
    return list(nodes)


def _source_id(node: Mapping[str, Any]) -> str | None:
    value = node.get("source_element_id")
    if value is None:
        source = node.get("source")
        value = source.get("element_id") if isinstance(source, Mapping) else None
    return None if value is None else str(value)


def _op_parameter_names(op_name: str | None) -> frozenset[str] | None:
    """The words the OPERATION knows how to say — from the registry, not
    from thin air.

    `None` means "the operation is unknown to the registry": that is not
    "there are no words," and equating the two is not allowed.
    """
    if not op_name:
        return None
    try:
        from kir import spec
    except Exception:                                          # noqa: BLE001
        return None
    contract = spec.OPS.get(op_name)
    if contract is None:
        return None
    names: set[str] = set()
    for holder in ("params", "parameters", "fields", "args"):
        block = getattr(contract, holder, None)
        if isinstance(block, Mapping):
            names.update(str(key) for key in block)
        elif isinstance(block, (list, tuple)):
            for item in block:
                name = getattr(item, "name", None) or (
                    item.get("name") if isinstance(item, Mapping) else None)
                if name:
                    names.add(str(name))
    return frozenset(names)


def _split_unit(name: str) -> tuple[str, str | None]:
    """`p0_mm` -> `("p0", "mm")`. The unit is part of the NAME, and
    therefore part of the value."""
    for suffix in _UNIT_SUFFIXES:
        if name.endswith("_" + suffix) and len(name) > len(suffix) + 1:
            return name[: -len(suffix) - 1], suffix
    return name, None


def _family_of(unit: str | None) -> Mapping[str, float] | None:
    if unit is None:
        return None
    for family in _UNIT_FAMILIES:
        if unit in family:
            return family
    return None


def _convert(value: float, frm: str | None, to: str | None) -> float | None:
    """Conversion is possible ONLY within a family. `None` means "not
    comparable, and that's a fact"."""
    if frm == to:
        return value
    family = _family_of(frm)
    if family is None or to not in family:
        return None
    return value * family[frm] / family[to]


def _numbers(value: Any) -> tuple[float, ...] | None:
    """A number or a sequence of numbers -> a tuple; otherwise `None`."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return (float(value),)
    if isinstance(value, (list, tuple)):
        out: list[float] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                return None
            out.append(float(item))
        return tuple(out)
    return None


def _close(a: float, b: float, rel: float, abs_: float) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def _compare(source: Any, carried: Any, source_unit: str | None,
             carrier_unit: str | None) -> str | None:
    """Compare the source value against the carrier.

    Returns `"represented"`, `"approximate"`, or `None` ("the carrier
    holds something ELSE"). Units and the number of components are part
    of the value: a point with `z` dropped cannot be fully recovered, and
    a number in a different unit describes a different place, no matter
    how many digits match.
    """
    left, right = _numbers(source), _numbers(carried)
    if left is not None and right is not None:
        if not right:
            return None
        converted: list[float] = []
        for item in right:
            back = _convert(item, carrier_unit, source_unit)
            if back is None:
                return None
            converted.append(back)
        shared = min(len(left), len(converted))
        if len(converted) > len(left):
            return None
        tight = all(_close(left[i], converted[i], _TIGHT_REL, _TIGHT_ABS)
                    for i in range(shared))
        coarse = all(_close(left[i], converted[i], _COARSE_REL, _COARSE_ABS)
                     for i in range(shared))
        if not coarse:
            return None
        if len(converted) < len(left):
            # Projection: a component was dropped. The fact is not fully
            # recoverable.
            return "approximate"
        return "represented" if tight else "approximate"
    if source_unit != carrier_unit and (source_unit or carrier_unit):
        # A non-numeric value in a different unit — nothing to compare.
        return None
    if isinstance(source, str) or isinstance(carried, str):
        one = source if isinstance(source, str) else str(source)
        two = carried if isinstance(carried, str) else str(carried)
        if one == two:
            return "represented"
        return "approximate" if one.strip() == two.strip() else None
    if source == carried:
        return "represented"
    encoded_source = json.dumps(source, ensure_ascii=False, default=str, sort_keys=True)
    encoded_carried = json.dumps(carried, ensure_ascii=False, default=str, sort_keys=True)
    if encoded_source == encoded_carried:
        return "represented"
    return None


def _dig(block: Any, path: str) -> Any:
    """The value at a dotted path, or `None` if there is no such path."""
    for step in path.split("."):
        if not isinstance(block, Mapping):
            return None
        block = block.get(step)
        if block is None:
            return None
    return block


def _named_carriers(node: Mapping[str, Any], name: str,
                    depth: int = 0) -> list[tuple[str, str | None, Any]]:
    """`[(address, unit, value)]` — carriers found BY NAME.

    The name is compared together with the unit: `p0_mm` and `p0_ft` are
    one carrier in different units; `p0_mm` and `xy` are different
    carriers. Opaque areas (:data:`OPAQUE_NODE_KEYS`) are not walked at
    all: they carry no meaning, and anything found there is source data,
    not representation.
    """
    base, unit = _split_unit(name)
    found: list[tuple[str, str | None, Any]] = []

    def walk(block: Any, address: str, level: int) -> None:
        if level > 5 or not isinstance(block, Mapping):
            return
        for key, value in block.items():
            key = str(key)
            if key in OPAQUE_NODE_KEYS:
                continue
            here = f"{address}.{key}" if address else key
            key_base, key_unit = _split_unit(key)
            if key == name:
                found.append((here, unit, value))
            elif (unit is not None and key_unit is not None and key_base == base
                  and _family_of(unit) is _family_of(key_unit)
                  and _family_of(unit) is not None):
                found.append((here, key_unit, value))
            if isinstance(value, Mapping):
                walk(value, here, level + 1)

    walk(node, "", depth)
    for alias in IR_SLOT_ALIAS.get(name, ()):
        if alias in node:
            found.append((alias, unit, node[alias]))
    paths = COMPOSED_SLOT_CARRIER.get(name)
    if paths:
        parts = [_dig(node, path) for path in paths]
        # Only a COMPLETE pair is assembled: half a carrier is not a
        # carrier.
        if all(part is not None for part in parts):
            found.append((" + ".join(paths), unit, parts))
    return found


def _reference_carrier(node: Mapping[str, Any], name: str,
                       by_node_id: Mapping[str, Mapping[str, Any]],
                       source_value: Any = None) -> tuple[str, Any] | None:
    """A REFERENCE carrier: a registry `{by,value,_id}` or a `{ref}` to a node.

    `host_id` is NOT lost just because the operation language names the
    host as a reference to a node: the reference is resolved, and the
    resolved node is asked for its source element. A match means the
    fact is represented; no match means nothing is saved.

    🔴 A REFERENCE ADDRESSES AN ENTITY, NOT A KEY, AND THIS IS THE
    MEASUREMENT OF 07.09.2026. The previous edition looked for the host
    ONLY under the key `host` and declared it lost for 777 of 1207 beams
    of `bench_A`. Measurement: beam 296802 has `host_id = 296349`, and
    this is exactly the entity the node ADDRESSES — via the reference
    `params.level = {"by": "name", "value": "HB-Ур.2", "_id": "296349"}`.
    The beam's host IS its level; the fact "the host is element 296349"
    is represented in the IR, and the previous verdict was talking about
    our search, not about the building.

    Therefore, for the `host` role, the carrier is looked up by the
    ADDRESSED IDENTIFIER: any named reference of the node whose `_id`
    (or resolved `ref`) equals `host_id` is named as the address in
    `carrier`. This is not fishing: the key is not chosen by name but by
    the EQUALITY of that very entity, and the address is printed so the
    verdict can be rechecked by hand.
    """
    role = FIELD_AS_REFERENCE.get(name)
    if role is None:
        return None
    role_name, part = role
    params = node.get("params")
    blocks = [node] + ([params] if isinstance(params, Mapping) else [])
    unresolved: tuple[str, Any] | None = None
    for block in blocks:
        for key in REFERENCE_ROLES[role_name]:
            value = block.get(key)
            if not isinstance(value, Mapping):
                continue
            address = f"params.{key}" if block is params else key
            if part == "node":
                ref = value.get("ref")
                target = by_node_id.get(str(ref)) if ref is not None else None
                if target is None:
                    # A reference exists but does not resolve: the
                    # address is remembered and returned IF the entity
                    # is not found anywhere else.
                    unresolved = unresolved or (f"{address}.ref", None)
                    continue
                return (f"{address}.ref", _source_id(target))
            return (f"{address}.{part}", value.get(part))
    if part == "node" and source_value not in _EMPTY:
        wanted = str(source_value)
        for block, prefix in ((node, ""), (params, "params.")):
            if not isinstance(block, Mapping):
                continue
            for key, value in block.items():
                if not isinstance(value, Mapping):
                    continue
                if str(value.get("_id")) == wanted:
                    return (f"{prefix}{key}._id", value.get("_id"))
                ref = value.get("ref")
                target = by_node_id.get(str(ref)) if ref is not None else None
                if target is not None and _source_id(target) == wanted:
                    return (f"{prefix}{key}.ref", _source_id(target))
    return unresolved


def _echoed_in_opaque(node: Mapping[str, Any], value: Any) -> str | None:
    """The address of the opaque area where EXACTLY this value lies.

    🔴 THE VALUE IS COMPARED, NOT A SUBSTRING, AND THIS IS THE SAME LAW.
    The temptation to ask "does the value's text occur inside the
    area's text" would bring back exactly the defect the law was
    rewritten for: `"point"` would be found inside someone else's word.
    That is why the area is walked by values.
    """
    if value in _EMPTY:
        return None
    wanted = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, default=str, sort_keys=True)

    def same(candidate: Any) -> bool:
        if isinstance(candidate, str):
            return candidate == wanted
        return json.dumps(candidate, ensure_ascii=False, default=str,
                          sort_keys=True) == wanted

    def scan(block: Any, address: str, level: int) -> str | None:
        if level > 5:
            return None
        if same(block):
            return address
        if isinstance(block, Mapping):
            for key, item in block.items():
                hit = scan(item, f"{address}.{key}" if address else str(key),
                           level + 1)
                if hit is not None:
                    return hit
        elif isinstance(block, (list, tuple)):
            for number, item in enumerate(block):
                hit = scan(item, f"{address}[{number}]", level + 1)
                if hit is not None:
                    return hit
        return None

    def walk(block: Any, address: str, level: int) -> str | None:
        if level > 5 or not isinstance(block, Mapping):
            return None
        for key, item in block.items():
            key = str(key)
            here = f"{address}.{key}" if address else key
            if key in OPAQUE_NODE_KEYS:
                hit = scan(item, here, level + 1)
                if hit is not None:
                    return hit
                continue
            hit = walk(item, here, level + 1)
            if hit is not None:
                return hit
        return None

    return walk(node, "", 0)


def field_ledger(l0, l1) -> FieldLedger:
    """`(L0Document, L1 nodes) -> field diff by element, with address and
    cause.

    Returns a `FieldLedger`; the sum of the causes matches the loss
    count by construction (otherwise the constructor refuses), and
    elements without a node are counted as a separate number and do not
    disappear from the denominator.
    """
    elements = getattr(l0, "elements", None)
    if elements is None:
        raise FieldLedgerError("ожидался L0Document с полем elements")
    elements = list(elements)
    if not elements:
        raise FieldLedgerError(
            "в L0 ноль элементов: пустая ведомость зелена по построению и "
            "означала бы «потерь нет» там, где не было замера")

    by_source: dict[str, Mapping[str, Any]] = {}
    by_node_id: dict[str, Mapping[str, Any]] = {}
    for node in _nodes_of(l1):
        if not isinstance(node, Mapping):
            continue
        node_id = node.get("_id")
        if node_id is not None and str(node_id) not in by_node_id:
            by_node_id[str(node_id)] = node
        source = _source_id(node)
        if source is not None and source not in by_source:
            by_source[source] = node

    names = [item.name for item in dataclasses.fields(elements[0])]
    rows: list[ElementFields] = []
    by_why: dict[str, int] = {name: 0 for name in WHY}
    by_field: dict[str, int] = {}
    kept_by_field: dict[str, int] = {}
    by_kind: dict[str, list[int]] = {"op": [0, 0], "atom": [0, 0]}
    by_state: dict[str, int] = {name: 0 for name in STATES}
    total_nonempty = total_lost = unclassified = kept_by_empty_key = 0
    represented_via_derived = 0
    without_node = 0
    contract_has_the_word = 0

    for element in elements:
        source = str(element.element_id)
        node = by_source.get(source)
        if node is None:
            # 🔴 AN ELEMENT WITHOUT A NODE IS NOT DISCARDED. The recon
            # probe used to skip such elements; skipping them in the
            # denominator makes the loss share SMALLER than it actually
            # is, and does so silently.
            without_node += 1
            continue
        kind = node.get("kind")
        op_name = node.get("op_name") if kind == "op" else None
        contract = _op_parameter_names(op_name)
        text = json.dumps(node, ensure_ascii=False, default=str, sort_keys=True)
        kept: list[str] = []
        lost: list[LostField] = []
        for name in names:
            value = getattr(element, name, None)
            if value in _EMPTY:
                continue
            total_nonempty += 1
            if kind in by_kind:
                by_kind[kind][0] += 1
            encoded = json.dumps(value, ensure_ascii=False, default=str).strip('"')
            source_unit = _split_unit(name)[1]
            # 🔴 THE PROOF IS THE CARRIER AND ITS VALUE, NOT THE NODE'S
            # TEXT. The order of branches is closed and named: named
            # carrier -> registry reference -> partner -> opaque -> "no
            # carrier."
            state, carrier = "unknown", None
            collision = (op_name, name) in COLLIDING_OP_PARAMS
            for address, unit, carried in _named_carriers(node, name):
                if collision and address in (name, f"params.{name}"):
                    # The word is the same, the SUBJECT is different:
                    # this is not a carrier in either direction — not as
                    # proof, not as a debt.
                    continue
                verdict = _compare(value, carried, source_unit, unit)
                if verdict == "represented":
                    state, carrier = verdict, address
                    break
                if verdict == "approximate" and state != "approximate":
                    state, carrier = verdict, address
            if state != "represented":
                reference = _reference_carrier(node, name, by_node_id, value)
                if reference is not None:
                    address, carried = reference
                    verdict = (None if carried in _EMPTY
                               else _compare(value, carried, source_unit, None))
                    if verdict is not None and (verdict == "represented"
                                                or state == "unknown"):
                        state, carrier = verdict, address
            if state == "represented":
                if carrier in DERIVED_SLOTS:
                    represented_via_derived += 1
                kept.append(name)
                kept_by_field[name] = kept_by_field.get(name, 0) + 1
                by_state["represented"] += 1
                # The previous law counted a key with an EMPTY VALUE as
                # having arrived (`level_name: null` — "arrived"). The
                # new law compares values, and an empty carrier is not
                # equal to a non-empty field: the number must be 0, and
                # it is printed so this is visible.
                if name in node and node.get(name) in _EMPTY:
                    kept_by_empty_key += 1
                continue
            total_lost += 1
            by_field[name] = by_field.get(name, 0) + 1
            if kind in by_kind:
                by_kind[kind][1] += 1
            partner = RECOVERABLE_FROM.get(name)
            # 🔴 THE PARTNER IS COUNTED BY A STRICT RULE, NOT BY THE
            # COUNTING LAW. The counting law accepts a key with an empty
            # value; for `derived` that would be a lie: `level_name:
            # null` in the node does NOT save a lost `level_id`. Here a
            # NON-EMPTY value is required.
            partner_value = None if partner is None else node.get(partner)
            partner_arrived = bool(
                partner is not None
                and (partner_value not in _EMPTY
                     or (getattr(element, partner, None) not in _EMPTY
                         and json.dumps(getattr(element, partner), ensure_ascii=False,
                                        default=str).strip('"') in text)))
            if state == "unknown" and partner_arrived:
                state = "approximate"
                carrier = partner
            if state == "unknown":
                if name in SOURCE_DATA_FIELDS:
                    # The raw Revit parameter dictionary stays in L0 on
                    # disk and is addressed by `element_id`. This is NOT
                    # a reconstruction.
                    state, carrier = "source_data", "L0"
                else:
                    echo = _echoed_in_opaque(node, value)
                    if echo is not None:
                        state, carrier = "source_data", echo
            by_state[state] += 1
            if partner_arrived:
                why, recovered = "derived", partner
            elif kind == "atom":
                why, recovered = "atom", None
            elif kind == "op":
                why, recovered = "op_language", None
            else:
                unclassified += 1
                by_state[state] -= 1
                continue
            by_why[why] += 1
            in_contract = (False if collision else
                           (None if contract is None else (name in contract)))
            if in_contract:
                contract_has_the_word += 1
            lost.append(LostField(field=name, why=why, state=state, carrier=carrier,
                                  in_op_contract=in_contract,
                                  recovered_from=recovered))
        rows.append(ElementFields(
            element_id=source, unique_id=getattr(element, "unique_id", None),
            category=getattr(element, "category", ""), node_kind=kind,
            op_name=op_name, kept=tuple(kept), lost=tuple(lost)))

    totals = {
        "elements": len(elements),
        "elements_with_node": len(rows),
        "elements_without_node": without_node,
        "elements_with_losses": sum(1 for row in rows if row.lost),
        "nonempty": total_nonempty,
        "lost": total_lost,
        "lost_share": (total_lost / total_nonempty) if total_nonempty else 0.0,
        "unclassified": unclassified,
        # Keys counted as having arrived with an EMPTY value in the
        # node. The counting law accepts them (otherwise the number
        # would not be comparable to the recon measurement), and this
        # number says how many there are and whether the law should
        # change.
        "kept_by_empty_key": kept_by_empty_key,
        # How much of "represented" rests on a DERIVED node slot rather
        # than on the operation's authored input. The number is printed
        # next to `represented`, so that a cleared loss cannot be read
        # as proven reconstruction: see :data:`DERIVED_SLOTS`.
        "represented_via_derived_slot": represented_via_derived,
        # Four field states. The sum must match `nonempty`: otherwise
        # the classifier silently dropped a field — the same law as for
        # the causes.
        "by_state": dict(by_state),
        "by_why": dict(by_why),
        "by_kind": {name: {"nonempty": pair[0], "lost": pair[1]}
                    for name, pair in by_kind.items()},
        "by_field": dict(sorted(by_field.items(), key=lambda item: (-item[1], item[0]))),
        "never_lost": sorted(name for name in kept_by_field if name not in by_field),
        # How many losses fell on a field PRESENT in the operation's
        # contract: that is a lifter repair, not a registry one, and
        # the number separates them.
        "lost_though_the_op_contract_has_the_word": contract_has_the_word,
    }
    return FieldLedger(rows=tuple(rows), totals=totals)


def as_losses(ledger: FieldLedger) -> list[dict[str, Any]]:
    """Ledger -> `[{element_id, unique_id, fields, why}]` for the seam
    with `capture_edit`.

    🔴 GROUPED BY CAUSE, NOT BY ELEMENT, AND THIS IS NOT FORMATTING. One
    element loses fields for DIFFERENT causes: for door `bench_A`
    286533, part of the fields is lost to the operation language, while
    `level_id` is recoverable by name. One row per element would force
    naming a single cause for all fields, i.e. lying about some of
    them. There are therefore as many rows as there are pairs "element
    × cause," and `fields` inside a row is sorted.

    An address is mandatory: a row without `element_id` is never
    emitted at all — there is nothing to check it against in the model.
    """
    rows: list[dict[str, Any]] = []
    for row in ledger.rows:
        if not row.lost or not row.element_id:
            continue
        by_why: dict[str, list[str]] = {}
        for item in row.lost:
            by_why.setdefault(item.why, []).append(item.field)
        for why in sorted(by_why):
            rows.append({"element_id": row.element_id, "unique_id": row.unique_id,
                         "fields": sorted(by_why[why]), "why": why,
                         "category": row.category, "node_kind": row.node_kind})
    return rows


__all__ = ["FIELD_LEDGER_SCHEMA", "WHY", "STATES", "LOST_STATES",
           "COLLIDING_OP_PARAMS", "DERIVED_SLOTS",
           "OPAQUE_NODE_KEYS", "SOURCE_DATA_FIELDS", "REFERENCE_ROLES",
           "FIELD_AS_REFERENCE", "RECOVERABLE_FROM", "FieldLedgerError",
           "LostField", "ElementFields", "FieldLedger", "field_ledger", "as_losses"]
