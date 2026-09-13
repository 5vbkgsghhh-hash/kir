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
from datetime import date as _date
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from kir import spec


REVERSE_CONTRACT_SCHEMA = "kir-reverse-contract/1"


class ReverseContractError(ValueError):
    """The reverse path attempted an operation outside its declared surface."""


class ReverseMode(str, Enum):
    DIRECT = "direct"
    CAPTURE_GAP = "capture_gap"
    # READING BRINGS EVERYTHING, THERE IS NO LIFTER (host-capture wave,
    # 2026-08-09).
    #
    # Introduced because `capture_gap` had become a LIE for exactly one
    # record, not for the sake of a tidy vocabulary. While
    # `WallFoundation.WallId` was not read, "capture gap" was accurate. Now
    # it is read, and leaving the old mode would send the next person to fix
    # reading that is already fixed. The distinction is about ADDRESS, the
    # same one this house already used to split `no_lifter` from
    # `source_contract_gap`: one mode sends work to CAPTURE, the other to
    # the LIFTER, and the manifest exists precisely so this address does not
    # lie.
    #
    # The guarantee on such a record is still NONE either way: there is no
    # lifter, so there is no lift. It differs from `capture_gap` not in the
    # strength of the promise but in WHAT exactly remains to be done.
    LIFTER_GAP = "lifter_gap"
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
    #: RATCHET FOR CAPTURE GAPS (2026-08-09, `record_ratchet`). Only
    #: `capture_gap` carries it, and that is not economy but a difference in
    #: substance: `direct`, `decomposed`, `state_transition`,
    #: `external_source` describe what the reverse path IS, while
    #: `capture_gap` describes what it CANNOT do YET. The former does not go
    #: stale; the latter goes stale silently on the exact day the capture
    #: wave starts reading the named field, and nobody comes to erase the
    #: line. The decision date and the review deadline stand here so that
    #: day gets noticed by someone.
    decided_on: str = ""
    due: str = ""

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
        if self.mode is ReverseMode.CAPTURE_GAP:
            # The shape is checked AT IMPORT TIME: a capture gap with no day
            # by which someone must answer is "someday", not a decision.
            for label, value in (("decided_on", self.decided_on),
                                 ("due", self.due)):
                try:
                    _date.fromisoformat(value)
                except ValueError:
                    raise ValueError(
                        f"capture_gap {self.op_name}: {label}={value!r} — не "
                        f"ISO-дата; пробел захвата обязан нести дату решения и "
                        f"срок пересмотра (kir/record_ratchet.py)"
                    ) from None
            if _date.fromisoformat(self.due) < _date.fromisoformat(
                    self.decided_on):
                raise ValueError(
                    f"capture_gap {self.op_name}: срок {self.due} раньше "
                    f"самого решения {self.decided_on}")
        elif self.decided_on or self.due:
            raise ValueError(
                f"{self.op_name}: дату и срок несёт только capture_gap — "
                f"остальные моды описывают, чем обратный ход ЯВЛЯЕТСЯ, а не "
                f"чего он пока не умеет")
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
            "decided_on": self.decided_on,
            "due": self.due,
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
    # wave/datums (2026-08-09). HALF of the input is already read, and this
    # is a MEASUREMENT, not an estimate: `sketch_extract.__ExtrusionRoofLoops`
    # calls `ExtrusionRoof.GetProfile()` and stores the profile in the same
    # index as a footprint roof's. The other half is not read AT ALL: neither
    # `EXTRUSION_START_PARAM`, nor `EXTRUSION_END_PARAM`, nor
    # `ReferencePlane` occurs even ONCE anywhere in `kir/decompile/` (grep,
    # 2026-08-09 — zero occurrences). Without them neither the extrusion
    # depth nor the plane the profile lies on is known — three of the op's
    # seven inputs.
    #
    # WHY THIS IS NOT DECOMPOSED. Claiming the state is representable by a
    # footprint roof would promise a rebuild in a DIFFERENT class's shape: an
    # extruded roof's profile is VERTICAL and open, and its plan projection
    # is a zero-area segment, not a contour. Refusing is more honest than
    # substituting.
    "create_extrusion_roof": ReverseContract(
        "create_extrusion_roof", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "the profile IS captured (sketch_extract calls "
        "ExtrusionRoof.GetProfile) and the work plane is captured too since "
        "2026-08-22 (extract.py collects OST_CLines by "
        ".OfClass(typeof(ReferencePlane)), 9724 planes across 10 of 10 "
        "corpus buildings). What is still missing is the extrusion RANGE: "
        "EXTRUSION_START_PARAM / EXTRUSION_END_PARAM appear nowhere in "
        "decompile/ — verified 2026-08-22, zero occurrences in code",
        sources=("L0:OST_Roofs", "side:sketch"),
        limitation=("capture must start reading the extrusion range and the "
                    "roof's work plane before a lifter is legal; until then "
                    "such a roof is a typed atom and is NEVER re-emitted as "
                    "a footprint roof — its profile is vertical and open, so "
                    "its plan projection has zero area"),
        decided_on="2026-08-09", due="2026-09-08"),
    "create_column": _direct(
        "create_column", "_lift_column",
        sources=("L0:OST_Columns", "L0:OST_StructuralColumns")),
    "create_beam": _direct(
        "create_beam", "_lift_beam", sources=("L0:OST_StructuralFraming",)),
    "create_foundation": _direct(
        "create_foundation", "_lift_foundation",
        sources=("L0:OST_StructuralFoundation", "side:sketch")),
    # wave/wall-foundation (2026-08-09). The op EXISTS, there is no reverse
    # path, and this is stated HERE rather than implied by default. There is
    # exactly one reason and it is about CAPTURE, not the lifter: a wall
    # foundation's only mandatory input is ITS WALL (WallFoundation.WallId),
    # and L0 carries no such relation at all. The category itself IS read:
    # OST_StructuralFoundation is already in the extraction table, so the
    # element WILL be read and becomes an honest atom rather than vanishing
    # silently.
    #
    # A MEASUREMENT, NOT AN ESTIMATE: not one decompile saved to disk
    # contains a single WallFoundation (grep over the L0.jsonl of every
    # decompile, 2026-08-09), so declaring DIRECT would promise a lift
    # nobody has ever seen. One capture field (WallId) closes the gap, not a
    # new lifter. SWITCHED FROM capture_gap TO lifter_gap on 2026-08-09 — by
    # MEASUREMENT, not by preference, the same night the previous record was
    # written.
    #
    # The previous text promised: "while capture does not read
    # WallFoundation.WallId, such an element is a typed atom, NEVER silently
    # re-emitted as an isolated footing". The promise was TRUE and
    # UNENFORCED: `_lift_foundation`, given `geom_kind is POINT`, emitted
    # `create_foundation(variety="isolated")` with no check at all on the
    # element's class, relying entirely on the fact that a `WallFoundation`
    # has no `LocationPoint`. That is, it relied on REVIT'S BEHAVIOUR, not on
    # our own invariant — exactly the class of defect a fixture-driven test
    # would pass through.
    #
    # What changed. Capture now reads the host of system elements through
    # one table (`extract._HOST_READERS`) and writes `host_source` — the
    # relation's CLASS — alongside `host_id`; `WallFoundation.WallId` is
    # measured by compilation against real assemblies as 6/6 at :52412. The
    # lifter now refuses on this class BEFORE parsing geometry, so the
    # promise is held by CODE, not by coincidence (`lift._lift_foundation`,
    # `decompile/tests/test_host_capture_system_elements.py`).
    #
    # Why NOT direct: reading is now sufficient (wall + type), but there is
    # no lifter, and writing one blind is not allowed — not one of the 67
    # decompiles saved to disk contains a SINGLE WallFoundation (measured
    # 2026-08-09 over the L0.jsonl of the whole corpus; only 5
    # OST_StructuralFoundation elements total, all with an empty host).
    # Declaring DIRECT would promise a lift nobody has seen.
    # wave/space (2026-08-10). Mode LIFTER_GAP, NOT CAPTURE_GAP, and this is
    # a measurement of address, not a nuance: "capture gap" would send the
    # next person to fix reading that already works. Extraction has read
    # OST_MEPSpaces since the category table was first set up
    # (`extract._CATEGORY_SPECS`), and the corpus confirms it: 44 of 76
    # decompiles even looked at this category, 6 found elements, and 169
    # spaces across THREE buildings were read with `expected == extracted`
    # and `state: complete`. What is missing is a row in the lifter's
    # candidate table (`lift.py` knows "OST_Rooms" and does not know
    # "OST_MEPSpaces", grep 2026-08-10), so all 126 elements today become
    # "op does not exist" atoms — and that has just stopped being true.
    #
    # THE LIFTER IS INTENTIONALLY NOT WRITTEN BY THIS WAVE: `decompile/**`
    # is another session's territory. The guarantee is NONE because there is
    # no lift; the mode names the ADDRESS of the work, not its scope.
    #
    # THE HONEST REMAINDER A FUTURE LIFTER MUST KNOW: in L0, all 169 spaces
    # have `params` EMPTY and `type_id`/`type_name` as empty strings. So the
    # source carries no name, number or type at all, and (number corrected
    # 2026-08-11: a folder name had been mistaken for a document name —
    # `snowdon_plumb_v5` carries `Snowdon Towers Sample Architectural`, the
    # third building, not the fifth plumbing revision) lifting into today's
    # signature (point + level) loses exactly nothing — but there is nothing
    # in this reading to enrich the op with either.
    "create_space": ReverseContract(
        "create_space", ReverseMode.LIFTER_GAP, ReverseGuarantee.NONE,
        "capture reads OST_MEPSpaces already (169 spaces over 3 buildings, "
        "expected == extracted, state complete); no lifter candidate maps "
        "that category to an op, so every space is still a typed atom",
        sources=("L0:OST_MEPSpaces",),
        limitation=("the source carries no name, number or type for a "
                    "space (params empty and type_id blank on all 126), "
                    "so a lifter can restore the point and the level and "
                    "nothing else")),
    "create_wall_foundation": ReverseContract(
        "create_wall_foundation", ReverseMode.LIFTER_GAP,
        ReverseGuarantee.NONE,
        "capture now reads WallFoundation.WallId (6/6) and records the class "
        "in host_source; no lifter emits the op yet, and no stored decompile "
        "contains a single WallFoundation to write one against",
        sources=("L0:OST_StructuralFoundation",),
        limitation=("such an element is a typed atom, never a silently "
                    "re-emitted isolated footing — enforced by "
                    "lift._lift_foundation on host_source, not by the absence "
                    "of a LocationPoint")),
    # wave/framing (2026-08-09). Neither op has a reverse path, and both
    # reasons are about CAPTURE, not an unwritten lifter.
    #
    # Beam system: L0 reads OST_StructuralFraming, i.e. it sees the
    # GENERATED beams, not the system that generated them. Lifting them one
    # by one as create_beam would be possible — and it would be a WORSE
    # answer than an atom: the beam system would stop existing as an object,
    # and its layout (LayoutRule) would degenerate into a pile of fixed
    # coordinates that cannot be rebuilt. `BeamSystem.BeamBelongsTo
    # (FamilyInstance)` gives exactly the relation capture is missing.
    "create_beam_system": ReverseContract(
        "create_beam_system", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 carries the generated beams, not the system that laid them, and "
        "no profile/direction/layout-rule record exists to lift",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_StructuralFraming",),
        limitation=("capture must read BeamSystem.Profile/Direction/Level and "
                    "BeamBelongsTo before a lifter is legal; until then the "
                    "system is a typed atom and its beams stay individual "
                    "create_beam leaves — never a silently re-derived layout")),
    # Truss: the same shape of gap and the same honesty. The truss's
    # members are read as ordinary structural framing; the truss itself is
    # not: L0 carries neither its base curve, nor its sketch plane, nor
    # `Truss.Members`. Once again, lifting the members one by one would not
    # be a "partial success" but a loss of the object.
    "create_truss": ReverseContract(
        "create_truss", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 carries no truss base curve, no sketch plane and no Members set — "
        "only the members themselves, which are not the truss",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_StructuralFraming",),
        limitation=("capture must read the truss LocationCurve, its "
                    "SketchPlane and TrussType before a lifter is legal; "
                    "until then the truss is a typed atom, never a pile of "
                    "loose beams pretending to be one")),
    # wave/reinforcement (2026-08-10). This is a CAPTURE gap specifically,
    # and a total one: the OST_AreaRein category is not in the extraction
    # table at all (grep over `extract._CATEGORY_SPECS`), so the
    # reinforcement pipeline sees not a single element — neither the system
    # nor the bars. Confirmed from the other side too: across 38 saved
    # decompiles with a census, there are ZERO OST_AreaRein, OST_PathRein,
    # OST_Rebar, OST_FabricAreas or OST_FabricReinforcement elements
    # (measured 2026-08-10 from the census records of the whole corpus).
    # Declaring anything stronger would promise a lift for something reading
    # has never even encountered.
    "create_area_reinforcement": ReverseContract(
        "create_area_reinforcement", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "the extraction table carries no OST_AreaRein category at all, so L0 "
        "never sees an area reinforcement system, its host, its major "
        "direction or its bar type — and no stored decompile contains one to "
        "write a lifter against",
        decided_on="2026-08-10", due="2026-09-09",
        sources=(),
        limitation=("capture must read AreaReinforcement.GetHostId/Direction/"
                    "GetTypeId and the bars' own type before a lifter is "
                    "legal; until then reinforcement is simply absent from "
                    "the reverse direction — never silently re-derived from "
                    "the bars that happen to be visible")),
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
    # A FLOOR PLAN IS NOT READ AT ALL, AND THIS IS NOT THIS WAVE'S OVERSIGHT.
    # `OST_Views` is in no category table of the decompile; a view enters
    # the program only as an annotation's `in_view`, i.e. as a REFERENCE TO
    # AN EXISTING view, not as something we know how to recreate.
    #
    # The op was introduced on 2026-08-23 not for the reverse path but for
    # the FORWARD one: without a floor plan `NewRoomBoundaryLines` does not
    # work, and a live run on building K3 stalled on 917 separators. That
    # is, this is CATALOG PREPARATION of a foreign document — the same kind
    # of work as `create_wall_type` and `transfer_family` — and lifting it
    # from a decompile is not required while view decompiling does not read.
    #
    # The revision condition is named: as soon as capture starts taking
    # views, the contract must become DIRECT with a lifter, not remain a
    # gap.
    "create_floor_plan": ReverseContract(
        "create_floor_plan", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "views are not captured at all: no OST_Views in any decompile "
        "category table, and no side index carries ViewPlan/GenLevel — "
        "verified 2026-08-23. The op exists for the FORWARD direction "
        "(catalog preparation of a foreign document), which is why a lifter "
        "is not the missing piece here",
        sources=(),
        limitation=("until capture reads views, a floor plan present in the "
                    "source document is invisible to the decompile and is "
                    "NEVER re-emitted; the op is called by catalog "
                    "preparation, not by the lifter"),
        decided_on="2026-08-23", due="2026-09-22"),
    # wave/datums (2026-08-09). The chain's axes ARE read — each of them is
    # an ordinary Grid and lifts as `create_grid`. What is not read is
    # MEMBERSHIP: `MultiSegmentGrid.GetMultiSegementGridId(Grid)` occurs in
    # no file of the package (grep over kukai/, 2026-08-09 — zero
    # occurrences outside this wave's forward emission), so a snapshot
    # cannot tell that three axes were one chain. The mode is DECOMPOSED,
    # not CAPTURE_GAP: the current state IS REPRESENTABLE — as three
    # `create_grid` — and the building rebuilds correct in geometry, losing
    # only the grouping.
    "create_multi_segment_grid": ReverseContract(
        "create_multi_segment_grid", ReverseMode.DECOMPOSED,
        ReverseGuarantee.BOUNDED,
        "each segment IS a Grid and lifts as create_grid; only the chain "
        "MEMBERSHIP is unrecoverable — L0 never reads "
        "MultiSegmentGrid.GetMultiSegementGridId",
        sources=("L0:OST_Grids", "L0:grids"),
        representation_ops=("create_grid",),
        limitation=("the rebuilt document has the same axes as separate "
                    "grids, not one chain; capture must start reading the "
                    "owning MultiSegmentGrid id before a same-op lift is "
                    "legal")),
    "create_pipe": _direct(
        "create_pipe", "_lift_pipe", sources=("L0:OST_PipeCurves", "side:mep_system")),
    "create_duct": _direct(
        "create_duct", "_lift_duct", sources=("L0:OST_DuctCurves", "side:mep_system")),
    "create_cable_tray": _direct(
        "create_cable_tray", "_lift_cable_tray", sources=("L0:OST_CableTray",)),
    # wave/mep-electrical (2026-08-09). Conduit inverts COMPLETELY: in L0
    # its row is indistinguishable in shape from a cable tray's (a linear
    # MEPCurve, the same ends, the same level, the same catalog type), and
    # the lifter was written the same wave. The forward op takes no
    # diameter, so there is nothing to lose on the reverse path either — the
    # shape closes.
    "create_conduit": _direct(
        "create_conduit", "_lift_conduit", sources=("L0:OST_Conduit",)),
    # wave/analysis (2026-08-09). Three loads and the path of travel: the
    # ops EXIST, there is no reverse path, and this is stated HERE rather
    # than implied by default. All four share one reason and it is about
    # CAPTURE: neither OST_PointLoads / OST_LineLoads / OST_AreaLoads nor
    # OST_PathOfTravelLines is in the L0 extraction table at all, so reading
    # never reaches these elements. The difference between "the stage
    # refused on the element" and "the stage said nothing about it" has
    # already cost this package one wrong diagnosis (see CLAUDE.md, "Absent
    # index and empty index are different facts"), and repeating it by
    # default is not allowed.
    #
    # WHAT EXACTLY IS MISSING is named by field, so the next wave does not
    # start with a re-census: for the loads it is `ForceVector`/
    # `MomentVector`, `LoadCaseId` and the work plane (a load cannot be
    # recovered from its endpoints and type alone: the same endpoints would
    # be given by any load of any magnitude); for the path of travel it is
    # `PathStart`/`PathEnd` and `OwnerViewId`. Until they exist, such an
    # element must become a typed atom, not vanish silently and not be
    # substituted by something similar.
    # 🔴 CLOSED 2026-09-04, SECOND KIND OF LOAD. The census reads
    # `PointLoad.Point`/`ForceVector`/`MomentVector` and the shared
    # `LoadBase` block (`IsHosted`/`IsReaction`/`OrientTo`/`LoadCaseName`).
    # All members are 6/6, and every documented trap on them is "when
    # setting this property", i.e. reading is safe; verified by the index,
    # not assumed.
    #
    # The boundaries are the SAME as the line load's, and come from one
    # body: this op's post-condition promises exactly `OrientTo ==
    # Project`, and it has no input at all for a host or for a reaction.
    "create_point_load": _direct(
        "create_point_load", "_lift_point_load",
        sources=("L0:OST_PointLoads",),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only a free, non-reaction, Project-oriented point load "
                    "is inverted. A hosted load refuses because the op has "
                    "no host input; a reaction refuses because analysis "
                    "computes it, not the author; a load oriented to the "
                    "host local system or a work plane refuses because the "
                    "op's own post-condition promises OrientTo == Project. "
                    "Force is newtons and moment newton-metres — separate "
                    "fields from the line load's newtons-per-metre, because "
                    "one field for both would leave the unit in the "
                    "reader's head")),
    # 🔴 CLOSED 2026-09-04 — THE FIRST OF ELEVEN INTRODUCED INTO THE CENSUS
    # THE SAME DAY. The earlier reason said "OST_LineLoads outside the
    # extraction table", and that stopped being true exactly when the
    # category entered it (dialect stage 10). The reader is
    # `extract._line_load_reader_cs`, the lifter is `lift._lift_line_load`.
    #
    # THERE ARE THREE BOUNDARIES, and each comes from a MEASUREMENT of API
    # members, not from caution:
    #   1. a snapshot taken before 09-04 carries no keys and gives the SAME
    #      refusal, verbatim;
    #   2. `IsUniform == false` — the load has TWO different vectors at its
    #      ends (`ForceVector1` != `ForceVector2`), while the op holds one:
    #      taking the first would pass off a different load as this one;
    #   3. `IsProjected == true` — the magnitude is relative to the
    #      PROJECTED length, and the op has no such input at all.
    #
    # All members have lived since 2021-2026; the vectors and `LoadCaseId`
    # do have documented traps, but ALL of them are "when setting this
    # property" — reading is safe, and this is verified by the index, not
    # assumed.
    "create_line_load": _direct(
        "create_line_load", "_lift_line_load",
        sources=("L0:OST_LineLoads",),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only a free, non-reaction, Project-oriented, uniform, "
                    "non-projected line load is inverted. A hosted load "
                    "refuses because the op has no host input and a free "
                    "load at the same coordinates is a DIFFERENT load; a "
                    "reaction refuses because analysis computes it, not the "
                    "author; a load oriented to the host local system or a "
                    "work plane refuses because the op's own post-condition "
                    "promises OrientTo == Project, so the basis would change "
                    "silently while the numbers stayed; a non-uniform load "
                    "refuses because ForceVector1 and ForceVector2 differ "
                    "while the op holds one vector; a projected load refuses "
                    "because the op has no such input. A row carrying the "
                    "endpoints but not IsHosted comes from the window "
                    "between the capture wave and this fix and refuses too — "
                    "re-capture it")),
        # 🔴 CLOSED 2026-09-04, THE THIRD AND LAST KIND OF LOAD. The census
    # reads `AreaLoad.GetLoops`/`NumRefPoints`/`ForceVector1` plus the
    # shared `LoadBase` block. All members are 6/6; the vectors' only traps
    # are "on write".
    #
    # THERE ARE FIVE BOUNDARIES, and the last two are read from the OP'S OWN
    # POST-CONDITION ("GetLoops returns ONE loop, whose vertices are the
    # outline at elev_mm"), not invented out of caution.
    "create_area_load": _direct(
        "create_area_load", "_lift_area_load",
        sources=("L0:OST_AreaLoads",),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only a free, non-reaction, Project-oriented, "
                    "non-projected area load with exactly ONE planar loop "
                    "and a single reference point is inverted. More than one "
                    "loop refuses because the op's post-condition promises "
                    "one; a non-planar loop refuses because elev_mm is a "
                    "single number; NumRefPoints > 1 refuses because the "
                    "load then carries three force vectors while the op "
                    "holds one; an arc boundary is never captured at all, "
                    "so such a load refuses as an unread source")),
    "create_path_of_travel": ReverseContract(
        "create_path_of_travel", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "L0 does not read path-of-travel lines, and the element's own "
        "geometry is DERIVED by Revit from the view's obstacles — only its "
        "two endpoints and its owner view are authored input",
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("capture must start reading PathOfTravel.PathStart/"
                    "PathEnd and OwnerViewId before a lifter is legal; "
                    "lifting the computed curves would re-author a route as "
                    "if it had been drawn by hand")),
    # 🔴 FAMILY AUTHORSHIP (2026-08-21). IT IS EASY TO LIE FOR THE BETTER
    # HERE, AND THIS IS WHY THE RECORD IS STILL `capture_gap`.
    #
    # WHAT CAPTURE CAN DO AS OF 2026-08-21, AND WHY THAT IS NOW ENOUGH.
    # `decompile/family_recipe.py` reads the family definition (`EditFamily`
    # + `GenericForm`) and takes a RECIPE: on 2026-08-21 the census grew
    # 27 -> 235 of 283 forms (9.5% -> 83.0%) across 110 families of a real
    # building. On 2026-08-21 the RELATION that was missing was added to the
    # form: `FamilyManager.Parameters` (name, kind, formula, value on the
    # current type, built-in-ness) and `GetAssociatedFamilyParameter` for
    # EVERY parameter of EVERY form.
    #
    # 🔴 WHY THE MODE CHANGED TO `LIFTER_GAP` INSTEAD OF STAYING. The
    # earlier argument was accurate and read: "the relation 'this parameter
    # drives this field of this form' is NOT IN THE RECIPE AT ALL, and a
    # lifter would have to INVENT the parameter's name and its binding."
    # The relation has appeared, and leaving `capture_gap` would send the
    # next person to fix reading that is already fixed — exactly the
    # address lie `LIFTER_GAP` was introduced for.
    #
    # THE MEASUREMENT THAT CLOSED CAPTURE (live, "Проект1", 36 families,
    # 2026-08-21):
    #
    #     KIR_Куб_21_08        Высота_KIR -> EXTRUSION_END_PARAM   volume 192e6
    #     KIR_параметрическое  Высота_KIR -> EXTRUSION_END_PARAM   volume 384e6
    #     KIR_проба_семейства  Высота_KIR -> nothing                volume 192e6
    #
    # The third row is the exact quiet lie that only a VOLUME measurement
    # caught on 2026-08-21: the parameter exists, the formula reads, the
    # body does not listen to it. Now it is read straight from the recipe
    # (`FamilyRecipe.rigid_with_a_handle`), and `flex_candidates` gives the
    # lifter the parameter's name and its `BuiltInParameter` BY NAME, not by
    # guesswork.
    #
    # WHAT IS STILL LEFT TO THE LIFTER, AND WHY THE GUARANTEE IS STILL
    # `NONE`. The op covers ONE body of ONE kind (`Extrusion`) with ONE
    # handle, while a real building asks for four: Extrusion 198 · Sweep 75
    # · Blend 6 · Revolution 4. So a lifter meeting a Sweep must REFUSE and
    # name the kind, not lift "something similar". On top of that, the
    # language has no reference planes, meaning a family's plan is rigid —
    # so a captured family that flexes IN PLAN comes back flexing only in
    # HEIGHT. That is a lifter REFUSAL, not a capture gap.
    "author_family": ReverseContract(
        "author_family", ReverseMode.LIFTER_GAP, ReverseGuarantee.NONE,
        "capture now reads FamilyManager.Parameters and, per GenericForm, "
        "GetAssociatedFamilyParameter with the BuiltInParameter of the "
        "driven field (measured live 21.08.2026 on 36 families: the "
        "authored KIR_* families read back Высота_KIR -> "
        "EXTRUSION_END_PARAM, and the one RIGID family is named as such); "
        "no lifter is written yet",
    # 🔴 THERE IS NO DEADLINE HERE, AND THAT IS THE REGISTRY'S LAW, NOT AN
    # OVERSIGHT. Only `capture_gap` carries a decision date and a deadline:
    # a capture gap is a debt that must be closed, while `lifter_gap`
    # describes what the reverse path IS today. The registry rejected the
    # first draft of this record precisely over the deadline, and it was
    # right: the 2026-09-21 deadline concerned READING, and reading is
    # closed today.
        sources=("side:family_recipe",),
        limitation=(
            "the op covers ONE Extrusion with ONE handle; a real building "
            "asks for four form kinds (Extrusion 198 · Sweep 75 · Blend 6 · "
            "Revolution 4, measured 20.08.2026), and the language has no "
            "reference planes, so a family that flexes IN PLAN can only be "
            "lifted as flexing in HEIGHT. A lifter meeting either case must "
            "REFUSE and name the kind — lifting the nearest thing would "
            "hand back a family that looks authored and is not. Version "
            "trap on the read side is closed: Parameters, Types, "
            "GetAssociatedFamilyParameter and CanElementParameterBe"
            "Associated are all 6/6 (api_trap_index, 21.08.2026); the one "
            "that is NOT is FamilyManager.GetParameter (absent on 2021) — "
            "use the indexer get_Parameter. 🔴 IsDeterminedByFormula is NOT "
            "'has a formula': measured False on a parameter whose Formula "
            "reads 'Высота_KIR * 2'; decide by Formula")),
    "create_stairs": _direct(
        "create_stairs", "_lift_stairs", sources=("L0:OST_Stairs", "side:stairs_path")),
    # STAIRS WAVE (2026-08-10). A landing is not read AT ALL, and this is a
    # CAPTURE gap, not a lifter one: the OST_StairsLandings category is
    # absent from the extraction table, the class `StairsLanding` occurs in
    # no file of `decompile/` (grep 2026-08-10), so there is nothing to
    # read. `_lift_stairs` lifts the STAIRS by its run and knows nothing
    # about landing components at all, so a decompiled building today loses
    # every landing silently — exactly the fact this record must keep in
    # view.
    #
    # WHY NOT DECOMPOSED. There is nothing to represent a landing with
    # among existing ops: a floor by contour would give a SLAB, not a
    # stairs component — a different element, a different category,
    # different behaviour when the run is edited. A false representation
    # here is worse than an honest gap.
    "create_stairs_landing": ReverseContract(
        "create_stairs_landing", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 reads no StairsLanding at all — OST_StairsLandings is absent from "
        "the extraction table and the class is named nowhere in decompile/",
        sources=("L0:OST_Stairs",),
        limitation=("capture must start reading StairsLanding, its "
                    "GetFootprintBoundary and its BaseElevation before a "
                    "lifter is legal; until then every landing of a "
                    "decompiled building is lost silently, and the stairs "
                    "lifts as its run alone"),
        decided_on="2026-08-10", due="2026-09-09"),
    # 🔴 THIS RECORD'S TEXT WAS A LIE FOR 28 DAYS, AND AN INSTRUMENT FOUND
    # IT, NOT AN EYE (2026-08-22, `agreements.py`'s eighth agreement). The
    # 2026-08-15 draft said: "Stairs.GetStairsRuns() is called nowhere in
    # decompile/ and the run class is named nowhere either". BOTH HALVES
    # ARE WRONG, and both were wrong BEFORE they were written:
    #
    #     sketch_extract.py:2047  `__stairs.GetStairsRuns()` — since 07-18 20:27
    #     sketch_extract.py:513   class `StairsRunPathRecord`
    #
    # That is, the record was born stale by 28 days and stood for 7 more.
    # This is the THIRD case of the same shape in five days (the first two
    # were `author_family` on 08-21 and `join_elements` on 08-22), and the
    # only one a human did not find.
    #
    # WHAT CAPTURE ACTUALLY GIVES — MEASURED FROM THE DECOMPILES ON DISK,
    # 2026-08-22 (`sketch.index.json`, key `stairs_run_path_index`), and it
    # is not about one run per stair:
    #
    #     k2v33_join2   89 stairs   173 runs   173 with a path
    #     MNVNK         24 stairs   48 runs    48 with a path
    #     bench_A       26 stairs   26 runs    26 with a path
    #     graph_check    9 stairs    9 runs     9 with a path
    #
    # WHY THE MODE STILL STAYS `CAPTURE_GAP`. Of the op's five inputs
    # (`stairs`, `p0_mm`, `p1_mm`, `base_elevation_mm`, `justification`),
    # capture gives three: the stair's address and both path endpoints.
    # `Stairs.BaseElevation` occurs NOWHERE in `decompile/` (measured
    # 2026-08-22 with the same instrument: no call at all), and neither
    # does `justification`. The gap is real, but it is FOUR TIMES NARROWER
    # than the old text: TWO fields need fixing, not "start reading the
    # runs". The decision date was reset deliberately — this is a NEW
    # decision on a new measurement, not an extension of the old one.
    "create_stairs_run": ReverseContract(
        "create_stairs_run", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "capture DOES read the runs: sketch_extract calls "
        "Stairs.GetStairsRuns and StairsRun.GetStairsPath and stores a typed "
        "path per run (measured 22.08.2026 on four decompiles: 173/173, "
        "48/48, 26/26, 9/9 runs carry a path). What is missing is narrower: "
        "Stairs.BaseElevation and the run justification appear nowhere in "
        "decompile/, and they are two of the op's five required inputs",
        sources=("L0:OST_Stairs", "side:sketch"),
        limitation=("capture must start reading BaseElevation and the run "
                    "justification before a lifter is legal; the path itself "
                    "is already in the sketch side index. Until then a stair "
                    "of N runs decompiles as one create_stairs and the run "
                    "structure is lost — measured on LEN_AR_ME_R24: 61 runs "
                    "across 19 stairs, mode FOUR runs per stair"),
        decided_on="2026-08-22", due="2026-09-21"),
    # 2026-08-09: a ceiling has TWO lift branches, and both are named here
    # by name. `_lift_ceiling_by_contour` appeared the same day as the
    # forward op's second form input (`contour` of kind `region`), and
    # takes exactly what a polyline cannot express — an arc in plan.
    # Capture itself did not change: the segment kind and the arc's
    # midpoint have lived in the sketch side index since 07-29, so this was
    # the only one of three cases where SPECIFICALLY the lifter was
    # missing. The guarantee stayed BOUNDED, and that is not an oversight:
    # the contour closes the PLAN, while the slope — the third coordinate —
    # stays open, and capture still does not have it.
    # wave/datums (2026-08-09). A multistory stairs is not read AT ALL: the
    # class `MultistoryStairs` occurs in no file of the package outside
    # this wave's forward emission (grep over kukai/, 08-09), and its
    # category (OST_MultistoryStairs) is absent from the extraction table.
    # So the problem is not the lifter — there is nothing to read.
    #
    # WHY NOT DECOMPOSED INTO N STAIRS. The member runs DO exist in the
    # model and lift as `create_stairs` — but promising that here would be
    # a lie TWICE OVER: the batch law (`spec.SOLO_OPS`) forbids several
    # `create_stairs` from riding one program, so the "representation"
    # would come out not as a program but as a batch of N programs; and the
    # link between the runs breaks in the process, meaning the rebuilt
    # building loses exactly the property the op was introduced for.
    "create_multistory_stairs": ReverseContract(
        "create_multistory_stairs", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 reads no MultistoryStairs at all — the category is absent from "
        "the extraction table and the class is named nowhere in decompile/",
        sources=("L0:OST_Stairs",),
        limitation=("capture must start reading MultistoryStairs and its "
                    "GetAllConnectedLevels before a lifter is legal; the "
                    "member runs themselves still lift as individual "
                    "create_stairs, which loses the multistory relation and "
                    "cannot be one program (SOLO_OPS)"),
        decided_on="2026-08-09", due="2026-09-08"),
    "create_ceiling": _direct(
        "create_ceiling", "_lift_ceiling", "_lift_ceiling_by_contour",
        sources=("L0:OST_Ceilings", "side:sketch"),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("frozen capture has no ceiling slope arrow; a captured "
                    "profile proves plan form but not native slope semantics, "
                    "and a sloped ceiling therefore lifts flat")),
    "create_directshape": _direct(
        "create_directshape", "_lift_directshape",
        sources=("L0:DirectShape", "geometry:mesh")),
    # wave/solid (2026-08-09). There is no reverse path, and the reason is
    # about CAPTURE, not the lifter — and it runs deeper than the wall
    # foundation's.
    #
    # A solid in the model is stored as a B-rep: faces, edges, surfaces.
    # WHAT it was built WITH — "a 3x4 rectangle extruded by 2" versus "the
    # same volume stretched differently" — is NOWHERE in the built
    # DirectShape: both programs give a byte-identical element. The reverse
    # path is therefore not "not written yet", it requires RECOGNISING
    # features (all lateral faces planar and vertical, two planar caps with
    # equal contours ⇒ a prism), i.e. a separate task with its own witness.
    # Declaring DIRECT would promise recovering intent from a trace that
    # stores no intent.
    #
    # The element does NOT disappear, though: `_lift_directshape` reads the
    # same DirectShape and returns it as a mesh (face tessellation) — the
    # form survives, the parametricity does not. This is an honest
    # degradation, not silence.
    "create_solid_extrusion": ReverseContract(
        "create_solid_extrusion", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "a built DirectShape stores a B-rep, not the profile+height that "
        "authored it; two different programs yield the identical element",
        sources=("L0:DirectShape",),
        # THE DATE AND DEADLINE WERE ADDED DURING THE 08-09 MERGE, AND THIS
    # IS NOT A FORMALITY. The solids wave's base predates the record
    # ratchet, so its lines arrived PLAIN — and the import refused instead
    # of staying silent: exactly the behaviour the ratchet was written for.
    # The date is the wave's day, the deadline thirty days, like all
    # nineteen other capture gaps.
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("recovering the op needs SHAPE RECOGNITION over the "
                    "B-rep (planar vertical laterals + two congruent planar "
                    "caps ⇒ prism), which is its own wave with its own "
                    "witness; until then such an element lifts as a mesh "
                    "DirectShape — form kept, parametricity lost, never "
                    "silently dropped")),
    "create_solid_revolve": ReverseContract(
        "create_solid_revolve", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "a built DirectShape stores a B-rep, not the profile+axis+sweep that "
        "authored it",
        sources=("L0:DirectShape",),
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("recognising a solid of revolution additionally needs the "
                    "AXIS recovered from the cylindrical/conical faces; same "
                    "wave, same requirement — until then it lifts as a mesh "
                    "DirectShape")),
    # wave/free-form (2026-08-20). THE SAME GAP AS THE TWO NEIGHBOURS
    # ABOVE, for the same reason — but with one addition that makes it
    # STRICTER, not milder. For a prism, recognition is at least
    # conceivable: planar vertical laterals plus two congruent caps ⇒ an
    # extrusion. For a blend even that does not work: the lateral surface
    # between the profiles is chosen by REVIT ITSELF ("blending smoothly",
    # RevitAPI.xml, all six versions), the smoothing rule is documented
    # nowhere, and from one built lateral surface a blend cannot be told
    # apart from a loft of the same profiles — nor from a tapered extrusion
    # giving the same caps.
    "create_solid_blend": ReverseContract(
        "create_solid_blend", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "a built DirectShape stores a B-rep, not the two profiles that "
        "authored it; the lateral surface is chosen by Revit, so several "
        "different programs yield the identical element",
        sources=("L0:DirectShape",),
        decided_on="2026-08-20", due="2026-09-19",
        limitation=("recovering the op needs SHAPE RECOGNITION over the "
                    "B-rep AND a rule for telling a blend from a loft of the "
                    "same two profiles — which Revit's own undocumented "
                    "smoothing makes unreliable by construction; until then "
                    "such an element lifts as a mesh DirectShape — form "
                    "kept, parametricity lost, never silently dropped")),

    # SURFACE AND ADAPTIVE COMPONENT ARE DIFFERENT REASONS FOR ONE GAP,
    # hence two records rather than one shared wording.
    "create_surface": ReverseContract(
        "create_surface", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "a built DirectShape stores a B-rep; WHICH control grid authored it is "
        "not recoverable, and _lift_directshape reads the element back as a "
        "MESH — so the form survives and the smoothness does not",
        sources=("L0:DirectShape",),
        decided_on="2026-08-20", due="2026-09-19"),
    "create_adaptive_component": ReverseContract(
        "create_adaptive_component", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "placement points live on ReferencePoint elements owned by the "
        "instance; L0 carries neither them nor their order, so the instance "
        "reads back as a plain family placement and the posture is lost",
        sources=("L0:FamilyInstance",),
        decided_on="2026-08-20", due="2026-09-19"),
    # BOOLEAN IS THE WORST OF THE THREE NEIGHBOURING GAPS, and this is said
    # here rather than softened by a shared wording. For a surface and a
    # blend, the METHOD of construction is lost while the form survives;
    # for a boolean even the OPERANDS are not recoverable: the result of
    # A-B and the result of A'-B' can coincide as solids for entirely
    # different A and B, and this is a property of the operation itself,
    # not of our reading. A reverse path here is impossible not "yet", but
    # by construction — boolean is not injective.
    # SWEEP IS THE SAME KIND OF GAP AS THE PRISM, but with ONE difference
    # in our favour, worth naming so the next person does not consider the
    # case hopeless. For the blend and the boolean the reverse path is
    # impossible in principle (Revit picks the lateral surface; boolean is
    # not injective). Here the form is FULLY DETERMINED by the input:
    # profile, path, roll. So recognition is CONCEIVABLE — a sweep's body
    # has a constant cross-section along a connected axis, and that is a
    # checkable property. What stands in the way is not the operation's
    # nature but the fact that L0 brings a `DirectShape` as one B-rep with
    # no axis at all.
    "create_solid_sweep": ReverseContract(
        "create_solid_sweep", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "a built DirectShape stores a B-rep; the path, the profile and the "
        "roll that authored it are not carried by L0, and the same solid is "
        "reachable by a sweep, a loft of many sections, or a mesh",
        sources=("L0:DirectShape",),
        decided_on="2026-08-20", due="2026-09-19",
        limitation=("recovering the op needs SHAPE RECOGNITION over the B-rep: "
                    "a constant cross-section along a connected axis. Unlike "
                    "the blend and the boolean this is mathematically "
                    "well-posed — the form is fully determined by the input — "
                    "but until capture carries an axis, such an element lifts "
                    "as a mesh DirectShape: form kept, parametricity lost, "
                    "never silently dropped")),
    "create_solid_boolean": ReverseContract(
        "create_solid_boolean", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "a built DirectShape stores the RESULT B-rep; the operands and the "
        "operation that produced it are not recoverable even in principle — "
        "boolean is not injective, and many different (base, parts, op) "
        "triples yield the identical solid",
        sources=("L0:DirectShape",),
        decided_on="2026-08-20", due="2026-09-19",
        limitation=("this gap does not close by better reading: the element "
                    "lifts as a mesh DirectShape — form kept, the authoring "
                    "history lost, never silently dropped")),
    # wave/mass (2026-08-10). A CAPTURE gap, not a lifter gap, and the
    # difference is one of address: reading does NOT bring everything.
    # `FaceWall` lives in OST_Walls, so it does reach the census and the
    # extraction — but two of the op's defining fields are absent there by
    # construction. First: a `FaceWall` has NO `LocationCurve` (it is not a
    # `Wall` — measured, CS0029 on all six), so an ordinary wall row with
    # p0/p1 cannot describe it at all. Second: the host and the FACE NORMAL
    # a wall was built on are captured by nothing in L0 — a wall's
    # face-based `HostReference` is read by no field of the current
    # extraction. Sending the next person to the lifter would send them to
    # fix something that is not broken.
    "create_face_wall": ReverseContract(
        "create_face_wall", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 carries no host-face reference and no face normal for a wall "
        "built on a mass face, and a FaceWall has no LocationCurve to "
        "describe it the way an ordinary wall row does",
        sources=("L0:OST_Walls",),
        decided_on="2026-08-10", due="2026-09-09",
        limitation=("recovering the op needs the host mass id AND the model "
                    "normal of the parent face; until capture reads both, "
                    "such a wall lifts as an atom — never silently dropped")),
    "place_family": _direct(
        "place_family", "_lift_family_fallback",
        sources=("side:family_placement",)),
    "set_curtain_panel": _direct(
        "set_curtain_panel", "_lift_curtain_panel",
        sources=("L0:OST_CurtainWallPanels", "side:curtain")),
    "create_curtain_grid_line": _direct(
        "create_curtain_grid_line", "_grid_line_node",
        sources=("side:curtain_grid_line",)),
    # wave/room (2026-08-03). The inversion is PER-SEGMENT and therefore
    # exact: in L0, each OST_RoomSeparationLines is one ModelCurve with its
    # own p0/p1 and its own level_id, and the lift gives it a polyline of
    # exactly two points (the law "one L0 element -> EXACTLY ONE L1 node"
    # would not allow stitching neighbouring lines into one polyline, and
    # there is nothing to stitch them with anyway: they share no common
    # identity). The guarantee is BOUNDED, not FORM_EXACT: an arc separator
    # is not expressible at all (`path` has no arc parameter — 14 of 2313
    # on K2), and a separator whose plane is offset from its own level also
    # stays an atom, because the operation itself has no offset input (4 of
    # 2313).
    "create_room_separator": _direct(
        "create_room_separator", "_lift_room_separator",
        sources=("L0:OST_RoomSeparationLines",),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("an arc separator has no expressible parameter and a "
                    "chord would silently straighten it; a separator whose "
                    "plane is offset from its own level has no offset "
                    "parameter either — both stay typed atoms")),

    # wave/site (2026-08-09). Three site ops are CAPTURE_GAP, and this is
    # a MEASUREMENT, not caution: the extraction category table
    # (decompile/extract.py) has neither OST_Topography, nor OST_Toposolid,
    # nor OST_BuildingPad, nor OST_Site — the pipeline does NOT read them
    # at all. Declaring DIRECT would promise a lift for which not even an
    # L0 row is assembled; the manifest exists precisely so such promises
    # do not go stale silently. The difference between "the stage refused"
    # and "the stage said nothing" falls on the latter here.
    "create_topography": ReverseContract(
        "create_topography", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction reads neither OST_Topography nor OST_Toposolid, so L0 "
        "carries no terrain points at all",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_Topography", "L0:OST_Toposolid"),
        limitation=("capture must start reading TopographySurface.GetPoints() "
                    "(and the toposolid's slab-shape vertices) before a "
                    "lifter is legal — a terrain re-emitted from its bounding "
                    "box would be a different landscape")),
    "create_building_pad": ReverseContract(
        "create_building_pad", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction does not read OST_BuildingPad, and the pad's sketch "
        "boundary is not captured anywhere",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_BuildingPad",),
        limitation=("capture must start reading BuildingPad.GetBoundary() and "
                    "its level before a lifter is legal")),
    # wave/sweep (2026-08-09). Both ops are CAPTURE_GAP, and this is a
    # MEASUREMENT the same way as the site wave's: the extraction category
    # table (decompile/extract.py) has neither OST_Cornices, nor
    # OST_Reveals, nor OST_EdgeSlab — the pipeline does NOT read them at
    # all. Declaring DIRECT would promise a lift for which not even an L0
    # row is assembled.
    "create_wall_sweep": ReverseContract(
        "create_wall_sweep", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction reads neither OST_Cornices nor OST_Reveals, so L0 carries "
        "no wall sweep at all",
        sources=("L0:OST_Cornices", "L0:OST_Reveals"),
        limitation=("capture must start reading WallSweep.GetHostIds() and "
                    "GetWallSweepInfo().IsVertical before a lifter is legal — "
                    "and note that the sweep's POSITION is unrecoverable by "
                    "construction, because Autodesk documents it as coming "
                    "from the type, not from the call, so a lifted sweep can "
                    "only ever name its host, its type and its orientation"),
        decided_on="2026-08-09", due="2026-09-08"),
    "create_slab_edge": ReverseContract(
        "create_slab_edge", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction does not read OST_EdgeSlab, and the host edges a slab "
        "edge runs along are not captured anywhere",
        sources=("L0:OST_EdgeSlab",),
        limitation=("capture must start reading the host and the swept edges "
                    "(HostedSweep.get_ReferenceCurve over the host's "
                    "perimeter) before a lifter is legal; re-emitting a slab "
                    "edge from its bounding box would put it on the wrong "
                    "edges"),
        decided_on="2026-08-09", due="2026-09-08"),
    "create_site_subregion": ReverseContract(
        "create_site_subregion", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction does not read the site categories, and a sub-region is "
        "indistinguishable from a plain topography surface in L0",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_Topography", "L0:OST_Site"),
        limitation=("capture must start reading "
                    "TopographySurface.IsSiteSubRegion and "
                    "SiteSubRegion.GetBoundary()/HostId; lifting a sub-region "
                    "as a plain surface would silently drop its host")),

    # The op exists, but current frozen capture lacks a mandatory source fact.
    # THIS RECORD WAS MOVED FROM `capture_gap` TO `direct` BY THE
    # DIMENSIONS WAVE, and this is exactly the day `capture_gap`'s
    # `decided_on` and `due` were introduced for (see the ratchet above:
    # "goes stale silently on the exact day the capture wave starts
    # reading the named field, and nobody comes to erase the line").
    #
    # The previous reason named TWO missing facts — "owner-view basis" and
    # "Dimension.References". Both are now read by the `dimension` stage
    # (`decompile/dimension_extract.py`): the view basis the same way as
    # tags and text notes, and `Dimension.References` -> `ReferenceArray`
    # by type, NAMED by the compiler against 2021/2023/2026, not taken
    # from documentation.
    #
    # THE GUARANTEE IS `BOUNDED`, NOT `FORM_EXACT`, AND THIS IS THE MAIN
    # POINT OF THIS RECORD. `refs` carries ELEMENTS, while `NewDimension`
    # requires GEOMETRIC references; WHICH face of the element is taken is
    # decided by the forward walk (`authoring._dim_geom_helpers_cs`), not
    # by what was read. So we promise to rebuild the dimension BETWEEN THE
    # SAME ELEMENTS, but not that the VALUE will match: a dimension to a
    # wall's outer face and one to its centerline bind the same pair of
    # elements. Declaring `FORM_EXACT` here would promise something no
    # offline measurement can confirm — and the bridge is disabled.
    "create_dimension": _direct(
        "create_dimension", "_lift_dimension",
        guarantee=ReverseGuarantee.BOUNDED,
        sources=("L0:OST_Dimensions", "side:dimension"),
        limitation=(
            "the rebuilt dimension binds the SAME ELEMENTS, but not "
            "necessarily the same FACES of them: Reference geometry is not "
            "captured, and the forward walk picks the face itself, so the "
            "measured VALUE may differ (the forward emitter gates that value "
            "itself). Non-linear shapes (Radial/Angular/...) stay atoms with "
            "unsupported_forward_signature")),
    # 08-09: an angular dimension has the same capture gap, and it is
    # WORSE by one quantity — besides the view and References, the arc
    # itself (vertex + radius + a pair of rays) would also need
    # recovering, and the frozen L0 1.0 row carries it in no form at all.
    # CAPTURE_GAP is declared explicitly rather than implied: the manifest
    # exists precisely so the promise of a lift does not go stale
    # silently.
    "create_angular_dimension": ReverseContract(
        "create_angular_dimension", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 has no owner-view basis, Dimension.References or the annotation arc",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_Dimensions",),
        limitation="must extend annotation capture before a lifter is legal"),
    # wave/detail (2026-08-09). CAPTURE_GAP, and this is a MEASUREMENT
    # from the extraction category table (decompile/extract.py): it has
    # neither OST_FilledRegion nor OST_MaskingRegion — the fill pipeline
    # does not read them at all, so "the stage refused" does not even
    # arise here, there is no stage. The gap is DOUBLE besides: it is not
    # enough to read `GetBoundaries()`, one must also be able to translate
    # its curves into the owner view's axes (Origin/Right/Up), or the
    # lifted boundary ends up in world XY — the exact mixing of spaces the
    # forward path refuses to express.
    "create_filled_region": ReverseContract(
        "create_filled_region", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction reads neither OST_FilledRegion nor OST_MaskingRegion, so "
        "L0 carries no region boundary and no owner-view basis",
        sources=("L0:OST_FilledRegion", "L0:OST_MaskingRegion"),
        # THE DATE AND DEADLINE WERE ADDED DURING THE 08-09 MERGE — the
    # second time in one evening and for the same reason: the detail
    # wave's base predates the record ratchet, its `capture_gap` arrived
    # PLAIN, and the import REFUSED instead of staying silent. The wave's
    # day, thirty days deadline — like all the rest.
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("capture must start reading FilledRegion.GetBoundaries() "
                    "AND the owner view's Origin/Right/Up before a lifter is "
                    "legal — a boundary re-emitted in world XY would be a "
                    "different place on every non-plan view")),
    # wave/opening (2026-08-03). The op EXISTS, there is no reverse path,
    # and this is stated here rather than implied: the frozen L0 1.0 row
    # carries NOT ONE mandatory opening input — neither Opening.Host (the
    # host) nor Opening.BoundaryRect/BoundaryCurves (the boundary).
    # Declaring DIRECT would promise a lift that does not exist, and this
    # manifest exists precisely so such promises do not go stale silently.
    # HALF THE REASON WAS CLOSED on 2026-08-09 by the host-capture wave,
    # and the text was brought into line within the hour: `Opening.Host`
    # is read (measured by compilation 6/6, `extract._HOST_READERS`,
    # `host_source="opening"`). The mode stays capture_gap, because the
    # other half of the input — the opening's BOUNDARY (BoundaryRect /
    # BoundaryCurves) — is still read by nothing, and without it a lifter
    # is impossible. Writing "carries neither Opening.Host nor the
    # boundary" after the first half stopped being true would keep in the
    # manifest exactly the staleness it was introduced against.
    # 🔴 THE SECOND HALF OF THE REASON WAS CLOSED ON 2026-09-04 — THE
    # BOUNDARY IS READ (`extract._opening_boundary_reader_cs`:
    # IsRectBoundary + BoundaryRect / BoundaryCurves, all three 6/6, zero
    # traps). The mode became DIRECT, but the lift is PARTIAL, and this is
    # exactly the shape of the railing entry below: one kind inverts, the
    # other stays an atom, and the reason for the latter is a MISSING
    # GETTER, not the poverty of our reading.
    #
    # THE MEASUREMENT THAT SETTLES THIS: the type
    # `Autodesk.Revit.DB.Opening` has EXACTLY SEVEN members across all six
    # versions — BoundaryCurves, BoundaryRect, Host, IsRectBoundary,
    # IsTransparentIn3D, IsTransparentInElevation and SketchId (2022+). The
    # cut direction is not among them. For `variety="host_face"` the `cut`
    # input is declared WITH NO DEFAULT deliberately (vertical and
    # perpendicular coincide only on a flat host and give different
    # openings on a slope), so host_face will never become a forward path
    # for ANY reading wave — there is nothing to read. An arc boundary
    # refuses separately: `outline` is a polyline, and the arc beneath it
    # becomes a chord, i.e. a different opening.
    "create_opening": _direct(
        "create_opening", "_lift_opening",
        sources=("L0:OST_SWallRectOpening", "L0:OST_FloorOpening",
                 "L0:OST_RoofOpening"),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only variety=wall_rect is inverted; a host_face opening "
                    "stays an atom because the cut direction has no getter on "
                    "Opening (seven members on all six versions, none of them "
                    "the cut), an arc boundary stays an atom because outline "
                    "is a polyline, and a snapshot taken before 2026-09-04 "
                    "carries no opening_is_rect key and refuses exactly as "
                    "before; the shaft variety is outside the forward op")),
    # 2026-08-03: MOVED FROM capture_gap TO direct, and the reason is a
    # measurement, not a preference. Railing capture
    # (``sketch_extract.RailingPathRecord``: Railing.GetPath, HasHost/HostId,
    # STAIRS_RAILING_BASE_LEVEL_PARAM) has been running since 07-29 and
    # collects data in production; k2_ar_rd_v9 carries 31 capture rows, 28
    # of them free railings with a path and a base level. So the earlier
    # wording "L0 has neither a railing path nor hosted placement position"
    # stopped being true in its first half — and the manifest exists
    # precisely so such statements do not go stale silently.
    #
    # THE SECOND HALF STAYED ENTIRELY TRUE, which is why the guarantee is
    # BOUNDED, not FORM_EXACT: a STAIRS railing does not invert at all —
    # the API has no getter for the position (Treads/Stringer) on any of
    # the six versions.
    "create_railing": _direct(
        "create_railing", "_lift_railing",
        sources=("L0:OST_Railings", "L0:OST_StairsRailing", "side:sketch"),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only variety=path is inverted; a hosted railing stays an "
                    "atom because RailingPlacementPosition has no getter on "
                    "any shipped version, and re-emitting it as a free path "
                    "railing would silently drop its host")),

    # wave/mep-electrical (2026-08-09). Four ops EXIST, there is no reverse
    # path, and the reason is different for each pair — stated here rather
    # than implied.
    #
    # PLACEHOLDERS — THE GAP WAS CLOSED ON 2026-09-04, FOUR DAYS BEFORE ITS
    # DEADLINE.
    #
    # A `capture_gap` stood here, decided on 08-09 with an 09-08 deadline,
    # and it described this house's ONE kind that lied silently instead of
    # refusing: a placeholder and a real segment produced a byte-identical
    # L0 row, and the reverse path rebuilt the placeholder as a
    # FULL-FLEDGED pipe. It closed with exactly what it promised to close
    # it with — one field: `L0Element.is_placeholder`, read by
    # `extract._placeholder_reader_cs`, branched on in `lift._lift_pipe` /
    # `_lift_duct`.
    #
    # Names were checked AGAINST THE TRAP INDEX, not from memory: both
    # live on all six versions, both have ZERO documented traps, both are
    # in RevitAPI — the assembly capture already references.
    #
    # 🔴 THE GUARANTEE IS `BOUNDED`, NOT `FORM_EXACT`, AND THIS IS NOT
    # CAUTION. A snapshot taken BEFORE 09-04 carries no key, and the
    # absence of a key means "not measured", not "not a placeholder". Such
    # a row lifts as before, i.e. on an old snapshot the defect REMAINS,
    # and the only honest form of that is naming the boundary here, rather
    # than declaring the loop closed for every snapshot at once. Refusing
    # on `None` would be worse than the defect: it would take down every
    # segment of every decompile taken before today — the exact law
    # `curve_kind` lives by.
    "create_pipe_placeholder": _direct(
        "create_pipe_placeholder", "_lift_pipe",
        sources=("L0:OST_PipeCurves",),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only a row whose is_placeholder key was captured is "
                    "inverted as a placeholder; a snapshot taken before "
                    "2026-09-04 carries no such key, and its placeholder "
                    "still lifts as a REAL create_pipe exactly as before")),
    "create_duct_placeholder": _direct(
        "create_duct_placeholder", "_lift_duct",
        sources=("L0:OST_DuctCurves",),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only a row whose is_placeholder key was captured is "
                    "inverted as a placeholder; a snapshot taken before "
                    "2026-09-04 carries no such key, and its placeholder "
                    "still lifts as a REAL create_duct exactly as before")),
    # FLEXIBLE. Here the capture gap is wider still and it is GEOMETRIC:
    # an L0 row knows a pair of curve endpoints, while a flex segment's
    # shape lives in `FlexDuct.Points`/`FlexPipe.Points` — a Hermite spline
    # through N points. Such a run's endpoints do not recover it: any
    # polyline with the same endpoints would give the same row. Hence both
    # the capture_gap mode and no representation_ops at all: substituting
    # a flexible run with a straight segment between its endpoints would
    # invent geometry, not express the missing one.
    # 🔴 THE GAP WAS CLOSED ON 2026-09-04, FOUR DAYS BEFORE THE DEADLINE.
    # The census reads `FlexDuct.Points`/`FlexPipe.Points`
    # (`extract._flex_path_reader_cs`), the path rides the
    # `L0Element.flex_path_mm` field, and the lifters are written as one
    # body (`lift._lift_flex_run`). What is read is `Points` SPECIFICALLY,
    # not `LocationCurve`: a flex element's curve there is a Hermite
    # spline whose endpoints are derived from the points, while the
    # forward op requires checking ALL the points and their count.
    #
    # THERE ARE TWO BOUNDARIES, and both are named, not left unsaid. The
    # first: an old snapshot carries no key and gives the SAME atom with
    # the same text as yesterday. The second: the language holds 2..64
    # points, and a longer run refuses BY NAME rather than being
    # truncated — a dropped middle would be a different run under a green
    # verdict.
    "create_flex_duct": _direct(
        "create_flex_duct", "_lift_flex_duct",
        sources=("L0:OST_FlexDuctCurves",),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only a row whose flex_path_mm was captured is inverted; "
                    "a snapshot taken before 2026-09-04 carries no such key "
                    "and still refuses with the same source_contract_gap, and "
                    "a run of more than 64 points refuses by name because "
                    "path3 cannot express it")),
    "create_flex_pipe": _direct(
        "create_flex_pipe", "_lift_flex_pipe",
        sources=("L0:OST_FlexPipeCurves",),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only a row whose flex_path_mm was captured is inverted; "
                    "a snapshot taken before 2026-09-04 carries no such key "
                    "and still refuses with the same source_contract_gap, and "
                    "a run of more than 64 points refuses by name because "
                    "path3 cannot express it")),

    # Current-state reverse representations that are intentionally not the
    # same high-level op.
    "create_group": ReverseContract(
        "create_group", ReverseMode.COMPOSED, ReverseGuarantee.BOUNDED,
        "group relations fold member leaves; optional native-group bridge "
        "re-composes a create_group program",
        sources=("side:group",),
    # TWO ENTRYPOINTS, AND THEY ARE ABOUT DIFFERENT THINGS. `lift_groups`
    # (2026-08-23) is the reverse path over the GROUPS OF A READ BUILDING:
    # the `group_extract` side index -> `create_group` with offsets
    # derived from the members' coordinates. `component_to_group_program`
    # is a bridge for OUR OWN component library, with no relation to a
    # building; it stays in the advance journal because there is still
    # nothing to feed it with.
        entrypoints=("lift_groups", "component_to_group_program"),
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
    # WALL TYPE WITH A COMPOUND STRUCTURE (2026-08-23). Mode LIFTER_GAP,
    # not CAPTURE_GAP, and this is a reversal on the same day: before it,
    # the layer makeup was not read AT ALL (0 of 44 types on K1, and
    # `uniform: true` meant "no blockers for a curtain shell", not "one
    # layer"). Now `TypeSection.layers` carries a triple per layer —
    # thickness, function, material NAME — and the name-based link is
    # checked live: 32 of 32 layer materials were found in the `materials`
    # pool.
    #
    # READ, BUT NOT LIFTED: no lifter produces `create_wall_type`, so a
    # wall type in a foreign document still has to be named by hand. What
    # this costs, in numbers: the authored K3 apartment in a clean
    # "Проект1" — 12 of 29 wall operations blocked by a missing type.
    "create_wall_type": ReverseContract(
        "create_wall_type", ReverseMode.LIFTER_GAP, ReverseGuarantee.NONE,
        "capture reads the compound structure since 23.08.2026 (40 of 44 wall "
        "types on K1 carry layers; 18 of 44 are compound); no lifter emits the "
        "op yet, so a wall type is still named by hand in a foreign document",
        sources=("open_model:wall_types.section.layers",),
        limitation=("6 of 44 types are not reproducible at all and the op "
                    "refuses them by name: 4 carry no CompoundStructure, "
                    "3 are Curtain, 2 vertically_compound (SetLayers is "
                    "documented to reset the structure to vertically "
                    "homogeneous), 1 is Stacked")),
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
    # 🔴 THIS OP DOES NOT LIFT FROM AN ELEMENT, AND NEVER WILL. A decompile
    # carries no family PROVENANCE AT ALL — the 2026-08-23 measurement is
    # exhaustive: 23 L0 row keys, 30 Revit parameter names, 17 placement
    # index fields, all 20 side indexes; matches against
    # PATH|FILE|SOURCE|RFA|LIBRARY|URL are ZERO, and `Family` itself has 27
    # members and not one path. There is nothing to ask: for a loaded
    # family, provenance does not exist as a fact.
    #
    # WHICH IS WHY `capture_gap` WOULD BE A LIE HERE — it would send the
    # next person to fix READING that does not exist. The op is
    # SYNTHESIZED by the materializer from the fact "the program addresses
    # a family absent from the target document", exactly as
    # `create_curtain_grid_line` is synthesized from a side index rather
    # than lifted from an element. Synthesis has one source — the
    # REQUIREMENT COUNTER
    # (`MaterializeStats.catalog_family_symbols_required`, K3 196 / K6
    # 192), and it already counts correctly.
    #
    # 🔴 THE BOUNDARY IS NAMED HONESTLY: the synthesis itself into the
    # program's head is NOT YET DONE. The op exists, compiles 6/6, has
    # never run live; emission is the next wave. The record stands here
    # precisely so this does not look finished.
    "transfer_family": ReverseContract(
        "transfer_family", ReverseMode.EXTERNAL_SOURCE, ReverseGuarantee.NONE,
        "a loaded family retains no provenance at all: neither a path nor the "
        "document it came from, so this op is never lifted from an element — "
        "it is SYNTHESIZED by the fresh_document materializer from the "
        "catalog-requirement counter",
        sources=("side:catalog_family_symbols_required",),
        limitation="synthesis into the fresh_document program head is not "
                   "implemented yet; the op compiles 6/6 and has never run "
                   "live"),

    # THE MATERIAL IS READ, BUT DOES NOT LIFT (2026-08-24). A decompile
    # DOES SEE the material name in every layer of a compound structure —
    # `create_wall_type.layers[].material` comes from exactly there — but
    # no lifter produces the transfer itself: a material in the target
    # document carries no provenance from which one could derive WHICH
    # document it should come from.
    #
    # What this costs, in numbers (08-24): a catalog of K3's 18 host types
    # builds on 2 in a clean document, the rest are short 23 materials.
    # The op closes the path, but its synthesis into the transfer
    # program's head is not written yet — exactly the same unclosed half
    # as `transfer_family`.
    "transfer_material": ReverseContract(
        "transfer_material", ReverseMode.EXTERNAL_SOURCE, ReverseGuarantee.NONE,
        "a material carries no provenance of the document it came from, so "
        "this op is never lifted from an element — it must be SYNTHESIZED "
        "from the layer-material names the capture already reads",
        sources=("open_model:wall_types.section.layers.material",),
        limitation="synthesis into the transfer program head is not "
                   "implemented yet; the op compiles 6/6 in both isolations "
                   "and its live run needs BOTH documents in ONE Revit "
                   "session (Application.Documents enumerates only its own)"),

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
    # 🔴 COMPOSED (2026-08-22). THE PREVIOUS RECORD WAS A LIE FROM THE VERY
    # HOUR IT WAS WRITTEN, AND THIS IS MEASURED, NOT SAID IN ANGER.
    #
    # It said: «nothing in decompile/ reads it yet: measured 2026-08-17,
    # zero occurrences». Measured from this tree's log:
    #
    #     39ebd521  08-18 07:03  `GetJoinedElements` appears in decompile/
    #     518325f3  08-18 07:19  "zero occurrences" is written here
    #
    # SIXTEEN MINUTES. The same session, the same hand: reading was
    # already running when the record declared it absent. The review date
    # (09-17) was correct in form and useless in substance — the ratchet
    # guards the DEADLINE, not the TRUTH of the reason, and says so about
    # itself (`record_ratchet.py`, "it cannot verify that the reason is
    # still TRUE"). The guard for this shape was introduced by the eighth
    # agreement (`kir/agreements.py`).
    #
    # WHAT CAPTURE CAN DO AS OF 2026-08-22 — THREE KINDS, SEPARATELY:
    #
    #     joined_to             GetJoinedElements       join_extract.py:823
    #     join_allowed_at_end   IsWallJoinAllowedAtEnd  join_extract.py:849,851
    #     elements_at_end_join  get_ElementsAtJoin      join_extract.py:885
    #
    # The addresses are of CALLS, not of steps. Nearby (820/842) sit
    # `__jnStep` labels, and citing them would name as the address a line
    # where nothing happens.
    #
    # WHY NOT `LIFTER_GAP` (the first instinct) — THE LIFTER WAS WRITTEN
    # TODAY: `decompile/lift.py:lift_joins`. Leaving "there is no lifter"
    # would repeat the exact address defect this record just paid for.
    #
    # WHY NOT `DIRECT`, EVEN THOUGH THE SAME OP LIFTS. `DIRECT` grants
    # `direct_same_op_lift`, and its only consumer is
    # `assert_lift_emission`, i.e. permission to place an L1 NODE. A join
    # cannot be a node by construction: a flat L1 is one node per element
    # (`validate_l1_nodes` flags a repeated `source_element_id`,
    # `fold_document` flags `invented`), and a relation has no element of
    # its own. Declaring DIRECT would grant a permission whose execution
    # breaks the fold — a promise stronger than the truth. `COMPOSED`
    # describes exactly what happens: a composite operation AFTER the
    # lift, like `create_group`'s `component_to_group_program`.
    #
    # THE GUARANTEE IS BOUNDED, AND THE BOUNDARY IS MEASURED, NOT DECLARED
    # (2026-08-22, decompiles on disk): MNVNK 1,992 pairs of 10,082,
    # k2v33_join2 1,887 of 1,952. The remainder is an end that stays an
    # ATOM, and on MNVNK there is ONE reason: 10,280 `OST_Walls` ends with
    # `missing_geometry`, meaning the work lies in lifting the wall, not
    # in the join.
    #
    # THE FORWARD SIDE'S LIVE RUN — FOUR RUNS, NOT ONE FULL CHAIN
    # (witness corpus `data/telemetry/kir_witness.jsonl`): 08-18 rolled
    # back ×10, 08-22 committed three times (×24, ×24, ×2) — and all four
    # have `ok=False`, acceptance did not agree. This is a fact about the
    # FORWARD path, and it stands here so "the op lifts" does not read as
    # "the op is proven".
    "join_elements": ReverseContract(
        "join_elements", ReverseMode.COMPOSED,
        ReverseGuarantee.BOUNDED,
        "capture reads all THREE join relations live since 18.08.2026 "
        "(JoinGeometryUtils.GetJoinedElements · "
        "WallUtils.IsWallJoinAllowedAtEnd · LocationCurve.get_ElementsAtJoin, "
        "join_extract.py:823/849/885) and lift_joins composes join_elements "
        "from the symmetric joined_to pairs after the per-element lift; a "
        "join is a RELATION and can never be an L1 node, so the mode is "
        "composed, not direct",
        sources=("side:join",),
        entrypoints=("lift_joins",),
        representation_ops=("join_elements",),
        limitation=(
            "ONE relation of the three is expressible: join_allowed_at_end "
            "(WallUtils.IsWallJoinAllowedAtEnd — a property of one wall end) "
            "and elements_at_end_join (LocationCurve.get_ElementsAtJoin — an "
            "end-to-end butt) have no op in the registry, and substituting "
            "join_elements for them would be a lie, not an approximation — "
            "measured live 18.08.2026 on one wall pair where the ends ARE "
            "butted while AreElementsJoined is False and JoinGeometry "
            "refuses. Cut order (JoinGeometryUtils.SwitchJoinOrder / "
            "JoinGeometryUtils.IsCuttingElementInJoin) is NOT READ by capture "
            "at all — a named absence, not a lifter gap. And the composed ops "
            "do not reach a program yet: orchestrator.decompile takes no "
            "join_index argument, and LiftResult cannot carry them because "
            "lift_cache.serialize_lift_result is written field by field and "
            "would drop a new one silently")),
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
