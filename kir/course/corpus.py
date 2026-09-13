"""CORPUS MEASUREMENTS — the sole source of numbers for the course.

WHY A SEPARATE MODULE, AND NOT LITERALS IN PROSE. A course that says
"that's how it's done" is worse than no course at all: it sounds
authoritative and cannot be checked. Here every number sits RIGHT NEXT
TO HOW TO GET IT — the path to the parse, exactly what was counted, and
the function that will recompute it. `test_course.py` runs the recount
against real files when the corpus exists on the box, and declares a
skip when it does not: "no index" and "an empty index" are different
facts.

WHAT DOES NOT LIVE HERE. Not one judgment. A print run of 7.8 is a
measurement; "so, print more" is a lesson, and it lives in `lessons.py`,
where it is visible as a conclusion, not a fact.

THE UNIT OF MEASUREMENT IS THE BUILDING, NOT THE PARSE. There are 70
directories on disk, but those are versions: 19 parses of one facade, 9
of one tower. Counting by directory would give the facade nineteen
votes. So the course's corpus is ONE, the most complete parse per
building, and there are seven of them.
"""
from __future__ import annotations

import json
import os
from kir import env  # noqa: E402  (a submodule with no dependencies — introduces no cycle)
from dataclasses import dataclass
from typing import Any, Callable

#: The map of derivative categories is taken from acceptance. The import
#: is MODULE-LEVEL, not lazy: the "for free" lesson prints inside the
#: sandbox, where the import guard refuses anything not loaded ahead of
#: time.
from kir.acceptance import _OP_DERIVED  # noqa: E402
from kir.install_paths import install_data_path  # noqa: E402

#: The snapshot root. The same path `serving` reads
#: (`KUKAI_DECOMPILE_DATA`).
#:
#: 🔴 IT USED TO BE A QUADRUPLE `dirname` FROM THIS FILE, and after the
#: split it pointed into `/opt` — past everything. Counting STEPS UPWARD
#: is only correct for one exact layout: the sandbox burned on this same
#: shape (`f518b05`), and so did `install_paths`, where it cost six
#: silenced telemetry feeds and a pre-effect acceptance refusal. The
#: install root is asked of the ONE authority, and its silence has a
#: reason: `install_paths.install_root_refusal()`.
DECOMPILE_ROOT = env.get("KIR_DECOMPILE_DATA") or str(
    install_data_path("decompile") or "")

#: Seven buildings, one decompile per building — the most complete of the
#: versions. The section is named because the repetition method depends on
#: it (measurement: in ЭОМ there are NO groups AT ALL, and this is not
#: designer carelessness, but a different form of repetition).
BUILDINGS: dict[str, str] = {
    "k2_ar_rd_v9": "K2, жилая башня 59 этажей, АР",
    "демо-v3": "демо-v3, жилой дом 64 уровня, АР",
    "sob62_r23_v5": "СОБ6.2, детский сад, АР",
    "sob62_fas_r23_v19": "СОБ6.2, фасад (витражи)",
    "snowdon_plumb_v5": "Snowdon, ВК",
    "snowdon_elec_v1": "Snowdon, ЭОМ",
    "sklnk_eom_r26_v8": "Сколково, ЭОМ",
}


@dataclass(frozen=True)
class Measurement:
    """A number, its origin, and how to recompute it.

    `recompute` returns the same value from the files on disk. If it
    returns something other than what was recorded, it is the RECORD that
    diverges, not reality, and the test must fail loudly: a stale
    measurement in the course is indistinguishable from a fabrication.
    """

    key: str
    value: float
    unit: str
    what: str
    source: str
    recompute: Callable[[], float] | None = None

    def __str__(self) -> str:
        v = (f"{self.value:.0f}" if float(self.value).is_integer()
             else f"{self.value:.2f}")
        return f"{v} {self.unit}"


# ─────────────────────────────────────────────────────── reading snapshots

def _path(building: str, name: str) -> str:
    return os.path.join(DECOMPILE_ROOT, building, name)


def available(building: str) -> bool:
    # 🔴 BOTH HALVES FROM ONE HELPER. Three times this held the pair "asked
    # about presence accounting for compression — read with a bare `open`":
    # the check knew about `.gz`, the read did not, and the two shelves
    # covered each other's defects exactly until the first compressed
    # snapshot (21.08, FileNotFoundError on `k2_ar_rd_v9/group.index.json`).
    # We import BOTH and use both.
    from kir.decompile.snapshot_io import (open_snapshot,
                                                snapshot_file_exists)
    # The compressed snapshot is NOT absent: we ask the helper, not the FS.
    return snapshot_file_exists(_path(building, "L0.jsonl"))


def elements(building: str) -> dict[str, dict]:
    """L0 elements by id. Only records with `record == "element"`."""
    out: dict[str, dict] = {}
    # 🔴 WE READ WITH THE SAME HELPER WE USE TO ASK ABOUT PRESENCE. Before
    # 21.08 `available()` knew about compression, but the read itself did
    # not: the two shelves covered each other's defects, and the very first
    # compressed snapshot gave a FileNotFoundError exactly where the check
    # said "present".
    from kir.decompile.snapshot_io import open_snapshot
    with open_snapshot(_path(building, "L0.jsonl"), "rt",
                       encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            envelope = json.loads(line)
            if envelope.get("record") != "element":
                continue
            element = envelope.get("element") or {}
            eid = element.get("element_id")
            if eid:
                out[eid] = element
    return out


class SideIndex(dict):
    """A side index AND THE REASON FOR ITS ABSENCE in a single value.

    🔴 A BARE `{}` USED TO STAND HERE (F-247, 29.08.2026). `group_index`/
    `curtain_index` return an empty value for a missing file, and this
    response must not be dropped: the lesson must be composed even over an
    incomplete decompile. But the empty value rode into the numbers as
    ZERO — "no groups in the building", "no curtain walls in the
    building" — and was indistinguishable from a REAL zero. The companion
    `index_absent_reason` was written precisely for this, and it works; the
    trouble was that nothing on the live path called it, and the guard
    called it ONLY inside `if drift` — that is, exactly where a divergence
    already exists. A measurement recorded as zero and recomputed as zero
    FROM A MISSING INDEX gives no divergence, and the guard was green BY
    CONSTRUCTION.

    A `dict` SUBCLASS, NOT A NEW KIND. `SideIndex()` EQUALS `{}`, is falsy
    in a condition, works with `len`/`.get`/`json.dumps` and in a loop —
    meaning not one of today's readers (including OUTSIDE KIR:
    `/opt/kukai-rebuild1/backend/tools/design/examples/method_baseline.py`
    calls `corpus.group_definitions` directly) sees any difference. The
    reason TRAVELS ALONG WITH THE VALUE, rather than being asked for with a
    second call that is easy to forget — it has already been forgotten
    once, and that is the finding itself.
    """

    __slots__ = ("absent_reason",)

    def __init__(self, data: Any = None, *,
                 absent_reason: str | None = None) -> None:
        super().__init__(data or {})
        #: `None` — the index was read (even if empty). A string — it was
        #: NOT THERE, and a zero on this count means "did not read", not
        #: "none in the building".
        self.absent_reason = absent_reason


#: The side indexes the course takes its numbers from: file name -> reader.
#: Filled by the READERS THEMSELVES (`@_reads_side_index`), not typed up
#: separately: a list typed up in a second place is that very second
#: carrier, and it would diverge on the first new index. A new reader lands
#: in the `side_index_absences` check by construction, with nothing to add
#: by hand.
SIDE_INDEXES: dict[str, Callable[[str], "SideIndex"]] = {}


def _reads_side_index(filename: str):
    def register(fn):
        SIDE_INDEXES[filename] = fn
        return fn
    return register


def index_absent_reason(building: str, filename: str) -> str | None:
    """`None` if the side index is present; otherwise the REASON in words.

    🔴 COMPANION TO `group_index` and `curtain_index`. Both return `{}` for
    a missing file, and this answer must not be dropped: the lesson must be
    composed even over an incomplete decompile. But `{}` rides into the
    lesson's numbers as ZERO — "no groups in the building", "no curtain
    walls in the building" — and is indistinguishable from a real zero.

    The cost here is higher than usual: the course's numbers are read by
    the MODEL, and it reads them as measurements of real buildings. A zero
    recorded where the index was simply missing teaches it that groups and
    curtain walls are not used.

    Three outcomes are distinguished: the building does not exist at all,
    the building exists without this index, the index is present.
    """
    from kir.decompile.snapshot_io import snapshot_file_exists

    if not available(building):
        return (f"разбора «{building}» нет на этой машине — числа по нему "
                f"НЕ ПЕРЕСЧИТЫВАЛИСЬ; это факт о МАШИНЕ, а не о здании")
    if not snapshot_file_exists(_path(building, filename)):
        return (f"у разбора «{building}» нет {filename}: стадия не снималась "
                f"либо индекс удалён. Ноль по этому счёту означает «не "
                f"читали», а не «в здании нет»")
    return None


@_reads_side_index("group.index.json")
def group_index(building: str) -> SideIndex:
    # Locally — with the same argument as in `kir/clash/existing.py:load`:
    # the decoupling from `decompile` is deliberate, the class holds the
    # `scope_audit` ratchet.
    # 🔴 BOTH HALVES FROM ONE HELPER. Three times this held the pair "asked
    # about presence accounting for compression — read with a bare `open`":
    # the check knew about `.gz`, the read did not, and the two shelves
    # covered each other's defects exactly until the first compressed
    # snapshot (21.08, FileNotFoundError on `k2_ar_rd_v9/group.index.json`).
    # We import BOTH and use both.
    from kir.decompile.snapshot_io import (open_snapshot,
                                                snapshot_file_exists)

    path = _path(building, "group.index.json")
    if not snapshot_file_exists(path):
        return SideIndex(absent_reason=index_absent_reason(
            building, "group.index.json"))
    with open_snapshot(path, "rt", encoding="utf-8") as handle:
        return SideIndex(json.load(handle).get("group_index") or {})


@_reads_side_index("curtain.index.json")
def curtain_index(building: str) -> SideIndex:
    # Locally — with the same argument as in `kir/clash/existing.py:load`:
    # the decoupling from `decompile` is deliberate, the class holds the
    # `scope_audit` ratchet.
    # 🔴 BOTH HALVES FROM ONE HELPER. Three times this held the pair "asked
    # about presence accounting for compression — read with a bare `open`":
    # the check knew about `.gz`, the read did not, and the two shelves
    # covered each other's defects exactly until the first compressed
    # snapshot (21.08, FileNotFoundError on `k2_ar_rd_v9/group.index.json`).
    # We import BOTH and use both.
    from kir.decompile.snapshot_io import (open_snapshot,
                                                snapshot_file_exists)

    path = _path(building, "curtain.index.json")
    if not snapshot_file_exists(path):
        return SideIndex(absent_reason=index_absent_reason(
            building, "curtain.index.json"))
    with open_snapshot(path, "rt", encoding="utf-8") as handle:
        return SideIndex(json.load(handle).get("curtain_index") or {})


def side_index_absences(building: str) -> list[str]:
    """REASONS in words for ALL side indexes of the course. Empty means all
    present.

    The list is taken from `SIDE_INDEXES`, i.e. from the readers
    themselves: asking "what indexes even exist" as a second enumeration
    would mean starting a pair that would diverge (F-247, and this is
    exactly the same class as F-190).

    The live path that was missing: today the reason existed, was correct,
    and WAS CALLED FROM NOWHERE except one test branch that only ever sees
    numbers that have already diverged.
    """
    out: list[str] = []
    for filename in SIDE_INDEXES:
        why = index_absent_reason(building, filename)
        if why is not None:
            out.append(why)
    return out


# ────────────────────────────────────────────────── recompute over decompiles

def count_elements(building: str) -> float:
    return float(len(elements(building)))


def count_types(building: str) -> float:
    """Distinct (category, type) pairs. Type is the FIRST level of a
    repeating unit: it lives in the model and is edited once for all its
    elements."""
    return float(len({(e.get("category"), e.get("type_id"))
                      for e in elements(building).values()}))


def group_definitions(building: str) -> float:
    return float(len(group_index(building).get("definitions") or {}))


def top_level_instances(building: str) -> float:
    """TOP-level placements. Nested ones (`group_id_parent`) are excluded:
    they have neither an origin nor a level binding, and counting them as
    independent placements would inflate the replication count."""
    instances = group_index(building).get("instances") or {}
    return float(sum(1 for row in instances.values()
                     if not row.get("group_id_parent")))


def reused_definitions(building: str) -> float:
    """Definitions placed MORE THAN ONCE. A definition with a single
    occurrence is not a replicated run, just a named set."""
    instances = group_index(building).get("instances") or {}
    per: dict[Any, int] = {}
    for row in instances.values():
        if row.get("group_id_parent"):
            continue
        per[row.get("group_type_id")] = per.get(row.get("group_type_id"), 0) + 1
    return float(sum(1 for n in per.values() if n > 1))


def reused_definition_size(building: str) -> float:
    """Median number of members for a definition placed more than once.

    Answers "what SIZE does a replicated unit come in": a single element is
    replicated by type, while a whole floor is not replicated at all.
    """
    index = group_index(building)
    definitions = index.get("definitions") or {}
    instances = index.get("instances") or {}
    per: dict[Any, int] = {}
    for row in instances.values():
        if row.get("group_id_parent"):
            continue
        per[row.get("group_type_id")] = per.get(row.get("group_type_id"), 0) + 1
    sizes = sorted(len(definitions[gid].get("slots") or [])
                   for gid, count in per.items()
                   if count > 1 and gid in definitions)
    if not sizes:
        return 0.0
    mid = len(sizes) // 2
    return float(sizes[mid] if len(sizes) % 2
                 else (sizes[mid - 1] + sizes[mid]) / 2)


def grouped_share(building: str) -> float:
    """Share of L0 elements lying INSIDE some group, in percent.

    This is a LOWER bound: group members routinely belong to categories the
    L0 collector did not capture, and such a member does not enter the
    denominator at all. There is nothing here that could overstate it; it
    can understate it as much as you like.
    """
    els = elements(building)
    instances = group_index(building).get("instances") or {}
    members: set[str] = set()
    for row in instances.values():
        members.update(row.get("member_ids") or [])
    return round(100.0 * len(members & set(els)) / max(1, len(els)), 1)


def curtain_hosts(building: str) -> float:
    return float(sum(1 for row in curtain_index(building).values()
                     if isinstance(row, dict) and row.get("curtain_available")))


def _curtain_records(building: str):
    from kir.decompile.curtain_extract import CurtainWallRecord
    for host_id, row in curtain_index(building).items():
        if isinstance(row, dict) and row.get("curtain_available"):
            yield CurtainWallRecord.from_dict(host_id, row)


def curtain_mullions(building: str) -> float:
    return float(sum(len(r.mullions) for r in _curtain_records(building)))


def curtain_type_driven_pct(building: str) -> float:
    """Share of mullions that the HOST TYPE GIVES RISE TO, in percent.

    Computed by two independent Revit witnesses — `Mullion.Lock` and the
    mullion type matching the type-default for its direction
    (`curtain_extract.CurtainWallRecord.mullion_state`). The logic is not
    rewritten here: the same logic used by the reverse pass is called.
    """
    from kir.decompile.curtain_extract import MullionState
    total = driven = 0
    for record in _curtain_records(building):
        for mullion in record.mullions:
            total += 1
            if record.mullion_state(mullion) is MullionState.TYPE_DRIVEN:
                driven += 1
    return round(100.0 * driven / max(1, total), 1)


def curtain_authored_grid_lines(building: str) -> float:
    """Split lines that NEED to be authored: those the host type does not
    cut on its own (`GridLineState.TYPE_DRIVEN` excluded)."""
    from kir.decompile.curtain_extract import GridLineState
    n = 0
    for record in _curtain_records(building):
        for line in list(record.u_grid_lines) + list(record.v_grid_lines):
            if record.grid_line_state(line) is not GridLineState.TYPE_DRIVEN:
                n += 1
    return float(n)


def curtain_panels(building: str) -> float:
    return float(sum(len(r.panels) for r in _curtain_records(building)))


def derived_categories() -> dict[str, tuple[str, ...]]:
    """Category → ops, IN THE WAKE OF WHICH Revit produces it.

    THERE IS NO SECOND LIST HERE. The truth about this is already recorded
    in the acceptance chain (`acceptance._OP_DERIVED`), where it carries
    weight: the census does not check a derived category against anything,
    nor show it as "unexpected". A course that started its own list would
    diverge from acceptance on the very first new op — and would teach the
    model not to write what needs to be written.

    The name is private on purpose: this map has no public reader besides
    this lesson. The `test_course` test keeps it non-empty, so that a
    rename breaks the course loudly, not quietly.

    THE IMPORT IS NOT LAZY: this function executes INSIDE the sandbox (a
    "free" lesson), and there the import guard refuses any root outside the
    allow-list. Everything the lesson needs is loaded when the module is
    imported.
    """
    out: dict[str, list[str]] = {}
    for op_name, categories in _OP_DERIVED.items():
        for category in categories:
            out.setdefault(category, []).append(op_name)
    return {c: tuple(sorted(ops)) for c, ops in sorted(out.items())}


def derived_share(building: str) -> float:
    """Share of the model in derived categories, in percent."""
    els = elements(building)
    derived = derived_categories()
    n = sum(1 for e in els.values() if e.get("category") in derived)
    return round(100.0 * n / max(1, len(els)), 1)


def level_signatures(building: str) -> float:
    """Distinct floor SIGNATURES (a set of types without counts) per
    building.

    A signature is the set of (category, type) pairs of a level's
    elements. Matching signatures mean the floor is repeated, and the
    "typical floor" stops being a metaphor.
    """
    per: dict[str, set] = {}
    for element in elements(building).values():
        level = element.get("level_name")
        if not level:
            continue
        per.setdefault(level, set()).add(
            (element.get("category"), element.get("type_id")))
    return float(len({tuple(sorted(s)) for s in per.values()}))


def levels_with_elements(building: str) -> float:
    return float(len({e.get("level_name") for e in elements(building).values()
                      if e.get("level_name")}))


# ═════════════════════════════════════════════════════════════════════════
# RECORDED MEASUREMENTS (03.08.2026, prod box, python3.12)
# ═════════════════════════════════════════════════════════════════════════

def _m(key: str, value: float, unit: str, what: str, building: str,
       fn: Callable[[str], float] | None = None) -> Measurement:
    return Measurement(
        key=key, value=value, unit=unit, what=what,
        source=f"backend/data/decompile/{building}/ — {BUILDINGS[building]}",
        recompute=(lambda: fn(building)) if fn else None)


MEASUREMENTS: dict[str, Measurement] = {m.key: m for m in (
    # ── scale and type as the first repeating unit ──────────────────────
    _m("k2.elements", 115880, "элементов", "элементов L0",
       "k2_ar_rd_v9", count_elements),
    _m("k2.types", 638, "типов", "различных (категория, тип)",
       "k2_ar_rd_v9", count_types),
    _m("demo.elements", 90758, "элементов", "элементов L0",
       "демо-v3", count_elements),
    _m("demo.types", 165, "типов", "различных (категория, тип)",
       "демо-v3", count_types),
    _m("sklnk.elements", 19306, "элементов", "элементов L0",
       "sklnk_eom_r26_v8", count_elements),
    _m("sklnk.types", 47, "типов", "различных (категория, тип)",
       "sklnk_eom_r26_v8", count_types),

    # ── groups: replication count of the repeating unit ─────────────────
    _m("k2.group_defs", 367, "определений", "определений групп",
       "k2_ar_rd_v9", group_definitions),
    _m("k2.group_places", 2846, "постановок", "постановок верхнего уровня",
       "k2_ar_rd_v9", top_level_instances),
    _m("k2.group_reused", 176, "определений", "определений с тиражом > 1",
       "k2_ar_rd_v9", reused_definitions),
    _m("k2.grouped_share", 41.1, "%", "элементов внутри групп (нижняя граница)",
       "k2_ar_rd_v9", grouped_share),
    _m("plumb.group_defs", 14, "определений", "определений групп",
       "snowdon_plumb_v5", group_definitions),
    _m("plumb.group_places", 110, "постановок", "постановок верхнего уровня",
       "snowdon_plumb_v5", top_level_instances),
    _m("plumb.group_reused", 12, "определений", "определений с тиражом > 1",
       "snowdon_plumb_v5", reused_definitions),
    _m("k2.group_members", 11, "членов", "медиана членов у тиражируемого "
       "определения", "k2_ar_rd_v9", reused_definition_size),
    _m("plumb.group_members", 50.5, "членов", "медиана членов у тиражируемого "
       "определения", "snowdon_plumb_v5", reused_definition_size),
    _m("elec.group_defs", 0, "определений", "определений групп",
       "snowdon_elec_v1", group_definitions),
    _m("sklnk.group_defs", 0, "определений", "определений групп",
       "sklnk_eom_r26_v8", group_definitions),
    _m("kinder.group_defs", 1, "определение", "определений групп",
       "sob62_r23_v5", group_definitions),

    # ── curtain wall: three layers, of which two are authored ───────────
    _m("k2.curtain_hosts", 1000, "носителей", "стен с витражной сеткой",
       "k2_ar_rd_v9", curtain_hosts),
    _m("k2.curtain_lines", 2561, "линий", "линий разрезки, НЕ рождённых типом",
       "k2_ar_rd_v9", curtain_authored_grid_lines),
    _m("k2.curtain_mullions", 11091, "импостов", "импостов всего",
       "k2_ar_rd_v9", curtain_mullions),
    _m("k2.curtain_driven", 92.0, "%", "импостов, рождённых типом носителя",
       "k2_ar_rd_v9", curtain_type_driven_pct),
    _m("k2.curtain_panels", 5505, "панелей", "панелей витража",
       "k2_ar_rd_v9", curtain_panels),
    _m("fas.curtain_hosts", 393, "носителей", "стен с витражной сеткой",
       "sob62_fas_r23_v19", curtain_hosts),
    _m("fas.curtain_lines", 122, "линий", "линий разрезки, НЕ рождённых типом",
       "sob62_fas_r23_v19", curtain_authored_grid_lines),
    _m("fas.curtain_mullions", 1372, "импостов", "импостов всего",
       "sob62_fas_r23_v19", curtain_mullions),
    _m("fas.curtain_driven", 92.1, "%", "импостов, рождённых типом носителя",
       "sob62_fas_r23_v19", curtain_type_driven_pct),
    _m("fas.curtain_panels", 559, "панелей", "панелей витража",
       "sob62_fas_r23_v19", curtain_panels),

    # ── what Revit does on its own ───────────────────────────────────────
    _m("k2.derived", 18.4, "%", "модели в производных категориях",
       "k2_ar_rd_v9", derived_share),
    _m("fas.derived", 48.7, "%", "модели в производных категориях",
       "sob62_fas_r23_v19", derived_share),

    # ── floor as a unit: where repetition exists and where it does not ──
    _m("demo.levels", 64, "уровней", "уровней с элементами",
       "демо-v3", levels_with_elements),
    _m("demo.level_sigs", 23, "подписей", "различных наборов типов на уровне",
       "демо-v3", level_signatures),
    _m("sklnk.levels", 121, "уровней", "уровней с элементами",
       "sklnk_eom_r26_v8", levels_with_elements),
    _m("sklnk.level_sigs", 21, "подписей", "различных наборов типов на уровне",
       "sklnk_eom_r26_v8", level_signatures),
    _m("k2.levels", 58, "уровней", "уровней с элементами",
       "k2_ar_rd_v9", levels_with_elements),
    _m("k2.level_sigs", 41, "подписей", "различных наборов типов на уровне",
       "k2_ar_rd_v9", level_signatures),
    _m("kinder.levels", 7, "уровней", "уровней с элементами",
       "sob62_r23_v5", levels_with_elements),
    _m("kinder.level_sigs", 7, "подписей", "различных наборов типов на уровне",
       "sob62_r23_v5", level_signatures),
)}


def value(key: str) -> float:
    return MEASUREMENTS[key].value


def n(key: str) -> str:
    """The measurement's number as a string — for substitution into the
    lesson text.

    Thousands are separated by a space: "115 880" is read, "115880" is
    recomputed by eye, and a lesson that needs to be recomputed gets read
    diagonally.
    """
    return fmt(MEASUREMENTS[key].value)


def fmt(v: float) -> str:
    """A number for a human: an integer with digit grouping, a fraction
    with one decimal place.

    The digit-group separator is a NON-BREAKING space (U+00A0), and this is
    not pedantry: otherwise paragraph reflow in `lessons._reflow` tears
    "16 596" into "16" and "596" at the end of a line, and the number has
    to be pieced back together by eye.
    """
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", " ")
    return f"{v:.1f}"


def ratio(a: str, b: str) -> str:
    """The ratio of two measurements. Computed, not typed by hand: a
    derived number typed by hand is the first thing to diverge from its
    source."""
    return fmt(round(MEASUREMENTS[a].value / MEASUREMENTS[b].value, 1))


def percent(a: str, b: str) -> str:
    return fmt(round(100.0 * MEASUREMENTS[a].value / MEASUREMENTS[b].value))


# ═════════════════════════════════════════════════════════════════════════
# OUR OWN TRACE — what the course was written for
# ═════════════════════════════════════════════════════════════════════════

#: Measured 27.07, recorded in `ground.py:671` next to the fix that made
#: the op reachable: before it, `ground()` did not descend into `members`,
#: the emitter received a raw selector and failed with a bare KeyError, and
#: the advice that went out was "members must be pre-grounded" — advice
#: that failed in exactly the same way when followed.
GROUP_USES_IN_LIFTED_OPS = 0
LIFTED_OPS_MEASURED = 51_574

#: 🔴 REMEASURED 18.08.2026, AND THE CLAIM FLIPPED. Read this paragraph
#: first — below stands the retracted edition, left in as an example.
#:
#:     same file, 18.08       2372 live refusals, 63 distinct ops
#:     `create_group`          64 lines — 63 of them IN ONE DAY, 18.08
#:     refused for what        KIR-T001 44 · KIR-G101 16 · KIR-P005 4
#:                            (all reject_code=VALIDATION_FAILED)
#:
#: The earlier edition said "the op was not tried, rather than tried and
#: failed". Today EXACTLY THE OPPOSITE is true: it was tried 64 times, and
#: it failed on TYPES and GROUNDING, not on an absence of intent. This is
#: not a correction of a number, it is a change of subject: the course was
#: written around "the model does not group", and the model has started.
#:
#: 🔴 WHAT THIS MEASUREMENT DOES NOT ESTABLISH, AND THIS MATTERS MORE THAN
#: THE NUMBER ITSELF. All 2372 lines carry `source: kir`, but the admin
#: door `/admin/kir/run` writes to the very same place as live traffic.
#: Distinguishing "the model in prod started grouping" from "our own runs
#: on 18.08" CANNOT be done with this file — there is no field in the line
#: that names the door. The earlier edition did not make this distinction
#: either, and back then it did not matter (zero is zero through any
#: door); now it does. As long as the door is not named in the line, the
#: number says "the op was REQUESTED 64 times", and does NOT say by whom.
#:
#: Recompute — `test_course.test_our_own_trace_still_shows_zero_group_uses`.
#: RETRACTED: "Measurement of 03.08: 1453 live refusals, 25 distinct
#: requested ops, `create_group` NOT AMONG THEM EVEN ONCE" — the number was
#: correct on 03.08 and is not correct today; left named rather than
#: erased.
#: REMEASURED 24.08.2026 (third shift): 3735 live refusals, `create_group`
#: among the requested ops 84 times. The earlier pair 64/2372 outlived its
#: own fact by a week — and it did not turn red on its own, but on a run of
#: a neighboring test: the ratchet works, but it is asked rarely.
#:
#: 🟢 REMEASURED 26.08.2026 — AND THE CAVEAT ABOUT THE DOOR IS CLOSED BY A
#: MEASUREMENT, NOT LIFTED. Two earlier editions honestly wrote: "the line
#: does not name the DOOR, so the number says 'the op was REQUESTED N
#: times' and does NOT say by whom." Now it does say. Split by `query_id`
#: (prefix `admin-kir-` = our direct door, everything else = chat):
#:
#:     TOTAL live refusals 3953, window 16.07 → 26.08
#:     `create_group` requested 94 times:
#:         CHAT (MODEL)            0   ← ZERO
#:         ADMIN (our own runs)   38
#:         UNDISTINGUISHED        56   lines predating `query_id`
#:     by day: 18.08 — 63 · 24.08 — 20 · 25.08 — 10 · 14.08 — 1
#:
#: 🔴 WHAT THIS CHANGES IN READING THE NUMBER. The entire rise 64 → 84 → 94
#: is OUR OWN runs; the model through chat has NEVER called `create_group`,
#: not once in the corpus's whole history. So the fact the course is
#: written around ("the op is senior-level, and it is used junior-style")
#: IS INTACT — and it is now PROVEN BY THE DOOR, rather than assumed. The
#: growing number looked like its refutation and was not: it was our work
#: growing, not the model's work.
#:
#: 🔴 AND THE SHAPE OF THE WINDOW, WITHOUT WHICH THE NUMBER LIES: 63 of 94
#: are ONE DAY, 18.08. This is an episode, not a chronicle, exactly like
#: `join_elements` (670 in a single day, 23.08). The lifetime count over
#: this corpus ranks July and our own campaigns; any conclusion drawn from
#: it must name the WINDOW and the DOOR.
GROUP_IN_LIVE_REJECTIONS = 94
LIVE_REJECTIONS_MEASURED = 3_953


__all__ = [
    "BUILDINGS", "DECOMPILE_ROOT", "MEASUREMENTS", "derived_categories",
    "Measurement", "GROUP_USES_IN_LIFTED_OPS", "LIFTED_OPS_MEASURED",
    "GROUP_IN_LIVE_REJECTIONS", "LIVE_REJECTIONS_MEASURED",
    "available", "curtain_authored_grid_lines", "curtain_hosts",
    "curtain_mullions", "curtain_panels", "curtain_type_driven_pct",
    "count_elements", "count_types", "derived_share", "elements",
    "group_definitions", "grouped_share", "index_absent_reason",
    "level_signatures", "side_index_absences", "SideIndex", "SIDE_INDEXES",
    "reused_definition_size",
    "levels_with_elements", "n", "fmt", "percent", "ratio",
    "reused_definitions", "top_level_instances",
    "value",
]
