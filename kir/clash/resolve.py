"""WHAT TO MOVE, WHERE, AND BY HOW MUCH — a proposal, not a list of pairs.

A detector says "these two intersect". That is not enough for a designer:
they can already see the red. A list becomes an instrument when every
finding names the ELEMENT, the DIRECTION, the DISTANCE, and — necessarily —
whether the move is LEGAL.

WHY A NUMBER IS ALWAYS GIVEN, WHILE A RECOMMENDATION IS NOT ALWAYS. The
first version of this module refused outright as soon as both sides turned
out to be construction (`both_immovable`), and on a live building this gave
3 346 refusals out of 3 348 (`sob62_r23_v5`) and 4 000 out of 4 000
(`snowdon_plumb_v5`) — i.e. the instrument was staying silent exactly where
it was being asked. The refusal was polite but useless: "wall A penetrates
wall B by 120 mm, and to exit it needs 120 mm along +X" is a fact about the
geometry, and there is nothing to hide it for. It is a human who decides
whether to EXECUTE the move; the module's job is not to substitute for that
decision, nor to deprive it of numbers.

Hence there are two DIFFERENT axes here, and they never fold into one:

  A NUMBER        — element, direction, distance, legality. Always present
                    when the geometry provides it, regardless of the sides'
                    classes.
  A RECOMMENDATION — `move` | `review` | `verify_duplicate` |
                    `assembly_relation`. Says what to do with the number,
                    and never pretends to be stronger than the data allows.

HOW THIS DIFFERS FROM `geom.certified_separating_translation`. That
function promises exactly one thing and keeps the promise: after the
transfer, the pair is separated. But it (a) always moves side A, chosen by
ADDRESS ORDER, not by meaning, (b) neither promises nor delivers
minimality — its own docstring says this outright, (c) knows nothing about
third bodies. All three holes are closed here, and not one of them is
closed by guessing.

HOW MUCH HOLE (b) COST — A MEASUREMENT, NOT AN ESTIMATE. The instrument:
600 real overlap findings from `sob62_r23_v5`, decompile of 10.08.2026, the
ratio of the move length of `geom.certified_separating_translation` to the
length of `minimal_exit` on the same pair:

    median    5.892x
    p90      56.667x
    maximum  112 066.5x

A hundred thousand times over is not "suboptimal" — it points to something
else: where a pipe needs only eight millimeters sideways, the previous
vector was carrying it tens of meters upward. The number is recorded HERE
and duplicated by a reference inside
`certified_separating_translation` itself, because writing ends together
with the session, while the code remains.

WHAT THE DECOMPOSE WAVE CHANGED (11.08.2026). The appearance of the
non-convex hull `geom.PrismSet` killed the justification `minimal_exit` had
stood on: for a union of convex pieces, the set of shifts at which the pair
intersects stops being a segment. Measurement before the fix: a slab with
an OPENING against a beam, 400 intersecting pairs — for 92 of them
(23.0 %) bisection was yielding a move longer than the smallest one, in the
worst case by a factor of 6.79. Minimality has been RESTORED by an exact
computation of segments over pairs of pieces, not removed.

AND ONE THING THAT WAS NEVER HERE, ALTHOUGH IT SOUNDED AS IF IT WAS. The
word "smallest" was, and is, relative to a FINITE set of directions
(`_directions`), not to all directions in space. A measurement against a
dense grid of 900 sphere directions: for a prism-prism pair the set is
COMPLETE (0 discrepancies over 120 pairs — both prisms are extruded along
one axis, so the face normals suffice), for a capsule-prism pair it is NOT
complete (60 discrepancies out of 120, a move up to 1.17 times longer than
the smallest). The second half was true even before this wave — nobody had
simply measured it. Now it travels in the finding itself, as the field
`Move.minimality`, rather than in a code comment.

THREE LAWS THE MODULE STANDS ON.

1. CONSTRUCTION DOES NOT YIELD TO ENGINEERING. A pipe routes around a beam;
   a beam does not route around a pipe. This is not a matter of taste or
   norm but the order of assembly: bearing elements are set by
   calculation, services are routed to fit.

2. A SMALLER SECTION YIELDS TO A LARGER ONE. Among themselves, services are
   ranked by CROSS-SECTION AREA from `section_radius_mm` — from that very
   number the capsule is justified by. Where there is no number, there is
   nothing to compare, and the order is decided by class; this is stated by
   the `rank_basis` field, not hidden in a default.

3. MINIMALITY IS PROVEN, NOT DECLARED. The set
   `{t : (A + t·d) ∩ B ≠ ∅}` for CONVEX bodies is a SEGMENT, so the
   smallest `t` that takes the pair out of intersection is found by
   bisection and requires no faith. All three of the module's hulls are
   convex, so the condition holds by construction, not "usually". The
   found move is CHECKED by the postcondition `geom.separates` — the same
   one `geom` uses to check itself.

WHAT IS NOT HERE. Building code, slopes, service zones, hanger rules. They
are not in the data, and inventing them would mean signing an axis that
nobody read.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from kir.clash import geom as G
from kir.clash import hulls as H
from kir.clash.spatial_index import SpatialIndex

__all__ = (
    "RESOLVE_SCHEMA",
    "RECOMMENDATIONS",
    "HOST_STATE_NOTES",
    "IMMOVABLE",
    "MOVE_CLASS",
    "RIDES_WITH_RUN",
    "ASSEMBLY_PAIRS",
    "LEGALITY_BLOCKERS",
    "RANK_BASIS",
    "Move",
    "Proposal",
    "Neighbourhood",
    "mobility_of",
    "minimal_exit",
    "exit_is_exact",
    "MINIMALITY",
    "MINIMALITY_NOTE",
    "MAX_EXIT_PIECE_PAIRS",
    "propose",
    "to_russian",
)

RESOLVE_SCHEMA = "kir-clash-resolution/3"

#: What to do with the number. A closed list: a recommendation outside it
#: is exactly the unsigned axis all of this was written against.
RECOMMENDATIONS: dict[str, str] = {
    "move": "исполняйте: сторона, которая уступает, определена порядком сборки",
    "review": "решает человек: обе стороны — конструкция, и её положение "
              "назначено расчётом, а не этим отчётом",
    "verify_duplicate": "геометрия похожа на дубликат, но удаление запрещено "
                        "до отдельного доказательства семантической и "
                        "dependency-эквивалентности",
    "assembly_relation": "это УЗЕЛ, а не ошибка: дверь в стене, панель в "
                         "витраже. Число дано для проверки, ход не назначается",
}

#: WHAT THE DATA SAID ABOUT THE HOST — a closed dictionary, word for word
#: the same as `kir.clash_judgement.HOST_STATES`. There is no second
#: definition here, and there must not be one: the state is COMPUTED by
#: `clash_judgement.host_relation`, and this dictionary only translates it
#: for the report's reader.
#:
#: WHY IT IS HERE (measurement of 18.08.2026, decompile of `sob62_r23_v5`,
#: 1 510 elements, 3 759 findings, instrument — a live run of `detect` +
#: `_recommendation`): the label guess `ASSEMBLY_PAIRS` resolves **497**
#: pairs, while `L0Element.host_id` confirms only **184**. The rest breaks
#: down into NOT JUST ONE PILE, and that is the whole point of the fix:
#:
#:     confirms     184  (37.0 %)  the data CONFIRMS the joint
#:     contradicts  239  (48.1 %)  a host IS DECLARED AND IT IS A DIFFERENT
#:                                 ELEMENT
#:     absent        74  (14.9 %)  the index exists, nobody declared a host
#:
#: The canon's earlier record ("313 of 497 = 63.0 % against the data") was
#: adding `contradicts` to `absent` together — i.e. "the data OBJECTS"
#: together with "the data STAYS SILENT". The number 63.0 % is reproduced
#: (239+74=313) and remains true as "resolved NOT BY CONFIRMATION", but only
#: `contradicts` is entitled to overturn the table.
HOST_STATE_NOTES: dict[str, str] = {
    "confirms": "одна сторона объявила ДРУГУЮ своим хозяином: узел подтверждён "
                "данными, а не догадкой по паре ярлыков",
    "contradicts": "хозяин объявлен, и это НЕ вторая сторона пары: элемент "
                   "перекрывает то, в чём не живёт — узлом это не является",
    "host_out_of_scope": "хозяин объявлен, но его нет в извлечении (связанный "
                         "файл либо датум): это граница НАШЕГО чтения, а не "
                         "вина автора — узел не опровергнут",
    "absent": "индекс хозяев есть, ни одна сторона хозяина не объявила: про "
              "хозяина сказать нечего. Это НЕ доказательство узла",
    "unknown": "индекса хозяев не подавали — никто не спрашивал",
}


# ═════════════════════════════════════════════════════════════ 1. WHO YIELDS

#: The `hulls.KIND_TABLE` labels that do not move according to the geometry
#: report.
IMMOVABLE = frozenset({
    "wall", "floor", "roof", "column", "beam", "foundation",
    "curtain_panel", "mullion", "curtain_system", "stairs", "ramp",
    "ceiling", "truss", "door", "window", "railing",
})

#: The mobility class: the LARGER the number, the more readily the element
#: yields.
MOVE_CLASS: dict[str, int] = {
    "duct": 1, "duct_insulation": 1, "duct_lining": 1,
    "tray": 2,
    "pipe": 3, "pipe_insulation": 3,
    "conduit": 4,
}

#: Travel ALONG WITH their section of the run, not on their own: proposing
#: to move a tee separately from the pipe means proposing to tear the
#: network apart.
RIDES_WITH_RUN = frozenset({
    "pipe_fitting", "duct_fitting", "tray_fitting", "conduit_fitting",
    "pipe_accessory", "duct_accessory", "duct_terminal", "sprinkler",
})

#: Pairs of labels whose intersection is a METHOD OF ASSEMBLY, not a
#: conflict. The list is closed and contains only what a designer will
#: confirm without opening a code book: a door lives IN a wall, a panel and
#: a mullion live IN a curtain wall, a railing stands ON a stair. No move
#: is assigned here, but the number is published: a joint that has come
#: apart by half a meter is no longer a joint.
ASSEMBLY_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"door", "wall"}),
    frozenset({"window", "wall"}),
    frozenset({"door", "curtain_panel"}),
    frozenset({"window", "curtain_panel"}),
    frozenset({"mullion", "curtain_panel"}),
    frozenset({"mullion", "curtain_system"}),
    frozenset({"curtain_panel", "curtain_system"}),
    frozenset({"mullion", "wall"}),
    frozenset({"curtain_panel", "wall"}),
    frozenset({"railing", "stairs"}),
    frozenset({"railing", "floor"}),
    frozenset({"stairs", "floor"}),
})

#: Named reasons for which a move is ILLEGAL. The list is closed: a move
#: without a verdict is the same silence this module cures.
LEGALITY_BLOCKERS: dict[str, str] = {
    "hits_third_body": "после переноса элемент входит в ТРЕТЬЕ тело, с "
                       "которым до переноса не пересекался",
    "leaves_level_band": "перенос выводит элемент за пределы его собственного "
                         "этажа",
    "exceeds_budget": "перенос больше бюджета: это перекладка участка, а не "
                      "правка примыкания",
    "uncertified": "постусловие `geom.separates` не подтвердило разведение",
}

#: The move's budget. Beyond the element's own bounding box, a transfer
#: stops being an adjustment of an abutment and becomes a re-routing, which
#: cannot be assigned from a single geometry report.
BUDGET_FACTOR = 3.0
BUDGET_FLOOR_MM = 300.0

#: The limit on cells per hull lives with the HULLS: `detect.py` computes
#: the same quantity by the same arithmetic, and a second copy would
#: diverge silently.
MAX_CELLS_PER_HULL = H.MAX_CELLS_PER_HULL


def mobility_of(rec: H.HullRecord) -> tuple[int, float, str]:
    """(mobility class, cross-section area, what decided it). Larger means
    more mobile."""
    label = rec.label or ""
    if label in RIDES_WITH_RUN:
        return (0, 0.0, "rides_with_run")
    cls = MOVE_CLASS.get(label)
    if cls is None:
        return (0, 0.0, "immovable" if label in IMMOVABLE else "label_outside_table")
    r = rec.section_radius_mm
    if isinstance(r, (int, float)) and math.isfinite(r) and r > 0:
        return (cls, math.pi * float(r) * float(r), "section_radius_mm")
    return (cls, 0.0, "class_only")


#: What DECIDED the pair's order. The list is closed: the basis is part of
#: the finding, and a default here would be the same silence this module
#: cures.
#: 🔴 The value is a property of the PAIR, not of a single record: see
#: `_decide`.
RANK_BASIS: dict[str, str] = {
    "move_class": "решил КЛАСС: одна сторона — не сеть (конструкция, узел "
                  "трассы либо метка вне таблицы), и закон 1 отдаёт ход сети",
    "section_radius_mm": "решила ПЛОЩАДЬ СЕЧЕНИЯ: обе стороны сети, у обеих "
                         "сечение известно, и меньшее уступает большему",
    "class_only": "решил КЛАСС при равных либо НЕИЗВЕСТНЫХ сечениях: "
                  "сравнивать по площади нечем, и это сказано, а не спрятано",
    "source_id": "решил АДРЕС: класс и сечение неразличимы, порядок взят "
                 "детерминированным, чтобы находка не плавала между прогонами",
}


def _decide(a: H.HullRecord,
            b: H.HullRecord) -> tuple[H.HullRecord, H.HullRecord, str]:
    """(who yields, who stays, WHAT decided it). The basis is a property of
    the PAIR.

    🔴 LAW 2 WAS BEING READ BACKWARDS BY THE CODE (F-145, 30.08.2026).
    `MOVE_CLASS` contains ONLY services — `duct` 1, `tray` 2, `pipe` 3,
    `conduit` 4; construction does not enter it at all and gets class 0 via
    `IMMOVABLE`. So comparing classes FIRST was deciding BY CLASS exactly
    where law 2 requires AREA: "among themselves, services are ranked by
    cross-section area". Measurement across the corpus: 35 real
    cross-class findings on 5 of 81 buildings, and in 24 of them the LARGER
    section was yielding — a pipe of r=100 was getting out of the way of a
    pipe of r=10.

    Class is compared first only where it does mean law 1: when ONE side is
    not a service. Between two services it falls back to the reserve
    basis, as the law says.

    🔴 AND THE BASIS WAS LYING IN ALL 35. `rank_basis` was taken from ONE
    record (`mobility_of(mover)[2]`), where it means "what THIS hull is
    justified by". A record may honestly carry `section_radius_mm` and
    still not be what decided the ORDER. So the basis is returned by
    whoever actually made the ordering decision.

    🔴 A MISSING SECTION IS NO LONGER TREATED AS THE SMALLEST. `mobility_of`
    returns an area of `0.0` for it, and the previous `aa != ab` was
    ranking an unmeasured element as the thinnest — i.e. forcing to yield
    the one about whom there is nothing to say. The law answers this case
    directly: "where there is no number, there is nothing to compare".
    Area decides only when it is known to BOTH sides.
    """
    ca, aa, _ = mobility_of(a)
    cb, ab, _ = mobility_of(b)
    if (ca == 0) != (cb == 0):
        return (a, b, "move_class") if ca > cb else (b, a, "move_class")
    if aa > 0.0 and ab > 0.0 and aa != ab:
        return ((a, b, "section_radius_mm") if aa < ab
                else (b, a, "section_radius_mm"))
    if ca != cb:
        return (a, b, "class_only") if ca > cb else (b, a, "class_only")
    return ((a, b, "source_id") if a.source_id <= b.source_id
            else (b, a, "source_id"))


def _order(a: H.HullRecord, b: H.HullRecord) -> tuple[H.HullRecord, H.HullRecord]:
    """(who yields, who stays). What decided it is in `_decide`."""
    mover, fixed, _ = _decide(a, b)
    return mover, fixed


def _recommendation(a: H.HullRecord, b: H.HullRecord, pair_kind: str,
                    host_state: str | None = None) -> str:
    """What to do with the pair. `host_state` is a verdict OF THE DATA, not
    a guess.

    🔴 EXACTLY ONE STATE OVERTURNS THE LABEL TABLE — `contradicts`. This is
    not timidity, it is an asymmetric cost, and it has been measured:

    * `contradicts` — the host IS KNOWN and it is a different element. A
      strong assertion, and it directly contradicts the "joint": the door
      overlaps a wall it does not live in. The pair must return among the
      findings;
    * `absent` / `host_out_of_scope` / `unknown` — the data STAYS SILENT.
      Letting them overturn the table would mean printing "move the door
      …" in a case where we simply did not read the host: in this
      decompile, `host_id` exists for only 12.5% of elements (189 of
      1 510). Here, unlike `clash_judgement`, there is NO ladder of tiers
      that catches the unproven: the `to_russian` string prints the VERB
      immediately. On exactly this seam, the session of 17.08 had already
      shipped a destructive instruction to prod based on an unproven
      finding (`9e9a43bf`, fixed by `95bc2fcd`).

    The asymmetry with `clash_judgement` (there `absent` also does not
    excuse, but neither does it stay silent — a tier catches it) is named
    here deliberately, not smoothed over.
    """
    if host_state == "contradicts":
        # The data OBJECTS: the joint is refuted, mobility decides from
        # here.
        ca, _, _ = mobility_of(a)
        cb, _, _ = mobility_of(b)
        if pair_kind == "coincident_duplicate":
            return "verify_duplicate"
        return "review" if (ca == 0 and cb == 0) else "move"
    return _recommendation_by_table(a, b, pair_kind)


def _recommendation_by_table(a: H.HullRecord, b: H.HullRecord,
                             pair_kind: str) -> str:
    if pair_kind == "coincident_duplicate":
        # Geometry answers only whether the occupied bodies coincide.  It says
        # nothing about phases, design options, systems, groups, ownership or
        # dependants.  Those are exactly the facts that decide whether either
        # BIM element may be deleted.  Keep the duplicate class visible, but
        # never mint a destructive recommendation from this geometry-only API.
        return "verify_duplicate"
    if frozenset({a.label or "", b.label or ""}) in ASSEMBLY_PAIRS:
        return "assembly_relation"
    ca, _, _ = mobility_of(a)
    cb, _, _ = mobility_of(b)
    if ca == 0 and cb == 0:
        return "review"
    return "move"


# ═════════════════════════════════════ 2. THE SMALLEST MOVE ALONG A DIRECTION

def _unit(v: Sequence[float]) -> tuple[float, float, float] | None:
    L = math.sqrt(sum(c * c for c in v))
    if L <= G.EPS_MM:
        return None
    return (v[0] / L, v[1] / L, v[2] / L)


def _span(h: G.Hull) -> float:
    lo, hi = G.hull_bounds(h)
    return max(hi[k] - lo[k] for k in range(3)) or 1.0


#: The ceiling on the number of piece-pairs in a single exit search. The
#: exact path costs O(m*n*edges), and for a pair of unions this is the only
#: quantity able to grow without bound. Beyond the ceiling there is a
#: NAMED fallback to bisection marked `separating_only`, not a silent
#: coarsening: a silent degradation here would be indistinguishable from
#: an answer. Measurement of 11.08.2026 across the corpus: median number
#: of footprint pieces 27, maximum 63, the worst pair of unions gives
#: 63*63 = 3 969 pairs — a ceiling of 4 096 lets it through, while a
#: degenerate contour with hundreds of pieces does not.
MAX_EXIT_PIECE_PAIRS = 4096

#: How many THIRD BODIES are named by identifier in the proposal. The
#: ceiling here is not about correctness but about LINE LENGTH: the list
#: travels in the receipt, and it is a human who reads it — eighty
#: identifiers in a row are not useful, they are noise.
#:
#: 🔴 THE BODY COUNT ITSELF IS ALWAYS COMPUTED and published as
#: `Move.hits_total` (F-147, 30.08.2026). Previously the number eight stood
#: as a literal right in the condition and was cutting off the COUNT
#: together with the printout: a designer would read "(bodies: e0…e7)" and
#: understand "eight", while there could in fact be 357 — measured across
#: the corpus, 77 buildings, the building `k4_geom_wave2`. A ceiling on
#: PRINTING is legitimate; a ceiling on the COUNT, passed off as the full
#: count, is not. A neighboring module already holds the same law:
#: `review.build_review` names a truncation with the field
#: `elements_truncated_to`, "a truncated list that looks complete is the
#: same lie as a silent zero".
MAX_NAMED_HITS = 8

#: HOW the published move was obtained. A separate axis from `certified`:
#: "the transfer separates" and "the transfer is the smallest" are
#: different assertions, and gluing them into one field would mean
#: repeating the defect that review #14 removed.
MINIMALITY = (
    #: Along EVERY direction examined, `t` was computed exactly (the right
    #: end of the zero component), not groped for. The minimum is taken
    #: over a FINITE set of directions — it is not the global minimum over
    #: the space.
    "minimal_over_searched_directions",
    #: The exact path is inapplicable (a capsule against a union, or the
    #: piece-pair ceiling). The move DOES SEPARATE, and this is checked by
    #: transfer, but it is not required to be the smallest even along its
    #: own direction.
    "separating_only",
)


#: What each value of `Move.minimality` means — in the report itself, not
#: in a code comment. A reader of the report never reaches the code, and
#: the difference between "the smallest of those examined" and "the
#: smallest at all" decides whether to trust the number as a design
#: decision.
MINIMALITY_NOTE: dict[str, str] = {
    "minimal_over_searched_directions": (
        "вдоль КАЖДОГО просмотренного направления величина хода вычислена "
        "ТОЧНО (правый конец компоненты нуля в замкнутой форме, а не "
        "бисекцией), и проверена переносом. Минимум взят по КОНЕЧНОМУ набору "
        "направлений: оси, нормали граней всех кусков обеих оболочек и "
        "сертифицированный ход geom. Глобальным минимумом по всем "
        "направлениям пространства это НЕ является — замер 11.08.2026: для "
        "пары призма-призма набор полон (0 расхождений на 120 парах против "
        "сетки из 900 направлений), для пары капсула-призма НЕ полон "
        "(60 расхождений из 120, до 1.17 раза длиннее)."),
    "separating_only": (
        "ход РАЗВОДИТ пару, и это проверено переносом, но наименьшим он не "
        "объявлен даже вдоль своего направления: точный путь неприменим "
        "(капсула против объединения кусков либо превышен потолок "
        "MAX_EXIT_PIECE_PAIRS), и величина получена бисекцией, которая у "
        "невыпуклого тела сходится к концу СВОЕЙ компоненты."),
}


def _shift_interval(c: float, lo_a: float, hi_a: float,
                    lo_b: float, hi_b: float) -> tuple[float, float] | None:
    """The set of `t` for which the segment `[lo_a, hi_a]`, shifted by
    `t*c`, intersects `[lo_b, hi_b]`. A segment, or empty.

    The condition for two segments to intersect is LINEAR in `t`, so it is
    solved exactly: `lo_a + t*c <= hi_b` and `lo_b <= hi_a + t*c`. At
    `c = 0` there is no shift along this axis at all, and the answer is
    either "always" or "never".
    """
    if c == 0.0:
        return (-math.inf, math.inf) if (lo_a <= hi_b and lo_b <= hi_a) else None
    t1 = (hi_b - lo_a) / c
    t2 = (lo_b - hi_a) / c
    return (t1, t2) if t1 <= t2 else (t2, t1)


def _piece_exit_interval(fa, za, fb, zb, u) -> tuple[float, float] | None:
    """The set of `t` for which A PAIR OF CONVEX PRISMS intersects. EXACT.

    A prism is the Cartesian product of a convex polygon and a segment
    along the same axes, so the intersection condition splits into two
    independent ones: along XY and along Z. For XY, by the separating-axis
    theorem, the edge normals of both CONVEX polygons suffice. Along each
    axis the condition is linear in `t` and yields a segment; the sought
    set is their intersection, i.e. also a segment.

    This is strictly better than the bisection the wave's plan assumed: the
    answer is EXACT rather than converging over `iters` steps, the cost is
    fixed, and the number of iterations stops affecting the published
    value.
    """
    lo, hi = -math.inf, math.inf
    iv = _shift_interval(u[2], za[0], za[1], zb[0], zb[1])
    if iv is None:
        return None
    lo, hi = max(lo, iv[0]), min(hi, iv[1])
    axes = G._poly_axes(fa) + G._poly_axes(fb)
    if not axes:
        axes = [(1.0, 0.0), (0.0, 1.0)]
    for n in axes:
        amin, amax = G._project(fa, n)
        bmin, bmax = G._project(fb, n)
        iv = _shift_interval(u[0] * n[0] + u[1] * n[1], amin, amax, bmin, bmax)
        if iv is None:
            return None
        lo, hi = max(lo, iv[0]), min(hi, iv[1])
        if lo > hi:
            return None
    return (lo, hi) if lo <= hi else None


def _exact_exit_candidates(mover: G.Hull, fixed: G.Hull,
                           u: tuple[float, float, float]) -> list[float] | None:
    """The right ends of the intersection segments over all piece-pairs.
    `None` — not possible.

    The smallest exit must be a RIGHT END of one of these segments: a union
    of segments has a boundary only at their ends, and the exact supremum
    of the component containing zero is one of the right ends. So the
    candidates are examined IN ASCENDING ORDER, and it is the CHECK BY
    TRANSFER on the real bodies that decides: there is no need to merge
    segments into components by hand, and a merging error is therefore
    impossible in principle.
    """
    fa, fb = G.footprint_pieces(mover), G.footprint_pieces(fixed)
    za, zb = G.z_span(mover), G.z_span(fixed)
    if fa is None or fb is None or za is None or zb is None:
        return None                      # a capsule: there is no exact path yet
    if len(fa) * len(fb) > MAX_EXIT_PIECE_PAIRS:
        return None
    out: list[float] = []
    for pa in fa:
        for pb in fb:
            iv = _piece_exit_interval(pa, za, pb, zb, u)
            if iv is None:
                continue
            if math.isinf(iv[1]):
                return None              # there is no exit along this direction
            if iv[1] >= 0.0:
                out.append(iv[1])
    return sorted(set(out))


def _bisect_exit(mover, fixed, u, iters, ceiling):
    """The previous bisection. The answer is CHECKED by transfer,
    minimality is not promised."""
    reach = _span(mover) + _span(fixed)
    hi = max(1.0, reach * 0.05)
    ok = False
    for _ in range(40):
        if G.separates(mover, fixed, tuple(c * hi for c in u)):
            ok = True
            break
        if ceiling is not None and hi > ceiling:
            return None
        hi *= 2.0
        if hi > reach * 8.0:
            return None
    if not ok:
        return None
    lo = 0.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if G.separates(mover, fixed, tuple(c * mid for c in u)):
            hi = mid
        else:
            lo = mid
    return hi


def minimal_exit(mover: G.Hull, fixed: G.Hull, d: Sequence[float], *,
                 iters: int = 50, ceiling: float | None = None) -> float | None:
    """The smallest `t >= 0` for which `mover + t*d` is separated from
    `fixed`.

    THE EARLIER JUSTIFICATION WAS TRUE AND STOPPED BEING APPLICABLE. It
    used to read: "for convex bodies, the set of `t` at which the pair
    intersects is a SEGMENT; all three of the module's hulls are convex,
    so bisection converges to its right end". The first half is true (this
    is the projection onto `d` of the convex Minkowski difference), the
    second died together with the appearance of `geom.PrismSet`: for a
    UNION of pieces, the set splits into a union of up to `m*n` segments
    WITH GAPS. The bracket `[0, hi]` can span an entire gap, and then
    bisection converges to the right end of a FOREIGN component, i.e. to a
    move LONGER than the smallest one.

    MEASUREMENT TAKEN BEFORE THE FIX (11.08.2026, `w1_exit_probe.py`): a
    slab with an OPENING against a beam, 400 intersecting pairs — for 92 of
    them (23.0 %) bisection was yielding a move longer than the smallest
    one, in the worst case by a factor of 6.79. The pipe exits INTO THE
    OPENING long before it leaves the slab, and the bisection bracket was
    spanning the opening entirely.

    Minimality here has been RESTORED, not removed: for the prism family,
    each segment is computed EXACTLY in closed form
    (`_piece_exit_interval`), and the answer is the smallest of the right
    ends that HAS PASSED the check by transfer. The check is mandatory — it
    turns reasoning about components into a demonstrated fact.

    What is NOT promised, and why — see `MINIMALITY`: the minimum is taken
    over a FINITE set of directions (`_directions`), and it is not the
    global minimum over all directions in space.
    """
    u = _unit(d)
    if u is None:
        return None
    if G.separates(mover, fixed, (0.0, 0.0, 0.0)):
        return 0.0
    cands = _exact_exit_candidates(mover, fixed, u)
    if cands is not None:
        for t in cands:
            if ceiling is not None and t > ceiling:
                return None              # the list is sorted: further on it only gets worse
            if G.separates(mover, fixed, tuple(c * t for c in u)):
                return t
        # Not one candidate separated the pair — the model of the set
        # diverged from the geometry. Staying silent is not allowed, nor is
        # inventing an answer: we fall back to bisection, which checks its
        # own answer by transfer.
    return _bisect_exit(mover, fixed, u, iters, ceiling)


def exit_is_exact(mover: G.Hull, fixed: G.Hull) -> bool:
    """Whether MINIMALITY along a direction is provable for this pair of
    hulls."""
    fa, fb = G.footprint_pieces(mover), G.footprint_pieces(fixed)
    if fa is None or fb is None:
        return False
    return len(fa) * len(fb) <= MAX_EXIT_PIECE_PAIRS


def _directions(mover: G.Hull, fixed: G.Hull) -> list[tuple[float, float, float]]:
    """Candidate directions. The SMALLEST move wins, not the first one
    found.

    WHY THE NORMALS ARE TAKEN FROM ALL PIECES. The earlier code was asking
    for them via `isinstance(pf, G.Prism)`, so `PrismSet` yielded NOT A
    SINGLE normal and was left with the six coordinate axes. For a floor
    decomposed into 27 pieces, this discarded every real exit direction —
    exactly the ones along which the exit turns out to be short.

    WHAT THIS SET DOES NOT GIVE, AND THIS IS MEASURED, NOT ASSUMED. For two
    convex bodies, the truly smallest transfer runs along the normal of a
    face of the Minkowski difference, and its faces are generated by the
    faces of the summands AND BY CROSS PRODUCTS OF PAIRS OF EDGES.
    Measurement of 11.08.2026 (`w1_exit_probe.py`), the minimum over this
    set against a dense grid of 900 sphere directions:

      * prism against prism — 120 intersecting pairs, ZERO discrepancies.
        And this is not luck: both prisms are extruded along ONE Z axis,
        so their Minkowski difference is again a prism along Z, and its
        faces are exactly the normals of the footprint edges plus plus/minus
        Z. The set is COMPLETE for this case;
      * capsule against prism — 120 pairs, 60 discrepancies (50.0 %), a
        move up to 1.17 times longer than the smallest. A capsule has no
        "faces" at all, and the closest point routinely lies on the
        rounding.

    The second point is not a defect of this wave, it was here before it
    too; the wave merely produced it as a number. Hence `Move.minimality`
    calls the thing by its own name (`minimal_over_searched_directions`),
    and `directions_searched` publishes the denominator.
    """
    out: list[tuple[float, float, float]] = [
        (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)]
    seen = set(out)

    def offer(v):
        u = _unit(v)
        if u is not None:
            # Rounding to 9 digits is not cosmetic: a floor of 27 pieces has
            # hundreds of nearly coincident normals, and without merging,
            # the set grows together with the decomposition, and with it
            # the cost of the search.
            key = tuple(round(c, 9) for c in u)
            if key not in seen:
                seen.add(key)
                out.append(u)

    for pr in G._as_prisms(fixed):
        for n, _d in G._halfspaces(pr):
            offer(n)
    for pr in G._as_prisms(mover):
        for n, _d in G._halfspaces(pr):
            offer((-n[0], -n[1], -n[2]))
    v = G.certified_separating_translation(mover, fixed)
    if v is not None:
        offer(v)
    return out

# ═════════════════════════════════════════════════════════ 3. IS THE MOVE LEGAL

@dataclass(frozen=True)
class Move:
    element_id: str
    label: str
    category: str
    direction: tuple[float, float, float]
    distance_mm: float
    vector_mm: tuple[float, float, float]
    #: The postcondition `geom.separates` is checked HERE, not promised.
    certified: bool
    legal: bool
    blockers: tuple[str, ...] = ()
    hits: tuple[str, ...] = ()
    #: 🔴 HOW MANY THIRD BODIES WERE FOUND IN TOTAL (F-147, 30.08.2026).
    #: `len(hits)` is how many are NAMED, and these are different numbers:
    #: names are truncated by `MAX_NAMED_HITS` for the sake of line length,
    #: while the count is truncated by nothing. Measurement across the
    #: corpus (77 buildings): 2 196 pairs on 53 buildings carry more than
    #: eight, maximum 357. "There are more" and "there are 349 more" are
    #: different facts for a decision: the first says "the list is
    #: incomplete", the second says "this move is hopeless, look for
    #: another one". Hence A NUMBER, not a flag; the flag next to it
    #: answers the first question without arithmetic.
    hits_total: int = 0
    #: The list of names is truncated by the `MAX_NAMED_HITS` ceiling.
    hits_truncated: bool = False
    rank_basis: str = ""
    #: HOW STRONG this move is as a MINIMUM. A separate axis from
    #: `certified`, and they are kept apart because gluing "separates"
    #: together with "smallest" is exactly the defect that review #14
    #: removed from `verdict`/`hull_grade`. The values are `MINIMALITY`.
    minimality: str = "separating_only"
    #: The denominator for the word "smallest": how many directions were
    #: examined. Without it, `minimal_over_searched_directions` is a word
    #: with no number.
    directions_searched: int = 0
    #: Where these directions came from. The reader must be able to see
    #: that the set is FINITE and exactly what generated it.
    direction_basis: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        def r(x):
            return G._norm_zero(round(float(x), 3))

        #: 🔴 A FOURTH INSTANCE OF THE SAME CLASS, FOUND WHILE FIXING
        #: F-088/F-028/F-148 (29.08.2026), and it was not in the registry.
        #: The `certified` field promises `geom.separates(a, b, vector_mm)`,
        #: checked against `geom.SEP_EPS_MM = 1e-6`. Rounding to 0.001 mm
        #: was voiding this promise: a certified move of (-0.0004, 0, 0)
        #: was being published as `vector_mm: [0, 0, 0]`,
        #: `distance_mm: 0.0` — while at the same time `certified: true`,
        #: i.e. the machine-readable receipt was asserting that a ZERO
        #: transfer separates the pair. `direction` is rounded by the same
        #: step, otherwise a reader who multiplies direction by distance
        #: would not get the published `vector_mm`. The nine digits are
        #: taken from `detect.Finding.as_dict.rsd`, not assigned anew: the
        #: same threshold, the same justification, the same three orders of
        #: magnitude of margin. The remaining fields are still rounded as
        #: before — they carry no certificate.
        def rcert(x):
            return G._norm_zero(round(float(x), 9))
        return {"element_id": self.element_id, "label": self.label,
                "category": self.category,
                "direction": [rcert(c) for c in self.direction],
                "distance_mm": rcert(self.distance_mm),
                "vector_mm": [rcert(c) for c in self.vector_mm],
                "certified": self.certified, "legal": self.legal,
                "blockers": list(self.blockers), "hits": list(self.hits),
                # `hits` remains the same key with the same meaning
                # ("named"); two fields are ADDED, not one previous one is
                # touched.
                "hits_total": self.hits_total,
                "hits_truncated": self.hits_truncated,
                "rank_basis": self.rank_basis,
                "minimality": self.minimality,
                "minimality_note": MINIMALITY_NOTE.get(self.minimality, ""),
                "directions_searched": self.directions_searched,
                "direction_basis": list(self.direction_basis)}


@dataclass(frozen=True)
class Proposal:
    finding_id: str
    recommendation: str
    chosen: Move | None
    alternative: Move | None = None
    refusal: str | None = None
    #: What the DATA said about the pair's host. `None` — the index was not
    #: supplied, and this is a fifth state, distinct from `unknown` in
    #: exactly this: it was not even asked about at the input. The field is
    #: DELIBERATELY SEPARATE from `recommendation`: the closed dictionary of
    #: recommendations must not be touched (other checks stand on it), and
    #: silently mixing a new value into the old axis is this tree's own
    #: named defect.
    host_state: str | None = None

    def as_dict(self) -> dict:
        return {"schema": RESOLVE_SCHEMA,
                "finding_id": self.finding_id,
                "recommendation": self.recommendation,
                "recommendation_note": RECOMMENDATIONS.get(self.recommendation, ""),
                "chosen": None if self.chosen is None else self.chosen.as_dict(),
                "alternative": (None if self.alternative is None
                                else self.alternative.as_dict()),
                "refusal": self.refusal,
                "host_state": self.host_state,
                "host_state_note": ("" if self.host_state is None
                                    else HOST_STATE_NOTES.get(
                                        self.host_state, "")),
                }


class Neighbourhood:
    """Who else stands nearby — so that the move does not drive the element
    into a third body."""

    def __init__(self, records: Sequence[H.HullRecord], cell: float | None = None):
        # ``cell or default`` was this class's historical contract; we
        # keep it for cell=0 and the previous 2000 mm for an empty set, but
        # the construction itself is no longer duplicated.
        record_tuple = tuple(records)
        chosen_cell = cell or (2000.0 if not record_tuple else None)
        self._index = SpatialIndex(
            record_tuple, cell=chosen_cell,
            max_cells_per_hull=MAX_CELLS_PER_HULL,
            upper_median=True)
        self.records = list(self._index.records)
        self.cell = self._index.cell
        self.buckets = self._index.buckets
        self.giants = self._index.giants

    def near(self, lo, hi) -> set[int]:
        return self._index.query_bounds(lo, hi)


def _bounds_overlap_record(lo, hi, record: H.HullRecord) -> bool:
    """An independent cheap screen for the final linear witness.

    The function deliberately does not import the AABB predicate
    ``SpatialIndex``: an error in the shared implementation must not both
    remove a candidate and confirm the absence of a third body.
    """
    other_lo, other_hi = record.bounds()
    return all(lo[axis] <= other_hi[axis] and other_lo[axis] <= hi[axis]
               for axis in range(3))


def _level_band(rec: H.HullRecord, levels: Mapping[str, float] | None
                ) -> tuple[float, float] | None:
    """The band of the element's own floor. `None` — there is nothing to
    judge by, and this is NOT a verdict."""
    if not levels or rec.level_id is None:
        return None
    key = str(rec.level_id)
    if key not in levels:
        return None
    base = float(levels[key])
    above = sorted(float(e) for e in levels.values() if float(e) > base + 1.0)
    return base, (above[0] if above else base + 100000.0)


def _already_hit(rec: H.HullRecord, hood: Neighbourhood | None) -> set[str]:
    """Whom the element intersects with BEFORE the move: the move is not
    answerable for this."""
    if hood is None:
        return set()
    out: set[str] = set()
    lo, hi = rec.bounds()
    # This is part of the postcondition, not a search for the UI: a full
    # pass rules out a common failure mode of false negatives shared with
    # the final-move index.
    for o in hood.records:
        if o.source_id == rec.source_id:
            continue
        if not _bounds_overlap_record(lo, hi, o):
            continue
        if G.signed_distance(rec.hull, o.hull) < -G.SEP_EPS_MM:
            out.add(o.source_id)
    return out


def _build_move(mover: H.HullRecord, fixed: H.HullRecord,
                hood: Neighbourhood | None, levels, basis: str) -> Move | None:
    best_t: float | None = None
    best_d: tuple[float, float, float] | None = None
    dirs = _directions(mover.hull, fixed.hull)
    for d in dirs:
        t = minimal_exit(mover.hull, fixed.hull, d, ceiling=best_t)
        if t is None:
            continue
        if best_t is None or t < best_t - 1e-9 or (
                abs(t - best_t) <= 1e-9 and (best_d is None or d < best_d)):
            best_t, best_d = t, d
    if best_t is None or best_d is None:
        return None
    vec = tuple(c * best_t for c in best_d)
    moved = G.translate(mover.hull, vec)
    certified = G.signed_distance(moved, fixed.hull) >= -G.SEP_EPS_MM
    blockers: list[str] = []
    hits: list[str] = []
    hits_total = 0
    if not certified:
        blockers.append("uncertified")
    budget = max(BUDGET_FLOOR_MM, BUDGET_FACTOR * _span(mover.hull))
    if best_t > budget:
        blockers.append("exceeds_budget")
    if hood is not None:
        already = _already_hit(mover, hood)
        lo, hi = G.hull_bounds(moved)
        # The final verdict cannot depend on the same index that supplied
        # the candidates.  We linearly scan all bodies relevant by an
        # independent AABB and only then call the exact geometry.
        for other in hood.records:
            if other.source_id in (mover.source_id, fixed.source_id):
                continue
            if other.source_id in already:
                continue
            if not _bounds_overlap_record(lo, hi, other):
                continue
            if G.signed_distance(moved, other.hull) < -G.SEP_EPS_MM:
                # 🔴 `break` REMOVED (F-147): it was cutting off not the
                # printing but the COUNT. The cost of removing it is named
                # as a number in the commit message and is small by
                # construction — the extra counting costs additional calls
                # ONLY for pairs that reached the ceiling, while the rest
                # were already scanning the whole neighborhood anyway.
                hits_total += 1
                if len(hits) < MAX_NAMED_HITS:
                    hits.append(other.source_id)
        if hits_total:
            blockers.append("hits_third_body")
    band = _level_band(mover, levels)
    if band is not None:
        lo, hi = G.hull_bounds(moved)
        if hi[2] < band[0] - 1.0 or lo[2] > band[1] + 1.0:
            blockers.append("leaves_level_band")
    exact = exit_is_exact(mover.hull, fixed.hull)
    return Move(element_id=mover.source_id, label=mover.label or "",
                category=mover.category,
                minimality=("minimal_over_searched_directions" if exact
                            else "separating_only"),
                directions_searched=len(dirs),
                direction_basis=("axes", "face_normals_mover",
                                 "face_normals_fixed", "certified_translation"),
                direction=tuple(G._norm_zero(c) for c in best_d),
                distance_mm=best_t,
                vector_mm=tuple(G._norm_zero(c) for c in vec),
                certified=certified, legal=not blockers,
                blockers=tuple(blockers), hits=tuple(sorted(hits)),
                hits_total=hits_total,
                hits_truncated=hits_total > len(hits),
                rank_basis=basis)


def _host_state(a_id: str, b_id: str,
                hosted: Mapping[str, Any] | None) -> str | None:
    """The verdict on host data — ASKED OF ITS OWNER, not derived here.

    The five-state algebra lives in `kir.clash_judgement.host_relation`
    together with its own measurement and its own reasons. The import is
    lazy and tolerant in both directions: `clash_judgement` itself calls
    `resolve` via the same kind of lazy import (`clash_judgement.py:1432`),
    and by the time of the call both modules are already loaded.

    An import failure is NOT a reason to silently decide by table: `None`
    is returned, i.e. "was not asked", and this is exactly the truth that
    occurred.
    """
    if hosted is None:
        return None
    try:
        from kir import clash_judgement as _judgement
    except Exception:  # noqa: BLE001 — the judgment is junior to the resolver
        return None
    state, _, _ = _judgement.host_relation(str(a_id), str(b_id), hosted)
    return state


def propose(a: H.HullRecord, b: H.HullRecord, *,
            hood: Neighbourhood | None = None,
            levels: Mapping[str, float] | None = None,
            pair_kind: str = "interference",
            finding_id: str | None = None,
            with_alternative: bool = True,
            hosted: Mapping[str, Any] | None = None) -> Proposal:
    """A proposal for ONE pair. A number is given always when the geometry
    provides it; a refusal, if one does occur, is NAMED.

    `hosted` — the index `element_id -> {host_element_id, host_ref,
    host_class, source}`. There are two forms, and both are already built:
    `clash_judgement.hosted_from_ops` (in the words of the PROGRAM) and
    `snapshot.hosted_from_l0` (in the words of the DECOMPILE). No third one
    is introduced here, and the verdict is not computed here either: it is
    rendered by `clash_judgement.host_relation`, the sole owner of this
    algebra.

    🔴 `hosted=None` — LITERALLY THE PREVIOUS BEHAVIOR: the index was not
    asked, and the label table decides, as it used to. "Was not asked" and
    "asked, there is no host" must be different facts, otherwise a default
    silently changes the decision for everyone who does not yet know about
    the fix.
    """
    ends = sorted((a, b), key=lambda r: r.source_id)
    fid = finding_id or "%s~%s" % (ends[0].source_id, ends[1].source_id)
    host_state = _host_state(a.source_id, b.source_id, hosted)
    rec = _recommendation(a, b, pair_kind, host_state)
    if G.signed_distance(a.hull, b.hull) >= -G.SEP_EPS_MM:
        return Proposal(fid, rec, None, None, "not_overlapping", host_state)
    mover, fixed, basis = _decide(a, b)
    primary = _build_move(mover, fixed, hood, levels, basis)
    alt = None
    if with_alternative:
        # There is ONE basis per pair: the counter-move is the same
        # ranking, read from the other end. Previously the basis was taken
        # from the SECOND record here, and one pair was publishing two
        # different bases for its single ordering.
        alt = _build_move(fixed, mover, hood, levels, basis)
    if primary is None and alt is None:
        return Proposal(fid, rec, None, None, "no_certified_direction",
                        host_state)
    if primary is None:
        return Proposal(fid, rec, alt, None, None, host_state)
    # An illegal cheap move alongside a legal expensive one: we show the
    # executable one first. A proposal exists for the sake of execution,
    # not for the sake of order.
    if not primary.legal and alt is not None and alt.legal:
        return Proposal(fid, rec, alt, primary, None, host_state)
    return Proposal(fid, rec, primary, alt, None, host_state)


AXIS_NAME = {(1, 0, 0): "по +X", (-1, 0, 0): "по −X", (0, 1, 0): "по +Y",
             (0, -1, 0): "по −Y", (0, 0, 1): "вверх", (0, 0, -1): "вниз"}

_VERB = {"move": "сдвиньте", "review": "чтобы развести, нужно сдвинуть",
         "verify_duplicate": "возможный дубликат; для проверки геометрически развело бы",
         "assembly_relation": "узел; геометрически развело бы"}


#: 🔴 ALMOST-AN-AXIS IS NOT AN AXIS (F-148, 29.08.2026). `int(round(c))` was
#: snapping to the axis anything closer than 0.5 on each component, i.e. up
#: to 60° off. A move of (0.342, −0.940, 0) — that is 20° from −Y — was
#: being printed as pure "along −Y", and the X component, a third of the
#: move's length, was vanishing WITHOUT A TRACE. Nobody declared the
#: threshold of 0.5: it fell out of `round` on its own. The tolerance is
#: taken from the certificate (`geom.SEP_EPS_MM`), not assigned: a
#: direction either IS an axis to the precision the move itself was
#: checked at, or it is printed as numbers.
def _axis_name(direction: Sequence[float]) -> str | None:
    for axis, name in AXIS_NAME.items():
        if all(abs(float(c) - a) <= G.SEP_EPS_MM
               for c, a in zip(direction, axis)):
            return name
    return None


#: 🔴 THE SAME CAUSE AS FOR `_axis_name` (F-148). `%.0f` was printing the
#: distance to whole millimeters: a move of 0.4 mm was coming out as the
#: string "by 0 mm", i.e. as an instruction to move nothing. The six
#: digits are derived from `geom.SEP_EPS_MM = 1e-6`, the precision the
#: move's certificate is checked at, not chosen to taste.
def _mm(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-", "0", "-0") else text


def to_russian(p: Proposal) -> str:
    """A line the designer executes without rewriting it."""
    if p.chosen is None:
        return "%s: хода нет — %s" % (p.finding_id, p.refusal)
    m = p.chosen
    axis = _axis_name(m.direction)
    where = axis or ("по (%s, %s, %s)" % tuple(_mm(c) for c in m.direction))
    head = "%s: %s %s %s %s на %s мм" % (
        p.finding_id, _VERB.get(p.recommendation, "сдвиньте"),
        m.label, m.element_id, where, _mm(m.distance_mm))
    # 🔴 A READY-MADE MOVE VECTOR ALREADY EXISTS IN `Move.vector_mm` AND WAS
    # NOT BEING PRINTED. It is precisely what gets executed; the reader had
    # to multiply direction by distance themselves, and on a NON-AXIS
    # direction this is exactly the place where mistakes happen. For an
    # axis-aligned move the vector follows from the two already-printed
    # numbers without error, and a third number would be noise — hence only
    # here.
    if axis is None:
        head += " (вектор: %s, %s, %s мм)" % tuple(_mm(c) for c in m.vector_mm)
    if m.legal:
        return head + " — ход свободен"
    tail = "; ".join(LEGALITY_BLOCKERS.get(x, x) for x in m.blockers)
    if m.hits:
        # 🔴 THE TRUNCATION IS NAMED, NOT IMPLIED (F-147). Without this
        # branch the fix would have reached the MACHINE and not reached the
        # HUMAN: they would read the same eight names and understand
        # "eight". A list that looks complete is the same lie as a silent
        # zero.
        tail += " (тела: " + ", ".join(m.hits)
        if m.hits_truncated:
            tail += f", и ещё {m.hits_total - len(m.hits)}"
        tail += ")"
    return head + " — НО " + tail


def proposals_for(pairs: Iterable[tuple[H.HullRecord, H.HullRecord]], *,
                  hood: Neighbourhood | None = None,
                  levels: Mapping[str, float] | None = None) -> list[Proposal]:
    return [propose(a, b, hood=hood, levels=levels) for a, b in pairs]
