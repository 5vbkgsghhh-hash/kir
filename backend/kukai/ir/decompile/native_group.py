"""Native Revit group op — bridge from the component library to a forward
`create_group` authoring op, plus its offline fidelity model.

The component library (``component.py``) already turns a building's repeated
subtrees into ``PlaceGroupOp``s: one localized ``ComponentDefinition`` drawn
once, and N ``ComponentInstance``s each carrying the occurrence's ABSOLUTE
canonical origin (``offset_mm``).  On rebuild we currently materialize each
occurrence as its own N separate elements.  This module lets a repeat instead
be rebuilt as a **native Revit group**: the members are authored ONCE at the
first occurrence, grouped with ``doc.Create.NewGroup``, and each further
occurrence is a ``doc.Create.PlaceGroup`` at the right offset — so the rebuilt
model edits the way a live modeller's does (edit one instance, all update).

This module is the OFFLINE half: it derives the placement data and PROVES,
without Revit, that the native-group expansion reproduces exactly the same
absolute leaf multiset as the N-element fallback (hence as the source — the
component layer already proved the N-element path is C-RT-lossless).  The C#
emission (``authoring._emit_group``) consumes ``NativeGroupOp`` verbatim.

Placement math (the LOT31 C-RT bug class — read ``ComponentInstance`` doc):

* Occurrence 0's members are authored at their ABSOLUTE positions
  (``instantiate(defn, occ_origin_0)``).  ``NewGroup`` then makes Revit choose a
  group origin ``O0`` we do NOT know at emit time.
* Occurrence k is occurrence 0 translated by ``delta_k = occ_origin_k -
  occ_origin_0`` — a subtraction of two ABSOLUTE origins, origin-independent
  (never assumes ``occ_origin_0 == 0``).  Since ``PlaceGroup`` aligns the group
  ORIGIN to its ``location`` argument, occurrence k is placed at ``O0 + delta_k``
  and ``O0`` cancels in the members' absolute coordinates.
* Offline we don't have ``O0`` (Revit picks it), and we don't need it: the
  fidelity model reproduces occurrence k as ``instantiate(defn, occ_origin_0 +
  delta_k) == instantiate(defn, occ_origin_k)`` — byte-identical to the
  N-element path, so equality is by construction, not by luck.

Fail-closed: the bridge REFUSES (returns ``None``) rather than emit a wrong or
lossy group — a single occurrence, an empty definition, or a place-op without
``FidelityCanon`` proof all fall back to the plain N-element path.  In
particular, TemplateCanon may discover geometrically identical floors bound to
different Levels; those are analysis components, not executable native groups,
until a per-instance binding contract proves Revit's level mapping.

Inert / additive / opt-in: nothing imports this in a hot path;
``native_group_enabled()`` is default OFF; frozen L0 untouched; universal (no
LOT31 hardcoding).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from kukai.ir.decompile.component import (
    ComponentDefinition,
    ComponentInstance,
    ComponentSchemaError,
    PlaceGroupOp,
    _abs_multiset,
    instantiate,
)
from kukai.ir.decompile.fold import _round_mm
from kukai.ir.decompile.l1_schema import L1Node

Vec3 = tuple[float, float, float]
_ZERO = (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Flag (inertness contract) — parallel to component.component_enabled()
# ---------------------------------------------------------------------------


def native_group_enabled() -> bool:
    """Opt-in gate for the rebuild bridge choosing group-vs-N; default OFF."""

    return os.getenv("KUKAI_IR_NATIVE_GROUP", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ---------------------------------------------------------------------------
# Native-group op — the forward data the C# emitter consumes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NativeGroupOp:
    """One native Revit group: definition members + per-occurrence deltas.

    * ``definition``      the localized ComponentDefinition (drawn once).
    * ``base_origin_mm``  occurrence 0's ABSOLUTE canonical origin: where the
                          definition members are authored (``instantiate(defn,
                          base_origin_mm)`` reproduces occurrence 0 exactly).
    * ``placement_deltas_mm``  one ``delta_k = occ_origin_k - base_origin_mm``
                          per ADDITIONAL occurrence (k>=1); occurrence 0 is the
                          members themselves and is NOT in this list.  These are
                          the exact XYZ offsets ``PlaceGroup`` needs relative to
                          the group's live origin ``O0`` (emit adds ``O0`` at
                          runtime; see module doc).
    * ``occurrence_count``  total occurrences == 1 + len(placement_deltas_mm).
    """

    def_hash: str
    definition: ComponentDefinition
    base_origin_mm: Vec3
    placement_deltas_mm: tuple[Vec3, ...]
    label: str

    @property
    def occurrence_count(self) -> int:
        return 1 + len(self.placement_deltas_mm)

    @property
    def member_count(self) -> int:
        return self.definition.leaf_count


def _sub(a: Vec3, b: Vec3) -> Vec3:
    """delta = a - b on the mm grid (both ABSOLUTE origins; origin-independent)."""

    return (_round_mm(a[0] - b[0]), _round_mm(a[1] - b[1]), _round_mm(a[2] - b[2]))


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (_round_mm(a[0] + b[0]), _round_mm(a[1] + b[1]), _round_mm(a[2] + b[2]))


def group_op_from_place_op(place_op: PlaceGroupOp) -> NativeGroupOp | None:
    """Bridge a component-library ``PlaceGroupOp`` to a ``NativeGroupOp``.

    FAIL-CLOSED: returns ``None`` (caller keeps the plain N-element path) when
    the repeat cannot be grouped correctly:

    * fewer than 2 occurrences — a native group of one instance buys nothing and
      only risks divergence; the single occurrence stays N elements.
    * an empty definition (0 members) — nothing to group.
    * no concrete fidelity proof — template equality alone intentionally ignores
      storey bindings and cannot authorize a model mutation.

    Otherwise the deltas are ``occ_origin_k - occ_origin_0`` for every
    occurrence after the first, in the place-op's deterministic instance order
    (occurrences are ordered by absolute origin then path in ``build_library``).
    """

    if not isinstance(place_op, PlaceGroupOp):
        raise ComponentSchemaError(
            "group_op_from_place_op needs a PlaceGroupOp")
    instances = place_op.instances
    if len(instances) < 2:
        return None
    if place_op.definition.leaf_count == 0:
        return None
    if not place_op.fidelity_proven:
        return None
    base_origin = instances[0].offset_mm            # ABSOLUTE occ_origin_0
    deltas = tuple(
        _sub(inst.offset_mm, base_origin)           # occ_origin_k - occ_origin_0
        for inst in instances[1:]
    )
    return NativeGroupOp(
        def_hash=place_op.def_hash,
        definition=place_op.definition,
        base_origin_mm=base_origin,
        placement_deltas_mm=deltas,
        label=place_op.definition.label,
    )


# ---------------------------------------------------------------------------
# Offline fidelity model — proves the native-group path is lossless
# ---------------------------------------------------------------------------


def expand_group_op(op: NativeGroupOp) -> list[L1Node]:
    """Expand the native-group op back into a flat absolute-leaf list.

    Models exactly what the C# emission produces geometrically: occurrence 0's
    members at ``base_origin`` plus, for each delta, the same members translated
    by ``delta`` (i.e. authored at ``base_origin + delta == occ_origin_k``).
    Ids are regenerated per placement so N placements never collide — the same
    ``regenerate_ids`` discipline the N-element path uses, so the ABSOLUTE
    geometry multiset (``canon_op`` ignores ids) is comparable and equal.
    """

    if not isinstance(op, NativeGroupOp):
        raise ComponentSchemaError("expand_group_op needs a NativeGroupOp")
    out: list[L1Node] = []
    # occurrence 0 — the authored definition members
    out.extend(instantiate(
        op.definition, op.base_origin_mm, instance_index=0,
        regenerate_ids=False))
    # occurrences 1..N — definition translated to base_origin + delta
    for k, delta in enumerate(op.placement_deltas_mm, start=1):
        placement_origin = _add(op.base_origin_mm, delta)
        out.extend(instantiate(
            op.definition, placement_origin, instance_index=k,
            regenerate_ids=False))
    return out


def assert_group_matches_place_op(
    op: NativeGroupOp, place_op: PlaceGroupOp,
) -> None:
    """Raise unless the native-group expansion == the N-element expansion.

    The native-group placement math is fidelity-preserving iff expanding the
    group op reproduces the SAME absolute-op multiset the plain N-element
    ``PlaceGroupOp`` does *and* the latter carries its separate source-fidelity
    proof.  Any divergence is fail-closed before emission.
    """

    if not place_op.fidelity_proven:
        raise ComponentSchemaError(
            "native group source fidelity is not proven")
    group_abs = _abs_multiset(expand_group_op(op))
    n_element_abs = _place_op_abs_multiset(place_op)
    if group_abs != n_element_abs:
        raise ComponentSchemaError(
            "native group expansion does not match the N-element expansion "
            "(placement-math divergence — refuse to emit)")


def _place_op_abs_multiset(place_op: PlaceGroupOp) -> dict[str, int]:
    """The absolute-op multiset the plain N-element rebuild of a PlaceGroupOp
    materializes (mirrors component.expand_library over one op)."""

    leaves: list[L1Node] = []
    for instance in place_op.instances:
        leaves.extend(instantiate(
            place_op.definition, instance.offset_mm,
            instance_index=instance.instance_index, regenerate_ids=False))
    return _abs_multiset(leaves)


# ---------------------------------------------------------------------------
# IR seam — the create_group op-dict a NativeGroupOp becomes on rebuild
# ---------------------------------------------------------------------------


def native_group_op_to_ir(
    op: NativeGroupOp,
    member_ops: list[dict],
    *,
    op_id: str,
    name: str | None = None,
) -> dict:
    """Assemble the ``create_group`` IR op-dict the compiler consumes.

    ``member_ops`` are the DEFINITION's members already materialized as
    PRE-GROUNDED authoring op-dicts, authored at ``op.base_origin_mm`` (i.e.
    ``instantiate(definition, base_origin_mm)`` translated to authoring ops).
    That leaf->authoring-op materialization is the ONE piece this bridge does
    NOT own yet (no such materializer exists in the codebase — recompile.py
    emits C# straight from leaves, not op-dicts); it is the documented next
    wiring step behind ``native_group_enabled()``.  This function owns the rest:
    the placement deltas and the name, so the seam is a single, tested call.

    Callers MUST keep the N-element fallback: if they cannot materialize the
    members faithfully, emit the plain N ops instead — never a lossy group.
    """

    if not isinstance(op, NativeGroupOp):
        raise ComponentSchemaError("native_group_op_to_ir needs a NativeGroupOp")
    ir: dict = {
        "op": "create_group",
        "id": op_id,
        "members": list(member_ops),
        "placements": [list(d) for d in op.placement_deltas_mm],
    }
    if name is not None:
        ir["name"] = name
    return ir


__all__ = [
    "NativeGroupOp",
    "assert_group_matches_place_op",
    "expand_group_op",
    "group_op_from_place_op",
    "native_group_enabled",
    "native_group_op_to_ir",
]
