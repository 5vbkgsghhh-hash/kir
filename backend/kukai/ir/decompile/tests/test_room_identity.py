"""Room name/number reverse seam stays lossless and unambiguous."""
from __future__ import annotations

from kukai.ir import ground as ground_mod
from kukai.ir.compiler import _parse_and_check, compile_program
from kukai.ir.decompile.extract import build_metadata_cs
from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.materialize import leaves_to_program
from kukai.ir.decompile.reextract import (
    build_room_reextract_cs,
    parse_room_reextract,
)
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
    RoomInfo,
)
from kukai.ir.translation_cert import certify_op


_LEVEL = LevelInfo(id="100", name="Этаж 1", elevation_mm=0.0)
_PROJECT = ProjectInfo(name="P", address=None, building_type_hint=None)


def _room_row(*, room_id: str = "8001", name: str = "Кабинет",
              number: str | None = "101", x: float = 0.0) -> dict:
    row = {
        "id": room_id,
        "name": name,
        "level_id": "100",
        "level_name": "Этаж 1",
        "area_m2": 12.0,
        "boundary_mm": [
            [x, 0.0], [x + 4000.0, 0.0],
            [x + 4000.0, 3000.0], [x, 3000.0],
        ],
        "boundary_loops_mm": [[
            [x, 0.0], [x + 4000.0, 0.0],
            [x + 4000.0, 3000.0], [x, 3000.0],
        ]],
        "bounding_element_ids": [],
    }
    if number is not None:
        row["number"] = number
    return row


def _room_element(room_id: str, x: float) -> L0Element:
    return L0Element(
        element_id=room_id,
        category="OST_Rooms",
        category_ru="Помещения",
        type_id="",
        type_name="Помещение",
        level_id="100",
        level_name="Этаж 1",
        geom_kind=GeometryKind.POINT,
        p0_mm=(x + 2000.0, 1500.0, 0.0),
        p1_mm=None,
        rotation_deg=None,
        bbox_min_mm=(x, 0.0, 0.0),
        bbox_max_mm=(x + 4000.0, 3000.0, 3000.0),
        host_id=None,
        params={},
    )


def _document(rows: list[dict]) -> L0Document:
    rooms = tuple(RoomInfo.from_dict(row) for row in rows)
    elements = tuple(
        _room_element(room.id, float(index * 5000))
        for index, room in enumerate(rooms)
    )
    return L0Document(
        doc_name="rooms",
        revit_version="2023",
        units="mm",
        change_stamp="room-identity",
        levels=(_LEVEL,),
        grids=(),
        rooms=rooms,
        project_info=_PROJECT,
        elements=elements,
    )


def test_legacy_room_wire_remains_unchanged_when_number_was_not_measured():
    legacy = _room_row(number=None)
    room = RoomInfo.from_dict(legacy)

    assert room.number is None
    assert room.to_dict() == legacy


def test_measured_empty_and_whitespace_room_numbers_are_not_collapsed():
    for number in ("", " 101 A "):
        room = RoomInfo.from_dict(_room_row(number=number))
        assert room.number == number
        assert RoomInfo.from_dict(room.to_dict()) == room


def test_whole_and_delta_extractors_read_name_and_number_parameters():
    for body in (build_metadata_cs(), build_room_reextract_cs(["8001"])):
        assert "BuiltInParameter.ROOM_NAME" in body
        assert "BuiltInParameter.ROOM_NUMBER" in body
        assert '__roomRow["name"] = __room.Name' not in body
        assert '__roomRow["number"]' in body


def test_delta_parser_preserves_independent_room_identity_fields():
    room = parse_room_reextract({
        "rooms": [_room_row(name="Зал", number="A-17")],
    })[0]

    assert room.name == "Зал"
    assert room.number == "A-17"


def test_same_names_and_numbers_do_not_merge_during_lift_and_materialize():
    rows = [
        _room_row(room_id="8001", name="Кабинет", number="101", x=0.0),
        _room_row(room_id="8002", name="Кабинет", number="102", x=5000.0),
        _room_row(room_id="8003", name="Переговорная", number="102",
                  x=10000.0),
    ]
    document = _document(rows)

    leaves = lift_document(document)
    lifted = {
        leaf["source_element_id"]: (
            leaf["params"]["name"], leaf["params"]["number"])
        for leaf in leaves
    }
    assert lifted == {
        "8001": ("Кабинет", "101"),
        "8002": ("Кабинет", "102"),
        "8003": ("Переговорная", "102"),
    }

    result = leaves_to_program(leaves, chunk_target=10)
    assert not result.skipped
    materialized = {
        (op["name"], op["number"])
        for program in result.programs
        for op in program["ops"]
        if op["op"] == "create_room"
    }
    assert materialized == set(lifted.values())


def test_forward_room_number_is_exact_and_compiler_witnessed():
    program = {
        "ir_version": "1.0",
        "intent": "room identity round trip",
        "ops": [{
            "op": "create_room",
            "id": "R1",
            "xy": [2000.0, 1500.0],
            "level": {"by": "element_id", "value": 100},
            "name": "Кабинет",
            "number": " 101 A ",
        }],
    }

    out = compile_program(program, revit_version="2023", snapshot=None)

    assert out.ok, [diagnostic.to_dict() for diagnostic in out.diagnostics]
    assert 'Set(" 101 A ")' in out.csharp
    assert "BuiltInParameter.ROOM_NUMBER" in out.csharp
    assert "R1: number mismatch (semantic)" in out.csharp
    assert '__rb["number"]' in out.csharp

    grounded = ground_mod.ground(_parse_and_check(program), None)
    certificate = certify_op(grounded[0], "2023")
    number_clause = next(
        clause for clause in certificate.clauses
        if "Number == number" in clause.clause)
    assert number_clause.required
    assert number_clause.discharged
    assert number_clause.kind == "semantic"
    assert certificate.proven

    program["ops"][0]["number"] = ""
    empty = compile_program(program, revit_version="2023", snapshot=None)
    assert empty.ok, [
        diagnostic.to_dict() for diagnostic in empty.diagnostics]
    assert 'Set("")' in empty.csharp
