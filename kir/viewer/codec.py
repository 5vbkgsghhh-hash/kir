"""THE SCENE CODEC — why this is bytes, not JSON, and why instances, not
meshes.

THE MEASUREMENT THAT SET THE FORMAT (10.08.2026, `демо-v3`, 84 120 shells):

| representation                                   | size     |
|---------------------------------------------------|---------:|
| naive JSON (full shell per element)               | 21.08 MB |
| the same, gzip -6                                 |  1.92 MB |
| THIS format (instances + string tables)           |  3.46 MB |
| of which geometry                                 |  2.11 MB |
| of which element addresses (strings)              |  0.76 MB |

`snowdon_plumb_v4`, 31 904 shells: JSON 7.55 MB, this format 1.31 MB.

Naive JSON doesn't lose on size — it loses on WHAT THE BROWSER DOES WITH
IT. 22 MB of text means parsing on the main thread and 84 120 objects on
the heap; here, instead, the browser gets an `ArrayBuffer` and turns it
into a `Float32Array` with zero parsing, then hands it straight to
`InstancedMesh`. The difference isn't in megabytes, it's in the fact that
the second approach doesn't block the frame.

WHY INSTANCING FROM DAY ONE, NOT "WE'LL OPTIMIZE LATER." 84 120 separate
meshes means 84 120 draw calls, i.e. a scene that is dead on arrival on any
hardware. Instancing turns them into THREE calls (boxes, capsules, prisms),
because the box is the same for everyone — only the matrix changes.
Rewriting the scene onto instances later is more expensive than starting
with them: the data format, the coloring method (`instanceColor`), and
mouse picking (`instanceId`) all rest on instancing.

THE FORMAT. The header is JSON (it holds the string tables and offsets),
the body is buffers laid end to end. No padding beyond the natural kind:
every buffer is a multiple of 4 bytes and they are laid out in decreasing
order of element size, so a `Float32Array` over the `ArrayBuffer` is built
with zero copying.

    "KIRSCN01"          8 bytes, magic
    header_len          uint32 LE
    header_json         header_len bytes, utf-8, PADDED WITH SPACES so
                        that 12 + header_len is divisible by 4
    <buffers back to back, in the order declared in header["buffers"]>

ALIGNMENT IS NOT PEDANTRY, IT IS A CONDITION OF WORKING AT ALL. `new
Float32Array(buffer, offset, len)` in the browser REQUIRES that `offset`
be divisible by 4, and throws a `RangeError` otherwise. The header length
is arbitrary (the string tables and the census go into it), so without
padding the body would start at a random byte and EVERY parse would fail
— on демо-v3 the header gave base % 4 == 3. The padding is done WITH
SPACES: a space is legal in JSON, so the client parses the header without
knowing anything about the padding.

The order of the buffers is also load-bearing and goes IN DECREASING
STRIDE: first everything that's a multiple of four (box 24, capsule 28,
prism_* 8/8/4, elem_slot 4), then two-byte fields (elem_cat, elem_level),
then one-byte fields, then strings. With an aligned start, this gives
every buffer an aligned start with not a single padding byte between them
— and this is verified by a test, not promised.

WHAT IS NOT HERE, AND WHY. There isn't a single triangle: the client
builds them from primitives (a box is one `BoxGeometry`, a capsule is one
`CapsuleGeometry`, a prism is an extrusion of its base). Putting triangles
here would triple the traffic for work the GPU does for free.

UNITS. Everything is in MILLIMETERS, as throughout the package
(`clash.geom`: «модели приезжают из Revit в футах и переводятся в мм»).
The client scales on its own — there is deliberately no conversion here,
otherwise a second place where the unit of length lives would appear.

PRECISION. `float32` on coordinates in millimeters: 24 mantissa bits give
an exact representation of integers up to 16 777 216 mm = 16.7 km. A
building of that size doesn't happen; a building DISPLACED that far from
the coordinate origin does happen (a site in a geodetic system). So the
codec SUBTRACTS a common origin (`header["origin_mm"]`) and writes offsets
from it — then the 24 bits land on the size of the building, not on the
distance to Greenwich. The origin is published in the header, not
implied.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, field
from typing import Any, Sequence

__all__ = ("SCENE_MAGIC", "SCENE_SCHEMA", "SceneBuilder", "encode_scene",
           "KIND_BOX", "KIND_CAPSULE", "KIND_PRISM", "KIND_MESH")

SCENE_MAGIC = b"KIRSCN01"
SCENE_SCHEMA = "kir-viewer-scene/1"

#: The size of one record of each stream, in bytes. Published in the
#: header rather than hard-coded in the client: a client that "knows" the
#: stride would drift silently from the server on the very first field
#: added.
STRIDE = {
    "box": 24,      # cx cy cz hx hy hz            (6 × float32)
    "capsule": 28,  # x0 y0 z0 x1 y1 z1 r          (7 × float32)
    "prism_z": 8,   # z0 z1                        (2 × float32)
    "prism_xy": 8,  # x y                          (2 × float32)
    "prism_ofs": 4,                                # uint32
    # 🔴 THE FOURTH KIND — THE SHAPE'S OWN CHANNEL (21.08.2026). Until
    # today the viewer had no channel of its own: it consumed the clash
    # output, and that knows exactly three primitives — the box, the
    # capsule, and the prism. Measurement on 21.08: ZERO triangles in the
    # codec, and not one of the five kinds of night expressiveness (vault,
    # hypar, NURBS, boolean, spline) is visible in the window. What was
    # shown were CLASH SHELLS, that is, a containment lock, not the body.
    #
    # A mesh source is FREE: `create_directshape` carries triangles
    # ready-made — they need not be derived or approximated.
    "mesh_vtx": 12,                                # x y z      (3 × float32)
    "mesh_tri": 12,                                # i j k      (3 × uint32)
    "mesh_ofs": 4,                                 # uint32 (triangles)
    # THE SECOND PREFIX SUM — OVER VERTICES, and it is not a luxury.
    # Triangle indices are global, so the mesh CAN be drawn without it.
    # But it cannot be SIGNED: the signature must carry the vertices of
    # EXACTLY THIS element, not all vertices of the scene. The first
    # revision signed all of them, and the signature grew quadratically,
    # while the client could not reproduce it at all.
    "mesh_vofs": 4,                                # uint32 (vertices)
    "elem_kind": 1,                                # uint8
    "elem_slot": 4,                                # uint32
    "elem_cat": 2,                                 # uint16
    "elem_level": 2,                               # uint16
    "elem_trust": 1,                               # uint8
    "elem_fidelity": 1,                            # uint8
    # Axes for which NOBODY PROMISED TO VERIFY ANYTHING — a tri-state
    # packed in one byte: 0 = all three declared, a mask = no obligation
    # on these axes, 255 = nothing to judge by. A separate buffer, not a
    # bit in `elem_fidelity`: this is a DIFFERENT question (not "is the
    # shape accurate" but "was the axis even taken up for checking"), and
    # merging them would repeat exactly the conflation that forced
    # `unwitnessed_axes` to be set up separately from the green triple.
    "elem_axes": 1,                                # uint8
    # THE LINE OF AUTHORITY AND EXISTENCE — two axes of the building
    # graph, and both are orthogonal to shape accuracy. `existence=planned`
    # means "the element does not yet exist in Revit," not "its shape is
    # unknown": an engineer spends three hours building a building that is
    # not in the document, and confusing this with something already built
    # would turn the "send to Revit" button into a lottery.
    "elem_authority": 1,                           # uint8
    "elem_existence": 1,                           # uint8
    # Facts ABOUT THE EDGE, attributed to its endpoint: a refuted
    # relation, a target outside extraction. Facts about the edge
    # specifically, not about the element itself.
    "elem_flags": 1,                               # uint8
}

#: Numeric codes of the primitives. The client reads them from the header
#: (`header["kinds"]`), not from its own copy of this table.
KIND_BOX, KIND_CAPSULE, KIND_PRISM, KIND_MESH = 0, 1, 2, 3

#: The signature record's separators. As bytes, not as literals with
#: special characters: source containing an actual null byte inside it is
#: not parsed by Python at all, and this has already happened once.
_RECORD_TAG = bytes((1,))
_FIELD_SEP = bytes((0,))

#: Duplicated from `honesty` BY VALUE, not by import: the codec must stay
#: pure stdlib (it knows nothing about `clash` or `ir`), and consistency
#: is held up by the test `test_codec.py::AxesContractMatchesHonesty`, not
#: by hope.
_AXES_ORDER = ("geometry", "topology", "semantic")
_AXES_UNJUDGEABLE = 255


def _f32_safe(value: float) -> float:
    """A non-finite number in the buffer is a NaN at a vertex and a black
    screen with not a single message. Here it turns into zero, and the
    caller was supposed to have filtered such an element out earlier
    (`snapshot.validate` does exactly that)."""
    return float(value) if math.isfinite(value) else 0.0


@dataclass
class SceneBuilder:
    """The scene accumulator. Writes PARALLEL streams, not a list of
    objects.

    The parallelism is not a micro-optimization but a requirement of
    `InstancedMesh`: the matrices of one instanced mesh must sit in one
    contiguous block. That's why an element is split into "which stream
    it sits in" (`elem_kind`) and "under which number" (`elem_slot`),
    while its attributes travel as separate arrays.
    """

    origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: 🔴 HOW MANY MESH VERTICES THE CLIENT ALREADY HOLDS FOR THIS SESSION
    #: (F-008, 29.08.2026). Zero for a whole scene and for anyone who
    #: builds the frame themselves — so the default changes not a single
    #: existing input.
    #: WHY. Triangle indices are global, and the client's `mergeScenes`
    #: REBASES them (`scene-data.js:112-120`). That means the client signs
    #: the tail mesh with the indices of the MERGED scene, while the
    #: server signed it with the indices of its own frame: 3,4,5 versus
    #: 0,1,2 on THE SAME geometry. Measurement: signature of the whole
    #: 73ea9fad66f809ff versus base+tail bd9551b401d2217f — and the "Send
    #: to Revit" button was refusing with `Refusal.SHOWN_MISMATCH` for
    #: anyone who kept the window open longer than one poll AND built a
    #: `create_directshape`.
    #: THE SHIFT DOES NOT ENTER THE STREAM ITSELF: the stream is read by
    #: the renderer, and there the indices must stay local to the frame.
    #: ONLY the signature shifts.
    mesh_vertex_base: int = 0

    box: bytearray = field(default_factory=bytearray)
    capsule: bytearray = field(default_factory=bytearray)
    prism_z: bytearray = field(default_factory=bytearray)
    prism_xy: bytearray = field(default_factory=bytearray)
    prism_ofs: bytearray = field(default_factory=bytearray)
    mesh_vtx: bytearray = field(default_factory=bytearray)
    mesh_tri: bytearray = field(default_factory=bytearray)
    mesh_ofs: bytearray = field(default_factory=bytearray)
    mesh_vofs: bytearray = field(default_factory=bytearray)

    elem_kind: bytearray = field(default_factory=bytearray)
    elem_slot: bytearray = field(default_factory=bytearray)
    elem_cat: bytearray = field(default_factory=bytearray)
    elem_level: bytearray = field(default_factory=bytearray)
    elem_trust: bytearray = field(default_factory=bytearray)
    elem_fidelity: bytearray = field(default_factory=bytearray)
    elem_axes: bytearray = field(default_factory=bytearray)
    elem_authority: bytearray = field(default_factory=bytearray)
    elem_existence: bytearray = field(default_factory=bytearray)
    elem_flags: bytearray = field(default_factory=bytearray)

    ids: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    #: SIGNATURE RECORDS — ONE PER ELEMENT, as a list, not as a
    #: contiguous stream. Per-element is deliberate: the signature of
    #: what's shown is composed as a MULTISET and therefore does not
    #: depend on order (see `showroom.scene_shown`).
    records: list = field(default_factory=list)

    _cats: dict[str, int] = field(default_factory=dict)
    _levels: dict[str, int] = field(default_factory=dict)
    _n_box: int = 0
    _n_cap: int = 0
    _n_prism: int = 0
    _prism_vert: int = 0
    _n_mesh: int = 0
    _mesh_tri: int = 0
    _mesh_vert: int = 0

    def __post_init__(self) -> None:
        # Prism offsets are prefix sums, so the first element = 0 and is
        # written immediately: without it the first prism would have no
        # start.
        self.prism_ofs += struct.pack("<I", 0)
        # The same reasoning as for prisms: the prefix sum starts at
        # zero, otherwise the first mesh would have no start.
        self.mesh_ofs += struct.pack("<I", 0)
        self.mesh_vofs += struct.pack("<I", 0)

    # ── string tables ──────────────────────────────────────────────────────
    def _cat_id(self, name: str) -> int:
        key = name or "?"
        if key not in self._cats:
            self._cats[key] = len(self._cats)
        return self._cats[key]

    @staticmethod
    def _level_key(name: str | None) -> str:
        """The level string IN THE TABLE — ONE for both the number and
        the signature.

        🔴 TWO PLACES COMPUTED IT DIFFERENTLY, AND THIS IS EXACTLY F-009
        (29.08.2026). The number was taken from here (`"?"` when there is
        no level), while the signature was assembled from `str(level or
        "")` — an empty string. The panel signs the TABLE
        (`scene-data.js:288`, `H.levels[d.level[i]]`), so for EVERY
        `create_directshape` (which has no level by construction), the
        server's and the panel's signatures diverged by exactly one
        field, and the "Send to Revit" button was refusing with
        `Refusal.SHOWN_MISMATCH`. Mesh transfer was dead by construction —
        that is, the entire FOURTH KIND of shape.

        A home-grown copy of `"?"` next to the signature won't do: it
        would drift on the very first edit of this function. The value is
        taken from the table's OWNER.
        """
        return str(name) if name is not None else "?"

    def _level_id(self, name: str | None) -> int:
        key = self._level_key(name)
        if key not in self._levels:
            self._levels[key] = len(self._levels)
        return self._levels[key]

    # ── primitives ──────────────────────────────────────────────────────────
    def add_box(self, lo: Sequence[float], hi: Sequence[float]) -> tuple[int, int]:
        """Bounding box -> center and HALF-extents. Half-extents, not
        full extents, because `BoxGeometry(1,1,1)` in three.js is
        centered, and the instance's scale multiplies exactly them."""
        ox, oy, oz = self.origin_mm
        cx = _f32_safe((lo[0] + hi[0]) * 0.5 - ox)
        cy = _f32_safe((lo[1] + hi[1]) * 0.5 - oy)
        cz = _f32_safe((lo[2] + hi[2]) * 0.5 - oz)
        # THE HALF-EXTENT IS NOT CLAMPED FROM BELOW. A degenerate shell (a
        # plane, a line, a point) must stay degenerate: inflating it to be
        # visible means drawing a volume that is not in the data. On
        # `демо-v3` this is 38.2 % of elements, and they are marked
        # `DEGENERATE`, and the viewer draws them with a separate
        # material, not with a separate thickness.
        hx = _f32_safe(abs(hi[0] - lo[0]) * 0.5)
        hy = _f32_safe(abs(hi[1] - lo[1]) * 0.5)
        hz = _f32_safe(abs(hi[2] - lo[2]) * 0.5)
        self.box += struct.pack("<6f", cx, cy, cz, hx, hy, hz)
        slot = self._n_box
        self._n_box += 1
        return KIND_BOX, slot

    def add_capsule(self, path: Sequence[Sequence[float]],
                    radius: float) -> tuple[int, int]:
        """Polyline × radius -> one instance per SEGMENT.

        A capsule made of N points is N-1 segments, and each travels as
        its own instance: `CapsuleGeometry` only knows a single span. The
        joints end up covered twice (the hemispheres of neighboring
        segments overlap) — exactly as in `clash.geom.Capsule`, where the
        body is the UNION of the segments.

        The element occupies slots `slot .. slot+n-1`; the viewer takes
        the segment count from the next element of the same stream, so
        the first slot is the element's address.
        """
        ox, oy, oz = self.origin_mm
        first = self._n_cap
        pts = list(path)
        if len(pts) == 1:
            pts = [pts[0], pts[0]]
        for a, b in zip(pts, pts[1:]):
            self.capsule += struct.pack(
                "<7f",
                _f32_safe(a[0] - ox), _f32_safe(a[1] - oy), _f32_safe(a[2] - oz),
                _f32_safe(b[0] - ox), _f32_safe(b[1] - oy), _f32_safe(b[2] - oz),
                _f32_safe(radius))
            self._n_cap += 1
        return KIND_CAPSULE, first

    def add_prism(self, pieces: Sequence[Sequence[Sequence[float]]],
                  z0: float, z1: float) -> tuple[int, int]:
        """Convex pieces of the base × [z0, z1].

        The pieces are written BACK TO BACK and each gets its own
        `prism_z` record, so `PrismSet` (a concave area as a union of
        convex ones) and a single `Prism` are encoded the same way — the
        only difference is the number of pieces. This is not a
        simplification: `PrismSet` has a shared Z-span by construction
        (`clash.geom.PrismSet`: «подошва выдавливается одной отметкой на
        одну высоту»), and there is nowhere to get a second Z for a
        piece.
        """
        ox, oy, oz = self.origin_mm
        first = self._n_prism
        for piece in pieces:
            for x, y in piece:
                self.prism_xy += struct.pack(
                    "<2f", _f32_safe(x - ox), _f32_safe(y - oy))
                self._prism_vert += 1
            self.prism_ofs += struct.pack("<I", self._prism_vert)
            self.prism_z += struct.pack(
                "<2f", _f32_safe(z0 - oz), _f32_safe(z1 - oz))
            self._n_prism += 1
        return KIND_PRISM, first

    def add_mesh(self, vertices_mm, triangles) -> tuple[int, int]:
        """A triangle mesh AS IT IS. Nothing is derived and nothing is
        smoothed.

        🔴 WHY A KIND THAT GENERALIZES NOTHING. The three previous kinds
        are SHELLS: a clash containment lock, which has its own job
        (don't let an intersection through) and its own cost of error (a
        spurious conflict is cheaper than a missed one). Showing them to a
        person as THE BODY means showing someone else's answer to
        someone else's question. A vault, a hypar, and a boolean inside a
        box are indistinguishable from the box.

        INDICES ARE STORED GLOBALLY, not local to the mesh, and this is
        not an economy: local indices would require the client to KNOW
        the vertex base of every mesh, that is, to keep a second copy of
        the layout, which would drift from the server's silently. Global
        indices are read back to back.

        A REFUSAL, NOT SILENT CORRUPTION: a triangle whose index falls
        outside the supplied vertices is a hole in the source, and it
        must name itself here, rather than become a black smudge on the
        screen.

        An input or packing error changes not a single stream or counter.
        After a refusal, the accumulator can be reused for the next mesh.
        """
        ox, oy, oz = self.origin_mm
        base = self._mesh_vert
        first = self._n_mesh
        # Validate and pack into local streams. A caller may catch a refusal
        # and draw a hull instead; rejected vertices must not become the next
        # mesh's geometry while the published offsets still point before them.
        vertices = bytearray()
        indices = bytearray()
        n_local = 0
        for pt in vertices_mm:
            x, y, z = pt[0], pt[1], pt[2]
            vertices += struct.pack(
                "<3f", _f32_safe(x - ox), _f32_safe(y - oy), _f32_safe(z - oz))
            n_local += 1
        n_triangles = 0
        for tri in triangles:
            i, j, k = int(tri[0]), int(tri[1]), int(tri[2])
            if not (0 <= i < n_local and 0 <= j < n_local and 0 <= k < n_local):
                raise ValueError(
                    f"треугольник ({i}, {j}, {k}) выходит за поданные "
                    f"{n_local} вершин — источник неполон, и молчаливое "
                    f"выбрасывание дало бы дыру в теле без единого слова")
            indices += struct.pack("<3I", base + i, base + j, base + k)
            n_triangles += 1
        next_tri = self._mesh_tri + n_triangles
        next_vert = base + n_local
        next_mesh = first + 1
        # Prefix sums can overflow uint32 even when every triangle fits.
        # Pack them before committing any buffer or counter as well.
        appends = (
            (self.mesh_vtx, vertices, len(self.mesh_vtx)),
            (self.mesh_tri, indices, len(self.mesh_tri)),
            (self.mesh_ofs, struct.pack("<I", next_tri), len(self.mesh_ofs)),
            (self.mesh_vofs, struct.pack("<I", next_vert), len(self.mesh_vofs)),
        )
        try:
            for buffer, data, _ in appends:
                buffer.extend(data)
        except (BufferError, MemoryError):
            # Keep in-place buffers and linear append cost. A resize can fail
            # (e.g. an exported memoryview); roll back already appended bytes
            # and propagate the original exception, without treating it as a
            # valid mesh or silently substituting a representation here.
            for buffer, _, original_length in appends:
                if len(buffer) != original_length:
                    del buffer[original_length:]
            raise
        self._mesh_tri = next_tri
        self._mesh_vert = next_vert
        self._n_mesh = next_mesh
        return KIND_MESH, first

    @property
    def mesh_count(self) -> int:
        """How many meshes landed with THEIR OWN shape. Asked of the
        builder.

        The scene header is assembled by a different function, and
        duplicating the counter there would mean setting up a second
        carrier of one number — precisely what the agreement registry
        catches.
        """
        return self._n_mesh

    # ── element ────────────────────────────────────────────────────────────
    def _record(self, *, element_id: str, category: str, level: str | None,
                label: str, kind: int, slot: int, trust: int, fidelity: int,
                axes: int, authority: int, existence: int, flags: int) -> None:
        """One record of the SIGNATURE OF WHAT WAS SHOWN. The format is a
        specification, not a detail.

        WHY THIS IS HERE. The "send to Revit" button signs WHAT THE PERSON
        SAW. As long as the scene arrived whole, "shown" and "transferred"
        matched by construction. With merging, these are two DIFFERENT
        computations — server-side and client-side — and any divergence
        between them is a building the engineer did not see, built with
        their consent.

        That's why the record is assembled from the same values that feed
        the renderer, and only from them: the address, the RESOLVED
        category and level strings (not their numbers — the merge has its
        own numbers), the operation's signature, both honesty axes, both
        graph axes, edge flags, and the element's OWN GEOMETRY, taken by
        slot exactly the way `build()` takes it.

        TABLE NUMBERS ARE DELIBERATELY EXCLUDED. Merging re-indexes
        categories and levels (the delta has its own numbers), so a
        signature over numbers would diverge between the two sides over a
        meaningless difference.
        """
        blob = bytearray(_RECORD_TAG)
        # 🔴 THE LEVEL IS SIGNED WITH THE RESOLVED STRING, THE SAME ONE
        # THAT WENT INTO THE TABLE (F-009). The docstring above requires
        # this verbatim — "the RESOLVED category and level strings" —
        # while what stood here was `str(level or "")`, i.e. the RAW
        # value.
        for text in (element_id, category, self._level_key(level), label):
            blob += text.encode("utf-8")
            blob += _FIELD_SEP
        blob += bytes((kind & 0xFF, trust & 0xFF, fidelity & 0xFF, axes & 0xFF,
                       authority & 0xFF, existence & 0xFF, flags & 0xFF))
        # GEOMETRY IS TAKEN BY SLOT UP TO THE STREAM'S CURRENT END: for a
        # capsule this is ALL of its segments, for a prism — ALL of its
        # pieces. Signing only the first would mean missing that half of a
        # polyline is gone.
        if kind == KIND_BOX:
            blob += self.box[slot * 24:(slot + 1) * 24]
        elif kind == KIND_CAPSULE:
            blob += self.capsule[slot * 28:self._n_cap * 28]
        elif kind == KIND_PRISM:
            blob += self.prism_z[slot * 8:self._n_prism * 8]
            v0 = struct.unpack_from("<I", self.prism_ofs, slot * 4)[0]
            v1 = struct.unpack_from("<I", self.prism_ofs, self._n_prism * 4)[0]
            blob += self.prism_xy[v0 * 8:v1 * 8]
        elif kind == KIND_MESH:
            # BOTH TRIANGLES AND VERTICES ARE SIGNED. Indices alone are
            # not enough: the same mesh over shifted vertices is a
            # different body, and the signature must change along with
            # WHAT THE PERSON SAW.
            t0 = struct.unpack_from("<I", self.mesh_ofs, slot * 4)[0]
            t1 = struct.unpack_from("<I", self.mesh_ofs, self._n_mesh * 4)[0]
            # THE SHIFT BY THE ACCUMULATED AMOUNT — see `mesh_vertex_base`.
            # The `if base:` branch is NOT an optimization: at zero the
            # slice must stay BYTE-IDENTICAL to before, otherwise the
            # change stops being additive and a whole scene changes the
            # signature that the client is already computing correctly.
            base = self.mesh_vertex_base
            if base:
                for at in range(t0 * 12, t1 * 12, 4):
                    blob += struct.pack("<I", struct.unpack_from(
                        "<I", self.mesh_tri, at)[0] + base)
            else:
                blob += self.mesh_tri[t0 * 12:t1 * 12]
            v0 = struct.unpack_from("<I", self.mesh_vofs, slot * 4)[0]
            v1 = struct.unpack_from("<I", self.mesh_vofs, self._n_mesh * 4)[0]
            blob += self.mesh_vtx[v0 * 12:v1 * 12]
        self.records.append(bytes(blob))

    def add_element(self, *, element_id: str, category: str,
                    level: str | None, trust: int, fidelity: int,
                    kind: int, slot: int, label: str = "",
                    axes: int = 255, authority: int = 2, existence: int = 2,
                    flags: int = 0) -> None:
        """`axes` defaults to 255 = "nothing to judge by," and NOT 0 =
        "all declared."

        The default is chosen this way deliberately: a caller who forgot
        to pass the axes gets a grey "wasn't looked at," not a green
        "verified." A default that errs toward green is the same defect
        as a silent witness, just hidden in the signature.

        `authority` and `existence` default to 2 = "unknown" for the same
        reason: a scene built without the graph layer must say "we didn't
        ask," not pass everything off as already built.
        """
        self.ids.append(element_id)
        self.labels.append(label)
        self.elem_kind += struct.pack("<B", kind)
        self.elem_slot += struct.pack("<I", slot)
        self.elem_cat += struct.pack("<H", self._cat_id(category))
        self.elem_level += struct.pack("<H", self._level_id(level))
        self.elem_trust += struct.pack("<B", trust)
        self.elem_fidelity += struct.pack("<B", fidelity)
        self.elem_axes += struct.pack("<B", axes)
        self.elem_authority += struct.pack("<B", authority)
        self.elem_existence += struct.pack("<B", existence)
        self.elem_flags += struct.pack("<B", flags)
        self._record(element_id=element_id, category=category, level=level,
                     label=label, kind=kind, slot=slot, trust=trust,
                     fidelity=fidelity, axes=axes, authority=authority,
                     existence=existence, flags=flags)

    @property
    def count(self) -> int:
        return len(self.ids)

    def shown_records(self) -> list[bytes]:
        """Element signature records for THIS scene — one per element.

        Handed back as a list, not as a digest: the session's signature
        is composed across all shown scenes, and the composing must be
        done by whoever remembers the session (`live.showroom`), not by
        whoever packs one frame.
        """
        return list(self.records)

    def finish(self, meta: dict[str, Any]) -> bytes:
        """Header + body. The buffer order is fixed HERE and published —
        the client reads `header["buffers"]` rather than remembering the
        order."""
        ids_blob = "\n".join(self.ids).encode("utf-8")
        labels_blob = "\n".join(self.labels).encode("utf-8")
        streams: list[tuple[str, bytes]] = [
            ("box", bytes(self.box)),
            ("capsule", bytes(self.capsule)),
            ("prism_z", bytes(self.prism_z)),
            ("prism_xy", bytes(self.prism_xy)),
            ("prism_ofs", bytes(self.prism_ofs)),
            ("mesh_vtx", bytes(self.mesh_vtx)),
            ("mesh_tri", bytes(self.mesh_tri)),
            ("mesh_ofs", bytes(self.mesh_ofs)),
            ("mesh_vofs", bytes(self.mesh_vofs)),
            ("elem_slot", bytes(self.elem_slot)),
            ("elem_cat", bytes(self.elem_cat)),
            ("elem_level", bytes(self.elem_level)),
            ("elem_kind", bytes(self.elem_kind)),
            ("elem_trust", bytes(self.elem_trust)),
            ("elem_fidelity", bytes(self.elem_fidelity)),
            ("elem_axes", bytes(self.elem_axes)),
            ("elem_authority", bytes(self.elem_authority)),
            ("elem_existence", bytes(self.elem_existence)),
            ("elem_flags", bytes(self.elem_flags)),
            ("ids", ids_blob),
            ("labels", labels_blob),
        ]
        buffers: list[dict[str, Any]] = []
        offset = 0
        for name, blob in streams:
            buffers.append({"name": name, "offset": offset, "length": len(blob),
                            "stride": STRIDE.get(name, 1)})
            offset += len(blob)

        header = dict(meta)
        header.update({
            "schema": SCENE_SCHEMA,
            "origin_mm": list(self.origin_mm),
            "units": "mm",
            "elements": self.count,
            "counts": {"box": self._n_box, "capsule": self._n_cap,
                       "prism": self._n_prism, "mesh": self._n_mesh,
                       "mesh_triangles": self._mesh_tri,
                       "mesh_vertices": self._mesh_vert},
            "kinds": {"box": KIND_BOX, "capsule": KIND_CAPSULE,
                      "prism": KIND_PRISM, "mesh": KIND_MESH},
            # The bit order of `elem_axes` and the "nothing to judge by"
            # value are published: a client holding its own copy would
            # drift from the server on the very first new axis added by
            # the owner of the obligations table.
            "axes_order": list(_AXES_ORDER),
            "axes_unjudgeable": _AXES_UNJUDGEABLE,
            "categories": [n for n, _ in sorted(self._cats.items(),
                                                key=lambda kv: kv[1])],
            "levels": [n for n, _ in sorted(self._levels.items(),
                                            key=lambda kv: kv[1])],
            "buffers": buffers,
            "body_bytes": offset,
        })
        header_json = json.dumps(header, ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
        # PADDING THE HEADER TO ALIGN THE BODY. Without it `new
        # Float32Array(buffer, offset, …)` throws a RangeError, because
        # offset must be divisible by 4. A space is legal JSON, so parsing
        # the header need not know anything about the padding.
        # Measurement: on демо-v3, without it, base % 4 == 3.
        pad = (-(len(SCENE_MAGIC) + 4 + len(header_json))) % 4
        header_json += b" " * pad
        out = bytearray(SCENE_MAGIC)
        out += struct.pack("<I", len(header_json))
        out += header_json
        for _, blob in streams:
            out += blob
        return bytes(out)


def encode_scene(builder: SceneBuilder, meta: dict[str, Any]) -> bytes:
    return builder.finish(meta)
