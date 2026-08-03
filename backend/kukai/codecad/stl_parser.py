"""Minimal STL parser — binary + ASCII.

Returns a list of triangles, each as a 3-tuple of (x, y, z) vertices in
MILLIMETRES (CadQuery's default unit).

Used to convert CadQuery output into a form embeddable into a Revit C# script
that builds a TessellatedShape.

We don't preserve normals — Revit's TessellatedShapeBuilder computes them
from vertex order. We also don't dedupe vertices; the C# side does, if needed.
"""
from __future__ import annotations

import struct
from typing import Iterable, NamedTuple


class Triangle(NamedTuple):
    """One triangular face, three (x, y, z) vertices in mm."""
    v1: tuple[float, float, float]
    v2: tuple[float, float, float]
    v3: tuple[float, float, float]


def parse_stl(data: bytes) -> list[Triangle]:
    """Parse STL bytes (auto-detect binary vs ASCII). Returns list of Triangles."""
    if not data:
        return []
    # Heuristic: ASCII STL starts with 'solid' but so does binary's 80-byte header
    # (often). The reliable test is checking byte size vs claimed triangle count.
    if data.lstrip().startswith(b"solid"):
        # Could still be binary. Try ASCII first; on parse failure fall through.
        try:
            tris = list(_parse_ascii(data))
            if tris:
                return tris
        except (ValueError, UnicodeDecodeError):
            pass
    return list(_parse_binary(data))


def _parse_binary(data: bytes) -> Iterable[Triangle]:
    if len(data) < 84:
        raise ValueError(f"binary STL too short: {len(data)} bytes")
    # 80-byte header + 4-byte triangle count + N * 50 bytes per triangle
    n_tris = struct.unpack("<I", data[80:84])[0]
    expected = 84 + n_tris * 50
    if len(data) < expected:
        raise ValueError(
            f"binary STL truncated: header says {n_tris} triangles ({expected} bytes), "
            f"got {len(data)} bytes"
        )
    offset = 84
    for _ in range(n_tris):
        # normal (12 bytes) + v1 (12) + v2 (12) + v3 (12) + attribute (2) = 50
        _, _, _, x1, y1, z1, x2, y2, z2, x3, y3, z3, _ = struct.unpack_from(
            "<3f 3f 3f 3f H", data, offset
        )
        offset += 50
        yield Triangle((x1, y1, z1), (x2, y2, z2), (x3, y3, z3))


def _parse_ascii(data: bytes) -> Iterable[Triangle]:
    text = data.decode("ascii", errors="strict")
    verts: list[tuple[float, float, float]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("vertex "):
            continue
        parts = line.split()
        if len(parts) != 4:
            continue
        x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
        verts.append((x, y, z))
        if len(verts) == 3:
            yield Triangle(verts[0], verts[1], verts[2])
            verts.clear()
