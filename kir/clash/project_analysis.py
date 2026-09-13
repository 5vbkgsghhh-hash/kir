"""ANALYSIS OF THE SAVED PROJECT: bodies from the store take part in clash
search.

🔴 WHAT THIS MODULE CLOSES, AND THE NUMBER THAT STARTED IT (06.09.2026).
Measurement on the saved residential complex
(`examples/residential_with_podium.py` → store): the scene had
`hulls 0 · pairs_compared 0 · findings 0 · search_complete False`, and the
podium body with the atrium (8 KB of BRep in the store) did not reach the
analysis AT ALL. There was one cause, and it was found by execution: the op
carries `category: "mass"`, the registry returns
`("DirectShape", "OST_Mass")`, the census key is discarded, `OST_Mass`
remains — which was not in `clash.hulls.KIND_TABLE`. That is, the form for
whose preservation the recipes, bundles, and store were built took no part
in the analysis.

WHAT IS NOT HERE, AND THIS IS NAMED BEFORE THE CODE:
  * NO new building graph, new kernel, or new certificates — the owner's
    prohibition;
  * NO new storage schema: a finding's address is the project's
    `output_id`, which is ALREADY the materialization's `op_id` and the
    clash census's `element_id`. The link already existed; all that was
    missing was for the body to arrive;
  * NO exact phase. A coarse hull is a bounding box, and its coarseness is
    printed in `hull_source`/`analysis_limits`, not silenced. The exact
    phase is built by a neighbor (`kir.clash.exact.verify_pair`); the seam
    here is a call by name, and while the module does not exist, the
    limitation is NAMED, not implied;
  * NO live Revit: it is the saved form of the project that is judged, not
    a built BIM.

TWO BOUNDARIES THAT ARE EASY TO CROSS SILENTLY, AND SO STAND EXPLICITLY:

1. **THE FRAME.** `GeometryBundle.read_body()` returns the shape in LOCAL
   coordinates. A bounding box taken from it WITHOUT the frame will place
   the body in the wrong spot, and nobody will notice. Here the frame is
   applied in ONE place — `_brep_bbox` — and this is the module's only line
   where local coordinates become project coordinates. The exact phase is
   given the body LOCAL, together with the frame (`bodies`); it applies the
   frame itself.
2. **A STALE PREVIEW.** Materialization marks `stored_preview_bytes_equal`.
   If the preview has diverged from the BRep, and the BRep exists — the
   hull is built FROM the BRep, and `hull_source` says `brep`. Taking the
   preview would mean judging by a picture of the body instead of the body.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import math
from typing import Any

UNITS = "mm"

#: The default tolerance. Declared HERE and travels entirely into the
#: policy's signature: acceptance must catch a tolerance weakening by a
#: number, not by trust.
#: The carrier of the clearance requirement. Today there is only ONE, and
#: hence it is named as a string rather than inferred: the reader must be
#: able to see WHOSE decision the number was taken by. Should an op
#: parameter or a type property appear, a second name will appear here,
#: not silence.
CLEARANCE_SOURCE = "analysis_policy.clearance_mm"

#: The limitation string for when there is no requirement at all.
NO_CLEARANCE_REQUIREMENT = (
    "требование зазора не задано (clearance_mm = 0): вердикт `clear` означает "
    "«тела не пересекаются», а НЕ «зазор выдержан»")

DEFAULT_TOLERANCE_POLICY: dict[str, Any] = {
    "schema": "kir-clash-tolerance/1",
    "slack_mm": 0.0,
    "clearance_mm": 0.0,
    "exact_pair_budget": 64,
}


class ProjectAnalysisError(Exception):
    """The analysis did not take place. Silence would read as "there are
    no clashes"."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class Finding:
    """A single pair. The field names carry BOTH contracts — the plan's and
    the acceptance instrument's.

    Different names for one fact were not introduced out of sloppiness: the
    plan (`§1`) and the `acceptance/run.py` instrument were assigned
    separately and diverged in spelling. Introducing a third name would be
    the worst option; so here one value is printed under both names, and
    the discrepancy is named in the report rather than hidden.
    """

    finding_id: str
    a_output_id: str
    b_output_id: str
    status: str   # confirmed | possible | refuted | clearance_violated | clearance_unverified
    relation: str                   # intersect | contained | clear
    kind: str                       # overlap | containment | clearance
    evidence: str
    depth_mm: float | None = None
    gap_mm: float | None = None
    overlap_volume_mm3: float | None = None
    surface_intersections: int | None = None
    exact_source: str | None = None
    # 🔴 CLEARANCE IS A REQUIREMENT, NOT THE ABSENCE OF INTERSECTION (owner,
    # 07.09.2026). Before this wave, a pair separated by 10 mm under a
    # requirement of 50 was receiving `refuted / clear / clearance` — i.e.
    # the STRONGEST assertion the analysis can make ("intersection is
    # provably absent") in a case where the requirement was VIOLATED, and
    # the fixer would then refuse: "nothing to fix: the pair is clear". The
    # three fields below exist only when a requirement is DECLARED: their
    # absence means "we did not ask", not "satisfied".
    required_clearance_mm: float | None = None
    deficit_mm: float | None = None
    #: The carrier of the requirement: whose decision it was taken by.
    #: Today there is one carrier — the analysis policy (`clearance_mm`);
    #: should an op parameter or a type appear, the value will name it, and
    #: the reader will see WHOSE number it is.
    clearance_source: str | None = None

    # ── the acceptance instrument's names
    @property
    def a(self) -> str:
        return self.a_output_id

    @property
    def b(self) -> str:
        return self.b_output_id

    def to_dict(self) -> dict:
        return {"finding_id": self.finding_id, "a": self.a_output_id, "b": self.b_output_id,
                "a_output_id": self.a_output_id, "b_output_id": self.b_output_id,
                "status": self.status, "relation": self.relation, "kind": self.kind,
                "evidence": self.evidence, "depth_mm": self.depth_mm, "gap_mm": self.gap_mm,
                "overlap_volume_mm3": self.overlap_volume_mm3,
                "surface_intersections": self.surface_intersections,
                "exact_source": self.exact_source,
                # The keys appear ONLY when a requirement is declared: an
                # empty field would read as "a requirement exists and is
                # satisfied".
                **({} if self.required_clearance_mm is None else {
                    "required_clearance_mm": self.required_clearance_mm,
                    "deficit_mm": self.deficit_mm,
                    "clearance_source": self.clearance_source})}


@dataclass(frozen=True)
class ProjectClashReport:
    """What the analysis saw — TOGETHER with what it did not see and why."""

    revision: str
    program_digest: str
    tolerance_policy_digest: str
    bodies_declared: int
    body_ids: frozenset
    bodies_with_hull: int
    bodies_in_pairs: dict
    hull_source: dict
    source_of_truth: dict
    pairs_compared: int
    search_complete: bool
    analysis_limits: list
    findings: list
    not_evaluated: dict
    # 🔴 A PARTICIPANT IS NOT AN OUTPUT (owner, finding 6, 07.09.2026). A
    # large-scale fixture declared 10 000 walls and printed "10 005
    # outputs", while the measurement showed: the walls have no contour, no
    # section, no bounding box, not a single one gets a hull built, and
    # there are 0 of them in pairs. The number of outputs does not prove
    # participation; the denominator here is bodies WITH GEOMETRY, i.e.
    # those that ENTERED the broad phase with a hull. `bodies_declared`
    # counts declared bodies (an output carries `geometry`),
    # `bodies_with_geometry` counts those that entered the search,
    # `bodies_in_pairs` counts those for which at least one pair was found.
    bodies_with_geometry: int = 0
    #: What the broad phase compared and what it spared. `pairs_possible` —
    #: the full double loop (`N·(N−1)/2`), `pairs_compared` — how many pairs
    #: were actually checked. BOTH are printed: one number does not
    #: distinguish "the index screened it out" from "the bodies did not
    #: reach the search".
    pairs_possible: int = 0
    broad_phase: dict = field(default_factory=dict)
    #: Bodies for the exact phase: `output_id -> (TopoDS_Shape IN LOCAL
    #: coordinates, frame)`. The frame is applied by `verify_pair`, not us
    #: (contract `geo-loop/CONTRACT-AB.md`).
    bodies: dict = field(default_factory=dict, repr=False)
    #: `output_id -> ([min_x,min_y,min_z], [max_x,max_y,max_z])` — the
    #: bounding box of THAT VERY hull against which the relations were
    #: computed. Placed here so that a fix computes the lift along the
    #: RIGHT axis, not by "depth in general": for a coarse finding
    #: `depth_mm` is the overlap along the SHORT axis, for an exact one it
    #: is a number from a different law, and neither of the two answers the
    #: question "how much to lift along z". The bounding boxes do answer
    #: it, and PROVABLY so: by separating the bounding boxes along z, we
    #: also separate the bodies that lie within them.
    hull_bounds: dict = field(default_factory=dict, repr=False)
    #: `output_id -> (instance_key, output_key)` — the AUTHORING name of the
    #: same body. 🔴 Introduced on 06.09.2026, not for the sake of prettiness.
    #: `output_id` is 64 hexadecimal digits with not a single separator, and
    #: anyone who wants to say "podium" must recompute the address
    #: themselves. The acceptance instrument did not do this: its
    #: `find_pair` was cutting the address on `/` hoping for a path, and was
    #: finding NOT A SINGLE pair, which is why item (2) said NO on numbers
    #: that had in fact converged, and item (1) said YES for the same
    #: reason — having found no pair at all. A report whose address is
    #: unreadable buys such mistakes for every next reader; here the
    #: translation sits right next to the address. The report's key remains
    #: `output_id` (the acceptance contract, CONTRACT.md §19) — this is a
    #: TRANSLATION, not a second address.
    body_keys: dict = field(default_factory=dict, repr=False)
    #: `output_id -> frame` (16 numbers, row-major). 🔴 WITHOUT IT A FIX
    #: COMPUTES IN THE WRONG COORDINATES. The bounding boxes (`hull_bounds`)
    #: are in WORLD coordinates, while the box in the instance's parameters
    #: is LOCAL; to lift the body by world `L` mm, one must add
    #: `Rᵀ·(0,0,L)` to the parameter, not `(0,0,L)`. Only the analysis knows
    #: the frame (it reads the bundle's manifest), so it is the analysis
    #: that carries it in the report — otherwise the fixer would be
    #: guessing it or staying silent.
    body_frames: dict = field(default_factory=dict, repr=False)
    #: `output_id -> {bundle_sha256, body_sha256, frame, modeling_tolerance_mm}`
    #: — the IDENTITY of the geometry that was read, not a reference to it.
    #: 🔴 Introduced on 07.09.2026 per measurement G02: the scene
    #: (`viewer/standalone_export`) and the emission
    #: (`materialization.sources`) were naming the bundle, the body, and the
    #: frame, while the analysis report named NOT ONE of the three, and
    #: nobody named the modeling tolerance. A reader who cannot say WHICH
    #: body they read is cross-checked against a revision neighbor — i.e.
    #: by a trait shared by all of a revision's bodies at once. The rows are
    #: taken from `materialize_project(...).sources`, not recomputed: a
    #: second source of the same truth would have diverged silently.
    body_geometry: dict = field(default_factory=dict, repr=False)
    #: The resolved tolerance policy IN FULL, not only its signature. A
    #: repeat analysis after a fix must run by THE SAME measure; with only
    #: a signature, there is nothing to reproduce the measure from.
    tolerance_policy: dict = field(default_factory=dict, repr=False)
    #: Whether the exact phase was asked for. The same rationale: a repeat
    #: must be the same one.
    exact: bool = False
    units: str = UNITS

    # ── the acceptance instrument's names
    @property
    def hull_sources(self) -> dict:
        return self.hull_source

    @property
    def policy_digest(self) -> str:
        return self.tolerance_policy_digest

    def to_dict(self) -> dict:
        return {"revision": self.revision, "units": self.units,
                "program_digest": self.program_digest,
                "tolerance_policy_digest": self.tolerance_policy_digest,
                "policy_digest": self.tolerance_policy_digest,
                "bodies_declared": self.bodies_declared,
                "body_ids": sorted(self.body_ids),
                "body_keys": {k: list(v) for k, v in sorted(self.body_keys.items())},
                "bodies_with_hull": self.bodies_with_hull,
                "bodies_with_geometry": self.bodies_with_geometry,
                "bodies_in_pairs": dict(self.bodies_in_pairs),
                "pairs_possible": self.pairs_possible,
                "broad_phase": dict(self.broad_phase),
                "hull_source": dict(self.hull_source),
                "hull_sources": dict(self.hull_source),
                "source_of_truth": dict(self.source_of_truth),
                "pairs_compared": self.pairs_compared,
                "search_complete": self.search_complete,
                "analysis_limits": list(self.analysis_limits),
                "not_evaluated": dict(self.not_evaluated),
                "body_geometry": {oid: dict(row) for oid, row in sorted(self.body_geometry.items())},
                "findings": [f.to_dict() for f in self.findings]}


def _open_store(store):
    """A store as an object OR a path: the plan and the instrument named
    this differently."""
    from kir.project_store import ProjectStore

    if type(store) is ProjectStore:
        return store
    if isinstance(store, (str,)) or hasattr(store, "__fspath__"):
        return ProjectStore.open(store)
    raise ProjectAnalysisError("expected a ProjectStore or a path to one")


def _brep_bbox(shape, frame) -> tuple[list, list]:
    """The body's bounding box IN PROJECT COORDINATES. The ONLY place the
    frame is applied.

    The bounding box is computed FROM THE VERTICES of the rotated box, not
    by rotating the box as a whole: for a rotated body, the axis-aligned
    bounding box is the bounding box of its eight corners, and taking
    "min/max after rotating min/max" would produce a different box. For
    rotations that are multiples of 90° the two methods agree; for 37° they
    do not, and that is exactly where the error would be silent.
    """
    # 🔴 A DOOR, NOT ONE'S OWN `from OCP...` (fix of 07.09.2026). There used
    # to be a fourth direct exit of the kernel to a foreign package here —
    # bypassing the version pin that `occt_geometry._kernel` checks exactly
    # once. The absence of OCP now arrives as
    # `GeometryRefusal("kernel_unavailable")`, i.e. BY NAME, and is picked
    # up into `limits` by the parsing above, rather than as a bare
    # `ImportError` from a foreign place.
    from kir.occt_geometry import _kernel

    k = _kernel()
    box = k.Bnd.Bnd_Box()
    k.BRepBndLib.BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        raise ProjectAnalysisError("body bounding box is empty")
    x0, y0, z0, x1, y1, z1 = box.Get()
    corners = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    moved = [[sum(frame[4 * r + i] * c[i] for i in range(3)) + frame[4 * r + 3]
              for r in range(3)] for c in corners]
    lo = [min(p[i] for p in moved) for i in range(3)]
    hi = [max(p[i] for p in moved) for i in range(3)]
    return lo, hi


def _relation(a_lo, a_hi, b_lo, b_hi, slack: float):
    """The relation between two bounding boxes: intersection / containment
    / clearance.

    The numbers here are COARSE by construction — these are bounding boxes,
    not bodies. Hence for an intersection `status` is `possible`, not
    `confirmed`: only the exact phase can confirm. Lying in the direction
    of confidence is the most expensive thing to do here.
    """
    gap = 0.0
    for i in range(3):
        if a_lo[i] - b_hi[i] > gap:
            gap = a_lo[i] - b_hi[i]
        if b_lo[i] - a_hi[i] > gap:
            gap = b_lo[i] - a_hi[i]
    if gap > slack:
        return "clear", "clearance", gap, None
    inside = all(b_lo[i] - slack <= a_lo[i] and a_hi[i] <= b_hi[i] + slack for i in range(3))
    other = all(a_lo[i] - slack <= b_lo[i] and b_hi[i] <= a_hi[i] + slack for i in range(3))
    if inside or other:
        depth = min(min(a_hi[i] - b_lo[i], b_hi[i] - a_lo[i]) for i in range(3))
        return "contained", "containment", 0.0, depth
    depth = min(min(a_hi[i], b_hi[i]) - max(a_lo[i], b_lo[i]) for i in range(3))
    return "intersect", "overlap", 0.0, depth


def _settings(tolerance_policy, policy) -> dict:
    if tolerance_policy is not None and policy is not None and tolerance_policy != policy:
        raise ProjectAnalysisError("tolerance_policy and policy disagree; name one")
    chosen = tolerance_policy if tolerance_policy is not None else policy
    settings = dict(DEFAULT_TOLERANCE_POLICY)
    if chosen is not None:
        if not isinstance(chosen, dict):
            raise ProjectAnalysisError("tolerance policy must be an object")
        settings.update(chosen)
    return settings


def analyze_project(store, revision_id=None, *, exact: bool = False,
                    tolerance_policy=None, policy=None) -> ProjectClashReport:
    """A saved project -> a report on the clashes of its BODIES.

    `store` — a `ProjectStore` or a path to one (both contracts are
    accepted).
    `policy` — a second name for `tolerance_policy`, for the same reason.
    `exact=True` calls `kir.clash.exact.verify_pair` over an explicit list
    of pairs; while the module does not exist, the limitation is NAMED in
    `analysis_limits`, not silenced.
    """
    opened = _open_store(store)
    revision = opened.head()
    if revision_id is not None:
        found = [r for r in opened.history() if r.revision_id == revision_id]
        if not found:
            raise ProjectAnalysisError(f"revision is not in this stored history: {revision_id}")
        revision = found[0]
    # 🔴 BODIES ARE READ IN ONE TRANSACTION, NOT ONE PER BODY (07.09.2026).
    # Measurement on 2000 bodies: 2000 × `get_asset` = 14.07 s of
    # transaction overhead versus 0.22 s for a single batch. The check on
    # each body is the same one — `get_assets` calls the same
    # `_read_asset` and cross-checks the BYTES the same way; below,
    # `lookup` returns what was read, and anything not found in the set (a
    # new bundle not yet in the store) is asked for one at a time, as
    # before.
    batch = getattr(opened, "get_assets", None)
    loaded = {}
    if callable(batch):
        wanted = [output.geometry.bundle_sha256
                  for _instance, output, _oid in revision.geometry_references()]
        if wanted:
            loaded = batch(wanted)

    def lookup(digest):
        found = loaded.get(digest)
        return found if found is not None else opened.get_asset(digest)

    return analyze_revision(revision, lookup, exact=exact,
                            tolerance_policy=tolerance_policy, policy=policy)


def reanalyze_after_fix(store, revision_id=None, *, exact: bool = False,
                        tolerance_policy=None, policy=None) -> ProjectClashReport:
    """A repeat analysis AFTER a fix — the same body as `analyze_project`.

    🔴 THE NAME WAS INTRODUCED NOT FOR THE SAKE OF A SECOND CODE PATH, BUT
    FOR THE SAKE OF A SECOND QUESTION. "The pair disappeared" and "things
    got no worse" are different assertions, and before 07.09.2026 the
    second was not asked at all: `apply_fix` was printing success after
    lifting a passage into a NEW body overhead (measurement
    `impl3/red-geometry.json`: the podium×passage pair disappeared, the
    passage×canopy pair appeared, and there was no refusal). The comparison
    is done by `kir.project_fix.new_conflicts(before, after)`; here there is
    only a repeat measurement BY THE SAME MEASURE, because a measure taken
    differently would be comparing different things.
    """
    return analyze_project(store, revision_id, exact=exact,
                           tolerance_policy=tolerance_policy, policy=policy)


def _check_snapshot(materialized, revision, shapes) -> None:
    """An accepted snapshot must be a snapshot of THIS revision FROM THESE
    VERY bytes.

    What is checked is exactly what would differ if the snapshot were a
    foreign one: kind, revision, completeness (not a subset), and body
    digests for each address — on the left those declared by the revision,
    on the right those the snapshot itself carries in its `sources` rows,
    and third, the digests of the BUNDLE read by this same call.
    """
    from kir.geometry_materialization import GeometryMaterialization

    if not isinstance(materialized, GeometryMaterialization):
        raise ProjectAnalysisError("materialized snapshot must be a GeometryMaterialization")
    if materialized.selection is not None:
        raise ProjectAnalysisError("materialized snapshot describes a selection, not the whole project")
    if (materialized.project.project_id != revision.project_id
            or materialized.project.revision_id != revision.revision_id):
        raise ProjectAnalysisError(
            "materialized snapshot belongs to another project revision: "
            f"{materialized.project.revision_id} != {revision.revision_id}")
    rows = {row["op_id"]: row for row in materialized.sources}
    declared = {oid: output.geometry for _instance, output, oid in revision.addressed_outputs()
                if output.geometry is not None}
    if set(rows) != set(declared):
        raise ProjectAnalysisError("materialized snapshot covers other body-owned outputs")
    for oid, reference in declared.items():
        row = rows[oid]
        if (row.get("source_bundle_sha256") != reference.bundle_sha256
                or row.get("source_body_sha256") != reference.body_sha256):
            raise ProjectAnalysisError(f"{oid}: materialized snapshot cites another body")
        bundle = shapes.get(oid)
        if bundle is not None and (bundle.digest != reference.bundle_sha256
                                   or bundle.body_digest != reference.body_sha256):
            raise ProjectAnalysisError(f"{oid}: read body differs from the snapshot's body")


def analyze_revision(revision, get_asset, *, exact: bool = False,
                     tolerance_policy=None, policy=None,
                     materialized=None) -> ProjectClashReport:
    """A revision (ANY, including one not yet recorded) -> a clash report.

    🔴 WHY THIS IS SEPARATED FROM THE STORE. The check that "the fix created
    no new conflicts" must happen BEFORE the write: a refusal after
    `accept_proposal` would leave in the history a revision that had itself
    been declared unfit, and a "rollback" would have to be staged as yet
    another commit. `revision` here is `proposal.change.candidate`, and
    `get_asset(sha)` is able to return a new bundle too, one not yet in the
    store.

    🔴 `materialized` IS A READY SNAPSHOT OF THE SAME REVISION, NOT A PROMISE
    (08.09.2026, measurement S). The viewer builds a materialization to show
    the scene, and until today the analysis was building it a SECOND time
    from the same bytes: at N=2000 a cold materialization costs 29.3 s, and
    it was being paid for twice. An accepted snapshot is CROSS-CHECKED, not
    taken on faith: identity of the revision (the `revision_id` itself is a
    sha over the payload), absence of subsetting (a snapshot of PART of the
    project cannot serve as the analysis of the whole), and BODY DIGESTS
    for EVERY address — the same ones the revision declared and the ones
    the bundle read carries. If even one diverges — a named refusal, not a
    silent rebuild: a silent rebuild would bring back the cost the
    measurement has just removed, and would hide the discrepancy.
    """
    from kir.geometry_materialization import materialize_project
    from kir import clash_bundle as CB
    from kir.clash import hulls as H

    settings = _settings(tolerance_policy, policy)
    slack = float(settings.get("slack_mm") or 0.0)

    limits: list[str] = []
    body_outputs = {oid: (instance, output)
                    for instance, output, oid in revision.addressed_outputs()
                    if output.geometry is not None}
    bundles, shapes, hull_source, source_of_truth = {}, {}, {}, {}
    for oid, (_instance, output) in body_outputs.items():
        bundle = get_asset(output.geometry.bundle_sha256)
        bundles[bundle.digest] = bundle
        shapes[oid] = bundle

    if materialized is None:
        materialized = materialize_project(revision, bundles, bulk=True)
    else:
        _check_snapshot(materialized, revision, shapes)
    program = materialized.to_program()
    program_digest = _digest(program)
    stale = {row["op_id"]: row for row in materialized.sources}

    # ── BODY BOUNDING BOX: BRep + frame. The preview is NEVER taken if a
    # BRep exists.
    brep_boxes, bodies, body_frames = {}, {}, {}
    for oid, bundle in shapes.items():
        row = stale.get(oid, {})
        frame = row.get("frame") or bundle.to_dict()["manifest"]["frame"]
        body_frames[oid] = tuple(float(v) for v in frame)
        try:
            shape = bundle.read_body()
            brep_boxes[oid] = _brep_bbox(shape, frame)
            bodies[oid] = (shape, tuple(frame))
            hull_source[oid] = "brep"
            source_of_truth[oid] = "brep"
        except Exception as exc:  # noqa: BLE001 — a kernel refusal is not silence
            hull_source[oid] = f"none:brep_unreadable:{type(exc).__name__}"
            source_of_truth[oid] = "none"
            limits.append(f"{oid}: BRep не прочитан ({type(exc).__name__})")
            if row.get("stored_preview_bytes_equal") is False:
                limits.append(f"{oid}: превью разошлось с BRep и НЕ взято взамен")

    geometry = CB.bundle_elements([program])
    records, by_output, not_evaluated_hull, with_hull = [], {}, {}, set()
    for element in geometry.elements:
        oid = str(element.get("element_id") or "")
        short = oid.split("/", 1)[1] if "/" in oid else oid
        if short in brep_boxes:
            lo, hi = brep_boxes[short]
            element = dict(element, bbox_min_mm=lo, bbox_max_mm=hi)
        record, refusal = H.build_hull(element, profile=geometry.profiles.get(element.get("element_id")))
        reason = getattr(refusal, "reason", "hull_refused")
        if record is None:
            # 🔴 `hull_source` IS ABOUT THE PROJECT'S BODIES, and only about
            # them. An element that has no body in the store at all (a
            # wall, a slab, a level) goes into `not_evaluated` with its own
            # reason: mixing them would make the report declare "the body
            # has no hull" in a case where no body was even declared —
            # i.e. it would inflate the denominator with exactly what the
            # clash census distinguishes these two cases for.
            if short in body_outputs and short not in hull_source:
                hull_source[short] = f"none:{reason}"
                source_of_truth[short] = "none"
            elif short not in body_outputs:
                not_evaluated_hull[f"hull_refused:{reason}"] = (
                    not_evaluated_hull.get(f"hull_refused:{reason}", 0) + 1)
            continue
        if short in body_outputs and short not in hull_source:
            hull_source[short] = "bbox"
            source_of_truth[short] = "hull"
        if short in body_outputs:
            with_hull.add(short)
        records.append(record)
        by_output[id(record)] = short

    not_evaluated = dict(geometry.no_geometry)
    not_evaluated.update(not_evaluated_hull)
    for name, count in geometry.no_body.items():
        not_evaluated[f"op_without_body:{name}"] = count

    pairs_compared, findings = 0, []
    in_pairs: dict[str, int] = {}
    # The bounding box is taken FROM THE HULL ITSELF by one law:
    # `Hull.bounds()` exists for all four kinds (`Aabb`, `Prism`,
    # `PrismSet`, `Capsule`), and a second way of computing the bounding box
    # is not introduced here.
    extents, chosen = {}, {}
    for record in records:
        name = by_output[id(record)]
        lo, hi = record.hull.bounds()
        extents[name] = ([float(v) for v in lo], [float(v) for v in hi])
        chosen[name] = record
    hull_bounds = dict(extents)

    names = sorted(k for k, v in extents.items() if v is not None)
    pairs_possible = len(names) * (len(names) - 1) // 2
    requirement = float(settings.get("clearance_mm") or 0.0)
    # 🔴 THE BROAD PHASE MUST KNOW ABOUT THE CLEARANCE REQUIREMENT, OR IT
    # WILL EAT IT. The index selects pairs whose bounding boxes converge
    # closer than `broad`; take only `slack_mm` here, and a pair separated
    # by 10 mm under a requirement of 50 will NOT MAKE IT into the
    # candidates — the clearance violation would disappear silently, purely
    # from the acceleration. Hence `broad = max(slack, requirement)`: the
    # candidate set remains a SUPERSET of the findings by construction, not
    # by luck.
    broad = max(slack, requirement)
    indexed = [chosen[name] for name in names]
    broad_phase = {"kind": "none", "slack_mm": broad}
    if len(names) >= 2:
        from kir.clash.spatial_index import SpatialIndex

        index = SpatialIndex(indexed, slack=broad)
        broad_phase = {"kind": "kir.clash.spatial_index.SpatialIndex",
                       "slack_mm": broad, **index.stats}
        candidates = index.iter_candidate_pairs(slack=broad)
    else:
        candidates = iter(())
    for i, j in candidates:
        pairs_compared += 1
        a, b = names[i], names[j]
        if a > b:
            a, b = b, a
        (a_lo, a_hi), (b_lo, b_hi) = extents[a], extents[b]
        relation, kind, gap, depth = _relation(a_lo, a_hi, b_lo, b_hi, slack)
        if relation == "clear" and gap > requirement:
            continue
        in_pairs[a] = in_pairs.get(a, 0) + 1
        in_pairs[b] = in_pairs.get(b, 0) + 1
        findings.append(Finding(
            finding_id=_digest([a, b, relation])[:16], a_output_id=a, b_output_id=b,
            status="possible", relation=relation, kind=kind,
            evidence="axis_aligned_bbox_of_" + hull_source.get(a, "?") + "+" + hull_source.get(b, "?"),
            depth_mm=depth, gap_mm=gap if relation == "clear" else None,
            overlap_volume_mm3=None, surface_intersections=None, exact_source=None))
    # The order of findings is taken from the ADDRESS, not from the index
    # traversal: the traversal runs over the records' `source_id`, and a
    # report whose order depends on the accelerator's internal law would
    # give us nothing to compare between revisions with.
    findings.sort(key=lambda f: (f.a_output_id, f.b_output_id, f.relation))
    if pairs_compared < pairs_possible:
        # 🔴 A SCREENED-OUT PAIR IS NOT A CHECKED PAIR, AND THIS IS STATED.
        # On 07.09.2026 the acceptor read the silence as "`clear` pairs are
        # not compared at all": on a scene of two bodies set apart, with NO
        # clearance requirement, there was not a single finding, and the
        # exact phase said "there is no pair with two bodies". Both lines
        # are true, and both are about DIFFERENT subjects. Here it is named
        # exactly WHAT was not compared, and against which threshold.
        limits.append(
            f"широкая фаза: сравнено {pairs_compared} пар из {pairs_possible} "
            f"возможных; пара, чьи габариты разведены дальше {broad:.3f} мм, "
            f"кандидатом не считается и `clear` о ней не печатается"
            + (" (требование зазора не задано, поэтому порог — только slack)"
               if requirement <= 0.0 else ""))

    # 🔴 A BRep THAT WAS READ IS NOT YET A HULL. A body whose kind the clash
    # census does not know does not reach `build_hull` at all, and counting
    # it as "with a hull" would mean measuring OUR OWN reading instead of
    # ITS participation — exactly the denominator substitution this report
    # was introduced against. Measurement before stage A: 5 read, 0 with a
    # hull.
    for oid in body_outputs:
        if oid not in with_hull:
            was = hull_source.get(oid, "none:unknown")
            hull_source[oid] = ("none:not_in_census" if was in ("brep", "preview", "bbox")
                                else was)
            source_of_truth[oid] = "none"
            limits.append(f"{oid}: тело прочитано, но в перепись клеша не вошло "
                          f"(род не знает `clash.hulls.KIND_TABLE`)")
    coarse = sum(1 for oid in body_outputs if hull_source.get(oid) in ("brep", "preview", "bbox"))
    if coarse:
        # COARSENESS IS NAMED BY A NUMBER. A hull is an axis-aligned
        # bounding box, and for a body with a void (a podium with an
        # atrium) it does NOT KNOW about the void: an object inside the
        # atrium will honestly land in a "contained" pair, even though
        # there are 1085.786 mm between them. Reading this as a clash is a
        # READER'S mistake exactly for as long as the limitation is not
        # named; here it is named.
        limits.append(f"coarse hull: axis-aligned bounding box for {coarse} bodies; "
                      f"voids and concavities are NOT represented")
    if exact:
        findings, extra = _verify_exact(findings, bodies, settings)
        limits.extend(extra)
    else:
        limits.append("exact narrow phase not requested (exact=False)")
        # 🔴 A REQUIREMENT IS JUDGED ALWAYS, NOT BY A FLAG (review6, B-1,
        # 07.09.2026). `clearance_violated` was being born in EXACTLY one
        # place — `_verify_exact` — which the default path does not enter.
        # An attack measurement: the same scene, a clearance of 10 under a
        # requirement of 50, `exact=False` -> `status "possible"`, the three
        # fields ARE ABSENT, and `propose_fix` answers "nothing to fix: the
        # pair is clear" — verbatim the owner's own finding that had been
        # declared closed. Worse: by this same module's own contract, the
        # absence of the fields reads as "there was no requirement", when
        # one had in fact been declared. The flag decides HOW EXACTLY we
        # answer, and has no right to decide WHETHER we ask at all.
        findings, extra = _judge_clearance(findings, bodies, settings)
        limits.extend(extra)

    return ProjectClashReport(
        revision=revision.revision_id, program_digest=program_digest,
        tolerance_policy_digest=_digest(settings),
        bodies_declared=len(body_outputs), body_ids=frozenset(body_outputs),
        body_keys={oid: (inst.key, out.key)
                   for oid, (inst, out) in body_outputs.items()},
        bodies_with_hull=len(with_hull),
        bodies_in_pairs=in_pairs, hull_source=hull_source, source_of_truth=source_of_truth,
        # 🔴 SEARCH COMPLETENESS IS NOT THE SAME AS HULL ACCURACY. A search
        # is complete when EVERY declared body has a hull and not a single
        # pair was skipped due to budget or the absence of a body. Coarse
        # hulls (`coarse hull`) do not negate completeness: they answer a
        # different question — "how accurately", not "was everything
        # looked at". Merging the two would mean calling a search
        # incomplete where it is complete, and vice versa.
        pairs_compared=pairs_compared, hull_bounds=hull_bounds,
        search_complete=(len(with_hull) == len(body_outputs)
                         and not any(mark in limit for limit in limits for mark in
                                     ("budget", "бюджет", "not available", "без тела",
                                      "не вошло", "отказала", "failed"))),
        analysis_limits=limits, findings=findings, not_evaluated=not_evaluated,
        bodies=bodies, body_frames=body_frames,
        # The identity of the geometry that was read comes from the
        # materialization rows IN FULL, including the body's modeling
        # tolerance (not the clash-search tolerance).
        body_geometry={oid: {"bundle_sha256": row["source_bundle_sha256"],
                             "body_sha256": row["source_body_sha256"],
                             "frame": list(row["frame"]),
                             "modeling_tolerance_mm": row.get("modeling_tolerance_mm")}
                       for oid, row in stale.items() if oid in body_outputs},
        # 🔴 A PARTICIPANT IS ONE THAT ENTERED THE SEARCH WITH A HULL. An
        # output without geometry (a large-scale fixture's wall: no
        # contour, no section, no bounding box) counts as neither a body
        # nor a participant — measurement `impl3`: 10 000 such outputs give
        # `bodies_with_geometry` of 5 and 10 pairs.
        bodies_with_geometry=len(names), pairs_possible=pairs_possible,
        broad_phase=broad_phase, tolerance_policy=dict(settings), exact=bool(exact))


def _judge_clearance(findings, bodies, settings):
    """Judge a DECLARED clearance requirement on the path WITHOUT
    `exact=True`.

    🔴 WHAT IS JUDGED HERE, AND WHY EXACTLY THIS MUCH. The candidate is
    EVERY finding, not only the coarsely-"clear" ones, and this is not
    wastefulness but a consequence of coarseness: bounding boxes lie
    outside the bodies, so a coarsely-INTERSECTING pair may well turn out
    to be, in fact, separated — and separated INSUFFICIENTLY. The very
    first attempt to judge only the coarsely-"clear" ones showed exactly
    this: on the podium scene the pair "object in the atrium × podium" is
    coarsely `contained` (the hull does not know about the void), while
    exactly it is `clear` with a clearance of 1085.786 mm, i.e. a violation
    of a 2000 mm requirement that the coarse selection would not have seen
    at all.
    The denominator is nonetheless small by construction: only pairs with a
    coarse clearance no greater than the requirement land among the
    findings (the rest are screened out in the pair loop, and the coarse
    clearance is a lower bound on the real one, so the screening is
    provable).

    The cost is named honestly: for a declared requirement, the default
    path does the same work as `exact=True`, on this small set. The default
    for `clearance_mm` is ZERO, so the truly default path does not become
    more expensive by a gram.

    What the exact phase could not do (no body, no OCP, a kernel refusal)
    is not silenced and does not pass itself off as verified:
    `clearance_unverified` with the requirement, with an UPPER bound on the
    deficit (computed from the coarse clearance, i.e. the real deficit is
    no greater), and with a line in `analysis_limits`.
    """
    requirement = float(settings.get("clearance_mm") or 0.0)
    if requirement <= 0.0 or not findings:
        return findings, []
    candidates = list(findings)
    judged, limits = _verify_exact(candidates, bodies, settings)
    by_id = {f.finding_id: f for f in judged}
    out, unverified = [], []
    for finding in findings:
        item = by_id.get(finding.finding_id, finding)
        if item.relation == "clear" and item.status not in (
                "clearance_violated", "clearance_unverified", "refuted"):
            gap = item.gap_mm
            item = replace(
                item, status="clearance_unverified",
                required_clearance_mm=requirement,
                deficit_mm=None if gap is None else round(requirement - gap, 6),
                clearance_source=CLEARANCE_SOURCE)
            unverified.append(item.finding_id)
        out.append(item)
    limits.append(
        f"требование зазора {requirement:.3f} мм судится и без `exact=True`: "
        f"кандидатов {len(candidates)} из {len(findings)} находок")
    if unverified:
        limits.append(
            f"требование заявлено и НЕ проверено у {len(unverified)} пар "
            f"({', '.join(unverified[:5])}): точная фаза их не судила, дефицит "
            f"посчитан по ГРУБОМУ зазору и является верхней границей")
    return out, limits


def _verify_exact(findings, bodies, settings):
    """The seam to the neighbor's exact phase (`geo-loop/CONTRACT-AB.md`).

    🔴 WHAT THIS FUNCTION JUDGES, AND WHAT IT DOES NOT JUDGE (review6, N-1:
    the docstring had been lost — the statement `requirement = …` stood
    BEFORE the literal, and it stopped being a docstring; `__doc__` was
    `None`).

    JUDGES: the pair's relation (intersection / containment / clearance),
    the volume of the shared body, the depth, and the clearance — from the
    REAL bodies, not from bounding boxes; and, if a clearance requirement
    is declared, distinguishes "the bodies do not intersect" from "the
    clearance is satisfied", raising `clearance_violated` with a deficit.

    DOES NOT JUDGE: pairs where at least one side has no body in the store
    (they remain coarse and are NAMED in `analysis_limits`); pairs beyond
    the budget (`exact_pair_budget`, `exact_budget_ms`) — the remainder is
    printed as a number; nothing about BIM meaning, and not a single live
    model. An OCCT kernel refusal is not swallowed: the pair remains
    coarse, and the reason travels out as a string.

    Calls `kir.clash.exact.verify_pairs` — over an EXPLICIT list of pairs
    for which BOTH sides are present in `bodies` (i.e. both have
    `hull_source == "brep"`). IT applies the frame: bodies travel local
    together with the frame, and applying it twice would mean silently
    putting the body in the wrong place.

    Everything the exact phase did not touch remains a COARSE finding and
    is NAMED in `analysis_limits` — not a single pair disappears because it
    was not checked.
    """
    requirement = float(settings.get("clearance_mm") or 0.0)
    try:
        from kir.clash import exact as _exact
    except Exception:  # noqa: BLE001 — the module does not exist yet: this is a limitation, not a
# failure
        return findings, ["exact narrow phase not available"]
    verify_pairs = getattr(_exact, "verify_pairs", None)
    if not callable(verify_pairs):
        return findings, ["exact narrow phase not available"]

    wanted = [(f.a_output_id, f.b_output_id) for f in findings
              if f.a_output_id in bodies and f.b_output_id in bodies]
    skipped = [f for f in findings
               if f.a_output_id not in bodies or f.b_output_id not in bodies]
    limits = [f"{f.finding_id}: точная фаза без тела у одной стороны" for f in skipped]
    if not wanted:
        return findings, limits + ["exact narrow phase had no pair with two bodies"]
    budget = settings.get("exact_pair_budget")
    try:
        verdicts, extra = verify_pairs(bodies, wanted,
                                       max_pairs=None if budget is None else int(budget),
                                       budget_ms=settings.get("exact_budget_ms"))
    except Exception as exc:  # noqa: BLE001 — a kernel refusal is named, not silenced
        return findings, limits + [f"exact narrow phase failed: {type(exc).__name__}: {exc}"]
    limits.extend(extra or [])

    out = []
    for finding in findings:
        verdict = verdicts.get((finding.a_output_id, finding.b_output_id))
        if verdict is None:
            out.append(finding)
            continue
        refusal = getattr(verdict, "refusal", None)
        if refusal:
            out.append(finding)
            limits.append(f"{finding.finding_id}: точная фаза отказала — {refusal}")
            continue
        relation = getattr(verdict, "relation", None) or finding.relation
        gap = getattr(verdict, "gap_mm", None)
        # Common may establish non-intersection even when distance reading
        # fails. Neither a missing nor an invalid distance proves a clearance.
        try:
            measured_gap = type(gap) in (int, float) and math.isfinite(gap) and gap >= 0
        except OverflowError:
            measured_gap = False
        if not measured_gap:
            gap = None
        status = "refuted" if relation == "clear" else "confirmed"
        required = deficit = source = None
        # 🔴 CLEARANCE IS JUDGED BY THE REQUIREMENT, NOT BY THE FACT OF
        # SEPARATION. `clear` in the exact phase's dictionary means "the
        # bodies are provably not intersecting". It does NOT mean "the
        # clearance is satisfied", and substituting one for the other is
        # exactly the falsehood the owner found: 10 mm under a requirement
        # of 50 was being printed as `refuted`, i.e. as a resolved finding.
        if relation == "clear" and requirement > 0.0:
            required, source = requirement, CLEARANCE_SOURCE
            if gap is None:
                status = "clearance_unverified"
                limits.append(
                    f"{finding.finding_id}: clearance distance not available: "
                    f"тела не пересекаются, но расстояние не измерено; "
                    f"требование зазора {requirement:.3f} мм НЕ проверено")
            elif gap < requirement:
                status, deficit = "clearance_violated", round(requirement - gap, 6)
        out.append(Finding(
            finding_id=finding.finding_id, a_output_id=finding.a_output_id,
            b_output_id=finding.b_output_id,
            status=status,
            relation=relation,
            kind={"clear": "clearance", "contained": "containment"}.get(relation, "overlap"),
            evidence=getattr(verdict, "basis", "exact"),
            depth_mm=getattr(verdict, "depth_mm", None),
            gap_mm=gap,
            overlap_volume_mm3=getattr(verdict, "overlap_volume_mm3", None),
            surface_intersections=getattr(verdict, "surface_intersections", None),
            exact_source="kir.clash.exact.verify_pairs",
            required_clearance_mm=required, deficit_mm=deficit, clearance_source=source))
    if requirement <= 0.0 and any(f.relation == "clear" for f in out):
        # Silence here would read as "the clearance is satisfied". There is
        # no requirement — meaning `clear` answers only the question of
        # INTERSECTION.
        limits.append(NO_CLEARANCE_REQUIREMENT)
    return out, limits


__all__ = ["analyze_project", "analyze_revision", "reanalyze_after_fix",
           "ProjectClashReport", "Finding",
           "ProjectAnalysisError", "DEFAULT_TOLERANCE_POLICY", "UNITS",
           "CLEARANCE_SOURCE", "NO_CLEARANCE_REQUIREMENT"]
