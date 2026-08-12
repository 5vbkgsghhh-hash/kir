"""stairs_landing_emit — ПЛОЩАДКА ЛЕСТНИЦЫ ПО ЭСКИЗУ (волна лестниц, 10.08.2026).

ЗАЧЕМ ЭТА ОПЕРАЦИЯ СУЩЕСТВУЕТ.  До неё компилятор умел ровно один марш —
прямой либо винтовой, — и лестница без площадки есть лестница на один марш.
Настоящий дом так не строится: между этажами стоит промежуточная площадка, и
сказать это на языке было НЕЧЕМ.  Перепись способностей (10.08,
`tools/api_capability_census.py`) нашла всё семейство площадок ни разу не
рассматривавшимся; здесь взята ОДНА фабрика — та, у которой свидетель читает
РЕЗУЛЬТАТ и может провалиться, — а остальные четыре отказаны ПОИМЁННО ниже.

────────────────────────────────────────────────────────────────────────────
ЗАМЕР API (компиляция на :52412 против настоящих сборок 2021-2026, 10.08.2026;
арбитр — компилятор, а не RevitAPI.xml)
────────────────────────────────────────────────────────────────────────────

  StairsLanding.CreateSketchedLanding(Document, ElementId,
                CurveLoop, Double)                 -> StairsLanding    → 6/6
  StairsLanding.CreateSketchedLandingWithSlopeData(Document, ElementId,
                IList<SketchedStairsCurveData>, Double)                → 6/6
  StairsLanding.CanCreateAutomaticLanding(Document, ElementId×2)       → 6/6
  StairsRun.CreateSketchedRun(Document, ElementId, Double,
                IList<Curve>×3)                                        → 6/6
  StairsRun.CreateSketchedRunWithSlopeData(Document, ElementId, Double,
                IList<SketchedStairsCurveData>, IList<Curve>×2)        → 6/6
  new SketchedStairsCurveData(Curve, Double, SketchedCurveSlopeOption) → 6/6
  StairsEditScope.Start(ElementId stairsId)   — ОДНОАРГУМЕНТНЫЙ        → 6/6
  StairsEditScope.Start(ElementId base, ElementId top)                 → 6/6
  StairsEditScope.IsPermitted / Stairs.IsInEditMode()                  → 6/6
  Stairs.GetStairsLandings() / .GetStairsRuns()                        → 6/6
  Stairs.ActualRiserHeight / .BaseElevation / .TopElevation            → 6/6
  StairsLanding.GetFootprintBoundary() -> CurveLoop                    → 6/6
  StairsLanding.BaseElevation / .Thickness / .IsAutomaticLanding       → 6/6
  StairsLanding.GetStairs() / .GetStairsPath()                         → 6/6
  StairsLanding.SetSketchedLandingBoundaryAndPath(Document, CurveLoop×2)→ 6/6
  doc.Application.VertexTolerance                                      → 6/6

  StairsLanding lg = ...CreateAutomaticLanding(doc, r1, r2)  → 0/6  CS1061
      (настоящий возврат — `IList<ElementId>`, проверено отдельной строкой:
       `IList<ElementId> x = CreateAutomaticLanding(...)` собирается 6/6)
  BuiltInParameter.STAIRS_LANDING_ELEVATION                  → 0/6  CS0117
  ElementTypeGroup.StairsLandingType                         → 0/6  CS0117

ПОСЛЕДНИЕ ТРИ СТРОКИ — НЕ ПЕДАНТИЗМ, каждая закрыла отдельный соблазн.
Отметка площадки читается СВОЙСТВОМ `BaseElevation`: цепочки BuiltInParameter
для неё не существует ни на одной версии, и свидетель, написанный через BIP,
не собрался бы нигде.  Спросить у документа «твой тип площадки по умолчанию»
НЕЛЬЗЯ ПО ПОСТРОЕНИЮ — `ElementTypeGroup` такого члена не несёт, — и поэтому
у операции НЕТ параметра `type` вовсе: тип площадки определяет тип лестницы
(Autodesk: «The landing type … is determined by stairs type»), то есть выбор
уже сделан хозяином и второго входа для него быть не должно.  А
`CreateAutomaticLanding` возвращает СПИСОК идентификаторов, а не элемент —
именно поэтому перепись пометила её «по возврату не видно», и именно поэтому
она отказана ниже отдельной причиной.

────────────────────────────────────────────────────────────────────────────
ПЛОЩАДКЕ НУЖНА ТА ЖЕ ОБЛАСТЬ ПРАВКИ, ЧТО И МАРШУ — ЭТО ЗАМЕР, А НЕ ДОГАДКА
────────────────────────────────────────────────────────────────────────────
RevitAPI.xml пишет у `CreateSketchedLanding` дословно и одинаково на всех
шести версиях: `InvalidOperationException` — «The stairs element represented
by stairsId is not in an active StairsEditScope.  New components cannot be
added to it.»  Значит область правки обязательна, и вопрос «а нельзя ли
поставить площадку рядом с маршем в одной программе» решается НЕ ослаблением
закона соло-опа, а вторым фактом того же замера: у `StairsEditScope.Start`
есть ОДНОАРГУМЕНТНАЯ перегрузка (`Start(ElementId stairsId)`, 6/6), которая
открывает область правки на УЖЕ СУЩЕСТВУЮЩЕЙ лестнице.

Отсюда устройство: `create_stairs_landing` — САМ соло-оп (`spec.SOLO_OPS`), со
своим шаблоном программы, и адресует лестницу `element_id`'ом.  Цена площадки
— ОТДЕЛЬНАЯ ПРОГРАММА, ровно как цена многоэтажки оказалась двумя программами
(`datum_emit.emit_multistory_stairs`).  Закон пачки при этом не ослаблен ни на
байт: две области правки в одном документе одновременно Revit не открывает
(«there already is a stairs edit mode active in the document» — тот же текст
исключения), поэтому соседство двух лестничных опов невыразимо ПО REVIT, а не
по нашему вкусу.

────────────────────────────────────────────────────────────────────────────
ОТКАЗАНО ПОИМЁННО, С ПРИЧИНОЙ (перепись отдельно считает корзину «названо без
причины» — каждая строка ниже держит её маленькой)
────────────────────────────────────────────────────────────────────────────

`StairsLanding.CreateAutomaticLanding` — ОТКАЗАНО.  Не потому, что её нет
    (есть, 6/6), а потому, что она требует ДВУХ УЖЕ ПОСТРОЕННЫХ МАРШЕЙ одной
    лестницы, а компилятор сегодня строит РОВНО ОДИН марш на лестницу
    (`create_stairs`: либо прямой, либо винтовой, ровно один вызов).  Второго
    марша взять неоткуда, то есть операция была бы вызываема только на
    лестнице, построенной не нами и снаружи не проверяемой.  Плюс её возврат
    — `IList<ElementId>` (замер выше): Autodesk пишет «landing(s)», число
    площадок выбирает Revit, и свидетеля на КОЛИЧЕСТВО у нас нет — автор
    никакого количества не называл, а требовать конкретное значило бы
    повторить дефект `height_mm` (31.07, откатывались верно построенные
    стены).  ЧТО ОТКРЫВАЕТ: марш из нескольких пролётов у `create_stairs`;
    тогда у автоматической площадки появятся и вход, и осмысленный свидетель.

`StairsLanding.CreateSketchedLandingWithSlopeData` — ОТКАЗАНО.  Отличается от
    взятой ровно одним: вместо `CurveLoop` берёт
    `IList<SketchedStairsCurveData>`, где у КАЖДОГО ребра свои высота и
    `SketchedCurveSlopeOption` (Sloped/Flat).  Это ТРЕТЬЯ КООРДИНАТА у
    контура, а CONTOUR — плоский подъязык по построению (канон, пункт 1:
    рёбра [(p0_mm, p1_mm, bulge)], вся тригонометрия на компиляции, z ставит
    потребитель).  Завести здесь по-рёберный уклон значило бы либо расширить
    CONTOUR (изменение ЯЗЫКА, не операции), либо завести ВТОРОЙ способ
    задавать профиль — ровно то, что канон запрещает.  ЧТО ОТКРЫВАЕТ: волна
    уклонов в CONTOUR; та же дверь нужна наклонному потолку, у которого уклон
    тоже назван отсутствующим.

`StairsRun.CreateSketchedRun` — ОТКАЗАНО.  Берёт ТРИ независимых списка
    кривых (граница, подступенки, линия пути), связанных между собой
    условиями, которых Autodesk не формулирует ни в одной из шести
    RevitAPI.xml: сколько подступенков должно быть, где именно они пересекают
    границу, обязана ли линия пути лежать внутри.  Ни одно из этих условий не
    проверяемо компилятором, а свидетель на РЕЗУЛЬТАТ пришлось бы строить на
    догадке о том, что Revit сделает с несогласованной тройкой.  Прямой и
    винтовой марши уже дают ФОРМУ марша одним осмысленным входом; эскизный
    марш — это чертёж, а не форма.  ЧТО ОТКРЫВАЕТ: живой замер на реальной
    лестнице — что именно `GetFootprintBoundary`/`GetStairsPath` отдают назад
    для эскизного марша, построенного руками.

`StairsRun.CreateSketchedRunWithSlopeData` — ОТКАЗАНО ДВАЖДЫ: она несёт обе
    названные выше причины сразу (тройка несогласуемых списков И по-рёберный
    уклон).  Отдельной причины ей не нужно, но и молча она не пропущена.

`StairsLanding.SetSketchedLandingBoundaryAndPath` — ОТКАЗАНО как ОПЕРАЦИЯ
    (6/6, существует).  Это ПРАВКА уже стоящей площадки, а не создание, то
    есть семейство `set_param`/`move_elements`, у которого свой контракт
    точных мутаций (`acceptance_mutation.py`: предикат точного конечного
    состояния, доказательства ElementId+UniqueId+VersionGuid).  Пристроить
    правку к создающей операции значило бы обойти этот контракт.  ЧТО
    ОТКРЫВАЕТ: волна правки эскизов, общая с проёмом и перекрытием.
"""
from __future__ import annotations

from kukai.ir import contour as C
from kukai.ir.authoring import (
    _AUTH_PREAMBLE, _cs, _document_binding_guard, _eid,
    _element_identity_guard, _indent, _program_stamp, _safe, _stamp_block,
    _stamp_readback, _with_program_helpers,
)
from kukai.ir.diag import (
    Diagnostic, EMIT_CONTOUR_HOLES, KirRefusal, PLAN_SOLO_OP)
from kukai.ir.emit_utils import cs_line_comment_fragment

#: Второе кольцо у площадки невыразимо: `CreateSketchedLanding` берёт ОДИН
#: `CurveLoop`, и второго аргумента-петли в подписи нет ни на одной из шести
#: версий.  Код тот же, что у проёма и
#: у балочной системы — общий `diag.EMIT_CONTOUR_HOLES`: один класс
#: дефекта — один код.

#: Ссылка внутри программы у соло-опа неразрешима по построению.  Реестр уже
#: отказывает ей на разборе (`ref_kinds=()`), это последний рубеж — тот же
#: приём и ТОТ ЖЕ КОД, что у `authoring._lvl_pin` для `create_stairs`: факт
#: один («оп владеет своей транзакцией и потому одинок»), значит и код один.
LANDING_SOLO_REF = PLAN_SOLO_OP


def _n(value: float) -> str:
    """Число в C#-литерал без потери разрядов (тот же приём, что в datum_emit)."""
    return repr(float(value) + 0.0)


def emit_stairs_landing_program(
    op: dict, ver: str, intent: str = "", *, stamp_scope: str = "",
    expected_document=None, expected_identities=None,
) -> str:
    """Отдельный шаблон ЦЕЛОЙ программы: площадка по эскизу на своей лестнице.

    Устройство один в один повторяет `authoring.emit_stairs_program`, и это
    НЕ копипаста ради симметрии, а один и тот же закон Revit: `StairsEditScope`
    владеет собственными транзакциями и не вкладывается в общую транзакцию
    программы (причина правила `KIR-L002`).  Общее с маршем — каркас области
    правки, предобработчик отказов на ОБЕИХ точках (транзакция и
    `StairsEditScope.Commit`), хвостовой `__KirPad`; своё — разрешение
    лестницы-хозяина, контур и свидетели.

    ПРЕДОБРАБОТЧИК ОТКАЗОВ СТОИТ ТАМ ЖЕ И ПО ТОЙ ЖЕ ПРИЧИНЕ (инцидент
    27.07.2026): модальное окно замораживает UI-поток Revit, и лестница,
    оставившая его после себя, убила мост на шести следующих вызовах подряд —
    для пользователя это «КУКИ завис после лестницы», навсегда.  Всё новое в
    этом семействе обязано жить внутри той же дисциплины, поэтому
    предупреждение снимается, а НАСТОЯЩАЯ ошибка по-прежнему отдаётся Revit.
    """
    oid = op["id"]
    s = _safe(oid)
    stamp = _program_stamp([op], stamp_scope)

    region = op["__region__"]
    # ДЫРКИ ОТКАЗЫВАЮТСЯ, А НЕ ОТБРАСЫВАЮТСЯ.  Молчаливое отбрасывание
    # построило бы СПЛОШНУЮ площадку там, где просили с вырезом.
    if region["holes"]:
        raise KirRefusal([Diagnostic(
            code=EMIT_CONTOUR_HOLES, op_id=oid, field_name="contour.holes",
            got=len(region["holes"]),
            message_ru=("create_stairs_landing: StairsLanding."
                        "CreateSketchedLanding принимает ОДНУ замкнутую петлю "
                        "— второго кольца в подписи нет ни на одной версии "
                        "2021-2026.  Вырез в площадке лестницы этой операцией "
                        "невыразим"))])

    edges = region["outer"]

    tgt = op["stairs"]
    if tgt.get("by") == "ref":
        # Соло-программа: предшественника не существует ни одного.  Реестр
        # уже отказал этому на разборе; здесь — последний рубеж.
        raise KirRefusal([Diagnostic(
            code=LANDING_SOLO_REF, op_id=oid, field_name="stairs",
            message_ru=("stairs: ref недопустим в соло-программе "
                        "create_stairs_landing — предшествующих опов у неё "
                        "нет по построению; назовите element_id лестницы"))])

    elev = float(op["elevation_mm"])

    # САМОЕ КОРОТКОЕ АВТОРСКОЕ РЕБРО — материал запрета вакуумности ниже.
    # Считается по ХОРДЕ, тем же `_dist`, которым CONTOUR меряет свои рёбра.
    min_edge = min(C._dist(p0, p1) for p0, p1, _b in edges)

    pre_doc_guard = _document_binding_guard(expected_document, rollback="")
    pre_identity_guard = _element_identity_guard(
        expected_identities, ver, rollback="")
    # После Start типизированный отказ допустим только если ОБА эффекта
    # доказанно сняты: транзакция вернула RolledBack, а scope после Cancel
    # больше не активен.  Guard-ы A5 получают именно этот fail-closed хвост.
    txn_rollback = (
        f"if (!__rollbackCancel_{s}(__t, __ess)) "
        f"throw new InvalidOperationException(\"transaction rollback / "
        f"stairs scope cancellation is unproven\"); ")
    txn_doc_guard_raw = _document_binding_guard(
        expected_document, rollback=txn_rollback)
    txn_doc_guard = (_indent(txn_doc_guard_raw, "        ") + "\n"
                     if txn_doc_guard_raw else "")
    txn_identity_guard_raw = _element_identity_guard(
        expected_identities, ver, rollback=txn_rollback,
        symbol_prefix="__kirLandingTxnBinding")
    txn_identity_guard = (_indent(txn_identity_guard_raw, "        ") + "\n"
                          if txn_identity_guard_raw else "")

    # КОНТУР ЛОЖИТСЯ НА СОБСТВЕННУЮ БАЗОВУЮ ОТМЕТКУ ЛЕСТНИЦЫ, А НЕ НА НОЛЬ.
    # Autodesk говорит про `GetFootprintBoundary` дословно: границу он отдаёт
    # «projected on the stairs base level», то есть плоскость площадки — это
    # плоскость лестницы, а не мировой ноль.  Петля, оставленная на нуле под
    # лестницей на +3.000, либо отвергается, либо строит площадку не там —
    # тот же шов и то же лечение, что у `create_beam_system` (профиль на
    # `MM(__lv.Elevation)`).  Отметка известна только в рантайме, поэтому в
    # `pt`-форматтер уезжает C#-ВЫРАЖЕНИЕ, а не число.
    zexpr = f"__sbz_{s}"
    fmt = (lambda x, y:
           f"P({round(x, C._EMIT_DECIMALS)}, {round(y, C._EMIT_DECIMALS)}, "
           f"{zexpr})")
    loop_cs = _indent(C.emit_loop_cs(edges, f"__ol_{s}", pt=fmt), "        ")

    # АВТОРСКИЙ КОНТУР, ВЫВЕЗЕННЫЙ В C# ОДИН РАЗ: свидетель сверяется с НИМ,
    # а не с тем, что сам же передал в вызов.  Тройка (начало, середина,
    # конец) — та же форма, что у заливки: по одним концам прямая и дуга
    # между теми же концами неразличимы, и стрелка дуги осталась бы
    # недоказанной.
    triples = C.edge_witness_triples(edges)
    n_edges = len(triples)

    def _arr(name: str, values) -> str:
        return (f"double[] __{name}_{s} = new double[] {{ "
                + ", ".join(_n(round(v, C._EMIT_DECIMALS)) for v in values)
                + " };")

    author_arrays = "\n".join([
        _arr("bx0", [t[0][0] for t in triples]),
        _arr("by0", [t[0][1] for t in triples]),
        _arr("bxm", [t[1][0] for t in triples]),
        _arr("bym", [t[1][1] for t in triples]),
        _arr("bx1", [t[2][0] for t in triples]),
        _arr("by1", [t[2][1] for t in triples]),
    ])

    # Один и тот же свидетель запускается до transaction commit и ПОСЛЕ
    # StairsEditScope.Commit на заново полученных из Document объектах. Это
    # не позволяет старому managed wrapper изображать живой результат.
    witness_cs = (
        f"Action<Autodesk.Revit.DB.Architecture.StairsLanding, "
        f"Autodesk.Revit.DB.Architecture.Stairs> __check_{s} = "
        f"(__landing_{s}, __stairs_{s}) =>\n"
        f"{{\n"
        f"    if (__landing_{s} == null)\n"
        f"    {{ __post.Add({_cs(oid + ': площадка не найдена при свежем чтении (identity)')}); return; }}\n"
        f"    if (__stairs_{s} == null)\n"
        f"        __post.Add({_cs(oid + ': лестница не найдена при свежем чтении (identity)')});\n"
        f"    try\n"
        f"    {{\n"
        f"        var __own_{s} = __landing_{s}.GetStairs();\n"
        f"        if (__stairs_{s} == null || __own_{s} == null || "
        f"__own_{s}.Id.ToString() != __stairs_{s}.Id.ToString())\n"
        f"            __post.Add({_cs(oid + ': площадка принадлежит не той лестнице (topology)')});\n"
        f"    }}\n"
        f"    catch {{ __post.Add({_cs(oid + ': владелец площадки нечитаем (topology)')}); }}\n"
        f"    bool __inSet_{s} = false;\n"
        f"    try\n"
        f"    {{\n"
        f"        if (__stairs_{s} != null)\n"
        f"            foreach (ElementId __li_{s} in __stairs_{s}.GetStairsLandings())\n"
        f"                if (__li_{s}.ToString() == __landing_{s}.Id.ToString()) "
        f"__inSet_{s} = true;\n"
        f"    }}\n"
        f"    catch {{ }}\n"
        f"    if (!__inSet_{s})\n"
        f"        __post.Add({_cs(oid + ': площадки нет в GetStairsLandings своей лестницы (topology)')});\n"
        f"    try {{ if (__landing_{s}.IsAutomaticLanding)\n"
        f"              __post.Add({_cs(oid + ': построена автоматическая площадка вместо эскизной (semantic)')}); }}\n"
        f"    catch {{ __post.Add({_cs(oid + ': признак автоматической площадки нечитаем (semantic)')}); }}\n"
        f"    int __bCurves_{s} = 0;\n"
        f"    bool __bRead_{s} = true; bool __bStray_{s} = false;\n"
        f"    int[] __bHit_{s} = new int[{n_edges}];\n"
        f"    try\n"
        f"    {{\n"
        f"        foreach (Curve __bc_{s} in __landing_{s}.GetFootprintBoundary())\n"
        f"        {{\n"
        f"            __bCurves_{s}++;\n"
        f"            double __ax_{s} = MM(__bc_{s}.GetEndPoint(0).X);\n"
        f"            double __ay_{s} = MM(__bc_{s}.GetEndPoint(0).Y);\n"
        f"            double __zx_{s} = MM(__bc_{s}.GetEndPoint(1).X);\n"
        f"            double __zy_{s} = MM(__bc_{s}.GetEndPoint(1).Y);\n"
        f"            double __mx_{s} = MM(__bc_{s}.Evaluate(0.5, true).X);\n"
        f"            double __my_{s} = MM(__bc_{s}.Evaluate(0.5, true).Y);\n"
        f"            bool __bOne_{s} = false;\n"
        f"            for (int __bk_{s} = 0; __bk_{s} < {n_edges}; __bk_{s}++)\n"
        f"            {{\n"
        f"                bool __bFwd_{s} = Math.Abs(__ax_{s} - __bx0_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__ay_{s} - __by0_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__zx_{s} - __bx1_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__zy_{s} - __by1_{s}[__bk_{s}]) <= __dt_{s};\n"
        f"                bool __bRev_{s} = Math.Abs(__ax_{s} - __bx1_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__ay_{s} - __by1_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__zx_{s} - __bx0_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__zy_{s} - __by0_{s}[__bk_{s}]) <= __dt_{s};\n"
        f"                if ((__bFwd_{s} || __bRev_{s})\n"
        f"                    && Math.Abs(__mx_{s} - __bxm_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__my_{s} - __bym_{s}[__bk_{s}]) <= __dt_{s})\n"
        f"                {{ __bHit_{s}[__bk_{s}]++; __bOne_{s} = true; break; }}\n"
        f"            }}\n"
        f"            if (!__bOne_{s}) __bStray_{s} = true;\n"
        f"        }}\n"
        f"    }}\n"
        f"    catch {{ __bRead_{s} = false; }}\n"
        f"    bool __bExact_{s} = true;\n"
        f"    for (int __bj_{s} = 0; __bj_{s} < {n_edges}; __bj_{s}++)\n"
        f"        if (__bHit_{s}[__bj_{s}] != 1) __bExact_{s} = false;\n"
        f"    if (!__bRead_{s})\n"
        f"        __post.Add({_cs(oid + ': граница площадки нечитаема — GetFootprintBoundary бросил (geometry)')});\n"
        f"    else if (__bCurves_{s} != {n_edges})\n"
        f"        __post.Add({_cs(oid + ': прочитано ')} + __bCurves_{s} + "
        f"{_cs(f' рёбер границы вместо {n_edges} (geometry)')});\n"
        f"    else if (__bStray_{s} || !__bExact_{s})\n"
        f"        __post.Add({_cs(oid + ': граница площадки не совпала с заданным контуром в плане (geometry)')});\n"
        f"    try\n"
        f"    {{\n"
        f"        double __gotE_{s} = MM(__landing_{s}.BaseElevation);\n"
        f"        if (Math.Abs(__gotE_{s} - __elevNorm_{s}) > __dt_{s})\n"
        f"            __post.Add({_cs(oid + ': отметка площадки не равна нормализованному кратному подступенка (geometry)')});\n"
        f"    }}\n"
        f"    catch {{ __post.Add({_cs(oid + ': отметка площадки нечитаема (geometry)')}); }}\n"
        f"}};\n")

    body = (
        f"{_AUTH_PREAMBLE}\n"
        f"// create_stairs_landing {cs_line_comment_fragment(oid)} — "
        f"sole-op program, StairsEditScope owns transactions\n"
        + pre_doc_guard
        + pre_identity_guard +
        # ── лестница-хозяин, ДО области правки ──────────────────────────
        f"Element __tg_{s} = doc.GetElement({_eid(tgt['value'], ver, oid)});\n"
        f"if (__tg_{s} == null)\n"
        f"    return __Refuse({_cs(oid)}, \"лестница не найдена (модель изменилась после grounding)\");\n"
        f"Autodesk.Revit.DB.Architecture.Stairs __st_{s} = "
        f"__tg_{s} as Autodesk.Revit.DB.Architecture.Stairs;\n"
        f"if (__st_{s} == null)\n"
        f"    return __Refuse({_cs(oid)}, \"указанный элемент — не лестница\");\n"
        # ── ДОПУСКИ И ГРАНИЦЫ — ИЗ ЧИСЕЛ САМОГО REVIT, ДО ТРАНЗАКЦИИ ────
        f"double __rh_{s} = MM(__st_{s}.ActualRiserHeight);\n"
        f"if (!(__rh_{s} > 0.0) || Double.IsNaN(__rh_{s}) || Double.IsInfinity(__rh_{s}))\n"
        f"    return __Refuse({_cs(oid)}, \"у лестницы нечитаема высота подступенка "
        f"(ActualRiserHeight не является конечным положительным числом)\");\n"
        # Точная нижняя граница отметки: Autodesk требует «equal to or greater
        # than half of the riser height».  Реестровая граница (0) слабее и
        # намеренно; настоящую ставит ЭТА строка, и она НАЗЫВАЕТ измеренное
        # число, а не отсылает автора к документации.
        f"if ({_n(elev)} < __rh_{s} / 2.0)\n"
        f"    return __Refuse({_cs(oid)}, \"elevation_mm = {_n(elev)} мм ниже половины "
        f"высоты подступенка этой лестницы (\" + Math.Round(__rh_{s} / 2.0, 1) + \" мм) — "
        f"Revit такую площадку не принимает\");\n"
        f"double __dt_{s} = MM(doc.Application.VertexTolerance) + "
        f"{_n(C.EMIT_COORD_QUANTUM_MM)};\n"
        # ЗАПРЕТ ВАКУУМНОСТИ — ОПРЕДЕЛЕНИЕ, А НЕ ВКУС: допуск, съедающий
        # половину самого короткого ребра, делает совпадение границы
        # непровалимым.  Проверка, которая не может провалиться, хуже
        # отсутствующей, поэтому здесь названный отказ, а не подпись.
        f"if (2.0 * __dt_{s} >= {_n(min_edge)})\n"
        f"    return __Refuse({_cs(oid)}, \"выведенный допуск границы (\" + "
        f"Math.Round(__dt_{s}, 3) + \" мм) не меньше половины самого короткого ребра "
        f"контура (ребро {_n(round(min_edge, 2))} мм, половина "
        f"{_n(round(min_edge / 2.0, 2))} мм) — свидетель границы не смог бы "
        f"провалиться\");\n"
        # Revit округляет BaseElevation к кратному ActualRiserHeight. Мы не
        # угадываем направление скрытого округления: принимаем только уже
        # краткое авторское значение, а иначе называем двух соседей.
        f"double __elevQ_{s} = {_n(elev)} / __rh_{s};\n"
        f"double __elevK_{s} = Math.Round(__elevQ_{s}, MidpointRounding.AwayFromZero);\n"
        f"if (__elevK_{s} < 1.0) __elevK_{s} = 1.0;\n"
        f"double __elevNorm_{s} = __elevK_{s} * __rh_{s};\n"
        f"double __elevLower_{s} = Math.Max(__rh_{s}, Math.Floor(__elevQ_{s}) * __rh_{s});\n"
        f"double __elevUpper_{s} = Math.Max(__rh_{s}, Math.Ceiling(__elevQ_{s}) * __rh_{s});\n"
        f"if (Math.Abs({_n(elev)} - __elevNorm_{s}) > __dt_{s})\n"
        f"    return __Refuse({_cs(oid)}, \"elevation_mm должна быть целым кратным "
        f"ActualRiserHeight; ближайшие кандидаты: \" + "
        f"Math.Round(__elevLower_{s}, 3) + \" мм и \" + "
        f"Math.Round(__elevUpper_{s}, 3) + \" мм\");\n"
        f"{author_arrays}\n"
        f"double __sbz_{s} = MM(__st_{s}.BaseElevation);\n"
        f"ElementId __stairsId_{s} = __st_{s}.Id;\n"
        + witness_cs +
        # ── область правки ─────────────────────────────────────────────
        f"var __ess = new StairsEditScope(doc, "
        f"{_cs(('KIR landing: ' + (intent or oid))[:60])});\n"
        f"if (!__ess.IsPermitted)\n"
        f"    return __Refuse({_cs(oid)}, \"StairsEditScope запрещён текущим состоянием документа\");\n"
        # Cancel считается доказанным лишь после перехода active -> inactive.
        # Уже неактивный scope не выдаётся за «успешно отменённый».
        f"Func<StairsEditScope, bool> __cancel_{s} = (__scope_{s}) =>\n"
        f"{{\n"
        f"    try\n"
        f"    {{\n"
        f"        if (!__scope_{s}.IsActive) return false;\n"
        f"        __scope_{s}.Cancel();\n"
        f"        return !__scope_{s}.IsActive;\n"
        f"    }}\n"
        f"    catch {{ return false; }}\n"
        f"}};\n"
        f"Func<Transaction, StairsEditScope, bool> __rollbackCancel_{s} = "
        f"(__transaction_{s}, __scope_{s}) =>\n"
        f"{{\n"
        f"    TransactionStatus __rollbackStatus_{s};\n"
        f"    try {{ __rollbackStatus_{s} = __transaction_{s}.RollBack(); }}\n"
        f"    catch {{ return false; }}\n"
        f"    if (__rollbackStatus_{s} != TransactionStatus.RolledBack) return false;\n"
        f"    return __cancel_{s}(__scope_{s});\n"
        f"}};\n"
        f"ElementId __sid_{s} = null;\n"
        f"ElementId __landingId_{s} = null;\n"
        f"Autodesk.Revit.DB.Architecture.StairsLanding __lg_{s} = null;\n"
        f"try\n"
        f"{{\n"
        f"    __sid_{s} = __ess.Start(__stairsId_{s});\n"
        # Start документирован как возвращающий тот же stairs id. Несовпадение
        # — нарушение API-контракта: scope снимается, но результат не
        # превращается в безопасный отказ без транзакционного rollback.
        f"    if (__sid_{s} == null || __sid_{s}.ToString() != __stairsId_{s}.ToString())\n"
        f"    {{\n"
        f"        if (!__cancel_{s}(__ess))\n"
        f"            throw new InvalidOperationException(\"StairsEditScope.Start target mismatch and cancellation is unproven\");\n"
        f"        throw new InvalidOperationException(\"StairsEditScope.Start returned a different stairs id\");\n"
        f"    }}\n"
        f"    using (Transaction __t = new Transaction(doc, \"KIR: stairs landing\"))\n"
        f"    {{\n"
        f"        var __startStatus = __t.Start();\n"
        f"        if (__startStatus != TransactionStatus.Started)\n"
        f"        {{\n"
        f"            if (!__cancel_{s}(__ess))\n"
        f"                throw new InvalidOperationException(\"transaction did not start and scope cancellation is unproven\");\n"
        f"            throw new InvalidOperationException(\"transaction start status: \" + __startStatus.ToString());\n"
        f"        }}\n"
        f"        var __fho = __t.GetFailureHandlingOptions();\n"
        f"        __fho.SetFailuresPreprocessor(new __KirStairsFailures());\n"
        f"        __fho.SetForcedModalHandling(false);\n"
        f"        __fho.SetClearAfterRollback(true);\n"
        f"        __t.SetFailureHandlingOptions(__fho);\n"
        + txn_doc_guard
        + txn_identity_guard
        + f"{loop_cs}\n"
        # Autodesk перечисляет для этого вызова пять разных ArgumentException
        # (петля не замкнута, кривая не Line/Arc, у лестницы нет типа
        # площадки, …) плюс ArgumentOutOfRangeException по отметке.  Ни один
        # не предсказуем из снапшота, и все обязаны стать НАЗВАННЫМ отказом,
        # а не «внутренней ошибкой».
        f"        try\n"
        f"        {{\n"
        f"            __lg_{s} = Autodesk.Revit.DB.Architecture.StairsLanding"
        f".CreateSketchedLanding(doc, __sid_{s}, __ol_{s}, U(__elevNorm_{s}));\n"
        f"        }}\n"
        f"        catch (Exception __ex_{s})\n"
        f"        {{\n"
        f"            if (!__rollbackCancel_{s}(__t, __ess))\n"
        f"                throw new InvalidOperationException(\"CreateSketchedLanding failed and rollback/cancel is unproven\", __ex_{s});\n"
        f"            return __Refuse({_cs(oid)}, \"CreateSketchedLanding: \" + __ex_{s}.Message);\n"
        f"        }}\n"
        f"        if (__lg_{s} == null)\n"
        f"        {{\n"
        f"            if (!__rollbackCancel_{s}(__t, __ess))\n"
        f"                throw new InvalidOperationException(\"CreateSketchedLanding returned null and rollback/cancel is unproven\");\n"
        f"            return __Refuse({_cs(oid)}, \"CreateSketchedLanding вернул null\");\n"
        f"        }}\n"
        f"        doc.Regenerate();\n"
        f"        " + _stamp_block(f"__lg_{s}", f"{stamp}:{oid}") + "\n"
        f"        __landingId_{s} = __lg_{s}.Id;\n"
        # ── свидетель внутри транзакции: нарушение откатывает всё ───────
        f"        __post.Clear();\n"
        f"        __check_{s}(__lg_{s}, __st_{s});\n"
        f"        if (__post.Count > 0)\n"
        f"        {{\n"
        f"            if (!__rollbackCancel_{s}(__t, __ess))\n"
        f"                throw new InvalidOperationException(\"postcondition failed and rollback/cancel is unproven\");\n"
        f"            var __er = new Dictionary<string, object>();\n"
        f"            __er[\"error\"] = \"postconditions_violated\";\n"
        f"            __er[\"violations\"] = new List<string>(__post);\n"
        f"            return __er;\n"
        f"        }}\n"
        f"        var __commitStatus = __t.Commit();\n"
        f"        if (__commitStatus != TransactionStatus.Committed)\n"
        f"        {{\n"
        f"            if (!__cancel_{s}(__ess))\n"
        f"                throw new InvalidOperationException(\"transaction commit was not Committed and scope cancellation is unproven\");\n"
        f"            throw new InvalidOperationException(\"transaction commit status: \" + __commitStatus.ToString());\n"
        f"        }}\n"
        f"    }}\n"
        f"    __ess.Commit(new __KirStairsFailures());\n"
        f"    if (__ess.IsActive)\n"
        f"        throw new InvalidOperationException(\"StairsEditScope.Commit returned but scope is still active\");\n"
        f"}}\n"
        f"catch (Exception __scopeEx_{s})\n"
        f"{{\n"
        f"    bool __cleanup_{s} = true;\n"
        f"    try\n"
        f"    {{\n"
        f"        if (__ess.IsActive)\n"
        f"        {{ __ess.Cancel(); __cleanup_{s} = !__ess.IsActive; }}\n"
        f"    }}\n"
        f"    catch {{ __cleanup_{s} = false; }}\n"
        f"    if (!__cleanup_{s})\n"
        f"        throw new InvalidOperationException(\"stairs scope cleanup is unproven\", __scopeEx_{s});\n"
        f"    throw;\n"
        f"}}\n"
        # ── СВЕЖИЙ свидетель после закрытия области правки ──────────────
        f"var __freshSt_{s} = doc.GetElement(__stairsId_{s}) as "
        f"Autodesk.Revit.DB.Architecture.Stairs;\n"
        f"var __freshLg_{s} = __landingId_{s} == null ? null : "
        f"doc.GetElement(__landingId_{s}) as "
        f"Autodesk.Revit.DB.Architecture.StairsLanding;\n"
        f"__post.Clear();\n"
        f"__check_{s}(__freshLg_{s}, __freshSt_{s});\n"
        f"// witness (fresh post-scope readback)\n"
        f"var __rb_{s} = new Dictionary<string, object>();\n"
        f"__rb_{s}[\"stairs_id\"] = __stairsId_{s}.ToString();\n"
        f"if (__landingId_{s} != null) __rb_{s}[\"id\"] = __landingId_{s}.ToString();\n"
        f"if (__freshLg_{s} != null)\n"
        f"{{\n"
        + _indent(_stamp_readback(f"__freshLg_{s}", f"__rb_{s}"), "    ") + "\n"
        f"    try {{ __rb_{s}[\"elevation_requested_mm\"] = {_n(elev)};\n"
        f"          __rb_{s}[\"elevation_normalized_mm\"] = Math.Round(__elevNorm_{s}, 3);\n"
        f"          __rb_{s}[\"elevation_built_mm\"] = "
        f"Math.Round(MM(__freshLg_{s}.BaseElevation), 3);\n"
        f"          __rb_{s}[\"riser_height_mm\"] = Math.Round(__rh_{s}, 2); }} catch {{ }}\n"
        f"    __rb_{s}[\"elevation_lower_candidate_mm\"] = Math.Round(__elevLower_{s}, 3);\n"
        f"    __rb_{s}[\"elevation_upper_candidate_mm\"] = Math.Round(__elevUpper_{s}, 3);\n"
        f"    try {{ __rb_{s}[\"thickness_mm\"] = "
        f"Math.Round(MM(__freshLg_{s}.Thickness), 2); }} catch {{ }}\n"
        f"    try {{ __rb_{s}[\"is_automatic\"] = __freshLg_{s}.IsAutomaticLanding; }} catch {{ }}\n"
        f"    try {{ __rb_{s}[\"boundary_tolerance_mm\"] = "
        f"Math.Round(__dt_{s}, 3); }} catch {{ }}\n"
        f"    try {{ var __rl_{s} = __freshSt_{s} == null ? null : "
        f"__freshSt_{s}.GetStairsLandings();\n"
        f"          __rb_{s}[\"landings\"] = __rl_{s} == null ? 0 : __rl_{s}.Count; }} catch {{ }}\n"
        f"}}\n"
        f"__results[{_cs(oid)}] = __rb_{s};\n"
        f"__results[\"ok\"] = true;\n"
        # После commit эффект уже произошёл. Нарушение здесь — committed but
        # unverified, а не ложный X004 «rolled back» и не повод повторять.
        f"if (__post.Count > 0)\n"
        f"    __results[\"postcondition_violations\"] = new List<string>(__post);\n"
        f"return __results;\n"
        f"}}\n"
        f"\n"
        # ТОТ ЖЕ СВОД, ЧТО У `__KirMainFailures` И У МАРША: предупреждение
        # снимаем, чтобы оно не всплыло диалогом и не заморозило UI-поток
        # Revit; настоящую ОШИБКУ по-прежнему отдаём Revit.  Обработчик стоит
        # и на транзакции, и на `StairsEditScope.Commit` — предупреждение
        # может подняться уже вне транзакции.
        f"private class __KirStairsFailures : IFailuresPreprocessor\n"
        f"{{\n"
        f"    public FailureProcessingResult PreprocessFailures(FailuresAccessor __fa)\n"
        f"    {{\n"
        f"        foreach (var __f in __fa.GetFailureMessages())\n"
        f"            if (__f.GetSeverity() == FailureSeverity.Warning)\n"
        f"                __fa.DeleteWarning(__f);\n"
        f"        return FailureProcessingResult.Continue;\n"
        f"    }}\n"
        f"}}\n"
        f"\n"
        f"private static class __KirPad\n"
        f"{{  // pad scope: the fixed wrapper footer closes __KirPad, UserCode, namespace"
    )
    return _with_program_helpers(body)
