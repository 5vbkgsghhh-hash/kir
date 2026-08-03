"""Contract tests for the SpatialModel pydantic schema (design §3)."""
import pytest
from pydantic import ValidationError

from kukai.modeling.checker.spatial_model import (
    Level, Room, Door, Window, Stair, Wall, SpatialModel,
    RoomFunction, Severity, Violation, CheckReport,
)
from kukai.modeling.schemas.foreman import ReviewSeverity


def test_room_function_has_all_spec_members():
    expected = {
        "ЖИЛАЯ": "жилая", "КУХНЯ": "кухня", "САНУЗЕЛ": "санузел",
        "КОРИДОР": "коридор", "ЛЕСТНИЦА": "лестница", "ЛИФТ_ХОЛЛ": "лифт_холл",
        "ПРИХОЖАЯ": "прихожая", "ВХОДНАЯ_ГРУППА": "входная_группа",
        "ТЕХ": "тех", "ПРОЧЕЕ": "прочее",
    }
    assert {m.name: m.value for m in RoomFunction} == expected


def test_severity_mirrors_review_severity_exactly():
    # Drift guard: checker Severity must stay byte-identical to the framework vocab.
    assert {s.name: s.value for s in Severity} == {
        s.name: s.value for s in ReviewSeverity
    }


def test_minimal_spatial_model_parses():
    model = SpatialModel(building_id="b1")
    assert model.building_id == "b1"
    assert model.rooms == []


def test_room_round_trips_with_function_enum():
    r = Room(id="r1", name="Спальня 1", level_id="L0",
             function=RoomFunction.ЖИЛАЯ, area_m2=12.0, height_mm=2700.0)
    assert r.function is RoomFunction.ЖИЛАЯ
    assert r.has_window is False


def test_room_is_frozen():
    r = Room(id="r1", name="x", level_id="L0",
             function=RoomFunction.ПРОЧЕЕ, area_m2=1.0, height_mm=2500.0)
    with pytest.raises(ValidationError):
        r.area_m2 = 2.0  # frozen → mutation rejected


def test_checkreport_passed_true_forbids_blocking():
    v = Violation(rule_id="HAB001", severity=Severity.BLOCKING, msg="x")
    with pytest.raises(ValidationError):
        CheckReport(passed=True, blocking=[v])


def test_checkreport_passed_false_requires_blocking():
    with pytest.raises(ValidationError):
        CheckReport(passed=False)


def test_checkreport_happy_path():
    rep = CheckReport(passed=True)
    assert rep.passed is True and rep.blocking == []
