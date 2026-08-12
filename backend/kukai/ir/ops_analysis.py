"""ops_analysis — нагрузки (КР) и путь эвакуации (АР): семейство, у которого до
этой волны не было НИ ОПА, НИ ОТКАЗА, НИ УПОМИНАНИЯ.

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

────────────────────────────────────────────────────────────────────────────
ЧЕМ МЕРЯЛОСЬ. Всё ниже снято с ЭТАЛОННЫХ СБОРОК
────────────────────────────────────────────────────────────────────────────

Каждая подпись и каждое читаемое свойство скомпилированы живым Roslyn
(localhost:52412) против настоящих `RevitAPI.dll` 2021-2026 ДО написания
эмиттера. `data/revit_api_db.json` доказанно неполон и здесь не спрашивался;
`RevitAPI.xml` читался напрямую, но арбитром был компилятор, а не документ.

────────────────────────────────────────────────────────────────────────────
ГЛАВНЫЙ ЗАМЕР: У НАГРУЗОК ЕСТЬ РАЗРЫВ ПОВЕРХНОСТИ НА 2024, И ОН ПОЛНЫЙ
────────────────────────────────────────────────────────────────────────────

Свободная (НЕ ХОСТИРОВАННАЯ) нагрузка выражается ТОЛЬКО на 2021-2023:

  PointLoad.Create(Document, XYZ point, XYZ force, XYZ moment,
                   PointLoadType, SketchPlane)                2021-2023, 3/6
  LineLoad.Create(Document, XYZ start, XYZ end, XYZ force,
                  XYZ moment, LineLoadType, SketchPlane)      2021-2023, 3/6
  AreaLoad.Create(Document, IList<CurveLoop>, XYZ force,
                  AreaLoadType)                               2021-2023, 3/6

На 2024-2026 этих перегрузок НЕТ ВООБЩЕ (`CS1503`/`CS1501`, замер), и это не
переименование: Autodesk убрала саму возможность создать нагрузку без
носителя. ВСЕ оставшиеся перегрузки первым (после документа) аргументом берут
`ElementId hostElemId` — «The AnalyticalElement host element for the load», —
то есть требуют АНАЛИТИЧЕСКИЙ элемент, которого у нас нет ни в снимке, ни в
языке ссылок.

ПОЧЕМУ НЕЛЬЗЯ ПРОСТО ПЕРЕДАТЬ `ElementId.InvalidElementId`. Компилируется —
проверено. Но документация 2024/2025/2026 дословно объявляет для этого же
аргумента `ArgumentException` «hostElemId is not permitted for this type of
load», и НИГДЕ не пишет, что недействительный id означает «без носителя».
Догадка о поведении, которую нельзя проверить без живого Revit, — это ровно
изобретение, запрещённое законом допусков, только про семантику вызова, а не
про число. Поэтому на 2024-2026 три операции нагрузок отказывают
ТИПИЗИРОВАННО (`KIR-E003`) и называют причину, а не строят «что-нибудь».

ЧТО СНИМЕТ ОТКАЗ (названо, чтобы следующая сессия не начинала с нуля): пул
аналитических элементов в снимке (`AnalyticalMember`/`AnalyticalPanel`, оба
класса существуют с 2023) плюс ОДИН живой прогон, показывающий, что
`PointLoad.IsValidHostId` отвечает на них true, а построенная нагрузка
читается обратно тем же свидетелем, что здесь. До этого прогона хостированная
нагрузка — не «недоделана», а НЕ ИЗМЕРЕНА.

────────────────────────────────────────────────────────────────────────────
РАБОЧАЯ ПЛОСКОСТЬ АВТОРИТСЯ НАМИ, А НЕ БЕРЁТСЯ У АКТИВНОГО ВИДА
────────────────────────────────────────────────────────────────────────────

Перегрузки точечной и линейной нагрузки принимают `SketchPlane plane`, и
Autodesk пишет: «Set null to use default plane». Умолчание здесь —
АКТИВНЫЙ ВИД пользователя, то есть вход, которого в программе нет. Отдать
ему отметку нагрузки значило бы построить элемент, чьё положение зависит от
того, какую вкладку человек последней открыл в Revit, — и это не теория:
исполнение едет через мост, активный вид на той машине нам неизвестен.

Поэтому эмиттер СТРОИТ ПЛОСКОСТЬ САМ (`SketchPlane.Create` +
`Plane.CreateByNormalAndOrigin`, обе 6/6) — через заданную точку у точечной
нагрузки, через оба конца у линейной. Следствие проверяемое: `PointLoad.Point`
и `StartPoint`/`EndPoint` обязаны совпасть с заказанными, и свидетель этого
требует. У площадной нагрузки плоскость задают сами кольца, аргумента плоскости
у неё нет.

────────────────────────────────────────────────────────────────────────────
ОРИЕНТАЦИЯ ПРИШПИЛЕНА, ИНАЧЕ ВЕКТОР СИЛЫ НИЧЕГО НЕ ЗНАЧИТ
────────────────────────────────────────────────────────────────────────────

`ForceVector` документирован дословно как «oriented according to OrientTo
setting». То есть одни и те же три числа означают РАЗНОЕ в зависимости от
системы отсчёта нагрузки, и «1000 Н вниз» на наклонной рабочей плоскости —
не вниз. Свидетель, сверяющий числа, не заметил бы подмены системы отсчёта
вообще: он читал бы ту же тройку.

Поэтому после создания эмиттер ставит `OrientTo = LoadOrientTo.Project`
(документировано как разрешённое для нехостированной нагрузки), ПОСЛЕ ЭТОГО
записывает вектор силы ещё раз — уже в пришпиленной системе — и свидетель
проверяет ОБА факта: и что система отсчёта проектная, и что вектор тот.
Порядок «сначала система, потом вектор» неслучаен: если бы Revit при смене
системы пересчитывал числа, проверка ловила бы собственный пересчёт.

────────────────────────────────────────────────────────────────────────────
ЕДИНИЦЫ: СПРАШИВАЕМ REVIT, А НЕ ПОМНИМ КОЭФФИЦИЕНТ
────────────────────────────────────────────────────────────────────────────

Внутренняя единица силы у Revit — не ньютон, и её значение нигде в этом
пакете не записано и записано не будет. Перевод идёт через
`UnitUtils.ConvertToInternalUnits(..., UnitTypeId.Newtons |
UnitTypeId.NewtonMeters | UnitTypeId.NewtonsPerMeter |
UnitTypeId.NewtonsPerSquareMeter)` — все четыре компилируются 6/6, — то есть
коэффициент знает сам Revit. Захардкоженный множитель здесь был бы тем же
классом дефекта, что захардкоженный допуск.

────────────────────────────────────────────────────────────────────────────
ДОПУСКИ: ГЕОМЕТРИЯ — У REVIT, СИЛА — ВЫВЕДЕНА ИЗ ГРАНИЦ И IEEE-754
────────────────────────────────────────────────────────────────────────────

ГЕОМЕТРИЯ. Ни одного числа ни в реестре, ни в C#: точки сравниваются с
`doc.Application.VertexTolerance` — собственным допуском Revit «две точки
ближе этого считаются одной», прочитанным у работающего приложения во время
проверки. Приём не новый: ровно так с 09.08 меряет значение
`create_dimension` (см. его докстринг — «no tolerance is invented for it, and
none is registered»). Мы сами авторим рабочую плоскость и сами кладём точки,
так что двигать их Revit незачем; если живой прогон покажет, что двигает,
проверка обязана быть заменена ИЗМЕРЕННЫМ сдвигом, а не ослаблена на вкус.
Направление ошибки при этом безопасное: слишком тугой допуск даёт ГРОМКИЙ
ложный отказ с откатом, а не тихий приём.

СИЛА. Число выведено, а не назначено:

  * реестр объявляет |f| <= 1e8 (Н, Н/м, Н/м²) — потолок мусора, не инженерный;
  * путь значения — `x -> x·k -> (x·k)/k`, две операции в double, каждая с
    ошибкой <= 0.5 ulp; с учётом представления самого x относительная ошибка
    не превышает 3·2^-53 ≈ 3.3e-16;
  * на верхней границе диапазона это 1e8 · 3.3e-16 = 3.3e-8;
  * ближайшая круглая декада строго выше — 1e-6, с запасом ~30x.

Момент считается так же и по той же границе, поэтому число у него то же.

────────────────────────────────────────────────────────────────────────────
СЛУЧАЙ ЗАГРУЖЕНИЯ — ОБЯЗАТЕЛЕН, И ЭТО НЕ ПЕДАНТИЗМ
────────────────────────────────────────────────────────────────────────────

`load_case` объявлен `required=True`, хотя API его не требует: без явной
установки Revit сам положит нагрузку в случай по умолчанию своей природы.
Именно это и есть тихо-неверный исход, ради которого компилятор существует —
нагрузка стоит, на экране выглядит правильно, а в сочетаниях участвует не в
том случае (или не участвует). Снаружи неотличимо от выполненной работы.
Поэтому случай называет АВТОР, эмиттер его записывает (`LoadBase.LoadCaseId`
доступен на запись, 6/6), а свидетель перечитывает `LoadCaseId` у
ПОСТРОЕННОГО элемента.

Пул `load_natures` НЕ ЗАВЕДЁН СОЗНАТЕЛЬНО: природа нагрузки — вход операции
СОЗДАНИЯ СЛУЧАЯ (`LoadCase.Create`), которой в этой волне нет, а закрытое
перечисление `query_types` по построению перечисляет пулы, ПО КОТОРЫМ
ЗАЗЕМЛЯЮТСЯ селекторы пишущих опов. Пул, которым никто не заземляется, стал
бы первым исключением из этого правила.

────────────────────────────────────────────────────────────────────────────
ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ (отвергнуто осознанно, не забыто)
────────────────────────────────────────────────────────────────────────────

1. `Autodesk.Revit.Creation.Document.NewPointBoundaryConditions` — ОПЕРАЦИИ
   НЕТ, потому что её единственный аргумент-носитель НЕ АДРЕСУЕМ ЭТИМ ЯЗЫКОМ.
   Перегрузка ровно одна на всех шести версиях, и берёт она
   `Autodesk.Revit.DB.Reference` — дословно «A Geometry reference to a Beam's,
   Brace's or Column's analytical line END». Замороженный диалект ссылок KIR —
   `{"by": "name"|"element_id"|"ref"}` — умеет называть ЭЛЕМЕНТЫ; «конец
   аналитической линии вон той колонны» назвать нечем ВООБЩЕ. Тот же случай,
   что у отвергнутого `create_wire` с его `Connector`: не «пока неудобно», а
   невыразимо по построению.

2. `NewLineBoundaryConditions` / `NewAreaBoundaryConditions` в форме ОТ
   ЭЛЕМЕНТА — адресуемы (берут `Element`: «A Beam» и «A Wall, Slab or Slab
   Foundation»), компилируются 6/6, и операции всё равно НЕТ. Причина ровно
   одна и она про свидетеля: ВЕСЬ профессиональный смысл опоры — это шесть
   степеней свободы (Fixed/Release/Spring по трём переносам и трём
   поворотам), а прочитать их обратно НЕЧЕМ. У `BoundaryConditions` нет ни
   одного свойства о степенях свободы: есть `HostElementId`, `Point`,
   `GetCurve`, `GetLoops`, `GetBoundaryConditionsType`,
   `GetDegreesOfFreedomCoordinateSystem` — и ни одного значения
   `TranslationRotationValue`. Встроенные параметры (`BOUNDARY_RESTRAINT_*`,
   `BOUNDARY_LINEAR_RESTRAINT_*`, `BOUNDARY_AREA_RESTRAINT_*`) существуют на
   всех шести версиях, но хранят ЦЕЛОЕ, чьё соответствие членам
   `TranslationRotationValue` Autodesk нигде не документирует. Свидетель,
   подписывающий «опора на этой балке существует» там, где заказанное
   шарнирное закрепление могло стать жёстким, — витрина, а не доказательство:
   в расчётной схеме это разница между работающей и неработающей конструкцией.
   ЧТО СНИМЕТ ОТКАЗ: один живой прогон, ставящий три известных значения и
   читающий параметр обратно, — после него соответствие ИЗМЕРЕНО, и свидетель
   пишется механически.

3. Момент у линейной и площадной нагрузки. Линейной он передаётся НУЛЁМ
   (аргумент обязателен), площадная его не имеет вовсе. Ноль в любых единицах
   ноль, поэтому вопроса о единице момента на метр здесь не возникает, а
   крутящая линейная нагрузка остаётся НАЗВАННЫМ пробелом, а не молчаливым.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/...)

#: Потолок модуля компоненты силы. Не инженерная граница, а граница МУСОРА:
#: 1e8 Н — сто тысяч тонн-силы, на порядки выше всего, что бывает в проекте.
#: Число тем не менее РАБОТАЕТ, а не украшает: из него выведен допуск силы
#: (см. шапку — 1e8 · 3.3e-16 = 3.3e-8, ближайшая круглая декада выше 1e-6).
#: Опустить границу — значит обязать опустить и допуск.
_FORCE_LIMIT = 100_000_000

#: Допуск силы/момента, ВЫВЕДЕННЫЙ из `_FORCE_LIMIT` и двоичной плавающей
#: арифметики. Один и тот же у всех трёх нагрузок, потому что вывод один и тот
#: же: у них общая граница диапазона и общий путь значения через UnitUtils.
_FORCE_TOL = 1e-6

OPS = [
    # ── Точечная нагрузка ──────────────────────────────────────────────────
    # Самая простая из трёх и поэтому первая: она задаёт форму всей волны —
    # своя рабочая плоскость, пришпиленная система отсчёта, вектор силы в СИ,
    # названный случай загружения, и свидетель, читающий у ПОСТРОЕННОГО
    # элемента `Point` / `ForceVector` / `MomentVector` / `OrientTo` /
    # `LoadCaseId` / `GetTypeId`, а не подтверждающий, что вызов состоялся.
    OpSpec(
        name="create_point_load",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("xyz", "pt_xyz", required=True),
            ParamSpec("fx_n", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fy_n", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fz_n", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("mx_nm", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("my_nm", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("mz_nm", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("load_case", "sel", required=True),
            ParamSpec("load_type", "sel"),   # omitted -> sole entry, else AMBIGUOUS
        ),
        capability=(("create", "load"),),
        post=("point load exists; Point of the built element == xyz "
              "(VertexTolerance, 3D, geometry); OrientTo of the built element "
              "== Project (semantic); ForceVector of the built element == "
              "[fx_n, fy_n, fz_n] newtons (±0.000001, semantic); MomentVector "
              "of the built element == [mx_nm, my_nm, mz_nm] newton-metres "
              "(±0.000001, semantic); load case of the built element == "
              "resolved load_case (semantic); load_type of the built element "
              "== resolved load_type (semantic)"),
        writes_model=True,
        grounded=(("load_case", "load_cases", True),
                  ("load_type", "point_load_types", False)),
        tolerances={"force_n": _FORCE_TOL, "moment_nm": _FORCE_TOL},
    ),
    # ── Линейная нагрузка ──────────────────────────────────────────────────
    # Оба конца ТРЁХМЕРНЫЕ и по той же причине, что у create_beam: погонная
    # нагрузка ложится и на наклонный элемент, а молча дописанный нулевой Z
    # положил бы её на абсолютную отметку 0. Рабочая плоскость строится через
    # ОБА конца (горизонтальная, если отметки равны; вертикальная, содержащая
    # отрезок, иначе) — вычисляется в питоне, в C# едут литералы.
    #
    # `IsUniform` читается обратно и подписан отдельно: перегрузка принимает
    # ОДИН вектор силы, то есть равномерность — обещание НАШЕЙ формы вызова, и
    # если Revit её не сохранил, нагрузка получилась другая при зелёной
    # геометрии.
    OpSpec(
        name="create_line_load",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("p0_mm", "pt_xyz", required=True),
            ParamSpec("p1_mm", "pt_xyz", required=True),
            ParamSpec("fx_n_per_m", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fy_n_per_m", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fz_n_per_m", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("load_case", "sel", required=True),
            ParamSpec("load_type", "sel"),
        ),
        capability=(("create", "load"),),
        post=("line load exists; StartPoint and EndPoint of the built element "
              "== p0_mm and p1_mm (VertexTolerance, 3D, geometry); OrientTo of "
              "the built element == Project (semantic); ForceVector1 of the "
              "built element == [fx_n_per_m, fy_n_per_m, fz_n_per_m] newtons "
              "per metre (±0.000001, semantic); IsUniform of the built element "
              "(semantic); load case of the built element == resolved "
              "load_case (semantic); load_type of the built element == "
              "resolved load_type (semantic)"),
        writes_model=True,
        grounded=(("load_case", "load_cases", True),
                  ("load_type", "line_load_types", False)),
        tolerances={"force_n_per_m": _FORCE_TOL},
    ),
    # ── Площадная нагрузка ─────────────────────────────────────────────────
    # Кольцо плоское и горизонтальное на отметке `elev_mm`: перегрузка берёт
    # `IList<CurveLoop>` и плоскость выводит из них сама, поэтому аргумента
    # плоскости у неё нет и авторить её нечем.
    #
    # СВИДЕТЕЛЬ ЧИТАЕТ КОЛЬЦА, А НЕ ПЛОЩАДЬ. `AreaLoad.Area` в квитанцию
    # едет, но обязательством НЕ ЯВЛЯЕТСЯ: это величина, которую Revit
    # ВЫВОДИТ из тех самых колец, что свидетель уже пришпилил повершинно, —
    # проверять её отдельно значило бы завести второй допуск (площадный) ради
    # следствия уже проверенного факта. Сверка вершин при этом НЕ
    # ПОЗИЦИОННАЯ: `CurveLoop` канонизирует кольцо (начальная вершина и
    # направление обхода — дело Revit), поэтому каждая заказанная вершина
    # ищется СРЕДИ возвращённых, и требуется совпадение их ЧИСЛА.
    OpSpec(
        name="create_area_load",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("outline", "pts", required=True),
            ParamSpec("elev_mm", "mm", required=True,
                      min_val=-1_000_000, max_val=1_000_000),
            ParamSpec("fx_n_per_m2", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fy_n_per_m2", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fz_n_per_m2", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("load_case", "sel", required=True),
            ParamSpec("load_type", "sel"),
        ),
        capability=(("create", "load"),),
        post=("area load exists; GetLoops of the built element returns one "
              "loop whose vertices are the outline at elev_mm, same count "
              "(VertexTolerance, 3D, geometry); OrientTo of the built element "
              "== Project (semantic); ForceVector1 of the built element == "
              "[fx_n_per_m2, fy_n_per_m2, fz_n_per_m2] newtons per square "
              "metre (±0.000001, semantic); load case of the built element == "
              "resolved load_case (semantic); load_type of the built element "
              "== resolved load_type (semantic)"),
        writes_model=True,
        grounded=(("load_case", "load_cases", True),
                  ("load_type", "area_load_types", False)),
        tolerances={"force_n_per_m2": _FORCE_TOL},
    ),
    # ── Путь эвакуации ─────────────────────────────────────────────────────
    # ЕДИНСТВЕННАЯ операция этой волны, живая на всех шести версиях
    # (`PathOfTravel.Create` есть с 2020 и не менялась), и единственная, чью
    # ГЕОМЕТРИЮ СЧИТАЕМ НЕ МЫ. Отсюда честная граница обещания, выписанная
    # прямо здесь:
    #
    # ЧТО УТВЕРЖДАЕТСЯ. Расчёт завершился успехом (перечисление
    # `PathOfTravelCalculationStatus` одинаково на шести версиях, и всё, кроме
    # `Success`, — типизированный отказ ДО постусловий); маршрут принадлежит
    # заказанному виду; его концы — заказанные точки; маршрут непуст и его
    # суммарная длина НЕ МЕНЬШЕ прямой между концами.
    #
    # ЧТО НЕ УТВЕРЖДАЕТСЯ И ПОЧЕМУ. Форма маршрута — вывод Revit по
    # препятствиям вида, и «обошёл ли он их правильно» невыразимо: у нас нет
    # независимой модели препятствий, а сравнивать вывод Revit с выводом Revit
    # бессмысленно. Длина проверяется НЕРАВЕНСТВОМ, а не равенством, и это не
    # слабость проверки, а её точная граница: «путь короче прямой» —
    # геометрически невозможное состояние, то есть настоящий отказ, а любое
    # конкретное ожидаемое число было бы выдумкой.
    #
    # КООРДИНАТА Z НЕ СВЕРЯЕТСЯ ПО ДОКУМЕНТАЦИИ, А НЕ ПО СНИСХОДИТЕЛЬНОСТИ:
    # Autodesk пишет дословно «The input Z coordinates are ignored and set to
    # the view's level elevation». Поэтому и род параметров здесь `pt_xy`:
    # факт «третьей координаты у этой операции нет» вписан в ТИП, а не в
    # прозу, которую можно не прочитать.
    OpSpec(
        name="create_path_of_travel",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("p0_mm", "pt_xy", required=True),
            ParamSpec("p1_mm", "pt_xy", required=True),
        ),
        capability=(("create", "path_of_travel"),),
        post=("path of travel exists and its calculation status is Success; "
              "PathStart and PathEnd of the built element == p0_mm and p1_mm "
              "in plan (VertexTolerance, geometry, Z excluded — the API "
              "replaces it with the view level elevation); the route read back "
              "is non-empty and no shorter than the straight line between the "
              "requested points (geometry); OwnerViewId of the built element "
              "== in_view (topology)"),
        writes_model=True,
    ),
]
