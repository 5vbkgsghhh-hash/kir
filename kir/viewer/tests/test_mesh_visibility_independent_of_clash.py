"""Authored display triangles are not gated by the clash category table."""
from __future__ import annotations

import copy
import json
import struct

import pytest

from kir.ops_shape import DIRECTSHAPE_CATEGORIES
from kir.viewer import graph
from kir.viewer.codec import SCENE_MAGIC
from kir.viewer.live_scene import scene_from_programs


VAULT = {
    "vertices_mm": [[0, 0, 0], [4000, 0, 0], [4000, 3000, 0], [0, 3000, 0],
                    [0, 1500, 2000], [4000, 1500, 2000]],
    "triangles": [[0, 1, 4], [1, 5, 4], [1, 2, 5], [2, 3, 5], [3, 4, 5],
                  [0, 4, 3], [0, 3, 2], [0, 2, 1]],
}


#: 🔴 THE EXAMPLE IS STALE, THE SUBJECT OF THE TEST IS NOT (06.09.2026).
#: The file asks "is the author's mesh shown for a category that clash
#: does NOT build a shell for". `mass` used to serve as the example, but
#: `OST_Mass` entered `hulls.KIND_TABLE`, and the example stopped being
#: an example: a mass now HAS a shell. Measured against the
#: `ops_shape.DIRECTSHAPE_CATEGORIES` registry (6 kinds): exactly two
#: remain outside the table — `entourage` (OST_Entourage) and `site`
#: (OST_Site); `generic_model`, `furniture`, `specialty_equipment` are
#: in the table. `entourage` was taken. The meaning of the test has not
#: changed in a single line.
def operation(category="entourage", ident="vault", mesh=None):
    return {"op": "create_directshape", "id": ident, "name": "Authored vault",
            "category": category, "mesh": copy.deepcopy(VAULT if mesh is None else mesh)}


def decode(ops, **kwargs):
    blob, meta = scene_from_programs([
        {"ir_version": "1.0", "intent": "offline display", "ops": ops}], **kwargs)
    at = len(SCENE_MAGIC) + 4
    size = struct.unpack_from("<I", blob, len(SCENE_MAGIC))[0]
    header = json.loads(blob[at:at + size])
    start = at + size
    streams = {entry["name"]: blob[start + entry["offset"]:start + entry["offset"] + entry["length"]]
               for entry in header["buffers"]}
    return header, meta, streams


@pytest.mark.parametrize("category", DIRECTSHAPE_CATEGORIES)
def test_every_legal_category_displays_its_actual_triangles(category):
    header, meta, streams = decode([operation(category)], first_position=7)
    assert header["counts"]["mesh"] == meta["mesh_shown"] == 1
    assert header["counts"]["mesh_vertices"] == 6
    assert header["counts"]["mesh_triangles"] == 8
    assert header["counts"]["box"] == header["counts"]["capsule"] == header["counts"]["prism"] == 0
    assert header["elements"] == 1 and streams["ids"].decode() == "p7/vault"
    assert header["categories"] == [DIRECTSHAPE_CATEGORIES[category]]
    assert streams["elem_existence"] == bytes([graph.EXISTENCE_CODE["planned"]])
    origin = header["origin_mm"]
    actual = [[point[i] + origin[i] for i in range(3)]
              for point in struct.iter_unpack("<3f", streams["mesh_vtx"])]
    assert actual == VAULT["vertices_mm"]
    assert list(struct.iter_unpack("<3I", streams["mesh_tri"])) == [tuple(t) for t in VAULT["triangles"]]


def test_mesh_only_origin_comes_from_authored_vertices():
    mesh = copy.deepcopy(VAULT)
    mesh["vertices_mm"] = [[x + 500_000, y - 700_000, z + 9000] for x, y, z in mesh["vertices_mm"]]
    header, meta, _ = decode([operation(mesh=mesh)])
    assert header["origin_mm"] == [502_000, -698_500, 9000]
    assert meta["origin_far_mm"] == 2000 and not meta["origin_overflow"]


def test_fixed_origin_remains_authoritative_for_a_delta():
    fixed = (100, 200, 300)
    header, meta, streams = decode([operation()], origin_mm=fixed, first_position=9, whole=False)
    assert header["origin_mm"] == list(fixed)
    assert next(struct.iter_unpack("<3f", streams["mesh_vtx"])) == (-100, -200, -300)
    assert streams["ids"].decode() == "p9/vault"
    assert meta["origin_far_mm"] == 3900


def test_large_world_coordinates_are_allowed_when_relative_mesh_fits():
    mesh = copy.deepcopy(VAULT)
    mesh["vertices_mm"] = [[1e40 + x * 1e30, y, z] for x, y, z in mesh["vertices_mm"]]
    header, meta, streams = decode([operation(mesh=mesh)])
    assert header["counts"]["mesh"] == 1 and not meta["mesh_refused"]
    origin = header["origin_mm"]
    for actual, point in zip(struct.iter_unpack("<3f", streams["mesh_vtx"]), mesh["vertices_mm"]):
        assert actual == pytest.approx([point[i] - origin[i] for i in range(3)])


def test_display_reconciliation_does_not_claim_clash_coverage():
    header, meta, _ = decode([operation()], session_key=("independent-mesh", "entourage"))
    assert meta["mesh_shown"] == 1 and meta["bodies"] == 0
    assert meta["bodies_scope"] == meta["blind_scope"] == "clash_hulls"
    assert meta["display_bodies"] == meta["display_meshes_without_clash_hull"] == 1
    assert meta["reconcile"]["buckets"] == {"scene_only": 1}
    assert meta["reconcile"]["balanced"]
    assert "clash" in meta["bodies_ru"]
    assert "тел не будет ни у чего" not in meta["sections_ru"]
    assert "тела не создаёт вовсе" not in meta["blind_class_ru"]["never_a_body"]
    assert meta["display_fidelity_scope"] == "authored_mesh_not_native_bim"
    assert header["display_meshes_without_clash_hull"] == 1


BAD_MESHES = [
    {"vertices_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "triangles": [[0, 1, 99]]},
    {"vertices_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "triangles": [[0, 1.5, 2]]},
    {"vertices_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "triangles": [[False, 1, 2]]},
    {"vertices_mm": [[float("nan"), 0, 0], [1, 0, 0], [0, 1, 0]], "triangles": [[0, 1, 2]]},
    {"vertices_mm": [[float("inf"), 0, 0], [1, 0, 0], [0, 1, 0]], "triangles": [[0, 1, 2]]},
    {"vertices_mm": [[False, 0, 0], [1, 0, 0], [0, 1, 0]], "triangles": [[0, 1, 2]]},
    {"vertices_mm": [[0, 0], [1, 0, 0], [0, 1, 0]], "triangles": [[0, 1, 2]]},
    {"vertices_mm": [], "triangles": []},
    {"vertices_mm": "not vertices", "triangles": "not triangles"},
]


@pytest.mark.parametrize("mesh", BAD_MESHES)
def test_invalid_out_of_clash_mesh_is_named_and_does_not_leak_into_next_mesh(mesh):
    fixed = (100, 200, 300)
    bad, good = operation(ident="bad", mesh=mesh), operation(ident="good")
    header, meta, streams = decode([bad, good], origin_mm=fixed)
    control, _, control_streams = decode([good], origin_mm=fixed)
    assert meta["mesh_refused"] == {"ValueError": 1}
    assert meta["mesh_refusal_details"]["p1/bad"]["code"] == "invalid_display_mesh"
    assert meta["mesh_refused"], "an explicit but unreadable mesh cannot silently disappear"
    assert header["counts"] == control["counts"]
    assert header["elements"] == 1 and streams["ids"].decode() == "p1/good"
    for name in ("mesh_vtx", "mesh_tri", "mesh_ofs", "mesh_vofs"):
        assert streams[name] == control_streams[name]


def test_unrepresentable_relative_mesh_coordinates_are_not_clamped_to_zero():
    huge = copy.deepcopy(VAULT)
    huge["vertices_mm"][0][0] = 1e40
    header, meta, _ = decode([operation(mesh=huge)], origin_mm=(0, 0, 0))
    assert header["counts"]["mesh"] == 0
    assert meta["mesh_refused"] == {"ValueError": 1}


#: Here BOTH kinds remain fitting even after the move: this test is
#: about an unrepresentable mesh, not about the absence of a shell.
#: `entourage` was added as the third — that very example outside the
#: table, so that the "no shell" case remains covered here too.
@pytest.mark.parametrize("category", ["mass", "generic_model", "entourage"])
@pytest.mark.parametrize("origin", [None, (0, 0, 0)])
def test_intrinsically_unrepresentable_mesh_cannot_poison_other_display_objects(category, origin):
    huge = copy.deepcopy(VAULT)
    huge["vertices_mm"][0][0] = 1e40
    good = operation(ident="good")
    header, meta, streams = decode(
        [operation(category, "bad", huge), good], origin_mm=origin,
        session_key=("unrepresentable-display", f"{category}-{origin}"))
    control, _, control_streams = decode([good], origin_mm=origin)
    assert header["origin_mm"] == control["origin_mm"]
    assert header["counts"] == control["counts"]
    assert streams["ids"].decode() == "p1/good"
    assert meta["display_bodies"] == meta["mesh_shown"] == 1
    assert meta["mesh_refused"] == {"ValueError": 1}
    assert meta["mesh_refusal_details"]["p1/bad"]["code"] == "invalid_display_mesh"
    assert meta["reconcile"]["buckets"] == {"scene_only": 1, "neither": 1}
    for name in ("mesh_vtx", "mesh_tri", "mesh_ofs", "mesh_vofs"):
        assert streams[name] == control_streams[name]


def test_clash_hull_fallback_and_valid_mesh_are_not_duplicated():
    bad = operation("generic_model", "bad", BAD_MESHES[0])
    header, meta, streams = decode([bad, operation("generic_model", "good")])
    assert header["counts"]["box"] == header["counts"]["mesh"] == 1
    assert header["elements"] == 2
    assert set(streams["ids"].decode().splitlines()) == {"p1/bad", "p1/good"}
    assert meta["display_bodies"] == 2 and meta["display_meshes_without_clash_hull"] == 0
