"""THE wall-prism LOCK GATE: one command decides whether the builder can be written.

    PYTHONPATH=. venv/bin/python -m kir.clash.tools.wall_prism_gate <run> [...]

Method. The predicted prism is checked for CONTAINMENT of the Revit bounding
box for those walls that HAVE a bounding box. The bounding box comes from the
real geometry of the model, so this is a check of the conservativeness law
against an EXTERNAL witness, not a formula checked against itself.
Measurement 29.07 on v18: the best variant of the formula left 15–24
violations out of 1 752 with a maximum of 1 785 mm outward — the builder was
not shipped.

**Zero violations across the whole sample = the lock opens.** Any nonzero
number is a refusal, and it is printed together with a breakdown by cause.

Numbers are not published without a manifest: code commit, sha of the inputs,
revision fingerprint.
"""
from __future__ import annotations

import collections
import json
import os
from kir import env  # noqa: E402  (submodule without dependencies — creates no cycle)
import pathlib
import statistics
import subprocess
import sys
import tempfile
import time

from kir.clash import hulls as H
# The name was called and was not bound AT ALL. Here a module-level import is
# appropriate: it's a separate tool, and it is run on the whole tree anyway.
from kir.model.snapshot_io import (
    open_snapshot, read_snapshot_text, snapshot_file_exists)
from kir.clash.hulls import _valid_box

#: 🔴 THREE ABSOLUTE PATHS WERE REMOVED 27.08.2026, AND ALL THREE WERE ROUTES.
#: Here stood `/opt/kukai-rebuild1` (the owner's tree), `/home/claude/kir-night`
#: (one person's one-night directory), and `parents[3]/backend/data` — a count
#: of steps upward that after the split points to `/opt/kir/backend`, where
#: there is nothing. The package is published under Apache-2.0: an unrelated
#: person has none of the three, and the instrument was silently measuring
#: emptiness.
#:
#: The root is ASKED of the installation (`install_paths`) — the same place
#: the other eight consumers get it — not recomputed a fourth way.
_ARTIFACTS_ENV = "KIR_GATE_ARTIFACTS"
_GIT_ROOT_ENV = "KIR_GIT_ROOT"


def _decompile_root() -> pathlib.Path | None:
    from kir.install_paths import install_data_path
    return install_data_path("decompile")


ROOT = _decompile_root() or pathlib.Path("decompile-root-not-configured")
ART = pathlib.Path(env.get(_ARTIFACTS_ENV) or tempfile.gettempdir())


def _git(*a: str) -> str:
    """`git` in the tree NAMED by the installation. Not named — empty, and
    that is honest.

    The previous version called `git -C /opt/kukai-rebuild1` unconditionally:
    an unrelated person has no such tree, `git` returned empty stdout, and
    the run's provenance came out empty WITHOUT SAYING SO. Form 34: an
    instrument whose action may not happen is required to have a separate
    loud outcome.
    """
    root = (env.get(_GIT_ROOT_ENV) or "").strip()
    if not root:
        return f"<{_GIT_ROOT_ENV} не задана: провенанс дерева не снят>"
    return subprocess.run(["git", "-C", root, *a],
                          capture_output=True, text=True).stdout.strip()


def _p(el: dict, key: str):
    return (el.get("params") or {}).get(key)


def _read(run_dir: pathlib.Path):
    levels: dict[str, float] = {}
    no_box: list[dict] = []
    with_box: list[dict] = []
    # 🔴 READ BY THE SAME LAW BY WHICH IT WAS ACCEPTED (F-324, 29.08.2026).
    # `analyse` judges whether a decompile exists via `snapshot_file_exists`,
    # which DELIBERATELY accepts `L0.jsonl.gz`. A bare `open` dropped the
    # instrument on the very input that the line above declared found. Line
    # by line, not all at once: L0 can be 13-47 MB raw.
    with open_snapshot(run_dir / "L0.jsonl", "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kind = row.get("record")
            if kind == "header":
                for lv in (row["document"].get("levels") or []):
                    levels[str(lv["id"])] = lv["elevation_mm"]
            elif kind == "element":
                el = row["element"]
                if el.get("category") != "OST_Walls":
                    continue
                if _valid_box(el.get("bbox_min_mm"), el.get("bbox_max_mm")) is None:
                    no_box.append(el)
                else:
                    with_box.append(el)
    curves = {}
    cv = run_dir / "curve.index.json"
    if snapshot_file_exists(cv):
        # A SECOND place with the same mismatch IN THE SAME instrument:
        # existence was judged by `snapshot_file_exists`, while the opening
        # went through a bare `read_text`. Here `read_snapshot_text` is
        # appropriate: the side index is read WHOLE with a single
        # `json.loads`, and the reading modes are already split in
        # `snapshot_io` — streaming for L0, whole for indexes.
        curves = json.loads(read_snapshot_text(cv)).get("curve_index") or {}
    return no_box, with_box, levels, curves


def _z_span(el: dict, levels: dict[str, float], mode: str) -> tuple[float, float]:
    """The vertical extent of a wall. The v19 measurement dictated a UNION of
    interpretations.

    `WALL_BASE_OFFSET` is sometimes already accounted for in the axis
    elevation, sometimes not: on v19, wall 9203306 misses by 4 300 mm without
    it, while wall 11444377 misses by 1 290 mm WITH it. There is nothing in
    the data to distinguish them by, so the UNION of both interpretations is
    taken: coarsening upward is legitimate, guessing which one is correct is
    not.

    `WALL_HEIGHT_TYPE` is the id of the TOP LEVEL of an attached wall
    (measured on v19: both values encountered resolve to header elevations).
    For such a wall the real height is NOT equal to `WALL_USER_HEIGHT_PARAM`:
    for 8234565 the parameter is 7 970 mm while the real height is 9 755 mm.
    The top is taken as the level plus `WALL_TOP_OFFSET`; on all seven of
    v19's Z-misses this is enough.
    """
    p0 = el["p0_mm"]
    h = _p(el, "WALL_USER_HEIGHT_PARAM") or 0.0
    base = _p(el, "WALL_BASE_OFFSET") or 0.0
    top = _p(el, "WALL_TOP_OFFSET") or 0.0
    lvl = levels.get(str(el.get("level_id")))
    if mode == "axis":
        return p0[2], p0[2] + h
    bases = [p0[2], p0[2] + base]
    if lvl is not None:
        bases += [lvl, lvl + base]
    tops = [b + h for b in bases]
    if mode == "level_union":
        ht = _p(el, "WALL_HEIGHT_TYPE")
        top_lvl = levels.get(str(ht)) if ht is not None else None
        if top_lvl is not None:
            tops += [top_lvl, top_lvl + top]
    if mode in ("base_top", "level_union"):
        tops = [t + abs(top) for t in tops] + tops
    return min(bases), max(tops)


def _predict(el: dict, *, z_mode: str, use_key_ref: bool,
             levels: dict[str, float] | None = None,
             curves: dict | None = None):
    w = _p(el, "WALL_ATTR_WIDTH_PARAM")
    h = _p(el, "WALL_USER_HEIGHT_PARAM")
    p0, p1 = el.get("p0_mm"), el.get("p1_mm")
    # 🔴 A LEGITIMATE ZERO IS NOT AN ABSENCE OF DATA (F-323, 29.08.2026).
    # `not (w and h ...)` dropped a wall with zero width or zero height into
    # `skipped_no_data` — that is, into the very EMPTINESS that is declared
    # below as the lock's threshold. A width of 0 is not "nothing to predict
    # from", it is a prediction of zero thickness, and if the Revit body has
    # thickness, the formula was WRONG, and it is required to answer with a
    # violation, not with silence.
    if w is None or h is None or not p0 or not p1:
        return None
    z0, z1 = _z_span(el, levels or {}, z_mode)
    hw = (H.wall_axis_halfwidth(w, _p(el, "WALL_KEY_REF_PARAM"))
          if use_key_ref else float(w))
    xs = [p0[0], p1[0]]
    ys = [p0[1], p1[1]]
    # An arc: the endpoints do NOT describe what lies between them. A gate
    # that predicts the bounding box from the endpoints misses by
    # construction — and that is not a property of the wall, but a defect of
    # the prediction. We take the same polyline that fixes the hull.
    cur = (curves or {}).get(str(el.get("element_id"))) or {}
    if cur.get("curve_kind") == "arc" and cur.get("arc"):
        pts, sag = H.arc_chord_polyline(cur["arc"], tuple(p0), tuple(p1))
        if len(pts) > 2 or sag > 0:
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            hw += sag
    lo = (min(xs) - hw, min(ys) - hw, min(z0, z1))
    hi = (max(xs) + hw, max(ys) + hw, max(z0, z1))
    return lo, hi


def _variant(with_box: list[dict], *, z_mode: str, use_key_ref: bool,
             levels: dict | None = None, curves: dict | None = None) -> dict:
    inside = skipped = 0
    breaches: list[tuple[float, dict, list[float]]] = []
    for el in with_box:
        pred = _predict(el, z_mode=z_mode, use_key_ref=use_key_ref,
                        levels=levels, curves=curves)
        if pred is None:
            skipped += 1
            continue
        plo, phi = pred
        lo, hi = el["bbox_min_mm"], el["bbox_max_mm"]
        per_axis = [max(plo[k] - lo[k], hi[k] - phi[k]) for k in range(3)]
        out = max(per_axis)
        if out <= 1e-6:
            inside += 1
        else:
            breaches.append((out, el, per_axis))
    ex = [b[0] for b in breaches]
    return {"contained": inside, "not_contained": len(breaches),
            "skipped_no_data": skipped,
            # 🔴 THE LOCK'S DENOMINATOR (F-323, 29.08.2026). "Zero violations
            # ACROSS THE WHOLE SAMPLE" is a claim about TWO numbers, but the
            # decision was made on one. Here it is declared HOW MANY walls
            # actually passed the check: only they were witnesses. The ones
            # skipped testify neither for nor against. The field is ADDED,
            # not one previous field is touched.
            "judged": inside + len(breaches),
            "median_excess_mm": round(statistics.median(ex), 1) if ex else 0.0,
            "max_excess_mm": round(max(ex), 1) if ex else 0.0,
            "_breaches": breaches}


VARIANTS = {
    "z_axis__hw_w": ("axis", False),
    "z_base__hw_w": ("base", False),
    "z_base_top__hw_w": ("base_top", False),
    "z_base_top__hw_key_ref": ("base_top", True),
    "z_level_union__arc__key_ref": ("level_union", True),
}
BEST = "z_level_union__arc__key_ref"


def analyse(run: str) -> dict:
    d = ROOT / run
    # 🔴 THE LOCAL IMPORT WAS REMOVED 28.08.2026: `snapshot_file_exists` is
    # already imported at the module level (line 31), and a second import of
    # the same name inside the function SHADOWS the first — a fix to the
    # module-level import silently fails to reach here. The guard
    # `test_authority_boundaries` catches exactly this.
    if not snapshot_file_exists(d / "L0.jsonl"):
        return {"run": run, "error": "нет L0.jsonl"}
    no_box, with_box, levels, curves = _read(d)

    variants: dict[str, dict] = {}
    best_breaches: list = []
    for name, (zm, kr) in VARIANTS.items():
        v = _variant(with_box, z_mode=zm, use_key_ref=kr,
                     levels=levels, curves=curves)
        b = v.pop("_breaches")
        variants[name] = v
        if name == BEST:
            best_breaches = b

    arcs = {k for k, v in curves.items() if v.get("curve_kind") != "line"}
    diag = {
        "count": len(best_breaches),
        "axis_of_excess": dict(collections.Counter(
            "XY" if max(a[0], a[1]) > a[2] else "Z" for _, _, a in best_breaches)),
        "curve_kind": dict(collections.Counter(
            (curves.get(str(e["element_id"])) or {}).get("curve_kind")
            for _, e, _ in best_breaches)),
        "has_WALL_HEIGHT_TYPE": sum(
            1 for _, e, _ in best_breaches if _p(e, "WALL_HEIGHT_TYPE") is not None),
        "has_WALL_CROSS_SECTION": sum(
            1 for _, e, _ in best_breaches if _p(e, "WALL_CROSS_SECTION") is not None),
        "predicate_axis_not_line_covers": sum(
            1 for _, e, _ in best_breaches if str(e["element_id"]) in arcs),
        "worst": [{"element_id": str(e["element_id"]), "excess_mm": round(o, 1),
                   "per_axis_mm": [round(x, 1) for x in a],
                   "width_mm": _p(e, "WALL_ATTR_WIDTH_PARAM"),
                   "height_mm": round(_p(e, "WALL_USER_HEIGHT_PARAM") or 0.0, 1),
                   "cross_section": _p(e, "WALL_CROSS_SECTION")}
                  for o, e, a in sorted(best_breaches, key=lambda t: -t[0])[:5]],
    }
    cand = [e for e in no_box if _p(e, "WALL_ATTR_WIDTH_PARAM") is not None]

    # 🔴 A FLOOR OF NON-EMPTINESS (F-323, 29.08.2026). The lock is declared
    # with the words "zero violations ACROSS THE WHOLE SAMPLE", but the
    # decision was made using ONLY the numerator (`diag["count"] == 0`). The
    # denominator was computed, printed — and did not enter the decision, so
    # the lock became GREENER THE FEWER CLUES IT HAD: no walls at all · not a
    # single one with a bounding box · every one missing width/height/axis.
    # This is a "green worthless control": the check "does it turn red on the
    # removed fix" does NOT catch it, because on the real sample it turns red
    # for a DIFFERENT reason.
    #
    # Two kinds of emptiness, not one flag: their next turn is different. "No
    # bounding box" = the decompile was taken before the bounding-box wave, a
    # different decompile is needed; "not predictable" = a defect of the
    # prediction itself, fix the formula. The shape is the same as in
    # `snapshot_janitor._verify_all` (`75220fb`) and the neighboring
    # `bundle_containment_gate`: the cause is printed FIRST, before the
    # numbers, and the return codes distinguish "the measurement found
    # damage" from "there was no measurement".
    #
    # There is deliberately NO threshold on the SHARE skipped: the 29.07
    # measurement speaks of 1 752 walls and 15–24 violations, but says
    # nothing about an acceptable share of skips — any threshold number would
    # have been assigned without an incident. The share IS DECLARED
    # (`coverage`), and the only thing that decides is the boundary "the
    # measurement happened".
    #
    # `judged` is taken from the SAME variant the numerator is taken from
    # (BEST): otherwise the numerator and denominator would be about
    # different formulas.
    judged = variants[BEST]["judged"]
    emptiness: str | None = None
    if len(with_box) == 0:
        emptiness = ("ни одной стены с габаритом Revit: свидетеля нет, "
                     "сверять предсказание не с чем")
    elif judged == 0:
        emptiness = (f"ни одна из {len(with_box)} стен с габаритом не "
                     f"предсказуема (нет ширины/высоты/оси): пропущено "
                     f"{variants[BEST]['skipped_no_data']}")

    proof = d / "revision.proof.json"
    return {
        "run": run,
        "revision": (json.loads(proof.read_text(encoding="utf-8"))
                     if proof.exists() else None),
        "levels_in_header": len(levels),
        "target_population": {
            "walls_total": len(no_box) + len(with_box),
            "without_hull": len(no_box),
            "ordinary_with_axis_width_height": len(cand),
            "curtain_hosts_without_width": len(no_box) - len(cand),
            "ground_truth_walls_with_bbox": len(with_box),
            "candidates_with_cross_section": sum(
                1 for e in cand if _p(e, "WALL_CROSS_SECTION") is not None),
        },
        "formula_variants": variants,
        "non_containing_diagnosis": diag,
        "judged": judged,
        "coverage": {
            "judged": judged,
            "denominator": len(with_box),
            "skipped_no_data": variants[BEST]["skipped_no_data"],
        },
        "empty_evidence": emptiness,
        "gate_open": emptiness is None and diag["count"] == 0,
    }


def main(argv: list[str] | None = None) -> int:
    runs = list(argv if argv is not None else sys.argv[1:]) or ["sob62_fas_r23_v18"]
    rows = [analyse(r) for r in runs]
    doc = {
        "manifest": {
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "code_commit": _git("rev-parse", "HEAD"),
            "code_commit_subject": _git("log", "-1", "--pretty=%s"),
            "tree_dirty_clash": _git("status", "--short",
                                     "backend/kir/clash").splitlines(),
            "tool": "kir.clash.tools.wall_prism_gate",
            "method": ("предсказанная призма проверяется на СОДЕРЖАНИЕ габарита "
                       "Revit; габарит — тело из самой модели, поэтому это "
                       "проверка закона консервативности против внешнего "
                       "свидетеля, а не сверка формулы с собой"),
            "gate_rule": "ноль нарушений на всей выборке = замок открывается",
            "note": "числа без манифеста не публикуются",
        },
        "runs": rows,
    }
    out = ART / f"clash_wallprism_{runs[0].split('_')[-1]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        if r.get("error"):
            print(f"{r['run']}: {r['error']}")
            continue
        t = r["target_population"]
        print(f"\n### {r['run']}")
        # 🔴 The cause FIRST, before the numbers (the convention of
        # `75220fb`): the reader is stopped by the header, not by a footnote
        # under the table.
        if r.get("empty_evidence"):
            print(f"  🔴 ЗАМЕР НЕ СОСТОЯЛСЯ: {r['empty_evidence']}")
        print(f"  стен {t['walls_total']}, без оболочки {t['without_hull']} "
              f"(обычных {t['ordinary_with_axis_width_height']}, "
              f"витражных {t['curtain_hosts_without_width']})")
        print(f"  WALL_CROSS_SECTION у кандидатов: "
              f"{t['candidates_with_cross_section']} из "
              f"{t['ordinary_with_axis_width_height']}")
        print(f"  ground truth: {t['ground_truth_walls_with_bbox']} стен с габаритом")
        for name, val in r["formula_variants"].items():
            print(f"    {name:26s} внутри {val['contained']:5d}  "
                  f"НЕ содержит {val['not_contained']:4d}  "
                  f"макс {val['max_excess_mm']:9.1f} мм")
        d = r["non_containing_diagnosis"]
        print(f"  нарушений: {d['count']} — оси {d['axis_of_excess']}, "
              f"кривые {d['curve_kind']}")
        print(f"  проверено стен: {r['coverage']['judged']} из "
              f"{r['coverage']['denominator']} "
              f"(пропущено {r['coverage']['skipped_no_data']})")
        print(f"  ЗАМОК: {'ОТКРЫТ — билдер можно писать' if r['gate_open'] else 'ЗАКРЫТ'}")
    print(f"\nнаписан {out}")
    # 🔴 THREE OUTCOMES — THREE CODES (F-323). Previously `main` always
    # returned `0`: even an honest lock refusal was invisible to the caller,
    # meaning the lock could not be put into a pipeline at all. `1` — "the
    # measurement happened, violations were found" (fix the formula); `2` —
    # "there was no measurement" (take a different decompile). The same
    # ladder as in `snapshot_janitor._verify_all` (`75220fb`) and
    # `bundle_containment_gate`.
    live = [r for r in rows if not r.get("error")]
    if not live or any(r.get("error") or r.get("empty_evidence") for r in rows):
        return 2
    return 0 if all(r["gate_open"] for r in live) else 1


if __name__ == "__main__":
    raise SystemExit(main())
