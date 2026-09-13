# -*- coding: utf-8 -*-
"""One offline-edit rule — across FOUR different buildings, not one
bench.

🔴 WHY THIS FILE EXISTS — A MEASUREMENT, NOT CAUTION. Wave 7's
reconnaissance (07.09.2026, `p1_scan`) went through the ENTIRE corpus of
decompiles — 81 directories — and asked each one two things: is there a
door lifted as an operation, and is there a floor slab whose
`sketch.index.json` carried an opening RING. The answer: offline-edit
acceptance, `acceptance/run.py`, and all `capture_edit` tests ran on ONE
run — `bench_A`, and its addresses (`DOOR_ID = 286533`,
`OPENING_ID = 294707`) are written into the instruments as constants. A
rule checked on one building is a rule fitted to one building; mandate
F5 says this verbatim: "check several different captures, do not fit
rules to a single bench."

The other good runs are not put into the repository: `k2v33_join2` — 240
MB, `k4_geom_wave2` — 182 MB, `len_ar_me_r24_v1` — 95 MB. So next to them
lie SLICES (`capture_slices/`, cut by `make_slice.py`): real L0 rows
from real runs, narrowed down to the door, the slab with the opening,
their closures by reference, and a named number of neighbors. Not a
single value is made up. What was dropped is written as a number in
each slice's `SLICE.json`.

🔴 WHAT THIS FILE DOES NOT PROVE. It is not about scale: the neighbors
in a slice number in the tens, not the thousands. Scale is the job of
the full `bench_A` in neighboring files and the acceptance instrument.
What is proven here is something ELSE, and exactly one thing: the rule
is not tied to one building — four different buildings, four different
sets of addresses, four different node shapes (for `k2v33_join2` the
rings sit in `params.contour.holes`, for the other three — in
`params.holes`), and the answer is the same for all of them.

Slice numbers as of 07.09.2026:

    run                elements  slice  door        slab        rings
    bench_A                4223     91  286533      286551          1
    k4_geom_wave2         105005    89  11876962    11876977        6
    len_ar_me_r24_v1       57809    83  10003279    1001075         3
    k2v33_join2           115889   122  11835964    11840421        3
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from kir.decompile import capture_edit as CE

SLICES = pathlib.Path(__file__).resolve().parent / "capture_slices"
ROOT = pathlib.Path(__file__).resolve().parents[3]
#: Four DIFFERENT buildings. The list is closed: adding a slice is a
#: change to the cutter, not a row here, and `SLICE.json` must arrive
#: together with it.
BUILDINGS = ("bench_A", "k4_geom_wave2", "len_ar_me_r24_v1", "k2v33_join2")


def _slice_dir(name: str) -> pathlib.Path:
    return SLICES / name


def _meta(name: str) -> dict:
    """The slice's whole `SLICE.json`."""
    return json.loads((_slice_dir(name) / "SLICE.json").read_text(encoding="utf-8"))


def _seeds(name: str) -> dict:
    """Only the slice's seeds — the door, the slab, their hosts."""
    return _meta(name)["семена"]


@pytest.fixture(params=BUILDINGS)
def building(request, tmp_path):
    """A copy of the slice in its own `tmp`. The slice itself is a
    source, and it is not written to."""
    name = request.param
    work = tmp_path / name
    shutil.copytree(_slice_dir(name), work)
    meta = _meta(name)
    return {"name": name, "path": work, "seeds": meta["семена"], "meta": meta}


def _l0_rows(directory: pathlib.Path) -> dict:
    """L0 rows by address. Read by the SAME reader as the snapshot."""
    import gzip
    path = directory / "L0.jsonl"
    opener = path.open
    # raw on purpose: this explicitly exercises the same low-level carrier
    # choice as the snapshot reader.
    if not path.exists():
        path = directory / "L0.jsonl.gz"
        opener = lambda: gzip.open(path, "rt", encoding="utf-8")  # noqa: E731
    else:
        opener = lambda: path.open(encoding="utf-8")  # noqa: E731
    rows = {}
    with opener() as handle:
        for line in handle:
            if '"record": "element"' not in line and '"record":"element"' not in line:
                continue
            row = json.loads(line)
            rows[str(row["element"]["element_id"])] = row["element"]
    return rows


def _rings(capture, host: str) -> list:
    """A slab's opening rings — by ONE module law, not by a search of
    our own.

    🔴 A SEARCH OF OUR OWN HERE WOULD BE A SECOND LAW. The node's shape
    DIFFERS between buildings (`params.holes` versus
    `params.contour.holes`), and a test that looks for rings itself
    would be checking its own knowledge of the shape, not the module's
    behavior.
    """
    holes, _why = CE._holes_of(capture.by_source.get(host))
    return [CE._points_of(ring) for ring in holes]


def _moved(ring: list, dx: float) -> list:
    return [[point[0] + dx, point[1]] for point in ring]


def _sources(capture, version: str = "2026") -> list:
    """The exported C#. `export_program` returns a PAIR — programs and
    sources.

    🔴 UNPACKING IT MUST HAPPEN HERE, NOT ON THE SPOT. The first version
    of this file called `export_program` directly and compared the pair
    as a whole: its `len()` is always 2, and "there are just as many
    sources" was green for ANY number of programs. An instrument whose
    number does not depend on the subject measures nothing.
    """
    _programs, sources = CE.export_program(capture, revit_version=version)
    return list(sources)


# ── a slice must call itself a slice ────────────────────────────────────────
def test_a_slice_says_that_it_is_a_slice(building):
    """The reader sees a SLICE, not a building — from the directory,
    not from a report.

    🔴 THE NUMBER IS CHECKED AGAINST THE SNAPSHOT ITSELF, NOT AGAINST A
    NEIGHBORING REPORT LINE. The first version compared
    `перепись_среза.элементов_записано` against `элементов_в_срезе` —
    both fields are written by the SAME cutter in the SAME pass, and
    such a comparison is green under any counting error. Here the count
    comes from an OUTSIDE reader (`_l0_rows`), and a mismatch with the
    report is red.
    """
    meta = building["meta"]
    assert meta["schema"] == "kir-capture-slice/1"
    assert meta["срез_чего"] == building["name"]
    assert len(meta["источник_L0_sha256"]) == 64
    assert meta["элементов_в_срезе"] < meta["элементов_в_источнике"]
    assert "срез не является зданием" in meta["чем_это_не_является"]

    counted = len(_l0_rows(building["path"]))
    assert counted == meta["элементов_в_срезе"], (
        f"{building['name']}: в снимке {counted} элементов, а срез отчитался "
        f"о {meta['элементов_в_срезе']}")
    assert counted == meta["перепись_среза"]["элементов_записано"]
    # The seeds ARE PRESENT in the slice: a report about a door that is
    # not in the snapshot is not a report.
    rows = _l0_rows(building["path"])
    assert meta["семена"]["door"] in rows
    assert meta["семена"]["opening_host"] in rows
    assert rows[meta["семена"]["door"]]["category"] == "OST_Doors"
    assert rows[meta["семена"]["opening_host"]]["category"] in ("OST_Floors", "OST_Ceilings")


# ── (acceptance 1) the door and the supported opening are edited TWICE after reopen ──
def test_a_door_and_a_hosted_opening_change_twice_across_a_reopen(building, tmp_path):
    """Two edits of each target, with a save and a reopen between them.

    The subject is not "the edit was applied" but "the edit SURVIVED the
    close": the second move edits something already read back from
    disk, and both edits must be in the journal.
    """
    seeds, work = building["seeds"], building["path"]
    door, host = seeds["door"], seeds["opening_host"]
    capture = CE.open_capture(work)
    first_ring = _rings(capture, host)[0]

    assert CE.edit_element(capture, door, {"offset_mm": 1111.0}).refusal is None
    assert CE.edit_element(capture, host, {"opening_index": 0,
                                           "opening_contour_mm": _moved(first_ring, 10.0)}
                           ).refusal is None
    saved = CE.save(capture, tmp_path / "save-1")

    reopened = CE.open_capture(saved)
    assert len(reopened.edits) == 2, "первые две правки не пережили сохранение"
    assert reopened.by_source[door]["params"]["offset_mm"] == 1111.0
    assert _rings(reopened, host)[0] == _moved(first_ring, 10.0)

    assert CE.edit_element(reopened, door, {"offset_mm": 2222.0}).refusal is None
    assert CE.edit_element(reopened, host, {"opening_index": 0,
                                            "opening_contour_mm": _moved(first_ring, 20.0)}
                           ).refusal is None
    saved2 = CE.save(reopened, tmp_path / "save-2")

    final = CE.open_capture(saved2)
    assert len(final.edits) == 4, "четыре правки — четыре строки журнала"
    assert final.edit_binding == "before_value"
    assert final.by_source[door]["params"]["offset_mm"] == 2222.0
    assert _rings(final, host)[0] == _moved(first_ring, 20.0)


def test_a_second_process_reads_what_the_first_one_saved(building, tmp_path):
    """A restart: a different process sees BOTH edits, not this one's
    memory."""
    seeds, work = building["seeds"], building["path"]
    door, host = seeds["door"], seeds["opening_host"]
    capture = CE.open_capture(work)
    ring = _rings(capture, host)[0]
    CE.edit_element(capture, door, {"offset_mm": 1111.0})
    CE.edit_element(capture, host, {"opening_index": 0,
                                    "opening_contour_mm": _moved(ring, 10.0)})
    saved = CE.save(capture, tmp_path / "one")
    again = CE.open_capture(saved)
    CE.edit_element(again, door, {"offset_mm": 2222.0})
    saved2 = CE.save(again, tmp_path / "two")

    child = subprocess.run(
        [sys.executable, "-c",
         "import json,sys;from kir.decompile import capture_edit as CE;"
         "c=CE.open_capture(sys.argv[1]);"
         "print(json.dumps({'offset':c.by_source[sys.argv[2]]['params']['offset_mm'],"
         "'edits':len(c.edits),'lineage':c.lineage,'integrity':c.integrity}))",
         str(saved2), door],
        capture_output=True, text=True, timeout=600,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"})
    assert child.returncode == 0, child.stderr[-2000:]
    got = json.loads(child.stdout.strip().splitlines()[-1])
    assert got["offset"] == 2222.0
    assert got["edits"] == 3
    assert got["integrity"] == "pinned:source_version"


# ── (acceptance 2) the rest of the building is intact — BY ADDRESS and byte for byte ──
def test_the_rest_of_the_building_is_untouched(building, tmp_path):
    """The neighbors are byte-for-byte the same in both L0 and the
    exported C#."""
    seeds, work = building["seeds"], building["path"]
    door, host = seeds["door"], seeds["opening_host"]
    before_rows = _l0_rows(work)

    pristine = CE.open_capture(work)
    before_sources = _sources(pristine)

    capture = CE.open_capture(work)
    ring = _rings(capture, host)[0]
    CE.edit_element(capture, door, {"offset_mm": 1111.0})
    CE.edit_element(capture, host, {"opening_index": 0,
                                    "opening_contour_mm": _moved(ring, 10.0)})
    saved = CE.save(capture, tmp_path / "saved")
    after_rows = _l0_rows(saved)

    assert set(before_rows) == set(after_rows), "адреса элементов уехали"
    moved = [key for key in before_rows
             if json.dumps(before_rows[key], sort_keys=True)
             != json.dumps(after_rows[key], sort_keys=True)]
    assert moved == [], f"строки L0 изменились у {moved[:5]}"

    reopened = CE.open_capture(saved)
    after_sources = _sources(reopened)
    assert len(before_sources) == len(after_sources)
    changed = [index for index, (was, now) in enumerate(zip(before_sources, after_sources))
               if was != now]
    assert changed, "правка не доехала до C# — экспорт не о том"
    untouched = [index for index in range(len(before_sources)) if index not in changed]
    for index in untouched:
        assert before_sources[index] == after_sources[index]


# ── (acceptance 3) the export is judged by CONTENT and compilation, not by length ──
_NUMBER = __import__("re").compile(r"-?\d+\.\d+(?:[eE][-+]?\d+)?")


def _changed_lines(before: list, after: list) -> list:
    """Pairs of C# lines that diverged. The programs must match in
    count."""
    assert len(before) == len(after), "экспорт выпустил другое число программ"
    out = []
    for was, now in zip(before, after):
        if was == now:
            continue
        lines_was, lines_now = was.splitlines(), now.splitlines()
        assert len(lines_was) == len(lines_now), "правка переписала строение файла"
        out.extend((x, y) for x, y in zip(lines_was, lines_now) if x != y)
    return out


def test_the_export_compiles_and_carries_the_change_by_content(building):
    """The numbers in the C# shifted by EXACTLY the size of the edit.
    Not "a line changed."

    🔴 LENGTH AND SUBSTRING PROVE NOTHING, AND THE MANDATE FORBIDS THEM
    FROM BEING THE JUDGE. The first version of this test searched the C#
    for the substring "1111" — and was RED on all four buildings, and
    HONESTLY so: `offset_mm` is an offset ALONG the host wall, while the
    C# carries the final point. For `bench_A`, `5000.0` moves to
    `3111.0` under an edit of 3000 -> 1111; the number "1111" is not in
    the text and must not be. A substring would be checking MY idea of
    the translation, not the translation itself.

    So what is judged is a LAW: every number that diverged shifted by
    exactly `new - old` millimeters, and none of them moved anywhere
    else.
    """
    seeds, work = building["seeds"], building["path"]
    door = seeds["door"]
    pristine = CE.open_capture(work)
    before = _sources(pristine)
    was = float(pristine.by_source[door]["params"]["offset_mm"])

    capture = CE.open_capture(work)
    assert CE.edit_element(capture, door, {"offset_mm": was + 137.0}).refusal is None
    after = _sources(capture)

    assert capture.export_refusals == [], capture.export_refusals
    assert after, "компилятор не выпустил ни одной программы"
    assert all(source.strip() for source in after), "пустой исходник — не перевод"

    pairs = _changed_lines(before, after)
    assert pairs, "правка не доехала до C#"
    moved = 0
    for old_line, new_line in pairs:
        olds = [float(x) for x in _NUMBER.findall(old_line)]
        news = [float(x) for x in _NUMBER.findall(new_line)]
        assert len(olds) == len(news), f"числа в строке пропали: {old_line!r}"
        for a, b in zip(olds, news):
            if a == b:
                continue
            moved += 1
            assert abs(abs(b - a) - 137.0) < 1e-6, (
                f"число уехало на {b - a}, а правка была на 137.0: {new_line!r}")
    assert moved, "строки разошлись, а числа те же — изменился не предмет"

    # Compilation happened TWICE — under both API versions, as the
    # mandate requires.
    older = _sources(capture, "2023")
    assert older and all(source.strip() for source in older)
    assert capture.export_refusals == [], capture.export_refusals


def test_a_hosted_opening_reaches_the_export_too(building):
    """The opening's edit also makes it to the C#, and these are
    DIFFERENT lines than the door's."""
    seeds, work = building["seeds"], building["path"]
    host = seeds["opening_host"]
    pristine = CE.open_capture(work)
    before = _sources(pristine)

    capture = CE.open_capture(work)
    ring = _rings(capture, host)[0]
    assert CE.edit_element(capture, host, {"opening_index": 0,
                                           "opening_contour_mm": _moved(ring, 137.0)}
                           ).refusal is None
    after = _sources(capture)
    assert capture.export_refusals == [], capture.export_refusals
    pairs = _changed_lines(before, after)
    assert pairs, "правка отверстия не доехала до C#"
    for old_line, new_line in pairs:
        olds = [float(x) for x in _NUMBER.findall(old_line)]
        news = [float(x) for x in _NUMBER.findall(new_line)]
        for a, b in zip(olds, news):
            assert a == b or abs(abs(b - a) - 137.0) < 1e-6, (
                f"кольцо уехало на {b - a}, а сдвиг был 137.0")


# ── (acceptance 4) changing sketch while L0 stays the same does not bypass binding ──
def test_a_new_sketch_under_the_same_l0_does_not_slip_past_the_binding(building, tmp_path):
    """The same snapshot, different geometry — a refusal BY NAME, not a
    silent edit.

    This is exactly the mandate's clause: "changing sketch while L0
    stays the same does not bypass source binding." The binding must
    rest on the WHOLE source, not on L0 alone.
    """
    seeds, work = building["seeds"], building["path"]
    door, host = seeds["door"], seeds["opening_host"]
    capture = CE.open_capture(work)
    ring = _rings(capture, host)[0]
    CE.edit_element(capture, door, {"offset_mm": 1111.0})
    CE.edit_element(capture, host, {"opening_index": 0,
                                    "opening_contour_mm": _moved(ring, 10.0)})
    saved = CE.save(capture, tmp_path / "saved")

    sketch = CE._side_path(saved, "sketch")
    assert sketch is not None, "у среза нет sketch — подменять нечего"
    import gzip
    payload = json.dumps({"profile_index": {}, "schema_version": "kir-decompile-sketch/1"},
                         ensure_ascii=False) + "\n"
    if sketch.suffix == ".gz":
        with sketch.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as handle:
                handle.write(payload.encode("utf-8"))
    else:
        sketch.write_text(payload, encoding="utf-8")

    with pytest.raises(CE.CaptureEditError) as refusal:
        CE.open_capture(saved)
    assert refusal.value.code == "source_sidecar_changed"
    assert "sketch" in str(refusal.value)


# ── (acceptance 5) moving the save does not change identity ────────────────
def test_moving_the_save_does_not_change_identity(building, tmp_path):
    """`mv` of the directory: `lineage`, the stamps, and the C# are byte
    for byte the same."""
    seeds, work = building["seeds"], building["path"]
    door = seeds["door"]
    capture = CE.open_capture(work)
    CE.edit_element(capture, door, {"offset_mm": 1111.0})
    saved = CE.save(capture, tmp_path / "here")
    first = CE.open_capture(saved)
    lineage, sources = first.lineage, _sources(first)

    moved = tmp_path / "somewhere" / "else-entirely"
    moved.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(saved), str(moved))
    second = CE.open_capture(moved)
    assert second.lineage == lineage, "перенос переименовал здание"
    assert second.lineage_source == "capture_meta.json"
    assert _sources(second) == sources


# ── (leftover from the F5 registry) `anchor_mm` is a carrier of the point, not a concession ──
def _p0_represented(capture, nodes) -> tuple:
    """(how many elements carry `p0_mm` as having arrived, how many of
    them as derived)."""
    from kir.decompile.field_ledger import field_ledger

    ledger = field_ledger(capture.document, nodes)
    kept = sum(1 for row in ledger.rows if "p0_mm" in row.kept)
    return kept, dict(ledger.totals)["represented_via_derived_slot"]


def test_the_anchor_alias_is_load_bearing_and_not_an_indulgence(building, monkeypatch):
    """The alias `p0_mm -> anchor_mm` EARNS its place — and only
    through its value.

    🔴 THE F5 REGISTRY WAS CHARGING THE LEDGER WITH AN UNDERCOUNT: the
    placement point sits in the node under the `anchor_mm` slot, while
    the old law looked for a carrier ONLY by a matching NAME and
    declared it lost for 126 doors and 756 columns of `bench_A`. The
    alias was set up on 07.09.2026; what is checked here is that it did
    not turn into a concession — by two moves and across four
    buildings.

    🔴 AND RECORDED RIGHT HERE IS MY OWN INCORRECT LAW. The first
    revision required "`anchor_mm` not equal to `p0_mm` -> the field is
    NOT represented" and gave 48 "violations" on the `bench_A` slice.
    The ledger was right, and I was not: for 48 beams the point is
    carried by the NAMED carrier `params.p0_mm`, which EQUALS the
    value, while `anchor_mm` (the segment's midpoint) is simply another
    slot of the same node. A field does not have a single carrier, and
    demanding that all carriers agree is not a law, it is my idea of
    one.
    """
    from kir.decompile import field_ledger as FL

    capture = CE.open_capture(building["path"])
    with_alias, derived = _p0_represented(capture, capture.nodes)
    assert derived >= 1, (
        f"{building['name']}: ни одна точка не держится на выведенном слоте — "
        f"проверять нечего")

    # (1) WITHOUT the alias the number DROPS: meaning it carries real
    # addresses, not a repeat of what the name already counted.
    alias = dict(FL.IR_SLOT_ALIAS)
    alias.pop("p0_mm", None)
    monkeypatch.setattr(FL, "IR_SLOT_ALIAS", alias)
    without_alias, derived_without = _p0_represented(capture, capture.nodes)
    assert without_alias == with_alias - derived, (
        f"{building['name']}: с псевдонимом {with_alias}, без него "
        f"{without_alias}, а через выведенный слот числилось {derived}")
    assert derived_without == 0


def test_the_anchor_alias_compares_values_not_the_presence_of_the_slot(building):
    """Corrupt the value in the slot — the point must stop being
    counted as arrived.

    This is the second move of the same control, and it matters more
    than the first: an alias that counts a field FOR THE MERE PRESENCE
    OF THE SLOT would be exactly the concession the law was written to
    forbid. The slot stays in place, only the number changes.
    """
    capture = CE.open_capture(building["path"])
    honest, derived = _p0_represented(capture, capture.nodes)
    spoiled = copy.deepcopy(capture.nodes)
    touched = 0
    for node in spoiled:
        if isinstance(node.get("anchor_mm"), list):
            node["anchor_mm"] = [9.0e6, 9.0e6, 9.0e6]
            touched += 1
    assert touched, f"{building['name']}: слота `anchor_mm` нет ни в одном узле"
    after, derived_after = _p0_represented(capture, spoiled)
    assert after == honest - derived, (
        f"{building['name']}: было {honest}, при испорченном якоре {after}, "
        f"а на якоре держалось {derived} — сравнение идёт не по значению")
    assert derived_after == 0


def test_a_carried_point_is_reported_as_carried_by_a_derived_slot(building):
    """A removed loss does NOT read as a proven reconstruction.

    `fold` calls `anchor_mm` derived and DISCARDS it from the canonical
    form (`canonical.pop("anchor_mm")`): reassembly places the door by
    `host` and `offset_mm`. So "represented" must be readable TOGETHER
    with how much of it rests on the derived slot, otherwise two
    different facts merge into one.
    """
    from kir.decompile.field_ledger import field_ledger

    capture = CE.open_capture(building["path"])
    totals = dict(field_ledger(capture.document, capture.nodes).totals)
    assert "represented_via_derived_slot" in totals
    assert totals["represented_via_derived_slot"] <= totals["by_state"]["represented"]


# ── (leftover from the F5 registry) `describe().losses` — ONE formula, not a copy ──
def test_describe_and_losses_answer_with_one_formula(building):
    """Two carriers of one law must give one answer at every address.

    🔴 THIS IS NOT A TAUTOLOGY, AND THE DIFFERENCE HERE IS SUBSTANTIAL.
    `describe()` calls the ledger on ONE element (`_OneElement`)
    together with ALL the building's nodes, while `losses()` calls it
    on the whole document at once. These are TWO DIFFERENT CALLS of one
    law, and there is real room for them to diverge: exactly this way
    the losses of `bench_A`'s door 286533 already diverged — 12 against
    11, when `describe` received a single node and had nothing to
    resolve the door's reference to the wall against.

    The F5 registry was charging `describe().losses` with its own copy
    of the formula. Measurement of 07.09.2026 across the full
    `bench_A` (4223 elements): 0 discrepancies — the copy is gone. Here
    the same is checked on four more buildings, so that "zero" does not
    turn out to be a property of one house.
    """
    capture = CE.open_capture(building["path"])
    global_rows = {row.element_id: set(row.fields) for row in CE.losses(capture)}
    checked = 0
    for key in sorted(capture.elements):
        mine = set(CE.describe(capture, key).losses)
        theirs = global_rows.get(key, set())
        assert mine == theirs, (
            f"{building['name']} {key}: describe говорит {sorted(mine - theirs)} "
            f"лишним и {sorted(theirs - mine)} недостающим против losses()")
        checked += 1
    assert checked == len(capture.elements)
    assert global_rows, f"{building['name']}: потерь ноль — сравнивать нечего"


def test_the_one_formula_check_would_catch_a_second_formula(building, monkeypatch):
    """CONTROL: swap the formula in one carrier — the instrument must
    turn red.

    Without this move, the previous test could be green simply because
    it compares something against itself.
    """
    capture = CE.open_capture(building["path"])
    honest = CE._field_states

    def second_formula(element, node, nodes=None):
        states = dict(honest(element, node, nodes))
        for name in list(states):
            states[name] = "unknown"
            break
        return states

    monkeypatch.setattr(CE, "_field_states", second_formula)
    global_rows = {row.element_id: set(row.fields) for row in CE.losses(capture)}
    disagreed = [key for key in sorted(capture.elements)
                 if set(CE.describe(capture, key).losses) != global_rows.get(key, set())]
    assert disagreed, "подменённая формула не была замечена — прибор ничего не мерит"


# ── (mandate F5) unknown data IS PRESERVED, not turned into zeros ──────────
_EMPTY = (None, "", [], {}, ())


def _is_empty(value) -> bool:
    """Whether a value is empty. `0` and `False` are NOT counted as
    empty HERE.

    🔴 THIS IS EXACTLY WHERE MY OWN PROBE LIED, AND IT IS RECORDED
    AGAINST MYSELF. The reconnaissance `p3_roundtrip.py` asked
    `value in (None, "", (), [], {})` — and a field with the value
    `0.0` in BOTH snapshots passed both arms of the condition "was
    non-empty" and "became zero." The instrument reported "54 zeroed
    out" on the full `bench_A`; a check of the first 20 gave 20 out of
    20 with `b == a` (`rotation_deg 0.0 -> 0.0`), the real answer being
    ZERO. The comparison below goes by the IDENTITY of the values, not
    by landing in the "empty" bucket.
    """
    return any(value is item or (type(value) is type(item) and value == item)
               for item in _EMPTY)


def _zeroed(before: dict, after: dict) -> list:
    """Fields that CARRIED a value and became zero/empty. Zero-into-zero
    is not that."""
    out = []
    for name, was in before.items():
        now = after.get(name)
        if was == now:
            continue                     # unchanged — is not a zeroing-out
        if _is_empty(was):
            continue                     # was empty — nothing to lose
        if now == 0 or now == 0.0 or _is_empty(now) or name not in after:
            out.append((name, was, now))
    return out


def test_unknown_data_survives_a_save_without_turning_into_zeros(building, tmp_path):
    """There are HUNDREDS of fields the lifter does not lift, and
    preservation does not touch them.

    Mandate F5 requires this verbatim: "unknown data must be preserved,
    not turned into zeros." Checked on three carriers at once: the L0
    row, the count of fields in the `unknown` state per the ledger, and
    the absence of zeroing-out BY VALUE.
    """
    seeds, work = building["seeds"], building["path"]
    door, host = seeds["door"], seeds["opening_host"]
    before_rows = _l0_rows(work)
    capture = CE.open_capture(work)
    before_unknown = sum(1 for key in capture.elements
                         for state in CE.describe(capture, key).field_states.values()
                         if state == "unknown")
    assert before_unknown, f"{building['name']}: неподнятых полей ноль — мерить нечего"

    ring = _rings(capture, host)[0]
    CE.edit_element(capture, door, {"offset_mm": 1111.0})
    CE.edit_element(capture, host, {"opening_index": 0,
                                    "opening_contour_mm": _moved(ring, 10.0)})
    saved = CE.save(capture, tmp_path / "saved")
    reopened = CE.open_capture(saved)
    after_rows = _l0_rows(saved)

    lost = []
    for key, was in before_rows.items():
        lost.extend((key, *item) for item in _zeroed(was, after_rows.get(key) or {}))
    assert lost == [], f"{building['name']}: обнулилось {lost[:5]}"

    after_unknown = sum(1 for key in reopened.elements
                        for state in CE.describe(reopened, key).field_states.values()
                        if state == "unknown")
    assert after_unknown == before_unknown, (
        f"{building['name']}: неподнятых полей было {before_unknown}, "
        f"стало {after_unknown} — сохранение изменило то, чего не понимает")


def test_the_zeroing_check_is_not_blind_to_a_real_zero(building, tmp_path):
    """CONTROL: zero out one NON-EMPTY field — the instrument must
    name it.

    And the second move of the same control: a field that was zero and
    stayed zero, the instrument must NOT name. The first move catches
    blindness, the second catches the very lie the reconnaissance probe
    was caught on.
    """
    rows = _l0_rows(building["path"])
    victim = next((key for key, row in rows.items()
                   if any(not _is_empty(value) and value not in (0, 0.0)
                          for value in row.values())), None)
    assert victim is not None
    row = rows[victim]
    name = next(key for key, value in row.items()
                if not _is_empty(value) and value not in (0, 0.0))
    assert _zeroed(row, {**row, name: 0}) == [(name, row[name], 0)]
    assert _zeroed(row, {**row, name: None}) == [(name, row[name], None)]
    # A zero that was already zero: silence is the correct answer.
    assert _zeroed({"rotation_deg": 0.0}, {"rotation_deg": 0.0}) == []
    assert _zeroed({"phase_created": ""}, {"phase_created": ""}) == []


# ── ANTI-GOODHART: are these actually FOUR buildings, and is the neighbor instrument blind ──
def test_the_four_buildings_are_four_different_documents():
    """Four slices are four DIFFERENT documents, not one under four
    names.

    🔴 WITHOUT THIS MOVE THE WHOLE FILE COULD BE "FOUR BUILDINGS" ONLY
    ON PAPER. This actually happens in the corpus:
    `13a-rd-ar-k2_v33_kuklev.d.s` and `k2v33_join2` carry the SAME
    number of doors (2 096) and the SAME opening address (13227531) —
    it is one house, decompiled twice. Taking both would mean
    reporting on four buildings while having three. A document's
    identity is asked of ITS OWN proof (`revision.proof.json`), not of
    the directory's name, and of the snapshot — by its bytes.
    """
    revisions, snapshots, seeds = {}, {}, {}
    for name in BUILDINGS:
        directory = _slice_dir(name)
        revisions[name] = CE._capture_revision(directory)
        snapshots[name] = CE._snapshot_digest(directory)
        seeds[name] = _seeds(name)["door"]
    assert len(set(revisions.values())) == len(BUILDINGS), (
        f"ревизии документов совпали: {revisions}")
    assert len(set(snapshots.values())) == len(BUILDINGS), "снимки совпали"
    assert len(set(seeds.values())) == len(BUILDINGS), (
        f"адреса дверей совпали — это один дом: {seeds}")
    assert not any(value.startswith(("absent:", "unreadable:"))
                   for value in revisions.values()), (
        f"срез без доказательства ревизии не годится в свидетели: {revisions}")


def test_the_neighbour_check_would_see_a_touched_neighbour(building, tmp_path):
    """CONTROL: touch a NEIGHBOR — the comparison must name it.

    The instrument "the rest of the building is intact" is also green
    when it compares nothing at all. Here an edit to a neighbor that
    the edit did not make is introduced into the saved copy, and the
    same comparison must turn red.
    """
    seeds, work = building["seeds"], building["path"]
    door = seeds["door"]
    capture = CE.open_capture(work)
    CE.edit_element(capture, door, {"offset_mm": 1111.0})
    saved = CE.save(capture, tmp_path / "saved")

    before = _l0_rows(work)
    after = dict(_l0_rows(saved))
    neighbour = next(key for key in sorted(after) if key != door)
    after[neighbour] = {**after[neighbour], "__подброшено__": 1}
    moved = [key for key in before
             if json.dumps(before[key], sort_keys=True)
             != json.dumps(after.get(key), sort_keys=True)]
    assert moved == [neighbour], f"сравнение соседей слепо: {moved}"


# ── a slice is REPRODUCIBLE from the corpus — meaning it was not hand-edited ──
_CORPUS = pathlib.Path("/opt/kukai-rebuild1/backend/backend/data/decompile")


@pytest.mark.skipif(not _CORPUS.is_dir(), reason="корпуса нет на этой машине")
def test_a_slice_is_reproducible_from_the_corpus(building, tmp_path):
    """Cut it again — the bytes are the same. Otherwise the fixture
    could have been tampered with.

    🔴 THIS IS A GUARD AGAINST ONESELF. The slice lives in the
    repository and looks like corpus data; nothing but this check would
    stop someone from tweaking a number in it to turn the test green.
    Here the cutter is run against the SAME corpus run, and the result
    is checked BYTE FOR BYTE — 14 files for `bench_A`. This is exactly
    why the compression is deterministic (`_write_gz`, `mtime=0`):
    without it, the gzip header would carry a timestamp, and "the same
    bytes" would be unreachable.
    """
    from kir.decompile.tests.capture_slices import make_slice

    if not (_CORPUS / building["name"]).is_dir():
        pytest.skip(f"прогона {building['name']} нет в корпусе этой машины")
    out = tmp_path / "recut"
    make_slice.main(["--run", building["name"], "--out", str(out),
                     "--corpus", str(_CORPUS)])

    have = {item.name: item.read_bytes()
            for item in sorted(_slice_dir(building["name"]).iterdir()) if item.is_file()}
    made = {item.name: item.read_bytes()
            for item in sorted(out.iterdir()) if item.is_file()}
    assert set(have) == set(made), (
        f"состав среза разошёлся: лишние {sorted(set(have) - set(made))}, "
        f"недостающие {sorted(set(made) - set(have))}")
    differ = sorted(name for name in have if have[name] != made[name])
    assert differ == [], f"{building['name']}: срез не воспроизводится по {differ}"


# ── three DIFFERENT facts about one field, not one ──────────────────────────
def test_storing_a_field_representing_it_and_restoring_it_are_three_facts(building):
    """A field IS STORED in L0, is NOT represented in the IR, and is
    NOT recoverable through export.

    🔴 MANDATE F5 REQUIRES TELLING THEM APART VERBATIM: "distinguish
    storage of the source field, representation in the IR, and
    recoverability in BIM. An L1/FOLD round trip is not proof of native
    losslessness." The lift→fold→expand loop will close even for a
    building that dropped `unique_id`: it compares IR against IR, not
    IR against the DOCUMENT.

    The witness is `unique_id`, and it was chosen by MEASUREMENT, not
    by taste: it exists on all 91/89/83/122 elements of the slices, the
    ledger calls it `unknown` on all four buildings, and its value
    (a GUID) does not occur in the exported C# for a single one of
    them. A substring match is ruled out here: `curve_kind` with the
    value `line` DOES occur in the C# — as an ordinary word, not as a
    carried-over field, and is therefore unfit as a witness.
    """
    capture = CE.open_capture(building["path"])
    rows = _l0_rows(building["path"])
    _programs, sources = CE.export_program(capture, revit_version="2026")
    emitted = "\n".join(sources)

    stored = represented = restorable = 0
    for key in sorted(capture.elements):
        value = (rows.get(key) or {}).get("unique_id")
        if not value:
            continue
        stored += 1                                   # (1) IS STORED in L0
        if CE.describe(capture, key).field_states.get("unique_id") == "represented":
            represented += 1                          # (2) is represented in the IR
        if value in emitted:
            restorable += 1                           # (3) is recoverable in BIM

    assert stored, f"{building['name']}: у элементов нет `unique_id` — свидетеля нет"
    assert represented == 0, (
        f"{building['name']}: ведомость числит `unique_id` доехавшим у "
        f"{represented} из {stored} — тогда свидетель не о том")
    assert restorable == 0, (
        f"{building['name']}: значение `unique_id` доехало до C# у "
        f"{restorable} из {stored}; «не представлено в IR» и «не восстановимо» "
        f"перестали быть одним фактом — свидетеля надо менять")
