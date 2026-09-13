# -*- coding: utf-8 -*-
"""AN EGRESS VERDICT HAS NO RIGHT TO STAND ON A GUESSED ROOM FUNCTION.

🔴 WHAT IS RED HERE, BY THE 07.09.2026 MEASUREMENT. The law of function
provenance (`kir/checker/function_provenance.py`, 22.08) is asked by EXACTLY
THREE rules — HAB020, HAB021, HAB030 (`rules/dimensions.py:162,220`,
`rules/light.py:65`). But HAB003 and HAB010 select stair landings with the
line

    room.function is RoomFunction.ЛЕСТНИЦА

(`rules/connectivity.py:150-157`, `250-263`) and do not ask `function_source`
AT ALL. These two rules also lack the precondition
`apartments_from_authored_functions`, with which the engine covered
HAB002/HAB004/HAB042 (`engine.py:381,388,432`).

THE PRICE RUNS IN ONE DIRECTION, AND IT IS THE WORST DIRECTION. A derived
function only ADDS a landing, meaning it can only EXTINGUISH a verdict: a
floor whose only "stair" was recognized by a TOILET FIXTURE or a third-party
classifier (`fixtures`, `host_classifier` — both `derived`, 22.08 and 28.08)
reads as connected to the ground, and HAB010 stays silent. The silence is
indistinguishable from silence about a real stair — exactly the same named
defect of ours for whose sake height provenance was set up on 20.08.

WHAT THE FIX DOES NOT DO: it does not extinguish a single BLOCKING item and
does not touch any thresholds. Only one thing changes — silence resting on a
guess STOPS BEING SILENCE.

Run: KIR_CHECKER_V2=1 pytest \
    kir/checker/tests/test_an_egress_verdict_may_not_stand_on_a_guessed_function.py -q
"""
from __future__ import annotations

import pytest

from kir.checker.graph import build_graph                        # noqa: E402
from kir.checker.rules.connectivity import check_hab010          # noqa: E402
from kir.checker.spatial_model import (                          # noqa: E402
    Door, Level, Room, RoomFunction, Severity, SpatialModel, Stair,
)
from kir.checker.thresholds import THRESHOLDS                     # noqa: E402


#: 🔴 THE LEVER IS SET FOR THE DURATION OF THE TEST, NOT ON MODULE IMPORT. The
#: first edition wrote `os.environ.setdefault("KIR_CHECKER_V2", "1")` in the
#: header — and the lever LEAKED into the entire pytest process: in the shared
#: run,
#: `kir/tests/test_design_check.py::test_v1_path_is_refused_never_silently_downgraded`
#: failed with «DID NOT RAISE DesignCheckUnavailable» (215 passed -> 1 failed),
#: because my file was turning on v2 for someone else's test. The same class
#: as "an instrument is right, but about a different subject": the red in the
#: suite was not where the defect was.
@pytest.fixture(autouse=True)
def _v2(monkeypatch):
    monkeypatch.setenv("KIR_CHECKER_V2", "1")


def _кв(x=0.0, y=0.0, s=3000.0):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]


def _модель(*, площадка_наверху: str | None, источник: str) -> SpatialModel:
    """A two-story building. The models differ ONLY in the name of the
    function's source upstairs.

    `площадка_наверху is None` — a control: there is no landing at all, and
    the rule is OBLIGATED to accuse the floor. It proves that the silence in
    the other two models is held up specifically by the landing, not by the
    scene's setup.
    """
    rooms = [
        Room(id="s0", name="Лестница", level_id="L0", function=RoomFunction.ЛЕСТНИЦА,
             area_m2=9.0, height_mm=3000.0, boundary=_кв(), function_source="room_name"),
        Room(id="r1", name="Спальня", level_id="L1", function=RoomFunction.ЖИЛАЯ,
             area_m2=14.0, height_mm=3000.0, boundary=_кв(4000.0, 0.0),
             function_source="room_name"),
    ]
    if площадка_наверху is not None:
        rooms.append(Room(id=площадка_наверху, name="Помещение", level_id="L1",
                          function=RoomFunction.ЛЕСТНИЦА, area_m2=9.0,
                          height_mm=3000.0, boundary=_кв(),
                          function_source=источник))
    return SpatialModel(
        building_id="b",
        levels=[Level(id="L0", name="L0", elevation_mm=0.0, index=0),
                Level(id="L1", name="L1", elevation_mm=3000.0, index=1)],
        rooms=rooms,
        doors=[Door(id="d0", level_id="L0", location=(0.0, 0.0), width_mm=900.0,
                    from_room_id="s0", to_room_id=None, is_exterior=True)],
        stairs=[Stair(id="st", base_level_id="L0", top_level_id="L1",
                      base_z=0.0, top_z=3000.0, run_width_mm=1200.0)],
    )


def _hab010(model: SpatialModel):
    return check_hab010(model, build_graph(model), THRESHOLDS)


def test_a_landing_that_only_a_guess_calls_a_landing_is_named():
    """RED: the connection to the ground rests on a DERIVED function — say so."""
    находки = _hab010(_модель(площадка_наверху="s1", источник="fixtures"))
    assert находки, (
        "HAB010 промолчал: единственная площадка этажа опознана ОБСТАНОВКОЙ, "
        "и вердикт «этаж связан с землёй» стоит на догадке")
    (одна,) = находки
    assert одна.rule_id == "HAB010"
    # Not BLOCKING: the building may well be fine. But not silence either.
    assert одна.severity is Severity.WARNING, одна.severity
    assert "s1" in одна.refs, одна.refs
    assert "fixtures" in одна.msg, одна.msg


def test_the_same_building_with_an_authored_landing_stays_silent():
    """CONTROL 1: the same scene, differing ONLY in the source's name — silence.

    Without it, the finding above would mean "the rule is noisy," not "the
    rule distinguishes read from derived."
    """
    assert _hab010(_модель(площадка_наверху="s1", источник="room_name")) == []


def test_without_the_guess_the_level_is_blocked_outright():
    """CONTROL 2: remove the landing — BLOCKING. So the silence was held up by a guess."""
    находки = _hab010(_модель(площадка_наверху=None, источник="room_name"))
    assert [f.severity for f in находки] == [Severity.BLOCKING], находки


def test_a_host_classifier_guess_is_named_too():
    """The second derived kind (`host_classifier`, 28.08) — the same law."""
    находки = _hab010(_модель(площадка_наверху="s1", источник="host_classifier"))
    assert находки and "host_classifier" in находки[0].msg, находки


def test_an_unknown_source_is_not_promoted_to_authored():
    """An unfamiliar source name reads as UNCONFIRMED, not as authored."""
    находки = _hab010(_модель(площадка_наверху="s1", источник="новый_съём"))
    assert находки, "новый источник молча получил права автора"


# ------------------------------------------------------- HAB003, the same law

def _квартира(*, источник_площадки: str) -> SpatialModel:
    """An apartment on the second floor; the only exit is a landing ON THE GROUND.

    For HAB003 what decides is the provenance of EXACTLY the ground landing:
    the rule asks "did we reach a stairwell at the exit level," and if that
    room's "stair-ness" is a guess, then the whole egress conclusion turns
    out to be a guess.
    """
    return SpatialModel(
        building_id="b",
        levels=[Level(id="L0", name="L0", elevation_mm=0.0, index=0),
                Level(id="L1", name="L1", elevation_mm=3000.0, index=1)],
        rooms=[
            Room(id="s0", name="Помещение", level_id="L0",
                 function=RoomFunction.ЛЕСТНИЦА, area_m2=9.0, height_mm=3000.0,
                 boundary=_кв(), function_source=источник_площадки),
            Room(id="s1", name="Лестница", level_id="L1",
                 function=RoomFunction.ЛЕСТНИЦА, area_m2=9.0, height_mm=3000.0,
                 boundary=_кв(), function_source="room_name"),
            Room(id="h1", name="Прихожая", level_id="L1",
                 function=RoomFunction.ПРИХОЖАЯ, area_m2=6.0, height_mm=3000.0,
                 boundary=_кв(3000.0, 0.0), apartment_id="кв1",
                 function_source="room_name"),
            Room(id="r1", name="Спальня", level_id="L1",
                 function=RoomFunction.ЖИЛАЯ, area_m2=14.0, height_mm=3000.0,
                 boundary=_кв(6000.0, 0.0), apartment_id="кв1",
                 function_source="room_name"),
        ],
        doors=[
            Door(id="d0", level_id="L0", location=(0.0, 1500.0), width_mm=1200.0,
                 from_room_id="s0", to_room_id=None, is_exterior=True),
            Door(id="d1", level_id="L1", location=(6000.0, 1500.0), width_mm=900.0,
                 from_room_id="h1", to_room_id="r1"),
            Door(id="d2", level_id="L1", location=(3000.0, 1500.0), width_mm=900.0,
                 from_room_id="h1", to_room_id="s1"),
        ],
        stairs=[Stair(id="st", base_level_id="L0", top_level_id="L1",
                      base_z=0.0, top_z=3000.0, run_width_mm=1200.0)],
    )


def _hab003(model: SpatialModel):
    from kir.checker.rules.connectivity import check_hab003

    return check_hab003(model, build_graph(model), THRESHOLDS)


def test_hab003_egress_confirmed_only_by_a_guess_is_named():
    """RED HAB003: the exit is confirmed by a landing that the author did not name."""
    находки = _hab003(_квартира(источник_площадки="fixtures"))
    assert находки, ("HAB003 засчитал эвакуацию молча: наземная площадка "
                     "опознана обстановкой")
    (одна,) = находки
    assert одна.rule_id == "HAB003" and одна.severity is Severity.WARNING
    assert "fixtures" in одна.msg, одна.msg


def test_hab003_stays_silent_when_the_landing_was_read_from_the_author():
    """CONTROL: the same apartment, differing ONLY in the source's name."""
    assert _hab003(_квартира(источник_площадки="room_name")) == []


# ------------------------------------- A VERDICT, NOT A NOTE (self-review)

def _строка(отчёт, rule_id):
    return next(o for o in отчёт.coverage.outcomes if o.rule_id == rule_id)


def _движок(model):
    from kir.checker.engine import run as run_engine

    return run_engine(model, THRESHOLDS)


def test_hab010_withholds_the_guessed_level_instead_of_calling_it_evaluated():
    """🔴 A WARNING IS NOT ENOUGH: the COVERAGE line is obligated to differ.

    Before the 07.09 self-review, both models gave `EVALUATED(n=2),
    excluded=0` — byte-for-byte identical — and "connected to the ground"
    stayed a yes with a footnote.

    🔴 THE NUMBER CHANGED ON THE SAME DAY, AND THIS IS NOT A FIT (07.09, point
    (a)). The two here was OUR OWN MISTAKE, not an expectation: HAB010's
    `RuleSpec` counted ALL occupied levels as subjects, while the rule's body
    `continue`s past the ground level on its very first line. This two-story
    building has exactly one occupied NON-GROUND level, and that is exactly
    the one the rule judged. Measurement on the fixture corpus: 17 buildings
    out of 25 are single-story, and all 17 printed `EVALUATED(n=1)` —
    "judged and clean" about something they never touched. The expectation
    has been recomputed against the FIXED counter, and it is STRONGER than
    before: the guessed model's sole subject is now held back in full, that
    is, the line goes to NOT_EVALUATED rather than "evaluated with a
    deduction."
    """
    угадано = _строка(_движок(_модель(площадка_наверху="s1", источник="fixtures")),
                      "HAB010")
    прочитано = _строка(_движок(_модель(площадка_наверху="s1", источник="room_name")),
                        "HAB010")
    assert (прочитано.n_subjects, прочитано.excluded_subjects) == (1, 0), прочитано
    assert прочитано.status.value == "evaluated", прочитано
    assert (угадано.n_subjects, угадано.excluded_subjects) == (0, 1), угадано
    assert угадано.status.value == "not_evaluated", угадано
    assert "function_guessed" in угадано.excluded_reason, угадано.excluded_reason


def test_hab003_reads_not_evaluated_when_every_exit_rests_on_a_guess():
    """All subjects held back -> NOT_EVALUATED, and this is NOT a "pass"."""
    отчёт = _движок(_квартира(источник_площадки="fixtures"))
    строка = _строка(отчёт, "HAB003")
    assert строка.status.value == "not_evaluated", строка
    assert строка.n_subjects == 0 and строка.excluded_subjects == 1, строка
    assert строка.excluded_reason.startswith("function_guessed:"), строка.excluded_reason
    # HAB003 is mandatory -> the building has NO RIGHT to read as PASS.
    assert "HAB003" in отчёт.coverage.mandatory_not_evaluated
    assert отчёт.verdict.value != "pass", отчёт.verdict


def test_the_same_flat_with_an_authored_landing_is_evaluated():
    """CONTROL: differing ONLY in the source's name — the rule judges and stays silent."""
    строка = _строка(_движок(_квартира(источник_площадки="room_name")), "HAB003")
    assert строка.status.value == "evaluated", строка
    assert (строка.n_subjects, строка.excluded_subjects) == (1, 0), строка
