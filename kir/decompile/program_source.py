"""A DECOMPILED FLOOR, PRINTED IN THE LANGUAGE THE MODEL WRITES.

WHY
---
`materialize.leaves_to_program` hands back JSON operations, while the
model writes PYTHON (`kir.dsl`, whose `OP_FUNCTIONS` surface is
GENERATED from the registry). Two forms for one language: reading and
writing become different skills, there is nothing to express repetition
with, and editing a building means editing a list of dictionaries that
can be neither reviewed nor diffed.

Printed Python removes the seam. An apartment becomes a function, a
reference to a wall becomes a variable, a type becomes a named constant,
and editing the layout becomes editing code.

THIS IS THE MATERIALIZER'S SECOND OUTPUT, NOT A SECOND PIPELINE
-----------------------------------------------------------------
The input here is EXACTLY the programs `leaves_to_program` has already
assembled, and that is not a convenience but a property: each of them
has already been run through `plan_program`
(`MaterializeResult.plans` / `plan_checks`), meaning the printed source
stands on operations the compiler has ALREADY accepted. A slicing of its
own has no such property, and so none is set up here.

Measured 17.08.2026 (`k2_ar_rd_v7`/L22, the development tree, branch
`integration/kir-2026-08-13`, Python 3.12.13), which is exactly why no
slicing was set up. The window is named honestly (Form 28): over the
course of the run, HEAD moved `7fb8b8b8` → `386d1ccf` from foreign
waves; the files they touched (`serving`, `building_index`,
`corpus_catalog`, `design_check`, `decompile/reextract`) do NOT
participate in this module's imports, so the numbers below survived the
shift — but that has to be checked, not assumed:

* the materializer produced **8 programs for 1000 operations**
  (244·250·250·193·60·1·1·1);
* `by=ref` references crossing a program boundary — **0 out of 210**.
  That is, every program is self-sufficient by construction (law D5a),
  and printing "one program — one source file" tears nothing;
* and the cost of the decision is named: **20 semantic units out of 23
  are cut** by the materializer's chunk boundary. A cut unit is still
  printed as a function, but the docstring says "N out of M
  operations," and the `units_partial` counter counts it separately
  from a whole one.

WHAT WAS MEASURED BEFORE THIS WAS WRITTEN (17.08.2026, `k2_ar_rd_v7`/L22)
---------------------------------------------------------------------------
* the tree's units (14 apartments + 9 МОП) hold **236 operations out of
  1000**; the remaining **764 hang directly on the floor**. So printing
  "a building made of apartments" would describe a quarter of the
  floor;
* **all 210 `by=ref` references lie in the free part**, zero of them
  inside units. That is, Python's win here is not in loops but in
  LINKS: `create_door(host=w17)`.
  🔴 AND THIS IS A PROPERTY OF ONE BUILDING, NOT A LAW: on
  `sob62_fas_r23_v19` a reference DOES enter a unit, and printing the
  unit as a function hid the variable inside a local scope — two floors
  out of four (1224 and 927 operations) executed into `NameError`.
  Therefore only the unit whose reference subgraph is CLOSED gets
  printed as a function (`units_linked_out` counts the rest);
* there are exactly TWO selector shapes on the floor: `element_id`
  (1885) and `ref` (210).

CORPUS COVERAGE, MEASURED BY THIS SAME REVISION (17.08.2026, window = one run)
--------------------------------------------------------------------------------
The entire store of decompiles with a tree is **52 decompiles**, and
that is NOT 52 buildings: `corpus_catalog` reports **10 distinct
documents**, of which one («Проект1 копия», 12 decompiles) is our own
generation. Taking the 2 most populated floors of each decompile, that
is **104 floors, 60 337 operations, 321 programs** in total:

* **95 floors are printed WHOLE, the round trip agreed on all 95,
  0 discrepancies**;
* **9 floors are EMPTY**: the materializer produced not a single
  program (every leaf went to `skipped`). A round trip over zero
  operations is green by construction and does NOT count — for this,
  `SourceRendering` has a separate `empty`;
* printing refusals — **0**: the corpus produced not one cause from
  `REFUSAL_CAUSES`. This is a fact about the SAMPLE, not proof they are
  unreachable, and that is exactly why the refusal list is declared a
  second kind ("closed, but not exhaustive");
* units: 221 printed whole as a function, 3023 printed partly as a
  function, 897 as a body for being small, 755 as a body for an
  unclosed reference, 31 as a body for being larger than the phase
  budget.

WHAT THE ROUND TRIP DOES NOT PROVE — NAMED, NOT IMPLIED
-----------------------------------------------------------
The check canonicalizes BOTH sides with the same `_round_by_kind` as the
printer, so a wrong rounding rule CANCELS ITSELF OUT in the round trip.
Verified by mutation on 17.08.2026: swapping the authority (registry
kind) for the field-name suffix turned red NOT ONE of 26 tests, even
though the two rules disagree on 41 (op, parameter) pairs. The round
trip proves "the same operations UP TO rounding by registry kind." The
rounding itself is guarded separately and directly — by the tolerance
value, not by the round trip.

🔴 AND HERE IS WHAT THIS BLINDNESS COST, MEASURED 03.09.2026. While
`_round_mm` rounded EVERY number inside a composite value to
millimeters, the round trip could not catch an angle swap BY
CONSTRUCTION — a blind band of ±0.5° (30.25 -> 30.0, 30.4, 30.5
"agreed"; 31.0 and 45.0 were seen). This is Form 48: a fixture made of
a matched pair is green for ANY value on both sides, because both are
mutated at once.

The band was lifted not by the round trip but by the value no longer
being rounded to a FOREIGN grain: `rotation_deg` follows the
`ANGLE_DEG` law, `start_angle_rad` follows `ANGLE_RAD` (not rounded at
all). Now the oracle CAN say "no," and this is pinned by mutation, not
merely claimed:
`decompile/tests/test_the_role_of_a_nested_key_is_asked.py`.

WHAT REMAINS BLIND, AND IS NAMED: the millimeter grain still cancels
itself out — the round trip cannot tell "both rounded correctly" from
"both rounded identically wrong." This cannot be fixed by the round
trip and is guarded separately, by tolerance.

THE SANDBOX HAS BEEN PASSED, LIVE REVIT HAS NOT. The model's real door
is `sandbox.execute_author_script` (fork, RLIMIT, an import guard,
ceilings), and it has been checked on the corpus's largest floor:
`sob62_fas_r23_v19`, 1224 operations in 5 programs, 1224 came back,
0 discrepancies, 1.1 s; texts of 51-64 KB against a `MAX_SOURCE_BYTES`
ceiling of 262 144 B. What is NOT checked, and cannot be checked here:
that the printed program BUILDS in live Revit. "Assembles the same
program" is not "builds in the model."

HOW THE "READABLE VERSUS PRECISE" CONTRADICTION IS RESOLVED
---------------------------------------------------------------
The type in the decompile is addressed as
`{"by":"element_id","value":11653371}` — noise, to a reader. Printing
`by_name("111_Кирпич 380")` instead would mean changing the SELECTOR,
and the round trip would diverge from the source in substance, not just
form. So the type is printed as a NAMED CONSTANT::

    T_Кирпич_380 = by_element_id(11653371)   # «111_Кирпич 380»

Meaning is carried by the variable name and the comment, precision by
the selector itself. Neither side gives way.

ROUNDING ASKS THE REGISTRY, NOT A NAME SUFFIX
--------------------------------------------------
`10829.999995547229` is noise, while `bulge = 0.4142135623730993` is an
arc, and the two cannot be rounded the same way. What measures what is
known by `ParamSpec.kind` (a closed list, 34 kinds): millimeter kinds
round to the millimeter, `deg` rounds to three digits, everything else
is left untouched entirely.

🔴 BUT A PARAMETER'S KIND ONLY ACCOUNTS FOR THE ROOT, WHILE DIFFERENT
QUANTITIES LIVE INSIDE A COMPOSITE VALUE. Under one `arc` kind live a
world point (`center_mm`), a length (`radius_mm`), two directions
(`x_axis`, `y_axis`), and two angles IN RADIANS (`start_angle_rad`,
`end_angle_rad`). Before 03.09.2026 a nested key's role was GUESSED
from the look of the value, and radians were rounded to a millimeter
grain on 299 corpus operations. Now the role is ASKED of `KEY_LAW`, and
there are two questions there, not one: what the quantity is measured
in, AND whether it moves together with the frame. The breakdown lives
with the table itself.

Whole millimeters give one more property, without which local unit
frames wouldn't work: `(abs - origin) + origin == abs` EXACTLY, with no
accumulated error.

THREE OUTCOMES, NOT TWO
------------------------
Printing REFUSES THE WHOLE PROGRAM and names the reason
(`REFUSAL_CAUSES`). A silently skipped operation is forbidden: a floor
printed halfway is indistinguishable from one printed whole, and this is
the main defect this entire module is written against. That is why the
count of what was printed lives both in the object
(`SourceRendering.ops_printed` against `ops_total`) and IN THE TEXT
ITSELF — a reader of the source learns about the incompleteness without
having access to our object.
"""
# 🔴 PROVENANCE MOVED OUT OF THE DOCSTRING 01.09.2026 — DOOR VS. JOURNAL.
# A module docstring is a PUBLIC DOOR: `help()` prints it to the reader of
# the published package, and our machine's address tells them nothing.
# The knowledge is not erased — it lives here, in the journal, where it
# belongs:
#     measurement tree  /home/claude/kir-merge/backend,
#                       branch integration/kir-2026-08-13
from __future__ import annotations

import collections
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping, Sequence

# ---------------------------------------------------------------------------
# AUTHORITIES. Not one number below is derived from a field's name or from
# convention.
# ---------------------------------------------------------------------------

#: Parameter kinds measured IN MILLIMETERS. The list is asked from the
#: registry (`spec.ParamSpec.kind`), not derived from a field's name:
#: `points_mm` inside a contour is named the same way as `p0_mm`, while
#: `bulge` right next to it is not a length at all.
MM_KINDS = frozenset({"mm", "pt_xy", "pt_xyz", "pts", "pts_list", "pts_xyz",
                      "region", "path", "path3", "pt_view2d", "mesh",
                      # `plane` (21.08.2026) — INSIDE the value, millimeters
                      # and dimensionless vectors are MIXED TOGETHER, and
                      # without this line the plane would slip PAST the
                      # shift into the local frame: the profile would shift,
                      # the plane's origin would stay in world space, and
                      # the drift would be silent.
                      "plane",
                      # ── 21.08.2026: THREE KINDS MISSED NOT BY A WAVE, BUT
                      # BY THE REVIEW'S SCOPE ───────────────────────────────
                      #
                      # 🔴 WHAT THIS COST. The 21.08 review looked ONLY at
                      # kinds introduced by the most recent waves, and so it
                      # missed the old ones. Measured by printing, in a unit
                      # frame of dx=1000,dy=500:
                      #
                      #   create_wall(p0_mm=[dx + 2000, dy + 1500],
                      #               arc={"center_mm": [4500, 2000], ...})
                      #
                      # The wall's ends follow the frame; the ARC'S CENTER is
                      # a world literal and does not follow. Shift the unit
                      # and the arc becomes a different arc, or fails
                      # outright. `create_wall` is the op with a DIRECT
                      # reverse path, and the most frequent one in the lift
                      # (7845 of 19 041 on MNVNK), so the path is not
                      # theoretical.
                      #
                      # Each kind was checked with BOTH halves (shift AND
                      # rounding), not added by name:
                      #   arc          center_mm shifts; radius_mm is a
                      #                scalar, rounds correctly to whole mm;
                      #                bulge is already in FREE_KEYS; dir is
                      #                a string
                      #   graph_nodes  xyz_mm shifts, id is untouched
                      #   placements   bare [x, y], shifts as a point
                      "arc", "graph_nodes", "placements"})
DEG_KINDS = frozenset({"deg"})

#: KINDS THAT CARRY MILLIMETERS AND ARE NOT IN `MM_KINDS` — WITH A REASON.
#:
#: 🔴 THIS IS NOT A TO-DO LIST, IT IS A GUARD AGAINST REPEATING THE MISTAKE.
#: Each of them WAS TRIED on 21.08.2026 and rejected BY MEASUREMENT, not by
#: caution: adding it breaks the value, and in exactly the place named. The
#: next person who wants to add them must first fix the named key, or they
#: will buy corruption instead of a fix.
#:
#:   spiral       ANGLES DIE FROM ROUNDING: `included_angle_deg` 180.75 -> 180.0,
#:                `start_angle_deg` 30.25 -> 30.0. First put both values in
#:                `FREE_KEYS` — only then bring the kind here
#:   solid_parts  `size_mm` is a TRIPLET OF NUMBERS, and `_shift` will
#:                mistake it for a point: a 1000x1000x1000 box in a dx=1000
#:                frame becomes 0x500x1000. First `size_mm` into `FREE_KEYS`
#:   surface      `knots_u`/`knots_v` die: [0.0, 0.5, 1.0] -> [0.0, 0.0, 1.0],
#:                `degree_u` 3 -> 3.0. First put knots and degrees into
#:                `FREE_KEYS`
#:
#: 🔴 AND THE COMMON REASON FOR ALL THREE, NAMED HERE SO IT IS NOT SOUGHT
#: AGAIN: `FREE_KEYS` frees a key from TWO questions AT ONCE — both rounding
#: and shifting — and these are DIFFERENT questions. A dimension needs
#: rounding and does not need shifting; a knot needs neither. As long as
#: `MM_KINDS` answers both questions with one set, these three kinds have no
#: honest place. The real fix is to separate "what we round" from "what we
#: shift"; until it happens, these lines are more honest than silence.
#:
#: 🔴 THE OBSTACLE WAS REMOVED 03.09.2026, BUT THE KINDS ARE NOT THEREBY
#: UNPARKED — AND THIS MUST NOT BE CONFUSED. `KEY_LAW` below answers both
#: questions SEPARATELY (`LENGTH` — round but do not shift; `FREE` — neither;
#: `ANGLE_RAD` — do not round with a millimeter grain), so the argument
#: "there is no honest place" no longer holds. What this does NOT mean: that
#: a kind can simply be added to `MM_KINDS`. Each one needs its own law for
#: EVERY nested key (`height_mm`, `knots_u`, `degree_u`, `width_mm`,
#: `included_angle_deg`…) and measurement with both halves — separate work,
#: NOT DONE here. The obstacle is removed, not the debt: it used to be "not
#: allowed until we split it" — now it is "allowed once we declare the keys".
#:
#: Two of the three (`solid_parts`, `surface`) are today UNREACHABLE by the
#: lift (the `capture_gap` reverse path); `spiral` is reachable — for
#: `create_stairs` it is DIRECT.
#: ── REVIEW 23.08.2026: 38 -> 39, AND IT FOUND A SECOND HOLE, SOMEONE ELSE'S ────
#:
#: The guard demands not moving the number but REPEATING THE REVIEW OVER THE
#: WHOLE LIST. Repeated: 39 kinds, samples `test_sdk._SAMPLES`, run with both
#: halves. One kind is its own new one (`wall_layers`), while millimeters
#: outside all three lists are carried by TWO — and the second was
#: introduced by someone else's wave even before this one.
#:
#: 🔴 THE FIRST REVIEW RUN WAS A LIE BY THE INSTRUMENT, and this is worth
#: recording alongside it. It called `_shift(value, kind, dx, dy)` and
#: `_round_mm(value, kind)` — both have different signatures. `_shift`
#: silently returned its input (1000.0 arrived in `kind`), `_round_mm`
#: failed on argument count, the failure was caught in `except` and printed
#: as «округляет». Both columns read with confidence and both were wrong.
#: The named form of the house: the instrument lies to its own author. The
#: signatures were taken from the code, not from memory.
MM_KINDS_REFUSED: dict[str, str] = {
    "spiral": "углы гибнут округлением; сперва углы в FREE_KEYS",
    "solid_parts": "size_mm — трёхчлен, сдвинется как точка; сперва во FREE_KEYS",
    "surface": "knots_u/knots_v и degree_* гибнут; сперва они во FREE_KEYS",
    # `wall_layers` (23.08.2026) — `width_mm` inside the layer dict. MEASURED
    # WITH BOTH HALVES: both `_round_mm` and `_shift` leave the sample
    # UNCHANGED — a thickness is neither a pair nor a triplet of numbers,
    # there is nothing in it to shift. So the kind lands here NOT because of
    # corruption, but because of ignorance: the 90 layers lying on our disk
    # (K3 and K1) have NOT A SINGLE fractional one, but a sub-millimeter
    # layer is legal in Revit and common in finishes (gypsum 12.5, membrane
    # 1.5), and on it, rounding to a whole mm will quietly spoil the
    # assembly. A zero about a quantity we have not yet counted is not an
    # answer.
    #
    # And the question is NOT LIVE today: `create_wall_type` does not emit a
    # single lifter (0 mentions across all of `decompile/`), so the reverse
    # path never sees this kind at all. The line is here so that whoever
    # teaches the lift a catalog reads the question before buying the
    # corruption.
    "wall_layers": ("width_mm внутри слоя: ни сдвиг, ни округление сегодня "
                    "ничего не меняют, но подмиллиметровый слой законен — "
                    "сперва отделить «что округляем» от «что сдвигаем». "
                    "Обратным ходом НЕ достижим: create_wall_type не поднимает "
                    "никто"),
    # `member_ops` (found 23.08.2026 by the repeated review, introduced by
    # SOMEONE ELSE'S wave of groups). Group members are WHOLE OPS with their
    # own millimeters, and both actions corrupt them in the places already
    # named:
    #
    #   rounding  rotation_deg 30.25 -> 30.0 · ref_dir [0.7071, 0.7071, 0]
    #             -> [1.0, 1.0, 0.0]
    #   shift     ref_dir [0.7071, 0.7071, 0] -> [-999.2929, -499.2929, 0]
    #
    # These are exactly the two corruptions for which `normal`/`x_dir`
    # landed in `FREE_KEYS` on the plane — but a group member has different
    # keys, and they are not in `FREE_KEYS`. The real fix is not "add a
    # kind" but printing each member with ITS OWN kinds, recursively.
    #
    # Not live today either: the `create_group` lifter is never called
    # (measured 22.08: 0 calls out of 51 574 operations).
    "member_ops": ("члены — целые опы: округление губит rotation_deg 30.25 и "
                   "ref_dir [0.7071…], сдвиг вычитает рамку из направления. "
                   "Печатать члены их собственными родами, рекурсивно"),
    # `slopes` (найдено РЕВИЗИЕЙ 13.09.2026, завела его чужая волна кровель).
    # Отличие от всех строк выше: этот род ЖИВОЙ на обратном ходе —
    # `create_roof` поднимается (`decompile/sketch_extract.py:359 _align_slopes`),
    # и `slopes[].angle_deg` (`authoring_validation.py:535`) едет через него
    # сегодня, а не когда-нибудь.
    #
    # Почему он всё-таки не в `DEG_KINDS`, а здесь: списки — это подписка НА
    # ПРЕОБРАЗОВАНИЕ, и неперечисленный род остаётся НЕТРОНУТЫМ, то есть целым.
    # Внесение `slopes` в `DEG_KINDS` без разделения «что округляем» от «что
    # сдвигаем» убило бы 30.25 → 30.0 ровно так, как описано у `member_ops`
    # строкой выше. Строка стоит здесь, чтобы тот, кто придёт учить обратный ход
    # уклонам, прочёл вопрос ПРЕЖДЕ, чем купит порчу.
    "slopes": ("angle_deg внутри уклона; род ЖИВОЙ (create_roof поднимается). "
               "В DEG_KINDS нельзя до разделения округления и сдвига: 30.25 → 30.0"),
}

# ---------------------------------------------------------------------------
# LAW OF THE NESTED KEY: THE KIND IS ASKED, NOT GUESSED FROM ITS SHAPE
# ---------------------------------------------------------------------------
#
# 🔴 WHAT THIS COST (03.09.2026, corpus of 56 decompiles / 82 451 operations).
# Before this fix, the kind of a nested value was derived FROM ITS SHAPE, and
# FOUR places did this, each in its own way:
#
#   `_round_mm`     "a number inside a millimeter composite is itself
#                   millimeters"
#   `_shift`        "a list of 2-3 numbers inside an area is a world point"
#   `_expr`         the reverse shift, repeating `_shift`'s guess
#   `_origin`       the local frame's origin, looking for a corner by the
#                   same guess
#
# None of them asked what KIND the field was declared as. Convention was
# taken for authority (form 7), and the class bit for the THIRD time
# running, each time under a new name: `normal`/`x_dir` on the plane (21.08)
# -> `ref_dir` as a bare parameter (21.08) -> `x_axis`/`y_axis` INSIDE the
# arc. The `FREE_KEYS` guard was written against the FIRST occurrence and so
# stayed silent BY CONSTRUCTION (form 54).
#
# WHAT THIS COST ON THE CORPUS (measured 03.09.2026, the 3 most populated
# floors of each of the 56 decompiles, 320 operations with a composite
# value):
#
#   arc.end_angle_rad     299 ops   -1.5707963267948744 -> -2.0  (-90° -> -114.6°)
#   arc.start_angle_rad   287 ops    3.4732052114696415 ->  3.0  (199.0° -> 171.9°)
#   arc.x_axis            266 ops    0.3255681544570712 ->  0.0  (axis zeroed out)
#   arc.y_axis            266 ops   -0.3255681544570712 ->  0.0
#   arc.x_axis            299 ops   THE SHIFT subtracted the frame's origin
#                                   from the DIRECTION
#   arc.y_axis            299 ops   the same
#
# In other words, radians were being rounded as if they were millimeters on
# `create_wall` — the most frequent op of the lift — while the arc's axes
# were getting the apartment's origin. `rotation_deg` of the rectangular
# area, after which the class was named, did not occur ONCE in the corpus
# (every area there is `poly`): the RAREST member of the class was the one
# that got named.
#
# 🔴 WHY THE TABLE IS HANDWRITTEN WHILE THE DENOMINATOR IS DERIVED — AND
# THESE ARE DIFFERENT THINGS. A field's role ("position" versus "quantity")
# is a human judgment: it cannot be derived from the schema, where both are
# just "an array of two numbers". But the LIST of keys that must have an
# answer is derived exactly — from the language's generated schema
# (`schema_gen.program_schema()`, today 39 keys inside the
# `MM_KINDS|DEG_KINDS` kinds). Handwritten ON TOP OF a derived denominator is
# honest: a new nested key in the language turns the guard red instead of
# being guessed. Handwritten on top of handwritten is not, and that is
# exactly what stood here.
# Held by `decompile/tests/test_the_role_of_a_nested_key_is_asked.py`.
#
# A role field on `contour._Slot` would be more honest than this table (one
# authority instead of two kept in sync), but that is a LANGUAGE change, and
# the owner decides it.

#: A world point: rounds to millimeters AND SHIFTS into the local frame.
POSITION = "position"
#: A millimeter QUANTITY (dimension, radius, offset): rounds, does NOT
#: shift. The frame does not touch it — a size does not depend on where the
#: apartment stands.
LENGTH = "length"
#: Degrees: round to three decimal places, do not shift.
ANGLE_DEG = "angle_deg"
#: Radians: are NOT ROUNDED AT ALL, and are not shifted. A millimeter grain
#: here is 57 degrees, so that is not rounding, it is corruption.
ANGLE_RAD = "angle_rad"
#: Dimensionless (direction, index, string, flag): nobody touches it.
FREE = "free"
#: Container: carries no value itself, we descend inside by the law of KEYS.
COMPOUND = "compound"

#: THE LAW OF EACH NESTED KEY. An answer to TWO questions at once, and this
#: is the load-bearing distinction: `size_mm` is millimeters but NOT a
#: position; `origin_mm` is millimeters AND a position; `x_axis` is neither.
#: With one flat set (which is what `FREE_KEYS` was), these three cases are
#: indistinguishable, and that is why five kinds sat parked in
#: `MM_KINDS_REFUSED` — they had no honest place.
KEY_LAW: dict[str, str] = {
    # ── area and profile containers ────────────────────────────────────
    "outer": COMPOUND, "holes": COMPOUND,
    "arcs": COMPOUND, "splines": COMPOUND,
    "at_grid": COMPOUND,           # ["Б", "3"] либо {grid, offset_mm, toward}

    # ── world points ───────────────────────────────────────────────────
    "origin": POSITION,            # rect/l origin — a point OR an attachment to grids
    "origin_mm": POSITION,         # sketch plane origin
    "center_mm": POSITION,         # arc center
    "point": POSITION,             # literal form of the attachment
    "points_mm": POSITION,         # contour ring
    "vertices_mm": POSITION,       # mesh vertices
    "via_mm": POSITION,            # points the spline passes through
    "xyz_mm": POSITION,            # graph node
    # Reachable not through the `MM_KINDS` scheme of kinds, but by other
    # paths. If removed, they would stop being rounded SILENTLY, so they are
    # left with a declared law.
    "p0_mm": POSITION, "p1_mm": POSITION, "xy": POSITION, "xyz": POSITION,
    "at": POSITION, "position_mm": POSITION, "anchor_mm": POSITION,
    "outline": POSITION,

    # ── millimeter QUANTITIES: round yes, shift no ──────────────
    "size_mm": LENGTH,             # 🔴 F-091: was shifted as a point
    "cut_mm": LENGTH,              # an L-shaped void, the same corruption
    "radius_mm": LENGTH,
    "offset_mm": LENGTH,           # offset from a grid — a displacement, not a position
    "z": LENGTH, "z_mm": LENGTH,   # an elevation mark: the plan's frame does not touch it
    # `delta_mm` is a DISPLACEMENT. Before this fix it sat among the
    # millimeter keys and would have been shifted as a point, had it landed
    # inside a kind from `MM_KINDS`.
    "delta_mm": LENGTH,

    # ── angles ────────────────────────────────────────────────────────────
    "rotation_deg": ANGLE_DEG,     # 🔴 F-090: 30.25 -> 30.0
    "start_angle_rad": ANGLE_RAD,  # 🔴 π/4 -> 1.0 rad on 287 operations of the corpus
    "end_angle_rad": ANGLE_RAD,    # 🔴 -π/2 -> -2.0 rad on 299 operations

    # ── dimensionless ────────────────────────────────────────────────────
    # 🔴 `normal`, `x_dir`, `x_axis`, `y_axis` are DIRECTIONS, and they are
    # lists of three numbers, so indistinguishable by shape from a point.
    # Rounding would turn [0.7071, 0.7071, 0] into the vector [1.0, 1.0, 0.0]
    # (length 1.41, a different angle), shifting would subtract the frame's
    # origin from the direction. Neither would fail anywhere: three numbers
    # remain three numbers.
    "normal": FREE, "x_dir": FREE, "x_axis": FREE, "y_axis": FREE,
    "bulge": FREE, "edge": FREE, "u": FREE, "v": FREE,
    # 🔴 `triangles` are VERTEX INDICES. The shift turned [0, 1, 2] into the
    # point [-1000.0, -499.0, 2]: the mesh topology stopped pointing at the
    # vertices.
    "triangles": FREE,
    "shape": FREE, "corner": FREE, "dir": FREE, "curve_type": FREE,
    "grid": FREE, "toward": FREE, "at_element": FREE,
    "by": FREE, "value": FREE, "id": FREE,
}

#: Nested-structure keys that carry a MILLIMETER POSITION. Derived from the
#: law, not written as a second list: two carriers of the same knowledge
#: drift apart at the first edit — a named defect of this tree.
MM_KEYS = frozenset(k for k, law in KEY_LAW.items() if law == POSITION)
#: Dimensionless keys: NOBODY rounds or shifts them. Also derived.
FREE_KEYS = frozenset(k for k, law in KEY_LAW.items() if law == FREE)

#: THE LAW OF THE WHOLE PARAMETER — the same question, but to the kind from
#: the registry. Needed because a root value has no key: `pt_xy` arrives as
#: a bare list.
KIND_LAW: dict[str, str] = {
    "mm": LENGTH,
    "deg": ANGLE_DEG,
    "pt_xy": POSITION, "pt_xyz": POSITION, "pt_view2d": POSITION,
    "pts": POSITION, "pts_xyz": POSITION, "pts_list": POSITION,
    "path": POSITION, "path3": POSITION, "placements": POSITION,
    "region": COMPOUND, "arc": COMPOUND, "plane": COMPOUND,
    "graph_nodes": COMPOUND, "mesh": COMPOUND,
}

# 🔴 A LOCK ON IMPORT, NOT A TEST: a kind that lands in `MM_KINDS` without a
# law would again start being guessed from its shape — exactly the defect
# being fixed here. A silent divergence between two lists costs more than a
# loud import failure.
_kinds_without_law = (MM_KINDS | DEG_KINDS) - set(KIND_LAW)
_laws_without_kind = set(KIND_LAW) - (MM_KINDS | DEG_KINDS)
if _kinds_without_law or _laws_without_kind:
    raise AssertionError(
        "KIND_LAW и MM_KINDS|DEG_KINDS разошлись: без закона %s, лишние %s. "
        "Род без закона печатается ДОГАДКОЙ ПО ОБЛИКУ значения — это дефект, "
        "против которого написана вся таблица выше"
        % (sorted(_kinds_without_law), sorted(_laws_without_kind)))
del _kinds_without_law, _laws_without_kind


def key_law(key: str) -> str | None:
    """The law of a nested key. `None` means NOT DECLARED — that is a refusal,
    not a guess.

    The only door to `KEY_LAW`: four places each read the role in their own
    way, and all four drifted apart. The law must be asked here, not
    reconciled between sets by hand.
    """

    return KEY_LAW.get(key)


def param_kinds() -> dict[tuple[str, str], str]:
    """`(op, parameter) -> kind`. THE AUTHORITY is the registry, not a guess by name."""

    from kir import spec

    return {(name, p.name): p.kind
            for name, ospec in spec.OPS.items() for p in ospec.params}


def param_names() -> dict[str, frozenset[str]]:
    """`op -> the names of its parameters`. The same question to the same
    registry.

    Needed for the `unknown_param` refusal: `dsl` builds the function's
    signature from this same list, so a field that is not here will crash
    the execution of the printed script — and it is better to name that
    BEFORE printing.
    """

    from kir import spec

    return {name: frozenset(p.name for p in ospec.params)
            for name, ospec in spec.OPS.items()}


def phase_budget() -> int:
    """How many operations fit in a PHASE. Asked from the compiler.

    🔴 THIS NUMBER WAS GUESSED TWICE, AND BOTH TIMES WRONG. First 250 "with
    margin from `MAX_BULK_OPS = 300`" (the value IS QUOTED here as part of
    that day's mistaken guess; ask `compiler` for the live value — on
    18.08.2026 it became 10000) — the language refused: under a phase, the
    AUTHOR'S budget `MAX_OPS_PER_PROGRAM` applies, because a phase is
    exactly the program that a single transaction will execute, and its
    size is the size of what will roll back entirely on the very first
    failure.

    That is why what stands here is not a literal but a QUESTION: if the
    registry constant moves, the printout moves with it, with no second
    place free to go stale.
    (Measured 17.08.2026 on this tree: `MAX_OPS_PER_PROGRAM = 100`. The
    canon's prose names 20 — that is about a DIFFERENT edition and is not an
    authority here.)
    """

    from kir.compiler import MAX_OPS_PER_PROGRAM

    return int(MAX_OPS_PER_PROGRAM)


def program_ceiling() -> int:
    """The ceiling of ONE program. The same question to the compiler
    (`MAX_BULK_OPS`)."""

    from kir.compiler import MAX_BULK_OPS

    return int(MAX_BULK_OPS)


# ---------------------------------------------------------------------------
# Rounding and literals
# ---------------------------------------------------------------------------

def _round_mm(value: Any, law: str = POSITION) -> Any:
    """Rounding BY THE DECLARED LAW, not by the value's shape.

    Whole millimeters — so that a shift into the local frame is exact
    (`(abs - origin) + origin == abs`). But only quantities MEASURED in
    millimeters have the right to become whole millimeters, and that is
    asked from `KEY_LAW`, not from the value's shape: a radian, a vertex
    index, and the cosine of an angle look like a number exactly the same
    way a length does.

    The `POSITION` default keeps former callers with a single argument;
    descending into a dict, the law is taken from the KEY, not inherited.
    """

    if law in (FREE, ANGLE_RAD):
        return value
    if isinstance(value, bool):
        return value
    if law == ANGLE_DEG:
        if isinstance(value, (int, float)):
            return round(float(value), 3)
        if isinstance(value, list):
            return [_round_mm(item, ANGLE_DEG) for item in value]
        return value
    if law == COMPOUND:
        if isinstance(value, dict):
            return {k: _round_mm(v, key_law(k) or FREE)
                    for k, v in value.items()}
        if isinstance(value, list):
            return [_round_mm(item, COMPOUND) for item in value]
        return value
    # POSITION and LENGTH: both are millimeter kinds, they differ only at `_shift`.
    if isinstance(value, (int, float)):
        return float(round(value))
    if isinstance(value, list):
        return [_round_mm(item, law) for item in value]
    if isinstance(value, dict):
        return {k: _round_mm(v, key_law(k) or FREE) for k, v in value.items()}
    return value


def _round_by_kind(op_name: str, param: str, value: Any,
                   kinds: Mapping[tuple[str, str], str]) -> Any:
    """Round a value BY THE PARAMETER'S KIND, asked from the registry."""

    kind = kinds.get((op_name, param))
    law = KIND_LAW.get(kind) if kind is not None else None
    if law is not None:
        return _round_mm(value, law)
    if isinstance(value, dict):
        # A nested structure of unknown kind: keys with a DECLARED law obey
        # it, everything else is left untouched. Otherwise a contour is
        # unreadable.
        return {k: (_round_mm(v, key_law(k)) if key_law(k) else v)
                for k, v in value.items()}
    return value


_BAD_IDENT = re.compile(r"[^0-9A-Za-zА-Яа-яёЁ_]+")


def _ident(prefix: str, text: Any, taken: set[str]) -> str:
    """A readable variable name from a type name.

    Collisions are resolved by a NUMBER, not by silent rewriting: two
    different things cannot become one variable.
    """

    body = _BAD_IDENT.sub("_", str(text)).strip("_")[:32] or "x"
    if body[0].isdigit():
        body = "_" + body
    name = "%s_%s" % (prefix, body)
    if name in taken:
        n = 2
        while "%s_%d" % (name, n) in taken:
            n += 1
        name = "%s_%d" % (name, n)
    taken.add(name)
    return name


#: A marker for "this is already a ready-made expression, not a literal".
#: Inside printing, a value can become the text `dx + 370`, and it must be
#: told apart from a string value EXPLICITLY, not by appearance. The
#: character chosen is unprintable: it cannot occur in Revit data.
_EXPR = "\x00"


def _lit(value: Any) -> str:
    """A Python literal. Whole millimeters print without a trailing `.0`."""

    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float) and value == int(value) and abs(value) < 1e15:
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_lit(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join("%s: %s" % (json.dumps(k, ensure_ascii=False),
                                           _lit(v))
                               for k, v in value.items()) + "}"
    if value is None:
        return "None"
    return repr(value)


def _shift(value: Any, dx: float, dy: float, kind: str | None) -> Any:
    """Shift planar coordinates into the unit's LOCAL frame.

    Only X and Y are shifted: for `pt_xyz` the third coordinate is an
    elevation mark, and it has nothing to do with the apartment's position
    in plan. Kinds are asked from the registry.
    """

    if kind not in MM_KINDS or (dx == 0 and dy == 0):
        return value

    def walk(node: Any, law: str) -> Any:
        if law == POSITION:
            if isinstance(node, list):
                if node and all(isinstance(c, (int, float))
                                and not isinstance(c, bool) for c in node) \
                        and len(node) in (2, 3):
                    out = [node[0] - dx, node[1] - dy]
                    return out + list(node[2:]) if len(node) > 2 else out
                return [walk(c, POSITION) for c in node]
            if isinstance(node, dict):
                # A position can be a DICT: an attachment to grids. Inside
                # it sits `offset_mm` — a displacement, and the frame does
                # not touch it.
                return {k: walk(v, key_law(k) or FREE)
                        for k, v in node.items()}
            return node
        if law == COMPOUND:
            if isinstance(node, dict):
                return {k: walk(v, key_law(k) or FREE)
                        for k, v in node.items()}
            if isinstance(node, list):
                return [walk(c, COMPOUND) for c in node]
            return node
        # LENGTH, ANGLE_DEG, ANGLE_RAD, FREE — the frame does not touch them
        # AT ALL. A dimension, radius, angle, and direction do not depend on
        # where the apartment stands; subtracting the frame's origin from
        # them would change the QUANTITY.
        return node

    return walk(value, KIND_LAW.get(kind, FREE))


# ---------------------------------------------------------------------------
# Object values: unit, refusal, program, the whole decompile
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SourceUnit:
    """A floor's semantic unit: an apartment, common areas, a zone.

    `op_ids` are OPERATION ADDRESSES (`materialize._op_id`), not tree nodes:
    a node carries its own hash, and it never matches an operation's
    address, not in a single case.
    """

    kind: str
    label: str
    op_ids: frozenset[str]


#: HOW MANY OF A UNIT'S OPERATIONS MUST LIE IN THIS PROGRAM TO WARRANT A
#: FUNCTION. The threshold is set BY MEASUREMENT, not by taste: the
#: materializer's law "(b) rooms to the tail" drives every `create_room`
#: into the last chunk, and on `k2_ar_rd_v7`/L22 (17.08.2026) the tail
#: program held 60 rooms from 23 apartments — meaning **at a threshold of 1,
#: 20 functions would be printed with exactly one operation each**, each
#: with its own frame `dx + 0, dy + 0`. A function of a single call groups
#: nothing and reads worse than a bare line; a local frame for a single
#: point is degenerate by construction (canon: "a positional check requires
#: a cardinality ≥ 2, otherwise the anchor is the whole sample").
MIN_UNIT_OPS = 2

#: WHY PRINTING CAN REFUSE. The list is **CLOSED, BUT NOT FULL** (canon,
#: the second kind of list): its membership is held by discipline, while
#: completeness is unreachable — "printing failed" is discovered when it
#: fires, and is not derived automatically. The absence of a line here
#: means "we do not know of such a case", NOT "such a case cannot happen".
REFUSAL_CAUSES: dict[str, str] = {
    "unknown_op": "имени операции нет в реестре — печатать нечем "
                  "(`dsl` не породит функцию, которой нет у `spec.OPS`)",
    "unknown_param": "поле не объявлено параметром этого опа: `dsl` строит "
                     "сигнатуру из реестра и откажет при исполнении",
    "op_without_id": "у операции нет строкового `id` — по нему на неё "
                     "ссылаются соседи, и без него ссылка неразрешима",
    "duplicate_op_id": "две операции с одним `id` в одной программе "
                       "(компилятор зовёт это KIR-P006)",
    "ref_outside_program": "`by=ref` указывает наружу программы: "
                           "напечатанный текст нёс бы висячую ссылку",
    "program_over_ceiling": "операций больше потолка одной программы "
                            "(`MAX_BULK_OPS`)",
    "null_param_value": "значение поля `None`: `dsl` молча выбросит поле, и "
                        "исходник станет ТИШЕ разбора",
    "value_not_finite": "нечисло или бесконечность — питон-литерала нет",
    "value_not_printable": "значение не выражается литералом языка "
                           "(не строка/число/логическое/список/словарь)",
    # 🔴 A THIRD OUTCOME INSTEAD OF A GUESS (03.09.2026). A key inside a
    # composite value that has no declared law used to be GUESSED from its
    # shape: a number is millimeters, a list of 2-3 numbers is a world
    # point. Both guesses silently corrupted the quantity (an arc's radians,
    # an arc's axes, mesh indices, an area's dimension), and neither ever
    # failed anywhere: numbers remain numbers. There is NO safe default for
    # this question — "leave it alone" corrupts a position, "touch it"
    # corrupts everything else — so the outcome is a third one. The cost of
    # the refusal is measured, not estimated: on a corpus of 56 decompiles /
    # 82 451 operations, all 11 live nested keys are declared, 0 refusals
    # out of 320.
    "undeclared_nested_key": "ключ внутри составного значения не объявлен в "
                             "`KEY_LAW`: его роль (положение / величина / "
                             "угол / безразмерное) неизвестна, а угадать её "
                             "по облику значения — тот самый дефект, против "
                             "которого написан закон",
}


@dataclass(frozen=True, slots=True)
class SourceRefusal:
    """A printing refusal with a NAMED reason, an address, and the next turn."""

    cause: str
    program_index: int
    op_id: str | None
    op_name: str | None
    detail: str

    def __post_init__(self) -> None:
        if self.cause not in REFUSAL_CAUSES:
            raise ValueError(
                "причина отказа %r не объявлена в REFUSAL_CAUSES: "
                "безымянный отказ — это молчание с оправданием" % (self.cause,))

    @property
    def reason_ru(self) -> str:
        return REFUSAL_CAUSES[self.cause]

    def line(self) -> str:
        where = " · оп %s" % self.op_id if self.op_id else ""
        what = " · %s" % self.op_name if self.op_name else ""
        return "%s (программа %d%s%s): %s — %s" % (
            self.cause, self.program_index + 1, what, where,
            self.reason_ru, self.detail)


@dataclass(frozen=True, slots=True)
class ProgramSource:
    """One printed program and everything one needs to know about it without reading."""

    text: str
    index: int
    ops: int
    #: `element_id` selectors for which no name was found in the profile.
    #: They are printed in an HONEST form and marked `??` — but their count
    #: must be visible, or the reader will mistake an anonymous type for a
    #: normal one.
    unresolved_names: int = 0
    #: Units lying entirely within this program: the function here is the whole apartment.
    units_printed: int = 0
    #: Units CUT by the materializer's chunk boundary: the function holds a
    #: part, and its docstring says "N of M of the unit's operations".
    #: Addressability ("move the apartment with one line") is lost, and
    #: this is NAMED, not hidden.
    units_partial: int = 0
    #: Units larger than the phase budget: printed as a BODY (a function
    #: call is one line, and there is nothing to cut it into phases with).
    units_oversize: int = 0
    #: Units that bring fewer than `MIN_UNIT_OPS` operations here: also as a body.
    units_thin: int = 0
    #: Units whose reference subgraph is NOT CLOSED (something looks into
    #: them from outside, or they look outside): a function would hide a
    #: variable in a local scope, and the source would fail with
    #: `NameError`. Printed as a body.
    units_linked_out: int = 0
    phases: int = 0


@dataclass(frozen=True, slots=True)
class _UnitSlice:
    """A unit through the eyes of ONE program: what is here and how much
    there is in total.

    The difference between `here` and `total` is the only way not to lie in
    a function's name: `unit_apartment_3`, holding 13 of 22 operations, must
    say so itself, because the reader sees only the text.
    """

    unit: SourceUnit
    here: frozenset[str]
    total: int


@dataclass(frozen=True, slots=True)
class SourceRendering:
    """The whole decompile: what was printed, what was refused, and whether the count adds up."""

    parts: tuple[ProgramSource, ...] = ()
    refusals: tuple[SourceRefusal, ...] = ()
    ops_total: int = 0
    ops_printed: int = 0
    programs_total: int = 0

    @property
    def ok(self) -> bool:
        """Everything was printed. Otherwise — three outcomes, not two."""

        return (not self.refusals
                and self.ops_printed == self.ops_total
                and len(self.parts) == self.programs_total)

    @property
    def texts(self) -> tuple[str, ...]:
        return tuple(part.text for part in self.parts)

    @property
    def empty(self) -> bool:
        """There was NOTHING to print — that is a third outcome, not a
        success.

        🔴 A ZERO FOR A QUANTITY THAT WAS NOT COUNTED HERE IS NOT A RESULT.
        Measured 17.08.2026: on `snowdon_elec_v1`, the four most populated
        floors gave `leaves_to_program` ZERO programs (every leaf went into
        `skipped`), and a round-trip run over them "converged" — green by
        construction, exactly the degenerate trial the canon warns against.
        An empty decompile must read as empty, not as printed.
        """

        return self.ops_total == 0

    def report_ru(self) -> str:
        head = "напечатано %d операций из %d, программ %d из %d" % (
            self.ops_printed, self.ops_total,
            len(self.parts), self.programs_total)
        if self.empty:
            return head + " — ПЕЧАТАТЬ БЫЛО НЕЧЕГО (материализатор не выдал " \
                          "ни одной программы; смотри его `skipped`)"
        if self.ok:
            return head + " — ПОЛНО"
        lines = [head + " — 🔴 НЕПОЛНО"]
        by_cause = collections.Counter(r.cause for r in self.refusals)
        for cause, count in by_cause.most_common():
            lines.append("   %s ×%d — %s" % (cause, count,
                                             REFUSAL_CAUSES[cause]))
        for refusal in self.refusals[:8]:
            lines.append("   " + refusal.line())
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Check BEFORE printing: three outcomes begin here
# ---------------------------------------------------------------------------

def _printable(value: Any) -> str | None:
    """`None` if the value is expressible as a literal; otherwise the reason's name."""

    if value is None:
        return "null_param_value"
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return "value_not_finite"
        return None
    if isinstance(value, str):
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            got = _printable(item)
            if got is not None:
                return got
        return None
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                return "value_not_printable"
            got = _printable(item)
            if got is not None:
                return got
        return None
    return "value_not_printable"


def _undeclared_keys(op_name: Any, param: str, value: Any,
                     kinds: Mapping[tuple[str, str], str]) -> list[str]:
    """Keys inside a composite value that have NO declared law.

    Asked only where the law applies at all — inside the `MM_KINDS|DEG_KINDS`
    kinds. For other kinds, the nested structure is neither rounded nor
    shifted, so its keys need no role either.
    """

    kind = kinds.get((op_name, param)) if isinstance(op_name, str) else None
    if kind not in MM_KINDS and kind not in DEG_KINDS:
        return []
    found: list[str] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                if isinstance(k, str) and k not in seen and key_law(k) is None:
                    seen.add(k)
                    found.append(k)
                walk(v)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(value)
    return found


def _check_program(ops: Sequence[Mapping[str, Any]], index: int,
                   known_params: Mapping[str, frozenset[str]],
                   ceiling: int,
                   kinds: Mapping[tuple[str, str], str]) -> list[SourceRefusal]:
    """Everything because of which the program will NOT be printed. Empty — we print."""

    out: list[SourceRefusal] = []
    if len(ops) > ceiling:
        out.append(SourceRefusal(
            "program_over_ceiling", index, None, None,
            "операций %d при потолке %d" % (len(ops), ceiling)))
    seen: set[str] = set()
    for op in ops:
        name = op.get("op")
        oid = op.get("id")
        if not isinstance(oid, str) or not oid:
            out.append(SourceRefusal("op_without_id", index, None,
                                     str(name) if name else None,
                                     "id=%r" % (oid,)))
            continue
        if oid in seen:
            out.append(SourceRefusal("duplicate_op_id", index, oid,
                                     str(name) if name else None,
                                     "этот адрес уже занят выше"))
        seen.add(oid)
        if not isinstance(name, str) or name not in known_params:
            out.append(SourceRefusal("unknown_op", index, oid,
                                     str(name) if name else None,
                                     "в реестре %d операций, этой нет"
                                     % len(known_params)))
            continue
        allowed = known_params[name]
        for key, value in op.items():
            if key in ("op", "id"):
                continue
            if key not in allowed:
                out.append(SourceRefusal(
                    "unknown_param", index, oid, name,
                    "поле %r; реестр знает: %s"
                    % (key, ", ".join(sorted(allowed)) or "(ни одного)")))
                continue
            cause = _printable(value)
            if cause is not None:
                out.append(SourceRefusal(cause, index, oid, name,
                                         "поле %r" % (key,)))
                continue
            for undeclared in _undeclared_keys(name, key, value, kinds):
                out.append(SourceRefusal(
                    "undeclared_nested_key", index, oid, name,
                    "поле %r несёт ключ %r без объявленного закона; объяви "
                    "его в `program_source.KEY_LAW` одним из "
                    "POSITION/LENGTH/ANGLE_DEG/ANGLE_RAD/FREE"
                    % (key, undeclared)))
    ids = seen
    for op in ops:
        oid = op.get("id")
        for key, value in op.items():
            if key in ("op", "id"):
                continue
            for target in _iter_ref_targets(value):
                if target not in ids:
                    out.append(SourceRefusal(
                        "ref_outside_program", index,
                        oid if isinstance(oid, str) else None,
                        op.get("op") if isinstance(op.get("op"), str) else None,
                        "поле %r ссылается на %r, которого в программе нет"
                        % (key, target)))
    return out


def _ref_components(ops: Sequence[Mapping[str, Any]]) \
        -> dict[str, frozenset[str]]:
    """`operation id -> its WHOLE reference component`.

    One count per program, two consumers: a unit's closure (can it become a
    function without hiding someone else's variable) and grouping the free
    part (a wall and its doors belong to one phase). Counting this twice
    would mean keeping two places that must agree — a named defect of this
    tree.
    """

    parent = {op["id"]: op["id"] for op in ops}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for op in ops:
        for key, value in op.items():
            if key in ("op", "id"):
                continue
            for target in _iter_ref_targets(value):
                if target in parent:
                    ra, rb = find(op["id"]), find(target)
                    if ra != rb:
                        parent[ra] = rb

    members: dict[str, set[str]] = collections.defaultdict(set)
    for oid in parent:
        members[find(oid)].add(oid)
    return {oid: frozenset(members[find(oid)]) for oid in parent}


def _iter_ref_targets(value: Any) -> Iterator[Any]:
    if isinstance(value, Mapping):
        if value.get("by") == "ref":
            yield value.get("value")
            return
        for item in value.values():
            yield from _iter_ref_targets(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_ref_targets(item)


# ---------------------------------------------------------------------------
# Printing one program
# ---------------------------------------------------------------------------

class _Printer:
    """A program -> `program_py` text. Nothing is invented: whatever is not
    in the decompile is not in the printout either."""

    def __init__(self, ops: Sequence[Mapping[str, Any]], *,
                 kinds: Mapping[tuple[str, str], str],
                 type_names: Mapping[int, str],
                 units: Sequence[_UnitSlice],
                 level: str, run: str, document: str,
                 index: int, total: int, floor_ops: int) -> None:
        self.ops = list(ops)
        self.kinds = kinds
        self.type_names = type_names
        self.units = list(units)
        self.level, self.run, self.document = level, run, document
        self.index, self.total, self.floor_ops = index, total, floor_ops
        self.taken: set[str] = set()
        self.const: dict[tuple[str, Any], str] = {}
        self.const_lines: list[str] = []
        self.var_of: dict[str, str] = {}
        self.unresolved = 0
        self.units_printed = 0
        self.units_partial = 0
        self.units_oversize = 0
        self.units_thin = 0
        self.units_linked_out = 0
        self.phases = 0

    # ── selectors ────────────────────────────────────────────────────────
    def selector(self, value: Mapping[str, Any]) -> str:
        by = value.get("by")
        if by == "ref":
            target = value.get("value")
            var = self.var_of.get(target)
            if var:
                return var
            # Unreachable: a reference outside the program is a REFUSAL
            # (`_check_program`), not an invented variable. The branch is
            # left honest in case printing is called bypassing the check.
            return "by_ref(%s)" % _lit(target)
        if by == "element_id":
            key = ("element_id", value.get("value"))
            if key not in self.const:
                eid = value.get("value")
                label = None
                if eid is not None:
                    try:
                        label = self.type_names.get(int(eid))
                    except (TypeError, ValueError):
                        label = None
                if not label:
                    self.unresolved += 1
                short = (label or "").split(" / ")[-1]
                var = _ident("T", short or "id%s" % eid, self.taken)
                self.const[key] = var
                self.const_lines.append(
                    "%s = by_element_id(%s)%s"
                    % (var, _lit(eid),
                       ("  # «%s»" % label) if label
                       else "  # ?? имени в профиле нет"))
            return self.const[key]
        if by == "name":
            key = ("name", value.get("value"))
            if key not in self.const:
                var = _ident("N", value.get("value"), self.taken)
                self.const[key] = var
                self.const_lines.append("%s = by_name(%s)"
                                        % (var, _lit(value.get("value"))))
            return self.const[key]
        if by == "default":
            return "DEFAULT"
        if by == "family_type":
            return "family_type(%s, %s)" % (_lit(value.get("family")),
                                            _lit(value.get("value")))
        return _lit(dict(value))              # unknown shape — as is

    # ── one operation ────────────────────────────────────────────────────
    def call(self, op: Mapping[str, Any], dx: float = 0.0, dy: float = 0.0,
             indent: str = "") -> str:
        name = op["op"]
        args: list[str] = []
        for key, value in op.items():
            if key in ("op", "id"):
                continue
            kind = self.kinds.get((name, key))
            value = _round_by_kind(name, key, value, self.kinds)
            value = _shift(value, dx, dy, kind)
            if isinstance(value, Mapping) and value.get("by"):
                args.append("%s=%s" % (key, self.selector(value)))
            elif isinstance(value, list) and value and all(
                    isinstance(v, Mapping) and v.get("by") for v in value):
                args.append("%s=[%s]" % (key, ", ".join(
                    self.selector(v) for v in value)))
            else:
                if dx or dy:
                    value = self._offset_expr(value, kind, dx, dy)
                if isinstance(value, str) and value.startswith(_EXPR):
                    args.append("%s=%s" % (key, value[1:]))
                else:
                    args.append("%s=%s" % (key, _lit(value)))
        args.append("id=%s" % _lit(op["id"]))
        var = self.var_of.get(op["id"])
        head = "%s%s = " % (indent, var) if var else indent
        return "%s%s(%s)" % (head, name, ", ".join(args))

    def _offset_expr(self, value: Any, kind: str | None,
                     dx: float, dy: float) -> Any:
        """A local coordinate is printed as `dx + <локальное>`.

        🔴 THE SHIFT AND THE REVERSE SHIFT MUST KNOW THE SAME SHAPES. The
        first edition handled lists and did NOT handle dicts, and `contour`
        is a dict (`{"outer": {...}, "holes": [...]}`). `_shift` subtracted
        the frame's origin, printing returned the bare number, and the
        contour drifted by exactly the unit's origin: in the source
        `[-370, 24214]`, in the printout `[670, 24844]`. Caught by a
        round-trip run on one floor out of twenty — invisible to the eye,
        because the numbers look plausible.
        """

        if kind not in MM_KINDS:
            return value
        return self._expr(value, KIND_LAW.get(kind, FREE))

    def _expr(self, value: Any, law: str = POSITION) -> Any:
        """An expression with `dx`/`dy` for any shape: a point, a list, a
        dict.

        🔴 THE LAW HERE MUST BE THE SAME ONE `_shift` USES, AND THAT IS NOT A
        STYLE CHOICE. The shift subtracts the frame's origin, printing adds
        it back; let them diverge by even one key, and the quantity drifts
        by exactly the unit's origin, and drifts silently. That is why both
        ask `key_law` instead of repeating each other from memory.
        """

        if law == POSITION:
            if isinstance(value, list) and value and all(
                    isinstance(c, (int, float)) and not isinstance(c, bool)
                    for c in value) and len(value) in (2, 3):
                parts = ["dx + %s" % _lit(value[0]),
                         "dy + %s" % _lit(value[1])]
                parts += [_lit(c) for c in value[2:]]
                return _EXPR + "[" + ", ".join(parts) + "]"
            if isinstance(value, list):
                inner = [self._expr(v, POSITION) for v in value]
                if any(isinstance(v, str) and v.startswith(_EXPR)
                       for v in inner):
                    return _EXPR + "[" + ", ".join(
                        v[1:] if isinstance(v, str) and v.startswith(_EXPR)
                        else _lit(v) for v in inner) + "]"
                return value
            if isinstance(value, Mapping):
                return self._expr_mapping(value)
            return value
        if law == COMPOUND:
            if isinstance(value, Mapping):
                return self._expr_mapping(value)
            if isinstance(value, list):
                inner = [self._expr(v, COMPOUND) for v in value]
                if any(isinstance(v, str) and v.startswith(_EXPR)
                       for v in inner):
                    return _EXPR + "[" + ", ".join(
                        v[1:] if isinstance(v, str) and v.startswith(_EXPR)
                        else _lit(v) for v in inner) + "]"
                return value
            return value
        # LENGTH, ANGLE_*, FREE — we do not add the frame back, because we
        # did not subtract it either: the quantity prints as a literal and
        # does not depend on the shift.
        return value

    def _expr_mapping(self, value: Mapping[str, Any]) -> Any:
        """A dict: each key by ITS OWN law, not all by one."""

        inner_d = {k: self._expr(v, key_law(k) or FREE)
                   for k, v in value.items()}
        if any(isinstance(v, str) and v.startswith(_EXPR)
               for v in inner_d.values()):
            body = ", ".join(
                "%s: %s" % (json.dumps(k, ensure_ascii=False),
                            v[1:] if isinstance(v, str)
                            and v.startswith(_EXPR) else _lit(v))
                for k, v in inner_d.items())
            return _EXPR + "{" + body + "}"
        return value

    # ── the whole program ────────────────────────────────────────────────────
    def render(self, warning: Sequence[str] = ()) -> str:
        by_id = {op["id"]: op for op in self.ops}
        # Variables are created ONLY for what is referenced: a name with no
        # reader is noise, and noise in a building's source costs more than
        # it looks like it does.
        referenced: set[str] = set()
        for op in self.ops:
            for key, value in op.items():
                if key in ("op", "id"):
                    continue
                for target in _iter_ref_targets(value):
                    referenced.add(target)
        for oid in sorted(referenced):
            if oid in by_id:
                self.var_of[oid] = _ident(
                    "w", by_id[oid]["op"].replace("create_", "")
                    + "_" + str(oid)[-4:], self.taken)

        # Reference components are counted ONCE per program: both a unit's
        # closure and grouping the free part ask for them. Two independent
        # counts of the same thing are two places that must agree.
        components = _ref_components(self.ops)
        body: list[str] = []
        unit_calls: list[tuple[str, int]] = []
        budget = phase_budget()
        inlined: set[str] = set()

        for order, slice_ in enumerate(self.units, 1):
            unit = slice_.unit
            here = [op for op in self.ops if op["id"] in slice_.here]
            if not here:
                continue
            whole = len(here) == slice_.total
            if not all(components[op["id"]] <= slice_.here for op in here):
                # 🔴 A FUNCTION HIDES A VARIABLE, AND THE CORPUS FOUND THIS,
                # NOT THE EYE. `w_wall_2846 = create_wall(...)` inside
                # `def unit_…` is a LOCAL name; `create_door(host=w_wall_2846)`
                # outside fails with `NameError`, and the function call's
                # order against the free part breaks even a global name.
                # Measured 17.08.2026: on `k2_ar_rd_v7` this is not visible at
                # all — all 210 references there lie in the free part — while
                # on `sob62_fas_r23_v19`, two floors out of four (1224 and
                # 927 operations) executed with `NameError`. Printing a
                # whole floor on a building where a reference enters an
                # apartment was impossible, and no counter said so.
                # That is why only the unit whose reference subgraph is
                # CLOSED is printed as a function: nobody looks into it from
                # outside, and it does not look at anyone outside.
                inlined |= {op["id"] for op in here}
                self.units_linked_out += 1
                continue
            if len(here) < MIN_UNIT_OPS:
                # The unit brought fewer than `MIN_UNIT_OPS` operations here:
                # a function of a single call is ceremony, not structure.
                # Printed as a body, the `units_thin` counter names it.
                inlined |= {op["id"] for op in here}
                self.units_thin += 1
                continue
            if len(here) > budget:
                # 🔴 A UNIT LARGER THAN THE PHASE BUDGET IS PRINTED AS A
                # BODY, NOT AS A FUNCTION. Measured on `snowdon_plumb_v4`/L4:
                # a unit of 181 operations against a phase budget of 100. A
                # function call is ONE line, and there is nothing to cut it
                # into phases with: Python cannot execute half a call. A
                # body, however, is cut like ordinary operations.
                inlined |= {op["id"] for op in here}
                self.units_oversize += 1
                continue
            ox, oy = self._origin(here)
            # A function's name is built from the unit's LABEL, not from its
            # ordinal number in this program: a cut-up apartment occurs
            # across several source files, and under different names the
            # reader cannot piece them back together. The `fold` label
            # (`apartment:14330363`) addresses the same unit across every
            # program of the floor.
            fname = _ident("unit", unit.label or "%s_%d" % (unit.kind, order),
                           self.taken)
            # 🔴 A CUT-UP UNIT IS STILL PRINTED AS A FUNCTION, BUT SAYS SO
            # ITSELF. Measured 17.08 on `k2_ar_rd_v7`/L22: the materializer's
            # chunk boundary cuts 20 units out of 23 — meaning the rule
            # "a function only for a whole unit" would leave the reader 3
            # functions instead of 23 and would remove the very thing
            # printing was undertaken for. What makes a function a lie is
            # not incompleteness, but SILENT incompleteness: the docstring
            # names both the part and the whole, and in the counter these
            # units stand apart (`units_partial`).
            note = ("операций %d, локальная рамка" % len(here) if whole
                    else "операций %d ИЗ %d — единица разрезана границей "
                         "программы, остальное в соседних" % (len(here),
                                                              slice_.total))
            body.append("")
            body.append("def %s(dx=0, dy=0):" % fname)
            body.append('    """%s — %s."""'
                        % (str(unit.label or unit.kind)[:60], note))
            for op in here:
                body.append(self.call(op, ox, oy, indent="    "))
            # A call's weight is how many operations it brings into a phase.
            # Without it, packing phases would count lines, while the budget
            # measures OPERATIONS.
            unit_calls.append(("%s(dx=%s, dy=%s)"
                               % (fname, _lit(ox), _lit(oy)), len(here)))
            if whole:
                self.units_printed += 1
            else:
                self.units_partial += 1

        in_unit: set[str] = set()
        for slice_ in self.units:
            in_unit |= set(slice_.here)
        loose = [op for op in self.ops
                 if op["id"] not in in_unit or op["id"] in inlined]
        tail = self._grouped_lines(loose)

        kinds_count = collections.Counter(op["op"] for op in self.ops)
        head = [
            "# ЭТАЖ %s%s — программа %d из %d: %d операций%s"
            % (self.level or "?",
               (" · здание «%s»" % self.document) if self.document else "",
               self.index + 1, self.total, len(self.ops),
               (" из %d на этаже" % self.floor_ops)
               if self.floor_ops and self.floor_ops != len(self.ops) else ""),
            "# %s" % ", ".join("%s %d" % kv
                               for kv in kinds_count.most_common(6)),
            "# Напечатано из разбора %s. Это program_py: та же поверхность,"
            % (self.run or "(разбор не назван)"),
            "# на которой модель пишет сама (`dsl.OP_FUNCTIONS` из реестра).",
            "#",
            "# Типы адресованы ИСХОДНЫМ селектором, а смысл несёт имя переменной",
            "# и комментарий рядом: читаемость не куплена ценой точности.",
        ]
        head += ["# " + line for line in warning]
        head += [
            "",
            'envelope(intent=%s)' % _lit("этаж %s из %s (программа %d/%d)"
                                         % (self.level or "?",
                                            self.run or "?",
                                            self.index + 1, self.total)),
            "",
        ]

        # 🔴 A FLOOR DOES NOT FIT INTO ONE TRANSACTION, AND THAT IS NOT OUR
        # CARELESSNESS. The language has its own remedy — `phase()`: a plan
        # is a SEQUENCE of phases, one transaction per phase, and the
        # author's budget measures a PHASE, not a script. The language's
        # condition: draw one boundary and you must mark up EVERYTHING, so
        # both units and the free part go into phases. Packing phases runs
        # BY THE NUMBER OF OPERATIONS, not by the number of lines: one
        # unit's call brings dozens of operations into a phase. Counting
        # lines would mean silently overrunning the budget.
        items = list(unit_calls) + list(tail)
        phases: list[list[str]] = []
        batch: list[str] = []
        weight_sum = 0
        for line, weight in items:
            if weight > budget:
                # 🔴 A GROUP LARGER THAN THE PHASE BUDGET IS CUT, AND THAT IS
                # LEGAL. A cut BY PHASE does not tear a reference — the
                # language re-marks it itself as
                # `{"by": "phase_result", "phase": N}` and will substitute it
                # by that phase's witness. A cut BY PROGRAM would tear it:
                # there, there is nothing left to reference.
                if batch:
                    phases.append(batch)
                    batch, weight_sum = [], 0
                rows = line.splitlines()
                per = max(1, budget * len(rows) // max(1, weight))
                for i in range(0, len(rows), per):
                    phases.append(["\n".join(rows[i:i + per])])
                continue
            if batch and weight_sum + weight > budget:
                phases.append(batch)
                batch, weight_sum = [], 0
            batch.append(line)
            weight_sum += weight
        if batch:
            phases.append(batch)

        # 🔴 A PHASE NAME IS A STRING OF 1..64 CHARACTERS, and this is the
        # language's rule (`course.phase`, refusal KIR-L006: «у фазы обязано
        # быть ИМЯ»). On the facade building, a level is called «План 1
        # этажа на отметках +2,800 , +2,790 , …» — over a hundred
        # characters, and printing refused. The LEVEL NAME gets truncated,
        # while the phase number is kept in full: the refusal is found by
        # it.
        total_phases = len(phases)
        self.phases = total_phases
        plan: list[str] = []
        for i, lines in enumerate(phases, 1):
            tail_txt = ": фаза %d из %d" % (i, total_phases)
            room = 64 - len(tail_txt)
            level_txt = self.level or "этаж"
            head_txt = level_txt if len(level_txt) <= room \
                else level_txt[:room - 1] + "…"
            plan.append("")
            plan.append("with phase(%s):" % _lit(head_txt + tail_txt))
            # A group of related operations arrives as a MULTI-LINE chunk,
            # and every line must be indented, not just the first: otherwise
            # Python gets an `IndentationError` on the group's second
            # element.
            for line in lines:
                plan.extend("    " + part for part in line.splitlines())

        # Constants are collected AS printing proceeds, so their block is
        # assembled AFTER the bodies: assemble it earlier and it comes out
        # empty, because `self.const_lines` is filled by `selector()` during
        # `call()`. In the file, the order stays reader-friendly: constants
        # first, then bodies.
        return "\n".join(
            head
            + ["# ── типы и уровни ──"] + self.const_lines
            + body
            + ["", "# ── план: транзакция на ФАЗУ, бюджет меряет фазу ──"]
            + plan) + "\n"

    def _grouped_lines(self, ops: Sequence[Mapping[str, Any]]) \
            -> list[tuple[str, int]]:
        """`[(lines, weight)]` — operations linked by references, as ONE
        group.

        🔴 A GROUP, NOT A LINE, AND THIS WAS BOUGHT BY A ROUND-TRIP RUN'S
        DIVERGENCE. The first edition packed phases one at a time, and a
        host with its openings landed in DIFFERENT phases. The language
        legally re-marked this: a reference crossing a phase boundary
        becomes `{"by": "phase_result", "phase": N}` — exactly as `phase()`'s
        docstring promises. There was no loss; there was a cut that changed
        the reference's shape for no reason. A wall and its doors belong to
        one transaction by meaning too, not only for the sake of the check.

        The order INSIDE a group is the program's original order, and it is
        not accidental: the materializer topologically sorts the chunk by
        `ref` (law D5d), meaning the host stands before its door. Sorting
        here a second time would mean setting up its own order alongside
        the authoritative one.
        """

        components = _ref_components(ops)
        groups: dict[frozenset[str], list[Mapping[str, Any]]] = \
            collections.OrderedDict()
        for op in ops:
            groups.setdefault(components[op["id"]], []).append(op)
        return [("\n".join(self.call(op) for op in group), len(group))
                for group in groups.values()]

    def _origin(self, ops: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
        """The local frame's zero is the unit's minimum corner, rounded to
        mm. Whole millimeters give an EXACT reverse shift."""

        xs: list[float] = []
        ys: list[float] = []

        # 🔴 ONLY A POSITION COUNTS AS A UNIT'S CORNER, AND THIS IS THE THIRD
        # PLACE WITH THE SAME DEFECT. The previous edition took EVERY list of
        # 2-3 numbers as a candidate, including `size_mm`. Measured
        # 03.09.2026 on two slabs (5000,6000)+[4000,3000] and
        # (12000,9000)+[2000,7000]: the frame's origin came out as
        # (2000, 3000) — a minimum over DIMENSIONS, not over corners. The
        # unit's frame was taken from a size, and the printed apartment
        # stood in the wrong place.
        def walk(node: Any, law: str) -> None:
            if law == POSITION:
                if isinstance(node, list):
                    if node and all(isinstance(c, (int, float))
                                    and not isinstance(c, bool)
                                    for c in node) and len(node) in (2, 3):
                        xs.append(node[0])
                        ys.append(node[1])
                    else:
                        for c in node:
                            walk(c, POSITION)
                elif isinstance(node, Mapping):
                    for k, v in node.items():
                        walk(v, key_law(k) or FREE)
            elif law == COMPOUND:
                if isinstance(node, Mapping):
                    for k, v in node.items():
                        walk(v, key_law(k) or FREE)
                elif isinstance(node, list):
                    for c in node:
                        walk(c, COMPOUND)

        for op in ops:
            for key, value in op.items():
                kind = self.kinds.get((op["op"], key))
                if kind in MM_KINDS:
                    walk(value, KIND_LAW.get(kind, FREE))
        if not xs:
            return 0.0, 0.0
        return float(round(min(xs))), float(round(min(ys)))


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def render_source(
    programs: Sequence[Mapping[str, Any]],
    *,
    level: str = "",
    run: str = "",
    document: str = "",
    type_names: Mapping[int, str] | None = None,
    units: Sequence[SourceUnit] = (),
) -> SourceRendering:
    """KIR programs -> `program_py` source files, one per program.

    Not a single operation disappears silently: a program either prints IN
    FULL, or REFUSES with a named reason, and the count of what was printed
    stands both in the result and in the text of each source file.
    """

    kinds = param_kinds()
    known = param_names()
    ceiling = program_ceiling()
    names = {int(k): str(v) for k, v in (type_names or {}).items()}

    op_lists: list[list[Mapping[str, Any]]] = []
    for program in programs:
        ops = program.get("ops") if isinstance(program, Mapping) else None
        op_lists.append(list(ops) if isinstance(ops, list) else [])
    ops_total = sum(len(ops) for ops in op_lists)

    refusals: list[SourceRefusal] = []
    for index, ops in enumerate(op_lists):
        refusals.extend(_check_program(ops, index, known, ceiling, kinds))
    refused_programs = {r.program_index for r in refusals}

    # The incompleteness warning is collected BEFORE printing and travels
    # INTO EVERY text: the reader of a source file does not hold our object
    # in their hands, and the incompleteness must be visible to exactly
    # them.
    warning: list[str] = []
    if refusals:
        lost = sum(len(op_lists[i]) for i in refused_programs)
        warning.append("")
        warning.append("🔴 НАПЕЧАТАНО НЕ ВСЁ: %d операций из %d, "
                       "программ %d из %d"
                       % (ops_total - lost, ops_total,
                          len(op_lists) - len(refused_programs), len(op_lists)))
        for cause, count in collections.Counter(
                r.cause for r in refusals).most_common():
            warning.append("   отказ %s ×%d — %s"
                           % (cause, count, REFUSAL_CAUSES[cause]))

    # 🔴 A UNIT'S WHOLENESS IS MEASURED ACROSS ALL PROGRAMS AT ONCE, NOT PER
    # ONE. Otherwise "the apartment is cut up" would get mixed up with "one
    # of its operations never materialized at all"
    # (`MaterializeResult.skipped`), and printing would blame the cut for
    # someone else's loss. A unit's whole here is what the materializer
    # HANDED OUT, not what the decompile carried.
    # Units must NOT OVERLAP: an op landing in two of them would be printed
    # twice, and a round-trip run would show "an extra operation" — meaning
    # a defect of the CALLER would read as a defect of printing. `fold`
    # gives non-overlapping children of a floor, but the entry point is open
    # to any caller.
    seen_unit_ops: set[str] = set()
    for unit in units:
        clash = seen_unit_ops & set(unit.op_ids)
        if clash:
            raise ValueError(
                "единицы пересекаются по операциям %s: печать выдала бы их "
                "дважды" % sorted(clash)[:5])
        seen_unit_ops |= set(unit.op_ids)

    materialized = {op["id"] for ops in op_lists for op in ops
                    if isinstance(op.get("id"), str)}
    slices_by_program: dict[int, list[_UnitSlice]] = collections.defaultdict(list)
    for unit in units:
        present = frozenset(unit.op_ids & materialized)
        if not present:
            continue
        for index, ops in enumerate(op_lists):
            here = frozenset(present & {op["id"] for op in ops
                                        if isinstance(op.get("id"), str)})
            if here:
                slices_by_program[index].append(
                    _UnitSlice(unit=unit, here=here, total=len(present)))

    parts: list[ProgramSource] = []
    for index, ops in enumerate(op_lists):
        if index in refused_programs:
            continue
        printer = _Printer(ops, kinds=kinds, type_names=names,
                           units=tuple(slices_by_program.get(index, ())),
                           level=level, run=run, document=document,
                           index=index, total=len(op_lists),
                           floor_ops=ops_total)
        text = printer.render(warning)
        parts.append(ProgramSource(
            text=text, index=index, ops=len(ops),
            unresolved_names=printer.unresolved,
            units_printed=printer.units_printed,
            units_partial=printer.units_partial,
            units_oversize=printer.units_oversize,
            units_thin=printer.units_thin,
            units_linked_out=printer.units_linked_out,
            phases=printer.phases))

    return SourceRendering(
        parts=tuple(parts),
        refusals=tuple(refusals),
        ops_total=ops_total,
        ops_printed=sum(p.ops for p in parts),
        programs_total=len(op_lists))


def source_from_materialized(result: Any, **kwargs: Any) -> SourceRendering:
    """THE SECOND OUTPUT of `leaves_to_program`: the same programs, but as
    source text.

    Takes the whole `MaterializeResult`, not just its `programs`, so the
    caller does not assemble the input by hand: the materializer's
    `skipped` remains its own report, and printing answers exactly for what
    it HANDED OUT.
    """

    programs = getattr(result, "programs", None)
    if programs is None:
        raise TypeError("нужен MaterializeResult (у него есть .programs), "
                        "получено %r" % (type(result).__name__,))
    return render_source(programs, **kwargs)


# ---------------------------------------------------------------------------
# Decompile helpers: ask the TREE, do not re-derive
# ---------------------------------------------------------------------------

_UNIT_KINDS = ("apartment", "mop", "core", "zone")


def find_floor(tree: Mapping[str, Any], level: str) -> Mapping[str, Any] | None:
    """A floor's node in the folded tree. `None` means no such level is in the tree."""

    macro = tree.get("macro") if isinstance(tree, Mapping) else None
    if isinstance(macro, Mapping) and macro.get("type") == "floor" \
            and macro.get("level_name") == level:
        return tree
    for child in (tree.get("children") or ()):
        got = find_floor(child, level)
        if got is not None:
            return got
    return None


def floor_leaves(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """A node's leaves — ASKED FROM `fold`, not traversed by hand.

    🔴 THIS IS NOT STYLE NITPICKING, IT IS A MEASUREMENT. The bench's own
    traversal took only `node["payload"]` and on `k2_ar_rd_v7`/L22 gave
    **994 leaves**, whereas `fold.iter_l1_leaves` gives **1001**: seven
    leaves sit in `members` (the exact-members ledger of folded nodes,
    «fold preserves leaves as law»), and its own traversal cannot see them.
    A silent shortfall of 0.7% of a floor looks like a whole floor — exactly
    the defect this module is written against.
    """

    from kir.decompile.fold import iter_l1_leaves

    seen: set[str] = set()
    out: list[Mapping[str, Any]] = []
    for leaf in iter_l1_leaves(node):          # type: ignore[arg-type]
        if not isinstance(leaf, Mapping) or not leaf.get("op_name"):
            continue
        source = leaf.get("source_element_id")
        key = str(source) if source is not None else str(id(leaf))
        if key in seen:
            continue
        seen.add(key)
        out.append(leaf)
    return out


def floor_units(node: Mapping[str, Any]) -> tuple[SourceUnit, ...]:
    """A floor's semantic units — apartments, common areas, cores, zones.

    Taken from the tree: `fold` has already folded rooms into apartments
    and common areas, and this is not re-derived a second time. An
    operation's address is asked from `materialize._op_id` — repeating the
    formula `"e" + source_element_id` here would mean setting up a second
    place that must agree with the first.
    """

    from kir.decompile.materialize import _op_id

    out: list[SourceUnit] = []
    for child in (node.get("children") or ()):
        macro = child.get("macro") if isinstance(child, Mapping) else None
        tag = macro.get("type") if isinstance(macro, Mapping) else None
        kind = tag or (child.get("kind") if isinstance(child, Mapping) else None)
        if kind not in _UNIT_KINDS:
            continue
        ids = {_op_id(str(leaf["source_element_id"]))
               for leaf in floor_leaves(child)
               if leaf.get("source_element_id") is not None}
        if ids:
            out.append(SourceUnit(kind=str(kind),
                                  label=str(child.get("label") or kind),
                                  op_ids=frozenset(ids)))
    return tuple(out)


# ---------------------------------------------------------------------------
# Round-trip run: without it, the printer is prose
# ---------------------------------------------------------------------------

def execute_source(text: str) -> dict | str:
    """Execute a printed `program_py` and return the program whole.

    🔴 THE ENVIRONMENT IS TAKEN FROM AN AUTHORITY, NOT ASSEMBLED BY HAND.
    Assembling it from `dsl.OP_FUNCTIONS` plus a handful of names would mean
    setting up a SECOND surface alongside the real one. The real one is
    declared in `sandbox.SandboxPolicy(dsl_module="kir.course.language")`:
    that is `dsl` PLUS the course's names (`phase`, `unit`, `take_ops`). A
    script checked against a homemade surface says nothing about the script
    that will actually go to the model.

    The output is `take_ops()`, the sandbox's door: it hands back the
    program together with the phase table in one envelope. The ops remain
    byte-identical throughout.

    A STRING INSTEAD OF A DICT IS A REFUSAL WITH A REASON. A silent empty
    result would be the worst outcome: "nothing got built" is
    indistinguishable from "it matched".

    A live Revit is not needed and is not touched: the language builds
    JSON, without executing it.
    """

    import traceback

    from kir import dsl
    from kir.course import language

    env = {name: getattr(language, name) for name in dir(language)
           if not name.startswith("__")}
    dsl.reset()
    try:
        exec(compile(text, "<этаж>", "exec"), env)   # noqa: S102 — our own text
        program = language.take_ops()
    except Exception as exc:                          # noqa: BLE001
        return "%s: %s\n%s" % (type(exc).__name__, exc,
                               traceback.format_exc()[-1200:])
    if not program:
        return "take_ops() вернул пусто — программа не собралась"
    return program


def _num(value: Any) -> Any:
    """A number — to one kind. `303010` and `303010.0` are one quantity.

    🔴 THE PRINTER ITSELF CREATED THE DIFFERENCE: `_lit` prints integers
    without a trailing `.0` for readability, and the executed program
    carries a Python `int` where the decompile held a `float`. JSON
    considers them different; millimeters do not. It is the COMPARISON that
    is normalized, not the printing: a source file's readability is worth
    more than the convenience of comparison.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Mapping):
        return {k: _num(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_num(v) for v in value]
    return value


def _same_target(value: Any) -> Any:
    """`phase_result` and `ref` — ONE target, differently marked up.

    🔴 THIS IS NOT A CONCESSION TO THE COMPARISON, IT IS A DOCUMENTED
    TRANSFORMATION OF THE LANGUAGE. A reference that crosses a phase
    boundary legally becomes
    `{"by": "phase_result", "phase": N, "value": X}` — the executor will
    substitute it by that phase's witness (`course.phase`'s docstring). The
    target is the same, `value` is the same; only WHO resolves it differs.
    Demanding byte-for-byte equality here would mean declaring the
    language's own work a defect.
    """

    if isinstance(value, Mapping) and value.get("by") == "phase_result":
        return {"by": "ref", "value": value.get("value")}
    if isinstance(value, Mapping):
        return {k: _same_target(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_same_target(v) for v in value]
    return value


def canonical_op(op: Mapping[str, Any],
                 kinds: Mapping[tuple[str, str], str]) -> str:
    """The canonical form of an operation for comparison.

    `id` is DROPPED deliberately: it is an address, not content. A `by=ref`
    reference is kept as is — it addresses the same operation by the same
    id, and if printing lost it, that must show up.
    """

    name = op.get("op")
    body: dict[str, Any] = {}
    for key, value in sorted(op.items()):
        if key in ("op", "id"):
            continue
        body[key] = _num(_same_target(_round_by_kind(name, key, value, kinds)))
    return str(name) + "|" + json.dumps(body, ensure_ascii=False,
                                        sort_keys=True)


@dataclass(frozen=True, slots=True)
class RoundTrip:
    """The result of a round-trip run. A divergence is named by name, not by a number."""

    ok: bool
    source_ops: int
    executed_ops: int
    lost: tuple[tuple[str, int], ...] = ()
    extra: tuple[tuple[str, int], ...] = ()
    refusal: str = ""

    def report_ru(self) -> str:
        if self.refusal:
            return "🔴 ОТКАЗ ИСПОЛНЕНИЯ: %s" % self.refusal[:400]
        head = "источник %d операций, исполнено %d" % (self.source_ops,
                                                       self.executed_ops)
        if self.ok:
            return head + "\nКРУГОВОЙ ПРОГОН СОШЁЛСЯ: мультимножества равны, " \
                          "расхождений 0"
        lines = [head, "🔴 РАСХОЖДЕНИЕ: потеряно %d, лишних %d"
                 % (sum(c for _k, c in self.lost),
                    sum(c for _k, c in self.extra))]
        for key, count in self.lost[:6]:
            lines.append("   ПОТЕРЯНО ×%d  %s" % (count, key[:150]))
        for key, count in self.extra[:6]:
            lines.append("   ЛИШНЕЕ   ×%d  %s" % (count, key[:150]))
        by_op = collections.Counter(k.split("|")[0] for k, _c in self.lost)
        by_op.update(collections.Counter(k.split("|")[0]
                                         for k, _c in self.extra))
        lines.append("   по операциям: %s" % dict(by_op.most_common(8)))
        return "\n".join(lines)


def compare_ops(source: Iterable[Mapping[str, Any]],
                got: Iterable[Mapping[str, Any]],
                kinds: Mapping[tuple[str, str], str] | None = None) -> RoundTrip:
    """A MULTISET comparison: field order and whitespace mean nothing, a
    lost wall means everything."""

    kinds = param_kinds() if kinds is None else kinds
    src = list(source)
    out = list(got)
    a = collections.Counter(canonical_op(o, kinds) for o in src)
    b = collections.Counter(canonical_op(o, kinds) for o in out)
    lost, extra = a - b, b - a
    return RoundTrip(ok=not lost and not extra,
                     source_ops=len(src), executed_ops=len(out),
                     lost=tuple(sorted(lost.items())),
                     extra=tuple(sorted(extra.items())))


def round_trip(rendering: SourceRendering,
               source_ops: Iterable[Mapping[str, Any]]) -> RoundTrip:
    """Print -> EXECUTE -> compare against the source.

    🔴 WITHOUT THIS, THE PRINTER IS PROSE. Printing that nobody executed
    proves exactly that some text came out; it proves nothing at all about
    matching the source.
    """

    got: list[Mapping[str, Any]] = []
    for part in rendering.parts:
        one = execute_source(part.text)
        if isinstance(one, str):
            return RoundTrip(ok=False, source_ops=0, executed_ops=0,
                             refusal="программа %d: %s" % (part.index + 1, one))
        got.extend(one.get("ops") or ())
    return compare_ops(source_ops, got)


# ---------------------------------------------------------------------------
# A SAMPLE FROM THE CORPUS — a decompile on disk becomes source with one call
# ---------------------------------------------------------------------------

#: The ceiling of a sample's text, in bytes. Not a round number: measured
#: 17.08.2026 on the tower's most populated floor (`k2_ar_rd_v8`/L23, 1029
#: leaves) gave **186 237 B**, and the owner named the norm as "116K tokens
#: per production building". The ceiling stands twice as high as the
#: measured floor, so as to cut only pathology — and every cut IS NAMED,
#: because a silently shortened sample teaches the wrong lesson.
EXAMPLE_TEXT_CAP = 400_000


def floors_of_tree(tree: Any) -> list[tuple[str, Mapping[str, Any]]]:
    """The tree's floors — ASKED FROM THE FOLD, not derived from a
    parameter.

    🔴 MEASURED 17.08.2026, AND IT CANCELED THE PREVIOUS EDITION ENTIRELY. A
    floor used to be derived from an operation's `params.level` — and then
    "outside the floors" turned out to be **93 250 operations out of
    115 880**, because `create_door` HAS NO level parameter BY DESIGN (a
    door inherits its host's level). The instrument showed a hole that does
    not exist. The fold has already sorted these nodes out: `macro.type ==
    "floor"` carries `level_name`, and after that, what is left outside the
    floors is **24** — grids and a solo staircase, that is, things
    belonging to the BUILDING, not to a floor.
    """

    out: list[tuple[str, Mapping[str, Any]]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, Mapping):
            return
        macro = node.get("macro")
        if isinstance(macro, Mapping) and macro.get("type") == "floor":
            out.append((str(macro.get("level_name") or ""), node))
        for child in (node.get("children") or ()):
            walk(child)

    walk(tree)
    return out


def floor_source(run_dir: str, *, level: str = "",
                 cap_bytes: int = EXAMPLE_TEXT_CAP) -> dict[str, Any]:
    """A decompile on disk -> ONE floor as `program_py` source. Never
    raises.

    WHY THIS FUNCTION IS SEPARATE FROM `render_source`. Printing takes
    programs; to get them, one must read the tree, pick a floor, ask the
    fold for its leaves, and run them through the materializer. Four steps,
    and each is already written — what was missing was exactly the door
    behind which they stand together. Without it, every caller would
    reassemble the chain from scratch and diverge at the third step, the way
    the bench diverged (see `floor_leaves`).

    THE COST IS MEASURED (17.08.2026, `k2_ar_rd_v8`, a 59-floor tower)::

        reading tree.json (216 MB)                1.74 s
        leaves of ALL 59 floors                   0.07 s
        materializing the most populated floor    0.84 s
        printing                                  0.08 s
        ─────────────────────────────────────────────────
        total                                     ~2.7 s · 186 237 B · 8 programs

    For comparison, a neighboring door of the same corpus: `building_index
    .index_from_query` on the same tower costs **11.7 s** and returns a
    CENSUS, not elements. So a sample as source is four times cheaper than
    the index and carries incomparably more — because it is exactly the
    language the model is written in.

    THE FLOOR'S CHOICE IS DISPLAYED, NOT MADE SILENTLY. If `level` is
    empty, the MOST POPULATED one is taken, and the answer states both the
    rule and the losers. `ground.py`'s law, verbatim: "a choice the caller
    cannot see is a `.FirstOrDefault()`
    with a good reputation".

    THREE OUTCOMES, AND NOT ONE IS EMPTY: a source file · `refused` with a
    named reason · `partial` (not everything printed, and it says exactly
    how much).
    """

    # 🔴 `json` IS NOT IMPORTED HERE — THE MODULE ALREADY HAS IT (line 124).
    # A local `import json` was SHADOWING the module-level one, and the
    # authority-boundaries guard (`test_authority_boundaries.py`) turned red
    # over it the same day. The form looks harmless and is dangerous in
    # substance: the function gets its OWN `json`, and any substitution of
    # the module-level one (in a test, in a measurement) does not reach it
    # — meaning the body stops being observable by exactly the instruments
    # that observe the rest of the module.
    import os

    def refuse(why: str) -> dict[str, Any]:
        return {"refused": why, "run": os.path.basename(run_dir.rstrip("/"))}

    # 🔴 `tree.json` GETS COMPRESSED (21.08.2026, `SNAPSHOT_FILES`). A bare
    # `os.path.exists` on a cooled-down decompile would print "this decompile
    # has no tree.json — nothing to print", that is, a fact about OUR OWN
    # cleanup job dressed as a fact about the decompile.
    from kir.decompile.snapshot_io import (
        open_snapshot, snapshot_file_exists)
    path = os.path.join(run_dir, "tree.json")
    if not snapshot_file_exists(path):
        return refuse("у разбора «%s» нет `tree.json` — печатать нечего. Это "
                      "факт о НАШЕМ разборе, а не о здании"
                      % os.path.basename(run_dir.rstrip("/")))
    try:
        with open_snapshot(path, "rt", encoding="utf-8") as handle:
            tree = json.load(handle)
    except Exception as exc:  # noqa: BLE001 — a broken tree is DATA
        return refuse("дерево разбора не прочиталось (%s: %s)"
                      % (type(exc).__name__, str(exc)[:160]))

    floors = floors_of_tree(tree)
    if not floors:
        return refuse("в разборе нет ни одного узла-этажа (`macro.type == "
                      "\"floor\"`) — свёртка их не выделила")

    scored = sorted(((len(floor_leaves(node)), name, node)
                     for name, node in floors),
                    key=lambda row: (-row[0], row[1]))
    chosen = None
    rule = ""
    if level:
        for count, name, node in scored:
            if name == level:
                chosen, rule = (count, name, node), "назван вызывающим"
                break
        if chosen is None:
            return refuse("этажа «%s» в разборе нет. Есть: %s"
                          % (level, ", ".join(name for _c, name, _n
                                              in scored[:20])))
    else:
        chosen, rule = scored[0], "самый полный этаж разбора"

    count, name, node = chosen
    try:
        from kir.decompile.materialize import leaves_to_program
        result = leaves_to_program(floor_leaves(node))
    except Exception as exc:  # noqa: BLE001
        return refuse("материализатор не собрал программы этажа «%s» (%s: %s)"
                      % (name, type(exc).__name__, str(exc)[:160]))

    # THE DOCUMENT NAME IS TAKEN FROM THE CARD, NOT FROM `passport.json`,
    # AND THIS IS NOT A MATTER OF TASTE. Neighbors paid the full price for
    # the second door and recorded it (`clash/existing.py:320-331`):
    # `passport.json` carries the whole tree, up to 206 MB, and parsing
    # every passport cost 17.2 s PER CALL for the sake of ONE string field.
    # A card is 544 B … 2.2 KB, and the name sits on its first line. The
    # first edition of this function read the first 4 KB of `passport.json`
    # and silently returned an empty name: the header does not fit there.
    document = ""
    try:
        with open(os.path.join(run_dir, "passport.md"), encoding="utf-8") as fh:
            head = fh.readline().strip()
        marker = "KIR Passport"
        if marker in head:
            document = head.split("—", 1)[-1].strip() if "—" in head else ""
    except Exception:  # noqa: BLE001 — a document name is decoration, not the subject
        document = ""

    run_name = os.path.basename(run_dir.rstrip("/"))
    rendering = render_source(result.programs, level=name, run=run_name,
                              document=document)
    if rendering.empty:
        return refuse("этаж «%s» держит %d листьев, но материализатор не выдал "
                      "ни одной программы — все листья ушли в `skipped`. "
                      "Печатать нечего, и это НЕ пустой этаж"
                      % (name, count))

    text = "\n\n".join(rendering.texts)
    raw = text.encode("utf-8")
    truncated = 0
    if len(raw) > cap_bytes:
        truncated = len(raw) - cap_bytes
        text = raw[:cap_bytes].decode("utf-8", "ignore")

    out: dict[str, Any] = {
        "run": run_name,
        "document": document,
        "level": name,
        "rule": rule,
        "runners_up": [{"level": n, "leaves": c}
                       for c, n, _node in scored[1:4] if n != name],
        "levels_total": len(scored),
        "leaves": count,
        "ops_printed": rendering.ops_printed,
        "ops_total": rendering.ops_total,
        "programs": len(rendering.parts),
        "bytes": len(raw),
        "complete": bool(rendering.ok) and not truncated,
        "report_ru": rendering.report_ru(),
        "source": text,
    }
    if truncated:
        out["truncated_bytes"] = truncated
        out["truncation_ru"] = (
            "образец срезан на %d Б из %d: потолок текста %d Б. Срезанный "
            "хвост НЕ напечатан, и достраивать по нему нельзя"
            % (truncated, len(raw), cap_bytes))
    return out
