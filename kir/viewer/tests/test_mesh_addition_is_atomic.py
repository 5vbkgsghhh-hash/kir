"""A rejected mesh cannot alter the next geometry or its signed scene bytes."""
from __future__ import annotations

from copy import deepcopy
import struct

import pytest

from kir.viewer.codec import SceneBuilder, encode_scene


_VERTICES = [(0, 0, 0), (1000, 0, 0), (0, 1000, 0)]
_TRIANGLES = [(0, 1, 2)]


def _builder(populated: bool = True) -> SceneBuilder:
    builder = SceneBuilder(origin_mm=(100, 200, 300), mesh_vertex_base=12)
    if populated:
        _add_valid_element(builder)
        builder.add_box((0, 0, 0), (1, 1, 1))
    return builder


def _add_valid_element(builder: SceneBuilder) -> None:
    kind, slot = builder.add_mesh(iter(_VERTICES), iter(_TRIANGLES))
    builder.add_element(
        element_id=f"mesh-{slot}", category="generic_model", level="L1",
        trust=1, fidelity=1, label="create_directshape", kind=kind, slot=slot,
        axes=0, authority=0, existence=0, flags=0)


def _assert_unchanged_and_reusable(builder: SceneBuilder,
                                  control: SceneBuilder) -> None:
    # Dataclass equality also covers records, counters and string tables that
    # are not all exposed as serialized streams.
    assert builder == control
    assert encode_scene(builder, {}) == encode_scene(control, {})
    _add_valid_element(builder)
    _add_valid_element(control)
    assert builder == control
    assert encode_scene(builder, {}) == encode_scene(control, {})


@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize(("vertices", "triangles", "error"), [
    (_VERTICES, [(0, 1, 9)], ValueError),
    (_VERTICES, [*_TRIANGLES, (0, 1, -1)], ValueError),
    (_VERTICES, [*_TRIANGLES, (0, 1)], IndexError),
    (_VERTICES, [*_TRIANGLES, (0, 1, "not-an-index")], ValueError),
    (_VERTICES, [*_TRIANGLES, (0, 1, None)], TypeError),
    ([_VERTICES[0], (1, 2)], _TRIANGLES, IndexError),
    ([_VERTICES[0], ("not-a-coordinate", 2, 3)], _TRIANGLES, TypeError),
    ([_VERTICES[0], (1e39, 2, 3)], _TRIANGLES, OverflowError),
])
def test_input_refusal_preserves_every_field_and_next_mesh(
        vertices, triangles, error, populated):
    builder = _builder(populated)
    control = deepcopy(builder)
    with pytest.raises(error):
        builder.add_mesh(vertices, triangles)
    _assert_unchanged_and_reusable(builder, control)


@pytest.mark.parametrize("failing_source", ["vertices", "triangles"])
def test_generator_failure_preserves_every_field_and_next_mesh(failing_source):
    def interrupted(items):
        yield from items
        raise RuntimeError("source interrupted")

    builder = _builder()
    control = deepcopy(builder)
    vertices = (interrupted(_VERTICES) if failing_source == "vertices"
                else iter(_VERTICES))
    triangles = (interrupted(_TRIANGLES) if failing_source == "triangles"
                 else iter(_TRIANGLES))
    with pytest.raises(RuntimeError, match="source interrupted"):
        builder.add_mesh(vertices, triangles)
    _assert_unchanged_and_reusable(builder, control)


@pytest.mark.parametrize(("counter", "value", "triangles"), [
    ("_mesh_vert", 2**32 - 1, _TRIANGLES),  # rebased triangle overflow
    ("_mesh_vert", 2**32 - 2, []),          # final vertex offset overflow
    ("_mesh_tri", 2**32 - 1, _TRIANGLES),   # final triangle offset overflow
])
def test_uint32_packing_failure_preserves_every_field(counter, value, triangles):
    builder = _builder()
    # Reach the protocol boundary without allocating billions of vertices.
    setattr(builder, counter, value)
    control = deepcopy(builder)
    with pytest.raises(struct.error):
        builder.add_mesh(_VERTICES, triangles)
    assert builder == control
    assert encode_scene(builder, {}) == encode_scene(control, {})


@pytest.mark.parametrize("locked_stream", [
    "mesh_vtx", "mesh_tri", "mesh_ofs", "mesh_vofs",
])
def test_a_buffer_resize_refusal_rolls_back_other_streams(locked_stream):
    builder = _builder()
    control = deepcopy(builder)
    # A public bytearray with an exported view cannot be resized. In later
    # streams this fails after earlier appends have already succeeded.
    with memoryview(getattr(builder, locked_stream)):
        with pytest.raises(BufferError):
            builder.add_mesh(_VERTICES, _TRIANGLES)
        assert builder == control
    _assert_unchanged_and_reusable(builder, control)


@pytest.mark.parametrize("failing_stream", [
    "mesh_vtx", "mesh_tri", "mesh_ofs", "mesh_vofs",
])
def test_an_append_memory_error_rolls_back_and_is_not_replaced(failing_stream):
    failure = MemoryError("injected append failure")

    class FailingBuffer(bytearray):
        def extend(self, data):
            super().extend(data[:1])
            raise failure

    builder = _builder()
    control = deepcopy(builder)
    setattr(builder, failing_stream, FailingBuffer(getattr(builder, failing_stream)))
    with pytest.raises(MemoryError) as caught:
        builder.add_mesh(_VERTICES, _TRIANGLES)
    assert caught.value is failure
    assert builder == control
    assert encode_scene(builder, {}) == encode_scene(control, {})
    # Remove the injected allocator fault, not any geometry or counter.
    setattr(builder, failing_stream, bytearray(getattr(builder, failing_stream)))
    _assert_unchanged_and_reusable(builder, control)


def test_empty_mesh_keeps_the_existing_success_contract():
    builder = _builder()
    first = builder.mesh_count
    _, slot = builder.add_mesh(iter(()), iter(()))
    assert slot == first
    assert builder.mesh_count == first + 1
    assert struct.unpack_from("<I", builder.mesh_ofs, len(builder.mesh_ofs) - 4)[0] == 1
    assert struct.unpack_from("<I", builder.mesh_vofs, len(builder.mesh_vofs) - 4)[0] == 3
