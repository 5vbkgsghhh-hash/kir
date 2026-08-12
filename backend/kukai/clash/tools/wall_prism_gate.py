"""ВОРОТА ЗАМКА wall-prism: одна команда решает, можно ли писать билдер.

    PYTHONPATH=. venv/bin/python -m kukai.clash.tools.wall_prism_gate <прогон> [...]

Метод. Предсказанная призма проверяется на СОДЕРЖАНИЕ габарита Revit у тех
стен, у которых габарит ЕСТЬ. Габарит приходит из настоящей геометрии модели,
поэтому это проверка закона консервативности против ВНЕШНЕГО свидетеля, а не
сверка формулы с собой. Замер 29.07 на v18: лучший вариант формулы оставлял
15–24 нарушения из 1 752 при максимуме 1 785 мм наружу — билдер не отгружен.

**Ноль нарушений на всей выборке = замок открывается.** Любое ненулевое число —
отказ, и он печатается вместе с разложением по причинам.

Числа без манифеста не публикуются: коммит кода, sha входов, отпечаток ревизии.
"""
from __future__ import annotations

import collections
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time

from kukai.clash import hulls as H
from kukai.clash.hulls import _valid_box

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[3]
ROOT = BACKEND_ROOT / "data" / "decompile"
ART = pathlib.Path(
    os.environ.get("KIR_CLASH_ARTIFACTS", str(BACKEND_ROOT / "artifacts"))
)


def _git(*a: str) -> str:
    return subprocess.run(["git", "-C", "/opt/kukai-rebuild1", *a],
                          capture_output=True, text=True).stdout.strip()


def _p(el: dict, key: str):
    return (el.get("params") or {}).get(key)


def _read(run_dir: pathlib.Path):
    levels: dict[str, float] = {}
    no_box: list[dict] = []
    with_box: list[dict] = []
    with (run_dir / "L0.jsonl").open(encoding="utf-8") as f:
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
    if cv.exists():
        curves = json.loads(cv.read_text(encoding="utf-8")).get("curve_index") or {}
    return no_box, with_box, levels, curves


def _z_span(el: dict, levels: dict[str, float], mode: str) -> tuple[float, float]:
    """Вертикальный размах стены. Замер v19 продиктовал СОЮЗ трактовок.

    `WALL_BASE_OFFSET` иногда уже учтён в отметке оси, иногда нет: на v19
    стена 9203306 без него промахивается на 4 300 мм, а стена 11444377 — С ним
    на 1 290 мм. Различить по данным нечем, поэтому берётся ОБЪЕДИНЕНИЕ обеих
    трактовок: огрубление вверх законно, догадка о том, какая из них верна, —
    нет.

    `WALL_HEIGHT_TYPE` — это id ВЕРХНЕГО УРОВНЯ присоединённой стены (замерено
    на v19: оба встреченных значения разрешаются в отметки заголовка). У такой
    стены реальная высота НЕ равна `WALL_USER_HEIGHT_PARAM`: у 8234565
    параметр 7 970 мм при настоящих 9 755 мм. Верх берётся по уровню плюс
    `WALL_TOP_OFFSET`; на всех семи Z-промахах v19 этого хватает.
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
    if not (w and h and p0 and p1):
        return None
    z0, z1 = _z_span(el, levels or {}, z_mode)
    hw = (H.wall_axis_halfwidth(w, _p(el, "WALL_KEY_REF_PARAM"))
          if use_key_ref else float(w))
    xs = [p0[0], p1[0]]
    ys = [p0[1], p1[1]]
    # Дуга: концы НЕ описывают то, что между ними. Ворота, предсказывающие
    # габарит по концам, промахиваются по построению — и это не свойство
    # стены, а дефект предсказания. Берём ту же ломаную, что чинит оболочку.
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
    if not (d / "L0.jsonl").exists():
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
        "gate_open": diag["count"] == 0,
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
                                     "backend/kukai/clash").splitlines(),
            "tool": "kukai.clash.tools.wall_prism_gate",
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
        print(f"  ЗАМОК: {'ОТКРЫТ — билдер можно писать' if r['gate_open'] else 'ЗАКРЫТ'}")
    print(f"\nнаписан {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
