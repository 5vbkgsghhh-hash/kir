"""Gate (b): golden corpus, chibicc discipline (SPEC 12.6a) — snapshots update
ONLY via KIR_UPDATE_GOLDEN=1 plus human/coordinator diff review. CI treats a
mismatch as red; auto-regeneration is forbidden."""
import os
import pathlib
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir.compiler import compile_program  # noqa: E402

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"

PROGRAMS = {
    # The canonical regression program: the 2026-07-16 incident query.
    "pdf_underlay_count": {
        "ir_version": "1.0",
        "intent": "посчитай PDF подложки",
        "ops": [{"op": "query_count", "id": "pdf", "kind": "pdf_underlay"}],
    },
    "list_walls_level1": {
        "ir_version": "1.0",
        "intent": "стены на уровне Этаж 1 с типами",
        "ops": [{"op": "query_list", "id": "walls", "kind": "wall",
                 "where": {"level_name": "Этаж 1"},
                 "fields": ["id", "name", "type_name", "level_name"], "limit": 50}],
    },
    "mixed_program": {
        "ir_version": "1.0",
        "intent": "сводка: связи CAD, виды, инспекция по имени",
        "ops": [
            {"op": "query_count", "id": "links", "kind": "cad_link"},
            {"op": "query_count", "id": "imports", "kind": "cad_import"},
            {"op": "query_list", "id": "views", "kind": "view", "limit": 20,
             "fields": ["id", "name"]},
            {"op": "query_inspect", "id": "probe",
             "target": {"by": "name", "value": "Стена-Тест", "kind": "wall"}},
        ],
    },
    # Authoring golden: exercises stamp, stale-guards, in-txn commit-gate,
    # topology postconditions and witness readback in one snapshot-reviewed file.
    "authoring_wall_pipe_grid": {
        "ir_version": "1.0",
        "intent": "стена 6м + труба ХВС + ось А",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "Кирпич 250"}, "height_mm": 3000},
            {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
             "p1_mm": [3000, 0, 2700], "level": {"by": "element_id", "value": 42},
             "diameter_mm": 50},
            {"op": "create_grid", "id": "G1", "p0_mm": [0, -1000],
             "p1_mm": [0, 9000], "name": "А"},
        ],
    },
    # Curve-IR (P4-B) golden: a curved (Arc) wall — Arc.Create instead of
    # Line.CreateBound plus the arc center/radius postcondition — in one
    # reviewed file, so a future diff isolates any drift in the arc branch. A
    # 90° fillet (r=325) matching LOT31's rounded corners; endpoints are the
    # arc's plan endpoints (325,0)->(0,325).
    "authoring_wall_arc": {
        "ir_version": "1.0",
        "intent": "дуговая стена (скруглённый угол r325)",
        "ops": [
            {"op": "create_wall", "id": "WA", "p0_mm": [325, 0],
             "p1_mm": [0, 325], "level": {"by": "name", "value": "Этаж 1"},
             "arc": {"curve_type": "Arc", "center_mm": [0.0, 0.0, 0.0],
                     "radius_mm": 325.0, "x_axis": [1.0, 0.0, 0.0],
                     "y_axis": [0.0, 1.0, 0.0], "start_angle_rad": 0.0,
                     "end_angle_rad": 1.5707963267948966}},
        ],
    },
    # Macro golden: stack expansion -> create_level DAG + per-storey walls,
    # single txn, ref-based topology checks.
    "stack_two_storeys": {
        "ir_version": "1.0",
        "intent": "две типовых этажа со стеной",
        "ops": [{"op": "stack", "id": "sec", "levels": 2, "h_mm": 3000,
                 "name_prefix": "Этаж",
                 "floor": [{"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                            "p1_mm": [6000, 0], "height_mm": 2800}]}],
    },
    # Modify golden: set_param (str + mm) and delete under allow_destructive.
    "modify_setparam_delete": {
        "ir_version": "1.0",
        "intent": "правка параметра и удаление",
        "allow_destructive": True,
        "ops": [
            {"op": "set_param", "id": "S1",
             "target": {"by": "element_id", "value": 7777},
             "param": "Комментарии", "value": "обработано KIR"},
            {"op": "delete", "id": "D1",
             "target": {"by": "element_id", "value": 8888}},
        ],
    },
    # Family-A completion golden: every authoring op in one reviewed file.
    "full_house_v1": {
        "ir_version": "1.0",
        "intent": "полный дом v1",
        "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 0, "name": "КИР-1"},
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [8000, 0],
             "level": {"by": "ref", "value": "L1"}},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000, "sill_mm": 900},
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 5000},
            {"op": "create_floor", "id": "F1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": {"by": "ref", "value": "L1"}},
            {"op": "create_column", "id": "C1", "xy": [4000, 3000],
             "level": {"by": "ref", "value": "L1"}},
            {"op": "create_room", "id": "R1", "xy": [4000, 3000],
             "level": {"by": "ref", "value": "L1"}, "name": "Зал"},
            {"op": "place_family", "id": "T1", "xyz": [2000, 2000, 0],
             "level": {"by": "ref", "value": "L1"}},
        ],
    },
    # wave/mep golden (2026-07-17): route_pipe_system (ВК stack+branch with a
    # checked slope) and route_duct_system (ОВ tee) — same reviewed-snapshot
    # discipline as create_pipe_system's own golden, one file per op so a
    # future diff isolates which op's emit drifted.
    "route_pipe_system_riser_branch": {
        "ir_version": "1.0",
        "intent": "стояк ВК с отводом и уклоном",
        "ops": [{"op": "route_pipe_system", "id": "SYS1",
                 "level": {"by": "element_id", "value": 42},
                 "nodes": [{"id": "N1", "xyz_mm": [0, 0, 15000]},
                           {"id": "N2", "xyz_mm": [0, 0, 0]},
                           {"id": "N3", "xyz_mm": [3000, 0, 0]}],
                 "segments": [{"from": "N1", "to": "N2", "diameter_mm": 100},
                              {"from": "N2", "to": "N3", "diameter_mm": 50,
                               "slope_min_pct": 2.0}]}],
    },
    "route_duct_system_tee": {
        "ir_version": "1.0",
        "intent": "тройник ОВ приточной сети",
        "ops": [{"op": "route_duct_system", "id": "SYS1",
                 "level": {"by": "element_id", "value": 42}, "diameter_mm": 250,
                 "nodes": [{"id": "T", "xyz_mm": [0, 0, 3000]},
                           {"id": "A", "xyz_mm": [3000, 0, 3000]},
                           {"id": "B", "xyz_mm": [-3000, 0, 3000]},
                           {"id": "C", "xyz_mm": [0, 3000, 3000]}],
                 "segments": [{"from": "T", "to": "A"}, {"from": "T", "to": "B"},
                              {"from": "T", "to": "C"}]}],
    },
    # wave/struct golden (2026-07-17): create_beam (gold-verified overload
    # against CreateBeamsColumnsBraces.cs) + create_foundation (both
    # varieties: isolated footing + slab, one file per variety so a future
    # diff isolates which branch drifted — same one-file-per-op discipline
    # as wave/mep's route_pipe_system/route_duct_system goldens).
    "struct_beam": {
        "ir_version": "1.0",
        "intent": "балка между колоннами на уровне",
        "ops": [{"op": "create_beam", "id": "B1",
                 "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
                 "level": {"by": "element_id", "value": 42},
                 "symbol": {"by": "name", "value": "Балка 200x400"}}],
    },
    "struct_foundation_isolated": {
        "ir_version": "1.0",
        "intent": "столбчатый фундамент под колонну",
        "ops": [{"op": "create_foundation", "id": "F1", "variety": "isolated",
                 "xy": [4000, 3000],
                 "level": {"by": "element_id", "value": 42},
                 "symbol": {"by": "name", "value": "Фундамент 1500x1500"}}],
    },
    # TWO openings, and this is NOT decoration (12.08.2026). `holes` is
    # the only PLURAL parameter of `create_foundation` (of kind
    # `pts_list`), and the emitter walks it with a hand-written
    # `for hi, hole in enumerate(holes)`. With ONE contour, this loop's
    # boundary is invisible by construction: `holes`, `holes[:1]`, and
    # `holes[-1:]` produce byte-for-byte the same thing, and a mutation
    # of "take only the first" survives the reference. Exactly the same
    # argument by which `move_elements` required THREE targets, not one.
    # Contours of DIFFERENT vertex counts (4 and 5 points) are
    # deliberate: two identical quadrilaterals would differ only in
    # coordinates, and a holes[0]/holes[1] swap would read worse to the
    # eye than 4 segments versus 5. This is also the first program in the
    # corpus where `check_holes_relation` reaches the PAIRWISE
    # non-intersection check — with a single contour, its inner loop
    # never runs at all.
    "struct_foundation_slab": {
        "ir_version": "1.0",
        "intent": "плитный фундамент с двумя проёмами",
        "ops": [{"op": "create_foundation", "id": "F1", "variety": "slab",
                 "outline": [[0, 0], [12000, 0], [12000, 8000], [0, 8000]],
                 "holes": [[[5000, 3000], [7000, 3000], [7000, 5000], [5000, 5000]],
                           [[9000, 1000], [11000, 1000], [11000, 2000],
                            [10000, 3000], [9000, 2000]]],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "name", "value": "Монолит 200"}}],
    },
    # The one above carries ONE hole, and one is exactly the cardinality that
    # pins nothing about a loop: `authoring.py:1332` walks the holes with
    # `for hi, hole in enumerate(holes)`, and a single-element list gives the
    # same bytes whether the loop runs once by accident or by construction.
    # That is why the unpinned-plural registry stopped counting "does the op
    # appear in a golden" and started asking for CARDINALITY >= 2 — the
    # difference between exercising a loop and merely entering it. Two holes,
    # deliberately unequal in shape and size, so the per-hole index `hi` has
    # to appear twice with different geometry behind it and a body that
    # silently emitted only the first would redden here while leaving the
    # one-hole golden above perfectly green.
    "struct_foundation_slab_two_holes": {
        "ir_version": "1.0",
        "intent": "плитный фундамент с двумя проёмами",
        "ops": [{"op": "create_foundation", "id": "F1", "variety": "slab",
                 "outline": [[0, 0], [12000, 0], [12000, 8000], [0, 8000]],
                 "holes": [
                     [[2000, 2000], [4000, 2000], [4000, 4000], [2000, 4000]],
                     [[7000, 3000], [10000, 3000], [10000, 6000],
                      [8500, 7000], [7000, 6000]],
                 ],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "name", "value": "Монолит 200"}}],
    },
    # wave/wall-foundation (2026-08-09): a strip foundation. ONE file for
    # BOTH host-selector branches, deliberately: ref and element_id are
    # different C# within the same program, and the diff must show them
    # side by side (the ref branch never introduces a wall variable at
    # all, the element_id branch introduces __hw_<s> and re-reads the
    # wall from the document). WF2 also goes by the document's default
    # type, so the reference also captures GetDefaultElementTypeId.
    "struct_wall_foundation": {
        "ir_version": "1.0",
        "intent": "лента под новой стеной и под существующей",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [9000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_wall_foundation", "id": "WF1",
             "wall": {"by": "ref", "value": "W1"},
             "type": {"by": "name", "value": "Ленточный 600x300"}},
            {"op": "create_wall_foundation", "id": "WF2",
             "wall": {"by": "element_id", "value": 8145901}},
        ],
    },
    # wave/arch (2026-07-29): a ceiling and both kinds of railing — one
    # file per branch, so a future diff shows exactly which one shifted
    # (the same "one file per branch" discipline as for the
    # isolated/slab foundation). WATCH OUT WHEN READING THE DIFF: for the
    # ceiling, the version axis is a REFUSAL, not an emission fork. This
    # reference was taken on the default version (2022+); on 2021 the
    # program does not exist at all, and the gate must see KIR-E003
    # there, not different C# (gate_runner.py, the list of expected
    # refusals).
    "arch_ceiling": {
        "ir_version": "1.0",
        "intent": "подвесной потолок в помещении с проёмом под шахту",
        "ops": [{"op": "create_ceiling", "id": "C1",
                 "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                 "holes": [[[2000, 1500], [3000, 1500],
                            [3000, 2500], [2000, 2500]]],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "name", "value": "Потолок подвесной 600x600"},
                 "height_offset_mm": 2700}],
    },
    # 09.08.2026: a SECOND shape input for the same op — a CONTOUR
    # sketch. A separate file rather than an extension of arch_ceiling,
    # under the same "one file per branch" discipline: the diff must show
    # exactly which branch shifted. What was taken is exactly what a
    # polyline cannot express — an arc edge (Arc.Create with three
    # literal points, all the trigonometry computed in Python) and an
    # opening AS A SKETCH (region.holes, not the flat `holes`: holding
    # both opening descriptions at once is forbidden, KIR-P007). The
    # version axis is the same as for arch_ceiling, and for the same
    # reason: on 2021 the ceiling has NO creation path at all, so the
    # reference was taken on the default version, and the gate must see
    # KIR-E003 there.
    "arch_ceiling_contour": {
        "ir_version": "1.0",
        "intent": "подвесной потолок с закруглённым краем и проёмом под шахту",
        "ops": [{"op": "create_ceiling", "id": "C1",
                 "contour": {
                     "outer": {"shape": "poly",
                               "points_mm": [[0, 0], [6000, 0],
                                             [6000, 4000], [0, 4000]],
                               "arcs": [{"edge": 1, "bulge": 0.4}]},
                     "holes": [{"shape": "rect", "origin": [2000, 1500],
                                "size_mm": [1000, 1000]}]},
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "name", "value": "Потолок подвесной 600x600"},
                 "height_offset_mm": 2700}],
    },
    # 09.08.2026: TWO shapes of a flight for one op, TWO files, and the
    # first of them is a RATCHET. `authoring_stairs_straight.golden.cs`
    # was captured from the EMITTER BEFORE the fix (`git stash` at
    # 15d5b206, the same snapshot, the same program): as long as it
    # matches, "a missing parameter moves nothing" is not a promise but a
    # byte comparison. Levels are addressed BY NAME on purpose: a stair
    # must be its own separate program (KIR-L002), and across the bundle
    # boundary, a name is the only form of address available to it.
    "authoring_stairs_straight": {
        "ir_version": "1.0",
        "intent": "прямой марш между этажами",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "p0_mm": [0, 0], "p1_mm": [5000, 0],
                 "base_level": {"by": "name", "value": "Этаж 1"},
                 "top_level": {"by": "name", "value": "Этаж 2"},
                 "width_mm": 1200}],
    },
    # A SECOND shape of the same op — a spiral flight. A separate file
    # under the same "one file per branch" discipline: the diff must
    # show exactly which branch shifted. What was taken is exactly what
    # a straight segment cannot express: 270° along an arc of 1500 mm
    # radius. The version axis for the spiral is THE SAME as for the
    # straight flight, and this was re-checked against the reference
    # assemblies and a live Roslyn on all six: `StairsRun.CreateSpiralRun`
    # is present and identical in 2021-2026.
    "authoring_stairs_spiral": {
        "ir_version": "1.0",
        "intent": "винтовая лестница вокруг шахты",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "spiral": {"center_mm": [3000.0, 3000.0],
                            "radius_mm": 1500.0,
                            "start_angle_deg": 0.0,
                            "included_angle_deg": 270.0,
                            "clockwise": False},
                 "base_level": {"by": "name", "value": "Этаж 1"},
                 "top_level": {"by": "name", "value": "Этаж 2"},
                 "width_mm": 1200}],
    },
    "arch_railing_path": {
        "ir_version": "1.0",
        "intent": "ограждение по краю балкона",
        "ops": [{"op": "create_railing", "id": "R1", "variety": "path",
                 "path": [[0, 0], [4000, 0], [4000, 2500]],
                 "level": {"by": "element_id", "value": 42},
                 "type": {"by": "name", "value": "Ограждение 900"}}],
    },
    "arch_railing_hosted": {
        "ir_version": "1.0",
        "intent": "ограждение по существующей лестнице",
        "ops": [{"op": "create_railing", "id": "R1", "variety": "hosted",
                 "host": {"by": "element_id", "value": 8888},
                 "position": "treads",
                 "type": {"by": "name", "value": "Ограждение 900"}}],
    },
    # wave/room (2026-08-03): a room separator. A П-shaped polyline —
    # three links — so the diff shows AT ONCE both the segment-by-segment
    # CurveArray assembly and the endpoint witness for each link. The op
    # has no version axis (6/6), so the reference was taken on the
    # default version and must match on all of them.
    "room_separator": {
        "ir_version": "1.0",
        "intent": "отделить кухню-нишу от гостиной без стены",
        "ops": [{"op": "create_room_separator", "id": "RS1",
                 "path": [[0, 0], [3200, 0], [3200, 2400], [0, 2400]],
                 "level": {"by": "name", "value": "Этаж 1"}}],
    },
    # wave/space (2026-08-10): an HVAC space. The program deliberately
    # holds ONE WALL and TWO spaces: the wall introduces the v0 rule
    # `doc.Regenerate()` before the space (NewSpace resolves the
    # enclosing region AT THE MOMENT OF CREATION), and the two ops show
    # in the diff the suffixing of the temporary witness — the only spot
    # where a name without a suffix would give CS0128. The op has no
    # version axis (three overloads, 6/6, byte-identical emission on
    # 2021-2026), so the reference was taken on the default version.
    # wave/placement (2026-08-11): both new kinds of placement side by
    # side, so a future diff immediately shows which of the two branches
    # shifted. Neither has a version axis (overloads 6/6, byte-identical
    # emission on 2021-2026), so the reference was taken on the default
    # version.
    # 11.08.2026: THE LAST "NOT REACHED" OF THE L6 ORACLE.
    #
    # `create_stairs_landing` was not built by a single program in
    # either corpus, and the three-state oracle honestly read this as
    # `not-reached` — that is, "no evidence", not "healthy". The probe
    # that declared the op hard to reach used MADE-UP field names
    # (`pts`, `elev_mm`) and got KIR-P003 on them; names taken from the
    # registry (`stairs`, `contour`, `elevation_mm`) compile right away.
    # The lesson is the same one as the whole marathon: ask the
    # registry, not memory.
    #
    # THE OP IS SOLO (`spec.SOLO_OPS`), so a program consisting of one
    # op is not a simplified fixture — it is the only admissible shape.
    #
    # THE CONTOUR IS SINGLE-LOOP, AND THIS IS A MEASUREMENT, NOT A
    # CHOICE: `contour` with `holes` is rejected by the typed KIR-E008 —
    # `StairsLanding.CreateSketchedLanding` accepts ONE loop. The
    # reference holds the shape the API actually executes.
    # 11.08.2026: A PROGRAM THAT CATCHES A HOLE IN THE REGENERATION RULE.
    #
    # Not a single reference in the corpus had built it, so the rule fix
    # went through WITHOUT shifting a byte in any of the 52 references —
    # meaning the corpus did not cover the hole at all. This program is
    # the only place where the difference shows: the room is placed into
    # a contour formed by a SEPARATOR, not a wall, and before the fix
    # there was no regeneration between them (measured by emission: the
    # separator at 2645, the room at 5534, no regeneration).
    #
    # This reference's diff must show `doc.Regenerate()` BETWEEN the two
    # ops. If it ever disappears, the rule is broken again.
    "room_separator_then_room": {
        "ir_version": "1.0",
        "intent": "комната в контуре из разделителей, без единой стены",
        "ops": [
            {"op": "create_room_separator", "id": "RS1",
             "path": [[0, 0], [4000, 0], [4000, 3000], [0, 3000], [0, 0]],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_room", "id": "R1", "xy": [2000, 1500],
             "level": {"by": "name", "value": "Этаж 1"},
             "name": "Кухня-ниша"},
        ],
    },
    "authoring_stairs_run": {
        "ir_version": "1.0",
        "intent": "второй марш на существующей лестнице",
        "ops": [{"op": "create_stairs_run", "id": "RN1",
                 "stairs": {"by": "element_id", "value": 8888},
                 "p0_mm": [0, 0], "p1_mm": [3200, 0],
                 "base_elevation_mm": 1800,
                 "justification": "left"}],
    },
    "authoring_stairs_landing": {
        "ir_version": "1.0",
        "intent": "промежуточная площадка на существующей лестнице",
        "ops": [{"op": "create_stairs_landing", "id": "LD1",
                 "stairs": {"by": "element_id", "value": 8888},
                 "contour": {"outer": {
                     "shape": "poly",
                     "points_mm": [[0, 0], [2400, 0],
                                   [2400, 1600], [0, 1600]]}},
                 "elevation_mm": 1800}],
    },
    "place_family_placement_kinds": {
        "ir_version": "1.0",
        "intent": "прибор на рабочей плоскости и стойка между уровнями",
        "ops": [
            {"op": "create_wall", "id": "PW", "p0_mm": [0, 0],
             "p1_mm": [8000, 0],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_level", "id": "PL", "elev_mm": 6000,
             "name": "КИР-Р"},
            {"op": "place_family", "id": "PP", "xyz": [4000, 0, 1200],
             "level": {"by": "name", "value": "Этаж 1"},
             "host": {"by": "ref", "value": "PW"},
             "ref_dir": [1, 0, 0]},
            {"op": "place_family", "id": "PT", "xyz": [2000, 2000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "top_level": {"by": "ref", "value": "PL"},
             "base_offset_mm": 100, "top_offset_mm": -250},
        ],
    },
    "space_mep": {
        "ir_version": "1.0",
        "intent": "два пространства ОВК в венткамере",
        "ops": [
            {"op": "create_wall", "id": "SW1", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_space", "id": "SPA", "xy": [2000, 2000],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_space", "id": "SPB", "xy": [6000, 2000],
             "level": {"by": "name", "value": "Этаж 1"}},
        ],
    },
    # wave hosted-flips-wall-vertical (audit F5): door with the full enforced
    # swing/mirror state + window with a facing flip — the MirrorElements
    # plane (normal along the host wall's direction), CanFlip* guards and the
    # three per-flag state witnesses in one reviewed file.
    # place_family along a CURVE (27.07). The occasion was measured on the
    # ЭОМ training model (SKLNK R2026): 79 instances — the entire
    # remaining gap of that model — have FamilyPlacementType.CurveBased
    # and a live LocationCurve, while LocationPoint does not exist for
    # them. The op is shared: the same CurveBased appears in structural
    # (КР, bracing), HVAC (ОВ, duct supports), and architectural (АР,
    # cornices, handrails) work.
    #
    # The program deliberately holds BOTH variants side by side: a
    # future diff will immediately show which of the two branches
    # shifted, while the point-based one is frozen by the parity corpus
    # and must not shift at all.
    "place_family_point_and_curve": {
        "ir_version": "1.0",
        "intent": "семейство в точку и семейство по кривой на хосте",
        "ops": [
            {"op": "place_family", "id": "P1", "xyz": [1000, 2000, 0],
             "level": {"by": "name", "value": "Этаж 1"}},
            # A host is mandatory for the curve-based variant, and this
            # is a MEASUREMENT: the level overload projects the curve
            # onto the level's plane and collapses a vertical segment
            # into a point. The order "host first, then what sits on it"
            # is the same topology as wall → door.
            {"op": "create_cable_tray", "id": "T1",
             "p0_mm": [155643, -5766, 565], "p1_mm": [155643, -5766, 4910],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "place_family", "id": "C1",
             "p0_mm": [155643, -5766, 565], "p1_mm": [155643, -5766, 4910],
             "host": {"by": "ref", "value": "T1"}},
        ],
    },
    "hosted_door_flips": {
        "ir_version": "1.0",
        "intent": "дверь с зеркалом и створкой",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [8000, 0], "level": {"by": "name", "value": "Этаж 1"},
             "height_mm": 3000},
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000,
             "mirrored": True, "hand_flipped": True, "facing_flipped": False},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 5000,
             "sill_mm": 900, "facing_flipped": True},
        ],
    },
    # wave hosted-flips-wall-vertical (audit F6): parapet wall with a base
    # offset (WALL_BASE_OFFSET.Set + ±1mm witness) and a wall attached to a
    # top level (WALL_HEIGHT_TYPE + WALL_TOP_OFFSET=0 + topology witness) —
    # one file per attribute so a future diff isolates which branch drifted.
    "wall_base_offset": {
        "ir_version": "1.0",
        "intent": "парапетная стена с офсетом основания",
        "ops": [{"op": "create_wall", "id": "WB", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 1200, "base_offset_mm": 900}],
    },
    # Wave A2: create_group WITH member-POSTs (the wave's one deliberate
    # emission change, pinned here) — each member's braced post block is
    # nested inside the group post (own C# scope per member).
    "native_group": {
        "ir_version": "1.0",
        "intent": "типовой этаж как нативная группа",
        "ops": [{"op": "create_group", "id": "GRP1", "name": "Типовой этаж",
                 "members": [
                     {"op": "create_wall", "id": "W1",
                      "p0_mm": [30000, 23000], "p1_mm": [36000, 23000],
                      "level": {"__grounded__": {"id": 42, "name": None,
                                                 "via": "element_id"}},
                      "height_mm": 3000.0,
                      "type": {"__grounded__": {"id": None, "name": None,
                                                "via": "doc_default",
                                                "in_emit": "__doc_default__"}}},
                     {"op": "create_wall", "id": "W2",
                      "p0_mm": [36000, 23000], "p1_mm": [36000, 27000],
                      "level": {"__grounded__": {"id": 42, "name": None,
                                                 "via": "element_id"}},
                      "height_mm": 3000.0,
                      "type": {"__grounded__": {"id": None, "name": None,
                                                "via": "doc_default",
                                                "in_emit": "__doc_default__"}}},
                 ],
                 "placements": [[0, 0, 6600], [0, 0, 13200]]}],
    },
    # 🔴 A CORPUS HOLE FOUND ON 19.08.2026, AND IT IS A FINDING OF THE SAME
    # KIND THIS VERY FILE WARNS ABOUT. The corpus had EXACTLY ONE program
    # with `create_column` (`full_house_v1`), and it has no `top_level`
    # at all. So the entire top-attachment branch — writing
    # FAMILY_TOP_LEVEL_PARAM, writing the top offset, the attachment
    # witness — stood in not a single reference, while
    # `FAMILY_TOP_LEVEL_PARAM` appeared in the references exactly once
    # and belonged to `place_family`. This is, word for word, "the
    # golden over a VERTICAL column read green while the tilted branch
    # stayed dark", repeated one level down: a green reference over a
    # column WITHOUT a top attachment while the branch WITH an
    # attachment stayed dark. And it was precisely in that dark branch
    # that 420 columns of the live benchmark came out at 2500 mm instead
    # of 3600–4500.
    "struct_column_top_constrained": {
        "ir_version": "1.0",
        "intent": "колонна между двумя уровнями, верх привязан, оба смещения",
        "ops": [{"op": "create_column", "id": "CT", "xy": [3000, 1500],
                 "category": "structural",
                 "level": {"by": "name", "value": "Этаж 1"},
                 "top_level": {"by": "name", "value": "Этаж 2"},
                 "base_offset_mm": 150, "top_offset_mm": -250}],
    },
    "wall_top_attached": {
        "ir_version": "1.0",
        "intent": "стена, приаттаченная к верхнему уровню",
        "ops": [{"op": "create_wall", "id": "WT", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 3000,
                 "top_level": {"by": "name", "value": "Этаж 2"}}],
    },
    # wave/opening (2026-08-03): an opening AS A SEPARATE ELEMENT — one
    # file per branch, the same discipline as for the isolated/slab
    # foundation and the path/hosted railing. The op has NO version axis
    # (all four NewOpening overloads live 6/6), so there is no need to
    # register expected refusals for them in gate_runner — unlike the
    # ceiling.
    #
    # Both values of `cut` stand as separate references on purpose: for
    # the vertical cut the witness checks EQUALITY of the bounding
    # boxes, for the perpendicular one it checks CONTAINMENT (on a slope
    # the opening's plan is legitimately wider than the contour) — that
    # is, these are two different emissions, and a future diff must show
    # exactly which one shifted.
    "opening_wall_rect": {
        "ir_version": "1.0",
        "intent": "прямоугольный проём в существующей стене",
        "ops": [{"op": "create_opening", "id": "O1", "variety": "wall_rect",
                 "host": {"by": "element_id", "value": 8145901},
                 "p0_mm": [1000.0, 0.0, 900.0],
                 "p1_mm": [2500.0, 0.0, 2400.0]}],
    },
    # ── wave/site (2026-08-09): pad and terrain ──────────────────────────
    # ONE FILE PER BRANCH, under the same discipline as the architecture
    # wave: the diff must show exactly which branch shifted.
    "site_topography_surface": {
        "ir_version": "1.0",
        "intent": "рельеф участка по съёмочным точкам",
        "ops": [{"op": "create_topography", "id": "T1", "variety": "surface",
                 "points_mm": [[0, 0, 0], [24000, 0, 800],
                               [24000, 18000, 1500], [0, 18000, 400],
                               [12000, 9000, 1100]]}],
    },
    # The reference was taken on the default version (2026), because the
    # Toposolid class does not exist before 2024: on 2021-2023 this is a
    # typed KIR-E003 refusal, meaning there is no emission there at all,
    # not a different emission.
    "site_topography_toposolid": {
        "ir_version": "1.0",
        "intent": "толща рельефа с привязкой к уровню",
        "ops": [{"op": "create_topography", "id": "T1", "variety": "toposolid",
                 "points_mm": [[0, 0, 0], [24000, 0, 800],
                               [24000, 18000, 1500], [0, 18000, 400],
                               [12000, 9000, 1100]],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "name", "value": "Толща рельефа 300"}}],
    },
    # The type is deliberately NOT set: this is the document's default
    # branch (ElementTypeGroup.BuildingPadType, 6/6 — measured against
    # our own API base), and the reference must show it.
    "site_building_pad": {
        "ir_version": "1.0",
        "intent": "площадка под здание с проёмом под приямок",
        "ops": [{"op": "create_building_pad", "id": "P1",
                 "contour": {"outer": {"shape": "rect", "origin": [2000, 2000],
                                       "size_mm": [12000, 9000]},
                             "holes": [{"shape": "rect",
                                        "origin": [5000, 4000],
                                        "size_mm": [1500, 1500]}]},
                 "level": {"by": "name", "value": "Этаж 1"}}],
    },
    # A sub-region with a NAMED host and an arc edge: the bounding box
    # is checked against the lowered-edges (the arc's cardinal extrema),
    # and a straight polyline never opens this branch.
    "site_subregion_hosted": {
        "ir_version": "1.0",
        "intent": "подобласть площадки под газон, с закруглённым краем",
        "ops": [{"op": "create_site_subregion", "id": "R1",
                 "contour": {"outer": {
                     "shape": "poly",
                     "points_mm": [[1000, 1000], [9000, 1000],
                                   [9000, 7000], [1000, 7000]],
                     "arcs": [{"edge": 1, "bulge": 0.35}]}},
                 "host": {"by": "element_id", "value": 7777}}],
    },
    # wave/sweep (2026-08-09). ONE FILE PER BRANCH, and there are
    # exactly four branches here, because it is the emission that
    # diverges, not the formatting: for the wall profile — orientation
    # (the only argument affecting the `WallSweepInfo` constructor) and
    # the shape of the host selector (`element_id` versus `ref`, i.e.
    # `doc.GetElement` versus a neighboring op's variable); for the edge
    # one — the side (`GetTopFaces` versus `GetBottomFaces`, different
    # calls) and the same host fork.
    "sweep_wall_horizontal": {
        "ir_version": "1.0",
        "intent": "карниз по существующей стене",
        "ops": [{"op": "create_wall_sweep", "id": "S1",
                 "host": {"by": "element_id", "value": 7777},
                 "orientation": "horizontal",
                 "type": {"by": "name", "value": "Карниз 200x100"}}],
    },
    # The host is a wall from THIS SAME program, plus vertical
    # orientation: both branches at once, because they are independent
    # and a second pair of references would add nothing.
    "sweep_wall_vertical_ref": {
        "ir_version": "1.0",
        "intent": "руст по только что построенной стене",
        "ops": [
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [8000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "ЖБ 200"}},
            {"op": "create_wall_sweep", "id": "S1",
             "host": {"by": "ref", "value": "W1"},
             "orientation": "vertical",
             "type": {"by": "name", "value": "Карниз 200x100"}},
        ],
    },
    # The type is deliberately NOT set: this is the "sole item in the
    # pool" branch for `ground`. There is no DOCUMENT default branch
    # here, and there should not be one — `ElementTypeGroup.EdgeSlabType`
    # exists 6/6, but is not used, for the same reason as with the
    # ceiling and the pad (see sweep_emit).
    "sweep_slab_edge_top": {
        "ir_version": "1.0",
        "intent": "капельник по верхнему краю плиты",
        "ops": [{"op": "create_slab_edge", "id": "E1",
                 "host": {"by": "element_id", "value": 7777},
                 "side": "top"}],
    },
    "sweep_slab_edge_bottom_ref": {
        "ir_version": "1.0",
        "intent": "капельник по нижнему краю только что построенного перекрытия",
        "ops": [
            {"op": "create_floor", "id": "F1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "Монолит 200"}},
            {"op": "create_slab_edge", "id": "E1",
             "host": {"by": "ref", "value": "F1"},
             "side": "bottom",
             "type": {"by": "name", "value": "Капельник 100x50"}},
        ],
    },
    "opening_host_face_vertical": {
        "ir_version": "1.0",
        "intent": "проём в существующем перекрытии, вертикальный рез",
        "ops": [{"op": "create_opening", "id": "O1", "variety": "host_face",
                 "host": {"by": "element_id", "value": 8145901},
                 "outline": [[1000, 1000], [3000, 1000],
                             [3000, 3000], [1000, 3000]],
                 "cut": "vertical"}],
    },
    "opening_host_face_perpendicular": {
        "ir_version": "1.0",
        "intent": "проём в скатной кровле, рез перпендикулярно грани",
        "ops": [{"op": "create_opening", "id": "O1", "variety": "host_face",
                 "host": {"by": "element_id", "value": 8145901},
                 "outline": [[5000, 1000], [7000, 1000],
                             [7000, 3000], [5000, 3000]],
                 "cut": "perpendicular"}],
    },
    # 09.08.2026: a SECOND shape input for the same kind — a CONTOUR
    # sketch. Again TWO files for two values of `cut`, under the same
    # discipline as the straight branch above: for the vertical cut the
    # witness checks a STRIP (vertices below, bounding box with arcs
    # above), for the perpendicular one only the lower boundary — and
    # these are two different emissions. The sketch has NO version axis,
    # and this was re-verified against the reference assemblies:
    # NewOpening(Element, CurveArray, bool), Arc.Create, Line.CreateBound,
    # CurveArray.Append, Curve.Evaluate, Curve.GetEndPoint,
    # Curve.IsBound — all 6/6, so there is no need to register expected
    # refusals in gate_runner here (unlike the ceiling).
    #
    # What was taken is exactly what a polyline cannot express: an arc
    # edge (Arc.Create with THREE literal points — all the trigonometry
    # computed in Python) and a rotated rectangle. The arc file
    # additionally shows a SAMPLING along the boundary (`Curve.Evaluate`),
    # which the straight profiles do not have at all.
    "opening_contour_vertical": {
        "ir_version": "1.0",
        "intent": "проём с закруглённой стороной в перекрытии, "
                  "вертикальный рез",
        "ops": [{"op": "create_opening", "id": "O1", "variety": "host_face",
                 "host": {"by": "element_id", "value": 8145901},
                 "contour": {"outer": {
                     "shape": "poly",
                     "points_mm": [[1000, 1000], [3000, 1000],
                                   [3000, 3000], [1000, 3000]],
                     "arcs": [{"edge": 1, "bulge": 0.4}]}},
                 "cut": "vertical"}],
    },
    "opening_contour_perpendicular": {
        "ir_version": "1.0",
        "intent": "повёрнутый прямоугольный проём в скатной кровле, "
                  "рез перпендикулярно грани",
        "ops": [{"op": "create_opening", "id": "O1", "variety": "host_face",
                 "host": {"by": "element_id", "value": 8145901},
                 "contour": {"outer": {"shape": "rect",
                                       "origin": [5000, 1000],
                                       "size_mm": [2000, 2000],
                                       "rotation_deg": 30.0}},
                 "cut": "perpendicular"}],
    },
    # wave/mep-electrical (2026-08-09). TWO references, not one: for a
    # tray with knockouts the witness reads the `LocationCurve` axis
    # (plus the knockout bit), for flexible ones it reads the whole
    # `Points` array. These are two different emissions, and a future
    # diff must show exactly which one shifted — the same argument by
    # which the opening has two files for two values of `cut`.
    "mep_conduit_and_placeholders": {
        "ir_version": "1.0",
        "intent": "короб ЭОМ и две заготовки трассы",
        "ops": [
            {"op": "create_conduit", "id": "CD1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000],
             "level": {"by": "name", "value": "Этаж 1"},
             "conduit_type": {"by": "name",
                              "value": "Короб жёсткий металлический"}},
            {"op": "create_pipe_placeholder", "id": "PP1",
             "p0_mm": [0, 1000, 2800], "p1_mm": [6000, 1000, 2800],
             "level": {"by": "element_id", "value": 42},
             "system_type": {"by": "name", "value": "ХВС"},
             "pipe_type": {"by": "name", "value": "Стандарт"}},
            {"op": "create_duct_placeholder", "id": "DP1",
             "p0_mm": [0, 2000, 3200], "p1_mm": [6000, 2000, 3200],
             "level": {"by": "element_id", "value": 42}},
        ],
    },
    "mep_flex_runs": {
        "ir_version": "1.0",
        "intent": "гибкая подводка воздуховода и гибкая труба",
        # Three-point and two-point side by side: for the first the
        # witness walks the midpoint too, for the second only the
        # endpoints, and the difference is visible in the file.
        "ops": [
            {"op": "create_flex_duct", "id": "FD1",
             "path": [[0, 3000, 3000], [1500, 3000, 2800],
                      [3000, 3200, 2600]],
             "level": {"by": "element_id", "value": 42},
             "flex_duct_type": {"by": "name",
                                "value": "Гибкий воздуховод круглый"}},
            {"op": "create_flex_pipe", "id": "FP1",
             "path": [[0, 4000, 3000], [1500, 4000, 2700]],
             "level": {"by": "name", "value": "Этаж 1"}},
        ],
    },
    # wave/analysis (2026-08-09). TWO files, not one, and their versions
    # DIFFER — that is the main fact of this wave, pinned in the
    # reference: a free load lives only on 2021-2023, while a path of
    # travel lives on all six. One file for both emissions would have
    # hidden exactly this boundary.
    #
    # Inside the load program, both forms of the load-case selector (by
    # name and by id) deliberately stand side by side, a load with an
    # explicit type next to one without it, and an inclined line load
    # next to a horizontal one: for the inclined one the work plane is
    # VERTICAL, and its normal is computed in Python — a future diff must
    # show which of the two branches shifted.
    "analysis_loads": {
        "__ver__": "2023",
        "ir_version": "1.0",
        "intent": "точечная, две линейных и площадная нагрузка",
        "ops": [
            {"op": "create_point_load", "id": "PL1", "xyz": [1000, 2000, 3000],
             "fz_n": -10000.0, "mx_nm": 250.0,
             "load_case": {"by": "name", "value": "ДЛ1 Собственный вес"}},
            {"op": "create_line_load", "id": "LL1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000], "fz_n_per_m": -5000.0,
             "fx_n_per_m": 120.0,
             "load_case": {"by": "element_id", "value": 1500},
             "load_type": {"by": "name", "value": "Линейная нагрузка 1"}},
            {"op": "create_line_load", "id": "LL2", "p0_mm": [0, 500, 3000],
             "p1_mm": [6000, 2500, 4200], "fz_n_per_m": -2500.0,
             "load_case": {"by": "element_id", "value": 1501}},
            {"op": "create_area_load", "id": "AL1",
             "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
             "elev_mm": 3000, "fz_n_per_m2": -3000.0,
             "load_case": {"by": "name", "value": "СН1 Снег"}},
        ],
    },
    "analysis_path_of_travel": {
        "ir_version": "1.0",
        "intent": "путь эвакуации от точки до выхода",
        "ops": [
            {"op": "create_path_of_travel", "id": "PT1",
             "in_view": {"by": "element_id", "value": 900},
             "p0_mm": [0, 0], "p1_mm": [12000, 5000]},
        ],
    },
    # wave/datums (09.08.2026). THREE separate golden programs, not one:
    # each covers a branch the others do not light up, and merging them
    # into one file would hide exactly what golden exists for — the
    # byte-level difference between branches.
    "datums_multi_segment_grid": {
        "ir_version": "1.0",
        "intent": "цепь осей ломаной",
        "ops": [
            {"op": "create_multi_segment_grid", "id": "MG1",
             "path": [[0, 0], [8000, 0], [8000, 6000], [14000, 6000]],
             "level": {"by": "name", "value": "Этаж 1"}},
        ],
    },
    # Two roofs side by side: for the first the type is taken from the
    # DOCUMENT (the field is omitted), for the second an id is pinned,
    # and the extrusion travel goes NEGATIVE on one side — the sign is
    # the only thing decided at runtime by Revit's normal.
    "datums_extrusion_roof": {
        "ir_version": "1.0",
        "intent": "выдавленные кровли: щипец и плоский навес",
        "ops": [
            {"op": "create_extrusion_roof", "id": "XR1",
             "p0_mm": [0, 0], "p1_mm": [0, 8000],
             "profile_mm": [[0, 3000], [4000, 5000], [8000, 3000]],
             "level": {"by": "name", "value": "Этаж 1"},
             "start_mm": 0, "end_mm": 12000},
            {"op": "create_extrusion_roof", "id": "XR2",
             "p0_mm": [1000, 2000], "p1_mm": [9000, 2000],
             "profile_mm": [[0, 4000], [8000, 4000]],
             "level": {"by": "element_id", "value": 43},
             "start_mm": -3000, "end_mm": 9000},
        ],
    },
    "datums_multistory_stairs": {
        "ir_version": "1.0",
        "intent": "марш, размноженный на два этажа",
        # The levels are named with DIFFERENT selector forms on purpose:
        # the list must resolve element-by-element under the same rule
        # as a single one.
        "ops": [
            {"op": "create_multistory_stairs", "id": "MS1",
             "stairs": {"by": "element_id", "value": 8145901},
             "levels": [{"by": "name", "value": "Этаж 1"},
                        {"by": "element_id", "value": 43}]},
        ],
    },
    # wave/solid: a parametric solid. BOTH ops in ONE file and with
    # DIFFERENT branches, deliberately — this way the reviewer sees side
    # by side what would otherwise have to be compared across two
    # snapshots:
    #   * the extrusion CARRIES an opening, an arc, and a base elevation,
    #     meaning all three optional emission branches at once (the
    #     contour transform is only printed here — a bare solid has none
    #     of it at all);
    #   * the revolve runs an INCOMPLETE turn, so it has end faces, and
    #     right next to it you can see how the end-face witness differs
    #     from the bounding-box one.
    # No selector is grounded (DirectShape has no type), so the file
    # compiles WITHOUT a snapshot — the only authored golden with this
    # property, and that is a fact about DirectShape, not about the
    # fixture.
    "solid_extrusion_and_revolve": {
        "ir_version": "1.0",
        "intent": "параметрическое тело: выдавливание с проёмом и вращение",
        "ops": [
            {"op": "create_solid_extrusion", "id": "SE1",
             "profile": {
                 "outer": {"shape": "poly",
                           "points_mm": [[0, 0], [6000, 0], [6000, 4000],
                                         [0, 4000]],
                           "arcs": [{"edge": 1, "bulge": 0.4}]},
                 "holes": [{"shape": "rect", "origin": [1000, 1000],
                            "size_mm": [1200, 1200]}]},
             "height_mm": 1800, "base_z_mm": 3300,
             "category": "mass", "name": "плита с проёмом"},
            {"op": "create_solid_revolve", "id": "SR1",
             "profile": {"outer": {"shape": "rect", "origin": [1000, 0],
                                   "size_mm": [800, 2400]}},
             "axis_xy_mm": [12000, 4000], "sweep_deg": 270,
             "category": "generic_model", "name": "сектор кольца"},
        ],
    },
    # ── wave/detail (2026-08-09): a fill on a view ───────────────────────
    # TWO FILES FOR TWO TYPE BRANCHES, under the same discipline as the
    # pad and the opening: the diff must show exactly which branch
    # shifted.
    #
    # The first — the type is NAMED, a contour with a hole and an arc.
    # The arc here is not decoration: it opens the only branch where the
    # witness must check the edge's MIDPOINT (an arc and its chord are
    # indistinguishable by their endpoints alone), and the hole opens
    # the branch with more than one loop.
    "detail_filled_region_named_type": {
        "ir_version": "1.0",
        "intent": "заливка бетона на разрезе, с проёмом и скруглённым краем",
        "ops": [{"op": "create_filled_region", "id": "F1",
                 "in_view": {"by": "element_id", "value": 900},
                 "contour": {"outer": {
                     "shape": "poly",
                     "points_mm": [[0, 0], [4000, 0], [4000, 2500], [0, 2500]],
                     "arcs": [{"edge": 1, "bulge": 0.4}]},
                     "holes": [{"shape": "rect", "origin": [1000, 800],
                                "size_mm": [800, 600]}]},
                 "type": {"by": "name", "value": "Бетон"}}],
    },
    # The second — the type is NOT set: the document-default branch
    # (ElementTypeGroup.FilledRegionType, 6/6 — measured by compilation),
    # and the reference must show it separately from the named one.
    "detail_filled_region_doc_default": {
        "ir_version": "1.0",
        "intent": "прямоугольная заливка типом документа по умолчанию",
        "ops": [{"op": "create_filled_region", "id": "F1",
                 "in_view": {"by": "element_id", "value": 900},
                 "contour": {"outer": {"shape": "rect", "origin": [500, 500],
                                       "size_mm": [3000, 1200]}}}],
    },
    # ── O2: lifted from gate_runner so ONE source serves the gate and
    # the golden. Each closes at least one write op that had no compared
    # golden at all. The gate now receives them through its seed.
    "auth_annotation": {'ir_version': '1.0',
     'intent': 'аннотации',
     'ops': [{'op': 'create_wall',
              'id': 'W1',
              'p0_mm': [0, 0],
              'p1_mm': [6000, 0],
              'level': {'by': 'element_id', 'value': 42},
              'height_mm': 3000},
             {'op': 'create_dimension',
              'id': 'DIM1',
              'in_view': {'by': 'element_id', 'value': 900},
              'refs': [{'by': 'ref', 'value': 'W1'},
                       {'by': 'element_id', 'value': 12345}],
              'line_at': [3000, 500]},
             {'op': 'create_angular_dimension',
              'id': 'ANG1',
              'in_view': {'by': 'element_id', 'value': 900},
              'refs': [{'by': 'ref', 'value': 'W1'},
                       {'by': 'element_id', 'value': 12345}],
              'at': [1500, 1500]},
             {'op': 'create_tag',
              'id': 'TAG1',
              'in_view': {'by': 'element_id', 'value': 900},
              'target': {'by': 'ref', 'value': 'W1'},
              'at': [3000, 800]},
             {'op': 'create_text',
              'id': 'TXT1',
              'in_view': {'by': 'element_id', 'value': 900},
              'at': [1000, 1000],
              'content': 'Проверка'}]},
    "auth_contour_l": {'ir_version': '1.0',
     'intent': 'Г-плита по контуру с проёмом',
     'ops': [{'op': 'create_floor_by_contour',
              'id': 'F1',
              'contour': {'outer': {'shape': 'l',
                                    'origin': [0, 0],
                                    'size_mm': [16000, 10000],
                                    'cut_mm': [6000, 4000]},
                          'holes': [{'shape': 'rect',
                                     'origin': [1000, 1000],
                                     'size_mm': [3000, 6000]}]},
              'level': {'by': 'name', 'value': 'Этаж 1'}}]},
    "auth_curtain_cell_named_type": {'ir_version': '1.0',
     'intent': 'витраж: стеклопакет в единственную ячейку',
     'ops': [{'op': 'create_wall',
              'id': 'WC',
              'p0_mm': [0, 0],
              'p1_mm': [6000, 0],
              'level': {'by': 'element_id', 'value': 42},
              'height_mm': 3000},
             {'op': 'set_curtain_panel',
              'id': 'CP1',
              'host': {'by': 'ref', 'value': 'WC'},
              'u': 0,
              'v': 0,
              'panel_type': {'by': 'name', 'value': 'Стеклопакет 30мм'}}]},
    "auth_curtain_grid_lines": {'ir_version': '1.0',
     'intent': 'витраж: раскладка сетки — своя линия на каждый шаг',
     'ops': [{'op': 'create_wall',
              'id': 'WG',
              'p0_mm': [0, 0],
              'p1_mm': [6000, 0],
              'level': {'by': 'element_id', 'value': 42},
              'height_mm': 3000},
             {'op': 'create_curtain_grid_line',
              'id': 'GL1',
              'host': {'by': 'ref', 'value': 'WG'},
              'direction': 'u',
              'position_mm': [2000.0, 0.0, 1500.0]},
             {'op': 'create_curtain_grid_line',
              'id': 'GL2',
              'host': {'by': 'ref', 'value': 'WG'},
              'direction': 'v',
              'position_mm': [3000.0, 0.0, 2100.0]},
             {'op': 'create_curtain_grid_line',
              'id': 'GL3',
              'host': {'by': 'element_id', 'value': 8145901},
              'direction': 'u',
              'position_mm': [4000.0, 120.0, 900.0]}]},
    # 🔴 THE ONLY BOOLEAN ENTRY IN THE CORPUS, AND IT IS DELIBERATELY THE
    # SIMPLEST ONE. The golden pins the BYTES of the emission, so the
    # program must be the smallest one that covers the op: one part, one
    # operation, a rectangular profile with no arcs. The Python loop,
    # the five perforations, and the remaining three operations live in
    # the live demo (scratchpad/boolean_demo.py) — there they are READ
    # BY A HUMAN, here they would only make more expensive a diff a
    # human must review by eye.
    #
    # WHAT IS PINNED: the emission of a boolean difference via
    # BooleanOperationsUtils.ExecuteBooleanOperation, four volumes and
    # four areas for the witness, an auxiliary solid built by a
    # DIFFERENT call (see ops_boolean: a witness equal to itself cannot
    # fail). WHAT IS NOT PINNED: union and intersect, parts other than
    # the sphere, several parts at once, an arc profile.
    "auth_solid_boolean_difference": {
        "ir_version": "1.0",
        "intent": "куб минус сфера",
        "ops": [{"op": "create_solid_boolean", "id": "D1",
                 "operation": "difference",
                 "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                       "size_mm": [4000, 4000]}},
                 "height_mm": 4000.0,
                 "parts": [{"shape": "sphere",
                            "center_mm": [2000, 2000, 4000],
                            "radius_mm": 2400.0}],
                 "category": "generic_model", "name": "куб минус сфера"}],
    },
    # A FOURTH KIND OF PART (21.08.2026): A PRISM OVER A CONTOUR, and
    # exactly the geometry it was set up for — a VOID in a family.
    # Pinned: a prism-part on a HORIZONTAL elevation and a prism-part on
    # a VERTICAL face (kind `plane`), two contour rings with different
    # names `__ol_*_p0` and `__ol_*_p1`, the part's extrusion direction
    # ALONG THE NORMAL, the base on the plane. WHAT IS NOT PINNED: union
    # and intersect with the prism, an arc contour for the part, an
    # opening (`holes`) inside the part.
    "auth_solid_boolean_prism_voids": {
        "ir_version": "1.0",
        "intent": "плита минус два выреза: один по отметке, один по грани",
        "ops": [{"op": "create_solid_boolean", "id": "D1",
                 "operation": "difference",
                 "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                       "size_mm": [4000, 4000]}},
                 "height_mm": 4000.0,
                 "parts": [
                     {"shape": "prism",
                      "profile": {"outer": {"shape": "poly",
                                            "points_mm": [[1000, 1000],
                                                          [3000, 1000],
                                                          [3000, 3000],
                                                          [1000, 3000]]}},
                      "height_mm": 2000.0, "base_z_mm": 500.0},
                     {"shape": "prism",
                      "profile": {"outer": {"shape": "rect",
                                            "origin": [0, 0],
                                            "size_mm": [1000, 1000]}},
                      "height_mm": 1500.0,
                      "plane": {"origin_mm": [1500.0, 1000.0, 500.0],
                                "normal": [0.0, 1.0, 0.0],
                                "x_dir": [1.0, 0.0, 0.0]}}],
                 "category": "generic_model",
                 "name": "плита минус два выреза"}],
    },
    "auth_directshape_tower": {'ir_version': '1.0',
     'intent': 'витая башня мешем',
     'ops': [{'op': 'create_directshape',
              'id': 'D1',
              'mesh': {'vertices_mm': [[6000.0, 0.0, 0.0],
                                       [5543.277195067721,
                                        2296.1005941905387,
                                        0.0],
                                       [4242.640687119286,
                                        4242.640687119285,
                                        0.0],
                                       [2296.100594190539,
                                        5543.277195067721,
                                        0.0],
                                       [3.6739403974420595e-13,
                                        6000.0,
                                        0.0],
                                       [-2296.1005941905382,
                                        5543.277195067721,
                                        0.0],
                                       [-4242.640687119285,
                                        4242.640687119286,
                                        0.0],
                                       [-5543.277195067721,
                                        2296.100594190539,
                                        0.0],
                                       [-6000.0,
                                        7.347880794884119e-13,
                                        0.0],
                                       [-5543.277195067722,
                                        -2296.1005941905382,
                                        0.0],
                                       [-4242.640687119286,
                                        -4242.640687119285,
                                        0.0],
                                       [-2296.100594190542,
                                        -5543.277195067719,
                                        0.0],
                                       [-1.1021821192326177e-12,
                                        -6000.0,
                                        0.0],
                                       [2296.10059419054,
                                        -5543.27719506772,
                                        0.0],
                                       [4242.640687119284,
                                        -4242.640687119286,
                                        0.0],
                                       [5543.277195067719,
                                        -2296.1005941905423,
                                        0.0],
                                       [5672.014434392153,
                                        1171.1767730897197,
                                        3000.0],
                                       [4792.068096611249,
                                        3252.6122017877296,
                                        3000.0],
                                       [3182.572831326752,
                                        4838.86690776659,
                                        3000.0],
                                       [1088.5597025673153,
                                        5688.447991475736,
                                        3000.0],
                                       [-1171.1767730897188,
                                        5672.014434392153,
                                        3000.0],
                                       [-3252.612201787729,
                                        4792.0680966112495,
                                        3000.0],
                                       [-4838.866907766589,
                                        3182.5728313267527,
                                        3000.0],
                                       [-5688.447991475736,
                                        1088.5597025673158,
                                        3000.0],
                                       [-5672.014434392153,
                                        -1171.1767730897184,
                                        3000.0],
                                       [-4792.0680966112495,
                                        -3252.612201787729,
                                        3000.0],
                                       [-3182.572831326751,
                                        -4838.866907766591,
                                        3000.0],
                                       [-1088.5597025673162,
                                        -5688.447991475736,
                                        3000.0],
                                       [1171.1767730897207,
                                        -5672.014434392153,
                                        3000.0],
                                       [3252.612201787733,
                                        -4792.068096611247,
                                        3000.0],
                                       [4838.866907766591,
                                        -3182.572831326751,
                                        3000.0],
                                       [5688.447991475736,
                                        -1088.5597025673164,
                                        3000.0],
                                       [5126.706596748196,
                                        2211.445360385292,
                                        6000.0],
                                       [3890.175792926157,
                                        4005.014782899366,
                                        6000.0],
                                       [2061.400989162488,
                                        5188.857010266425,
                                        6000.0],
                                       [-81.2034285546698,
                                        5582.74279492635,
                                        6000.0],
                                       [-2211.445360385292,
                                        5126.706596748196,
                                        6000.0],
                                       [-4005.0147828993645,
                                        3890.1757929261576,
                                        6000.0],
                                       [-5188.857010266424,
                                        2061.4009891624896,
                                        6000.0],
                                       [-5582.74279492635,
                                        -81.20342855466822,
                                        6000.0],
                                       [-5126.706596748197,
                                        -2211.4453603852908,
                                        6000.0],
                                       [-3890.1757929261585,
                                        -4005.0147828993645,
                                        6000.0],
                                       [-2061.4009891624896,
                                        -5188.857010266424,
                                        6000.0],
                                       [81.2034285546654,
                                        -5582.74279492635,
                                        6000.0],
                                       [2211.4453603852903,
                                        -5126.706596748197,
                                        6000.0],
                                       [4005.014782899366,
                                        -3890.1757929261566,
                                        6000.0],
                                       [5188.857010266424,
                                        -2061.40098916249,
                                        6000.0],
                                       [5582.74279492635,
                                        81.20342855466507,
                                        6000.0],
                                       [4402.942238053331,
                                        3082.9733453868726,
                                        9000.0],
                                       [2887.9853948641785,
                                        4533.22902124426,
                                        9000.0],
                                       [933.358954959751,
                                        5293.341672440618,
                                        9000.0],
                                       [-1163.3629249173025,
                                        5247.591038269642,
                                        9000.0],
                                       [-3082.973345386873,
                                        4402.942238053331,
                                        9000.0],
                                       [-4533.2290212442595,
                                        2887.9853948641794,
                                        9000.0],
                                       [-5293.341672440618,
                                        933.3589549597502,
                                        9000.0],
                                       [-5247.591038269642,
                                        -1163.362924917301,
                                        9000.0],
                                       [-4402.942238053331,
                                        -3082.973345386873,
                                        9000.0],
                                       [-2887.9853948641803,
                                        -4533.2290212442595,
                                        9000.0],
                                       [-933.3589549597506,
                                        -5293.341672440618,
                                        9000.0],
                                       [1163.3629249173007,
                                        -5247.591038269642,
                                        9000.0],
                                       [3082.9733453868726,
                                        -4402.942238053331,
                                        9000.0],
                                       [4533.229021244262,
                                        -2887.985394864176,
                                        9000.0],
                                       [5293.341672440618,
                                        -933.3589549597508,
                                        9000.0],
                                       [5247.591038269642,
                                        1163.3629249173005,
                                        9000.0],
                                       [3545.5817956551236,
                                        3758.097148127418,
                                        12000.0],
                                       [1837.5289360435283,
                                        4828.864447636441,
                                        12000.0],
                                       [-150.27104683940922,
                                        5164.480908758037,
                                        12000.0],
                                       [-2115.1936250514786,
                                        4713.85196765724,
                                        12000.0],
                                       [-3758.0971481274187,
                                        3545.5817956551236,
                                        12000.0],
                                       [-4828.864447636441,
                                        1837.5289360435286,
                                        12000.0],
                                       [-5164.480908758037,
                                        -150.2710468394089,
                                        12000.0],
                                       [-4713.85196765724,
                                        -2115.193625051478,
                                        12000.0],
                                       [-3545.5817956551236,
                                        -3758.097148127418,
                                        12000.0],
                                       [-1837.5289360435288,
                                        -4828.864447636441,
                                        12000.0],
                                       [150.2710468394063,
                                        -5164.480908758037,
                                        12000.0],
                                       [2115.1936250514736,
                                        -4713.851967657242,
                                        12000.0],
                                       [3758.0971481274164,
                                        -3545.5817956551255,
                                        12000.0],
                                       [4828.864447636441,
                                        -1837.5289360435293,
                                        12000.0],
                                       [5164.480908758037,
                                        150.27104683940598,
                                        12000.0],
                                       [4713.851967657242,
                                        2115.193625051473,
                                        12000.0],
                                       [2603.008877492194,
                                        4220.120167500123,
                                        15000.0],
                                       [789.8965541681328,
                                        4895.01101920698,
                                        15000.0],
                                       [-1143.4703590979323,
                                        4824.680816624959,
                                        15000.0],
                                       [-2902.7542757759547,
                                        4019.8366955523024,
                                        15000.0],
                                       [-4220.120167500123,
                                        2603.008877492194,
                                        15000.0],
                                       [-4895.01101920698,
                                        789.8965541681332,
                                        15000.0],
                                       [-4824.680816624959,
                                        -1143.470359097932,
                                        15000.0],
                                       [-4019.8366955523024,
                                        -2902.7542757759543,
                                        15000.0],
                                       [-2603.0088774921946,
                                        -4220.120167500123,
                                        15000.0],
                                       [-789.8965541681313,
                                        -4895.01101920698,
                                        15000.0],
                                       [1143.4703590979318,
                                        -4824.68081662496,
                                        15000.0],
                                       [2902.7542757759525,
                                        -4019.8366955523043,
                                        15000.0],
                                       [4220.120167500123,
                                        -2603.0088774921946,
                                        15000.0],
                                       [4895.01101920698,
                                        -789.8965541681315,
                                        15000.0],
                                       [4824.68081662496,
                                        1143.4703590979314,
                                        15000.0],
                                       [4019.8366955523043,
                                        2902.754275775952,
                                        15000.0],
                                       [1624.595680796927,
                                        4463.539948733064,
                                        18000.0],
                                       [-207.19208998534546,
                                        4745.479052513824,
                                        18000.0],
                                       [-2007.4367432683218,
                                        4304.961988424087,
                                        18000.0],
                                       [-3502.0673498480887,
                                        3209.0534861743868,
                                        18000.0],
                                       [-4463.539948733064,
                                        1624.5956807969271,
                                        18000.0],
                                       [-4745.479052513824,
                                        -207.19208998534518,
                                        18000.0],
                                       [-4304.961988424087,
                                        -2007.4367432683216,
                                        18000.0],
                                       [-3209.0534861743868,
                                        -3502.0673498480883,
                                        18000.0],
                                       [-1624.5956807969255,
                                        -4463.539948733065,
                                        18000.0],
                                       [207.1920899853449,
                                        -4745.479052513824,
                                        18000.0],
                                       [2007.4367432683193,
                                        -4304.961988424089,
                                        18000.0],
                                       [3502.0673498480883,
                                        -3209.053486174387,
                                        18000.0],
                                       [4463.539948733065,
                                        -1624.5956807969258,
                                        18000.0],
                                       [4745.479052513824,
                                        207.19208998534882,
                                        18000.0],
                                       [4304.961988424089,
                                        2007.436743268319,
                                        18000.0],
                                       [3209.053486174387,
                                        3502.0673498480883,
                                        18000.0],
                                       [658.2321943537453,
                                        4493.714108555122,
                                        21000.0],
                                       [-1111.5426871258871,
                                        4403.545045279776,
                                        21000.0],
                                       [-2712.0952706501525,
                                        3642.976167095824,
                                        21000.0],
                                       [-3899.755934422785,
                                        2327.79719113272,
                                        21000.0],
                                       [-4493.714108555122,
                                        658.2321943537465,
                                        21000.0],
                                       [-4403.545045279776,
                                        -1111.5426871258878,
                                        21000.0],
                                       [-3642.976167095824,
                                        -2712.0952706501525,
                                        21000.0],
                                       [-2327.7971911327204,
                                        -3899.7559344227843,
                                        21000.0],
                                       [-658.232194353747,
                                        -4493.714108555122,
                                        21000.0],
                                       [1111.5426871258876,
                                        -4403.545045279776,
                                        21000.0],
                                       [2712.095270650152,
                                        -3642.976167095824,
                                        21000.0],
                                       [3899.755934422782,
                                        -2327.7971911327236,
                                        21000.0],
                                       [4493.714108555122,
                                        -658.2321943537472,
                                        21000.0],
                                       [4403.545045279776,
                                        1111.5426871258874,
                                        21000.0],
                                       [3642.9761670958246,
                                        2712.095270650152,
                                        21000.0],
                                       [2327.7971911327245,
                                        3899.755934422782,
                                        21000.0],
                                       [-251.96092527872838,
                                        4326.002019175496,
                                        24000.0],
                                       [-1888.2708429740096,
                                        3900.283451411193,
                                        24000.0],
                                       [-3237.1086420443166,
                                        2880.7820843270642,
                                        24000.0],
                                       [-4093.1259948262873,
                                        1422.7077592587661,
                                        24000.0],
                                       [-4326.002019175496,
                                        -251.9609252787291,
                                        24000.0],
                                       [-3900.283451411193,
                                        -1888.2708429740094,
                                        24000.0],
                                       [-2880.7820843270642,
                                        -3237.1086420443166,
                                        24000.0],
                                       [-1422.7077592587664,
                                        -4093.125994826287,
                                        24000.0],
                                       [251.9609252787288,
                                        -4326.002019175496,
                                        24000.0],
                                       [1888.2708429740092,
                                        -3900.2834514111933,
                                        24000.0],
                                       [3237.1086420443166,
                                        -2880.7820843270642,
                                        24000.0],
                                       [4093.125994826287,
                                        -1422.7077592587666,
                                        24000.0],
                                       [4326.002019175496,
                                        251.96092527872852,
                                        24000.0],
                                       [3900.2834514111914,
                                        1888.2708429740123,
                                        24000.0],
                                       [2880.7820843270647,
                                        3237.108642044316,
                                        24000.0],
                                       [1422.7077592587668,
                                        4093.125994826287,
                                        24000.0],
                                       [-1067.6285610478985,
                                        3984.4440334424066,
                                        27000.0],
                                       [-2511.1408946609727,
                                        3272.582528701345,
                                        27000.0],
                                       [-3572.3547906108097,
                                        2062.4999999999995,
                                        27000.0],
                                       [-4089.710053166968,
                                        538.4205429077127,
                                        27000.0],
                                       [-3984.4440334424066,
                                        -1067.6285610478983,
                                        27000.0],
                                       [-3272.582528701345,
                                        -2511.1408946609727,
                                        27000.0],
                                       [-2062.499999999998,
                                        -3572.35479061081,
                                        27000.0],
                                       [-538.420542907713,
                                        -4089.710053166968,
                                        27000.0],
                                       [1067.6285610478963,
                                        -3984.444033442407,
                                        27000.0],
                                       [2511.140894660972,
                                        -3272.582528701345,
                                        27000.0],
                                       [3572.35479061081,
                                        -2062.4999999999986,
                                        27000.0],
                                       [4089.7100531669676,
                                        -538.4205429077168,
                                        27000.0],
                                       [3984.444033442407,
                                        1067.628561047896,
                                        27000.0],
                                       [3272.5825287013454,
                                        2511.140894660972,
                                        27000.0],
                                       [2062.4999999999986,
                                        3572.35479061081,
                                        27000.0],
                                       [538.420542907717,
                                        4089.7100531669676,
                                        27000.0],
                                       [-1757.7967891184767,
                                        3500.0611746000313,
                                        30000.0],
                                       [-2963.4078995643467,
                                        2560.9551730901894,
                                        30000.0],
                                       [-3717.867020661049,
                                        1231.9669615938203,
                                        30000.0],
                                       [-3906.3145904105745,
                                        -284.5770519968913,
                                        30000.0],
                                       [-3500.0611746000313,
                                        -1757.7967891184765,
                                        30000.0],
                                       [-2560.9551730901894,
                                        -2963.4078995643467,
                                        30000.0],
                                       [-1231.9669615938205,
                                        -3717.867020661049,
                                        30000.0],
                                       [284.57705199688934,
                                        -3906.314590410575,
                                        30000.0],
                                       [1757.7967891184762,
                                        -3500.0611746000313,
                                        30000.0],
                                       [2963.4078995643476,
                                        -2560.9551730901885,
                                        30000.0],
                                       [3717.867020661049,
                                        -1231.9669615938208,
                                        30000.0],
                                       [3906.314590410575,
                                        284.5770519968891,
                                        30000.0],
                                       [3500.061174600032,
                                        1757.796789118476,
                                        30000.0],
                                       [2560.9551730901885,
                                        2963.4078995643476,
                                        30000.0],
                                       [1231.966961593821,
                                        3717.8670206610486,
                                        30000.0],
                                       [-284.5770519968888,
                                        3906.314590410575,
                                        30000.0],
                                       [-2300.0399467864627,
                                        2908.8747574100944,
                                        33000.0],
                                       [-3238.1380072802253,
                                        1807.262669596859,
                                        33000.0],
                                       [-3683.2589099597053,
                                        430.5112232143976,
                                        33000.0],
                                       [-3567.637032422983,
                                        -1011.7816543084992,
                                        33000.0],
                                       [-2908.8747574100944,
                                        -2300.0399467864627,
                                        33000.0],
                                       [-1807.2626695968606,
                                        -3238.138007280224,
                                        33000.0],
                                       [-430.5112232143978,
                                        -3683.2589099597053,
                                        33000.0],
                                       [1011.7816543085006,
                                        -3567.6370324229824,
                                        33000.0],
                                       [2300.039946786462,
                                        -2908.874757410095,
                                        33000.0],
                                       [3238.138007280224,
                                        -1807.2626695968609,
                                        33000.0],
                                       [3683.2589099597053,
                                        -430.51122321439806,
                                        33000.0],
                                       [3567.6370324229833,
                                        1011.7816543084972,
                                        33000.0],
                                       [2908.874757410095,
                                        2300.039946786462,
                                        33000.0],
                                       [1807.2626695968581,
                                        3238.138007280226,
                                        33000.0],
                                       [430.5112232143982,
                                        3683.2589099597053,
                                        33000.0],
                                       [-1011.7816543084939,
                                        3567.6370324229847,
                                        33000.0],
                                       [-2681.1555509164227,
                                        2249.756633902888,
                                        36000.0],
                                       [-3338.009327618794,
                                        1052.4702982649567,
                                        36000.0],
                                       [-3486.6814433211093,
                                        -305.0450996168028,
                                        36000.0],
                                       [-3104.5379161237765,
                                        -1616.1201463226182,
                                        36000.0],
                                       [-2249.756633902888,
                                        -2681.1555509164227,
                                        36000.0],
                                       [-1052.4702982649583,
                                        -3338.0093276187936,
                                        36000.0],
                                       [305.0450996168026,
                                        -3486.6814433211093,
                                        36000.0],
                                       [1616.1201463226193,
                                        -3104.5379161237756,
                                        36000.0],
                                       [2681.1555509164223,
                                        -2249.7566339028886,
                                        36000.0],
                                       [3338.0093276187936,
                                        -1052.4702982649585,
                                        36000.0],
                                       [3486.6814433211093,
                                        305.0450996168024,
                                        36000.0],
                                       [3104.537916123777,
                                        1616.1201463226162,
                                        36000.0],
                                       [2249.7566339028886,
                                        2681.1555509164223,
                                        36000.0],
                                       [1052.4702982649558,
                                        3338.0093276187945,
                                        36000.0],
                                       [-305.0450996168022,
                                        3486.6814433211093,
                                        36000.0],
                                       [-1616.1201463226132,
                                        3104.537916123779,
                                        36000.0],
                                       [0.0, 0.0, 0.0],
                                       [0.0, 0.0, 36000.0]],
                       'triangles': [[0, 1, 17],
                                     [0, 17, 16],
                                     [1, 2, 18],
                                     [1, 18, 17],
                                     [2, 3, 19],
                                     [2, 19, 18],
                                     [3, 4, 20],
                                     [3, 20, 19],
                                     [4, 5, 21],
                                     [4, 21, 20],
                                     [5, 6, 22],
                                     [5, 22, 21],
                                     [6, 7, 23],
                                     [6, 23, 22],
                                     [7, 8, 24],
                                     [7, 24, 23],
                                     [8, 9, 25],
                                     [8, 25, 24],
                                     [9, 10, 26],
                                     [9, 26, 25],
                                     [10, 11, 27],
                                     [10, 27, 26],
                                     [11, 12, 28],
                                     [11, 28, 27],
                                     [12, 13, 29],
                                     [12, 29, 28],
                                     [13, 14, 30],
                                     [13, 30, 29],
                                     [14, 15, 31],
                                     [14, 31, 30],
                                     [15, 0, 16],
                                     [15, 16, 31],
                                     [16, 17, 33],
                                     [16, 33, 32],
                                     [17, 18, 34],
                                     [17, 34, 33],
                                     [18, 19, 35],
                                     [18, 35, 34],
                                     [19, 20, 36],
                                     [19, 36, 35],
                                     [20, 21, 37],
                                     [20, 37, 36],
                                     [21, 22, 38],
                                     [21, 38, 37],
                                     [22, 23, 39],
                                     [22, 39, 38],
                                     [23, 24, 40],
                                     [23, 40, 39],
                                     [24, 25, 41],
                                     [24, 41, 40],
                                     [25, 26, 42],
                                     [25, 42, 41],
                                     [26, 27, 43],
                                     [26, 43, 42],
                                     [27, 28, 44],
                                     [27, 44, 43],
                                     [28, 29, 45],
                                     [28, 45, 44],
                                     [29, 30, 46],
                                     [29, 46, 45],
                                     [30, 31, 47],
                                     [30, 47, 46],
                                     [31, 16, 32],
                                     [31, 32, 47],
                                     [32, 33, 49],
                                     [32, 49, 48],
                                     [33, 34, 50],
                                     [33, 50, 49],
                                     [34, 35, 51],
                                     [34, 51, 50],
                                     [35, 36, 52],
                                     [35, 52, 51],
                                     [36, 37, 53],
                                     [36, 53, 52],
                                     [37, 38, 54],
                                     [37, 54, 53],
                                     [38, 39, 55],
                                     [38, 55, 54],
                                     [39, 40, 56],
                                     [39, 56, 55],
                                     [40, 41, 57],
                                     [40, 57, 56],
                                     [41, 42, 58],
                                     [41, 58, 57],
                                     [42, 43, 59],
                                     [42, 59, 58],
                                     [43, 44, 60],
                                     [43, 60, 59],
                                     [44, 45, 61],
                                     [44, 61, 60],
                                     [45, 46, 62],
                                     [45, 62, 61],
                                     [46, 47, 63],
                                     [46, 63, 62],
                                     [47, 32, 48],
                                     [47, 48, 63],
                                     [48, 49, 65],
                                     [48, 65, 64],
                                     [49, 50, 66],
                                     [49, 66, 65],
                                     [50, 51, 67],
                                     [50, 67, 66],
                                     [51, 52, 68],
                                     [51, 68, 67],
                                     [52, 53, 69],
                                     [52, 69, 68],
                                     [53, 54, 70],
                                     [53, 70, 69],
                                     [54, 55, 71],
                                     [54, 71, 70],
                                     [55, 56, 72],
                                     [55, 72, 71],
                                     [56, 57, 73],
                                     [56, 73, 72],
                                     [57, 58, 74],
                                     [57, 74, 73],
                                     [58, 59, 75],
                                     [58, 75, 74],
                                     [59, 60, 76],
                                     [59, 76, 75],
                                     [60, 61, 77],
                                     [60, 77, 76],
                                     [61, 62, 78],
                                     [61, 78, 77],
                                     [62, 63, 79],
                                     [62, 79, 78],
                                     [63, 48, 64],
                                     [63, 64, 79],
                                     [64, 65, 81],
                                     [64, 81, 80],
                                     [65, 66, 82],
                                     [65, 82, 81],
                                     [66, 67, 83],
                                     [66, 83, 82],
                                     [67, 68, 84],
                                     [67, 84, 83],
                                     [68, 69, 85],
                                     [68, 85, 84],
                                     [69, 70, 86],
                                     [69, 86, 85],
                                     [70, 71, 87],
                                     [70, 87, 86],
                                     [71, 72, 88],
                                     [71, 88, 87],
                                     [72, 73, 89],
                                     [72, 89, 88],
                                     [73, 74, 90],
                                     [73, 90, 89],
                                     [74, 75, 91],
                                     [74, 91, 90],
                                     [75, 76, 92],
                                     [75, 92, 91],
                                     [76, 77, 93],
                                     [76, 93, 92],
                                     [77, 78, 94],
                                     [77, 94, 93],
                                     [78, 79, 95],
                                     [78, 95, 94],
                                     [79, 64, 80],
                                     [79, 80, 95],
                                     [80, 81, 97],
                                     [80, 97, 96],
                                     [81, 82, 98],
                                     [81, 98, 97],
                                     [82, 83, 99],
                                     [82, 99, 98],
                                     [83, 84, 100],
                                     [83, 100, 99],
                                     [84, 85, 101],
                                     [84, 101, 100],
                                     [85, 86, 102],
                                     [85, 102, 101],
                                     [86, 87, 103],
                                     [86, 103, 102],
                                     [87, 88, 104],
                                     [87, 104, 103],
                                     [88, 89, 105],
                                     [88, 105, 104],
                                     [89, 90, 106],
                                     [89, 106, 105],
                                     [90, 91, 107],
                                     [90, 107, 106],
                                     [91, 92, 108],
                                     [91, 108, 107],
                                     [92, 93, 109],
                                     [92, 109, 108],
                                     [93, 94, 110],
                                     [93, 110, 109],
                                     [94, 95, 111],
                                     [94, 111, 110],
                                     [95, 80, 96],
                                     [95, 96, 111],
                                     [96, 97, 113],
                                     [96, 113, 112],
                                     [97, 98, 114],
                                     [97, 114, 113],
                                     [98, 99, 115],
                                     [98, 115, 114],
                                     [99, 100, 116],
                                     [99, 116, 115],
                                     [100, 101, 117],
                                     [100, 117, 116],
                                     [101, 102, 118],
                                     [101, 118, 117],
                                     [102, 103, 119],
                                     [102, 119, 118],
                                     [103, 104, 120],
                                     [103, 120, 119],
                                     [104, 105, 121],
                                     [104, 121, 120],
                                     [105, 106, 122],
                                     [105, 122, 121],
                                     [106, 107, 123],
                                     [106, 123, 122],
                                     [107, 108, 124],
                                     [107, 124, 123],
                                     [108, 109, 125],
                                     [108, 125, 124],
                                     [109, 110, 126],
                                     [109, 126, 125],
                                     [110, 111, 127],
                                     [110, 127, 126],
                                     [111, 96, 112],
                                     [111, 112, 127],
                                     [112, 113, 129],
                                     [112, 129, 128],
                                     [113, 114, 130],
                                     [113, 130, 129],
                                     [114, 115, 131],
                                     [114, 131, 130],
                                     [115, 116, 132],
                                     [115, 132, 131],
                                     [116, 117, 133],
                                     [116, 133, 132],
                                     [117, 118, 134],
                                     [117, 134, 133],
                                     [118, 119, 135],
                                     [118, 135, 134],
                                     [119, 120, 136],
                                     [119, 136, 135],
                                     [120, 121, 137],
                                     [120, 137, 136],
                                     [121, 122, 138],
                                     [121, 138, 137],
                                     [122, 123, 139],
                                     [122, 139, 138],
                                     [123, 124, 140],
                                     [123, 140, 139],
                                     [124, 125, 141],
                                     [124, 141, 140],
                                     [125, 126, 142],
                                     [125, 142, 141],
                                     [126, 127, 143],
                                     [126, 143, 142],
                                     [127, 112, 128],
                                     [127, 128, 143],
                                     [128, 129, 145],
                                     [128, 145, 144],
                                     [129, 130, 146],
                                     [129, 146, 145],
                                     [130, 131, 147],
                                     [130, 147, 146],
                                     [131, 132, 148],
                                     [131, 148, 147],
                                     [132, 133, 149],
                                     [132, 149, 148],
                                     [133, 134, 150],
                                     [133, 150, 149],
                                     [134, 135, 151],
                                     [134, 151, 150],
                                     [135, 136, 152],
                                     [135, 152, 151],
                                     [136, 137, 153],
                                     [136, 153, 152],
                                     [137, 138, 154],
                                     [137, 154, 153],
                                     [138, 139, 155],
                                     [138, 155, 154],
                                     [139, 140, 156],
                                     [139, 156, 155],
                                     [140, 141, 157],
                                     [140, 157, 156],
                                     [141, 142, 158],
                                     [141, 158, 157],
                                     [142, 143, 159],
                                     [142, 159, 158],
                                     [143, 128, 144],
                                     [143, 144, 159],
                                     [144, 145, 161],
                                     [144, 161, 160],
                                     [145, 146, 162],
                                     [145, 162, 161],
                                     [146, 147, 163],
                                     [146, 163, 162],
                                     [147, 148, 164],
                                     [147, 164, 163],
                                     [148, 149, 165],
                                     [148, 165, 164],
                                     [149, 150, 166],
                                     [149, 166, 165],
                                     [150, 151, 167],
                                     [150, 167, 166],
                                     [151, 152, 168],
                                     [151, 168, 167],
                                     [152, 153, 169],
                                     [152, 169, 168],
                                     [153, 154, 170],
                                     [153, 170, 169],
                                     [154, 155, 171],
                                     [154, 171, 170],
                                     [155, 156, 172],
                                     [155, 172, 171],
                                     [156, 157, 173],
                                     [156, 173, 172],
                                     [157, 158, 174],
                                     [157, 174, 173],
                                     [158, 159, 175],
                                     [158, 175, 174],
                                     [159, 144, 160],
                                     [159, 160, 175],
                                     [160, 161, 177],
                                     [160, 177, 176],
                                     [161, 162, 178],
                                     [161, 178, 177],
                                     [162, 163, 179],
                                     [162, 179, 178],
                                     [163, 164, 180],
                                     [163, 180, 179],
                                     [164, 165, 181],
                                     [164, 181, 180],
                                     [165, 166, 182],
                                     [165, 182, 181],
                                     [166, 167, 183],
                                     [166, 183, 182],
                                     [167, 168, 184],
                                     [167, 184, 183],
                                     [168, 169, 185],
                                     [168, 185, 184],
                                     [169, 170, 186],
                                     [169, 186, 185],
                                     [170, 171, 187],
                                     [170, 187, 186],
                                     [171, 172, 188],
                                     [171, 188, 187],
                                     [172, 173, 189],
                                     [172, 189, 188],
                                     [173, 174, 190],
                                     [173, 190, 189],
                                     [174, 175, 191],
                                     [174, 191, 190],
                                     [175, 160, 176],
                                     [175, 176, 191],
                                     [176, 177, 193],
                                     [176, 193, 192],
                                     [177, 178, 194],
                                     [177, 194, 193],
                                     [178, 179, 195],
                                     [178, 195, 194],
                                     [179, 180, 196],
                                     [179, 196, 195],
                                     [180, 181, 197],
                                     [180, 197, 196],
                                     [181, 182, 198],
                                     [181, 198, 197],
                                     [182, 183, 199],
                                     [182, 199, 198],
                                     [183, 184, 200],
                                     [183, 200, 199],
                                     [184, 185, 201],
                                     [184, 201, 200],
                                     [185, 186, 202],
                                     [185, 202, 201],
                                     [186, 187, 203],
                                     [186, 203, 202],
                                     [187, 188, 204],
                                     [187, 204, 203],
                                     [188, 189, 205],
                                     [188, 205, 204],
                                     [189, 190, 206],
                                     [189, 206, 205],
                                     [190, 191, 207],
                                     [190, 207, 206],
                                     [191, 176, 192],
                                     [191, 192, 207],
                                     [208, 1, 0],
                                     [209, 192, 193],
                                     [208, 2, 1],
                                     [209, 193, 194],
                                     [208, 3, 2],
                                     [209, 194, 195],
                                     [208, 4, 3],
                                     [209, 195, 196],
                                     [208, 5, 4],
                                     [209, 196, 197],
                                     [208, 6, 5],
                                     [209, 197, 198],
                                     [208, 7, 6],
                                     [209, 198, 199],
                                     [208, 8, 7],
                                     [209, 199, 200],
                                     [208, 9, 8],
                                     [209, 200, 201],
                                     [208, 10, 9],
                                     [209, 201, 202],
                                     [208, 11, 10],
                                     [209, 202, 203],
                                     [208, 12, 11],
                                     [209, 203, 204],
                                     [208, 13, 12],
                                     [209, 204, 205],
                                     [208, 14, 13],
                                     [209, 205, 206],
                                     [208, 15, 14],
                                     [209, 206, 207],
                                     [208, 0, 15],
                                     [209, 207, 192]]},
              'category': 'mass',
              'name': 'витая башня'}]},
    "auth_face_wall_existing_mass": {'ir_version': '1.0',
     'intent': 'стена по скату существующей массы',
     'ops': [{'op': 'create_face_wall',
              'id': 'FW1',
              'host': {'by': 'element_id', 'value': 900001},
              'face_normal': [0.6, 0.0, 0.8],
              'location_line': 'core_exterior',
              'type': {'by': 'name', 'value': 'Кирпич 250'}}]},
    "auth_pipe_system_chain": {'ir_version': '1.0',
     'intent': 'стояк ВК с отводом',
     'ops': [{'op': 'create_pipe_system',
              'id': 'SYS1',
              'level': {'by': 'element_id', 'value': 42},
              'nodes': [{'id': 'N1', 'xyz_mm': [0, 0, 0]},
                        {'id': 'N2', 'xyz_mm': [0, 0, 15000]},
                        {'id': 'N3', 'xyz_mm': [3000, 0, 15000]}],
              'segments': [{'from': 'N1', 'to': 'N2', 'diameter_mm': 100},
                           {'from': 'N2', 'to': 'N3', 'diameter_mm': 50}]}]},
    "struct_area_reinforcement_slabs": {'ir_version': '1.0',
     'intent': 'армирование двух плит одной программой',
     'ops': [{'op': 'create_floor',
              'id': 'SL1',
              'outline': [[0, 0], [9000, 0], [9000, 6000], [0, 6000]],
              'level': {'by': 'element_id', 'value': 42},
              'structural': True},
             {'op': 'create_area_reinforcement',
              'id': 'AR1',
              'host': {'by': 'ref', 'value': 'SL1'},
              'direction_deg': 0.0,
              'bar_type': {'by': 'name', 'value': 'Ø12 A500C'}},
             {'op': 'create_area_reinforcement',
              'id': 'AR2',
              'host': {'by': 'element_id', 'value': 8145901},
              'direction_deg': 90.0,
              'type': {'by': 'name', 'value': 'Армирование по области 2'},
              'bar_type': {'by': 'element_id', 'value': 1902},
              'hook_type': {'by': 'name', 'value': 'Крюк 90'}}]},
    "struct_framing_bay": {'ir_version': '1.0',
     'intent': 'пролёт: две балочные системы, две фермы и балка',
     'ops': [{'op': 'create_beam_system',
              'id': 'BS1',
              'profile': {'outer': {'shape': 'rect',
                                    'origin': [0, 0],
                                    'size_mm': [12000, 6000]}},
              'level': {'by': 'element_id', 'value': 42}},
             {'op': 'create_beam_system',
              'id': 'BS2',
              'profile': {'outer': {'shape': 'l',
                                    'origin': [0, 7000],
                                    'size_mm': [12000, 8000],
                                    'cut_mm': [4000, 3000],
                                    'corner': 'ne'}},
              'level': {'by': 'element_id', 'value': 42}},
             {'op': 'create_truss',
              'id': 'TR1',
              'p0_mm': [0, 16000],
              'p1_mm': [12000, 16000],
              'level': {'by': 'element_id', 'value': 42},
              'type': {'by': 'name', 'value': 'Ферма стропильная 12м'}},
             {'op': 'create_truss',
              'id': 'TR2',
              'p0_mm': [0, 19000],
              'p1_mm': [12000, 19000],
              'level': {'by': 'element_id', 'value': 42}},
             {'op': 'create_beam',
              'id': 'B1',
              'p0_mm': [0, 22000, 3000],
              'p1_mm': [12000, 22000, 3000],
              'level': {'by': 'element_id', 'value': 42}}]},
    # Lifted from gate_runner (CLASH repair wave, 2026-07-28) so ONE source
    # serves the gate and the golden. `move_elements` is first of the
    # thirteen by REVERSIBILITY — a creation error adds a visible wrong
    # thing, a modification error destroys a thing that was already right —
    # and it carries THREE targets ON PURPOSE. With ONE target an
    # off-by-one at the witness loop bound is INVISIBLE BY CONSTRUCTION —
    # there is no last element to lose. The pin therefore rests not on a
    # golden existing but on BOTH `__mtEls_ME1.Count` bounds standing in
    # the emitted bytes. A mutation doing exactly that (`Count - 1`)
    # survived the entire suite, the gate 6/6 and all 57 goldens
    # (measured 2026-08-12); against this file it reddens exactly one
    # subtest and no other.
    #
    # NOTE the gate cannot help here and never could: `Count - 1` compiles
    # perfectly on all six versions. The golden and the gate are the two
    # genuinely independent instruments — the SUITE is not a third, because
    # this file is inside it.
    "auth_move_and_change_type": {
        "ir_version": "1.0",
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
        ],
    },
    # Lifted from gate_runner (wave/families 2026-07-17) so ONE source
    # serves both: the gate receives these through its seed from PROGRAMS,
    # and the golden pins exactly what the gate compiles. Their `.cs` files
    # had sat since 2026-07-17 with no program at all — the bytes below are
    # regenerated, not adopted.
    "families_create_type_full": {
        "ir_version": "1.0",
        "intent": "жб колонна 400x400 из существующего типа",
        "ops": [{"op": "create_type", "id": "T1",
                 "source_type": {"by": "element_id", "value": 500},
                 "category": "structural", "new_name": "ЖБ 400x400",
                 "width_mm": 400, "depth_mm": 400, "material": "Бетон"}],
    },
    "families_load_family_whole": {
        "ir_version": "1.0",
        "intent": "загрузить семейство целиком (первый типоразмер)",
        "ops": [{"op": "load_family", "id": "F1",
                 "path": r"C:\ProgramData\Autodesk\RVT 2024\Libraries\Russian\Конструкции\Колонны\Бетонные\M_Бетонная-Прямоугольная-Колонна.rfa"}],
    },
    # `create_duct` and `create_roof` had NO offline net at all before
    # 2026-08-12: no golden, AND no gate program either (measured over the
    # gate's own 164 programs). `create_duct` carries live evidence — 215
    # built, 98.2% — so it builds in production with nothing offline
    # watching it. Not a reservation: a four-line program against the
    # standard snapshot compiles AND Roslyn-builds on all six versions, so
    # it was simply never written.
    "duct_min": {
        "ir_version": "1.0", "intent": "воздуховод",
        "ops": [
            {"op": "create_duct", "id": "D1",
             "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
             "level": {"by": "element_id", "value": 42}},
        ],
    },
    "roof_min": {
        "ir_version": "1.0", "intent": "кровля",
        "ops": [
            {"op": "create_roof", "id": "R1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": {"by": "element_id", "value": 42}},
        ],
    },
    # `create_roof.slopes` was the LAST plural operand with cardinality 0 in
    # the whole golden corpus (measured 2026-08-12 by the gate zone, after
    # the unpinned-plural registry stopped matching on the label form and
    # started reading contents). `roof_min` above says so in its own note:
    # "does NOT pin: slope". It matters more than a missing pin usually does,
    # because slopes is walked TWICE by independent code — a generator that
    # renders the ratio array (`authoring.py:2929`) and a hand-written C#
    # loop that consumes it edge by edge (`:2935`) — and the two agreeing is
    # exactly the "asserted here, read there" class this compiler is built
    # against. A gable: two opposite edges pitched, two left level, so the
    # `-1.0` sentinel and a real ratio both appear in the frozen bytes and
    # neither branch of the loop's `if` can be dropped unnoticed.
    "roof_gable_slopes": {
        "ir_version": "1.0", "intent": "двускатная кровля",
        "ops": [
            {"op": "create_roof", "id": "R1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "slopes": [30.0, None, 30.0, None],
             "level": {"by": "element_id", "value": 42}},
        ],
    },
}


#: Goldens frozen from today's emission WITHOUT a correctness review.
#: A golden is a CHANGE DETECTOR, never a certificate that the bytes are
#: RIGHT: if an op emits wrongly today, freezing makes the wrong output
#: canonical and the future FIX then looks like the regression.
#: `grep -n UNREVIEWED_GOLDENS` enumerates them.
#:
#: The marker cannot live INSIDE the .cs: `test_golden` compares each file
#: byte-for-byte against `out.csharp`, so a header line would make every
#: golden red against its own emitter — a mark that breaks the thing it
#: marks. Any annotation on a byte-compared artefact must live OUTSIDE it.
UNREVIEWED_GOLDENS: dict[str, str] = {
    "solid_extrusion_and_revolve":
        "2026-08-19; ПЕРЕЕХАЛ ИЗ PREDATES_CONVENTION — перезаморожен вместе с "
        "асимметричным допуском габарита у ОБОИХ солидов и числами в тексте "
        "нарушения. Диф прочитан построчно: 34 строки, все в SE1 и SR1, "
        "постороннего нет; у выдавливания запас 0.0, то есть условие "
        "семантически ТОЖДЕСТВЕННО прежнему |MM-x0|>dt — работающий свидетель "
        "не ослаблен, изменилась только форма записи. "
        "does NOT pin: (1) сам множитель 2.0e-3 — он ВЫБРАН как замеренные "
        "5.6e-4 радиуса с запасом 3.6x, плотность тесселяции Revit нигде не "
        "документирована и от версии к версии не обещана; (2) поведение Revit "
        "на ПРОФИЛЕ С ДУГОЙ у выдавливания — этот эталон её содержит (bulge "
        "0.4), но живьём выдавливание проверено только на ПРЯМОМ контуре, и "
        "недобор на дуге у него НЕ ЗАМЕРЕН НИ РАЗУ, а запас стоит 0.0; (3) что "
        "габарит равен привязкам — здесь наш вывод сверяется с нашим же "
        "выводом, живой замер лежит в test_sector_bbox_tessellation.py",
    "native_group": (
        "2026-08-19; ПЕРЕЕХАЛ ИЗ PREDATES_CONVENTION — перезаморожен вместе с "
        "обязательством `member_positions` (ось ГЕОМЕТРИИ у create_group была "
        "пуста). Диф прочитан построчно: 70 строк, все мои и только в этом "
        "эталоне — сбор размещений в список уровня программы (иначе свидетель "
        "их не видит под per_op), чтение членов каждого экземпляра через "
        "GetMemberIds, вычитание смещения копии, сравнение по БЛИЖАЙШЕМУ соответствию (без "
        "сортировки: её delegate-компаратор сторож областей видимости не считает "
        "объявлением, под per_op это CS0103), "
        "двусторонний сторож с допуском 1000.0 и четыре числа в квитанции. "
        "Посторонний `datums_multistory_stairs` KIR_UPDATE_GOLDEN тронул только "
        "переводами строк — сверено побайтно и возвращено. Roslyn собирает "
        "2021/2023/2026. pins: эмиссию группы с двумя ненулевыми смещениями. "
        "does NOT pin верность 1000 мм — число ВЫБРАНО, а не замерено, и порог "
        "груб намеренно: bbox члена законно отличается между копиями, если швы "
        "соединений разные (замер 18.08, солид двигается на полтолщины). "
        "does NOT pin поведение Revit — что копия группы вообще воспроизводит "
        "члены со смещением, здесь не проверено ничем: живых прогонов ноль. "
        "does NOT pin случай СОВПАДАЮЩИХ смещений (59 дублей замера 18.08): он "
        "меняет один целочисленный литерал в квитанции и закреплён юнит-тестом "
        "`test_group_positions.CoincidentInstancesAreCounted`, а не эталоном — "
        "отдельный эталон на 300 строк ради одного числа тут не заведён "
        "СОЗНАТЕЛЬНО."
    ),

    "wall_top_attached": (
        "2026-08-19; ПЕРЕЕХАЛ ИЗ PREDATES_CONVENTION — перезаморожен вместе с "
        "обязательством `vertical_extent` (Э3.1). Диф прочитан построчно, 41 "
        "строка, и ВСЯ она моя: два double выведенного габарита в объявлении, "
        "два присваивания из MM(__lv.Elevation) и MM(__tl.Elevation), "
        "односторонний сторож пролёта с допуском 300.0 и пара чисел в "
        "квитанции. Ничего постороннего диф не тронул. Roslyn 2023 собирает. "
        "pins: эмиссию стены с привязкой верха к уровню. does NOT pin: "
        "верность 300 мм (ВЫБРАНО, не замерено); does NOT pin поведение Revit "
        "— что bbox стены равен привязкам, здесь не проверено ничем; does NOT "
        "pin случай без top_level — там источником истины остаётся "
        "WALL_USER_HEIGHT_PARAM, и это замер 29.07"),
    "struct_column_top_constrained": (
        "2026-08-19; FROZEN FIRST TIME — заведён вместе с обязательством "
        "`vertical_extent` (Э3.1), закрывающим ветку, которой в корпусе не "
        "было: единственная прежняя программа с create_column не имела "
        "top_level вовсе. Проверен в эмитированном C# глазами: выведенный "
        "габарит вынесен в decl двумя double и присваивается из "
        "MM(__lv.Elevation)+150 и MM(__ctl.Elevation)+-250; сторож читает "
        "bbox и сравнивает ПРОЛЁТ; допуск 300.0 присутствует в C# (иначе "
        "emit_model отказывает по провенансу); квитанция несёт "
        "vertical_extent_mm и vertical_extent_expected_mm. Roslyn 2023 "
        "собирает. pins: эмиссию колонны С верхней привязкой и оба смещения. "
        "does NOT pin: верность величины 300 мм — она ВЫБРАНА, а не замерена "
        "(замерен промах 1100 мм), и первым живым прогоном может вырасти; "
        "does NOT pin ПОВЕДЕНИЕ Revit — что bbox колонны действительно равен "
        "привязкам, здесь не проверено ничем, живого прогона у операции с "
        "верхней привязкой не было; does NOT pin случай БЕЗ top_level — там "
        "габарит не выводится, и говорит про это не свидетель, а объявление "
        "ParamSpec.omission_transfers"),
    "annotation_full_set": (
        "2026-08-13; FROZEN FIRST TIME — the file did not exist, and the "
        "test said so in its own words («missing — run once with "
        "KIR_UPDATE_GOLDEN=1 and review»); determinism proven BEFORE the "
        "freeze by two processes at PYTHONHASHSEED 0 and 12345, "
        "byte-identical (33 425 bytes); reviewed in the emitted C# against "
        "the canon's named checkpoints; pins: AngularDimension.Create with "
        "the FIVE-argument overload (the only one in the dimension family "
        "that compiles on all six), NewDimension through a ReferenceArray "
        "(geometric references, never Reference(element)), and TextNote "
        "placed through the VIEW BASIS (Origin + Right*U(x) + Up*U(y)); "
        "does NOT pin: the version axis (frozen at 2026 alone), that Revit "
        "BUILDS any of it, the angular arc's geometry (derived by the "
        "emitter, indistinguishable offline), nor the tag-with-type and "
        "text-without-leader configurations"),
    "annotation_explicit_types": (
        "2026-08-13; FROZEN FIRST TIME, same history as its sibling; "
        "determinism proven the same way (35 697 bytes); frozen at 2022 "
        "because tag_type forces the >=2022 symId branch; pins: the "
        "type-carrying IndependentTag.Create overload WITH leader, beside "
        "the sibling's typeless one — cardinality 2, so substituting one "
        "form for the other cannot pass unseen; does NOT pin: the version "
        "axis, live behaviour, the derived arc, nor the reverse "
        "configurations (typed text without leader, untyped tag with one)"),
    "families_create_type_full": (
        "2026-08-12; REGENERATED, not adopted — the file had sat since "
        "2026-07-17 with no program and was never once compared (disk 6986 "
        "vs 7008 today); pins: create_type from an element_id source under "
        "category=structural with explicit width/depth/material; "
        "does NOT pin: by-name sources, architectural category, custom "
        "param names, the type+set_param ref chain"),
    "families_load_family_whole": (
        "2026-08-12; REGENERATED, not adopted — same history (disk 5957 vs "
        "6389 today); pins: load_family of a whole family by path; "
        "does NOT pin: the named-type variant (type_name), nor any path "
        "that is not a Windows absolute path"),
    "auth_annotation": (
        "2026-08-12; pins: create_dimension, create_angular_dimension, create_tag and create_text in one view-space program; does NOT pin: sections/elevations (the loop is built on a PLAN basis), nor in_view by ref, nor dimension references other than the two walls used here"),
    "auth_contour_l": (
        "2026-08-12; pins: create_floor_by_contour with an L outline and one "
        "opening; does NOT pin: arc segments in the contour, multiple "
        "openings, nor at_grid anchors. "
        "🔴 ПРОЧИТАН ПОСТРОЧНО 19.08.2026, И ЧТЕНИЕ НАШЛО СЛЕПОТУ ЖИВОГО "
        "СВИДЕТЕЛЯ, а не дефект байтов. Эмиссия контуру СООТВЕТСТВУЕТ: "
        "внешнее кольцо (0,0)->(16000,0)->(16000,6000)->(10000,6000)->"
        "(10000,10000)->(0,10000) есть ровно L 16000x10000 с вырезом 6000x4000 "
        "из угла max-x/max-y, обход против часовой; дыра 3000x6000 от "
        "(1000,1000) лежит внутри полки; порядок колец у `Floor.Create` "
        "внешнее-первым соблюдён. "
        "НО ЖИВОЙ СВИДЕТЕЛЬ ЗДЕСЬ — ТОЛЬКО ГАБАРИТ: он сверяет Min/Max по X и Y "
        "с допуском 50 мм и ПО ПОСТРОЕНИЮ не видит ни выреза, ни отверстия. "
        "Эмиттер, потерявший вырез и построивший прямоугольник 16000x10000, "
        "прошёл бы этот witness зелёным, подписав ось `(geometry)`. Ловит такую "
        "потерю СЕГОДНЯ только сам голден — побайтовым сравнением, — то есть "
        "оффлайн-детектор изменения, а не живая приёмка. "
        "И ГЛАВНОЕ, ЧЕГО ЧТЕНИЕ НЕ ДАЁТ ВООБЩЕ: имя списка означает «заморожено "
        "БЕЗ проверки правильности», а правильность эмиссии для Revit "
        "устанавливается ЖИВЫМ ПРОГОНОМ. Чтение даёт лишь «согласовано с "
        "программой и с документированным API». Поэтому запись остаётся здесь, "
        "а не переносится: снять её — значит выдать чтение за живой замер. "
        "Не установлено чтением: требует ли Revit ПРОТИВОПОЛОЖНОЙ намотки у "
        "кольца отверстия (здесь оба кольца против часовой)"),
    "auth_curtain_cell_named_type": (
        "2026-08-12; pins: set_curtain_panel into a named cell type; does NOT pin: the AUTO_PANEL vs AUTO_PANEL_WALL default-panel branch, nor curtain WINDOW cells (no readable address by construction)"),
    "auth_curtain_grid_lines": (
        "2026-08-12; pins: create_curtain_grid_line on both axes; does NOT pin: removal of segments, nor grids on a curved curtain wall"),
    "auth_solid_boolean_difference": (
        "2026-08-20; pins: create_solid_boolean difference emission, the "
        "four-volume/four-area witness, and the auxiliary solid built by a "
        "DIFFERENT call; does NOT pin: union, intersect, parts other than "
        "sphere, several parts at once, an arc profile"),
    "auth_solid_boolean_prism_voids": (
        "2026-08-21; pins: the FOURTH kind of boolean operand — a prism over "
        "an explicit contour — with one part placed by base_z_mm and one by a "
        "`plane` (vertical face), each part's loops under its OWN variable "
        "name, and the part extruded ALONG THE PLANE NORMAL rather than +Z; "
        "does NOT pin: union/intersect with a prism, an arc edge in a part "
        "contour, holes inside a part contour, nor a prism part mixed with "
        "box/sphere/cylinder in one op"),
    "auth_directshape_tower": (
        "2026-08-12; pins: create_directshape from a stacked solid; does NOT pin: mesh geometry, nor category other than the one used here"),
    "auth_face_wall_existing_mass": (
        "2026-08-12; pins: create_face_wall on an existing mass face; does NOT pin: mass created in the same program, nor by-face roofs (they need FamilyInstance)"),
    "auth_pipe_system_chain": (
        "2026-08-12; pins: create_pipe_system over a riser+branch chain; does NOT pin: slope validation branches, nor duct systems"),
    "struct_area_reinforcement_slabs": (
        "2026-08-12; pins: create_area_reinforcement over slab hosts; does NOT pin: wall hosts, nor per-layer bar overrides"),
    "struct_framing_bay": (
        "2026-08-12; pins: create_beam_system and create_truss in one bay; does NOT pin: arc profiles, sloped systems, nor truss types other than the one used here"),
    "auth_move_and_change_type": (
        "2026-08-22; ПЕРЕЗАМОРОЖЕН вместе с КРУГОМ ПОСЛЕДСТВИЙ переноса. "
        "Диф прочитан целиком и весь мой: 6 строк объявления, ТРИ "
        "одинаковых снимка соседей (по одному на цель — вставки хозяина "
        "через HostObject.FindInserts, соединения через "
        "JoinGeometryUtils.GetJoinedElements, залоченные размеры через "
        "Element.GetDependentElements+Dimension.IsLocked), два новых "
        "сторожа в post и шесть полей квитанции. Ни одна прежняя строка "
        "эмиссии не тронута. Roslyn собирает 6/6 на обеих изоляциях "
        "(36 из 36 проверок, 22.08). "
        "pins: move_elements over THREE targets (two refs + "
        "one element_id) and change_type by ref, with the witness loop "
        "bounds visible in the bytes, плюс байты обоих соседских сторожей "
        "и шести полей квитанции; does NOT pin: connector-preserving "
        "moves on MEP with real connections, single-target moves, "
        "change_type on a non-ref target, nor ПОВЕДЕНИЕ Revit — что "
        "вставки переживают перенос хозяина и что замок автора его "
        "переживает, здесь не проверено ничем: живых прогонов ноль, "
        "куплена только компилируемость"),
    "modify_setparam_delete": (
        "2026-08-22; ПЕРЕЕХАЛ ИЗ PREDATES_CONVENTION — перезаморожен "
        "вместе с КРУГОМ ПОСЛЕДСТВИЙ удаления. Диф прочитан целиком, "
        "четыре места, и всё моё: одна строка объявления "
        "(List<string> __delalso_D1), тело try, забирающее возврат "
        "doc.Delete (ICollection<ElementId> — всё, что Revit удалил как "
        "полностью зависимое от цели), и три поля квитанции "
        "collateral_count/collateral_ids/collateral_capped. Ни одна "
        "прежняя строка не тронута; лишних вызовов Revit НОЛЬ — возврат "
        "прежде выбрасывался. Roslyn собирает 6/6 на обеих изоляциях. "
        "pins: эмиссию set_param+delete в одной программе и байты съёма "
        "попутно удалённого; does NOT pin: удаление по ref, отказ "
        "allow_destructive (он до эмиссии), ни ПОВЕДЕНИЕ Revit — что "
        "именно попадёт в возврат на настоящей стене с дверью, здесь не "
        "проверено ничем: живых прогонов ноль"),
    "duct_min": (
        "2026-08-12; pins: the create_duct emission under GROUNDING "
        "DEFAULTS for system_type and duct_type; does NOT pin: explicit "
        "type selection, nor the duct Shape branches "
        "(Rectangular/Round/Oval decide whether diameter_mm applies)"),
    "roof_min": (
        "2026-08-12; pins: create_roof from a 4-point rectangular outline "
        "under a grounding-default type; does NOT pin: slope, arc "
        "profiles, non-rectangular outlines, explicit type selection"),
    # A DUPLICATE FOUND BY THE 12.08 MERGE — both entries below pin ONE
    # AND THE SAME fact: `create_foundation.holes` at cardinality 2 with
    # rings of different cardinality (4 and 5). The GATE zone re-froze
    # the existing `struct_foundation_slab`; the LEAD's line set up a
    # separate `struct_foundation_slab_two_holes`. Neither knew about
    # the other. Both are left in place ON PURPOSE: deleting a golden is
    # a decision about someone else's committed work, and a merge is not
    # the place to make it. Which one to retire is open work; for now we
    # keep both and know we are paying for one fact twice.
    "struct_foundation_slab_two_holes": (
        "2026-08-12; pins: create_foundation.holes at CARDINALITY 2 — the "
        "bounds of the per-hole loop (authoring.py:1332), two openings of "
        "different vertex counts (4 and 5) so a body emitting only the first "
        "cannot pass, and the pre-2022 typed refusal branch (Floor.Create "
        "carries holes from 2022; NewFloor never did); "
        "does NOT pin: arc-segmented hole boundaries, a hole that touches or "
        "leaves the outline, overlapping holes, nor holes on the isolated "
        "variety (which takes no outline at all)"),
    "roof_gable_slopes": (
        "2026-08-12; pins: create_roof.slopes — the ratio array, the -1.0 "
        "level-edge sentinel, and the bounds of the C# loop that consumes "
        "them, i.e. BOTH traversals of one list; "
        "ONE thing here WAS reviewed rather than frozen blind, and only "
        "one: the degrees->ratio conversion, checked against the measured "
        "API fact that set_SlopeAngle takes rise/run and not radians "
        "(45deg sent as 0.7854 rad came back 5221mm where 45deg needs "
        "6400) — tan(radians(30)) = 0.577350269 is in the bytes; "
        "does NOT pin: whether ModelCurveArray order matches the outline "
        "order, which decides WHICH edges pitch and is unanswerable "
        "offline — a live roof is the only instrument for it; nor slopes "
        "on arc profiles, nor a fully-pitched hip (no -1.0 in the array), "
        "nor the rise witness tolerance"),
    "struct_foundation_slab": (
        "2026-08-12; RE-FROZEN, not adopted — the file predated the "
        "convention and its program carried ONE hole, which made the "
        "emitter's `for hi, hole in enumerate(holes)` boundary invisible "
        "by construction; pins: create_foundation(variety=slab) with TWO "
        "holes of DIFFERENT ring cardinality (4 and 5 points), so both "
        "the outer hole loop (__hl_F1_0 / __hl_F1_1, both Add-ed to "
        "__loops_F1) and each ring's own closing segment stand in the "
        "bytes, under a by-name level and a by-name floor type on 2026; "
        "does NOT pin: the 2021 legacy NewFloor branch (holes REFUSE "
        "there, EMIT_UNSUPPORTED), the document-default type branch, the "
        "isolated variety (its own golden), nor holes at the 8-contour "
        "MAX_HOLES ceiling"),
}

#: The generator CANNOT create an orphan: `test_golden` under
#: KIR_UPDATE_GOLDEN=1 iterates PROGRAMS and writes only those names, so a
#: forgotten entry produces NO file and is visible immediately. The only
#: way in is what happened here — WRITING A .cs BY HAND. Do not.
#: Goldens that have NEVER had a program in :data:`PROGRAMS` — verified
#: against git history 2026-08-12, not inferred: `git log -S<name>` over
#: this file returns ZERO commits before today for all four, while each
#: `.cs` was ADDED BY HAND in the commit that introduced its ops.
#: So they did not go stale — THEY WERE NEVER CHECKED ONCE, and their
#: contents are of unknown correctness rather than merely old. Measured
#: 2026-08-12, and the four do NOT share a fate: two have a program in
#: the GATE corpus whose emission has since moved on (a month-old
#: freeze, not foreign content), and two have NO program anywhere at
#: all. None can be adopted for free — wiring any name in reddens
#: test_golden immediately, because file != emission. That
#: distinction decides what to do with them: "stale" invites wiring them
#: up as-is; "never verified" requires regenerating and reviewing.
#: `test_golden` iterates PROGRAMS, so these files are compared against
#: NOTHING — they are bytes on disk that a `grep` reads as coverage while
#: no test can ever go red over them. Found 2026-08-12 when two sessions'
#: golden censuses disagreed: one had grepped `// create_dimension ` and
#: found two "goldens", and BOTH were orphans.
#: Named rather than deleted: they are reviewed artefacts of someone
#: else's wave and the decision to remove them is not one session's to
#: take. The list is CLOSED, so a fifth orphan fails instead of joining
#: quietly.
ORPHANED_GOLDENS: dict[str, str] = {
    # Empty on purpose, and it must STAY a declared list: the check
    # above fails on any new orphan, so emptiness here is a measured
    # state rather than an absent feature. Two entries left by gaining a
    # program (2026-08-12); two left by deletion, same day.
}

#: The goldens that existed before the convention of 2026-08-12 and
#: have not since been regenerated. Two names LEFT this list on
#: 2026-08-12 when they gained a program and were re-frozen — the
#: ledger's own 'declared BOTH' check is what caught them still
#: sitting here after the move.
#: Being here means EXACTLY "predates the convention" — it is NOT a review
#: and confers no certification. Named one by one on purpose: silence must
#: never be readable as approval.
PREDATES_CONVENTION: frozenset[str] = frozenset({
    "analysis_loads",
    "analysis_path_of_travel",
    "arch_ceiling",
    "arch_ceiling_contour",
    "arch_railing_hosted",
    "arch_railing_path",
    "authoring_stairs_landing",
    "authoring_stairs_run",
    "authoring_stairs_spiral",
    "authoring_stairs_straight",
    "authoring_wall_arc",
    "authoring_wall_pipe_grid",
    "datums_extrusion_roof",
    "datums_multi_segment_grid",
    "datums_multistory_stairs",
    "detail_filled_region_doc_default",
    "detail_filled_region_named_type",
    "full_house_v1",
    "hosted_door_flips",
    "list_walls_level1",
    "mep_conduit_and_placeholders",
    "mep_flex_runs",
    "mixed_program",
    "opening_contour_perpendicular",
    "opening_contour_vertical",
    "opening_host_face_perpendicular",
    "opening_host_face_vertical",
    "opening_wall_rect",
    "pdf_underlay_count",
    "place_family_placement_kinds",
    "place_family_point_and_curve",
    "room_separator",
    "room_separator_then_room",
    "route_duct_system_tee",
    "route_pipe_system_riser_branch",
    "site_building_pad",
    "site_subregion_hosted",
    "site_topography_surface",
    "site_topography_toposolid",
    "space_mep",
    "stack_two_storeys",
    "struct_beam",
    "struct_foundation_isolated",
    # "struct_foundation_slab" LEFT here on 12.08.2026 — it was
    # re-frozen on a program with two openings and declared in
    # UNREVIEWED_GOLDENS. The entry was removed here in THE SAME motion:
    # the check "declared EXACTLY once" would have gone red had the name
    # stayed on both lists.
    "struct_wall_foundation",
    "sweep_slab_edge_bottom_ref",
    "sweep_slab_edge_top",
    "sweep_wall_horizontal",
    "sweep_wall_vertical_ref",
    "wall_base_offset",
})

from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


class Golden(unittest.TestCase):
    def test_multistory_stairs_refuses_the_unbindable_net48_lane(self):
        prog = dict(PROGRAMS["datums_multistory_stairs"])
        prog.pop("__ver__", None)
        for ver in ("2021", "2022", "2023", "2024"):
            with self.subTest(revit_version=ver):
                out = compile_program(
                    prog, revit_version=ver, snapshot=GROUND_SNAPSHOT)
                self.assertFalse(out.ok)
                # THE REFUSAL CODE IS E003, AND THIS IS NOT A FIT TO MAKE
                # IT GREEN.
                #
                # The file arrived via the 16.08 merge from the prod
                # line, where KIR-E001 used to stand here. On our branch
                # the same refusal has been reclassified as KIR-E003
                # ("the operation honestly says: it does not exist on
                # this version"), and the authority for this is not an
                # opinion but THE GATE: the table
                # gate_runner.E003_EXPECTED_BELOW holds
                # "datums_multistory_stairs": "2025", meaning below 2025
                # the gate EXPECTS exactly E003 and is green on it
                # (measured 16.08 after the merge: 2048 live compilation
                # checks, 0 refusals).
                #
                # The test's assertion has not weakened from the code
                # change: it still requires a REFUSAL and empty C#,
                # meaning it catches exactly what it was written for — a
                # silent emission of an unbindable run.
                self.assertIn("KIR-E003", [d.code for d in out.diagnostics])
                self.assertFalse(out.csharp)

    def test_golden(self):
        update = os.environ.get("KIR_UPDATE_GOLDEN") == "1"
        for name, prog in PROGRAMS.items():
            with self.subTest(name=name):
                # The emission version is a property OF THE PROGRAM, not
                # of the whole corpus (09.08). Before the loads wave, all
                # references were built on 2026 by default, because
                # every earlier operation exists there. A free load on
                # 2026 honestly REFUSES, and a reference for its emission
                # can only exist on a version where the emission exists.
                ver = prog.get("__ver__", "2026")
                prog = {k: v for k, v in prog.items() if k != "__ver__"}
                snap = GROUND_SNAPSHOT if name in (
                    # duct_min/roof_min ground `level` by element_id, so
                    # they need the snapshot the determinism check used —
                    # without it create_duct refuses, and create_roof would
                    # silently pin a DIFFERENT emission than the one that
                    # was verified.
                    "duct_min", "roof_min", "auth_move_and_change_type",
                    "auth_annotation",
                    "auth_contour_l",
                    "auth_curtain_cell_named_type",
                    "auth_curtain_grid_lines",
                    "auth_directshape_tower",
                    "auth_face_wall_existing_mass",
                    "auth_pipe_system_chain",
                    "struct_area_reinforcement_slabs",
                    "struct_framing_bay",
                    "authoring_wall_pipe_grid", "authoring_wall_arc",
                    "full_house_v1",
                    "route_pipe_system_riser_branch", "route_duct_system_tee",
                    "struct_beam", "struct_foundation_isolated", "struct_foundation_slab",
                    "struct_foundation_slab_two_holes",
                    "struct_wall_foundation",
                    "hosted_door_flips", "wall_base_offset", "wall_top_attached",
                    "native_group", "place_family_point_and_curve",
                    "arch_ceiling", "arch_ceiling_contour",
                    "authoring_stairs_straight", "authoring_stairs_spiral",
                    "arch_railing_path", "arch_railing_hosted",
                    "room_separator",
                    "space_mep",
                    "place_family_placement_kinds",
                    "authoring_stairs_landing",
                    "room_separator_then_room",
                    "mep_conduit_and_placeholders", "mep_flex_runs",
                    "analysis_loads", "analysis_path_of_travel",
                    # wave/site: the level and the terrain/pad types are
                    # grounded against the shared fixture — the wave has
                    # no snapshot copy of its own (lesson of 16.07: a
                    # private copy makes a run unreproducible from HEAD).
                    "site_topography_surface", "site_topography_toposolid",
                    "site_building_pad", "site_subregion_hosted",
                    # wave/sweep: the same considerations — the host,
                    # the level, and the profile types are grounded
                    # against the SHARED fixture.
                    "sweep_wall_horizontal", "sweep_wall_vertical_ref",
                    "sweep_slab_edge_top", "sweep_slab_edge_bottom_ref",
                    "datums_multi_segment_grid", "datums_extrusion_roof",
                    "datums_multistory_stairs",
                    # wave/detail: the fill type is grounded against
                    # the shared fixture; the document-default branch
                    # reads the snapshot too (an empty `type` passes
                    # through ground as doc_default).
                    "detail_filled_region_named_type",
                    "detail_filled_region_doc_default",
                    # Э3.1 (19.08): a column with a TOP ATTACHMENT.
                    # The levels are grounded against the shared fixture
                    # — without the snapshot, `top_level` does not get
                    # grounded, the emitter does not print the top
                    # branch at all, and the reference would pin exactly
                    # the darkness it was set up to catch.
                    "struct_column_top_constrained",
                ) else None
                out = compile_program(prog, revit_version=ver, snapshot=snap)
                self.assertTrue(out.ok, name)
                path = GOLDEN_DIR / f"{name}.golden.cs"
                if update:
                    path.write_text(out.csharp, encoding="utf-8")
                    continue
                self.assertTrue(path.exists(),
                                f"{path} missing — run once with KIR_UPDATE_GOLDEN=1 and review")
                self.assertEqual(path.read_text(encoding="utf-8"), out.csharp,
                                 f"{name}: emit drifted from reviewed golden "
                                 f"(intentional? update via KIR_UPDATE_GOLDEN=1 + review)")


if __name__ == "__main__":
    unittest.main()


class GoldenLedger(unittest.TestCase):
    """Silence must never be readable as approval.

    A golden frozen from today's emission proves the bytes have not
    CHANGED; it proves nothing about whether they are RIGHT. Recording
    that in prose fails the moment prose is the only thing recording it —
    a golden added next week with no entry would read as reviewed by
    default. So the list is CLOSED: every file in the directory is either
    declared unreviewed or declared to predate the convention, and a new
    one lands in neither, which fails here.
    """

    def _on_disk(self) -> set[str]:
        return {p.name[:-len(".golden.cs")]
                for p in GOLDEN_DIR.glob("*.golden.cs")}

    def test_the_subtest_total_decomposes_into_two_registers(self):
        """The gate's safety net stood on an unverified assumption. Here
        it is made LIVE.

        The rule used to be: "the number of subtests in this file
        changed — so `PROGRAMS` drifted". It only holds under "one
        program = one subtest", and it stopped holding the day a SECOND
        `subTest` loop appeared in the file. Measured on 2026-08-13
        while merging four lines:

            gate baseline     82 = PROGRAMS 67 + UNREVIEWED_GOLDENS 15
            merged line       86 = PROGRAMS 69 + UNREVIEWED_GOLDENS 17

        The +4 delta was **+2 programs AND +2 entries**, and the rule
        would have sent you looking for four names where there were two.

        AN UNVERIFIED PROXY INSIDE A SAFETY NET LIVES LONGER THAN ONE
        INSIDE A NUMBER: a number gets re-checked, while a safety net is
        trusted by construction — that is exactly why it was set up, so
        nobody has to think. So the assumption no longer lives in
        someone's head: this test FAILS as soon as a third source of
        subtests appears, and it fails while pointing out that the rule
        needs rewriting, not patching.

        What must be compared is the MAKEUP — the `PROGRAMS` names and
        the `UNREVIEWED_GOLDENS` keys, each separately — not their sum.
        """
        sources = {"PROGRAMS": len(PROGRAMS),
                   "UNREVIEWED_GOLDENS": len(UNREVIEWED_GOLDENS)}
        for name, n in sources.items():
            with self.subTest(register=name):
                self.assertGreater(n, 0, f"{name} пуст — счёт вырожден")

        # THE RULE WAS REWRITTEN FOR A NEW SOURCE (the 16.08 merge),
        # rather than patched by number — the guard's own text demanded
        # this, and it was right to.
        #
        # The previous edition counted ITEMS: `loops == len(sources) + 1`.
        # The merge brought a fourth loop in from the prod line —
        # `subTest(revit_version=…)` in
        # `test_multistory_stairs_refuses_the_unbindable_net48_lane` —
        # and the count broke, as intended. But fixing it by count
        # ("expected 4") would have brought back exactly the blindness
        # this guard was written against: the next source would again
        # become a nameless number.
        #
        # Now what is compared is the MAKEUP OF NAMES, not a quantity.
        # Every source of subtests must be NAMED here along with its
        # reason; the appearance of an unnamed one fails the test while
        # naming it, not with arithmetic. This makes the guard stricter:
        # it catches both an addition and a DISAPPEARANCE.
        declared_sources = {
            "register": "этот тест: по одному субтесту на регистр",
            "name": "test_golden: по одному субтесту на программу PROGRAMS",
            "golden": "непроверенные эталоны: по одному на ключ "
                      "UNREVIEWED_GOLDENS",
            "revit_version": "multistory-stairs на net48-полосе: по одному "
                             "субтесту на версию 2021-2024 (пришло сводом "
                             "16.08 из прод-линии)",
        }
        found = set(re.findall(r"with self\.subTest\((\w+)=",
                               pathlib.Path(__file__).read_text(encoding="utf-8")))
        unnamed = sorted(found - set(declared_sources))
        vanished = sorted(set(declared_sources) - found)
        self.assertFalse(
            unnamed or vanished,
            f"состав источников субтестов изменился: безымянные {unnamed}, "
            f"исчезнувшие {vanished}. Правило «субтесты => состав» держится "
            f"ИМЕНАМИ: назови новый источник в `declared_sources` вместе с "
            f"причиной либо убери исчезнувший. Подгонять число нечего — его "
            f"здесь больше нет.")

        loops = len(re.findall(r"with self\.subTest\(",
                               pathlib.Path(__file__).read_text(encoding="utf-8")))
        self.assertEqual(
            loops, len(declared_sources),
            "число ЦИКЛОВ субтестов разошлось с числом НАЗВАННЫХ источников "
            f"(циклов {loops}, названо {len(declared_sources)} — по одному на "
            f"регистр плюс этот тест). Сумма субтестов больше не раскладывается "
            f"на {sorted(sources)}; правило «субтесты => состав» надо ПЕРЕПИСАТЬ "
            "под новый источник, а не подогнать число.")

    def test_every_golden_is_declared_exactly_once(self):
        on_disk = self._on_disk()
        self.assertTrue(on_disk, "golden directory is empty — this test "
                                 "would pass vacuously")
        declared = set(UNREVIEWED_GOLDENS) | PREDATES_CONVENTION

        undeclared = sorted(on_disk - declared)
        self.assertFalse(undeclared, (
            "golden(s) in neither UNREVIEWED_GOLDENS nor "
            f"PREDATES_CONVENTION: {undeclared}. A new golden must SAY "
            "which it is — absence of an entry is not a review."))

        missing = sorted(declared - on_disk)
        self.assertFalse(missing, (
            f"declared golden(s) with no file: {missing} — the ledger "
            "outlived its artefact"))

        both = sorted(set(UNREVIEWED_GOLDENS) & PREDATES_CONVENTION)
        self.assertFalse(both, (
            f"golden(s) declared BOTH unreviewed and predating: {both} — "
            "the two mean different things and cannot both hold"))

    def test_unreviewed_entries_say_what_they_do_not_pin(self):
        """The half that stops a golden being mistaken for a certificate.

        A golden over a VERTICAL column read green while the slanted
        branch was dark. Naming what a fixture leaves uncovered is what
        keeps the next reader from inheriting that illusion.
        """
        for name, note in sorted(UNREVIEWED_GOLDENS.items()):
            with self.subTest(golden=name):
                self.assertIn("does NOT pin", note)
                self.assertRegex(note, r"^\d{4}-\d{2}-\d{2};")

    def test_every_golden_file_has_a_program_to_compare_against(self):
        """The third axis: a file with no PROGRAM is compared to NOTHING.

        `test_golden` iterates PROGRAMS. A golden whose program was
        renamed or removed stays on disk, is never read, and reads as
        coverage to any grep — which is precisely how two censuses of the
        same directory disagreed. My own ledger missed it because
        PREDATES_CONVENTION was SEEDED FROM THE DIRECTORY LISTING, so the
        orphans were declared by construction: a list closed on one axis
        and open on another.
        """
        on_disk = self._on_disk()
        # THIS CHECK'S PREMISE WAS TRUE YESTERDAY AND FALSE TODAY
        # (13.08.2026), and the correction follows exactly the canon's
        # first remedy — ask THE AUTHORITY, not one of its sources.
        #
        # The docstring above says «`test_golden` iterates PROGRAMS», and
        # the whole orphan count stood on that. But `PROGRAMS` is NOT the
        # only corpus checking files in this directory: `test_annotation`
        # declares its own `ANNOTATION_PROGRAMS` and checks two goldens
        # against it, and `test_families` used to do the same for two
        # others, until its duplicate was removed. Measured: 71 files,
        # 71 owners, 0 collisions — of which 69 belong to `test_golden`,
        # 2 to `test_annotation`.
        #
        # Under the old denominator, two LEGITIMATELY checked files read
        # as orphans, and the "fix" would have consisted of declaring an
        # orphan something that is not one — that is, writing an untruth
        # into the registry for the sake of green.
        from kir.tests.test_golden_files_have_one_owner import _claims
        compared = {name for name, owners in _claims().items() if owners}
        orphans = sorted(on_disk - compared - set(ORPHANED_GOLDENS))
        self.assertFalse(orphans, (
            f"golden file(s) no corpus compares: {orphans}. Nothing "
            "compares them, so they can never fail. Give them a program "
            "or declare them in ORPHANED_GOLDENS with the reason."))

        healed = sorted(set(ORPHANED_GOLDENS) & compared)
        self.assertFalse(healed, (
            f"declared orphan(s) that now HAVE a program: {healed} — "
            "remove them from ORPHANED_GOLDENS, they are live again"))
