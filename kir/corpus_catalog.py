"""THE CORPUS CATALOG OF PARSES — what the model uses to pick ITSELF a
building.

WHY. `building_index` can assemble the index of any saved parse
(`index_from_run`) — from disk, without the bridge and without Revit. But
the SELECTION of a parse was exactly one path: `clash.existing.
resolve_run(doc_title)`, an exact match against the title of the document
OPEN for the engineer. The model saw exactly the house that was open, and
never a sample from the corpus. A second selection path is set up here: by
query.

The wave's bet: a model starting from a blank page writes 11 operations per
attempt, while a real floor of a residential tower carries 969. It writes
little not because it is weak, but because it has never seen production.
Showing it production can be done for free: it already sits on disk.

═══════════════════════════════════════════════════════════════════════════
CORPUS MEASUREMENT 17.08.2026 — the owner's prod box: the installation's
decompile catalog, the interpreter from the owner's venv (exact paths are
in the comment below the docstring)
═══════════════════════════════════════════════════════════════════════════

    directories in the corpus                80
    with a readable `passport.md` card       52
    without a card                           28   ← and NOT ONE is silent, see below
      of those, without `L0.jsonl` at all     9

**28 "no card" is not 28 silences but 28 TYPED reasons**, and all of them
are already recorded by the producer in `status.json`. Breakdown by reason:

    extract_failed                  11   L0 extraction was interrupted
    template_compile_failed          5   our emitter failed to compile
    model_edited_during_decompile    5   the document was edited during decompile
    snapshot_non_authoritative       3   partial categories, LIFT is blocked
    internal                         2   internal error
    (stage `geometry`, NO refusal)   2   the parse is ALIVE and simply hasn't reached the passport yet

The last line is the one this is read out for, not invented: `k2_ar_rd_v9`
and `len_ar_me_r24_v1` sit at the `geometry` stage, not fallen. "No card"
and "the parse is dead" are DIFFERENT facts, and merging them would mean
burying two living buildings. The canon has already paid for this exactly
once ("retracted: the log went stale by 24 records — they are ONE").

THE CATALOG'S COST, AND WHY `.md`, NOT `.json`:

    52 × passport.md    61,980 B (62 KB)   961.8 MB for 52 × passport.json
                                            largest passport.json 205.9 MB

    catalog build, median of three runs, warm FS cache:
      cards + `status.json` + course labels           10 ms
      plus resolving orphan labels (2 L0 headers)    145 ms   ← see below
      lookup over the already-built catalog           0.2 ms

Neighbors elsewhere in the tree paid this trap's full price and recorded it
(`clash/existing.py:320-331`): a full parse of the passports cost **17.2 s
PER CALL**, of which 13.2 s was `json.loads` over 918 MB for the sake of ONE
string field. Here it is not repeated: the whole catalog is 62 KB, which is
**15,500 times smaller**. This module NEVER opens `passport.json`.

═══════════════════════════════════════════════════════════════════════════
🔴 THE MAIN REFUTATION: SUBSTRING SEARCH OVER THE CARDS IS NOT ENOUGH
═══════════════════════════════════════════════════════════════════════════

The task names three example queries. A substring search measured against
the text of the 52 cards (17.08.2026):

    «жилая башня»          → 0 cards out of 52   («жил» 0, «башн» 0)
    «многофункциональное»  → 6 cards out of 52
    a building name        → works: «snowdon» 4, «k2» 3, «sob» 23

Two queries out of three give ZERO. The reason is not the corpus but the
card's VOCABULARY: names are asked from an authority, not guessed:

* `name._purpose` (`:1014`) — exactly FOUR values: «не определено»,
  «жилой дом», «офис», «многофункциональное»;
* `name._shape_head` (`:1084`) — exactly SIX: «Прямоугольное здание»,
  «Г-образное», «Т-образное», «П-образное», «Здание: <описание>», «Здание,
  контур не определён»;
* `name._roof_kind` (`:1038`) — THREE: плоская / скатная / не определена.

The words «башня», «квартира», «фасад», «офис», «жилой» occur in the corpus
0 · 0 · 0 · 0 · 0 times. «жилой дом» is a word from the closed vocabulary —
but not a single corpus parse matched it (threshold `residential/considered
> 0.60`). These are TWO DIFFERENT refusals, and they must sound different:

    «башня»     — a card can NEVER say this (not in the vocabulary);
    «жилой дом» — it can, but THIS corpus has none of those (a fact about
                  the corpus).

═══════════════════════════════════════════════════════════════════════════
WHAT CLOSES THE GAP — AND THIS TOO IS ALREADY BUILT
═══════════════════════════════════════════════════════════════════════════

`kir/course/corpus.py:41 BUILDINGS` — a hand-written map of seven parses to
human descriptions, and it carries exactly the words missing from the
cards: «K2, **жилая башня** 59 этажей, АР», «демо-v3, **жилой дом** 64
уровня, АР», «СОБ6.2, **детский сад**, АР». It is QUERIED here, not
rewritten: two tables that must agree is a named defect of this tree.

Hence the search field is a CLOSED, NAMED set of four texts
(`SEARCHED_FIELDS`), not "the whole file": `run` · `doc_name` · `gestalt` ·
`labels`. Nothing smarter than a substring is built, and that is a
MEASUREMENT, not laziness: at 62 KB, after joining the course labels, the
substring answers all three example queries in 0.2 ms (control-PASS —
`kir/tests/test_corpus_catalog.py::LiveCorpus`), while a similarity metric
would add unverifiable ranking on top of TEN buildings. Ten is the entire
denominator: building a trained similarity measure on ten objects means
fitting it to them, with nothing left to check it against.

🔴 A LABEL BELONGS TO THE BUILDING, NOT TO THE CATALOG ENTRY, AND THIS WAS
BOUGHT BY A MEASUREMENT, NOT DERIVED FROM ELEGANCE. The first edition hung
the label on a parse by the catalog directory's name, and the query «жилая
башня» answered `NOT_FOUND` — even though those two words sit in the tree.
The reason: the course names `k2_ar_rd_v9`, which has NO card (stage
`geometry`), so the label never attached to a single catalog row. The L0
header says `k2_ar_rd_v9` is `13A-RD-AR-K2_v33_kuklev.d.s`, that is, THE
SAME building as `k2_ar_rd_v8`, which does have a card. The label is
therefore resolved down to `doc_name` and handed out to EVERY parse of that
building.

The cost of this resolution is named, and it is NOT small: the header is
read by `clash.existing._doc_name_from_l0_head` (borrowed, not written a
second time), and a tower's first L0 line costs **114 ms** on its own.
Measured difference: the catalog without orphan resolution is 10 ms, with
resolution 145 ms — that is, **135 ms for TWO files**, fourteen times
costlier than the rest of the catalog combined. That is why headers are
read ONLY for orphan labels, and the upper bound of the work is the number
of rows in `BUILDINGS` (7), not the corpus size: grow the corpus tenfold,
and this line item does not move. Against the 17.2 s trap of
`passport.json`, the cost is accepted.

🔴 AND A THIRD DISCREPANCY, FOUND BY THAT SAME READING: the course labels
`snowdon_plumb_v5` as «Snowdon, ВК», while its L0 header says `Snowdon
Towers Sample **Architectural**`. The catalog name and the hand-written
label agree with each other and disagree with the document that was
actually read; the header holds the authority here — it is written by
`extract` from the live `Document.Title`. No verdict is issued on WHICH one
is wrong: this is one reading, and one reading is not a conclusion. The row
travels into `Catalog.label_disputes` in full.

═══════════════════════════════════════════════════════════════════════════
THREE OUTCOMES OF SELECTION, AND NOT ONE OF THEM IS SILENT
═══════════════════════════════════════════════════════════════════════════

The same law as `building_index` and `sandbox.ModelCatalog` use:

* **`FOUND_ONE`** — one building matched. The representative parse travels
  along with the RULE by which it was chosen, plus the runners-up
  (`runners_up`);
* **`FOUND_MANY`** — several matched. The choice is NOT made silently: a
  list of buildings with their counts is returned, so the query can be
  narrowed. A silent "first of the matches" is `.FirstOrDefault()` with a
  good reputation, and `ground.py` has already learned that lesson in full;
* **`NOT_FOUND`** — nothing matched, and the refusal NAMES the vocabulary
  one can hit: building names, purposes, course labels. A refusal that
  gives no next move is, to an LLM, the same as silence.

WHAT THIS MODULE DOES NOT DO. It does not read Revit, does not reach the
bridge, does not open `passport.json`, does not build an index (that is
`building_index.index_from_run`), and does not decide whether a building
fits under the 8 MB ceiling — it only REPORTS an estimate from the size of
`L0.jsonl`, because whoever selects a building must know in advance whether
they will get the per-element layer or the census.
"""
# 🔴 PROVENANCE WAS MOVED OUT OF THE DOCSTRING ON 01.09.2026 — A DOOR VS. A
# LOG. A module's docstring is a PUBLIC DOOR: `help()` prints it to a
# reader of the published package, and our machine's address tells them
# nothing. The knowledge is not erased — it is here, in the log, where it
# belongs:
#     corpus        /opt/kukai-rebuild1/backend/backend/data/decompile
#     interpreter   /opt/kukai-rebuild1/backend/venv/bin/python
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

#: The card's name. Written by `decompile/pipeline.py:1464`; parsed here
#: against the PRODUCER'S FORMAT (`_passport_markdown`, `:1368`), not
#: against a sample from disk: a parser built against a sample guards the
#: fixture, not the product.
CARD_NAME = "passport.md"

#: The card's header. This exact line is the first one (`pipeline.py:1372`).
_TITLE_PREFIX = "# KIR Passport — "

#: The values with which the producer says "I didn't know" (`pipeline.py:1429`
#: onward). This is NOT zero and not empty: "nothing to ask" and "empty"
#: are different outcomes, and this entire project stands on that
#: distinction.
UNKNOWN_TOKENS = ("?", "—", "unknown", "None")

#: A CLOSED, NAMED set of texts that is searched. Not "the whole file": the
#: census and slice receipts carry category codes (`OST_SketchLines`,
#: `element_unresolved`), and a query for "lines" would match half the
#: corpus by a service code. The list is CLOSED AND COMPLETE BY
#: CONSTRUCTION: it is itself the definition of `Entry.haystack`, and a
#: test checks one against the other, so the set cannot be widened silently
#: — from only one side.
#:
#: `labels` is plural DELIBERATELY: a label belongs to the BUILDING, and a
#: parse inherits the labels of NEIGHBORING parses of the same document
#: (see the header).
SEARCHED_FIELDS = ("run", "doc_name", "gestalt", "labels")

#: The kinds of selection outcome. A closed list: there is no fourth one.
FOUND_ONE = "found_one"
FOUND_MANY = "found_many"
NOT_FOUND = "not_found"

#: An estimate of "will the index fit under the ceiling". The index/L0
#: ratio was measured in the header of `building_index` as 0.19–0.21 across
#: three buildings; the WORSE end is taken, so as to err toward "warned for
#: nothing" rather than "promised and didn't deliver."
_INDEX_TO_L0_RATIO = 0.21


class CorpusCatalogError(RuntimeError):
    """There is no catalog, or it cannot answer this question — WITH A
    REASON.

    A separate type for the same reason it exists in `building_index`:
    "there is no corpus on this machine" and "the corpus has no such
    building" must be distinguishable by the caller, not read off the
    message text.
    """


def corpus_root(root: Any = None) -> str:
    """The corpus root — ASKED FROM the shared authority, not a third one
    of its own.

    🔴 NO SECOND CORPUS ADDRESS IS SET UP IN THIS TREE. `clash.existing.
    decompile_root()` already reads `KUKAI_DECOMPILE_DATA` and is already
    declared shared by `serving`, `course.corpus`, and `gate_runner`.

    🔴 AND THE MEASUREMENT THAT MUST TRAVEL ALONGSIDE THIS (17.08.2026): in
    production `KUKAI_DECOMPILE_DATA` is NOT SET (`/proc/<pid>/environ` of
    the live service), meaning the default is in effect — and there are two
    defaults, and they are DIFFERENT: `clash.existing.
    DECOMPILE_ROOT_DEFAULT` = the RELATIVE `backend/data/decompile`
    (depends on the process's working directory), while `course.corpus.
    DECOMPILE_ROOT` is computed as ABSOLUTE from `__file__`. They agree
    only because the service is launched from `/opt/kukai-rebuild1/backend`.
    In a development tree the first one points nowhere. The fix is not
    mine (both files belong to someone else) — the discrepancy is NAMED in
    the wave's report.
    """
    if root is not None:
        return str(root)
    from kir.clash.existing import decompile_root

    return str(decompile_root())


@dataclass(frozen=True)
class Card:
    """A parsed card — exactly what the producer put into it.

    Numbers are `int | None`: `None` means "the producer wrote `?`," that
    is, there was nothing to ask. Zero would mean "it was computed and came
    out zero."
    """

    doc_name: str
    revit: str
    change_stamp: str
    gestalt: str
    elements: int | None
    ops_lifted: int | None
    atoms: int | None
    floors: int | None
    rooms: int | None
    apartments: int | None
    failed_verdicts: int | None
    partial_read: bool
    card_bytes: int
    #: The first line — the header of a KIR passport. 🔴 THE FLAG USED TO
    #: BE COMPUTED AND THEN DISCARDED (F-186, 29.08.2026): for a
    #: non-passport, `doc_name` becomes '?', and '?' is a LEGAL name from
    #: the producer (`pipeline.py:1581` `passport.get('doc_name', '?')`).
    #: By name alone these two states are indistinguishable, and an
    #: arbitrary readable file used to pass into the catalog AS A BUILDING.
    #: The default is true — the fix is additive: not a single existing
    #: `Card` constructor breaks.
    well_formed: bool = True


def _clean(value: str) -> str:
    value = value.strip()
    return "" if value in UNKNOWN_TOKENS else value


def _as_int(value: str) -> int | None:
    value = _clean(value)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_card(text: str) -> Card:
    """`passport.md` text -> a `Card`.

    Parsing follows the PRODUCER's format (`pipeline._passport_markdown`):
    top-level fields are `- <key>: <value>` lines, and the `## Stats` and
    `## Verify` sections are the same kind of lines under their own
    headers. Keys inside the sections do not overlap with the top-level
    ones, so a single flat key map is enough and a second pass is not
    needed.
    """
    head, _, _ = text.partition("\n")
    # 🔴 THE FLAG IS NOT SET UP ANEW — IT IS PRESERVED (F-186). It used to
    # be computed right here too, but lived for one expression and was
    # lost. Checking `doc_name != "?"` instead of it is NOT ALLOWED: that
    # is exactly the trap — it would filter out genuine passports of
    # unknown buildings, that is, a second bug instead of the first. And
    # checking required fields is not allowed either: their absence is
    # legal, `parse_card` deliberately turns an unreadable number into
    # `None`. THE KIND of a document and the COMPLETENESS of a document are
    # different questions.
    is_kir_passport = head.startswith(_TITLE_PREFIX)
    doc_name = head[len(_TITLE_PREFIX):].strip() if is_kir_passport else ""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        key, sep, value = stripped[2:].partition(": ")
        if sep:
            fields[key.strip()] = value.strip()
    return Card(
        doc_name=_clean(doc_name) or "?",
        revit=_clean(fields.get("Revit", "")),
        # `change_stamp` is written by the producer in backticks (`:1375`).
        change_stamp=_clean(fields.get("change_stamp", "").strip("`")),
        gestalt=_clean(fields.get("gestalt", "")),
        elements=_as_int(fields.get("elements", "")),
        ops_lifted=_as_int(fields.get("ops lifted", "")),
        atoms=_as_int(fields.get("atoms", "")),
        floors=_as_int(fields.get("floors", "")),
        rooms=_as_int(fields.get("rooms", "")),
        apartments=_as_int(fields.get("apartments", "")),
        failed_verdicts=_as_int(fields.get("failed verdicts", "")),
        # The partial-read marker is not a `- key: value` field but a
        # separate line with ⚠ (`pipeline.py:1382`). It is searched for as
        # a substring for the same reason it is printed that way: it is a
        # warning, not a value.
        partial_read="ЧАСТИЧНОЕ ЧТЕНИЕ" in text,
        card_bytes=len(text.encode("utf-8")),
        well_formed=is_kir_passport,
    )


@dataclass(frozen=True)
class Entry:
    """One corpus parse that HAS a card."""

    run: str
    card: Card
    #: Labels of the BUILDING this parse belongs to — including a label the
    #: course wrote for a NEIGHBORING parse of the same document. The
    #: argument and the cost of the resolution are in the module's header.
    labels: tuple[str, ...]
    stage: str
    l0_bytes: int | None
    #: The same third state as `Missing` has (F-185). The default is
    #: false — the fix is ADDITIVE: not a single existing `Entry`
    #: constructor breaks, no name is renamed.
    l0_unreadable: bool = False

    @property
    def doc_name(self) -> str:
        return self.card.doc_name

    def fits_under(self, ceiling_bytes: int) -> bool | None:
        """Whether the per-element index fits under a NAMED ceiling.

        🔴 THE CEILING IS AN ARGUMENT, NOT A CONSTANT, AND THIS WAS CAUGHT
        BY A CONTROL, NOT FORESEEN. The first edition knew only
        `CEILING_BYTES`, while `index_from_query` already accepted
        `ceiling_bytes` as a parameter: the estimate answered about one
        ceiling while the build went by another, and the early refusal
        stayed silent exactly where it was supposed to fire. The value was
        DECLARED in one place and READ in another — a named defect of this
        tree, committed inside the very fix meant to guard against it. The
        test `test_index_from_query::test_census_is_the_default…` is what
        uncovered it.

        `None` — `L0.jsonl` was not found, there is nothing to ask. This is
        an ESTIMATE from the file size, not a built index: the real answer
        comes from `build_index`, which also hands back the census with a
        reason if it did not fit.
        """
        if self.l0_bytes is None:
            return None
        return self.l0_bytes * _INDEX_TO_L0_RATIO <= ceiling_bytes

    @property
    def index_fits(self) -> bool | None:
        """The same, at the STANDARD ceiling — a convenience, not a second
        source of truth."""
        from kir.building_index import CEILING_BYTES

        return self.fits_under(CEILING_BYTES)

    def haystack(self) -> str:
        """A concatenation of exactly `SEARCHED_FIELDS` — and nothing beyond it."""
        return "\n".join((self.run, self.card.doc_name, self.card.gestalt,
                          "\n".join(self.labels)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run,
            "doc_name": self.card.doc_name,
            "labels": list(self.labels),
            "revit": self.card.revit,
            "gestalt": self.card.gestalt,
            "stage": self.stage,
            "elements": self.card.elements,
            "ops_lifted": self.card.ops_lifted,
            "atoms": self.card.atoms,
            "floors": self.card.floors,
            "rooms": self.card.rooms,
            "apartments": self.card.apartments,
            "partial_read": self.card.partial_read,
            "index_fits": self.index_fits,
            # 🔴 A NEW KEY, NOT A REPLACEMENT FOR THE OLD ONE. `index_fits: null`
            # now means exactly one thing — "L0 does not exist in any form";
            # the "exists and unreadable" case is named separately, or a new
            # silence would have taken root exactly where the old one was
            # cured (F-185).
            "l0_unreadable": self.l0_unreadable,
        }


@dataclass(frozen=True)
class Missing:
    """A parse WITHOUT a card — with its own reason, not silence.

    `stage` is taken from the producer (`status.json`), `reason` is the
    first line of its `errors`. An empty `reason` with `stage != "error"`
    means the parse did NOT fail: it simply has not reached the passport
    yet. Conflating these two outcomes is exactly the defect this whole
    class exists to prevent.
    """

    run: str
    stage: str
    reason: str
    has_l0: bool
    #: Whether `status.json` could be READ. False means "we DON'T KNOW,"
    #: not "there is no stage": without this field, "not asked" and "asked,
    #: empty" were one value, and `alive` used to declare a parse alive
    #: about which nothing at all is known (F-187). The default is false —
    #: the fix is additive.
    status_read: bool = False
    #: The L0 file EXISTS, but its size could not be read. Kept separate
    #: from `has_l0` deliberately (F-185): "there is no data" and "we
    #: couldn't read it" are different facts with different next moves, and
    #: merging them would mean planting a silent value exactly where a
    #: cured one used to be.
    l0_unreadable: bool = False

    @property
    def alive(self) -> bool:
        """The parse never declared a refusal — it hasn't gotten there, it
        hasn't died.

        🔴 DERIVED FROM THE FACT OF READING (F-187). A parse whose
        `status.json` we did not read cannot be declared "alive": the
        absence of an accusation is not proof of life.
        """
        return self.status_read and self.stage != "error"

    def to_dict(self) -> dict[str, Any]:
        return {"run": self.run, "stage": self.stage, "reason": self.reason,
                "has_l0": self.has_l0, "alive": self.alive,
                "status_read": self.status_read,
                "l0_unreadable": self.l0_unreadable}


def _status_of(run_dir: str) -> tuple[str, str] | None:
    """`(stage, reason)` from `status.json`, or `None` — "nothing to ask."

    🔴 `("", "")` USED TO BE RETURNED FOR THREE DIFFERENT STATES (F-187,
    29.08.2026): the file is missing · the file is corrupt · the stage is
    LEGITIMATELY empty. `Missing.alive` is defined as `stage != "error"`
    and used to declare the parse ALIVE in all three, even though the first
    two carry no proof of life at all.

    The docstring promised "a named 'nothing to ask'" — there was no named
    value, only an unnamed collision with a legal value. The requirement
    sat right next to the violation, the same kind as `F-188` in a
    neighboring function of this file.

    The file is tiny (hundreds of bytes) and is read one per directory; an
    expensive `passport.json` has no place here and cannot have one.
    """
    import json

    path = os.path.join(run_dir, "status.json")
    try:
        with open(path, encoding="utf-8") as handle:
            row = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(row, Mapping):
        return None
    stage = str(row.get("stage") or "")
    errors = row.get("errors")
    reason = ""
    if isinstance(errors, (list, tuple)) and errors:
        reason = str(errors[0])
    return stage, reason


def _course_labels() -> tuple[dict[str, str], bool]:
    """Course labels and a flag for the source's AVAILABILITY.

    An import failure is data, not an exception: without labels the
    catalog has a poorer vocabulary but remains fully functional, and "no
    labels" must be distinguishable from "labels are empty."

    🔴 A SINGLE `{}` USED TO BE RETURNED FOR TWO STATES (F-188, 29.08.2026),
    and the requirement to tell them apart sat IN THIS VERY DOCSTRING — and
    was violated by the very next line of code. `Catalog` carried no flag,
    and the label dictionary could vanish silently, producing neither a
    refusal nor a line in the report.

    The flag travels TOGETHER with the dictionary, not alongside it: two
    separate values would have drifted apart exactly the way these two
    states did.
    """
    try:
        from kir.course.corpus import BUILDINGS
    except Exception:  # noqa: BLE001 — a foreign module, its failure is data
        return {}, False
    return {str(k): str(v) for k, v in dict(BUILDINGS).items()}, True


def _doc_name_from_head(run_dir: str) -> str | None:
    """A document's name from the L0 HEADER — via a BORROWED instrument,
    not one of our own.

    🔴 NO SECOND IMPLEMENTATION OF THIS READ IS SET UP IN THE TREE.
    `clash.existing._doc_name_from_l0_head` already has a contract for
    THREE outcomes — a name / an empty string meaning "the parse carries no
    name" / `None` meaning "could not be read" — and it has already been
    checked against all 52 corpus parses (52 matched, 0 diverged). A
    read-it-ourselves of the first line would be a second place required
    to agree, that is, a named defect of this tree. The name is private,
    and this is a conscious price: borrowing someone else's private
    function is cheaper than drifting apart.
    """
    import pathlib

    try:
        from kir.clash.existing import _doc_name_from_l0_head
    except Exception:  # noqa: BLE001 — a foreign module's failure is data
        return None
    try:
        return _doc_name_from_l0_head(pathlib.Path(run_dir) / "L0.jsonl")
    except Exception:  # noqa: BLE001
        return None


@dataclass(frozen=True)
class Catalog:
    """The corpus, seen as a single object."""

    root: str
    entries: tuple[Entry, ...]
    missing: tuple[Missing, ...]
    #: Course labels whose parse has NO card at all. Not discarded: a
    #: hand-written list that has drifted from the generated one is a
    #: finding, not noise.
    labels_without_card: tuple[str, ...]
    #: A label whose building the L0 header names DIFFERENTLY from the
    #: directory name and the label itself: `(parse, label, name_from_header)`.
    #: No verdict is issued.
    label_disputes: tuple[tuple[str, str, str], ...]
    bytes_read: int
    #: Whether the course label source came up. False means "there was
    #: NOTHING TO ASK," not "there are no labels" (F-188): without this
    #: field, the «жилая башня» / «многофункциональное» vocabulary could
    #: vanish silently, producing neither a refusal nor a line in the
    #: report. The default is true — the fix is additive, not a single
    #: existing `Catalog` constructor breaks.
    labels_source_available: bool = True

    def buildings(self) -> dict[str, tuple[Entry, ...]]:
        """Parses grouped by BUILDING, not by directory.

        🔴 THE UNIT IS THE BUILDING, AND THIS IS SOMEONE ELSE'S
        MEASUREMENT, NOT MY TASTE. `course/corpus.py` already recorded it:
        "on disk there are 70 directories, but these are versions: 19
        parses of one facade, 9 of one tower. Counting by directory means
        giving the facade nineteen votes." The same law applies here: 52
        cards fold into 10 buildings (measured 17.08.2026).

        The key is `doc_name`, and it has a NAMED limit: *Save As* splits a
        building's history in two (the canon already carries this case for
        the journal). It is observed in the corpus too: `13A-RD-AR-K2_v33`
        and `13A-RD-AR-K2_v33_kuklev.d.s` — one house under two keys.
        """
        out: dict[str, list[Entry]] = {}
        for entry in self.entries:
            out.setdefault(entry.doc_name, []).append(entry)
        return {k: tuple(v) for k, v in sorted(out.items())}


def load_catalog(root: Any = None) -> Catalog:
    """Read the whole corpus. Only `passport.md`, only `status.json`.

    Measured 17.08.2026: 80 directories, 52 cards, 61,980 B, 31.5 ms with a
    cold read. `passport.json` (961.8 MB for the same 52) is never opened.
    """
    base = corpus_root(root)
    if not os.path.isdir(base):
        raise CorpusCatalogError(
            "корпуса разборов нет по пути %r. Это факт о МАШИНЕ, а не о "
            "зданиях: каталог не пуст, его нечем наполнить. Корень задаётся "
            "`KUKAI_DECOMPILE_DATA`" % base)
    labels, labels_available = _course_labels()
    raw: list[tuple[str, Card, str, int | None]] = []
    missing: list[Missing] = []
    read = 0
    for name in sorted(os.listdir(base)):
        run_dir = os.path.join(base, name)
        if not os.path.isdir(run_dir):
            continue
        # 🔴 A DIRECTORY STARTING WITH AN UNDERSCORE IS NOT A PARSE, AND
        # THIS IS A RULE, NOT A LIST (21.08.2026). Alongside the parses live
        # the corpus's service directories (`_evidence`, `_journals`), and
        # the catalog used to demand a card from them — that is, it declared
        # "the parse said NOTHING about itself" about something that is not
        # a parse at all. The refusal was honest in form and false in
        # substance: it called for issuing a passport to an evidence store.
        #
        # The flag is a PREFIX, not an enumeration of names: the next
        # service directory will land here on its own, while a parse never
        # begins with an underscore (names are assembled from the document
        # name and a version).
        if name.startswith("_"):
            continue
        # 🔴 THE SIZE IS ASKED FROM THE SNAPSHOT LAYER, NOT FROM `getsize`
        # (audit finding F-185, 29.08.2026). The cleanup job compresses
        # `L0.jsonl` -> `L0.jsonl.gz`, and `getsize` on the raw name used to
        # throw an `OSError`: "couldn't read it" fell into the same `None`
        # as "there is no data." Measured on the LIVE corpus (read-only): 37
        # cards out of 56 went to the client with `l0_bytes=None` AND
        # `index_fits=None`, and exactly 37 directories out of 93 on disk
        # have only a compressed L0. Both numbers were obtained by DIFFERENT
        # routes — via `load_catalog` and by a direct walk — and matched
        # exactly.
        #
        # A second implementation of one question was superfluous here from
        # the very start: `snapshot_io.snapshot_raw_size` was written FOR
        # EXACTLY THIS TRAP and cites it in its own docstring. Adding a
        # `.gz` check alongside it would set up a THIRD implementation of
        # "how many bytes are in the snapshot"; two have already drifted
        # apart, a third would drift faster.
        #
        # The size taken is the UNCOMPRESSED one: `index_fits` compares the
        # volume of DATA against the transport ceiling, not disk space. A
        # compressed size would silently change the field's MEANING.
        #
        # The import is lazy — the same technique `_status_of` uses to pull
        # in `json`: the `kir.decompile` chain is heavy, and the catalog is
        # called in places that don't need a parse at all.
        from kir.decompile.snapshot_io import (snapshot_file_exists,
                                               snapshot_raw_size)
        l0 = os.path.join(run_dir, "L0.jsonl")
        l0_unreadable = False
        if not snapshot_file_exists(l0):
            l0_bytes: int | None = None
        else:
            try:
                l0_bytes = snapshot_raw_size(l0)
            except OSError:
                # 🔴 A THIRD STATE: THE FILE EXISTS AND IS UNREADABLE.
                # Without it, the fix would be incomplete: `None` would
                # again mean two things at once, and we would have swapped
                # one ailment for another of the same kind. A negative size
                # here would be a trick every reader of the field would have
                # to be told about; the state travels as a SEPARATE field,
                # not as a substitute number.
                l0_bytes, l0_unreadable = None, True
        status = _status_of(run_dir)
        stage, reason = status if status is not None else ("", "")
        try:
            with open(os.path.join(run_dir, CARD_NAME), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            missing.append(Missing(run=name, stage=stage, reason=reason,
                                   has_l0=l0_bytes is not None,
                                   status_read=status is not None,
                                   l0_unreadable=l0_unreadable))
            continue
        read += len(text.encode("utf-8"))
        card = parse_card(text)
        if not card.well_formed:
            # 🔴 THE DOCUMENT'S KIND IS DISAMBIGUATED HERE (F-186). A
            # readable file whose first line is not a passport header is
            # NOT a building, and until today it used to fall in as a
            # regular `Entry`: a search by name would find it, and
            # `doc_name` was '?' — a legal value from the producer. It
            # goes into `missing`, not into a refusal: the catalog must
            # stay operational with junk in the root, and `missing` is
            # already the existing channel for "there is a run, there is
            # no building," and it has a `reason`.
            missing.append(Missing(
                run=name, stage=stage,
                reason=(reason or
                        f"паспорт нечитаем: первая строка не «{_TITLE_PREFIX}»"),
                has_l0=l0_bytes is not None,
                status_read=status is not None,
                l0_unreadable=l0_unreadable))
            continue
        raw.append((name, card, stage, l0_bytes, l0_unreadable))

    # LABEL -> BUILDING. A parse with a card hands over its `doc_name` for
    # free; a parse WITHOUT a card (an orphan label) costs an L0 header
    # read, and so only it is read. The upper bound of the work is the
    # number of rows in `BUILDINGS`.
    by_run = {name: card.doc_name for name, card, _s, _b, _u in raw}
    doc_labels: dict[str, list[str]] = {}
    orphan: list[str] = []
    disputes: list[tuple[str, str, str]] = []
    for run, label in sorted(labels.items()):
        doc = by_run.get(run)
        if doc is None:
            orphan.append(run)
            head = _doc_name_from_head(os.path.join(base, run))
            # `None` — "could not be read," and this is NOT the same as
            # "there is no name": merging them silently would mean losing
            # an existing building.
            if not head:
                continue
            doc = head
            if doc not in by_run.values():
                disputes.append((run, label, head))
        doc_labels.setdefault(doc, []).append(label)

    entries = tuple(
        Entry(run=name, card=card,
              labels=tuple(doc_labels.get(card.doc_name, ())),
              stage=stage, l0_bytes=l0_bytes, l0_unreadable=unreadable)
        for name, card, stage, l0_bytes, unreadable in raw)
    return Catalog(root=base, entries=entries, missing=tuple(missing),
                   labels_without_card=tuple(orphan),
                   label_disputes=tuple(disputes), bytes_read=read,
                   labels_source_available=labels_available)


# ── SELECTION ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Building:
    """A corpus building and the NAMED choice of a representative parse
    within it."""

    doc_name: str
    chosen: Entry
    rule: str
    runners_up: tuple[Entry, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {"doc_name": self.doc_name, "chosen": self.chosen.to_dict(),
                "rule": self.rule,
                "runners_up": [e.run for e in self.runners_up]}


#: The ordering rule for the parses of ONE building. ASSIGNED, not derived,
#: and this is recorded here, not in a commit.
RUN_CHOICE_RULE = ("самый полный ЗАВЕРШЁННЫЙ разбор здания: стадия `done` "
                   "вперёд числа элементов")


def _rank(entry: Entry) -> tuple[int, int, str]:
    """The ordering of ONE building's parses. The rule is named, not
    implied.

    🔴 THE MEASUREMENT DOES NOT CHOOSE BETWEEN THREE RULES, AND THAT IS THE
    MAIN THING TO KNOW ABOUT IT (17.08.2026). The only external cross-check
    that exists is the hand-written list `course.corpus.BUILDINGS`; it
    overlaps with the catalog on FIVE buildings, and three different rules
    give the SAME count on them:

        "more elements"                 4 of 5   (facade -> v17)
        "done, then more elements"      4 of 5   (facade -> v16)   ← chosen
        "newest by directory name"      4 of 5   (facade -> v9)

    All three disagree on the very same building — a facade with 18 carded
    versions, while the course names `v19`. Three mechanisms give the same
    discrepancy, so the NUMBER IS EXHAUSTED: this measurement cannot choose
    between the rules, and declaring a winner would be taste served up as a
    conclusion. The cost difference is small in any case — v16 against v19
    is 5287 against 5218 elements, 1.3%.

    A consequence follows from this, not an excuse: the rule is ASSIGNED
    and must be DISCLOSED. It travels in `Building.rule` together with the
    full list of runners-up (`runners_up`), and the caller is free to take
    a different parse — exactly the law `ground.py` used to replace
    `.FirstOrDefault()`.

    🔴 FRESHNESS IS DELIBERATELY NOT PART OF THE RULE. The only freshness
    signal available here is a directory's `mtime`, and in THIS corpus it
    is poisoned by our own reading of it: the canon carries a measurement
    where 67 parses out of 76 were dated to the same day, because our own
    traversal had walked over them the day before. Dating a building by a
    timestamp that the act of observation itself writes is a separate law
    of the canon, and breaking it for the sake of a pretty tie-break buys
    nothing good.
    """
    return (1 if entry.stage == "done" else 0, entry.card.elements or 0,
            entry.run)


def _building_of(doc_name: str, runs: Iterable[Entry]) -> Building:
    ordered = sorted(runs, key=_rank, reverse=True)
    return Building(doc_name=doc_name, chosen=ordered[0],
                    rule=RUN_CHOICE_RULE, runners_up=tuple(ordered[1:]))


@dataclass(frozen=True)
class Selection:
    """The selection outcome — one of three, and none of them is silent."""

    outcome: str
    query: str
    matched: tuple[Building, ...]
    refused: str = ""
    #: The corpus root THAT THIS SEARCH USED. Travels with the outcome
    #: rather than being recomputed by the caller: a second computation of
    #: the same root is a second place required to agree, and it will drift
    #: apart the very first time `KUKAI_DECOMPILE_DATA` changes mid-turn.
    root: str = ""

    @property
    def building(self) -> Building | None:
        """A building — ONLY when there is one. Otherwise `None`, and that
        is not empty.

        A silent "first of the matches" is forbidden here: `ground.py` has
        already learned this lesson in full ("a choice the caller cannot
        see is `.FirstOrDefault()` with a good reputation").
        """
        return self.matched[0] if self.outcome == FOUND_ONE else None

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "query": self.query,
                "matched": [b.to_dict() for b in self.matched],
                "refused": self.refused, "root": self.root}


def _vocabulary(catalog: Catalog) -> str:
    """The vocabulary one CAN hit — for the `NOT_FOUND` refusal.

    A refusal that gives no next move is, to an LLM, the same as silence:
    it cannot see a screen and cannot "just look at the list itself."
    """
    names = sorted({e.doc_name for e in catalog.entries})
    purposes = sorted({m for e in catalog.entries
                       for m in re.findall(r"Назначение: ([^.]+)\.",
                                           e.card.gestalt)})
    labels = sorted({lab for e in catalog.entries for lab in e.labels})
    parts = ["здания корпуса: " + ", ".join("«%s»" % n for n in names)]
    if purposes:
        parts.append("назначения (закрытый словарь `name._purpose`): "
                     + ", ".join(purposes))
    if labels:
        parts.append("ярлыки курса: " + "; ".join(labels))
    return " · ".join(parts)


def search(query: str, catalog: Catalog | None = None, *,
           root: Any = None) -> Selection:
    """A query -> a corpus building. Three outcomes, and none of them is
    an empty list.

    A match is a case-insensitive SUBSTRING over `SEARCHED_FIELDS`, and the
    rule is taken from `building_index.matches`, not invented: a search
    stricter than the already-working grounding-by-name would send the
    author off to fix something that would build just fine.
    """
    catalog = catalog if catalog is not None else load_catalog(root)
    needle = (query or "").strip()
    if not needle:
        return Selection(
            outcome=NOT_FOUND, query=query or "", matched=(), root=catalog.root,
            refused=("запрос пуст — выбирать не по чему. Это факт о ЗАПРОСЕ, "
                     "а не о корпусе; в нём %d разборов %d зданий. %s"
                     % (len(catalog.entries),
                        len(catalog.buildings()), _vocabulary(catalog))))
    folded = needle.casefold()
    hit = [e for e in catalog.entries if folded in e.haystack().casefold()]
    if not hit:
        return Selection(
            outcome=NOT_FOUND, query=needle, matched=(), root=catalog.root,
            refused=("по запросу «%s» в корпусе не нашлось ничего. Искалось "
                     "подстрокой по %s. Это факт о КОРПУСЕ и о словаре "
                     "карточки — она порождается детерминированно и слов вне "
                     "закрытого словаря не несёт. Попасть можно так: %s"
                     % (needle, ", ".join("`%s`" % f for f in SEARCHED_FIELDS),
                        _vocabulary(catalog))))
    # 🔴 A MATCH IDENTIFIES THE BUILDING; SELECTING THE PARSE IS A SEPARATE
    # RULE. The first edition built a `Building` from the MATCHED parses,
    # and the query «фасад» (a course label written for one directory only)
    # handed back a building with `runners_up: []` — even though the corpus
    # holds 19 parses of that facade. The field meant both "the building
    # has no other parses" and "the others did not match" at once — one
    # code for two outcomes, our named defect form 11. The candidates are
    # taken from the catalog in full.
    all_runs = catalog.buildings()
    buildings = tuple(_building_of(name, all_runs.get(name, ()))
                      for name in sorted({e.doc_name for e in hit}))
    if len(buildings) == 1:
        return Selection(outcome=FOUND_ONE, query=needle, matched=buildings,
                         root=catalog.root)
    return Selection(
        outcome=FOUND_MANY, query=needle, matched=buildings, root=catalog.root,
        refused=("по запросу «%s» подошло %d зданий, и выбор за автором — "
                 "молча взять первое значило бы отдать решение порядку "
                 "каталога. Подошли: %s. Сузить можно именем здания или "
                 "числом (этажи, элементы) из строк ниже."
                 % (needle, len(buildings),
                    "; ".join("«%s» (%s, элементов %s, этажей %s)"
                              % (b.doc_name, b.chosen.run,
                                 b.chosen.card.elements,
                                 b.chosen.card.floors)
                              for b in buildings))))


__all__ = [
    "CARD_NAME", "UNKNOWN_TOKENS", "SEARCHED_FIELDS", "RUN_CHOICE_RULE",
    "FOUND_ONE", "FOUND_MANY", "NOT_FOUND",
    "CorpusCatalogError", "Card", "Entry", "Missing", "Catalog", "Building",
    "Selection", "corpus_root", "parse_card", "load_catalog", "search",
]
