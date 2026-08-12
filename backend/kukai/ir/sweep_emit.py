"""sweep_emit — эмиссия create_wall_sweep / create_slab_edge (парный файл к
`ops_sweep.py`, ровно как `site_emit.py` к `ops_site.py`).

Своя зона волны: модуль не трогает ни один другой `ops_*.py` и ни один другой
`*_emit.py`. `authoring.py` получает аддитивно отложенный импорт и две строки
в `_EMITTERS` — тот же минимальный шов, которым подключились волны площадки,
каркаса и архитектуры.

Переиспользовано из `authoring.py` БЕЗ ИЗМЕНЕНИЙ (импортом, не копией): `_gid`,
`_eid`, `_cs`, `_safe`, `_stamp_block`, `_stamp_readback`, `EMIT_UNSUPPORTED`.
Оговорка та же, что в шапках `site_emit.py`/`struct_emit.py`: часть имён
приватные, и чистый шов лечится повышением их до публичных в `authoring.py`, а
не копированием тел сюда.

ГЛАВНОЕ ОБ ЭТОМ ФАЙЛЕ — ДВА СВИДЕТЕЛЯ РАЗНОЙ СИЛЫ, И РАЗНИЦА НАЗВАНА, А НЕ
СПРЯТАНА. Обе операции читают РЕЗУЛЬТАТ, а не собственный вызов, но
утверждают о нём РАЗНОЕ:

* СТЕННОЙ ПРОФИЛЬ — самый слабый свидетель во всём реестре, и это ЗАМЕР, а не
  недоделка. `RevitAPI.xml` всех шести версий пишет у `WallSweep.Create`
  дословно: «The wall sweep's profile and type are taken from the wall sweep
  type properties. The values set in the WallSweepInfo are ignored.» Значит
  положение профиля на стене задаёт ТИП, а не вызов; ни расстояния, ни
  смещения операция не принимает вовсе, и утверждать о них нечего. Остаётся
  ТРОЙКА ТОЧНЫХ фактов о построенном элементе — он есть, он числится на
  запрошенной стене (`GetHostIds`), у него запрошенный тип (`GetTypeId`) — и
  четвёртый, СЕМАНТИЧЕСКИЙ: ориентация (`GetWallSweepInfo().IsVertical`),
  единственное поле `WallSweepInfo`, которое операция вообще предъявляет,
  потому что записать его иначе нельзя (свойство только для чтения, CS0200 на
  всех шести — канал ровно один, аргумент конструктора);
* КРАЕВОЙ ПРОФИЛЬ — свидетель НАСТОЯЩИЙ геометрический, и он появился ровно
  потому, что вопрос «а есть ли у `SlabEdge` хоть какое-то чтение» был
  ЗАМЕРЕН, а не вспомнен. `get_ReferenceCurve(Reference)` — индексируемое
  свойство базового `HostedSweep`, 6/6: у ПОСТРОЕННОГО профиля спрашивается
  кривая, которую он проложил по КАЖДОЙ переданной нами ссылке на ребро.
  `null` означает, что Revit эту ссылку не взял, и тогда капельник обводит не
  тот периметр, который просили. Эмиттер такое утверждение подделать не может
  ничем: он ссылку передал, а кривую вернул элемент.

ССЫЛКУ НА РЕБРО НАЗЫВАЕТ НЕ АВТОР, А МОЩНОСТЬ. `NewSlabEdge` принимает
геометрическую ссылку, а замороженный диалект KIR адресует ЭЛЕМЕНТЫ; вторая
ступень селектора (`faceref.py`, 09.08) называет ГРАНЬ, но не РЕБРО, и писать
здесь третий род второй ступени значило бы завести второй механизм рядом с
существующим. Поэтому операция берёт ВЕСЬ ПЕРИМЕТР названной стороны, и обе
ступени решаются МОЩНОСТЬЮ множества, а не порядком перебора — тот же закон,
что в `faceref.py`:

    сторона  -> ровно одна грань, иначе типизированный отказ С ЧИСЛОМ;
    грань    -> ровно один контур, иначе типизированный отказ С ЧИСЛОМ.

Плита с отверстием честно отказывает вторым отказом: какое из колец обводить —
решение автора, а «первое подходящее» при недокументированном порядке
`Face.EdgeLoops` есть `.FirstOrDefault()` под другим именем (живой замер
02.08: плечо C# взяло 1 тип двери из 62 молча и построило).

ЛОВУШКА, КОТОРУЮ ЗДЕСЬ НЕ ПОВТОРИЛИ. Ссылки на рёбра берутся с геометрии,
полученной от `HostObjectUtils` + `Element.GetGeometryObjectFromReference`, —
то есть с ГЕОМЕТРИИ САМОГО ЭЛЕМЕНТА. `GeometryInstance.GetInstanceGeometry()`
здесь не вызывается ВООБЩЕ: RevitAPI.xml документирует его результат как
КОПИЮ, чьи ссылки «not suitable for creating new Revit elements referencing
the original element», и эта ловушка компилируется 6/6, а отказывает живьём
(цена уже уплачена веткой аннотаций, `9c5c7492`).

`NewSlabEdge` ВОЗВРАЩАЕТ NULL, А НЕ БРОСАЕТ («If successful a new slab edge
object within the project, otherwise null» — все шесть XML). Поэтому проверка
на null здесь не перестраховка, а единственная граница между отказом и
`NullReferenceException`, которую конвейер записал бы как `internal`, то есть
как «у нас что-то сломалось», вместо «Revit не принял эти рёбра».
"""
from __future__ import annotations

from kukai.ir.authoring import (
    _gid, _eid, _cs, _safe, _stamp_block, _stamp_readback, EMIT_UNSUPPORTED,
)
from kukai.ir.emit_model import WitnessCheck
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.diag import (
    Diagnostic, EMIT_UNSUPPORTED_ENUM, KirRefusal, PARSE_MISSING_FIELD)
from kukai.ir.ops_sweep import (
    SWEEP_ORIENTATIONS, SLAB_EDGE_SIDES, WALL_SWEEP_NON_FIXED_ID,
)

#: Ориентация/сторона вне закрытого множества. Ремень поверх подтяжек, ровно
#: как у волны площадки (`site_emit`, тот же общий код): `enum`-choices уже
#: ловит это на authoring.validate(), а здесь стоит защита в глубину — тот,
#: кто расширит choices, не дописав ветку, упадёт ГРОМКО, а не построит молча
#: не то.

#: Как сторона, НАЗВАННАЯ САМИМ Revit, превращается в вызов
#: `HostObjectUtils`. Таблица, а не `if`-лестница, и по той же причине, что
#: `faceref._SIDE_CALL`: список сторон закрыт и живёт в реестре
#: (`ops_sweep.SLAB_EDGE_SIDES`), а два места, знающих его порознь, разъехались
#: бы на первой же правке.
_SIDE_CALL: dict = {
    "top": "HostObjectUtils.GetTopFaces({ho})",
    "bottom": "HostObjectUtils.GetBottomFaces({ho})",
}


# ── общие помощники ──────────────────────────────────────────────────────────

def _host_resolve_cs(op: dict, s: str, ver: str, oid: str, isolation: str,
                     cs_class: str, human: str) -> tuple[str, str]:
    """(объявление, разрешение) носителя в переменную `__ho_<s>`.

    НОСИТЕЛЬ ОБЪЯВЛЯЕТСЯ ВО ВНЕШНЕЙ ОБЛАСТИ, а не в блоке создания: при
    `isolation="per_op"` create и post попадают в РАЗНЫЕ области видимости, и
    переменная, объявленная внутри create, свидетелю не видна (CS0103 — ровно
    тот шов, на котором волна ограждений получила шесть отказов ворот), а
    свидетель хозяина её читает.

    ПРИВЕДЕНИЕ ИДЁТ ЧЕРЕЗ `Element`, А НЕ НАПРЯМУЮ, и это не украшение.
    `ref_kinds` у обоих опов включает ELEMENT, то есть источником ссылки может
    оказаться оп, чья переменная `__el_<id>` объявлена НЕ родственным классом
    (`TopographySurface`, `Railing`, ...). Прямое `__el_X as Wall` между
    неродственными классами — это CS0039 на всех шести версиях, то есть
    программа, законная по типизированному контракту реестра, не собралась бы
    вовсе. Восходящее приведение к `Element` законно для любого элемента
    Revit, а уже с него `as` работает.
    """
    sel = op["host"]
    decl = f"{cs_class} __ho_{s} = null;"
    if sel.get("by") == "ref":
        src = "__el_" + _safe(sel["value"])
        res = (f"Element __hsrc_{s} = {src};\n"
               f"__ho_{s} = __hsrc_{s} as {cs_class};\n")
    else:
        res = (f"Element __hsrc_{s} = doc.GetElement("
               f"{_eid(sel['value'], ver, oid)});\n"
               f"if (__hsrc_{s} == null) {{ "
               + refuse_stmt(oid, _cs(
                   f"{human}: носитель не найден (модель изменилась после "
                   f"grounding)"), isolation) + " }\n"
               f"__ho_{s} = __hsrc_{s} as {cs_class};\n")
    res += (f"if (__ho_{s} == null) {{ "
            + refuse_stmt(
                oid,
                _cs(f"{human}: носителем может быть только {human_host(cs_class)}, "
                    f"а этот элемент — ")
                + f" + __ClassName(__hsrc_{s}) + " + _cs(
                    ". СЛЕДУЮЩИЙ ХОД: назови в host элемент нужного класса"),
                isolation) + " }\n")
    return decl, res


def human_host(cs_class: str) -> str:
    """Класс носителя ЧЕЛОВЕЧЕСКИМИ словами — для текста отказа.

    Отказ читает человек, и «носителем может быть только HostObject» отправляет
    его читать документацию Autodesk вместо собственной программы.
    """
    return {"Wall": "стена",
            "HostObject": "перекрытие, кровля, потолок или стена "
                          "(любой HostObject)"}[cs_class]


def _grounded_type_cs(op: dict, s: str, oid: str, ver: str, cs_class: str,
                      human: str, isolation: str) -> str:
    """Разрешение типа в переменную `__ty_<s>`.

    ВЕТКИ doc_default ЗДЕСЬ НЕТ, и это ПРОВЕРЕНО, а не унаследовано:
    `ElementTypeGroup.RevealType` и `.EdgeSlabType` существуют на всех шести
    версиях (замерено вопреки нашей же базе API, которая знает 30 из 93 членов
    этого перечисления), — то есть спросить документ «твой карниз по
    умолчанию» технически МОЖНО. И всё равно не спрашиваем, по той же причине,
    что у потолка и площадки под здание: «карниз по умолчанию» на чужом
    здании почти никогда не тот, а подмена типа снаружи неотличима от успеха.
    Пропущенный `type` разрешает `ground` общим правилом «единственный в пуле,
    иначе типизированный вопрос с кандидатами» — и этот вопрос автор увидит, в
    отличие от подстановки.

    Здесь же названа и вторая причина, специфичная для этой волны: у стенного
    профиля ТИП РЕШАЕТ ВСЁ (см. шапку модуля), поэтому подставленный за автора
    тип — это подставленная за автора ГЕОМЕТРИЯ, а не только имя в спецификации.
    """
    sel = op.get("type")
    g = _gid(op, "type") if isinstance(sel, dict) and "__grounded__" in sel else None
    if not g or g.get("id") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="type",
            message_ru=(f"{human}: тип не разрешён на стадии ground — у этой "
                        f"операции нет типа по умолчанию, подставить нечего"))])
    # ПРИВЕДЕНИЕ ЕСТЬ НЕ ВСЕГДА, И ТЕКСТ ОТКАЗА ОБЯЗАН ЭТО ОТРАЖАТЬ. У
    # краевого профиля тип — настоящий класс (`SlabEdgeType`), и «он не
    # SlabEdgeType» — годная причина. У стенного тип берётся `Element`ом,
    # потому что класса типа у него не существует вовсе, и та же фраза
    # звучала бы «он не Element» — отказ, отправляющий человека искать
    # несуществующую разницу.
    cast = "" if cs_class == "Element" else f" as {cs_class}"
    why = ("тип не найден (модель изменилась после grounding)"
           if cs_class == "Element" else
           f"тип не найден или он не {cs_class} "
           f"(модель изменилась после grounding)")
    guard = (f"\nif (__ty_{s} == null) {{ "
             + refuse_stmt(oid, _cs(f"{human}: {why}"), isolation) + " }")
    return (f"__ty_{s} = doc.GetElement({_eid(g['id'], ver, oid)}){cast};"
            + guard)


def _type_id_witness(s: str, oid: str, human: str) -> WitnessCheck:
    """ТИП ПОСТРОЕННОГО ЭЛЕМЕНТА, прочитанный обратно.

    Общий для обеих операций, потому что утверждение у них дословно одно:
    `GetTypeId()` построенного элемента равен тому id, который ground разрешил
    ДО эффекта. Сравнение через `ToString()` — единственная идиома `ElementId`,
    работающая на всех шести версиях: `.IntegerValue` мёртв на 2026, `.Value`
    не существует до 2024.
    """
    return WitnessCheck(
        obligation_key="sweep_type",
        reader_cs=f"    ElementId __rt_{s} = __el_{s}.GetTypeId();\n",
        verdict_cs=(
            f"    if (__rt_{s} == null || __ty_{s} == null\n"
            f"        || __rt_{s}.ToString() != __ty_{s}.Id.ToString())\n"
            f"        __post.Add({_cs(oid + f': тип построенного элемента ({human}) не равен запрошенному (topology)')});\n"),
        message=f"тип построенного элемента ({human}) не равен запрошенному (topology)",
        style="guard")


# ── create_wall_sweep ────────────────────────────────────────────────────────

def emit_wall_sweep(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Карниз/поясок/руст на стене, Revit 2021-2026.

    `WallSweep.Create(Wall, ElementId wallSweepTypeId, WallSweepInfo)` — 6/6,
    `since 2012`, версионной ветки НЕТ и это факт замера, а не надежда.

    РОД ПРОФИЛЯ ВЫВОДИТСЯ ИЗ КАТЕГОРИИ ТИПА, А НЕ СПРАШИВАЕТСЯ У АВТОРА.
    `WallSweepType` — это ПЕРЕЧИСЛЕНИЕ {Sweep, Reveal}, а не класс типа; сам
    тип живёт обычным `ElementType` в `OST_Cornices` (карниз) либо
    `OST_Reveals` (руст). Спросить род у автора значило бы завести поле,
    которое может ПРОТИВОРЕЧИТЬ типу, — а по ремарке Autodesk (шапка модуля)
    победил бы тип, то есть ответ автору был бы молча другим. Категория
    сверяется через `Category.GetCategory(doc, ...)` и `Id.ToString()`:
    version-safe идиома на всех шести (`.IntegerValue` мёртв на 2026).

    ПРЕДПРОВЕРКА `WallAllowsWallSweep` — НЕ ВЫДУМАННЫЕ ВОРОТА. «wall may not
    host a wall sweep or reveal» стоит в списке условий `ArgumentException`
    самой `Create` (все шесть XML), а документация метода перечисляет, кого он
    исключает: витражные стены и главную стену составной. То есть API этот
    отказ ТРЕБУЕТ; без предпроверки он приехал бы исключением Revit, которое
    конвейер запишет как `internal` — «у нас что-то сломалось» вместо «эта
    стена не может нести профиль, возьми другую».

    `WallSweepInfo.Id = -1` ВЫСТАВЛЯЕТСЯ ЯВНО: «The WallSweepInfo id must be
    set to -1 for a non-fixed wall sweep» — тоже условие `ArgumentException`.
    Понадеяться на умолчание конструктора значило бы отдать целый класс
    исключений в рантайм ради одной несделанной строки.
    """
    oid = op["id"]
    s = _safe(oid)
    orientation = op.get("orientation")
    if orientation not in SWEEP_ORIENTATIONS:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED_ENUM, op_id=oid, field_name="orientation",
            got=orientation, candidates=list(SWEEP_ORIENTATIONS),
            message_ru=(f"create_wall_sweep: ориентация {orientation!r} не "
                        f"поддержана — у WallSweepInfo ровно два состояния, и "
                        f"записать их можно только конструктором"))])
    vertical = "true" if orientation == "vertical" else "false"
    human = "стенной профиль"
    host_decl, host_res = _host_resolve_cs(op, s, ver, oid, isolation,
                                           "Wall", human)
    ty = _grounded_type_cs(op, s, oid, ver, "Element", human, isolation)

    # `__hs_` ОБЪЯВЛЕН ЗДЕСЬ, А НЕ В ЧИТАТЕЛЕ СВИДЕТЕЛЯ, И ЭТО ПОЙМАЛИ ВОРОТА,
    # а не рассуждение: блок постусловий — СВОЯ область видимости
    # (`// post <oid>\n{ ... }`), и квитанция стоит в СЛЕДУЮЩЕЙ. Имя,
    # объявленное в читателе, умирает на закрывающей скобке поста, и квитанция
    # получает CS0103 на всех шести версиях в обеих изоляциях (замер 09.08:
    # 48 живых ячеек, 48 отказов). Контракт областей видимости этого дома
    # ровно об этом: то, что читает POST или квитанция, объявляется в `decl`.
    decl = (f"WallSweep __el_{s} = null;\n"
            f"Element __ty_{s} = null;\n"
            f"WallSweepInfo __wi_{s} = null;\n"
            f"bool __rev_{s} = false;\n"
            f"ICollection<ElementId> __hs_{s} = null;\n"
            + host_decl)

    create = (
        f"// create_wall_sweep {cs_line_comment_fragment(oid)}\n"
        + host_res
        + f"{ty}\n"
        # Род профиля — из категории ТИПА. Обе категории 6/6.
        f"Category __rc_{s} = Category.GetCategory(doc, BuiltInCategory.OST_Reveals);\n"
        f"Category __sc_{s} = Category.GetCategory(doc, BuiltInCategory.OST_Cornices);\n"
        f"string __tc_{s} = (__ty_{s}.Category == null) ? \"\" : __ty_{s}.Category.Id.ToString();\n"
        f"__rev_{s} = (__rc_{s} != null && __tc_{s} == __rc_{s}.Id.ToString());\n"
        f"bool __swp_{s} = (__sc_{s} != null && __tc_{s} == __sc_{s}.Id.ToString());\n"
        f"if (!__rev_{s} && !__swp_{s}) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: разрешённый тип не принадлежит ни карнизам "
                f"(OST_Cornices), ни рустам (OST_Reveals) — WallSweep.Create "
                f"строит только их. Тип: ")
            + f" + (__ty_{s}.Name ?? \"\") + " + _cs(
                ". СЛЕДУЮЩИЙ ХОД: спроси каталог операцией "
                "query_types(pool=\"wall_sweep_types\") и назови тип оттуда"),
            isolation) + " }\n"
        # Предпроверка, которой ТРЕБУЕТ сама Create (см. докстринг).
        f"if (!WallSweep.WallAllowsWallSweep(__ho_{s})) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: эта стена не может нести профиль "
                f"(WallSweep.WallAllowsWallSweep вернул false — метод исключает "
                f"витражные стены и главную стену составной стены). СЛЕДУЮЩИЙ "
                f"ХОД: назови в host обычную стену"),
            isolation) + " }\n"
        f"__wi_{s} = new WallSweepInfo("
        f"__rev_{s} ? WallSweepType.Reveal : WallSweepType.Sweep, {vertical});\n"
        f"__wi_{s}.Id = {WALL_SWEEP_NON_FIXED_ID};\n"
        f"__el_{s} = WallSweep.Create(__ho_{s}, __ty_{s}.Id, __wi_{s});\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(oid, _cs("создание стенного профиля вернуло null"),
                      isolation) + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    checks: list[WitnessCheck] = [
        WitnessCheck(
            # ХОЗЯИН, ПРОЧИТАННЫЙ С ПОСТРОЕННОГО ЭЛЕМЕНТА. `GetHostIds()`
            # возвращает СПИСОК — у профиля, идущего по цепочке соединённых
            # стен, хозяев несколько, — поэтому утверждение здесь «наша стена
            # СРЕДИ хозяев», а не «хозяин ровно один». Требовать
            # единственности значило бы обвинять правильно построенный
            # карниз, перешедший на соседнюю стену: Revit делает это сам, и
            # ремарка `GetHostIds` («Fixed wall sweeps ... will return only
            # one host element») прямо подразумевает, что нефиксированные
            # могут вернуть больше одного.
            obligation_key="sweep_host",
            reader_cs=(
                f"    try {{ __hs_{s} = __el_{s}.GetHostIds(); }} catch {{ }}\n"
                f"    bool __hh_{s} = false;\n"
                f"    if (__hs_{s} != null && __ho_{s} != null)\n"
                f"        foreach (ElementId __hq_{s} in __hs_{s})\n"
                f"            if (__hq_{s} != null && __hq_{s}.ToString() == __ho_{s}.Id.ToString())\n"
                f"            {{ __hh_{s} = true; break; }}\n"),
            verdict_cs=(
                f"    if (!__hh_{s})\n"
                f"        __post.Add({_cs(oid + ': построенный профиль не числится на запрошенной стене (topology)')});\n"),
            message="построенный профиль не числится на запрошенной стене (topology)",
            style="guard"),
        _type_id_witness(s, oid, human),
        WitnessCheck(
            # ОРИЕНТАЦИЯ — ЕДИНСТВЕННОЕ, ЧТО АВТОР СКАЗАЛ О ФОРМЕ, И ПОЭТОМУ
            # ЕДИНСТВЕННОЕ, ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ СВЕРХ ТОЖДЕСТВА. Ремарка
            # Autodesk («values set in the WallSweepInfo are ignored») делает
            # исход НЕОПРЕДЕЛЁННЫМ, а не заведомо ложным: канал ориентации —
            # аргумент конструктора, а не «set». Неопределённое утверждение
            # обязано быть ПРОВЕРЕНО, а не принято на веру: если живой Revit
            # распространяет ремарку и на конструктор, программа получит
            # типизированный неуспех — вместо молча построенного
            # горизонтального пояска там, где просили вертикальный руст.
            # Отказ читателя (`null`) — ТОЖЕ нарушение, а не молчание: мы
            # проверяем ровно то, что автор произнёс, и «не смогли прочитать»
            # не имеет права выглядеть как «сошлось».
            obligation_key="sweep_orientation",
            reader_cs=(
                f"    WallSweepInfo __ri_{s} = null;\n"
                f"    try {{ __ri_{s} = __el_{s}.GetWallSweepInfo(); }} catch {{ }}\n"),
            verdict_cs=(
                f"    if (__ri_{s} == null)\n"
                f"        __post.Add({_cs(oid + ': GetWallSweepInfo() не прочитался — подтвердить ориентацию нечем (semantic)')});\n"
                f"    else if (__ri_{s}.IsVertical != {vertical})\n"
                f"        __post.Add({_cs(oid + ': ориентация построенного профиля не та, что запрошена (semantic)')});\n"),
            message="ориентация построенного профиля не та, что запрошена (semantic)",
            style="guard"),
    ]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"sweep_kind\"] = __rev_{s} ? \"reveal\" : \"sweep\";\n"
        f"    __rb[\"orientation\"] = {_cs(orientation)};\n"
        f"    try {{ __rb[\"host_count\"] = (__hs_{s} == null) ? -1 : __hs_{s}.Count; }} catch {{ }}\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ if (__ty_{s} != null && __ty_{s}.Name != null) __rb[\"type_name\"] = __ty_{s}.Name; }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


# ── create_slab_edge ─────────────────────────────────────────────────────────

def emit_slab_edge(op: dict, ver: str, stamp: str,
                   isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Капельник/краевой профиль по периметру названной стороны плиты.

    `Autodesk.Revit.Creation.Document.NewSlabEdge(SlabEdgeType,
    ReferenceArray)` — 6/6, версионной ветки НЕТ.

    ДВЕ СТУПЕНИ, ОБЕ РЕШАЮТСЯ МОЩНОСТЬЮ (см. шапку модуля). Ни в одной точке
    нет «первого подходящего», поэтому недокументированный порядок граней и
    рёбер на результат не влияет вовсе.

    ПОЧЕМУ ПЕРИМЕТР СЧИТАЕТСЯ ТУТ ЖЕ, ХОТЯ В ВЕРДИКТ НЕ ЕДЕТ. Сумма длин рёбер
    — НАБЛЮДЕНИЕ в квитанции, а не утверждение: на стыках Revit подрезает
    профиль в ус, и насколько именно, никто не мерил. Сверить `HostedSweep.
    Length` с этой суммой можно было бы только назначенным допуском — ровно
    тем классом дефекта, который этот дом называет своим («bound authored by
    reasoning»). Поэтому в квитанции лежат ОБА числа, и живой прогон закроет
    вопрос за час, чего рассуждение не сделает никогда.
    """
    oid = op["id"]
    s = _safe(oid)
    side = op.get("side")
    if side not in SLAB_EDGE_SIDES:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED_ENUM, op_id=oid, field_name="side",
            got=side, candidates=list(SLAB_EDGE_SIDES),
            message_ru=(f"create_slab_edge: сторона {side!r} не поддержана — "
                        f"стороны НАЗЫВАЕТ САМ Revit (HostObjectUtils), и у "
                        f"горизонтального носителя их ровно две"))])
    human = "краевой профиль"
    host_decl, host_res = _host_resolve_cs(op, s, ver, oid, isolation,
                                           "HostObject", human)
    ty = _grounded_type_cs(op, s, oid, ver, "SlabEdgeType", human, isolation)
    face_call = _SIDE_CALL[side].format(ho=f"__ho_{s}")

    # `__named_`/`__bound_` — см. тот же комментарий у стенного профиля: их
    # читает КВИТАНЦИЯ, то есть область, следующая за блоком постусловий.
    # ОДНО ОБЪЯВЛЕНИЕ НА СТРОКУ, а не `int a = 0, b = 0;` — контракт областей
    # видимости разбирает объявления построчно, и вторая переменная в списке
    # для него НЕ ОБЪЯВЛЕНА (тот же шов, что у site_emit._boundary_bbox_witness).
    decl = (f"SlabEdge __el_{s} = null;\n"
            f"SlabEdgeType __ty_{s} = null;\n"
            f"List<Reference> __edges_{s} = null;\n"
            f"double __plen_{s} = 0.0;\n"
            f"int __named_{s} = 0;\n"
            f"int __bound_{s} = 0;\n"
            + host_decl)

    create = (
        f"// create_slab_edge {cs_line_comment_fragment(oid)}\n"
        + host_res
        + f"{ty}\n"
        # СТУПЕНЬ 1: сторона -> ровно одна грань.
        f"IList<Reference> __fs_{s} = null;\n"
        f"try {{ __fs_{s} = {face_call}; }} catch {{ }}\n"
        f"int __nf_{s} = (__fs_{s} == null) ? 0 : __fs_{s}.Count;\n"
        f"if (__nf_{s} == 0) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: у носителя нет грани со стороны «{side}» "
                f"(HostObjectUtils вернул пусто). СЛЕДУЮЩИЙ ХОД: проверь, что "
                f"host — плита или кровля, и назови другую сторону"),
            isolation) + " }\n"
        f"if (__nf_{s} > 1) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: со стороны «{side}» у носителя не одна грань, а ")
            + f" + __nf_{s}.ToString() + " + _cs(
                ". Компилятор НЕ выбирает за автора: порядок граней в теле не "
                "документирован, поэтому «первая подходящая» — число без "
                "смысла. СЛЕДУЮЩИЙ ХОД: краевой профиль по ступенчатому "
                "носителю строится отдельной операцией на каждую его плоскость"),
            isolation) + " }\n"
        f"Face __fc_{s} = null;\n"
        f"try {{ __fc_{s} = __ho_{s}.GetGeometryObjectFromReference(__fs_{s}[0]) as Face; }} catch {{ }}\n"
        f"if (__fc_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: грань со стороны «{side}» не читается как Face — "
                f"геометрию носителя прочитать не удалось"),
            isolation) + " }\n"
        # СТУПЕНЬ 2: грань -> ровно один контур.
        f"EdgeArrayArray __ls_{s} = __fc_{s}.EdgeLoops;\n"
        f"int __nl_{s} = (__ls_{s} == null) ? 0 : __ls_{s}.Size;\n"
        f"if (__nl_{s} != 1) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: у грани со стороны «{side}» не один контур, а ")
            + f" + __nl_{s}.ToString() + " + _cs(
                " — значит в носителе есть отверстия, и какое из колец "
                "обводить, решает автор, а не компилятор. СЛЕДУЮЩИЙ ХОД: "
                "назови ребро явно, когда у операции появится второй род "
                "селектора (сегодня его нет: вторая ступень называет ГРАНЬ, "
                "не ребро)"),
            isolation) + " }\n"
        f"__edges_{s} = new List<Reference>();\n"
        f"ReferenceArray __ra_{s} = new ReferenceArray();\n"
        f"foreach (Edge __ed_{s} in __ls_{s}.get_Item(0))\n"
        f"{{\n"
        f"    Reference __er_{s} = __ed_{s}.Reference;\n"
        f"    if (__er_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: у ребра периметра нет ссылки (Edge.Reference == "
                f"null) — по такому ребру профиль проложить нечем"),
            isolation) + " }\n"
        f"    Curve __ec_{s} = __ed_{s}.AsCurve();\n"
        f"    if (__ec_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: ребро периметра не читается как кривая"),
            isolation) + " }\n"
        f"    __plen_{s} += __ec_{s}.Length;\n"
        f"    __edges_{s}.Add(__er_{s});\n"
        f"    __ra_{s}.Append(__er_{s});\n"
        f"}}\n"
        f"if (__ra_{s}.Size == 0) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: контур грани не дал ни одного ребра"),
            isolation) + " }\n"
        # NewSlabEdge возвращает null, а не бросает (все шесть XML).
        f"__el_{s} = doc.Create.NewSlabEdge(__ty_{s}, __ra_{s});\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs("создание краевого профиля вернуло null — Revit не принял "
                "эти рёбра (NewSlabEdge документирован как возвращающий null "
                "при неудаче, а не бросающий)"),
            isolation) + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    checks: list[WitnessCheck] = [
        WitnessCheck(
            # НАСТОЯЩЕЕ ЧТЕНИЕ РЕЗУЛЬТАТА: у ПОСТРОЕННОГО профиля
            # спрашивается кривая, которую он проложил по каждой переданной
            # ссылке. Эмиттер подделать это не может ничем — он передал
            # ссылку, а кривую вернул элемент. `null` означает, что Revit эту
            # ссылку не взял, то есть капельник обводит НЕ ТОТ периметр,
            # который просили, и снаружи это неотличимо от успеха.
            obligation_key="slab_edge_binding",
            reader_cs=(
                f"    __named_{s} = (__edges_{s} == null) ? 0 : __edges_{s}.Count;\n"
                f"    if (__edges_{s} != null)\n"
                f"        foreach (Reference __wr_{s} in __edges_{s})\n"
                f"        {{\n"
                f"            Curve __wc_{s} = null;\n"
                f"            try {{ __wc_{s} = __el_{s}.get_ReferenceCurve(__wr_{s}); }} catch {{ }}\n"
                f"            if (__wc_{s} != null) __bound_{s}++;\n"
                f"        }}\n"),
            verdict_cs=(
                f"    if (__named_{s} == 0 || __bound_{s} != __named_{s})\n"
                f"        __post.Add(__bound_{s}.ToString() + \" из \" + __named_{s}.ToString() + \" \"\n"
                f"            + {_cs(oid + ': рёбер периметра связаны в построенном профиле (geometry)')});\n"),
            message="рёбер периметра связаны в построенном профиле (geometry)",
            style="guard"),
        _type_id_witness(s, oid, human),
    ]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"side\"] = {_cs(side)};\n"
        f"    __rb[\"edges_named\"] = __named_{s};\n"
        f"    __rb[\"edges_bound\"] = __bound_{s};\n"
        # ОБА ЧИСЛА, И НИ ОДНО ИЗ НИХ НЕ ВЕРДИКТ: периметр — то, что мы
        # передали, длина — то, что Revit построил. Их расхождение и есть та
        # величина подрезки в ус, которую никто не мерил; живой прогон
        # закроет вопрос, назначенный допуск — только замаскирует.
        f"    __rb[\"perimeter_mm\"] = MM(__plen_{s});\n"
        f"    try {{ __rb[\"sweep_length_mm\"] = MM(__el_{s}.Length); }} catch {{ }}\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ if (__ty_{s} != null && __ty_{s}.Name != null) __rb[\"type_name\"] = __ty_{s}.Name; }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback
