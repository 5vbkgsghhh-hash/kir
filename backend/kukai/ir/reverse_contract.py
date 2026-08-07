"""Exhaustive typed contract between KIR forward and reverse directions.

The forward registry answers what can be executed.  A snapshot cannot invert
every execution: some final-state elements can be lifted to the same op, some
are reconstructed through simpler ops, and history/external artifacts are not
recoverable from a Revit document at all.  Before this manifest those outcomes
lived in unrelated lifter branches and prose; adding a write op required no
machine-readable reverse decision.

``REVERSE_CONTRACTS`` is exhaustive over every write op in ``spec.OPS``.  It
does not claim more than the reverse path proves: ``DIRECT`` means the lifter
may emit the same op for the supported/captured subset; every unsupported
source element remains a typed atom.  Other modes explicitly name why no such
same-op inverse exists and, where applicable, which simpler ops represent the
current state instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from kukai.ir import spec


REVERSE_CONTRACT_SCHEMA = "kir-reverse-contract/1"


class ReverseContractError(ValueError):
    """The reverse path attempted an operation outside its declared surface."""


class ReverseMode(str, Enum):
    DIRECT = "direct"
    CAPTURE_GAP = "capture_gap"
    DECOMPOSED = "decomposed"
    COMPOSED = "composed"
    STATE_TRANSITION = "state_transition"
    PINNED_EXISTING = "pinned_existing"
    EXTERNAL_SOURCE = "external_source"


class ReverseGuarantee(str, Enum):
    FORM_EXACT = "form_exact"
    BOUNDED = "bounded"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ReverseContract:
    op_name: str
    mode: ReverseMode
    guarantee: ReverseGuarantee
    reason: str
    sources: tuple[str, ...] = ()
    entrypoints: tuple[str, ...] = ()
    representation_ops: tuple[str, ...] = ()
    limitation: str = ""

    def __post_init__(self) -> None:
        if self.op_name not in spec.OPS:
            raise ValueError(f"unknown forward op {self.op_name!r}")
        if spec.OPS[self.op_name].family not in spec.WRITE_FAMILIES:
            raise ValueError(f"reverse contract on read op {self.op_name!r}")
        if not isinstance(self.mode, ReverseMode):
            raise TypeError("reverse mode must be typed")
        if not isinstance(self.guarantee, ReverseGuarantee):
            raise TypeError("reverse guarantee must be typed")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reverse contract needs a reason")
        for label, values in (
            ("sources", self.sources),
            ("entrypoints", self.entrypoints),
            ("representation_ops", self.representation_ops),
        ):
            if not isinstance(values, tuple):
                raise TypeError(f"{label} must be an immutable tuple")
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"{label} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{label} contains duplicates")
        if self.mode is ReverseMode.DIRECT:
            if not self.entrypoints:
                raise ValueError("direct reverse contract needs an entrypoint")
            if self.guarantee is ReverseGuarantee.NONE:
                raise ValueError("direct reverse contract needs a guarantee")
        elif self.mode is ReverseMode.COMPOSED:
            if not self.entrypoints:
                raise ValueError("composed reverse contract needs an entrypoint")
        elif self.entrypoints:
            raise ValueError(
                "only direct/composed contracts declare emitting entrypoints")
        if (self.mode in (ReverseMode.DECOMPOSED, ReverseMode.COMPOSED)
                and not self.representation_ops):
            raise ValueError(
                f"{self.mode.value} contract needs representation ops")
        for representation in self.representation_ops:
            if representation not in spec.OPS:
                raise ValueError(
                    f"unknown representation op {representation!r}")
            if spec.OPS[representation].family not in spec.WRITE_FAMILIES:
                raise ValueError(
                    f"reverse representation is not a write op: "
                    f"{representation!r}")

    @property
    def direct_same_op_lift(self) -> bool:
        return self.mode is ReverseMode.DIRECT

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op_name,
            "mode": self.mode.value,
            "guarantee": self.guarantee.value,
            "direct_same_op_lift": self.direct_same_op_lift,
            "reason": self.reason,
            "sources": list(self.sources),
            "entrypoints": list(self.entrypoints),
            "representation_ops": list(self.representation_ops),
            "limitation": self.limitation,
        }


def _direct(
    op_name: str,
    *entrypoints: str,
    sources: tuple[str, ...],
    guarantee: ReverseGuarantee = ReverseGuarantee.FORM_EXACT,
    limitation: str = "",
) -> ReverseContract:
    return ReverseContract(
        op_name=op_name,
        mode=ReverseMode.DIRECT,
        guarantee=guarantee,
        reason=("captured current-state facts can produce the same typed op; "
                "unsupported signatures remain atoms"),
        sources=sources,
        entrypoints=tuple(entrypoints),
        limitation=limitation,
    )


_CONTRACTS = {
    # Same-op lift surface (23/35 write ops). These are subset guarantees: the
    # named entrypoint emits only after its own capture/shape checks pass.
    "create_wall": _direct(
        "create_wall", "_lift_wall", sources=("L0:OST_Walls", "side:wall_curve")),
    "create_floor": _direct(
        "create_floor", "_lift_floor", sources=("L0:OST_Floors", "side:sketch")),
    "create_floor_by_contour": _direct(
        "create_floor_by_contour", "_lift_floor_by_contour",
        sources=("L0:OST_Floors", "side:sketch")),
    "create_roof": _direct(
        "create_roof", "_lift_roof", sources=("L0:OST_Roofs", "side:sketch")),
    "create_column": _direct(
        "create_column", "_lift_column",
        sources=("L0:OST_Columns", "L0:OST_StructuralColumns")),
    "create_beam": _direct(
        "create_beam", "_lift_beam", sources=("L0:OST_StructuralFraming",)),
    "create_foundation": _direct(
        "create_foundation", "_lift_foundation",
        sources=("L0:OST_StructuralFoundation", "side:sketch")),
    "create_door": _direct(
        "create_door", "_lift_door", sources=("L0:OST_Doors",)),
    "create_window": _direct(
        "create_window", "_lift_window", sources=("L0:OST_Windows",)),
    "create_room": _direct(
        "create_room", "_lift_room", sources=("L0:OST_Rooms", "L0:rooms")),
    "create_text": _direct(
        "create_text", "_lift_text", sources=("L0:OST_TextNotes", "side:annotation")),
    "create_tag": _direct(
        "create_tag", "_lift_tag", sources=("L0:tag-categories", "side:tag")),
    "create_level": _direct(
        "create_level", "_lift_level", sources=("L0:OST_Levels", "L0:levels")),
    "create_grid": _direct(
        "create_grid", "_lift_grid", sources=("L0:OST_Grids", "L0:grids")),
    "create_pipe": _direct(
        "create_pipe", "_lift_pipe", sources=("L0:OST_PipeCurves", "side:mep_system")),
    "create_duct": _direct(
        "create_duct", "_lift_duct", sources=("L0:OST_DuctCurves", "side:mep_system")),
    "create_cable_tray": _direct(
        "create_cable_tray", "_lift_cable_tray", sources=("L0:OST_CableTray",)),
    "create_stairs": _direct(
        "create_stairs", "_lift_stairs", sources=("L0:OST_Stairs", "side:stairs_path")),
    "create_ceiling": _direct(
        "create_ceiling", "_lift_ceiling",
        sources=("L0:OST_Ceilings", "side:sketch"),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("frozen capture has no ceiling slope arrow; a captured "
                    "profile proves plan form but not native slope semantics")),
    "create_directshape": _direct(
        "create_directshape", "_lift_directshape",
        sources=("L0:DirectShape", "geometry:mesh")),
    "place_family": _direct(
        "place_family", "_lift_family_fallback",
        sources=("side:family_placement",)),
    "set_curtain_panel": _direct(
        "set_curtain_panel", "_lift_curtain_panel",
        sources=("L0:OST_CurtainWallPanels", "side:curtain")),
    "create_curtain_grid_line": _direct(
        "create_curtain_grid_line", "_grid_line_node",
        sources=("side:curtain_grid_line",)),
    # wave/room (2026-08-03). Инверсия ПОСЕГМЕНТНАЯ и потому точная: в L0
    # каждый OST_RoomSeparationLines — один ModelCurve со своими p0/p1 и
    # своим level_id, и лифт даёт ему ломаную ровно из двух точек (закон
    # «один L0-элемент → РОВНО ОДИН L1-узел» не позволил бы сшить соседние
    # линии в одну ломаную, да и сшивать их нечем: общей личности у них нет).
    # Гарантия BOUNDED, а не FORM_EXACT: дуговой разделитель не выражается
    # вовсе (у `path` дугового параметра нет — 14 из 2 313 на K2), а
    # разделитель, чья плоскость смещена от своего уровня, тоже остаётся
    # атомом, потому что смещения нет у самой операции (4 из 2 313).
    "create_room_separator": _direct(
        "create_room_separator", "_lift_room_separator",
        sources=("L0:OST_RoomSeparationLines",),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("an arc separator has no expressible parameter and a "
                    "chord would silently straighten it; a separator whose "
                    "plane is offset from its own level has no offset "
                    "parameter either — both stay typed atoms")),

    # The op exists, but current frozen capture lacks a mandatory source fact.
    "create_dimension": ReverseContract(
        "create_dimension", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "L0 has no owner-view basis and Dimension.References",
        sources=("L0:OST_Dimensions",),
        limitation="must extend annotation capture before a lifter is legal"),
    # wave/opening (03.08.2026). Операция ЕСТЬ, обратного хода НЕТ, и это
    # заявлено здесь, а не подразумевается: замороженная строка L0 1.0 не
    # несёт НИ ОДНОГО обязательного входа проёма — ни Opening.Host (носитель),
    # ни Opening.BoundaryRect/BoundaryCurves (границу). Объявить DIRECT
    # значило бы обещать подъём, которого нет, а этот манифест существует
    # ровно затем, чтобы такие обещания не протухали молча.
    "create_opening": ReverseContract(
        "create_opening", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "L0 carries neither Opening.Host nor the opening boundary "
        "(BoundaryRect / BoundaryCurves)",
        sources=("L0:OST_SWallRectOpening", "L0:OST_FloorOpening",
                 "L0:OST_RoofOpening"),
        limitation=("capture must start reading Opening.Host and the "
                    "boundary before a lifter is legal; the shaft variety is "
                    "additionally outside the forward op itself")),
    # 03.08.2026: ПЕРЕВЕДЁН ИЗ capture_gap В direct, и повод — замер, а не
    # желание. Захват ограждений (``sketch_extract.RailingPathRecord``:
    # Railing.GetPath, HasHost/HostId, STAIRS_RAILING_BASE_LEVEL_PARAM) поехал
    # ещё 29.07 и снимает данные в проде; k2_ar_rd_v9 несёт 31 строку захвата,
    # из них 28 свободных ограждений с путём и базовым уровнем. То есть
    # прежняя формулировка «L0 has neither a railing path nor hosted placement
    # position» перестала быть правдой в первой своей половине — а манифест
    # существует ровно затем, чтобы такие утверждения не протухали молча.
    #
    # ВТОРАЯ ПОЛОВИНА ОСТАЛАСЬ ПРАВДОЙ ЦЕЛИКОМ, поэтому гарантия BOUNDED, а не
    # FORM_EXACT: ЛЕСТНИЧНОЕ ограждение не инвертируется вовсе — позиции
    # (Treads/Stringer) в API нет геттера ни на одной из шести версий.
    "create_railing": _direct(
        "create_railing", "_lift_railing",
        sources=("L0:OST_Railings", "L0:OST_StairsRailing", "side:sketch"),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only variety=path is inverted; a hosted railing stays an "
                    "atom because RailingPlacementPosition has no getter on "
                    "any shipped version, and re-emitting it as a free path "
                    "railing would silently drop its host")),

    # Current-state reverse representations that are intentionally not the
    # same high-level op.
    "create_group": ReverseContract(
        "create_group", ReverseMode.COMPOSED, ReverseGuarantee.BOUNDED,
        "group relations fold member leaves; optional native-group bridge "
        "re-composes a create_group program",
        sources=("side:group",),
        entrypoints=("component_to_group_program",),
        representation_ops=("create_group",)),
    "create_pipe_system": ReverseContract(
        "create_pipe_system", ReverseMode.DECOMPOSED, ReverseGuarantee.BOUNDED,
        "snapshot stores physical segments; reverse emits elementary pipes",
        sources=("L0:OST_PipeCurves", "side:mep_system"),
        representation_ops=("create_pipe",),
        limitation="graph intent and auto-created fittings are not inverted"),
    "route_pipe_system": ReverseContract(
        "route_pipe_system", ReverseMode.DECOMPOSED, ReverseGuarantee.BOUNDED,
        "snapshot stores physical segments; reverse emits elementary pipes",
        sources=("L0:OST_PipeCurves", "side:mep_system"),
        representation_ops=("create_pipe",),
        limitation="routing intent and auto-created fittings are not inverted"),
    "route_duct_system": ReverseContract(
        "route_duct_system", ReverseMode.DECOMPOSED, ReverseGuarantee.BOUNDED,
        "snapshot stores physical segments; reverse emits elementary ducts",
        sources=("L0:OST_DuctCurves", "side:mep_system"),
        representation_ops=("create_duct",),
        limitation="routing intent and auto-created fittings are not inverted"),

    # Same-document rebuild pins existing definitions instead of pretending a
    # fresh-document inverse exists.
    "create_type": ReverseContract(
        "create_type", ReverseMode.PINNED_EXISTING, ReverseGuarantee.NONE,
        "same-document materialization references the existing type ElementId",
        sources=("L0:type references",),
        limitation="fresh-document type reconstruction is not implemented"),
    "load_family": ReverseContract(
        "load_family", ReverseMode.EXTERNAL_SOURCE, ReverseGuarantee.NONE,
        "a loaded Revit family does not retain a reproducible source RFA path",
        sources=("L0:family references",),
        limitation="an external artifact store is required for inversion"),

    # Final-state snapshots cannot recover which historical mutation produced
    # that state. Replaying these would duplicate or destroy effects.
    "change_type": ReverseContract(
        "change_type", ReverseMode.STATE_TRANSITION, ReverseGuarantee.NONE,
        "final state carries the current type, not a historical type change"),
    "set_param": ReverseContract(
        "set_param", ReverseMode.STATE_TRANSITION, ReverseGuarantee.NONE,
        "final state cannot distinguish an explicit set from original state"),
    "move_elements": ReverseContract(
        "move_elements", ReverseMode.STATE_TRANSITION, ReverseGuarantee.NONE,
        "final geometry carries no recoverable movement delta or target set"),
    "delete": ReverseContract(
        "delete", ReverseMode.STATE_TRANSITION, ReverseGuarantee.NONE,
        "deleted identities are absent from a final-state snapshot"),
}


def _validate_manifest(contracts: Mapping[str, ReverseContract]) -> None:
    write_ops = {
        name for name, op in spec.OPS.items()
        if op.family in spec.WRITE_FAMILIES
    }
    keys = set(contracts)
    if keys != write_ops:
        missing = sorted(write_ops - keys)
        extra = sorted(keys - write_ops)
        raise AssertionError(
            f"reverse manifest must cover every write op; missing={missing}, "
            f"extra={extra}")
    for name, contract in contracts.items():
        if contract.op_name != name:
            raise AssertionError(f"reverse manifest key mismatch for {name}")


_validate_manifest(_CONTRACTS)
REVERSE_CONTRACTS: Mapping[str, ReverseContract] = MappingProxyType(_CONTRACTS)


def assert_lift_emission(op_name: str) -> ReverseContract:
    """Guard a same-op L1 emission against the exhaustive manifest."""
    contract = REVERSE_CONTRACTS.get(op_name)
    if contract is None or not contract.direct_same_op_lift:
        mode = contract.mode.value if contract is not None else "undeclared"
        raise ReverseContractError(
            f"reverse lift may not emit {op_name!r} (mode={mode})")
    return contract


def assert_composed_emission(op_name: str) -> ReverseContract:
    """Guard a post-lift composed operation against the same manifest."""
    contract = REVERSE_CONTRACTS.get(op_name)
    if contract is None or contract.mode is not ReverseMode.COMPOSED:
        mode = contract.mode.value if contract is not None else "undeclared"
        raise ReverseContractError(
            f"reverse composition may not emit {op_name!r} (mode={mode})")
    return contract


def reverse_contract_report() -> dict[str, Any]:
    counts = {mode.value: 0 for mode in ReverseMode}
    for contract in REVERSE_CONTRACTS.values():
        counts[contract.mode.value] += 1
    return {
        "schema": REVERSE_CONTRACT_SCHEMA,
        "write_ops": len(REVERSE_CONTRACTS),
        "direct_same_op_lifts": sum(
            contract.direct_same_op_lift
            for contract in REVERSE_CONTRACTS.values()),
        "modes": counts,
        "contracts": [
            REVERSE_CONTRACTS[name].to_dict()
            for name in sorted(REVERSE_CONTRACTS)
        ],
    }
