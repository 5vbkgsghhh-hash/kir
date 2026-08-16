"""Тесты вердикта о замысле (`kukai/ir/design_check.py`) и профиля стадии.

Проверяется не «функция что-то вернула», а ЧЕТЫРЕ свойства, ради которых модуль и
написан:

1. геометрическое чтение делает то, что обещает: планарное разбиение даёт полигон там,
   где стены замыкают, и ЧЕСТНО не даёт там, где не замыкают;
2. профиль стадии снимает ровно названное и ничего сверх — и без него любое здание с
   лестницей читалось бы NOT_EVALUATED;
3. названное умолчание не может стать несущим (инвариант `StageProfile`);
4. вердикт по программе НЕ ВЫДАЁТ СЕБЯ за вердикт по разбору, и расхождение двух путей
   объясняется входом, а не формулировкой.

Прогон: KUKAI_CHECKER_V2=1 pytest kukai/ir/tests/test_design_check.py -q
"""
from __future__ import annotations

import os
from typing import Any, Mapping

import pytest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kukai.ir.design_check import (  # noqa: E402
    DESIGN_STAGE,
    DESIGN_STAGE_THRESHOLDS,
    OUT_OF_SCOPE,
    UNATTRIBUTED,
    BuildWitness,
    DesignCheckUnavailable,
    ModelSource,
    check_design,
    design_stage_profile,
    compare,
    render_comparison,
    render_verdict,
    spatial_model_from_program,
)
from kukai.ir.decompile.l1_schema import stable_l1_id  # noqa: E402
from kukai.modeling.checker.spatial_model import (  # noqa: E402
    RoomFunction,
    Verdict,
)
from kukai.modeling.checker.thresholds import StageProfile, Thresholds  # noqa: E402


# --------------------------------------------------------------------- строители

def _op(op_name: str, source_id: str, params: dict, *, level_name=None,
        type_name: str = "") -> dict:
    return {
        "kind": "op", "op_name": op_name, "_id": stable_l1_id("op", source_id),
        "type_name": type_name, "params": params, "source_element_id": source_id,
        "level_name": level_name, "anchor_mm": None,
    }


def _level_ref(name: str, source_id: str) -> dict:
    return {"by": "name", "value": name, "_id": source_id}


def _wall(source_id: str, p0, p1, *, level=("L1", "L-1"), height_mm=3000.0) -> dict:
    return _op("create_wall", source_id, {
        "p0_mm": list(p0), "p1_mm": list(p1),
        "level": _level_ref(*level), "height_mm": height_mm,
    })


def _rect_walls(prefix: str, x0, y0, x1, y1, *, height_mm=3000.0) -> list[dict]:
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [
        _wall(f"{prefix}{i}", corners[i], corners[(i + 1) % 4], height_mm=height_mm)
        for i in range(4)
    ]


def _two_room_program() -> list[dict]:
    """Две смежные замкнутые комнаты, дверь между ними, наружная дверь и окно.

    Числа подобраны так, чтобы каждое утверждение теста читалось глазами:
    комната 8x5 м (40 м²) и 4x5 м (20 м²), высота стен 3000 мм.
    """
    nodes: list[dict] = [
        _op("create_level", "L-1", {"elev_mm": 0.0, "name": "L1"}),
        _op("create_level", "L-2", {"elev_mm": 3000.0, "name": "L2"}),
    ]
    # общий контур 12x5 с перегородкой на x=8000
    nodes += [
        _wall("w1", (0, 0), (12000, 0)),
        _wall("w2", (12000, 0), (12000, 5000)),
        _wall("w3", (12000, 5000), (0, 5000)),
        _wall("w4", (0, 5000), (0, 0)),
        _wall("w5", (8000, 0), (8000, 5000)),
    ]
    nodes += [
        _op("create_room", "r1", {"xy": [4000.0, 2500.0],
                                  "level": _level_ref("L1", "L-1"),
                                  "name": "Спальня"}),
        _op("create_room", "r2", {"xy": [10000.0, 2500.0],
                                  "level": _level_ref("L1", "L-1"),
                                  "name": "Кухня"}),
    ]
    wall5 = stable_l1_id("op", "w5")
    wall1 = stable_l1_id("op", "w1")
    nodes += [
        # межкомнатная дверь в перегородке
        _op("create_door", "d1", {"host": {"ref": wall5}, "offset_mm": 2500.0}),
        # наружная дверь в южной стене комнаты «Кухня»
        _op("create_door", "d2", {"host": {"ref": wall1}, "offset_mm": 10000.0}),
        # окно в южной стене комнаты «Спальня»
        _op("create_window", "win1", {"host": {"ref": wall1}, "offset_mm": 4000.0,
                                      "sill_mm": 800.0}),
    ]
    return nodes


# ------------------------------------------------- 1. геометрическое чтение

def test_planar_partition_finds_rooms_that_walls_actually_enclose():
    model, witness = spatial_model_from_program(
        _two_room_program(), building_id="t")
    assert witness.source is ModelSource.PROGRAM
    assert witness.rooms_measured == 2, witness.unmeasured_reasons
    by_name = {room.name: room for room in model.rooms}
    # 8x5 и 4x5 метра: площадь считана с полигона разбиения, а не объявлена
    assert by_name["Спальня"].area_m2 == pytest.approx(40.0, abs=0.05)
    assert by_name["Кухня"].area_m2 == pytest.approx(20.0, abs=0.05)
    assert by_name["Спальня"].function is RoomFunction.ЖИЛАЯ
    assert by_name["Кухня"].function is RoomFunction.КУХНЯ


def test_room_height_comes_from_the_walls_that_closed_it():
    model, _ = spatial_model_from_program(_two_room_program(), building_id="t")
    for room in model.rooms:
        assert room.height_mm == pytest.approx(3000.0)
        assert room.height_source == "wall_enclosure"


def test_unenclosed_room_goes_to_unmeasured_never_invented():
    """Комната вне стен — НЕ ошибка сборщика и НЕ выдумка: она уходит в неизмеримые."""
    nodes = _two_room_program()
    nodes.append(_op("create_room", "r3", {"xy": [50000.0, 50000.0],
                                           "level": _level_ref("L1", "L-1"),
                                           "name": "Спальня в чистом поле"}))
    model, witness = spatial_model_from_program(nodes, building_id="t")
    assert witness.rooms_total == 3
    assert witness.rooms_measured == 2
    assert witness.unmeasured_room_ids == ["r3"]
    assert witness.unmeasured_reasons["not_enclosed_by_walls"] == 1
    lonely = next(room for room in model.rooms if room.id == "r3")
    assert lonely.boundary == []          # контура нет
    assert lonely.height_mm is None       # и высоты нет — не 2700 из воздуха


def test_one_face_claimed_by_two_rooms_is_given_to_neither():
    """Разбиение не разделило две точки — выбрать одну значило бы угадать."""
    nodes = [
        _op("create_level", "L-1", {"elev_mm": 0.0, "name": "L1"}),
        *_rect_walls("w", 0, 0, 10000, 5000),
        _op("create_room", "r1", {"xy": [2000.0, 2500.0],
                                  "level": _level_ref("L1", "L-1"), "name": "Спальня"}),
        _op("create_room", "r2", {"xy": [8000.0, 2500.0],
                                  "level": _level_ref("L1", "L-1"), "name": "Кухня"}),
    ]
    model, witness = spatial_model_from_program(nodes, building_id="t")
    assert witness.rooms_measured == 0
    assert witness.unmeasured_reasons["shared_face"] == 2
    assert sorted(witness.shared_face_room_ids) == ["r1", "r2"]
    assert all(room.boundary == [] for room in model.rooms)


def test_door_position_is_read_from_host_and_offset_not_guessed():
    model, _ = spatial_model_from_program(_two_room_program(), building_id="t")
    doors = {door.id: door for door in model.doors}
    # w5 идёт из (8000,0) в (8000,5000); отступ 2500 -> ровно середина
    assert doors["d1"].location == pytest.approx((8000.0, 2500.0))
    # w1 идёт из (0,0) в (12000,0); отступ 10000
    assert doors["d2"].location == pytest.approx((10000.0, 0.0))
    # ширины проёма в программе нет — 0.0 означает «не выражено», а не «нулевая»
    assert doors["d1"].width_mm == 0.0


def test_door_adjacency_is_measured_not_declared():
    model, _ = spatial_model_from_program(_two_room_program(), building_id="t")
    inner = next(door for door in model.doors if door.id == "d1")
    assert {inner.from_room_id, inner.to_room_id} == {"r1", "r2"}
    # наружность НЕ объявляется сборщиком: её выводит derive.py по кольцу оболочки
    assert all(not door.is_exterior for door in model.doors)


# --------------------------------------------------- 2. профиль стадии

def test_without_a_profile_any_building_with_a_stair_is_not_evaluated():
    """Повод, ради которого профиль вообще заведён (engine.RULE_SPECS_V2:HAB011)."""
    nodes = _two_room_program()
    nodes.append(_op("create_stairs", "s1", {
        "p0_mm": [1000.0, 1000.0], "p1_mm": [3000.0, 1000.0],
        "base_level": _level_ref("L1", "L-1"),
        "top_level": _level_ref("L2", "L-2"),
    }))
    model, witness = spatial_model_from_program(nodes, building_id="t", profile=None)
    plain = check_design(model, witness, thresholds=Thresholds())
    assert "HAB011" in plain.report.coverage.mandatory_not_evaluated
    assert plain.verdict is not Verdict.PASS

    staged = check_design(model, witness, thresholds=DESIGN_STAGE_THRESHOLDS)
    assert "HAB011" not in staged.report.coverage.mandatory_not_evaluated


def test_suspended_rule_does_not_run_and_says_who_suspended_it():
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    verdict = check_design(model, witness)
    rows = {o.rule_id: o for o in verdict.report.coverage.outcomes}
    for rule_id in DESIGN_STAGE.suspended:
        assert rows[rule_id].status.value == "not_evaluated"
        assert DESIGN_STAGE.name in rows[rule_id].reason
        assert DESIGN_STAGE.suspension_reason(rule_id) in rows[rule_id].reason
    # и ни одна находка снятого правила не просочилась в отчёт
    fired = {v.rule_id for v in (verdict.report.blocking + verdict.report.warnings
                                 + verdict.report.info)}
    assert not (fired & set(DESIGN_STAGE.suspended))


def test_profile_changes_nothing_it_did_not_name():
    """Профиль — это состав правил, а не скидка: остальные правила идут как шли."""
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    staged = check_design(model, witness, thresholds=DESIGN_STAGE_THRESHOLDS)
    plain = check_design(model, witness, thresholds=Thresholds())
    staged_rows = {o.rule_id: o for o in staged.report.coverage.outcomes}
    plain_rows = {o.rule_id: o for o in plain.report.coverage.outcomes}
    touched = set(DESIGN_STAGE.suspended) | set(DESIGN_STAGE.mandatory)
    for rule_id in plain_rows:
        if rule_id in touched:
            continue
        assert staged_rows[rule_id].status is plain_rows[rule_id].status, rule_id
        assert staged_rows[rule_id].n_subjects == plain_rows[rule_id].n_subjects
    # числовые допуски профиль не трогает вовсе
    assert DESIGN_STAGE_THRESHOLDS.model_dump(
        exclude={"profile"}) == Thresholds().model_dump(exclude={"profile"})


def test_profile_name_reaches_the_report_and_the_verdict_text():
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    verdict = check_design(model, witness)
    assert verdict.report.coverage.profile_name == DESIGN_STAGE.name
    text = render_verdict(verdict)
    assert DESIGN_STAGE.name in text
    assert "применимо" in text and "правил из" in text


def test_named_nominal_cannot_become_load_bearing():
    """Инвариант `StageProfile`: номинал живёт, только пока снято всё, что его сравнит."""
    with pytest.raises(ValueError) as excinfo:
        StageProfile(name="кривой", nominal_opening_area_m2=1.0)
    assert "HAB031" in str(excinfo.value)
    # а объявленный по правилам — живёт
    ok = StageProfile(name="ровный", suspended={"HAB031": "нет площади"},
                      nominal_opening_area_m2=1.0)
    assert ok.nominal_opening_area_m2 == 1.0
    assert DESIGN_STAGE.nominal_opening_area_m2 is not None
    assert "HAB031" in DESIGN_STAGE.suspended


def test_window_presence_survives_the_unmeasurable_opening_size():
    """Окно без габарита всё ещё окно: HAB030 отвечает на «есть ли проём»."""
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    assert witness.nominal_opening_area_m2 == DESIGN_STAGE.nominal_opening_area_m2
    assert witness.opening_size_measured is False
    verdict = check_design(model, witness)
    # у «Спальни» окно есть -> HAB030 о ней молчит; у «Кухни» окна нет -> говорит
    fired = {ref for v in verdict.report.blocking + verdict.report.warnings
             if v.rule_id == "HAB030" for ref in v.refs}
    assert "r1" not in fired
    assert "r2" in fired


def test_missing_window_is_the_headline_finding():
    """«Квартира без окна» — то, ради чего затевалось. Убираем окно — правило говорит."""
    nodes = [node for node in _two_room_program()
             if node.get("op_name") != "create_window"]
    model, witness = spatial_model_from_program(nodes, building_id="t")
    verdict = check_design(model, witness)
    blocking = [v for v in verdict.report.blocking if v.rule_id == "HAB030"]
    assert blocking, "жилая комната без окна обязана быть BLOCKING"
    assert "r1" in {ref for v in blocking for ref in v.refs}
    assert verdict.verdict is Verdict.FAIL


def _low_storey_program() -> list[dict]:
    """Тот же дом, но этаж 2400 мм и стены 2100 — настоящий низкий этаж.

    Шаг этажа опускается ВМЕСТЕ со стенами намеренно: ограждение считается потолком
    только когда доходит до следующего уровня, и 2100-мм стены под уровнем 3000 —
    это балюстрада, а не низкий потолок (см. `_height_from_enclosure`).
    """
    nodes = []
    for node in _two_room_program():
        if node.get("op_name") == "create_level" and node["params"]["name"] == "L2":
            node = _op("create_level", "L-2", {"elev_mm": 2400.0, "name": "L2"})
        elif node.get("op_name") == "create_wall":
            node = _wall(node["source_element_id"], node["params"]["p0_mm"],
                         node["params"]["p1_mm"], height_mm=2100.0)
        nodes.append(node)
    return nodes


def test_low_ceiling_is_a_finding_and_it_comes_from_the_walls():
    model, witness = spatial_model_from_program(_low_storey_program(),
                                                building_id="t")
    verdict = check_design(model, witness)
    blocking = [v for v in verdict.report.blocking if v.rule_id == "HAB022"]
    assert blocking, "2100 мм ниже жёсткого порога 2200 — обязано быть BLOCKING"
    assert all(room.height_mm == pytest.approx(2100.0) for room in model.rooms)


def test_a_balustrade_is_not_a_ceiling():
    """Замер K2: холл «ЛК 2.1 1» замкнут стенами 1530 мм при собственной высоте 3830.

    Ограждение вокруг проёма лестницы — не потолок, и высота, снятая с него, породила
    бы обвинение, порождённое допущением сборщика, а не зданием.
    """
    nodes = [node if node.get("op_name") != "create_wall"
             else _wall(node["source_element_id"], node["params"]["p0_mm"],
                        node["params"]["p1_mm"], height_mm=1530.0)
             for node in _two_room_program()]      # уровень выше остаётся на 3000
    model, witness = spatial_model_from_program(nodes, building_id="t")
    assert all(room.height_mm is None for room in model.rooms), \
        "ограждение, не доходящее до перекрытия, не определяет высоту помещения"
    verdict = check_design(model, witness)
    assert not [v for v in verdict.report.blocking if v.rule_id == "HAB022"]
    row = {o.rule_id: o for o in verdict.report.coverage.outcomes}["HAB022"]
    assert row.status.value == "not_evaluated"


# ------------------------------------------------- 3. честность источника

def test_v1_path_is_refused_never_silently_downgraded(monkeypatch):
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    monkeypatch.setenv("KUKAI_CHECKER_V2", "0")
    with pytest.raises(DesignCheckUnavailable):
        check_design(model, witness)


def test_source_is_visible_in_the_artifact_not_implied():
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    text = render_verdict(check_design(model, witness))
    assert "САМОПРОВЕРКА" in text
    assert "ЗАЯВЛЕННОЕ" in text
    parse_witness = BuildWitness(source=ModelSource.PARSE, building_id="t")
    assert "НЕЗАВИСИМОЕ ЧТЕНИЕ" in parse_witness.source.evidence


def test_out_of_scope_is_named_in_every_verdict():
    """Компонент, который не берётся предсказывать Revit, обязан сказать это вслух."""
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    text = render_verdict(check_design(model, witness))
    assert len(OUT_OF_SCOPE) == 5
    for item in OUT_OF_SCOPE:
        assert item.name in text
        assert item.measured, "поведение вне области обязано нести замер"


# ----------------------------------------------------------- 4. ворота

def test_identical_models_diverge_in_nothing():
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    verdict = check_design(model, witness)
    assert compare(verdict, verdict) == []
    assert "РАСХОЖДЕНИЙ НЕТ" in render_comparison(verdict, verdict, [])


def test_every_divergence_carries_a_derived_cause_or_says_it_does_not():
    """Догадок не принимаем: причина либо выведена из входов, либо названа НЕ УСТАНОВЛЕННОЙ."""
    full = _two_room_program()
    stripped = [node for node in full if node.get("op_name") != "create_window"]
    a = check_design(*spatial_model_from_program(full, building_id="t"))
    b = check_design(*spatial_model_from_program(stripped, building_id="t"))
    divergences = compare(a, b)
    assert divergences, "снятое окно обязано быть видно в воротах"
    assert {d.subject for d in divergences} >= {"windows", "HAB030/blocking"}
    for item in divergences:
        assert item.cause, item
    # Здесь окно СНЯТО ИЗ ПРОГРАММЫ руками: ни лифт, ни сборщик его не терял, и
    # честный ответ — «причина не установлена». Именно это свойство и проверяется:
    # модуль обязан молчать там, где не знает, а не подобрать правдоподобное.
    window_row = next(d for d in divergences if d.subject == "windows")
    assert window_row.cause == UNATTRIBUTED
    # А вот следствие — расхождение ПРАВИЛА — обязано быть привязано ко входу.
    rule_row = next(d for d in divergences if d.subject == "HAB030/blocking")
    assert rule_row.cause != UNATTRIBUTED
    text = render_comparison(a, b, divergences)
    assert "причина:" in text


def test_rule_divergence_is_attributed_to_the_input_the_rule_reads():
    full = _two_room_program()
    stripped = [node for node in full if node.get("op_name") != "create_window"]
    a = check_design(*spatial_model_from_program(full, building_id="t"))
    b = check_design(*spatial_model_from_program(stripped, building_id="t"))
    row = next(d for d in compare(a, b) if d.subject == "HAB030/blocking")
    # HAB030 читает окна — именно они и обязаны стоять в причине
    assert "окон" in row.cause


# ═══════════ 5. ПРАВИЛО НЕ СМЕЕТ СРАБАТЫВАТЬ НА ВХОДЕ, КОТОРОГО У НЕГО НЕТ ═══════

def _program_with_one_unenclosed_room() -> list[Mapping[str, Any]]:
    nodes = _two_room_program()
    nodes.append(_op("create_room", "r3", {"xy": [50000.0, 50000.0],
                                           "level": _level_ref("L1", "L-1"),
                                           "name": "Спальня в чистом поле"}))
    return nodes


def test_unmeasurable_room_is_withheld_from_the_area_rule_not_accused():
    """Ноль вместо неизвестности — ложь. Замер K2: 732 обвинения «площадь 0»."""
    model, witness = spatial_model_from_program(
        _program_with_one_unenclosed_room(), building_id="t")
    lonely = next(room for room in model.rooms if room.id == "r3")
    assert lonely.area_m2 == 0.0        # сказать «неизвестно» контракт не умеет
    assert lonely.function is RoomFunction.ЖИЛАЯ   # и порог у неё есть

    verdict = check_design(model, witness)
    accused = {ref for v in verdict.report.blocking if v.rule_id == "HAB020"
               for ref in v.refs}
    assert "r3" not in accused, "правило обвинило помещение, площади которого не знает"
    row = {o.rule_id: o for o in verdict.report.coverage.outcomes}["HAB020"]
    assert row.excluded_subjects == 1
    assert "room_polygon" in row.excluded_reason
    # и то же самое видно в тексте, а не только в структуре
    assert "не оценено HAB020 на 1 субъектах" in render_verdict(verdict)


def test_the_same_law_covers_width_height_daylight_and_door_sides():
    model, witness = spatial_model_from_program(
        _program_with_one_unenclosed_room(), building_id="t")
    verdict = check_design(model, witness)
    rows = {o.rule_id: o for o in verdict.report.coverage.outcomes}
    for rule_id in ("HAB020", "HAB021", "HAB022", "HAB030", "HAB040"):
        assert rows[rule_id].excluded_subjects >= 1, rule_id
    # HAB060..063 — СВИДЕТЕЛИ, а не обвинители: их дело как раз назвать помещение,
    # границу которого проверить нечем. Все остальные правила о нём молчат.
    accused = {(v.rule_id, ref)
               for bucket in (verdict.report.blocking, verdict.report.warnings)
               for v in bucket for ref in v.refs
               if not v.rule_id.startswith("HAB06")}
    assert not [pair for pair in accused if pair[1] == "r3"], accused
    witnessed = {v.rule_id for v in verdict.report.warnings
                 if "r3" in v.refs and v.rule_id.startswith("HAB06")}
    assert witnessed == {"HAB060"}, "неизмеримое помещение обязано быть НАЗВАНО"


def test_apartment_oracle_rules_are_suspended_with_the_measurement_named():
    """Замер точности оракула — часть причины, а не сноска к ней.

    🔴 HAB002 ВЫШЕЛ ИЗ ЭТОГО СПИСКА 15.08.2026, и это не смягчение, а второй замер.
    На эталоне генератора, где истина известна по построению, `derive_apartments`
    даёт 20 квартир из 20 с ТОЧНЫМ составом: «0%» есть свойство ВХОДА, а не
    алгоритма. HAB002 переехал на предусловия (`_DESIGN_PRECONDITIONS`), которые
    отделяют вход, на котором оракулу верить можно, от входа, на котором нельзя;
    основание и оба контроля — `test_apartment_oracle_precondition.py`.
    Остальные три стоят каждое на СВОЁМ входе, и этим замером они НЕ покрыты.
    """
    _, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    profile = design_stage_profile(witness)
    for rule_id in ("HAB003", "HAB004", "HAB042"):
        reason = profile.suspension_reason(rule_id)
        assert reason, rule_id
        assert "0%" in reason and "469" in reason, "причина обязана нести замер"
    assert not profile.suspension_reason("HAB002"), (
        "HAB002 больше не снимается безусловно — он обязан стоять на предусловиях")


def test_curtain_wall_facade_suspends_the_daylight_rule_with_both_numbers():
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    assert "HAB030" not in design_stage_profile(witness).suspended

    witness.curtain_panels = 2602          # замер K2
    witness.counts["windows"] = 0
    profile = design_stage_profile(witness)
    reason = profile.suspension_reason("HAB030")
    assert "2602" in reason and "витраж" in reason.lower()
    verdict = check_design(model, witness,
                           thresholds=Thresholds(profile=profile))
    assert not [v for v in verdict.report.blocking if v.rule_id == "HAB030"]
    row = {o.rule_id: o for o in verdict.report.coverage.outcomes}["HAB030"]
    assert row.status.value == "not_evaluated"
    assert "2602" in row.reason


def test_missing_ground_level_stops_hab010_instead_of_accusing_every_level():
    """Замер: детсад — 4 обвинения из 4 занятых уровней, snowdon — 8 из 8."""
    from kukai.modeling.checker.engine import PRECONDITIONS

    nodes = [node for node in _two_room_program()
             if node.get("op_name") != "create_door"
             or node["source_element_id"] != "d2"]      # убираем наружную дверь
    nodes.append(_op("create_stairs", "s1", {
        "p0_mm": [1000.0, 1000.0], "p1_mm": [3000.0, 1000.0],
        "base_level": _level_ref("L1", "L-1"),
        "top_level": _level_ref("L2", "L-2"), "width_mm": 1200.0}))
    model, witness = spatial_model_from_program(nodes, building_id="t")
    verdict = check_design(model, witness)
    rows = {o.rule_id: o for o in verdict.report.coverage.outcomes}
    assert rows["HAB010"].status.value == "not_evaluated"
    assert "ground_level_known" in rows["HAB010"].reason
    assert not [v for v in verdict.report.blocking if v.rule_id == "HAB010"]
    assert "ground_level_known" in PRECONDITIONS
    # An active mandatory rule that cannot establish its precondition is unknown,
    # never satisfied. Before the regression fix this exact design returned PASS.
    assert verdict.report.coverage.mandatory_not_evaluated == ["HAB001", "HAB010"]
    assert verdict.verdict is Verdict.NOT_EVALUATED
    assert verdict.report.passed is False


def test_stair_landing_gap_stops_the_vertical_rules():
    nodes = _two_room_program()
    nodes.append(_op("create_stairs", "s1", {
        "p0_mm": [1000.0, 1000.0], "p1_mm": [3000.0, 1000.0],
        "base_level": _level_ref("L1", "L-1"),
        "top_level": _level_ref("L2", "L-2"), "width_mm": 1200.0}))
    model, witness = spatial_model_from_program(nodes, building_id="t")
    # ни одно помещение не названо лестничной клеткой -> рёбра вверх не построятся
    assert witness.rooms_stair == 0
    verdict = check_design(model, witness)
    rows = {o.rule_id: o for o in verdict.report.coverage.outcomes}
    for rule_id in ("HAB001", "HAB010"):
        assert rows[rule_id].status.value == "not_evaluated", rule_id
        assert "stair_landings_complete" in rows[rule_id].reason


def test_a_rule_may_be_suspended_or_filtered_but_never_both():
    with pytest.raises(ValueError) as excinfo:
        StageProfile(name="кривой", suspended={"HAB020": "нет"},
                     subject_inputs={"HAB020": "room_polygon"})
    assert "HAB020" in str(excinfo.value)


def test_the_filter_refuses_rules_that_reason_about_the_whole_graph():
    """Обрезать модель правилу о СВЯЗНОСТИ — значит изменить вопрос, а не охват."""
    from kukai.modeling.checker.engine import _ROOM_FILTERABLE

    assert not (_ROOM_FILTERABLE & {"HAB002", "HAB003", "HAB004", "HAB010", "HAB042"})
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    bad = Thresholds(profile=StageProfile(
        name="кривой", subject_inputs={"HAB010": "room_polygon"}))
    with pytest.raises(ValueError) as excinfo:
        check_design(model, witness, thresholds=bad)
    assert "HAB010" in str(excinfo.value)


def _tiny_l0_document():
    """Тот же дом, что и `_two_room_program`, но как РАЗБОР.

    Границы помещений заданы контурами (как их возвращает Revit), проёмы — точками с
    инстансными габаритами. Это тот случай, когда два пути ОБЯЗАНЫ сойтись: всё, чем
    они различаются на настоящем здании, здесь выражено обоими.
    """
    from kukai.ir.decompile.schema import L0Document

    def wall(eid, p0, p1):
        return {
            "element_id": eid, "category": "OST_Walls", "category_ru": "Стены",
            "type_id": "t", "type_name": "Стена 200", "level_id": "L-1",
            "level_name": "L1", "host_id": None, "geom_kind": "curve",
            "p0_mm": [p0[0], p0[1], 0.0], "p1_mm": [p1[0], p1[1], 0.0],
            "bbox_min_mm": None, "bbox_max_mm": None, "rotation_deg": None,
            "design_option": None, "phase_created": None, "workset": None,
            "params": {"WALL_USER_HEIGHT_PARAM": 3000.0},
        }

    def hosted(eid, category, xy, host, width, height):
        return {
            "element_id": eid, "category": category, "category_ru": category,
            "type_id": "t", "type_name": f"{category} 900", "level_id": "L-1",
            "level_name": "L1", "host_id": host, "geom_kind": "point",
            "p0_mm": [xy[0], xy[1], 0.0], "p1_mm": None,
            "bbox_min_mm": None, "bbox_max_mm": None, "rotation_deg": None,
            "design_option": None, "phase_created": None, "workset": None,
            "params": {"FAMILY_WIDTH_PARAM": width, "FAMILY_HEIGHT_PARAM": height},
        }

    def room_element(eid):
        return {
            "element_id": eid, "category": "OST_Rooms", "category_ru": "Помещения",
            "type_id": "", "type_name": "", "level_id": "L-1", "level_name": "L1",
            "host_id": None, "geom_kind": "bbox_only", "p0_mm": None, "p1_mm": None,
            "bbox_min_mm": [0.0, 0.0, 0.0], "bbox_max_mm": [12000.0, 5000.0, 3000.0],
            "rotation_deg": None, "design_option": None, "phase_created": None,
            "workset": None, "params": {},
        }

    return L0Document.from_dict({
        "doc_name": "tiny", "revit_version": "2023", "units": "mm",
        "change_stamp": "tiny-v1",
        "levels": [{"id": "L-1", "name": "L1", "elevation_mm": 0.0},
                   {"id": "L-2", "name": "L2", "elevation_mm": 3000.0}],
        "grids": [], "project_info": {},
        "rooms": [
            {"id": "r1", "name": "Спальня", "level_id": "L-1", "level_name": "L1",
             "area_m2": 40.0,
             "boundary_mm": [[0, 0], [8000, 0], [8000, 5000], [0, 5000]],
             "boundary_loops_mm": [[[0, 0], [8000, 0], [8000, 5000], [0, 5000]]],
             "bounding_element_ids": ["w1", "w4", "w3", "w5"]},
            {"id": "r2", "name": "Кухня", "level_id": "L-1", "level_name": "L1",
             "area_m2": 20.0,
             "boundary_mm": [[8000, 0], [12000, 0], [12000, 5000], [8000, 5000]],
             "boundary_loops_mm": [[[8000, 0], [12000, 0], [12000, 5000],
                                    [8000, 5000]]],
             "bounding_element_ids": ["w1", "w2", "w3", "w5"]},
        ],
        "elements": [
            wall("w1", (0, 0), (12000, 0)),
            wall("w2", (12000, 0), (12000, 5000)),
            wall("w3", (12000, 5000), (0, 5000)),
            wall("w4", (0, 5000), (0, 0)),
            wall("w5", (8000, 0), (8000, 5000)),
            room_element("r1"), room_element("r2"),
            hosted("d1", "OST_Doors", (8000, 2500), "w5", 900.0, 2100.0),
            hosted("d2", "OST_Doors", (10000, 0), "w1", 1000.0, 2100.0),
            hosted("win1", "OST_Windows", (4000, 0), "w1", 1200.0, 1400.0),
        ],
        "category_status": [], "links": [],
    })


def test_gate_two_paths_agree_when_both_can_express_the_building():
    """ВОРОТА, положительный случай: сходятся — путь от программы обоснован."""
    from kukai.ir.design_check import spatial_model_from_l0

    parse = check_design(*spatial_model_from_l0(_tiny_l0_document()))
    program = check_design(*spatial_model_from_program(
        _two_room_program(), building_id="tiny-v1"))
    assert parse.verdict is program.verdict
    divergences = compare(parse, program)
    subjects = {d.subject for d in divergences}
    # населения, входы «геометрия помещения» и все правила совпадают …
    assert not (subjects & {"rooms", "doors", "walls", "windows", "levels",
                            "rooms_measured", "rooms_with_height",
                            "HAB020", "HAB030", "HAB001", "HAB003"})
    # … и остаётся ровно то, что представления действительно выражают по-разному:
    # габарит проёма, который программа не несёт.
    assert subjects <= {"doors_with_width", "windows_with_size", "HAB041"}
    for item in divergences:
        assert item.cause != UNATTRIBUTED, item


def test_geometry_gate_is_per_element_and_splits_along_from_across():
    """Ворота сравнивают ЧИСЛА элементов, а не только их количество."""
    from kukai.ir.design_check import compare_geometry, spatial_model_from_l0

    model_a, _ = spatial_model_from_l0(_tiny_l0_document())
    model_b, _ = spatial_model_from_program(_two_room_program(),
                                            building_id="tiny-v1")
    rows = {row.subject: row for row in compare_geometry(model_a, model_b)}
    # ось стены читается обоими путями из одних чисел — строки о ней быть не должно
    assert "ось стены" not in rows
    # вдоль оси хозяина проём восстановлен ТОЧНО
    assert "совпало 2, макс 0.00 мм" in rows["положение двери — ВДОЛЬ оси хозяина"].program
    # поперёк расхождения нет: в этом стенде проёмы и так на оси
    assert "положение двери — ПОПЕРЁК оси хозяина" not in rows
    iou = rows["контур помещения (IoU)"]
    assert "IoU медиана 1.000" in iou.program


def test_parse_path_reads_the_room_boundary_revit_returned():
    from kukai.ir.design_check import spatial_model_from_l0

    model, witness = spatial_model_from_l0(_tiny_l0_document())
    assert witness.source is ModelSource.PARSE
    assert witness.rooms_measured == 2
    rooms = {room.name: room for room in model.rooms}
    assert rooms["Спальня"].area_m2 == pytest.approx(40.0)
    assert rooms["Спальня"].height_source == "room_bbox"
    # у разбора габарит проёма ЕСТЬ — и номинал профиля не используется вовсе
    assert witness.opening_size_measured is True
    assert witness.nominal_opening_area_m2 is None
    assert witness.inputs["windows_with_size"] == 1


def test_witness_counts_are_not_decoration():
    """Каждое число свидетеля обязано совпасть с содержимым модели."""
    model, witness = spatial_model_from_program(_two_room_program(), building_id="t")
    assert witness.counts["rooms"] == len(model.rooms)
    assert witness.counts["walls"] == len(model.walls)
    assert witness.counts["doors"] == len(model.doors)
    assert witness.inputs["rooms_measured"] == witness.rooms_measured
    assert witness.inputs["doors_with_width"] == 0
    assert witness.inputs["windows_with_size"] == 0
    assert witness.measured_ratio == pytest.approx(1.0)


# ---------------------------------- замкнутость БЕЗ комнат (15.08.2026)

def _walls_only(*, closed: bool) -> list[dict]:
    """Четыре стены и НИ ОДНОЙ комнаты. `closed=False` — дыра 1500 мм."""
    nodes = [_op("create_level", "L-1", {"elev_mm": 0.0, "name": "L1"})]
    nodes += _rect_walls("w", 0, 0, 6000, 4000)[:3]
    last = (0, 4000), ((0, 0) if closed else (0, 1500))
    nodes.append(_wall("w3", *last))
    return nodes


def test_enclosure_is_measured_where_walls_are_not_where_rooms_are():
    """ЗАМКНУТОСТЬ — ФАКТ О СТЕНАХ, И СЧИТАЕТСЯ ТАМ, ГДЕ ЕСТЬ СТЕНЫ.

    До 15.08.2026 разбиение строилось циклом по уровням, У КОТОРЫХ ЕСТЬ
    КОМНАТЫ. Программа из четырёх стен без единой комнаты давала
    `partition_faces == 0` независимо от того, замкнули стены контур или нет —
    то есть ровно в том случае, в котором сломалась «полосатая стена» (три
    стены, комнат нет), свидетель не нёс ни одного числа о сборке.

    Здесь обе стороны: замкнутая коробка даёт грань, разомкнутая не даёт.
    Второй случай — контроль-FAIL: без него тест был бы зелен и на приборе,
    который всегда отвечает «одна грань».
    """
    closed, _w = spatial_model_from_program(
        _walls_only(closed=True), building_id="закрытая")
    opened, _w2 = spatial_model_from_program(
        _walls_only(closed=False), building_id="открытая")
    del closed, opened

    _, w_closed = spatial_model_from_program(
        _walls_only(closed=True), building_id="закрытая")
    _, w_open = spatial_model_from_program(
        _walls_only(closed=False), building_id="открытая")

    assert w_closed.counts.get("walls") == 4
    assert w_open.counts.get("walls") == 4, "стены обязаны доехать в обоих случаях"
    assert w_closed.partition_faces == 1, "замкнутая коробка обязана дать грань"
    assert w_open.partition_faces == 0, "дыра 1500 мм не замыкает ничего"
    assert w_closed.rooms_total == 0 and w_open.rooms_total == 0


def test_walls_on_a_level_nobody_declared_are_named_upstream_not_here():
    """Стены на уровне, которого не объявил ни один `create_level`.

    Ноль граней здесь НЕ молчалив, и причина названа ВЫШЕ по потоку: такая
    стена не доходит до разбиения вовсе, её отбрасывает чтение с запиской
    `wall_level_unresolved`. Тест держит именно это — чтобы следующая правка
    не завела ВТОРОЕ имя тому же факту (первая редакция завела, и этот тест
    её поймал).
    """
    nodes = [_op("create_level", "L-1", {"elev_mm": 0.0, "name": "L1"})]
    nodes += [_wall("x1", (0, 0), (6000, 0), level=("L9", "L-9"))]
    _, witness = spatial_model_from_program(nodes, building_id="сирота")
    assert witness.partition_faces == 0
    assert witness.counts.get("walls", 0) == 0, "стена не доехала — и это верно"
    codes = {note.code for note in witness.notes}
    assert "wall_level_unresolved" in codes, codes
