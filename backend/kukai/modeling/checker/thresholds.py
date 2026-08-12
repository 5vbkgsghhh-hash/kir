"""All tunable thresholds for the ruleset (design §6). The 'common sense' dials.
Swapping this object (or its values) is how a future formal СП/СНиП profile is built.

`StageProfile` (below) is the SECOND injectable dimension: not "which numbers", but
"which rules this DESIGN STAGE is entitled to be judged by". It rides on `Thresholds`
because `engine.run(model, thr)` already takes that object — the seam exists, so the
engine gets extended, never forked.
"""

from pydantic import BaseModel, ConfigDict, model_validator


class StageProfile(BaseModel):
    """A NAMED rule profile for one design stage (checker v2, engine `_run_v2`).

    The problem it solves, measured: `HAB011` (stair geometry) is `mandatory` whenever
    the model holds ANY stair (`engine.RULE_SPECS_V2`), and riser count / tread depth
    exist in no design-stage representation we own — neither a KIR program nor frozen
    L0 1.0 carries them. Without a profile EVERY building with a stair reads
    NOT_EVALUATED forever, and a verdict that is always the same is not a verdict.

    Three levers, and no fourth:

    * `suspended` — rule_id -> WHY this stage cannot supply the rule's inputs. A
      suspended rule DOES NOT RUN (it can neither pass, nor fail, nor accuse), its
      coverage row is NOT_EVALUATED carrying that exact reason, and it is never
      mandatory. This is for rules whose inputs the stage does not express AT ALL:
      running them would produce findings about the REPRESENTATION, not the building.
    * `mandatory` — rule_id -> whether the verdict may depend on it. Overrides the
      engine's per-rule `mandatory(ctx)` predicate. A rule that RUNS but whose subjects
      this stage cannot measure belongs here, not in `suspended`: it still emits its
      honest "cannot verify" findings, it just may not veto the verdict.
    * `subject_inputs` — rule_id -> the per-room/per-door INPUT without which that rule
      has nothing to say. The rule still runs, but ONLY over the subjects that carry
      the input; the rest are counted as `excluded_subjects` in the coverage row.

      THE LAW THIS ENFORCES: a rule may not fire on an input it does not have. A rule
      that fires anyway is not reporting a defect of the building, it is reporting its
      own blindness — and doing so in the confident voice of a finding, which is worse
      than silence. Measured 2026-08-03 (K2 tower): `HAB020` produced 732 BLOCKING
      "area 0 m² is below the minimum 8 m²" for rooms whose boundary polygon never
      formed. Zero-instead-of-unknown is a lie, and `Room.area_m2` has no way to spell
      "unknown" — so the subject is withheld from the rule instead.

      The filter may only be applied to rules that iterate their subjects
      INDEPENDENTLY (see `_ROOM_FILTERABLE` / `_DOOR_FILTERABLE` in engine.py):
      handing a pruned model to a rule that reasons about the graph as a whole would
      change its meaning, not just its scope.
    * `nominal_opening_area_m2` — the ONE named default this profile hands to a model
      builder: an opening whose SIZE the stage does not fix (a KIR program names a
      family `symbol`; the dimensions live in the family, and the grounding snapshot's
      `window_symbols` entries carry `params: null` — measured 2026-08-03). It exists so
      a PRESENCE test (`HAB030`: is there an exterior window at all) is not defeated by
      an unmeasurable area, and the validator below makes sure it can never reach a rule
      that COMPARES that area against a dial.

    Nothing here weakens a numeric threshold. A profile that wants softer numbers builds
    a different `Thresholds`; that is a separate, visible act. Nothing here silences a
    rule either: a suspended or filtered rule SAYS SO in the coverage row, with the name
    of the input it is missing.
    """
    model_config = ConfigDict(frozen=True)

    name: str
    note: str = ""
    #: rule_id -> reason this stage cannot supply the rule's inputs
    suspended: dict[str, str] = {}
    #: rule_id -> may the verdict depend on this rule at this stage
    mandatory: dict[str, bool] = {}
    #: rule_id -> name of the per-subject input the rule requires (closed vocabulary,
    #: resolved in engine.SUBJECT_INPUTS)
    subject_inputs: dict[str, str] = {}
    #: rule_id -> names of MODEL-WIDE inputs that must exist before the rule may
    #: speak at all (closed vocabulary, resolved in engine.PRECONDITIONS). Unlike
    #: `subject_inputs` these are facts only the derivation knows — chiefly "is any
    #: level ground at all". A rule whose precondition fails is NOT_EVALUATED with
    #: that precondition named: measured 2026-08-03, with zero ground levels HAB010
    #: accused 4 of 4 occupied levels of not reaching a ground it had never found.
    preconditions: dict[str, list[str]] = {}
    #: named stand-in for an opening whose size the stage does not express (m2)
    nominal_opening_area_m2: float | None = None

    #: Every rule that compares an opening AREA against a dial. If a nominal is
    #: declared, all of these must be suspended, or the nominal quietly becomes the
    #: number a threshold is measured against — which is the defect, not the fix.
    AREA_QUANTITATIVE_RULES: tuple[str, ...] = ("HAB031",)

    @model_validator(mode="after")
    def _nominal_cannot_become_load_bearing(self) -> "StageProfile":
        if self.nominal_opening_area_m2 is None:
            return self
        if self.nominal_opening_area_m2 <= 0.0:
            raise ValueError("nominal_opening_area_m2 must be positive when declared")
        missing = [rid for rid in self.AREA_QUANTITATIVE_RULES
                   if rid not in self.suspended]
        if missing:
            raise ValueError(
                "a named nominal opening area may only stand in for a PRESENCE test: "
                f"suspend {missing} first, or the nominal silently becomes the number "
                "a threshold is compared against")
        return self

    @model_validator(mode="after")
    def _filter_and_suspension_are_exclusive(self) -> "StageProfile":
        both = sorted(set(self.subject_inputs) & set(self.suspended))
        if both:
            raise ValueError(
                f"{both} are both suspended and subject-filtered — a rule that does "
                "not run cannot also run on a subset; pick which is true")
        return self

    def is_suspended(self, rule_id: str) -> bool:
        return rule_id in self.suspended

    def suspension_reason(self, rule_id: str) -> str:
        return self.suspended.get(rule_id, "")


class Thresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: Which design stage's rule set applies. None = the full as-built profile, i.e.
    #: bit-for-bit the behaviour every existing caller already gets.
    profile: StageProfile | None = None

    # HAB011 — stair geometry sanity (mm)
    stair_min_run_width_mm: float = 1000.0
    stair_max_rise_mm: float = 180.0
    stair_min_going_mm: float = 250.0
    # HAB012 — core continuity
    stair_min_footprint_overlap_ratio: float = 0.50
    # HAB020 — minimum room area by function (m²)
    min_area_zhilaya_m2: float = 8.0
    min_area_kuhnya_m2: float = 5.0
    min_area_sanuzel_m2: float = 2.2
    # HAB021 — minimum room width (mm)
    min_width_zhilaya_mm: float = 2000.0
    min_width_koridor_mm: float = 900.0
    # HAB022 — minimum ceiling height (mm)
    min_ceiling_height_mm: float = 2500.0
    # HAB031 — daylight ratio window/floor (window_area_m2 : floor_area_m2)
    min_daylight_ratio: float = 1.0 / 8.0
    # HAB040 — room footprint overlap (m²)
    max_room_overlap_m2: float = 0.05
    # HAB042 — envelope gap (mm) + minimum substantial-enclosure coverage ratio
    max_envelope_gap_mm: float = 50.0
    # 0.10: with length-based coverage (clash.py) an under-walled-but-real apartment
    # (GOOD ~0.28) clears this floor while a wall-stripped or point-walled one (~0.03) does not.
    min_envelope_coverage_ratio: float = 0.10
    # HAB041/HAB042 — how close a wall must lie to a door / to the perimeter to count as
    # hosting / enclosing it (mm). Was a hidden 50.0 inside clash.py; lifted here (review fix).
    wall_snap_tol_mm: float = 50.0
    # HAB050 — column→support alignment tolerance + minimum support overlap (mm)
    struct_support_offset_mm: float = 200.0
    struct_min_support_overlap_mm: float = 300.0

    # ------------------------------------------------------------------ checker v2 dials
    # derive.py — geometric join tolerance (mm): room boundaries are offset from wall
    # centerlines by up to a wall half-thickness, so doors/windows sit up to ~150-200 mm
    # away from the boundary polyline they serve; 300 covers thick walls without
    # swallowing a whole niche.
    derive_join_tol_mm: float = 300.0
    # derive.py — morphological-closing radius when unioning rooms into the level
    # footprint (fills wall-thickness gaps between adjacent rooms).
    derive_close_tol_mm: float = 300.0
    # derive.py — a window's host wall must overlap the room boundary ring AND the level
    # envelope by at least this length (mm) to count as a verified exterior window.
    window_host_min_overlap_mm: float = 400.0
    # derive.py — ground levels: an exterior door counts as GRADE egress only when its
    # level sits within this band above the lowest occupied level (kills the "floor 3
    # is ground because a balcony/fake door is exterior" collapse).
    ground_elevation_band_mm: float = 1500.0
    # HAB060 — declared-vs-derived area mismatch tolerance: BLOCKING when BOTH exceeded.
    area_mismatch_abs_m2: float = 0.5
    area_mismatch_rel: float = 0.10
    # HAB021 v2 — width floors for kitchens / bathrooms (mm). A kitchen narrower than
    # 1700 mm cannot hold a 600 counter + passage → BLOCKING (probe F: the 1.3 m kitchen).
    min_width_kuhnya_mm: float = 1700.0
    min_width_sanuzel_mm: float = 800.0
    # HAB022 v2 — hard uninhabitable ceiling floor (BLOCKING below; WARNING below the
    # comfort floor min_ceiling_height_mm).
    min_ceiling_hard_mm: float = 2200.0
    # HAB062 — unclassified rooms at/above this derived area are flagged (WARNING).
    unclassified_min_area_m2: float = 4.0
    # verdict gate — minimum share of classified rooms for PASS to be claimable.
    min_classification_coverage: float = 0.75
    # verdict gate — minimum share of rooms with a measurable boundary polygon.
    min_measured_room_ratio: float = 0.75
    # HAB063 — floor-plate dead-void instrument: rooms-union / closed-footprint ratio
    # below this is WARNING (non-blocking v1 of the rule; courtyards legitimately dip).
    min_floorplate_coverage: float = 0.80


THRESHOLDS = Thresholds()
