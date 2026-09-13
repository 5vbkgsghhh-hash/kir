"""ФОКУС ЛИСТА НАЗЫВАЕТ РОВНО ТО, ЧТО ЛИСТ РИСУЕТ.

🔴 ЧЕМ КУПЛЕНО (13.09.2026, аудит окна V §3 п.3). `render_svg(focus=…)` гасит
до 0.16 всё, чего НЕТ в списке. Значит список и правило имени нарисованного
элемента обязаны совпадать — а живут они в разных функциях: `program_element_ids`
идёт по операциям, `build_program_preview` строит `DrawnElement`. Две величины,
обязанные совпадать, — именной дефект этого дерева, и здесь он особенно тих:
несовпавший адрес НЕ бросает исключения, он молча гасит лист целиком, и человек
читает это как «половина не нарисовалась».

ПОЧЕМУ СПИСОК ШИРЕ НАРИСОВАННОГО, И ЭТО ЗАКОННО. Операция, которую рисовать
нечем (нет правила, не разрешился уровень, `create_level` — не объект плана),
уходит в перепись, а её id всё равно назван. `focus` — БЕЛЫЙ СПИСОК: лишний
адрес не стоит ничего, пропущенный стоит человеку его предмета. Поэтому
утверждается ВКЛЮЧЕНИЕ нарисованного в список, а не равенство множеств.
"""
from __future__ import annotations

from kir.live.plan_stream import _focus_ids, _render_frame
from kir.preview import build_program_preview, program_element_ids


def _wall(oid: str, x: float) -> dict:
    return {"op": "create_wall", "id": oid,
            "level": {"by": "ref", "value": "L1"},
            "p0_mm": [x, 0.0, 0.0], "p1_mm": [x, 4000.0, 0.0],
            "height_mm": 3000.0}


LEVEL = {"op": "create_level", "id": "L1", "name": "Уровень 1", "elevation_mm": 0}


def _drawn_ids(ops: list[dict]) -> set[str]:
    building = build_program_preview(ops)
    out: set[str] = set()
    for plan in building.plans:
        out.update(e.element_id for e in plan.elements)
        out.update(d.element_id for d in plan.datums)
    return out


def test_every_drawn_element_is_named_by_the_cheap_walk():
    ops = [LEVEL, _wall("w1", 0.0), _wall("w2", 5000.0),
           {"op": "create_floor_by_contour", "id": "f1",
            "level": {"by": "ref", "value": "L1"},
            "boundary_mm": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]}]
    названные = set(program_element_ids(ops))
    нарисованные = _drawn_ids(ops)
    assert нарисованные, "контроль негоден: лист ничего не нарисовал"
    assert нарисованные <= названные, (
        "лист рисует адреса, которых фокус не назвал — они погаснут молча: "
        f"{sorted(нарисованные - названные)}")


def test_a_group_publishes_its_members_not_itself():
    """Правило `_members_out_of_groups` — общее у обоих, и это проверяется."""
    ops = [LEVEL, {"op": "create_group", "id": "g1",
                   "members": [_wall("w1", 0.0), _wall("w2", 5000.0)]}]
    названные = set(program_element_ids(ops))
    assert {"w1", "w2"} <= названные, названные
    нарисованные = _drawn_ids(ops)
    assert нарисованные <= названные, sorted(нарисованные - названные)


def test_the_sheet_dims_everything_outside_the_focus_and_nothing_else():
    """СМЫСЛ ФОКУСА — ЧИСЛОМ, НА НАСТОЯЩЕМ КАДРЕ.

    Контроль-пара внутри одного теста: тот же срез без `fresh` не гасит ни
    одного элемента, с `fresh` гасит ровно чужие.
    """
    чужое = [LEVEL] + [_wall(f"old{i}", i * 1000.0) for i in range(6)]
    свежее = [_wall("new1", 20000.0), _wall("new2", 25000.0)]
    ops = чужое + свежее

    без = _render_frame(ops, "Уровень 1")
    с = _render_frame(ops, "Уровень 1", свежее)

    assert без["svg"].count('data-context="1"') == 0, "кадр без фокуса что-то погасил"
    assert без["focus"] == []

    нарисовано = с["svg"].count("data-el=")
    погашено = с["svg"].count('data-context="1"')
    assert с["focus"] == ["new1", "new2"], с["focus"]
    assert погашено == нарисовано - len(с["focus"]), (
        f"погашено {погашено} из {нарисовано} при фокусе {с['focus']}")


def test_an_empty_program_never_dims_the_whole_sheet():
    """🔴 `focus=[]` погасило бы ВЕСЬ лист: «нечего подсветить» и «подсветить
    ничего» — разные факты, и второй отдаёт человеку серый лист."""
    ops = [LEVEL, _wall("w1", 0.0)]
    кадр = _render_frame(ops, "Уровень 1", [])
    assert кадр["svg"].count('data-context="1"') == 0
    assert кадр["focus"] == []
    assert _focus_ids([]) == ()


def test_a_focus_that_matches_nothing_on_the_sheet_dims_nothing():
    """🔴 СЕРЫЙ ЛИСТ ЗАПРЕЩЁН. Свежая программа может целиком уйти в перепись
    — тогда ни один её адрес на листе не встретится, и честное «гаси всё, чего
    нет в списке» отдало бы человеку серый лист вместо ответа."""
    ops = [LEVEL, _wall("w1", 0.0), _wall("w2", 5000.0)]
    кадр = _render_frame(ops, "Уровень 1", [{"op": "create_wall", "id": "нет-такого",
                                             "p0_mm": [0, 0, 0]}])
    assert кадр["svg"].count("data-el=") > 0, "контроль негоден: лист пуст"
    assert кадр["svg"].count('data-context="1"') == 0, (
        "фокус, не совпавший с листом ни одним адресом, погасил лист целиком")
    assert кадр["focus"] == [], "кадр обязан признать, что подсвечивать нечего"
