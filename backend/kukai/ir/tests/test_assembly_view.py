"""ЗАКОНЫ СВОДКИ О СБОРКЕ. У каждого — контроль, который обязан покраснеть.

Проверяется не «функция вернула словарь», а четыре свойства, ради которых
модуль написан: адрес обязателен, список кодов закрыт, молчание источника
записывается, и замкнутость РАЗЛИЧАЕТСЯ (иначе прибор измеряет собственную
доброжелательность).
"""
from __future__ import annotations

import os
import unittest

import pytest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kukai.ir.assembly_view import (  # noqa: E402
    AssemblyView,
    AssemblyViewError,
    Observation,
    observe_program,
)

_LVL = {"by": "ref", "value": "L1"}
_TYPE = {"by": "name", "value": "Типовой - 200мм"}
_LEVEL_OP = {"op": "create_level", "id": "L1", "elev_mm": 0.0, "name": "Этаж 1"}


def _wall(oid, p0, p1):
    return {"op": "create_wall", "id": oid, "type": _TYPE, "level": _LVL,
            "height_mm": 3000.0, "p0_mm": list(p0), "p1_mm": list(p1)}


def _program(ops, intent="проба"):
    return {"ir_version": "1.0", "intent": intent, "ops": [_LEVEL_OP] + ops}


_BOX = [_wall("w1", (0, 0), (6000, 0)), _wall("w2", (6000, 0), (6000, 4000)),
        _wall("w3", (6000, 4000), (0, 4000)), _wall("w4", (0, 4000), (0, 0))]
#: та же коробка, но последняя стена не доходит до начала: дыра 1500 мм
_GAP = _BOX[:3] + [_wall("w4", (0, 4000), (0, 1500))]


def _codes(view: AssemblyView) -> set[str]:
    return {o.code for o in view.observations}


class TheAddressIsMandatory(unittest.TestCase):
    """Наблюдение без адреса не даёт модели ничего, что можно поправить."""

    def test_an_observation_without_an_address_is_refused(self):
        with pytest.raises(AssemblyViewError):
            Observation("enclosure_none", address=())

    def test_an_address_makes_the_same_observation_legal(self):
        """КОНТРОЛЬ: отказ обязан быть про АДРЕС, а не про код."""
        assert Observation("enclosure_none", address=("w1",)).address == ("w1",)


class TheCodeListIsClosed(unittest.TestCase):

    def test_an_unknown_code_is_refused(self):
        with pytest.raises(AssemblyViewError):
            Observation("прекрасное_наблюдение", address=("w1",))

    def test_a_foreign_registry_code_passes_by_its_prefix(self):
        """Коды правил приезжают своим реестром: заводить им вторые имена
        значило бы развести два списка, обязанных совпадать."""
        assert Observation("hab:HAB042", address=("r1",)).code == "hab:HAB042"


class EnclosureIsActuallyDiscriminated(unittest.TestCase):
    """ГЛАВНЫЙ ЗАКОН. Прибор, отвечающий одинаково на замкнутое и разомкнутое,
    не измеряет ничего — и до 15.08.2026 он отвечал именно так, когда в
    программе не было комнат."""

    def test_a_closed_box_is_seen_as_enclosing(self):
        view = observe_program(_program(_BOX))
        assert "enclosure_ok" in _codes(view)
        enclosure = [o for o in view.observations if o.code == "enclosure_ok"][0]
        assert enclosure.number == 1.0
        assert set(enclosure.address) == {"w1", "w2", "w3", "w4"}

    def test_a_gap_of_1500mm_is_seen_as_enclosing_NOTHING(self):
        view = observe_program(_program(_GAP))
        assert "enclosure_none" in _codes(view)
        assert "enclosure_ok" not in _codes(view)
        gap = [o for o in view.observations if o.code == "enclosure_none"][0]
        assert set(gap.address) == {"w1", "w2", "w3", "w4"}

    def test_no_walls_is_a_THIRD_answer_not_the_same_as_enclosing_nothing(self):
        """«Стен нет» и «стены есть, ничего не замкнули» — разные факты, и
        разными их обязан видеть тот, кто будет чинить программу."""
        view = observe_program(_program([]))
        assert _codes(view) == {"no_walls"}


class SilenceIsRecordedNotEmpty(unittest.TestCase):

    def test_a_rule_addressed_to_the_whole_building_goes_to_silence(self):
        """`HAB000` («в модели нет помещений») верно и НЕ говорит о сборке —
        оно говорит, что судить было нечем. Его адрес — здание целиком, то есть
        адрес, которым нельзя действовать."""
        view = observe_program(_program(_BOX))
        assert any(k.startswith("design_check:HAB000")
                   for k in view.silent_sources), view.silent_sources
        assert not any(o.code == "hab:HAB000" for o in view.observations)

    def test_who_was_asked_is_always_stated(self):
        """Ноль наблюдений при пустом `asked` неотличим от «не спрашивали».

        Состав спрошенных пинуется в `EverySourceIsNamedAndItsSilenceToo`;
        здесь держится только сам закон — список НЕ ПУСТ.
        """
        assert observe_program(_program(_BOX)).sources_asked


class TheViewNamesWhatItJudged(unittest.TestCase):

    def test_source_says_declared_not_built(self):
        """Сегодня судится ЗАЯВЛЕННОЕ. Читатель обязан знать это из ответа, а
        не из докстроки: ветка, судящая построенное, существует и не имеет ни
        одного прод-вызывающего."""
        assert observe_program(_program(_BOX)).source == "program"

    def test_the_wire_shape_is_flat_enough_to_read(self):
        row = observe_program(_program(_GAP)).to_dict()
        assert row["schema"] == "assembly-view/1"
        assert isinstance(row["observations"], list)
        assert all({"code", "at"} <= set(o) for o in row["observations"])


def test_a_broken_judge_is_named_not_swallowed(monkeypatch):
    """КОНТРОЛЬ-FAIL МОЛЧАНИЯ. Если судья падает, пустой список наблюдений
    обязан сопровождаться ПРИЧИНОЙ: иначе «ничего не нашли» неотличимо от
    «всё хорошо», а это тот самый молчаливо-неверный результат.

    Функцией, а не методом: подмена нужна на уровне модуля, и `monkeypatch`
    у `unittest.TestCase` недоступен.
    """
    import kukai.ir.design_check as dc

    def boom(*_a, **_k):
        raise RuntimeError("судья сломан нарочно")

    monkeypatch.setattr(dc, "check_bundle", boom)
    view = observe_program(_program(_BOX))
    assert view.observations == ()
    assert "design_check" in view.silent_sources
    assert "судья сломан нарочно" in view.silent_sources["design_check"]


# --------------------------------- дайджест переживает историю (Ш2)

def _receipt_with(view) -> str:
    """Квитанция такой формы, какой её строит ПРОД — не такой, какой удобно.

    🔴 ПРЕЖНЯЯ РЕДАКЦИЯ КЛАЛА `assembly_note` НА ВЕРХНИЙ УРОВЕНЬ РУКАМИ, а прод
    клал его внутрь `building` (`live/verdict._with_assembly`). Форма теста
    выживала при сворачивании, форма прода — нет, и тест был зелен ровно
    столько, сколько петля была разомкнута: он сторожил фикстуру.

    Теперь блок собирается как в проде (`building` со всеми полями, дайджест
    ВНУТРИ), а наверх его поднимает та самая функция, которую зовёт прод, —
    `serving.lift_assembly_note`. Ошибиться формой больше негде: форма одна.
    """
    import json
    from kukai.ir.assembly_view import digest
    from kukai.ir.serving import lift_assembly_note

    block = {                                # ← как строит `live/verdict.judge`
        "programs": 2, "ops": 4, "programs_evicted": 0,
        "verdict": "PASS", "message_ru": "…",
        "assembly": view.to_dict(),          # СТРУКТУРА — будет свёрнута
        "assembly_note": digest(view),       # ПЛОСКАЯ строка — обязана выжить
    }
    receipt = {
        "ok": True, "kir": True,
        "witness": {"geometry_ok": True, "semantic_ok": True},
        "result": {"w1": {"id": "9001"}, "w2": {"id": "9002"}},
        "building": block,
    }
    return json.dumps(lift_assembly_note(receipt, block), ensure_ascii=False)


def test_the_receipt_shape_is_the_one_prod_builds():
    """КОНТРОЛЬ ФОРМЫ. Дайджест обязан лежать И внутри `building` (как его
    кладёт вердикт), И наверху (как его поднимает прод). Если однажды подъём
    исчезнет, этот тест краснеет ДО того, как краснеет выживание."""
    import json
    view = observe_program(_program(_GAP))
    receipt = json.loads(_receipt_with(view))
    assert "assembly_note" in receipt["building"], "вердикт перестал класть дайджест"
    assert receipt["assembly_note"] == receipt["building"]["assembly_note"]


def test_without_the_lift_the_digest_is_lost():
    """КОНТРОЛЬ-FAIL ПОДЪЁМА: без него дайджест НЕ выживает.

    Без этого контроля предыдущий тест зелен по построению — он не отличает
    «подъём работает» от «сворачиватель и так всё сохраняет»."""
    import json
    from kukai.api.chat_helpers import _summarize_tool_result
    from kukai.ir.assembly_view import digest

    view = observe_program(_program(_GAP))
    nested = json.dumps({                    # форма БЕЗ подъёма — прод до 15.08
        "ok": True, "kir": True,
        "result": {"w1": {"id": "9001"}},
        "building": {"programs": 2, "verdict": "PASS",
                     "assembly": view.to_dict(), "assembly_note": digest(view)},
    }, ensure_ascii=False)
    collapsed = _summarize_tool_result(nested, cap=600)
    assert "enclosure_none" not in collapsed, (
        "дайджест выжил БЕЗ подъёма — значит подъём ничего не доказывает, "
        "и сворачиватель изменился: перечитай `_summarize_tool_result`")


def test_the_digest_survives_history_collapse_while_the_structure_does_not():
    """🔴 ГЛАВНЫЙ ЗАКОН Ш2. Восприятие, которое модель не может ВСПОМНИТЬ, —
    не петля.

    Через тридцать сообщений `_summarize_tool_result` заменяет КАЖДЫЙ словарь и
    список на «свёрнуто», оставляя только скаляры верхнего уровня. Тест
    прогоняет квитанцию через настоящий сворачиватель и требует, чтобы КОД
    наблюдения и АДРЕС остались читаемыми — а структура при этом свернулась
    (иначе тест был бы зелен и без дайджеста).
    """
    from kukai.api.chat_helpers import _summarize_tool_result

    view = observe_program(_program(_GAP))
    collapsed = _summarize_tool_result(_receipt_with(view), cap=600)

    assert "enclosure_none" in collapsed, collapsed
    assert "w1" in collapsed and "w4" in collapsed
    # КОНТРОЛЬ: структура ОБЯЗАНА быть свёрнута, иначе выживание ничего не
    # доказывает — оно объяснялось бы тем, что не сворачивают вообще
    assert "свёрнуто" in collapsed
    assert '"observations"' not in collapsed


def test_the_digest_never_looks_complete_when_it_is_not():
    """Усечённая строка, не сказавшая об усечении, хуже отсутствующей: по ней
    принимают решение как по полной."""
    from kukai.ir.assembly_view import AssemblyView, Observation, digest

    many = tuple(Observation("hab:HAB0%02d" % i, address=("r%d" % i,))
                 for i in range(1, 20))
    line = digest(AssemblyView(observations=many,
                               silent_sources={"design_check:HAB000": "нет комнат"}))
    assert len(line) <= 120
    assert " +" in line, line          # сколько НЕ показано
    assert line.endswith("?1"), line   # сколько источников промолчало


def test_the_building_name_is_asked_of_the_verdict_not_asserted_here():
    """🔴 КОНТРОЛЬ ЗА СОБСТВЕННЫМ ДЕФЕКТОМ КЛАССА.

    Отличать «наблюдение об элементе» от «правило не судило» приходится по
    адресу здания целиком. Первая редакция сравнивала его с КОНСТАНТОЙ этого
    модуля — и она верна ровно на его собственном пути вызова: едва сводку
    позвал `live.verdict` со своим именем («здание этой сессии (пачка
    программ)»), `HAB000` протекло в наблюдения с адресом, которым нельзя
    действовать. Утверждено в одном месте, прочитано в другом — ровно тот
    класс, против которого написан модуль.

    Здесь имя берётся у ВЕРДИКТА, и тест это держит: чужое имя обязано
    работать так же, как своё.
    """
    from kukai.ir import design_check as dc
    from kukai.ir.assembly_view import observe_verdict

    alien = dc.check_bundle([_program(_BOX)],
                            building_id="здание этой сессии (пачка программ)")
    view = observe_verdict(alien, ["w1", "w2", "w3", "w4"])
    assert not any(o.code == "hab:HAB000" for o in view.observations), \
        [o.code for o in view.observations]
    assert any(k.endswith("HAB000") for k in view.silent_sources)


# ------------------------------------------ Ш5: те же правила по ПОСТРОЕННОМУ

def _l0():
    """Разбор того же дома. Фикстура берётся у соседа, а не переписывается:
    копия унаследовала бы форму и НЕ унаследовала бы решения, которые в ней уже
    приняты (контуры такие, как их отдаёт Revit; проёмы точками с габаритами)."""
    from kukai.ir.tests.test_design_check import _tiny_l0_document
    return _tiny_l0_document()


class TheBuiltBuildingIsJudgedByTheSameRules(unittest.TestCase):
    """🔴 ВТОРАЯ ПОЛОВИНА ЦЕЛОСТНОСТИ. Один вход правил объявлен ТИПОМ
    (`ModelSource`), но до 15.08.2026 жила только ветка PROGRAM: продукт судил
    ЗАМЫСЕЛ и называл это проверкой РЕЗУЛЬТАТА."""

    def test_the_parse_door_says_it_judged_the_BUILT_thing(self):
        from kukai.ir.assembly_view import observe_l0
        assert observe_l0(_l0()).source == "parse"

    def test_the_two_doors_do_not_share_an_address_space(self):
        """Замер хребта (`tools/address_spine.py`) доказал общий адрес у миров
        РАЗБОРА и ничего не сказал про программу: её `w1` в L0 нет по
        построению. Сводка обязана называть своё пространство, иначе два
        наблюдения об одной стене сравнят как разные, не заметив этого."""
        from kukai.ir.assembly_view import observe_l0

        assert observe_program(_program(_BOX)).address_space == "op_id"
        assert observe_l0(_l0()).address_space == "element_id"

    def test_enclosure_is_SILENT_on_the_parse_path_not_answered_falsely(self):
        """🔴 МОЛЧАЛИВО-НЕВЕРНОЕ НАБЛЮДЕНИЕ, ПОЙМАННОЕ ДО ВЫПУСКА.

        `partition_faces` считает ТОЛЬКО `spatial_model_from_program`: на пути
        PARSE разбиение не строится намеренно — контуры помещений берутся у
        Revit. Значит поле равно нулю ПО ПОСТРОЕНИЮ, и первая редакция читала
        этот ноль как ОТВЕТ, выдавая «стены не замкнули ничего» на здании, где
        107 помещений из 120 несут измеренный контур (живой замер
        `sob62_r23_v5`).

        Ноль величины, которую прибор на этом входе не считает, — не результат.
        """
        from kukai.ir.assembly_view import observe_l0

        view = observe_l0(_l0())
        assert not any(o.code.startswith("enclosure") for o in view.observations)
        assert "design_check:enclosure" in view.silent_sources

    def test_CONTROL_the_same_question_IS_answered_on_the_program_path(self):
        """Без этого контроля молчание объяснялось бы тем, что замкнутость не
        считается нигде, — и закон выше был бы зелен по построению."""
        assert "enclosure_ok" in _codes(observe_program(_program(_BOX)))


class ATruncatedAddressSaysSo(unittest.TestCase):
    """Перечитанное здание даёт 690 стен; такой список адресом не является.
    Обрезать молча нельзя: усечённый список читается как полный."""

    def test_the_full_count_rides_with_the_shown_ones(self):
        from kukai.ir.assembly_view import ADDRESS_CAP, Observation

        many = tuple(str(i) for i in range(ADDRESS_CAP))
        row = Observation("enclosure_none", address=many,
                          address_total=690).to_dict()
        assert row["at_of"] == 690
        assert len(row["at"]) == ADDRESS_CAP

    def test_an_unshortened_list_carries_no_marker(self):
        """КОНТРОЛЬ: маркер, стоящий всегда, не отличает усечённое от полного."""
        from kukai.ir.assembly_view import Observation

        assert "at_of" not in Observation("no_walls", address=("w1",)).to_dict()

    def test_claiming_fewer_addresses_than_shown_is_refused(self):
        from kukai.ir.assembly_view import Observation

        with pytest.raises(AssemblyViewError):
            Observation("no_walls", address=("w1", "w2"), address_total=1)


# ------------------------- ВТОРОЙ ИСТОЧНИК: аномалии плана (дыра Ш1, 15.08)

_DUP = [_wall("w1", (0, 0), (6000, 0)), _wall("w2", (0, 0), (6000, 0))]
#: тот же дубль, но вторая стена нарисована В ОБРАТНУЮ сторону — для автора
#: это та же ошибка, и прибор обязан видеть её так же
_DUP_REVERSED = [_wall("w1", (0, 0), (6000, 0)), _wall("w2", (6000, 0), (0, 0))]
#: три стены встык вместо одной — «полосатая стена»
_STRIPED = [_wall("w1", (0, 0), (2000, 0)), _wall("w2", (2000, 0), (4000, 0)),
            _wall("w3", (4000, 0), (6000, 0))]


class TheSummaryDiscriminatesWhatOneSourceCannot(unittest.TestCase):
    """🔴 ЗАМЕР, ПРОВАЛИВШИЙ СОБСТВЕННЫЙ КРИТЕРИЙ ПРИЁМКИ (15.08).

    До подключения второго источника одна стена, три стены встык и ДВЕ СТЕНЫ В
    ОДНОМ МЕСТЕ давали ОДИН ответ `enclosure_none`. Различался только список
    адресов — а он говорит, сколько стен написали, не о сборке. Сводка,
    отвечающая одинаково на здоровое и на дублированное, не измеряет ничего.
    """

    def test_duplicated_walls_are_told_apart_from_one_wall(self):
        one = _codes(observe_program(_program([_wall("w1", (0, 0), (6000, 0))])))
        dup = _codes(observe_program(_program(_DUP)))
        assert dup != one, "дубль неотличим от здоровой стены"
        assert "preview:coincident_walls" in dup

    def test_a_wall_drawn_backwards_is_the_same_defect(self):
        assert "preview:coincident_walls" in _codes(
            observe_program(_program(_DUP_REVERSED)))

    def test_CONTROL_a_healthy_box_carries_no_anomaly(self):
        """Без этого контроля код «дубли» мог бы стоять всегда, и тогда он не
        отличал бы ничего — зелёный без акта различения."""
        assert not any(c.startswith("preview:")
                       for c in _codes(observe_program(_program(_BOX))))

    def test_the_striped_wall_stays_INDISTINGUISHABLE_and_that_is_measured(self):
        """🔴 ОТРИЦАТЕЛЬНЫЙ РЕЗУЛЬТАТ, ЗАКРЕПЛЁННЫЙ НАРОЧНО.

        Три стены встык — случай, ради которого затевалась вся ставка, — от
        одной стены НЕ отличаются, и это не недоделка, а замер: на настоящем
        здании (`sob62_r23_v5`, 690 стен) в коллинеарные цепочки входит 41.6 %
        стен, а после отсева законных узлов и разнотипья — всё равно 22.6 %
        (156 стен). Детектор на этом кричал бы волками на четверти каждого
        проекта.

        Значит полосатая стена — не слепота свидетеля, а НЕСОВПАДЕНИЕ ЗАМЫСЛА:
        ничто не объявляло «здесь одна стена». Лечится единицей замысла, а не
        предикатом по осям. Тест держит границу: если кто-то однажды научит
        сводку это различать, он обязан прийти сюда и объяснить, чем побит
        замер 22.6 %.
        """
        one = _codes(observe_program(_program([_wall("w1", (0, 0), (6000, 0))])))
        assert _codes(observe_program(_program(_STRIPED))) == one


class EverySourceIsNamedAndItsSilenceToo(unittest.TestCase):

    def test_who_was_asked_names_EVERY_source(self):
        """🔴 ЧЕТВЁРТЫЙ ИСТОЧНИК — `units` (15.08.2026), и этот пин сработал
        ровно как задуман: добавить источник и не прийти сюда нельзя.

        Три первых судят ЭЛЕМЕНТ (замкнутость по стенам, аномалия плана,
        опора конструктива). Четвёртый читает НАБОР: единицы замысла
        (`course.unit(reads_as=...)`) — единственный источник, работающий на
        арности N. Он молчит, когда единиц нет: «не спрашивали» и «спросили,
        ответа нет» здесь по-прежнему разные факты, и `sources_asked` называет
        именно первый.
        """
        assert observe_program(_program(_BOX)).sources_asked == (
            "design_check", "preview", "coherence", "units")

    def test_no_walls_still_asks_the_plan(self):
        """«Стен нет» не значит «смотреть не на что»: проём без хозяина живёт
        без единой стены. Оставить источник в `asked`, не спросив его, — ложь
        о том, у кого спрашивали."""
        view = observe_program(_program([]))
        assert view.sources_asked == ("design_check", "preview", "coherence")
        assert "no_walls" in _codes(view)

    def test_a_broken_plan_source_is_named_not_swallowed(self):
        import kukai.ir.preview as pv
        from kukai.ir.assembly_view import observe_plan_anomalies

        original = pv.build_program_preview
        try:
            def boom(*_a, **_k):
                raise RuntimeError("план сломан нарочно")
            pv.build_program_preview = boom
            found, silence = observe_plan_anomalies([_program(_DUP)])
        finally:
            pv.build_program_preview = original
        assert found == []
        assert "план сломан нарочно" in silence["preview"]

    def test_the_foreign_code_is_not_renamed_here(self):
        """У `AnomalyReason` свой закрытый реестр. Второе имя тому же явлению
        развело бы два списка, обязанных совпадать."""
        from kukai.ir.preview import AnomalyReason

        codes = _codes(observe_program(_program(_DUP)))
        assert "preview:" + AnomalyReason.COINCIDENT_WALLS.value in codes


# ------------------- ТРЕТИЙ ИСТОЧНИК: что ни на чём не стоит (дыра Ш1, 15.08)

_SLAB = {"op": "create_floor", "id": "f1", "level": _LVL, "type": _TYPE,
         "outline": [[0, 0], [20000, 0], [20000, 20000], [0, 20000]]}


def _column(oid, xy):
    return {"op": "create_column", "id": oid, "level": _LVL, "type": _TYPE,
            "xy": list(xy), "height_mm": 3000.0}


class WhatStandsOnNothingIsNamed(unittest.TestCase):
    """🔴 ИСТОЧНИК СЧИТАЛСЯ ДАВНО И БЫЛ ОТРЕЗАН ОДНИМ ПОЛЕМ.

    `coherence.check` отдавал счётчики без адресов («колонн_вне_плиты: 404» на
    настоящей башне), а первый закон сводки требует адреса. Причина лежала на
    одну функцию выше: `flatten` держал `id` операции в руках и не переносил
    его в `Elem`. Работа была сделана и не соединена — наш способ отказа по
    умолчанию.
    """

    def test_a_column_in_the_air_is_named_by_its_own_id(self):
        view = observe_program(_program(
            [_SLAB, _wall("w1", (0, 0), (6000, 0)),
             _column("c_ok", (1000, 1000)), _column("c_air", (99000, 99000))]))
        loose = [o for o in view.observations if o.code == "column_off_slab"]
        assert loose, _codes(view)
        assert loose[0].address == ("c_air",)

    def test_CONTROL_the_column_that_stands_on_the_slab_is_NOT_named(self):
        """Без этого контроля прибор мог бы звать «в воздухе» каждую колонну —
        и был бы красным по построению, ничего не различая."""
        view = observe_program(_program(
            [_SLAB, _wall("w1", (0, 0), (6000, 0)),
             _column("c_ok", (1000, 1000))]))
        assert not any(o.code == "column_off_slab" for o in view.observations)

    def test_without_a_slab_the_source_is_SILENT_not_screaming(self):
        """🔴 ВЫРОЖДЕННЫЙ ВХОД, НАЗВАННЫЙ ВСЛУХ. Без плит «вне плиты» верно
        для КАЖДОГО элемента — то есть не различает ничего. Залить сводку
        такими наблюдениями значило бы выдать за находку свойство входа."""
        view = observe_program(_program(
            [_wall("w1", (0, 0), (6000, 0)), _column("c1", (1000, 1000))]))
        assert not any(o.code == "column_off_slab" for o in view.observations)
        assert "плит" in view.silent_sources.get("coherence", "")

    def test_all_three_sources_answer_in_one_summary(self):
        """Три РАЗНЫХ дефекта в одной программе — три разных кода, и каждый со
        своим адресом. Ради этого сводка и существует."""
        view = observe_program(_program(
            [_SLAB, _wall("w1", (0, 0), (6000, 0)),
             _wall("w2", (0, 0), (6000, 0)), _column("c_air", (99000, 99000))]))
        assert _codes(view) == {"enclosure_none", "preview:coincident_walls",
                                "column_off_slab"}

    def test_a_broken_coherence_source_is_named_not_swallowed(self):
        from kukai.design import coherence as co
        from kukai.ir.assembly_view import observe_coherence

        original = co.flatten
        try:
            def boom(*_a, **_k):
                raise RuntimeError("связность сломана нарочно")
            co.flatten = boom
            found, silence = observe_coherence([_program(_BOX)])
        finally:
            co.flatten = original
        assert found == []
        assert "связность сломана нарочно" in silence["coherence"]
