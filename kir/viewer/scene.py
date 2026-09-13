"""THE DECOMPILE'S BUILDING SCENE — `clash` hulls plus an honesty layer,
into bytes.

WHAT THIS MODULE DOES NOT DO, AND THIS IS THE MAIN POINT. It does not build
geometry. All the geometry is already built by `clash/hulls.py` and
`clash/snapshot.py`, and this module only READS it (not a line is written in
`clash` here — a different agent works there). A measurement it was worth
checking before building anything: `build_from_decompile` on `демо-v3` — 84
120 hulls in 6.5–7.3 s; on `sob62_fas_r23_v19` — 4 218 in 0.39 s. The viewer
does not need a geometry extractor of its own, and writing one would be a
seventh graph in exactly the sense the roadmap speaks of them.

WHY THE SCENE IS TAKEN FROM HULLS, NOT FROM BODIES. There are no bodies.
`hulls` builds CONSERVATIVE SUPERSETS, and `grade="exact"` is unreachable by
inference (`hulls.UNREACHABLE_GRADE_REASONS`). A viewer that draws a hull and
calls it a body would repeat the "green witness of an unread axis" defect in
the graphics. That is why `Fidelity` travels with every element, and the
rendering form is chosen by it, not by category.

THE CENSUS TRAVELS WITH THE SCENE. `snapshot.Census` already holds the law
`eligible = hulled + unsupported + missing_geometry`, and it converges for
every decompile. The scene publishes it in full, because "the building looks
whole" and "the building is whole" are different claims: on
`sob62_fas_r23_v19`, of 5 001 eligible elements, 4 218 got a hull, and 783
(15.66 %) got nothing at all and are NOT in the scene. The user must see this
number next to the picture, or the picture lies by omission.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import time
from typing import Any

from kir.install_paths import install_data_path, install_root_refusal
from kir.viewer import graph as _graph
from kir.viewer import honesty as _honesty
from kir.viewer.codec import SceneBuilder
from kir import env  # noqa: E402

__all__ = ("TRUST_CODE", "FIDELITY_CODE", "scene_from_decompile",
           "scene_from_directory", "run_root", "list_runs")

#: Numeric status codes in the buffer. Order = order of severity, and it is
#: also the legend order in the viewer. Published in the scene header: the
#: client must not keep a second copy of this table.
TRUST_CODE: dict[str, int] = {
    _honesty.Trust.OP_PROVEN.value: 0,
    _honesty.Trust.OP_UNPROVEN.value: 1,
    _honesty.Trust.ATOM.value: 2,
    _honesty.Trust.UNKNOWN.value: 3,
}

FIDELITY_CODE: dict[str, int] = {
    _honesty.Fidelity.EXACT.value: 0,
    _honesty.Fidelity.SHAPED.value: 1,
    _honesty.Fidelity.BOX_ONLY.value: 2,
    _honesty.Fidelity.DEGENERATE.value: 3,
    _honesty.Fidelity.NO_BODY.value: 4,
}


def _graph_enabled() -> bool:
    """A flag of a foreign module, asked for without importing it on the hot
    path."""
    try:
        from kir.decompile.building_graph import building_graph_enabled
        return building_graph_enabled()
    except Exception:  # noqa: BLE001 — the module is unavailable: the layer simply is not there
        return False


#: One central tap onto the decompile corpus instead of private symlinks.
#: SET UP FROM THE 11.08.2026 MEASUREMENT: the corpus (4.1 GB, 76 runs, 67
#: with `L0.jsonl`) is machine-local and sits ONLY on prod, while the path
#: was derived from `__file__` — meaning in any worktree it pointed into
#: emptiness, and a whole family of tests either failed with
#: `FileNotFoundError` or silently got an empty list. The first person to
#: work around this made a private symlink into their own tree: greenness
#: that no one else can reproduce. Five such symlinks are one and the same
#: defect, multiplied fivefold.
CORPUS_ENV = "KIR_DECOMPILE_CORPUS"


def run_root() -> pathlib.Path:
    """The decompile corpus. `backend` is doubled NOT BY MISTAKE — that is
    how it sits on prod.

    Overridden by ``KUKAI_DECOMPILE_CORPUS``: the corpus is machine-local,
    and otherwise unreachable from a foreign worktree.

    🔴 THE ANCHOR USED TO BE `here.parent.parent.parent` WITH THE COMMENT
    "kir/viewer/scene.py -> kukai -> backend": the comment described a
    layout that no longer exists, and three steps up after the split gave
    the repository root instead of the install root. Counting STEPS UPWARD
    is correct for exactly one layout — on this very shape the sandbox
    (`f518b05`) and `install_paths` burned, where it cost six telemetry
    feeds going silent. The install root knows one authority.
    """
    override = env.get(CORPUS_ENV, "").strip()
    if override:
        return pathlib.Path(override)
    anchored = install_data_path("decompile")
    if anchored is not None:
        return anchored
    # The install is not named. What is returned is a path KNOWN NOT TO
    # EXIST, not a plausible-looking one: `corpus_unreachable_reason()` below
    # must say WHY, and it asks the same authority for the reason.
    return pathlib.Path("<установка не названа>") / "backend" / "data" / "decompile"


def corpus_unreachable_reason() -> str | None:
    """``None`` if the corpus is in place; otherwise the REASON in words.

    A law bought twice today: ANY ZERO TAKEN FROM THE CORPUS MUST TRAVEL
    WITH PROOF THAT THE CORPUS WAS REACHABLE. "I looked and found nothing"
    and "this does not exist" are one phrase and different facts; an empty
    list from a missing directory is indistinguishable from an honestly
    empty corpus.
    """
    root = run_root()
    if root.is_dir():
        return None
    # 🔴 TWO REASONS, AND THEY CANNOT BE MERGED INTO ONE. "The directory does
    # not exist" and "the install is not named" call for DIFFERENT next
    # moves: in the first case one sets the corpus, in the second, the
    # install. A refusal that names one reason instead of two sends the
    # author to fix the wrong thing (shape 51: the refusal named a third
    # number).
    named = install_root_refusal()
    if named is not None and not env.get(CORPUS_ENV, "").strip():
        return (f"корпус разборов недостижим, потому что {named} "
                f"Либо задай {CORPUS_ENV} каталогом разборов напрямую.")
    # 🔴 AN ABSOLUTE PATH OF ONE SPECIFIC INSTALL USED TO STAND HERE ("on
    # prod it's /opt/.../data/decompile"), removed 27.08.2026. It is not a
    # route — the code goes through `run_root()` — but the text TRAVELS TO
    # THE READER, and the package is published as a separate repository
    # under Apache-2.0. For someone else, such an example does not help and
    # misleads: they do not have this directory, and they will go look for
    # the error in their own layout. The refusal must name THE VARIABLE and
    # the kind of value, not someone else's machine.
    return (f"корпус разборов недостижим: {root} не существует — "
            f"задай {CORPUS_ENV} каталогом, где лежат разборы этой установки "
            "(по каталогу на здание, внутри каждого L0.jsonl)")


#: The building's name from the passport, keyed by (path, mtime, size). The
#: passport is rewritten in full, so the pair (mtime, size) is a sufficient
#: sign of change, while the path is the same only for one and the same
#: decompile.
_DOC_NAME_CACHE: dict[tuple[str, int, int], str] = {}

_DOC_NAME_RE = re.compile(rb'"doc_name"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _doc_name_of(passport: pathlib.Path) -> str:
    """The building's name from the passport WITHOUT parsing the whole
    passport.

    🔴 MEASURED 14.08.2026, found with a stopwatch in the KIR window: the
    corpus list responded in **16.8 s** — 69 decompiles, of which 52 have a
    passport, and the old line did `json.loads(passport.read_text())` on each
    one. Passports run as large as **196 MB** (`k2_ar_rd_v7`), **918 MB**
    total, and all of it was parsed into objects for the sake of ONE string
    field. The panel was silent for seventeen seconds, and the building named
    in the address was waiting on this list.

    We search for the key byte by byte and stop at the first match. A full
    scan, not "the first N KB": on a 10-megabyte passport `doc_name` sits in
    the first 400 KB, on a 196-megabyte one it does not, and a head-only
    slice would answer "no name" where there is one. An empty string here
    means "the passport has no such field", and that is the only thing it
    means.
    """
    # 🔴 THE PASSPORT GETS COMPRESSED (21.08.2026, `SNAPSHOT_FILES`). The
    # cache key is taken from WHICHEVER file is actually on disk (raw or
    # `.gz`), otherwise on a cooled-down decompile `stat` throws and the
    # corpus list loses the building's name.
    from kir.decompile.snapshot_io import gz_path, open_snapshot
    on_disk = passport if passport.is_file() else gz_path(passport)
    try:
        st = on_disk.stat()
    except OSError:
        return ""
    key = (str(passport), st.st_mtime_ns, st.st_size)
    hit = _DOC_NAME_CACHE.get(key)
    if hit is not None:
        return hit
    found = ""
    try:
        # `open_snapshot` hands back the UNPACKED data, so the byte-by-byte
        # key search works the same on a raw and on a compressed passport.
        with open_snapshot(passport, "rb") as fh:
            tail = b""
            while True:
                chunk = fh.read(4 << 20)
                if not chunk:
                    break
                buf = tail + chunk
                m = _DOC_NAME_RE.search(buf)
                if m:
                    found = json.loads(b'"' + m.group(1) + b'"')
                    break
                # A tail for the seam: the key may land right on the read
                # boundary.
                tail = buf[-256:]
    except Exception:  # noqa: BLE001 — the passport is not mandatory
        found = ""
    if len(_DOC_NAME_CACHE) > 512:
        _DOC_NAME_CACHE.clear()
    _DOC_NAME_CACHE[key] = found
    return found


def list_runs() -> list[dict[str, Any]]:
    """Decompiles that have an L0 stream. The directory name IS NOT the
    building's name: `snowdon_plumb_v5` contains an architectural model
    (measured 10.08: 1 425 curtain-wall mullions and 1 136 walls, not a
    single pipe), so `doc_name` from the passport is published alongside the
    directory name whenever it exists."""
    root = run_root()
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        l0 = entry / "L0.jsonl"
        from kir.decompile.snapshot_io import snapshot_file_exists
        if not entry.is_dir() or not snapshot_file_exists(l0):
            continue
        # WHEN IT WAS DECOMPILED IS THE ONLY THING THAT DISTINGUISHES 69
        # DECOMPILES FOR SOMEONE WHO IS CHOOSING (14.08.2026). The owner: "I
        # can't properly add a building" — the list has 71 lines shaped like
        # `k2_ar_rd_v13`, and from them you cannot tell what it is or which
        # one is fresh. The time is taken from the L0 stream, not from the
        # directory: the directory is touched by any service record placed
        # next to it, the stream only by the decompile itself. The stream's
        # bytes travel as EXPLICITLY named bytes, not as an "element count"
        # in disguise: there is no element count here, and slipping in a
        # size instead of one would be lying about the unit.
        try:
            # See the argument in `api/viewer.py`: on a compressed decompile
            # a bare `stat` dropped the key to (0.0, 0), and the cache
            # stopped telling re-decompiles apart.
            from kir.decompile.snapshot_io import (
                gz_path, snapshot_raw_size)
            st = (l0 if l0.is_file() else gz_path(l0)).stat()  # raw is intentional: the key goes by whatever exists
            mtime, size = st.st_mtime, snapshot_raw_size(l0)
        except OSError:
            mtime, size = 0.0, 0
        out.append({"run": entry.name,
                    "doc_name": _doc_name_of(entry / "passport.json"),
                    "l0_mtime": round(mtime, 3),
                    "l0_bytes": size,
                    "has_tree": snapshot_file_exists(entry / "tree.json")})
    return out


def scene_from_decompile(run: str) -> tuple[bytes, dict[str, Any]]:
    """A decompile FROM THE CORPUS -> scene bytes + reference. The address is
    the run's name.

    Exactly the same as before: the name resolves to a directory under
    `run_root()`. The body moved into `scene_from_directory` without a single
    change in behavior — see the argument there.
    """
    root = run_root() / run
    if not root.exists():
        raise FileNotFoundError(f"разбора {run!r} нет в {run_root()}")
    return scene_from_directory(root, run=run)


def scene_from_directory(root, *, run: str | None = None
                         ) -> tuple[bytes, dict[str, Any]]:
    """A decompile directory -> scene bytes + reference. The address is a
    PATH, not a name.

    🔴 WHY A SECOND DOOR, IF THE SCENE IS THE SAME (08.09.2026). It is the
    same: below is the former `scene_from_decompile` body, letter for
    letter, and the only thing that changed is WHAT the decompile is
    addressed by. The old entry point only knew a run's name inside the
    corpus (`run_root()/<name>`), so a decompile sitting ANYWHERE ELSE was
    unreachable through this tract — and the slot of an existing building in
    the application (`kir.app.capture_slot`) lives exactly that way: by a
    path the human named, and after saving, by a new path. That day's
    measurement: the application was instead calling the LIVE tract
    (`live_scene.scene_from_programs`, "what is declared but not built") and
    getting 0 bodies out of 51 candidates on `bench_A`, because
    `same_document` ops address the types and levels of the live document.
    Through this door, the same `bench_A` gives 51 hulls from real L0
    bounding boxes — meaning what was missing was not geometry, but an
    ADDRESS.

    The lazy imports of `clash` are deliberate: the viewer must come up even
    while `clash` is being edited (a different agent is working there right
    now), rather than fail on importing the whole module.
    """
    from kir.clash import geom as G
    from kir.clash import hulls as H
    from kir.clash import snapshot as S

    root = pathlib.Path(root)
    if not root.exists():
        raise FileNotFoundError(f"каталога разбора нет: {root}")
    run = root.name if run is None else run

    t0 = time.perf_counter()
    snap = S.build_from_decompile(root)
    t_hulls = time.perf_counter() - t0

    t1 = time.perf_counter()
    l1, l1_note = _honesty.read_l1_honesty(root)
    t_l1 = time.perf_counter() - t1

    # ── THE GRAPH LAYER. Built from the SAME L0 as the hulls, and from the
    #    same L1 atoms: `generator_child` is the only witness of
    #    derivedness that exists in the data today, and it is served
    #    EXPLICITLY. It respects the foreign module's flag; a flag turned
    #    off gives `available: false` with a reason, not silence.
    t3 = time.perf_counter()
    graph_facts: dict[str, _graph.ElementGraph] = {}
    graph_note = _graph.unavailable(
        "KUKAI_IR_BUILDING_GRAPH не задан: граф здания не строился. Его "
        "владелец держит модуль за флагом, пока тот не сверен с живым Revit, "
        "и показывать непроверенное как правду вьюер не вправе")
    # THE FLAG IS ASKED BEFORE READING, NOT AFTER. The graph requires A
    # SECOND pass over L0 (`build_from_decompile` does not hand out lines
    # internally), and this is the most expensive part of the layer:
    # measured 11.08 — 0.25 s on the facade and ~3.2 s on demo-v3. Paying it
    # while the flag is off would mean charging for goods that are known in
    # advance not to be delivered.
    if _graph_enabled():
        kids = [sid for sid, (trust, why) in l1.items()
                if trust is _honesty.Trust.ATOM and why == "generator_child"]
        try:
            elements, _profiles, _curves, l0_origin = S.read_decompile(root)
            graph_facts, graph_note = _graph.facts_for_decompile(
                l0_origin, elements, generator_child_ids=kids,
                l1_source_ids=list(l1))
        except Exception as exc:  # noqa: BLE001 — the graph layer does not bring down the picture
            graph_facts, graph_note = {}, _graph.unavailable(
                f"L0 не перечитался для графа: {type(exc).__name__}")
    t_graph = time.perf_counter() - t3

    # A COMMON ORIGIN is not decoration: float32 is exact on integers up to
    # 16.7 million mm, and a site in geodetic coordinates eats up that
    # margin with the distance to the origin, not with the building's size
    # (see the header of `codec`).
    t2 = time.perf_counter()
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for rec in snap.records:
        a, b = rec.bounds()
        for i in range(3):
            lo[i] = min(lo[i], a[i])
            hi[i] = max(hi[i], b[i])
    if not snap.records:
        lo, hi = [0.0] * 3, [0.0] * 3
    origin = ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, lo[2])

    builder = SceneBuilder(origin_mm=origin)
    census = _honesty.HonestyCensus()
    axes_tally: dict[int, int] = {}
    #: A memo keyed by THE OP'S NAME. The axes depend only on the name, so
    #: the cache is not a just-in-case optimization but a consequence of the
    #: rule's shape: on demo-v3 that is 84 120 elements across 30 distinct
    #: names. The dict is LOCAL: editing a foreign module for speed would
    #: mean changing behavior for everyone.
    axes_cache: dict[str, int] = {}

    def axes_for(op_name: str, judgeable: bool) -> int:
        if not judgeable:
            return _honesty.AXES_UNJUDGEABLE
        if op_name not in axes_cache:
            axes_cache[op_name] = _honesty.axes_byte(
                _honesty.axes_for_ops([op_name]))
        return axes_cache[op_name]

    for rec in snap.records:
        hull = rec.hull
        if isinstance(hull, G.Capsule):
            kind, slot = builder.add_capsule(hull.path, hull.radius)
        elif isinstance(hull, G.PrismSet):
            kind, slot = builder.add_prism(hull.pieces, hull.z0, hull.z1)
        elif isinstance(hull, G.Prism):
            kind, slot = builder.add_prism((hull.footprint,), hull.z0, hull.z1)
        else:
            a, b = rec.bounds()
            kind, slot = builder.add_box(a, b)

        trust, why = l1.get(rec.source_id,
                            (_honesty.Trust.UNKNOWN, ""))
        fidelity = _honesty.fidelity_of(
            rec.grade, rec.hull_source, H.hull_degeneracy(hull))
        item = _honesty.ElementHonesty(
            element_id=rec.source_id, trust=trust, fidelity=fidelity, why=why,
            benign=(trust is _honesty.Trust.ATOM
                    and why in _honesty.BENIGN_ATOM_REASONS))
        census.add(item)
        # AXES FOR A DECOMPILED BUILDING ARE READ DIFFERENTLY FROM A LIVE
        # ONE, and this is not pedantry. A decompile's element was NOT BUILT
        # by this op — it was RAISED by it. So the claim here is exactly
        # this: "rebuilding this element with op X would leave these axes
        # without a witness", not "this element's axes were not checked".
        # The wording travels to the screen as the `axes_ru` field, so the
        # distinction is not lost between the server and the picture.
        axes = axes_for(why, trust in (_honesty.Trust.OP_PROVEN,
                                       _honesty.Trust.OP_UNPROVEN))
        axes_tally[axes] = axes_tally.get(axes, 0) + 1
        # A hull with no graph node gets `unknown`, NOT `materialized`: "the
        # graph is silent about this element" and "the element is built" are
        # different facts.
        node = graph_facts.get(rec.source_id)
        builder.add_element(
            element_id=rec.source_id, category=rec.category,
            level=rec.level_id, trust=TRUST_CODE[trust.value],
            fidelity=FIDELITY_CODE[fidelity.value], kind=kind, slot=slot,
            label=rec.type_name or "", axes=axes,
            authority=_graph.AUTHORITY_CODE.get(
                node.authority if node else "unknown", 2),
            existence=_graph.EXISTENCE_CODE.get(
                node.existence if node else "unknown", 2),
            flags=node.flags if node else 0)
    t_pack = time.perf_counter() - t2

    meta: dict[str, Any] = {
        "run": run,
        "source": "model",
        # SOURCE HONESTY, using the same vocabulary as `preview`: this is an
        # INDEPENDENT READING of the document, not a retelling of the
        # program.
        "assertion": "independent",
        "assertion_ru": "НЕЗАВИСИМОЕ чтение модели (разбор), не заявление программы",
        "trust_codes": TRUST_CODE,
        "fidelity_codes": FIDELITY_CODE,
        "honesty": census.to_dict(),
        "honesty_source": l1_note,
        "census": snap.census.as_dict(),
        "join_manifest": snap.join_manifest(),
        "by_grade": snap.by_grade(),
        # ELEMENTS THAT ARE NOT IN THE SCENE. Without this line the picture
        # lies by omission: on the facade that is 783 of 5 001 (15.66 %).
        "not_in_scene": snap.join_manifest()["not_scored"],
        "graph": graph_note,
        "authority_codes": _graph.AUTHORITY_CODE,
        "existence_codes": _graph.EXISTENCE_CODE,
        "flag_bits": {"refuted": _graph.FLAG_REFUTED,
                      "unresolved": _graph.FLAG_UNRESOLVED},
        "flags_ru": {"refuted": "у элемента ОПРОВЕРГНУТО отношение — назван "
                                "правилом, снявшим ребро (сам элемент цел)",
                     "unresolved": "у элемента есть отношение, чья ЦЕЛЬ вне "
                                   "извлечения: проверить нечем"},
        "timing_ms": {"hulls": round(t_hulls * 1000, 1),
                      "l1": round(t_l1 * 1000, 1),
                      "graph": round(t_graph * 1000, 1),
                      "pack": round(t_pack * 1000, 1)},
        # RECONCILIATION WITH THE PLAN IS NOT PART OF THE SCENE, AND THIS IS
        # STATED. The plan and the volume show DIFFERENT things (measured
        # 11.08: 337 elements plan-only, 270 volume-only, 663 in neither —
        # facade), and the scene's silence about it reads as "no
        # discrepancies".
        "reconcile": {"available": False,
                      "reason": ("сверка с планом не запрашивалась: она строит "
                                 "обе переписи целиком и стоит их суммы"),
                      "endpoint": "/api/viewer/reconcile"},
        # CLEARANCE PROPOSALS ARE NOT PART OF THE SCENE, AND THIS IS STATED.
        # Measured 11.08: one pair costs 29.1 ms (facade) and 372.4 ms
        # (engineering), and there are 19 239 and 35 633 overlaps — that is,
        # 9.3 minutes and 3.7 hours per building. The scene's silence would
        # read as "there is nothing to clear".
        "advice": {"available": False,
                   "reason": ("предложения разведения не запрашивались: одна "
                              "пара стоит 29–372 мс, полное здание — часы"),
                   "endpoint": "/api/viewer/advice"},
        "blind_spots": BLIND_SPOTS,
        "axes_order": list(_honesty.AXES_ORDER),
        "axes_unjudgeable": _honesty.AXES_UNJUDGEABLE,
        "axes_tally": {str(k): v for k, v in sorted(axes_tally.items())},
        "axes_ru": ("оси, по которым обязательств НЕ ОБЪЯВЛЕНО: пересборка "
                    "этого элемента его опом оставила бы их без свидетеля"),
    }
    blob = builder.finish(meta)
    meta["bytes"] = len(blob)
    return blob, meta


#: WHAT THIS SCENE DOES NOT SHOW. Printed in the viewer itself, not hidden
#: in documentation: the picture's silence reads as "everything is fine" —
#: exactly the same argument by which `preview.BLIND_SPOTS` is printed on
#: the plan sheet.
BLIND_SPOTS: tuple[str, ...] = (
    "НЕ ТЕЛА, А ОБОЛОЧКИ: каждая содержит элемент и почти всегда больше него; "
    "grade=exact недостижим по выводу, так что ни одна форма здесь не равна "
    "настоящей",
    "габарит — не форма: на демо-v3 99.89 % элементов известны только "
    "габаритным боксом, и они нарисованы боксами намеренно",
    "то, что выводит Revit (стыковки стен, составные слои, триангуляция "
    "рельефа, фитинги трасс), офлайн не считается и здесь отсутствует",
    "элементы связанных файлов оболочек не получают — межразделная картина "
    "пуста не потому, что чисто",
    "клеши: пересечения тел здесь не ищутся и не показываются",
    "материалы, слои конструкции и внешний вид — цвет здесь означает доверие, "
    "а не материал",
)
