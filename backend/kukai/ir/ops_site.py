"""ops_site — площадка и рельеф (wave/site, 2026-08-09).

Registry module — Add ops HERE, not in spec.py. Парный файл эмиссии —
`site_emit.py`, ровно как `ops_arch.py` ↔ `arch_emit.py`.

ДО ЭТОЙ ВОЛНЫ СЕМЕЙСТВО ПЛОЩАДКИ БЫЛО ПУСТЫМ: ни рельефа, ни площадки под
здание, ни подобласти. Здание стояло в пустоте, а «посади дом на рельеф» —
самая обычная фраза заказчика — не выражалась НИЧЕМ.

ЗАМЕР API (живой компайл-сервис :52412, 2021-2026, 09.08.2026). Ни одна
строка ниже не написана по памяти; каждая проверена присваиванием в
ОБЪЯВЛЕННЫЙ тип (`var __x = ...` компилируется при любом типе справа и не
доказывает ничего — урок волны ограждений, где такая проба пропустила
`ICollection<ElementId>`):

    TopographySurface.Create(doc, IList<XYZ>)                6/6
    TopographySurface.GetPoints()                            6/6
    TopographySurface.IsSiteSubRegion                        6/6
    Toposolid.Create(doc, IList<XYZ>, typeId, levelId)       2024-2026
    Toposolid.Create(doc, IList<CurveLoop>, typeId, levelId) 2024-2026
    Toposolid.Create(doc, profiles, points, typeId, levelId) 2024-2026
    Toposolid.GetSlabShapeEditor()                           2024-2026
    Toposolid.GetPoints()                                    НЕТ НИ НА ОДНОЙ
    SlabShapeEditor.SlabShapeVertices / SlabShapeVertex.Position  6/6
    BuildingPad.Create(doc, typeId, levelId, IList<CurveLoop>)    6/6
    BuildingPad.GetBoundary() / .AssociatedTopographySurfaceId    6/6
    SiteSubRegion.Create(doc, IList<CurveLoop>)              6/6
    SiteSubRegion.Create(doc, IList<CurveLoop>, ElementId)   6/6
    SiteSubRegion.GetBoundary() / .HostId / .TopographySurface    6/6
    ElementTypeGroup.BuildingPadType                         6/6
    ElementTypeGroup.ToposolidType                           НЕТ НИ НА ОДНОЙ
    ToposolidType (тип)              2024-2026 (2023: CS0122, internal)

ЧЕТЫРЕ ФАКТА, КОТОРЫЕ ПЕРЕВЕРНУЛИ БЫ ЭТИ ОПЫ, ЕСЛИ БЫ ИХ НЕ ЗАМЕРИЛИ:

1. `SiteSubRegion` — НЕ `Element`. У него нет ни `.Id`, ни `get_Parameter`
   (CS0029/CS1061 на всех шести). Элемент подобласти — это её
   `.TopographySurface`, и именно он штампуется, читается в квитанцию и
   свидетельствуется. Написать `__sr.Id` было бы шестикратным CS1061; хуже —
   писать `__sr` в квитанцию нечем, а квитанция без id неотличима от мусора
   в модели, потому что A5 сверяет владение именно по ней.
2. `ElementTypeGroup.BuildingPadType` СУЩЕСТВУЕТ на всех шести, хотя
   `backend/data/revit_api_db.json` его не знает (наша база несёт 30 из 93
   членов `ElementTypeGroup`). База — документация, судья — компилятор; тот
   же приоритет, которым 30.07 закрыли `SpatialElementTag.SpatialElement`.
   Поэтому у площадки под здание тип по умолчанию ЕСТЬ (как у стены), а у
   толщи рельефа его нет по построению (как у ограждения).
3. `Toposolid.GetPoints()` НЕ СУЩЕСТВУЕТ (CS1061 на 2024/2025/2026, где сам
   тип есть). Симметричного сильного свидетеля у толщи нет; вместо него —
   `GetSlabShapeEditor().SlabShapeVertices`, который КОМПИЛИРУЕТСЯ, но чью
   НЕ-пустоту у толщи, построенной по точкам, офлайн не проверить (см. ниже
   «ЧЕГО ЗДЕСЬ НЕ ДОКАЗАНО»).
4. `BuiltInCategory.OST_Toposolid` появился в 2023 — на ГОД раньше самого
   класса `Toposolid` (2024). Значит имя категории нельзя использовать как
   признак версии, а сборщик типов толщи нельзя писать через `OfCategory`.

ОДНА ОПЕРАЦИЯ РЕЛЬЕФА, А НЕ ДВЕ, И ВОТ ОДНО ПРЕДЛОЖЕНИЕ ПОЧЕМУ: поверхность
и толща — это ДВЕ РАЗНОВИДНОСТИ одного намерения «положи рельеф», ровно как
столбчатый и плитный у `create_foundation`, поэтому разновидность называет
АВТОР (`variety`, закрытое перечисление без умолчания), а условно
обязательные поля — уровень и тип, нужные только толще, — держит эмиттер
типизированным отказом, как `struct_emit.emit_foundation` держит `xy`
против `outline`.

Почему это НЕ «одна операция с автоматическим выбором по версии»: толща и
поверхность — РАЗНЫЕ элементы РАЗНЫХ категорий (`OST_Toposolid` против
`OST_Topography`), с разными свидетелями и разной привязкой к уровню.
Подставить одно вместо другого по номеру версии значило бы построить не то,
что просили, и снаружи это неотличимо от успеха — ровно запрещённое.
Поэтому `variety="toposolid"` на 2021-2023 — типизированный отказ KIR-E003,
НАЗЫВАЮЩИЙ следующий ход (`variety="surface"`), а не тихая замена.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО:

* толща по КОНТУРУ (`Toposolid.Create(doc, IList<CurveLoop>, ...)` и
  перегрузка «профили + точки») не подключена: у операции один вход формы —
  точки, — и вызвать пятиаргументную перегрузку с пустым списком профилей
  значило бы передать в API форму, поведение которой не документировано.
  Это отдельная будущая работа с отдельным свидетелем, а не «ещё один
  необязательный параметр»;
* у площадки под здание НЕТ параметра `host`: `BuildingPad.Create` хозяина
  не принимает вовсе — Revit ищет его сам. Поэтому «нет хозяина» ловится
  предпроверкой в эмиттере (см. site_emit.py), а не полем.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

#: Разновидности рельефа. Закрытое перечисление БЕЗ умолчания: подставить
#: одну за автора значит выбрать за него элемент другой категории.
TOPOGRAPHY_VARIETIES = ("surface", "toposolid")

#: Самая ранняя версия Revit, где существует класс `Toposolid` (замер).
#: Живёт здесь, а не литералом в эмиттере: то же число читает и тест оси
#: версий, и таблица ворот.
TOPOSOLID_MIN_VERSION = "2024"

OPS = [
    OpSpec(
            name="create_topography",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # РАЗНОВИДНОСТЬ НАЗЫВАЕТ АВТОР. Имя `variety`, а не `kind`, —
                # то же ограничение реестра, что у create_foundation:
                # `kind` зарезервировано за kind_enum, и test_invariants
                # требует у поля с таким именем escape-значение, которого у
                # рельефа честно нет.
                ParamSpec("variety", "enum", required=True,
                          choices=TOPOGRAPHY_VARIETIES),
                # ТОЧКИ РЕЛЬЕФА — ТРЁХМЕРНЫЕ, И ЭТО НЕ УДОБСТВО. У рельефа
                # отметка живёт В САМОЙ ТОЧКЕ: TopographySurface.Create не
                # принимает уровня вовсе, и Z каждой точки — это и есть
                # высота земли. Плоский род `pts` ([x,y]) обнулил бы рельеф
                # в плоскость — то есть построил бы ДРУГОЙ рельеф молча.
                ParamSpec("points_mm", "pts_xyz", required=True),
                # УРОВЕНЬ — ТОЛЬКО У ТОЛЩИ, и это настоящее расхождение
                # сигнатур, а не ветка эмиттера: Toposolid.Create ТРЕБУЕТ
                # levelId, TopographySurface.Create его не принимает.
                # required=False на уровне схемы по той же причине, по
                # которой у create_railing.level: статическое required=True
                # потребовало бы уровня и у поверхности, которой он не нужен
                # НИГДЕ. Условную обязательность держит эмиттер (KIR-P005).
                ParamSpec("level", "sel",
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # ТИП — ТОЛЬКО У ТОЛЩИ. Умолчания документа у неё нет ПО
                # ПОСТРОЕНИЮ: ElementTypeGroup.ToposolidType не существует ни
                # на одной из шести версий (замерено), спросить Revit «твоя
                # толща по умолчанию» невозможно. Пропущенный тип разрешает
                # ground общим правилом «единственный в пуле, иначе
                # типизированный вопрос» — тот же шов, что у ограждения.
                ParamSpec("type", "sel"),
            ),
            capability=(("create", "element"), ("create", "geometry")),
            post=("variety=surface: topography surface exists on 2021-2026 "
                  "(TopographySurface.Create, no level — elevation lives in "
                  "each point's Z); "
                  "variety=toposolid: toposolid exists on 2024-2026 only, and "
                  "below that the whole op is a typed refusal naming "
                  "variety=surface as the next move — never a substituted "
                  "element of another category; "
                  "described terrain points are re-read FROM the built "
                  "element (±1mm): GetPoints() on the surface, "
                  "SlabShapeEditor vertices on the toposolid (geometry); "
                  "bbox XY extents == points XY extents (±50mm, geometry); "
                  "level binding == resolved level when variety=toposolid "
                  "(topology)"),
            writes_model=True,
            grounded=(("level", "levels", False),
                      ("type", "toposolid_types", False)),
            # ±1mm — ВЫВЕДЕН, а не назначен: это `contour._EDGE_TOL`, то есть
            # статический ShortCurveTolerance самого Revit. Две точки ближе
            # него Revit не различает вовсе, значит совпадение прочитанной
            # точки с описанной в пределах 1 мм — САМОЕ ТОЧНОЕ утверждение,
            # которое вообще имеет смысл на этой платформе. Ужать его до
            # шума перевода единиц (≈1e-9 мм) значило бы обвинять правильный
            # рельеф за округление, которого мы не измеряли.
            #
            # ±50mm — УНАСЛЕДОВАН, и это сказано прямо: ровно то число, что
            # уже лежит в реестре у create_floor_by_contour, create_ceiling и
            # create_foundation под тем же ключом `bbox_mm`, для того же
            # предиката над тем же читателем `get_BoundingBox`. Оно
            # НАЗНАЧЕННОЕ (`assigned` в терминах bounds_audit), не
            # замеренное; завести здесь СВОЁ число значило бы добавить
            # четвёртую границу, назначенную рассуждением, — класс дефекта
            # этого дома.
            tolerances={"point_mm": 1.0, "bbox_mm": 50.0},
        ),
    OpSpec(
            name="create_building_pad",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # CONTOUR — РОДНОЙ ВХОД ЭТОЙ ОПЕРАЦИИ, а не альтернатива
                # ломаной: BuildingPad.Create принимает IList<CurveLoop>,
                # то есть ровно то, что contour.emit_loop_cs уже строит.
                # Плоского `outline` здесь нет вовсе — заводить второй вход
                # формы там, где обратного хода (materialize) не существует,
                # значило бы завести взаимную обязательность ни для кого.
                ParamSpec("contour", "region", required=True),
                # Уровень ОБЯЗАТЕЛЕН у самого API (четырёхаргументный
                # Create), поэтому здесь required=True без оговорок.
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # Пропущенный тип разрешает ground общим правилом
                # «единственный в пуле, иначе типизированный вопрос». Тип
                # документа по умолчанию у площадки СУЩЕСТВУЕТ
                # (ElementTypeGroup.BuildingPadType, 6/6 — замерено вопреки
                # нашей же базе API), но НЕ используется: см. разбор в
                # site_emit._grounded_type_cs. Коротко — «площадка по
                # умолчанию» на чужом здании почти никогда не та, а подмена
                # типа снаружи неотличима от успеха; типизированный вопрос с
                # кандидатами автор увидит, подстановку — нет.
                ParamSpec("type", "sel"),
            ),
            capability=(("create", "element"), ("create", "geometry")),
            post=("building pad exists on 2021-2026 (BuildingPad.Create); "
                  "a pad with no hosting topography anywhere in the document "
                  "is a typed refusal naming create_topography as the next "
                  "move, never a raw InvalidOperationException; "
                  "level binding == resolved level (topology); "
                  "GetBoundary() re-read bbox == contour lowered-edges bbox "
                  "(±50mm, arc extremes included, geometry); "
                  "AssociatedTopographySurfaceId holds a real element id "
                  "(topology)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("type", "building_pad_types", False)),
            # ±50mm — тот же унаследованный `bbox_mm`, что выше, и здесь у
            # него есть ВЫВОДИМАЯ составляющая: читатель — не габарит тела, а
            # сама граница `GetBoundary()`, развёрнутая `Curve.Tessellate()`.
            # Точки развёртки лежат НА кривой, поэтому единственная
            # собственная погрешность чтения — стрелка одного звена
            # развёртки, и она на порядки меньше 50 мм при любом здании.
            # Остаток запаса — унаследованное назначение, не замер.
            tolerances={"bbox_mm": 50.0},
        ),
    OpSpec(
            name="create_site_subregion",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("contour", "region", required=True),
                # ХОЗЯИН НЕОБЯЗАТЕЛЕН, потому что перегрузок ДВЕ (обе 6/6):
                # без хозяина Revit ищет поверхность сам, с хозяином — берёт
                # названную. Пула у этого селектора нет намеренно: пула
                # топоповерхностей в снапшоте не существует, а заводить его
                # ради `by:name` значило бы обещать разрешение по имени там,
                # где имя поверхности в Revit не является её адресом.
                # Работают `by:element_id` и `by:ref` — тот же шов и та же
                # причина, что у create_railing.host.
                ParamSpec("host", "sel",
                          ref_kinds=(ReferenceKind.ELEMENT,)),
            ),
            capability=(("create", "element"), ("create", "geometry")),
            post=("site subregion exists on 2021-2026 "
                  "(SiteSubRegion.Create); "
                  "the created surface reports IsSiteSubRegion (semantic); "
                  "GetBoundary() re-read bbox == contour lowered-edges bbox "
                  "(±50mm, arc extremes included, geometry); "
                  "HostId holds a real element id, and equals host when host "
                  "is given (topology)"),
            writes_model=True,
            grounded=(),
            tolerances={"bbox_mm": 50.0},
        ),
]
