"""6/6 compile-gate runner — the prod-path gate (SPEC §5, discipline item 4).

Wraps emitted Execute-bodies with the SAME wrap_user_code the serving pipeline
uses and drives the live kukai-compile.service (:52412) across all six Revit
versions. Exit code != 0 on any failure. Run:

    PYTHONPATH=backend backend/venv/bin/python -m kukai.ir.gate_runner
"""
from __future__ import annotations

import asyncio
import math
import os
import random
import sys
import tempfile

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_gate_queue.jsonl"))

from kukai.compile_client import CompileClient                     # noqa: E402
from kukai.llm.revit_execution_pipeline import wrap_user_code      # noqa: E402
from kukai.ir import spec                                          # noqa: E402
from kukai.ir.compiler import compile_program                      # noqa: E402
from kukai.ir.tests.test_golden import PROGRAMS                    # noqa: E402
from kukai.ir.tests.test_pbt import gen_program                    # noqa: E402

N_PBT = 25
SEED = 62026

#: Представительные id для тел боковых стадий. Эмитированный C# инвариантен к
#: ЧИСЛУ id по форме, поэтому двух хватает; важно лишь, что они настоящие
#: числовые id, а не заглушки, — числовой разбор внутри тела реален.
GATE_SIDE_STAGE_IDS = ["19227219", "456"]

#: Стадии, чей C# едет в Revit, но которых НЕТ в реестре конвейера. Tier G
#: теперь является live-стадией ``geometry`` и берётся из того же реестра, так
#: что честный остаток пуст. Новая обходная стадия обязана быть названа здесь.
UNREGISTERED_GATE_STAGES = frozenset()


def side_stage_gate_bodies(revit_version: str) -> dict[str, str]:
    """C# КАЖДОЙ боковой стадии, эмитированный ДЛЯ ЭТОЙ версии Revit.

    ПОЧЕМУ ЭТО ФУНКЦИЯ, А НЕ СПИСОК ИМПОРТОВ ВНУТРИ ``main``. До 30.07 здесь
    лежал ручной словарь из четырёх строителей: ``family_placement`` /
    ``group`` / ``curtain`` / ``sketch``. Стадий было девять. Пять из них —
    ``curve``, ``geometry`` и три новых (аннотации, системы MEP, марки) — ворота
    не видели, и одна из них не собиралась на трети поставляемых версий:

        CS1503: Argument 1: cannot convert from 'long' to
        'Autodesk.Revit.DB.BuiltInParameter'

    Разбор 59-этажной башни на R2023 повторял этот отказ по кругу полтора
    часа с ``bridge_roundtrips=0``. Ручной словарь не мог этого поймать по
    построению: чтобы стадия попала в ворота, кто-то должен был вспомнить.

    Теперь источник строителей ОДИН — реестр конвейера. Стадия, добавленная в
    реестр, попадает в ворота сама; стадия, добавленная мимо реестра, обязана
    быть названа в :data:`UNREGISTERED_GATE_STAGES`, иначе сверка имён
    (``test_side_stage_contract.SideStageGateCoverageTests``) валит сборку.

    ЭМИССИЯ ПОД ВЕРСИЮ, А НЕ ОДИН ТЕКСТ ШЕСТЬ РАЗ: у марок C# зависит от
    версии по построению (шов ``TaggedLocalElementId`` /
    ``GetTaggedLocalElementIds`` на 2022). Ворота, эмитирующие однажды,
    проверяли бы одну поверхность шесть раз — дефект, который
    ``tools/compile_gate_offline.py`` уже описал в своём докстринге.
    """
    from kukai.ir.decompile import pipeline as _pipe
    return {
        stage: builder(GATE_SIDE_STAGE_IDS)
        for stage, builder in _pipe._default_cs_builders(revit_version).items()
    }


def acceptance_gate_body() -> str:
    """Representative live L2 reread, compiled on every shipped Revit API."""

    from kukai.ir.acceptance import derive_expectation
    from kukai.ir.acceptance_live import build_scope_census_cs
    from kukai.ir.compiler import plan_program
    from kukai.ir.contracts import DocumentFingerprint

    planned = plan_program({
        "ir_version": "1.0",
        "ops": [
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Gate L1"}},
            {"op": "create_pipe", "id": "P1",
             "p0_mm": [0, 0, 2700], "p1_mm": [6000, 0, 2700],
             "level": {"by": "element_id", "value": 42},
             "diameter_mm": 50},
        ],
    })
    expectation = derive_expectation(
        planned, level_names_by_id={42: "Gate L1"})
    return build_scope_census_cs(
        expectation,
        DocumentFingerprint(
            title="KIR gate COPY",
            path_name="gate.rvt",
            project_uid="kir-gate-project",
        ),
        run_id="0" * 32,
        phase="before",
    )


def mutation_acceptance_gate_body(revit_version: str) -> str:
    """Representative atomic census + exact-mutation reread for one API."""

    from kukai.ir.acceptance import derive_expectation
    from kukai.ir.acceptance_mutation import derive_mutation_expectation
    from kukai.ir.acceptance_probe import build_acceptance_probe_cs
    from kukai.ir.compiler import plan_program
    from kukai.ir.contracts import DocumentFingerprint

    planned = plan_program({
        "ir_version": "1.0",
        "allow_destructive": True,
        "ops": [
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Gate L1"}},
            {"op": "set_param", "id": "S1",
             "target": {"by": "element_id", "value": 101},
             "param": "Comments", "value": "KIR gate"},
            {"op": "move_elements", "id": "M1",
             "targets": [{"by": "element_id", "value": 102}],
             "delta_mm": [100, 0, 500]},
            {"op": "change_type", "id": "T1",
             "target": {"by": "element_id", "value": 103},
             "type": {"by": "element_id", "value": 900}},
            {"op": "delete", "id": "D1",
             "target": {"by": "element_id", "value": 104}},
        ],
    })
    document = DocumentFingerprint(
        title="KIR gate COPY",
        path_name="gate.rvt",
        project_uid="kir-gate-project",
    )
    return build_acceptance_probe_cs(
        plan_digest=planned.plan_digest,
        scope_expectation=derive_expectation(planned),
        mutation_expectation=derive_mutation_expectation(planned),
        document=document,
        run_id="1" * 32,
        phase="before",
        revit_version=revit_version,
    )


async def main() -> int:
    client = CompileClient()
    if not await client.health():
        print("FATAL: compile service :52412 unavailable")
        return 2

    programs: dict[str, dict] = dict(PROGRAMS)
    rng = random.Random(SEED)
    for i in range(N_PBT):
        programs[f"pbt_{i:02d}"] = gen_program(rng)
    # Programs exercising every kind. A KIR program is capped at 20 ops, so
    # chunk instead of truncating: the old [:20] silently left the final kind
    # outside the live gate as soon as the registry grew to 21 entries.
    _kind_ops = [
        {"op": "query_count", "id": f"k{j}", "kind": kind}
        for j, kind in enumerate(sorted(spec.KINDS))
    ]
    for offset in range(0, len(_kind_ops), 20):
        programs[f"all_kinds_{offset // 20:02d}"] = {
            "ir_version": "1.0", "ops": _kind_ops[offset:offset + 20]}
    # fix/g102-disambiguate (2026-07-17): query_types — one program per
    # closed pool, proving every _TYPE_POOL_COLLECTOR_CS idiom (compiler.py)
    # actually compiles on all six versions (the two-table-lockstep guard
    # test_authoring.QueryTypes.test_all_sixteen_pools_compile_offline
    # proves offline; this is the same proof through the live gate).
    _qt_pools = spec.OPS["query_types"].params[0].choices
    programs["query_types_all_pools"] = {"ir_version": "1.0",
        "intent": "какие типы существуют в каждом закрытом пуле",
        "ops": [{"op": "query_types", "id": f"t{j}", "pool": p}
                for j, p in enumerate(_qt_pools)]}
    # authoring family — grounded via the COMMITTED shared fixture (fixtures.py,
    # same snapshot unit tests and goldens use; a private harness copy is how
    # the 2026-07-16 checkpoint became non-reproducible from HEAD)
    from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
    from kukai.ir.tests.test_authoring import _prog, _wall
    programs["auth_wall"] = _prog([_wall()], intent="стена 6м")
    programs["auth_mixed"] = _prog([
        _wall(),
        _wall(oid="W2", p0_mm=[0, 4000], p1_mm=[6000, 4000],
              type={"by": "name", "value": "ЖБ 200"}, height_mm=2800),
        {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
         "p1_mm": [3000, 0, 2700], "level": {"by": "element_id", "value": 42},
         "diameter_mm": 50},
        {"op": "create_grid", "id": "G1", "p0_mm": [0, -1000],
         "p1_mm": [0, 9000], "name": "А"},
    ], intent="стены+труба+ось")
    programs["auth_stack"] = {"ir_version": "1.0", "intent": "стек 5 этажей",
        "ops": [{"op": "stack", "id": "sec", "levels": 5, "h_mm": 3000,
                 "floor": [
                     {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                      "p1_mm": [6000, 0], "height_mm": 2800},
                     {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
                      "p1_mm": [3000, 0, 2700], "diameter_mm": 50},
                 ]}]}
    programs["auth_grid_array"] = {"ir_version": "1.0", "intent": "сетка осей 4x3",
        "ops": [{"op": "grid_array", "id": "net", "nx": 4, "ny": 3,
                 "dx_mm": 6000, "dy_mm": 4500, "prefix_y": "А"}]}
    programs["auth_stairs"] = {"ir_version": "1.0", "intent": "лестничный марш",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "p0_mm": [0, 0], "p1_mm": [5000, 0],
                 "base_level": {"by": "element_id", "value": 42},
                 "top_level": {"by": "element_id", "value": 43},
                 "width_mm": 1200}]}
    # feat/native-groups: a native Revit group (create_group). Members are
    # PRE-GROUNDED authoring ops (the component-library bridge shape); the group
    # op grounds through with no snapshot dependency (grounded=()), and the two
    # placement deltas exercise the O0+delta emission on all six versions.
    def _grp_wall(oid, x0, y0, x1, y1):
        return {"op": "create_wall", "id": oid, "p0_mm": [x0, y0],
                "p1_mm": [x1, y1],
                "level": {"__grounded__": {"id": 42, "name": None,
                                           "via": "element_id"}},
                "height_mm": 3000.0,
                "type": {"__grounded__": {"id": None, "name": None,
                                          "via": "doc_default",
                                          "in_emit": "__doc_default__"}}}
    programs["auth_native_group"] = {"ir_version": "1.0",
        "intent": "типовой этаж как нативная группа",
        "ops": [{"op": "create_group", "id": "GRP1", "name": "Типовой этаж",
                 "members": [_grp_wall("W1", 30000, 23000, 36000, 23000),
                             _grp_wall("W2", 36000, 23000, 36000, 27000)],
                 "placements": [[0, 0, 6600], [0, 0, 13200]]}]}
    programs["mod_setparam_delete"] = {"ir_version": "1.0",
        "intent": "параметр + удаление", "allow_destructive": True,
        "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 12000, "name": "Тех"},
            {"op": "set_param", "id": "S1", "target": {"by": "ref", "value": "L1"},
             "param": "Комментарии", "value": "создан KIR"},
            {"op": "set_param", "id": "S2",
             "target": {"by": "element_id", "value": 7777},
             "param": "Смещение снизу", "value": {"value": 250, "unit": "mm"}},
            {"op": "delete", "id": "D1",
             "target": {"by": "element_id", "value": 8888}},
        ]}
    programs["auth_contour_l"] = {"ir_version": "1.0", "intent": "Г-плита по контуру с проёмом",
        "ops": [{"op": "create_floor_by_contour", "id": "F1",
                 "contour": {"outer": {"shape": "l", "origin": [0, 0],
                                       "size_mm": [16000, 10000], "cut_mm": [6000, 4000]},
                             "holes": [{"shape": "rect", "origin": [1000, 1000],
                                        "size_mm": [3000, 6000]}]},
                 "level": {"by": "name", "value": "Этаж 1"}}]}
    programs["auth_contour_arc"] = {"ir_version": "1.0", "intent": "контур с дугой",
        "ops": [{"op": "create_floor_by_contour", "id": "F1",
                 "contour": {"outer": {"shape": "poly",
                                       "points_mm": [[0,0],[8000,0],[8000,6000],[0,6000]],
                                       "arcs": [{"edge": 1, "radius_mm": 5000}]}},
                 "level": {"by": "element_id", "value": 42}}]}
    # CONTOUR обратным ходом (28.07): контур с ДУГОЙ и СМЕЩЕНИЕМ ОТ УРОВНЯ —
    # ровно та форма, которую теперь строит лифт для дуговых полов. Смещение
    # у 107 из 155 таких полов «демо-v3», поэтому ветка параметра обязана
    # компилироваться на всех шести версиях, а не только в тесте эмиссии.
    programs["auth_contour_arc_offset"] = {"ir_version": "1.0",
        "intent": "дуговой контур со смещением от уровня",
        "ops": [{"op": "create_floor_by_contour", "id": "F1",
                 "contour": {"outer": {"shape": "poly",
                                       "points_mm": [[13012.5, 58950.0],
                                                     [21287.0, 58950.0],
                                                     [14544.7, 55088.2]],
                                       "arcs": [{"edge": 2, "bulge": 0.2874}]}},
                 "level": {"by": "element_id", "value": 42},
                 "height_offset_mm": -700.0}]}
    programs["auth_pipe_system_chain"] = {"ir_version": "1.0", "intent": "стояк ВК с отводом",
        "ops": [{"op": "create_pipe_system", "id": "SYS1", "level": {"by": "element_id", "value": 42},
                 "nodes": [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [0, 0, 15000]},
                           {"id": "N3", "xyz_mm": [3000, 0, 15000]}],
                 "segments": [{"from": "N1", "to": "N2", "diameter_mm": 100},
                              {"from": "N2", "to": "N3", "diameter_mm": 50}]}]}
    programs["auth_pipe_system_tee"] = {"ir_version": "1.0", "intent": "тройник",
        "ops": [{"op": "create_pipe_system", "id": "SYS1", "level": {"by": "element_id", "value": 42},
                 "diameter_mm": 100,
                 "nodes": [{"id": "T", "xyz_mm": [0, 0, 0]}, {"id": "A", "xyz_mm": [3000, 0, 0]},
                           {"id": "B", "xyz_mm": [-3000, 0, 0]}, {"id": "C", "xyz_mm": [0, 3000, 0]}],
                 "segments": [{"from": "T", "to": "A"}, {"from": "T", "to": "B"}, {"from": "T", "to": "C"}]}]}
    from kukai.ir.tests.test_golden import PROGRAMS as _GP
    programs["auth_full_house"] = _GP["full_house_v1"]
    # wave/mep (2026-07-17): route_pipe_system / route_duct_system gate
    # coverage beyond the two golden programs (already included via PROGRAMS
    # above: route_pipe_system_riser_branch, route_duct_system_tee). Adds the
    # ring topology (CONNECT checklist's "кольцо — если домен допускает") and
    # a duct tee, so the 6-version gate exercises both fitting types
    # (elbow/tee) on BOTH domains, not just pipe.
    programs["auth_route_pipe_ring"] = {"ir_version": "1.0", "intent": "кольцевая сеть ВК",
        "ops": [{"op": "route_pipe_system", "id": "SYSR",
                 "level": {"by": "element_id", "value": 42}, "diameter_mm": 100,
                 "nodes": [{"id": "R1", "xyz_mm": [0, 0, 3000]}, {"id": "R2", "xyz_mm": [4000, 0, 3000]},
                           {"id": "R3", "xyz_mm": [4000, 4000, 3000]}, {"id": "R4", "xyz_mm": [0, 4000, 3000]}],
                 "segments": [{"from": "R1", "to": "R2"}, {"from": "R2", "to": "R3"},
                              {"from": "R3", "to": "R4"}, {"from": "R4", "to": "R1"}]}]}
    programs["auth_route_duct_chain"] = {"ir_version": "1.0", "intent": "магистраль ОВ",
        "ops": [{"op": "route_duct_system", "id": "SYSD",
                 "level": {"by": "element_id", "value": 42},
                 "nodes": [{"id": "D1", "xyz_mm": [0, 0, 3000]}, {"id": "D2", "xyz_mm": [6000, 0, 3000]},
                           {"id": "D3", "xyz_mm": [6000, 0, 2950]}],
                 "segments": [{"from": "D1", "to": "D2", "diameter_mm": 400},
                              {"from": "D2", "to": "D3", "diameter_mm": 200,
                               "slope_min_pct": 1.0}]}]}
    # fix/mep-fittings (2026-07-17): the exact live-semantic-test failure
    # shape — a straight (collinear) riser continuation used to force an
    # elbow onto a node with nothing to bend, and Revit refused at runtime
    # ("failed to insert elbow"). These two programs put the fixed
    # classify_junction branches ("connect" via Connector.ConnectTo, and
    # "transition" via NewTransitionFitting) through the real 6-version
    # compile gate, not just the offline unit/golden corpus — proving the
    # emit itself still compiles on every version with the new branches
    # live. auth_route_pipe_ring/auth_route_duct_chain above stay as the
    # pre-existing bend/branch coverage, unaffected by this fix.
    programs["auth_route_pipe_straight_riser"] = {
        "ir_version": "1.0", "intent": "прямой стояк ВК без изгиба (ConnectTo, не отвод)",
        "ops": [{"op": "route_pipe_system", "id": "SYSS",
                 "level": {"by": "element_id", "value": 42}, "diameter_mm": 100,
                 "nodes": [{"id": "S1", "xyz_mm": [0, 0, 0]}, {"id": "S2", "xyz_mm": [0, 0, 6000]},
                           {"id": "S3", "xyz_mm": [0, 0, 12000]}],
                 "segments": [{"from": "S1", "to": "S2"}, {"from": "S2", "to": "S3"}]}]}
    programs["auth_route_duct_straight_transition"] = {
        "ir_version": "1.0", "intent": "прямой переход диаметра ОВ на стыке (NewTransitionFitting)",
        "ops": [{"op": "route_duct_system", "id": "SYST",
                 "level": {"by": "element_id", "value": 42},
                 "nodes": [{"id": "S1", "xyz_mm": [0, 0, 3000]}, {"id": "S2", "xyz_mm": [5000, 0, 3000]},
                           {"id": "S3", "xyz_mm": [10000, 0, 3000]}],
                 "segments": [{"from": "S1", "to": "S2", "diameter_mm": 400},
                              {"from": "S2", "to": "S3", "diameter_mm": 250}]}]}
    # Витражные ячейки (дизайн 2026-07-28). Ворота обязаны компилировать ОБЕ
    # формы носителя (ref на стену этой же программы и пинованный
    # element_id — дизайн пишет `host: ref|element_id`) и ОБЕ формы селектора
    # типа (имя, которое эмиттер разрешает коллектором по двум пространствам
    # типов, и пинованный element_id). Адрес (0,0) — не «пустой», а сетка
    # 1×1: ровно тот частный случай, который дизайн запретил считать
    # оправданием отсутствия адреса.
    programs["auth_curtain_cell_named_type"] = {"ir_version": "1.0",
        "intent": "витраж: стеклопакет в единственную ячейку",
        "ops": [
            {"op": "create_wall", "id": "WC", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42},
             "height_mm": 3000},
            {"op": "set_curtain_panel", "id": "CP1",
             "host": {"by": "ref", "value": "WC"}, "u": 0, "v": 0,
             "panel_type": {"by": "name", "value": "Стеклопакет 30мм"}},
        ]}
    programs["auth_curtain_cell_grid"] = {"ir_version": "1.0",
        "intent": "витраж: разные типы в ячейках сетки существующей стены",
        "ops": [
            {"op": "set_curtain_panel", "id": "CP1",
             "host": {"by": "element_id", "value": 8145901}, "u": 0, "v": 0,
             "panel_type": {"by": "element_id", "value": 273445}},
            {"op": "set_curtain_panel", "id": "CP2",
             "host": {"by": "element_id", "value": 8145901}, "u": 2, "v": 1,
             "panel_type": {"by": "name", "value": "Стена НР_ВТ 200мм"}},
            {"op": "set_curtain_panel", "id": "CP3",
             "host": {"by": "element_id", "value": 8145901}, "u": 3, "v": 0,
             "panel_type": {"by": "name", "value": "Пустая панель"}},
        ]}
    # Линии разрезки витража (волна 29.07): ворота обязаны компилировать обе
    # формы носителя (ref на стену этой же программы и пинованный element_id)
    # и ОБА направления — isUGridLine у AddGridLine булев, и перепутанная
    # ветка не видна ничем, кроме живой модели.
    programs["auth_curtain_grid_lines"] = {"ir_version": "1.0",
        "intent": "витраж: раскладка сетки — своя линия на каждый шаг",
        "ops": [
            {"op": "create_wall", "id": "WG", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42},
             "height_mm": 3000},
            {"op": "create_curtain_grid_line", "id": "GL1",
             "host": {"by": "ref", "value": "WG"}, "direction": "u",
             "position_mm": [2000.0, 0.0, 1500.0]},
            {"op": "create_curtain_grid_line", "id": "GL2",
             "host": {"by": "ref", "value": "WG"}, "direction": "v",
             "position_mm": [3000.0, 0.0, 2100.0]},
            {"op": "create_curtain_grid_line", "id": "GL3",
             "host": {"by": "element_id", "value": 8145901},
             "direction": "u", "position_mm": [4000.0, 120.0, 900.0]},
        ]}
    # wave/shape: произвольная геометрия мешем. Меш порождается МАТЕМАТИКОЙ
    # прямо здесь (витая башня), а не приносится списком литералов: гейт
    # должен гонять ту же форму, которой пользуются живьём, и оставаться
    # читаемым. 16 граней × 12 этажей + крышка и днище = 416 треугольников —
    # десятая часть замеренного предела MAX_TRIANGLES=4096.
    def _twisted_tower_mesh(sides=16, storeys=12, r0=6000.0, r1=3500.0,
                            h=36000.0, twist=140.0):
        verts, tris = [], []
        for k in range(storeys + 1):
            f = k / storeys
            r = r0 + (r1 - r0) * f
            a0 = math.radians(twist * f)
            for j in range(sides):
                a = a0 + 2 * math.pi * j / sides
                verts.append([r * math.cos(a), r * math.sin(a), h * f])
        for k in range(storeys):
            for j in range(sides):
                a, b = k * sides + j, k * sides + (j + 1) % sides
                c, d = (k + 1) * sides + j, (k + 1) * sides + (j + 1) % sides
                tris += [[a, b, d], [a, d, c]]
        bot = len(verts); verts.append([0.0, 0.0, 0.0])
        top = len(verts); verts.append([0.0, 0.0, h])
        for j in range(sides):
            tris.append([bot, (j + 1) % sides, j])
            tris.append([top, storeys * sides + j,
                         storeys * sides + (j + 1) % sides])
        return verts, tris

    _ds_verts, _ds_tris = _twisted_tower_mesh()
    programs["auth_directshape_tower"] = {
        "ir_version": "1.0", "intent": "витая башня мешем",
        "ops": [{"op": "create_directshape", "id": "D1",
                 "mesh": {"vertices_mm": _ds_verts, "triangles": _ds_tris},
                 "category": "mass", "name": "витая башня"}]}
    programs["auth_floor_holes"] = {"ir_version": "1.0", "intent": "плита с проёмом",
        "ops": [{"op": "create_floor", "id": "F1",
                 "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
                 "holes": [[[3000, 2000], [5000, 2000], [5000, 4000], [3000, 4000]]],
                 "level": {"by": "name", "value": "Этаж 1"}}]}
    # Documentation family (ops_annotation.py): create_dimension/create_tag/
    # create_text had ZERO live 6-version compile coverage before 28.07 — the
    # per_op gate finding that closed the in_view:{by:ref} CS0039 hole (see
    # expected_refusals below) surfaced that this whole op family had never
    # been driven through the real compile service, atomic OR per_op, at
    # all. in_view here stays element_id (the only legal form after the fix).
    programs["auth_annotation"] = {"ir_version": "1.0", "intent": "аннотации",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42},
             "height_mm": 3000},
            {"op": "create_dimension", "id": "DIM1",
             "in_view": {"by": "element_id", "value": 900},
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "element_id", "value": 12345}],
             "line_at": [3000, 500]},
            {"op": "create_tag", "id": "TAG1",
             "in_view": {"by": "element_id", "value": 900},
             "target": {"by": "ref", "value": "W1"}, "at": [3000, 800]},
            {"op": "create_text", "id": "TXT1",
             "in_view": {"by": "element_id", "value": 900},
             "at": [1000, 1000], "content": "Проверка"},
        ]}
    # host: element_id (28.07, audit's most frequent external scenario:
    # «поставь окно в МОЮ стену»). No wall op in this program on purpose —
    # the whole point is a host the program never creates. Runtime frame
    # (doc.GetElement(...) as Wall, LocationCurve, Curve.Evaluate(t, true))
    # goes through the live 6-version compile gate here, atomic AND per_op
    # (the per_op axis below), same bar as everything else in this table.
    # No expected-refusal entry needed: element_id is now a legal host.
    programs["auth_hosted_element_id"] = {"ir_version": "1.0",
        "intent": "дверь и окно на чужой стене (host по element_id)",
        "ops": [
            {"op": "create_door", "id": "D1",
             "host": {"by": "element_id", "value": 8145901},
             "offset_mm": 1500, "sill_mm": -100,
             "symbol": {"by": "name", "value": "Дверь 900x2100"}},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "element_id", "value": 8145901},
             "offset_mm": 3000, "sill_mm": 900,
             "symbol": {"by": "name", "value": "Окно 1200x1500"}},
        ]}
    # CLASH-починка (28.07, оператор: ранний честный релиз): move_elements +
    # change_type. targets mixes ref (this program's own wall+pipe, so
    # ElementTransformUtils.MoveElements is proven on a LocationCurve pair
    # created in the SAME transaction) with element_id (an existing
    # element); change_type runs on the same created wall, byref, proving
    # the target_w path independent of host/type selector kind.
    programs["auth_move_and_change_type"] = {"ir_version": "1.0",
        "intent": "перенос связки стена+труба, смена типа стены",
        "ops": [
            {"op": "create_wall", "id": "MW", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42}},
            {"op": "create_pipe", "id": "MP", "p0_mm": [0, 0, 2700],
             "p1_mm": [3000, 0, 2900], "level": {"by": "element_id", "value": 42},
             "diameter_mm": 50},
            {"op": "move_elements", "id": "ME1",
             "targets": [{"by": "ref", "value": "MW"},
                         {"by": "ref", "value": "MP"},
                         {"by": "element_id", "value": 8145901}],
             "delta_mm": [1000.0, 0.0, 500.0]},
            {"op": "change_type", "id": "CT1",
             "target": {"by": "ref", "value": "MW"},
             "type": {"by": "element_id", "value": 5001}},
        ]}
    # ops_families gate (wave/families, 2026-07-17): create_type (FamilySymbol
    # duplication — the exact prod incident this wave fixes, RC columns coming
    # in as steel because no create_type existed) + load_family (Document.
    # LoadFamily/LoadFamilySymbol, wiki family-load-place.md FAM-034 pattern).
    programs["families_create_type_full"] = {"ir_version": "1.0",
        "intent": "жб колонна 400x400 из существующего типа",
        "ops": [{"op": "create_type", "id": "T1",
                 "source_type": {"by": "element_id", "value": 500},
                 "category": "structural", "new_name": "ЖБ 400x400",
                 "width_mm": 400, "depth_mm": 400, "material": "Бетон"}]}
    programs["families_create_type_by_name_custom_params"] = {"ir_version": "1.0",
        "intent": "тип по имени источника с нестандартными именами параметров",
        "ops": [{"op": "create_type", "id": "T1",
                 "source_type": {"by": "name", "value": "К 300x300"},
                 "category": "structural", "new_name": "К 350x300",
                 "width_mm": 350, "param_width_name": "b"}]}
    programs["families_create_type_architectural"] = {"ir_version": "1.0",
        "intent": "архитектурная колонна нового сечения",
        "ops": [{"op": "create_type", "id": "T1",
                 "source_type": {"by": "element_id", "value": 501},
                 "category": "architectural", "new_name": "Колонна 400",
                 "width_mm": 400, "param_width_name": "Width"}]}
    programs["families_type_then_setparam_ref"] = {"ir_version": "1.0",
        "intent": "тип + правка комментария к типу по intra-program ref",
        "ops": [
            {"op": "create_type", "id": "T1",
             "source_type": {"by": "element_id", "value": 500},
             "category": "structural", "new_name": "ЖБ 400x400 v2",
             "width_mm": 400, "depth_mm": 400},
            {"op": "set_param", "id": "S1", "target": {"by": "ref", "value": "T1"},
             "param": "Комментарии типа", "value": "создан KIR"},
        ]}
    programs["families_load_family_whole"] = {"ir_version": "1.0",
        "intent": "загрузить семейство целиком (первый типоразмер)",
        "ops": [{"op": "load_family", "id": "F1",
                 "path": r"C:\ProgramData\Autodesk\RVT 2024\Libraries\Russian\Конструкции\Колонны\Бетонные\M_Бетонная-Прямоугольная-Колонна.rfa"}]}
    programs["families_load_family_named_type"] = {"ir_version": "1.0",
        "intent": "загрузить один именованный типоразмер",
        "ops": [{"op": "load_family", "id": "F1",
                 "path": r"C:\Lib\Doors\Standard.rfa", "type_name": "0900x2100"}]}
    rnga_fam = random.Random(SEED + 2)
    _fam_sources = [({"by": "element_id", "value": 500}, "structural"),
                    ({"by": "name", "value": "К 300x300"}, "structural"),
                    ({"by": "element_id", "value": 501}, "architectural")]
    for i in range(8):
        src, cat = rnga_fam.choice(_fam_sources)
        op = {"op": "create_type", "id": "T1", "source_type": src, "category": cat,
              "new_name": f"КИР-тип-{i}", "width_mm": float(rnga_fam.randint(50, 2000))}
        if rnga_fam.random() < 0.6:
            op["depth_mm"] = float(rnga_fam.randint(50, 2000))
        if rnga_fam.random() < 0.3:
            op["material"] = rnga_fam.choice(["Бетон", "Сталь", "Дерево"])
        programs[f"families_pbt_{i}"] = {"ir_version": "1.0",
            "intent": "families pbt", "ops": [op]}
    # wave/struct (2026-07-17): create_beam + create_foundation (both
    # varieties) gate coverage. struct_beam/struct_foundation_isolated/
    # struct_foundation_slab already included above via test_golden.PROGRAMS;
    # these add the version-axis edge case (slab holes refused pre-2022,
    # mirrors auth_floor_holes/auth_contour_l) plus a mixed authoring program
    # (beam + isolated footing sharing one txn/level, the realistic "колонна
    # + фундамент + балка" combo) and PBT coverage.
    programs["struct_foundation_slab_holes_2021"] = {"ir_version": "1.0",
        "intent": "плитный фундамент с проёмом (версионная граница)",
        "ops": [{"op": "create_foundation", "id": "F1", "variety": "slab",
                 "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
                 "holes": [[[3000, 2000], [5000, 2000], [5000, 4000], [3000, 4000]]],
                 "level": {"by": "name", "value": "Этаж 1"}}]}
    programs["struct_beam_and_isolated_footing"] = {"ir_version": "1.0",
        "intent": "колонна: фундамент + балка на одном уровне",
        "ops": [
            {"op": "create_foundation", "id": "F1", "variety": "isolated",
             "xy": [0, 0], "level": {"by": "element_id", "value": 42}},
            {"op": "create_foundation", "id": "F2", "variety": "isolated",
             "xy": [6000, 0], "level": {"by": "element_id", "value": 42}},
            {"op": "create_beam", "id": "B1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000], "level": {"by": "element_id", "value": 42}},
        ]}
    rnga_struct = random.Random(SEED + 3)
    for i in range(8):
        x0 = rnga_struct.randint(-50000, 50000)
        z0 = rnga_struct.randint(0, 4000)
        if rnga_struct.random() < 0.5:
            programs[f"struct_beam_pbt_{i}"] = {"ir_version": "1.0", "intent": "балка pbt",
                "ops": [{"op": "create_beam", "id": "B1",
                         "p0_mm": [x0, x0, z0],
                         "p1_mm": [x0 + rnga_struct.randint(1000, 15000), x0, z0],
                         "level": {"by": "element_id", "value": 42}}]}
        else:
            w = rnga_struct.randint(2000, 20000)
            h = rnga_struct.randint(2000, 20000)
            programs[f"struct_foundation_pbt_{i}"] = {"ir_version": "1.0", "intent": "фундамент pbt",
                "ops": [{"op": "create_foundation", "id": "F1", "variety": "slab",
                         "outline": [[x0, x0], [x0 + w, x0], [x0 + w, x0 + h], [x0, x0 + h]],
                         "level": {"by": "element_id", "value": 42}}]}
    rnga = random.Random(SEED + 1)
    from kukai.ir.tests.test_authoring import NASTY
    for i in range(8):
        x0 = rnga.randint(-50000, 50000)
        programs[f"auth_pbt_{i}"] = _prog([
            _wall(oid=f"W{j}", p0_mm=[x0, j * 3000], p1_mm=[x0 + 5000, j * 3000],
                  height_mm=rnga.randint(1000, 6000))
            for j in range(rnga.randint(1, 4))
        ], intent=rnga.choice(NASTY))

    def _needs_snapshot(p: dict) -> bool:
        """By op FAMILY over the EXPANDED op list — macros hide pool-needing
        ops (a stack's pipes), so detection must run post-expansion; and never
        by program name (the checkpoint-return lesson)."""
        from kukai.ir import macros as _macros
        ops = p.get("ops", [])
        try:
            ops = _macros.expand(ops)
        except Exception:
            pass          # compiler will refuse; no snapshot decision needed
        for o in ops if isinstance(ops, list) else []:
            os_ = spec.OPS.get(o.get("op")) if isinstance(o, dict) else None
            if os_ is not None and os_.family in spec.WRITE_FAMILIES:
                return True
        return False

    # per_op axis (promoted from the scratch gate_per_op.py prototype,
    # 28.07): the atomic-only loop below left every emitter's per_op branch
    # — the SubTransaction wrapper closing over an emitter's own locals,
    # exactly the shape that produced the load_family CS0136 __ok_<s>
    # collision — compiled ZERO times by this gate; the only place per_op
    # ever ran live was a real A5/bulk rebuild. A KNOWN, already-tracked
    # per_op-only defect (fix pending, not yet landed) is counted as an
    # EXPECTED regression here — visible in the printed row, added to
    # known_gaps, and EXCLUDED from `failures` — never a silent green hole
    # (name not in the dict) and never an untracked plain failure (name in
    # the dict but still counted against the pass/fail bit).
    PER_OP_KNOWN_GAPS: dict[str, str] = {
        # name -> reason. Empty by construction (28.07): the two per_op
        # defects this same wave's per_op gate found — load_family CS0136
        # __ok_<s> collision, in_view:{by:ref} CS0039 — are BOTH fixed. This
        # dict is the mechanism for the NEXT one, not a resting place for
        # old bugs already closed.
    }
    checks = 0
    known_gaps = 0
    failures = 0

    async def _gate_row(name: str, prog: dict, snapshot, isolation: str) -> list[str]:
        nonlocal checks, known_gaps, failures
        row: list[str] = []
        for ver in spec.REVIT_VERSIONS:
            checks += 1
            out = compile_program(prog, revit_version=ver,
                                  snapshot=snapshot,
                                  isolation=isolation)   # per-version emit (SPEC 11.2)
            # wave/arch: у ПОТОЛКА отказ на 2021 — не «известная дыра», а
            # правильный ответ. Ceiling.Create появился в 2022, а
            # doc.Create.NewCeiling не существует ни на одной из шести версий
            # (замерено компиляцией), то есть построить потолок на 2021
            # нечем. Ворота обязаны отличать «операция честно сказала, что
            # на этой версии её нет» от «эмиссия сломалась»: без этой строки
            # зелёные ворота требовали бы от опа молча построить что-нибудь
            # другое — ровно тот Гудхарт, ради борьбы с которым отказ и
            # заведён.
            if not out.ok and name in ("auth_floor_holes", "auth_contour_l",
                                       "struct_foundation_slab_holes_2021",
                                       "struct_foundation_slab",
                                       "arch_ceiling") and ver == "2021" \
                    and any(d.code == "KIR-E003" for d in out.diagnostics):
                row.append(f"{ver}:E003-EXPECTED")
                continue
            if not out.ok:
                if name in PER_OP_KNOWN_GAPS:
                    row.append(f"{ver}:KNOWN-GAP")
                    known_gaps += 1
                    continue
                print(f"FAIL {name}@{ver} [{isolation}]: KIR refused: "
                      f"{[d.code for d in out.diagnostics][:3]}")
                failures += 1
                row.append(f"{ver}:REFUSED")
                continue
            wrapped = wrap_user_code(out.csharp)
            res = await client.check(wrapped, ver)
            if res is None:
                row.append(f"{ver}:SVC?")
                failures += 1
            elif res.success:
                row.append(f"{ver}:OK")
            elif name in PER_OP_KNOWN_GAPS:
                row.append(f"{ver}:KNOWN-GAP")
                known_gaps += 1
                for e in res.errors[:3]:
                    print(f"    {name} @{ver} [{isolation}, known gap: "
                          f"{PER_OP_KNOWN_GAPS[name]}] {e.code} L{e.line}: "
                          f"{e.message[:100]}")
            else:
                row.append(f"{ver}:FAIL")
                failures += 1
                for e in res.errors[:3]:
                    print(f"    {name} @{ver} [{isolation}] {e.code} L{e.line}: "
                          f"{e.message[:100]}")
        return row

    write_program_count = 0
    for name, prog in programs.items():
        needs_snapshot = _needs_snapshot(prog)
        snapshot = GROUND_SNAPSHOT if needs_snapshot else None
        atomic_row = await _gate_row(name, prog, snapshot, "atomic")
        print(f"{name:24s} {' '.join(atomic_row)}")
        # per_op is only a DIFFERENT emission for write-family programs (the
        # query/read path ignores isolation entirely — compiling it twice
        # would be redundant, not honest new coverage). `_needs_snapshot`
        # already computes exactly this predicate (post-macro-expansion, by
        # op family, never by program name — same discipline as its own
        # docstring), so it doubles as the per_op eligibility check.
        if needs_snapshot:
            write_program_count += 1
            per_op_row = await _gate_row(
                name, prog, snapshot, "per_op")
            print(f"{name + '_per_op':24s} {' '.join(per_op_row)}")

    # Expected-refusal gate: valuable invariants proven in CI, not left to be
    # accidental failures. (coordinator return, 2026-07-16)
    expected_refusals = {
        "auth_no_snapshot": (_prog([_wall()], intent="без снапшота"), None, "KIR-G103"),
        # 28.07 per_op gate finding: in_view:{by:ref} used to compile
        # (ok=True) into a GUARANTEED Roslyn CS0039.  Forward-reference
        # compatibility is now a typed-IR responsibility, so the invalid
        # non-referenceable view input must stop at KIR-T001 before grounding
        # or emission (also pinned in test_result_semantics.py).
        "auth_in_view_ref_refused": (
            _prog([_wall(), {"op": "create_tag", "id": "TAG1",
                             "in_view": {"by": "ref", "value": "W1"},
                             "target": {"by": "ref", "value": "W1"},
                             "at": [3000, 800]}], intent="in_view ref"),
            GROUND_SNAPSHOT, "KIR-T001"),
    }
    for name, (prog, snap, want_code) in expected_refusals.items():
        out = compile_program(prog, revit_version="2026", snapshot=snap)
        codes = [d.code for d in out.diagnostics]
        if not out.ok and want_code in codes:
            print(f"{name:24s} EXPECTED-REFUSAL:{want_code} OK")
        else:
            print(f"FAIL {name}: want refusal {want_code}, got ok={out.ok} codes={codes}")
            failures += 1

    # serving ground-snapshot collector: emitted-adjacent C#, same 6/6 bar
    from kukai.ir.serving import _SNAPSHOT_CS
    wrapped_snap = wrap_user_code(_SNAPSHOT_CS)
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        res = await client.check(wrapped_snap, ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    snapshot_cs @{ver} {e.code} L{e.line}: {e.message[:100]}")
    print(f"{'serving_snapshot_cs':24s} {' '.join(row)}")

    # Open-model transaction guard: optional internal emission is outside the
    # legacy byte corpus, so compile it explicitly on all versions.  This also
    # proves the document guard and identity guard remain separated by valid
    # newlines before the first mutation.
    import copy as _copy
    from kukai.ir.open_model import OpenModelProfile
    _guard_snapshot = _copy.deepcopy(GROUND_SNAPSHOT)
    for _level in _guard_snapshot["levels"]:
        _element_id = int(_level["id"])
        _level["unique_id"] = f"gate-level-{_element_id}"
        _level["version_guid"] = f"{_element_id:032x}"
    _guard_snapshot["levels__total"] = len(_guard_snapshot["levels"])
    _guard_profile = OpenModelProfile.from_ground_snapshot(_guard_snapshot)
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        guarded = compile_program(
            programs["auth_wall"],
            revit_version=ver,
            snapshot=GROUND_SNAPSHOT,
            expected_document={
                "title": "KIR gate COPY",
                "path_name": "",
                "project_uid": "kir-gate-project",
            },
            open_model_profile=_guard_profile,
        )
        if not guarded.ok:
            row.append(f"{ver}:REFUSED")
            failures += 1
            continue
        res = await client.check(wrap_user_code(guarded.csharp), ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    model_binding_guard @{ver} {e.code} L{e.line}: "
                      f"{e.message[:100]}")
    print(f"{'model_binding_guard':24s} {' '.join(row)}")

    # The independent acceptance body is not emitted by compile_program, so it
    # needs an explicit 6/6 proof just like the ground snapshot and decompile
    # side stages.  A Python shape test cannot detect a Revit API member drift.
    _acceptance_body = acceptance_gate_body()
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        res = await client.check(wrap_user_code(_acceptance_body), ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    acceptance_l2 @{ver} {e.code} L{e.line}: "
                      f"{e.message[:140]}")
    print(f"{'acceptance_l2':24s} {' '.join(row)}")

    # Mutation probes use LocationPoint/LocationCurve, GetParameters,
    # GetTypeId, UniqueId, and the version-split ElementId constructor.  They
    # are emitted per API version and must pass the same live compiler matrix.
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        res = await client.check(
            wrap_user_code(mutation_acceptance_gate_body(ver)), ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    acceptance_mutation @{ver} {e.code} L{e.line}: "
                      f"{e.message[:140]}")
    print(f"{'acceptance_mutation':24s} {' '.join(row)}")

    # DECOMPILE side-index bridge collectors: read-only Execute bodies emitted
    # by the extract builders.  Same 6/6 compile bar as serving_snapshot_cs —
    # the bridge round-trip is expensive, so a version-specific compile failure
    # must be caught here, not at a live-Revit run.  Bodies use only
    # representative ids/budgets (the emitted C# is id-count-invariant in
    # shape), and are EMITTED PER VERSION (see side_stage_gate_bodies).
    _side_rows: dict[str, list[str]] = {
        stage: [] for stage in side_stage_gate_bodies(spec.REVIT_VERSIONS[0])}
    for ver in spec.REVIT_VERSIONS:
        for _stage, _body in sorted(side_stage_gate_bodies(ver).items()):
            checks += 1
            res = await client.check(wrap_user_code(_body), ver)
            if res is None:
                _side_rows[_stage].append(f"{ver}:SVC?"); failures += 1
            elif res.success:
                _side_rows[_stage].append(f"{ver}:OK")
            else:
                _side_rows[_stage].append(f"{ver}:FAIL"); failures += 1
                for e in res.errors[:3]:
                    print(f"    боковая {_stage} @{ver} {e.code} L{e.line}: "
                          f"{e.message[:140]}")
    for _stage in sorted(_side_rows):
        print(f"{'боковая ' + _stage:24s} {' '.join(_side_rows[_stage])}")

    # БАЗОВОЕ ТЕЛО ИЗВЛЕЧЕНИЯ. До 31.07 ворота компилировали боковые стадии и
    # НЕ компилировали главную: `build_category_batch_cs` — тот самый код,
    # который читает каждый элемент каждого разбора. Дыра нашлась при добавке
    # `CEILING_HEIGHTABOVELEVEL_PARAM`: имя параметра было взято из
    # документации, а документация Autodesk расходится с её же сборками
    # (задача #78 — `SpatialElementTag.SpatialElement` описан в шести версиях
    # XML и отсутствует в шести DLL). Утверждать существование члена по
    # описанию — ровно то, от чего эти ворота и защищают.
    #
    # Трёх категорий достаточно и это ЗАМЕРЕНО, а не выбрано на глаз: блок
    # параметров общий для всех категорий (один набор `__Put*Param` на
    # элемент), различается только коллектор. Стена, потолок и перекрытие
    # берут три разных коллектора и один общий блок.
    from kukai.ir.decompile.extract import build_category_batch_cs
    for _cat in ("OST_Walls", "OST_Ceilings", "OST_Floors"):
        _row: list[str] = []
        _body = build_category_batch_cs(_cat)
        for ver in spec.REVIT_VERSIONS:
            checks += 1
            res = await client.check(wrap_user_code(_body), ver)
            if res is None:
                _row.append(f"{ver}:SVC?"); failures += 1
            elif res.success:
                _row.append(f"{ver}:OK")
            else:
                _row.append(f"{ver}:FAIL"); failures += 1
                for e in res.errors[:3]:
                    print(f"    извлечение {_cat} @{ver} {e.code} L{e.line}: "
                          f"{e.message[:140]}")
        print(f"{'извлечение ' + _cat:24s} {' '.join(_row)}")

    # УБОРКА ШТАМПОВ. Третья дыра одной породы, найденная за 31.07: ворота не
    # знали про `_orphan_sweep_cs` вовсе. Цена ошибки у этого генератора выше
    # средней — он единственный, кто УДАЛЯЕТ элементы из живой модели, и
    # несобирающаяся версия обнаружилась бы ровно в тот момент, когда человек
    # нажал «отменить построенное».
    #
    # Четыре варианта покрывают все ветви шаблона: предпросмотр против
    # удаления (разные блоки транзакции) и обе грамматики префикса — прогон A5
    # и хэш содержимого обычной программы. Страж отпечатка документа включён,
    # потому что он вставляет СВОЙ C# в оба блока.
    from kukai.ir.serving import DocumentFingerprint, _orphan_sweep_cs
    _fp = DocumentFingerprint(
        title="Ворота", path_name="gate.rvt", project_uid="gate-uid")
    _sweeps = {
        "a5 предпросмотр": ("kir:a5:" + "0" * 12 + ":" + "0" * 16 + ":", False),
        "a5 удаление": ("kir:a5:" + "0" * 12 + ":" + "0" * 16 + ":", True),
        "программа предпросмотр": ("kir:" + "0" * 8 + ":", False),
        "программа удаление": ("kir:" + "0" * 8 + ":", True),
    }
    for _label, (_prefix, _delete) in _sweeps.items():
        _row = []
        _body = _orphan_sweep_cs(
            _prefix, delete=_delete, document_fingerprint=_fp)
        for ver in spec.REVIT_VERSIONS:
            checks += 1
            res = await client.check(wrap_user_code(_body), ver)
            if res is None:
                _row.append(f"{ver}:SVC?"); failures += 1
            elif res.success:
                _row.append(f"{ver}:OK")
            else:
                _row.append(f"{ver}:FAIL"); failures += 1
                for e in res.errors[:3]:
                    print(f"    уборка {_label} @{ver} {e.code} L{e.line}: "
                          f"{e.message[:140]}")
        print(f"{'уборка ' + _label:24s} {' '.join(_row)}")

    await client.close()
    print(f"\n{'PASS' if failures == 0 else 'FAIL'}: "
          f"{len(programs)} programs (atomic) "
          f"+ {write_program_count} write programs (per_op), "
          f"x {len(spec.REVIT_VERSIONS)} versions each "
          f"+ {len(expected_refusals)} expected-refusal check(s), "
          f"{checks} live compile checks, "
          f"{known_gaps} known per_op gap(s) tracked separately, "
          f"{failures} failures")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
