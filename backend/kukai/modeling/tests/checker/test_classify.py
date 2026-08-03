"""RU function-lexicon tests (design §4)."""
import pytest

from kukai.modeling.checker.classify import classify_room
from kukai.modeling.checker.spatial_model import RoomFunction as RF


@pytest.mark.parametrize("name,expected", [
    ("Спальня 1", RF.ЖИЛАЯ),
    ("Гостиная", RF.ЖИЛАЯ),
    ("Кабинет", RF.ЖИЛАЯ),
    ("Кухня-гостиная", RF.КУХНЯ),
    ("Кухня", RF.КУХНЯ),
    ("Санузел", RF.САНУЗЕЛ),
    ("Ванная", RF.САНУЗЕЛ),
    ("С/у", RF.САНУЗЕЛ),
    ("Туалет", RF.САНУЗЕЛ),
    ("Коридор", RF.КОРИДОР),
    ("Прихожая", RF.ПРИХОЖАЯ),
    ("Лестничная клетка", RF.ЛЕСТНИЦА),
    ("Лифтовой холл", RF.ЛИФТ_ХОЛЛ),
    ("Входная группа", RF.ВХОДНАЯ_ГРУППА),
    ("Тех. помещение", RF.ТЕХ),
    ("Балкон", RF.ПРОЧЕЕ),          # unknown → fallback
])
def test_classify_room_by_name(name, expected):
    assert classify_room(name) is expected


def test_explicit_function_wins_over_name():
    # Generator stamped жилая even though the name reads like a corridor.
    assert classify_room("Коридор", explicit=RF.ЖИЛАЯ) is RF.ЖИЛАЯ


def test_explicit_accepts_raw_string():
    assert classify_room("anything", explicit="санузел") is RF.САНУЗЕЛ
