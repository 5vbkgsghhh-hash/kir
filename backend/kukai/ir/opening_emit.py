"""opening_emit — эмиссия `create_opening` (парный файл к `ops_opening.py`,
ровно как `struct_emit.py` к `ops_struct.py` и `arch_emit.py` к `ops_arch.py`).

Своя зона волны: этот модуль не трогает ни один чужой `ops_*.py` и ни один
чужой `*_emit.py`. `authoring.py` получает аддитивно импорт и ОДНУ строку в
`_EMITTERS` — тот же минимальный шов, которым подключились волны каркаса,
архитектуры и формы.

Переиспользовано из `authoring.py` БЕЗ ИЗМЕНЕНИЙ (импортом, не копией): `_cs`,
`_eid`, `_safe`, `_stamp_block`, `_readback_block`. Тот же список и та же
оговорка, что в шапках `struct_emit.py`/`arch_emit.py`: часть имён приватные, и
чистый шов лечится их повышением в `authoring.py`, а не копированием тел сюда.

═══ ЧТО ЗДЕСЬ ГЛАВНОЕ: СВИДЕТЕЛЬ ПРОВЕРЯЕТ РЕЗУЛЬТАТ, А НЕ ЭХО ВЫЗОВА ══════

Обе ветви читают ТРИ факта С ПОСТРОЕННОГО ЭЛЕМЕНТА:

  1. проём существует — `NewOpening` вернул не null, иначе типизированный
     отказ (`refuse_stmt`, никогда не молчаливый пропуск). Это же место ловит
     ЗАКОННЫЙ отказ Revit «Slanted stacked walls do not support rectangular
     openings» — он обязан прийти громко;
  2. проём ПРИНАДЛЕЖИТ ЗАПРОШЕННОМУ носителю — `Opening.Host.Id` сверяется с
     id того элемента, который мы САМИ только что разрешили. Не с аргументом
     программы, а с разрешённым элементом документа;
  3. габарит совпадает — читается `Opening.BoundaryRect` (прямоугольный проём)
     либо `Opening.BoundaryCurves` (профильный). Оба члена 6/6.

Допуск ровно один и приходит ТОЛЬКО объектом `emit_model.tolerance` (ЗАКОН
ПРОВЕНАНСА, `emit_model.py`): число, набранное рядом руками, витнес не
построит.

═══ ЧТО СВИДЕТЕЛЬ НАМЕРЕННО НЕ ПРОВЕРЯЕТ, И ПОЧЕМУ ═══════════════════════

`wall_rect`: сравниваются АБСОЛЮТНО отметки верха и низа (Z) и ШИРИНА проёма
(горизонтальное расстояние между углами). Положение проёма ВДОЛЬ стены в
абсолютных X/Y НЕ сверяется, и это не забывчивость.

Revit проецирует обе заданные точки на плоскость привязки стены. Плоскость
привязки — не обязательно та, на которой лежат заданные точки: у стены есть
толщина и настройка `WALL_KEY_REF_PARAM` (осевая, внутренняя грань, наружная
грань...), поэтому X/Y построенного прямоугольника ЗАКОННО отличаются от
заданных на половину толщины стены и больше. Сверять их дословно значило бы
откатывать ПРАВИЛЬНО построенный проём — ровно тот дефект, из-за которого
`create_beam` требовал от Revit обещания «опорный уровень == переданный», и
который стоил отката верных балок (см. комментарий в `struct_emit.emit_beam`).

Проекция на ВЕРТИКАЛЬНУЮ плоскость (а другой у прямоугольного проёма быть не
может — наклонные стены их не поддерживают по спеке) сохраняет РОВНО две
величины: координату Z и составляющую вдоль стены. Обе и проверяются. То, что
остаётся непришпиленным, — сдвиг вдоль стены, — назван здесь, а не спрятан.

`host_face`: габарит сверяется ПО-РАЗНОМУ у двух резов, и это следствие
документации, а не осторожность:
  * `cut="vertical"` — профиль режется вертикально, то есть план проёма ЕСТЬ
    наш контур: сверяется РАВЕНСТВО габаритов;
  * `cut="perpendicular"` — профиль режется перпендикулярно грани носителя, и
    на скате его план ШИРЕ контура (на плоском носителе — совпадает).
    Сверяется ВКЛЮЧЕНИЕ: габарит проёма обязан покрыть контур. Требовать
    здесь равенство значило бы отказывать верному проёму на любой скатной
    кровле.
Нижняя граница вместо равенства — не поблажка, а `Certainty.AT_LEAST` этого
дома, названная в `OpSpec.post` дословно.

═══ ЭСКИЗ CONTOUR: ЧТО СВИДЕТЕЛЬ РЕЗА ВПРАВЕ УТВЕРЖДАТЬ (09.08.2026) ═══════

`host_face` получил ВТОРОЙ вход профиля — `contour` рода `region` (эскиз
rect/l/poly с малыми дугами и точками-пересечениями осей). Эмиссия расходится
ровно в двух местах: сборке `CurveArray` (прямые звенья против Line/Arc из
канонических рёбер) и ЧИСЛЕ, с которым сверяется габарит. Всё остальное —
разрешение носителя, Regenerate, отметка профиля, null-отказ, штамп,
принадлежность хозяину, квитанция — общее, и это не экономия строк: две копии
хвоста разъезжаются, а разъехавшийся свидетель ничего не значит.

ГЛАВНЫЙ ВОПРОС ЭТОЙ ВОЛНЫ БЫЛ НЕ «КАК ПОСТРОИТЬ», А «ЧТО МОЖНО ЧЕСТНО
ПРОЧИТАТЬ С РЕЗА ПОСЛЕ КОММИТА». Ответ замерен по эталонным XML, а не выведен
рассуждением, и он УЖЕ, чем у плиты или потолка:

  * `Opening.Host` (6/6) — принадлежность. Полная сила, читается с проёма.
  * `Opening.BoundaryCurves` (6/6) — «geometry information for
    non-rectangular openings in project documents». Это ПЛАНОВАЯ ГРАНИЦА и
    больше ничего.
  * `Curve.GetEndPoint(int)` (6/6) — конец кривой ТОЧНО.
  * `Curve.Evaluate(double, bool)` (6/6) — «the point that matches a
    parameter along the curve», то есть точка ГАРАНТИРОВАННО НА границе.

Чего в этом наборе НЕТ и что поэтому не обещано:

  1. ГЛУБИНЫ РЕЗА И ФАКТА «МАТЕРИАЛ УБРАН» не читает ничто. `Opening` — это
     пустота: у неё нет тела, а `get_BoundingBox` документация ей не
     обещает (у `Ceiling`/`Floor` габарит есть, и потому у них свидетель
     СИЛЬНЕЕ — там сверяется габарит САМОГО ЭЛЕМЕНТА). Утверждать, что
     носитель прорезан, можно только живым Revit по объёму его тела до и
     после; офлайн такого утверждения не существует, и выдумывать его здесь
     нельзя.
  2. РАВЕНСТВА ГАБАРИТА С ДУГОВЫМ ЭСКИЗОМ. Экстремум дуги лежит ВНУТРИ
     кривой, а не в её конце, и достаётся только выборкой по параметру;
     выборка конечна, а плотности `Evaluate` API не обещает. Прочитанный
     габарит поэтому — НИЖНЯЯ оценка настоящего, и требовать от него точного
     `edges_bbox` значило бы назначить допуск на плотность выборки, то есть
     выдумать число (класс дефекта этого дома: `docspace._SHEET_LIMIT_MM`,
     `create_door.sill_mm`).

Поэтому габарит эскиза сверяется ПОЛОСОЙ, и обе её границы — обещания API,
а не наши предположения:

     edges_vertex_bbox  <=  прочитанный габарит  <=  edges_bbox      (± допуск)
     ^^^^ вершины отдаёт GetEndPoint ТОЧНО        ^^^^ ни одна точка границы
          => это НИЖНЯЯ граница, её обязаны              вертикального реза не
          накрыть                                        смеет выйти наружу

У профиля БЕЗ ДУГ обе границы совпадают, и полоса вырождается в РАВЕНСТВО —
ровно то, что делает прямая ветка. То есть контурная ветка не «слабее», она
обобщает прямую и совпадает с ней там, где прямая права.

НАЗВАННЫЙ ОСТАТОК: внутри полосы (это ровно стрелка дуги) свидетель не
различает — граница, воспроизведённая хордой вместо дуги, обе проверки
прошла бы. Что при этом ЛОВИТСЯ и ради чего выборка вообще эмитируется:
дуга, выгнутая НЕ В ТУ СТОРОНУ или НЕ ТОГО размера, выходит за верхнюю
границу и падает громко — то есть под контролем оказывается наша собственная
тригонометрия знака `bulge`, посчитанная в питоне. Выборка эмитируется
ТОЛЬКО когда в профиле есть дуга: у прямых звеньев концы и есть экстремумы,
и лишние точки не добавили бы ни одного факта.

`cut="perpendicular"` остаётся НИЖНЕЙ оценкой и в контурной ветке: на скате
план реза законно шире профиля, поэтому верхняя граница там не требуется —
её отсутствие названо, а не забыто.

═══ ОТМЕТКА ПРОФИЛЯ — ЕЁ ДАЁТ НОСИТЕЛЬ, А НЕ НОЛЬ ═════════════════════════

`outline` — контур В ПЛАНЕ (мм), без Z. Положить его на отметку 0 было бы
тихой неправдой: перекрытие 17-го этажа стоит не там, и профиль просто не
пересёк бы носителя. Золотой код обоих эталонов кладёт профиль НА ПЛОСКОСТЬ
НОСИТЕЛЯ (Autodesk SDK `NewOpenings` строит его из точек собственного эскиза
элемента; BHoM явно проецирует: `hole.IProject(slabPlane)`).

Поэтому отметка читается ЖИВЬЁМ у самого носителя: середина его габарита по Z.
Это не догадка, а следствие: у связного плитоподобного тела серединная
плоскость габарита пересекает тело при ЛЮБОМ уклоне, то есть профиль
гарантированно попадает внутрь носителя. Габарита нет — типизированный отказ,
а не ноль.
"""
from __future__ import annotations

from kukai.ir import contour as C
from kukai.ir.authoring import (
    _cs, _eid, _safe, _stamp_block, _readback_block,
)
from kukai.ir.emit_model import WitnessCheck, tolerance
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.diag import (
    Diagnostic, EMIT_CONTOUR_HOLES, EMIT_UNSUPPORTED_ENUM, KirRefusal,
    PARSE_EXCLUSIVE_FIELDS, PARSE_MISSING_FIELD)
from kukai.ir.ops_opening import (
    CONTOUR_HOLES_NOT_EXPRESSIBLE, CUT_PERPENDICULAR_FACE, VARIETIES_NOT_TAKEN)

#: Род проёма вне закрытого множества {wall_rect, host_face}.
#: Ремень поверх подтяжек: `enum`-choices ParamSpec уже ловит это на
#: `authoring.validate()` (KIR-T001), а эта проверка — защита в глубину внутри
#: самого эмиттера, ровно как `FOUNDATION_UNSUPPORTED_KIND` у волны каркаса и
#: `RAILING_UNSUPPORTED_VARIETY` у волны архитектуры. Сюда попадёт тот, кто
#: расширит `choices`, не дописав ветку: пусть падает ГРОМКО, а не строит
#: молча не то. Причина по каждому невзятому роду берётся из ОДНОЙ таблицы
#: `ops_opening.VARIETIES_NOT_TAKEN`, а не набирается здесь заново.

#: Эскиз с ОТВЕРСТИЯМИ у проёма: у `NewOpening` профиль ровно один, петель
#: список не бывает. Не «ещё не сделали», а «нечем сказать» — причина берётся
#: из ОДНОЙ таблицы `ops_opening.CONTOUR_HOLES_NOT_EXPRESSIBLE`, чтобы шапка
#: реестра и отказ эмиттера не разъехались. Отдельный код, а не E007: тот
#: значит «род проёма не взят», и путать «нет такого рода» с «у взятого рода
#: нет такой формы» значит отправить автора чинить не то.


def _host_id_cs(op: dict, ver: str, oid: str) -> str:
    """C#-выражение id носителя: пришпиленный id либо ссылка внутри программы.

    Оба пути ведут через `doc.GetElement(...)` НАМЕРЕННО, а не приведением
    переменной соседнего опа напрямую: `__el_<ref> as Wall` для ссылки на
    перекрытие — межродовое приведение (CS0039), то есть отказ КОМПИЛЯТОРА C#
    вместо типизированного отказа KIR. Через `Id` компилируется всегда, а
    неверный род ловится живой проверкой `as Wall` ниже — там, где отказ можно
    назвать по-человечески.
    """
    host = op.get("host") or {}
    if host.get("by") == "ref":
        return "__el_" + _safe(str(host.get("value"))) + ".Id"
    return _eid(host["value"], ver, oid)


def _require(op: dict, field: str, message: str) -> None:
    """Условно обязательное поле: типизированный KIR-P005, а не голый KeyError.

    Тот же шов и та же причина, что у `emit_foundation`/`emit_railing`:
    `ParamSpec.required` не умеет «обязателен только у этого рода», а голый
    KeyError доехал бы наверх как KIR-P000 «внутренняя ошибка» — fail-closed,
    но диагностика хуже.
    """
    if op.get(field) is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=op.get("id"), field_name=field,
            message_ru=message)])


def _host_witness(s: str, oid: str, host_var: str, human: str) -> WitnessCheck:
    """«Проём принадлежит ЗАПРОШЕННОМУ носителю» — топология, прочитанная у
    самого проёма (`Opening.Host`, 6/6), а не у нашего намерения.

    ``human`` — ГОТОВАЯ падежная форма («запрошенной стене», «запрошенному
    носителю»), а не корень: склеивать русское сообщение из «запрошенному» +
    существительного значит печатать «запрошенному стене». Диагностика, за
    которую стыдно, читается как небрежность и в остальном тоже.
    """
    return WitnessCheck(
        obligation_key="host",
        reader_cs=f"    var __hh_{s} = __el_{s}.Host;\n",
        verdict_cs=(
            f"    if (__hh_{s} == null)\n"
            f"        __post.Add({_cs(oid + ': у проёма нет носителя (topology)')});\n"
            f"    else if (__hh_{s}.Id.ToString() != {host_var}.Id.ToString())\n"
            f"        __post.Add({_cs(oid + ': проём не принадлежит ' + human + ' (topology)')});\n"),
        message=f"проём не принадлежит {human} (topology)",
        style="else_block")


# ── variety="wall_rect" ─────────────────────────────────────────────────────

def _emit_wall_rect(op: dict, ver: str, stamp: str,
                    isolation: str) -> tuple[str, str, list, str]:
    """Прямоугольный проём в стене.

    `Autodesk.Revit.Creation.Document.NewOpening(Wall, XYZ, XYZ)` — 6/6,
    форма сверена с золотым образцом Autodesk SDK
    (`NewOpenings/CS/ProfileWall.cs:65`: `m_docCreator.NewOpening(m_data,
    p1, p2)`).
    """
    oid = op["id"]
    s = _safe(oid)
    # ЭСКИЗ ЭТОМУ РОДУ СКАЗАТЬ НЕЧЕМ, И МОЛЧА ВЫБРОСИТЬ ЕГО НЕЛЬЗЯ.
    # `NewOpening(Wall, XYZ, XYZ)` профиля не принимает вовсе — род проёма
    # задаётся двумя углами. Принять `contour` и не посмотреть на него значило
    # бы построить прямоугольник там, где автор написал дугу, и промолчать:
    # ровно тот молчаливый исход, ради запрета которого волна проёма и
    # заводилась. Отказ типизированный и по коду взаимного исключения — род и
    # эскиз действительно несовместимы.
    if op.get("contour") is not None:
        raise KirRefusal([Diagnostic(
            code=PARSE_EXCLUSIVE_FIELDS, op_id=oid, field_name="contour",
            expected="variety=host_face", got="variety=wall_rect",
            message_ru=(
                "create_opening(variety=wall_rect): contour несовместим с "
                "этим родом — NewOpening(Wall, XYZ, XYZ) профиля не "
                "принимает вообще, прямоугольный проём в стене задаётся "
                "двумя противоположными углами (p0_mm/p1_mm). Эскиз "
                "работает у variety=host_face"))])
    _require(op, "host",
             "create_opening(variety=wall_rect): host обязателен — это и есть "
             "стена, в которой режется проём")
    _require(op, "p0_mm",
             "create_opening(variety=wall_rect): p0_mm обязателен — угол "
             "прямоугольника")
    _require(op, "p1_mm",
             "create_opening(variety=wall_rect): p1_mm обязателен — "
             "противоположный угол прямоугольника")
    p0, p1 = op["p0_mm"], op["p1_mm"]
    host_id = _host_id_cs(op, ver, oid)
    decl = (f"Opening __el_{s} = null;\n"
            f"Wall __hw_{s} = null;")
    create = (
        f"// create_opening(wall_rect) {cs_line_comment_fragment(oid)}\n"
        f"__hw_{s} = doc.GetElement({host_id}) as Wall;\n"
        f"if (__hw_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('носитель проёма не читается как стена (модель изменилась после grounding или id указывает не на стену)'), isolation)} }}\n"
        # REGENERATE ПЕРЕД РЕЗОМ, и это не украшение. Носитель бывает создан
        # ЭТОЙ ЖЕ программой (`host: {by: ref}`), а NewOpening режет по
        # геометрии, которой у несрегенерированного элемента ещё нет.
        # Продовый BHoM делает ровно это (`ToRevit/Floor.cs:108` —
        # `document.Regenerate()` непосредственно перед NewOpening).
        # Ставится безусловно, а не только на ref-ветке: разная эмиссия у
        # двух форм одного и того же селектора — это лишняя развилка, а
        # лишний Regenerate внутри уже открытой транзакции ничего не стоит.
        f"doc.Regenerate();\n"
        f"__el_{s} = doc.Create.NewOpening(__hw_{s}, "
        f"P({p0[0]}, {p0[1]}, {p0[2]}), P({p1[0]}, {p1[1]}, {p1[2]}));\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('создание прямоугольного проёма в стене вернуло null (наклонные и многослойные стены прямоугольных проёмов не поддерживают — ремарка спеки)'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    tol = tolerance("create_opening", "bbox_mm")
    zmin, zmax = min(p0[2], p1[2]), max(p0[2], p1[2])
    width = ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5
    checks: list[WitnessCheck] = [
        _host_witness(s, oid, f"__hw_{s}", "запрошенной стене"),
        WitnessCheck(
            obligation_key="rect_extent",
            # ЧИТАЕТСЯ ГРАНИЦА САМОГО ПРОЁМА. `BoundaryRect` документирован
            # как «geometry information if the opening boundary is a rect» и
            # как null при `IsRectBoundary == false`, поэтому обе величины
            # снимаются вместе: прямоугольность — такой же результат, как
            # размер. Индексирование [0]/[1] и Linq-`Count()` работают и на
            # `IList<XYZ>`, и на массиве — вид коллекции в документации не
            # назван, а `var` сам по себе не доказывает ничего (урок волны
            # ограждений: `var __r = ...` компилируется при любом типе).
            reader_cs=(
                f"    var __br_{s} = __el_{s}.BoundaryRect;\n"
                f"    int __brn_{s} = __br_{s} == null ? 0 : "
                f"System.Linq.Enumerable.Count(__br_{s});\n"),
            verdict_cs=(
                f"    if (!__el_{s}.IsRectBoundary || __brn_{s} != 2)\n"
                f"        __post.Add({_cs(oid + ': граница проёма не прямоугольник (geometry)')});\n"
                f"    else\n    {{\n"
                f"        double __bz0_{s} = Math.Min(MM(__br_{s}[0].Z), MM(__br_{s}[1].Z));\n"
                f"        double __bz1_{s} = Math.Max(MM(__br_{s}[0].Z), MM(__br_{s}[1].Z));\n"
                f"        double __bw_{s} = Math.Sqrt(\n"
                f"            Math.Pow(MM(__br_{s}[0].X) - MM(__br_{s}[1].X), 2)\n"
                f"          + Math.Pow(MM(__br_{s}[0].Y) - MM(__br_{s}[1].Y), 2));\n"
                f"        if (Math.Abs(__bz0_{s} - {zmin}) > {tol} || Math.Abs(__bz1_{s} - {zmax}) > {tol}\n"
                f"            || Math.Abs(__bw_{s} - {width}) > {tol})\n"
                f"            __post.Add({_cs(oid + ': rect extents mismatch (geometry)')});\n"
                f"    }}\n"),
            message="rect extents mismatch (geometry)",
            tol=tol, style="else_block"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp)


# ── variety="host_face" ─────────────────────────────────────────────────────

def _profile_curve_array(outline: list, name: str, z_var: str) -> list[str]:
    """ЗАМКНУТЫЙ профиль в `CurveArray` на РАНТАЙМНОЙ отметке `z_var`.

    Свой помощник, а не `_loop_pts`: тот строит `CurveLoop` (его требуют
    `Floor.Create`/`Ceiling.Create`), а `NewOpening` принимает `CurveArray` —
    другой тип, и подменять один другим нечем. Плюс отметка здесь ВЫРАЖЕНИЕ, а
    не литерал: `P(x, y, z)` пропустил бы её через `U()` второй раз, а она уже
    во внутренних единицах (прочитана у носителя).

    Замыкающий сегмент добавляется ЯВНО — ровно как в золотом образце Autodesk
    (`ProfileFloor.cs:95-99` дописывает последний отрезок от последней точки к
    первой). Кольцо здесь ОБЯЗАНО быть замкнутым: это профиль выреза, а не
    путь ограждения.

    ЕДИНИЦЫ ОТМЕТКИ ПОМЕНЯЛИСЬ ПРИ СЛИЯНИИ 09.08.2026, и докстрока выше про
    «уже во внутренних единицах» была верна ровно до него. `__z_` теперь
    МИЛЛИМЕТРОВЫЙ — его приводит `MM(...)` у источника, — потому что вторая
    ветка того же опа ушла на общий сборщик `contour._edge_curve_cs`, который
    ждёт миллиметры, как и весь язык. Две ветки ОДНОГО опа с разными
    единицами отметки — это молчаливо-неверный результат, ждущий своего
    первого проёма выше нулевого этажа; поэтому здесь тоже `U()`.
    """
    out = [f"CurveArray {name} = new CurveArray();"]
    n = len(outline)
    for k in range(n):
        a, b = outline[k], outline[(k + 1) % n]
        out.append(
            f"{name}.Append(Line.CreateBound("
            f"new XYZ(U({a[0]}), U({a[1]}), U({z_var})), "
            f"new XYZ(U({b[0]}), U({b[1]}), U({z_var}))));")
    return out


def _boundary_extents_reader(s: str, samples: int) -> str:
    """C#, снимающий ПЛАНОВЫЙ габарит с границы САМОГО ПРОЁМА.

    Читается `Opening.BoundaryCurves` — «geometry information for
    non-rectangular openings in project documents», то есть у профильного
    проёма он ЗАПОЛНЕН ПО СПЕЦИФИКАЦИИ, тогда как про `get_BoundingBox` у
    `Opening` документация не обещает ничего. Свидетель обязан читать то, что
    API обещает отдать.

    ``samples`` — сколько точек снимается С КАЖДОЙ кривой:

      * ``0`` — только концы (`GetEndPoint`, 6/6). Для профиля БЕЗ ДУГ этого
        достаточно ПО СУЩЕСТВУ: каждое звено прямое, и любая его точка лежит
        внутри габарита собственных концов. Это же ровно та эмиссия, что
        стояла здесь до 09.08 — прямая ветка обязана остаться байт в байт;
      * ``N > 0`` — `Evaluate(k/N, true)`, «the point that matches a parameter
        along the curve» (6/6), то есть точки ГАРАНТИРОВАННО НА границе,
        включая внутренность дуги. Нужны они РОВНО для верхней границы полосы
        (см. шапку модуля): точка, вылезшая за габарит эскиза, — громкий
        отказ, и именно так ловится дуга, выгнутая не в ту сторону.

    Плотность N берётся у `contour.ARC_SAMPLES` — тем же числом, которым
    канон разворачивает дугу в своих статических законах. Новое число здесь
    было бы вторым ответом на вопрос «во сколько точек мы смотрим на дугу».

    ``IsBound`` (6/6) — потому что `Evaluate(..., normalized: true)` на
    неограниченной кривой бросает по документации. Неограниченная кривая
    просто не даёт точек; если их не даст НИ ОДНА, `__on_` останется нулём и
    вердикт скажет об этом ГРОМКО, а не тихо примет пустой габарит.

    ОДИН ДЕКЛАРАТОР НА ОПЕРАТОР, а не ``double a = 0, b = 0;``. Это не стиль:
    контракт области видимости (`_DECL` в test_emitter_scope_contract) читает
    объявление регуляркой и видит в списке только ПЕРВОЕ имя — остальные
    выглядели бы «нигде не объявленными», то есть контракт молча ослаб бы
    ровно там, где эмиттер усложняется.
    """
    if samples:
        walk = (f"            if (!__c_{s}.IsBound) continue;\n"
                f"            for (int __k_{s} = 0; __k_{s} <= {samples}; __k_{s}++)\n            {{\n"
                f"                var __pt_{s} = __c_{s}.Evaluate(__k_{s} / {samples}.0, true);\n")
    else:
        walk = (f"            for (int __k_{s} = 0; __k_{s} < 2; __k_{s}++)\n            {{\n"
                f"                var __pt_{s} = __c_{s}.GetEndPoint(__k_{s});\n")
    return (
        f"    var __bc_{s} = __el_{s}.BoundaryCurves;\n"
        f"    double __ox0_{s} = 0;\n"
        f"    double __ox1_{s} = 0;\n"
        f"    double __oy0_{s} = 0;\n"
        f"    double __oy1_{s} = 0;\n"
        f"    int __on_{s} = 0;\n"
        f"    if (__bc_{s} != null)\n    {{\n"
        f"        foreach (Curve __c_{s} in __bc_{s})\n        {{\n"
        + walk +
        f"                double __px_{s} = MM(__pt_{s}.X);\n"
        f"                double __py_{s} = MM(__pt_{s}.Y);\n"
        f"                if (__on_{s} == 0) {{ __ox0_{s} = __px_{s}; __ox1_{s} = __px_{s};"
        f" __oy0_{s} = __py_{s}; __oy1_{s} = __py_{s}; }}\n"
        f"                else {{ __ox0_{s} = Math.Min(__ox0_{s}, __px_{s});"
        f" __ox1_{s} = Math.Max(__ox1_{s}, __px_{s});\n"
        f"                       __oy0_{s} = Math.Min(__oy0_{s}, __py_{s});"
        f" __oy1_{s} = Math.Max(__oy1_{s}, __py_{s}); }}\n"
        f"                __on_{s}++;\n"
        f"            }}\n        }}\n    }}\n")


def _emit_host_face(op: dict, ver: str, stamp: str,
                    isolation: str) -> tuple[str, str, list, str]:
    """Проём по профилю в перекрытии, кровле или потолке.

    `Autodesk.Revit.Creation.Document.NewOpening(Element, CurveArray, bool)` —
    6/6, «Creates a new opening in a roof, floor and ceiling». Форма сверена с
    золотым образцом Autodesk SDK (`NewOpenings/CS/ProfileFloor.cs:101`) и с
    продовым BHoM (`ToRevit/Floor.cs:114,127`).
    """
    oid = op["id"]
    s = _safe(oid)
    _require(op, "host",
             "create_opening(variety=host_face): host обязателен — это и есть "
             "перекрытие/кровля/потолок, в котором режется проём")
    # ФОРМА СКАЗАНА РОВНО ОДИН РАЗ. «Оба сразу» отказывает план (KIR-P007,
    # правило читается из реестра: параметр рода `pts` и параметр рода
    # `region` у одной операции). «Ни одного» ПЛАН СКАЗАТЬ НЕ МОЖЕТ: у
    # операции с развилкой `variety` обязательность условна по роду, а
    # компилятор родов не разбирает — у wall_rect формы нет ни в каком виде,
    # и общий отказ «форма не задана» обвинял бы верную программу. Поэтому
    # нижняя половина взаимной обязательности живёт ЗДЕСЬ, в ветке рода, и
    # называет ОБА входа: автор, забывший форму, обязан узнать про оба.
    region = op.get("__region__")
    if region is None and op.get("outline") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="outline",
            expected="outline ЛИБО contour",
            message_ru=(
                "create_opening(variety=host_face): форма проёма не задана — "
                "нужен либо outline (замкнутая ломаная из 3..64 точек в "
                "плане), либо contour (эскиз CONTOUR: rect/l/poly, малые "
                "дуги, точки-пересечения осей)"))])
    if region is not None and region["holes"]:
        # НЕ ПРОПУСК, А ОТКАЗ, и причина — из ОДНОЙ таблицы реестра.
        raise KirRefusal([Diagnostic(
            code=EMIT_CONTOUR_HOLES, op_id=oid, field_name="contour.holes",
            got=len(region["holes"]),
            message_ru=(f"create_opening(variety=host_face): отверстия внутри "
                        f"эскиза невыразимы — {CONTOUR_HOLES_NOT_EXPRESSIBLE}"))])
    _require(op, "cut",
             "create_opening(variety=host_face): cut обязателен — "
             "вертикальный и перпендикулярный рез совпадают ТОЛЬКО на плоском "
             "носителе, а на скате дают разные проёмы; выбрать один за автора "
             "значило бы построить не то и промолчать")
    # Ремень поверх подтяжек, как у развилки `variety`: `enum`-choices уже
    # закрыли множество на разборе, но таблица резов и список choices живут
    # рядом и могут разъехаться. Голый KeyError доехал бы наверх как
    # KIR-P000 «внутренняя ошибка» — fail-closed, но диагностика хуже.
    if op["cut"] not in CUT_PERPENDICULAR_FACE:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED_ENUM, op_id=oid, field_name="cut",
            got=op["cut"], candidates=sorted(CUT_PERPENDICULAR_FACE),
            message_ru=(f"create_opening: рез {op['cut']!r} не поддержан — у "
                        f"NewOpening(Element, CurveArray, bool) ровно два "
                        f"значения третьего аргумента"))])
    perpendicular = CUT_PERPENDICULAR_FACE[op["cut"]]
    host_id = _host_id_cs(op, ver, oid)
    decl = (f"Opening __el_{s} = null;\n"
            f"Element __hst_{s} = null;")
    if region is not None:
        # Эскиз CONTOUR. Вся тригонометрия дуг посчитана в питоне на стадии
        # ground: в C# уезжают три ЛИТЕРАЛЬНЫЕ точки на дугу (Arc.Create(
        # start, end, точка-на-дуге), 6/6), поэтому версии здесь не
        # расходятся. Отметка профиля — то же рантаймное выражение, что и у
        # прямой ветки: её даёт носитель, а не ноль.
        edges = region["outer"]
        geo = C.emit_curvearray_cs(edges, f"__ca_{s}",
                                   z=f"__z_{s}").split("\n")
    else:
        geo = _profile_curve_array(op["outline"], f"__ca_{s}", f"__z_{s}")
    create = (
        f"// create_opening(host_face) {cs_line_comment_fragment(oid)}\n"
        f"__hst_{s} = doc.GetElement({host_id});\n"
        f"if (__hst_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('носитель проёма не найден (модель изменилась после grounding)'), isolation)} }}\n"
        f"doc.Regenerate();\n"
        f"var __hbb_{s} = __hst_{s}.get_BoundingBox(null);\n"
        f"if (__hbb_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('у носителя проёма нет габарита — отметку профиля взять неоткуда, а нулевая была бы тихой неправдой'), isolation)} }}\n"
        # ЕДИНИЦЫ ПРИВОДЯТСЯ ЗДЕСЬ, У ИСТОЧНИКА (слияние 09.08.2026).
        # `BoundingBoxXYZ` отдаёт ВНУТРЕННИЕ единицы, а общий сборщик рёбер
        # `contour._edge_curve_cs` собирает точку через `P()`, то есть ждёт
        # МИЛЛИМЕТРЫ — как и вторая ветка того же помощника (каркас кладёт
        # `MM(__lv.Elevation)`). Без `MM` здесь отметка прошла бы `U()`
        # вторым разом: профиль уехал бы примерно в 304.8 раза выше, C#
        # скомпилировался бы одинаково на всех шести версиях, и увидеть это
        # можно было бы только на живой модели выше нулевого этажа.
        f"double __z_{s} = MM((__hbb_{s}.Min.Z + __hbb_{s}.Max.Z) / 2.0);\n"
        + "\n".join(geo) + "\n"
        f"__el_{s} = doc.Create.NewOpening(__hst_{s}, __ca_{s}, {perpendicular});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('создание проёма по профилю вернуло null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    tol = tolerance("create_opening", "bbox_mm")
    if region is not None:
        # ГАБАРИТ ЭСКИЗА — ПОЛОСА МЕЖДУ ДВУМЯ ОБЕЩАНИЯМИ API, а не одно
        # число (разбор — в шапке модуля):
        #   * `edges_bbox` знает кардинальные экстремумы дуг и потому
        #     ВЕРХНЯЯ граница: точка границы вертикального реза за неё не
        #     выходит;
        #   * `edges_vertex_bbox` берёт только вершины и потому НИЖНЯЯ:
        #     вершину `GetEndPoint` отдаёт ТОЧНО, без всякой выборки.
        # У профиля без дуг обе совпадают, и полоса вырождается в равенство —
        # ровно в ту проверку, которую делает прямая ветка.
        ex0, ey0, ex1, ey1 = (round(v, 1) for v in C.edges_bbox(edges))
        vx0, vy0, vx1, vy1 = (round(v, 1)
                              for v in C.edges_vertex_bbox(edges))
        # Выборка ТОЛЬКО при дуге: у прямых звеньев концы и есть экстремумы,
        # и лишние точки не добавили бы ни одного факта — зато развели бы
        # эмиссию двух эквивалентных профилей.
        samples = (C.ARC_SAMPLES
                   if any(abs(b) >= C.STRAIGHT_BULGE_EPS for _p0, _p1, b in edges) else 0)
        if op["cut"] == "vertical":
            human_verdict = "opening extents leave the contour band (geometry)"
            compare = (
                f"        if (__ox0_{s} < {ex0} - {tol} || __ox0_{s} > {vx0} + {tol}\n"
                f"            || __ox1_{s} > {ex1} + {tol} || __ox1_{s} < {vx1} - {tol}\n"
                f"            || __oy0_{s} < {ey0} - {tol} || __oy0_{s} > {vy0} + {tol}\n"
                f"            || __oy1_{s} > {ey1} + {tol} || __oy1_{s} < {vy1} - {tol})\n"
                f"            __post.Add({_cs(oid + ': opening extents leave the contour band (geometry)')});\n")
        else:
            # Перпендикулярный рез на скате законно ШИРЕ профиля, поэтому
            # верхней границы здесь нет — остаётся нижняя, и это названо, а
            # не забыто.
            human_verdict = "opening extents do not cover the contour (geometry)"
            compare = (
                f"        if (__ox0_{s} > {vx0} + {tol} || __ox1_{s} < {vx1} - {tol}\n"
                f"            || __oy0_{s} > {vy0} + {tol} || __oy1_{s} < {vy1} - {tol})\n"
                f"            __post.Add({_cs(oid + ': opening extents do not cover the contour (geometry)')});\n")
        obligation_key = "bbox_contour"
    else:
        outline = op["outline"]
        samples = 0
        xs = [pt[0] for pt in outline]
        ys = [pt[1] for pt in outline]
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        if op["cut"] == "vertical":
            human_verdict = "opening extents mismatch (geometry)"
            compare = (
                f"        if (Math.Abs(__ox0_{s} - {xmin}) > {tol} || Math.Abs(__ox1_{s} - {xmax}) > {tol}\n"
                f"            || Math.Abs(__oy0_{s} - {ymin}) > {tol} || Math.Abs(__oy1_{s} - {ymax}) > {tol})\n"
                f"            __post.Add({_cs(oid + ': opening extents mismatch (geometry)')});\n")
        else:
            # Перпендикулярный рез на скате даёт план ШИРЕ контура — сверяется
            # ВКЛЮЧЕНИЕ, а не равенство (см. шапку модуля). Тот же допуск.
            human_verdict = "opening extents do not cover the outline (geometry)"
            compare = (
                f"        if (__ox0_{s} > {xmin} + {tol} || __ox1_{s} < {xmax} - {tol}\n"
                f"            || __oy0_{s} > {ymin} + {tol} || __oy1_{s} < {ymax} - {tol})\n"
                f"            __post.Add({_cs(oid + ': opening extents do not cover the outline (geometry)')});\n")
        obligation_key = "bbox"
    checks: list[WitnessCheck] = [
        _host_witness(s, oid, f"__hst_{s}", "запрошенному носителю"),
        WitnessCheck(
            # КЛЮЧИ РАЗНЫЕ У ДВУХ ВХОДОВ ФОРМЫ, и это не педантизм: условное
            # обязательство разряжается ровно ОТСУТСТВИЕМ своего свидетеля
            # (`certify_op`), поэтому общий ключ на две взаимоисключающие
            # ветви объявил бы витнес соседней ветви «лишним». Тот же довод,
            # по которому габаритные ключи `rect_extent` и `bbox` у двух
            # родов проёма тоже разные.
            obligation_key=obligation_key,
            # ЧИТАЕТСЯ ГРАНИЦА САМОГО ПРОЁМА, а не габарит элемента —
            # разбор и оба режима выборки в `_boundary_extents_reader`.
            reader_cs=_boundary_extents_reader(s, samples),
            verdict_cs=(
                f"    if (__on_{s} == 0)\n"
                f"        __post.Add({_cs(oid + ': у проёма нет граничных кривых (geometry)')});\n"
                f"    else\n    {{\n"
                + compare +
                f"    }}\n"),
            # Сообщение — ветвевое: у равенства и у включения РАЗНЫЙ
            # вердикт, и один текст на оба врал бы аудиту про то, что
            # проверялось.
            message=human_verdict,
            tol=tol, style="else_block"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp)


# ── развилка ────────────────────────────────────────────────────────────────

def emit_opening(op: dict, ver: str, stamp: str,
                 isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Развилка по закрытому множеству {wall_rect, host_face}.

    Значение вне множества — типизированный отказ, НАЗЫВАЮЩИЙ причину для тех
    родов, которые волна сознательно не взяла (`VARIETIES_NOT_TAKEN`): «не
    поддержано» без причины неотличимо от «забыли», а невзятый род обязан
    отличаться от несуществующего.
    """
    variety = op.get("variety")
    if variety == "wall_rect":
        return _emit_wall_rect(op, ver, stamp, isolation)
    if variety == "host_face":
        return _emit_host_face(op, ver, stamp, isolation)
    _nt = VARIETIES_NOT_TAKEN.get(variety)
    why = _nt.reason if _nt else None
    raise KirRefusal([Diagnostic(
        code=EMIT_UNSUPPORTED_ENUM, op_id=op.get("id"),
        field_name="variety", got=variety,
        candidates=["wall_rect", "host_face"],
        message_ru=(f"create_opening: род проёма {variety!r} не поддержан — {why}"
                    if why else
                    f"create_opening: род проёма {variety!r} не поддержан "
                    f"(взяты wall_rect и host_face — у остальных перегрузок "
                    f"NewOpening нет полного свидетеля, см. ops_opening.py)"))])
