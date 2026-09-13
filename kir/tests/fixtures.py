"""Shared committed test fixtures — ONE ground snapshot for unit tests,
goldens and the gate runner (the ir_defaults discipline: a fixture duplicated
per-harness silently diverges, and a gate run stops being reproducible from
the committed state — the 2026-07-16 checkpoint-return lesson)."""

GROUND_SNAPSHOT = {
    # Every live write snapshot is bound to one active document.  Tests use a
    # stable synthetic identity; serving refuses a write before compilation if
    # this field is absent or unbound.
    "__document_fingerprint": {
        "title": "KIR Test Model",
        "path_name": r"C:\models\kir-test.rvt",
        "project_uid": "kir-test-project-uid",
    },
    # `elevation_mm` has been arriving from the live collector since
    # 09.08.2026 (the sections wave, `open_model.GROUND_SNAPSHOT_CS`:
    # `__r["elevation_mm"] = __MM(__lvl.Elevation)`), and the fixture was
    # not carrying it — i.e. it was describing a bridge that no longer
    # exists. An instrument covering part of the range is more dangerous
    # than a missing one: without these numbers, addressing from an
    # element (`z: "base"|"top"`) would fail tests as a "capture gap" on a
    # snapshot that is complete in prod. The elevations are the same
    # 0/3300 used in the course examples.
    "levels": [{"id": 42, "name": "Этаж 1", "elevation_mm": 0.0},
               {"id": 43, "name": "Этаж 2", "elevation_mm": 3300.0}],
    "wall_types": [{"id": 100, "name": "Кирпич 250"}, {"id": 101, "name": "ЖБ 200"}],
    "pipe_types": [{"id": 200, "name": "Стандарт"}],
    "piping_system_types": [{"id": 300, "name": "ХВС"}],
    "floor_types": [{"id": 400, "name": "Монолит 200"}],
    # The fixture had no roofs, and `create_roof`/`create_extrusion_roof`
    # ground their type on `roof_types` — meaning by default they were
    # grounding to NOTHING in the suite, and any corpus where a roof stood
    # next to other ops failed with `KIR-G104: roof_types: empty in model`.
    # The red was read as a defect in the group path, but it was a defect
    # of the MODEL it was measured against. Measured 12.08.2026: there are
    # 34 pools that at least one op grounds against; exactly one was
    # missing. The pin for this sits in
    # `test_ground_snapshot_covers_every_pool.py` — the count matched
    # (35 = 35), the NAMES diverged.
    "roof_types": [{"id": 1234, "name": "Кровля 200"}],
    # MATERIALS — set up on 2026-08-13 together with the `set_param`
    # reference value. The pool is not there for completeness: it moves
    # the material-name check from EXECUTION to AUTHORING. Before it, the
    # only path to a material (`create_type`) was resolving the name with
    # the collector INSIDE the transaction — an honest, typed refusal, but
    # one arriving where the loop costs the most. It was set up AT THE
    # SAME TIME as its consumer, not ahead of it: a pool without a
    # consumer is green and proves nothing.
    # Two entries, not one, DELIBERATELY: at cardinality 1, "the correct
    # one was chosen" would be proven merely by the absence of a second
    # candidate.
    "materials": [{"id": 1300, "name": "Бетон М300"},
                  {"id": 1301, "name": "Кирпич керамический"}],
    # PHASES — set up on 2026-08-13, the second reference genus after
    # material. The order was chosen by what hurts the MODEL: every real
    # project is phased, and an element placed in the wrong phase does not
    # show up on the views it should — the building LOOKS built and is
    # not.
    # Cardinality 2 for the same reason as materials: with a single phase,
    # "the correct one was chosen" would be proven merely by the absence
    # of a second.
    "phases": [{"id": 1400, "name": "Существующие"},
               {"id": 1401, "name": "Новая конструкция"}],
    # WORKSETS. `id` here is an INTEGER (`WorksetId.IntegerValue`), not an
    # `ElementId`: `Workset` does not inherit from `Element`, and
    # `Parameter.Set(WorksetId)` does not exist on any of the six versions
    # (CS1503, measured by the GATE on 13.08). So a workset is NOT a third
    # reference genus, but its own mechanism, with `Set(int)` for writing
    # and `AsInteger()` as the witness.
    "worksets": [{"id": 0, "name": "Общие уровни и оси"},
                 {"id": 1, "name": "АР_Стены"}],
    # Whether the document is workshared is a SEPARATE fact, not a
    # consequence of a non-empty pool: a non-workshared document gives an
    # empty pool, and "there are no worksets" must be distinguished from
    # "we did not ask."
    "worksets__workshared": True,
    "column_symbols_structural": [{"id": 500, "name": "К 300x300"}],
    "column_symbols_architectural": [{"id": 501, "name": "Колонна 300"}],
    "window_symbols": [{"id": 600, "name": "Окно 1200x1500"}],
    "door_symbols": [{"id": 700, "name": "Дверь 900x2100"}],
    "family_symbols": [{
        "id": 800,
        "name": "Стол 1200",
        "category": "OST_Furniture",
        "family_name": "Стол офисный",
        "type_name": "Стол 1200",
    }],
    # CONTOUR anchors: grids with geometry (id/name/endpoints in mm)
    "grids": [
        {"id": 900, "name": "1", "p0_mm": [0, -1000], "p1_mm": [0, 9000]},
        {"id": 901, "name": "2", "p0_mm": [4000, -1000], "p1_mm": [4000, 9000]},
        {"id": 902, "name": "А", "p0_mm": [-1000, 0], "p1_mm": [17000, 0]},
        {"id": 903, "name": "Б", "p0_mm": [-1000, 4500], "p1_mm": [17000, 4500]},
    ],
    # wave/mep (2026-07-17): these three pools were referenced by
    # create_duct/create_cable_tray's OpSpec.grounded since v1.1 (and
    # registry_base.py's known_pools already lints them) but were never
    # actually populated in this shared fixture — a real gap, additive fix
    # (fresh id block 1000+, no existing key touched) so route_duct_system
    # (and create_duct/create_cable_tray) can ground in tests/goldens/gate.
    "duct_types": [{"id": 1000, "name": "Прямоугольный стандарт"}],
    "duct_system_types": [{"id": 1001, "name": "Приточная"}],
    "cable_tray_types": [{"id": 1002, "name": "Лоток стандарт"}],
    # wave/struct (2026-07-17): create_beam/create_foundation pools. Fresh
    # id-block 1100+ (mep's own additive block already used 1000-1002) — no
    # existing key touched, additive only.
    "beam_types": [{"id": 1100, "name": "Балка 200x400"}],
    "foundation_symbols": [{"id": 1101, "name": "Фундамент 1500x1500"}],
    # wave/arch (2026-07-29): create_ceiling/create_railing. A fresh id
    # block, 1200+ (framing took 1100-1101) — not a single existing key
    # touched. EXACTLY ONE entry each: neither operation has a default
    # type (create_railing — by construction,
    # ElementTypeGroup.RailingType does not exist; create_ceiling — by
    # decision, see ops_arch.py), so the omitted `type` is resolved by the
    # general "sole entry in the pool" rule. A second type here would
    # silently turn every such program AMBIGUOUS — the ambiguity test adds
    # it itself, locally.
    "ceiling_types": [{"id": 1200, "name": "Потолок подвесной 600x600"}],
    "railing_types": [{"id": 1201, "name": "Ограждение 900"}],
    # wave/wall-foundation (2026-08-09): create_wall_foundation. A fresh id
    # block, 1300+ (architecture took 1200-1201). TWO entries, not one,
    # and this is deliberate: for this op, an omitted `type` goes to the
    # DOCUMENT's default type, not to the "sole entry in the pool" rule,
    # so a single entry would make both branches indistinguishable in
    # tests — the second type is exactly the proof that the default
    # branch has not slid over into sole_entry.
    "wall_foundation_types": [{"id": 1300, "name": "Ленточный 600x300"},
                              {"id": 1301, "name": "Ленточный 900x400"}],
    # wave/mep-electrical (2026-08-09): an electrical conduit box and two
    # flexible types. A fresh id block, 1400+ — not a single existing key
    # touched. THE BLOCK WAS SHIFTED DURING THE 09.08 MERGE: the wave was
    # written in parallel with the strip foundation, and both took 1300+
    # independently, meaning the same id would have been both a
    # WallFoundationType and a ConduitType at once. In Revit, an id is
    # unique per document, and this snapshot is ONE document (the module's
    # header), so the blocks diverge, not the rule. EXACTLY ONE entry each,
    # for the same reason as the ceiling and the railing: none of the
    # three ops has a default type in our emitter, so the omitted selector
    # is resolved by the general "sole entry in the pool" rule, and a
    # second type would silently turn every such program into KIR-G102.
    # The ambiguity test adds it itself, locally.
    "conduit_types": [{"id": 1400, "name": "Короб жёсткий металлический"}],
    "flex_duct_types": [{"id": 1401, "name": "Гибкий воздуховод круглый"}],
    "flex_pipe_types": [{"id": 1402, "name": "Гибкая труба"}],
    # wave/analysis (2026-08-09): load cases and three load types. A fresh
    # id block, 1500+ — not a single existing key touched.
    #
    # FOR THE TYPES — EXACTLY ONE entry each, for the same reason as the
    # ceiling, the railing, and the flexibles: there is no default load
    # type in the API (`ElementTypeGroup` contains neither PointLoadType,
    # nor LineLoadType, nor AreaLoadType), so an omitted `load_type` is
    # resolved by the general "sole entry in the pool" rule, and a second
    # type would silently turn every such program into KIR-G102. The
    # ambiguity test adds it itself, locally.
    #
    # FOR LOAD CASES — TWO, and this is a deliberately opposite decision:
    # `load_case` is declared mandatory, i.e. the author always names it,
    # and a single entry would make "name resolution worked" and "the
    # sole-entry-in-the-pool rule fired" indistinguishable — and that rule
    # does not even apply to a mandatory parameter. Two cases are also a
    # truth about the domain itself: loads never exist without
    # combinations.
    "load_cases": [{"id": 1500, "name": "ДЛ1 Собственный вес"},
                   {"id": 1501, "name": "СН1 Снег"}],
    "point_load_types": [{"id": 1502, "name": "Точечная нагрузка 1"}],
    "line_load_types": [{"id": 1503, "name": "Линейная нагрузка 1"}],
    "area_load_types": [{"id": 1504, "name": "Площадная нагрузка 1"}],
    # wave/framing (2026-08-09): create_truss. ONE entry — a truss has no
    # default type in the API at all (ElementTypeGroup.TrussType does not
    # compile on any of the six versions), so the omitted `type` must be
    # resolved by the "sole entry in the pool" rule, and a second type
    # would silently turn every such program into KIR-G102. The ambiguity
    # test adds it itself, locally. create_beam_system has NO pool of its
    # own: its `symbol` is the beam_types above.
    #
    # ID BLOCK 1600, NOT 1500, AND THIS WAS FIXED DURING THE 09.08 MERGE.
    # The framing wave took "a fresh block, 1500+," knowing only about the
    # electrical (1400-1402) — while the analysis wave, the same day, took
    # 1500-1504 by the same reasoning. Both were right on their own and
    # collided together: the fixture models ONE document, and an id in it
    # is unique, so `truss_types` moved on to the next free block of a
    # hundred. Picking a winning side here would have silently fused the
    # truss with the load case «ДЛ1 Собственный вес».
    "truss_types": [{"id": 1600, "name": "Ферма стропильная 12м"}],
    # wave/site (2026-08-09): create_topography(toposolid)/create_building_pad.
    # One entry each, for the same reason as the architecture wave: a
    # toposolid has no default type BY CONSTRUCTION
    # (ElementTypeGroup.ToposolidType does not exist on any version), and
    # the omitted `type` is resolved by the general "sole entry in the
    # pool" rule; a second type would silently turn every such program
    # AMBIGUOUS. A building pad DOES have a document default, and the pool
    # is there for an explicit `by:name`.
    #
    # ID BLOCK 1700, NOT 1300, AND THIS IS THE THIRD SUCH FIX IN ONE DAY.
    # The site wave took "a fresh block, 1300+," knowing only about
    # architecture (1200-1201) — but 1300-1301 was already taken by the
    # strip foundation, 1400-1402 by electrical, 1500-1504 by loads, 1600
    # by the truss. Five waves in a row reasoned identically and
    # correctly, and collided for exactly that reason: each was computing
    # "the next free block" from its OWN slice of the tree. Here that
    # would have given the toposolid the same id as the strip foundation
    # — within one document, where an id is unique.
    "toposolid_types": [{"id": 1700, "name": "Толща рельефа 300"}],
    "building_pad_types": [{"id": 1701, "name": "Площадка 200"}],
    # wave/sweep (2026-08-09): create_wall_sweep / create_slab_edge. ONE
    # entry each, for the same reason as all the pools above: the omitted
    # `type` is resolved by the general "sole entry in the pool" rule, and
    # a second type would silently turn every such program into KIR-G102
    # AMBIGUOUS.
    #
    # ID BLOCK 1800 — AND IT WAS TAKEN NOT AS "THE NEXT FREE ONE," BUT
    # AFTER READING THE WHOLE DICTIONARY. This exact mistake cost the
    # previous five waves three collisions in one day: each was computing
    # "the next free block" from its OWN slice of the tree, and each was
    # right on its own. Here everything up to 1701 inclusive is taken, so
    # 1800.
    #
    # A CORNICE TYPE IS NOT A CLASS, IT IS A CATEGORY, and the fixture must
    # reflect that: `wall_sweep_types` is assembled over
    # OST_Cornices + OST_Reveals as one pool (there is no
    # `WallSweepType`-as-ElementType class in the API at all), so one
    # entry here represents BOTH categories at once, and which
    # {Sweep, Reveal} enum value to pass is derived by the emitter from
    # the resolved element's category, at runtime.
    "wall_sweep_types": [{"id": 1800, "name": "Карниз 200x100"}],
    "slab_edge_types": [{"id": 1801, "name": "Капельник 100x50"}],
    # wave/detail (2026-08-09): create_filled_region. ID BLOCK 1800 — THE
    # NEXT FREE ONE ON THIS TREE, not "a fresh block" from its own slice:
    # exactly the mistake the three comments above were fixing three times
    # in one day. Taken: 1200-1201, 1300-1301, 1400-1402, 1500-1504, 1600,
    # 1700-1701.
    #
    # TWO ENTRIES, not one, and this is substantive, not for completeness:
    # a filled region DOES have a document default
    # (ElementTypeGroup.FilledRegionType, 6/6), so the omitted `type`
    # takes the doc_default branch, NOT "sole entry in the pool." With a
    # one-line pool, both branches would give the same id, and the default
    # golden file would be indistinguishable from the sole_entry golden
    # file — i.e. the test would stop showing the difference it must show.
    "filled_region_types": [{"id": 1800, "name": "Бетон"},
                            {"id": 1801, "name": "Грунт"}],
    # wave/reinforcement (2026-08-10): create_area_reinforcement. ID BLOCK
    # 1900, AND IT WAS TAKEN AFTER READING THE WHOLE DICTIONARY, not "the
    # next free one from its own slice" — exactly the mistake the three
    # comments above were fixing three times in one day. Taken: 1200-1201,
    # 1300-1301, 1400-1402, 1500-1504, 1600, 1700-1701, 1800-1801 (and
    # 1800/1801 are taken TWICE: by both the wall sweep and the filled
    # region — a fourth collision of the same kind, only noted here, not
    # touched).
    #
    # EACH POOL'S CARDINALITY IS CHOSEN FOR THE BRANCH IT MUST
    # DISTINGUISH, not "for completeness":
    #   * `area_reinforcement_types` — TWO entries, like the filled region
    #     and for the same reason: it DOES have a document default
    #     (ElementTypeGroup.AreaReinforcementType, 6/6), so the omitted
    #     `type` takes the doc_default branch, NOT "sole entry in the
    #     pool." With a one-line pool, both branches would give one id,
    #     and the test would stop showing the difference it must show.
    #   * `rebar_bar_types` — ONE: the omitted `bar_type` is resolved by
    #     the general "sole entry in the pool" rule, and a second line
    #     would silently turn every such program into KIR-G102.
    #   * `rebar_hook_types` — TWO, AND THIS IS THE MOST SUBSTANTIVE LINE
    #     IN THE BLOCK. An omitted hook means "NO HOOKS"
    #     (InvalidElementId — a value of the API itself), not "sole entry
    #     in the pool." With a one-entry pool, both laws would give the
    #     same visible outcome, and swapping "no hooks" for "the first
    #     hook that turns up" would slip past the test unnoticed. Two
    #     entries make this difference observable: the general rule here
    #     WOULD HAVE TO refuse with KIR-G102, while the op must build.
    "area_reinforcement_types": [{"id": 1900, "name": "Армирование по области 1"},
                                 {"id": 1901, "name": "Армирование по области 2"}],
    "rebar_bar_types": [{"id": 1902, "name": "Ø12 A500C"}],
    "rebar_hook_types": [{"id": 1903, "name": "Крюк 135"},
                         {"id": 1904, "name": "Крюк 90"}],
}
