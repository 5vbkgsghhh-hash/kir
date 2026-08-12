"""ВИТРИНА ВЫБОРА — выбор обязан быть не только СДЕЛАН, но и ПРЕДЪЯВЛЕН.

Опровергающий тест воспроизводит живой случай 10.08.2026 (модель оператора
`13A-RD-AR-K2_v33`, Revit 2023) дословно. Одна стена без `type`, ход зелёный
насквозь — `execution=committed`, `witness=satisfied`, `acceptance=accepted`, —
построенная стена получила тип «111_Кирпич 380», а квитанция вернула вот это:

    [{"op_id": "W1", "op": "create_wall", "param": "type",
      "rule": "doc_default", "chosen": {"id": null, "name": null}}]

Правило НАЗВАНО, а что выбрано — пусто, и `defaults_note_ru` промолчал вовсе.
Это ровно тот дефект, ради которого механизм написан: пустой выбор
НЕОТЛИЧИМ ОТ «выбор не сделан», то есть сообщает читателю (а главный читатель
здесь — модель) ложь о его собственной осведомлённости.

ПОЧЕМУ ПОЛЕ ПУСТО — ЭТО НЕ БАГ ЗАПОЛНЕНИЯ, А ФАКТ О СТАДИИ. Замер по коду:
`ground._resolve_one` для `create_wall.type` отдаёт `IN_EMIT_DEFAULT`, а имя
типа появляется только внутри эмиссии — `doc.GetDefaultElementTypeId(
ElementTypeGroup.WallType)` спрашивают у САМОГО ДОКУМЕНТА в момент исполнения
(`authoring.py:507`). На стадии заземления имени НЕ СУЩЕСТВУЕТ, и придумать
его было бы хуже, чем не назвать. Поэтому чинится не «пустое поле», а ЛОЖНАЯ
ФОРМА строки, и чинится в двух шагах:

* до исполнения строка честно говорит, что выбор ОТЛОЖЕН документу, и
  называет, где имя появится (`chosen.resolved_at` + `chosen.read_from`);
* после исполнения имя ДОЕЗЖАЕТ из квитанции построенного элемента
  (`ground.attach_runtime_choices`) — эмиттер тип применил, он же его и
  прочитал обратно, так что это ЗАМЕР, а не догадка.

Второй шаг нужен именно потому, что «сходи прочитай сам» снимает у модели
меньше неопределённости, чем названное имя: ответ у нас уже есть в том же
JSON, и не соединить его значило бы отдать модели нашу работу.
"""
from __future__ import annotations

import copy
import re

from kukai.ir.compiler import compile_program
from kukai.ir.ground import describe_choices_ru, IN_EMIT_DEFAULT
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

LV = {"by": "name", "value": "Этаж 1"}
SQ = [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]


def _snapshot(**pools) -> dict:
    snap = copy.deepcopy(GROUND_SNAPSHOT)
    snap.update(pools)
    return snap


def _compile(ops, snapshot, bulk=False):
    return compile_program({"ir_version": "1.0", "ops": ops},
                           revit_version="2026", snapshot=snapshot, bulk=bulk)


def _row(out, op_id, param):
    report = out.as_dict().get("grounding_report") or []
    return next((r for r in report
                 if r["op_id"] == op_id and r["param"] == param), None)


#: Живая программа 10.08: одна стена, тип не назван.
_BARE_WALL = [{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
               "p1_mm": [6000, 0], "level": LV, "height_mm": 3000}]


def test_the_document_default_must_not_present_an_empty_choice():
    """ЖИВОЙ СЛУЧАЙ 10.08: `chosen` пуст, и это неотличимо от «не выбирал».

    Пустая пара `{id: null, name: null}` — худшая из возможных форм: элемент
    ТИП ПОЛУЧИЛ, значит выбор состоялся, а строка сообщает обратное.
    """
    out = _compile(_BARE_WALL, _snapshot())
    assert out.ok, [d.code for d in out.diagnostics]
    row = _row(out, "W1", "type")
    assert row is not None and row["rule"] == "doc_default", row
    chosen = row["chosen"]
    assert chosen.get("resolved_at") == "revit", (
        "строка обязана СКАЗАТЬ, что выбор отложен документу, а не молча "
        f"вернуть пустую пару: {chosen}")
    assert chosen.get("read_from") == "result.W1.type_name", (
        "строка обязана назвать, ГДЕ имя появится после постройки: "
        f"{chosen}")


def test_the_note_never_stays_silent_about_a_choice_that_was_made():
    """Молчание о сделанном выборе — это и есть исходный дефект.

    Живьём `defaults_note_ru` не приехал вовсе: `describe_choices_ru`
    пропускала всё, у чего нет `rule_detail.candidates`. Для `sole_entry` это
    обосновано (кандидат один, выбирать не из чего), для документного
    умолчания — нет: типов стен у настоящего проекта десятки, выбор среди них
    СДЕЛАН, просто не нами.
    """
    out = _compile(_BARE_WALL, _snapshot())
    note = describe_choices_ru(out.as_dict()["grounding_report"])
    assert note, "витрина обязана говорить о документном умолчании"
    assert "result.W1.type_name" in note, note


def test_the_deferred_choice_is_filled_from_the_element_that_was_built():
    """Имя доезжает из РАНТАЙМА: эмиттер тип применил — он же его и прочитал.

    Это не догадка и не заполнение правдоподобным: `type_name` в квитанции
    исполнения читается с `GetTypeId()` построенного элемента.
    """
    from kukai.ir.ground import attach_runtime_choices

    out = _compile(_BARE_WALL, _snapshot())
    payload = {"ok": True, "W1": {"id": "424242",
                                  "type_name": "111_Кирпич 380"}}
    filled = attach_runtime_choices(out.as_dict()["grounding_report"], payload)
    chosen = filled[0]["chosen"]
    assert chosen["name"] == "111_Кирпич 380", chosen
    assert chosen["source"] == "readback", (
        "происхождение имени обязано быть названо: снапшот и построенный "
        f"элемент — разные источники: {chosen}")
    note = describe_choices_ru(filled)
    assert "111_Кирпич 380" in note, note


def test_a_missing_readback_leaves_the_choice_unresolved_and_invents_nothing():
    """Придуманное имя типа ХУЖЕ пустого: пустое честно, придуманное лжёт."""
    from kukai.ir.ground import attach_runtime_choices

    out = _compile(_BARE_WALL, _snapshot())
    report = out.as_dict()["grounding_report"]
    for payload in ({"ok": True, "W1": {"id": "424242"}},
                    {"ok": True, "W1": {"id": "1", "type_name": "  "}},
                    {"ok": True}, None, "не словарь"):
        filled = attach_runtime_choices(report, payload)
        chosen = filled[0]["chosen"]
        assert chosen["name"] is None, (payload, chosen)
        assert chosen["resolved_at"] == "revit", chosen
        note = describe_choices_ru(filled)
        assert "result.W1.type_name" in note, (payload, note)


def test_the_join_does_not_mutate_the_compiled_report():
    """`CompileOutput` переживает ход и кэшируется; квитанция — не черновик."""
    from kukai.ir.ground import attach_runtime_choices

    out = _compile(_BARE_WALL, _snapshot())
    report = out.as_dict()["grounding_report"]
    before = copy.deepcopy(report)
    attach_runtime_choices(report, {"ok": True,
                                    "W1": {"type_name": "111_Кирпич 380"}})
    assert report == before, "соединение обязано вернуть НОВЫЙ список"


# ── тот же прибор по остальным двум правилам ────────────────────────────────
# Дыра могла быть общей. Замер 10.08 говорит, что нет: `sole_entry` и
# `most_used` берут имя из снапшота, то есть знают его ещё до эмиссии.

def test_sole_entry_carries_its_name_at_compile_time():
    ops = [{"op": "create_ceiling", "id": "C1", "outline": SQ, "level": LV}]
    row = _row(_compile(ops, _snapshot()), "C1", "type")
    assert row is not None and row["rule"] == "sole_entry", row
    assert row["chosen"]["id"] == 1200, row
    assert row["chosen"]["name"] == "Потолок подвесной 600x600", row
    assert "resolved_at" not in row["chosen"], (
        "имя известно на стадии заземления — откладывать нечего")


def test_most_used_carries_its_name_at_compile_time():
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}",
             "instances": 1 if i % 3 == 0 else 0} for i in range(62)]
    pool[31] = {"id": 7031, "name": "Дверь однопольная 900x2100",
                "instances": 47}
    ops = [{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
            "p1_mm": [6000, 0], "level": LV, "height_mm": 3000,
            "type": {"by": "name", "value": "Кирпич 250"}},
           {"op": "create_door", "id": "D1",
            "host": {"by": "ref", "value": "W1"}, "offset_mm": 3000}]
    row = _row(_compile(ops, _snapshot(door_symbols=pool)), "D1", "symbol")
    assert row is not None and row["rule"] == "most_used", row
    assert row["chosen"]["name"] == "Дверь однопольная 900x2100", row
    assert "resolved_at" not in row["chosen"], row


# ── ЗАМОК НА ВЕСЬ ДИАПАЗОН ──────────────────────────────────────────────────
# Указатель `read_from` честен только пока поле существует. Прибор, накрывающий
# часть диапазона, опаснее отсутствующего, поэтому список опов с документным
# умолчанием проверяется ЦЕЛИКОМ, а не на стене-образце.

#: Минимальная программа на каждый оп, у которого пропущенный `type` уходит в
#: документное умолчание. Список берётся из `ground.py` замером, а не списком.
_DOC_DEFAULT_PROGRAMS = {
    "create_wall": [{"op": "create_wall", "id": "X1", "p0_mm": [0, 0],
                     "p1_mm": [6000, 0], "level": LV, "height_mm": 3000}],
    "create_floor": [{"op": "create_floor", "id": "X1", "outline": SQ,
                      "level": LV}],
    "create_roof": [{"op": "create_roof", "id": "X1", "outline": SQ,
                     "level": LV}],
    "create_floor_by_contour": [
        {"op": "create_floor_by_contour", "id": "X1", "level": LV,
         "contour": {"outer": {"shape": "poly", "points_mm": SQ}}}],
    "create_wall_foundation": [
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": LV, "height_mm": 3000,
         "type": {"by": "name", "value": "Кирпич 250"}},
        {"op": "create_wall_foundation", "id": "X1",
         "wall": {"by": "ref", "value": "W1"}}],
    "create_extrusion_roof": [
        {"op": "create_extrusion_roof", "id": "X1", "level": LV,
         "p0_mm": [0, 0], "p1_mm": [0, 6000],
         "profile_mm": [[0, 0], [4000, 2000], [8000, 0]],
         "start_mm": 0, "end_mm": 6000}],
    "create_area_reinforcement": [
        {"op": "create_floor", "id": "F1", "outline": SQ, "level": LV,
         "type": {"by": "name", "value": "Монолит 200"}},
        {"op": "create_area_reinforcement", "id": "X1",
         "host": {"by": "ref", "value": "F1"}, "direction_deg": 0}],
    "create_filled_region": [
        {"op": "create_filled_region", "id": "X1",
         "in_view": {"by": "element_id", "value": 12345},
         "contour": {"outer": {"shape": "poly", "points_mm": SQ}}}],
}

_TYPE_NAME_READBACK = re.compile(r'__rb(?:_\w+)?\["type_name"\]')


def test_the_named_op_list_matches_the_rule_in_ground():
    """Список выше — не память автора, а то же множество, что в `ground.py`."""
    import inspect

    from kukai.ir import ground as ground_mod

    src = inspect.getsource(ground_mod.ground)
    named = {name for name in _DOC_DEFAULT_PROGRAMS if f'"{name}"' in src}
    assert named == set(_DOC_DEFAULT_PROGRAMS), (
        "оп с документным умолчанием исчез из ground.py или переименован: "
        f"{set(_DOC_DEFAULT_PROGRAMS) - named}")


def test_every_document_default_op_reads_its_type_name_back():
    """Иначе `read_from` указывал бы на поле, которого в квитанции нет.

    Пустое поле — честно; указатель в никуда — нет. Этот замок ловит новый оп
    с документным умолчанием, у которого забыли чтение типа обратно.
    """
    for op_name, ops in _DOC_DEFAULT_PROGRAMS.items():
        out = _compile(ops, _snapshot(), bulk=True)
        assert out.ok, (op_name, [d.code for d in out.diagnostics])
        row = _row(out, "X1", "type")
        assert row is not None and row["rule"] == "doc_default", (op_name, row)
        assert row["chosen"].get("read_from") == "result.X1.type_name", (
            op_name, row)
        assert _TYPE_NAME_READBACK.search(out.csharp or ""), (
            f"{op_name}: квитанция обещает result.X1.type_name, а эмиссия "
            "имя типа обратно не читает")


def test_a_deferred_param_other_than_type_gets_no_address_it_cannot_keep():
    """Указатель верен ТОЛЬКО пока отложен `type`, и это не вечная правда.

    Сегодня `IN_EMIT_DEFAULT` ставится единственно на `type`, а имя обратно
    читается под ключом `type_name`. Заведи кто-нибудь документное умолчание на
    другом параметре — и прежний указатель послал бы читателя в чужое поле.
    Строка обязана в этом случае остаться без адреса, а соединение — не
    трогать её: догадка под видом замера хуже молчания.
    """
    from kukai.ir import ground as ground_mod

    report = ground_mod.compiler_choices([{
        "id": "X1", "op": "выдуманный_оп",
        "какой_то_другой_селектор": {"__grounded__": {
            "id": None, "name": None, "via": "doc_default",
            "in_emit": IN_EMIT_DEFAULT}}}])
    chosen = report[0]["chosen"]
    assert chosen["resolved_at"] == "revit", chosen
    assert "read_from" not in chosen, chosen
    filled = ground_mod.attach_runtime_choices(
        report, {"ok": True, "X1": {"type_name": "не про этот параметр"}})
    assert filled[0]["chosen"]["name"] is None, filled
    assert "не про этот параметр" not in describe_choices_ru(filled)


def test_the_deferred_marker_comes_from_the_emitter_contract():
    """`resolved_at` ставится по метке эмиссии, а не по имени правила.

    Метка `IN_EMIT_DEFAULT` — то самое, что заставляет эмиттер спросить
    документ; привязка к ней, а не к строке «doc_default», не даёт витрине
    разъехаться с эмиссией при переименовании правила.
    """
    from kukai.ir import ground as ground_mod
    from kukai.ir.compiler import plan_program

    normed = plan_program({"ir_version": "1.0", "ops": _BARE_WALL},
                          bulk=False).to_ops()
    grounded = ground_mod.ground(normed, _snapshot())
    res = grounded[0]["type"]["__grounded__"]
    assert res["in_emit"] == IN_EMIT_DEFAULT
    res_without = dict(res)
    res_without.pop("in_emit")
    report = ground_mod.compiler_choices(
        [{"id": "W1", "op": "create_wall",
          "type": {"__grounded__": res_without}}])
    assert "resolved_at" not in report[0]["chosen"], (
        "без метки эмиссии откладывать нечего — строка не должна обещать "
        "чтения, которого не будет")
