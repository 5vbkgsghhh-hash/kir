"""THE INDEX OF AN EXISTING BUILDING — what an author searches the way one
searches a repository.

WHY. The catalog (`sandbox.ModelCatalog`) answers "what can I build with":
levels, axes, TYPE pools. Nobody answered the question "what is already
standing here": the four query ops (`query_count`/`query_list`/
`query_inspect`/`query_types`) are OPERATIONS inside the program, i.e. a
trip to Revit, and the answer arrives in the RECEIPT, not in the script's
hands. You cannot branch on what was found.

Because of this, the "did → looked → analyzed → fixed" loop broke apart
into turns: finding an element was a turn, looking was a turn, fixing was a
turn. Here it is assembled into one: the index arrives in the same stdin
frame as the catalog, and the author searches it locally.

═══════════════════════════════════════════════════════════════════════════
THE CEILING IS SET BY MEASUREMENT, NOT BY TASTE (15.08.2026)
═══════════════════════════════════════════════════════════════════════════

The sandbox child lives under `DEFAULT_MEMORY_MB = 256` and
`DEFAULT_CPU_SECONDS = 5.0`. Measured on three real buildings from the
corpus, the row rounded to whole millimeters:

    building              elements    index      B/elem  parse   process RSS
    sob62_r23_v5             1 510    0.29 MB    193   0.01 s      36 MB
    snowdon_plumb_v3          6 556    0.99 MB    150   0.03 s      47 MB
    k2_ar_rd_v15            115 889   16.68 MB    143   0.39 s     268 MB  ← OVER

The binding constraint is MEMORY, not time: parsing the tower costs 0.39 s
out of five, but the process runs into 268 MB against a ceiling of 256.
Hence `CEILING_BYTES = 8 MB` — the same value already used as the result's
transport ceiling (`sandbox.MAX_RESULT_BYTES`), not a new number pulled
from thin air.

**59 of 71 corpus parses fit whole** under this ceiling (measured by
`L0.jsonl` size; the index/L0 ratio holds at 0.19–0.21 across all three).

ROUNDING TO THE MILLIMETER is also measured: without it a row weighs
320–427 B, with it 143–193 B. A building is designed in millimeters;
seventeen significant digits in a search index describe not the building
but the double-precision format.

═══════════════════════════════════════════════════════════════════════════
THREE OUTCOMES, AND NOT ONE STAYS SILENT
═══════════════════════════════════════════════════════════════════════════

The same law as for the catalog (`sandbox.ModelCatalog._rows`), set up here
not by symmetry but because the cost of being wrong is the same:

* **`tier="full"`** — all elements arrived. An empty search result is a
  fact ABOUT THE BUILDING: there is no such thing in it, the author
  branches;
* **`tier="census"`** — the building did not fit, only the census arrived.
  The search REFUSES and names the count, the ceiling, and a way to narrow
  it. An empty result here would be a lie: we did not look;
* **there is no index at all** — a third kind of refusal: "not supplied."

A silent empty list for all three cases is exactly the defect
`ModelCatalog` already cost once ("no pool. Got: (catalog not supplied)" —
both statements false).

WHAT THIS MODULE DOES NOT DO. It does not read Revit. It projects an
ALREADY-read L0 — a fresh snapshot of the turn or a saved parse. Live
re-reading of the document for the index is separate work with its own trip
cost, and it is NAMED, not implied.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Iterator, Mapping

#: The index's transport ceiling. The rationale is in the module header: it
#: is tied to the child's memory (256 MB), not to parse time. The value is
#: taken from the already-existing result ceiling, so as not to set up a
#: second number of the same kind.
CEILING_BYTES: int = 8 * 1024 * 1024

#: How many elements one search returns if the author has not named their
#: own limit. This is a CEILING ON THE ANSWER, not on the index: truncation
#: must be declared, so `find` always also returns the full count found
#: (`total`).
DEFAULT_FIND_LIMIT: int = 200

#: The index's kind. A closed list: there is no third value, and adding one
#: silently is not allowed — `BuildingIndexError` parses exactly these two
#: plus absence.
TIER_FULL = "full"
TIER_CENSUS = "census"


class BuildingIndexError(RuntimeError):
    """There is no index, or it does not answer this question — WITH A
    REASON.

    A separate type, not `ValueError`: "the building did not fit" and
    "there is no such thing in the building" must be distinguishable by the
    caller, not read off the text.
    """


def _mm(triple: Any) -> list[int] | None:
    """A point in whole millimeters. See the argument about rounding in the module header."""
    if not triple:
        return None
    try:
        return [int(round(float(v))) for v in triple]
    except (TypeError, ValueError):
        return None


def _row(element: Any) -> dict[str, Any]:
    """One index row — a "file" of this repository.

    Fields are chosen by WHAT THE SEARCH DECIDES: address, category, level,
    type, geometry, host. Parameters are NOT included here: measured at
    2.4–3.6 per element, but they are exactly what produces the 320→143 B
    weight spread. A single element with all its parameters is returned by
    `get()`, and that is exactly `read file:line` against `grep`.
    """
    # 🔴 ONE QUANTITY — ONE REPRESENTATION. The first draft put `None` into
    # the row and `"?"` into the census (a JSON key must be a string), and
    # `levels()` returned a level that `find(lvl=…)` could never find. The
    # same named defect: a quantity declared in one place and read in
    # another. `"?"` means "the element carries no level" — that is a fact
    # ABOUT THE BUILDING, not a gap.
    row: dict[str, Any] = {
        "id": element.element_id,
        "cat": element.category or "?",
        "lvl": element.level_name or "?",
        "type": element.type_name or "?",
    }
    for key, value in (("p0", _mm(element.p0_mm)), ("p1", _mm(element.p1_mm)),
                       ("b0", _mm(element.bbox_min_mm)),
                       ("b1", _mm(element.bbox_max_mm))):
        if value is not None:
            row[key] = value
    if element.host_id:
        row["host"] = element.host_id
    return row


def _params(element: Any) -> dict[str, Any]:
    """Element parameters as-is — only for `get()`, one at a time."""
    raw = getattr(element, "params", None)
    return dict(raw) if isinstance(raw, Mapping) else {}


def _frame_bytes(payload: Mapping[str, Any]) -> int:
    """The frame's length EXACTLY in the form it will go out in."""
    return len(json.dumps(payload, ensure_ascii=False,
                          separators=(",", ":"), default=str).encode("utf-8"))


def _stamp_frame_bytes(payload: dict[str, Any]) -> int:
    """Set `bytes` so that it equals the LENGTH OF THE FRAME ITSELF.

    🔴 AN INSTRUMENT THAT MEASURES SOMETHING OTHER THAN WHAT IT RETURNS
    GUARDS NOTHING (30.08.2026, audit finding F-294). The size was measured
    WITHOUT the `bytes` field, compared against the ceiling, and only then
    appended — meaning the declared number was smaller than the real frame
    by exactly the length of `,"bytes":NNN`, and at the boundary the
    instrument declared `tier=full` and returned a frame LARGER than the
    ceiling it exists to enforce.

    🔴 WHY A LOOP, NOT TWO PASSES. Appending the number lengthens its own
    written form, and at a digit-count boundary two passes are NOT ENOUGH —
    verified by execution: with suitable padding, after two passes the
    declared value was 100 for a frame of 101. The fixed point is found by
    a loop and reached in two to three steps.

    🔴 WHY THE LARGER VALUE IS TAKEN WHEN IT DOES NOT CONVERGE. Oscillation
    between two values is theoretically possible at a digit-count boundary;
    understating the size means bringing back the original defect,
    overstating it means handing the frame to the census one byte early.
    The error must lean toward caution.
    """
    payload["bytes"] = 0
    seen: list[int] = []
    for _ in range(8):
        size = _frame_bytes(payload)
        if payload["bytes"] == size:
            return size
        seen.append(size)
        payload["bytes"] = size
    payload["bytes"] = max(seen)
    return payload["bytes"]


def build_index(elements: Iterable[Any],
                *,
                ceiling_bytes: int = CEILING_BYTES) -> dict[str, Any]:
    """A bounded building index built from the L0 stream of elements.

    🔴 THE CALL SHAPE IS PART OF THE CONTRACT. What goes in here is the
    stream of ELEMENTS (`L0JSONLReader.iter_elements()`), not the document
    and not `metadata()`: the header carries levels and axes, and
    `elements` in it is empty BY CONSTRUCTION, and whoever feeds it in will
    get "0 elements" on a building that has 115 889. This trap is already
    named by name in this tree and has already cost a false conclusion — we
    do not repeat it.

    Returns a dict fit for an stdin frame. The census is ALWAYS built: it
    weighs kilobytes and answers "what is even here" even when the
    per-element layer did not fit.
    """
    rows: list[dict[str, Any]] = []
    params: dict[str, dict[str, Any]] = {}
    by_category: dict[str, int] = {}
    by_level: dict[str, int] = {}
    total = 0

    for element in elements:
        total += 1
        row = _row(element)
        rows.append(row)
        detail = _params(element)
        if detail:
            params[row["id"]] = detail
        by_category[row["cat"]] = by_category.get(row["cat"], 0) + 1
        by_level[row["lvl"]] = by_level.get(row["lvl"], 0) + 1

    # 🔴 ORDER IS NOT DECLARED HERE, AND THAT IS A MEASUREMENT, NOT
    # LAZINESS (15.08.2026). The first draft sorted the census by
    # descending count — and the order was SILENTLY LOST: the stdin frame
    # is serialized with `sort_keys=True` (otherwise the index signature is
    # not reproducible), and the dict arrived at the author's end in
    # alphabetical order. "Top categories" returned `OST_CableTray: 1` as
    # the first row on a building with 695 walls. A quantity declared in
    # one place and rewritten in another — our own named defect, committed
    # inside the very fix meant to remove it.
    # Order is now decided WHERE IT IS READ: `BuildingView.top()`.
    census = {
        "total": total,
        "by_category": by_category,
        "by_level": by_level,
    }

    payload: dict[str, Any] = {"tier": TIER_FULL, "census": census,
                               "elements": rows, "params": params,
                               # The field is set up BEFORE the
                               # measurement: the key must take part in
                               # serialization from the FIRST pass,
                               # otherwise the same defect repeats one
                               # level down.
                               "bytes": 0}
    size = _stamp_frame_bytes(payload)
    # What is compared is WHAT WILL ACTUALLY GO OUT, not what it was before
    # the field was appended.
    if size <= ceiling_bytes:
        return payload

    # OVER THE LIMIT. Silently truncating the list is not allowed: a
    # truncated index looks complete, and a search against it will return
    # "not found" where the element exists. We return the census and NAME
    # why the per-element layer is absent.
    census_only: dict[str, Any] = {
        "tier": TIER_CENSUS,
        "census": census,
        "elements": [],
        "params": {},
        "bytes": 0,
        "refused": (
            "здание не поместилось в индекс: %d элементов, %.1f МБ при потолке "
            "%.1f МБ. Приехала перепись — по ней видно, что и на каких уровнях "
            "есть. Поэлементный поиск по этому зданию недоступен, пока область "
            "не сужена."
            % (total, size / 1e6, ceiling_bytes / 1e6)),
    }
    # The refusal branch suffered the same problem: the number was computed
    # BEFORE assignment (F-294).
    _stamp_frame_bytes(census_only)
    return census_only


def observations_of(document: Any, *, building_id: str | None = None
                    ) -> tuple[list[dict], str]:
    """Observations about the BUILT building — ready-made, for the frame.

    The PARENT computes them and puts them in the index. The point is not
    convenience: the sandbox child lives under `DEFAULT_CPU_SECONDS = 5.0`,
    and a building judge is not obliged to fit in five seconds, and a
    script whose judge ate the budget will not finish the program. The
    environment computes — the author reads and branches.

    A judge's refusal IS DATA: it comes back as the other half of the
    pair, not as an exception, otherwise "the rules are silent" would
    become indistinguishable from "the rules never ran."
    """
    try:
        from kir.assembly_view import observe_l0
        view = observe_l0(document, building_id=building_id)
    except Exception as exc:  # noqa: BLE001 — a judge's refusal is data
        return [], "%s: %s" % (type(exc).__name__, exc)
    out: list[dict] = []
    for obs in getattr(view, "observations", ()) or ():
        try:
            out.append(obs.to_dict())
        except Exception:  # noqa: BLE001 — the observation's shape belongs to someone else
            out.append({"code": str(getattr(obs, "code", "?"))})
    silent = getattr(view, "silent_sources", None)
    return out, ("; ".join(f"{k}: {v}" for k, v in silent.items())
                 if isinstance(silent, dict) and silent else "")


def index_from_run(run_dir: str,
                   *,
                   ceiling_bytes: int = CEILING_BYTES,
                   with_observations: bool = False) -> dict[str, Any]:
    """An index over a SAVED parse — an offline entry point, no bridge, no
    Revit.

    The live entry point (re-reading an open document for the index) is
    SEPARATE work with its own trip cost; it is named here, not implied.

    🔴 `with_observations` builds the WHOLE DOCUMENT — header plus
    elements. `metadata()` alone returns only the header, and `elements`
    in it is empty BY CONSTRUCTION: whoever feeds it to the judge will get
    "0 walls" on a building with 695 walls. The trap is named by name in
    this tree and has already cost a false conclusion.
    """
    import dataclasses
    import os

    from kir.decompile.extract import L0JSONLReader

    path = os.path.join(run_dir, "L0.jsonl")
    # 🔴 EXISTENCE IS ASKED OF THE PROD HELPER, NOT OF THE FS DIRECTLY. A
    # bare `os.path.exists` on the RAW name declares a compressed parse
    # absent — and the refusal below confidently calls this a "fact ABOUT
    # THE RUN," though it is a fact about our own reading. Caught
    # 20.08.2026 by the very first control after compression was turned
    # on: six parses became invisible to nine readers at once.
    from kir.decompile.snapshot_io import snapshot_file_exists
    if not snapshot_file_exists(path):
        raise BuildingIndexError(
            "разбор %r не несёт L0.jsonl — индекс строить не из чего. Это факт "
            "о ПРОГОНЕ, а не о здании" % run_dir)
    payload = build_index(L0JSONLReader(path).iter_elements(),
                          ceiling_bytes=ceiling_bytes)
    if with_observations:
        reader = L0JSONLReader(path)
        document = dataclasses.replace(
            reader.metadata(), elements=tuple(reader.iter_elements()))
        observations, silent = observations_of(document)
        payload["observations"] = observations
        if silent:
            payload["observations_silent"] = silent
    return payload


def index_from_query(query: str,
                     *,
                     root: Any = None,
                     ceiling_bytes: int = CEILING_BYTES,
                     with_observations: bool = False,
                     allow_census: bool = True) -> dict[str, Any]:
    """An index of the building SELECTED BY A QUERY, not by the header of
    an open document.

    THE SECOND SELECTION PATH, AND WHY IT EXISTS. `index_from_run` can
    assemble an index for any saved parse from disk — without a bridge and
    without Revit. But there was exactly one way to select a target:
    `clash.existing.resolve_run(doc_title)`, an exact match against the
    title of the document OPEN for the engineer. The model saw exactly the
    house that was open, and never a sample from the corpus.

    The measurement this is written for (17.08.2026): a model starting
    from a blank sheet produces 11 operations per attempt, a real floor of
    a residential tower carries 969, the median production building 1363.
    Given a REAL floor, the same model spent 433 s parsing the unit layout
    and found three defects in someone else's project. It writes little
    not because it is weak but because it never saw production — and
    production sits on disk and costs 62 KB to read (`corpus_catalog`).

    🔴 THIS IS A FIX TO SELECTION, NOT TO OUTPUT CONSTRUCTION. Having found
    the building, the function calls the very same `index_from_run` with
    the same ceiling and the same three outcomes; nothing about the
    index's shape is decided or duplicated here.

    THREE SELECTION OUTCOMES, AND TWO OF THEM ARE A NAMED REFUSAL:

    * ONE building found — returns the index plus `source_run`,
      `doc_name`, `chosen_rule`, and `runners_up`: the choice of parse
      within the building is DISCLOSED, not made silently (the law of
      `ground.py`);
    * SEVERAL found — `BuildingIndexError` with the list of matching
      buildings and their counts. Silently taking the first would mean
      handing the decision to the catalog's order, and this project has
      already paid once for a well-reputed `.FirstOrDefault()`;
    * NONE found — `BuildingIndexError`, naming the DICTIONARY one can
      reach through. A refusal that gives no next move equals silence for
      an LLM: it cannot see a screen and cannot "just look at the list
      itself."

    🔴 AND ONE THING THIS FUNCTION DOES NOT PROMISE. The chosen building
    may not fit under the ceiling — then `tier="census"` arrives with its
    own refusal, exactly as with any other input. Measured across the
    corpus: **48 of 52 parses with a card fit, 4 do not**
    (`k2_ar_rd_v6/v7/v8`, `demo-v3` — towers of 90–116 thousand elements).
    The estimate travels ahead of time, in `Entry.index_fits`, so that
    whoever selects the tower learns about the census BEFORE the build,
    not instead of the elements.

    `allow_census=False` is FOR WHOEVER CANNOT WAIT, and its cost is
    measured (17.08.2026, production corpus, venv 3.12):

        "kindergarten" -> sob62_r23_v5, 1510 elements, tier=full      0.44 s
        "residential tower" -> k2_ar_rd_v8, 115 880 elements, tier=census  11.7 s
        the whole catalog (the `fits_under` estimate by L0 size)          0.145 s

    Eleven seconds go into building 27.6 MB of rows, measuring them, and
    THROWING THEM AWAY, keeping only the census. The census is
    nonetheless an honest and needed answer — it cannot be gotten more
    cheaply, it IS the full pass — hence the default of `True`: silently
    swapping the answer for a refusal is not allowed. But a caller for
    whom the census is useless has the right to learn that in 0.18 s
    instead of 11.7 s, and then gets a REFUSAL WITH A REASON, not an empty
    index.
    """
    import os

    from kir.corpus_catalog import (FOUND_ONE, CorpusCatalogError,
                                         search)

    try:
        selection = search(query, root=root)
    except CorpusCatalogError as exc:
        # A REFUSAL FROM ELSEWHERE IS NAMED AS FROM ELSEWHERE AND IS NOT
        # TRIMMED BY SUBSTRING: cutting it would mean matching the LABEL
        # instead of the subject — a shape this tree has already been
        # caught by. "There is no corpus" and "there is no such thing in
        # the corpus" are DIFFERENT facts, and the first is not about
        # buildings at all.
        raise BuildingIndexError("каталог корпуса не собрался: %s" % exc)
    if selection.outcome != FOUND_ONE:
        raise BuildingIndexError(
            selection.refused
            or ("выбор по запросу %r не состоялся (%s)"
                % (query, selection.outcome)))
    building = selection.matched[0]
    entry = building.chosen
    # The estimate is asked about the SAME ceiling the build will use:
    # `entry.index_fits` knows only the standard one, and an early refusal
    # based on it would stay silent under a non-standard `ceiling_bytes`.
    if not allow_census and entry.fits_under(ceiling_bytes) is False:
        raise BuildingIndexError(
            "здание «%s» (разбор %s, элементов %s) заведомо не поместится в "
            "поэлементный индекс при потолке %.1f МБ — это видно по размеру "
            "L0 за 0.145 с, без сборки. Вызывающий отказался от переписи "
            "(`allow_census=False`), поэтому ответа нет, и это ОТКАЗ, а не "
            "пустое здание. Следующий ход: взять здание поменьше "
            "(в корпусе таких 48 из 52) либо разрешить перепись — она честна, "
            "но стоит около 11.7 с на этой башне"
            % (entry.doc_name, entry.run, entry.card.elements,
               ceiling_bytes / 1e6))
    # The root is taken FROM THE RUN, not recomputed a second time:
    # recomputing would be a second place obliged to match the first, and
    # it would drift apart at the very first mid-turn change of
    # `KUKAI_DECOMPILE_DATA`.
    payload = index_from_run(os.path.join(selection.root, entry.run),
                             ceiling_bytes=ceiling_bytes,
                             with_observations=with_observations)
    payload["source_run"] = entry.run
    payload["doc_name"] = entry.doc_name
    payload["query"] = selection.query
    payload["chosen_rule"] = building.rule
    payload["runners_up"] = [e.run for e in building.runners_up]
    if entry.labels:
        payload["labels"] = list(entry.labels)
    return payload


def matches(row: Mapping[str, Any], criteria: Mapping[str, Any]) -> bool:
    """Whether a row matches the search criteria.

    There is one rule and it is closed: string criteria (`cat`, `lvl`,
    `type`) are compared by SUBSTRING, case-insensitively — an author
    searches for "Walls" without remembering the exact `OST_Walls`;
    everything else is compared exactly. Case is dropped deliberately:
    `ground.by=name` in this tree already accepts a name case-insensitively,
    and a search stricter than grounding would send the author off to fix
    something that will in fact build.
    """
    for key, want in criteria.items():
        if want is None:
            continue
        got = row.get(key)
        if key in ("cat", "lvl", "type"):
            if got is None:
                return False
            if str(want).casefold() not in str(got).casefold():
                return False
        elif got != want:
            return False
    return True


def iter_matching(rows: Iterable[Mapping[str, Any]],
                  criteria: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    for row in rows:
        if matches(row, criteria):
            yield row


__all__ = [
    "CEILING_BYTES", "DEFAULT_FIND_LIMIT", "TIER_FULL", "TIER_CENSUS",
    "BuildingIndexError", "build_index", "index_from_run", "index_from_query",
    "matches", "iter_matching",
]
