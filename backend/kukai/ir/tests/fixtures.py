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
    "levels": [{"id": 42, "name": "Этаж 1"}, {"id": 43, "name": "Этаж 2"}],
    "wall_types": [{"id": 100, "name": "Кирпич 250"}, {"id": 101, "name": "ЖБ 200"}],
    "pipe_types": [{"id": 200, "name": "Стандарт"}],
    "piping_system_types": [{"id": 300, "name": "ХВС"}],
    "floor_types": [{"id": 400, "name": "Монолит 200"}],
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
    # wave/arch (2026-07-29): create_ceiling/create_railing. Свежий id-блок
    # 1200+ (каркас занял 1100-1101) — ни один существующий ключ не тронут.
    # РОВНО ПО ОДНОЙ записи в каждом: у обеих операций нет типа по умолчанию
    # (create_railing — по построению, ElementTypeGroup.RailingType не
    # существует; create_ceiling — по решению, см. ops_arch.py), поэтому
    # пропущенный `type` разрешается общим правилом «единственный в пуле».
    # Второй тип здесь молча превратил бы каждую такую программу в
    # AMBIGUOUS — тест на неоднозначность добавляет его сам, локально.
    "ceiling_types": [{"id": 1200, "name": "Потолок подвесной 600x600"}],
    "railing_types": [{"id": 1201, "name": "Ограждение 900"}],
}
