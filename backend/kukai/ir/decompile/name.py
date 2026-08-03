"""Deterministic DECOMPILE NAME stage.

NAME annotates a copied FOLD tree with geometry-only labels and renders a
compact building gestalt.  It has no LLM dependency: an optional label
decorator is called only when ``USE_LLM_LABELS`` (or an explicit override) is
true, and it never supplies or replaces geometric facts.

The public contour input is deliberately explicit because the frozen Wave-A
L0 schema has no slab/roof Sketch profile.  ``shape_of`` accepts either a
single point ring, a sequence of rings (exterior first), or a mapping such as::

    {"outer": [[x_mm, y_mm], ...],
     "holes": [[[x_mm, y_mm], ...], ...],
     "curvilinear": False}

A ring may instead contain typed ``segments`` with ``kind`` equal to
``line``/``arc`` and ``p0_mm``/``p1_mm``.  Any arc makes the result complex
and sets ``curvilinear_perimeter``; NAME never turns its chord into a claimed
rectangle.
"""
from __future__ import annotations

import copy
import math
import re
import statistics
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, Literal, TypedDict

from kukai.ir.decompile.fold import TreeNode, iter_l1_leaves
from kukai.ir.decompile.schema import (
    COLLINEAR_TOL,
    L0Document,
    USE_LLM_LABELS,
)


ShapeKind = Literal["rectangle", "L", "T", "U", "complex", "unknown"]
Point2 = tuple[float, float]


class NameStageError(ValueError):
    """NAME cannot safely consume a malformed explicit contract."""


class ContourError(NameStageError):
    """An explicitly supplied contour is structurally malformed."""


class ShapeClassification(TypedDict):
    """JSON-ready, lossless result of deterministic contour analysis."""

    shape: ShapeKind
    corners: int
    aspect: float | None
    convex: bool
    courtyard: bool
    curvilinear_perimeter: bool
    dims_mm: list[float] | None
    area_m2: float | None
    valid: bool
    description: str


class NameResult(TypedDict):
    """Output boundary for NAME, ready for the future Passport assembler."""

    tree: TreeNode
    gestalt: str
    shape: ShapeClassification


LabelDecorator = Callable[[str, str, Mapping[str, Any]], str]


_CURVE_KINDS = frozenset({
    "arc", "circle", "ellipse", "elliptical_arc", "spline", "nurbs",
    "hermite", "curve", "curved",
})
_PHYSICAL_HEIGHT_EXCLUSIONS = frozenset({
    "OST_Levels", "OST_Grids", "OST_RasterImages", "OST_Rooms",
})
# Mirrors fold._MOP_RE (audit F9): the multilingual МОП classifier must not
# diverge between the fold partition and the NAME purpose heuristic — an
# EN-named building near the 60% threshold misclassified when corridors
# stayed in the denominator.
_MOP_RE = re.compile(
    r"коридор|лестнич|лифт|тамбур|холл|вестибюль|моп|лестн.?\s*клетк|"
    r"corridor|hall(?:way)?|lobby|stair|stairwell|elevator|lift|foyer|"
    r"vestibule|entrance|utility|mechanical|electrical|riser|shaft|mop|core",
    re.IGNORECASE,
)
_OFFICE_RE = re.compile(
    r"офис|кабинет|переговор|рабоч(?:ее|ая)\s+мест|open[ -]?space|"
    r"conference|reception|office|workplace",
    re.IGNORECASE,
)
_RESIDENTIAL_RE = re.compile(
    r"спальн|гостин|жил(?:ая|ое|ой)|детск|комнат|кухн|сануз|ванн|"
    r"прихож|квартир|студи|bedroom|living|kitchen|bath(?:room)?|"
    r"nursery|apartment|studio",
    re.IGNORECASE,
)
_HABITABLE_RE = re.compile(
    r"спальн|гостин|жил(?:ая|ое|ой)\s+комнат|детск|(?:^|\W)комнат|"
    r"студи|bedroom|living|nursery|studio",
    re.IGNORECASE,
)
_TRAILING_NUMBER_RE = re.compile(r"^(.*?)(\d+)\s*$")
_POINT_EPS = 1e-7


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray))


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContourError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ContourError(f"{field_name} must be a finite number")
    return number


def _point(value: Any, field_name: str) -> Point2:
    if isinstance(value, Mapping):
        if "point" in value:
            return _point(value["point"], f"{field_name}.point")
        if "x" in value and "y" in value:
            return (
                _finite(value["x"], f"{field_name}.x"),
                _finite(value["y"], f"{field_name}.y"),
            )
        if "x_mm" in value and "y_mm" in value:
            return (
                _finite(value["x_mm"], f"{field_name}.x_mm"),
                _finite(value["y_mm"], f"{field_name}.y_mm"),
            )
    if _is_sequence(value) and len(value) >= 2:
        return (
            _finite(value[0], f"{field_name}[0]"),
            _finite(value[1], f"{field_name}[1]"),
        )
    raise ContourError(f"{field_name} must contain x/y coordinates")


def _curve_marker(value: Mapping[str, Any]) -> bool:
    kind = value.get(
        "kind", value.get("type", value.get("curve_kind", "")))
    return (
        str(kind).strip().lower() in _CURVE_KINDS
        or value.get("arc") is True
        or bool(value.get("arcs"))
        or value.get("curvilinear") is True
        or value.get("has_arcs") is True
    )


def _segment_endpoint(
    segment: Mapping[str, Any],
    names: Sequence[str],
    field_name: str,
) -> Point2:
    for name in names:
        if name in segment:
            return _point(segment[name], f"{field_name}.{name}")
    raise ContourError(f"{field_name} has no segment endpoint")


def _ring(value: Any, field_name: str) -> tuple[list[Point2], bool]:
    """Normalize a point or typed-segment ring without approximating arcs."""

    ring_curvilinear = False
    if isinstance(value, Mapping):
        ring_curvilinear = _curve_marker(value)
        if "segments" in value:
            segments = value["segments"]
            if not _is_sequence(segments):
                raise ContourError(f"{field_name}.segments must be an array")
            points: list[Point2] = []
            previous_end: Point2 | None = None
            for index, raw_segment in enumerate(segments):
                segment_name = f"{field_name}.segments[{index}]"
                if not isinstance(raw_segment, Mapping):
                    raise ContourError(f"{segment_name} must be an object")
                start = _segment_endpoint(
                    raw_segment,
                    ("p0_mm", "p0", "start", "from"),
                    segment_name,
                )
                end = _segment_endpoint(
                    raw_segment,
                    ("p1_mm", "p1", "end", "to"),
                    segment_name,
                )
                if previous_end is not None and not _points_close(
                        previous_end, start):
                    raise ContourError(
                        f"{segment_name} is not contiguous with the prior segment")
                if not points:
                    points.append(start)
                points.append(end)
                previous_end = end
                ring_curvilinear = (
                    ring_curvilinear or _curve_marker(raw_segment))
            return points, ring_curvilinear
        for key in ("points", "outline", "outer", "exterior"):
            if key in value:
                points, nested_curve = _ring(
                    value[key], f"{field_name}.{key}")
                return points, ring_curvilinear or nested_curve
        raise ContourError(
            f"{field_name} must contain points, outline, or segments")

    if not _is_sequence(value):
        raise ContourError(f"{field_name} must be an array or object")
    points = []
    for index, raw_point in enumerate(value):
        point_name = f"{field_name}[{index}]"
        if isinstance(raw_point, Mapping):
            ring_curvilinear = ring_curvilinear or _curve_marker(raw_point)
        points.append(_point(raw_point, point_name))
    return points, ring_curvilinear


def _looks_like_point_or_segment(value: Any) -> bool:
    if isinstance(value, Mapping):
        keys = set(value)
        return bool(keys & {
            "x", "y", "x_mm", "y_mm", "point", "p0_mm", "p0",
            "start", "from",
        })
    return (
        _is_sequence(value)
        and len(value) >= 2
        and all(isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in value[:2])
    )


def _normalise_outline(
    outline_points: Any,
) -> tuple[list[Point2], list[list[Point2]], bool]:
    if outline_points is None:
        return [], [], False

    contour_curvilinear = False
    raw_outer: Any
    raw_holes: Any = []
    if isinstance(outline_points, Mapping):
        contour_curvilinear = _curve_marker(outline_points)
        if "loops" in outline_points:
            loops = outline_points["loops"]
            if not _is_sequence(loops):
                raise ContourError("outline.loops must be an array")
            if not loops:
                return [], [], contour_curvilinear
            raw_outer, raw_holes = loops[0], loops[1:]
        else:
            for key in ("outer", "exterior", "outline", "points", "segments"):
                if key in outline_points:
                    if key == "segments":
                        raw_outer = outline_points
                    else:
                        raw_outer = outline_points[key]
                    break
            else:
                raise ContourError(
                    "outline must contain outer, exterior, outline, points, "
                    "segments, or loops")
            raw_holes = outline_points.get(
                "holes", outline_points.get("inner_loops", []))
    elif _is_sequence(outline_points):
        if not outline_points:
            return [], [], False
        if _looks_like_point_or_segment(outline_points[0]):
            raw_outer = outline_points
        else:
            raw_outer = outline_points[0]
            raw_holes = outline_points[1:]
    else:
        raise ContourError("outline must be a ring, rings, or an object")

    if raw_holes is None:
        raw_holes = []
    if not _is_sequence(raw_holes):
        raise ContourError("outline holes must be an array of rings")
    outer, outer_curve = _ring(raw_outer, "outline.outer")
    holes: list[list[Point2]] = []
    holes_curve = False
    for index, raw_hole in enumerate(raw_holes):
        hole, hole_curve = _ring(raw_hole, f"outline.holes[{index}]")
        holes.append(hole)
        holes_curve = holes_curve or hole_curve
    return outer, holes, contour_curvilinear or outer_curve or holes_curve


def _points_close(left: Point2, right: Point2, tolerance: float = _POINT_EPS) \
        -> bool:
    return math.hypot(left[0] - right[0], left[1] - right[1]) <= tolerance


def _dedupe_ring(points: Sequence[Point2]) -> list[Point2]:
    deduped: list[Point2] = []
    for point in points:
        if not deduped or not _points_close(deduped[-1], point):
            deduped.append(point)
    if len(deduped) > 1 and _points_close(deduped[0], deduped[-1]):
        deduped.pop()
    return deduped


def _turn_degrees(previous: Point2, current: Point2, following: Point2) \
        -> float | None:
    incoming = (current[0] - previous[0], current[1] - previous[1])
    outgoing = (following[0] - current[0], following[1] - current[1])
    incoming_length = math.hypot(*incoming)
    outgoing_length = math.hypot(*outgoing)
    if incoming_length <= _POINT_EPS or outgoing_length <= _POINT_EPS:
        return None
    cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
    dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
    return math.degrees(math.atan2(cross, dot))


def _simplify_ring(points: Sequence[Point2]) -> list[Point2]:
    simplified = _dedupe_ring(points)
    changed = True
    while changed and len(simplified) > 3:
        changed = False
        for index in range(len(simplified)):
            turn = _turn_degrees(
                simplified[index - 1],
                simplified[index],
                simplified[(index + 1) % len(simplified)],
            )
            if turn is not None and abs(turn) <= COLLINEAR_TOL:
                del simplified[index]
                changed = True
                break
    return simplified


def _signed_area_mm2(points: Sequence[Point2]) -> float:
    return 0.5 * sum(
        point[0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * point[1]
        for index, point in enumerate(points)
    )


def _orientation(a: Point2, b: Point2, c: Point2) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (
        b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point2, b: Point2, point: Point2) -> bool:
    return (
        abs(_orientation(a, b, point)) <= _POINT_EPS
        and min(a[0], b[0]) - _POINT_EPS
        <= point[0]
        <= max(a[0], b[0]) + _POINT_EPS
        and min(a[1], b[1]) - _POINT_EPS
        <= point[1]
        <= max(a[1], b[1]) + _POINT_EPS
    )


def _segments_intersect(a: Point2, b: Point2, c: Point2, d: Point2) -> bool:
    turns = (
        _orientation(a, b, c),
        _orientation(a, b, d),
        _orientation(c, d, a),
        _orientation(c, d, b),
    )
    if ((turns[0] > _POINT_EPS and turns[1] < -_POINT_EPS)
            or (turns[0] < -_POINT_EPS and turns[1] > _POINT_EPS)):
        if ((turns[2] > _POINT_EPS and turns[3] < -_POINT_EPS)
                or (turns[2] < -_POINT_EPS
                    and turns[3] > _POINT_EPS)):
            return True
    return (
        (abs(turns[0]) <= _POINT_EPS and _on_segment(a, b, c))
        or (abs(turns[1]) <= _POINT_EPS and _on_segment(a, b, d))
        or (abs(turns[2]) <= _POINT_EPS and _on_segment(c, d, a))
        or (abs(turns[3]) <= _POINT_EPS and _on_segment(c, d, b))
    )


def _simple_ring(points: Sequence[Point2]) -> bool:
    count = len(points)
    if count < 3:
        return False
    for first in range(count):
        a = points[first]
        b = points[(first + 1) % count]
        for second in range(first + 1, count):
            if second in {first, (first + 1) % count}:
                continue
            if first == 0 and second == count - 1:
                continue
            c = points[second]
            d = points[(second + 1) % count]
            if _segments_intersect(a, b, c, d):
                return False
    return True


def _point_in_ring(point: Point2, ring: Sequence[Point2]) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        if _on_segment(previous, current, point):
            return True
        if (previous[1] > point[1]) != (current[1] > point[1]):
            crossing = (
                (current[0] - previous[0])
                * (point[1] - previous[1])
                / (current[1] - previous[1])
                + previous[0]
            )
            if point[0] < crossing:
                inside = not inside
        previous = current
    return inside


def _rings_intersect(left: Sequence[Point2], right: Sequence[Point2]) -> bool:
    return any(
        _segments_intersect(
            left[left_index],
            left[(left_index + 1) % len(left)],
            right[right_index],
            right[(right_index + 1) % len(right)],
        )
        for left_index in range(len(left))
        for right_index in range(len(right))
    )


def _convex(points: Sequence[Point2]) -> bool:
    signs: set[int] = set()
    for index in range(len(points)):
        cross = _orientation(
            points[index - 1], points[index], points[(index + 1) % len(points)])
        if abs(cross) <= _POINT_EPS:
            continue
        signs.add(1 if cross > 0.0 else -1)
    return len(signs) == 1


def _orthogonal_reflex_indices(points: Sequence[Point2]) -> list[int] | None:
    signed_area = _signed_area_mm2(points)
    if abs(signed_area) <= _POINT_EPS:
        return None
    winding = 1 if signed_area > 0.0 else -1
    reflex: list[int] = []
    for index in range(len(points)):
        turn = _turn_degrees(
            points[index - 1], points[index], points[(index + 1) % len(points)])
        if turn is None or abs(abs(turn) - 90.0) > COLLINEAR_TOL:
            return None
        if turn * winding < 0.0:
            reflex.append(index)
    return reflex


def _local_orthogonal_points(points: Sequence[Point2]) -> list[Point2]:
    first = points[0]
    second = points[1]
    dx = second[0] - first[0]
    dy = second[1] - first[1]
    length = math.hypot(dx, dy)
    if length <= _POINT_EPS:
        return list(points)
    ux, uy = dx / length, dy / length
    vx, vy = -uy, ux
    return [
        (
            (point[0] - first[0]) * ux + (point[1] - first[1]) * uy,
            (point[0] - first[0]) * vx + (point[1] - first[1]) * vy,
        )
        for point in points
    ]


def _reflection_symmetric(
    points: Sequence[Point2],
    axis: int,
    middle: float,
    tolerance: float,
) -> bool:
    for point in points:
        reflected = list(point)
        reflected[axis] = 2.0 * middle - reflected[axis]
        if not any(
            math.hypot(candidate[0] - reflected[0],
                       candidate[1] - reflected[1]) <= tolerance
            for candidate in points
        ):
            return False
    return True


def _eight_corner_shape(
    points: Sequence[Point2],
    reflex: Sequence[int],
) -> ShapeKind:
    if len(reflex) != 2:
        return "complex"
    local = _local_orthogonal_points(points)
    mins = [min(point[index] for point in local) for index in (0, 1)]
    maxs = [max(point[index] for point in local) for index in (0, 1)]
    tolerance = max(1.0, max(maxs[index] - mins[index] for index in (0, 1))
                    * 1e-6)
    middles = [(mins[index] + maxs[index]) / 2.0 for index in (0, 1)]
    distance = abs(reflex[0] - reflex[1])
    adjacent = distance in {1, len(points) - 1}
    if adjacent:
        left = local[reflex[0]]
        right = local[reflex[1]]
        connecting_axis = (
            0 if abs(left[0] - right[0]) >= abs(left[1] - right[1]) else 1)
        midpoint = (left[connecting_axis] + right[connecting_axis]) / 2.0
        if (abs(midpoint - middles[connecting_axis]) <= tolerance
                and _reflection_symmetric(
                    local, connecting_axis, middles[connecting_axis], tolerance)):
            return "U"
        return "complex"
    if any(_reflection_symmetric(local, axis, middles[axis], tolerance)
           for axis in (0, 1)):
        return "T"
    return "complex"


def _russian_count(number: int, one: str, few: str, many: str) -> str:
    last_two = number % 100
    last = number % 10
    if 11 <= last_two <= 14:
        word = many
    elif last == 1:
        word = one
    elif 2 <= last <= 4:
        word = few
    else:
        word = many
    return f"{number} {word}"


def _format_decimal(value: float, digits: int = 2) -> str:
    rounded = round(value, digits)
    if abs(rounded - round(rounded)) < 10 ** (-digits):
        text = str(int(round(rounded)))
    else:
        text = f"{rounded:.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _shape_description(
    shape: ShapeKind,
    corners: int,
    aspect: float | None,
    courtyard: bool,
    curvilinear: bool,
    area_m2: float | None,
    valid: bool,
) -> str:
    named = {
        "rectangle": "прямоугольный контур",
        "L": "Г-образный контур",
        "T": "Т-образный контур",
        "U": "П-образный контур",
    }
    if shape in named:
        return named[shape]
    if shape == "unknown":
        return "контур не определён"
    parts = [
        "сложный контур",
        _russian_count(corners, "угол", "угла", "углов"),
    ]
    if aspect is not None:
        parts.append(f"соотношение сторон {_format_decimal(aspect)}")
    if area_m2 is not None:
        parts.append(f"~{_format_decimal(area_m2, 1)} м²")
    if courtyard:
        parts.append("с внутренним двором")
    if curvilinear:
        parts.append("криволинейный периметр")
    if not valid:
        parts.append("геометрия контура некорректна")
    return ", ".join(parts)


def shape_of(outline_points: Any) -> ShapeClassification:
    """Classify a typed millimetre contour without guessing from a bbox.

    Near-collinear vertices are removed within ``COLLINEAR_TOL``.  Clean named
    classes require a valid, simple, hole-free, non-curvilinear orthogonal
    polygon.  Everything else is richly described as ``complex``; an absent or
    degenerate contour is explicitly ``unknown``.
    """

    outer_raw, holes_raw, curvilinear = _normalise_outline(outline_points)
    outer = _simplify_ring(outer_raw)
    holes = [_simplify_ring(hole) for hole in holes_raw]
    courtyard = bool(holes)
    if len(outer) < 3:
        return {
            "shape": "unknown",
            "corners": len(outer),
            "aspect": None,
            "convex": False,
            "courtyard": courtyard,
            "curvilinear_perimeter": curvilinear,
            "dims_mm": None,
            "area_m2": None,
            "valid": False,
            "description": "контур не определён",
        }

    xs = [point[0] for point in outer]
    ys = [point[1] for point in outer]
    width = max(xs) - min(xs)
    depth = max(ys) - min(ys)
    dims = [width, depth]
    aspect = None if depth <= _POINT_EPS else round(width / depth, 6)
    outer_area = abs(_signed_area_mm2(outer))
    holes_area = sum(abs(_signed_area_mm2(hole)) for hole in holes
                     if len(hole) >= 3)
    area_m2 = max(0.0, outer_area - holes_area) / 1_000_000.0

    valid = (
        width > _POINT_EPS
        and depth > _POINT_EPS
        and outer_area > _POINT_EPS
        and _simple_ring(outer)
        and all(
            len(hole) >= 3
            and abs(_signed_area_mm2(hole)) > _POINT_EPS
            and _simple_ring(hole)
            and _point_in_ring(hole[0], outer)
            and not _rings_intersect(outer, hole)
            for hole in holes
        )
        and all(
            not _rings_intersect(holes[left], holes[right])
            and not _point_in_ring(holes[left][0], holes[right])
            and not _point_in_ring(holes[right][0], holes[left])
            for left in range(len(holes))
            for right in range(left + 1, len(holes))
        )
    )
    is_convex = valid and not courtyard and not curvilinear and _convex(outer)
    shape: ShapeKind = "complex"
    reflex = _orthogonal_reflex_indices(outer) if valid else None
    if valid and not courtyard and not curvilinear and reflex is not None:
        if len(outer) == 4 and len(reflex) == 0:
            shape = "rectangle"
        elif len(outer) == 6 and len(reflex) == 1:
            shape = "L"
        elif len(outer) == 8:
            shape = _eight_corner_shape(outer, reflex)

    # Endpoint chords do not prove an arc's extrema or enclosed area.  Keep
    # those facts unknown until the contour contract carries full arc geometry.
    reported_dims = None if curvilinear else dims
    reported_aspect = None if curvilinear else aspect
    reported_area = round(area_m2, 6) if valid and not curvilinear else None

    description = _shape_description(
        shape,
        len(outer),
        reported_aspect,
        courtyard,
        curvilinear,
        reported_area,
        valid,
    )
    return {
        "shape": shape,
        "corners": len(outer),
        "aspect": reported_aspect,
        "convex": bool(is_convex),
        "courtyard": courtyard,
        "curvilinear_perimeter": curvilinear,
        "dims_mm": reported_dims,
        "area_m2": reported_area,
        "valid": valid,
        "description": description,
    }


def _walk(node: TreeNode) -> Iterator[TreeNode]:
    yield node
    for child in node["children"]:
        yield from _walk(child)


def _nodes_of_kind(node: TreeNode, kind: str) -> list[TreeNode]:
    return [candidate for candidate in _walk(node) if candidate["kind"] == kind]


def _profile_from_l3(
    tree: TreeNode,
    document: L0Document,
) -> Any | None:
    """Use a single proven lowest-floor op profile, never bbox geometry."""

    elevations = {level.name: level.elevation_mm for level in document.levels}
    candidates: list[tuple[float, str, Any]] = []
    for leaf in iter_l1_leaves(tree):
        if leaf["kind"] != "op" or leaf["op_name"] != "create_floor":
            continue
        outline = leaf["params"].get("outline")
        if outline is None:
            continue
        level_name = leaf["level_name"]
        elevation = elevations.get(
            level_name, math.inf) if level_name is not None else math.inf
        candidates.append((elevation, leaf["source_element_id"], {
            "outer": outline,
            "holes": leaf["params"].get("holes", []),
        }))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    lowest = candidates[0][0]
    lowest_profiles = [item for item in candidates if item[0] == lowest]
    # Multiple slabs require a real polygon union, not arbitrary selection.
    return lowest_profiles[0][2] if len(lowest_profiles) == 1 else None


def _room_nodes(node: TreeNode) -> list[TreeNode]:
    return _nodes_of_kind(node, "room")


def _room_name(node: TreeNode) -> str:
    return node["label"].strip()


def _known_area(node: TreeNode) -> float | None:
    values = [
        float(room["facts"]["area_m2"])
        for room in _room_nodes(node)
        if isinstance(room["facts"].get("area_m2"), (int, float))
        and not isinstance(room["facts"].get("area_m2"), bool)
    ]
    return sum(values) if values else None


def _habitable_room_count(node: TreeNode) -> int | None:
    names = [_room_name(room) for room in _room_nodes(node)]
    count = sum(bool(_HABITABLE_RE.search(name)) for name in names)
    return count or None


def _format_area(area_m2: float) -> str:
    return _format_decimal(area_m2, 1)


def _apartment_label(node: TreeNode) -> str:
    room_count = _habitable_room_count(node)
    area = _known_area(node)
    parts = ["Квартира"]
    if room_count is not None:
        parts.append(f"{room_count}-комн.")
    if area is not None:
        parts.append(f"{_format_area(area)} м²")
        node["facts"]["area_m2"] = area
    return " ".join(parts)


def _level_range(levels: Sequence[Any]) -> str:
    names = [str(level) for level in levels]
    parsed = [_TRAILING_NUMBER_RE.match(name) for name in names]
    if names and all(match is not None for match in parsed):
        matches = [match for match in parsed if match is not None]
        prefixes = {match.group(1).strip().casefold() for match in matches}
        numbers = [int(match.group(2)) for match in matches]
        if len(prefixes) == 1 and sorted(set(numbers)) == list(
                range(min(numbers), max(numbers) + 1)):
            return (
                str(numbers[0]) if len(numbers) == 1
                else f"{min(numbers)}-{max(numbers)}"
            )
    return ", ".join(names)


def _stack_context(tree: TreeNode) -> tuple[dict[str, str], dict[str, str]]:
    floor_ranges: dict[str, str] = {}
    stack_ranges: dict[str, str] = {}
    for stack in _nodes_of_kind(tree, "stack"):
        macro = stack["macro"] or {}
        levels = macro.get("levels")
        if not isinstance(levels, list) or len(levels) < 2:
            continue
        display = _level_range(levels)
        stack_ranges[stack["node_id"]] = display
        for child in stack["children"]:
            if child["kind"] == "floor":
                floor_ranges[child["node_id"]] = display
    return floor_ranges, stack_ranges


def _room_model_name(node: TreeNode, document: L0Document) -> str:
    names_by_id = {room.id: room.name for room in document.rooms}
    source_names = sorted({
        names_by_id[leaf["source_element_id"]]
        for leaf in iter_l1_leaves(node)
        if leaf["source_element_id"] in names_by_id
    })
    return source_names[0] if len(source_names) == 1 else node["label"]


def _base_label(
    node: TreeNode,
    document: L0Document,
    floor_ranges: Mapping[str, str],
    stack_ranges: Mapping[str, str],
    section_numbers: Mapping[str, int],
) -> str:
    kind = node["kind"]
    if kind == "building":
        return document.doc_name
    if kind == "section":
        return f"Секция {section_numbers[node['node_id']]}"
    if kind == "stack":
        display = stack_ranges.get(node["node_id"])
        return f"Типовые этажи {display}" if display else "Повторяющиеся этажи"
    if kind == "floor":
        macro = node["macro"] or {}
        level_name = str(macro.get("level_name") or node["label"] or "Level")
        display = floor_ranges.get(node["node_id"])
        return (
            f"{level_name} (типовой, ={display})"
            if display else level_name
        )
    if kind == "apartment":
        return _apartment_label(node)
    if kind == "core":
        return "Лестнично-лифтовой узел"
    if kind == "mop":
        return "Места общего пользования"
    if kind == "room":
        return _room_model_name(node, document)
    if kind in {"atom_cluster", "atom_summary"}:
        macro = node["macro"] or {}
        count = macro.get("count", node["facts"]["element_count"])
        category = macro.get("category_ru") or macro.get("category") or "атомы"
        type_name = macro.get("type_name")
        suffix = "" if not type_name or type_name == "<mixed>" else f" — {type_name}"
        return f"{count} × {category}{suffix}"
    if kind == "atom" and node["payload"] is not None:
        payload = node["payload"]
        if payload["kind"] == "atom":
            category = payload["category_ru"] or payload["category"]
            return f"{category} — {payload['type_name']}"
    if kind == "op" and node["payload"] is not None:
        payload = node["payload"]
        if payload["kind"] == "op":
            suffix = f" — {payload['type_name']}" if payload["type_name"] else ""
            return f"{payload['op_name']}{suffix}"
    return node["label"] or kind


def _document_height_mm(document: L0Document, tree: TreeNode) -> float | None:
    bounds = [
        (element.bbox_min_mm[2], element.bbox_max_mm[2])
        for element in document.elements
        if element.category not in _PHYSICAL_HEIGHT_EXCLUSIONS
        and element.bbox_min_mm is not None
        and element.bbox_max_mm is not None
    ]
    if bounds:
        floor_elevations = _floor_elevations(tree)
        minimum = min(low for low, _high in bounds)
        if floor_elevations:
            minimum = min(minimum, floor_elevations[0])
        height = max(high for _low, high in bounds) - minimum
        if height > 0.0:
            return height
    elevations = sorted({
        float((floor["macro"] or {})["elevation_mm"])
        for floor in _nodes_of_kind(tree, "floor")
        if isinstance((floor["macro"] or {}).get("elevation_mm"), (int, float))
        and not isinstance((floor["macro"] or {}).get("elevation_mm"), bool)
    })
    typical = _typical_height_mm(elevations)
    if elevations and typical is not None:
        return elevations[-1] - elevations[0] + typical
    return None


def _typical_height_mm(elevations: Sequence[float]) -> float | None:
    deltas = [
        elevations[index + 1] - elevations[index]
        for index in range(len(elevations) - 1)
        if elevations[index + 1] > elevations[index]
    ]
    if not deltas:
        return None
    buckets: dict[int, list[float]] = {}
    for delta in deltas:
        buckets.setdefault(round(delta / 50.0), []).append(delta)
    _bucket, values = min(
        buckets.items(),
        key=lambda item: (-len(item[1]), statistics.median(item[1]), item[0]),
    )
    return float(statistics.median(values))


def label_tree(
    tree: TreeNode,
    document: L0Document,
    *,
    shape: ShapeClassification | None = None,
    use_llm_labels: bool | None = None,
    llm_labeler: LabelDecorator | None = None,
) -> TreeNode:
    """Return a deeply copied tree with deterministic fact-template labels."""

    if tree.get("kind") != "building":
        raise NameStageError("NAME requires an L3 building root")
    named = copy.deepcopy(tree)
    floor_ranges, stack_ranges = _stack_context(named)
    sections = sorted(
        _nodes_of_kind(named, "section"), key=lambda node: node["node_id"])
    section_numbers = {
        node["node_id"]: index + 1 for index, node in enumerate(sections)
    }
    decorate = USE_LLM_LABELS if use_llm_labels is None else use_llm_labels

    def visit(node: TreeNode) -> None:
        for child in node["children"]:
            visit(child)
        area = _known_area(node) if node["kind"] in {
            "apartment", "floor", "section", "building",
        } else None
        if area is not None:
            node["facts"]["area_m2"] = area
        base = _base_label(
            node,
            document,
            floor_ranges,
            stack_ranges,
            section_numbers,
        )
        if decorate and llm_labeler is not None:
            decorated = llm_labeler(
                node["kind"], base, copy.deepcopy(node["facts"]))
            if not isinstance(decorated, str) or not decorated.strip():
                raise NameStageError("LLM label decorator returned an invalid label")
            base = decorated.strip()
        node["label"] = base

    visit(named)
    if shape is not None:
        named["facts"]["shape"] = (
            None if shape["shape"] == "unknown" else shape["shape"])
        if shape["area_m2"] is not None:
            named["facts"]["area_m2"] = shape["area_m2"]
        if shape["dims_mm"] is not None:
            existing = named["facts"].get("dims_mm")
            existing_height = (
                existing[2]
                if isinstance(existing, list) and len(existing) == 3
                else None
            )
            height = _document_height_mm(document, named)
            proven_height = height if height is not None else existing_height
            if proven_height is not None:
                named["facts"]["dims_mm"] = [
                    shape["dims_mm"][0],
                    shape["dims_mm"][1],
                    proven_height,
                ]
    return named


def _floor_elevations(tree: TreeNode) -> list[float]:
    return sorted({
        float((floor["macro"] or {})["elevation_mm"])
        for floor in _nodes_of_kind(tree, "floor")
        if isinstance((floor["macro"] or {}).get("elevation_mm"), (int, float))
        and not isinstance((floor["macro"] or {}).get("elevation_mm"), bool)
    })


def _typical_floor(tree: TreeNode) -> TreeNode | None:
    stacks: list[tuple[int, float, str, TreeNode]] = []
    for stack in _nodes_of_kind(tree, "stack"):
        floors = [child for child in stack["children"] if child["kind"] == "floor"]
        if len(floors) < 2:
            continue
        elevations = [
            float((floor["macro"] or {}).get("elevation_mm", math.inf))
            for floor in floors
        ]
        template_id = (stack["macro"] or {}).get("template_node_id")
        template = next(
            (floor for floor in floors if floor["node_id"] == template_id),
            floors[0],
        )
        stacks.append((len(floors), min(elevations), stack["node_id"], template))
    if not stacks:
        return None
    return min(stacks, key=lambda item: (-item[0], item[1], item[2]))[3]


def _purpose(document: L0Document) -> str:
    residential = 0
    office = 0
    considered = 0
    for room in sorted(document.rooms, key=lambda item: item.id):
        name = room.name.strip()
        if not name or _MOP_RE.search(name):
            continue
        considered += 1
        if _OFFICE_RE.search(name):
            office += 1
        elif _RESIDENTIAL_RE.search(name):
            residential += 1
    if considered == 0:
        return "не определено"
    if residential / considered > 0.60:
        return "жилой дом"
    if office / considered > 0.60:
        return "офис"
    if residential and office:
        return "многофункциональное"
    return "не определено"


def _roof_kind(tree: TreeNode) -> Literal["flat", "pitched", "unknown"]:
    roof_ops = 0
    roof_atoms = 0
    for leaf in iter_l1_leaves(tree):
        if leaf["kind"] == "op" and leaf["op_name"] == "create_roof":
            roof_ops += 1
        elif leaf["kind"] == "atom" and leaf["category"] == "OST_Roofs":
            roof_atoms += 1
    # Current create_roof's compiler contract is a flat FootPrintRoof.  Mixed
    # op/atom evidence remains unknown rather than laundering the atom.
    if roof_ops and not roof_atoms:
        return "flat"
    return "unknown"


def _apartment_types(floor: TreeNode) -> tuple[int, str]:
    apartments = _nodes_of_kind(floor, "apartment")
    histogram: Counter[tuple[int | None, float | None]] = Counter()
    for apartment in apartments:
        rooms = _habitable_room_count(apartment)
        area = _known_area(apartment)
        histogram[(rooms, None if area is None else round(area, 1))] += 1
    if not histogram:
        return 0, "нет данных"
    rendered: list[str] = []
    for (rooms, area), count in sorted(
        histogram.items(),
        key=lambda item: (
            item[0][0] is None,
            item[0][0] or 0,
            item[0][1] is None,
            item[0][1] or 0.0,
        ),
    ):
        parts = []
        if rooms is not None:
            parts.append(f"{rooms}-комн.")
        if area is not None:
            parts.append(f"{_format_area(area)} м²")
        text = " ".join(parts) or "тип не определён"
        if count > 1:
            text += f" ×{count}"
        rendered.append(text)
    return len(apartments), ", ".join(rendered)


def _shape_head(shape: ShapeClassification) -> str:
    return {
        "rectangle": "Прямоугольное здание",
        "L": "Г-образное здание",
        "T": "Т-образное здание",
        "U": "П-образное здание",
        "complex": f"Здание: {shape['description']}",
        "unknown": "Здание, контур не определён",
    }[shape["shape"]]


def _format_metres(mm: float) -> str:
    return _format_decimal(mm / 1_000.0, 2)


def build_gestalt(
    document: L0Document,
    tree: TreeNode,
    shape: ShapeClassification,
) -> str:
    """Render Part 7.2 solely from deterministic model/tree facts."""

    head_parts = [_shape_head(shape)]
    if shape["dims_mm"] is not None:
        head_parts.append(
            f"{_format_metres(shape['dims_mm'][0])}×"
            f"{_format_metres(shape['dims_mm'][1])} м")
    sections = len(_nodes_of_kind(tree, "section"))
    if sections > 1:
        head_parts.append(_russian_count(
            sections, "секция", "секции", "секций"))

    floors = _nodes_of_kind(tree, "floor")
    elevations = _floor_elevations(tree)
    typical_height = _typical_height_mm(elevations)
    height = _document_height_mm(document, tree)
    floor_phrase = _russian_count(len(floors), "этаж", "этажа", "этажей")
    if typical_height is not None:
        floor_phrase += f" по {_format_metres(typical_height)} м"
    if height is not None:
        floor_phrase += f" (высота {_format_metres(height)} м)"
    head_parts.append(floor_phrase)

    roof = _roof_kind(tree)
    head_parts.append({
        "flat": "плоская кровля",
        "pitched": "скатная кровля",
        "unknown": "кровля не определена",
    }[roof])
    first_sentence = ", ".join(head_parts) + "."
    second_sentence = f"Назначение: {_purpose(document)}."

    typical_floor = _typical_floor(tree)
    if typical_floor is None:
        third_sentence = "Типовой этаж: не определён."
    else:
        apartments, apartment_types = _apartment_types(typical_floor)
        cores = len(_nodes_of_kind(typical_floor, "core"))
        third_sentence = (
            f"Типовой этаж: {apartments} кв. ({apartment_types}), "
            f"{cores} ЛК."
        )
    return " ".join((first_sentence, second_sentence, third_sentence))


def name_document(
    document: L0Document,
    tree: TreeNode,
    outline_points: Any | None = None,
    *,
    use_llm_labels: bool | None = None,
    llm_labeler: LabelDecorator | None = None,
) -> NameResult:
    """Run NAME over one L0 document and its corresponding L3 building tree."""

    if tree.get("kind") != "building":
        raise NameStageError("NAME requires an L3 building root")
    proven_outline = (
        outline_points
        if outline_points is not None
        else _profile_from_l3(tree, document)
    )
    shape = shape_of(proven_outline)
    named_tree = label_tree(
        tree,
        document,
        shape=shape,
        use_llm_labels=use_llm_labels,
        llm_labeler=llm_labeler,
    )
    return {
        "tree": named_tree,
        "gestalt": build_gestalt(document, named_tree, shape),
        "shape": shape,
    }


def name_tree(
    tree: TreeNode,
    document: L0Document,
    outline_points: Any | None = None,
    **kwargs: Any,
) -> NameResult:
    """Tree-first convenience alias for pipeline composition."""

    return name_document(document, tree, outline_points, **kwargs)


def gestalt_of(
    tree: TreeNode,
    document: L0Document,
    outline_points: Any | None = None,
) -> str:
    """Return just the deterministic gestalt for callers not yet using L4."""

    return name_document(document, tree, outline_points)["gestalt"]


__all__ = [
    "ContourError",
    "LabelDecorator",
    "NameResult",
    "NameStageError",
    "ShapeClassification",
    "ShapeKind",
    "USE_LLM_LABELS",
    "build_gestalt",
    "gestalt_of",
    "label_tree",
    "name_document",
    "name_tree",
    "shape_of",
]
