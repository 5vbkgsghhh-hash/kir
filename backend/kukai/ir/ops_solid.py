"""ops_solid — ПАРАМЕТРИЧЕСКОЕ ТЕЛО (GeometryCreationUtilities → DirectShape).

Registry module — операции добавляются СЮДА, а не в spec.py. Эмиттер живёт в
solid_emit.py (парный файл, как ops_shape.py + shape_emit.py у волны меша).

═══ ПОЧЕМУ ЭТА ВОЛНА, ЕСЛИ МЕШ УЖЕ ЕСТЬ ════════════════════════════════════

Шапка ops_shape.py оставила запись: «СОЛИД. TessellatedShapeBuilderTarget.Solid
компилируется, но требует замкнутого тела… Солид — отдельная волна с ЖИВЫМ
ЗАМЕРОМ, а не флажок здесь». Это она — и дверь оказалась другой: тело строится
не тесселятором, а СЕМЬЮ ФАБРИКАМИ `GeometryCreationUtilities`, и у них есть
свойство, которого у меша нет принципиально.

СРАЗУ О ГРАНИЦЕ ЗАМЕРА, чтобы её не пришлось искать: всё, что ниже измерено
КОМПИЛЯЦИЕЙ против настоящих сборок 2021-2026, а не живым Revit. Живого
прогона у этих двух опов НЕТ НИ ОДНОГО (они стоят в `tool_doc.UNPROVEN`), и
собралось ≠ построит — тот же закон, что записан в шапке shape_emit.py.

**ОБЪЁМ ВЫДАВЛИВАНИЯ СЧИТАЕТСЯ АНАЛИТИЧЕСКИ НА КОМПИЛЯЦИИ.** Профиль CONTOUR
опускается в замкнутый список рёбер, интеграл Грина по границе даёт площадь
ТОЧНО (с дугами — замкнутой формой, не выборкой), объём призмы = площадь ×
высота. Свидетель сравнивает это число с `Solid.Volume`, вычитанным С
ПОСТРОЕННОГО элемента. У меша ничего подобного нет: там сверяются габарит и
число треугольников — то есть то, что мы сами же и прислали, пересчитанное.
Здесь сверяется ВЕЛИЧИНА, которой во входе не было ни в каком виде.

Тело вращения даёт то же самое через первую теорему Гульдина-Паппа, точнее —
через её вывод: объём тела, полученного поворотом плоской области вокруг оси
на угол θ, равен θ·∬x dA (цилиндрические координаты, теорема Фубини). Момент
∬x dA — снова интеграл по границе, снова замкнутая форма (contour.py).

═══ ЗАМЕР API (живой Roslyn :52412 против настоящих сборок, 2021-2026, 09.08)

Ни одного расхождения между версиями: КАЖДЫЙ названный ниже член собирается
на всех шести, поэтому у обоих опов НЕТ ОСИ ВЕРСИЙ вовсе — редкость для этого
пакета (у полов, кровель, потолков и марок она есть). Закреплено тестом
`test_solid.py::SixVersionsEmitTheSameSurface`: эмиссия обязана совпадать
байт в байт на 2021-2026, иначе кто-то завёл ветку и не сказал.

  CreateExtrusionGeometry(IList<CurveLoop>, XYZ, double)          → 6/6
  CreateExtrusionGeometry(..., SolidOptions)                      → 6/6
  CreateRevolvedGeometry(Frame, IList<CurveLoop>, double, double) → 6/6
  CreateRevolvedGeometry(..., SolidOptions)                       → 6/6
  CreateSweptGeometry(CurveLoop, int, double, IList<CurveLoop>)   → 6/6
  CreateBlendGeometry(CurveLoop, CurveLoop, ICollection<VertexPair>) → 6/6
  CreateSweptBlendGeometry(Curve, IList<double>, IList<CurveLoop>,
                           IList<ICollection<VertexPair>>)        → 6/6
  CreateLoftGeometry(IList<CurveLoop>, SolidOptions)              → 6/6
  CreateFixedReferenceSweptGeometry(CurveLoop, int, double,
                                    IList<CurveLoop>, XYZ)        → 6/6
  Solid.{Volume,SurfaceArea,Faces,Edges,GetBoundingBox,ComputeCentroid} → 6/6
  PlanarFace.{FaceNormal,Area}, Face.GetEdgesAsCurveLoops         → 6/6
  CurveLoop.CreateViaTransform / Transform.Identity+сеттеры базисов → 6/6
  Frame(XYZ, XYZ, XYZ, XYZ)                                       → 6/6
  DirectShape.SetShape(IList<GeometryObject>)                     → 6/6
  doc.Application.{VertexTolerance,ShortCurveTolerance}           → 6/6
  DirectShapeType.Create(doc, string, ElementId) + SetTypeId      → 6/6
  FreeFormElement.Create(doc, Solid)                              → 6/6 (собирается!)

  CreateSweptBlendGeometry(..., SolidOptions) 4-м аргументом      → 0/6
      CS1503 cannot convert from 'SolidOptions' to
      'IList<ICollection<VertexPair>>'  ← ПАМЯТЬ: перегрузка так НЕ выглядит
  Autodesk.Revit.DB.IFC.ExporterIFCUtils                          → 0/6
      CS0234 нет в замыкании ссылок — готового «посчитай площадь
      CurveLoop'ов» у нас НЕТ, поэтому площадь считается своей замкнутой
      формой, а не одалживается у экспортёра

ДВЕ ФАБРИКИ ЭЛЕМЕНТОВ, ОБЕ ОТКАЗАНЫ С ПРИЧИНОЙ:

* `FreeFormElement.Create` СОБИРАЕТСЯ на всех шести и всё равно НЕ
  ИСПОЛЬЗУЕТСЯ — ровно тот класс, о котором предупреждает shape_emit.py
  («собралось — не значит построит»): RevitAPI.xml на всех шести версиях
  дословно перечисляет условие броска — *«document is not a family document,
  nor a document editing an in-place family»*. KIR пишет в ПРОЕКТНЫЙ документ,
  значит вызов гарантированно бросит. Отказ по документации, а не по живому
  падению. ЧТО ОТКРЫВАЕТ: своя волна редактирования семейств; в проектном
  документе — ничего.

* `DirectShapeType.Create(doc, name, categoryId)` + `DirectShape.SetTypeId`
  собирается 6/6 и дала бы телу ТИП, то есть сняла бы половину «честной
  этикетки». Отказана не из осторожности, а потому что ломает СЧЁТНЫЙ слой:
  один оп создавал бы ДВА элемента (тип и экземпляр), а перепись §18.1
  выводит ожидание из категории×уровня по ОДНОМУ элементу на оп
  (`acceptance._category_of_op`), и типовой элемент лёг бы в ту же ячейку
  категории. L2-приёмка объявила бы расхождение на каждом теле. ЧТО ОТКРЫВАЕТ:
  ветка `_OP_DERIVED` в acceptance.py, объявляющая производный типовой
  элемент, — и тогда типизация тел станет отдельной волной с честным
  свидетелем идентичности типа. Заводить её попутно значило бы сломать
  приёмку ради поля в дереве проекта.

═══ ЧЕСТНАЯ ЭТИКЕТКА — ТА ЖЕ, ЧТО У МЕША ═══════════════════════════════════

DirectShape с солидом внутри — по-прежнему ГЕОМЕТРИЯ БЕЗ BIM-СМЫСЛА: нет типа,
нет параметров, человек его не отредактирует. Поэтому:

  * клетка способности — («create», «geometry»), НЕ («create», «element»);
  * `grounded` ПУСТ, и это содержательно (подставлять нечего);
  * категории — ТА ЖЕ закрытая таблица `DIRECTSHAPE_CATEGORIES` из
    ops_shape.py, ИМПОРТОМ, а не копией. Тело в категории стен читалось бы
    стеной в каждом фильтре и каждой спецификации, не будучи ничем, чем стена
    является. У KIR есть настоящие create_wall/create_floor/create_roof —
    `IMPERSONATION_ROUTES` называет их поимённо, и с 09.08 эта таблица
    наконец ЧИТАЕТСЯ отказом (до этого дня у неё было НОЛЬ импортёров:
    она описывала закон, которого никто не произносил).

ЭТИМИ ОПАМИ НЕЛЬЗЯ ДОБИРАТЬ СТЕНЫ/ПЕРЕКРЫТИЯ/КРОВЛИ. Соблазн здесь сильнее,
чем у меша: выдавленный контур ВЫГЛЯДИТ как плита и объём у него правильный.
Он всё так же не имеет ни слоёв, ни соединений, ни проёмов, ни спецификации.

═══ ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ (пять фабрик из семи) ══════════════════════════

Закон волны: ФАБРИКА ЕДЕТ ТОЛЬКО С ЧЕСТНЫМ СВИДЕТЕЛЕМ. У выдавливания и
вращения замкнутая форма объёма есть; у остальных пяти её НЕТ, и подписывать
габаритом «мы построили то, что вы просили» значило бы поставить проверку,
которая не может провалиться на подмене формы.

  * `CreateSweptGeometry` / `CreateFixedReferenceSweptGeometry` — объём
    протяжки по НЕПЛОСКОМУ пути замкнутой формы не имеет: теорема Паппа
    верна только когда путь плоский и не пересекает область, а RevitAPI.xml
    прямо разрешает «The path may be planar or non-planar». Считать объём
    выборкой пути значит внести в свидетеля свою ошибку и заложить её в
    допуск — тот самый дефект «допуск придуман», который этот компилятор
    ловит. ЧТО ОТКРЫВАЕТ: ограничение пути одной плоскостью + доказательство
    непересечения, тогда V = A·L(центроида) — отдельная волна.
  * `CreateBlendGeometry` / `CreateSweptBlendGeometry` / `CreateLoftGeometry` —
    поверхность между профилями строит САМ Revit («blending smoothly»,
    «the function chooses vertex connections»), то есть форма боковой
    поверхности не определяется входом однозначно. Объёма в замкнутой форме
    нет ни у одного из трёх; линейная интерполяция (призматоид Симпсона)
    точна лишь для линейчатой боковой поверхности, а Revit её таковой не
    обещает. ЧТО ОТКРЫВАЕТ: живой замер `Solid.Volume` против формулы
    призматоида на десятке пар профилей — если сходится, свидетель честен.

═══ ДОПУСК: ВЫВЕДЕН ИЗ САМОГО REVIT, А НЕ НАЗНАЧЕН ════════════════════════

`tolerances` ПУСТ, и это не пробел. Число допуска здесь не может быть
реестровой константой по построению: оно зависит от размера тела. Свидетель
считает его В ЭМИССИИ из двух выведенных величин:

  δ = MM(doc.Application.VertexTolerance) + <квант эмиссии координаты>

`VertexTolerance` — собственное число Revit: «Two points within this distance
are considered coincident». RevitAPI.xml там же предупреждает: *«Do not use
this value to set the distance between two points»* — мы и не задаём им
расстояний, мы им СРАВНИВАЕМ, то есть используем ровно по назначению. Тело,
вся граница которого лежит в пределах δ от эталонной, состоит из точек,
которые сам Revit считает совпадающими; сдвиг границы на δ меняет объём не
больше чем на (площадь поверхности)·δ, а площадь — на (длина границ граней)·δ.
Отсюда два допуска, оба ВЫВЕДЕННЫЕ и оба зависящие от геометрии опа.

Квант эмиссии — `contour.EMIT_COORD_QUANTUM_MM`: `emit_loop_cs` печатает
координаты с двумя знаками, значит наша собственная граница уже отличается от
идеальной на величину этого кванта, и складывать его с δ обязательно.

ЗАПРЕТ ВАКУУМНОСТИ (закон «проверка, которая не может провалиться, хуже
отсутствующей»). Выведенный допуск может оказаться больше самой измеряемой
величины — у листа толщиной в миллиметр или у проёма размером с допуск.
Тогда свидетель формально есть, а провалиться не может. Эмиссия ставит рядом
РАНТАЙМ-ОТКАЗ: если допуск объёма не меньше объёма самого мелкого
ОБЪЯВЛЕННОГО элемента профиля (самого профиля либо мельчайшего проёма) — оп
отказывает названно, а не подписывает. Порог не выдуман: «допуск ≥ величины»
и есть определение вакуумности.

═══ ЧТО ЖДЁТ ЖИВОГО REVIT ══════════════════════════════════════════════════

RevitAPI.xml, `Solid.Volume`, дословно и ОДИНАКОВО на всех шести версиях:
*«Revit attempts to compute the volume analytically, if possible. If an
analytical solution is not possible, it uses tessellated faces… The calculated
volume may be slightly underestimated or overestimated if curved surfaces are
present.»* Величина этого «slightly» не документирована нигде. Наш допуск
моделирует СИММЕТРИЧНОЕ возмущение границы — ровно то, о чём говорит эта
фраза, — поэтому объёмный свидетель едет всегда.

`Solid.SurfaceArea` там же: *«Will slightly underestimate if curved surfaces
are present»* — это СИСТЕМАТИЧЕСКИЙ СДВИГ, а сдвиг возмущением границы не
моделируется. Поэтому свидетеля полной площади поверхности здесь НЕТ вовсе;
вместо него едет свидетель ПЛОСКИХ ТОРЦОВ (`PlanarFace.Area`), который к
кривым поверхностям не прикасается и потому от этой оговорки свободен. Это
не осторожность, а закон дома: свидетель подписывает ту ось, которую читал.

Квитанция везёт СЫРУЮ ПАРУ (ожидание и замер, в мм³/мм²) — первый живой
прогон тем самым ИЗМЕРЯЕТ остаток, а не оценивает его.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)
from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES

#: Оба опа кладут тело в DirectShape, поэтому набор категорий у них ОДИН и тот
#: же и берётся импортом. Копия здесь означала бы, что запрет выдавать тело за
#: стену можно снять в одном файле и не заметить во втором.
SOLID_CATEGORIES = tuple(DIRECTSHAPE_CATEGORIES)

#: Предел выдавливания/радиуса. Тот же порядок, что у `contour._validate_shape`
#: (сторона формы 100..500 000 мм): тело, у которого высота живёт по другим
#: правилам, чем его же профиль, — две системы координат в одной операции.
MIN_EXTENT_MM = 100.0
MAX_EXTENT_MM = 500_000.0

OPS = [
    OpSpec(
            name="create_solid_extrusion",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # ПРОФИЛЬ — РОД `region`, а не свой формат. CONTOUR уже
                # умеет rect/l/poly, дуги, проёмы и привязку к осям, и
                # ground.py опускает ЛЮБОЙ параметр рода `region` (правило
                # адресовано роду, а не имени опа, — 09.08). Свой формат
                # профиля был бы вторым домом для тех же законов.
                ParamSpec("profile", "region", required=True),
                # Высота — РАССТОЯНИЕ ВЫДАВЛИВАНИЯ вдоль +Z. Направление не
                # параметр: наклонная призма имеет замкнутый объём
                # (A·d·|d̂·ẑ|), но её боковые грани перестают быть теми
                # прямоугольниками, из которых считается допуск, а торцевой
                # свидетель перестаёт отличать торец от боковины по нормали.
                # Наклон — отдельная волна со своим выводом.
                ParamSpec("height_mm", "mm", required=True,
                          min_val=MIN_EXTENT_MM, max_val=MAX_EXTENT_MM),
                # Отметка плоскости профиля. НЕОБЯЗАТЕЛЬНА и БЕЗ УМОЛЧАНИЯ:
                # отсутствие означает плоскость Z=0 внутреннего начала
                # координат, и эмиссия тогда не печатает НИ ОДНОГО
                # преобразования (absent stays absent).
                #
                # УРОВНЯ ЗДЕСЬ НЕТ НАМЕРЕННО: у DirectShape нет привязки к
                # уровню, и селектор `level` пообещал бы связь, которой в
                # построенном элементе не существует — то же враньё, что
                # категория стены у меша, только тише.
                ParamSpec("base_z_mm", "mm",
                          min_val=-MAX_EXTENT_MM, max_val=MAX_EXTENT_MM),
                ParamSpec("category", "enum", required=True,
                          choices=SOLID_CATEGORIES),
                # Имя обязательно по той же причине, что у меша: у элемента
                # без типа имя — единственное, что отличает его от блоба.
                ParamSpec("name", "str", required=True, max_val=64),
            ),
            capability=(("create", "geometry"),),
            post=("solid direct shape exists (materialized or typed refusal); "
                  "built geometry holds exactly one solid (geometry); "
                  "solid volume == profile area * extrusion height, both "
                  "closed-form at compile time (geometry); "
                  "planar cap area == twice the profile area (geometry); "
                  "bbox extents == profile bbox by base_z..base_z+height in "
                  "XYZ (geometry)"),
            writes_model=True,
            # ПУСТО ПО ПОСТРОЕНИЮ: у DirectShape нет типа — нечего грунтовать.
            grounded=(),
            # ПУСТО ПО ПОСТРОЕНИЮ: допуск здесь — функция геометрии опа и
            # собственного числа Revit, а не константа. Разбор — в шапке.
            tolerances={},
        ),
    OpSpec(
            name="create_solid_revolve",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # Профиль читается В ОСЕВЫХ КООРДИНАТАХ: x контура — РАДИУС
                # от оси, y контура — отметка вдоль оси. Так требует сам
                # Revit («The loops must lie in the xz coordinate plane of
                # the input coordinate frame… on the "right" side of the z
                # axis (where x >= 0)»), и переучивать автора на третью
                # систему координат ради одной операции незачем.
                ParamSpec("profile", "region", required=True),
                # Ось — ВЕРТИКАЛЬНАЯ прямая через эту точку плана. Наклонной
                # оси в v1 нет: её пришлось бы задавать вторым вектором, а
                # профиль, заданный в плоскости этой оси, стал бы
                # непроверяемым на глаз. Габаритный свидетель кольцевого
                # сектора выведен именно для вертикальной оси.
                ParamSpec("axis_xy_mm", "pt_xy", required=True),
                ParamSpec("base_z_mm", "mm",
                          min_val=-MAX_EXTENT_MM, max_val=MAX_EXTENT_MM),
                # Угол поворота, градусы. Отсчёт ВСЕГДА от мировой оси +X:
                # начального угла как параметра нет, и это не умолчание, а
                # отсутствие степени свободы — рамка задана нами, значит 0
                # есть определение, а не догадка за автора.
                ParamSpec("sweep_deg", "num", required=True,
                          min_val=1, max_val=360),
                ParamSpec("category", "enum", required=True,
                          choices=SOLID_CATEGORIES),
                ParamSpec("name", "str", required=True, max_val=64),
            ),
            capability=(("create", "geometry"),),
            post=("revolved direct shape exists (materialized or typed "
                  "refusal); "
                  "built geometry holds exactly one solid (geometry); "
                  "solid volume == sweep radians * profile first moment about "
                  "the axis, closed-form at compile time (geometry); "
                  "planar cap area == twice the profile area for a sector and "
                  "zero for a full turn (geometry); "
                  "bbox extents == the swept annular sector of the profile in "
                  "XYZ (geometry)"),
            writes_model=True,
            grounded=(),
            tolerances={},
        ),
]
