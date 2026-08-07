"""ops_shape — произвольная геометрия мешем (DirectShape).

Registry module — операции добавляются СЮДА, а не в spec.py. Эмиттер живёт в
shape_emit.py (парный файл, ровно как ops_arch.py + arch_emit.py у волны АР);
authoring.py получает только импорт и одну строку в _EMITTERS. Законы формы
меша — в mesh.py.

ЗАЧЕМ ВОЛНА. KIR задуман экзоскелетом для нейросети: модель придумывает
геометрию, инструмент снимает с неё версии Revit, транзакции, типы, хосты,
единицы и откат. Но все 32 операции реестра зданиецентричны — уровни, стены,
помещения, контуры, — и произвольную форму (оболочку, решётку, витую башню)
модель не может выразить НИЧЕМ. Стена стоит ровно там, где сила модели
наибольшая.

═══ ЧЕСТНАЯ ЭТИКЕТКА ═══════════════════════════════════════════════════════

DirectShape — ГЕОМЕТРИЯ БЕЗ BIM-СМЫСЛА. Это не оговорка мелким шрифтом, а
главное свойство операции, и она обязана произносить его сама:

  * ТИПА НЕТ. У элемента нет ни типоразмера, ни его параметров. Поэтому у
    операции нет параметра `type` и НЕТ НИ ОДНОГО пула в `grounded` — не по
    недоделке, а потому что подставлять нечего. Единственная операция реестра
    без грунтовки, и это факт о DirectShape, а не о нашей лени.
  * ПАРАМЕТРОВ НЕТ. Толщины, материала слоёв, огнестойкости — ничего этого у
    меша не существует. Спецификация по такому элементу посчитает штуки, а не
    квадратные метры стен.
  * ЧЕЛОВЕК ЕГО НЕ ОТРЕДАКТИРУЕТ. Стену тянут за ручку и меняют тип; меш
    можно только удалить и построить заново. Это односторонняя дверь.

Отсюда две решённые конструктивные вещи, обе — против вранья:

1. КЛЕТКА СПОСОБНОСТИ — («create», «geometry»), и НЕ («create», «element»).
   Все остальные пишущие операции реестра объявляют «element»; куб покрытия
   покажет эту — и только эту — как создающую ГЕОМЕТРИЮ. Так «мы это умеем»
   не превратится в отчёте в «мы умеем создавать элементы такого рода».

2. КАТЕГОРИИ ОГРАНИЧЕНЫ ТЕМИ, ЧТО НЕ ВЫДАЮТ СЕБЯ ЗА ЧУЖОЕ (см. таблицу).
   BuiltInCategory.OST_Walls компилируется (замерено 6/6), и соблазн
   разрешить его велик: «пользователь просил стену — вот стена». Но меш в
   категории стен читается стеной в КАЖДОМ фильтре, спецификации и выгрузке,
   не будучи ничем, чем стена является: без слоёв, без соединений, без
   проёмов, без высоты. Снаружи это неотличимо от успеха — тот самый Гудхарт,
   который в этом доме стоил 96.77% групп. У KIR есть настоящие create_wall/
   create_floor/create_roof/create_column/create_beam; там, где они есть,
   мешу нечего делать под их вывеской. Отказ называет их поимённо.

ЗАМЕРЫ API (живой компайл-сервис :52412, 2021-2026, 29.07 — имена у нас
проверяются компиляцией, а не памятью):

  DirectShape.CreateElement(doc, ElementId categoryId)      → 6/6
  DirectShape.CreateElement(doc, catId, string, string)     → 0/6  ← ПАМЯТЬ
      CS1501 No overload for method 'CreateElement' takes 4 arguments
  DirectShape.IsValidCategoryId(ElementId, Document)        → 6/6
  DirectShape.GetValidCategoryIds(Document)                 → 0/6
      CS0117 'DirectShape' does not contain a definition for it
  TessellatedShapeBuilder + OpenConnectedFaceSet/AddFace/
      CloseConnectedFaceSet/Build/GetBuildResult             → 6/6
  new TessellatedFace(IList<XYZ>, ElementId)                → 6/6
  new TessellatedFace(IList<XYZ>)                           → 0/6
      CS1729 does not contain a constructor that takes 1 arguments
  TessellatedShapeBuilderTarget.{AnyGeometry,Mesh,Solid}    → 6/6
  TessellatedShapeBuilderFallback.{Abort,Mesh,Salvage}      → 6/6
  TessellatedShapeBuilderOutcome.{Nothing,Mesh,Solid}       → 6/6
  ElementId.IntegerValue                                    → 5/6  (нет в 2026)

Четырёхаргументный CreateElement — это ровно тот случай, о котором
предупреждает шапка extract.py: по памяти он пишется первым (так выглядит
почти весь код DirectShape в интернете и в старых версиях API), компилятор
принял бы его молча, если бы он существовал, и мы бы узнали о беде живьём.
Он не существует ни на одной из шести версий. Проверять компиляцией, а не
памятью, — не ритуал.

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ:

* МАТЕРИАЛ. TessellatedFace принимает materialId, и передавать туда
  ElementId.InvalidElementId — единственное, что мы можем доказать офлайн.
  Параметр материала потребовал бы своего пула и своей грунтовки; заводить
  его «на всякий случай» с угаданным поведением — тот же класс ошибки, что
  уклон потолка у волны АР. Пока грань строится материалом по умолчанию.
* СОЛИД. TessellatedShapeBuilderTarget.Solid компилируется, но требует
  замкнутого тела, а открытая оболочка — половина осмысленных мешей. Солид —
  отдельная волна с живым замером, а не флажок здесь.

ЗАМЕР, КОТОРЫЙ ВОРОТА НЕ ЛОВЯТ (и потому записан отдельно). Пара
Target=Mesh + Fallback=Abort компилируется 6/6 и НЕ ЯВЛЯЕТСЯ поддерживаемой:
RevitAPI.xml эталонного пакета, примечание к TessellatedShapeBuilder.Build,
дословно и одинаково в 2021 и в 2026 —

    Currently only "Solid/Abort", "AnyGeometry/Mesh" and "Mesh/Salvage"
    target/fallback combinations are supported.

Эмиттер поэтому ставит Mesh/Salvage, а молчаливость Salvage («использовать все
пригодные данные») закрыта свидетелем числа граней, а не надеждой. Подробный
разбор — в шапке shape_emit.py. Вывод для будущих волн: зелёные ворота
доказывают, что код СОБЕРЁТСЯ, и ничего не говорят о том, что Revit его
примет; для второго есть RevitAPI.xml и живой прогон.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)

#: `category` словами <-> члены BuiltInCategory. ОДНА таблица на эмиттер и
#: лифт, чтобы два направления не разъехались — тот же приём, что
#: RAILING_PLACEMENT_MEMBERS у волны АР и WALL_LOCATION_LINE_ORDINALS у стен.
#:
#: Множество ЗАКРЫТО и сознательно узко: сюда входят только категории, которые
#: и в родном Revit означают «объём без BIM-роли». Категории, у которых в KIR
#: есть настоящая операция (стены, перекрытия, кровли, колонны, каркас),
#: отсутствуют намеренно — см. пункт 2 шапки. Все члены замерены 6/6.
DIRECTSHAPE_CATEGORIES = freeze_registry_mapping({
    "generic_model": "OST_GenericModel",
    "mass": "OST_Mass",
    "site": "OST_Site",
    "entourage": "OST_Entourage",
    "specialty_equipment": "OST_SpecialityEquipment",
    "furniture": "OST_Furniture",
})

#: Категории, которые компилируются, но запрещены здесь, и операция, которая
#: делает то же самое ЧЕСТНО. Читается отказом, поэтому пользователь узнаёт не
#: «нельзя», а «вот чем это делается».
IMPERSONATION_ROUTES = freeze_registry_mapping({
    "walls": "create_wall",
    "floors": "create_floor / create_floor_by_contour",
    "roofs": "create_roof",
    "columns": "create_column",
    "structural_columns": "create_column",
    "structural_framing": "create_beam",
    "ceilings": "create_ceiling",
    "stairs": "create_stairs",
})

OPS = [
    OpSpec(
            name="create_directshape",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # Меш — ОДНО значение, а не два параллельных списка. Иначе
                # схема допускала бы состояние «вершины есть, треугольников
                # нет», то есть ровно тот класс, где отсутствие превращается
                # в ноль. Индексы без вершинного массива не проверяемы в
                # принципе, значит вместе они и должны ехать.
                ParamSpec("mesh", "mesh", required=True),
                ParamSpec("category", "enum", required=True,
                          choices=tuple(DIRECTSHAPE_CATEGORIES)),
                # Имя ОБЯЗАТЕЛЬНО. У элемента без типа имя — единственное, что
                # отличает его от безымянного блоба в дереве проекта; человек,
                # открывший модель через год, читает именно его. Необязательное
                # имя означало бы «можно и молча».
                ParamSpec("name", "str", required=True, max_val=64),
            ),
            # ГЕОМЕТРИЯ, А НЕ ЭЛЕМЕНТ — см. пункт 1 шапки. Единственная
            # пишущая операция реестра с такой клеткой.
            capability=(("create", "geometry"),),
            # Обещано ровно то, что проверяется, и каждое обещание читает
            # РЕЗУЛЬТАТ, а не наш вызов: габарит и число треугольников
            # вычитываются из построенной геометрии элемента.
            post=("direct shape exists (materialized or typed refusal); "
                  "bbox extents == mesh vertex extents in XYZ (±5mm, "
                  "geometry); "
                  "built mesh triangle count == triangles count (geometry)"),
            writes_model=True,
            # ПУСТО, И ЭТО СОДЕРЖАТЕЛЬНО: у DirectShape нет типа, значит нет
            # ни пула, ни грунтовки. Единственная пишущая операция реестра без
            # grounded — см. «ЧЕСТНАЯ ЭТИКЕТКА».
            grounded=(),
            tolerances={"bbox_mm": 5.0},
        ),
]
