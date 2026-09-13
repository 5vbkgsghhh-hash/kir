"""WHAT AN OPERATION CAN DO — ONE QUESTION, ONE DOOR, FIVE AXES.

The registry (`spec.OPS`) answers WHAT an operation means: slots, effect, result
kind, postcondition, tolerances. It did NOT answer what the tree around it can
do with this operation, and asking that takes five different ways:

    backend   does the op compile to C# — and by which emitter
    preview   is the op drawn in the plan BEFORE the transaction
    witness   does the op carry an obligation checked after commit
    reverse   can the op be lifted back out of the model by that SAME op
    clash     does the op give the building a BODY that clash detection looks for

🔴 WHY THIS MODULE EXISTS, BY MEASUREMENT 07.09.2026. Before it, each axis had its own
carrier, and asking "what can `create_surface` do" meant knowing five
foreign modules by heart:

    backend   authoring._EMITTERS (72) + authoring._SOLO_PROGRAMS (5)
              + the `query_*` branches in compiler._emit_op (6)
    preview   preview._program_shape — a handwritten if/elif chain
    witness   translation_cert.REFINEMENT (77)
    reverse   reverse_contract.REVERSE_CONTRACTS (77)
    clash     clash_bundle.OP_NO_BODY (50) and its supplement

Four of the five carriers are ALREADY checked against the registry by their own guard, and as of 07.09
disagree with it by zero names. THE FIFTH IS CHECKED BY NOTHING: 64 operations out of 83
fall into `preview.OmitReason.OP_NOT_DRAWN`, and there was NOTHING to say which of them the language
PROMISES to draw and which it does not draw by its very nature. Silence here
reads as "everything is drawn", exactly as a clash blind spot with no reason
reads as the absence of a blind spot (`clash_bundle.OP_NO_BODY`, header).

🔴 THIS IS A PROJECTION, NOT A SIXTH TABLE. The precedent is `op_contract.py`, which,
by the same discipline, brings the registry, the grounding, and the certificate together into one document and
does NOT set up a second registry. It is the same here: `backend`, `witness`, `reverse`, and
`clash` are ASKED of their carriers live, not one name is copied
from there to here. A copy would be a second opinion about one fact — a named defect
of this tree, and it has already been paid for here twice (`spec.PLURAL_OPERAND_KINDS`,
header; `clash_bundle.REGISTRY_GAPS`, header).

This module has exactly one entry of its own — `PREVIEW_LIMITS`, and it exists
BECAUSE THE PREVIEW AXIS HAS NO CARRIER AT ALL. The shape is borrowed from
`reverse_contract.REVERSE_CONTRACTS`: a reason for every name, completeness
checked by the registry on import, and agreement with the live drawer checked
by the instrument `tests/test_the_registry_owns_every_capability.py`.

🔴 WHY THIS IS USEFUL TO A HUMAN AND TO THE MODEL. `kir ops <name>` and MCP print an operation's
contract. Before this module they could not say "this op is not drawn in the plan"
or "it cannot be lifted back" — and that is exactly the kind of knowledge an author
otherwise buys with time (the argument at `OpSpec.caveat`, 26.08.2026). Now one
call to `limits("create_surface")` answers for all five axes, and it answers
with a REASON, not with emptiness.
"""
from __future__ import annotations

from typing import Mapping

from kir import spec

__all__ = [
    "AXES",
    "PREVIEW_LIMITS",
    "AXIS_LAW",
    "capabilities",
    "limits",
    "axis_fact",
    "audit_capability_axes",
]

#: A CLOSED list of axes. A new axis must appear HERE and get both a
#: declaration and a live measurement: an axis without a measurement is a promise with no instrument.
AXES: tuple[str, ...] = ("backend", "preview", "witness", "reverse", "clash")


# ═════════════════════════════════════════════════════════════════════════
# THE PREVIEW AXIS: THE ONLY ONE THAT HAD NO CARRIER
# ═════════════════════════════════════════════════════════════════════════

#: WHY AN OP IS NOT DRAWN IN THE PLAN. The key is the op's name, the value is the reason.
#:
#: THE KIND OF LIST: **COMPLETE BY CONSTRUCTION AND CHECKABLE**. Completeness is held by
#: `audit_capability_axes()` (called on import): every op in the registry either
#: is drawn by the live `preview._program_shape`, or stands here with a reason.
#: There is no third bucket — the same law as `clash_bundle.OP_NO_BODY`.
#:
#: 🔴 THE REASONS CARRY DIFFERENT WEIGHT, AND THIS IS NAMED, NOT SMOOTHED OVER. Two of them
#: ARE DERIVED FROM THE REGISTRY and therefore cannot go stale:
#:
#:   * `family == "query"` — the op reads and creates nothing that can be
#:     drawn. 6 names, and not one is typed in here by hand;
#:   * `family == "modify"` — the op edits an EXISTING element, and the outline in
#:     the plan belongs to the op that created the element.
#:
#: The third — `NO_RULE_YET` — is NOT a derivation but a MEASUREMENT: the drawing rule simply has not
#: been written. It is said in one line for all names ON PURPOSE: composing 53
#: different "whys" would mean declaring a decision what is actually a gap, and
#: closing the finding with prose. A name leaves here only together with a branch in
#: `preview._program_shape` — and the instrument will REQUIRE it.
_QUERY_READS_NOTHING = (
    "оп читает модель и не создаёт элемента — рисовать в плане нечего "
    "(выведено из реестра: family == \"query\")")
_MODIFY_HAS_NO_OUTLINE_OF_ITS_OWN = (
    "оп правит существующий элемент; очерк в плане принадлежит опу, который "
    "этот элемент создал (выведено из реестра: family == \"modify\")")
_NO_RULE_YET = (
    "правило рисования для этого опа не написано — ЗАМЕРЕННЫЙ ПРОБЕЛ "
    "рисовальщика, а не свойство операции; план молчит о нём "
    "(preview.OmitReason.OP_NOT_DRAWN)")

#: Ops of the `modify` family whose outline IN THE PLAN DOES CHANGE after all, and so
#: the family-level derivation does NOT APPLY to them. Today there is one such op.
#:
#: `move_elements` moves something already drawn, and the plan does not show its shift:
#: this is the same class as the 07.09 finding about a door's host
#: (`docs/OPERATION_WITNESS_STAGE_RU.md`, addendum) — a shift of the same
#: program must be part of what the author sees. Recording its reason as
#: "edits someone else's element" would excuse a gap as a property of the op.
_MODIFY_THAT_MOVES_THE_OUTLINE: frozenset[str] = frozenset({"move_elements"})

#: Ops whose absence from the plan is a MEASURED GAP. The list is closed; a name
#: leaves only together with the appearance of a drawing branch.
_PREVIEW_GAP: frozenset[str] = frozenset({
    "author_family",
    "create_adaptive_component",
    "create_angular_dimension",
    "create_area_load",
    "create_area_reinforcement",
    "create_beam_system",
    "create_building_pad",
    "create_curtain_grid_line",
    "create_dimension",
    "create_directshape",
    "create_extrusion_roof",
    "create_face_wall",
    "create_filled_region",
    "create_floor_by_contour",
    "create_floor_plan",
    "create_foundation",
    "create_grid",
    "create_group",
    "create_level",
    "create_line_load",
    "create_multi_segment_grid",
    "create_multistory_stairs",
    "create_opening",
    "create_path_of_travel",
    "create_pipe_system",
    "create_point_load",
    "create_railing",
    "create_room_separator",
    "create_site_subregion",
    "create_slab_edge",
    "create_solid_boolean",
    # `create_solid_extrusion`, `create_solid_revolve`, and `create_solid_blend` left here
    # on 08.09.2026 together with drawing branches (`preview._BODY_OPS`: a trace from the profile,
    # a ring of radii for the revolved body; the approximation is named LEVEL_NOT_BOUND).
    "create_solid_sweep",
    "create_space",
    "create_stairs_landing",
    "create_stairs_run",
    "create_surface",
    "create_tag",
    "create_text",
    "create_topography",
    "create_truss",
    "create_type",
    "create_wall_foundation",
    "create_wall_sweep",
    "create_wall_type",
    "load_family",
    "move_elements",
    "route_duct_system",
    "route_pipe_system",
    "transfer_family",
    "transfer_material",
})


def _preview_limits() -> dict[str, str]:
    """Assemble the PREVIEW axis: a derivation from the registry plus the measured remainder."""
    out: dict[str, str] = {}
    for name, ospec in spec.OPS.items():
        if ospec.family == "query":
            out[name] = _QUERY_READS_NOTHING
        elif (ospec.family == "modify"
                and name not in _MODIFY_THAT_MOVES_THE_OUTLINE):
            out[name] = _MODIFY_HAS_NO_OUTLINE_OF_ITS_OWN
    for name in sorted(_PREVIEW_GAP):
        out.setdefault(name, _NO_RULE_YET)
    return out


PREVIEW_LIMITS: dict[str, str] = _preview_limits()


# ═════════════════════════════════════════════════════════════════════════
# A LIVE MEASUREMENT OF EACH AXIS. NOT ONE NAME IS COPIED — EVERYTHING IS ASKED.
# ═════════════════════════════════════════════════════════════════════════

def _fact_backend() -> frozenset[str]:
    """Ops that HAVE an emission path. Asked of three dispatchers.

    Writing ops travel through `authoring.emit_program` (`_EMITTERS`, the spokes
    `*_emit.py`) or as a whole program (`_SOLO_PROGRAMS`). Reading ops travel
    the `compiler._emit_op` chain, which has no dict but does have an HONEST
    tail — `AssertionError("unreachable: <name>")`. We ask by behaviour, not
    by reading the source: parsing a function's text would lie on the very first
    reshuffling of branches (`tests/…a-source-reading-test…`, finding 26.08).
    """
    from kir import authoring, compiler

    found = set(authoring._EMITTERS) | set(authoring._SOLO_PROGRAMS)
    for name, ospec in spec.OPS.items():
        if name in found or ospec.family in spec.WRITE_FAMILIES:
            continue
        try:
            compiler._emit_op({"op": name, "id": "__probe__"}, "2026")
        except AssertionError:
            continue          # no branch — "unreachable"
        except Exception:
            found.add(name)   # a branch exists, tripped over an unnamed slot
        else:
            found.add(name)
    return frozenset(found)


def _fact_preview() -> frozenset[str]:
    """Ops that have a plan-drawing branch.

    Asked by BEHAVIOUR. `_program_shape` catches `KeyError/TypeError/
    IndexError/ValueError` from its own branch and answers `NO_GEOMETRY`; if there is no branch, it
    answers `OP_NOT_DRAWN`. The difference between the two reasons is exactly the fact
    being sought, and it is declared by the drawer itself (`OmitReason`, header).
    """
    from kir import preview

    found = set()
    for name in spec.OPS:
        _element, why = preview._program_shape(
            {"op": name, "id": "__probe__"}, "__probe__", {})
        if why is not preview.OmitReason.OP_NOT_DRAWN:
            found.add(name)
    return frozenset(found)


def _fact_witness() -> frozenset[str]:
    """Ops that carry an obligation checked after commit."""
    from kir import translation_cert

    return frozenset(translation_cert._ensure_table())


def _fact_reverse() -> frozenset[str]:
    """Ops that have a LIVE lifter, not just an entry in the manifest.

    🔴 THE MEASUREMENT IS TAKEN FROM A DIFFERENT CARRIER THAN THE DECLARATION, AND THIS IS NOT NITPICKING.
    The declaration reads `reverse_contract.REVERSE_CONTRACTS`. If the measurement
    read the same thing, the check could not fail under ANY state of the code —
    that is exactly what happened with the first edition of this file, and it was caught
    by the 07.09 control mutation (removing a name from the hand-written copy left the instrument
    green). A check that cannot fail is WORSE than a missing one: it
    counts as part of the suite. So here the lifter dispatcher is asked instead
    (`decompile.lift.LIFTER_TABLE`) — the one that actually lifts.
    """
    from kir.decompile import lift

    return frozenset(op for _kind, op in lift.LIFTER_TABLE.values())


def _fact_clash() -> frozenset[str]:
    """Ops whose category is known to the body-making table AND is eligible for a body.

    THE SAME ARGUMENT AS `_fact_reverse`. The declaration reads
    `clash_bundle.OP_NO_BODY`, while `body_making_ops()` is the COMPLEMENT of the same
    table: checking them against each other means checking the table against itself.
    The independent carrier is `clash.hulls.KIND_TABLE`, a closed table of
    Revit CATEGORIES with an `eligible` field, and the bridge to it is
    `clash_bundle.op_categories`, which asks the registry
    (`spec.op_result_categories`), not its own list.
    """
    from kir import clash_bundle
    from kir.clash import hulls

    return frozenset(
        name for name in spec.OPS
        if any(getattr(hulls.KIND_TABLE.get(cat), "eligible", False)
               for cat in clash_bundle.op_categories(name)))


#: THE DIRECTION OF THE LAW FOR EACH AXIS — AND AN HONEST REASON FOR ONE-SIDEDNESS.
#:
#: `both`  the declaration and the measurement are DIFFERENT carriers, and must match name for name.
#: `subset` the measurement is complete on only one side; the other side is named, not
#:          silenced. Demanding equality there would mean declaring a defect out of
#:          something the tree has already worked out and decided.
AXIS_LAW: dict[str, tuple[str, str]] = {
    "backend": ("both", ""),
    "preview": ("both", ""),
    "witness": ("both", ""),
    # The measurement is the lifter dispatcher, by CATEGORY. Five ops in the manifest
    # are lifted not by category but some other way (`create_floor_by_contour`,
    # `create_curtain_grid_line`, `place_family`, both drafts), and their
    # absence from `LIFTER_TABLE` is not a defect. The reverse direction IS a defect:
    # a live lifter that the manifest did not call a "direct move".
    "reverse": ("fact_subset_of_declared",
                "пять прямых опов поднимаются не по категории — "
                "их нет в LIFTER_TABLE намеренно"),
    # The measurement is a CATEGORY's eligibility for a body. `create_face_wall` has
    # an eligible category (`OST_Walls`) but gives no body: `FaceWall` is not `Wall`, and
    # it has no `LocationCurve` at all — this is a DECOMPILED independence of two
    # quantities (`test_clash_in_the_receipt.py`, 11.08.2026). The reverse
    # direction IS a defect: a body declared where the category does not carry it.
    "clash": ("declared_subset_of_fact",
              "create_face_wall: категория годна, а оболочки нет — "
              "независимость двух величин разобрана 11.08.2026"),
}


_FACT = {
    "backend": _fact_backend,
    "preview": _fact_preview,
    "witness": _fact_witness,
    "reverse": _fact_reverse,
    "clash": _fact_clash,
}


def axis_fact(axis: str) -> frozenset[str]:
    """A live measurement of the axis: the set of ops the axis CAN do today."""
    if axis not in _FACT:
        raise KeyError(f"ось {axis!r} не объявлена; известны: {AXES}")
    return _FACT[axis]()


# ═════════════════════════════════════════════════════════════════════════
# THE REGISTRY'S DECLARATION. FOUR AXES ARE DERIVED, THE FIFTH IS DECLARED HERE.
# ═════════════════════════════════════════════════════════════════════════

def _declared_limits(name: str) -> dict[str, str]:
    ospec = spec.OPS[name]
    out: dict[str, str] = {}

    # BACKEND. A registry op that does not compile is not a "limited
    # capability" but a dead entry: the language promises the program execution.
    # So the declaration here is UNCONDITIONAL, and a mismatch with the fact means
    # a missing emitter, not a narrowed-down op.

    # PREVIEW. The only axis with its own carrier in this file.
    reason = PREVIEW_LIMITS.get(name)
    if reason is not None:
        out["preview"] = reason

    # WITNESS. Derived from the registry: the witness checks what the commit
    # WROTE. A reading op writes nothing, and has no obligation by
    # construction, not by an oversight.
    if ospec.family not in spec.WRITE_FAMILIES:
        out["witness"] = (
            "оп ничего не записывает — проверять после коммита нечего "
            "(выведено из реестра: family не пишущее)")

    # REVERSE. The carrier is the reverse-move manifest; the reason is taken FROM THERE
    # verbatim, so as not to introduce a second opinion about the same fact.
    from kir import reverse_contract

    contract = reverse_contract.REVERSE_CONTRACTS.get(name)
    if contract is None:
        out["reverse"] = (
            "оп ничего не создаёт — поднимать из модели нечего "
            "(выведено из реестра: family не пишущее)")
    elif contract.mode is not reverse_contract.ReverseMode.DIRECT:
        out["reverse"] = f"{contract.mode.value}: {contract.reason}"

    # CLASH. The carrier is `clash_bundle.OP_NO_BODY`; the reason is taken from there.
    # 🔴 AND ON TOP OF IT — A REGISTRY VETO. An op that creates nothing gives no
    # body by construction, and "no reason in the table" for it means not "there is a
    # body" but "a name fell through". The complement (`body_making_ops`) cannot
    # tell the difference on its own: it declares everything not in the table a body.
    from kir import clash_bundle

    no_body = clash_bundle.OP_NO_BODY.get(name)
    if no_body is not None:
        out["clash"] = no_body
    elif ospec.family not in spec.WRITE_FAMILIES:
        out["clash"] = (
            "оп ничего не создаёт — тела у него нет по построению "
            "(вето реестра: family не пишущее)")

    return out


def limits(op_name: str) -> dict[str, str]:
    """What an op CANNOT do — axis by axis, with a reason for each.

    The answer is COMPLETE: an axis not present here is one the op can do. An empty dict means
    "can do all five", not "we did not look".
    """
    if op_name not in spec.OPS:
        raise KeyError(f"{op_name!r} — не операция реестра")
    return _declared_limits(op_name)


def capabilities(op_name: str) -> frozenset[str]:
    """What an op CAN do: the axes minus the named restrictions."""
    return frozenset(AXES) - frozenset(limits(op_name))


def declared_axis(axis: str) -> frozenset[str]:
    """The set of ops the declaration says "can do" on this axis."""
    if axis not in AXES:
        raise KeyError(f"ось {axis!r} не объявлена; известны: {AXES}")
    return frozenset(n for n in spec.OPS if axis not in limits(n))


# ═════════════════════════════════════════════════════════════════════════
# A COMPLETENESS GUARD, RUN ON IMPORT
# ═════════════════════════════════════════════════════════════════════════

def audit_capability_axes() -> tuple[str, ...]:
    """Every name in `PREVIEW_LIMITS` must be an op of the registry.

    Agreement of the declaration with the LIVE fact is a question for the instrument, not for import:
    measuring the `backend` axis compiles code, and `preview` builds shapes, and
    paying that cost on every `import kir.capability` is not acceptable. Only what
    costs zero is held here — and it is held fail-closed.
    """
    problems: list[str] = []
    for name in sorted(PREVIEW_LIMITS):
        if name not in spec.OPS:
            problems.append(
                f"{name}: PREVIEW_LIMITS называет оп вне реестра")
    stray = sorted(_PREVIEW_GAP - set(spec.OPS))
    for name in stray:
        problems.append(f"{name}: _PREVIEW_GAP называет оп вне реестра")
    return tuple(problems)


_problems = audit_capability_axes()
if _problems:
    raise AssertionError(
        "kir.capability разошёлся с реестром:\n  " + "\n  ".join(_problems))
del _problems
