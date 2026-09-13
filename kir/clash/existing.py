"""ALREADY STANDING IN THE DOCUMENT — a second source of bodies for the batch.

WHAT THIS FIXES. `clash_bundle` compares the session's batch AGAINST ITSELF.
Its own receipt says this in plain text: «НЕ ВИДИТ ВООБЩЕ: только
объявленное сессией. Стоящее в документе в поиск не входит никогда (ground даёт
уровни и ТИПЫ, ни одного экземпляра) — столкновение с чужой стеной не „не
найдено“, а НЕВИДИМО.» A zero findings answered "my new elements do not clash
with each other", and was read as "the building is fine".

WHERE THE EXISTING BODIES COME FROM. From the L0 parse that lies on disk: an
element carries `bbox_min_mm`/`bbox_max_mm` — the REAL Revit bounding box,
taken by reading, not declared by the program. `hulls.build_hull` already
knows this path and marks it with the `coarse` grade; its own comment about
`_z_span` says directly: "the L0 parse doesn't have it — there Z comes from
the real bounding box." We do not set up a second hull builder: the same
`build_hull`, the same snapshot, the same detector.

THE SOURCE ADDRESS IS AN ALREADY-EXISTING CONVENTION, NOT A NEW ONE. The
consolidated-model wave (14.08) introduced `<model>::<source id>` and
`detect.cross_model_pair_filter` on top of it. The existing building is just
one more source in the same address space, so there is not a single new
address form here.

════════════════════════════════════════════════════════════════════════════
THREE DECISIONS, AND EACH ONE IS PROVEN, NOT CHOSEN
════════════════════════════════════════════════════════════════════════════

**1. SCOPE = BOUNDING BOX OF THE UNION OF NEW BODIES, MARGIN 0 mm.**

This is neither taste nor a threshold. We look for exactly two relations —
`overlap` (signed_distance < 0) and `contact` (== 0); both REQUIRE the
bounding boxes of the two hulls to intersect: a hull is contained in its
bounding box, so for a pair with non-intersecting bounding boxes the
distance is strictly positive. So an element whose bounding box does not
intersect the bounding box of the union of new bodies cannot be in either
`overlap` or `contact` with them — and it can be dropped WITHOUT LOSING ANY
FINDINGS.

A margin of 0 mm means: we are not looking "nearby". The third relation,
`separated`, is NOT published at all against the existing building —
otherwise the entire building would end up in the findings, and the number
of findings would stop meaning anything. This is stated in the receipt.

**2. "DOES NOT CLASH" DIFFERS FROM "WAS NOT EXAMINED" BY A FIELD, NOT BY TONE.**

An empty report must carry AGAINST WHAT the comparison was made: the source,
the number of existing bodies, the scope, the number of pairs compared.
Without the source, zero findings remains the same undifferentiated green,
only wider — and that is exactly the defect this wave closes. So
`Existing.absent()` is not an empty set but a NAMED absence with a reason,
and the receipt prints it in different words.

**3. CONTACT AND PENETRATION ARE NOT MIXED.** They are already kept apart
(`detect.HULL_RELATIONS`), and the measurement justifies this: contact
accounts for up to a third of all pairs (7 804 against 19 523 overlaps on
one building). Adding them together means systematically overestimating the
number of conflicts, so here they are counted separately and printed
separately.

WHAT THIS MODULE DOES NOT DO. It does not go to the bridge and does not read
the live document: the source is a parse already lying on disk, i.e. the
state at the moment of reading. A discrepancy between the parse and the live
document is a fact about the source's freshness, and it is named as the
parse's fingerprint in the provenance, not hidden.
"""

from __future__ import annotations

import collections
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping, Sequence

# Reading the compressed corpus — with ONE prod function for the whole tree;
# the justification is at the call site below.
from kir.model.snapshot_io import open_snapshot
from kir import env  # noqa: E402

#: Separator of the source address. The same convention as the consolidated
#: model (`detect.cross_model_pair_filter`), and deliberately the same: two
#: address spaces for one question would be our own named defect.
SOURCE_SEPARATOR = "::"

#: The source prefix "already standing in the document". Short and NOT
#: empty: an element without a prefix is considered to belong to the batch,
#: and an empty string would make these two cases indistinguishable.
EXISTING_SOURCE = "документ"

#: Scope margin, mm. ZERO, and this is proven in the module's header:
#: `overlap` and `contact` require the bounding boxes to intersect, so
#: widening the scope would add not a single finding, only work.
REGION_MARGIN_MM = 0.0


def existing_source_id(element_id: Any) -> str:
    """Address of an existing element in the shared source space."""
    return f"{EXISTING_SOURCE}{SOURCE_SEPARATOR}{element_id}"


def is_existing(source_id: str) -> bool:
    """Whether the address belongs to the existing building.

    The PREFIX decides, not the presence of a separator: another model's
    address (`ФАС_R23::7240696`) is also not the batch, but it is not our
    existing building either, and the two must not be conflated.
    """
    return source_id.split(SOURCE_SEPARATOR, 1)[0] == EXISTING_SOURCE


@dataclass(frozen=True)
class Region:
    """The comparison scope — the bounding box within which a finding is AT
    ALL possible.

    An empty scope (`lo is None`) is a legitimate case: the batch built no
    bodies at all. Then there is nothing to compare not because there is no
    building, but because OUR side of the pair is missing, and these are
    different facts.
    """

    lo: tuple[float, float, float] | None
    hi: tuple[float, float, float] | None
    margin_mm: float = REGION_MARGIN_MM

    @property
    def empty(self) -> bool:
        return self.lo is None or self.hi is None

    @classmethod
    def around(cls, records: Iterable[Any],
               *, margin_mm: float = REGION_MARGIN_MM) -> "Region":
        """Bounding box of the union of hulls. Loses no findings — see the header."""
        lo: list[float] | None = None
        hi: list[float] | None = None
        for rec in records:
            try:
                blo, bhi = rec.bounds()
            except Exception:  # noqa: BLE001 — a record without bounds simply doesn't extend the scope
                continue
            if lo is None:
                lo, hi = list(blo), list(bhi)
                continue
            for axis in range(3):
                if blo[axis] < lo[axis]:
                    lo[axis] = blo[axis]
                if bhi[axis] > hi[axis]:  # type: ignore[index]
                    hi[axis] = bhi[axis]  # type: ignore[index]
        if lo is None or hi is None:
            return cls(None, None, margin_mm)
        m = float(margin_mm)
        return cls(
            (lo[0] - m, lo[1] - m, lo[2] - m),
            (hi[0] + m, hi[1] + m, hi[2] + m),
            m,
        )

    def admits(self, bbox_lo: Sequence[float], bbox_hi: Sequence[float]) -> bool:
        """Whether an element with this bounding box can touch the scope at all."""
        if self.empty:
            return False
        for axis in range(3):
            if bbox_hi[axis] < self.lo[axis]:  # type: ignore[index]
                return False
            if bbox_lo[axis] > self.hi[axis]:  # type: ignore[index]
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        if self.empty:
            return {"empty": True, "margin_mm": self.margin_mm,
                    "why": "пачка не построила ни одного тела"}
        return {"empty": False, "margin_mm": self.margin_mm,
                "lo_mm": [round(v, 3) for v in self.lo],   # type: ignore[union-attr]
                "hi_mm": [round(v, 3) for v in self.hi]}   # type: ignore[union-attr]


@dataclass(frozen=True)
class Existing:
    """Bodies of the existing building — OR a named reason why there are none.

    Two states, and they are DIFFERENT facts. `present=False` means "there
    is no source, there was nothing to compare with"; `present=True` with
    `elements == ()` means "the source exists, the scope is empty" — i.e. a
    real answer about the building. Merging them into an empty list would
    bring back the same undifferentiated green the wave was made to remove.
    """

    present: bool
    elements: tuple[dict, ...] = ()
    source: str = ""
    doc_name: str = ""
    region: Region = Region(None, None)
    scanned: int = 0
    admitted: int = 0
    without_bbox: int = 0
    reason: str = ""
    freshness: "Freshness | None" = None

    @classmethod
    def absent(cls, reason: str) -> "Existing":
        """There is no source. A reason is MANDATORY — a silent absence is
        indistinguishable from an honest zero, and this is exactly what we
        are fixing."""
        if not reason:
            raise ValueError("отсутствие стоящего обязано называть причину")
        return cls(present=False, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        if not self.present:
            return {"present": False, "reason": self.reason}
        return {
            "present": True,
            "source": self.source,
            "doc_name": self.doc_name,
            "region": self.region.to_dict(),
            "scanned": self.scanned,
            "admitted": self.admitted,
            "bodies": len(self.elements),
            "without_bbox": self.without_bbox,
            # FRESHNESS ALWAYS TRAVELS, not only when it is bad: a field
            # that appears only in trouble reads as "if it's absent,
            # everything is fine", and here THERE IS NO SUCH THING AS FINE
            # (see `Freshness`).
            "freshness": (None if self.freshness is None
                          else self.freshness.to_dict()),
        }


@dataclass(frozen=True)
class Freshness:
    """HOW MUCH the source corresponds to the SAME document — and whether
    this is proven.

    🔴 TODAY IT IS NOT PROVEN AT ALL, AND THIS IS A MEASUREMENT, NOT CAUTION.
    The identity of a live document is `contracts.DocumentFingerprint`: the
    triple `(title, path_name, project_uid)`. The parse carries NOT A SINGLE
    field from it except the name: `passport.json` holds `doc_name`,
    `change_stamp`, `revit_version`; the `L0.jsonl` header holds the same
    ones plus `units`. `project_uid` and `path_name` are absent from the
    parse artifacts entirely.

    There is exactly one shared key — the NAME, and it is compared with the
    NAME honestly: the parse's `doc_name` is literally `Document.Title`
    (`decompile/extract.py:1014`), the very same field that lies in
    `DocumentFingerprint.title`. So a name match is a comparison of like
    with like, not a guess; but two documents with the same title are
    indistinguishable, and "the same file" does NOT follow from this.

    So a finding taken from such a source is marked `proven=False`, and the
    receipt prints this. Comparing with the past silently is not allowed —
    this is the same class as "a stale catalog gives `KIR-G101`, not a
    silent build".

    🔴 CLOSED 15.08.2026 — PARTIALLY, AND THE BOUNDARY HERE MATTERS MORE THAN
    THE FACT. The passport now carries `document_identity`
    (`decompile/passport.py`), and the live fingerprint takes the same Revit
    field (`open_model.py:1908`). But `ProjectInformation.UniqueId` is
    LINEAGE, not authority: Save As carries the same value. Hence the
    asymmetry everything here rests on:

        matched    -> stronger than the name, but "the same file" does NOT follow
        diverged   -> a DIFFERENT document, proven; such a parse is discarded
        missing from the passport -> the parse was taken before this wave (4 of 71 carry an identity)

    `proven=True` occurs only on an authoritative source (a cloud or server
    GUID), and the list of these sources is looked up from
    `decompile/identity.py`, not rewritten here.
    """

    proven: bool
    matched_by: str
    age_days: float | None = None
    why: str = ""
    #: "2023 -> 2026", when BOTH sides named a version and they diverged.
    #: Empty = they matched OR one side is silent. This is NOT a refutation
    #: (a 2023 document opened in 2026 legitimately upgrades), but it is not
    #: trivial either: for a document with a common name this is the most
    #: noticeable sign that the parse was taken from a DIFFERENT file. Set up
    #: by measurement 20.08.2026 — see `resolve_run`.
    version_drift: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"proven": self.proven, "matched_by": self.matched_by,
                "age_days": (None if self.age_days is None
                             else round(self.age_days, 1)),
                "why": self.why,
                "version_drift": self.version_drift}


#: Root of the parse corpus. THE SAME variable read by `serving`,
#: `course.corpus`, and `gate_runner` — a second address for the same corpus
#: would mean two places obliged to match.
DECOMPILE_ROOT_ENV = "KIR_DECOMPILE_DATA"
DECOMPILE_ROOT_DEFAULT = "backend/data/decompile"


def decompile_root() -> pathlib.Path:
    import os

    return pathlib.Path(
        env.get(DECOMPILE_ROOT_ENV, DECOMPILE_ROOT_DEFAULT))


#: An identity source that Autodesk contracts as the AUTHORITY of the
#: logical model. `project_information_unique_id` is deliberately NOT
#: included here: it is `Element.UniqueId`, unique only WITHIN a document,
#: and Save As carries the same value. The list is maintained in
#: `decompile/identity.py`; here it is looked up, not rewritten — two tables
#: obliged to match is exactly the named defect of this tree.
def _authoritative_sources() -> frozenset:
    from kir.model.identity import (
        AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES)
    return AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES


def resolve_run(doc_title: str, *, root: Any = None, project_uid: str = "",
                revit_version: str = ""
                ) -> tuple[pathlib.Path | None, str, Freshness | None]:
    """Title of the live document -> its most recent parse.

    Returns `(path, refusal_reason, freshness)`. The path and the reason are
    mutually exclusive: a refusal MUST name itself in words, otherwise the
    absence of a source is indistinguishable from "compared, and it's
    clean" — the defect the whole wave exists to fix.

    Freshness is computed from the time of the catalog's most recent write,
    not from `change_stamp`: the stamp is the name of a run, it is not
    ordered in time.
    """
    import os
    import time

    if not doc_title:
        return None, ("личность документа неизвестна: ground не дал "
                      "`__document_fingerprint`, и с ЧЕМ сравнивать — "
                      "не выведено"), None
    base = pathlib.Path(str(root)) if root is not None else decompile_root()
    if not base.exists():
        return None, f"корпуса разборов нет: {base}", None

    best: tuple[int, int, float, pathlib.Path,
                Mapping[str, Any]] | None = None
    seen = 0
    refuted = 0
    #: 🔴 THE JUDGE MAY STAY SILENT, BUT MUST COUNT ITS OWN SILENCE
    #: (29.08.2026, debt `MUTE_SOURCES` in
    #: `test_a_missing_source_names_its_cause`). Catalogs skipped by the
    #: three branches below fell into NO count at all: they were not in
    #: `seen`, not in `refuted`, and the reader got "0 examined — there is
    #: NOTHING to compare against the existing building". This is a fact
    #: ABOUT THE INSTRUMENT ("there was nothing to look with"), read as a
    #: fact ABOUT THE BUILDING ("there is no parse") — exactly the class of
    #: defect the ratchet was set up for. The answer DOES NOT CHANGE: a skip
    #: remains a skip, but the SILENCE now gets a REASON that can be asked
    #: for — in the shape of `install_paths` and `viewer/scene`, not its own.
    #:
    #: The reasons are DIFFERENT and therefore counted separately: "not a
    #: catalog" is trash at the corpus root; "no passport" and "no L0" are an
    #: unfinished or uncleaned-up parse, and their next step differs. Before,
    #: the last two stood as ONE condition joined by `or`, meaning there was
    #: no way even to tell them apart.
    skipped: collections.Counter = collections.Counter()
    for run in sorted(base.iterdir()):
        if not run.is_dir():
            skipped["не каталог"] += 1
            continue
        passport = run / "passport.json"
        # A compressed L0 is not a missing one: otherwise `resolve_run`
        # stops finding the parse, and the model silently loses the
        # building's index.
        from kir.model.snapshot_io import (
            read_snapshot_text, snapshot_file_exists)
        # 🔴 THE PASSPORT IS COMPRESSED TOO (21.08.2026): `passport.json`
        # entered `snapshot_janitor.SNAPSHOT_FILES` (1001 MB across 28
        # parses). A bare `.exists()` on a cooled-down parse would answer
        # "no passport", and `resolve_run` would silently lose the building
        # — exactly the same failure that L0 is already protected from a
        # line below.
        if not snapshot_file_exists(passport):
            skipped["паспорта нет"] += 1
            continue
        if not snapshot_file_exists(run / "L0.jsonl"):
            skipped["L0 нет"] += 1
            continue
        seen += 1
        # 🔴 EXPENSIVE READING — ONLY FOR CANDIDATES SELECTED CHEAPLY.
        # Measured 16.08.2026 on a live corpus (52 parses): a full parse of
        # passports cost 17.2 s PER CALL, of which 13.2 s was `json.loads`
        # over 918 MB, just to read ONE string field. The cost grew with the
        # BUILDING's size (the largest passport 206 MB, of which `tree` is
        # 276 MB in JSON), even though the answer is of fixed size. For a
        # clash this was a second on a turn; for a live KIR turn it was a
        # verdict on capability.
        #
        # The L0 header (the first line of the JSONL) carries the same
        # `doc_name`: checked against ALL 52 parses of the corpus — 52
        # matched, 0 diverged. Passing over the headers costs 0.7 s against
        # 17.2 s.
        #
        # The cheap filter can err ONLY toward extra work: if the name did
        # not read, the parse goes to the passport as before. It cannot skip
        # a real candidate, because "I don't know" and "not it" are
        # different outcomes, and the former does not disqualify.
        cheap = _doc_name_from_l0_head(run / "L0.jsonl")
        # 🔴 THE THIRD OUTCOME WAS DECLARED AND WAS NOT BEING READ (E-34,
        # 29.08.2026). The header function `_doc_name_from_l0_head` names
        # THREE answers: a name · an EMPTY string ("the parse carries no
        # name") · `None` ("could not be read"). The condition treated them
        # as TWO: `cheap is not None` let the empty string pass through, and
        # it was compared against the title as a NAME — i.e. it answered
        # "not it". But that is NOT the answer "not it", it is "nothing to
        # say".
        #
        # The cost is not theoretical: this broke the very law stated in the
        # paragraph above about the cheap filter itself — "it cannot skip a
        # real candidate, because 'I don't know' and 'not it' are different
        # outcomes, and the former does not disqualify". A parse with an
        # empty `doc_name` in its header and the CORRECT name in its
        # passport was thrown out by the cheap filter, and `resolve_run`
        # answered "there is no document parse in the corpus" while a live
        # parse sat on disk. Now both forms of "nothing to say" — both
        # `None` and the empty string — go to the passport.
        if cheap and cheap != doc_title:
            continue
        try:
            # 🔴 `touch=False`, AND WITHOUT IT THE INSTRUMENT WAS DESTROYING
            # THE VERY THING IT MEASURES (found 21.08.2026 by the control
            # `test_берётся_САМЫЙ_СВЕЖИЙ_...`). `open_snapshot`, when
            # reading, plants a `.last_access` marker inside the catalog —
            # and creating a file updates the mtime of the CATALOG ITSELF.
            # The resolver reads the passport of EVERY candidate, meaning it
            # dates all of them with today's date in a single pass; the
            # freshness that decides on the third key becomes the same for
            # all of them, and the strict `>` hands the win to WHOEVER COMES
            # FIRST ALPHABETICALLY.
            #
            # Measurement: the parse was given an mtime thirty days old,
            # after `resolve_run` both folders carried the SAME "now" stamp.
            # The corpus has 88 parses, among them a group of 18 sharing one
            # name — there this decided which building the clash would be
            # compared against.
            #
            # The knowledge already EXISTED in the tree:
            # `decompile/graph_clash_query.py:826` carries exactly this
            # `touch=False` with the argument "an instrument does not date
            # what it measures". The fix stood in one of the two copies —
            # this house's own named form.
            row = json.loads(read_snapshot_text(passport, encoding="utf-8",
                                                touch=False))
        except (OSError, ValueError):
            continue
        if row.get("doc_name") != doc_title:
            continue
        # 🔴 A REFUTATION IS STRONGER THAN A CONFIRMATION, AND THIS IS NOT
        # CAUTION. A match on `project_uid` does NOT prove "the same file"
        # (Save As carries the same value), but a MISMATCH proves "a
        # different file" — both sides read one Revit field: the parse
        # through `L0Document.identity` (`extract.py:1074`), the live
        # fingerprint through `open_model.py:1908`. So a diverged parse is
        # discarded HERE, not flagged below: it is known for certain to be
        # about a different document, and "the freshest" among foreign
        # documents is the worst possible answer.
        row_uid = _passport_uid(row)
        if project_uid and row_uid and row_uid != project_uid:
            refuted += 1
            continue
        try:
            stamp = os.path.getmtime(run)
        except OSError:
            stamp = 0.0
        # 🔴 EVIDENCE COMES BEFORE FRESHNESS, AND THIS WAS CAUGHT BY A
        # CONTROL, NOT INVENTED. The first revision simply took the freshest,
        # and a parse WITHOUT identity beat a parse with a MATCHING lineage
        # by the accident of write time: the strongest evidence lost to a
        # filesystem stamp. The order is now explicit — authority, then
        # lineage, then "no identity", and freshness decides only within one
        # rank.
        rank = _evidence_rank(row, project_uid)
        # 🔴 THE REVIT VERSION SITS BETWEEN LINEAGE AND THE FILE CLOCK, and
        # this is a fix measured 20.08.2026. Before it, within one evidence
        # rank, a SINGLE mtime decided — meaning among 18 parses sharing one
        # name (and the corpus does have such a group) the plain winner was
        # whichever was written last. The version exists on BOTH sides and
        # was never checked against each other.
        #
        # Three positions, not two: a match (2) is stronger than "one side
        # is silent" (1), and a known MISMATCH (0) is weaker than not
        # knowing — not knowing testifies neither for nor against, a
        # mismatch testifies AGAINST. There is no disqualification at any
        # position: a document upgrade is legitimate, and losing the only
        # candidate over it would be worse than comparing with a caveat.
        theirs = str(row.get("revit_version") or "").strip()
        if not theirs or not revit_version:
            version_rank = 1
        else:
            version_rank = 2 if theirs == revit_version.strip() else 0
        if best is None or (rank, version_rank, stamp) > (best[0], best[1],
                                                          best[2]):
            best = (rank, version_rank, stamp, run, row)

    if best is None:
        tail = (f"; {refuted} отброшено по РАСХОЖДЕНИЮ личности — это другие "
                f"документы с тем же заголовком" if refuted else "")
        # The silence is named by a NUMBER AND A REASON, next to "examined":
        # without it "0 examined" reads as "the corpus is empty", even
        # though the catalogs existed — there was simply nothing to read
        # them into.
        mute = (f"; ПРОПУЩЕНО {sum(skipped.values())} каталогов, ни один не "
                f"вошёл в счёт: {dict(sorted(skipped.items()))}"
                if skipped else "")
        return None, (f"разбора документа «{doc_title}» в корпусе нет "
                      f"(просмотрено {seen}){tail}{mute} — сравнивать со "
                      f"стоящим НЕ С ЧЕМ"), None
    age_days = max(0.0, (time.time() - best[2]) / 86400.0)
    return best[3], "", _freshness_of(best[4], project_uid, age_days,
                                      revit_version)


def _doc_name_from_l0_head(l0: pathlib.Path) -> str | None:
    """The document name from the L0 HEADER — or `None`, meaning "I don't
    know".

    🔴 THREE OUTCOMES, NOT TWO, AND THE THIRD ONE IS THE MAIN ONE HERE. A
    string is a name. An empty string means the parse carries no name (also
    knowledge: it is a candidate for no one). `None` means reading failed,
    and then deciding by the header is NOT ALLOWED: the caller must go to
    the passport. Merging `None` with an empty string means SILENTLY
    discarding an existing parse and answering "there is nothing to compare
    with".

    Exactly the first line is read: for `L0.jsonl` that is the header, and
    the rest of the file (up to 1.4 MB per floor) is not touched at all.
    """
    # THROUGH THE SNAPSHOT'S DOOR, NOT A BARE `open`: the janitor lays a
    # cooled-down parse down as `L0.jsonl.gz`, and a direct open would
    # return `None` — i.e. OUR OWN blindness disguised as "the header could
    # not be read". The shape was caught 19.08 in the read kernel
    # (`extract._read_header`) and cleaned up here as well, not later.
    # 🔴 THE LOCAL IMPORT WAS REMOVED 28.08.2026: `open_snapshot` is already
    # imported at the module level (line 69). A second import of the same
    # name inside the function SHADOWS the first — and then a fix to the
    # module import silently never reaches this function. The guard
    # `test_authority_boundaries` catches exactly this.

    # 🔴 `touch=False` — THE SAME ARGUMENT AS FOR THE PASSPORT ABOVE, AND
    # WITHOUT BOTH THE FIX IS INCOMPLETE. This header is read for EVERY
    # candidate under resolution, meaning it too dates all of them with
    # today's date and erases the freshness that decides the choice. Fixing
    # the passport alone was not enough — measured: the `.last_access`
    # marker kept appearing in both folders.
    try:
        with open_snapshot(l0, "rt", encoding="utf-8", touch=False) as handle:
            head = json.loads(handle.readline())
    except (OSError, ValueError):
        return None
    if not isinstance(head, Mapping):
        return None
    document = head.get("document")
    if not isinstance(document, Mapping):
        return None
    name = document.get("doc_name")
    return name if isinstance(name, str) else None


def _evidence_rank(row: Mapping[str, Any], project_uid: str) -> int:
    """Strength of the identity evidence: 2 authority · 1 lineage · 0 nothing.

    The rank is NOT the quality of the parse, nor its freshness. It answers
    one question: how firmly do we know that this parse is about the SAME
    document.
    """
    if not project_uid:
        return 0
    fact = row.get("document_identity")
    if not isinstance(fact, Mapping):
        return 0
    if _passport_uid(row) != project_uid:
        return 0
    source = fact.get("source")
    return 2 if source in _authoritative_sources() else 1


def _passport_uid(row: Mapping[str, Any]) -> str:
    """The identity value from the passport; empty means the parse was taken
    before this wave."""
    fact = row.get("document_identity")
    if not isinstance(fact, Mapping):
        return ""
    value = fact.get("value")
    return value if isinstance(value, str) else ""


def _version_drift(row: Mapping[str, Any], live_version: str) -> str:
    """"2023 -> 2026" or empty. If BOTH sides are silent, we stay silent too.

    Both sides HAVE the value and have never been checked against each
    other: the parse writes `passport.revit_version`, the live side
    `__revit_version` from `doc.Application.VersionNumber`
    (`open_model.py:1986`). Measurement 20.08.2026: the corpus has 54 parses
    and ELEVEN unique names; 94% of parses sit in a group sharing a name, 49
    of 54 share a name AND have no identity. Given such indistinguishability,
    the version is the only common trait left, and staying silent about its
    mismatch means passing off someone else's building as one's own past
    state.
    """
    theirs = str(row.get("revit_version") or "").strip()
    mine = str(live_version or "").strip()
    if not theirs or not mine or theirs == mine:
        return ""
    return f"{theirs} -> {mine}"


def _freshness_of(row: Mapping[str, Any], project_uid: str,
                  age_days: float, live_version: str = "") -> Freshness:
    """FOUR outcomes, not two, and each one is named by its own field.

    The difference between them decides what to do with the finding, so
    they must not be merged: "identity proven" and "only the name matched"
    lead to different actions, while "the parse was taken before this wave"
    is a fact ABOUT US, not about the building.
    """
    fact = row.get("document_identity")
    source = (fact.get("source") if isinstance(fact, Mapping) else None) or ""
    row_uid = _passport_uid(row)
    drift = _version_drift(row, live_version)
    tail = ("" if not drift else
            f"; 🔴 И РАЗБОР СНЯТ В ДРУГОМ РЕВИТЕ ({drift}) — апгрейд это "
            f"объясняет, но у документа с ходовым именем это первый признак, "
            f"что файл ДРУГОЙ")

    if not row_uid:
        return Freshness(
            proven=False, matched_by="doc_title", age_days=age_days,
            version_drift=drift,
            why=("совпало ИМЯ документа; разбор снят ДО того, как паспорт "
                 "научился нести личность, и доказать «тот же файл» нечем"
                 + tail))
    if not project_uid:
        return Freshness(
            proven=False, matched_by="doc_title", age_days=age_days,
            version_drift=drift,
            why=("совпало ИМЯ; разбор личность НЕСЁТ, но живая сторона её не "
                 "дала — сравнивать не с чем, и это факт о НАШЕМ чтении"
                 + tail))
    if source in _authoritative_sources():
        return Freshness(
            proven=True, matched_by=source, age_days=age_days,
            version_drift=drift,
            why=("личность документа совпала по источнику, который Autodesk "
                 "контрактует как авторитет логической модели" + tail))
    return Freshness(
        proven=False, matched_by=source or "project_uid", age_days=age_days,
        version_drift=drift,
        why=("совпали ИМЯ и РОДОСЛОВНАЯ (`ProjectInformation.UniqueId`); это "
             "сильнее имени, но не доказательство: Save As несёт то же "
             "значение, поэтому «тот же файл» отсюда не следует" + tail))


def _bbox_of(element: Mapping[str, Any]
             ) -> tuple[list[float], list[float]] | None:
    lo = element.get("bbox_min_mm")
    hi = element.get("bbox_max_mm")
    if (not isinstance(lo, list) or not isinstance(hi, list)
            or len(lo) != 3 or len(hi) != 3):
        return None
    try:
        lo_f = [float(v) for v in lo]
        hi_f = [float(v) for v in hi]
    except (TypeError, ValueError):
        return None
    if any(a != a for a in lo_f + hi_f):        # NaN
        return None
    if any(hi_f[i] < lo_f[i] for i in range(3)):
        return None
    return lo_f, hi_f


def iter_l0_elements(path: pathlib.Path) -> Iterator[dict]:
    """Elements of the L0 parse. A line without `record == "element"` is
    skipped.

    Reads line by line and does not hold the document in memory: a tower has
    115 889 elements, and "read everything, then filter" would cost a
    gigabyte for a scope only a handful will fall into.
    """
    # 🔴 THROUGH `open_snapshot`, NOT A BARE `open` (26.08.2026).
    #
    # The parse corpus is COMPRESSED: `graph_check` has `L0.jsonl.gz` lying
    # on disk, while this reader was opening `L0.jsonl` and failing with
    # `FileNotFoundError`. The failure was caught higher up and did not fail
    # the turn — so the background collision check SILENTLY never worked in
    # prod at all, from the moment the corpus was compressed. Reproduced
    # twice in a row by a live model turn (07:48:50 and 07:50:17), and the
    # same line stood in EVERY receipt that day: «ПРОВЕРКА НА КОЛЛИЗИИ НЕ
    # ВЫПОЛНЕНА… Это НЕ „коллизий нет“ — это „не смотрели“». The receipt was
    # honest; I read past it.
    #
    # The first diagnosis ("an extra `backend/` in the path") was REFUTED by
    # checking: the doubling `backend/backend/data` here is NOT a typo, it
    # is documented at `course/building.py` — the export lays parses down
    # exactly this way. The path was correct the whole time; what was not
    # being read was the COMPRESSION.
    #
    # This is the sixth carrier of a shape the agreement registry already
    # holds (`agreements`, agreement 3: "whoever asks about compression is
    # the one who reads through compression"). Five were found 21.08 in
    # `kir/course/`; this one lives in `kir/clash/`, which that census never
    # looked into.
    with open_snapshot(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, Mapping) or row.get("record") != "element":
                continue
            element = row.get("element")
            if isinstance(element, Mapping):
                yield dict(element)


def load(run_dir: Any, region: Region, *, doc_name: str = "",
         freshness: "Freshness | None" = None) -> Existing:
    """Parse + scope -> bodies of the existing building in the shared address
    space.

    Refusals are NAMED, not returned as emptiness: the path is not set,
    there is no catalog, there is no `L0.jsonl`, the scope is empty — four
    different facts, and the receipt's reader must tell them apart.
    """
    # 🔴 THE IMPORT IS LOCAL ON PURPOSE, AND THIS IS NOT SLOPPINESS
    # (20.08.2026). `kir.clash` is deliberately decoupled from
    # `kir.decompile`: the latter drags in `lift` -> `reverse_contract`,
    # which validates the entire operation registry on import. Raising this
    # name to module level, I got, for ten minutes,
    # `kir.clash.existing` that stops importing the moment a neighboring wave
    # touches the registry — i.e. I traded a NameError in one function for a
    # broken clash detector entirely. The decoupling was restored.
    #
    # WHAT THEN HOLDS THE CLASS, if the rule has two carriers. Not import
    # style, but the RATCHET: `tools/scope_audit.py` genuinely parses scope
    # boundaries and turns red on any name called outside its scope. It is
    # also what caught this defect, when grep and two homemade instruments
    # gave zero.
    from kir.model.snapshot_io import snapshot_file_exists

    if run_dir is None:
        return Existing.absent("источник стоящего не задан")
    root = pathlib.Path(str(run_dir))
    if not root.exists():
        return Existing.absent(f"каталога разбора нет: {root}")
    l0 = root / "L0.jsonl"
    if not snapshot_file_exists(l0):
        return Existing.absent(f"в разборе нет L0.jsonl: {root.name}")
    if region.empty:
        return Existing.absent(
            "область пуста: пачка не построила ни одного тела, "
            "и сравнивать было НЕ ЧЕМУ с нашей стороны")

    elements: list[dict] = []
    scanned = 0
    without_bbox = 0
    for element in iter_l0_elements(l0):
        scanned += 1
        box = _bbox_of(element)
        if box is None:
            without_bbox += 1
            continue
        if not region.admits(box[0], box[1]):
            continue
        raw_id = element.get("element_id")
        if raw_id is None:
            without_bbox += 1
            continue
        # The address is rewritten INTO THE SHARED SPACE, everything else is
        # as in the parse: bodies are built by the same `build_hull`, and
        # substituting its input would mean setting up a second builder.
        element["element_id"] = existing_source_id(raw_id)
        elements.append(element)
    return Existing(
        present=True,
        elements=tuple(elements),
        source=root.name,
        doc_name=doc_name or root.name,
        region=region,
        scanned=scanned,
        admitted=len(elements),
        without_bbox=without_bbox,
        freshness=freshness,
    )


#: THE PAIR FILTER DOES NOT LIVE HERE, AND THIS IS DELIBERATE.
#: `detect.bundle_vs_document_pair_filter` is the only one, and the scope is
#: named in the canon of scopes (`detect.SCOPES`), because the detector
#: refuses an unknown filter: "the search scope must be named in the canon".
#: A second copy of the predicate here would be exactly our own named
#: defect — two functions obliged to match, with nothing forcing them to.


def pairs_compared(new_bodies: int, existing_bodies: int) -> int:
    """How many pairs were handed to the filter — EXACTLY, not by estimate.

    Computed by a formula, because both counts are known by construction:
    all pairs within the batch plus all batch×existing pairs. `None` is
    forbidden here — read as zero, it would turn "not counted" into "none at
    all".
    """
    n = max(0, int(new_bodies))
    m = max(0, int(existing_bodies))
    return n * (n - 1) // 2 + n * m
