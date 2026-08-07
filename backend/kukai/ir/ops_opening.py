"""ops_opening — ПРОЁМ КАК ОТДЕЛЬНЫЙ ЭЛЕМЕНТ (`Autodesk.Revit.DB.Opening`).

Registry module — см. REGISTRY_MODULES.md. Операции добавляются СЮДА, а не в
spec.py. Эмиттер живёт в `opening_emit.py` (парный файл, ровно как
`struct_emit.py` к `ops_struct.py` и `arch_emit.py` к `ops_arch.py`);
`authoring.py` получает только импорт и одну строку в `_EMITTERS`.

═══ ПОВОД: ЕДИНСТВЕННАЯ МОЛЧАЛИВАЯ ПОТЕРЯ ВО ВСЁМ КОНВЕЙЕРЕ ════════════════

Обход восьми настоящих зданий (03.08.2026) нашёл РОВНО ОДНУ потерю, которая
не даёт ни отказа, ни атома, ни строки в карте причин. Проём в Revit делается
ДВУМЯ разными механизмами:

  * внутренней петлёй эскиза САМОГО НОСИТЕЛЯ — это мы умеем давно (60
    `create_floor` с непустым `holes` в трёх зданиях);
  * ОТДЕЛЬНЫМ элементом `Opening` — этого не было НИ В ОДНОМ ВИДЕ. Грепом по
    всем `.py` и `.cs` пакета: ноль упоминаний `OST_ShaftOpening`,
    `OST_SWallRectOpening`, `OST_FloorOpening`, `OST_RoofOpening`, `Opening`,
    `NewOpening`. Ни чтения, ни операции, ни отказа.

Перепись: 35 элементов в 3 зданиях из 6 — `OST_FloorOpening` 10,
`OST_ShaftOpening` 9, `OST_SWallRectOpening` 9, `OST_RoofOpening` 7.

ПОЧЕМУ ЭТО ХУДШИЙ КЛАСС ДЕФЕКТА. Элемент не извлекается ⇒ атома не даёт ⇒ его
нет ни в одном ранжире. Но НОСИТЕЛЬ при этом поднимается обычным
`create_floor`/`create_wall` и пересобирается СПЛОШНЫМ. Приёмка L2 этого не
ловит по построению: `acceptance.py` пишет прямым текстом, что ГЕОМЕТРИЮ НЕ
СМОТРИТ ВООБЩЕ. Снаружи тихо неверный результат неотличим от успеха.

═══ ЗАМЕР API (индекс ловушек + эталонные XML шести пакетов) ═══════════════

    Creation.Document.NewOpening(Element, CurveArray, eRefFace)      6/6
    Creation.Document.NewOpening(Element, CurveArray, bool)          6/6
    Creation.Document.NewOpening(Level, Level, CurveArray)           6/6
    Creation.Document.NewOpening(Wall, XYZ, XYZ)                     6/6
    Creation.FamilyItemFactory.NewOpening(Element, CurveArray)       6/6  (документ семейства, не проект)
    Opening.Host                                                     6/6
    Opening.IsRectBoundary / .BoundaryRect / .BoundaryCurves         6/6
    Opening.SketchId                                           2022-2026 (5/6)

Оси версий у операции НЕТ: всё, чем она пользуется, живёт на 2021-2026.
`Opening.SketchId` — единственный член со швом (нет на 2021), и мы им не
пользуемся ни в одну сторону; это записано здесь, чтобы следующий не начал
строить на нём чтение, не увидев шва.

Дословные ремарки спеки, которые меняют поведение:
  * «Slanted stacked walls do not support rectangular openings» — отказ Revit
    на наклонной/многослойной стене ЗАКОНЕН, и он обязан прийти ГРОМКО
    (NewOpening вернёт null или бросит ArgumentException ⇒ типизированный
    отказ, а не молчаливый пропуск);
  * `bPerpendicularFace`: «True if the profile is cut perpendicular to the
    intersecting face of the host. False if the profile is cut vertically» —
    смысл ДОКУМЕНТИРОВАН, поэтому параметр выражен (см. `cut` ниже), в
    отличие от уклона потолка, чей второй аргумент документация не
    объясняет и который поэтому в `create_ceiling` не заведён вовсе.

Форма вызовов сверена не только по документации, но и по ЗОЛОТОМУ КОДУ:
  * Autodesk SDK `NewOpenings/CS/ProfileWall.cs:65` —
    `m_docCreator.NewOpening(m_data, p1, p2)` (стена, две точки);
  * Autodesk SDK `NewOpenings/CS/ProfileFloor.cs:101` —
    `m_docCreator.NewOpening(m_data, curves, true)`, где `curves` собран
    замкнутой ломаной с ЯВНЫМ замыкающим сегментом;
  * BHoM `Revit_Core_Engine/Convert/Physical/ToRevit/Floor.cs:114,127` — тот
    же вызов на проде, и профиль там ПРОЕЦИРУЕТСЯ НА ПЛОСКОСТЬ ПЛИТЫ
    (`hole.IProject(slabPlane)`). Отсюда следствие для нашей эмиссии: отметку
    профиля нельзя брать нулём, её обязан дать САМ НОСИТЕЛЬ — она читается
    живьём как середина его габарита по Z (`opening_emit._emit_host_face`).

═══ ФОРМА: ДВА РОДА ИЗ ЧЕТЫРЁХ, И ЭТО РЕШЕНИЕ ═════════════════════════════

Четыре перегрузки — это четыре РАЗНЫХ рода проёма, а не четыре записи одного.
Разделены полем `variety` — тем же приёмом и тем же именем, что у
`create_foundation` (реестр держит слово «kind» за словарём родов объектов
Revit, SPEC 12.8; NAMING NOTE в `ops_struct.py`).

ВЗЯТЫ ДВА, У КАЖДОГО ПОЛНЫЙ СВИДЕТЕЛЬ (существование + принадлежность
запрошенному хозяину + габарит, и всё три читаются С ПОСТРОЕННОГО ЭЛЕМЕНТА):

  variety="wall_rect"  — прямоугольный проём в стене, `NewOpening(Wall, XYZ,
      XYZ)`. Свидетель: `Opening.Host.Id` == запрошенная стена (топология),
      `Opening.IsRectBoundary` == true, а углы `Opening.BoundaryRect` держат
      запрошенную полосу по Z и запрошенную ширину (геометрия; почему НЕ
      абсолютные X/Y — разобрано в шапке `opening_emit.py`). Перепись:
      `OST_SWallRectOpening` 9.

  variety="host_face" — проём по профилю в перекрытии/кровле/потолке,
      `NewOpening(Element, CurveArray, bool)`. Свидетель: `Opening.Host.Id` ==
      запрошенный носитель (топология) + габарит проёма против `outline`
      (геометрия). Перепись: `OST_FloorOpening` 10 + `OST_RoofOpening` 7 = 17.

НЕ ВЗЯТЫ ДВА, И ПРИЧИНА У КАЖДОГО НАЗВАНА (`VARIETIES_NOT_TAKEN` ниже — одна
таблица на шапку, отказ эмиттера и отказ чтения, чтобы три текста не
разъехались). Коротко:

  "shaft"   — `NewOpening(Level, Level, CurveArray)`. Строится легко, а
      ПРОВЕРИТЬ нечем: у шахты нет элемента-хозяина (`Opening.Host` для неё не
      носитель), а `BuiltInParameter` базового и верхнего ограничения шахты не
      документирован НИ В ОДНОМ из шести пакетов (проверено поиском по ВСЕМ
      задокументированным членам `BuiltInParameter` каждой версии —
      3338/3383/3493/3583/3665/3739 членов на 2021...2026, — совпадений по
      слову «shaft» НОЛЬ). Единственное, чем
      можно было бы подтвердить пару уровней, — совпадение Z-габарита с
      отметками уровней, а это ДОГАДКА о том, чего API не обещает: ровно тот
      дефект, из-за которого `create_beam` откатывал ПРАВИЛЬНО построенные
      балки, требуя от Revit обещания, которого он не давал. Строить без
      свидетеля запрещено §18.1. Перепись: `OST_ShaftOpening` 9.

  "framing" — `NewOpening(Element, CurveArray, eRefFace)`, проём в балке,
      связи или колонне. `eRefFace` — CenterX/CenterY/CenterZ, то есть
      профиль обязан лежать НА СРЕДИННОЙ ГРАНИ элемента, а её базис (начало и
      два орта) из плоского `outline` не выводится: пришлось бы читать
      геометрию хоста и решать, какая из трёх граней имелась в виду. Габарит
      без базиса не проверяем. Плюс замер: в переписи восьми зданий этого
      рода НОЛЬ элементов.

Правило выбора взято дословно: лучше два рода с полным свидетелем, чем четыре
с обещаниями.

═══ ПОЧЕМУ У ОПЕРАЦИИ НЕТ НИ ТИПА, НИ УРОВНЯ, НИ ПУЛА ═════════════════════

Ни одна из четырёх перегрузок не принимает ни `ElementType`, ни `Level`
(кроме шахты, где уровни — сама сигнатура). У `Opening` нет типа вовсе.
Поэтому `grounded=()`: заводить снапшот-пул под операцию, которая им не
пользуется, значило бы обещать разрешение, которого не происходит. Это второй
пишущий оп реестра без заземления (первый — `create_directshape`).

Уровень проёма выводит Revit из носителя; мы его не задаём и не обещаем.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)

#: Роды проёма, которые эта волна НЕ БЕРЁТ, и почему — ОДНА таблица на все
#: три места, где причина обязана прозвучать: шапка модуля, типизированный
#: отказ эмиттера (`opening_emit.OPENING_UNSUPPORTED_VARIETY`) и отказ стороны
#: чтения. Три отдельно набранных текста разъезжаются — этот дом уже платил за
#: это парностью категорий потолков и ограждений 29.07.
VARIETIES_NOT_TAKEN = freeze_registry_mapping({
    "shaft": (
        "шахта между уровнями (NewOpening(Level, Level, CurveArray), 6/6) "
        "строится, но НЕ ПРОВЕРЯЕТСЯ: элемента-хозяина у неё нет, а "
        "BuiltInParameter базового и верхнего ограничения шахты не "
        "документирован ни в одном из шести пакетов API — подтверждать пару "
        "уровней совпадением Z-габарита значило бы требовать от Revit "
        "обещания, которого он не давал (дефект create_beam), и откатывать "
        "правильно построенные шахты"),
    "framing": (
        "проём в балке/связи/колонне (NewOpening(Element, CurveArray, "
        "eRefFace), 6/6) требует профиль НА СРЕДИННОЙ ГРАНИ хоста: базис этой "
        "грани из плоского outline не выводится, а без базиса габарит "
        "непроверяем; в переписи восьми зданий этого рода ноль элементов"),
})

#: `create_opening.cut` словами <-> третий аргумент NewOpening(Element,
#: CurveArray, bool). ОДНА таблица на эмиттер и будущее чтение — тот же приём,
#: что `RAILING_PLACEMENT_MEMBERS` у волны ограждений. Смысл взят ДОСЛОВНО из
#: документации параметра `bPerpendicularFace`, а не угадан.
CUT_PERPENDICULAR_FACE = freeze_registry_mapping({
    "vertical": "false",        # «False if the profile is cut vertically»
    "perpendicular": "true",    # «True if the profile is cut perpendicular
                                #   to the intersecting face of the host»
})

OPS = [
    OpSpec(
            name="create_opening",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # Род проёма — закрытое множество ВЗЯТЫХ перегрузок, а не
                # вкусов. Незакрытые роды названы в VARIETIES_NOT_TAKEN.
                ParamSpec("variety", "enum", required=True,
                          choices=("wall_rect", "host_face")),
                # Носитель. `target_w` — тот же род ссылки, которым
                # create_window адресует свою стену, а create_railing —
                # лестницу: и на СУЩЕСТВУЮЩИЙ носитель («сделай проём в этой
                # плите»), и на построенный этой же программой. Для проёма
                # первый случай — основной: дырку режут в том, что уже стоит.
                # ref_kinds широкие намеренно: род носителя решает `variety`,
                # а РЕАЛЬНЫЙ класс проверяется в рантайме (`as Wall` для
                # wall_rect) типизированным отказом, а не догадкой на разборе.
                ParamSpec("host", "target_w",
                          ref_kinds=(ReferenceKind.ELEMENT,
                                     ReferenceKind.WALL)),
                # variety="wall_rect": ДВА ПРОТИВОПОЛОЖНЫХ УГЛА прямоугольника,
                # обязательно 3D (`pt_xyz`). Плоская точка молча уехала бы на
                # отметку 0, а высота проёма в стене — это ровно Z: подоконник
                # и перемычка. Тот же довод, по которому 3D требует
                # create_beam, и та же цена ошибки.
                ParamSpec("p0_mm", "pt_xyz"),
                ParamSpec("p1_mm", "pt_xyz"),
                # variety="host_face": замкнутый контур проёма в плане.
                ParamSpec("outline", "pts"),
                # variety="host_face": КАК режем. БЕЗ УМОЛЧАНИЯ намеренно —
                # вертикальный и перпендикулярный рез совпадают только на
                # плоском носителе, а на скате дают разные проёмы. Подставить
                # один за автора значило бы на кровле построить не то и
                # промолчать. Ровно та же причина, по которой `position`
                # обязателен у ограждения на лестнице.
                ParamSpec("cut", "enum",
                          choices=("vertical", "perpendicular")),
            ),
            capability=(("create", "element"),),
            # ОБЕЩАНО РОВНО ТО, ЧТО ПРОВЕРЯЕТСЯ, и каждое обещание читается С
            # ПОСТРОЕННОГО ЭЛЕМЕНТА, а не из наших же аргументов.
            # Точка с запятой РАЗДЕЛЯЕТ обязательства (translation_cert.py
            # бьёт post именно по ней) — внутри клаузулы её быть не должно.
            # ОБЕЩАНИЕ РОВНО ПО СВИДЕТЕЛЮ, включая то, чего свидетель НЕ
            # пришпиливает. У wall_rect сверяются АБСОЛЮТНЫЕ отметки верха и
            # низа и ШИРИНА проёма, а сдвиг вдоль стены — нет: Revit проецирует
            # заданные точки на плоскость привязки стены, и абсолютные X/Y
            # законно уезжают на половину её толщины. Обещать их значило бы
            # откатывать ВЕРНЫЙ проём — дефект create_beam дословно; разбор в
            # шапке opening_emit.py.
            post=("opening element exists (materialized or typed refusal); "
                  "Opening.Host == the host element the program asked for "
                  "(topology); "
                  "variety=wall_rect: IsRectBoundary and the BoundaryRect "
                  "corners hold the requested Z band and the requested width "
                  "along the wall (±50mm, geometry), while the absolute shift "
                  "along the wall stays deliberately unpinned; "
                  "variety=host_face: the BoundaryCurves extents == outline "
                  "extents for a vertical cut, and contain them for a "
                  "perpendicular cut (±50mm, geometry)"),
            writes_model=True,
            # Нечего заземлять: у проёма нет ни типа, ни уровня (см. шапку).
            grounded=(),
            # Одно число на обе ветви: ±50 мм — тот же габаритный допуск и тот
            # же ключ, что у перекрытия, потолка и фундаментной плиты. Проём
            # это вырезанный габарит, мерить его иначе, чем сам носитель, было
            # бы двумя правдами об одной величине.
            tolerances={"bbox_mm": 50.0},
        ),
]
