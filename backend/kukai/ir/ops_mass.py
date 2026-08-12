"""ops_mass — КОНЦЕПТУАЛЬНАЯ МАССА: единственная дверь из неё в НАСТОЯЩИЙ BIM.

Registry module — операции добавляются СЮДА, а не в spec.py. Эмиттер живёт в
mass_emit.py (парный файл, как ops_sweep.py + sweep_emit.py у волны профилей).

═══ ГЛАВНЫЙ ЗАМЕР ЭТОЙ ВОЛНЫ: ДВЕРЬ, А НЕ КОМНАТА ══════════════════════════

Перепись 09.08 назвала семейство «свободные формы и массы» почти слепым (2 из
12) и оставила гипотезу: шесть форм массы, `DividedSurface`, `DividedPath`.
Замер компиляцией против настоящих сборок 2021-2026 (живой Roslyn :52412,
10.08) эту гипотезу НЕ подтвердил, и расхождение — не деталь, а весь ответ.

ШЕСТЬ ФОРМ МАССЫ НЕДОСТИЖИМЫ НЕ ПО УСЛОВИЮ ВНУТРИ ВЫЗОВА, А ПО ДВЕРИ. Все
шесть живут ТОЛЬКО на `Autodesk.Revit.Creation.FamilyItemFactory`, то есть на
`doc.FamilyCreate`, и ни одна — на `doc.Create` (CS1061 на всех шести):

  doc.Create.NewExtrusionForm / NewRevolveForms / NewSweptBlendForm /
  NewLoftForm / NewFormByThickenSingleSurface / NewFormByCap   → 0/6  CS1061
  doc.FamilyCreate.<те же шесть>                               → есть (CS7036)
  doc.Create.NewSweepForm И doc.FamilyCreate.NewSweepForm      → 0/6  CS1061
      ← ПАМЯТЬ: такого члена НЕТ ВООБЩЕ; протяжённая форма — NewSweptBlendForm

А сам аксессор `Document.FamilyCreate` документирован дословно и ОДИНАКОВО во
ВСЕХ ШЕСТИ RevitAPI.xml (перечитаны по одной, 2021-2026, а не по двум крайним:
прибор на часть диапазона опаснее отсутствующего):
*«Thrown when the current document is project document»*. То
есть отказ здесь СИЛЬНЕЕ, чем у `FreeFormElement.Create` (там условие названо
внутри метода — «document is not a family document»): у форм массы бросает
САМА ДВЕРЬ, до всякого аргумента. KIR пишет в ПРОЕКТНЫЙ документ, значит
шесть фабрик недостижимы по построению, а не по недоделке. ЧТО ОТКРЫВАЕТ:
своя волна редактирования семейств; в проектном документе — ничего.

Итог по знаменателю, и он важнее любой отдельной строки. ТОЧНОГО СОСТАВА ТЕХ
ДВЕНАДЦАТИ ЭТА ВОЛНА НЕ ВИДЕЛА: файла переписи в дереве нет, и выдавать свою
реконструкцию за её список значило бы ровно ту неоплаченную точность, которую
этот дом ловит у себя же. Проверяемое утверждение поэтому одно, и оно
измерено: **семь записей этого семейства недостижимы из проектного документа
ПО КОНСТРУКЦИИ** — шесть фабрик форм плюс `FreeFormElement`, — а восьмая,
`NewSweepForm`, не существует ни в одной из шести сборок. Значит «2 из 12»
как оценка ПРОБЕЛА завышает работу, которую вообще можно сделать: бо́льшая
часть знаменателя — это чужие комнаты, а не наша слепота.

═══ ЗАМЕР API (живой Roslyn :52412 против сборок 2021-2026, 10.08) ═════════

  FaceWall.Create(Document, ElementId, WallLocationLine, Reference)   → 6/6
  FaceWall.IsValidFaceReferenceForFaceWall(Document, Reference)       → 6/6
  FaceWall.IsWallTypeValidForFaceWall(Document, ElementId)            → 6/6
  HostObjectUtils.GetSideFaces(FaceWall, ShellLayerType.Exterior)     → 6/6
  PlanarFace.{FaceNormal, Area, Origin} / Face.GetEdgesAsCurveLoops   → 6/6
  WallType.Width / doc.Application.VertexTolerance                    → 6/6
  WallLocationLine — все шесть членов                                 → 6/6
  BuiltInParameter.HOST_AREA_COMPUTED                                 → 6/6
  DividedSurface.{Create, CanBeDivided, HostReference, GetGridNodeUV} → 6/6
  DividedPath.{Create, NumberOfPoints, TotalPathLength}               → 6/6
  MassInstanceUtils.{AddMassLevelDataToMassInstance, GetGrossFloorArea,
                     GetGrossSurfaceArea, GetGrossVolume}             → 6/6

  FaceWall — НЕ Wall                                        → 0/6  CS0029
      ПАМЯТЬ: «стена по грани» не даёт `Wall`. Это `HostObject`, поэтому
      `LocationCurve` у неё нет вовсе, а грани читаются HostObjectUtils.
  FaceWall.WallType                                         → 0/6  CS1061
      ← ПАМЯТЬ: тип берётся `doc.GetElement(GetTypeId()) as WallType`
  MassLevelData.GetMassFloorArea / GetMassGrossVolume / … → 0/6  CS1061
      ← ПАМЯТЬ: у самого «этажа массы» НЕТ НИ ОДНОГО геометрического
      геттера; из членов есть только `LevelId`. Площади и объём живут на
      `MassInstanceUtils` и относятся к МАССЕ ЦЕЛИКОМ, не к этажу.
  MassZone / MassEnergyAnalyticalModel (типы)               → 3/6  CS0246
      только 2021-2023; в 2024-2026 этих типов в сборках НЕТ.
  doc.Create.NewFloorFaceBased / NewRoofFaceBased           → 0/6  CS1061
      подтверждает измеренное ранее: пол и кровля ПО ГРАНИ в API отсутствуют.

═══ ЧТО ВЗЯТО И ПОЧЕМУ ИМЕННО ЭТО ═════════════════════════════════════════

`FaceWall.Create` — ЕДИНСТВЕННАЯ фабрика всей главы, у которой RevitAPI.xml
называет условием броска *«document is not a project document»* — дословно и
одинаково во всех шести версиях, проверено по каждой. Это ТОЧНАЯ ИНВЕРСИЯ
отказа форм массы и `FreeFormElement`: она требует ровно тот документ, в
который KIR и пишет.

И она единственная, кто переводит свободную форму в НАСТОЯЩИЙ элемент: у
результата есть тип, слои, площадь в спецификации — в отличие от DirectShape,
про который волна тел и волна меша честно пишут «геометрия без BIM-смысла».
Дорога «масса → здание» в API состоит из трёх ходов, и после замера выше их
осталось два: стена по грани (здесь) и витраж по грани
(`NewCurtainSystem2`, см. ниже); пола и кровли по грани нет вовсе.

═══ ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ (каждая причина — замер, а не осторожность) ════

* `DividedSurface.Create` СОБИРАЕТСЯ 6/6 и грань назвать есть чем (вторая
  ступень селектора, `faceref.py`). Не взята по СВИДЕТЕЛЮ: весь её читаемый
  обратно поверхностный слой — `NumberOfUGridlines`, `NumberOfVGridlines`,
  `USpacingRule`, `VSpacingRule`, `AllGridRotation` — это ПРАВИЛА РАЗБИВКИ,
  то есть ровно то, что задал автор; узловые же величины (`GetGridNodeUV`,
  `GetGridNodeLocation`) лежат НА ГРАНИ-НОСИТЕЛЕ ПО ПОСТРОЕНИЮ и потому не
  могут разойтись ни с чем, что программа в состоянии заявить. Свидетель
  вышел бы пересчётом собственного ввода — запрещённый род. ЧТО ОТКРЫВАЕТ:
  операция УЗОРА (тип разбитой поверхности — `TilePattern` либо
  `FamilySymbol` панели витража, дословно по RevitAPI.xml); тогда построенные
  панели — настоящие элементы со своей переписью, и свидетель появляется у
  них, а не у сетки.

* `DividedPath.Create` собирается 6/6 и НЕ взята по ССЫЛКЕ: обе перегрузки
  требуют `IList<Reference>` НА КРИВЫЕ ИЛИ РЁБРА («Not all curve references in
  curveReferences represent a curve or an edge»), а вторая ступень
  замороженного диалекта называет ГРАНЬ, но не РЕБРО — это уже записано
  волной профилей (`ops_sweep.py`, `sweep_emit.py`) и здесь не переоткрыто.
  Завести третий род второй ступени попутно значило бы написать второй
  механизм рядом с существующим. ЧТО ОТКРЫВАЕТ: род `edge` во второй ступени
  селектора — отдельная волна, у которой уже есть готовый закон мощности.

* `MassInstanceUtils.AddMassLevelDataToMassInstance` («этаж массы»)
  собирается 6/6 и работает в ПРОЕКТНОМ документе — единственный кандидат
  главы, прошедший тест документа вместе с `FaceWall`. Не взята по
  СВИДЕТЕЛЮ, и это ЗАМЕР, а не осторожность: у созданного `MassLevelData`
  нет НИ ОДНОГО геометрического геттера (все `GetMass*Area`/`GetMass*Volume`
  дают CS1061 на всех шести), из членов остаётся `LevelId` — то есть ровно
  тот уровень, который мы и передали. Свидетель читал бы собственный ввод.
  Площади есть на МАССЕ ЦЕЛИКОМ (`GetGrossFloorArea`), но их величина
  выводится из геометрии массы, которой программа не авторствовала, поэтому
  ожидания у неё нет ни в какой форме. ЧТО ОТКРЫВАЕТ: чтение — эти три
  геттера просятся в семейство `query_*`, где свидетель не нужен вовсе.

* `NewCurtainSystem2(ReferenceArray, CurtainSystemType)` собирается 6/6 на
  `doc.Create` (проектный документ) и остаётся ЗДЕСЬ НЕ ВЗЯТОЙ по счётному
  слою: она возвращает `ICollection<ElementId>`, а не элемент (замерено,
  CS0266), и RevitAPI.xml объясняет почему — *«The number of CurtainSystems
  will be equal to the number of masses and generic models»*, то есть число
  созданных элементов решает REVIT по составу граней, а не оп. Перепись
  §18.1 выводит ожидание из «один элемент на оп». ЧТО ОТКРЫВАЕТ: та же
  ветка `_OP_DERIVED`, которой волна тел отложила `DirectShapeType.Create`,
  ЛИБО ограничение «все грани одного носителя» — тогда элемент ровно один и
  ветка не нужна. Второе дешевле и делается вместе с приёмкой, а не мимо.

* `FreeFormElement.Create` и `DirectShapeType.Create` — решения волны тел
  (`ops_solid.py`), здесь НЕ переоткрываются.

═══ СВИДЕТЕЛЬ: ЧЕСТНАЯ ЭТИКЕТКА ЕГО СИЛЫ ══════════════════════════════════

У волны тел свидетель сильнейший в проекте: объём считается АНАЛИТИЧЕСКИ на
компиляции и сверяется с построенным элементом. ЗДЕСЬ ТАКОЙ ВЕЛИЧИНЫ НЕТ, и
это надо сказать прямо, а не замаскировать длинным списком проверок: форму
стены по грани задаёт ГРАНЬ ЧУЖОГО ЭЛЕМЕНТА, которую программа не
авторствовала, поэтому замкнутой формы ни площади, ни объёма у неё не
существует в принципе.

Что свидетель поэтому подписывает — и каждое читает РЕЗУЛЬТАТ:

  1. тип построенного элемента == разрешённый до эффекта (topology, точно);
  2. у построенной стены РОВНО ОДНА наружная грань, сонаправленная с
     названной гранью массы (geometry). Проверка ТОЧНАЯ и без единого своего
     допуска: параллельность — родным `XYZ.CrossProduct(...).IsZeroLength()`,
     сонаправленность — знаком `DotProduct`. Ровно те же два теста, которыми
     `faceref.py` отбирает грань, и по той же причине («ни одного своего
     допуска»);
  3. точка этой грани лежит внутри габарита НОСИТЕЛЯ, расширенного на
     собственную толщину стены плюс `VertexTolerance` (geometry). Обе
     величины — числа САМОГО Revit (`WallType.Width`,
     `doc.Application.VertexTolerance`), ни одного назначенного. Расширение
     ровно на толщину верно ПРИ ЛЮБОМ `location_line`: тело стены целиком
     лежит в полосе ±толщина от грани-носителя, а грань-носитель — внутри
     габарита носителя. Утверждение ПРОВАЛИВАЕТСЯ, если Revit построил стену
     не по названной массе;

     ПОЧЕМУ ГАБАРИТ НОСИТЕЛЯ, А НЕ ПЛОСКОСТЬ НАЗВАННОЙ ГРАНИ — это замер, а
     не выбор попроще. Масса в проекте — `FamilyInstance`, и грань её тела
     приходит через `GeometryInstance`: `faceref` берёт ССЫЛКУ одним
     аксессором, а КООРДИНАТЫ другим, через `GeometryInstance.Transform`,
     ровно потому что у символьной геометрии своя система координат.
     Прочитать `PlanarFace.Origin` по такой ссылке и молча считать его
     модельным значило бы завести третью систему координат в свидетеле —
     тот же род ошибки, что и назначенный допуск, только тише. Габарит
     элемента Revit отдаёт в координатах МОДЕЛИ, и обе части сравнения
     оказываются в одной системе БЕЗ единого нашего преобразования;
  4. площадь ТОЙ ЖЕ грани, прочитанная с построенного тела
     (`PlanarFace.Area`), строго больше нуля (geometry). Это не порог, а
     ГРАНИЦА ВАКУУМНОСТИ: нулевая площадь означает, что не построено ничего.

     ЧИТАЕТСЯ ТЕЛО, А НЕ ПАРАМЕТР, и это исправление, а не первоначальный
     замысел. Первая редакция брала здесь `HOST_AREA_COMPUTED` и всё равно
     подписывала (geometry) — то есть удостоверяла ось, на которую не
     смотрела. Поймал это страж дома (`test_witness_axis_honesty`, §18.3), и
     поймал ровно там, где такую подмену не видно глазом: параметр С ИМЕНЕМ
     ПРО ПЛОЩАДЬ выглядит геометрией убедительнее многих настоящих чтений.

ЧЕГО СВИДЕТЕЛЬ НЕ ПОДПИСЫВАЕТ, НАЗВАННОЕ ВСЛУХ: равенства площади стены
площади названной грани здесь НЕТ. Накрывает ли Revit грань целиком, в
RevitAPI.xml не сказано ни словом, и утверждать это значило бы завести
проверку, которая может отвергнуть исправную работу. Вместо утверждения
квитанция везёт СЫРУЮ ПАРУ (площадь грани и площадь стены, мм²) — первый
живой прогон тем самым ИЗМЕРИТ этот остаток, а не оценит его. Та же
дисциплина, что у `create_slab_edge` с периметром и у волны тел с объёмом.

═══ ГРАНИЦА ЗАМЕРА ════════════════════════════════════════════════════════

Всё выше измерено КОМПИЛЯЦИЕЙ против настоящих сборок и ЧТЕНИЕМ RevitAPI.xml
в части условий броска. Живого прогона у этого опа НЕТ НИ ОДНОГО (он стоит в
`tool_doc.UNPROVEN`), и собралось ≠ построит — тот же закон, что в шапке
shape_emit.py. Офлайн непроверяемы ровно две вещи, и обе названы: накрывает
ли стена грань целиком и какие именно типы стен Revit допускает по грани
(на второе есть предполётный `IsWallTypeValidForFaceWall`, и он спрашивается
ДО эффекта, поэтому неизвестность станет типизированным отказом, а не
исключением).
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)

#: `create_face_wall.location_line` -> член `WallLocationLine`. ВСЕ ШЕСТЬ, в
#: отличие от `create_wall`, где их три. Разница не в вольности, а в поводе:
#: там сужение объяснено ЛИФТОМ (добавление ординалов меняет разбор реальных
#: моделей и требует своего замера покрытия), а у стены по грани лифтера нет
#: вовсе — обратный ход объявлен пробелом захвата. Сузить здесь значило бы
#: унести у автора степень свободы, которую сам Revit принимает, ради
#: ограничения, повод которого к этой операции не относится.
#:
#: Имена — те же слова, что у `create_wall` (`WALL_LOCATION_LINE_ORDINALS`),
#: и это существенно: два разных написания одного понятия в одном реестре
#: заставили бы автора гадать, одно ли это и то же.
FACE_WALL_LOCATION_LINES = {
    "wall_centerline": "WallCenterline",
    "core_centerline": "CoreCenterline",
    "finish_face_exterior": "FinishFaceExterior",
    "finish_face_interior": "FinishFaceInterior",
    "core_exterior": "CoreExterior",
    "core_interior": "CoreInterior",
}

OPS = [
    OpSpec(
        name="create_face_wall",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            # НОСИТЕЛЬ — СУЩЕСТВУЮЩАЯ МАССА, и `target_w` здесь по той же
            # причине, что у проёма и у профилей: стену по грани строят по
            # массе, которая УЖЕ СТОИТ, а масса, размещённая этой же
            # программой (`place_family`), — частный случай. `ref_kinds`
            # только ELEMENT: отдельного рода ссылки на массу нет, а сузить
            # до WALL было бы прямо неверно.
            ParamSpec("host", "target_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            # КАКАЯ ГРАНЬ — ЕЁ ВНЕШНЯЯ НОРМАЛЬ, в координатах модели. Не
            # индекс: порядок `Solid.Faces` не документирован, и «первая
            # подходящая» — это `.FirstOrDefault()` под другим именем (живой
            # парный замер 02.08 на Snowdon: плечо C# взяло 1 тип двери из 62
            # МОЛЧА). Решает МОЩНОСТЬ множества подошедших граней, ровно как
            # в `faceref.py`: одна — берём, ноль — отказ, две и больше —
            # отказ С ЧИСЛОМ.
            #
            # ОТБОР ТОЧНЫЙ, А НЕ «БЛИЖАЙШИЙ ПО УГЛУ», и это следствие, а не
            # упрощение: «ближайшая» требует УГЛОВОГО ДОПУСКА, которого никто
            # не мерил. Длина вектора не важна — он нормируется в Revit.
            #
            # РОД `pt_xyz`, НО ЭТО НЕ МИЛЛИМЕТРЫ, и умолчать об этом нельзя.
            # Здесь ровно тот же приём и тот же повод, что у
            # `move_elements.delta_mm`: форма [x, y, z] уже РАСПОЗНАЁТСЯ
            # схемой, а `schema_gen` исчерпывающий — новый род означал бы
            # правку в каждом его потребителе ради значения той же формы.
            # Отличие названо в `authoring_validation`: общий потолок
            # координат (`_COORD_LIMIT_MM`) к направлению не применяется
            # вовсе, а нулевой вектор отвергается на разборе ТОЧНЫМ
            # равенством нулю — не порогом: «почти нулевой» решает сам Revit
            # своим `XYZ.IsZeroLength()` уже в рантайме.
            ParamSpec("face_normal", "pt_xyz", required=True),
            # ПОЛОЖЕНИЕ СТЕНЫ ОТНОСИТЕЛЬНО ГРАНИ. ОБЯЗАТЕЛЬНО и БЕЗ
            # УМОЛЧАНИЯ: это АРГУМЕНТ вызова, а не параметр, который можно
            # оставить незаданным, — подставить его за автора значило бы
            # молча решить, с какой стороны грани встанет тело.
            ParamSpec("location_line", "enum", required=True,
                      choices=tuple(FACE_WALL_LOCATION_LINES)),
            # Тип стены. Пул тот же, что у `create_wall`: класс типа тот же
            # (`WallType`), и второй пул на те же элементы означал бы два
            # ответа на один вопрос. Пригодность КОНКРЕТНОГО типа для стены
            # по грани решает не пул, а сам Revit —
            # `IsWallTypeValidForFaceWall`, и спрашивается он ДО эффекта.
            ParamSpec("type", "sel"),
        ),
        # НАСТОЯЩИЙ ЭЛЕМЕНТ, а не («create», «geometry»): у стены по грани
        # есть тип, слои и площадь в спецификации — всё то, чего у
        # DirectShape нет по построению. Клетка категории НЕ объявляется:
        # категория известна точно (OST_Walls), но `create_wall` уже
        # покрывает эту клетку, и вторая запись про то же не добавляет знания.
        capability=(("create", "element"),),
        post=("face wall exists (materialized or typed refusal); "
              "a wall type Revit refuses for a face wall is a typed refusal "
              "from IsWallTypeValidForFaceWall BEFORE the call, never a raw "
              "ArgumentException; "
              "a face Revit refuses as a face-wall parent is a typed refusal "
              "from IsValidFaceReferenceForFaceWall BEFORE the call; "
              "GetTypeId() re-read == resolved wall type (topology); "
              "the built wall has EXACTLY ONE exterior side face codirectional "
              "with the named mass face, by Revit's own zero-length "
              "cross-product test and the sign of the dot product, with no "
              "tolerance of ours (geometry); "
              "a point of that face lies inside the host's model-space "
              "bounding box grown by the wall's own WallType.Width plus "
              "doc.Application.VertexTolerance — both Revit's own numbers, "
              "none assigned here (geometry); "
              "the PlanarFace.Area of that same built face is strictly "
              "positive (geometry: the vacuity boundary, not a threshold — "
              "and read off the SOLID, never off a parameter, so the verdict "
              "signs the axis it actually read); "
              "NAMED ABSENCE: area equality between the wall and the named "
              "face is NOT asserted — whether Revit spans the whole face is "
              "documented nowhere, so the receipt carries the RAW PAIR and "
              "the first live run measures the remainder instead of a "
              "reasoned tolerance standing in for it"),
        writes_model=True,
        grounded=(("type", "wall_types", False),),
        # ПУСТО ПО ПОСТРОЕНИЮ, как у волны тел: единственный числовой допуск
        # этой операции — функция самой стены (`WallType.Width`) и
        # собственного числа Revit (`VertexTolerance`), поэтому реестровой
        # константой он быть не может. Разбор — в шапке модуля.
        tolerances={},
    ),
]
