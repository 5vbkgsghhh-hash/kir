"""KIR registry AGGREGATOR — the single source of truth (SPEC §3).

OpSpec DEFINITIONS live in per-family modules (ops_authoring/ops_contour/
ops_connect/ops_mep/ops_struct/ops_annotation/ops_families) so that N
Sonnet waves add ops CONCURRENTLY without touching this file or each other
(the contention that took prod down once). This module imports them, builds the
aggregate OPS, and enforces registry invariants on the WHOLE — schema_gen,
grammar, capability-cells and the gate all still read from here. Shared types
and tables (OpSpec/ParamSpec/KindSpec, KINDS, FILTERS, DEFAULTS, vocab deltas,
WRITE_FAMILIES) live in registry_base.py and are re-exported here for
backward-compat (every existing `spec.X` access keeps working). See
REGISTRY_MODULES.md for how a wave adds an op.
"""
from __future__ import annotations

from functools import lru_cache as _lru_cache

# Re-export the shared base so `spec.KINDS`, `spec.OpSpec`, `spec.DEFAULTS`,
# `spec.WRITE_FAMILIES`, ... all keep resolving exactly as before.
from kukai.ir.registry_base import *  # noqa: F401,F403
from kukai.ir.registry_base import (  # explicit, for this module + linters
    EffectKind, IdentityCardinality, OpSpec, ResultSpec, IR_VERSION,
    ROUTE_ONLY_ACTIONS, BANNED_OBJECT_KIND_PLACEHOLDERS,
)

# Every registry module. A new family = a new ops_*.py added to THIS list only.
# ТЁМНЫЙ МОДУЛЬ, СНЯТЫЙ 10.08.2026: `ops_doc`. Он был СЕМЕНЕМ семьи
# аннотаций (tag/dimension/text) и родил её — она уехала в `ops_annotation`,
# чей собственный докстринг так и говорит: «annotation tirage beyond ops_doc
# seed». После переезда `ops_doc.OPS` стоял ПУСТЫМ списком с 17.07, пока все
# соседние `ops_*` двигались весь август. Пустой модуль в списке импорта
# реестра неотличим от сломанного: он ничего не регистрирует и ничего об этом
# не говорит. Семя, давшее всходы, не хранят рядом с урожаем.
from kukai.ir import (  # noqa: E402
    ops_authoring, ops_contour, ops_connect, ops_mep,
    ops_struct, ops_annotation, ops_families, ops_arch,
    ops_shape, ops_room, ops_opening, ops_analysis, ops_site, ops_sweep,
    ops_solid, ops_mass,
)

_REGISTRY_MODULES = (
    ops_authoring, ops_contour, ops_connect, ops_mep,
    ops_struct, ops_annotation, ops_families, ops_arch,
    ops_shape, ops_room, ops_opening, ops_analysis, ops_site, ops_sweep,
    ops_solid, ops_mass,
)

# Aggregate — duplicate op names across modules are a hard error (each op lives
# in exactly one ops_*.py; this is what makes concurrent-wave edits safe).
OPS: dict[str, OpSpec] = {}
for _mod in _REGISTRY_MODULES:
    for _op in _mod.OPS:
        if _op.name in OPS:
            raise AssertionError(
                f"duplicate op name {_op.name!r} across registry modules "
                f"(module {_mod.__name__}); each op must live in exactly one ops_*.py")
        OPS[_op.name] = _op


#: Ops that OWN THEIR TRANSACTION SCOPE and therefore must be the sole op of
#: their program (KIR-L002 / `diag.PLAN_SOLO_OP`).
#:
#: `create_stairs` drives `StairsEditScope`, which opens and commits its own
#: transactions; it cannot nest inside the shared program transaction, so a
#: neighbour in the same program is unbuildable BY REVIT, not by our taste.
#:
#: ONE TRUTH, FOUR READERS. Until 2026-08-04 this fact was spelled three times
#: in three places — a hardcoded `op["op"] == "create_stairs"` in the emitter
#: (`authoring.emit_program`), a private `_SOLO_OPS` in
#: `decompile/materialize.py`, and prose in `tool_doc`/`course`. The plan stage
#: knew it NOWHERE, so the refusal only existed AFTER grounding: the sandbox
#: assembled the program, `plan_program` accepted it, and the model met the wall
#: only on a live device (measured 04.08 — `plan_program` accepted
#: `[create_stairs, create_wall]` without a word). A fact stated in N places
#: drifts in N-1 of them; stated here it is read by plan, emit and materialize
#: alike.
#: `create_stairs_landing` (10.08.2026) — ВТОРОЙ жилец этого множества, и он
#: здесь по ЗАМЕРУ, а не по симметрии.  RevitAPI.xml пишет у
#: `StairsLanding.CreateSketchedLanding` дословно и одинаково на всех шести
#: версиях: `InvalidOperationException` — «The stairs element represented by
#: stairsId is not in an active StairsEditScope».  Область правки площадке
#: нужна ТА ЖЕ, что маршу, и открыть её на уже стоящей лестнице позволяет
#: одноаргументный `StairsEditScope.Start(ElementId)` (замер компиляцией 6/6,
#: 10.08).  Отсюда: площадка — отдельная ПРОГРАММА, а не сосед марша.  Закон
#: соло-опа при этом не ослаблен ни на байт — наоборот, второй жилец делает
#: его общим правилом вместо частного случая одного имени.
SOLO_OPS: frozenset[str] = frozenset({"create_stairs", "create_stairs_landing"})

#: КАК ВЫГЛЯДИТ ССЫЛКА, ПЕРЕСЁКШАЯ ГРАНИЦУ ФАЗЫ ПЛАНА СТРОИТЕЛЬСТВА.
#:
#:     {"by": "phase_result", "value": "<id опа-производителя>", "phase": <N>}
#:
#: ПОЧЕМУ ЭТО ИМЯ ЖИВЁТ ЗДЕСЬ, А НЕ ТАМ, ГДЕ ЕГО ПИШУТ. Пишет метку разметчик
#: (`course.phase()`), а ПОДСТАВЛЯЕТ её исполнитель плана (`compiler.
#: substitute_phase_results`, зовёт `serving`), и компилятор не имеет права
#: импортировать курс: курс импортирует компилятор ради бюджета, и обратное
#: ребро замкнуло бы цикл. Написать литерал `"phase_result"` в обоих местах
#: значило бы завести ту самую вторую запись одного факта, из-за которой
#: `SOLO_OPS` выше разъехался в двух местах из трёх. Реестр видят оба.
#:
#: ПОЧЕМУ НЕ `by=ref`. `ref` адресует оп ЭТОЙ ЖЕ программы и разрешается до
#: эмиссии; к моменту следующей фазы произведённый элемент уже закоммичен
#: ОТДЕЛЬНОЙ транзакцией, и ссылки на него внутри программы больше нет. Метка
#: — обязательство подставить `{"by": "element_id"}`, а не форма селектора:
#: дойдя до `plan_program` неподставленной, она обязана отказать.
CROSS_PHASE_BY: str = "phase_result"


#: ЗАКРЫТЫЙ СЛОВАРЬ ВИДОВ ПАРАМЕТРА — 34 вида, ровно те, что стоят в реестре.
#:
#: ДО 07.08.2026 ЕГО НЕ БЫЛО, и `ParamSpec.kind` была обычной строкой: опечатка
#: в ней не падала нигде. Стоила она дороже, чем кажется. В
#: `authoring_validation` разбор параметров — цепочка `if/elif p.kind == ...`,
#: и хвоста у неё не было; параметр с неузнанным видом не проверялся НИ ОДНОЙ
#: ветвью и не попадал в `norm`, то есть уезжал дальше так, будто автор его не
#: писал. Обязательный параметр молча превращался в отсутствующий.
#:
#: ПРАВИЛО НЕ НОВОЕ — НОВО ЕГО ИСПОЛНЕНИЕ. REGISTRY_MODULES.md уже называет
#: новый вид параметра изменением «уровня Fable» (координация, наравне с новым
#: пулом снапшота и новым KIND), и ровно это записано в комментарии к
#: `known_pools` ниже. Пулы лint закрывал, виды — нет. Теперь закрывает: пока
#: вид не назван здесь, реестр не импортируется вовсе.
#:
#: Замков на опечатку теперь три, и они НЕЗАВИСИМЫ: этот (на импорте реестра),
#: `schema_gen` (на сборке схемы) и
#: `authoring_validation._assert_kind_dispatched` (на разборе программы).
PARAM_KINDS: frozenset[str] = frozenset({
    # точки, ломаные и кривые
    "pt_xy", "pt_xyz", "pt_view2d", "pts", "pts_xyz", "pts_list",
    "path", "path3", "arc", "spiral", "region", "slopes", "mesh",
    # графы
    "graph_nodes", "graph_segments",
    # числа и скаляры
    "mm", "deg", "num", "int", "bool",
    # строки и перечисления
    "str", "str_long", "enum", "value",
    # селекторы
    "sel", "sel_list", "target", "target_w", "refs_w",
    # составные операнды
    "member_ops", "placements",
    # только семейство query (разбираются в `compiler._validate_op`)
    "fields", "filters", "kind_enum",
})


def _lint_registry() -> None:
    """Registry invariants, enforced at import on the AGGREGATE (RISK R10,
    bare-action ban 13.2, §16 placeholder ban)."""
    for name in SOLO_OPS:
        if name not in OPS:
            raise AssertionError(
                f"SOLO_OPS names {name!r}, which is not a registered op — "
                f"a solo rule about a nonexistent op is a rule nobody enforces")
    for op in OPS.values():
        if not isinstance(op.effect, EffectKind):
            raise AssertionError(f"{op.name}: effect must be typed")
        if not isinstance(op.result, ResultSpec):
            raise AssertionError(f"{op.name}: result must be typed")
        if op.family == "query" and op.writes_model:
            raise AssertionError(f"{op.name}: query family must not write")
        if op.family in ("authoring", "modify") and not op.writes_model:
            raise AssertionError(f"{op.name}: authoring op must declare writes_model")
        if op.writes_model == (op.effect is EffectKind.READ):
            raise AssertionError(
                f"{op.name}: writes_model and typed effect disagree")
        if (op.family == "query"
                and op.result.identity_cardinality
                is not IdentityCardinality.NONE):
            raise AssertionError(
                f"{op.name}: query result cannot claim write identity")
        if (op.writes_model
                and op.result.identity_cardinality
                is IdentityCardinality.NONE):
            raise AssertionError(
                f"{op.name}: write result needs identity evidence")
        for p in op.params:
            if p.kind not in PARAM_KINDS:
                raise AssertionError(
                    f"{op.name}.{p.name}: неизвестный вид параметра "
                    f"{p.kind!r}. Вид — не свободная строка: неназванный вид "
                    f"не разбирает ни одна ветвь `authoring_validation`, и "
                    f"параметр молча не доедет до `norm`. Назовите вид в "
                    f"`PARAM_KINDS` и заведите ему ветвь разбора")
        for action, object_kind in op.capability:
            if not action or not object_kind \
                    or object_kind in BANNED_OBJECT_KIND_PLACEHOLDERS \
                    or action in BANNED_OBJECT_KIND_PLACEHOLDERS:
                raise AssertionError(f"{op.name}: bare/placeholder capability cell "
                                     f"({action!r}×{object_kind!r}) — banned forever (§16)")
            if action in ROUTE_ONLY_ACTIONS:
                raise AssertionError(f"{op.name}: {action} is route-only, cannot own IR ops")
        known_pools = ("levels", "wall_types", "pipe_types", "piping_system_types",
                       "floor_types", "column_symbols_structural",
                       "column_symbols_architectural", "window_symbols",
                       "door_symbols", "family_symbols",
                       "roof_types", "duct_types", "duct_system_types",
                       "cable_tray_types", "grids",
                       # wave/struct (2026-07-17): create_beam/create_foundation.
                       # REGISTRY_MODULES.md calls a new snapshot pool a
                       # "Fable-level" change (new param-kind/pool/KIND =
                       # coordination) — flagged in the wave report as the one
                       # unavoidable shared touch this wave needed beyond its
                       # own ops_struct.py/struct_emit.py/test_struct.py.
                       "beam_types", "foundation_symbols",
                       # wave/arch (2026-07-29): create_ceiling/create_railing.
                       # ДВА НОВЫХ ПУЛА, а не переиспользование floor_types —
                       # и это не педантизм: CeilingType и RailingType в Revit
                       # разные классы, и грунтовка потолка по пулу перекрытий
                       # дала бы ПРАВДОПОДОБНЫЙ, но неверный тип, то есть
                       # тихую подмену, неотличимую снаружи от успеха. Пул —
                       # «Fable-level» изменение (REGISTRY_MODULES.md), потому
                       # что тянет за собой сборщик в open_model.py; лишний
                       # повод не заводить его от лени, а не повод не заводить
                       # его по делу.
                       "ceiling_types", "railing_types",
                       # wave/wall-foundation (2026-08-09):
                       # create_wall_foundation. Пул собирается ПО КЛАССУ
                       # (WallFoundationType — самостоятельный класс
                       # ElementType, компиляция 6/6), а не по категории:
                       # OST_StructuralFoundation держит и точечные башмаки
                       # (FamilySymbol, пул foundation_symbols), и ленточные
                       # типы, а WallFoundation.Create принимает ТОЛЬКО
                       # WallFoundationType — иначе ArgumentException
                       # «typeId is not a valid WallFoundationType id»
                       # (RevitAPI.xml). Переиспользовать foundation_symbols
                       # значило бы отдать эмиттеру id, который вызов
                       # заведомо отвергнет.
                       "wall_foundation_types",
                       # wave/framing (2026-08-09): create_truss. ОДИН новый
                       # пул на две операции, и это замер: у балочной системы
                       # своего пула нет вовсе — её `symbol` это обычная
                       # несущая балка из `beam_types` (тот же класс, тот же
                       # фильтр по типу размещения). А вот тип фермы —
                       # отдельный класс TrussType, и подсунуть вместо него
                       # что-либо ещё нельзя: Truss.Create отвергает чужой id
                       # ArgumentException'ом, а документного типа по
                       # умолчанию у фермы не существует (ElementTypeGroup.
                       # TrussType не компилируется ни на одной из шести).
                       "truss_types",
                       # wave/mep-electrical (2026-08-09): create_conduit и
                       # два гибких опа. ТРИ НОВЫХ ПУЛА, и снова не от лени
                       # переиспользования: ConduitType, FlexDuctType и
                       # FlexPipeType — самостоятельные классы Revit, а не
                       # подмножества cable_tray_types/duct_types/pipe_types.
                       # Заземлить гибкий воздуховод по пулу жёстких значило
                       # бы отдать эмиттеру тип, который `FlexDuct.Create`
                       # отвергает (`IsFlexDuctTypeId` — отдельный предикат
                       # API), то есть поменять типизированный отказ на
                       # рантайм-исключение внутри транзакции.
                       "conduit_types", "flex_duct_types", "flex_pipe_types",
                       # wave/analysis (2026-08-09): нагрузки КР. ЧЕТЫРЕ пула,
                       # и три из них — типы нагрузок, собираемые ПО КЛАССУ
                       # (PointLoadType/LineLoadType/AreaLoadType —
                       # самостоятельные классы ElementType, компиляция 6/6).
                       # Свести их в один нельзя: `PointLoad.Create` принимает
                       # только `PointLoadType`, и отдать ему тип линейной
                       # нагрузки значило бы заменить типизированный отказ
                       # рантайм-исключением внутри транзакции.
                       #
                       # `load_cases` — пул ЭКЗЕМПЛЯРОВ, а не типов (как
                       # `levels` и `grids`), и он обязателен у всех трёх
                       # нагрузок: случай загружения — профессиональная суть
                       # операции, а не оформление (см. ops_analysis.py).
                       # Пула `load_natures` здесь НЕТ намеренно: природа —
                       # вход операции создания СЛУЧАЯ, которой в этой волне
                       # нет, и пул, которым никто не заземляется, был бы
                       # первым исключением из правила «пул существует ради
                       # селектора».
                       "load_cases", "point_load_types", "line_load_types",
                       "area_load_types",
                       # wave/site (2026-08-09): create_topography(toposolid)
                       # и create_building_pad. ДВА НОВЫХ ПУЛА, и оба —
                       # «Fable-level» изменение (тянут сборщик в
                       # open_model.py), поэтому названы в отчёте волны как
                       # единственный неизбежный общий шов.
                       #
                       # У толщи рельефа пул — ЕДИНСТВЕННЫЙ способ узнать
                       # список типов: ElementTypeGroup.ToposolidType не
                       # существует ни на одной из шести версий (замерено),
                       # то есть спросить документ «а какая толща по
                       # умолчанию» нельзя в принципе — ровно как у
                       # ограждения. У площадки под здание умолчание, наоборот,
                       # ЕСТЬ (ElementTypeGroup.BuildingPadType, 6/6), и пул
                       # нужен для явного `by:name`.
                       "toposolid_types", "building_pad_types",
                       # wave/sweep (2026-08-09): create_wall_sweep и
                       # create_slab_edge. ДВА НОВЫХ ПУЛА, и оба собираются
                       # по-разному ПО ЗАМЕРУ, а не по вкусу.
                       #
                       # `slab_edge_types` — ПО КЛАССУ (`SlabEdgeType` —
                       # самостоятельный класс ElementType, компиляция 6/6),
                       # ровно как `wall_foundation_types`: `NewSlabEdge`
                       # принимает ТОЛЬКО `SlabEdgeType`, а `NewFascia`/
                       # `NewGutter` — свои классы, и подсунуть один вместо
                       # другого нельзя (ArgumentException, RevitAPI.xml).
                       #
                       # `wall_sweep_types` — ПО ДВУМ КАТЕГОРИЯМ
                       # (OST_Cornices + OST_Reveals), и это единственный
                       # возможный способ: класса `WallSweepType`-как-
                       # ElementType в API НЕ СУЩЕСТВУЕТ вовсе —
                       # `WallSweepType` это ПЕРЕЧИСЛЕНИЕ {Sweep, Reveal}
                       # (замерено), а сам тип живёт обычным ElementType в
                       # одной из двух категорий. Пул поэтому ОДИН на карнизы
                       # и русты, а какое значение перечисления передать,
                       # эмиттер выводит из категории разрешённого типа.
                       "wall_sweep_types", "slab_edge_types",
                       # wave/detail (2026-08-09): create_filled_region. ПУЛ
                       # СОБИРАЕТСЯ ПО КЛАССУ (FilledRegionType — тип
                       # ElementType, компиляция 6/6), а не по категории:
                       # OST_FilledRegion держит и сами заливки, и их типы, а
                       # `FilledRegion.Create` принимает ТОЛЬКО id типа
                       # заливки и сам это проверяет
                       # (`IsValidFilledRegionTypeId`, тоже 6/6). Документное
                       # умолчание у него ЕСТЬ
                       # (`ElementTypeGroup.FilledRegionType`, 6/6), поэтому
                       # пул нужен не как единственный вход, а ради явного
                       # `by:name` — у настоящего проекта типов заливки
                       # десятки («Бетон», «Грунт», «Утеплитель»), и вслепую
                       # они не выбираются.
                       "filled_region_types",
                       # wave/reinforcement (2026-08-10):
                       # create_area_reinforcement. ТРИ ПУЛА, все ПО КЛАССУ
                       # (AreaReinforcementType / RebarBarType /
                       # RebarHookType — самостоятельные классы ElementType,
                       # компиляция 6/6), и ни один не сводится к другому:
                       # `AreaReinforcement.Create` проверяет КАЖДЫЙ из трёх
                       # аргументов на свой класс отдельно и бросает
                       # ArgumentException на чужом id (RevitAPI.xml). Свести
                       # их в один пул «арматурных типов» значило бы заменить
                       # типизированный отказ рантайм-исключением внутри
                       # транзакции.
                       #
                       # `rebar_hook_types` нужен ИМЕННО как пул, хотя пропуск
                       # крюка законен: пропуск значит «без крюков», а НАЗВАТЬ
                       # крюк по имени автор обязан иметь возможность — иначе
                       # единственной выразимой арматурой была бы арматура без
                       # анкеровки.
                       "area_reinforcement_types", "rebar_bar_types",
                       "rebar_hook_types")
        for pname, pool, _req in op.grounded:
            variants = ([pool.format(category=c) for c in ("structural", "architectural")]
                        if "{category}" in pool else [pool])
            for v in variants:
                if v not in known_pools:
                    raise AssertionError(f"{op.name}.{pname}: unknown snapshot pool {v!r}")


_lint_registry()


def ops_by_object_kind(*, writes: bool | None = None) -> list[tuple[str, list[str]]]:
    """Имена опов, сгруппированные по РОДУ ОБЪЕКТА их клеток способности.

    НИ ОДИН ТЕКСТ, ЕДУЩИЙ МОДЕЛИ, ЭТУ ГРУППИРОВКУ БОЛЬШЕ НЕ ПЕЧАТАЕТ (09.08).
    До этого дня её печатали и описание инструмента, и `course.spec()` — то
    есть внутреннее поле реестра (`element`, `element/mep_system`,
    `category/element`) стояло на поверхности, и автор не мог им пользоваться:
    из текста не следовало, почему `create_wall` отделён от `create_floor`.
    Оба читателя перешли на `ops_by_discipline`.

    ЕДИНСТВЕННЫЙ ОСТАВШИЙСЯ ЧИТАТЕЛЬ — ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ
    (`test_tool_doc.test_the_op_list_is_grouped_by_discipline_not_by_a_
    compiler_field`): он берёт заголовки отсюда и требует, чтобы НИ ОДНОГО из
    них в описании не было. Функция поэтому не мёртвая, но и не рабочая — она
    формулирует ЗАПРЕТ, и удалить её значило бы снять сторожа, который не даёт
    компиляторному полю вернуться на поверхность следующей волной.

    `writes=True` — только пишущие в модель, `False` — только читающие,
    `None` — всё вместе. Порядок групп: сначала крупные, дальше по алфавиту.
    """
    groups: dict[str, list[str]] = {}
    for name, op in sorted(OPS.items()):
        if writes is not None and op.writes_model is not writes:
            continue
        key = "/".join(sorted({kind for _action, kind in op.capability}))
        groups.setdefault(key, []).append(name)
    return sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))


#: ЯРЛЫК РАЗДЕЛА ДЛЯ ПЕЧАТИ. Это ПЕРЕВОД, а не второй словарь разделов:
#: ключи обязаны совпадать с `registry_base.DISCIPLINES` символ в символ, и это
#: держит тест, а не соглашение. Зачем перевод вообще: в тексте раздел стоит
#: ЗАГОЛОВКОМ группы, то есть платится каждым запросом, и «АР» против
#: «architectural» — это 2 символа против 13 на каждой из шести групп; а ещё
#: АР/КР/ОВ/ВК/ЭОМ — те же самые буквы, которыми разделы называет и сам
#: экстрактор, когда угадывает раздел связи по имени (`__Discipline`).
DISCIPLINE_RU: dict[str, str] = {
    "architectural": "АР (архитектура)",
    "structural": "КР (конструкции)",
    "mechanical": "ОВ (вентиляция)",
    "plumbing": "ВК (водоснабжение)",
    "electrical": "ЭОМ (электрика)",
    "shared": "общее",
}

#: Порядок групп в тексте — ЯВНЫЙ и по разделам, а не по размеру группы.
#: Автор планирует «сначала АР, потом КР, потом инженерка», и порядок, который
#: скачет от того, в какую волну добавили оп, читается как случайный.
DISCIPLINE_ORDER: tuple[str, ...] = (
    "architectural", "structural", "mechanical", "plumbing", "electrical",
    "shared",
)


@_lru_cache(maxsize=1)
def _category_disciplines() -> dict[str, str]:
    """Таблица «BuiltInCategory -> раздел», СОБРАННАЯ, а не написанная.

    Второго словаря разделов в пакете нет и заводить его нельзя (см.
    `registry_base.DISCIPLINES`). Поэтому раздел категории берётся у ДВУХ
    носителей того же самого словаря, которые уже существуют и поддерживаются
    ради другой работы:

    * `registry_base.KINDS` — род запроса; его `collector_cs` называет
      BuiltInCategory прямо в тексте коллектора;
    * `decompile.extract._CATEGORY_SPECS` — таблица извлечения; её строки и
      есть категории, которые конвейер читает.

    Расхождение между ними — не «выбрать поудобнее», а ОШИБКА: одна категория
    не может принадлежать двум разделам. Поэтому конфликт роняет сборку здесь,
    а не доезжает молча до текста, который читает модель.

    Импорт экстрактора ленивый: `spec` тянут все, а `decompile.extract` тянет
    за собой схему L0 и хелперы чтения.
    """
    import re as _re

    from kukai.ir.decompile.extract import _CATEGORY_SPECS

    table: dict[str, str] = {}

    def put(category: str, discipline: str, where: str) -> None:
        seen = table.setdefault(category, discipline)
        if seen != discipline:
            raise AssertionError(
                f"{category}: раздел разошёлся между носителями одного "
                f"словаря — {seen!r} против {discipline!r} ({where})")

    for kind in KINDS.values():
        for category in _re.findall(r"BuiltInCategory\.(OST_\w+)",
                                    kind.collector_cs):
            put(category, kind.discipline, f"KINDS[{kind.name!r}]")
    for cat in _CATEGORY_SPECS:
        put(cat.name, cat.discipline, "extract._CATEGORY_SPECS")
    return table


# ═════════════════════════════════════════════════════════════════════════
# КАТЕГОРИЯ РЕЗУЛЬТАТА ОПА — ОДИН ОТВЕТ, И ОН ЗДЕСЬ
#
# «В какую категорию Revit попадёт результат этого опа» — вопрос К РЕЕСТРУ:
# он про операцию, а не про конкретную постройку. До 10.08.2026 ответов было
# два с половиной: `acceptance._OP_CATEGORIES` (43 опа, кортежи),
# `clash_bundle.OP_CATEGORY` (29 опов, строки) — и `op_census_categories`
# ниже, который спрашивал ПЕРВЫЙ, то есть реестр зависел от судьи приёмки.
# Именно эта развилка и есть та работа, что делалась дважды.
#
# Таблица переехала сюда ЦЕЛИКОМ, вместе с разрешателем: у пяти опов
# категорию решает собственное закрытое перечисление (`category` у колонны и
# тел, `variety` у проёма, рельефа, фундамента), и таблица без разрешателя
# ответила бы неполно. `acceptance` теперь читает отсюда.
#
# ВТОРОГО СЛОВАРЯ БОЛЬШЕ НЕТ (сведён `8ad465a0`). До этого здесь стояло
# «`clash_bundle.OP_CATEGORY` остаётся вторым словарём: файл занят» и
# «расхождение ровно одно — `create_railing`». Оба утверждения устарели, и
# второе было ещё и НЕВЕРНЫМ на момент написания: при сведении нашлось, что
# таблицы разошлись ТРЕМЯ способами, а не одним. Урок ровно тот, ради
# которого этот файл и держит таблицу один: пока ответов два, число
# расхождений между ними никто не знает — его ОЦЕНИВАЮТ, и оценка занижена.
#
# ПРО «НЕЗАПОЛНЕННЫЕ» ОПЫ — АРИФМЕТИКА, А НЕ ОБЕЩАНИЕ (перемер 11.08.2026,
# `tests/test_registry_category_accounting.py`, он же и держит её впредь).
# Ниже 44 строки на 65 пишущих опов, и недостающий 21 — не пробел: КАЖДЫЙ
# назван, но механизмов ПЯТЬ, а не три, как говорила прежняя редакция:
#
#   1. строка в этой таблице                                        44
#   2. ветка разрешателя `op_result_categories` ниже (закрытое
#      перечисление самого опа решает категорию точно)               6
#   3. `acceptance._OPS_BLIND` — перепись их физически не видит,
#      у каждого причина словами и дата                             10
#   4. `acceptance._OPS_WITHOUT_ELEMENTS` — элемента не создают       4
#   5. `acceptance._OP_DERIVED` + разворот в ЧЛЕНОВ — `create_group`:
#      обёртку группы Revit ведёт как свою бухгалтерию, а ожидание
#      строится по членам группы                                     1
#                                                                  ---
#                                                                   65
#
# ПЯТЫЙ МЕХАНИЗМ ПРЕЖНЯЯ РЕДАКЦИЯ НЕ НАЗЫВАЛА ВОВСЕ, и её сумма (43+10+4+7)
# сходилась к 64 только потому, что и слагаемые, и итог были сняты в один
# день и с тех пор разъехались. Отсюда правило: эту арифметику держит ТЕСТ,
# а не абзац. Абзац объясняет ПОЧЕМУ, тест отвечает СКОЛЬКО.
#
# ЗАПОЛНЯТЬ НЕДОСТАЮЩЕЕ ЗАПРЕЩЕНО. Дописать сюда оп, чью клетку перепись не
# наблюдает, значит ЗАСТАВИТЬ приёмку ждать прибавки, которой она не увидит,
# — то есть отклонить ЧЕСТНУЮ постройку. Ошибка слепоты обратима (теряется
# только верхняя граница), ошибка заполнения — нет. Именно поэтому
# `create_curtain_grid_line` и `create_wall_foundation` строк здесь НЕ
# ИМЕЮТ и иметь не должны, пока не появится замер:
#   * `create_curtain_grid_line` — линия разрезки делит ячейки, и сколько
#     панелей с импостами окажется после неё, решает Revit (STANDS);
#   * `create_wall_foundation` — клетка ленточного фундамента НЕ ЗАМЕРЕНА:
#     WallFoundation не встретился ни в одном сохранённом разборе, а назвать
#     её по таксономии Revit — ровно та догадка, что валит верную постройку
#     (CLOSE_BY, закрывается ОДНИМ живым прогоном: квитанция уже везёт
#     Category.Id созданного элемента).
# Отсутствие здесь ИМЕНОВАНО там; это разные вещи.
# ═════════════════════════════════════════════════════════════════════════

#: ОП → КЛЮЧИ ПЕРЕПИСИ, КУДА ПОПАДЁТ ЕГО РЕЗУЛЬТАТ. Кортеж длиннее одного =
#: «в одну из них, а в какую — не видно» (сверяется сумма).
OP_RESULT_CATEGORIES: dict[str, tuple[str, ...]] = {
    "create_wall": ("OST_Walls",),
    "create_floor": ("OST_Floors",),
    "create_floor_by_contour": ("OST_Floors",),
    "create_roof": ("OST_Roofs",),
    "create_ceiling": ("OST_Ceilings",),
    "create_door": ("OST_Doors",),
    "create_window": ("OST_Windows",),
    "create_room": ("OST_Rooms",),
    "create_level": ("OST_Levels",),
    "create_grid": ("OST_Grids",),
    "create_extrusion_roof": ("OST_Roofs",),
    # Многоэтажная лестница живёт в СВОЕЙ категории, а не в
    # OST_Stairs: `MultistoryStairs.Create` создаёт контейнер, а
    # исходный марш остаётся тем же элементом, которым был.
    "create_multistory_stairs": ("OST_MultistoryStairs",),
    "create_beam": ("OST_StructuralFraming",),
    "create_stairs": ("OST_Stairs",),
    # Площадка живёт в СВОЕЙ категории и НЕ добавляет лестницы: хозяин уже
    # стоит в модели, `CreateSketchedLanding` вешает на него компонент.
    # Именно поэтому здесь одна строка, а не «OST_Stairs + OST_StairsLandings»:
    # вторая ячейка переписи означала бы «эта программа построила лестницу»,
    # и честный успех читался бы как незаказанный чужой create.
    "create_stairs_landing": ("OST_StairsLandings",),
    "create_pipe": ("OST_PipeCurves",),
    "create_duct": ("OST_DuctCurves",),
    "create_cable_tray": ("OST_CableTray",),
    # wave/mep-electrical (2026-08-09). Категория у всех пяти известна ТОЧНО:
    # её задаёт сам вызов API (Conduit/FlexDuct/FlexPipe — свои классы), а не
    # селектор типа. Заготовка трубы/воздуховода остаётся в категории своего
    # рода: Revit не заводит для placeholder отдельной категории, `Pipe` он
    # `Pipe` и есть, отличается только битом `IsPlaceholder`.
    "create_conduit": ("OST_Conduit",),
    "create_pipe_placeholder": ("OST_PipeCurves",),
    "create_duct_placeholder": ("OST_DuctCurves",),
    "create_flex_duct": ("OST_FlexDuctCurves",),
    "create_flex_pipe": ("OST_FlexPipeCurves",),
    # wave/analysis (2026-08-09). Категория у всех четырёх известна ТОЧНО —
    # её задаёт сам вызов API (PointLoad/LineLoad/AreaLoad/PathOfTravel —
    # свои классы Revit), а не селектор типа. Все четыре члена
    # BuiltInCategory проверены компиляцией на 2021-2026.
    #
    # ЧЕСТНО О ЛИШНЕМ ЭЛЕМЕНТЕ: точечная и линейная нагрузка авторят себе
    # рабочую плоскость (`SketchPlane.Create`), то есть создают в документе
    # ещё один элемент сверх названного. В справку «неожиданное» он не
    # попадёт: перепись считает по ЗАКРЫТОМУ набору категорий ожидания, а
    # `SketchPlane` в них не входит. Это ограничение переписи, а не
    # утверждение, что элемента нет, — и записано оно здесь именно затем,
    # чтобы следующий, кто будет сверять числа на живой модели, знал заранее.
    "create_point_load": ("OST_PointLoads",),
    "create_line_load": ("OST_LineLoads",),
    "create_area_load": ("OST_AreaLoads",),
    "create_path_of_travel": ("OST_PathOfTravelLines",),
    "create_pipe_system": ("OST_PipeCurves",),
    "route_pipe_system": ("OST_PipeCurves",),
    "route_duct_system": ("OST_DuctCurves",),
    "create_text": ("OST_TextNotes",),
    # wave/detail (2026-08-09): заливка. СУММА ПО ДВУМ РОДАМ, и это не
    # осторожность, а прецедент ограждения дословно: `FilledRegion.Create`
    # принимает тип заливки, а маскирующая область в Revit — это ТОЖЕ
    # FilledRegion, отличающаяся своим типом (`IsMasking` — свойство
    # ЭКЗЕМПЛЯРА, читается только ПОСЛЕ создания). Какие типы проекта
    # маскирующие, из программы не видно, поэтому выбрать одну категорию
    # значило бы поставить на догадку; сумма верна при любом ответе.
    # Обе константы существуют на всех шести версиях (замер компиляцией).
    "create_filled_region": ("OST_FilledRegion", "OST_MaskingRegion"),
    "create_dimension": ("OST_Dimensions",),
    "create_angular_dimension": ("OST_Dimensions",),
    # wave/room (2026-08-03): категория известна ТОЧНО — её задаёт сам вызов
    # NewRoomBoundaryLines, а не селектор типа (типа у операции нет вовсе).
    "create_room_separator": ("OST_RoomSeparationLines",),
    # wave/space (2026-08-10): пространство ОВК. Категория известна ТОЧНО и
    # ровно одна — её задаёт сам вызов `doc.Create.NewSpace`, чей
    # возвращаемый тип `Autodesk.Revit.DB.Mechanical.Space` доказан
    # компилятором (CS0029 на всех шести версиях), а не селектор типа:
    # типа у операции нет вовсе. Пары ключей здесь не нужно — выбора
    # между категориями у операции нет ни в одном поле.
    #
    # ПОЧЕМУ ЭТА СТРОКА ЕСТЬ, А НЕ ОБЪЯВЛЕНА СЛЕПОЙ. Слепота обязана быть
    # ЗАМЕРОМ, а не осторожностью, и здесь замер есть с обеих сторон.
    # Живая перепись (`acceptance_live.scope_census_fragment`) ключует
    # элемент через `Enum.GetName(typeof(BuiltInCategory), Category.Id)` по
    # всему `WhereElementIsNotElementType()`, то есть закрытой таблицы
    # категорий у неё нет вовсе — вопрос только в том, отдаёт ли Revit у
    # пространства эту категорию. Отдаёт: 169 пространств ТРЁХ зданий
    # корпуса (Electrical 80, Plumbing 43, Architectural 46) прочитаны
    # извлечением ИМЕННО как OST_MEPSpaces, `expected == extracted`,
    # `state: complete`. Сам член `BuiltInCategory.OST_MEPSpaces`
    # существует на всех шести версиях (замер компиляцией 10.08).
    # Ошибка в эту сторону дала бы `category_shortfall` и ОТКЛОНИЛА бы
    # честную постройку, поэтому строка стоит только на замере.
    "create_space": ("OST_MEPSpaces",),
    # wave/site (2026-08-09): площадка под здание — категория известна ТОЧНО,
    # её задаёт сам вызов BuildingPad.Create, а не селектор типа.
    "create_building_pad": ("OST_BuildingPad",),
    # Подобласть площадки: созданный ЭЛЕМЕНТ — это её TopographySurface
    # (сам SiteSubRegion элементом не является — замерено, CS0029), поэтому
    # перепись увидит её ровно там же, где обычный рельеф.
    "create_site_subregion": ("OST_Topography",),
    # wave/sweep (2026-08-09). КРАЕВОЙ ПРОФИЛЬ — категория известна ТОЧНО:
    # её задаёт сам вызов NewSlabEdge, а не селектор типа.
    "create_slab_edge": ("OST_EdgeSlab",),
    # СТЕННОЙ ПРОФИЛЬ — ДВЕ категории, и это не осторожность, а устройство
    # API. `WallSweep.Create` строит карниз ЛИБО руст, и решает это КАТЕГОРИЯ
    # РАЗРЕШЁННОГО ТИПА (OST_Cornices против OST_Reveals) — самого перечисления
    # `WallSweepType` перепись не видит, потому что видит только элементы.
    # Сумма по двум верна при любом ответе; выбрать одну значило бы отвергать
    # каждый правильно построенный руст (или каждый карниз) как «не в той
    # категории» — ровно тот же довод, по которому здесь стоят парами колонна
    # и ограждение.
    "create_wall_sweep": ("OST_Cornices", "OST_Reveals"),
    # wave/mass (2026-08-10). СТЕНА ПО ГРАНИ — категория известна ТОЧНО и
    # ровно одна: `FaceWall` не `Wall` (замерено, CS0029 на всех шести), но
    # категория у неё та же OST_Walls, и её задаёт сам вызов FaceWall.Create,
    # а не селектор типа. Пары здесь не нужно: выбора между категориями у
    # операции нет ни в каком поле.
    "create_face_wall": ("OST_Walls",),
    # Колонна: категорию выбирает ЗАКРЫТОЕ перечисление самого опа, поэтому
    # она известна точно — см. _category_of_op.
    "create_column": ("OST_StructuralColumns", "OST_Columns"),
    # Ограждение: ``OST_Railings`` не встретился НИ В ОДНОМ из 31 разбора, но
    # таблица лифтера знает обе, и версия Revit могла бы решить иначе. Сумма
    # по двум верна при любом ответе; выбрать одну значило бы поставить на
    # догадку там, где ставить не на что.
    "create_railing": ("OST_Railings", "OST_StairsRailing"),
    # Марка: род марки определяет КАТЕГОРИЯ ЦЕЛИ, а цель — id или ссылка,
    # то есть из программы не читается. Сумма по десяти родам, которые вообще
    # читает конвейер (tag_extract.TAG_CATEGORIES).
    "create_tag": (
        "OST_AreaTags", "OST_DoorTags", "OST_FloorTags", "OST_MaterialTags",
        "OST_MechanicalEquipmentTags", "OST_MultiCategoryTags",
        "OST_RoomTags", "OST_StairsRailingTags", "OST_StructuralFramingTags",
        "OST_WallTags",
    ),
}


def op_result_categories(op: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Ключи переписи для результата опа; None — категория неизвестна."""
    name = op.get("op")
    if name == "create_column":
        # Закрытое перечисление с умолчанием — категория известна точно.
        category = op.get("category", "structural")
        return (("OST_StructuralColumns",) if category == "structural"
                else ("OST_Columns",))
    if name in ("create_directshape", "create_solid_extrusion",
                "create_solid_revolve"):
        # ТРИ ОПА, ОДНА ВЕТКА, И ЭТО НЕ ЛЕНЬ: все три кладут результат в
        # DirectShape той же категории из той же закрытой таблицы, значит для
        # переписи они НЕРАЗЛИЧИМЫ по построению. Своя ветка на каждый оп
        # означала бы три места, где можно разойтись в ключе.
        #
        # ДВА КЛЮЧА, И ЭТО НЕ ПЕРЕСТРАХОВКА. Перепись §18.1 ключует элемент
        # его BuiltInCategory, а строки извлечения кладут в поле литерал
        # "DirectShape" (extract.py) — в 31 разборе ключа "DirectShape" в
        # переписи нет ни разу, а в строках он есть. Сумма по двум верна при
        # любом источнике переписи.
        from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES
        built_in = DIRECTSHAPE_CATEGORIES.get(op.get("category"))
        if built_in is None:
            return None
        return tuple(sorted((built_in, "DirectShape")))
    if name == "create_opening":
        # ПРОЁМ ОБЯЗАН НАЗВАТЬ СВОЮ КАТЕГОРИЮ, иначе одна новая операция
        # ослабила бы L2 для ВСЕЙ программы: оп с неизвестной категорией
        # снимает верхние границы целиком (на настоящем фасаде это уже стоило
        # 270 опов из 2 720).
        if op.get("variety") == "wall_rect":
            # Перегрузка NewOpening(Wall, XYZ, XYZ) даёт ровно один род.
            return ("OST_SWallRectOpening",)
        # variety="host_face": род определяет КАТЕГОРИЯ НОСИТЕЛЯ, а носитель —
        # id или ссылка, то есть из программы не читается. Сумма по трём
        # родам, которые эта перегрузка вообще умеет («Creates a new opening
        # in a roof, floor and ceiling» — документация метода, а не догадка о
        # модели). Потолочный проём в переписи восьми зданий не встретился ни
        # разу; он здесь потому, что его умеет ОПЕРАЦИЯ.
        return ("OST_FloorOpening", "OST_RoofOpening", "OST_CeilingOpening")
    if name == "create_topography":
        # Закрытое перечисление самого опа, поэтому категория известна ТОЧНО,
        # и это важнее удобства: поверхность и толща — РАЗНЫЕ категории, и
        # сумма по двум ключам скрыла бы ровно ту подмену, ради запрета
        # которой у операции вообще появилась разновидность.
        return (("OST_Toposolid",) if op.get("variety") == "toposolid"
                else ("OST_Topography",))
    if name == "create_foundation":
        if op.get("variety") == "isolated":
            # Символ грунтуется пулом foundation_symbols — это
            # FilteredElementCollector(...).OfCategory(OST_StructuralFoundation)
            # (open_model.py), значит категория известна точно.
            return ("OST_StructuralFoundation",)
        # variety="slab" эмитируется через Floor.Create с типом из пула
        # floor_types: перекрытие это или фундаментная плита — решает ТИП,
        # которого компилятор не видит.
        return ("OST_Floors", "OST_StructuralFoundation")
    return OP_RESULT_CATEGORIES.get(name)



def op_census_categories(ospec: OpSpec) -> tuple[str, ...]:
    """ВСЕ категории переписи, куда результат опа может попасть.

    Берётся у `op_result_categories` ВЫШЕ, в этом же файле. До 10.08 ответ
    брался у судьи приёмки (`acceptance._category_of_op`) — реестр спрашивал
    категорию у своего потребителя; теперь таблица живёт здесь, а приёмка
    читает её отсюда.

    У части опов категория зависит от ЗАКРЫТОГО перечисления самого опа
    (`category` у колонны и меша, `variety` у проёма, рельефа, фундамента).
    Перечисление лежит в реестре (`ParamSpec.choices`), поэтому здесь не
    гадают, а перебирают его целиком и объединяют ответы: раздел опа обязан
    быть верен при ЛЮБОМ разрешённом значении, иначе это не раздел опа.

    Пусто — значит судья категории не знает; таких опов сегодня 18 из 58, и
    почти все они правят чужие элементы (`set_param`, `delete`, `move_
    elements`, `change_type`) либо создают не элемент, а тип/семейство.
    """
    from itertools import product

    axes = [[(p.name, choice) for choice in p.choices]
            for p in ospec.params
            if p.name in ("category", "variety") and p.choices]
    found: set[str] = set()
    for combo in (product(*axes) if axes else [()]):
        probe: dict[str, object] = {"op": ospec.name}
        probe.update(dict(combo))
        cats = op_result_categories(probe)
        if cats:
            found.update(cats)
    return tuple(sorted(found))


def op_disciplines(ospec: OpSpec) -> tuple[tuple[str, ...], str]:
    """Разделы опа и — если раздел вывести НЕЛЬЗЯ — причина словами.

    Цепочка вывода целиком: оп -> категории переписи (судья приёмки) ->
    раздел (носители `registry_base.DISCIPLINES`). Ни одного шага рукой: раздел
    нового опа появляется сам, как только у него появляется строка у судьи, и
    ошибиться в нём по памяти негде.

    Три исхода, и каждый назван:

    * категории известны и все ведут в один-два раздела -> эти разделы;
    * среди них есть `shared` -> ТОЛЬКО `shared`: `shared` в этом словаре
      значит «принадлежит всем», и дублировать такой оп по разделам значило бы
      платить за него пять раз;
    * вывести НЕЛЬЗЯ -> ПУСТО и причина. Пусто, а не `shared`: словарь разделов
      говорит про `shared` прямым текстом, что это «принадлежит всем», а НЕ
      «неизвестно» (`registry_base`, шапка `DISCIPLINES`). Свалить сюда
      невыведенное значило бы утверждать про `create_truss`, что он общий для
      всех разделов, — то есть заменить пробел учёта уверенным враньём, ровно
      тем классом, против которого писан весь этот пакет.
    """
    # ПРАВИЛО ЭФФЕКТА, И ОНО ТОЖЕ ИЗ РЕЕСТРА. Оп, который не СОЗДАЁТ, работает
    # по чужому элементу — его положил кто-то другой, и раздела своего у такого
    # опа нет по построению: `set_param` правит и стену, и трубу, и щит.
    # Это ровно то, что словарь называет `shared` («принадлежит всем»), а не
    # пробел учёта, поэтому причины здесь нет и быть не должно.
    if ospec.effect is not EffectKind.CREATE:
        return ("shared",), ""
    table = _category_disciplines()
    cats = op_census_categories(ospec)
    if not cats:
        return (), "судья приёмки не знает категории результата"
    known = {table[c] for c in cats if c in table}
    if not known:
        return (), ("категории " + ", ".join(cats)
                    + " не значатся ни у одного носителя словаря разделов")
    if "shared" in known:
        return ("shared",), ""
    return tuple(sorted(known)), ""


def ops_by_discipline(*, writes: bool | None = None
                      ) -> list[tuple[str, list[str]]]:
    """Имена опов, сгруппированные ПО РАЗДЕЛАМ ПРОЕКТА.

    ОДНА группировка на двух читателей — ровно та же причина, по которой здесь
    живёт `ops_by_object_kind`: описание инструмента печатает её в ПРОМПТ
    (`tool_doc`), `course.spec()` — в КВИТАНЦИЮ по запросу, и две копии
    разошлись бы на первом же новом опе молча.

    ЧЕМ ЭТО ЛУЧШЕ ГРУППИРОВКИ ПО `capability`, КОТОРАЯ СТОЯЛА ЗДЕСЬ ДО 09.08.
    Та печатала внутреннее поле реестра: `element`, `element/mep_system`,
    `category/element: create_column, create_wall`, `room_space`. Автор не
    может этим пользоваться — из текста не следует, почему `create_wall`
    отделён от `create_floor`, а ответ был в том, что компиляторное поле
    протекло на поверхность. РАБОТУ ВЕДУТ РАЗДЕЛАМИ, у каждого свой
    исполнитель; перегруппировка тех же имён стоит НОЛЬ символов.

    Оп с двумя разделами (колонна — АР и КР) стоит в ОБОИХ: автор раздела КР
    ищет, что ему можно строить, и отсутствие колонны в его списке — потеря,
    а не экономия. Сумма длин групп поэтому больше числа опов.

    Опы, у которых раздел вывести НЕ УДАЛОСЬ, сюда не попадают вовсе — их
    отдаёт `ops_without_discipline()`, и печатать их надо отдельным заголовком.
    Смешать их с `shared` значит соврать (см. `op_disciplines`).
    """
    groups: dict[str, list[str]] = {}
    for name, op in sorted(OPS.items()):
        if writes is not None and op.writes_model is not writes:
            continue
        for discipline in op_disciplines(op)[0]:
            groups.setdefault(discipline, []).append(name)
    return [(d, groups[d]) for d in DISCIPLINE_ORDER if d in groups]


def ops_without_discipline(*, writes: bool | None = None
                           ) -> list[tuple[str, str]]:
    """Опы, у которых раздел вывести нельзя, — с ПРИЧИНОЙ у каждого.

    Пара к `ops_by_discipline`: вместе они покрывают реестр без остатка, и это
    держит тест. Пробел учёта, названный вслух, закрывается; пробел, ссыпанный
    в `shared`, живёт вечно и выглядит как факт.
    """
    rows: list[tuple[str, str]] = []
    for name, op in sorted(OPS.items()):
        if writes is not None and op.writes_model is not writes:
            continue
        disciplines, why = op_disciplines(op)
        if not disciplines:
            rows.append((name, why))
    return rows


def export_capability_cells() -> list[dict]:
    """The cube s covered-by-IR feed (SPEC §3 / arbitration Q5)."""
    cells = []
    for op in OPS.values():
        for action, object_kind in op.capability:
            cells.append({
                "action": action,
                "object_kind": object_kind,
                "status": "covered-by-IR",
                "ir_op": op.name,
                "ir_version": IR_VERSION,
            })
    for action, route in ROUTE_ONLY_ACTIONS.items():
        cells.append({"action": action, "object_kind": "*",
                      "status": "route-only", "route": route})
    return cells
