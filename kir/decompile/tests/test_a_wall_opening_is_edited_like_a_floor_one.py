# -*- coding: utf-8 -*-
"""An opening in a WALL is edited just as precisely as a hole in a slab —
and refuses just as by-name.

🔴 WHY THIS FILE EXISTS — A MEASUREMENT, NOT A SYMMETRY. Before
08.09.2026, the capture edit contract knew two subjects: the door
(`_DOOR_FIELDS`) and the opening RING in the inner loop of a slab/ceiling
sketch (`_OPENING_FIELDS`). A wall opening is a third, and it is not
"just another category of the second":

    hole in a slab             opening in a wall
    ────────────────────────   ─────────────────────────────────────────
    a ring in the BEARER's     a SEPARATE `DB.Opening` element
    sketch
    the slab itself is edited  the opening itself is edited
    opening_index + contour    two opposite corners
    create_floor/create_ceiling create_opening(variety="wall_rect")
    the profile's inner loop   NewOpening(Wall, XYZ, XYZ)

The wave plan's hypothesis — "`_OPENING_FIELDS` already covers walls, only
the category validator was refusing, one move fixes the target" — was
TESTED AND NOT CONFIRMED: with the validator removed, a wall opening would
be handed to `_edit_opening`, which would ask the opening node for
`_holes_of` and return `opening_contour_not_captured` — a refusal correct
in wording and false in reason.

🔴 THE WAVE'S KEY NUMBER, AND IT CHANGES THIS FILE'S SHAPE. A corpus
census on 08.09.2026 by ELEMENT records (a line-based `grep` lies: the
category is also mentioned in the header census):

    run                 elements    wall openings    came up in an op
    mnvnk_k1_layers        63,965          120                0
    k4_geom_wave2         105,005           51                0
    bench_A                 4,223           12                0
    ─────────────────────────────────────────────────────────────────
    3 runs out of 93                       183                0

A scan of all 1,508 corpus files: occurrences of `opening_is_rect` and
`opening_boundary_mm` — ZERO. The reason is named by the date: the
boundary reader (`extract._opening_boundary_reader_cs`) was set up
04.09.2026, while the entire corpus was captured in August. So **the
corpus contains not a single supported wall opening**, and the contract's
two moves are checked by DIFFERENT means, not one:

* REFUSAL — on 183 real openings from three real buildings (slices of two
  are in the repository: `mnvnk_k1_layers_walls`, `k4_geom_wave2_walls`);
* THE EDIT — on a synthetic snapshot of the SHAPE that the very same
  reader writes (`write_demo_capture(..., wall_opening=True)`).

The synthetic snapshot is not, and cannot be, a corpus number; this is
said here, not only in the report, because the reader of this test is the
next shift.
"""
from __future__ import annotations

import copy
import gzip
import json
import math
import pathlib
import re
import shutil

import pytest

from kir.decompile import capture_api as API
from kir.decompile import capture_edit as CE

SLICES = pathlib.Path(__file__).resolve().parent / "capture_slices"
#: Slices of REAL buildings carrying wall openings. Two, not one: a rule
#: checked on a single building is a rule fitted to that one building.
WALL_SLICES = ("mnvnk_k1_layers_walls", "k4_geom_wave2_walls")
_CORPUS = pathlib.Path("/opt/kukai-rebuild1/backend/backend/data/decompile")


def _meta(name: str) -> dict:
    return json.loads((SLICES / name / "SLICE.json").read_text(encoding="utf-8"))


@pytest.fixture(params=WALL_SLICES)
def wall_building(request, tmp_path):
    """A copy of the slice in its own `tmp`. The slice itself is the
    source, and it is never written to."""
    name = request.param
    work = tmp_path / name
    shutil.copytree(SLICES / name, work)
    meta = _meta(name)
    return {"name": name, "path": work, "seeds": meta["семена"], "meta": meta}


@pytest.fixture
def supported(tmp_path):
    """A snapshot in which the wall opening CAME UP AS AN OP. Synthetic —
    and named as such."""
    directory = tmp_path / "demo-wall-opening"
    API.write_demo_capture(directory, wall_opening=True)
    return directory


def _l0_rows(directory: pathlib.Path) -> dict:
    """L0 rows by address — read by an OUTSIDE reader, not through the
    module."""
    path = directory / "L0.jsonl"
    # raw on purpose: an outside reader chooses the raw/gzip carrier by
    # itself instead of reusing the module under test.
    opener = (lambda: path.open(encoding="utf-8")) if path.exists() else None
    if opener is None:
        path = directory / "L0.jsonl.gz"
        opener = lambda: gzip.open(path, "rt", encoding="utf-8")  # noqa: E731
    rows = {}
    with opener() as handle:
        for line in handle:
            if '"record": "element"' not in line and '"record":"element"' not in line:
                continue
            row = json.loads(line)
            rows[str(row["element"]["element_id"])] = row["element"]
    return rows


def _corners(capture, key: str) -> tuple:
    """Two opening corners TAKEN FROM THE NODE, by the same name mapping
    the contract uses."""
    params = (capture.by_source.get(key) or {}).get("params") or {}
    return params.get("p0_mm"), params.get("p1_mm")


def _emitted(capture, version: str) -> str:
    """The emitted C#. `export_program` returns a PAIR — programs and
    sources.

    It is unpacked HERE: a pair's `len()` is always 2, and comparing the
    whole pair would stay green regardless of the number of programs (a
    lesson from a neighboring file, verbatim).
    """
    _programs, sources = CE.export_program(capture, revit_version=version)
    return "\n".join(sources)


#: What an opening call looks like in the emitted C#:
#: `NewOpening(Wall, XYZ, XYZ)`.
_NEW_OPENING = re.compile(r"NewOpening\(__hw_[^,]+, P\(([^)]*)\), P\(([^)]*)\)\)")


def _emitted_corners(text: str) -> list:
    """The corners that actually made it into the C#. What is read is the
    CALL, not the presence of a substring."""
    out = []
    for first, second in _NEW_OPENING.findall(text):
        out.append(([float(x) for x in first.split(",")],
                    [float(x) for x in second.split(",")]))
    return out


def _law(p0, p1) -> tuple:
    """THE FORWARD LAW, retold from the op's postcondition, not called
    directly.

    🔴 CALLING `opening_emit` HERE WOULD BE CHECKING THE CODE AGAINST
    ITSELF. `create_opening`'s promise is stated in words
    (`ops_opening.OPS[0].post`): "variety=wall_rect: IsRectBoundary and
    the BoundaryRect corners hold the requested Z band and the requested
    width along the wall." Three quantities — the band's lower and upper
    elevations and the width ALONG THE WALL (the plan distance between the
    corners) — are computed here by arithmetic on this wording. Whether
    they match the emitter's output or not is exactly what is being
    checked.
    """
    return (min(p0[2], p1[2]), max(p0[2], p1[2]),
            math.hypot(p1[0] - p0[0], p1[1] - p0[1]))


def _witness_numbers(text: str) -> list:
    """The numbers the C# witness checks against the built opening.

    The witness is written as: `Math.Abs(__bz0_X - <zmin>) > tol ||
    Math.Abs(__bz1_X - <zmax>) > tol || Math.Abs(__bw_X - <width>) > tol`.
    Exactly these three are extracted, and they are extracted FROM THE
    TEXT — that is, from what would actually ship to Revit, not from our
    own arguments.
    """
    pattern = re.compile(
        r"Math\.Abs\(__bz0_\w+ - (-?[\d.eE+]+)\) > [\d.]+ \|\| "
        r"Math\.Abs\(__bz1_\w+ - (-?[\d.eE+]+)\) > [\d.]+\s*\n?\s*\|\| "
        r"Math\.Abs\(__bw_\w+ - (-?[\d.eE+]+)\) > [\d.]+")
    return [tuple(float(x) for x in row) for row in pattern.findall(text)]


# ── 1. the slice calls itself a slice, and names its SUBJECT ──────────────
def test_a_wall_slice_says_what_it_is_a_slice_of(wall_building):
    """The reader sees the SLICE and sees its SUBJECT — from the
    directory, not from the report.

    🔴 THE NUMBER IS COMPUTED BY AN OUTSIDE READER. Checking
    `slice_census.elements_written` against `elements_in_slice` is
    pointless: both fields are written by ONE cutter in ONE pass, and
    such a check stays green under any counting bug.
    """
    meta = wall_building["meta"]
    assert meta["schema"] == "kir-capture-slice/1"
    assert meta["предмет"] == "wall_opening", (
        "срез предмета проёма стены обязан называть свой предмет: без этого "
        "он неотличим от среза про отверстие в плите")
    assert len(meta["источник_L0_sha256"]) == 64
    assert meta["элементов_в_срезе"] < meta["элементов_в_источнике"]
    assert "срез не является зданием" in meta["чем_это_не_является"]

    rows = _l0_rows(wall_building["path"])
    assert len(rows) == meta["элементов_в_срезе"]
    assert len(rows) == meta["перепись_среза"]["элементов_записано"]

    seeds = wall_building["seeds"]
    assert len(seeds["wall_openings"]) >= 2, (
        "срез с одним проёмом не даёт сказать «соседний проём цел»")
    for key in seeds["wall_openings"]:
        assert rows[key]["category"] == "OST_SWallRectOpening"
    for key in seeds["wall_opening_hosts"]:
        assert rows[key]["category"] == "OST_Walls"


# ── 2. the corpus reality: the refusal NAMES THE REASON, not the
# category ─────────────────────────────────────────────────────────────
def test_a_wall_opening_without_a_captured_boundary_refuses_by_its_real_cause(wall_building):
    """183 real openings across three buildings came up as ATOMS — and the
    refusal says why.

    🔴 THIS IS THE WAVE'S MAIN NEGATIVE MOVE. Before 08.09.2026 what
    arrived here was `unsupported_category`: "this contract edits doors
    and floor openings only." Every word of it is formally true, and
    together they are untrue about the REASON: the category has been in
    the lifter's table since 04.09, it has an op, and what is missing is
    exactly the BOUNDARY in the capture. Such a refusal sent the reader
    off to look for a different category instead of recapturing — that
    is, it addressed the work at the wrong target.
    """
    capture = CE.open_capture(wall_building["path"])
    seeds = wall_building["seeds"]
    for key in seeds["wall_openings"]:
        node = capture.by_source.get(key) or {}
        assert node.get("kind") == "atom", (
            f"{wall_building['name']}: проём {key} вдруг поднялся опом — "
            f"перепись волны (0 из 183) устарела, предмет теста изменился")
        result = CE.edit_element(capture, key, {
            "opening_p0_mm": [0.0, 0.0, 0.0], "opening_p1_mm": [1000.0, 0.0, 2000.0]})
        refusal = result.refusal
        assert refusal is not None, "править нечего, а контракт согласился"
        assert refusal["code"] == "wall_opening_not_captured", refusal
        assert refusal["address"] == key
        detail = refusal["detail"]
        # The refusal must name WHAT IS MISSING, WHAT EXISTS INSTEAD, and
        # HOW IT IS FIXED.
        assert "BoundaryRect" in detail and "bbox_min_mm" in detail, detail
        assert "ПЕРЕСЪЁМКОЙ" in detail, detail
        assert "source_contract_gap" in detail, (
            "отказ обязан донести причину атома, а не заменить её своей")
        # And must NOT point to a different category.
        assert "floor openings only" not in detail


def test_the_refusal_is_not_the_old_category_refusal(wall_building):
    """The wall-opening refusal DIFFERS from the refusal for a genuinely
    unsupported category.

    🔴 AN INSTRUMENT WITH ONE ANSWER FOR TWO DIFFERENT QUESTIONS MEASURES
    NOTHING. A check that "a refusal arrived" would have been green even
    before the fix: it arrived before too. Here TWO different addresses
    in the same capture are compared — a wall opening and an element of a
    category the contract does not know at all — and the codes must
    DIVERGE.
    """
    capture = CE.open_capture(wall_building["path"])
    opening = wall_building["seeds"]["wall_openings"][0]
    foreign = next((key for key, element in capture.elements.items()
                    if element.category not in ("OST_Doors", "OST_Floors",
                                                "OST_Ceilings", "OST_SWallRectOpening")
                    and not str(element.category or "").endswith("FloorOpening")), None)
    assert foreign is not None, "в срезе нет ни одной чужой категории — контроль пуст"

    theirs = CE.edit_element(capture, opening, {"opening_p0_mm": [0.0, 0.0, 0.0]})
    other = CE.edit_element(capture, foreign, {"opening_p0_mm": [0.0, 0.0, 0.0]})
    assert theirs.refusal["code"] == "wall_opening_not_captured"
    assert other.refusal["code"] == "unsupported_category"
    assert theirs.refusal["code"] != other.refusal["code"]


def test_a_wall_opening_is_not_routed_into_the_slab_contract(wall_building):
    """A wall opening does NOT fall into the slab-hole branch — neither by
    field nor by code.

    The "remove the category validator" hypothesis is checked by
    execution: an edit using SLAB fields on a wall opening must refuse
    under its own code, not `opening_*`.
    """
    capture = CE.open_capture(wall_building["path"])
    key = wall_building["seeds"]["wall_openings"][0]
    result = CE.edit_element(capture, key, {"opening_index": 0,
                                            "opening_contour_mm": [[0, 0], [1, 0], [1, 1]]})
    assert result.refusal["code"] == "unsupported_wall_opening_field", result.refusal
    assert "opening_p0_mm" in result.refusal["detail"]


# ── 3. a supported opening: TWO edits through a reopen ────────────────────
def test_a_supported_wall_opening_changes_twice_across_a_reopen(supported, tmp_path):
    """Two edits to size and position, with a save and a reopen between
    them.

    The subject is not "the edit applied" but "the edit SURVIVED closing":
    the second move edits what was already read back from disk, and both
    edits must be in the log.
    """
    key = API.DEMO_WALL_OPENING
    capture = CE.open_capture(supported)
    was_p0, was_p1 = _corners(capture, key)
    assert was_p0 == [6000.0, 0.0, 900.0] and was_p1 == [7000.0, 0.0, 2100.0]

    # 1) wider and with a lower sill — size AND position
    first = ([6000.0, 0.0, 800.0], [7500.0, 0.0, 2200.0])
    assert CE.edit_element(capture, key, {"opening_p0_mm": first[0],
                                          "opening_p1_mm": first[1]}).refusal is None
    saved = CE.save(capture, tmp_path / "save-1")

    reopened = CE.open_capture(saved)
    assert len(reopened.edits) == 1, "первая правка не пережила сохранение"
    assert _corners(reopened, key) == first

    # 2) a shift along the wall without changing the size
    second = ([8000.0, 0.0, 800.0], [9500.0, 0.0, 2200.0])
    assert CE.edit_element(reopened, key, {"opening_p0_mm": second[0],
                                           "opening_p1_mm": second[1]}).refusal is None
    saved2 = CE.save(reopened, tmp_path / "save-2")

    final = CE.open_capture(saved2)
    assert len(final.edits) == 2, "две правки — две строки журнала"
    assert final.edit_binding == "before_value"
    assert final.revision_binding == "pinned"
    assert _corners(final, key) == second
    # The `before` binding names the PRIOR value, not a copy of the new
    # one.
    assert final.edits[0]["before"] == {"opening_p0_mm": list(was_p0),
                                        "opening_p1_mm": list(was_p1)}
    assert final.edits[1]["before"] == {"opening_p0_mm": list(first[0]),
                                        "opening_p1_mm": list(first[1])}


def test_the_neighbours_of_an_edited_wall_opening_stay_byte_identical(supported, tmp_path):
    """Neighbors are intact BYTE-FOR-BYTE: exactly one node changed, and
    only that one.

    🔴 THE COMPARISON MUST BE CAPABLE OF TURNING RED. If `moved` were
    computed from a list of nodes with some difference, and that list was
    always empty, the check would stay green even for a rewritten
    building. So a control stands alongside it: a neighbor rewritten by
    hand must land in `moved`.
    """
    key = API.DEMO_WALL_OPENING
    capture = CE.open_capture(supported)
    before = {str(node.get("_id")): json.dumps(node, sort_keys=True, ensure_ascii=False)
              for node in capture.nodes}
    changed = CE.edit_element(capture, key, {"opening_p0_mm": [6000.0, 0.0, 700.0],
                                             "opening_p1_mm": [7200.0, 0.0, 2300.0]})
    assert changed.refusal is None
    assert changed.untouched_count == len(capture.elements) - 1
    after = {str(node.get("_id")): json.dumps(node, sort_keys=True, ensure_ascii=False)
             for node in capture.nodes}
    moved = sorted(name for name in before if before[name] != after.get(name))
    assert moved == list(changed.changed_ops), (
        f"сдвинулось {moved}, а правка отчиталась о {list(changed.changed_ops)}")
    assert len(moved) == 1

    # CONTROL: the comparison is not blind.
    neighbour = next(node for node in capture.nodes
                     if str(node.get("_id")) not in moved)
    neighbour["params"] = dict(neighbour.get("params") or {}, __контроль__=1)
    after2 = {str(node.get("_id")): json.dumps(node, sort_keys=True, ensure_ascii=False)
              for node in capture.nodes}
    moved2 = sorted(name for name in before if before[name] != after2.get(name))
    assert len(moved2) == 2, f"сравнение соседей слепо: {moved2}"


# ── 4. export: it compiles and CARRIES THE REQUESTED NUMBERS BY LAW ───────
@pytest.mark.parametrize("version", ("2023", "2026"))
def test_the_export_of_an_edited_wall_opening_compiles_under_both_versions(
        supported, version):
    """The export compiles for 2023 and 2026, and the call carries EXACTLY
    the requested corners."""
    key = API.DEMO_WALL_OPENING
    capture = CE.open_capture(supported)
    asked = ([6000.0, 0.0, 850.0], [7400.0, 0.0, 2250.0])
    assert CE.edit_element(capture, key, {"opening_p0_mm": asked[0],
                                          "opening_p1_mm": asked[1]}).refusal is None
    programs, sources = CE.export_program(capture, revit_version=version)
    assert len(programs) == len(sources) and len(programs) > 0
    text = "\n".join(sources)
    calls = _emitted_corners(text)
    assert len(calls) == 1, f"NewOpening в выпуске {len(calls)} раз, ожидался 1"
    assert calls[0] == asked, f"в C# уехали углы {calls[0]}, а просили {asked}"


def test_the_witness_numbers_move_by_the_law_not_by_the_substring(supported):
    """🔴 CHECKED AGAINST THE LAW, NOT AGAINST A SUBSTRING, AND THE LAW IS
    RETOLD, NOT CALLED.

    The C# witness checks three quantities against the built opening: the
    band's lower and upper elevations and the width along the wall. Here
    they are computed by arithmetic on the op's postcondition wording
    (`_law`), not by calling the emitter, and they must match the numbers
    that actually made it into the text. A check for "the substring 7400
    is present in the C#" would stay green even from a coincidental match
    with an unrelated number.
    """
    key = API.DEMO_WALL_OPENING
    capture = CE.open_capture(supported)
    base = _witness_numbers(_emitted(capture, "2026"))
    assert len(base) == 1, f"свидетелей проёма в выпуске {len(base)}, ожидался 1"
    p0, p1 = _corners(capture, key)
    assert base[0] == pytest.approx(_law(p0, p1)), (
        "свидетель НЕисправленного проёма уже не сходится с законом — "
        "мерить сдвиг после этого бессмысленно")

    asked = ([6000.0, 0.0, 850.0], [7400.0, 0.0, 2250.0])
    assert CE.edit_element(capture, key, {"opening_p0_mm": asked[0],
                                          "opening_p1_mm": asked[1]}).refusal is None
    now = _witness_numbers(_emitted(capture, "2026"))
    assert len(now) == 1
    assert now[0] == pytest.approx(_law(*asked)), (
        f"свидетель несёт {now[0]}, а закон по заданным углам даёт {_law(*asked)}")
    # And the number ACTUALLY moved: an instrument whose reading does not
    # depend on the subject measures nothing.
    assert now[0] != base[0]


def test_a_broken_opening_formula_is_caught_by_the_number_not_by_the_text(supported):
    """FAIL control: a corrupted opening formula → the C# number no longer
    matches → red.

    🔴 THIS IS A CHECK ON THE INSTRUMENT, NOT ON THE SUBJECT. What is
    corrupted is the RESULT of the edit in the node — exactly as a bug in
    the contract's formula would corrupt it — and the law-based check must
    see this. The export, meanwhile, KEEPS compiling: exactly why "the
    export is green" proves nothing by itself.
    """
    key = API.DEMO_WALL_OPENING
    capture = CE.open_capture(supported)
    asked = ([6000.0, 0.0, 850.0], [7400.0, 0.0, 2250.0])
    assert CE.edit_element(capture, key, {"opening_p0_mm": asked[0],
                                          "opening_p1_mm": asked[1]}).refusal is None

    # corruption: the width drifted by 500 mm, everything else in place
    capture.by_source[key]["params"]["p1_mm"] = [7900.0, 0.0, 2250.0]
    programs, sources = CE.export_program(capture, revit_version="2026")
    text = "\n".join(sources)
    assert len(programs) > 0 and "NewOpening" in text, (
        "экспорт обязан ПРОДОЛЖАТЬ компилироваться — иначе контроль ловил бы "
        "поломку выпуска, а не расхождение числа")
    broken = _witness_numbers(text)
    assert len(broken) == 1
    assert broken[0] != pytest.approx(_law(*asked)), (
        "формула испорчена, а сверка по закону этого НЕ ЗАМЕТИЛА — прибор слеп")
    # And the discrepancy is specifically in the width, not "somewhere."
    assert broken[0][0] == pytest.approx(_law(*asked)[0])
    assert broken[0][1] == pytest.approx(_law(*asked)[1])
    assert broken[0][2] - _law(*asked)[2] == pytest.approx(500.0)


# ── 5. an unsupported shape — refusal BY NAME ─────────────────────────────
@pytest.mark.parametrize("change,code,why", [
    ({"opening_p0_mm": [6000.0, 0.0]}, "bad_change_value",
     "плоская точка уехала бы на отметку 0, а высота проёма — это ровно Z"),
    ({"opening_p0_mm": [6000.0, 0.0, float("nan")]}, "non_finite_value",
     "NaN — не координата"),
    ({"opening_p0_mm": [6e9, 0.0, 900.0]}, "value_out_of_contract",
     "за пределом сцены: почти всегда метры вместо миллиметров"),
    ({"opening_p0_mm": [6000.0, 0.0, 900.0],
      "opening_p1_mm": [6000.2, 0.0, 900.1]}, "wall_opening_degenerate",
     "это не маленький проём, а отсутствие проёма"),
    ({"offset_mm": 100.0}, "unsupported_wall_opening_field",
     "поле двери у проёма — не поле проёма"),
    ({}, "empty_change", "правка обязана назвать хотя бы одно поле"),
])
def test_an_unsupported_wall_opening_change_refuses_by_name(supported, change, code, why):
    """Everything the contract cannot do is a REFUSAL BY NAME, not a
    silent success."""
    capture = CE.open_capture(supported)
    before = copy.deepcopy(capture.by_source[API.DEMO_WALL_OPENING])
    result = CE.edit_element(capture, API.DEMO_WALL_OPENING, change)
    assert result.refusal is not None, f"{why}: контракт согласился"
    assert result.refusal["code"] == code, result.refusal
    # A PARTIAL RESULT DECLARED AS A REFUSAL IS THE SAME UNTRUTH.
    assert capture.by_source[API.DEMO_WALL_OPENING] == before, (
        "отказ оставил в узле часть правки")
    assert capture.edits == [], "отказ дописал строку в журнал"


def test_a_host_face_opening_is_refused_by_its_variety(supported):
    """The `host_face` kind is defined by a PROFILE — an edit of two
    corners would say the wrong thing about it."""
    capture = CE.open_capture(supported)
    node = capture.by_source[API.DEMO_WALL_OPENING]
    node["params"]["variety"] = "host_face"
    result = CE.edit_element(capture, API.DEMO_WALL_OPENING,
                             {"opening_p0_mm": [6000.0, 0.0, 900.0]})
    assert result.refusal["code"] == "wall_opening_variety_not_editable", result.refusal
    assert "host_face" in result.refusal["detail"]


# ── 6. the ledger tells the truth about the opening, and the unknown is
# not zeroed out ──────────────────────────────────────────────────────────
def test_the_ledger_names_what_a_wall_opening_represents_and_what_it_loses(supported):
    """The field ledger names the state of EVERY opening field — using an
    outside ledger.

    🔴 THE STATE IS TAKEN FROM `field_ledger`, NOT FROM US. A homegrown
    formula of "the name occurs in the node's text" would give a second
    answer to the same question.
    """
    capture = CE.open_capture(supported)
    read = API.read_element(capture, API.DEMO_WALL_OPENING)
    assert read.category == "OST_SWallRectOpening"
    assert read.node_kind == "op" and read.op_name == "create_opening"
    assert read.field_states_from == "kir.decompile.field_ledger"
    assert set(read.editable_fields) == set(CE._WALL_OPENING_FIELDS), (
        "публичная дверь обязана называть, ЧТО именно здесь правится")

    states = {item.field: item.state for item in read.fields}
    assert states, "ведомость молчит о проёме целиком"
    assert set(states.values()) <= set(("represented", "approximate",
                                        "source_data", "unknown"))
    # The node carries the opening's boundary via TWO slots (`params.p0_mm`
    # + `params.p1_mm`) — meaning it is REPRESENTED, not lost. Before
    # 08.09.2026 the ledger looked for a bearer under ONE name and called
    # it `unknown`: a false loss, calling finished work unfinished.
    assert states.get("opening_boundary_mm") == "represented", states
    # 🔴 AND EXACTLY AS MUCH AS THERE IS. `IsRectBoundary` is NOT present
    # in the node: rectangularity is stated via the kind
    # (`variety="wall_rect"`), which is a different assertion, and
    # crediting it as carrying the flag over would overstate
    # representation. The ledger must keep calling the flag lost.
    assert states.get("opening_is_rect") != "represented", (
        "ведомость записала в представленные то, чего узел не несёт")
    # The bounding box is not a bearer either: a box is not the opening's
    # rectangle.
    assert states.get("bbox_min_mm") != "represented", states
    # The opening's host is named by a reference, and the relationship is
    # proven.
    assert read.host is not None and read.host.element_id == API.DEMO_WALL
    assert read.host.category == "OST_Walls"
    # Every LOST field must carry a reason, not emptiness.
    for item in read.fields:
        if item.state != "represented":
            assert item.why, f"{item.field}: состояние {item.state} без причины"


def test_an_edit_does_not_zero_what_the_contract_does_not_know(supported):
    """The unknown is NOT ZEROED OUT: editing two corners does not touch
    the rest of the node.

    🔴 "NOTHING CHANGED" IN RESPONSE TO A REQUEST TO CHANGE SOMETHING IS
    THE WORST UNTRUTH, but silently ZEROING a neighboring field is the
    same breed. Here the node is checked in full, key by key: only
    `p0_mm`/`p1_mm` are allowed to move.
    """
    key = API.DEMO_WALL_OPENING
    capture = CE.open_capture(supported)
    before = copy.deepcopy(capture.by_source[key])
    assert CE.edit_element(capture, key, {"opening_p0_mm": [6100.0, 0.0, 950.0],
                                          "opening_p1_mm": [7100.0, 0.0, 2050.0]}
                           ).refusal is None
    after = capture.by_source[key]
    assert set(after) == set(before), (
        f"состав узла изменился: {sorted(set(after) ^ set(before))}")
    assert set(after["params"]) == set(before["params"]), (
        f"состав параметров изменился: "
        f"{sorted(set(after['params']) ^ set(before['params']))}")
    moved = sorted(name for name in before["params"]
                   if before["params"][name] != after["params"][name])
    assert moved == ["p0_mm", "p1_mm"], moved
    # Everything that is not the parameters is byte-for-byte identical.
    assert {k: v for k, v in after.items() if k != "params"} == \
           {k: v for k, v in before.items() if k != "params"}


# ── 7. the public door: reads, proposes WITHOUT WRITING, applies ──────────
def test_the_public_door_proposes_a_wall_opening_patch_without_writing(supported, tmp_path):
    """`propose_patch` computes the diff and writes NOTHING — not to
    memory, not to disk."""
    key = API.DEMO_WALL_OPENING
    capture = CE.open_capture(supported)
    snapshot = {item.name: item.read_bytes()
                for item in sorted(supported.iterdir()) if item.is_file()}
    node_before = copy.deepcopy(capture.by_source[key])

    proposal = API.propose_patch(capture, key,
                                 {"opening_p0_mm": [6000.0, 0.0, 800.0],
                                  "opening_p1_mm": [7500.0, 0.0, 2200.0]},
                                 source_binding=API.source_binding(capture))
    assert proposal.admissible and proposal.refusal is None
    assert proposal.wrote_nothing
    assert proposal.diff, "предпросмотр без diff ничего не показывает"
    assert proposal.before == {"opening_p0_mm": [6000.0, 0.0, 900.0],
                               "opening_p1_mm": [7000.0, 0.0, 2100.0]}
    assert capture.by_source[key] == node_before, "предпросмотр написал в память"
    assert capture.edits == [], "предпросмотр дописал журнал"
    assert {item.name: item.read_bytes()
            for item in sorted(supported.iterdir()) if item.is_file()} == snapshot

    applied = API.apply_patch(capture, key,
                              {"opening_p0_mm": [6000.0, 0.0, 800.0],
                               "opening_p1_mm": [7500.0, 0.0, 2200.0]},
                              before=proposal.before,
                              source_binding=API.source_binding(capture))
    assert applied.refusal is None and applied.edits == 1
    assert _corners(capture, key) == ([6000.0, 0.0, 800.0], [7500.0, 0.0, 2200.0])


def test_the_public_door_still_names_the_three_older_categories(supported):
    """An extension is not a replacement: doors and slabs/ceilings remain
    where they were.

    A guard for app-3, which reads these same doors: the list of editable
    things must GROW, not change shape.
    """
    assert set(API._EDITABLE) == {"OST_Doors", "OST_Floors", "OST_Ceilings",
                                  "OST_SWallRectOpening"}
    assert API._EDITABLE["OST_Doors"] == CE._DOOR_FIELDS
    assert API._EDITABLE["OST_Floors"] == CE._OPENING_FIELDS
    assert API._EDITABLE["OST_Ceilings"] == CE._OPENING_FIELDS
    assert API._EDITABLE["OST_SWallRectOpening"] == CE._WALL_OPENING_FIELDS
    # The field lists are DIFFERENT sets: merged together, they would
    # edit the wrong thing.
    assert not set(CE._WALL_OPENING_FIELDS) & set(CE._OPENING_FIELDS)
    assert not set(CE._WALL_OPENING_FIELDS) & set(CE._DOOR_FIELDS)


def test_the_default_demo_capture_has_no_wall_opening(tmp_path):
    """The default of `write_demo_capture` DID NOT SHIFT: the fifth
    element is by request only.

    The instructions, the scenario guard, and the acceptance test all
    rest on the demo; silently changing it would have the wave's fix
    moving their subject instead of its own.
    """
    plain = tmp_path / "plain"
    API.write_demo_capture(plain)
    rows = _l0_rows(plain)
    assert len(rows) == 4
    assert not [key for key, row in rows.items()
                if row["category"] == "OST_SWallRectOpening"]

    withop = tmp_path / "withop"
    API.write_demo_capture(withop, wall_opening=True)
    rows2 = _l0_rows(withop)
    assert len(rows2) == 5
    assert [key for key, row in rows2.items()
            if row["category"] == "OST_SWallRectOpening"] == [API.DEMO_WALL_OPENING]


# ── 8. the slice is REPRODUCIBLE from the corpus — meaning it was not
# hand-edited ─────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _CORPUS.is_dir(), reason="корпуса нет на этой машине")
def test_a_wall_slice_is_reproducible_from_the_corpus(wall_building, tmp_path):
    """Cut it again — the bytes are the same. The cutter's arguments are
    taken FROM THE SLICE ITSELF."""
    from kir.decompile.tests.capture_slices import make_slice

    meta = wall_building["meta"]
    run = meta["срез_чего"]
    if not (_CORPUS / run).is_dir():
        pytest.skip(f"прогона {run} нет в корпусе этой машины")
    out = tmp_path / "recut"
    make_slice.main(["--run", run, "--out", str(out), "--corpus", str(_CORPUS),
                     "--subject", meta["предмет"]])

    have = {item.name: item.read_bytes()
            for item in sorted((SLICES / wall_building["name"]).iterdir())
            if item.is_file()}
    made = {item.name: item.read_bytes()
            for item in sorted(out.iterdir()) if item.is_file()}
    assert set(have) == set(made), (
        f"состав среза разошёлся: лишние {sorted(set(have) - set(made))}, "
        f"недостающие {sorted(set(made) - set(have))}")
    differ = sorted(name for name in have if have[name] != made[name])
    assert differ == [], f"{wall_building['name']}: срез не воспроизводится по {differ}"


@pytest.mark.skipif(not (_CORPUS / "bench_A").is_dir(), reason="корпуса нет")
def test_the_whole_bench_building_gives_the_same_answer_as_its_slice():
    """A THIRD building, and it is WHOLE: the slice did not fit the answer
    by trimming its size.

    `bench_A` carries 12 wall openings, and all 12 must give the same
    named refusal as the two openings in the slice. This is also where
    the wave's number is re-checked: if even one comes up as an op, the
    corpus was recaptured and the test's subject has changed.
    """
    capture = CE.open_capture(_CORPUS / "bench_A")
    keys = [key for key, element in capture.elements.items()
            if element.category == "OST_SWallRectOpening"]
    assert len(keys) == 12, f"в bench_A проёмов стен {len(keys)}, перепись знала 12"
    codes = set()
    for key in keys:
        assert (capture.by_source.get(key) or {}).get("kind") == "atom"
        result = CE.edit_element(capture, key, {"opening_p0_mm": [0.0, 0.0, 0.0],
                                                "opening_p1_mm": [1000.0, 0.0, 2000.0]})
        codes.add(result.refusal["code"])
    assert codes == {"wall_opening_not_captured"}, codes
