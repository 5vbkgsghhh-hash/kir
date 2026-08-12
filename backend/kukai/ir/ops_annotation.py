"""ops_annotation — annotation tirage; holds the whole family (KIR_DOC_SPEC.md).

create_dimension / create_tag / create_text: the ops_annotation.md family
0% -> tirage. VIEW-SPACE core (PtView2D vs PtModel3D, VIEW-BINDING LAW) lives
in docspace.py and is REUSED here, never reinvented (per KIR_DOC_SPEC.md
"эмиттер клонирует ядро, не координатную модель заново").

in_view / target / refs[] are write-target selectors (kind="target_w": pinned
element_id OR an intra-program `ref` to an earlier create_* op) — there is no
`views`/`sheets` snapshot pool yet (KIR_DOC_SPEC.md GROUND §: "добавить в
serving _SNAPSHOT_CS — сейчас есть view/sheet KINDS в query, пул для ground
нужен" — that pool is a Fable-level registry_base.py change, NOT made here).
Resolution is therefore id-pinned/ref only, exactly like `target` in
set_param/delete and `host` in create_window/create_door — no new snapshot
pool, no grounded=(...) entry needed for this v1 tirage.

FLAGGED GAP (not invented around): dim_type/tag_type/text_type are spec'd as
"каталог проекта на ground (sole-entry/candidates)" — that needs a
dimension_types/tag_types/text_note_types snapshot pool, which does not exist
in known_pools (registry_base.py, Fable-level). These three params are
therefore ALSO plain target_w (element_id-pinned only, optional) here, NOT
sole-entry-resolved; when omitted the emitter falls back to the document's
default type (GetDefaultElementTypeId, same in-emit-default pattern as
create_wall's `type`). This is a real, flagged gap versus the spec's GROUND
ambition, not a silent guess — see KIR_ANNOTATION_GAPS note in this module's
tests for the follow-up.

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

──────────────────────────────────────────────────────────────────────────────
ЧТО ЭТОЙ ВОЛНОЙ (09.08.2026) НЕ СДЕЛАНО, И ПОЧЕМУ — ЗАМЕРОМ, А НЕ ВКУСОМ
──────────────────────────────────────────────────────────────────────────────
Записано здесь, а не в отчёте, потому что отчёт следующая волна не читает, а
этот файл — читает. Каждая строка проверена компиляцией на :52412 против шести
ЭТАЛОННЫХ СБОРОК (2021-2026), а не по документации: см. ниже случай, где XML
описывает член, которого нет ни в одной DLL.

1. МАРКА ВЫСОТНОЙ ОТМЕТКИ (``ElevationMarker``) — ОТКАЗАНО, причина:
   «маркер сам по себе не рисует ничего».
   * ``ElevationMarker.CreateElevationMarker(Document, ElementId, XYZ, int)``
     компилируется 6/6 — вопрос не в доступности API.
   * У свежесозданного маркера ``CurrentViewCount == 0`` и ``HasElevations()``
     == false ПО ПОСТРОЕНИЮ: чертёжный продукт — это ВИДЫ на маркере, а не
     маркер. Единственное честное постусловие одиночного опа звучало бы как
     «пустой маркер существует», то есть оп, который нельзя довести до
     чертежа. Это ровно тот «построено, но бесполезно», которого дом избегает.
   * ЧТО ПОТРЕБОВАЛ БЫ ВТОРОЙ ОП, и он ВЫРАЗИМ СЕГОДНЯ НЕ ВЕСЬ:
     ``ElevationMarker.CreateElevation(Document, ElementId viewPlanId, int
     index)`` — 6/6. **Имя ``CreateElevationView`` НЕ СУЩЕСТВУЕТ: CS1061 на
     всех шести** (ловушка: правдоподобное имя, которого нет). Входы:
     ``marker`` — target_w (element_id | ref на оп-маркер), выразим;
     ``in_plan`` — id ПЛАНА, в котором маркер виден, выразим ровно так же,
     как ``in_view`` ниже (пула видов по-прежнему нет); ``index`` — int,
     0..``MaximumViewCount``-1, охраняется ``IsAvailableIndex``.
     НЕВЫРАЗИМО СЕГОДНЯ ОДНО, И ОНО ЯЗЫКОВОЕ: ``CreateElevation`` возвращает
     ``ViewSection``, то есть в реестре впервые появился бы оп, СОЗДАЮЩИЙ
     ВИД, — а на утверждении «ни один оп KIR не создаёт View» стоит
     типизированный отказ ``authoring._annot_view_res`` для ``in_view: ref``.
     После такого опа этот отказ стал бы ЛОЖНЫМ (``ViewSection`` приводится к
     ``View`` законно), то есть понадобился бы новый ``ReferenceKind.VIEW`` и
     пересмотр отказа — изменение ЯЗЫКА, а не операции.
   * Диапазон ``initialViewScale`` — 1..24 000, и это НЕ наше число: так
     сказано в самой RevitAPI.xml («The denominator X of the view scale 1/X
     must be in the range 1 to 24,000»). Записан здесь, чтобы следующая волна
     не выдумала свой.

2. ``NewModelText`` — ОТКАЗАНО НАВСЕГДА для проектных документов, и это
   ЗАМЕР: ``doc.Create.NewModelText`` даёт **CS1061 на всех шести** (у
   ``Autodesk.Revit.Creation.Document`` такого члена нет вовсе), а
   ``doc.FamilyCreate.NewModelText`` существует, но живёт на
   ``FamilyItemFactory``, то есть ТОЛЬКО в редакторе семейств, и его подпись
   — ШЕСТЬ аргументов (``string, ModelTextType, SketchPlane, XYZ,
   HorizontalAlign, double``; попытка семью даёт CS1501 6/6). KIR пишет
   проектные документы, значит объёмного текста у него быть не может ни на
   одной версии. НЕ ПРЕДЛАГАТЬ ЗАНОВО.

3. ЛОВУШКА ДОКУМЕНТАЦИИ, пойманная этой волной:
   ``FilledRegion.IsRegionCreationEnabledInView`` ОПИСАН в RevitAPI.xml 2026
   («since 2012») и даёт **CS0117 на всех шести DLL**. Ровно случай #78 из
   канона: документация Autodesk расходится с собственными сборками Autodesk,
   судья — компилятор. Поэтому предпроверки вида у заливки нет, и её роль
   играет типизированный отказ по исключению самого ``Create``.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

OPS = [
    # dimension — a size between >=2 refs (elements or grids), drawn in
    # in_view's 2D plane at line_at [u,v]. VIEW-BINDING LAW (semantic witness):
    # every ref must be visible in in_view — checked post-commit (no snapshot
    # visibility pool exists yet; witness is the only layer that can prove it).
    OpSpec(
        name="create_dimension",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("refs", "refs_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            ParamSpec("line_at", "pt_view2d", required=True),
            ParamSpec("dim_type", "target_w"),          # optional catalog typoразмер
        ),
        capability=(("create", "dimension"),),
        # 28.07 (live E5 measurement, FAS_R23 Revit 2023): the "line_at
        # reproduced" clause is retired — once the dimension line's own
        # direction became geometry-derived (the first reference's face
        # normal, not a fixed view axis), "offset along a fixed axis" is no
        # longer a meaningful invariant, and Dimension.Curve stays ALWAYS
        # UNBOUND regardless (Revit API Developer Guide) — see
        # _emit_dimension's docstring for the full law.
        # 09.08: the value clause REVERSES the 28.07 "receipt-only" note.
        # That note was true while the emitter picked an arbitrary planar
        # face; it stopped being true once the resolver started knowing which
        # PLANE it hands to NewDimension. The gated claim is not "the number
        # the operator wanted" (no compiler can know exterior vs interior) —
        # it is "the number Revit printed is the distance between the
        # geometry this dimension is bound to", which the witness re-derives
        # from those planes. No tolerance is registered for it: the
        # comparison runs against Revit's own Application.VertexTolerance,
        # read at runtime, so there is no number here to drift.
        post=("dimension exists in in_view (materialize); References bound "
              "to all refs, none empty (topology); every ref visible in "
              "in_view (semantic, VIEW-BINDING LAW); measured value equals "
              "the distance between the geometry the references name "
              "(geometry)"),
        writes_model=True,
    ),
    # angular dimension — the ANGLE between exactly two non-parallel refs,
    # drawn in in_view. AngularDimension.Create is 2017-era API and compiles
    # on ALL SIX shipped versions (measured 09.08 against the reference
    # assemblies via the live Roslyn service, not against docs) — unlike the
    # rest of that family: LinearDimension/RadialDimension/ArcLengthDimension
    # .Create are 2025-2026 only, and NewDiameterDimension/NewRadialDimension
    # /NewAngularDimension live on FamilyItemFactory alone (doc.FamilyCreate)
    # — family editor only, so unusable for the project documents KIR writes.
    #
    # EXACTLY TWO refs, and that bound is derived, not chosen: the API demands
    # "at least two, non parallel and rays of the arc passed", and the arc's
    # vertex is the intersection of the two referenced planes — a third plane
    # has no place in that construction. So the refs_w bound for this op is
    # (2, 2) in authoring_validation, beside create_dimension's own (2, 16).
    #
    # `at` is ONE view-space point and it carries three jobs at once, which is
    # why there is no radius parameter and no centre parameter: it fixes the
    # arc's radius (distance from the derived vertex), and it picks WHICH of
    # the four ray combinations is measured (each ray is signed toward it).
    # Same law as create_dimension.line_at — the author points at the drawing,
    # the compiler derives the geometry.
    OpSpec(
        name="create_angular_dimension",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("refs", "refs_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            ParamSpec("at", "pt_view2d", required=True),
            ParamSpec("dim_type", "target_w"),
        ),
        capability=(("create", "dimension"),),
        post=("angular dimension exists in in_view (materialize); References "
              "bound to all refs, none empty (topology); every ref visible in "
              "in_view (semantic, VIEW-BINDING LAW); measured angle equals "
              "the sweep of the arc built from those references (geometry)"),
        writes_model=True,
    ),
    # tag — a mark on target, drawn in in_view. `at` is REQUIRED (not
    # defaulted): IndependentTag.Create has no point-less overload on either
    # version branch, and a compile-time "near the target" default would need
    # the target's 2D position in in_view — unavailable without a witness/
    # geometry round-trip. A human places the tag point explicitly in the
    # Revit UI; the IR asks for the same (no invented auto-placement).
    OpSpec(
        name="create_tag",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("target", "target_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            ParamSpec("at", "pt_view2d", required=True),
            ParamSpec("leader", "bool"),
            ParamSpec("tag_type", "target_w"),
        ),
        capability=(("create", "tag"),),
        post=("tag exists in in_view, TaggedLocalElementId == target (semantic, "
              "VIEW-BINDING LAW: target must be visible in in_view); at "
              "reproduced ±tol in view-space (geometry)"),
        writes_model=True,
        # 03.08: «±tol» получил адрес — головка марки сверяется в осях вида
        # с тем же 10 мм, что стояло литералом в _emit_tag.
        tolerances={"head_mm": 10.0},
    ),
    # text — a note (± leader) in in_view at view-space `at`; width_mm
    # (optional, TextNote.Width — the ONE per-instance sheet-space size Revit
    # exposes; font HEIGHT is TextNoteType-owned, not per-instance, so it is
    # NOT modeled here, see module docstring) is compiler-owned size-from-
    # intent via the resolved view's own Scale, read at RUNTIME from in_view
    # (docspace.view_scale_to_model_mm mirrors the SAME formula as a pure-
    # python proof/test helper — the compiler cannot know view_scale at
    # python-emit-time, only after the view is resolved in C#, exactly like
    # emit_view2d_to_xyz_cs never hardcodes a basis).
    OpSpec(
        name="create_text",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("at", "pt_view2d", required=True),
            ParamSpec("content", "str_long", required=True),
            ParamSpec("width_mm", "mm", min_val=1.0, max_val=5000.0),
            ParamSpec("text_type", "target_w"),
            ParamSpec("leader_to", "target_w",
                      ref_kinds=(ReferenceKind.ELEMENT,)),
        ),
        capability=(("create", "text_note"),),
        post=("text note exists in in_view at `at` ±tol (geometry); content "
              "matches verbatim (re-read, semantic); when leader_to given, "
              "a leader exists, its endpoint matches the target's in-view "
              "bounding-box center, and leader_to is visible in in_view "
              "(VIEW-BINDING LAW)"),
        writes_model=True,
        # 03.08: «±tol» точки вставки — те же 5 мм, что в _emit_text.
        # НАЗВАНО ЧЕСТНО: допуск ширины (`__wmm * 0.15 + 5.0`) сюда НЕ
        # внесён — это относительная поправка на подгонку Revit под контент,
        # а не обещание `post`; вносить её значило бы выдать за контракт то,
        # чего контракт не обещает.
        tolerances={"location_mm": 5.0},
    ),
    # ── ЗАЛИВКА (09.08.2026): 2D-штриховка по контуру, живущая НА ВИДЕ ──────
    #
    # `FilledRegion.Create(Document, ElementId typeId, ElementId viewId,
    # IList<CurveLoop>)` — 6/6 по эталонным сборкам. Первая операция, где
    # сходятся ДВА подъязыка: CONTOUR даёт форму, docspace — пространство.
    #
    # КОНТУР ЛОЖИТСЯ В ПЛОСКОСТЬ ВИДА, А НЕ В XY МОДЕЛИ, и это не выбор
    # оформления: RevitAPI.xml у самого вызова говорит, что петля обязана
    # лежать «in a plane parallel to the view's detail sketch plane», то есть
    # готовый `contour.emit_loop_cs` (он собирает петлю при z=0 в мировых XY)
    # верен РОВНО на видах с горизонтальной эскизной плоскостью — на планах —
    # и отвергается Revit'ом на любом разрезе или фасаде. «Заземление и
    # проверка достаются даром» подтвердилось: `ground.py` опускает ЛЮБОЙ род
    # `region`, и все законы формы (замкнутость, самопересечения, дуги, дырки
    # внутри) работают без единой строки здесь. А вот СБОРКА петли даром не
    # досталась — она поехала через базис вида, тем же выражением, каким
    # `create_text`/`create_tag` кладут свою одну точку.
    #
    # СЛЕДСТВИЕ, КОТОРОЕ ОБЯЗАНО БЫТЬ ОТКАЗОМ, А НЕ ПРИМЕЧАНИЕМ: точки
    # контура — это [u,v] мм ПРОСТРАНСТВА ВИДА. Адрес от осей (`at_grid`)
    # даёт МОДЕЛЬНУЮ пару координат, и на плане с мировым базисом эти числа
    # совпадают, а на разрезе — молча означают другое место. Ровно та
    # путаница пространств, которую docspace.py существует делать
    # НЕВЫРАЗИМОЙ, поэтому эмиттер отказывает по `at_grid` внутри `contour`.
    OpSpec(
        name="create_filled_region",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("contour", "region", required=True),
            ParamSpec("type", "sel"),
        ),
        capability=(("create", "geometry"),),
        # ЧТО ЗДЕСЬ НЕ ОБЕЩАНО, И ЭТО ГРАНИЦА ЖАНРА, А НЕ НЕДОРАБОТКА:
        # 2D-заливка не утверждает НИЧЕГО о здании. Она не доказывает, что
        # закрашено то, что под ней (связи «заливка ↔ элемент под ней» в API
        # нет вовсе), не доказывает попадания в область подрезки вида
        # (заливка вне рамки существует и проходит все проверки, оставаясь
        # невидимой на листе — но подрезку двигают, и отказывать по ней
        # значило бы запрещать законное), и не доказывает ВИДА штриховки:
        # узор, цвет и вес линий принадлежат `FilledRegionType`, поэтому
        # доказан id типа, а не то, что этот тип рисует.
        post=("filled region exists on in_view (materialize); OwnerViewId == "
              "in_view (topology); GetTypeId == the resolved filled region "
              "type (semantic); GetBoundaries reproduces the authored loops "
              "in view space — loop count, curve count, and every authored "
              "edge matched exactly once by its endpoints and its mid-point "
              "±1.0 (geometry)"),
        writes_model=True,
        grounded=(("type", "filled_region_types", False),),
        # ДОПУСК ВЫВЕДЕН, А НЕ НАЗНАЧЕН: 1.0 мм — это `contour._EDGE_TOL`, то
        # есть СОБСТВЕННОЕ разрешение подъязыка по точкам. Ребро короче него
        # CONTOUR отвергает статически как нулевое, значит две точки ближе
        # 1 мм для этого языка — ОДНА точка. Свидетель, различающий то, чего
        # язык различить не даёт, требовал бы от Revit точности, которой сам
        # не выражает. Замок на равенство стоит в тестах.
        tolerances={"boundary_mm": 1.0},
    ),
]
