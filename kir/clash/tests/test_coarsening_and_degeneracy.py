"""THE TWO MAIN FINDINGS OF THE ZONE, LOCKED DOWN BY WHAT IS EXPRESSIBLE
INSIDE THE TREE.

Before this file, both lived ONLY as prose in `ORACLE_LIMITS.md`.
Writing it down is not protection: `fp_sign`, `lb_slack`,
`frac_underestimate`, `dist_err` do not occur anywhere in the backend
outside venv as a single line of code, only as text. Measured
11.08.2026.

WHAT THIS FILE DOES NOT DO AND CANNOT DO IS STATED FIRST.
It does NOT reproduce the oracle and does not try to. The oracle lives
OUTSIDE the repository (`ORACLE_LIMITS.md`, first line: «a harness, not
a module»), so neither "18,173 pairs, 0 misses," nor "`fp_sign` 4 -> 0,"
nor "`lb_slack.frac_underestimate` = 0.0 across eight buildings" is
checked here, and none of them can be. This is a property of WHERE the
instrument lives, not a gap in the suite. Anyone who sees green here
must read this caveat before citing the file: it protects a RULE and
TWO MECHANISMS, not gate numbers.

ALL TWELVE ARE GREEN FROM THE FIRST RUN, AND THAT IS A REASON FOR
SUSPICION, NOT FOR JOY. The mechanisms are already fixed, so a test
cannot be red against the current code — and a test that could not be
made red is, for us, a hypothesis, not a finding. So the ability of
each to fail is proven by MUTATIONS (measured 11.08.2026, three
mutants):

  A. A BLIND ORACLE — "zero area means no intersection":
     `degenerate_inside_is_overlap` TURNS RED,
     `point_degenerate_inside` TURNS RED, while
     `neighbours_are_contact` stays green — and it SHOULD, it guards
     the opposite half of the rule. A test that turns red on both
     mutants at once would not distinguish a fix from the opposite
     breakage.
  B. A CONVEX COVERING INSTEAD OF DECOMPOSITION: `carved_vs_convex`
     TURNS RED, `concave_outline_decomposed` TURNS RED.
  C. INFLATING THE DECLARED z BY ±25mm: contact between two slabs
     `0.0` becomes `−50.0`, that is, exactly 2t of overlap OUT OF
     NOTHING, and a declared clearance of 50mm gets eaten down to
     zero. The mechanism is measured, not retold.

MUTANT C'S BOUNDARY, AND IT MATTERS: it is caught by
`the_declared_z_span_reaches_the_hull_unwidened` — a check of the
hull's span against the declaration. Its paired counterpart,
`slabs_that_only_share_a_plane_do_not_overlap`, guards `geom`'s
ARITHMETIC and does NOT check the builder: if the builder starts
inflating, this test would stay green. Two tests, two different
targets; reading them as one is a mistake.

Three more things it does NOT cover, named explicitly:
  * it says nothing about whether an overlap is LAWFUL (a door in a
    wall, a panel in a curtain wall) — that is `clash_judgement`'s job,
    not the detector's;
  * it does not measure the ACCURACY of a distance against independent
    algebra — that is `test_clash_proximity_oracle`'s job for
    segments, and an external rig's job for bodies;
  * it does not prove that the hull CONTAINS the Revit body:
    containment is a question for the live model, and there is nothing
    here to substitute for it.
"""
from __future__ import annotations

from kir.clash import geom as G
from kir.clash import hulls as H


# ═══════════════════════════════════════════════════════════════════════════
# 1. THE DEGENERATE-BRANCH RULE
#
# When the exact intersection test was made AREA-BASED — so that
# neighboring paving tiles wouldn't read as a collision — a segment and
# a point got zero area BY DEFINITION, and the oracle declared them
# non-intersecting with anything. Degenerate hulls run 9.7-38.2% PER
# BUILDING, so this is a class, not four pairs.
#
# The rule after the fix: POSITIVE AREA where both sides are
# full-dimensional, SET-THEORETIC INTERSECTION where at least one is
# degenerate. Both halves are mandatory: without the first, paving
# neighbors become clashes; without the second, a beam inside a wall is
# declared "clean."
# ═══════════════════════════════════════════════════════════════════════════

_SOLID = G.Prism(((0, 0), (1000, 0), (1000, 1000), (0, 1000)), 0.0, 1000.0)


def test_a_degenerate_hull_inside_a_solid_is_an_overlap_not_clear():
    """The `aabb_line` case from `ORACLE_LIMITS`: a beam INSIDE a wall.

    Before the fix, the oracle answered "clean," `geom` gave −100.0mm,
    and `geom` was right in all four hand-analyzed pairs. Here is the
    same shape assembled from clean geometry: a zero-area segment
    footprint, entirely inside the body.
    """
    line = G.Prism(((400, 500), (600, 500)), 400.0, 600.0)
    assert H.hull_degeneracy(line) == "prism_degenerate_footprint"
    assert G.signed_distance(_SOLID, line) < 0.0, (
        "вырожденная оболочка внутри тела прочитана как непересекающаяся — "
        "ровно тот дефект, из-за которого оракул был слеп к 9.7–38.2 % "
        "оболочек на здание")


def test_a_point_degenerate_hull_inside_a_solid_is_an_overlap():
    """The `aabb_point` case from `ORACLE_LIMITS` (two of four pairs,
    −15.0mm).

    A point is the ultimate degeneracy: it has zero area AND zero
    length.
    """
    point = G.Prism(((500, 500),), 400.0, 600.0)
    assert H.hull_degeneracy(point) == "prism_degenerate_footprint"
    assert G.signed_distance(_SOLID, point) < 0.0


def test_a_degenerate_hull_outside_a_solid_stays_clear():
    """THE OTHER SIDE, without which the first side means nothing.

    The rule "a degenerate case intersects by set membership" must be
    able to say NO: a test that stays green even when a degenerate case
    always intersects everything does not distinguish a fix from the
    opposite breakage.
    """
    outside = G.Prism(((4000, 500), (6000, 500)), 400.0, 600.0)
    assert G.signed_distance(_SOLID, outside) > 0.0


def test_full_dimensional_neighbours_sharing_a_face_are_contact_not_overlap():
    """THE FIRST HALF OF THE RULE, and also the reason area was
    introduced.

    Two paving tiles touching along an edge must give EXACTLY zero:
    contact, not overlap. If full-dimensional pairs were judged by
    set-theoretic intersection, a shared face would give a non-empty
    intersection, and every bit of paving in the building would arrive
    as a field of collisions.
    """
    a = G.Prism(((0, 0), (1000, 0), (1000, 1000), (0, 1000)), 0.0, 100.0)
    b = G.Prism(((1000, 0), (2000, 0), (2000, 1000), (1000, 1000)), 0.0, 100.0)
    assert G.signed_distance(a, b) == 0.0


def test_the_degeneracy_is_named_by_the_census_not_silently_ok():
    """Degeneracy must be NAMED, not swallowed: a zero-volume hull
    cannot prove anything, and the count of such hulls is part of the
    honest denominator, not a minor technicality."""
    plane = G.Prism(((0, 0), (1000, 0), (1000, 1000), (0, 1000)), 300.0, 300.0)
    assert H.hull_degeneracy(plane) == "prism_zero_height"
    assert "prism_zero_height" in H.DEGENERACIES
    assert H.hull_degeneracy(_SOLID) == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# 2. THE FIRST MECHANISM: A CONVEX HULL FILLS IN HOLES
#
# One of the two mechanisms that explained ALL 66 "critical" findings:
# disputes with the operator on a real building — zero, and 62 of 76
# slabs didn't intersect by declaration at all. Filling a hole isn't a
# numerical error, it CREATES a pair that doesn't exist in the
# building.
# ═══════════════════════════════════════════════════════════════════════════

def _slab_with_a_hole():
    el = {"element_id": "f0", "category": "OST_Floors",
          "bbox_min_mm": [0, 0, 3000], "bbox_max_mm": [1000, 1000, 3200]}
    profile = {
        "profile_available": True,
        "exterior_loop": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]],
        "curve_kinds": [["line"] * 4, ["line"] * 4],
        "arc_midpoints": [[None] * 4, [None] * 4],
        "holes": [[[300, 300], [700, 300], [700, 700], [300, 700]]]}
    rec, refusal = H.build_hull(el, profile=profile)
    assert rec is not None, refusal
    return rec


#: A body standing IN A HOLE of the slab: a shaft, a riser, a stairwell
#: opening.
_IN_THE_HOLE = G.Prism(((450, 450), (550, 450), (550, 550), (450, 550)),
                       3000.0, 3200.0)


def test_the_carved_hull_says_clear_where_the_convex_cover_fabricates_an_overlap():
    """MEASURING THE MECHANISM, ONE PAIR AND TWO NUMBERS.

    The same slab, the same body inside its opening:

        footprint with the hole cut out   ->  +150.0mm, CLEAN
        convex covering of the same       ->  −200.0mm, OVERLAP

    A 350mm swing on one pair, and the sign flips. No threshold was
    touched here: the entire difference is created by the footprint's
    shape. Hence the zone's rule — before declaring a collision, ask
    whether your own approximation is what created it.
    """
    carved = _slab_with_a_hole()
    convex = G.Prism(
        G.convex_footprint([(0, 0), (1000, 0), (1000, 1000), (0, 1000)]),
        3000.0, 3200.0)
    carved_sd = G.signed_distance(carved.hull, _IN_THE_HOLE)
    convex_sd = G.signed_distance(convex, _IN_THE_HOLE)
    assert carved_sd > 0.0, "тело в проёме прочитано как коллизия"
    assert convex_sd < 0.0, (
        "выпуклое накрытие перестало заливать дыру — механизм, на котором "
        "стоит вывод о 66 находках, больше не воспроизводится, и вывод надо "
        "перепроверять, а не радоваться зелёному")
    assert carved_sd - convex_sd > 300.0


def test_a_hole_is_carved_and_the_shape_of_the_footprint_is_published():
    """COARSENING IS DECLARED, NOT IMPLIED — the
    `arc_outward_slack_mm` precedent: a hull that became thinner or
    thicker silently is no different from a wrong one."""
    rec = _slab_with_a_hole()
    assert rec.extra["holes_declared"] == 1
    assert rec.extra["holes_carved"] == 1
    assert rec.extra["footprint_form"] == "decomposed"
    assert rec.extra["footprint_cells"] > 1
    pieces = G.footprint_pieces(rec.hull)
    assert pieces is not None and len(pieces) == rec.extra["footprint_cells"]


def test_a_concave_outline_is_decomposed_rather_than_convex_hulled():
    """An L-shaped slab: the concavity must survive building the hull.

    A convex hull of the L would fill in the notch entirely — the same
    mechanism as the hole, only on the outside of the contour.
    """
    el = {"element_id": "f1", "category": "OST_Floors",
          "bbox_min_mm": [0, 0, 3000], "bbox_max_mm": [1000, 1000, 3200]}
    profile = {"profile_available": True,
               "exterior_loop": [[0, 0], [1000, 0], [1000, 300], [300, 300],
                                 [300, 1000], [0, 1000]],
               "curve_kinds": [["line"] * 6], "arc_midpoints": [[None] * 6],
               "holes": []}
    rec, refusal = H.build_hull(el, profile=profile)
    assert rec is not None, refusal
    assert rec.extra["footprint_form"] == "decomposed"
    in_the_notch = G.Prism(((600, 600), (700, 600), (700, 700), (600, 700)),
                           3000.0, 3200.0)
    assert G.signed_distance(rec.hull, in_the_notch) > 0.0
    convex = G.Prism(G.convex_footprint(profile["exterior_loop"]),
                     3000.0, 3200.0)
    assert G.signed_distance(convex, in_the_notch) < 0.0


def test_no_hull_source_claims_to_be_exact():
    """No hull source issues the grade `exact`, and this is NOT
    nitpicking over a word: `confirmed` is read only from `exact`, so a
    promise of precision here would turn coarsening into a confirmed
    collision."""
    assert "exact" not in set(H.GRADE_BY_SOURCE.values())


# ═══════════════════════════════════════════════════════════════════════════
# 3. THE SECOND MECHANISM: THE INTERVAL [z − t, z + t] FABRICATES 2t
#
# The second of the two. Thickness taken as "elevation plus or minus a
# tolerance" creates 2t of overlap OUT OF NOTHING — for two slabs
# declared at neighboring elevations, a shared thickness appears out of
# thin air. Below is a ratchet: the declared z-interval must reach the
# hull WITHOUT widening, and a zero thickness must stay zero and be
# NAMED.
# ═══════════════════════════════════════════════════════════════════════════

def test_a_zero_thickness_declaration_stays_zero_and_is_named():
    """A slab declared at a single elevation does not get a body.

    Inflating it to `[z − t, z + t]` would mean handing out 2t of
    thickness that isn't in the declaration; instead the span stays
    zero, and the degeneracy gets a NAME and goes into the census.
    """
    el = {"element_id": "f2", "category": "OST_Floors",
          "bbox_min_mm": [0, 0, 3000], "bbox_max_mm": [1000, 1000, 3000]}
    rec, refusal = H.build_hull(el)
    assert rec is not None, refusal
    assert G.z_span(rec.hull) == (3000.0, 3000.0)
    assert H.hull_degeneracy(rec.hull) == "aabb_plane"


def test_the_declared_z_span_reaches_the_hull_unwidened():
    el = {"element_id": "f3", "category": "OST_Floors",
          "bbox_min_mm": [0, 0, 3000], "bbox_max_mm": [1000, 1000, 3200]}
    rec, refusal = H.build_hull(el)
    assert rec is not None, refusal
    assert G.z_span(rec.hull) == (3000.0, 3200.0)


def test_slabs_that_only_share_a_plane_do_not_overlap():
    """A RATCHET ON THE MECHANISM ITSELF. Two slabs stacked one on top
    of the other share exactly a plane. Any widening of the z-interval —
    whether by a tolerance or by half a thickness — would immediately
    give a negative number here, that is, a fabricated overlap where
    the building doesn't have one.
    """
    lower = G.Prism(((0, 0), (1000, 0), (1000, 1000), (0, 1000)), 0.0, 200.0)
    upper = G.Prism(((0, 0), (1000, 0), (1000, 1000), (0, 1000)), 200.0, 400.0)
    assert G.signed_distance(lower, upper) == 0.0
    apart = G.Prism(((0, 0), (1000, 0), (1000, 1000), (0, 1000)), 250.0, 450.0)
    assert G.signed_distance(lower, apart) == 50.0
