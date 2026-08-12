"""Deterministic DECOMPILE FOLD: flat L1 nodes to a compact L3 tree.

The transform follows Part 6's order: semantic grouping inside each floor,
then horizontal rows/arrays, then vertical stacks over the already-folded
floor subtrees.  It is offline, geometry/hash based, and preserves an exact
ledger of every input L1 node even when a visible summary represents many
atoms.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping, Sequence, TypedDict, cast

from kukai.ir.decompile.l1_schema import (
    L1AtomNode,
    L1Node,
    L1OpNode,
    L1SchemaError,
    validate_l1_nodes,
)
from kukai.ir.decompile.group_extract import GroupIndexPayloadError
from kukai.ir.decompile.group_relations import (
    GroupIndexInput,
    analyze_group_relations,
)
from kukai.ir.decompile.schema import (
    ATOM_CELL_MM,
    ATOM_CLUSTER_MIN,
    ATOM_LEAF_CAP,
    CANON_MM,
    DZ_TOL,
    GRID_COVERAGE,
    GRID_REL_TOL,
    MIN_ARRAY,
    MIN_ROW,
    SIM_THRESHOLD,
    ZONE_CELL_MM,
    L0Document,
    L0Element,
    RoomInfo,
)


class FoldError(ValueError):
    """FOLD cannot safely consume the supplied L0/L1 contract."""


class TreeFacts(TypedDict):
    bbox_min_mm: list[float] | None
    bbox_max_mm: list[float] | None
    shape: str | None
    dims_mm: list[float] | None
    area_m2: float | None
    element_count: int
    op_histogram: dict[str, int]


class TreeNode(TypedDict):
    node_id: str
    kind: str
    label: str
    children: list["TreeNode"]
    payload: L1Node | None
    # Summary/macro nodes keep exact payloads here rather than exposing one
    # child per element.  iter_l1_leaves expands this preservation ledger.
    members: list[L1Node]
    macro: dict[str, Any] | None
    facts: TreeFacts
    verdict: None


_MOP_RE = re.compile(
    r"коридор|лестнич|лифт|тамбур|холл|вестибюль|моп|лестн.?\s*клетк|"
    r"corridor|hall(?:way)?|lobby|stair|stairwell|elevator|lift|foyer|"
    r"vestibule|entrance|utility|mechanical|electrical|riser|shaft|mop|core",
    re.IGNORECASE,
)

_COORDINATE_FIELDS = frozenset({
    "p0_mm", "p1_mm", "xy", "anchor_mm", "origin_mm", "origin",
    "bbox_min_mm", "bbox_max_mm", "outline", "holes", "center_mm",
    # Live place_family evidence 2026-07-21: «xyz» отсутствовал в списке →
    # Δ-перенос НЕ двигал мебель (создавалась по оригинальным xy ВНУТРИ
    # здания) и канон place_family не был трансляционно-инвариантен.  Оба
    # потребителя (component._translate_leaf и канон-локализация) делят этот
    # список — одно поле чинит обоих.
    "xyz",
    # Tier-G atom escrow materializes a mesh in world millimetres.  Its
    # vertices are coordinates just as much as wall endpoints: component
    # localization and rebuild offset must move them through the same single
    # coordinate authority, or the DirectShape would stay at the source while
    # the semantic building moves.
    "vertices_mm",
    # ТОТ ЖЕ УРОК, ВОЛНОЙ ПОЗЖЕ (живой прогон №9, v15, 29.07):
    # «position_mm» у create_curtain_grid_line отсутствовал здесь, и
    # Δ-перенос двигал СТЕНУ, но не точку её линии разрезки. Замер по
    # артефактам того прогона: в программе стена уехала на
    # p0_mm=[637652.0, 15682.0], а позиция линии осталась
    # [7717.8, 28822.4, 4925.0] — координаты ОРИГИНАЛА. Пересборка при этом
    # умерла на откате коммита с посланной Revit ошибкой «Не удалось создать
    # импост витража. Та часть схемы разрезки витража, на которой он был
    # размещён, больше не существует».
    #
    # Второе следствие ровно то же, что у «xyz»: без этого поля канон не
    # трансляционно-инвариантен, и лист линии НИКОГДА не совпал бы с
    # оригиналом в сравнении идемпотентности, даже если бы сборка прошла.
    "position_mm",
})
_LEVEL_SELECTOR_FIELDS = frozenset({"level", "base_level", "top_level"})
# Periodic angles — canonicalized mod 360 (360°≡0°).  place_family rotation
# (live antresol furniture 2026-07-21: flip-composition reads a full turn).
_ANGLE_FIELDS = frozenset({"rotation_deg"})
_VOLATILE_FIELDS = frozenset({
    "_id", "id", "node_id", "source_element_id", "source_element_ids",
    "level_name", "label", "template_node_id",
})

# Hash semantics are public data contracts.  Template v2 adds ``center_mm`` to
# the shared coordinate authority (arc translation/localisation); every other
# template-equivalence rule, including host/level wildcarding, remains intact.
# Fidelity canon is deliberately separate: A5 is a proof, not a template
# search, and therefore retains level binding and graph-target identity.
# /3 (2026-07-26): дименсиональные сетки — оси и радианы больше не округляются
# по миллиметровой сетке, безразмерные скаляры тоже; версия вошла в canon_hash.
# /4 (2026-07-28): раздел зонной группы читается из таблицы экстрактора, а не
# из собственного словаря fold.py.  Macro discipline-группы несёт
# `{"discipline": ...}` и входит в канон поддерева, а лексикон сменился
# целиком («architecture»→«architectural», «coordination»→«shared») и стал
# покрывать все 47 категорий вместо 17 — то есть у тех же элементов меняется
# и раскладка, и tree-хеш.  Смысловая смена канона, а не переименование.
TEMPLATE_CANON_VERSION = "template-canon/4"
# /2 (2026-07-28): контурные полы (create_floor_by_contour) — первая живая
# пересборка (№7, v12) построилась но не сошлась в каноне: extra_rebuilt
# 11438487 против ожидаемого 9981227, ТОТ ЖЕ лист. Замер по дампу
# (idempotence_debug.json): (a) петля дыры читается relift'ом с ДРУГОГО
# первого узла (edge 1->0) — те же points_mm/arcs данные на уровень глубже,
# чем `_canonical_ring` искал (`{"shape","points_mm","arcs"}`, не голый
# список под "outline"/"holes"), так рефайнмент кольца ни разу не срабатывал
# для этого опа; (b) bulge — безразмерный скаляр на сетке 1e-9
# (_FIDELITY_SCALAR_STEP), а шум раунд-трипа через эмиссию+relift садится в
# 6-7-й знак (~1.3e-6 на хорде ~3925мм) — грид на 3 порядка точнее самого
# шума, никогда не сходится.
# /3 (2026-07-29, кодекс-ревью tasks/b8f3v4r97.output сессии eeccfb91, шов
# №5/№6/№8 — все три канона /2, автор тот же):
#   №5 (P1) — bulge-квантование /2 (safety*2*CANON_MM/chord) ЛОЖНО сходилось:
#   на хорде 4000мм bulge=0.09951 и 0.10049 (шаг там был 0.001) получали ОДИН
#   hash, хотя середины дуг различаются на 1.96мм — БОЛЬШЕ CANON_MM=1. Причина
#   структурная: безразмерный bulge квантуется на сетке, подобранной ПОД
#   ОДНУ хорду, а не на сетке точек. Правка кодекса — канонизировать не
#   bulge, а физическую mid-sweep точку дуги (contour.bulge_midpoint) на
#   ТОЙ ЖЕ мм-сетке, что вершины (_round_mm/CANON_MM). Больше нет отдельной
#   "безопасной" константы для bulge вообще — есть один и тот же допуск для
#   любой точки контура, дуговой или прямой.
#   №6 (P1) — radius_mm/dir-форма дуги вообще выпадала из /2 (канон принимал
#   только {"edge","bulge"} и возвращал сырой ring без нормализации). Правка
#   — оба представления дуги лежат ЧЕРЕЗ ОДНУ функцию понижения
#   (_effective_bulge зовёт contour.radius_to_bulge на radius-форме), после
#   чего обе формы неотличимы для канона: один и тот же mid-sweep точка.
#   №8 (P1, канон-половина; лифт-половина у lift.py, вне этой волны по
#   границам) — height_offset_mm: канон не считал absent≡0мм, хотя семантика
#   опа именно такая (authoring.py ставит параметр, только если ключ
#   присутствует вообще). См. _FIDELITY_ABSENT_DEFAULTS.
FIDELITY_CANON_VERSION = "fidelity-canon/4"

_FIDELITY_ANGLE_STEP_DEG = 0.1
_FIDELITY_RADIAL_STEP_MM = 0.5
_FIDELITY_AXIS_STEP = 1e-6
_FIDELITY_RADIAN_STEP = 1e-6
_FIDELITY_SCALAR_STEP = 1e-9
_FIDELITY_RADIAL_FIELDS = frozenset({"radius_mm", "diameter_mm"})
_FIDELITY_AXIS_FIELDS = frozenset({"x_axis", "y_axis"})
_FIDELITY_RADIAN_FIELDS = frozenset({
    "start_angle_rad", "end_angle_rad",
})
_GRAPH_REFINEMENT_ROUNDS = 16

# codex #8 (2026-07-29): ops whose optional params have a semantic default
# that "absent" must canonicalize IDENTICALLY to. height_offset_mm is only
# ever set on these two ops when the source read a value at all
# (authoring.py's ho_set is "" when the key is missing — no witness, no
# emitted Set() call) — its absence IS a typed zero, not an unknown. Applied
# at the op level (_fidelity_canonical_l1), not as a generic "_mm fields
# default to 0" rule: that would silently paper over a genuinely-missing
# required field on some OTHER op the day one is added.
_FIDELITY_ABSENT_DEFAULTS: dict[str, dict[str, float]] = {
    "create_floor": {"height_offset_mm": 0.0},
    "create_floor_by_contour": {"height_offset_mm": 0.0},
}


def _volatile_field(field_name: str) -> bool:
    return (
        field_name in _VOLATILE_FIELDS
        or field_name.endswith("_id")
        or field_name.endswith("_ids")
    )


def stable_tree_id(kind: str, source_element_ids: Iterable[str]) -> str:
    """Return Part 6.7's identity from kind plus sorted descendant sources."""

    payload = json.dumps(
        [kind, sorted(source_element_ids)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _round_mm(value: float) -> float:
    rounded = round(float(value) / CANON_MM) * CANON_MM
    return 0.0 if rounded == 0.0 else rounded


def _canonical_rotation(value: float) -> float:
    """Canonical angle: rotation is periodic, so 360°≡0°.

    A flip-composition can leave a family instance reading 360° where the
    lifted original was 0° (live antresol furniture 2026-07-21: hand-flip +
    pre-rotation compose to a full turn); geometrically identical, but a raw
    canon treated 360.0 ≠ 0.0.  Normalize to [0,360) on the canon grid, with a
    wrap guard so a float that rounds up onto 360 folds back to 0.
    """
    rounded = _round_mm(float(value) % 360.0)
    if rounded >= 360.0:
        rounded -= 360.0
    return 0.0 if rounded == 0.0 else rounded


def _canonical_arc_branch(arc: Any) -> Any:
    """Одна дуга — одна ветвь 2π.

    Углы дуги периодичны так же, как rotation_deg (у которого приведение
    есть с 2026-07-21), но радианы его не получили: _FIDELITY_RADIAN_FIELDS
    только квантуются на сетке 1e-6. Живой замер (пересборка №11, v18):
    декомпиляция хранит start=3.4732052114687098, обратное чтение из Revit
    возвращает -2.8099800957108703 — atan2 отдаёт (-pi, pi], разница ровно
    1.0*2pi. Та же дуга, тот же радиус, те же оси — и разный канон; четыре
    дуговые стены из пяти не сошлись только из-за этого.

    Сдвигается ПАРА, а не каждый угол по отдельности: развёртка end-start
    физически определяет дугу и обязана сохраниться бит-в-бит. Независимое
    приведение по модулю схлопнуло бы дугу развёрткой 3pi с дугой развёрткой
    pi — разные дуги под одним хешем, ровно та беда, от которой канон и
    существует.
    """
    if not isinstance(arc, dict):
        return arc
    start, end = arc.get("start_angle_rad"), arc.get("end_angle_rad")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in (start, end)):
        return arc
    turns = math.floor(float(start) / (2.0 * math.pi))
    if turns == 0:
        return arc
    shifted = dict(arc)
    shifted["start_angle_rad"] = float(start) - turns * 2.0 * math.pi
    shifted["end_angle_rad"] = float(end) - turns * 2.0 * math.pi
    return shifted


def _arc_endpoints(arc: Mapping[str, Any]) -> tuple[list[float], list[float]] | None:
    """Концы дуги по её собственным параметрам, или None если форма не та."""
    try:
        c = [float(v) for v in arc["center_mm"]]
        xa = [float(v) for v in arc["x_axis"]]
        ya = [float(v) for v in arc["y_axis"]]
        r = float(arc["radius_mm"])
        s, e = float(arc["start_angle_rad"]), float(arc["end_angle_rad"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None

    def at(t: float) -> list[float]:
        return [c[0] + r * (math.cos(t) * xa[0] + math.sin(t) * ya[0]),
                c[1] + r * (math.cos(t) * xa[1] + math.sin(t) * ya[1])]

    return at(s), at(e)


def _localize_coordinates(value: Any, origin: Sequence[float]) -> Any:
    if isinstance(value, list):
        if (len(value) in (2, 3)
                and all(isinstance(item, (int, float))
                        and not isinstance(item, bool) for item in value)):
            return [
                _round_mm(float(component) - float(origin[index]))
                for index, component in enumerate(value)
            ]
        return [_localize_coordinates(item, origin) for item in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _round_mm(float(value))
    return value


def _canonical_ring(points: Any) -> Any:
    """Canonical cyclic form of a closed ring (rotation+direction invariant).

    Live floor evidence 2026-07-21: Revit rebuilds a floor sketch and reads the
    loop back starting from ITS OWN internal first segment — the start vertex
    (and potentially the winding) of an outline is Revit-incidental, not a
    defining DOF.  Canon identity of a ring is the cyclic sequence itself:
    pick the lexicographically smallest rotation over both directions.
    Non-ring shapes pass through untouched (fail-open for atoms/junk)."""
    if not isinstance(points, list) or len(points) < 3:
        return points
    if not all(isinstance(p, list) and len(p) >= 2 for p in points):
        return points
    best = None
    for seq in (points, points[::-1]):
        for i in range(len(seq)):
            cand = tuple(tuple(pt) for pt in (seq[i:] + seq[:i]))
            if best is None or cand < best:
                best = cand
    return [list(pt) for pt in best]


def _canonical_value(
    value: Any,
    origin: Sequence[float],
    *,
    field_name: str | None = None,
) -> Any:
    if field_name in _COORDINATE_FIELDS:
        localized = _localize_coordinates(value, origin)
        if field_name == "outline":
            return _canonical_ring(localized)
        if field_name == "holes" and isinstance(localized, list):
            rings = [_canonical_ring(ring) for ring in localized]
            try:
                rings.sort(key=lambda r: json.dumps(r))
            except TypeError:
                pass
            return rings
        return localized
    if field_name == "elevation_mm" or field_name == "elev_mm":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _round_mm(float(value) - float(origin[2]))
    if field_name in _ANGLE_FIELDS:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _canonical_rotation(float(value))
    # Дименсиональная граница канона.  Wildcarding уровней/ref-ов ниже —
    # НАМЕРЕННОЕ обобщение шаблона; миллиметровая сетка на величине, которая не
    # в миллиметрах, — просто ошибка размерности.  Разбор 2026-07-25 §3.2
    # воспроизвёл её последствие: ось [0.7071, 0.7071, 0] округлялась в
    # [1.0, 1.0, 0.0] (переставая быть единичной), радианы ложились на сетку
    # ≈57.3°, и две разные дуговые стены давали ОДИН канон — то есть два разных
    # здания под общим merkle/dedup/rebuild/journal.  Сетки те же, что у
    # FidelityCanon: единственная разница между канонами должна быть в том, ЧТО
    # обобщается, а не в том, как округляется число.
    if field_name in _FIDELITY_AXIS_FIELDS:
        return _fidelity_axis(value)
    if field_name in _FIDELITY_RADIAN_FIELDS:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _round_step(float(value), _FIDELITY_RADIAN_STEP)
    if isinstance(value, dict):
        # Level names/ids vary by storey but express the same relative binding.
        if field_name in _LEVEL_SELECTOR_FIELDS and value.get("by") == "name":
            return {"by": "name", "value": "<level>"}
        result: dict[str, Any] = {}
        for key in sorted(value):
            if _volatile_field(key):
                continue
            if key == "ref":
                # Preserve that a topology reference exists, not its volatile
                # source-derived target id.
                result[key] = "<ref>"
                continue
            result[key] = _canonical_value(
                value[key], origin, field_name=key)
        return result
    if isinstance(value, list):
        return [
            _canonical_value(item, origin, field_name=field_name)
            for item in value
        ]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if field_name is not None and field_name.endswith("_mm"):
            return _round_mm(float(value))
        # Безразмерное/неизвестное НЕ наследует миллиметровую сетку: иначе
        # coverage 0.8 канонически равен 1.0 (массив на 80% == полный).  Мм-сетка
        # для *_mm сохранена НАМЕРЕННО — дедуп обязан переживать субмиллиметровый
        # float-шум ревитовской геометрии (живое свидетельство 2026-07-21:
        # 10/40 стен промахивались мимо канона из-за дрейфа 0.5 мм).
        return _round_step(float(value), _FIDELITY_SCALAR_STEP)
    return value


def _canonical_l1(node: L1Node, origin_mm: Sequence[float]) -> dict[str, Any]:
    canonical = cast(dict[str, Any], _canonical_value(node, origin_mm))
    if node["kind"] == "op":
        # Canon identity of an OP is its DEFINING DOF: op_name + type_name +
        # params (the materializer rebuilds the element from params ALONE, so
        # equal params ⇒ an identical element).  ``anchor_mm`` is a DERIVED
        # convenience (grid/progression detection, passport) computed from RAW
        # Revit geometry with float noise: on a rounding tie it lands one
        # CANON_MM cell away from the midpoint of the node's own rounded
        # endpoints (live A5 evidence 2026-07-21: 10/40 walls "missed" canon by
        # a 0.5mm anchor drift while p0/p1 matched exactly).  Derived values
        # are excluded from identity — they can only double-count noise.
        # ATOMS keep their anchor: an atom has no params, so its measured
        # anchor/bbox ARE its identity.
        canonical.pop("anchor_mm", None)
        if node["op_name"] == "create_level":
            params = canonical.get("params")
            if isinstance(params, dict):
                # A level's display name is the vertical instance label, not
                # part of a repeated floor template.
                params.pop("name", None)
    return canonical


def canon_op(node: L1Node, origin_mm: Sequence[float]) -> str:
    """Return Part 6.1 stable JSON for one localized L1 operation/atom."""

    if len(origin_mm) != 3:
        raise ValueError("origin_mm must contain exactly three coordinates")
    return json.dumps(
        _canonical_l1(node, origin_mm),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_tree(node: TreeNode, origin_mm: Sequence[float]) -> dict[str, Any]:
    result: dict[str, Any] = {"kind": node["kind"]}
    if node["payload"] is not None:
        result["payload"] = _canonical_l1(node["payload"], origin_mm)
    if node["members"]:
        result["members"] = sorted(
            canon_op(member, origin_mm) for member in node["members"])
    if node["children"]:
        children = [
            _canonical_tree(child, origin_mm) for child in node["children"]
        ]
        result["children"] = sorted(
            children,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")),
        )
    if node["macro"] is not None:
        # Membership lists/diffs describe where repetitions occurred, not the
        # repeated structural template itself.
        macro = {
            key: value for key, value in node["macro"].items()
            if key not in {"levels", "diffs", "template_node_id"}
        }
        result["macro"] = _canonical_value(macro, origin_mm)
    return result


def canon_hash(node: L1Node | TreeNode, origin_mm: Sequence[float]) -> str:
    """Return a recursive canonical SHA-1 for an L1 leaf or L3 subtree.

    ``TEMPLATE_CANON_VERSION`` входит в digest — как ``MERKLE_VERSION`` в
    merkle.py и ``FIDELITY_CANON_VERSION`` у графового канона.  Без неё смена
    смысла канона (а он менялся уже трижды: ``center_mm`` → ``/2``,
    дименсиональные сетки → ``/3``, раздел зонной группы из таблицы
    экстрактора → ``/4``) молча переопределяла бы значение уже
    сохранённых хешей: старый и новый канон дали бы совпадающий digest на разных
    правилах, и persisted-дедуп сравнивал бы несравнимое.
    """

    if "node_id" in node:
        canonical: Any = _canonical_tree(cast(TreeNode, node), origin_mm)
        stable = json.dumps(
            canonical, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"))
    else:
        stable = canon_op(cast(L1Node, node), origin_mm)
    return hashlib.sha1(
        f"{TEMPLATE_CANON_VERSION}\n{stable}".encode("utf-8")).hexdigest()


def multiset_hash(
    nodes: Iterable[L1Node | TreeNode],
    origin_mm: Sequence[float],
) -> str:
    """Return Part 6.1's order-independent hash of canonical node hashes."""

    hashes = sorted(canon_hash(node, origin_mm) for node in nodes)
    return hashlib.sha1("\n".join(hashes).encode("utf-8")).hexdigest()


def _round_step(value: float, step: float) -> float:
    """Round a finite scalar on a dimensionally appropriate canon grid."""

    number = float(value)
    if not math.isfinite(number):
        raise ValueError("canonical numeric value must be finite")
    rounded = round(round(number / step) * step, 12)
    return 0.0 if rounded == 0.0 else rounded


def _fidelity_rotation(value: float) -> float:
    rounded = _round_step(float(value) % 360.0, _FIDELITY_ANGLE_STEP_DEG)
    if rounded >= 360.0:
        rounded -= 360.0
    return 0.0 if rounded == 0.0 else rounded


def _fidelity_axis(value: Any) -> list[float]:
    """Normalize a dimensionless Arc basis vector before quantization."""

    if not isinstance(value, list) or len(value) != 3 or not all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in value):
        raise ValueError("arc axis must contain exactly three finite numbers")
    numbers = [float(item) for item in value]
    if not all(math.isfinite(item) for item in numbers):
        raise ValueError("arc axis must contain exactly three finite numbers")
    norm = math.sqrt(sum(item * item for item in numbers))
    if norm == 0.0:
        raise ValueError("arc axis must be non-zero")
    return [
        _round_step(item / norm, _FIDELITY_AXIS_STEP)
        for item in numbers
    ]


def _looks_like_contour_ring(value: Any) -> bool:
    """True for {"shape", "points_mm", "arcs"} — contour.py's OWN validated
    shape (contour.py:_validate_shape, `extra = set(shape) - {"shape",
    "points_mm", "arcs"}`). Anything else fails open (untouched, same
    discipline as _canonical_ring's "non-ring shapes pass through")."""
    if not isinstance(value, dict):
        return False
    points = value.get("points_mm")
    return (isinstance(points, list) and len(points) >= 3
            and all(isinstance(p, list) and len(p) >= 2
                    and all(isinstance(c, (int, float)) and not isinstance(c, bool)
                            for c in p)
                    for p in points))


def _effective_bulge(arc: Any, p0: Sequence[float], p1: Sequence[float]) -> float | None:
    """Both arc forms contour.py's own validated schema accepts
    (contour.py:_validate_shape) -> one DXF-bulge value, via contour.py's
    OWN conversion — codex #6 (2026-07-29): a shared semantic lowering,
    not a second copy of the geometry.  ``None`` on anything unrecognized
    or geometrically invalid (radius shorter than half the chord): the
    caller fails open, same discipline as every other "not a ring we
    understand" branch here."""
    if not isinstance(arc, dict):
        return None
    if (set(arc) == {"edge", "bulge"} and isinstance(arc.get("bulge"), (int, float))
            and not isinstance(arc.get("bulge"), bool)):
        return float(arc["bulge"])
    if ("radius_mm" in arc and set(arc) <= {"edge", "radius_mm", "dir"}
            and isinstance(arc.get("radius_mm"), (int, float))
            and not isinstance(arc.get("radius_mm"), bool)
            and arc.get("dir", "ccw") in ("ccw", "cw")):
        from kukai.ir.contour import radius_to_bulge
        return radius_to_bulge(list(p0), list(p1), float(arc["radius_mm"]),
                               arc.get("dir", "ccw") == "ccw",
                               "canon", "canon", [])
    return None


def _canonical_contour_ring(ring: dict, origin: Sequence[float]) -> dict:
    """Canonical form of one create_floor_by_contour loop: cyclic start AND
    winding direction are Revit-incidental (2026-07-28 live evidence, v12
    rebuild #7 — a rebuilt floor's contour re-extracts from a different
    first vertex than the original), same law _canonical_ring already
    encodes for plain rings, extended to the {points_mm, arcs} shape a
    contour loop actually has. Arc "edge" indices are reindexed to follow
    their own chord under rotation/reflection, and bulge sign flips on
    reflection (a DXF-bulge is signed by traversal direction — codex #7,
    verified for major arcs too, see test_fold.py).

    codex #5/#6 (2026-07-29): the arc's OWN curvature is never quantized as
    a bare number — /2 tried a bulge-specific grid tied to chord length and
    a codex review proved it falsely converges (Δbulge under the grid step
    can still move the arc's physical midpoint by more than CANON_MM,
    worse the shorter the chord). Canon instead lowers EVERY arc form
    (bulge or radius+dir, contour.py's own shapes) to its physical
    mid-sweep point (contour.bulge_midpoint) using the ALREADY-canonicalized
    (rotated/reflected/rounded) endpoints, and rounds that point on the
    exact same CANON_MM grid as every vertex — one tolerance, no separate
    dial, radius and bulge forms of the same arc collapse to one hash by
    construction rather than by a second normalization pass."""
    from kukai.ir.contour import bulge_midpoint

    points = ring.get("points_mm")
    localized = [
        [_round_mm(float(c) - float(origin[i])) for i, c in enumerate(pt)]
        for pt in points
    ]
    n = len(localized)
    edge_bulge: dict[int, float] = {}
    arcs_raw = ring.get("arcs")
    if isinstance(arcs_raw, list):
        for arc in arcs_raw:
            if not (isinstance(arc, dict) and isinstance(arc.get("edge"), int)
                    and not isinstance(arc.get("edge"), bool)
                    and 0 <= arc["edge"] < n):
                return ring  # unrecognized shape: fail-open, untouched
            e = arc["edge"]
            bulge = _effective_bulge(arc, localized[e], localized[(e + 1) % n])
            if bulge is None:
                return ring  # unrecognized/geometrically invalid: fail-open
            edge_bulge[e] = bulge

    best: tuple[str, list, list] | None = None
    for reflect in (False, True):
        seq = localized[::-1] if reflect else localized
        for start in range(n):
            cand_points = seq[start:] + seq[:start]
            cand_arcs = []
            for old_edge, bulge in edge_bulge.items():
                if reflect:
                    new_edge = ((n - 2 - old_edge) % n - start) % n
                    new_bulge = -bulge
                else:
                    new_edge = (old_edge - start) % n
                    new_bulge = bulge
                p0, p1 = cand_points[new_edge], cand_points[(new_edge + 1) % n]
                mid = bulge_midpoint(p0, p1, new_bulge)
                mid_mm = [_round_mm(c) for c in mid]
                cand_arcs.append({"edge": new_edge, "mid_mm": mid_mm})
            cand_arcs.sort(key=lambda a: a["edge"])
            key = _stable_canonical_json(
                {"points_mm": cand_points, "arcs": cand_arcs})
            if best is None or key < best[0]:
                best = (key, cand_points, cand_arcs)
    assert best is not None  # n >= 3, loop always runs at least once
    result = dict(ring)
    result["points_mm"] = best[1]
    result["arcs"] = best[2]
    return result


def _fidelity_canonical_value(
    value: Any,
    origin: Sequence[float],
    *,
    field_name: str | None = None,
    ref_targets: Mapping[str, str] | None = None,
    seed_refs: bool = False,
) -> Any:
    """A5 value canon: typed grids plus level/topology preservation.

    Template canon intentionally treats host/level as replaceable template
    slots.  Fidelity canon instead resolves every ``ref`` to the canonical
    identity of its graph target and keeps the concrete level selector.
    """

    # create_floor_by_contour's params.contour.{outer,holes}: one level
    # deeper than plain coordinate rings (points_mm nested inside a
    # {shape,points_mm,arcs} dict) — checked by SHAPE, not just field_name,
    # so an unrelated "outer"/"holes" elsewhere fails open unchanged.
    if field_name == "outer" and _looks_like_contour_ring(value):
        return _canonical_contour_ring(value, origin)
    if field_name == "holes" and isinstance(value, list) and value and all(
            _looks_like_contour_ring(item) for item in value):
        rings = [_canonical_contour_ring(item, origin) for item in value]
        rings.sort(key=_stable_canonical_json)
        return rings
    if field_name in _COORDINATE_FIELDS:
        localized = _localize_coordinates(value, origin)
        if field_name == "outline":
            return _canonical_ring(localized)
        if field_name == "holes" and isinstance(localized, list):
            rings = [_canonical_ring(ring) for ring in localized]
            try:
                rings.sort(key=lambda ring: json.dumps(ring))
            except TypeError:
                pass
            return rings
        return localized
    if field_name in {"elevation_mm", "elev_mm"}:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _round_mm(float(value) - float(origin[2]))
    if field_name in _ANGLE_FIELDS:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _fidelity_rotation(float(value))
    if field_name in _FIDELITY_RADIAL_FIELDS:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _round_step(float(value), _FIDELITY_RADIAL_STEP_MM)
    if field_name in _FIDELITY_AXIS_FIELDS:
        return _fidelity_axis(value)
    if field_name in _FIDELITY_RADIAN_FIELDS:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _round_step(float(value), _FIDELITY_RADIAN_STEP)
    # Ветвь 2π снимается на УРОВНЕ ДУГИ, а не поля: пара углов неделима.
    if field_name == "arc":
        value = _canonical_arc_branch(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            if _volatile_field(key):
                continue
            if key == "ref":
                target = value[key]
                if not isinstance(target, str) or not target:
                    raise ValueError("fidelity ref target must be a non-empty string")
                if seed_refs:
                    result[key] = "<graph-target>"
                elif ref_targets is None or target not in ref_targets:
                    raise ValueError(
                        f"fidelity ref target {target!r} is absent from graph")
                else:
                    result[key] = ref_targets[target]
                continue
            result[key] = _fidelity_canonical_value(
                value[key], origin, field_name=key,
                ref_targets=ref_targets, seed_refs=seed_refs)
        return result
    if isinstance(value, list):
        return [
            _fidelity_canonical_value(
                item, origin, field_name=field_name,
                ref_targets=ref_targets, seed_refs=seed_refs)
            for item in value
        ]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if field_name is not None and field_name.endswith("_mm"):
            return _round_mm(float(value))
        # Dimensionless/unknown scalars must not inherit a one-millimetre grid.
        # A fine grid removes floating serialization noise without creating a
        # tolerance wider than any current witness.
        return _round_step(float(value), _FIDELITY_SCALAR_STEP)
    return value


def _fidelity_seed_absent_defaults(node: L1Node) -> L1Node:
    """codex #8 (2026-07-29): fill in an op's absent-but-semantically-zero
    params BEFORE canonicalizing, so an omitted key and an explicit 0.0
    produce the identical canonical value. Purely additive — a node that
    already names the field is returned untouched, byte-identical."""
    if node.get("kind") != "op":
        return node
    defaults = _FIDELITY_ABSENT_DEFAULTS.get(node.get("op_name"))
    if not defaults:
        return node
    params = node.get("params")
    if not isinstance(params, dict):
        return node
    missing = {k: v for k, v in defaults.items() if k not in params}
    if not missing:
        return node
    return {**node, "params": {**params, **missing}}


def _fidelity_arc_endpoints_from_arc(node: L1Node) -> L1Node:
    """Единственный источник правды о дуговой стене — её дуга.

    Хранимые p0/p1 избыточны и в источнике ей противоречат (v18: 0.37-0.94 мм
    на всех пяти живых дугах); Revit строит ИЗ дуги, поэтому пересобранный
    элемент всегда согласован с ней, а исходный лист — нет. Сравнивать надо
    согласованное представление, иначе канон ловит не расхождение модели, а
    расхождение записи с самой собой.
    """
    params = node.get("params")
    if not isinstance(params, dict):
        return node
    arc = params.get("arc")
    if not isinstance(arc, dict) or "p0_mm" not in params:
        return node
    ends = _arc_endpoints(_canonical_arc_branch(arc))
    if ends is None:
        return node
    a0, a1 = ends
    p0 = [float(v) for v in params["p0_mm"][:2]]
    # НАПРАВЛЕНИЕ СОХРАНЯЕТСЯ: какой конец был p0, тот им и остаётся.
    # Иначе две стены с одной дугой, но встречным направлением, слиплись бы
    # в один хеш — а направление у стены смысловое (внутренняя/наружная
    # сторона, location_line).
    near_start = (math.dist(a0, p0) <= math.dist(a1, p0))
    out = dict(node)
    out["params"] = {**params,
                     "p0_mm": a0 if near_start else a1,
                     "p1_mm": a1 if near_start else a0}
    return out


def _fidelity_canonical_l1(
    node: L1Node,
    origin_mm: Sequence[float],
    *,
    ref_targets: Mapping[str, str] | None = None,
    seed_refs: bool = False,
) -> dict[str, Any]:
    node = _fidelity_seed_absent_defaults(node)
    node = _fidelity_arc_endpoints_from_arc(node)
    canonical = cast(dict[str, Any], _fidelity_canonical_value(
        node, origin_mm, ref_targets=ref_targets, seed_refs=seed_refs))
    if node["kind"] == "op":
        # As in TemplateCanon, anchor is derived from defining params.  Unlike
        # TemplateCanon, concrete level selectors and graph targets survive.
        canonical.pop("anchor_mm", None)
    return canonical


def _stable_canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"))


def _iter_graph_refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        if "ref" in value:
            if set(value) != {"ref"} or not isinstance(value["ref"], str):
                raise ValueError("graph ref must be exactly {'ref': <string>}")
            yield value["ref"]
            return
        for item in value.values():
            yield from _iter_graph_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_graph_refs(item)


class TemplateCanon:
    """Broad equivalence for repeated-template/Merkle discovery."""

    VERSION = TEMPLATE_CANON_VERSION
    canon_op = staticmethod(canon_op)
    hash = staticmethod(canon_hash)
    multiset_hash = staticmethod(multiset_hash)


class FidelityCanon:
    """Graph-aware, typed canonical identity used only for fidelity proofs."""

    VERSION = FIDELITY_CANON_VERSION

    @classmethod
    def _digest(cls, stable: str) -> str:
        return hashlib.sha1(
            (cls.VERSION + "\0" + stable).encode("utf-8")).hexdigest()

    @classmethod
    def _target_identities(
        cls,
        nodes: Sequence[L1Node],
        origin_mm: Sequence[float],
    ) -> dict[str, str]:
        by_id: dict[str, L1Node] = {}
        for node in nodes:
            node_id = node.get("_id")
            if not isinstance(node_id, str) or not node_id:
                raise ValueError("fidelity graph node needs a non-empty _id")
            if node_id in by_id:
                raise ValueError(f"duplicate fidelity graph node id {node_id!r}")
            by_id[node_id] = node
        for node in nodes:
            for target in _iter_graph_refs(node):
                if target not in by_id:
                    raise ValueError(
                        f"fidelity ref target {target!r} is absent from graph")

        identities = {
            node_id: cls._digest(_stable_canonical_json(
                _fidelity_canonical_l1(
                    node, origin_mm, seed_refs=True)))
            for node_id, node in by_id.items()
        }
        # Weisfeiler-Lehman-style refinement makes identity independent of raw
        # ids and captures nested graph targets.  Host graphs are shallow DAGs;
        # a fixed bound also gives deterministic behaviour for malformed cycles.
        for _round in range(_GRAPH_REFINEMENT_ROUNDS):
            refined = {
                node_id: cls._digest(_stable_canonical_json(
                    _fidelity_canonical_l1(
                        node, origin_mm, ref_targets=identities)))
                for node_id, node in by_id.items()
            }
            if refined == identities:
                break
            identities = refined
        return identities

    @classmethod
    def hash_sequence(
        cls,
        nodes: Sequence[L1Node],
        origin_mm: Sequence[float],
    ) -> tuple[str, ...]:
        if len(origin_mm) != 3:
            raise ValueError("origin_mm must contain exactly three coordinates")
        targets = cls._target_identities(nodes, origin_mm)
        return tuple(
            cls._digest(_stable_canonical_json(_fidelity_canonical_l1(
                node, origin_mm, ref_targets=targets)))
            for node in nodes
        )

    @classmethod
    def hash(
        cls,
        node: L1Node,
        origin_mm: Sequence[float],
        *,
        graph: Sequence[L1Node] | None = None,
    ) -> str:
        corpus = tuple(graph) if graph is not None else (node,)
        targets = cls._target_identities(corpus, origin_mm)
        return cls._digest(_stable_canonical_json(_fidelity_canonical_l1(
            node, origin_mm, ref_targets=targets)))

    @classmethod
    def multiset_hash(
        cls,
        nodes: Iterable[L1Node],
        origin_mm: Sequence[float],
    ) -> str:
        corpus = tuple(nodes)
        return cls.multiset_digest(cls.hash_sequence(corpus, origin_mm))

    @classmethod
    def multiset_digest(cls, hashes: Iterable[str]) -> str:
        """Digest precomputed leaf hashes without rebuilding graph context."""

        return cls._digest("\n".join(sorted(hashes)))


def iter_l1_leaves(node: TreeNode) -> Iterator[L1Node]:
    """Yield every exact L1 payload represented by a folded subtree."""

    payload = node["payload"]
    if payload is not None:
        yield payload
    yield from node["members"]
    for child in node["children"]:
        yield from iter_l1_leaves(child)


def _points_from_params(value: Any, field_name: str | None = None) \
        -> Iterator[tuple[float, float, float]]:
    if field_name in _COORDINATE_FIELDS and isinstance(value, list):
        if (len(value) in (2, 3)
                and all(isinstance(item, (int, float))
                        and not isinstance(item, bool) for item in value)):
            z = float(value[2]) if len(value) == 3 else 0.0
            yield (float(value[0]), float(value[1]), z)
            return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _points_from_params(item, key)
    elif isinstance(value, list):
        for item in value:
            yield from _points_from_params(item, field_name)


def _node_points(node: L1Node) -> Iterator[tuple[float, float, float]]:
    anchor = node["anchor_mm"]
    if anchor is not None:
        yield (anchor[0], anchor[1], anchor[2])
    if node["kind"] == "atom":
        if node["bbox_min_mm"] is not None:
            yield tuple(node["bbox_min_mm"])  # type: ignore[misc]
            yield tuple(node["bbox_max_mm"])  # type: ignore[misc]
    else:
        yield from _points_from_params(node["params"])


def _facts_for_sources(
    sources: Sequence[L1Node],
    *,
    area_m2: float | None = None,
) -> TreeFacts:
    bbox_min: list[float] | None = None
    bbox_max: list[float] | None = None
    dims: list[float] | None = None
    for source in sources:
        for point in _node_points(source):
            if bbox_min is None:
                bbox_min = list(point)
                bbox_max = list(point)
                continue
            assert bbox_max is not None
            for index in range(3):
                bbox_min[index] = min(bbox_min[index], point[index])
                bbox_max[index] = max(bbox_max[index], point[index])
    if bbox_min is not None:
        assert bbox_max is not None
        dims = [high - low for low, high in zip(bbox_min, bbox_max)]
    histogram = Counter(
        source["op_name"] for source in sources if source["kind"] == "op")
    return {
        "bbox_min_mm": bbox_min,
        "bbox_max_mm": bbox_max,
        "shape": None,
        "dims_mm": dims,
        "area_m2": area_m2,
        "element_count": len(sources),
        "op_histogram": dict(sorted(histogram.items())),
    }


def _make_tree_node(
    kind: str,
    *,
    label: str = "",
    children: Sequence[TreeNode] = (),
    payload: L1Node | None = None,
    members: Sequence[L1Node] = (),
    macro: Mapping[str, Any] | None = None,
    area_m2: float | None = None,
) -> TreeNode:
    children_list = list(children)
    members_list = list(members)
    sources: list[L1Node] = []
    if payload is not None:
        sources.append(payload)
    sources.extend(members_list)
    for child in children_list:
        sources.extend(iter_l1_leaves(child))
    source_ids = [source["source_element_id"] for source in sources]
    if len(source_ids) != len(set(source_ids)):
        raise FoldError(f"{kind} node would duplicate one or more L1 leaves")
    return {
        "node_id": stable_tree_id(kind, source_ids),
        "kind": kind,
        "label": label,
        "children": children_list,
        "payload": payload,
        "members": members_list,
        "macro": dict(macro) if macro is not None else None,
        "facts": _facts_for_sources(sources, area_m2=area_m2),
        "verdict": None,
    }


def _leaf(node: L1Node) -> TreeNode:
    return _make_tree_node(node["kind"], payload=node)


@dataclass(frozen=True, slots=True)
class _Pattern:
    kind: str
    members: tuple[L1Node, ...]
    macro: Mapping[str, Any]


def _axis_values(values: Iterable[float]) -> list[float]:
    return sorted({_round_mm(value) for value in values})


def _progression_step(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    deltas = [
        values[index + 1] - values[index]
        for index in range(len(values) - 1)
    ]
    if any(delta <= 0.0 for delta in deltas):
        return None
    median = float(statistics.median(deltas))
    if median <= 0.0:
        return None
    if max(deltas) - min(deltas) > GRID_REL_TOL * median:
        return None
    return median


def _maximal_row(nodes: Sequence[L1Node]) -> _Pattern | None:
    anchored = [node for node in nodes if node["anchor_mm"] is not None]
    if len(anchored) < MIN_ROW:
        return None
    xs = [cast(list[float], node["anchor_mm"])[0] for node in anchored]
    ys = [cast(list[float], node["anchor_mm"])[1] for node in anchored]
    axis_index = 0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 1
    axis_name = "x" if axis_index == 0 else "y"
    ordered = sorted(
        anchored,
        key=lambda node: (
            cast(list[float], node["anchor_mm"])[axis_index],
            node["source_element_id"],
        ),
    )
    coords = [
        _round_mm(cast(list[float], node["anchor_mm"])[axis_index])
        for node in ordered
    ]
    deltas = [coords[index + 1] - coords[index]
              for index in range(len(coords) - 1)]
    min_q: deque[int] = deque()
    max_q: deque[int] = deque()
    left = 0
    best: tuple[int, int] | None = None
    for right, delta in enumerate(deltas):
        while min_q and deltas[min_q[-1]] >= delta:
            min_q.pop()
        while max_q and deltas[max_q[-1]] <= delta:
            max_q.pop()
        min_q.append(right)
        max_q.append(right)
        while left <= right:
            minimum = deltas[min_q[0]]
            maximum = deltas[max_q[0]]
            valid = (
                minimum > 0.0
                and maximum - minimum <= GRID_REL_TOL * minimum
            )
            if valid:
                break
            if min_q and min_q[0] == left:
                min_q.popleft()
            if max_q and max_q[0] == left:
                max_q.popleft()
            left += 1
        length = right - left + 2
        if length >= MIN_ROW:
            candidate = (left, right + 1)
            if best is None or length > best[1] - best[0] + 1:
                best = candidate
    if best is None:
        return None
    start, end = best
    members = ordered[start:end + 1]
    member_coords = coords[start:end + 1]
    step = float(statistics.median([
        member_coords[index + 1] - member_coords[index]
        for index in range(len(member_coords) - 1)
    ]))
    perpendicular = 1 - axis_index
    perpendicular_values = [
        cast(list[float], node["anchor_mm"])[perpendicular]
        for node in members
    ]
    # The macro grammar only supports axis-aligned rows.  Refuse a diagonal or
    # broad scatter instead of emitting a plausible-but-wrong row descriptor.
    if (max(perpendicular_values) - min(perpendicular_values)
            > max(CANON_MM, GRID_REL_TOL * step)):
        return None
    origin = cast(list[float], members[0]["anchor_mm"])
    return _Pattern(
        kind="row",
        members=tuple(members),
        macro={
            "type": "row",
            "n": len(members),
            "d_mm": step,
            "origin_mm": [origin[0], origin[1]],
            "axis": axis_name,
        },
    )


def _detect_pattern(
    nodes: Sequence[L1Node],
    *,
    allow_row: bool,
) -> _Pattern | None:
    anchored = [node for node in nodes if node["anchor_mm"] is not None]
    if len(anchored) >= MIN_ARRAY:
        xs = _axis_values(
            cast(list[float], node["anchor_mm"])[0] for node in anchored)
        ys = _axis_values(
            cast(list[float], node["anchor_mm"])[1] for node in anchored)
        dx = _progression_step(xs)
        dy = _progression_step(ys)
        if dx is not None and dy is not None and len(xs) >= 2 and len(ys) >= 2:
            unique_points = {
                (
                    _round_mm(cast(list[float], node["anchor_mm"])[0]),
                    _round_mm(cast(list[float], node["anchor_mm"])[1]),
                )
                for node in anchored
            }
            capacity = len(xs) * len(ys)
            coverage = len(unique_points) / capacity
            if (len(unique_points) == len(anchored)
                    and coverage >= GRID_COVERAGE):
                return _Pattern(
                    kind="grid_array",
                    members=tuple(sorted(
                        anchored,
                        key=lambda node: node["source_element_id"])),
                    macro={
                        "type": "grid_array",
                        "nx": len(xs),
                        "ny": len(ys),
                        "dx_mm": dx,
                        "dy_mm": dy,
                        "origin_mm": [xs[0], ys[0]],
                        "coverage": coverage,
                    },
                )
    return _maximal_row(nodes) if allow_row else None


def _fold_ops_unbounded(nodes: Sequence[L1OpNode]) -> list[TreeNode]:
    groups: dict[tuple[str, str], list[L1Node]] = defaultdict(list)
    for node in nodes:
        groups[(node["op_name"], node["type_name"])].append(node)
    result: list[TreeNode] = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda node: node["source_element_id"])
        pattern = _detect_pattern(group, allow_row=True)
        consumed: set[str] = set()
        if pattern is not None:
            consumed = {node["_id"] for node in pattern.members}
            result.append(_make_tree_node(
                pattern.kind,
                label=f"{key[0]} {pattern.kind}",
                members=pattern.members,
                macro=pattern.macro,
            ))
        result.extend(
            _leaf(node) for node in group if node["_id"] not in consumed)
    return result


def _cell_of(anchor: Sequence[float], cell_mm: float) -> tuple[int, int]:
    return (
        math.floor(float(anchor[0]) / cell_mm),
        math.floor(float(anchor[1]) / cell_mm),
    )


def _atom_components(nodes: Sequence[L1AtomNode]) \
        -> list[tuple[tuple[tuple[int, int], ...] | None, list[L1AtomNode]]]:
    cells: dict[tuple[int, int], list[L1AtomNode]] = defaultdict(list)
    unlocated: list[L1AtomNode] = []
    for node in nodes:
        if node["anchor_mm"] is None:
            unlocated.append(node)
        else:
            cells[_cell_of(node["anchor_mm"], ATOM_CELL_MM)].append(node)
    components: list[
        tuple[tuple[tuple[int, int], ...] | None, list[L1AtomNode]]
    ] = []
    unseen = set(cells)
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        queue = deque([start])
        component_cells: list[tuple[int, int]] = []
        members: list[L1AtomNode] = []
        while queue:
            cell = queue.popleft()
            component_cells.append(cell)
            members.extend(cells[cell])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbour = (cell[0] + dx, cell[1] + dy)
                    if neighbour in unseen:
                        unseen.remove(neighbour)
                        queue.append(neighbour)
        components.append((
            tuple(sorted(component_cells)),
            sorted(members, key=lambda node: node["source_element_id"]),
        ))
    if unlocated:
        components.append((
            None,
            sorted(unlocated, key=lambda node: node["source_element_id"]),
        ))
    return components


def _atom_summary(
    kind: str,
    members: Sequence[L1AtomNode],
    *,
    cells: Sequence[tuple[int, int]] | None = None,
) -> TreeNode:
    first = members[0]
    facts = _facts_for_sources(cast(Sequence[L1Node], members))
    full_histogram = Counter(node["type_name"] for node in members)
    ranked_types = sorted(
        full_histogram.items(), key=lambda item: (-item[1], item[0]))
    visible_types = ranked_types[:ATOM_LEAF_CAP]
    type_histogram = dict(sorted(visible_types))
    type_name = ranked_types[0][0] if len(ranked_types) == 1 else "<mixed>"
    macro: dict[str, Any] = {
        "type": kind,
        "category": first["category"],
        "category_ru": first["category_ru"],
        "type_name": type_name,
        "count": len(members),
        "bbox_min_mm": facts["bbox_min_mm"],
        "bbox_max_mm": facts["bbox_max_mm"],
        "type_histogram": type_histogram,
    }
    if len(ranked_types) > len(visible_types):
        macro["type_kinds_omitted"] = len(ranked_types) - len(visible_types)
        macro["type_instances_omitted"] = sum(
            count for _name, count in ranked_types[len(visible_types):])
    if cells is not None:
        macro["cells"] = [list(cell) for cell in cells]
    else:
        macro["spatially_unresolved"] = True
    return _make_tree_node(
        kind,
        label=f"{len(members)} × {first['category']} / {type_name}",
        members=members,
        macro=macro,
    )


def _fold_atoms_unbounded(nodes: Sequence[L1AtomNode]) -> list[TreeNode]:
    groups: dict[tuple[str, str], list[L1AtomNode]] = defaultdict(list)
    for node in nodes:
        groups[(node["category"], node["type_name"])].append(node)
    result: list[TreeNode] = []
    individual: list[L1AtomNode] = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda node: node["source_element_id"])
        pattern = _detect_pattern(cast(Sequence[L1Node], group), allow_row=False)
        consumed: set[str] = set()
        if pattern is not None:
            consumed = {node["_id"] for node in pattern.members}
            macro = dict(pattern.macro)
            macro["element_kind"] = "atom"
            result.append(_make_tree_node(
                pattern.kind,
                label=f"{key[0]} {pattern.kind}",
                members=pattern.members,
                macro=macro,
            ))
        remainder = [node for node in group if node["_id"] not in consumed]
        for cells, component in _atom_components(remainder):
            if len(component) >= ATOM_CLUSTER_MIN:
                result.append(_atom_summary(
                    "atom_cluster", component, cells=cells))
            else:
                individual.extend(component)

    individual.sort(key=lambda node: (
        node["category"], node["type_name"], node["source_element_id"]))
    result.extend(_leaf(node) for node in individual[:ATOM_LEAF_CAP])
    overflow: dict[str, list[L1AtomNode]] = defaultdict(list)
    for node in individual[ATOM_LEAF_CAP:]:
        overflow[node["category"]].append(node)
    for category in sorted(overflow):
        result.append(_atom_summary(
            "atom_summary", overflow[category], cells=()))
    return result


def _group_boundary_partitions(
    nodes: Sequence[L1Node],
    group_boundaries: Mapping[str, str],
) -> list[list[L1Node]]:
    """Partition heuristic candidates without adding group tree parents."""

    partitions: dict[str, list[L1Node]] = defaultdict(list)
    for node in nodes:
        boundary = group_boundaries.get(
            node["source_element_id"], "ungrouped")
        partitions[boundary].append(node)
    return [
        sorted(partitions[key], key=lambda node: node["source_element_id"])
        for key in sorted(partitions)
    ]


def _fold_ops(
    nodes: Sequence[L1OpNode],
    group_boundaries: Mapping[str, str] | None,
) -> list[TreeNode]:
    if group_boundaries is None:
        # Preserve the pre-R4 byte path exactly when the side index is absent.
        return _fold_ops_unbounded(nodes)
    result: list[TreeNode] = []
    for partition in _group_boundary_partitions(
            cast(Sequence[L1Node], nodes), group_boundaries):
        result.extend(_fold_ops_unbounded(cast(Sequence[L1OpNode], partition)))
    return result


def _fold_atoms(
    nodes: Sequence[L1AtomNode],
    group_boundaries: Mapping[str, str] | None,
) -> list[TreeNode]:
    if group_boundaries is None:
        # Atom clusters and overflow summaries retain their legacy ordering.
        return _fold_atoms_unbounded(nodes)
    result: list[TreeNode] = []
    for partition in _group_boundary_partitions(
            cast(Sequence[L1Node], nodes), group_boundaries):
        result.extend(_fold_atoms_unbounded(
            cast(Sequence[L1AtomNode], partition)))
    return result


def _fold_payloads(
    nodes: Sequence[L1Node],
    group_boundaries: Mapping[str, str] | None = None,
) -> list[TreeNode]:
    ops = [cast(L1OpNode, node) for node in nodes if node["kind"] == "op"]
    atoms = [cast(L1AtomNode, node) for node in nodes if node["kind"] == "atom"]
    result = (
        _fold_ops(ops, group_boundaries)
        + _fold_atoms(atoms, group_boundaries)
    )
    return sorted(result, key=lambda node: (node["kind"], node["node_id"]))


def _point_on_segment(
    point: tuple[float, float],
    start: Sequence[float],
    end: Sequence[float],
) -> bool:
    px, py = point
    x0, y0 = float(start[0]), float(start[1])
    x1, y1 = float(end[0]), float(end[1])
    cross = (px - x0) * (y1 - y0) - (py - y0) * (x1 - x0)
    if abs(cross) > CANON_MM:
        return False
    return (
        min(x0, x1) - CANON_MM <= px <= max(x0, x1) + CANON_MM
        and min(y0, y1) - CANON_MM <= py <= max(y0, y1) + CANON_MM
    )


def _point_in_ring(point: tuple[float, float], ring: Sequence[Sequence[float]]) \
        -> bool:
    if len(ring) < 3:
        return False
    inside = False
    previous = ring[-1]
    for current in ring:
        if _point_on_segment(point, previous, current):
            return True
        x0, y0 = float(previous[0]), float(previous[1])
        x1, y1 = float(current[0]), float(current[1])
        if (y0 > point[1]) != (y1 > point[1]):
            crossing_x = (x1 - x0) * (point[1] - y0) / (y1 - y0) + x0
            if point[0] < crossing_x:
                inside = not inside
        previous = current
    return inside


def _room_contains(room: RoomInfo, point: tuple[float, float]) -> bool:
    if not _point_in_ring(point, room.boundary_mm):
        return False
    loops = room.boundary_loops_mm
    for hole in loops[1:] if loops else ():
        if _point_in_ring(point, hole):
            return False
    return True


class _RoomSpatialIndex:
    """Uniform-grid candidate index for room point containment."""

    def __init__(self, rooms: Sequence[RoomInfo]) -> None:
        self.rooms = {room.id: room for room in rooms}
        self.cells: dict[tuple[int, int], list[str]] = defaultdict(list)
        for room in rooms:
            if len(room.boundary_mm) < 3:
                continue
            xs = [point[0] for point in room.boundary_mm]
            ys = [point[1] for point in room.boundary_mm]
            min_cell = _cell_of((min(xs), min(ys)), ZONE_CELL_MM)
            max_cell = _cell_of((max(xs), max(ys)), ZONE_CELL_MM)
            for cell_x in range(min_cell[0], max_cell[0] + 1):
                for cell_y in range(min_cell[1], max_cell[1] + 1):
                    self.cells[(cell_x, cell_y)].append(room.id)
        for room_ids in self.cells.values():
            room_ids.sort()

    def containing(self, anchor: Sequence[float]) -> tuple[str, ...]:
        point = (float(anchor[0]), float(anchor[1]))
        candidates = self.cells.get(_cell_of(point, ZONE_CELL_MM), ())
        return tuple(
            room_id for room_id in candidates
            if _room_contains(self.rooms[room_id], point)
        )


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}
        self.rank = {value: 0 for value in self.parent}

    def find(self, value: str) -> str:
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            parent = self.parent[value]
            self.parent[value] = root
            value = parent
        return root

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left == root_right:
            return
        if self.rank[root_left] < self.rank[root_right]:
            root_left, root_right = root_right, root_left
        self.parent[root_right] = root_left
        if self.rank[root_left] == self.rank[root_right]:
            self.rank[root_left] += 1


def _discipline(element: L0Element | None) -> str:
    """Раздел элемента — строкой из таблицы экстрактора.

    Здесь до 28.07 лежал СВОЙ словарь категорий (`_CATEGORY_DISCIPLINE`) —
    третий источник правды об одном понятии: первый — закрытый словарь
    значений `registry_base.DISCIPLINES`, второй — колонка
    `CategorySpec.discipline` в `extract.py`, где раздел проставлен у КАЖДОЙ
    категории таблицы.  Свой знал 17 категорий из 47 и говорил на своём
    лексиконе («architecture»/«structure»/«coordination»), поэтому все 25
    категорий инженерных разделов — светильники, фитинги, короба — зонная
    раскладка сваливала в «unknown»: раздел ЭОМ выглядел как «не знаем, что
    это», хотя таблица знает про него всё.  Пакет сам запрещает второй
    словарь об одном понятии; теперь запрет соблюдён и здесь.

    «unknown» остаётся ровно для того, для чего оно честно: категории, о
    которой таблица экстрактора молчит.  Угадывать раздел по имени категории
    хуже пустоты — пустота видна, догадка нет.
    """

    if element is None:
        return "unknown"
    # Импорт внутри функции: extract.py — самый тяжёлый модуль пакета, а FOLD
    # работает и офлайн, без моста (тот же приём, что `census._extract_table`).
    from .extract import _SPEC_BY_NAME

    spec = _SPEC_BY_NAME.get(element.category)
    return "unknown" if spec is None else spec.discipline


def _zoned_fold(
    nodes: Sequence[L1Node],
    elements_by_id: Mapping[str, L0Element],
    group_boundaries: Mapping[str, str] | None,
) -> list[TreeNode]:
    zones: dict[tuple[int, int] | None, list[L1Node]] = defaultdict(list)
    for node in nodes:
        key = (
            None if node["anchor_mm"] is None
            else _cell_of(node["anchor_mm"], ZONE_CELL_MM)
        )
        zones[key].append(node)
    result: list[TreeNode] = []
    ordered_keys = sorted(
        zones, key=lambda key: (key is None, key if key is not None else (0, 0)))
    for key in ordered_keys:
        disciplines: dict[str, list[L1Node]] = defaultdict(list)
        for node in zones[key]:
            disciplines[_discipline(
                elements_by_id.get(node["source_element_id"]))].append(node)
        discipline_nodes: list[TreeNode] = []
        for name in sorted(disciplines):
            discipline_nodes.append(_make_tree_node(
                "group",
                label=name,
                children=_fold_payloads(
                    disciplines[name], group_boundaries),
                macro={"type": "discipline", "discipline": name},
            ))
        result.append(_make_tree_node(
            "zone",
            label=("zone:unlocated" if key is None
                   else f"zone:{key[0]},{key[1]}"),
            children=discipline_nodes,
            macro={
                "type": "zone",
                "cell": None if key is None else list(key),
                "cell_mm": ZONE_CELL_MM,
            },
        ))
    return result


def _components(
    union_find: _UnionFind,
    room_ids: Iterable[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for room_id in room_ids:
        result[union_find.find(room_id)].append(room_id)
    return {
        root: sorted(members) for root, members in sorted(result.items())
    }


@dataclass(frozen=True, slots=True)
class RoomAdjacencyCensus:
    """Скольких дверей КОСНУЛСЯ предикат `_semantic_fold`, и что с ними стало.

    Закон тот же, что у переписи CLASH и у графа: ответ «смежности нет» ничего
    не значит, пока не сказано, скольких дверей поиск коснулся. До 10.08.2026
    82.6 % дверей `демо-v3` выпадали из этого предиката молча — не потому, что
    кто-то их скрывал, а потому, что ветка `len(adjacent) == 2` не имела
    альтернативы, и «не подошло» было неотличимо от «не смотрели».

    `by_degree` — сколько дверей у скольких ограниченных хозяином комнат.
    Ключ 2 есть ЕДИНСТВЕННЫЙ, дающий ребро; все прочие ключи суть названный
    исход, а не тишина.
    """

    doors_seen: int
    doors_without_host: int
    by_degree: Mapping[int, int]

    @property
    def edges_built(self) -> int:
        return self.by_degree.get(2, 0)

    @property
    def doors_with_host(self) -> int:
        return sum(self.by_degree.values())

    @property
    def refuted(self) -> int:
        """Двери с хозяином, чей хозяин ограничивает НЕ две комнаты."""
        return self.doors_with_host - self.edges_built

    def assert_balanced(self) -> None:
        total = self.doors_with_host + self.doors_without_host
        if total != self.doors_seen:
            raise FoldError(
                f"перепись смежности не сходится: дверей {self.doors_seen}, "
                f"с хозяином {self.doors_with_host}, без хозяина "
                f"{self.doors_without_host}")


def room_adjacency_census(
    nodes: Sequence[L1Node],
    rooms: Sequence[RoomInfo],
    elements_by_id: Mapping[str, L0Element],
) -> RoomAdjacencyCensus:
    """Перепись предиката `_semantic_fold` БЕЗ участия в построении дерева.

    Чистая функция над теми же входами, что у `_semantic_fold`, и намеренно
    отдельная от неё: перепись, которая меняла бы форму фолда, стоила бы
    каждого сохранённого merkle-индекса (см. шапку `_semantic_fold`). Здесь
    считается ровно то, о чём фолд молчал, и не двигается ничего.
    """
    boundary_to_rooms: dict[str, set[str]] = defaultdict(set)
    for room in rooms:
        for element_id in room.bounding_element_ids:
            boundary_to_rooms[element_id].add(room.id)

    seen = 0
    without_host = 0
    by_degree: Counter[int] = Counter()
    for node in nodes:
        source_id = node["source_element_id"]
        element = elements_by_id.get(source_id)
        if element is None or element.category != "OST_Doors":
            continue
        seen += 1
        if not element.host_id:
            without_host += 1
            continue
        by_degree[len(boundary_to_rooms.get(element.host_id, ()))] += 1

    census = RoomAdjacencyCensus(doors_seen=seen,
                                 doors_without_host=without_host,
                                 by_degree=dict(sorted(by_degree.items())))
    census.assert_balanced()
    return census


def _semantic_fold(
    nodes: Sequence[L1Node],
    rooms: Sequence[RoomInfo],
    elements_by_id: Mapping[str, L0Element],
    group_boundaries: Mapping[str, str] | None,
) -> tuple[list[TreeNode], list[L1Node]]:
    """Return proven semantic containers plus leaves that remain floor-loose.

    ПРЕДИКАТ СМЕЖНОСТИ ЗДЕСЬ НАЗЫВАЕТСЯ ТОЧНО, и это не педантизм: под именем
    «смежность комнат» в пакете живут ДВА РАЗНЫХ предиката, и до 10.08.2026 они
    носили одно слово.

    Тот, что строится ниже, утверждает НЕ «между этими комнатами можно пройти»,
    а **«ХОЗЯИН ЭТОЙ ДВЕРИ ОГРАНИЧИВАЕТ РОВНО ДВЕ КОМНАТЫ»** — факт об
    ОБЪЯВЛЕНИИ Revit (расчёт границ помещения), а не об измеренной геометрии
    двери. Второй предикат, `design_check._openings`, спрашивает, каких
    полигонов КАСАЕТСЯ точка проёма, и это факт об измерении. Замер их
    согласия (Жаккар): 0.288 на `демо`, 0.649 на `13A-RD-AR-K2_v33`, 0.324 на
    `Snowdon …Architectural`, 0.287 на `SOB6.2…AR_R23` — расхождение
    ДВУСТОРОННЕЕ на каждом здании, значит ни один не есть огрубление другого.

    СКОЛЬКО ДВЕРЕЙ ЭТОТ ПРЕДИКАТ НЕ ОБСЛУЖИВАЕТ (замер 10.08, распределение
    числа комнат, ограниченных хозяином двери):

        `демо-v3`      5 941 дверь: {0: 2816, 1: 154, **2: 1036**, 3: 966,
                       4: 648, 5: 50, 6: 76, 7: 25, 8: 55, 9: 113, 30: 1, 34: 1}
                       -> ребро получают 1 036 дверей, **17.4 %**
        `k2_ar_rd_v7`  2 096 дверей: {0: 66, 1: 449, **2: 1054**, 3: 326,
                       4: 125, 5: 25, 8: 8, 9: 1} -> **50.3 %**
        `sob62_r23_v5`   153 двери: {0: 15, 1: 79, **2: 47**, 3: 12}

    Дверь в стене, ограничивающей три комнаты, — НЕ ошибка данных, это реальная
    конфигурация, и раньше она исчезала здесь молча.

    ПОЧЕМУ ИСХОД ДЛЯ ОСТАЛЬНЫХ ЖИВЁТ НЕ ЗДЕСЬ. Дать им ребро в этой функции
    нельзя, не сдвинув всё, что стоит на форме дерева, и цена названа замером
    по коду, а не опасением: `merkle._build_merkle_node` хеширует узел как
    `_hash_parts(content_json, edges)`, где `edges` — хеши ДЕТЕЙ, поэтому иная
    раскладка комнат по контейнерам меняет хеш каждого узла выше листьев и
    обесценивает СОХРАНЁННЫЕ индексы: дедуп (×9.96 на Snowdon Plumbing) и
    отсечение диффом (33 617 поддеревьев на паре `k2_ar_rd_v7`→`v8`).
    Что при этом НЕ пострадало бы — `BuildingState`: он есть мультимножество
    `canon_op` ЛИСТЬЕВ, а листья сохраняются законом (`assert_preservation`),
    поэтому воспроизведение журнала (18/18, 5/5, 3/3, 2/2) и `merge3` к форме
    контейнеров нечувствительны. Различие между этими двумя половинами и есть
    ответ на вопрос «что стоит менять форму фолда».

    Поэтому исход ТИПИЗИРОВАН И ПОСЧИТАН в двух местах, ни одно из которых не
    трогает дерево: :func:`room_adjacency_census` ниже (число, по каждому
    зданию) и `building_graph.Relation.BOUNDED_BY_SAME_WALL`, где дверь со
    степенью != 2 даёт ребро `Modality.REFUTED` с именем правила
    `host_does_not_separate_exactly_two_rooms`. «Не нашли» стало отличимо от
    «не искали», не сдвинув ни одного дайджеста.
    """

    room_by_id = {room.id: room for room in rooms}
    room_ids = set(room_by_id)
    spatial = _RoomSpatialIndex(rooms)
    boundary_to_rooms: dict[str, set[str]] = defaultdict(set)
    for room in rooms:
        for element_id in room.bounding_element_ids:
            boundary_to_rooms[element_id].add(room.id)

    node_by_source = {node["source_element_id"]: node for node in nodes}
    stair_rooms: set[str] = set()
    for source_id, node in node_by_source.items():
        element = elements_by_id.get(source_id)
        if element is None or element.category != "OST_Stairs":
            continue
        explicit = boundary_to_rooms.get(source_id, set())
        if len(explicit) == 1:
            stair_rooms.update(explicit)
        if node["anchor_mm"] is not None:
            contained = spatial.containing(node["anchor_mm"])
            if len(contained) == 1:
                stair_rooms.add(contained[0])

    is_mop = {
        room.id: bool(_MOP_RE.search(room.name)) or room.id in stair_rooms
        for room in rooms
    }

    # ИМЯ ГОВОРИТ, ЧТО УТВЕРЖДАЕТСЯ: не «двери, соединяющие комнаты», а двери,
    # ЧЕЙ ХОЗЯИН ОГРАНИЧИВАЕТ РОВНО ДВЕ КОМНАТЫ. Остальные (82.6 % на `демо-v3`)
    # считает `room_adjacency_census`, а типизированный исход им даёт
    # `building_graph` — см. шапку функции.
    doors_whose_host_separates_two_rooms: list[tuple[str, str, str]] = []
    for source_id in sorted(node_by_source):
        element = elements_by_id.get(source_id)
        if (element is None or element.category != "OST_Doors"
                or not element.host_id):
            continue
        adjacent = sorted(boundary_to_rooms.get(element.host_id, ()))
        if len(adjacent) == 2:
            doors_whose_host_separates_two_rooms.append(
                (source_id, adjacent[0], adjacent[1]))

    non_mop_ids = sorted(room_id for room_id in room_ids if not is_mop[room_id])
    mop_ids = sorted(room_id for room_id in room_ids if is_mop[room_id])
    non_mop_uf = _UnionFind(non_mop_ids)
    mop_uf = _UnionFind(mop_ids)
    for _door_id, left, right in doors_whose_host_separates_two_rooms:
        if not is_mop[left] and not is_mop[right]:
            non_mop_uf.union(left, right)
        elif is_mop[left] and is_mop[right]:
            mop_uf.union(left, right)

    non_mop_components = _components(non_mop_uf, non_mop_ids)
    mop_components = _components(mop_uf, mop_ids)
    entry_doors: dict[str, set[str]] = defaultdict(set)
    for door_id, left, right in doors_whose_host_separates_two_rooms:
        if is_mop[left] == is_mop[right]:
            continue
        non_mop_room = right if is_mop[left] else left
        entry_doors[non_mop_uf.find(non_mop_room)].add(door_id)

    apartment_roots = {
        root for root in non_mop_components
        if len(entry_doors.get(root, ())) == 1
    }
    room_container: dict[str, tuple[str, str]] = {}
    for root, members in non_mop_components.items():
        for room_id in members:
            room_container[room_id] = (
                ("apartment", root) if root in apartment_roots
                else ("room", room_id)
            )
    mop_kind: dict[str, str] = {}
    for root, members in mop_components.items():
        kind = "core" if any(room_id in stair_rooms for room_id in members) else "mop"
        mop_kind[root] = kind
        for room_id in members:
            room_container[room_id] = (kind, root)

    assigned_to_room: dict[str, list[L1Node]] = defaultdict(list)
    assigned_to_container: dict[tuple[str, str], list[L1Node]] = defaultdict(list)
    loose: list[L1Node] = []
    for node in sorted(nodes, key=lambda item: item["source_element_id"]):
        source_id = node["source_element_id"]
        element = elements_by_id.get(source_id)
        if source_id in room_ids:
            claims = {source_id}
        elif source_id in boundary_to_rooms:
            claims = set(boundary_to_rooms[source_id])
        elif (element is not None and element.host_id
              and element.host_id in boundary_to_rooms):
            claims = set(boundary_to_rooms[element.host_id])
        elif node["anchor_mm"] is not None:
            claims = set(spatial.containing(node["anchor_mm"]))
        else:
            claims = set()
        claims &= room_ids
        if len(claims) == 1:
            assigned_to_room[next(iter(claims))].append(node)
            continue
        if len(claims) > 1:
            containers = {room_container[room_id] for room_id in claims}
            if len(containers) == 1:
                container = next(iter(containers))
                if container[0] != "room":
                    assigned_to_container[container].append(node)
                    continue
        loose.append(node)

    room_nodes: dict[str, TreeNode] = {}
    for room_id in sorted(room_ids):
        sources = assigned_to_room.get(room_id, [])
        if not sources:
            continue
        room = room_by_id[room_id]
        room_nodes[room_id] = _make_tree_node(
            "room",
            label=room.name,
            children=_fold_payloads(sources, group_boundaries),
            area_m2=room.area_m2,
        )

    semantic: list[TreeNode] = []
    for root in sorted(apartment_roots):
        container = ("apartment", root)
        children = [
            room_nodes[room_id]
            for room_id in non_mop_components[root]
            if room_id in room_nodes
        ]
        children.extend(_fold_payloads(
            assigned_to_container.get(container, []), group_boundaries))
        if children:
            semantic.append(_make_tree_node(
                "apartment",
                label=f"apartment:{root}",
                children=children,
                macro={
                    "type": "apartment",
                    "entry_door_id": next(iter(sorted(entry_doors[root]))),
                },
            ))
    for root, members in sorted(mop_components.items()):
        kind = mop_kind[root]
        container = (kind, root)
        children = [room_nodes[room_id] for room_id in members
                    if room_id in room_nodes]
        children.extend(_fold_payloads(
            assigned_to_container.get(container, []), group_boundaries))
        if children:
            semantic.append(_make_tree_node(
                kind,
                label=f"{kind}:{root}",
                children=children,
                macro={"type": kind, "has_stairs": kind == "core"},
            ))
    grouped_room_ids = {
        room_id for root in apartment_roots
        for room_id in non_mop_components[root]
    } | set(mop_ids)
    semantic.extend(
        room_nodes[room_id] for room_id in sorted(room_nodes)
        if room_id not in grouped_room_ids
    )
    return sorted(
        semantic, key=lambda node: (node["kind"], node["node_id"])), loose


@dataclass(frozen=True, slots=True)
class _Floor:
    level_name: str
    elevation_mm: float
    node: TreeNode


def _floor_origin(floor: _Floor) -> tuple[float, float, float]:
    return (0.0, 0.0, floor.elevation_mm)


def _floor_leaf_buckets(floor: _Floor) -> dict[str, list[L1Node]]:
    result: dict[str, list[L1Node]] = defaultdict(list)
    for leaf in iter_l1_leaves(floor.node):
        result[canon_hash(leaf, _floor_origin(floor))].append(leaf)
    for members in result.values():
        members.sort(key=lambda node: node["source_element_id"])
    return result


def _jaccard_buckets(
    left: Mapping[str, Sequence[L1Node]],
    right: Mapping[str, Sequence[L1Node]],
) -> float:
    left_hashes = set(left)
    right_hashes = set(right)
    union = left_hashes | right_hashes
    return 1.0 if not union else len(left_hashes & right_hashes) / len(union)


def _floor_diff(
    template_buckets: Mapping[str, list[L1Node]],
    member_buckets: Mapping[str, list[L1Node]],
) -> dict[str, list[L1Node]]:
    added: list[L1Node] = []
    removed: list[L1Node] = []
    for canonical_hash in sorted(set(template_buckets) | set(member_buckets)):
        template_nodes = template_buckets.get(canonical_hash, [])
        member_nodes = member_buckets.get(canonical_hash, [])
        shared = min(len(template_nodes), len(member_nodes))
        removed.extend(template_nodes[shared:])
        added.extend(member_nodes[shared:])
    return {
        "added": sorted(added, key=lambda node: node["source_element_id"]),
        "removed": sorted(
            removed, key=lambda node: node["source_element_id"]),
    }


def _regular_dz(floors: Sequence[_Floor]) -> float | None:
    if len(floors) < 2:
        return None
    deltas = [
        floors[index + 1].elevation_mm - floors[index].elevation_mm
        for index in range(len(floors) - 1)
    ]
    median = float(statistics.median(deltas))
    if all(abs(delta - median) <= DZ_TOL for delta in deltas):
        return median
    return None


def _stack_node(
    floors: Sequence[_Floor],
    buckets: Mapping[str, Mapping[str, list[L1Node]]],
) -> TreeNode:
    ordered = sorted(floors, key=lambda floor: (
        floor.elevation_mm, floor.level_name, floor.node["node_id"]))
    template = ordered[0]
    dz = _regular_dz(ordered)
    macro_type = "stack" if dz is not None else "repeat_on_levels"
    diffs: dict[str, dict[str, list[L1Node]]] = {}
    for floor in ordered[1:]:
        diff = _floor_diff(
            buckets[template.node["node_id"]],
            buckets[floor.node["node_id"]],
        )
        if diff["added"] or diff["removed"]:
            diffs[floor.level_name] = diff
    macro: dict[str, Any] = {
        "type": macro_type,
        "levels": [floor.level_name for floor in ordered],
        "base_z_mm": ordered[0].elevation_mm,
        "template_node_id": template.node["node_id"],
        "diffs": diffs,
    }
    if dz is not None:
        macro["dz_mm"] = dz
    return _make_tree_node(
        "stack",
        label=f"{macro_type}:{len(ordered)} levels",
        children=[floor.node for floor in ordered],
        macro=macro,
    )


def _vertical_fold(floors: Sequence[_Floor]) \
        -> list[tuple[float, TreeNode]]:
    buckets = {
        floor.node["node_id"]: _floor_leaf_buckets(floor)
        for floor in floors
    }
    exact: dict[str, list[_Floor]] = defaultdict(list)
    for floor in floors:
        signature = canon_hash(floor.node, _floor_origin(floor))
        exact[signature].append(floor)

    groups: list[list[_Floor]] = []
    unmatched: list[_Floor] = []
    for signature in sorted(exact):
        members = sorted(exact[signature], key=lambda floor: (
            floor.elevation_mm, floor.level_name))
        if len(members) >= 2:
            groups.append(members)
        else:
            unmatched.extend(members)
    groups.sort(key=lambda group: (
        group[0].elevation_mm, group[0].level_name))
    unmatched.sort(key=lambda floor: (floor.elevation_mm, floor.level_name))

    # First attach near floors to exact templates, selecting the strongest
    # similarity and using template elevation/name as deterministic tie-breaks.
    remaining: list[_Floor] = []
    for floor in unmatched:
        candidates: list[tuple[float, int]] = []
        for index, group in enumerate(groups):
            similarity = _jaccard_buckets(
                buckets[group[0].node["node_id"]],
                buckets[floor.node["node_id"]],
            )
            if similarity >= SIM_THRESHOLD:
                candidates.append((similarity, index))
        if not candidates:
            remaining.append(floor)
            continue
        _similarity, group_index = max(
            candidates,
            key=lambda item: (
                item[0], -groups[item[1]][0].elevation_mm,
                groups[item[1]][0].level_name,
            ),
        )
        groups[group_index].append(floor)

    # Near-match is the main real-model path, so it must also be able to seed a
    # group when no byte-identical pair exists.
    standalone: list[_Floor] = []
    while remaining:
        template = remaining.pop(0)
        group = [template]
        still_unmatched: list[_Floor] = []
        for candidate in remaining:
            similarity = _jaccard_buckets(
                buckets[template.node["node_id"]],
                buckets[candidate.node["node_id"]],
            )
            if similarity >= SIM_THRESHOLD:
                group.append(candidate)
            else:
                still_unmatched.append(candidate)
        remaining = still_unmatched
        if len(group) >= 2:
            groups.append(group)
        else:
            standalone.append(template)

    result: list[tuple[float, TreeNode]] = []
    for group in groups:
        elevation = min(floor.elevation_mm for floor in group)
        result.append((elevation, _stack_node(group, buckets)))
    result.extend((floor.elevation_mm, floor.node) for floor in standalone)
    return sorted(result, key=lambda item: (item[0], item[1]["node_id"]))


def _level_elevations(document: L0Document) -> dict[str, float]:
    result: dict[str, float] = {}
    for level in document.levels:
        if level.name in result and result[level.name] != level.elevation_mm:
            raise FoldError(
                f"duplicate level name {level.name!r} has multiple elevations")
        result[level.name] = level.elevation_mm
    return result


def _build_floor(
    level_name: str,
    elevation_mm: float,
    nodes: Sequence[L1Node],
    rooms: Sequence[RoomInfo],
    elements_by_id: Mapping[str, L0Element],
    group_boundaries: Mapping[str, str] | None,
) -> _Floor:
    if rooms:
        semantic, loose = _semantic_fold(
            nodes, rooms, elements_by_id, group_boundaries)
        children = semantic + _fold_payloads(loose, group_boundaries)
    else:
        children = _zoned_fold(nodes, elements_by_id, group_boundaries)
    floor_node = _make_tree_node(
        "floor",
        label=level_name,
        children=children,
        macro={
            "type": "floor",
            "level_name": level_name,
            "elevation_mm": elevation_mm,
            "semantic_mode": "rooms" if rooms else "zones",
        },
    )
    return _Floor(level_name, elevation_mm, floor_node)


def assert_preservation(tree: TreeNode, nodes: Sequence[L1Node]) -> None:
    """Raise if the folded tree loses, duplicates, or mutates an L1 leaf."""

    expected = {node["_id"]: node for node in nodes}
    actual_leaves = list(iter_l1_leaves(tree))
    actual_ids = [node["_id"] for node in actual_leaves]
    if Counter(actual_ids) != Counter(expected.keys()):
        raise FoldError("folded tree does not preserve the exact L1 leaf multiset")
    for leaf in actual_leaves:
        if leaf != expected[leaf["_id"]]:
            raise FoldError("folded tree mutated an L1 leaf payload")


def fold_document(
    document: L0Document,
    nodes: Iterable[L1Node],
    *,
    group_index: GroupIndexInput | None = None,
) -> TreeNode:
    """Fold a materialized L0 document's validated flat L1 into an L3 tree."""

    materialized = tuple(nodes)
    try:
        validated = validate_l1_nodes(materialized)
    except L1SchemaError as exc:
        raise FoldError(f"invalid L1 input: {exc}") from exc
    l0_source_ids = {element.element_id for element in document.elements}
    l1_source_ids = {node["source_element_id"] for node in validated}
    if l0_source_ids != l1_source_ids:
        missing = len(l0_source_ids - l1_source_ids)
        invented = len(l1_source_ids - l0_source_ids)
        raise FoldError(
            f"L0/L1 source mismatch: missing={missing}, invented={invented}")

    elements_by_id = {
        element.element_id: element for element in document.elements
    }
    group_boundaries: Mapping[str, str] | None = None
    if group_index is not None:
        try:
            group_boundaries = analyze_group_relations(
                group_index, l0_source_ids).boundary_by_source
        except (GroupIndexPayloadError, TypeError, ValueError) as exc:
            raise FoldError(f"invalid group_index: {exc}") from exc
    level_elevations = _level_elevations(document)
    by_level: dict[str, list[L1Node]] = defaultdict(list)
    unassigned: list[L1Node] = []
    for node in validated:
        if node["level_name"] is None:
            unassigned.append(node)
        else:
            by_level[node["level_name"]].append(node)
    rooms_by_level: dict[str, list[RoomInfo]] = defaultdict(list)
    for room in document.rooms:
        if room.level_name is not None:
            rooms_by_level[room.level_name].append(room)

    floors: list[_Floor] = []
    for level_name in sorted(by_level):
        floor_nodes = sorted(
            by_level[level_name], key=lambda node: node["source_element_id"])
        if level_name not in level_elevations:
            raise FoldError(
                f"L1 level {level_name!r} has no matching L0 elevation")
        elevation = level_elevations[level_name]
        floors.append(_build_floor(
            level_name,
            elevation,
            floor_nodes,
            sorted(rooms_by_level.get(level_name, ()), key=lambda room: room.id),
            elements_by_id,
            group_boundaries,
        ))
    floors.sort(key=lambda floor: (
        floor.elevation_mm, floor.level_name, floor.node["node_id"]))
    building_children = [node for _elevation, node in _vertical_fold(floors)]

    if unassigned:
        unassigned_children = _zoned_fold(
            sorted(unassigned, key=lambda node: node["source_element_id"]),
            elements_by_id,
            group_boundaries,
        )
        building_children.append(_make_tree_node(
            "group",
            label="unassigned-level",
            children=unassigned_children,
            macro={"type": "unassigned_level"},
        ))
    tree = _make_tree_node(
        "building",
        label=document.doc_name,
        children=building_children,
        macro={"type": "building"},
    )
    assert_preservation(tree, validated)
    return tree


def fold_l1(
    nodes: Iterable[L1Node],
    document: L0Document,
    *,
    group_index: GroupIndexInput | None = None,
) -> TreeNode:
    """Argument-order convenience alias for streaming pipeline composition."""

    return fold_document(document, nodes, group_index=group_index)


__all__ = [
    "RoomAdjacencyCensus",
    "room_adjacency_census",
    "FIDELITY_CANON_VERSION",
    "FidelityCanon",
    "FoldError",
    "TEMPLATE_CANON_VERSION",
    "TemplateCanon",
    "TreeFacts",
    "TreeNode",
    "assert_preservation",
    "canon_hash",
    "canon_op",
    "fold_document",
    "fold_l1",
    "iter_l1_leaves",
    "multiset_hash",
    "stable_tree_id",
]
