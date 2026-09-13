"""THE VIEWER'S HONESTY DICTIONARY — why color here means TRUST, not
category.

An ordinary BIM viewer colors by category: walls grey, pipes blue. Such a
viewer is physically unable to show the difference between "this wall was
built by an operation that has live runs" and "there's an atom here: the
lift refused, all we know is a bounding box." Both will be grey walls,
and for three hours a person will trust a picture that never promised
them that.

That's why the OPPOSITE decision was made here, and it is load-bearing:

    THE ELEMENT'S BASE COLOR = THE STRENGTH OF THE CLAIM ABOUT IT.
    THE ELEMENT'S SHAPE = THE ACCURACY OF THE GEOMETRY WE HAVE.

The second is not a metaphor. An element for which only a bounding box is
known is drawn as A BOX, not as a wall: we don't have a wall, we have a
box. A building where 99% of the shells are bounding boxes MUST look like
a field of boxes, because that is the truth about what we know of it. A
smooth grey wall in place of a bounding box is exactly the "a witness
signed an axis it never read" defect, just drawn on screen.

THE MEASUREMENT THIS DECISION RESTS ON (10.08.2026, `clash.snapshot` +
`tree.json`, the real corpus `backend/backend/data/decompile`):

| parse                 | shells   | Aabb (bounding box) | Prism/PrismSet | Capsule         |
|------------------------|---------:|----------------------:|-----------------:|-----------------:|
| `демо-v3`             |   84 120 | 84 027 (99.89 %)      |    93 (0.11 %)   |       0 (0 %)    |
| `k2_ar_rd_v15`        |   47 635 | 47 318 (99.33 %)      |   317 (0.67 %)   |       0 (0 %)    |
| `snowdon_plumb_v4`    |   31 904 | 15 648 (49.05 %)      |      0 (0 %)     | 16 256 (50.95 %) |
| `sob62_fas_r23_v19`   |    4 218 |  4 118 (97.63 %)      |   100 (2.37 %)   |       0 (0 %)    |

That is, in architecture there is practically no honest geometry TODAY,
while in engineering half of it is capsules. A viewer that hides this
would be lying about the main thing.

A SECOND MEASUREMENT, AND IT MADE THE HONESTY LAYER POSSIBLE. Joining a
shell to an L1 node by `source_element_id` is COMPLETE — not a single
shell without a node:

| parse               | shells   | join op          | join atom        | no node |
|----------------------|---------:|------------------:|------------------:|--------:|
| `sob62_fas_r23_v19` |    4 218 |  2 167 (51.38 %) |  2 051 (48.62 %) |        0 |
| `демо-v3`           |   84 120 | 46 618 (55.42 %) | 37 502 (44.58 %) |        0 |
| `snowdon_plumb_v4`  |   31 904 | 31 840 (99.80 %) |     64 (0.20 %)  |        0 |

Zero in the last column is not luck but a condition of meaningfulness:
trust-based coloring, where part of the building is "don't know," must
have a state for that. It has one (`UNKNOWN`).

AND IT IS NOT EMPTY — THIS IS A MEASUREMENT THAT OVERTURNED THE PREVIOUS
EDITION OF THIS PARAGRAPH. It used to say here "on this corpus it is
empty," derived from three parses that have a `tree.json`. A full sweep
of the corpus refuted that: **out of 67 parses with an L0 stream, only 52
have an L1 tree.** For the remaining 15 (`k2_ar_rd_v15`,
`snowdon_plumb_v5`, and others) there is NOTHING TO JOIN a shell to, and
`UNKNOWN` there is 100%, not zero. This is exactly the "boundary set up
by reasoning instead of measurement" that the package considers its own
main class of defect, and it nearly slipped through into a
comment-as-specification.

The practical consequence for the picture: the viewer must color such
buildings ENTIRELY in the "unknown" state and print the reason from
`read_l1_honesty(...)[1]["reason"]`. A grey building, honestly labeled
"no L1 nodes," is useful; the same building colored as proven is exactly
the defect this whole module was written against.

A TRAP THIS MODULE FELL INTO AND CLIMBED OUT OF (recorded so it isn't
repeated). The first join measurement gave 32.7–37.9% of shells "with no
L1 node" — and that was an INSTRUMENT DEFECT, not a fact about the
buildings: the tree walk read only nodes' `payload` and did not read
`members` on `atom_cluster` / `row` / `grid_array`, where COLLAPSED atoms
live (on демо-v3, 118 such clusters). An instrument that covers only
part of its own range is worse than having none — that's why
`iter_l1_nodes` walks both `children` and `members`, and there is a test
for it.

A REMOVED STATE, AND THIS IS MY MISTAKE, NOT SOMEONE ELSE'S.
`Trust.CLASH_REFUTED` used to stand here — "a clash edge cleared by a
named rule." It was removed, and not because the source never appeared
(it did: `Modality.REFUTED` and `GraphEdge.refuted_by` in
`building_graph`, a live measurement on демо-v3 — 5 941 edges cleared by
the rule `host_does_not_separate_exactly_two_rooms`), but because it was
an AXIS CONFLATION. `Trust` answers the question "how strong is the claim
that the ELEMENT is such"; a refutation, on the other hand, is a property
of the RELATION between two elements. Coloring a door as "refuted"
because its edge to a room was cleared by a rule would mean accusing an
element that was read perfectly well — exactly the conflation this whole
coloring scheme was written to forbid.

The real signal lives on its own axis: `viewer.graph.FLAG_REFUTED` — a
bit meaning "this element has a REFUTED RELATION," plus a summary broken
down by rule NAMES.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

__all__ = (
    "AXES_ORDER",
    "AXES_UNJUDGEABLE",
    "HONESTY_SCHEMA",
    "Trust",
    "Fidelity",
    "ElementHonesty",
    "HonestyCensus",
    "iter_l1_nodes",
    "read_l1_honesty",
    "unproven_ops",
)

HONESTY_SCHEMA = "kir-viewer-honesty/1"


class Trust(str, Enum):
    """HOW STRONG the claim is that this element is what it claims to be
    at all.

    The order of values goes from strong to weak, and it is also the
    order of alarm in the viewer's color. The value reads as an answer to
    the question "what proves that exactly this is standing here."
    """

    #: The element is raised to a KIR operation, and this operation has
    #: live runs: it is not in `tool_doc.UNPROVEN`. The strongest thing
    #: that exists offline at all.
    OP_PROVEN = "op_proven"

    #: The element is raised to an operation, but the operation is listed
    #: in `tool_doc.UNPROVEN` (29 entries as of 10.08.2026): the gate
    #: compiles it, nobody has built it live. "Will compile" and "will
    #: build" are different claims, and mixing them in the picture is not
    #: allowed.
    OP_UNPROVEN = "op_unproven"

    #: The element is an ATOM: the lift refused and NAMED the reason
    #: (`payload.reason.code`). A rebuild will not build it. This is not
    #: a reading defect by itself — `generator_child` means "Revit's own
    #: generator makes it," and that is legitimate — but neither is it a
    #: building we know how to reproduce.
    ATOM = "atom"

    #: There is a shell, there is no L1 node. On the measured corpus it
    #: is EMPTY (0 out of 120 242). The state exists so that an
    #: occurrence would be visible if one ever appears.
    UNKNOWN = "unknown"



class Fidelity(str, Enum):
    """HOW ACCURATE the geometry is that we have about the element.

    Maps directly to `clash.hulls.GRADES` plus the degeneracy from
    `clash.hulls.hull_degeneracy`. The viewer must choose the SHAPE by
    this field, not just the shade: a bounding box drawn as a body is a
    lie about what is known.
    """

    #: `grade="conservative"`: the base's outline (`profile`), a band
    #: around the axis (`prism`), or a capsule along the axis with a
    #: cross-section from the data (`axis_section`). The shell CONTAINS
    #: the body and follows its shape.
    SHAPED = "shaped"

    #: `grade="coarse"`, `hull_source="bbox"`: only the bounding box is
    #: known. On `демо-v3` this is 99.89 % of elements. Drawn as A BOX.
    BOX_ONLY = "box_only"

    #: A zero-volume bounding box (`hull_degeneracy` != "ok"): a plane, a
    #: line, or a point. Measurement across the whole store — 64 357 out
    #: of 664 870 (9.7 %), and on `демо-v3` 32 165 out of 84 120 (38.2 %,
    #: all `OST_GenericModel`). Such a shell can prove NOTHING and must
    #: be visible separately.
    DEGENERATE = "degenerate"

    #: `grade="exact"` — unreachable BY INFERENCE
    #: (`hulls.UNREACHABLE_GRADE_REASONS`): no source proves the shell
    #: equals the body. Set up so that the unreachability is named,
    #: rather than looking like "not found."
    EXACT = "exact"

    #: THERE IS NO BODY AT ALL. The element is declared by the program,
    #: but `clash_bundle` refused to build its body and named the
    #: reason. This is NOT "zero volume" (`DEGENERATE`, where a body
    #: exists and is flat) and not "bounding box only" (`BOX_ONLY`, where
    #: a bounding box exists): here there is NOTHING, and on screen the
    #: element is held up only by an outline from the plan.
    #:
    #: THE MEASUREMENT ON 11.08.2026 THAT THIS STATE WAS SET UP FOR: a
    #: batch of six walls and a pipe WITHOUT a snapshot of the open model
    #: gives **0 bodies out of 7**, all seven — `needs_live_model`. Wall
    #: thickness and a pipe's outer diameter live in the TYPE, and
    #: offline there is nowhere to get them from. The same at scale:
    #: `snowdon_plumb_v4` — 905 bodies without a snapshot versus 16 247
    #: out of 16 257 (99.94 %) with one. A viewer that draws these seven
    #: walls as built would be lying about exactly what separates "I
    #: wrote a program" from "the building exists."
    NO_BODY = "no_body"


#: Atom reasons under which the atom is NORMAL, not a loss.
#: `generator_child` means "Revit's own generator spawns this element"
#: (nested families, mullions behind `Mullion.Lock`): there is NOT
#: SUPPOSED to be an op for it, and coloring it as alarming would mean
#: calling for a fix to something that isn't broken. Measurement on
#: `sob62_fas_r23_v19`: 2 152 out of 2 412 atoms (89.2 %) are exactly
#: `generator_child`.
BENIGN_ATOM_REASONS: frozenset[str] = frozenset({"generator_child"})


@dataclass(frozen=True, slots=True)
class ElementHonesty:
    """Everything the viewer knows about TRUST in one element. Not a
    single inference."""

    element_id: str
    trust: Trust
    fidelity: Fidelity
    #: `op_name` for `OP_*`, `reason.code` for `ATOM`, `""` for `UNKNOWN`.
    why: str = ""
    #: An atom for a legitimate reason (see `BENIGN_ATOM_REASONS`).
    benign: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.element_id, "trust": self.trust.value,
                "fidelity": self.fidelity.value, "why": self.why,
                "benign": self.benign}


@dataclass
class HonestyCensus:
    """The honesty layer's census. The same law as
    `clash.snapshot.Census`: the sum across states must equal the number
    of elements, otherwise the percentage at the bottom of the screen has
    no denominator."""

    by_trust: dict[str, int] = field(default_factory=dict)
    by_fidelity: dict[str, int] = field(default_factory=dict)
    by_atom_reason: dict[str, int] = field(default_factory=dict)
    by_unproven_op: dict[str, int] = field(default_factory=dict)
    total: int = 0

    def add(self, item: ElementHonesty) -> None:
        self.total += 1
        self.by_trust[item.trust.value] = self.by_trust.get(item.trust.value, 0) + 1
        key = item.fidelity.value
        self.by_fidelity[key] = self.by_fidelity.get(key, 0) + 1
        if item.trust is Trust.ATOM and item.why:
            self.by_atom_reason[item.why] = self.by_atom_reason.get(item.why, 0) + 1
        elif item.trust is Trust.OP_UNPROVEN and item.why:
            self.by_unproven_op[item.why] = self.by_unproven_op.get(item.why, 0) + 1

    def balanced(self) -> bool:
        """The census's convergence. A discrepancy is not a warning:
        coloring where part of the elements fell into no state at all
        shows a green building that nobody actually knows to be green."""
        return sum(self.by_trust.values()) == self.total == sum(
            self.by_fidelity.values())

    def to_dict(self) -> dict[str, Any]:
        return {"schema": HONESTY_SCHEMA, "total": self.total,
                "by_trust": dict(sorted(self.by_trust.items())),
                "by_fidelity": dict(sorted(self.by_fidelity.items())),
                "by_atom_reason": dict(sorted(self.by_atom_reason.items())),
                "by_unproven_op": dict(sorted(self.by_unproven_op.items())),
                "balanced": self.balanced()}


def unproven_ops() -> frozenset[str]:
    """The names of the operations in `tool_doc.UNPROVEN` (29 entries as
    of 10.08.2026).

    The import is lazy and guarded: `tool_doc` pulls in the registry, and
    the viewer must draw the building even when the registry fails to
    come up. An empty set here means "there was nothing to ask," and
    that is NOT the same as "all ops are proven" — that's why the caller
    also gets a flag in `read_l1_honesty`.
    """
    try:
        from kir.tool_doc import UNPROVEN
        return frozenset(UNPROVEN)
    except Exception:  # noqa: BLE001 — the registry belongs to someone else; its silence is not our green light
        return frozenset()


def iter_l1_nodes(node: Any) -> Iterator[Mapping[str, Any]]:
    """All L1 tree nodes that CARRY AN ELEMENT — both via `children` and
    via `members`.

    THE SECOND WALK IS NOT DECORATION. `atom_cluster` / `row` /
    `grid_array` collapse same-type atoms into one node and hold them in
    `members`, not in `children`; the cluster's own `payload` is empty. A
    walk that reads only descendants' `payload` loses them SILENTLY: a
    measurement on 10.08 gave 37.9 % "shells with no node" on `демо-v3`,
    and all of them were found in `members`. After the fix — 0.
    """
    if not isinstance(node, Mapping):
        return
    payload = node.get("payload")
    if isinstance(payload, Mapping) and payload.get("source_element_id"):
        yield payload
    for member in (node.get("members") or ()):
        if isinstance(member, Mapping) and member.get("source_element_id"):
            yield member
    for child in (node.get("children") or ()):
        yield from iter_l1_nodes(child)


def read_l1_honesty(run_dir: str | pathlib.Path) -> tuple[
        dict[str, tuple[Trust, str]], dict[str, Any]]:
    """A parse's `tree.json` -> {element_id: (Trust, почему)} + a
    reading note.

    Returns TWO values, and the second is mandatory: if there is no
    tree, or it failed to read, the viewer has no right to silently
    color the whole building `OP_PROVEN`. The note carries `available`
    and the reason, and the caller must turn everything into
    `Trust.UNKNOWN`.
    """
    path = pathlib.Path(run_dir) / "tree.json"
    note: dict[str, Any] = {"available": False, "reason": "", "path": str(path),
                            "unproven_table": True}
    # 🔴 VIA `snapshot_io`, NOT A BARE `exists`/`read_text` (21.08.2026):
    # `tree.json` was added to `SNAPSHOT_FILES`, and on a cooled-down
    # parse a bare check would have returned "no L1 nodes" — and on that
    # note the viewer colors THE WHOLE building `Trust.UNKNOWN`. An
    # instrument's silence dressed up as a fact about the house.
    from kir.decompile.snapshot_io import (
        read_snapshot_text, snapshot_file_exists)
    if not snapshot_file_exists(path):
        note["reason"] = "tree.json отсутствует: узлов L1 в этом разборе нет"
        return {}, note
    try:
        tree = json.loads(read_snapshot_text(path, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — a corrupted tree is not a green light
        note["reason"] = f"tree.json не разобран: {type(exc).__name__}"
        return {}, note

    unproven = unproven_ops()
    note["unproven_table"] = bool(unproven)
    if not unproven:
        # The registry didn't come up. Then `OP_PROVEN` would be an
        # INFERENCE, not a measurement, and it must not be shown as a
        # measurement.
        note["reason"] = ("таблица tool_doc.UNPROVEN не прочитана: отличить "
                          "доказанный оп от недоказанного нечем")

    out: dict[str, tuple[Trust, str]] = {}
    for payload in iter_l1_nodes(tree):
        sid = str(payload.get("source_element_id"))
        kind = payload.get("kind")
        if kind == "atom":
            reason = (payload.get("reason") or {})
            out[sid] = (Trust.ATOM, str(reason.get("code") or "unnamed"))
        elif kind == "op":
            name = str(payload.get("op_name") or "")
            if not unproven:
                out[sid] = (Trust.UNKNOWN, name)
            else:
                out[sid] = ((Trust.OP_UNPROVEN if name in unproven
                             else Trust.OP_PROVEN), name)
    note["available"] = True
    note["nodes"] = len(out)
    return out, note


def fidelity_of(grade: str, hull_source: str, degeneracy: str) -> Fidelity:
    """Grade + source + degeneracy -> the SHAPE the element is drawn
    with.

    The order of checks is not a matter of taste. Degeneracy OUTRANKS
    grade: a zero-volume bounding box stays `coarse` by the grade table,
    but it is not a body at all, and drawing it as a box would mean
    inventing a thickness for it.
    """
    if degeneracy and degeneracy != "ok":
        return Fidelity.DEGENERATE
    if grade == "exact":
        return Fidelity.EXACT
    if grade == "conservative" or hull_source in ("profile", "prism",
                                                  "axis_section"):
        return Fidelity.SHAPED
    return Fidelity.BOX_ONLY


# ---------------------------------------------------------------------------
# Axes for which nobody promised to check — PER ELEMENT and AS A TRI-STATE
# ---------------------------------------------------------------------------
#
# `serving._unwitnessed_axes` answers not "was the axis violated" but "was
# it ever taken up for checking at all," and it answers with THREE states:
#
#     {}          — every op declared obligations on all three axes
#     {axis: ops} — there are no obligations on these axes, and the
#                   culprits are named
#     None        — nothing to judge by (the op is outside the table, the
#                   table didn't come up)
#
# **`None` is NOT "everything is fine,"** and that is exactly why this is
# a byte, not a flag: a binary "ok/not ok" would merge the third state
# into the first, that is, show green where nobody looked. Exactly the
# defect this field was set up against.
#
# THE RULE IS NOT COPIED. The query goes through a call to
# `serving._unwitnessed_axes`; here there is only the PACKING of the
# answer into a byte. Two copies of the rule would drift apart silently —
# the same argument by which `serving` keeps a single copy.

#: The bit order. Published in the scene header: the client keeps no
#: copy of its own.
AXES_ORDER: tuple[str, ...] = ("geometry", "topology", "semantic")

#: "Nothing to judge by." Not zero and not any mask: zero means "all
#: three declared," which is the opposite claim.
AXES_UNJUDGEABLE = 255


def axes_byte(unwitnessed: Any) -> int:
    """The `_unwitnessed_axes` response -> one byte. The tri-state is
    preserved.

    0 — all three axes declared; a mask — there are no obligations on
    these axes; `AXES_UNJUDGEABLE` — nothing to judge by.
    """
    if unwitnessed is None:
        return AXES_UNJUDGEABLE
    if not unwitnessed:
        return 0
    mask = 0
    for index, axis in enumerate(AXES_ORDER):
        if unwitnessed.get(axis):
            mask |= 1 << index
    # A non-empty response that fits no known bit is a NEW axis at the
    # owner of the table. Returning zero would mean saying "all
    # declared" about something we didn't understand; we return
    # "nothing to judge by."
    return mask if mask else AXES_UNJUDGEABLE


def axes_for_ops(op_names: Sequence[str]) -> Any:
    """Axes for a SET of operations. A thin wrapper over the single
    rule.

    An empty list gives `None`, not `{}`: an element with no operation
    has nothing to ask, and that is "nothing to judge by," not "all
    declared."
    """
    names = [str(n) for n in op_names if n]
    if not names:
        return None
    try:
        from kir.serving import _unwitnessed_axes
        return _unwitnessed_axes(names)
    except Exception:  # noqa: BLE001 — a foreign module; its silence is not our green light
        return None
