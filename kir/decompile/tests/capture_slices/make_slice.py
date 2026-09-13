# -*- coding: utf-8 -*-
"""The SLICE cutter for captures: a small, real capture out of a large
corpus run.

🔴 WHY IT EXISTS — A NUMBER, NOT CONVENIENCE. Acceptance of the offline fix
ran on ONE run (`bench_A`, 8 MB) until 07.09.2026, because the corpus's
other valid runs weigh 95–700 MB and do not go into the repository. A rule
checked against one building is a rule fitted to one building: mandate F5
requires "checking several different captures, not fitting the rules to a
single bench".

A SLICE IS NOT A MADE-UP BUILDING. It takes REAL L0 lines from a real run
and discards the excess; not one value is invented or edited. What exactly
was discarded is named as a number in `SLICE.json` next to the slice: the
source run, its sha256, the seeds (door, opening, host), how many elements
were kept out of how many. The reader must be able to see that they are
holding a SLICE, not a building — so the label sits IN THE DIRECTORY
ITSELF, not in the name and not in a report.

🔴 WHAT A SLICE DOES NOT PROVE. It does not prove that the fix holds up on
a WHOLE building: it has dozens of neighbors, not thousands. It proves that
the rule is not tied to one building — and that is exactly what the mandate
requires. The full `bench_A` stays in the acceptance suite alongside the
slices and answers for scale.

Run it (the corpus is ONLY read):
    python -m kir.decompile.tests.capture_slices.make_slice \
        --run k4_geom_wave2 --out kir/decompile/tests/capture_slices/k4_geom_wave2
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import pathlib
import sys

#: The corpus of decompiles. Read, NEVER written.
CORPUS = pathlib.Path("/opt/kukai-rebuild1/backend/backend/data/decompile")
#: The side indexes that `capture_edit._SIDE` feeds to the lifter, plus the
#: ones a capture carries alongside. A slice filters THE SAME ONES, so as
#: not to drag along 1.2 MB of someone else's lines for the sake of one
#: door.
SIDE_FILES = ("family_placement", "curve", "curtain", "sketch", "group",
              "join", "annotation", "dimension", "tag", "mep_system")
#: What gets copied next to a slice whole: they are small and carry the run's IDENTITY.
WHOLE_FILES = ("revision.proof.json", "side_index.manifest.json")
SLICE_SCHEMA = "kir-capture-slice/1"


def _open(path: pathlib.Path):
    return (gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz"
            else path.open(encoding="utf-8"))


def _l0_path(run_dir: pathlib.Path) -> pathlib.Path:
    for name in ("L0.jsonl", "L0.jsonl.gz"):
        if (run_dir / name).exists():
            return run_dir / name
    raise SystemExit(f"{run_dir}: нет L0.jsonl")


def _side_payload(run_dir: pathlib.Path, name: str):
    for suffix in (".index.json", ".index.json.gz"):
        path = run_dir / f"{name}{suffix}"
        if path.exists():
            with _open(path) as handle:
                return path, json.load(handle)
    return None, None


#: The element fields that suffice for picking seeds and the closure.
#: NOTHING more is loaded into memory.
#:
#: 🔴 THIS IS NOT ECONOMY, IT IS A CONDITION FOR RUNNING AT ALL. The
#: corpus's valid runs weigh 95–700 MB (`k2_ar_rd_v7` — 700 MB, 115 889
#: elements). The first edition held the WHOLE stream as a list of dicts
#: and on a machine like this (2.3 GB free) would not have survived to the
#: slicing step. There are now TWO passes: the first takes a skeleton, the
#: second writes, and neither holds the building whole.
SKELETON_FIELDS = ("category", "host_id", "level_id", "type_id", "host_source")


def read_skeleton(run_dir: pathlib.Path) -> dict:
    """A skeleton of elements: address -> only reference fields and category."""
    out = {}
    with _open(_l0_path(run_dir)) as handle:
        for line in handle:
            if '"record"' not in line or '"element"' not in line:
                continue
            row = json.loads(line)
            if row.get("record") != "element":
                continue
            element = row["element"]
            out[str(element["element_id"])] = {
                name: element.get(name) for name in SKELETON_FIELDS}
    return out


def iter_records(run_dir: pathlib.Path):
    """L0 records in order, ONE AT A TIME. The header and footer are NOT lost."""
    with _open(_l0_path(run_dir)) as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def pick_seeds(elements: dict, profiles: dict) -> dict:
    """A door op and a SUPPORTED opening — a ring in the host slab's
    profile.

    🔴 "AN OPENING IN A SLAB" AND "AN OPENING THAT CAN BE EDITED" ARE
    DIFFERENT SETS, AND THIS IS A MEASUREMENT. The first edition of the
    cutter took any `OST_FloorOpening` with a slab host: `bench_A` has 27 of
    those, and all of them passed the filter. But editability is expressed
    by the SLAB'S CONTOUR (`opening_contour_mm` on the slab), and it exists
    only where `sketch.index.json` carried the ring through: of 128 profile
    lines, 100 carry only `profile_available`, and just 28 carry `holes`. A
    slice built on slab 287227 opened fine, but the slab in it came up as
    an ATOM, and there was nothing to edit. A seed must be the thing THAT
    GETS EDITED.
    """
    doors = [key for key, e in elements.items() if e.get("category") == "OST_Doors"]
    if not doors:
        raise SystemExit("в прогоне нет дверей — срез не о чем резать")
    hosts = []
    for key, payload in (profiles or {}).items():
        if not isinstance(payload, dict) or not payload.get("holes"):
            continue
        element = elements.get(str(key))
        if element is not None and element.get("category") in ("OST_Floors", "OST_Ceilings"):
            hosts.append(str(key))
    if not hosts:
        raise SystemExit("в прогоне нет плиты, чей профиль донёс кольцо отверстия")
    host = sorted(hosts)[0]
    opening = next((key for key in sorted(elements)
                    if "Opening" in str(elements[key].get("category") or "")
                    and str(elements[key].get("host_id")) == host), "")
    # The door taken is the ONE THAT HAS A HOST WALL: without a wall,
    # `create_door` does not compose, and the slice would give
    # `door_is_opaque_atom` instead of an edit.
    with_wall = [key for key in doors
                 if elements.get(str(elements[key].get("host_id")), {}
                                 ).get("category") == "OST_Walls"]
    door = sorted(with_wall or doors)[0]
    return {"door": door, "opening": opening, "opening_host": host,
            "door_host": str(elements[door].get("host_id") or "")}


#: How many wall openings a `wall_opening`-subject slice must carry. TWO,
#: not one: a rule checked on one opening is a rule fitted to one opening,
#: and "the neighboring opening is intact" on a slice with a single opening
#: is a claim about nothing.
WALL_OPENINGS_WANTED = 2


def pick_wall_opening_seeds(elements: dict, want: int = WALL_OPENINGS_WANTED) -> dict:
    """Openings IN WALLS and their host walls. The seed is the thing THAT
    GETS EDITED.

    🔴 THE SUBJECT HERE IS DIFFERENT, AND THIS IS NOT TASTE, IT IS A
    MEASUREMENT. An opening in a slab is edited as a RING in the inner loop
    of the HOST'S OWN sketch, and so the seed is the SLAB (`pick_seeds`
    above). An opening in a wall is a SEPARATE
    `Autodesk.Revit.DB.Opening` element with its own op
    `create_opening(wall_rect)` and its own two corners; the seed is THE
    OPENING ITSELF. Taking the slab here would mean cutting a slice about
    the wrong thing.

    Corpus runs carrying wall openings (census 08.09.2026 by ELEMENT
    records, not a line-based `grep`): `mnvnk_k1_layers` 120,
    `k4_geom_wave2` 51, `bench_A` 12 — 183 across three runs out of 93.
    """
    openings = []
    for key in sorted(elements):
        element = elements[key]
        if element.get("category") != "OST_SWallRectOpening":
            continue
        host = elements.get(str(element.get("host_id") or ""))
        # The host must EXIST AND BE A WALL: `create_opening(wall_rect)` cuts
        # `NewOpening(Wall, XYZ, XYZ)`, and an opening whose wall was left
        # outside the slice would give a refusal caused by the slice, not by
        # the building.
        if host is None or host.get("category") != "OST_Walls":
            continue
        openings.append(key)
    if len(openings) < want:
        raise SystemExit(
            f"в прогоне {len(openings)} проёмов стены с хозяином-стеной, "
            f"а срезу предмета wall_opening нужно {want}")
    picked = openings[:want]
    return {"wall_openings": picked,
            "wall_opening_hosts": [str(elements[key]["host_id"]) for key in picked]}


def _seed_addresses(seeds: dict) -> list:
    """All seed addresses as ONE list: the closure knows nothing about the
    subject's kind.

    🔴 SORTING SEEDS BY NAME HERE WOULD BE A SECOND PIECE OF KNOWLEDGE ABOUT
    THE SUBJECT. The first edition called `seeds["door"]`,
    `seeds["opening_host"]`, and so on, as a list of names: adding the
    `wall_opening` subject would have silently left its seeds OUTSIDE the
    closure — the slice would open, and the opening would not be in it.
    """
    out = []
    for value in seeds.values():
        for item in (value if isinstance(value, list) else [value]):
            if item:
                out.append(str(item))
    return out


def closure(elements: dict, seeds: dict, neighbours: int) -> set:
    """The reference closure plus a named number of neighbors.

    Neighbors are needed by the acceptance's SUBJECT: "the rest of the
    building is intact" on a slice with no neighbors is a claim about
    nothing. They are taken deterministically (by ascending address), so
    the slice is reproducible.
    """
    keep: set = set()
    queue = _seed_addresses(seeds)
    while queue:
        key = queue.pop()
        if key in keep or key not in elements:
            continue
        keep.add(key)
        element = elements[key]
        for field in ("host_id", "level_id", "type_id", "host_source"):
            value = element.get(field)
            if value is None:
                continue
            for item in (value if isinstance(value, list) else [value]):
                if str(item) in elements and str(item) not in keep:
                    queue.append(str(item))
    # ALL of the building's levels are kept: they are cheap, and without
    # them, a neighbor's attachment drifts, meaning the slice would measure
    # the wrong thing.
    for key, element in elements.items():
        if element.get("category") == "OST_Levels":
            keep.add(key)
    rest = sorted(set(elements) - keep, key=lambda k: (len(k), k))
    keep.update(rest[:neighbours])
    return keep


#: How an element's address is named in a side index's refusal line.
_ADDRESS_KEYS = ("element_id", "wall_id", "host_id", "floor_id", "id")


def _row_is_ours(row: dict, keep: set) -> bool:
    """Does a side index line belong to the slice? An addressless one does."""
    named = [str(row[name]) for name in _ADDRESS_KEYS if row.get(name) is not None]
    return not named or any(value in keep for value in named)


def filter_side(payload, keep: set):
    """Keep only the slice's lines in a side index. The file's shape does not change."""
    if not isinstance(payload, dict):
        return None, 0, 0
    out, kept, dropped = {}, 0, 0
    for name, value in payload.items():
        if name.endswith("_index") and isinstance(value, dict):
            picked = {k: v for k, v in value.items() if str(k) in keep}
            kept += len(picked)
            dropped += len(value) - len(picked)
            out[name] = picked
        elif name == "failures" and isinstance(value, list):
            # 🔴 AN ADDRESS IN A REFUSAL IS NAMED DIFFERENTLY, AND THIS IS A
            # MEASUREMENT. For `curtain`, a refusal line carries `wall_id`,
            # not `element_id`: filtering by one name left all 14 343
            # refusals about OTHER walls in the `k2v33_join2` slice — 1.5 MB
            # of talk about a building that is not in the slice.
            out[name] = [row for row in value
                         if not isinstance(row, dict) or _row_is_ours(row, keep)]
        else:
            out[name] = value
    return out, kept, dropped


#: The buckets of a cross-section receipt. The order is fixed, so the slice is reproducible.
_RECEIPT_BUCKETS = ("exception", "instance_hit", "no_value", "not_applicable",
                    "type_hit", "wrong_storage")


def _project_receipt(receipt: dict, count: int):
    """Narrow a receipt down to a subset — ONLY when it is not made up.

    🔴 THE CENSUS'S LAW (`model/schema.py`, `CategoryStatus._validate`)
    requires that the sum of every receipt's buckets equal
    `extracted_count`. A slice keeps only part of the elements, so receipts
    must add up ON THE SLICE, not on the source run. Fitting them
    "approximately" is exactly a made-up number.

    So there is one rule, and it is narrow: if a receipt's whole mass sits
    in ONE bucket, then for EVERY element of the category it is known which
    bucket it landed in, and narrowing to a subset invents nothing. If the
    mass is spread across several buckets, nothing is known about an
    INDIVIDUAL element, and such a receipt is DROPPED, not split
    proportionally. Measured on `bench_A`: 348 single-bucket receipts, 4
    multi-bucket ones — the four are dropped.
    """
    filled = [name for name in _RECEIPT_BUCKETS if receipt.get(name)]
    if len(filled) > 1:
        return None
    out = dict(receipt)
    for name in _RECEIPT_BUCKETS:
        out[name] = 0
    out[filled[0] if filled else "not_applicable"] = count
    return out


def _write_gz(path: pathlib.Path, text: str) -> None:
    """Compress DETERMINISTICALLY: two runs of the cutter must produce the
    same bytes.

    🔴 `gzip.open` PUTS A TIMESTAMP IN THE HEADER, and without `mtime=0` the
    same slice would give a DIFFERENT sha256 on every cut — and a capture's
    `source_sha256` is computed from the snapshot's bytes. A slice whose
    digest drifts is unfit for a fixture: the "the edit is tied to the
    snapshot" test would be checking a clock.
    """
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as handle:
            handle.write(text.encode("utf-8"))


def rewrite_stream(run_dir: pathlib.Path, skeleton: dict, keep: set,
                   path: pathlib.Path) -> dict:
    """Write a slice's L0 so that the CENSUS ADDS UP on it, and only it.

    🔴 WITHOUT THIS, A SLICE DOES NOT READ AT ALL, AND THIS IS A
    MEASUREMENT, NOT A WORRY. The first edition of the cutter discarded
    element lines and left `category_status` and the footer as is:
    `L0JSONLReader.materialize()` answered with
    `ExtractionProtocolError: category status extracted_count does not match
    streamed records`. The L0 stream carries ITS OWN census, and a slice
    must be an honest census of itself, not a clipping of someone else's.
    """
    by_category: dict = {}
    for key in keep:
        category = skeleton[key].get("category")
        by_category[category] = by_category.get(category, 0) + 1
    dropped_receipts = 0
    dropped_skips = 0
    kept_status = 0
    rewritten_status = 0
    elements_written = 0
    lines: list = []
    for record in iter_records(run_dir):
        kind = record.get("record")
        if kind == "element":
            if str(record["element"]["element_id"]) not in keep:
                continue
            elements_written += 1
        elif kind == "category_status":
            status = dict(record["status"])
            count = by_category.get(status.get("category"), 0)
            if count == status.get("extracted_count"):
                kept_status += 1
            else:
                rewritten_status += 1
                status["extracted_count"] = count
                if status.get("expected_count") is not None:
                    status["expected_count"] = count
                receipts = status.get("section_receipts")
                if isinstance(receipts, list):
                    picked = []
                    for receipt in receipts:
                        projected = _project_receipt(receipt, count)
                        if projected is None:
                            dropped_receipts += 1
                        else:
                            picked.append(projected)
                    status["section_receipts"] = picked
                skips = status.get("route_skipped")
                if isinstance(skips, list):
                    # 🔴 A ROUTE LINE MUST NOT BE FLIPPED FOR THE SAKE OF
                    # ADDING UP. The first edition set `skipped=0,
                    # audited=count` for everyone — and a line that said
                    # "name CUT OFF for all" started saying "name CHECKED
                    # for all". The census's law still added up, while the
                    # fact was replaced with its opposite. Only a line where
                    # the cut-off count is ZERO can be narrowed honestly:
                    # then it is known that every element was asked about.
                    picked = []
                    for row in skips:
                        if row.get("skipped"):
                            dropped_skips += 1
                            continue
                        picked.append(dict(row, skipped=0, audited=count))
                    status["route_skipped"] = picked
                record = dict(record, status=status)
        elif kind == "footer":
            record = dict(record, element_count=elements_written)
        lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
    _write_gz(path, "\n".join(lines) + "\n")
    return {"элементов_записано": elements_written,
            "категорий_без_правки": kept_status,
            "категорий_пересчитано": rewritten_status,
            "квитанций_снято_как_невыводимых": dropped_receipts,
            "строк_маршрута_снято_как_невыводимых": dropped_skips}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, help="имя прогона в корпусе")
    parser.add_argument("--out", required=True, help="каталог среза")
    parser.add_argument("--neighbours", type=int, default=60,
                        help="сколько соседей оставить сверх замыкания")
    parser.add_argument("--corpus", default=str(CORPUS))
    # 🔴 A SLICE'S SUBJECT IS PART OF ITS IDENTITY, NOT THE CUTTER'S TASTE.
    # An opening in a slab and an opening in a wall are two DIFFERENT
    # editing subjects (different elements, different ops, different
    # fields), and their seeds differ accordingly. The `floor_opening`
    # default is left exactly as it was: the four slices cut before
    # 08.09.2026 must reproduce BYTE-FOR-BYTE, or the
    # `test_a_slice_is_reproducible_from_the_corpus` guard would stop
    # guarding.
    parser.add_argument("--subject", choices=("floor_opening", "wall_opening"),
                        default="floor_opening",
                        help="что срез несёт: отверстие в плите или проём в стене")
    args = parser.parse_args(argv)

    run_dir = pathlib.Path(args.corpus) / args.run
    if not run_dir.is_dir():
        raise SystemExit(f"{run_dir}: прогона нет")
    out_dir = pathlib.Path(args.out)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"{out_dir}: каталог не пуст; срез не перезаписывает чужое")

    elements = read_skeleton(run_dir)
    _path, sketch = _side_payload(run_dir, "sketch")
    profiles = dict((sketch or {}).get("profile_index") or {})
    if args.subject == "wall_opening":
        seeds = pick_wall_opening_seeds(elements)
    else:
        seeds = pick_seeds(elements, profiles)
    keep = closure(elements, seeds, args.neighbours)

    out_dir.mkdir(parents=True, exist_ok=True)
    census = rewrite_stream(run_dir, elements, keep, out_dir / "L0.jsonl.gz")

    sides = {}
    for name in SIDE_FILES:
        path, payload = _side_payload(run_dir, name)
        if path is None:
            continue
        filtered, kept, dropped = filter_side(payload, keep)
        if filtered is None:
            continue
        _write_gz(out_dir / f"{name}.index.json.gz",
                  json.dumps(filtered, ensure_ascii=False, sort_keys=True) + "\n")
        sides[name] = {"kept": kept, "dropped": dropped}
    for name in WHOLE_FILES:
        if (run_dir / name).exists():
            (out_dir / name).write_text((run_dir / name).read_text(encoding="utf-8"),
                                        encoding="utf-8")

    source_sha = hashlib.sha256(_l0_path(run_dir).read_bytes()).hexdigest()
    (out_dir / "SLICE.json").write_text(json.dumps({
        "schema": SLICE_SCHEMA,
        "срез_чего": args.run,
        "предмет": args.subject,
        "корпус": str(args.corpus),
        "источник_L0_sha256": source_sha,
        "элементов_в_источнике": len(elements),
        "элементов_в_срезе": len(keep),
        "семена": seeds,
        "соседей_сверх_замыкания": args.neighbours,
        "боковые_индексы": sides,
        "перепись_среза": census,
        "чем_это_не_является": "срез не является зданием: соседей в нём десятки, "
                               "а не тысячи; он доказывает независимость правила от "
                               "одного прогона, а не масштаб",
    }, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"срез": str(out_dir), "элементов": len(keep),
                      "из": len(elements), "семена": seeds}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
