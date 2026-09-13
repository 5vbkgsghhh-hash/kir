"""A PAIR JUDGEMENT — what the designer will accept, instead of a list of
pairs.

WHAT THIS FIXES (measured 09.08.2026, `snowdon_plumb_v5`, 122 bodies). The
bundle's search domain is `all_physical_diagnostic`, that is, ALL physical
pairs, and intra-partition adjacencies within it are deliberately not
filtered out. On the real building this produced 99 findings, of which
**66 were at the top severity stage**, and all 66 were "floor~floor" pairs
on ONE level. A report two-thirds of which the designer discards is worse
than none: what is discarded together with the noise carries away the
genuine finding too.

Analysis of those 66 showed the issue is NEITHER the search domain NOR the
threshold:

  * a prism's footprint is the CONVEX HULL of the declared outline, and
    holes in it are filled in (`hulls.build_hull`, its own comment). Slabs
    that TILE a floor intersect in their convex hulls but not in their
    declared outlines. Measured: **62 pairs out of 76** "floor~floor"
    pairs have non-intersecting DECLARED outlines, and 61 of them have at
    least one non-convex footprint — only these 61 are explained by the
    rounding (the 62nd is convex on both sides, its hulls merely touch);
  * a slab's Z-span is rounded TWOFOLD by `clash_bundle._slab_geometry`
    itself, because the program does not say which direction from the
    elevation the body grows. For two slabs at the same elevation, this
    rounding manufactures a 2t overlap out of nothing: a legitimate
    reading of the same program exists under which the bodies do not
    meet at all.

Hence this module's law: **a finding must say whether it is proven, and
rounding that WE OURSELVES introduced is not proof.** No rule here
discards a pair silently: a removed pair stays in the report under the
name of the rule that removed it, and with the numbers by which that was
decided.

WHAT IS NOT HERE AND WILL NOT BE. A building code. A rule is written only
where the assertion is a fact about CONSTRUCTION that a designer would
confirm without checking the codes ("a pipe passing through a wall is a
sleeve, not an error"), or a fact about THE PROGRAM ITSELF ("the author
declared a host — an element inside the host is not a contradiction").
Where no such fact exists, the pair goes into the honest `unclassified`
bucket with a named reason. Refused rules are listed in `REFUSED_RULES` —
they are part of the contract exactly as much as the ones that are
written.

BOUNDARIES. Reading only. This module does NOT change or recompute the
geometry of `kir/clash/`: it reads an already-computed finding, the
bounding sizes of already-built hulls, and the outlines DECLARED by the
program. The only geometry here is a refutation by the plan outline, and
it works on the numbers of the program itself.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from kir.clash import detect as clash_detect

__all__ = (
    "HOST_STATES",
    "JUDGEMENT_SCHEMA",
    "KINDS",
    "ORIGINS",
    "REFUSED_RULES",
    "ROLE_BY_LABEL",
    "RULES",
    "RUNGS",
    "Judged",
    "Judgement",
    "discipline_of",
    "host_relation",
    "hosted_from_ops",
    "judge",
    "loops_overlap",
    "loop_is_convex",
    "origin_of",
    "role_of",
)

JUDGEMENT_SCHEMA = "kir-clash-judgement/1"


# ═════════════════════════════════════════════════════════════════════════
# 1. THE TWO AXES ALONG WHICH A PAIR IS DISTINGUISHABLE AT ALL, AND BOTH ARE
# SOMEONE ELSE'S DICTIONARIES
# ═════════════════════════════════════════════════════════════════════════

def discipline_of(category: str) -> str:
    """A project's discipline — from the ONLY dictionary the package has.

    `CategorySpec.discipline` in `decompile/extract.py`, the lexicon of
    values is `registry_base.DISCIPLINES`. There is no dictionary of
    disciplines of its own here, and there cannot be: a third source of
    truth about one concept was already written once
    (`fold._CATEGORY_DISCIPLINE`, killed 28.07) and drifted from the
    table on 25 categories out of 47 — the entire electrical discipline
    read as "we don't know what this is."

    `unknown` remains exactly for categories the extractor's table is
    silent about (measured 09.08: there are five — `OST_CLines`,
    `OST_DuctAccessory`, `OST_DuctCurvesInsulation`,
    `OST_FabricationPipeworkInsulation`, `OST_SketchLines`). Guessing the
    discipline from the category name is worse than emptiness: emptiness
    is visible, a guess is not.
    """
    try:
        from kir.decompile.extract import _SPEC_BY_NAME
    except Exception:  # noqa: BLE001 — no table: the discipline is unknown, and that is stated
        return "unknown"
    spec = _SPEC_BY_NAME.get(category)
    return "unknown" if spec is None else spec.discipline


#: The ROLE of an element in construction — an axis along which
#: construction behaves differently, and it is NOT the same as
#: discipline: a wall and a floor slab are both "architectural," but one
#: gets penetrated as routine while the other… also gets penetrated as
#: routine; yet a column and a wall are one discipline (`architectural`
#: for `OST_Columns`) under opposite relationships to an opening. The
#: key is `label` from the closed table `hulls.KIND_TABLE`, so the
#: dictionary is closed together with it and held by a test.
#:
#: The values and WHAT EACH ONE ASSERTS ABOUT CONSTRUCTION:
#:
#:   envelope    — an enclosing or separating structure. An opening in it
#:                 for a utility run is a STANDARD DETAIL (a sleeve, a
#:                 casing), executed per working drawings without
#:                 recalculating the structure.
#:   bearing     — a load-bearing linear element. An opening in it
#:                 changes the section's load-bearing capacity and
#:                 requires calculation and approval by the structural
#:                 engineer; it is not a standard detail.
#:   run         — a STRAIGHT segment of a utility run: the body is
#:                 solid, nothing passes through it.
#:   run_part    — a fitting, valve, or insulation of the same run: the
#:                 same property, but it has no axis of its own (a
#:                 fitting is not a segment).
#:   equipment   — equipment and fixtures: the body is solid, installed
#:                 in place.
#:   opening     — an opening infill and a curtain wall: exists INSIDE
#:                 its host, and that is its mode of existing, not a
#:                 contradiction.
#:   circulation — circulation paths (a stair, a ramp, a guardrail).
#:   furnishing  — furniture and fittings: movable, not a structure.
#:   opaque      — a body exists, purpose is not expressed by the
#:                 program at all.
#:   not_a_body  — a datum or annotation: `KIND_TABLE` does not even
#:                 consider them eligible, they do not enter pairs.
ROLE_BY_LABEL: dict[str, str] = {
    # ── enclosing and separating
    "wall": "envelope", "floor": "envelope", "roof": "envelope",
    "ceiling": "envelope",
    # ── load-bearing linear
    "column": "bearing", "beam": "bearing", "foundation": "bearing",
    "truss": "bearing",
    # ── straight segments of runs
    "pipe": "run", "duct": "run", "tray": "run", "conduit": "run",
    # ── fittings, valves, and insulation of runs
    "pipe_fitting": "run_part", "duct_fitting": "run_part",
    "tray_fitting": "run_part", "conduit_fitting": "run_part",
    "pipe_accessory": "run_part", "duct_accessory": "run_part",
    "duct_terminal": "run_part", "sprinkler": "run_part",
    "pipe_insulation": "run_part", "duct_insulation": "run_part",
    "duct_lining": "run_part",
    # ── equipment and fixtures
    "equipment": "equipment", "electrical_equipment": "equipment",
    "electrical_fixture": "equipment", "lighting_device": "equipment",
    "lighting_fixture": "equipment", "fixture": "equipment",
    # ── opening infill and curtain wall
    "door": "opening", "window": "opening", "curtain_panel": "opening",
    "mullion": "opening", "curtain_system": "opening",
    # ── circulation paths
    "stairs": "circulation", "ramp": "circulation", "railing": "circulation",
    # ── furnishings
    "furniture": "furnishing", "casework": "furnishing",
    # ── a body exists, no purpose
    "generic": "opaque", "direct_shape": "opaque", "import_instance": "opaque",
    # Mass is eligible geometry, not evidence of an envelope/bearing purpose.
    "mass": "opaque",
    # ── not bodies at all (do not appear in pairs: KIND_TABLE does not admit them)
    "area": "not_a_body", "curtain_grid": "not_a_body",
    "dimension": "not_a_body", "grid": "not_a_body", "level": "not_a_body",
    "line": "not_a_body", "mep_space": "not_a_body", "raster": "not_a_body",
    "refplane": "not_a_body", "room": "not_a_body", "sketch": "not_a_body",
    # ── TWO LABELS WITHOUT A ROLE, FOUND BY THE CLOSEDNESS LAW ON 21.08.2026 ────
    # `role_of` answers an unfamiliar label with `unknown`, and that is
    # correct as a SAFEGUARD, but NOT as a working state: as long as a
    # label is not named here, every one of its bodies is judged by the
    # role "unclear," that is, it falls out of the adjacency rules the
    # table exists for.
    #
    # `telephone_device` (OST_TelephoneDevices) — a BODY (`eligible=True`),
    # so the role must be physical. A low-voltage device stands in the
    # same row as `lighting_device` and `electrical_fixture`, which
    # already have `equipment`, and behaves the same way: hangs on the
    # structure, does not form a run, is not an opening.
    "telephone_device": "equipment",
    # `opening` (OST_FloorOpening) — is NOT a body (`eligible=False`): an
    # opening in a slab is the ABSENCE of material, not material.
    # 🔴 The label coincides by name with the ROLE `opening` (a door, a
    # window, a curtain-wall panel), and these are different things: that
    # role is about an element that FILLS an opening. Assigning the label
    # to the same-named role would mean judging a hole by a door's rules
    # — a coincidence of name instead of a coincidence of subject.
    "opening": "not_a_body",
}

#: Roles that behave as a SOLID BODY of a utility run.
_RUN_ROLES = frozenset({"run", "run_part"})
#: Structural roles — what the building itself is assembled from.
_STRUCTURE_ROLES = frozenset({"envelope", "bearing"})


def role_of(label: str) -> str:
    """Role by the `hulls.KIND_TABLE` label. An unfamiliar label is
    `unknown`, not a silent assignment to whatever fits: a new label must
    be NOTICED."""
    return ROLE_BY_LABEL.get(label, "unknown")


# ═════════════════════════════════════════════════════════════════════════
# 2. ROUNDING THAT WE OURSELVES INTRODUCED
#
# A hull must CONTAIN the element — that is the law of `hulls.py`, and it
# is paid for with false positives. As long as the rounding is unnamed,
# every such false positive is indistinguishable from a genuine finding.
# Here it is named BY NAME, with the code address that introduced it, and
# with a number, if a number exists.
# ═════════════════════════════════════════════════════════════════════════

#: Rounding -> how it explains an overlap. The keys ride into the receipt.
SLACK_REASONS: dict[str, str] = {
    "plate_z_doubling": (
        "размах плиты по Z огрублён ВДВОЕ (`clash_bundle._slab_geometry`): "
        "программа объявляет отметку, но не сторону, в которую от неё "
        "нарастает тело"),
    "profile_convexified": (
        "подошва призмы — ВЫПУКЛАЯ оболочка объявленного контура, отверстия "
        "засыпаны (`hulls.build_hull`): замощающие этаж плиты в оболочках "
        "пересекаются, а в объявленных контурах — нет"),
}


# ── refutation by plan: works on the NUMBERS OF THE PROGRAM ITSELF ──────────

#: The degeneracy threshold for comparing outlines. This is NOT a
#: construction tolerance and not "a few millimeters": the outlines
#: arrive as the same numbers from the same program, so they must be
#: compared for exact coincidence, and the only imprecision is binary.
#: 1e-6 mm is 1 picometer; no real distance in a building ever falls
#: within it.
_DEGENERATE = 1e-6


def _cross(o: Sequence[float], a: Sequence[float], b: Sequence[float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def loop_is_convex(loop: Sequence[Sequence[float]]) -> bool:
    """Whether the DECLARED outline is convex. A convex outline equals
    its convex hull — meaning the rounding `profile_convexified` for it
    is ZERO, and referring to it is not allowed."""
    n = len(loop)
    if n < 3:
        return True
    sign = 0
    for i in range(n):
        c = _cross(loop[i], loop[(i + 1) % n], loop[(i + 2) % n])
        if abs(c) < _DEGENERATE:
            continue
        s = 1 if c > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def _on_segment(p: Sequence[float], a: Sequence[float],
                b: Sequence[float]) -> bool:
    """Whether a point lies ON a segment.

    Review #8 in `geom` had already caught this class of bug: "a SQUARED
    length cannot be compared against a length threshold." Here it was
    exactly the same — `_cross` has the dimension mm², while
    `_DEGENERATE` is given in mm, so the threshold DRIFTED WITH SCALE: on
    an edge 20,000 mm long, a point 1e-10 mm off the line produced a
    product of 2e-6 > 1e-6 and was declared OUTSIDE the segment.
    `_strictly_inside` then picked it up, and a touch was read as an
    overlap.

    Measured 10.08.2026, the `loops_overlap` gate against shapely on
    117,987 real outline pairs (7 buildings): 5 discrepancies, all
    touches declared as overlaps, the worst on a 108-vertex outline
    (`k2_ar_rd_v15`, 11840492) with an intersection area of 0.0. After
    switching to DISTANCE (the product divided by the edge length),
    discrepancies: 0.

    A degenerate edge (a == b) is compared as a point: there is nothing
    to divide by.
    """
    ex, ey = b[0] - a[0], b[1] - a[1]
    L = math.hypot(ex, ey)
    if L <= _DEGENERATE:
        return (abs(p[0] - a[0]) <= _DEGENERATE
                and abs(p[1] - a[1]) <= _DEGENERATE)
    if abs(_cross(a, b, p)) / L > _DEGENERATE:
        return False
    return (min(a[0], b[0]) - _DEGENERATE <= p[0] <= max(a[0], b[0]) + _DEGENERATE
            and min(a[1], b[1]) - _DEGENERATE <= p[1] <= max(a[1], b[1]) + _DEGENERATE)


def _properly_cross(p1, p2, p3, p4) -> bool:
    """The OWN intersection of segments: a shared endpoint and overlap do
    not count.

    That is exactly right: two tiling slabs share an EDGE, and declaring
    that an intersection would mean bringing back exactly the noise this
    module was written to remove."""
    d1, d2 = _cross(p3, p4, p1), _cross(p3, p4, p2)
    d3, d4 = _cross(p1, p2, p3), _cross(p1, p2, p4)
    return (((d1 > _DEGENERATE and d2 < -_DEGENERATE)
             or (d1 < -_DEGENERATE and d2 > _DEGENERATE))
            and ((d3 > _DEGENERATE and d4 < -_DEGENERATE)
                 or (d3 < -_DEGENERATE and d4 > _DEGENERATE)))


def _strictly_inside(p: Sequence[float],
                     loop: Sequence[Sequence[float]]) -> bool:
    n = len(loop)
    if any(_on_segment(p, loop[i], loop[(i + 1) % n]) for i in range(n)):
        return False
    inside = False
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x > p[0]:
                inside = not inside
    return inside


#: A ceiling on the product of vertex counts of a pair of outlines. The
#: check costs O(n·m); measured 09.08 on `snowdon_plumb_v5`: 111
#: outlines, up to 26 vertices, 76 pairs — 8 ms in total. The ceiling
#: does not exist for these numbers, but so that an outline of a
#: thousand vertices does not turn a CHEAP refutation into an expensive
#: one; beyond the ceiling the answer is `None` — "not checked," and
#: that differs from "do not intersect."
_MAX_LOOP_WORK = 250_000


def _ccw(loop):
    """Outline counterclockwise. Orientation is needed so that "a convex
    vertex" is a fact, not a consequence of traversal order."""
    n = len(loop)
    area2 = sum(loop[i][0] * loop[(i + 1) % n][1]
                - loop[(i + 1) % n][0] * loop[i][1] for i in range(n))
    return list(loop) if area2 >= 0 else list(reversed(loop))


def _point_in_triangle(p, a, b, c) -> bool:
    d1, d2, d3 = _cross(a, b, p), _cross(b, c, p), _cross(c, a, p)
    neg = d1 < -_DEGENERATE or d2 < -_DEGENERATE or d3 < -_DEGENERATE
    pos = d1 > _DEGENERATE or d2 > _DEGENERATE or d3 > _DEGENERATE
    return not (neg and pos)


def _interior_witness(loop):
    """A point STRICTLY inside a simple outline, or `None`.

    An "ear" is taken: a convex vertex whose triangle no other vertex
    falls into; the center of such a triangle lies inside the outline. A
    witness is needed because for two COINCIDING outlines, no boundary
    point can serve as a witness — the whole boundary of one lies on the
    boundary of the other.
    """
    pts = _ccw(loop)
    n = len(pts)
    if n < 3:
        return None
    for i in range(n):
        a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        if _cross(a, b, c) <= _DEGENERATE:
            continue
        blocked = False
        for k in range(n):
            q = pts[k]
            if q is a or q is b or q is c:
                continue
            if _point_in_triangle(q, a, b, c):
                blocked = True
                break
        if blocked:
            continue
        vertex_count = len((a, b, c))
        return ((a[0] + b[0] + c[0]) / vertex_count,
                (a[1] + b[1] + c[1]) / vertex_count)
    return None


def _sub_edge_midpoints(loop, other):
    """The midpoints of the pieces into which `other`'s boundary cuts
    `loop`'s edges.

    An edge that lies entirely INSIDE the second outline gives neither
    an own intersection of edges nor a strictly interior vertex — and
    before this fix it gave nothing at all. Its midpoint is exactly the
    missing witness.
    """
    n, m = len(loop), len(other)
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ts = [0.0, 1]
        for j in range(m):
            c, d = other[j], other[(j + 1) % m]
            den = dx * (d[1] - c[1]) - dy * (d[0] - c[0])
            if abs(den) <= _DEGENERATE:
                continue
            t = ((c[0] - a[0]) * (d[1] - c[1])
                 - (c[1] - a[1]) * (d[0] - c[0])) / den
            if 0.0 < t < 1:
                ts.append(t)
        ts.sort()
        for k in range(len(ts) - 1):
            t = (ts[k] + ts[k + 1]) / 2
            yield (a[0] + dx * t, a[1] + dy * t)


def loops_overlap(a: Sequence[Sequence[float]],
                  b: Sequence[Sequence[float]]) -> bool | None:
    """Whether the DECLARED outlines intersect as sets of points in plan.

    `None` — not checked (the outline is degenerate or the pair is too
    expensive). The tristate here is the same as in
    `detect.hulls_coincide`: "nothing to say" is not "do not intersect,"
    and the two must not be confused in either direction.

    A shared edge and a shared vertex do NOT count as an intersection:
    tiling is precisely shared edges.

    MEASURED 10.08.2026 — WHY THERE ARE FOUR WITNESSES, NOT TWO. The
    previous version looked only for OWN intersections of edges and
    STRICTLY interior vertices. This falls short exactly when one
    outline's boundary lies entirely on the other's boundary — and such
    pairs exist in the corpus:

      * `sob62_fas_r23_v19`, pairs 11127626~11204761 and
        11443571~11443706: the outlines COINCIDE vertex for vertex (a
        720x420 triangle), intersection area 302,400 mm², the answer was
        `False`;
      * the squares [0,10]² and [0,10]x[8,20] overlap in a 10x2 strip —
        the answer was `False`;
      * two IDENTICAL NON-CONVEX L-shaped outlines, intersection area 64
        — the answer was `False`.

    The third case is a defect, not an imprecision. `_slack_explains`
    refers to `profile_convexified` only when at least one outline is
    NON-CONVEX, and a false `False` there becomes a certificate that
    "the overlap was created by our own convexification" for a pair
    that overlaps BY ITS DECLARED OUTLINES. This is exactly the same
    disease as the vacuous `plate_z_doubling`: a refutation firing where
    it should not.

    Two witnesses were added, and both are mandatory:
      * the midpoint of an edge piece cut off by the second outline's
        boundary — catches a STRIP overlap;
      * the interior point of an "ear" — catches COINCIDING and nested
        outlines whose entire boundary is shared.

    Tiling still gives `False`: for a pair sharing only an edge, no
    piece midpoint and no ear falls inside the neighbor — this is
    verified by the same measurement.
    """
    na, nb = len(a), len(b)
    if na < 3 or nb < 3:
        return None
    if na * nb > _MAX_LOOP_WORK:
        return None
    for i in range(na):
        for j in range(nb):
            if _properly_cross(a[i], a[(i + 1) % na], b[j], b[(j + 1) % nb]):
                return True
    if any(_strictly_inside(p, b) for p in a):
        return True
    if any(_strictly_inside(p, a) for p in b):
        return True
    if any(_strictly_inside(p, b) for p in _sub_edge_midpoints(a, b)):
        return True
    if any(_strictly_inside(p, a) for p in _sub_edge_midpoints(b, a)):
        return True
    for loop, other in ((a, b), (b, a)):
        w = _interior_witness(loop)
        if w is not None and _strictly_inside(w, other):
            return True
    return False


# ═════════════════════════════════════════════════════════════════════════
# 3. STAGES: EACH ONE SAYS WHAT IS SAFE TO DO WITH IT
#
# A stage is not decoration on a finding, it is a CONTRACT about the
# permissible action. Before this wave, a suspicion based on a bounding
# box stood at the same stage as a proven overlap, and both read as
# "critical"; exactly out of this indistinguishability grew the defect
# fixed on 09.08 on `feat/kir-clash-duplicate`: the advice "delete one
# of them" was issued on the coincidence of TWO BOXES and erased a live
# element.
# ═════════════════════════════════════════════════════════════════════════

#: (key, name in the receipt, WHAT IS SAFE TO DO). Order — from strongest to weakest.
RUNGS: tuple[tuple[str, str, str], ...] = (
    ("fix", "ЧИНИТЬ",
     "правьте программу: сдвиньте операцию или измените размер. Геометрия "
     "сама по себе никогда не даёт права удалить BIM-элемент"),
    ("agree", "СОГЛАСОВАТЬ",
     "это узел, а не ошибка: объявите проём или гильзу и согласуйте со "
     "смежником. Двигать сеть вслепую — испортить рабочее решение"),
    ("look", "СМОТРЕТЬ",
     "откройте в Revit и посмотрите: хотя бы одна оболочка — габаритный бокс, "
     "тела он не описывает. Разрушающее указание по такой находке ЗАПРЕЩЕНО"),
    # "NOTHING TO JUDGE BY" stands ABOVE "for the record" on purpose: the
    # first is a hole in the DECLARATION that the author can close, the
    # second is how the building is assembled. The last stage is the one
    # where there is nothing to do, not the one that is unclear.
    ("nothing", "НЕЧЕМ СУДИТЬ",
     "дополните ЗАЯВЛЕНИЕ — назовите то, чего программа не сказала. "
     "Двигать элементы по такой строке нельзя: двигать, возможно, нечего"),
    ("note", "К СВЕДЕНИЮ",
     "делать нечего: так здание и собрано. Строка стоит здесь, чтобы "
     "«находок нет» не читалось как «не смотрели»"),
)

_RUNG_ORDER = {key: i for i, (key, _, _) in enumerate(RUNGS)}
_RUNG_NAME = {key: name for key, name, _ in RUNGS}
_RUNG_ACTION = {key: action for key, _, action in RUNGS}

#: The pair's kind — a closed list of classification outcomes.
KINDS: tuple[str, ...] = (
    "duplicate", "collision", "penetration", "adjacency",
    "unproven", "unclassified",
)


# ═════════════════════════════════════════════════════════════════════════
# 4. THE RULE TABLE. EACH ONE IS A FACT, AND EACH ONE IS NAMED
# ═════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Rule:
    """A rule: name, kind, justification. The justification rides into
    the receipt — a rule that cannot be contested by reading it is no
    better than a threshold pulled from the ceiling."""

    rule_id: str
    kind: str
    why_ru: str


RULES: tuple[Rule, ...] = (
    Rule("host_declared", "adjacency",
         "программа САМА объявила хозяина (`host`): заполнение проёма живёт "
         "ВНУТРИ несущей его конструкции — это способ его существования, а "
         "не спор. Строительного кодекса тут нет вовсе, это факт о заявлении"),
    Rule("duplicate", "duplicate",
         "детектор объявил род `coincident_duplicate`: два элемента стоят на "
         "одном месте. Это кандидат на проверку: геометрия не доказывает "
         "семантическую взаимозаменяемость и отсутствие зависимостей"),
    Rule("structure_contact", "adjacency",
         "плита опирается на стену и на колонну, стены смыкаются в углу, "
         "балка садится на колонну — КАСАНИЕ конструкций и есть способ, "
         "которым здание собрано"),
    Rule("hull_over_approximation", "unproven",
         "перекрытие целиком объясняется огрублением, которое внесли МЫ "
         "САМИ: существует законное прочтение той же программы, при котором "
         "тела не встречаются. Огрубление названо поимённо вместе с числами"),
    Rule("run_meets_run", "collision",
         "два тела трассы не могут занимать один объём: ни трубопровод, ни "
         "воздуховод, ни лоток не проходят сквозь другой. Верно и внутри "
         "одного раздела (два воздуховода в одном месте), и между разделами"),
    Rule("run_through_envelope", "penetration",
         "инженерная сеть ОБЯЗАНА переходить между помещениями и этажами; "
         "отверстие в стене или плите с гильзой — типовой узел рабочей "
         "документации, а не ошибка. Требует проёма, а не переноса сети"),
    Rule("run_through_bearing", "collision",
         "отверстие в колонне, балке, ферме или фундаменте меняет несущую "
         "способность сечения: это расчёт и согласование конструктора, а не "
         "типовой узел. Поэтому такая пара — столкновение, а не проникание"),
    Rule("run_meets_equipment", "collision",
         "трасса и оборудование делят объём: подключение идёт ЧЕРЕЗ патрубок "
         "оборудования, а не сквозь его корпус"),
    Rule("unclassified", "unclassified",
         "ни одно правило не применимо: ЧЕСТНАЯ корзина. Пара остаётся "
         "видимой с числами, но суждения о ней здесь нет"),
)

_RULE_BY_ID = {rule.rule_id: rule for rule in RULES}

#: THE RULES THAT ARE REFUSED HERE, AND WHY. The refusal is part of the
#: contract: without this list, "there is no rule" is indistinguishable
#: from "the rule was forgotten." Each line is a pair that, for this
#: reason, goes into `unclassified` with a named question.
REFUSED_RULES: dict[str, str] = {
    "structure_meets_structure_overlap": (
        "ВЗАИМНОЕ ПРОНИКАНИЕ ДВУХ КОНСТРУКЦИЙ. У монолита колонна, плита и "
        "стена льются вместе — их объёмы в модели пересекаются ПО "
        "ПОСТРОЕНИЮ, и это норма; у стального каркаса то же пересечение — "
        "конфликт изготовления. Различает их МАТЕРИАЛ, а материал программа "
        "не выражает: ни одна из 48 операций создания его не несёт. Правило, "
        "выбравшее одну из двух трактовок, было бы выдуманным кодексом"),
    "run_meets_run_clearance": (
        "НОРМИРУЕМЫЙ ЗАЗОР МЕЖДУ ТРАССАМИ. Касание двух трасс — не всегда "
        "норма: между ними бывает требуемый зазор на изоляцию и на монтаж. "
        "Величина зазора зависит от раздела, среды и изоляции; программа её "
        "не выражает, а взять число из головы значило бы обвинять или "
        "оправдывать по выдумке"),
    "run_along_the_wall": (
        "ВДОЛЬ ИЛИ СКВОЗЬ. Труба, лежащая ВНУТРИ стены по её длине, — "
        "столкновение, а проходящая СКВОЗЬ — гильза. По оболочкам это не "
        "различается: минимальный разводящий перенос в обоих случаях один и "
        "тот же (полутолщина стены плюс радиус). Поэтому `penetration` "
        "говорит именно «узел, а не ошибка» и НЕ утверждает, что трасса "
        "пересекает конструкцию поперёк; оговорка едет в самой находке"),
    "opening_body_is_a_void": (
        "ПРОЁМ КАК ОПРАВДАНИЕ. Объявленный `create_opening` мог бы снимать "
        "проникание сети сквозь конструкцию — но проём ТЕЛА НЕ СОЗДАЁТ "
        "(`clash_bundle.OP_NO_BODY`), в поиск он не попадает вовсе, и "
        "сопоставить его с находкой не по чему. Пока проём не станет "
        "вычитаемым объёмом, снимать по нему находку — врать"),
    "equipment_meets_structure": (
        "ОБОРУДОВАНИЕ У КОНСТРУКЦИИ. Щит на стене, светильник в потолке, "
        "прибор у плиты — врезка в конструкцию тут норма, но её глубина "
        "нормируется, а закладная деталь программой не выражена. Ни "
        "«столкновение», ни «примыкание» доказать нечем"),
}


# ═════════════════════════════════════════════════════════════════════════
# 5. JUDGEMENT
# ═════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Judged:
    """One pair that became a judgement."""

    finding_id: str
    a_id: str
    b_id: str
    kind: str
    rule_id: str
    rung: str
    #: Whether an overlap of BODIES, not of their outer hulls, is proven.
    #: `True` — the detector brought `verdict=confirmed` on exact
    #: geometry; `False` — it brought only `possible`, or our own
    #: rounding fully explains the overlap; `None` — the evidence is
    #: coarse, incomplete, or internally contradictory. `None` is NOT
    #: "no."
    proven: bool | None
    depth_mm: float
    #: THE DETECTOR'S RAW FACTS, riding alongside the judgement. The
    #: judgement is derived from them, and the reader must be able to
    #: verify it without requesting the report again: `relation` and
    #: `pair_kind` are what the geometry computed, while `kind` and
    #: `rung` are what the rule table decided.
    relation: str
    pair_kind: str
    hull_grade: str
    #: The geometry's raw verdict (`confirmed | possible`). Without it,
    #: `proven=False` cannot be distinguished from a refutation or a
    #: data hole.
    geometry_verdict: str
    #: Full detector proof chain.  A positive user-visible claim must remain
    #: auditable after judgement serialization, not only in the raw report.
    physical_overlap_proof: dict[str, Any]
    a_label: str
    b_label: str
    #: The roundings that explain this pair. Empty means none apply.
    slack: tuple[str, ...]
    text_ru: str
    next_move_ru: str
    #: THE HOST EDGE AS A TRISTATE (plus "not asked"). One of
    #: `HOST_STATES`. Rides into the receipt ALWAYS, not only when it
    #: removed a pair: "the host confirmed," "a DIFFERENT host was
    #: declared," and "no host was declared" are three different facts,
    #: and gluing them into silence means bringing back exactly the
    #: guess this edge was built to replace.
    host_state: str = "unknown"
    #: The address of the ACTUAL host — only when `contradicts`. This is
    #: exactly the news: "the door overlaps a wall it does not live in,
    #: it lives in this one instead."
    declared_host_id: str | None = None
    #: In whose words the edge was obtained (`program_host_ref` |
    #: `l0_host_id` | …).
    host_source: str | None = None
    #: WHO INTRODUCED THE PAIR — one of `ORIGINS`. `unknown` means "the
    #: turn's boundary was not named," and that is NOT "it stood there
    #: before."
    origin: str = "unknown"
    #: The rule's JUSTIFICATION — here, not in the finding's text. There
    #: is one justification per rule, and findings under it can number
    #: eighty: printing it on every line would drown both the findings
    #: and the completeness accounting in it. In the receipt it is
    #: printed ONCE (`render_bundle_clash`), and here it sits in full,
    #: so the rule can be contested without opening the source.
    why_ru: str = ""
    #: 🔴 WHAT THE HULL OF EACH SIDE WAS (F-026, 29.08.2026). `hull_grade`
    #: speaks of PRECISION, but not of PROVENANCE: `bbox` is a Revit
    #: bounding box, `prism`/`analytic_outer` is a built body. A
    #: `contact` relation between a pair of boxes and a pair of prisms
    #: are facts of different strength, and before this line the report
    #: did not distinguish them: there was NOTHING in the row to tell a
    #: box from a prism. A tuple, not one field: a pair can be mixed (a
    #: bounding box against a prism), and gluing two axes into one is
    #: exactly what `translation_unavailable_reason` in this same file
    #: exists to remove.
    hull_sources: tuple[str, str] = ("", "")
    #: WHOSE TURN THIS IS — the source of the number in `next_move_ru`,
    #: named, not implied. `detector` is the raw certified carry-over
    #: from `detect`; `minimal_exit` is the provably minimal separation
    #: from `clash.resolve`. The difference is measured
    #: (`resolve.py:32-38`, 600 findings on `sob62_r23_v5`): median
    #: 5.892x, p90 56.667x, maximum 112,066.5x. Where a pipe needs only
    #: eight millimeters sideways, the raw vector used to carry it tens
    #: of meters away — so the source must be visible to the reader.
    move_source: str = "detector"

    def as_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "a_element_id": self.a_id, "b_element_id": self.b_id,
            "kind": self.kind, "rule_id": self.rule_id,
            "rung": self.rung, "rung_name": _RUNG_NAME[self.rung],
            "action_ru": _RUNG_ACTION[self.rung],
            "proven": self.proven,
            # 🔴 THE NAME MUST TELL THE TRUTH (F-027, 29.08.2026). The
            # value is the depth of overlap of the OUTER HULLS (the
            # detector's `hull_overlap_depth_mm`), not of BODY
            # penetration: for a pair with `hull_source='bbox'` this is
            # the overlap of two bounding boxes, and with `proven=None`
            # it is confirmed by nothing. `detect` had ALREADY removed
            # exactly this lie (review #6/#14: the field
            # `physical_penetration_mm` renamed to
            # `hull_overlap_depth_mm`, guarded by
            # `test_06b_penetration_field_is_named_hull_overlap_depth`)
            # — and it came back through a NEIGHBORING layer the guard
            # cannot see.
            "hull_overlap_depth_mm": round(float(self.depth_mm), 1),
            #: 🔴 A STALE ALIAS, REMOVED BY THE OWNER, NOT BY A SMITH. It
            #: is kept exactly because the key is already published (the
            #: rule: keys never disappear from dictionaries). Readers in
            #: the tree — one test; in KUKAI production — zero; but
            #: "zero readers that I found" and "zero readers" are
            #: different facts, and the receipt travels out into the
            #: chat. The value is IDENTICAL to `hull_overlap_depth_mm`
            #: and is guarded by equality, otherwise the two keys would
            #: drift apart silently.
            "penetration_mm": round(float(self.depth_mm), 1),
            #: WHAT THIS NUMBER MEANS — RIGHT NEXT TO THE NUMBER, not in
            #: another key. `proven` is present in the row, but it is
            #: three-valued and answers the question "is the OVERLAP
            #: proven"; the reader of the number needs the answer to a
            #: different one — "can THIS NUMBER be read as
            #: penetration." Two questions, two fields.
            "depth_is_body_proven": self.proven is True,
            "hull_sources": list(self.hull_sources),
            "relation": self.relation, "pair_kind": self.pair_kind,
            "hull_grade": self.hull_grade,
            "geometry_verdict": self.geometry_verdict,
            "physical_overlap_proof": self.physical_overlap_proof,
            "a_label": self.a_label, "b_label": self.b_label,
            "slack": list(self.slack),
            "text": self.text_ru,
            "next_move": self.next_move_ru,
            "why": self.why_ru,
            "host_state": self.host_state,
            "declared_host_id": self.declared_host_id,
            "host_source": self.host_source,
            "origin": self.origin,
        }


@dataclass(frozen=True)
class Judgement:
    """All judgements TOGETHER with three different completeness counters."""

    judged: tuple[Judged, ...]
    by_kind: dict[str, int] = field(default_factory=dict)
    by_rung: dict[str, int] = field(default_factory=dict)
    #: A WRITTEN rule -> how many pairs it removed from the worktable
    #: (stages `note` and `nothing`). Not one of them disappeared — all
    #: of them are here by name.
    filtered_by_rule: dict[str, int] = field(default_factory=dict)
    #: A REFUSED rule -> how many pairs were left without a judgement
    #: because of it. A separate counter, not a line in the previous
    #: one: "a rule removed a pair" and "there is no rule" are different
    #: facts, and the second costs more: it shows what is missing from
    #: the LANGUAGE, not from the building.
    refused_by_rule: dict[str, int] = field(default_factory=dict)
    #: Rounding -> how many pairs it explained.
    filtered_by_slack: dict[str, int] = field(default_factory=dict)
    #: PROVENANCE -> how many pairs. A separate counter, because the
    #: question "what did the turn introduce" and the question "what is
    #: in the building" are different, and one number for both always
    #: answers the one that was not asked.
    by_origin: dict[str, int] = field(default_factory=dict)
    #: THE HOST EDGE'S STATE -> how many pairs. A separate counter, not
    #: a line in `filtered_by_rule`: what the host removed is visible
    #: there, but `contradicts` and `absent` remove NOTHING and so would
    #: never appear in that counter at all — meaning the most expensive
    #: fact ("a host is declared, and it is a different wall") would be
    #: left without a denominator.
    by_host_state: dict[str, int] = field(default_factory=dict)
    #: A rule -> its justification, ONLY for rules that fired today. The
    #: justification rides into the receipt as data, not as text: a
    #: rule that cannot be contested by reading it is no better than a
    #: threshold pulled from the ceiling.
    justifications: dict[str, str] = field(default_factory=dict)
    #: THE SECOND PASS'S BOOKKEEPING: `computed` — the turn was computed
    #: by minimal separation, `refused` — the solver refused with a
    #: named reason, `skipped_budget` — the budget ran out, and we SAY
    #: SO. An empty dictionary = the second pass was not run
    #: (`propose_budget_ms=0`), and that is not the same as "computed
    #: zero."
    proposals: dict[str, int] = field(default_factory=dict)

    @property
    def actionable(self) -> tuple[Judged, ...]:
        return tuple(j for j in self.judged
                     if _RUNG_ORDER[j.rung] <= _RUNG_ORDER["look"])


def _label_ru(label: str) -> str:
    from kir.clash.review import LABEL_RU
    return LABEL_RU.get(label, label or "элемент")


def _plate_can_miss(sa, sb) -> bool:
    """∃ a LEGITIMATE reading under which the slices do not meet along Z.

    The set of legitimate readings is NOT the product {down,up}²: the
    direction of growth is a property of the CONVENTION, not of the
    element, so two ops of ONE class are read identically. Cross
    readings (one slab down, the other up under one class) are
    physically impossible, and it was exactly these that used to
    satisfy the condition IDENTICALLY: 2·min(tₐ,t_b) − tₐ − t_b =
    −|tₐ − t_b| ≤ 0 for any thicknesses. A certificate that cannot fail
    to fire reads as proof without being one.
    """
    ta, tb = float(sa.get("z_mm") or 0.0), float(sb.get("z_mm") or 0.0)
    ra, rb = sa.get("z_ref_mm"), sb.get("z_ref_mm")
    if not (ta > 0.0 and tb > 0.0) or ra is None or rb is None:
        return False                      # nothing to judge by — NOT a refutation
    ga, gb = sa.get("grow_class"), sb.get("grow_class")
    if ga is None or gb is None:
        return False                      # NOT a refutation, but silence
    readings = (("down", "down"), ("up", "up")) if ga == gb else (
        ("down", "down"), ("up", "up"), ("down", "up"), ("up", "down"))
    for da, db in readings:
        lo_a, hi_a = (ra - ta, ra) if da == "down" else (ra, ra + ta)
        lo_b, hi_b = (rb - tb, rb) if db == "down" else (rb, rb + tb)
        if min(hi_a, hi_b) - max(lo_a, lo_b) <= 0.0:
            return True
    return False


def _slack_explains(finding: Mapping[str, Any], hulls: Mapping[str, Any],
                    profiles: Mapping[str, Any],
                    slack: Mapping[str, Any]) -> tuple[str, ...]:
    """Which of OUR OWN roundings fully explain this overlap.

    Empty means none. Each line is a `SLACK_REASONS` key, and it means
    "a legitimate reading of the same program exists under which the
    bodies do not meet along this axis."

    `hulls` IS NO LONGER READ, and that is said out loud. After the set
    of readings was narrowed, the Z certificate judges by the ROUNDING'S
    RECORDS — elevation, thickness, the convention class — not by the
    bounding sizes of built hulls. The parameter is kept because removing
    it means editing `judge`'s PUBLIC signature, and that is not decided
    here.
    """
    a_id = finding["a"]["source_element_id"]
    b_id = finding["b"]["source_element_id"]
    found: list[str] = []

    # ── the Z axis: a slab rounded TWOFOLD ──────────────────────────────
    # The actual slab body is a slice of thickness t within the declared
    # span 2t, and the program does not name the slice's position.
    # `_plate_can_miss` judges this: what decides is not arithmetic over
    # spans but WHICH SET OF READINGS ∃ ranges over, and that set is a
    # diagonal, not a square.
    sa, sb = slack.get(a_id) or {}, slack.get(b_id) or {}
    if _plate_can_miss(sa, sb):
        found.append("plate_z_doubling")

    # ── plan: the footprint is convexified ───────────────────────────────
    loop_a = (profiles.get(a_id) or {}).get("exterior_loop")
    loop_b = (profiles.get(b_id) or {}).get("exterior_loop")
    if loop_a and loop_b and not (loop_is_convex(loop_a) and loop_is_convex(loop_b)):
        # Referring to the convexification is allowed ONLY when it is
        # nonzero: for a convex outline the hull equals the outline, and
        # there is nothing to explain with it.
        if loops_overlap(loop_a, loop_b) is False:
            found.append("profile_convexified")
    return tuple(found)


def _hull_is_a_box(side: Mapping[str, Any]) -> bool:
    return str(side.get("hull_source") or "") == "bbox"


def _has_certified_inner_overlap(finding: Mapping[str, Any]) -> bool:
    """Validate the detector's sealed proof chain fail-closed.

    This consumer never recreates authority from plausible public fields.
    ``detect`` owns the one narrow verifier for both certificate tags and the
    pair tag; missing, replayed or edited serialized evidence stays unproven.
    """

    if finding.get("verdict") != "confirmed":
        return False
    proof = finding.get("physical_overlap_proof")
    side_a = finding.get("a")
    side_b = finding.get("b")
    if (not isinstance(proof, Mapping)
            or not isinstance(side_a, Mapping)
            or not isinstance(side_b, Mapping)):
        return False
    subject_a = side_a.get("source_element_id")
    subject_b = side_b.get("source_element_id")
    if not isinstance(subject_a, str) or not isinstance(subject_b, str):
        return False
    return clash_detect.verify_serialized_physical_overlap_proof(
        proof, subject_a=subject_a, subject_b=subject_b)


def _physical_overlap_proof(
        finding: Mapping[str, Any], explains: tuple[str, ...]
        ) -> bool | None:
    """Whether the geometry has proven an overlap of BODIES.

    This is a proof-firebreak between the detector and the design
    judgement. `detect` already publishes a typed `verdict`: an
    intersection of conservative OUTER hulls is `possible`, not a fact
    about bodies. The judgement layer has no right to promote this type
    by the indirect sign of "thinner than bbox."

    `True` is accepted only for the consistent chain
    `confirmed + certified_inner_overlap + valid certificates`. The
    OUTER hull's grade does not enter this chain. Any contradictory or
    incomplete record closes into `None`, not into a guess.
    """
    if explains:
        return False
    verdict = str(finding.get("verdict") or "")
    grade = str(finding.get("hull_grade") or "")
    a, b = finding.get("a") or {}, finding.get("b") or {}
    if verdict == "possible":
        # `coarse` does not describe the body at all; with
        # `conservative`, the body is localized, but the OUTER overlap
        # remains only an unproven hypothesis. These states are
        # deliberately different: `None` is a data hole, `False` is an
        # honest possible.
        return None if grade == "coarse" or _hull_is_a_box(a) \
            or _hull_is_a_box(b) else False
    return True if _has_certified_inner_overlap(finding) else None


# ═════════════════════════════════════════════════════════════════════════
# 4b. THE HOST — AN EDGE, NOT A PAIR OF LABELS
#
# WHAT THIS FIXES (measured 10.08.2026, two real buildings, instrument
# `/tmp/wiring/m_baseline.py`). Before this wave, the relation "a door
# lives IN a wall" was judged in the package by TWO different methods,
# and neither read data that already exists:
#
#   * `clash/resolve.ASSEMBLY_PAIRS` — A GUESS BY A PAIR OF LABELS.
#     Measured against `L0Element.host_id`, which carries the answer:
#       `sob62_r23_v5`      — 3,759 findings, the guess fires 497 times,
#                             the host CONFIRMS 184, does NOT confirm
#                             **313** (63.0%): `door~wall` 181,
#                             `wall~window` 58;
#       `sob62_fas_r23_v19` — 27,041 findings, guess 8,815, confirms
#                             1,453, does NOT confirm **7,362** (83.5%):
#                             `mullion~wall` 4,061, `curtain_panel~mullion`
#                             1,838.
#     Sample: `door~wall (10324348, 13109052)` — the door's actual host
#     is `9857641`, a DIFFERENT wall. The guess says "a node, don't
#     look"; the data says "the door overlaps a wall it does not live
#     in";
#   * `_host_declared` (used to be HERE) — read `host` off the op, and
#     that is the right source, but BINARY: "declared" or "not." "No
#     host was declared at all" and "a host is declared, and it is NOT
#     the other side" were merged into one value, `False`, meaning the
#     second fact — the most expensive of the three — never reached the
#     reader at all.
#
# THAT IS WHY THERE ARE FOUR STATES, NOT TWO, and they are separated by
# the same law by which `hulls_coincide` separates "no" from "nothing to
# say":
#
#   confirms    — one side declared the OTHER as its host. Removes the
#                 pair: this is a mode of existing, not a contradiction;
#   contradicts — a side declared a host, and it is NOT the other side.
#                 THE FINDING STAYS, and the actual host's address rides
#                 along with it;
#   host_out_of_scope
#               — a host IS DECLARED, but no such element exists in the
#                 extraction, and it was NOT declared by the AUTHOR.
#                 Measured across the whole corpus (11.08.2026): 1,263
#                 dangling edges out of 213,811, and they cluster —
#                 `snowdon_elec_v1` 959 of 1,001 (95.8%), four Snowdon
#                 Plumbing snapshots at 100% each. Of these, 1,010 lead
#                 into a linked file, 86 into a `ReferencePlane`. Dumping
#                 this into `contradicts` would mean blaming the author
#                 959 times for a boundary of OUR OWN reading. Does not
#                 remove the pair;
#   absent      — the index exists, and BOTH sides have no host declared
#                 at all. This is not an excuse: the absence of a host
#                 says nothing about whether the bodies contradict or
#                 not;
#   unknown     — there is NO INDEX AT ALL (no one asked). `absent` and
#                 `unknown` must be different values for the same reason
#                 `journal.sections` distinguishes `None` from `{}`:
#                 "asked, there is no host" and "did not ask" are
#                 different facts, and the second must not be printed as
#                 the first.
#
# WHAT IS NOT HERE. An opinion of its own about WHICH pairs of labels
# count as a node. The `ASSEMBLY_PAIRS` list is neither imported into
# nor repeated in this module: a third source of truth about one
# concept was already written once (`fold._CATEGORY_DISCIPLINE`) and
# drifted from the table on 25 categories.
# ═════════════════════════════════════════════════════════════════════════

#: The separator for a bundle op's qualified identifier. EQUALS
#: `clash_bundle._BUNDLE_SEP`, and the equality is held by a test:
#: without it, address `p1/wall3` and address `p7/wall3` would read as
#: one.
_BUNDLE_SEP = "/"

#: The states of the host edge. A closed list: a state outside it is
#: exactly the unsigned axis this whole accounting was set up to
#: forbid. The source whose words BIND THE AUTHOR. Only the program:
#: everything else is the decompile's words, and the decompile is not
#: the author's boss.
AUTHORED_SOURCE = "program_host_ref"

HOST_STATES: tuple[str, ...] = (
    "confirms", "contradicts", "host_out_of_scope", "absent", "unknown")

#: THE PAIR'S PROVENANCE — who introduced it. A closed list.
#:
#: WHY (measured 11.08.2026, `/tmp/wiring/m_delta.py`, reassembly of
#: `snowdon_plumb_v4`, 129 chunks): on the last turn the receipt says
#: "45 CONTRADICTIONS," and all 45 stood there BEFORE this turn — the
#: turn introduced NOT A SINGLE ONE. The engineer who pressed the
#: button reads 45 as his own contribution. This is the same
#: blame-the-other-guy that the host edge was just cured of.
#:
#:   both_new   — both sides were declared by THIS turn: the
#:                contradiction is entirely its own;
#:   one_new    — one side is its own, the other stood there before.
#:                ALSO a contribution of the turn: without it, this
#:                pair would not have existed at all;
#:   both_prior — both sides stood there before the turn. NOT its work,
#:                and adding it to the first two means bringing back
#:                the exact number that must not be read;
#:   unknown    — the turn's boundary was not named. This is NOT
#:                `both_prior`: "did not ask" and "stood there before"
#:                are different facts, and the second would declare
#:                everyone else's whatever was not asked about.
ORIGINS: tuple[str, ...] = ("both_new", "one_new", "both_prior", "unknown")


def origin_of(a_id: str, b_id: str,
              new_ids: frozenset[str] | None) -> str:
    """The pair's provenance. `None` -> `unknown` (the turn's boundary
    was not named).

    A side is assigned to a turn by the address of ITS OWN OP: the body
    of a graph edge (`p3/g#7`) belongs to the same turn as the op
    `p3/g` that spawned it.
    """
    if new_ids is None:
        return "unknown"
    a = a_id in new_ids or _op_key(a_id) in new_ids
    b = b_id in new_ids or _op_key(b_id) in new_ids
    if a and b:
        return "both_new"
    return "one_new" if (a or b) else "both_prior"


def _program_of(element_id: str) -> str:
    """The PROGRAM prefix of a bundle address (`p1/wall3` -> `p1`).

    Needed because `id` is unique within a program, while between
    programs a coincidence is LEGITIMATE — exactly why
    `clash_bundle.bundle_oid` qualifies the address ALWAYS. Comparing
    `host.value` against a neighbor's bare `id` would mean declaring a
    namesake from someone else's program as the host.
    """
    head, sep, _ = element_id.partition(_BUNDLE_SEP)
    return head if sep else ""


def _host_ref_of(op: Mapping[str, Any] | None) -> str | None:
    """The bare `id` the op named as its host, or `None`.

    The reference's form is taken from the language itself: within a
    program the author refers to a neighboring op via
    `{"by":"ref","value":<id>}`, and has no other way. A string is
    accepted as the same reference written more briefly.
    """
    if not isinstance(op, Mapping):
        return None
    host = op.get("host")
    if isinstance(host, Mapping):
        if str(host.get("by") or "") != "ref":
            return None
        value = host.get("value")
        return None if value is None else str(value)
    if isinstance(host, str) and host.strip():
        return host.strip()
    return None


def hosted_from_ops(ops: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """`element_id -> op` -> the host index IN THE PROGRAM'S OWN WORDS.

    A reference is resolved ONLY within its own program (`KIR-V002`: a
    reference across a program boundary is illegal), so the candidate
    is sought among addresses with the same `p<N>/` prefix. An
    unresolved reference stays in the index with
    `host_element_id = None`: the author DID NAME a host, and staying
    silent about it is not allowed — "a host is named but not found" is
    closer to `contradicts` than to `absent`, and that is exactly how
    it is read further down.
    """
    by_program: dict[str, dict[str, str]] = {}
    for element_id, op in ops.items():
        if not isinstance(op, Mapping):
            continue
        oid = op.get("id")
        if oid is None:
            continue
        by_program.setdefault(_program_of(str(element_id)), {}).setdefault(
            str(oid), str(element_id))
    out: dict[str, dict[str, Any]] = {}
    for element_id, op in ops.items():
        ref = _host_ref_of(op)
        if ref is None:
            continue
        program = _program_of(str(element_id))
        target = (by_program.get(program) or {}).get(ref)
        out[str(element_id)] = {
            "host_element_id": target,
            "host_ref": ref,
            "host_class": None if target is None else str(
                (ops.get(target) or {}).get("op") or "") or None,
            "source": "program_host_ref",
        }
    return out


def host_relation(a_id: str, b_id: str,
                  hosted: Mapping[str, Any] | None
                  ) -> tuple[str, str | None, str | None]:
    """The host edge for a pair -> (state, host address, whose words
    these are).

    The state is one of `HOST_STATES`. The host address is returned
    ONLY for `contradicts`: there it is exactly the news ("the door
    overlaps a wall it does not live in, it lives in this one
    instead"). For `confirms`, the host is the pair's other side, and
    repeating its address would mean printing what is already printed.

    ABSENCE DOES NOT EXCUSE. `absent` is returned only when the index
    EXISTS and neither side declared a host; the reader must read this
    as "nothing to say about the host," not as "there is no host, so it
    must be a node."
    """
    if hosted is None:
        return "unknown", None, None
    a_key, b_key = _op_key(a_id), _op_key(b_id)
    #: Candidate outcomes, STRONGEST FIRST. `contradicts` outweighs
    #: `host_out_of_scope` because it is a stronger assertion: there the
    #: host IS KNOWN and it is not the other side, here we simply did
    #: not see the host. Staying silent about the stronger one for the
    #: sake of the weaker one is not allowed.
    found: dict[str, tuple[str, str | None]] = {}
    for me, other, other_key in ((a_id, b_id, b_key), (b_id, a_id, a_key)):
        edge = hosted.get(me) or hosted.get(_op_key(me))
        if not isinstance(edge, Mapping):
            continue
        target = edge.get("host_element_id")
        source = str(edge.get("source") or "") or None
        if target is not None:
            if _op_key(str(target)) in (other, other_key):
                return "confirms", None, source
            found.setdefault("contradicts", (str(target), source))
            continue
        # A HOST IS NAMED BUT NOT FOUND — AND THAT IS TWO DIFFERENT
        # FACTS, DEPENDING ON WHOSE WORDS THESE ARE. The PROGRAM's
        # words: the author referenced an op that does not exist in his
        # program, and he is the one who fixes it (`KIR-V002`). The
        # DECOMPILE's words: we did not extract the host — measured
        # across the corpus, it lies in a linked file (1,010 of 1,263)
        # or is a datum (86), and blaming the author 959 times in a row
        # for a boundary of our own reading is a defect of the same
        # kind as a silent instrument, just with the opposite sign.
        ref = str(edge.get("host_ref") or "") or "?"
        key = ("contradicts" if source == AUTHORED_SOURCE
               else "host_out_of_scope")
        found.setdefault(key, (ref, source))
    for state in ("contradicts", "host_out_of_scope"):
        if state in found:
            return state, found[state][0], found[state][1]
    return "absent", None, None


def _classify(finding: Mapping[str, Any], slack: tuple[str, ...],
              host_state: str) -> tuple[str, str]:
    """A pair -> (rule, refused rule, or empty). Order MATTERS."""
    a, b = finding["a"], finding["b"]
    role_a, role_b = role_of(a.get("label")), role_of(b.get("label"))
    roles = {role_a, role_b}
    relation = finding.get("hull_relation")

    # ONLY CONFIRMATION REMOVES A PAIR. `contradicts`, `absent`, and
    # `unknown` fall through DELIBERATELY: a pair removed for the
    # absence of a host is an excuse by silence, exactly the defect the
    # edge became a tristate to fix.
    if host_state == "confirms":
        return "host_declared", ""
    if finding.get("pair_kind") == "coincident_duplicate":
        return "duplicate", ""
    if relation == "contact" and roles <= _STRUCTURE_ROLES:
        return "structure_contact", ""
    if slack:
        return "hull_over_approximation", ""
    if roles <= _RUN_ROLES:
        if relation == "contact":
            return "unclassified", "run_meets_run_clearance"
        return "run_meets_run", ""
    if roles & _RUN_ROLES:
        other = role_b if role_a in _RUN_ROLES else role_a
        if other == "envelope":
            return "run_through_envelope", ""
        if other == "bearing":
            return "run_through_bearing", ""
        if other == "equipment":
            return "run_meets_equipment", ""
        return "unclassified", ""
    if roles <= _STRUCTURE_ROLES:
        return "unclassified", "structure_meets_structure_overlap"
    if roles & {"equipment"} and roles & _STRUCTURE_ROLES:
        return "unclassified", "equipment_meets_structure"
    return "unclassified", ""


def _rung(kind: str, finding: Mapping[str, Any], proven: bool | None) -> str:
    """STAGE = (proof strength × kind × depth). Not a single threshold
    pulled from the ceiling.

    There is exactly one depth threshold here, and it is SOMEONE ELSE'S:
    `ranking_tol_mm` is the tolerance of the hull's OWN grade from
    `hulls.TOL_GRADE_MM` (exact 0, conservative 1, coarse 25 mm). An
    overlap finer than that lies within the hull's own numerical noise,
    and there is nothing to assert from it.

    This module deliberately does not set up its own "significant /
    insignificant." The `clash/review.py` layer holds thresholds of 100
    mm and 10 mm that have no justification either in its text or in
    the package's measurements; repeating them here would mean doubling
    the invention. The depth rides into the finding as a NUMBER, and
    the reader judges for himself.
    """
    depth = float(finding.get("hull_overlap_depth_mm") or 0.0)
    tol = float(finding.get("ranking_tol_mm") or 0.0)
    if kind in ("adjacency",):
        return "note"
    if kind in ("unproven", "unclassified"):
        return "nothing"
    if kind == "duplicate":
        # Exact geometric coincidence is still a review task until semantic
        # equivalence and absence of external dependencies are proved.
        return "look"
    if kind == "penetration":
        # A node, but by a bounding box, and the node is not visible.
        #
        # `proven is not False and proven is not None` USED TO STAND
        # HERE, and the first term COULD NOT BE FALSE. `_classify`
        # returns `penetration` only AFTER the branch
        # `if slack: return "hull_over_approximation"`, meaning that
        # for a penetration the rounding is ALWAYS empty, and
        # `proven=False` is set exactly and only when the rounding is
        # non-empty. A condition that cannot fail to hold reads as a
        # check without being one — the same class as the vacuous
        # certificate `_plate_can_miss`, killed this same week.
        return "agree" if proven is True else "look"
    # collision | duplicate
    if proven is not True:
        return "look"
    if depth <= tol:
        # Within the grade's own tolerance — look, but do not fix.
        return "look"
    return "fix"


def _op_address(element_id: str, op: Mapping[str, Any] | None) -> str:
    name = str((op or {}).get("op") or "оп")
    return f"`{name} {element_id}`"


#: 🔴 SIX DIGITS — NOT "PRETTY," BUT DERIVED FROM `geom.SEP_EPS_MM`
#: (F-028, 29.08.2026). The separation certificate promises
#: `signed_distance >= -1e-6`, and the fallback bounding-box candidate
#: is built RIGHT UP AGAINST this boundary. So printing that loses more
#: than a micron takes back the promise along with the number. Half a
#: unit of the last of the six digits is 5e-7 per axis, up to 8.7e-7
#: over three axes by length: strictly less than 1e-6, meaning the
#: printed vector still separates the same pair. The `+.0f` format lost
#: up to 0.5 mm — 500,000 times the tolerance — and for a 0.4 mm move
#: it ate the move entirely and printed "shift by (+0, +0, +0) mm,"
#: calling that a certified translation. Measured over 4,000 synthetic
#: pairs: for 49.3% the printed `+.0f` vector NO LONGER SEPARATES the
#: bodies.
def _mm(value: float) -> str:
    """A turn's component is printed so as to survive its own printing."""
    text = f"{float(value):+.6f}".rstrip("0").rstrip(".")
    return "+0" if text in ("+", "-", "+0", "-0") else text


def _diameter_of(op: Mapping[str, Any] | None) -> float | None:
    value = (op or {}).get("diameter_mm")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _next_move(rule_id: str, finding: Mapping[str, Any],
               slack: tuple[str, ...], op_a: Mapping[str, Any] | None,
               op_b: Mapping[str, Any] | None,
               proven: bool | None) -> str:
    """A TURN DERIVED FROM THE PROGRAM. Not a single guess: either the
    op's address and its operand, or a number computed by the detector,
    or an honest "nothing to give"."""
    a, b = finding["a"], finding["b"]
    a_id, b_id = a["source_element_id"], b["source_element_id"]
    addr_a, addr_b = _op_address(a_id, op_a), _op_address(b_id, op_b)
    vector = finding.get("certified_separating_translation_mm")

    if rule_id == "duplicate":
        if clash_detect.duplicate_claim_is_proven(dict(finding)):
            return (f"сверить {addr_a} и {addr_b}: точные тела совпали, но "
                    "семантическая взаимозаменяемость и отсутствие внешних "
                    "зависимостей не доказаны; автоматически удалять нельзя")
        return (f"сверить {addr_a} и {addr_b} по точным телам: детектор "
                f"видит совпадение внешних оболочек, но не доказал "
                f"совпадение тел; удалять по такой находке нельзя")
    if rule_id == "host_declared":
        return "ничего: автор сам объявил вмещение через `host`"
    if rule_id == "structure_contact":
        # 🔴 THE TURN STOPS VOUCHING FOR THE UNMEASURED (F-026). The
        # stage does NOT change and must not change: a bounding box is
        # CONSERVATIVE, and boxes touching EXCLUDES bodies intersecting
        # — sending a person to where there is definitely no clash
        # would cost him a day. What was wrong was not the stage but the
        # assertion "must be touching": a node cannot be confirmed by
        # it.
        if proven is True:
            return "ничего: конструкции обязаны касаться"
        return ("ничего ПО КЛЕШУ: оболочки консервативны, тела пересечься не "
                "могут; но КАСАНИЕ ТЕЛ не доказано — узел этим не подтвердить")
    if rule_id == "hull_over_approximation":
        moves = []
        if "plate_z_doubling" in slack:
            moves.append(
                "программа не выражает, в какую сторону от отметки нарастает "
                "плита; пока не выражает — эта пара не судится")
        if "profile_convexified" in slack:
            moves.append(
                "объявленные контуры в плане НЕ встречаются: спор возможен "
                "только за пределами объявленного контура")
        return "; ".join(moves) or "дополнить заявление"
    if (rule_id in ("run_through_envelope", "run_meets_run",
                    "run_through_bearing", "run_meets_equipment")
            and proven is not True):
        return (
            "проверить точное тело или получить inner-evidence: "
            "сейчас пересекаются только внешние оболочки; "
            "менять или удалять операции по этой находке нельзя")
    if rule_id == "run_through_envelope":
        run_op, run_id = ((op_a, a_id) if role_of(a.get("label")) in _RUN_ROLES
                          else (op_b, b_id))
        host_id = b_id if run_id == a_id else a_id
        diameter = _diameter_of(run_op)
        size = f" под Ø{diameter:.0f} мм" if diameter else ""
        return (f"объявить проём: `create_opening` с `host` = {host_id}"
                f"{size} — либо подтвердить, что проём уже в модели")
    if rule_id in ("run_meets_run", "run_through_bearing",
                   "run_meets_equipment"):
        if isinstance(vector, (list, tuple)) and len(vector) == 3:
            v = ", ".join(_mm(c) for c in vector)
            return (f"развести: сдвинуть {addr_a} на ({v}) мм — это "
                    f"сертифицированный разводящий перенос детектора")
        diameter = _diameter_of(op_a) or _diameter_of(op_b)
        if diameter:
            return (f"развести: сдвинуть {addr_a} или {addr_b}; объявленный "
                    f"размер трассы — Ø{diameter:.0f} мм")
        return f"развести: сдвинуть {addr_a} или {addr_b}"
    return "нечем: ни одно правило не применимо, пара оставлена с числами"


def _text(rule: Rule, finding: Mapping[str, Any], proven: bool | None,
          slack: tuple[str, ...]) -> str:
    a, b = finding["a"], finding["b"]
    an, bn = _label_ru(a.get("label")), _label_ru(b.get("label"))
    a_id, b_id = a["source_element_id"], b["source_element_id"]
    depth = float(finding.get("hull_overlap_depth_mm") or 0.0)
    grade = finding.get("hull_grade")
    tol = float(finding.get("ranking_tol_mm") or 0.0)
    disc_a, disc_b = (discipline_of(a.get("category")),
                      discipline_of(b.get("category")))
    disc = (f"раздел {disc_a}" if disc_a == disc_b
            else f"разделы {disc_a}↔{disc_b}")
    if proven is True:
        sure = "доказано точной геометрией"
    elif proven is False and finding.get("verdict") == "possible":
        sure = "НЕ доказано: вердикт геометрии possible"
    elif proven is False:
        sure = "НЕ доказано: перекрытие объяснено огрублением"
    else:
        sure = "сказать нечего: свидетельство грубое или неполное"
    possible = proven is not True
    head = {
        "duplicate": (("ВОЗМОЖНЫЙ " if possible else "")
                      + f"ДУБЛИКАТ: {an} {a_id} и {bn} {b_id} "
                      + ("имеют перекрывающиеся оболочки" if possible
                         else "стоят НА ОДНОМ МЕСТЕ")),
        "collision": (("ВОЗМОЖНОЕ " if possible else "")
                      + f"СТОЛКНОВЕНИЕ: {an} {a_id} и {bn} {b_id} "
                      + ("пересекаются только внешними оболочками" if possible
                         else "делят объём")),
        "penetration": (("ВОЗМОЖНЫЙ " if possible else "")
                        + f"ПРОХОД СКВОЗЬ КОНСТРУКЦИЮ: {an} {a_id} "
                        + ((f"и {bn} {b_id} пересекаются только "
                            "внешними оболочками") if possible
                           else f"в теле {bn} {b_id}")),
        # 🔴 ADJACENCY IS A FACT ABOUT HULLS, NOT ABOUT BODIES (F-026,
        # 29.08.2026). `relation` is computed from OUTER hulls
        # (`detect.relation_of`), and for a pair with
        # `hull_source='bbox'` the outer hull is a Revit bounding box.
        # Two bodies half a meter apart give exactly the same box
        # contact, and the line was asserting about the building
        # something it had not measured. A neighboring layer on the
        # same input already tells the truth (`review.phrase`, the
        # `hull_relation == "contact"` branch) — the two layers that
        # drifted apart were OUR OWN two, not us and the model.
        "adjacency": (f"ПРИМЫКАНИЕ: {an} {a_id} и {bn} {b_id} "
                      + ("соприкасаются" if proven is True
                         else "соприкасаются ОБОЛОЧКАМИ, касание тел не "
                              "доказано")),
        "unproven": (f"НЕ ДОКАЗАНО: {an} {a_id} и {bn} {b_id} спорят только "
                     f"в оболочках"),
        "unclassified": f"БЕЗ СУЖДЕНИЯ: {an} {a_id} и {bn} {b_id}",
    }[rule.kind]
    line = (f"{head}; глубина {depth:.0f} мм, {sure} "
            f"(грейд {grade}, допуск грейда {tol:.0f} мм, {disc})")
    if rule.kind == "penetration":
        line += (". СКВОЗЬ ИЛИ ВДОЛЬ — по оболочкам не различается: "
                 "трасса, лежащая внутри конструкции по её длине, дала бы "
                 "ту же глубину")
    if slack and rule.kind == "unproven":
        # The rounding is printed where it is exactly the answer. For
        # adjacency the answer is different, and hanging the same sheet
        # on it would mean drowning it.
        line += ". ОГРУБЛЕНИЕ: " + "; ".join(SLACK_REASONS[s] for s in slack)
    return line


def _same_host(a_id: str, b_id: str,
               hosted: Mapping[str, Any] | None) -> str | None:
    """The shared host of both sides, or `None`.

    THE MEASUREMENT this case was separated for (10.08.2026,
    `/tmp/wiring/m_contra.py`): out of 8,728 `contradicts` pairs on
    `sob62_fas_r23_v19`, **1,584 are SIBLINGS** — both sides declared
    the SAME host (a panel and a mullion of one curtain wall, two
    panels of one curtain wall). On `sob62_r23_v5`, 15 out of 588 are
    such.

    The difference is not cosmetic: "the door overlaps a wall it does
    not live in" and "two panels of ONE curtain wall stand in the same
    place" are fixed in different places — the first by moving, the
    second by deleting the extra panel. A reader given one phrase for
    both cases will not find the second fix.
    """
    if hosted is None:
        return None
    ea = hosted.get(a_id) or hosted.get(_op_key(a_id))
    eb = hosted.get(b_id) or hosted.get(_op_key(b_id))
    if not isinstance(ea, Mapping) or not isinstance(eb, Mapping):
        return None
    ha, hb = ea.get("host_element_id"), eb.get("host_element_id")
    if ha is None or hb is None or str(ha) != str(hb):
        return None
    return str(ha)


def _host_note(host_state: str, host_id: str | None,
               shared: str | None = None) -> str:
    """A host annotation — ONLY where it is news.

    `confirms` stays silent: the pair is already removed by the
    `host_declared` rule, and its text has already said everything.
    `unknown` stays silent: "there was no index" is a property of the
    CALL, not of this pair, and printing it on every line would mean
    paying context for news that does not exist; a counter,
    `by_host_state`, exists for it.

    ONLY `contradicts` speaks, because it is the only state in which
    the edge changes what the reader will do: the pair looks like a
    node by labels, while the element's host is a DIFFERENT one.
    """
    if host_state == "host_out_of_scope":
        # NAMES THE BOUNDARY, NOT THE CULPRIT. Measured across the
        # corpus: 1,010 of 1,263 such hosts lie in a LINKED file, 86
        # are datums (`ReferencePlane`), which can never be a body in
        # principle. The author has no part in this in either case.
        return (f". ХОЗЯИН ОБЪЯВЛЕН, НО ЕГО НЕТ В ИЗВЛЕЧЕНИИ: разбор называет "
                f"хозяином `{host_id}`, а такого элемента мы не извлекали — "
                f"он за границей чтения (связанный файл либо датум). Это НЕ "
                f"ошибка автора и НЕ оправдание паре: про вмещение здесь "
                f"сказать нечего, находка остаётся")
    if host_state != "contradicts":
        return ""
    if shared is not None:
        return (f". ОБЕ СТОРОНЫ ЖИВУТ В ОДНОМ ХОЗЯИНЕ `{shared}`, а не одна в "
                f"другой: это БРАТЬЯ, и перекрытие между ними хозяином не "
                f"объясняется — узел здесь ни при чём")
    return (f". ХОЗЯИН ОБЪЯВЛЕН, И ЭТО НЕ ВТОРАЯ СТОРОНА: автор назвал хозяином "
            f"`{host_id}`, а перекрытие — с другим элементом. Снятие по "
            f"хозяину НЕ ПРИМЕНИМО, находка остаётся")


#: The prefix of a body spawned by a graph edge
#: (`clash_bundle._SEGMENT_SEP`): all edges of one graph share ONE op,
#: and the finding's turn addresses exactly that one.
_SEGMENT_SEP = "#"


def _op_key(element_id: str) -> str:
    return element_id.split(_SEGMENT_SEP, 1)[0]


#: Rules whose turn is TODAY printed as the detector's raw vector. The
#: list is COMPLETE BY CONSTRUCTION: it is derived from the single
#: `_next_move` branch that prints a vector at all. If a second one
#: appears, the list must grow along with it, and that is held by
#: `test_clash_minimal_move.py`.
_VECTOR_MOVE_RULES = frozenset({
    "run_meets_run", "run_through_bearing", "run_meets_equipment"})


#: 🔴 THE STAGES AT WHICH A TURN IS LEGITIMATE TO NAME AT ALL. Exactly one.
#:
#: THE BAN DOES NOT STAND HERE OR IN A TEST, BUT IN THE STAGE'S OWN
#: DEFINITION — `RUNGS`, the `look` line: "at least one hull is a
#: bounding box, it does not describe the body. **A destructive
#: instruction for such a finding IS FORBIDDEN**." This is an authority,
#: not a wish: advising a move on a finding that OUR OWN ROUNDING COULD
#: HAVE CREATED means moving a real element by our own error.
#:
#: 🔴 THIS CONSTANT WAS PAID FOR BY A LIVE DEFECT ON 17.08.2026, NOT BY
#: CAUTION. The first edition of `_upgrade_moves` filtered ONLY by
#: `rule_id` and never asked about the stage. For `rung=look,
#: proven=False` it swapped the honest "obtain the missing evidence" for
#: "move the pipe by −Y 150 mm — the move is clear." The code made it
#: into production and ran with `KUKAI_IR_CLASH=1` enabled; a
#: neighboring session caught it with its own suite, not me.
#:
#: THE COST OF THE MISTAKE WOULD NOT HAVE BEEN THEORETICAL: the canon
#: says `verdict=confirmed` for a clash is UNREACHABLE today (it needs
#: two certified inner hulls, production does not issue them), and
#: `_rung` gives `fix` only when `proven is True`. So IN PRODUCTION all
#: findings sit at `look`, and the unclosed branch would have issued a
#: destructive instruction for 100% of live findings.
#:
#: WHY NOT "PRINT IT AS A HYPOTHESIS." That outcome was discussed and
#: rejected: the cost is asymmetric. Not naming the number costs one
#: extra step, exactly what the `look` stage prescribes ("open it and
#: look"); naming it costs moving a real element in a real building by
#: our own error. A conditional phrasing does not save this: a number
#: that looks executable gets executed.
_RUNGS_ALLOWING_A_NAMED_MOVE = frozenset({"fix"})


def _upgrade_moves(judged: list[Judged],
                   by_fid: Mapping[str, Mapping[str, Any]],
                   hulls: Mapping[str, Any],
                   *, budget_ms: float,
                   hosted: Mapping[str, Any] | None = None,
                   ) -> tuple[list[Judged], dict[str, int]]:
    """The detector's raw vector -> a PROVABLY minimal separation.

    WHY. `detect` returns a certified separating translation, while
    `resolve` looks for the SMALLEST one. The difference is measured
    over 600 real findings from `sob62_r23_v5` (`resolve.py:32-38`):
    median **5.892x**, p90 56.667x, maximum **112,066.5x** — "where a
    pipe needs only eight millimeters sideways, the old vector used to
    carry it tens of meters upward." Before 17.08 this was computed and
    went ONLY into the human panel (`viewer/advice.py`); the model,
    which is what edits the program, received the raw vector.

    WHY A SECOND PASS. The display order is decided by the sort AFTER
    the loop: inside the loop it is still unknown which lines will
    reach the reader, and computing the separation for ALL pairs is
    forbidden by cost (19,239 façade overlaps at 29.1 ms — 9.3 minutes,
    `advice.py:193`).

    WHY A TIME BUDGET, NOT A LINE COUNT — and this is a refutation of
    the first edition of this fix. Measured 17.08, `propose` on the
    three deepest overlaps of two saved decompiles:

        sob62_r23_v5      1,326 bodies ->     5.9 ms for three
        snowdon_plumb_v3  6,381 bodies -> 1,329.9 ms for three

    The cost grows not with the number of findings but with
    NEIGHBORHOOD DENSITY: `propose` checks whether the move runs into a
    THIRD body. "Compute three" is a hope, not a ceiling; only time can
    be a ceiling.

    WHAT IT DOES NOT DO. It does not touch the verdict, the stage, the
    order, or the counters — only the move's TEXT and its NAMED source
    (`move_source`). A solver refusal leaves the previous text: a raw
    vector is worse than a minimal one, but better than silence. A
    budget that runs out before the lines do IS COUNTED and rides into
    `Judgement.proposals` — "did not count" must be distinguishable
    from "nothing to give."
    """
    import time as _time

    from dataclasses import replace as _replace

    counts = {"computed": 0, "refused": 0, "skipped_budget": 0,
              "skipped_rung": 0}
    try:
        from kir.clash import resolve as _resolve
    except Exception:  # noqa: BLE001 — the solver ranks below the judgement
        return judged, counts

    targets = []
    for i, j in enumerate(judged):
        if j.rule_id not in _VECTOR_MOVE_RULES:
            continue
        if j.rung not in _RUNGS_ALLOWING_A_NAMED_MOVE:
            # NOT IN SILENCE: "the stage does not allow it" and "the
            # budget ran out" are different facts, and the receipt's
            # reader must be able to tell them apart.
            counts["skipped_rung"] += 1
            continue
        targets.append(i)
    if not targets:
        return judged, counts

    records = [r for r in hulls.values() if getattr(r, "source_id", None)]
    if not records:
        return judged, counts
    hood = _resolve.Neighbourhood(records)

    # A UNIT CONVERSION, NOT A THRESHOLD: the caller's milliseconds into
    # wall-clock seconds. There is no number of its own here — the
    # ceiling is brought in whole by the caller, and
    # `test_the_module_invents_no_depth_threshold_of_its_own` must stay
    # green precisely because there is nothing to set up here.
    deadline = _time.perf_counter() + budget_ms * 1e-3
    out = list(judged)
    for i in targets:
        if _time.perf_counter() >= deadline:
            counts["skipped_budget"] += 1
            continue
        row = out[i]
        a, b = hulls.get(row.a_id), hulls.get(row.b_id)
        if a is None or b is None:
            counts["refused"] += 1
            continue
        try:
            p = _resolve.propose(a, b, hood=hood, pair_kind=row.pair_kind,
                                 finding_id=row.finding_id,
                                 hosted=hosted)
        except Exception:  # noqa: BLE001 — a solver refusal IS DATA
            counts["refused"] += 1
            continue
        if p.chosen is None:
            counts["refused"] += 1
            continue
        # THE LINE IS TAKEN FROM THE RULE'S OWNER, not assembled here: a
        # second phrasing of the same number is a defect with our own
        # name on it.
        out[i] = _replace(row, next_move_ru=_resolve.to_russian(p),
                          move_source="minimal_exit")
        counts["computed"] += 1
    return out, counts


def judge(findings: Iterable[Mapping[str, Any]], *,
          hulls: Mapping[str, Any] | None = None,
          profiles: Mapping[str, Any] | None = None,
          slack: Mapping[str, Any] | None = None,
          ops: Mapping[str, Any] | None = None,
          hosted: Mapping[str, Any] | None = None,
          new_ids: frozenset[str] | None = None,
          propose_budget_ms: float = 0.0) -> Judgement:
    """The detector's findings -> judgements. A pure function, NEVER
    raises.

    `hulls`   — `source_id -> HullRecord` of the already-built snapshot
                (only the Z bounding size is read);
    `profiles`— declared footprint outlines (`BundleGeometry.profiles`);
    `slack`   — the rounding introduced by `clash_bundle`
                (`{"z_mm": t, ...}`);
    `ops`     — `element_id -> op`, the op the element was born from:
                without it the turn can only be invented, and an
                invented turn is worse than silence;
    `hosted`  — THE HOST INDEX, `element_id -> {"host_element_id",
                "host_class", "source"}`. `None` means EXACTLY "did not
                ask" and gives all pairs the state `unknown`; an EMPTY
                dictionary means "asked, there are no hosts" and gives
                `absent`. These two facts are different, and confusing
                them is not allowed in either direction — exactly as
                `journal` distinguishes `sections=None` from
                `sections={}`.

                When `hosted` is not passed but `ops` is, the index is
                built HERE from the program's own words
                (`hosted_from_ops`): no previous caller loses the host
                relation, and additionally gets it QUALIFIED by program
                — see the defect in `hosted_from_ops`'s header.
    """
    hulls = hulls or {}
    profiles = profiles or {}
    slack = slack or {}
    ops = ops or {}
    if hosted is None and ops:
        hosted = hosted_from_ops(ops)

    judged: list[Judged] = []
    by_kind: dict[str, int] = {}
    by_rung: dict[str, int] = {}
    filtered_rule: dict[str, int] = {}
    refused_rule: dict[str, int] = {}
    filtered_slack: dict[str, int] = {}
    by_host: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    justifications: dict[str, str] = {}
    #: A finding by its id — needed by the SECOND pass, which walks the
    #: already-sorted list and does not have the raw finding at hand.
    by_fid: dict[str, Mapping[str, Any]] = {}

    for finding in findings:
        a_id = finding["a"]["source_element_id"]
        b_id = finding["b"]["source_element_id"]
        op_a = ops.get(a_id) or ops.get(_op_key(a_id))
        op_b = ops.get(b_id) or ops.get(_op_key(b_id))
        explains = _slack_explains(finding, hulls, profiles, slack)
        host_state, host_id, host_source = host_relation(a_id, b_id, hosted)
        by_host[host_state] = by_host.get(host_state, 0) + 1
        origin = origin_of(a_id, b_id, new_ids)
        by_origin[origin] = by_origin.get(origin, 0) + 1
        rule_id, refused = _classify(finding, explains, host_state)
        rule = _RULE_BY_ID[rule_id]
        # PROOF STRENGTH IS NOT RAISED a second time. `detect` has
        # already decided `confirmed | possible`; the judgement can
        # only lower it with a named rounding, never turn an OUTER
        # overlap into a fact about bodies.
        proven = _physical_overlap_proof(finding, explains)
        rung = _rung(rule.kind, finding, proven)
        why = rule.why_ru if not refused else REFUSED_RULES[refused]
        item = Judged(
            finding_id=str(finding.get("finding_id") or f"{a_id}~{b_id}"),
            a_id=a_id, b_id=b_id, kind=rule.kind,
            rule_id=refused or rule_id, rung=rung, proven=proven,
            depth_mm=float(finding.get("hull_overlap_depth_mm") or 0.0),
            relation=str(finding.get("hull_relation") or ""),
            pair_kind=str(finding.get("pair_kind") or ""),
            hull_grade=str(finding.get("hull_grade") or ""),
            geometry_verdict=str(finding.get("verdict") or ""),
            physical_overlap_proof=dict(
                finding.get("physical_overlap_proof") or {}),
            a_label=str(finding["a"].get("label") or ""),
            b_label=str(finding["b"].get("label") or ""),
            hull_sources=(str(finding["a"].get("hull_source") or ""),
                          str(finding["b"].get("hull_source") or "")),
            slack=explains,
            text_ru=_text(rule, finding, proven, explains)
            + (f". ПРАВИЛО НЕ НАПИСАНО: `{refused}`" if refused else "")
            + _host_note(host_state, host_id,
                         _same_host(a_id, b_id, hosted)
                         if host_state == "contradicts" else None),
            next_move_ru=_next_move(
                rule_id, finding, explains, op_a, op_b, proven),
            why_ru=why,
            host_state=host_state, declared_host_id=host_id,
            host_source=host_source, origin=origin)
        judged.append(item)
        by_fid[item.finding_id] = finding
        justifications[refused or rule_id] = why
        by_kind[rule.kind] = by_kind.get(rule.kind, 0) + 1
        by_rung[rung] = by_rung.get(rung, 0) + 1
        if refused:
            refused_rule[refused] = refused_rule.get(refused, 0) + 1
        elif _RUNG_ORDER[rung] > _RUNG_ORDER["look"]:
            filtered_rule[rule_id] = filtered_rule.get(rule_id, 0) + 1
        for name in explains:
            filtered_slack[name] = filtered_slack.get(name, 0) + 1

    # THE DISPLAY ORDER. Within one stage, pairs whose rule is REFUSED
    # come first: these are the only lines that answer the question
    # "what is the language missing," and they must not drown in
    # repeated rounding. ONE'S OWN AHEAD OF SOMEONE ELSE'S — WITHIN ONE
    # STAGE AND ONLY WHEN ASKED. The stage remains the senior key: it is
    # a contract about the permissible action, and reordering it by
    # provenance would mean hiding the dangerous behind one's own.
    # Without a turn boundary (`new_ids is None`), all pairs are
    # `unknown`, the key is identically zero, and the order stays BYTE
    # FOR BYTE the same as before.
    _ORIGIN_FIRST = {"both_new": 0, "one_new": 0, "both_prior": 1,
                     "unknown": 0}
    judged.sort(key=lambda j: (_RUNG_ORDER[j.rung],
                               _ORIGIN_FIRST[j.origin],
                               0 if j.rule_id in REFUSED_RULES else 1,
                               -j.depth_mm, j.finding_id))
    # THE SECOND PASS — AFTER sorting, and only by budget. The default
    # of 0 leaves everything BYTE FOR BYTE the same as before: the
    # unknown here means the previous behavior, not a silent
    # improvement.
    proposals: dict[str, int] = {}
    if propose_budget_ms > 0 and hulls:
        # 🔴 THE HOST INDEX RIDES INTO THE SECOND PASS TOO. Measured
        # 25.08: `judge` used it to compute `host_state`, while the
        # move proposal was made BLIND to what the verdict already
        # knew. `propose` without the index NEVER sees `contradicts`
        # and always falls back to the tabular recommendation.
        # resolve.py's header measures the cost: the label-based guess
        # removes 497 pairs, of which 239 (48.1%) are exactly
        # `contradicts`. A door overlapping a wall it does not live in
        # used to get "a node; would separate geometrically" instead of
        # "move it" — even though the SAME `Judged` row already carries
        # a computed `host_state`.
        judged, proposals = _upgrade_moves(
            judged, by_fid, hulls, budget_ms=float(propose_budget_ms),
            hosted=hosted)

    # NAMED, NOT POSITIONAL: `Judgement` has seven counters of the same
    # type `dict[str, int]`, and no type system would catch two of them
    # swapped — only an eye on the numbers in the receipt.
    return Judgement(
        judged=tuple(judged),
        proposals=proposals,
        by_kind=dict(sorted(by_kind.items())),
        by_rung=dict(sorted(by_rung.items())),
        filtered_by_rule=dict(sorted(filtered_rule.items())),
        refused_by_rule=dict(sorted(refused_rule.items())),
        filtered_by_slack=dict(sorted(filtered_slack.items())),
        by_host_state=dict(sorted(by_host.items())),
        by_origin=dict(sorted(by_origin.items())),
        justifications=dict(sorted(justifications.items())))
