"""Frozen Wave-0 schema for the streamed DECOMPILE L0 representation.

Every coordinate is millimetres and every Revit identifier is serialized as a
string.  The dataclasses are immutable so later stages cannot accidentally
rewrite extraction truth in place.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from kir import env  # noqa: E402  (a dependency-free submodule — introduces no cycle)
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .identity import (
    AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES,
    DOCUMENT_IDENTITY_SOURCES,
    L0_IDENTITY_METADATA_SCHEMA,
    IdentityGap,
    IdentityStatus,
)


# ── CONSTANTS — KIR_DECOMPILE_SPEC Part 11 ──────────────────────────────────

CANON_MM = 1.0
DZ_TOL = 50.0
SIM_THRESHOLD = 0.90
GRID_COVERAGE = 0.8
GRID_REL_TOL = 0.02
MIN_ROW = 3
MIN_ARRAY = 4
COLLINEAR_TOL = 5.0
VERIFY_TOL = 10.0
# Extraction page size. A page executes as ONE call on Revit's UI thread and
# is required to fit inside EXTRACT_TIMEOUT_MS with margin: a call the
# server cancels is FINISHED by Revit anyway, the retry lands in a busy
# window, the bridge's ping starves, and the socket dies with 1006. Measured
# 29.07 (13A-RD-AR-K2, RD, 15 341 walls): pages of 2000 killed the bridge on
# the 6th page of walls (v2) and on the first page of doors (v1) — the point
# of death drifts, which is exactly what gives away cumulative starvation,
# not a "poisonous" page. Overriding it — ONLY through the environment, the
# discriminant is structural (size), not model-specific.
_EXTRACT_BATCH_DEFAULT = 2_000
EXTRACT_BATCH = max(50, int(
    env.get("KIR_EXTRACT_BATCH", _EXTRACT_BATCH_DEFAULT)))
ATOM_CELL_MM = 5_000.0
ATOM_CLUSTER_MIN = 5
ATOM_LEAF_CAP = 20
ZONE_CELL_MM = 8_000.0
PASSPORT_INJECT_TOKENS = 800
USE_LLM_LABELS = False
GEOM_DETAIL = "Fine"
GEOM_CANON_MM = 0.5
# A CEILING ON SHAPE WEIGHT DURING CAPTURE — the only defense a live Revit
# has against hanging.
#
# WHAT IT FIXES. `Face.Triangulate` cannot be interrupted, and the time
# budgets (`element_budget_ms`/`call_budget_ms`) honestly admit this: they
# are checked BEFORE and AFTER a stage, not inside it. So one heavy shape
# carries capture past any budget and drags Revit's UI thread down with it.
# Measured 14.08.2026: a pilaster with 236 thousand triangles hung the
# Revit 2023 process TO DEATH — the socket stayed connected, while any exec
# at all, including `return doc.Title;`, got no response from the plugin
# for over half an hour; killing the server process does not help, the work
# runs on the UI thread. On 15.08 a full decompile run of 13B-RD-AR-K4 died
# at the geometry stage, and the heaviest shapes in that model were 39 724
# and 22 908 triangles.
#
# WHY THE CHECK IS DONE ALONG THE WAY, NOT AHEAD OF TIME. Predicting a
# shape's weight cheaply is not possible: measured across 351 shapes from
# two buildings — heavy ones (>16 384 triangles) have 120..262 faces, light
# ones up to 418, any threshold on face count either lets heavy ones
# through or cuts normal ones. Lowering the tessellation level does not
# help either: for that same pilaster, Triangulate(0.0) gives 81 548
# against 235 998 at 1.0 — this is an imported mesh, not a smooth surface.
# So the count has to be tracked CUMULATIVELY during the walk and stopped
# once the sum crosses the line.
#
# WHY EXACTLY 16 384. The distribution is bimodal, and the ceiling is set
# in the EMPTY VALLEY between the modes, where moving it changes almost
# nothing. Measured across 550 shapes with solids (13A-RD-AR-K2 +
# 13B-RD-AR-K4, 39 547 instances):
#   ≤4096          475 shapes / 38 971 inst  ← the main mode
#   4097..8191       6 shapes /    341 inst
#   8192..16383      1 shape  /      2 inst  ← the valley: only 10 shapes
#   16384..32767     3 shapes /     27 inst     across the whole
#                                              4097..32767 band
#   32768+          65 shapes /    206 inst  ← the tail mode (imported meshes)
# The cost of 16 384: 68 shapes out of 550 are lost (12.4%), and 233
# instances out of 39 547 (0.6%). Moving it to 8192 would cost 69 shapes /
# 235 inst, to 32768 — 65 / 206: the difference is a handful of shapes, so
# the choice within the valley decides nothing, and the ceiling can be set
# by a DIFFERENT consideration — bounding the work. That is what settles
# it here: no more than 16 384 triangles get tessellated before a refusal,
# which is 14 times below the measured hang and four times above the
# authoring op's format limit (`ir/mesh.py`, MAX_TRIANGLES=4096) — a bigger
# shape would not be accepted by `create_directshape` anyway. The number
# matches the ceiling of the measurement instrument
# (`/home/claude/geom/prod_capture.py`), so that the project has ONE "safe
# size", not two different ones.
#
# THE HONEST COST, STATED OUT LOUD: the decompile bundle has no size limit
# of its own (`GmMesh` in `decompile/recompile.py` has none), so the shapes
# cut off are NOT "what wouldn't have been saved anyway." This is a real
# loss of geometry for 68 shapes, and it is justified only by the fact that
# the alternative is losing the entire run, together with the live Revit.
GEOM_WEIGHT_CEILING = 16_384
GEOM_TOL = 1.0
GEOM_VOLUME_REL_TOL = 0.001

EXTRACT_TIMEOUT_MS = 30_000
EXTRACT_RETRIES = 2
# WAITING FOR THE WINDOW TO COME BACK (task #26). The page retry budget
# (EXTRACT_RETRY_BACKOFF_S) tolerates ~25 s — enough for network jitter,
# but not for a real disconnect: the window comes back with a new ws_id
# after SECONDS TO MINUTES. When retries are exhausted, the extraction loop
# waits for the window and repeats the page.
#
# THE BUDGET IS SHARED ACROSS THE WHOLE RUN, NOT PER PAGE — and that is the
# main decision here. A per-page ceiling would multiply by the number of
# pages: if the window is closed for good (the operator left Revit), 54
# categories at 5 minutes each would give four and a half hours of
# pretend work. The shared budget is spent once: we survive one long
# outage OR several short ones, and a dead window costs exactly five
# minutes once, after which the rest of the run refuses fast and honestly.
#
# WHY 300 s. The cost of the error is asymmetric: waiting five minutes is
# cheap, while failing to wait means throwing away the extraction of an
# entire model (measured 29.07, K2 RD: three runs died on a flaky page,
# each one had to be restarted completely). Reconnection is made up of a
# network reconnect, a client reconnect, and Revit's UI thread, which is
# still finishing the canceled call — three minutes is tight for that sum.
EXTRACT_WINDOW_WAIT_S = max(0.0, float(
    env.get("KIR_EXTRACT_WINDOW_WAIT_S", 300.0)))
# The pause between attempts to reach the window that came back. The probe
# IS the page call itself: success IS the proof that the window is back. A
# separate "liveness ping" would be a second path with its own failure
# mode, and could lie "the window is there" in a case where the page still
# doesn't go through.
EXTRACT_WINDOW_POLL_S = 10.0
L0_SCHEMA_VERSION = "1.0"
L0_UNITS = "mm"

# Transform evidence is versioned independently from the frozen L0 record
# dialect.  Adding this optional side axis therefore keeps historical L0 1.0
# streams readable without pretending that those streams measured a frame.
FEDERATION_TRANSFORM_SCHEMA = "kir-l0-federation-transform/1"
FEDERATION_TRANSFORM_CONVENTION = (
    "row_major_source_to_target_affine_mm")
FEDERATION_TRANSFORM_ORTHONORMAL_TOL = 1e-8


class L0SchemaError(ValueError):
    """A persisted or bridge-supplied L0 record violates the frozen schema."""


# ── L0 DIALECT: GENERATION OF THE READ TABLE ────────────────────────────────
#
# WHAT GOES INTO THE DIALECT VERSION — AND WHY EXACTLY THIS.
#
# The dialect version names EXACTLY ONE THING: the generation of the
# ordered category table that extraction is required to walk
# (``EXTRACT_CATEGORIES``). Nothing more. The justification is not
# aesthetic but structural: this is the one part of L0 whose meaning is
# POSITIONAL AND TOTAL. The container declares "one ``category_status`` per
# table row, strictly in its order, with the footer last and only after
# ALL rows." So growing the table changes the very definition of a
# complete stream — and completeness is exactly what the reader needs the
# version for.
#
# WHAT DOES NOT GO INTO THE VERSION, though it might seem to belong:
#
# * THE SET OF RECORD FIELDS. The house already has a working rule: a
#   field is appended AT THE TAIL with a default value, and its absence
#   means "not measured," not "zero." That is how ``curve_kind``,
#   ``section_receipts``, ``census``, ``worksharing``/``worksets`` were
#   added — and this is exactly why the stream from 18.07 still parses
#   record by record today. The rule is local to a record and does NOT
#   touch the stream's completeness, so it needs no version. The same
#   docstring appears on :class:`LocationCurveKind` and on
#   ``CategoryStatus.section_receipts``.
# * GEOMETRY INVARIANTS. On 29.07 (cb9c3b65) the requirement "a point is
#   required to carry a turn" was lifted — this is a RELAXATION, and a
#   relaxation cannot devalue old bytes: everything that parsed yesterday
#   still parses today. Only a TIGHTENING can devalue them, and it is
#   required to refuse by name inside :class:`L0SchemaError`, naming the
#   field, rather than hiding behind a version number. A version that
#   every such change moves is exactly as useless as a missing one.
#
# CHECKED BY FREQUENCY (measured 29.07, eleven days of history). Under
# this rule the version would have moved SIX times — exactly on the six
# table growths — and would NOT have moved even once on five changes that
# do not concern it (curve_kind, section receipts, the §18.1 census,
# §18.4 worksets, the turn relaxation). That is exactly the ratio being
# sought.
#
# WHY THIS IS NOT ``L0_SCHEMA_VERSION``. That one names the RECORD schema
# and honestly stands at "1.0": no record shape has ever changed
# incompatibly. Moving it for the sake of the table growing would mean
# declaring broken something that never broke, while also refusing to
# read all 55 accumulated snapshots. These are two DIFFERENT axes, and
# each has its own version.
#
# THE APPEND-AT-THE-TAIL LAW. All six generations are strict prefixes of
# one another; cross-checked against three independent sources (extract.py's
# git history; the bytes of 55 snapshots in ``backend/data/decompile``;
# sha256 fingerprints of both). As long as the law holds, a generation is
# unambiguously determined by ONE number — the table's length. The
# fingerprint below is not decoration but a guard: it is taken from
# HISTORY, not computed from today's table, so ``verify_dialect_ladder``
# will scream if someone inserts a row in the middle or renames one.
# Without the fingerprint, "length = generation" would become exactly that
# same silent reinterpretation: row N in an old stream would end up
# meaning a different category.


@dataclass(frozen=True, slots=True)
class L0Dialect:
    """One generation of the read table.

    ``category_count`` is the table's length at this generation;
    ``fingerprint`` is sha256 (16 hex) over its names joined by ``\\n``.
    Version names were assigned RETROSPECTIVELY on 29.07: not a single byte
    captured before that day carries a dialect version, and the reader
    derives the generation from the stream itself. This is honest
    precisely because the derivation rests on the proven append-at-the-tail
    law, not on a guess.
    """

    version: str
    category_count: int
    fingerprint: str
    note: str = ""

    def __post_init__(self) -> None:
        # The checks are spelled out inline, rather than through
        # ``_nonempty_string``: the ladder is built at module import time,
        # HIGHER up in the file than the shared helpers — the version is
        # required to stand next to ``L0_SCHEMA_VERSION``, not move further
        # down for the sake of reusing three lines.
        for name in ("version", "fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise L0SchemaError(f"L0Dialect.{name} must be a non-empty string")
        if (isinstance(self.category_count, bool)
                or not isinstance(self.category_count, int)
                or self.category_count <= 0):
            raise L0SchemaError("L0Dialect.category_count must be positive")


def dialect_fingerprint(categories: Sequence[str]) -> str:
    """Fingerprint of the ordered category table.

    By NAMES and ORDER, not by length: length would not tell a permutation
    apart from the original table, and it is exactly a permutation that
    breaks resume addressing.
    """
    joined = "\n".join(categories)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


#: The ladder of generations, oldest to newest. Fingerprints were taken
#: from HISTORY (extract.py's git revisions) and independently confirmed
#: by the corpus's bytes: 22 — 22 snapshots, 47 — 9, 48 — 12, 51 — 1,
#: 54 — 10; zero discrepancies.
SUPPORTED_L0_DIALECTS: tuple[L0Dialect, ...] = (
    L0Dialect("kir-decompile-l0-dialect/1", 22, "0d20aa3e8b5ce49b",
              "18.07 (52ccee78) — первая закрытая таблица: АР + каркас."),
    L0Dialect("kir-decompile-l0-dialect/2", 47, "b256896173524f19",
              "27.07 (0a16e8f5) — разделы ЭОМ/ОВ/ВК/КР, +25 строк."),
    L0Dialect("kir-decompile-l0-dialect/3", 48, "292a11cb208e17b5",
              "28.07 (d1e77855) — витражная система, +1."),
    L0Dialect("kir-decompile-l0-dialect/4", 51, "f7b63ba25d895240",
              "29.07 (cfb820d6) — витражные сетки и линии сетки, +3."),
    L0Dialect("kir-decompile-l0-dialect/5", 54, "999cf7b6c990a8fe",
              "29.07 (8de6d1c5) — изоляция/оболочки воздуховодов, +3."),
    L0Dialect("kir-decompile-l0-dialect/6", 73, "40f56665718cc014",
              "29.07 (ee32fb82) — рабочая документация: размеры, марки, "
              "линии, узлы, +19."),
    # 03.08 — OPENINGS AS SEPARATE ELEMENTS. The rung was set up TOGETHER
    # WITH the table's growth, not after: this file's law is exactly that a
    # generation is determined by ONE number — the table's length — and a
    # table grown without a rung refuses to be read by its own reader. The
    # fingerprint was taken by the instrument
    # (`dialect_fingerprint(EXTRACT_CATEGORIES)`), not copied by hand.
    L0Dialect("kir-decompile-l0-dialect/7", 77, "22709313f3e53d9a",
              "03.08 (wave/opening) — проёмы отдельными элементами: "
              "SWallRect/Floor/Roof/Shaft, +4."),
    # 22.08 — WINDOW MARKS. The rung was set up TOGETHER WITH the row in
    # `extract._CATEGORY_SPECS`, not after: a table grown without a rung
    # refuses to be read by its own reader (`resolve_dialect` does not know
    # the number 78). The fingerprint was taken by the instrument
    # `dialect_fingerprint(EXTRACT_CATEGORIES)`, not copied by hand; the
    # prefix of 77 names still gives the previous `22709313f3e53d9a`, so the
    # append-at-the-tail law is not violated.
    L0Dialect("kir-decompile-l0-dialect/8", 78, "227bcd35c548b0cb",
              "22.08 (срок годности довода) — OST_WindowTags: 3 545 марок "
              "окон в 4 документах корпуса, +1."),
    # 22.08 — REFERENCE PLANES. The rung was set up TOGETHER WITH the row in
    # `extract._CATEGORY_SPECS`, in the SAME turn, not after: a table grown
    # without a rung refuses to be read by its own reader (`resolve_dialect`
    # does not know the number 79), and a window of such breakage in the
    # shared tree stops every fork at once. The fingerprint was taken by the
    # instrument `dialect_fingerprint(EXTRACT_CATEGORIES)` on the table
    # AFTER the edit, not copied off someone else's screen; the prefix of
    # 78 names still gives `227bcd35c548b0cb`, so the append-at-the-tail law
    # holds.
    L0Dialect("kir-decompile-l0-dialect/9", 79, "4a4dce617a5432dc",
              "22.08 (первая из двух дыр MNVNK) — OST_CLines: 9 724 опорные "
              "плоскости в 10 зданиях из 10, +1."),
    # 04.09 — SILENCE BECOMES A REFUSAL. The rung was set up IN THE SAME
    # turn as the rows in `extract._CATEGORY_SPECS`, not after: a table
    # grown without a rung refuses to be read by its own reader. The
    # fingerprint was taken by the instrument
    # `dialect_fingerprint(EXTRACT_CATEGORIES)` on the table AFTER the
    # edit; the prefix of 79 names still gives `4a4dce617a5432dc`, so the
    # append-at-the-tail law holds and is verified, not merely claimed.
    #
    # All thirteen categories HAD an operation in the registry and HAD NO
    # row: the element gave neither an atom nor a refusal, and the building
    # got reassembled silently, without toposolids, fills, loads, and
    # fascias. `OST_Toposolid` is not among that count: the oracle gives
    # 4/6 (2023+), and the collector would not have compiled with it on two
    # of the six versions.
    L0Dialect("kir-decompile-l0-dialect/10", 92, "3bb94e8ddb0b5c40",
              "04.09 (молчание становится отказом) — нагрузки, армирование "
              "по площади, рельеф, площадка, заливки, маскировка, карнизы, "
              "ниши, край плиты, площадки лестниц, пути эвакуации, +13."),
)

#: The version that NEW streams are written with.
L0_DIALECT_VERSION = SUPPORTED_L0_DIALECTS[-1].version
SUPPORTED_L0_DIALECT_VERSIONS = tuple(
    dialect.version for dialect in SUPPORTED_L0_DIALECTS)
_DIALECT_BY_VERSION = {
    dialect.version: dialect for dialect in SUPPORTED_L0_DIALECTS}
_DIALECT_BY_COUNT = {
    dialect.category_count: dialect for dialect in SUPPORTED_L0_DIALECTS}


def dialect_by_version(version: str) -> L0Dialect:
    """A rung by version name. An unrecognized name is a refusal, not the
    nearest lookalike."""
    dialect = _DIALECT_BY_VERSION.get(version)
    if dialect is None:
        raise L0SchemaError(
            f"неизвестная версия диалекта L0 {version!r}; поддерживаются "
            f"{', '.join(SUPPORTED_L0_DIALECT_VERSIONS)}")
    return dialect


def verify_dialect_ladder(table: Sequence[str]) -> None:
    """Check the ladder against the live table. A mismatch is a loud
    refusal.

    Three assertions, each guarding its own way of lying quietly:

    1. the current table is REQUIRED to be the last rung — otherwise the
       next wave will grow it, forget the rung, and a fresh snapshot will
       refuse to be read by its own reader;
    2. each rung's fingerprint is required to match the fingerprint of
       today's table's prefix — this is exactly what forbids inserting a
       row in the middle or renaming one;
    3. the rungs go in strictly increasing length.
    """
    table = tuple(table)
    counts = [dialect.category_count for dialect in SUPPORTED_L0_DIALECTS]
    if counts != sorted(set(counts)):
        raise L0SchemaError(
            "ступени диалекта L0 обязаны идти строго по возрастанию длины")
    newest = SUPPORTED_L0_DIALECTS[-1]
    if len(table) != newest.category_count:
        raise L0SchemaError(
            f"таблица чтения содержит {len(table)} категорий, а последняя "
            f"ступень диалекта {newest.version} объявляет "
            f"{newest.category_count}: диалект изменился — заведите ступень "
            f"(отпечаток текущей таблицы {dialect_fingerprint(table)})")
    for dialect in SUPPORTED_L0_DIALECTS:
        prefix = table[:dialect.category_count]
        actual = dialect_fingerprint(prefix)
        if actual != dialect.fingerprint:
            raise L0SchemaError(
                f"{dialect.version} больше не является префиксом таблицы "
                f"чтения (ожидался отпечаток {dialect.fingerprint}, получен "
                f"{actual}): строку вставили в середину или переименовали, а "
                f"это сдвигает смысл уже снятых потоков и формат "
                f"возобновления")


def resolve_dialect(category_count: int, table: Sequence[str]) -> L0Dialect:
    """Name a stream's generation from its category count.

    A number that appeared in NO build at all is not a generation, and the
    guess "probably a prefix" is forbidden here: it is unknown what that
    build considered completeness, so its stream cannot be called
    complete.
    """
    verify_dialect_ladder(table)
    dialect = _DIALECT_BY_COUNT.get(category_count)
    if dialect is None:
        known = ", ".join(
            f"{d.category_count}={d.version}" for d in SUPPORTED_L0_DIALECTS)
        raise L0SchemaError(
            f"поток объявляет {category_count} категорий — такого поколения "
            f"диалекта L0 не существовало; известные: {known}")
    return dialect


def categories_outside_dialect(
    dialect: L0Dialect,
    table: Sequence[str],
) -> tuple[str, ...]:
    """Categories that did not yet exist in THAT generation's table.

    This is exactly what tells a named incompleteness apart from a silent
    zero: for these categories, an old snapshot doesn't have "zero
    elements" — it has "was not asked."
    """
    return tuple(table[dialect.category_count:])


class GeometryKind(str, Enum):
    CURVE = "curve"
    POINT = "point"
    BBOX_ONLY = "bbox_only"


class LocationCurveKind(str, Enum):
    """The kind of an element's curve, captured IN THE CAPTURE ITSELF
    (a §18.1 consequence).

    ``geom_kind == "curve"`` says only that the element has a
    ``LocationCurve`` — before this wave, an arc, a spline and a straight
    line were indistinguishable in L0, and the lift silently straightened
    an arc into a chord (audit finding M2, 2026-07-28). Three values close
    the question exactly as far as it can be answered in one word:

    * ``line`` — ``Autodesk.Revit.DB.Line``;
    * ``arc`` — ``Arc`` (exact geometry is in the side ``curve.index.json``);
    * ``other`` — NurbSpline / HermiteSpline / CylindricalHelix / etc.

    ``None`` (the field is absent from the row) is a SEPARATE state: "not
    measured." That is what all L0 frozen before this wave looks like, and
    treating it as ``line`` would be the same guess as the chord.
    """

    LINE = "line"
    ARC = "arc"
    OTHER = "other"


class HostSource(str, Enum):
    """WHAT an element turned out to be, once it was found to have a host
    (capture wave 09.08).

    Before this wave, ``host_id`` was filled by a SINGLE method — casting
    ``__element as FamilyInstance``. A system element does not fit that
    cast, so for a strip footing, a railing, an opening and insulation the
    field was ALWAYS empty, and ``L0Element`` carries no field at all with
    the element's CLASS: a strip footing and an isolated footing share one
    ``category`` (``OST_StructuralFoundation``), and the only way to tell
    them apart was ``type_name`` — matching on a bare name, which the canon
    forbids.

    The value names the READING BRANCH that answered, and that is exactly a
    fact about the class: ``as WallFoundation`` could not give a nonzero
    result on anything else. The same technique as
    ``default_panel_source`` for curtain walls: read several sources and
    record WHICH ONE answered, so that one value doesn't end up meaning
    three different truths.

    ``None`` (the field is absent from the row) is a SEPARATE state: "not
    measured." That is what all frozen L0 looks like. Treating it as
    ``family_instance`` is not allowed, even though for old rows that would
    happen to be correct: an empty field and an unmeasured field are
    different facts, and it is exactly on conflating them that this house
    has already been burned (§18.2, the silence of the side stage).
    """

    FAMILY_INSTANCE = "family_instance"
    WALL_FOUNDATION = "wall_foundation"
    RAILING = "railing"
    OPENING = "opening"
    INSULATION_LINING = "insulation_lining"


class LineOwner(str, Enum):
    """WHAT THE LINE BELONGS TO: the view or the sketch plane (13.08).

    ``OST_Lines`` holds two different kinds within ONE CATEGORY: a model
    line (authoring geometry, lives on a sketch plane) and a detail line
    (annotation, lives on a view). Telling them apart by category is
    impossible BY CONSTRUCTION, and `tools/content_coverage.py` says so
    plainly in its own classifier line: "classified as annotation BY
    MAJORITY in real construction-document models; if a model MODELS with
    lines, this line needs editing." Measured 13.08 on `k2_ar_rd_v7`: 9 407
    such elements, ALL of them with an empty `type_name` and no level,
    while geometry is present (9 256 curves with endpoints, 151 bounding
    boxes) — that is, L0 had NOT ONE field capable of telling one kind from
    the other, even though the line itself is described.

    The value names the READING BRANCH that answered — the same technique
    as :class:`HostSource` and as `default_panel_source` for curtain
    walls: one value has no right to mean three different truths.

    ``None`` (the key is ABSENT from the row) is a SEPARATE state: NOT
    CAPTURED. That is what all frozen L0 looks like, and every row that is
    not a `CurveElement`. ``NONE`` means captured and NOT DETERMINED:
    neither a view nor a plane; this is a TYPED REFUSAL, not an empty
    field. ``READ_FAILED`` means an attempt was made and it threw.
    Conflating the first two is exactly the defect this house has already
    been burned by (§18.2, the silence of the side stage).
    """

    VIEW = "view"
    SKETCH_PLANE = "sketch_plane"
    NONE = "none"
    READ_FAILED = "read_failed"


class CategoryState(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"


Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise L0SchemaError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise L0SchemaError(f"{field_name} must be a finite number")
    return number


def _nonempty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise L0SchemaError(f"{field_name} must be a non-empty string")
    return value


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise L0SchemaError(f"{field_name} must be a string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, field_name)


def _optional_enum(enum_cls: Any, value: Any, field_name: str) -> Any:
    """Parse an optional closed-vocabulary field without inventing a default.

    A missing key and an unknown value are deliberately different outcomes:
    absence is "never measured" (frozen L0 предшествующих волн), while a value
    outside the vocabulary is a payload defect and must refuse.
    """
    if value is None:
        return None
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        raise L0SchemaError(f"{field_name} is invalid: {value!r}") from exc


def _vec(value: Any, size: int, field_name: str) -> tuple[float, ...]:
    if (not isinstance(value, Sequence) or isinstance(value, (str, bytes))
            or len(value) != size):
        raise L0SchemaError(f"{field_name} must contain exactly {size} numbers")
    return tuple(_finite_number(item, f"{field_name}[{index}]")
                 for index, item in enumerate(value))


def _optional_vec(value: Any, size: int, field_name: str) -> tuple[float, ...] | None:
    return None if value is None else _vec(value, size, field_name)


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise L0SchemaError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise L0SchemaError(f"{field_name} keys must be strings")
    return dict(value)


def _require_fields(
    row: Mapping[str, Any],
    required: Sequence[str],
    field_name: str,
) -> None:
    missing = [name for name in required if name not in row]
    if missing:
        raise L0SchemaError(
            f"{field_name} is missing required fields: {', '.join(missing)}")


def _bbox_pair(
    bbox_min_mm: Vec3 | None,
    bbox_max_mm: Vec3 | None,
    field_name: str,
) -> None:
    if (bbox_min_mm is None) != (bbox_max_mm is None):
        raise L0SchemaError(
            f"{field_name}: bbox_min_mm and bbox_max_mm must both be present or absent")
    if bbox_min_mm is not None and any(
            low > high for low, high in zip(bbox_min_mm, bbox_max_mm or ())):
        raise L0SchemaError(f"{field_name}: bbox min must not exceed bbox max")


class FederationTransformStatus(str, Enum):
    """Authority of one measured source-to-declared-target transform."""

    AUTHORITATIVE = "authoritative"
    INCOMPLETE = "incomplete"


class FederationTransformGap(str, Enum):
    """Closed reasons why a Revit transform could not be federated."""

    TRANSFORM_UNAVAILABLE = "transform_unavailable"
    TRANSFORM_INVALID = "transform_invalid"


class FederationTransformTarget(str, Enum):
    """The coordinate frame named by the matrix output."""

    FEDERATION_ROOT = "federation_root"
    PARENT_SOURCE = "parent_source"


_FEDERATION_TRANSFORM_KEYS = frozenset({
    "schema_version", "convention", "matrix", "status", "gaps",
    "content_digest", "target_frame", "subject_context",
})


@dataclass(frozen=True, slots=True)
class FederationTransformSubject:
    """Exact occurrence context to which a measured matrix belongs.

    Keys use the same opaque ``revit:<source>:<value>`` namespace as graph
    ``DocumentIdentity``.  Missing identities remain representable so the
    transform can still be inspected, but such evidence is not replay-safe and
    cannot enter :func:`federate_hulls`.
    """

    source_document_key: str | None
    target_document_key: str | None
    link_instance_chain: tuple[str, ...]
    target_link_instance_chain: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("source_document_key", self.source_document_key),
            ("target_document_key", self.target_document_key),
        ):
            if value is not None and (
                    not isinstance(value, str) or not value.strip()):
                raise L0SchemaError(f"transform.subject.{name} is invalid")
        for name in ("link_instance_chain", "target_link_instance_chain"):
            raw = getattr(self, name)
            if isinstance(raw, str):
                raise L0SchemaError(f"transform.subject.{name} must be an array")
            chain = tuple(raw)
            if any(not isinstance(item, str) or not item.strip()
                   for item in chain):
                raise L0SchemaError(
                    f"transform.subject.{name} contains an invalid id")
            object.__setattr__(self, name, chain)
        parent = self.target_link_instance_chain
        if self.link_instance_chain[:len(parent)] != parent:
            raise L0SchemaError(
                "transform target chain must be a prefix of source chain")

    @property
    def replay_safe(self) -> bool:
        return (
            self.source_document_key is not None
            and self.target_document_key is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_document_key": self.source_document_key,
            "target_document_key": self.target_document_key,
            "link_instance_chain": list(self.link_instance_chain),
            "target_link_instance_chain": list(
                self.target_link_instance_chain),
        }

    @classmethod
    def from_dict(
        cls, value: Any, field_name: str = "transform.subject_context",
    ) -> "FederationTransformSubject":
        row = _mapping(value, field_name)
        expected = frozenset({
            "source_document_key", "target_document_key",
            "link_instance_chain", "target_link_instance_chain",
        })
        if frozenset(row) != expected:
            raise L0SchemaError(f"{field_name} keys mismatch")
        source_key = row.get("source_document_key")
        target_key = row.get("target_document_key")
        for name, raw in (
            ("source_document_key", source_key),
            ("target_document_key", target_key),
        ):
            if raw is not None and (not isinstance(raw, str) or not raw.strip()):
                raise L0SchemaError(f"{field_name}.{name} is invalid")
        source_chain = row.get("link_instance_chain")
        target_chain = row.get("target_link_instance_chain")
        if not isinstance(source_chain, list) or not isinstance(target_chain, list):
            raise L0SchemaError(f"{field_name} chains must be arrays")
        return cls(
            source_document_key=source_key,
            target_document_key=target_key,
            link_instance_chain=tuple(source_chain),
            target_link_instance_chain=tuple(target_chain),
        )


def _canonical_affine_matrix(value: Any, field_name: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != 16:
        raise L0SchemaError(f"{field_name} must contain exactly 16 numbers")
    matrix: list[float] = []
    for index, item in enumerate(value):
        if (isinstance(item, bool) or not isinstance(item, (int, float))
                or not math.isfinite(item)):
            raise L0SchemaError(
                f"{field_name}[{index}] must be a finite number")
        number = float(item)
        matrix.append(0.0 if number == 0.0 else number)
    result = tuple(matrix)
    tol = FEDERATION_TRANSFORM_ORTHONORMAL_TOL
    # The Bridge constructs this row from literals, so numerical drift cannot
    # occur here.  Accepting a merely-near affine row would be dangerous:
    # `_point` intentionally evaluates the 3x4 affine block and ignores W,
    # while the evidence digest would attest different projective bytes.
    if result[12:] != (0.0, 0.0, 0.0, 1.0):
        raise L0SchemaError(
            f"{field_name} must have affine last row [0, 0, 0, 1]")

    # Revit link transforms are Euclidean isometries.  Columns are basis
    # vectors because p_parent = BasisX*x + BasisY*y + BasisZ*z + Origin.
    columns = tuple(
        (result[column], result[4 + column], result[8 + column])
        for column in range(3))
    for index, column in enumerate(columns):
        norm2 = sum(component * component for component in column)
        if abs(norm2 - 1.0) > tol:
            raise L0SchemaError(
                f"{field_name} basis column {index} is scaled or singular")
    for left in range(3):
        for right in range(left + 1, 3):
            dot = sum(
                columns[left][axis] * columns[right][axis]
                for axis in range(3))
            if abs(dot) > tol:
                raise L0SchemaError(
                    f"{field_name} basis contains shear")
    a, b, c = columns
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - b[0] * (a[1] * c[2] - a[2] * c[1])
        + c[0] * (a[1] * b[2] - a[2] * b[1]))
    # abs(det)=1 admits mirrored Revit links while still rejecting collapse,
    # scale and shear.  Reflection is an evidence fact, not an error.
    if abs(abs(determinant) - 1.0) > tol:
        raise L0SchemaError(
            f"{field_name} basis determinant must be +1 or -1")
    return result


def federation_transform_digest(
    matrix: Sequence[float],
    target_frame: FederationTransformTarget = (
        FederationTransformTarget.FEDERATION_ROOT),
    subject_context: FederationTransformSubject | None = None,
) -> str:
    """Content digest of the exact canonical transform convention + matrix."""

    canonical = _canonical_affine_matrix(matrix, "transform.matrix")
    if not isinstance(target_frame, FederationTransformTarget):
        raise L0SchemaError("transform.target_frame must be typed")
    if not isinstance(subject_context, FederationTransformSubject):
        raise L0SchemaError("transform.subject_context must be typed")
    payload = {
        "schema_version": FEDERATION_TRANSFORM_SCHEMA,
        "convention": FEDERATION_TRANSFORM_CONVENTION,
        "matrix": list(canonical),
        "target_frame": target_frame.value,
        "subject_context": subject_context.to_dict(),
    }
    raw = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class FederationTransformEvidence:
    """Validated source-to-declared-target frame evidence.

    The matrix and its digest are an orthogonal axis to document identity:
    knowing *which* link occurrence was read does not prove *where* it was
    placed, and knowing a transform does not identify a document.
    """

    matrix: tuple[float, ...] | None
    status: FederationTransformStatus
    gaps: tuple[FederationTransformGap, ...]
    content_digest: str | None
    target_frame: FederationTransformTarget = (
        FederationTransformTarget.FEDERATION_ROOT)
    subject_context: FederationTransformSubject | None = None
    schema_version: str = FEDERATION_TRANSFORM_SCHEMA
    convention: str = FEDERATION_TRANSFORM_CONVENTION

    def __post_init__(self) -> None:
        if self.schema_version != FEDERATION_TRANSFORM_SCHEMA:
            raise L0SchemaError(
                f"unsupported federation transform schema "
                f"{self.schema_version!r}")
        if self.convention != FEDERATION_TRANSFORM_CONVENTION:
            raise L0SchemaError(
                f"unsupported federation transform convention "
                f"{self.convention!r}")
        if not isinstance(self.status, FederationTransformStatus):
            raise L0SchemaError("transform.status must be typed")
        if not isinstance(self.target_frame, FederationTransformTarget):
            raise L0SchemaError("transform.target_frame must be typed")
        if not isinstance(self.subject_context, FederationTransformSubject):
            raise L0SchemaError("transform.subject_context must be typed")
        gaps = tuple(self.gaps)
        if (len(gaps) != len(set(gaps))
                or any(not isinstance(gap, FederationTransformGap)
                       for gap in gaps)):
            raise L0SchemaError("transform.gaps are invalid or duplicated")
        object.__setattr__(self, "gaps", gaps)
        if self.matrix is None:
            if self.status is not FederationTransformStatus.INCOMPLETE:
                raise L0SchemaError(
                    "missing transform cannot be authoritative")
            if len(gaps) != 1:
                raise L0SchemaError(
                    "missing transform requires exactly one named gap")
            if self.content_digest is not None:
                raise L0SchemaError(
                    "missing transform cannot carry a content digest")
            return
        canonical = _canonical_affine_matrix(
            self.matrix, "transform.matrix")
        object.__setattr__(self, "matrix", canonical)
        if self.status is not FederationTransformStatus.AUTHORITATIVE or gaps:
            raise L0SchemaError(
                "present transform must be authoritative and gap-free")
        expected = federation_transform_digest(
            canonical, self.target_frame, self.subject_context)
        if self.content_digest != expected:
            raise L0SchemaError("transform.content_digest mismatch")

    @property
    def authoritative(self) -> bool:
        return self.status is FederationTransformStatus.AUTHORITATIVE

    @property
    def determinant(self) -> float | None:
        if self.matrix is None:
            return None
        m = self.matrix
        return (
            m[0] * (m[5] * m[10] - m[6] * m[9])
            - m[1] * (m[4] * m[10] - m[6] * m[8])
            + m[2] * (m[4] * m[9] - m[5] * m[8]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "convention": self.convention,
            "matrix": list(self.matrix) if self.matrix is not None else None,
            "status": self.status.value,
            "gaps": [gap.value for gap in self.gaps],
            "content_digest": self.content_digest,
            "target_frame": self.target_frame.value,
            "subject_context": self.subject_context.to_dict(),
        }

    @classmethod
    def from_dict(
        cls, value: Any, field_name: str = "federation_transform",
    ) -> "FederationTransformEvidence":
        row = _mapping(value, field_name)
        keys = frozenset(row)
        if keys != _FEDERATION_TRANSFORM_KEYS:
            missing = sorted(_FEDERATION_TRANSFORM_KEYS - keys)
            extra = sorted(keys - _FEDERATION_TRANSFORM_KEYS)
            raise L0SchemaError(
                f"{field_name} keys mismatch; missing={missing}, extra={extra}")
        try:
            status = FederationTransformStatus(row.get("status"))
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"{field_name}.status is invalid: {row.get('status')!r}") from exc
        try:
            target_frame = FederationTransformTarget(row.get("target_frame"))
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"{field_name}.target_frame is invalid: "
                f"{row.get('target_frame')!r}") from exc
        raw_gaps = row.get("gaps")
        if not isinstance(raw_gaps, list):
            raise L0SchemaError(f"{field_name}.gaps must be an array")
        try:
            gaps = tuple(FederationTransformGap(item) for item in raw_gaps)
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"{field_name}.gaps contains an unknown reason") from exc
        digest = row.get("content_digest")
        if digest is not None and (
                not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise L0SchemaError(
                f"{field_name}.content_digest must be lowercase sha256 or null")
        raw_matrix = row.get("matrix")
        subject = FederationTransformSubject.from_dict(
            row.get("subject_context"), f"{field_name}.subject_context")
        return cls(
            schema_version=_nonempty_string(
                row.get("schema_version"), f"{field_name}.schema_version"),
            convention=_nonempty_string(
                row.get("convention"), f"{field_name}.convention"),
            matrix=(
                _canonical_affine_matrix(raw_matrix, f"{field_name}.matrix")
                if raw_matrix is not None else None),
            status=status,
            gaps=gaps,
            content_digest=digest,
            target_frame=target_frame,
            subject_context=subject,
        )

    @classmethod
    def from_bridge_dict(
        cls, value: Any, field_name: str = "federation_transform",
        *, subject_context: FederationTransformSubject,
    ) -> "FederationTransformEvidence":
        """Issue the digest at the Python trust boundary.

        Revit 2025/2026 cannot compile ``SHA256`` in the exact Bridge closure.
        The collector therefore returns only the measured matrix/status/gaps;
        the server validates the isometry and issues the canonical digest
        before a byte reaches persisted L0.
        """

        row = _mapping(value, field_name)
        if not isinstance(subject_context, FederationTransformSubject):
            raise L0SchemaError(
                f"{field_name} requires typed subject_context")
        expected = frozenset({"matrix", "status", "gaps", "target_frame"})
        if frozenset(row) != expected:
            raise L0SchemaError(
                f"{field_name} bridge keys must be exactly "
                "matrix,status,gaps,target_frame")
        try:
            target_frame = FederationTransformTarget(row.get("target_frame"))
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"{field_name}.target_frame is invalid: "
                f"{row.get('target_frame')!r}") from exc
        raw_matrix = row.get("matrix")
        if raw_matrix is None:
            matrix = None
            digest = None
        else:
            matrix = _canonical_affine_matrix(
                raw_matrix, f"{field_name}.matrix")
            digest = federation_transform_digest(
                matrix, target_frame, subject_context)
        return cls.from_dict({
            "schema_version": FEDERATION_TRANSFORM_SCHEMA,
            "convention": FEDERATION_TRANSFORM_CONVENTION,
            "matrix": list(matrix) if matrix is not None else None,
            "status": row.get("status"),
            "gaps": row.get("gaps"),
            "content_digest": digest,
            "target_frame": target_frame.value,
            "subject_context": subject_context.to_dict(),
        }, field_name)


def identity_federation_transform(
    *,
    document_key: str = "test:federation-root",
) -> FederationTransformEvidence:
    matrix = (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
    return FederationTransformEvidence(
        matrix=matrix,
        status=FederationTransformStatus.AUTHORITATIVE,
        gaps=(),
        content_digest=federation_transform_digest(
            matrix, FederationTransformTarget.FEDERATION_ROOT,
            FederationTransformSubject(
                source_document_key=document_key,
                target_document_key=document_key,
                link_instance_chain=(),
                target_link_instance_chain=())),
        target_frame=FederationTransformTarget.FEDERATION_ROOT,
        subject_context=FederationTransformSubject(
            source_document_key=document_key,
            target_document_key=document_key,
            link_instance_chain=(),
            target_link_instance_chain=()),
    )


class L0SourceKind(str, Enum):
    """How the source document is observed from the federation root."""

    ROOT = "root"
    LINK = "link"


def _identity_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise L0SchemaError(f"{field_name} must be a non-blank string")
    return value


@dataclass(frozen=True, slots=True)
class DocumentIdentityFact:
    """One Revit-owned document identity fact, before graph namespacing."""

    source: str
    value: str

    def __post_init__(self) -> None:
        if self.source not in DOCUMENT_IDENTITY_SOURCES:
            raise L0SchemaError(
                f"unsupported document identity source {self.source!r}")
        _identity_text(self.value, "DocumentIdentityFact.value")

    @property
    def authoritative(self) -> bool:
        """Whether this source may namespace graph definitions by itself."""
        return self.source in AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "value": self.value}

    @classmethod
    def from_dict(
        cls, value: Any, field_name: str = "document_identity",
    ) -> "DocumentIdentityFact":
        row = _mapping(value, field_name)
        _require_fields(row, ("source", "value"), field_name)
        return cls(
            source=_identity_text(
                row.get("source"), f"{field_name}.source"),
            value=_identity_text(
                row.get("value"), f"{field_name}.value"),
        )


_DOCUMENT_CONTEXT_GAPS = frozenset({
    IdentityGap.SOURCE_DOCUMENT_IDENTITY_UNAVAILABLE,
    IdentityGap.SOURCE_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE,
    IdentityGap.FEDERATION_ROOT_IDENTITY_UNAVAILABLE,
    IdentityGap.FEDERATION_ROOT_IDENTITY_NOT_AUTHORITATIVE,
    IdentityGap.LINK_INSTANCE_UNIQUE_ID_UNAVAILABLE,
})

_LINK_IDENTITY_GAPS = frozenset({
    IdentityGap.LINK_INSTANCE_UNIQUE_ID_UNAVAILABLE,
    IdentityGap.LINKED_DOCUMENT_UNAVAILABLE,
    IdentityGap.LINKED_DOCUMENT_IDENTITY_UNAVAILABLE,
    IdentityGap.LINKED_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE,
})


def _identity_gaps(
    value: Any,
    field_name: str,
    *,
    allowed: frozenset[IdentityGap],
) -> tuple[IdentityGap, ...]:
    if not isinstance(value, list):
        raise L0SchemaError(f"{field_name} must be an array")
    parsed: list[IdentityGap] = []
    for index, item in enumerate(value):
        try:
            gap = IdentityGap(item)
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"{field_name}[{index}] is invalid: {item!r}") from exc
        if gap not in allowed:
            raise L0SchemaError(
                f"{field_name}[{index}] is not valid in this identity seam")
        parsed.append(gap)
    if len(parsed) != len(set(parsed)):
        raise L0SchemaError(f"{field_name} contains duplicates")
    return tuple(parsed)


@dataclass(frozen=True, slots=True)
class L0IdentityMetadata:
    """Identity context captured by the same Revit call as the L0 header.

    This is intentionally optional on :class:`L0Document`: old snapshots did
    not capture it and remain readable, but their graph identity is explicitly
    incomplete.  The status is checked against the facts so a producer cannot
    claim authority with an empty link path or a missing document identity.
    """

    source_kind: L0SourceKind
    document_identity: DocumentIdentityFact | None
    federation_root_identity: DocumentIdentityFact | None
    link_instance_chain: tuple[str, ...]
    status: IdentityStatus
    gaps: tuple[IdentityGap, ...]
    schema_version: str = L0_IDENTITY_METADATA_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != L0_IDENTITY_METADATA_SCHEMA:
            raise L0SchemaError(
                f"unsupported L0 identity schema {self.schema_version!r}")
        if not isinstance(self.source_kind, L0SourceKind):
            raise L0SchemaError("L0IdentityMetadata.source_kind must be typed")
        for name, value in (
            ("document_identity", self.document_identity),
            ("federation_root_identity", self.federation_root_identity),
        ):
            if value is not None and not isinstance(value, DocumentIdentityFact):
                raise L0SchemaError(
                    f"L0IdentityMetadata.{name} must be typed or null")
        if isinstance(self.link_instance_chain, str):
            raise L0SchemaError("identity link chain must be an array")
        chain = tuple(self.link_instance_chain)
        for index, value in enumerate(chain):
            _identity_text(value, f"identity.link_instance_chain[{index}]")
        object.__setattr__(self, "link_instance_chain", chain)
        if self.source_kind is L0SourceKind.ROOT and chain:
            raise L0SchemaError("root identity cannot carry a link chain")
        if (self.source_kind is L0SourceKind.ROOT
                and self.document_identity is not None
                and self.federation_root_identity is not None
                and self.document_identity != self.federation_root_identity):
            raise L0SchemaError(
                "root document identity differs from federation root")
        if not isinstance(self.status, IdentityStatus):
            raise L0SchemaError("identity.status must be typed")
        gaps = tuple(self.gaps)
        if (len(gaps) != len(set(gaps))
                or any(gap not in _DOCUMENT_CONTEXT_GAPS for gap in gaps)):
            raise L0SchemaError("identity.gaps are invalid or duplicated")
        object.__setattr__(self, "gaps", gaps)
        expected_gaps: set[IdentityGap] = set()
        if self.document_identity is None:
            expected_gaps.add(
                IdentityGap.SOURCE_DOCUMENT_IDENTITY_UNAVAILABLE)
        elif not self.document_identity.authoritative:
            expected_gaps.add(
                IdentityGap.SOURCE_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE)
        if self.federation_root_identity is None:
            expected_gaps.add(
                IdentityGap.FEDERATION_ROOT_IDENTITY_UNAVAILABLE)
        elif not self.federation_root_identity.authoritative:
            expected_gaps.add(
                IdentityGap.FEDERATION_ROOT_IDENTITY_NOT_AUTHORITATIVE)
        if self.source_kind is L0SourceKind.LINK and not chain:
            expected_gaps.add(
                IdentityGap.LINK_INSTANCE_UNIQUE_ID_UNAVAILABLE)
        if set(gaps) != expected_gaps:
            raise L0SchemaError(
                "identity.gaps do not exactly describe missing facts")
        complete = (
            self.document_identity is not None
            and self.document_identity.authoritative
            and self.federation_root_identity is not None
            and self.federation_root_identity.authoritative
            and (self.source_kind is L0SourceKind.ROOT or bool(chain))
            and not gaps)
        if (self.status is IdentityStatus.AUTHORITATIVE) != complete:
            raise L0SchemaError(
                "identity.status contradicts captured facts/gaps")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_kind": self.source_kind.value,
            "document_identity": (
                self.document_identity.to_dict()
                if self.document_identity is not None else None),
            "federation_root_identity": (
                self.federation_root_identity.to_dict()
                if self.federation_root_identity is not None else None),
            "link_instance_chain": list(self.link_instance_chain),
            "status": self.status.value,
            "gaps": [gap.value for gap in self.gaps],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "L0IdentityMetadata":
        row = _mapping(value, "identity")
        _require_fields(row, (
            "schema_version", "source_kind", "document_identity",
            "federation_root_identity", "link_instance_chain", "status",
            "gaps",
        ), "identity")
        try:
            source_kind = L0SourceKind(row.get("source_kind"))
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"identity.source_kind is invalid: "
                f"{row.get('source_kind')!r}") from exc
        try:
            status = IdentityStatus(row.get("status"))
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"identity.status is invalid: {row.get('status')!r}") from exc
        raw_chain = row.get("link_instance_chain")
        if not isinstance(raw_chain, list):
            raise L0SchemaError("identity.link_instance_chain must be an array")
        return cls(
            schema_version=_nonempty_string(
                row.get("schema_version"), "identity.schema_version"),
            source_kind=source_kind,
            document_identity=(
                DocumentIdentityFact.from_dict(
                    row["document_identity"], "identity.document_identity")
                if row.get("document_identity") is not None else None),
            federation_root_identity=(
                DocumentIdentityFact.from_dict(
                    row["federation_root_identity"],
                    "identity.federation_root_identity")
                if row.get("federation_root_identity") is not None else None),
            link_instance_chain=tuple(
                _identity_text(
                    item, f"identity.link_instance_chain[{index}]")
                for index, item in enumerate(raw_chain)),
            status=status,
            gaps=_identity_gaps(
                row.get("gaps"), "identity.gaps",
                allowed=_DOCUMENT_CONTEXT_GAPS),
        )


@dataclass(frozen=True, slots=True)
class L0LinkIdentity:
    """Identity facts for one RevitLinkInstance in the root header."""

    instance_unique_id: str | None
    linked_document_identity: DocumentIdentityFact | None
    status: IdentityStatus
    gaps: tuple[IdentityGap, ...]
    schema_version: str = L0_IDENTITY_METADATA_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != L0_IDENTITY_METADATA_SCHEMA:
            raise L0SchemaError(
                f"unsupported link identity schema {self.schema_version!r}")
        if self.instance_unique_id is not None:
            _identity_text(
                self.instance_unique_id,
                "L0LinkIdentity.instance_unique_id")
        if (self.linked_document_identity is not None
                and not isinstance(
                    self.linked_document_identity, DocumentIdentityFact)):
            raise L0SchemaError(
                "linked_document_identity must be typed or null")
        if not isinstance(self.status, IdentityStatus):
            raise L0SchemaError("link.identity.status must be typed")
        gaps = tuple(self.gaps)
        if (len(gaps) != len(set(gaps))
                or any(gap not in _LINK_IDENTITY_GAPS for gap in gaps)):
            raise L0SchemaError("link.identity.gaps are invalid or duplicated")
        object.__setattr__(self, "gaps", gaps)
        expected_instance_gap = self.instance_unique_id is None
        if ((IdentityGap.LINK_INSTANCE_UNIQUE_ID_UNAVAILABLE in gaps)
                != expected_instance_gap):
            raise L0SchemaError(
                "link.identity instance gap contradicts instance_unique_id")
        linked_gaps = {
            IdentityGap.LINKED_DOCUMENT_UNAVAILABLE,
            IdentityGap.LINKED_DOCUMENT_IDENTITY_UNAVAILABLE,
            IdentityGap.LINKED_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE,
        } & set(gaps)
        if self.linked_document_identity is None:
            if len(linked_gaps) != 1:
                raise L0SchemaError(
                    "missing linked document identity needs one named gap")
        elif self.linked_document_identity.authoritative:
            if linked_gaps:
                raise L0SchemaError(
                    "link.identity linked-document gap contradicts its fact")
        elif linked_gaps != {
                IdentityGap.LINKED_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE}:
            raise L0SchemaError(
                "weak linked document identity needs its authority gap")
        complete = (
            self.instance_unique_id is not None
            and self.linked_document_identity is not None
            and self.linked_document_identity.authoritative
            and not gaps)
        if (self.status is IdentityStatus.AUTHORITATIVE) != complete:
            raise L0SchemaError(
                "link.identity.status contradicts captured facts/gaps")

    @property
    def authoritative(self) -> bool:
        return self.status is IdentityStatus.AUTHORITATIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "instance_unique_id": self.instance_unique_id,
            "linked_document_identity": (
                self.linked_document_identity.to_dict()
                if self.linked_document_identity is not None else None),
            "status": self.status.value,
            "gaps": [gap.value for gap in self.gaps],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "L0LinkIdentity":
        row = _mapping(value, "link.identity")
        _require_fields(row, (
            "schema_version", "instance_unique_id",
            "linked_document_identity", "status", "gaps",
        ), "link.identity")
        try:
            status = IdentityStatus(row.get("status"))
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"link.identity.status is invalid: "
                f"{row.get('status')!r}") from exc
        return cls(
            schema_version=_nonempty_string(
                row.get("schema_version"),
                "link.identity.schema_version"),
            instance_unique_id=(
                _identity_text(
                    row.get("instance_unique_id"),
                    "link.identity.instance_unique_id")
                if row.get("instance_unique_id") is not None else None),
            linked_document_identity=(
                DocumentIdentityFact.from_dict(
                    row["linked_document_identity"],
                    "link.identity.linked_document_identity")
                if row.get("linked_document_identity") is not None else None),
            status=status,
            gaps=_identity_gaps(
                row.get("gaps"), "link.identity.gaps",
                allowed=_LINK_IDENTITY_GAPS),
        )


@dataclass(frozen=True, slots=True)
class NamedReference:
    id: str
    name: str

    def __post_init__(self) -> None:
        _nonempty_string(self.id, "NamedReference.id")
        if not isinstance(self.name, str):
            raise L0SchemaError("NamedReference.name must be a string")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}

    @classmethod
    def from_dict(cls, value: Any, field_name: str = "reference") -> "NamedReference":
        row = _mapping(value, field_name)
        _require_fields(row, ("id", "name"), field_name)
        return cls(
            id=_nonempty_string(row.get("id"), f"{field_name}.id"),
            name=_string(row.get("name"), f"{field_name}.name"),
        )


@dataclass(frozen=True, slots=True)
class LevelInfo:
    id: str
    name: str
    elevation_mm: float

    def __post_init__(self) -> None:
        _nonempty_string(self.id, "LevelInfo.id")
        if not isinstance(self.name, str):
            raise L0SchemaError("LevelInfo.name must be a string")
        _finite_number(self.elevation_mm, "LevelInfo.elevation_mm")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name,
                "elevation_mm": self.elevation_mm}

    @classmethod
    def from_dict(cls, value: Any) -> "LevelInfo":
        row = _mapping(value, "level")
        _require_fields(row, ("id", "name", "elevation_mm"), "level")
        return cls(
            id=_nonempty_string(row.get("id"), "level.id"),
            name=_string(row.get("name"), "level.name"),
            elevation_mm=_finite_number(row.get("elevation_mm"), "level.elevation_mm"),
        )


@dataclass(frozen=True, slots=True)
class GridInfo:
    id: str
    name: str
    p0_mm: Vec3
    p1_mm: Vec3
    #: 🔴 THE AXIS CURVE'S KIND, SET UP 25.08.2026. Before it, the axis was
    #: described by TWO ENDPOINTS and nothing else: an arc arrived as a
    #: straight line, and nowhere did anything turn red. The op's
    #: postcondition — «curve endpoints == p0/p1 (±5 мм)» — matches a CHORD
    #: against an arc EXACTLY, meaning the witness could not turn red on
    #: exactly the defect it exists for.
    #:
    #: `None` is a THIRD STATE: the snapshot was captured before this wave,
    #: the kind was NOT MEASURED. Refusing on it would mean declaring every
    #: snapshot in the corpus unfit at once — that is, refusing out of
    #: IGNORANCE.
    curve_kind: str | None = None

    def __post_init__(self) -> None:
        _nonempty_string(self.id, "GridInfo.id")
        if not isinstance(self.name, str):
            raise L0SchemaError("GridInfo.name must be a string")
        _vec(self.p0_mm, 3, "GridInfo.p0_mm")
        _vec(self.p1_mm, 3, "GridInfo.p1_mm")
        if self.curve_kind is not None and not isinstance(self.curve_kind, str):
            raise L0SchemaError("GridInfo.curve_kind must be a string or None")

    def to_dict(self) -> dict[str, Any]:
        row = {"id": self.id, "name": self.name,
               "p0_mm": list(self.p0_mm), "p1_mm": list(self.p1_mm)}
        # Not measured — the key is absent: otherwise the third state would
        # be erased on the very first write-read round trip.
        if self.curve_kind is not None:
            row["curve_kind"] = self.curve_kind
        return row

    @classmethod
    def from_dict(cls, value: Any) -> "GridInfo":
        row = _mapping(value, "grid")
        _require_fields(row, ("id", "name", "p0_mm", "p1_mm"), "grid")
        род = row.get("curve_kind")
        return cls(
            id=_nonempty_string(row.get("id"), "grid.id"),
            name=_string(row.get("name"), "grid.name"),
            p0_mm=_vec(row.get("p0_mm"), 3, "grid.p0_mm"),  # type: ignore[arg-type]
            p1_mm=_vec(row.get("p1_mm"), 3, "grid.p1_mm"),  # type: ignore[arg-type]
            curve_kind=(_string(род, "grid.curve_kind")
                        if род is not None else None),
        )


@dataclass(frozen=True, slots=True)
class RoomInfo:
    id: str
    name: str
    level_id: str | None
    level_name: str | None
    area_m2: float
    boundary_mm: tuple[Vec2, ...]
    boundary_loops_mm: tuple[tuple[Vec2, ...], ...]
    bounding_element_ids: tuple[str, ...]
    # Additive L0 field.  None means an older record did not measure the room
    # number; an empty string is a measured empty ROOM_NUMBER and must not be
    # collapsed into that legacy state.
    number: str | None = None

    def __post_init__(self) -> None:
        _nonempty_string(self.id, "RoomInfo.id")
        if not isinstance(self.name, str):
            raise L0SchemaError("RoomInfo.name must be a string")
        if self.number is not None:
            _string(self.number, "RoomInfo.number")
        _optional_string(self.level_id, "RoomInfo.level_id")
        _optional_string(self.level_name, "RoomInfo.level_name")
        if _finite_number(self.area_m2, "RoomInfo.area_m2") < 0:
            raise L0SchemaError("RoomInfo.area_m2 must be non-negative")
        for index, point in enumerate(self.boundary_mm):
            _vec(point, 2, f"RoomInfo.boundary_mm[{index}]")
        for loop_index, loop in enumerate(self.boundary_loops_mm):
            for point_index, point in enumerate(loop):
                _vec(point, 2,
                     f"RoomInfo.boundary_loops_mm[{loop_index}][{point_index}]")
        for index, element_id in enumerate(self.bounding_element_ids):
            _nonempty_string(
                element_id, f"RoomInfo.bounding_element_ids[{index}]")

    def to_dict(self) -> dict[str, Any]:
        row = {
            "id": self.id,
            "name": self.name,
            "level_id": self.level_id,
            "level_name": self.level_name,
            "area_m2": self.area_m2,
            "boundary_mm": [list(point) for point in self.boundary_mm],
            "boundary_loops_mm": [
                [list(point) for point in loop] for loop in self.boundary_loops_mm
            ],
            "bounding_element_ids": list(self.bounding_element_ids),
        }
        # Preserve the frozen byte shape of legacy RoomInfo rows.  Fresh
        # extraction always carries this key, including number="".
        if self.number is not None:
            row["number"] = self.number
        return row

    @classmethod
    def from_dict(cls, value: Any) -> "RoomInfo":
        row = _mapping(value, "room")
        _require_fields(row, (
            "id", "name", "level_id", "level_name", "area_m2",
            "boundary_mm", "bounding_element_ids",
        ), "room")
        boundary = row.get("boundary_mm")
        loops = row.get("boundary_loops_mm")
        if loops is None:
            loops = [boundary] if boundary else []
        if not isinstance(boundary, list) or not isinstance(loops, list):
            raise L0SchemaError("room boundaries must be arrays")
        ids = row.get("bounding_element_ids")
        if not isinstance(ids, list):
            raise L0SchemaError("room.bounding_element_ids must be an array")
        return cls(
            id=_nonempty_string(row.get("id"), "room.id"),
            name=_string(row.get("name"), "room.name"),
            level_id=_optional_string(row.get("level_id"), "room.level_id"),
            level_name=_optional_string(row.get("level_name"), "room.level_name"),
            area_m2=_finite_number(row.get("area_m2"), "room.area_m2"),
            boundary_mm=tuple(
                _vec(point, 2, f"room.boundary_mm[{index}]")  # type: ignore[arg-type]
                for index, point in enumerate(boundary)),
            boundary_loops_mm=tuple(
                tuple(
                    _vec(point, 2,  # type: ignore[arg-type]
                         f"room.boundary_loops_mm[{loop_index}][{point_index}]")
                    for point_index, point in enumerate(loop))
                for loop_index, loop in enumerate(loops)),
            bounding_element_ids=tuple(
                _nonempty_string(element_id,
                                 f"room.bounding_element_ids[{index}]")
                for index, element_id in enumerate(ids)),
            number=(None if row.get("number") is None else
                    _string(row.get("number"), "room.number")),
        )


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    name: str | None = None
    address: str | None = None
    building_type_hint: str | None = None

    def __post_init__(self) -> None:
        _optional_string(self.name, "ProjectInfo.name")
        _optional_string(self.address, "ProjectInfo.address")
        _optional_string(
            self.building_type_hint, "ProjectInfo.building_type_hint")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "address": self.address,
            "building_type_hint": self.building_type_hint,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ProjectInfo":
        row = _mapping({} if value is None else value, "project_info")
        return cls(
            name=_optional_string(row.get("name"), "project_info.name"),
            address=_optional_string(row.get("address"), "project_info.address"),
            building_type_hint=_optional_string(
                row.get("building_type_hint"),
                "project_info.building_type_hint"),
        )


@dataclass(frozen=True, slots=True)
class L0Element:
    element_id: str
    category: str
    category_ru: str
    type_id: str
    type_name: str
    level_id: str | None
    level_name: str | None
    geom_kind: GeometryKind
    p0_mm: Vec3 | None
    p1_mm: Vec3 | None
    rotation_deg: float | None
    bbox_min_mm: Vec3 | None
    bbox_max_mm: Vec3 | None
    host_id: str | None
    params: Mapping[str, Any] = field(default_factory=dict)
    design_option: NamedReference | None = None
    phase_created: NamedReference | None = None
    workset: NamedReference | None = None
    # A §18.1 consequence: the curve's kind. The field was APPENDED AT THE
    # END deliberately — the order of the fields above is a positional
    # contract of already-written code, and the default value keeps the
    # field compatible with frozen L0 1.0: its rows contain no such field,
    # and its absence means "not measured," not "a straight line" (see
    # :class:`LocationCurveKind`).
    curve_kind: "LocationCurveKind | None" = None
    # The host-capture wave (09.08). The field was appended AT THE TAIL
    # under the same law as `curve_kind` two lines above: the order of the
    # fields above it is a positional contract of already-written code, and
    # the default value keeps frozen L0 1.0 parseable record by record.
    # This does not move the dialect version: the dialect names the
    # generation of the CATEGORY TABLE, not the set of record fields (see
    # "THE APPEND-AT-THE-TAIL LAW" in the file's header).
    host_source: "HostSource | None" = None
    # Federated identity capture.  ``element_id`` remains the local Revit
    # address used by all historical L0 consumers; this additive field is the
    # stable definition fact.  None means a legacy/unmeasured row, never a
    # synthesized identity from the local id.
    unique_id: str | None = None
    # A line's ownership (13.08). Appended AT THE TAIL under the same law
    # as `curve_kind` and `host_source` above. The default value keeps
    # frozen L0 parseable record by record, and the key's absence means
    # "not captured," not "undetermined" — see :class:`LineOwner`.
    line_owner_kind: "LineOwner | None" = None
    line_owner_id: str | None = None
    # An MEP run's kind (04.09.2026). Appended AT THE TAIL under the same
    # law as `curve_kind`, `host_source` and `line_owner_kind` above.
    #
    # 🔴 THE FIELD IS THREE-VALUED, AND THAT IS ITS WHOLE POINT. `True` is a
    # placeholder, `False` is a real run, `None` is NOT MEASURED. Without
    # the third state, a decompile captured before this wave would declare
    # every one of its pipes real — that is, it would give back exactly
    # the defect the field exists to prevent: a placeholder
    # indistinguishable from a run, reassembled as a solid pipe.
    #
    # Names cross-checked AGAINST THE TRAP INDEX, not from memory:
    #   P:Autodesk.Revit.DB.Plumbing.Pipe.IsPlaceholder      2021-2026, 0 traps
    #   P:Autodesk.Revit.DB.Mechanical.Duct.IsPlaceholder    2021-2026, 0 traps
    # The same index shows a namesake that is easy to confuse and has
    # nothing to do with runs: `P:Autodesk.Revit.DB.ViewSheet.IsPlaceholder`.
    is_placeholder: bool | None = None
    # A flexible run's path (04.09.2026). Appended AT THE TAIL under the
    # same law.
    #
    # A PRIMARY quantity, not a derived one: for a flexible element,
    # `Location as LocationCurve` gives a Hermite spline whose endpoints
    # are computed FROM the points, and the authoring op directly requires
    # checking ALL the points and their COUNT — "checking the endpoints
    # would miss a discarded middle, that is, a different route under a
    # green verdict" (`ops_mep`). So this holds the entire polyline, not a
    # pair of endpoints.
    #
    # `None` means NOT MEASURED. An empty tuple is impossible by
    # construction: `Points` includes the endpoints, so an existing run
    # has no fewer than two of them.
    #
    # Names cross-checked AGAINST THE TRAP INDEX:
    #   P:Autodesk.Revit.DB.Mechanical.FlexDuct.Points   2021-2026, 0 traps
    #   P:Autodesk.Revit.DB.Plumbing.FlexPipe.Points     2021-2026, 0 traps
    flex_path_mm: "tuple[Vec3, ...] | None" = None
    # An opening's boundary (04.09.2026). Appended AT THE TAIL under the
    # same law.
    #
    # TWO FIELDS, NOT ONE, AND THIS IS LOAD-BEARING. Together they encode
    # FOUR states without a single new vocabulary:
    #
    #   is_rect None                      -> NOT MEASURED (old snapshot)
    #   is_rect True  + boundary (2 corners) -> a rectangular opening in a wall
    #   is_rect False + boundary (N points)  -> a profile in a floor/roof
    #   is_rect False + no boundary          -> the boundary WAS READ and
    #                                           it is NOT A POLYLINE (an
    #                                           arc), and an arc cannot be
    #                                           expressed as a polyline:
    #                                           `outline` would give a
    #                                           DIFFERENT shape, not an
    #                                           approximation
    #
    # The fourth state is not a poor record, but a fact about the
    # building, and the lifter is required to refuse on it BY NAME. The
    # authoring op states the same class verbatim: "a round opening for a
    # riser cannot be expressed as a polyline."
    #
    # Names cross-checked AGAINST THE TRAP INDEX (all 6/6, 0 traps):
    #   P:Autodesk.Revit.DB.Opening.IsRectBoundary
    #   P:Autodesk.Revit.DB.Opening.BoundaryRect
    #   P:Autodesk.Revit.DB.Opening.BoundaryCurves
    # `Opening.SketchId` lives only on 2022-2026 — a seam, so it is not
    # read.
    opening_is_rect: bool | None = None
    opening_boundary_mm: "tuple[Vec3, ...] | None" = None
    # A linear load (04.09.2026). Appended AT THE TAIL under the same law.
    #
    # FIVE FIELDS, AND TWO OF THEM ARE NOT DATA BUT BOUNDARIES.
    # `load_uniform` and `load_projected` are not parameters of the op at
    # all; they exist here purely so the lifter can REFUSE on them by
    # name. A non-uniform load carries TWO different vectors at its ends,
    # while the op holds a single triple: taking the first would mean
    # passing off a different load as this one.
    #
    # Names cross-checked against the trap index; both vectors have two
    # traps each, and both are "when setting this property," meaning
    # READING is safe.
    load_p0_mm: "Vec3 | None" = None
    load_p1_mm: "Vec3 | None" = None
    load_case_id: str | None = None
    load_case_name: str | None = None
    load_force_n_per_m: "Vec3 | None" = None
    load_uniform: bool | None = None
    load_projected: bool | None = None
    # 🔴 THREE FIELDS ADDED THE SAME DAY, AFTER ONE'S OWN MISTAKE. The
    # first version read from a load only its endpoints, vector, and case
    # — exactly what the reason for the gap named. The full member list of
    # `LoadBase` was read IN FULL one turn later, and it turned up three
    # 6/6 properties with zero traps, each of which changes the load's
    # MEANING:
    #
    #   IsHosted / HostElementId  a hosted load travels with its carrier;
    #                             the op has no input for a carrier at all
    #   IsReaction                a reaction is the RESULT of a
    #                             calculation, not an author's input;
    #                             rebuilding it as authored means passing
    #                             off a computed value as a given one
    #   OrientTo                  the force's basis: Project /
    #                             HostLocalCoordinateSystem / WorkPlane.
    #                             The authoring op's postcondition
    #                             promises exactly `Project`, meaning it
    #                             cannot express any other basis, and
    #                             would silently change it
    load_hosted: bool | None = None
    load_reaction: bool | None = None
    load_orient_to: str | None = None
    # A point load (04.09.2026). SEPARATE fields from the linear load, and
    # this is not pedantry: a linear load's force is measured in N/M, a
    # point load's in N. One field for both kinds would mean a number
    # without a unit, with the unit living inside the reader's head. The
    # same argument keeps the moment apart: N·m does not reduce to any of
    # the above.
    load_force_n: "Vec3 | None" = None
    load_moment_nm: "Vec3 | None" = None
    # An area load (04.09.2026). ALL of the rings, not just the first: the
    # op's postcondition promises "GetLoops returns ONE ring," meaning the
    # ring count is a boundary, and it can only be known by keeping all of
    # them.
    #
    # `load_ref_points` is `AreaLoad.NumRefPoints`. An area load has
    # THREE force vectors (ForceVector1/2/3), and more than one reference
    # point means non-uniformity, which the op with its single triple
    # cannot express.
    load_area_loops_mm: "tuple[tuple[Vec3, ...], ...] | None" = None
    load_ref_points: int | None = None
    load_force_n_per_m2: "Vec3 | None" = None

    def __post_init__(self) -> None:
        _nonempty_string(self.element_id, "L0Element.element_id")
        _nonempty_string(self.category, "L0Element.category")
        if not isinstance(self.category_ru, str):
            raise L0SchemaError("L0Element.category_ru must be a string")
        if not isinstance(self.type_id, str) or not isinstance(self.type_name, str):
            raise L0SchemaError("L0Element type id/name must be strings")
        _optional_string(self.level_id, "L0Element.level_id")
        _optional_string(self.level_name, "L0Element.level_name")
        if not isinstance(self.geom_kind, GeometryKind):
            raise L0SchemaError("L0Element.geom_kind must be a GeometryKind")
        _optional_vec(self.p0_mm, 3, "L0Element.p0_mm")
        _optional_vec(self.p1_mm, 3, "L0Element.p1_mm")
        if self.rotation_deg is not None:
            _finite_number(self.rotation_deg, "L0Element.rotation_deg")
        _optional_vec(self.bbox_min_mm, 3, "L0Element.bbox_min_mm")
        _optional_vec(self.bbox_max_mm, 3, "L0Element.bbox_max_mm")
        _bbox_pair(self.bbox_min_mm, self.bbox_max_mm, "L0Element")
        _optional_string(self.host_id, "L0Element.host_id")
        _mapping(self.params, "L0Element.params")
        for field_name, reference in (
            ("design_option", self.design_option),
            ("phase_created", self.phase_created),
            ("workset", self.workset),
        ):
            if reference is not None and not isinstance(reference, NamedReference):
                raise L0SchemaError(
                    f"L0Element.{field_name} must be a NamedReference or null")
        if self.curve_kind is not None:
            if not isinstance(self.curve_kind, LocationCurveKind):
                raise L0SchemaError(
                    "L0Element.curve_kind must be a LocationCurveKind or null")
            if self.geom_kind is not GeometryKind.CURVE:
                raise L0SchemaError(
                    "curve_kind describes a LocationCurve and cannot accompany "
                    f"{self.geom_kind.value} geometry")
        if self.host_source is not None:
            if not isinstance(self.host_source, HostSource):
                raise L0SchemaError(
                    "L0Element.host_source must be a HostSource or null")
            # A source without the host itself is a contradiction, not a
            # sparse row: capture writes both fields in one assignment or
            # neither, and a mismatch means a corrupted stream, not "we
            # read the class but not the id." The refusal is by name, as
            # the file's header requires of any TIGHTENING.
            if self.host_id is None:
                raise L0SchemaError(
                    "L0Element.host_source without host_id: the reader that "
                    "answered must have produced a host id")
        if self.unique_id is not None:
            _identity_text(self.unique_id, "L0Element.unique_id")
        _optional_string(self.load_orient_to, "L0Element.load_orient_to")
        for имя, значение in (("load_uniform", self.load_uniform),
                              ("load_projected", self.load_projected),
                              ("load_hosted", self.load_hosted),
                              ("load_reaction", self.load_reaction)):
            if значение is not None and not isinstance(значение, bool):
                raise L0SchemaError(f"L0Element.{имя} must be a bool or null")
        for имя, вектор in (("load_p0_mm", self.load_p0_mm),
                            ("load_p1_mm", self.load_p1_mm),
                            ("load_force_n_per_m", self.load_force_n_per_m),
                            ("load_force_n", self.load_force_n),
                            ("load_moment_nm", self.load_moment_nm),
                            ("load_force_n_per_m2", self.load_force_n_per_m2)):
            _optional_vec(вектор, 3, f"L0Element.{имя}")
        if self.load_ref_points is not None:
            if not isinstance(self.load_ref_points, int) \
                    or isinstance(self.load_ref_points, bool) \
                    or self.load_ref_points < 1:
                raise L0SchemaError(
                    "L0Element.load_ref_points must be a positive int or null")
        if self.load_area_loops_mm is not None:
            if not isinstance(self.load_area_loops_mm, tuple):
                raise L0SchemaError(
                    "L0Element.load_area_loops_mm must be a tuple of loops")
            for н, кольцо in enumerate(self.load_area_loops_mm):
                if not isinstance(кольцо, tuple) or len(кольцо) < 3:
                    raise L0SchemaError(
                        f"L0Element.load_area_loops_mm[{н}]: кольцо площадной "
                        "нагрузки — не меньше трёх точек")
                for м, точка in enumerate(кольцо):
                    _optional_vec(
                        точка, 3, f"L0Element.load_area_loops_mm[{н}][{м}]")
        if self.load_case_name is not None and self.load_case_id is None:
            # A name without an id is a corrupted stream: capture writes
            # the pair in one move.
            raise L0SchemaError(
                "L0Element.load_case_name without load_case_id: the reader "
                "that answered must have produced both")
        if self.opening_is_rect is not None \
                and not isinstance(self.opening_is_rect, bool):
            raise L0SchemaError(
                "L0Element.opening_is_rect must be a bool or null")
        if self.opening_boundary_mm is not None:
            if self.opening_is_rect is None:
                raise L0SchemaError(
                    "L0Element.opening_boundary_mm without opening_is_rect: "
                    "the reader that answered must have produced both")
            if not isinstance(self.opening_boundary_mm, tuple):
                raise L0SchemaError(
                    "L0Element.opening_boundary_mm must be a tuple or null")
            if self.opening_is_rect and len(self.opening_boundary_mm) != 2:
                raise L0SchemaError(
                    "a rectangular opening boundary is exactly two corners, "
                    f"got {len(self.opening_boundary_mm)}")
            if not self.opening_is_rect and len(self.opening_boundary_mm) < 3:
                raise L0SchemaError(
                    "a profile opening boundary needs at least three points, "
                    f"got {len(self.opening_boundary_mm)}")
            for индекс, точка in enumerate(self.opening_boundary_mm):
                _optional_vec(
                    точка, 3, f"L0Element.opening_boundary_mm[{индекс}]")
        if self.flex_path_mm is not None:
            if not isinstance(self.flex_path_mm, tuple) \
                    or len(self.flex_path_mm) < 2:
                raise L0SchemaError(
                    "L0Element.flex_path_mm must be a tuple of at least two "
                    "points or null: Points includes the end points, so a "
                    "shorter path is a broken stream, not a poor row")
            for индекс, точка in enumerate(self.flex_path_mm):
                _optional_vec(точка, 3, f"L0Element.flex_path_mm[{индекс}]")
        if self.is_placeholder is not None \
                and not isinstance(self.is_placeholder, bool):
            # A string instead of a boolean is a corrupted stream:
            # `bool("false")` is true, and one such parse would silently
            # declare every placeholder real.
            raise L0SchemaError(
                "L0Element.is_placeholder must be a bool or null")
        if self.line_owner_kind is not None:
            if not isinstance(self.line_owner_kind, LineOwner):
                raise L0SchemaError(
                    "L0Element.line_owner_kind must be a LineOwner or null")
            # An owner without its own id, and an id without an owner, is
            # a corrupted stream, not a sparse row: the capturer writes
            # the pair in one assignment. The refusal is by name, as the
            # file's header requires of any TIGHTENING.
            if self.line_owner_kind in (LineOwner.VIEW, LineOwner.SKETCH_PLANE):
                if self.line_owner_id is None:
                    raise L0SchemaError(
                        "L0Element.line_owner_kind names an owner but "
                        "line_owner_id is absent")
            elif self.line_owner_id is not None:
                raise L0SchemaError(
                    "L0Element.line_owner_id without an owner: "
                    f"line_owner_kind is {self.line_owner_kind.value}")
            _optional_string(self.line_owner_id, "L0Element.line_owner_id")
        elif self.line_owner_id is not None:
            raise L0SchemaError(
                "L0Element.line_owner_id without line_owner_kind: an id "
                "whose provenance was never recorded is not a measurement")
        if self.geom_kind is GeometryKind.CURVE:
            if self.p0_mm is None or self.p1_mm is None:
                raise L0SchemaError("curve geometry requires p0_mm and p1_mm")
            if self.rotation_deg is not None:
                raise L0SchemaError("curve geometry must not carry rotation_deg")
        elif self.geom_kind is GeometryKind.POINT:
            if self.p0_mm is None or self.p1_mm is not None:
                raise L0SchemaError("point geometry requires only p0_mm")
            # A point's rotation is OPTIONAL — see the same invariant and
            # its cost in geometry_store.py: for rooms, zones, groups and
            # model text, `LocationPoint.Rotation` is unsupported per
            # Autodesk's documentation and throws, and requiring the pair
            # was making emission lose the point as well (12 369 rooms and
            # 566 zones across four buildings — not a single point across
            # the whole run history).
        elif any(value is not None for value in (
                self.p0_mm, self.p1_mm, self.rotation_deg)):
            raise L0SchemaError(
                "bbox_only geometry must not carry point/curve fields")

    def to_dict(self) -> dict[str, Any]:
        row = {
            "element_id": self.element_id,
            "category": self.category,
            "category_ru": self.category_ru,
            "type_id": self.type_id,
            "type_name": self.type_name,
            "level_id": self.level_id,
            "level_name": self.level_name,
            "geom_kind": self.geom_kind.value,
            "p0_mm": list(self.p0_mm) if self.p0_mm is not None else None,
            "p1_mm": list(self.p1_mm) if self.p1_mm is not None else None,
            "rotation_deg": self.rotation_deg,
            "bbox_min_mm": (
                list(self.bbox_min_mm) if self.bbox_min_mm is not None else None),
            "bbox_max_mm": (
                list(self.bbox_max_mm) if self.bbox_max_mm is not None else None),
            "host_id": self.host_id,
            "params": dict(self.params),
            "design_option": (
                self.design_option.to_dict() if self.design_option else None),
            "phase_created": (
                self.phase_created.to_dict() if self.phase_created else None),
            "workset": self.workset.to_dict() if self.workset else None,
            "curve_kind": (
                self.curve_kind.value if self.curve_kind is not None else None),
            "host_source": (
                self.host_source.value
                if self.host_source is not None else None),
        }
        # Preserve frozen legacy byte shape for objects constructed without
        # the new capture. Fresh extraction always writes the key.
        if self.unique_id is not None:
            row["unique_id"] = self.unique_id
        # The key is written ONLY when it was captured: absence is
        # required to read as "not captured," and writing `null` would
        # take this state away from the field.
        if self.line_owner_kind is not None:
            row["line_owner_kind"] = self.line_owner_kind.value
            row["line_owner_id"] = self.line_owner_id
        # Under the same law: no key means NOT MEASURED. Writing `null`
        # would take the field's third state away.
        if self.is_placeholder is not None:
            row["is_placeholder"] = self.is_placeholder
        if self.flex_path_mm is not None:
            row["flex_path_mm"] = [list(точка) for точка in self.flex_path_mm]
        if self.opening_is_rect is not None:
            row["opening_is_rect"] = self.opening_is_rect
        if self.opening_boundary_mm is not None:
            row["opening_boundary_mm"] = [
                list(точка) for точка in self.opening_boundary_mm]
        for имя, вектор in (("load_p0_mm", self.load_p0_mm),
                            ("load_p1_mm", self.load_p1_mm),
                            ("load_force_n_per_m", self.load_force_n_per_m),
                            ("load_force_n", self.load_force_n),
                            ("load_moment_nm", self.load_moment_nm),
                            ("load_force_n_per_m2", self.load_force_n_per_m2)):
            if вектор is not None:
                row[имя] = list(вектор)
        if self.load_ref_points is not None:
            row["load_ref_points"] = self.load_ref_points
        if self.load_area_loops_mm is not None:
            row["load_area_loops_mm"] = [
                [list(т) for т in кольцо] for кольцо in self.load_area_loops_mm]
        for имя, значение in (("load_case_id", self.load_case_id),
                              ("load_case_name", self.load_case_name),
                              ("load_uniform", self.load_uniform),
                              ("load_projected", self.load_projected),
                              ("load_hosted", self.load_hosted),
                              ("load_reaction", self.load_reaction),
                              ("load_orient_to", self.load_orient_to)):
            if значение is not None:
                row[имя] = значение
        return row

    @classmethod
    def from_dict(cls, value: Any) -> "L0Element":
        row = _mapping(value, "element")
        _require_fields(row, (
            "element_id", "category", "category_ru", "type_id", "type_name",
            "level_id", "level_name", "geom_kind", "p0_mm", "p1_mm",
            "rotation_deg", "bbox_min_mm", "bbox_max_mm", "host_id", "params",
        ), "element")
        try:
            geom_kind = GeometryKind(row.get("geom_kind"))
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"element.geom_kind is invalid: {row.get('geom_kind')!r}") from exc
        raw_line_owner = row.get("line_owner_kind")
        if raw_line_owner is None:
            line_owner_kind = None
        else:
            try:
                line_owner_kind = LineOwner(raw_line_owner)
            except (TypeError, ValueError) as exc:
                raise L0SchemaError(
                    "element.line_owner_kind is invalid: "
                    f"{raw_line_owner!r}") from exc
        raw_placeholder = row.get("is_placeholder")
        if raw_placeholder is not None and not isinstance(raw_placeholder, bool):
            # The refusal is by name and EARLY: the string "false" is true
            # under bool(), and letting it through silently would declare
            # a placeholder real.
            raise L0SchemaError(
                "element.is_placeholder is invalid: "
                f"{raw_placeholder!r} (bool or absent)")
        raw_path = row.get("flex_path_mm")
        if raw_path is None:
            flex_path_mm = None
        else:
            if not isinstance(raw_path, list):
                raise L0SchemaError(
                    "element.flex_path_mm must be an array of [x,y,z] or absent")
            flex_path_mm = tuple(
                _vec(точка, 3, f"element.flex_path_mm[{индекс}]")
                for индекс, точка in enumerate(raw_path))
        raw_rect = row.get("opening_is_rect")
        if raw_rect is not None and not isinstance(raw_rect, bool):
            raise L0SchemaError(
                f"element.opening_is_rect is invalid: {raw_rect!r}")
        raw_boundary = row.get("opening_boundary_mm")
        if raw_boundary is None:
            opening_boundary_mm = None
        else:
            if not isinstance(raw_boundary, list):
                raise L0SchemaError(
                    "element.opening_boundary_mm must be an array of [x,y,z]")
            opening_boundary_mm = tuple(
                _vec(точка, 3, f"element.opening_boundary_mm[{индекс}]")
                for индекс, точка in enumerate(raw_boundary))
        def _необяз_вектор(ключ):
            сырое = row.get(ключ)
            return None if сырое is None else _vec(сырое, 3, f"element.{ключ}")

        for _ключ in ("load_uniform", "load_projected",
                      "load_hosted", "load_reaction"):
            if row.get(_ключ) is not None and not isinstance(row[_ключ], bool):
                raise L0SchemaError(f"element.{_ключ} is invalid: {row[_ключ]!r}")
        return cls(
            load_p0_mm=_необяз_вектор("load_p0_mm"),
            load_p1_mm=_необяз_вектор("load_p1_mm"),
            load_force_n_per_m=_необяз_вектор("load_force_n_per_m"),
            load_force_n=_необяз_вектор("load_force_n"),
            load_moment_nm=_необяз_вектор("load_moment_nm"),
            load_force_n_per_m2=_необяз_вектор("load_force_n_per_m2"),
            load_ref_points=row.get("load_ref_points"),
            load_area_loops_mm=(
                None if row.get("load_area_loops_mm") is None else tuple(
                    tuple(_vec(т, 3, f"element.load_area_loops_mm[{н}][{м}]")
                          for м, т in enumerate(кольцо))
                    for н, кольцо in enumerate(row["load_area_loops_mm"]))),
            load_case_id=_optional_string(
                row.get("load_case_id"), "element.load_case_id"),
            load_case_name=_optional_string(
                row.get("load_case_name"), "element.load_case_name"),
            load_uniform=row.get("load_uniform"),
            load_projected=row.get("load_projected"),
            load_hosted=row.get("load_hosted"),
            load_reaction=row.get("load_reaction"),
            load_orient_to=_optional_string(
                row.get("load_orient_to"), "element.load_orient_to"),
            opening_is_rect=raw_rect,
            opening_boundary_mm=opening_boundary_mm,
            flex_path_mm=flex_path_mm,
            is_placeholder=raw_placeholder,
            line_owner_kind=line_owner_kind,
            line_owner_id=_optional_string(
                row.get("line_owner_id"), "element.line_owner_id"),
            element_id=_nonempty_string(
                row.get("element_id"), "element.element_id"),
            category=_nonempty_string(row.get("category"), "element.category"),
            category_ru=_string(row.get("category_ru"), "element.category_ru"),
            type_id=_string(row.get("type_id"), "element.type_id"),
            type_name=_string(row.get("type_name"), "element.type_name"),
            level_id=_optional_string(row.get("level_id"), "element.level_id"),
            level_name=_optional_string(row.get("level_name"), "element.level_name"),
            geom_kind=geom_kind,
            p0_mm=_optional_vec(
                row.get("p0_mm"), 3, "element.p0_mm"),  # type: ignore[arg-type]
            p1_mm=_optional_vec(
                row.get("p1_mm"), 3, "element.p1_mm"),  # type: ignore[arg-type]
            rotation_deg=(None if row.get("rotation_deg") is None else
                          _finite_number(
                              row.get("rotation_deg"), "element.rotation_deg")),
            bbox_min_mm=_optional_vec(
                row.get("bbox_min_mm"), 3,
                "element.bbox_min_mm"),  # type: ignore[arg-type]
            bbox_max_mm=_optional_vec(
                row.get("bbox_max_mm"), 3,
                "element.bbox_max_mm"),  # type: ignore[arg-type]
            host_id=_optional_string(row.get("host_id"), "element.host_id"),
            params=_mapping(row.get("params"), "element.params"),
            design_option=(
                NamedReference.from_dict(
                    row["design_option"], "element.design_option")
                if row.get("design_option") is not None else None),
            phase_created=(
                NamedReference.from_dict(
                    row["phase_created"], "element.phase_created")
                if row.get("phase_created") is not None else None),
            workset=(
                NamedReference.from_dict(row["workset"], "element.workset")
                if row.get("workset") is not None else None),
            curve_kind=_optional_enum(
                LocationCurveKind, row.get("curve_kind"), "element.curve_kind"),
            host_source=_optional_enum(
                HostSource, row.get("host_source"), "element.host_source"),
            unique_id=(
                _identity_text(row.get("unique_id"), "element.unique_id")
                if row.get("unique_id") is not None else None),
        )


@dataclass(frozen=True, slots=True)
class LinkSummary:
    element_id: str
    name: str
    loaded: bool
    element_count: int | None
    bbox_min_mm: Vec3 | None
    bbox_max_mm: Vec3 | None
    discipline: str
    # None is the readable legacy state. Fresh metadata always carries a
    # typed identity result, including named gaps for unloaded links.
    identity: L0LinkIdentity | None = None
    # Child-document coordinates -> this source-document coordinates.  It is
    # independent from identity: an unloaded link can still have a placement,
    # while a known linked document can still lack trustworthy frame evidence.
    transform: FederationTransformEvidence | None = None

    def __post_init__(self) -> None:
        _nonempty_string(self.element_id, "LinkSummary.element_id")
        if not isinstance(self.name, str):
            raise L0SchemaError("LinkSummary.name must be a string")
        if not isinstance(self.loaded, bool):
            raise L0SchemaError("LinkSummary.loaded must be boolean")
        if (self.element_count is not None
                and (isinstance(self.element_count, bool)
                     or not isinstance(self.element_count, int)
                     or self.element_count < 0)):
            raise L0SchemaError(
                "LinkSummary.element_count must be non-negative or null")
        _optional_vec(self.bbox_min_mm, 3, "LinkSummary.bbox_min_mm")
        _optional_vec(self.bbox_max_mm, 3, "LinkSummary.bbox_max_mm")
        _bbox_pair(self.bbox_min_mm, self.bbox_max_mm, "LinkSummary")
        _nonempty_string(self.discipline, "LinkSummary.discipline")
        if self.identity is not None:
            if not isinstance(self.identity, L0LinkIdentity):
                raise L0SchemaError(
                    "LinkSummary.identity must be L0LinkIdentity or null")
            if (not self.loaded
                    and self.identity.linked_document_identity is not None):
                raise L0SchemaError(
                    "unloaded link cannot claim linked document identity")
            if (not self.loaded
                    and IdentityGap.LINKED_DOCUMENT_UNAVAILABLE
                    not in self.identity.gaps):
                raise L0SchemaError(
                    "unloaded link identity must name linked_document_unavailable")
            if (self.loaded
                    and IdentityGap.LINKED_DOCUMENT_UNAVAILABLE
                    in self.identity.gaps):
                raise L0SchemaError(
                    "loaded link cannot claim linked_document_unavailable")
        if (self.transform is not None
                and not isinstance(
                    self.transform, FederationTransformEvidence)):
            raise L0SchemaError(
                "LinkSummary.transform must be typed or null")

    def to_dict(self) -> dict[str, Any]:
        row = {
            "element_id": self.element_id,
            "name": self.name,
            "loaded": self.loaded,
            "element_count": self.element_count,
            "bbox_min_mm": (
                list(self.bbox_min_mm) if self.bbox_min_mm is not None else None),
            "bbox_max_mm": (
                list(self.bbox_max_mm) if self.bbox_max_mm is not None else None),
            "discipline": self.discipline,
        }
        if self.identity is not None:
            row["identity"] = self.identity.to_dict()
        if self.transform is not None:
            row["transform"] = self.transform.to_dict()
        return row

    @classmethod
    def from_dict(cls, value: Any) -> "LinkSummary":
        row = _mapping(value, "link")
        _require_fields(row, (
            "element_id", "name", "loaded", "element_count",
            "bbox_min_mm", "bbox_max_mm", "discipline",
        ), "link")
        loaded = row.get("loaded")
        if not isinstance(loaded, bool):
            raise L0SchemaError("link.loaded must be boolean")
        count = row.get("element_count")
        if (count is not None
                and (isinstance(count, bool) or not isinstance(count, int))):
            raise L0SchemaError(
                "link.element_count must be an integer or null")
        return cls(
            element_id=_nonempty_string(
                row.get("element_id"), "link.element_id"),
            name=_string(row.get("name"), "link.name"),
            loaded=loaded,
            element_count=count,
            bbox_min_mm=_optional_vec(
                row.get("bbox_min_mm"), 3,
                "link.bbox_min_mm"),  # type: ignore[arg-type]
            bbox_max_mm=_optional_vec(
                row.get("bbox_max_mm"), 3,
                "link.bbox_max_mm"),  # type: ignore[arg-type]
            discipline=_nonempty_string(
                row.get("discipline"), "link.discipline"),
            identity=(
                L0LinkIdentity.from_dict(row["identity"])
                if row.get("identity") is not None else None),
            transform=(
                FederationTransformEvidence.from_dict(
                    row["transform"], "link.transform")
                if row.get("transform") is not None else None),
        )


#: Six outcomes of reading one section parameter (code review #12). The
#: order matters: it is also the order of the slots in the generated C#.
SECTION_RECEIPT_OUTCOMES = (
    "instance_hit", "type_hit", "not_applicable", "no_value",
    "wrong_storage", "exception",
)


@dataclass(frozen=True, slots=True)
class RouteSkip:
    """How many times the probe was NOT ASKED of this category, per the
    routing table.

    🔴 WHY A SEPARATE ROW, NOT A SEVENTH RECEIPT OUTCOME. The census law
    says: the sum of the six outcomes equals `extracted_count`. It is
    load-bearing — it is what catches a probe that forgot to report. A
    route, though, is not a "reading outcome" but the ABSENCE of reading,
    and writing it in as a seventh term would mean conflating "we asked,
    and here's what came back" with "we never asked at all."

    So the route keeps its OWN count, and a name cut off for a category
    has no receipt at all. The pair "no receipt + a route row exists" is
    the complete description: it shows both that it wasn't asked, and how
    many times.

    `audited` is how many elements the probe was asked of anyway, on a
    sample basis. Zero here would mean a route with no safety check, and
    that is a separate fact.
    """

    parameter: str
    skipped: int = 0
    audited: int = 0

    def __post_init__(self) -> None:
        _nonempty_string(self.parameter, "route_skip.parameter")
        for name in ("skipped", "audited"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise L0SchemaError(
                    f"route_skip.{name} must be a non-negative integer")

    def total(self) -> int:
        """How many elements passed this probe by, plus how many were
        checked."""
        return self.skipped + self.audited

    def to_dict(self) -> dict[str, Any]:
        return {"parameter": self.parameter,
                "skipped": self.skipped, "audited": self.audited}

    @classmethod
    def from_dict(cls, value: Any) -> "RouteSkip":
        row = _mapping(value, "route_skip")
        _require_fields(row, ("parameter", "skipped", "audited"), "route_skip")
        return cls(parameter=_nonempty_string(row["parameter"],
                                              "route_skip.parameter"),
                   skipped=row["skipped"], audited=row["audited"])


@dataclass(frozen=True, slots=True)
class SectionReceipt:
    """The fail-open receipt for one section parameter on one category.

    Before it, `null`, `HasValue=false`, a foreign `StorageType`, and an
    exception all collapsed into ONE missing key: "this class has no such
    parameter" was indistinguishable from "the parameter exists but could
    not be read." Measured v13: width was captured for 992 walls out of
    1189, and all 197 misses coincide with curtain-wall carriers — a
    perfect match, but the code had no way to PROVE it.

    The counters are aggregate (per category × parameter), so the
    receipt's cost does not depend on the model's size.
    """

    parameter: str
    instance_hit: int = 0
    type_hit: int = 0
    not_applicable: int = 0
    no_value: int = 0
    wrong_storage: int = 0
    exception: int = 0

    def __post_init__(self) -> None:
        _nonempty_string(self.parameter, "section_receipt.parameter")
        for name in SECTION_RECEIPT_OUTCOMES:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise L0SchemaError(
                    f"section_receipt.{name} must be a non-negative integer")

    def total(self) -> int:
        """How many elements were polled for this parameter. This exact
        number is required to match the category's `extracted_count` —
        otherwise the census doesn't add up."""
        return sum(getattr(self, name) for name in SECTION_RECEIPT_OUTCOMES)

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"parameter": self.parameter}
        for name in SECTION_RECEIPT_OUTCOMES:
            row[name] = getattr(self, name)
        return row

    @classmethod
    def from_dict(cls, value: Any) -> "SectionReceipt":
        row = _mapping(value, "section_receipt")
        _require_fields(row, ("parameter",) + SECTION_RECEIPT_OUTCOMES,
                        "section_receipt")
        return cls(
            parameter=_nonempty_string(
                row.get("parameter"), "section_receipt.parameter"),
            **{name: row.get(name) for name in SECTION_RECEIPT_OUTCOMES},
        )


@dataclass(frozen=True, slots=True)
class CategoryStatus:
    category: str
    state: CategoryState
    extracted_count: int
    expected_count: int | None = None
    error: str | None = None
    #: Section-reading receipts (code review #12). `None` means the
    #: stream was written BEFORE the receipts wave and asserts NOTHING
    #: about reading outcomes; an empty tuple means not a single page was
    #: received. Six zeros in place of `None` would be an assertion the
    #: old stream never made.
    section_receipts: tuple["SectionReceipt", ...] | None = None
    #: ROUTE rows: probes that were never asked of this category at all.
    #: `None` means the stream was written BEFORE routing and asserts
    #: NOTHING about cutoffs; an empty tuple means a route existed and
    #: cut off no name at all. The difference is load-bearing: without
    #: it, "the name is absent from the receipts" would read as "the
    #: probe forgot to report," that is, as a defect instead of a
    #: decision.
    route_skipped: tuple["RouteSkip", ...] | None = None

    def __post_init__(self) -> None:
        _nonempty_string(self.category, "CategoryStatus.category")
        if not isinstance(self.state, CategoryState):
            raise L0SchemaError("CategoryStatus.state must be a CategoryState")
        if (isinstance(self.extracted_count, bool)
                or not isinstance(self.extracted_count, int)
                or self.extracted_count < 0):
            raise L0SchemaError(
                "CategoryStatus.extracted_count must be non-negative")
        if (self.expected_count is not None
                and (isinstance(self.expected_count, bool)
                     or not isinstance(self.expected_count, int)
                     or self.expected_count < 0)):
            raise L0SchemaError(
                "CategoryStatus.expected_count must be non-negative or null")
        _optional_string(self.error, "CategoryStatus.error")
        if self.state is CategoryState.COMPLETE:
            if self.expected_count is None:
                raise L0SchemaError(
                    "complete category status requires expected_count")
            if self.extracted_count != self.expected_count:
                raise L0SchemaError(
                    "complete category status count does not match expected")
            if self.error is not None:
                raise L0SchemaError(
                    "complete category status cannot carry an error")
        elif self.error is None:
            raise L0SchemaError(
                "partial category status requires an error")
        if self.route_skipped is not None:
            if not isinstance(self.route_skipped, tuple):
                raise L0SchemaError(
                    "CategoryStatus.route_skipped must be a tuple or null")
            names = [r.parameter for r in self.route_skipped]
            if names != sorted(names) or len(names) != len(set(names)):
                raise L0SchemaError(
                    "route skips must be unique and sorted by parameter")
            for skip in self.route_skipped:
                if skip.total() != self.extracted_count:
                    raise L0SchemaError(
                        f"маршрут не сходится: {skip.parameter} обошёл "
                        f"{skip.skipped} и проверил {skip.audited} элементов, "
                        f"извлечено {self.extracted_count}")
            # 🔴 THE INTERSECTION OF THE TWO CENSUSES IS NOT FORBIDDEN, IT
            # IS REQUIRED TO ADD UP. The first version of this law forbade
            # a name from being both cut off and polled — and it was
            # wrong: a cut-off name IS asked on a sample basis, of every
            # `AUDIT_EVERY`-th element, which is exactly what the safety
            # check exists for. So such a name has both rows, and what
            # must be checked is AGREEMENT, not absence.
            if self.section_receipts:
                by_name = {r.parameter: r for r in self.section_receipts}
                for skip in self.route_skipped:
                    receipt = by_name.get(skip.parameter)
                    if receipt is not None and receipt.total() != skip.audited:
                        raise L0SchemaError(
                            f"две переписи расходятся по {skip.parameter}: "
                            f"маршрут проверил {skip.audited}, квитанция "
                            f"насчитала {receipt.total()}")
        if self.section_receipts is not None:
            if not isinstance(self.section_receipts, tuple):
                raise L0SchemaError(
                    "CategoryStatus.section_receipts must be a tuple or null")
            names = [r.parameter for r in self.section_receipts]
            if names != sorted(names) or len(names) != len(set(names)):
                raise L0SchemaError(
                    "section receipts must be unique and sorted by parameter")
            # THE CENSUS LAW, GENERALIZED TO THE ROUTE: polled plus CUT
            # OFF is required to give all extracted. Without the second
            # term, the route would break the very law it was written
            # for — and that law is what catches a probe that forgot to
            # report, and it must not be lost.
            skipped_by = {s.parameter: s.skipped
                          for s in (self.route_skipped or ())}
            for receipt in self.section_receipts:
                asked = receipt.total() + skipped_by.get(receipt.parameter, 0)
                if asked != self.extracted_count:
                    raise L0SchemaError(
                        f"перепись сечений не сходится: "
                        f"{receipt.parameter} опросил {receipt.total()} "
                        f"плюс отсечено {skipped_by.get(receipt.parameter, 0)}, "
                        f"извлечено {self.extracted_count}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "state": self.state.value,
            "extracted_count": self.extracted_count,
            "expected_count": self.expected_count,
            "error": self.error,
            "route_skipped": (
                None if self.route_skipped is None
                else [row.to_dict() for row in self.route_skipped]),
            "section_receipts": (
                None if self.section_receipts is None
                else [r.to_dict() for r in self.section_receipts]),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CategoryStatus":
        row = _mapping(value, "category_status")
        _require_fields(row, (
            "category", "state", "extracted_count", "expected_count", "error",
        ), "category_status")
        try:
            state = CategoryState(row.get("state"))
        except (TypeError, ValueError) as exc:
            raise L0SchemaError(
                f"category_status.state is invalid: {row.get('state')!r}") from exc
        extracted = row.get("extracted_count")
        expected = row.get("expected_count")
        if isinstance(extracted, bool) or not isinstance(extracted, int):
            raise L0SchemaError(
                "category_status.extracted_count must be an integer")
        if (expected is not None
                and (isinstance(expected, bool) or not isinstance(expected, int))):
            raise L0SchemaError(
                "category_status.expected_count must be an integer or null")
        raw_receipts = row.get("section_receipts")
        if raw_receipts is None:
            receipts = None
        else:
            if not isinstance(raw_receipts, list):
                raise L0SchemaError(
                    "category_status.section_receipts must be an array or null")
            receipts = tuple(
                SectionReceipt.from_dict(item) for item in raw_receipts)
        # A missing key and an empty list are DIFFERENT facts: the first
        # says "the stream predates routing," the second "a route existed
        # and cut off nothing." So `None` here is not replaced by an
        # empty tuple.
        raw_skips = row.get("route_skipped")
        if raw_skips is None:
            skips = None
        else:
            if not isinstance(raw_skips, list):
                raise L0SchemaError(
                    "category_status.route_skipped must be an array or null")
            skips = tuple(RouteSkip.from_dict(item) for item in raw_skips)
        return cls(
            category=_nonempty_string(
                row.get("category"), "category_status.category"),
            state=state,
            extracted_count=extracted,
            expected_count=expected,
            error=_optional_string(row.get("error"), "category_status.error"),
            section_receipts=receipts,
            route_skipped=skips,
        )


@dataclass(frozen=True, slots=True)
class CensusEntry:
    """One row of a document census (§18.1): category → count.

    ``key`` is the BuiltInCategory (or ``category_id:<n>`` for a category
    absent from the enum, or ``no_category``). It is the ONLY thing that
    WORKS as a key: §18.5 forbids a localized name as a rule's sole key,
    so ``name`` is a reference column for humans and decides nothing.

    ``count`` is how many such elements one full-model pass counted.
    Neither geometry nor parameters: the census is required to stay
    cheap, so it runs ALWAYS, not just "on small models."
    """

    key: str
    name: str
    count: int

    def __post_init__(self) -> None:
        _nonempty_string(self.key, "census.key")
        if not isinstance(self.name, str):
            raise L0SchemaError("census.name must be a string")
        if isinstance(self.count, bool) or not isinstance(self.count, int) \
                or self.count < 0:
            raise L0SchemaError("census.count must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "count": self.count}

    @classmethod
    def from_dict(cls, value: Any) -> "CensusEntry":
        row = _mapping(value, "census")
        _require_fields(row, ("key", "count"), "census")
        return cls(
            key=_nonempty_string(row.get("key"), "census.key"),
            name=_string(row.get("name") or "", "census.name"),
            count=row.get("count"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class L0Document:
    doc_name: str
    revit_version: str
    units: str
    change_stamp: str
    levels: tuple[LevelInfo, ...]
    grids: tuple[GridInfo, ...]
    rooms: tuple[RoomInfo, ...]
    project_info: ProjectInfo
    elements: tuple[L0Element, ...] = ()
    category_status: tuple[CategoryStatus, ...] = ()
    links: tuple[LinkSummary, ...] = ()
    # Worksharing state. MEASURED 27.07 (an electrical training model,
    # SKLNK R2026): the document was opened with 17 out of 18 worksets
    # closed, and the collectors honestly returned what they saw — 11
    # elements instead of 2016. Extraction would have gone through with
    # not a single sign of incompleteness, and coverage over such an L0
    # would have described the file-opening dialog, not the compiler.
    #
    # The default values keep the fields compatible with frozen L0 1.0:
    # its rows do not contain them, and their absence means "not
    # measured," not "there are no worksets."
    worksharing: bool | None = None
    worksets: tuple[dict, ...] = ()
    # 🔴 None = NOT MEASURED. Before 25.08, both fields defaulted to
    # False/0, and a stream WITHOUT these keys answered "the model is
    # complete" — exactly the outcome these fields were set up to forbid
    # (measured 27.07: 17 out of 18 worksets closed, 11 elements instead
    # of 2016). Verified on sklnk_eom_r26_20260727 — THE VERY document
    # from that measurement: its header has no such keys.
    worksets_closed: int | None = None
    # §18.1: a census of the whole document. An empty tuple means the
    # census DID NOT HAPPEN (L0 was captured before this wave, or the
    # bridge did not return one), not "the document has zero elements":
    # telling these two states apart lives in decompile.census and is
    # required to stay separate — otherwise a missing denominator looks
    # like full coverage.
    census: tuple["CensusEntry", ...] | None = None
    # Trusted production extraction context. None is the legacy state and is
    # intentionally non-authoritative downstream.
    identity: L0IdentityMetadata | None = None
    # Current source-document coordinates -> federation-root coordinates.
    # Optional only for historical streams; new extraction always measures or
    # emits a typed gap.
    federation_transform: FederationTransformEvidence | None = None

    @property
    def census_total(self) -> int:
        """How many elements the census counted (0 if there was none)."""
        return sum(entry.count for entry in (self.census or ()))

    @property
    def has_census(self) -> bool:
        return bool(self.census)

    @property
    def census_taken(self) -> bool:
        """Whether a census was taken AT ALL — separate from what it
        counted.

        🔴 The field's comment says verbatim: an empty tuple means the
        census DID NOT HAPPEN, not "the document has zero elements."
        Before 25.08 these two facts arrived as one value, and
        `UnloadedElements` could not fire on a snapshot with no census:
        measured across 40 readable snapshots — four have no census
        despite a nonempty stream, including sklnk_eom_r26_20260727 with
        1916 elements.
        """
        return self.census is not None

    @property
    def is_partial_read(self) -> bool:
        """Whether the document was read KNOWINGLY incomplete.

        Under its own name, not a bare number: the caller needs an
        answer to the question "can this L0 be trusted," and should not
        have to derive it themselves every time.
        """
        return bool(self.worksharing) and (self.worksets_closed or 0) > 0

    @property
    def partial_read_measured(self) -> bool:
        """Whether separation was measured at all — a SECOND question,
        not a shade of the first.

        `is_partial_read` answers "the snapshot is KNOWINGLY incomplete"
        and is read as a boolean in forty places; its meaning and type
        never changed. What was missing was a name for the question "was
        it measured at all," and the tree had already named this gap:
        ground.py — "is_partial_read measures closed worksets, yet gets
        read as 'is the snapshot complete'."

        Before 25.08 the fix stood OUTSIDE: serving.py wrote
        `measured=bool(metadata.worksharing)`, which meant a
        single-user model (worksharing=False, honestly measured) got
        declared unmeasured. Two carriers of one quantity drifted apart
        silently.
        """
        return self.worksharing is not None

    def __post_init__(self) -> None:
        _nonempty_string(self.doc_name, "L0Document.doc_name")
        _nonempty_string(self.revit_version, "L0Document.revit_version")
        if self.units != L0_UNITS:
            raise L0SchemaError(
                f"L0Document.units must be {L0_UNITS!r}, got {self.units!r}")
        _nonempty_string(self.change_stamp, "L0Document.change_stamp")
        for field_name, collection, expected_type in (
            ("levels", self.levels, LevelInfo),
            ("grids", self.grids, GridInfo),
            ("rooms", self.rooms, RoomInfo),
            ("elements", self.elements, L0Element),
            ("category_status", self.category_status, CategoryStatus),
            ("links", self.links, LinkSummary),
            ("census", self.census or (), CensusEntry),
        ):
            # THE ONLY LEGITIMATE READ OF THE HEADER. `UnloadedElements` is empty BY
            # CONSTRUCTION and typed; checking it by iteration means asking
            # the guard about the very thing it guards. All OTHER
            # readers still get the named refusal.
            if isinstance(collection, UnloadedElements):
                continue
            if not isinstance(collection, tuple) or not all(
                    isinstance(item, expected_type) for item in collection):
                raise L0SchemaError(
                    f"L0Document.{field_name} must be a tuple of "
                    f"{expected_type.__name__}")
        if not isinstance(self.project_info, ProjectInfo):
            raise L0SchemaError(
                "L0Document.project_info must be a ProjectInfo")
        if (self.identity is not None
                and not isinstance(self.identity, L0IdentityMetadata)):
            raise L0SchemaError(
                "L0Document.identity must be L0IdentityMetadata or null")
        if (self.federation_transform is not None
                and not isinstance(
                    self.federation_transform, FederationTransformEvidence)):
            raise L0SchemaError(
                "L0Document.federation_transform must be typed or null")
        if tuple(sorted(self.levels, key=lambda level: level.elevation_mm)) != self.levels:
            raise L0SchemaError("L0Document.levels must be sorted by elevation")
        for field_name, identifiers in (
            ("levels", [level.id for level in self.levels]),
            ("grids", [grid.id for grid in self.grids]),
            ("rooms", [room.id for room in self.rooms]),
            ("elements", [element.element_id for element in _own(self.elements)]),
            ("links", [link.element_id for link in self.links]),
        ):
            if len(identifiers) != len(set(identifiers)):
                raise L0SchemaError(
                    f"L0Document.{field_name} contains duplicate ids")
        categories = [status.category for status in self.category_status]
        if len(categories) != len(set(categories)):
            raise L0SchemaError("L0Document.category_status contains duplicates")
        census_keys = [entry.key for entry in (self.census or ())]
        if len(census_keys) != len(set(census_keys)):
            # A duplicate key would mean one category was counted
            # twice, and the §18.1 identity would match against the wrong denominator.
            raise L0SchemaError("L0Document.census contains duplicate keys")

    def metadata_dict(self) -> dict[str, Any]:
        # §18.4: working-set state is part of the HEADER, not only the
        # full document. The header is the only thing that survives the
        # L0.jsonl write and that every downstream consumer reads (A5, re-lift,
        # the passport). While these three fields lived only in to_dict(), the
        # "a partial model was read" signal was lost between C# and the very first artifact.
        row = {
            "doc_name": self.doc_name,
            "revit_version": self.revit_version,
            "units": self.units,
            "change_stamp": self.change_stamp,
            "levels": [level.to_dict() for level in self.levels],
            "grids": [grid.to_dict() for grid in self.grids],
            "rooms": [room.to_dict() for room in self.rooms],
            "project_info": self.project_info.to_dict(),
            "worksets": list(self.worksets),
            # §18.1: the census is part of the HEADER for the same reason
            # the working sets became one: the header is the only thing that
            # survives the L0.jsonl write and that every downstream consumer reads.
        }
        # 🔴 NOT MEASURED — MEANS THE KEY IS ABSENT. Writing `null` or a default
        # would erase the third state on the very first write-read round-trip,
        # exactly as already happened to `identity` and `federation_transform`.
        if self.worksharing is not None:
            row["worksharing"] = self.worksharing
        if self.worksets_closed is not None:
            row["worksets_closed"] = self.worksets_closed
        # §18.1: the census is part of the HEADER for the same reason the
        # working sets became one: the header is the only thing that survives
        # the L0.jsonl write and that every downstream consumer reads.
        if self.census is not None:
            row["census"] = [entry.to_dict() for entry in self.census]
        if self.identity is not None:
            row["identity"] = self.identity.to_dict()
        if self.federation_transform is not None:
            row["federation_transform"] = self.federation_transform.to_dict()
        return row

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.metadata_dict(),
            "elements": [element.to_dict() for element in _own(self.elements)],
            "category_status": [
                status.to_dict() for status in self.category_status],
            "links": [link.to_dict() for link in self.links],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "L0Document":
        row = _mapping(value, "document")
        _require_fields(row, (
            "doc_name", "revit_version", "units", "change_stamp",
            "levels", "grids", "rooms", "project_info", "elements",
        ), "document")
        levels = row.get("levels")
        grids = row.get("grids")
        rooms = row.get("rooms")
        elements = row.get("elements")
        statuses = row.get("category_status", [])
        links = row.get("links", [])
        census_rows = row.get("census") or []
        for field_name, collection in (
            ("levels", levels), ("grids", grids), ("rooms", rooms),
            ("elements", elements), ("category_status", statuses),
            ("links", links), ("census", census_rows),
        ):
            if not isinstance(collection, list):
                raise L0SchemaError(f"document.{field_name} must be an array")
        return cls(
            doc_name=_nonempty_string(row.get("doc_name"), "document.doc_name"),
            revit_version=_nonempty_string(
                row.get("revit_version"), "document.revit_version"),
            units=_nonempty_string(row.get("units"), "document.units"),
            change_stamp=_nonempty_string(
                row.get("change_stamp"), "document.change_stamp"),
            levels=tuple(LevelInfo.from_dict(item) for item in levels),
            grids=tuple(GridInfo.from_dict(item) for item in grids),
            rooms=tuple(RoomInfo.from_dict(item) for item in rooms),
            project_info=ProjectInfo.from_dict(row.get("project_info", {})),
            elements=tuple(L0Element.from_dict(item) for item in elements),
            category_status=tuple(
                CategoryStatus.from_dict(item) for item in statuses),
            links=tuple(LinkSummary.from_dict(item) for item in links),
            worksharing=(bool(row["worksharing"])
                         if "worksharing" in row else None),
            worksets=tuple(row.get("worksets") or ()),
            worksets_closed=(int(row["worksets_closed"] or 0)
                             if "worksets_closed" in row else None),
            census=(tuple(CensusEntry.from_dict(item)
                          for item in census_rows)
                    if "census" in row else None),
            identity=(
                L0IdentityMetadata.from_dict(row["identity"])
                if row.get("identity") is not None else None),
            federation_transform=(
                FederationTransformEvidence.from_dict(
                    row["federation_transform"],
                    "document.federation_transform")
                if row.get("federation_transform") is not None else None),
        )


def _own(collection):
    """Internal read of the schema ITSELF — the only one the guard yields to.

    The schema must be able to validate and serialize the header; asking the
    guard about the very thing it guards would make the header unbuildable. All
    OTHER readers (105 places in the tree) still get the named refusal.
    """
    return tuple.__iter__(collection) if isinstance(
        collection, UnloadedElements) else collection


class L0HeaderMisread(RuntimeError):
    """THE HEADER WAS MISTAKEN FOR THE DOCUMENT — and this is caught HERE, not in the report."""


class UnloadedElements(tuple):
    """An empty sequence of HEADER elements that REFUSES TO STAY SILENT.

    🔴 WHY A TYPE, NOT A LINE IN THE CANON. The trap "`metadata()` returns the
    header, `elements` is empty BY CONSTRUCTION" is recorded verbatim in the
    root `CLAUDE.md`, in the "CALL-SHAPE TRAPS" list, with its own example
    ("otherwise 0 walls on a building with 695 walls"). **On 2026-08-18 it was
    stepped on THREE TIMES IN ONE DAY** — the topology wave, the honest-comparison
    instrument, and the director, who had read this very list at the start of
    the session:

        rooms 2442 · doors 0   ← on a building with 2096 doors
        rooms 2442 · walls 0   ← on a building with 15,323 walls

    Both times the answer looked LIKE IT WORKED: rooms come through (they're in
    the header), so the table filled in, and the zero was read as a fact about
    the building. This is exactly our named defect — a zero for a quantity the
    instrument doesn't count here.

    THE CONCLUSION, WRITTEN AT NIGHT AND CONFIRMED BY DAY: **the read form does
    not protect.** The document is read once at the start, and the mistake is
    made four hours later, while thinking about something else. So the warning
    must fire AT THE MOMENT OF THE CALL, not at the moment the canon is read.

    HOW THIS IS POSSIBLE HERE AND NOT EVERYWHERE. The header already has
    `census` — the document's census. "Zero elements" WITH "census 115,889" is
    an internal contradiction, and it is visible without any knowledge of the
    caller. An empty document (census 0), however, passes silently and
    legitimately: the refusal catches only the IMPOSSIBLE, not the rare.

    There are **105** readers of `document.elements` in the tree. Guarding each
    one would mean setting up 105 places obliged to agree — our own named
    defect in the cure for our own named defect. Here there is ONE guard, and
    it sits in the type.
    """

    #: 🔴 THE THIRD CASE, MEASURED 2026-08-25. Before this date the guard went
    #: red only when `census_total > 0`. But a census of zero, by the law of
    #: THIS SAME file (see the comment on the `census` field), means "no
    #: census WAS TAKEN," not "the document has zero elements" — and the
    #: docstring above asserted the opposite. Two carriers of one law in one
    #: file, drifted apart silently.
    #:
    #: Measured by the production reader over 40 readable snapshots: on FOUR of
    #: them the census is absent despite a non-empty stream
    #: (sklnk_eom_r26_20260727 — 1916 elements in the stream, sob62_r23_v3/v4/v6).
    #: On these, `len(md.elements) == 0` passed silently — exactly the outcome
    #: the type was written to forbid.
    #:
    #: There are now three cases, and they are DIFFERENT:
    #:   taken, counted >0, elements empty -> CONTRADICTION, refusal
    #:   taken, counted 0                  -> the document is truly empty, silence
    #:   NOT TAKEN                         -> nothing to prove it, refusal with a
    #:                                        DIFFERENT text (canon form 4: a zero
    #:                                        from the corpus without proven
    #:                                        reachability is not a zero)
    def __new__(cls, census_total: int = 0, census_taken: bool = False):
        self = super().__new__(cls, ())
        self.census_total = int(census_total or 0)
        self.census_taken = bool(census_taken)
        return self

    def _refuse(self):
        хвост = (
            "Документ = шапка + `iter_elements()`:\n"
            "    rd = L0JSONLReader(path)\n"
            "    doc = dataclasses.replace(rd.metadata(), "
            "elements=tuple(rd.iter_elements()))")
        if self.census_total:
            raise L0HeaderMisread(
                f"ЭТО ШАПКА, А НЕ ДОКУМЕНТ: перепись объявляет "
                f"{self.census_total} элементов, а `elements` пуст ПО "
                f"ПОСТРОЕНИЮ. Ноль отсюда — факт о ТОМ, ЧТО ВЫ СПРОСИЛИ, "
                f"а не о здании. {хвост}")
        raise L0HeaderMisread(
            "ПЕРЕПИСЬ НЕ СНЯТА, И ПУСТОТУ ДОКАЗАТЬ НЕЧЕМ: слепок сделан до "
            "волны §18.1 либо мост переписи не вернул. `elements` шапки пуст "
            "ПО ПОСТРОЕНИЮ, а знаменателя, которым это можно было бы "
            "опровергнуть, нет. Ноль из корпуса, о достижимости которого нет "
            f"доказательства, — не ноль. {хвост}")

    def _проверить(self):
        if self.census_total or not self.census_taken:
            self._refuse()

    def __iter__(self):
        self._проверить()
        return super().__iter__()

    def __len__(self):
        self._проверить()
        return 0

    def __bool__(self):
        self._проверить()
        return False
