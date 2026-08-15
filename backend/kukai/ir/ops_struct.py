"""ops_struct — structural ops (beams/foundations/rebar). wave/struct
(2026-07-17): create_beam + create_foundation. Rebar stays STUB (out of this
wave's scope — see wave report).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

create_beam: FamilyInstance over a line, StructuralType.Beam — the same
NewFamilyInstance(Line, FamilySymbol, Level, StructuralType) overload the
gold SDK sample CreateBeamsColumnsBraces/CS/CreateBeamsColumnsBraces.cs
uses (PlaceBeam(), verified locally at
/root/27B/harvest/sdk_samples/snapshot/2025/Samples/CreateBeamsColumnsBraces/CS/CreateBeamsColumnsBraces.cs
lines 376-388: `Line line = Line.CreateBound(...); ... NewFamilyInstance(line,
beamType, topLevel, StructuralType.Beam);` with an IsActive/Activate() guard
— exactly authoring.py's existing _symbol_res() helper). Version-safe
2021-2026: same overload family create_column already relies on, only the
StructuralType enum member differs.

p0_mm/p1_mm are REQUIRED 3D (pt_xyz, like create_pipe) rather than 2D-plus-
level-elevation (like create_wall): a beam's two ends commonly sit at
DIFFERENT elevations (sloped beam / connecting columns whose tops differ),
so silently defaulting a missing Z to 0 (authoring._pt3's existing behavior
for a bare-2D point) would place a beam at absolute Z=0 while the resolved
level sits at its own elevation — a silent-wrong floating beam, exactly the
class of bug this project exists to kill. authoring.validate()'s dims-by-
name dispatch (`dims = (3,) if name in ("create_pipe", "create_duct",
"create_cable_tray") else (2, 3)`) is name-hardcoded to a tuple that does
NOT include create_beam; "create_beam" must be appended to that tuple for
the 3D requirement to actually be enforced (currently a (2,3) fallthrough
would silently accept a 2D point here too). This is a ONE-TOKEN additive
touch to a shared line in authoring.py, made alongside the _EMITTERS
registration (same file already gets touched per every prior wave's
precedent — see wave/mep's authoring.py diff) — flagged explicitly in the
wave report as a real, unavoidable shared-file dependency, not invented
scope-creep.

create_foundation: TWO real, distinct structural varieties, discriminated by
`variety` (NOT named "kind" — see naming note below):
  - variety="isolated" (столбчатый под колонну/точку): FamilyInstance placed
    at a point, StructuralType.Footing. Mirrors create_column's point-
    placement shape exactly (NewFamilyInstance(XYZ, FamilySymbol, Level,
    StructuralType)), enum member swapped Column->Footing. StructuralType.
    Footing verified as a REAL enum member via local SDK grep (BoundaryConditions/
    CS/{BoundaryConditionsData,Command}.cs read/filter it off existing
    instances — no local sample CREATES one, so the create-side call is
    confident-by-overload-analogy + enum-verified, not sample-verified;
    flagged in the wave report per the task's own escape hatch).
  - variety="slab" (ленточный/плитный — modeled as a structural mat/strip
    footing, i.e. a structural Floor by contour): this IS create_floor's
    existing structural=True path (create_floor's own post-condition already
    says "structural flag == requested (semantic)" — a foundation slab is
    that op with structural forced True). Reused, not duplicated: struct_emit.
    _emit_foundation_slab mirrors _emit_floor's 2022+/2021 structural path at
    the same fidelity (see struct_emit.py's module docstring for why it's a
    mirror, not a cross-import of a private function). No new C# geometry
    logic invented for this variant.
  - a true ribbon/grillage foundation (real ростверк geometry: varying
    width along a beam-like path, stepped sections) is NOT modeled: no
    confident single-call Revit API shape and no local gold sample to check
    against. FOUNDATION_UNSUPPORTED_KIND (struct_emit.py) is the typed
    refusal for any variety outside the closed {isolated, slab} enum — never
    a silent guess.

create_wall_foundation: НОВЫЙ ОП, А НЕ ТРЕТЬЯ РАЗНОВИДНОСТЬ create_foundation
— и это решение, а не вкус. Ленточный фундамент (WallFoundation) не делит с
create_foundation НИ ОДНОГО параметра: у него нет ни точки, ни контура, ни
уровня — весь его вход это СТЕНА-НОСИТЕЛЬ, которая сама несёт и уровень, и
путь, и протяжённость. А `create_foundation.level` объявлен required=True;
третья ветвь заставила бы ослабить его до необязательного (как это пришлось
сделать `create_railing.level`), и тогда пропущенный уровень у ветвей
isolated/slab перестал бы быть жёстким отказом «level обязателен» и поехал бы
по общему правилу «единственный в пуле» — то есть в модели с одним уровнем
молча подставлялся бы. Расширение перечисления ЗАБРАЛО БЫ строгость у уже
работающих ветвей ради ветви, которой уровень не нужен вовсе; отдельный оп не
забирает ничего.

ЗАМЕР API (компиляция на :52412, 2021-2026, 09.08 — арбитр здесь компилятор, а
не XML; см. инженерные правила про SpatialElementTag):

  WallFoundation.Create(Document, ElementId typeId, ElementId wallId)  → 6/6
  WallFoundation.WallId                                                → 6/6
  ElementTypeGroup.WallFoundationType                                  → 6/6
  FilteredElementCollector(doc).OfClass(typeof(WallFoundationType))    → 6/6
  WallFoundation.GetHostIds()                    → 0/6  CS1061, НЕ СУЩЕСТВУЕТ
  WallFoundation.WallAllowsWallFoundation(Wall)  → 0/6  CS0117, НЕ СУЩЕСТВУЕТ

Последние две строки — исправление входного задания, а не педантизм. Оба
имени существуют, но у ДРУГОГО класса: `WallSweep.GetHostIds()` и
`WallSweep.WallAllowsWallSweep(Wall)` (grep по RevitAPI.xml всех шести версий,
подтверждено компиляцией). Значит ПРЕДПОЛЁТНОЙ проверки «можно ли повесить
фундамент на эту стену» в API нет вовсе, и выдумывать её нельзя: единственная
доступная защита — типизированный отказ по факту (`as Wall` даёт null, либо
Create возвращает null).

ПОЧЕМУ ПАРАМЕТР ЗОВЁТСЯ `wall`, А НЕ `host`. Так называет его сам API
(аргумент `wallId`, свойство `WallFoundation.WallId`), поэтому свидетель
читает свойство, одноимённое параметру. Есть и второе следствие, названное
прямо, чтобы не читалось как обход правила: authoring_validation.py держит
правило «`host` — только ref» с поимённым списком исключений, и оно про
ХОСТИНГ ПО ГЕОМЕТРИИ (дверь/окно/панель/проём/ограждение — эмиттер сам считает
точку вставки внутри носителя). У ленточного фундамента геометрии размещения
нет ни одной строки: стена — обычный аргумент вызова. Обе дороги (имя `wall`
или `host` + строчка в списке исключений) дают ОДНУ И ТУ ЖЕ семантику
«ref ЛИБО element_id», и она здесь обязательна: фундамент подводят под
СУЩЕСТВУЮЩУЮ стену не реже, чем под построенную этой же программой — тот же
довод, которым create_opening отбил требование ref-only.

ГЕОМЕТРИЯ НЕ ПРОВЕРЯЕТСЯ, И ЭТО НАЗВАНО В `post`. Свидетеля на габарит здесь
НЕТ намеренно: отношение подошвы к стене (свес по бокам, выпуск за торцы,
отметка низа) НЕ ЗАМЕРЕНО ни на одном здании — во всех 60+ сохранённых
разборах на диске нет НИ ОДНОГО WallFoundation (проверено grep'ом 09.08), то
есть взять число неоткуда. Допуск, выведенный рассуждением, — это ровно
`create_door.sill_mm min_val=0` (140 отрицательных отметок из 151 в реальном
доме) и `_SHEET_LIMIT_MM` (10 м на здании, где стены стоят в 82-110 м).
Отсутствующая проверка честнее выдуманной, а проверка, которая не может
упасть, хуже отсутствующей. Закрывает этот пробел ОДИН живой прогон, а не
ещё один час рассуждений.

ЧТО ОСТАЁТСЯ ЗАКРЫТЫМ: FOUNDATION_UNSUPPORTED_KIND у create_foundation НЕ
ТРОНУТ. Ростверк и свая по-прежнему отказ: у `Autodesk.Revit.DB.Foundation`
нет ни одного документированного метода, а фабрики «Grillage»/«Pile» нет во
всём API. Эта волна закрывает ровно ленточный случай — тот, у которого
единственный вызов есть и он одинаков на всех шести версиях.

create_beam_system / create_truss: ВОЛНА КАРКАСА (09.08.2026). Обе операции
перепись нашла НИ РАЗУ НЕ РАССМОТРЕННЫМИ, и обе закрывают одну и ту же дыру:
до них единственным способом сказать «здесь каркас по эскизу» была пачка
отдельных create_beam с зафиксированными координатами — то есть потеря самого
ОБЪЕКТА и его раскладки.

ЗАМЕР API (компиляция на :52412 против настоящих сборок 2021-2026, 09.08 —
арбитр компилятор, а не XML):

  BeamSystem.Create(Document, IList<Curve>, Level, XYZ, bool)        → 6/6
  BeamSystem.Create(Document, IList<Curve>, Level, int, bool)        → 6/6
  BeamSystem.Create(Document, IList<Curve>, SketchPlane, XYZ, bool)  → 6/6
  BeamSystem.Create(Document, IList<Curve>, SketchPlane, int)        → 6/6
  BeamSystem.Profile (CurveArray) / GetBeamIds() (ICollection)       → 6/6
  BeamSystem.Direction / .Elevation / .Level / .LayoutRule           → 6/6
  BeamSystem.BeamType — читается И ПИШЕТСЯ (FamilySymbol)            → 6/6
  Truss.Create(Document, ElementId, ElementId sketchPlaneId, Curve)  → 6/6
  Truss.Curves (CurveArray) / Truss.Members (ICollection<ElementId>) → 6/6
  TrussType : FamilySymbol (IsActive/Activate/Family)                → 6/6
  SketchPlane.Create(Document, ElementId уровня)                     → 6/6
  BuiltInParameter.TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM               → 6/6
  ElementTypeGroup.BeamSystemType                                    → 6/6

  IList<Curve> x = beamSystem.Profile          → 0/6  CS0266 (это CurveArray)
  truss.Members.Size                           → 0/6  CS1061 (не ElementIdSet)
  ElementTypeGroup.TrussType                   → 0/6  CS0117, НЕ СУЩЕСТВУЕТ
  ElementTypeGroup.StructuralFramingType       → 0/6  CS0117, НЕ СУЩЕСТВУЕТ
  BuiltInParameter.BEAM_SYSTEM_LEVEL_PARAM     → 0/6  CS0117, НЕ СУЩЕСТВУЕТ
  BuiltInParameter.BEAM_SYSTEM_ELEVATION_PARAM → 0/6  CS0117, НЕ СУЩЕСТВУЕТ

Нижние шесть строк — не педантизм, каждая закрыла соблазн. Уровень балочной
системы читается СВОЙСТВОМ (цепочки BIP у неё нет вовсе), тип фермы и «тип
балки по умолчанию» спросить у документа НЕЛЬЗЯ ПО ПОСТРОЕНИЮ (как у двери и
окна — см. НАЗВАННОЕ УМОЛЧАНИЕ в инженерных правилах KIR), а `Members` считается
`.Count`, а не `.Size`.

ПРОФИЛЬ БАЛОЧНОЙ СИСТЕМЫ — ЕСТЕСТВЕННЫЙ ПОТРЕБИТЕЛЬ CONTOUR, И ЭТО ЗАМЕР, А
НЕ АНАЛОГИЯ. Канонический вид CONTOUR — замкнутый список рёбер [(p0,p1,bulge)]
с Line при bulge==0 и Arc.Create по трём литеральным точкам иначе; аргумент
`profile` у `BeamSystem.Create` — это `IList<Curve>` ровно из таких кривых.
Совпадает всё, кроме ОДНОГО: у региона есть `holes`, а у вызова второго кольца
нет ни на одной версии. Поэтому `profile` объявлен родом `region` (и получает
даром адреса точек от осей, законы дуг, нулевые рёбра, самопересечение и
вырожденную площадь — ground.py опускает ЛЮБОЙ параметр этого рода), а дырки
ОТКАЗЫВАЮТСЯ типизированно (KIR-E008). У фермы CONTOUR не нужен вовсе: её вход
это ОДНА прямая (`Curve`, «must be a line, must not be vertical, must be
within the sketch plane»), то есть p0/p1 + уровень.

ЧТО ВЫЧИСЛЯЕТ REVIT, ТО НЕ ПРОВЕРЯЕТСЯ — и названо в `post` отдельной
клаузулой. Число и шаг балок выбирает `LayoutRule`, которого НИ ОДИН аргумент
`Create` не задаёт: автор никакого количества не называл, и потребовать его
значило бы повторить дефект `height_mm` (31.07, откатывались верно
построенные фасадные стены). Проверяется РЕЗУЛЬТАТ, который заказан самим
фактом операции: `GetBeamIds()` не пуст, `Members` не пуст. Ноль — настоящий
исход (профиль мельче шага раскладки), и снаружи он неотличим от успеха.

create_area_reinforcement: ВОЛНА АРМИРОВАНИЯ (10.08.2026). Перепись нашла
`Rebar`, `AreaReinforcement`, `PathReinforcement`, `FabricArea`,
`FabricSheet`, `StructuralConnectionHandler` и три вида `BoundaryConditions`
НИ РАЗУ НЕ РАССМАТРИВАВШИМИСЯ. Замерены все девять (таблица ниже), взят
ОДИН — тот, у которого свидетель читает РЕЗУЛЬТАТ и может ПРОВАЛИТЬСЯ.

ЗАМЕР API (компиляция на :52412 против настоящих сборок 2021-2026, 10.08 —
арбитр компилятор, а не XML; см. инженерные правила про SpatialElementTag):

  AreaReinforcement.Create(Document, Element, XYZ, ElementId×3)      → 6/6
  AreaReinforcement.Create(Document, Element, IList<Curve>, XYZ, ×3) → 6/6
  AreaReinforcement.GetHostId() / .GetTypeId()                       → 6/6
  AreaReinforcement.GetRebarInSystemIds() / .GetBoundaryCurveIds()   → 6/6
  AreaReinforcement.Direction / .AreaReinforcementType               → 6/6
  RebarHostData.IsValidHost(Element)  — ПРЕДПОЛЁТНАЯ проверка!       → 6/6
  ReinforcementSettings.GetReinforcementSettings(doc)
      .HostStructuralRebar                                          → 6/6
  RebarInSystem.GetTypeId() / .SystemId / .GetHookTypeId(int)        → 6/6
  ElementTypeGroup.AreaReinforcementType / .RebarBarType             → 6/6
  FilteredElementCollector по AreaReinforcementType / RebarBarType /
      RebarHookType                                                  → 6/6

  AreaReinforcement.GetNumberOfLines()          → 0/6 (2021 CS1061, 2022+
                                                  требует AreaReinforcement-
                                                  LayerType — которого на
                                                  2021 НЕТ вовсе, CS0103)
  AreaReinforcement.GetLayerDirection(int)      → 5/6 (нет на 2021)
  BuiltInParameter.REBAR_BAR_TYPE               → 0/6  CS0117, НЕ СУЩЕСТВУЕТ

Нижние три строки — не педантизм. ВЕСЬ ПОСЛОЙНЫЙ СЛОЙ API (число линий,
направление слоя, активность слоя) на 2021 отсутствует, а на 2022+ ключуется
перечислением, которого на 2021 нет: свидетель, читающий слой, работал бы на
пяти версиях из шести — ровно «прибор на часть диапазона», который в этом
доме опаснее отсутствующего. Поэтому послойного свидетеля здесь НЕТ, и это
названо, а не умолчано. Тип стержня спрашивается не параметром (его нет), а
у самого стержня — `RebarInSystem.GetTypeId()`.

ВЗЯТА ПЕРЕГРУЗКА ПО ГРАНИЦЕ НОСИТЕЛЯ, А НЕ ПО КРИВЫМ, и это решение про
ЧЕСТНОСТЬ. Обе компилируются 6/6. Но перегрузка с `IList<Curve>` требует,
чтобы кривые ЛЕЖАЛИ В ПЛОСКОСТИ ГРАНИ НОСИТЕЛЯ, а CONTOUR — горизонтальный
плоский эскиз без отметки: его Z пришлось бы выводить в рантайме из
собственной плоскости эскиза перекрытия (уровень + FLOOR_HEIGHTABOVELEVEL),
то есть завести ЕЩЁ ОДИН незамеренный шов ради формы, которой никто не
проверял. Перегрузка по границе носителя не имеет этого шва вовсе: границу
считает Revit по самому носителю, и авторской геометрии в операции нет ни
одной величины. «Армируй эту плиту» — и есть основной случай КР.

ДОПУСКОВ У ЭТОГО ОПА НЕТ НИ ОДНОГО, И ЭТО ЗАМЕР, А НЕ ПРОПУСК. Все четыре
проверки — равенства id и счётчик, то есть топология и семантика, а не
измерение. Геометрического свидетеля здесь нет намеренно: в 38 сохранённых
разборах с переписью на диске НОЛЬ элементов OST_AreaRein, OST_PathRein,
OST_Rebar, OST_FabricAreas и OST_FabricReinforcement (замер 10.08 по
census-записям всего корпуса), то есть взять число неоткуда. Допуск,
выведенный рассуждением, — ровно `create_door.sill_mm min_val=0` (140
отрицательных отметок из 151) и `_SHEET_LIMIT_MM` (10 м на здании со
стенами в 82-110 м). Отсутствующая проверка честнее выдуманной.

ПОЧЕМУ СВИДЕТЕЛЬ «СТЕРЖНИ ПОЛОЖЕНЫ» УСЛОВНЫЙ, А НЕ БЕЗУСЛОВНЫЙ. Autodesk
пишет про `GetRebarInSystemIds` прямым текстом: «The RebarInSystem elements
are only created if ReinforcementSettings.HostStructuralRebar is set to
true. If that setting is false, this function returns an empty array».
Безусловное «непусто» отвергало бы ПРАВИЛЬНО построенное армирование в
каждом документе, где эта настройка выключена, — то есть было бы проверкой,
отвергающей исправную работу (класс «приёмка ломалась на кириллице»).
Настройка читается из документа тем же вызовом и решает, требовать или нет;
её значение и число стержней едут в квитанцию всегда, поэтому ноль стержней
не бывает молчаливым.

ПОЧЕМУ НОСИТЕЛЬ ОБЯЗАН БЫТЬ ГОРИЗОНТАЛЬНЫМ (`Floor`), И ЭТО ОТКАЗ, А НЕ
ОГРАНИЧЕНИЕ ОТ ЛЕНИ. `majorDirection` у стены обязан лежать В ПЛОСКОСТИ
СТЕНЫ — вертикальной. Плановый угол её не задаёт: у стены вдоль Y угол 0°
проецируется в НОЛЬ (Revit бросает исключение — это ещё повезло), а у стены
под 45° проецируется во что-то ненулевое и НЕ ТО, что автор имел в виду, —
то есть даёт молча неверный результат. Армирование стены требует адресации
направления в её собственной плоскости; это отдельная работа, а не поле
этого опа. Отказ типизированный (AREA_REINF_HOST_NOT_HORIZONTAL) и называет
следующий ход.

ЧТО ОТКАЗАНО ПОИМЁННО В ЭТОЙ ВОЛНЕ (каждый отказ — с причиной ЗАМЕРА):

  * `Rebar` — фабрики есть (`CreateFromCurves` 6/6 в длинной перегрузке,
    `CreateFromRebarShape` 6/6, `CreateFreeForm` 6/6), свидетель отличный
    (`GetCenterlineCurves` 6/6 читает реальную ось стержня). НЕ ВЗЯТ из-за
    аргумента `norm` — нормали к плоскости стержня: у ПРЯМОГО стержня она
    не определена ничем (перпендикуляров к отрезку бесконечно много), а
    выбрать её за автора значит назначить величину, определяющую ориентацию
    отгибов и вид стержня в разрезе. Короткая перегрузка, где эту роль
    берёт `BarTerminationsData`, существует ТОЛЬКО на 2026 (1/6, CS0246 на
    2021-2025 — замер). Оп станет законным, когда у KIR появится способ
    назвать плоскость, а не когда кто-то подберёт вектор.
  * `PathReinforcement` — `Create` 6/6, `GetHostId`/`GetCurveElementIds`/
    `GetRebarInSystemIds` 6/6. НЕ ВЗЯТ: перегрузки без кривых у него НЕ
    СУЩЕСТВУЕТ ни на одной версии, а кривые обязаны лежать в плоскости
    грани носителя — тот самый незамеренный шов Z, из-за которого здесь
    отвергнута и контурная перегрузка армирования по области. Ровно один
    живой прогон закрывает оба.
  * `FabricArea` — `Create` 6/6 обеих перегрузок, `HostId` /
    `GetFabricSheetElementIds` / `GetTotalSheetMass` 6/6. НЕ ВЗЯТ по
    ПРИОРИТЕТУ, а не по невозможности: форма один в один совпадает с взятой
    операцией (носитель + главное направление + два типа), и вторая копия
    того же скелета до первого живого прогона первой — это пять
    правдоподобных вместо одного доказанного. Строка держится до прогона.
  * `FabricSheet` — `Create(Document, Element, ElementId)` 6/6, но у вызова
    НЕТ НИ ОДНОГО аргумента положения: где именно ляжет лист, решает Revit,
    а сдвинуть его можно только `PlaceInHost(Element, Transform)` —
    аргумент рода `Transform`, которого в KIR нет вовсе (замер: XYZ туда не
    приводится, CS1503 6/6). Автор не может назвать положение, значит его
    нечем и проверить.
  * `StructuralConnectionHandler` — `Create` 6/6, `CreateGenericConnection`
    6/6, `GetConnectedElementIds` 6/6. И это ЕДИНСТВЕННЫЙ кандидат волны, у
    которого в корпусе есть живые элементы (OST_StructConnections: 3 396
    штук в одном здании, 12 разборов). НЕ ВЗЯТ, потому что свидетель
    ВЫРОЖДЕН: `GetConnectedElementIds()` возвращает ровно тот список, что
    подан в `Create`, — проверка, которая не может провалиться, а такая
    хуже отсутствующей. Всё остальное про узел (`IsCustom()`/`IsDetailed()`
    — МЕТОДЫ, а не свойства, замер CS0119 6/6) описывает тип, а не
    результат. Плюс документированный отказ «Missing detailed structural
    connection service implementation»: детальные узлы требуют надстройки
    Steel Connections, наличие которой из снапшота не читается.
  * `BoundaryConditions` (три вида) — `NewLineBoundaryConditions` и
    `NewAreaBoundaryConditions` берут `Element` 6/6, но
    `NewPointBoundaryConditions` НЕ ИМЕЕТ перегрузки с `Element` вовсе
    (CS1503 6/6): ей нужна геометрическая `Reference` на КОНЕЦ
    АНАЛИТИЧЕСКОЙ ЛИНИИ. Идиомы, дающей такую ссылку на всех шести версиях,
    НЕ СУЩЕСТВУЕТ: `AnalyticalModel` недоступен на 2023-2026 (CS0122), а
    `AnalyticalMember` отсутствует на 2021 (CS0234) и недоступен на 2022
    (CS0122) — аналитический мир раскололся на 2023, и оп пришлось бы
    писать двумя разными языками. Сверх того сам API пишет: «This method
    will only function with the Autodesk Revit Structure application» —
    предусловие, которого компилятор не проверяет ничем. В корпусе НОЛЬ
    элементов OST_BoundaryConditions.

NAMING NOTE: the discriminator param is "variety", not "kind" — this
registry reserves "kind" as a vocabulary word for ParamSpec.kind=="kind_enum"
(the closed Revit-object-kind table wall/door/floor/.../other, SPEC 12.8),
and test_invariants.py's test_schema_generates_and_is_closed asserts BY
PROPERTY NAME that any op-schema field literally called "kind" carries
spec.KIND_ESCAPE in its enum — a real, deliberate safety invariant (every
closed-kind-enum must have an escape hatch so an unrecognized category never
silently guesses) enforced by name-match rather than by ParamSpec.kind value.
A param named "kind" holding {"isolated","slab"} (no escape value — this
wave has no honest escape/other bucket for foundation variety, unlike a
Revit-object-kind table) would collide with that invariant and is a correct
FAIL, not a test bug to route around by loosening the shared test. Renamed
instead — the honest fix.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

OPS = [
    OpSpec(
            name="create_beam",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # named "symbol" (not "type"): a beam is a FamilyInstance, so
                # its type-selector resolves to a FamilySymbol via the SAME
                # shared _symbol_res()/IsActive-Activate() helper create_column/
                # create_window/create_door/place_family already use (which
                # hardcodes the param key "symbol") — "type" is reserved in
                # this registry for ElementType-based ops (wall/floor/roof)
                # with different resolution semantics (doc-default support a
                # FamilySymbol selector doesn't have). Consistent naming, not
                # an arbitrary choice.
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),        # omitted -> sole snapshot entry, else AMBIGUOUS
            ),
            capability=(("create", "element"),),
            post=("beam exists; LocationCurve endpoints == p0/p1 (±5mm, 3D) — "
                  "положение пришпилено целиком именно здесь; опорный уровень "
                  "СУЩЕСТВУЕТ (topology), но КАКОЙ — выводит Revit из отметки "
                  "кривой, а не из аргумента level: замерено 27.07, передан "
                  "L_01 @ 0 при кривой на Z=3000 -> привязка к L_01ДОО1_+2.500. "
                  "Полученный уровень читается в свидетель "
                  "(reference_level_id/reference_level), а не навязывается; "
                  "StructuralType == Beam (semantic, witness)"),
            writes_model=True,
            # 03.08: обещанные ±5 мм ЖИВУТ ЗДЕСЬ.  До этого `post` обещал
            # число, которого реестр назвать не мог, а эмиттер штамповал
            # tol_key="endpoint_mm" — ссылка в пустоту (дефект create_type
            # дословно).  Число ТО ЖЕ, что стояло литералом в struct_emit.
            tolerances={"endpoint_mm": 5.0},
            grounded=(("level", "levels", True), ("symbol", "beam_types", False)),
        ),
    OpSpec(
            name="create_foundation",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("variety", "enum", required=True,
                          choices=("isolated", "slab")),
                # isolated-only:
                ParamSpec("xy", "pt_xy"),
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),         # omitted -> sole snapshot entry
                # slab-only (mirrors create_floor's own outline/holes/type):
                ParamSpec("outline", "pts"),
                ParamSpec("holes", "pts_list"),     # 2022+ only, same as create_floor
                ParamSpec("type", "sel"),           # omitted -> doc default floor type
                # shared:
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
            ),
            capability=(("create", "element"),),
            post=("variety=isolated: footing exists; LocationPoint == xy (±5mm); "
                  "base level == resolved level (topology, BIP chain); "
                  "StructuralType == Footing (semantic, witness). "
                  "variety=slab: structural floor exists; level binding == resolved "
                  "level (topology); bbox XY extents == outline extents (±50mm); "
                  "structural flag forced true (semantic) — this IS create_floor's "
                  "structural path, reused not duplicated. "
                  "any other variety value -> typed refusal (KIR-E004), never a guess"),
            writes_model=True,
            # 03.08: обе обещанные величины — по своей разновидности.
            # `location_mm` — точка отдельно стоящего башмака (±5 мм),
            # `bbox_mm` — габарит плиты (±50 мм, тот же ключ и то же число,
            # что у create_floor: плита фундамента ЕСТЬ структурное
            # перекрытие).  Числа те же, что стояли литералами.
            tolerances={"location_mm": 5.0, "bbox_mm": 50.0},
            grounded=(("level", "levels", True),
                      ("symbol", "foundation_symbols", False),
                      ("type", "floor_types", False)),
        ),
    OpSpec(
            name="create_wall_foundation",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # Стена-носитель. `target_w` + ref_kinds=WALL: ссылка внутрь
                # программы разрешена типом параметра (иначе KIR-L004 на
                # плановой стадии — ref на не-стену отказывается ДО эмиссии),
                # а element_id остаётся законным, потому что фундамент
                # подводят и под уже стоящую стену. Имя — из API, см. шапку.
                ParamSpec("wall", "target_w", required=True,
                          ref_kinds=(ReferenceKind.WALL,)),
                # Пропущенный тип -> ТИП ДОКУМЕНТА ПО УМОЛЧАНИЮ, как у
                # create_wall/create_floor и по той же причине: спросить Revit
                # «твой тип ленточного фундамента» МОЖНО —
                # ElementTypeGroup.WallFoundationType компилируется на всех
                # шести (замер выше). У ограждения этой ветки нет по
                # построению, у потолка она есть и сознательно не взята; здесь
                # взята, потому что подмена типа не молчалива: свидетель
                # semantic сверяет ПОСТРОЕННЫЙ тип с запрошенным, а квитанция
                # везёт type_name наружу.
                ParamSpec("type", "sel"),
            ),
            capability=(("create", "element"),),
            # ОБЕЩАНО РОВНО ТО, ЧТО ПРОВЕРЯЕТСЯ, и отдельной клаузулой названо
            # то, что НЕ проверяется. Промолчать про геометрию значило бы
            # оставить читателя думать, что её кто-то сторожит.
            post=("wall foundation exists (materialized or typed refusal); "
                  "WallId == host wall id, EXACT equality with no tolerance "
                  "(topology); "
                  "GetTypeId == requested wall foundation type (semantic); "
                  "geometry deliberately NOT witnessed on purpose — the "
                  "footing's projection beyond its wall and its underside "
                  "elevation are unmeasured (zero WallFoundation instances "
                  "across every stored decompile), and a bound authored by "
                  "reasoning is this compiler's own defect class"),
            writes_model=True,
            # Ни одного допуска, и это не пропуск: обе проверки ТОЧНЫЕ
            # (равенство id), а геометрической проверки здесь нет вовсе.
            tolerances={},
            grounded=(("type", "wall_foundation_types", False),),
        ),
    OpSpec(
            name="create_beam_system",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # ПРОФИЛЬ — CONTOUR, И ЭТО ЗАМЕР, А НЕ ВКУС (см. шапку).
                # `region` даёт бесплатно всё, чем эскиз обязан быть проверен
                # ДО транзакции: адреса точек от осей, дуги по bulge/радиусу,
                # нулевые рёбра, самопересечение, вырожденная площадь. Дырки
                # у него ОТКАЗЫВАЮТСЯ эмиттером — вызов их не принимает.
                ParamSpec("profile", "region", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # НОМЕР РЕБРА-НАПРАВЛЕНИЯ, а не вектор. Перегрузка с
                # `curveIndexForDirection` выбрана над перегрузкой с XYZ
                # ровно потому, что её предусловие ПРОВЕРЯЕМО НА КОМПИЛЯЦИИ:
                # Autodesk требует, чтобы кривая направления была ПРЯМОЙ, а
                # какие рёбра опущенного контура прямые (bulge==0), известно
                # в питоне. Вектор же пришлось бы сверять со свидетелем через
                # угловой допуск, которого никто не мерил.
                # Границы 0..63 ВЫВЕДЕНЫ, а не назначены: `poly` у CONTOUR
                # держит 3..64 точки (contour.py), то есть рёбер не больше 64.
                ParamSpec("direction_edge", "int", min_val=0, max_val=63),
                # Тот же пул и то же имя, что у create_beam: балки системы —
                # обычные несущие FamilyInstance, и пул уже отфильтрован по
                # типу размещения (open_model.py). Пропущенный селектор
                # разрешается общим правилом «единственный / most_used».
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),
            ),
            capability=(("create", "element"), ("create", "geometry")),
            # ОБЕЩАНО РОВНО ТО, ЧТО ПЕРЕЧИТЫВАЕТСЯ. Отдельной клаузулой
            # названо то, что НЕ проверяется, и почему.
            post=("beam system exists (materialized or typed refusal); "
                  "re-read Profile vertex bbox == lowered-edge vertex bbox "
                  "±50mm (geometry) — arc extrema between vertices stay "
                  "outside this witness on purpose, because C# reads the "
                  "returned curves by endpoints and the system's own "
                  "BoundingBox is a solid, not a sketch; "
                  "GetBeamIds is non-empty — Revit actually laid framing "
                  "(semantic); "
                  "BeamSystem.Level == resolved level (topology, exact id "
                  "equality); "
                  "BeamType == resolved symbol (semantic) — the emitter "
                  "assigns it, so demanding it back is fair; "
                  "beam count and spacing deliberately NOT gated (LayoutRule "
                  "is Revit's, nobody authored a number), and Direction / "
                  "Elevation ride the receipt instead of a demand"),
            writes_model=True,
            # ОДИН допуск, и он НЕ НОВОЕ ЧИСЛО: тот же ключ `bbox_mm` = 50.0,
            # что у create_floor_by_contour и create_ceiling, и та же самая
            # сверка — авторский эскиз против построенного. Заводить здесь
            # своё число значило бы назначить границу рассуждением.
            tolerances={"bbox_mm": 50.0},
            grounded=(("level", "levels", True), ("symbol", "beam_types", False)),
        ),
    OpSpec(
            name="create_truss",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # ДВУМЕРНЫЕ КОНЦЫ, И ЭТО НЕ УПРОЩЕНИЕ. `Truss.Create` берёт
                # плоскость эскиза отдельным аргументом и требует, чтобы
                # базовая кривая ЛЕЖАЛА В НЕЙ; плоскость здесь — плоскость
                # самого уровня (SketchPlane.Create(doc, levelId)), значит Z
                # у концов не степень свободы, а следствие. Принять pt_xyz
                # значило бы дать автору написать Z, который эмиттер обязан
                # проигнорировать, — ровно наоборот к доводу create_beam,
                # где концы РЕАЛЬНО бывают на разных отметках.
                ParamSpec("p0_mm", "pt_xy", required=True),
                ParamSpec("p1_mm", "pt_xy", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # Имя из API (`trussTypeId`, свойство `Truss.TrussType`).
                # Типа по умолчанию у фермы НЕТ: ElementTypeGroup.TrussType
                # не компилируется ни на одной из шести версий (CS0117 6/6,
                # замер 09.08) — ровно как у ограждения, и поэтому
                # неразрешённый тип здесь типизированный отказ, а не подмена.
                ParamSpec("type", "sel"),
            ),
            capability=(("create", "element"),),
            post=("truss exists (materialized or typed refusal); "
                  "LocationCurve endpoints == p0/p1 ±5mm in plan (geometry); "
                  "both endpoint elevations == the level's own plane ±5mm "
                  "(geometry) — the sketch plane is the level's, so this is "
                  "the op's own promise and not Revit's inference; "
                  "GetTypeId == requested truss type (semantic); "
                  "Members is non-empty — Revit derived chords and webs "
                  "(semantic); "
                  "reference level link is REAL, and WHICH level rides the "
                  "receipt rather than a demand — same measured lesson as "
                  "create_beam, where forcing it rolled correct framing back; "
                  "the truss profile (chord shape, panel count, web layout) "
                  "belongs to the truss family and is deliberately ungated"),
            writes_model=True,
            # Число ТО ЖЕ и ключ ТОТ ЖЕ, что у create_beam: сверка
            # авторского отрезка с LocationCurve несущего элемента —
            # буквально то же сравнение над теми же величинами.
            tolerances={"endpoint_mm": 5.0},
            grounded=(("level", "levels", True), ("type", "truss_types", False)),
        ),
    OpSpec(
            name="create_area_reinforcement",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # НОСИТЕЛЬ. `target_w` + ref_kinds=ELEMENT: армируют и плиту,
                # построенную этой же программой (ref), и УЖЕ СТОЯЩУЮ
                # (element_id) — второе даже чаще, ровно как у create_opening
                # и create_wall_sweep. Уже класса нет: ReferenceKind знает
                # только ELEMENT/WALL/LEVEL/FAMILY_SYMBOL, а «перекрытие» из
                # них не выражается, поэтому горизонтальность носителя
                # проверяет ЭМИТТЕР в рантайме типизированным отказом, а не
                # система типов ссылок.
                ParamSpec("host", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                # ГЛАВНОЕ НАПРАВЛЕНИЕ — ОБЯЗАТЕЛЬНО, И УМОЛЧАНИЯ У НЕГО НЕТ.
                # Направление рабочей арматуры — профессиональная суть
                # операции: подставить его молча значило бы повторить дефект
                # `height_mm` (31.07), где откатывались ВЕРНО построенные
                # стены за значение, которого автор не называл. Плановый
                # угол, а не вектор: у горизонтального носителя это одна
                # величина, а вектор пришлось бы сверять со свидетелем через
                # угловой допуск, которого здесь никто не мерил.
                ParamSpec("direction_deg", "deg", required=True),
                # Пропущенный тип -> ТИП ДОКУМЕНТА ПО УМОЛЧАНИЮ:
                # ElementTypeGroup.AreaReinforcementType компилируется на всех
                # шести (замер 10.08), ровно как у ленточного фундамента. И
                # общее правило «единственный в пуле» здесь было бы ХУЖЕ
                # ВСЕГО: у настоящего проекта КР типов армирования несколько,
                # то есть опущенный `type` отказывал бы KIR-G102 всегда.
                ParamSpec("type", "sel"),
                # Тип стержня — обычный пул, как `symbol` у балки: пропуск
                # разрешается общим правилом «единственный / most_used», и
                # выбор компилятора уезжает в квитанцию.
                ParamSpec("bar_type", "sel"),
                # ПРОПУЩЕННЫЙ КРЮК ЗНАЧИТ «БЕЗ КРЮКОВ», и это НЕ наша
                # выдумка: `InvalidElementId` в этом аргументе — документиро-
                # ванное значение самого API («If this parameter is
                # InvalidElementId, it means to create a rebar with no
                # hooks»). Общее правило «единственный в пуле» подставило бы
                # сюда крюк, которого автор не просил, а в проекте с
                # несколькими типами крюков просто отказало бы KIR-G102 —
                # потеряв армирование ни за что (тот же довод, что у
                # create_topography.level).
                ParamSpec("hook_type", "sel"),
            ),
            capability=(("create", "element"),),
            # ОБЕЩАНО РОВНО ТО, ЧТО ПЕРЕЧИТЫВАЕТСЯ ИЗ ДОКУМЕНТА, и отдельными
            # клаузулами названо то, что НЕ проверяется, и почему.
            post=("area reinforcement exists (materialized or typed refusal); "
                  "GetHostId == requested host id, EXACT equality with no "
                  "tolerance (topology); "
                  "GetTypeId == requested area reinforcement type (semantic); "
                  "when the document's ReinforcementSettings."
                  "HostStructuralRebar is true, GetRebarInSystemIds is "
                  "non-empty — Revit actually laid bars (semantic); zero is a "
                  "real outcome and is a VIOLATION only under that setting, "
                  "because Autodesk documents an empty array as correct when "
                  "it is false; "
                  "the bars' own GetTypeId == requested bar type (semantic) — "
                  "the emitter passes it, so demanding it back is fair; "
                  "major direction, bar count and the HostStructuralRebar "
                  "setting itself ride the receipt rather than a demand — "
                  "Revit normalises and projects the direction into the host "
                  "plane and there is no measured angular comparison rule; "
                  "geometry deliberately NOT witnessed on purpose — the "
                  "boundary is computed by Revit from the host, no dimension "
                  "is authored, and no stored decompile contains a single "
                  "reinforcement element to derive a bound from"),
            writes_model=True,
            # ПУСТО, И ЭТО СОДЕРЖАТЕЛЬНО: все проверки этого опа — равенства
            # id и счётчик. Числа здесь нет, потому что нечего измерять; и
            # завести его «из практики» значило бы сделать ровно тот дефект,
            # против которого писан весь этот пакет.
            tolerances={},
            grounded=(("type", "area_reinforcement_types", False),
                      ("bar_type", "rebar_bar_types", False),
                      ("hook_type", "rebar_hook_types", False)),
        ),
]
