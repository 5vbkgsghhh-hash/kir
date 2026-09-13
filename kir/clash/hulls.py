"""A closed table "category → eligibility → hull source → grade".

The law of census §18 is literal here: EVERY element of the model must exit
this table with exactly one outcome — a hull, or a named reason for its
absence. No class can fall out silently: an unknown category goes into
`unsupported` with the reason `kind_outside_table`, rather than vanishing.

Why the table is closed, rather than "if it worked out". A detector that
built hulls for half the building and found zero clashes is indistinguishable
from a detector that searched honestly. The only defense is counters that
converge on the census: `eligible = hulled + unsupported + missing_geometry`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from kir.clash import decompose as D
from kir.clash import geom as G

#: How many grid cells one hull is allowed to occupy before it is recognized
#: as a giant and removed from bucket placement. Not a matter of taste: past
#: this number the cost of placement outweighs the grid's payoff.
#:
#: 🔴 THE HOME IS HERE, AND THIS IS A FIX FROM 29.08.2026. The value stood
#: TWICE — in `detect.py:38` and `resolve.py:225` — with one value, one
#: arithmetic (the product of index spans), and one meaning, but without a
#: single home. It was not caught by an eye but by the agreement registry at
#: gate 6/6: "MAX_CELLS_PER_HULL: a NEW twin in 2 places". The argument
#: against the disposition "one value" instead of a merge is the tree's own
#: convention: for the coordinate limit there is ONE home, and this is
#: guarded by a separate test. Two carriers of the same knowledge diverge
#: silently, and here they would have diverged the more unnoticeably because
#: the two clash modules are edited apart.
MAX_CELLS_PER_HULL = 512

#: The hull's grade — how tightly it hugs the element.
#:
#: `exact`        — the hull coincides with the body (a straight round-section
#:                  pipe);
#: `conservative` — contains the body and coarsens in a NAMED way (after the
#:                  DECOMPOSE wave the contour's base is exact, but Z is still
#:                  taken from the declared elevation, and an arc is inflated
#:                  outward by its sagitta);
#: `coarse`       — bounding box only: contains the body and asserts nothing
#:                  more about it.
GRADES = ("exact", "conservative", "coarse")

#: Tolerance for the grade: how deeply a pair must penetrate each other to
#: call it a clash. An exact hull has no tolerance. For a coarse one,
#: penetration cannot be proven at all (review #14), so its verdict is at
#: most `possible` — and the tolerance keeps a mere touch of bounding boxes
#: from being declared a clash.
TOL_GRADE_MM = {"exact": 0.0, "conservative": 1.0, "coarse": 25.0}


#: Hull sources, per allowed category. Review #12: a row declaring ALL three
#: sources for every eligible category is self-consistent and empty —
#: furniture has no base contour, a wall today has no section. The list of
#: sources must be a property of the CATEGORY, otherwise the coverage matrix
#: promises nothing.
SOURCES_SKETCH = ("profile", "bbox")
SOURCES_AXIS = ("axis_section", "bbox")
SOURCES_BBOX = ("bbox",)
#: A band around the axis × [z0, z1]. Input — `el["prism"]`, assembled only
#: from numbers proven to be of the TYPE.
#:
#: NO CATEGORY HAS THIS SOURCE TODAY, AND THIS IS A MEASUREMENT, NOT AN
#: OVERSIGHT. The sections wave (09.08.2026) gave the snapshot the wall
#: thickness (`WallType.Width`) and checked the conservativeness law against
#: an external witness — the real Revit bounding boxes of 800 walls of the
#: Snowdon building:
#:
#:   body exceeding the box ALONG the axis    409 of 800 walls, median 6.3,
#:                                             p99 757, max 1362 mm
#:   body exceeding the box ACROSS the axis    93 of 800 walls,
#:                                             max 2854 mm
#:
#: The longitudinal excess is explained by joins and is almost entirely (703
#: of 707) covered by an EXACT join calculation over the batch itself. The
#: transverse one is explained by nothing the program expresses: 93 walls
#: are wider than their own `WallType.Width`, by up to 2854 mm (packaged
#: assemblies, an edited profile, overhangs). With the exact join, the
#: total is 97 violations out of 800, meaning the lock
#: `clash.tools.wall_prism_gate` ("zero violations across the whole sample")
#: is NOT OPEN, and the wall stays on its bounding box.
#:
#: The builder, the input, and this line live here so that the day the lock
#: opens, it costs one edit to the table, not a redesign from scratch.
SOURCES_PRISM = ("prism", "bbox")


#: WHY THE WALL IS NOT GIVEN A BAND — MEASUREMENT 11.08.2026 OVER THE WHOLE
#: CORPUS.
#:
#: The earlier note (above) is correct and UNUSED: "the band failed by
#: 2854 mm on 97 of 800 walls" says the attempt was unsuccessful, but does
#: not say WHAT exactly would open the gate. Going by it, the next session
#: will propose the band again — "but a wall does have thickness" sounds
#: obvious. Here the same door is locked by a breakdown into classes, from
#: which one can see both why it is locked and what unlocks it.
#:
#: DENOMINATOR: 220 871 walls, all readable parses of the corpus
#: (`/tmp/clashwork/w2_wall_width.py`, `w2_prize.py`).
#:
#: (1) THERE IS NO THICKNESS IN THE DATA AT ALL. Not one wall in the corpus
#:     carries a `prism` key; the wall's entire `params` is
#:     WALL_BASE_OFFSET, WALL_HEIGHT_TYPE, WALL_KEY_REF_PARAM,
#:     WALL_TOP_OFFSET, WALL_USER_HEIGHT_PARAM. There is no type record in
#:     `L0.jsonl` (record kinds: header, link, element, category_status,
#:     footer). That is, `_prism_record` today does not even reach the
#:     check — it exits on the first line.
#:
#: (2) FOR 55.9% OF WALLS THE BAND REFINES NOTHING BY CONSTRUCTION. 123 418
#:     walls are axis-aligned, and for them the rectangle around the axis
#:     COINCIDES with the bounding box. Half the argument is removed before
#:     any dispute about containment even starts: there is nothing to hug.
#:
#: (3) 39.3% OF DIAGONAL WALLS CONTRADICT THEMSELVES. The bounding box of a
#:     straight wall OVER-DETERMINES its width: dx = L·|ux| + w·|uy| and
#:     dy = L·|uy| + w·|ux| — two equations for one unknown, so w is
#:     computed twice and independently. Of 31 915 diagonal walls, 19 368
#:     agree, while for 12 547 (39.3%) the two estimates diverge by more
#:     than 1 mm, up to 587.6 mm. This is not "the data is imprecise" — it
#:     is data INCOMPATIBLE with the rectangular-wall model. Fitting w to
#:     one of the two estimates means choosing which of the two
#:     measurements to declare false.
#:
#: (4) 17.5% OF AXIS-ALIGNED WALLS HAVE AN AXIAL OVERHANG. For 21 556 walls
#:     the bounding box is longer than the axis by more than 1 mm, up to
#:     250 mm: joins push material PAST the placement line. The axis is not
#:     the body even by length, let alone by width.
#:
#: (5) THERE IS NOTHING TO CHECK AGAINST, AND THIS IS NOT TEMPORARY. There
#:     are no wall triangles in the corpus: the only parse with a
#:     `geometry.bundle.json` (`snowdon_plumb_v4`) carries five walls, and
#:     NOT ONE of them is in the geometry index. But something else matters
#:     more, and it will outlive the corpus's appearance: A BOUNDING-BOX
#:     GATE CANNOT CHECK A BAND IN PRINCIPLE. A band lies STRICTLY INSIDE
#:     the bounding box, so the condition "band ⊇ box" always fails and
#:     diagnoses nothing, while "band ⊆ box" always holds and promises
#:     nothing about the BODY. This is an argument of form, not of missing
#:     data — the same one by which a bounding-box gate cannot check a
#:     capsule (see `tools/mesh_gate`).
#:
#: (6) THE PRIZE, FOR THE SAKE OF THE FULL PICTURE. For the 19 368
#:     consistent diagonal walls (8.8% of the corpus) the band's area is —
#:     median 50.1% of the bounding box's, p10 35.1%, minimum 3.6%. Half the
#:     trail on one wall in eleven, and only if containment is PROVEN.
#:     Shipping that 8.8% on an unproven assumption is not allowed: a body
#:     smaller than the real one hides a clash silently, and that is the one
#:     failure that reaches the construction site.
#:
#: WHAT WOULD OPEN THE GATE, in order of usefulness:
#:
#:   1. WALL TRIANGLES in the geometry bundle for the ARCHITECTURAL model.
#:      The tool is already written: `clash/tools/mesh_gate` checks every
#:      vertex of the real body against the hull with independent code and
#:      settles the question in one pass. This removes item (5) entirely —
#:      and only this removes it.
#:   2. TYPE WIDTH (`WallType.Width` or a type record in L0). Without item 1
#:      it is not enough: it closes item (1), but not (3) or (4), because
#:      the estimate mismatch and the axial overhang are properties of the
#:      BODY, not of the nominal value.
#:
#: Both inputs lie outside this module (`kir/**`), so this note is not a
#: task but an acceptance condition: the day the data arrives, it must cost
#: one edit to `KIND_TABLE` and one gate run, not a redesign from scratch.
#: THE BOUNDARY OF THE BAND, named by a number. The band was allowed on
#: 14.08 precisely for a wall THAT THE PROGRAM DECLARED, and precisely
#: because it has no bounding box: there the choice is "a band versus
#: nothing". For a wall parsed out of the model, the refusal below remains
#: in force in full, and what separates these two cases is not intent but
#: DATA: the `prism` key is written by one place (`clash_bundle`, the
#: authoring path), and the whole corpus does not carry it.
WALL_BAND_SCOPE: dict[str, object] = {
    "admitted_for": "стена, объявленная программой (есть `prism`, нет bbox)",
    "still_refused_for": "стена, разобранная из модели (есть bbox, нет `prism`)",
    "measured_on": "2026-08-14",
    "declared_wall_bodies_before": 0,
    "declared_wall_bodies_after": 1,
    "not_promised": (
        "полоса содержит стену КАК ОБЪЯВЛЕНО, а не тело, которое Revit "
        "построит после переноса: стыки выносят материал за ось до 250 мм, "
        "93 стены из 800 шире собственной WallType.Width до 2854 мм"),
}

WALL_BAND_REFUSAL: dict[str, object] = {
    "measured_on": "2026-08-11",
    "walls_total": 220871,
    "axis_aligned_no_gain": 123418,
    "axis_aligned_axial_overhang_gt1mm": 21556,
    "axis_overhang_max_mm": 250.0,
    "diagonal": 31915,
    "diagonal_consistent": 19368,
    "diagonal_self_contradictory": 12547,
    "width_disagreement_max_mm": 587.6,
    "non_line_axis_or_no_location_curve": 63231,
    "wall_meshes_in_corpus": 0,
    "band_area_over_bbox_area_p50": 0.501,
    "opens_with": ("wall_triangles_in_geometry_bundle", "wall_type_width"),
    "why_bbox_gate_cannot_decide": (
        "полоса лежит строго внутри габарита: «полоса ⊇ габарит» ложно всегда, "
        "«полоса ⊆ габарит» истинно всегда и про тело не говорит ничего"),
}


#: TWO DIFFERENT PHENOMENA LAY UNDER ONE REFUSAL ABOVE. SEPARATED 20.08.2026.
#:
#: `WALL_BAND_REFUSAL` mixes "a join pushes out the end" and "the wall is
#: wider than its own thickness", and this makes the refusal broader than
#: the data allows. Measurement on the `k2v33_join2` tower (Revit 2023),
#: 13 044 STRAIGHT VERTICAL AXIS-ALIGNED walls with a declared width — for
#: an axis-aligned wall the transverse direction coincides with a coordinate
#: axis, so both quantities are read from the bounding box without
#: projections:
#:
#:   ALONG the axis    median 0 · p90 37.5 · p99 160 · MAX 250 mm
#:                     86.1% exactly zero · 9.7% EXACTLY HALF-THICKNESS (w/2) ·
#:                     1.2% exactly the thickness (both ends) · 3.0% other
#:   ACROSS the axis   MAXIMUM 0.0 mm ACROSS ALL 13 044
#:
#: The first is a join, and it is QUANTIZED: exactly w/2 per joined end,
#: exactly as the live measurement of 18.08 showed (+125 at 250, +190 at
#: 380). It is bounded above by one thickness and is now KNOWN per element:
#: the join index reached the graph on 20.08, and every wall has something
#: to ask about its own ends.
#:
#: The second is ABSENT ENTIRELY on straight vertical walls — not one of the
#: 13 044.
#:
#: 🔴 SO WHERE IS "WIDER THAN ITS OWN THICKNESS BY UP TO 2854 mm"? On the
#: same data the excess appears PRECISELY on diagonal walls: 1280 walls,
#: median +371, maximum +5200 mm. And this is not a property of the body:
#: for a rotated rectangle the axis-aligned bounding box is WIDER than the
#: thickness BY GEOMETRY, always, and more so the closer the angle is to
#: 45°. That is, a quantity of this kind measures a COMPARISON, not the
#: wall.
#:
#: ⚠️ THIS IS A HYPOTHESIS ABOUT SOMEONE ELSE'S NUMBER, NOT ITS REFUTATION.
#: How 2854 mm and 587.6 mm were obtained cannot be reconstructed from the
#: record, and `mesh_gate` checked the band against the REAL body, not
#: against the bounding box. Exactly one thing is asserted: on a straight
#: vertical wall there is no transverse excess on any of the 13 044, while
#: on a diagonal one it arises from the construction of the comparison.
#: Verification — with the same `mesh_gate`.
WALL_OVERHANG_SPLIT_2026_08_20: dict[str, object] = {
    "measured_on": "2026-08-20",
    "run": "k2v33_join2 (13A-RD-AR-K2_v33, Revit 2023)",
    "population": "прямые вертикальные ОСЕВЫЕ стены с объявленной шириной",
    "walls": 13044,
    "axial_zero": 11227,
    "axial_half_thickness": 1262,
    "axial_full_thickness": 161,
    "axial_other": 394,
    "axial_max_mm": 250.0,
    "transverse_excess_max_mm": 0.0,
    "transverse_excess_count": 0,
    "diagonal_walls": 1280,
    "diagonal_apparent_transverse_median_mm": 371.0,
    "diagonal_apparent_transverse_max_mm": 5200.0,
    "diagonal_caveat": (
        "у повёрнутого прямоугольника осевой габарит шире толщины ПО "
        "ГЕОМЕТРИИ — величина меряет сравнение, а не стену"),
    "verdict": (
        "стык КВАНТОВАН (w/2 на присоединённый конец, потолок w) и теперь "
        "известен поэлементно из индекса стыков; поперечного превышения у "
        "прямой вертикальной стены нет"),
}

#: THE DIVIDEND OF AN EXACT WALL HULL WAS MEASURED ON A SAMPLE. ANSWER:
#: PERCENT, NOT ORDER OF MAGNITUDE.
#:
#: The question was "will the stream of findings collapse with an exact
#: hull, or shift by a few percent", and it decides whether it is worth
#: extending the Tier-G scope to 220 thousand walls. There are no offline
#: triangles, so what is measured is the ANALYTIC PRISM — and this is an
#: UPPER BOUND on the dividend, not an approximation:
#:
#:     prism ⊆ box                   => findings(prism) ⊆ findings(box)
#:     the real body ⊇ the prism at the ends  (a join adds exactly w/2)
#:     => findings(prism) ≤ findings(triangles) ≤ findings(box)
#:
#: The dividend is small even at the upper bound — meaning this is the wrong
#: lever.
#:
#:   `len_ar_me_r24_v1` (AR+MEP, Revit 2026, 57 809 elements, filter any)
#:     hull       prism/box by volume: median 0.147, half or less on 200 of
#:                200
#:     findings   pairs touching the sample: 3949 -> 3005, KILLED 944,
#:                survived 76.1%
#:     document   309 546 -> 308 602  (−0.30%)
#:
#:   `bench_A` (all walls AXIS-ALIGNED)
#:     hull       prism/box MEDIAN 1.000 — for an axis-aligned wall the prism
#:                IS the box
#:     findings   0 of 11 killed. An axis-aligned wall gives NOTHING, and
#:                this is a measurement, not an argument
#:
#: THE BREAKDOWN, WITHOUT WHICH THE NUMBER READS WRONG. On a SINGLE diagonal
#: wall the effect is LARGE — a quarter of its findings are corners of an
#: empty bounding box. It is small on the DOCUMENT because diagonal walls
#: are 5.1% (8.9% on the tower), and the axis-aligned 94.9% give nothing.
#: Carrying the sample over to the whole diagonal population:
#: 944 × (480/200) ≈ 2266 of 309 546 = **about 0.7%**.
#:
#: THE COST, SO THE MULTIPLICATION IS ARITHMETIC. Existing geometry bundles
#: carry 16–18 elements per 1.5 MB — 86…100 KB per element. For 220 thousand
#: walls that is on the order of 20 GB; even a tenth of that for a simple
#: wall is about 2 GB, with the disk at 83%. ⚠️ These 16–18 elements are NOT
#: walls but complex atoms that Tier-G requests today, so the estimate is
#: INFLATED by an unknown amount; it sets the order of magnitude, 10⁰–10¹ GB,
#: but does not give an exact number.
#:
#: CONCLUSION FOR THE DECISION: extending Tier-G for the sake of the finding
#: stream is NOT WORTH IT. The lever is not the wall hull. If an exact wall
#: is needed, a prism with a join is cheaper: across it is already exact (0
#: excesses on 13 044), and along it is fixed by the known addition of w/2
#: per joined end.
WALL_PRECISE_HULL_DIVIDEND_2026_08_20: dict[str, object] = {
    "measured_on": "2026-08-20",
    "method": "аналитическая призма вместо габарита — ВЕРХНЯЯ граница Tier-G",
    "sample_walls": 200,
    "runs": {
        "len_ar_me_r24_v1": {
            "elements": 57809, "diagonal_of_derivable": "480 из 9326 (5.1 %)",
            "prism_over_bbox_volume_p50": 0.147,
            "pairs_touching_sample_before": 3949,
            "pairs_touching_sample_after": 3005,
            "killed": 944, "survived_share": 0.761,
            "document_before": 309546, "document_after": 308602,
            "document_delta_share": -0.0030,
        },
        "bench_A": {"diagonal_of_derivable": "0 из 378",
                    "prism_over_bbox_volume_p50": 1.000, "killed": 0},
    },
    "extrapolated_to_all_diagonal": "≈2266 из 309 546 ≈ 0.7 %",
    "why_small_on_the_document": "осевых 94.9 %, и они не дают НИЧЕГО",
    "why_large_per_wall": "у диагональной стены четверть находок — углы габарита",
    "cost_bytes_per_element_today": "86 000…100 000 (сложные атомы, оценка ЗАВЫШЕНА)",
    "cost_order_for_220k_walls": "10⁰…10¹ ГБ при диске на 83 %",
    "verdict": "поток находок сдвигается на ПРОЦЕНТЫ, не схлопывается; Tier-G не тот рычаг",
}


#: Where the section comes from — the `params` of an L0 line (emission
#: d154196e). The `params` key EQUALS the BuiltInParameter name, so there is
#: not a single "similar-looking" name here: `WALL_ATTR_WIDTH` is absent
#: from the Revit enumeration entirely.
#:
#: The rule is a property of the CATEGORY, exactly like `sources` (review
#: #12). A pipe must read a pipe's diameter, a tray a tray's bounding box;
#: "any number that looks like a section" would be the same
#: self-consistent, empty list of sources.
#:
#: `round` — parameters giving a diameter (radius = d/2). `rect` — pairs
#: (width, height), giving a HALF-DIAGONAL hypot(w,h)/2: the rotation of a
#: rectangular section around the axis is not captured in L0, so the hull
#: must contain the box at ANY roll angle, and that is exactly a cylinder of
#: half-diagonal radius.
SECTION_RULES: dict[str, dict[str, tuple]] = {
    "OST_PipeCurves": {
        "round": ("RBS_PIPE_OUTER_DIAMETER", "RBS_PIPE_DIAMETER_PARAM"),
        "rect": ()},
    "OST_DuctCurves": {
        "round": ("RBS_CURVE_DIAMETER_PARAM",),
        "rect": (("RBS_CURVE_WIDTH_PARAM", "RBS_CURVE_HEIGHT_PARAM"),)},
    # 🔴 PLACEHOLDERS HAVE THEIR OWN CATEGORIES, AND THIS IS A MEASUREMENT,
    # NOT AN ANALOGY (03.09.2026). Until this day the tree assumed a
    # placeholder lives in the category of a real pipe; live Revit 2026 says
    # otherwise (`OST_PlaceHolder*`), and after the category-map fix
    # (`bc3a172`) both operations FELL OUT of the closed table of bodies —
    # `test_clash_in_the_receipt` named them by name.
    #
    # WHAT WAS MEASURED LIVE, before writing in the same rule:
    #     pipe placeholder     has an axis · RBS_PIPE_OUTER_DIAMETER 152.4 mm
    #                                        RBS_PIPE_DIAMETER_PARAM 152.4 mm
    #     duct placeholder     has an axis · RBS_CURVE_DIAMETER_PARAM NONE
    #                                        WIDTH 304.8 mm · HEIGHT 304.8 mm
    #     body                 1 solid, volume 3.22 and 16.40 — i.e. a
    #                          placeholder is NOT bodiless, and it has no
    #                          place in `OP_NO_BODY`
    # The section parameters match the real ones byte-for-byte by name, so
    # the rule carries over wholesale, rather than being written anew.
    "OST_PlaceHolderPipes": {
        "round": ("RBS_PIPE_OUTER_DIAMETER", "RBS_PIPE_DIAMETER_PARAM"),
        "rect": ()},
    "OST_PlaceHolderDucts": {
        "round": ("RBS_CURVE_DIAMETER_PARAM",),
        "rect": (("RBS_CURVE_WIDTH_PARAM", "RBS_CURVE_HEIGHT_PARAM"),)},
    "OST_CableTray": {
        "round": (),
        "rect": (("RBS_CABLETRAY_WIDTH_PARAM", "RBS_CABLETRAY_HEIGHT_PARAM"),)},
    "OST_Conduit": {
        "round": ("RBS_CONDUIT_OUTER_DIAM_PARAM", "RBS_CONDUIT_DIAMETER_PARAM"),
        "rect": ()},
}

#: WHAT EXACTLY the round parameter describes — and, therefore, whether a
#: capsule of that radius contains the body. Red-team finding R3: the
#: nominal value does NOT contain it. For DN100, `RBS_PIPE_DIAMETER_PARAM` =
#: 100, while the outer one is 114.3; a capsule of radius 50 does not
#: contain a body of radius 57.15, and this is within the MVP pair.
#:
#: The classification is taken from the enumeration's `<summary>` STRING in
#: `RevitAPI.xml` (checked across all six versions; the existence of every
#: name is proven by 6/6 compilation), not from habit:
#:
#:   RBS_PIPE_DIAMETER_PARAM      "Diameter"              -> nominal
#:   RBS_PIPE_OUTER_DIAMETER      "Outside Diameter"      -> outer
#:   RBS_CONDUIT_DIAMETER_PARAM   "Diameter(Trade Size)"  -> nominal, in plain text
#:   RBS_CONDUIT_OUTER_DIAM_PARAM "Outside Diameter"      -> outer
#:   RBS_CURVE_DIAMETER_PARAM     "Diameter"              -> see below
#:
#: For a DUCT there is no outer parameter in the API in any of the six
#: versions (checked). So `RBS_CURVE_DIAMETER_PARAM` is the only description
#: of its section, and calling it nominal has nothing to be compared
#: against: `modelled`. This is an ASSUMPTION, and it is named here, not
#: hidden in a default.
DIAMETER_KIND: dict[str, str] = {
    "RBS_PIPE_OUTER_DIAMETER": "outer",
    "RBS_PIPE_DIAMETER_PARAM": "nominal",
    "RBS_CONDUIT_OUTER_DIAM_PARAM": "outer",
    "RBS_CONDUIT_DIAMETER_PARAM": "nominal",
    "RBS_CURVE_DIAMETER_PARAM": "modelled",
}

#: Readings ALLOWED to justify a capsule. The nominal value is not among
#: them: the law of conservativeness knows no exceptions, and "almost
#: contains" does not contain. Exactly the same decision as for an arc in
#: `profile_refusal`: no proof — fall back to the bounding box, which comes
#: from the REAL Revit geometry and does contain the body.
DIAMETER_KIND_ALLOWED = ("outer", "modelled")

#: ALL section parameters the clash kernel can read form a closed list that
#: must be a SUBSET of `extract.SECTION_PARAM_NAMES` (this is held by
#: `test_every_clash_section_parameter_is_emitted`). L0 is deliberately
#: wider: it also captures levels, offsets, and stair parameters for
#: reverse/graph, even though the clash hull does not use them. This list is
#: wider than `SECTION_RULES` by exactly the names the table is FORBIDDEN to
#: use: the value was captured, but it does not justify a hull. This way the
#: report says "the number exists, promotion is forbidden" instead of a
#: silent zero.
ALL_SECTION_PARAM_NAMES: tuple[str, ...] = (
    "RBS_CABLETRAY_HEIGHT_PARAM",
    "RBS_CABLETRAY_WIDTH_PARAM",
    "RBS_CONDUIT_DIAMETER_PARAM",
    "RBS_CONDUIT_OUTER_DIAM_PARAM",
    "RBS_CURVE_DIAMETER_PARAM",
    "RBS_CURVE_HEIGHT_PARAM",
    "RBS_CURVE_WIDTH_PARAM",
    "RBS_PIPE_DIAMETER_PARAM",
    "RBS_PIPE_OUTER_DIAMETER",
    "STRUCTURAL_SECTION_COMMON_DIAMETER",
    "STRUCTURAL_SECTION_COMMON_HEIGHT",
    "STRUCTURAL_SECTION_COMMON_WIDTH",
    "WALL_ATTR_WIDTH_PARAM",
)

#: Section parameters that are NOT a length. `WALL_CROSS_SECTION` is an
#: enumeration ("Cross-Section") distinguishing vertical from slanted/tapered.
#: The hull is not built from it: it decides whether a prism is ALLOWED to be
#: built at all.
#: Kept separate from `ALL_SECTION_PARAM_NAMES`, because `> 0` is meaningless
#: for an enumeration: 0 is a legitimate value, not an absence.
SECTION_ENUM_PARAM_NAMES: tuple[str, ...] = (
    "WALL_BOTTOM_IS_ATTACHED",
    "WALL_CROSS_SECTION",
    "WALL_TOP_IS_ATTACHED",
)

#: What must be PROVEN before a wall is allowed a prism by a single
#: thickness (code review #10). L0 resolves none of the three today:
#: `WALL_CROSS_SECTION` distinguishes vertical from slanted/tapered, the
#: `CompoundStructure` composition by height — stacked and vertically
#: compound, the sweeps list — projections beyond the nominal width/2.
#: Without them a prism by width is NON-CONSERVATIVE for part of the walls,
#: i.e. it allows a clash to be missed.
WALL_PRISM_EVIDENCE = ("WALL_CROSS_SECTION",
                       "wall_compound_layers_by_height",
                       "wall_sweeps")


@dataclass(frozen=True)
class KindRule:
    """A row of the closed table."""
    #: A physical model element that is required to have a hull. False —
    #: a datum/annotation: grids, levels, zones, rasters. They take part
    #: neither in the census of eligible elements nor in the search.
    eligible: bool
    #: Class for MVP pairs: "mep" (pipe/duct/tray) or "struct"
    #: (wall/floor/column). None — outside MVP pairs, the hull is built, but
    #: a pair with it does not go into the narrow phase.
    mvp_side: str | None = None
    #: Short class name for `pair_class` in the finding.
    label: str = ""
    note: str = ""
    #: What this category is ALLOWED to justify a hull with, from exact to coarse.
    sources: tuple[str, ...] = SOURCES_BBOX


#: Revit categories -> rule. The list is closed: anything not here is an
#: explicit `kind_outside_table`, not a silent skip.
KIND_TABLE: dict[str, KindRule] = {
    # ── bearing and enclosing (the struct side of MVP pairs)
    # Wall: the BAND FIRST, then the bounding box. The order here is the
    # whole point.
    #
    # A wall decompiled from the model CARRIES a bounding box and has no
    # `prism` key (`el["prism"]` is written by exactly one place —
    # `clash_bundle`, the authoring path), so for the whole corpus
    # `_prism_record` comes out on the first line and the rule works as
    # before: as a box. The measured band refusal (`WALL_BAND_REFUSAL`,
    # 220 871 walls) concerns EXACTLY this case and remains in force —
    # there the band contests the real body and loses.
    #
    # A DECLARED wall is a different case, and the earlier line did not
    # distinguish it. It has NO bounding box AT ALL: the program knows the
    # grid line, the type thickness, and the height, but does not know what
    # Revit will build from that. The measurement of 14.08 on the wall
    # «Типовой - 200мм» (a full `prism`: width 200, uniform, blockers empty):
    #
    #     sources=('bbox',)   0 bodies, refusal "neither a contour, nor a
    #                         section, nor a bounding box"
    #     sources=('prism',)  1 body, grade=conservative, source prism
    #
    # That is, the choice here is not "band against bounding box" but the
    # BAND AGAINST NOTHING, and all six refusal clauses compare the band
    # against a body that does not exist for a wall that has not yet been
    # built.
    #
    # WHAT THIS LINE DOES NOT PROMISE, AND THIS MUST BE READ TOGETHER WITH
    # WHAT IT DOES GIVE. The band contains the wall AS IT IS DECLARED. It
    # does not contain the body that Revit will build AFTER transfer: joints
    # push material past the grid line by up to 250 mm, and 93 walls out of
    # 800 are wider than their own `WallType.Width` by up to 2854 mm (points
    # 3–4 of the record below). So a clash of the DECLARED is a clash of the
    # DESIGN INTENT, and it is not inherited across transfer: after transfer
    # L0 measures the wall by its real bounding box. The boundary is named,
    # not hidden — `WALL_BAND_SCOPE`.
    "OST_Walls": KindRule(True, "struct", "wall", sources=SOURCES_PRISM),
    "OST_Floors": KindRule(True, "struct", "floor", sources=SOURCES_SKETCH),
    "OST_StructuralColumns": KindRule(True, "struct", "column", sources=SOURCES_BBOX),
    "OST_Columns": KindRule(True, "struct", "column", sources=SOURCES_BBOX),
    # A beam is eccentric relative to its axis (justification) — review #3;
    # until a category-specific builder, only the bounding box.
    "OST_StructuralFraming": KindRule(True, "struct", "beam", sources=SOURCES_BBOX),
    "OST_StructuralFoundation": KindRule(True, "struct", "foundation",
                                         sources=SOURCES_BBOX),
    "OST_Roofs": KindRule(True, "struct", "roof", sources=SOURCES_SKETCH),
    # ── engineering (the mep side of MVP pairs)
    "OST_PipeCurves": KindRule(True, "mep", "pipe", sources=SOURCES_AXIS),
    "OST_DuctCurves": KindRule(True, "mep", "duct", sources=SOURCES_AXIS),
    # Stock elements are the same kind and the same rule: axis plus section.
    # The justification and the measurement are at their own rows in
    # `SECTION_RULES` above.
    "OST_PlaceHolderPipes": KindRule(True, "mep", "pipe", sources=SOURCES_AXIS),
    "OST_PlaceHolderDucts": KindRule(True, "mep", "duct", sources=SOURCES_AXIS),
    # Flexible runs: the axis between the ends does NOT describe the sag
    # (review #3) — only the bounding box, until the real curve is captured.
    "OST_FlexPipeCurves": KindRule(True, "mep", "pipe", sources=SOURCES_BBOX),
    "OST_FlexDuctCurves": KindRule(True, "mep", "duct", sources=SOURCES_BBOX),
    "OST_CableTray": KindRule(True, "mep", "tray", sources=SOURCES_AXIS),
    "OST_Conduit": KindRule(True, "mep", "conduit", sources=SOURCES_AXIS),
    # ── R2 of the red findings: RUN FITTINGS AND ACCESSORIES. On
    #    `sklnk_eom_r26_v8` there are 75 trays, 64 tray fittings — 46.0% of
    #    the run by element count had NO hull AT ALL and went into
    #    `kind_outside_table`. And these are exactly the elbows, tees, and
    #    transitions — i.e. the places where the run is WIDER than a
    #    straight section. They have no axis (a fitting is not a segment),
    #    so only a bounding box; but the bounding box exists, and it does
    #    contain the body.
    "OST_PipeFitting": KindRule(True, "mep", "pipe_fitting", sources=SOURCES_BBOX),
    "OST_DuctFitting": KindRule(True, "mep", "duct_fitting", sources=SOURCES_BBOX),
    "OST_CableTrayFitting": KindRule(True, "mep", "tray_fitting",
                                     sources=SOURCES_BBOX),
    "OST_ConduitFitting": KindRule(True, "mep", "conduit_fitting",
                                   sources=SOURCES_BBOX),
    "OST_PipeAccessory": KindRule(True, "mep", "pipe_accessory",
                                  sources=SOURCES_BBOX),
    "OST_DuctAccessory": KindRule(True, "mep", "duct_accessory",
                                  sources=SOURCES_BBOX),
    "OST_DuctTerminal": KindRule(True, "mep", "duct_terminal",
                                 sources=SOURCES_BBOX),
    "OST_Sprinklers": KindRule(True, "mep", "sprinkler", sources=SOURCES_BBOX),
    # ── R4 of the red findings: INSULATION AND LINING. The body exists in
    #    the model as a SEPARATE element with its own bounding box, and we
    #    were not asking for it. DN20 (outer 26.9) + 50 mm of insulation: the
    #    pipe hull covered 4.5% of the obstacle's cross-section area. We take
    #    the insulation body rather than inflate the radius by its thickness:
    #    the former does not require trusting a number.
    "OST_PipeInsulations": KindRule(True, "mep", "pipe_insulation",
                                    sources=SOURCES_BBOX),
    "OST_DuctInsulations": KindRule(True, "mep", "duct_insulation",
                                    sources=SOURCES_BBOX),
    "OST_DuctCurvesInsulation": KindRule(True, "mep", "duct_insulation",
                                         sources=SOURCES_BBOX),
    "OST_DuctLinings": KindRule(True, "mep", "duct_lining", sources=SOURCES_BBOX),
    "OST_FabricationPipeworkInsulation": KindRule(
        True, "mep", "pipe_insulation", sources=SOURCES_BBOX),
    # ── physical, but outside MVP pairs: the hull is built, the census
    #    reconciles, they do not go into the narrow phase (many legal
    #    abutments — second stage)
    "OST_Doors": KindRule(True, None, "door"),
    "OST_Windows": KindRule(True, None, "window"),
    "OST_CurtainWallPanels": KindRule(True, None, "curtain_panel"),
    "OST_CurtainWallMullions": KindRule(True, None, "mullion"),
    "OST_GenericModel": KindRule(True, None, "generic"),
    "OST_SpecialityEquipment": KindRule(True, None, "equipment"),
    "OST_StairsRailing": KindRule(True, None, "railing"),
    "OST_Stairs": KindRule(True, None, "stairs"),
    "OST_Furniture": KindRule(True, None, "furniture"),
    "OST_Casework": KindRule(True, None, "casework"),
    "OST_PlumbingFixtures": KindRule(True, None, "fixture"),
    "OST_MechanicalEquipment": KindRule(True, None, "equipment"),
    "OST_Ceilings": KindRule(True, None, "ceiling"),
    "OST_Ramps": KindRule(True, None, "ramp"),
    "OST_CurtaSystem": KindRule(True, None, "curtain_system"),
    # ── R2 of the red findings, second half: physical bodies that were
    #    until now going into `kind_outside_table` (991 elements across the
    #    corpus: electrical equipment 516, tray fittings 384, DirectShape
    #    91). A hull is built for them, they do not go into MVP pairs —
    #    equipment against a wall is a separate conversation.
    "OST_ElectricalEquipment": KindRule(True, None, "electrical_equipment"),
    "OST_ElectricalFixtures": KindRule(True, None, "electrical_fixture"),
    "OST_LightingDevices": KindRule(True, None, "lighting_device"),
    "OST_LightingFixtures": KindRule(True, None, "lighting_fixture"),
    # Importing an entire discipline section (DWG/IFC) gave ZERO hulls —
    # i.e. it was entirely invisible to the search.
    "DirectShape": KindRule(True, None, "direct_shape"),
    # 🔴 MASS IS THE BODY OF THE PROJECT, AND UNTIL 06.09.2026 IT WAS NOT
    # HERE (audit F-3). Measurement on the saved residential complex: the op
    # carries `category: "mass"`, the registry returns
    # `("DirectShape", "OST_Mass")`, the census key `DirectShape` is
    # discarded, `OST_Mass` remains — and `category_of` was returning None,
    # because the table did not know this category. The podium body with the
    # atrium (8 KB of BRep in the store) did not reach the analysis AT ALL:
    # `hulls 0 · pairs 0 · findings 0`.
    #
    # CORRECTION TO THE AUDIT'S WORDING: what was missing was the
    # `OST_Mass` key, not "the mass category" — `mass` is an enum value on
    # the op. The difference is load-bearing: it is fixed by a table row,
    # not by a new kind of hull.
    #
    # MASS DOES NOT GO INTO MVP PAIRS (`mvp_side=None`), and this is not
    # caution: MVP pairs are "engineering against bearing", and mass is
    # neither. It takes part in the `all_physical_diagnostic` scope, where
    # ALL physical pairs are judged — that is where it belongs.
    "OST_Mass": KindRule(True, None, "mass",
                         "тело проекта: подиум, башня, проход"),
    "ImportInstance": KindRule(True, None, "import_instance"),
    # A truss is a CONTAINER: its bodies are its elements
    # (OST_StructuralFraming), which are already in the table. A hull is
    # built for the census, it does not go into MVP pairs, otherwise the
    # same metal would be counted twice.
    "OST_StructuralTruss": KindRule(True, None, "truss",
                                    "контейнер: тела — его элементы"),
    # Curtain-wall grid lines are a DATUM (layout), not a body.
    "OST_CurtainGridsWall": KindRule(False, None, "curtain_grid", "датум"),
    "OST_CurtainGridsRoof": KindRule(False, None, "curtain_grid", "датум"),
    "OST_CurtainGridsCurtaSystem": KindRule(False, None, "curtain_grid", "датум"),
    # ── R3, tower measurement of 19.08.2026 (`k2_ar_rd_v15`, 115 889
    #    elements). Outside the table there were 18 categories / 37 284
    #    elements, and sorting them by substance gives EXACTLY TWO physical
    #    ones: the remaining 16 (32 796 elements) are tags, text, callouts,
    #    partition lines, marks — annotation by nature, and their absence
    #    here is not a hole but the correct answer.
    #
    # Telephone devices: 4 479 units, ALL 4 479 HAVE A BOUNDING BOX (checked
    # element by element). Before this line they were going into
    # `kind_outside_table`, i.e. they were entirely invisible to the search
    # — the corpus's largest physical blind spot.
    #
    # HONESTLY ABOUT THE BODY: their bounding box is TALL — the first-row
    # measurement gives 500 x 540 x 5000 mm, because it is a `TwoLevelsBased`
    # family (the same fact by which the canon explains why `place_family`
    # does not pick them up). A five-meter box would intersect almost
    # everything on the floor, so MVP pairs are NOT GIVEN to them: the hull
    # is built for the CENSUS and visibility, not for a verdict. Promising
    # accuracy where the source is a bare bbox would amount to repeating
    # `confirmed` at the `coarse` grade.
    "OST_TelephoneDevices": KindRule(True, None, "telephone_device",
                                     "TwoLevelsBased: габарит высокий, "
                                     "оболочка ради переписи"),
    # ── OPENING: THE DECISION IS THE OPPOSITE OF "add what is missing", and
    #    here is why.
    #
    # `OST_FloorOpening` (9 units on the tower) is an ABSENCE of material, a
    # hole in the slab. Giving it a body would produce FALSE findings
    # exactly where the designer did everything right: a duct CORRECTLY
    # routed THROUGH the opening would clash with it. This is not caution
    # but a reversed sign: the instrument would report a conflict exactly
    # where the conflict is in fact resolved.
    #
    # A DECISION, NOT A MEASUREMENT, and hence named as such. It is cheaply
    # refuted: show an opening whose intersection with a body means a
    # defect — and the line changes. The data it was decided on: all 9
    # carry `geom_kind: bbox_only`, not one `host_id`, not one `type_name`.
    "OST_FloorOpening": KindRule(False, None, "opening",
                                 "проём — ОТСУТСТВИЕ материала, а не тело"),
    # HVAC spaces are a volume, not a body (like rooms).
    "OST_MEPSpaces": KindRule(False, None, "mep_space", "пространство, не тело"),
    # ── datums and annotations: there is no physical body, no hull exists
    "OST_Grids": KindRule(False, None, "grid", "датум"),
    "OST_Levels": KindRule(False, None, "level", "датум"),
    "OST_Areas": KindRule(False, None, "area", "аннотация"),
    "OST_RasterImages": KindRule(False, None, "raster", "аннотация"),
    "OST_Rooms": KindRule(False, None, "room", "пространство, не тело"),
    "OST_CLines": KindRule(False, None, "refplane", "датум"),
    "OST_Dimensions": KindRule(False, None, "dimension", "аннотация"),
    "OST_Lines": KindRule(False, None, "line", "аннотация"),
    "OST_SketchLines": KindRule(False, None, "sketch", "аннотация"),
}

#: MVP class pairs: cross-discipline clashes, the most expensive on the
#: construction site.
MVP_PAIR = ("mep", "struct")



#: Hull degeneracy: a body of zero volume. Not a reading error — that is
#: how the bounding box arrived from Revit; but a zero-volume hull CANNOT
#: prove a clash, and its pairs mean nothing, and before the wave of
#: 10.08.2026 nobody counted them.
#:
#: Measurement of 10.08.2026 across the whole store (65 readable
#: decompiles, 664 870 hulls with a bounding box): 64 357 are degenerate,
#: i.e. 9.7 %.
#:
#:   OST_GenericModel        35 225   (flat 32 306, points 2 919)
#:   OST_Furniture           14 088
#:   OST_PlumbingFixtures     8 591
#:   OST_StructuralFraming    6 408   ← the `struct` side of MVP pairs
#:   OST_SpecialityEquipment     45
#:   OST_Walls                    6
#:
#: HONESTLY ABOUT WHAT THIS MEANS. None of them has, in the data, an
#: independent witness of extent: no axis, no section, no height, no
#: contour — checked by the same measurement (`no_independent_witness` =
#: 67 108 of 67 108). So the law of containment here is NEITHER VIOLATED NOR
#: CONFIRMED: there is nothing to say that the body is wider than its
#: bounding box. Hence the report's form — a counter, not a refusal: the
#: number is published, no conclusion is drawn.
DEGENERACIES = ("ok", "aabb_point", "aabb_line", "aabb_plane",
                "prism_zero_area", "prism_zero_height", "prism_degenerate_footprint",
                "capsule_zero_radius")


def hull_degeneracy(hull: "G.Hull") -> str:
    """Name of hull degeneracy. `ok` — a body of non-zero volume.

    For a union, degeneracy is a property of the WHOLE body, not of a piece:
    a sweep legitimately produces segment-cells at the pinch points of a
    region, and declaring the whole floor zero because of one such cell
    would mean reading the census backwards.
    """
    if isinstance(hull, G.Capsule):
        return "capsule_zero_radius" if hull.radius <= 0.0 else "ok"
    if isinstance(hull, G.PrismSet):
        if not hull.pieces:
            return "prism_degenerate_footprint"
        if hull.z1 - hull.z0 <= 0.0:
            return "prism_zero_height"
        total = 0.0
        for fp in hull.pieces:
            n = len(fp)
            if n < 3:
                continue
            total += abs(sum(fp[i][0] * fp[(i + 1) % n][1]
                             - fp[(i + 1) % n][0] * fp[i][1] for i in range(n)))
        return "prism_zero_area" if total <= 0.0 else "ok"
    if isinstance(hull, G.Prism):
        fp = hull.footprint
        if len(fp) < 3:
            return "prism_degenerate_footprint"
        n = len(fp)
        area2 = sum(fp[i][0] * fp[(i + 1) % n][1] - fp[(i + 1) % n][0] * fp[i][1]
                    for i in range(n))
        if abs(area2) <= 0.0:
            return "prism_zero_area"
        return "prism_zero_height" if hull.z1 - hull.z0 <= 0.0 else "ok"
    lo, hi = hull.bounds()
    zero = sum(1 for k in range(3) if hi[k] - lo[k] <= 0.0)
    return {0: "ok", 1: "aabb_plane", 2: "aabb_line", 3: "aabb_point"}[zero]

INNER_CERTIFICATE_SCHEMA = "kir-certified-inner/2"

# A certificate is authority, not a bag of plausible strings.  The registry
# binds an issuer to the one proof rule it is allowed to assert.  The only
# issuer in this first vertical slice is deliberately a fixture producer: it
# must be handed an explicit analytic body and proves
# ``Inner ⊆ Body ⊆ Outer`` before minting anything.  Production Revit
# builders remain outer-only until they have an equally explicit body source.
ANALYTIC_TEST_INNER_ISSUER = "kir.clash.analytic-test-body/v1"
ANALYTIC_SUBSET_PROOF_KIND = "analytic-inner-subset/v1"
ANALYTIC_BODY_PROVENANCE = "explicit-analytic-body/v1"
INNER_CERTIFICATE_ISSUER_REGISTRY = {
    ANALYTIC_TEST_INNER_ISSUER: frozenset({ANALYTIC_SUBSET_PROOF_KIND}),
}
INNER_CERTIFICATE_PROVENANCE = frozenset({ANALYTIC_BODY_PROVENANCE})

# Process-local issuance authority.  A JSON mapping, dataclass constructor or
# deserialiser cannot obtain it.  This is an internal proof-capability marker,
# not a claim that Python can sandbox malicious code already running inside
# this module's process.
_INNER_CERTIFICATE_AUTHORITY = object()
_PAIR_PROOF_ISSUANCE_AUTHORITY = object()
_EXACT_BODY_EQUALITY_ISSUANCE_AUTHORITY = object()

# Serialized proof data crosses a trust boundary: unlike the in-memory
# authority marker above, a JSON client can copy every public field and
# recompute an ordinary SHA-256 content digest.  A per-process HMAC key seals
# the audit payload after a trusted producer has checked it.  This protects
# consumers from forged/tampered *serialized data*; it is deliberately not a
# Python sandbox for code already executing in this process.  The key is not
# persisted, so evidence loaded after a process restart fails closed.  That is
# the intended boundary for the current in-process/test-only producer.
_PROCESS_LOCAL_PROOF_KEY = secrets.token_bytes(32)
_INNER_CERTIFICATE_TAG_DOMAIN = b"kir-certified-inner-integrity/v1\x00"
_PAIR_PROOF_TAG_DOMAIN = b"kir-certified-inner-pair-integrity/v1\x00"
_EXACT_BODY_EQUALITY_TAG_DOMAIN = b"kir-exact-body-equality-integrity/v1\x00"


def _safe_certificate_value(certificate: object, name: str) -> Any:
    """Read even a deliberately malformed ``object.__new__`` fixture safely."""

    try:
        return getattr(certificate, name)
    except (AttributeError, TypeError):
        return None


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8")


def _process_local_integrity_tag(domain: bytes, payload: object) -> str:
    """Seal canonical data for an in-process proof consumer.

    This helper is private by design.  Its secrecy boundary is the random key,
    not the Python function name: arbitrary code in this process is trusted,
    while arbitrary serialized mappings are not.
    """

    return hmac.new(
        _PROCESS_LOCAL_PROOF_KEY, domain + _canonical_json_bytes(payload),
        hashlib.sha256).hexdigest()


def _verify_process_local_integrity_tag(
        domain: bytes, payload: object, tag: object) -> bool:
    if not _is_sha256_digest(tag):
        return False
    try:
        expected = _process_local_integrity_tag(domain, payload)
    except (TypeError, ValueError, OverflowError):
        return False
    return hmac.compare_digest(expected, tag)


def seal_serialized_pair_proof(
        payload: Mapping[str, Any], *, authority: object
        ) -> dict[str, Any]:
    """Attach audit digest + process-local integrity to one pair payload.

    Only ``detect.PhysicalOverlapProof.as_dict`` calls this.  The digest is
    public and reproducible; the integrity tag is the trust boundary.  They
    stay separate so tooling can address identical content without mistaking
    that address for authority.
    """

    if authority is not _PAIR_PROOF_ISSUANCE_AUTHORITY:
        raise PermissionError("pair proof must be issued by the narrow kernel")
    canonical = dict(payload)
    proof_digest = _sha256_json(canonical)
    sealed = {**canonical, "proof_digest": proof_digest}
    return {
        **sealed,
        "pair_integrity_tag": _process_local_integrity_tag(
            _PAIR_PROOF_TAG_DOMAIN, sealed),
    }


def verify_serialized_pair_proof_integrity(
        proof: Mapping[str, Any], *, payload_keys: frozenset[str]) -> bool:
    """Verify exactly one canonical pair payload, fail-closed.

    Semantic checks (schema, subjects, geometry relation and certificates)
    belong to ``detect.verify_serialized_physical_overlap_proof``.  This
    narrow primitive only proves that the complete mapping named by
    ``payload_keys`` is byte-for-byte the one sealed in this process.
    """

    expected_keys = payload_keys | {"proof_digest", "pair_integrity_tag"}
    if set(proof) != expected_keys:
        return False
    payload = {key: proof[key] for key in payload_keys}
    try:
        digest = _sha256_json(payload)
    except (TypeError, ValueError, OverflowError):
        return False
    if (not _is_sha256_digest(proof.get("proof_digest"))
            or not hmac.compare_digest(digest, proof["proof_digest"])):
        return False
    sealed = {**payload, "proof_digest": proof["proof_digest"]}
    return _verify_process_local_integrity_tag(
        _PAIR_PROOF_TAG_DOMAIN, sealed, proof.get("pair_integrity_tag"))


def seal_serialized_exact_body_equality_proof(
        payload: Mapping[str, Any], *, authority: object
        ) -> dict[str, Any]:
    """Seal an exact-body equality assertion under its own HMAC domain."""

    if authority is not _EXACT_BODY_EQUALITY_ISSUANCE_AUTHORITY:
        raise PermissionError(
            "exact-body proof must be issued by the equality kernel")
    canonical = dict(payload)
    proof_digest = _sha256_json(canonical)
    sealed = {**canonical, "proof_digest": proof_digest}
    return {
        **sealed,
        "equality_integrity_tag": _process_local_integrity_tag(
            _EXACT_BODY_EQUALITY_TAG_DOMAIN, sealed),
    }


def verify_serialized_exact_body_equality_integrity(
        proof: Mapping[str, Any], *, payload_keys: frozenset[str]) -> bool:
    """Verify exact-body proof content + process-local authority.

    The process-local key is intentionally lost on restart.  Persisted proof
    JSON therefore becomes non-authoritative instead of being silently
    upgraded from its publicly reproducible SHA-256 digest.
    """

    expected_keys = payload_keys | {"proof_digest", "equality_integrity_tag"}
    if set(proof) != expected_keys:
        return False
    payload = {key: proof[key] for key in payload_keys}
    try:
        digest = _sha256_json(payload)
    except (TypeError, ValueError, OverflowError):
        return False
    if (not _is_sha256_digest(proof.get("proof_digest"))
            or not hmac.compare_digest(digest, proof["proof_digest"])):
        return False
    sealed = {**payload, "proof_digest": proof["proof_digest"]}
    return _verify_process_local_integrity_tag(
        _EXACT_BODY_EQUALITY_TAG_DOMAIN, sealed,
        proof.get("equality_integrity_tag"))


def _canonical_analytic_hull(hull: G.Hull) -> dict[str, Any]:
    """Canonical source material for the supported analytic proof kernel."""

    if _analytic_vertices(hull) is None:
        raise ValueError("analytic_hull_invalid_or_unsupported")
    if isinstance(hull, G.Aabb):
        return {
            "type": "Aabb",
            "lo": [G._norm_zero(float(value)) for value in hull.lo],
            "hi": [G._norm_zero(float(value)) for value in hull.hi],
        }
    if isinstance(hull, G.Prism):
        return {
            "type": "Prism",
            "footprint": [[G._norm_zero(float(x)), G._norm_zero(float(y))]
                          for x, y in hull.footprint],
            "z0": G._norm_zero(float(hull.z0)),
            "z1": G._norm_zero(float(hull.z1)),
        }
    # `_analytic_vertices` and the two branches above are one closed table.
    raise ValueError("analytic_hull_type_unsupported")


def analytic_hull_digest(hull: G.Hull) -> str:
    """Content digest used to bind a certificate to explicit body evidence."""

    return _sha256_json(_canonical_analytic_hull(hull))


def _certificate_payload(*, issuer: str, proof_kind: str, provenance: str,
                         revision: str, subject_source_id: str,
                         body_source_digest: str,
                         body_source_revision: str, inner_digest: str,
                         outer_digest: str, error_bound_mm: float,
                         tolerance_mm: float) -> dict[str, Any]:
    return {
        "schema_version": INNER_CERTIFICATE_SCHEMA,
        "issuer": issuer,
        "proof_kind": proof_kind,
        "provenance": provenance,
        "revision": revision,
        "subject_source_id": subject_source_id,
        "body_source_digest": body_source_digest,
        "body_source_revision": body_source_revision,
        "inner_digest": inner_digest,
        "outer_digest": outer_digest,
        "error_bound_mm": G._norm_zero(float(error_bound_mm)),
        "tolerance_mm": G._norm_zero(float(tolerance_mm)),
    }


@dataclass(frozen=True, init=False)
class InnerHullCertificate:
    """Opaque authority carried by an analytic ``Inner ⊆ Body`` witness.

    Direct construction is forbidden.  The public fields are an audit trail;
    they are not independently authoritative.  Only a registered producer may
    attach the process-local issuance marker after checking its proof rule.

    ``error_bound_mm`` is the producer's maximum geometric error and
    ``tolerance_mm`` the maximum accepted error.  Both only make confirmation
    harder: the detector requires penetration deeper than their combined sum.
    """

    issuer: str
    proof_kind: str
    provenance: str
    revision: str
    subject_source_id: str
    body_source_digest: str
    body_source_revision: str
    inner_digest: str
    outer_digest: str
    error_bound_mm: float
    tolerance_mm: float
    certificate_digest: str
    integrity_tag: str
    schema_version: str
    _authority: object = field(repr=False, compare=False)

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError(
            "InnerHullCertificate is opaque; use a registered issuer")

    def as_dict(self) -> dict[str, Any]:
        def string_or_none(name: str) -> str | None:
            value = _safe_certificate_value(self, name)
            return value if isinstance(value, str) else None

        error = _safe_certificate_value(self, "error_bound_mm")
        tolerance = _safe_certificate_value(self, "tolerance_mm")
        return {
            "schema_version": string_or_none("schema_version"),
            "issuer": string_or_none("issuer"),
            "proof_kind": string_or_none("proof_kind"),
            "provenance": string_or_none("provenance"),
            "revision": string_or_none("revision"),
            "subject_source_id": string_or_none("subject_source_id"),
            "body_source_digest": string_or_none("body_source_digest"),
            "body_source_revision": string_or_none("body_source_revision"),
            "inner_digest": string_or_none("inner_digest"),
            "outer_digest": string_or_none("outer_digest"),
            "error_bound_mm": float(error) if G._finite(error) else None,
            "tolerance_mm": (float(tolerance)
                             if G._finite(tolerance) else None),
            "certificate_digest": string_or_none("certificate_digest"),
            "integrity_tag": string_or_none("integrity_tag"),
        }


@dataclass(frozen=True)
class CertifiedInnerHull:
    """Optional analytic ``Inner ⊆ Body`` witness.

    ``certificate`` is optional in the Python type on purpose: it makes the
    malformed state representable and therefore testable.  Validation names
    ``inner_certificate_missing`` and downgrades to ``possible``; it never
    infers a certificate from the hull type or from an outer grade.
    """

    hull: G.Hull
    certificate: InnerHullCertificate | None


@dataclass(frozen=True)
class InnerHullAssessment:
    status: str                    # absent | valid | rejected
    reason: str | None
    hull: G.Hull | None = field(default=None, repr=False)
    certificate: InnerHullCertificate | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "certificate": (
                None if self.certificate is None
                else self.certificate.as_dict()),
            "hull_type": None if self.hull is None else type(self.hull).__name__,
        }


def _analytic_vertices(hull: G.Hull) -> tuple[G.Pt3, ...] | None:
    if isinstance(hull, G.Aabb):
        lo, hi = hull.lo, hull.hi
        if any(not math.isfinite(v) for v in (*lo, *hi)):
            return None
        if any(hi[i] - lo[i] <= G.EPS_MM for i in range(3)):
            return None
        return tuple(
            (x, y, z)
            for x in (lo[0], hi[0])
            for y in (lo[1], hi[1])
            for z in (lo[2], hi[2]))
    if isinstance(hull, G.Prism):
        if (len(hull.footprint) < 3
                or not D.loop_is_convex(hull.footprint)
                or hull.z1 - hull.z0 <= G.EPS_MM):
            return None
        return tuple((x, y, z) for x, y in hull.footprint
                     for z in (hull.z0, hull.z1))
    return None


def _analytic_inner_is_nested(inner: G.Hull, outer: G.Hull) -> bool:
    """Exact convex containment check for the first supported kernel types.

    Every vertex of one convex Aabb/Prism lying in the other convex body is
    necessary and sufficient for containment.  No certificate tolerance is
    applied here: a tolerance that widened Outer would weaken the invariant.
    """

    vertices = _analytic_vertices(inner)
    if vertices is None or _analytic_vertices(outer) is None:
        return False
    return all(G.contains_point(outer, point) for point in vertices)


def _is_sha256_digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


_SERIALIZED_INNER_CERTIFICATE_KEYS = frozenset({
    "schema_version", "issuer", "proof_kind", "provenance", "revision",
    "subject_source_id", "body_source_digest", "body_source_revision",
    "inner_digest", "outer_digest", "error_bound_mm", "tolerance_mm",
    "certificate_digest", "integrity_tag",
})


def verify_serialized_inner_certificate(
        certificate: Mapping[str, Any], *,
        expected_subject_source_id: str) -> bool:
    """Verify authority of a serialized inner certificate, fail-closed.

    The public content digest detects ordinary corruption but is forgeable by
    anyone who can serialize JSON.  Authority therefore requires the
    process-local HMAC as well.  A valid tag means this process' registered
    producer already checked ``Inner ⊆ Body ⊆ Outer``; it is intentionally
    invalid after restart because the current producer is in-process only.
    """

    if (not isinstance(certificate, Mapping)
            or set(certificate) != _SERIALIZED_INNER_CERTIFICATE_KEYS):
        return False
    schema = certificate.get("schema_version")
    issuer = certificate.get("issuer")
    proof_kind = certificate.get("proof_kind")
    provenance = certificate.get("provenance")
    revision = certificate.get("revision")
    subject = certificate.get("subject_source_id")
    body_revision = certificate.get("body_source_revision")
    if (schema != INNER_CERTIFICATE_SCHEMA
            or not isinstance(issuer, str)
            or issuer not in INNER_CERTIFICATE_ISSUER_REGISTRY
            or not isinstance(proof_kind, str)
            or proof_kind not in INNER_CERTIFICATE_ISSUER_REGISTRY[issuer]
            or provenance not in INNER_CERTIFICATE_PROVENANCE
            or not isinstance(revision, str) or not revision.strip()
            or not isinstance(subject, str) or not subject.strip()
            or subject != expected_subject_source_id
            or not isinstance(body_revision, str)
            or not body_revision.strip()):
        return False
    body_digest = certificate.get("body_source_digest")
    inner_digest = certificate.get("inner_digest")
    outer_digest = certificate.get("outer_digest")
    content_digest = certificate.get("certificate_digest")
    integrity_tag = certificate.get("integrity_tag")
    if not all(_is_sha256_digest(value) for value in (
            body_digest, inner_digest, outer_digest, content_digest,
            integrity_tag)):
        return False
    error = certificate.get("error_bound_mm")
    tolerance = certificate.get("tolerance_mm")
    if (isinstance(error, bool) or not isinstance(error, (int, float))
            or isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(float(error))
            or not math.isfinite(float(tolerance))
            or float(error) < 0.0 or float(tolerance) < 0.0
            or float(error) > float(tolerance)):
        return False
    payload = _certificate_payload(
        issuer=issuer, proof_kind=proof_kind, provenance=provenance,
        revision=revision, subject_source_id=subject,
        body_source_digest=body_digest,
        body_source_revision=body_revision, inner_digest=inner_digest,
        outer_digest=outer_digest, error_bound_mm=float(error),
        tolerance_mm=float(tolerance))
    try:
        expected_digest = _sha256_json(payload)
    except (TypeError, ValueError, OverflowError):
        return False
    if not hmac.compare_digest(expected_digest, content_digest):
        return False
    sealed_payload = {**payload, "certificate_digest": content_digest}
    return _verify_process_local_integrity_tag(
        _INNER_CERTIFICATE_TAG_DOMAIN, sealed_payload, integrity_tag)


def certify_analytic_inner_for_test(
        *, inner: G.Hull, body: G.Hull, outer: G.Hull,
        subject_source_id: str, body_source_digest: str,
        body_source_revision: str,
        revision: str = "analytic-test-r1", error_bound_mm: float = 0.0,
        tolerance_mm: float = 0.0) -> CertifiedInnerHull:
    """Issue fixture evidence after proving ``Inner ⊆ Body ⊆ Outer``.

    This intentionally is *not* a generic certificate constructor.  It is the
    sole registered analytic fixture producer until a Revit body extractor can
    provide equivalent source evidence.  The caller must pass both the body
    itself and the digest/revision of that same source; contradictory evidence
    is refused before a certificate exists.
    """

    issuer = ANALYTIC_TEST_INNER_ISSUER
    proof_kind = ANALYTIC_SUBSET_PROOF_KIND
    provenance = ANALYTIC_BODY_PROVENANCE
    if proof_kind not in INNER_CERTIFICATE_ISSUER_REGISTRY.get(
            issuer, frozenset()):
        raise RuntimeError("inner_certificate_issuer_not_registered")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("inner_certificate_revision_missing")
    if not isinstance(subject_source_id, str) or not subject_source_id.strip():
        raise ValueError("inner_certificate_subject_missing")
    if (not isinstance(body_source_revision, str)
            or not body_source_revision.strip()):
        raise ValueError("body_source_revision_missing")
    if not (G._finite(error_bound_mm) and G._finite(tolerance_mm)):
        raise ValueError("inner_certificate_error_non_finite")
    if error_bound_mm < 0.0 or tolerance_mm < 0.0:
        raise ValueError("inner_certificate_error_negative")
    if error_bound_mm > tolerance_mm:
        raise ValueError("inner_certificate_error_exceeds_tolerance")

    # Each digest call also rejects unsupported, non-finite, non-convex and
    # zero-volume analytic bodies.  No Capsule is silently promoted to an
    # inner hull merely because its outer approximation has a radius.
    inner_digest = analytic_hull_digest(inner)
    actual_body_digest = analytic_hull_digest(body)
    outer_digest = analytic_hull_digest(outer)
    if (not _is_sha256_digest(body_source_digest)
            or body_source_digest != actual_body_digest):
        raise ValueError("body_source_digest_mismatch")
    if not _analytic_inner_is_nested(inner, body):
        raise ValueError("inner_not_contained_in_body")
    if not _analytic_inner_is_nested(body, outer):
        raise ValueError("body_not_contained_in_outer")

    payload = _certificate_payload(
        issuer=issuer, proof_kind=proof_kind, provenance=provenance,
        revision=revision.strip(), subject_source_id=subject_source_id.strip(),
        body_source_digest=actual_body_digest,
        body_source_revision=body_source_revision.strip(),
        inner_digest=inner_digest, outer_digest=outer_digest,
        error_bound_mm=float(error_bound_mm),
        tolerance_mm=float(tolerance_mm))
    certificate = object.__new__(InnerHullCertificate)
    for name, value in payload.items():
        object.__setattr__(certificate, name, value)
    object.__setattr__(certificate, "certificate_digest",
                       _sha256_json(payload))
    sealed_payload = {
        **payload,
        "certificate_digest": _safe_certificate_value(
            certificate, "certificate_digest"),
    }
    object.__setattr__(certificate, "integrity_tag",
                       _process_local_integrity_tag(
                           _INNER_CERTIFICATE_TAG_DOMAIN, sealed_payload))
    object.__setattr__(certificate, "_authority",
                       _INNER_CERTIFICATE_AUTHORITY)
    return CertifiedInnerHull(inner, certificate)


def assess_inner_hull(record: "HullRecord") -> InnerHullAssessment:
    """Validate optional inner evidence without ever upgrading malformed data."""

    evidence = record.inner
    if evidence is None:
        return InnerHullAssessment("absent", "inner_evidence_absent")
    if not isinstance(evidence, CertifiedInnerHull):
        return InnerHullAssessment("rejected", "inner_evidence_type_invalid")
    inner = evidence.hull
    certificate = evidence.certificate
    if certificate is None:
        return InnerHullAssessment(
            "rejected", "inner_certificate_missing", hull=inner)
    if not isinstance(certificate, InnerHullCertificate):
        return InnerHullAssessment(
            "rejected", "inner_certificate_type_invalid", hull=inner)
    if (_safe_certificate_value(certificate, "_authority")
            is not _INNER_CERTIFICATE_AUTHORITY):
        return InnerHullAssessment(
            "rejected", "inner_certificate_not_issued", inner, certificate)
    schema_version = _safe_certificate_value(certificate, "schema_version")
    if schema_version != INNER_CERTIFICATE_SCHEMA:
        return InnerHullAssessment(
            "rejected", "inner_certificate_schema_unsupported", inner,
            certificate)
    issuer = _safe_certificate_value(certificate, "issuer")
    proof_kind = _safe_certificate_value(certificate, "proof_kind")
    if (not isinstance(issuer, str)
            or issuer not in INNER_CERTIFICATE_ISSUER_REGISTRY):
        return InnerHullAssessment(
            "rejected", "inner_certificate_issuer_untrusted", inner,
            certificate)
    if (not isinstance(proof_kind, str)
            or proof_kind not in INNER_CERTIFICATE_ISSUER_REGISTRY[issuer]):
        return InnerHullAssessment(
            "rejected", "inner_certificate_proof_kind_unsupported", inner,
            certificate)
    provenance = _safe_certificate_value(certificate, "provenance")
    if (not isinstance(provenance, str)
            or provenance not in INNER_CERTIFICATE_PROVENANCE):
        return InnerHullAssessment(
            "rejected", "inner_certificate_provenance_untrusted", inner,
            certificate)
    revision = _safe_certificate_value(certificate, "revision")
    if not isinstance(revision, str) or not revision.strip():
        return InnerHullAssessment(
            "rejected", "inner_certificate_revision_missing", inner,
            certificate)
    subject_source_id = _safe_certificate_value(
        certificate, "subject_source_id")
    if (not isinstance(subject_source_id, str)
            or not subject_source_id.strip()):
        return InnerHullAssessment(
            "rejected", "inner_certificate_subject_missing", inner,
            certificate)
    if subject_source_id != record.source_id:
        return InnerHullAssessment(
            "rejected", "inner_certificate_subject_mismatch", inner,
            certificate)
    body_source_revision = _safe_certificate_value(
        certificate, "body_source_revision")
    if (not isinstance(body_source_revision, str)
            or not body_source_revision.strip()):
        return InnerHullAssessment(
            "rejected", "inner_certificate_body_revision_missing", inner,
            certificate)
    body_source_digest = _safe_certificate_value(
        certificate, "body_source_digest")
    inner_digest = _safe_certificate_value(certificate, "inner_digest")
    outer_digest = _safe_certificate_value(certificate, "outer_digest")
    certificate_digest = _safe_certificate_value(
        certificate, "certificate_digest")
    integrity_tag = _safe_certificate_value(certificate, "integrity_tag")
    if not all(_is_sha256_digest(value) for value in (
            body_source_digest, inner_digest, outer_digest,
            certificate_digest, integrity_tag)):
        return InnerHullAssessment(
            "rejected", "inner_certificate_digest_invalid", inner,
            certificate)
    error = _safe_certificate_value(certificate, "error_bound_mm")
    tolerance = _safe_certificate_value(certificate, "tolerance_mm")
    if not (G._finite(error) and G._finite(tolerance)):
        return InnerHullAssessment(
            "rejected", "inner_certificate_error_non_finite", inner,
            certificate)
    if error < 0.0 or tolerance < 0.0:
        return InnerHullAssessment(
            "rejected", "inner_certificate_error_negative", inner,
            certificate)
    if error > tolerance:
        return InnerHullAssessment(
            "rejected", "inner_certificate_error_exceeds_tolerance", inner,
            certificate)
    if not isinstance(inner, (G.Aabb, G.Prism)):
        return InnerHullAssessment(
            "rejected", f"inner_hull_type_unsupported:{type(inner).__name__}",
            inner, certificate)
    if not isinstance(record.hull, (G.Aabb, G.Prism)):
        return InnerHullAssessment(
            "rejected",
            f"outer_hull_type_unsupported:{type(record.hull).__name__}",
            inner, certificate)
    if _analytic_vertices(inner) is None:
        return InnerHullAssessment(
            "rejected", "inner_hull_invalid_or_zero_volume", inner,
            certificate)
    try:
        actual_inner_digest = analytic_hull_digest(inner)
        actual_outer_digest = analytic_hull_digest(record.hull)
    except ValueError:
        return InnerHullAssessment(
            "rejected", "inner_certificate_geometry_digest_unavailable",
            inner, certificate)
    if inner_digest != actual_inner_digest:
        return InnerHullAssessment(
            "rejected", "inner_certificate_inner_digest_mismatch", inner,
            certificate)
    if outer_digest != actual_outer_digest:
        return InnerHullAssessment(
            "rejected", "inner_certificate_outer_digest_mismatch", inner,
            certificate)
    payload = _certificate_payload(
        issuer=issuer, proof_kind=proof_kind, provenance=provenance,
        revision=revision, subject_source_id=subject_source_id,
        body_source_digest=body_source_digest,
        body_source_revision=body_source_revision,
        inner_digest=inner_digest, outer_digest=outer_digest,
        error_bound_mm=float(error), tolerance_mm=float(tolerance))
    if certificate_digest != _sha256_json(payload):
        return InnerHullAssessment(
            "rejected", "inner_certificate_integrity_mismatch", inner,
            certificate)
    sealed_payload = {**payload, "certificate_digest": certificate_digest}
    if not _verify_process_local_integrity_tag(
            _INNER_CERTIFICATE_TAG_DOMAIN, sealed_payload, integrity_tag):
        return InnerHullAssessment(
            "rejected", "inner_certificate_integrity_tag_mismatch", inner,
            certificate)
    if not _analytic_inner_is_nested(inner, record.hull):
        return InnerHullAssessment(
            "rejected", "inner_not_contained_in_outer", inner, certificate)
    return InnerHullAssessment("valid", None, inner, certificate)


@dataclass
class HullRecord:
    """One snapshot record: the hull and everything that justifies it."""
    source_id: str
    category: str
    label: str
    mvp_side: str | None
    hull: G.Hull
    grade: str
    hull_source: str          # profile | axis_section | bbox
    level_id: str | None = None
    type_name: str | None = None
    #: The section that justifies the hull (wave D2-A). `None` — either the
    #: element has no section OR its category is not allowed the
    #: `axis_section` source; distinguishing these two cases is the job of
    #: the snapshot census, not this field.
    section_radius_mm: float | None = None
    section_round: bool | None = None
    #: Name of the L0 parameter(s) the number was taken from. Without it a
    #: report cannot say WHAT justifies the hull — and "conservative"
    #: without a justification is no better than "coarse".
    section_source: str | None = None
    extra: dict = field(default_factory=dict)
    #: Optional ``Inner ⊆ Body`` evidence.  Existing production builders
    #: intentionally leave it absent; in particular capsules are never
    #: promoted to inner merely because they came from a section parameter.
    inner: CertifiedInnerHull | None = None

    def bounds(self):
        return self.hull.bounds()


@dataclass
class Refusal:
    source_id: str
    category: str
    bucket: str               # unsupported | missing_geometry | not_eligible
    reason: str


def _pt3(v: Any) -> G.Pt3 | None:
    if isinstance(v, (list, tuple)) and len(v) >= 3 and all(G._finite(x) for x in v[:3]):
        return (float(v[0]), float(v[1]), float(v[2]))
    return None


def _valid_box(lo: Any, hi: Any) -> tuple[G.Pt3, G.Pt3] | None:
    a, b = _pt3(lo), _pt3(hi)
    if a is None or b is None:
        return None
    lo3 = tuple(min(a[i], b[i]) for i in range(3))
    hi3 = tuple(max(a[i], b[i]) for i in range(3))
    if any(hi3[i] - lo3[i] < 0 for i in range(3)):
        return None
    return lo3, hi3


def arc_chord_polyline(arc: dict, p0: G.Pt3, p1: G.Pt3, *,
                       max_sagitta_mm: float = 25.0) -> tuple[list[G.Pt3], float]:
    """Arc -> polyline of chords + the maximum sag that it must be inflated
    by.

    Review #10: "a chord inflated by a sag" is not defined until it is said
    by exactly how much and in which direction. Here the arc is cut into as
    many chords as needed so that each one's sag does not exceed the named
    threshold, and the ACTUAL sag is returned — the hull is inflated by it.
    Arcs greater than π are cut by the same rule, with no special case.
    """
    c = _pt3(arc.get("center_mm"))
    r = arc.get("radius_mm")
    a0, a1 = arc.get("start_angle_rad"), arc.get("end_angle_rad")
    xa, ya = _pt3(arc.get("x_axis")), _pt3(arc.get("y_axis"))
    if c is None or not G._finite(r) or r <= 0 or not G._finite(a0) \
            or not G._finite(a1) or xa is None or ya is None:
        return [p0, p1], 0.0
    span = abs(float(a1) - float(a0))
    if span <= G.EPS_MM:
        return [p0, p1], 0.0
    # n chords -> sub-chord sag r*(1-cos(span/2n)). THE FORMULA HOLDS ONLY
    # WHILE THE SUB-ARC IS NOT GREATER THAN π: at span/n > π the cosine
    # wraps around, and the condition "the sag is small" passes FALSELY.
    # Measurement of the hole (cross-check against the BHoM pair checklist,
    # where Circle is a separate type): at span ≈ 4π (715°…730°, 1440°) n=1
    # gave cos(2π)=1, i.e. sag=0, the arc was substituted by ONE chord, and
    # the body escaped the hull by 5 900 mm at r=3000 — the same violation
    # of the conservativeness law as finding #1 of the hardening.
    #
    # Hence the number of chords is bounded below by ceil(span/π): the
    # sub-arc is NEVER greater than π, and the formula is applied only
    # within its domain of validity.
    n = max(1, math.ceil(span / math.pi))
    while n < 4096:
        sag = float(r) * (1.0 - math.cos(span / (2 * n)))
        if sag <= max_sagitta_mm:
            break
        n += 1
    pts: list[G.Pt3] = []
    for i in range(n + 1):
        ang = float(a0) + (float(a1) - float(a0)) * (i / n)
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        pts.append(tuple(c[k] + float(r) * (cos_a * xa[k] + sin_a * ya[k])
                         for k in range(3)))
    return pts, float(r) * (1.0 - math.cos(span / (2 * n)))


@dataclass(frozen=True)
class Section:
    """The read section: the hull radius and what justifies it."""
    radius_mm: float
    round: bool
    source: str
    #: outer | modelled | rect — readings that contain the body. `nominal`
    #: never falls here: it is returned as a separate field,
    #: `nominal_radius_mm`.
    kind: str = "rect"


def category_allows_sections(category: str) -> bool:
    """Whether the CATEGORY is allowed to justify a hull by a section.

    Two conditions at once, and both are mandatory: the reading rule
    (`SECTION_RULES`) and the table's permission (`sources`). A wall today
    has the number but not the permission — and this is a prohibition, not
    an absence of data (review #2).
    """
    rule = KIND_TABLE.get(category)
    return (rule is not None and "axis_section" in rule.sources
            and category in SECTION_RULES)


def section_from_params(category: str, params: Any
                        ) -> tuple[Section | None, str, float | None]:
    """The element's section from the `params` of the L0 row.

    Returns `(Section|None, reason, nominal radius|None)`.

    The reason for absence is ALWAYS NAMED: `no_section_rule` (the category
    is not allowed a section), `section_absent` (there are no numbers),
    `section_nominal_only` (a number exists, but it is a NOMINAL, and it
    does not contain the body — R3 of the red findings). A silent `None`
    never happens.

    The nominal is returned as the third element rather than discarded: it
    stays in the record's receipt, so that "there is no outer" is
    distinguishable from "there is no section".

    If both kinds of section are readable (an oval duct carries both a
    diameter and a width with a height), the LARGER radius is taken: the
    smaller one might not contain the body, and coarsening is only
    legitimate upward.
    """
    if not category_allows_sections(category):
        return None, "no_section_rule", None
    rule = SECTION_RULES[category]
    p = params if isinstance(params, dict) else {}
    best: Section | None = None
    nominal: float | None = None

    def offer(cand: Section) -> None:
        nonlocal best
        if best is None or cand.radius_mm > best.radius_mm:
            best = cand

    for name in rule["round"]:
        d = p.get(name)
        if not (G._finite(d) and d > 0):
            continue
        kind = DIAMETER_KIND.get(name, "nominal")
        if kind in DIAMETER_KIND_ALLOWED:
            offer(Section(float(d) / 2.0, True, name, kind))
        else:
            # A nominal NEVER builds a hull, but it does not disappear
            # either.
            r = float(d) / 2.0
            nominal = r if nominal is None else max(nominal, r)
    for w_name, h_name in rule["rect"]:
        w, h = p.get(w_name), p.get(h_name)
        if G._finite(w) and G._finite(h) and w > 0 and h > 0:
            offer(Section(math.hypot(float(w), float(h)) / 2.0, False,
                          f"{w_name}+{h_name}", "rect"))
    if best is None:
        return None, ("section_nominal_only" if nominal is not None
                      else "section_absent"), nominal
    return best, "", nominal


def carries_section_number(params: Any) -> bool:
    """Whether the element has AT LEAST ONE positive section number in
    `params`.

    This is needed not by the hull but by the census: a wall with a
    thickness of 200 mm and a wall without one are different facts, even
    when both receive a bounding box. Without this counter, "hulls did not
    come up" is indistinguishable from "parameters are not read".
    """
    p = params if isinstance(params, dict) else {}
    return any(G._finite(p.get(n)) and p.get(n) > 0
               for n in ALL_SECTION_PARAM_NAMES)


def wall_prism_blockers(el: dict) -> tuple[str, ...]:
    """What is MISSING to allow a wall a prism by a single thickness.

    Code review #10: for an ordinary straight wall of constant thickness the
    total width is indeed sufficient, but L0 cannot distinguish it from
    slanted/tapered, stacked, vertically compound, and a wall with sweeps —
    and for each of these a prism by `width` does NOT contain the body.
    Until they can be told apart, there is only one honest hull: the
    bounding box.

    The function returns the NAMES of the missing proofs, not a bool: "not
    allowed" without a reason is the same silence that the law of the
    census guards against.
    """
    params = el.get("params") if isinstance(el.get("params"), dict) else {}
    return tuple(name for name in WALL_PRISM_EVIDENCE if name not in params)


#: `WALL_KEY_REF_PARAM` — which PLANE of the wall its axis is. Revit
#: enumeration values: 0 — wall centerline, 1 — core centerline, 2..5 —
#: faces (finish and core, exterior/interior). Measurement v18: for 213 of
#: 215 candidate walls the axis lies on a FACE (`3`), for 2 more — also a
#: face (`2`). Not one centerline.
WALL_KEY_REF_CENTRELINE = 0


def wall_axis_halfwidth(width_mm: float, key_ref: Any) -> float:
    """Half-width of the band around the axis that CONTAINS the body for
    any answer.

    If the axis is the wall centerline (`key_ref == 0`), the body lies
    within ±width/2, and this is proven. In every other case the axis lies
    on a face (or on the CORE centerline, which for asymmetric layers does
    not coincide with the wall centerline), i.e. the body is offset to one
    side — and the SIDE is not resolved in L0: the sign depends on the
    wall's orientation, which is not in the artifact.

    Guessing the side is not allowed — a sign error shifts the hull PAST
    the body. But it is mandatory to contain the body for any answer, and
    the body, for any offset, lies within ±width of the axis. So there are
    exactly two outcomes here: a proven centerline gives width/2, everything
    else gives width. This is a twofold coarsening, and it is NAMED, not
    hidden.
    """
    w = float(width_mm)
    return w / 2.0 if key_ref == WALL_KEY_REF_CENTRELINE else w


def hull_from_wall_axis(p0: G.Pt3, p1: G.Pt3, *, width_mm: float,
                        z0: float, z1: float,
                        offset_mm: float = 0.0) -> G.Prism | None:
    """A band around the wall axis × [z0, z1] — a builder for a FUTURE
    wave.

    Written per the requirement of review #10 as a builder for a FUTURE
    wave — and since 14.08.2026 it IS CALLED: `OST_Walls` was switched to
    `SOURCES_PRISM`, because otherwise a declared wall received no body at
    all (`refused_by_hull_gate`), and the owner's scene stayed empty for a
    fully declared program.

    🔴 THIS LINE, UNTIL 15.08, ASSERTED THE OPPOSITE — "not called from any
    path, `OST_Walls` remains on `SOURCES_BBOX`" — already after the table
    had been switched over. Nobody mutates prose: no run turns red because
    a comment lies, and the reader will believe it before the code. If you
    put a promise here, put its boundary here too.

    The measurement this switch was made for: `sources=('bbox',)` → 0
    bodies, `sources=('prism',)` → 1 body, grade `conservative`. The band
    is admitted EXACTLY where there is nothing else to measure with, and
    its conservativeness is proven by a test IN ADVANCE, not declared here.

    `offset_mm` — the body's offset relative to the axis along the left
    normal (location line: a face instead of the centerline). It is
    ACCEPTED as a number rather than derived from `WALL_KEY_REF_PARAM`: the
    sign depends on the wall's orientation, which is not in L0, and
    guessing it would mean shifting the hull to the wrong side.
    """
    if not (G._finite(width_mm) and width_mm > 0):
        return None
    d = G._sub(p1, p0)
    L = math.hypot(d[0], d[1])
    if L <= G.EPS_MM:
        return None
    nx, ny = -d[1] / L, d[0] / L          # left normal in plan
    half = float(width_mm) / 2.0
    cx, cy = nx * float(offset_mm), ny * float(offset_mm)
    corners = []
    for base in ((p0[0] + cx, p0[1] + cy), (p1[0] + cx, p1[1] + cy)):
        corners.append((base[0] + nx * half, base[1] + ny * half))
        corners.append((base[0] - nx * half, base[1] - ny * half))
    fp = G.convex_footprint(corners)
    if len(fp) < 3:
        return None
    lo, hi = (z0, z1) if z0 <= z1 else (z1, z0)
    return G.Prism(fp, lo, hi)


def _z_span(el: dict) -> tuple[float, float] | None:
    """The Z-extent DECLARED by the element, or `None`.

    Exists because a DECLARATION has no bounding box at all: the program
    knows the level elevation and the height, but does not know what Revit
    will build from that. An L0 decompile, conversely, carries a real
    bounding box and has none of these keys — so its behavior here does not
    change by a single byte.
    """
    z0, z1 = el.get("z0_mm"), el.get("z1_mm")
    if not (G._finite(z0) and G._finite(z1)):
        return None
    lo, hi = float(z0), float(z1)
    return (lo, hi) if lo <= hi else (hi, lo)


#: What must be present in `el["prism"]` for a band around the axis to have
#: something to be justified by. The list is closed: a missing key is a
#: named fallback to the bounding box, not a reason to "take what there is".
PRISM_REQUIRED = ("width_mm", "uniform")


def _prism_record(el: dict, common: dict,
                  z_span: tuple[float, float] | None
                  ) -> tuple[HullRecord | None, str]:
    """A band around the wall axis. Returns `(record|None, fallback reason)`.

    WHY THE OFFSET IS EXACTLY ZERO. A live measurement of 28.07.2026 (Revit
    2023, the operator's document, 700+ real walls,
    `docs/2026-07-28-location-line-measurement.md`): the wall body is
    SYMMETRIC about the `LocationCurve` for ANY ordinal of
    `WALL_KEY_REF_PARAM` — for a 200 mm wall the bounding box along Y lies
    within −100…+100, and none of the six ordinals moves either the curve or
    the body. Hence `width/2` here, not the doubling from
    `wall_axis_halfwidth`: the doubling guards against an UNKNOWN offset
    side, and a declared wall has no offset — this is measured, not
    assumed.
    """
    prism = el.get("prism")
    if not isinstance(prism, dict):
        return None, ""
    missing = [key for key in PRISM_REQUIRED if key not in prism]
    if missing:
        return None, "prism_incomplete_" + "+".join(sorted(missing))
    if not prism.get("uniform"):
        blockers = prism.get("blockers") or ()
        return None, ("prism_blocked_" + "+".join(sorted(str(b) for b in blockers))
                      if blockers else "prism_blocked")
    width = prism.get("width_mm")
    if not (G._finite(width) and width > 0):
        return None, "prism_width_invalid"
    if z_span is None:
        return None, "prism_z_span_missing"
    p0, p1 = _pt3(el.get("p0_mm")), _pt3(el.get("p1_mm"))
    if p0 is None or p1 is None:
        return None, "prism_endpoints_missing"
    hull = hull_from_wall_axis(p0, p1, width_mm=float(width),
                               z0=z_span[0], z1=z_span[1])
    if hull is None:
        return None, "prism_zero_length"
    extra = {"prism_width_mm": float(width),
             "prism_source": str(prism.get("source") or "")}
    return HullRecord(hull=hull, grade="conservative", hull_source="prism",
                      extra=extra, **common), ""


#: The kinds of contour curves that the hull is able to BOUND FROM OUTSIDE.
#: The list is closed: everything else (ellipse, spline, hyperbola) is a
#: named refusal, because we have no proven outward approximation for them.
PROFILE_CURVE_KINDS = ("line", "arc")


def _arc_outward_rect(p0: G.Pt2, p1: G.Pt2, mid: G.Pt2
                      ) -> tuple[float, G.Pt2] | str:
    """The arc's sag and the OUTWARD unit normal of the chord. A row is a
    refusal.

    WHY. A chord drawn between the arc's ends is INSCRIBED: the body lies
    outside it, and a hull built from chords is SHRUNK — exactly the gap
    for which `review #1` sent every arc contour to the bounding box (floor
    9981227 of the facade, the arc midpoint 752.832 mm OUTSIDE the
    "conservative" hull).

    WHAT IS PROVEN HERE. Let an arc rest on the chord [p0,p1], with its
    midpoint standing off the chord by `s` (this is the sag). For an arc NO
    GREATER THAN A SEMICIRCLE both facts hold at once:

      * the projection of any of its points onto the chord's line lies
        between p0 and p1;
      * the distance of any of its points from the chord's line does not
        exceed `s`.

    So the arc lies entirely within the RECTANGLE "chord × [0, s] toward the
    midpoint". Replacing the chord edge with the three sides of this
    rectangle, the region GROWS, and grows STRICTLY OUTWARD — the law of
    conservativeness is preserved, and the value `s` is not invented but
    taken from the data (the decompile's `arc_midpoints`).

    THE BOUNDARY OF APPLICABILITY IS CHECKED, NOT ASSUMED. `s >= L/2` is
    equivalent to "the arc is not smaller than a semicircle" (for half-angle
    θ: s = R(1−cosθ), L/2 = R·sinθ, and s ≥ L/2 ⟺ θ ≥ π/2). Beyond this
    boundary the first fact is false — the arc extends past the chord's
    ends — and here there is an honest refusal, rather than a formula
    outside its domain.
    """
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    if L <= G.EPS_MM:
        # A closed arc as a single edge: there is no chord, nothing to
        # measure the sag from.
        return "profile_arc_zero_chord"
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    sd = (mid[0] - p0[0]) * nx + (mid[1] - p0[1]) * ny
    s = abs(sd)
    if s <= G.EPS_MM:
        return "profile_arc_degenerate"      # the arc is indistinguishable from a straight line
    if 2.0 * s >= L:
        return "profile_arc_over_half_circle"
    return (s, (nx, ny) if sd > 0 else (-nx, -ny))


def profile_refusal(profile: dict) -> str | None:
    """Why this contour CANNOT be trusted. `None` — it can.

    Review #1, a live counterexample (floor 9981227 of the facade, edge 5 of
    the outer contour — an arc): convexifying VERTICES ONLY replaces the arc
    with a chord, and the arc's midpoint ended up 752.832 mm OUTSIDE the
    "conservative" hull. The law of conservativeness is violated on live
    data, i.e. a clash can be missed.

    THE DECOMPOSE WAVE lifts the refusal SPECIFICALLY FOR ARCS, and only
    because the outward approximation is now PROVEN rather than promised
    (`_arc_outward_rect`): the arc is replaced not by a chord but by a
    rectangle that contains it, and the inflation value is taken from the
    decompile's `arc_midpoints`, not from a constant. Measurement of the
    refusal's cost (10.08.2026): on `демо-v3` an arc was sending 155 floors
    out of 235 (66.0 %) to the bounding box, on `k2_ar_rd_v15` — 57 of 398.

    Everything that is neither a line nor an arc is still refused: we have
    no outward hull for a spline, and a chord through it is the same gap.
    """
    for loop in (profile.get("curve_kinds") or []):
        for kind in (loop or []):
            if kind and kind not in PROFILE_CURVE_KINDS:
                return f"profile_curve_{kind}"
    for name in ("exterior_loop",):
        for p in (profile.get(name) or []):
            if not (isinstance(p, (list, tuple)) and len(p) >= 2
                    and G._finite(p[0]) and G._finite(p[1])):
                return "profile_vertex_invalid"
    for hole in (profile.get("holes") or []):
        for p in (hole or []):
            if not (isinstance(p, (list, tuple)) and len(p) >= 2
                    and G._finite(p[0]) and G._finite(p[1])):
                return "profile_vertex_invalid"
    return None


@dataclass(frozen=True)
class ProfileRegion:
    """A decomposed contour: what the region is DECLARED as, prior to any
    hull.

    A separate type rather than a tuple, because there are now four fields
    of different natures: loops are data, overlays are output, the bounding
    box is proof, and the margin is a measurement of coarsening. A
    five-element tuple can only be read by counting commas.
    """
    #: Chorded loops: the first is outer, the rest are holes. NOT TOUCHED.
    loops: tuple[tuple[G.Pt2, ...], ...] = ()
    #: Convex overlays covering the arcs. United with the region.
    arc_patches: tuple[tuple[G.Pt2, ...], ...] = ()
    #: The EXACT bounding box of the declared region (vertices + arc extreme
    #: points). `None` — there are no arcs, nothing to clip.
    bounds: tuple[float, float, float, float] | None = None
    #: The largest sag by which the hull is wider than the declared contour.
    arc_slack_mm: float = 0.0
    #: Why there is no contour. `None` — it exists.
    reason: str | None = None


def profile_loops(profile: dict) -> ProfileRegion:
    """Profile contours -> `ProfileRegion`.

    Loops are returned CHORDED and UNTOUCHED; arcs travel as a separate list
    of CONVEX rectangles, which the consumer UNITES with the region.

    WHY A SEPARATE LIST, NOT A SPLICE INTO THE LOOP. The first version
    inserted two points directly into the contour, flaring the boundary
    outward by the sag. This works on a convex contour, but not on a RING,
    and the corpus produced exactly such a ring: `k2_ar_rd_v15`, floor
    11839990 — a perimeter band 300 mm wide, whose outer and inner
    boundaries travel as ONE loop in opposite windings. The splice, which
    added area on the outside, SUBTRACTED it on the inner boundary: a
    Shapely measurement — 8 480 000 mm² of real material vanished from the
    hull, 524 probes out of 40 000 turned out to be outside the body. This
    is a direct violation of the law of containment, i.e. a missed clash.

    Union does not depend on orientation at all: `A ∪ R ⊇ A` for any winding
    of A and any R. Pieces are allowed to overlap — neither
    `signed_distance` (minimum over pairs) nor `contains_point` (disjunction
    over pieces) requires non-intersection. The cost is up to one extra cell
    per arc.

    WHEN AN OVERLAY IS NOT NEEDED. If the arc's midpoint already lies WITHIN
    the chorded region, then the entire segment between the chord and the
    arc lies within it too (the segment is connected and touches the region
    only along the chord) — there is nothing to cover. The check is done by
    even-odd (`decompose.point_in_region`), which knows nothing about
    orientation; it cannot err on the dangerous side, because a superfluous
    overlay only COARSENS, whereas a missed one does not.
    """
    raw = [profile.get("exterior_loop") or []]
    raw += [h or [] for h in (profile.get("holes") or [])]
    kinds = profile.get("curve_kinds") or []
    mids = profile.get("arc_midpoints") or []

    chord: list[list[G.Pt2]] = []
    for lp in raw:
        pts: list[G.Pt2] = []
        for p in lp:
            if not (isinstance(p, (list, tuple)) and len(p) >= 2
                    and G._finite(p[0]) and G._finite(p[1])):
                return ProfileRegion(reason="profile_vertex_invalid")
            pts.append((float(p[0]), float(p[1])))
        chord.append(pts)
    if not chord or len(chord[0]) < 3:
        return ProfileRegion(reason="profile_not_a_polygon")

    if not any(k == "arc" for lk in kinds for k in (lk or [])):
        return ProfileRegion(loops=tuple(tuple(c) for c in chord))

    if len(kinds) < len(chord):
        return ProfileRegion(reason="profile_curve_kinds_missing")
    rects: list[tuple[G.Pt2, ...]] = []
    extremes: list[G.Pt2] = []
    slack = 0.0
    for i, pts in enumerate(chord):
        lk = list(kinds[i] or [])
        lm = list(mids[i] or []) if i < len(mids) else []
        if len(lk) != len(pts):
            # The number of declared edges does not match the number of
            # vertices: there is nothing to match an arc to an edge with,
            # and guessing the correspondence would mean inventing geometry.
            return ProfileRegion(reason="profile_curve_kinds_mismatch")
        n = len(pts)
        for j in range(n):
            if lk[j] != "arc":
                continue
            p0, p1 = pts[j], pts[(j + 1) % n]
            m = lm[j] if j < len(lm) else None
            if not (isinstance(m, (list, tuple)) and len(m) >= 2
                    and G._finite(m[0]) and G._finite(m[1])):
                return ProfileRegion(reason="profile_arc_midpoint_missing")
            mid = (float(m[0]), float(m[1]))
            if D.point_in_region(mid, chord):
                continue                     # the chord already covers the segment
            got = _arc_outward_rect(p0, p1, mid)
            if isinstance(got, str):
                return ProfileRegion(reason=got)
            s, nrm = got
            rects.append((p0, p1,
                          (p1[0] + nrm[0] * s, p1[1] + nrm[1] * s),
                          (p0[0] + nrm[0] * s, p0[1] + nrm[1] * s)))
            extremes.extend(arc_extremes(p0, p1, mid))
            if s > slack:
                slack = s
    pts_all = [q for lp in chord for q in lp] + extremes
    bounds = (min(q[0] for q in pts_all), min(q[1] for q in pts_all),
              max(q[0] for q in pts_all), max(q[1] for q in pts_all))
    return ProfileRegion(loops=tuple(tuple(c) for c in chord),
                         arc_patches=tuple(rects), bounds=bounds,
                         arc_slack_mm=slack)


def _circle_through(p0: G.Pt2, m: G.Pt2, p1: G.Pt2) -> tuple[G.Pt2, float] | None:
    """A circle through three points. `None` — the points are collinear."""
    ax, ay = p0
    bx, by = m
    cx, cy = p1
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if d == 0.0:
        return None
    sa, sb, sc = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (sa * (by - cy) + sb * (cy - ay) + sc * (ay - by)) / d
    uy = (sa * (cx - bx) + sb * (ax - cx) + sc * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def arc_extremes(p0: G.Pt2, p1: G.Pt2, mid: G.Pt2) -> list[G.Pt2]:
    """The axis-extreme points of an ARC — exactly, not from its vertices.

    An arc's bounding box is not equal to the bounding box of its ends: for
    an arc that has passed over an axis direction, the extreme point lies
    INSIDE the span. This is computed with no tolerance at all: the circle
    is reconstructed from three declared points (start, middle, end), and
    each of the circle's four axis points is included if and only if it
    lies ON the arc.
    """
    got = _circle_through(p0, mid, p1)
    if got is None:
        return [p0, p1, mid]
    (cx, cy), r = got
    if not (math.isfinite(cx) and math.isfinite(cy) and math.isfinite(r)):
        return [p0, p1, mid]
    tau = 2.0 * math.pi
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    am = math.atan2(mid[1] - cy, mid[0] - cx)
    a1 = math.atan2(p1[1] - cy, p1[0] - cx)
    span_m = (am - a0) % tau
    span_1 = (a1 - a0) % tau
    ccw = span_m <= span_1          # the winding for which the midpoint lies inside
    out = [p0, p1, mid]
    for k in range(4):
        ang = k * math.pi / 2.0
        rel = (ang - a0) % tau if ccw else (a0 - ang) % tau
        lim = span_1 if ccw else (a0 - a1) % tau
        if rel <= lim:
            out.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return out


def hull_from_region(loops: Sequence[Sequence[G.Pt2]], z0: float, z1: float,
                     clip_xy: tuple[float, float, float, float] | None = None,
                     arc_rects: Sequence[Sequence[G.Pt2]] = ()
                     ) -> tuple[G.Hull | None, dict]:
    """A footprint region × [z0, z1] -> a hull and a RECEIPT of how it came
    out.

    Three outcomes, and all three are named:

    * the contour is CONVEX and without holes — the previous `Prism` with
      the previous footprint, byte-for-byte. There is nothing to refine, and
      shifting the report where the geometry has not changed would make the
      wave's diff unreadable;
    * the decomposition succeeded — a `PrismSet` of convex pieces whose
      union EQUALS the declared region (proven in `decompose`);
    * the decomposition refused — the previous convex prism with holes
      filled in, but the refusal reason travels in the receipt. There is no
      silent convexifying: without a name, "the hull is convex" is
      indistinguishable from "the hull is convex because we gave up", and
      these are different facts about the search.
    """
    if not loops:
        return None, {"reason": "profile_not_a_polygon"}
    ext = list(loops[0])
    holes = [list(h) for h in loops[1:] if h and len(h) >= 3]
    lo, hi = (z0, z1) if z0 <= z1 else (z1, z0)

    form: dict = {}
    cells: tuple[tuple[G.Pt2, ...], ...]
    if not holes and not arc_rects and D.loop_is_convex(ext):
        fp = G.convex_footprint(ext)
        if len(fp) < 3:
            return None, {"reason": "profile_not_a_polygon"}
        cells, form = (fp,), {"footprint_form": "convex_loop"}
    else:
        dec = D.decompose(ext, holes)
        if dec.ok:
            cells = dec.cells
            form = {"footprint_form": "decomposed", "holes_carved": len(holes)}
        else:
            fp = G.convex_footprint(ext)
            if len(fp) < 3:
                return None, {"reason": "profile_not_a_polygon"}
            cells = (fp,)
            form = {"footprint_form": "convexified",
                    "holes_filled": len(holes),
                    "decomposition_refused": dec.reason,
                    **{f"decomposition_{k}": v
                       for k, v in (dec.stats or {}).items()
                       if k in ("cells", "slabs", "work", "residual_rel")}}

    # Arc overlays are UNITED with the region, not spliced into the
    # contour: see `profile_loops`. Each overlay is already convex, so
    # these are simply more pieces; overlap with neighbors is legitimate and
    # harms nothing.
    if arc_rects:
        cells = tuple(cells) + tuple(tuple(r) for r in arc_rects)
        form["arc_patches"] = len(arc_rects)

    # Bounding-box clipping is ONE for all three outcomes, not just for the
    # decomposition. A separate clip for one outcome would be exactly the
    # class of defect that this module has been fixing all month: a rule
    # that works on one branch and stays silent on the neighboring one. The
    # measurement that caught this (10.08.2026, `k2_ar_rd_v15`): 138 findings
    # that did not exist before the wave were coming from the `convexified`
    # branch — there the convex hull was taken from a contour ALREADY
    # INFLATED by arcs, and nobody clipped the arcs' outer corners back to
    # the bounding box.
    cells, clipped_frac = _clip_cells(cells, clip_xy)
    if not cells:
        return None, {"reason": "profile_not_a_polygon"}
    form["footprint_cells"] = len(cells)
    if clipped_frac > 0.0:
        form["bbox_clip_removed_frac"] = round(clipped_frac, 9)
    if len(cells) == 1:
        return G.Prism(cells[0], lo, hi), form
    return G.PrismSet(cells, lo, hi), form


def _clip_cells(cells: Sequence[Sequence[G.Pt2]],
                clip_xy: tuple[float, float, float, float] | None
                ) -> tuple[tuple[tuple[G.Pt2, ...], ...], float]:
    """Cells ∩ the region's OWN bounding box. Plus the clipped fraction.

    WHY NOT THE ELEMENT'S BOUNDING BOX, EVEN THOUGH IT WAS THE OBVIOUS
    CHOICE. The Revit bounding box contains the body — a reasoning that is
    correct and inapplicable: the contour and the bounding box arrive from
    the decompile by DIFFERENT paths and diverge in the corpus. Measurement
    of 10.08.2026, `snowdon_plumb_v5`, floor 1424071: the declared contour
    reaches x = 974.73, while the element's bounding box ends at
    x = −1854.20, and clipping by the bounding box cut away 21.13 % of the
    DECLARED region. The containment probe caught this as 95 contour points
    outside the hull — i.e. as A MISSED CLASH, not as an inaccuracy.

    It is therefore clipped by the bounding box of THE REGION ITSELF
    (contour vertices plus the EXACT arc extreme points, `arc_extremes`).
    Such a bounding box contains the region by construction, so the clip
    cannot take away a single one of its points — it can only take away the
    CORNERS OF OVERLAYS that stick out past everything that is declared at
    all. There is no longer a single tolerance or a single trust in someone
    else's frame here, and the `MAX_BBOX_CLIP_FRAC` guard is not needed
    along with them: there is nothing to take away.
    """
    if clip_xy is None:
        return tuple(tuple(c) for c in cells), 0.0
    x0, y0, x1, y1 = clip_xy
    total = sum(D.polygon_area(c) for c in cells if len(c) >= 3)
    out: list[tuple[G.Pt2, ...]] = []
    kept_area = 0.0
    for c in cells:
        q = D.clip_to_box(c, x0, y0, x1, y1)
        if not q:
            continue
        out.append(q)
        if len(q) >= 3:
            kept_area += D.polygon_area(q)
    if not out or total <= 0.0:
        return tuple(tuple(c) for c in cells), 0.0
    return tuple(out), max(0.0, (total - kept_area) / total)


def hull_from_profile(loop: list, z0: float, z1: float) -> G.Hull | None:
    """A single footprint contour -> a hull. A thin wrapper over
    `hull_from_region`.

    This input has no holes by definition, and no arcs either (the caller
    has already passed `profile_refusal`). Concavity is NO LONGER
    convexified: it is decomposed into convex pieces, and the hull becomes
    equal to the contour, not to its convex hull.
    """
    pts: list[G.Pt2] = []
    for p in loop:
        if not (isinstance(p, (list, tuple)) and len(p) >= 2
                and G._finite(p[0]) and G._finite(p[1])):
            return None                      # we do not silently discard — we refuse
        pts.append((float(p[0]), float(p[1])))
    if len(pts) < 3:
        return None
    return hull_from_region((pts,), z0, z1)[0]


def build_hull(el: dict, *, profile: dict | None = None,
               curve: dict | None = None) -> tuple[HullRecord | None, Refusal | None]:
    """The single point where an element turns into a hull.

    The order of sources goes from exact to coarse, and it is this order
    that determines the grade. No step MAKES UP numbers: sections and
    thicknesses are taken only from data, and when they are absent, the
    hull becomes the bounding box, which is always present in the data.
    """
    sid = str(el.get("element_id"))
    cat = el.get("category") or "?"
    rule = KIND_TABLE.get(cat)
    if rule is None:
        return None, Refusal(sid, cat, "unsupported", "kind_outside_table")
    if not rule.eligible:
        return None, Refusal(sid, cat, "not_eligible", rule.note or "нет тела")

    box = _valid_box(el.get("bbox_min_mm"), el.get("bbox_max_mm"))
    common = dict(source_id=sid, category=cat, label=rule.label,
                  mvp_side=rule.mvp_side, level_id=el.get("level_id"),
                  type_name=el.get("type_name"))
    #: Why a more exact source did not work. An empty list = the first one
    #: worked.
    downgrades: list[str] = []
    #: The Z-extent DECLARED by the source (the program knows the level
    #: elevation and the height; an L0 decompile has none of this — there Z
    #: comes from the real bounding box).
    z_span = _z_span(el) or (None if box is None else (box[0][2], box[1][2]))

    # 0. A band around the axis × [z0, z1] — a wall. The numbers come
    #    entirely from `el["prism"]`, and the builder ADDS NOTHING on its
    #    own: an incomplete set is a named fallback, not "taking what there
    #    was".
    #
    #    `box is None` is NOT an optimization, it is the entire tolerance of
    #    the band, and it stands HERE, not in the table, because the table
    #    knows nothing about the data. The containment lock
    #    (`WALL_BAND_REFUSAL`) measured the band against the REAL body and
    #    refused: 97 violations out of 800, up to 2854 mm outward. There the
    #    bounding box EXISTS, and it remains the body. The band is taken
    #    exactly where there is nothing else to measure with — for a wall
    #    declared by the program and not yet built. This is a condition on
    #    THE DATA, not on intent: otherwise tomorrow's L0 decompile, should
    #    it start carrying `prism`, would silently carry walls out from
    #    under the lock that was refusing them.
    if "prism" in rule.sources and box is None:
        pr_rec, why = _prism_record(el, common, z_span)
        if pr_rec is not None:
            return pr_rec, None
        if why:
            downgrades.append(why)

    # 1. A footprint contour (floors, roofs) — a prism. Only if the
    #    CATEGORY is allowed this source (review #12) and the contour can be
    #    trusted (review #1).
    if ("profile" in rule.sources and profile
            and profile.get("profile_available") and z_span):
        why = profile_refusal(profile)
        if why is None:
            reg = profile_loops(profile)
            if reg.reason is not None:
                downgrades.append(reg.reason)
            else:
                loops, arc_rects, arc_slack = (
                    reg.loops, reg.arc_patches, reg.arc_slack_mm)
                # Clipping is needed exactly where there are arc overlays:
                # only their corners are able to stick out past what is
                # declared. The boundary is the bounding box of THE REGION
                # ITSELF, not of the element (see `_clip_cells`).
                clip = reg.bounds if arc_rects else None
                pr, receipt = hull_from_region(loops, z_span[0], z_span[1],
                                               clip_xy=clip, arc_rects=arc_rects)
                if pr is not None:
                    extra = dict(receipt)
                    extra["holes_declared"] = len(profile.get("holes") or [])
                    if arc_slack > 0.0:
                        # How much WIDER the hull is than the declared
                        # contour because of arcs. The number is computed
                        # from the geometry of the arc itself, not taken
                        # from a tolerance constant — otherwise the "outward
                        # approximation" would be a promise, not a
                        # measurement.
                        extra["arc_outward_slack_mm"] = round(arc_slack, 6)
                    if downgrades:
                        extra["downgraded_from"] = list(downgrades)
                    return HullRecord(hull=pr, grade="conservative",
                                      hull_source="profile",
                                      extra=extra, **common), None
                downgrades.append(receipt.get("reason") or "profile_not_a_polygon")
        else:
            downgrades.append(why)

    # 2. Axis + SECTION FROM DATA — a capsule. The numbers come from the
    #    `params` of the L0 row (emission d154196e): the params key equals
    #    the BuiltInParameter name. The `section_radius_mm` field remains
    #    the senior input — it is used by synthetic scenes and snapshots
    #    from other sources.
    radius: Any = None
    round_flag: Any = None
    section_source: str | None = None
    nominal_radius: float | None = None
    if "axis_section" in rule.sources:
        radius, round_flag = el.get("section_radius_mm"), el.get("section_round")
        if G._finite(radius) and radius > 0:
            section_source = "section_radius_mm"
        else:
            sec, why, nominal_radius = section_from_params(cat, el.get("params"))
            if sec is not None:
                radius, round_flag, section_source = (
                    sec.radius_mm, sec.round, sec.source)
            elif why in ("section_absent", "section_nominal_only"):
                # The category is allowed the source, there is no proven
                # number — this is a NAMED fallback, not "it was always
                # like this". Without a name, a coarse grade for an entire
                # discipline section is indistinguishable from broken
                # parameter reading.
                downgrades.append(why)
    common["section_radius_mm"] = (
        float(radius) if section_source is not None else None)
    common["section_round"] = (
        bool(round_flag) if section_source is not None else None)
    common["section_source"] = section_source

    def _extra(base: dict | None = None) -> dict:
        """The record's receipt. The nominal lands here ALWAYS when it is
        read: "there is no outer" and "there is no section" are different
        diagnoses (R3 of the red findings)."""
        out = dict(base or {})
        if downgrades:
            out["downgraded_from"] = list(downgrades)
        if nominal_radius is not None:
            out["nominal_radius_mm"] = float(nominal_radius)
        return out
    if section_source is not None:
        path = None
        if curve and curve.get("curve_kind") == "arc":
            arc = curve.get("arc") or {}
            p0a, p1a = _pt3(curve.get("p0_mm")), _pt3(curve.get("p1_mm"))
            if p0a is None or p1a is None:
                # Review #4: a broken arc was returning [p0,p1], and without
                # points — (0,0,0), i.e. a hull at the origin.
                downgrades.append("arc_endpoints_missing")
            else:
                pts, sag = arc_chord_polyline(arc, p0a, p1a)
                if sag <= 0 and len(pts) == 2:
                    downgrades.append("arc_unreadable")
                else:
                    path, radius = pts, float(radius) + sag
        else:
            p0 = _pt3(el.get("p0_mm")) or _pt3((curve or {}).get("p0_mm"))
            p1 = _pt3(el.get("p1_mm")) or _pt3((curve or {}).get("p1_mm"))
            if p0 is None or p1 is None:
                downgrades.append("axis_endpoints_missing")
            elif G._len(G._sub(p1, p0)) <= G.EPS_MM:
                # Review #4: zero length was turning a pipe into a SPHERE of
                # the section's radius — a body that is not in the model.
                downgrades.append("axis_zero_length")
            else:
                path = [p0, p1]
        if path:
            # Review #4: `exact` NEVER happens for a capsule. A straight
            # pipe has flat ends, a capsule has spherical ones; an arced
            # capsule is additionally inflated by the sag. Even after the
            # proof-firebreak, the grade must be honest: it describes OUTER
            # and is not replaced by an Inner certificate.
            return HullRecord(hull=G.Capsule(tuple(path), float(radius)),
                              grade="conservative", hull_source="axis_section",
                              extra=_extra(), **common), None

    # 3. The bounding box — exists for every extracted element.
    if box:
        return HullRecord(hull=G.Aabb(box[0], box[1]), grade="coarse",
                          hull_source="bbox",
                          extra=_extra(), **common), None

    return None, Refusal(sid, cat, "missing_geometry",
                         "нет ни контура, ни сечения, ни габаритного бокса")



#: WHICH SOURCE yields which grade. The table is not descriptive but
#: verifiable: `grade_reachability()` cross-checks it against `KIND_TABLE`
#: and declares UNREACHABLE any grade left with not a single source for any
#: category. Without this cross-check, "exact = 0" in a report reads as "no
#: exact hulls were found", when in fact they cannot exist in principle.
GRADE_BY_SOURCE: dict[str, str] = {
    "prism": "conservative",
    "profile": "conservative",
    "axis_section": "conservative",
    "bbox": "coarse",
}

#: 🔴 WHY COARSE HULLS ARE THE OVERWHELMING MAJORITY — MEASUREMENT OF
#: 19.08.2026, AND IT SEPARATES TWO DIFFERENT CAUSES THAT ARE FIXED IN
#: OPPOSITE WAYS.
#:
#: The first reading ("the coarse share is exactly what the table allows")
#: is TRUE ONLY BY HALF and is corrected here by its own measurement.
#: Non-coarse can be produced by 7 of the 49 eligible categories; the other
#: 42 are declared `SOURCES_BBOX`. But beyond this, rich categories LOSE
#: their source and fall back to the bounding box:
#:
#:     building            hulls  non-coarse  forced by    LOST for
#:                                            the table    the rich
#:     sob62_r23_v5           1326    18 1.36%       601        707
#:     graph_check            1504    20 1.33%      1344        140
#:     snowdon_plumb_v5       5442   192 3.53%      4093       1157
#:
#: THE CULPRIT FOR THE LOSSES IS THE SAME EVERYWHERE — `OST_Walls` (691 /
#: 140 / 1136), and the reason is named in `WALL_BAND_SCOPE` two paragraphs
#: below: the `prism` key is written by EXACTLY ONE place (`clash_bundle`,
#: the authoring path), and a wall decompiled from the model does not carry
#: it at all. That is, for walls the source is ALLOWED and physically
#: absent across the entire corpus.
#:
#: THE CONSEQUENCE FOR ANY WAVE AIMING AT THE GRADE: fixing "builders" is
#: useless — they fire where a source exists (losses of 6 and 21 for floors
#: and roofs, 9 for pipes). Exactly two pieces of work move the share, and
#: they are DIFFERENT:
#:   * give a source to the 42 categories that declare only a bounding box;
#:   * give the wall an independent witness of extent. Named exactly, as a
#:     number, in `WALL_BAND_REFUSAL.opens_with`:
#:     `wall_triangles_in_geometry_bundle` and `wall_type_width`.
#: The band as a substitute for the bounding box is, on this point, REFUSED
#: by measurement (220 871 walls) and remains refused: it contests the real
#: body and loses.
#:
#: AND ABOUT THE METRIC: the number of FINDINGS cannot be a quality metric —
#: with a bad grade it GROWS, rather than falls. The wave's closing number
#: is the non-coarse share.
#:
#: 🔴🔴🔴 EVERYTHING BELOW ABOUT "THERE ARE NO WITNESSES IN THE STORE" IS
#: REVOKED AS OF 20.08.2026. THE MARK STANDS HERE, ABOVE WHAT IS BEING
#: REVOKED, NOT BELOW IT: a retraction is checked on the carrier's first
#: screen, not by grepping through it.
#:
#: THREE assertions are revoked, and each one would have sent the next wave
#: to build what is already built. Remeasured on the SAME corpus (77
#: profiles, 75 L0), with two independent instruments — JSON parsing and
#: grep — they agreed down to one service line of a category page:
#:
#:   REVOKED: "the `wall_types` pool carries 0 rows in 77 of 77 profiles"
#:     -> the pool is NON-EMPTY in **77 of 77**, rows **6880**, median 69,
#:        maximum 185. What is empty is not the rows but their `params` — 0
#:        of 6880, and in ALL 19 pools too, because `params` is written only
#:        under the authoring program's `disambiguate_by`. But the
#:        thickness is NOT TAKEN from there.
#:
#:   REVOKED: "there is no type width in the store"
#:     -> `open_model.__Section` writes the `section` key UNCONDITIONALLY,
#:        outside `__ParamNames`. `section.thickness_mm`
#:        (`source: WallType.Width`) is present on **1023 of 6880 rows**,
#:        and the distribution across profiles is ALL-OR-NOTHING: 8 profiles
#:        at 100 %, 69 at 0 %. The reason is not the capture, but the
#:        CORPUS'S AGE: `__Section` appeared in commit `f911ba4d` on
#:        09.08.2026, and 69 runs were taken earlier. A fresh reading always
#:        carries the width.
#:
#:   REVOKED: "a wall in L0 carries thickness in no parameter at all"
#:     -> it does: `params.WALL_ATTR_WIDTH_PARAM` is present for
#:        **220 326 of 286 430 walls (76.9 %)** across the entire corpus.
#:        And `WALL_CROSS_SECTION` is read for **220 812 (77.1 %)**, of
#:        which 220 782 are vertical — i.e. this also revokes the
#:        `extract.py` comment "not read for NOT A SINGLE ONE of the 2360
#:        walls".
#:
#: THE FULL SET FOR A PRISM (axis + straight curve + thickness + height +
#: `WALL_CROSS_SECTION==1` + top not linked) is present in L0 for
#: **203 661 of 286 430 walls = 71.1 %**; on the tower `k2_ar_rd_v15` —
#: **14 215 of 15 341 = 92.7 %**.
#:
#: 🔴 AND HERE IS WHAT DOES NOT FOLLOW FROM THIS: that a prism can be built.
#: A band around the wall axis is refused BY MEASUREMENT (`WALL_BAND_REFUSAL`,
#: 220 871 walls), and the refusal remains fully in force: the real body
#: exceeds the nominal — a joint pushes up to 250 mm past the axis end, 93
#: walls out of 800 are wider than their own `WallType.Width` by up to
#: 2854 mm, the discrepancy between estimates reaches 587.6 mm. A hull
#: smaller than the body hides a clash SILENTLY. The data was not the only
#: obstacle, and not even the main one.
#:
#: WHAT THIS CHANGES IN SUBSTANCE: the owner of the work is NOT "capturing
#: the width". Exactly one named opener remains — the wall's triangles —
#: and its absence has also stopped being "we didn't measure it": it is
#: STRUCTURAL. `pipeline._geometry_atom_ids` requests Tier-G ONLY for
#: L1-ATOMS that are not a `generator_child`. A wall is raised in
#: `create_wall` SUCCESSFULLY, does not become an atom — and NEVER enters
#: the request, on any corpus. Hence `bundles_containing_a_wall: 0` is not
#: an observation about three bundles but a property of the selection.
#: Opening this is possible only by a DECISION to widen the Tier-G scope,
#: which has a cost (triangles for 286 430 walls), and that decision is not
#: this one's to make.
#:
#: Below is the earlier edition, left in place as a SAMPLE OF FORM: "the
#: pool is captured by name with no content" sounded like a measurement and
#: was a conclusion drawn from an empty `params`, i.e. a measurement of THE
#: WRONG QUANTITY.
#:
#: ⛔ OUTDATED, DO NOT CITE:
#: 🔴 AND MOST IMPORTANTLY: BOTH WITNESSES NAMED IN
#: `WALL_BAND_REFUSAL.opens_with` ARE ABSENT FROM THE STORE. Checked on
#: 19.08.2026 BEFORE building anything for the wall — and the check
#: cancelled the work rather than refined it.
#:
#:   `wall_type_width`                     the `wall_types` pool carries
#:                                         **0 rows in 77 of 77 profiles**.
#:                                         Not "usually empty" — ALWAYS: the
#:                                         pool is captured by name with no
#:                                         content;
#:   `wall_triangles_in_geometry_bundle`   a geometry bundle exists for
#:                                         **3 of 75 decompiles**, and NOT
#:                                         ONE of the three has a single
#:                                         `OST_Walls`. What they do have:
#:                                         DirectShape, StairsRailing,
#:                                         DuctTerminal, MEPSpaces,
#:                                         PlumbingFixtures, Lines, rasters.
#:
#: The wall itself in L0 carries an AXIS (`geom_kind: curve`, 690 of 695)
#: and a HEIGHT (`WALL_USER_HEIGHT_PARAM`, 690), but carries THICKNESS in no
#: parameter at all — it is a property of the TYPE, and the type is
#: captured empty. Two of the three quantities needed for a prism are
#: missing.
#:
#: THE CONSEQUENCE, AND IT CHANGES THE OWNER OF THE WORK: there is nothing
#: to raise the wall's grade with today, and this is a CAPTURE hole, not a
#: builder's. A wave started here would be building a source on top of data
#: that is not in the snapshot; this is fixed on the OPPOSITE side — by
#: capturing the type width into the profile, or the wall's triangles into
#: the bundle. Until then the non-coarse share on walls is fixed BY
#: CONSTRUCTION, and the number 1.33–3.53 % describes not the quality of the
#: hulls but the completeness of the capture.
#: ⛔ REVOKED IN FULL ON 20.08.2026 — three of the seven numbers are wrong,
#: see the analysis above this block. The record is left standing as a
#: SAMPLE OF FORM (a conclusion about the pool, drawn from its `params`),
#: not as a fact. The reader must use `WALL_WITNESS_2026_08_20`.
WALL_WITNESS_ABSENT_2026_08_19: dict[str, object] = {
    "retracted_on": "2026-08-20",
    "retracted_because": "три числа измеряли не ту величину; см. WALL_WITNESS_2026_08_20",
    "measured_on": "2026-08-19",
    "wall_types_pool_rows": 0,             # ⛔ incorrect: 6880
    "profiles_checked": 77,
    "profiles_with_a_nonempty_wall_types_pool": 0,   # ⛔ incorrect: 77
    "geometry_bundles_in_corpus": 3,
    "runs_with_l0": 75,
    "bundles_containing_a_wall": 0,
    "l0_carries": ("axis (geom_kind=curve)", "WALL_USER_HEIGHT_PARAM"),
    # ⛔ incorrect: WALL_ATTR_WIDTH_PARAM is present for 220 326 walls out
    # of 286 430
    "l0_lacks": ("thickness — свойство ТИПА, тип захвачен пустым",),
    "verdict": "дыра ЗАХВАТА, работа обратного хода, не построителя оболочек",
}

#: THE CURRENT RECORD. Taken on 20.08.2026 on the same corpus, with two
#: independent instruments (JSON parsing and grep), and they diverged by
#: exactly one service line of a category page — 15 342/14 325 against
#: 15 341/14 324 on the tower.
#:
#: `prism_derivable_from_l0` — walls for which the L0 record ITSELF has ALL
#: five quantities: axis (`geom_kind=curve`), a straight curve,
#: `WALL_ATTR_WIDTH_PARAM`, `WALL_USER_HEIGHT_PARAM`,
#: `WALL_CROSS_SECTION==1`, and `WALL_TOP_IS_ATTACHED==0`. The number says
#: "the data is sufficient", and does NOT say "a prism can be built": the
#: band around the axis is refused by `WALL_BAND_REFUSAL`, and this refusal
#: is in force.
WALL_WITNESS_2026_08_20: dict[str, object] = {
    "measured_on": "2026-08-20",
    "corpus": "backend/data/decompile — 77 профилей, 75 L0, машинно-локален",
    "profiles_with_a_nonempty_wall_types_pool": 77,
    "wall_types_pool_rows": 6880,
    "wall_types_rows_with_params": 0,
    "wall_types_rows_with_section_width": 1023,
    "profiles_carrying_the_width": 8,
    "profiles_without_it": 69,
    "why_the_69": "сняты ДО коммита f911ba4d (09.08.2026), которым появился __Section",
    "walls_in_l0": 286430,
    "walls_with_axis": 286130,
    "walls_with_WALL_ATTR_WIDTH_PARAM": 220326,
    "walls_with_WALL_CROSS_SECTION": 220812,
    "walls_vertical": 220782,
    "prism_derivable_from_l0": 203661,
    "prism_derivable_share": 0.711,
    "tower_k2_ar_rd_v15": {"walls": 15341, "derivable": 14215, "share": 0.927},
    "still_refused_by": "WALL_BAND_REFUSAL — полоса не содержит настоящего тела",
    "the_one_real_opener": "wall_triangles_in_geometry_bundle",
    "why_triangles_are_absent": (
        "pipeline._geometry_atom_ids запрашивает Tier-G только у L1-АТОМОВ; "
        "стена поднимается успешно, атомом не становится и в запрос не "
        "попадает НИКОГДА — свойство отбора, а не полноты корпуса"),
    "verdict": "не дыра захвата ширины; открывает грейд только РЕШЕНИЕ о Tier-G",
}

GRADE_SOURCE_LOSS_2026_08_19: dict[str, object] = {
    "measured_on": "2026-08-19",
    "eligible_categories": 49,
    "categories_that_can_be_non_coarse": 7,
    "dominant_loss_category": "OST_Walls",
    "why": "ключ `prism` пишет только авторский путь; корпус его не несёт",
    "runs": {
        "sob62_r23_v5": {"hulls": 1326, "non_coarse": 18,
                         "forced_by_table": 601, "lost_by_rich": 707},
        "graph_check": {"hulls": 1504, "non_coarse": 20,
                        "forced_by_table": 1344, "lost_by_rich": 140},
        "snowdon_plumb_v5": {"hulls": 5442, "non_coarse": 192,
                             "forced_by_table": 4093, "lost_by_rich": 1157},
    },
}

#: Why the grade is unreachable. The key must be in `GRADES`; an empty
#: dictionary would mean that everything is reachable, and this assertion
#: is checked too.
UNREACHABLE_GRADE_REASONS: dict[str, str] = {
    "exact": (
        "`exact` значит ОБОЛОЧКА РАВНА ТЕЛУ, и сегодня этого не доказывает ни "
        "один источник: у капсулы прямой трубы торцы СФЕРИЧЕСКИЕ вместо "
        "плоских (ревью №4), а габаритный бокс телом не является по "
        "определению. Замер 10.08.2026 по всему складу: 65 читаемых прогонов, "
        "664 870 оболочек, `exact` = 0 — то есть недостижимость не наблюдение "
        "на выборке, а свойство таблицы источников. "
        "ВОЛНА DECOMPOSE ЗАКРЫЛА ОДНО ИЗ ТРЁХ УСЛОВИЙ И НЕ ПОДПИСЫВАЕТ ГРЕЙД. "
        "Подошва источника `profile` с этой волны РАВНА объявленному контуру "
        "(разбивка на выпуклые куски, отверстия вырезаны, сверка площадей "
        "сходится) — это условие ВЫПОЛНЕНО. Не выполнены два других, и оба "
        "названы: (1) РАЗМАХ ПО Z берётся как [z0, z1] из объявленной отметки "
        "и толщины, а НАПРАВЛЕНИЯ РОСТА тела в снапшоте нет — плита в 200 мм "
        "с отметкой 3000 может занимать и [2800,3000], и [3000,3200], и "
        "оболочка обязана накрывать обе догадки; (2) ДУГА раздувается наружу "
        "на стрелку, то есть оболочка СТРОГО ШИРЕ тела ровно на "
        "`arc_outward_slack_mm`, и это огрубление, пусть и измеренное. "
        "Подписать `exact` по одной закрытой оси из трёх значило бы повторить "
        "дефект, который в этом модуле только что чинили: подпись на оси, "
        "которую никто не прочитал."
    ),
}


def grade_reachability() -> dict[str, dict]:
    """Whether each grade is reachable — BY INFERENCE from the table, not
    by observation.

    A report that prints `exact: 0` does not distinguish "no exact hulls
    were found" from "exact hulls do not exist". This is a separate axis
    from `confirmed`: the latter now requires two certified inner subsets.
    """
    live: set[str] = set()
    for rule in KIND_TABLE.values():
        if not rule.eligible:
            continue
        for src in rule.sources:
            g = GRADE_BY_SOURCE.get(src)
            if g:
                live.add(g)
    return {
        g: {"reachable": g in live,
            "emitting_sources": sorted(s for s, gg in GRADE_BY_SOURCE.items()
                                       if gg == g),
            "reason": "" if g in live else UNREACHABLE_GRADE_REASONS.get(
                g, "источника нет, причина не названа — это дефект таблицы")}
        for g in GRADES}

def coverage_matrix() -> list[dict]:
    """A closed matrix for the report: category → eligibility → class →
    grades."""
    rows = []
    for cat, rule in sorted(KIND_TABLE.items()):
        rows.append({
            "category": cat,
            "eligible": rule.eligible,
            "mvp_side": rule.mvp_side,
            "label": rule.label,
            "hull_sources": list(rule.sources) if rule.eligible else [],
            "refusal": "" if rule.eligible else (rule.note or "нет тела"),
        })
    return rows
