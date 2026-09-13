"""KIR authoring family — deterministic emit (SPEC §4A, 12.5, 11.2).

Typed input normalization lives in :mod:`kir.authoring_validation` and is
re-exported here for the historical compiler API.

Emit contract (the create_element bricks, generalized to programs):
  * ONE Transaction per program; rollback-on-catch; every grounded ref gets an
    in-emit null-guard -> RollBack + typed stale result (model drift between
    ground and execute leaves ZERO trace).
  * STAMP: deterministic op stamp `kir:<program-sha1-8>:<op_id>` written to
    ALL_MODEL_INSTANCE_COMMENTS inside the same transaction (idempotency key;
    deterministic so goldens stay byte-stable).
  * IN-TXN COMMIT-GATE (12.5): after all creates, doc.Regenerate(), then every
    op's postconditions (geometry ±tol AND topology: level/host bindings —
    §11.4 day-one) are checked against the live regenerated document; ANY
    violation -> RollBack + typed result. A partially-wrong program is
    unexpressible as a committed outcome.
  * WITNESS: post-commit readback per op (id, endpoints mm, type/level names)
    — the truth record, independent of the create call's echo.

Version axis (11.2): creation APIs (Wall.Create / Plumbing.Pipe.Create /
Grid.Create) are stable 2021-2026; the live divergence is ElementId literals —
64-bit ids exist only since 2024. Dialect stays C# 7.3 (.NET 4.8 ceiling).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from kir import spec, docspace, faceref, ops_room
from kir import geom as _geom
from kir.ops_authoring import WALL_LOCATION_LINE_ORDINALS

from kir.contracts import ElementIdentityProof
from kir.emit_model import (BarePost, WitnessCheck, render_staged_post,
                                 tolerance, tolerances)
from kir.diag import (Diagnostic, KirRefusal, PLAN_SOLO_OP, TYPE_BAD_TYPE,
                           GROUND_BAD_SELECTOR, PARSE_EXCLUSIVE_FIELDS,
                           EMIT_UNSUPPORTED)
from kir.ground import IN_EMIT_DEFAULT
from kir.emit_utils import (
    ELEMENT_ID_MAX,
    cs_element_id_literal,
    cs_identifier_fragment,
    cs_line_comment_fragment,
    cs_string_literal,
    failure_channel_reset_cs,
    failure_preprocessor_cs,
    failure_warnings_into_results_cs,
    program_refusal_tokens,
    refuse_stmt,
)

# Внутренний контракт эмиссии, не пользовательский ввод: op-локальный гард,
# написанный мимо emit_utils.refuse_stmt(), уносит семантику ЦЕЛОЙ программы
# внутрь SubTransaction.  Своя буква намеренно вне занятого разбором
# диапазона KIR-P001…P007 (ревью кодекса №11); отказ несёт вид опа, его id
# и функцию-источник — без источника такой отказ нечего чинить.
EMIT_GUARD_CONTRACT = "KIR-E005"



# Validation lives behind a typed, emitter-free boundary.  Re-export the
# historical names from this module so compiler/tests and external KIR users
# keep the same import contract while dependencies flow validator -> emitter.
from kir.authoring_validation import (
    PLACE_FAMILY_WORK_PLANE_UNSUPPORTED,
    _ARC_ENDPOINT_TOL_MM,
    _COORD_LIMIT_MM,
    _arc_endpoints_mm,
    _dist,
    _num,
    _pt_ok,
    _sel_shape_ok,
    _target_w_ok,
    _validate_arc,
    validate,
)

# 🔴 ЯДРО ЭМИССИИ ПЕРЕЕХАЛО В `kir.emit_core` (02.09.2026), А ЗДЕСЬ ОСТАЛСЯ
# РЕЭКСПОРТ. Довод целиком — в шапке того файла; коротко: 17 спутников из 19
# тянули эти имена ОТСЮДА на уровне модуля, а хаб тянул спутники ЛЕНИВО, 41
# импортом в 41 обёртке, и ленивость прятала ЦИКЛ. Пока кольцо было, `_EMITTERS`
# обязан был оставаться рукописным.
#
# Реэкспорт НЕ временный и не из вежливости: `from kir.authoring import _cs`
# написано в семнадцати файлах и в чужих деревьях, и переименование стоило бы
# больше, чем даёт. Носитель при этом ОДИН — определения живут в `emit_core`.
from kir.emit_core import expected_identity_check  # noqa: F401
from kir.emit_core import (  # noqa: F401
    EMIT_ID_RANGE, MODEL_BINDING_GUARD_VERSION, _AUTH_PREAMBLE, _CLASS_NAME_HELPER_CS,
    _GRID_OCC_HELPER_CS, _MESH_CANON_HELPER_CS, _annot_view_res, _cs,
    _document_binding_guard, _eid, _element_identity_guard, _endpoint_check,
    _gid, _indent, _level_chain_check, _level_check_expr,
    _level_expr, _loop_pts, _program_stamp, _pt3,
    _readback_block, _safe, _split_witness, _stamp_block,
    _stamp_readback, _symbol_res, _target_res, _with_class_name_helper,
    _with_grid_occ_helper, _with_mesh_canon_helper, _with_program_helpers, bbox_extents_witness,
    canon_unit, curve_ring_payload_cs, element_identity_readback_cs, endpoint_witness,
    final_shift, level_binding_witness,
    program_tail_writes, render_tail_adjusted_post,
    level_chain_witness, loops_payload_expected, loops_verdict_cs, path_points_witness,
    profile_loops_witness, program_hash, sketch_loops_witness, spline_points_witness,
    type_assignment_declarations, type_assignment_witness, type_assignment_readback_cs,
)



# ── emit ─────────────────────────────────────────────────────────────────────








































# ── Wave A2: witness-model wrappers over the string helpers ─────────────────
# Each wrapper partitions the legacy fragment at its first newline (reader
# statement vs guard+verdict) and pins the surrounding glue (lead indent /
# trailing newline) INSIDE the check, so render_post's concatenation is
# byte-identical to the historical hand-built post block.







# ── ЧТО ПЛАНОВЫЕ СВИДЕТЕЛИ ДЕЛАЮТ НА НАКЛОННОЙ ПЛОСКОСТИ (21.08.2026) ──────
#
# Волна плоскости эскиза (`plane.py`) обязана была ответить на этот вопрос
# ДО первой строки кода, потому что наклонная плоскость обесценивает всякого
# свидетеля, который меряет В ПЛАНЕ. Ответ по каждому — здесь, и он ОДИН И ТОТ
# ЖЕ, но не потому, что вопрос неважен, а потому, что род `plane` до этих
# свидетелей НЕ ДОХОДИТ, и это решение с доводом.
#
# ГЕОМЕТРИЧЕСКИХ СВИДЕТЕЛЕЙ, МЕРЯЮЩИХ В ПЛАНЕ, ПЯТЬ, А НЕ ТРИ:
#
#   bbox_extents_witness     габарит по X и Y (Z не смотрит вовсе)
#   sketch_loops_witness     кольца на ПЛАНОВОЙ решётке канона
#   profile_loops_witness    то же для профиля без эскиза (BeamSystem)
#   path_points_witness      то же для открытой ломаной (Railing)
#   spline_points_witness    ЕДИНСТВЕННЫЙ, кто наклон уже НАЗЫВАЛ:
#                            «эскиз не горизонтален — свидетель кривой здесь
#                            неприменим». Прецедент верного поведения.
#
# ВСЕ ПЯТЬ ОБЯЗАНЫ ДЕЛАТЬ РОВНО ТО ЖЕ, ЧТО ДЕЛАЮТ, И ВОТ ПОЧЕМУ. Их носители —
# АР-опы: плита, кровля, потолок, площадка, система балок, ограждение. Ни один
# из них не получил рода `plane` и не получит: у `Floor.Create`,
# `Ceiling.Create` и `Roof` эскиз кладёт САМ Revit — на уровень, — а уклон
# задаётся стрелкой уклона, отдельным механизмом со своей семантикой. Дать им
# `plane` значило бы пообещать степень свободы, которой у построенного элемента
# нет: то же враньё, что категория стены у меша, только тише.
#
# ЧЕЙ СВИДЕТЕЛЬ ДЕЙСТВИТЕЛЬНО СТОЯЛ НА ПУТИ 73 ОСВОБОЖДЁННЫХ ФОРМ — ДРУГОЙ, и
# он живёт в `solid_emit.py`, потому что четыре объёмные операции кладут тело в
# DirectShape и настоящего эскиза Revit у них нет вовсе:
#
#   _solid_count_check   ИНВАРИАНТЕН: считает тела, рамке безразличен;
#   _volume_check        ИНВАРИАНТЕН ДОКАЗУЕМО: рамка плоскости — ДВИЖЕНИЕ
#                        (правая ортонормированная тройка), а движение
#                        сохраняет объём. По той же причине не меняются
#                        площадь поверхности и периметр, из которых выведены
#                        допуски;
#   _cap_area_check      ИЗМЕНЁН: торцы ищутся по нормали ПЛОСКОСТИ, а не по
#                        мировой Z. Разделение осталось ТОЧНЫМ — довод в шапке
#                        `_AXIS_COS_EPS` был про ось выдавливания, а не про
#                        вертикаль;
#   _bbox_check          ИЗМЕНЁН: эталон считается опорной функцией профиля,
#                        положенного на плоскость (`_plane_profile_box`), и
#                        остаётся ТОЧНЫМ для дуги — закон дуги при этом не
#                        скопирован, а ОБОБЩЁН (`contour.extreme_candidates`,
#                        из неё же выведен плановый `edges_bbox`);
#   _profiles_on_boundary_check  ИЗМЕНЁН у бленда: объявленные вершины едут
#                        туда, куда их кладёт рамка.
#
# 🔴 НИ ОДНО ОБЯЗАТЕЛЬСТВО НЕ СНЯТО И НИ ОДИН ДОПУСК НЕ РАСТЯНУТ. Форма 46
# требует снимать и НАЗЫВАТЬ, когда ось недоказуема; здесь она доказуема —
# потому что рамка плоскости есть движение, а не деформация, и все величины,
# которыми мерили, к движению инвариантны либо переносятся вместе с ним.














def path_points_payload_expected(path, grid) -> str:
    """Подпись ОТКРЫТОГО пути: порядок вершин ЗНАЧИМ (F-342).

    🔴 ЗАЧЕМ ОТДЕЛЬНАЯ ФУНКЦИЯ, А НЕ ПРАВКА КОЛЬЦЕВОГО КАНОНИЗАТОРА.
    `loops_payload_expected` обслуживает ЗАМКНУТЫЕ контуры (потолок, плита,
    система балок, площадка), где сортировка законна: у кольца нет выделенного
    начала, и любая вершина равноправна. У ОТКРЫТОГО пути связность — часть
    смысла, и сортировка её стирает. Тронуть общий канонизатор значило бы
    сломать четыре законных площадки ради пятой.

    ЧТО ИМЕННО СТИРАЛОСЬ, АЛГЕБРАИЧЕСКИ. Свидетель брал ОБА конца каждого
    сегмента и сортировал всё одним мультимножеством. Путь A-B-C-D и путь
    A-C-B-D имеют общие концы (A, D) и общие внутренние (B, C), значит дают
    ПОБАЙТОВО ОДНУ подпись — независимо от координат. Свидетель мог
    подтвердить ЧУЖОЙ связный путь.

    ИНВАРИАНТНОСТЬ РОВНО ОДНА, И ОНА ЗАКОННАЯ: разворот пути ЦЕЛИКОМ.
    `Railing.GetPath()` вправе вернуть ломаную в противоположном глобальном
    направлении, и это ТА ЖЕ постройка. Поэтому берётся `min(вперёд, назад)` —
    выбор детерминированный, но НЕ сортирующий вершины. Перестановка
    внутренних вершин инвариантностью НЕ является и обязана менять подпись.

    🔴 ФУНКЦИЯ СЕГОДНЯ ИНЕРТНА — ЕЁ НИКТО НЕ ЗОВЁТ, И ЭТО НАРОЧНО (F-342).
    Свидетель сверяет ПИТОНОВСКОЕ ожидание с ЧИСЛОМ, посчитанным в C# на
    исполнении. Обе половины сегодня сортируют ОДИНАКОВО, поэтому подключить
    одну эту функцию, не заменив C#-половину, значит развести их: измерено
    исполнением, ожидание и C# расходятся на ЛЮБОМ пути, включая законный
    прямой —

        путь [(0,0),(10000,0),(10000,10000),(20000,10000)]
            C# посчитает : 0,0|10000,0|10000,0|10000,10000|10000,10000|20000,10000
            эта функция  : 0,0|10000,0|10000,10000|20000,10000

    — то есть `__post.Count > 0` и `__t.RollBack()` ВСЕЙ программы на ВЕРНОЙ
    геометрии, с обвинением автора в чужой ошибке. Ровно та беда, память о
    которой хранит докстрока `path_points_witness` (24.08.2026).

    C#-половина (сцепление кривых `GetPath()` в упорядоченную цепь) — предмет
    ОТДЕЛЬНОГО хода: её правильность есть утверждение о поведении ЖИВОГО
    `GetPath()`, а ворота 6/6 доказывают компиляцию, а не поведение. Пока того
    хода нет, свидетель продолжает звать кольцевой канонизатор, и слепота к
    порядку СОХРАНЯЕТСЯ — названная, а не забытая.
    """
    g = float(getattr(grid, "value", grid))
    forward = "|".join("%d,%d" % (canon_unit(x, g), canon_unit(y, g))
                       for x, y in path)
    backward = "|".join("%d,%d" % (canon_unit(x, g), canon_unit(y, g))
                        for x, y in reversed(path))
    return min(forward, backward)










def _arc_curve_cs(arc: dict) -> str:
    """Arc.Create(...) built with authoring's U/V macros, mirroring
    decompile.recompile._curve_cs's Arc branch. center is a world-mm point, the
    axes are unit vectors, angles are radians — exactly recompile.ArcCurve."""
    c = arc["center_mm"]
    xa = arc["x_axis"]
    ya = arc["y_axis"]
    return (
        f"Arc.Create(P({c[0]}, {c[1]}, {c[2]}), U({arc['radius_mm']}), "
        f"{arc['start_angle_rad']}, {arc['end_angle_rad']}, "
        f"new XYZ({xa[0]}, {xa[1]}, {xa[2]}), new XYZ({ya[0]}, {ya[1]}, {ya[2]}))")


def _emit_wall(op: dict, ver: str, stamp: str,
               isolation: str = "atomic") -> tuple[str, str, str, str]:
    oid = op["id"]
    s = _safe(oid)
    lv = _gid(op, "level")
    g_type = _gid(op, "type") if isinstance(op.get("type"), dict) and "__grounded__" in op["type"] else None
    h = op.get("height_mm", spec.DEFAULTS["wall"]["height_mm"])
    x0, y0, _ = _pt3(op["p0_mm"])
    x1, y1, _ = _pt3(op["p1_mm"])
    arc = op.get("arc")
    decl = f"Wall __el_{s} = null;\n" + type_assignment_declarations(oid)
    # Э3.1: имена выведенного габарита живут в decl — `__lv_`/`__tl_` объявлены
    # внутри create и при обёртке per_op умирают на скобке (CS0103). Тот же
    # контракт, что у колонны и у оси наклонной колонны.
    # `op.get`, а не локальная `top`: она присваивается на 45 строк НИЖЕ, и
    # чтение её здесь давало UnboundLocalError -> KIR-P000 «внутренняя ошибка
    # компилятора» на каждой стене. Поймано точечными тестами за один прогон.
    _w_top = op.get("top_level")
    if isinstance(_w_top, dict) and "__grounded__" in _w_top:
        decl += f"\ndouble __wexLo_{s} = 0.0;\ndouble __wexHi_{s} = 0.0;"
    if g_type and g_type.get("in_emit") == IN_EMIT_DEFAULT:
        # deterministic doc-default rule, echoed later in readback type_name
        wt = (f"WallType __wt_{s} = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;\n"
              f"if (__wt_{s} == null) {{ {refuse_stmt(oid, _cs('в документе нет типа стены по умолчанию'), isolation)} }}")
    elif g_type.get("via") == "ref":
        # ТИП, СОЗДАННЫЙ ЭТОЙ ЖЕ ПРОГРАММОЙ (`create_wall_type`). Ни
        # `GetElement`, ни сторож дрейфа здесь не нужны и были бы ложью:
        # элемент создан несколькими строками выше, в этой же транзакции, и
        # его переменная уже держит нужный род. Тот же приём и тот же довод,
        # что у `_level_expr` для `create_level`.
        wt = f"WallType __wt_{s} = __el_{_safe(g_type['ref'])};"
    else:
        wt = (f"WallType __wt_{s} = doc.GetElement({_eid(g_type['id'], ver, oid)}) as WallType;\n"
              f"if (__wt_{s} == null) {{ {refuse_stmt(oid, _cs('тип стены не найден (модель изменилась после grounding)'), isolation)} }}")
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    # Vertical attributes (audit F6).  Both OPTIONAL: with neither present the
    # whole emission below is byte-identical to the pre-existing wall (goldens
    # must not move).  base_offset_mm -> WALL_BASE_OFFSET.Set after
    # Wall.Create (the Create call itself stays byte-stable); top_level ->
    # the wall top is ATTACHED to that level: WALL_HEIGHT_TYPE = level id and
    # WALL_TOP_OFFSET = 0.
    #
    # height_mm's ±1mm witness used to stay UNCONDITIONAL, on the theory that
    # it doubled as a consistency check between a requested height and an
    # attached top constraint.  Live witness telemetry (29.07.2026, two
    # facade programs — 4 walls + 5 floors, then 16 walls, every wall
    # reporting "height mismatch") disproved that: height_mm carries a
    # registry DEFAULT (DEFAULTS["wall"]["height_mm"] = 3000.0mm), and
    # validate()'s "mm"-kind branch fills that default into `norm` for EVERY
    # omitted height_mm before the emitter ever sees the op (`v = op.get(
    # p.name, p.default)`) — there is no way, at this point, to tell "caller
    # asked for exactly 3000mm" apart from "caller said nothing and let
    # top_level decide the span".  A caller building a facade wall between
    # two levels naturally omits height_mm; the compiler then silently
    # promised the built element would measure exactly 3000mm and rolled
    # back every wall whose real (correctly-built) storey height differed.
    # WALL_USER_HEIGHT_PARAM ("Unconnected Height") also stops being the
    # authoritative height source the moment a top constraint is attached —
    # Revit itself derives the built height from the base/top level pair, not
    # from whatever was passed to Wall.Create. So when top_level is given,
    # the height witness is skipped: the vertical extent is already fully
    # pinned by two OTHER checks — "top constraint == resolved top_level"
    # below (topology) and the "верх стены не выше подошвы" guard above
    # (a real contradiction, e.g. top below base, still refuses before
    # commit, just not via a fabricated height literal).
    base_offset = op.get("base_offset_mm")
    top = op.get("top_level")
    # location_line -> WALL_KEY_REF_PARAM, set AFTER Wall.Create (there is no
    # creation-time overload for it).  The ordinals are Revit's WallLocationLine
    # enum; the schema spells them in words so the program is readable and
    # language-neutral, and the mapping lives here alone.  What the rule does
    # and does not do is measured — see the block above the Wall.Create call.
    location_line = op.get("location_line")
    loc_set = ""
    if location_line is not None:
        loc_set = (
            f"\nParameter __ll_{s} = __el_{s}.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM);\n"
            f"if (__ll_{s} == null || __ll_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('WALL_KEY_REF_PARAM недоступен у стены'), isolation)} }}\n"
            f"__ll_{s}.Set({WALL_LOCATION_LINE_ORDINALS[location_line]});")
    base_set = ""
    if base_offset is not None:
        base_set = (
            f"\nParameter __bo_{s} = __el_{s}.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET);\n"
            f"if (__bo_{s} == null || __bo_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('WALL_BASE_OFFSET недоступен у стены'), isolation)} }}\n"
            f"__bo_{s}.Set(U({base_offset}));")
    top_res = ""
    top_set = ""
    top_idexpr = None
    if isinstance(top, dict) and "__grounded__" in top:
        tl = _gid(op, "top_level")
        if tl.get("via") == "ref":
            rv = "__el_" + _safe(tl["ref"])
            top_res = f"\nLevel __tl_{s} = {rv};"
            top_idexpr = f"{rv}.Id.ToString()"
        else:
            top_res = (
                f"\nLevel __tl_{s} = doc.GetElement({_eid(tl['id'], ver, oid)}) as Level;\n"
                f"if (__tl_{s} == null) {{ {refuse_stmt(oid, _cs('top_level: уровень не найден (модель изменилась после grounding)'), isolation)} }}")
            top_idexpr = _cs(str(tl["id"]))
        # Wall-fidelity (live A5 evidence 2026-07-21): the top offset is a
        # DEFINING DOF of the attach — forcing 0 made every offset-attached
        # wall rebuild at the full base->top span (canon miss by exactly
        # |offset|).  op top_offset_mm now flows into WALL_TOP_OFFSET; absent
        # keeps the historical ``Set(0.0)`` literal byte-exact.
        top_offset = op.get("top_offset_mm")
        to_literal = "0.0" if top_offset is None else f"U({top_offset})"
        # ОДНА НЕВОЗМОЖНАЯ СТЕНА НЕ ДОЛЖНА ВАЛИТЬ ВСЮ ПРОГРАММУ.
        # Пересборка настоящего здания 27.07: чанк из 250 опов откатился
        # ЦЕЛИКОМ на «Верх стены находится ниже, чем подошва стены» — Revit
        # отвечает ошибкой уровня ERROR, и она уносит транзакцию. Отметки
        # уровней компилятору недоступны (в снапшоте только id и имя), поэтому
        # проверка живёт здесь, где обе отметки уже разрешены. В режиме per_op
        # это отказ ОДНОГО опа, соседи коммитятся; в atomic — честный
        # типизированный откат вместо невнятного RolledBack.
        base_off_expr = f"U({base_offset})" if base_offset is not None else "0.0"
        top_guard = (
            f"\nif ({{0}}.Elevation + {to_literal} <= __lv_{s}.Elevation + {base_off_expr})\n"
            f"{{{{ {refuse_stmt(oid, _cs('верх стены не выше подошвы: привязка верха невозможна'), isolation)} }}}}"
        ).format(f"__tl_{s}")
        top_set = (
            top_guard +
            f"\nParameter __ht_{s} = __el_{s}.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE);\n"
            f"if (__ht_{s} == null || __ht_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('WALL_HEIGHT_TYPE недоступен у стены'), isolation)} }}\n"
            f"__ht_{s}.Set(__tl_{s}.Id);\n"
            f"try {{ Parameter __to_{s} = __el_{s}.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET); "
            f"if (__to_{s} != null && !__to_{s}.IsReadOnly) __to_{s}.Set({to_literal}); }} catch {{ }}")
    # Curve-IR (P4-B): an arc dict swaps Line.CreateBound for Arc.Create; the
    # rest of Wall.Create (type/level/height) is unchanged. Absent -> the exact
    # pre-existing straight-wall emission (byte-stable golden).
    curve_expr = (_arc_curve_cs(arc) if arc is not None
                  else f"Line.CreateBound(P({x0}, {y0}, 0), P({x1}, {y1}, 0))")
    # MEASURED 2026-07-26, and it cost a bad guess to learn: Wall.Create's
    # sixth argument is the wall's BASE offset from its level -- vertical --
    # not a plan offset from the curve.  Passing half the type width there
    # raised one wall 100mm and dropped another 100mm (WALL_BASE_OFFSET read
    # back as +100 / -100) while both bodies stayed dead-centred on their
    # curves in plan.  Silent elevation corruption that no postcondition
    # caught, because the endpoint check only looks at the plan.
    #
    # WALL_KEY_REF_PARAM was measured too, twice, and the second measurement
    # (2026-07-28, docs/2026-07-28-location-line-measurement.md) settled the
    # question this comment used to leave open.  It does NOT describe an offset
    # the wall already has: the LocationCurve Revit's API returns is the CENTRE
    # plane of the body under every ordinal -- checked by solid tessellation on
    # 724 real walls of the operator's facade model, faces at exactly -w/2 and
    # +w/2.  What the rule decides is which plane STAYS PUT when the thickness
    # later changes: swap a 200 mm type for a 400 mm one under ordinal 2 and
    # the exterior face holds while the curve itself slides 100 mm to the new
    # centre.
    #
    # So shifting p0/p1 by factor*width would not "realise the effect" -- it
    # would CREATE a displacement.  A wall rebuilt on the curve the decompiler
    # read lands exactly on the original (measured end to end on a real
    # ordinal-2 wall); shifted, it would land half a thickness away, and the
    # lift could not compensate because decompile/extract.py never captures a
    # wall's width at all.  The plan offset therefore stays ZERO for every
    # location_line, and the rule travels as what it is: semantic state.
    offset_expr = "0.0"
    create = (
        f"// create_wall {cs_line_comment_fragment(oid)}\n{wt}\n"
        + lv_res + top_res + "\n"
        f"__el_{s} = Wall.Create(doc, {curve_expr}, "
        f"__wt_{s}.Id, __lv_{s}.Id, U({h}), {offset_expr}, false, false);\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('Wall.Create вернул null'), isolation)} }}"
        + loc_set + base_set + top_set + "\n"
        + ((f"__wexLo_{s} = MM(__lv_{s}.Elevation)"
            + ("" if base_offset is None else f" + {base_offset}") + ";\n"
            f"__wexHi_{s} = MM(__tl_{s}.Elevation)"
            + ("" if op.get("top_offset_mm") is None
               else f" + {op['top_offset_mm']}") + ";\n")
           if top_idexpr is not None else "")
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # Curve-IR (P4-B): a curved wall must actually commit as an Arc with the
    # requested centre/radius, not a flattened line — surfaced as a typed
    # postcondition (reported, never a silent straight wall). The endpoint check
    # already covers p0/p1 for both shapes.
    # Wave A2: the post block is a list of WitnessCheck objects; render_post
    # reproduces the historical bytes (frame + fragment glue pinned in each
    # check).  Tolerances come from the registry (same numbers as before).
    tol = tolerances("create_wall")
    checks: list[WitnessCheck] = [
        type_assignment_witness(f"__el_{s}", f"__wt_{s}", oid),
        # 🔴 ИТОГ, А НЕ ЗАМЫСЕЛ (E-2, 07.09.2026). Свидетель финальной стадии
        # исполняется ПОСЛЕ всей программы, поэтому сверять он обязан с тем,
        # где стена ОКАЖЕТСЯ, а не откуда её начали. Сдвиг приделан
        # `emit_program` из `geom.program_shift_after`; при пустом сдвиге поля
        # нет и байты прежние. Довод целиком — у `spec.SYNTHETIC_FINAL_SHIFT`.
        endpoint_witness(
            f"__el_{s}", oid, op["p0_mm"], op["p1_mm"],
            tol["endpoint_mm"], False, shift=final_shift(op)),
    ]
    if arc is not None:
        c = arc["center_mm"]
        atol = tol["arc_mm"]
        checks.append(WitnessCheck(
            obligation_key="arc",
            reader_cs=f"    var __lca = __el_{s}.Location as LocationCurve;\n",
            verdict_cs=(
                # 🔴 ПОМЕТКА ОСИ ЗДЕСЬ ОТСУТСТВОВАЛА ВОВСЕ (правка 22.08.2026),
                # и оба сообщения дуги уезжали в СЕМАНТИКУ: `_axes_from_
                # violations` раскладывает нарушение по пометке в строке, а без
                # неё всё непомеченное — семантика. То есть дуговая стена с
                # неверным центром отчитывалась `geometry_ok: True`, а красной
                # становилась чужая ось. Стен в MNVNK 7 845.
                f"    if (__lca == null || !(__lca.Curve is Arc))\n"
                f"        __post.Add({_cs(oid + ': arc requested but wall is not an Arc (geometry)')});\n"
                f"    else\n    {{\n"
                f"        var __arc = (Arc)__lca.Curve;\n"
                f"        if (Math.Abs(MM(__arc.Radius) - {arc['radius_mm']}) > {atol} ||\n"
                f"            Math.Abs(MM(__arc.Center.X) - {c[0]}) > {atol} ||\n"
                f"            Math.Abs(MM(__arc.Center.Y) - {c[1]}) > {atol})\n"
                f"            __post.Add({_cs(oid + ': arc center/radius mismatch (geometry)')});\n"
                f"    }}\n"),
            message="arc center/radius mismatch (geometry)",
            tol=atol,
            style="else_block"))
    checks.append(level_binding_witness(
        f"__el_{s}", oid, "WALL_BASE_CONSTRAINT", lv_idexpr))
    if top_idexpr is None:
        # WALL_USER_HEIGHT_PARAM is only meaningful — and only witnessed —
        # for an UNCONNECTED wall.  See the comment above top_res/top_set for
        # the live measurement (29.07.2026) that moved this check behind the
        # `top_idexpr is None` gate: once a top constraint is attached, this
        # parameter is no longer the source of truth, and height_mm is very
        # often a silently-defaulted 3000.0mm the caller never asked for.
        checks.append(WitnessCheck(
            obligation_key="height",
            reader_cs=(
                f"    var __hp = __el_{s}.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);\n"),
            verdict_cs=(
                f"    if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - {h}) > {tol['height_mm']})\n"
                f"        __post.Add({_cs(oid + ': height mismatch')});\n"),
            message="height mismatch",
            tol=tol["height_mm"],
            style="guard"))
    if base_offset is not None:
        checks.append(WitnessCheck(
            obligation_key="base_offset",
            reader_cs=(
                f"    var __bop = __el_{s}.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET);\n"),
            verdict_cs=(
                f"    if (__bop == null || Math.Abs(MM(__bop.AsDouble()) - {base_offset}) > {tol['base_offset_mm']})\n"
                f"        __post.Add({_cs(oid + ': base offset mismatch (geometry)')});\n"),
            message="base offset mismatch (geometry)",
            tol=tol["base_offset_mm"],
            style="guard"))
    if location_line is not None:
        # An enum ordinal, so the verdict is equality, not a tolerance: there
        # is no "close enough" plane.  SEMANTIC, and the axis is load-bearing
        # (§18.3): serving.py splits its geometry/topology/semantic triple on
        # exactly these substrings, and this witness reads back an ordinal the
        # emitter itself wrote.  The 2026-07-28 measurement showed that ordinal
        # moves neither curve nor body, so signing it "(geometry)" reported a
        # placement nobody had checked.  The wall's placement is discharged by
        # the endpoint witness above, which reads the LocationCurve Revit
        # returns — and per the same measurement that curve IS the whole truth
        # about where the body stands.
        checks.append(WitnessCheck(
            obligation_key="location_line",
            reader_cs=(
                f"    var __llp = __el_{s}.get_Parameter("
                f"BuiltInParameter.WALL_KEY_REF_PARAM);\n"),
            verdict_cs=(
                f"    if (__llp == null || __llp.AsInteger() != "
                f"{WALL_LOCATION_LINE_ORDINALS[location_line]})\n"
                f"        __post.Add({_cs(oid + ': location line mismatch (semantic)')});\n"),
            message="location line mismatch (semantic)",
            style="guard"))
    if top_idexpr is not None:
        checks.append(WitnessCheck(
            obligation_key="top_constraint",
            reader_cs=(
                f"    var __htp = __el_{s}.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE);\n"),
            verdict_cs=(
                f"    if (__htp == null || __htp.AsElementId() == null || __htp.AsElementId().ToString() != {top_idexpr})\n"
                f"        __post.Add({_cs(oid + ': top constraint mismatch (topology)')});\n"),
            message="top constraint mismatch (topology)",
            style="guard"))
        # 🔴 Э3.1: ГЕОМЕТРИЯ ПРОТИВ ССЫЛКИ, односторонне (`__post` откатывает).
        wspan = tol["vertical_span_mm"]
        checks.append(WitnessCheck(
            obligation_key="vertical_extent",
            reader_cs=(
                f"    var __wexBB_{s} = __el_{s}.get_BoundingBox(null);\n"),
            verdict_cs=(
                f"    if (__wexBB_{s} == null)\n"
                f"        __post.Add({_cs(oid + ': вертикальный габарит не прочитан (geometry)')});\n"
                f"    else\n    {{\n"
                f"        double __wexGot_{s} = MM(__wexBB_{s}.Max.Z) - MM(__wexBB_{s}.Min.Z);\n"
                f"        double __wexWant_{s} = __wexHi_{s} - __wexLo_{s};\n"
                f"        if (__wexGot_{s} < __wexWant_{s} - {wspan})\n"
                f"            __post.Add({_cs(oid + ': вертикальный габарит НЕ ДОХОДИТ до верхнего уровня (geometry)')});\n"
                f"    }}\n"),
            message="вертикальный габарит НЕ ДОХОДИТ до верхнего уровня (geometry)",
            tol=wspan,
            style="guard"))
        # Wall-fidelity (live A5 evidence 2026-07-21): explicit top offset must
        # hold on the committed wall — mirrors base_offset's conditional check.
        if op.get("top_offset_mm") is not None:
            checks.append(WitnessCheck(
                obligation_key="top_offset",
                reader_cs=(
                    f"    var __top = __el_{s}.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET);\n"),
                verdict_cs=(
                    f"    if (__top == null || Math.Abs(MM(__top.AsDouble()) - {op['top_offset_mm']}) > {tol['top_offset_mm']})\n"
                    f"        __post.Add({_cs(oid + ': top offset mismatch (geometry)')});\n"),
                message="top offset mismatch (geometry)",
                tol=tol["top_offset_mm"],
                style="guard"))
    readback = _readback_block(s, oid, stamp,
                               identity_version=ver,
                               extra_rows_cs=type_assignment_readback_cs(f"__el_{s}", oid),
                               vertical_extent=top_idexpr is not None,
                               extent_prefix="__wex")
    return decl, create, checks, readback


def _emit_pipe(op: dict, ver: str, stamp: str,
               isolation: str = "atomic") -> tuple[str, str, str, str]:
    oid = op["id"]
    s = _safe(oid)
    lv = _gid(op, "level")
    st = _gid(op, "system_type")
    pt = _gid(op, "pipe_type")
    x0, y0, z0 = _pt3(op["p0_mm"])
    x1, y1, z1 = _pt3(op["p1_mm"])
    d = op.get("diameter_mm")
    decl = f"Autodesk.Revit.DB.Plumbing.Pipe __el_{s} = null;"
    dia = ""
    if d is not None:
        dia = (f"\ntry {{ Parameter __dp_{s} = __el_{s}.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM); "
               f"if (__dp_{s} != null && !__dp_{s}.IsReadOnly) __dp_{s}.Set(U({d})); }} catch {{ }}")
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    create = (
        f"// create_pipe {cs_line_comment_fragment(oid)}\n"
        + lv_res + "\n"
        f"__el_{s} = Autodesk.Revit.DB.Plumbing.Pipe.Create(doc, {_eid(st['id'], ver, oid)}, "
        f"{_eid(pt['id'], ver, oid)}, __lv_{s}.Id, P({x0}, {y0}, {z0}), P({x1}, {y1}, {z1}));\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('Pipe.Create вернул null'), isolation)} }}"
        + dia + "\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # Wave A2 model post (glue: level check has no own newline; the diameter
    # fragment starts with one; the LAST fragment carries the final "\n").
    ptol = tolerances("create_pipe")
    checks: list[WitnessCheck] = [
        # ИТОГ ПОСЛЕДНЕГО ЗАКОННОГО ПИСАТЕЛЯ (E-3): тот же закон, что у
        # `create_wall` (E-2) — `emit_core.final_shift`, один читатель.
        endpoint_witness(f"__el_{s}", oid, op["p0_mm"], op["p1_mm"],
                         ptol["endpoint_mm"], True, shift=final_shift(op)),
        level_binding_witness(
            f"__el_{s}", oid, "RBS_START_LEVEL_PARAM", lv_idexpr,
            key="reference_level",
            tail=("" if d is not None else "\n")),
    ]
    if d is not None:
        checks.append(WitnessCheck(
            obligation_key="diameter",
            reader_cs=(f"\n    var __dp = __el_{s}.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);\n"),
            verdict_cs=(
                f"    if (__dp == null || Math.Abs(MM(__dp.AsDouble()) - {d}) > {ptol['diameter_mm']})\n"
                f"        __post.Add({_cs(oid + ': diameter mismatch')});\n"),
            message="diameter mismatch",
            tol=ptol["diameter_mm"],
            style="guard"))
    readback = _readback_block(s, oid, stamp, identity_version=ver)
    return decl, create, checks, readback


def _emit_grid(op: dict, ver: str, stamp: str,
               isolation: str = "atomic") -> tuple[str, str, str, str]:
    oid = op["id"]
    s = _safe(oid)
    x0, y0, _ = _pt3(op["p0_mm"])
    x1, y1, _ = _pt3(op["p1_mm"])
    nm = op.get("name")
    decl = f"Grid __el_{s} = null;"
    rename = ""
    if nm:
        rename = (f"\ntry {{ __el_{s}.Name = {_cs(nm)}; }}\n"
                  f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"имя сетки: \" + __ex_{s}.Message', isolation)} }}")
    create = (
        f"// create_grid {cs_line_comment_fragment(oid)}\n"
        f"__el_{s} = Grid.Create(doc, Line.CreateBound(P({x0}, {y0}, 0), P({x1}, {y1}, 0)));\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('Grid.Create вернул null'), isolation)} }}"
        + rename + "\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # Wave A2 model post.  Same glue discipline as create_level: the else
    # block historically ends `    }` with NO newline; nchk starts with one;
    # the LAST fragment carries the final "\n" before the frame "}".
    gtol = tolerance("create_grid", "endpoint_mm")
    checks: list[WitnessCheck] = [WitnessCheck(
        obligation_key="endpoints",
        reader_cs=f"    var __gc = __el_{s}.Curve;\n",
        verdict_cs=(
            f"    if (__gc == null) __post.Add({_cs(oid + ': нет Curve')});\n"
            f"    else\n    {{\n"
            f"        var __a = __gc.GetEndPoint(0); var __b = __gc.GetEndPoint(1);\n"
            f"        double __da = Math.Pow(MM(__a.X) - {x0}, 2) + Math.Pow(MM(__a.Y) - {y0}, 2);\n"
            f"        double __db = Math.Pow(MM(__b.X) - {x0}, 2) + Math.Pow(MM(__b.Y) - {y0}, 2);\n"
            f"        var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;\n"
            f"        if (Math.Abs(MM(__e0.X) - {x0}) > {gtol} || Math.Abs(MM(__e0.Y) - {y0}) > {gtol} ||\n"
            f"            Math.Abs(MM(__e1.X) - {x1}) > {gtol} || Math.Abs(MM(__e1.Y) - {y1}) > {gtol})\n"
            f"            __post.Add({_cs(oid + ': endpoints mismatch (geometry)')});\n"
            f"    }}" + ("" if nm else "\n")),
        message="endpoints mismatch (geometry)",
        tol=gtol,
        style="else_block")]
    if nm:
        checks.append(WitnessCheck(
            obligation_key="name",
            reader_cs="",
            verdict_cs=(f"\n    if (__el_{s}.Name != {_cs(nm)}) "
                        f"__post.Add({_cs(oid + ': name mismatch')});\n"),
            message="name mismatch",
            style="guard"))
    # Grid exposes Curve directly; unlike walls/MEPCurves it has no
    # LocationCurve.  Using the generic readback silently omitted both
    # endpoints even though the in-transaction postcondition checked them.
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    __rb[\"name\"] = __el_{s}.Name;\n"
        f"    try {{ var __gc2 = __el_{s}.Curve;\n"
        f"        if (__gc2 != null) {{\n"
        f"            var __s2 = __gc2.GetEndPoint(0); var __e2 = __gc2.GetEndPoint(1);\n"
        f"            __rb[\"start_mm\"] = new double[] {{ Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) }};\n"
        f"            __rb[\"end_mm\"] = new double[] {{ Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) }};\n"
        f"        }} }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback




def _emit_level(op: dict, ver: str, stamp: str,
                isolation: str = "atomic") -> tuple[str, str, str, str]:
    oid = op["id"]
    s = _safe(oid)
    elev = op["elev_mm"]
    nm = op.get("name")
    decl = f"Level __el_{s} = null;"
    rename = ""
    if nm:
        rename = (f"\ntry {{ __el_{s}.Name = {_cs(nm)}; }}\n"
                  f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"имя уровня: \" + __ex_{s}.Message', isolation)} }}")
    create = (
        f"// create_level {cs_line_comment_fragment(oid)}\n"
        f"__el_{s} = Level.Create(doc, U({elev}));\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('Level.Create вернул null'), isolation)} }}"
        + rename + "\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # Wave A2 model post.  Glue discipline (byte parity): the historical body
    # was `<elev check>` + nchk + "\n" — the elevation verdict carries NO
    # trailing newline when a name check follows (nchk starts with one), and
    # the LAST fragment always ends with the final "\n" before the frame "}".
    tol = tolerances("create_level")
    checks: list[WitnessCheck] = [WitnessCheck(
        obligation_key="elevation",
        reader_cs="",
        verdict_cs=(
            f"    if (Math.Abs(MM(__el_{s}.Elevation) - {elev}) > {tol['elevation_mm']})\n"
            f"        __post.Add({_cs(oid + ': elevation mismatch (geometry)')});"
            + ("" if nm else "\n")),
        message="elevation mismatch (geometry)",
        tol=tol["elevation_mm"],
        style="guard")]
    if nm:
        checks.append(WitnessCheck(
            obligation_key="name",
            reader_cs="",
            verdict_cs=(f"\n    if (__el_{s}.Name != {_cs(nm)}) "
                        f"__post.Add({_cs(oid + ': name mismatch')});\n"),
            message="name mismatch",
            style="guard"))
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    try {{ __rb[\"id\"] = __el_{s}.Id.ToString(); }} catch {{ __rb[\"id\"] = null; }}\n"
        f"    __rb[\"elevation_mm\"] = Math.Round(MM(__el_{s}.Elevation), 1);\n"
        f"    __rb[\"name\"] = __el_{s}.Name;\n"
        + element_identity_readback_cs(f"__el_{s}", revit_version=ver) +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


def _emit_floor_plan(op: dict, ver: str, stamp: str,
                     isolation: str = "atomic") -> tuple[str, str, list, str]:
    """План этажа для уровня — или он уже есть.

    ЗАЧЕМ ЭТОТ ОП СУЩЕСТВУЕТ, ОДНОЙ СТРОКОЙ: `create_level` плана не создаёт,
    а `NewRoomBoundaryLines` без вида не работает. Живой прогон 23.08 на K3:
    917 разделителей, и каждый ронял свою программу целиком.

    🔴 ПРАВИЛО ПОИСКА ЗДЕСЬ — ТО ЖЕ, ЧТО У РАЗДЕЛИТЕЛЯ, И ЭТО НЕ СОВПАДЕНИЕ.
    `room_emit._view_pick_cs` выбирает план так: `ViewPlan`, не шаблон,
    `ViewType.FloorPlan`, `GenLevel` — разрешённый уровень, наименьший Id.
    Оп, который создал бы вид, не проходящий этот фильтр, был бы ВЕРНЫМ И
    БЕСПОЛЕЗНЫМ. Поэтому и проверка «уже есть», и свидетель спрашивают ровно
    ту же тройку — а не похожую.

    ПОЧЕМУ `doc.Regenerate()` СРАЗУ ПОСЛЕ СОЗДАНИЯ. Общий `Regenerate` стоит
    ПОСЛЕ ВСЕХ создающих (шапка модуля, IN-TXN COMMIT-GATE), а разделитель
    ищет вид СВОИМ коллектором в фазе создания. Без локальной регенерации
    план, созданный соседней операцией той же программы, коллектору не виден,
    и оп чинил бы только следующую программу, но не свою.

    ИДЕМПОТЕНТНОСТЬ НЕ УКРАШЕНИЕ: план у уровня может уже быть (в целевом
    документе или от прошлого прогона). Тогда создавать второй — не ошибка
    Ревита, а тихий мусор, и постусловие «у уровня есть план» выполнено и без
    нас. Признак уходит в квитанцию (`already_present`), чтобы «нашли» и
    «построили» не слились в одно.

    ТИП ВИДА — СОБСТВЕННЫЙ ОТВЕТ ДОКУМЕНТА (`GetDefaultElementTypeId`), а не
    наш выбор среди кандидатов: пула снимка для видов нет, заземлять `sel`
    не о что. `ElementId` сверяется СТРОКОЙ — безопасной идиомы у него на
    шести версиях нет (замер 03.08).
    """
    oid = op["id"]
    s = _safe(oid)
    nm = op.get("name")
    # 🔴 `lv_idexpr`, А НЕ `__lv_<s>`, И ЭТО НЕ СТИЛЬ. При isolation="per_op"
    # блок создания и блок постусловий попадают в РАЗНЫЕ области видимости
    # (шапка room_emit, живые грабли волны ограждений: CS0103 на шести
    # прогонах). `__lv_<s>` объявляется ВНУТРИ create и свидетелю не виден —
    # первая редакция этого эмиттера получила ровно CS0103 6/6. Выражение
    # идентификатора либо литерал, либо ссылка на переменную из `decl`
    # соседнего опа, и видно всюду.
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)

    decl = (f"ViewPlan __vp_{s} = null;\n"
            f"bool __vpnew_{s} = false;")

    rename = ""
    if nm:
        rename = (f"\n    try {{ __vp_{s}.Name = {_cs(nm)}; }}\n"
                  f"    catch (Exception __exn_{s}) {{ "
                  + refuse_stmt(
                      oid, f'"имя плана этажа: " + __exn_{s}.Message',
                      isolation)
                  + " }")

    create = (
        f"// create_floor_plan {cs_line_comment_fragment(oid)}\n"
        + lv_res + "\n"
        # уже есть? — та же тройка, что у выбора вида в room_emit
        f"foreach (ViewPlan __c_{s} in new FilteredElementCollector(doc)\n"
        f"        .OfClass(typeof(ViewPlan)).Cast<ViewPlan>())\n"
        f"{{\n"
        f"    if (__c_{s}.IsTemplate) continue;\n"
        f"    if (__c_{s}.ViewType != ViewType.FloorPlan) continue;\n"
        f"    Level __g_{s} = null;\n"
        f"    try {{ __g_{s} = __c_{s}.GenLevel; }} catch {{ }}\n"
        f"    if (__g_{s} == null "
        f"|| __g_{s}.Id.ToString() != __lv_{s}.Id.ToString()) continue;\n"
        f"    if (__vp_{s} == null || __c_{s}.Id < __vp_{s}.Id) "
        f"__vp_{s} = __c_{s};\n"
        f"}}\n"
        f"if (__vp_{s} == null)\n"
        f"{{\n"
        f"    ElementId __vft_{s} = doc.GetDefaultElementTypeId("
        f"ElementTypeGroup.ViewTypeFloorPlan);\n"
        f"    if (__vft_{s} == null || __vft_{s}.ToString() == "
        f"ElementId.InvalidElementId.ToString()) {{ "
        + refuse_stmt(
            oid,
            _cs("в документе нет типа вида «план этажа» по умолчанию — "
                "ViewPlan.Create нечем создавать, а выбирать за документ "
                "среди его типов значило бы решить за него"),
            isolation)
        + " }\n"
        f"    try {{ __vp_{s} = ViewPlan.Create(doc, __vft_{s}, "
        f"__lv_{s}.Id); }}\n"
        f"    catch (Exception __exc_{s}) {{ "
        + refuse_stmt(oid, f'"ViewPlan.Create: " + __exc_{s}.Message',
                      isolation)
        + " }\n"
        f"    if (__vp_{s} == null) {{ "
        + refuse_stmt(oid, _cs("ViewPlan.Create вернул null"), isolation)
        + " }\n"
        f"    __vpnew_{s} = true;"
        + rename + "\n"
        # ЛОКАЛЬНАЯ РЕГЕНЕРАЦИЯ — см. докстроку: иначе разделитель этой же
        # программы созданного плана не увидит.
        f"    doc.Regenerate();\n"
        f"}}\n"
        # 🔴 ШТАМП ВЛАДЕНИЯ — ТОЛЬКО НА СОЗДАННОЕ НАМИ (24.08.2026, находка
        # аудита, подтверждена чтением эмиссии).
        #
        # Штамп стоял ПОСЛЕ закрывающей скобки блока `if (__vp == null)`, то
        # есть выполнялся и на идемпотентной ветке «план у уровня УЖЕ ЕСТЬ».
        # Оп разницу ЗНАЕТ — он кладёт её в квитанцию (`already_present`), —
        # но штамп флаг не спрашивал.
        #
        # Цена — не порядок, а УДАЛЁННЫЙ ВИД ВЛАДЕЛЬЦА. Под прогоном A5
        # штамп имеет вид `kir:a5:<doc>:<run>:…`, а уборка сирот обходит
        # `FilteredElementCollector(doc).WhereElementIsNotElementType()`
        # (ViewPlan — не ElementType!) и УДАЛЯЕТ каждый элемент, чей
        # `ALL_MODEL_INSTANCE_COMMENTS` начинается с этого префикса.
        # Сценарий из докстроки самого опа: перенос K3, 917 разделителей,
        # каждый требует план; у целевых уровней планы УЖЕ БЫЛИ.
        #
        # Владение — это утверждение «мы это создали». На чужом виде оно
        # ложно, и ложь тут стоит вида.
        f"if (__vpnew_{s})\n"
        f"{{\n    "
        + _stamp_block(f"__vp_{s}", f"{stamp}:{oid}")
        + f"\n}}")

    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="plan_for_level",
            reader_cs=(f"    ViewPlan __w_{s} = doc.GetElement(__vp_{s}.Id) "
                       f"as ViewPlan;\n"),
            verdict_cs=(
                f"    if (__w_{s} == null)\n"
                f"        __post.Add({_cs(oid + ': floor plan is not in the model (materialize)')});\n"),
            message="floor plan is not in the model (materialize)",
            style="guard"),
        WitnessCheck(
            obligation_key="gen_level",
            reader_cs="",
            verdict_cs=(
                f"    if (__w_{s} != null && (__w_{s}.GenLevel == null "
                f"|| __w_{s}.GenLevel.Id.ToString() != {lv_idexpr}))\n"
                f"        __post.Add({_cs(oid + ': GenLevel is not the resolved level (identity)')});\n"),
            message="GenLevel is not the resolved level (identity)",
            style="guard"),
        WitnessCheck(
            obligation_key="not_template",
            reader_cs="",
            verdict_cs=(
                f"    if (__w_{s} != null && __w_{s}.IsTemplate)\n"
                f"        __post.Add({_cs(oid + ': floor plan is a template (semantic)')});\n"),
            message="floor plan is a template (semantic)",
            style="guard"),
        WitnessCheck(
            obligation_key="view_type",
            reader_cs="",
            verdict_cs=(
                f"    if (__w_{s} != null && __w_{s}.ViewType != ViewType.FloorPlan)\n"
                f"        __post.Add({_cs(oid + ': ViewType is not FloorPlan (semantic)')});\n"),
            message="ViewType is not FloorPlan (semantic)",
            style="guard"),
    ]
    if nm:
        checks.append(WitnessCheck(
            obligation_key="name",
            reader_cs="",
            verdict_cs=(
                f"    if (__w_{s} != null && __vpnew_{s} "
                f"&& __w_{s}.Name != {_cs(nm)})\n"
                f"        __post.Add({_cs(oid + ': name mismatch (identity)')});\n"),
            message="name mismatch (identity)",
            style="guard"))

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __vp_{s}.Id.ToString();\n"
        f"    __rb[\"name\"] = __vp_{s}.Name;\n"
        f"    __rb[\"already_present\"] = !__vpnew_{s};\n"
        f"    __rb[\"level_id\"] = {lv_idexpr};\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback




#: ЧЕГО ЭТА ТАБЛИЦА НЕ ПОКРЫВАЕТ, СКАЗАНО ПЕРВЫМ, потому что добавить сюда
#: строку дешевле, чем проверить, можно ли: **род, который задаётся НЕ через
#: `Parameter.Set(ElementId)`, сюда не относится.**
#:
#: Замерено по индексу ловушек 13.08.2026 на шести версиях: у `Parameter.Set`
#: ровно четыре перегрузки — `ElementId`, `Double`, `Int32`, `String`, — и
#: `Set(WorksetId)` среди них НЕТ. Рабочий набор (`Workset`) не наследует
#: `Element`, не имеет `.Id`, собирается СВОИМ коллектором
#: (`FilteredWorksetCollector`) и адресуется `WorksetId.IntegerValue`. То есть
#: приём отсюда не применим к нему НИ В ОДНОМ из четырёх шагов — ни разрешение,
#: ни запись, ни свидетель, ни коллектор.
#:
#: ЦЕНА ОБОБЩЕНИЯ — ПРОВЕРКА ПРИМЕНИМОСТИ ПЕРЕД КАЖДЫМ ПРИМЕНЕНИЕМ. Эта таблица
#: сделала второй род дешёвым; ровно поэтому она опасна на третьем: строка,
#: добавленная по аналогии, дала бы способность, которая ВЫГЛЯДИТ как две уже
#: доказанные. Похожая на рабочую хуже несобирающейся.
#:
#: Род ссылки -> (класс Ревита, слово для отказа, причастие). Таблица закрыта
#: НАМЕРЕННО:
#: новый род заводится здесь И в нормализаторе И в схеме одной правкой, иначе
#: программа, законная для одного, отвергается другим.
_REF_POOLS = {
    "materials": ("Material", "материал", "найден"),
    "phases": ("Phase", "фаза", "найдена"),
}



def _expected_current_check(op: dict, s: str, pname: str, oid: str,
                            isolation: str = "atomic") -> str:
    """Compare-and-set: refuse if the parameter is no longer what the author read.

    🔴 THE HALF THAT WORKS WHERE IDENTITY CANNOT. `expected_identity` leans on
    `VersionGuid`, and on an UNSAVED document that returns the DOCUMENT's
    episode — the same 32 characters for every element (measured 13.09.2026,
    registry ОТК-26). There it cannot tell an edited wall from an untouched one.
    The parameter's OWN value can: it is re-read here, before the write, and a
    write computed from a stale read is refused by name instead of overwriting
    someone else's edit. That is the T10 subject stated in one op.

    THE RULER IS THE OP'S OWN, NOT A NEW ONE. The comparison uses
    `tolerances("set_param")` — the same `length_mm` / `double_abs` the
    postcondition uses when it re-reads the value it just wrote. A second
    tolerance for "the same measurement" would drift from the first.
    """
    expected = op.get("expected_current")
    if not expected:
        return ""
    tol = tolerances("set_param")
    kind, value = expected["type"], expected["v"]
    next_move = ("следующий ход: прочитай элемент заново (query_element_state) "
                 "и повтори от свежей базы")
    stale = ("value_changed_since_read: параметр «" + pname + "» больше не тот, что был "
             "прочитан — правка посчитана от устаревшей базы; " + next_move)
    if kind == "str":
        read = f"(__pp_{s}.AsString() ?? \"\")"
        differs = f"{read} != {_cs(str(value))}"
    elif kind == "int":
        differs = f"__pp_{s}.AsInteger() != {int(value)}"
    elif kind == "mm":
        differs = (f"Math.Abs(MM(__pp_{s}.AsDouble()) - {value}) > {tol['length_mm'].cs}")
    elif kind == "raw":
        differs = (f"Math.Abs(__pp_{s}.AsDouble() - {value}) > {tol['double_abs'].cs}")
    else:
        # A reference value (material/workset/phase) would have to be resolved to
        # an ElementId and compared as one; that is a second resolution path and
        # it is NOT written yet. Refusing by name beats comparing the wrong thing.
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED, op_id=oid, got=kind,
            message_ru=("expected_current пока выражается для строк, целых, длин (мм) и "
                        f"сырых чисел; значение рода «{kind}» так не сверяется — убери "
                        "expected_current или сверь ссылку отдельным чтением"))])
    return (f"if ({differs}) {{ {refuse_stmt(oid, _cs(stale), isolation)} }}\n")


def _emit_setparam(op: dict, ver: str, stamp: str,
                   isolation: str = "atomic") -> tuple[str, str, str, str]:
    oid = op["id"]
    s = _safe(oid)
    pname = op["param"]
    val = op["value"]
    decl = f"Element __tg_{s} = null; Parameter __pp_{s} = null;"
    res = _target_res(op, s, ver, oid, isolation).replace(f"Element __tg_{s} =", f"__tg_{s} =")
    ref_res = ""
    if val["type"] == "int_ref":
        # РАБОЧИЙ НАБОР. НЕ ветка `ref` и не строка в `_REF_POOLS`: `Workset`
        # не наследует `Element`, коллектор свой, запись ЦЕЛЫМ, свидетель
        # `AsInteger()`. Все четыре шага другие — сложить его к ссылкам значило
        # бы получить способность, которая ВЫГЛЯДИТ как две доказанные.
        #
        # ДВА ПРЕДУСЛОВИЯ, ОБА СПРАШИВАЮТСЯ ДО ЗАПИСИ (замер ВОРОТ 13.08):
        # `Parameter.Set` документирует `InvalidOperationException` «The
        # parameter is read-only» у ВСЕХ четырёх перегрузок — но `IsReadOnly`
        # существует и спрашивается, значит это ПРЕДУСЛОВИЕ, а не ловушка
        # класса. Разделённость документа индекс не покрывает вовсе — это
        # названная неизвестность, и она закрывается тем же способом:
        # спросить `IsWorkshared` и отказать типизированно.
        ref_res = (
            f"\nif (!doc.IsWorkshared) {{ "
            f"{refuse_stmt(oid, _cs('документ не разделён на рабочие наборы — набор задать некуда'), isolation)} }}\n"
            f"int __ws_{s} = -1;\n"
            f"foreach (Workset __wcand_{s} in new FilteredWorksetCollector(doc).ToWorksets())\n"
            f"    if (__wcand_{s}.Name == {_cs(val['v'])}) {{ __ws_{s} = __wcand_{s}.Id.IntegerValue; break; }}\n"
            f"if (__ws_{s} < 0) {{ "
            f"{refuse_stmt(oid, _cs('рабочий набор «' + val['v'] + '» не найден в документе'), isolation)} }}")
        set_expr = f"__pp_{s}.Set(__ws_{s})"
    elif val["type"] == "ref":
        # РОД ССЫЛКИ РЕШАЕТ ТОЛЬКО КЛАСС РЕВИТА И СЛОВО В ОТКАЗЕ. Всё
        # остальное — разрешение, отказ, `Set(<el>.Id)`, свидетель — ОДНО для
        # всех родов: второй способ делать то же разошёлся бы с первым на роде,
        # который придёт третьим.
        cls, word, found = _REF_POOLS[val.get("pool", "materials")]
        # ССЫЛКА. Приём взят ДОСЛОВНО у `_emit_create_type` (материал в
        # `create_type`, строки 3648-3672): разрешение коллектором, типизированный
        # отказ, `Set(<el>.Id)`, свидетель через `AsElementId()`. Второй способ
        # делать то же самое — будущее расхождение, и за эту ночь их было
        # достаточно.
        ref_res = (
            f"\n{cls} __rf_{s} = new FilteredElementCollector(doc)"
            f".OfClass(typeof({cls})).Cast<{cls}>()\n"
            f"    .FirstOrDefault(__m => __m.Name == {_cs(val['v'])});\n"
            f"if (__rf_{s} == null) {{ "
            f"{refuse_stmt(oid, _cs(word + ' «' + val['v'] + '» не ' + found + ' в документе'), isolation)} }}")
        set_expr = f"__pp_{s}.Set(__rf_{s}.Id)"
    elif val["type"] == "str":
        set_expr = f"__pp_{s}.Set({_cs(val['v'])})"
    elif val["type"] == "mm":
        set_expr = f"__pp_{s}.Set(U({val['v']}))"
    elif val["type"] == "int":
        set_expr = f"__pp_{s}.Set({int(val['v'])})"
    else:  # raw double
        set_expr = f"__pp_{s}.Set({val['v']})"
    create = (
        f"// set_param {cs_line_comment_fragment(oid)}\n{res}{ref_res}\n"
        f"var __matches_{s} = __tg_{s}.GetParameters({_cs(pname)});\n"
        f"if (__matches_{s} == null || __matches_{s}.Count == 0) {{ {refuse_stmt(oid, _cs('параметр «' + pname + '» не найден у элемента'), isolation)} }}\n"
        f"if (__matches_{s}.Count != 1) {{ {refuse_stmt(oid, _cs('параметр «' + pname + '» неоднозначен: найдено несколько параметров с этим именем'), isolation)} }}\n"
        f"__pp_{s} = __matches_{s}[0];\n"
        f"if (__pp_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('параметр «' + pname + '» только для чтения'), isolation)} }}\n"
        + _expected_current_check(op, s, pname, oid, isolation) +
        f"if (!{set_expr}) {{ {refuse_stmt(oid, _cs('Set(' + pname + ') вернул false — несовместимый тип значения'), isolation)} }}")
    # Допуски ре-чтения — из реестра.  `post` обещает «±tol for lengths», и
    # у обещания теперь есть адрес: длина сверяется с `length_mm`, сырой
    # double — с `double_abs`.  Формы подстановки выбраны ПО БАЙТАМ: `0.5`
    # печатается обычным str, а `1e-6` — компактной формой `.cs` (обычный
    # repr дал бы `1e-06` и сдвинул бы корпус эталонных эмиссий).
    stol = tolerances("set_param")
    vtol = None
    if val["type"] == "int_ref":
        # СВИДЕТЕЛЬ НАБОРА — целое, а не ссылка. Способность без своего
        # свидетеля запрещена, и свидетель обязан быть ТОГО ЖЕ рода, что запись.
        chk = f"__pp_{s}.AsInteger() != __ws_{s}"
    elif val["type"] == "ref":
        # СВИДЕТЕЛЬ ССЫЛКИ. Способность, добавленная БЕЗ своего свидетеля, не
        # «неполная» — она запрещённая: исполнение совершено, подтвердить
        # нечем. Поэтому ветка записи и ветка перечитывания заводятся ОДНОЙ
        # правкой, а не одна за другой.
        chk = (f"__pp_{s}.AsElementId() == null || "
               f"__pp_{s}.AsElementId().ToString() != __rf_{s}.Id.ToString()")
    elif val["type"] == "str":
        chk = f"(__pp_{s}.AsString() ?? \"\") != {_cs(val['v'])}"
    elif val["type"] == "mm":
        vtol = stol["length_mm"]
        chk = f"Math.Abs(MM(__pp_{s}.AsDouble()) - {val['v']}) > {vtol}"
    elif val["type"] == "int":
        chk = f"__pp_{s}.AsInteger() != {int(val['v'])}"
    else:
        vtol = stol["double_abs"]
        chk = f"Math.Abs(__pp_{s}.AsDouble() - {val['v']}) > {vtol.cs}"
    # 🔴 СТАДИЯ ОПЕРАЦИИ, А НЕ КОНЕЦ ПРОГРАММЫ (07.09.2026, F1/C01).
    #
    # «Параметр держит значение» — факт О МОЁМ ОПЕ: в конце set_param у цели
    # стоит то, что просил ЭТОТ оп. На стадии final тот же текст читается как
    # «до конца программы никто больше этого не пишет», а это НЕПРАВДА и не
    # обещание реестра: `set_param(101,"Comments","first")` и следом
    # `set_param(101,"Comments","last")` — две законные записи, и первая
    # обязана уступить второй. Пока проверка стояла на final, свидетель
    # первого писателя спрашивал `!= "first"` уже ПОСЛЕ второго, добавлял
    # нарушение и откатывал ВЕРНО построенную программу.
    #
    # Форма выбрана не заново: ровно так закрыт `change_type.type_assignment`
    # (docs/OPERATION_WITNESS_STAGE_RU.md) — проверка исполняется внутри
    # границы своей операции, до её subcommit и до следующего опа, а
    # последующий явный писатель вправе это состояние сменить.
    #
    # ЧТО ЭТО НЕ ДЕЛАЕТ: проверка НЕ снята и НЕ ослаблена — тот же предикат,
    # тот же допуск, тот же ключ обязательства; сменилась стадия исполнения.
    # Прибор: kir/tests/test_the_last_legal_writer_defines_the_final_state.py
    post = [WitnessCheck(
        obligation_key="value_held", reader_cs="",
        verdict_cs=(
            f"    if ({chk}) __post.Add({_cs(oid + ': параметр не удержал значение (re-read)')});\n"),
        message="параметр не удержал значение (re-read)",
        tol=vtol, style="guard", stage="operation")]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __tg_{s}.Id.ToString();\n"
        f"    __rb[\"param\"] = {_cs(pname)};\n"
        f"    try {{ __rb[\"value\"] = (__pp_{s}.StorageType == StorageType.String) ? (object)__pp_{s}.AsString() : (object)__pp_{s}.AsValueString(); }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


#: Сколько ИМЁН соседей квитанция называет поимённо (число рядом с ними —
#: всегда полное).  Величина НЕ НОВАЯ: это тот же закон реза, которым уже
#: живут `violations`, `unwitnessed_axes` и `named_absences` в
#: `serving.py` — «режутся по десять, квитанция платится каждым ходом».
#: Заводить сюда своё число значило бы получить два закона реза на одну
#: квитанцию, то есть второй носитель одной величины.
_NEIGHBOUR_ID_CAP = 10


def _emit_delete(op: dict, ver: str, stamp: str,
                 isolation: str = "atomic") -> tuple[str, str, str, str]:
    """delete: doc.Delete(ElementId) — И КРУГ ПОСЛЕДСТВИЙ, КОТОРЫЙ РЕВИТ
    ОТДАЁТ САМ.

    🔴 ЧТО ЗДЕСЬ БЫЛО НЕ ТАК ДО 22.08.2026. Обязательство опа — «элемент
    больше не разрешается» — говорит РОВНО про цель. Между тем документация
    Autodesk, отгруженная ВНУТРИ NuGet-пакета сборки (индекс ловушек
    `data/api_traps`, поле `remarks`, ОДИН И ТОТ ЖЕ текст на всех шести
    версиях 2021-2026), обещает про этот вызов больше:

        "This method will delete the element AND ANY ELEMENTS THAT ARE
         TOTALLY DEPENDENT UPON THAT ELEMENT."

    То есть удаление стены забирает её двери, и квитанция об этом молчала.
    Владелец спрашивает «хозяин удалён — что стало с дверью?», а ответить
    было нечем: `deleted_id` называл ОДИН id, тот самый, который и просили.

    ЦЕНА ЭТОГО ОТВЕТА — НОЛЬ ЛИШНИХ ВЫЗОВОВ РЕВИТА. `Document.Delete` уже
    ВОЗВРАЩАЕТ `ICollection<ElementId>` — полный список удалённого, — и
    прежняя эмиссия этот возврат ВЫБРАСЫВАЛА. Сигнатура подтверждена по
    настоящим reference-сборкам (`data/api_surface/api_signatures_20NN.json`:
    `Delete -> ["(ICollection<ElementId>)", "(ElementId)"]`, 6/6) и живой
    компайл-службой на всех шести версиях (проба
    `ICollection<ElementId> x = doc.Delete(id);` — 6/6 OK, 22.08.2026).

    🔴 ПОЧЕМУ ЭТО ФАКТ КВИТАНЦИИ, А НЕ ОБЯЗАТЕЛЬСТВО. Сторож «попутно удалено
    ноль» краснил бы КАЖДОЕ удаление стены с дверью, то есть самый обычный
    случай, и в строгом режиме откатывал бы всю программу. Это ровно та
    несимметричная цена ложного красного, о которой предупреждает
    `_NON_WITNESSABLE_CLAUSES`. Утверждения вида «попутно удалено не больше
    чем разрешил план» у нас нет: план знает только `allow_destructive`
    (булев затвор на ЦЕЛЬ), и понятия «что обязано остаться» язык не несёт.
    Поэтому здесь ЧИСЛО И ИМЕНА в квитанции, а границы нет — и это названо
    отсутствием, а не подписано зелёным (запись для
    `translation_cert._NON_WITNESSABLE_CLAUSES` — в отчёте волны).
    """
    oid = op["id"]
    s = _safe(oid)
    # Список живёт в decl (контракт областей): readback читает его ПОСЛЕ того,
    # как per-op try-scope закрылся.
    decl = (f"ElementId __delid_{s} = null;\n"
            f"List<string> __delalso_{s} = new List<string>();\n"
            # Same scope contract as the list above: everything the receipt
            # reads is built in `decl`, or it dies with the per-op try-scope.
            f"List<object> __delpred_{s} = new List<object>();\n"
            f"int __delpredn_{s} = 0;")
    res = _target_res(op, s, ver, oid, isolation)
    create = (
        f"// delete {cs_line_comment_fragment(oid)}\n{res}\n"
        f"__delid_{s} = __tg_{s}.Id;\n"
        # 🔴 НАЗВАТЬ КРУГ ПОСЛЕДСТВИЙ ДО ЭФФЕКТА, А НЕ ПОСЛЕ (13.09.2026).
        # Возврат `doc.Delete` уже даёт полный список — но ПОСЛЕ удаления, то
        # есть отвечает на «что ушло», когда решать уже поздно. Замер живого
        # Ревита 13.09: одно удаление унесло 38 элементов (в другом проходе
        # 10+13+12) — `live-20260913-slice-cleanup-receipt.json`. Автор, который
        # видит это число ЗАРАНЕЕ, может передумать; автор, который видит его в
        # квитанции, уже ничего не решает. `GetDependentElements` — ЧТЕНИЕ, оно
        # ничего не меняет, и Ревит считает круг тем же способом, каким потом
        # удаляет. Предсказание и факт лежат в квитанции РЯДОМ, и расхождение
        # названо отдельным полем: молчаливое «предсказали одно, удалили другое»
        # было бы хуже, чем отсутствие предсказания.
        f"try\n"
        f"{{\n"
        f"    ICollection<ElementId> __delpredids_{s} = __tg_{s}.GetDependentElements(null);\n"
        f"    if (__delpredids_{s} != null)\n"
        f"        foreach (ElementId __delpx_{s} in __delpredids_{s})\n"
        f"            if (__delpx_{s}.ToString() != __delid_{s}.ToString())\n"
        f"            {{ __delpredn_{s}++; if (__delpred_{s}.Count < {_NEIGHBOUR_ID_CAP}) "
        f"__delpred_{s}.Add(__delpx_{s}.ToString()); }}\n"
        f"}}\n"
        f"catch {{ __delpredn_{s} = -1; }}\n"
        f"try\n"
        f"{{\n"
        f"    ICollection<ElementId> __delret_{s} = doc.Delete(__delid_{s});\n"
        # Сама цель из списка вычитается: спрашивают «что ЕЩЁ ушло», и число,
        # включающее заказанное, отвечало бы на другой вопрос.
        f"    if (__delret_{s} != null)\n"
        f"        foreach (ElementId __delx_{s} in __delret_{s})\n"
        f"            if (__delx_{s}.ToString() != __delid_{s}.ToString())\n"
        f"                __delalso_{s}.Add(__delx_{s}.ToString());\n"
        f"}}\n"
        f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"Delete: \" + __ex_{s}.Message', isolation)} }}")
    post = [WitnessCheck(
        obligation_key="gone", reader_cs="",
        verdict_cs=(
            f"    if (doc.GetElement(__delid_{s}) != null)\n"
            f"        __post.Add({_cs(oid + ': элемент всё ещё существует после Delete')});\n"),
        message="элемент всё ещё существует после Delete", style="guard")]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"deleted_id\"] = __delid_{s}.ToString();\n"
        # ЧИСЛО ВСЕГДА ПОЛНОЕ, ИМЕНА РЕЖУТСЯ. Квитанция платится каждым ходом
        # (замер 21.08: 44 КБ из 85 были одним фактом, сказанным сто раз), а
        # «сколько ушло» — это одна величина, и урезать её нечестно.
        f"    __rb[\"collateral_count\"] = __delalso_{s}.Count;\n"
        f"    __rb[\"collateral_ids\"] = __delalso_{s}.GetRange(0, Math.Min({_NEIGHBOUR_ID_CAP}, __delalso_{s}.Count));\n"
        f"    __rb[\"collateral_capped\"] = __delalso_{s}.Count > {_NEIGHBOUR_ID_CAP};\n"
        f"    __rb[\"dependents_predicted\"] = __delpred_{s};\n"
        f"    __rb[\"dependents_predicted_count\"] = __delpredn_{s};\n"
        f"    __rb[\"dependents_actual_count\"] = __delalso_{s}.Count;\n"
        # Расхождение НАЗЫВАЕТСЯ, а не выводится читателем из двух чисел: −1
        # значит «прочитать круг не удалось», и это не то же самое, что «круг
        # пуст». Это факт квитанции, не обязательство: сторож «предсказание
        # совпало» краснил бы законные случаи, где Ревит доудаляет по своим
        # правилам, и в строгом режиме откатывал бы верную программу.
        f"    __rb[\"dependents_prediction_matched\"] = __delpredn_{s} < 0 ? (object)null "
        f": (object)(__delpredn_{s} == __delalso_{s}.Count);\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_change_type(op: dict, ver: str, stamp: str,
                      isolation: str = "atomic") -> tuple[str, str, str, str]:
    """change_type: Element.ChangeTypeId(ElementId) — CLASH-fix op 2/2.

    Return-value semantics confirmed via RevitAPI.xml — the doc comments
    SHIPPED INSIDE the NuGet assembly package, not wiki — identical on all
    six versions (``<since>2011</since>`` in the doc itself, and the method
    signature confirmed byte-identical by reflection over RevitAPI.dll
    2021..2026): ``InvalidElementId`` is the ORDINARY success case (type
    changed IN PLACE, same element — "this element becomes invalid" does NOT
    apply); a REAL ElementId is returned ONLY in the rare case Revit creates
    a NEW element instead (wall <-> curtain-panel wall is the one
    documented example), and THEN the original reference is stale — the
    witness must re-read the RETURNED id, never the original. Incompatible
    type is a THROWN ArgumentException ("The type typeId is not valid for
    this element"), never a return value — treating InvalidElementId as
    failure would have misread the ORDINARY success path as a refusal.
    """
    oid = op["id"]
    s = _safe(oid)
    tgt_res = _target_res(op, s, ver, oid, isolation).replace(
        f"Element __tg_{s} =", f"__tg_{s} =")
    type_val = op["type"]["value"]
    # Everything post/readback touch lives in decl — the per_op create block
    # closes its own try-scope (emitter scope contract).
    decl = (f"Element __tg_{s} = null;\nElementType __ty_{s} = null;\n"
            f"ElementId __chid_{s} = null;\nElement __el_{s} = null;\n"
            + type_assignment_declarations(oid))
    create = (
        f"// change_type {cs_line_comment_fragment(oid)}\n{tgt_res}\n"
        f"__ty_{s} = doc.GetElement({_eid(type_val, ver, oid)}) as ElementType;\n"
        f"if (__ty_{s} == null) {{ {refuse_stmt(oid, _cs('тип не найден (модель изменилась после grounding)'), isolation)} }}\n"
        f"try {{ __chid_{s} = __tg_{s}.ChangeTypeId(__ty_{s}.Id); }}\n"
        f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"несовместимый тип (ChangeTypeId): \" + __ex_{s}.Message', isolation)} }}\n"
        f"doc.Regenerate();\n"
        f"__el_{s} = (__chid_{s} != null && __chid_{s} != ElementId.InvalidElementId)\n"
        f"    ? doc.GetElement(__chid_{s}) : __tg_{s};\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('элемент не найден после ChangeTypeId'), isolation)} }}")
    post = [type_assignment_witness(f"__el_{s}", f"__ty_{s}", oid)]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + type_assignment_readback_cs(f"__el_{s}", oid) +
        f"    __rb[\"new_element_created\"] = __chid_{s} != null && __chid_{s} != ElementId.InvalidElementId;\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_join_elements(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, str, str]:
    """join_elements: JoinGeometryUtils.JoinGeometry(doc, a, b).

    ФАКТ СОЕДИНЕНИЯ ПЕРЕСТАЁТ ТЕРЯТЬСЯ — прямая просьба владельца 17.08.2026.
    До этого опа в реестре было НОЛЬ операций соединения: пересобранное здание
    приезжало в Revit рассыпанным, и восстановить связи было нечем.

    ТРИ ЗАМЕРА, НА КОТОРЫХ СТОИТ ЭТА ЭМИССИЯ (18.08.2026):

    * **версионности НЕТ.** Тело ``AreElementsJoined`` + ``JoinGeometry`` +
      ``GetJoinedElements`` собрано живой компайл-службой на эталонных
      сборках 2021, 2022, 2023, 2024, 2025, 2026 — шесть из шести, ошибок
      ноль. Поэтому опа нет в ``VERSION_FRAGILE``, и это замер, а не пробел;
    * **предпроверка обязательна.** Документация Autodesk (индекс ловушек,
      6/6 версий): ``JoinGeometry`` бросает ``ArgumentException`` — «The
      elements are already joined. -or- The elements cannot be joined.»
      Без ``AreElementsJoined`` ПЕРЕД вызовом повторный прогон той же
      программы падал бы на паре, которую сам же и соединил в прошлый раз,
      то есть идемпотентность ломалась бы об СОБСТВЕННЫЙ успех. Пересборка
      состоит из повторных прогонов, так что это главный случай, а не край;
    * **витражная панель — свой отказ.** ``InvalidOperationException``:
      «Please remove or add segments on curtain grids instead of joining or
      unjoining geometry of the panels.» Он приходит текстом Revit в
      типизированный отказ, а не превращается в общий сбой.

    ПОЧЕМУ ОТКАЗ, А НЕ ЗАПИСЬ (в отличие от де-джойна ниже). Де-джойн —
    попутное улучшение уже созданной стены, и его провал не отменяет стену.
    Здесь соединение — ЕДИНСТВЕННОЕ, что оп делает: несоединившаяся пара
    означает, что оп не сделал ничего, и назвать это успехом нельзя.

    СВИДЕТЕЛЬ СПРАШИВАЕТ РОВНО ТО, ЧТО ОП ОБЕЩАЛ. Обещано «соединено» —
    перечитывается ``AreElementsJoined(doc, a, b)``. Ни прокси, ни габарит,
    ни «похоже»: то же самое отношение, спрошенное после Regenerate. Такое
    совпадение обещания и проверки в этом реестре редкость, и оно и есть
    ценность опа.
    """
    oid = op["id"]
    s = _safe(oid)

    def _resolve(field: str, var: str) -> str:
        """Разрешение одного из ДВУХ операндов.

        ``_target_res`` захардкожен на ``op["target"]`` и обслуживает 30+
        опов; здесь операндов два, и звать его дважды нечем. Форма разрешения
        повторена дословно, чтобы отказ читался так же, как у соседей.
        """
        sel = op[field]
        if sel["by"] == "ref":
            return f"__{var}_{s} = (Element)__el_{_safe(sel['value'])};"
        return (
            f"__{var}_{s} = doc.GetElement({_eid(sel['value'], ver, oid)});\n"
            f"if (__{var}_{s} == null) {{ "
            f"{refuse_stmt(oid, _cs(field + ': элемент не найден (модель изменилась после grounding)'), isolation)} }}")

    decl = (f"Element __ja_{s} = null;\nElement __jb_{s} = null;\n"
            f"bool __jpre_{s} = false;")
    create = (
        f"// join_elements {cs_line_comment_fragment(oid)}\n"
        f"{_resolve('first', 'ja')}\n"
        f"{_resolve('second', 'jb')}\n"
        # Пара из одного элемента — не соединение, а вопрос без смысла.
        # Revit на этом бросает; отказ здесь называет ПРИЧИНУ, а не пересылает
        # текст исключения про «уже соединены».
        f"if (__ja_{s}.Id == __jb_{s}.Id) {{ "
        f"{refuse_stmt(oid, _cs('first и second — один и тот же элемент: соединять нечего'), isolation)} }}\n"
        # Native A/B: earlier writes in this transaction must be regenerated
        # before Revit can inspect and join their current geometry.
        f"try {{ doc.Regenerate(); __jpre_{s} = JoinGeometryUtils.AreElementsJoined(doc, __ja_{s}, __jb_{s}); }}\n"
        f"catch (Exception __jq_{s}) {{ "
        f"{refuse_stmt(oid, '"не удалось спросить, соединены ли элементы: " + __jq_' + s + '.Message', isolation)} }}\n"
        f"if (!__jpre_{s})\n"
        f"{{\n"
        f"    try {{ JoinGeometryUtils.JoinGeometry(doc, __ja_{s}, __jb_{s}); }}\n"
        f"    catch (Exception __jx_{s})\n"
        f"    {{\n"
        # ДВА БРОСКА ПОД ОДНИМ ТИПОМ ИСКЛЮЧЕНИЯ, И ЭТО РАЗНЫЕ ФАКТЫ (25.08.2026,
        # живой замер 13A-RD-AR-K2_v33, Revit 2023 — kir/CLAUDE.md). Автодеск
        # документирует ОДИН ArgumentException на четыре причины разом: «already
        # joined», «cannot be joined», документ не тот, элемент не найден (индекс
        # ловушек, revit_api_traps.sqlite, fingerprint той же строки). «already
        # joined» отсечена ВЫШЕ предпроверкой AreElementsJoined, а «cannot be
        # joined» — измеренный ГЛАВНЫЙ случай опа: пара, построенная ПРОШЛОЙ (уже
        # закоммиченной) транзакцией, честно не имеет общей грани для JoinGeometry,
        # хотя та же пара в ТОЙ ЖЕ транзакции соединяется без единой ошибки. Это
        # факт о ПАРЕ, а не поломка эмиссии, и сваливать его в тот же текст, что
        # настоящее исключение, значило бы читать измеренный главный случай как
        # баг. Различитель — подстрока сообщения Revit (другого носителя нет).
        f"        if (__jx_{s}.Message.IndexOf(\"cannot be joined\", "
        f"StringComparison.OrdinalIgnoreCase) >= 0)\n"
        f"        {{ {refuse_stmt(oid, '"элементы НЕ ИМЕЮТ ОБЩЕЙ ГРАНИ для соединения (Revit: cannot be joined) — это факт о паре (не касаются, либо стык уже сведён автоматически), а не отказ эмиссии: " + __jx_' + s + '.Message', isolation)} }}\n"
        f"        else\n"
        f"        {{ {refuse_stmt(oid, '"соединить не удалось (JoinGeometry), причина не «cannot be joined»: " + __jx_' + s + '.Message', isolation)} }}\n"
        f"    }}\n"
        f"}}")
    post = [WitnessCheck(
        obligation_key="elements_joined", reader_cs="",
        verdict_cs=(
            f"    bool __jok_{s} = false;\n"
            f"    try {{ __jok_{s} = JoinGeometryUtils.AreElementsJoined("
            f"doc, __ja_{s}, __jb_{s}); }} catch {{ __jok_{s} = false; }}\n"
            f"    if (!__jok_{s})\n"
            f"        __post.Add({_cs(oid + ': элементы НЕ соединены после JoinGeometry (semantic, re-read)')});\n"),
        message="элементы не соединены после JoinGeometry (semantic, re-read)",
        style="guard")]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    var __jids_{s} = new List<string>();\n"
        f"    __jids_{s}.Add(__ja_{s}.Id.ToString());\n"
        f"    __jids_{s}.Add(__jb_{s}.Id.ToString());\n"
        f"    __rb[\"joined_ids\"] = __jids_{s};\n"
        # ЧЕСТНОЕ РАЗЛИЧЕНИЕ ДВУХ ИСХОДОВ. «Соединил» и «уже было соединено»
        # дают одно и то же состояние документа, но это РАЗНЫЕ факты о том,
        # что сделал ход: без этого поля повторный прогон пересборки выглядел
        # бы как работа, которой не было.
        f"    __rb[\"already_joined\"] = __jpre_{s};\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_move_elements(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, str, str]:
    """move_elements: ElementTransformUtils.MoveElements(doc, ICollection
    <ElementId>, XYZ) — CLASH-fix op 1/2. Moves the WHOLE set in one call;
    Revit pulls fittings and PRESERVES connections (this is the entire
    industrial point — moving elements one at a time breaks and re-forms
    connections instead). Signature confirmed identical 2021..2026 by
    reflection over RevitAPI.dll.

    Per-target RESOLUTION is Python-unrolled (one block per target, same
    discipline as create_dimension.refs) — the SHAPE differs per target
    (ref vs element_id). Per-target VERIFICATION is a C# runtime loop over
    the resolved Lists instead — up to 500 targets, and the check LOGIC is
    identical for every one of them, so unrolling verification too would be
    500x the code for zero extra proof. Every list read by post/readback is
    built in decl (scope contract): a target's pre-move snapshot must
    survive the per-op try-scope closing.

    🔴 КРУГ ПОСЛЕДСТВИЙ — ЧТО ЗДЕСЬ ПОЯВИЛОСЬ 22.08.2026 И ЗАЧЕМ.

    До этой правки ВСЕ ТРИ обязательства опа говорили про САМУ ЦЕЛЬ: точка и
    концы сдвинулись, коннекторы целей сосчитаны, наклон целей не поехал.
    Между тем действие переноса целиком живёт в СОСЕДЯХ — дверь хозяина,
    соединение с примыкающей стеной, замок автора, площадь помещения. Ни
    одного вопроса про них задано не было, и от этого свидетель возвращал
    `unwitnessed_axes: {}` — ПОЛНОЕ покрытие: осей соседа в списке осей нет
    вовсе, поэтому и непроверенным ничего не числилось. Замер 22.08 по
    живому `serving._witness_for_success`: из шести мутаций реестра
    `move_elements` — ЕДИНСТВЕННАЯ с пустым `unwitnessed_axes`, то есть
    единственная, о которой квитанция утверждала полноту.

    ВЗЯТО (дёшево, по одному вызову на цель, все три члена 6/6 по настоящим
    reference-сборкам и по живой компайл-службе 22.08):

    * ``HostObject.FindInserts(true, true, false, false)`` — ОБЯЗАТЕЛЬСТВО.
      Дверь и окно существуют ТОЛЬКО в своём хозяине, и жёсткий перенос
      хозяина обязан унести их с собой. Потеря — не «побочный эффект», а
      ровно то «упало», против которого заведён критерий владельца, и
      красный здесь верен даже там, где сам Ревит считает исход законным:
      автор просил подвинуть стену, а не удалить дверь. `findShared` и
      `findEmbedded` выключены СОЗНАТЕЛЬНО: врезанная в витраж стена
      законно перестаёт быть врезанной, когда её отодвигают, и это
      единственная ветка, где красный обвинил бы правильную работу.
    * ``Element.GetDependentElements(ElementClassFilter(typeof(Dimension)))``
      + ``Dimension.IsLocked`` — ОБЯЗАТЕЛЬСТВО. См. большой замер про 1 233
      замка настоящего здания в теле резолва.
    * ``JoinGeometryUtils.GetJoinedElements`` — ФАКТ КВИТАНЦИИ, НЕ сторож.
      Довод — в комментарии у `joins_lost`.

    НЕ ВЗЯТО, И ЦЕНА НАЗВАНА ЧИСЛОМ: ПОМЕЩЕНИЯ. У Ревита НЕТ вопроса «какие
    комнаты граничат с этой стеной» — обратного индекса не существует.
    Единственный путь — `FilteredElementCollector(OST_Rooms)` по ВСЕМУ
    документу плюс `Room.GetBoundarySegments` у каждой найденной.

    Цена, замерена по переписи разобранного MNVNK (`L0.jsonl`, поле
    `document.census`): **OST_Rooms 1 102**, OST_Walls 10 646. То есть
    вопрос про соседей-комнат стоит 1 102 элемента НА КАЖДЫЙ оп, тогда как
    всё взятое выше — ОДИН вызов на цель, а целей в обычной перепланировке
    одна-две. `MAX_OPS_PER_PROGRAM` = 100 000 (`compiler.py:111`), так что
    множитель — число опов программы, а не константа.

    Поэтому площади и целостность помещений остаются НАЗВАННЫМ
    ОТСУТСТВИЕМ, а не молчаливым зелёным (запись для
    `_NON_WITNESSABLE_CLAUSES` — в отчёте волны). Дешёвый вопрос, который
    сделал бы это обязательством, существует только у САМОЙ КОМНАТЫ
    (`Room.Area`), а не у стены; чтобы им воспользоваться, нужен адрес
    комнаты, а его переносу стены никто не даёт.
    """
    oid = op["id"]
    s = _safe(oid)
    targets = op["targets"]
    dx, dy, dz = op["delta_mm"]
    htol = tolerance("move_elements", "location_mm")

    # 🔴 ONE BASE CANNOT DESCRIBE MANY TARGETS. `expected_identity` says "the
    # thing I read"; with several targets there is no single thing, and quietly
    # applying the same identity to all of them — or to the first — would be a
    # claim nobody made. Refused at COMPILE time, because it is a fact about the
    # program, not about the model.
    if op.get("expected_identity") and len(targets) != 1:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED, op_id=oid, got=len(targets),
            message_ru=("expected_identity задаёт ОДНУ прочитанную личность, а целей "
                        f"{len(targets)} — раздели перенос на отдельные опы, по одному "
                        "на цель, либо убери expected_identity"))])
    base_check = expected_identity_check(op, f"__mte_{s}", oid, isolation)
    resolve_blocks = []
    for i, sel in enumerate(targets):
        label = f"targets[{i}]"
        if sel["by"] == "ref":
            get_line = f"Element __mte_{s} = (Element)__el_{_safe(sel['value'])};"
        elif sel["by"] == "unique_id":
            # Same law as `_target_res`: a UniqueId is the only address that
            # survives the session that created the element, and the document is
            # asked to confirm the identity it returned rather than trusted to
            # have resolved the right number.
            gone = (label + ": элемент с этим UniqueId не найден — он удалён или это другой "
                    "документ; следующий ход: прочитай элемент заново (query_element_state) "
                    "и повтори от свежей базы")
            get_line = (
                f"Element __mte_{s} = null;\n"
                f"    try {{ __mte_{s} = doc.GetElement({_cs(sel['value'])}); }} catch {{ }}\n"
                f"    if (__mte_{s} == null) {{ {refuse_stmt(oid, _cs(gone), isolation)} }}\n"
                f"    if (__mte_{s}.UniqueId != {_cs(sel['value'])}) "
                f"{{ {refuse_stmt(oid, _cs(label + ': документ вернул элемент с другим UniqueId'), isolation)} }}")
        else:
            get_line = (
                f"Element __mte_{s} = doc.GetElement({_eid(sel['value'], ver, oid)});\n"
                f"    if (__mte_{s} == null) {{ {refuse_stmt(oid, _cs(label + ': элемент не найден (модель изменилась после grounding)'), isolation)} }}")
        resolve_blocks.append(
            f"{{\n    {get_line}{base_check}\n"
            f"    if (__mte_{s}.Pinned) {{ {refuse_stmt(oid, _cs(label + ': элемент закреплён (Pinned) — перенос невозможен'), isolation)} }}\n"
            f"    __mtIds_{s}.Add(__mte_{s}.Id);\n"
            f"    __mtEls_{s}.Add(__mte_{s});\n"
            f"    var __mtlp_{s} = __mte_{s}.Location as LocationPoint;\n"
            f"    var __mtlc_{s} = __mte_{s}.Location as LocationCurve;\n"
            f"    __mtBeforePt_{s}.Add(__mtlp_{s} != null ? __mtlp_{s}.Point : null);\n"
            f"    __mtBefore0_{s}.Add(__mtlc_{s} != null ? __mtlc_{s}.Curve.GetEndPoint(0) : null);\n"
            f"    __mtBefore1_{s}.Add(__mtlc_{s} != null ? __mtlc_{s}.Curve.GetEndPoint(1) : null);\n"
            f"    ConnectorManager __mtcm_{s} = null;\n"
            f"    MEPCurve __mtmc_{s} = __mte_{s} as MEPCurve;\n"
            f"    FamilyInstance __mtfi_{s} = __mte_{s} as FamilyInstance;\n"
            f"    if (__mtmc_{s} != null) __mtcm_{s} = __mtmc_{s}.ConnectorManager;\n"
            f"    else if (__mtfi_{s} != null && __mtfi_{s}.MEPModel != null) __mtcm_{s} = __mtfi_{s}.MEPModel.ConnectorManager;\n"
            f"    if (__mtcm_{s} != null)\n"
            f"        foreach (Connector __mtc_{s} in __mtcm_{s}.Connectors)\n"
            f"            if (__mtc_{s}.IsConnected) __mtConnBefore_{s}++;\n"
            # КРУГ ПОСЛЕДСТВИЙ, СНЯТЫЙ ДО ХОДА (22.08.2026). Обе величины
            # читаются здесь, потому что ПОСЛЕ MoveElements «как было» уже не
            # спросить: сравнивать не с чем — ровно та же причина, по которой
            # рядом снимаются точка, концы и коннекторы.
            f"    var __mtins_{s} = new List<string>();\n"
            f"    HostObject __mtho_{s} = __mte_{s} as HostObject;\n"
            f"    if (__mtho_{s} != null)\n"
            f"        foreach (ElementId __mtii_{s} in __mtho_{s}.FindInserts(true, true, false, false))\n"
            f"            __mtins_{s}.Add(__mtii_{s}.ToString());\n"
            f"    __mtInsBefore_{s}.Add(__mtins_{s});\n"
            f"    var __mtjn_{s} = new List<string>();\n"
            # 🔴 ОТКАЗ ЧТЕНИЯ НЕ ГЛОТАЕТСЯ, А НАЗЫВАЕТСЯ. `GetJoinedElements`
            # несёт три задокументированные ловушки (индекс `data/api_traps`:
            # ArgumentException «документ не проектный / элемент не найден в
            # документе» + два ArgumentNull). Пустой catch дал бы пустой
            # список «до», и «ничего не потеряно» стало бы истинным по
            # построению — это и есть зелёный по построению, против которого
            # заведена вся волна. Поэтому флаг едет в квитанцию.
            f"    try {{ foreach (ElementId __mtji_{s} in JoinGeometryUtils.GetJoinedElements(doc, __mte_{s})) __mtjn_{s}.Add(__mtji_{s}.ToString()); }}\n"
            f"    catch {{ __mtJoinRead_{s} = false; }}\n"
            f"    __mtJoinBefore_{s}.Add(__mtjn_{s});\n"
            # ЗАМОК АВТОРА — ЗАМЕР ПО НАСТОЯЩЕМУ ЗДАНИЮ, 22.08.2026. В MNVNK
            # `OST_Constraints` — 1 256 штук, ВСЕ класса Dimension, и 1 233 из
            # них (98.2 %) С ЗАМКОМ. Замок это запрет геометрии разъехаться,
            # поставленный рукой автора; подвинуть удерживаемое им — либо
            # переезд партнёра, либо отказ Ревита, и оба исхода до сих пор были
            # для квитанции невидимы.
            #
            # 🔴 ЧТО ЭТО ЧИСЛО НЕ ЗНАЧИТ, И ЭТО ЧАСТЬ ЗАМЕРА. Ссылки тех же
            # размеров раскладываются так: <Эскиз> 1 233 · Опорные плоскости
            # 1 233 · Уровни 44 · СТЕНЫ 2 (из 2 513). То есть почти все замки
            # держат ЭСКИЗ и ОПОРНУЮ ПЛОСКОСТЬ — внутреннюю параметрику, — а
            # не пару элементов модели. Для переноса стены круг замков в этом
            # здании близок к пустому, и прибор скажет это ЧИСЛОМ вместо
            # молчания. Прибор нужен не потому, что здесь много, а потому что
            # «пусто» и «не спрашивали» до него были одним и тем же ответом.
            #
            # ЦЕНА — ОДИН ВЫЗОВ НА ЦЕЛЬ. `Element.GetDependentElements` с
            # `ElementClassFilter(typeof(Dimension))` спрашивает САМУ цель, а
            # не обходит соседей; 6/6 версий, ловушек в индексе НОЛЬ.
            f"    foreach (ElementId __mtdi_{s} in __mte_{s}.GetDependentElements(new ElementClassFilter(typeof(Dimension))))\n"
            f"    {{\n"
            f"        Dimension __mtd_{s} = doc.GetElement(__mtdi_{s}) as Dimension;\n"
            f"        if (__mtd_{s} == null) continue;\n"
            f"        __mtDimsSeen_{s}++;\n"
            # МНОГОСЕГМЕНТНЫЙ РАЗМЕР НЕ СУДИМ, И ЭТО СКАЗАНО ЧИСЛОМ. Autodesk
            # про `Dimension.IsLocked` (prose, 6/6): свойство НЕЛЬЗЯ ЗАДАТЬ у
            # линейного размера более чем с одним сегментом — замки там живут
            # посегментно (`DimensionSegment.IsLocked`). Судить такой размер
            # одним булевым значило бы подписать то, чего не читали; его число
            # уезжает в квитанцию отдельным полем.
            f"        if (__mtd_{s}.NumberOfSegments > 1) {{ __mtDimsMulti_{s}++; continue; }}\n"
            f"        if (__mtd_{s}.IsLocked) __mtLockedDims_{s}.Add(__mtdi_{s});\n"
            f"    }}\n"
            f"}}")
    decl = (
        f"List<ElementId> __mtIds_{s} = new List<ElementId>();\n"
        f"List<Element> __mtEls_{s} = new List<Element>();\n"
        f"List<XYZ> __mtBeforePt_{s} = new List<XYZ>();\n"
        f"List<XYZ> __mtBefore0_{s} = new List<XYZ>();\n"
        f"List<XYZ> __mtBefore1_{s} = new List<XYZ>();\n"
        f"List<List<string>> __mtInsBefore_{s} = new List<List<string>>();\n"
        f"List<List<string>> __mtJoinBefore_{s} = new List<List<string>>();\n"
        f"List<ElementId> __mtLockedDims_{s} = new List<ElementId>();\n"
        f"bool __mtJoinRead_{s} = true;\n"
        f"int __mtDimsSeen_{s} = 0;\n"
        f"int __mtDimsMulti_{s} = 0;\n"
        f"int __mtConnBefore_{s} = 0;")
    create = (
        f"// move_elements {cs_line_comment_fragment(oid)}\n"
        f"doc.Regenerate();\n"
        + "\n".join(resolve_blocks) + "\n"
        f"XYZ __mtDelta_{s} = new XYZ(U({dx}), U({dy}), U({dz}));\n"
        f"try {{ ElementTransformUtils.MoveElements(doc, __mtIds_{s}, __mtDelta_{s}); doc.Regenerate(); }}\n"
        f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"MoveElements: \" + __ex_{s}.Message', isolation)} }}")
    post = [
        WitnessCheck(
            obligation_key="location", reader_cs="",
            verdict_cs=(
                f"    for (int __mti_{s} = 0; __mti_{s} < __mtEls_{s}.Count; __mti_{s}++)\n"
                f"    {{\n"
                f"        Element __mte2_{s} = __mtEls_{s}[__mti_{s}];\n"
                f"        var __mtlp2_{s} = __mte2_{s}.Location as LocationPoint;\n"
                f"        XYZ __mtbp_{s} = __mtBeforePt_{s}[__mti_{s}];\n"
                f"        if (__mtlp2_{s} != null && __mtbp_{s} != null &&\n"
                f"            (Math.Abs(MM(__mtlp2_{s}.Point.X) - (MM(__mtbp_{s}.X) + {dx})) > {htol} ||\n"
                f"             Math.Abs(MM(__mtlp2_{s}.Point.Y) - (MM(__mtbp_{s}.Y) + {dy})) > {htol} ||\n"
                f"             Math.Abs(MM(__mtlp2_{s}.Point.Z) - (MM(__mtbp_{s}.Z) + {dz})) > {htol}))\n"
                f"            __post.Add({_cs(oid + ': targets[')} + __mti_{s} + {_cs('] точка не сдвинулась на delta_mm (geometry)')});\n"
                f"        var __mtlc2_{s} = __mte2_{s}.Location as LocationCurve;\n"
                f"        XYZ __mtb0_{s} = __mtBefore0_{s}[__mti_{s}];\n"
                f"        XYZ __mtb1_{s} = __mtBefore1_{s}[__mti_{s}];\n"
                f"        if (__mtlc2_{s} != null && __mtb0_{s} != null && __mtb1_{s} != null)\n"
                f"        {{\n"
                f"            XYZ __mta_{s} = __mtlc2_{s}.Curve.GetEndPoint(0);\n"
                f"            XYZ __mtb_{s} = __mtlc2_{s}.Curve.GetEndPoint(1);\n"
                f"            if (Math.Abs(MM(__mta_{s}.X) - (MM(__mtb0_{s}.X) + {dx})) > {htol} ||\n"
                f"                Math.Abs(MM(__mta_{s}.Y) - (MM(__mtb0_{s}.Y) + {dy})) > {htol} ||\n"
                f"                Math.Abs(MM(__mta_{s}.Z) - (MM(__mtb0_{s}.Z) + {dz})) > {htol} ||\n"
                f"                Math.Abs(MM(__mtb_{s}.X) - (MM(__mtb1_{s}.X) + {dx})) > {htol} ||\n"
                f"                Math.Abs(MM(__mtb_{s}.Y) - (MM(__mtb1_{s}.Y) + {dy})) > {htol} ||\n"
                f"                Math.Abs(MM(__mtb_{s}.Z) - (MM(__mtb1_{s}.Z) + {dz})) > {htol})\n"
                f"                __post.Add({_cs(oid + ': targets[')} + __mti_{s} + {_cs('] концы не сдвинулись на delta_mm (geometry)')});\n"
                f"        }}\n"
                f"    }}\n"),
            message="target не сдвинулся на delta_mm (geometry)",
            # 🔴 СТАДИЯ ОПЕРАЦИИ (07.09.2026, F1/C01). Предикат сверяет
            # ТЕКУЩЕЕ положение со СНИМКОМ, снятым ДО ЭТОГО переноса, плюс
            # delta ЭТОГО переноса. На стадии final «текущее» — это конец всей
            # программы, и второй законный `move_elements` той же цели уводит
            # элемент ещё на свою delta: `+10/+20/+30` и следом `-5/0/+5` дают
            # расхождение 5 мм при допуске location_mm = 1.0 — ГАРАНТИРОВАННЫЙ
            # ложный отказ и откат на верно построенной программе. Остальные
            # свидетели переноса (коннекторы, наклон, вставки, замки размеров)
            # к порядку не чувствительны и остаются финальными.
            stage="operation",
            tol=htol, style="plain"),
        WitnessCheck(
            obligation_key="connectors", reader_cs="",
            verdict_cs=(
                f"    int __mtConnAfter_{s} = 0;\n"
                f"    foreach (Element __mte3_{s} in __mtEls_{s})\n"
                f"    {{\n"
                f"        ConnectorManager __mtcm2_{s} = null;\n"
                f"        MEPCurve __mtmc2_{s} = __mte3_{s} as MEPCurve;\n"
                f"        FamilyInstance __mtfi2_{s} = __mte3_{s} as FamilyInstance;\n"
                f"        if (__mtmc2_{s} != null) __mtcm2_{s} = __mtmc2_{s}.ConnectorManager;\n"
                f"        else if (__mtfi2_{s} != null && __mtfi2_{s}.MEPModel != null) __mtcm2_{s} = __mtfi2_{s}.MEPModel.ConnectorManager;\n"
                f"        if (__mtcm2_{s} != null)\n"
                f"            foreach (Connector __mtc2_{s} in __mtcm2_{s}.Connectors)\n"
                f"                if (__mtc2_{s}.IsConnected) __mtConnAfter_{s}++;\n"
                f"    }}\n"
                f"    if (__mtConnBefore_{s} != __mtConnAfter_{s})\n"
                f"        __post.Add({_cs(oid + ': подключённых коннекторов стало ')} + __mtConnAfter_{s} + {_cs(', было ')} + __mtConnBefore_{s} + {_cs(' (topology)')});\n"),
            message="connector count changed across targets (topology)",
            style="plain"),
        WitnessCheck(
            obligation_key="slope", reader_cs="",
            verdict_cs=(
                f"    for (int __mtj_{s} = 0; __mtj_{s} < __mtEls_{s}.Count; __mtj_{s}++)\n"
                f"    {{\n"
                f"        Element __mte4_{s} = __mtEls_{s}[__mtj_{s}];\n"
                f"        var __mtlc3_{s} = __mte4_{s}.Location as LocationCurve;\n"
                f"        XYZ __mtb0b_{s} = __mtBefore0_{s}[__mtj_{s}];\n"
                f"        XYZ __mtb1b_{s} = __mtBefore1_{s}[__mtj_{s}];\n"
                f"        if (__mtlc3_{s} != null && __mtb0b_{s} != null && __mtb1b_{s} != null)\n"
                f"        {{\n"
                f"            double __mtSlopeBefore_{s} = MM(__mtb1b_{s}.Z) - MM(__mtb0b_{s}.Z);\n"
                f"            XYZ __mtA2_{s} = __mtlc3_{s}.Curve.GetEndPoint(0);\n"
                f"            XYZ __mtB2_{s} = __mtlc3_{s}.Curve.GetEndPoint(1);\n"
                f"            double __mtSlopeAfter_{s} = MM(__mtB2_{s}.Z) - MM(__mtA2_{s}.Z);\n"
                f"            if (Math.Abs(__mtSlopeAfter_{s} - __mtSlopeBefore_{s}) > {htol})\n"
                f"                __post.Add({_cs(oid + ': targets[')} + __mtj_{s} + {_cs('] наклон изменился (semantic)')});\n"
                f"        }}\n"
                f"    }}\n"),
            message="LocationCurve target slope changed (semantic)",
            tol=htol, style="plain"),
        WitnessCheck(
            obligation_key="hosted_inserts", reader_cs="",
            verdict_cs=(
                f"    for (int __mtk_{s} = 0; __mtk_{s} < __mtEls_{s}.Count; __mtk_{s}++)\n"
                f"    {{\n"
                f"        HostObject __mtho2_{s} = __mtEls_{s}[__mtk_{s}] as HostObject;\n"
                f"        if (__mtho2_{s} == null) continue;\n"
                f"        var __mtnow_{s} = new HashSet<string>();\n"
                f"        foreach (ElementId __mtii2_{s} in __mtho2_{s}.FindInserts(true, true, false, false))\n"
                f"            __mtnow_{s}.Add(__mtii2_{s}.ToString());\n"
                f"        foreach (string __mtwas_{s} in __mtInsBefore_{s}[__mtk_{s}])\n"
                f"            if (!__mtnow_{s}.Contains(__mtwas_{s}))\n"
                f"                __post.Add({_cs(oid + ': targets[')} + __mtk_{s} + {_cs('] потерял размещённый в нём элемент ')} + __mtwas_{s} + {_cs(' (topology)')});\n"
                f"    }}\n"),
            message="host lost a door/window it carried (topology)",
            style="plain"),
        WitnessCheck(
            obligation_key="locked_dimensions", reader_cs="",
            verdict_cs=(
                f"    foreach (ElementId __mtld_{s} in __mtLockedDims_{s})\n"
                f"    {{\n"
                f"        Dimension __mtd2_{s} = doc.GetElement(__mtld_{s}) as Dimension;\n"
                f"        if (__mtd2_{s} == null || !__mtd2_{s}.IsLocked)\n"
                f"            __post.Add({_cs(oid + ': замок размера ')} + __mtld_{s}.ToString() + {_cs(' не пережил перенос (topology)')});\n"
                f"    }}\n"),
            message="an authored dimension lock did not survive the move (topology)",
            style="plain"),
    ]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    var __mtIdStrs_{s} = new List<string>();\n"
        f"    foreach (ElementId __mtrid_{s} in __mtIds_{s}) __mtIdStrs_{s}.Add(__mtrid_{s}.ToString());\n"
        f"    __rb[\"moved_ids\"] = __mtIdStrs_{s};\n"
        f"    __rb[\"count\"] = __mtIds_{s}.Count;\n"
        # 🔴 СОЕДИНЕНИЕ, ПОТЕРЯННОЕ ПРИ ПЕРЕНОСЕ, — ФАКТ, А НЕ НАРУШЕНИЕ, И
        # ПРИЧИНА НАЗВАНА. Отодвинуть перегородку от стены, к которой она
        # примыкала, — обычная перепланировка, и соединение там пропадает
        # ЗАКОННО. Сторож на этом краснил бы правильную работу, а в строгом
        # режиме откатывал бы всю программу (`report_posts=False`), то есть
        # цена ложного красного здесь несимметрична — тот же довод, по
        # которому названным отсутствием живёт форма границы у площадки.
        # Поэтому число и имена едут в квитанцию, и автор видит, ЧТО он
        # разъединил, вместо тишины.
        f"    var __mtjlost_{s} = new List<string>();\n"
        f"    for (int __mtm_{s} = 0; __mtm_{s} < __mtEls_{s}.Count; __mtm_{s}++)\n"
        f"    {{\n"
        f"        var __mtjnow_{s} = new HashSet<string>();\n"
        f"        try {{ foreach (ElementId __mtjj_{s} in JoinGeometryUtils.GetJoinedElements(doc, __mtEls_{s}[__mtm_{s}])) __mtjnow_{s}.Add(__mtjj_{s}.ToString()); }}\n"
        f"        catch {{ __mtJoinRead_{s} = false; }}\n"
        f"        foreach (string __mtjw_{s} in __mtJoinBefore_{s}[__mtm_{s}])\n"
        f"            if (!__mtjnow_{s}.Contains(__mtjw_{s})) __mtjlost_{s}.Add(__mtjw_{s});\n"
        f"    }}\n"
        f"    __rb[\"joins_lost_count\"] = __mtjlost_{s}.Count;\n"
        f"    __rb[\"joins_lost\"] = __mtjlost_{s}.GetRange(0, Math.Min({_NEIGHBOUR_ID_CAP}, __mtjlost_{s}.Count));\n"
        # «Спросили и получили ноль» и «спросить не вышло» — РАЗНЫЕ факты, и
        # без этого флага они читались бы одинаково.
        f"    __rb[\"joins_read\"] = __mtJoinRead_{s};\n"
        f"    __rb[\"dims_dependent\"] = __mtDimsSeen_{s};\n"
        f"    __rb[\"dims_locked\"] = __mtLockedDims_{s}.Count;\n"
        f"    __rb[\"dims_multisegment_unjudged\"] = __mtDimsMulti_{s};\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


# 🔴 РЕЭКСПОРТ, А НЕ ОБЪЯВЛЕНИЕ (01.09.2026). Код живёт у распорядителя
# (`kir/diag.py`), потому что его читали СЕМЬ эмиттеров и реестр: ленивый
# импорт `ops_site -> authoring` тянул реестр в эмиссию, а через неё —
# рисовальщика плана в компилятор. Имя остаётся здесь ровно затем, чтобы
# ни один из семи эмиттеров не двинулся: `from kir.authoring import
# EMIT_UNSUPPORTED` продолжает работать и означает то же самое.
# (импортирован выше из kir.diag)








def _emit_floor(op: dict, ver: str, stamp: str,
                isolation: str = "atomic") -> tuple[str, str, str, str]:
    oid = op["id"]
    s = _safe(oid)
    holes = op.get("holes") or []
    if holes and ver < "2022":
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED, op_id=oid, field_name="holes",
            message_ru=f"отверстия в перекрытии не поддержаны на Revit {ver} "
                       f"(NewFloor без holes; Floor.Create — с 2022)")])
    lv = _gid(op, "level")
    g_type = _gid(op, "type") if isinstance(op.get("type"), dict) and "__grounded__" in op["type"] else None
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    decl = f"Floor __el_{s} = null;\n" + type_assignment_declarations(oid)
    if g_type and g_type.get("in_emit") == IN_EMIT_DEFAULT:
        ft = (f"FloorType __ft_{s} = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.FloorType)) as FloorType;\n"
              f"if (__ft_{s} == null) {{ {refuse_stmt(oid, _cs('в документе нет типа перекрытия по умолчанию'), isolation)} }}")
    # ТИП, СОЗДАННЫЙ ЭТОЙ ЖЕ ПРОГРАММОЙ (`create_wall_type` с host_kind=
    # "floor"). Ни `GetElement`, ни сторож дрейфа здесь не нужны и были бы
    # ложью: элемент создан выше, в этой же транзакции, и его переменная уже
    # держит нужный род. Та же ветка и тот же довод, что у `create_wall.type`
    # с 23.08 — без неё оп получал грунтованную ссылку без `id` и падал
    # KIR-P000 «внутренняя ошибка компилятора» (замер 24.08.2026).
    elif g_type and g_type.get("via") == "ref":
        ft = f"FloorType __ft_{s} = __el_{_safe(g_type['ref'])};"
    else:
        ft = (f"FloorType __ft_{s} = doc.GetElement({_eid(g_type['id'], ver, oid)}) as FloorType;\n"
              f"if (__ft_{s} == null) {{ {refuse_stmt(oid, _cs('тип перекрытия не найден (модель изменилась после grounding)'), isolation)} }}")
    outline = op["outline"]
    if ver >= "2022":
        geo = [f"var __loops_{s} = new List<CurveLoop>();"]
        geo += _loop_pts(outline, f"__ol_{s}")
        geo.append(f"__loops_{s}.Add(__ol_{s});")
        for hi, hole in enumerate(holes):
            geo += _loop_pts(hole, f"__hl_{s}_{hi}")
            geo.append(f"__loops_{s}.Add(__hl_{s}_{hi});")
        structural = bool(op.get("structural", False))
        if structural:
            make = (f"__el_{s} = Floor.Create(doc, __loops_{s}, __ft_{s}.Id, __lv_{s}.Id, "
                    f"true, null, 0.0);")
        else:
            make = f"__el_{s} = Floor.Create(doc, __loops_{s}, __ft_{s}.Id, __lv_{s}.Id);"
    else:
        # 2021: legacy NewFloor over a CurveArray (API-axis divergence, SPEC 11.2)
        structural = bool(op.get("structural", False))
        geo = [f"CurveArray __ca_{s} = new CurveArray();"]
        n = len(outline)
        for k in range(n):
            a, b = outline[k], outline[(k + 1) % n]
            geo.append(f"__ca_{s}.Append(Line.CreateBound(P({a[0]}, {a[1]}, 0), P({b[0]}, {b[1]}, 0)));")
        make = f"__el_{s} = doc.Create.NewFloor(__ca_{s}, __ft_{s}, __lv_{s}, {'true' if structural else 'false'});"
    # P1 DOF-completeness: смещение пола от уровня (51% полов «демо»).
    height_offset = op.get("height_offset_mm")
    ho_set = ""
    if height_offset is not None:
        ho_set = (
            f"\nParameter __fho_{s} = __el_{s}.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM);\n"
            f"if (__fho_{s} == null || __fho_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('FLOOR_HEIGHTABOVELEVEL_PARAM недоступен у перекрытия'), isolation)} }}\n"
            f"__fho_{s}.Set(U({height_offset}));")
    create = (f"// create_floor {cs_line_comment_fragment(oid)}\n{ft}\n{lv_res}\n"
              + "\n".join(geo) + f"\n{make}\n"
              f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('создание перекрытия вернуло null'), isolation)} }}\n"
              + ho_set
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    xs = [pt[0] for pt in outline]; ys = [pt[1] for pt in outline]
    ftol = tolerances("create_floor")
    checks: list[WitnessCheck] = [
        type_assignment_witness(f"__el_{s}", f"__ft_{s}", oid),
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
        WitnessCheck(
            obligation_key="structural",
            reader_cs=f"    var __struct = __el_{s}.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL);\n",
            verdict_cs=(
                f"    if (__struct == null || __struct.AsInteger() != {1 if structural else 0})\n"
                f"        __post.Add({_cs(oid + ': structural flag mismatch (semantic)')});\n"),
            message="structural flag mismatch (semantic)",
            style="guard"),
        bbox_extents_witness(
            f"__el_{s}", oid, min(xs), max(xs), min(ys), max(ys),
            ftol["bbox_mm"]),
        # ФОРМА РЯДОМ С ГАБАРИТОМ, А НЕ ВМЕСТО НЕГО: они судят РАЗНОЕ.
        # Габарит ловит дугу, заменённую хордой (её концы те же, и в
        # мультимножество вершин подмена не попадает); форма ловит сдвинутый
        # внутренний угол, потерянный вырез и заполненное отверстие, которых
        # габарит не видит по построению. Снять один ради другого значило бы
        # обменять одну слепоту на другую.
        sketch_loops_witness(
            f"__el_{s}", oid, [outline] + [h for h in holes],
            ftol["sketch_mm"]),
    ]
    if height_offset is not None:
        checks.append(WitnessCheck(
            obligation_key="height_offset",
            reader_cs=(
                f"    var __fhop = __el_{s}.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM);\n"),
            verdict_cs=(
                f"    if (__fhop == null || Math.Abs(MM(__fhop.AsDouble()) - {height_offset}) > {ftol['height_offset_mm']})\n"
                f"        __post.Add({_cs(oid + ': height offset mismatch (geometry)')});\n"),
            message="height offset mismatch (geometry)",
            tol=ftol["height_offset_mm"],
            style="guard"))
    return decl, create, checks, _readback_block(s, oid, stamp,
        identity_version=ver, extra_rows_cs=type_assignment_readback_cs(f"__el_{s}", oid))


def _emit_column(op: dict, ver: str, stamp: str,
                 isolation: str = "atomic") -> tuple[str, str, str, str]:
    oid = op["id"]
    s = _safe(oid)
    x, y = op["xy"][0], op["xy"][1]
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    stype = ("Autodesk.Revit.DB.Structure.StructuralType.Column"
             if op.get("category", "structural") == "structural"
             else "Autodesk.Revit.DB.Structure.StructuralType.NonStructural")
    has_rotation = "rotation_deg" in op
    rotation_deg = float(op.get("rotation_deg", 0.0))
    rotate = ""
    if rotation_deg != 0.0:
        rotate = (
            f"Line __axis_{s} = Line.CreateUnbound(P({x}, {y}, 0), XYZ.BasisZ);\n"
            f"ElementTransformUtils.RotateElement(doc, __el_{s}.Id, "
            f"__axis_{s}, {rotation_deg} * Math.PI / 180.0);\n")
    decl = f"FamilyInstance __el_{s} = null;"
    # P1 DOF-completeness (fidelity audit 2026-07-21): столбовая вертикаль —
    # на «демо» 100% колонн top-attached, 99% с base-offset; без этих сетов
    # каждая колонна пересобиралась бы as-placed высотой символа.  Absent →
    # эмиссия байт-в-байт историческая.
    base_offset = op.get("base_offset_mm")
    base_set = ""
    if base_offset is not None:
        base_set = (
            f"\nParameter __cbo_{s} = __el_{s}.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM);\n"
            f"if (__cbo_{s} == null || __cbo_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('FAMILY_BASE_LEVEL_OFFSET_PARAM недоступен у колонны'), isolation)} }}\n"
            f"__cbo_{s}.Set(U({base_offset}));")
    top = op.get("top_level")
    top_res = ""
    top_set = ""
    top_idexpr = None
    if isinstance(top, dict) and "__grounded__" in top:
        ctl = _gid(op, "top_level")
        if ctl.get("via") == "ref":
            rv = "__el_" + _safe(ctl["ref"])
            top_res = f"\nLevel __ctl_{s} = {rv};"
            top_idexpr = f"{rv}.Id.ToString()"
        else:
            top_res = (
                f"\nLevel __ctl_{s} = doc.GetElement({_eid(ctl['id'], ver, oid)}) as Level;\n"
                f"if (__ctl_{s} == null) {{ {refuse_stmt(oid, _cs('top_level: уровень не найден (модель изменилась после grounding)'), isolation)} }}")
            top_idexpr = _cs(str(ctl["id"]))
        top_offset = op.get("top_offset_mm")
        cto_literal = "0.0" if top_offset is None else f"U({top_offset})"
        top_set = (
            f"\nParameter __ctp_{s} = __el_{s}.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);\n"
            f"if (__ctp_{s} == null || __ctp_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('FAMILY_TOP_LEVEL_PARAM недоступен у колонны'), isolation)} }}\n"
            f"__ctp_{s}.Set(__ctl_{s}.Id);\n"
            f"try {{ Parameter __cto_{s} = __el_{s}.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM); "
            f"if (__cto_{s} != null && !__cto_{s}.IsReadOnly) __cto_{s}.Set({cto_literal}); }} catch {{ }}")
    # top_xy present => a SLANTED column.  Revit models a slanted column as a
    # location CURVE from base to top, so the point overload cannot express it
    # at all — every column authored through it comes out vertical.  The line
    # runs between the two levels' own elevations plus their offsets, so the
    # ends land exactly where the level constraints say, and the top-level
    # PARAMETER writes are skipped: the curve already defines the top, and
    # setting them afterwards would fight the geometry.
    top_xy = op.get("top_xy")
    if top_xy is None:
        place = (f"__el_{s} = doc.Create.NewFamilyInstance("
                 f"P({x}, {y}, 0), __sy_{s}, __lv_{s}, {stype});\n")
        constrain = base_set + top_set
        # 🔴 Э3.1 19.08: ВЫВЕДЕННЫЙ ВЕРТИКАЛЬНЫЙ ГАБАРИТ. Он следствие
        # программы — низ это отметка разрешённого уровня плюс нижнее
        # смещение, верх это отметка верхнего уровня плюс верхнее, — и модели
        # объявлять его не надо. Имена вынесены в `decl` и лишь присваиваются
        # здесь: `__lv_`/`__ctl_` объявлены ВНУТРИ create, и при обёртке
        # per_op имя умирает на закрывающей скобке (CS0103). Тот же контракт
        # областей видимости, что у `__axz0_`/`__axz1_` наклонной колонны,
        # купленный шестью отказами Roslyn 10.08.
        if top_idexpr is not None:
            _c_toff = op.get("top_offset_mm")
            decl += (f"\ndouble __vexLo_{s} = 0.0;"
                     f"\ndouble __vexHi_{s} = 0.0;")
            constrain += (
                f"\n__vexLo_{s} = MM(__lv_{s}.Elevation)"
                + ("" if base_offset is None else f" + {base_offset}") + ";\n"
                f"__vexHi_{s} = MM(__ctl_{s}.Elevation)"
                + ("" if _c_toff is None else f" + {_c_toff}") + ";\n")
    else:
        tx, ty = top_xy[0], top_xy[1]
        # Отметки концов оси ВЫНЕСЕНЫ в decl и лишь присваиваются в create.
        # Свидетель наклонной колонны читает их после закрытия блока, а
        # `__lv_`/`__ctl_` объявлены ВНУТРИ create — при per_op обёртке имя
        # умирает на скобке, и это CS0103. Замер 10.08 на настоящем разборе
        # `night_b13`: 6 отказов Roslyn из 6 проверок, «The name
        # '__lv_e287178' does not exist in the current context», все шесть
        # версий. Тот же контракт областей видимости, что у `__pfh_`/`__hl_`;
        # структурный сторож — `test_emitter_scope_contract`, который эту
        # ветвь не видел, пока в корпус не добавили наклонную колонну.
        base_z = f"__axz0_{s}"
        top_z = f"__axz1_{s}"
        decl += f"\ndouble __axz0_{s} = 0.0;\ndouble __axz1_{s} = 0.0;"
        base_z_expr = f"__lv_{s}.Elevation" + (
            "" if base_offset is None else f" + U({base_offset})")
        top_z_expr = f"__ctl_{s}.Elevation" + (
            "" if op.get("top_offset_mm") is None
            else f" + U({op['top_offset_mm']})")
        # P() converts mm->feet for the plan coords; Level.Elevation is
        # ALREADY feet, so the two are combined component-wise rather than
        # pushed through P() again.
        place = (
            f"XYZ __b_{s} = P({x}, {y}, 0);\n"
            f"XYZ __tp_{s} = P({tx}, {ty}, 0);\n"
            f"__axz0_{s} = {base_z_expr};\n"
            f"__axz1_{s} = {top_z_expr};\n"
            f"Line __axis_{s} = Line.CreateBound(\n"
            f"    new XYZ(__b_{s}.X, __b_{s}.Y, {base_z}),\n"
            f"    new XYZ(__tp_{s}.X, __tp_{s}.Y, {top_z}));\n"
            f"__el_{s} = doc.Create.NewFamilyInstance("
            f"__axis_{s}, __sy_{s}, __lv_{s}, {stype});\n")
        constrain = base_set
    create = (f"// create_column {cs_line_comment_fragment(oid)}\n"
              + _symbol_res(op, s, oid, ver, isolation) + f"\n{lv_res}" + top_res + "\n"
              + place
              + f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('NewFamilyInstance вернул null'), isolation)} }}\n"
              + rotate
              + constrain
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    ctols = tolerances("create_column")
    rtol = ctols["rotation_deg"]
    rotation_post = ""
    if has_rotation:
        rotation_post = (
            f"    else\n    {{\n"
            f"        double __wantRot_{s} = {rotation_deg} * Math.PI / 180.0;\n"
            f"        double __rotDelta_{s} = Math.Atan2(\n"
            f"            Math.Sin(__loc.Rotation - __wantRot_{s}),\n"
            f"            Math.Cos(__loc.Rotation - __wantRot_{s}));\n"
            # Допуск поворота эмитируется ВЫРАЖЕНИЕМ (`Math.PI / 1800.0`), а
            # не числом радиан: делитель считается из реестрового 0.1deg в
            # Decimal, поэтому байты те же, а число адресуемо.
            f"        if (Math.Abs(__rotDelta_{s}) > Math.PI / {rtol.deg_rad_divisor})\n"
            f"            __post.Add({_cs(oid + ': rotation mismatch (geometry, tolerance 0.1deg)')});\n"
            f"    }}\n")
    ctol = ctols["location_mm"]
    if top_xy is None:
        checks: list[WitnessCheck] = [WitnessCheck(
            obligation_key="location",
            reader_cs=f"    var __loc = __el_{s}.Location as LocationPoint;\n",
            verdict_cs=(
                f"    if (__loc == null) __post.Add({_cs(oid + ': нет LocationPoint')});\n"
                f"    else if (Math.Abs(MM(__loc.Point.X) - {x}) > {ctol} || Math.Abs(MM(__loc.Point.Y) - {y}) > {ctol})\n"
                f"        __post.Add({_cs(oid + ': location mismatch (geometry)')});\n"),
            message="location mismatch (geometry)",
            tol=ctol,
            style="else_block")]
    else:
        # A slanted column has a LocationCURVE, so the point reader above would
        # find nothing.  Check what actually matters and what the location-line
        # mistake taught: the GEOMETRY.  Both plan ends, and the fact that the
        # axis really is inclined -- a column that silently came out vertical
        # would otherwise satisfy every other obligation.
        tx, ty = top_xy[0], top_xy[1]
        checks = [WitnessCheck(
            obligation_key="location",
            reader_cs=f"    var __lc = __el_{s}.Location as LocationCurve;\n",
            verdict_cs=(
                f"    if (__lc == null || __lc.Curve == null)\n"
                f"        __post.Add({_cs(oid + ': наклонная колонна без LocationCurve (geometry)')});\n"
                f"    else\n    {{\n"
                f"        XYZ __a0 = __lc.Curve.GetEndPoint(0);\n"
                f"        XYZ __a1 = __lc.Curve.GetEndPoint(1);\n"
                f"        bool __fwd = Math.Abs(MM(__a0.X) - {x}) <= {ctol}\n"
                f"            && Math.Abs(MM(__a0.Y) - {y}) <= {ctol};\n"
                f"        XYZ __base = __fwd ? __a0 : __a1;\n"
                f"        XYZ __top = __fwd ? __a1 : __a0;\n"
                f"        if (Math.Abs(MM(__base.X) - {x}) > {ctol}\n"
                f"            || Math.Abs(MM(__base.Y) - {y}) > {ctol}\n"
                f"            || Math.Abs(MM(__top.X) - {tx}) > {ctol}\n"
                f"            || Math.Abs(MM(__top.Y) - {ty}) > {ctol})\n"
                f"            __post.Add({_cs(oid + ': location mismatch (geometry)')});\n"
                f"        if (Math.Abs(MM(__base.Z) - MM({base_z})) > {ctol}\n"
                f"            || Math.Abs(MM(__top.Z) - MM({top_z})) > {ctol})\n"
                f"            __post.Add({_cs(oid + ': ось колонны не по уровням (geometry)')});\n"
                f"        if (Math.Abs(MM(__top.X) - MM(__base.X)) <= {ctol}\n"
                f"            && Math.Abs(MM(__top.Y) - MM(__base.Y)) <= {ctol})\n"
                f"            __post.Add({_cs(oid + ': колонна вышла вертикальной (geometry)')});\n"
                f"    }}\n"),
            message="location mismatch (geometry)",
            tol=ctol,
            style="guard")]
    # rotation_post is an `else` continuation of the POINT location check,
    # and a slanted column replaced that check with a self-contained guard —
    # so chaining it emitted a dangling `else` and C# that does not compile.
    # Skipping it is also the right semantics: a slanted column's orientation
    # is carried by its axis, and rotation_deg means nothing there.
    # Found by the offline compile gate, never by the live run: the live
    # program omitted rotation_deg (the op default), the LIFTED one states it.
    if rotation_post and top_xy is None:
        # Chained else-continuation of the location check (byte-glued); the
        # 0.1deg tolerance stays the historical C# EXPRESSION Math.PI/1800.0.
        checks.append(WitnessCheck(
            obligation_key="rotation", reader_cs="",
            verdict_cs=rotation_post,
            message="rotation mismatch (geometry, tolerance 0.1deg)",
            tol=rtol, style="else_block"))
    checks.append(WitnessCheck(
        obligation_key="structural_type", reader_cs="",
        verdict_cs=(
            f"    if (__el_{s}.StructuralType != {stype})\n"
            f"        __post.Add({_cs(oid + ': StructuralType mismatch (semantic)')});\n"),
        message="StructuralType mismatch (semantic)", style="guard"))
    checks.append(level_chain_witness(f"__el_{s}", oid, lv_idexpr))
    ctol_off = ctols
    if base_offset is not None:
        checks.append(WitnessCheck(
            obligation_key="base_offset",
            reader_cs=(
                f"    var __cbop = __el_{s}.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM);\n"),
            verdict_cs=(
                f"    if (__cbop == null || Math.Abs(MM(__cbop.AsDouble()) - {base_offset}) > {ctol_off['base_offset_mm']})\n"
                f"        __post.Add({_cs(oid + ': base offset mismatch (geometry)')});\n"),
            message="base offset mismatch (geometry)",
            tol=ctol_off["base_offset_mm"],
            style="guard"))
    # A slanted column's top is defined by its axis, not by the parameter —
    # we deliberately do not write it, so demanding it back would roll the
    # transaction back on every slanted column.
    if top_idexpr is not None and top_xy is None:
        checks.append(WitnessCheck(
            obligation_key="top_constraint",
            reader_cs=(
                f"    var __ctpp = __el_{s}.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);\n"),
            verdict_cs=(
                f"    if (__ctpp == null || __ctpp.AsElementId() == null || __ctpp.AsElementId().ToString() != {top_idexpr})\n"
                f"        __post.Add({_cs(oid + ': top constraint mismatch (topology)')});\n"),
            message="top constraint mismatch (topology)",
            style="guard"))
        # 🔴 Э3.1: ГЕОМЕТРИЯ ПРОТИВ ССЫЛКИ. Три проверки вокруг читают, куда
        # УКАЗЫВАЕТ параметр; эта читает, ДОКУДА ДОШЛО ТЕЛО. Односторонне:
        # `__post` ведёт к RollBack, наблюдавшийся дефект — недобор 1100 мм
        # (2500 вместо 3600 на 420 колоннах), а перебор бывает у семейства,
        # чья геометрия законно выступает за привязку. Маркер `__vex` — то,
        # чем обязательство гасится по ключу.
        vspan = ctols["vertical_span_mm"]
        checks.append(WitnessCheck(
            obligation_key="vertical_extent",
            reader_cs=(
                f"    var __vexBB_{s} = __el_{s}.get_BoundingBox(null);\n"),
            verdict_cs=(
                f"    if (__vexBB_{s} == null)\n"
                f"        __post.Add({_cs(oid + ': вертикальный габарит не прочитан (geometry)')});\n"
                f"    else\n    {{\n"
                f"        double __vexGot_{s} = MM(__vexBB_{s}.Max.Z) - MM(__vexBB_{s}.Min.Z);\n"
                f"        double __vexWant_{s} = __vexHi_{s} - __vexLo_{s};\n"
                f"        if (__vexGot_{s} < __vexWant_{s} - {vspan})\n"
                f"            __post.Add({_cs(oid + ': вертикальный габарит НЕ ДОХОДИТ до верхнего уровня (geometry)')});\n"
                f"    }}\n"),
            message="вертикальный габарит НЕ ДОХОДИТ до верхнего уровня (geometry)",
            tol=vspan,
            style="guard"))
        # 19.08: РАСШИРЕНО с «когда прислано» на «всегда при top_level».
        # Эмиттер ПИШЕТ ноль, когда смещение опущено (`cto_literal = "0.0"`), и
        # никто его не перечитывал: записанное и не прочитанное — обещание без
        # свидетеля. У стены этот же случай закрыт с 30.07.
        _toff_want = op.get("top_offset_mm")
        _toff_want = 0.0 if _toff_want is None else _toff_want
        checks.append(WitnessCheck(
            obligation_key="top_offset",
            reader_cs=(
                f"    var __ctop = __el_{s}.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM);\n"),
            verdict_cs=(
                f"    if (__ctop == null || Math.Abs(MM(__ctop.AsDouble()) - {_toff_want}) > {ctol_off['top_offset_mm']})\n"
                f"        __post.Add({_cs(oid + ': top offset mismatch (geometry)')});\n"),
            message="top offset mismatch (geometry)",
            tol=ctol_off["top_offset_mm"],
            style="guard"))
    return decl, create, checks, _readback_block(
        s, oid, stamp, location_rotation=has_rotation,
        vertical_extent=(top_xy is None and top_idexpr is not None), identity_version=ver)


def _hosted_curve_frame(
    wall: Mapping[str, Any],
    offset_mm: float,
) -> tuple[float, float, float, float]:
    """Insertion XY and unit tangent at distance along the host curve."""

    x0, y0, _ = _pt3(wall["p0_mm"])
    x1, y1, _ = _pt3(wall["p1_mm"])
    arc = wall.get("arc")
    if not isinstance(arc, Mapping):
        length = math.hypot(x1 - x0, y1 - y0)
        return (
            round(x0 + (x1 - x0) * offset_mm / length, 1),
            round(y0 + (y1 - y0) * offset_mm / length, 1),
            round((x1 - x0) / length, 6),
            round((y1 - y0) / length, 6),
        )

    center = arc["center_mm"]
    radius = float(arc["radius_mm"])
    x_axis = arc["x_axis"]
    y_axis = arc["y_axis"]
    start = float(arc["start_angle_rad"])
    end = float(arc["end_angle_rad"])

    def _point(angle: float) -> tuple[float, float]:
        ca, sa = math.cos(angle), math.sin(angle)
        return (
            float(center[0]) + radius * (
                ca * float(x_axis[0]) + sa * float(y_axis[0])),
            float(center[1]) + radius * (
                ca * float(x_axis[1]) + sa * float(y_axis[1])),
        )

    start_point, end_point = _point(start), _point(end)
    p0_is_start = math.hypot(start_point[0] - x0, start_point[1] - y0) \
        <= math.hypot(end_point[0] - x0, end_point[1] - y0)
    direction = 1.0 if p0_is_start else -1.0
    angle = (start + offset_mm / radius if p0_is_start
             else end - offset_mm / radius)
    px, py = _point(angle)
    tangent_x = direction * (
        -math.sin(angle) * float(x_axis[0])
        + math.cos(angle) * float(y_axis[0]))
    tangent_y = direction * (
        -math.sin(angle) * float(x_axis[1])
        + math.cos(angle) * float(y_axis[1]))
    tangent_norm = math.hypot(tangent_x, tangent_y)
    if tangent_norm <= 0.0:
        raise ValueError("host Arc has no plan tangent")
    return (
        round(px, 1), round(py, 1),
        round(tangent_x / tangent_norm, 6),
        round(tangent_y / tangent_norm, 6),
    )


def _emit_hosted(op: dict, ver: str, stamp: str, kind: str,
                 isolation: str = "atomic") -> tuple[str, str, str, str]:
    """window/door: distance along the actual host Line/Arc and local tangent.

    host: ref (same-program wall, ``__host_wall__`` attached by compiler.py's
    plan stage from KNOWN p0/p1 — px/py computed HERE, in Python, at compile
    time) OR element_id (28.07: an EXISTING wall the program never creates —
    compiler.py's plan stage looks ``host.value`` up in ``byid``, a table
    keyed by op-id STRINGS, so an int is never found there BY CONSTRUCTION,
    ``__host_wall__`` is never attached, and px/py cannot be Python constants
    at all).  The element_id branch therefore reads the host's ACTUAL
    LocationCurve live and asks Revit's own ``Curve.Evaluate(t, true)`` for
    the point at the normalized fraction ``offset/length`` along it — proven
    correct for BOTH Line and Arc by the Revit API itself (an Arc's native
    parameter is its angle, and for constant radius arc-length is exactly
    proportional to angle, so length-normalized == angle-normalized; api
    confirmed by reflection over RevitAPI.dll, all six versions:
    ``Curve.Evaluate(Double,Boolean)->XYZ``, ``Curve.Length``,
    ``LocationCurve.Curve``).  This is also where the compile-time-only
    "offset beyond wall end" law (KIR-T002, unexpressible for this branch —
    the real length is not known until runtime) MOVES to: a typed
    refuse_stmt if the live length is exceeded, never a silent overrun.
    """
    oid = op["id"]
    s = _safe(oid)
    host_sel = op["host"]
    off = op["offset_mm"]
    # audit F1: sill applies to BOTH kinds — a door on a multi-storey wall
    # carries an explicit sill from the host wall's level (absent -> 0.0, the
    # exact pre-existing door emission, byte-stable).
    sill = op.get("sill_mm", 0.0)
    if host_sel.get("by") == "ref":
        host_ref = host_sel["value"]
        hv = "__el_" + _safe(host_ref)
        wall = op[spec.SYNTHETIC_HOST_WALL]        # attached by the plan stage
        # Касательная (третий-четвёртый элементы) была нужна только
        # плоскости зеркала; сам вызов остаётся — он же проверяет,
        # что у хоста есть касательная в плане, и отказывает иначе.
        px, py = _hosted_curve_frame(wall, off)[:2]
        host_decl = ""
        host_res = ""
        pt_stmt = f"XYZ __pt_{s} = new XYZ(U({px}), U({py}), __hl_{s}.Elevation + U({sill}));\n"
        # location witness: px/py are Python constants (same-program host is
        # KNOWN geometry), so the post-check compares against them directly
        # — exactly the pre-existing byte shape.
        x_cmp, y_cmp = f"{px}", f"{py}"
    else:
        hv = f"__hw_{s}"
        host_decl = f"\nWall {hv} = null;\nXYZ __pt_{s} = null;"
        host_res = (
            f"{hv} = doc.GetElement({_eid(host_sel['value'], ver, oid)}) as Wall;\n"
            f"if ({hv} == null) {{ {refuse_stmt(oid, _cs('стена-хост не найдена (модель изменилась после grounding)'), isolation)} }}\n"
            f"LocationCurve __hlc_{s} = {hv}.Location as LocationCurve;\n"
            f"if (__hlc_{s} == null) {{ {refuse_stmt(oid, _cs('у стены-хоста нет продольной кривой (LocationCurve)'), isolation)} }}\n"
            f"Curve __hc_{s} = __hlc_{s}.Curve;\n"
            f"if (U({off}) > __hc_{s}.Length) {{ {refuse_stmt(oid, f'\"offset {off}мм за пределами стены-хоста (длина \" + MM(__hc_{s}.Length).ToString(\"F0\") + \"мм)\"', isolation)} }}\n"
            f"XYZ __hcpt_{s} = __hc_{s}.Evaluate(U({off}) / __hc_{s}.Length, true);\n")
        pt_stmt = f"__pt_{s} = new XYZ(__hcpt_{s}.X, __hcpt_{s}.Y, __hl_{s}.Elevation + U({sill}));\n"
        # location witness: the host's real geometry is unknown at compile
        # time — the expected point is the RUNTIME __pt_<s> the create block
        # itself computed (moved to decl-scope precisely so post can read
        # it), never a Python-side guess (design law 4, 28.07).
        x_cmp, y_cmp = f"MM(__pt_{s}.X)", f"MM(__pt_{s}.Y)"
    # Placement uses the host's location at this operation; the final witness
    # includes later explicit moves of either the hosted instance or its host.
    sx, sy, sz = final_shift(op)
    if sx:
        x_cmp = f"({x_cmp} + {sx})"
    if sy:
        y_cmp = f"({y_cmp} + {sy})"
    final_sill = sill + sz if sz else sill
    # audit F5: swing/mirror state — the enforced-state pattern cloned from
    # _emit_place, hosted-adapted.  NO rotation branch (a hosted instance's
    # orientation comes from its host); the mirror plane's normal runs ALONG
    # the host wall's direction (derived from __host_wall__ p0/p1 at compile
    # time, NEVER from rotation_deg — hosted ops have none), through the
    # insertion point, so mirroring swaps the swing side within the wall.
    # Absent flags -> zero new emission (byte-stable pre-existing programs).
    has_mirrored = "mirrored" in op
    has_hand = "hand_flipped" in op
    has_facing = "facing_flipped" in op
    # audit F5 v2 (2026-07-21, живые пробы P2/P3/P6 на «демо»): Mirrored у
    # Revit — ПРОИЗВОДНЫЙ признак (= HandFlipped XOR FacingFlipped), а
    # MirrorElements вдоль стены никогда не даёт Mirrored=T (P2: свидетель
    # ловит M=F) и валит ВЕСЬ commit на (M,H)=(T,T) (P3: RolledBack).
    # v2.2 (живой регресс двери×51 94/95→0 на v2.1): MirrorElements на
    # hosted-двери фатален для КОММИТА в принципе — дверь, пережившая
    # per_op после зеркала, валит финальный Commit (RolledBack; та же
    # сигнатура, что P3). Никаких зеркал на hosted; чётная пара при
    # CanFlip*=false — честный residual-refuse (ДЛ 0915x2032, 19171883).
    # Гипотеза на завтра: Δ-стена в ОБРАТНОМ направлении (p1→p0)
    # инвертирует начальные флипы создаваемой двери — путь без зеркал.
    mirror = ""
    # EXPERIMENT 2026-07-21 (mirror-COPY, откатить после замера): для double-flip
    # делаем зеркальный ДУБЛЬ (mirrorCopies=true), удаляем оригинал, читаем
    # состояние копии. Без refuse — чтобы увидеть фактический (H,F,M).
    # F5 v3 (экзамен ЛОТ31, 2026-07-21): семантические флипы двери ставятся
    # ЗЕРКАЛОМ-КОПИЕЙ (mirrorCopies=true), а НЕ flipHand/flipFacing — mirror
    # НЕ требует CanFlip, поэтому берёт flip-locked семейства (ДЛ 0915x2032,
    # Блок), которые Revit не флипает пост-факто.  Живо доказано: зеркало
    # нормалью ВДОЛЬ стены = hand-флип; нормалью ⟂ стене = facing-флип; оба =
    # (T,T) M=F (точечное отражение).  Каждый mirror-copy транзакционно-
    # безопасен (создаёт дубль, удаляем оригинал, ведём __el на копию).  M —
    # производный (= H XOR F), зеркало даёт консистентный M само.
    # In-place зеркало НЕ меняет семантич. флип (доказано — только копия
    # даёт новый зеркальный инстанс).  Значит mirror-COPY: создаём зеркальную
    # копию (флипнута), удаляем оригинал, ведём __el на копию.  Копия хоста-
    # стены (побочный дубль) стамп-помечена (наследует «kir:») и снимается
    # финальным стамп-свипом idempotence — измерению не мешает (re-extract
    # читает дверь-копию по created_id ДО свипа).
    # F5 v3.1 (2026-07-21): ГИБРИД. flipHand/flipFacing при CanFlip=true —
    # СТАБИЛЬНО (не орфанит, не пере-режет стену).  mirror-COPY ТОЛЬКО как
    # fallback при CanFlip=false (flip-locked ДЛ/Блок) — их 1-2 на этаж,
    # конфликтов минимум.  Живой урок: чистый mirror-copy валил кластерные
    # этажи (паркинг −1: 30 дверей на общей межэтажной стене → копии-вырезы
    # конфликтуют → commit RolledBack).  Гибрид держит стабильность И крак.
    # F5 v4 (2026-07-27): ветки зеркала БОЛЬШЕ НЕТ.  Флип ставится только
    # штатным flipHand/flipFacing, и только когда Revit это разрешает.
    #
    # Живой замер (SOB6.2, R2023, 178 опов окрестности, три прогона на своих
    # полосах — artifacts/mirror_cause*.json): с mirror-copy три опа отказали
    # «зеркальная копия недоступна», И ПРИ ЭТОМ геометрию потеряли ТРИ ДРУГИЕ
    # двери, на другом хосте — они оказались в точке [0,0] вообще без тела.
    # Снимаем флипы у всех опов — 0 отказов, 0 нарушений, 0 поломок.  Снимаем
    # только у трёх отказавших — поломка переезжает на четвёртый оп.  То есть
    # MirrorElements(mirrorCopies=true) на hosted-экземпляре портит документ
    # ЗА ПРЕДЕЛАМИ своего опа, и per-op SubTransaction этого не удерживает.
    #
    # Тот же вывод стоял здесь комментарием с 21.07 («никаких зеркал на
    # hosted»), но в код доведён не был.  Правило, заведённое рассуждением и
    # не сомкнутое с кодом, — главный класс дефекта этого пакета.
    #
    # НЕДОСТИЖИМЫЙ ФЛИП — ФАКТ О СЕМЕЙСТВЕ, А НЕ БРАК ПОСТРОЙКИ (09.08).
    #
    # `CanFlipHand`/`CanFlipFacing=false` — это отказ REVIT менять навеску
    # этого типа, а не наша ошибка и не признак того, что дверь построена
    # неправильно.  Живой корпус (`kir_witness.jsonl`, 16 красных строк
    # create_door 21.07) показывает цену прежней формы дословно:
    #
    #     16:26:28  KIR-X004  committed=false  geometry_ok=true topology_ok=true
    #       ["PD: hand flip state mismatch (semantic)",
    #        "PD: facing flip state mismatch (semantic)"]
    #
    # Геометрия и топология ЗЕЛЁНЫЕ: дверь встала в нужную стену, в нужную
    # точку, на нужной отметке.  Не сошлась одна створка — и откатилась ВСЯ
    # программа, потому что нарушенное постусловие имеет программный масштаб.
    # Цена по корпусу — одна правильная стена на дверь (все 16 строк это
    # двухопные пробы `create_wall`+`create_door`); важно не это число, а то,
    # что масштаб ПРОГРАММНЫЙ: на перестройке тем же дефектом платит целый
    # чанк материализатора (MAX_BULK_OPS).
    #
    # Флип теперь ОТКАЗЫВАЕТ НА МЕСТЕ, и отказ типизированный: он называет
    # СЕМЕЙСТВО (какой именно тип не флипается) и СЛЕДУЮЩИЙ ХОД (взять другой
    # тип) — единственный ход, который тут вообще есть, потому что обойти
    # `CanFlip*` нечем: `MirrorElements` запрещён навсегда (см. выше).
    # Под `per_op` отказ уносит только свой оп — соседи остаются
    # закоммиченными; под `atomic` откат тот же, что и был, но теперь у него
    # названа причина, а не «postconditions_violated».
    #
    # Ровно эта форма уже стоит у `place_family` (тот же файл, ветка
    # `hand`/`facing`): компилятор вёл себя двумя разными способами в одной
    # ситуации, и hosted-сторона была той, где расплачивалась вся программа.
    #
    # Постусловия ниже СОХРАНЕНЫ: после отказа они срабатывают только когда
    # `CanFlip*` был true, а флип всё равно не встал — то есть на настоящем
    # дефекте.  Хвост «— семейство не допускает флипа» остаётся верным
    # остаточным пояснением, но основной путь теперь не он.
    #
    # NB зеркало у place_family (mirrorCopies=FALSE, на месте, не hosted)
    # трогать нечем: живых улик против него нет, и оно не создаёт копий.
    kind_ru = "двери" if kind == "door" else "окна"

    def _flip_or_refuse(prop: str, flipper: str, canflip: str,
                        want: str, human: str) -> str:
        # `FamilySymbol.FamilyName` НЕ документирован ни в одном из шести
        # RevitAPI.xml (замер 09.08), а `FamilySymbol.Family` документирован
        # во всех шести — имя семейства берём через него.
        msg = (f"{_cs('семейство «')} + __sy_{s}.Family.Name + \" / \" "
               f"+ __sy_{s}.Name + "
               + _cs(f"» не допускает {human} ({canflip}=false) — "
                     f"выберите другой тип {kind_ru}"))
        return (
            f"if (__el_{s}.{prop} != {want})\n{{\n"
            f"    if (!__el_{s}.{canflip}) {{ {refuse_stmt(oid, msg, isolation)} }}\n"
            f"    __el_{s}.{flipper}();\n"
            f"}}\n")

    mirror = ""
    hand = ""
    if has_hand:
        wantH = "true" if bool(op.get("hand_flipped", False)) else "false"
        hand = _flip_or_refuse("HandFlipped", "flipHand", "CanFlipHand", wantH,
                               "смену стороны навески")
    facing = ""
    if has_facing:
        wantF = "true" if bool(op.get("facing_flipped", False)) else "false"
        facing = _flip_or_refuse(
            "FacingFlipped", "flipFacing", "CanFlipFacing", wantF,
            "смену направления открывания")
    # __hl_<s> is read by the post block (sill check) — declared here, not in
    # the create block, so per_op isolation (create inside its own try scope)
    # never cuts it off from the post (the emitter scope contract).  The
    # element_id branch's host var/computed point (__hw_<s>/__pt_<s>) join it
    # here for the SAME reason — the host post-check and the location
    # witness both read them AFTER the per-op try-scope closes.
    decl = f"FamilyInstance __el_{s} = null;\nLevel __hl_{s} = null;{host_decl}"
    create = (
        f"// create_{kind} {cs_line_comment_fragment(oid)}\n"
        + _symbol_res(op, s, oid, ver, isolation) + "\n"
        + host_res
        + f"__hl_{s} = doc.GetElement({hv}.LevelId) as Level;\n"
        f"if (__hl_{s} == null) {{ {refuse_stmt(oid, _cs('уровень стены-хоста не найден'), isolation)} }}\n"
        + pt_stmt
        + f"__el_{s} = doc.Create.NewFamilyInstance(__pt_{s}, __sy_{s}, {hv}, __hl_{s}, "
        f"Autodesk.Revit.DB.Structure.StructuralType.NonStructural);\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('NewFamilyInstance вернул null'), isolation)} }}\n"
        + mirror
        + hand
        + facing
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # State witnesses (semantic), one __post.Add per check IN the marker's
    # span — the translation-cert verdict-span rule (audit F3) requires each
    # discharged obligation to carry its own verdict line.
    # Wave A2 model post.  NB the 10.0mm hosted location tolerance appears
    # both as MM-comparison and as U(10.0) (internal units) — the historical
    # bytes interleave them, preserved verbatim via the registry value.
    htol = tolerance(f"create_{kind}", "location_mm")
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="host", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.Host == null || __el_{s}.Host.Id.ToString() != {hv}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': host mismatch (topology)')});\n"),
            message="host mismatch (topology)", style="guard"),
        WitnessCheck(
            obligation_key="location",
            reader_cs=f"    var __loc = __el_{s}.Location as LocationPoint;\n",
            verdict_cs=(
                f"    if (__loc == null) __post.Add({_cs(oid + ': no LocationPoint (geometry)')});\n"
                f"    else if (Math.Abs(MM(__loc.Point.X) - {x_cmp}) > {htol} || Math.Abs(MM(__loc.Point.Y) - {y_cmp}) > {htol} ||\n"
                f"             Math.Abs(__loc.Point.Z - (__hl_{s}.Elevation + U({final_sill}))) > U({htol}))\n"
                f"        __post.Add({_cs(oid + ': location/sill mismatch (geometry)')});\n"),
            message="location/sill mismatch (geometry)",
            tol=htol, style="else_block"),
    ]
    if has_mirrored:
        desired = "true" if bool(op.get("mirrored", False)) else "false"
        checks.append(WitnessCheck(
            obligation_key="mirrored", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.Mirrored != {desired})\n"
                f"        __post.Add({_cs(oid + ': mirrored state mismatch (semantic)')});\n"),
            message="mirrored state mismatch (semantic)", style="guard"))
    if has_hand:
        desired = "true" if bool(op.get("hand_flipped", False)) else "false"
        checks.append(WitnessCheck(
            obligation_key="hand_flipped", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.HandFlipped != {desired})\n"
                f"        __post.Add({_cs(oid + ': hand flip state mismatch (semantic)')}\n"
                f"            + (__el_{s}.CanFlipHand ? \"\" : \" — семейство не допускает флипа\"));\n"),
            message="hand flip state mismatch (semantic)", style="guard"))
    if has_facing:
        desired = "true" if bool(op.get("facing_flipped", False)) else "false"
        checks.append(WitnessCheck(
            obligation_key="facing_flipped", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.FacingFlipped != {desired})\n"
                f"        __post.Add({_cs(oid + ': facing flip state mismatch (semantic)')}\n"
                f"            + (__el_{s}.CanFlipFacing ? \"\" : \" — семейство не допускает флипа\"));\n"),
            message="facing flip state mismatch (semantic)", style="guard"))
    return decl, create, checks, _readback_block(
        s, oid, stamp, family_state=has_mirrored or has_hand or has_facing, identity_version=ver)


def _emit_window(op, ver, stamp, isolation: str = "atomic"):
    return _emit_hosted(op, ver, stamp, "window", isolation)


def _emit_door(op, ver, stamp, isolation: str = "atomic"):
    return _emit_hosted(op, ver, stamp, "door", isolation)


def _emit_room(op: dict, ver: str, stamp: str,
               isolation: str = "atomic") -> tuple[str, str, str, str]:
    oid = op["id"]
    s = _safe(oid)
    x, y = op["xy"][0], op["xy"][1]
    nm = op.get("name")
    has_number = "number" in op
    number = op.get("number")
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    decl = f"Autodesk.Revit.DB.Architecture.Room __el_{s} = null;"
    rename = ""
    if nm:
        rename = (f"\ntry {{ __el_{s}.Name = {_cs(nm)}; }}\n"
                  f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"имя помещения: \" + __ex_{s}.Message', isolation)} }}")
    renumber = ""
    if has_number:
        renumber = (
            f"\nParameter __rno_set_{s} = null;\n"
            f"try {{ __rno_set_{s} = __el_{s}.get_Parameter("
            f"BuiltInParameter.ROOM_NUMBER); }}\n"
            f"catch (Exception __rno_get_ex_{s})\n"
            f"{{ {refuse_stmt(oid, f'\"чтение номера помещения: \" + __rno_get_ex_{s}.Message', isolation)} }}\n"
            f"if (__rno_set_{s} == null || __rno_set_{s}.IsReadOnly)\n"
            f"{{ {refuse_stmt(oid, _cs('номер помещения недоступен для записи'), isolation)} }}\n"
            f"bool __rno_ok_{s} = false;\n"
            f"try {{ __rno_ok_{s} = __rno_set_{s}.Set({_cs(number)}); }}\n"
            f"catch (Exception __rno_set_ex_{s})\n"
            f"{{ {refuse_stmt(oid, f'\"номер помещения: \" + __rno_set_ex_{s}.Message', isolation)} }}\n"
            f"if (!__rno_ok_{s})\n"
            f"{{ {refuse_stmt(oid, _cs('запись номера помещения отклонена Revit'), isolation)} }}")
    # upper_offset_mm -> ROOM_UPPER_OFFSET (25.08.2026, живая находка:
    # HAB022 у настоящей квартиры — NewRoom ставит верхний предел из
    # умолчания типа документа, 8 футов = 2438мм, ниже нормы 2500мм, и
    # язык не мог задать его вовсе). Тот же приём, что у
    # `create_floor`/FLOOR_HEIGHTABOVELEVEL_PARAM: параметр читается,
    # недоступность — типизированный отказ, а не молчаливый пропуск.
    upper_offset = op.get("upper_offset_mm")
    uo_set = ""
    if upper_offset is not None:
        uo_set = (
            f"\nParameter __ruo_{s} = __el_{s}.get_Parameter(BuiltInParameter.ROOM_UPPER_OFFSET);\n"
            f"if (__ruo_{s} == null || __ruo_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('ROOM_UPPER_OFFSET недоступен у помещения'), isolation)} }}\n"
            f"__ruo_{s}.Set(U({upper_offset}));")
    create = (f"// create_room {cs_line_comment_fragment(oid)}\n{lv_res}\n"
              f"__el_{s} = doc.Create.NewRoom(__lv_{s}, new UV(U({x}), U({y})));\n"
              f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('NewRoom вернул null'), isolation)} }}"
              + uo_set + rename + renumber + "\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # ИМЯ ПОМЕЩЕНИЯ ЧИТАЕТСЯ ПАРАМЕТРОМ, А НЕ `Room.Name`.
    #
    # Замер живьём 04.08 («Проект1», Revit 2026, транзакция откачена):
    #     rm.Name = "KIR_GAP_ROOM_1";
    #     rm.Name                     -> "KIR_GAP_ROOM_1 1"   (имя + НОМЕР)
    #     ROOM_NAME.AsString()        -> "KIR_GAP_ROOM_1"
    # Сеттер `Room.Name` кладёт ТОЛЬКО имя, а геттер склеивает его с номером
    # помещения. Постусловие, сверявшее геттер с запрошенным именем, поэтому
    # не выполнялось НИКОГДА: живая матрица 04.08 откатила ИСПРАВНОЕ
    # помещение с `KIR-X004: RM: name mismatch`. Ложный красный — свидетель
    # мерил не то, чем оп писал. Читаем тот же параметр, в который пишет
    # сеттер; отсутствие параметра — тоже нарушение (fail-closed).
    rmtol = tolerance("create_room", "location_mm")
    rutol = tolerance("create_room", "upper_offset_mm")
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="level_binding", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.LevelId == null || __el_{s}.LevelId.ToString() != {lv_idexpr})\n"
                f"        __post.Add({_cs(oid + ': level binding mismatch (topology)')});\n"),
            message="level binding mismatch (topology)", style="guard"),
        WitnessCheck(
            obligation_key="location",
            reader_cs=f"    var __loc = __el_{s}.Location as LocationPoint;\n",
            verdict_cs=(
                f"    if (__loc == null || Math.Abs(MM(__loc.Point.X) - {x}) > {rmtol} || "
                f"Math.Abs(MM(__loc.Point.Y) - {y}) > {rmtol})\n"
                f"        __post.Add({_cs(oid + ': room placement mismatch (geometry)')});\n"),
            message="room placement mismatch (geometry)",
            tol=rmtol, style="guard"),
        WitnessCheck(
            obligation_key="area", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.Area <= 1e-6)\n"
                f"        __post.Add({_cs(oid + ': room is not enclosed (semantic)')});"
                + ("" if nm else "\n")),
            message="room is not enclosed (semantic)", style="guard"),
    ]
    if nm:
        checks.append(WitnessCheck(
            obligation_key="name", reader_cs="",
            verdict_cs=(f"\n    Parameter __rnm_{s} = "
                        f"__el_{s}.get_Parameter(BuiltInParameter.ROOM_NAME);\n"
                        f"    if (__rnm_{s} == null || __rnm_{s}.AsString() != {_cs(nm)}) "
                        f"__post.Add({_cs(oid + ': name mismatch')});\n"),
            message="name mismatch", style="guard"))
    if has_number:
        checks.append(WitnessCheck(
            obligation_key="number", reader_cs="",
            verdict_cs=(
                f"\n    Parameter __rno_{s} = "
                f"__el_{s}.get_Parameter(BuiltInParameter.ROOM_NUMBER);\n"
                f"    if (__rno_{s} == null || "
                f"__rno_{s}.AsString() != {_cs(number)}) "
                f"__post.Add({_cs(oid + ': number mismatch (semantic)')});\n"),
            message="number mismatch (semantic)", style="guard"))
    if upper_offset is not None:
        # Постусловие ЧИТАЕТ ROOM_UPPER_OFFSET ОБРАТНО у построенного
        # помещения, а не подтверждает, что `.Set()` не бросил исключение —
        # тот же довод, что развёрнут у ROOM_NAME выше: сеттер и геттер
        # одного параметра иногда расходятся, и единственная защита —
        # свериться с тем, что реально осталось на элементе.
        checks.append(WitnessCheck(
            obligation_key="upper_offset",
            reader_cs=(f"    var __ruop_{s} = "
                       f"__el_{s}.get_Parameter(BuiltInParameter.ROOM_UPPER_OFFSET);\n"),
            verdict_cs=(
                f"    if (__ruop_{s} == null || "
                f"Math.Abs(MM(__ruop_{s}.AsDouble()) - {upper_offset}) > {rutol})\n"
                f"        __post.Add({_cs(oid + ': upper offset mismatch (geometry)')});\n"),
            message="upper offset mismatch (geometry)",
            tol=rutol, style="guard"))
    post = checks
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f'    try {{ __rb["id"] = __el_{s}.Id.ToString(); }} catch {{ }}\n'
        + element_identity_readback_cs(f"__el_{s}", revit_version=ver) +
        # `name` — ИМЯ (то, что ставил оп). `name_and_number` — склейка,
        # которую отдаёт `Room.Name`: она полезна человеку, но сверять по
        # ней нельзя, и разные ключи не дают их спутать.
        f"    try {{ Parameter __rnb_{s} = "
        f"__el_{s}.get_Parameter(BuiltInParameter.ROOM_NAME);\n"
        f"        __rb[\"name\"] = __rnb_{s} != null ? __rnb_{s}.AsString() : __el_{s}.Name; }} catch {{ }}\n"
        f"    try {{ Parameter __rno_rb_{s} = "
        f"__el_{s}.get_Parameter(BuiltInParameter.ROOM_NUMBER);\n"
        f"        __rb[\"number\"] = __rno_rb_{s} != null ? __rno_rb_{s}.AsString() : null; }} catch {{ }}\n"
        f"    try {{ __rb[\"name_and_number\"] = __el_{s}.Name; }} catch {{ }}\n"
        f"    try {{ __rb[\"area_m2\"] = Math.Round(UnitUtils.ConvertFromInternalUnits(__el_{s}.Area, UnitTypeId.SquareMeters), 2); }} catch {{ }}\n"
        # upper_offset_mm — ГАТИРОВАНО, как rename/renumber выше в этой же
        # функции: пустая строка при отсутствии поля держит КАЖДУЮ уже
        # существующую программу байт-в-байт (golden-корпус её ловит
        # первым же прогоном, если ослабить дисциплину). Эхо в квитанции —
        # то же самое сообщение автору, что уже даёт `area_m2`: не только
        # «откат/не откат», а «вот что реально осталось на элементе».
        + (f"    try {{ Parameter __ruorb_{s} = "
           f"__el_{s}.get_Parameter(BuiltInParameter.ROOM_UPPER_OFFSET);\n"
           f"        __rb[\"upper_offset_mm\"] = __ruorb_{s} != null ? "
           f"(object)MM(__ruorb_{s}.AsDouble()) : null; }} catch {{ }}\n"
           if upper_offset is not None else "")
        + f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_place_curve(op: dict, ver: str, stamp: str, isolation: str = "atomic"):
    """`place_family` по КРИВОЙ — вторая перегрузка NewFamilyInstance.

    Отдельная функция, а не ветка внутри точечной: точечный путь заморожен
    корпусом байт-паритета (18 700 экземпляров демо, 327 из прогона A5), и
    единственный способ не сдвинуть его ни на байт — не заходить в него.

    Повод замерен (тренировочная модель ЭОМ, SKLNK R2026): 79 экземпляров —
    весь остаток дыры этой модели — имеют `FamilyPlacementType.CurveBased` и
    живой `LocationCurve`, а `LocationPoint` у них не существует в принципе.
    Точечный оп их не берёт по существу, а не по недосмотру.

    Чего здесь СОЗНАТЕЛЬНО нет:

    * поворота и зеркала. У кривого экземпляра ориентацию задаёт сама кривая;
      вращать его вокруг оси Z в точке — действие без определённого смысла.
      Если лифт когда-нибудь принесёт флипы на кривом семействе, они должны
      получить собственный замер, а не унаследовать точечную ветку;
    * хоста. В живой модели все 79 висят на лотках, но `NewFamilyInstance`
      с кривой хоста НЕ принимает: Revit связывает их сам. Поэтому хост не
      навязывается, а ЧИТАЕТСЯ ОБРАТНО в свидетеле — расхождение попадёт в
      отчёт, а не растворится.
    """
    oid = op["id"]
    s = _safe(oid)
    x0, y0, z0 = _pt3(op["p0_mm"])
    x1, y1, z1 = _pt3(op["p1_mm"])
    # Хост адресуется так же, как у двери и окна: ссылкой на оп этой же
    # программы (пересборка создаёт лоток раньше кожуха) либо готовым id.
    host = op.get("host") or {}
    host_ref = host.get("value")
    grounded_host = host.get("__grounded__") or {}
    if isinstance(host_ref, str) and not grounded_host:
        host_expr = "__el_" + _safe(host_ref)
    elif grounded_host.get("id") is not None:
        host_expr = f"doc.GetElement({_eid(grounded_host['id'], ver, oid)})"
    else:
        raise KirRefusal([Diagnostic(
            code=GROUND_BAD_SELECTOR, op_id=oid, field_name="host",
            message_ru="place_family по кривой: хост задаётся ссылкой на оп "
                       "этой же программы или element_id")])
    # Хост объявляется В ОБЛАСТИ ОБЪЯВЛЕНИЙ, а не внутри блока операции.
    # ЗАМЕР 28.07 (живая пересборка ЭОМ, 9344 опа): свидетель хоста читает
    # `__pfh_` уже ПОСЛЕ закрытия per-op блока, и `var` внутри блока делал имя
    # невидимым — `CS0103: The name '__pfh_e1278883' does not exist in the
    # current context`. Программа была верна, невидим был только шов областей
    # видимости; ровно так же здесь всегда жил `__el_`.
    decl = f"FamilyInstance __el_{s} = null;\nElement __pfh_{s} = null;"
    create = (
        f"// place_family (кривая) {cs_line_comment_fragment(oid)}\n"
        + _symbol_res(op, s, oid, ver, isolation) + "\n"
        f"__pfh_{s} = {host_expr};\n"
        f"if (__pfh_{s} == null) {{ {refuse_stmt(oid, _cs('хост не найден'), isolation)} }}\n"
        f"Line __pfc_{s} = Line.CreateBound(P({x0}, {y0}, {z0}), P({x1}, {y1}, {z1}));\n"
        # ЗАМЕРЕНО 27.07 на живой модели: перегрузка с УРОВНЕМ проецирует
        # кривую на плоскость уровня и схлопывает вертикальный отрезок в
        # точку (получено [...,0]→[...,0] вместо [...,565]→[...,4910]), а
        # переданный уровень Revit вдобавок игнорирует. Верная перегрузка —
        # по ссылке на хост; она же честно отказывает «line does not
        # coincide with the input face», если отрезок не лежит на грани.
        f"__el_{s} = doc.Create.NewFamilyInstance(new Reference(__pfh_{s}), __pfc_{s}, __sy_{s});\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('NewFamilyInstance вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    ctol = tolerance("place_family", "location_mm")
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="location",
            reader_cs=f"    var __lc = __el_{s}.Location as LocationCurve;\n",
            verdict_cs=(
                f"    if (__lc == null) __post.Add({_cs(oid + ': нет LocationCurve')});\n"
                f"    else\n    {{\n"
                f"        var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);\n"
                # Ориентацию отрезка Revit вправе выбрать сам, поэтому концы
                # сверяются как НЕУПОРЯДОЧЕННАЯ пара — иначе свидетель ловил
                # бы верную постройку (та же оговорка, что в create_wall).
                f"        double __d0 = Math.Pow(MM(__a.X) - {x0}, 2) + Math.Pow(MM(__a.Y) - {y0}, 2) + Math.Pow(MM(__a.Z) - {z0}, 2);\n"
                f"        double __d1 = Math.Pow(MM(__b.X) - {x0}, 2) + Math.Pow(MM(__b.Y) - {y0}, 2) + Math.Pow(MM(__b.Z) - {z0}, 2);\n"
                f"        var __e0 = __d0 <= __d1 ? __a : __b; var __e1 = __d0 <= __d1 ? __b : __a;\n"
                f"        if (Math.Abs(MM(__e0.X) - {x0}) > {ctol} || Math.Abs(MM(__e0.Y) - {y0}) > {ctol} || Math.Abs(MM(__e0.Z) - {z0}) > {ctol} ||\n"
                f"            Math.Abs(MM(__e1.X) - {x1}) > {ctol} || Math.Abs(MM(__e1.Y) - {y1}) > {ctol} || Math.Abs(MM(__e1.Z) - {z1}) > {ctol})\n"
                f"            __post.Add({_cs(oid + ': endpoints mismatch (geometry)')});\n"
                f"    }}\n"),
            message="endpoints mismatch (geometry)",
            tol=ctol, style="else_block"),
        # Свидетель проверяет ХОСТ, а не уровень: у этого класса уровня нет
        # ни в источнике (все 79 кожухов ЭОМ: LevelId = -1), ни в вызове.
        WitnessCheck(
            obligation_key="host", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.Host == null || __el_{s}.Host.Id.ToString() != __pfh_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': host mismatch (topology)')});\n"),
            message="host mismatch (topology)", style="guard"),
    ]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    try {{ var __sp = __el_{s}.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__sp != null) __rb[\"stamp\"] = __sp.AsString(); }} catch {{ }}\n"
        f"    try {{ var __lc2 = __el_{s}.Location as LocationCurve;\n"
        f"        if (__lc2 != null) {{\n"
        f"            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);\n"
        f"            __rb[\"start_mm\"] = new double[] {{ Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) }};\n"
        f"            __rb[\"end_mm\"] = new double[] {{ Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) }};\n"
        f"        }} }} catch {{ }}\n"
        # Хост читается, а не назначается: перегрузка с кривой его не берёт,
        # Revit связывает сам. Прочитанное значение — факт для сравнения при
        # пересборке, а не обещание.
        f"    try {{ if (__el_{s}.Host != null) __rb[\"host_id\"] = __el_{s}.Host.Id.ToString(); }} catch {{ }}\n"
        f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
        f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
        f"            var __te = doc.GetElement(__tid);\n"
        f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
        f"        }} }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


def _emit_place_work_plane(op: dict, ver: str, stamp: str,
                           isolation: str = "atomic"):
    """`place_family` НА РАБОЧЕЙ ПЛОСКОСТИ — третья перегрузка.

    Отдельная функция, а не ветка внутри точечной, по той же причине, что у
    кривой: точечный путь заморожен корпусом байт-паритета (18 700
    экземпляров демо), и единственный способ не сдвинуть его ни на байт — не
    заходить в него.

    ПОВОД ЗАМЕРЕН ПО КОРПУСУ (`tools/coverage_matrix.py`, 11 различных
    документов, 11.08.2026). Лифтер отказывает «place_family ставит только
    точечные размещения (OneLevelBased/OneLevelBasedHosted)» на:

        'WorkPlaneBased'   483 элемента на 7 документах из 11
        'TwoLevelsBased'  9392 элемента на 4 документах

    Семь документов из одиннадцати — самый широкий разброс по зданиям среди
    всех действенных строк корпуса, а по логике самой карты покрытия широкий
    разброс означает, что неверно НАШЕ правило вообще, а не особенность
    одного проекта.

    API СНЯТ С СБОРОК, А НЕ С ДОКУМЕНТАЦИИ (11.08, рефлексия по шести
    `RevitAPI.dll` + живая компиляция на :52412 по отдельному прогону на
    каждую версию):

        NewFamilyInstance(XYZ, FamilySymbol, XYZ refDir, Element,
                          StructuralType)                            6/6
        NewFamilyInstance(Reference, XYZ, XYZ, FamilySymbol)         6/6
        FamilyPlacementType — все 10 членов                          6/6
        FamilyInstance.HandOrientation / FacingOrientation / Host    6/6

    ОСИ ВЕРСИЙ У ЭТОЙ ВЕТКИ НЕТ, и это замер, а не надежда. Попутно замерена
    ловушка чтения рефлексии: `(XYZ, FamilySymbol, Level, StructuralType)`
    объявлен на `Creation.Document` в 2021-2023 и на `Creation.ItemFactoryBase`
    в 2024-2026 — он НЕ ИСЧЕЗАЛ, он переехал по цепочке наследования, и
    дамп объявленных членов показывает это как пропажу. Тот же капкан, что
    у `SpatialElement.Name`: спрашивать надо всю цепочку, а не класс.

    ПОЧЕМУ ВЗЯТА ПЕРЕГРУЗКА С ХОСТОМ, А НЕ СО ССЫЛКОЙ НА ГРАНЬ. Вторая
    (`Reference, XYZ, XYZ, FamilySymbol`) требует `Reference` на КОНКРЕТНУЮ
    ГРАНЬ, а грань адресуется faceref-слоем, который живёт за флагом и
    решает свою задачу. Перегрузка с хостом принимает элемент целиком —
    ровно то, чем `place_family` уже адресует носителя в точечной и кривой
    ветках. Один способ назвать хост на все три ветки, а не третий.

    ═══ ЧЕГО ЭТА ВЕТКА НЕ ДАЁТ, И ЭТО НАДО ЗНАТЬ ЗАРАНЕЕ ═══

    ОБРАТНОГО ХОДА У НЕЁ НЕТ, и не будет, пока не изменится ЗАХВАТ.
    `schema.L0Element` несёт РОВНО ОДИН уровень (`level_id`) и НЕ несёт
    ссылки на рабочую плоскость вовсе — ни поля, ни бокового индекса. То
    есть эта волна расширяет ПРЯМОЙ ход (то, что инженер может попросить), а
    поднять такой экземпляр обратно по-прежнему нечем: лифтер продолжит
    отказывать, и это правильный ответ, а не регресс. Записано здесь, а не в
    сообщении коммита, чтобы следующий замер не переоткрывал это как находку.
    """
    oid = op["id"]
    unsupported = [field for field in PLACE_FAMILY_WORK_PLANE_UNSUPPORTED
                   if field in op]
    if unsupported:
        # Defence in depth for trusted callers which invoke an emitter with a
        # pre-normalised op and therefore bypass authoring_validation.validate.
        # Every accepted operand must be emitted+witnessed or refused; the
        # WorkPlaneBased branch currently has no measured lowering for these.
        raise KirRefusal([
            Diagnostic(
                code=PARSE_EXCLUSIVE_FIELDS,
                op_id=oid,
                field_name=field,
                expected=(f"{field} без ref_dir или ref_dir без "
                          f"{field}"),
                got=op[field],
                message_ru=(
                    f"place_family на рабочей плоскости: {field} "
                    "не имеет доказанного совместного lowering с "
                    "ref_dir"))
            for field in unsupported
        ])
    s = _safe(oid)
    x, y, z = _pt3(op["xyz"])
    dx, dy, dz = _pt3(op["ref_dir"])
    host = op.get("host") or {}
    host_ref = host.get("value")
    grounded_host = host.get("__grounded__") or {}
    if isinstance(host_ref, str) and not grounded_host:
        host_expr = "__el_" + _safe(host_ref)
    elif grounded_host.get("id") is not None:
        host_expr = f"doc.GetElement({_eid(grounded_host['id'], ver, oid)})"
    else:
        # Нижняя половина взаимной обязательности живёт в ветке рода —
        # ровно тем же швом, которым её держат create_opening и
        # create_railing: план родов не разбирает, а без носителя у этой
        # перегрузки нет рабочей плоскости, к которой крепиться.
        raise KirRefusal([Diagnostic(
            code=GROUND_BAD_SELECTOR, op_id=oid, field_name="host",
            message_ru="place_family на рабочей плоскости: носитель "
                       "обязателен и задаётся ссылкой на оп этой же "
                       "программы или element_id — именно он несёт "
                       "плоскость, к которой крепится экземпляр")])
    decl = f"FamilyInstance __el_{s} = null;\nElement __pfh_{s} = null;"
    create = (
        f"// place_family (рабочая плоскость) {cs_line_comment_fragment(oid)}\n"
        + _symbol_res(op, s, oid, ver, isolation) + "\n"
        f"__pfh_{s} = {host_expr};\n"
        f"if (__pfh_{s} == null) {{ {refuse_stmt(oid, _cs('хост не найден'), isolation)} }}\n"
        # РОД РАЗМЕЩЕНИЯ — ФАКТ О СЕМЕЙСТВЕ, И ОТКАЗ НАЗЫВАЕТ ЕГО ВСЛУХ.
        #
        # Тот же класс, что у неповорачиваемой створки двери: `CanFlip*=false`
        # — факт о СЕМЕЙСТВЕ, и Revit не станет его переставлять. Здесь так
        # же: попросить размещение на рабочей плоскости у семейства, которое
        # так не ставится, — не дефект постройки, а невыполнимая просьба.
        # Поэтому типизированный ОТКАЗ (стоит свой оп под per_op), а не
        # нарушение постусловия (стоило бы всю программу), и в тексте едет
        # ФАКТИЧЕСКИЙ род, чтобы автору было что исправить.
        f"if (__sy_{s}.Family == null || __sy_{s}.Family.FamilyPlacementType "
        f"!= FamilyPlacementType.WorkPlaneBased)\n{{ "
        + refuse_stmt(
            oid,
            f'"place_family на рабочей плоскости: у семейства род размещения "'
            f' + (__sy_{s}.Family == null ? "неизвестен"'
            f' : __sy_{s}.Family.FamilyPlacementType.ToString())'
            f' + ", а не WorkPlaneBased — выберите другой тип или ставьте '
            f'точкой"',
            isolation)
        + " }\n"
        # НАПРАВЛЕНИЕ — ВЕКТОР, А НЕ ТОЧКА, поэтому БЕЗ U(): перевод мм->футы
        # на направление не влияет (масштаб направления не меняет), и
        # написать его здесь значило бы соврать в коде о роде величины.
        f"XYZ __pfp_{s} = new XYZ(U({x}), U({y}), U({z}));\n"
        f"XYZ __pfd_{s} = new XYZ({dx}, {dy}, {dz});\n"
        f"if (__pfd_{s}.IsZeroLength()) {{ "
        + refuse_stmt(oid, _cs("ref_dir нулевой длины: направление отсчёта "
                               "не задано"), isolation)
        + " }\n"
        f"try {{ __el_{s} = doc.Create.NewFamilyInstance(__pfp_{s}, __sy_{s}, "
        f"__pfd_{s}, __pfh_{s}, "
        f"Autodesk.Revit.DB.Structure.StructuralType.NonStructural); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(oid, f'"NewFamilyInstance: " + __ex_{s}.Message',
                      isolation)
        + " }\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(oid, _cs("NewFamilyInstance вернул null"), isolation)
        + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    wtol = tolerance("place_family", "location_mm")
    checks: list[WitnessCheck] = [
        # ГДЕ. `Location` считает Revit, а не мы: под §18.3 подпись
        # «(geometry)» законна ровно при таком читателе.
        WitnessCheck(
            obligation_key="location",
            reader_cs=f"    var __wloc_{s} = __el_{s}.Location as LocationPoint;\n",
            verdict_cs=(
                f"    if (__wloc_{s} == null\n"
                f"        || Math.Abs(MM(__wloc_{s}.Point.X) - {x}) > {wtol}\n"
                f"        || Math.Abs(MM(__wloc_{s}.Point.Y) - {y}) > {wtol}\n"
                f"        || Math.Abs(MM(__wloc_{s}.Point.Z) - {z}) > {wtol})\n"
                f"        __post.Add({_cs(oid + ': location mismatch (geometry)')});\n"),
            message="location mismatch (geometry)",
            tol=wtol, style="guard"),
        # НА ЧЁМ. Носитель читается обратно, а не принимается на веру.
        WitnessCheck(
            obligation_key="host", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.Host == null "
                f"|| __el_{s}.Host.Id.ToString() != __pfh_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': host mismatch (topology)')});\n"),
            message="host mismatch (topology)", style="guard"),
        # КАК ПОВЁРНУТ. Единственное, что эта ветка добавляет к точечной, —
        # направление отсчёта, и не проверить его значило бы принять оп,
        # чей главный операнд никто не читал.
        #
        # ЧИТАЕТСЯ `HandOrientation` — ВЕКТОР, КОТОРЫЙ СЧИТАЕТ REVIT по
        # размещённому экземпляру, а не параметр, который писали мы: подпись
        # «(geometry)» законна по §18.3 именно поэтому.
        #
        # СВЕРКА ПО ПАРАЛЛЕЛЬНОСТИ, А НЕ ПО РАВЕНСТВУ, и это не послабление:
        # Revit вправе выбрать противоположный смысл того же направления
        # (та же оговорка, что у концов стены и сегментов разделителя, где
        # ориентацию кривой выбирает он же). Требовать один смысл значило бы
        # заворачивать верную постройку по знаку.
        WitnessCheck(
            obligation_key="reference_direction",
            reader_cs=(
                f"    XYZ __wdir_{s} = null;\n"
                f"    try {{ __wdir_{s} = __el_{s}.HandOrientation; }} catch {{ }}\n"
                f"    XYZ __wwant_{s} = new XYZ({dx}, {dy}, {dz});\n"),
            verdict_cs=(
                f"    if (__wdir_{s} == null || __wdir_{s}.IsZeroLength())\n"
                f"        __post.Add({_cs(oid + ': reference direction unreadable (geometry)')});\n"
                f"    else\n"
                f"    {{\n"
                f"        double __wang_{s} = __wdir_{s}.AngleTo(__wwant_{s});\n"
                f"        if (Math.Min(__wang_{s}, Math.PI - __wang_{s}) > "
                f"Math.PI / {tolerance('place_family', 'rotation_deg').deg_rad_divisor})\n"
                f"            __post.Add({_cs(oid + ': reference direction mismatch (geometry)')});\n"
                f"    }}\n"),
            message="reference direction mismatch (geometry)",
            style="plain"),
        # УРОВЕНЬ СВИДЕТЕЛЬСТВУЕТСЯ И ЗДЕСЬ, хотя перегрузка его не
        # принимает: план ТРЕБУЕТ назвать уровень у любого точечного
        # размещения (KIR-P005), а обязательство `level_binding`
        # условно по наличию поля — значит названный уровень обязан
        # быть прочитан обратно, иначе сертификат честно объявит
        # клаузулу недоказанной. Читатель — ТОТ ЖЕ помощник цепочки
        # уровня, что у точечной ветки: один вопрос, один судья.
        level_chain_witness(f"__el_{s}", oid, _level_expr(
            op, s, ver, oid, isolation)[1]),
    ]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    try {{ var __wl_{s} = __el_{s}.Location as LocationPoint;\n"
        f"        if (__wl_{s} != null) __rb[\"xyz_mm\"] = new double[] {{ "
        f"Math.Round(MM(__wl_{s}.Point.X), 1), "
        f"Math.Round(MM(__wl_{s}.Point.Y), 1), "
        f"Math.Round(MM(__wl_{s}.Point.Z), 1) }}; }} catch {{ }}\n"
        f"    try {{ if (__el_{s}.Host != null) "
        f"__rb[\"host_id\"] = __el_{s}.Host.Id.ToString(); }} catch {{ }}\n"
        f"    try {{ var __wo_{s} = __el_{s}.HandOrientation;\n"
        f"        if (__wo_{s} != null) __rb[\"hand_orientation\"] = new double[] {{ "
        f"Math.Round(__wo_{s}.X, 4), Math.Round(__wo_{s}.Y, 4), "
        f"Math.Round(__wo_{s}.Z, 4) }}; }} catch {{ }}\n"
        # Род размещения едет в квитанцию ФАКТОМ О СЕМЕЙСТВЕ: он объясняет и
        # успех, и отказ выше, и его нельзя вывести из программы.
        f"    try {{ __rb[\"placement_type\"] = "
        f"__el_{s}.Symbol.Family.FamilyPlacementType.ToString(); }} catch {{ }}\n"
        + _stamp_readback(f"__el_{s}") +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


def _emit_place(op: dict, ver: str, stamp: str,
                isolation: str = "atomic") -> tuple[str, str, str, str]:
    # Кривая обслуживается отдельной функцией: точечный путь ниже заморожен
    # байт-в-байт корпусом паритета и не смеет сдвинуться.
    if "p0_mm" in op and "p1_mm" in op:
        if "ref_dir" in op:
            # МОЛЧА ПРОГЛОТИТЬ ОПЕРАНД — ХУЖЕ, ЧЕМ ОТКАЗАТЬ. Кривая
            # ставится перегрузкой по ссылке на носитель, у которой
            # направления отсчёта нет вовсе; принять `ref_dir` и не
            # использовать его значило бы построить не то, о чём
            # просили, и отчитаться успехом.
            raise KirRefusal([Diagnostic(
                code=PARSE_EXCLUSIVE_FIELDS, op_id=op["id"],
                field_name="ref_dir",
                expected="ref_dir ЛИБО p0_mm/p1_mm",
                got="и направление, и кривая",
                message_ru="place_family по кривой не принимает "
                           "ref_dir: у перегрузки по ссылке на "
                           "носитель направления отсчёта нет — "
                           "ориентацию задаёт сама кривая")])
        return _emit_place_curve(op, ver, stamp, isolation)
    # Рабочая плоскость — тоже отдельная функция и по той же причине.
    if "ref_dir" in op:
        return _emit_place_work_plane(op, ver, stamp, isolation)
    oid = op["id"]
    s = _safe(oid)
    x, y, z = _pt3(op["xyz"])
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    has_rotation = "rotation_deg" in op
    rotation_deg = float(op.get("rotation_deg", 0.0))
    has_mirrored = "mirrored" in op
    mirrored = bool(op.get("mirrored", False))
    has_hand = "hand_flipped" in op
    hand_flipped = bool(op.get("hand_flipped", False))
    has_facing = "facing_flipped" in op
    facing_flipped = bool(op.get("facing_flipped", False))
    # XOR-модель флипов (живые пробы 2026-07-21, Balcon_Шкаф/ДГ 900x2100):
    # Mirrored у Revit ПРОИЗВОДЕН (= Hand XOR Facing); зеркало плоскостью
    # (-sinθ,cosθ) — единственное проверенное действие для facing=T (работает
    # и при CanFlipFacing=false, сохраняет чтение rotation); ортогональная
    # плоскость читается Mirrored=F — «выбор плоскости по чётности»
    # опровергнут живьём.  flipHand сдвигает чтение __loc.Rotation на 180°
    # (GT_C) — поэтому при hand=T действие поворота пре-компенсируется,
    # свидетель остаётся на лифтованном rotation_deg.
    action_deg = ((rotation_deg + 180.0) % 360.0
                  if (has_hand and hand_flipped) else rotation_deg)
    rotate = ""
    if (has_rotation or (has_hand and hand_flipped)) and action_deg != 0.0:
        rotate = (
            f"Line __axis_{s} = Line.CreateUnbound(P({x}, {y}, {z}), XYZ.BasisZ);\n"
            f"ElementTransformUtils.RotateElement(doc, __el_{s}.Id, "
            f"__axis_{s}, {action_deg} * Math.PI / 180.0);\n")
    mirror = ""
    emit_mirror = (bool(facing_flipped) if has_facing
                   else (has_mirrored and mirrored))
    if has_mirrored and emit_mirror:
        desired = "true" if mirrored else "false"
        # Гард по НАБЛЮДАЕМОМУ эффекту действия: зеркало = facing-флип,
        # поэтому при facing=T гардим по FacingFlipped.  Гард по Mirrored
        # для цели M=F не срабатывал никогда (свежий инстанс уже M=F) —
        # живой промах (F,T,T)×11 (шкафы этажа 20, полный прогон 13:10);
        # legacy-ветка без facing-ключа держит старый гард байт-в-байт.
        if has_facing and facing_flipped:
            mirror_guard = f"__el_{s}.FacingFlipped != true"
        else:
            mirror_guard = f"__el_{s}.Mirrored != {desired}"
        mirror = (
            f"if ({mirror_guard})\n{{\n"
            f"    double __mirrorAngle_{s} = {rotation_deg} * Math.PI / 180.0;\n"
            f"    XYZ __mirrorNormal_{s} = new XYZ(-Math.Sin(__mirrorAngle_{s}), Math.Cos(__mirrorAngle_{s}), 0);\n"
            f"    Plane __mirrorPlane_{s} = Plane.CreateByNormalAndOrigin(__mirrorNormal_{s}, P({x}, {y}, {z}));\n"
            f"    ElementTransformUtils.MirrorElements(doc, new List<ElementId> {{ __el_{s}.Id }}, __mirrorPlane_{s}, false);\n"
            f"}}\n")
    hand = ""
    if has_hand:
        desired = "true" if hand_flipped else "false"
        hand = (
            f"if (__el_{s}.HandFlipped != {desired})\n{{\n"
            f"    if (!__el_{s}.CanFlipHand) {{ {refuse_stmt(oid, _cs('семейство не поддерживает требуемый hand flip'), isolation)} }}\n"
            f"    __el_{s}.flipHand();\n"
            f"}}\n")
    facing = ""
    if has_facing:
        desired = "true" if facing_flipped else "false"
        facing = (
            f"if (__el_{s}.FacingFlipped != {desired})\n{{\n"
            f"    if (!__el_{s}.CanFlipFacing) {{ {refuse_stmt(oid, _cs('семейство не поддерживает требуемый facing flip'), isolation)} }}\n"
            f"    __el_{s}.flipFacing();\n"
            f"}}\n")
    decl = f"FamilyInstance __el_{s} = null;"
    # Точка НА ХОСТЕ — та же перегрузка, которой уже ставятся двери и окна
    # (`_emit_hosted`): оборудование, закреплённое на стене или потолке,
    # отличается от двери только тем, что адресуется точкой, а не смещением
    # вдоль кривой хоста.
    #
    # ЗАМЕР 28.07 (ЭОМ): после того как боковой индекс покрыл разделы,
    # ЕДИНСТВЕННОЙ оставшейся причиной атомов стали 199 элементов «hosted
    # FamilyInstance placement is not represented by place_family». Оп умел
    # ставить только неhosted — и терял на этом каждый закреплённый прибор.
    #
    # Ветка отделена условием: программа БЕЗ хоста эмитится дословно как
    # раньше (18 700 экземпляров демо заморожены корпусом паритета).
    host_pt = op.get("host") or {}
    host_pt_ref = host_pt.get("value")
    host_pt_grounded = host_pt.get("__grounded__") or {}
    host_pt_expr = ""
    if isinstance(host_pt_ref, str) and not host_pt_grounded:
        host_pt_expr = "__el_" + _safe(host_pt_ref)
    elif host_pt_grounded.get("id") is not None:
        host_pt_expr = f"doc.GetElement({_eid(host_pt_grounded['id'], ver, oid)})"
    # NewFamilyInstance(point, symbol, level) трактует z точки как офсет НАД
    # уровнем (Revit прибавляет Level.Elevation) — передаём z−elevation;
    # свидетель ниже сверяет абсолютный z по LocationPoint.
    if host_pt_expr:
        # То же объявление вне блока, что и у кривой (см. её комментарий):
        # свидетель хоста живёт за пределами per-op блока.
        decl += f"\nElement __pfh_{s} = null;"
        place_cs = (
            f"__pfh_{s} = {host_pt_expr};\n"
            f"if (__pfh_{s} == null) {{ {refuse_stmt(oid, _cs('хост не найден'), isolation)} }}\n"
            # У hosted-перегрузки z — АБСОЛЮТНЫЙ (её уровень контекстный, не
            # база отсчёта): та же оговорка, что у create_door/create_window.
            f"XYZ __pfp_{s} = new XYZ(U({x}), U({y}), U({z}));\n"
            f"__el_{s} = doc.Create.NewFamilyInstance(__pfp_{s}, __sy_{s}, __pfh_{s}, __lv_{s}, "
            f"Autodesk.Revit.DB.Structure.StructuralType.NonStructural);\n")
    else:
        place_cs = (
            f"XYZ __pfp_{s} = new XYZ(U({x}), U({y}), U({z}) - __lv_{s}.Elevation);\n"
            f"__el_{s} = doc.Create.NewFamilyInstance(__pfp_{s}, __sy_{s}, __lv_{s}, "
            f"Autodesk.Revit.DB.Structure.StructuralType.NonStructural);\n")
    # ── ДВА УРОВНЯ (11.08.2026): TwoLevelsBased ────────────────────────
    #
    # Отдельной перегрузки у Revit для этого рода НЕТ — экземпляр
    # ставится той же точечной перегрузкой, а «до какого уровня» задаётся
    # ПАРАМЕТРАМИ после размещения. Поэтому это не третья ветка, а
    # ДОПИСКА к точечной, и она пуста, когда `top_level` не назван:
    # байты каждой уже написанной программы place_family не двигаются
    # (тот же приём, которым живут rotate/mirror/hand/facing выше).
    #
    # Имена параметров — те же, что у create_column, который держит этот
    # род для колонн с 21.07: FAMILY_TOP_LEVEL_PARAM и пара смещений.
    # Второй словарь для «верха привязки» означал бы двух судей о нём.
    two_levels = ""
    tl = op.get("top_level")
    tl_idexpr = None
    if isinstance(tl, dict) and "__grounded__" in tl:
        # ЧИТАЕТСЯ ТЕМ ЖЕ СПОСОБОМ, ЧТО У create_column, а не вторым
        # своим: заземлённый селектор приходит в конверте
        # `__grounded__`, и «ссылка на оп» отличается от «готовый id»
        # полем `via`, а не формой value. Своя проверка формы здесь
        # давала KIR-G002 на ВЕРНОЙ программе (замер на своей же
        # правке 11.08) — ровно тот второй судья, которого этот файл
        # запрещает.
        gtl = _gid(op, "top_level")
        if gtl.get("via") == "ref":
            tl_expr = "__el_" + _safe(gtl["ref"]) + ".Id"
            tl_idexpr = "__el_" + _safe(gtl["ref"]) + ".Id.ToString()"
        else:
            tl_expr = _eid(gtl["id"], ver, oid)
            tl_idexpr = _cs(str(gtl["id"]))
    if tl_idexpr is not None:
        two_levels = (
            f"Parameter __ptl_{s} = __el_{s}.get_Parameter("
            f"BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);\n"
            # РОД РАЗМЕЩЕНИЯ — ФАКТ О СЕМЕЙСТВЕ. Параметра верхнего
            # уровня у одноуровневого семейства нет вовсе, и просьба
            # невыполнима не потому, что постройка плоха, а потому, что
            # тип другой. Отказ называет фактический род — автору есть
            # что исправить.
            f"if (__ptl_{s} == null || __ptl_{s}.IsReadOnly)\n{{ "
            + refuse_stmt(
                oid,
                f'"place_family: у семейства нет записываемого верхнего "'
                f' + "уровня (род размещения " + (__sy_{s}.Family == null'
                f' ? "неизвестен" : __sy_{s}.Family.FamilyPlacementType'
                f'.ToString()) + "), а top_level задан"',
                isolation)
            + " }\n"
            f"if (!__ptl_{s}.Set({tl_expr})) {{ "
            + refuse_stmt(oid, _cs("запись верхнего уровня отклонена "
                                   "Revit"), isolation)
            + " }\n")
        for pname, bip in (("base_offset_mm",
                            "FAMILY_BASE_LEVEL_OFFSET_PARAM"),
                           ("top_offset_mm",
                            "FAMILY_TOP_LEVEL_OFFSET_PARAM")):
            if pname not in op:
                continue
            short = "bo" if pname == "base_offset_mm" else "to"
            two_levels += (
                f"Parameter __p{short}_{s} = __el_{s}.get_Parameter("
                f"BuiltInParameter.{bip});\n"
                f"if (__p{short}_{s} == null || __p{short}_{s}.IsReadOnly) {{ "
                + refuse_stmt(oid, _cs(f"{pname} недоступен для записи "
                                       f"у этого семейства"), isolation)
                + " }\n"
                f"if (!__p{short}_{s}.Set(U({float(op[pname])}))) {{ "
                + refuse_stmt(oid, _cs(f"запись {pname} отклонена Revit"),
                              isolation)
                + " }\n")
    create = (f"// place_family {cs_line_comment_fragment(oid)}\n"
              + _symbol_res(op, s, oid, ver, isolation) + f"\n{lv_res}\n"
              + place_cs +
              f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('NewFamilyInstance вернул null'), isolation)} }}\n"
              + two_levels
              + rotate
              + mirror
              + hand
              + facing
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    ptols = tolerances("place_family")
    rtol = ptols["rotation_deg"]
    rotation_post = ""
    if has_rotation:
        rotation_post = (
            f"    if (__loc != null)\n    {{\n"
            f"        double __wantRot_{s} = {rotation_deg} * Math.PI / 180.0;\n"
            f"        double __rotDelta_{s} = Math.Atan2(\n"
            f"            Math.Sin(__loc.Rotation - __wantRot_{s}),\n"
            f"            Math.Cos(__loc.Rotation - __wantRot_{s}));\n"
            # Тот же приём, что у create_column: 0.1deg из реестра ->
            # делитель 1800.0 через Decimal, байты выражения не движутся.
            f"        if (Math.Abs(__rotDelta_{s}) > Math.PI / {rtol.deg_rad_divisor})\n"
            f"            __post.Add({_cs(oid + ': rotation mismatch (geometry, tolerance 0.1deg)')});\n"
            f"    }}\n")
    state_post = ""
    if has_mirrored:
        desired = "true" if mirrored else "false"
        state_post += (
            f"    if (__el_{s}.Mirrored != {desired})\n"
            f"        __post.Add({_cs(oid + ': mirrored state mismatch (semantic)')});\n")
    if has_hand:
        desired = "true" if hand_flipped else "false"
        state_post += (
            f"    if (__el_{s}.HandFlipped != {desired})\n"
            f"        __post.Add({_cs(oid + ': hand flip state mismatch (semantic)')});\n")
    if has_facing:
        desired = "true" if facing_flipped else "false"
        state_post += (
            f"    if (__el_{s}.FacingFlipped != {desired})\n"
            f"        __post.Add({_cs(oid + ': facing flip state mismatch (semantic)')});\n")
    ptol = ptols["location_mm"]
    checks: list[WitnessCheck] = [WitnessCheck(
        obligation_key="location",
        reader_cs=f"    var __loc = __el_{s}.Location as LocationPoint;\n",
        verdict_cs=(
            f"    if (__loc == null) __post.Add({_cs(oid + ': нет LocationPoint')});\n"
            f"    else if (Math.Abs(MM(__loc.Point.X) - {x}) > {ptol} || Math.Abs(MM(__loc.Point.Y) - {y}) > {ptol} || Math.Abs(MM(__loc.Point.Z) - {z}) > {ptol})\n"
            f"        __post.Add({_cs(oid + ': location mismatch (geometry)')});\n"),
        message="location mismatch (geometry)",
        tol=ptol,
        style="else_block")]
    if host_pt_expr:
        # Хост задан ⇒ обязан быть прочитан обратно. Без этой проверки
        # «поставили на стену» и «поставили рядом со стеной» неразличимы.
        checks.append(WitnessCheck(
            obligation_key="host", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.Host == null || __el_{s}.Host.Id.ToString() != __pfh_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': host mismatch (topology)')});\n"),
            message="host mismatch (topology)", style="guard"))
    if rotation_post:
        checks.append(WitnessCheck(
            obligation_key="rotation", reader_cs="",
            verdict_cs=rotation_post,
            message="rotation mismatch (geometry, tolerance 0.1deg)",
            tol=rtol, style="guard"))
    if has_mirrored:
        desired = "true" if mirrored else "false"
        checks.append(WitnessCheck(
            obligation_key="mirrored", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.Mirrored != {desired})\n"
                f"        __post.Add({_cs(oid + ': mirrored state mismatch (semantic)')});\n"),
            message="mirrored state mismatch (semantic)", style="guard"))
    if has_hand:
        desired = "true" if hand_flipped else "false"
        checks.append(WitnessCheck(
            obligation_key="hand_flipped", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.HandFlipped != {desired})\n"
                f"        __post.Add({_cs(oid + ': hand flip state mismatch (semantic)')}\n"
                f"            + (__el_{s}.CanFlipHand ? \"\" : \" — семейство не допускает флипа\"));\n"),
            message="hand flip state mismatch (semantic)", style="guard"))
    if has_facing:
        desired = "true" if facing_flipped else "false"
        checks.append(WitnessCheck(
            obligation_key="facing_flipped", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.FacingFlipped != {desired})\n"
                f"        __post.Add({_cs(oid + ': facing flip state mismatch (semantic)')}\n"
                f"            + (__el_{s}.CanFlipFacing ? \"\" : \" — семейство не допускает флипа\"));\n"),
            message="facing flip state mismatch (semantic)", style="guard"))
    # ── СВИДЕТЕЛИ ДВУХ УРОВНЕЙ (11.08) ────────────────────────────────
    #
    # Сеттер без свидетеля — главный рецидивный дефект этого кода: он
    # проходит все тесты и не доказывает ничего. Всё, что дописка выше
    # ЗАПИСАЛА, здесь ПЕРЕЧИТЫВАЕТСЯ из документа.
    if tl_idexpr is not None:
        # ОСЬ — ТОПОЛОГИЯ, И ЧИТАЕТСЯ ИМЕННО ОНА: связь экземпляра с
        # уровнем есть отношение, а не размер. Тот же род свидетеля и тот
        # же BIP-читатель, что у базового уровня стены и опорного уровня
        # трубы, — один вопрос, один судья.
        checks.append(WitnessCheck(
            obligation_key="top_level_binding",
            reader_cs=(
                f"    Parameter __rtl_{s} = __el_{s}.get_Parameter("
                f"BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);\n"),
            verdict_cs=(
                f"    if (__rtl_{s} == null\n"
                f"        || __rtl_{s}.AsElementId() == ElementId.InvalidElementId\n"
                f"        || __rtl_{s}.AsElementId().ToString() != {tl_idexpr})\n"
                f"        __post.Add({_cs(oid + ': top level binding mismatch (topology)')});\n"),
            message="top level binding mismatch (topology)", style="guard"))
    # СМЕЩЕНИЯ ПОДПИСАНЫ СЕМАНТИКОЙ, А НЕ ГЕОМЕТРИЕЙ, И ЭТО НЕ РОБОСТЬ.
    # §18.3: проверка, подписанная «(geometry)», чей читатель состоит
    # ТОЛЬКО из `get_Parameter(...)`, геометрию не разряжает — читатель
    # тут именно такой. Утверждение, которое он ДЕЙСТВИТЕЛЬНО доказывает,
    # семантическое: «параметр держит запрошенное число». Подписать его
    # геометрией значило бы просить исключение в списке
    # `_ALLOWED_PARAMETER_GEOMETRY` под утверждение, которого никто не
    # мерил; у create_column такие исключения есть и каждое оплачено
    # разбором — здесь платить нечем, поэтому подпись честная и узкая.
    for pname, bip, short, key in (
            ("base_offset_mm", "FAMILY_BASE_LEVEL_OFFSET_PARAM", "rbo",
             "base_offset"),
            ("top_offset_mm", "FAMILY_TOP_LEVEL_OFFSET_PARAM", "rto",
             "top_offset")):
        if pname not in op:
            continue
        want = float(op[pname])
        otol = tolerance("place_family", pname)
        checks.append(WitnessCheck(
            obligation_key=key,
            reader_cs=(
                f"    Parameter __{short}_{s} = __el_{s}.get_Parameter("
                f"BuiltInParameter.{bip});\n"),
            verdict_cs=(
                f"    if (__{short}_{s} == null\n"
                f"        || Math.Abs(MM(__{short}_{s}.AsDouble()) - {want}) > {otol})\n"
                f"        __post.Add({_cs(oid + ': ' + pname + ' mismatch (semantic)')});\n"),
            message=pname + " mismatch (semantic)",
            tol=otol, style="guard"))
    checks.append(level_chain_witness(f"__el_{s}", oid, lv_idexpr))
    return decl, create, checks, _readback_block(
        s,
        oid,
        stamp,
        location_rotation=has_rotation,
        family_state=has_mirrored or has_hand or has_facing,
        identity_version=ver,
    )


def _emit_duct(op: dict, ver: str, stamp: str,
               isolation: str = "atomic") -> tuple[str, str, str, str]:
    """Mirror of _emit_pipe over Mechanical.Duct.Create (same arg shape,
    signature verified 2021-2026: (Document, systemTypeId, ductTypeId,
    levelId, XYZ, XYZ))."""
    oid = op["id"]
    s = _safe(oid)
    st = _gid(op, "system_type")
    dt = _gid(op, "duct_type")
    x0, y0, z0 = _pt3(op["p0_mm"])
    x1, y1, z1 = _pt3(op["p1_mm"])
    d = op.get("diameter_mm")
    decl = f"Autodesk.Revit.DB.Mechanical.Duct __el_{s} = null;"
    dia = ""
    if d is not None:
        dia = (f"\ntry {{ Parameter __dp_{s} = __el_{s}.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM); "
               f"if (__dp_{s} != null && !__dp_{s}.IsReadOnly) __dp_{s}.Set(U({d})); }} catch {{ }}")
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    create = (
        f"// create_duct {cs_line_comment_fragment(oid)}\n"
        + lv_res + "\n"
        f"__el_{s} = Autodesk.Revit.DB.Mechanical.Duct.Create(doc, {_eid(st['id'], ver, oid)}, "
        f"{_eid(dt['id'], ver, oid)}, __lv_{s}.Id, P({x0}, {y0}, {z0}), P({x1}, {y1}, {z1}));\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('Duct.Create вернул null'), isolation)} }}"
        + dia + "\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # Wave A2 model post (same glue discipline as create_pipe).
    dtol = tolerances("create_duct")
    checks: list[WitnessCheck] = [
        # ИТОГ ПОСЛЕДНЕГО ЗАКОННОГО ПИСАТЕЛЯ (E-3): тот же закон, что у
        # `create_wall` (E-2) — `emit_core.final_shift`, один читатель.
        endpoint_witness(f"__el_{s}", oid, op["p0_mm"], op["p1_mm"],
                         dtol["endpoint_mm"], True, shift=final_shift(op)),
        level_binding_witness(
            f"__el_{s}", oid, "RBS_START_LEVEL_PARAM", lv_idexpr,
            key="reference_level",
            tail=("" if d is not None else "\n")),
    ]
    if d is not None:
        checks.append(WitnessCheck(
            obligation_key="diameter",
            reader_cs=(f"\n    var __dp = __el_{s}.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM);\n"),
            # ДВА СЛУЧАЯ ВРОЗЬ, а не один. Живой замер 30.07 на образце
            # Snowdon: `create_duct` с diameter_mm на типе «Mitered Elbows /
            # Tees» строил воздуховод и откатывался с одним словом «diameter
            # mismatch». Откат был честный, диагноз — нет: у ПРЯМОУГОЛЬНОГО
            # воздуховода параметра диаметра не существует вовсе, и модели
            # надо чинить не число, а сам замысел. Подтверждено опровержением:
            # тот же оп без diameter_mm строит.
            #
            # Формы сечения нет в пуле заземления, поэтому отказать НА
            # КОМПИЛЯЦИИ нечем: единственное место, где она известна, —
            # исполнение. Отсюда правило «отсутствие параметра и расхождение
            # значения — разные отказы», а не расширение снимка ради текста.
            verdict_cs=(
                f"    if (__dp == null)\n"
                f"        __post.Add({_cs(oid + ': diameter mismatch — у элемента нет параметра диаметра: сечение не круглое, а диаметр применим только к круглому')});\n"
                f"    else if (Math.Abs(MM(__dp.AsDouble()) - {d}) > {dtol['diameter_mm']})\n"
                f"        __post.Add({_cs(oid + ': diameter mismatch')});\n"),
            message="diameter mismatch",
            tol=dtol["diameter_mm"],
            style="guard"))
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


_TRAY_SECTION = (
    ("width_mm", "RBS_CABLETRAY_WIDTH_PARAM", "width", "__twp"),
    ("height_mm", "RBS_CABLETRAY_HEIGHT_PARAM", "height", "__thp"),
)


def _emit_cable_tray(op: dict, ver: str, stamp: str,
                     isolation: str = "atomic") -> tuple[str, str, str, str]:
    """Electrical.CableTray.Create(Document, trayTypeId, XYZ, XYZ, levelId)
    — NB the argument order differs from Pipe/Duct (verified per-version
    signature DB, stable 2021-2026)."""
    oid = op["id"]
    s = _safe(oid)
    tt = _gid(op, "tray_type")
    x0, y0, z0 = _pt3(op["p0_mm"])
    x1, y1, z1 = _pt3(op["p1_mm"])
    decl = f"Autodesk.Revit.DB.Electrical.CableTray __el_{s} = null;"
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    section = ""
    for field, bip, _key, var in _TRAY_SECTION:
        value = op.get(field)
        if value is None:
            continue
        # CableTray.Create has no sized overload; size is writable only on
        # the new instance.  A swallowed setter error cannot become success:
        # the independent readback below then records a mismatch and rolls
        # the transaction back.
        section += (
            f"\ntry {{ Parameter {var}_{s} = __el_{s}.get_Parameter("
            f"BuiltInParameter.{bip}); if ({var}_{s} != null && "
            f"!{var}_{s}.IsReadOnly) {var}_{s}.Set(U({value})); }} catch {{ }}")
    create = (
        f"// create_cable_tray {cs_line_comment_fragment(oid)}\n"
        + lv_res + "\n"
        f"__el_{s} = Autodesk.Revit.DB.Electrical.CableTray.Create(doc, {_eid(tt['id'], ver, oid)}, "
        f"P({x0}, {y0}, {z0}), P({x1}, {y1}, {z1}), __lv_{s}.Id);\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('CableTray.Create вернул null'), isolation)} }}"
        + section + "\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # Wave A2 model post.
    has_section = any(op.get(field) is not None for field, *_ in _TRAY_SECTION)
    checks: list[WitnessCheck] = [
        # ИТОГ ПОСЛЕДНЕГО ЗАКОННОГО ПИСАТЕЛЯ (E-3): тот же закон, что у
        # `create_wall` (E-2) — `emit_core.final_shift`, один читатель.
        endpoint_witness(
            f"__el_{s}", oid, op["p0_mm"], op["p1_mm"],
            tolerance("create_cable_tray", "endpoint_mm"), True,
            shift=final_shift(op)),
        level_binding_witness(
            f"__el_{s}", oid, "RBS_START_LEVEL_PARAM", lv_idexpr,
            key="reference_level", tail=("" if has_section else "\n")),
    ]
    section_tol = tolerance("create_cable_tray", "section_mm")
    for field, bip, key, var in _TRAY_SECTION:
        value = op.get(field)
        if value is None:
            continue
        checks.append(WitnessCheck(
            obligation_key=key,
            reader_cs=(
                f"\n    var {var} = __el_{s}.get_Parameter("
                f"BuiltInParameter.{bip});\n"),
            verdict_cs=(
                f"    if ({var} == null)\n"
                f"        __post.Add({_cs(oid + f': {key} mismatch — у элемента нет параметра сечения лотка')});\n"
                f"    else if (Math.Abs(MM({var}.AsDouble()) - {value}) > "
                f"{section_tol})\n"
                f"        __post.Add({_cs(oid + f': {key} mismatch')});\n"),
            message=f"{key} mismatch", tol=section_tol, style="guard"))
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


def _emit_roof(op: dict, ver: str, stamp: str,
               isolation: str = "atomic") -> tuple[str, str, str, str]:
    """Footprint roof over the outline (flat; ring implied). API stable
    2021-2026: doc.Create.NewFootPrintRoof(CurveArray, Level, RoofType,
    out ModelCurveArray)."""
    oid = op["id"]
    s = _safe(oid)
    g_type = _gid(op, "type") if isinstance(op.get("type"), dict) and "__grounded__" in op["type"] else None
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    decl = f"FootPrintRoof __el_{s} = null;"
    if g_type and g_type.get("in_emit") == IN_EMIT_DEFAULT:
        rt = (f"RoofType __rt_{s} = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.RoofType)) as RoofType;\n"
              f"if (__rt_{s} == null) {{ {refuse_stmt(oid, _cs('в документе нет типа кровли по умолчанию'), isolation)} }}")
    # ТИП, СОЗДАННЫЙ ЭТОЙ ЖЕ ПРОГРАММОЙ (`create_wall_type` с host_kind=
    # "roof"). Ни `GetElement`, ни сторож дрейфа здесь не нужны и были бы
    # ложью: элемент создан выше, в этой же транзакции, и его переменная уже
    # держит нужный род. Та же ветка и тот же довод, что у `create_wall.type`
    # с 23.08 — без неё оп получал грунтованную ссылку без `id` и падал
    # KIR-P000 «внутренняя ошибка компилятора» (замер 24.08.2026).
    elif g_type and g_type.get("via") == "ref":
        rt = f"RoofType __rt_{s} = __el_{_safe(g_type['ref'])};"
    else:
        rt = (f"RoofType __rt_{s} = doc.GetElement({_eid(g_type['id'], ver, oid)}) as RoofType;\n"
              f"if (__rt_{s} == null) {{ {refuse_stmt(oid, _cs('тип кровли не найден (модель изменилась после grounding)'), isolation)} }}")
    outline = op["outline"]
    # slopes: Revit pitches a footprint roof edge by edge, through the model
    # curves NewFootPrintRoof hands back.  -1 marks an edge that stays level,
    # so one array carries both which edges pitch and by how much, in the
    # footprint's own order.  Absent -> not a single extra byte is emitted and
    # the roof is the historical flat one.
    slopes = op.get("slopes")
    pitch = ""
    if slopes:
        # MEASURED, not assumed: set_SlopeAngle takes the slope RATIO
        # (rise/run), not radians.  A 45-degree roof sent as 0.7854 radians
        # came back 5221mm tall where 45 degrees needs 6400 — Revit had read
        # 0.7854 as the ratio, i.e. 38.15 degrees, and the vertical thickness
        # 400/cos(38.15) = 509 accounts for the rest to the millimetre.
        angles = ", ".join(
            "-1.0" if x is None else f"{math.tan(math.radians(float(x))):.9f}"
            for x in slopes)
        pitch = (
            f"double[] __sl_{s} = new double[] {{ {angles} }};\n"
            f"int __sk_{s} = 0;\n"
            f"foreach (ModelCurve __mc_{s} in __ma_{s})\n"
            f"{{\n"
            f"    if (__sk_{s} < __sl_{s}.Length && __sl_{s}[__sk_{s}] >= 0.0)\n"
            f"    {{\n"
            f"        __el_{s}.set_DefinesSlope(__mc_{s}, true);\n"
            f"        __el_{s}.set_SlopeAngle(__mc_{s}, __sl_{s}[__sk_{s}]);\n"
            f"    }}\n"
            f"    __sk_{s}++;\n"
            f"}}\n"
            f"doc.Regenerate();\n")
    geo = [f"CurveArray __ca_{s} = new CurveArray();"]
    n = len(outline)
    for k in range(n):
        a, b = outline[k], outline[(k + 1) % n]
        geo.append(f"__ca_{s}.Append(Line.CreateBound(P({a[0]}, {a[1]}, 0), P({b[0]}, {b[1]}, 0)));")
    create = (
        f"// create_roof {cs_line_comment_fragment(oid)}\n{rt}\n{lv_res}\n"
        + "\n".join(geo) + "\n"
        f"ModelCurveArray __ma_{s} = new ModelCurveArray();\n"
        f"__el_{s} = doc.Create.NewFootPrintRoof(__ca_{s}, __lv_{s}, __rt_{s}, out __ma_{s});\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('NewFootPrintRoof вернул null'), isolation)} }}\n"
        + pitch
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    xs = [pt[0] for pt in outline]; ys = [pt[1] for pt in outline]
    rtol = tolerance("create_roof", "bbox_mm")
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="base_level",
            reader_cs=f"    var __blp = __el_{s}.get_Parameter(BuiltInParameter.ROOF_BASE_LEVEL_PARAM);\n",
            verdict_cs=(
                f"    if (__blp == null || __blp.AsElementId() == null || __blp.AsElementId().ToString() != {lv_idexpr})\n"
                f"        __post.Add({_cs(oid + ': base level mismatch (topology)')});\n"),
            message="base level mismatch (topology)",
            style="guard"),
        bbox_extents_witness(
            f"__el_{s}", oid, min(xs), max(xs), min(ys), max(ys), rtol),
        # ФОРМА ПОДОШВЫ РЯДОМ С ГАБАРИТОМ. Кровля по подошве —
        # `NewFootPrintRoof`, то есть у неё зависимый Sketch ровно как у
        # плиты, и читатель берётся ТОТ ЖЕ, без второго способа.
        #
        # Что это ловит сверх габарита: сдвинутый внутренний угол
        # Г-образной кровли и потерянный излом подошвы. Уклон при этом
        # свидетельствуется ОТДЕЛЬНО (вертикальный размах ниже) —
        # подошва плоская по построению, и подпись колец про наклон
        # ничего не утверждает.
        sketch_loops_witness(
            f"__el_{s}", oid, [[list(pt) for pt in outline]],
            tolerance("create_roof", "sketch_mm")),
    ]
    if slopes:
        # The lesson of the wall location line: check the SHAPE, not the fact
        # that a setter ran.  A pitched roof must gain vertical extent; one
        # that quietly stayed flat satisfies every other obligation here.
        rise_mm = _expected_roof_rise_mm(outline, slopes)
        checks.append(WitnessCheck(
            obligation_key="slopes",
            reader_cs=(
                f"    var __rb2 = __el_{s}.get_BoundingBox(null);\n"),
            verdict_cs=(
                f"    if (__rb2 == null)\n"
                f"        __post.Add({_cs(oid + ': нет bbox для проверки уклона (geometry)')});\n"
                # 🔴 ИЗМЕРЕННОЕ ПЕЧАТАЕТСЯ — правило этого дома, которого
                # здесь не было. При нарушении постусловий транзакция
                # откатывается, и числа не увидит НИКТО: «уклон не тот» стоило
                # живого захода 24.08, когда три кровли из 74 операций
                # откатили ВЕСЬ перенос, а причину пришлось выводить
                # арифметикой на стороне.
                f"    else if (MM(__rb2.Max.Z - __rb2.Min.Z) < {rise_mm:.1f})\n"
                f"        __post.Add({_cs(oid + ': уклон крыши не тот (geometry): подъём ')}\n"
                f"            + MM(__rb2.Max.Z - __rb2.Min.Z).ToString(\"F1\")\n"
                f"            + {_cs(f' мм против ожидаемых не менее {rise_mm:.1f} мм')});\n"),
            message="уклон крыши не тот (geometry)",
            style="guard"))
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


def _expected_roof_rise_mm(outline, slopes) -> float:
    """The rise a correctly pitched roof must reach, in mm.

    A first version only asked "did it gain ANY height", and that is precisely
    how a roof built at 38 degrees instead of the requested 45 passed live:
    it had risen, just not by the right amount.  So the bound is the real
    prediction — each sloped edge lifts the roof by its RUN (the farthest
    perpendicular distance from that edge to the outline) times the tangent of
    its pitch, and where several edges slope they meet at whichever apex comes
    lowest.

    A small slack stays below the true rise so roof thickness and Revit's own
    solver can only ever push the measured extent UP, never below the bound.
    """
    n = len(outline)
    planes = []
    for k, pitch in enumerate(slopes):
        if pitch is None:
            continue
        ax, ay = outline[k]
        bx, by = outline[(k + 1) % n]
        edge = math.hypot(bx - ax, by - ay)
        if edge <= 0.0:
            continue
        planes.append((ax, ay, bx, by, edge, math.tan(math.radians(float(pitch)))))
    if not planes:
        return 1.0

    def height(px, py):
        """Высота ОГИБАЮЩЕЙ в точке: скат — плоскость, вращаемая вокруг своего
        ребра, а крыша — их НИЖНЯЯ огибающая, то есть минимум."""
        return min(
            abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / edge * tan
            for ax, ay, bx, by, edge, tan in planes)

    def inside(px, py):
        hit = False
        for i in range(n):
            x1, y1 = outline[i][0], outline[i][1]
            x2, y2 = outline[(i + 1) % n][0], outline[(i + 1) % n][1]
            if (y1 > py) != (y2 > py):
                xx = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
                if xx > px:
                    hit = not hit
        return hit

    xs = [pt[0] for pt in outline]
    ys = [pt[1] for pt in outline]
    lo_x, hi_x, lo_y, hi_y = min(xs), max(xs), min(ys), max(ys)
    best = 0.0
    steps = 48
    for _round in range(4):
        found = None
        dx = (hi_x - lo_x) / steps
        dy = (hi_y - lo_y) / steps
        for i in range(steps + 1):
            px = lo_x + dx * i
            for j in range(steps + 1):
                py = lo_y + dy * j
                if not inside(px, py):
                    continue
                h = height(px, py)
                if h > best:
                    best, found = h, (px, py)
        if found is None:
            break
        # Сужаем окно вокруг найденного максимума — детерминированно, без
        # случайности: тот же вход всегда даёт тот же порог, иначе байты
        # эмиссии перестали бы быть функцией программы.
        cx, cy = found
        lo_x, hi_x = cx - dx, cx + dx
        lo_y, hi_y = cy - dy, cy + dy
    return max(1.0, best * 0.95)


def _emit_floor_contour(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, str, str]:
    from kir import contour as C
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    holes = region["holes"]
    if holes and ver < "2022":
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED, op_id=oid, field_name="contour.holes",
            message_ru=f"проёмы в перекрытии-по-контуру не поддержаны на Revit {ver}")])
    lv = _gid(op, "level")
    g_type = _gid(op, "type") if isinstance(op.get("type"), dict) and "__grounded__" in op["type"] else None
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    decl = f"Floor __el_{s} = null;\n" + type_assignment_declarations(oid)
    if g_type and g_type.get("in_emit") == IN_EMIT_DEFAULT:
        ft = (f"FloorType __ft_{s} = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.FloorType)) as FloorType;\n"
              f"if (__ft_{s} == null) {{ {refuse_stmt(oid, _cs('в документе нет типа перекрытия по умолчанию'), isolation)} }}")
    # ТИП, СОЗДАННЫЙ ЭТОЙ ЖЕ ПРОГРАММОЙ (`create_wall_type` с host_kind=
    # "floor"). Ни `GetElement`, ни сторож дрейфа здесь не нужны и были бы
    # ложью: элемент создан выше, в этой же транзакции, и его переменная уже
    # держит нужный род. Та же ветка и тот же довод, что у `create_wall.type`
    # с 23.08 — без неё оп получал грунтованную ссылку без `id` и падал
    # KIR-P000 «внутренняя ошибка компилятора» (замер 24.08.2026).
    elif g_type and g_type.get("via") == "ref":
        ft = f"FloorType __ft_{s} = __el_{_safe(g_type['ref'])};"
    else:
        ft = (f"FloorType __ft_{s} = doc.GetElement({_eid(g_type['id'], ver, oid)}) as FloorType;\n"
              f"if (__ft_{s} == null) {{ {refuse_stmt(oid, _cs('тип перекрытия не найден (модель изменилась после grounding)'), isolation)} }}")
    if ver >= "2022":
        geo = [f"var __loops_{s} = new List<CurveLoop>();",
               C.emit_loop_cs(region["outer"], f"__ol_{s}"),
               f"__loops_{s}.Add(__ol_{s});"]
        for hi, hole in enumerate(holes):
            geo.append(C.emit_loop_cs(hole, f"__hl_{s}_{hi}"))
            geo.append(f"__loops_{s}.Add(__hl_{s}_{hi});")
        make = f"__el_{s} = Floor.Create(doc, __loops_{s}, __ft_{s}.Id, __lv_{s}.Id);"
    else:
        geo = [C.emit_curvearray_cs(region["outer"], f"__ca_{s}")]
        make = f"__el_{s} = doc.Create.NewFloor(__ca_{s}, __ft_{s}, __lv_{s}, false);"
    # Смещение от уровня — та же ветка, что у create_floor: параметр тот же
    # (FLOOR_HEIGHTABOVELEVEL_PARAM), недоступный или только для чтения —
    # типизированный отказ, а не молчаливый пол на плоскости уровня.
    height_offset = op.get("height_offset_mm")
    ho_set = ""
    if height_offset is not None:
        ho_set = (
            f"\nParameter __fho_{s} = __el_{s}.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM);\n"
            f"if (__fho_{s} == null || __fho_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('FLOOR_HEIGHTABOVELEVEL_PARAM недоступен у перекрытия'), isolation)} }}\n"
            f"__fho_{s}.Set(U({height_offset}));")
    create = (f"// create_floor_by_contour {cs_line_comment_fragment(oid)}\n{ft}\n{lv_res}\n"
              + "\n".join(geo) + f"\n{make}\n"
              f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('создание перекрытия вернуло null'), isolation)} }}\n"
              + ho_set
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    x0, y0, x1, y1 = C.edges_bbox(region["outer"])
    ctol = tolerances("create_floor_by_contour")
    # 🔴 ГАБАРИТ КОЛЬЦА СО СПЛАЙНОМ НЕ ПРИШПИЛИВАЕТСЯ — ИЗМЕРЕНО ЖИВЬЁМ.
    # Тремя строками ниже с 20.08 стояло «габарит на сплайне занижен по
    # построению», и свидетель всё равно вешался БЕЗУСЛОВНО: знание жило в
    # комментарии, а решение принимал код. Первый же живой прогон плиты с
    # волнистым краем (Revit 2026): Ревит дал по Y 9705.3 мм, наша выборка
    # ждала 9426.0 — разъезд 279 мм при допуске 50.
    #
    # ЭТО НЕ ПОГРЕШНОСТЬ, А РАЗНЫЕ КРИВЫЕ. Мы приближаем ребро Катмуллом–Ромом
    # НА КОМПИЛЯЦИИ, Ревит строит `HermiteSpline` со своими касательными;
    # алгоритм не документирован, и совпадения экстремумов быть не может ни
    # при каком допуске. Допуск, растянутый до 300 мм, подписал бы и настоящую
    # ошибку — то есть свидетель, который не может провалиться.
    #
    # ЧТО ВМЕСТО. Точки, ЧЕРЕЗ которые кривая объявлена идти, доказываются
    # `spline_points_witness` — он читает `Sketch.Profile` и меряет расстояние
    # до реальной кривой. Габарит становится НАЗВАННЫМ ОТСУТСТВИЕМ
    # (`_NON_WITNESSABLE_CLAUSES`), а не молча растянутым допуском.
    ring_has_spline = any(C.is_spline(b) for _p0, _p1, b in region["outer"]) \
        or any(C.is_spline(b) for h in holes for _p0, _p1, b in h)
    checks: list[WitnessCheck] = [
        type_assignment_witness(f"__el_{s}", f"__ft_{s}", oid),
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
    ]
    if not ring_has_spline:
        checks.append(bbox_extents_witness(
            f"__el_{s}", oid, round(x0, 1), round(x1, 1),
            round(y0, 1), round(y1, 1), ctol["bbox_mm"]))
    checks += [
        # ФОРМА РЯДОМ С ГАБАРИТОМ. Габарит по опущенным рёбрам знает
        # кардинальные экстремумы дуги — стрелку, которой нет среди вершин;
        # вершины знают сдвинутый внутренний угол и потерянное отверстие,
        # которых габарит не видит. Ни один не подмножество другого.
        #
        # Дуга свидетелю формы не мешает: `GetEndPoint(0)` даёт по одной
        # вершине на авторское ребро, потому что Revit хранит дугу ОДНОЙ
        # кривой — замер 19.08.2026 по 67 разборам корпуса (10 463 кольца,
        # 259 с дугами, 331 кривая вида `arc` отдельными записями вперемешку
        # с `line`, ни одного пробега тесселяции).
        sketch_loops_witness(
            f"__el_{s}", oid,
            [C.edges_vertices(region["outer"])]
            + [C.edges_vertices(h) for h in holes],
            ctol["sketch_mm"]),
    ]
    # КРИВАЯ ДОКАЗЫВАЕТСЯ ОТДЕЛЬНО, ПОТОМУ ЧТО ОБА СОСЕДА К НЕЙ СЛЕПЫ.
    # `sketch_loops_witness` читает КОНЦЫ рёбер, а концы одни и те же у прямой
    # и у любой кривой между ними; габарит на сплайне занижен по построению.
    # Проверка добавляется ТОЛЬКО когда сплайн есть: свидетель, стоящий всегда,
    # платится каждой программой и ничего не различает.
    spline_pts = [pt for _k, pts in C.spline_witness_points(region["outer"])
                  for pt in pts]
    for _h in holes:
        spline_pts += [pt for _k, pts in C.spline_witness_points(_h)
                       for pt in pts]
    if spline_pts:
        checks.append(spline_points_witness(f"__el_{s}", oid, spline_pts,
                                            ctol["spline_point_mm"]))
    if height_offset is not None:
        checks.append(WitnessCheck(
            obligation_key="height_offset",
            reader_cs=(
                f"    var __fhop = __el_{s}.get_Parameter(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM);\n"),
            verdict_cs=(
                f"    if (__fhop == null || Math.Abs(MM(__fhop.AsDouble()) - {height_offset}) > {ctol['height_offset_mm']})\n"
                f"        __post.Add({_cs(oid + ': height offset mismatch (geometry)')});\n"),
            message="height offset mismatch (geometry)",
            tol=ctol["height_offset_mm"],
            style="guard"))
    return decl, create, checks, _readback_block(s, oid, stamp,
        identity_version=ver, extra_rows_cs=type_assignment_readback_cs(f"__el_{s}", oid))


def _segment_trim_bounds_mm(pa, pb, *, degree_a: int, degree_b: int,
                            tol_mm: float
                            ) -> tuple[float, float]:
    """Сколько конец участка вправе отступить ВНУТРЬ под врезку отвода.

    ЖИВОЙ ЗАМЕР 30.07 (Snowdon Towers Sample Plumbing). Прежнее постусловие
    требовало «конец == заказанный узел ±5 мм» на ОБОИХ концах — и на связной
    системе не могло выполниться никогда: Revit ставит в узле отвод и подрезает
    соседние участки под его грань. Различающий опыт: один участок проходил,
    два — нет, три — нет, причём топология (BFS по коннекторам) проходила
    везде. То есть система собиралась связной, а сверка объявляла её неверной.

    Правило различает роды концов:

    * узел степени 1 — конец СВОБОДНЫЙ, подрезать нечему, допуск прежний;
    * узел степени >1 — конец СТЫКОВАННЫЙ, отвод вправе съесть часть участка,
      но не больше половины: подрезка длиннее половины означает уже не врезку,
      а другую геометрию.

    Границей берётся БОЛЬШЕЕ из половины и допуска: на коротком участке
    половина меньше 5 мм, и стыкованный конец получил бы допуск СТРОЖЕ
    свободного — связная система из коротких участков стала бы непроходимой по
    новой причине вместо старой.

    ``tol_mm`` — ТОТ ЖЕ допуск конца, что и в свидетеле (``endpoint_mm`` опа
    из реестра). Обязателен и не имеет умолчания: пол подрезки, набранный
    здесь отдельным числом, был бы вторым домом одного допуска.
    """
    length = math.dist(pa, pb)
    if length <= 1e-6:
        # Нулевая длина — это не «всё сошлось», а отсутствие участка. Молча
        # растянуть допуск здесь значило бы принять пустоту за постройку.
        raise ValueError(
            f"segment has zero length between {pa!r} and {pb!r}")
    half = length / 2.0
    return (tol_mm if degree_a <= 1 else max(half, tol_mm),
            tol_mm if degree_b <= 1 else max(half, tol_mm))


def _network_geometry_post(graph: dict, seg_meta: list, oid: str,
                           diameter_bip: str,
                           op_name: str) -> tuple[str, str, object, object]:
    """Shared live geometry/diameter witness for CONNECT emitters.

    ``op_name`` — чей это свидетель: допуски конца и диаметра берутся из
    ``spec.OPS[op_name].tolerances`` (03.08). Формат подстановки ``:g``
    выбран не для красоты, а ради БАЙТОВ: исторический исходник набран
    целым (``> 5``) и коротким (``>0.5``), и подстановка ``5.0`` сдвинула бы
    весь корпус эталонных эмиссий.

    Endpoint orientation is chosen by full 3-D proximity to the declared
    start node. The old X/Y-only heuristic was ambiguous for every vertical
    segment. Every declared diameter is read back.

    The MEPSystem clause that used to live here was removed 2026-07-27: Revit
    derives system membership from the connector graph at COMMIT, so an
    in-transaction check can only ever see the per-segment systems
    `Pipe.Create` auto-assigns and must fail. It moved to the post-commit
    readback (`connect.emit_system_readback_cs`); the in-transaction semantic
    guarantee is the connectivity BFS. See connect.py §A for the measurements.
    """
    # ДВЕ части врозь, а не одна строка: сертификат разряжает обязательства
    # ПО КЛЮЧУ, и пока концы с диаметром ехали под общим ключом «endpoints»,
    # обязательства диаметра не существовало вовсе — аргумент `diameter_bip`
    # принимался и не использовался ни разу, а удаление проверки из эмиттера
    # оставляло сертификат «доказанным».
    ntol = tolerances(op_name)
    etol = ntol["endpoint_mm"]
    dtol = ntol["diameter_mm"]
    checks = []
    dia_checks = []
    # Степень узла решает, какой у конца допуск: стыкованный конец законно
    # подрезан отводом, свободный — нет. Считается ОДИН раз по всем участкам,
    # а не по соседям в списке: ветка может прийти в узел откуда угодно.
    degrees: dict = {}
    for _var, _a, _b, _dia in seg_meta:
        degrees[_a] = degrees.get(_a, 0) + 1
        degrees[_b] = degrees.get(_b, 0) + 1
    for i, (var, a, b, diameter) in enumerate(seg_meta):
        pa, pb = graph["nodes"][a], graph["nodes"][b]
        p0 = f"P({round(pa[0], 2)}, {round(pa[1], 2)}, {round(pa[2], 2)})"

        def lit(value):
            # Parenthesize negatives so subtraction never produces `--`.
            return f"({round(value, 1)})"

        trim_a, trim_b = _segment_trim_bounds_mm(
            pa, pb, degree_a=degrees.get(a, 1), degree_b=degrees.get(b, 1),
            tol_mm=etol.value)
        length = math.dist(pa, pb)
        ux, uy, uz = ((pb[0] - pa[0]) / length,
                      (pb[1] - pa[1]) / length,
                      (pb[2] - pa[2]) / length)

        # Конец проверяется В ОСЯХ УЧАСТКА, а не коробкой вокруг узла:
        #   t — насколько ушёл ВДОЛЬ участка (внутрь положительно),
        #   d — насколько сошёл С ОСИ.
        # Подрезка меняет t и не трогает d, поэтому послабление даётся ровно
        # по одной степени свободы: сойти с оси или перелететь наружу
        # по-прежнему нельзя.
        checks.append(
            f"    {{ var __lc = {var}.Location as LocationCurve; if (__lc == null) "
            f"__post.Add({_cs(oid + f': segment {i} no curve (geometry)')});\n"
            f"      else {{ var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);\n"
            f"        bool __fwd = __a.DistanceTo({p0}) <= __b.DistanceTo({p0});\n"
            f"        var __e0 = __fwd ? __a : __b; var __e1 = __fwd ? __b : __a;\n"
            # ОДНО объявление на строку: страж области видимости эмиттера
            # разбирает только первый объявитель в `double a = .., b = ..`,
            # и остальные для него не существуют. Правило дешевле обойти
            # соблюдением, чем расширением разбора.
            f"        double __ux = {lit(ux)};\n"
            f"        double __uy = {lit(uy)};\n"
            f"        double __uz = {lit(uz)};\n"
            f"        double __r0x = MM(__e0.X)-{lit(pa[0])};\n"
            f"        double __r0y = MM(__e0.Y)-{lit(pa[1])};\n"
            f"        double __r0z = MM(__e0.Z)-{lit(pa[2])};\n"
            f"        double __t0 = __r0x*__ux + __r0y*__uy + __r0z*__uz;\n"
            f"        double __d0 = Math.Sqrt(Math.Max(0.0, __r0x*__r0x + __r0y*__r0y + __r0z*__r0z - __t0*__t0));\n"
            f"        double __r1x = MM(__e1.X)-{lit(pb[0])};\n"
            f"        double __r1y = MM(__e1.Y)-{lit(pb[1])};\n"
            f"        double __r1z = MM(__e1.Z)-{lit(pb[2])};\n"
            f"        double __t1 = -(__r1x*__ux + __r1y*__uy + __r1z*__uz);\n"
            f"        double __d1 = Math.Sqrt(Math.Max(0.0, __r1x*__r1x + __r1y*__r1y + __r1z*__r1z - __t1*__t1));\n"
            f"        if (__d0 > {etol:g} || __t0 < -{etol:g} || __t0 > {lit(trim_a)} ||\n"
            f"            __d1 > {etol:g} || __t1 < -{etol:g} || __t1 > {lit(trim_b)})\n"
            f"          __post.Add({_cs(oid + f': segment {i} endpoints (geometry)')}); }} }}")
        if diameter is not None:
            if op_name == "route_duct_system":
                # У Duct отсутствие diameter — не числовое расхождение:
                # выбранное сечение не круглое.  Разделяем причины так же,
                # как одиночный create_duct, не меняя сам отказ или допуск.
                dia_checks.append(
                    f"    {{ try {{ var __dp = {var}.get_Parameter(BuiltInParameter.{diameter_bip});\n"
                    f"        if (__dp == null)\n"
                    f"          __post.Add({_cs(oid + f': segment {i} diameter mismatch — у элемента нет параметра диаметра: сечение не круглое, а диаметр применим только к круглому (semantic)')});\n"
                    f"        else if (Math.Abs(MM(__dp.AsDouble())-{lit(diameter)})>{dtol:g})\n"
                    f"          __post.Add({_cs(oid + f': segment {i} diameter (semantic)')}); }}\n"
                    f"      catch {{ __post.Add({_cs(oid + f': segment {i} diameter unreadable (semantic)')}); }} }}")
            else:
                dia_checks.append(
                    f"    {{ try {{ var __dp = {var}.get_Parameter(BuiltInParameter.{diameter_bip});\n"
                    f"        if (__dp == null || Math.Abs(MM(__dp.AsDouble())-{lit(diameter)})>{dtol:g})\n"
                    f"          __post.Add({_cs(oid + f': segment {i} diameter (semantic)')}); }}\n"
                    f"      catch {{ __post.Add({_cs(oid + f': segment {i} diameter unreadable (semantic)')}); }} }}")

    # Возвращаются и САМИ допуски: витнес обязан объявить ТОТ объект,
    # который отрендерил число в его C# (закон 2, emit_model.py).
    return "\n".join(checks), "\n".join(dia_checks), etol, dtol


def _network_level_post(seg_meta: list, oid: str, lv_idexpr: str) -> str:
    """Per-segment reference-level readback for the CONNECT emitters.

    ЧТО ЗДЕСЬ АВТОРСКОЕ.  ``level`` у сетевых опов — обязательный параметр, и
    эмиттер САМ передаёт его четвёртым аргументом в ``Pipe.Create`` /
    ``Duct.Create``.  Значит это ровно тот случай, который правило «кто
    присваивает значение в построенном элементе» называет честным для
    свидетеля: обещание наше, и держим его мы, а не Revit (ср. `height_mm`
    стены под верхней привязкой — там значение выбирает Revit, и спрашивать
    его с элемента нельзя).

    ПОЧЕМУ ЭТО НЕ ВЫДУМАННЫЙ ДОПУСК.  Проверка ТОЧНАЯ: сверяется ElementId
    уровня, число здесь не участвует вовсе, поэтому ей нечего изобретать.
    Механизм не новый: `create_pipe` и `create_duct` читают ТОТ ЖЕ
    ``RBS_START_LEVEL_PARAM`` тем же способом с 21.07, и НИ ОДНОГО нарушения
    «level binding» за ними в корпусе нет — все 35 таких нарушений
    принадлежат `create_beam` (29) и `create_floor` (5), то есть опам, где
    уровень Revit ВЫВОДИТ, а не получает. Перенос допуска здесь не нужен, а
    перенос МЕХАНИЗМА измерен.

    🔴 СЧЁТ ПОСТРОЕК ИЗ ЭТОГО АБЗАЦА ОТОЗВАН 17.08.2026, ВЫВОД — НЕТ. Здесь
    стояло «3434 и 215 построек при НУЛЕ обвинений» по корпусу в 1306
    записей. Числа были артефактом непочиненного `tally()`, не смотревшего на
    признак усечения (см. `kir/CLAUDE.md`, отзыв таблицы «четыре опа выше
    95 %»). Сегодня по корпусу в 2172 записи те же опы читаются как
    `create_pipe` 377/1 и `create_duct` 43/7 — то есть «ноль обвинений» тоже
    неверно. **Уцелело ровно то, на чём стоит абзац**, и оно перепроверено в
    тот же день: нарушений «level binding» 35, приписаны `create_beam` 29 и
    `create_floor` 5, за сетевыми опами — ноль. Счёт построек к этому
    утверждению отношения не имел никогда.

    ЗАЧЕМ ВООБЩЕ.  `acceptance._LEVEL_FROM_PARAM` уже числит все три сетевых
    опа среди тех, у кого «уровень результата РАВЕН разрешённому селектору», и
    строит на этом послекоммитную перепись category x level.  До сих пор это
    утверждение нигде не проверялось: судья на нём стоял, а свидетель его не
    читал.

    Ось подписи — ``(topology)``: читается ссылка на элемент, а не координата
    (§18.3, `tests/test_witness_axis_honesty.py`).
    """
    lines = []
    for i, (var, _a, _b, _dia) in enumerate(seg_meta):
        # Своя пара скобок на участок: имя `__lvp` иначе переобъявляется во
        # втором сегменте — та же дисциплина, что у `__lc` выше.
        lines.append(
            f"    {{ var __lvp = {var}.get_Parameter(BuiltInParameter.RBS_START_LEVEL_PARAM);\n"
            f"      if (__lvp == null || __lvp.AsElementId() == null\n"
            f"          || __lvp.AsElementId().ToString() != {lv_idexpr})\n"
            f"        __post.Add({_cs(oid + f': segment {i} level binding (topology)')}); }}")
    return "\n".join(lines)


def _hoist_segments(seg_lines: str, seg_meta: list, seg_var: str) -> tuple[str, str]:
    """(decl lines, create lines) with the per-segment declarations hoisted.

    connect/route_mep emit ``var __seg_<s>_<i> = <Create>(...);`` inside the
    create block, but _network_post_checks and the connectivity witness read
    those vars from the post block — the emitter scope contract requires them
    in decl (per_op wraps create in its own try scope). Pipe and Duct both sit
    under MEPCurve, the narrowest type every consumer (MEPCurve[] system
    merge, Element[] witness, Location/get_Parameter) needs."""
    decls = "\n".join(f"MEPCurve {var} = null;" for var, _a, _b, _d in seg_meta)
    return decls, seg_lines.replace(f"var {seg_var}_", f"{seg_var}_")


def _emit_pipe_system(op: dict, ver: str, stamp: str,
                      isolation: str = "atomic") -> tuple[str, str, str, str]:
    from kir import connect as CN
    oid = op["id"]
    sfx = _safe(oid)
    graph = op["__graph__"]
    st = _gid(op, "system_type")
    pt = _gid(op, "pipe_type")
    lv_res, lv_idexpr = _level_expr(op, sfx, ver, oid, isolation)
    sys_id = _eid(st["id"], ver, oid)
    type_id = _eid(pt["id"], ver, oid)

    def create_call(sysv, typev, lvlv, p0cs, p1cs):
        return (f"Autodesk.Revit.DB.Plumbing.Pipe.Create(doc, {sysv}, {typev}, "
                f"{lvlv}, {p0cs}, {p1cs})")

    def cs_pt(xyz):
        return f"P({round(xyz[0], 2)}, {round(xyz[1], 2)}, {round(xyz[2], 2)})"

    seg_var = f"__seg_{sfx}"
    seg_lines, seg_meta = CN.emit_segments_cs(
        graph, seg_var, create_call, sys_id, type_id, f"__lv_{sfx}.Id", cs_pt, _cs,
        isolation)
    seg_decls, seg_lines = _hoist_segments(seg_lines, seg_meta, seg_var)
    sys_readback = CN.emit_system_readback_cs(seg_meta, oid, _cs, "__results")
    fittings = CN.emit_fittings_cs(graph, seg_meta, oid, cs_pt, _cs, isolation)
    witness = CN.emit_connectivity_witness_cs(seg_meta, oid, _cs)
    stamps = "\n".join(_stamp_block(v, f"{stamp}:{oid}:{i}")
                        for i, (v, a, b, d) in enumerate(seg_meta))

    decl = (f"Element __sysprobe_{sfx} = null;\n"
            f"var __segids_{sfx} = new List<string>();\n" + seg_decls)
    create = (
        f"// create_pipe_system {cs_line_comment_fragment(oid)} — graph: {len(graph['nodes'])} nodes, {len(seg_meta)} segments\n"
        f"{lv_res}\n{seg_lines}\n"
        f"doc.Regenerate();  // connectors materialize after regen (CONNECT emit order)\n"
        f"{fittings}\n{stamps}\n"
        + "".join(f"__segids_{sfx}.Add({v}.Id.ToString());\n" for v, a, b, d in seg_meta)
        + f"__sysprobe_{sfx} = {seg_meta[0][0]};")

    seg_part, dia_part, etol, dtol = _network_geometry_post(
        graph, seg_meta, oid, "RBS_PIPE_DIAMETER_PARAM", op["op"])
    post = BarePost(tuple(check for check in (
        WitnessCheck(
            obligation_key="endpoints", reader_cs="",
            verdict_cs=seg_part + "\n",
            message="segment endpoints (geometry)",
            tol=etol, style="else_block"),
        # Диаметр — СВОЙ ключ и свой вердикт. Обязательство, разряжаемое
        # чужим ключом, неотличимо от отсутствующего.
        (WitnessCheck(
            obligation_key="diameter", reader_cs="",
            verdict_cs=dia_part + "\n",
            message="segment diameter (semantic)",
            tol=dtol, style="else_block") if dia_part else None),
        WitnessCheck(
            obligation_key="connectivity", reader_cs="",
            verdict_cs=witness,
            message="network not fully connected (topology)",
            style="guard"),
    ) if check is not None))
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"segments\"] = {len(seg_meta)};\n"
        f"    __rb[\"segment_ids\"] = __segids_{sfx}.ToArray();\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}\n"
        f"{sys_readback}")
    return decl, create, post, readback


# ── wave/mep (2026-07-17): route_pipe_system / route_duct_system ────────────
# Tile the create_pipe_system graph pattern onto the full ВК/ОВ family. Shared
# graph logic (connectivity, degree-cap, fitting-by-degree, live topology
# witness) comes from connect.py UNCHANGED, exactly as create_pipe_system uses
# it. Domain deltas (Create() call name, diameter BIP) come from route_mep.py
# for the duct case, since connect.emit_segments_cs hardcodes the pipe BIP.
# Both add the checked (not generative) slope postcondition — see
# ops_connect.py's module docstring for why slope is a witness, not a param
# that derives node Z.

def _emit_route_pipe_system(op: dict, ver: str, stamp: str,
                            isolation: str = "atomic") -> tuple[str, str, str, str]:
    """route_pipe_system — ВК network graph. Segment creation/diameter BIP
    are IDENTICAL to create_pipe_system's (Plumbing.Pipe.Create,
    RBS_PIPE_DIAMETER_PARAM), so this reuses CN.emit_segments_cs unchanged;
    the only addition over _emit_pipe_system is the slope witness."""
    from kir import connect as CN
    from kir import route_mep as RM
    oid = op["id"]
    sfx = _safe(oid)
    graph = op["__graph__"]
    slope_reqs = op.get("__slope_reqs__") or {}
    st = _gid(op, "system_type")
    pt = _gid(op, "pipe_type")
    lv_res, lv_idexpr = _level_expr(op, sfx, ver, oid, isolation)
    sys_id = _eid(st["id"], ver, oid)
    type_id = _eid(pt["id"], ver, oid)

    def create_call(sysv, typev, lvlv, p0cs, p1cs):
        return (f"Autodesk.Revit.DB.Plumbing.Pipe.Create(doc, {sysv}, {typev}, "
                f"{lvlv}, {p0cs}, {p1cs})")

    def cs_pt(xyz):
        return f"P({round(xyz[0], 2)}, {round(xyz[1], 2)}, {round(xyz[2], 2)})"

    seg_var = f"__seg_{sfx}"
    seg_lines, seg_meta = CN.emit_segments_cs(
        graph, seg_var, create_call, sys_id, type_id, f"__lv_{sfx}.Id", cs_pt, _cs,
        isolation)
    seg_decls, seg_lines = _hoist_segments(seg_lines, seg_meta, seg_var)
    sys_readback = CN.emit_system_readback_cs(seg_meta, oid, _cs, "__results")
    fittings = CN.emit_fittings_cs(graph, seg_meta, oid, cs_pt, _cs, isolation)
    witness = CN.emit_connectivity_witness_cs(seg_meta, oid, _cs)
    slope_witness = RM.emit_slope_witness_cs(seg_meta, slope_reqs, oid, _cs)
    stamps = "\n".join(_stamp_block(v, f"{stamp}:{oid}:{i}")
                        for i, (v, a, b, d) in enumerate(seg_meta))

    decl = (f"Element __sysprobe_{sfx} = null;\n"
            f"var __segids_{sfx} = new List<string>();\n" + seg_decls)
    create = (
        f"// route_pipe_system {cs_line_comment_fragment(oid)} — graph: {len(graph['nodes'])} nodes, {len(seg_meta)} segments\n"
        f"{lv_res}\n{seg_lines}\n"
        f"doc.Regenerate();  // connectors materialize after regen (CONNECT emit order)\n"
        f"{fittings}\n{stamps}\n"
        + "".join(f"__segids_{sfx}.Add({v}.Id.ToString());\n" for v, a, b, d in seg_meta)
        + f"__sysprobe_{sfx} = {seg_meta[0][0]};")

    seg_part, dia_part, etol, dtol = _network_geometry_post(
        graph, seg_meta, oid, "RBS_PIPE_DIAMETER_PARAM", op["op"])
    checks = [
        WitnessCheck(
            obligation_key="endpoints", reader_cs="",
            verdict_cs=seg_part + "\n",
            message="segment endpoints (geometry)",
            tol=etol, style="else_block"),
        WitnessCheck(
            obligation_key="connectivity", reader_cs="",
            verdict_cs=witness,
            message="network not fully connected (topology)",
            style="guard"),
        # Уровень стоит СРАЗУ ЗА связностью: обе проверки топологические, и
        # общий с create_pipe_system префикс (концы / диаметр / связность)
        # остаётся на месте — диффы трёх сетевых золотых по-прежнему
        # читаются рядом.
        WitnessCheck(
            obligation_key="reference_level", reader_cs="",
            verdict_cs="\n" + _network_level_post(seg_meta, oid, lv_idexpr) + "\n",
            message="segment level binding (topology)",
            style="guard"),
    ]
    if slope_witness:
        checks.append(WitnessCheck(
            obligation_key="slope", reader_cs="",
            verdict_cs="\n" + slope_witness,
            message="slope below required (KIR-L004)",
            style="guard"))
    # Диаметр — свой ключ: обязательство, разряжаемое ЧУЖИМ ключом,
    # неотличимо от отсутствующего (см. _network_geometry_post).
    #
    # Вставка СРАЗУ ЗА концами, а не в хвост: у трёх сетевых опов порядок
    # свидетелей обязан совпадать, иначе диффы их золотых файлов перестают
    # читаться рядом, а именно ради этого они и лежат рядом.
    if dia_part:
        checks.insert(1, WitnessCheck(
            obligation_key="diameter", reader_cs="",
            verdict_cs=dia_part + "\n",
            message="segment diameter (semantic)",
            tol=dtol, style="else_block"))
    post = BarePost(tuple(checks))
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"segments\"] = {len(seg_meta)};\n"
        f"    __rb[\"segment_ids\"] = __segids_{sfx}.ToArray();\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}\n"
        f"{sys_readback}")
    return decl, create, post, readback


def _emit_route_duct_system(op: dict, ver: str, stamp: str,
                            isolation: str = "atomic") -> tuple[str, str, str, str]:
    """route_duct_system — ОВ network graph. Mirrors _emit_route_pipe_system
    over Duct.Create + RBS_CURVE_DIAMETER_PARAM (route_mep.py's
    emit_segments_route_cs, NOT connect.emit_segments_cs — that one hardcodes
    the pipe-only diameter BIP, see route_mep.py docstring)."""
    from kir import connect as CN
    from kir import route_mep as RM
    oid = op["id"]
    sfx = _safe(oid)
    graph = op["__graph__"]
    slope_reqs = op.get("__slope_reqs__") or {}
    st = _gid(op, "system_type")
    dt = _gid(op, "duct_type")
    lv_res, lv_idexpr = _level_expr(op, sfx, ver, oid, isolation)
    sys_id = _eid(st["id"], ver, oid)
    type_id = _eid(dt["id"], ver, oid)

    def create_call(sysv, typev, lvlv, p0cs, p1cs):
        return (f"Autodesk.Revit.DB.Mechanical.Duct.Create(doc, {sysv}, {typev}, "
                f"{lvlv}, {p0cs}, {p1cs})")

    def cs_pt(xyz):
        return f"P({round(xyz[0], 2)}, {round(xyz[1], 2)}, {round(xyz[2], 2)})"

    seg_var = f"__seg_{sfx}"
    seg_lines, seg_meta = RM.emit_segments_route_cs(
        graph, seg_var, create_call, sys_id, type_id, f"__lv_{sfx}.Id", cs_pt, _cs,
        diameter_bip="RBS_CURVE_DIAMETER_PARAM", isolation=isolation)
    seg_decls, seg_lines = _hoist_segments(seg_lines, seg_meta, seg_var)
    sys_readback = CN.emit_system_readback_cs(seg_meta, oid, _cs, "__results")
    fittings = CN.emit_fittings_cs(graph, seg_meta, oid, cs_pt, _cs, isolation)
    witness = CN.emit_connectivity_witness_cs(seg_meta, oid, _cs)
    slope_witness = RM.emit_slope_witness_cs(seg_meta, slope_reqs, oid, _cs)
    stamps = "\n".join(_stamp_block(v, f"{stamp}:{oid}:{i}")
                        for i, (v, a, b, d) in enumerate(seg_meta))

    decl = (f"Element __sysprobe_{sfx} = null;\n"
            f"var __segids_{sfx} = new List<string>();\n" + seg_decls)
    create = (
        f"// route_duct_system {cs_line_comment_fragment(oid)} — graph: {len(graph['nodes'])} nodes, {len(seg_meta)} segments\n"
        f"{lv_res}\n{seg_lines}\n"
        f"doc.Regenerate();  // connectors materialize after regen (CONNECT emit order)\n"
        f"{fittings}\n{stamps}\n"
        + "".join(f"__segids_{sfx}.Add({v}.Id.ToString());\n" for v, a, b, d in seg_meta)
        + f"__sysprobe_{sfx} = {seg_meta[0][0]};")

    seg_part, dia_part, etol, dtol = _network_geometry_post(
        graph, seg_meta, oid, "RBS_CURVE_DIAMETER_PARAM", op["op"])
    checks = [
        WitnessCheck(
            obligation_key="endpoints", reader_cs="",
            verdict_cs=seg_part + "\n",
            message="segment endpoints (geometry)",
            tol=etol, style="else_block"),
        WitnessCheck(
            obligation_key="connectivity", reader_cs="",
            verdict_cs=witness,
            message="network not fully connected (topology)",
            style="guard"),
        # Порядок — как у route_pipe_system (см. там же).
        WitnessCheck(
            obligation_key="reference_level", reader_cs="",
            verdict_cs="\n" + _network_level_post(seg_meta, oid, lv_idexpr) + "\n",
            message="segment level binding (topology)",
            style="guard"),
    ]
    if slope_witness:
        checks.append(WitnessCheck(
            obligation_key="slope", reader_cs="",
            verdict_cs="\n" + slope_witness,
            message="slope below required (KIR-L004)",
            style="guard"))
    # Диаметр — свой ключ: обязательство, разряжаемое ЧУЖИМ ключом,
    # неотличимо от отсутствующего (см. _network_geometry_post).
    #
    # Вставка СРАЗУ ЗА концами, а не в хвост: у трёх сетевых опов порядок
    # свидетелей обязан совпадать, иначе диффы их золотых файлов перестают
    # читаться рядом, а именно ради этого они и лежат рядом.
    if dia_part:
        checks.insert(1, WitnessCheck(
            obligation_key="diameter", reader_cs="",
            verdict_cs=dia_part + "\n",
            message="segment diameter (semantic)",
            tol=dtol, style="else_block"))
    post = BarePost(tuple(checks))
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"segments\"] = {len(seg_meta)};\n"
        f"    __rb[\"segment_ids\"] = __segids_{sfx}.ToArray();\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}\n"
        f"{sys_readback}")
    return decl, create, post, readback


def _stamp_type_block(type_var: str, stamp: str, *, required: bool = False) -> str:
    """Type-level analogue of _stamp_block: types have no instance-comments
    parameter, so the idempotency/audit stamp goes on ALL_MODEL_TYPE_COMMENTS
    (verified present in RevitAPI.xml 2021-2026, same enum as the instance one)."""
    if not required and not stamp.startswith("kir:a5:"):
        return (f'try {{ Parameter __cmt = {type_var}.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS); '
                f'if (__cmt != null && !__cmt.IsReadOnly) __cmt.Set({_cs(stamp)}); }} catch {{ }}')
    label = "A5" if stamp.startswith("kir:a5:") else "Type ownership"
    return (
        f'try {{ Parameter __cmt = {type_var}.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS); '
        f'if (__cmt == null) throw new InvalidOperationException("{label} stamp parameter missing"); '
        f'if (__cmt.IsReadOnly) throw new InvalidOperationException("{label} stamp parameter is read-only"); '
        f'if (!__cmt.Set({_cs(stamp)}) || __cmt.AsString() != {_cs(stamp)}) '
        f'throw new InvalidOperationException("{label} stamp readback mismatch"); }} '
        f'catch (Exception __stampEx) {{ throw new InvalidOperationException('
        f'"{label} stamp write failed: " + __stampEx.Message, __stampEx); }}')


def _type_owner_guard(type_var: str, stamp: str, oid: str, isolation: str) -> str:
    """Exact creation marker, not a global KIR prefix or authentication proof.

    Reuse is read-only; unchanged requested values are checked by the existing
    postconditions. A different request needs explicit binding/new naming, not
    mutation of a shared model type through a create operation.
    """
    s = _safe(oid)
    return (
        f"string __owner_{s} = null;\n"
        f"try {{ var __ownerParam_{s} = {type_var}.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS);\n"
        f"    if (__ownerParam_{s} != null) __owner_{s} = __ownerParam_{s}.AsString(); }} catch {{ }}\n"
        f"if (!String.Equals(__owner_{s}, {_cs(stamp + ':' + oid)}, StringComparison.Ordinal)) {{ "
        f"{refuse_stmt(oid, _cs('одноимённый тип не принадлежит этому точному запросу; создание не изменяет существующие типы'), isolation)} }}\n")


def _type_length_guard(param_var: str, label: str, ver: str,
                       oid: str, isolation: str) -> str:
    """An arbitrary named Double parameter is not necessarily a length.

    Check the observed definition before converting mm, including read-only
    reuse. Definition.GetDataType replaces GetSpecTypeId starting in 2022.
    """
    suffix = _safe(oid) + "_" + label
    getter = "GetSpecTypeId" if str(ver) == "2021" else "GetDataType"
    return (
        f"bool __length_{suffix} = false;\n"
        f"try {{ if ({param_var} != null && {param_var}.StorageType == StorageType.Double) {{\n"
        f"    var __definition_{suffix} = {param_var}.Definition;\n"
        f"    var __spec_{suffix} = __definition_{suffix} == null ? null : __definition_{suffix}.{getter}();\n"
        f"    __length_{suffix} = __spec_{suffix} != null && __spec_{suffix}.Equals(SpecTypeId.Length);\n"
        f"}} }} catch {{ }}\n"
        f"if (!__length_{suffix}) {{ {refuse_stmt(oid, _cs(label + ': параметр должен иметь StorageType.Double и размерность Length; mm нельзя записывать или проверять как другую величину'), isolation)} }}\n")


def _emit_create_type(op: dict, ver: str, stamp: str,
                      isolation: str = "atomic") -> tuple[str, str, str, str]:
    """Duplicate a FamilySymbol (columns/beams — symbol-based types ONLY;
    wall/floor/roof CompoundStructure types are explicitly out of scope, see
    ops_families.py docstring) and set dimension/material params BY NAME —
    never a guessed BuiltInParameter (RevitAPI.xml has no universal
    COLUMN_WIDTH/DEPTH; see the module docstring for the audit trail).

    Idempotent re-run (family-geometry-authoring.md DuplicateTypeWithSize
    lesson): ElementType.Duplicate(name) THROWS ArgumentException on a name
    already used by a sibling type of the SAME Family — search for that type
    first. Only one exact-marker match can be reused, read-only; existing drift
    fails the original postconditions instead of being repaired by create."""
    oid = op["id"]
    s = _safe(oid)
    g_src = _gid(op, "source_type")
    new_name = op["new_name"]
    width = op["width_mm"]
    depth = op.get("depth_mm")
    pw_name = op.get("param_width_name", "b")
    pd_name = op.get("param_depth_name", "h")
    material = op.get("material")
    # __pw_/__pd_/__mat_ are re-read by the post re-read checks — declared
    # here, assigned in create (emitter scope contract, per_op-safe).
    decl = (f"FamilySymbol __el_{s} = null; bool __dupd_{s} = false;\n"
            f"Parameter __pw_{s} = null;")
    if depth is not None:
        decl += f"\nParameter __pd_{s} = null;"
    if material is not None:
        decl += f"\nMaterial __mat_{s} = null;"
    src_res = (f"FamilySymbol __src_{s} = doc.GetElement({_eid(g_src['id'], ver, oid)}) as FamilySymbol;\n"
               f"if (__src_{s} == null) {{ {refuse_stmt(oid, _cs('source_type не найден (модель изменилась после grounding)'), isolation)} }}")
    dup_logic = (
        f"var __twins_{s} = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>()\n"
        f"    .Where(__c => __c.Family.Id == __src_{s}.Family.Id && __c.Name == {_cs(new_name)}).ToList();\n"
        f"if (__twins_{s}.Count > 1) {{ {refuse_stmt(oid, _cs('одноимённый тип неоднозначен; создание не выбирает первый'), isolation)} }}\n"
        f"FamilySymbol __twin_{s} = __twins_{s}.Count == 1 ? __twins_{s}[0] : null;\n"
        f"if (__twin_{s} != null) {{\n{_type_owner_guard(f'__twin_{s}', stamp, oid, isolation)}__el_{s} = __twin_{s}; }}\n"
        f"else\n"
        f"{{\n"
        f"    try {{ __el_{s} = __src_{s}.Duplicate({_cs(new_name)}) as FamilySymbol; __dupd_{s} = true; }}\n"
        f"    catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"Duplicate: \" + __ex_{s}.Message', isolation)} }}\n"
        f"}}\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('Duplicate вернул null'), isolation)} }}\n"
        f"if (__dupd_{s} && !__el_{s}.IsActive) {{ __el_{s}.Activate(); doc.Regenerate(); }}")
    width_set = (
        f"var __pws_{s} = __el_{s}.GetParameters({_cs(pw_name)});\n"
        f"if (__pws_{s} == null || __pws_{s}.Count != 1) {{ {refuse_stmt(oid, _cs('параметр «' + pw_name + '» (width) не найден или неоднозначен на этом шаблоне семейства'), isolation)} }}\n"
        f"__pw_{s} = __pws_{s}[0];\n"
        f"{_type_length_guard(f'__pw_{s}', 'width', ver, oid, isolation)}"
        f"if (__dupd_{s}) {{\n"
        f"if (__pw_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('параметр «' + pw_name + '» (width) read-only на этом шаблоне семейства'), isolation)} }}\n"
        f"__pw_{s}.Set(U({width}));\n}}")
    depth_set = ""
    if depth is not None:
        depth_set = (
            f"\nvar __pds_{s} = __el_{s}.GetParameters({_cs(pd_name)});\n"
            f"if (__pds_{s} == null || __pds_{s}.Count != 1) {{ {refuse_stmt(oid, _cs('параметр «' + pd_name + '» (depth) не найден или неоднозначен на этом шаблоне семейства'), isolation)} }}\n"
            f"__pd_{s} = __pds_{s}[0];\n"
            f"{_type_length_guard(f'__pd_{s}', 'depth', ver, oid, isolation)}"
            f"if (__dupd_{s}) {{\n"
            f"if (__pd_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('параметр «' + pd_name + '» (depth) read-only на этом шаблоне семейства'), isolation)} }}\n"
            f"__pd_{s}.Set(U({depth}));\n}}")
    mat_set = ""
    if material is not None:
        mat_set = (
            f"\nvar __materials_{s} = new FilteredElementCollector(doc).OfClass(typeof(Material)).Cast<Material>()\n"
            f"    .Where(__m => __m.Name == {_cs(material)}).ToList();\n"
            f"if (__materials_{s}.Count != 1) {{ {refuse_stmt(oid, _cs('материал «' + material + '» отсутствует или неоднозначен в документе'), isolation)} }}\n"
            f"__mat_{s} = __materials_{s}[0];\n"
            f"Parameter __pm_{s} = __el_{s}.get_Parameter(BuiltInParameter.STRUCTURAL_MATERIAL_PARAM);\n"
            f"if (__dupd_{s}) {{\n"
            f"if (__pm_{s} == null || __pm_{s}.IsReadOnly) {{ {refuse_stmt(oid, _cs('параметр материала (STRUCTURAL_MATERIAL_PARAM) недоступен на этом шаблоне семейства — материал не может быть применён'), isolation)} }}\n"
            f"__pm_{s}.Set(__mat_{s}.Id);\n}}")
    create = (f"// create_type {cs_line_comment_fragment(oid)}\n{src_res}\n{dup_logic}\n{width_set}{depth_set}{mat_set}\n"
              + f"if (__dupd_{s}) {{ " + _stamp_type_block(f"__el_{s}", f"{stamp}:{oid}", required=True) + " }")
    # Допуск ре-чтения — из реестра, а не литералом: WitnessCheck ниже заявляет
    # tol_key="param_mm", и это заявление должно быть правдой.
    ptol = tolerance("create_type", "param_mm")
    depth_check = ""
    if depth is not None:
        depth_check = (
            f"\n    {{ if (__pd_{s} == null || Math.Abs(MM(__pd_{s}.AsDouble()) - {depth}) > {ptol})\n"
            f"          __post.Add({_cs(oid + ': depth не удержалась (re-read)')}); }}")
    mat_check = ""
    if material is not None:
        mat_check = (
            f"\n    {{ var __pm2 = __el_{s}.get_Parameter(BuiltInParameter.STRUCTURAL_MATERIAL_PARAM);\n"
            f"      if (__pm2 == null || __pm2.AsElementId() == null || "
            f"__pm2.AsElementId().ToString() != __mat_{s}.Id.ToString())\n"
            f"          __post.Add({_cs(oid + ': материал не удержался (re-read)')}); }}")
    # A2 glue: width verdict has no own newline when depth/mat follow (their
    # fragments start with one); the last fragment carries the final "\n".
    checks: list[WitnessCheck] = [WitnessCheck(
        obligation_key="width", reader_cs="",
        verdict_cs=(
            f"    if (__pw_{s} == null || Math.Abs(MM(__pw_{s}.AsDouble()) - {width}) > {ptol})\n"
            f"        __post.Add({_cs(oid + ': width не удержалась (re-read)')});"
            + ("" if (depth_check or mat_check) else "\n")),
        message="width не удержалась (re-read)",
        tol=ptol, style="guard")]
    if depth_check:
        checks.append(WitnessCheck(
            obligation_key="depth", reader_cs="",
            verdict_cs=depth_check + ("" if mat_check else "\n"),
            message="depth не удержалась (re-read)",
            tol=ptol, style="guard"))
    if mat_check:
        checks.append(WitnessCheck(
            obligation_key="material", reader_cs="",
            verdict_cs=mat_check + "\n",
            message="материал не удержался (re-read)", style="guard"))
    post = checks
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"name\"] = __el_{s}.Name;\n"
        f"    __rb[\"duplicated\"] = __dupd_{s};\n"
        + _stamp_readback(f"__el_{s}", type_level=True) +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_create_wall_type(op: dict, ver: str, stamp: str,
                           isolation: str = "atomic") -> tuple[str, str, str, str]:
    """`WallType.Duplicate` + `CreateSimpleCompoundStructure` + `SetCompoundStructure`.

    🔴 ЧТО ПЕРЕЖИВАЕТ ИСТОЧНИК, А ЧТО НЕТ. `SetLayers` документирован как
    «Completely resets this CompoundStructure», поэтому здесь берётся не он, а
    фабрика `CreateSimpleCompoundStructure`: структура строится С НУЛЯ из
    запрошенных слоёв, и от источника не наследуется НИЧЕГО из пирога. От
    источника остаётся ровно то, что живёт ВНЕ `CompoundStructure`: род
    (`WallType.Kind`), параметры типа (функция стены, обёртка на торцах,
    графика) и принадлежность документу. Это и есть ответ на «что именно
    останется» — не «мало», а НАЗВАННОЕ.

    🔴 ПРЕДПОЛЁТНОЙ ПРОВЕРКИ НЕТ. `CompoundStructure.IsValid` не существует:
    компиляция против референс-сборок дала 0/6 на трёх сигнатурах и 0/6 на
    `IsValidLayerList` при честном контроле. Единственный судья — исключение
    от `SetCompoundStructure`, и оно ловится в типизированный отказ.

    🔴 СВИДЕТЕЛЬ ЧИТАЕТ МОДЕЛЬ, А НЕ ЭХО. Пирог перечитывается через
    `GetCompoundStructure().GetLayers()` у элемента, ВЗЯТОГО ПО СВОЕМУ Id.
    Цена доверия эху куплена в тот же день: `load_family` был зелёным, когда
    семейства приехали под именами `kir_f1`…`kir_f6`, потому что проверял
    ответ вызова, а не документ."""
    oid = op["id"]
    s = _safe(oid)
    g_src = _gid(op, "source_type")
    new_name = op["new_name"]
    layers = op["layers"]
    ltol = tolerance("create_wall_type", "layer_mm")
    # РОД ХОЗЯЙСКОГО ТИПА -> КЛАСС REVIT. Опущенный параметр = "wall", и вся
    # ветка стены обязана остаться ДОСЛОВНО прежней: у неё есть золотой
    # образец, и «улучшенная» буква сломала бы паритет эмиссии.
    host_kind = op.get("host_kind") or "wall"
    cls = spec.HOST_TYPE_CLASS[host_kind]
    is_wall = host_kind == "wall"

    decl = (f"{cls} __el_{s} = null; bool __dupd_{s} = false;\n"
            f"IList<CompoundStructureLayer> __lay_{s} = "
            f"new List<CompoundStructureLayer>();")

    # ПРЕДПОЛЁТ РАЗНЫЙ, И РАЗНЫЙ ПО ЗАМЕРУ, А НЕ ПО ОСТОРОЖНОСТИ. `Kind`
    # существует ТОЛЬКО у `WallType` (компиляция против настоящих сборок
    # 2021-2026: `WallType.Kind` 6/6, `FloorType.Kind` / `RoofType.Kind` /
    # `CeilingType.Kind` 0/6 при двух отрицательных контролях 0/6). Значит у
    # трёх остальных родов «род источника Basic» непроверяем ПО ПОСТРОЕНИЮ, и
    # писать туда тот же затвор было бы обещанием, которого класс не несёт.
    # Их предполёт — наличие пирога у источника: тип без `CompoundStructure`
    # не может быть образцом для типа С пирогом, и это факт о НЁМ, читаемый
    # до `Duplicate`, ровно как `Kind` у стены.
    preflight = (
        f"if (__src_{s}.Kind != WallKind.Basic) {{ {refuse_stmt(oid, f'\"source_type рода \" + __src_{s}.Kind.ToString() + \" — создать по нему обычный слоистый тип нельзя; нужен Basic\"', isolation)} }}"
        if is_wall else
        f"if (__src_{s}.GetCompoundStructure() == null) {{ {refuse_stmt(oid, _cs('у source_type нет CompoundStructure — по такому образцу слоистый тип не создаётся'), isolation)} }}")
    src_res = (
        f"{cls} __src_{s} = doc.GetElement({_eid(g_src['id'], ver, oid)}) as {cls};\n"
        f"if (__src_{s} == null) {{ {refuse_stmt(oid, _cs('source_type не найден или резолвится не в ' + cls + ' (модель изменилась после grounding)'), isolation)} }}\n"
        # Род источника — факт о НЁМ, и он решает раньше пирога: у витражной и
        # многослойной-по-высоте стены CompoundStructure устроен иначе, и
        # «похожий» тип здесь хуже отказа.
        + preflight)

    # Материалы: каждое ИМЯ разрешается коллектором. Ноль и больше одного —
    # РАЗНЫЕ отказы; «первый попавшийся» запрещён.
    mat_names = sorted({lr["material"] for lr in layers if lr.get("material")})
    mat_res = ""
    mat_var = {}
    for mi, mname in enumerate(mat_names):
        mv = f"__mat{mi}_{s}"
        mat_var[mname] = mv
        # Postconditions also run outside the per-op create block.
        decl += f"\nMaterial {mv} = null;"
        mat_res += (
            f"\nvar {mv}_all = new FilteredElementCollector(doc).OfClass(typeof(Material)).Cast<Material>()\n"
            f"    .Where(__m => __m.Name == {_cs(mname)}).ToList();\n"
            f"if ({mv}_all.Count == 0) {{ {refuse_stmt(oid, _cs('материал «' + mname + '» не найден в целевом документе — перенесите материалы прежде типа; подставлять другой запрещено'), isolation)} }}\n"
            f"if ({mv}_all.Count > 1) {{ {refuse_stmt(oid, _cs('имя материала «' + mname + '» неоднозначно в целевом документе (найдено больше одного) — адрес слоя не определён'), isolation)} }}\n"
            f"{mv} = {mv}_all[0];")

    build = ""
    for lr in layers:
        mv = mat_var.get(lr.get("material"))
        mid = f"{mv}.Id" if mv else "ElementId.InvalidElementId"
        build += (
            f"\n__lay_{s}.Add(new CompoundStructureLayer(U({lr['width_mm']}), "
            f"MaterialFunctionAssignment.{lr['function']}, {mid}));")

    # 🔴 ИМЯ ТИПА — НЕ ДОКУМЕНТ-ГЛОБАЛЬНАЯ ЛИЧНОСТЬ (24.08.2026).
    #
    # Здесь стоял предпоиск-на-повтор по ОДНОМУ имени в пределах класса, и
    # найденный тип БЕЗУСЛОВНО получал `SetCompoundStructure`. У соседей закон
    # уже стоял — `create_type` сверяет `Family.Id` источника, `load_family`
    # имя `.rfa`, — но сюда не доехал.
    #
    # И ЗДЕСЬ ОН НУЖНЕЕ, ЧЕМ У СОСЕДЕЙ. У `FamilySymbol` имя уникально внутри
    # СЕМЕЙСТВА, и `Duplicate` бросает только на своём. У системных типов
    # (`WallType`/`FloorType`/`RoofType`/`CeilingType`) имя уникально по ВСЕМУ
    # классу документа: одноимённый найдётся ВСЕГДА, включая набранный
    # оператором руками.
    #
    # ЦЕНА, ВОСПРОИЗВЕДЁННАЯ: имя «Кирпич 250» есть в пуле `wall_types` того
    # самого снимка заземления, который компилятор держит в руках, — программа
    # компилируется `ok=True` при нуле диагностик. Шесть свидетелей ниже
    # поймать это не могут ПО ПОСТРОЕНИЮ: перечитывают тип по СВОЕМУ Id и
    # сверяют с ЗАПРОШЕННЫМ, а после перезаписи всё сходится. Пирог меняется у
    # КАЖДОГО существующего элемента чужого типа. Молча. Необратимо.
    #
    # Ownership requires the exact request/operation marker, not merely kir:.
    # Even an exact reused type is read-only: create is not a shared-type
    # update or drift repair. Existing postconditions qualify its current data.
    #
    # 🔴 ВЫБРАН ОТКАЗ, А НЕ СУФФИКС, И ЭТО РЕШЕНИЕ, А НЕ ОЧЕВИДНОСТЬ.
    # Автоматический суффикс («Кирпич 250 (2)») тихо завёл бы ВТОРОЙ тип, и
    # автор не узнал бы, каким из двух стоят его стены — молчаливая подмена
    # вместо молчаливой порчи, то есть тот же род, только дешевле на вид.
    # Отказ называет положение и оставляет выбор автору. Если владелец решит
    # иначе, менять надо ЗДЕСЬ и назвать это решением так же явно.
    twin = (
        f"\nvar __twins_{s} = new FilteredElementCollector(doc).OfClass(typeof({cls})).Cast<{cls}>()\n"
        f"    .Where(__c => __c.Name == {_cs(new_name)}).ToList();\n"
        f"if (__twins_{s}.Count > 1) {{ {refuse_stmt(oid, _cs('одноимённый тип неоднозначен; создание не выбирает первый'), isolation)} }}\n"
        f"{cls} __twin_{s} = __twins_{s}.Count == 1 ? __twins_{s}[0] : null;\n"
        f"if (__twin_{s} != null) {{\n{_type_owner_guard(f'__twin_{s}', stamp, oid, isolation)}"
        # 🔴 D-1: АДРЕС СОВПАЛ — ЭТО ЕЩЁ НЕ ПРАВО ПЕРЕПИСАТЬ. Слово владельца:
        # «стабильный адрес сам по себе не даёт права переписывать
        # существующий тип». Со стабильным адресом (`lineage`) повторная
        # публикация ПОПАДАЕТ сюда штатно, а не отказывает на владении, — и
        # именно поэтому здесь нужен ВТОРОЙ вопрос: тот ли это состав.
        #
        # ПОЧЕМУ ЗДЕСЬ, А НЕ ТОЛЬКО В ФИНАЛЬНЫХ СВИДЕТЕЛЯХ (они остаются и НЕ
        # ослаблены). Финальный свидетель судит КОНЕЦ ПРОГРАММЫ — к тому часу
        # стены соседних опов уже построены НЕ ТЕМ типом, и отказ обходится в
        # откат всей программы. Этот отказ стоит НА ОПЕ, до единого
        # потребителя, и не пишет ничего: ветка повторного использования не
        # зовёт `SetCompoundStructure` вовсе. Тот же урок, что у C-1: стадия
        # решает, чем обходится правда.
        f"    var __reuseCs_{s} = __twin_{s}.GetCompoundStructure();\n"
        f"    var __reuseL_{s} = __reuseCs_{s} == null ? null : __reuseCs_{s}.GetLayers();\n"
        f"    bool __reuseSame_{s} = __reuseL_{s} != null && __reuseL_{s}.Count == __lay_{s}.Count;\n"
        f"    if (__reuseSame_{s}) {{\n"
        f"        for (int __ri_{s} = 0; __ri_{s} < __lay_{s}.Count; __ri_{s}++) {{\n"
        f"            if (Math.Abs(__reuseL_{s}[__ri_{s}].Width - __lay_{s}[__ri_{s}].Width) > U({ltol})\n"
        f"                || __reuseL_{s}[__ri_{s}].Function != __lay_{s}[__ri_{s}].Function\n"
        f"                || !__reuseL_{s}[__ri_{s}].MaterialId.Equals(__lay_{s}[__ri_{s}].MaterialId))\n"
        f"            {{ __reuseSame_{s} = false; break; }}\n"
        f"        }}\n"
        f"    }}\n"
        f"    if (!__reuseSame_{s}) {{ "
        + refuse_stmt(oid, _cs('тип с этим адресом уже существует с другим '
                               'составом; изменение существующего типа — '
                               'отдельная операция'), isolation)
        + f" }}\n"
        f"__el_{s} = __twin_{s}; }}\n"
        f"else\n"
        f"{{\n"
        f"    try {{ __el_{s} = __src_{s}.Duplicate({_cs(new_name)}) as {cls}; __dupd_{s} = true; }}\n"
        f"    catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"Duplicate: \" + __ex_{s}.Message', isolation)} }}\n"
        f"}}\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('Duplicate вернул null'), isolation)} }}")

    # 🔴 ТОРЕЦ ПИРОГА — ЗАМЕР ЖИВОГО РЕВИТА, 24.08.2026, А НЕ ТЕОРИЯ.
    # `CreateSimpleCompoundStructure` собирает структуру со СТЕНОВЫМ условием
    # торца, и `FloorType.SetCompoundStructure` отвергает её дословно:
    # «Input compound structure has wrong EndCap condition for this element
    # type. Parameter name: srcStructure». Компиляция об этом молчала — 6/6 на
    # всех шести версиях, — то есть это ровно тот разрыв между «компилируется»
    # и «исполняется», который у нас уже назван.
    #
    # ЗНАЧЕНИЕ НЕ ВЫБРАНО НАМИ, А ВЗЯТО У ИСТОЧНИКА: `EndCapCondition` имеет
    # четыре члена (все 6/6), и написать здесь литерал значило бы объявить
    # своё знание о том, какой торец законен у каждого рода. Источник — тип
    # ТОГО ЖЕ рода, чей пирог Ревит уже принял; его условие законно ПО
    # ПОСТРОЕНИЮ. Наличие `GetCompoundStructure()` у источника гарантирует
    # предполёт выше, поэтому второго затвора здесь нет.
    endcap = ("" if is_wall else
              f"    __cs_{s}.EndCap = __src_{s}.GetCompoundStructure().EndCap;\n")
    apply = (
        f"\nif (__dupd_{s}) {{\ntry\n"
        f"{{\n"
        f"    CompoundStructure __cs_{s} = CompoundStructure.CreateSimpleCompoundStructure(__lay_{s});\n"
        f"{endcap}"
        f"    __el_{s}.SetCompoundStructure(__cs_{s});\n"
        f"}}\n"
        f"catch (Exception __exc_{s}) {{ {refuse_stmt(oid, f'\"пирог отвергнут Ревитом: \" + __exc_{s}.Message', isolation)} }}\n"
        f"doc.Regenerate();\n}}")

    create = (f"// create_wall_type {cs_line_comment_fragment(oid)}\n"
              f"{src_res}{mat_res}{build}{twin}{apply}\n"
              + f"if (__dupd_{s}) {{ " + _stamp_type_block(f"__el_{s}", f"{stamp}:{oid}", required=True) + " }")

    # ── свидетель: перечитать ПИРОГ из модели по своему Id
    #
    # 🔴 ШЕСТЬ ПРОВЕРОК, А НЕ ОДНА, И ЭТО НЕ КОСМЕТИКА (23.08.2026).
    # Сперва здесь стоял ОДИН `WitnessCheck` с ключом `compound_structure`, а
    # таблица сертификата обещала ПЯТЬ обязательств поимённо. Сертификат
    # разряжает обязательство ПО КЛЮЧУ — «`WitnessCheck` неконструируем без
    # своего `__post.Add`, поэтому наличие ключа И ЕСТЬ наличие приговора», —
    # и пять ключей из пяти не находились. `create_wall_type` был UNPROVEN на
    # всех шести версиях, и никто этого не видел: файл, где живёт закон, не
    # СОБИРАЛСЯ (соло-оп без образца).
    #
    # Одного ключа на пять клауз мало и по существу. Проверки внутри блока
    # можно вырезать поштучно, а ключ останется на месте — то есть посылка
    # «ключ = приговор» держится ровно до тех пор, пока ключ ОДИН НА ОДНО
    # обязательство. Разрезано так, чтобы каждая клауза таблицы имела свой.
    #
    # Чтение — общее и лежит в `reader_cs` ПЕРВОЙ проверки: `render_post`
    # печатает проверки подряд в одной области видимости, и соседи видят
    # `__vt_*`. Ровно та идиома, что у `create_floor_plan`.
    exp_n = len(layers)
    exp_total = round(sum(float(lr["width_mm"]) for lr in layers), 6)
    reader = (
        f"    {cls} __vt_{s} = doc.GetElement(__el_{s}.Id) as {cls};\n"
        f"    CompoundStructure __vcs_{s} = "
        f"__vt_{s} == null ? null : __vt_{s}.GetCompoundStructure();\n"
        f"    IList<CompoundStructureLayer> __vls_{s} = "
        f"__vcs_{s} == null ? null : __vcs_{s}.GetLayers();\n"
        f"    double[] __exw_{s} = new double[] {{ "
        + ", ".join(str(float(lr["width_mm"])) for lr in layers) + " };\n"
        f"    string[] __exf_{s} = new string[] {{ "
        + ", ".join(_cs(lr["function"]) for lr in layers) + " };\n"
        # МАТЕРИАЛ СЛОЯ ПЕРЕЧИТЫВАЕТСЯ ТОЖЕ, и по Id, а не по имени: имя
        # разрешено в фазе создания (ноль и больше одного — отказы), а слой
        # без материала обязан прийти с InvalidElementId. Молчаливая подмена
        # материала — та же форма, что имена `kir_f1` у семейств: зелёный
        # свидетель при подменённой личности.
        f"    string[] __exm_{s} = new string[] {{ "
        + ", ".join(
            (mat_var[lr["material"]] + ".Id.ToString()") if lr.get("material")
            else "ElementId.InvalidElementId.ToString()" for lr in layers)
        + " };\n"
    )

    # Затвор `__vls_ == null || Count != N` повторён у каждой поштучной
    # проверки НАМЕРЕННО: без него вырезание `layer_count` роняло бы соседей
    # по индексу, и закон L6 сообщал бы о падении компиляции, а не о
    # непроверенном обязательстве.
    ok_n = f"__vls_{s} != null && __vls_{s}.Count == {exp_n}"
    post = [
        WitnessCheck(
            obligation_key="type_reread", reader_cs=reader,
            verdict_cs=(
                f"    if (__vt_{s} == null)\n"
                f"      __post.Add({_cs(oid + ': тип не перечитывается по своему Id')});\n"),
            message="тип не перечитывается по своему Id", style="guard"),
        WitnessCheck(
            obligation_key="type_name", reader_cs="",
            verdict_cs=(
                f"    if (__vt_{s} != null && __vt_{s}.Name != {_cs(new_name)})\n"
                f"      __post.Add({_cs(oid + ': имя типа не равно запрошенному (re-read)')});\n"),
            message="имя типа не равно запрошенному (re-read)", style="guard"),
        WitnessCheck(
            obligation_key="layer_count", reader_cs="",
            verdict_cs=(
                f"    if (__vt_{s} != null && __vcs_{s} == null)\n"
                f"      __post.Add({_cs(oid + ': у типа нет CompoundStructure после записи')});\n"
                f"    else if (__vls_{s} != null && __vls_{s}.Count != {exp_n})\n"
                f"      __post.Add({_cs(oid + f': слоёв {{0}} вместо {exp_n} (re-read)')}"
                f".Replace(\"{{0}}\", __vls_{s}.Count.ToString()));\n"),
            message=f"слоёв не {exp_n} (re-read)", style="guard"),
        WitnessCheck(
            obligation_key="layers", reader_cs="",
            verdict_cs=(
                f"    if ({ok_n})\n"
                f"      for (int __i = 0; __i < {exp_n}; __i++)\n"
                f"      {{\n"
                f"        if (Math.Abs(MM(__vls_{s}[__i].Width) - __exw_{s}[__i]) > {ltol})\n"
                f"          __post.Add({_cs(oid + ': толщина слоя не удержалась (geometry, re-read), слой ')} + __i.ToString());\n"
                f"        if (__vls_{s}[__i].Function.ToString() != __exf_{s}[__i])\n"
                f"          __post.Add({_cs(oid + ': функция слоя не удержалась (geometry, re-read), слой ')} + __i.ToString());\n"
                f"      }}\n"),
            message="толщина или функция слоя не удержалась (geometry, re-read)",
            tol=ltol, style="guard"),
        WitnessCheck(
            obligation_key="layer_material", reader_cs="",
            verdict_cs=(
                f"    if ({ok_n})\n"
                f"      for (int __i = 0; __i < {exp_n}; __i++)\n"
                f"        if (__vls_{s}[__i].MaterialId.ToString() != __exm_{s}[__i])\n"
                f"          __post.Add({_cs(oid + ': материал слоя не удержался (re-read), слой ')} + __i.ToString());\n"),
            message="материал слоя не удержался (re-read)", style="guard"),
        WitnessCheck(
            obligation_key="total_width", reader_cs="",
            # 🔴 ОДНО ОБЯЗАТЕЛЬСТВО, ДВА ЧИТАТЕЛЯ, И ВЫБОР ЗАМЕРЕН. Свойства
            # `Width` нет ни у `FloorType`, ни у `RoofType`, ни у
            # `CeilingType` (0/6 на настоящих сборках 2021-2026 при двух
            # отрицательных контролях 0/6) — у них общая толщина живёт на
            # самом пироге, `CompoundStructure.GetWidth()` (6/6). Ветка стены
            # оставлена ДОСЛОВНО прежней ради паритета эмиссии.
            verdict_cs=(
                (f"    if (__vt_{s} != null && Math.Abs(MM(__vt_{s}.Width) - {exp_total}) > {ltol})\n"
                 if is_wall else
                 f"    if (__vcs_{s} != null && Math.Abs(MM(__vcs_{s}.GetWidth()) - {exp_total}) > {ltol})\n")
                + f"      __post.Add({_cs(oid + f': Width типа не равен сумме слоёв {exp_total} мм (geometry, re-read)')});\n"),
            message=f"Width типа не равен сумме слоёв {exp_total} мм (geometry, re-read)",
            tol=ltol, style="guard"),
    ]

    # Identity is an observation of the returned type object, whether new or
    # reused. The existing duplicated flag remains the separate creation fact.
    identity = (element_identity_readback_cs(f"__el_{s}", revit_version=ver)
                if host_kind in ("wall", "floor") else "")
    identifier = (f'    try {{ __rb["id"] = __el_{s}.Id.ToString(); }} catch {{ }}\n'
                  if identity else f'    __rb["id"] = __el_{s}.Id.ToString();\n')
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        + identifier + identity +
        f"    __rb[\"name\"] = __el_{s}.Name;\n"
        f"    __rb[\"duplicated\"] = __dupd_{s};\n"
        f"    __rb[\"layer_count\"] = {exp_n};\n"
        + (f"    __rb[\"width_mm\"] = MM(__el_{s}.Width);\n" if is_wall else
           f"    __rb[\"width_mm\"] = __el_{s}.GetCompoundStructure() == null "
           f"? -1.0 : MM(__el_{s}.GetCompoundStructure().GetWidth());\n")
        + _stamp_readback(f"__el_{s}", type_level=True) +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_transfer_material(op: dict, ver: str, stamp: str,
                            isolation: str = "atomic") -> tuple[str, str, list, str]:
    """`ElementTransformUtils.CopyElements` из ОТКРЫТОГО соседнего документа.

    🔴 ПОЧЕМУ КОПИЯ, А НЕ СБОРКА ПО ЗНАЧЕНИЯМ. Замер 23 материалов K3
    (24.08.2026): приложение внешнего вида несут 21, штриховку разреза 12,
    поверхности 8, физический актив 2. Это ОТДЕЛЬНЫЕ элементы, из программы
    неавторуемые; материал, собранный `Material.Create` + присвоением полей,
    приехал бы с верным именем и верным цветом при потерянном внешнем виде у
    двадцати одного из двадцати трёх. `CopyElements` везёт узел С
    ЗАВИСИМОСТЯМИ.

    🔴 СВИДЕТЕЛЬ ЧИТАЕТ ОБЕ СТОРОНЫ, И ЭТО НЕ ИЗБЫТОК. Обещание опа — «как в
    источнике», а не «как в программе»: ожидаемых значений в программе нет
    вовсе. Поэтому здесь единственный в реестре свидетель, который
    перечитывает и цель, и источник, и сравнивает их. Источник при этом ТОЛЬКО
    ЧИТАЕТСЯ — ни одна строка ниже в него не пишет.

    🔴 ОБРАБОТЧИКА ОДНОИМЁННЫХ ТИПОВ НЕТ НАМЕРЕННО. `CopyPasteOptions`
    позволяет назначить `SetDuplicateTypeNamesHandler` (6/6), но всякий его
    выбор — это решение ЗА АВТОРА о судьбе чужого одноимённого элемента в
    цели. Пока такого решения не заказывали, конфликт остаётся исключением
    Ревита и превращается в типизированный отказ, называющий имя."""
    oid = op["id"]
    s = _safe(oid)
    src_doc = op["source_document"]
    name = op["name"]

    # 🔴 ПОМОЩНИКИ ЖИВУТ В `decl`, А НЕ В ЧИТАТЕЛЕ СВИДЕТЕЛЯ. Контракт области
    # видимости этого файла: всё, что читают POST и квитанция, объявляется в
    # `decl` — под `per_op` создание заворачивается в свою скобку, и имя,
    # объявленное там, умирает на ней (CS0103, куплено здесь же на первом
    # прогоне: `__nm_` был объявлен в `reader_cs` и не дожил до квитанции).
    decl = (f"Material __el_{s} = null; bool __already_{s} = false;\n"
            f"Material __src_{s} = null; Document __sdoc_{s} = null;\n"
            f"Func<Document, ElementId, string> __nm_{s} = (__d, __id) =>\n"
            f"{{ var __e = __id == null ? null : __d.GetElement(__id); "
            f"return __e == null ? \"\" : __e.Name; }};\n"
            f"Func<Color, string> __col_{s} = __c => __c == null ? \"\" :\n"
            f"    (__c.Red + \",\" + __c.Green + \",\" + __c.Blue);")

    # ── источник: документ, потом материал в нём ────────────────────────
    resolve = (
        f"var __docs_{s} = new List<Document>();\n"
        f"var __titles_{s} = new List<string>();\n"
        f"foreach (Document __d_{s} in doc.Application.Documents)\n"
        f"{{\n"
        f"    if (__d_{s}.IsFamilyDocument) continue;\n"
        f"    __titles_{s}.Add(__d_{s}.Title);\n"
        f"    if (__d_{s}.Title.IndexOf({_cs(src_doc)}, StringComparison.OrdinalIgnoreCase) >= 0)\n"
        f"        __docs_{s}.Add(__d_{s});\n"
        f"}}\n"
        f"if (__docs_{s}.Count == 0) {{ {refuse_stmt(oid, f'{_cs("исходный документ «" + src_doc + "» не открыт в этой сессии Ревита; открытые: ")} + string.Join(", ", __titles_{s})', isolation)} }}\n"
        f"if (__docs_{s}.Count > 1) {{ {refuse_stmt(oid, f'{_cs("подстрока «" + src_doc + "» совпала с несколькими открытыми документами: ")} + string.Join(", ", __titles_{s})', isolation)} }}\n"
        f"__sdoc_{s} = __docs_{s}[0];\n"
        f"if (__sdoc_{s}.Equals(doc)) {{ {refuse_stmt(oid, _cs('источник и цель — ОДИН документ: переносить нечего'), isolation)} }}\n"
        f"var __sm_{s} = new FilteredElementCollector(__sdoc_{s}).OfClass(typeof(Material)).Cast<Material>()\n"
        f"    .Where(__m => __m.Name == {_cs(name)}).OrderBy(__m => __m.Id.ToString(), StringComparer.Ordinal).ToList();\n"
        f"if (__sm_{s}.Count == 0) {{ {refuse_stmt(oid, _cs('в исходном документе нет материала с именем «' + name + '»'), isolation)} }}\n"
        f"if (__sm_{s}.Count > 1) {{ {refuse_stmt(oid, _cs('в исходном документе имя материала «' + name + '» неоднозначно (найдено больше одного)'), isolation)} }}\n"
        f"__src_{s} = __sm_{s}[0];")

    # ── штатный повтор узнаётся ДО вызова ───────────────────────────────
    twin = (
        f"\nvar __tw_{s} = new FilteredElementCollector(doc).OfClass(typeof(Material)).Cast<Material>()\n"
        f"    .Where(__m => __m.Name == {_cs(name)}).ToList();\n"
        f"if (__tw_{s}.Count > 1) {{ {refuse_stmt(oid, _cs('в целевом документе имя материала «' + name + '» уже неоднозначно — адрес не определён'), isolation)} }}\n"
        f"if (__tw_{s}.Count == 1) {{ __el_{s} = __tw_{s}[0]; __already_{s} = true; }}\n"
        f"else\n"
        f"{{\n"
        f"    ICollection<ElementId> __new_{s} = null;\n"
        f"    try\n"
        f"    {{\n"
        f"        __new_{s} = ElementTransformUtils.CopyElements(\n"
        f"            __sdoc_{s}, new List<ElementId> {{ __src_{s}.Id }}, doc,\n"
        f"            Transform.Identity, new CopyPasteOptions());\n"
        f"    }}\n"
        f"    catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"CopyElements: \" + __ex_{s}.Message', isolation)} }}\n"
        f"    doc.Regenerate();\n"
        # Возврат несёт и ЗАВИСИМОСТИ (штриховки, приложения вида), поэтому
        # материал выбирается ПО ИМЕНИ, а не «первым из списка».
        f"    if (__new_{s} != null)\n"
        f"        foreach (ElementId __i_{s} in __new_{s})\n"
        f"        {{\n"
        f"            var __c_{s} = doc.GetElement(__i_{s}) as Material;\n"
        f"            if (__c_{s} != null && __c_{s}.Name == {_cs(name)}) __el_{s} = __c_{s};\n"
        f"        }}\n"
        f"    if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('перенос не дал материала с именем «' + name + '» — копия ушла под другим именем или не состоялась'), isolation)} }}\n"
        f"}}")

    create = (f"// transfer_material {cs_line_comment_fragment(oid)}\n"
              f"{resolve}{twin}\n"
              + _stamp_type_block(f"__el_{s}", f"{stamp}:{oid}"))

    # ── свидетель: обе стороны, по своей оси каждая ─────────────────────
    reader = (
        f"    Material __vt_{s} = doc.GetElement(__el_{s}.Id) as Material;\n")

    def check(key, verdict, message):
        return WitnessCheck(obligation_key=key, reader_cs="",
                            verdict_cs=verdict, message=message, style="guard")

    post = [
        WitnessCheck(
            obligation_key="material_reread", reader_cs=reader,
            verdict_cs=(
                f"    if (__vt_{s} == null)\n"
                f"      __post.Add({_cs(oid + ': материал не перечитывается по своему Id')});\n"),
            message="материал не перечитывается по своему Id", style="guard"),
        check("material_name",
              f"    if (__vt_{s} != null && __vt_{s}.Name != {_cs(name)})\n"
              f"      __post.Add({_cs(oid + ': имя материала не равно запрошенному (re-read)')});\n",
              "имя материала не равно запрошенному (re-read)"),
        check("material_class",
              f"    if (__vt_{s} != null && (__vt_{s}.MaterialClass != __src_{s}.MaterialClass\n"
              f"        || __vt_{s}.MaterialCategory != __src_{s}.MaterialCategory))\n"
              f"      __post.Add({_cs(oid + ': класс или категория материала не совпали с источником (re-read): ')}\n"
              f"        + __vt_{s}.MaterialClass + \"/\" + __vt_{s}.MaterialCategory\n"
              f"        + \" против \" + __src_{s}.MaterialClass + \"/\" + __src_{s}.MaterialCategory);\n",
              "класс или категория материала не совпали с источником (re-read)"),
        check("material_color",
              f"    if (__vt_{s} != null && __col_{s}(__vt_{s}.Color) != __col_{s}(__src_{s}.Color))\n"
              f"      __post.Add({_cs(oid + ': цвет материала не совпал с источником (re-read): ')}\n"
              f"        + __col_{s}(__vt_{s}.Color) + \" против \" + __col_{s}(__src_{s}.Color));\n",
              "цвет материала не совпал с источником (re-read)"),
        # 🔴 ГЛАВНАЯ КЛАУЗА. Ради неё оп не собирает материал по значениям:
        # верное имя при потерянном внешнем виде — исход, неотличимый от успеха
        # без этой проверки.
        check("appearance_asset",
              f"    if (__vt_{s} != null && __nm_{s}(doc, __vt_{s}.AppearanceAssetId)\n"
              f"        != __nm_{s}(__sdoc_{s}, __src_{s}.AppearanceAssetId))\n"
              f"      __post.Add({_cs(oid + ': приложение внешнего вида не совпало с источником (re-read): «')}\n"
              f"        + __nm_{s}(doc, __vt_{s}.AppearanceAssetId) + \"» против «\"\n"
              f"        + __nm_{s}(__sdoc_{s}, __src_{s}.AppearanceAssetId) + \"»\");\n",
              "приложение внешнего вида не совпало с источником (re-read)"),
        check("fill_patterns",
              f"    if (__vt_{s} != null && (\n"
              f"        __nm_{s}(doc, __vt_{s}.SurfaceForegroundPatternId)\n"
              f"          != __nm_{s}(__sdoc_{s}, __src_{s}.SurfaceForegroundPatternId)\n"
              f"        || __nm_{s}(doc, __vt_{s}.CutForegroundPatternId)\n"
              f"          != __nm_{s}(__sdoc_{s}, __src_{s}.CutForegroundPatternId)))\n"
              f"      __post.Add({_cs(oid + ': штриховки не совпали с источником (re-read): ')}\n"
              f"        + __nm_{s}(doc, __vt_{s}.SurfaceForegroundPatternId) + \"/\"\n"
              f"        + __nm_{s}(doc, __vt_{s}.CutForegroundPatternId) + \" против \"\n"
              f"        + __nm_{s}(__sdoc_{s}, __src_{s}.SurfaceForegroundPatternId) + \"/\"\n"
              f"        + __nm_{s}(__sdoc_{s}, __src_{s}.CutForegroundPatternId));\n",
              "штриховки не совпали с источником (re-read)"),
    ]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"name\"] = __el_{s}.Name;\n"
        f"    __rb[\"already_present\"] = __already_{s};\n"
        f"    __rb[\"source_document\"] = __sdoc_{s}.Title;\n"
        f"    __rb[\"appearance\"] = __nm_{s}(doc, __el_{s}.AppearanceAssetId);\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_load_family(op: dict, ver: str, stamp: str,
                      isolation: str = "atomic") -> tuple[str, str, str, str]:
    """Document.LoadFamily(path, out Family) / Document.LoadFamilySymbol(path,
    typeName, out FamilySymbol) — the wiki-verified pattern (family-load-
    place.md FAM-034 / the nested-load recipe). File.Exists is checked INSIDE
    the emitted C# (execute time, on the Revit-bridge host — the only place
    with the user's filesystem; ground has no such access). No IFamilyLoadOptions
    override here: v1 accepts the Revit-default no-overwrite behavior.  The
    API contract only promises a non-null out value on successful loading;
    already-loaded values are therefore resolved first by BOTH family name
    (the .rfa filename stem) and type name, never by type name alone.  The
    OnFamilyFound override pattern (class-sibling idiom) is reserved for a
    future reload/overwrite op."""
    oid = op["id"]
    s = _safe(oid)
    path = op["path"]
    type_name = op.get("type_name")
    if type_name is not None:
        decl = f"FamilySymbol __el_{s} = null; bool __already_{s} = false;"
        # per_op collision (28.07, gate finding): emit_program's per_op
        # scaffold declares its OWN op-scoped `bool __ok_{s} = false;`
        # sentinel in the outer decl block (one per op, set True on
        # SubTransaction commit — every emitter shares that name unmodified).
        # This branch used to declare a SECOND, inner `bool __ok_{s};` for
        # LoadFamilySymbol's own out-parameter — same name, enclosing scope
        # -> Roslyn CS0136, live, on all six versions. Atomic emission has no
        # outer sentinel at all, so it never collided and its bytes are a
        # golden — the rename is CONDITIONAL on isolation so atomic keeps its
        # original `__ok_{s}` untouched and only per_op gets the new name.
        sym_ok = f"__ok_{s}" if isolation != "per_op" else f"__symOk_{s}"
        load = (
            f"if (!System.IO.File.Exists({_cs(path)})) {{ {refuse_stmt(oid, _cs('файл не найден: ' + path), isolation)} }}\n"
            f"string __family_name_{s} = System.IO.Path.GetFileNameWithoutExtension({_cs(path)});\n"
            f"var __existing_{s} = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>()\n"
            f"    .Where(__c => __c.Name == {_cs(type_name)} && __c.Family != null &&\n"
            f"        __c.Family.Name.Equals(__family_name_{s}, StringComparison.OrdinalIgnoreCase))\n"
            f"    .OrderBy(__c => __c.Id.ToString(), StringComparer.Ordinal).ToList();\n"
            f"if (__existing_{s}.Count > 1) {{ {refuse_stmt(oid, _cs('несколько уже загруженных типоразмеров совпали по семье и имени'), isolation)} }}\n"
            f"if (__existing_{s}.Count == 1) {{ __el_{s} = __existing_{s}[0]; __already_{s} = true; }}\n"
            f"else\n"
            f"{{\n"
            f"    FamilySymbol __sym_{s};\n"
            f"    bool {sym_ok};\n"
            f"    try {{ {sym_ok} = doc.LoadFamilySymbol({_cs(path)}, {_cs(type_name)}, out __sym_{s}); }}\n"
            f"    catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"LoadFamilySymbol: \" + __ex_{s}.Message', isolation)} }}\n"
            f"    if (!{sym_ok} || __sym_{s} == null) {{ {refuse_stmt(oid, _cs('типоразмер «' + type_name + '» не найден в файле'), isolation)} }}\n"
            f"    __el_{s} = __sym_{s};\n"
            f"}}\n"
            f"if (!__el_{s}.IsActive) {{ __el_{s}.Activate(); doc.Regenerate(); }}\n"
            + _stamp_type_block(f"__el_{s}", f"{stamp}:{oid}"))
        readback_extra = f'    __rb["already_loaded"] = __already_{s};\n'
    else:
        decl = f"Family __fam_{s} = null; FamilySymbol __el_{s} = null; bool __already_{s} = false;"
        # RevitAPI.xml promises a non-null out Family only on success.  Resolve
        # a previously loaded family by the .rfa stem first; never reinterpret
        # an undocumented false/null return as a successful idempotent load.
        load = (
            f"if (!System.IO.File.Exists({_cs(path)})) {{ {refuse_stmt(oid, _cs('файл не найден: ' + path), isolation)} }}\n"
            f"string __family_name_{s} = System.IO.Path.GetFileNameWithoutExtension({_cs(path)});\n"
            f"var __families_{s} = new FilteredElementCollector(doc).OfClass(typeof(Family)).Cast<Family>()\n"
            f"    .Where(__f => __f.Name.Equals(__family_name_{s}, StringComparison.OrdinalIgnoreCase))\n"
            f"    .OrderBy(__f => __f.Id.ToString(), StringComparer.Ordinal).ToList();\n"
            f"if (__families_{s}.Count > 1) {{ {refuse_stmt(oid, _cs('несколько уже загруженных семейств совпали с именем файла'), isolation)} }}\n"
            f"if (__families_{s}.Count == 1) {{ __fam_{s} = __families_{s}[0]; __already_{s} = true; }}\n"
            f"else\n"
            f"{{\n"
            f"    bool __loaded_{s};\n"
            f"    try {{ __loaded_{s} = doc.LoadFamily({_cs(path)}, out __fam_{s}); }}\n"
            f"    catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"LoadFamily: \" + __ex_{s}.Message', isolation)} }}\n"
            f"    if (!__loaded_{s} || __fam_{s} == null) {{ {refuse_stmt(oid, _cs('LoadFamily не загрузил семейство'), isolation)} }}\n"
            f"}}\n"
            # The symbols are found with a COLLECTOR, not with
            # `Family.GetFamilySymbolIds()`, and that is not a preference:
            # that member returns `ISet<ElementId>`, and on net48 `ISet<>` is
            # declared in `System.dll`, which the DEPLOYED plugin does not
            # reference — CS0012, the same mine that killed the decompile tag
            # stage live on 2026-08-04. `FamilySymbol.Family` exists on all six
            # versions and answers the same question with types from mscorlib.
            # Same set, same ordering, same FirstOrDefault.
            f"__el_{s} = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol))\n"
            f"    .Cast<FamilySymbol>()\n"
            f"    .Where(__x => __x != null && __x.Family != null\n"
            f"                  && __x.Family.Id.ToString() == __fam_{s}.Id.ToString())\n"
            f"    .OrderBy(__x => __x.Name, StringComparer.Ordinal)\n"
            f"    .ThenBy(__x => __x.Id.ToString(), StringComparer.Ordinal).FirstOrDefault();\n"
            f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('семейство не содержит ни одного типоразмера, который резолвится'), isolation)} }}\n"
            f"if (!__el_{s}.IsActive) {{ __el_{s}.Activate(); doc.Regenerate(); }}\n"
            + _stamp_type_block(f"__el_{s}", f"{stamp}:{oid}"))
        readback_extra = f'    __rb["family_name"] = __fam_{s} != null ? __fam_{s}.Name : null;\n    __rb["already_loaded"] = __already_{s};\n'
    create = f"// load_family {cs_line_comment_fragment(oid)}\n{load}"
    post = [WitnessCheck(
        obligation_key="active", reader_cs="",
        verdict_cs=(
            f"    if (!__el_{s}.IsActive) __post.Add({_cs(oid + ': символ не активен после Activate (semantic)')});\n"),
        message="символ не активен после Activate (semantic)", style="guard")]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"type_name\"] = __el_{s}.Name;\n"
        + readback_extra +
        _stamp_readback(f"__el_{s}", type_level=True) +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


# ── Documentation family: create_dimension / create_tag / create_text ───────
# (KIR_DOC_SPEC.md — VIEW-SPACE ops; docspace.py core REUSED, not reinvented.)
#
# in_view/target/refs[]/*_type are write-target selectors (kind="target_w":
# pinned element_id OR an intra-program ref) — there is no views/sheets or
# */types snapshot pool yet (a Fable-level registry_base.py change), so
# resolution here is the SAME id-pinned/ref-only pattern as set_param.target
# and create_window/create_door.host — never _gid()/ground.py (grounded=()
# for every op in ops_annotation.py).



def _annot_elem_res(sel: dict, var: str, ver: str, oid: str, label: str,
                    isolation: str = "atomic") -> str:
    """Resolve a target_w selector (element_id | ref) into Element <var>,
    labeled null-guard message (shared shape for target/refs[i]/*_type)."""
    if sel["by"] == "ref":
        rv = "__el_" + _safe(sel["value"])
        return f"Element {var} = (Element){rv};"
    return (f"Element {var} = doc.GetElement({_eid(sel['value'], ver, oid)});\n"
            f"if ({var} == null) {{ {refuse_stmt(oid, f'\"{label}: элемент не найден (модель изменилась после grounding)\"', isolation)} }}")


def _dim_geom_helpers_cs(s: str) -> str:
    """C# local functions (one set per create_dimension op) that turn an
    ELEMENT into the GEOMETRIC reference ``NewDimension`` demands, plus the
    model-space plane that reference names.

    Local functions rather than unrolled text because the same walk is needed
    once per ref AND again for nested family geometry (recursion); they are
    emitted into ``decl`` so ``per_op`` isolation, which wraps every create
    block in its own scope, still sees them (scope contract).

    THREE SHAPES OF GEOMETRY, ONE OF THEM DOCUMENTED-DANGEROUS:

    * ``Solid`` at the top level — a wall/floor/roof/in-place body: take a
      ``PlanarFace`` and its own ``Reference``.
    * ``Curve`` at the top level — a datum (grid, level, reference plane) or a
      model line.  ``Options.IncludeNonVisibleObjects`` is what makes datum
      geometry appear at all; without it ``Grid.get_Geometry`` yields an EMPTY
      GeometryElement, which is why every grid refused before 09.08 while the
      registry entry advertised "элементов ИЛИ ОСЕЙ".  The measured plane of a
      datum is the vertical plane through the line: normal = direction ×
      View.ViewDirection.
    * ``GeometryInstance`` — EVERY family instance (column, beam, door,
      window, furniture, generic model): Revit stores one copy of the symbol
      geometry and transforms it per instance, so the top level carries NO
      Solid at all.  The old walk tested ``go as Solid`` and skipped, so the
      op refused on the entire FamilyInstance class.

      The obvious repair — ``GetInstanceGeometry()`` — is the WRONG reference,
      and RevitAPI.xml says so verbatim for both transformed accessors: "because
      it returns a copy the references found in the geometry objects contained
      in this element are not suitable for creating new Revit elements
      referencing the original element (for example, dimensioning). Only the
      geometry returned by GetSymbolGeometry() with no transform can be used
      for that purpose."  ``GetSymbolGeometry()`` (no argument) answers: "This
      method returns the actual Revit geometry ... suitable for creating new
      Revit elements referencing the original element (for example,
      dimensioning)."  So the REFERENCE comes from symbol geometry, and the
      POSITION does not: symbol geometry is in the symbol's local coordinate
      space, so the point/normal are pushed through ``GeometryInstance.Transform``
      (composed for nesting) to get back into model space.  Taking the
      reference from one accessor and the coordinates from another is the whole
      trick, and it is why this cannot be a single ``as Solid`` cast.

    WHICH face, and why it is no longer arbitrary.  A dimension between "the
    first planar face of A" and "the first planar face of B" is a number with
    no meaning — Solid.Faces has no documented order, so an end face and a side
    face could be measured against each other and the result would look fine.
    Two rules remove the arbitrariness, both using Revit's OWN zero-length test
    (``XYZ.IsZeroLength``) so no threshold is invented here:

      1. a candidate is usable only if its normal has a non-zero projection
         into the view plane (a face edge-on to the view cannot carry an
         in-plane dimension direction at all);
      2. the FIRST ref fixes the measurement normal; every later ref prefers a
         candidate PARALLEL to it (cross product zero-length).  Preference, not
         a gate: when nothing parallel exists the first usable candidate is
         still handed over and ``NewDimension`` itself judges it — refusing
         earlier than Revit would would refuse dimensions Revit accepts.

    The chosen plane travels out of here (``__gpt``/``__gn``) because the
    VALUE witness needs it: see ``_emit_dimension``."""
    return f"""bool __dimTake_{s}(Reference __r, XYZ __o, XYZ __n, XYZ __want,
    ref Reference __gr, ref XYZ __gp, ref XYZ __gn,
    ref Reference __fr, ref XYZ __fp, ref XYZ __fn)
{{
    if (__r == null || __o == null || __n == null) return false;
    XYZ __vd = __vw_{s}.ViewDirection;
    XYZ __ip = __n.Subtract(__vd.Multiply(__n.DotProduct(__vd)));
    if (__ip.IsZeroLength()) return false;
    __ip = __ip.Normalize();
    if (__fr == null) {{ __fr = __r; __fp = __o; __fn = __ip; }}
    if (__want != null && !__ip.CrossProduct(__want).IsZeroLength()) return false;
    __gr = __r; __gp = __o; __gn = __ip;
    return true;
}}
void __dimWalk_{s}(GeometryElement __ge, Transform __tf, XYZ __want,
    ref Reference __gr, ref XYZ __gp, ref XYZ __gn,
    ref Reference __fr, ref XYZ __fp, ref XYZ __fn)
{{
    if (__ge == null) return;
    foreach (GeometryObject __go in __ge)
    {{
        Solid __sol = __go as Solid;
        if (__sol != null)
        {{
            foreach (Face __fc in __sol.Faces)
            {{
                PlanarFace __pf = __fc as PlanarFace;
                if (__pf == null || __pf.Reference == null) continue;
                if (__dimTake_{s}(__pf.Reference, __tf.OfPoint(__pf.Origin),
                        __tf.OfVector(__pf.FaceNormal), __want,
                        ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn)) return;
            }}
            continue;
        }}
        Curve __cv = __go as Curve;
        if (__cv != null)
        {{
            if (__cv.Reference == null) continue;
            XYZ __ca = null; XYZ __cd = null;
            Line __cl = __cv as Line;
            if (__cl != null) {{ __ca = __cl.Origin; __cd = __cl.Direction; }}
            else if (__cv.IsBound) {{ __ca = __cv.GetEndPoint(0); __cd = __cv.GetEndPoint(1).Subtract(__ca); }}
            if (__ca == null || __cd == null || __cd.IsZeroLength()) continue;
            XYZ __cn = __cd.Normalize().CrossProduct(__vw_{s}.ViewDirection);
            if (__cn.IsZeroLength()) continue;
            if (__dimTake_{s}(__cv.Reference, __tf.OfPoint(__ca),
                    __tf.OfVector(__cn.Normalize()), __want,
                    ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn)) return;
            continue;
        }}
        GeometryInstance __gi = __go as GeometryInstance;
        if (__gi != null)
        {{
            __dimWalk_{s}(__gi.GetSymbolGeometry(), __tf.Multiply(__gi.Transform), __want,
                ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn);
            if (__gr != null) return;
        }}
    }}
}}
void __dimGeom_{s}(Element __el, XYZ __want, out Reference __gr, out XYZ __gp, out XYZ __gn)
{{
    __gr = null; __gp = null; __gn = null;
    Reference __fr = null; XYZ __fp = null; XYZ __fn = null;
    Wall __wl = __el as Wall;
    if (__wl != null)
    {{
        try
        {{
            IList<Reference> __sf = HostObjectUtils.GetSideFaces(__wl, ShellLayerType.Exterior);
            if (__sf != null)
                foreach (Reference __sr in __sf)
                {{
                    PlanarFace __spf = __el.GetGeometryObjectFromReference(__sr) as PlanarFace;
                    if (__spf == null) continue;
                    if (__dimTake_{s}(__sr, __spf.Origin, __spf.FaceNormal, __want,
                            ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn)) break;
                }}
        }} catch {{ }}
    }}
    if (__gr == null)
    {{
        Options __gopt = new Options();
        __gopt.ComputeReferences = true;
        __gopt.IncludeNonVisibleObjects = true;
        __gopt.View = __vw_{s};
        GeometryElement __gge = null;
        try {{ __gge = __el.get_Geometry(__gopt); }} catch {{ }}
        __dimWalk_{s}(__gge, Transform.Identity, __want,
            ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn);
    }}
    if (__gr == null && __fr != null) {{ __gr = __fr; __gp = __fp; __gn = __fn; }}
}}"""


def _emit_dimension(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple[str, str, str, str]:
    """create_dimension: doc.Create.NewDimension(view, Line, ReferenceArray[, DimensionType])
    — STABLE across 2021-2026 (no per-version branch; the 4-arg DimensionType
    overload exists unchanged back to 2019, re-confirmed 09.08 against the six
    reference assemblies through the live Roslyn service, not against docs).

    Regenerate BEFORE reference extraction (28.07, live П11-repeat measured
    by the lead AFTER the reference/line fix below landed): the SAME typed
    refusal fired again live — «refs[0]: у элемента нет геометрической
    ссылки для размера» — for a DIFFERENT, structural reason. A freshly
    created wall has NO faces until the document is regenerated
    (GetSideFaces returns empty; the geometry-fallback walk is ALSO empty
    pre-regen — Element.Geometry needs regenerated geometry same as
    GetSideFaces does). Measured: no ``doc.Regenerate()`` sat between the
    wall's ``Wall.Create`` and this op's ``GetSideFaces`` in the ATOMIC
    emission — ``emit_program``'s own wall-tracking regenerate ("v0 rule")
    only fires before ``create_room``, never before ``create_dimension``.
    per_op isolation needs the SAME explicit call: neither
    ``SubTransaction.Commit()`` nor ``Transaction.Commit()`` is documented
    to regenerate (RevitAPI.xml is silent on it either way — regeneration
    is always its own, separate ``Document.Regenerate()`` call), so a wall
    committed in an earlier, already-closed SubTransaction is not
    guaranteed to have live faces when this op's OWN SubTransaction starts.
    Fix: unconditional ``doc.Regenerate()`` as the first statement of this
    op's create block, before ANY reference is extracted — covers same-
    program refs (walls OR the geometry-fallback path, which needs
    regenerated geometry equally) and is a cheap no-op when nothing is
    pending. NOT wrapped in try/catch, matching the established law
    elsewhere in this file (set_curtain_panel, INTENDED_CHANGES 28.07):
    RevitAPI.xml is explicit that a RegenerationFailedException means the
    document is corrupted and the transaction owner must be aborted, never
    caught-and-ignored.

    References (28.07, live E5 measurement, FAS_R23 Revit 2023 — see wave
    report): ReferenceArray needs GEOMETRIC references (a face/edge/curve),
    never an ELEMENT reference — ``new Reference(element)`` compiled 6/6 (the
    gate cannot see this) but refused LIVE: «NewDimension: The references are
    not geometric references. Parameter name: references».  RevitAPI.xml says
    the same for both overloads: "An array of geometric references to which
    the dimension is to be bound", ArgumentException "Thrown when references
    are not geometric references".

    WHAT WAS STILL WRONG AFTER THAT FIX (09.08).  The 28.07 repair covered
    exactly one shape of element — a straight ``Wall``, via
    ``HostObjectUtils.GetSideFaces``, the one shape E5 measured.  Everything
    else fell to a generic walk that tested only ``go as Solid`` at the top
    level, and TWO whole classes of element can never produce a Solid there:

      * a FAMILY INSTANCE (column, beam, door, window, furniture, generic
        model) stores its geometry as a ``GeometryInstance`` — RevitAPI.xml,
        type summary: "The most common situation where GeometryInstances are
        encountered is in Family instances."  The walk skipped it, so the op
        answered every such request with the typed refusal «у элемента нет
        геометрической ссылки для размера»;
      * a DATUM (grid, level, reference plane) and a model line expose a
        ``Curve``, not a Solid, and only when
        ``Options.IncludeNonVisibleObjects`` is set — which it was not.  The
        registry entry for this op advertises "элементов ИЛИ ОСЕЙ" in its own
        comment, so a grid dimension was a promise the emitter could not keep.

    That is the honest reading of "1 built / 3 blamed": the ONE recipe that
    was fixed is the one that builds, and the emitter refused the rest.  The
    fix is not "unwrap the instance" but WHICH unwrap: ``GetInstanceGeometry()``
    is documented as returning a COPY whose "references ... are not suitable
    for creating new Revit elements referencing the original element (for
    example, dimensioning)" — i.e. it produces exactly the class of reference
    NewDimension throws on, and it would have compiled 6/6 and refused live a
    third time.  ``GetSymbolGeometry()`` with no transform is the one the API
    names as suitable; its coordinates are symbol-local, so the point and
    normal ride back through ``GeometryInstance.Transform``.  See
    :func:`_dim_geom_helpers_cs` for the walk and for why the face choice is
    no longer arbitrary.

    Refusal stays typed and op-bound (``refuse_stmt``): a null is never
    smuggled into ReferenceArray.

    THE MEASURED VALUE IS NOW GATED (09.08) — and this is a reversal of the
    28.07 note, so the reason matters.  28.07 said no expectation exists
    because "which faces get chosen changes the value".  That was true when
    the face was chosen arbitrarily; it stopped being true when the emitter
    started KNOWING which plane it handed over.  The witness now compares
    Revit's own reported number against the distance between the planes the
    references actually name:

      * project every resolved plane's point onto the dimension direction,
        sort (the sort makes the check independent of the order Revit chose
        to store References in — RevitAPI.xml only promises that segment N is
        "wrapped by nth and n+1st references", i.e. an along-the-line order);
      * consecutive differences ARE the expected segment values;
      * read back ``Dimension.Value`` for one segment, or every
        ``DimensionSegment.Value`` when ``NumberOfSegments > 1`` — RevitAPI.xml:
        Value "will not have a value ... for linear dimensions with more than
        one segment", which is why a single-segment read alone would have been
        a check that cannot fail on a 3-ref dimension.

    This is NOT a claim about the user's intent — no compiler can know whether
    the operator wanted the exterior or the interior face.  It is the claim
    the axis can carry: THE NUMBER REVIT PRINTED IS THE DISTANCE BETWEEN THE
    GEOMETRY THIS DIMENSION IS BOUND TO.  It can fail, and the failures it is
    built for are real: a family-instance transform composed wrongly (symbol
    coordinates leaking into model space), a reference that re-associated to
    another subelement on regeneration, or a segment/reference correspondence
    that is not the documented one.  Any of those used to be a plausible-
    looking number in the receipt with a green witness.

    NO TOLERANCE IS INVENTED FOR IT, and none is registered: the comparison
    runs against ``doc.Application.VertexTolerance`` — Revit's own "two points
    within this distance are considered coincident" — read from the running
    application at witness time.  There is no number in the emitted C# and no
    number in the registry to drift.  The margin is not load-bearing either
    way: both sides are exact double arithmetic over the same geometry (noise
    ~1e-12 ft), while the defect class it separates (a wrong face, a wrong
    transform) is off by a wall thickness or a storey.

    Line (28.07, same live measurement): line_at is ONE view-space point
    (KIR_DOC_SPEC.md dimension.line_at) — the ANCHOR the line passes
    through, unchanged. The DIRECTION used to be unconditionally
    View.RightDirection (horizontal in view-space); E5 showed this is
    backwards for the ordinary case (two parallel walls running EAST-WEST,
    separated NORTH-SOUTH) — the line must run ACROSS the measured faces
    (a perpendicular to the walls), or the references project onto
    coincident/degenerate points. It is now the in-view-plane normal of the
    FIRST resolved reference, which the resolver already computed and
    already proved non-degenerate — so the old ``View.RightDirection``
    fallback is GONE, together with the flagged gap that described it: a ref
    whose normal cannot project into the view plane is no longer silently
    dimensioned along an unrelated axis, it is not a usable candidate at all.
    Dimension.Curve is documented ALWAYS UNBOUND (Revit API Developer
    Guide, "Dimensions and Constraints"): the drawn extent — and the
    position of Origin ALONG the line — is an emergent property of where
    the actual references project, never of line_at.u; only the line's
    ANCHOR+DIRECTION are ours to state, and neither is asserted as a
    postcondition (the VALUE is)."""
    oid = op["id"]
    s = _safe(oid)
    view_res = _annot_view_res(op, s, ver, oid, isolation)
    refs = op["refs"]
    u, w = op["line_at"]
    p0_cs = docspace.emit_view2d_to_xyz_cs(f"__vw_{s}", u, w)
    ref_lines = []
    elem_vars = []
    gref_vars = []
    pt_vars = []
    for i, sel in enumerate(refs):
        rv = f"__rf_{s}_{i}"
        gv = f"__gref_{s}_{i}"
        pv = f"__gpt_{s}_{i}"
        nv = f"__gn_{s}_{i}"
        label = f"refs[{i}]"
        # ВТОРАЯ СТУПЕНЬ СЕЛЕКТОРА: грань НАЗВАНА, а не найдена наугад.
        #
        # Ветка стоит ПЕРЕД общей и заменяет её целиком, потому что это два
        # разных обещания, а не два способа сделать одно. Общая ветка ИЩЕТ
        # годную геометрическую ссылку и вправе взять первую попавшуюся: у
        # `NewDimension` без ссылки нет вообще ничего, и «какая-нибудь грань»
        # лучше отказа. Названная грань — обещание другого рода: программа
        # сказала КАКАЯ, и «какая-нибудь» здесь была бы ложью в квитанции.
        # Поэтому здесь мощность множества решает, а не порядок перебора
        # (см. `faceref.resolve_cs`).
        if faceref.is_face_sel(sel):
            el_res = _annot_elem_res(
                faceref.inner_selector(sel), rv, ver, oid, f"{label}.of",
                isolation).replace(f"Element {rv} =", f"{rv} =", 1)
            ref_lines.append(
                f"{el_res}\n"
                f"Reference {gv} = null;\n"
                + faceref.resolve_cs(
                    sel, s=s, i=i, elem_var=rv, out_var=gv, oid=oid,
                    label=label, isolation=isolation, view_var=f"__vw_{s}",
                    refuse_stmt=refuse_stmt, cs_literal=_cs)
                # ПОДПИСЬ СВЯЗАННОЙ ГРАНИ, снятая ДО коммита. Её читает
                # свидетель ниже; `catch` не глотает неудачу, а СНИМАЕТ ФЛАГ,
                # и свидетель на снятом флаге падает. Проглоченное чтение
                # сделало бы проверку непроваливаемой — то есть хуже, чем её
                # отсутствие.
                + f"\ntry {{ __fbWant_{s}.Add({gv}.ConvertToStableRepresentation(doc)); }}"
                + f"\ncatch {{ __fbOk_{s} = false; }}"
                # 🔴 ПЛОСКОСТЬ НАЗВАННОЙ ГРАНИ — ТО, ЧЕГО ЗДЕСЬ НЕ БЫЛО, И
                # ЦЕНА БЫЛА ДВОЙНАЯ (25.08.2026, доказано Roslyn).
                #
                # Ветка связывала ТОЛЬКО `Reference` и уходила `continue`,
                # минуя объявление `XYZ __gn_<s>_<i>` и пополнение
                # `pt_vars`. Следствия, оба гарантированные, а не вероятные:
                #
                #   1. `__dimDir_<s> = __gn_<s>_0;` ниже читает переменную,
                #      которой НЕТ. Roslyn на настоящих сборках 2026:
                #      «CS0103 The name '__gn_D1_0' does not exist in the
                #      current context» — при `out.ok = True`. То есть
                #      компилятор говорил «годно», а у пользователя это не
                #      собиралось НИКОГДА;
                #   2. `__proj_<s>` строится из `pt_vars`, поэтому у размера
                #      с названными гранями он ПУСТ: `__expect_.Count == 0`
                #      против `__got_.Count == 1` -> свидетель значения
                #      падает ВСЕГДА, а в `atomic` это откат всей программы.
                #
                # Плоскость берётся из ТОЙ ЖЕ связанной ссылки — не ищется
                # заново: искать значило бы вернуть «какую-нибудь грань» в
                # ветку, вся суть которой в том, что грань НАЗВАНА.
                + f"\nXYZ {nv} = null;"
                + f"\ntry {{ PlanarFace __pf_{s}_{i} = "
                  f"{rv}.GetGeometryObjectFromReference({gv}) as PlanarFace;"
                  f" if (__pf_{s}_{i} != null) {{ {pv} = __pf_{s}_{i}.Origin;"
                  f" {nv} = __pf_{s}_{i}.FaceNormal; }} }} catch {{ }}"
                + f"\nif ({nv} == null) {{ "
                + refuse_stmt(
                    oid,
                    _cs(label + ": названная грань связана, но её ПЛОСКОСТЬ "
                        "не читается (грань не планарна) — размер по ней не "
                        "выразим. СЛЕДУЮЩИЙ ХОД: сошлись на элемент без "
                        "`by: face`, либо назови планарную грань"),
                    isolation)
                + " }")
            elem_vars.append(rv)
            gref_vars.append(gv)
            pt_vars.append(pv)
            continue
        # assignment form: the post block reads every __rf_<s>_<i> (requested
        # ids witness) and every __gpt_<s>_<i> (value witness), so their
        # declarations hoist to decl (scope contract).  __gref_/__gn_ are
        # create-local; __gn_<s>_0 is read by the LATER refs of the same
        # create block, which is the same scope.
        el_res = _annot_elem_res(sel, rv, ver, oid, label, isolation).replace(
            f"Element {rv} =", f"{rv} =", 1)
        want = "null" if i == 0 else f"__gn_{s}_0"
        ref_lines.append(
            f"{el_res}\n"
            f"Reference {gv} = null;\n"
            f"XYZ {nv} = null;\n"
            f"__dimGeom_{s}({rv}, {want}, out {gv}, out {pv}, out {nv});\n"
            f"if ({gv} == null) {{ {refuse_stmt(oid, _cs(label + ': у элемента нет геометрической ссылки для размера'), isolation)} }}")
        elem_vars.append(rv)
        gref_vars.append(gv)
        pt_vars.append(pv)
    ref_array_lines = "\n".join(ref_lines)
    ref_appends = "\n".join(
        f"__refs_{s}.Append({gv});" for gv in gref_vars)
    # Line direction: the in-view-plane normal the resolver chose for the
    # FIRST reference (see docstring — no View.RightDirection fallback).
    dir_lines = f"__dimDir_{s} = __gn_{s}_0;"
    g_dimtype = op.get("dim_type")
    if g_dimtype is not None:
        dt_res = _annot_elem_res(g_dimtype, f"__dtel_{s}", ver, oid, "dim_type",
                              isolation)
        dimtype_decl = (f"{dt_res}\n"
                        f"DimensionType __dt_{s} = __dtel_{s} as DimensionType;\n"
                        f"if (__dt_{s} == null) {{ {refuse_stmt(oid, _cs('dim_type: элемент не DimensionType'), isolation)} }}")
        new_dim_call = (f"__el_{s} = doc.Create.NewDimension(__vw_{s}, __ln_{s}, __refs_{s}, __dt_{s});")
    else:
        dimtype_decl = ""
        new_dim_call = f"__el_{s} = doc.Create.NewDimension(__vw_{s}, __ln_{s}, __refs_{s});"
    named_faces = [i for i, sel in enumerate(refs) if faceref.is_face_sel(sel)]
    decl = (f"Dimension __el_{s} = null;\nView __vw_{s} = null;\n"
            + "\n".join(f"Element {v} = null;" for v in elem_vars) + "\n"
            + "\n".join(f"XYZ {v} = null;" for v in pt_vars) + "\n"
            + f"XYZ __dimDir_{s} = null;\n"
            + _dim_geom_helpers_cs(s))
    if named_faces:
        # Всё это появляется ТОЛЬКО при названной грани: без неё программа
        # обязана быть побайтово прежней (закон выключенного флага).
        # СЛИЯНИЕ 09.08: объявления волны размеров (точки, направление и
        # помощники геометрии) и объявления волны названных граней стоят
        # ОДНО ЗА ДРУГИМ, а не вместо друг друга — обе волны дописывали в один
        # блок `decl`, и любая победившая сторона унесла бы у другой имя,
        # которое её же POST-блок читает (правило области видимости: имя,
        # прочитанное свидетелем, обязано быть объявлено в `decl`).
        decl += (f"\nList<string> __fbWant_{s} = new List<string>();"
                 f"\nbool __fbOk_{s} = true;\n"
                 + faceref.walk_helpers_cs(s))
    create = (
        f"// create_dimension {cs_line_comment_fragment(oid)}\n{view_res}\n"
        f"doc.Regenerate();\n"
        f"{ref_array_lines}\n"
        f"ReferenceArray __refs_{s} = new ReferenceArray();\n{ref_appends}\n"
        f"{dir_lines}\n"
        f"XYZ __p0_{s} = {p0_cs};\n"
        f"Line __ln_{s};\n"
        f"try {{ __ln_{s} = Line.CreateBound(__p0_{s}, __p0_{s}.Add(__dimDir_{s}.Multiply(U(1000.0)))); }}\n"
        f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"line_at: вырожденная линия размера: \" + __ex_{s}.Message', isolation)} }}\n"
        f"{dimtype_decl}\n"
        f"try {{ {new_dim_call} }}\n"
        f"catch (Exception __ex2_{s}) {{ {refuse_stmt(oid, f'\"NewDimension: \" + __ex2_{s}.Message', isolation)} }}\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('NewDimension вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    requested_ids = ", ".join(f"{var}.Id.ToString()" for var in elem_vars)
    proj_pushes = "\n".join(
        f"    __proj_{s}.Add({pv}.DotProduct(__dimDir_{s}));" for pv in pt_vars)
    # topology: References bound to exactly the requested element ids
    # (SPEC witness triple — topology_ok; Reference.ElementId reports the
    # OWNING element for a geometric reference exactly as it did for the
    # retired element reference, confirmed via RevitAPI.xml).  geometry: the
    # measured value against the planes those references name (09.08 — see
    # the emitter docstring for why this became derivable and why no
    # tolerance is registered for it).
    post = [
        WitnessCheck(
            obligation_key="in_view", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.OwnerViewId.ToString() != __vw_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': dimension belongs to wrong view (topology)')});\n"),
            message="dimension belongs to wrong view (topology)", style="guard"),
        WitnessCheck(
            obligation_key="references",
            reader_cs=(
                f"    var __requested_{s} = new List<string>() {{ {requested_ids} }};\n"
                f"    var __actual_{s} = new List<string>(); bool __refsReadable_{s} = true;\n"
                f"    try {{ foreach (Reference __rr in __el_{s}.References) "
                f"if (__rr != null && __rr.ElementId != null) __actual_{s}.Add(__rr.ElementId.ToString()); }}\n"
                f"    catch {{ __refsReadable_{s} = false; }}\n"),
            verdict_cs=(
                f"    if (!__refsReadable_{s} || __actual_{s}.Count != __requested_{s}.Count ||\n"
                f"        !__actual_{s}.OrderBy(__x => __x, StringComparer.Ordinal).SequenceEqual(\n"
                f"            __requested_{s}.OrderBy(__x => __x, StringComparer.Ordinal)))\n"
                f"        __post.Add({_cs(oid + ': References do not match requested refs (topology)')});\n"),
            message="References do not match requested refs (topology)",
            style="guard"),
        WitnessCheck(
            obligation_key="value",
            reader_cs=(
                f"    var __proj_{s} = new List<double>();\n"
                f"{proj_pushes}\n"
                f"    __proj_{s}.Sort();\n"
                f"    var __expect_{s} = new List<double>();\n"
                f"    for (int __pi = 0; __pi + 1 < __proj_{s}.Count; __pi++)\n"
                f"        __expect_{s}.Add(__proj_{s}[__pi + 1] - __proj_{s}[__pi]);\n"
                f"    var __got_{s} = new List<double>(); bool __valRead_{s} = true;\n"
                f"    try\n"
                f"    {{\n"
                f"        if (__el_{s}.NumberOfSegments > 1)\n"
                f"            foreach (DimensionSegment __sg_{s} in __el_{s}.Segments)\n"
                f"                __got_{s}.Add(__sg_{s}.Value ?? double.NaN);\n"
                f"        else __got_{s}.Add(__el_{s}.Value ?? double.NaN);\n"
                f"    }}\n"
                f"    catch {{ __valRead_{s} = false; }}\n"
                f"    double __vtol_{s} = doc.Application.VertexTolerance;\n"),
            verdict_cs=(
                f"    bool __valBad_{s} = !__valRead_{s} || __got_{s}.Count != __expect_{s}.Count;\n"
                f"    if (!__valBad_{s})\n"
                f"        for (int __vi = 0; __vi < __expect_{s}.Count; __vi++)\n"
                f"            if (double.IsNaN(__got_{s}[__vi]) ||\n"
                f"                Math.Abs(__got_{s}[__vi] - __expect_{s}[__vi]) > __vtol_{s})\n"
                f"                __valBad_{s} = true;\n"
                f"    if (__valBad_{s})\n"
                f"        __post.Add({_cs(oid + ': measured value is not the distance between the referenced geometry (geometry)')});\n"),
            message="measured value is not the distance between the referenced geometry (geometry)",
            style="guard"),
    ]
    if named_faces:
        # ЧТО ЭТА ПРОВЕРКА УТВЕРЖДАЕТ, СЛОВО В СЛОВО: грань, которую резолвер
        # выбрал ДО коммита, присутствует среди `References` ПОСТРОЕННОГО
        # размера ПОСЛЕ коммита — сверка по `ConvertToStableRepresentation`,
        # то есть по подписи самой ГРАНИ, а не её владельца.
        #
        # ПОЧЕМУ ЭТОГО НЕ ГОВОРИТ СОСЕДНЯЯ ПРОВЕРКА `references`. Та читает
        # `Reference.ElementId` — ВЛАДЕЛЬЦА геометрической ссылки. Она
        # одинаково зелена, к какой бы грани того же элемента размер ни
        # привязался, и потому о названной грани не говорит НИЧЕГО.
        #
        # ПОЧЕМУ ОНА НЕ ВАКУУМНА: эмитируется только при названной грани,
        # значит `__fbWant` непуст по построению. Провалиться ей есть на чём,
        # и отказы, ради которых она написана, — настоящие: ссылка,
        # переассоциировавшаяся на другой подэлемент при регенерации, или
        # `NewDimension`, связавшийся не с тем, что ему передали.
        #
        # ЧЕГО ОНА НЕ ДОКАЗЫВАЕТ, И ЭТО СКАЗАНО ПРЯМО: что выбранная грань —
        # ТА, КОТОРУЮ ХОТЕЛ АВТОР. Наружная против внутренней компилятору
        # неизвестна; ось несёт ровно то, что может нести.
        #
        # НЕ ПРОВЕРЕНО ЖИВЬЁМ (09.08): равенство подписи ДО и ПОСЛЕ коммита
        # офлайн не устанавливается — Revit вправе переписать представление
        # при регенерации. Это ПЕРВАЯ живая проверка этой ветки; см. docs.
        post.append(WitnessCheck(
            obligation_key="named_face_binding",
            reader_cs=(
                f"    var __fbActual_{s} = new List<string>();\n"
                f"    bool __fbRead_{s} = __fbOk_{s};\n"
                f"    try {{ foreach (Reference __fbR in __el_{s}.References) "
                f"if (__fbR != null) "
                f"__fbActual_{s}.Add(__fbR.ConvertToStableRepresentation(doc)); }}\n"
                f"    catch {{ __fbRead_{s} = false; }}\n"),
            verdict_cs=(
                f"    if (!__fbRead_{s} || "
                f"!__fbWant_{s}.All(__fbW => __fbActual_{s}.Contains(__fbW)))\n"
                f"        __post.Add({_cs(oid + ': named face is not among the built dimension References (topology)')});\n"),
            message="named face is not among the built dimension References (topology)",
            style="guard"))
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ __rb[\"value_mm\"] = Math.Round(MM(__el_{s}.Value ?? 0.0), 1); }} catch {{ }}\n"
        f"    try {{ __rb[\"references\"] = __el_{s}.References.Size; }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_angular_dimension(op: dict, ver: str, stamp: str,
                            isolation: str = "atomic") -> tuple[str, str, str, str]:
    """create_angular_dimension: ``AngularDimension.Create(doc, view, Arc,
    IList<Reference>, DimensionType)``.

    VERSION AXIS: NONE.  Measured 09.08 against the six reference assemblies
    through the live Roslyn service (not against docs, and not against
    ``revit_api_db.json``): the 5-argument overload compiles on 2021, 2022,
    2023, 2024, 2025 AND 2026 — RevitAPI.xml dates it to 2017.  That is worth
    stating because the rest of the family does NOT behave this way:
    ``LinearDimension.Create`` / ``RadialDimension.Create`` /
    ``ArcLengthDimension.Create`` are 2025-2026 only (CS0103 "the name does
    not exist" on 2021-2024), and ``NewDiameterDimension`` /
    ``NewRadialDimension`` / ``NewAngularDimension`` / ``NewModelText`` live on
    ``FamilyItemFactory`` alone — ``doc.Create.NewDiameterDimension`` is CS1061
    on all six, only ``doc.FamilyCreate`` has them, i.e. FAMILY EDITOR ONLY and
    unusable for the project documents this compiler authors.

    THE ARC IS DERIVED, NOT ASKED FOR.  RevitAPI.xml constrains the call:
    "References should be: at least two, non parallel and RAYS OF THE ARC
    passed".  So the arc is not decoration — its centre must be the vertex
    where the two referenced planes meet, and its two endpoints must sit on
    those planes.  Asking the author for a centre and a radius would invite
    exactly the silently-wrong outcome this op exists to avoid (an arc that
    misses the vertex still compiles, and Revit would either refuse or measure
    something else).  Everything is therefore computed at RUNTIME from the two
    references the resolver already returns (point + in-view-plane unit
    normal, see :func:`_dim_geom_helpers_cs`) plus the ONE view-space point the
    author does give:

      * vertex — the 2x2 solve of the two plane equations in the view's own
        (Right, Up) basis.  Because both normals are unit and lie in the view
        plane, the determinant IS ``sin`` of the angle between them, so
        "parallel references" needs no invented epsilon: it is compared with
        ``doc.Application.AngleTolerance`` — the API's own "two angle
        measurements closer than this value are considered identical";
      * radius — the distance from that vertex to ``at``.  The author's point
        is the arc, not a hint about it;
      * WHICH pair of rays — the four ray combinations give four different
        angles, and ``at`` disambiguates: each ray is the in-plane direction
        along its own reference, signed toward ``at``.  This is the same law
        as create_dimension's line_at (one point, no extra parameter) and it
        means the op cannot silently measure the supplement of what the author
        pointed at.

    THE VALUE IS GATED, on the same principle as create_dimension (09.08): the
    sweep angle is known at creation time because we built the arc from the two
    rays, so ``Dimension.Value`` — radians, Revit's internal angle unit — has
    an independent expectation to be compared against, with
    ``Application.AngleTolerance`` read from the running application.  No
    number is invented and none is registered.  What is NOT proven offline is
    that Revit reports the sweep of the arc we passed rather than its
    supplement; if it does not, this witness makes the FIRST live run refuse
    loudly instead of returning a plausible angle — which is the whole point of
    gating it.

    Refusals are typed and op-bound (``refuse_stmt``): parallel references, an
    ``at`` that lands on the vertex, a degenerate arc, and a document with no
    default angular DimensionType each name themselves."""
    oid = op["id"]
    s = _safe(oid)
    view_res = _annot_view_res(op, s, ver, oid, isolation)
    refs = op["refs"]
    u, w = op["at"]
    at_cs = docspace.emit_view2d_to_xyz_cs(f"__vw_{s}", u, w)
    ref_lines = []
    elem_vars = []
    gref_vars = []
    for i, sel in enumerate(refs):
        rv = f"__rf_{s}_{i}"
        gv = f"__gref_{s}_{i}"
        pv = f"__gpt_{s}_{i}"
        nv = f"__gn_{s}_{i}"
        label = f"refs[{i}]"
        el_res = _annot_elem_res(sel, rv, ver, oid, label, isolation).replace(
            f"Element {rv} =", f"{rv} =", 1)
        # ``want`` stays null for BOTH refs here: create_dimension prefers a
        # PARALLEL second candidate because it measures a distance; an angle
        # needs the opposite, and a parallel pair is a typed refusal below.
        ref_lines.append(
            f"{el_res}\n"
            f"Reference {gv} = null;\n"
            f"__dimGeom_{s}({rv}, null, out {gv}, out {pv}, out {nv});\n"
            f"if ({gv} == null) {{ {refuse_stmt(oid, _cs(label + ': у элемента нет геометрической ссылки для размера'), isolation)} }}")
        elem_vars.append(rv)
        gref_vars.append(gv)
    g_dimtype = op.get("dim_type")
    if g_dimtype is not None:
        dt_res = _annot_elem_res(g_dimtype, f"__dtel_{s}", ver, oid, "dim_type",
                                 isolation)
        dimtype_decl = (
            f"{dt_res}\n"
            f"DimensionType __dt_{s} = __dtel_{s} as DimensionType;\n"
            f"if (__dt_{s} == null) {{ {refuse_stmt(oid, _cs('dim_type: элемент не DimensionType'), isolation)} }}")
    else:
        dimtype_decl = (
            f"DimensionType __dt_{s} = doc.GetElement(doc.GetDefaultElementTypeId(\n"
            f"    ElementTypeGroup.AngularDimensionType)) as DimensionType;\n"
            f"if (__dt_{s} == null) {{ {refuse_stmt(oid, _cs('dim_type: в документе нет типа углового размера по умолчанию — назовите dim_type явно'), isolation)} }}")
    decl = (f"AngularDimension __el_{s} = null;\nView __vw_{s} = null;\n"
            + "\n".join(f"Element {v} = null;" for v in elem_vars) + "\n"
            + "\n".join(f"XYZ __gpt_{s}_{i} = null;" for i in range(len(refs)))
            + "\n"
            + "\n".join(f"XYZ __gn_{s}_{i} = null;" for i in range(len(refs)))
            + "\n"
            + f"double __asw_{s} = 0.0;\n"
            + _dim_geom_helpers_cs(s))
    create = (
        f"// create_angular_dimension {cs_line_comment_fragment(oid)}\n{view_res}\n"
        f"doc.Regenerate();\n"
        + "\n".join(ref_lines) + "\n"
        f"XYZ __aR_{s} = __vw_{s}.RightDirection;\n"
        f"XYZ __aU_{s} = __vw_{s}.UpDirection;\n"
        f"XYZ __aO_{s} = __vw_{s}.Origin;\n"
        f"double __aa0_{s} = __gn_{s}_0.DotProduct(__aR_{s});\n"
        f"double __ab0_{s} = __gn_{s}_0.DotProduct(__aU_{s});\n"
        f"double __ac0_{s} = __gpt_{s}_0.Subtract(__aO_{s}).DotProduct(__gn_{s}_0);\n"
        f"double __aa1_{s} = __gn_{s}_1.DotProduct(__aR_{s});\n"
        f"double __ab1_{s} = __gn_{s}_1.DotProduct(__aU_{s});\n"
        f"double __ac1_{s} = __gpt_{s}_1.Subtract(__aO_{s}).DotProduct(__gn_{s}_1);\n"
        f"double __adet_{s} = __aa0_{s} * __ab1_{s} - __aa1_{s} * __ab0_{s};\n"
        f"if (Math.Abs(__adet_{s}) <= doc.Application.AngleTolerance) "
        f"{{ {refuse_stmt(oid, _cs('refs: ссылки параллельны — у угла нет вершины'), isolation)} }}\n"
        f"XYZ __avx_{s} = __aO_{s}\n"
        f"    .Add(__aR_{s}.Multiply((__ac0_{s} * __ab1_{s} - __ac1_{s} * __ab0_{s}) / __adet_{s}))\n"
        f"    .Add(__aU_{s}.Multiply((__aa0_{s} * __ac1_{s} - __aa1_{s} * __ac0_{s}) / __adet_{s}));\n"
        f"XYZ __aat_{s} = {at_cs};\n"
        f"XYZ __arv_{s} = __aat_{s}.Subtract(__avx_{s});\n"
        f"if (__arv_{s}.IsZeroLength()) "
        f"{{ {refuse_stmt(oid, _cs('at: точка совпала с вершиной угла — у дуги размера нулевой радиус'), isolation)} }}\n"
        f"XYZ __ad0_{s} = __gn_{s}_0.CrossProduct(__vw_{s}.ViewDirection).Normalize();\n"
        f"if (__ad0_{s}.DotProduct(__arv_{s}) < 0.0) __ad0_{s} = __ad0_{s}.Negate();\n"
        f"XYZ __ad1_{s} = __gn_{s}_1.CrossProduct(__vw_{s}.ViewDirection).Normalize();\n"
        f"if (__ad1_{s}.DotProduct(__arv_{s}) < 0.0) __ad1_{s} = __ad1_{s}.Negate();\n"
        f"XYZ __ay_{s} = __vw_{s}.ViewDirection.CrossProduct(__ad0_{s}).Normalize();\n"
        f"if (__ay_{s}.DotProduct(__ad1_{s}) < 0.0) __ay_{s} = __ay_{s}.Negate();\n"
        f"__asw_{s} = Math.Atan2(__ad1_{s}.DotProduct(__ay_{s}), __ad1_{s}.DotProduct(__ad0_{s}));\n"
        f"Arc __arc_{s};\n"
        f"try {{ __arc_{s} = Arc.Create(__avx_{s}, __arv_{s}.GetLength(), 0.0, __asw_{s}, __ad0_{s}, __ay_{s}); }}\n"
        f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"at: вырожденная дуга углового размера: \" + __ex_{s}.Message', isolation)} }}\n"
        f"{dimtype_decl}\n"
        f"IList<Reference> __arefs_{s} = new List<Reference>();\n"
        + "\n".join(f"__arefs_{s}.Add({gv});" for gv in gref_vars) + "\n"
        f"try {{ __el_{s} = AngularDimension.Create(doc, __vw_{s}, __arc_{s}, __arefs_{s}, __dt_{s}); }}\n"
        f"catch (Exception __ex2_{s}) {{ {refuse_stmt(oid, f'\"AngularDimension.Create: \" + __ex2_{s}.Message', isolation)} }}\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('AngularDimension.Create вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    requested_ids = ", ".join(f"{var}.Id.ToString()" for var in elem_vars)
    post = [
        WitnessCheck(
            obligation_key="in_view", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.OwnerViewId.ToString() != __vw_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': angular dimension belongs to wrong view (topology)')});\n"),
            message="angular dimension belongs to wrong view (topology)",
            style="guard"),
        WitnessCheck(
            obligation_key="references",
            reader_cs=(
                f"    var __requested_{s} = new List<string>() {{ {requested_ids} }};\n"
                f"    var __actual_{s} = new List<string>(); bool __refsReadable_{s} = true;\n"
                f"    try {{ foreach (Reference __rr in __el_{s}.References) "
                f"if (__rr != null && __rr.ElementId != null) __actual_{s}.Add(__rr.ElementId.ToString()); }}\n"
                f"    catch {{ __refsReadable_{s} = false; }}\n"),
            verdict_cs=(
                f"    if (!__refsReadable_{s} || __actual_{s}.Count != __requested_{s}.Count ||\n"
                f"        !__actual_{s}.OrderBy(__x => __x, StringComparer.Ordinal).SequenceEqual(\n"
                f"            __requested_{s}.OrderBy(__x => __x, StringComparer.Ordinal)))\n"
                f"        __post.Add({_cs(oid + ': References do not match requested refs (topology)')});\n"),
            message="References do not match requested refs (topology)",
            style="guard"),
        WitnessCheck(
            obligation_key="value",
            reader_cs=(
                f"    double __agot_{s} = double.NaN; bool __aRead_{s} = true;\n"
                f"    try {{ __agot_{s} = __el_{s}.Value ?? double.NaN; }}\n"
                f"    catch {{ __aRead_{s} = false; }}\n"),
            verdict_cs=(
                f"    if (!__aRead_{s} || double.IsNaN(__agot_{s}) ||\n"
                f"        Math.Abs(__agot_{s} - __asw_{s}) > doc.Application.AngleTolerance)\n"
                f"        __post.Add({_cs(oid + ': measured angle is not the sweep of the arc built from the references (geometry)')});\n"),
            message="measured angle is not the sweep of the arc built from the references (geometry)",
            style="guard"),
    ]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ __rb[\"value_deg\"] = Math.Round((__el_{s}.Value ?? 0.0) * 180.0 / Math.PI, 3); }} catch {{ }}\n"
        f"    try {{ __rb[\"references\"] = __el_{s}.References.Size; }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_tag(op: dict, ver: str, stamp: str,
              isolation: str = "atomic") -> tuple[str, str, str, str]:
    """create_tag: IndependentTag.Create — the annotation family's real
    version-drift (KIR_DOC_SPEC.md warning, confirmed against revitapidocs
    AND against the live compile-gate, which caught 3 real mistakes in an
    earlier draft of this emitter — CS0117 IndependentTagType doesn't exist,
    CS1061 GetTaggedLocalElementIds/TaggedLocalElementId each missing on one
    side of the version split, CS0103 a witness var never hoisted to decl):

      TagMode overload  (ALL versions 2021-2026, legacy but never removed):
        Create(doc, viewId, Reference, addLeader, TagMode, orientation, pnt)
        — 7 args, NO explicit type id; per a Building Coder / API-forum
        source, this overload picks "a default tag type depending on the
        element being tagged" INSIDE Revit — no GetDefaultElementTypeId
        guess needed, so THIS is the omitted-tag_type path on every version.
      symId overload    (>=2022 ONLY; revitapidocs 2021 404s this overload):
        Create(doc, symId, viewId, Reference, addLeader, orientation, pnt)
        — 7 args, explicit tag TYPE id, no TagMode. Used ONLY when tag_type
        is given; requesting tag_type on <=2021 is a typed E-VERSION refusal
        (the API slot for it does not exist there — not a silent ignore).

    Witness API also drifts (2022 is the ONLY version where BOTH exist):
      <=2021: TaggedLocalElementId (property; GetTaggedLocalElementIds 404s)
      >=2023: GetTaggedLocalElementIds() (TaggedLocalElementId was REMOVED,
              not just deprecated — a runtime try/catch of both does NOT
              compile on either exclusive side, so this branches in PYTHON,
              emitting one call per version, never both in one C# body)."""
    oid = op["id"]
    s = _safe(oid)
    view_res = _annot_view_res(op, s, ver, oid, isolation)
    tgt_res = _annot_elem_res(op["target"], f"__tg_{s}", ver, oid, "target",
                          isolation).replace(
        f"Element __tg_{s} =", f"__tg_{s} =")
    u, w = op["at"]
    pt_cs = docspace.emit_view2d_to_xyz_cs(f"__vw_{s}", u, w)
    leader = "true" if op.get("leader") else "false"
    g_tagtype = op.get("tag_type")
    # ДВА КЛАССА МАРОК, И РАЗЛИЧАЕТ ИХ ЦЕЛЬ, А НЕ АВТОР (13.08.2026).
    # `__el_` перестал быть `IndependentTag`: марка помещения, площади и
    # пространства — `SpatialElementTag`, у которого другой создатель и
    # другая поверхность чтения. Ветка стоит В C#, а не здесь, и это не
    # выбор стиля: у `create_tag.target` НЕТ пула (`ref_kinds=ELEMENT`),
    # цель приходит как `element_id`/`ref`, и класс цели питону на эмиссии
    # НЕИЗВЕСТЕН ПО ПОСТРОЕНИЮ. Спрашивать про него автора значило бы
    # завести второй источник истины, способный разойтись с целью.
    decl = (f"Element __el_{s} = null; Element __tg_{s} = null;\n"
            f"View __vw_{s} = null;")
    if g_tagtype is not None:
        if ver <= "2021":
            raise KirRefusal([Diagnostic(
                code=EMIT_UNSUPPORTED, op_id=oid, field_name="tag_type",
                message_ru=f"tag_type (явный тип марки) недоступен на Revit {ver} — "
                           "IndependentTag.Create(symId,...) появился в 2022; "
                           "опустите tag_type для версии по умолчанию по категории")])
        type_decl = _annot_elem_res(g_tagtype, f"__ttel_{s}", ver, oid, "tag_type",
                                isolation)
        create_call = (
            f"__el_{s} = IndependentTag.Create(doc, __ttel_{s}.Id, __vw_{s}.Id, "
            f"new Reference(__tg_{s}), {leader}, TagOrientation.Horizontal, {pt_cs});")
    else:
        type_decl = ""
        create_call = (
            f"__el_{s} = IndependentTag.Create(doc, __vw_{s}.Id, new Reference(__tg_{s}), "
            f"{leader}, TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, {pt_cs});")
    # With a leader Revit interprets Create's point as its end; KIR's `at`
    # denotes the head. Set that head explicitly before the native witness.
    if op.get("leader"):
        create_call += (f"\n        if (__el_{s} != null) "
                        f"((IndependentTag)__el_{s}).TagHeadPosition = {pt_cs};")
    # ═══ ПРОСТРАНСТВЕННАЯ МАРКА ═══════════════════════════════════════════
    #
    # ЗАЧЕМ. Замерено 13.08.2026 на `len_ar_me_r24_v1` (второе жилое здание,
    # чтение полное, все десять стадий): 7 067 элементов — марки рода
    # `spatial`, крупнейшая причина `unsupported_forward_signature` на этом
    # здании. Обратный ход снимал их с 30.07 и честно отказывал в подъёме
    # (`lift.py`: «прямой ход строит марку единственным способом»). Это была
    # дыра ПРЯМОГО хода, а не чтения.
    #
    # ЧЕМ СТРОИТСЯ — установлено КОМПИЛЯЦИЕЙ против эталонных сборок, а не
    # документацией, и в этом семействе это принципиально: `tag_extract`
    # несёт случай #78, где `SpatialElementTag.SpatialElement` описан в шести
    # XML и отсутствует в шести DLL. Индекса ловушек в дереве НЕТ вовсе —
    # сказано именно так, потому что «индекса нет» и «члена нет» разные
    # факты. Замер 13.08, все шесть версий:
    #
    #     NewRoomTag(LinkElementId, UV, ElementId)   6/6   контроль:
    #     NewSpaceTag(Space, UV, View)               6/6     NewRoomTag(UV)
    #     NewAreaTag(ViewPlan, Area, UV)             6/6     6/6 CS7036
    #     RoomTag.HasLeader (чтение И запись)        6/6     NewNonesuchTagZZZ
    #     RoomTag.ChangeTypeId · Room.Location       6/6     6/6 CS1061
    #
    # ЧЕГО МЫ НЕ ЗНАЕМ И ГДЕ ЭТО СТОРОЖИТСЯ. В КАКИХ ОСЯХ `UV` у
    # `NewRoomTag` — компиляцией не устанавливается, живьём не проверено.
    # Догадка здесь была бы молча смещённой маркой, поэтому точка НЕ
    # додумывается: свидетель `head_at` читает `TagHeadPosition` обратно ТЕМ
    # ЖЕ базисом вида, каким она клалась, и неверная ось даёт ТИПИЗИРОВАННОЕ
    # НАРУШЕНИЕ, а не тихий сдвиг. Оп уезжает НЕПРОВЕРЕННЫМ живьём, и это
    # сказано вслух, а не спрятано.
    spatial_create = (
        f"    var __se_{s} = __tg_{s} as SpatialElement;\n"
        f"    if (__se_{s} != null)\n    {{\n"
        # ОТКАЗ 1: маркировать нечего. Неразмещённое помещение Ревит
        # маркирует МУСОРОМ, а не ошибкой — потому проверка наша.
        f"        if (__se_{s}.Location == null || __se_{s}.Area <= 0.0)\n"
        f"            {{ {refuse_stmt(oid, _cs('цель — пространственный элемент, который НЕ РАЗМЕЩЁН (нет Location или нулевая площадь): маркировать нечего'), isolation)} }}\n"
        # ОТКАЗ 2: выноска. Причина унесена дословно из lift.py — у марки С
        # выноской точка означает КОНЕЦ ВЫНОСКИ, а мы храним и сверяем
        # ГОЛОВУ. Молчаливый увод головы на длину выноски по умолчанию
        # сравнением по голове не ловится.
        # СТОРОЖ ВЫНОСКИ ИСПУСКАЕТСЯ ТОЛЬКО КОГДА ВЫНОСКА ЗАПРОШЕНА.
        # Первая редакция писала `if (false)` при `leader` по умолчанию —
        # константно-ложный сторож, то есть мёртвая ветка по построению.
        # Ровно та форма, которую `translation_cert.analyze_witness_cs`
        # отвергает у свидетелей; здесь она стояла бы в создании, куда
        # сертификат не смотрит, и жила бы незамеченной.
        + (f"        {refuse_stmt(oid, _cs('leader:true у пространственной марки в этой волне отказан: точка означала бы КОНЕЦ ВЫНОСКИ, а сверяется ГОЛОВА (дословно RevitAPI.xml про седьмой аргумент) — молчаливый сдвиг вместо марки'), isolation)}\n"
           if op.get("leader") else "")
        + (
        # 🔴 ЕДИНИЦЫ. ПОЧИНЕНО 04.09.2026, БЫЛИ СЫРЫЕ МИЛЛИМЕТРЫ.
        # Здесь стояло `new UV({round(u, 4)}, {round(w, 4)})` — то есть
        # `new UV(3000.0, 800.0)` при `at: [3000, 800]`. Ревит читает `UV` во
        # ВНУТРЕННИХ единицах (футах), значит марка уезжала примерно в 304.8
        # раза. Довод не догадка, а ЧИСЛО ИЗ ЭТОГО ЖЕ ЭТАЛОНА: соседняя ветка
        # ТОГО ЖЕ опа печатала для ТОЙ ЖЕ точки `at` строкой ниже
        # `...Multiply(U(3000.0))` (`auth_annotation.golden.cs`: 360 против
        # 380), и `room_emit`/`NewRoom`/`NewSpace` — те же `doc.Create` и тот
        # же `UV` — тоже идут через `U()`. Один закон, два носителя, два
        # вердикта: разошлись ровно так, как расходятся молча.
        #
        # ОСЬ ЭТИМ НЕ РЕШЕНА И РЕШАТЬСЯ НЕ ДОЛЖНА. Шапка выше говорит: в каких
        # осях `UV` у `NewRoomTag`, компиляцией не устанавливается. Единицы —
        # другой вопрос: перевод мм → внутренние однозначен и от выбора оси не
        # зависит. Ось по-прежнему сторожит свидетель `head_at`.
        f"        var __uv_{s} = {docspace.emit_view2d_to_uv_cs(u, w)};\n"
        f"        var __rm_{s} = __se_{s} as Autodesk.Revit.DB.Architecture.Room;\n"
        f"        var __ar_{s} = __se_{s} as Area;\n"
        f"        var __sc_{s} = __se_{s} as Autodesk.Revit.DB.Mechanical.Space;\n"
        f"        if (__rm_{s} != null)\n"
        f"            __el_{s} = doc.Create.NewRoomTag(new LinkElementId(__rm_{s}.Id), __uv_{s}, __vw_{s}.Id);\n"
        f"        else if (__sc_{s} != null)\n"
        f"            __el_{s} = doc.Create.NewSpaceTag(__sc_{s}, __uv_{s}, __vw_{s});\n"
        f"        else if (__ar_{s} != null)\n"
        f"        {{\n"
        # ОТКАЗ 3: площадь маркируется ТОЛЬКО на плане, и отказ называет
        # фактический род вида, а не «неверный вид».
        f"            var __vp_{s} = __vw_{s} as ViewPlan;\n"
        f"            if (__vp_{s} == null)\n"
        f"                {{ {refuse_stmt(oid, '"марка площади требует вид-план (ViewPlan), а in_view — " + __vw_' + s + '.ViewType.ToString()', isolation)} }}\n"
        f"            __el_{s} = doc.Create.NewAreaTag(__vp_{s}, __ar_{s}, __uv_{s});\n"
        f"        }}\n"
        # ОТКАЗ 4: род пространственного элемента, которого мы не знаем.
        # Молчать нельзя — иначе `__el_` останется null и причина потеряется.
        f"        else\n"
        f"            {{ {refuse_stmt(oid, '"цель — SpatialElement рода " + __ClassName(__se_' + s + ') + ", а марки строятся только для помещения, площади и пространства"', isolation)} }}\n"
        # ТИП МАРКИ у пространственной ставится ПОСЛЕ создания
        # (`ChangeTypeId`, 6/6): у `NewRoomTag`/`NewSpaceTag`/`NewAreaTag`
        # слота под тип нет ни на одной версии. На 2021 `tag_type` отказан
        # ВЫШЕ, на эмиссии, и здесь его просто нет — поведение 2021 не
        # тронуто ни на байт, и место отказа по версии осталось одно.
        + (f"        if (__el_{s} != null)\n"
           f"            {{ try {{ __el_{s}.ChangeTypeId(__ttel_{s}.Id); }}\n"
           f"              catch (Exception __tex_{s}) {{ {refuse_stmt(oid, '"тип марки не принят пространственной маркой: " + __tex_' + s + '.Message', isolation)} }} }}\n"
           if g_tagtype is not None else "")
        + (
        f"    }}\n    else\n    {{\n        {create_call}\n    }}\n")))

    create = (
        f"// create_tag {cs_line_comment_fragment(oid)}\n{view_res}\n{tgt_res}\n{type_decl}\n"
        f"try {{\n{spatial_create}}}\n"
        f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"IndependentTag.Create: \" + __ex_{s}.Message', isolation)} }}\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('IndependentTag.Create вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # VIEW-BINDING LAW (semantic_ok): the tag's own tagged-element id must
    # equal target — this is the witness that target was actually visible in
    # in_view (Revit refuses to create/associate a tag on an invisible
    # element; a mismatch here is the typed proof, not an opinion). The
    # readback API itself drifts (see docstring) — branched in PYTHON, one
    # call emitted per version, never a dual try/catch of both members.
    if ver >= "2022":
        # >=2022: the multi-target readback exists (2022 also still compiles the
        # deprecated TaggedLocalElementId property, but the new member is correct
        # on both 2022 and 2023+ so there is no need to branch here).
        #
        # GetTaggedLocalElement*S*, not ...ElementIds, and that is not a style
        # choice: `GetTaggedLocalElementIds()` returns `ISet<ElementId>`, and on
        # net48 `ISet<>` lives in `System.dll`, which the DEPLOYED plugin does
        # not reference — CS0012, measured live on 2026-08-04 (the decompile tag
        # stage died on it). The sibling member returns `ICollection<Element>`
        # (mscorlib), exists on the same 2022-2026, and answers the same
        # question. See `kir/decompile/tag_extract.py:_TAG_TARGET_2022_CS`.
        bound_expr = (
            f"    try\n    {{\n"
            f"        foreach (Element __tel in __itg_{s}.GetTaggedLocalElements())\n"
            f"            if (__tel != null && __tel.Id.ToString() == __tg_{s}.Id.ToString()) {{ __bound_{s} = true; break; }}\n"
            f"    }} catch {{ }}\n")
    else:  # <=2021: the multi-target readback does not exist yet
        bound_expr = (
            f"    try {{ __bound_{s} = __itg_{s}.TaggedLocalElementId.ToString() == __tg_{s}.Id.ToString(); }}\n"
            f"    catch {{ }}\n")
    htol = tolerance("create_tag", "head_mm")
    post = [
        WitnessCheck(
            obligation_key="in_view", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.OwnerViewId.ToString() != __vw_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': tag belongs to wrong view (topology)')});\n"),
            message="tag belongs to wrong view (topology)", style="guard"),
        WitnessCheck(
            obligation_key="target_bound",
            # СВЯЗЬ ЧИТАЕТСЯ У ТОГО КЛАССА, КОТОРЫЙ ЕЁ НЕСЁТ. У базы
            # `SpatialElementTag` свойства цели НЕТ в поставляемых сборках
            # (случай #78: описано в шести XML, CS1061 в шести DLL), поэтому
            # цель берётся у подкласса — ровно так же, как это сделала
            # боковая стадия чтения 30.07.
            reader_cs=(f"    bool __bound_{s} = false;\n"
                       f"    var __itg_{s} = __el_{s} as IndependentTag;\n"
                       f"    var __rtg_{s} = __el_{s} as Autodesk.Revit.DB.Architecture.RoomTag;\n"
                       f"    var __atg_{s} = __el_{s} as AreaTag;\n"
                       f"    var __stg_{s} = __el_{s} as Autodesk.Revit.DB.Mechanical.SpaceTag;\n"
                       f"    if (__rtg_{s} != null)\n"
                       f"    {{ try {{ __bound_{s} = __rtg_{s}.Room != null && __rtg_{s}.Room.Id.ToString() == __tg_{s}.Id.ToString(); }} catch {{ }} }}\n"
                       f"    else if (__atg_{s} != null)\n"
                       f"    {{ try {{ __bound_{s} = __atg_{s}.Area != null && __atg_{s}.Area.Id.ToString() == __tg_{s}.Id.ToString(); }} catch {{ }} }}\n"
                       f"    else if (__stg_{s} != null)\n"
                       f"    {{ try {{ __bound_{s} = __stg_{s}.Space != null && __stg_{s}.Space.Id.ToString() == __tg_{s}.Id.ToString(); }} catch {{ }} }}\n"
                       f"    else if (__itg_{s} != null)\n" + bound_expr +
                       f"    else\n"
                       f"    {{ }}\n"),
            verdict_cs=(
                f"    if (!__bound_{s})\n"
                f"        __post.Add({_cs(oid + ': марка не связана с target (semantic, VIEW-BINDING LAW: target не виден в in_view?)')});\n"),
            message="марка не связана с target (semantic)", style="guard"),
        WitnessCheck(
            obligation_key="head_at", reader_cs="",
            verdict_cs=(
                f"    try\n    {{\n"
                # ОДИН закон обратного хода на всё семейство (docspace):
                # байты те же, что были набраны здесь руками.
                + f"        XYZ __head_{s} = (__el_{s} as IndependentTag) != null\n"
                  f"            ? ((IndependentTag)__el_{s}).TagHeadPosition\n"
                  f"            : ((SpatialElementTag)__el_{s}).TagHeadPosition;\n"
                + docspace.emit_xyz_to_view2d_cs(
                    f"__vw_{s}", f"__head_{s}", f"__rel_{s}",
                    f"__ou_{s}", f"__ow_{s}", indent=" " * 8) +
                f"        if (Math.Abs(__ou_{s} - {round(u, 2)}) > {htol} || Math.Abs(__ow_{s} - {round(w, 2)}) > {htol})\n"
                f"            __post.Add({_cs(oid + ': tag head differs from at (geometry)')});\n"
                f"    }} catch {{ __post.Add({_cs(oid + ': tag head unreadable (geometry)')}); }}\n"),
            message="tag head differs from at (geometry)",
            tol=htol, style="else_block"),
    ]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    __rb[\"tagged_id\"] = __tg_{s}.Id.ToString();\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_text(op: dict, ver: str, stamp: str,
               isolation: str = "atomic") -> tuple[str, str, str, str]:
    """create_text: TextNote.Create(doc, viewId, XYZ, string, ElementId typeId)
    — STABLE across 2021-2026 (confirmed present since 2017 on revitapidocs;
    no per-version branch). text_type omitted -> doc default TextNoteType
    (IN_EMIT_DEFAULT pattern, same as create_wall's `type`).

    width_mm (optional, KIR_DOC_SPEC.md "размер-на-листе через view_scale"):
    TextNote.Width is the ONE per-instance sheet-space size Revit actually
    exposes (font HEIGHT is TextNoteType-owned — same value for every
    instance of that type — so it is NOT modeled as a create_text param,
    flagged in the module docstring, not silently approximated). Uses the
    6-arg TextNote.Create(doc, viewId, XYZ, double width, string, typeId)
    overload — EMPIRICALLY probed against the live compile-gate on all 6
    versions (2021-2026, all OK) despite revitapidocs listing this overload
    as "updated" on several years (2022/2024/2025/2025.3/2027) — a
    behavior-doc note, not a signature break, confirmed by the gate itself
    rather than trusted from prose alone. width_mm is compiler-owned
    size-from-intent: `sheet_mm x view_scale = model_mm`, the SAME formula
    docspace.view_scale_to_model_mm proves in pure Python, but view_scale is
    only known AFTER in_view resolves, so it is read from View.Scale AT
    RUNTIME here (never hardcoded, same discipline as the view basis itself).
    View.Scale is "meaningless for perspective views" (revitapidocs) — a
    perspective in_view with width_mm given is a typed runtime refusal, not
    a silently-wrong width.

    leader_to (optional): TextNote has no leader-to-element API on Create
    itself — v1 FLAGGED LIMITATION: leader_to is accepted and VIEW-BINDING-
    checked (the target must resolve+be an Element) but the leader itself is
    added via AddLeader(TextNoteLeaderTypes.TNLT_STRAIGHT_L) (the gate caught
    the parameterless AddLeader() as CS7036 — TextNoteLeaderTypes is a
    required arg, confirmed via a live building-coder AddLeader(TNLT_STRAIGHT_L)
    example) + leader end point set to the target's location, a best-effort
    placement (Revit's own leader UX free-drags the end; there is no API
    that "snaps" a leader end onto an arbitrary element)."""
    oid = op["id"]
    s = _safe(oid)
    view_res = _annot_view_res(op, s, ver, oid, isolation)
    u, w = op["at"]
    pt_cs = docspace.emit_view2d_to_xyz_cs(f"__vw_{s}", u, w)
    content = op["content"]
    g_texttype = op.get("text_type")
    if g_texttype is not None:
        type_decl = _annot_elem_res(g_texttype, f"__ttel_{s}", ver, oid, "text_type",
                                isolation)
        type_id_expr = f"__ttel_{s}.Id"
    else:
        type_decl = (f"ElementId __ttid_{s} = doc.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType);\n"
                    f"if (__ttid_{s} == null || __ttid_{s} == ElementId.InvalidElementId)\n"
                    f"    {{ {refuse_stmt(oid, _cs('в документе нет типа текста по умолчанию'), isolation)} }}")
        type_id_expr = f"__ttid_{s}"
    width_mm = op.get("width_mm")
    if width_mm is not None:
        # __wmm_<s> is re-read by the post width check — assignment here,
        # declaration in decl (scope contract).
        width_decl = (
            f"if (__vw_{s}.Scale <= 0)\n"
            f"    {{ {refuse_stmt(oid, _cs('width_mm: масштаб вида не определён (перспективный вид?) — размер-на-листе неприменим'), isolation)} }}\n"
            f"__wmm_{s} = {round(width_mm, 2)} * (double)__vw_{s}.Scale;  // sheet_mm x view_scale = model_mm (view_scale read at RUNTIME)")
        create_call = (
            f"try {{ __el_{s} = TextNote.Create(doc, __vw_{s}.Id, {pt_cs}, U(__wmm_{s}), {_cs(content)}, {type_id_expr}); }}\n"
            f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"TextNote.Create: \" + __ex_{s}.Message', isolation)} }}")
    else:
        width_decl = ""
        create_call = (
            f"try {{ __el_{s} = TextNote.Create(doc, __vw_{s}.Id, {pt_cs}, {_cs(content)}, {type_id_expr}); }}\n"
            f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"TextNote.Create: \" + __ex_{s}.Message', isolation)} }}")
    leader_to = op.get("leader_to")
    leader_decl = ""
    if leader_to is not None:
        # assignment form: the post leader check re-reads __ltel_<s>'s bbox,
        # so its declaration hoists to decl (scope contract).
        lt_res = _annot_elem_res(
            leader_to, f"__ltel_{s}", ver, oid, "leader_to", isolation).replace(
            f"Element __ltel_{s} =", f"__ltel_{s} =", 1)
        leader_decl = (
            f"{lt_res}\n"
            f"try\n{{\n"
            f"    __el_{s}.AddLeader(TextNoteLeaderTypes.TNLT_STRAIGHT_L);\n"
            f"    var __ldrs_{s} = __el_{s}.GetLeaders();\n"
            f"    if (__ldrs_{s} != null && __ldrs_{s}.Count > 0)\n"
            f"    {{\n"
            f"        var __ld_{s} = __ldrs_{s}[__ldrs_{s}.Count - 1];\n"
            f"        var __ltbb_{s} = __ltel_{s}.get_BoundingBox(__vw_{s});\n"
            f"        if (__ltbb_{s} != null)\n"
            f"        {{\n"
            f"            var __ltmid_{s} = (__ltbb_{s}.Min + __ltbb_{s}.Max) * 0.5;\n"
            f"            __ld_{s}.End = __ltmid_{s};\n"
            f"        }}\n"
            f"    }}\n"
            f"}} catch {{ }}  // best-effort leader placement (no snap-to-element API)")
    decl = f"TextNote __el_{s} = null;\nView __vw_{s} = null;"
    if width_mm is not None:
        decl += f"\ndouble __wmm_{s} = 0.0;"
    if leader_to is not None:
        decl += f"\nElement __ltel_{s} = null;"
    create = (
        f"// create_text {cs_line_comment_fragment(oid)}\n{view_res}\n{type_decl}\n{width_decl}\n"
        f"{create_call}\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('TextNote.Create вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}") + "\n"
        + leader_decl)
    width_check = ""
    width_witness = ""
    if width_mm is not None:
        width_check = (
            f"    try {{ if (Math.Abs(MM(__el_{s}.Width) - __wmm_{s}) > __wmm_{s} * 0.15 + 5.0)\n"
            f"        __post.Add({_cs(oid + ': width_mm сильно разошёлся с фактической шириной (geometry, Revit подгоняет под контент)')}); }}\n"
            f"    catch {{ __post.Add({_cs(oid + ': width unreadable (geometry)')}); }}\n")
        width_witness = f"    try {{ __rb[\"width_mm\"] = Math.Round(MM(__el_{s}.Width), 1); }} catch {{ }}\n"
    leader_check = ""
    if leader_to is not None:
        leader_check = (
            f"    bool __leaderTargetVisible_{s} = false; bool __leaderOk_{s} = false;\n"
            f"    try\n    {{\n"
            f"        var __ltbb2_{s} = __ltel_{s}.get_BoundingBox(__vw_{s});\n"
            f"        if (__ltbb2_{s} != null)\n"
            f"        {{\n"
            f"            __leaderTargetVisible_{s} = true;\n"
            f"            var __ltmid2_{s} = (__ltbb2_{s}.Min + __ltbb2_{s}.Max) * 0.5;\n"
            f"            var __ldrs2_{s} = __el_{s}.GetLeaders();\n"
            f"            if (__ldrs2_{s} != null) foreach (var __ldr2 in __ldrs2_{s})\n"
            f"                if (__ldr2.End.DistanceTo(__ltmid2_{s}) <= U(10.0)) "
            f"{{ __leaderOk_{s} = true; break; }}\n"
            f"        }}\n"
            f"    }} catch {{ }}\n"
            f"    if (!__leaderTargetVisible_{s})\n"
            f"        __post.Add({_cs(oid + ': leader target not visible in view (semantic, VIEW-BINDING LAW)')});\n"
            f"    if (!__leaderOk_{s})\n"
            f"        __post.Add({_cs(oid + ': leader endpoint does not match target (geometry)')});\n")
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="in_view", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.OwnerViewId.ToString() != __vw_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': text belongs to wrong view (topology)')});\n"),
            message="text belongs to wrong view (topology)", style="guard"),
        WitnessCheck(
            obligation_key="content", reader_cs="",
            verdict_cs=(
                f"    if ((__el_{s}.Text ?? \"\").TrimEnd('\\r', '\\n') != "
                f"{_cs(content)}.TrimEnd('\\r', '\\n'))\n"
                f"        __post.Add({_cs(oid + ': content не совпадает после чтения (semantic)')});\n"),
            message="content не совпадает после чтения (semantic)", style="guard"),
    ]
    if width_check:
        checks.append(WitnessCheck(
            obligation_key="width", reader_cs="",
            verdict_cs=width_check,
            message="width_mm сильно разошёлся с фактической шириной (geometry)",
            style="guard"))
    attol = tolerance("create_text", "location_mm")
    checks.append(WitnessCheck(
        obligation_key="at", reader_cs="",
        verdict_cs=(
            f"    try\n    {{\n"
            f"        var __loc_{s} = __el_{s}.Coord;\n"
            # ОДИН закон обратного хода на всё семейство (docspace).
            + docspace.emit_xyz_to_view2d_cs(
                f"__vw_{s}", f"__loc_{s}", f"__rel_{s}",
                f"__ou_{s}", f"__ow_{s}", indent=" " * 8) +
            f"        if (Math.Abs(__ou_{s} - {round(u, 2)}) > {attol} || Math.Abs(__ow_{s} - {round(w, 2)}) > {attol})\n"
            f"            __post.Add({_cs(oid + ': at смещена относительно заданной точки вида (geometry)')});\n"
            f"    }} catch {{ __post.Add({_cs(oid + ': text position unreadable (geometry)')}); }}\n"),
        message="at смещена относительно заданной точки вида (geometry)",
        tol=attol, style="else_block"))
    if leader_check:
        checks.append(WitnessCheck(
            obligation_key="leader", reader_cs="",
            verdict_cs=leader_check,
            message="leader endpoint does not match target (geometry)",
            style="guard"))
    post = checks
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ __rb[\"content\"] = __el_{s}.Text; }} catch {{ }}\n"
        + width_witness +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


def _emit_filled_region(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, str, str]:
    """create_filled_region: ``FilledRegion.Create(doc, typeId, viewId,
    IList<CurveLoop>)`` — 6/6 по эталонным сборкам, без единой развилки версий.

    ДВА ПОДЪЯЗЫКА В ОДНОМ ОПЕ, И ШОВ МЕЖДУ НИМИ — ЕДИНСТВЕННОЕ, ЧТО ЗДЕСЬ
    НЕТРИВИАЛЬНО. CONTOUR отдаёт канонические рёбра (вся дуговая арифметика уже
    посчитана в питоне), docspace отдаёт базис вида. Петля собирается ТЕМ ЖЕ
    ``contour.emit_loop_cs``, но с форматтером точки, который кладёт [u,v] в
    плоскость вида, — потому что ``FilledRegion.Create`` отвергает петлю, не
    параллельную эскизной плоскости вида (RevitAPI.xml дословно), а прежний
    форматтер строит в плоскости XY модели, то есть верен только на планах.
    Одна формула на прямой ход живёт в ``docspace._view2d_to_xyz_expr``, и
    обратный ход свидетеля берётся оттуда же — тождественность, а не сходство.

    ТРИ ОТКАЗА ДО ВСЯКОЙ C#, каждый — потому что иначе получился бы молчаливо
    неверный результат, а не ошибка:

    * ``in_view: ref`` — общий отказ семейства (``_annot_view_res``): ни один
      оп KIR не создаёт View, значит ``as View`` не скомпилировался бы никогда;
    * ``at_grid`` внутри контура — адрес от осей даёт МОДЕЛЬНЫЕ координаты, а
      поле объявлено видовым. На плане с мировым базисом числа совпадают, на
      разрезе — означают другое место; ровно путаница пространств, которую
      docspace делает невыразимой для точек, и она не должна протекать через
      контур;
    * координата вне рабочего предела — тот же ``check_pt_view2d``, что стоит у
      ``at`` марки и текста, применённый к вершинам ОПУЩЕННОГО контура (у
      CONTOUR собственного предела координат нет вовсе).

    Тип: опущенный разрешается документным умолчанием
    (``ElementTypeGroup.FilledRegionType`` — компилируется 6/6), названный —
    пулом ``filled_region_types``. Обе ветки проходят
    ``FilledRegion.IsValidFilledRegionTypeId`` ДО вызова: он дешевле
    исключения внутри транзакции и называет ошибку точнее.
    ``IsRegionCreationEnabledInView`` для симметрии НЕ используется — он описан
    в RevitAPI.xml и отсутствует во всех шести DLL (CS0117, замер 09.08).
    """
    from kir import contour as C
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    holes = region["holes"]
    view_res = _annot_view_res(op, s, ver, oid, isolation)
    # Адрес от осей — модельная рамка в видовом поле. Отказ до эмиссии.
    if "at_grid" in repr(op.get("contour")):
        raise KirRefusal([Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name="contour",
            got=op.get("contour"),
            message_ru=(
                "contour: адрес от осей (at_grid) недопустим у заливки — "
                "точки контура задаются в ПРОСТРАНСТВЕ ВИДА ([u,v] мм от "
                "View.Origin вдоль Right/Up), а ось живёт в модели: на плане "
                "эти числа совпали бы, на разрезе означали бы другое место. "
                "Дайте литеральные [u,v]"))])
    # Предел координат — тот же, что у `at` марки/текста (docspace), потому что
    # это то же самое пространство. У самого CONTOUR предела координат нет.
    bound_diags: list[Diagnostic] = []
    for label, edges in ([("contour.outer", region["outer"])]
                         + [(f"contour.holes[{hi}]", h)
                            for hi, h in enumerate(holes)]):
        for p0, _p1, _b in edges:
            docspace.check_pt_view2d(list(p0), oid, label, bound_diags)
    if bound_diags:
        # СРЕЗ УБРАН 13.08, и он был ЕДИНСТВЕННЫМ на 76 мест `raise
        # KirRefusal` во всём дереве. Остальные 75 отдают список целиком, а
        # квитанция ограничивает показ САМА и называет остаток
        # (`_diagnostics_total(out.diagnostics, 8)` в `serving.py:115`).
        #
        # ЧЕМ ЭТОТ СРЕЗ БЫЛ ХУЖЕ ОБЫЧНОГО УСЕЧЕНИЯ: лекарство от этого класса
        # уже написано (12.08, `23be2d1f`) и стоит У ПОТРЕБИТЕЛЯ — оно считает,
        # сколько диагностик ЕМУ ДАЛИ. Срез стоял У ПРОИЗВОДИТЕЛЯ, поэтому
        # потребитель честно видел одну из одной и молчал об остатке ПРАВИЛЬНО.
        # Модель получала «точка вне границ», чинила её, слала заново и
        # получала следующую — по одному ходу на точку, без единого признака,
        # что их было больше.
        #
        # Контур может дать много таких точек сразу: проверяется КАЖДАЯ вершина
        # внешнего обхода и каждого отверстия, а вылет обычно системный (не та
        # система координат), то есть валит их все разом — именно тот случай,
        # где показать одну дороже всего.
        raise KirRefusal(bound_diags)
    g_type = _gid(op, "type") if isinstance(op.get("type"), dict) \
        and "__grounded__" in op["type"] else None
    if g_type and g_type.get("in_emit") == IN_EMIT_DEFAULT:
        type_res = (
            f"__frt_{s} = doc.GetElement(doc.GetDefaultElementTypeId("
            f"ElementTypeGroup.FilledRegionType)) as FilledRegionType;\n"
            f"if (__frt_{s} == null) {{ {refuse_stmt(oid, _cs('в документе нет типа заливки по умолчанию — назовите type'), isolation)} }}")
    else:
        type_res = (
            f"__frt_{s} = doc.GetElement({_eid(g_type['id'], ver, oid)}) as FilledRegionType;\n"
            f"if (__frt_{s} == null) {{ {refuse_stmt(oid, _cs('тип заливки не найден (модель изменилась после grounding)'), isolation)} }}")
    pt_fn = f"__vp_{s}"
    triples = [C.edge_witness_triples(region["outer"])]
    triples += [C.edge_witness_triples(h) for h in holes]
    flat = [t for loop in triples for t in loop]
    n_edges = len(flat)

    def _arr(name: str, values) -> str:
        return (f"double[] __{name}_{s} = new double[] {{ "
                + ", ".join(f"{round(v, 2)}" for v in values) + " };")

    decl = "\n".join([
        f"FilledRegion __el_{s} = null;",
        f"View __vw_{s} = null;",
        f"FilledRegionType __frt_{s} = null;",
        # Локальная функция вида→мир: её видят и создание, и постусловия
        # (контракт областей видимости — per_op оборачивает create своей).
        docspace.emit_view2d_point_fn_cs(f"__vw_{s}", pt_fn),
        # Авторский контур, вывезенный в C# ОДИН РАЗ: свидетель сверяется с
        # ним, а не с тем, что сам же передал в вызов.
        _arr("fu0", [t[0][0] for t in flat]),
        _arr("fv0", [t[0][1] for t in flat]),
        _arr("fum", [t[1][0] for t in flat]),
        _arr("fvm", [t[1][1] for t in flat]),
        _arr("fu1", [t[2][0] for t in flat]),
        _arr("fv1", [t[2][1] for t in flat]),
    ])
    fmt = (lambda x, y: f"{pt_fn}({round(x, 2)}, {round(y, 2)})")
    geo = [f"var __loops_{s} = new List<CurveLoop>();",
           C.emit_loop_cs(region["outer"], f"__ol_{s}", pt=fmt),
           f"__loops_{s}.Add(__ol_{s});"]
    for hi, hole in enumerate(holes):
        geo.append(C.emit_loop_cs(hole, f"__hl_{s}_{hi}", pt=fmt))
        geo.append(f"__loops_{s}.Add(__hl_{s}_{hi});")
    create = (
        f"// create_filled_region {cs_line_comment_fragment(oid)}\n{view_res}\n{type_res}\n"
        f"if (!FilledRegion.IsValidFilledRegionTypeId(doc, __frt_{s}.Id)) "
        f"{{ {refuse_stmt(oid, _cs('type: id резолвится не в тип заливки (IsValidFilledRegionTypeId)'), isolation)} }}\n"
        + "\n".join(geo) + "\n"
        f"try {{ __el_{s} = FilledRegion.Create(doc, __frt_{s}.Id, __vw_{s}.Id, __loops_{s}); }}\n"
        f"catch (Exception __ex_{s}) {{ {refuse_stmt(oid, f'\"FilledRegion.Create: \" + __ex_{s}.Message', isolation)} }}\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('FilledRegion.Create вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    btol = tolerance("create_filled_region", "boundary_mm")
    # Обратный ход — из docspace, тем же законом, что и прямой.
    inv = (lambda point_cs, rel, u, v:
           docspace.emit_xyz_to_view2d_cs(f"__vw_{s}", point_cs, rel, u, v,
                                          indent=" " * 16))
    boundary_reader = (
        f"    int __frLoops_{s} = 0; int __frCurves_{s} = 0;\n"
        f"    bool __frRead_{s} = true; bool __frStray_{s} = false;\n"
        f"    int[] __frHit_{s} = new int[{n_edges}];\n"
        f"    try\n    {{\n"
        f"        foreach (CurveLoop __frCl_{s} in __el_{s}.GetBoundaries())\n"
        f"        {{\n"
        f"            __frLoops_{s}++;\n"
        f"            foreach (Curve __frCv_{s} in __frCl_{s})\n"
        f"            {{\n"
        f"                __frCurves_{s}++;\n"
        + inv(f"__frCv_{s}.GetEndPoint(0)", f"__frRa_{s}", f"__frAu_{s}", f"__frAv_{s}")
        + inv(f"__frCv_{s}.GetEndPoint(1)", f"__frRb_{s}", f"__frBu_{s}", f"__frBv_{s}")
        + inv(f"__frCv_{s}.Evaluate(0.5, true)", f"__frRm_{s}", f"__frMu_{s}", f"__frMv_{s}")
        + f"                bool __frOne_{s} = false;\n"
        f"                for (int __frK_{s} = 0; __frK_{s} < {n_edges}; __frK_{s}++)\n"
        f"                {{\n"
        f"                    bool __frFwd_{s} = Math.Abs(__frAu_{s} - __fu0_{s}[__frK_{s}]) <= {btol}\n"
        f"                        && Math.Abs(__frAv_{s} - __fv0_{s}[__frK_{s}]) <= {btol}\n"
        f"                        && Math.Abs(__frBu_{s} - __fu1_{s}[__frK_{s}]) <= {btol}\n"
        f"                        && Math.Abs(__frBv_{s} - __fv1_{s}[__frK_{s}]) <= {btol};\n"
        f"                    bool __frRev_{s} = Math.Abs(__frAu_{s} - __fu1_{s}[__frK_{s}]) <= {btol}\n"
        f"                        && Math.Abs(__frAv_{s} - __fv1_{s}[__frK_{s}]) <= {btol}\n"
        f"                        && Math.Abs(__frBu_{s} - __fu0_{s}[__frK_{s}]) <= {btol}\n"
        f"                        && Math.Abs(__frBv_{s} - __fv0_{s}[__frK_{s}]) <= {btol};\n"
        f"                    if ((__frFwd_{s} || __frRev_{s})\n"
        f"                        && Math.Abs(__frMu_{s} - __fum_{s}[__frK_{s}]) <= {btol}\n"
        f"                        && Math.Abs(__frMv_{s} - __fvm_{s}[__frK_{s}]) <= {btol})\n"
        f"                    {{ __frHit_{s}[__frK_{s}]++; __frOne_{s} = true; break; }}\n"
        f"                }}\n"
        f"                if (!__frOne_{s}) __frStray_{s} = true;\n"
        f"            }}\n"
        f"        }}\n"
        f"    }} catch {{ __frRead_{s} = false; }}\n"
        f"    bool __frExact_{s} = true;\n"
        f"    for (int __frJ_{s} = 0; __frJ_{s} < {n_edges}; __frJ_{s}++)\n"
        f"        if (__frHit_{s}[__frJ_{s}] != 1) __frExact_{s} = false;\n")
    boundary_verdict = (
        f"    if (!__frRead_{s})\n"
        f"        __post.Add({_cs(oid + ': граница заливки нечитаема — GetBoundaries бросил (geometry)')});\n"
        f"    else if (__frLoops_{s} != {1 + len(holes)} || __frCurves_{s} != {n_edges})\n"
        f"        __post.Add({_cs(oid + ': прочитано ')} + __frLoops_{s} + "
        f"{_cs(' петель / ')} + __frCurves_{s} + "
        f"{_cs(f' рёбер вместо {1 + len(holes)}/{n_edges} (geometry)')});\n"
        f"    else if (__frStray_{s} || !__frExact_{s})\n"
        f"        __post.Add({_cs(oid + ': граница заливки не совпала с заданным контуром в осях вида (geometry)')});\n")
    post = [
        WitnessCheck(
            obligation_key="in_view", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.OwnerViewId.ToString() != __vw_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': filled region belongs to wrong view (topology)')});\n"),
            message="filled region belongs to wrong view (topology)",
            style="guard"),
        WitnessCheck(
            obligation_key="region_type", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.GetTypeId().ToString() != __frt_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': тип заливки после чтения не тот, что запрошен (semantic)')});\n"),
            message="тип заливки после чтения не тот, что запрошен (semantic)",
            style="guard"),
        WitnessCheck(
            obligation_key="boundary",
            reader_cs=boundary_reader,
            verdict_cs=boundary_verdict,
            message="граница заливки не совпала с заданным контуром (geometry)",
            tol=btol, style="else_block"),
    ]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}", type_level=False) +
        f"    __rb[\"view_id\"] = __el_{s}.OwnerViewId.ToString();\n"
        f"    __rb[\"type_id\"] = __el_{s}.GetTypeId().ToString();\n"
        # ИМЯ типа, а не только id, и это не украшение квитанции. При
        # опущенном `type` тип выбирает сам документ уже здесь, внутри
        # исполнения, поэтому витрина выбора (`ground.attach_runtime_choices`)
        # берёт имя ровно отсюда. Замер 10.08.2026: из восьми опов с
        # документным умолчанием семь читали `type_name` обратно, а заливка —
        # единственная — не читала, то есть указатель в её квитанции вёл бы в
        # никуда. Прибор на часть диапазона опаснее отсутствующего.
        f"    try {{ var __frTy_{s} = doc.GetElement(__el_{s}.GetTypeId());\n"
        f"        if (__frTy_{s} != null && __frTy_{s}.Name != null) "
        f"__rb[\"type_name\"] = __frTy_{s}.Name; }} catch {{ }}\n"
        # ЗАПИСАНО, А НЕ УТВЕРЖДЕНО: «заливка это или маска» решает ТИП, а
        # какие типы проекта маскирующие — из программы не видно. Требовать
        # `IsMasking == false` значило бы отказывать по догадке; квитанция
        # несёт факт, и первый живой прогон закроет вопрос замером.
        f"    try {{ __rb[\"is_masking\"] = __el_{s}.IsMasking; }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


# ── wave/struct (2026-07-17): create_beam / create_foundation ───────────────
# Thin registration wrappers only — all real logic (StructuralType.Beam /
# StructuralType.Footing / structural-Floor-slab emit) lives in struct_emit.py
# (this wave's own zone), mirroring wave/mep's route_mep.py split exactly.



def _emit_foundation_struct(op: dict, ver: str, stamp: str,
                            isolation: str = "atomic") -> tuple[str, str, str, str]:
    from kir import struct_emit
    return struct_emit.emit_foundation(op, ver, stamp, isolation)


def _emit_wall_foundation_struct(op: dict, ver: str, stamp: str,
                                 isolation: str = "atomic") -> tuple[str, str, str, str]:
    from kir import struct_emit
    return struct_emit.emit_wall_foundation(op, ver, stamp, isolation)


# wave/framing (2026-08-09): балочная система и ферма. Та же регистрация
# без логики, что у трёх опов выше — тело живёт в struct_emit.py.





# wave/reinforcement (2026-08-10): армирование по области. Та же регистрация
# без логики — тело живёт в struct_emit.py, как у всех структурных опов.



# wave/arch (2026-07-29): потолки и ограждения. Логика в arch_emit.py (своя
# зона волны), здесь — только регистрация, ровно как у волны каркаса выше.





# wave/datums (2026-08-09): цепь осей, выдавленная кровля и размножение марша
# по этажам. Логика в datum_emit.py (своя зона волны), здесь — только
# регистрация, ровно как у волн каркаса и архитектуры выше. Импорт отложенный
# по той же причине: datum_emit импортирует помощники ИЗ этого модуля.





def _emit_multistory_stairs_datum(op: dict, ver: str, stamp: str,
                                  isolation: str = "atomic") -> tuple[str, str, str, str]:
    from kir import datum_emit
    return datum_emit.emit_multistory_stairs(op, ver, stamp, isolation)


# wave/mep-electrical (2026-08-09): короб ЭОМ, две заготовки и два гибких
# участка. Логика в mep_emit.py (своя зона волны), здесь — только регистрация,
# ровно как у волн каркаса и архитектуры выше. Импорт отложенный по той же
# причине: mep_emit импортирует помощники ИЗ этого модуля.











# wave/analysis (2026-08-09): три нагрузки КР и путь эвакуации. Логика в
# analysis_emit.py (своя зона волны), здесь — только регистрация, ровно как у
# волн каркаса, архитектуры и ЭОМ выше. Импорт отложенный по той же причине:
# analysis_emit импортирует помощники ИЗ этого модуля.







# wave/site (2026-08-09): рельеф, площадка под здание, подобласть. Логика в
# site_emit.py (своя зона волны), здесь — только регистрация. Импорт
# отложенный по той же причине, что у волн выше: site_emit импортирует
# помощники ИЗ этого модуля, и импорт на уровне файла замкнул бы цикл.







# wave/sweep (2026-08-09): навесные профили — карниз/руст на стене и краевой
# профиль по периметру плиты. Логика в sweep_emit.py (своя зона волны), здесь
# — только регистрация. Импорт отложенный по той же причине, что у волн выше:
# sweep_emit импортирует помощники ИЗ этого модуля, и импорт на уровне файла
# замкнул бы цикл.

def _emit_wall_sweep(op: dict, ver: str, stamp: str,
                     isolation: str = "atomic") -> tuple[str, str, str, str]:
    from kir import sweep_emit
    return sweep_emit.emit_wall_sweep(op, ver, stamp, isolation)




# wave/shape (2026-07-29): произвольная геометрия мешем. Логика в
# shape_emit.py (своя зона волны), здесь — только регистрация. Импорт
# отложенный по той же причине, что у волн выше: shape_emit импортирует
# помощники ИЗ этого модуля, и импорт на уровне файла замкнул бы цикл.



# wave/solid (2026-08-09): ПАРАМЕТРИЧЕСКОЕ тело — та самая «отдельная волна с
# живым замером», которую пообещала шапка ops_shape.py вместо флажка
# Target=Solid. Логика в solid_emit.py (своя зона волны), здесь — только
# регистрация; импорт отложенный по той же причине, что у волн выше.





# wave/blend (2026-08-20): БЛЕНД между двумя профилями. Элементом тело делает
# `DirectShape`, а НЕ `FreeFormElement`: последний компилируется 6/6 и бросает
# «document is not a family document» на всех шести версиях (`data/api_traps`).
# Логика в solid_emit.py (своя зона волны), здесь — только регистрация.



# wave/sweep (2026-08-20): ПРОТЯЖКА профиля по пространственной ломаной, две
# фабрики Revit под одним опом. Объём здесь ТОЧЕН (A·L), потому что центроид
# профиля ставится на путь и первый момент обращается в ноль в каждом усе —
# вывод в шапке sweep_path.py. Логика в solid_emit.py.

def _emit_solid_sweep(op: dict, ver: str, stamp: str,
                      isolation: str = "atomic") -> tuple[str, str, str, str]:
    from kir import solid_emit
    return solid_emit.emit_solid_sweep(op, ver, stamp, isolation)


# wave/surface (2026-08-20): NURBS-ПОВЕРХНОСТЬ как значение языка. Вход —
# КОНТРОЛЬНЫЕ точки, а не интерполяционные, и это решает обратный ход:
# `geom_extract.__gxNurbsSurface` читает именно их, иначе круговой ход не
# замкнулся бы по построению. Логика в surface_emit.py.

def _emit_surface(op: dict, ver: str, stamp: str,
                  isolation: str = "atomic") -> tuple[str, str, str, str]:
    from kir import surface_emit
    return surface_emit.emit_surface(op, ver, stamp, isolation)


# wave/adaptive (2026-08-20): АДАПТИВНЫЙ КОМПОНЕНТ — единственный род, дающий
# произвольную посадку по точкам И настоящий типизированный элемент разом.
# Всё прочее свободной формы (меш, поверхность, блендованное тело) идёт через
# `DirectShape` и BIM-смысла не несёт. Логика в adaptive_emit.py.



# wave/boolean (2026-08-20): БУЛЕВЫ над телами — вычесть, объединить, пересечь.
# Операнды рождаются и умирают ВНУТРИ опа: `Solid` в Revit не элемент, у него
# нет ElementId и он не переживает транзакцию, поэтому сослаться на соседний
# оп нечем. Свидетель — тождество включения-исключения на объёмах, которые
# все до одного меряет Revit. Логика в boolean_emit.py.

def _emit_solid_boolean(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, str, str]:
    from kir import boolean_emit
    return boolean_emit.emit_solid_boolean(op, ver, stamp, isolation)


# wave/mass (2026-08-10): стена по НАКЛОННОЙ грани концептуальной массы —
# единственная фабрика главы масс, которую RevitAPI.xml разрешает В ПРОЕКТНОМ
# документе («document is not a project document» стоит у неё среди условий
# броска, то есть требуется ровно тот документ, в который KIR и пишет).
# Логика в mass_emit.py (своя зона волны), здесь — только регистрация; импорт
# отложенный по той же причине, что у волн выше.



# wave/room (2026-08-03): разделитель помещений. Логика в room_emit.py (своя
# зона волны), здесь — только регистрация. Импорт отложенный по той же
# причине, что у волн выше: room_emit импортирует помощники ИЗ этого модуля.



# wave/opening (2026-08-03): проём КАК ОТДЕЛЬНЫЙ ЭЛЕМЕНТ (Autodesk.Revit.DB.
# Opening) — единственная молчаливая потеря, найденная замером восьми зданий.
# Логика в opening_emit.py (своя зона волны), здесь — только регистрация.
# Импорт отложенный по той же причине, что у волн выше.



# wave/space (2026-08-10): пространство ОВК. Логика в room_emit.py
# (парный файл своей волны), здесь — только регистрация. Импорт
# отложенный по той же причине, что у волн выше: room_emit импортирует
# помощники ИЗ этого модуля.

def _emit_space(op: dict, ver: str, stamp: str,
                isolation: str = "atomic") -> tuple[str, str, str, str]:
    from kir import room_emit
    return room_emit.emit_space(op, ver, stamp, isolation)


def _emit_group(op: dict, ver: str, stamp: str,
                isolation: str = "atomic") -> tuple[str, str, str, str]:
    """Emit a native Revit group of a repeated component (feat/native-groups).

    Authors the DEFINITION member ops ONCE (at occurrence 0's absolute coords),
    ``doc.Create.NewGroup``s them into a GroupType, then ``doc.Create.PlaceGroup``s
    a new instance at every ``placements`` offset.  Placement math (LOT31 C-RT
    bug class): PlaceGroup aligns the group ORIGIN to its location argument, and
    the group's origin ``O0`` is chosen by Revit — unknown at emit time — so we
    read it LIVE from the created group and place occurrence k at ``O0 + delta_k``
    where ``delta_k = occ_origin_k - occ_origin_0`` (already computed in mm by the
    bridge; ABSOLUTE origins subtracted, never assuming occ_origin_0 == 0).

    FAIL-CLOSED: any member create returning null, NewGroup null, or a PlaceGroup
    null goes through the SAME ``refuse_stmt(oid, msg, isolation)`` guard every
    creation op uses, so under per_op isolation ONLY the group op is refused and
    the caller keeps the N-element fallback.  A group is never committed wrong:
    better ungrouped-but-correct than grouped-wrong.

    Members are authored by their OWN emitters and *isolation* travels with
    them: a member's guard is rendered in the form the enclosing program needs
    (review finding №10 — a guard-site nested inside a group is a guard-site
    like any other, and it is the member's TYPE that decides which ones exist).
    """
    oid = op["id"]
    s = _safe(oid)
    members = op["members"]
    placements = op["placements"]
    group_name = op.get("name")

    # Author each member with its own emitter, namespacing the member id under
    # the group op id so member vars never collide with sibling program ops.
    member_decls: list[str] = []
    member_creates: list[str] = []
    member_id_vars: list[str] = []
    member_readbacks: list[str] = []
    member_witnesses: list[WitnessCheck] = []
    #: Имена членов внутри группы: `{oid}__m__{id}`. Ссылка одного члена на
    #: другого обязана ехать в ТОМ ЖЕ имени, иначе эмиссия даст `__el_<сырое>`,
    #: которого в этом scope нет. `authoring_validation` уже доказал, что все
    #: ссылки указывают на членов ЭТОЙ группы и только назад по списку.
    _member_ns = {str(m0["id"]): f"{oid}__m__{m0['id']}"
                  for m0 in members if isinstance(m0, dict) and "id" in m0}

    def _rename_refs(node):
        if isinstance(node, dict):
            out = {}
            for key, val in node.items():
                if (key == "value" and node.get("by") == "ref"
                        and str(val) in _member_ns):
                    out[key] = _member_ns[str(val)]
                else:
                    out[key] = _rename_refs(val)
            return out
        if isinstance(node, list):
            return [_rename_refs(x) for x in node]
        return node

    for mi, member in enumerate(members):
        m = _rename_refs(dict(member))
        m["id"] = f"{oid}__m__{member['id']}"
        ms = _safe(m["id"])
        try:
            m_decl, m_create, m_post, m_readback = _EMITTERS[m["op"]](
                m, ver, stamp, isolation)
        except KirRefusal:
            raise
        except Exception as exc:  # noqa: BLE001 — лид-ревью №2: член, собранный
            # НЕ мостом (сырые/неграундованные селекторы), раньше падал голым
            # KeyError -> KIR-P000 «внутренняя ошибка»; теперь — типизированный
            # отказ (члены обязаны быть pre-grounded, см. OpSpec create_group).
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid,
                field_name=f"members[{mi}]", got=member.get("id"),
                message_ru=(f"член группы {member.get('id')!r} не эмитится "
                            f"({type(exc).__name__}) — члены должны быть "
                            "pre-grounded (element_id/абсолютные координаты), "
                            "как их строит component-library мост"))]) from exc
        member_decls.append(m_decl)
        m_operation, m_final = render_staged_post(m["id"], m_post)
        member_creates.append(m_create + operation_check_gate(m["id"], m_operation, isolation))
        # Wave A2 (закрывает отложенную оговорку №1 групп): каждый member-POST
        # включается как WitnessCheck.  Рендерим member-пост его же braced-
        # фреймом (post_to_string) и вкладываем БЛОКОМ внутрь группового поста:
        # вложенный `{ }` даёт каждому члену собственный C#-scope, так что
        # локали одинаковых проверок соседних членов (var __lc и т.п.) не
        # конфликтуют (CS0128) — тот же приём, что отдельные op-посты.
        if m_final:
            member_witnesses.append(WitnessCheck(
                obligation_key=f"member_{mi}",
                reader_cs="",
                verdict_cs="    " + m_final.replace("\n", "\n    ") + "\n",
                message=f"member {member.get('id')!r} postconditions",
                style="plain"))
        # Лид-ревью №1 (частично): member-ридбэки включаем — post-commit
        # свидетельство id/геометрии каждого члена; member-POSTs отложены до
        # волны «однострочный свидетель» (cert-конвенция), см. NOTES.
        member_readbacks.append(m_readback)
        # every member emitter creates a `__el_<safeid>` element variable.
        member_id_vars.append(f"__el_{ms}.Id")

    # Fully-qualify Group/GroupType: the compile wrapper imports
    # System.Text.RegularExpressions, whose `Group` collides with
    # Autodesk.Revit.DB.Group (CS0104, gate-caught on all 6 versions).
    decl = (
        "\n".join(member_decls) + "\n"
        + f"Autodesk.Revit.DB.Group __grp_{s} = null;\n"
        + f"Autodesk.Revit.DB.GroupType __gt_{s} = null;\n"
        + f"int __placed_{s} = 0;\n"
        # 🔴 ЭТИ ЧЕТЫРЕ ЖИВУТ В `decl`, А НЕ В `create`, И ЭТО НЕ СТИЛЬ.
        # `__pg_<s>_<k>` объявлены внутри `create` и при обёртке per_op умирают
        # на закрывающей скобке — свидетелю они не видны. Тот же промах стоил
        # соседнему опу шести отказов Roslyn 10.08. Поэтому размещения
        # СОБИРАЮТСЯ в список уровня программы, а числа для квитанции
        # выставляются свидетелем (он идёт ДО Commit) и читаются ридбэком
        # (он идёт ПОСЛЕ) — порядок проверен по сборке программы.
        + f"var __pgl_{s} = new List<Autodesk.Revit.DB.Group>();\n"
        + f"double __gpDev_{s} = -1.0;\n"
        + f"int __gpUnread_{s} = 0;"
    )

    # ICollection<ElementId> of the freshly-created member ids -> NewGroup.
    ids_add = "".join(
        f"    __members_{s}.Add({idv});\n" for idv in member_id_vars)
    rename = ""
    if group_name is not None:
        # Rename the GroupType (the definition name), guarded — a duplicate name
        # is not a hard failure (Revit auto-suffixes), so swallow.
        rename = (
            f"try {{ __gt_{s}.Name = {_cs(group_name)}; }} catch {{ }}\n")
    # PlaceGroup at O0 + delta for each additional occurrence.  Deltas are mm;
    # convert with U(). O0 is read live from the definition group's origin.
    place_lines = ""
    for k, delta in enumerate(placements):
        dx, dy, dz = float(delta[0]), float(delta[1]), float(delta[2])
        place_lines += (
            f"XYZ __loc_{s}_{k} = new XYZ(__o0_{s}.X + U({dx}), "
            f"__o0_{s}.Y + U({dy}), __o0_{s}.Z + U({dz}));\n"
            f"Autodesk.Revit.DB.Group __pg_{s}_{k} = doc.Create.PlaceGroup(__loc_{s}_{k}, __gt_{s});\n"
            f"if (__pg_{s}_{k} == null) {{ {refuse_stmt(oid, f'\"PlaceGroup вернул null для смещения {k}\"', isolation)} }}\n"
            f"__placed_{s}++;\n"
            f"__pgl_{s}.Add(__pg_{s}_{k});\n"
            + _stamp_block(f"__pg_{s}_{k}", f"{stamp}:{oid}:{k}") + "\n")

    create = (
        f"// create_group {cs_line_comment_fragment(oid)} — native Revit group ({len(members)} members, "
        f"{len(placements)} extra placements)\n"
        # 1) author the definition members at occurrence 0
        + "\n".join(member_creates) + "\n"
        # 2) freshly-created elements must be regenerated before grouping (API
        #    doc note: avoids the 'group changed outside edit mode' warning).
        + "doc.Regenerate();\n"
        + f"var __members_{s} = new List<ElementId>();\n"
        + ids_add
        + f"__grp_{s} = doc.Create.NewGroup(__members_{s});\n"
        + f"if (__grp_{s} == null) {{ {refuse_stmt(oid, _cs('NewGroup вернул null (члены не образуют группу)'), isolation)} }}\n"
        + f"__gt_{s} = __grp_{s}.GroupType;\n"
        + f"if (__gt_{s} == null) {{ {refuse_stmt(oid, _cs('у созданной группы нет GroupType'), isolation)} }}\n"
        + rename
        # 3) read the definition group's live origin O0 (the point PlaceGroup
        #    aligns to), then place each further occurrence at O0 + delta.
        + f"var __lp0_{s} = __grp_{s}.Location as LocationPoint;\n"
        + f"if (__lp0_{s} == null) {{ {refuse_stmt(oid, _cs('у группы-определения нет LocationPoint (origin)'), isolation)} }}\n"
        + f"XYZ __o0_{s} = __lp0_{s}.Point;\n"
        + place_lines
        + _stamp_block(f"__grp_{s}", f"{stamp}:{oid}"))

    # Литералы смещений для свидетеля положений: они КОНСТАНТЫ программы, и
    # считать их живьём не нужно. Здесь же — совпадающие смещения: размещение с
    # нулевым смещением совпадает с экземпляром-определением, и тогда в модели
    # стоят ДВЕ группы в одной точке. Замер 18.08: 59 таких дублей по зданию, и
    # нигде не задокументировано. Число выводится из программы, поэтому уезжает
    # в квитанцию ЧИСЛОМ, а не ищется в Revit.
    gp_dx = ", ".join(repr(float(d[0])) for d in placements)
    gp_dy = ", ".join(repr(float(d[1])) for d in placements)
    gp_dz = ", ".join(repr(float(d[2])) for d in placements)
    # Через `tolerance()`, а НЕ через `spec.OPS[...].tolerances[...]`: голое
    # число провенанс не несёт, и `WitnessCheck` его отвергает (закон 1
    # emit_model — «ссылка в пустоту, дожившая до прода» — дефект create_type).
    gp_tol = tolerance("create_group", "group_placement_mm")
    _seen_deltas: dict[tuple, int] = {}
    for _d in placements:
        _key = (float(_d[0]), float(_d[1]), float(_d[2]))
        _seen_deltas[_key] = _seen_deltas.get(_key, 0) + 1
    gp_coincident = sum(n - 1 for n in _seen_deltas.values())
    gp_coincident += _seen_deltas.get((0.0, 0.0, 0.0), 0)

    # Post: the GroupType materialized, the right number of instances exist, and
    # the name matches when requested.  ``__gt_<s>.Groups`` is the GroupSet of all
    # instances of this definition == 1 (definition) + placements.
    want_instances = 1 + len(placements)
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="instances", reader_cs="",
            verdict_cs=(
                f"    if (__gt_{s} == null || doc.GetElement(__gt_{s}.Id) == null)\n"
                f"        __post.Add({_cs(oid + ': GroupType не материализован')});\n"
                f"    else\n    {{\n"
                f"        int __cnt_{s} = 0;\n"
                f"        foreach (Autodesk.Revit.DB.Group __g_{s} in __gt_{s}.Groups) __cnt_{s}++;\n"
                f"        if (__cnt_{s} != {want_instances})\n"
                f"            __post.Add({_cs(oid + ': число экземпляров группы не совпадает (semantic)')});\n"
                f"    }}\n"),
            message="число экземпляров группы не совпадает (semantic)",
            style="else_block"),
        WitnessCheck(
            obligation_key="placed", reader_cs="",
            verdict_cs=(
                f"    if (__placed_{s} != {len(placements)})\n"
                f"        __post.Add({_cs(oid + ': размещено не все экземпляры (semantic)')});\n"),
            message="размещено не все экземпляры (semantic)", style="guard"),
        # 🔴 ОСЬ ГЕОМЕТРИИ. Соседняя проверка `instances` почти тавтологична:
        # шлём N размещений, читаем N экземпляров. Эта — нет. Положение каждого
        # члена внутри копии Revit ВЫВОДИТ сам из определения группы; мы шлём
        # ОДНУ точку на копию. Поэтому ожидаемое выводится из программы
        # (положение члена определения плюс смещение), полученное читается
        # живьём, и акт различения существует.
        #
        # Признак — центр bbox каждого члена, приведённый к системе определения
        # вычитанием смещения копии. Порядок `GetMemberIds()` Revit НЕ
        # документирует, поэтому сравнение идёт по БЛИЖАЙШЕМУ соответствию (для
        # каждого члена определения — минимум расстояния до членов копии), и от
        # порядка не зависит вовсе. Сортировка была бы вторым способом это
        # обойти, но она требует `delegate`-компаратора, чьи параметры сторож
        # областей видимости объявлением не считает — под `per_op` это CS0103,
        # и он поймал это на шести версиях, прежде чем оно доехало куда-либо.
        #
        # Сравнение ЧИСЛОВОЕ с допуском, а не по строковой сетке: равенство на
        # сетке врёт у границы ячейки (замер 14.08 — свидетель отверг
        # геометрию, совпавшую на 0.0000% по трём мерам).
        #
        # Нечитаемый bbox — ОТКАЗ, а не пропуск: молча выкинуть член значило бы
        # свидетельствовать по части предмета и назвать это чистотой.
        WitnessCheck(
            obligation_key="member_positions",
            reader_cs=(
                # Копии только что созданы; без регенерации их bbox устарел.
                f"    doc.Regenerate();\n"
                f"    double[] __gpDX_{s} = new double[] {{{gp_dx}}};\n"
                f"    double[] __gpDY_{s} = new double[] {{{gp_dy}}};\n"
                f"    double[] __gpDZ_{s} = new double[] {{{gp_dz}}};\n"
                f"    var __gpAll_{s} = new List<List<XYZ>>();\n"
                f"    for (int __gi_{s} = -1; __gi_{s} < __pgl_{s}.Count; __gi_{s}++)\n"
                f"    {{\n"
                f"        Autodesk.Revit.DB.Group __g_{s} = (__gi_{s} < 0)\n"
                f"            ? __grp_{s} : __pgl_{s}[__gi_{s}];\n"
                f"        double __dx_{s} = (__gi_{s} < 0) ? 0.0 : __gpDX_{s}[__gi_{s}];\n"
                f"        double __dy_{s} = (__gi_{s} < 0) ? 0.0 : __gpDY_{s}[__gi_{s}];\n"
                f"        double __dz_{s} = (__gi_{s} < 0) ? 0.0 : __gpDZ_{s}[__gi_{s}];\n"
                f"        var __sig_{s} = new List<XYZ>();\n"
                f"        if (__g_{s} != null)\n"
                f"        {{\n"
                f"            foreach (var __mid_{s} in __g_{s}.GetMemberIds())\n"
                f"            {{\n"
                f"                var __me_{s} = doc.GetElement(__mid_{s});\n"
                f"                var __mbb_{s} = (__me_{s} == null)\n"
                f"                    ? null : __me_{s}.get_BoundingBox(null);\n"
                f"                if (__mbb_{s} == null) {{ __gpUnread_{s}++; continue; }}\n"
                f"                __sig_{s}.Add(new XYZ(\n"
                f"                    MM((__mbb_{s}.Min.X + __mbb_{s}.Max.X) / 2.0) - __dx_{s},\n"
                f"                    MM((__mbb_{s}.Min.Y + __mbb_{s}.Max.Y) / 2.0) - __dy_{s},\n"
                f"                    MM((__mbb_{s}.Min.Z + __mbb_{s}.Max.Z) / 2.0) - __dz_{s}));\n"
                f"            }}\n"
                f"        }}\n"
                f"        __gpAll_{s}.Add(__sig_{s});\n"
                f"    }}\n"),
            verdict_cs=(
                f"    if (__gpUnread_{s} > 0)\n"
                f"        __post.Add({_cs(oid + ': положение членов группы не прочитано (geometry)')});\n"
                f"    else\n    {{\n"
                f"        var __gpB_{s} = __gpAll_{s}[0];\n"
                f"        for (int __gk_{s} = 1; __gk_{s} < __gpAll_{s}.Count; __gk_{s}++)\n"
                f"        {{\n"
                f"            var __gpC_{s} = __gpAll_{s}[__gk_{s}];\n"
                f"            if (__gpC_{s}.Count != __gpB_{s}.Count)\n"
                f"            {{\n"
                f"                __post.Add({_cs(oid + ': состав размещения не равен определению (geometry)')});\n"
                f"                break;\n"
                f"            }}\n"
                f"            for (int __gj_{s} = 0; __gj_{s} < __gpB_{s}.Count; __gj_{s}++)\n"
                f"            {{\n"
                f"                double __best_{s} = double.MaxValue;\n"
                f"                for (int __gm_{s} = 0; __gm_{s} < __gpC_{s}.Count; __gm_{s}++)\n"
                f"                {{\n"
                f"                    double __dd_{s} = Math.Max(\n"
                f"                        Math.Abs(__gpC_{s}[__gm_{s}].X - __gpB_{s}[__gj_{s}].X),\n"
                f"                        Math.Max(\n"
                f"                            Math.Abs(__gpC_{s}[__gm_{s}].Y - __gpB_{s}[__gj_{s}].Y),\n"
                f"                            Math.Abs(__gpC_{s}[__gm_{s}].Z - __gpB_{s}[__gj_{s}].Z)));\n"
                f"                    if (__dd_{s} < __best_{s}) __best_{s} = __dd_{s};\n"
                f"                }}\n"
                f"                if (__best_{s} > __gpDev_{s}) __gpDev_{s} = __best_{s};\n"
                f"            }}\n"
                f"        }}\n"
                f"        if (__gpDev_{s} > {gp_tol})\n"
                f"            __post.Add({_cs(oid + ': члены размещения стоят не там, где определение плюс смещение (geometry)')});\n"
                f"    }}\n"),
            message=("члены размещения стоят не там, где определение плюс "
                     "смещение (geometry)"),
            tol=gp_tol,
            style="guard"),
    ]
    if group_name is not None:
        checks.append(WitnessCheck(
            obligation_key="name", reader_cs="",
            verdict_cs=(
                f"    if (__gt_{s}.Name != {_cs(group_name)})\n"
                f"        __post.Add({_cs(oid + ': имя GroupType не совпадает (semantic)')});\n"),
            message="имя GroupType не совпадает (semantic)", style="guard"))
    # Wave A2: member-POSTs — the one DELIBERATE byte change of this wave
    # (pinned decision #7; parity exemption + dedicated golden pin new bytes).
    checks.extend(member_witnesses)
    post = checks

    readback = (
        "\n\n".join(member_readbacks) + "\n\n"
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb_{s} = new Dictionary<string, object>();\n"
        f"    try {{ if (__grp_{s} != null) __rb_{s}[\"id\"] = __grp_{s}.Id.ToString(); }} catch {{ }}\n"
        f"    try {{ if (__gt_{s} != null) {{ __rb_{s}[\"group_type_id\"] = __gt_{s}.Id.ToString();\n"
        f"        __rb_{s}[\"group_type_name\"] = __gt_{s}.Name; }} }} catch {{ }}\n"
        f"    __rb_{s}[\"member_count\"] = {len(members)};\n"
        f"    __rb_{s}[\"placed_count\"] = __placed_{s};\n"
        f"    __rb_{s}[\"instance_count\"] = {want_instances};\n"
        # Числа свидетеля положений — В КВИТАНЦИЮ, а не только в сторож. Порог
        # ГРУБЫЙ по названной причине (шов соединения двигает солид на
        # полтолщины), поэтому точное максимальное расхождение обязано быть
        # видно: им и уточняется порог, когда его наконец замерят живьём.
        f"    __rb_{s}[\"member_offset_max_mm\"] = __gpDev_{s};\n"
        f"    __rb_{s}[\"member_offset_tol_mm\"] = {gp_tol};\n"
        f"    __rb_{s}[\"members_unreadable\"] = __gpUnread_{s};\n"
        f"    __rb_{s}[\"coincident_instances\"] = {gp_coincident};\n"
        f"    __results[{_cs(oid)}] = __rb_{s};\n"
        f"}}")
    return decl, create, post, readback


# ── Витражная ячейка: ОДНО определение адреса на оба направления ────────────
#
# Этот фрагмент C# — единственный источник правды о том, что значит «ячейка
# (u,v)». Его подставляет и прямой эмиттер (`_emit_set_curtain_panel`), и
# обратный захват (`decompile/curtain_extract.py`): если бы определений было
# два, адрес не пережил бы пересборку — молча, потому что обе стороны по
# отдельности выглядели бы правильными.
#
# Почему адрес — РАНГ линии разрезки, а не порядок выдачи Revit:
# `CurtainGrid.GetPanelIds()`/`GetUGridLineIds()` порядок не документируют, а
# id линий в пересобранной модели ДРУГИЕ. Поэтому линии упорядочиваются по
# ГЕОМЕТРИИ (середина FullCurve, мм, округление до 0.1 мм — лексикографически
# X,Y,Z), а адрес панели читается `Panel.GetRefGridLines`, который отдаёт пару
# опорных линий ячейки. Какую именно из двух граничных линий Revit называет
# опорной, знать не нужно: отображение «ранг ↔ ячейка» биективно, а обе
# стороны считают его ОДНИМ И ТЕМ ЖЕ кодом.
#
# Совпадение ключей двух линий (или нечитаемая FullCurve) — не «возьмём как
# есть», а отказ: порядок неопределён, значит адреса нет.
#
# `__CC_S__` — суффикс уникальности: в одной программе может быть несколько
# опов, а преамбула эмиттера заморожена голденами и общие хелперы туда не
# добавить.
#
# СТРАЖ `if (__ccEl == null) continue;` В `__ccPanelAt` — ДОКАЗУЕМОСТЬ, А НЕ
# ПОЧИНКА ПОВЕДЕНИЯ, и разница названа здесь, чтобы завтра не искали
# несуществующий инцидент в данных.
#
# Поведение было ВЕРНЫМ и до 13.08.2026: `__ccAddress` начинается с
# `__ccPanelEl as Panel`, `as` на null даёт null, и следующая строка
# возвращает null. Шаблон удовлетворял СВОЙСТВУ, не удовлетворяя
# ДОКАЗАТЕЛЬСТВУ.
#
# 13.08 в прод приехали анализаторы KUKAI001-006 (`08f711f6`), и KUKAI002
# требует доказательства. Цена включения померена автором честно — «2 отказа
# = 1.8%» — но НА КОРПУСЕ ТОГО, ЧТО ПИШЕТ МОДЕЛЬ: ворота компилируют её
# программы, а серверные шаблоны через них не проходят вовсе. Эта строка в ту
# популяцию не входила, и с 14:28 `revit_ir/decompile_read` умирал в чате:
# `internal.template_failed` НЕРЕПРАЙАБЕЛЕН по замыслу, то есть инструмент не
# деградировал, а умирал — 38 ходов за час. Обход всех 16 серверных шаблонов
# через живую службу: падал РОВНО ЭТОТ.
#
# НАСТОЯЩЕЕ ЛЕКАРСТВО — не эта строка, а шаблоны В КОРПУСЕ ВОРОТ, чтобы
# следующий анализатор не приземлился мимо них.
#
# ГРАНИЦА: неразрешимый id панели НИГДЕ НЕ ЗАПИСЫВАЕТСЯ, и это намеренно.
# `__ccPanelAt` есть `Func<…, Element>` — чистый поиск; «id не разрешается»
# значит «это не та панель», и `continue` тут ПРАВИЛЬНЫЙ ответ, а не
# молчаливая потеря. Канал отказа сменил бы тип лямбды и всех потребителей
# ради факта, которого никто не запрашивал.
#
# УСЛОВИЕ ПЕРЕСМОТРА ГРАНИЦЫ. Молчание верно ровно пока неразрешимый id
# значит «это не та панель». Оно станет ПОТЕРЕЙ, если `GetPanelIds` начнёт
# выдавать id панелей, которые в документе ЕСТЬ, но не читаются этим `doc` —
# например при чтении СВЯЗАННОГО файла, где id принадлежит другому документу.
# Наблюдаемый признак: непустая сетка, у которой найдено НОЛЬ ячеек при
# ненулевом `GetPanelIds`.
#
# И ПРОЗА ЖИВЁТ ЗДЕСЬ, А НЕ В ШАБЛОНЕ: первая редакция этой правки положила
# тридцать строк объяснения ВНУТРЬ C#, и они поехали бы в Revit с каждой
# витражной программой — голден вырос на 111 строк вместо трёх.
CURTAIN_CELL_ADDRESS_CS = r"""
Func<double, double> __ccMM__CC_S__ = (__ccFeet) =>
    UnitUtils.ConvertFromInternalUnits(__ccFeet, UnitTypeId.Millimeters);
// Носители витражной сетки: стена, витражная система, обе разновидности
// кровли. Один класс на носителя — не «а вдруг ещё», а ровно то, что несёт
// CurtainGrid в API 2021-2026 (замер по эталонным сборкам).
Func<Element, List<CurtainGrid>> __ccGrids__CC_S__ = (__ccHost) =>
{
    var __ccOut = new List<CurtainGrid>();
    if (__ccHost == null) return __ccOut;
    try
    {
        Wall __ccWall = __ccHost as Wall;
        if (__ccWall != null)
        {
            CurtainGrid __ccOne = __ccWall.CurtainGrid;
            if (__ccOne != null) __ccOut.Add(__ccOne);
            return __ccOut;
        }
        CurtainGridSet __ccSet = null;
        CurtainSystem __ccSys = __ccHost as CurtainSystem;
        if (__ccSys != null) __ccSet = __ccSys.CurtainGrids;
        ExtrusionRoof __ccExtr = __ccHost as ExtrusionRoof;
        if (__ccExtr != null) __ccSet = __ccExtr.CurtainGrids;
        FootPrintRoof __ccFoot = __ccHost as FootPrintRoof;
        if (__ccFoot != null) __ccSet = __ccFoot.CurtainGrids;
        if (__ccSet != null)
            foreach (CurtainGrid __ccItem in __ccSet)
                if (__ccItem != null) __ccOut.Add(__ccItem);
    }
    catch { }
    return __ccOut;
};
Func<double[], double[], int> __ccCmp__CC_S__ = (__ccA, __ccB) =>
{
    for (int __ccI = 0; __ccI < 3; __ccI++)
    {
        int __ccC = __ccA[__ccI].CompareTo(__ccB[__ccI]);
        if (__ccC != 0) return __ccC;
    }
    return 0;
};
// null == порядок не определён (нечитаемая кривая или две линии на одном
// месте). Молчаливое «оставим как пришло» здесь было бы адресом-догадкой.
Func<ICollection<ElementId>, List<ElementId>> __ccOrder__CC_S__ = (__ccIds) =>
{
    var __ccKeys = new Dictionary<string, double[]>();
    var __ccList = new List<ElementId>();
    if (__ccIds == null) return __ccList;
    foreach (ElementId __ccLineId in __ccIds)
    {
        CurtainGridLine __ccLine = null;
        Curve __ccCurve = null;
        XYZ __ccMid = null;
        try
        {
            __ccLine = __CC_DOC__.GetElement(__ccLineId) as CurtainGridLine;
            if (__ccLine != null) __ccCurve = __ccLine.FullCurve;
            if (__ccCurve != null) __ccMid = __ccCurve.Evaluate(0.5, true);
        }
        catch { }
        if (__ccMid == null) return null;
        __ccKeys[__ccLineId.ToString()] = new double[] {
            Math.Round(__ccMM__CC_S__(__ccMid.X), 1),
            Math.Round(__ccMM__CC_S__(__ccMid.Y), 1),
            Math.Round(__ccMM__CC_S__(__ccMid.Z), 1) };
        __ccList.Add(__ccLineId);
    }
    __ccList.Sort((__ccL, __ccR) => __ccCmp__CC_S__(
        __ccKeys[__ccL.ToString()], __ccKeys[__ccR.ToString()]));
    for (int __ccI = 1; __ccI < __ccList.Count; __ccI++)
        if (__ccCmp__CC_S__(__ccKeys[__ccList[__ccI - 1].ToString()],
                            __ccKeys[__ccList[__ccI].ToString()]) == 0)
            return null;
    return __ccList;
};
// Адрес ячейки: {u, v} либо null. 0 — ячейка по эту сторону первой линии.
Func<Element, List<ElementId>, List<ElementId>, int[]> __ccAddress__CC_S__ =
    (__ccPanelEl, __ccU, __ccV) =>
{
    Panel __ccPanel = __ccPanelEl as Panel;
    if (__ccPanel == null || __ccU == null || __ccV == null) return null;
    // GetRefGridLines принимает ИМЕННО ref, а не out (замер: Roslyn против
    // эталонных сборок, CS1620 на всех шести версиях), поэтому обе ссылки
    // обязаны быть проинициализированы до вызова.
    ElementId __ccURef = ElementId.InvalidElementId;
    ElementId __ccVRef = ElementId.InvalidElementId;
    try { __ccPanel.GetRefGridLines(ref __ccURef, ref __ccVRef); }
    catch { return null; }
    var __ccAddr = new int[] { 0, 0 };
    var __ccRefs = new ElementId[] { __ccURef, __ccVRef };
    var __ccOrders = new List<ElementId>[] { __ccU, __ccV };
    string __ccInvalid = ElementId.InvalidElementId.ToString();
    for (int __ccAxis = 0; __ccAxis < 2; __ccAxis++)
    {
        ElementId __ccRef = __ccRefs[__ccAxis];
        if (__ccRef == null || __ccRef.ToString() == __ccInvalid) continue;
        int __ccRank = -1;
        List<ElementId> __ccOrderAxis = __ccOrders[__ccAxis];
        for (int __ccI = 0; __ccI < __ccOrderAxis.Count; __ccI++)
            if (__ccOrderAxis[__ccI].ToString() == __ccRef.ToString())
            { __ccRank = __ccI + 1; break; }
        if (__ccRank < 0) return null;
        __ccAddr[__ccAxis] = __ccRank;
    }
    return __ccAddr;
};
Func<CurtainGrid, List<ElementId>, List<ElementId>, int, int, Element>
    __ccPanelAt__CC_S__ = (__ccGrid, __ccU, __ccV, __ccWantU, __ccWantV) =>
{
    if (__ccGrid == null || __ccU == null || __ccV == null) return null;
    ICollection<ElementId> __ccPanelIds = null;
    try { __ccPanelIds = __ccGrid.GetPanelIds(); }
    catch { return null; }
    if (__ccPanelIds == null) return null;
    foreach (ElementId __ccPid in __ccPanelIds)
    {
        Element __ccEl = __CC_DOC__.GetElement(__ccPid);
        // Страж доказуемости KUKAI002; обоснование и границы — в
        // комментарии Python над этим шаблоном, чтобы проза не ехала в Revit.
        if (__ccEl == null) continue;
        int[] __ccAddr = __ccAddress__CC_S__(__ccEl, __ccU, __ccV);
        if (__ccAddr != null && __ccAddr[0] == __ccWantU
            && __ccAddr[1] == __ccWantV)
            return __ccEl;
    }
    return null;
};
// ЭФФЕКТИВНЫЙ тип ячейки. Ячейка, заполненная стеной, живёт в Revit ДВУМЯ
// элементами: обёрткой-Panel (её тип — системный «стена») и телом-Wall (у
// него настоящий тип). Тип ячейки — это тип ТЕЛА, если тело есть; иначе
// собственный тип панели. Одно определение на захват и на свидетеля, иначе
// пересборка «сходилась» бы с исходником по обёртке, потеряв тип тела.
Func<Element, ElementId> __ccEffType__CC_S__ = (__ccPanelEl) =>
{
    if (__ccPanelEl == null) return null;
    try
    {
        Panel __ccPanel = __ccPanelEl as Panel;
        if (__ccPanel != null)
        {
            ElementId __ccBodyId = __ccPanel.FindHostPanel();
            if (__ccBodyId != null
                && __ccBodyId.ToString() != ElementId.InvalidElementId.ToString())
            {
                Element __ccBody = __CC_DOC__.GetElement(__ccBodyId);
                if (__ccBody != null) return __ccBody.GetTypeId();
            }
        }
    }
    catch { }
    return __ccPanelEl.GetTypeId();
};
""".strip("\n")


def curtain_cell_address_cs(suffix: str, *, document: str = "doc") -> str:
    """The shared address helpers, name-scoped by ``suffix`` (one per op).

    ``document`` — имя переменной ЧИТАЕМОГО документа. Прямому компилятору
    читать нечего кроме хозяина, поэтому умолчание ``doc``; захват же с 30.07
    умеет снимать СВЯЗЬ и передаёт сюда ``__src``. Параметризован именно
    документ, а не текст: адрес ячейки (u,v) обязан считаться ОДНИМ кодом на
    обеих сторонах, иначе он не переживёт пересборку — молча, потому что
    каждая сторона по отдельности выглядела бы правильной.
    """

    if not re.fullmatch(r"[A-Za-z0-9_]*", suffix or ""):
        raise ValueError("curtain cell helper suffix must be a C# identifier")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", document or ""):
        raise ValueError("curtain cell document must be a C# identifier")
    body = CURTAIN_CELL_ADDRESS_CS.replace("__CC_S__", suffix or "")
    body = body.replace("__CC_DOC__", document)
    if "__CC_S__" in body or "__CC_DOC__" in body:
        raise ValueError("curtain cell helper placeholder survived emission")
    return body


def _emit_set_curtain_panel(op: dict, ver: str, stamp: str,
                            isolation: str = "atomic") -> tuple[str, str, str, str]:
    """Назначить тип ячейке витража — ЕДИНСТВЕННЫЙ способ «создать» панель.

    Свидетель читает РЕЗУЛЬТАТ: после Regenerate ячейка ищется заново, и у
    ЗАНЯВШЕГО её элемента читается эффективный тип. `ChangePanelType`
    подменяет элемент — эхо вызова доказывало бы лишь то, что вызов
    состоялся.

    СТАРАЯ ПАНЕЛЬ ОСТАЁТСЯ В СЕТКЕ — ЭТО НЕ ДЕФЕКТ. Замер E2 (живой
    носитель, транзакция закоммичена): после смены ячейки на тип стены
    `GetPanelIds()` по-прежнему держит прежнюю авто-панель (класс `Panel`,
    тип разрезки), а стена-занявший в списке отсутствует вовсе — ни после
    `Regenerate`, ни после `Commit`. Это запись Revit для возврата ячейки к
    type-driven состоянию, живущая ПАРАЛЛЕЛЬНО занявшему. Поэтому
    принадлежность носителю у ячейки-стены доказывается осью, а не списком:
    проверка членством для неё ложно-отрицательна всегда.
    """

    oid = op["id"]
    s = _safe(oid)
    u = int(op["u"])
    v = int(op["v"])
    sel = op["panel_type"]
    host = op["host"]

    if host["by"] == "ref":
        host_res = f"__ch_{s} = (Element)__el_{_safe(host['value'])};"
    else:
        host_res = (
            f"__ch_{s} = doc.GetElement({_eid(host['value'], ver, oid)});\n"
            f"if (__ch_{s} == null) {{ {refuse_stmt(oid, _cs('носитель витража не найден (модель изменилась после grounding)'), isolation)} }}")

    # panel_type: пул под объединение «типы панелей + типы стен» не
    # существует, поэтому селектор разрешается здесь, ограниченным поиском по
    # обоим пространствам типов. Ноль и больше одного — типизированные
    # отказы; «первый попавшийся» запрещён (SPEC §2).
    by = sel.get("by")
    if by == "element_id":
        type_res = (
            f"__ct_{s} = doc.GetElement({_eid(sel['value'], ver, oid)}) "
            f"as ElementType;\n"
            f"if (__ct_{s} == null) {{ {refuse_stmt(oid, _cs('тип панели не найден (модель изменилась после grounding)'), isolation)} }}")
    elif by == "name":
        want = sel["value"]
        type_res = (
            f"var __cts_{s} = new List<ElementType>();\n"
            f"foreach (Element __cte_{s} in new FilteredElementCollector(doc)"
            f".OfClass(typeof(FamilySymbol)))\n"
            f"    if (__cte_{s}.Name == {_cs(want)}) "
            f"__cts_{s}.Add((ElementType)__cte_{s});\n"
            f"foreach (Element __ctw_{s} in new FilteredElementCollector(doc)"
            f".OfClass(typeof(WallType)))\n"
            f"    if (__ctw_{s}.Name == {_cs(want)}) "
            f"__cts_{s}.Add((ElementType)__ctw_{s});\n"
            f"if (__cts_{s}.Count == 0) {{ {refuse_stmt(oid, _cs('тип панели «' + want + '» не найден среди '
                              'типоразмеров семейств и типов стен'), isolation)} }}\n"
            f"if (__cts_{s}.Count > 1) {{ {refuse_stmt(oid, _cs('тип панели «' + want + '» неоднозначен — '
                              'несколько типов с этим именем; укажите '
                              'element_id'), isolation)} }}\n"
            f"__ct_{s} = __cts_{s}[0];")
    else:
        raise KirRefusal([Diagnostic(
            code=GROUND_BAD_SELECTOR, op_id=oid, field_name="panel_type",
            expected={"by": "name|element_id"}, got=sel,
            message_ru=("panel_type: у типа ячейки витража нет детерминированного "
                        "правила по умолчанию — назовите тип или его element_id"))])

    decl = (
        curtain_cell_address_cs(s) + "\n"
        f"Element __ch_{s} = null;\n"
        f"CurtainGrid __cg_{s} = null;\n"
        f"List<ElementId> __cu_{s} = null;\n"
        f"List<ElementId> __cv_{s} = null;\n"
        f"Element __cp_{s} = null;\n"
        f"Element __cq_{s} = null;\n"
        # ChangePanelType ВОЗВРАЩАЕТ элемент: «If operation succeeds, the
        # modified panel element is returned» (документация сборок). Для
        # WallType это НОВЫЙ элемент ячейки — старая Panel ею быть
        # перестаёт. Близнец урока ChangeTypeId: смена типа здесь —
        # ЗАМЕНА элемента, и свидетель, читающий старую ссылку, свидетель
        # мёртвого.
        f"Element __cn_{s} = null;\n"
        f"Element __co_{s} = null;\n"
        f"string __cpi_{s} = null;\n"
        f"bool __cch_{s} = false;\n"
        f"ElementType __ct_{s} = null;\n"
        # ПРОСТРАНСТВЕННАЯ ПРИВЯЗКА занявшего к носителю. Нужна потому, что
        # ячейку, занятую СТЕНОЙ, список панелей сетки не показывает вовсе
        # (замер E2: и после Regenerate, и после Commit GetPanelIds держит
        # старую авто-панель, а стена-занявший в списке отсутствует). У
        # такой стены и HOST_ID_PARAM пуст — параметром хост не читается.
        # Остаётся геометрия: середина её оси лежит НА оси носителя
        # (замер E2 дал ровно 0.0 мм). Допуск 50 мм — на дуговые носители,
        # где середина хорды отходит от оси.
        f"Func<Element, bool> __ccAxis{s} = (__cae_{s}) =>\n"
        f"{{\n"
        f"    if (__cae_{s} == null || __ch_{s} == null) return false;\n"
        f"    try\n"
        f"    {{\n"
        f"        LocationCurve __cah_{s} = __ch_{s}.Location as LocationCurve;\n"
        f"        LocationCurve __cao_{s} = __cae_{s}.Location as LocationCurve;\n"
        f"        if (__cah_{s} == null || __cao_{s} == null) return false;\n"
        f"        if (__cah_{s}.Curve == null || __cao_{s}.Curve == null) "
        f"return false;\n"
        f"        XYZ __cam_{s} = __cao_{s}.Curve.Evaluate(0.5, true);\n"
        f"        IntersectionResult __cap_{s} = "
        f"__cah_{s}.Curve.Project(__cam_{s});\n"
        f"        if (__cap_{s} == null) return false;\n"
        f"        return MM(__cap_{s}.Distance) <= 50.0;\n"
        f"    }}\n"
        f"    catch {{ return false; }}\n"
        f"}};")

    create = (
        f"// set_curtain_panel {cs_line_comment_fragment(oid)}\n"
        f"{host_res}\n"
        # Сетка витража и её панели рождаются РЕГЕНЕРАЦИЕЙ, а не вызовом
        # Wall.Create: до неё носитель, созданный этой же программой, знает
        # свой тип, но ещё не свои ячейки. Тот же класс, что «коннекторы
        # читаются только после регена» в CONNECT и `Activate()+Regenerate()`
        # в _symbol_res.
        #
        # ЗАМЕР 28.07 (живая проба П4): чтение сетки свежесозданной стены
        # прошло — ячейка нашлась, — а ЗАПИСЬ ChangePanelType бросила
        # исключение с пустым Message. Реген ставится перед всей работой с
        # сеткой, а не только перед записью: наполовину материализованную
        # сетку нельзя ни читать, ни менять, и стоит он одного прохода.
        #
        # Исключение регенерации НЕ глушится: по документации сборок
        # (Document.Regenerate) провал регена означает испорченный документ,
        # и владелец транзакции обязан её оборвать, а не продолжать.
        f"doc.Regenerate();\n"
        f"var __cgs_{s} = __ccGrids{s}(__ch_{s});\n"
        f"if (__cgs_{s}.Count == 0) {{ {refuse_stmt(oid, _cs('у носителя нет витражной сетки — ячейку назначать нечему'), isolation)} }}\n"
        f"if (__cgs_{s}.Count > 1) {{ {refuse_stmt(oid, _cs('у носителя несколько витражных сеток — адрес (u,v) неоднозначен'), isolation)} }}\n"
        f"__cg_{s} = __cgs_{s}[0];\n"
        f"__cu_{s} = __ccOrder{s}(__cg_{s}.GetUGridLineIds());\n"
        f"__cv_{s} = __ccOrder{s}(__cg_{s}.GetVGridLineIds());\n"
        f"if (__cu_{s} == null || __cv_{s} == null) {{ {refuse_stmt(oid, _cs('порядок линий разрезки не определён (нечитаемая кривая или две линии на одном месте) — адреса ячейки нет'), isolation)} }}\n"
        f"if ({u} > __cu_{s}.Count || {v} > __cv_{s}.Count) {{ {refuse_stmt(oid, f'\"адрес ячейки вне сетки носителя: ({u},{v}) при \" + __cu_{s}.Count + \"×\" + __cv_{s}.Count + \" линиях\"', isolation)} }}\n"
        f"__cp_{s} = __ccPanelAt{s}(__cg_{s}, __cu_{s}, __cv_{s}, {u}, {v});\n"
        f"if (__cp_{s} == null) {{ {refuse_stmt(oid, f'\"ячейка ({u},{v}) не найдена в сетке носителя\"', isolation)} }}\n"
        f"__cpi_{s} = __cp_{s}.Id.ToString();\n"
        f"{type_res}\n"
        # ЗАМОК ЯЧЕЙКИ. Панель, порождённая ТИПОМ носителя, у Revit
        # «type-driven» и заперта: в словаре отказов сборок это
        # BuiltInFailures.CurtainWallFailures.
        # TypePanelsFronNonRectCellsUnlocked — «Type-driven panels … were
        # UNLOCKED and left unchanged», то есть отпирание и есть штатная
        # операция Revit над ровно этим классом панелей.
        #
        # ЗАМЕР 28.07, живые пробы П6 и П7 (фасад SOB6.2, Revit 2023): обе
        # вернули ОДНО И ТО ЖЕ — «InvalidOperationException: (пустое
        # сообщение Revit) … РАЗБЛОКИРОВАНА=НЕТ». П6 шла по УЖЕ
        # существующему носителю (значит транзакция ни при чём), П7 — с
        # PanelType вместо WallType (значит вид типа ни при чём). Остался
        # замок.
        #
        # Отпирание — не хак, а ТОЧНОЕ ВОСПРОИЗВЕДЕНИЕ авторского действия:
        # все 53 поднятые ячейки фасада ЗАМЕНЁННЫЕ, значит в оригинале их
        # отперли руками. Обратно панель не запирается: запертой она в
        # исходнике и не была.
        #
        # Глагол отпирания — Element.Pinned (замер по сборкам 2021-2026): у
        # Panel есть только Lockable {get;} без сеттера, а Lock {get;set;}
        # существует у Mullion, не у панели. Pinned живёт на Element,
        # поэтому один и тот же код отпирает и Panel, и ячейку-СТЕНУ —
        # GetPanelIds по документации сборок отдаёт оба класса.
        f"bool __clk_{s} = true;\n"
        f"try {{ foreach (ElementId __cli_{s} in "
        f"__cg_{s}.GetUnlockedPanelIds())\n"
        f"    if (__cli_{s}.ToString() == __cp_{s}.Id.ToString()) "
        f"{{ __clk_{s} = false; break; }} }} catch {{ }}\n"
        f"bool __cpn_{s} = false;\n"
        f"try {{ __cpn_{s} = __cp_{s}.Pinned; }} catch {{ }}\n"
        f"if (__clk_{s} || __cpn_{s})\n"
        f"{{\n"
        f"    try {{ __cp_{s}.Pinned = false; }}\n"
        f"    catch (Exception __cux_{s})\n"
        f"    {{\n"
        f"        {refuse_stmt(oid, '"замок ячейки не снимается для " + '
                              f'__ClassName(__cp_{s}) + " (панель " + '
                              f'__cp_{s}.Id.ToString() + "): " + '
                              f'__ClassName(__cux_{s}) + ": " + '
                              f'(String.IsNullOrEmpty(__cux_{s}.Message) ? '
                              '"(пустое сообщение Revit)" : '
                              f'__cux_{s}.Message)', isolation)}\n"
        f"    }}\n"
        f"}}\n"
        # УЛИКА, А НЕ ПУСТАЯ СТРОКА. Revit бросает из ChangePanelType с
        # ПУСТЫМ Message (замер: живая проба П4 вернула ровно
        # «ChangePanelType: » и ничего больше — час на догадки вместо
        # секунды на чтение). Поэтому в отказ идёт всё, что отличает один
        # случай от другого: класс исключения, внутреннее исключение,
        # КЛАССЫ панели и нового типа (GetPanelIds по документации сборок
        # отдаёт и Panel, и Wall), id носителя, адрес ячейки и признак
        # разблокированности — GetUnlockedPanelIds существует именно
        # потому, что запертую панель менять нельзя.
        f"try {{ __cn_{s} = __cg_{s}.ChangePanelType(__cp_{s}, __ct_{s}); }}\n"
        f"catch (Exception __cex_{s})\n"
        f"{{\n"
        f"    string __cdg_{s} = __ClassName(__cex_{s}) + \": \" + "
        f"(String.IsNullOrEmpty(__cex_{s}.Message) ? \"(пустое сообщение "
        f"Revit)\" : __cex_{s}.Message);\n"
        f"    if (__cex_{s}.InnerException != null)\n"
        f"        __cdg_{s} += \" | внутреннее \" + "
        f"__ClassName(__cex_{s}.InnerException) + \": \" + "
        f"(__cex_{s}.InnerException.Message ?? \"\");\n"
        f"    bool __cul_{s} = false;\n"
        f"    try {{ foreach (ElementId __cui_{s} in "
        f"__cg_{s}.GetUnlockedPanelIds())\n"
        f"        if (__cui_{s}.ToString() == __cp_{s}.Id.ToString()) "
        f"{{ __cul_{s} = true; break; }} }} catch {{ }}\n"
        f"    __cdg_{s} += \" | до отпирания: заперта=\" + "
        f"(__clk_{s} ? \"да\" : \"нет\") + \", pinned=\" + "
        f"(__cpn_{s} ? \"да\" : \"нет\");\n"
        f"    __cdg_{s} += \" | ячейка ({u},{v}) панель \" + "
        f"__cp_{s}.Id.ToString() + \" (\" + __ClassName(__cp_{s}) + "
        f"\"), разблокирована=\" + (__cul_{s} ? \"да\" : \"нет\")"
        f" + \", новый тип \" + __ct_{s}.Id.ToString() + \" (\" + "
        f"__ClassName(__ct_{s}) + \"), носитель \" + "
        f"__ch_{s}.Id.ToString();\n"
        f"    {refuse_stmt(oid, f'\"ChangePanelType: \" + __cdg_{s}', isolation)}\n"
        f"}}\n"
        # ДОГОН ТИПА. ChangePanelType с типом СТЕНЫ строит стену, но НЕ ТОГО
        # типа: замер E1 на живом носителе — возврат id=11401344, класс Wall,
        # тип 7469627 (тип разрезки носителя), тогда как просили 273445.
        # Молча, без исключения. Повторный вызов идемпотентно возвращает ту
        # же чужую стену.
        #
        # Лечится вторым шагом, и он документирован сборками ровно для этого
        # случая — Element.ChangeTypeId: «In rare cases, applying a change in
        # type will result in a new element being created. The ONLY active
        # examples of this are when applying a normal wall type to a curtain
        # panel, or converting such a wall back to a curtain panel. In this
        # situation the new element id is returned. Also, this element becomes
        # invalid.» Возврат: «The new element id if new element is created, or
        # InvalidElementId if the element's type changed without creating a
        # new element».
        #
        # То есть -1 из ChangeTypeId — ОБЫЧНЫЙ УСПЕХ (замер E3), а не отказ:
        # тот же близнец-урок, что и в ChangeTypeId у прочих опов. Не-(-1)
        # означает, что занявший заменён ЕЩЁ РАЗ, и читать надо новый id.
        f"if (__cn_{s} != null)\n"
        f"{{\n"
        f"    ElementId __cnt_{s} = null;\n"
        f"    try {{ __cnt_{s} = __cn_{s}.GetTypeId(); }} catch {{ }}\n"
        f"    if (__cnt_{s} == null || __cnt_{s}.ToString() != "
        f"__ct_{s}.Id.ToString())\n"
        f"    {{\n"
        f"        try\n"
        f"        {{\n"
        f"            ElementId __cnr_{s} = "
        f"__cn_{s}.ChangeTypeId(__ct_{s}.Id);\n"
        f"            __cch_{s} = true;\n"
        f"            if (__cnr_{s} != null && __cnr_{s}.ToString() != "
        f"ElementId.InvalidElementId.ToString())\n"
        f"            {{\n"
        f"                Element __cnw_{s} = doc.GetElement(__cnr_{s});\n"
        f"                if (__cnw_{s} != null) __cn_{s} = __cnw_{s};\n"
        f"            }}\n"
        f"        }}\n"
        f"        catch (Exception __ctx_{s})\n"
        f"        {{\n"
        f"            {refuse_stmt(oid, '"догон типа ячейки не прошёл: " + '
                                  f'__ClassName(__ctx_{s}) + ": " + '
                                  f'(String.IsNullOrEmpty(__ctx_{s}.Message) ? '
                                  '"(пустое сообщение Revit)" : '
                                  f'__ctx_{s}.Message) + " | занявший " + '
                                  f'__cn_{s}.Id.ToString() + " (" + '
                                  f'__ClassName(__cn_{s}) + "), просили тип " '
                                  f'+ __ct_{s}.Id.ToString()', isolation)}\n"
        f"        }}\n"
        f"    }}\n"
        f"}}")

    create += (
        "\n"
        # ШТАМП — на то, что мы СОЗДАЛИ, и только на это.
        #
        # Пересборка №5 (замер 28.07, артефакт v10): 1236 созданных против
        # переписи штампа — фаза RECONCILED упала «run-prefix reconciliation
        # disagrees with commit receipts». Причина здесь: ячейку занимал
        # НОВЫЙ элемент (ChangePanelType с типом стены рождает стену), его id
        # ехал в created_ids, а штампа на нём не было — перепись такого не
        # видит, потому что видит ровно штампованное. 54 опа ячейки в плане.
        #
        # Условие «только созданное» не косметика: A5 УДАЛЯЕТ по штампу.
        # Пометить ячейку, которая существовала до нас (тип сменён на месте,
        # элемент тот же), значило бы объявить чужой элемент своим — и снести
        # его на уборке.
        f"if (__cn_{s} != null && __cn_{s}.Id.ToString() != __cpi_{s})\n"
        f"{{\n"
        + _indent(_stamp_block(f"__cn_{s}", stamp), "    ") + "\n"
        f"}}")

    post = [
        WitnessCheck(
            obligation_key="panel_type",
            reader_cs=(
                # ДВА независимых чтения модели, ни одно не «эхо вызова»:
                #   * ячейка ищется ЗАНОВО ПО АДРЕСУ — это проверка того,
                #     что мы поменяли именно ту ячейку;
                #   * возвращённый вызовом элемент принимается за занявшего
                #     ТОЛЬКО после проверки, что он состоит в списке панелей
                #     ЭТОЙ сетки. Ссылка от вызова — это id, а не утверждение
                #     о состоянии; состояние всё равно читается из модели
                #     после Regenerate.
                # Адресный поиск умеет только Panel (GetRefGridLines живёт
                # на ней), а ячейку, занятую СТЕНОЙ, адресовать нечем —
                # поэтому у возвращённого элемента приоритет, когда он в
                # сетке; иначе остаётся адресный.
                f"    __cq_{s} = __ccPanelAt{s}(__cg_{s}, "
                f"__ccOrder{s}(__cg_{s}.GetUGridLineIds()), "
                f"__ccOrder{s}(__cg_{s}.GetVGridLineIds()), {u}, {v});\n"
                f"    if (__cn_{s} != null)\n"
                f"    {{\n"
                f"        bool __cnm_{s} = false;\n"
                f"        if (__cn_{s} is FamilyInstance)\n"
                f"        {{\n"
                f"            try {{ foreach (ElementId __cni_{s} in "
                f"__cg_{s}.GetPanelIds())\n"
                f"                if (__cni_{s}.ToString() == "
                f"__cn_{s}.Id.ToString()) {{ __cnm_{s} = true; break; }} }} "
                f"catch {{ }}\n"
                f"        }}\n"
                f"        else __cnm_{s} = __ccAxis{s}(__cn_{s});\n"
                f"        if (__cnm_{s}) __co_{s} = __cn_{s};\n"
                f"    }}\n"
                f"    if (__co_{s} == null) __co_{s} = __cq_{s};\n"),
            verdict_cs=(
                f"    if (__co_{s} == null)\n"
                f"        __post.Add({_cs(oid + ': ячейка (%d,%d) не читается '
                                          'после сборки (semantic)' % (u, v))});\n"
                f"    else\n"
                f"    {{\n"
                f"        ElementId __cet_{s} = __ccEffType{s}(__co_{s});\n"
                f"        if (__cet_{s} == null || __cet_{s}.ToString() != "
                f"__ct_{s}.Id.ToString())\n"
                f"            __post.Add({_cs(oid + ': тип панели в ячейке не '
                                              'равен запрошенному (semantic)')});\n"
                f"    }}\n"),
            message="тип панели в ячейке не равен запрошенному (semantic)",
            style="else_block"),
        WitnessCheck(
            obligation_key="cell_host",
            reader_cs="",
            verdict_cs=(
                # Ячейку, занятую СТЕНОЙ, `as FamilyInstance` не берёт —
                # у неё нет свойства Host. Принадлежность носителю тогда
                # доказывает СПИСОК ПАНЕЛЕЙ САМОЙ СЕТКИ: это чтение модели,
                # а не поблажка. Для FamilyInstance остаётся прежняя, более
                # сильная проверка ссылки Host.
                f"    {{\n"
                f"        FamilyInstance __cfi_{s} = __co_{s} as FamilyInstance;\n"
                f"        if (__cfi_{s} != null)\n"
                f"        {{\n"
                f"            if (__cfi_{s}.Host == null\n"
                f"                || __cfi_{s}.Host.Id.ToString() != "
                f"__ch_{s}.Id.ToString())\n"
                f"                __post.Add({_cs(oid + ': ячейка принадлежит '
                                                  'другому носителю (topology)')});\n"
                f"        }}\n"
                f"        else\n"
                f"        {{\n"
                # Список панелей сетки для ячейки-СТЕНЫ ЛОЖНО-ОТРИЦАТЕЛЕН
                # ВСЕГДА (замер E2: стена-занявший не появляется в
                # GetPanelIds ни после Regenerate, ни после Commit).
                # Принадлежность носителю доказывает ось: середина оси
                # занявшего лежит на оси носителя.
                f"            bool __chm_{s} = __ccAxis{s}(__co_{s});\n"
                f"            if (!__chm_{s})\n"
                f"                __post.Add({_cs(oid + ': ячейка принадлежит '
                                                  'другому носителю (topology)')});\n"
                f"        }}\n"
                f"    }}\n"),
            message="ячейка принадлежит другому носителю (topology)",
            style="guard"),
    ]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"host_id\"] = __ch_{s}.Id.ToString();\n"
        f"    __rb[\"u\"] = {u};\n"
        f"    __rb[\"v\"] = {v};\n"
        f"    __rb[\"requested_type_id\"] = __ct_{s}.Id.ToString();\n"
        f"    __rb[\"requested_type_name\"] = __ct_{s}.Name;\n"
        # ЗАМЕНА ЭЛЕМЕНТА — факт, а не догадка: в квитанции стоят оба id.
        # Для WallType ячейку занимает НОВЫЙ элемент (класс Wall), и это
        # ожидаемо; молчаливая подмена id была бы неотличима от «ничего не
        # произошло».
        f"    __rb[\"old_panel_id\"] = __cpi_{s};\n"
        f"    if (__cn_{s} != null) __rb[\"returned_panel_id\"] = "
        f"__cn_{s}.Id.ToString();\n"
        f"    if (__cq_{s} != null) __rb[\"addressed_panel_id\"] = "
        f"__cq_{s}.Id.ToString();\n"
        f"    if (__co_{s} != null)\n"
        f"    {{\n"
        # Закон переписи (serving KIR-X008): у пишущего опа в квитанции
        # обязан быть ключ идентичности `id`. Занявший ячейку — и есть
        # элемент этого опа; `panel_id` остаётся как говорящий дубль.
        f"        __rb[\"id\"] = __co_{s}.Id.ToString();\n"
        f"        __rb[\"panel_id\"] = __co_{s}.Id.ToString();\n"
        f"        __rb[\"panel_replaced\"] = "
        f"(__co_{s}.Id.ToString() != __cpi_{s});\n"
        # `created` отделяет СОЗДАНИЕ от смены типа на месте. Закон
        # переписи требует ключ `id` у всякого пишущего опа — но `id` это
        # ИДЕНТИЧНОСТЬ, а не свидетельство рождения. Уборка A5 удаляет
        # созданное, поэтому она обязана различать эти два случая.
        f"        __rb[\"created\"] = "
        f"(__co_{s}.Id.ToString() != __cpi_{s});\n"
        f"        __rb[\"type_chased\"] = __cch_{s};\n"
        f"        __rb[\"panel_class\"] = __ClassName(__co_{s});\n"
        f"        bool __rbl_{s} = false;\n"
        f"        try {{ foreach (ElementId __rbi_{s} in "
        f"__cg_{s}.GetUnlockedPanelIds())\n"
        f"            if (__rbi_{s}.ToString() == __co_{s}.Id.ToString()) "
        f"{{ __rbl_{s} = true; break; }} }} catch {{ }}\n"
        f"        bool __rbp_{s} = false;\n"
        f"        try {{ __rbp_{s} = __co_{s}.Pinned; }} catch {{ }}\n"
        f"        __rb[\"panel_lock\"] = (__rbl_{s} ? \"разблокирована\" "
        f": \"заперта\") + \", pinned=\" + (__rbp_{s} ? \"да\" : \"нет\");\n"
        f"        ElementId __rbt_{s} = __ccEffType{s}(__co_{s});\n"
        f"        if (__rbt_{s} != null)\n"
        f"        {{\n"
        f"            __rb[\"panel_type_id\"] = __rbt_{s}.ToString();\n"
        f"            Element __rbe_{s} = doc.GetElement(__rbt_{s});\n"
        f"            if (__rbe_{s} != null) __rb[\"panel_type_name\"] = "
        f"__rbe_{s}.Name;\n"
        f"        }}\n"
        f"    }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")

    return decl, create, post, readback


#: Радиус, в котором импост считается стоящим НА этой линии разрезки.
#: Это улика для квитанции — «поставил ли тип носителя импосты сам», — а не
#: обязательство опа, поэтому число живёт здесь, а не в реестре допусков
#: свидетелей: там оно означало бы обещание, которого оп не даёт.
_MULLION_ON_LINE_EVIDENCE_MM = 10.0


def _emit_create_curtain_grid_line(op: dict, ver: str, stamp: str,
                                   isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Линия разрезки витража — состояние, которого create_wall не несёт.

    ЗАЧЕМ ОП ВООБЩЕ ЕСТЬ. Замер ночи 28.07 (child_closure_20260728.json):
    замыкание детей 417/1556 = 27%, и у ВСЕХ пересобранных носителей НОЛЬ
    внутренних U/V линий при байт-идентичных типах. Раскладка сетки —
    авторское состояние, а не следствие типа; без неё носитель приходит
    пустым, и вместе с ней не воспроизводится вся его семья: ячейки,
    панели, импосты.

    СВИДЕТЕЛЬ ЧИТАЕТ РЕЗУЛЬТАТ, А НЕ ВОЗВРАТ ВЫЗОВА. ``AddGridLine``
    возвращает объект, но состояние берётся перечитыванием ПО ID после
    ``Regenerate``: принадлежность сетке доказывается СПИСКОМ линий этой
    сетки, направление — ``IsUGridLine``, положение — расстоянием от
    запрошенной точки до ``FullCurve``. Возврат вызова доказывал бы лишь
    то, что вызов состоялся.

    ШТАМП. У A5 штамп — не косметика: по нему идёт сверка созданного и
    уборка. Если линия разрезки не принимает ``Comments``, оп
    ТИПИЗИРОВАННО отказывает, а не роняет транзакцию и не оставляет
    непомеченного созданного элемента (он сломал бы фазу RECONCILED,
    которая требует РАВЕНСТВА переписи штампа и созданных id). В обычной
    (чатовой) эмиссии тот же штамп молчалив, как у всех опов.
    """

    oid = op["id"]
    s_ = _safe(oid)
    host = op["host"]
    direction = str(op["direction"])
    is_u = "true" if direction == "u" else "false"
    px, py, pz = _pt3(op["position_mm"])
    tol = tolerance("create_curtain_grid_line", "position_mm")
    mul_tol = _MULLION_ON_LINE_EVIDENCE_MM

    if host["by"] == "ref":
        host_res = f"__gh_{s_} = (Element)__el_{_safe(host['value'])};"
    else:
        host_res = (
            f"__gh_{s_} = doc.GetElement({_eid(host['value'], ver, oid)});\n"
            f"if (__gh_{s_} == null) {{ {refuse_stmt(oid, _cs('носитель витража не найден (модель изменилась после grounding)'), isolation)} }}")

    decl = (
        curtain_cell_address_cs(s_) + "\n"
        f"Element __gh_{s_} = null;\n"
        f"CurtainGrid __gg_{s_} = null;\n"
        f"CurtainGridLine __gl_{s_} = null;\n"
        f"CurtainGridLine __gr_{s_} = null;\n"
        f"XYZ __gp_{s_} = null;\n"
        f"string __gli_{s_} = null;\n"
        f"bool __gmem_{s_} = false;\n"
        f"bool __gisu_{s_} = false;\n"
        f"double __gdel_{s_} = -1.0;\n"
        f"int __gmul_{s_} = -1;\n"
        # Расстояние от запрошенной точки до кривой линии — ЕДИНСТВЕННОЕ
        # честное измерение «встала ли линия туда, куда просили»: концы
        # сравнивать нельзя, длину линии задаёт носитель, а не мы.
        f"Func<CurtainGridLine, XYZ, double> __gDist{s_} = "
        f"(__gdl_{s_}, __gdp_{s_}) =>\n"
        f"{{\n"
        f"    if (__gdl_{s_} == null || __gdp_{s_} == null) return -1.0;\n"
        f"    try\n"
        f"    {{\n"
        f"        Curve __gdc_{s_} = __gdl_{s_}.FullCurve;\n"
        f"        if (__gdc_{s_} == null) return -1.0;\n"
        f"        IntersectionResult __gdr_{s_} = "
        f"__gdc_{s_}.Project(__gdp_{s_});\n"
        f"        if (__gdr_{s_} == null) return -1.0;\n"
        f"        return MM(__gdr_{s_}.Distance);\n"
        f"    }}\n"
        f"    catch {{ return -1.0; }}\n"
        f"}};\n"
        # Принадлежность линии ЭТОЙ сетке — чтение модели списком, а не
        # доверие к возврату вызова.
        f"Func<CurtainGrid, string, bool, bool> __gMem{s_} = "
        f"(__gmg_{s_}, __gmi_{s_}, __gmu_{s_}) =>\n"
        f"{{\n"
        f"    if (__gmg_{s_} == null || __gmi_{s_} == null) return false;\n"
        f"    try\n"
        f"    {{\n"
        f"        ICollection<ElementId> __gms_{s_} = __gmu_{s_}\n"
        f"            ? __gmg_{s_}.GetUGridLineIds()\n"
        f"            : __gmg_{s_}.GetVGridLineIds();\n"
        f"        if (__gms_{s_} == null) return false;\n"
        f"        foreach (ElementId __gme_{s_} in __gms_{s_})\n"
        f"            if (__gme_{s_}.ToString() == __gmi_{s_}) return true;\n"
        f"    }}\n"
        f"    catch {{ }}\n"
        f"    return false;\n"
        f"}};")

    create = (
        f"// create_curtain_grid_line {cs_line_comment_fragment(oid)}\n"
        f"{host_res}\n"
        # Сетка витража рождается РЕГЕНЕРАЦИЕЙ: у носителя, созданного этой
        # же программой, до неё есть тип, но ещё нет сетки (тот же урок,
        # что стоил живой пробы П4 у ячейки).
        f"doc.Regenerate();\n"
        f"var __ggs_{s_} = __ccGrids{s_}(__gh_{s_});\n"
        f"if (__ggs_{s_}.Count == 0) {{ {refuse_stmt(oid, _cs('у носителя нет витражной сетки — линию разрезки ставить некуда'), isolation)} }}\n"
        f"if (__ggs_{s_}.Count > 1) {{ {refuse_stmt(oid, _cs('у носителя несколько витражных сеток — в какую ставить линию, неизвестно'), isolation)} }}\n"
        f"__gg_{s_} = __ggs_{s_}[0];\n"
        f"__gp_{s_} = P({px}, {py}, {pz});\n"
        # Пустое сообщение Revit уже стоило круга на ячейке: в отказ идёт
        # всё, что различает случаи.
        f"try {{ __gl_{s_} = __gg_{s_}.AddGridLine({is_u}, __gp_{s_}, false); }}\n"
        f"catch (Exception __gex_{s_})\n"
        f"{{\n"
        f"    string __gdg_{s_} = __ClassName(__gex_{s_}) + \": \" + "
        f"(String.IsNullOrEmpty(__gex_{s_}.Message) ? \"(пустое сообщение "
        f"Revit)\" : __gex_{s_}.Message);\n"
        f"    if (__gex_{s_}.InnerException != null)\n"
        f"        __gdg_{s_} += \" | внутреннее \" + "
        f"__ClassName(__gex_{s_}.InnerException) + \": \" + "
        f"(__gex_{s_}.InnerException.Message ?? \"\");\n"
        f"    __gdg_{s_} += \" | носитель \" + __gh_{s_}.Id.ToString() + "
        f"\" (\" + __ClassName(__gh_{s_}) + \"), направление "
        f"{direction}, точка ({px}, {py}, {pz}) мм\";\n"
        # ПУСТОЕ СООБЩЕНИЕ РЕВИТА — ОТДЕЛЬНЫЙ ИСХОД, И У НЕГО ЕСТЬ ЗАМЕР.
        # 26.08.2026, живая стена 0..4000: точка с z=0, то есть РОВНО на
        # нижнем ребре носителя, даёт `ArgumentException` без единого слова.
        # Раньше автор получал имя класса исключения и ничего больше.
        f"    if (String.IsNullOrEmpty(__gex_{s_}.Message))\n"
        f"        __gdg_{s_} += \" | пустое сообщение у этого вызова "
        f"замерено 26.08.2026 на точке, лежавшей РОВНО НА ГРАНИЦЕ носителя "
        f"(z равнялся отметке низа стены): сдвинь точку ВНУТРЬ носителя\";\n"
        f"    __gdg_{s_} += \" | \" + "
        f"__KirGridOcc(__gg_{s_}, {is_u}, __gp_{s_});\n"
        f"    {refuse_stmt(oid, f'\"AddGridLine: \" + __gdg_{s_}', isolation)}\n"
        f"}}\n"
        # 🔴 ОТКАЗ, НАЗЫВАЮЩИЙ НЕВЫПОЛНИМЫЙ ХОД, ДОРОЖЕ ОТКАЗА, НЕ
        # НАЗЫВАЮЩЕГО НИКАКОГО (закон `ground.py`). Здесь стояло голое
        # «AddGridLine вернул null — линия не создана»: не названо НИЧЕГО —
        # ни ось, ни занятое, ни следующий ход.
        #
        # ЦЕНА НАЗВАНА ЧИСЛОМ. Марафон 26.08: 17 попыток пачкой за 630 с и
        # 15 вызовов по одной за 529 с, четыре линии так и не легли. Модель
        # двигала X, держа Z, и каждый раз просила ОДНУ И ТУ ЖЕ линию —
        # потому что из отказа нельзя было узнать, какая координата значима.
        f"if (__gl_{s_} == null)\n"
        f"{{\n"
        f"    string __gnl_{s_} = \"AddGridLine вернул null — линия не "
        f"создана. Запрошено: направление {direction}, точка "
        f"({px}, {py}, {pz}) мм. \" + "
        f"__KirGridOcc(__gg_{s_}, {is_u}, __gp_{s_});\n"
        f"    {refuse_stmt(oid, f'__gnl_{s_}', isolation)}\n"
        f"}}\n"
        f"__gli_{s_} = __gl_{s_}.Id.ToString();\n"
        # Линия материализуется регенерацией: до неё ни FullCurve, ни
        # членство в списке сетки читать нельзя.
        f"doc.Regenerate();\n"
        f"__gr_{s_} = doc.GetElement(__gl_{s_}.Id) as CurtainGridLine;\n"
        f"if (__gr_{s_} == null) {{ {refuse_stmt(oid, f'\"созданная линия \" + __gli_{s_} + \" не читается после Regenerate\"', isolation)} }}\n"
        # ШТАМП. Для A5 отсутствие параметра — типизированный отказ, а не
        # исключение: непомеченный созданный элемент ломает RECONCILED (она
        # требует равенства переписи штампа и созданных id), и узнать об
        # этом на живом прогоне дороже, чем отказать здесь.
        f"try\n"
        f"{{\n"
        + _indent(_stamp_block(f"__gr_{s_}", stamp), "    ") + "\n"
        f"}}\n"
        f"catch (Exception __gsx_{s_})\n"
        f"{{\n"
        f"    {refuse_stmt(oid, '"линия разрезки не принимает штамп прогона (" + '
                          f'__gsx_{s_}.Message + ") — созданный, но непомеченный '
                          'элемент сломал бы сверку пересборки"', isolation)}\n"
        f"}}")

    post = [
        WitnessCheck(
            obligation_key="grid_membership",
            reader_cs=(
                f"    __gmem_{s_} = __gMem{s_}(__gg_{s_}, __gli_{s_}, "
                f"{is_u});\n"
                f"    try {{ __gisu_{s_} = __gr_{s_}.IsUGridLine; }} "
                f"catch {{ }}\n"
                f"    __gdel_{s_} = __gDist{s_}(__gr_{s_}, __gp_{s_});\n"),
            verdict_cs=(
                f"    if (!__gmem_{s_})\n"
                f"        __post.Add({_cs(oid + ': созданная линия не состоит '
                                          'в сетке носителя (topology)')});\n"),
            message="созданная линия не состоит в сетке носителя (topology)",
            style="else_block"),
        WitnessCheck(
            obligation_key="direction",
            reader_cs="",
            verdict_cs=(
                f"    if (__gisu_{s_} != {is_u})\n"
                f"        __post.Add({_cs(oid + ': направление линии не равно '
                                          'запрошенному (semantic)')});\n"),
            message="направление линии не равно запрошенному (semantic)",
            style="guard"),
        WitnessCheck(
            obligation_key="position_mm",
            reader_cs="",
            verdict_cs=(
                # -1 — «не измерено»: нечитаемая кривая обязана быть
                # отказом, а не молчаливым успехом.
                f"    if (__gdel_{s_} < 0.0 || __gdel_{s_} > {tol})\n"
                f"        __post.Add({_cs(oid + ': линия не проходит через '
                                          'запрошенную точку (geometry)')});\n"),
            message="линия не проходит через запрошенную точку (geometry)",
            tol=tol,
            style="guard"),
    ]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        # Закон переписи (KIR-X008): у пишущего опа в квитанции обязан быть
        # ключ идентичности `id`. Линию мы СОЗДАЛИ — `created` говорит это
        # прямо, потому что по нему A5 решает, что удалять на уборке.
        f"    __rb[\"id\"] = __gli_{s_};\n"
        f"    __rb[\"grid_line_id\"] = __gli_{s_};\n"
        f"    __rb[\"created\"] = true;\n"
        f"    __rb[\"host_id\"] = __gh_{s_}.Id.ToString();\n"
        f"    __rb[\"direction\"] = {_cs(direction)};\n"
        f"    __rb[\"is_u_grid_line\"] = __gisu_{s_};\n"
        f"    __rb[\"in_grid\"] = __gmem_{s_};\n"
        f"    __rb[\"position_mm\"] = new double[] "
        f"{{ {px}, {py}, {pz} }};\n"
        f"    __rb[\"position_delta_mm\"] = __gdel_{s_};\n"
        # ИМПОСТЫ НА НОВОЙ ЛИНИИ — УЛИКА, А НЕ ОБЯЗАТЕЛЬСТВО.
        #
        # Ставит ли тип носителя импосты на свежесозданную линию сам, знает
        # только живой Revit; документация сборок этого не решает ни в одну
        # сторону. Поэтому оп НЕ зовёт AddMullions (лишний вызов удвоил бы
        # импосты там, где они появляются сами) и НЕ обещает их в
        # постусловии — он ЗАМЕРЯЕТ их число на созданной линии и кладёт в
        # квитанцию. Следующая волна получит ответ ЧИСЛОМ с живого прогона.
        f"    try\n"
        f"    {{\n"
        f"        int __rbm_{s_} = 0;\n"
        f"        ICollection<ElementId> __rbi_{s_} = "
        f"__gg_{s_}.GetMullionIds();\n"
        f"        if (__rbi_{s_} != null)\n"
        f"            foreach (ElementId __rbe_{s_} in __rbi_{s_})\n"
        f"            {{\n"
        f"                Mullion __rbu_{s_} = doc.GetElement(__rbe_{s_}) "
        f"as Mullion;\n"
        f"                if (__rbu_{s_} == null) continue;\n"
        f"                Curve __rbc_{s_} = __rbu_{s_}.LocationCurve;\n"
        f"                if (__rbc_{s_} == null) continue;\n"
        f"                double __rbd_{s_} = __gDist{s_}(__gr_{s_}, "
        f"__rbc_{s_}.Evaluate(0.5, true));\n"
        f"                if (__rbd_{s_} >= 0.0 && __rbd_{s_} <= {mul_tol}) "
        f"__rbm_{s_}++;\n"
        f"            }}\n"
        f"        __gmul_{s_} = __rbm_{s_};\n"
        f"    }}\n"
        f"    catch {{ }}\n"
        f"    __rb[\"mullions_on_line\"] = __gmul_{s_};\n"
        f"    try {{ __rb[\"line_locked\"] = __gr_{s_}.Lock; }} catch {{ }}\n"
        + _stamp_readback(f"__gr_{s_}") +
        f"    __results[{_cs(oid)}] = __rb;\n}}")

    return decl, create, post, readback



#: Опы, чей результат — ПРОСТРАНСТВЕННЫЙ элемент. ВЫВОДИТСЯ из реестра по
#: категории результата, а не перечисляется: список имён протух бы на первом
#: же новом пространственном опе, и протух бы МОЛЧА — программа просто
#: перестала бы получать регенерацию.
_SPATIAL_ENCLOSURE_OPS = frozenset(
    name for name, cats in spec.OP_RESULT_CATEGORIES.items()
    if set(cats) & set(ops_room.SPATIAL_ENCLOSURE_CATEGORIES))

#: Строка регенерации перед пространственным опом. ИМЕНОВАНА, ПОТОМУ ЧТО ЕЁ
#: ЧИТАЮТ СНАРУЖИ. `tests/test_regen_before_spatial.py` искал её в испущенном
#: C# по СВОЕЙ копии текста — и та копия отстала: тест держал `// finalize`,
#: эмиттер писал `// realise everything…`, `find` возвращал -1, и три теста
#: правила падали сутки с сообщением «−1 не больше 2633», которое не называет
#: причину вовсе. Величина объявлялась здесь и читалась там, и ничто не
#: заставляло их совпасть — тот же класс, что весь остальной день.
#: Комментарий В СТРОКЕ обязателен: в одной программе `doc.Regenerate()`
#: встречается дважды (второй — коммит-гейт после всех создателей), и без
#: текста отличить их в испущенном C# нечем.
SPATIAL_REGEN_CS = (
    "doc.Regenerate();  // realise everything created above "
    "before the enclosure is resolved")

#: Эмиттеры, чьи ТЕЛА живут в этом файле. Тела, уехавшие в спутники,
#: объявлены там же, где лежат, и присоединяются ниже сборкой.
_EMITTERS = {
    'create_wall': _emit_wall,
    'create_pipe': _emit_pipe,
    'create_grid': _emit_grid,
    'create_level': _emit_level,
    'create_floor_plan': _emit_floor_plan,
    'create_floor': _emit_floor,
    'create_column': _emit_column,
    'create_window': _emit_window,
    'create_door': _emit_door,
    'create_room': _emit_room,
    'place_family': _emit_place,
    'create_pipe_system': _emit_pipe_system,
    'create_floor_by_contour': _emit_floor_contour,
    'set_param': _emit_setparam,
    'delete': _emit_delete,
    'create_duct': _emit_duct,
    'create_cable_tray': _emit_cable_tray,
    'create_roof': _emit_roof,
    'route_pipe_system': _emit_route_pipe_system,
    'route_duct_system': _emit_route_duct_system,
    'create_type': _emit_create_type,
    'load_family': _emit_load_family,
    'create_wall_type': _emit_create_wall_type,
    'transfer_material': _emit_transfer_material,
    'create_dimension': _emit_dimension,
    'create_angular_dimension': _emit_angular_dimension,
    'create_tag': _emit_tag,
    'create_text': _emit_text,
    'create_filled_region': _emit_filled_region,
    'create_group': _emit_group,
    'set_curtain_panel': _emit_set_curtain_panel,
    'create_curtain_grid_line': _emit_create_curtain_grid_line,
    'move_elements': _emit_move_elements,
    'change_type': _emit_change_type,
    'join_elements': _emit_join_elements,
}


# 🔴 РЕЕСТР ЭМИТТЕРОВ СОБИРАЕТСЯ ИЗ СПИЦ, А НЕ ПИШЕТСЯ РУКОЙ (02.09.2026).
#
# Выше — эмиттеры, чьи тела живут в этом же файле. Ниже к ним ПРИСОЕДИНЯЮТСЯ
# объявления спутников: каждый `*_emit.py` объявляет свой `EMITTERS` рядом со
# своими телами, и хаб их СПРАШИВАЕТ. Прежде соответствие «оп -> тело» жило
# здесь рукописным словарём, тело — в спутнике, а связывала их тонкая обёртка
# (41 штука). Три носителя одного факта, и ничто не заставляло их согласоваться.
#
# ПОЧЕМУ ЭТО СТАЛО ВОЗМОЖНО ТОЛЬКО СЕЙЧАС: пока спутники тянули хаб на уровне
# модуля (за 29 именами), импортировать их отсюда было нельзя — кольцо. Ядро
# эмиссии переехало в `kir.emit_core`, кольца нет, и хаб вправе спросить спицу.
#
# ТРИ ПРОВЕРКИ ПРИ СБОРКЕ, И КАЖДАЯ ЛОВИТ СВОЙ РОД РАСХОЖДЕНИЯ:
#   * оп, объявленный ДВАЖДЫ (двумя спицами или спицей и хабом) — отказ с
#     именами обоих: молча выигравший последний импорт есть тихая потеря;
#   * оп, которого НЕТ В РЕЕСТРЕ языка — отказ: эмиттер без операции никем не
#     достижим, и это ровно тот случай, когда рукописный словарь молчал;
#   * оп реестра, у которого НЕТ эмиттера, здесь НЕ проверяется намеренно —
#     этим ведает `test_emitter_coverage`, и дублировать его вопрос значило бы
#     завести второй ответ на него.
def _collect_spoke_emitters() -> dict:
    from kir import spec as _spec
    out = dict(_EMITTERS)
    home = {op: "authoring" for op in out}
    for _name in _SPOKES:
        _mod = __import__("kir." + _name, fromlist=["EMITTERS"])
        for _op, _fn in getattr(_mod, "EMITTERS", {}).items():
            if _op in out:
                raise AssertionError(
                    f"оп {_op!r} эмитируют ДВОЕ: {home[_op]} и {_name}")
            if _op not in _spec.OPS:
                raise AssertionError(
                    f"{_name} эмитирует {_op!r}, которого нет в реестре языка")
            out[_op] = _fn
            home[_op] = _name
    return out


#: Спицы, чьи объявления собираются. Список ЗАКРЫТ и ПОЛОН ПО ПОСТРОЕНИЮ:
#: выводится из каталога пакета, а не пишется именами — новый `*_emit.py`
#: попадает сюда сам, и его объявление проверяется теми же тремя правилами.
_SPOKES = tuple(sorted(
    _p.stem for _p in __import__("pathlib").Path(__file__).parent.glob("*_emit.py")))

_EMITTERS = _collect_spoke_emitters()











def _lvl_pin(op: dict, param: str, var: str, ver: str, oid: str) -> str:
    """Pinned-level resolution OUTSIDE a transaction (stairs program preamble):
    null -> typed refusal dict directly (no __t to roll back yet)."""
    g = _gid(op, param)
    if g.get("via") == "ref":
        # sole-op program: refs cannot exist (nothing precedes) — ground/plan
        # guarantee this; guard anyway for the invariant.
        raise KirRefusal([Diagnostic(
            code=PLAN_SOLO_OP, op_id=oid, field_name=param,
            message_ru=f"{param}: ref недопустим в sole-op программе create_stairs")])
    return (f"Level {var} = doc.GetElement({_eid(g['id'], ver, oid)}) as Level;\n"
            f"if ({var} == null) return __Refuse({_cs(oid)}, \"{param}: уровень не найден (модель изменилась после grounding)\");")


def emit_stairs_program(op: dict, ver: str, intent: str = "",
                        *, stamp_scope: str = "", lineage: str = "",
                        expected_document: Mapping[str, str] | None = None,
                        expected_identities: Sequence[
                            ElementIdentityProof] | None = None) -> str:
    """Dedicated whole-program template for create_stairs: StairsEditScope owns
    its transactions (cannot nest inside the shared program txn — the reason
    for the KIR-L002 sole-op rule). The IFailuresPreprocessor implementation
    is a nested class AFTER Execute's body; the trailing __KirPad class keeps
    the fixed wrap_user_code footer brace count intact (compiler-owned emit,
    proven by the 6/6 gate like every other template)."""
    oid = op["id"]
    s = _safe(oid)
    stamp = _program_stamp([op], stamp_scope, lineage)
    # ФОРМА МАРША — РОВНО ОДНА ИЗ ДВУХ (KIR-P007 держит это в плане):
    # прямой отрезок `p0_mm`/`p1_mm` либо винт `spiral`. Ветка расходится
    # ровно в ОДНОМ операторе — создании марша — плюс свидетель, который
    # существует только у винта; весь каркас StairsEditScope/транзакции/
    # предобработчика отказов общий и не сдвинулся ни на байт.
    spiral = op.get("spiral")
    if spiral is None:
        x0, y0 = op["p0_mm"][0], op["p0_mm"][1]
        x1, y1 = op["p1_mm"][0], op["p1_mm"][1]
    w = op.get("width_mm")
    width_cs = (f"        try {{ __run_{s}.ActualRunWidth = U({w}); }} catch {{ }}\n"
                if w is not None else "")
    # 🔴 ВЕРТИКАЛЬ МАРША: ДОХОДИТ ЛИ ОН ТУДА, КУДА УКАЗЫВАЕТ `top_level`.
    #
    # Замер 19.08 на чистой модели, девять маршей, свидетель зелёный у всех:
    #   подъём 5400 · DesiredRisersNumber=29 · ActualRisersNumber=36
    #   ActualRiserHeight=186.2 = 5400/29 · ActualTreadDepth=250
    #   геометрия 0…6770 против объявленных 0…5400 — перелёт 1370 мм
    # Восемь остальных маршей: перелёт 995 мм каждый. 18.08 то же самое на
    # бенчмарке: 1202 мм на 11 маршах из 12.
    #
    # ЗАКОН, УСТАНОВЛЕННЫЙ ЧТЕНИЕМ И АРИФМЕТИКОЙ (сходится на двух подъёмах):
    # высоту подступенка Revit считает ВЕРНО из подъёма (`rise/Desired`), а
    # ЧИСЛО подступенков берёт из ДЛИНЫ МАРША, делённой на проступь ТИПА.
    # Длина 8680 при проступи 250 даёт 35 проступей и 36 подступенков вместо
    # 29 нужных: (8680 − 28×250)/250 = 6.7 → 7 лишних, ровно 36 − 29.
    #
    # Автор длину назвать не может ОБОСНОВАННО: проступь и максимальный
    # подступенок живут в ТИПЕ лестницы, а тип у этого опа не выбирается вовсе
    # (берётся умолчание документа) и в каталоге скрипта пула `stairs_types`
    # нет. Поэтому отказ ОБЯЗАН вернуть число: `(Desired − 1) × ActualTreadDepth`
    # — ровно ту длину, при которой марш встанет на уровень.
    #
    # СТОРОЖ ОДНОСТОРОННИЙ, И ПРИЧИНА СТРУКТУРНАЯ, А НЕ «ВЕЛИЧИНА НЕ МЕРЕНА»:
    # перебор (`actual > desired`) оправдать нечем — марш вылез выше объявленного
    # верха. Недобор законен: `create_stairs` кладёт ОДИН марш, а лестница из
    # нескольких маршей с площадками достраивается `create_stairs_landing`, и до
    # достройки actual < desired — верное промежуточное состояние. Оба числа
    # уезжают в расписку, поэтому недобор ВИДЕН, не будучи смертельным.
    #
    # Допуска здесь нет вовсе, и это лучше допуска: сравниваются ЦЕЛЫЕ числа
    # подступенков, а не миллиметры. Придумывать порог не пришлось.
    risers_post = (
        f"        try\n"
        f"        {{\n"
        f"            int __desR_{s} = __st_{s}.DesiredRisersNumber;\n"
        f"            int __actR_{s} = __st_{s}.ActualRisersNumber;\n"
        f"            if (__desR_{s} > 0 && __actR_{s} > __desR_{s})\n"
        f"            {{\n"
        f"                double __td_{s} = MM(__st_{s}.ActualTreadDepth);\n"
        f"                __post.Add({_cs(oid + ': марш перелетает top_level — подступенков ')}\n"
        f"                    + __actR_{s} + {_cs(' против нужных ')} + __desR_{s}\n"
        f"                    + {_cs('; длина марша должна быть ')}\n"
        f"                    + Math.Round((__desR_{s} - 1) * __td_{s}, 1)\n"
        f"                    + {_cs(' мм при проступи ')} + Math.Round(__td_{s}, 1)\n"
        f"                    + {_cs(' мм (vertical extent, geometry)')});\n"
        f"            }}\n"
        f"        }}\n"
        f"        catch {{ __post.Add({_cs(oid + ': число подступенков непрочитаемо (geometry)')}); }}\n")
    wtol = tolerance("create_stairs", "width_mm")
    width_post = (
        f"        try {{ if (Math.Abs(MM(__run_{s}.ActualRunWidth) - {w}) > {wtol})\n"
        f"            __post.Add({_cs(oid + ': stairs run width mismatch (geometry)')}); }}\n"
        f"        catch {{ __post.Add({_cs(oid + ': stairs run width unreadable (geometry)')}); }}\n"
        if w is not None else "")
    pre_doc_guard = _document_binding_guard(
        expected_document, rollback="")
    txn_doc_guard_raw = _document_binding_guard(
        expected_document,
        rollback="__t.RollBack(); try { __ess.Cancel(); } catch { } ")
    txn_doc_guard = (
        _indent(txn_doc_guard_raw, "        ") + "\n"
        if txn_doc_guard_raw else ""
    )
    pre_identity_guard = _element_identity_guard(
        expected_identities, ver, rollback="")
    # 🔴 СВОЙ ПРЕФИКС У ВТОРОГО СТОРОЖА — ИНАЧЕ CS0136 НА ВСЕХ ШЕСТИ.
    # Сторож объявляет локальные `__kirBinding_0/Uid/Version`; эмитированный
    # ДВАЖДЫ (до области правки и внутри транзакции) он объявляет их в
    # объемлющей и вложенной областях сразу, и C# это запрещает: «A local
    # named '__kirBinding_0' cannot be declared in this scope».
    #
    # ЗАМЕР 21.08.2026: `emit_program(create_stairs, expected_identities=...)`
    # НЕ КОМПИЛИРОВАЛСЯ ни на одной из шести версий — три CS0136 подряд. То
    # есть любой прогон A5 с доказательствами тождества на программе лестницы
    # падал бы на машине пользователя ДО Ревита, и ворота этого не видели:
    # `model_binding_guard_inputs` соло-опов не строит.
    #
    # ЛЕЧЕНИЕ УЖЕ БЫЛО НАЙДЕНО И НЕ ДОЕХАЛО СЮДА. Оба СПУТНИКА — площадка
    # (`stairs_landing_emit.py:235`, `__kirLandingTxnBinding`) и марш
    # (`stairs_run_emit.py:158`, `__kirRunTxnBinding`) — передают свой
    # префикс. Здесь, у САМОГО СТАРОГО из трёх шаблонов, правка не появилась:
    # починили копии, оригинал оставили.
    txn_identity_guard_raw = _element_identity_guard(
        expected_identities, ver,
        rollback="__t.RollBack(); try { __ess.Cancel(); } catch { } ",
        symbol_prefix="__kirStairsTxnBinding")
    txn_identity_guard = (
        _indent(txn_identity_guard_raw, "        ") + "\n"
        if txn_identity_guard_raw else ""
    )
    base = _lvl_pin(op, "base_level", f"__base_{s}", ver, oid)
    top = _lvl_pin(op, "top_level", f"__top_{s}", ver, oid)
    if spiral is None:
        run_cs = (
            f"        StairsRun __run_{s} = StairsRun.CreateStraightRun(doc, __sid_{s},\n"
            f"            Line.CreateBound(\n"
            f"                new XYZ(U({x0}), U({y0}), __base_{s}.Elevation),\n"
            f"                new XYZ(U({x1}), U({y1}), __base_{s}.Elevation)),\n"
            f"            StairsRunJustification.Center);\n"
            f"        if (__run_{s} == null)\n"
            f"        {{ __t.RollBack(); __ess.Cancel(); return __Refuse({_cs(oid)}, \"CreateStraightRun вернул null\"); }}\n")
        spiral_post = ""
        spiral_readback = ""
    else:
        # ВСЯ ТРИГОНОМЕТРИЯ — ЗДЕСЬ, НА КОМПИЛЯЦИИ. В C# уезжают готовые
        # литералы радиан: авторские градусы переводит питон, ровно как у
        # контуров с дугами. Z центра НЕ авторский — API прямо говорит, что
        # Z центра И ЕСТЬ базовая отметка нового марша, поэтому туда идёт
        # `__base.Elevation`, тот же, что у прямого марша.
        cx, cy = spiral["center_mm"][0], spiral["center_mm"][1]
        start_rad = math.radians(spiral["start_angle_deg"])
        included_rad = math.radians(spiral["included_angle_deg"])
        cw = "true" if spiral["clockwise"] else "false"
        run_cs = (
            f"        StairsRun __run_{s} = StairsRun.CreateSpiralRun(doc, __sid_{s},\n"
            f"            new XYZ(U({cx}), U({cy}), __base_{s}.Elevation),\n"
            f"            U({spiral['radius_mm']}), {start_rad!r}, {included_rad!r}, {cw},\n"
            f"            StairsRunJustification.Center);\n"
            f"        if (__run_{s} == null)\n"
            f"        {{ __t.RollBack(); __ess.Cancel(); return __Refuse({_cs(oid)}, \"CreateSpiralRun вернул null\"); }}\n")
        # СВИДЕТЕЛЬ ЧИТАЕТ РЕЗУЛЬТАТ, И ТОЛЬКО ТО, ЗА ЧТО МОЖЕТ ОТВЕЧАТЬ.
        #
        # Что проверяется: путь СОЗДАННОГО марша перечитывается
        # (`GetStairsPath` — есть на всех шести версиях) и обязан содержать
        # ДУГУ. Проверка не пустая: у прямого марша путь — Line, дуге там
        # взяться неоткуда, так что «винт запросили, а марш вышел прямой»
        # эта строка ловит и откатывает.
        #
        # ЧЕГО ЗДЕСЬ НАМЕРЕННО НЕТ — ЦЕНТРА, РАДИУСА, РАЗМАХА И НАПРАВЛЕНИЯ.
        # Отношение между ЗАПРОШЕННЫМИ центром/радиусом и тем, что
        # `GetStairsPath` возвращает (смещение на полуширину марша,
        # юстировка, положение линии пути), НЕ ИЗМЕРЕНО ни нами, ни
        # документацией. Допуск, придуманный ради зелёного свидетеля, —
        # именно тот дефект, который этот компилятор существует запрещать,
        # а жёсткая проверка по выдуманному числу откатила бы ВЕРНО
        # построенную лестницу. Поэтому вместо проверки — ЗАМЕР: центр и
        # радиус пути уезжают в расписку (ниже), и первый же живой прогон
        # превращает «не измерено» в число.
        spiral_post = (
            f"        try\n"
            f"        {{\n"
            f"            bool __spiralArc_{s} = false;\n"
            f"            foreach (Curve __spc_{s} in __run_{s}.GetStairsPath())\n"
            f"                if (__spc_{s} is Arc) __spiralArc_{s} = true;\n"
            f"            if (!__spiralArc_{s})\n"
            f"                __post.Add({_cs(oid + ': spiral run path has no Arc (geometry)')});\n"
            f"        }}\n"
            f"        catch {{ __post.Add({_cs(oid + ': spiral run path unreadable (geometry)')}); }}\n")
        spiral_readback = (
            f"    try {{ foreach (ElementId __rid_{s} in __st_{s}.GetStairsRuns())\n"
            f"          {{\n"
            f"              var __r_{s} = doc.GetElement(__rid_{s}) as StairsRun;\n"
            f"              if (__r_{s} == null) continue;\n"
            f"              foreach (Curve __pc_{s} in __r_{s}.GetStairsPath())\n"
            f"              {{\n"
            f"                  var __pa_{s} = __pc_{s} as Arc;\n"
            f"                  if (__pa_{s} == null) continue;\n"
            f"                  __rb_{s}[\"path_center_mm\"] = new double[] {{ Math.Round(MM(__pa_{s}.Center.X), 1), Math.Round(MM(__pa_{s}.Center.Y), 1) }};\n"
            f"                  __rb_{s}[\"path_radius_mm\"] = Math.Round(MM(__pa_{s}.Radius), 1);\n"
            f"              }}\n"
            f"          }} }} catch {{ }}\n")
    return _with_program_helpers(
        f"{_AUTH_PREAMBLE}\n"
        f"// create_stairs {cs_line_comment_fragment(oid)} — sole-op program, StairsEditScope owns transactions\n"
        + pre_doc_guard +
        pre_identity_guard +
        f"{base}\n{top}\n"
        f"if (__base_{s}.Elevation >= __top_{s}.Elevation)\n"
        f"    return __Refuse({_cs(oid)}, \"base_level выше или равен top_level\");\n"
        f"var __ess = new StairsEditScope(doc, {_cs(('KIR stairs: ' + (intent or oid))[:60])});\n"
        f"ElementId __sid_{s} = __ess.Start(__base_{s}.Id, __top_{s}.Id);\n"
        f"Autodesk.Revit.DB.Architecture.Stairs __st_{s} = null;\n"
        f"try\n"
        f"{{\n"
        f"    using (Transaction __t = new Transaction(doc, \"KIR: stairs run\"))\n"
        f"    {{\n"
        f"        var __startStatus = __t.Start();\n"
        f"        if (__startStatus != TransactionStatus.Started)\n"
        f"        {{ try {{ __ess.Cancel(); }} catch {{ }} return __Refuse({_cs(oid)}, \"transaction start status: \" + __startStatus.ToString()); }}\n"
        # Живьём 27.07: лестница построилась и оставила Revit с МОДАЛЬНЫМ окном
        # — мост умер на шести следующих вызовах подряд («Execution was
        # cancelled before Revit started it»), то есть у пользователя это
        # «КУКИ завис после лестницы», навсегда. Причина: это единственный оп
        # со своим шаблоном программы, и в нём не было ничего из того, что
        # emit_program ставит каждой обычной программе. Ставим то же самое.
        + failure_channel_reset_cs("__KirStairsFailures", "        ") +
        f"        var __fho = __t.GetFailureHandlingOptions();\n"
        f"        __fho.SetFailuresPreprocessor(new __KirStairsFailures());\n"
        f"        __fho.SetForcedModalHandling(false);\n"
        f"        __fho.SetClearAfterRollback(true);\n"
        f"        __t.SetFailureHandlingOptions(__fho);\n"
        + txn_doc_guard
        + txn_identity_guard
        + run_cs
        + width_cs +
        f"        doc.Regenerate();\n"
        f"        __st_{s} = doc.GetElement(__sid_{s}) as Autodesk.Revit.DB.Architecture.Stairs;\n"
        f"        if (__st_{s} == null)\n"
        f"        {{ __t.RollBack(); __ess.Cancel(); return __Refuse({_cs(oid)}, \"лестница не материализовалась\"); }}\n"
        f"        " + _stamp_block(f"__st_{s}", f"{stamp}:{oid}") + "\n"
        f"        var __bl = __st_{s}.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM);\n"
        f"        if (__bl == null || __bl.AsElementId().ToString() != __base_{s}.Id.ToString())\n"
        f"            __post.Add({_cs(oid + ': base level mismatch (topology)')});\n"
        f"        var __tl = __st_{s}.get_Parameter(BuiltInParameter.STAIRS_TOP_LEVEL_PARAM);\n"
        f"        if (__tl == null || __tl.AsElementId().ToString() != __top_{s}.Id.ToString())\n"
        f"            __post.Add({_cs(oid + ': top level mismatch (topology)')});\n"
        f"        if (__st_{s}.GetStairsRuns().Count < 1)\n"
        f"            __post.Add({_cs(oid + ': нет маршей (semantic)')});\n"
        + risers_post
        + width_post
        + spiral_post +
        f"        if (__post.Count > 0)\n"
        f"        {{\n"
        f"            var __rollbackStatus = __t.RollBack(); __ess.Cancel();\n"
        f"            var __er = new Dictionary<string, object>();\n"
        f"            __er[\"error\"] = \"postconditions_violated\";\n"
        f"            __er[\"violations\"] = __post;\n"
        f"            __er[\"commit_status\"] = __rollbackStatus.ToString();\n"
        f"            return __er;\n"
        f"        }}\n"
        f"        var __commitStatus = __t.Commit();\n"
        f"        if (__commitStatus != TransactionStatus.Committed)\n"
        # Отказ лестницы был НЕМЫМ: до 20.08 препроцессор марша не копил
        # ошибку вовсе, и «transaction commit status: RolledBack» приходило
        # без единого слова Revit — ровно тот исход, который главный эмиттер
        # запретил себе ещё в июле.
        f"        {{ try {{ __ess.Cancel(); }} catch {{ }} var __refused = __Refuse({_cs(oid)}, \"transaction commit status: \" + __commitStatus.ToString()\n"
        f"            + (__KirStairsFailures.Seen.Count > 0 ? \" | Revit: \" + String.Join(\" ; \", __KirStairsFailures.Seen) : \"\"));\n"
        f"          __refused[\"commit_status\"] = __commitStatus.ToString();\n"
        f"          if (__KirStairsFailures.Warned.Count > 0) __refused[\"revit_warnings\"] = __KirStairsFailures.Warned;\n"
        f"          if (__KirStairsFailures.Resolved.Count > 0) __refused[\"revit_errors_resolved\"] = __KirStairsFailures.Resolved;\n"
        f"          return __refused; }}\n"
        f"    }}\n"
        f"    __ess.Commit(new __KirStairsFailures());\n"
        f"}}\n"
        f"catch\n"
        f"{{\n"
        f"    try {{ __ess.Cancel(); }} catch {{ }}\n"
        f"    throw;\n"
        f"}}\n"
        f"// witness (post-scope readback)\n"
        f"__st_{s} = doc.GetElement(__sid_{s}) as Autodesk.Revit.DB.Architecture.Stairs;\n"
        f"var __rb_{s} = new Dictionary<string, object>();\n"
        f"__rb_{s}[\"id\"] = __sid_{s}.ToString();\n"
        + _stamp_readback(f"__st_{s}", f"__rb_{s}") +
        f"if (__st_{s} != null)\n"
        f"{{\n"
        f"    try {{ __rb_{s}[\"runs\"] = __st_{s}.GetStairsRuns().Count; }} catch {{ }}\n"
        f"    try {{ __rb_{s}[\"risers\"] = __st_{s}.ActualRisersNumber; }} catch {{ }}\n"
        # 🔴 ЧИСЛА НАРУЖУ ВСЕГДА, А НЕ ТОЛЬКО ПРИ ОТКАЗЕ. Сторож ловит перебор;
        # недобор законен и потому МОЛЧИТ — но автор обязан его видеть, иначе
        # «марш не достроен» неотличимо от «марш встал верно». У девяти маршей
        # 19.08 сверить было нечем: ни нужного числа подступенков, ни проступи,
        # ни длины, при которой марш встал бы на уровень, в квитанции не было.
        f"    try {{ __rb_{s}[\"risers_desired\"] = __st_{s}.DesiredRisersNumber; }} catch {{ }}\n"
        f"    try {{ __rb_{s}[\"tread_depth_mm\"] = Math.Round(MM(__st_{s}.ActualTreadDepth), 1); }} catch {{ }}\n"
        f"    try {{ __rb_{s}[\"riser_height_mm\"] = Math.Round(MM(__st_{s}.ActualRiserHeight), 1); }} catch {{ }}\n"
        f"    try {{ __rb_{s}[\"run_length_for_top_mm\"] = Math.Round((__st_{s}.DesiredRisersNumber - 1) * MM(__st_{s}.ActualTreadDepth), 1); }} catch {{ }}\n"
        f"    try {{ var __tid = __st_{s}.GetTypeId(); var __ty = doc.GetElement(__tid);\n"
        f"          if (__ty != null) __rb_{s}[\"type_name\"] = __ty.Name; }} catch {{ }}\n"
        + spiral_readback +
        f"}}\n"
        f"__results[{_cs(oid)}] = __rb_{s};\n"
        + failure_warnings_into_results_cs("__KirStairsFailures")
        + f"__results[\"ok\"] = true;\n"
        f"return __results;\n"
        f"}}\n"
        f"\n"
        # ОДИН свод на все эмиттеры (`emit_utils.failure_preprocessor_cs`).
        # Обработчик стоит и на транзакции, и на StairsEditScope.Commit:
        # предупреждение может подняться уже вне транзакции.
        + failure_preprocessor_cs("__KirStairsFailures")
        + f"\n"
        f"private static class __KirPad\n"
        f"{{  // pad scope: the fixed wrapper footer closes __KirPad, UserCode, namespace")


def _emit_stairs_landing_program(op: dict, ver: str, intent: str = "", *,
                                 stamp_scope: str = "", lineage: str = "",
                                 expected_document=None,
                                 expected_identities=None) -> str:
    """Тонкая регистрация без логики — тело в `stairs_landing_emit.py`.

    Импорт ленивый по той же причине, что у struct/datum/solid: тот модуль
    берёт приватные помощники ОТСЮДА, и модульный импорт замкнул бы граф.
    """
    from kir import stairs_landing_emit
    return stairs_landing_emit.emit_stairs_landing_program(
        op, ver, intent, stamp_scope=stamp_scope,
        expected_document=expected_document,
        expected_identities=expected_identities)


def _emit_stairs_run_program(op: dict, ver: str, intent: str = "", *,
                             stamp_scope: str = "", lineage: str = "",
                             expected_document=None,
                             expected_identities=None) -> str:
    """Тонкая регистрация без логики — тело в `stairs_run_emit.py`.

    Импорт ленивый по той же причине, что у площадки: тот модуль берёт
    приватные помощники ОТСЮДА, и модульный импорт замкнул бы граф.
    """
    from kir import stairs_run_emit
    return stairs_run_emit.emit_stairs_run_program(
        op, ver, intent, stamp_scope=stamp_scope,
        expected_document=expected_document,
        expected_identities=expected_identities)


#: ОП-ВЛАДЕЛЕЦ ТРАНЗАКЦИЙ -> ЕГО СОБСТВЕННЫЙ ШАБЛОН ЦЕЛОЙ ПРОГРАММЫ.
#:
#: Таблица заведена вместе со вторым таким опом (10.08.2026) и ровно затем,
#: чтобы факт «у соло-опа свой шаблон» имел ОДИН адрес.  До неё имя
#: `emit_stairs_program` стояло литералом в ветке, общей для всего множества
#: `spec.SOLO_OPS`, — то есть площадка молча уехала бы в шаблон марша и
#: получила бы чужую эмиссию, а не отказ.  Ключи обязаны совпадать с
#: `spec.SOLO_OPS`; расхождение ловит `tests/test_stairs_landing.py`.
def _emit_transfer_family_program(op: dict, ver: str, intent: str = "",
                                 *, stamp_scope: str = "", lineage: str = "",
                                 expected_document=None,
                                 expected_identities=None) -> str:
    from kir import family_transfer_emit
    return family_transfer_emit.emit_transfer_family_program(
        op, ver, intent,
        stamp=_program_stamp([op], stamp_scope, lineage),
        stamp_scope=stamp_scope,
        expected_document=expected_document,
        expected_identities=expected_identities)


def _emit_author_family_program(op: dict, ver: str, intent: str = "",
                                *, stamp_scope: str = "", lineage: str = "",
                                expected_document=None,
                                expected_identities=None) -> str:
    from kir import family_author_emit
    return family_author_emit.emit_author_family_program(
        op, ver, intent,
        stamp=_program_stamp([op], stamp_scope, lineage),
        stamp_scope=stamp_scope,
        expected_document=expected_document,
        expected_identities=expected_identities)


_SOLO_PROGRAMS = {
    "create_stairs": emit_stairs_program,
    "create_stairs_landing": _emit_stairs_landing_program,
    "create_stairs_run": _emit_stairs_run_program,
    # ВТОРОЙ ДОКУМЕНТ, А НЕ ТОЛЬКО СВОИ ТРАНЗАКЦИИ (21.08.2026). Разница с
    # тремя соседями по таблице: те строят В `doc`, просто своей рукой; этот
    # строит В ДРУГОМ документе, созданном из шаблона, и `doc` видит только на
    # последнем шаге — загрузка и постановка экземпляра.
    "author_family": _emit_author_family_program,
    # ВТОРОЙ ДОКУМЕНТ — ЧУЖОЙ И ТОЛЬКО НА ЧТЕНИЕ. Разница с `author_family`:
    # тот СОЗДАЁТ документ семейства из шаблона и закрывает его сам; этот
    # берёт УЖЕ ОТКРЫТЫЙ проект, просит у него копию семейства
    # (`EditFamily`) и закрывает только её. Исходный документ не меняется ни
    # в одной точке программы.
    "transfer_family": _emit_transfer_family_program,
}


# Ops whose Wall.Create output can be de-joined (per_op disallow_wall_joins).
_WALL_OPS = frozenset({"create_wall"})


def _op_refs(node) -> set:
    """Intra-program op ids this (grounded) op depends on: all ref forms —
    ``{"__grounded__": {"via": "ref", "ref": id}}`` (ground.py pools) and raw
    ``{"by": "ref", "value": id}`` selectors (host/target_w, never grounded).
    Element addresses are replaced by literal points during GROUND, so their
    source op survives only in the compiler-owned ``__address__`` receipt.
    It remains a runtime prerequisite: under per-op isolation a dependent must
    not be created at cached coordinates after its authored support refused.
    ``__host_wall__`` (the plan-attached host op ECHO) is skipped: its inner
    refs belong to the host op, not to this one."""
    refs = set()
    if isinstance(node, dict):
        g = node.get("__grounded__")
        if isinstance(g, dict) and g.get("via") == "ref" \
                and isinstance(g.get("ref"), str):
            refs.add(g["ref"])
        if node.get("by") == "ref" and isinstance(node.get("value"), str):
            refs.add(node["value"])
        addresses = node.get("__address__")
        if isinstance(addresses, list):
            for address in addresses:
                if not isinstance(address, dict):
                    continue
                element = address.get("element")
                if isinstance(element, dict) \
                        and isinstance(element.get("of"), str):
                    refs.add(element["of"])
        for key, value in node.items():
            if key in spec.SYNTHETIC_FIELDS:  # власть — registry_base
                continue
            refs |= _op_refs(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            refs |= _op_refs(value)
    return refs


def _emitter_source(op_kind: str) -> str:
    """Where an op's C# came from — the missing half of a contract refusal."""

    fn = _EMITTERS.get(op_kind)
    if fn is None:
        return "<неизвестный эмиттер>"
    return (f"{getattr(fn, '__module__', '?')}."
            f"{getattr(fn, '__qualname__', getattr(fn, '__name__', '?'))}")


def _wrap_create_per_op(op: dict, s: str, create: str,
                        disallow_wall_joins: bool, op_ids: set) -> str:
    """One op's create block in its own SubTransaction (bulk-rebuild isolation).

    A guard failure or exception refuses THIS op only — its SubTransaction is
    rolled back, ``{op_id: {refused: reason}}`` is recorded, and the neighbours
    keep committing. Style mirrors decompile/recompile._emit_brep_attempt_cs:
    never re-throw, finally rolls back + disposes.

    *create* MUST already be emitted with ``isolation="per_op"``.  Until
    2026-07-28 this function chose the refusal semantics itself, by rewriting
    the emitted C#::

        body = create.replace("__t.RollBack(); return __Refuse(",
                              "throw __OpRefuse(")

    That was belief in the literal spelling of a phrase typed by hand in 105
    places across four files.  An emitter that spelled it any other way — one
    extra space, its own rollback, a refusal inside ``catch`` — kept
    WHOLE-PROGRAM semantics inside a SubTransaction: one op's refusal silently
    rolling its already-committed neighbours back, exactly the class of quiet
    wrongness this compiler exists to forbid.  The form is now chosen where
    the statement is built (``emit_utils.refuse_stmt``), nothing rewrites C#
    here any more, and the check below makes the absence CHECKABLE instead of
    assumed (review findings №9 and №12).

    The allowlist of surviving whole-program refusals is EMPTY by
    construction: inside a real wrapped create there is no legitimate reason
    to touch the outer transaction.  ``emit_program``'s own scaffold (commit
    path, outer catch, document/identity guards) and the stairs template are
    not wrapped creates at all and are outside this contract.

    Dependency gate: an op whose ref'd prerequisite (host wall / created level
    / annotation target) was itself refused must refuse with a TYPED message —
    not trip a NullReference on the dead ``__el_*`` and surface as noise."""
    oid = op["id"]
    leftovers = program_refusal_tokens(create)
    if leftovers:
        raise KirRefusal([Diagnostic(
            code=EMIT_GUARD_CONTRACT, op_id=oid, field_name=op["op"],
            got=leftovers,
            message_ru=(
                f"нарушен контракт гарда эмиссии: в теле операции "
                f"{op['op']} (id {oid!r}) при изоляции per_op остались "
                f"{', '.join(leftovers)} — отказ ОДНОГО опа откатил бы уже "
                f"созданных соседей. Источник: {_emitter_source(op['op'])}; "
                f"отказ обязан строиться emit_utils.refuse_stmt(oid, msg, "
                f"isolation), а не набираться фразой вручную"))])
    body = create
    dep_gate = "".join(
        f"if (!__ok_{_safe(ref)}) throw __OpRefuse({_cs(oid)}, "
        f"{_cs('опорный оп «' + ref + '» отказан — оп пропущен')});\n"
        for ref in sorted(_op_refs(op) & op_ids))
    join_kill = ""
    if disallow_wall_joins and op["op"] in _WALL_OPS:
        # Гипотеза, ради которой этот де-джойн вообще есть: автосоединение
        # концов стены — источник и отказов, и дрейфа позиции на плотной
        # пересборке (канон: живой Revit двигает кривую на ±100/125/150 мм).
        #
        # 🔴 ДВА `try`, А НЕ ОДИН, И ОТКАЗ НАЗВАН. До 18.08.2026 здесь стояло
        # `try { Disallow(0); Disallow(1); } catch { }` — ОДИН перехват на два
        # конца, и пустой. Два дефекта в одной строке:
        #   * бросок на конце 0 забирал с собой конец 1, который никто не
        #     пробовал; программа при этом выглядела успешной;
        #   * пустой `catch` делал «де-джойн отказал» НЕОТЛИЧИМЫМ от «де-джойн
        #     сработал». А сработал он или нет — решает, верить ли геометрии
        #     концов: допуск свидетеля 5.0 мм против дрейфа 100–150 мм, то
        #     есть именно этот вызов держит зелёное на пересборке.
        #
        # ПОЧЕМУ ЗАПИСЬ, А НЕ БРОСОК. Де-джойн — best-effort по замыслу: стена
        # создана и годна, даже если её концы остались соединяемыми. Отказ
        # уронил бы оп целиком и выбросил бы годную стену — из двух зол выбрано
        # обратимое. Канал взят СУЩЕСТВУЮЩИЙ (`__post` -> `postcondition_
        # violations`), а не заведён второй: `disallow_wall_joins` бывает
        # только при `per_op`, а `per_op` форсирует `report_posts` (:7425), так
        # что запись доезжает до `__results` ПО ПОСТРОЕНИЮ, а не по надежде.
        #
        # ПОЧЕМУ ЗДЕСЬ ТОЛЬКО `create_wall` И ЭТО НЕ НЕДОСМОТР. `create_face_wall`
        # эмитит `FaceWall.Create` (`mass_emit.py:232`), а `FaceWall` — НЕ
        # `Wall`: `WallUtils.DisallowWallJoinAtEnd(FaceWall, 0)` не собирается
        # вовсе. Замерено 18.08.2026 живой компайл-службой на референсах 2026:
        # `CS1503: cannot convert from 'Autodesk.Revit.DB.FaceWall' to
        # 'Autodesk.Revit.DB.Wall'` (контроль: та же строка с `Wall` — OK).
        # Расширение `_WALL_OPS` на него сломало бы эмиссию, а не починило её.
        join_kill = "".join(
            f"\ntry {{ WallUtils.DisallowWallJoinAtEnd(__el_{s}, {end}); }}\n"
            f"catch (Exception __dj{end}_{s}) {{ __post.Add("
            f"{_cs(oid + f': конец {end} НЕ де-джойнен, автосоединение осталось: ')}"
            f" + __dj{end}_{s}.Message); }}"
            for end in (0, 1))
    inner = _indent(body + join_kill, "    ")
    # 🔴 C-1, ВТОРОЙ НОСИТЕЛЬ. Ворота операции чистят СВОЙ диапазон сами
    # (`operation_check_gate`), и по замеру 06.09.2026 во ВСЁМ замороженном
    # корпусе (921 per_op-эмиссия) это закрывает вопрос целиком: 399 из 399
    # обращений `__post.Add` внутри тела SubTransaction лежат ВНУТРИ блока
    # ворот, снаружи — НОЛЬ. Но корпус не содержит ни одной эмиссии с
    # `disallow_wall_joins`, а она пишет в общий `__post` ПОСЛЕ ворот (см.
    # `join_kill` выше) — и если оп потом отказывает на позднем броске или
    # на `subtransaction commit:`, его строка остаётся числиться нарушением
    # ЗАКОММИЧЕННОЙ программы. Забор ставится ровно там, где есть writer:
    # при пустом `join_kill` байты прежние (иначе двинулись бы 921 ключ
    # заморозки ради ноля настоящих утечек), при непустом — сообщение
    # снимается в отказ, а диапазон опа снимается со списка.
    #
    # ОТ ПРОТУХАНИЯ ЗАКРЫТО ЧИСЛОМ, А НЕ ЭТИМ КОММЕНТАРИЕМ:
    # `kir/tests/test_a_refused_op_leaves_no_trace.py` обходит эмиссии и
    # краснеет, если в теле SubTransaction появился writer в `__post`, чей
    # диапазон никто не снимает.
    fence = f"int __opPostStart_{s} = __post.Count;\n" if join_kill else ""
    if join_kill:
        def _refused_msg(source: str) -> str:
            return (
                f"    var __rfMsg_{s} = {source};\n"
                f"    if (__post.Count > __opPostStart_{s})\n"
                f"    {{\n"
                f"        __rfMsg_{s} = __rfMsg_{s} + \" | откачено вместе с "
                f"операцией: \" + String.Join(\" ; \", __post.Skip(__opPostStart_{s}));\n"
                f"        __post.RemoveRange(__opPostStart_{s}, __post.Count - __opPostStart_{s});\n"
                f"    }}\n"
                f"    __rf_{s}[\"refused\"] = __rfMsg_{s};\n")
    else:
        def _refused_msg(source: str) -> str:
            return f"    __rf_{s}[\"refused\"] = {source};\n"
    return (
        fence +
        f"SubTransaction __st_{s} = null;\n"
        f"try\n"
        f"{{\n"
        + _indent(dep_gate, "    ") + ("\n" if dep_gate else "")
        + f"    __st_{s} = new SubTransaction(doc);\n"
        f"    var __stStart_{s} = __st_{s}.Start();\n"
        f"    if (__stStart_{s} != TransactionStatus.Started)\n"
        f"        throw __OpRefuse({_cs(oid)}, \"subtransaction start: \" + __stStart_{s}.ToString());\n"
        f"{inner}\n"
        f"    var __stCommit_{s} = __st_{s}.Commit();\n"
        f"    if (__stCommit_{s} != TransactionStatus.Committed)\n"
        f"        throw __OpRefuse({_cs(oid)}, \"subtransaction commit: \" + __stCommit_{s}.ToString());\n"
        f"    __ok_{s} = true;\n"
        f"}}\n"
        # §13: a MANAGED refusal and a genuine Revit API failure used to
        # arrive here as the same bare Exception, so anything at all could be
        # recorded as if the compiler had decided it.  The sentinel type has
        # its own branch and carries the op id it was raised for; everything
        # else is still an op-local refusal (the neighbours keep committing)
        # but is labelled `internal` and never claims to be a decision.
        f"catch (__KirOpRefusal __orf_{s})\n"
        f"{{\n"
        f"    var __rf_{s} = new Dictionary<string, object>();\n"
        + _refused_msg(f"__orf_{s}.Msg") +
        f"    __rf_{s}[\"refused_op_id\"] = __orf_{s}.Oid;\n"
        f"    __results[{_cs(oid)}] = __rf_{s};\n"
        f"}}\n"
        f"catch (Exception __oex_{s})\n"
        f"{{\n"
        f"    var __rf_{s} = new Dictionary<string, object>();\n"
        + _refused_msg(f"__oex_{s}.Message") +
        f"    __rf_{s}[\"internal\"] = true;\n"
        f"    __results[{_cs(oid)}] = __rf_{s};\n"
        f"}}\n"
        f"finally\n"
        f"{{\n"
        f"    try {{ if (__st_{s} != null && __st_{s}.HasStarted() && !__st_{s}.HasEnded()) __st_{s}.RollBack(); }} catch {{ }}\n"
        f"    try {{ if (__st_{s} != null) __st_{s}.Dispose(); }} catch {{ }}\n"
        f"}}")


def operation_check_gate(oid: str, operation_cs: str, isolation: str) -> str:
    """Typed operation checks run before the operation can commit/continue.

    Failed stages refuse even in final-post report mode. Revit rollback also
    undoes any stamp written earlier in this operation; ordinary C# observations
    survive but are not published as a successful per-op result.

    🔴 C-1 (аудит 06.09.2026): ОТКАЧЕННЫЙ ОП НЕ ОСТАВЛЯЕТ СЛЕДА В ОБЩЕМ СПИСКЕ.
    ``__post`` — список ВСЕЙ программы, и в режиме ``report`` он целиком
    уезжает в ``__results["postcondition_violations"]`` (:emit_program).  До
    этой правки per_op-ворота бросали отказ, ОСТАВИВ свои строки в списке:
    оп откатывался вместе со своей SubTransaction, но его сообщение
    продолжало числиться нарушением ЗАКОММИЧЕННОЙ программы, и потребитель
    (``bridge_result.assess_write_result``) объявлял всю запись VIOLATED,
    хотя закоммичены были только верные соседи.  Один факт сообщался дважды
    в двух несовместимых ролях: как ``{refused}`` своего опа и как нарушение
    постусловия чужих.

    Порядок здесь не косметика, и он ровно такой:
      1. сообщение СНИМАЕТСЯ в локальную переменную (``String.Join``
         материализует ленивый ``Skip`` немедленно) — ДО любого удаления;
      2. удаляется РОВНО диапазон этого опа ``[start, Count)`` — строки
         соседей, лежащие ниже ``start``, не трогаются;
      3. отказ бросается уже снятым сообщением, и оно доезжает до
         ``__results[oid]["refused"]`` через ``__KirOpRefusal``.
    Обратный порядок (удалить, потом читать) отдал бы пустую строку — это и
    есть причина, по которой шаги перечислены, а не свёрнуты в одну.

    ``atomic`` НЕ МЕНЯЕТСЯ И ЭТО ПРОВЕРЕНО, А НЕ ПРЕДПОЛОЖЕНО: там отказ —
    ``__t.RollBack(); return __Refuse(...)``, то есть выход из Execute ДО
    строки ``if (__post.Count > 0)``; ``__post`` не публикуется вовсе, утечки
    нет, и байты остаются прежними (см.
    ``kir/tests/test_a_refused_op_leaves_no_trace.py``).
    """
    if not operation_cs:
        return ""
    s = _safe(oid)
    head = f"\nint __operationPostStart_{s} = __post.Count;\n" + operation_cs + "\n"
    if isolation == "per_op":
        return (head
                + f"if (__post.Count > __operationPostStart_{s}) {{ "
                f"var __opRefusal_{s} = String.Join(\" ; \", "
                f"__post.Skip(__operationPostStart_{s})); "
                f"__post.RemoveRange(__operationPostStart_{s}, "
                f"__post.Count - __operationPostStart_{s}); "
                + refuse_stmt(oid, f"__opRefusal_{s}", isolation)
                + " }\n")
    return (head
            + f"if (__post.Count > __operationPostStart_{s}) {{ "
            + refuse_stmt(oid, f'String.Join(" ; ", __post.Skip(__operationPostStart_{s}))', isolation)
            + " }\n")


def emit_program(grounded_ops: list[dict], revit_version: str, intent: str = "",
                 *, isolation: str = "atomic", postconditions: str = "strict",
                 disallow_wall_joins: bool = False,
                 stamp_scope: str = "",
                 lineage: str = "",
                 expected_document: Mapping[str, str] | None = None,
                 expected_identities: Sequence[
                     ElementIdentityProof] | None = None) -> str:
    """Emit one authoring program.

    ``isolation``:
      * ``"atomic"`` (default) — ONE transaction; any op guard failure rolls
        back the whole program (all-or-nothing; the chat contract).
      * ``"per_op"`` — each create block owns a SubTransaction; a bad op is a
        single refusal recorded in ``__results`` while neighbours commit (bulk
        rebuild). Implies ``postconditions="report"`` regardless of the flag
        (a partial commit cannot honour a whole-program rollback).
    ``postconditions``:
      * ``"strict"`` (default) — legacy: any postcondition violation rolls the
        whole transaction back and returns ``postconditions_violated``.
      * ``"report"`` — violations are recorded in
        ``__results["postcondition_violations"]`` and the program still commits.
    ``disallow_wall_joins`` (``per_op`` only, ``create_wall`` only) — de-join
    both wall ends after creation to shed auto-join refusals / position drift.

    The default ``(atomic, strict)`` reproduces the legacy chat program
    byte-for-byte apart from the unconditional warning swallower below.
    """
    if isolation not in ("atomic", "per_op"):
        raise ValueError(
            f"isolation must be 'atomic' or 'per_op', got {isolation!r}")
    if postconditions not in ("strict", "report"):
        raise ValueError(
            f"postconditions must be 'strict' or 'report', got {postconditions!r}")
    # ПОСЛЕДНИЙ РУБЕЖ. То же правило стоит теперь и на плане
    # (`compiler.plan_program`, `spec.SOLO_OPS`), чтобы быть достижимым БЕЗ
    # живого Revit; здесь оно остаётся дословно — эмиттер обязан отказывать
    # сам, а не полагаться на то, что до него дошли через план.
    solo = [op for op in grounded_ops if op["op"] in spec.SOLO_OPS]
    if solo:
        if len(grounded_ops) != 1:
            # ИМЯ ОПА БЕРЁТСЯ ИЗ ПРОГРАММЫ, А НЕ ПИШЕТСЯ ЛИТЕРАЛОМ (10.08.2026).
            # До появления второго соло-опа текст называл `create_stairs`
            # безусловно, и площадка получила бы отказ, обвиняющий чужую
            # операцию, — прибор, врущий ровно на новой половине диапазона.
            raise KirRefusal([Diagnostic(
                code=PLAN_SOLO_OP,
                message_ru=f"{solo[0]['op']} — единственный оп своей программы "
                           "(StairsEditScope владеет собственными транзакциями); "
                           "вынесите остальные опы в отдельные программы")])
        return _SOLO_PROGRAMS[solo[0]["op"]](
            grounded_ops[0], revit_version, intent, stamp_scope=stamp_scope,
            lineage=lineage,
            expected_document=expected_document,
            expected_identities=expected_identities)
    per_op = isolation == "per_op"
    # A partial commit cannot honour a whole-program rollback, so per_op forces
    # report-mode postconditions (drift surfaced, elements kept).
    report_posts = per_op or postconditions == "report"
    stamp = _program_stamp(grounded_ops, stamp_scope, lineage)
    txn_name = ("KIR: " + (intent or "authoring"))[:80]
    op_ids = {op["id"] for op in grounded_ops}
    decls, creates, posts, readbacks = [], [], [], []
    writes_since_regen = False
    for __idx, op in enumerate(grounded_ops):
        s = _safe(op["id"])
        # ═══ ИТОГ ПОСЛЕДНЕГО ЗАКОННОГО ПИСАТЕЛЯ (E-2, 07.09.2026) ═══
        #
        # Эмиттер зовётся ПО ОДНОМУ опу и программы не видит, а вопрос
        # «перепишет ли мой результат кто-то ниже» — вопрос о ПРОГРАММЕ.
        # Ответ считается здесь, где вся программа есть, и приделывается
        # КОПИИ опа: чужой словарь не мутируется, разбор и приёмка этого поля
        # не видят вовсе (они прошли выше), а имя объявлено ровно в одном
        # месте дерева — `spec.SYNTHETIC_FINAL_SHIFT`.
        #
        # ПУСТОЙ СДВИГ НЕ ПРИДЕЛЫВАЕТСЯ. Это не оптимизация: приделанный ноль
        # доехал бы до `shifted_point` и превратил `6000` в `6000.0` — другой
        # литерал в C# и сдвиг байтов в 646 эмиссиях корпуса из 2340 ради
        # ноля настоящих починок.
        __shift = _geom.program_result_shift(grounded_ops, __idx)
        if any(__shift):
            op = dict(op)
            op[spec.SYNTHETIC_FINAL_SHIFT] = __shift
        d, c, p, r = _EMITTERS[op["op"]](op, revit_version, stamp,
                                         isolation)
        # ═══ ИТОГ ПОСЛЕДНЕГО ПИСАТЕЛЯ ПО ПАРАМЕТРАМ И ПО ЖИЗНИ (E-4) ═══
        #
        # Второй вопрос о том же хвосте программы, что и `__shift` выше, но
        # про ДРУГОЙ род переписывания: `set_param`, законно переписавший
        # параметр, который пришпилил свидетель СОЗДАНИЯ, и `delete`, законно
        # снявший элемент, которого финальный блок продолжал читать. Оба
        # ответа считает ОДИН закон (`emit_core.program_tail_writes`), и его же
        # зовёт `translation_cert.certify_op` — иначе эмиссия и её
        # доказательство разошлись бы на стадии.
        __rewritten, __deleted_by = program_tail_writes(grounded_ops, __idx)
        # Wave A2 transitional adapter (Д4): migrated emitters return post as
        # list[WitnessCheck]; legacy emitters return the pre-rendered string.
        # Both render HERE — the one render path, byte-identically.
        operation_cs, p = render_tail_adjusted_post(
            op["id"], p, __rewritten, __deleted_by)
        c += operation_check_gate(op["id"], operation_cs, isolation)
        # v0 rule: build walls first, THEN place rooms into finished enclosures
        # ═══ ПРАВИЛО РЕГЕНЕРАЦИИ ПЕРЕД ПРОСТРАНСТВЕННЫМ ОПОМ ═══
        #
        # ЧТО ЗАМЕРЕНО, И ЭТО НЕ ПРО СТЕНЫ. Провенанс правила (a63d5c13) —
        # факт о Revit: «свежая стена без граней ДО регенерации». То есть
        # только что созданный элемент не реализован в документе целиком,
        # пока не позвали `doc.Regenerate()`. `NewRoom`/`NewSpace` разрешают
        # объемлющую область В МОМЕНТ ВЫЗОВА — значит важно, создавалось ли
        # ЧТО-НИБУДЬ после последней регенерации, а вовсе не была ли это
        # стена.
        #
        # ПОЧЕМУ НЕ СПИСОК ОГРАНИЧИВАЮЩИХ ОПОВ. Соблазн был: спросить
        # реестр, чей результат ограничивает комнату. Замер 11.08 по шести
        # сборкам закрывает эту дорогу — ЕДИНСТВЕННЫЙ BuiltInParameter,
        # называющий ограничение комнаты, это `WALL_ATTR_ROOM_BOUNDING`
        # (6/6). У разделителя, перекрытия, потолка и кровли такого
        # параметра нет вовсе: они ограничивают по своей природе. Спросить
        # элемент «ограничиваешь ли ты» нечем, поэтому список пришлось бы
        # вести руками — и он протух бы на первом же новом опе.
        #
        # ЧТО БЫЛО СЛОМАНО. Правило вооружал ТОЛЬКО `create_wall`, а
        # ограничивающих элементов реестр строит восемь родов (замер 11.08:
        # create_room_separator, create_floor, create_floor_by_contour,
        # create_ceiling, create_roof, create_extrusion_roof, create_column,
        # create_building_pad). Программа «разделитель, затем комната в
        # образованном им контуре» регенерации НЕ получала — проверено на
        # эмиссии: разделитель на позиции 2645, комната на 5534, регенерации
        # между ними нет.
        #
        # ЦЕНА ОШИБКИ НЕСИММЕТРИЧНА, и правило выбрано по ней: лишняя
        # регенерация стоит времени, пропущенная — ОТКАТА ВЕРНОЙ ПРОГРАММЫ
        # (комната прочитает Area == 0 и свидетель уронит всё). Из двух зол
        # выбрано обратимое, ровно как у слепоты приёмки.
        #
        # ЗАКРЫТО ОТ ПРОТУХАНИЯ: обе стороны правила выводятся из реестра, а
        # не перечисляются. Вооружает — любой оп с `writes_model`, значит
        # новый пишущий оп попадает в правило сам. Потребляет —
        # `_SPATIAL_ENCLOSURE_OPS`, и `tests/test_regen_before_spatial.py`
        # падает, если в реестре появился пространственный оп, которого там
        # нет.
        if op["op"] in _SPATIAL_ENCLOSURE_OPS and writes_since_regen:
            c = SPATIAL_REGEN_CS + "\n" + c
            writes_since_regen = False
        elif spec.OPS[op["op"]].writes_model:
            writes_since_regen = True
        if per_op:
            d = d + f"\nbool __ok_{s} = false;"
            c = _wrap_create_per_op(op, s, c, disallow_wall_joins, op_ids)
            # A refused op leaves __el_<s> null: gate its post + readback so a
            # neighbour's failure never NPEs the surviving ops.
            p = f"if (__ok_{s})\n{{\n" + _indent(p, "    ") + "\n}"
            r = f"if (__ok_{s})\n{{\n" + _indent(r, "    ") + "\n}"
        decls.append(d)
        creates.append(c)
        posts.append(p)
        readbacks.append(r)
    body_creates = "\n\n".join(creates)
    body_posts = "\n".join(posts)
    ind = "\n".join("        " + ln if ln.strip() else ln
                    for ln in (body_creates + "\n\ndoc.Regenerate();\n\n" + body_posts).splitlines())
    if report_posts:
        # Postcondition violations are REPORTED, never rolled back: a created
        # element (e.g. a wall whose ends Revit join-extended past the 5mm
        # tolerance) must be kept and its drift surfaced, not silently dropped.
        post_gate = (
            f"        if (__post.Count > 0)\n"
            f"            __results[\"postcondition_violations\"] = __post;\n")
    else:
        # strict (legacy chat contract): any violation rolls the whole program
        # back and reports it; a partially-wrong program is unexpressible.
        post_gate = (
            f"        if (__post.Count > 0)\n"
            f"        {{\n"
            f"            var __rollbackStatus = __t.RollBack();\n"
            f"            var __er = new Dictionary<string, object>();\n"
            f"            __er[\"error\"] = \"postconditions_violated\";\n"
            f"            __er[\"violations\"] = __post;\n"
            f"            __er[\"commit_status\"] = __rollbackStatus.ToString();\n"
            f"            return __er;\n"
            f"        }}\n")
    # The op-local refusal sentinel (per_op only): carries a message the way
    # __Refuse builds its dict, but as an exception the SubTransaction catch can
    # absorb without returning from the whole Execute body.
    # It is a TYPE, not a bare InvalidOperationException: a refusal the
    # compiler DECIDED on and a failure Revit threw at us must not be the same
    # thing at the catch site (review finding №13).
    op_refuse_decl = (
        f"Func<string, string, Exception> __OpRefuse = (string __oid, string __msg) =>\n"
        f"    new __KirOpRefusal(__oid, __msg);\n"
    ) if per_op else ""
    op_refuse_class = (
        f"private class __KirOpRefusal : Exception\n"
        f"{{\n"
        f"    // Управляемый отказ ОДНОГО опа — тип, а не «какое-то исключение».\n"
        f"    // Пока это был InvalidOperationException, поломка Revit API и наше\n"
        f"    // собственное решение отказать приходили в один catch неразличимыми,\n"
        f"    // и любая случайная ошибка записывалась как осознанный отказ.\n"
        f"    public readonly string Oid;\n"
        f"    public readonly string Msg;\n"
        f"    public __KirOpRefusal(string __oid, string __msg) : base(__msg)\n"
        f"    {{ Oid = __oid; Msg = __msg; }}\n"
        f"}}\n"
    ) if per_op else ""
    document_guard_raw = _document_binding_guard(
        expected_document, rollback="__t.RollBack(); ")
    document_guard = (
        _indent(document_guard_raw, "        ") + "\n"
        if document_guard_raw else ""
    )
    identity_guard_raw = _element_identity_guard(
        expected_identities, revit_version, rollback="__t.RollBack(); ")
    identity_guard = (
        _indent(identity_guard_raw, "        ") + "\n"
        if identity_guard_raw else ""
    )
    return _with_program_helpers(
        f"{_AUTH_PREAMBLE}\n"
        + op_refuse_decl
        + "\n".join(decls) + "\n"
        f"using (Transaction __t = new Transaction(doc, {_cs(txn_name)}))\n"
        f"{{\n"
        f"    try\n    {{\n"
        f"        var __startStatus = __t.Start();\n"
        f"        if (__startStatus != TransactionStatus.Started)\n"
        f"            return __Refuse(\"$program\", \"transaction start status: \" + __startStatus.ToString());\n"
        + document_guard +
        identity_guard +
        # Never let a Revit WARNING dialog silently cancel the whole program:
        # swallow warnings so every element still commits; a real ERROR is left
        # for Revit to surface, never auto-cancelled here. Unconditional across
        # isolation/postcondition modes — a lost element hurts chat too.
        failure_channel_reset_cs("__KirMainFailures", "        ") +
        f"        var __fho = __t.GetFailureHandlingOptions();\n"
        f"        __fho.SetFailuresPreprocessor(new __KirMainFailures());\n"
        f"        __fho.SetForcedModalHandling(false);\n"
        f"        __fho.SetClearAfterRollback(true);\n"
        f"        __t.SetFailureHandlingOptions(__fho);\n"
        f"{ind}\n"
        + post_gate +
        f"        var __commitStatus = __t.Commit();\n"
        f"        if (__commitStatus != TransactionStatus.Committed)\n"
        f"        {{\n"
        f"            try {{ if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack(); }} catch {{ }}\n"
        f"            var __refused = __Refuse(\"$program\", \"transaction commit status: \" + __commitStatus.ToString()\n"
        f"                + (__KirMainFailures.Seen.Count > 0 ? \" | Revit: \" + String.Join(\" ; \", __KirMainFailures.Seen) : \"\"));\n"
        f"            __refused[\"commit_status\"] = __commitStatus.ToString();\n"
        # Предупреждения едут и на пути ОТКАЗА, и структурой, а не строкой:
        # `__Refuse` отдаёт словарь, поэтому мутация здесь не трогает
        # преамбулу (её байты общие у ВСЕХ программ, включая query).
        f"            if (__KirMainFailures.Warned.Count > 0)\n"
        f"                __refused[\"revit_warnings\"] = __KirMainFailures.Warned;\n"
        # На пути ОТКАЗА разрешённые ошибки нужнее, чем на пути успеха:
        # программа не встала, а Revit уже что-то решил за нас, и читателю
        # надо знать ЧТО — иначе «откатилось» выглядит как «ничего не было».
        f"            if (__KirMainFailures.Resolved.Count > 0)\n"
        f"                __refused[\"revit_errors_resolved\"] = __KirMainFailures.Resolved;\n"
        f"            return __refused;\n"
        f"        }}\n"
        f"    }}\n"
        f"    catch\n    {{\n"
        f"        if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack();\n"
        f"        throw;\n"
        f"    }}\n"
        f"}}\n\n"
        + "\n\n".join(readbacks) + "\n\n"
        + failure_warnings_into_results_cs("__KirMainFailures")
        + f"__results[\"ok\"] = true;\n"
        f"return __results;\n"
        f"}}\n"
        + failure_preprocessor_cs("__KirMainFailures")
        + op_refuse_class +
        f"private static class __KirPad\n"
        f"{{")
