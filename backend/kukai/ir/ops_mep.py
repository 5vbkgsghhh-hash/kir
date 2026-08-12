"""ops_mep — MEP single-element ops (duct/cable-tray/conduit/flex/placeholder);
systems live in ops_connect.

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

────────────────────────────────────────────────────────────────────────────
ВОЛНА ЭОМ/ГИБКИХ/ЗАГОТОВОК (09.08.2026) — ЧТО ИЗМЕРЕНО, А ЧТО ОТВЕРГНУТО
────────────────────────────────────────────────────────────────────────────

До этой волны вся электрика ниже лотка и вся «мягкая» инженерия были СЛЕПЫ:
ни опа, ни отказа, ни упоминания. `registry_base.KINDS` при этом уже знал
категории `OST_Conduit`, `OST_FlexDuctCurves`, `OST_FlexPipeCurves` — то есть
спросить «сколько их» было можно, а построить хоть одну нельзя. Пять новых
операций закрывают ровно этот разрыв.

Все пять — потомки `MEPCurve : HostObject`, поэтому свидетель у них тот же,
что у отгруженного `create_pipe`: НЕЗАВИСИМОЕ ПЕРЕЧИТЫВАНИЕ результата
(геометрия + привязка к уровню + тип), а не подтверждение того, что вызов
состоялся.

ПОДПИСИ API СНЯТЫ С ЭТАЛОННЫХ СБОРОК, А НЕ ПО ПАМЯТИ. Каждая форма вызова
скомпилирована живым Roslyn (localhost:52412) против настоящих
`RevitAPI.dll` 2021-2026 ДО написания эмиттера (`data/revit_api_db.json`
доказанно неполон и здесь не спрашивался):

  Electrical.Conduit.Create(Document, ElementId conduitType, XYZ start,
                            XYZ end, ElementId levelId)          6/6
  Plumbing.Pipe.CreatePlaceholder(Document, ElementId systemTypeId,
                            ElementId pipeTypeId, ElementId levelId,
                            XYZ start, XYZ end)                  6/6
  Mechanical.Duct.CreatePlaceholder(… то же …)                   6/6
  Mechanical.FlexDuct.Create(Document, ElementId systemTypeId,
                            ElementId ductTypeId, ElementId levelId,
                            IList<XYZ> points)                   6/6
  Plumbing.FlexPipe.Create(… то же …)                            6/6
  Pipe.IsPlaceholder / Duct.IsPlaceholder (bool)                 6/6
  FlexDuct.Points / FlexPipe.Points (IList<XYZ>)                 6/6
  Electrical.ConduitType / Mechanical.FlexDuctType /
  Plumbing.FlexPipeType (классы для пулов)                       6/6

ПОРЯДОК АРГУМЕНТОВ У КОРОБА ДРУГОЙ, и это не мелочь: у `Conduit.Create`
уровень стоит ПОСЛЕДНИМ (как у `CableTray.Create`), а у `Pipe`/`Duct`/
`FlexDuct`/`FlexPipe` — ТРЕТЬИМ/ЧЕТВЁРТЫМ, до точек. Перепутать их — это
`CS1503` на воротах, а не тихая ошибка, но зафиксировать порядок здесь
дешевле, чем узнавать его заново.

────────────────────────────────────────────────────────────────────────────
ОТВЕРГНУТО: `create_wire` (Electrical.Wire.Create) — ОСОЗНАННО, НЕ ЗАБЫТО
────────────────────────────────────────────────────────────────────────────

Подпись существует на всех шести версиях и КОМПИЛИРУЕТСЯ вместе с обоими
`null`-коннекторами (проверено тем же прибором):

  Wire.Create(Document, ElementId wireTypeId, ElementId viewId,
              WiringType, IList<XYZ> vertexPoints,
              Connector startConnectorTo, Connector endConnectorTo)

То есть провод БЕЗ подключений построить можно, и его вершины даже читаются
обратно (`NumberOfVertices` + `GetVertex(i)`, 6/6). Операции всё равно нет, и
причин три — каждая проверяемая:

1. КОННЕКТОР НЕ АДРЕСУЕМ ЭТИМ ЯЗЫКОМ. `Autodesk.Revit.DB.Connector` — не
   `Element`: у него нет `ElementId`, он живёт только внутри
   `ConnectorManager` своего владельца и не переживает транзакцию. Замороженный
   диалект ссылок KIR — `{"by": "name"|"element_id"|"ref", "value": …}` —
   умеет называть ЭЛЕМЕНТЫ. Назвать «третий электрический коннектор вон того
   щита» нечем ВООБЩЕ, а не «пока неудобно».

2. ПРОВОД БЕЗ ЦЕПИ — РОВНО ТОТ ТИХО-НЕВЕРНЫЙ ИСХОД, РАДИ КОТОРОГО ЭТОТ
   КОМПИЛЯТОР СУЩЕСТВУЕТ. С обоими `null` элемент строится, свидетель
   вершин зелёный, на плане видна разводка — а `Wire.GetMEPSystems()` пуст,
   и в спецификации кабеля не появится ни метра. Снаружи это неотличимо от
   выполненного раздела ЭОМ. Свидетель, который подписывает геометрию там,
   где отсутствует ВСЯ профессиональная суть операции, — это витрина, а не
   доказательство.

3. У ВЕРШИН НЕТ ТРЕТЬЕЙ КООРДИНАТЫ. Autodesk пишет прямо: «Vertices are
   projected to the view plane for comparison», а `AreVertexPointsValid`
   сравнивает только X и Y. Значит трёхмерный путь провода невыразим по
   построению, и `viewId` (только план или план потолка) — не оформление, а
   часть смысла.

Что нужно, чтобы отказ снять: адресуемый коннектор (расширение CONNECT —
«коннектор k элемента, созданного опом X», плюс тот же язык для
существующего оборудования) и живой замер того, что читается обратно у
ПОДКЛЮЧЁННОГО провода. Решение закреплено тестом
(`tests/test_mep_electrical.py::WireIsDeliberatelyAbsent`), чтобы следующая
сессия не отгрузила вакуумную версию молча.

────────────────────────────────────────────────────────────────────────────
ЧТО НЕ ВОШЛО В `create_conduit`: `diameter_mm`
────────────────────────────────────────────────────────────────────────────

`RBS_CONDUIT_DIAMETER_PARAM` существует на всех шести версиях, и написать
`Set(U(x))` + свидетеля было бы механически тем же, что у `create_duct`. Не
сделано СОЗНАТЕЛЬНО: номинальный диаметр короба — это ТОРГОВЫЙ РАЗМЕР
(`RBS_CONDUIT_TRADESIZE`), перечисление из таблицы типа, а не длина из
континуума. Значение вне таблицы Revit подтягивает к ближайшему из неё,
и свидетель честно упал бы на КОРРЕКТНО построенном коробе — та же цена,
которую уже заплатил `create_duct` на прямоугольном сечении (замер 30.07),
только здесь она была бы не исключением, а нормой. Таблицы размеров в
снимке нет, значит отказать НА КОМПИЛЯЦИИ тоже нечем. Закон допусков
говорит: не выводится — не проверяй и скажи об этом. Сказано.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

#: Допуск конца отрезка у КАЖДОГО линейного MEP-опа — 5 мм. Число НЕ НОВОЕ:
#: это ровно зарегистрированный `create_pipe.endpoint_mm` == `create_duct` ==
#: `create_cable_tray`, и совпадение здесь содержательное, а не косметическое.
#: Все они читают ОДНО И ТО ЖЕ — `MEPCurve.Location as LocationCurve`, то есть
#: ось, которую Revit возвращает сам, — и ни у одного из них нет собственной
#: причины расходиться. Заводить шестое число значило бы утверждать, что у
#: короба ось читается иначе, чем у трубы; такого замера нет.
_MEP_ENDPOINT_MM = 5.0

OPS = [
    OpSpec(
            name="create_duct",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),   # omitted -> sole snapshot entry, else AMBIGUOUS
                ParamSpec("duct_type", "sel"),     # same rule
                ParamSpec("diameter_mm", "mm", min_val=50, max_val=3_000),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("duct exists; LocationCurve endpoints == p0/p1 (±5mm, 3D); "
                  "reference level == resolved level (topology); "
                  "diameter param == diameter_mm (±0.5mm) when given"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "duct_system_types", False),
                      ("duct_type", "duct_types", False)),
            tolerances={"endpoint_mm": 5.0, "diameter_mm": 0.5},
        ),
    OpSpec(
            name="create_cable_tray",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("tray_type", "sel"),     # omitted -> sole snapshot entry, else AMBIGUOUS
                # CableTrayType has no width/height API and CableTray.Create
                # has no sized overload (verified for Revit 2021-2026).  The
                # dimensions therefore belong to the instance operation.
                ParamSpec("width_mm", "mm", min_val=1),
                ParamSpec("height_mm", "mm", min_val=1),
            ),
            capability=(("create", "element"),),
            post=("cable tray exists; LocationCurve endpoints == p0/p1 (±5mm, 3D); "
                  "reference level == resolved level (topology); "
                  "width param == width_mm (±0.5mm) when given; "
                  "height param == height_mm (±0.5mm) when given"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("tray_type", "cable_tray_types", False)),
            tolerances={"endpoint_mm": 5.0, "section_mm": 0.5},
        ),
    # ── ЭОМ: короб электропроводки ─────────────────────────────────────────
    # Ближайший родственник лотка: тот же порядок аргументов (точки, потом
    # уровень) и тот же свидетель. Отличие ровно одно и оно в пользу
    # строгости — у короба сверяется ещё и ТИП: `Conduit.Create` принимает
    # `InvalidElementId` и в этом случае молча берёт тип документа по
    # умолчанию (документировано Autodesk дословно). ground.py такого id
    # никогда не отдаёт, но предъявить прочитанный обратно тип дешевле, чем
    # верить, что не отдаст.
    OpSpec(
            name="create_conduit",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("conduit_type", "sel"),  # omitted -> sole entry, else AMBIGUOUS
            ),
            capability=(("create", "element"),),
            post=("conduit exists; LocationCurve endpoints == p0/p1 (±5mm, 3D); "
                  "reference level == resolved level (topology); "
                  "conduit_type of the built element == resolved conduit_type "
                  "(semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("conduit_type", "conduit_types", False)),
            tolerances={"endpoint_mm": _MEP_ENDPOINT_MM},
        ),
    # ── Заготовки (placeholder) ────────────────────────────────────────────
    # Ранняя стадия: трасса и система названы, фитингов и сечения ещё нет.
    # Дешёвая и полезная операция, но её собственное содержание — ровно один
    # бит `IsPlaceholder`, и без него это была бы обычная труба под другим
    # именем. Поэтому бит ЧИТАЕТСЯ ОБРАТНО и подписан `(semantic)`.
    OpSpec(
            name="create_pipe_placeholder",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("pipe_type", "sel"),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("placeholder pipe exists; LocationCurve endpoints == p0/p1 "
                  "(±5mm, 3D); reference level == resolved level (topology); "
                  "IsPlaceholder of the built element (semantic); "
                  "pipe_type of the built element == resolved pipe_type "
                  "(semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "piping_system_types", False),
                      ("pipe_type", "pipe_types", False)),
            tolerances={"endpoint_mm": _MEP_ENDPOINT_MM},
        ),
    OpSpec(
            name="create_duct_placeholder",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("duct_type", "sel"),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("placeholder duct exists; LocationCurve endpoints == p0/p1 "
                  "(±5mm, 3D); reference level == resolved level (topology); "
                  "IsPlaceholder of the built element (semantic); "
                  "duct_type of the built element == resolved duct_type "
                  "(semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "duct_system_types", False),
                      ("duct_type", "duct_types", False)),
            tolerances={"endpoint_mm": _MEP_ENDPOINT_MM},
        ),
    # ── Гибкие участки ─────────────────────────────────────────────────────
    # У гибкого воздуховода/трубы НЕТ пары концов: у него есть ПУТЬ. Отсюда
    # свой род параметра `path3` — открытая ТРЁХМЕРНАЯ ломаная 2..64 точек.
    # Плоский `path` (у ограждения) взять было нельзя: он двумерный, а гибкая
    # подводка почти всегда идёт с этажа на подшивной потолок, то есть её
    # смысл — как раз в Z. Молча дописать нулевую высоту значило бы построить
    # НЕ ТУ трассу; это ровно тот класс, из-за которого create_beam потребовал
    # `pt_xyz`.
    #
    # СВИДЕТЕЛЬ ЗДЕСЬ СИЛЬНЕЕ, ЧЕМ У ЖЁСТКИХ ОПОВ, и это не украшение: Revit
    # отдаёт весь путь обратно (`FlexDuct.Points`/`FlexPipe.Points` — «points
    # of the flex duct, including the end points»), поэтому сверяются ВСЕ
    # точки и их ЧИСЛО, а не только концы. Проверка концов пропустила бы
    # выброшенную середину, то есть другую трассу при зелёном вердикте.
    # `Location as LocationCurve` у гибкого элемента намеренно НЕ читается:
    # там сплайн Эрмита, и его концы — производная величина, а `Points` —
    # первичная.
    OpSpec(
            name="create_flex_duct",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("path", "path3", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("flex_duct_type", "sel"),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("flex duct exists; Points read back == path, same count and "
                  "same order (±5mm, 3D, geometry); reference level == "
                  "resolved level (topology); flex_duct_type of the built "
                  "element == resolved flex_duct_type (semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "duct_system_types", False),
                      ("flex_duct_type", "flex_duct_types", False)),
            tolerances={"point_mm": _MEP_ENDPOINT_MM},
        ),
    OpSpec(
            name="create_flex_pipe",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("path", "path3", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("flex_pipe_type", "sel"),
            ),
            capability=(("create", "mep_system"), ("create", "element")),
            post=("flex pipe exists; Points read back == path, same count and "
                  "same order (±5mm, 3D, geometry); reference level == "
                  "resolved level (topology); flex_pipe_type of the built "
                  "element == resolved flex_pipe_type (semantic)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "piping_system_types", False),
                      ("flex_pipe_type", "flex_pipe_types", False)),
            tolerances={"point_mm": _MEP_ENDPOINT_MM},
        ),
]
