"""SpatialModel — the normalized building contract (design §3) plus the checker's
violation vocabulary (Severity / Violation / CheckReport). Pure data, no behaviour.
All lengths in millimetres, areas in m**2."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RoomFunction(str, Enum):
    """Common-sense room functions for residential ЖК (design §3/§4).

    Values are the canonical RU lowercase tokens used across the checker.
    `classify.py` maps free-text RU room names onto these members.
    """
    ЖИЛАЯ = "жилая"                 # habitable: bedroom, living room, study
    КУХНЯ = "кухня"                 # kitchen / kitchen-living room
    САНУЗЕЛ = "санузел"             # bathroom / WC / bathroom / sanitary unit
    КОРИДОР = "коридор"             # internal corridor (public circulation)
    ЛЕСТНИЦА = "лестница"           # stair / stairwell (public circulation)
    ЛИФТ_ХОЛЛ = "лифт_холл"         # lift lobby (public circulation)
    ПРИХОЖАЯ = "прихожая"           # apartment entrance hall (private, the apt's root node)
    ВХОДНАЯ_ГРУППА = "входная_группа"  # building entrance group (public circulation)
    ТЕХ = "тех"                     # technical / service
    ПРОЧЕЕ = "прочее"               # fallback / unclassified


class Level(BaseModel):
    """One building level, sorted bottom→top by `index` (design §3)."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    name: str
    #: 🔴 MAY BE UNKNOWN, AND UNKNOWN IS NOT ZERO (13.09.2026). A program that
    #: builds into an EXISTING document addresses its levels by `element_id` /
    #: `unique_id` — the production case — and offline there is no document to
    #: read the elevation from. Until this day such a level did not enter the
    #: model at all, so every element hanging on it vanished with it: measured
    #: on one program with one difference, `create_level` vs `{by: element_id}`,
    #: gave rooms 1→0, walls 4→0, rules 7/20→0/20. Fabricating 0.0 would have
    #: been worse than dropping it: the ground-level band would then call the
    #: fortieth floor "ground". So the level enters, its elevation says "I do
    #: not know", and the rules that need a number say they were not evaluated.
    #: `elevation_source`: "program" (a create_level op), "facts" (the caller's
    #: sheet), None (external and unsupplied).
    elevation_mm: float | None = None
    elevation_source: str | None = None
    external: bool = False
    index: int = Field(..., ge=0, description="0 = lowest occupied level, ascending")


class Room(BaseModel):
    """One enclosed room on a level (design §3).

    `has_window`/`window_area_m2` are a convenience denormalization of windows[]
    filled by the extractor (design §6). Under checker v2 (flags.checker_v2_enabled)
    these DECLARED scalars — and `area_m2` — are recomputed from geometry by the
    derivation pre-pass (derive.py) BEFORE any rule reads them, so declarations become
    cross-checked claims (HAB060), never load-bearing inputs.

    `height_mm` may be None (v2 honest extraction: unknown ≠ a fabricated 2700).
    `height_source` records provenance: "bounded" (room upper-limit geometry),
    "param" (unbounded ROOM_HEIGHT parameter), "declared" (generator/LLM input),
    None (unknown).
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    name: str
    number: str = ""
    level_id: str = Field(..., min_length=1)
    function: RoomFunction
    area_m2: float = Field(..., ge=0.0)
    height_mm: float | None = Field(..., ge=0.0)
    boundary: list[tuple[float, float]] = Field(
        default_factory=list, description="outer loop polygon (mm), in the level plane"
    )
    #: 🔴 ROOM VOIDS — SHAFT, ATRIUM, STAIR CUTOUT (29.08.2026, audit finding
    #: F-041). Empty = there are no voids OR the source does not supply them;
    #: on the PROGRAM path it is empty by construction, on the PARSE path — by
    #: the fact of the building. The order and meaning are the same as in
    #: `RoomInfo.boundary_loops_mm[1:]` and in `decompile.fold._room_contains`:
    #: the outer contour lives in `boundary`, here — only the INNER ones.
    #: WHY A SEPARATE FIELD, NOT A CHANGE OF `boundary`'S TYPE. `Room.boundary`
    #: is read in nine places; changing the type would rewrite them all at
    #: once. A field with an empty default leaves every prior input BYTE FOR
    #: BYTE the same — the same technique as with `height_source` and
    #: `function_source`.
    boundary_holes: list[list[tuple[float, float]]] = Field(
        default_factory=list,
        description="inner loops (mm): shafts/atria cut out of `boundary`")
    apartment_id: str | None = None
    has_window: bool = False
    window_area_m2: float = Field(default=0.0, ge=0.0)
    height_source: str | None = None
    #: 🔴 WHERE THE WORD SITTING IN `function` CAME FROM — THREE KINDS, NOT TWO
    #: (22.08.2026). MNVNK measurement: `ROOM_NAME` equals «Помещение» for 1102
    #: rooms out of 1102, and the function has to be inferred from the
    #: FURNISHING (toilet fixture → bathroom, kitchen front → kitchen, bed →
    #: habitable). A room named by the author and a room whose function was
    #: named by a toilet fixture are different claims, and the rule that
    #: judges 'habitable' floor area is obligated to distinguish them.
    #:
    #: The name dictionary and matcher — `function_provenance`.
    #:
    #: 🔴 THE DEFAULT `declared` FOLLOWS THE SAME LAW AS `Stair.top_level_source`
    #: and `height_source`: a model assembled without this field carries the
    #: function that its author NAMED in the input. An explicit `None` (set
    #: only by the L0 parse — "the room's name said nothing") reads as
    #: `unknown` and cannot serve a strict verdict.
    function_source: str | None = "declared"
    #: Identifiers of the ROOM SEPARATION LINES bounding this room
    #: (`OST_RoomSeparationLines`). NOT all bounding elements: walls and
    #: columns are NOT included here, and this is a load-bearing distinction —
    #: a room's shared wall does NOT connect, a shared separation line does
    #: connect.
    #:
    #: 🔴 WHY THE FILTER SITS AT THE SOURCE, NOT HERE. An element's category is
    #: known only where L0 is read (`design_check.spatial_model_from_l0`). If
    #: we carried RAW `bounding_element_ids` here, the consumer (`graph.py`)
    #: would have to distinguish a separator from a wall without having the
    #: categories — and it would connect rooms through a SHARED WALL, that is,
    #: it would fuse neighboring apartments together. The field therefore
    #: carries MEANING, not raw ids.
    #:
    #: Empty = "there are no separators" OR "the source does not supply them"
    #: — these two cases are indistinguishable here, and the consumer must
    #: know this: on the PROGRAM path the field is empty by construction, on
    #: the PARSE path — by the fact of the building (kindergarten
    #: `sob62_r23_v5`: 0 separators for 120 rooms, measured 18.08.2026).
    separator_ids: tuple[str, ...] = ()


class Door(BaseModel):
    """A door connecting two rooms, or a room to OUTSIDE if is_exterior (design §3)."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    level_id: str = Field(..., min_length=1)
    location: tuple[float, float]
    width_mm: float = Field(..., ge=0.0)
    from_room_id: str | None = None
    to_room_id: str | None = None
    is_exterior: bool = False
    host_wall_id: str | None = None


class Window(BaseModel):
    """A window hosted in a wall, lighting one room (design §3).

    v2 truth fields: `height_mm` is the MEASURED opening height (None = unknown; the
    v1 extractor fabricated area as width x 1.4 — v2 refuses to invent), `location` is
    the instance point used for the geometric window->wall->room join in derive.py."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    level_id: str = Field(..., min_length=1)
    host_wall_id: str | None = None
    room_id: str | None = None
    width_mm: float = Field(..., ge=0.0)
    area_m2: float = Field(..., ge=0.0)
    height_mm: float | None = Field(default=None, ge=0.0)
    location: tuple[float, float] | None = None
    #: 🔴 WHERE THE NUMBER IN `area_m2` COMES FROM — THREE KINDS, NOT ONE
    #: (30.08.2026, audit finding F-254). "measured" — width times MEASURED
    #: height; "declared" — the value that the input's author NAMED; "nominal"
    #: — a substituted stand-in (a live read plugs in `width x 1.4`,
    #: `design_check` — the profile's named nominal). The first two are claims
    #: ABOUT THE BUILDING, the third is a claim about OUR OWN BLINDNESS, and it
    #: cannot be judged by the 1:8 norm. Measurement on the tower: a dimension
    #: exists for 588 windows out of 2952, meaning 2364 substituted numbers
    #: today either exonerate or convict the room.
    #:
    #: 🔴 THE DEFAULT IS "declared", NOT None, AND THIS IS NOT CAUTION BUT THE
    #: LAW OF THIS TREE (verbatim — as with `Stair.top_level_source`): a model
    #: assembled by anyone WITHOUT this field carries the value that its
    #: author named in the input. Silently downgrading such inputs to
    #: "unmeasured" would strip strictness from all existing models at once,
    #: without measuring anything in the process. Measurement: on 17 fixtures
    #: ALL 58 windows go without `height_mm`, meaning unconditional distrust
    #: would switch off the 1:8 norm across the entire reference corpus.
    area_source: str | None = "declared"


class Stair(BaseModel):
    """A stair run connecting base_level_id to top_level_id (design §3).

    v2 truth fields: `run_width_mm` may be None (unmeasured — the v1 extractor
    hardcoded 1200); `kind` distinguishes a real Revit Stairs ELEMENT ("element") from
    a vertical link INFERRED from stacked лестница rooms ("inferred"). Inferred runs
    carry NO invented dimensions and can never certify stair geometry (HAB011)."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    base_level_id: str = Field(..., min_length=1)
    top_level_id: str = Field(..., min_length=1)
    base_z: float
    top_z: float
    run_width_mm: float | None = Field(..., ge=0.0)
    #: 🔴 IT USED TO BE `int | None` WITHOUT A BOUND, AND THIS COULD BRING DOWN
    #: THE JUDGE ENTIRELY (29.08.2026). `check_hab011` computes the rise as
    #: `(top_z - base_z) / riser_count` with no guard: zero risers produced a
    #: ZeroDivisionError and aborted the ENTIRE run — that is, one broken
    #: element cancelled the verdict for the whole building. A negative number
    #: is worse: it yields a negative rise, which passes the "rise not above
    #: the maximum" check and turns dangerous geometry into a clean result.
    #:
    #: `ge=1` is not a guess about the data but agreement with its SUPPLIER:
    #: the extraction (`design_check.py:1313`) already returns `None` when
    #: `int(risers) <= 0`. Zero here never meant "unmeasured" — `None` exists
    #: for that — it meant "a stair with no steps," and no such thing exists.
    #: Only the contract had fallen behind.
    riser_count: int | None = Field(None, ge=1)
    tread_depth_mm: float | None = None
    footprint: list[tuple[float, float]] = Field(default_factory=list)
    kind: str = "element"
    #: 🔴 WHERE `top_level_id`/`top_z` COME FROM — THREE KINDS, NOT TWO
    #: (22.08.2026). MNVNK measurement: `STAIRS_TOP_LEVEL_PARAM` is empty for
    #: 24 stairs out of 24, and the top is DERIVED from the base and the riser
    #: count. A derived value is obligated to name itself as derived:
    #: `check_hab011` computes the rise as `(top_z - base_z) / riser_count`,
    #: and on a derived top this formula returns exactly the riser height that
    #: the top was computed from in the first place — that is, it checks
    #: itself.
    #:
    #: The name dictionary and matcher — `stair_provenance`.
    #:
    #: 🔴 THE DEFAULT IS `declared`, NOT `None`, AND THIS IS THE SAME TECHNIQUE
    #: AS WITH HEIGHT. `derive` has for many waves written
    #: `height_source = r.height_source or "declared"` for one reason: a
    #: `SpatialModel` assembled by anyone WITHOUT this field carries the value
    #: that its author NAMED in the input — this is literally a declaration.
    #: Silently downgrading such models to "unconfirmed" would strip
    #: strictness from all existing inputs at once, without measuring
    #: anything in the process. The duty to name itself falls on whoever
    #: DERIVES, and it does so.
    top_level_source: str | None = "declared"


class Wall(BaseModel):
    """A wall segment on a level (design §3)."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    level_id: str = Field(..., min_length=1)
    curve: tuple[tuple[float, float], tuple[float, float]]
    height_mm: float = Field(..., ge=0.0)
    #: 🔴 THREE STATES, NOT TWO (20.08.2026). The field used to be
    #: `bool = False`, and "we did not ask" was INDISTINGUISHABLE from "we
    #: asked, and the wall is not structural." Before
    #: `WALL_STRUCTURAL_SIGNIFICANT` was added to the capture, the parse
    #: hard-set `False`, and `HAB050` printed "no structural walls flagged" —
    #: which read as a hole of ours. After the capture (live measurement: the
    #: parameter arrives for 7845 walls out of 10 646 and is EVERYWHERE zero),
    #: the same line came to mean the opposite — a fact about the building.
    #: There was no way to tell them apart, because both cases produced the
    #: same value.
    #:
    #: `None` — NOT CAPTURED. `False` — captured, the answer is negative.
    #: Consumers read the field for truthiness (`if wall.is_structural`), so
    #: `None` behaves like the former `False`, and rule behavior has not
    #: shifted one step — only the READABILITY of emptiness has shifted.
    is_structural: bool | None = None
    #: 🔴 THREE STATES AGAIN, AND FOR THE SAME REASON (11.09.2026). A wall
    #: used to be an AXIS with no width, and HAB042 covered the perimeter
    #: with a ±50 mm strip around that axis. But a Revit room boundary lies
    #: on the wall FACE — half a thickness away from the axis. Native witness
    #: 2026-09-09 (`kir-live-20260909/native-spatial-checker.json`): four
    #: walls at x=0/10000, y=0/8000, room boundary at 100…9890 × 110…7900 —
    #: a closed 76.26 m² room was judged "only 2 % enclosed", BLOCKING.
    #:
    #: `None` — NOT CAPTURED (the producer did not read `Wall.Width` /
    #: `WALL_ATTR_WIDTH_PARAM`); a number — the wall's width in mm. Consumers
    #: widen their snap by HALF the thickness when it is known and NAME the
    #: walls whose thickness is unknown, so a false "open" says where it
    #: came from instead of asking for a larger global tolerance.
    thickness_mm: float | None = Field(default=None, ge=0.0)


#: Names of nodes that the GRAPH builds itself and which an author therefore
#: cannot claim.
#:
#: 🔴 DECLARED HERE, NOT IN `graph.py`, AND THIS IS LOAD-BEARING (29.08.2026,
#: audit finding F-264). The graph reserves `OUTSIDE`, `stair:<id>`, and
#: `open_air:<id>`, while the contract accepted ANY non-empty string as an id.
#: A collision was neither rejected nor separated into namespaces:
#: `nx.Graph.add_node` on an existing node UPDATES its attributes, so a room
#: with id `OUTSIDE` merged with the ground — it acquired `kind="outside"`
#: while keeping its own `level_id`/`function` — and a route "to the ground"
#: became indistinguishable from a route "into this room." For evacuation
#: rules this is the worst possible miss: it makes the building SAFER on
#: paper.
#:
#: The dictionary's place is where ids are declared: `graph` already imports
#: this model, a reverse import would create a cycle, and a second instance
#: of the list would drift apart silently. THE GROUND ITSELF. One name for
#: the whole tree: `graph.OUTSIDE` is it, not a copy.
OUTSIDE_ID: str = "OUTSIDE"

RESERVED_NODE_IDS: frozenset[str] = frozenset({OUTSIDE_ID})

#: Prefixes of synthetic nodes. `id.startswith(...)` is the very same
#: condition by which the graph BUILDS these nodes, and it must be kept in one
#: place together with them.
RESERVED_NODE_PREFIXES: tuple[str, ...] = ("stair:", "open_air:")


def reserved_node_conflict(element_id: str) -> str:
    """Why this id cannot belong to an authored element, or it is empty."""
    if element_id in RESERVED_NODE_IDS:
        return (f"id {element_id!r} занят графом под саму ЗЕМЛЮ: узел с этим "
                f"именем строится независимо от модели, и элемент с таким id "
                f"слился бы с ним")
    for prefix in RESERVED_NODE_PREFIXES:
        if element_id.startswith(prefix):
            return (f"id {element_id!r} начинается с {prefix!r} — этим "
                    f"префиксом граф строит СВОИ синтетические узлы, и "
                    f"элемент с таким id слился бы с одним из них")
    return ""


class SpatialModel(BaseModel):
    """The full normalized building (design §3). Pure data; no behaviour."""
    model_config = ConfigDict(frozen=True)

    building_id: str = Field(..., min_length=1)
    levels: list[Level] = Field(default_factory=list)
    rooms: list[Room] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    stairs: list[Stair] = Field(default_factory=list)
    walls: list[Wall] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_authored_id_collides_with_a_graph_node(self) -> "SpatialModel":
        """A collision with a graph node's name is a REFUSAL, not a silent merge.

        Rooms and stairs are checked: only their ids become nodes. The
        refusal is named and pre-effect: a model that the graph cannot
        represent must not reach a verdict — a verdict about it would be a
        claim about a DIFFERENT building.
        """
        bad: list[str] = []
        for room in self.rooms:
            why = reserved_node_conflict(room.id)
            if why:
                bad.append(f"помещение: {why}")
        for stair in self.stairs:
            why = reserved_node_conflict(stair.id)
            if why:
                bad.append(f"лестница: {why}")
        # 🔴 A DUPLICATE ID IS A SILENT MERGE OF NODES, NOT A HARMLESS REPEAT
        # (F-335, 30.08.2026). `nx.Graph.add_node`/`add_edge` on an existing
        # node UPDATE it, so two elements with the same id become ONE place,
        # and the path through them is fiction. Measurement: two independent
        # stair cores on the same pair of floors received one shared
        # `synth_L1_L2` and merged into a node connected to ALL FOUR
        # landings. The refusal is of the same form as the one for a
        # collision with a node's name: named and PRE-EFFECT — a model that
        # the graph cannot represent must not reach a verdict.
        seen: dict[str, str] = {}
        for kind, items in (("помещение", self.rooms), ("лестница", self.stairs)):
            for item in items:
                if item.id in seen:
                    bad.append(f"{kind}: id {item.id!r} уже занят "
                               f"({seen[item.id]}) — граф слил бы их в один узел")
                seen[item.id] = kind
        if bad:
            raise ValueError("; ".join(bad))
        return self


class Severity(str, Enum):
    """Checker-local severity. Mirrors kukai.modeling.schemas.foreman.ReviewSeverity
    EXACTLY (same members + string values) but kept separate by design §8 (checker is
    building-scope, ReviewIssue is proposal-scope). A guard test asserts no drift.
    """
    BLOCKING = "blocking"   # uninhabitable — must fix; any BLOCKING ⇒ report.passed = False
    WARNING = "warning"     # probably wrong — review
    INFO = "info"           # note only


class Violation(BaseModel):
    """One finding from a rule (design §6 report row)."""
    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(..., min_length=1, description="e.g. 'HAB001'")
    severity: Severity
    refs: list[str] = Field(
        default_factory=list, description="element ids this violation points at (rooms/doors/…)"
    )
    msg: str = Field(..., min_length=1, description="human-readable what-is-wrong")
    fix_hint: str = Field(default="", description="actionable suggestion for the fix-loop")


class Verdict(str, Enum):
    """Three-valued verdict (checker v2). `PASS` is a positive claim backed by evaluated
    rules; `FAIL` means at least one BLOCKING violation; `NOT_EVALUATED` means the model
    could not be meaningfully checked (empty/failed extraction, unmeasurable geometry,
    unclassifiable rooms, mandatory rules vacuous) — which must NEVER read as a pass."""
    PASS = "pass"
    FAIL = "fail"
    NOT_EVALUATED = "not_evaluated"


class RuleStatus(str, Enum):
    """Per-rule engagement status (checker v2 coverage)."""
    EVALUATED = "evaluated"          # the rule examined >=1 real subject
    NOT_EVALUATED = "not_evaluated"  # vacuous — nothing measurable to examine


class RuleOutcome(BaseModel):
    """How one rule engaged with the model (checker v2 coverage row)."""
    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(..., min_length=1)
    status: RuleStatus
    n_subjects: int = Field(default=0, ge=0, description="elements the rule examined")
    reason: str = Field(default="", description="why NOT_EVALUATED (empty when evaluated)")
    #: Subjects WITHHELD from the rule because they lack the input it reads
    #: (StageProfile.subject_inputs). EVALUATED(n) with excluded>0 means "the rule
    #: spoke about n and stayed silent about excluded" — which is a different claim
    #: from EVALUATED(n) alone, and the difference is the whole point.
    excluded_subjects: int = Field(default=0, ge=0)
    excluded_reason: str = Field(default="", description="which input the excluded subjects lack")


class CoverageInfo(BaseModel):
    """What the check actually LOOKED AT (checker v2). A verdict without coverage is a
    claim without a witness — this section makes vacuous rules visible instead of
    indistinguishable from clean passes."""
    model_config = ConfigDict(frozen=True)

    outcomes: list[RuleOutcome] = Field(default_factory=list)
    rules_evaluated: int = 0
    rules_not_evaluated: int = 0
    mandatory_not_evaluated: list[str] = Field(default_factory=list)
    classification_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    unclassified_room_ids: list[str] = Field(default_factory=list)
    measured_room_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    unmeasured_room_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    #: Which stage profile decided this rule set ("" = the full as-built profile).
    #: A rule COUNT without the stage that produced it is the half-fact that gets
    #: quoted as "the checker looked at everything" (see thresholds.StageProfile).
    profile_name: str = ""


class CheckReport(BaseModel):
    """Aggregate result of engine.run(model, thr) (design §2/§11).

    v1 contract (verdict is None): passed <=> no BLOCKING violation.
    v2 contract (verdict set): passed <=> verdict is PASS; FAIL requires >=1 BLOCKING;
    PASS additionally requires the mandatory rule set to have evaluated real subjects
    (enforced by the engine, witnessed by `coverage`)."""
    model_config = ConfigDict(frozen=True)

    passed: bool
    blocking: list[Violation] = Field(default_factory=list)
    warnings: list[Violation] = Field(default_factory=list)
    info: list[Violation] = Field(default_factory=list)
    verdict: Verdict | None = None
    coverage: CoverageInfo | None = None

    @model_validator(mode="after")
    def _consistency(self) -> "CheckReport":
        has_blocking = len(self.blocking) > 0
        if self.verdict is None:
            # v1 contract: passed <=> no BLOCKING
            if self.passed and has_blocking:
                raise ValueError("passed=True is incompatible with a BLOCKING violation")
            if not self.passed and not has_blocking:
                raise ValueError("passed=False requires at least one BLOCKING violation")
            return self
        # v2 contract
        if self.passed != (self.verdict is Verdict.PASS):
            raise ValueError("passed must be True exactly when verdict is PASS")
        if self.verdict is Verdict.PASS and has_blocking:
            raise ValueError("verdict PASS is incompatible with a BLOCKING violation")
        if self.verdict is Verdict.FAIL and not has_blocking:
            raise ValueError("verdict FAIL requires at least one BLOCKING violation")
        return self
