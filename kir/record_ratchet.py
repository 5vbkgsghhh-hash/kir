"""A dated ratchet for the compiler's LISTS OF RECORDS.

WHY THIS MODULE EXISTS
------------------------
In a single day (09.08.2026), across six independent pieces of work, the
barrier turned out not to be code, but an honestly filed RECORD about code
that had outlived its fact. Three verified examples, all three from this
same batch:

  * ``_KNOWN_NAKED`` held ``route_pipe_system``/``route_duct_system`` as
    "geometrically bare." A witness for segment ends had stood there since
    27.07 (``97892ce5``/``557d55fc``) and live-rolled back the program on
    30.07 — the instrument did not see it because it looked for
    ``return f(...)``, while the emitter took the helper by tuple
    unpacking. TWO audits in a row read the name in the debt list as a
    measurement;
  * ``UNPROVEN["create_dimension"]`` told the model "the op doesn't work."
    The record is from 27.07, the fix from 28.07: the model went around a
    working op for a week and a half;
  * ``_OPS_BLIND["place_family"]`` explained the blindness by saying the
    category "cannot be read from the program." True — but it lives in the
    SNAPSHOT, and acceptance simply never asked it. The corpus's
    highest-load op (7000 placements) was blind because of a substitution
    in the REASONING, not because of missing data.

The diagnosis in one line: **this tree has excellent MEASUREMENT discipline
and no STALENESS discipline whatsoever.** A list of names with a reason in
a comment is read by its consumer — a model, an acceptance judge, a test —
as a MEASUREMENT, and nothing forces anyone to measure it again.

THIS IS NOT A SECOND RATCHET, IT IS THE SAME ONE
---------------------------------------------------
The cure was built once — the dark-MODULES journal
(``tests/test_capability_reachability.py``, part three, ``a9e500d7``): 111
rows with the fields "reason, decision date, deadline, verdict" and a test
that fails an overdue record. Exactly THE SAME mechanism lives here,
factored out into one place so the modules journal and the records journals
do not drift apart in form: the modules journal imports ``Entry``,
``check_form``, and ``REVIEW_DAYS`` from here. Setting up a second mechanism
alongside it would mean repeating the very defect both are written against.

WHAT IS CHECKED ON IMPORT HERE, WHAT IS CHECKED BY A TEST, AND WHY THE LINE
FALLS EXACTLY HERE
-----------------------------------------------------------------------------
The FORM of a row is checked in ``Ledger.__init__``, that is, on importing
the module that declares it: a row with an unparsable date, or a verdict
not from the dictionary, makes the module UNIMPORTABLE. This is the same
discipline as ``WitnessCheck``, which cannot be built without a verdict —
the class of defect is removed by construction, not by attentiveness.

The DEADLINE is checked by a TEST and never by the import. Otherwise a
calendar date arriving would take down prod: a record whose deadline has
passed is a reason to wake a human, not to refuse the user a record in
Revit. The difference is stated here outright, because the temptation to
"check everything in one place" would have cost an outage.

WHAT THIS INSTRUMENT CANNOT DO IS STATED UP FRONT
----------------------------------------------------
It holds the FORM of a record and its DEADLINE. It cannot check that the
reason is still TRUE — only the instrument of that specific domain can do
that (a corpus of live runs for ``UNPROVEN``, an emitter walk for
``_KNOWN_NAKED``, an extraction table for ``capture_gap``). So every journal
must have its own recheck test standing beside it, and the deadline exists
for exactly one purpose: so that someone runs that test again.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Mapping, NamedTuple

__all__ = [
    "CLOSE_BY", "STANDS", "DROP_BY", "RECORD_VERDICTS",
    "REVIEW_DAYS", "Entry", "Ledger", "RecordFormError",
    "ALL_LEDGERS", "check_form", "check_expiry",
]


class RecordFormError(ValueError):
    """A journal row of invalid form. Raised ON IMPORT, not in a test."""


#: Three verdicts for a record, and there is no third kind, "say nothing,"
#: among them — the same closed set as the dark-modules journal, but in its
#: own words: there it is about a MODULE ("wire it in/keep it dark/remove
#: it"), here it is about the GAP the record describes.
#:
#:   close-by       — the gap closes through work: a live run, a field in
#:                    the capture, a witness. Such a record MUST have a
#:                    deadline;
#:   stands-because — the gap is STRUCTURAL and will never close (a snapshot
#:                    does not hold what is not in it; Revit decides on its
#:                    own). There is no deadline by construction — a
#:                    standing decision is held not by a deadline, but by
#:                    repeatedly reaffirming `decided_on`;
#:   drop-by        — the RECORD ITSELF is due for removal by the deadline:
#:                    it is already wrong or superseded, and is kept only
#:                    until someone else's edit.
CLOSE_BY, STANDS, DROP_BY = "close-by", "stands-because", "drop-by"
RECORD_VERDICTS = (CLOSE_BY, STANDS, DROP_BY)

#: HOW MANY DAYS BEFORE A DECISION GOES STALE. The number is ASSIGNED, and
#: this is stated outright.
#:
#: It is NOT re-derived here: the 30-day threshold was derived (more
#: precisely — honestly assigned, with the attempt to derive it refuted) by
#: the dark-modules journal, and its full justification stands there, above
#: this same constant in its former home. Briefly, so as not to send the
#: reader off for every word: a measurement over the git history of 111
#: dark modules gave a median and a MAXIMUM of 28 days at a repository age
#: of 28 days — meaning the sample is censored by its own boundary and is
#: not a derivation; 30 days is longer than the entire visible history (not
#: one of today's records goes red from the mere fact of being filed) and
#: shorter than what it would take for a record to be forgotten (the tree's
#: pace is ~20 commits a day).
#:
#: THE CONSTANT IS DELIBERATELY THE SAME FOR BOTH JOURNALS. Two thresholds
#: would drift apart, and then "overdue" would mean different things in two
#: places of the same tree.
REVIEW_DAYS = 30

#: The default minimum length of a reason. A shorter reason explains
#: nothing, and a month from now will not help whoever reads it.
DEFAULT_MIN_REASON = 40


class Entry(NamedTuple):
    """One row of any journal: reason, decision date, deadline, verdict.

    ``due`` is the date by which the row must be ANSWERED: the gap is
    closed, the record is removed, or the decision is written anew. This is
    a REVIEW DEADLINE, not a delivery promise, and the wording is chosen
    deliberately: a delivery promise made on someone else's behalf is a
    fake unit of accounting, whereas a review must be carried out by
    someone regardless.

    The fields and their order match ``Dark`` of the dark-modules journal
    byte for byte — this is one type, not two similar ones.
    """
    verdict: str        # from the dictionary of a specific journal
    decided_on: str     # the ISO date when the decision was RECORDED
    due: str            # the ISO date of the review; empty ONLY for a standing decision
    reason: str         # why the gap exists — in words, not a placeholder


def check_form(
    entries: Mapping[str, Entry],
    *,
    verdicts: Iterable[str],
    standing: str,
    today: date | None = None,
    min_reason: int = DEFAULT_MIN_REASON,
) -> list[str]:
    """The form of EVERY row. Returns a list of complaints; empty means clean.

    What is checked is exactly what cannot be seen by eye in a diff:
      * the verdict comes from the closed dictionary — "leave it as is" is
        not a decision;
      * ``decided_on`` parses as an ISO date and is not dated in the future;
      * a standing verdict has NO deadline (a deadline on a permanent gap is
        a fiction), the others DO have a deadline, and it is not earlier
        than the decision itself;
      * the reason is not a placeholder.
    """
    today = today or date.today()
    verdicts = tuple(verdicts)
    bad: list[str] = []
    for name, e in sorted(entries.items()):
        if not isinstance(e, Entry):
            bad.append(f"{name}: не строка журнала ({type(e).__name__})")
            continue
        if e.verdict not in verdicts:
            bad.append(f"{name}: вердикт {e.verdict!r} не из {verdicts}")
        if len(e.reason.strip()) < min_reason:
            bad.append(f"{name}: причина-заглушка короче {min_reason} символов "
                       f"— через месяц она не поможет тому, кто это читает")
        try:
            decided = date.fromisoformat(e.decided_on)
        except ValueError:
            bad.append(f"{name}: decided_on {e.decided_on!r} — не ISO-дата")
            continue
        if decided > today:
            bad.append(f"{name}: решение датировано будущим ({e.decided_on})")
        if e.verdict == standing:
            if e.due:
                bad.append(f"{name}: у {standing} не бывает срока ({e.due}) — "
                           f"стоячее решение держится подтверждением "
                           f"decided_on, а не дедлайном")
            continue
        if not e.due:
            bad.append(f"{name}: вердикт {e.verdict} без срока — «когда-нибудь» "
                       f"это не решение")
            continue
        try:
            if date.fromisoformat(e.due) < decided:
                bad.append(f"{name}: срок {e.due} раньше самого решения "
                           f"{e.decided_on}")
        except ValueError:
            bad.append(f"{name}: due {e.due!r} — не ISO-дата")
    return bad


def check_expiry(
    entries: Mapping[str, Entry],
    *,
    today: date | None = None,
    review_days: int = REVIEW_DAYS,
) -> tuple[list[tuple[str, Entry]], list[tuple[str, Entry]]]:
    """``(overdue, stale)`` — THE VERY THING ALL OF THIS WAS BUILT FOR.

    Honesty without a deadline is an archive. Everything about
    ``route_pipe_system`` was written correctly in its own comment; the one
    thing missing was a day by which someone was obligated to answer.

    THE DEPENDENCE ON THE CALENDAR IS DELIBERATE. The suite will go red on
    rows that are not touched by their day, and this is not flakiness, it
    is the mechanism itself: a deadline that cannot go unnoticed. The right
    response is to re-measure with the INSTRUMENT and either close it,
    remove it, or write the decision anew with a new date; the wrong
    response is to push the date without making a decision, and that is
    visible in ``git log -p`` as a single line of diff.
    """
    today = today or date.today()
    overdue = [(n, e) for n, e in sorted(entries.items())
               if e.due and date.fromisoformat(e.due) < today]
    cutoff = today - timedelta(days=review_days)
    stale = [(n, e) for n, e in sorted(entries.items())
             if date.fromisoformat(e.decided_on) < cutoff]
    return overdue, stale


#: All declared record journals, by name. Filled in by ``Ledger`` ITSELF on
#: construction, that is, on importing the module that declares it: a test
#: does not have to know the list of journals by heart, or a new journal
#: could be set up bypassing the ratchet — exactly the defect the ratchet
#: catches.
ALL_LEDGERS: dict[str, "Ledger"] = {}


class Ledger:
    """Log of records: name, lines, dictionary of verdicts, its own instrument — in words.

    THE FORM IS CHECKED HERE, AT CONSTRUCTION. A line without a date or with
    a verdict not from the dictionary fails the IMPORT of the module that
    declared it. This way a new record physically cannot be created without
    a date and a deadline — which is exactly how all the earlier ones were
    created.

    ``instrument`` is a single line about WHAT re-verifies the truthfulness
    of this journal's lines. Not a decorative field: a record whose
    deadline has passed is re-verified by an instrument, not by reading its
    own comment, and if no instrument is named, the next person will end up
    reading the comment.
    """

    __slots__ = ("name", "entries", "verdicts", "standing", "instrument",
                 "min_reason")

    def __init__(self, name: str, entries: Mapping[str, Entry], *,
                 instrument: str,
                 verdicts: Iterable[str] = RECORD_VERDICTS,
                 standing: str = STANDS,
                 min_reason: int = DEFAULT_MIN_REASON) -> None:
        self.name = name
        self.entries = dict(entries)
        self.verdicts = tuple(verdicts)
        self.standing = standing
        self.instrument = instrument
        self.min_reason = min_reason
        if len(instrument.strip()) < 20:
            raise RecordFormError(
                f"{name}: у журнала не назван прибор перепроверки — без него "
                f"просроченную строку будут «проверять» её же комментарием")
        bad = check_form(self.entries, verdicts=self.verdicts,
                         standing=self.standing, min_reason=self.min_reason)
        if bad:
            raise RecordFormError(
                f"журнал {name}: строки неверной формы:\n  " + "\n  ".join(bad))
        ALL_LEDGERS[name] = self

    def __contains__(self, key: object) -> bool:
        return key in self.entries

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, key: str) -> Entry:
        return self.entries[key]

    def get(self, key: str, default=None):
        return self.entries.get(key, default)

    def items(self):
        return self.entries.items()

    def keys(self):
        return self.entries.keys()

    def values(self):
        return self.entries.values()

    def reason(self, key: str) -> str:
        """The reason in words — what the CONSUMER of the record sees.

        A separate method, not a field access, because there are many
        consumers of the reason (the instrument's description, the
        acceptance receipt, the emitter's refusal), and all of them must
        take ONE text: three separately typed texts drift apart — this
        house has already paid for that.
        """
        return self.entries[key].reason
