"""Checker v2 adversarial probes as pytest (roadmap 'Checker correctness & trust').

Every case here was EMPIRICALLY passed=True by the v1 checker (see step12/probes.py and
baseline_before.txt): a sealed 5-story building, an empty model, a wall-stripped
building, a 1.3 m kitchen, a fabricated shaft window, a declared-area lie, unclassified
room names, a 300 mm stair, and a fix-loop that certified its own scalar edits. With
KUKAI_CHECKER_V2=1 they must all FAIL (or read NOT-EVALUATED) — and the known-good
buildings, including the v1 false-BLOCKING victims (тех-room, 1-story house), must PASS.
"""
import pytest

from kukai.modeling.tests.checker import v2_probes as probes
from kukai.modeling.checker.engine import run
from kukai.modeling.checker.spatial_model import SpatialModel, Verdict


@pytest.fixture(autouse=True)
def _v2_on(monkeypatch):
    monkeypatch.setenv("KUKAI_CHECKER_V2", "1")


def _check(model_dict: dict):
    return run(SpatialModel.model_validate(model_dict))


def _blocking_ids(report) -> set[str]:
    return {v.rule_id for v in report.blocking}


# ------------------------------------------------------------------ adversarial: FAIL

def test_empty_model_is_not_a_pass():
    """Probe B: a failed/empty extraction certified the building in v1 (HAB000 was INFO
    theater). v2: BLOCKING HAB000 + three-valued NOT_EVALUATED verdict."""
    rep = _check(probes.probe_empty())
    assert rep.passed is False
    assert rep.verdict is Verdict.NOT_EVALUATED
    assert "HAB000" in _blocking_ids(rep)
    assert rep.coverage is not None and rep.coverage.rules_evaluated == 0


def test_declared_area_lie_fails():
    """Probe A: bedroom declares 8.75 m² over a 1.0 m² polygon → v1 passed. v2: the
    declaration-consistency rule blocks it AND the area rule runs on the DERIVED area."""
    rep = _check(probes.probe_declared_area_lie())
    assert rep.passed is False and rep.verdict is Verdict.FAIL
    assert "HAB060" in _blocking_ids(rep)          # the lie itself
    assert "HAB020" in _blocking_ids(rep)          # 1.0 m² жилая < 8 m², measured


def test_fabricated_shaft_window_fails():
    """Probe I/C: a window hosted in NOTHING (host_wall_id=None) satisfied HAB030 in v1.
    v2: the window never verifies → the room is windowless (HAB030) and the declared
    has_window=true is an unbacked claim (HAB060)."""
    rep = _check(probes.probe_fabricated_window())
    assert rep.passed is False and rep.verdict is Verdict.FAIL
    assert "HAB030" in _blocking_ids(rep)
    assert "HAB060" in _blocking_ids(rep)


def test_narrow_kitchen_fails_via_width_rule_only():
    """Probe F: the 1.3 m kitchen (the real DeepSeek head-to-head output passed v1 with
    ZERO findings). v2: BLOCKING HAB021 — and nothing else, the probe is clean."""
    rep = _check(probes.probe_narrow_kitchen())
    assert rep.passed is False and rep.verdict is Verdict.FAIL
    assert _blocking_ids(rep) == {"HAB021"}


def test_walls_deleted_live_shape_fails():
    """Probe G: live extractions carry no apartment stamps, so v1's HAB042 checked ZERO
    apartments and a wall-stripped building passed. v2 derives apartments stamp-free →
    open envelope is BLOCKING; the windows also lose their hosts (HAB030/HAB060)."""
    rep = _check(probes.probe_walls_deleted_live_shape())
    assert rep.passed is False and rep.verdict is Verdict.FAIL
    assert "HAB042" in _blocking_ids(rep)
    assert "HAB030" in _blocking_ids(rep)


def test_unclassified_english_names_fail():
    """Probe E2: 'Bedroom 1' (2 m², windowless, 1.2 m ceiling) and 'Kitchen' (1.5 m²)
    were ПРОЧЕЕ → no thresholds → v1 passed. v2 upgrades the declared-прочее functions
    from the extended lexicon and the habitability rules finally run."""
    rep = _check(probes.probe_unclassified_names())
    assert rep.passed is False and rep.verdict is Verdict.FAIL
    fired = _blocking_ids(rep)
    assert "HAB020" in fired      # 2 m² bedroom / 1.5 m² kitchen, measured
    assert "HAB030" in fired      # windowless bedroom
    assert "HAB022" in fired      # 1.2 m ceiling < 2.2 m hard floor


def test_truly_unknown_names_cannot_pass():
    """Names outside every lexicon must surface as a coverage failure — unknown ≠ pass."""
    d = probes.control_good()
    for r in d["rooms"]:
        if r["id"] in ("bed", "kit"):
            r["name"] = f"Зона {r['id']}"
            r["function"] = "прочее"
            r["has_window"] = False
            r["window_area_m2"] = 0.0
    d["windows"] = [w for w in d["windows"] if w["id"] not in ("w_bed", "w_kit")]
    rep = _check(d)
    assert rep.passed is False
    assert rep.verdict is Verdict.NOT_EVALUATED
    assert rep.coverage is not None
    assert "HAB030" in rep.coverage.mandatory_not_evaluated  # no daylit rooms remained
    assert rep.coverage.classification_coverage < 0.75


def test_unbuildable_stair_fails():
    """Probe K: 300 mm-wide stair rising 6 m, riser/tread nulls (live shape) → v1
    skipped HAB011 entirely. v2: the measured 300 mm width is BLOCKING; the unmeasured
    rise/going produce explicit 'cannot verify' warnings."""
    rep = _check(probes.probe_unbuildable_stair())
    assert rep.passed is False and rep.verdict is Verdict.FAIL
    assert "HAB011" in _blocking_ids(rep)
    assert any(v.rule_id == "HAB011" and "unmeasured" in v.msg for v in rep.warnings)


def test_sealed_five_story_fails():
    """Probe D2 — the flagship collapse: a fully sealed 5-story building whose only
    'exterior' door is a floor-3 corridor door to an unplaced closet (v1: floor 3
    became 'ground', everything had 'egress', passed=True). v2: exteriority is
    positive-evidence-only → no entrance at all → unreachable + no egress + floating."""
    rep = _check(probes.probe_sealed_five_story())
    assert rep.passed is False and rep.verdict is Verdict.FAIL
    fired = _blocking_ids(rep)
    assert "HAB001" in fired     # truly sealed: nothing reachable from any entrance
    assert "HAB003" in fired     # no apartment has egress to grade
    assert "HAB010" in fired     # no ground level → every occupied level floats


def test_balcony_exterior_door_is_not_ground():
    """Elevation gating alone: even a REAL envelope door on floor 3 must not make
    floor 3 'ground' (the balcony-door variant of D2)."""
    d = probes.probe_sealed_five_story()
    for door in d["doors"]:
        if door["id"] == "d_fake_exit":
            door["location"] = [4000, 0]   # ON the facade (envelope ring), floor 3
    rep = _check(d)
    assert rep.passed is False and rep.verdict is Verdict.FAIL
    assert "HAB003" in _blocking_ids(rep)   # egress must reach GRADE, not a balcony
    assert "HAB010" in _blocking_ids(rep)


# ------------------------------------------------ self-certification loops are closed

def test_fix_loop_scalar_fixers_can_no_longer_certify():
    """Probe C: the v1 fixer writes has_window=True + a host-less window — exactly the
    scalars HAB030 reads — and v1 then passed. Under v2 the same fixer must FAIL."""
    from kukai.modeling.checker.fixtures.builders import bad_bedroom_no_window
    from kukai.modeling.generator.fix_loop import DEFAULT_FIXERS, run_loop
    res = run_loop(bad_bedroom_no_window(), fixers=DEFAULT_FIXERS)
    assert res.passed is False
    assert res.certified is False


def test_fix_loop_v2_geometric_fixer_repairs_honestly():
    """The v2 fixer hosts a real, measured window in a wall on the room's
    envelope-exterior edge — an edit the derivation layer verifies independently."""
    from kukai.modeling.checker.derive import derive
    from kukai.modeling.checker.fixtures.builders import bad_bedroom_no_window
    from kukai.modeling.checker.thresholds import THRESHOLDS
    from kukai.modeling.generator.fix_loop import run_loop
    res = run_loop(bad_bedroom_no_window())     # flag on → DEFAULT_FIXERS_V2
    assert res.passed is True, res.history
    # independent witness: derivation on the repaired dict verifies the new window
    dmodel, drep = derive(SpatialModel.model_validate(res.model), THRESHOLDS)
    bed = next(r for r in dmodel.rooms if r.id == "bed")
    assert bed.has_window is True
    assert drep.rooms["bed"].verified_window_ids
    assert res.certified is False               # dict-verdicts never certify the world


def test_llm_cannot_certify_with_scalar_edits():
    """llm_adapt under v2: an 'LLM' that answers HAB030 feedback by flipping
    has_window=true (the exact move the v1 system prompt taught) must not converge."""
    import copy
    import json
    from kukai.modeling.checker.fixtures.builders import bad_bedroom_no_window
    from kukai.modeling.generator.llm_adapt import adapt

    base = bad_bedroom_no_window()

    def scalar_liar(messages):
        d = copy.deepcopy(base)
        for r in d["rooms"]:
            if r["id"] == "bed":
                r["has_window"] = True
                r["window_area_m2"] = 2.5
        return json.dumps(d, ensure_ascii=False)

    res = adapt(base, "add light to the bedroom", max_iters=2, complete=scalar_liar)
    assert res.passed is False
    assert res.certified is False


def test_v2_system_prompt_does_not_teach_scalar_certification():
    from kukai.modeling.generator.llm_adapt import SYSTEM_V2
    assert "has_window=true" not in SYSTEM_V2
    assert "host" in SYSTEM_V2 and "envelope" in SYSTEM_V2


# ------------------------------------------------------------ round-trip certification

def _raw_payload_from(model_dict: dict, *, drop_windows: bool = False) -> dict:
    """A raw-extractor-shaped payload for the mock world: what a read-only re-extraction
    of a faithfully-built model would return (functions classified from RU names)."""
    raw_rooms = [
        {"id": r["id"], "name": r["name"], "number": r.get("number", ""),
         "level_id": r["level_id"], "area_m2": r["area_m2"], "height_mm": r["height_mm"],
         "boundary": r["boundary"]}
        for r in model_dict["rooms"]
    ]
    return {
        "building_id": model_dict["building_id"],
        "levels": model_dict["levels"],
        "rooms": raw_rooms,
        "doors": model_dict["doors"],
        "windows": [] if drop_windows else model_dict["windows"],
        "stairs": model_dict["stairs"],
        "walls": model_dict["walls"],
    }


def test_roundtrip_certifies_only_what_the_world_contains():
    from kukai.modeling.checker.fixtures.builders import make_good
    from kukai.modeling.generator.roundtrip import certify

    model = make_good()
    honest_world = {"built": False}

    def mat(m):
        honest_world["built"] = True
        return {"created": ["1"]}

    res = certify(model, mat, lambda: _raw_payload_from(model))
    assert honest_world["built"] is True
    assert res.certified is True
    assert res.report.verdict is Verdict.PASS


def test_roundtrip_catches_a_lying_world():
    """The dict passes on paper; the 'materializer' silently drops every window. The
    round-trip verdict must come from the re-extraction, not the author's dict."""
    from kukai.modeling.checker.fixtures.builders import make_good
    from kukai.modeling.generator.roundtrip import certify

    model = make_good()
    res = certify(model, lambda m: {"created": []},
                  lambda: _raw_payload_from(model, drop_windows=True))
    assert res.dict_report is not None and res.dict_report.passed is True
    assert res.certified is False
    assert "HAB030" in {v.rule_id for v in res.report.blocking}


def test_roundtrip_preflight_never_builds_a_rejected_model():
    from kukai.modeling.checker.fixtures.builders import bad_bedroom_no_window
    from kukai.modeling.generator.roundtrip import certify

    touched = {"mat": False, "ext": False}

    def mat(m):
        touched["mat"] = True
        return {}

    def ext():
        touched["ext"] = True
        return {}

    res = certify(bad_bedroom_no_window(), mat, ext)
    assert res.certified is False
    assert touched == {"mat": False, "ext": False}


# --------------------------------------------------- known-good: no false BLOCKING

def test_good_building_passes_with_full_coverage():
    rep = _check(probes.control_good())
    assert rep.passed is True and rep.verdict is Verdict.PASS
    assert rep.blocking == [] and rep.warnings == []
    assert rep.coverage is not None
    assert rep.coverage.mandatory_not_evaluated == []
    assert rep.coverage.classification_coverage == 1.0
    assert rep.coverage.measured_room_ratio == 1.0


def test_tech_room_is_not_an_apartment():
    """Probe H (v1 false-BLOCKING): an Электрощитовая off the corridor tripped HAB004
    'apartment without прихожая'. v2: service rooms are exempt from apartment rules."""
    rep = _check(probes.control_tech_room())
    assert rep.passed is True and rep.verdict is Verdict.PASS, [
        (v.rule_id, v.msg) for v in rep.blocking
    ]


def test_one_story_house_with_street_door_passes():
    """Probe M (v1 false-BLOCKING): a valid 1-story house with a street door and no
    stair tripped HAB003. v2: a ground-level exterior door IS egress."""
    rep = _check(probes.control_one_story_no_stair())
    assert rep.passed is True and rep.verdict is Verdict.PASS, [
        (v.rule_id, v.msg) for v in rep.blocking
    ]
