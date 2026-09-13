#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measurement of the FULL cycle on N real bodies: save, analyze, K edits, history, reopen.

Owner's F10/Q02 mandate: "measure 10 000 REAL elements, repeated local
edits, history, memory, full latency." The instrument answers exactly this
and fixes NOTHING: it names bottlenecks with a number, it does not fix them.

🔴 THREE RULES WITHOUT WHICH THE MEASUREMENT IS NOT A MEASUREMENT (all three
paid for by findings on 06–07.09).

1. BODIES, NOT OUTPUTS. 10 000 walls without geometry do not enter the
   pairs, and a count of outputs proves nothing (owner's finding 6). Here
   every output has ITS OWN body via `capture_body`, and
   `bodies_with_geometry` must equal N — otherwise the result is NO.
2. EVERY NUMBER CARRIES WHAT EXACTLY WAS MEASURED. The report carries the
   tree's fingerprint (HEAD + dirt), the Python version, the box, N, K, and
   the phase. The time of one snapshot is not carried over to another: each
   phase has its own field.
3. WHILE THE MEASUREMENT IS RUNNING, THERE MUST BE NO FINISHED REPORT. The
   final JSON appears only at the end; while it runs, `<out>.partial` sits
   alongside it with an explicit `"состояние": "идёт"`. The previous
   artifact moves to `.prev-<штамп>.json` BEFORE the first run (finding
   impl-3: the guard reported «ГОТОВ» from the previous measurement's file
   39 s after the start).

What is measured, by phase:
  build     — building N bodies with real OCCT (`capture_body`);
  save      — writing the project to `ProjectStore` (time + size on disk);
  analyze   — `analyze_project(exact=True)` (time, peak RSS, `pairs_compared`);
  edits     — K repeated LOCAL edits: shifting ONE body via
              `ChangeProposal`/`accept_proposal`, then `reanalyze_after_fix`;
              time of each edit, p50/p95, asset reads per edit;
  history   — `store.history()` at K+3 revisions;
  reopen    — a DIFFERENT process: open the store and assemble the display
              scene (`kir.viewer.standalone_export.export_saved_project_scene`).

Run:
    PYTHONPATH=<tree> python tools/scale_bench.py --bodies 10000 --edits 20 \
        --out report.json
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

SCHEMA = "kir-scale-bench/1"
PROJECT_ID = "scale-bench"
MODULE = "scale-bench-module"

    #: Grid: a 700 mm pitch with a 600 mm box length — a 100 mm gap,
    #: neighbors do NOT overlap.
SCALE_COLS = 50
SCALE_STEP_MM = 700.0
SCALE_LEN_MM = 600.0
    #: Every `SCALE_EVERY`-th body is shifted by `SCALE_SHIFT_MM` and
    #: overlaps its right neighbor by exactly 450 mm: the answer is known
    #: BEFORE the run.
SCALE_EVERY = 37
SCALE_SHIFT_MM = 550.0
    #: Edit: shift a body by 5 mm along x. The gap is 100 mm, which means
    #: there CANNOT be new intersections — and this is the testable premise:
    #: the number of findings must stay the same.
EDIT_SHIFT_MM = 5.0


    # ── instruments ────────────────────────────────────────────────────────────
class _Rss:
    """Peak RSS BY PHASE. `ru_maxrss` gives only the global peak for the whole process.

    Read from `/proc/self/statm` (pages) by a background thread: 20 samples
    per second cost tenths of a percent and give the peak of EACH phase
    separately, rather than one number for the whole run that cannot be
    attributed to specific subjects.
    """

    def __init__(self, period: float = 0.05, limit_mb: float = 0.0) -> None:
        self._page = os.sysconf("SC_PAGE_SIZE")
        self._period = period
        self._stop = threading.Event()
        self.phase = "start"
        self.peaks: dict[str, int] = {}
        #: 🔴 THE MEMORY LIMIT IS PART OF THE MEASUREMENT, NOT ITS SERVICING.
        #: A run taken on a box that it itself brought down would measure
        #: swap, not the subject. On exceeding it the instrument raises a
        #: flag, and the DECISION is made by the main thread between phases:
        #: an edit killed mid-phase would not give an honest number.
        self.limit = int(limit_mb * 1048576)
        self.over_limit = 0
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _sample(self) -> int:
        with open("/proc/self/statm", "rb") as handle:
            return int(handle.read().split()[1]) * self._page

    def _loop(self) -> None:
        while not self._stop.wait(self._period):
            try:
                value = self._sample()
            except OSError:
                return
            if value > self.peaks.get(self.phase, 0):
                self.peaks[self.phase] = value
            if self.limit and value > self.limit and not self.over_limit:
                self.over_limit = value

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def mb(self, phase: str) -> float:
        return round(self.peaks.get(phase, self._sample()) / 1048576.0, 1)


class _AssetReads:
    """Asset-read counter. There is one real point: `project_store._read_asset`.

    🔴 WHAT IS COUNTED IS NOT "HOW MANY BODIES" BUT HOW MANY TIMES READ.
    Before 07.09 every transaction checked ALL assets of the head, and a
    single `get_asset` cost the whole revision: the formula `(N+2)·M + N`.
    This is visible only via a counter on the reader itself.
    """

    def __init__(self) -> None:
        from kir import project_store

        self._module = project_store
        self._original = project_store._read_asset
        self.calls = 0
        self.rows = 0      # reads that reached SELECT (not intercepted by the transaction cache)

    def __enter__(self) -> "_AssetReads":
        original, self_ = self._original, self

        # 🔴 THE COUNTER PASSES THROUGH ALL NAMED ARGUMENTS RATHER THAN
        # ENUMERATING THEM (08.09.2026). Enumeration broke on EVERY new
        # argument of the reader (`verify_only` is a fresh example: the
        # instrument crashed with `TypeError` before reaching the first
        # number), and what failed was the MEASUREMENT, not the subject of
        # the measurement.
        def counting(connection, project_id, digest, cache=None, **kwargs):
            self_.calls += 1
            if cache is None or digest not in cache:
                self_.rows += 1
            return original(connection, project_id, digest, cache=cache, **kwargs)

        self._module._read_asset = counting
        return self

    def __exit__(self, *exc) -> None:
        self._module._read_asset = self._original


def _pct(values, q: float):
    xs = sorted(values)
    if not xs:
        return None
    k = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return round(xs[k], 4)


def _load() -> list:
    """Box load AT THE MOMENT OF THE PHASE. Time on a busy box is a different
    number, and without this line two runs of the same code cannot be
    compared (a spread of 423 vs 101 s on 1000 bodies, 07.09)."""
    return [round(value, 2) for value in os.getloadavg()]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tree_print(root: Path) -> dict:
    """Tree fingerprint: HEAD, dirt, number of modified files. Without git edits."""
    def git(*args) -> str:
        try:
            out = subprocess.run(("git", *args), cwd=str(root), capture_output=True,
                                 text=True, timeout=30)
            return out.stdout.strip() if out.returncode == 0 else ""
        except Exception:
            return ""

    head = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain")
    lines = [line for line in dirty.splitlines() if line.strip()]
    return {"head": head or "неизвестен", "head_short": (head or "?")[:7],
            "dirty": bool(lines), "dirty_files": len(lines),
            "subject": git("log", "-1", "--pretty=%s")[:120]}


    # ── scene ──────────────────────────────────────────────────────────────────
def seeded_boxes(n: int):
    """N real boxes in a grid + a DETERMINISTIC SEEDING of intersections.

    Moved into the repository from the acceptance fixture
    `.work/.../acceptance/fixture.py` (mandate: acceptance scenarios live IN
    THE REPOSITORY). There are no dependencies on `.work`.
    -> (bodies, seeded pairs, indices safe to edit).
    """
    boxes, seeded, touched = [], [], set()
    for i in range(n):
        col, row = i % SCALE_COLS, i // SCALE_COLS
        x0, y0 = col * SCALE_STEP_MM, row * SCALE_STEP_MM
        shift = SCALE_SHIFT_MM if (i % SCALE_EVERY == 0 and col != SCALE_COLS - 1) else 0.0
        if shift:
            seeded.append((i, i + 1))
            touched.update((i, i + 1))
        boxes.append((f"b{i}", ((x0 + shift, y0, 0.0),
                                (x0 + shift + SCALE_LEN_MM, y0 + 200.0, 3000.0))))
    # We edit only bodies NOT participating in the seeding: otherwise the
    # edit would change the oracle's answer, and "the number of findings did
    # not change" would stop being a check.
    safe = tuple(i for i in range(n) if i not in touched)
    return tuple(boxes), tuple(seeded), safe


def _pin():
    from kir.occt_geometry import OCP_VERSION
    from kir.project import RecipePin

    source = Path(__file__).read_text(encoding="utf-8")
    env = {"python": platform.python_version(), "ocp_package": OCP_VERSION, "dependencies": {}}
    digest = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
    return RecipePin(source, digest, entrypoint="build_scene", dependencies={})


def _box_shape(box):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    (x0, y0, z0), (x1, y1, z1) = box
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def _capture(key: str, box, parameters, pin):
    from kir.occt_geometry import IDENTITY_FRAME, capture_body

    return capture_body(_box_shape(box), project_id=PROJECT_ID, instance_key=key,
                        output_key=key, recipe=pin, parameters=parameters,
                        frame=IDENTITY_FRAME, linear_deflection_mm=40.0)


def _empty_root():
    from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision

    seed = NamedOutput("origin", {"op": "create_level", "elev_mm": 0, "name": "L0"})
    return ProjectRevision(PROJECT_ID, [ModuleDefinition(MODULE)],
                           [ModuleInstance("scene", MODULE, [seed])])


def build_scene(boxes, pin=None):
    """-> (revision, {sha: bandle}). EVERY body has its own instance and its own geometry."""
    from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance,
                             NamedOutput, PROJECT_SCHEMA_V2)

    pin = pin or _pin()
    instances, bundles = [], []
    for key, box in boxes:
        parameters = {"bulge_mm": 0.0, key: [list(box[0]), list(box[1])]}
        bundle = _capture(key, box, parameters, pin)
        bundles.append(bundle)
        instances.append(ModuleInstance(
            key, MODULE,
            [NamedOutput(key, {"op": "create_directshape", "category": "mass",
                               "name": "scale " + key},
                         BodyRepresentation(bundle.digest, bundle.body_digest))],
            parameters, metadata={"scene": "scale-bench"}))
    root = _empty_root()
    upgraded = root.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=root.revision_id)
    revision = upgraded.revise(expected_revision=upgraded.revision_id,
                               modules=[ModuleDefinition(MODULE, "sealed_evaluation", pin)],
                               instances=instances)
    return revision, bundles


def save_scene(path: Path, revision, bundles):
    """Store /1 -> upgrade to /2 -> commit the revision WITH ASSETS."""
    from kir.project_store import ProjectStore

    root = _empty_root()
    store = ProjectStore.create(path, root)
    store.upgrade_schema("kir-project-store/2", expected_revision=root.revision_id)
    upgraded = root.upgrade_schema(revision.schema, expected_revision=root.revision_id)
    store.commit(upgraded, expected_revision=root.revision_id)
    store.commit(revision, expected_revision=upgraded.revision_id, assets=list(bundles))
    return store


def disk_bytes(path: Path) -> int:
    total = 0
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            total += candidate.stat().st_size
    return total


    # ── one local edit ────────────────────────────────────────────────────────
def edit_one_body(store, key: str, pin):
    """Shift of ONE body by 5 mm along x: recompute the body -> ChangeProposal -> accept_proposal.

    🔴 THE CLOCK COVERS THE WHOLE EDIT, NOT ITS LAST THIRD. In the
    instrument's first edition (07.09, caught before the numbers were
    published) the stopwatch stood ONLY around `accept_proposal`, while the
    caption said «пересчёт тела + ChangeProposal + accept_proposal». The
    difference is not cosmetic: `ChangeProposal.__post_init__` canonicalizes
    and hashes BOTH revisions in full, i.e. it pays for all N bodies — and
    that time slipped past the report. Now the three terms are named
    separately, and `apply_s` is their sum.

    Returns a dict with the times, asset reads, and the new head.
    """
    from kir.project import BodyRepresentation, ModuleInstance, NamedOutput
    from kir.project_merge import ChangeProposal, ProposalScope, accept_proposal

    head = store.head()
    instance = next(item for item in head.instances if item.key == key)
    output = next(item for item in instance.outputs if item.key == key)
    box = instance.parameters[key]
    moved = [[box[0][0] + EDIT_SHIFT_MM, box[0][1], box[0][2]],
             [box[1][0] + EDIT_SHIFT_MM, box[1][1], box[1][2]]]
    parameters = dict(instance.parameters)
    parameters[key] = moved
    with _AssetReads() as reads:
        start = time.monotonic()
        bundle = _capture(key, ((moved[0][0], moved[0][1], moved[0][2]),
                                (moved[1][0], moved[1][1], moved[1][2])), parameters, pin)
        rebuilt = time.monotonic()
        new_instance = ModuleInstance(
            instance.key, instance.module_key,
            [NamedOutput(output.key, output.operation,
                         BodyRepresentation(bundle.digest, bundle.body_digest))
             if item.key == output.key else item for item in instance.outputs],
            parameters, metadata=instance.metadata)
        candidate = head.revise(expected_revision=head.revision_id,
                                instances=[new_instance if item.key == key else item
                                           for item in head.instances])
        scope = ProposalScope(instances=(key,))
        proposal = ChangeProposal(head, candidate, scope, "tools.scale_bench",
                                  f"сдвиг {key} на {EDIT_SHIFT_MM} мм по x (замер масштаба)")
        proposed = time.monotonic()
        acceptance = accept_proposal(store, proposal, expected_revision=head.revision_id,
                                     authorized_scope=scope, assets=[bundle])
        accepted = time.monotonic()
    if not acceptance.merge.clean:
        raise RuntimeError("правка не принята хранилищем: " + json.dumps(
            acceptance.merge.report.get("conflicts", []), ensure_ascii=False)[:300])
    return {"apply_s": accepted - start,
            "rebuild_s": rebuilt - start,
            "proposal_s": proposed - rebuilt,
            "accept_s": accepted - proposed,
            "asset_reads_apply": reads.calls, "asset_row_reads_apply": reads.rows,
            "head": acceptance.commit.head_revision}


    # ── child: reopening in a DIFFERENT process ───────────────────────────────
def reopen_child(store_path: str, exact: bool) -> int:
    """Cold process: open the store and assemble the display scene. Prints JSON."""
    from kir.project_store import ProjectStore
    from kir.viewer.standalone_export import export_saved_project_scene

    t0 = time.monotonic()
    store = ProjectStore.open(Path(store_path))
    head = store.head()
    open_s = time.monotonic() - t0
    t1 = time.monotonic()
    artifact, report = export_saved_project_scene(store, exact=exact)
    scene_s = time.monotonic() - t1
    blob = artifact.scene_bytes
    print(json.dumps({
        "open_s": round(open_s, 4), "scene_s": round(scene_s, 4),
        "ready_s": round(open_s + scene_s, 4),
        "revision": head.revision_id[:12], "findings": len(report.findings),
        "scene_bytes": len(blob), "artifact_digest": artifact.digest[:12],
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
    }, ensure_ascii=False))
    return 0


    # ── run ────────────────────────────────────────────────────────────────────
def run(args) -> int:
    from kir.clash.project_analysis import analyze_project, reanalyze_after_fix

    root = Path(__file__).resolve().parent.parent
    out = Path(args.out).resolve() if args.out else (root / f"scale-{args.bodies}.json")
    partial = out.with_suffix(out.suffix + ".partial")
    # The old artifact moves out BEFORE the first run: while the measurement
    # is in progress, there is nothing to read.
    if out.exists():
        kept = out.with_name(out.stem + f".prev-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
        out.rename(kept)
        print(f"  прежний отчёт убран в {kept.name}", flush=True)

    rss = _Rss(limit_mb=args.rss_limit_mb)
    rss.start()
    report: dict = {
        # 🔴 "REQUESTED" AND "DONE" ARE DIFFERENT FIELDS. While they were one
        # name, the edit summary overwrote the requested number, and the
        # report lost how many edits were asked for: a run stopped by the RSS
        # limit would read as complete.
        "schema": SCHEMA, "состояние": "идёт", "bodies": args.bodies,
        "edits_planned": args.edits,
        "exact": bool(args.exact), "started_utc": _now(),
        "tree": tree_print(root),
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "host": {"cpu_count": os.cpu_count(), "loadavg_start": list(os.getloadavg()),
                 "hostname": platform.node()},
        "измерено": ("полный цикл: запись -> анализ -> K локальных правок -> история -> "
                     "повторное открытие в другом процессе; каждое число — своей фазы"),
    }

    def flush(state: str = "идёт") -> None:
        report["состояние"] = state
        partial.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    flush()
    boxes, seeded, safe = seeded_boxes(args.bodies)
    if args.edits > len(safe):
        print(f"ЗАМЕР НЕ СОСТОЯЛСЯ: правок {args.edits} больше свободных тел {len(safe)}")
        return 2
    pin = _pin()

    # (0) building the bodies
    rss.phase = "build"
    t0 = time.monotonic()
    revision, bundles = build_scene(boxes, pin)
    report["build"] = {"s": round(time.monotonic() - t0, 3), "bodies": len(bundles),
                       "peak_rss_mb": rss.mb("build"), "loadavg": _load(),
                       "что измерено": "capture_body по N коробкам, настоящий OCCT"}
    print("  build:", json.dumps(report["build"], ensure_ascii=False), flush=True)
    flush()

    # (a) writing the project
    tmp = Path(tempfile.mkdtemp(prefix=f"scale-{args.bodies}-", dir=args.tmp or None))
    store_path = tmp / "project.sqlite"
    rss.phase = "save"
    t0 = time.monotonic()
    store = save_scene(store_path, revision, bundles)
    save_s = time.monotonic() - t0
    report["save"] = {"s": round(save_s, 3), "loadavg": _load(),
                      "disk_bytes": disk_bytes(store_path),
                      "disk_mb": round(disk_bytes(store_path) / 1048576.0, 2),
                      "peak_rss_mb": rss.mb("save"), "path": str(store_path),
                      "что измерено": "ProjectStore.create + подъём схемы + коммит ревизии с ассетами"}
    print("  save:", json.dumps(report["save"], ensure_ascii=False), flush=True)
    flush()
    del bundles

    # (b) analysis
    rss.phase = "analyze"
    with _AssetReads() as reads:
        t0 = time.monotonic()
        analysis = analyze_project(store, exact=args.exact)
        analyze_s = time.monotonic() - t0
    inter = [f for f in analysis.findings if f.relation == "intersect"]
    names = {bid: pair[1] for bid, pair in (analysis.body_keys or {}).items()}
    found = {tuple(sorted((names.get(f.a, f.a), names.get(f.b, f.b)))) for f in inter}
    want = {tuple(sorted((f"b{i}", f"b{j}"))) for i, j in seeded}
    report["analyze"] = {
        "s": round(analyze_s, 3), "peak_rss_mb": rss.mb("analyze"), "loadavg": _load(),
        "bodies_declared": analysis.bodies_declared,
        "bodies_with_geometry": getattr(analysis, "bodies_with_geometry", "нет поля"),
        "pairs_possible": getattr(analysis, "pairs_possible", "нет поля"),
        "pairs_compared": analysis.pairs_compared,
        "findings": len(analysis.findings), "intersections": len(inter),
        "seeded": len(seeded), "seed_found_all": found == want,
        "seed_missing": sorted(want - found)[:5], "extra_intersections": len(found - want),
        "asset_reads": reads.calls, "asset_row_reads": reads.rows,
        "что измерено": f"analyze_project(exact={bool(args.exact)}) на голове, N тел",
    }
    print("  analyze:", json.dumps(report["analyze"], ensure_ascii=False), flush=True)
    flush()
    baseline_findings = len(analysis.findings)
    del analysis, inter, found

    # (c) K repeated LOCAL edits
    rows = []
    for number in range(args.edits):
        key = f"b{safe[number]}"
        rss.phase = f"edit{number}"
        edit = edit_one_body(store, key, pin)
        with _AssetReads() as reads:
            t0 = time.monotonic()
            after = reanalyze_after_fix(store, exact=args.exact)
            re_s = time.monotonic() - t0
        rows.append({"n": number + 1, "body": key, "apply_s": round(edit["apply_s"], 4),
                     "rebuild_s": round(edit["rebuild_s"], 4),
                     "proposal_s": round(edit["proposal_s"], 4),
                     "accept_s": round(edit["accept_s"], 4),
                     "reanalyze_s": round(re_s, 3),
                     "total_s": round(edit["apply_s"] + re_s, 3),
                     "asset_reads_apply": edit["asset_reads_apply"],
                     "asset_row_reads_apply": edit["asset_row_reads_apply"],
                     "asset_reads_reanalyze": reads.calls,
                     "findings": len(after.findings), "revision": edit["head"][:12],
                     "peak_rss_mb": rss.mb(f"edit{number}"), "loadavg": _load()})
        print("  edit:", json.dumps(rows[-1], ensure_ascii=False), flush=True)
        report["edits"] = _edit_summary(rows, args.edits, baseline_findings)
        flush()
        del after
        if rss.over_limit:
            report["остановлено"] = {
                "почему": "RSS вышел за объявленный предел",
                "предел_мб": round(rss.limit / 1048576.0, 1),
                "замечено_мб": round(rss.over_limit / 1048576.0, 1),
                "правок_сделано": len(rows), "правок_заказано": args.edits}
            print("  ОСТАНОВ:", json.dumps(report["остановлено"], ensure_ascii=False), flush=True)
            break
    if rows:
        report["edits"] = _edit_summary(rows, args.edits, baseline_findings)

    # (d) history at K+3 revisions
    rss.phase = "history"
    with _AssetReads() as reads:
        t0 = time.monotonic()
        history = store.history()
        history_s = time.monotonic() - t0
    report["history"] = {"s": round(history_s, 3), "revisions": len(history), "loadavg": _load(),
                         "asset_reads": reads.calls, "asset_row_reads": reads.rows,
                         "peak_rss_mb": rss.mb("history"),
                         "что измерено": "store.history() при K правках поверх базовой ревизии"}
    print("  history:", json.dumps(report["history"], ensure_ascii=False), flush=True)
    del history
    flush()

    # (e) reopening in a DIFFERENT process
    if args.reopen:
        rss.phase = "reopen"
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--reopen-child", str(store_path)]
            + ([] if args.exact else ["--no-exact"]),
            capture_output=True, text=True, timeout=args.reopen_timeout,
            env={**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"})
        try:
            report["reopen"] = json.loads(child.stdout.strip().splitlines()[-1])
            report["reopen"]["что измерено"] = (
                "ХОЛОДНЫЙ процесс: ProjectStore.open + export_saved_project_scene "
                "(анализ внутри), время до готовности сцены")
        except Exception:
            report["reopen"] = {"ЗАМЕР НЕ СОСТОЯЛСЯ": (child.stderr or child.stdout)[-400:]}
        print("  reopen:", json.dumps(report["reopen"], ensure_ascii=False), flush=True)
        flush()

    report["peak_rss_mb"] = round(max(rss.peaks.values() or [0]) / 1048576.0, 1)
    report["ru_maxrss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    report["finished_utc"] = _now()
    report["wall_s"] = round(sum(
        float(report.get(phase, {}).get("s") or 0.0) for phase in ("build", "save", "analyze", "history")
    ) + sum(row["total_s"] for row in rows), 1)
    honest = (report["analyze"]["bodies_with_geometry"] == args.bodies
              and report["analyze"]["seed_found_all"] is True)
    report["ИТОГ"] = "ДА" if honest else "НЕТ"
    report["почему"] = ("тела участвуют и посев найден полностью" if honest else
                        "тела не участвуют либо посев найден не весь — время есть, ответа нет")
    rss.stop()
    flush(state="готов")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    partial.unlink(missing_ok=True)
    print(json.dumps({k: v for k, v in report.items() if k not in ("edits",)},
                     ensure_ascii=False), flush=True)
    print("записано:", out, flush=True)
    return 0 if honest else 1


def _edit_summary(rows, planned: int, baseline_findings: int) -> dict:
    """p50/p95 across edits + latency growth + read-count stability.

    🔴 GROWTH IS COMPUTED AS THE MEDIANS OF HALVES, NOT AS "LAST TO FIRST".
    One edit under someone else's load produces an outlier, and the ratio of
    the extreme numbers would declare degradation where there is none. The
    halves are robust and still catch growth just the same.
    """
    totals = [row["total_s"] for row in rows]
    half = max(1, len(totals) // 2)
    first, second = totals[:half], totals[len(totals) - half:]
    growth = (statistics.median(second) / statistics.median(first)
              if statistics.median(first) > 0 else None)
    applies = [row["asset_reads_apply"] for row in rows]
    return {
        "count": len(rows), "planned": planned,
        "apply_s_p50": _pct([row["apply_s"] for row in rows], 0.5),
        "apply_s_p95": _pct([row["apply_s"] for row in rows], 0.95),
        "rebuild_s_p50": _pct([row["rebuild_s"] for row in rows], 0.5),
        "proposal_s_p50": _pct([row["proposal_s"] for row in rows], 0.5),
        "accept_s_p50": _pct([row["accept_s"] for row in rows], 0.5),
        "reanalyze_s_p50": _pct([row["reanalyze_s"] for row in rows], 0.5),
        "reanalyze_s_p95": _pct([row["reanalyze_s"] for row in rows], 0.95),
        "total_s_p50": _pct(totals, 0.5), "total_s_p95": _pct(totals, 0.95),
        "total_s_min": round(min(totals), 3), "total_s_max": round(max(totals), 3),
        "growth_ratio_halves": round(growth, 3) if growth else None,
        "asset_reads_apply_min": min(applies), "asset_reads_apply_max": max(applies),
        "asset_reads_apply_p50": _pct(applies, 0.5),
        "asset_reads_apply_growth": (round(applies[-1] / applies[0], 3)
                                     if applies and applies[0] else None),
        "findings_baseline": baseline_findings,
        "findings_stable": all(row["findings"] == baseline_findings for row in rows),
        "per_edit": rows,
        "что измерено": ("одна локальная правка: apply = пересчёт тела (rebuild) + "
                         "сборка ChangeProposal (proposal) + accept_proposal (accept); "
                         "затем reanalyze_after_fix (reanalyze). total = apply + reanalyze"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="замер полного цикла KIR на N телах")
    parser.add_argument("--bodies", type=int, default=200, help="N тел с настоящей геометрией")
    parser.add_argument("--edits", type=int, default=5, help="K повторных локальных правок")
    parser.add_argument("--out", default="", help="куда положить отчёт JSON")
    parser.add_argument("--tmp", default=os.environ.get("TMPDIR") or "",
                        help="каталог для хранилища замера")
    parser.add_argument("--no-exact", dest="exact", action="store_false",
                        help="грубый анализ вместо точного")
    parser.add_argument("--no-reopen", dest="reopen", action="store_false",
                        help="не мерить повторное открытие в другом процессе")
    parser.add_argument("--reopen-timeout", type=float, default=7200.0)
    parser.add_argument("--rss-limit-mb", type=float, default=3000.0,
                        help="остановиться между правками, если пик RSS вышел за предел")
    parser.add_argument("--reopen-child", default="", help=argparse.SUPPRESS)
    parser.set_defaults(exact=True, reopen=True)
    args = parser.parse_args(argv)
    if args.reopen_child:
        return reopen_child(args.reopen_child, args.exact)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
