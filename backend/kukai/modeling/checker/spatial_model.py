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
    ЖИЛАЯ = "жилая"                 # habitable: спальня, гостиная, кабинет
    КУХНЯ = "кухня"                 # kitchen / кухня-гостиная
    САНУЗЕЛ = "санузел"             # bathroom / WC / ванная / с/у
    КОРИДОР = "коридор"             # internal corridor (public circulation)
    ЛЕСТНИЦА = "лестница"           # stair / лестничная клетка (public circulation)
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
    elevation_mm: float
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
    apartment_id: str | None = None
    has_window: bool = False
    window_area_m2: float = Field(default=0.0, ge=0.0)
    height_source: str | None = None


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
    riser_count: int | None = None
    tread_depth_mm: float | None = None
    footprint: list[tuple[float, float]] = Field(default_factory=list)
    kind: str = "element"


class Wall(BaseModel):
    """A wall segment on a level (design §3)."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., min_length=1)
    level_id: str = Field(..., min_length=1)
    curve: tuple[tuple[float, float], tuple[float, float]]
    height_mm: float = Field(..., ge=0.0)
    is_structural: bool = False


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
