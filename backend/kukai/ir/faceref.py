"""ССЫЛКА, КОТОРУЮ РАЗРЕШАЕТ REVIT: именованная ГРАНЬ элемента.

ЧТО ЭТО ЗА СЛОЙ И ПОЧЕМУ ОН ОТДЕЛЬНЫЙ
--------------------------------------
Замороженный диалект ссылок KIR отвечает ровно на один вопрос — «КАКОЙ
ЭЛЕМЕНТ» — и отвечает на него ЧЕТЫРЬМЯ формами, каждая из которых
разрешается ДО того, как C# попадёт в Revit:

    {"by": "name",         "value": ...}   -> `ground.py`, против снимка модели
    {"by": "element_id",   "value": ...}   -> уже разрешено, это и есть id
    {"by": "ref",          "value": <op>}  -> компилятором, в переменную C#
    {"by": "phase_result", "value": <op>,
                           "phase": N}     -> исполнителем между программами
                                             (`course.CROSS_PHASE_BY`, 09.08)

Ни одна из них не может назвать ГРАНЬ: у грани нет `ElementId`, она не
`Element`, и до исполнения её не существует как адресуемой вещи. Тот же
структурный тупик закрыл `Electrical.Wire.Create` (ветка `feat/kir-mep`,
`e4fe53b8`: «`Connector` — не `Element`… замороженный диалект ссылок KIR
назвать его не может ВООБЩЕ») и держит всю главу концептуальных масс:
`FaceWall.Create` и `NewCurtainSystem2` требуют грань настоящего
`FamilyInstance`-массы, а назвать грань типизированной программе нечем.

ФОРМА — ОБЁРТКА, А НЕ ПЯТЫЙ `by`
--------------------------------
    {"by": "face", "of": <селектор элемента>, "predicate": {...}}

`of` несёт ЦЕЛЫЙ селектор существующего диалекта, а не голый id опа. Это
ГЛАВНОЕ решение этого файла, и оно выведено из `phase_result`, а не придумано
рядом с ним.

Довод замера, а не вкуса. Ссылки ищут РОДОВЫМИ обходами по всей структуре:
`design_check._ref_targets` и `course._mark_cross_phase` спускаются в любой
вложенный словарь и ищут `by == "ref"`. Напиши мы `{"of": "M1"}` голой
строкой — оба обхода прошли бы мимо, и ссылка на грань элемента из ПРОШЛОЙ
фазы осталась бы `by=ref` на оп, которого к тому моменту уже нет: ровно тот
отказ, который `_merge_bundle` формулирует словами «соседняя программа —
отдельная транзакция, и к её исполнению id уже не существует». С вложенным
селектором те же обходы находят ссылку САМИ, и фазы с гранями складываются
без единой правки в `course/__init__.py`. Проверено тестом
(`test_faceref.py::CoherenceWithFrozenDialectTests`), а не рассуждением.

Отсюда же читается, ЧТО ЭТО ЗА ГРАММАТИКА: не пятая форма в одном перечне, а
ВТОРАЯ СТУПЕНЬ. Ступень 1 отвечает «какой элемент» (четыре формы выше),
ступень 2 — «какая часть этого элемента» и ВСЕГДА содержит ровно один
селектор ступени 1. Замороженный диалект остаётся замороженным: каждый его
потребитель видит те же четыре формы, просто на уровень глубже.

ГДЕ РАЗРЕШАЕТСЯ И ЧТО ИЗМЕНИТСЯ, ЕСЛИ ЭТО ПЕРЕЕДЕТ
---------------------------------------------------
СЕГОДНЯ: инлайновым C#, который эмитирует этот файл. Тогда текст резолвера
входит в программу, а значит в `program_digest`, — квитанция подписывает
поведение резолвера ПО ПОСТРОЕНИЮ.

ЕСЛИ ПЕРЕЕДЕТ В ОТГРУЖАЕМУЮ DLL — подпись сломается ровно так, как сломался
бы `author_digest` без подписи среды (`sandbox.environment_signature`, ветка
`feat/kir-kernel`, `ad06eeb8`): один дайджест удостоверял бы РАЗНЫЕ поведения
после обновления библиотеки, и в квитанции не было бы ни одного поля, чтобы
отличить правку программы от дрейфа рантайма. ПОЭТОМУ ПОРЯДОК ЗАФИКСИРОВАН
ЛИДОМ: сначала квитанция подписывает версию и дайджест этой DLL, потом код
туда переезжает. Здесь эта DLL НЕ реализуется — здесь названо условие.

ЗАКОН ЭТОГО ФАЙЛА: ОПИСАНИЕ ФИЛЬТРУЕТ, А НЕ ВЫБИРАЕТ
-----------------------------------------------------
У `Solid.Faces` порядок НЕ документирован (это уже записано в
`authoring._dim_geom_helpers_cs`), поэтому любое «взять первую подходящую» —
число без смысла и `.FirstOrDefault()` под другим именем. Живой замер 02.08
на Snowdon: плечо C# взяло 1 тип двери ИЗ 62 молча и построило.

Здесь предикат — ФИЛЬТР, а решает МОЩНОСТЬ множества:

    ровно 1 кандидат  -> связываем
    0 кандидатов      -> типизированный отказ с названным следующим ходом
    >= 2 кандидатов   -> типизированный отказ, С ЧИСЛОМ кандидатов

Мощность не зависит от порядка перебора — поэтому недокументированный порядок
`Solid.Faces` перестаёт влиять на результат ВООБЩЕ. Это и есть весь трюк.

ДОПУСКИ: НИ ОДНОГО СВОЕГО
-------------------------
Параллельность нормалей проверяется РОДНЫМ тестом Revit —
`XYZ.CrossProduct(...).IsZeroLength()`, тем же, которым уже пользуется
`_dim_geom_helpers_cs` («Revit's OWN zero-length test so no threshold is
invented here»). Сонаправленность — знаком `DotProduct`. Вырожденность
заданного вектора — тем же `IsZeroLength()`, В РАНТАЙМЕ. Ни одного числа,
назначенного здесь.

ПРЯМОЕ СЛЕДСТВИЕ, НАЗВАННОЕ ВСЛУХ: предикат `normal` — ТОЧНЫЙ, а не
«ближайший». Грань, повёрнутая на градус, не подойдёт и даст отказ «нет
кандидата». Это СОЗНАТЕЛЬНО: «ближайшая по углу» требует УГЛОВОГО ДОПУСКА,
которого никто не мерил, а назначенный допуск — тот самый класс дефекта, что
и `create_door.sill_mm min_val=0`.

ПОДПИСИ API СНЯТЫ С ЭТАЛОННЫХ СБОРОК (замер 09.08, живой Roslyn :52412,
одна строка на кандидата, `data/revit_api_db.json` не спрашивался):

    HostObjectUtils.GetSideFaces(HostObject, ShellLayerType)   2021..2026  6/6
    HostObjectUtils.GetTopFaces(HostObject)                    2021..2026  6/6
    HostObjectUtils.GetBottomFaces(HostObject)                 2021..2026  6/6
    Element.GetGeometryObjectFromReference(Reference)          2021..2026  6/6
    GeometryInstance.GetSymbolGeometry() + .Transform          2021..2026  6/6
    PlanarFace.FaceNormal / .Reference                         2021..2026  6/6
    XYZ.IsZeroLength/CrossProduct/DotProduct/Normalize         2021..2026  6/6
    Reference.ConvertToStableRepresentation(Document)          2021..2026  6/6

Поэтому версионной ветки в эмиссии НЕТ: шесть версий получают один и тот же
C#, и это ФАКТ ЗАМЕРА, а не надежда.
"""
from __future__ import annotations

import os
from typing import Any

from kukai.ir.diag import (
    Diagnostic, GROUND_BAD_SELECTOR, TYPE_BAD_ENUM, TYPE_BAD_TYPE,
)

#: Второй род селектора. Живёт РЯДОМ с четырьмя формами ступени 1, а не среди
#: них: см. «ФОРМА — ОБЁРТКА, А НЕ ПЯТЫЙ `by`» в докстринге модуля.
BY_FACE = "face"

#: Имя флага оператора — ЗДЕСЬ ТОЛЬКО ДЛЯ ЧТЕНИЯ СНАРУЖИ (тесты, документация).
#: В самой калитке `face_ref_enabled` оно написано ЛИТЕРАЛОМ, и это не
#: дублирование по недосмотру: `tools/capability_map.py` ищет флаги регуляркой
#: `os.getenv("ИМЯ")` ПО ТЕКСТУ, и вызов через константу инвентарь НЕ УВИДИТ —
#: флаг станет невидимым, то есть лежащим на складе по построению. Тот же приём
#: и та же причина, что у `sandbox.AUTHOR_GEOMETRY_LIBS_FLAG`. Что имена не
#: разъехались, держит тест, а не договорённость.
FACE_REF_FLAG = "KUKAI_IR_FACE_REF"

#: Стороны, которые Revit НАЗЫВАЕТ САМ. Это не геометрия, которую мы считаем, —
#: это имена из `HostObjectUtils`, поэтому у них нет и не может быть допуска.
SIDES: tuple[str, ...] = ("exterior", "interior", "top", "bottom")

#: Ключи предиката. Больше одного — КОНЪЮНКЦИЯ (И), и это единственный
#: названный следующий ход при отказе «кандидатов несколько».
PREDICATE_KEYS: tuple[str, ...] = ("side", "normal")


def face_ref_enabled() -> bool:
    """Флаг оператора: разрешена ли ВТОРАЯ СТУПЕНЬ селектора (грань).

    ВЫКЛЮЧЕН ПО УМОЛЧАНИЮ. Выключенным он обязан быть неотличим от отсутствия
    формы вовсе: селектор ступени 2 получает типизированный отказ на разборе, а
    эмиссия программ БЕЗ таких селекторов обязана быть побайтово той же
    (`test_faceref.py::FlagOffIsAbsentTests`).
    """
    return os.getenv("KUKAI_IR_FACE_REF", "").strip().lower() in (
        "1", "true", "yes", "on")


def is_face_sel(value: Any) -> bool:
    """Похоже ли значение на селектор грани — СТРУКТУРНО, до всякой проверки.

    Нужна отдельно от `validate_face_sel`, потому что вызывающему надо
    отличить «это не грань» (пусть разбирается обычная ветка) от «это грань, но
    кривая» (типизированный отказ О ГРАНИ). Слить эти два ответа значило бы
    отвечать «селектор должен быть element_id|ref» на опечатку в предикате —
    диагностика, посылающая ремонт не туда.
    """
    return isinstance(value, dict) and value.get("by") == BY_FACE


def inner_selector(sel: dict) -> Any:
    """Селектор СТУПЕНИ 1 внутри селектора грани — то, что адресует элемент."""
    return sel.get("of")


def validate_face_sel(sel: dict, *, oid: str, field: str, i: int | None,
                      inner_ok, diags: list) -> dict | None:
    """Проверить форму селектора грани. Вернуть НОРМАЛИЗОВАННЫЙ или None.

    `inner_ok` — предикат вызывающего для селектора СТУПЕНИ 1: этот файл не
    знает и не должен знать, какие формы законны в конкретном параметре
    (`refs_w` берёт element_id|ref, `sel` взял бы ещё name/default). Спрашивать
    об этом вызывающего — единственный способ не завести здесь второй источник
    правды о замороженном диалекте.

    ОТКАЗЫ РАЗДЕЛЬНЫЕ, А НЕ СКЛЕЕННЫЕ В ОДИН. Замер 02.08 (девять заметок
    длиннее предела, все девять сообщили «content — непустая строка») стоит
    здесь той же дисциплины: сообщение, называющее не тот отказ, дороже
    отсутствия сообщения.
    """
    where = field if i is None else f"{field}[{i}]"
    allowed = {"by", "of", "predicate"}
    extra = set(sel) - allowed
    if extra:
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_id=oid, field_name=where,
            expected=sorted(allowed), got=sorted(extra),
            message_ru=(
                f"{where}: у селектора грани нет полей {sorted(extra)}. "
                f"Форма ровно одна: "
                f'{{"by": "face", "of": <селектор элемента>, '
                f'"predicate": {{...}}}}')))
        return None

    inner = sel.get("of")
    if not inner_ok(inner):
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_id=oid, field_name=f"{where}.of",
            expected='{"by": "element_id"|"ref", "value": ...}', got=inner,
            message_ru=(
                f"{where}.of: грань принадлежит ЭЛЕМЕНТУ, и элемент "
                f"называется обычным селектором — тем же, что и везде. "
                f"СЛЕДУЮЩИЙ ХОД: подставь сюда селектор, законный для этого "
                f"параметра")))
        return None

    pred = sel.get("predicate")
    if not isinstance(pred, dict):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{where}.predicate",
            expected="объект", got=pred,
            message_ru=(
                f"{where}.predicate: описание грани обязательно — селектор "
                f"грани БЕЗ описания адресует все грани сразу, то есть не "
                f"адресует ни одной")))
        return None

    unknown = set(pred) - set(PREDICATE_KEYS)
    if unknown:
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_id=oid, field_name=f"{where}.predicate",
            expected=list(PREDICATE_KEYS), got=sorted(unknown),
            message_ru=(
                f"{where}.predicate: неизвестные ключи {sorted(unknown)}. "
                f"Описание грани знает {list(PREDICATE_KEYS)}; несколько "
                f"ключей сразу — это И (конъюнкция)")))
        return None

    if not pred:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{where}.predicate",
            expected=f"хотя бы один из {list(PREDICATE_KEYS)}", got=pred,
            message_ru=(
                f"{where}.predicate пуст. Описание, которому отвечает КАЖДАЯ "
                f"грань, — не имя грани, а `.FirstOrDefault()` в другой "
                f"одежде. СЛЕДУЮЩИЙ ХОД: назови side или normal")))
        return None

    out: dict[str, Any] = {}
    if "side" in pred:
        side = pred["side"]
        if side not in SIDES:
            diags.append(Diagnostic(
                code=TYPE_BAD_ENUM, op_id=oid,
                field_name=f"{where}.predicate.side",
                expected=list(SIDES), got=side, candidates=list(SIDES),
                message_ru=(
                    f"{where}.predicate.side: сторону НАЗЫВАЕТ САМ Revit "
                    f"(`HostObjectUtils`), и список закрыт: {list(SIDES)}")))
            return None
        out["side"] = side
    if "normal" in pred:
        vec = pred["normal"]
        # Числовая проверка ТОЛЬКО на форму. Вырожденность вектора решается в
        # РАНТАЙМЕ родным `XYZ.IsZeroLength()`: назначить здесь «минимальную
        # длину» значило бы выдумать допуск, а единственный настоящий порог
        # у Revit, и спросить его можно только на исполнении.
        if (not isinstance(vec, (list, tuple)) or len(vec) != 3
                or any(isinstance(x, bool) or not isinstance(x, (int, float))
                       for x in vec)):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid,
                field_name=f"{where}.predicate.normal",
                expected="[x, y, z] — три числа", got=vec,
                message_ru=(
                    f"{where}.predicate.normal — направление внешней нормали "
                    f"грани в координатах МОДЕЛИ, три числа. Длина не важна: "
                    f"вектор нормируется в Revit")))
            return None
        out["normal"] = [float(x) for x in vec]

    return {"by": BY_FACE, "of": inner, "predicate": out}


# ══════════════════════════════════════════════════════════════════════════
# ЭМИССИЯ: РАЗРЕШЕНИЕ ОПИСАНИЯ В ССЫЛКУ, ВНУТРИ REVIT
# ══════════════════════════════════════════════════════════════════════════

#: Как сторона, названная Revit, превращается в вызов `HostObjectUtils`.
#: Таблица, а не `if`-лестница: список сторон закрыт и живёт в `SIDES`, и два
#: места, знающих его порознь, разъехались бы на первой же правке.
_SIDE_CALL: dict = {
    "exterior": "HostObjectUtils.GetSideFaces({ho}, ShellLayerType.Exterior)",
    "interior": "HostObjectUtils.GetSideFaces({ho}, ShellLayerType.Interior)",
    "top": "HostObjectUtils.GetTopFaces({ho})",
    "bottom": "HostObjectUtils.GetBottomFaces({ho})",
}


def walk_helpers_cs(s: str) -> str:
    """Локальные функции ОДНОГО опа: обход геометрии и отбор кандидатов.

    Локальными функциями, а не развёрнутым текстом: обход РЕКУРСИВЕН (вложенные
    семейства — это `GeometryInstance` внутри `GeometryInstance`), и он нужен
    один раз на КАЖДУЮ ссылку. Едут в `decl`, а не в `create`: изоляция
    `per_op` оборачивает каждый create в свою область видимости, и объявленное
    внутри неё имя умирает на закрывающей скобке (контракт областей).

    ЛОВУШКА, КОТОРАЯ КОМПИЛИРУЕТСЯ 6/6 И ОТКАЗЫВАЕТ ЖИВЬЁМ — не выведена
    заново, а взята из ветки `feat/kir-annotation` (`9c5c7492`), где она стоила
    третьего живого отказа. Очевидный `GetInstanceGeometry()` документирован
    RevitAPI.xml как КОПИЯ, чьи ссылки «not suitable for creating new Revit
    elements referencing the original element (for example, dimensioning)», —
    то есть ровно тот род ссылки, на котором Revit бросает. Годится только
    `GetSymbolGeometry()` БЕЗ аргумента. Координаты у него символьные, поэтому
    НОРМАЛЬ возвращается в модель через `GeometryInstance.Transform`
    (композиция — значит и вложенные семейства работают). Ссылка берётся из
    одного аксессора, а координаты из другого — в этом весь приём.

    ОБХОД НЕ ПРЕРЫВАЕТСЯ НА ПЕРВОМ ПОПАДАНИИ, и это отличает его от обхода
    размера. Тот ИЩЕТ годную грань и вправе остановиться; этот СЧИТАЕТ, сколько
    граней отвечает описанию, потому что решение принимает мощность множества.
    Ранний выход превратил бы «их две» в «взял первую» — то самое тихо-неверное
    поведение, ради запрета которого форма и заводится.
    """
    return f"""void __faceKeep_{s}(Element __fkEl, IList<Reference> __fkSrc, XYZ __fkWant,
    List<Reference> __fkOut)
{{
    if (__fkSrc == null) return;
    foreach (Reference __fkR in __fkSrc)
    {{
        if (__fkR == null) continue;
        if (__fkWant == null) {{ __fkOut.Add(__fkR); continue; }}
        PlanarFace __fkPf = null;
        try {{ __fkPf = __fkEl.GetGeometryObjectFromReference(__fkR) as PlanarFace; }}
        catch {{ }}
        if (__fkPf == null) continue;
        XYZ __fkN = __fkPf.FaceNormal;
        if (__fkN.IsZeroLength()) continue;
        __fkN = __fkN.Normalize();
        if (!__fkN.CrossProduct(__fkWant).IsZeroLength()) continue;
        if (__fkN.DotProduct(__fkWant) <= 0) continue;
        __fkOut.Add(__fkR);
    }}
}}
void __faceWalk_{s}(GeometryElement __fwGe, Transform __fwTf, XYZ __fwWant,
    List<Reference> __fwOut)
{{
    if (__fwGe == null) return;
    foreach (GeometryObject __fwGo in __fwGe)
    {{
        Solid __fwSol = __fwGo as Solid;
        if (__fwSol != null)
        {{
            foreach (Face __fwFc in __fwSol.Faces)
            {{
                PlanarFace __fwPf = __fwFc as PlanarFace;
                if (__fwPf == null || __fwPf.Reference == null) continue;
                XYZ __fwN = __fwTf.OfVector(__fwPf.FaceNormal);
                if (__fwN.IsZeroLength()) continue;
                __fwN = __fwN.Normalize();
                if (__fwWant != null && !__fwN.CrossProduct(__fwWant).IsZeroLength()) continue;
                if (__fwWant != null && __fwN.DotProduct(__fwWant) <= 0) continue;
                __fwOut.Add(__fwPf.Reference);
            }}
            continue;
        }}
        GeometryInstance __fwGi = __fwGo as GeometryInstance;
        if (__fwGi != null)
            __faceWalk_{s}(__fwGi.GetSymbolGeometry(), __fwTf.Multiply(__fwGi.Transform),
                __fwWant, __fwOut);
    }}
}}"""


def resolve_cs(sel: dict, *, s: str, i: int, elem_var: str, out_var: str,
               oid: str, label: str, isolation: str, view_var: str | None,
               refuse_stmt, cs_literal,
               next_move_zero: str | None = None,
               next_move_many: str | None = None,
               normal_field: str = "predicate.normal") -> str:
    """C#, связывающий `out_var` с ЕДИНСТВЕННОЙ гранью, отвечающей описанию.

    `refuse_stmt`/`cs_literal` приходят параметрами, а не импортом: у отказа
    ОДИН владелец (`emit_utils.refuse_stmt`), и этот файл обязан спрашивать
    форму, а не печатать её (иначе `per_op` молча получил бы семантику всей
    программы — дефект, закрытый 28.07 и охраняемый KIR-E005).

    ТРИ ИСХОДА, И НИ ОДНОГО МОЛЧАЛИВОГО: ровно один кандидат — связываем;
    ноль — отказ; больше одного — отказ, НАЗЫВАЮЩИЙ ЧИСЛО. Компилятор не
    выбирает за автора: живой парный замер 02.08 на Snowdon показал цену
    выбора — плечо C# взяло 1 тип двери из 62 молча и построило.

    `next_move_zero` / `next_move_many` — СЛЕДУЮЩИЙ ХОД словами вызывающего.
    Заведены волной масс (10.08) и НЕ ради вкуса: собственный текст этого
    файла отсылает к `predicate.side` и `predicate.normal`, то есть к
    словарю ВТОРОЙ СТУПЕНИ СЕЛЕКТОРА. У операции, которая берёт направление
    грани обычным параметром (`create_face_wall.face_normal`, как
    `create_slab_edge` берёт `side`), таких полей нет вовсе — и отказ,
    посылающий автора править несуществующее поле, дороже отсутствия
    отказа. Это ровно тот закон, который этот файл уже применил к себе
    («ОТКАЗЫ РАЗДЕЛЬНЫЕ, А НЕ СКЛЕЕННЫЕ В ОДИН»), просто на ступень выше.

    `normal_field` — тем же поводом и для того же места: имя поля, в котором
    автор написал вектор. У селектора это `predicate.normal`, у операции с
    обычным параметром — имя её параметра, и отказ обязан называть ТО, что
    автор правит.

    Умолчания дают ДОСЛОВНО прежний текст, поэтому эмиссия
    `create_dimension` побайтово та же — расширение помощника не имеет права
    двигать программы, которые его уже звали.
    """
    pred = sel["predicate"]
    human = describe_predicate_ru(pred)
    cand = f"__fc_{s}_{i}"
    want = f"__fw_{s}_{i}"
    lines = [f"List<Reference> {cand} = new List<Reference>();"]

    if "normal" in pred:
        x, y, z = pred["normal"]
        lines.append(f"XYZ {want} = new XYZ({x!r}, {y!r}, {z!r});")
        # Вырожденность решает РОДНОЙ тест Revit, в рантайме. Назначить порог
        # здесь значило бы выдумать допуск; настоящий порог знает только Revit.
        lines.append(
            f"if ({want}.IsZeroLength()) {{ "
            + refuse_stmt(oid, cs_literal(
                f"{label}: {normal_field} — вырожденный вектор (Revit "
                f"считает его нулевым). СЛЕДУЮЩИЙ ХОД: задай направление "
                f"нормали ненулевым вектором"), isolation) + " }")
        lines.append(f"{want} = {want}.Normalize();")
    else:
        lines.append(f"XYZ {want} = null;")

    if "side" in pred:
        ho = f"__fh_{s}_{i}"
        src = f"__fs_{s}_{i}"
        call = _SIDE_CALL[pred["side"]].format(ho=ho)
        lines.append(f"HostObject {ho} = {elem_var} as HostObject;")
        lines.append(
            f"if ({ho} == null) {{ "
            + refuse_stmt(oid, cs_literal(
                f"{label}: сторона «{pred['side']}» — имя, которое даёт САМ "
                f"Revit (HostObjectUtils), и оно есть только у HostObject "
                f"(стена, перекрытие, кровля, потолок). Этот элемент — ")
            + f" + __ClassName({elem_var}) + " + cs_literal(
                ". СЛЕДУЮЩИЙ ХОД: опиши грань нормалью "
                "(predicate.normal)"), isolation) + " }")
        lines.append(f"IList<Reference> {src} = null;")
        lines.append(f"try {{ {src} = {call}; }} catch {{ }}")
        lines.append(f"__faceKeep_{s}({elem_var}, {src}, {want}, {cand});")
    else:
        opt = f"__fo_{s}_{i}"
        ge = f"__fg_{s}_{i}"
        lines.append(f"Options {opt} = new Options();")
        lines.append(f"{opt}.ComputeReferences = true;")
        # Без этого геометрия базовой линии (оси, уровни, опорные плоскости)
        # не появляется ВООБЩЕ — измерено веткой аннотаций: каждая ось
        # отказывала до 09.08 именно поэтому.
        lines.append(f"{opt}.IncludeNonVisibleObjects = true;")
        if view_var:
            lines.append(f"{opt}.View = {view_var};")
        lines.append(f"GeometryElement {ge} = null;")
        lines.append(f"try {{ {ge} = {elem_var}.get_Geometry({opt}); }} catch {{ }}")
        lines.append(
            f"__faceWalk_{s}({ge}, Transform.Identity, {want}, {cand});")

    lines.append(
        f"if ({cand}.Count == 0) {{ "
        + refuse_stmt(oid, cs_literal(
            f"{label}: у элемента нет грани, отвечающей описанию ({human}). "
            f"Описание ТОЧНОЕ: грань берётся, только если её нормаль строго "
            f"параллельна и сонаправлена заданной (проверка родным "
            f"XYZ.IsZeroLength на векторном произведении) — «почти "
            f"параллельна» не считается, потому что углового допуска никто "
            f"не мерил. "
            + (next_move_zero or
               "СЛЕДУЮЩИЙ ХОД: проверь направление нормали в координатах "
               "МОДЕЛИ, либо назови сторону (predicate.side)")),
            isolation) + " }")
    lines.append(
        f"if ({cand}.Count > 1) {{ "
        + refuse_stmt(
            oid,
            # «отвечает не одна грань, а N» — а не «отвечает N граней»:
            # русское число согласуется с существительным, и склеенная из
            # шаблона форма врёт на 2, 3 и 4. Отказ читает человек.
            cs_literal(f"{label}: описанию ({human}) отвечает не одна грань, а ")
            + f" + {cand}.Count.ToString() + "
            + cs_literal(
                ". Компилятор НЕ выбирает за автора: порядок граней "
                "в теле не документирован, поэтому «первая подходящая» — "
                "число без смысла. "
                + (next_move_many or
                   "СЛЕДУЮЩИЙ ХОД: сузь описание — добавь predicate.normal "
                   "рядом с predicate.side (или наоборот)")),
            isolation) + " }")
    lines.append(f"{out_var} = {cand}[0];")
    return "\n".join(lines)


def describe_predicate_ru(pred: dict) -> str:
    """Описание грани ЧЕЛОВЕЧЕСКИМИ словами — для текста отказа.

    Отказ обязан повторить описание дословно: «грань не найдена» без описания
    отправляет автора перечитывать собственную программу, а это ровно та цена,
    которую типизированный отказ существует чтобы не брать.
    """
    parts = []
    if "side" in pred:
        parts.append(f"сторона «{pred['side']}»")
    if "normal" in pred:
        x, y, z = pred["normal"]
        parts.append(f"нормаль [{x:g}, {y:g}, {z:g}]")
    return " и ".join(parts)
