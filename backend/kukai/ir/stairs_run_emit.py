"""stairs_run_emit — ВТОРОЙ МАРШ УЖЕ СТОЯЩЕЙ ЛЕСТНИЦЫ (волна лестниц, 15.08.2026).

ЗАЧЕМ ЭТА ОПЕРАЦИЯ СУЩЕСТВУЕТ — ЧИСЛО, СНЯТОЕ НА НАСТОЯЩЕМ ДОМЕ.
`LEN_AR_ME_R24`, жилой дом владельца:

    всего лестниц                        19
    выразимо KIR до этой волны            2   (10.5 %)
    НЕвыразимо                           17   (89.5 %)
    маршей на лестницу: 1м:2 · 2м:4 · 3м:2 · 4м:10 · 5м:1   — МОДА ЧЕТЫРЕ МАРША
    61 марш · 40 площадок · 522 ограждения на 19 лестниц

`create_stairs` эмитирует `Stairs.Create` плюс РОВНО ОДИН марш
(`authoring.emit_stairs_program`), `create_stairs_landing` садится на уже
стоящую лестницу.  Марш + площадка были выразимы двумя программами; марш +
площадка + марш — НЕТ, потому что опа, добавляющего ВТОРОЙ марш, в реестре не
было.  Дыра в ЯЗЫКЕ, не в документации, и она держала жилой дом невыразимым на
89.5 %.

────────────────────────────────────────────────────────────────────────────
ЗАМЕР API (компиляция на :52412 против настоящих сборок 2021-2026, 15.08.2026;
арбитр — компилятор, а не RevitAPI.xml; это правило проверки API)
────────────────────────────────────────────────────────────────────────────

  StairsRun.CreateStraightRun(Document, ElementId, Line,
             StairsRunJustification)                              → 6/6
  StairsRunJustification.Center / .Left / .Right                  → 6/6 каждый
  StairsRun.BaseElevation / .TopElevation / .Height               → 6/6
  StairsRun.GetStairs() / .GetStairsPath() / .ActualRunWidth      → 6/6
  Stairs.GetStairsRuns() / .BaseElevation / .ActualRiserHeight    → 6/6

RevitAPI.xml у `CreateStraightRun` (все шесть версий, дословно):
  ArgumentException — «The stairsId is not a valid stairs element. -or- The
      input locationPath is not a bound line. -or- The input locationPath is
      not a valid location path line for straight run. -or- The locationPath
      is not valid line used as stairs path (probably it's too short).»
  InvalidOperationException — «The stairs element represented by stairsId is
      not in an active StairsEditScope.  New components cannot be added to it.»

────────────────────────────────────────────────────────────────────────────
ПОЧЕМУ ОТДЕЛЬНЫЙ ОП, А НЕ МНОЖЕСТВЕННЫЙ ОПЕРАНД У `create_stairs`
────────────────────────────────────────────────────────────────────────────
Развилка решена ЗАМЕРОМ API, а не вкусом.  `CreateStraightRun` первым
аргументом берёт `stairsId` — то есть добавляет марш к УЖЕ СУЩЕСТВУЮЩЕЙ
лестнице, и требует активной области правки.  Плечо «маршей» у `create_stairs`
описывало бы только случай «лестница создаётся сейчас» и было бы НЕВЫРАЗИМО
для самого частого случая настоящей работы — лестница в документе уже стоит.
Форма API и форма задачи здесь совпадают, и совпадение это не случайно: марш
в Revit есть КОМПОНЕНТ лестницы, а не её параметр.

СОЛО-ОП, И ЭТО ЗАМЕР, А НЕ СИММЕТРИЯ С ПЛОЩАДКОЙ.  Фраза
`InvalidOperationException` выше — та же самая, что у `CreateSketchedLanding`:
область правки обязательна.  Две области одновременно Revit не открывает
(«there already is a stairs edit mode active in the document»), поэтому
соседство двух лестничных опов невыразимо ПО REVIT.  Отсюда `spec.SOLO_OPS`.

────────────────────────────────────────────────────────────────────────────
ОТМЕТКА ОТНОСИТЕЛЬНАЯ, И У ЭТОГО ДВЕ ПРИЧИНЫ, А НЕ ОДНА
────────────────────────────────────────────────────────────────────────────
1. `CreateStraightRun` НЕ ИМЕЕТ аргумента отметки вовсе — её несёт Z точек
   `locationPath`.  Абсолютный Z потребовал бы знать `Stairs.BaseElevation` на
   КОМПИЛЯЦИИ, то есть живой Revit там, где его нет.
2. Автор мыслит «второй марш начинается на площадке», то есть ОТ ЛЕСТНИЦЫ.
   Ровно так же устроена отметка площадки, и одинаковый смысл выражен
   одинаково.

`BaseElevation` читает C# в рантайме; сетка допустимых отметок — целое кратное
`ActualRiserHeight` ЭТОЙ лестницы, и марш, начинающийся посреди подступенка,
получает ТИПИЗИРОВАННЫЙ ОТКАЗ с двумя ближайшими кандидатами, а не
исключение.  Приём и обоснование — те же, что у площадки.

🔴 ЖИВЬЁМ ЭТОТ ОП НЕ ПРОВЕРЯЛСЯ, И ПРИЧИНА НАЗВАНА.  15.08.2026 `create_stairs`
на настоящем доме владельца закоммитилась и ЗАБЛОКИРОВАЛА поток Ревита
модальным окном, которое некому нажать; окно снимал владелец руками.  Инцидент
лестниц, считавшийся закрытым, для ЭТОГО пути не закрыт, поэтому вся волна
офлайновая: реестр, эмиссия, ворота шести версий, голден.  Живое доказательство
— отдельным заходом, после разбора модального окна.  Строка в `tool_doc`
UNPROVEN стоит именно с этой причиной, а не по забывчивости.
"""
from __future__ import annotations

from kukai.ir.authoring import (
    _AUTH_PREAMBLE, _cs, _document_binding_guard, _eid,
    _element_identity_guard, _indent, _program_stamp, _safe, _stamp_block,
    _stamp_readback, _with_program_helpers,
)
from kukai.ir.diag import Diagnostic, KirRefusal, PLAN_SOLO_OP
from kukai.ir.emit_utils import cs_line_comment_fragment

#: Ссылка внутри программы у соло-опа неразрешима по построению — тот же код и
#: тот же довод, что у площадки: факт один («оп владеет своей транзакцией и
#: потому одинок»), значит и код один.
RUN_SOLO_REF = PLAN_SOLO_OP

#: ЗАКРЫТОЕ ПЕРЕЧИСЛЕНИЕ REVIT -> ИМЯ ЧЛЕНА, А НЕ ЧИСЛО.
#: Канон этого дерева прямо требует отдавать в C# ИМЯ члена enum: тогда
#: авторитетом становятся сборки Revit (опечатка не собирается), а не наша
#: таблица.  Голым числом в реестре пишет ровно один жилец —
#: `WALL_LOCATION_LINE_ORDINALS`, и он назван в каноне как единственный
#: оставшийся.  Второго не заводим.
JUSTIFICATION_MEMBERS: dict[str, str] = {
    "center": "Center",
    "left": "Left",
    "right": "Right",
}


def _n(value: float) -> str:
    """Число в C#-литерал без потери разрядов (тот же приём, что у площадки)."""
    return repr(float(value) + 0.0)


def emit_stairs_run_program(
    op: dict, ver: str, intent: str = "", *, stamp_scope: str = "",
    expected_document=None, expected_identities=None,
) -> str:
    """Отдельный шаблон ЦЕЛОЙ программы: второй марш на своей лестнице.

    Устройство повторяет `stairs_landing_emit.emit_stairs_landing_program`, и
    это НЕ копипаста ради симметрии, а один и тот же закон Revit:
    `StairsEditScope` владеет собственными транзакциями и не вкладывается в
    общую.  Общее — форма области правки (Start на существующей лестнице,
    двойной свидетель, `StairsEditScope.Commit`); своё — вызов фабрики, разбор
    оси марша и свидетель по пути марша.
    """
    oid = op["id"]
    s = _safe(oid)
    stamp = _program_stamp([op], stamp_scope)

    tgt = op["stairs"]
    if tgt.get("by") == "ref":
        raise KirRefusal([Diagnostic(
            code=RUN_SOLO_REF, op_id=oid, field_name="stairs",
            message_ru=("stairs: ref недопустим в соло-программе "
                        "create_stairs_run — предшествующих опов у неё нет "
                        "по построению; назовите element_id лестницы"))])

    p0 = op["p0_mm"]
    p1 = op["p1_mm"]
    elev = float(op["base_elevation_mm"])
    justification = JUSTIFICATION_MEMBERS[op.get("justification", "center")]

    pre_doc_guard = _document_binding_guard(expected_document, rollback="")
    pre_identity_guard = _element_identity_guard(
        expected_identities, ver, rollback="")
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
        symbol_prefix="__kirRunTxnBinding")
    txn_identity_guard = (_indent(txn_identity_guard_raw, "        ") + "\n"
                          if txn_identity_guard_raw else "")

    # СВИДЕТЕЛЬ ЧИТАЕТ РЕЗУЛЬТАТ, А НЕ ФАКТ ВЫЗОВА.  Тот же двойной запуск,
    # что у площадки: внутри транзакции (нарушение откатывает всё) и ПОСЛЕ
    # `StairsEditScope.Commit` на заново прочитанных из документа объектах —
    # старый managed wrapper не должен изображать живой результат.
    #
    # Z НЕ СРАВНИВАЕТСЯ по пути марша: его назначает Revit от базы лестницы,
    # и требовать от него авторского числа значило бы гонять свидетеля за
    # тем, чего Revit не обещает (ровно ошибка уровня балки, записанная в
    # каноне).  Отметка марша проверяется ОТДЕЛЬНО, своим `BaseElevation`.
    witness_cs = (
        f"Action<Autodesk.Revit.DB.Architecture.StairsRun, "
        f"Autodesk.Revit.DB.Architecture.Stairs> __check_{s} = "
        f"(__run_{s}, __stairs_{s}) =>\n"
        f"{{\n"
        f"    if (__run_{s} == null)\n"
        f"    {{ __post.Add({_cs(oid + ': марш не найден при свежем чтении (identity)')}); return; }}\n"
        f"    if (__stairs_{s} == null)\n"
        f"        __post.Add({_cs(oid + ': лестница не найдена при свежем чтении (identity)')});\n"
        f"    try\n"
        f"    {{\n"
        f"        var __own_{s} = __run_{s}.GetStairs();\n"
        f"        if (__stairs_{s} == null || __own_{s} == null || "
        f"__own_{s}.Id.ToString() != __stairs_{s}.Id.ToString())\n"
        f"            __post.Add({_cs(oid + ': марш принадлежит не той лестнице (topology)')});\n"
        f"    }}\n"
        f"    catch {{ __post.Add({_cs(oid + ': владелец марша нечитаем (topology)')}); }}\n"
        f"    bool __inSet_{s} = false;\n"
        f"    try\n"
        f"    {{\n"
        f"        if (__stairs_{s} != null)\n"
        f"            foreach (ElementId __ri_{s} in __stairs_{s}.GetStairsRuns())\n"
        f"                if (__ri_{s}.ToString() == __run_{s}.Id.ToString()) "
        f"__inSet_{s} = true;\n"
        f"    }}\n"
        f"    catch {{ }}\n"
        f"    if (!__inSet_{s})\n"
        f"        __post.Add({_cs(oid + ': марша нет в GetStairsRuns своей лестницы (topology)')});\n"
        # ── ось марша в ПЛАНЕ: концы, без Z ─────────────────────────────
        f"    bool __pathRead_{s} = false; bool __pathHit_{s} = false;\n"
        f"    try\n"
        f"    {{\n"
        f"        foreach (Curve __pc_{s} in __run_{s}.GetStairsPath())\n"
        f"        {{\n"
        f"            __pathRead_{s} = true;\n"
        f"            double __ax_{s} = MM(__pc_{s}.GetEndPoint(0).X);\n"
        f"            double __ay_{s} = MM(__pc_{s}.GetEndPoint(0).Y);\n"
        f"            double __zx_{s} = MM(__pc_{s}.GetEndPoint(1).X);\n"
        f"            double __zy_{s} = MM(__pc_{s}.GetEndPoint(1).Y);\n"
        f"            bool __fwd_{s} = Math.Abs(__ax_{s} - {_n(p0[0])}) <= __dt_{s}\n"
        f"                && Math.Abs(__ay_{s} - {_n(p0[1])}) <= __dt_{s}\n"
        f"                && Math.Abs(__zx_{s} - {_n(p1[0])}) <= __dt_{s}\n"
        f"                && Math.Abs(__zy_{s} - {_n(p1[1])}) <= __dt_{s};\n"
        f"            bool __rev_{s} = Math.Abs(__ax_{s} - {_n(p1[0])}) <= __dt_{s}\n"
        f"                && Math.Abs(__ay_{s} - {_n(p1[1])}) <= __dt_{s}\n"
        f"                && Math.Abs(__zx_{s} - {_n(p0[0])}) <= __dt_{s}\n"
        f"                && Math.Abs(__zy_{s} - {_n(p0[1])}) <= __dt_{s};\n"
        f"            if (__fwd_{s} || __rev_{s}) __pathHit_{s} = true;\n"
        f"        }}\n"
        f"    }}\n"
        f"    catch {{ __pathRead_{s} = false; }}\n"
        f"    if (!__pathRead_{s})\n"
        f"        __post.Add({_cs(oid + ': путь марша нечитаем (geometry)')});\n"
        f"    else if (!__pathHit_{s})\n"
        f"        __post.Add({_cs(oid + ': ось марша в плане не совпала с заявленной (geometry)')});\n"
        # ── отметка низа марша ──────────────────────────────────────────
        f"    try\n"
        f"    {{\n"
        f"        double __built_{s} = MM(__run_{s}.BaseElevation);\n"
        f"        if (Math.Abs(__built_{s} - (__sbz_{s} + __elevNorm_{s})) > __dt_{s})\n"
        f"            __post.Add({_cs(oid + ': отметка низа марша не совпала с заявленной (geometry)')});\n"
        f"    }}\n"
        f"    catch {{ __post.Add({_cs(oid + ': отметка марша нечитаема (geometry)')}); }}\n"
        f"}};\n")

    body = (
        f"{_AUTH_PREAMBLE}\n"
        f"// create_stairs_run {cs_line_comment_fragment(oid)} — "
        f"sole-op program, StairsEditScope owns transactions\n"
        + pre_doc_guard + pre_identity_guard +
        # ── лестница-хозяин, ДО области правки ──────────────────────────
        f"Element __tg_{s} = doc.GetElement({_eid(tgt['value'], ver, oid)});\n"
        f"if (__tg_{s} == null)\n"
        f"    return __Refuse({_cs(oid)}, \"лестница не найдена (модель изменилась после grounding)\");\n"
        f"Autodesk.Revit.DB.Architecture.Stairs __st_{s} = "
        f"__tg_{s} as Autodesk.Revit.DB.Architecture.Stairs;\n"
        f"if (__st_{s} == null)\n"
        f"    return __Refuse({_cs(oid)}, \"указанный элемент — не лестница\");\n"
        # Допуск ВЫВОДИТСЯ из документа, а не назначается реестром: тот же
        # приём и та же причина, что у площадки.
        f"double __dt_{s} = MM(doc.Application.VertexTolerance) + 0.5;\n"
        # СЕТКА ОТМЕТОК — ЖИВАЯ ВЕЛИЧИНА ЭТОЙ ЛЕСТНИЦЫ, и отказ НАЗЫВАЕТ
        # ближайшие законные значения.  Марш, начинающийся посреди
        # подступенка, — не лестница; но выдумать шаг на компиляции нельзя.
        f"double __rh_{s} = MM(__st_{s}.ActualRiserHeight);\n"
        f"if (!(__rh_{s} > 0.0))\n"
        f"    return __Refuse({_cs(oid)}, \"высота подступенка лестницы "
        f"нечитаема или ноль — отметку марша не к чему привязать\");\n"
        f"double __elevQ_{s} = {_n(elev)} / __rh_{s};\n"
        f"double __elevNorm_{s} = Math.Round(__elevQ_{s}) * __rh_{s};\n"
        f"double __elevLower_{s} = Math.Floor(__elevQ_{s}) * __rh_{s};\n"
        f"double __elevUpper_{s} = Math.Ceiling(__elevQ_{s}) * __rh_{s};\n"
        f"if (Math.Abs({_n(elev)} - __elevNorm_{s}) > __dt_{s})\n"
        f"    return __Refuse({_cs(oid)}, \"base_elevation_mm должна быть "
        f"целым кратным ActualRiserHeight; ближайшие кандидаты: \" + "
        f"Math.Round(__elevLower_{s}, 3) + \" мм и \" + "
        f"Math.Round(__elevUpper_{s}, 3) + \" мм\");\n"
        f"double __sbz_{s} = MM(__st_{s}.BaseElevation);\n"
        f"ElementId __stairsId_{s} = __st_{s}.Id;\n"
        + witness_cs +
        # ── область правки ─────────────────────────────────────────────
        f"var __ess = new StairsEditScope(doc, "
        f"{_cs(('KIR run: ' + (intent or oid))[:60])});\n"
        f"if (!__ess.IsPermitted)\n"
        f"    return __Refuse({_cs(oid)}, \"StairsEditScope запрещён текущим состоянием документа\");\n"
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
        f"ElementId __runId_{s} = null;\n"
        f"Autodesk.Revit.DB.Architecture.StairsRun __rn_{s} = null;\n"
        f"try\n"
        f"{{\n"
        f"    __sid_{s} = __ess.Start(__stairsId_{s});\n"
        f"    if (__sid_{s} == null || __sid_{s}.ToString() != __stairsId_{s}.ToString())\n"
        f"    {{\n"
        f"        if (!__cancel_{s}(__ess))\n"
        f"            throw new InvalidOperationException(\"StairsEditScope.Start target mismatch and cancellation is unproven\");\n"
        f"        throw new InvalidOperationException(\"StairsEditScope.Start returned a different stairs id\");\n"
        f"    }}\n"
        f"    using (Transaction __t = new Transaction(doc, \"KIR: stairs run\"))\n"
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
        + txn_doc_guard + txn_identity_guard +
        # Z оси — ОТ ЛЕСТНИЦЫ, а не от автора: см. шапку модуля.
        f"        Line __path_{s} = Line.CreateBound(\n"
        f"            new XYZ(U({_n(p0[0])}), U({_n(p0[1])}), "
        f"U(__sbz_{s} + __elevNorm_{s})),\n"
        f"            new XYZ(U({_n(p1[0])}), U({_n(p1[1])}), "
        f"U(__sbz_{s} + __elevNorm_{s})));\n"
        # Autodesk перечисляет для этого вызова четыре разных ArgumentException
        # (не bound line, не годная ось прямого марша, слишком короткая) —
        # ни один не предсказуем из снапшота, и все обязаны стать НАЗВАННЫМ
        # отказом, а не «внутренней ошибкой».
        f"        try\n"
        f"        {{\n"
        f"            __rn_{s} = Autodesk.Revit.DB.Architecture.StairsRun"
        f".CreateStraightRun(doc, __sid_{s}, __path_{s}, "
        f"Autodesk.Revit.DB.Architecture.StairsRunJustification.{justification});\n"
        f"        }}\n"
        f"        catch (Exception __ex_{s})\n"
        f"        {{\n"
        f"            if (!__rollbackCancel_{s}(__t, __ess))\n"
        f"                throw new InvalidOperationException(\"CreateStraightRun failed and rollback/cancel is unproven\", __ex_{s});\n"
        f"            return __Refuse({_cs(oid)}, \"CreateStraightRun: \" + __ex_{s}.Message);\n"
        f"        }}\n"
        f"        if (__rn_{s} == null)\n"
        f"        {{\n"
        f"            if (!__rollbackCancel_{s}(__t, __ess))\n"
        f"                throw new InvalidOperationException(\"CreateStraightRun returned null and rollback/cancel is unproven\");\n"
        f"            return __Refuse({_cs(oid)}, \"CreateStraightRun вернул null\");\n"
        f"        }}\n"
        f"        doc.Regenerate();\n"
        f"        " + _stamp_block(f"__rn_{s}", f"{stamp}:{oid}") + "\n"
        f"        __runId_{s} = __rn_{s}.Id;\n"
        f"        __post.Clear();\n"
        f"        __check_{s}(__rn_{s}, __st_{s});\n"
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
        f"var __freshRn_{s} = __runId_{s} == null ? null : "
        f"doc.GetElement(__runId_{s}) as "
        f"Autodesk.Revit.DB.Architecture.StairsRun;\n"
        f"__post.Clear();\n"
        f"__check_{s}(__freshRn_{s}, __freshSt_{s});\n"
        f"// witness (fresh post-scope readback)\n"
        f"var __rb_{s} = new Dictionary<string, object>();\n"
        f"__rb_{s}[\"stairs_id\"] = __stairsId_{s}.ToString();\n"
        f"if (__runId_{s} != null) __rb_{s}[\"id\"] = __runId_{s}.ToString();\n"
        f"if (__freshRn_{s} != null)\n"
        f"{{\n"
        + _indent(_stamp_readback(f"__freshRn_{s}", f"__rb_{s}"), "    ") + "\n"
        f"    try {{ __rb_{s}[\"base_elevation_requested_mm\"] = {_n(elev)};\n"
        f"          __rb_{s}[\"base_elevation_normalized_mm\"] = Math.Round(__elevNorm_{s}, 3);\n"
        f"          __rb_{s}[\"base_elevation_built_mm\"] = "
        f"Math.Round(MM(__freshRn_{s}.BaseElevation), 3);\n"
        f"          __rb_{s}[\"riser_height_mm\"] = Math.Round(__rh_{s}, 2); }} catch {{ }}\n"
        f"    __rb_{s}[\"base_elevation_lower_candidate_mm\"] = Math.Round(__elevLower_{s}, 3);\n"
        f"    __rb_{s}[\"base_elevation_upper_candidate_mm\"] = Math.Round(__elevUpper_{s}, 3);\n"
        f"    try {{ __rb_{s}[\"top_elevation_mm\"] = "
        f"Math.Round(MM(__freshRn_{s}.TopElevation), 2); }} catch {{ }}\n"
        f"    try {{ __rb_{s}[\"run_width_mm\"] = "
        f"Math.Round(MM(__freshRn_{s}.ActualRunWidth), 2); }} catch {{ }}\n"
        f"    __rb_{s}[\"justification\"] = {_cs(justification)};\n"
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
        # ТОТ ЖЕ СВОД, ЧТО У МАРША И ПЛОЩАДКИ: предупреждение снимаем, чтобы
        # оно не всплыло диалогом и не заморозило UI-поток Revit; настоящую
        # ОШИБКУ по-прежнему отдаём Revit. Обработчик стоит и на транзакции,
        # и на `StairsEditScope.Commit` — предупреждение может подняться уже
        # вне транзакции.
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
