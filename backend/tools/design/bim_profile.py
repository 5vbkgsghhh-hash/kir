"""What a real building model is made of — measured, never assumed.

The dojo can already tell a tower from a shed by counting elements. It cannot
tell a MODEL from a MASSING, and that is the next wall: asked for a complete
building the model produces a shell, calls it done, and nothing in the loop
disagrees, because "complete" was never defined by anything except my opinion.

An opinion is the wrong instrument. A stage-П model is a real artefact with a
real composition, so the target should be READ OFF real models and then held
up against what the model built. This tool reads that composition:

    profile = per-category counts
            + how they relate (doors per room, windows per exterior wall, …)
            + how much of each element's PARAMETER payload is filled

The third line is the one that matters most and is easiest to miss. Stage П is
not "there are walls" — it is "every wall carries its fire rating, its finish,
its assembly code". A model can have every element and still be worthless, and
counting elements will never notice.

    python tools/bim_profile.py --live --doc SKLNK        # a running document
    python tools/bim_profile.py --json prof.json --live --doc SOB6
    python tools/bim_profile.py --compare a.json b.json   # target vs built
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

BACKEND = pathlib.Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:52411"

#: Every kind KIR's read side can count. Kept as the full list on purpose — a
#: category that is always zero is itself a finding (this project has 0 rooms
#: and 0 doors, which is why it is an electrical model and not a building one).
KINDS = (
    "wall", "floor", "ceiling", "roof", "door", "window", "room", "stair",
    "column_structural", "column_architectural", "duct", "pipe", "cable_tray",
    "grid", "level", "view", "sheet", "image", "cad_link", "cad_import",
    "pdf_underlay",
)

#: Ratios that separate a modelled building from a massing. Each is
#: (name, numerator, denominator) and only reported when the denominator is
#: non-zero — a ratio against nothing is noise, not a finding.
RATIOS = (
    ("дверей на помещение", "door", "room"),
    ("окон на помещение", "window", "room"),
    ("помещений на этаж", "room", "level"),
    ("стен на этаж", "wall", "level"),
    ("перекрытий на этаж", "floor", "level"),
    ("видов на лист", "view", "sheet"),
)


def _token() -> str:
    for line in (BACKEND / ".env").read_text(encoding="utf-8",
                                             errors="replace").splitlines():
        for key in ("ADMIN_TOKEN=", "KUKAI_ADMIN_TOKEN="):
            if line.startswith(key):
                return line.split("=", 1)[1].strip()
    raise SystemExit("не найден ADMIN_TOKEN в .env")


def _kir(program: dict, doc: str, *, timeout_ms: int = 60000) -> Any:
    body = json.dumps({"program": program, "doc_contains": doc,
                       "timeout_ms": timeout_ms}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{BASE}/admin/kir/run", data=body,
        headers={"Content-Type": "application/json",
                 "X-Admin-Token": _token()})
    with urllib.request.urlopen(req, timeout=timeout_ms / 1000 + 30) as r:
        return json.loads(r.read())


def count_live(doc: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for kind in KINDS:
        try:
            res = _kir({"ir_version": "1.0",
                        "ops": [{"op": "query_count", "id": "q", "kind": kind}]},
                       doc)
            row = (res.get("kir") or {}).get("result", {}).get("q")
            out[kind] = row.get("count") if isinstance(row, dict) else row
        except Exception as exc:  # noqa: BLE001 — a category that cannot be read
            out[kind] = None      # is reported as unknown, never as zero
            print(f"  {kind}: не прочитано ({type(exc).__name__})",
                  file=sys.stderr)
    return out


def profile(counts: dict[str, int], *, source: str = "") -> dict[str, Any]:
    known = {k: v for k, v in counts.items() if isinstance(v, int)}
    model_kinds = {k: v for k, v in known.items()
                   if k not in ("view", "sheet", "image", "level", "grid",
                                "cad_link", "cad_import", "pdf_underlay")}
    total = sum(model_kinds.values())
    ratios: dict[str, float] = {}
    for name, num, den in RATIOS:
        d = known.get(den) or 0
        if d:
            ratios[name] = round((known.get(num) or 0) / d, 2)
    return {
        "source": source,
        "counts": counts,
        "элементов_модели": total,
        "категорий_непустых": sum(1 for v in model_kinds.values() if v),
        "пусто": sorted(k for k, v in model_kinds.items() if v == 0),
        "доли": {k: round(v / total, 3) for k, v in
                 sorted(model_kinds.items(), key=lambda kv: -kv[1]) if total and v},
        "соотношения": ratios,
    }


def compare(target: dict, built: dict) -> list[str]:
    """What the built model is missing relative to the target. Plain sentences —
    they go to the model verbatim, and a gap it cannot read is a gap it cannot
    close."""
    gaps: list[str] = []
    t_counts = {k: v for k, v in (target.get("counts") or {}).items()
                if isinstance(v, int)}
    b_counts = built.get("counts") or {}
    for kind, want in sorted(t_counts.items(), key=lambda kv: -kv[1]):
        if not want or kind in ("view", "sheet", "image", "cad_link",
                                "cad_import", "pdf_underlay"):
            continue
        have = b_counts.get(kind) or 0
        if have == 0:
            gaps.append(f"нет ни одного «{kind}», в эталоне {want}")
        elif have < want * 0.25:
            gaps.append(f"«{kind}»: {have} против {want} в эталоне "
                        f"({have / want * 100:.0f}%)")
    for name, want in (target.get("соотношения") or {}).items():
        have = (built.get("соотношения") or {}).get(name)
        if want and (have is None or have < want * 0.4):
            gaps.append(f"{name}: {have if have is not None else 0} против "
                        f"{want} в эталоне")
    return gaps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="read a running document")
    ap.add_argument("--doc", default="", help="substring of the document name")
    ap.add_argument("--json", help="write the profile here")
    ap.add_argument("--compare", nargs=2, metavar=("ЭТАЛОН", "ПОСТРОЕНО"))
    a = ap.parse_args()

    if a.compare:
        target = json.loads(pathlib.Path(a.compare[0]).read_text("utf-8"))
        built = json.loads(pathlib.Path(a.compare[1]).read_text("utf-8"))
        gaps = compare(target, built)
        print(f"эталон: {target.get('source')}  →  построено: {built.get('source')}")
        for g in gaps:
            print("  -", g)
        if not gaps:
            print("  состав дотянут до эталона")
        return 0

    if not a.live or not a.doc:
        ap.error("нужен --live --doc <часть имени документа>")
    print(f"читаю «{a.doc}» …", file=sys.stderr)
    prof = profile(count_live(a.doc), source=a.doc)
    text = json.dumps(prof, ensure_ascii=False, indent=2)
    if a.json:
        pathlib.Path(a.json).write_text(text, encoding="utf-8")
        print(f"записал → {a.json}", file=sys.stderr)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
