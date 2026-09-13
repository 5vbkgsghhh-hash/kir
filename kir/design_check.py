"""design_check.py — a verdict on the fitness of the DESIGN, without Revit.

WHAT THIS IS. A KIR program (or a decompile of someone else's model) ->
`SpatialModel` -> the HAB rules engine (`kir/checker`) -> "apartment
without a window / no second exit / ceiling below code." Between "there
is a program" and "there is a verdict," Revit is never launched.

=====================================================================================
THIS IS NOT A REVIT SIMULATOR. THIS IS A GEOMETRIC READING OF THE PROGRAM.
=====================================================================================

The difference is not philosophical, and it rests on exactly one rule:
**only numbers the representation ALREADY CONTAINS are read**, and none
is derived that would arise only as a result of Revit's behavior. A wall
has ends. A floor has a contour. A door has a host and an offset along
it. Everything Revit WOULD ADD on its own is declared out of scope by
name (`OUT_OF_SCOPE` below) and is not modeled even approximately.

Why this matters more than it sounds: at least FIVE places are known
where a simulator would have lied on the very first building, and all
five are our own measurements, not fears. A component that does not
undertake to predict Revit cannot diverge from it; a component that does
undertake it diverges silently, and exactly where it is most expensive.

=====================================================================================
TWO SOURCES, AND THEY ARE NOT EQUIVALENT
=====================================================================================

`ModelSource.PARSE`   — `SpatialModel` is assembled from `L0Document` (a
                        decompile). An independent reading: the verdict
                        judges the building.
`ModelSource.PROGRAM` — `SpatialModel` is assembled from OPS (what the
                        program declares). This is a SELF-CHECK: what is
                        declared is what gets checked. A verdict from the
                        program is not testimony about the building, and
                        `BuildWitness.source` carries this distinction in
                        the artifact itself, rather than implying it.

`compare()` reconciles two verdicts about ONE building and names the
discrepancies BY NAME. This is the map of what a reading of the program
does not see — not a list of what we hope it sees.

=====================================================================================
ROOM BOUNDARIES — BY PLANAR SUBDIVISION
=====================================================================================

`create_room` gives a POINT, and nothing more. A room's polygon on the
PROGRAM path is computed as a planar subdivision of the level's wall
segments (`shapely.ops.polygonize`), and a room is the subdivision face
that contains the point. A face that TWO points fall into is not given to
either: the subdivision did not separate them, and naming one of them the
room would amount to guessing.

A room for which no polygon formed honestly goes into UNMEASURABLE. This
is not a bug and not an invention: for this the checker has
`measured_room_ratio` and `unmeasured_room_ids`, and a NOT_EVALUATED
verdict with a named cause is the correct answer, not a refusal to
answer.

MEASUREMENT OF 2026-08-03 (K2, 59 floors, 2442 rooms) — the method loses
nothing that the walls give, and does not invent what they do not give:

    the subdivision returned a polygon                    933 rooms
    bounded ONLY by walls (independently, per L0)          936 rooms
    also bounded by separators/columns                    1217 rooms
    with no bounding elements at all                        289 rooms

That is, 38% is neither luck nor the method's ceiling — it is EXACTLY the
share of the building that WALLS ALONE can, in principle, enclose. The
rest rests on room separators and columns.

FIXED ON THE EVENING OF 03.08, AND THIS WAS NOT A REFINEMENT BUT A WIRE.
Here it used to say: "there is NO room separator AT ALL in the KIR
language," from which it followed that in the program a room is enclosed
by walls or not at all. The claim went stale that same day:
`create_room_separator` is written and sits in the registry (`spec.OPS`,
measured by me: parameters `path` + `level`). Before this fix, the
subdivision was built from `create_wall` alone anyway, meaning the
language already knew how to declare a boundary while the verdict did not
read it — and a room opened onto a corridor (which has no fourth wall and
should not have one) did not close AT ALL. Now the separator's segments
go into the subdivision on par with walls, but do NOT go into
`SpatialModel.walls`: the wall rules read walls, and a separator among
them would be a zero-thickness wall.

The path FROM THE DECOMPILE (`spatial_model_from_l0`) still does not read
separators: there they need to be lifted from the L0 category, and that
is the decompiler's territory.

`PARTITION_CLOSE_TOL_MM` is the only tolerance in this spot, and it is
named. Wall axis lines in Revit do not always meet exactly; measured on
K2: without a tolerance 11.3% of rooms, at 100 mm — 37.8%, at 150 mm —
38.2% and already 112 rooms are lost on shared faces. 100 mm is the
knee of the curve, not a round number.

=====================================================================================
STAGE PROFILE
=====================================================================================

`HAB011` (stair geometry) is declared `mandatory` whenever a stair
exists. Neither any decompile nor any program carries the riser count and
tread depth numbers — they are absent from the frozen L0 1.0 and absent
from `create_stairs`. Without a profile ANY building with a stair would
read as NOT_EVALUATED forever, and a verdict that is always the same one
is not a verdict.

`DESIGN_STAGE` — the design-stage profile: the same rules, a different
mandatory set plus ones withdrawn by name. It is NAMED in the report
(`CoverageInfo.profile_name`) and in the verdict's text: "design-stage
check: N rules out of M applicable." The mechanism is
`Thresholds.profile`, a seam the checker already had.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

from kir.checker.classify import (
    classify_by_fixtures,
    classify_room,
    is_known_nonhabitable,
)
from kir.checker.engine import run as run_checker
from kir.checker.flags import checker_v2_enabled
from kir.checker.report import format_text as format_check_report
from kir.checker.spatial_model import (
    CheckReport,
    Door,
    Level,
    Room,
    RoomFunction,
    SpatialModel,
    Stair,
    Verdict,
    Wall,
    Window,
)
from kir.checker.thresholds import StageProfile, Thresholds

_MM2_PER_M2 = 1_000_000.0


# ---------------------------------------------------------------------------------
# 1. WHAT IS DECLARED OUT OF SCOPE — by name, with a measurement, not a
#    blanket caveat
# ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class OutOfScope:
    """One piece of Revit behavior that is NOT modeled here — and why."""

    name: str
    behaviour: str
    measured: str


#: Five places where a simulator would have lied immediately. Each one is
#: our own measurement. The list is printed in the verdict: the reader
#: must see the boundary before trusting the number.
OUT_OF_SCOPE: tuple[OutOfScope, ...] = (
    OutOfScope(
        name="автосоединение стен",
        behaviour="Revit растягивает концы соединяемых стен на полтолщины партнёра; "
                  "длина и площадь помещения меняются ПОСЛЕ записи",
        measured="замер 21.07: +-100/125/150 мм на трёх типах стен",
    ),
    OutOfScope(
        name="опорный уровень балки",
        behaviour="`create_beam` берёт опорный уровень от ОТМЕТКИ КРИВОЙ, а не от "
                  "аргумента `level`",
        measured="замер 27.07",
    ),
    OutOfScope(
        name="высота стены при верхней привязке",
        behaviour="`WALL_USER_HEIGHT_PARAM` перестаёт быть истиной, когда стена "
                  "привязана к верхнему уровню; истина — пара top_level/top_offset",
        measured="замер 29.07; здесь высота считается по паре, а параметр берётся "
                 "только при отсутствии верхней привязки",
    ),
    OutOfScope(
        name="панель витража со стеновым типом",
        behaviour="`set_curtain_panel` со стеновым типом строит СТЕНУ вместо панели",
        measured="замер 28.07",
    ),
    OutOfScope(
        name="Railing.Create",
        behaviour="`Railing.Create(host)` возвращает КОЛЛЕКЦИЮ, а не один элемент",
        measured="замер 28.07",
    ),
)


# ---------------------------------------------------------------------------------
# 2. THE DESIGN-STAGE PROFILE
# ---------------------------------------------------------------------------------

#: Withdrawn rules: each is withdrawn because the stage does NOT EXPRESS
#: its inputs, and the cause is named as an input, not a mood. A
#: withdrawn rule is not run at all — otherwise its finding would be a
#: finding about the REPRESENTATION, indistinguishable from a finding
#: about the building.
_DESIGN_SUSPENDED: dict[str, str] = {
    "HAB031": (
        "отношение остекления 1:8 требует ПЛОЩАДИ проёма. Программа задаёт окно типом "
        "(`create_window.symbol`), габарит живёт в семействе, и в снимке заземления "
        "пул `window_symbols` несёт `params: null` (замер 03.08) — сравнивать нечего"
    ),
    # 🔴 FIXED ON 20.08.2026: HALF OF THIS RATIONALE HAD GONE STALE. It used
    # to say "L0 1.0 does not carry `WALL_STRUCTURAL_SIGNIFICANT`" — it now
    # does: the parameter was added to capture (`f4c35e51`), a live
    # measurement gives it on 7845 walls out of 10 646, and every answer is
    # negative. Leaving the old text would mean withdrawing the rule on a
    # basis that no longer exists — and the next reader would take that as
    # fact.
    #
    # The withdrawal REMAINS, and here is what now holds it up: the stage
    # judges the DESIGN, and a design is written in ops, and `create_wall`
    # has no bearing-significance attribute (`spec.OPS`, measured on
    # 03.08 — this half still stands). The decompile path now reads the
    # attribute, but there is one profile for both paths, and withdrawing
    # it based on the capability of only ONE of them would mean judging
    # the program by what it cannot say.
    #
    # WHAT CLOSES THIS: the appearance of a bearing-significance attribute
    # on `create_wall`. Then the withdrawal is reconsidered WHOLESALE, not
    # merely propped up.
    "HAB050": (
        "вертикальная неразрывность несущих требует признака «несущая» у стены, "
        "а `create_wall` такого параметра не имеет (`spec.OPS`, замер 03.08): "
        "стадия судит ЗАМЫСЕЛ, и заявить несущность автору сегодня нечем. "
        "Разбор её с 20.08.2026 читает (`WALL_STRUCTURAL_SIGNIFICANT`), но "
        "профиль один на оба пути — судить программу по способности разбора "
        "значило бы спрашивать с неё несказанное"
    ),
}

#: Mandatoriness: the rule IS RUN and honestly says "nothing to check
#: with," but it has no veto over the verdict — otherwise the verdict
#: would be predetermined by the representation.
_DESIGN_MANDATORY: dict[str, bool] = {
    "HAB011": False,
}

#: There is ONE named default, and it is closed off by the `StageProfile`
#: invariant: while HAB031 is withdrawn, the nominal value cannot reach
#: any comparison against a tolerance — it answers only the question "is
#: there an opening at all?" The number is chosen to be a deliberately
#: small single-leaf window; its magnitude affects nothing, only its sign
#: matters.
_DESIGN_NOMINAL_OPENING_M2 = 1.0

#: Rules resting on APARTMENT DERIVATION (`graph.derive_apartments`). ALWAYS
#: withdrawn, and this is not caution but a consequence of a measurement.
#: HAB002 LEFT HERE ON 15.08.2026 and moved under a PRECONDITION — see
#: `_DESIGN_PRECONDITIONS`. The basis is a measurement, not a softening: on
#: the generator's reference, where the truth is known by construction,
#: `derive_apartments` gives 20 apartments out of 20 with an EXACT
#: composition (100%). So the recorded "0%" is a property of the INPUT, and
#: the `apartments_are_dwellings` precondition separates an input the
#: oracle can be trusted on from one it cannot.
#: The remaining three stay withdrawn UNCONDITIONALLY, each for its own
#: reason — below.
_APARTMENT_ORACLE_RULES = ("HAB003", "HAB004", "HAB042")
_APARTMENT_ORACLE_REASON = (
    "правило стоит на выводе КВАРТИРЫ, а тот — на классификации имён помещений. "
    "Точность этого оракула ИЗМЕРЕНА 03.08 и разгромна: по составу жилища 0% "
    "(415 «квартир» из 469 — одна комната, ни в одной нет кухни), `core` не "
    "произведён ни разу за 52 дерева, precision mop/core 15.29%. Правило на оракуле "
    "с измеренной нулевой точностью обязано молчать, пока точность не измерена заново"
)

#: Preconditions: what the derivation had to FIND for the rule to have
#: something to talk about. Measured on 03.08: without this line HAB010
#: accused 4 occupied levels of the kindergarten and 8 levels of snowdon of
#: not descending to ground that the check had not found at all.
_DESIGN_PRECONDITIONS: dict[str, list[str]] = {
    "HAB001": ["building_entrance_known", "stair_landings_complete"],
    "HAB010": ["ground_level_known", "stair_landings_complete"],
    "HAB003": ["ground_level_known", "stair_landings_complete", "apartments_derived"],
    # HAB002 judges the apartment's TOPOLOGY (not apartment-into-apartment,
    # exactly one entrance into the common zone). Its subject is precisely
    # what the precondition makes trustworthy: as long as the components
    # are dwellings, the topology is about dwellings; as soon as one of
    # them is a component without a kitchen and a bathroom, the same rule
    # is reasoning about a derivation artifact. That is why there are TWO
    # preconditions here, and the second is not caution but a
    # discriminator.
    # A THIRD PRECONDITION WAS ADDED FOR A RED, NOT BY DESIGN, and this is
    # worth recording. With the first two, HAB002 accused the
    # `test_missing_ground_level_...` fixture, whose outer door is REMOVED
    # ON PURPOSE: the apartment got ZERO entrances, and "exactly one
    # entrance" accused the building of something that is a property of
    # the READING. This is the same class that preconditions exist for in
    # the first place (measured 03.08: HAB010 accused 4 kindergarten
    # levels and 8 snowdon levels of not descending to ground that the
    # check had not found). A rule about ENTRANCES has no right to speak
    # until at least one door is confirmed as an entrance from the street.
    "HAB002": ["apartments_derived", "apartments_are_dwellings",
               "building_entrance_known"],
}

#: Subject filters: the rule speaks only about those who have its input.
_DESIGN_SUBJECT_INPUTS: dict[str, str] = {
    "HAB001": "room_polygon",
    "HAB020": "room_polygon",
    "HAB021": "room_polygon",
    "HAB030": "room_polygon",
    "HAB040": "room_polygon",
    "HAB022": "room_height",
    "HAB041": "door_adjacency",
}


def design_stage_profile(witness: BuildWitness) -> StageProfile:
    """The stage profile for THIS PARTICULAR representation of this building.

    The profile is not universal and cannot be universal: "there is no
    input" is a claim about what could be read, not about the stage in
    general. So the base withdrawals (opening area, bearing-significance
    attribute, apartment oracle) always stand, while two of them —
    curtain-wall glazing and the absence of recognized stairwells — are
    switched on by a MEASUREMENT of this witness and print their numbers
    in the cause.

    This is NOT a flag and NOT a threshold tweak: a withdrawn rule states
    in the coverage WHAT it was missing, while the `Thresholds` numeric
    tolerances remain untouched.
    """
    suspended = dict(_DESIGN_SUSPENDED)
    for rule_id in _APARTMENT_ORACLE_RULES:
        suspended[rule_id] = _APARTMENT_ORACLE_REASON

    windows = witness.counts.get("windows", 0)
    if witness.curtain_panels > windows:
        # The glazing is expressed as a curtain wall, and `SpatialModel`
        # does not know about curtain walls at all: the building simply
        # has no window elements, and "no window" would be a claim about
        # the modeling technique, not about the room.
        suspended["HAB030"] = (
            f"остекление ВИТРАЖНОЕ: заполнений витража {witness.curtain_panels}, "
            f"окон-элементов {windows}. У `SpatialModel` понятия «витражное "
            f"остекление» нет, признака «стекло» у панели тоже нет (только имя типа) "
            f"— наличие естественного света проверить нечем")

    stairs = witness.counts.get("stairs", witness.inputs.get("stairs", 0))
    if not stairs:
        # D-4, MEASURED ON 03.08. With ZERO stairs, HAB011 printed its
        # hardcoded line from `RULE_SPECS_V2`: "stairs present but none
        # has measured geometry." It asserts the PRESENCE OF SOMETHING
        # THAT DOES NOT EXIST, and asserts it confidently — a model reads
        # it as "there are stairs, but they are wrong," and goes to fix
        # geometry that does not exist.
        #
        # This is fixed here, not in `engine.py`: there the line is a
        # field of the rule specification, and computing it from the model
        # would introduce a second source of truth about the subject into
        # the engine. The stage profile exists for exactly this: a rule
        # that HAS NO SUBJECT is not run at all and states in the coverage
        # what it was missing.
        suspended["HAB011"] = (
            "лестниц в представлении НЕТ ВОВСЕ: `create_stairs` не вызван ни "
            "разу (и ни одна лестница не поднялась из разбора). Правилу о "
            "геометрии лестницы не о чем высказываться — ни «прошло», ни «не "
            "прошло», ни «геометрия не измерена»")
    if stairs and witness.rooms_stair == 0 and witness.occupied_levels > 1:
        # The graph's vertical edges are built ONLY through a room with the
        # STAIRCASE function (`graph.build_graph` ->
        # `_landing_room_on_level`). Zero such rooms with live stairs means
        # the graph is BROKEN APART by floor, and anything reading
        # connectivity between levels will discover its own blindness.
        reason = (
            f"вертикальная связность графа строится только через помещение с функцией "
            f"ЛЕСТНИЦА; лестниц в модели {stairs}, занятых уровней "
            f"{witness.occupied_levels}, а помещений, распознанных как лестничная "
            f"клетка, — НОЛЬ (лексикон `classify.py` не знает принятых в этом проекте "
            f"имён). Граф развален по этажам, и «этаж висит» / «комната недостижима» "
            f"здесь — свойство словаря, а не здания")
        suspended["HAB001"] = reason
        suspended["HAB010"] = reason

    subject_inputs = {rule_id: name
                      for rule_id, name in _DESIGN_SUBJECT_INPUTS.items()
                      if rule_id not in suspended}
    preconditions = {rule_id: names
                     for rule_id, names in _DESIGN_PRECONDITIONS.items()
                     if rule_id not in suspended}
    return StageProfile(
        name="стадия замысла (KIR design intent)",
        note=(
            "Проверяется ЗАМЫСЕЛ. Правило, у которого нет входа, НЕ СРАБАТЫВАЕТ и "
            "говорит об этом в покрытии: снятое — целиком, отфильтрованное — по тем "
            "субъектам, у которых входа нет."
        ),
        suspended=suspended,
        mandatory=_DESIGN_MANDATORY,
        subject_inputs=subject_inputs,
        preconditions=preconditions,
        nominal_opening_area_m2=_DESIGN_NOMINAL_OPENING_M2,
    )


#: The base profile — what is withdrawn for ANY representation. Live runs
#: get its extension from `design_stage_profile(witness)`; this object
#: remains the reference point and what the tests read for "the profile
#: touches nothing beyond what is named."
DESIGN_STAGE = StageProfile(
    name="стадия замысла (KIR design intent)",
    note=(
        "Проверяется ЗАМЫСЕЛ: связность, выходы, площади, высоты, наличие окна. "
        "Всё, что становится известно только после выбора семейств и узлов, снято "
        "поимённо."
    ),
    suspended={**_DESIGN_SUSPENDED,
               **{rule: _APARTMENT_ORACLE_REASON
                  for rule in _APARTMENT_ORACLE_RULES}},
    mandatory=_DESIGN_MANDATORY,
    subject_inputs={rule_id: name
                    for rule_id, name in _DESIGN_SUBJECT_INPUTS.items()
                    if rule_id not in (*_APARTMENT_ORACLE_RULES,
                                       *_DESIGN_SUSPENDED)},
    preconditions={rule_id: names
                   for rule_id, names in _DESIGN_PRECONDITIONS.items()
                   if rule_id not in (*_APARTMENT_ORACLE_RULES,
                                      *_DESIGN_SUSPENDED)},
    nominal_opening_area_m2=_DESIGN_NOMINAL_OPENING_M2,
)

#: A ready object for `run_checker(model, thr)`. The numeric tolerances are
#: NOT touched: the profile changes the set of rules and the coverage of
#: subjects, but not the strictness of any of them.
DESIGN_STAGE_THRESHOLDS = Thresholds(profile=DESIGN_STAGE)


# ---------------------------------------------------------------------------------
# 3. READING TOLERANCES — all in one place, each with a measurement
# ---------------------------------------------------------------------------------

#: How far each wall segment is extended at both ends before the network is
#: welded (mm). Measured on K2: 0 -> 11.3% of rooms, 100 -> 37.8%, 150 ->
#: 38.2% (and 112 rooms are lost on shared faces), 400 -> 38.7% (335 on
#: shared faces). The knee is 100.
PARTITION_CLOSE_TOL_MM = 100.0

#: How close an opening must lie to a room's/envelope's boundary to count
#: as its opening. Deliberately matches `Thresholds.derive_join_tol_mm`:
#: the checker already has this tolerance, and two different numbers for
#: one question is a way to diverge silently.
OPENING_JOIN_TOL_MM = 300.0

#: The share of the perimeter that must agree on one height for a room's
#: height to be considered known. Measured on K2: 2126 rooms out of 2152
#: agree at 0.5.
HEIGHT_AGREEMENT_RATIO = 0.5

#: Rounding of wall heights before the vote (mm).
HEIGHT_BUCKET_MM = 10.0

#: How far below the next level a guard is allowed to end and still count
#: as reaching the slab (mm). Measured on K2: for 11 863 walls out of
#: 15 255 the top is given by a BINDING and lands exactly on the level's
#: elevation; 500 mm covers a negative top offset and the slab thickness,
#: but does not cover a 1530 mm balustrade at a 3100 floor-to-floor
#: height.
ENCLOSURE_REACH_TOL_MM = 500.0


# ---------------------------------------------------------------------------------
# 4. THE ASSEMBLY WITNESS
# ---------------------------------------------------------------------------------

class ModelSource(str, Enum):
    """Where the `SpatialModel` came from. The difference must be visible in the artifact."""

    PARSE = "parse"       # from L0Document — an INDEPENDENT reading
    PROGRAM = "program"   # from ops — a SELF-CHECK (what is declared is what gets checked)

    @property
    def evidence(self) -> str:
        if self is ModelSource.PARSE:
            return ("НЕЗАВИСИМОЕ ЧТЕНИЕ: модель собрана из разбора (L0), вердикт "
                    "судит здание")
        return ("САМОПРОВЕРКА: модель собрана из ОПОВ ПРОГРАММЫ, вердикт судит "
                "ЗАЯВЛЕННОЕ, а не построенное")


@dataclass(frozen=True)
class BuildNote:
    """One fact about the assembly: what could not be read and why."""

    code: str
    detail: str
    count: int = 1


@dataclass
class BuildWitness:
    """Exactly what was assembled, what was not, and for what named reason."""

    source: ModelSource
    building_id: str
    doc_name: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    rooms_total: int = 0
    rooms_measured: int = 0
    unmeasured_room_ids: list[str] = field(default_factory=list)
    unmeasured_reasons: Counter = field(default_factory=Counter)
    partition_faces: int = 0
    #: rooms whose subdivision face was occupied by several points — given to no one
    shared_face_room_ids: list[str] = field(default_factory=list)
    rooms_with_height: int = 0
    height_source: str = ""
    #: 🔴 THE PROVENANCE OF THE HEIGHT LIVES IN ITS OWN FIELDS, NOT IN
    #: `counts`, AND THIS WAS BOUGHT (20.08.2026). The first edition put
    #: these three numbers into `witness.counts` — and `counts` FURTHER
    #: DOWN THE SAME PATH IS ASSIGNED WHOLESALE (`witness.counts =
    #: {...}`), so the counters died silently. Caught by exactly printing
    #: them: the line about the source showed 2154, while the dictionary
    #: was empty. The same form this wave is fixing — a receipt lost at
    #: the next seam.
    rooms_height_authored: int = 0
    rooms_height_substituted: int = 0
    #: 🔴 A DECLARED ZERO IS A THIRD OUTCOME, NOT AN EMPTINESS. Live
    #: measurement 20.08.2026: for 21 rooms out of 1102 `ROOM_UPPER_OFFSET`
    #: is EXACTLY zero. The author spoke up, but a height does not follow
    #: from this (the zero is measured from the upper limit, and its level
    #: is not captured in L0). Counting this as "not captured" would lose
    #: the fact that the author spoke; counting it as a height would
    #: declare the ceiling zero.
    rooms_height_authored_zero: int = 0
    #: for how many both values diverged by more than a millimeter: the one
    #: declared by the author and our bounding box. The number says
    #: whether the assumption "the upper limit sits at the room's own
    #: level" holds on THIS building.
    rooms_height_disagree: int = 0
    #: whether opening dimensions are measured FOR EVERY LAST ONE; False ->
    #: at least one opening was substituted with the profile's named
    #: nominal.
    #:
    #: 🔴 A BUILDING-LEVEL FLAG DOES NOT REPLACE A PER-WINDOW COUNT, AND
    #: THIS WAS BOUGHT (22.08.2026). The "measured or nominal" decision is
    #: made PER ELEMENT, while the earlier edition accumulated
    #: `measured_any` ("at least one") and used it to print a claim about
    #: the whole building: on MNVNK 588 windows were measured, 2364 got a
    #: made-up 1.0 m², and the witness said `opening_size_measured: true`
    #: with NOT A SINGLE note. The two counters below are exactly the
    #: quantity the flag lacked.
    opening_size_measured: bool = False
    openings_measured: int = 0
    openings_nominal: int = 0
    nominal_opening_area_m2: float | None = None
    #: how many elements of EACH kind carry a measured rule input — it is
    #: exactly these numbers that explain gate discrepancies, so they are
    #: collected, not merely described
    inputs: dict[str, int] = field(default_factory=dict)
    #: L0 category -> typed reasons why elements did NOT become ops (only
    #: for the PROGRAM source: a decompile has no such thing as atoms)
    lift_atoms: dict[str, Counter] = field(default_factory=dict)
    #: 🔴 WHERE ROOMS GOT THEIR FUNCTIONS FROM — FOUR NUMBERS, NOT ONE
    #: (22.08.2026). `CoverageInfo.classification_coverage` answers "how
    #: many were classified" and does not answer "by what"; after
    #: inference from furnishings these are different questions, and
    #: conflating them loses the verdict's authority.
    #: `rooms_function_conflict` is the ACCURACY of the inference, and it
    #: must be printed: 5 conflicts out of 291 statements is a number too.
    rooms_function_authored: int = 0
    rooms_function_inferred: int = 0
    rooms_function_conflict: int = 0
    #: unnamed rooms with a contour that the furnishings SAID NOTHING about
    rooms_function_unnamed: int = 0
    #: rooms whose NAME was recognized as a stairwell. Zero with live
    #: stairs means the graph's vertical edges will not be built no matter
    #: what doors exist
    rooms_stair: int = 0
    #: levels on which there is at least one room
    occupied_levels: int = 0
    #: curtain-wall infills in the representation: not windows (there is
    #: no "glass" attribute), but not nothing either — without this
    #: number, a false "no window" on a curtain-wall facade has nothing to
    #: explain it, and an explanation without a number is just intonation
    curtain_panels: int = 0
    #: element kind -> how many the ASSEMBLER SPECIFICALLY could not place
    #: in the model, and why. Separate from `lift_atoms`: "the op did not
    #: get raised" and "the op got raised, but the assembler came up
    #: short" are different addresses for the fix, and lumping them
    #: together loses the address.
    dropped: dict[str, Counter] = field(default_factory=dict)
    notes: list[BuildNote] = field(default_factory=list)

    def drop(self, population: str, reason: str, count: int = 1) -> None:
        self.dropped.setdefault(population, Counter())[reason] += count

    def note(self, code: str, detail: str, count: int = 1) -> None:
        for index, existing in enumerate(self.notes):
            if existing.code == code and existing.detail == detail:
                self.notes[index] = BuildNote(code, detail, existing.count + count)
                return
        self.notes.append(BuildNote(code, detail, count))

    @property
    def measured_ratio(self) -> float:
        return self.rooms_measured / self.rooms_total if self.rooms_total else 0.0


# ---------------------------------------------------------------------------------
# 5. GEOMETRY — planar subdivision
# ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class _WallSeg:
    """A wall segment as the representation declares it: ends, level, height."""

    wall_id: str
    level_id: str
    p0: tuple[float, float]
    p1: tuple[float, float]
    height_mm: float
    height_known: bool

    @property
    def length(self) -> float:
        return math.dist(self.p0, self.p1)


def _extended(seg: _WallSeg, tol: float) -> LineString | None:
    dx, dy = seg.p1[0] - seg.p0[0], seg.p1[1] - seg.p0[1]
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return None
    ux, uy = dx / length, dy / length
    return LineString([
        (seg.p0[0] - ux * tol, seg.p0[1] - uy * tol),
        (seg.p1[0] + ux * tol, seg.p1[1] + uy * tol),
    ])


@dataclass(frozen=True)
class _Partition:
    """Planar subdivision of one level: faces + the source segments for attributing them."""

    faces: tuple[Polygon, ...]
    segs: tuple[_WallSeg, ...]
    _face_tree: Any = None
    _seg_tree: Any = None

    @classmethod
    def build(cls, segs: Sequence[_WallSeg], tol: float) -> "_Partition":
        lines = [ln for ln in (_extended(s, tol) for s in segs) if ln is not None]
        if not lines:
            return cls(faces=(), segs=tuple(segs))
        faces = tuple(polygonize(unary_union(lines)))
        return cls(
            faces=faces,
            segs=tuple(segs),
            _face_tree=STRtree(list(faces)) if faces else None,
            _seg_tree=(STRtree([LineString([s.p0, s.p1]) for s in segs])
                       if segs else None),
        )

    def face_containing(self, point: Point) -> int | None:
        if self._face_tree is None:
            return None
        for index in self._face_tree.query(point):
            if self.faces[index].contains(point):
                return int(index)
        return None

    def bounding_segments(self, face: Polygon, tol: float) -> list[_WallSeg]:
        """Segments lying ON a face's boundary — exactly the walls that closed it."""
        if self._seg_tree is None:
            return []
        ring = LineString(face.exterior.coords).buffer(tol)
        out: list[_WallSeg] = []
        for index in self._seg_tree.query(ring):
            seg = self.segs[int(index)]
            piece = LineString([seg.p0, seg.p1]).intersection(ring)
            if getattr(piece, "length", 0.0) > tol:
                out.append(seg)
        return out


def _height_from_enclosure(segs: Iterable[_WallSeg], *,
                           base_z: float, next_level_z: float | None) -> float | None:
    """A room's height from the walls that closed it, or None.

    TWO conditions, and the second arose from a finding, not from
    caution.

    1. Length-weighted voting: the height is known only if at least
       `HEIGHT_AGREEMENT_RATIO` of the perimeter agrees on one elevation.
       A parapet on 5% of the perimeter does not declare a room half a
       meter tall, and disagreement honestly stays an unknown.
    2. A GUARD IS NOT A CEILING. A wall determines a room's height only if
       it REACHES THE NEXT LEVEL. Measured 03.08 (K2): the stair hall «ЛК
       2.1 1» is enclosed on 100% of its perimeter by walls 1530 mm tall —
       this is a balustrade around a stair opening, not a ceiling; the
       room's own extent is 3830 mm. The first edition took 1530 as the
       room's height and issued a BLOCKING "ceiling below 2200" —
       an accusation produced by the assembler's assumption, not by the
       building.
       There is no level above ⇒ nothing to check against ⇒ the height is
       UNKNOWN.

    WHAT THIS IS NOT, EVEN AFTER TWO CONDITIONS: it is the WALL's height
    from base to top, not the clear height to the ceiling. The program
    does not express floor and ceiling thickness, and the difference runs
    in the UNSAFE direction (measured on K2: walls 3100 mm against 3000
    mm for the room as read).
    """
    votes: dict[float, float] = defaultdict(float)
    total = 0.0
    for seg in segs:
        if not seg.height_known or seg.height_mm <= 0.0:
            continue
        bucket = round(seg.height_mm / HEIGHT_BUCKET_MM) * HEIGHT_BUCKET_MM
        votes[bucket] += seg.length
        total += seg.length
    if total <= 0.0 or not votes:
        return None
    best, best_len = max(votes.items(), key=lambda item: item[1])
    if best_len / total < HEIGHT_AGREEMENT_RATIO:
        return None
    if next_level_z is None:
        return None
    if base_z + best < next_level_z - ENCLOSURE_REACH_TOL_MM:
        return None
    return float(best)


def _ring(poly: Polygon) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in poly.exterior.coords]


# ---------------------------------------------------------------------------------
# 6. ASSEMBLY FROM THE DECOMPILE (L0Document) — path A
# ---------------------------------------------------------------------------------

def _levels_from_l0(document: Any) -> tuple[list[Level], dict[str, float]]:
    ordered = sorted(document.levels, key=lambda lvl: lvl.elevation_mm)
    levels = [
        Level(id=lvl.id, name=lvl.name, elevation_mm=float(lvl.elevation_mm),
              index=index)
        for index, lvl in enumerate(ordered)
    ]
    return levels, {lvl.id: float(lvl.elevation_mm) for lvl in ordered}


def _wall_span(element: Any, elevations: Mapping[str, float]) -> tuple[float, float] | None:
    """A wall's bottom and top — FROM THE top_level/top_offset PAIR, when it exists.

    This is precisely where the 29.07 measurement lives: with a top
    binding, `WALL_USER_HEIGHT_PARAM` stops being the truth, and reading
    it first would amount to predicting Revit.
    """
    level_id = getattr(element, "level_id", None)
    if level_id not in elevations:
        return None
    params = getattr(element, "params", None) or {}
    base = elevations[level_id] + float(params.get("WALL_BASE_OFFSET") or 0.0)
    top_level = params.get("WALL_HEIGHT_TYPE")
    if isinstance(top_level, str) and top_level in elevations:
        top = elevations[top_level] + float(params.get("WALL_TOP_OFFSET") or 0.0)
        return base, top
    height = params.get("WALL_USER_HEIGHT_PARAM")
    if height is None:
        return base, base
    return base, base + float(height)


def _category_of(by_id: dict, element_id: str) -> str | None:
    """The category of the boundary element, if it exists in the decompile at all.

    `None` means "the element is named as a boundary but did not make it
    into this decompile" — and this is a LAWFUL outcome, not a failure: a
    room boundary can be an element of a LINKED file. Measured on
    18.08.2026 on the kindergarten `sob62_r23_v5`: of 898 boundary
    references 340 point outside the decompile. Silently treating them as
    "not separators" is correct, whereas treating them as "separators"
    would mean joining rooms via an element we never saw.
    """
    element = by_id.get(element_id)
    return getattr(element, "category", None) if element is not None else None


def _room_upper_offset(element: Any) -> tuple[float | None, str]:
    """The room's upper offset from L0 and the KIND of what we read.

    🔴 THREE OUTCOMES, AND THE MIDDLE ONE WAS BOUGHT BY A LIVE MEASUREMENT
    ON 20.08.2026. On the document `MNVNK_ATR_PD_B14_K6_AR_R2022` the
    parameter arrived for 1102 rooms out of 1102, and for **21 of them it
    EQUALS ZERO**. Zero here is neither an emptiness nor a refusal but a
    value declared by the author, and the first edition of this read
    (`> 0.0`) dropped it into the same branch as the absence of the
    parameter. That is, "the author wrote 0" and "we did not ask" again
    became one fact — exactly the class of bug this wave is fixing for
    the third time in one day.

        absent         no parameter        -> not captured
        authored_zero  parameter = 0       -> DECLARED, but no height follows
        authored       parameter > 0       -> a declared height

    WHY ZERO IS NOT A HEIGHT. The offset is measured from the UPPER
    LIMIT; zero means "the limit with no addition," and the height itself
    then equals the difference of the levels' elevations — a quantity L0
    does not have (the limit's level is not captured). Taking zero as the
    height would declare the ceiling zero; taking it as an absence would
    lose the fact that the author spoke. So the height is taken from the
    bounding box (and honestly called `room_bbox`), while the fact of the
    declaration is counted separately.
    """
    if element is None:
        return None, "absent"
    value = (getattr(element, "params", None) or {}).get("ROOM_UPPER_OFFSET")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "absent"
    number = float(value)
    if number > 0.0:
        return number, "authored"
    if number == 0.0:
        return None, "authored_zero"
    # A negative offset is physically possible (the limit is BELOW the
    # elevation), but it is not a height, and it must not be substituted
    # in silently.
    return None, "authored_negative"


def upper_offset_vs_bbox(rows: Any) -> dict:
    """The discrepancy between the DECLARED height and our substitution — from raw L0 rows.

    WHY A SEPARATE INPUT. `rooms_height_disagree` is computed inside a
    decompile, and there may be no decompile at all: the capture body
    (`extract.build_category_batch_cs("OST_Rooms")`) returns both
    `params` and the bounding box in ONE response in two seconds. So the
    question "does the equality offset = height hold on this building"
    is settled WITHOUT a decompile — on rows already collected. The
    function is pure: no files, no network.

    🔴 WHAT IT DOES NOT DECIDE AND DOES NOT ATTEMPT. It does NOT judge who
    is right in a disagreement. The offset is measured from the UPPER
    LIMIT, whose level is not present in the row — so the disagreement
    means exactly one thing: "the limit does not sit at the room's own
    level, OR the bounding box does not equal the height." Telling these
    apart is possible only via the limit's level, and nobody captures it.
    Printing a verdict instead of a number here would pass off a guess as
    a measurement.

    AND ROUNDNESS OF THE NUMBER DOES NOT ESTABLISH AUTHORITY. On the live
    document, one value out of 1102 is 3493.7421314280423, and the
    temptation to read a non-round one as "derived by Revit, not typed by
    the author" is great. This is a CONVENTION, not a source (form 7): the
    author is entitled to type any number, and Revit is entitled to store
    a round one. True authority is `Parameter.IsReadOnly` /
    `UserModifiable` on the parameter itself, and it is asked LIVE. So
    non-round values here are COUNTED and NAMED, but influence nothing.
    """
    n = absent = zero = negative = authored = 0
    no_bbox = agree = disagree = 0
    worst = None
    fractional: list[float] = []
    for row in rows or ():
        element = row.get("element", row) if isinstance(row, dict) else row
        n += 1
        params = (element.get("params") if isinstance(element, dict)
                  else getattr(element, "params", None)) or {}
        value = params.get("ROOM_UPPER_OFFSET")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            absent += 1
            continue
        number = float(value)
        if number < 0.0:
            negative += 1
            continue
        if number == 0.0:
            zero += 1
            continue
        authored += 1
        if abs(number - round(number)) > 1e-9:
            fractional.append(number)
        lo = (element.get("bbox_min_mm") if isinstance(element, dict)
              else getattr(element, "bbox_min_mm", None))
        hi = (element.get("bbox_max_mm") if isinstance(element, dict)
              else getattr(element, "bbox_max_mm", None))
        if not lo or not hi:
            no_bbox += 1
            continue
        span = float(hi[2]) - float(lo[2])
        delta = abs(span - number)
        if delta > 1.0:
            disagree += 1
            if worst is None or delta > worst[0]:
                worst = (delta, number, span)
        else:
            agree += 1
    return {
        "rows": n,
        "absent": absent,
        "authored_zero": zero,
        "authored_negative": negative,
        "authored": authored,
        "authored_without_bbox": no_bbox,
        "agree_within_1mm": agree,
        "disagree": disagree,
        "worst_disagreement": worst,
        "fractional_values": sorted(set(fractional))[:8],
        "fractional_count": len(fractional),
    }


def _structural_flag(element: Any) -> bool | None:
    """The wall's bearing-significance attribute from L0: `None` when the parameter DID NOT ARRIVE.

    Three outcomes, not two (see the rationale at `Wall.is_structural`).
    The value arrives as an integer (`__PutIntParam`), so the type is
    checked and compared against zero: coercing to `bool` would turn an
    empty string and a missing key into a well-meaning "not bearing,"
    that is, it would return exactly the substitution this fix removes.
    """
    value = (getattr(element, "params", None) or {}).get("WALL_STRUCTURAL_SIGNIFICANT")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return None


def _thickness_mm(element: Any) -> float | None:
    """The wall's width from L0 (`WALL_ATTR_WIDTH_PARAM`, already in mm via
    `__PutSectionParam`): `None` when the parameter DID NOT ARRIVE.

    Same three-state law as `_structural_flag`: a missing key, an empty
    string or a non-number are NOT "zero thickness" — they are an emptiness
    the envelope rule (HAB042) must be able to see and name. A Revit room
    boundary lies on the wall FACE, half this width off the axis (native
    witness 2026-09-09), so substituting 0 here would re-create the false
    "open envelope" that this field exists to remove.
    """
    value = (getattr(element, "params", None) or {}).get("WALL_ATTR_WIDTH_PARAM")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    width = float(value)
    if not math.isfinite(width) or width < 0.0:
        return None
    return width


def spatial_model_from_l0(
    document: Any,
    *,
    building_id: str | None = None,
    profile: StageProfile | None = DESIGN_STAGE,
) -> tuple[SpatialModel, BuildWitness]:
    """`SpatialModel` from a decompile. An independent reading: the verdict judges the building.

    Room boundaries are taken EXACTLY AS REVIT RETURNED THEM
    (`RoomInfo.boundary_mm`) — the decompile already contains them, and
    recomputing them by subdivision would mean discarding what was read
    in favor of a worse copy. The difference from the PROGRAM path at
    this spot is precisely the gate's subject.
    """
    building = building_id or document.change_stamp
    witness = BuildWitness(source=ModelSource.PARSE, building_id=building,
                           doc_name=document.doc_name)
    levels, elevations = _levels_from_l0(document)
    known_levels = {lvl.id for lvl in levels}

    elements = getattr(document, "elements", ()) or ()
    by_category: dict[str, list[Any]] = defaultdict(list)
    for element in elements:
        by_category[element.category].append(element)
    by_id = {element.element_id: element for element in elements}

    # --- walls ----------------------------------------------------------------
    walls: list[Wall] = []
    wall_span: dict[str, tuple[float, float]] = {}
    for element in by_category.get("OST_Walls", ()):
        if element.p0_mm is None or element.p1_mm is None:
            witness.note("wall_no_curve",
                         "стена без LocationCurve в L0 — в план не попадает")
            witness.drop("walls", "нет LocationCurve в L0")
            continue
        if element.level_id not in known_levels:
            witness.note("wall_no_level", "стена ссылается на уровень вне документа")
            witness.drop("walls", "уровень вне документа")
            continue
        span = _wall_span(element, elevations)
        height = abs(span[1] - span[0]) if span else 0.0
        if span:
            wall_span[element.element_id] = span
        walls.append(Wall(
            id=element.element_id,
            level_id=element.level_id,
            curve=((float(element.p0_mm[0]), float(element.p0_mm[1])),
                   (float(element.p1_mm[0]), float(element.p1_mm[1]))),
            height_mm=max(height, 0.0),
            # 🔴 IT USED TO BE `is_structural=False` WITH THE RATIONALE "the
            # attribute is not in L0." The rationale went stale on
            # 20.08.2026: `WALL_STRUCTURAL_SIGNIFICANT` was added to
            # capture (`f4c35e51`), a live measurement gives it on 7845
            # walls out of 10 646. And the substitution itself was the
            # same illness as the room height: we were writing a VALUE
            # where we had an EMPTINESS, and `HAB050` printed "no bearing
            # walls marked" the same way both when it did not ask and when
            # the building answered NO.
            #
            # Now: the parameter arrived — we read it; it did not — `None`,
            # and the rule can see that. Zero/one arrive as an integer
            # (`__PutIntParam`), so it is compared against zero rather than
            # coerced to bool: an empty string and a missing key must not
            # become "not bearing."
            is_structural=_structural_flag(element),
            # Width in mm from the type section; `None` when L0 did not carry it.
            thickness_mm=_thickness_mm(element),
        ))
    walls_by_id = {wall.id: wall for wall in walls}

    # --- rooms: polygon = what Revit returned ----------------------------------
    room_elements = {element.element_id: element
                     for element in by_category.get("OST_Rooms", ())}
    rooms: list[Room] = []
    room_polys: dict[str, Polygon] = {}
    rooms_by_level: dict[str, list[str]] = defaultdict(list)
    heights_known = 0
    for info in document.rooms:
        if info.level_id not in known_levels:
            witness.note("room_no_level", "помещение ссылается на уровень вне документа")
            witness.drop("rooms", "уровень вне документа")
            continue
        boundary = [(float(x), float(y)) for x, y in (info.boundary_mm or ())]
        # 🔴 HOLES WERE TRAVELING IN L0 AND WERE BEING DISCARDED HERE
        # (F-041, 29.08.2026). `boundary_mm` is `loops[0]` (`extract.py`),
        # while `loops[1:]` are the interior contours; the same parsing
        # already exists in `fold._room_contains`. Without them a 4x4 m
        # room with a 3x3 shaft is measured as 16 m² instead of 7, and a
        # "dwelling" passes the minimum 8 m² it does not have — while
        # HAB060 in the process ACCUSES Revit of lying about the area.
        holes = [[(float(x), float(y)) for x, y in loop]
                 for loop in (info.boundary_loops_mm or ())[1:]]
        poly = _polygon_or_none(boundary)
        element = room_elements.get(info.id)
        if poly is None:
            witness.unmeasured_room_ids.append(info.id)
            # 🔴 "NOT PLACED" AND "PLACED BUT NOT ENCLOSED" ARE DIFFERENT
            # FACTS, AND THE DECOMPILE DISTINGUISHES THEM (22.08.2026).
            # Previously both emptinesses were counted under one code,
            # `ring_degenerate`, and the reader got 629 identical lines
            # about a building where two DIFFERENT things needed fixing.
            #
            # The discriminator had been sitting in the decompile the
            # whole time: a PLACED room has a location point
            # (`Room.Location`), an unplaced one has none at all. Measured
            # on MNVNK: of 629 zero-area rooms, 608 carry a point
            # (`geom_kind: point`), 21 do not (`bbox_only`), and this is
            # exactly the 608/21 split that used to be settled only by
            # live Revit.
            #
            # WHAT THIS DOES NOT DISTINGUISH, AND THE BOUNDARY IS NAMED
            # HONESTLY: for the 608 placed ones, "walls do not close" is
            # still indistinguishable from "closed IN A DIFFERENT PHASE" —
            # a room's closure is a PER-PHASE fact, and L0 has no room
            # phase (`phase_created` is empty for 1102 of 1102, even
            # though walls do carry it: АГК 10305 · ПД 215 · Промежуточная
            # 126). This is closed ONLY by a fresh capture.
            placed = element is not None and element.p0_mm is not None
            witness.unmeasured_reasons[
                "room_placed_but_not_enclosed" if placed
                else "room_not_placed"] += 1
        else:
            room_polys[info.id] = poly
        # Height: FIRST the one declared by the author, and only then our substitution.
        #
        # 🔴 BEFORE 20.08.2026 ONLY THE BOUNDING-BOX EXTENT WAS HERE, AND
        # HAB022 JUDGED BY IT. `ROOM_UPPER_OFFSET` was added to capture the
        # same day (`f4c35e51`) and confirmed by a live run: 1102 rooms out
        # of 1102 carry the parameter, 1081 nonzero, 0 refusals
        # (`MNVNK_ATR_PD_B14_K6_AR_R2022`, Revit 2023).
        #
        # THE BOUNDARY OF THIS READ, NAMED RATHER THAN SKIRTED. The
        # parameter is an offset from the UPPER LIMIT, and the limit's
        # level is not captured in L0. So the equality "offset = height"
        # is true only when the limit sits at the room's own level. There
        # is nothing in the decompile to check this against, so the
        # discrepancy with the bounding box is not swallowed but COUNTED:
        # a pair of numbers in the witness says how far the assumption
        # holds on THIS building. A silent choice between the two
        # candidates would be exactly the defect this fixes.
        height: float | None = None
        source: str | None = None
        span: float | None = None
        if element is not None and element.bbox_min_mm and element.bbox_max_mm:
            raw = float(element.bbox_max_mm[2]) - float(element.bbox_min_mm[2])
            if raw > 0.0:
                span = raw
        authored, offset_state = _room_upper_offset(element)
        if offset_state == "authored_zero":
            witness.rooms_height_authored_zero += 1
        if authored is not None:
            height, source = authored, "room_upper_offset"
            witness.rooms_height_authored += 1
            if span is not None and abs(span - authored) > 1.0:
                witness.rooms_height_disagree += 1
        elif span is not None:
            height, source = span, "room_bbox"
            witness.rooms_height_substituted += 1
        if height is not None:
            heights_known += 1
        rooms.append(Room(
            id=info.id,
            name=info.name,
            level_id=info.level_id,
            function=classify_room(info.name),
            # The function kind is named AT THE MOMENT IT IS ASSIGNED, not
            # reconstructed later from the value: "OTHER, because the
            # author wrote Balcony" and "OTHER, because the author wrote
            # nothing" are different claims, and by `function` alone they
            # are indistinguishable (see `function_provenance`).
            function_source=_name_function_source(info.name),
            area_m2=float(info.area_m2 or 0.0),
            height_mm=height,
            boundary=boundary,
            boundary_holes=holes,
            # has_window is NOT declared: Revit does not declare it; if we
            # declared it, HAB060 would be catching our own claim, not the
            # model.
            has_window=False,
            height_source=source,
            # SEPARATION LINES, not all boundary elements. The category is
            # known ONLY here, so the filter sits here: `graph.py` would
            # receive raw ids and would join rooms across a shared WALL,
            # merging adjacent apartments. Measured on 18.08.2026 on the
            # tower: 17 296 boundary references, of which 2 958 are
            # separators — that is, 83% would have to be discarded by a
            # consumer that has nothing to discard them with.
            separator_ids=tuple(
                eid for eid in (info.bounding_element_ids or ())
                if _category_of(by_id, eid) == "OST_RoomSeparationLines"),
        ))
        rooms_by_level[info.level_id].append(info.id)
    witness.rooms_total = len(rooms)
    witness.rooms_measured = len(room_polys)
    witness.rooms_with_height = heights_known
    # The source is named by WHAT ACTUALLY CAME OUT, not by what was
    # intended: in one building both branches live simultaneously, and one
    # label for everyone would lie about the half that was read
    # differently.
    _authored = witness.rooms_height_authored
    _substituted = witness.rooms_height_substituted
    if _authored and _substituted:
        witness.height_source = (
            f"ROOM_UPPER_OFFSET у {_authored}, подстановка габаритом у {_substituted}")
    elif _authored:
        witness.height_source = f"ROOM_UPPER_OFFSET (объявлено автором), {_authored}"
    elif _substituted:
        witness.height_source = (
            f"вертикальный размах помещения (L0 bbox) — ПОДСТАВЛЕНО, {_substituted}")
    else:
        witness.height_source = "высоты нет ни у одного помещения"
    if witness.rooms_height_authored_zero:
        # An annotation, not a separate row: this is not a source of the
        # height but a fact that the author spoke up, and the statement
        # DOES NOT GIVE a height.
        witness.height_source += (
            f"; у {witness.rooms_height_authored_zero} верхнее смещение объявлено "
            f"НУЛЁМ — высказывание есть, высоты из него нет")

    rooms = _name_functions_backfilled_by_fixtures(
        rooms=rooms, room_polys=room_polys, rooms_by_level=rooms_by_level,
        by_category=by_category, witness=witness)

    doors, windows = _openings(
        door_elements=by_category.get("OST_Doors", ()),
        window_elements=by_category.get("OST_Windows", ()),
        walls_by_id=walls_by_id,
        room_polys=room_polys,
        rooms_by_level=rooms_by_level,
        witness=witness,
        profile=profile,
        location_of=lambda e: _l0_point(e, witness),
        size_of=_size_from_instance_params,
        host_of=lambda e: e.host_id,
        id_of=lambda e: e.element_id,
        # The decompile declares a level ON THE OPENING ITSELF; the host's
        # level remains a fallback. The program has no such field at all —
        # there is only the host there, and this is a difference of
        # inputs, not a difference in interpretation.
        level_of=lambda e: e.level_id if e.level_id in known_levels else None,
    )

    stairs = _stairs_from_l0(by_category.get("OST_Stairs", ()), elevations, witness)

    # Curtain-wall glazing is COUNTED but not declared a window: a
    # curtain-wall panel has no "glass" attribute — only a type name, and
    # deciding by name would be guessing. The number is needed so the
    # caveat about a false "no window" carries a figure, not an
    # intonation.
    witness.curtain_panels = len(by_category.get("OST_CurtainWallPanels", ()))

    witness.counts = {
        "levels": len(levels), "rooms": len(rooms), "walls": len(walls),
        "doors": len(doors), "windows": len(windows), "stairs": len(stairs),
    }
    model = SpatialModel(building_id=building, levels=levels, rooms=rooms,
                         doors=doors, windows=windows, stairs=stairs, walls=walls)
    _fill_inputs(witness, model)
    return model, witness


#: L0 categories whose INSTANCES name a room's function by their own type.
#:
#: The list is deliberately closed and short, by measurement: in MNVNK the
#: function is named by `OST_PlumbingFixtures` (a wet point) and
#: `OST_Furniture` (bed, sofa, kitchen front). `OST_MechanicalEquipment` IS
#: NOT IN THIS LIST, even though 231 «Телевизор» looks like a sign of a
#: dwelling: the same 818 elements also hold 370 outdoor AC condenser
#: units and 96 trash bins, that is, the category mixes an apartment's
#: furnishings with facade engineering, and the "television" key would
#: drag along the obligation to sort through the remaining 587.
#: `OST_SpecialityEquipment` — funnels and chimneys — says nothing at all
#: about a room's function.
_FUNCTION_FIXTURE_CATEGORIES = ("OST_PlumbingFixtures", "OST_Furniture")


def _name_function_source(name: str) -> str | None:
    """The function kind assigned BY THE ROOM'S NAME: `room_name`, or `None`.

    `None` means "the name said nothing," not "said OTHER": the name
    «Балкон» does declare OTHER (the lexicon knows it as definitely not a
    dwelling), while the name «Помещение» declares nothing. The first one
    needs no inference from furnishings and is not entitled to one; the
    second one needs it — without this discriminator they are
    indistinguishable.
    """
    if classify_room(name) is not RoomFunction.ПРОЧЕЕ:
        return "room_name"
    if is_known_nonhabitable(name):
        return "room_name"
    return None


def _name_functions_backfilled_by_fixtures(
    *,
    rooms: list[Room],
    room_polys: Mapping[str, Polygon],
    rooms_by_level: Mapping[str, list[str]],
    by_category: Mapping[str, list[Any]],
    witness: BuildWitness,
) -> list[Room]:
    """A room's function BY FURNISHINGS — where the name said nothing.

    🔴 THIS IS AN INFERENCE, AND IT NAMES ITSELF AS ONE. `Room.function_source`
    gets the value `fixtures`, `function_provenance` classes it as
    `derived`, and HAB020/HAB021 on such a room do NOT BLOCK but print the
    reason. The inference touches not a single name and not a single
    threshold.

    WHY IT EXISTS AT ALL, BY THE 22.08.2026 MEASUREMENT (MNVNK): `ROOM_NAME`
    = «Помещение» for 1102 rooms out of 1102, 0% classification, and
    because of it seven rules out of twenty stay silent. The furnishings
    sit in the same decompile and do name the function.

    BOUNDARIES, EACH NAMED BY A NUMBER OR A PROHIBITION:

    * the inference runs ONLY on a room with a MEASURABLE contour —
      without a polygon there is not even the question "what's inside";
      on MNVNK this is 473 rooms out of 1102;
    * membership is decided by STRICT point-in-polygon containment, with
      no tolerance: a toilet on the boundary of two contours belongs to
      both equally badly, and a tolerance here would produce false
      confidence, not coverage;
    * A CONFLICT OF SIGNS IS NOT RESOLVED, IT IS COUNTED: a room where the
      furnishings name two kinds at once stays OTHER and goes into the
      counter. The inference's accuracy is therefore printed, not implied;
    * a name that said SOMETHING (including «Балкон») is not overridden by
      the furnishings: the author's word outranks the derived one.
    """
    inferable = {room.id for room in rooms
                 if room.function is RoomFunction.ПРОЧЕЕ
                 and room.function_source is None
                 and room.id in room_polys}
    witness.rooms_function_authored = sum(
        1 for room in rooms if room.function_source == "room_name")
    if not inferable:
        return rooms

    trees: dict[str, tuple[list[str], STRtree]] = {}
    for level_id, room_ids in rooms_by_level.items():
        ids = [rid for rid in room_ids if rid in inferable]
        if ids:
            trees[level_id] = (ids, STRtree([room_polys[rid] for rid in ids]))

    fixtures_in_room: dict[str, list[str]] = defaultdict(list)
    fixtures_seen = 0
    fixtures_placed = 0
    for category in _FUNCTION_FIXTURE_CATEGORIES:
        for element in by_category.get(category, ()):
            fixtures_seen += 1
            point = _fixture_point(element)
            got = trees.get(element.level_id) if point is not None else None
            if got is None:
                continue
            ids, tree = got
            for index in tree.query(point):
                rid = ids[int(index)]
                if room_polys[rid].contains(point):
                    fixtures_in_room[rid].append(element.type_name or "")
                    fixtures_placed += 1
                    break

    named, conflicted = 0, 0
    decided: dict[str, RoomFunction] = {}
    for rid, type_names in fixtures_in_room.items():
        function, seen = classify_by_fixtures(type_names)
        if function is not None:
            decided[rid] = function
            named += 1
        elif len(seen) > 1:
            conflicted += 1
    witness.rooms_function_inferred = named
    witness.rooms_function_conflict = conflicted
    witness.rooms_function_unnamed = len(inferable) - named - conflicted
    if named or conflicted:
        total = named + conflicted
        witness.note(
            "room_function_from_fixtures",
            f"функция ВЫВЕДЕНА ИЗ ОБСТАНОВКИ у {named} помещений из {len(inferable)} "
            f"безымянных с измеримым контуром (обстановка высказалась о {total}, "
            f"конфликт признаков у {conflicted} — "
            f"{named / total * 100:.1f} % однозначных). Автор этих функций НЕ "
            f"называл: `function_source=fixtures`, и HAB020/HAB021 на них не "
            f"блокируют. Признаков разнесено по контурам {fixtures_placed} из "
            f"{fixtures_seen} прочитанных",
            named)
    if not decided:
        return rooms
    return [room.model_copy(update={"function": decided[room.id],
                                    "function_source": "fixtures"})
            if room.id in decided else room
            for room in rooms]


def _fixture_point(element: Any) -> Point | None:
    """A furnishing item's point: its own, or — if it has none — the center of the READ bbox.

    The same fallback, for the same reason, as `_l0_point` for openings,
    and the same boundary: the center of the box is not a guess about
    Revit, it is the middle of the exact box the reading returned.
    """
    if element.p0_mm is not None:
        return Point(float(element.p0_mm[0]), float(element.p0_mm[1]))
    if element.bbox_min_mm is not None and element.bbox_max_mm is not None:
        return Point((float(element.bbox_min_mm[0]) + float(element.bbox_max_mm[0])) / 2.0,
                     (float(element.bbox_min_mm[1]) + float(element.bbox_max_mm[1])) / 2.0)
    return None


def _l0_point(element: Any, witness: BuildWitness) -> tuple[float, float] | None:
    """An opening's position from the decompile: a point, or — if there is none — the CENTER OF THE READ BBOX.

    Measured 03.08 (K2): all 49 windows of the tower were captured as
    `geom_kind: bbox_only` — they have no point at all. Without this
    fallback, the decompile path lost ALL of the building's windows and
    reported "no window" for every dwelling room, that is, it lost
    exactly the finding it was undertaken for. The center of the bbox is
    not a guess about Revit, it is the middle of the exact box the
    reading returned; the provenance is noted in the witness.
    """
    if element.p0_mm is not None:
        return float(element.p0_mm[0]), float(element.p0_mm[1])
    if element.bbox_min_mm is not None and element.bbox_max_mm is not None:
        witness.note("opening_from_bbox",
                     "положение проёма взято как центр bbox: точки в L0 нет "
                     "(geom_kind=bbox_only)")
        return ((float(element.bbox_min_mm[0]) + float(element.bbox_max_mm[0])) / 2.0,
                (float(element.bbox_min_mm[1]) + float(element.bbox_max_mm[1])) / 2.0)
    return None


def _size_from_instance_params(element: Any) -> tuple[float, float] | None:
    params = getattr(element, "params", None) or {}
    width = params.get("FAMILY_WIDTH_PARAM")
    height = params.get("FAMILY_HEIGHT_PARAM")
    if width is None or height is None:
        return None
    return float(width), float(height)


#: How close the derived top of a flight must land to an existing level's
#: elevation for that level to be named the top (mm).
#:
#: MEASURED 22.08.2026, MNVNK, 24 stairs: for 23 of them base +
#: `ACTUAL_NUM_RISERS` × `ACTUAL_RISER_HEIGHT` coincides with an existing
#: level's elevation TO WITHIN FLOATING-POINT NOISE (|Δ| < 1e-8 mm — level
#: elevations arrive as 77849.99999999997). For the twenty-fourth (id
#: 929851, a finishing stair to the roof) the top lands 600 mm ABOVE the
#: nearest level.
#:
#: That is, the distribution of discrepancies here is TWO-HUMPED and the
#: gap between the humps spans five orders of magnitude; 50 mm sits inside
#: the gap and was chosen not by fitting but by meaning: it is the same
#: tolerance by which `Thresholds.wall_snap_tol_mm` counts a wall as
#: adjoining. A match within tolerance is an argument in favor of the
#: inference, not proof of authorship: the kind still remains `derived`.
STAIR_TOP_SNAP_TOL_MM = 50.0


def _stairs_from_l0(elements: Iterable[Any], elevations: Mapping[str, float],
                    witness: BuildWitness) -> list[Stair]:
    """Stairs from L0.

    A stair's `Element.Level` is empty — the collector puts None there,
    and the truth lives in `STAIRS_BASE_LEVEL_PARAM`/
    `STAIRS_TOP_LEVEL_PARAM` (measured 03.08: because of reading
    `Element.Level`, stairs never even reached the semantic fold).

    🔴 THE TOP LEVEL IS INFERRED WHEN IT WAS NOT DECLARED (22.08.2026). The
    earlier edition required BOTH parameters and skipped a stair if the
    top one was missing. Measured on MNVNK: `STAIRS_TOP_LEVEL_PARAM`
    returned empty for 24 stairs out of 24, and all 24 were discarded —
    while `BASE_LEVEL`, `ACTUAL_NUM_RISERS`, and `ACTUAL_RISER_HEIGHT`
    arrived 24 out of 24. The price of discarding was printed in the same
    run: with not a single stair, the `stair_landings_complete`
    precondition is true VACUOUSLY, and HAB010 accused 23 levels out of
    24 of not descending to ground. This was a claim about our reading,
    spoken in the voice of a claim about the building.

    The inferred value NAMES ITSELF as inferred (`Stair.top_level_source`,
    the dict — `stair_provenance`), and `check_hab011` does not block on
    it: a flight's rise, computed from the inferred top, returns exactly
    the riser height the top was inferred from.
    """
    stairs: list[Stair] = []
    for element in elements:
        params = getattr(element, "params", None) or {}
        base = params.get("STAIRS_BASE_LEVEL_PARAM")
        top = params.get("STAIRS_TOP_LEVEL_PARAM")
        if not isinstance(base, str):
            witness.note("stair_no_base_level",
                         "у лестницы нет STAIRS_BASE_LEVEL_PARAM — выводить верх "
                         "не от чего, пропущена")
            witness.drop("stairs", "нет STAIRS_BASE_LEVEL_PARAM")
            continue
        if base not in elevations:
            witness.note("stair_level_absent",
                         "уровень лестницы отсутствует в документе — пропущена")
            witness.drop("stairs", "уровень лестницы вне документа")
            continue

        # The riser count and tread depth DO ARRIVE: 24 out of 24 on
        # MNVNK (17-24 risers of 150 mm, a 300 mm tread). The earlier
        # docstring "they are absent in L0 1.0" went stale — of the three
        # quantities, one is missing.
        risers = params.get("STAIRS_ACTUAL_NUM_RISERS")
        riser_h = params.get("STAIRS_ACTUAL_RISER_HEIGHT")
        tread = params.get("STAIRS_ACTUAL_TREAD_DEPTH")
        riser_count = (int(risers) if isinstance(risers, (int, float))
                       and not isinstance(risers, bool) and int(risers) > 0 else None)
        tread_depth = (float(tread) if isinstance(tread, (int, float))
                       and not isinstance(tread, bool) else None)

        base_z = float(elevations[base])
        if isinstance(top, str) and top in elevations:
            top_level_id, top_z = top, float(elevations[top])
            top_source = "stairs_top_level_param"
        else:
            derived = _derived_stair_top(base_z, riser_count, riser_h, elevations)
            if derived is None:
                witness.note(
                    "stair_no_top_level",
                    "STAIRS_TOP_LEVEL_PARAM пуст, и вывести верх нечем: нужны "
                    "STAIRS_ACTUAL_NUM_RISERS и STAIRS_ACTUAL_RISER_HEIGHT — "
                    "пропущена")
                witness.drop("stairs", "верх не объявлен и не выводится")
                continue
            top_level_id, top_z, delta = derived
            if abs(delta) <= STAIR_TOP_SNAP_TOL_MM:
                top_source = "riser_run"
                witness.note(
                    "stair_top_derived",
                    "верхний уровень лестницы ВЫВЕДЕН: база + число подступенков × "
                    "высоту подступенка; выведенная отметка совпала с отметкой "
                    f"уровня в пределах {STAIR_TOP_SNAP_TOL_MM:.0f} мм. Подъём марша "
                    "на такой лестнице проверяет сам себя — HAB011 не блокирует")
            else:
                top_source = "riser_run_offlevel"
                witness.note(
                    "stair_top_off_level",
                    "верх марша ВЫВЕДЕН и НЕ совпал ни с одним уровнем: ближайший "
                    f"отстоит на {delta:+.0f} мм. Верхним назван он, отметка верха "
                    "оставлена выведенной — это факт о здании (марш кончается не на "
                    "уровне), а не пробел чтения")
        # THE FLIGHT'S PLAN IS NOT IN L0, AND THE BBOX IS NOT IT.
        #
        # The first edition put the bounding-box rectangle here. The box
        # is a genuine reading number, but it is not the flight's plan:
        # for a rotated or L-shaped flight it describes an entirely
        # different figure, and HAB012 (core continuity) started comparing
        # something other than what it names. Measured 03.08 (K2, 89
        # stairs): 100 "core broken" warnings on a tower whose core stands
        # in place. An empty list means "there is no plan," and the rule
        # honestly goes to NOT_EVALUATED instead of a hundred findings
        # about our own substitution.
        witness.note("stair_no_plan",
                     "плана марша в L0 нет (габаритная рамка им не является) — "
                     "HAB012 сравнивать нечего")
        if riser_count is None or tread_depth is None:
            witness.note("stair_geometry_partial",
                         "у лестницы нет STAIRS_ACTUAL_NUM_RISERS / "
                         "_TREAD_DEPTH — HAB011 скажет «неизмеримо» по этой части")
        stairs.append(Stair(
            id=element.element_id,
            base_level_id=base,
            top_level_id=top_level_id,
            base_z=base_z,
            top_z=top_z,
            # 🔴 THE FLIGHT WIDTH IS THE ONLY ONE OF THE THREE THAT IS
            # TRULY ABSENT. Measured 20.08: `STAIRS_ATTR_TREAD_WIDTH` gives
            # `HasValue=false` on all 24 stairs — the parameter exists and
            # is empty; the width lives on the RUN
            # (`Stairs.GetStairsRuns()` → `StairsRun.ActualRunWidth`), and
            # the capture does not read runs at all (the recipe is
            # recorded in `decompile/extract.py`, next to
            # `__PutSectionParam` for stairs). None means "not measured,"
            # not 1200 mm pulled out of thin air.
            run_width_mm=None,
            riser_count=riser_count,
            tread_depth_mm=tread_depth,
            footprint=[],
            kind="element",
            top_level_source=top_source,
        ))
    return stairs


def _derived_stair_top(base_z: float, riser_count: int | None, riser_h: Any,
                       elevations: Mapping[str, float],
                       ) -> tuple[str, float, float] | None:
    """The flight's top, computed from the risers: `(level, elevation, discrepancy)`.

    Returns `None` when there is nothing to compute from. The top's
    elevation is DERIVED (base + N × h), not the elevation of the chosen
    level: substituting the level there would mean printing, for a stair
    that ends off a level, a rise that does not exist (on MNVNK this
    would give 115 mm instead of the declared 150). The discrepancy is
    returned as a third number so that the decision about the kind is
    made by the caller, not by this function.
    """
    if riser_count is None or not isinstance(riser_h, (int, float)) \
            or isinstance(riser_h, bool) or not elevations:
        return None
    top_z = base_z + riser_count * float(riser_h)
    nearest = min(elevations, key=lambda lid: abs(float(elevations[lid]) - top_z))
    return nearest, top_z, float(elevations[nearest]) - top_z


# ---------------------------------------------------------------------------------
# 7. ASSEMBLY FROM THE PROGRAM (L1 ops) — path B
# ---------------------------------------------------------------------------------

def _ref_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        if value.get("by") == "name":
            return str(value.get("value"))
        if value.get("by") == "family_type":
            return str(value.get("type_name"))
    return None


def _ref_source_id(value: Any) -> str | None:
    if isinstance(value, Mapping) and "by" in value:
        got = value.get("_id")
        return str(got) if got else None
    return None


def _ref_node(value: Any) -> str | None:
    if isinstance(value, Mapping) and set(value) == {"ref"}:
        return str(value["ref"])
    return None


# ---------------------------------------------------------------------------------
# 7-BIS. TWO INPUT SHAPES — AND A REFUSAL THAT NAMES THE ONE IT SAW
# ---------------------------------------------------------------------------------
#
# WHY THIS IS A SEPARATE KIND OF REFUSAL, NOT AN EMPTY MODEL. "The input
# is the wrong shape" and "there are no rooms in the building" are
# DIFFERENT claims, and the second one lies: it states something about
# the building that it never read. Measured 03.08 on a live loop: 100
# operations, 27 `create_room`, the answer "HAB000 — model has no rooms."
# The diagnosis was steering the model to add rooms where twenty-seven
# already existed — that is, it cost a round AND damaged the program.

#: The refusal code about the verdict's input shape. A separate letter on
#: purpose: this is not a decompile (`KIR-P*`) and not grounding
#: (`KIR-G*`), but the door of the VERDICT.
PROGRAM_SHAPE = "KIR-V001"

#: The refusal code about the BUNDLE CONTRACT. The input shape is correct
#: for it — what is unlawful is the CONTENT: a `{"by": "ref"}` reference
#: that crossed the program's boundary. A reference lives inside a program
#: (`KIR-L003` resolves it against the plan), and between the bundle's
#: programs there is nothing to resolve it with: the second program
#: executes as a separate transaction, where the first program's id no
#: longer exists. Silently ignoring such a reference would mean judging a
#: different building than the one that will actually get built.
BUNDLE_CONTRACT = "KIR-V002"

#: The refusal code about NON-BUILDABILITY. The input shape is correct,
#: the references are lawful — but the COMPILER WILL NOT TAKE the
#: program. The 04.08 measurement this code was set up for: `check_ops`
#: judged fit a program containing `create_stairs` next to its neighbors
#: and printed `ПРИГОДЕН`, while `plan_program` rejected the same program
#: with `KIR-L002`. The model got TWO green lights and a wall: `preview()`
#: drew it, `design_check()` blessed it, the compiler refused it. This is
#: exactly the "two signatures on one building" the entire compiler is
#: typed against — and the verdict was one of them.
#:
#: A third code, not an extension of `KIR-V002`, by the logic of this
#: family itself: "this is not a bundle," "a bundle, but a reference
#: crossed the boundary," and "the program is not buildable" are THREE
#: DIFFERENT FIXES. The last one is fixed by the program's author, and
#: fixed unambiguously: split it into a bundle and judge it with
#: `check_bundle`.
#:
#: WHAT THIS DOOR DOES NOT DO. It does not become a front end for the
#: compiler and does not repeat `plan_program`: that one also refuses for
#: reasons that have nothing to do with fitness (an unknown field, a
#: budget), and dragging them in here would substitute the question "is
#: this a house" with the question "does it compile." What is checked is
#: precisely the law of FORM the bundle was set up for — `spec.SOLO_OPS`.
PROGRAM_NOT_BUILDABLE = "KIR-V003"

_SHAPE_OPS = "ops"      # KIR operations: {"op": …, "id": …}, fields flat
_SHAPE_L1 = "l1"        # decompiler nodes: {"kind": …, "op_name": …, "params": {…}}
_SHAPE_PROGRAM = "program"   # a program envelope: {"ops": [...]} — an element of a BUNDLE

_SHAPE_RU = {
    _SHAPE_OPS: ('ОПЕРАЦИИ KIR — {"op": "create_wall", "id": …, поля плоско}; '
                 'ровно то, что отдаёт песочница (`SandboxResult.ops`)'),
    _SHAPE_L1: ('УЗЛЫ L1 декомпилятора — {"kind": "op", "op_name": …, '
                '"params": {…}, "source_element_id": …}'),
    _SHAPE_PROGRAM: ('ПРОГРАММА целиком — конверт {"ops": [...]}; '
                     'последовательность таких конвертов и есть ПАЧКА'),
}

#: Which door accepts which shape. A refusal must name not only what it
#: saw but also where one should have gone instead: a refusal without an
#: address is a second round.
_SHAPE_DOOR = {
    _SHAPE_OPS: "spatial_model_from_ops(...) / check_ops(...)",
    _SHAPE_L1: "spatial_model_from_program(...)",
    _SHAPE_PROGRAM: "check_bundle(...) / spatial_model_from_bundle(...)",
}

#: The prefix of the node's internal identifier. These nodes NEVER leave
#: `spatial_model_from_ops`: they live for exactly one call and are not
#: the decompiler's L1 (which has its own `stable_l1_id`). The prefix
#: exists only so that a reference to a node (`{"ref": …}`) does not
#: collide with an element identifier.
_NODE_PREFIX = "kir::"


class VerdictInputError(ValueError):
    """The common root of the VERDICT DOOR's refusals: an unfit input, the building was never read.

    The root exists precisely so the caller has ONE catch point for all
    of the door's refusals, with the CODE LETTER distinguishing them, not
    the class. Otherwise every new kind of refusal from this door would
    silently fly past an old `except` — and a traceback would escape
    outward instead of a named cause.
    """

    code = ""

    def __init__(self, message_ru: str, **detail: Any) -> None:
        super().__init__(message_ru)
        self.message_ru = message_ru
        self.detail = {k: v for k, v in detail.items() if v is not None}

    def render(self) -> str:
        return f"{self.code}: {self.message_ru}"


class ProgramShapeError(VerdictInputError):
    """The verdict's input is the wrong shape — said DIRECTLY.

    An exception, not an empty model, because an empty model is
    indistinguishable from an honest "the building is empty," and the
    difference between these two answers is the difference between "fix
    the call" and "fix the building."
    """

    code = PROGRAM_SHAPE


class BundleContractError(VerdictInputError):
    """The input shape is CORRECT, but a reference inside the bundle is unlawful.

    A code separate from `KIR-V001` on purpose: "this is not a bundle" and
    "this is a bundle, but a reference in it crossed the program's
    boundary" are DIFFERENT fixes. The first is fixed by the caller, the
    second by the program's author, and one code for both would send half
    the cases to the wrong address.
    """

    code = BUNDLE_CONTRACT


class ProgramNotBuildableError(VerdictInputError):
    """The shape is correct, the references are lawful — but the COMPILER will not take this program.

    An exception, not a verdict finding, and this distinction bears
    weight. A finding says "the building is bad" — it is fixed by
    changing the building. Here, though, the building can be perfectly
    fine: the PROGRAM as a unit is not buildable, and this is fixed by
    splitting it into a bundle, not by redesigning. Conflating them would
    send the author looking for a nonexistent flaw in the design.
    """

    code = PROGRAM_NOT_BUILDABLE


def _unbuildable_solo(ops: Sequence[Any]) -> tuple[str, list[str]] | None:
    """The op that owns its own transaction, alongside neighbors — or `None`.

    There is one source of truth — `spec.SOLO_OPS`, the same one
    `plan_program` and `emit_program` use to refuse. A list of its own
    here would become a fourth judge of one question and would diverge
    from the others on the very first new op.
    """
    from kir import spec  # lazily: the verdict does not drag in the registry just for the import

    if len(ops) < 2:
        return None
    names = {o.get("op") for o in ops if isinstance(o, Mapping)}
    solo = sorted(n for n in names if n in spec.SOLO_OPS)
    if not solo:
        return None
    return solo[0], sorted(n for n in names if n and n not in spec.SOLO_OPS)


def _refuse_if_unbuildable(ops: Sequence[Any], *, where: str) -> None:
    found = _unbuildable_solo(ops)
    if found is None:
        return
    solo, neighbours = found
    raise ProgramNotBuildableError(
        f"{where}: `{solo}` обязан быть ЕДИНСТВЕННЫМ опом своей программы "
        f"(KIR-L002 — он владеет собственными транзакциями), а рядом с ним "
        f"здесь {len(ops) - 1} опов: {', '.join(neighbours[:6])}"
        + (" …" if len(neighbours) > 6 else "")
        + ". Компилятор такую программу НЕ ВОЗЬМЁТ, поэтому судить её "
          "пригодность значило бы выдать разрешение на непостроимое. "
          "СЛЕДУЮЩИЙ ХОД: разбей на ПАЧКУ — тело отдельно, "
          f"`{solo}` отдельной программой — и спроси "
          "`design_check([тело, лестница])`.")
    # THE NAME OF THE MOVE IS WHAT THE MODEL HAS, NOT WHAT WE HAVE. The
    # first edition was pointing at `check_bundle` — this door's name from
    # the outside. From inside the sandbox it does not exist at all:
    # `KIR-B006: NameError: name 'check_bundle' is not defined` (measured
    # 04.08). A refusal naming a nonexistent move is worse than a refusal
    # with no move at all: it spends a model turn checking our own typo.
    # `course.design_check` recognizes a bundle itself (`_is_bundle`), so
    # the correct shape from inside is with a list of programs.


def _shape_of(item: Any) -> str:
    """What kind of element this is — by KEYS, not by the caller's hope.

    THE ORDER OF THE CHECKS IS A CLAIM IN ITS OWN RIGHT, and until 04.08
    it was wrong. `op` is asked FIRST, because it is the one key present
    on every KIR operation and on no L1 node (those have `kind`/
    `op_name`/`params`/`source_element_id`; neither a node nor an atom has
    an `op` key — `lift._op_node` / `lift._atom_node`). The reverse order
    broke on a flat field: for `query_count`/`query_list` their OWN
    parameter is called `kind`, and the lawful operation
    `{"op": "query_count", "id": …, "kind": "wall"}` was declared an L1
    node — `check_ops` refused with KIR-V001 and sent the caller TO THE
    WRONG DOOR. This is exactly the mistake this section's header warns
    against: the refusal stated something about the input that it had
    never read, and steered the fix to the wrong place.
    """
    if not isinstance(item, Mapping):
        return ""
    if isinstance(item.get("op"), str):
        return _SHAPE_OPS
    # `kind` covers `{"kind": "atom"}` too: atoms are L1 as well, the
    # assembler counts them.
    if "kind" in item or "op_name" in item:
        return _SHAPE_L1
    # A program envelope. Asked LAST: `ops` is the weakest signal, and it
    # must yield to both of the previous ones, not the other way around.
    if isinstance(item.get("ops"), (list, tuple)):
        return _SHAPE_PROGRAM
    return ""


def _unwrap_program(program: Any) -> Sequence[Any]:
    """A bare list of operations, or an envelope `{"ops": [...]}` — both shapes are lawful.

    The sandbox returns a list, the compiler pipeline returns an
    envelope. Requiring the caller to unwrap it would mean introducing a
    THIRD shape where there are already two.
    """
    if isinstance(program, Mapping):
        if "ops" not in program:
            raise ProgramShapeError(
                f"это словарь без ключа `ops`: программа — это список операций "
                f"либо конверт {{'ops': [...]}}. Ключи, которые пришли: "
                f"{sorted(str(k) for k in program)[:12]}",
                keys=sorted(str(k) for k in program)[:12])
        program = program["ops"]
    if isinstance(program, (str, bytes)):
        raise ProgramShapeError(
            f"программа пришла как строка ({len(program)} символов), а нужен "
            f"СПИСОК операций. Строка — это не программа IR",
            got=type(program).__name__)
    if not isinstance(program, (list, tuple)):
        raise ProgramShapeError(
            f"программа пришла как {type(program).__name__}, а нужен список "
            f"операций", got=type(program).__name__)
    return program


def _require_shape(program: Any, want: str) -> list[Mapping[str, Any]]:
    """A list of the required shape, or a refusal naming the shape it saw and its door."""
    items = _unwrap_program(program)
    if not items:
        raise ProgramShapeError(
            "программа пуста: ни одной операции. Пустая программа — это не "
            "«здание без помещений», это отсутствие входа", ops=0)
    for index, item in enumerate(items):
        got = _shape_of(item)
        if got == want:
            continue
        where = f"ops[{index}]"
        if got:
            raise ProgramShapeError(
                f"{where} — это {_SHAPE_RU[got]}, а эта дверь принимает "
                f"{_SHAPE_RU[want]}. Их принимает {_SHAPE_DOOR[got]}. "
                f"Это утверждение О ФОРМЕ ВХОДА, а не о здании: помещения, "
                f"стены и двери здесь ещё не читались вовсе",
                index=index, got=got, want=want)
        if isinstance(item, Mapping):
            raise ProgramShapeError(
                f"{where}: ни `op` (операция KIR), ни `kind`/`op_name` (узел L1) "
                f"— по ключам не видно, что это. Ключи: "
                f"{sorted(str(k) for k in item)[:12]}",
                index=index, keys=sorted(str(k) for k in item)[:12])
        raise ProgramShapeError(
            f"{where} — это {type(item).__name__}, а операция — это объект "
            f"с полем `op`", index=index, got=type(item).__name__)
    return list(items)


def _adapt_ref(value: Any, kinds: Mapping[str, str]) -> Any:
    """A KIR reference -> a reference in the shape the assembler reads.

    Parsing proceeds BY THE ADDRESSEE'S KIND, not by the field's name, and
    this matters: the assembler resolves a level through `_ref_source_id`
    (needs `_id`), and an opening's host through `_ref_node` (needs ONE
    key, `ref`). Guessing by the field's name (`host`/`target`) would
    fall apart on the very first operation whose host is named
    differently.
    """
    if isinstance(value, Mapping):
        if value.get("by") == "ref":
            target = str(value.get("value"))
            kind = kinds.get(target)
            if kind == "create_level":
                # a level: `resolve_level` -> `_ref_source_id` -> `_id`
                return {**value, "_id": target}
            if kind is not None:
                # everything else — a reference to a NODE (an opening's host, etc.)
                return {"ref": _NODE_PREFIX + target}
            # The addressee is unknown: the reference leads nowhere. We
            # leave it as is — it will not resolve by either of the two
            # methods, and the assembly witness will say so in words
            # ("the level does not resolve against the program").
            return dict(value)
        return {k: _adapt_ref(v, kinds) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_adapt_ref(v, kinds) for v in value]
    return value


def _ops_to_nodes(ops: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """KIR operations -> the nodes the assembler reads. An INTERNAL conversion.

    It invents nothing: `source_element_id` is the operation's own `id`,
    not a new identifier, so any verdict finding is addressed by THE SAME
    string the model wrote in its script.
    """
    kinds: dict[str, str] = {}
    ids: list[str] = []
    for index, op in enumerate(ops):
        raw = op.get("id")
        oid = str(raw) if raw not in (None, "") else f"#{index}"
        ids.append(oid)
        kinds[oid] = str(op.get("op"))
    nodes: list[dict[str, Any]] = []
    for index, op in enumerate(ops):
        oid = ids[index]
        params = {key: _adapt_ref(value, kinds)
                  for key, value in op.items() if key not in ("op", "id")}
        nodes.append({
            "kind": "op",
            "op_name": str(op["op"]),
            "_id": _NODE_PREFIX + oid,
            "params": params,
            "source_element_id": oid,
        })
    return nodes


def spatial_model_from_ops(
    program: Any,
    *,
    building_id: str,
    profile: StageProfile | None = DESIGN_STAGE,
    close_tol_mm: float = PARTITION_CLOSE_TOL_MM,
    known_levels: Mapping[Any, float] | None = None,
) -> tuple[SpatialModel, BuildWitness]:
    """`SpatialModel` from KIR OPERATIONS — the verdict's outer door.

    `known_levels` — the caller's facts sheet, `{level id: elevation_mm}`, for
    levels the program addresses but does not create. The author got that id
    from somewhere (a document snapshot, `query_types(pool="levels")`); the same
    source carries the elevation, and nothing here invents one.

    Accepts exactly what the sandbox produces (`SandboxResult.ops`) and
    what the pipeline's `program` field carries. The L1 shape remains the
    decompiler's internal affair: the adapter lives here and is not
    exposed outward.
    """
    ops = _require_shape(program, _SHAPE_OPS)
    # LAWFULNESS BEFORE FITNESS. The door for ONE program must refuse on
    # what the compiler will not take: otherwise `ПРИГОДЕН` is issued to
    # something not buildable, and the model gets two green lights and one
    # wall (measured 04.08). In a bundle, this same set of ops is LAWFUL —
    # there the law is checked link by link, see
    # `spatial_model_from_bundle`.
    _refuse_if_unbuildable(ops, where="программа")
    return spatial_model_from_program(
        _ops_to_nodes(ops), building_id=building_id, profile=profile,
        close_tol_mm=close_tol_mm, known_levels=known_levels)


def check_ops(
    program: Any,
    *,
    building_id: str = "(программа KIR)",
    thresholds: Thresholds | None = None,
    known_levels: Mapping[Any, float] | None = None,
) -> DesignVerdict:
    """KIR OPERATIONS -> a verdict, in one call. Revit is never launched in between.

    This is a SELF-CHECK (`ModelSource.PROGRAM`): what the program
    DECLARES is judged, and `DesignVerdict.source` carries this
    distinction in the artifact itself.
    """
    model, witness = spatial_model_from_ops(program, building_id=building_id,
                                            known_levels=known_levels)
    return check_design(model, witness, thresholds=thresholds)


# ---------------------------------------------------------------------------------
# A BUNDLE OF PROGRAMS — THE BUILDING'S UNIT
#
# WHY THIS DOOR EXISTS AT ALL. The law "a large building is a BUNDLE of
# programs" already existed in this package (`tool_doc.CONSTRAINTS`), and
# `KIR-L002` is its special case: `create_stairs` owns its own
# transactions (`StairsEditScope`), so it is the ONLY op of its program.
# But the verdict judged ONE program. Out of two correct rules a third,
# incorrect one emerged: a multi-story building expressed as one program
# is unfit BY CONSTRUCTION — `HAB010` blocks every occupied level with no
# stair connection, `HAB001` falls apart right after, and a stair cannot
# be placed in the same program. Measured 03-04.08 (4 A/B runs, 2 models,
# 20 turns each): NOT A SINGLE building without blockers, all four with
# `stairs 0`, three stalled on exactly this pair. The strong model found
# the wall ITSELF and cobbled together a stair from 12 `create_floor` ops
# — the verdict honestly read `stairs 0` and blocked it.
#
# This is fixed here, not in the emitter: `KIR-L002` is a fact of the
# Revit API, not our whim. What was wrong was not the prohibition but the
# UNIT OF JUDGMENT.
# ---------------------------------------------------------------------------------

#: The separator in a bundle operation's qualified identifier: `p1/wall3`.
_BUNDLE_SEP = "/"


def _bundle_oid(position: int, oid: str) -> str:
    """An operation's identifier AT BUNDLE SCALE: the program's position + its own id.

    WHY WE ALWAYS QUALIFY, NOT ONLY ON COLLISION. `id` is unique WITHIN a
    program — that is the contract; between programs a match is LAWFUL,
    and two independently written programs will both call their first
    wall `wall1`. Qualifying on demand would produce a floating address:
    the same operation would be called `wall1` or `p2/wall1` depending on
    what is written in the NEIGHBORING program. A verdict finding is the
    address for a fix, and an address must depend only on what it points
    to.
    """
    return f"p{position}{_BUNDLE_SEP}{oid}"


def _ref_targets(value: Any) -> list[str]:
    """All `{"by": "ref"}` addressees inside the value, nested however deep.

    The traversal is GENERIC, not by field names, for the same reason as
    `_adapt_ref`: the host is called `host` for an opening, `target` for
    a tag, and `members` for a group, and a list of names would diverge
    from the schema on the very first new operation.
    """
    if isinstance(value, Mapping):
        if value.get("by") == "ref":
            return [str(value.get("value"))]
        out: list[str] = []
        for item in value.values():
            out.extend(_ref_targets(item))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_ref_targets(item))
        return out
    return []


def _rewrite_refs(value: Any, rename: Mapping[str, str]) -> Any:
    """Rewrite reference addressees to the qualified identifiers."""
    if isinstance(value, Mapping):
        if value.get("by") == "ref":
            target = str(value.get("value"))
            if target in rename:
                return {**value, "value": rename[target]}
            return dict(value)
        return {key: _rewrite_refs(item, rename) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rewrite_refs(item, rename) for item in value]
    return value


def _require_bundle(bundle: Any) -> list[list[Mapping[str, Any]]]:
    """A sequence of PROGRAMS, or a refusal naming what it saw and its door."""
    if isinstance(bundle, Mapping):
        if isinstance(bundle.get("ops"), (list, tuple)):
            raise ProgramShapeError(
                "это ОДНА программа, а дверь принимает ПАЧКУ — последовательность "
                "программ: [программа_тела, программа_лестницы]. Одну программу "
                f"судит {_SHAPE_DOOR[_SHAPE_OPS]}. Если здание правда одно"
                "этажное и лестница ему не нужна — идите туда",
                got=_SHAPE_PROGRAM)
        raise ProgramShapeError(
            "пачка пришла словарём без ключа `ops`: пачка — это СПИСОК программ. "
            f"Ключи, которые пришли: {sorted(str(k) for k in bundle)[:12]}",
            keys=sorted(str(k) for k in bundle)[:12])
    if isinstance(bundle, (str, bytes)):
        raise ProgramShapeError(
            f"пачка пришла как строка ({len(bundle)} символов), а нужен СПИСОК "
            "программ", got=type(bundle).__name__)
    if not isinstance(bundle, (list, tuple)):
        raise ProgramShapeError(
            f"пачка пришла как {type(bundle).__name__}, а нужен список программ",
            got=type(bundle).__name__)
    if not bundle:
        raise ProgramShapeError(
            "пачка пуста: ни одной программы. Пустая пачка — это не «здание без "
            "помещений», это отсутствие входа", programs=0)
    out: list[list[Mapping[str, Any]]] = []
    for index, item in enumerate(bundle):
        position = index + 1
        shape = _shape_of(item)
        # A bundle's element is a PROGRAM. An operation and an L1 node
        # turn up here precisely when the caller fed a single program
        # WHERE a bundle was expected — and the refusal must name that,
        # rather than parsing the operation as a program.
        if shape in (_SHAPE_OPS, _SHAPE_L1):
            raise ProgramShapeError(
                f"пачка[{index}] — это {_SHAPE_RU[shape]}, а элемент пачки — это "
                f"ПРОГРАММА целиком ({_SHAPE_RU[_SHAPE_PROGRAM]}). Похоже, подан "
                f"СПИСОК ОПЕРАЦИЙ вместо списка программ: его принимает "
                f"{_SHAPE_DOOR[shape]}. Это утверждение О ФОРМЕ ВХОДА — стены и "
                f"помещения здесь ещё не читались",
                index=index, got=shape, want=_SHAPE_PROGRAM)
        try:
            ops = _require_shape(item, _SHAPE_OPS)
        except ProgramShapeError as exc:
            raise ProgramShapeError(
                f"пачка[{index}] (программа {position}): {exc.message_ru}",
                index=index, **exc.detail) from exc
        out.append(ops)
    return out


def _merge_bundle(
    programs: Sequence[Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str], list[int]]:
    """A bundle -> ONE list of the building's operations. The bundle's order is preserved.

    ORDER MATTERS, and that is why the merge is a concatenation, not a
    set union: the programs execute sequentially, and a level created by
    the first exists for the second. This is exactly what the stair
    program stands on — it addresses the level BY NAME (`base_level` does
    not accept `ref`: `ref_kinds` is empty, measured), and the name
    resolves because the first program's `create_level` sits ABOVE it in
    this same list.

    Returns: the operations, the COLLIDING identifiers, the programs'
    sizes.
    """
    own_ids: list[list[str]] = []
    for ops in programs:
        ids: list[str] = []
        for index, op in enumerate(ops):
            raw = op.get("id")
            # The same substitution as in `_ops_to_nodes`: otherwise an
            # unnamed operation would get one address here and a different
            # one there.
            ids.append(str(raw) if raw not in (None, "") else f"#{index}")
        own_ids.append(ids)

    merged: list[dict[str, Any]] = []
    for position0, ops in enumerate(programs):
        position = position0 + 1
        ids = own_ids[position0]
        mine = set(ids)
        rename = {oid: _bundle_oid(position, oid) for oid in ids}
        for index, op in enumerate(ops):
            for target in _ref_targets(op):
                if target in mine:
                    continue
                elsewhere = [other + 1 for other, other_ids in enumerate(own_ids)
                             if other != position0 and target in set(other_ids)]
                if elsewhere:
                    raise BundleContractError(
                        f"программа {position}, операция `{ids[index]}`: ссылка "
                        f"{{\"by\": \"ref\"}} на `{target}` ведёт в программу "
                        f"{elsewhere[0]} этой же пачки. Ссылка живёт ВНУТРИ "
                        f"программы: соседняя программа — отдельная транзакция, "
                        f"и к её исполнению id `{target}` уже не существует. "
                        f"Адресуй по ИМЕНИ ({{\"by\": \"name\"}}) — имя переживает "
                        f"границу программы, ссылка нет",
                        program=position, op_id=ids[index], ref=target,
                        defined_in=elsewhere[0])
                # The addressee is unknown to the ENTIRE bundle — this is a
                # dangling reference, not a violation of the bundle's law.
                # The assembly witness speaks about it in the same words
                # as for a single program: folding two different
                # diagnoses into one code would lose the address for the
                # fix.
            body = {key: value for key, value in op.items() if key != "id"}
            body = _rewrite_refs(body, rename)
            merged.append({**body, "id": rename[ids[index]]})

    seen: Counter = Counter()
    for ids in own_ids:
        seen.update(set(ids))
    collisions = sorted(oid for oid, count in seen.items() if count > 1)
    return merged, collisions, [len(ids) for ids in own_ids]


def spatial_model_from_bundle(
    bundle: Any,
    *,
    building_id: str,
    profile: StageProfile | None = DESIGN_STAGE,
    close_tol_mm: float = PARTITION_CLOSE_TOL_MM,
) -> tuple[SpatialModel, BuildWitness]:
    """`SpatialModel` from a BUNDLE of programs — the building, not one of its programs."""
    programs = _require_bundle(bundle)
    # THE LAW IS CHECKED LINK BY LINK, NOT ON THE MERGED WHOLE, and that
    # is exactly the point of a bundle: `create_stairs` next to walls is
    # UNLAWFUL in one program and PERFECTLY LAWFUL in a bundle, where it
    # is its own link. Had we checked the merged list, the bundle would
    # refuse itself, that is, the door would forbid the very shape it was
    # set up for.
    for index, program in enumerate(programs, start=1):
        _refuse_if_unbuildable(
            program.get("ops", ()) if isinstance(program, Mapping) else program,
            where=f"звено пачки p{index}")
    ops, collisions, sizes = _merge_bundle(programs)
    # The merged list arrives here ALREADY checked link by link — so we
    # build from it directly, bypassing the single-program door and its
    # law.
    model, witness = spatial_model_from_program(
        _ops_to_nodes(ops), building_id=building_id, profile=profile,
        close_tol_mm=close_tol_mm)
    witness.note("bundle",
                 f"пачка из {len(programs)} программ судится как ОДНО здание "
                 f"(операций по программам: {sizes}); идентификаторы операций "
                 f"квалифицированы позицией программы — `p1/wall3`",
                 len(programs))
    if collisions:
        # NAMED, rather than silently resolved in favor of the last
        # program: without this record, two different walls sharing
        # `wall1` would merge into one finding, and the reader would fix
        # the wrong one.
        witness.note("bundle_id_collision",
                     "идентификаторы, занятые более чем одной программой пачки "
                     f"(это ЗАКОННО — id уникален внутри программы): "
                     f"{', '.join(collisions[:12])}"
                     + (" …" if len(collisions) > 12 else "")
                     + ". Каждый развёрнут в свой `p<номер>/<id>`",
                     len(collisions))
    return model, witness


def check_bundle(
    bundle: Any,
    *,
    building_id: str = "(пачка программ KIR)",
    thresholds: Thresholds | None = None,
) -> DesignVerdict:
    """A BUNDLE of KIR programs -> a verdict about the BUILDING, in one call.

    The building's unit is the BUNDLE, not the program: the body is
    separate, the stairs are separate (`KIR-L002`). This door judges
    their UNION, so `HAB010`/`HAB001` see the stair that Revit's law would
    not allow to be placed in the body.

    The input's kind is the same as for `check_ops` — KIR operations; what
    differs is the UNIT. This is a SELF-CHECK (`ModelSource.PROGRAM`):
    what the bundle DECLARES is judged.
    """
    model, witness = spatial_model_from_bundle(bundle, building_id=building_id)
    return check_design(model, witness, thresholds=thresholds)


#: Selector shapes that name a level living OUTSIDE the program.
_EXTERNAL_LEVEL_SELECTORS = ("element_id", "unique_id")


def _referenced_level_ids(ops: Sequence[Mapping[str, Any]],
                          produced: set[str]) -> list[str]:
    """Ids of levels the program USES but does not create, in first-use order.

    Order is the program's own, not sorted: with no elevation there is nothing
    to sort by, and inventing an order would invent a storey sequence.
    """
    seen: list[str] = []
    for node in ops:
        params = node.get("params") or {}
        for key in ("level", "top_level", "base_level"):
            ref = params.get(key)
            if not isinstance(ref, Mapping):
                continue
            if ref.get("by") not in _EXTERNAL_LEVEL_SELECTORS:
                continue
            value = ref.get("value")
            if value is None:
                continue
            ident = str(value)
            if ident in produced or ident in seen:
                continue
            seen.append(ident)
    return seen


def spatial_model_from_program(
    nodes: Sequence[Mapping[str, Any]],
    *,
    building_id: str,
    profile: StageProfile | None = DESIGN_STAGE,
    close_tol_mm: float = PARTITION_CLOSE_TOL_MM,
    diagnostics: Sequence[Any] = (),
    known_levels: Mapping[Any, float] | None = None,
) -> tuple[SpatialModel, BuildWitness]:
    """`SpatialModel` from L1 NODES. A self-check: what is declared is judged.

    THE INPUT HERE IS THE DECOMPILER'S INTERNAL SHAPE
    (`{"kind": "op", "op_name": …, "params": {…}, "source_element_id":
    …}`), not KIR operations. The outer door is
    :func:`spatial_model_from_ops` / :func:`check_ops`: they accept
    exactly what the sandbox returns, and the shape adapter lives INSIDE
    this module.

    Exactly the numbers carried by the ops' parameters are read. No field
    is taken from L0 around the program — otherwise the gate would be
    comparing the decompile against itself.

    `diagnostics` are optional `LiftDiagnostic`s from the same lift. They
    take no part in the assembly: they give the gate a TYPED reason why
    an element did not become an operation, so that the population
    difference is explained by `no_lifter`/`missing_geometry`, not by a
    generic phrase.
    """
    # THE SHAPE IS CHECKED BEFORE ASSEMBLY, and this is not pedantry.
    # Before 03.08 it was possible to pass KIR operations here: none of
    # them had a `kind` key, `ops` came out empty, and the degenerate gate
    # `_run_v2` printed "HAB000 — model has no rooms" — and this was
    # UNTRUE when the program had live `create_room` ops, lying in exactly
    # the direction the model would run off to fix.
    nodes = _require_shape(nodes, _SHAPE_L1)
    witness = BuildWitness(source=ModelSource.PROGRAM, building_id=building_id)
    ops = [node for node in nodes if node.get("kind") == "op"]
    atoms = sum(1 for node in nodes if node.get("kind") == "atom")
    if atoms:
        witness.note("atoms",
                     "элементов, не ставших операциями (в программе их нет)", atoms)
    for diagnostic in diagnostics:
        category = getattr(diagnostic, "category", None)
        reason = getattr(diagnostic, "reason", None)
        if not category or reason is None:
            continue
        code = getattr(reason, "value", str(reason))
        witness.lift_atoms.setdefault(category, Counter())[code] += 1

    # --- levels -----------------------------------------------------------------
    raw_levels: list[tuple[str, str, float]] = []
    for node in ops:
        if node["op_name"] != "create_level":
            continue
        params = node["params"]
        name = str(params.get("name") or f"level@{params['elev_mm']}")
        raw_levels.append((node["source_element_id"], name, float(params["elev_mm"])))
    # 🔴 LEVELS THE PROGRAM ONLY REFERENCES ARE LEVELS TOO (13.09.2026).
    # A section that goes into an EXISTING document addresses its levels by
    # `element_id`/`unique_id` — that IS the production case — and until this
    # day such a level existed for nobody here: `elevations` held only ids that
    # `create_level` produced, `resolve_level` returned None, and every wall and
    # room hanging on that level was dropped in silence. Measured on one program
    # with one difference: `create_level` → rooms 1, walls 4, rules 7 of 20;
    # `{by: element_id}` → rooms 0, walls 0, rules 0 of 20 and HAB000 "model has
    # no rooms". The refusal was honest and the verdict was empty, which is the
    # worst pair: nothing checked, on the only case that ships.
    #
    # Such a level enters WITHOUT an elevation unless the caller supplies one
    # (`known_levels`, the same facts sheet the author took the id from). Offline
    # there is no document to read it from, and inventing 0.0 would make the
    # ground-level band call an arbitrary floor "ground" — see `Level`.
    referenced = _referenced_level_ids(ops, {lid for lid, _, _ in raw_levels})
    supplied = {str(key): value for key, value in (known_levels or {}).items()}
    for ref_id in referenced:
        elevation = supplied.get(ref_id)
        raw_levels.append((ref_id, f"уровень {ref_id} (существующий)",
                           None if elevation is None else float(elevation)))
    # Known elevations sort bottom→top; an unknown one cannot be placed among
    # them and goes last, keeping the order the program named it in.
    raw_levels.sort(key=lambda item: (item[2] is None, item[2] if item[2] is not None else 0.0))
    external_ids = set(referenced)
    levels = [Level(id=lid, name=name, elevation_mm=elev, index=index,
                    external=lid in external_ids,
                    elevation_source=("facts" if lid in external_ids and elev is not None
                                      else None if elev is None else "program"))
              for index, (lid, name, elev) in enumerate(raw_levels)]
    level_by_name = {name: lid for lid, name, _ in raw_levels}
    elevations = {lid: elev for lid, _, elev in raw_levels}

    def datum(level_id: str) -> float:
        """The z the program's geometry is measured FROM.

        🔴 RELATIVE GEOMETRY IS KNOWN EVEN WHEN THE ABSOLUTE ELEVATION IS NOT.
        A level the program only references has no elevation offline (see
        `Level.elevation_mm`), but every wall, floor and room on it is placed
        RELATIVE to it, and those distances are exactly what the geometric rules
        read. So the local datum for an unknown level is 0.0 — its own floor —
        and the model still says `elevation_mm is None`, so the rules that need
        the ABSOLUTE number (the ground-level band) stay honest about not having
        it. Folding the two into one fabricated 0.0 would have made "unknown"
        indistinguishable from "at grade".
        """
        value = elevations.get(level_id)
        return 0.0 if value is None else float(value)

    def resolve_level(ref: Any) -> str | None:
        name = _ref_name(ref)
        if name is not None and name in level_by_name:
            return level_by_name[name]
        source = _ref_source_id(ref)
        if source is not None and source in elevations:
            return source
        # 🔴 A THIRD SELECTOR SHAPE, WITHOUT WHICH THE WHOLE PROGRAM PATH IS
        # MUTE ON A LIVE RECORDING (measured 17.08.2026 on `13A-RD-AR-K2`).
        # `_ref_source_id` reads the `_id` field, which is set by
        # GROUNDING; the author's program does not carry it, and
        # `{"by": "element_id", "value": "11835959"}` — exactly what a
        # model writes after getting an id from
        # `query_types(pool="levels")` — resolved NO WAY AT ALL. The wall
        # came out `level_id is None`, that is, the verdict about the
        # DECLARED answered "0 walls" with six actually built.
        #
        # There is no shape collision here by construction: the id of the
        # author's `create_level` operation is an author-chosen string
        # (`L1`), while `value` under `by=element_id` is a Revit element
        # number. They can coincide only when the author THEMSELF named
        # the operation with the element's number, and then the
        # coincidence is exactly what was meant.
        if isinstance(ref, Mapping) and ref.get("by") == "element_id":
            value = ref.get("value")
            if value is not None and str(value) in elevations:
                return str(value)
        return None

    # --- walls --------------------------------------------------------------
    walls: list[Wall] = []
    segs_by_level: dict[str, list[_WallSeg]] = defaultdict(list)
    wall_node_to_id: dict[str, str] = {}
    for node in ops:
        if node["op_name"] != "create_wall":
            continue
        params = node["params"]
        level_id = resolve_level(params.get("level"))
        if level_id is None:
            witness.note("wall_level_unresolved",
                         "у стены уровень не разрешается по программе — в план не идёт")
            witness.drop("walls", "уровень не разрешается по программе")
            continue
        if params.get("arc"):
            # An arced wall: the subdivision works on straight segments, a
            # chord would narrow the room silently. The wall goes into the
            # model (HAB041/HAB042 see it), but not into the subdivision.
            witness.note("wall_arc",
                         "дуговая стена: в планарное разбиение не включена (хорда "
                         "изменила бы площадь молча)")
        p0 = (float(params["p0_mm"][0]), float(params["p0_mm"][1]))
        p1 = (float(params["p1_mm"][0]), float(params["p1_mm"][1]))
        base = datum(level_id) + float(params.get("base_offset_mm") or 0.0)
        top_ref = params.get("top_level")
        top_level_id = resolve_level(top_ref) if top_ref else None
        if top_level_id is not None:
            top = datum(top_level_id) + float(params.get("top_offset_mm") or 0.0)
            height_known = True
        elif params.get("height_mm") is not None:
            top = base + float(params["height_mm"])
            height_known = True
        else:
            top, height_known = base, False
        wall_id = node["source_element_id"]
        wall_node_to_id[node["_id"]] = wall_id
        walls.append(Wall(id=wall_id, level_id=level_id, curve=(p0, p1),
                          height_mm=abs(top - base), is_structural=False))
        if not params.get("arc"):
            segs_by_level[level_id].append(_WallSeg(
                wall_id=wall_id, level_id=level_id, p0=p0, p1=p1,
                height_mm=abs(top - base), height_known=height_known))
    walls_by_id = {wall.id: wall for wall in walls}

    # --- room separators: there is a boundary, there is no wall -----------------
    #
    # A SEPARATOR ENCLOSES A ROOM BUT IS NOT A WALL, and both halves of
    # this sentence bear weight. First: a room opening onto a corridor has
    # no fourth wall and should have none — its boundary is held by
    # `create_room_separator`, and a subdivision built from `create_wall`
    # alone does not enclose such a room AT ALL (measured: no polygon, the
    # cause "not_enclosed_by_walls," then cascading into "area 0" from
    # HAB020 and "no window" from HAB030). Second: the separator does not
    # go into `SpatialModel.walls` — HAB041/HAB042/HAB050 read walls, and
    # a separator among them would be a zero-thickness wall that can
    # neither have an opening cut into it nor bear a load.
    #
    # `height_known=False` is not a stub but a fact: a separator has no
    # height. `_height_from_enclosure` SKIPS such segments before counting
    # the perimeter, so they do not dilute the height vote (verified by a
    # test).
    for node in ops:
        if node["op_name"] != "create_room_separator":
            continue
        params = node["params"]
        level_id = resolve_level(params.get("level"))
        if level_id is None:
            witness.note("separator_level_unresolved",
                         "у разделителя помещений уровень не разрешается по "
                         "программе — в разбиение не идёт")
            witness.drop("room_separators", "уровень не разрешается по программе")
            continue
        path = params.get("path") or []
        if len(path) < 2:
            witness.note("separator_degenerate",
                         "разделитель помещений короче двух точек — границы нет")
            continue
        sep_id = node["source_element_id"]
        for index in range(len(path) - 1):
            p0 = (float(path[index][0]), float(path[index][1]))
            p1 = (float(path[index + 1][0]), float(path[index + 1][1]))
            segs_by_level[level_id].append(_WallSeg(
                # A prefix so a separator's segment can never be confused
                # with a wall's address in any finding.
                wall_id=f"separator::{sep_id}#{index}", level_id=level_id,
                p0=p0, p1=p1, height_mm=0.0, height_known=False))

    # --- rooms: planar subdivision -----------------------------------------------
    room_ops: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    unplaced = 0
    for node in ops:
        if node["op_name"] != "create_room":
            continue
        level_id = resolve_level(node["params"].get("level"))
        if level_id is None:
            unplaced += 1
            continue
        room_ops[level_id].append(node)
    if unplaced:
        witness.note("room_level_unresolved",
                     "у помещения уровень не разрешается по программе", unplaced)
        witness.drop("rooms", "уровень не разрешается по программе", unplaced)

    rooms: list[Room] = []
    room_polys: dict[str, Polygon] = {}
    rooms_by_level: dict[str, list[str]] = defaultdict(list)
    faces_total = 0
    heights_known = 0
    # Only levels with a KNOWN elevation can be ordered; an unknown one has no
    # place in a storey sequence, and giving it one would invent the sequence.
    ordered_elevations = sorted(z for z in elevations.values() if z is not None)
    # 🔴 THE SUBDIVISION IS BUILT FROM LEVELS WITH WALLS, NOT FROM LEVELS
    # WITH ROOMS.
    #
    # The earlier edition went through `room_ops.items()`, that is,
    # closure was computed ONLY where a room asked for it. But closure is
    # a fact about WALLS, not about rooms, and a whole class of answers
    # depended on this.
    #
    # Measured 15.08.2026, four programs differing exactly in assembly:
    #
    #     4 walls closed, no rooms         rules 0/20, HAB000 "no rooms"
    #     4 walls with a 1500 mm gap, no rooms  rules 0/20, HAB000 — THE SAME
    #     4 walls closed + a room          rules 8/20
    #     4 walls with a gap + a room      rules 5/20, HAB060 "no measurable
    #                                       contour" — the defect is NAMED
    #
    # That is, the apparatus can see an unclosed contour and stays silent
    # in exactly the case where the "striped wall" test used to break:
    # there are walls, there are no rooms. In a separate measurement with
    # the same instrument: a closed box gives 1 face of 24 m² and names
    # the FOUR walls that closed it; a 1500 mm gap gives 0 faces.
    #
    # No rule is added and the verdict does NOT change: with no rooms,
    # the rules still have nothing to judge. One thing changes — the
    # witness now CARRIES A NUMBER (`partition_faces`) that did not exist
    # before, and it can be used to say "your walls closed nothing." The
    # field had been in `BuildWitness` from the very start and simply was
    # never populated on this path.
    for level_id in sorted(set(room_ops) | set(segs_by_level)):
        level_rooms = room_ops.get(level_id, ())
        if level_id not in elevations:
            # A DEFENSIVE LINE, AND IT IS NAMED HONESTLY: unreachable on
            # today's input. A wall whose level does not resolve against
            # the program never even reaches `segs_by_level` — it is
            # discarded by the reading above, with the already-named cause
            # `wall_level_unresolved` (`BuildNote`).
            #
            # The first edition of this fix introduced a SECOND cause here
            # (`level_elevation_unknown`) for something that already had
            # one — and the test caught it. Two names for one fact would
            # diverge on the very first reader that counts by only one of
            # them.
            continue
        base_elev = datum(level_id)
        next_level_z = next((z for z in ordered_elevations if z > base_elev), None)
        partition = _Partition.build(segs_by_level.get(level_id, ()), close_tol_mm)
        faces_total += len(partition.faces)
        claims: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        homeless: list[Mapping[str, Any]] = []
        for node in level_rooms:
            xy = node["params"]["xy"]
            face = partition.face_containing(Point(float(xy[0]), float(xy[1])))
            if face is None:
                homeless.append(node)
            else:
                claims[face].append(node)
        assigned: dict[str, tuple[Polygon, list[_WallSeg]]] = {}
        for face_index, claimants in claims.items():
            if len(claimants) > 1:
                # A face claimed by several points is given to none of
                # them: the subdivision did not separate them, and a
                # choice would be a guess.
                #
                # A NOTE TO THE NEXT WAVE (03.08). The outward channel
                # here is FLAT: `shared_face_room_ids` is a list of
                # identifiers with no pairing, and it cannot say WHO
                # shared the face WITH WHOM. Because of this, the finding
                # "Room X has no measurable boundary polygon" accuses an
                # INNOCENT room: the guilty one is whichever fell into its
                # same face, and there is nothing to name it with. This is
                # fixed by the channel's shape, not by the message's text:
                # the channel must carry `face -> [claimant ids]` (for
                # example `witness.shared_faces: list[list[str]]`), and
                # then the message will be able to name the neighbor by
                # name. Left as is here ON PURPOSE: changing the channel's
                # shape also touches the witness's readers, and that is
                # separate work, not a side fix.
                for node in claimants:
                    witness.shared_face_room_ids.append(node["source_element_id"])
                    witness.unmeasured_reasons["shared_face"] += 1
                homeless.extend(claimants)
                continue
            node = claimants[0]
            face = partition.faces[face_index]
            assigned[node["source_element_id"]] = (
                face, partition.bounding_segments(face, close_tol_mm))
        shared = set(witness.shared_face_room_ids)
        for node in homeless:
            if node["source_element_id"] not in shared:
                witness.unmeasured_reasons["not_enclosed_by_walls"] += 1
        for node in level_rooms:
            room_id = node["source_element_id"]
            name = str(node["params"].get("name") or "")
            # A function NAMED by the program's author (`create_room.function`,
            # 28.08.2026): there is no need to guess from the name when
            # the answer is already given.
            declared_function = node["params"].get("function") or None
            got = assigned.get(room_id)
            if got is None:
                witness.unmeasured_room_ids.append(room_id)
                boundary: list[tuple[float, float]] = []
                area = 0.0
                height = None
            else:
                face, bounding = got
                room_polys[room_id] = face
                boundary = _ring(face)
                area = round(face.area / _MM2_PER_M2, 2)
                height = _height_from_enclosure(
                    bounding, base_z=datum(level_id),
                    next_level_z=next_level_z)
                if height is not None:
                    heights_known += 1
            rooms.append(Room(
                id=room_id, name=name, level_id=level_id,
                function=classify_room(name, explicit=declared_function),
                # A room's name on this path is an input field
                # (`create_room.name`) written by the program's author: the
                # kind is `declared` (see `function_provenance`), and it is
                # authored regardless of whether the lexicon recognized
                # that name.
                #
                # 🔴 AND IF THE AUTHOR NAMED THE FUNCTION DIRECTLY
                # (`create_room.function`), the kind is `explicit`, and
                # this is NOT the same thing. `declared` means "we
                # inferred the kind from a string the author wrote";
                # `explicit` means "the author named the kind themselves."
                # Both are `authored`, but telling them apart must be
                # possible: under the first lies our guess about the
                # word's meaning, under the second lies nothing but the
                # author's own answer.
                function_source="explicit" if declared_function else "declared",
                # Area = the area of THE SAME polygon: the program does
                # not declare an area separately, so there cannot be a
                # discrepancy here between declared and derived. HAB060
                # will remain an honest witness of the unmeasurable ones.
                area_m2=area, height_mm=height, boundary=boundary,
                has_window=False,
                height_source="wall_enclosure" if height is not None else None,
            ))
            rooms_by_level[level_id].append(room_id)
    witness.rooms_total = len(rooms)
    witness.rooms_measured = len(room_polys)
    witness.partition_faces = faces_total
    witness.rooms_with_height = heights_known
    witness.height_source = ("длинновзвешенная высота замкнувших стен, ДОХОДЯЩИХ до "
                             "следующего уровня (БЕЗ толщин пола/потолка)")

    # --- openings ---------------------------------------------------------------
    def program_location(node: Mapping[str, Any]) -> tuple[float, float] | None:
        host_node = _ref_node(node["params"].get("host"))
        if host_node is None:
            return None
        wall_id = wall_node_to_id.get(host_node)
        wall = walls_by_id.get(wall_id) if wall_id else None
        if wall is None:
            return None
        (x0, y0), (x1, y1) = wall.curve
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length <= 0.0:
            return None
        offset = float(node["params"].get("offset_mm") or 0.0)
        return (x0 + dx / length * offset, y0 + dy / length * offset)

    def program_host(node: Mapping[str, Any]) -> str | None:
        host_node = _ref_node(node["params"].get("host"))
        return wall_node_to_id.get(host_node) if host_node else None

    doors, windows = _openings(
        door_elements=[n for n in ops if n["op_name"] == "create_door"],
        window_elements=[n for n in ops if n["op_name"] == "create_window"],
        walls_by_id=walls_by_id,
        room_polys=room_polys,
        rooms_by_level=rooms_by_level,
        witness=witness,
        profile=profile,
        location_of=program_location,
        # The program does NOT express an opening's dimensions: `symbol`
        # names the family type, the sizes live in the family, and the
        # grounding pool carries `params: null`.
        size_of=lambda node: None,
        host_of=program_host,
        id_of=lambda node: node["source_element_id"],
    )

    witness.curtain_panels = sum(1 for node in ops
                                 if node["op_name"] == "set_curtain_panel")

    # --- stairs -------------------------------------------------------------------
    stairs: list[Stair] = []
    for node in ops:
        if node["op_name"] != "create_stairs":
            continue
        params = node["params"]
        base_id = resolve_level(params.get("base_level"))
        top_id = resolve_level(params.get("top_level"))
        if base_id is None or top_id is None:
            witness.note("stair_level_unresolved",
                         "у лестницы уровень не разрешается по программе")
            witness.drop("stairs", "уровень не разрешается по программе")
            continue
        width = params.get("width_mm")
        footprint: list[tuple[float, float]] = []
        if width and params.get("p0_mm") is not None:
            p0 = (float(params["p0_mm"][0]), float(params["p0_mm"][1]))
            p1 = (float(params["p1_mm"][0]), float(params["p1_mm"][1]))
            band = LineString([p0, p1]).buffer(float(width) / 2.0, cap_style=2)
            if not band.is_empty:
                footprint = _ring(band)
        elif params.get("spiral") is not None:
            # A SPIRAL FLIGHT (09.08): it has NO plan here, and this is a
            # named gap, not silence. A straight band around a segment
            # does not describe a spiral at all — its trace is an annular
            # sector — and substituting a straight band here would give
            # HAB012 a plausibly WRONG plan. Empty is more honest: a
            # flight with no width behaves exactly the same way.
            witness.note("stair_spiral_no_footprint",
                         "винтовой марш: `create_stairs.spiral` — кольцевой "
                         "сектор, полосой вокруг отрезка он не выражается, "
                         "и плана марша здесь нет")
        else:
            witness.note("stair_no_width",
                         "`create_stairs.width_mm` не задан — плана марша нет, "
                         "HAB012 сравнивать нечего")
        stairs.append(Stair(
            id=node["source_element_id"], base_level_id=base_id, top_level_id=top_id,
            base_z=datum(base_id), top_z=datum(top_id),
            run_width_mm=float(width) if width else None,
            riser_count=None, tread_depth_mm=None,
            footprint=footprint, kind="element",
            # FOR THE PROGRAM, THE TOP IS NAMED BY THE AUTHOR:
            # `create_stairs.top_level` is an input field, not our
            # inference, so the kind is `declared` (see
            # `stair_provenance`).
            top_level_source="declared",
        ))

    witness.counts = {
        "levels": len(levels), "rooms": len(rooms), "walls": len(walls),
        "doors": len(doors), "windows": len(windows), "stairs": len(stairs),
    }
    model = SpatialModel(building_id=building_id, levels=levels, rooms=rooms,
                         doors=doors, windows=windows, stairs=stairs, walls=walls)
    _fill_inputs(witness, model)
    return model, witness


# ---------------------------------------------------------------------------------
# 8. OPENINGS — shared code for both paths (different NUMBERS, one geometry)
# ---------------------------------------------------------------------------------

#: An input key -> how it reads to a human. The keys are collected from
#: the FINISHED model (`_fill_inputs`), not described in words: a gate
#: discrepancy is explained by a number that can be rechecked, otherwise
#: the explanation is a guess spoken with the intonation of a fact.
_INPUT_RU: dict[str, str] = {
    "rooms": "помещений в модели",
    "rooms_measured": "помещений с полигоном",
    "rooms_with_height": "помещений с известной высотой",
    "rooms_classified": "помещений с распознанной функцией",
    "doors": "дверей",
    "doors_with_width": "дверей с известной шириной проёма",
    "doors_with_adjacency": "дверей, у которых нашлась хотя бы одна сторона",
    "windows": "окон",
    "windows_with_size": "окон с ИЗМЕРЕННЫМ габаритом",
    "windows_joined": "окон, привязанных к помещению",
    "walls": "стен",
    "structural_walls": "стен с признаком «несущая»",
    "levels": "уровней",
    "stairs": "лестниц",
    "stairs_with_footprint": "лестниц с планом марша",
    "stairs_with_geometry": "лестниц с полной геометрией (ширина+подступенки+проступь)",
    "rooms_stair": "помещений, распознанных как лестничная клетка",
    "occupied_levels": "уровней с помещениями",
    "curtain_panels": "витражных заполнений",
}

#: What EACH rule reads from the model. The table is taken from the
#: rules' own source code (`kir/checker/rules/*.py`, read on 03.08), not
#: from their names: rule HAB042, for instance, reads a door's width,
#: which is not visible from the name "apartment envelope."
_RULE_INPUTS: dict[str, tuple[str, ...]] = {
    "HAB001": ("rooms", "doors_with_adjacency"),
    "HAB002": ("rooms", "doors_with_adjacency", "rooms_classified"),
    "HAB003": ("rooms", "doors_with_adjacency", "stairs", "rooms_classified"),
    "HAB004": ("rooms", "doors_with_adjacency", "rooms_classified"),
    "HAB010": ("levels", "stairs", "rooms_classified", "doors_with_adjacency"),
    "HAB011": ("stairs", "stairs_with_geometry"),
    "HAB012": ("stairs", "stairs_with_footprint"),
    "HAB020": ("rooms_measured", "rooms_classified"),
    "HAB021": ("rooms_measured", "rooms_classified"),
    "HAB022": ("rooms_with_height",),
    "HAB030": ("rooms_classified", "windows_joined", "windows_with_size"),
    "HAB031": ("rooms_classified", "windows_with_size"),
    "HAB040": ("rooms_measured",),
    "HAB041": ("doors", "doors_with_width", "doors_with_adjacency", "walls"),
    "HAB042": ("rooms_measured", "doors_with_width", "walls"),
    "HAB050": ("structural_walls",),
    # 🔴 `windows_with_size` WAS ADDED ON 30.08.2026 (F-254). Since this
    # fix, HAB060 NAMES the substituted glazing area, that is, it reads
    # the opening's dimensions — and a path discrepancy on it must
    # REDUCE TO THE INPUT, rather than stay `UNATTRIBUTED`. The program
    # does not carry a dimension (`windows_with_size` is zero for it), so
    # the finding exists only on its side; without this line the gate
    # would honestly say "cause not established" about a cause that is
    # established.
    "HAB060": ("rooms_measured", "windows_joined", "windows_with_size"),
    "HAB061": ("doors", "doors_with_adjacency"),
    "HAB062": ("rooms_classified", "rooms_measured"),
    "HAB063": ("rooms_measured", "levels"),
}

#: A rule input -> the population whose difference it inherits. Needed so
#: that "classified 5 fewer" does not look like a phenomenon of its own
#: when the rooms themselves are 13 fewer.
_INPUT_GOVERNED_BY: dict[str, str] = {
    "rooms_measured": "rooms",
    "rooms_with_height": "rooms",
    "rooms_classified": "rooms",
    "doors_with_width": "doors",
    "doors_with_adjacency": "doors",
    "windows_with_size": "windows",
    "windows_joined": "windows",
    "structural_walls": "walls",
    "stairs_with_footprint": "stairs",
    "stairs_with_geometry": "stairs",
}

#: An element kind -> the L0 category it is lifted from. Needed to
#: explain a population difference by a TYPED lift cause, not by a
#: platitude.
_POPULATION_CATEGORY: dict[str, str] = {
    "curtain_panels": "OST_CurtainWallPanels",
    "rooms": "OST_Rooms",
    "doors": "OST_Doors",
    "windows": "OST_Windows",
    "walls": "OST_Walls",
    "levels": "OST_Levels",
    "stairs": "OST_Stairs",
}


def _fill_inputs(witness: BuildWitness, model: SpatialModel) -> None:
    """Collect all rule inputs from the finished model. One pass, one place."""
    witness.rooms_stair = sum(1 for r in model.rooms
                              if r.function is RoomFunction.ЛЕСТНИЦА)
    witness.occupied_levels = len({r.level_id for r in model.rooms})
    witness.inputs = {
        "levels": len(model.levels),
        "rooms": len(model.rooms),
        "rooms_measured": witness.rooms_measured,
        "rooms_with_height": sum(1 for r in model.rooms if r.height_mm is not None),
        "rooms_classified": sum(1 for r in model.rooms
                                if r.function is not RoomFunction.ПРОЧЕЕ),
        "doors": len(model.doors),
        "doors_with_width": sum(1 for d in model.doors if d.width_mm > 0.0),
        "doors_with_adjacency": sum(1 for d in model.doors
                                    if d.from_room_id or d.to_room_id),
        "windows": len(model.windows),
        "windows_with_size": sum(1 for w in model.windows
                                 if w.height_mm is not None and w.width_mm > 0.0),
        "windows_joined": sum(1 for w in model.windows if w.room_id),
        "walls": len(model.walls),
        "structural_walls": sum(1 for w in model.walls if w.is_structural),
        "stairs": len(model.stairs),
        "stairs_with_footprint": sum(1 for s in model.stairs if s.footprint),
        "stairs_with_geometry": sum(
            1 for s in model.stairs
            if s.run_width_mm is not None and s.riser_count is not None
            and s.tread_depth_mm is not None),
        "rooms_stair": witness.rooms_stair,
        "occupied_levels": witness.occupied_levels,
        "curtain_panels": witness.curtain_panels,
    }


#: THE SHARE OF THE BUILT CONTOUR OUTSIDE THE DECLARED ONE, BEYOND WHICH
#: THIS COUNTS AS A DISCREPANCY.
#:
#: 🔴 `IoU < 1.0` USED TO STAND HERE, AND IT WAS THE WRONG QUANTITY
#: (27.08.2026, found by a live run on a real building).
#:
#: The declared contour is built from walls' AXIS LINES, while Revit
#: returns a room's boundary along its INTERIOR FACES. The difference
#: equals the wall thickness and is unremovable by construction: for a
#: 4.0 x 3.5 m room with 200 mm walls, the axis rectangle gives 14.00 m²,
#: the interior 3800 x 3300 = 12.54 m² — and Revit returned EXACTLY 12.54.
#: That is, `IoU < 1.0` is true for EVERY correctly built room, and the
#: judge was dumping any of them into geometry.
#:
#: WORSE STILL: IoU does not distinguish correct from outright broken.
#: Measured on four contours of one room:
#:
#:      case                              IoU     outside declared
#:      correct, 200 mm walls           0.896        0.0000
#:      correct, 400 mm walls           0.797        0.0000
#:      leaked outward past a wall      0.805        0.1333
#:      placed with an offset           0.627        0.1842
#:
#: 0.805 for the LEAKED one against 0.797 for the CORRECT one with thick
#: walls: by IoU they are indistinguishable, and no threshold will
#: separate them. But the share that fell OUTSIDE the declared contour
#: separates them by two orders of magnitude — because a cutout the size
#: of the wall thickness always lies INSIDE the axis contour, while a
#: leak lies outside it.
#:
#: One percent is a margin for tessellation noise and rounding; a real
#: leak gives thirteen in the measurement.
_ROOM_OUTSIDE_TOL = 0.01


def _polygon_or_none(boundary: Sequence[tuple[float, float]]) -> Polygon | None:
    if not boundary or len(boundary) < 3:
        return None
    poly = Polygon(boundary)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.geom_type == "MultiPolygon":
        if poly.is_empty:
            return None
        poly = max(poly.geoms, key=lambda g: g.area)
    if poly.is_empty or poly.area <= 0.0:
        return None
    return poly


#: A TIE when choosing an opening's adjacency. This is NOT a threshold
#: and NOT "a minor difference."
#:
#: MEASURED 10.08.2026 (instrument: a raw parse of `L0.jsonl`, corpus
#: `backend/backend/data/decompile`, machine-local): the gap between the
#: SECOND and THIRD candidate by distance splits IN TWO, and the band
#: between the halves holds not a single observation.
#:
#:     `демо-v3`      66 doors of degree >=3: gap EXACTLY 0.0 for 36
#:                    (54.5%), for the remaining 30 — from 145.702 to
#:                    204.951 mm
#:     `k2_ar_rd_v7`  34 doors: gap 0.0 for ZERO, for all 34 — either
#:                    115.242 or 237.894 mm
#:
#: That is, what must be distinguished is EXACT equality, and the value
#: below guards only against binary-arithmetic noise and settles NOTHING
#: else. Raising it to "reasonable" millimeters is FORBIDDEN: that would
#: turn a noise guard into a boundary erected by reasoning — the main
#: class of defect this code exists to fix. The empty band 0.0 …
#: 115.242 mm is measured, not assigned; if a new building fills it, the
#: rule must be revisited by measurement, not by tweaking the number.
_ADJACENCY_TIE_EPS_MM: float = 1e-6


def _adjacent_pair(ranked: Sequence[tuple[float, str]],
                   witness: BuildWitness) -> tuple[str | None, str | None]:
    """The two rooms a door SEPARATES — by geometry, or not at all.

    WHAT IS FIXED HERE. The earlier code took `near[0]`, `near[1]` from a
    list sorted BY ROOM IDENTIFIER. When a point touched three or more
    rooms, the pair was chosen by alphabet — a quantity with no relation
    to either the geometry or the building. The consequence is stronger
    than a miscount: RENAMING ROOMS CHANGED THE BUILDING'S ADJACENCY
    WITHOUT CHANGING THE BUILDING, and adjacency becomes an edge in
    `checker/graph.py` and flows on into apartment derivation and the
    evacuation rules.

    WHY A REFUSAL, NOT "THE TWO NEAREST." The measurement showed that on
    `демо-v3`, in 54.5% of cases the second place is a TIE
    (`d = [0.0, 150.0, 150.0]`): one room contains the point, and two
    neighbors stand at exactly 150 mm. Taking "the two nearest" here
    means asking the alphabet again, just more quietly. So the pair is
    declared ONLY if there is a gap between the second and third
    candidates; otherwise what is known is named, and what is not stays
    unspoken.

    WHY A REFUSAL IS SAFE PRECISELY AT THE DOOR. An adjacency edge with
    the wrong pair makes the evacuation rule INCAPABLE OF FAILING — the
    same defect by which one OUTSIDE node welded floors together across
    the street and HAB010 could not fail. A door with no edge is a state
    the package already handles: `derive.py` strips the edges of phantom
    doors (`exclude_door_ids`), and `_landing_room_on_level` returns None
    on ambiguous landings and DOES NOT BUILD an edge. Here it is the same
    choice, on the same grounds.

    The order within the pair (who is `from`, who is `to`) CARRIES NO
    SEMANTICS: the real extractor sets FromRoom/ToRoom by the door's
    orientation, not by inside/outside meaning, and consumers read the
    pair as UNORDERED (`building_entrance_rooms` takes either non-empty
    side, `build_graph` builds an UNDIRECTED edge). The invariant is a
    set, not slots.
    """
    if not ranked:
        return None, None
    if len(ranked) == 1:
        return ranked[0][1], None
    if len(ranked) == 2:
        return ranked[0][1], ranked[1][1]
    if ranked[2][0] - ranked[1][0] > _ADJACENCY_TIE_EPS_MM:
        return ranked[0][1], ranked[1][1]
    if ranked[1][0] - ranked[0][0] > _ADJACENCY_TIE_EPS_MM:
        witness.note(
            "opening_second_side_undecidable",
            f"у двери первая сторона определена геометрией, а ВТОРАЯ занята "
            f"вничью ({len(ranked)} помещений в допуске, кандидаты на второе "
            f"место равноудалены): вторая сторона не объявлена, потому что "
            f"выбрать её можно было бы только по имени помещения")
        return ranked[0][1], None
    witness.note(
        "opening_sides_undecidable",
        f"у двери НИ ОДНА сторона не определяется геометрией: {len(ranked)} "
        f"помещений в допуске равноудалены. Стороны не объявлены — прежний код "
        f"брал две первые ПО АЛФАВИТУ идентификатора")
    return None, None


def _nearest_room(ranked: Sequence[tuple[float, str]],
                  witness: BuildWitness) -> str | None:
    """The room a window lights: the NEAREST one, or — on a tie — the named one.

    THE DIFFERENCE FROM THE DOOR IS DELIBERATE, AND HERE IS ITS BASIS. For
    a door, a refusal removes an edge and can only deny a rule its green
    light. For a window, a refusal removes `room_id`, and HAB030 stands on
    it ("the room has no window"): refusing means ACCUSING the building —
    exactly the class of false BLOCKING that `APARTMENT_MARKERS` and the
    `_caveats` provisos exist to guard against in checker v2. So here the
    choice is not dropped but REFINED to the geometric one and NAMED, when
    the geometry stays silent.

    MEASURED 10.08, why this is not theory: on `sob62_r23_v5`, 24 windows
    out of 31 touch TWO rooms, and ALL 24 stand at EXACTLY THE SAME
    distance from them. That is, on this building the room choice for
    every ambiguous window was being made by alphabet. The corpus's other
    buildings give no ambiguous windows at all (`демо-v3` — 0,
    `k2_ar_rd_v7` — 0, `snowdon_plumb_v5` — 0).

    Changing HAB030's semantics to "a window MAY light any of N" is a
    product decision, not a mechanical fix, and it is not made here.
    """
    if not ranked:
        return None
    if len(ranked) == 1:
        return ranked[0][1]
    if ranked[1][0] - ranked[0][0] > _ADJACENCY_TIE_EPS_MM:
        return ranked[0][1]
    witness.note(
        "window_room_undecidable",
        f"окно равноудалено от {len(ranked)} помещений: помещение выбрано ПО "
        f"ИМЕНИ, потому что геометрия их не различает. Число сказано, чтобы "
        f"HAB030 читался с этой поправкой, а не как факт о здании")
    return ranked[0][1]


def _openings(
    *,
    door_elements: Iterable[Any],
    window_elements: Iterable[Any],
    walls_by_id: Mapping[str, Wall],
    room_polys: Mapping[str, Polygon],
    rooms_by_level: Mapping[str, list[str]],
    witness: BuildWitness,
    profile: StageProfile | None,
    location_of,
    size_of,
    host_of,
    id_of,
    level_of=lambda element: None,
) -> tuple[list[Door], list[Window]]:
    """Doors and windows from both paths.

    A door's adjacency is NOT declared on its own say-so: the rooms taken
    are those whose polygons the door ACTUALLY touches. A door that
    touches no MEASURED room stays without sides — and `derive.py` will
    call this "sides unmeasurable," not "phantom door": the difference
    between "we could not verify" and "we verified and it did not check
    out" is worth a whole class of false accusations here.

    `is_exterior` is likewise not declared: `derive.py` derives
    exteriority by POSITIVE membership in the envelope's ring. Declaring
    it here would mean slipping the checker an answer to the question it
    is asking.
    """
    tol = OPENING_JOIN_TOL_MM
    level_of_wall = {wid: wall.level_id for wid, wall in walls_by_id.items()}
    trees: dict[str, tuple[list[str], STRtree]] = {}
    for level_id, room_ids in rooms_by_level.items():
        ids = [rid for rid in room_ids if rid in room_polys]
        if ids:
            trees[level_id] = (ids, STRtree([room_polys[rid] for rid in ids]))

    def touching(level_id: str, point: Point) -> list[tuple[float, str]]:
        """The rooms a point touches, RANKED BY DISTANCE.

        A distance is returned, not just one address: without it, the
        only way to choose a side is by sorting strings, and the
        lexicographic order of identifiers is not a property of the
        building. The earlier `sorted(out)` returned rooms BY ALPHABET,
        and `near[0]`/`near[1]` took the first two.
        """
        got = trees.get(level_id)
        if got is None:
            return []
        ids, tree = got
        out: list[tuple[float, str]] = []
        for index in tree.query(point.buffer(tol)):
            rid = ids[int(index)]
            poly = room_polys[rid]
            if poly.contains(point):
                out.append((0.0, rid))
                continue
            distance = poly.exterior.distance(point)
            if distance <= tol:
                out.append((distance, rid))
        return sorted(out)

    doors: list[Door] = []
    for element in door_elements:
        host = host_of(element)
        level_id = level_of(element) or (level_of_wall.get(host) if host else None)
        location = location_of(element)
        if location is None:
            witness.note("door_no_geometry",
                         "у двери в представлении нет ни точки, ни рамки — положения "
                         "не существует, дверь пропущена")
            witness.drop("doors", "положения нет в представлении")
            continue
        if level_id is None:
            witness.note("door_no_level",
                         "у двери не разрешается уровень (ни свой, ни хозяина) — "
                         "пропущена")
            witness.drop("doors", "уровень не разрешается")
            continue
        size = size_of(element)
        first, second = _adjacent_pair(
            touching(level_id, Point(location)), witness)
        doors.append(Door(
            id=id_of(element), level_id=level_id, location=location,
            width_mm=float(size[0]) if size else 0.0,
            from_room_id=first,
            to_room_id=second,
            is_exterior=False,
            host_wall_id=host,
        ))

    # 🔴 THE "MEASURED OR NOMINAL" DECISION IS MADE PER ELEMENT, SO IT MUST
    # ALSO BE RECORDED PER ELEMENT (22.08.2026). The earlier edition
    # accumulated ONE flag, `measured_any` ("at least one window has a
    # dimension"), and used it to print a claim about the WHOLE building.
    #
    # The MNVNK measurement this fixes: 2952 window elements, a dimension
    # (`FAMILY_WIDTH_PARAM` + `FAMILY_HEIGHT_PARAM`) exists for exactly
    # 588, and 2364 got a made-up nominal of 1.0 m². The witness, in the
    # process, printed `opening_size_measured: true`,
    # `nominal_opening_area_m2: null`, and issued NO
    # `opening_size_unmeasured` note AT ALL. That is, 2364 substituted
    # numbers were traveling into the model under a receipt of "everything
    # measured."
    #
    # Today this accuses nobody only because HAB030 is withdrawn by the
    # profile for a DIFFERENT reason (curtain-wall facade), and HAB031 is
    # withdrawn by the `StageProfile` validator. A lie that breaks nothing
    # only by coincidence of other withdrawals is a lie waiting for its
    # moment, not a harmless inaccuracy.
    #
    # WHAT CANNOT BE DONE HERE, AND THIS IS A BOUNDARY OF THE INPUT, NOT A
    # CHOICE. The live measurement of 22.08 showed WHAT exactly these 2364
    # are: nested counted families "Условный стеклопакет" with a
    # `super_component_id` pointing at the real window — that is, they are
    # not openings at all, and the correct answer would be "judge the
    # 588." But `super_component_id` is NOT CAPTURED in L0 (`host_id` is
    # empty for 2952 of 2952, and so is `host_source`), and telling a
    # nested family apart BY ITS TYPE NAME means guessing — exactly the
    # prohibition by which curtain-wall panels are not counted as windows
    # here. So they remain openings and are NAMED as nominal; this can be
    # closed only by capturing `super_component_id` in
    # `decompile/extract.py`.
    nominal = profile.nominal_opening_area_m2 if profile is not None else None
    windows: list[Window] = []
    measured_count = 0
    nominal_count = 0
    for element in window_elements:
        host = host_of(element)
        level_id = level_of(element) or (level_of_wall.get(host) if host else None)
        location = location_of(element)
        if location is None:
            # MEASURED 03.08 (K2): 46 windows out of 49 carry in L0
            # NEITHER a point NOR a valid frame — `geom_kind: bbox_only`
            # with a frame the geometry parser rejected. This is not an
            # assembler failure and not a defect of the building: the
            # reading never saw the window, and it must be named exactly
            # that way.
            witness.note("window_no_geometry",
                         "у окна в представлении нет ни точки, ни годной рамки — "
                         "положения не существует, окно пропущено")
            witness.drop("windows", "положения нет в представлении")
            continue
        if level_id is None:
            witness.note("window_no_level",
                         "у окна не разрешается уровень (ни свой, ни хозяина) — "
                         "пропущено")
            witness.drop("windows", "уровень не разрешается")
            continue
        size = size_of(element)
        lit_room = _nearest_room(touching(level_id, Point(location)), witness)
        if size is not None:
            measured_count += 1
            width, height = size
            area = round(width * height / _MM2_PER_M2, 2)
        else:
            # A NAMED DEFAULT, not an invention: the value answers
            # exclusively the question "is there an opening at all," and
            # `StageProfile` forbids declaring it until every rule
            # comparing glazing area against a tolerance has been
            # withdrawn.
            nominal_count += 1
            width, height, area = 0.0, None, float(nominal or 0.0)
        windows.append(Window(
            id=id_of(element), level_id=level_id, host_wall_id=host,
            room_id=lit_room,
            width_mm=width, area_m2=area, height_mm=height, location=location,
            # 🔴 THE SECOND SUBSTITUTION NAMES ITSELF WITH THE SAME WORD
            # (F-254). The witness already states this with the
            # `opening_size_unmeasured` note; the field makes the same
            # truth READABLE BY CODE, not by prose, and so it reaches the
            # area accumulator, which does not read prose.
            area_source="measured" if size is not None else "nominal",
        ))
    witness.openings_measured = measured_count
    witness.openings_nominal = nominal_count
    # "Opening dimensions are measured" is a claim about ALL openings, and
    # it is true exactly when not one of them is substituted. The earlier
    # "at least one" turned 588 measured windows into a receipt covering
    # 2952.
    witness.opening_size_measured = bool(windows) and nominal_count == 0
    if nominal_count:
        witness.nominal_opening_area_m2 = nominal
        witness.note(
            "opening_size_unmeasured",
            f"габарит проёма представление не выражает у {nominal_count} проёмов из "
            f"{len(windows)} (измерены {measured_count}); каждому из них для проверки "
            f"НАЛИЧИЯ окна принят названный номинал профиля {nominal} м², правило 1:8 "
            f"(HAB031) снято",
            nominal_count)
    return doors, windows


# ---------------------------------------------------------------------------------
# 9. THE VERDICT
# ---------------------------------------------------------------------------------

class DesignCheckUnavailable(RuntimeError):
    """Checker v2 is switched off. A refusal, not a silent fallback to v1.

    The v1 path has neither a three-valued verdict, nor coverage, nor a
    geometric pre-pass — a "verdict" from it would be a binary
    pass/fail over unverified declarations, and there would be nothing to
    tell it apart from the real one.
    """


@dataclass(frozen=True)
class DesignVerdict:
    """The verdict together with WHAT exactly was checked and where it came from."""

    source: ModelSource
    building_id: str
    report: CheckReport
    witness: BuildWitness
    profile: StageProfile | None

    @property
    def verdict(self) -> Verdict | None:
        return self.report.verdict

    @property
    def rules_applied(self) -> int:
        coverage = self.report.coverage
        return coverage.rules_evaluated if coverage else 0

    @property
    def rules_total(self) -> int:
        coverage = self.report.coverage
        return len(coverage.outcomes) if coverage else 0

    @property
    def rules_suspended(self) -> list[str]:
        if self.profile is None:
            return []
        return sorted(self.profile.suspended)


def check_design(
    model: SpatialModel,
    witness: BuildWitness,
    *,
    thresholds: Thresholds | None = None,
) -> DesignVerdict:
    """Run the rules engine and return the verdict together with the assembly witness.

    By default the profile is DERIVED from the witness
    (`design_stage_profile`): whatever inputs this representation gives
    are exactly the rules entitled to speak. An explicit `thresholds`
    overrides the derivation — used by tests that need a fixed set.
    """
    if not checker_v2_enabled():
        raise DesignCheckUnavailable(
            "KIR_CHECKER_V2=1 не выставлен (прежнее имя KUKAI_CHECKER_V2 тоже "
            "читается): путь v1 не даёт ни трёхзначного "
            "вердикта, ни покрытия, ни геометрической предпроходки — молча выдать "
            "его вместо вердикта стадии значило бы подменить утверждение")
    if thresholds is None:
        thresholds = Thresholds(profile=design_stage_profile(witness))
    report = run_checker(model, thresholds)
    return DesignVerdict(source=witness.source, building_id=witness.building_id,
                         report=report, witness=witness,
                         profile=thresholds.profile)


# ---------------------------------------------------------------------------------
# 10. THE TEXT THE MODEL READS
# ---------------------------------------------------------------------------------

_VERDICT_RU = {
    Verdict.PASS: "ПРИГОДЕН",
    Verdict.FAIL: "НЕПРИГОДЕН",
    Verdict.NOT_EVALUATED: "НЕ ОЦЕНЕНО",
}


def verdict_headline_text(verdict: Verdict | None, *, evaluated: int,
                          total: int) -> str:
    """Verdict headline. LAW: the headline has no right to be stronger than the body.

    The DEFECT this function exists for. `Verdict.PASS` used to print as the word
    FIT, period — while the verdict body right below it listed rules that were
    not evaluated AT ALL (measurement 03.08: 12 of 20 evaluated; on the program
    with a staircase — 9 of 14, and the unevaluated ones included reachability
    from the entrance, descent to grade, staircase geometry, and heights). The
    model reads the headline and leaves: the headline is the one line that is
    always read.

    The third value is NOT invented: `Verdict` stays three-valued, only the
    STRENGTH OF THE WORD in the headline changes, and it changes by the number
    taken from coverage.
    """
    word = _VERDICT_RU.get(verdict, str(verdict))
    if verdict is Verdict.PASS and total and evaluated < total:
        return f"{word} ПО {evaluated} ПРАВИЛАМ ИЗ {total}, ОСТАЛЬНОЕ НЕ ОЦЕНЕНО"
    if verdict is Verdict.NOT_EVALUATED and total:
        return f"ИТОГ НЕ ОЦЕНЕН; ОЦЕНЕНО {evaluated} ПРАВИЛ ИЗ {total}"
    return word


def verdict_headline(verdict: "DesignVerdict") -> str:
    """The same headline, taken from a finished verdict."""
    coverage = verdict.report.coverage
    return verdict_headline_text(
        verdict.report.verdict,
        evaluated=coverage.rules_evaluated if coverage else 0,
        total=len(coverage.outcomes) if coverage else 0)

#: How many characters of one finding to show. Rule HAB001 folds ALL
#: unreachable rooms into ONE message line: on tower K2 that is 24,000 characters,
#: which would push the rest of the verdict out of the model's window. The TAIL is
#: cut and the length of the cut part is named — otherwise the truncation is
#: indistinguishable from there being few findings.
_MSG_CLIP = 260
_REFS_CLIP = 12


def _clip(text: str, limit: int = _MSG_CLIP) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (+{len(text) - limit} символов)"


def _clip_refs(refs: Sequence[str]) -> str:
    shown = ", ".join(refs[:_REFS_CLIP])
    if len(refs) <= _REFS_CLIP:
        return shown
    return f"{shown} … всего {len(refs)}"


def render_verdict(verdict: DesignVerdict, *, max_examples: int = 3) -> str:
    """The verdict as human (and model) text.

    The order of the parts is set by the order in which they can be read
    HONESTLY: first the source (is this a self-check or a read), then the
    profile (which rule set judged it), then coverage (what was even looked
    at), and only then the findings. A finding read before coverage is a
    statement without a denominator.
    """
    report = verdict.report
    coverage = report.coverage
    witness = verdict.witness
    lines: list[str] = []

    lines.append(f"═══ ВЕРДИКТ О ЗАМЫСЛЕ: {verdict_headline(verdict)} ═══")
    lines.append(f"здание: {witness.building_id}"
                 + (f"  ({witness.doc_name})" if witness.doc_name else ""))
    lines.append(f"источник: {verdict.source.evidence}")

    if verdict.profile is not None:
        evaluated = coverage.rules_evaluated if coverage else 0
        total = len(coverage.outcomes) if coverage else 0
        lines.append(f"профиль: {verdict.profile.name} — "
                     f"применимо {total - len(verdict.rules_suspended)} правил "
                     f"из {total}, оценено {evaluated}")
        # Rules taken down by ONE AND THE SAME cause are printed as one line: four
        # copies of one paragraph read as four different reasons, and there is one.
        by_reason: dict[str, list[str]] = defaultdict(list)
        for rule_id in verdict.rules_suspended:
            by_reason[verdict.profile.suspension_reason(rule_id)].append(rule_id)
        for reason, rule_ids in by_reason.items():
            lines.append(f"    снято {'/'.join(sorted(rule_ids))}: {reason}")
        partial = [o for o in (coverage.outcomes if coverage else [])
                   if o.excluded_subjects]
        for outcome in partial:
            lines.append(
                f"    не оценено {outcome.rule_id} на {outcome.excluded_subjects} "
                f"субъектах: {outcome.excluded_reason} "
                f"(высказалось о {outcome.n_subjects})")
        if witness.nominal_opening_area_m2 is not None:
            lines.append(f"    названное умолчание: габарит проёма не выражен у "
                         f"{witness.openings_nominal} проёмов из "
                         f"{witness.openings_nominal + witness.openings_measured} "
                         f"(измерены {witness.openings_measured}), им принят номинал "
                         f"{witness.nominal_opening_area_m2} м² ТОЛЬКО для проверки "
                         f"наличия окна")

    lines.append("")
    lines.append(f"что прочитано: " + ", ".join(
        f"{name} {count}" for name, count in sorted(witness.counts.items())))
    lines.append(
        f"полигон помещения получили {witness.rooms_measured} из "
        f"{witness.rooms_total} ({witness.measured_ratio:.0%}); "
        f"неизмеримых {len(witness.unmeasured_room_ids)}")
    for reason, count in witness.unmeasured_reasons.most_common():
        lines.append(f"    {count:>6}  {_UNMEASURED_RU.get(reason, reason)}")
    if witness.rooms_total:
        lines.append(f"высота известна у {witness.rooms_with_height} помещений — "
                     f"{witness.height_source}")

    if coverage is not None:
        lines.append("")
        lines.append(f"покрытие: классификация {coverage.classification_coverage:.0%}, "
                     f"измеримость {coverage.measured_room_ratio:.0%}")
        if coverage.mandatory_not_evaluated:
            lines.append("    ОБЯЗАТЕЛЬНЫЕ НЕ ОЦЕНЕНЫ: "
                         + ", ".join(coverage.mandatory_not_evaluated))
        for note in coverage.notes:
            # Coverage notes list the IDENTIFIERS of every room touched — on the
            # tower that is thousands; the note itself matters, the list does not.
            lines.append(f"    {_clip(note, 300)}")
        vacuous = [o for o in coverage.outcomes if o.status.value == "not_evaluated"]
        if vacuous:
            lines.append(f"    не оценено правил: {len(vacuous)}")
            # Reasons already named in the profile block are not repeated here in
            # full: a report where one paragraph stands six times gets skimmed.
            named_above = set(verdict.rules_suspended)
            for outcome in vacuous:
                if outcome.rule_id in named_above:
                    lines.append(f"      {outcome.rule_id}: снято профилем (см. выше)")
                else:
                    lines.append(f"      {outcome.rule_id}: {_clip(outcome.reason, 400)}")

    lines.append("")
    for label, bucket in (("БЛОКИРУЮЩИЕ", report.blocking),
                          ("ПРЕДУПРЕЖДЕНИЯ", report.warnings),
                          ("СПРАВОЧНО", report.info)):
        if not bucket:
            continue
        lines.append(f"{label}: {len(bucket)}")
        grouped: dict[str, list] = defaultdict(list)
        for violation in bucket:
            grouped[violation.rule_id].append(violation)
        for rule_id in sorted(grouped):
            found = grouped[rule_id]
            lines.append(f"  {rule_id} — {len(found)}")
            for violation in found[:max_examples]:
                lines.append(f"      {_clip(violation.msg)}")
                if violation.refs:
                    lines.append(f"        адреса: {_clip_refs(violation.refs)}")
            if len(found) > max_examples:
                lines.append(f"      … и ещё {len(found) - max_examples}")

    if witness.notes:
        lines.append("")
        lines.append("что не прочиталось:")
        for note in witness.notes:
            lines.append(f"  {note.count:>6}  {note.detail}")

    caveats = _caveats(witness)
    if caveats:
        lines.append("")
        lines.append("КАК ЧИТАТЬ ЭТИ НАХОДКИ:")
        for caveat in caveats:
            lines.append(f"  · {caveat}")

    lines.append("")
    lines.append("ВНЕ ОБЛАСТИ (не моделируется, поимённо):")
    for item in OUT_OF_SCOPE:
        lines.append(f"  · {item.name}: {item.behaviour} [{item.measured}]")
    return "\n".join(lines)


#: Ceiling of the short verdict. The sandbox channel is `MAX_STDOUT_CHARS` (4000),
#: and it is the ONLY one through which anything reaches the model at all. The
#: full verdict weighs 5-8 KB: printed into the script, it would push out both
#: the model's own printing and its own tail. The number is a deduction, not a
#: round figure: half the channel to the verdict, half to the plan and the
#: author's printing.
BRIEF_VERDICT_CAP = 1800


def render_verdict_brief(verdict: DesignVerdict, *,
                         limit: int = BRIEF_VERDICT_CAP) -> str:
    """Verdict for the NARROW channel (sandbox) — shorter, but not weaker.

    What is dropped compared to `render_verdict`: examples beyond the first,
    element addresses, the "out of scope" list, and the caveat text. What is
    NOT dropped under any circumstances: the headline (the very same, character
    for character), the source (self-check), the count of what was read, ALL
    blocking rules by name, and the list of rules that were not evaluated.
    Brevity that drops any one of these turns the verdict into a paraphrase of
    itself.
    """
    report = verdict.report
    coverage = report.coverage
    witness = verdict.witness
    lines: list[str] = [f"═══ ВЕРДИКТ О ЗАМЫСЛЕ: {verdict_headline(verdict)} ═══"]

    lines.append("источник: САМОПРОВЕРКА — судится ЗАЯВЛЕННОЕ программой, "
                 "а не построенное"
                 if verdict.source is ModelSource.PROGRAM else
                 "источник: независимое чтение разбора (L0)")
    if witness.counts:
        lines.append("прочитано: " + ", ".join(
            f"{name} {count}" for name, count in sorted(witness.counts.items())))
    if witness.rooms_total:
        lines.append(
            f"полигон помещения получили {witness.rooms_measured} из "
            f"{witness.rooms_total} ({witness.measured_ratio:.0%}), "
            f"высота известна у {witness.rooms_with_height}")
        for reason, count in witness.unmeasured_reasons.most_common(2):
            lines.append(f"    {count} — {_UNMEASURED_RU.get(reason, reason)}")

    for label, bucket in (("БЛОКИРУЮЩИЕ", report.blocking),
                          ("ПРЕДУПРЕЖДЕНИЯ", report.warnings)):
        if not bucket:
            continue
        grouped: dict[str, list] = defaultdict(list)
        for violation in bucket:
            grouped[violation.rule_id].append(violation)
        lines.append(f"{label} {len(bucket)}: " + ", ".join(
            f"{rule_id}×{len(found)}" for rule_id, found in sorted(grouped.items())))
        # The FIRST example of EACH rule, not the first examples of the first
        # rule: a rule that isn't mentioned at all reads as absent.
        for rule_id, found in sorted(grouped.items()):
            lines.append(f"  {rule_id}: {_clip(found[0].msg, 150)}")

    if coverage is not None:
        vacuous = [o for o in coverage.outcomes
                   if o.status.value == "not_evaluated"]
        if vacuous:
            lines.append(f"НЕ ОЦЕНЕНО правил {len(vacuous)} из "
                         f"{len(coverage.outcomes)}: "
                         + ", ".join(o.rule_id for o in vacuous))
            named = set(verdict.rules_suspended)
            for outcome in vacuous:
                if outcome.rule_id in named:
                    continue
                lines.append(f"  {outcome.rule_id}: {_clip(outcome.reason, 120)}")
            if named:
                lines.append(f"  снято профилем стадии: "
                             f"{', '.join(sorted(named))} (причины — "
                             f"в полном вердикте)")
        if coverage.mandatory_not_evaluated:
            lines.append("  ОБЯЗАТЕЛЬНЫЕ НЕ ОЦЕНЕНЫ: "
                         + ", ".join(coverage.mandatory_not_evaluated))

    text = "\n".join(lines)
    if len(text) > limit:
        # The truncation NAMES ITSELF: a silently shortened verdict is
        # indistinguishable from a verdict with fewer findings.
        cut = text[:limit].rsplit("\n", 1)[0]
        text = (f"{cut}\n… вердикт обрезан на {limit} символах "
                f"(+{len(text) - len(cut)}); полностью — `render_verdict()`")
    return text


# ---------------------------------------------------------------------------------
# 10a. THE THREE CORRECTNESS AXES — SHAPE OF THE RELEASE CRITERION
# ---------------------------------------------------------------------------------
#
# OWNER'S DECISION 17.08.2026: before shipping to prod, measure ourselves by the
# BIM-Edit axes — **geometric / semantic / topological correctness, SEPARATELY**,
# not by a census of minimums. The reason is named by him too: a predicate of the
# form `walls>=8, floors>=2` is satisfied by a STACK OF BOXES — it measures the
# appearance of ELEMENTS, not the quality of the DESIGN. The axes were already
# being measured in the tree; exactly what was missing is what follows — not
# merging them into one `Verdict`.
#
# 🔴 THE MAIN DEVICE OF THIS REPORT, AND ALSO THE SOLE REASON IT IS USEFUL:
# an axis has THREE numbers, not one. «Нарушений 0» and «правил не судило ни
# одно» look the same on today's real building, and mean the opposite. Zero
# violations on an axis nobody judged is zero of a quantity the instrument is
# not counting here, and passing it off as success would be committing exactly
# the mistake this whole package is written against.
#
# The share is computed ONLY over JUDGING rules: a rule that did not judge
# enters neither the numerator nor the denominator. The shape is taken from
# `tools/live_op_rates.py`, where the same decision has already been made and
# justified, not reinvented here.


#: THE AXIS OF EACH RULE. The list is CLOSED and must cover BOTH registries —
#: the geometric one (`engine.RULE_SPECS_V2`, 16) and the consistency one
#: (`rules.consistency.CONSISTENCY_REGISTRY`, 4). A rule not named here would
#: fall into NO axis and vanish from the report silently; the lint below
#: forbids this.
#:
#: The dividing question is the same one for every line: **which witness the
#: rule stands on.** A measure in millimeters is geometric; connectivity and
#: reachability are topological; the meaning of the label (room function,
#: whether the declared matches) is semantic. That is why HAB020 (area BY
#: FUNCTION) is semantic, while HAB021/HAB022 (width, height) are geometric,
#: even though all three measure a room.
_RULE_AXIS: dict[str, str] = {
    # --- geometric: a measure in millimeters, needs nobody's classification
    "HAB011": "geometric",   # flight geometry: width/rise/tread
    "HAB012": "geometric",   # continuity of the stair core in plan
    "HAB021": "geometric",   # minimum room width
    "HAB022": "geometric",   # minimum ceiling height
    "HAB040": "geometric",   # overlap of room outlines on a floor
    "HAB063": "geometric",   # dead void in the slab: rooms cover the slab
    # --- topological: connectivity, reachability, membership
    "HAB001": "topological",  # room reachability from the entrance
    "HAB002": "topological",  # apartment-into-apartment, exactly one entrance
    "HAB003": "topological",  # path to the staircase and down to grade
    "HAB004": "topological",  # reachability inside the apartment from the entry hall
    "HAB010": "topological",  # the staircase connects ALL occupied levels
    "HAB041": "topological",  # the door has a host wall and opens
    "HAB042": "topological",  # the apartment envelope is substantially closed
    "HAB050": "topological",  # vertical continuity: load reaches grade
    "HAB061": "topological",  # door adjacency is GEOMETRICALLY real (not a graph phantom)
    # --- semantic: the meaning of the label — room function, whether the declared matches
    "HAB020": "semantic",    # minimum area BY FUNCTION
    "HAB030": "semantic",    # a living room and kitchen must have an exterior window
    "HAB031": "semantic",    # daylight share for LIVING rooms
    "HAB060": "semantic",    # the declared scalar matches the geometry
    "HAB062": "semantic",    # unclassified room of livable size
}

#: The order of axes in the report is DECLARED, not by group size: the reader
#: hunts for a line with their eyes and expects it in the same place run to
#: run.
AXES: tuple[str, ...] = ("geometric", "semantic", "topological")

_AXIS_RU = {"geometric": "ГЕОМЕТРИЯ", "semantic": "СМЫСЛ",
            "topological": "ТОПОЛОГИЯ"}


def _lint_axis_map() -> None:
    """Every rule of BOTH registries is named by exactly one axis — otherwise it
    disappears.

    Checked on import, not by a test: an unclosed map makes the report
    silently incomplete, and this cannot be noticed from the report itself —
    it will simply be missing a line. The same technique as `spec._lint_registry`.
    """
    try:
        from kir.checker.engine import RULE_SPECS_V2
        from kir.checker.rules import consistency
    except Exception:  # noqa: BLE001 — the checker is not installed: the map cannot be verified,
        return         # but the report cannot be built either; silence here is honest
    known = {spec.rule_id for spec in RULE_SPECS_V2}
    known |= {rule_id for rule_id, _ in consistency.CONSISTENCY_REGISTRY}
    missing = sorted(known - set(_RULE_AXIS))
    if missing:
        raise AssertionError(
            f"правила без оси: {missing}. Правило, не названное в `_RULE_AXIS`, "
            f"не попадёт НИ В ОДНУ ось и исчезнет из отчёта МОЛЧА — а отчёт по "
            f"осям и есть объявленный критерий выпуска")
    unknown = sorted(set(_RULE_AXIS) - known)
    if unknown:
        raise AssertionError(
            f"ось названа для правил, которых нет ни в одном реестре: {unknown}. "
            f"Карта разъехалась с реестром — значит она второй экземпляр, а не "
            f"реестр под другим углом")
    bad = sorted(r for r, axis in _RULE_AXIS.items() if axis not in AXES)
    if bad:
        raise AssertionError(f"неизвестная ось у правил: {bad}")


_lint_axis_map()


@dataclass(frozen=True)
class AxisOutcome:
    """One axis: THREE numbers and the causes of silence, named."""

    axis: str
    judged: tuple[str, ...]          # rules that SPOKE
    violated: tuple[str, ...]        # of those — the ones that found a violation
    silent: tuple[tuple[str, str], ...]   # (rule, CAUSE of silence)
    subjects: int                    # how many objects were examined by the judging rules
    withheld: int                    # how many objects were held back for lack of input
    findings: int                    # number of findings on the axis

    @property
    def total(self) -> int:
        return len(self.judged) + len(self.silent)

    @property
    def clean_share(self) -> float | None:
        """Share clean AMONG THE JUDGED. `None` when nobody judged.

        `None`, not `1.0` and not `0.0`: a share over an empty denominator is
        neither «всё чисто» nor «всё плохо», it is the ABSENCE OF AN ANSWER,
        and it must look different from an answer.
        """
        if not self.judged:
            return None
        return (len(self.judged) - len(self.violated)) / len(self.judged)


def axis_report(verdict: DesignVerdict) -> tuple[AxisOutcome, ...]:
    """The verdict broken down over the three axes of the release criterion.

    Reads ONLY what the engine has already computed (`coverage.outcomes` and
    the finding lists). There is not, and must not be, a single judgment of
    its own about the building here: a rule that stays silent must stay silent
    in the report too — un-silencing it in the report would substitute a
    different subject for the measurement.
    """
    coverage = verdict.report.coverage
    outcomes = list(coverage.outcomes) if coverage else []
    findings = list(verdict.report.blocking) + list(verdict.report.warnings) \
        + list(verdict.report.info)
    hits: dict[str, int] = {}
    for finding in findings:
        rule_id = getattr(finding, "rule_id", "")
        if rule_id:
            hits[rule_id] = hits.get(rule_id, 0) + 1

    out: list[AxisOutcome] = []
    for axis in AXES:
        mine = [o for o in outcomes if _RULE_AXIS.get(o.rule_id) == axis]
        judged = tuple(o.rule_id for o in mine
                       if o.status.value == "evaluated")
        silent = tuple((o.rule_id, o.reason or "причина не названа")
                       for o in mine if o.status.value != "evaluated")
        violated = tuple(r for r in judged if hits.get(r))
        out.append(AxisOutcome(
            axis=axis, judged=judged, violated=violated, silent=silent,
            subjects=sum(o.n_subjects for o in mine
                         if o.status.value == "evaluated"),
            withheld=sum(o.excluded_subjects for o in mine),
            findings=sum(hits.get(r, 0) for r in judged),
        ))
    return tuple(out)


def render_axis_report(verdict: DesignVerdict, *, max_silent: int = 8) -> str:
    """The three-axis report as text. Silence is printed LOUDER than findings."""
    rows = axis_report(verdict)
    lines = [
        f"ТРИ ОСИ КОРРЕКТНОСТИ — {verdict.building_id or '(без имени)'} "
        f"({verdict.source.value})",
        "",
        f"{'ось':12} {'судило':>8} {'нашли':>7} {'МОЛЧАТ':>8} "
        f"{'предметов':>10} {'удержано':>9}  чисто среди судивших",
        "-" * 86,
    ]
    for row in rows:
        share = ("—  (не судил НИКТО)" if row.clean_share is None
                 else f"{row.clean_share:.0%} ({len(row.judged) - len(row.violated)}"
                      f" из {len(row.judged)})")
        lines.append(
            f"{_AXIS_RU[row.axis]:12} {len(row.judged):>8} {len(row.violated):>7} "
            f"{len(row.silent):>8} {row.subjects:>10} {row.withheld:>9}  {share}")
    judged_all = sum(len(r.judged) for r in rows)
    total_all = sum(r.total for r in rows)
    lines += [
        "-" * 86,
        f"{'ВСЕГО':12} {judged_all:>8} "
        f"{sum(len(r.violated) for r in rows):>7} "
        f"{sum(len(r.silent) for r in rows):>8}",
        "",
        f"🔴 ПРАВИЛ ВЫСКАЗАЛОСЬ {judged_all} ИЗ {total_all}. "
        f"Остальные МОЛЧАТ, и это не «чисто»:",
    ]
    for row in rows:
        if not row.silent:
            continue
        lines.append(f"  {_AXIS_RU[row.axis]}:")
        for rule_id, reason in row.silent[:max_silent]:
            lines.append(f"    {rule_id}  {_clip(reason, 96)}")
        if len(row.silent) > max_silent:
            lines.append(f"    … и ещё {len(row.silent) - max_silent}")
    lines += [
        "",
        "ЧТО ЭТОТ ОТЧЁТ НЕ ГОВОРИТ: доля считается ТОЛЬКО по осуждённым правилам.",
        "Ось, где не судил никто, не имеет доли ВООБЩЕ — там прочерк, а не 100%.",
    ]
    return "\n".join(lines)


def _caveats(witness: BuildWitness) -> list[str]:
    """Caveats that MUST stand next to the findings, not at the end of the
    document.

    Each describes a CASCADE: one unmeasured property turns into a stream of
    findings across several rules at once, and without this line the stream
    reads as a verdict on the building.
    """
    out: list[str] = []
    if witness.rooms_total and witness.rooms_measured < witness.rooms_total:
        missing = witness.rooms_total - witness.rooms_measured
        if witness.source is ModelSource.PROGRAM:
            out.append(
                f"{missing} помещений программа НЕ ЗАМЫКАЕТ стенами. У незамкнутого "
                f"помещения нет площади (её считает контур), поэтому HAB020 говорит "
                f"«площадь 0», HAB030 — «нет окна», HAB041/HAB061 — «дверь ни к чему "
                f"не примыкает». Это верные утверждения О ПРОГРАММЕ (Revit такое "
                f"помещение тоже вернёт незамкнутым), но НЕ приговор зданию: у "
                f"здания эти границы держат разделители помещений и колонны, "
                f"которых в языке KIR нет вовсе")
        else:
            out.append(
                f"{missing} помещений вернулись из чтения с ВЫРОЖДЕННЫМ контуром — "
                f"в Revit это неразмещённые помещения (площадь 0). Тот же каскад: "
                f"HAB020 «площадь 0», HAB030 «нет окна», HAB060 «границу не "
                f"проверить». Находка настоящая, но она о состоянии модели, а не о "
                f"замысле")
    if witness.source is ModelSource.PROGRAM and witness.rooms_with_height:
        out.append(
            "высота помещения на этом пути — высота ЗАМКНУВШИХ ЕГО СТЕН, от отметки "
            "основания до верха. Чистая высота до потолка МЕНЬШЕ на толщины пола и "
            "потолка, которых программа не выражает: замер K2 — 3100 мм по стенам "
            "против 3000 мм по прочтённому помещению. Ошибка в НЕБЕЗОПАСНУЮ сторону, "
            "и HAB022 на этом пути мягче, чем на разборе")
    if witness.nominal_opening_area_m2 is not None:
        out.append(
            f"площадь остекления НЕ ИЗМЕРЕНА у {witness.openings_nominal} проёмов из "
            f"{witness.openings_nominal + witness.openings_measured} — им подставлен "
            f"номинал {witness.nominal_opening_area_m2} м². HAB030 отвечает по ним "
            f"только на вопрос «проём есть», а норма 1:8 (HAB031) снята профилем — "
            f"окно размером с форточку здесь пройдёт. Измеренных проёмов "
            f"{witness.openings_measured}, и на них 1:8 работал бы, если бы правило "
            f"умело судить часть проёмов и молчать об остальных: сегодня не умеет — "
            f"`StageProfile.subject_inputs` фильтрует ПОМЕЩЕНИЯ, а не проёмы")
    windows = witness.counts.get("windows", 0)
    if witness.curtain_panels > windows:
        out.append(
            f"ФАСАД ВИТРАЖНЫЙ: заполнений витража {witness.curtain_panels}, окон "
            f"как отдельных элементов {windows}. У `SpatialModel` понятия «витражное "
            f"остекление» НЕТ, а у панели нет признака «стекло» — есть только имя "
            f"типа, и решать по имени значит гадать. Поэтому HAB030 на таком здании "
            f"даёт ЛОЖНОЕ «нет окна» у комнат за витражом. Это не находка о здании, "
            f"это предел модели, и он один и тот же на обоих путях")
    return out


_UNMEASURED_RU = {
    "not_enclosed_by_walls": "точка помещения не попала ни в одну грань разбиения "
                             "(стены его не замыкают)",
    "shared_face": "на одну грань разбиения претендовало несколько помещений — "
                   "грань не отдана никому",
    "ring_degenerate": "контур помещения вырожден (<3 точек или нулевая площадь)",
    # 🔴 SPLIT OF `ring_degenerate` INTO TWO CAUSES (22.08.2026, MNVNK 608/21).
    # The old name is LEFT AS IS: it is written by the PROGRAM path and by old
    # artifacts, and renaming it would mean pretending those runs never
    # happened.
    "room_not_placed": "помещение НЕ РАЗМЕЩЕНО: у него нет точки положения "
                       "(`Room.Location`) — его нет в плане вовсе, и стены тут "
                       "ни при чём",
    "room_placed_but_not_enclosed": "помещение РАЗМЕЩЕНО (точка положения есть), "
                                    "а контура Revit не вернул: границы не "
                                    "замкнулись. 🔴 «не замкнуто» и «замкнуто В "
                                    "ДРУГОЙ ФАЗЕ» здесь НЕРАЗЛИЧИМЫ: замкнутость "
                                    "— факт пофазный, а фазы помещения в L0 нет",
}


# ---------------------------------------------------------------------------------
# 11. THE GATE: two paths, one building
# ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Divergence:
    """One discrepancy between the verdicts of the two paths — with a NAMED
    cause."""

    kind: str
    subject: str
    parse: str
    program: str
    cause: str


#: The one line this module is allowed to say when the cause was NOT captured
#: by the measurement. It must be more conspicuous than any plausible-sounding
#: phrasing: a line whose cause is not established is a finding, not cosmetics.
UNATTRIBUTED = "ПРИЧИНА НЕ УСТАНОВЛЕНА — расхождение не сводится ни к одному входу"


def _input_delta(parse: BuildWitness, program: BuildWitness,
                 keys: Iterable[str]) -> str:
    """Which of the inputs READ BY THE RULE differ, with the numbers of both
    paths."""
    parts: list[str] = []
    for key in keys:
        a = parse.inputs.get(key)
        b = program.inputs.get(key)
        if a is None or b is None or a == b:
            continue
        parts.append(f"{_INPUT_RU.get(key, key)}: А={a} Б={b}")
    return "; ".join(parts)


def _population_cause(parse: BuildWitness, program: BuildWitness,
                      population: str) -> str:
    """Why the population of one kind diverged: lifting and assembly are NAMED
    separately.

    Two different fix addresses: `no_lifter` sends you to write the operation,
    while «сборщику не хватило хозяина» sends you to fix the assembly. Merging
    them into one phrase would give us a number with no address, which has
    already cost the project one wrong diagnosis (AtomReason §1).
    """
    parts: list[str] = []
    category = _POPULATION_CATEGORY.get(population, "")
    reasons = program.lift_atoms.get(category) if category else None
    if reasons:
        detail = ", ".join(f"{code} x{count}"
                           for code, count in reasons.most_common(4))
        parts.append(f"подъём ({category}): {detail}")
    for label, witness in (("А", parse), ("Б", program)):
        dropped = witness.dropped.get(population)
        if dropped:
            detail = ", ".join(f"{why} x{count}"
                               for why, count in dropped.most_common(4))
            parts.append(f"сборка {label}: {detail}")
    return "; ".join(parts)


def compare(parse: DesignVerdict, program: DesignVerdict) -> list[Divergence]:
    """Reconcile two verdicts about ONE building and name the discrepancies
    BY NAME.

    The cause of each line is DERIVED from the assembly witnesses — from
    numbers taken off the finished models and from typed lifter causes — not
    taken from a pre-written dictionary. A dictionary would explain both a
    real difference in representations and a fresh bug in this very file the
    same way; a derived cause stays silent on the second, and that silence is
    visible (`UNATTRIBUTED`).
    """
    out: list[Divergence] = []
    wa, wb = parse.witness, program.witness

    def add(kind: str, subject: str, a: Any, b: Any, cause: str) -> None:
        if str(a) == str(b):
            return
        out.append(Divergence(kind, subject, str(a), str(b), cause or UNATTRIBUTED))

    # --- verdict: the cause is what split coverage/findings ---------------------
    verdict_cause = _input_delta(wa, wb, _INPUT_RU)
    add("вердикт", "verdict",
        _VERDICT_RU.get(parse.verdict, parse.verdict),
        _VERDICT_RU.get(program.verdict, program.verdict),
        verdict_cause)

    # --- profile: two representations may deserve DIFFERENT rule sets -----------
    # If the sets diverge, what gets compared next are verdicts reached under
    # different rules, and staying silent about it is not allowed: this is not
    # a detail, it is a condition of comparability.
    a_susp = sorted(parse.profile.suspended) if parse.profile else []
    b_susp = sorted(program.profile.suspended) if program.profile else []
    add("профиль", "снятые правила", ", ".join(a_susp) or "—",
        ", ".join(b_susp) or "—",
        "снятие выводится ИЗ ЗАМЕРА представления; разные наборы означают, что "
        "представления дают разные входы — сравнивать их вердикты можно только по "
        "общей части")

    # --- population: how many elements made it to the model ---------------------
    for name in sorted(set(wa.counts) | set(wb.counts)):
        add("популяция", name, wa.counts.get(name, 0), wb.counts.get(name, 0),
            _population_cause(wa, wb, name))

    # --- rule inputs: what everything else is explained by ----------------------
    for key in sorted(set(wa.inputs) | set(wb.inputs)):
        a, b = wa.inputs.get(key, 0), wb.inputs.get(key, 0)
        if key in _POPULATION_CATEGORY and a != b:
            continue        # already named above as population
        cause = ""
        if key == "rooms_measured":
            cause = (f"разбор несёт готовый контур Revit; программа замыкает "
                     f"помещение ТОЛЬКО стенами "
                     f"({', '.join(f'{r} x{c}' for r, c in wb.unmeasured_reasons.most_common())})")
        elif key == "rooms_with_height":
            cause = f"А: {wa.height_source}; Б: {wb.height_source}"
        elif key in ("windows_with_size", "doors_with_width"):
            cause = ("габарит проёма живёт в семействе: программа называет только "
                     "`symbol`, разбор несёт FAMILY_WIDTH/HEIGHT_PARAM инстанса")
        elif key in ("windows_joined", "doors_with_adjacency"):
            cause = ("привязка проёма к помещению требует полигона помещения — "
                     f"полигонов А={wa.inputs.get('rooms_measured')} "
                     f"Б={wb.inputs.get('rooms_measured')}")
        elif key == "curtain_panels":
            cause = _population_cause(wa, wb, "curtain_panels") or (
                "разбор считает элементы `OST_CurtainWallPanels`, программа — операции "
                "`set_curtain_panel`; разница = панели, не ставшие операцией")
        elif key == "rooms_stair":
            cause = ("наследует разницу населения «rooms» и один и тот же лексикон "
                     "`classify.py` — расхождение здесь означало бы разные имена, а "
                     "имена у обоих путей одни")
        elif key == "stairs_with_footprint":
            cause = ("план марша: у разбора он из bbox лестницы, у программы — "
                     "только из `create_stairs.width_mm`, который часто не задан")
        if not cause:
            # The last honest move before `UNATTRIBUTED`: the input could simply
            # have inherited the difference from its own population. If that
            # matches too — the cause is NOT established, and that is a fact,
            # not an invitation to invent a phrasing.
            governing = _INPUT_GOVERNED_BY.get(key)
            if governing and wa.counts.get(governing) != wb.counts.get(governing):
                cause = (f"наследует разницу населения «{governing}»: "
                         f"А={wa.counts.get(governing)} Б={wb.counts.get(governing)}"
                         + (f" ({reason})"
                            if (reason := _population_cause(wa, wb, governing)) else ""))
        add("вход правил", key, a, b, cause)

    # --- rules: cause = difference in THOSE INPUTS that the rule reads ----------
    parse_rows = {o.rule_id: o for o in (parse.report.coverage.outcomes
                                         if parse.report.coverage else [])}
    prog_rows = {o.rule_id: o for o in (program.report.coverage.outcomes
                                        if program.report.coverage else [])}
    for rule_id in sorted(set(parse_rows) | set(prog_rows)):
        a, b = parse_rows.get(rule_id), prog_rows.get(rule_id)
        a_txt = f"{a.status.value}({a.n_subjects})" if a else "—"
        b_txt = f"{b.status.value}({b.n_subjects})" if b else "—"
        add("правило", rule_id, a_txt, b_txt,
            _input_delta(wa, wb, _RULE_INPUTS.get(rule_id, ())))

    # --- findings: the same attribution by the rule's inputs ---------------------
    def counts(report: CheckReport) -> Counter:
        got: Counter = Counter()
        for bucket in (report.blocking, report.warnings, report.info):
            for violation in bucket:
                got[f"{violation.rule_id}/{violation.severity.value}"] += 1
        return got

    a_counts, b_counts = counts(parse.report), counts(program.report)
    for key in sorted(set(a_counts) | set(b_counts)):
        rule_id = key.split("/")[0]
        add("находки", key, a_counts.get(key, 0), b_counts.get(key, 0),
            _input_delta(wa, wb, _RULE_INPUTS.get(rule_id, ())))
    return out


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0


def _translated(model_ids: Iterable[str],
                translate: Mapping[str, str] | None) -> dict[str, str]:
    """Program model keys translated into `element_id` space.

    An empty translation leaves the keys as is — this is the REASSEMBLY path,
    where both sides already carry `element_id`.
    """

    if not translate:
        return {mid: mid for mid in model_ids}
    return {mid: translate.get(mid, mid) for mid in model_ids}


#: THE KIND OF LINE THAT REPORTS AGREEMENT, NOT DISCREPANCY.
#:
#: 🔴 CAUGHT LIVE 25.08.2026, Проект1, 80 walls with doors. The judge of the
#: built model printed «геометрия расходится в 1», while the record itself
#: said «совпало 80, макс 0.00 мм» and carried the reason «ноль означает, что
#: восстановление точное». That is, a REPORT OF AGREEMENT was sitting in the
#: discrepancy list, and the `len(...)` counter counted it as a discrepancy.
#: On every program with an opening, the model read «геометрия расходится»
#: exactly where the geometry matched PERFECTLY — and would have gone off to
#: fix coordinates that were already correct.
#:
#: The named tree defect in its purest form: the quantity «сколько разошлось»
#: is DECLARED by a length counter and READ from a list that also contains
#: agreements.
#:
#: 🔴 AND THIS IS NOT A SYSTEMIC ISSUE, IT IS A MISS IN ONE FUNCTION — which is
#: what makes it expensive. Of the five checks here, THREE stay silent on a
#: match («ось стены», «ПОПЕРЁК оси хозяина», «пространства не сведены»), and
#: exactly TWO always spoke: «ВДОЛЬ оси хозяина» and «контур помещения (IoU)».
#: The correct form stood twenty lines from the wrong one, in the same loop.
#:
#: Since 04.09.2026 there are SIX checks: «помещения не сведены» (HR-09) was
#: added, and it is silent — like its wall twin, it speaks only of an EMPTY
#: intersection of addresses, not of matching outlines.
#:
#: WHY NOT SIMPLY GO SILENT, LIKE ITS NEIGHBORS. Silence merges «сошлось»
#: with «не смотрели», and the canon requires telling them apart. So
#: agreement is not discarded, it CHANGES KIND: the discrepancy counter does
#: not pick it up, the reader sees that the check happened and passed, while
#: the absence of a line still means «не смотрели».
СВЕРКА = "сверка"


def compare_geometry(parse: SpatialModel, program: SpatialModel,
                     *, tol_mm: float = 1.0,
                     translate: Mapping[str, str] | None = None,
                     ) -> list[Divergence]:
    """ELEMENT-BY-ELEMENT comparison of the geometry of two paths — not
    counters, but numbers.

    The comparison goes by identifiers, and therefore makes sense exactly
    when both sides address IN THE SAME SPACE.

    * **reassembly** — both sides carry the `element_id` of the same
      decompile, `translate` is not needed;
    * **AUTHORED program** — the program side carries the `id` of the
      OPERATION (`_program_nodes`: «`source_element_id` is the `id` of the
      operation itself»), while the decompile side carries the Revit
      `element_id`. The intersection of such sets is EMPTY by construction.
      Pass `translate` — a map `op_id → element_id` assembled from
      `kir.address.receipt_map(ops, payload)`, the sole producer of this map
      in the tree.

      🔴 THE UNPACKING MUST BE EXPLICIT, AND THIS IS NOT PEDANTRY.
      `receipt_map` returns a LIST for any arity, and `translate` here is
      flat, because what is being compared is walls, openings, and rooms —
      all of arity ONE. Assemble it like this:

          translate = {oid: only for oid, (only,) in receipt_map(...).items()}

      The `(only,)` unpacking REFUSES if there turn out to be two elements,
      and that is exactly the behavior needed here. Before 15.08.2026 the
      same map was built by the function `address.op_to_element_ids`, which,
      instead of refusing, SILENTLY dropped operations of multiple arity —
      measured against the registry: five writing ops out of 66
      (`create_pipe_system`, `create_room_separator`, `move_elements`,
      `route_duct_system`, `route_pipe_system`). It has been removed; the
      decision about arity is made HERE, where the question is asked.

    🔴 WHAT WAS HERE BEFORE 15.08.2026 AND WHY IT WAS WORSE THAN NOT HAVING
    THE FUNCTION AT ALL. The docstring honestly said that for a non-reassembly
    there is no correspondence. But the code in that case did not refuse:
    every branch sits under `if common:` / `if not shared: continue`, so on
    an authored program the function returned an **empty list of
    discrepancies**, and an empty list of discrepancies reads as «всё
    совпало». A zero of a quantity that nobody was counting here was passed
    off as agreement. Now an empty intersection is a NAMED finding, and it
    stands as the first line.

    Opening offset is broken down ALONG and ACROSS the axis of the host wall
    separately — and this is not decoration: the language expresses exactly
    one of the two degrees of freedom (`offset_mm` along the host), it has no
    across. One combined «разошлось на 438 мм» would blend the error with the
    boundary of expressiveness; broken down, it shows that along the axis the
    error is EXACTLY ZERO, while across it could not help but be nonzero.
    """
    out: list[Divergence] = []

    walls_a = {wall.id: wall for wall in parse.walls}
    keys_b = _translated((wall.id for wall in program.walls), translate)
    walls_b = {keys_b[wall.id]: wall for wall in program.walls}

    # REFUSAL INSTEAD OF SILENCE. Both sides are non-empty, there is not one
    # in common — meaning addresses from different spaces were being compared,
    # and any further conclusion would be about the empty set. This is the one
    # place where the function must speak up BEFORE it computes even a single
    # number.
    if walls_a and walls_b and not (set(walls_a) & set(walls_b)):
        out.append(Divergence(
            "адрес", "пространства не сведены",
            f"{len(walls_a)} стен, пример `{sorted(walls_a)[0]}`",
            f"{len(walls_b)} стен, пример `{sorted(walls_b)[0]}`",
            "пересечение идентификаторов ПУСТО: стороны адресуют в разных "
            "пространствах. Для авторской программы передай `translate` — "
            "карту `op_id → element_id` из `address.receipt_map` с ЯВНОЙ "
            "распаковкой `(only,)`, чтобы множественная арность отказала, а "
            "не потерялась. "
            "Без неё любое «совпало» ниже было бы утверждением о пустом "
            "множестве"))
        return out

    common = sorted(set(walls_a) & set(walls_b))
    if common:
        deltas = [max(math.dist(walls_a[i].curve[0], walls_b[i].curve[0]),
                      math.dist(walls_a[i].curve[1], walls_b[i].curve[1]))
                  for i in common]
        exact = sum(1 for value in deltas if value <= tol_mm)
        if exact != len(common):
            # 🔴 A DISCREPANCY WITHOUT AN ADDRESS IS HALF A FINDING (17.08.2026).
            # The line said «совпало 1 из 2, макс 2000 мм» and did NOT NAME
            # which wall. While the comparator had only tests, this was
            # enough; its first live consumer (`built_verdict`, the judge of
            # the built model) hands the verdict to the MODEL, and the model
            # cannot fix an aggregate — it needs an element. The number had
            # already been computed right here and was being discarded. The
            # constitution requires the same thing verbatim: an observation
            # must be typed AND ADDRESSED.
            worst = max(zip(deltas, common), key=lambda pair: pair[0])[1]
            out.append(Divergence(
                "геометрия", "ось стены", f"{len(common)} общих",
                f"совпало {exact}, макс {max(deltas):.1f} мм, худшая `{worst}`",
                "оси стен читаются обоими путями из одних и тех же чисел — "
                "расхождение здесь означало бы дефект сборки, а не границу языка"))

    for label, a_items, b_items in (("положение двери", parse.doors, program.doors),
                                    ("положение окна", parse.windows, program.windows)):
        a_by_id = {item.id: item for item in a_items}
        keys_items = _translated((item.id for item in b_items), translate)
        b_by_id = {keys_items[item.id]: item for item in b_items}
        shared = sorted(set(a_by_id) & set(b_by_id))
        if not shared:
            continue
        along: list[float] = []
        across: list[float] = []
        for item_id in shared:
            ax, ay = a_by_id[item_id].location
            bx, by = b_by_id[item_id].location
            host = walls_a.get(a_by_id[item_id].host_wall_id or "")
            if host is None:
                continue
            (x0, y0), (x1, y1) = host.curve
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if length <= 0.0:
                continue
            ux, uy = dx / length, dy / length
            vx, vy = ax - bx, ay - by
            along.append(abs(vx * ux + vy * uy))
            across.append(abs(vx * -uy + vy * ux))
        if not along:
            continue
        exact_along = sum(1 for value in along if value <= tol_mm)
        exact_across = sum(1 for value in across if value <= tol_mm)
        out.append(Divergence(
            "геометрия" if exact_along != len(along) else СВЕРКА,
            f"{label} — ВДОЛЬ оси хозяина", f"{len(along)} общих",
            f"совпало {exact_along}, макс {max(along):.2f} мм",
            "`offset_mm` — единственная степень свободы, которую язык здесь "
            "выражает; ноль означает, что восстановление точное"))
        if exact_across != len(across):
            out.append(Divergence(
                "геометрия", f"{label} — ПОПЕРЁК оси хозяина", f"{len(across)} общих",
                f"совпало {exact_across}, медиана расхождения "
                f"{_median([v for v in across if v > tol_mm]):.1f} мм, "
                f"макс {max(across):.1f} мм",
                "поперечного смещения у `create_door`/`create_window` НЕТ ВОВСЕ: "
                "программа кладёт проём на ось хозяина, а разбор несёт точку "
                "экземпляра как её хранит Revit — это граница языка, не ошибка"))

    rooms_a = {room.id: room for room in parse.rooms if room.boundary}
    keys_rooms = _translated(
        (room.id for room in program.rooms if room.boundary), translate)
    rooms_b = {keys_rooms[room.id]: room
               for room in program.rooms if room.boundary}
    # REFUSAL INSTEAD OF SILENCE — THE SAME SHAPE AS FOR WALLS EIGHTY LINES
    # ABOVE (HR-09, measured 04.09.2026). For walls, an empty intersection of
    # addresses has been named since 15.08 and is returned as the first line;
    # for rooms there was NO guard AT ALL — the whole branch sat under
    # `if shared_rooms:`, and two NON-EMPTY models with not a single matching
    # room put zero lines into `out`. `render_comparison` prints zero lines
    # as «РАСХОЖДЕНИЙ НЕТ.» — that is, a quantity nobody was counting here
    # was passed off as agreement.
    #
    # Emptiness ON BOTH SIDES (no rooms with an outline at all) is legitimate
    # and stays silent: the guard asks exactly the same question as the wall
    # one — "are both sides non-empty, with nothing in common."
    if rooms_a and rooms_b and not (set(rooms_a) & set(rooms_b)):
        out.append(Divergence(
            "адрес", "помещения не сведены",
            f"{len(rooms_a)} с контуром, пример `{sorted(rooms_a)[0]}`",
            f"{len(rooms_b)} с контуром, пример `{sorted(rooms_b)[0]}`",
            "пересечение идентификаторов ПОМЕЩЕНИЙ пусто: стороны адресуют в "
            "разных пространствах, и «контуры сошлись» было бы утверждением о "
            "пустом множестве. Для авторской программы передай `translate` — "
            "карту `op_id → element_id` из `address.receipt_map` с ЯВНОЙ "
            "распаковкой `(only,)`. Если перевод уже дан, значит помещения "
            "переименованы или не построены: сверка контуров НЕ ВЫПОЛНЯЛАСЬ"))
        return out

    shared_rooms = sorted(set(rooms_a) & set(rooms_b))
    if shared_rooms:
        ious: list[float] = []
        ratios: list[float] = []
        наружу: list[float] = []
        уехали: list[tuple[float, str]] = []
        for room_id in shared_rooms:
            pa = _polygon_or_none(rooms_a[room_id].boundary)
            pb = _polygon_or_none(rooms_b[room_id].boundary)
            if pa is None or pb is None:
                continue
            общее = pa.intersection(pb).area
            union = pa.union(pb).area
            if union > 0:
                ious.append(общее / union)
            if pa.area > 0:
                ratios.append(pb.area / pa.area)
                # SHARE OF THE BUILT THAT LIES OUTSIDE THE DECLARED — see below.
                доля_наружу = max(0.0, 1.0 - общее / pa.area)
                наружу.append(доля_наружу)
                if доля_наружу > _ROOM_OUTSIDE_TOL:
                    уехали.append((доля_наружу, room_id))
        if ious:
            # 🔴 A SECOND QUESTION TO THE SAME NUMBER (HR-10, measured 04.09.2026).
            #
            # THE MEDIAN STAYS, AND ITS REASONING IS UNTOUCHED: the cutout for
            # wall thickness lies INSIDE the axial outline for EVERY correct
            # room, what must be judged is the share that came out OUTSIDE, and
            # the median answers "is the trouble typical across the building."
            # But it answers that question ALONE, when two must be asked: three
            # rooms with shares [0, 0, 1] give a median of 0 — one room
            # ENTIRELY out of place, and the line still stood as the kind
            # "check," meaning agreement.
            #
            # THE THRESHOLD TAKEN IS THE EXISTING ONE, AND THIS IS ITS NATIVE
            # DOMAIN, not a convenience: the table that bought
            # `_ROOM_OUTSIDE_TOL` — four outlines of ONE room (correct 200 mm —
            # 0.0000, correct 400 mm — 0.0000, leaked — 0.1333, shifted —
            # 0.1842). One percent there is named a margin for tessellation
            # noise AT THE ROOM LEVEL. Applying it to a building-wide median
            # was an EXTENSION of that calibration beyond its measurement; the
            # question "is there a room above the threshold" is asked exactly
            # where the threshold was measured.
            #
            # NOT A REPLACEMENT OF THE MEDIAN BY A MAXIMUM: a maximum alone
            # would say "the worst one is such-and-such" and lose "is this
            # typical." Both stand here, and each names its own number.
            расходится = ((_median(наружу) > _ROOM_OUTSIDE_TOL if наружу
                           else False)
                          or bool(уехали))
            # THE NAME IS NOT `program`: that is what the function's PARAMETER
            # is called, and a local variable of the same name would shadow the
            # declared model.
            сторона_Б = (f"{len(shared_rooms)} общих, IoU медиана "
                         f"{_median(ious):.3f}, "
                         f"площадь Б/А медиана {_median(ratios):.3f}, "
                         f"вне заявленного медиана "
                         f"{(_median(наружу) if наружу else 0.0):.4f}")
            if уехали:
                # AN ADDRESS IS MANDATORY: a discrepancy without one is half a
                # finding, the same reasoning as for the worst wall twenty lines
                # above.
                худшая_доля, худшая = max(уехали)
                сторона_Б += (f", ВНЕ СВОЕГО МЕСТА {len(уехали)} из "
                              f"{len(наружу)}, худшая `{худшая}` "
                              f"{худшая_доля:.4f}")
            out.append(Divergence(
                "геометрия" if расходится else СВЕРКА,
                "контур помещения (IoU)",
                f"{len(rooms_a)} с контуром",
                сторона_Б,
                ("разбор несёт контур, вернувшийся из Revit; программа складывает "
                 "его планарным разбиением ОСЕВЫХ ЛИНИЙ стен. Граница помещения в "
                 "Revit идёт по ВНУТРЕННИМ ГРАНЯМ, то есть построенный контур "
                 "обязан быть МЕНЬШЕ заявленного ровно на толщину стен — это "
                 "ожидаемо и расхождением не является. Судится доля построенного "
                 "контура, вышедшая НАРУЖУ заявленного: она и означает, что "
                 "помещение протекло или встало не туда. Вопроса ДВА: медиана "
                 "говорит, типична ли беда по зданию, и отдельно называется "
                 "КАЖДАЯ комната, у которой наружу вышло больше "
                 f"{_ROOM_OUTSIDE_TOL:.0%} — медиана одну уехавшую из трёх "
                 "не видит вовсе")))
    return out


def render_comparison(parse: DesignVerdict, program: DesignVerdict,
                      divergences: Sequence[Divergence]) -> str:
    """The gate table. A match means the path from the program is justified;
    a mismatch — here is the map."""
    lines = [
        f"═══ ВОРОТА: одно здание, два пути — {parse.building_id} ═══",
        f"путь А (разбор):   {_VERDICT_RU.get(parse.verdict, parse.verdict)}",
        f"путь Б (программа): {_VERDICT_RU.get(program.verdict, program.verdict)}",
        "",
    ]
    if not divergences:
        lines.append("РАСХОЖДЕНИЙ НЕТ.")
        return "\n".join(lines)
    width = max(len(d.subject) for d in divergences)
    lines.append(f"расхождений: {len(divergences)}")
    lines.append("")
    current = ""
    for item in divergences:
        if item.kind != current:
            current = item.kind
            lines.append(f"— {current} —")
        lines.append(f"  {item.subject:<{width}}  А={item.parse:<22} "
                     f"Б={item.program:<22}")
        lines.append(f"  {'':<{width}}  причина: {item.cause}")
    return "\n".join(lines)


__all__ = [
    "BRIEF_VERDICT_CAP",
    "DESIGN_STAGE",
    "DESIGN_STAGE_THRESHOLDS",
    "PROGRAM_SHAPE",
    "BUNDLE_CONTRACT",
    "BuildNote",
    "BuildWitness",
    "BundleContractError",
    "VerdictInputError",
    "DesignCheckUnavailable",
    "DesignVerdict",
    "Divergence",
    "ModelSource",
    "OUT_OF_SCOPE",
    "OutOfScope",
    "PARTITION_CLOSE_TOL_MM",
    "PROGRAM_NOT_BUILDABLE",
    "ProgramNotBuildableError",
    "ProgramShapeError",
    "Verdict",
    "check_design",
    # The OUTER door of the verdict: KIR operations, i.e. the sandbox output.
    "check_ops",
    "spatial_model_from_ops",
    # The same door, but the UNIT is a building: a batch of programs (body +
    # staircases).
    "check_bundle",
    "spatial_model_from_bundle",
    "design_stage_profile",
    "compare",
    "compare_geometry",
    "format_check_report",
    "render_comparison",
    "render_verdict",
    "render_verdict_brief",
    "verdict_headline",
    "verdict_headline_text",
    "spatial_model_from_l0",
    # The INTERNAL form of the decompiler (L1 nodes). What goes outward is
    # `*_from_ops`.
    "spatial_model_from_program",
]
