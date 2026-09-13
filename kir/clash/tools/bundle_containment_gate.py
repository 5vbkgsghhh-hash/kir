"""THE sections LOCK GATE: does the DECLARED hull contain the real body.

    PYTHONPATH=. venv/bin/python -m kir.clash.tools.bundle_containment_gate <run> [...]

WHAT THIS MEASURES AND HOW IT DIFFERS FROM `wall_prism_gate`. That one checks
a formula assembled from EXTRACTED decompile parameters (L0), and stumbled on
the ambiguity of `WALL_BASE_OFFSET`. Here what is checked is what will
actually go into the search: L0 -> lift -> materialize -> KIR PROGRAMS ->
`clash_bundle.bundle_elements` -> `hulls.build_hull`. The program declares the
elevation, height, and type itself, so it has no Z-extent ambiguity at all.

WHERE THE TYPE'S CROSS-SECTION COMES FROM OFFLINE. The live path reads it
from the type at the ground stage (`WallType.Width`,
`CompoundStructure.GetWidth`, `FamilySymbol.get_BoundingBox`). All saved
decompiles were taken BEFORE the sections wave, and they cannot be re-taken
without a live Revit. So here the same quantity is reconstructed from the
REAL elements of the same document and is accepted ONLY as constant per type:
a type whose instances disagree is not a fact about the type. The
reconstruction gives an ESTIMATE of the body count; what is proved here is
something else — the containment check, and it does not depend on the
reconstruction method.

THE EXTERNAL WITNESS. The hull is checked against the Revit bounding box of
the same element from L0. The bounding box comes from the live geometry of
the model, so this is a check of the conservativeness law against an
external witness, not a formula checked against itself.

THE LOCK'S RULE (the same as for `wall_prism_gate`): zero violations across
the whole sample opens the source; any nonzero number is a refusal.

MEASUREMENT 09.08.2026, `snowdon_plumb_v5` (11 069 elements, 22 programs):

    OST_Floors/profile   111 checked, 0 violations
    OST_Columns/bbox      11 checked, 0 violations
    OST_Walls/prism      787 checked, 360 violations, up to 5283 mm outward
                         (along the axis 409/800 — abutments; across it 93/800 —
                          the body is wider than its own `WallType.Width`)

That is why `OST_Walls` stands on the bounding box, while the slab and the
column do not.
"""
from __future__ import annotations

import collections
import dataclasses
import json
import os
import pathlib
import sys
from typing import Any
from kir import env  # noqa: E402
# 🔴 THE IMPORT IS MODULE-LEVEL, NOT LOCAL (F-314, 29.08.2026). A local import
# of the same name inside a function SHADOWS the module-level one, and a fix
# to the module-level one silently fails to reach inside: this shape was
# ALREADY a defect in a neighboring instrument and was removed on 28.08
# (`wall_prism_gate.analyse`). The removed shape must not be repeated.
from kir.model.snapshot_io import open_snapshot, snapshot_file_exists

#: Category -> snapshot pool, where the cross-section of its type is put.
_POOL = {
    "OST_Walls": "wall_types",
    "OST_Floors": "floor_types",
    "OST_Ceilings": "ceiling_types",
    "OST_Roofs": "roof_types",
    "OST_Columns": "column_symbols_architectural",
    "OST_StructuralColumns": "column_symbols_structural",
}

#: Rounding noise of the mm grid: L0 and the program store the same
#: coordinates via different paths. 1 mm is the step of the grid itself, not
#: "a small amount".
_NOISE_MM = 1.0

#: The decompile store. It is not in the working tree (0.5 GB per building),
#: and the absolute path of the run is accepted as-is. Silently returning "no
#: runs" is not allowed: it would read as "zero violations".
#:
#: ~~"the run name is looked for nearby first, then ON PROD"~~ — a wording
#: valid before the 27.08.2026 split and left as evidence: "on prod" meant a
#: literal path into the owner's tree, hardcoded into the package that is
#: published separately.
#: 🔴 BOTH STORES WERE GUESSED, AND BOTH MISSED AFTER THE SPLIT (27.08.2026).
#: The first was counted as STEPS UPWARD and after the split gives
#: `/opt/kir/backend/data`, which does not exist; the second was a literal
#: path into the owner's tree — in a package under Apache-2.0, meaning an
#: unrelated person doesn't have it either. Two nonexistent candidates in a
#: row produced `SystemExit` with two made-up addresses: a refusal naming the
#: wrong cause sends the author to fix what is not broken.
#:
#: We ask the installation (`install_paths`) — the same authority as the
#: other eight consumers — plus an explicit variable for the store that lies
#: outside the installation (0.5 GB per building; it is normally kept
#: separately).
_CORPUS_ENV = "KIR_DECOMPILE_DATA"


def _roots() -> tuple[pathlib.Path, ...]:
    out: list[pathlib.Path] = []
    named = (env.get(_CORPUS_ENV) or "").strip()
    if named:
        out.append(pathlib.Path(named))
    from kir.install_paths import install_data_path
    owned = install_data_path("decompile")
    if owned is not None:
        out.append(owned)
    return tuple(out)


def _resolve(run: str) -> pathlib.Path:
    candidate = pathlib.Path(run)
    if candidate.is_dir():
        return candidate
    roots = _roots()
    if not roots:
        # An empty candidate list and "searched, did not find" are DIFFERENT
        # facts, and previously they arrived as a single refusal (form 4).
        raise SystemExit(
            f"склад разборов не адресуется: {_CORPUS_ENV} не задана и "
            "установка не названа. СЛЕДУЮЩИЙ ХОД: задай "
            f"{_CORPUS_ENV} каталогом склада либо KIR_INSTALL_ROOT установкой, "
            "либо передай абсолютный путь прогона.")
    for root in roots:
        if snapshot_file_exists(root / run / "L0.jsonl"):
            return root / run
    raise SystemExit(
        f"разбор {run!r} не найден ни в одном из складов: "
        + ", ".join(str(root) for root in roots))


def _bbox(el: dict) -> tuple[list[float], list[float]] | None:
    lo, hi = el.get("bbox_min_mm"), el.get("bbox_max_mm")
    if not (isinstance(lo, list) and isinstance(hi, list)
            and len(lo) == 3 and len(hi) == 3):
        return None
    return [float(c) for c in lo], [float(c) for c in hi]


def read_l0(run_dir: pathlib.Path) -> tuple[dict[str, float], list[dict]]:
    levels: dict[str, float] = {}
    elements: list[dict] = []
    # 🔴 READ BY THE SAME LAW BY WHICH IT WAS ACCEPTED (F-314, 29.08.2026).
    # `_resolve` judges whether a decompile exists via `snapshot_file_exists`,
    # which DELIBERATELY accepts `L0.jsonl.gz`: the janitor compresses
    # cooled-off decompiles IN PLACE, and the store (0.5 GB per building)
    # cools off by construction. A bare `open` immediately dropped a
    # `FileNotFoundError` exactly on the very input that the line above
    # declared found — meaning a legitimate archived decompile was
    # UNCHECKABLE by the gate AT ALL. Not `read_snapshot_text`: L0 can be
    # 13-47 MB raw, and it is read LINE BY LINE.
    with open_snapshot(run_dir / "L0.jsonl", "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("record") == "header":
                for level in (row["document"].get("levels") or []):
                    levels[str(level["id"])] = float(level["elevation_mm"])
            elif row.get("record") == "element":
                elements.append(row["element"])
    return levels, elements


def derive_sections(levels: dict[str, float],
                    elements: list[dict]) -> tuple[dict, dict[str, int]]:
    """Type cross-sections reconstructed from instances. See the header."""
    width: dict = collections.defaultdict(set)
    xsec: dict = collections.defaultdict(set)
    thick: dict = collections.defaultdict(set)
    plan: dict = collections.defaultdict(set)
    local_z: dict = collections.defaultdict(set)
    names: dict = {}
    for el in elements:
        category, type_id = el.get("category"), el.get("type_id")
        if category not in _POOL or not type_id:
            continue
        key = (category, str(type_id))
        names[key] = el.get("type_name") or ""
        params = el.get("params") or {}
        box = _bbox(el)
        if category == "OST_Walls":
            if "WALL_ATTR_WIDTH_PARAM" in params:
                width[key].add(round(float(params["WALL_ATTR_WIDTH_PARAM"]), 3))
            if "WALL_CROSS_SECTION" in params:
                xsec[key].add(int(float(params["WALL_CROSS_SECTION"])))
        elif category in ("OST_Floors", "OST_Ceilings", "OST_Roofs"):
            if box is not None:
                thick[key].add(round(box[1][2] - box[0][2], 1))
        elif box is not None:
            plan[key].add((round(box[1][0] - box[0][0], 1),
                           round(box[1][1] - box[0][1], 1)))
            base = levels.get(str(el.get("level_id")))
            offset = params.get("FAMILY_BASE_LEVEL_OFFSET_PARAM")
            top_level = params.get("FAMILY_TOP_LEVEL_PARAM")
            if base is None or offset is None:
                continue
            if top_level is not None and str(top_level) in levels:
                z0 = base + float(offset)
                local_z[key].add((round(box[0][2] - z0, 1),
                                  round(box[1][2] - z0, 1)))

    snapshot: dict[str, list] = collections.defaultdict(list)
    report: collections.Counter = collections.Counter()
    for key, name in sorted(names.items()):
        category, type_id = key
        # 🔴 THE TYPE ID IS A STRING (E-9, 29.08.2026). See the explanation at
        # `levels` below: `int()` drops the gate on a legitimate non-numeric
        # id, while the consumer
        # (`clash_bundle.SnapshotSections.from_snapshot`) builds the key with
        # the f-string `f"element_id:{row['id']}"` — for a numeric id the key
        # text is identical, verified by execution.
        row: dict[str, Any] = {"id": str(type_id), "name": name}
        if category == "OST_Walls":
            widths, sections = width[key], xsec[key]
            if len(widths) != 1:
                report[f"{category}:width_not_constant_per_type"] += 1
            elif len(sections) != 1:
                report[f"{category}:cross_section_not_constant"] += 1
            else:
                section = {"kind": "plate", "source": "WallType.Width",
                           "thickness_mm": sorted(widths)[0]}
                if sections == {1}:              # 1 == Vertical (measured 27.07)
                    section["uniform"] = True
                else:
                    section["blockers"] = [
                        f"wall_cross_section_{sorted(sections)[0]}"]
                row["section"] = section
                report[f"{category}:derived"] += 1
        elif category in ("OST_Floors", "OST_Ceilings", "OST_Roofs"):
            thicknesses = {t for t in thick[key] if t > 0}
            if len(thicknesses) != 1:
                report[f"{category}:thickness_not_constant_per_type"] += 1
            else:
                row["section"] = {
                    "kind": "plate",
                    "source":
                        "HostObjAttributes.GetCompoundStructure().GetWidth",
                    "thickness_mm": sorted(thicknesses)[0], "uniform": True}
                report[f"{category}:derived"] += 1
        else:
            plans = {p for p in plan[key] if p[0] > 0 and p[1] > 0}
            zs = local_z[key]
            if len(plans) != 1:
                report[f"{category}:plan_section_not_constant"] += 1
            elif len(zs) != 1:
                report[f"{category}:local_z_not_constant"] += 1
            else:
                w, h = sorted(plans)[0]
                z_lo, z_hi = sorted(zs)[0]
                row["section"] = {
                    "kind": "rect",
                    "source": "STRUCTURAL_SECTION_COMMON_WIDTH+HEIGHT",
                    "width_mm": w, "height_mm": h, "uniform": True,
                    "local_z_min_mm": z_lo, "local_z_max_mm": z_hi}
                report[f"{category}:derived"] += 1
        snapshot[_POOL[category]].append(row)
    # 🔴 THE LEVEL ID IS A STRING (E-9, 29.08.2026). `LevelInfo.id: str` is
    # only checked by the language for non-emptiness, while in a federated
    # model an element's address has the form `<model>::<id>`
    # (`existing.SOURCE_SEPARATOR`), meaning non-numeric ids are the NORM,
    # not corruption. `int(lid)` drops the gate on a legitimate input, and
    # drops it BEFORE the verdict: the instrument does not say "did not
    # check", it never reaches a word at all, and in the pipeline this is
    # indistinguishable from an environment crash.
    #
    # The consumer is verified by EXECUTION, not by reasoning:
    # `clash_bundle.SnapshotSections.from_snapshot` builds the key with an
    # f-string (`f"element_id:{row['id']}"`), so for a numeric id the index
    # comes out IDENTICAL — `{'element_id:1': 0.0, 'name:1': 0.0}` in both
    # forms.
    snapshot["levels"] = [
        {"id": str(lid), "name": str(lid), "elevation_mm": elevation}
        for lid, elevation in sorted(levels.items())]
    return dict(snapshot), dict(sorted(report.items()))


def materialise(run_dir: pathlib.Path) -> list[dict]:
    """L0 -> lift -> materialize -> KIR programs (without Revit and without the bridge)."""
    # 🔴 IT USED TO BE `parents[3]` FROM THIS FILE — correct exactly for the
    # current depth of `kir/clash/tools/`. Move the instrument one level and
    # the path drifts SILENTLY, and `import kir` will pick up a foreign
    # package or none at all. This exact shape brought down the sandbox
    # (`f518b05`) and `install_paths` (six feeds went silent). The package is
    # already imported — its own location is the authority.
    import kir as _kir_pkg
    sys.path.insert(
        0, str(pathlib.Path(_kir_pkg.__file__).resolve().parent.parent))
    from kir.decompile import lift, materialize
    from kir import ports
    _gate = ports.need(ports.OFFLINE_GATE)
    _load_envelope = _gate._load_envelope
    _load_side_index = _gate._load_side_index
    load_document = _gate.load_document

    document, elements = load_document(run_dir)
    result = lift.lift_document_detailed(
        dataclasses.replace(document, elements=elements),
        _load_side_index(run_dir, "sketch.index.json", "sketch_index"),
        _load_envelope(run_dir, "family_placement.index.json"),
        wall_curve_index=_load_side_index(
            run_dir, "curve.index.json", "curve_index"),
        curtain_index=_load_envelope(run_dir, "curtain.index.json"),
        annotation_index=_load_envelope(run_dir, "annotation.index.json"),
        tag_index=_load_envelope(run_dir, "tag.index.json"),
        mep_system_index=_load_envelope(run_dir, "mep_system.index.json"))
    leaves = [node for node in result.nodes if isinstance(node, dict)]
    return list(materialize.leaves_to_program(
        leaves, chunk_target=250).programs)


def gate(run: str) -> dict:
    from kir.clash import snapshot as _snapshot
    from kir import clash_bundle as _bundle

    run_dir = _resolve(run)
    levels, elements = read_l0(run_dir)
    real = {str(el.get("element_id")): _bbox(el)
            for el in elements if _bbox(el) is not None}
    sections, derivation = derive_sections(levels, elements)
    programs = json.loads(json.dumps(materialise(run_dir), default=str))

    geometry = _bundle.bundle_elements(programs, snapshot=sections)
    snap = _snapshot.build_from_elements(
        geometry.elements,
        origin={"source": "bundle-containment-gate", "run_dir": run_dir.name},
        profiles=geometry.profiles)

    checked: collections.Counter = collections.Counter()
    violations: collections.Counter = collections.Counter()
    worst: dict[str, float] = collections.defaultdict(float)
    unjoined = 0
    for record in snap.records:
        tail = record.source_id.rsplit("/", 1)[-1]
        box = (real.get(tail[1:])
               if tail.startswith("e") and tail[1:].isdigit() else None)
        if box is None:
            unjoined += 1
            continue
        key = f"{record.category}/{record.hull_source}"
        checked[key] += 1
        hull_lo, hull_hi = record.hull.bounds()
        out = max([0.0] + [max(hull_lo[k] - box[0][k], box[1][k] - hull_hi[k])
                           for k in range(3)])
        if out > _NOISE_MM:
            violations[key] += 1
            worst[key] = max(worst[key], out)
    total_checked = sum(checked.values())
    # 🔴 A FLOOR OF NON-EMPTINESS (F-315, 29.08.2026). The lock's rule in the
    # header reads "zero violations ACROSS THE WHOLE SAMPLE" — that is a claim
    # about TWO numbers, but the decision was made on one:
    # `"PASS" if not violations`. An empty `violations` means success only
    # when at least one body was actually compared against the Revit bounding
    # box. Three other kinds of emptiness gave the same green, and the
    # instrument became GREENER THE FEWER CLUES IT HAD: not a single program
    # · zero bodies · not a single body matched by `source_id`.
    #
    # Three texts, not one flag: their next turn is DIFFERENT. "No programs" —
    # the wrong decompile or a lift refusal; "zero bodies" — a
    # `bundle_elements` refusal, already broken down into `no_geometry`; "did
    # not match" — a source address of the wrong shape, a JOINT defect, not a
    # building one. One flag would send the author to fix the wrong thing.
    # The shape is taken from `snapshot_janitor._verify_all` (commit
    # `75220fb` of the same shift): the cause is printed FIRST, before the
    # numbers, and the tree's gates answer emptiness THE SAME WAY — the
    # operator learns the behavior of one and carries it over to the others.
    #
    # There is deliberately no threshold on the SHARE checked: the 09.08
    # measurement on `snowdon_plumb_v5` names the bodies checked, but does not
    # name how many of them did not match — any threshold number would have
    # been assigned without an incident. The share IS DECLARED
    # (`checked_total`/`bodies`/`unjoined`), and the only thing that decides
    # is the boundary "the comparison happened at all".
    empty: str | None = None
    if not programs:
        empty = ("materialize не дал ни одной программы: сравнивать нечего. "
                 "СЛЕДУЮЩИЙ ХОД: проверь, что разбор несёт элементы и что "
                 "lift не отказал целиком")
    elif not snap.records:
        empty = (f"{len(programs)} программ дали НОЛЬ тел; отказы по телу: "
                 f"{dict(geometry.no_geometry)}")
    elif total_checked == 0:
        empty = (f"{len(snap.records)} тел построено, но НИ ОДНО не сошлось с "
                 f"элементом L0 по source_id (unjoined={unjoined}): свидетеля "
                 f"нет, закон консервативности не проверялся")
    return {
        "run": run_dir.name,
        "programs": len(programs),
        "bodies": len(snap.records),
        "derivation": derivation,
        "checked": dict(sorted(checked.items())),
        "checked_total": total_checked,
        "violations": dict(sorted(violations.items())),
        "worst_mm": {k: round(v, 1) for k, v in sorted(worst.items())},
        "unjoined": unjoined,
        "no_geometry": dict(sorted(geometry.no_geometry.items(),
                                   key=lambda kv: (-kv[1], kv[0]))),
        "empty_evidence": empty,
        "gate": "FAIL" if (violations or empty) else "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    runs = list(argv or sys.argv[1:])
    if not runs:
        print(__doc__)
        return 2
    failed = empty = False
    for run in runs:
        row = gate(run)
        empty |= bool(row.get("empty_evidence"))
        failed |= row["gate"] == "FAIL" and not row.get("empty_evidence")
        print(f"== {row['run']}: программ {row['programs']}, "
              f"ТЕЛ {row['bodies']}")
        # 🔴 The cause is printed FIRST, BEFORE the numbers — the convention
        # of `snapshot_janitor._verify_all` (`75220fb`): the reader is stopped
        # by the header, not by a footnote under the table. Otherwise a
        # change to the verdict dies silently, left as a line in the tail.
        if row.get("empty_evidence"):
            print(f"   🔴 СВЕРКА НЕ СОСТОЯЛАСЬ: {row['empty_evidence']}")
        print(f"   вывод сечений: {row['derivation']}")
        print(f"   проверено:     {row['checked']}")
        print(f"   нарушений:     {row['violations'] or '—'}")
        print(f"   макс выход:    {row['worst_mm'] or '—'} мм")
        print(f"   без тела:      {row['no_geometry']}")
        print(f"   проверено тел: {row['checked_total']} из {row['bodies']} "
              f"(не сошлось {row['unjoined']})")
        print(f"   ЗАМОК: {row['gate']}")
    # 🔴 THREE OUTCOMES — THREE CODES (F-315). `1` means "the check DID
    # HAPPEN and found excursions beyond the bounding box" — go analyze the
    # violations; `2` means "the check DID NOT HAPPEN" — name a different
    # decompile or fix the source_id joint. Their next turn is different, and
    # the pipeline branches on the code: merging them would devalue the code
    # exactly where it is used to make the decision. The shape is taken from
    # `snapshot_janitor._verify_all` (`75220fb`), not invented anew — the
    # tree's three gates are required to answer emptiness THE SAME WAY.
    if empty:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
