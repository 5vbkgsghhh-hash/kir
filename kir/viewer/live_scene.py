"""A SCENE FROM THE LIVE JOURNAL — what the model HAS DECLARED, without
having built it yet.

THIS IS THE HALF EVERYTHING ELSE IS FOR. `scene.py` shows the PARSED
building. Here is what does not exist in Revit yet at all: the programs
of a three-hour session from `kir.live.journal`, including what hasn't
been committed.

════════════════════════════════════════════════════════════════════════════
TWO DIFFERENT CONTRACTS: AUTHOR MESH AND THE CLASH SHELL
════════════════════════════════════════════════════════════════════════════
`create_directshape.mesh` is drawn directly from declared triangles, even
if clash does not support the category. For all other elements, the
shells are built by `clash_bundle.bundle_elements` +
`clash.snapshot.build_from_elements`. Matching the authored mesh proves
neither native BIM, nor BRep, nor clash coverage.

════════════════════════════════════════════════════════════════════════════
A SNAPSHOT IS NEEDED FOR TYPE GEOMETRY, BUT NOT FOR AUTHOR MESH
════════════════════════════════════════════════════════════════════════════
11.08.2026, a batch of six walls and a pipe, `bundle_elements` +
`build_from_elements`:

    without a snapshot   →  0 bodies out of 7, all seven:
                             `needs_live_model`
    (wall thickness and a pipe's outer diameter live in the TYPE)

The same at scale (the lead's measurement, `snowdon_plumb_v4`, the
rebuild door):

    without a snapshot   →     905 bodies
    with a snapshot      →  16 247 out of 16 257  (99.94 %)

These historical measurements pertain to the shells of typed elements,
not to the standalone display of declared meshes. It arrives in the
journal via `plan_stream.remember_sections` and sits in
`SessionJournal.sections`. The absence of a snapshot does not forbid
displaying the mesh.

════════════════════════════════════════════════════════════════════════════
WHY AN ELEMENT HAS NO BODY — FIVE DIFFERENT FACTS, FIXED BY DIFFERENT
PEOPLE
════════════════════════════════════════════════════════════════════════════
`clash_bundle.BLIND_CLASS_RU` is a closed table of five classes
(`never_a_body`, `op_expresses_no_body`, `not_declared_by_program`,
`needs_live_model`, `refused_by_hull_gate`) plus `unclassified` for holes
in it. "No body" without a reason is useless; with a reason it is an
instruction on what to do: the AUTHOR fixes the operand, the ground stage
fixes the snapshot, `kir/clash` fixes the containment lock.

THE HONEST BOUNDARY OF THIS DISPLAY, AND IT IS NAMED.
`BundleGeometry.no_geometry` counts reasons AS A BATCH (`{reason: how
many}`), not by name per element. So the class is shown as a
DISTRIBUTION across the session, while on the element there is only the
fact "no body" and the refusal that the shell builder itself named.
Attributing a specific class to a specific element would be a guess, and
a guess dressed up on an element reads as a measurement.

════════════════════════════════════════════════════════════════════════════
THE PLAN OUTLINE IS A FALLBACK PATH, AND IT IS MARKED
════════════════════════════════════════════════════════════════════════════
An element without a body has no right to DISAPPEAR: a vanished element
is indistinguishable from a nonexistent one. So wherever `preview` knows
the outline in plan, the element is drawn as an extrusion of that outline
and gets `Fidelity.NO_BODY` — that is, on screen it is a ghost, not a
body. A height that isn't in the program gives `FALLBACK_HEIGHT_MM` and
the `height_unknown` label: a plausible number is worse than a missing
one.

IDENTIFIERS ARE QUALIFIED IN ADVANCE. `bundle_elements` addresses
elements as `p1/w0` (`bundle_oid`), while `preview` uses the operation's
raw `id`. For both to be talking about the same element, the batch is
rewritten ONCE before both calls: `id` and every `{"by":"ref"}` reference
get a program prefix. The rewrite is TOTAL and therefore safe: by the
compiler's rule (`KIR-L003`), `ref` only points to an earlier op of THE
SAME program, so there are never references pointing outward, and
nothing to break.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any, Mapping, Sequence

from kir.viewer import graph as _graph
from kir.viewer import honesty as _honesty
from kir.viewer import reconcile as _reconcile
from kir.viewer.codec import SceneBuilder
from kir.viewer.scene import FIDELITY_CODE, TRUST_CODE

__all__ = ("FALLBACK_HEIGHT_MM", "FLOAT32_EXACT_MM", "LIVE_BLIND_SPOTS",
           "StaleBase", "base_digest", "programs_since",
           "scene_from_programs", "scene_from_session")

#: The radius within which float32 represents WHOLE millimeters exactly:
#: 24 mantissa bits = 16 777 216. Farther from the coordinate origin, a
#: millimeter stops being representable, and merging the delta with the
#: base would drift at the SUB-MILLIMETER level — that is, invisibly.
#: That's why the radius is checked and named, not implied.
FLOAT32_EXACT_MM = 16_777_216.0


class StaleBase(ValueError):
    """The client's base is not the one the delta applies to.

    A TYPED REFUSAL, NOT A SILENT MERGE. Gluing a tail onto the wrong
    base means showing a building that never existed — which is worse
    than a blank screen, because a blank screen is visible.
    """

#: A height that is NOT in the program. The value is chosen to be
#: NOTICEABLE, not typical: 2500 mm looks like a real wall and would
#: hide among the real ones, while 100 mm is visible right away. The
#: element is additionally marked `height_unknown` and goes into the
#: census — the number here is not a "sensible default" but an
#: admission of not knowing.
FALLBACK_HEIGHT_MM = 100.0

#: The names of height parameters per the registry. The list is closed:
#: a parameter that isn't here won't be seen by the extrusion, and that
#: will go into `height_unknown`, not into a silent zero.
_HEIGHT_FIELDS = ("height_mm", "depth_mm", "thickness_mm")

#: The names of the vertical base for an op WITHOUT a host.
#:
#: 🔴 `offset_mm` USED TO STAND HERE, AND IT WAS A HOMONYM (F-156,
#: 29.08.2026). For `create_door`/`create_window`, `offset_mm` means the
#: DISTANCE ALONG THE HOST from its start, not a lift. Measurement: a
#: door with `offset_mm=3000` was drawn at `z0=3000` — three meters
#: ABOVE the opening it stands in. The same kind of thing as
#: `Observation.unit` versus `of_unit` (`assembly_view.py:298`).
_BASE_FIELDS = ("base_offset_mm", "elev_mm")

#: The vertical base of an op WITH a host. `sill_mm` is the opening's
#: lift above the bottom of the host, and that is ITS real vertical.
_HOSTED_BASE_FIELDS = ("sill_mm",)


def _base_fields_for(op: Mapping[str, Any]) -> tuple[str, ...]:
    """The names of the vertical base BY OP KIND — ASKED FROM THE
    REGISTRY.

    🔴 NO LIST OF OPS IS MAINTAINED HERE. The package used to offer a
    hand-written `_OFFSET_IS_ALONG_HOST = ("create_door",
    "create_window")`; such a list is forever catching up to the
    registry and will fall behind on the very first new host-bearing op.
    The registry knows the trait on its own: `offset_mm` appears in the
    WHOLE registry for exactly two ops, and BOTH have `host` — that is,
    "has a host" itself means "offset_mm is along it" (confirmed by
    execution on 30.08.2026).

    An op that isn't in the registry is read by the rule WITHOUT
    `offset_mm`: an unknown kind has no right to silently drift upward.
    """
    from kir import spec

    op_spec = spec.OPS.get(str(op.get("op") or ""))
    if op_spec is None:
        return _BASE_FIELDS
    names = {p.name for p in op_spec.params}
    if "host" in names:
        return _HOSTED_BASE_FIELDS + _BASE_FIELDS
    return _BASE_FIELDS

LIVE_BLIND_SPOTS: tuple[str, ...] = (
    "это ЗАЯВЛЕНО программой, а не прочитано из Revit: модель ещё не строилась",
    "clash-оболочки зависят от чисел программы и типа; authored mesh "
    "показывается независимо от clash-категории и наличия снимка",
    "класс причины «нет тела» считается ПАЧКОЙ, а не на элементе: на элементе "
    "сказано только «тела нет» и отказ построителя оболочек",
    "высота берётся из параметра операции; где параметра нет — заглушка и "
    "метка height_unknown, а не правдоподобное число",
    "top_level не разрешается: это грундинг, а он требует живого документа",
    "всё, что выводит Revit (стыковки стен, слои, фитинги трасс, "
    "триангуляция рельефа), здесь отсутствует по построению",
    "часть программ Revit ещё отвергнет: журнал наполняется ДО записи",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def live_origin(datums: Sequence[Mapping[str, Any]]) -> tuple[float, float, float]:
    """The origin of a live scene's coordinates — from DATUMS, not from
    the bounding box of the elements.

    WHY THIS IS LOAD-BEARING, NOT A MATTER OF TASTE. The codec writes
    coordinates as OFFSETS from the origin. If the origin were computed
    from the bounding box of the current elements (as the parse scene
    does), then every new program would SHIFT the origin — and all
    previously sent coordinates would become wrong. A delta against such
    a base would glue the building together out of two coordinate
    systems, and the divergence would grow smoothly and therefore
    invisibly.

    Hence the rule: a live scene's origin depends ONLY on what the delta
    does not change — on datums. `create_level` gives the elevation, XY
    stays zero: the program is written by the author, and its numbers
    sit at the project origin by construction.

    THE PRICE IS NAMED. The offset loses centering, so a building
    farther than `FLOAT32_EXACT_MM` from the project origin will lose
    millimeter precision. This is checked on every scene
    (`origin_overflow`), not promised.
    """
    elevations = [float(op.get("elev_mm"))
                  for op in datums
                  if op.get("op") == "create_level"
                  and isinstance(op.get("elev_mm"), (int, float))
                  and not isinstance(op.get("elev_mm"), bool)]
    return (0.0, 0.0, min(elevations) if elevations else 0.0)


def base_digest(datums: Sequence[Mapping[str, Any]], sections: Any,
                evicted: int) -> str:
    """A signature of EVERYTHING capable of changing elements ALREADY
    SENT.

    A delta is legitimate exactly when the past is unchanged. There are
    exactly three channels through which a new program can change an old
    element, and all three are here:

      * DATUMS. `create_level` sets an elevation that is referenced by
        name by programs that came EARLIER. The journal keeps them
        separately (`_DATUM_OPS`), so their state is captured precisely;
      * THE TYPE SNAPSHOT. Wall thickness and a pipe's outer diameter
        come from the type; `remember_sections` can refresh the
        snapshot at any moment, and then the bodies of ALL elements get
        recomputed;
      * EVICTION. The journal is bounded; evicting from the head removes
        programs that the client has already drawn.

    What is NOT here, and why that is legitimate: by the compiler's rule
    (`KIR-L003`), `ref` references never leave the bounds of their own
    program, so a program cannot redefine someone else's element.

    WHAT THE DELTA DOES NOT RECOMPUTE, AND THIS IS NAMED IN THE SCENE
    HEADER: `preview` judges outliers (`FAR_OUTLIER`) and coinciding
    walls across the WHOLE sheet, meaning a new program can change these
    MARKS on old elements. Today the scene does not carry them at all,
    so this does not affect its content; but as soon as they travel into
    the buffer, they will become a fourth channel.
    """
    payload = {
        "schema": "kir-live-base/1",
        "datums": [_canonical(op) for op in datums],
        "sections": None if sections is None else _canonical(sections),
        "evicted": int(evicted),
    }
    return hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()[:32]


def programs_since(device_id: str | None, doc_key: str = "",
                   since: int = 0) -> tuple[list[Any], dict[str, Any]]:
    """Session programs, starting from `seq >= since`. The change
    transport in full.

    There is no diff protocol of its own, and there won't be one:
    `SessionJournal` already numbers programs (`seq`, `next_seq`) and
    already survives a missed poll. The client holds the cursor and sends
    it back — a lost poll costs one frame, not one program.

    The second value is a note, and it is mandatory: a client that gets
    an empty list must be able to tell "nothing changed" apart from
    "there is no session" and from "programs were evicted and will no
    longer be shown."
    """
    from kir.live import journal as _journal

    session = _journal.get(_journal.key_for(device_id, doc_key))
    if session is None:
        return [], {"session": False,
                    "reason": "сессии с таким ключом в журнале нет",
                    "next_seq": 0, "evicted": 0, "sections": False}
    fresh = [rec for rec in session.records if rec.seq >= since]
    sections = getattr(session, "sections", None)
    note = {
        "session": True,
        # ────────────────────────────────────────────────────────────────
        # A CURSOR SLICE IS A TAIL, NOT A BUILDING. FOUND ON 11.08 IN MY
        # OWN CODE.
        # ────────────────────────────────────────────────────────────────
        # `since > 0` returns ONLY the programs after the cursor, and the
        # scene built from them is assembled as if it were complete: the
        # header carries `elements`, the census converges, the picture
        # draws. Measurement on a journal of two programs: `since=1`
        # gives a building of ONE element, `since=2` gives an EMPTY
        # building, and neither differs in shape from a real one. A
        # client following the cursor would show a house from which
        # everything before the cursor had silently vanished.
        #
        # There is no scene delta today: `scene_from_programs` only knows
        # how to build the whole thing. So this is not "almost a delta"
        # but a NAMED tail: `partial` travels in the header, and the
        # client must either apply it as an addition to its own base, or
        # request `since=0`. A silently half-shown building is exactly
        # the defect this whole screen was written against, and it was
        # mine.
        "partial": since > 0,
        "since": since,
        "next_seq": session.next_seq,
        "held": len(session.records),
        "returned": len(fresh),
        "evicted": session.programs_evicted,
        "stage": "planned",
        "assertion": "self_reported",
        # Snapshot availability concerns type-dependent hulls; declared meshes
        # do not require a live model snapshot.
        "sections": bool(sections),
        # THREE STATES, NOT TWO (14.08.2026). `bool()` was collapsing "WE
        # DIDN'T ASK" and "we asked, there are no sections" into a single
        # answer — exactly what the `prune_ground_snapshot` docstring
        # forbids: "an empty dict and a missing dict are different
        # facts, the reader must tell them apart." Live, this cost half
        # an hour: the scene said "NO snapshot," and there was no way to
        # tell whether grounding hadn't arrived or the document really
        # was empty.
        "sections_state": ("present" if sections
                           else "empty" if sections is not None
                           else "absent"),
        "sections_ru": ("снимок типов открытой модели ЕСТЬ: оболочки строятся из "
                        "толщин и сечений типов"
                        if sections else
                        "снимок ЗАПРОШЕН, но сечений в документе нет: "
                        "типозависимые оболочки могут отсутствовать; authored mesh от снимка не зависит"
                        if sections is not None else
                        "снимок НЕ ЗАПРАШИВАЛСЯ (заземление не дошло): "
                        "толщины стен и диаметры труб живут в ТИПЕ, поэтому "
                        "типозависимые оболочки могут отсутствовать; authored mesh от снимка не зависит"),
    }
    if since > 0:
        note["partial_ru"] = (
            f"ЭТО ХВОСТ ЖУРНАЛА, А НЕ ЗДАНИЕ: показаны только программы с "
            f"seq >= {since} ({len(fresh)} из {len(session.records)}). "
            f"Всё, что было раньше, в этой сцене ОТСУТСТВУЕТ. Для полного "
            f"здания нужен since=0")
    if session.programs_evicted:
        # EVICTION IS NAMED. A scene missing its first programs and a
        # scene that never had them look the same — exactly the silence
        # that is forbidden.
        note["truncated_ru"] = (
            f"{session.programs_evicted} программ вытеснено из журнала и в "
            f"сцене их НЕТ")
    return fresh, note


def _ops_of(item: Any) -> list[Mapping[str, Any]]:
    """`ProgramRecord` | `{"ops": …}` | a list -> a list of operations."""
    raw = getattr(item, "ops", None)
    if raw is None and isinstance(item, Mapping):
        raw = item.get("ops")
    if raw is None and isinstance(item, Sequence) and not isinstance(
            item, (str, bytes)):
        raw = item
    return [op for op in (raw or ()) if isinstance(op, Mapping)]


def _qualify(pack: Sequence[Sequence[Mapping[str, Any]]],
             *, first_position: int = 1) -> list[list[dict[str, Any]]]:
    """A batch -> the same batch with addresses at BATCH scale
    (`p1/w0`).

    Both `id` and EVERY `{"by": "ref", "value": …}` reference are
    rewritten. The walk is recursive, because references live both in
    lists (`refs_w`) and in nested dicts, and a list of field names
    ("host", "level", "wall") would drift from the registry on the very
    first new operation — and would drift SILENTLY. The same argument by
    which `live.transfer.refs_of` reads `spec.OPS[...].params`, not a
    list of names.

    THE SAFETY OF TOTALITY. By the compiler's rule (`KIR-L003`), `ref`
    only points to an earlier op of THE SAME program. There are never
    outward references, so an identical prefix on both the target and
    the reference preserves every link, and addresses between programs
    stop colliding.
    """
    from kir.clash_bundle import bundle_oid

    def walk(value: Any, prefix: str) -> Any:
        if isinstance(value, Mapping):
            if value.get("by") == "ref" and isinstance(value.get("value"), str):
                return {**value, "value": f"{prefix}{value['value']}"}
            return {k: walk(v, prefix) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [walk(v, prefix) for v in value]
        return value

    out: list[list[dict[str, Any]]] = []
    for position, ops in enumerate(pack, start=first_position):
        # The prefix is taken FROM `bundle_oid`, not assembled here: the
        # separator belongs to the address, and a second copy of it is a
        # second address format.
        prefix = bundle_oid(position, "")
        program: list[dict[str, Any]] = []
        for op in ops:
            fresh = {k: walk(v, prefix) for k, v in op.items() if k != "id"}
            if op.get("id"):
                fresh["id"] = f"{prefix}{op['id']}"
            program.append(fresh)
        out.append(program)
    return out


def _z_of(op: Mapping[str, Any] | None, base_mm: float
          ) -> tuple[float, float, bool]:
    """(z0, z1, is the height known?) — and the third value is NOT
    decorative."""
    if op is None:
        return base_mm, base_mm + FALLBACK_HEIGHT_MM, False
    offset = 0.0
    for name in _base_fields_for(op):
        value = op.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            offset = float(value)
            break
    for name in _HEIGHT_FIELDS:
        value = op.get(name)
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and value):
            z0 = base_mm + offset
            return z0, z0 + abs(float(value)), True
    z0 = base_mm + offset
    return z0, z0 + FALLBACK_HEIGHT_MM, False


_FLOAT32_MAX = 3.4028234663852886e38


def _display_bounds_fit(lo: tuple, hi: tuple, origin: Any = None) -> bool:
    """Necessary float32-frame limits, without a world-coordinate limit."""
    if any(not math.isfinite(low) or not math.isfinite(high)
           or not math.isfinite(high - low) or high - low > 2 * _FLOAT32_MAX
           for low, high in zip(lo, hi)):
        return False
    return origin is None or all(
        math.isfinite(v - origin[i]) and abs(v - origin[i]) <= _FLOAT32_MAX
        for point in (lo, hi) for i, v in enumerate(point))


def _display_mesh(mesh: Any) -> tuple[tuple, tuple, tuple, tuple]:
    """Validate display buffers, not Revit limits, solidness or connectivity.

    SceneBuilder is an atomic packer, but deliberately not an input validator:
    it coerces indices and substitutes non-finite coordinates. This boundary
    must reject those inputs before either bounds or buffers use them.
    """
    def sequence(value: Any) -> bool:
        return isinstance(value, (list, tuple))

    if not isinstance(mesh, Mapping):
        raise ValueError("mesh must contain vertices_mm and triangles")
    raw_vertices, raw_triangles = mesh.get("vertices_mm"), mesh.get("triangles")
    if not sequence(raw_vertices) or not raw_vertices or not sequence(raw_triangles) or not raw_triangles:
        raise ValueError("mesh vertices_mm and triangles must be nonempty arrays")
    vertices = []
    for point in raw_vertices:
        if not sequence(point) or len(point) != 3:
            raise ValueError("mesh vertex must contain exactly three coordinates")
        try:
            valid = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) for v in point)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("mesh coordinates must be finite numbers, not booleans")
        vertices.append(tuple(float(v) for v in point))
    triangles = []
    for triangle in raw_triangles:
        if (not sequence(triangle) or len(triangle) != 3
                or any(not isinstance(i, int) or isinstance(i, bool)
                       or not 0 <= i < len(vertices) for i in triangle)):
            raise ValueError("mesh triangle must contain three in-range integer indices")
        triangles.append(tuple(triangle))
    lo = tuple(min(point[i] for point in vertices) for i in range(3))
    hi = tuple(max(point[i] for point in vertices) for i in range(3))
    if not _display_bounds_fit(lo, hi):
        raise ValueError("mesh intrinsic extent cannot fit any finite float32-relative frame")
    return tuple(vertices), tuple(triangles), lo, hi


def scene_from_programs(programs: Sequence[Any], *, doc_key: str = "",
                        snapshot: Any = None,
                        journal: Mapping[str, Any] | None = None,
                        origin_mm: tuple[float, float, float] | None = None,
                        first_position: int = 1,
                        session_key: tuple[str, str] | None = None,
                        whole: bool = True,
                        context_programs: int = 0,
                        upto_seq: int = 0
                        ) -> tuple[bytes, dict[str, Any]]:
    """Programs -> scene bytes. The same codec, honesty dictionary, and
    geometry pipeline as for a parsed building."""
    from kir.clash import geom as G
    from kir.clash import hulls as HU
    from kir.clash import snapshot as S
    from kir import clash_bundle as CB
    from kir import preview as P
    from kir.ops_shape import DIRECTSHAPE_CATEGORIES

    started = time.perf_counter()
    # TWO CONSUMERS, AND ONLY ONE OF THEM QUALIFIES ADDRESSES ITSELF.
    # `bundle_elements` addresses elements with `bundle_oid` INSIDE
    # ITSELF, so it is handed the RAW batch: feeding it an
    # already-qualified one means getting `p1/p1/w0`. Measurement on
    # 11.08 (this very defect was caught by it): five pipes arrived in
    # the scene TWICE — as a body under a double address and as a ghost
    # under a single one, and the census showed 13 elements where there
    # were 8. `preview` does not build its own address at all, so it is
    # handed the batch qualified HERE — and then both are saying `p1/w0`
    # about the same element.
    raw = [_ops_of(item) for item in programs]
    # THE PROGRAM NUMBER IS AT SESSION SCALE, NOT SLICE SCALE. A delta
    # that restarted numbering at `p1` would hand new elements addresses
    # already occupied by old ones on the client, and merging would
    # silently SUBSTITUTE them. An address must depend only on what it
    # points to.
    flat: list[Mapping[str, Any]] = [
        op for ops in _qualify(raw, first_position=first_position) for op in ops]

    # ── 1. BODIES. Built by `clash_bundle`, not by this module.
    # `bundle_elements` numbers the batch STARTING FROM ONE and knows
    # nothing of its own offset. The alignment is done with DUMMY empty
    # programs placed in front: an empty program creates neither an
    # element nor a no-body reason, so the address shift comes for free
    # and without touching a foreign module.
    geometry = CB.bundle_elements([[]] * (first_position - 1) + list(raw),
                                  snapshot=snapshot)
    hulls = S.build_from_elements(geometry.elements,
                                  origin={"doc_key": doc_key or "живая сессия"},
                                  profiles=geometry.profiles)
    body = {rec.source_id: rec for rec in hulls.records}
    # The PER-ELEMENT refusal comes from here — it is the only reason we
    # have by name. The class (`BLIND_CLASS_RU`) is counted as a batch
    # and therefore travels as a distribution, not on the element.
    refused = {ref.source_id: ref.reason for ref in hulls.refusals}

    # ── 2. PLAN OUTLINES. The fallback path for bodyless elements and
    # the source of floors.
    building = P.build_program_preview(flat)
    op_by_id = {str(op.get("id")): op for op in flat if op.get("id")}
    display_meshes: dict[str, tuple] = {}
    mesh_refused: dict[str, int] = {}
    mesh_refusal_details: dict[str, dict[str, str]] = {}

    def refuse_mesh(oid: str, error: Exception) -> None:
        if oid in mesh_refusal_details:
            return  # One named refusal per object, including a refused fallback.
        key = type(error).__name__
        mesh_refused[key] = mesh_refused.get(key, 0) + 1
        mesh_refusal_details[oid] = {"code": "invalid_display_mesh", "reason": str(error)}

    for oid, op in op_by_id.items():
        if op.get("op") != "create_directshape":
            continue
        try:
            category = DIRECTSHAPE_CATEGORIES.get(op.get("category"))
            if category is None:
                raise ValueError("unsupported DirectShape display category")
            display_meshes[oid] = (*_display_mesh(op.get("mesh")), category)
        except (ValueError, TypeError, IndexError) as exc:
            refuse_mesh(oid, exc)
    display_hulls = []
    for rec in hulls.records:
        # Clash inventory remains unchanged. An intrinsically unrepresentable
        # authored DS must not poison the display origin through its fallback.
        if (op_by_id.get(rec.source_id, {}).get("op") == "create_directshape"
                and not _display_bounds_fit(*rec.bounds())):
            refuse_mesh(rec.source_id, ValueError("DirectShape hull intrinsic extent cannot fit a float32 frame"))
            continue
        display_hulls.append(rec)
    # ── THE GRAPH LAYER FOR WHAT IS DECLARED. `existence=planned` is
    #    what this whole half exists for: an engineer spends three hours
    #    building a building that doesn't exist in Revit yet, and the
    #    unbuilt must be DISTINGUISHABLE from the built.
    # 🔴 THE HOST INDEX IS PASSED THROUGH, NOT LOST (F-310, 29.08.2026).
    # `bundle_elements` above has ALREADY built `geometry.hosted`, and
    # `facts_for_programs` explicitly accepts it — its docstring calls
    # this index "READY, computed before this." The one production call
    # site was only passing `op_by_id`, and every live frame was
    # publishing `edges_unmeasured=true`, empty relations, and NOT A
    # SINGLE unresolved host — even when that same frame had resolved or
    # rejected them.
    #
    # COVERAGE MEASUREMENT 30.08.2026 (mine, turn 1): a frame built from
    # a raised program for EACH of the corpus's 65 parses —
    # `edges_unmeasured=true` in 65 out of 65. Not an edge case, every
    # frame.
    graph_facts, graph_note = _graph.facts_for_programs(op_by_id,
                                                       geometry.hosted)
    unproven = _honesty.unproven_ops()
    census = _honesty.HonestyCensus()
    axes_cache: dict[str, int] = {}
    axes_tally: dict[int, int] = {}
    height_unknown = 0
    drawn: set[str] = set()

    def axes_for(op_name: str) -> int:
        if op_name not in axes_cache:
            axes_cache[op_name] = _honesty.axes_byte(
                _honesty.axes_for_ops([op_name]))
        return axes_cache[op_name]

    # ── 3. A SHARED ORIGIN across both sources at once, otherwise the
    #      bodies and the outlines drift into different coordinate
    #      origins and the building falls apart.
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for _, _, lo, hi, _ in display_meshes.values():
        xs.extend((lo[0], hi[0]))
        ys.extend((lo[1], hi[1]))
        zs.extend((lo[2], hi[2]))
    for rec in display_hulls:
        lo, hi = rec.bounds()
        xs += [lo[0], hi[0]]
        ys += [lo[1], hi[1]]
        zs += [lo[2], hi[2]]
    for plan in building.plans:
        extents = plan.extents_mm()
        if extents:
            xs += [extents[0], extents[2]]
            ys += [extents[1], extents[3]]
        if plan.level_elevation_mm is not None:
            zs.append(float(plan.level_elevation_mm))
    # A FIXED ORIGIN OUTRANKS A COMPUTED ONE. A delta must land in the
    # same coordinate system as the base; an origin computed from the
    # slice's bounding box would shift it by an amount nobody would
    # notice.
    origin = origin_mm if origin_mm is not None else (
        min(xs) * 0.5 + max(xs) * 0.5 if xs else 0.0,
        min(ys) * 0.5 + max(ys) * 0.5 if ys else 0.0,
        min(zs) if zs else 0.0)
    if (len(origin) != 3 or any(not isinstance(v, (int, float)) or isinstance(v, bool)
                                or not math.isfinite(v) for v in origin)):
        raise ValueError("scene origin must contain three finite numbers")
    far = max((abs(v - o) for vals, o in ((xs, origin[0]), (ys, origin[1]),
                                          (zs, origin[2])) for v in vals),
              default=0.0)
    builder = SceneBuilder(origin_mm=origin)
    # 🔴 THE TAIL IS SIGNED IN THE INDICES OF THE MERGED SCENE (F-008).
    # For a whole scene, the base is zero by construction: `whole=True`
    # resets the showroom's accumulation, and the client will not be
    # merging anything. It is asked BEFORE the build — afterward is too
    # late, the signature is written along the way by `add_element`.
    if not whole and session_key is not None:
        from kir.live import showroom as _sr
        try:
            builder.mesh_vertex_base = _sr.scene_mesh_base(session_key)
        except Exception:  # noqa: BLE001 — the showroom has no right to bring down the frame
            builder.mesh_vertex_base = 0

    def place(element_id: str, category: str, level: Any, op_name: str,
              kind: int, slot: int, fidelity: _honesty.Fidelity,
              why: str) -> None:
        trust = (_honesty.Trust.UNKNOWN if not unproven
                 else (_honesty.Trust.OP_UNPROVEN if op_name in unproven
                       else _honesty.Trust.OP_PROVEN))
        axes = axes_for(op_name) if op_name else _honesty.AXES_UNJUDGEABLE
        axes_tally[axes] = axes_tally.get(axes, 0) + 1
        census.add(_honesty.ElementHonesty(
            element_id=element_id, trust=trust, fidelity=fidelity, why=why))
        node = graph_facts.get(element_id)
        builder.add_element(
            element_id=element_id, category=category, level=level,
            trust=TRUST_CODE[trust.value],
            fidelity=FIDELITY_CODE[fidelity.value],
            kind=kind, slot=slot, label=op_name, axes=axes,
            authority=_graph.AUTHORITY_CODE.get(
                node.authority if node else "unknown", 2),
            existence=_graph.EXISTENCE_CODE.get(
                node.existence if node else "unknown", 2),
            flags=node.flags if node else 0)
        drawn.add(element_id)

    # ── 4. AUTHOR MESH FIRST; CLASH HULLS ARE AN INDEPENDENT FALLBACK.
    mesh_ids: set[str] = set()
    for oid, (verts, tris, lo, hi, category) in display_meshes.items():
        try:
            # The packer maps inf to zero. Reject unrepresentable relative
            # coordinates here, even if both absolute coordinates are finite.
            if not _display_bounds_fit(lo, hi, origin):
                raise ValueError("mesh offsets are not representable as finite float32 coordinates")
            kind, slot = builder.add_mesh(verts, tris)
        except (ValueError, TypeError, IndexError, OverflowError) as exc:
            refuse_mesh(oid, exc)
            continue
        rec = body.get(oid)
        # EXACT means the supplied triangles (subject to the published float32
        # coordinate precision), not an exact BRep or accepted native BIM.
        place(oid, category, rec.level_id if rec else None, "create_directshape",
              kind, slot, _honesty.Fidelity.EXACT, "authored_mesh_not_native_bim")
        mesh_ids.add(oid)

    hull_ids: set[str] = set()
    for rec in display_hulls:
        if rec.source_id in drawn:
            continue
        hull = rec.hull
        op = op_by_id.get(rec.source_id) or {}
        if (op.get("op") == "create_directshape"
                and not _display_bounds_fit(*rec.bounds(), origin)):
            refuse_mesh(rec.source_id, ValueError("DirectShape hull offsets cannot fit the display float32 frame"))
            continue
        # These are conservative clash envelopes, not the authored surface.
        # A refused mesh may still have a valid envelope; its refusal remains
        # named in metadata even when that fallback is displayed.
        if isinstance(hull, G.Capsule):
            kind, slot = builder.add_capsule(hull.path, hull.radius)
        elif isinstance(hull, G.PrismSet):
            kind, slot = builder.add_prism(hull.pieces, hull.z0, hull.z1)
        elif isinstance(hull, G.Prism):
            kind, slot = builder.add_prism((hull.footprint,), hull.z0, hull.z1)
        else:
            lo, hi = rec.bounds()
            kind, slot = builder.add_box(lo, hi)
        place(rec.source_id, rec.category, rec.level_id,
              str(op.get("op") or ""), kind, slot,
              _honesty.fidelity_of(rec.grade, rec.hull_source,
                                  HU.hull_degeneracy(hull)),
              str(op.get("op") or ""))
        hull_ids.add(rec.source_id)

    # ── 5. BODYLESS ELEMENTS — with the plan outline and as a GHOST, not
    # by being skipped.
    for plan in building.plans:
        base = float(plan.level_elevation_mm or 0.0)
        for element in plan.elements:
            if element.element_id in drawn:
                continue
            op = op_by_id.get(element.element_id)
            z0, z1, known = _z_of(op, base)
            if not known:
                height_unknown += 1
            placed = _extrude(builder, element, z0, z1)
            if placed is None:
                continue
            kind, slot = placed
            place(element.element_id, element.category, plan.level_name,
                  str((op or {}).get("op") or ""), kind, slot,
                  _honesty.Fidelity.NO_BODY,
                  refused.get(element.element_id)
                  or ("height_unknown" if not known else "тела нет"))
    # ── RECONCILING PLAN AND VOLUME. Both censuses are already built
    #    above, so what's left for the reconciliation is the breakdown:
    #    measured at 5.5 ms for 6 000 elements against the 213 ms of
    #    bundle and 84 ms of preview, which get paid anyway. On the delta
    #    path the frame builds only new programs, so the breakdown is
    #    O(new). The denominator is ALL written operations: otherwise the
    #    fourth bucket is empty by construction.
    context_ids = {str(op.get("id")) for ops in _qualify(
        raw[:context_programs], first_position=first_position)
        for op in ops if op.get("id")} if context_programs else set()
    recon = {"available": False, "reason": "сессия не названа: сверять нечего"}
    if session_key is not None:
        try:
            recon = _reconcile.live_frame(
                session_key,
                # CONTEXT DATUMS ARE EXCLUDED FROM THE DENOMINATOR. They
                # travel with EVERY delta (without `create_level` a slice
                # has no elevation), and each time they get the address
                # of their own position — that is, a NEW one. Found by my
                # own measurement: `neither` was growing by one with
                # every delta, and over a three-hour session would have
                # racked up hundreds of ghosts. This is context, not work
                # written in this frame.
                ops_by_id={oid: str(op.get("op") or "")
                           for oid, op in op_by_id.items()
                           if oid not in context_ids},
                drawn={str(e.element_id) for plan in building.plans
                       for e in plan.elements},
                # DATUMS ARE COUNTED AS DRAWN: `preview` keeps them in a
                # separate list, and not looking there would mean
                # declaring the axis invisible exactly where the plan
                # shows it.
                datums={str(e.element_id) for plan in building.plans
                        for e in plan.datums},
                bodied=hull_ids | mesh_ids,
                refused={**{ref.source_id: ref.reason for ref in hulls.refusals},
                         **{oid: detail["reason"] for oid, detail in mesh_refusal_details.items()}},
                no_body_ops=dict(geometry.no_body),
                whole=whole)
        except Exception as exc:  # noqa: BLE001 — the reconciliation does not bring down the frame
            recon = {"available": False,
                     "reason": f"сверка не собралась: {type(exc).__name__}"}
    return _finish(builder, census, building, geometry, hulls, axes_tally,
                   height_unknown, doc_key, snapshot, flat, started, journal,
                   graph_note, far, session_key, whole, recon,
                   mesh_refused=mesh_refused, upto_seq=upto_seq,
                   mesh_refusal_details=mesh_refusal_details,
                   display_bodies=len(hull_ids | mesh_ids),
                   mesh_without_hull=len(mesh_ids - set(body)),
                   origin_mm=builder.origin_mm)


def _finish(builder, census, building, geometry, hulls, axes_tally,
            height_unknown, doc_key, snapshot, flat, started, journal,
            graph_note, far, session_key=None, whole=True, recon=None,
            mesh_refused=None, upto_seq=0,
            origin_mm=None, mesh_refusal_details=None, display_bodies=0,
            mesh_without_hull=0) -> tuple[bytes, dict[str, Any]]:
    """The scene header. Everything that is NOT in the picture is named
    here."""
    from kir import clash_bundle as CB
    from kir import preview as P
    from kir.live import showroom as _showroom

    # THE SIGNATURE OF WHAT'S SHOWN IS ACCUMULATED BY THE SHOWROOM, NOT
    # RECOMPUTED FROM SCRATCH. A whole scene resets the accumulation, a
    # tail appends to it; the server adds EXACTLY the records of the new
    # elements and stays O(new) per frame. Recomputing over the whole
    # scene would give the frame the cost of the whole, that is, it
    # would fix the transport and break it again through its own button.
    shown = ""
    if session_key is not None:
        try:
            # 🔴 THE SIGNATURE CARRIES THE JOURNAL REVISION AND THE SCENE
            # ORIGIN WITH IT (F-284/F-196). Without the revision it only
            # vouched for the PICTURE, while what got executed was the
            # JOURNAL — and everything appended between the render and
            # the button press was going to Revit on someone else's
            # consent.
            shown = _showroom.scene_shown(
                session_key, builder.shown_records(),
                elements=builder.count, whole=whole,
                mesh_vertices=builder._mesh_vert,
                upto_seq=upto_seq, origin_mm=origin_mm)
        except Exception:  # noqa: BLE001 — the showroom has no right to bring down the frame
            shown = ""

    # THE REASON CLASS IS COMPUTED BY THE TABLE'S OWNER. A home-grown
    # copy of the six lines (`never_a_body` from `no_body`, the rest
    # from `no_geometry`) would drift from the original silently — the
    # same argument by which `unwitnessed_axes` is not copied but
    # called.
    by_class = CB._blind_by_class(geometry)
    bodies = len(hulls.records)
    declared = bodies + len(hulls.refusals)
    blind_class_ru = dict(CB.BLIND_CLASS_RU)
    if geometry.no_body.get("create_directshape"):
        # The owner's ordinary datum/edit label is not a valid explanation
        # for a DS category excluded by KIND_TABLE. Preserve the counts and
        # scope, but do not call a displayed mass physically nonexistent.
        blind_class_ru["never_a_body"] = (
            "операция/категория не входит в построение clash-оболочек; "
            "это не утверждение об отсутствии отображаемой формы")
    meta: dict[str, Any] = {
        "run": doc_key or "(живая сессия)",
        "source": "program",
        "stage": "planned",
        "assertion": "self_reported",
        "assertion_ru": ("ЗАЯВЛЕНО программами сессии — модель не читалась, "
                         "в Revit этого ещё нет"),
        "trust_codes": TRUST_CODE,
        "fidelity_codes": FIDELITY_CODE,
        "honesty": census.to_dict(),
        "honesty_source": {"available": bool(_honesty.unproven_ops()),
                           "unproven_table": bool(_honesty.unproven_ops())},
        "census": building.census.to_dict(),
        "levels_total": building.levels_total,
        "levels_rendered": len(building.plans),
        "programs": len({str(op.get("id", "")).split("/")[0]
                         for op in flat if op.get("id")}),
        "ops": len(flat),
        # ── BODY COVERAGE. The screen's first number, not a footnote.
        "bodies": bodies,
        "bodies_scope": "clash_hulls",
        "display_bodies": display_bodies,
        "display_meshes_without_clash_hull": mesh_without_hull,
        "display_fidelity_scope": "authored_mesh_not_native_bim",
        "bodies_declared": declared,
        "bodies_pct": (round(100.0 * bodies / declared, 2) if declared else 0.0),
        "bodies_ru": (f"{bodies} clash-оболочек из {declared} кандидатов; "
                      f"отображаемых объёмных представлений: {display_bodies}"),
        "blind_by_class": by_class,
        "blind_class_ru": blind_class_ru,
        "blind_scope": "clash_hulls",
        # A HOLE IN SOMEONE ELSE'S TABLE IS VISIBLE ON SCREEN, not just
        # in a test: a reason with no class reads as the absence of a
        # problem.
        "blind_unclassified": by_class.get("unclassified", 0),
        "blind_scope_ru": ("причины отсутствия clash-оболочек считаются ПАЧКОЙ; "
                           "не описывают видимость authored mesh и не являются результатом clash detection"),
        "sections_present": bool(snapshot),
        # THE SAME TRI-STATE AS IN THE NOTE ABOVE, AND THIS IS THE
        # SECOND PLACE WHERE IT IS DECLARED. The first fix on 14.08 split
        # it into three states only in the note — while the scene
        # header, which is what the panel actually reads, stayed binary,
        # and the "fix" changed nothing on screen. Our class of defect: a
        # value is declared in two places, and nothing reconciles them.
        # They are now held together by one expression below; a
        # divergence will become visible immediately.
        "sections_state": ("present" if snapshot
                           else "empty" if snapshot is not None
                           else "absent"),
        "sections_ru": ("снимок типов открытой модели ЕСТЬ"
                        if snapshot else
                        "снимок ЗАПРОШЕН, сечений в документе НЕТ; "
                        "типозависимые оболочки могут отсутствовать, authored mesh от снимка не зависит"
                        if snapshot is not None else
                        "снимок НЕ ЗАПРАШИВАЛСЯ: заземление до сессии не "
                        "дошло; типозависимые оболочки могут отсутствовать, authored mesh от снимка не зависит"),
        "height_unknown": height_unknown,
        "height_unknown_ru": (
            f"{height_unknown} элементов без высоты в программе: им поставлена "
            f"заглушка {FALLBACK_HEIGHT_MM:.0f} мм, это НЕ их высота"),
        "axes_order": list(_honesty.AXES_ORDER),
        "axes_unjudgeable": _honesty.AXES_UNJUDGEABLE,
        "axes_tally": {str(k): v for k, v in sorted(axes_tally.items())},
        # 🔴 "ZERO MESHES" AND "MESHES WEREN'T ASKED ABOUT" ARE DIFFERENT
        # FACTS, and the first without the second is indistinguishable
        # from "the shape channel doesn't work." The number is printed
        # ALWAYS, even when zero: until 21.08.2026 it was zero BY
        # CONSTRUCTION, and that is exactly why nobody noticed that the
        # viewer was drawing clash shells.
        "mesh_shown": builder.mesh_count,
        "mesh_refused": dict(sorted((mesh_refused or {}).items())),
        "mesh_refusal_details": mesh_refusal_details or {},
        "mesh_note_ru": (
            f"сеток показано СВОЕЙ формой: {builder.mesh_count}"
            + (f"; ОТКАЗАНО в чтении: "
               + ", ".join(f"{k}×{v}"
                           for k, v in sorted((mesh_refused or {}).items()))
               if mesh_refused else "")
            + ("; остальные тела — ОБОЛОЧКИ клеша (коробка, капсула, призма): "
               "они СОДЕРЖАТ тело, но формой ему не равны. Видимость сетки не доказывает clash coverage или native BIM"
               if builder.mesh_count else
               "; все тела сцены — ОБОЛОЧКИ клеша. Своей формой сегодня "
               "приходит только create_directshape")),
        "axes_ru": ("оси, по которым операция НЕ ОБЪЯВИЛА обязательств: "
                    "зелёный по ним не значит проверено"),
        "declaration_slack": len(geometry.declaration_slack),
        "id_collisions": geometry.collisions,
        "blind_spots": LIVE_BLIND_SPOTS + P.BLIND_SPOTS,
        # THE JOURNAL NOTE IS PLACED BEFORE `finish`, NOT AFTER. The
        # header sits INSIDE the scene bytes; anything appended to
        # `meta` after packing is seen only by the server, never by the
        # client. Measurement on 11.08: program eviction and a missing
        # snapshot reached the server and did NOT reach the screen —
        # that is, a warning existed and stayed silent.
        "journal": dict(journal) if journal else None,
        # THE TAIL IS ALSO NAMED AT THE ROOT. A consumer reading only the
        # top level of the header should not have to guess that the
        # building is incomplete.
        "partial": bool(journal.get("partial")) if journal else False,
        "delta": bool(journal.get("delta")) if journal else False,
        "base_digest": (journal or {}).get("base_digest", ""),
        # THE SIGNATURE OF WHAT THE PERSON SEES. An empty string means
        # "the showroom was not consulted" (the scene was assembled
        # outside a session), and that is NOT "nothing to sign": the
        # button on such a scene must refuse, not agree.
        "shown_digest": shown,
        "shown_ru": ("подпись СКЛЕЙКИ, накопленной витриной; панель обязана "
                     "посчитать свою по нарисованному и прислать её кнопке"),
        # THE OFFSET'S PRECISION IS CHECKED, NOT PROMISED. Beyond this
        # radius float32 stops representing a millimeter exactly, and
        # merging the delta with the base would drift at the
        # sub-millimeter level — that is, invisibly.
        "origin_overflow": bool(far > FLOAT32_EXACT_MM),
        "origin_far_mm": round(float(far), 1),
        "partial_ru": (journal or {}).get("partial_ru", ""),
        "graph": graph_note,
        # THE RECONCILIATION TRAVELS IN THE FRAME, because here it costs
        # almost nothing: both censuses are already built by this same
        # call. For a parse it cost their sum and therefore lives as a
        # separate endpoint — different price, different place.
        "reconcile": recon or {"available": False,
                               "reason": "сверка не запрашивалась"},
        "authority_codes": _graph.AUTHORITY_CODE,
        "existence_codes": _graph.EXISTENCE_CODE,
        "flag_bits": {"refuted": _graph.FLAG_REFUTED,
                      "unresolved": _graph.FLAG_UNRESOLVED},
        "flags_ru": {"refuted": "у элемента ОПРОВЕРГНУТО отношение (сам "
                                "элемент цел)",
                     "unresolved": "у элемента есть отношение, чья ЦЕЛЬ вне "
                                   "извлечения"},
        "timing_ms": {"total": round((time.perf_counter() - started) * 1000, 1)},
    }
    blob = builder.finish(meta)
    meta["bytes"] = len(blob)
    return blob, meta


def _extrude(builder: SceneBuilder, element: Any, z0: float, z1: float):
    """`DrawnElement` -> a scene primitive. Dispatch by SHAPE, not by
    category.

    `preview`'s shapes are a closed set (`Poly | Path | Dot |
    TextMark`), so the dispatch is complete by construction, rather than
    by enumerating categories, which would drift from the registry on
    the very first new operation.
    """
    from kir import preview as P

    for shape in element.shapes:
        if isinstance(shape, P.Poly) and shape.loops and len(shape.loops[0]) >= 3:
            # Outline holes (`loops[1:]`) are NOT subtracted: there are
            # no boolean operations in `clash.geom`, and setting them up
            # here would mean setting up a second set. The outer contour
            # is a superset — the same law of conservatism as for
            # shells.
            return builder.add_prism((tuple(shape.loops[0]),), z0, z1)
        if isinstance(shape, P.Path) and len(shape.pts) >= 2:
            # A polyline with no thickness -> a thin-radius capsule: the
            # axis has no cross-section, and inventing a width for it is
            # not allowed.
            return builder.add_capsule(
                [(x, y, z0) for x, y in shape.pts], max(1.0, (z1 - z0) * 0.02))
        if isinstance(shape, P.Dot):
            x, y = shape.xy
            r = max(shape.r_mm, 1.0)
            return builder.add_box((x - r, y - r, z0), (x + r, y + r, z1))
    return None


def scene_from_session(device_id: str | None, doc_key: str = "",
                       since: int = 0, base: str = ""
                       ) -> tuple[bytes, dict[str, Any]]:
    """A live session: the whole thing at `since=0`, a DELTA at
    `since>0`.

    The snapshot is taken FROM THE JOURNAL, not from a parameter: it is
    put there by `plan_stream.remember_sections`, and a second source
    for the snapshot would mean the picture is built from one document
    while the transfer to Revit runs off another.

    ────────────────────────────────────────────────────────────────────
    THE DELTA CONTRACT, AND IT REFUSES RATHER THAN GUESSES
    ────────────────────────────────────────────────────────────────────
    The client holds the cursor `since` and the base signature `base`. A
    delta is handed out ONLY when the signature matches the current one:
    `base_digest` covers everything capable of changing elements already
    sent (datums, the type snapshot, eviction). If it diverges —
    `StaleBase`, and the client must re-request the whole thing. Gluing a
    tail onto someone else's base means showing a building that never
    existed; a blank screen is at least visible.

    `since>0` with no signature is also a refusal, not a "probably
    fine": silently accepting an unknown base is the same kind of merge,
    just with laziness instead of error.
    """
    from kir.live import journal as _journal

    session = _journal.get(_journal.key_for(device_id, doc_key))
    snapshot = getattr(session, "sections", None) if session else None
    datums = list(getattr(session, "datums", ()) or ()) if session else []
    evicted = getattr(session, "programs_evicted", 0) if session else 0
    digest = base_digest(datums, snapshot, evicted)
    origin = live_origin(datums)

    if since > 0 and base != digest:
        raise StaleBase(
            "база клиента не та, к которой применима дельта: "
            f"ожидалась {digest}, пришла {base or '(пусто)'}. "
            "Изменились датумы, снимок типов или журнал вытеснил программы. "
            "Нужен полный запрос since=0 — приклеивать хвост к чужой базе "
            "нельзя")

    programs, note = programs_since(device_id, doc_key, since)
    note["base_digest"] = digest
    note["delta"] = since > 0
    # DATUMS TRAVEL AS CONTEXT, NOT AS ELEMENTS. Without `create_level` a
    # slice has no floor elevation, and new elements would land at zero
    # — that is, the delta would draw only the first floor correctly.
    # The journal keeps datums separately exactly for this
    # (`_DATUM_OPS`), and `plan_stream._slice_for` takes them the same
    # way.
    context = [{"ops": datums}] if (since > 0 and datums) else []
    blob, meta = scene_from_programs(
        context + list(programs), doc_key=doc_key, snapshot=snapshot,
        journal=note, origin_mm=origin,
        session_key=_journal.key_for(device_id, doc_key), whole=(since == 0),
        # THE REVISION IS TAKEN HERE, NOT IN THE SHOWROOM: `next_seq` is
        # exactly "one more than the last existing record," so the frame
        # shows everything with `seq < next_seq` and nothing beyond. A
        # record appended after this line will get `seq >= upto`, and it
        # will not make it into the batch.
        upto_seq=(getattr(session, "next_seq", 0) if session else 0),
        context_programs=len(context),
        # The context program occupies position zero, so the real ones
        # start from their own place in the session — addresses match
        # the base.
        first_position=(since - len(context) + 1) if since > 0 else 1)
    meta["context_ops"] = len(datums) if context else 0
    return blob, meta
