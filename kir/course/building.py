"""THE BUILDING'S NUMBERS — taken from real projects, not recalled from
norms.

WHY THIS MODULE CAME TO BE (16.08.2026, the night rig). The owner: "the
agent builds primitive buildings." The measurement found the cause
somewhere nobody was looking: the KIR course — 21,922 characters, eight
topics — teaches the LANGUAGE and teaches almost nothing about the
BUILDING. Checked by word count across the whole course text:
`create_wall` 9 occurrences, `level` 33, `ref` 12; and yet **«шаг
колонн» 0, «пролёт» 0, «высота этажа» 0, «несущ» 0, «перегородк» 0,
«ядро» 0, «толщина стены» 0, «фундамент» 0, «планировк» 0.**

We taught the model to SPEAK and never told it WHAT to say.

WHY THE NUMBERS ARE TAKEN, NOT WRITTEN FROM MEMORY. "Residential floor
height 2.8–3.0 m" can be typed from memory in a second, and it is a
number with no provenance — exactly what this tree forbids. Parses of
REAL projects sit on disk, and their heights, thicknesses, bay spacing,
and areas can be computed from them. What gets computed diverges from
memory in two cases out of four, and both divergences are substantive —
see the lesson.

THE CORPUS BOUNDARIES, NAMED HONESTLY. The unit of count is the
BUILDING, not the parse: 13 buildings by document name, drawn from 80
parses sitting on disk (17.08.2026; the live number is printed by the
lesson itself, here it stands only as an order of magnitude). The gap is
almost sixfold and invisible in a number with no baseline.
Predominantly residential and office projects from Russia (K2, СОБ6.2,
ЛЕН, Сколково) plus three American demo models from Snowdon. Room
purpose is not stored in the header, so "residential vs. office" cannot
be separated by this instrument; column spacing is not counted (columns
are elements, not grid lines).
"""
from __future__ import annotations

import json
import math
import os
from kir import env  # noqa: E402  (a submodule with no dependencies — introduces no cycle)
import statistics
from typing import Any, Callable, NamedTuple

#: The corpus is machine-local: its absence is not a defect, it is a
#: property of the machine.
#:
#: 🔴 THE PATH IS DERIVED FROM THE INSTALL, NOT HARD-CODED. The first
#: version carried the literal `/opt/…` — and the boundary guard
#: (`test_no_absolute_deployment_path_is_executable`) turned red on that
#: very run, rightly so: KIR ships as a separate open-source package, and
#: an absolute install path in executable code makes it fit exactly one
#: box. Measured 02.08, the reason this guard exists: a process started
#: from a working copy leaked telemetry into the PROD corpus.
#:
#: 🔴 THE AUTHORITY IS THE PARSE PRODUCER, NOT `install_paths`. The
#: second version asked `install_data_path("decompile")` — and that is a
#: DIFFERENT path: it gives `<install>/backend/data/decompile`, while
#: the parses sit at `<install>/backend/backend/data/decompile`. The
#: duplication is not a typo: the dump is written by
#: `serving._DECOMPILE_OUT_ROOT` — as a RELATIVE path from the service's
#: working directory (`backend/`). Verified by running it 16.08: the
#: derived path does not exist, the real one carries 80 parses.
#:
#: So here it is the same key and the same default as the producer's —
#: otherwise this would be a second opinion about where the corpus
#: lives, and it would drift from the first, silently. Plus one named
#: override for the night rig, which measures the corpus of SOMEONE
#: ELSE's install, with its own working directory.
DECOMPILE_ROOT = (env.get("KIR_DECOMPILE_ROOT")
                  or env.get("KIR_DECOMPILE_DATA",
                                    "backend/data/decompile"))

#: The ceiling on reading an L0 body for one parse. Thicknesses live in
#: the BODY, and a tower's body is hundreds of thousands of lines; the
#: limit is named here so the recount is reproducible, rather than being
#: "however much got done."
BODY_RECORD_CAP = 120_000


def _resolved_root() -> str:
    """THE SAME path, but from the install root, when the working
    directory is not ours.

    🔴 WHY, AND WHY THIS IS NOT A SECOND OPINION ABOUT WHERE THE CORPUS
    LIVES. The path stays ONE AND THE SAME — `backend/data/decompile` of
    the parse producer (see the block at `DECOMPILE_ROOT`). Only the
    ANCHOR changes: the working directory or the install root.

    The anchor became necessary on 22.08.2026, by measurement. The
    sandbox starts the child with `cwd=jail` (`sandbox`:
    `subprocess.Popen(..., cwd=jail)`), meaning its working directory is
    EMPTY even before the chroot. A relative path never resolves there,
    and two lessons in the course — "house" and "apartment", the only
    ones with the building's numbers taken from data — refused the
    author with «корпуса нет на этой машине». The corpus existed; there
    was no anchor.

    Order is preserved: if the relative path resolves from the working
    directory, that one is used, and the service behaves exactly as it
    did.

    🔴 THE ANCHOR USED TO BE `parents[3]` FROM THIS FILE, AND AFTER THE
    SPLIT IT POINTED INTO `/opt`. The refusal stayed the same
    («корпуса нет на этой машине»), because a nonexistent anchor was
    silently dropped — that is, the 22.08 fix had stopped working and
    said nothing about it. Counting steps upward is only correct for one
    exact layout; the install root is known to `install_paths`, and it
    is the one that names the REASON for its own silence
    (`install_root_refusal`).
    """
    if os.path.isdir(DECOMPILE_ROOT):
        return DECOMPILE_ROOT
    if os.path.isabs(DECOMPILE_ROOT):
        return DECOMPILE_ROOT
    from kir.install_paths import install_root
    root = install_root()
    if root is None:
        return DECOMPILE_ROOT
    anchored = root / DECOMPILE_ROOT
    return str(anchored) if anchored.is_dir() else DECOMPILE_ROOT


def _head(run: str) -> dict | None:
    path = os.path.join(_resolved_root(), run, "L0.jsonl")
    try:
        # A transparent read: a snapshot may be compressed (`snapshot_io`).
        from kir.decompile.snapshot_io import open_snapshot
        with open_snapshot(path, "rt", encoding="utf-8") as fh:
            return (json.loads(fh.readline()) or {}).get("document") or {}
    except Exception:  # noqa: BLE001
        return None


def _runs() -> list[str]:
    try:
        return sorted(os.listdir(_resolved_root()))
    except Exception:  # noqa: BLE001
        return []


def available() -> bool:
    """Whether even ONE readable parse exists — not whether even one name
    sits in the directory.

    🔴 IT USED TO BE `bool(_runs())`, THAT IS, `bool(os.listdir(...))`
    (F-204, 29.08.2026). A README, a service file, or an empty
    subdirectory made the lesson "available", and it printed its usual
    form over ZERO buildings; the honest refusal branch right next to it
    («УРОК «ДОМ» НЕДОСТУПЕН») simply never fired. Two values of the same
    module contradicted each other in one and the same output:
    `available(): True | buildings(): []`.

    🔴 THE COST IS NOT THAT ZEROS READ AS NUMBERS — the lesson names its
    own emptiness out loud («Нули ниже означают «не мерили», а не
    «ноль»»), and that has been verified by running it. The cost is in
    the one line the banner does NOT cover: «ЧИСЛА СНЯТЫ С НАСТОЯЩИХ
    ПРОЕКТОВ, НЕ ВСПОМНЕНЫ: по 0 ЗДАНИЯМ» — a claim about PROVENANCE,
    self-contradictory and unqualified by anything. Instead of ONE line
    of refusal with the next turn, the reader got a whole page that was
    correct in everything except one sentence, and spent a turn figuring
    that out.

    Enumerating the kinds of junk is pointless — the list is unbounded.
    Instead we ask the one function that alone decides what a building
    is: `buildings()` reads every parse's header and filters out junk by
    construction. No extra reading results from this: `lesson()` calls
    `buildings()` on the very next line, and the result is cached for the
    process (`_BUILDINGS_CACHE`).
    """
    return bool(buildings())


#: MEMORY FOR ONE PROCESS. Five of the lesson's measurements — heights,
#: areas, spacing, thicknesses, purposes — walk the same list of
#: buildings, and each one used to re-read the headers: measured 22.08 —
#: 1.9–2.1 s per measurement, 10.1 s for the whole lesson, against the
#: sandbox's wall-clock limit of 8 s. That is, the lesson could not reach
#: the author by TIME, even when it reached him by paths.
#:
#: 🔴 THE KEY IS THE DIRECTORY'S CONTENTS, NOT "ONCE AND FOR ALL". The
#: service runs for weeks, and the corpus grows: every new parse is
#: dropped in alongside the others. Memory with no key would have gone
#: stale FOREVER and SILENTLY — the lesson would keep naming twelve
#: buildings after the thirteenth arrived. The key is cheap
#: (`os.listdir`, milliseconds against two seconds of reading headers),
#: and it also honestly invalidates the cache when a parse is deleted.
_BUILDINGS_CACHE: tuple[tuple[str, ...], list] | None = None


def buildings() -> list[tuple[str, dict]]:
    """ONE PARSE PER BUILDING — the unit of count for this whole file.

    🔴 WHY THIS IS A SEPARATE FUNCTION, AND NOT REPEATED IN EVERY
    MEASUREMENT. Before 17.08.2026 the filtering by document name lived
    INSIDE `room_kinds`, while three neighboring measurements walked
    every parse in a row. That is two counting rules in one file, which
    were supposed to agree and did not: a tower parsed fifteen times
    weighed in as fifteen buildings, and "median room area" was
    answering a question about OUR OWN history of parses, not about
    design practice.

    Parses on disk: 71; buildings by name: 13 — a gap of almost
    sixfold, entirely invisible in a number with no baseline.

    The FIRST parse of a building is taken, in sorted order: the rule is
    arbitrary, but it is ONE rule and it is named. "The most complete"
    would sound better and would drag in a new measure of completeness
    this module does not have.

    🔴 ONE BUILDING IS STILL COUNTED TWICE, AND THAT IS NAMED, NOT FIXED
    (21.08.2026). `13A-RD-AR-K2_v33` and `13A-RD-AR-K2_v33_kuklev.d.s`
    are one house: Revit had detached it from the central model and
    appended it to a username. MEASURED: both have 112 categories and
    310,558 elements, and the censuses differ by SIX lines, all six
    about VIEW FURNITURE (`OST_Cameras` 33 vs. 34, `OST_SectionBox` 33
    vs. 34, `OST_IOSSketchGrid` 654 vs. 655): someone had one extra 3D
    view open.

    WHY IT IS NOT FIXED. Filtering by a NAME SUFFIX would bake a
    username into the course's code. Filtering by census EQUALITY does
    not work — they are not equal. Filtering by "a census matching to
    within N percent" would introduce a threshold nobody has ever
    measured, right next to numbers that are all measured. Of three bad
    options, a fourth was chosen: say out loud that twelve buildings are
    eleven houses and one pair of twins, and live with a known skew of
    one part in twelve instead of an unknown one.
    """
    global _BUILDINGS_CACHE
    runs = tuple(_runs())
    if _BUILDINGS_CACHE is not None and _BUILDINGS_CACHE[0] == runs:
        return list(_BUILDINGS_CACHE[1])
    out: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for run in runs:
        doc = _head(run)
        if not doc:
            continue
        key = str(doc.get("doc_name") or run)
        if key in seen or not counts_as_a_building(key):
            continue
        seen.add(key)
        out.append((key, doc))
    _BUILDINGS_CACHE = (runs, out)
    return list(out)


#: Names that DO NOT COUNT as a building. Rules, not a list: the next
#: draft and the next copy will fall under them on their own.
#:
#: 🔴 FOUND 21.08.2026 BY THE RATCHET "THE LESSON'S NUMBERS MUST
#: REPRODUCE." It turned red at "13 -> 15 buildings", and the obvious
#: temptation was to update the numbers. But the increase turned out NOT
#: to be buildings:
#:
#:     Проект1, Проект1_копия      OUR OWN DRAFT, where this session builds trials
#:     13A-RD-AR-K2_v33 and ..._kuklev.d.s     one building under two names
#:     SKLNK_... and копияSKLNK_...            the same
#:
#: The "house" lesson is the only one that teaches not the language but
#: DESIGN PRACTICE, and every one of its numbers is taken from real
#: projects. Feeding it the room areas of our own draft would mean
#: training the model on itself — exactly the substitution the docstring
#: of `buildings()` warns about: "the median was answering a question
#: about OUR OWN history of parses, not about practice."
# 🔴 «демо» WAS ADDED 22.08.2026, AND THIS IS NOT NITPICKING THE LIST. A
# document with this name — 90,758 elements, the FOURTH largest "house"
# in the corpus — was built BY US on the rig. The rule was filtering out
# "Проект1" and its copies while letting this one through, meaning the
# "house" lesson's numbers were partly drawn from our own work: the
# textbook was being confirmed by what had already been written from it.
# Found while remeasuring groups across the whole corpus
# (`tools/discipline_practice.py`), where this same document turned up
# voting for "best practice."
_NOT_A_BUILDING_PREFIX = ("Проект", "копия", "Копия", "Untitled", "Project",
                          "демо", "Демо", "demo", "Demo", "night_b")
_NOT_A_BUILDING_SUFFIX = ("_копия", "_копия2", " - копия")


def counts_as_a_building(doc_name: str) -> bool:
    """Whether this is a real project, and not our own draft or someone
    else's copy.

    A RULE, NOT AN ENUMERATION: names are drawn from the Revit document's
    name, and «Проект1»/«копия…» are what Revit and Explorer call things
    by default. A list of names would go stale at the very first new
    draft.

    THE BOUNDARY IS NAMED HONESTLY: the rule looks at the NAME, not the
    contents. A real project named «Проект1» will not get through — and
    that is the right trade: losing one building out of fifteen is
    cheaper than teaching the model practice on our own draft.
    """
    name = (doc_name or "").strip()
    if not name:
        return False
    if any(name.startswith(p) for p in _NOT_A_BUILDING_PREFIX):
        return False
    return not any(name.endswith(sfx) for sfx in _NOT_A_BUILDING_SUFFIX)


def storey_heights() -> list[float]:
    """Floor heights = the differences between neighboring levels'
    elevations, ONE PER BUILDING.

    Bounds of 1500…8000 mm cut out what is not a floor: a single level
    can carry duplicate elevations (a grid one and a structural one), and
    a difference of 0 mm is not a floor.
    """
    out: list[float] = []
    for _key, doc in buildings():
        els = sorted(float(l.get("elevation_mm") or 0.0)
                     for l in doc.get("levels") or ())
        out += [b - a for a, b in zip(els, els[1:]) if 1500.0 <= b - a <= 8000.0]
    return out


def room_areas() -> list[float]:
    out: list[float] = []
    for _key, doc in buildings():
        out += [float(r.get("area_m2") or 0.0) for r in doc.get("rooms") or ()
                if 1.0 <= float(r.get("area_m2") or 0.0) <= 400.0]
    return out


#: The width of the direction bundle, in degrees. The number used to
#: stand as a LITERAL on the same line as a bucket count derived from
#: it, and the derived value was simply forgotten (F-207, 29.08.2026).
_BEAM_STEP_DEG = 5.0
#: Buckets per half-circle. DERIVED, not assigned: writing `36` as a
#: literal would leave the relationship unnamed, and it would drift the
#: moment someone changes the bundle width to 2.5.
_BEAM_COUNT = int(180.0 / _BEAM_STEP_DEG)

#: Bounds on a plausible grid spacing, mm. Pulled out of the body along
#: with it — so a synthetic-data check and a corpus measurement share ONE
#: threshold.
_GRID_SPACING_MIN_MM = 1000.0
_GRID_SPACING_MAX_MM = 20000.0


def grid_spacings_of(grids: Any) -> list[float]:
    """The spacing between neighboring PARALLEL grid lines of one
    building — PURE FROM ITS INPUT.

    🔴 SPLIT OFF FROM THE CORPUS ON PURPOSE (F-206/F-207, 29.08.2026).
    Previously the whole body lived inside `grid_spacings()`, which walks
    into `buildings()`, and there was nothing to check it with on a
    machine with no corpus: all six tests in
    `test_building_numbers_are_current.py` SKIP on a machine with no
    parses. That is, the `grid_mm` number the MODEL reads was guarded by
    nothing here at all. Splitting "take the grid lines" from "compute
    the spacing" is part of the fix, not incidental work: without it
    neither finding below would have had a runnable discriminator.

    Grid lines are sorted into bundles by direction (precision
    `_BEAM_STEP_DEG`); within a bundle the signed distance to the line is
    taken, and the differences between neighbors are computed.
    """
    beams: dict[int, list[float]] = {}
    for g in grids or ():
        p0, p1 = g.get("p0_mm"), g.get("p1_mm")
        if not (isinstance(p0, list) and isinstance(p1, list)):
            continue
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        n = math.hypot(dx, dy)
        if n < 1.0:
            continue
        # 🔴 THE SIGN OF THE DIRECTION IS CANONICALIZED, OTHERWISE THE
        # OFFSET DEPENDS ON THE ORDER OF THE ENDPOINTS (F-206). A bundle
        # merges a direction with its reverse (`% 180`), while the offset
        # was computed from the RAW (dx, dy) and flipped sign on a
        # reversal — even though it is the SAME physical line. Two grid
        # lines at y=3000 and y=6000, the second one recorded right to
        # left, gave a spacing of 9000 instead of 3000 — THREE TIMES OVER.
        # The order of the endpoints is set by the Revit parse file, not
        # by the author and not by us. `abs()` on the offset does not fit
        # here: it would destroy the SIDE, and two grid lines on opposite
        # sides of the origin would merge into one. A sign is needed —
        # it just has to be a property of the LINE, not of the record.
        # The rule `dx < 0 or (dx == 0 and dy < 0)` is a lexicographic
        # choice of a representative from the pair (d, -d): complete
        # (covers the vertical case) and unambiguous, with no thresholds
        # and no list of special cases.
        if dx < 0 or (dx == 0 and dy < 0):
            dx, dy = -dx, -dy
        # 🔴 THE CIRCULAR BOUNDARY IS CLOSED (F-207). `% 180.0` declares
        # 180° and 0° to be one direction, while `int(round(.../5))`
        # gives 0..36 — that is, buckets 36 and 0 are ONE direction under
        # TWO keys. Grid lines at +0.1° and −0.1° landed in different
        # bundles, and the spacing between them was NOT COMPUTED AT ALL:
        # an empty list went out, indistinguishable from "there are no
        # distances between them". A slightly rotated grid is a common
        # case: a document's true north almost never lines up with the
        # project's grid. Shifting the angle by half a step does not fit
        # here — it just moves the boundary to where it will cut someone
        # else; closing it removes the boundary as such, and the buckets
        # become the ring that a direction actually is.
        key = int(round((math.degrees(math.atan2(dy, dx)) % 180.0)
                        / _BEAM_STEP_DEG)) % _BEAM_COUNT
        beams.setdefault(key, []).append((p0[0] * dy - p0[1] * dx) / n)
    out: list[float] = []
    for vals in beams.values():
        vals.sort()
        out += [abs(b - a) for a, b in zip(vals, vals[1:])
                if _GRID_SPACING_MIN_MM <= abs(b - a) <= _GRID_SPACING_MAX_MM]
    return out


def grid_spacings() -> list[float]:
    """Grid spacing across the corpus. ONE parse per building — see
    `buildings()`."""
    out: list[float] = []
    for _key, doc in buildings():
        out += grid_spacings_of(doc.get("grids"))
    return out


#: The parses from which wall thickness is taken. Named individually,
#: because the body is read with a ceiling: "the whole corpus" would be a
#: promise this instrument does not keep.
WIDTH_RUNS = ("k2_ar_rd_v15", "sob62_fas_r23_v19", "len_ar_me_r24_v1")


def wall_widths() -> list[float]:
    out: list[float] = []
    for run in WIDTH_RUNS:
        path = os.path.join(_resolved_root(), run, "L0.jsonl")
        from kir.decompile.snapshot_io import snapshot_file_exists
        if not snapshot_file_exists(path):
            continue
        from kir.decompile.snapshot_io import open_snapshot
        with open_snapshot(path, "rt", encoding="utf-8") as fh:
            fh.readline()
            for i, line in enumerate(fh):
                if i > BODY_RECORD_CAP:
                    break
                # 🔴 SUBSTRING FILTERING BEFORE PARSING, MEASURED
                # 25.08.2026. JSON was being parsed for EVERY line: 179,153
                # calls to json.loads at 4.81 s, that is 72% of the whole
                # "house" lesson's time. Walls among them: 27,361 — 15.3%.
                # The lesson assembled in 6.66 s against the sandbox's
                # 5 s CPU-time ceiling, and failed with `KIR-B002` two
                # times out of six: the same call gave a different
                # answer.
                #
                # The filter is SAFE by construction, and that must be
                # said: in the JSON, the value `"OST_Walls"` cannot be
                # absent from the line if the field equals it. The filter
                # cannot skip a real wall; it will let through an extra
                # line (where the name occurred in another field), and
                # the check below will filter that one out — the same
                # check that already stood here before. That is, the set
                # of results does not change, only the cost does.
                if '"OST_Walls"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if rec.get("record") != "element":
                    continue
                el = rec.get("element") or {}
                if el.get("category") != "OST_Walls":
                    continue
                v = (el.get("params") or {}).get("WALL_ATTR_WIDTH_PARAM")
                if isinstance(v, (int, float)) and 20.0 <= v <= 1500.0:
                    out.append(float(v))
    return out


#: How many room names to print in the lesson. Not "all 192": the tail is
#: one-off names of a single project, and they teach not the vocabulary
#: but that project.
ROOM_NAMES_SHOWN = 16


def room_kinds() -> dict[str, list[float]]:
    """Room name -> areas, ONE parse per building.

    The name is normalized: trailing numbers and "№" are stripped
    ("Жилая комната 3" and "Жилая комната" are the same designation,
    split apart by numbering). Case is folded to lowercase for the same
    reason.

    ONE PARSE PER BUILDING — otherwise a tower parsed fifteen times would
    outweigh the other twelve buildings, and this would be a measurement
    of OUR OWN history of parses, not of design practice. The rule is now
    asked of `buildings()` rather than repeated here: before 17.08.2026
    it lived ONLY in this function, and three neighboring measurements
    counted differently, saying nothing about it.
    """
    import re
    out: dict[str, list[float]] = {}
    for _key, doc in buildings():
        for r in doc.get("rooms") or ():
            name = (r.get("name") or "").strip()
            area = float(r.get("area_m2") or 0.0)
            if not name or not (1.0 <= area <= 400.0):
                continue
            base = re.sub(r"[\s\d\.\-_№]+$", "", name).strip().lower()
            if base:
                out.setdefault(base, []).append(area)
    return out


def _median(fn: Callable[[], list[float]]) -> float:
    vals = fn()
    return statistics.median(vals) if vals else 0.0


class Recorded(NamedTuple):
    """A MEASUREMENT TOGETHER WITH ITS OWN BASE, because a number with no
    base answers the wrong question.

    🔴 WHY THE `n` AND `buildings` FIELDS WERE ADDED (17.08.2026). Before
    that day the base lived as PROSE inside `what` — "38,392 values" —
    and no ratchet mutates prose: the value was checked against disk,
    while its base could drift from the corpus forever and silently.
    This is canon form 9 in its pure state.

    And the base here is not decoration, it is a KIND OF QUANTITY.
    "5.59 m² over 38,392 values" and "5.88 m² over 11,484 rooms of
    thirteen buildings" are different statements: the first is weighted
    by our own history of parses (a tower parsed fifteen times), the
    second by design practice. What was being fixed was not the digit,
    it was its foundation.
    """

    value: float
    unit: str
    what: str
    n: int
    buildings: int
    recompute: Callable[[], list[float]]


#: THE RECORDED MEASUREMENTS ARE FROM 17.08.2026, ONE PARSE PER
#: BUILDING. They are recomputed by the functions above; the test
#: `test_building_numbers_are_current` turns red if either the value or
#: its base has drifted from disk — a stale measurement in the course is
#: indistinguishable from a fabrication.
# 🔴 RETAKEN 21.08.2026, AND THE REASON IS NOT "THE CORPUS GREW". The
# ratchet turned red at "13 -> 15 buildings", and the obvious move would
# have been to update the numbers. The increase turned out NOT to be
# buildings:
#
#     Проект1 · Проект1_копия          OUR OWN DRAFT, where trial builds go
#     копияSKLNK_…                     a copy of someone else's project
#
# The "house" lesson teaches DESIGN PRACTICE, and feeding it the room
# areas of our own draft would mean training the model on itself — the
# very same substitution the docstring of `buildings()` warns about. The
# rule `counts_as_a_building` was introduced, and after filtering, the
# number of buildings became TWELVE, not fifteen and not thirteen: that
# is, the 17.08 record already included the draft.
#
# THE NUMBERS AFTER FILTERING (median, same recount):
#     storey_mm  3300.0 -> 3300.0   base 360 -> 330
#     room_m2     5.880 -> 5.760    base 11,484 -> 11,957
#     grid_mm    3300.0 -> 3400.0   base 296 -> 277
#
# 🔴 The room_m2 base GREW while the number of buildings dropped — and
# that is not a typo: MNVNK was added (33,944 elements), while the draft
# and its copies, which have few rooms, dropped out. The number of
# buildings and the number of values move DIFFERENTLY, and that is
# exactly why the base is kept as a separate field.
# 🔴 RETAKEN 22.08.2026 AFTER FILTERING OUT OUR OWN «демо», and the cost
# of the filtering is named as a number: the room-area base fell from
# 11,957 to 7,140 values. That is, FOUR TENTHS of this measurement had
# been drawn from a document we built ourselves. The grid spacing shifted
# 3400 -> 3500 mm, floor height held (3300 mm, base 330 -> 291).
# Buildings 13 -> 12.
# 🔴 RETAKEN 23.08.2026: THE CORPUS GAINED A BUILDING, THE NUMBERS HELD.
# A neighboring wave dropped the full parse `mnvnk_k3_23aug` (210 MB, all
# indexes) into the corpus, and buildings went from 12 to 13. The ratchet
# turned red — as it should: the recorded base had drifted from disk.
#
# WHAT THE RECOUNT SHOWED, and this is the main point. A whole real
# building was added to the corpus — and it did NOT MOVE floor height
# (3300), grid spacing (3500), or wall thickness (80). One thing did
# move: room area, 5.685 → 5.534, that is, by 0.15 m² on a base that grew
# from 7,140 to 8,926 values. Three numbers out of four holding steady
# under an INDEPENDENT building is evidence that these are properties of
# typical Russian housing, not artifacts of the sample.
#
# Two other recent runs do NOT belong in the corpus and must not:
# `mnvnk_k1_layers` and `k3_layers` carry only L0 and a type profile —
# these are partial layer captures, with no tree and no indexes;
# `buildings()` does not take them.
# 🔴 29–30.08.2026: `grid_mm` IS KNOWN TO BE STALE, AND THERE IS NOTHING
# HERE TO RECOMPUTE IT WITH. The `F-206` fix (canonicalizing the
# direction's sign) and `F-207` (closing the buckets at the 0°/180°
# boundary) change THE MEASUREMENT ITSELF that 3500.0 mm and a base of
# 302 pairs were derived from: the first removes pairs counted three
# times over because of endpoint order, the second ADDS pairs that used
# to fall through at the boundary. The direction of the shift is not
# known in advance — the base moves both ways at once.
#
# On the machine where the fix was made the corpus does not resolve
# (`buildings()` gives ZERO buildings, `DECOMPILE_ROOT =
# "backend/data/decompile"` is a relative path), so the number is NOT
# TOUCHED: substituting a guess here would mean introducing exactly the
# defect both findings were written against. Recompute on a box with the
# corpus in ONE pass after BOTH fixes, not after each one.
#
# This staleness will not stay silent: `test_building_numbers_are_current`
# (`test_each_recorded_number_reproduces_from_the_corpus` and
# `..._carries_a_base_that_also_reproduces`) checks the RECORD against
# the RECOUNT and turns red wherever the corpus exists. Here these six
# tests SKIP, and that is the second half of both findings: the number
# the MODEL reads was guarded by nothing on a machine with no corpus.
# Closed by synthetic checks of the law —
# `test_grid_spacing_measures_the_building_not_the_file.py`, which turn
# red on ANY machine.
RECORDED: dict[str, Recorded] = {
    "storey_mm": Recorded(
        3300.0, "мм", "высота этажа: разность отметок соседних уровней",
        314, 13, storey_heights),
    "room_m2": Recorded(
        5.534, "м²", "площадь помещения", 8_926, 13, room_areas),
    "grid_mm": Recorded(
        3500.0, "мм", "шаг соседних параллельных осей", 302, 13,
        grid_spacings),
    # Thickness has ITS OWN, smaller base: a parse's body is read with a
    # ceiling, so three named buildings were taken, not the corpus. Its
    # own base number stands right here.
    "wall_mm": Recorded(
        80.0, "мм", "толщина стены", 24_032, len(WIDTH_RUNS), wall_widths),
}


def sample_too_small_reason(vals: list[float], what: str) -> str | None:
    """`None`, if the sample is enough for quartiles; otherwise the
    REASON, in words.

    🔴 `_q`'S COMPANION. That one hands back `(0, 0, 0)` on a sample
    smaller than four, and that answer cannot be dropped: the lesson must
    assemble even on an incomplete machine. But the zeros print in the
    VERY SAME UNITS as real quartiles — "wall thickness 0 mm" is
    indistinguishable from "we did not measure thicknesses".

    The cost is the same as for a recorded zero in the course: the MODEL
    reads the numbers and takes them for measurements of real buildings.
    It will repeat a zero floor height.

    Two outcomes are distinguished: no sample at all (the source was
    never read) and a sample that exists but is shorter than four
    (quartiles cannot be computed).
    """
    if len(vals) >= 4:
        return None
    if not vals:
        return (f"{what}: НИ ОДНОГО замера — источник не читался. Нули ниже "
                f"означают «не мерили», а не «ноль»")
    return (f"{what}: замеров {len(vals)}, для четвертей нужно ≥4 — числа "
            f"ниже НЕ КВАРТИЛИ, а заполнитель")


def missing_width_runs() -> tuple[str, ...]:
    """Runs from `WIDTH_RUNS` that are absent on this machine.

    🔴 `wall_widths`'S COMPANION. That one skips a missing run with a
    silent `continue` — and rightly so, a measurement must assemble from
    what exists. But the sample shrinks silently, and "thicknesses taken
    from three buildings" becomes indistinguishable from "taken from
    one".
    """
    from kir.decompile.snapshot_io import snapshot_file_exists

    return tuple(
        run for run in WIDTH_RUNS
        if not snapshot_file_exists(
            os.path.join(_resolved_root(), run, "L0.jsonl")))


def _q(vals: list[float]) -> tuple[float, float, float]:
    """Median and quartiles — or zeros, if there is no corpus on this
    machine.

    `sample_too_small_reason()` names the reason for the zeros — the
    answer here cannot be dropped, so what gets asked is the REASON
    itself."""
    if len(vals) < 4:
        return (0.0, 0.0, 0.0)
    q = statistics.quantiles(vals, n=4)
    return (q[0], statistics.median(vals), q[2])


def _width_law(text: str) -> str:
    """Prose width is the COURSE's own law, and a refusal obeys it just
    like the regular text.

    🔴 BOUGHT BY THE SUITE ON 17.08.2026: both lessons in this file were
    failing `test_every_lesson_fits_the_sandbox_stdout` with a line of
    179 and 176 characters against an 88-character ceiling — and both
    times it was the REFUSAL BRANCH, the only thing assembled by
    concatenation instead of a ready-made paragraph. A familiar shape: a
    refusal is always written differently, and that is exactly why it
    falls outside the discipline the main text observes.

    The law is asked of the author (`lessons._reflow`), not rewritten
    here: two places that are supposed to agree are our own naming
    defect. The import is local because `lessons` pulls this module back
    in (via a lazy `__import__`), and a top-level pair would have closed
    the cycle.
    """
    from kir.course.lessons import _reflow

    return _reflow(text)


#: THE LESSON'S FINISHED TEXT, TAKEN BEFORE SANDBOX ISOLATION.
#:
#: 🔴 WHY. Measured 22.08.2026 through the REAL sandbox: of the course's
#: sixteen topics, two — "house" and "apartment" — could not be read
#: from a script AT ALL, and those are exactly the two that carry the
#: building's measured numbers. First with a `KIR-B004` refusal (the
#: module not warmed up), and after warming it up, with the honest
#: «корпуса нет на этой машине»: the corpus is addressed by a RELATIVE
#: path, while the sandbox's child sits in an empty root. That is, the
#: module written on 16.08 in response to the "the agent builds
#: primitive buildings" measurement had never once been readable by the
#: author since that day.
#:
#: WHY A TEXT CACHE, AND NOT A PATH. An absolute path in executable code
#: is forbidden by the boundary guard (KIR ships as a separate package),
#: and threading the corpus into the jail means opening someone else's
#: files to the script. The lesson's text is 3,268 characters, taken ONCE
#: before isolation, and after that it depends on the filesystem not at
#: all.
#:
#: THE COST IS NAMED: `lesson()` reads the corpus in 10.1 s, `lesson_flat()`
#: in 1.9 s. So the warm-up runs NOT on every mention of `course`, but
#: only when the source has been PARSED as calling exactly these topics —
#: see `language._course_topics`.
_PRIMED: dict[str, str] = {}

#: TOPICS WHOSE TEXT IS TAKEN BEFORE ISOLATION. ONE CARRIER for the whole
#: tree: before 29.08.2026 two places knew them — the `prime()` loop
#: below and `language._WARM_LESSONS` — and the second one also knew the
#: call's GRAMMAR, which it had no business knowing (F-359).
PRIMABLE_TOPICS: tuple[str, ...] = ("дом", "квартира")


def prime() -> tuple[str, ...]:
    """Take the lesson texts BEFORE isolation. Calls
    `language.warm_for_source`.

    Stays silent on any failure: an unwarmed lesson will say so about
    itself, and an exception from here would bring down the whole turn
    together with the program already assembled.
    """
    by_topic = {"дом": lesson, "квартира": lesson_flat}
    for key in PRIMABLE_TOPICS:
        fn = by_topic[key]
        if key in _PRIMED:
            continue
        try:
            text = fn()
        except Exception:  # noqa: BLE001 — the warm-up must not drop the turn
            continue
        if text and "НЕДОСТУПЕН" not in text:
            _PRIMED[key] = text
    return tuple(sorted(_PRIMED))


def lesson() -> str:
    """THE "HOUSE" LESSON — what a real building is made of, in measured
    numbers."""
    if not available() and "дом" in _PRIMED:
        # Taken before isolation, by the same code and from the same
        # disk — this is a MEASUREMENT, not prose from memory, and that
        # is why it is allowed to travel into the jail.
        return _PRIMED["дом"]
    if not available():
        # A NAMED refusal, not silent text with no numbers: a lesson with
        # no corpus is prose recollections, and those were exactly what
        # was missing here.
        return _width_law(
            "УРОК «ДОМ» НЕДОСТУПЕН: корпуса разборов нет на этой машине "
            f"({DECOMPILE_ROOT}). Числа этого урока СНЯТЫ с настоящих "
            "проектов и без них урок стал бы пересказом норм по памяти.")
    runs, houses = len(_runs()), len(buildings())
    h1, h2, h3 = _q(storey_heights())
    a1, a2, a3 = _q(room_areas())
    g1, g2, g3 = _q(grid_spacings())
    widths = wall_widths()
    w1, w2, w3 = _q(widths)
    # 🔴 INCOMPLETENESS IS NAMED BEFORE THE NUMBERS. The lesson prints
    # quartiles in the same units and the same shape regardless of how
    # many buildings produced them.
    _gaps = [r for r in (
        sample_too_small_reason(storey_heights(), "высота этажа"),
        sample_too_small_reason(room_areas(), "площадь помещения"),
        sample_too_small_reason(grid_spacings(), "шаг осей"),
        sample_too_small_reason(widths, "толщина стены"),
    ) if r]
    _absent = missing_width_runs()
    if _absent:
        _gaps.append("толщины: нет разборов " + ", ".join(_absent)
                     + " — выборка снята с того, что осталось")
    _warn = ("🔴 ЧИСЛА НИЖЕ НЕПОЛНЫ:\n" + "\n".join("   · " + g for g in _gaps)
             + "\n\n") if _gaps else ""
    return _warn + f"""
УРОК «ДОМ» — из чего состоит здание, которое проектировщик считает настоящим.

ЭТОТ УРОК НЕ ПРО ЯЗЫК. Остальные семь тем учат, КАК сказать; этот — ЧТО
говорят. Он появился потому, что замер курса дал «create_wall» девять раз и
«высота этажа» ноль, а владелец увидел следствие раньше: агент строит
примитивно.

ЧИСЛА СНЯТЫ С НАСТОЯЩИХ ПРОЕКТОВ, НЕ ВСПОМНЕНЫ: по {houses} ЗДАНИЯМ, по одному
разбору на здание из {runs} на диске (РФ жильё и офисы плюс демо Snowdon). База
важна: иначе башня, разобранная пятнадцать раз, весила бы пятнадцать зданий, и
это был бы замер нашей истории разборов. «Четверть — медиана — четверть»:

  высота этажа     {h1:>7.0f} — {h2:>7.0f} — {h3:>7.0f} мм
  шаг осей         {g1:>7.0f} — {g2:>7.0f} — {g3:>7.0f} мм
  толщина стены    {w1:>7.0f} — {w2:>7.0f} — {w3:>7.0f} мм
  площадь помещения{a1:>7.1f} — {a2:>7.1f} — {a3:>7.1f} м²

ТРИ ИЗ ЧЕТЫРЁХ ЧИСЕЛ ПРОТИВОРЕЧАТ ЗДРАВОМУ СМЫСЛУ, И ИМЕННО ПОЭТОМУ ОНИ ЗДЕСЬ.

1. ТИПИЧНАЯ СТЕНА — ПЕРЕГОРОДКА {w2:.0f} мм, А НЕ КИРПИЧ 380. Частоты по
   24 032 стенам: 80 мм — 5 911, 200 мм — 4 474, 30 мм — 3 723, 20 мм — 2 807,
   далее 50, 250, 150, 100, 190, 300. Двадцать и тридцать миллиметров — это
   ОТДЕЛОЧНЫЕ слои («Черновая отделка 20 мм_Квартиры»), тоже стены. Значит:
   строя жильё, ставь перегородки 80–100, несущие 200, наружные 200–300, и не
   делай всё здание из одного толстого типа — так выглядит макет, а не проект.

2. ШАГ ОСЕЙ {g2:.0f} мм, А НЕ 6000. Сетка настоящего проекта плотнее учебной:
   между несущими осями стоят промежуточные — по перегородкам, витражам,
   лифтам. Четверти {g1:.0f} и {g3:.0f} показывают обе природы сразу. Значит:
   сетка 6000×6000 на всё здание — признак каркаса из учебника; настоящая
   сетка неравномерна.

3. МЕДИАННОЕ ПОМЕЩЕНИЕ — {a2:.1f} м², А НЕ КОМНАТА. В российском проекте
   помещением считают КАЖДУЮ кладовую, санузел, шахту и тамбур; комнаты — это
   верхняя четверть ({a3:.1f} м² и выше). Значит: этаж из четырёх больших
   комнат — не квартира, а схема. Настоящая квартира это прихожая, кухня,
   комната(ы), санузел и кладовая, и половина из них меньше десяти метров.

4. ВЫСОТА ЭТАЖА {h2:.0f} мм ДЕРЖИТСЯ ПЛОТНО. Четверти {h1:.0f} и {h3:.0f} —
   разброс в шестьдесят миллиметров на тринадцати зданиях. Это самое
   устойчивое число проекта: бери 3000–3300, если задание не говорит иного, и
   не выдумывай 2500 или 4500.

ПОРЯДОК АВТОРСТВА, КОТОРЫЙ ПОВТОРЯЕТ ПОРЯДОК СТРОЙКИ. Он не украшение: каждый
следующий слой ССЫЛАЕТСЯ на предыдущий, и перестановка порождает висячие
ссылки, которые компилятор отвергнет.

  1. уровни          отметки этажей — на них встанет всё остальное
  2. оси             сетка, по которой ставят несущее
  3. несущее         колонны и/или несущие стены по осям
  4. перекрытия      плиты этажей по контуру несущего
  5. оболочка        наружные стены, витражи, кровля
  6. перегородки     деление этажа на помещения
  7. проёмы          двери и окна В УЖЕ ПОСТАВЛЕННЫХ стенах
  8. помещения       объявить, когда контур замкнут
  9. инженерия       трассы под потолком, когда есть где вести

ЧЕГО ЭТОТ УРОК НЕ ЗНАЕТ, И ЭТО НАЗВАНО. Назначение помещений в шапке разбора
не хранится — «жилое против офиса» этим прибором не разделяется. Шаг КОЛОНН не
считался (колонны — элементы, а не оси), пролёты перекрытий тоже. Корпус
смещён в сторону жилья и офисов РФ; промышленных зданий в нём нет.
""".strip()


def lesson_flat() -> str:
    """THE "APARTMENT" LESSON — what is inside a home and what size, by
    measurement."""
    if not available() and "квартира" in _PRIMED:
        return _PRIMED["квартира"]
    if not available():
        return _width_law(
            "УРОК «КВАРТИРА» НЕДОСТУПЕН: корпуса разборов нет на этой "
            f"машине ({DECOMPILE_ROOT}). Числа урока сняты с настоящих "
            "проектов, и без корпуса он стал бы пересказом по памяти.")
    kinds = room_kinds()
    rows = sorted(kinds.items(), key=lambda kv: -len(kv[1]))[:ROOM_NAMES_SHOWN]
    total = sum(len(v) for v in kinds.values())
    body = []
    for name, vals in rows:
        q1, med, q3 = _q(vals)
        body.append("  %-22s %5d шт   %5.1f м²   четверти %4.1f – %4.1f"
                    % (name[:22], len(vals), med, q1, q3))
    return f"""
УРОК «КВАРТИРА» — из чего состоит жильё и какого размера бывает каждая часть.

ЗАМЕР, А НЕ ПАМЯТЬ: {total} помещений с именами, по ОДНОМУ разбору на здание
(иначе башня, разобранная пятнадцать раз, перевесила бы двенадцать остальных).
Различных имён в корпусе {len(kinds)}; печатаются {ROOM_NAMES_SHOWN} самых
частых — хвост состоит из имён одного проекта и учит его частностям.

{chr(10).join(body)}

ЧТО ИЗ ЭТОГО СЛЕДУЕТ ДЛЯ ЗАМЫСЛА.

САМОЕ ЧАСТОЕ ПОМЕЩЕНИЕ ЖИЛОГО ДОМА — САНУЗЕЛ, И ОН МАЛЕНЬКИЙ. «с/у» встречается
чаще жилых комнат, а его медиана — около четырёх метров. Квартира, нарисованная
из одних больших комнат, не похожа на жильё ни по числу помещений, ни по их
размеру.

КОМНАТЫ РАЗНЫЕ, И РАЗНИЦА УСТОЙЧИВА. Жилая комната около 13 м², спальня около
14, мастер-спальня около 18, гостиная около 17 с широким разбросом. Это не
синонимы: гостиная и мастер-спальня крупнее рядовой комнаты примерно в полтора
раза, и планировка, где все комнаты равны, читается как схема.

КУХНЯ ОКОЛО ШЕСТИ МЕТРОВ, А НЕ ДВЕНАДЦАТИ. И рядом с ней живёт «кухня-ниша» —
отдельное назначение, а не описка: в современных планировках это самостоятельный
тип помещения.

ПОЛОВИНА СОСТАВА — ВСПОМОГАТЕЛЬНОЕ. Прихожая, коридор, холл, гардеробная,
гардероб, кладовая, тамбур: каждое от двух до семи метров. Именно они делают
план планом, и именно их пропускает всякая «схема из четырёх комнат».

БАЛКОН И ЛОДЖИЯ — ПОМЕЩЕНИЯ. Они объявлены наравне с комнатами и попадают в
перепись; забыв их, теряешь заметную часть площади этажа.

ЧЕГО ЭТОТ УРОК НЕ ЗНАЕТ. Он не отличает квартиру от секции: связь «помещение ->
квартира» в шапке разбора не хранится, поэтому числа здесь — про ЧАСТИ, а не
про их наборы. Корпус жилой и офисный, РФ; промышленных и общественных зданий
в нём нет.
""".strip()
