"""Дожо обязано быть библиотекой, а не скриптом, который «вроде работал».

`tools/design/kir_dojo.py` — предпосылка стенда §19.3: его `spar()`, `TASKS` и
`judge()` импортирует раннер. Скрипт прощает то, чего библиотека не прощает, и
28.07 ревью нашло ровно это: `spar()` звал `kir_coherence.check/flatten/gaps`,
которых в модуле нет (падение на ПЕРВОЙ же принятой программе), а цель пяти
простых задач (`min_ops`/`ops`) не читал никто — пустой прогон объявлялся
достигшим цели.

Ни один тест здесь не ходит в сеть: модель подменяется фейк-прокси через
monkeypatch `call_model`.

    venv/bin/pytest tests/design/test_kir_dojo.py -q
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tools.design import kir_dojo  # noqa: E402


# ── фейк-прокси ──────────────────────────────────────────────────────────────

#: Маленькая, но настоящая программа: компилятор её принимает, в ней есть плита
#: и стена — значит связности есть что считать.
SMALL_PROGRAM = {
    "ir_version": "1.0",
    "ops": [
        {"op": "create_floor_by_contour", "id": "f1",
         "level": {"by": "name", "value": "Этаж 1"},
         "type": {"by": "name", "value": "Монолит 200"},
         "contour": {"outer": {"shape": "poly",
                               "points_mm": [[0, 0], [12000, 0],
                                             [12000, 9000], [0, 9000]]}}},
        {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [12000, 0],
         "level": {"by": "name", "value": "Этаж 1"}, "height_mm": 3000,
         "type": {"by": "name", "value": "Кирпич 250"}},
    ],
}


def _tool_reply(program: dict) -> dict:
    return {"choices": [{"finish_reason": "tool_calls", "message": {
        "content": "",
        "tool_calls": [{"id": "call-1", "type": "function", "function": {
            "name": "revit_ir",
            "arguments": json.dumps({"program": program}, ensure_ascii=False)}}],
    }}]}


def _text_reply(text: str) -> dict:
    return {"choices": [{"finish_reason": "stop",
                         "message": {"content": text}}]}


def _scripted(monkeypatch, replies: list[dict]) -> list[list[dict]]:
    """Подменяет модель списком ответов; последний повторяется до конца бюджета.

    Возвращает журнал переданных `messages` — по нему видно, что именно ушло бы
    модели (в т.ч. текст отказа «готово»)."""
    seen: list[list[dict]] = []
    box = list(replies)

    def fake_call_model(messages, tools, *, timeout: int = 300) -> dict:
        seen.append([dict(m) for m in messages])
        return box.pop(0) if len(box) > 1 else box[0]

    monkeypatch.setattr(kir_dojo, "call_model", fake_call_model)
    return seen


# ── t1: spar() доходит до конца и несёт связность ────────────────────────────

def test_spar_reaches_a_terminal_record_with_coherence(monkeypatch):
    """Первый же принятый вызов шёл в `kir_coherence.check(...)`, которого нет.

    Падало AttributeError прямо в раунде — то есть НИ ОДИН прогон дожо не мог
    дойти до записи. Терминальный результат обязан существовать, и в нём обязана
    быть связность: на неё смотрит и фидбек модели, и итоговый `reached_goal`.
    """
    _scripted(monkeypatch, [_tool_reply(SMALL_PROGRAM),
                            _text_reply("ГОТОВО — 2 элемента")])
    rec = kir_dojo.spar(kir_dojo.TASKS["house"], max_rounds=2,
                        verbose=False, look=False)

    assert rec["accepted"] == 1, rec
    assert rec["elements"] == 2
    assert isinstance(rec.get("coherence"), dict) and rec["coherence"], \
        "запись прогона обязана нести отчёт связности"
    assert "колонн_вне_плиты" in rec["coherence"]
    assert isinstance(rec.get("gaps"), list)
    assert isinstance(rec.get("reached_goal"), bool)
    assert rec["committed"] == [SMALL_PROGRAM]


def test_spar_never_calls_the_network(monkeypatch):
    """Страховка самого теста: если фейк-прокси перестанет ловить вызов, тест
    обязан упасть здесь, а не уйти в живую модель."""
    def boom(*a, **kw):
        raise AssertionError("дожо пошло в сеть")

    monkeypatch.setattr(kir_dojo.urllib.request, "urlopen", boom)
    _scripted(monkeypatch, [_text_reply("ГОТОВО")])
    kir_dojo.spar(kir_dojo.TASKS["house"], max_rounds=1,
                  verbose=False, look=False)


# ── t2: пустой прогон не достигает цели ──────────────────────────────────────

def test_empty_run_does_not_reach_a_simple_goal():
    """`min_ops`/`ops` не читал никто ⇒ дом «построен» нулём операций.

    Это худший вид зелени: гейт молчит именно там, где строить не начали."""
    ok, gaps = kir_dojo.composition_verdict(
        kir_dojo.composition([]), kir_dojo.TASKS["house"].goal)
    assert ok is False, "пустая модель не может закрыть цель дома"
    assert gaps, "и обязана сказать, чего не хватает"


@pytest.mark.parametrize("key", sorted(kir_dojo.TASKS))
def test_no_task_is_reachable_by_building_nothing(key):
    """Любая задача корпуса: ничего не построено — цель не достигнута."""
    ok, gaps = kir_dojo.composition_verdict(
        kir_dojo.composition([]), kir_dojo.TASKS[key].goal)
    assert ok is False and gaps, f"{key}: пустой прогон объявлен успехом"


def test_a_done_claim_on_an_empty_model_is_refused(monkeypatch):
    """Живьём: модель говорит «ГОТОВО», не вызвав инструмент ни разу."""
    _scripted(monkeypatch, [_text_reply("ГОТОВО — дом собран")])
    rec = kir_dojo.spar(kir_dojo.TASKS["house"], max_rounds=3,
                        verbose=False, look=False)

    assert rec["accepted"] == 0
    assert rec["said_done"] is False, "пустой прогон не смеет закончиться успехом"
    assert rec["rejected_done"] >= 1
    assert rec["reached_goal"] is False


# ── t3: закрытая схема цели ──────────────────────────────────────────────────

def test_a_typo_in_a_goal_key_is_refused_at_load():
    """`min_opz` вместо `min_ops` — цель, которую никто не проверяет.

    Ровно так пять задач и потеряли свой критерий: ключ есть, потребителя нет,
    и молчание неотличимо от успеха."""
    with pytest.raises(ValueError):
        kir_dojo.Task("bad", "prompt", {"min_opz": 5})


def test_every_key_of_every_shipped_goal_is_consumed():
    """Схема закрыта не «на будущее», а по всему корпусу прямо сейчас."""
    for key, task in kir_dojo.TASKS.items():
        assert task.goal, f"{key}: пустая цель"
        assert set(task.goal) <= set(kir_dojo.GOAL_KEYS), key


def test_goal_values_are_type_checked():
    """Закрытые имена без проверки типов ловят опечатку, но не мусор."""
    with pytest.raises(ValueError):
        kir_dojo.Task("bad", "p", {"min_ops": "сорок"})
    with pytest.raises(ValueError):
        kir_dojo.Task("bad", "p", {"ops": "create_beam"})
    with pytest.raises(ValueError):
        kir_dojo.Task("bad", "p", {"ops": ["не_операция"]})
    with pytest.raises(ValueError):
        kir_dojo.Task("bad", "p", {"min_per_discipline": {"ТХ": 10}})
    with pytest.raises(ValueError):
        kir_dojo.Task("bad", "p", {})


# ── что именно принуждают min_ops и ops ──────────────────────────────────────

def test_min_ops_is_a_floor_on_what_was_actually_created():
    """Порог по созданному, а не по числу строк программы: `create_group`
    материализует сотни элементов одной операцией, и гейт, считающий строки,
    бил бы по единственной идиоме, которой дожо само и учит."""
    goal = {"min_ops": 3, "ops": ["create_beam"]}
    one = [{"ops": [{"op": "create_beam"}]}]
    ok, gaps = kir_dojo.composition_verdict(kir_dojo.composition(one), goal)
    assert ok is False and gaps

    grouped = [{"ops": [{"op": "create_group", "members": [{"op": "create_beam"}],
                         "placements": [[0, 0, 0], [0, 0, 4000]]}]}]
    ok, _ = kir_dojo.composition_verdict(kir_dojo.composition(grouped), goal)
    assert ok is True, "группа из трёх балок обязана закрывать порог в три"


def test_required_ops_must_each_be_present():
    progs = [{"ops": [{"op": "create_wall"}] * 30}]
    ok, gaps = kir_dojo.composition_verdict(
        kir_dojo.composition(progs), kir_dojo.TASKS["house"].goal)
    assert ok is False
    assert any("create_floor" in g for g in gaps), gaps


def test_dominance_gate_only_applies_to_multi_discipline_briefs():
    """Для башни из одних балок доля 100% — это ЗАДАНИЕ, а не Гудхарт.

    Гейт доминирования осмыслен там, где бриф требует несколько разделов; на
    eiffel/dome он был невыполним в принципе и просто запрещал успех."""
    beams = [{"ops": [{"op": "create_beam"}] * 60}]
    ok, gaps = kir_dojo.composition_verdict(
        kir_dojo.composition(beams), kir_dojo.TASKS["eiffel"].goal)
    assert ok is True, gaps

    ok, gaps = kir_dojo.composition_verdict(
        kir_dojo.composition(beams), kir_dojo.TASKS["skyscraper"].goal)
    assert ok is False
    assert any("всей модели" in g for g in gaps), gaps


# ── judge(): поле CompileOutput ──────────────────────────────────────────────

def test_judge_measures_the_emitted_code_not_a_field_that_does_not_exist():
    """`CompileOutput` несёт `csharp`; `out.code` не существует, и `getattr` с
    умолчанием превращал каждую принятую программу в «0 символов C#»."""
    from kukai.ir.compiler import CompileOutput

    assert not hasattr(CompileOutput(ok=True), "code")
    res = kir_dojo.judge(SMALL_PROGRAM, kir_dojo.ground_snapshot())
    assert res["ok"] is True, res
    assert res["cs_chars"] > 0, "эмиссия измеряется, а не обнуляется"


def test_judge_reports_refusals_as_data():
    res = kir_dojo.judge({"ops": []}, kir_dojo.ground_snapshot())
    assert res["ok"] is False
    assert res["diagnostics"] and res["diagnostics"][0].get("code")


# ── kir_coherence: публичный API, которого ждёт дожо ─────────────────────────

def test_kir_coherence_exports_the_api_the_dojo_calls():
    from tools.design import kir_coherence

    for name in ("flatten", "check", "gaps", "full_check"):
        assert callable(getattr(kir_coherence, name, None)), name

    elems = kir_coherence.flatten([SMALL_PROGRAM])
    assert elems
    rep = kir_coherence.check(elems)
    assert isinstance(rep, dict) and "стен_вне_плиты" in rep
    assert isinstance(kir_coherence.gaps(rep), list)


def test_kir_coherence_is_the_same_object_as_the_package():
    """Обёртка обязана быть тонкой: две копии проверки разъедутся."""
    from kukai.design import coherence
    from tools.design import kir_coherence

    assert kir_coherence.flatten is coherence.flatten
    assert kir_coherence.check is coherence.check
    assert kir_coherence.gaps is coherence.gaps


def test_coherence_gaps_reach_the_model_and_block_done(monkeypatch):
    """Стена без перекрытия в брифе, который перекрытие ТРЕБУЕТ: связность
    обязана и попасть в фидбек, и не дать закрыть задачу."""
    lonely = {"ir_version": "1.0", "ops": [
        {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": {"by": "name", "value": "Этаж 1"}, "height_mm": 3000,
         "type": {"by": "name", "value": "Кирпич 250"}}]}
    _scripted(monkeypatch, [_tool_reply(lonely)])
    rec = kir_dojo.spar(kir_dojo.TASKS["house"], max_rounds=1,
                        verbose=False, look=False)

    assert rec["accepted"] == 1, rec
    assert rec["reached_goal"] is False
    assert any("вне перекрытия" in g for g in rec["gaps"]), rec["gaps"]
    tool_msgs = [t for t in rec["transcript"] if t.get("result", {}).get("status")]
    assert tool_msgs and tool_msgs[0]["result"]["чего_не_хватает"], tool_msgs


# ── связность меряет бриф, а не разницу между проверкой и заданием ───────────

def _beams(n: int) -> list[dict]:
    return [{"op": "create_beam", "id": f"b{i}",
             "p0_mm": [i * 1000, 0, 0], "p1_mm": [i * 1000 + 1000, 0, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "Балка 200x400"}} for i in range(n)]


def _grid(cols: int, rows: int) -> list[dict]:
    return [{"op": "create_column", "id": f"c{i}_{j}", "xy": [i * 6000, j * 6000],
             "level": {"by": "name", "value": "Этаж 1"},
             "symbol": {"by": "name", "value": "К 300x300"}}
            for i in range(cols) for j in range(rows)]


@pytest.mark.parametrize("key", ["eiffel", "dome"])
def test_a_lattice_of_beams_is_allowed_to_have_no_columns(key):
    """У Эйфелевой башни колонн нет и не будет: «100% балок не доходят ни до
    одной колонны» — это проверка, вышедшая за задание, а не дефект модели.

    Такой замер не измеряет ничего и просто сжигает бюджет раундов — ровно тот
    разбор, по которому сняли и гейт доминирования."""
    progs = [{"ops": _beams(60)}]
    rep = kir_coherence_of(progs)
    binding, noted = kir_dojo.binding_coherence(rep, kir_dojo.TASKS[key].goal)
    assert binding == [], binding
    assert noted, "факт обязан остаться замеренным, даже когда он не запрещает"

    ok, gaps = kir_dojo.composition_verdict(
        kir_dojo.composition(progs), kir_dojo.TASKS[key].goal)
    assert (ok and not binding) is True, gaps


def test_beams_must_still_reach_the_columns_the_brief_asked_for():
    """Обратная сторона: раз бриф каркаса требует колонны, «балка ни до чего не
    доходит» снова становится запретом."""
    loose = [{"ops": _grid(8, 5) + [
        {"op": "create_beam", "id": f"x{i}",
         "p0_mm": [i * 1000 + 3000, 3000, 0], "p1_mm": [i * 1000 + 3500, 3000, 0],
         "level": {"by": "name", "value": "Этаж 1"},
         "symbol": {"by": "name", "value": "Балка 200x400"}} for i in range(40)]}]
    binding, _ = kir_dojo.binding_coherence(
        kir_coherence_of(loose), kir_dojo.TASKS["frame"].goal)
    assert any("не доходят" in g for g in binding), binding


def test_the_big_briefs_keep_every_coherence_gate():
    """Небоскрёб просит и плиты, и колонны — сужать там нечего, и колонна вне
    плиты обязана запрещать: ровно этот дефект (404 колонны) связность и
    ловит."""
    off = [{"ops": [
        {"op": "create_floor_by_contour", "id": "s",
         "level": {"by": "name", "value": "Этаж 1"},
         "type": {"by": "name", "value": "Монолит 200"},
         "contour": {"outer": {"shape": "poly",
                               "points_mm": [[0, 0], [1000, 0],
                                             [1000, 1000], [0, 1000]]}}},
        {"op": "create_column", "id": "c", "xy": [50000, 50000],
         "level": {"by": "name", "value": "Этаж 1"},
         "symbol": {"by": "name", "value": "К 300x300"}}]}]
    for key in ("skyscraper", "moscowcity"):
        binding, _ = kir_dojo.binding_coherence(
            kir_coherence_of(off), kir_dojo.TASKS[key].goal)
        assert any("вне плиты" in g or "вне перекрытия" in g for g in binding), key


def test_every_task_is_reachable_by_a_plausible_build():
    """Встречное требование к гейту: цель, которой нельзя достичь, меряет не
    модель, а сам гейт. Пять из семи задач были недостижимы В ПРИНЦИПЕ, и
    заметить это можно было только так — построив то, что просит бриф."""
    frame_like = [{"ops": _grid(8, 5) + [
        {"op": "create_beam", "id": f"bb{i}_{j}",
         "p0_mm": [i * 6000, j * 6000, 0], "p1_mm": [(i + 1) * 6000, j * 6000, 0],
         "level": {"by": "name", "value": "Этаж 1"},
         "symbol": {"by": "name", "value": "Балка 200x400"}}
        for i in range(7) for j in range(5)]}]
    for key in ("eiffel", "dome"):
        progs = [{"ops": _beams(60)}]
        ok, gaps = kir_dojo.composition_verdict(
            kir_dojo.composition(progs), kir_dojo.TASKS[key].goal)
        binding, _ = kir_dojo.binding_coherence(
            kir_coherence_of(progs), kir_dojo.TASKS[key].goal)
        assert ok and not binding, (key, gaps, binding)
    for key in ("frame", "spiral"):
        ok, gaps = kir_dojo.composition_verdict(
            kir_dojo.composition(frame_like), kir_dojo.TASKS[key].goal)
        binding, _ = kir_dojo.binding_coherence(
            kir_coherence_of(frame_like), kir_dojo.TASKS[key].goal)
        assert ok and not binding, (key, gaps, binding)


def test_the_record_keeps_the_whole_report_even_when_it_does_not_forbid(monkeypatch):
    """Сузили право закрыть задачу — не замер. Отчёт связности остаётся в записи
    целиком, а незапрещающие факты названы отдельно."""
    _scripted(monkeypatch, [_tool_reply(
        {"ir_version": "1.0", "ops": _beams(20)})])
    rec = kir_dojo.spar(kir_dojo.TASKS["eiffel"], max_rounds=1,
                        verbose=False, look=False)

    assert rec["accepted"] == 1, rec
    assert rec["coherence"]["балок_без_опоры"] == 20
    assert any("не доходят" in g for g in rec["coherence_notes"]), rec
    assert not any("не доходят" in g for g in rec["gaps"]), rec["gaps"]


def kir_coherence_of(programs: list[dict]) -> dict:
    from tools.design import kir_coherence

    return kir_coherence.check(kir_coherence.flatten(programs))


# ── состав обязан видеть то же здание, что и связность ───────────────────────

#: Три этажа, на каждом стена и плита — ШЕСТЬ элементов, сказанных ОДНОЙ
#: операцией. Компилятор такую программу принимает (это первый assert ниже),
#: связность её раскрывает и видит этажи, а состав до 28.07 читал сырой
#: `program["ops"]`, находил там один оп по имени `stack` и считал ноль.
STACK_PROGRAM = {
    "ir_version": "1.0",
    "ops": [
        {"op": "stack", "id": "t", "levels": 3, "h_mm": 3300,
         "name_prefix": "Этаж", "floor": [
             {"op": "create_wall", "id": "w", "p0_mm": [0, 0],
              "p1_mm": [12000, 0], "height_mm": 3300,
              "type": {"by": "name", "value": "Кирпич 250"}},
             {"op": "create_floor", "id": "s",
              "outline": [[0, 0], [12000, 0], [12000, 9000], [0, 9000]],
              "type": {"by": "name", "value": "Монолит 200"}},
         ]},
    ],
}


def test_composition_sees_a_building_written_with_a_macro():
    """Два счётчика одного прогона расходились на ЦЕЛОЕ здание.

    `stack`/`grid_array` — не сахар, а главная форма выразительности KIR: одна
    строка говорит шестьдесят этажей. Состав считал написанные строки и объявлял
    такое здание нулём, тогда как связность макрос раскрывала и видела этажи. На
    ринге это смертельно: цель меряется составом — значит KIR-рука наказывалась
    ровно за свой лучший приём и училась писать здание построчно.
    """
    assert kir_dojo.judge(STACK_PROGRAM, kir_dojo.ground_snapshot())["ok"] is True

    comp = kir_dojo.composition([STACK_PROGRAM])
    assert comp["total"] == 6, comp
    assert comp["by_op"].get("create_wall") == 3, comp
    assert comp["by_op"].get("create_floor") == 3, comp
    assert comp["by_discipline"] == {"КР": 3, "АР": 3}, comp
    assert kir_dojo.elements_in(STACK_PROGRAM) == 6

    # Раскрытие — в одном месте, и в нём видно ровно то же, что видит
    # связность: уровни макрос заводит сам.
    names = [o.get("op") for o in kir_dojo._expanded_ops(STACK_PROGRAM)]
    assert names.count("create_level") == 3, names
    assert names.count("create_wall") == 3 and names.count("create_floor") == 3


def test_a_macro_program_is_not_punished_by_the_goal():
    """Обратная сторона: раз состав раскрывает — порог закрывается макросом так
    же, как построчной программой. Иначе гейт учит худшему из двух способов."""
    goal = {"min_ops": 6, "ops": ["create_wall", "create_floor"]}
    ok, gaps = kir_dojo.composition_verdict(
        kir_dojo.composition([STACK_PROGRAM]), goal)
    assert ok is True, gaps


def test_a_run_reports_both_written_and_expanded_ops(monkeypatch):
    """Способность «сказать много малым» обязана быть видна ЧИСЛОМ.

    Одно число вместо двух её растворяет: `ops=1` не отличить от пустой
    программы, `ops=30` — от тридцати написанных строк. Запись прогона несёт
    оба, и в ответе инструмента модель видит оба тоже.
    """
    ten = json.loads(json.dumps(STACK_PROGRAM))
    ten["ops"][0]["levels"] = 10
    _scripted(monkeypatch, [_tool_reply(ten)])
    rec = kir_dojo.spar(kir_dojo.TASKS["house"], max_rounds=1,
                        verbose=False, look=False)

    assert rec["accepted"] == 1, rec
    assert rec["ops_written"] == 1, rec          # одна строка
    assert rec["ops_expanded"] == 30, rec        # 10 уровней + 10×2 опа
    assert rec["elements"] == 20, rec            # уровни — не элементы
    assert rec["composition"]["total"] == 20

    done = [t for t in rec["transcript"] if t.get("result", {}).get("status")]
    assert done and done[0]["ops_expanded"] == 30, done
    assert done[0]["result"]["ops_expanded"] == 30


def test_datums_are_not_building_elements():
    """`grid_array` раскрывается в ОСИ, `stack` — в УРОВНИ. И то и другое —
    базовые линии, а не состав здания. Считать их элементами значит открыть
    ровно ту дыру, которую состав и закрывает: набрать десять тысяч «элементов»
    самым дешёвым, что есть, и заодно размыть долю доминирующего типа."""
    grids = {"ir_version": "1.0", "ops": [
        {"op": "grid_array", "id": "g", "nx": 10, "ny": 10}]}
    comp = kir_dojo.composition([grids])
    assert comp["total"] == 0, comp
    assert len(kir_dojo._expanded_ops(grids)) == 20, "оси при этом раскрыты"


def test_a_macro_that_cannot_expand_costs_zero_and_not_the_run():
    """Программа, которую компилятор ПРИНЯЛ, уже раскрывалась успешно — сюда
    доходит только та, что до `judge()` не дошла. Она стоит нуля, а не падения
    всего прогона."""
    broken = {"ir_version": "1.0", "ops": [
        {"op": "stack", "id": "b", "levels": 0, "floor": [{"op": "create_wall"}]}]}
    assert kir_dojo.judge(broken, kir_dojo.ground_snapshot())["ok"] is False
    assert kir_dojo.composition([broken])["total"] == 0
    assert kir_dojo.elements_in(broken) == 0


def test_an_unexpected_expansion_error_is_not_swallowed(monkeypatch):
    """Молчать обязан ровно отказ макроса, и ничто больше: голый `except`
    превратил бы любой дефект раскрытия в тихий ноль — то есть в ту же самую
    находку, только уже необнаружимую."""
    from kukai.ir import macros

    def boom(ops):
        raise RuntimeError("дефект раскрытия")

    monkeypatch.setattr(macros, "expand", boom)
    with pytest.raises(RuntimeError):
        kir_dojo.composition([STACK_PROGRAM])


def test_elements_and_composition_can_never_disagree():
    """Один счёт, а не два похожих: `rec["elements"]` и `composition.total`
    считаются одним выражением, и разъехаться им негде."""
    grouped = {"ops": [{"op": "create_group",
                        "members": [{"op": "create_beam"},
                                    {"op": "create_column"}],
                        "placements": [[0, 0, 0], [0, 0, 4000]]}]}
    for prog in (STACK_PROGRAM, SMALL_PROGRAM, grouped):
        assert kir_dojo.elements_in(prog) == kir_dojo.composition([prog])["total"]


def test_a_correct_build_is_allowed_to_finish(monkeypatch):
    """Самое сильное утверждение о ринге: его МОЖНО пройти.

    Каркас собирается четырьмя программами (в одной не больше 20 опов — это
    отказ KIR-L001, а не совет), балки приходят в узлы сетки, и «ГОТОВО»
    принимается. Без этого теста любое ужесточение гейта выглядит зелёным:
    прогон, который не может закончиться успехом, ничего не меряет.
    """
    L = {"by": "name", "value": "Этаж 1"}
    cols = [{"op": "create_column", "id": f"c{i}_{j}", "xy": [i * 6000, j * 6000],
             "level": L, "symbol": {"by": "name", "value": "К 300x300"}}
            for i in range(8) for j in range(5)]
    beams = [{"op": "create_beam", "id": f"bb{i}_{j}",
              "p0_mm": [i * 6000, j * 6000, 0],
              "p1_mm": [(i + 1) * 6000, j * 6000, 0], "level": L,
              "symbol": {"by": "name", "value": "Балка 200x400"}}
             for i in range(7) for j in range(5)]
    chunks = [cols[:20], cols[20:], beams[:20], beams[20:]]
    _scripted(monkeypatch,
              [_tool_reply({"ir_version": "1.0", "ops": c}) for c in chunks]
              + [_text_reply("ГОТОВО — 75 элементов")])

    rec = kir_dojo.spar(kir_dojo.TASKS["frame"], max_rounds=6,
                        verbose=False, look=False)

    assert rec["refused"] == 0, rec["codes"]
    assert rec["accepted"] == 4
    assert rec["elements"] == 75
    assert rec["gaps"] == [], rec["gaps"]
    assert rec["reached_goal"] is True
    assert rec["said_done"] is True
    assert rec["rejected_done"] == 0
