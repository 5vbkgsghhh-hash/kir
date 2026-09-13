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
    #: rule_id -> the name (or LIST of names) of the input the stage requires from the subject;
    #: a closed dict, resolved in `engine.SUBJECT_INPUTS`. A subject is held back
    #: if it is missing AT LEAST ONE of the named ones.
    #:
    #: A list has been allowed since 17.08.2026: HAB030 has TWO inputs — "the room's
    #: contour is measurable" (`room_polygon`) and "the fact of a window is read at all"
    #: (`room_window_readable`) — and a live-reading stage must name both.
    #: A single string remains a legal entry: no existing profile needs
    #: to be rewritten.
    subject_inputs: dict[str, str | list[str]] = {}
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


#: Dials that are, by meaning, RATIOS. A value outside [0, 1] for them is not a "strict
#: profile" but nonsense: a coverage ratio of 2.0 is unreachable for any building,
#: a ratio of −1 is reachable for ANY of them.
#:
#: The list is CLOSED and guarded below: a new dial with the `_ratio` suffix
#: that is not added here fails the check. Otherwise the next ratio would slide into the
#: same silence this list grew out of.
_RATIO_DIALS = frozenset({
    "stair_min_footprint_overlap_ratio",
    "min_daylight_ratio",
    "min_envelope_coverage_ratio",
    "area_mismatch_rel",
    "min_classification_coverage",
    "min_measured_room_ratio",
    "min_floorplate_coverage",
})


class Thresholds(BaseModel):
    """The judge's dials. EACH must be finite, non-negative, and a ratio must be in [0, 1].

    🔴 BEFORE 29.08.2026 ALL OF THEM WERE BARE `float`, AND THIS SILENTLY DISABLED THE GATE.
    Three values passed validation and looked like an ordinary user
    profile rather than a refusal:

        Thresholds(min_area_zhilaya_m2=float("nan"))     -> HAB020 GOES GREEN
        Thresholds(min_measured_room_ratio=-1)           -> the verdict gate
                                                            lets ANY model through
        Thresholds(stair_min_footprint_overlap_ratio=2)  -> impassable for nothing

    NaN is the most dangerous of all: an ordinary comparison with it is FALSE both ways, so
    the rule doesn't "fail" — it quietly stops finding violations. The judge stays
    green, the verdict looks delivered, and there is nothing to tell it apart from an honest PASS —
    exactly what this corpus was written against.

    Measured after the fix: the three values above are rejected at model validation,
    and all defaults pass unchanged (the default profile is untouched).
    """

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

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


    @model_validator(mode="after")
    def _every_dial_is_finite_nonnegative_and_a_ratio_is_a_ratio(self) -> "Thresholds":
        """Finiteness is covered by `allow_inf_nan=False`; here it's sign and range.

        WHY NOT `Field(ge=0)` ON EVERY FIELD: there are thirty of them, and thirty
        identical clauses is thirty places where the next dial will
        forget its own. Here there is one law for all, and it also guards ITSELF:
        a ratio not added to `_RATIO_DIALS` fails the check.
        """
        bad: list[str] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if not isinstance(value, float):
                continue
            if value < 0.0:
                bad.append(f"{name}={value!r}: настройка судьи не может быть "
                           f"отрицательной — отрицательный порог проходит ЛЮБАЯ модель")
            if name in _RATIO_DIALS and value > 1.0:
                bad.append(f"{name}={value!r}: это ДОЛЯ, значение выше 1 "
                           f"недостижимо ни для одного дома")
        # A GUARD ON THE LIST ITSELF. A dial named as a ratio but not added to the
        # closed list would only be checked for sign — that is, a "ratio of 2.0"
        # would pass silently, and that is exactly the case this law started from.
        undeclared = sorted(
            n for n in type(self).model_fields
            if (n.endswith("_ratio") or n.endswith("_coverage"))
            and n not in _RATIO_DIALS)
        if undeclared:
            bad.append(f"настройки {undeclared} названы долями и не внесены в "
                       f"_RATIO_DIALS — их область никто не сторожит")
        if bad:
            raise ValueError("; ".join(bad))
        return self


THRESHOLDS = Thresholds()
