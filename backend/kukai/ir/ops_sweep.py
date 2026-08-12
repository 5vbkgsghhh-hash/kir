"""ops_sweep — навесные профили: сweep/reveal на стене и капельник по краю
плиты (wave/sweep, 2026-08-09).

Registry module — Add ops HERE, not in spec.py. Парный файл эмиссии —
`sweep_emit.py`, ровно как `ops_site.py` ↔ `site_emit.py`.

ДО ЭТОЙ ВОЛНЫ СЕМЕЙСТВО НАВЕСНЫХ ПРОФИЛЕЙ НЕ БЫЛО ОСМОТРЕНО НИ РАЗУ: перепись
реестра не находила ни одной операции, создающей `WallSweep`, `SlabEdge`,
`Fascia` или `Gutter`. Это целый класс фасадной и кровельной отделки —
карнизы, пояски, ниши-рустовки, капельники по краю плиты, — который
выражался НИЧЕМ.

ЗАМЕР API (живой компайл-сервис :52412, шесть эталонных сборок 2021-2026,
09.08.2026). Ни одна строка ниже не написана по памяти и ни одна не взята из
`backend/data/revit_api_db.json` (эта база доказанно неполна — 30 из 93 членов
`ElementTypeGroup`, и `NewSlabEdge` она не знает вовсе). Каждая проверена
присваиванием в ОБЪЯВЛЕННЫЙ тип: `var __x = ...` компилируется при ЛЮБОМ типе
справа и не доказывает ничего — урок волны ограждений.

    WallSweep.Create(Wall, ElementId, WallSweepInfo)          6/6  (since 2012)
    WallSweep.WallAllowsWallSweep(Wall)                       6/6
    WallSweep.GetHostIds() -> ICollection<ElementId>          6/6
    WallSweep.GetWallSweepInfo() -> WallSweepInfo             6/6
    WallSweep.GetTypeId() / .Id / (Element)                   6/6
    WallSweepInfo..ctor(WallSweepType, bool vertical)         6/6
    WallSweepInfo.IsVertical (ЧТЕНИЕ)                         6/6
    WallSweepInfo.IsVertical (ЗАПИСЬ)          НЕТ НИ НА ОДНОЙ (CS0200)
    WallSweepInfo.Id — это `int`, а НЕ ElementId              6/6 (CS0029)
    WallSweepInfo.DistanceMeasuredFrom : DistanceMeasuredFrom 6/6
    WallSweep -> HostedSweep (приведение)      НЕТ НИ НА ОДНОЙ (CS0030)
    ElementTypeGroup.RevealType / .EdgeSlabType               6/6
    BuiltInCategory.OST_Cornices / OST_Reveals                6/6
    doc.Create.NewSlabEdge(SlabEdgeType, Reference)           6/6
    doc.Create.NewSlabEdge(SlabEdgeType, ReferenceArray)      6/6
    doc.Create.NewFascia / NewGutter (обе перегрузки)         6/6
    SlabEdge.SlabEdgeType -> SlabEdgeType                     6/6
    SlabEdge.GetTypeId()                                      6/6
    SlabEdge -> HostedSweep: Length/Angle/HorizontalOffset/
                VerticalOffset/get_ReferenceCurve(Reference)  6/6
    HostObjectUtils.GetTopFaces / GetBottomFaces              6/6
    Face.EdgeLoops -> EdgeArrayArray; Edge.Reference          6/6
    Category.GetCategory(Document, BuiltInCategory)           6/6

ПЯТЬ ФАКТОВ, КОТОРЫЕ ПЕРЕВЕРНУЛИ БЫ ЭТИ ОПЫ, ЕСЛИ БЫ ИХ НЕ ЗАМЕРИЛИ:

1. НАЗВАННАЯ БОЛЕЕ СЛАБАЯ ГАРАНТИЯ У СТЕННОГО ПРОФИЛЯ. `RevitAPI.xml` всех
   ШЕСТИ версий несёт у `WallSweep.Create` дословную ремарку:

       "The wall sweep's profile and type are taken from the wall sweep type
       properties.  The values set in the WallSweepInfo are ignored."

   Это не оговорка на полях, а главный факт операции: положение профиля
   задаётся ТИПОМ, заранее загруженным в документ, а не вызовом. Значит
   параметра «на какой высоте» у этой операции НЕТ И НЕ МОЖЕТ БЫТЬ: завести
   `distance_mm`, который API документированно игнорирует, — это построить
   ровно тот тихо-неверный исход, ради запрета которого весь дом и написан
   (автор просит поясок на 900, получает на отметке типа, и снаружи это
   неотличимо от успеха). Поэтому честный свидетель — СУЩЕСТВОВАНИЕ, ХОЗЯИН и
   ТИП, и это записано в `post` дословно, а не пересказом.
2. `WallSweepInfo.IsVertical` — СВОЙСТВО ТОЛЬКО ДЛЯ ЧТЕНИЯ (CS0200 на всех
   шести). Единственный канал ориентации — аргумент КОНСТРУКТОРА, и он
   обязателен. Поэтому `orientation` у операции есть, он БЕЗ УМОЛЧАНИЯ, и он
   ЕДИНСТВЕННОЕ поле `WallSweepInfo`, которое операция вообще предъявляет:
   подставить его за автора значило бы завести «умолчание, которого никто не
   произносил» — тот самый класс дефекта, что `height_mm=3000` у стены.
   Свидетель на него ставится (`GetWallSweepInfo().IsVertical`), и это
   СОЗНАТЕЛЬНО НАДЁЖНЕЕ, чем промолчать: если живой Revit ремарку выше
   распространяет и на конструктор, программа получит типизированный
   неуспех — а не молча построенный горизонтальный поясок вместо руста.
3. `WallSweepInfo.Id` — это `int`, а не `ElementId` (CS0029 на всех шести), и
   документация требует `-1` для нефиксированного профиля («The WallSweepInfo
   id must be set to -1 for a non-fixed wall sweep» — условие
   ArgumentException). Эмиттер выставляет его явно; надеяться на умолчание
   конструктора значило бы отдать целый класс ArgumentException в рантайм.
4. `WallSweep` — НЕ `HostedSweep` (CS0030 на всех шести), хотя `SlabEdge`,
   `Fascia` и `Gutter` — да. То есть `Length`/`Angle`/`HorizontalOffset` у
   стенного профиля НЕ СУЩЕСТВУЮТ, а у краевого есть. Два элемента, которые
   в интерфейсе Revit выглядят роднёй, в API стоят в разных иерархиях, и
   свидетели у них поэтому РАЗНОЙ СИЛЫ — см. `post` каждого.
5. У КРАЕВОГО ПРОФИЛЯ ЧТЕНИЕ ЕСТЬ, И ЭТО ГЛАВНЫЙ ЗАМЕР ЭТОЙ ВОЛНЫ. Задание
   волны несло вопрос «есть ли у `SlabEdge` хоть один геттер сверх базового
   `Element` и `AddSegment(Reference)`; прежний осмотр не нашёл ни одного».
   ОТВЕТ: НАШЛОСЬ ЧЕТЫРЕ РОДА, все 6/6 — собственное свойство
   `SlabEdge.SlabEdgeType`, базовый `GetTypeId()`, и через базовый класс
   `HostedSweep` — `Length`/`Angle`/`HorizontalOffset`/`VerticalOffset` и
   индексируемое `get_ReferenceCurve(Reference)`. Последнее и есть настоящий
   свидетель: у ПОСТРОЕННОГО профиля спрашивается кривая, которую он
   проложил по КАЖДОЙ названной нами ссылке, и `null` означает, что Revit
   эту ссылку не взял. Прежний вывод «читать нечем» был бы отказом от
   операции, у которой свидетель есть.

ПОЧЕМУ У КРАЕВОГО ПРОФИЛЯ НЕТ ПАРАМЕТРА «КАКОЕ РЕБРО» — И ЭТО НЕ УПРОЩЕНИЕ.
`NewSlabEdge` принимает геометрическую ССЫЛКУ на ребро, а замороженный диалект
ссылок KIR адресует ЭЛЕМЕНТЫ; вторая ступень селектора, которая появилась
09.08 (`faceref.py`, `{"by": "face", ...}`), называет ГРАНЬ, но не РЕБРО.
Заводить здесь третий род второй ступени значило бы написать второй механизм
рядом с существующим — прямо запрещено заданием волны.

Поэтому операция берёт не «ребро», а ВЕСЬ ПЕРИМЕТР НАЗВАННОЙ ГРАНИ, и обе
ступени решаются МОЩНОСТЬЮ, а не порядком перебора — тот же закон, что в
`faceref.py` («описание фильтрует, решает мощность»):

    сторона (`side`) -> HostObjectUtils.GetTopFaces/GetBottomFaces
        ровно 1 грань   -> берём
        0 граней        -> типизированный отказ
        >= 2 граней     -> типизированный отказ, С ЧИСЛОМ
    контуры этой грани -> Face.EdgeLoops
        ровно 1 контур  -> берём ВСЕ его рёбра
        иначе           -> типизированный отказ, С ЧИСЛОМ контуров
                           (плита с отверстием честно отказывает: какое из
                           колец обводить — решает автор, а не мы)

Ни в одной точке нет «первого подходящего», поэтому недокументированный
порядок граней и рёбер на результат НЕ ВЛИЯЕТ ВООБЩЕ. Это и весь приём.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО:

* `NewFascia` и `NewGutter` (обе 6/6, подпись та же, результат — тот же
  `HostedSweep`) НЕ ПОДКЛЮЧЕНЫ. Причина ровно одна и она не в лени: каждая
  берёт СВОЙ класс типа (`Architecture.FasciaType`, `Architecture.GutterType`),
  а `grounded` в реестре — статическая тройка (параметр, пул, обязательность),
  то есть один параметр `type` не может заземляться в три разных пула по
  значению соседнего поля. Честных выхода два — три отдельных пула с тремя
  операциями либо один слитый пул с проверкой категории в рантайме, — и оба
  это отдельная работа с отдельными эталонами, а не «ещё одно значение
  перечисления». Подсунуть же `FasciaType` в `NewSlabEdge` нельзя: подпись
  требует именно `SlabEdgeType` (та же причина, по которой у ленточного
  фундамента заведён свой `wall_foundation_types`, а не переиспользован
  `foundation_symbols`);
* перегрузка `NewSlabEdge(type, Reference)` — одиночное ребро — не
  подключена: единственный вход этой операции — периметр, и одно ребро без
  второй ступени селектора назвать нечем (см. выше);
* `HostedSweep.HorizontalOffset` / `VerticalOffset` / `Angle` НЕ предъявлены
  как параметры, хотя читаются 6/6. Это СЕТТЕРЫ на уже созданном элементе,
  то есть работа для `set_param`, а не второй способ создать тот же элемент.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/...)

#: Ориентация стенного профиля. Закрытое перечисление БЕЗ умолчания: канал
#: ровно один (аргумент конструктора `WallSweepInfo`, запись в свойство
#: невозможна — CS0200 на всех шести), и подставить его за автора значило бы
#: построить поясок там, где просили руст, и промолчать.
SWEEP_ORIENTATIONS = ("horizontal", "vertical")

#: Сторона носителя, по периметру которой ставится краевой профиль. Имена НЕ
#: наши: их даёт сам Revit в `HostObjectUtils` — поэтому у них нет и не может
#: быть допуска. Подмножество `faceref.SIDES` (там ещё exterior/interior,
#: которых у горизонтального носителя не бывает).
SLAB_EDGE_SIDES = ("top", "bottom")

#: Значение `WallSweepInfo.Id`, которого требует документация для
#: НЕфиксированного профиля: «The WallSweepInfo id must be set to -1 for a
#: non-fixed wall sweep» (условие ArgumentException, все шесть XML). Живёт
#: здесь, а не литералом в эмиттере, по той же причине, что
#: `TOPOSOLID_MIN_VERSION` у волны площадки: это число читает и тест, и
#: эмиттер.
WALL_SWEEP_NON_FIXED_ID = -1

OPS = [
    OpSpec(
        name="create_wall_sweep",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            # НОСИТЕЛЬ — СУЩЕСТВУЮЩАЯ СТЕНА, и `target_w` здесь по той же
            # причине, что у проёма: карниз вешают на то, что УЖЕ СТОИТ
            # («сделай поясок по этой стене»), а стена, построенная этой же
            # программой, — частный случай. `ref_kinds` широкие намеренно:
            # реальный класс проверяется в рантайме (`as Wall`)
            # типизированным отказом, а не догадкой на разборе.
            ParamSpec("host", "target_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT, ReferenceKind.WALL)),
            # ОРИЕНТАЦИЯ БЕЗ УМОЛЧАНИЯ — см. факт 2 в шапке модуля.
            ParamSpec("orientation", "enum", required=True,
                      choices=SWEEP_ORIENTATIONS),
            # Тип профиля. Пул ОДИН на карнизы и русты (OST_Cornices +
            # OST_Reveals), потому что класса `WallSweepType`-как-ElementType
            # в API не существует вовсе: `WallSweepType` — это ПЕРЕЧИСЛЕНИЕ
            # {Sweep, Reveal}, а сам тип живёт обычным `ElementType` в одной
            # из двух категорий (замерено). Какое из двух значений
            # перечисления передать, эмиттер ВЫВОДИТ из категории
            # разрешённого типа, а не спрашивает у автора: спросить значило
            # бы завести поле, которое может ПРОТИВОРЕЧИТЬ типу, и по
            # ремарке из факта 1 победил бы тип — то есть ответ автору был бы
            # молча другим.
            ParamSpec("type", "sel"),
        ),
        # ТЕЛО ЕСТЬ, НО КООРДИНАТЫ У ОПЕРАЦИИ НЕТ: клетка ("create",
        # "geometry") здесь была бы переобещанием ровно на ту величину,
        # которую описывает названная более слабая гарантия. Та же позиция,
        # что у create_railing (только ("create", "element")).
        capability=(("create", "element"),),
        post=("wall sweep exists on 2021-2026 (WallSweep.Create, since 2012); "
              "a wall that may not host a sweep is a typed refusal from "
              "WallAllowsWallSweep BEFORE the call, never a raw "
              "ArgumentException; "
              "GetHostIds() re-read contains the requested wall (topology); "
              "GetTypeId() re-read == resolved wall sweep type (topology); "
              "GetWallSweepInfo().IsVertical == requested orientation "
              "(semantic); "
              "NAMED WEAKER GUARANTEE, documented by Autodesk in all six "
              "RevitAPI.xml: \"The wall sweep's profile and type are taken "
              "from the wall sweep type properties. The values set in the "
              "WallSweepInfo are ignored.\" — the placement distance, the "
              "wall offset and the profile therefore come ENTIRELY from the "
              "pre-loaded type, this op exposes no field for any of them, "
              "and none of them is witnessed or witnessable here"),
        writes_model=True,
        grounded=(("type", "wall_sweep_types", False),),
        # НИ ОДНОГО ДОПУСКА, И ЭТО СЛЕДСТВИЕ, А НЕ ПРОБЕЛ. Все три свидетеля
        # — точные: принадлежность id множеству, равенство id, равенство
        # булева значения. Числа, которое можно было бы сравнивать с
        # допуском, у этой операции нет вовсе — ровно потому, что положение
        # профиля задаёт тип (факт 1). Завести здесь допуск было бы
        # невозможно честно: мерить нечего.
        tolerances={},
    ),
    OpSpec(
        name="create_slab_edge",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            # НОСИТЕЛЬ — СУЩЕСТВУЮЩАЯ ПЛИТА ИЛИ КРОВЛЯ. `ref_kinds` — только
            # ELEMENT: `Floor` и `RoofBase` оба `HostObject` (замерено 6/6),
            # но отдельного ReferenceKind у них нет, а сужать до WALL было бы
            # прямо неверно.
            ParamSpec("host", "target_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            # СТОРОНА БЕЗ УМОЛЧАНИЯ. Капельник по верхнему краю и по нижнему —
            # это разные элементы в разных местах, и «обычно верхний» есть
            # догадка о чужом проекте.
            ParamSpec("side", "enum", required=True, choices=SLAB_EDGE_SIDES),
            ParamSpec("type", "sel"),
        ),
        # ЗДЕСЬ КЛЕТКА ГЕОМЕТРИИ ЗАСЛУЖЕНА, в отличие от стенного профиля:
        # положение краевого профиля задаём МЫ (набором рёбер), и оно
        # перечитывается с построенного элемента (`get_ReferenceCurve`).
        capability=(("create", "element"), ("create", "geometry")),
        post=("slab edge exists on 2021-2026 "
              "(Autodesk.Revit.Creation.Document.NewSlabEdge, which returns "
              "null rather than throwing on failure — the null is a typed "
              "refusal here); "
              "the named side resolves to exactly ONE face and that face to "
              "exactly ONE edge loop, and any other cardinality is a typed "
              "refusal NAMING THE COUNT — never a first match, so the "
              "undocumented order of faces and edges cannot affect the "
              "result; "
              "every perimeter edge handed to the call is bound in the BUILT "
              "sweep: get_ReferenceCurve(edge) is non-null for each of them "
              "(geometry); "
              "GetTypeId() re-read == resolved slab edge type (topology)"),
        writes_model=True,
        grounded=(("type", "slab_edge_types", False),),
        # ДОПУСКОВ НЕТ, И СНОВА ПО ДЕЛУ. Свидетель ребра — БУЛЕВ (ссылка
        # связана или нет), а не метрический. `HostedSweep.Length` читается
        # 6/6 и было бы соблазнительно сверить его с суммой длин рёбер — но
        # на стыках Revit подрезает профиль в ус, и НАСКОЛЬКО именно, никто
        # не мерил. Сверять их с выдуманным допуском значило бы обвинять
        # правильно построенный капельник; поэтому длина едет в КВИТАНЦИЮ
        # как наблюдение, а не в вердикт — тот же приём, что
        # `slab_shape_vertices: -1` у толщи рельефа.
        tolerances={},
    ),
]
