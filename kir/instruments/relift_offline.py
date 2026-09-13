"""Lift a persisted decompile run again, offline, with the current compiler.

L0 is the boundary. Everything below it -- lift, fold, canon -- is pure Python
over bytes already on disk, so a whole real building can be re-lifted without
Revit, without the bridge, and without the operator awake. That was true all
along and nobody had a way to do it: every path into the lifter ran through
live extraction, so the only numbers anyone ever quoted came from whichever
run happened to be live at the time.

That is why "100% roundtrip" was measured on 887 of 90 758 elements, and why
place_family was verified on 327 of the 53 791 placements the building
actually contains. Not a missing capability -- a missing measurement.

Point it at a decompile directory (the one holding L0.jsonl) and it reports
what the lifter makes of every element: which ops, which atoms, and why.

    python tools/relift_offline.py backend/data/decompile/демо-v3
    python tools/relift_offline.py <dir> --json out.json
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any


#: Side indexes this run was MISSING: file name -> reason. Filled by
#: `absent_side_indexes()`, read by the report BEFORE the numbers.
#:
#: 🔴 WHY ALONGSIDE, NOT INSTEAD OF `None`. `_load_side_index` must return
#: `None` — the instrument computes even over an incomplete decompile, it
#: must not be dropped. But the docstring promises "the stage DID NOT
#: RUN", while `None` means exactly "there is no file": a deleted index,
#: a foreign directory, and a stage that never ran all arrive as one
#: value (journal: F-301). The verdict is unchanged, but the silence now
#: has a reason that can be asked.
#: Names the instrument actually asks the decompile for. The list is
#: closed: listing here what the instrument does not read would mean
#: complaining about the absence of something not needed.
_SIDE_INDEX_NAMES: "tuple[str, ...]" = (
    "family_placement.index.json", "sketch.index.json",
    "curtain.index.json", "annotation.index.json", "tag.index.json",
    "dimension.index.json", "mep_system.index.json",
)


def absent_side_indexes(directory: pathlib.Path,
                        names: "tuple[str, ...]") -> dict[str, str]:
    """Which of the listed indexes are NOT PRESENT next to this decompile.

    Three outcomes are distinguished: there is no directory at all (in
    which case it is pointless to list files — one reason covers all of
    them), the directory exists and the file does not, the file exists.
    """
    from kir.decompile.snapshot_io import snapshot_file_exists

    if not directory.is_dir():
        return {"": (f"каталога разбора нет: {directory} — это факт о МАШИНЕ, "
                     f"а не о стадиях. Перечислять отсутствующие индексы "
                     f"здесь нечего: не найдено НИ ОДНОГО, потому что искать "
                     f"было негде")}
    return {
        name: (f"{name} не лежит рядом с разбором: «стадия не запускалась» и "
               f"«индекс удалён» отсюда неотличимы")
        for name in names
        if not snapshot_file_exists(directory / name)
    }


class SideIndexUnreadable(RuntimeError):
    """The index IS PRESENT and FAILED TO READ. Not the same as "there was
    no stage".

    🔴 SET UP 2026-09-04 (RT-15). Both loaders carried
    `except (OSError, ValueError): return None`, and `None` meant three
    things AT ONCE. A direct measurement:

        a healthy index -> {'a': 1}
        CORRUPTED       -> None
        ABSENT          -> None      indistinguishable

    The cost is not in the count, but in the CONCLUSION: the report
    prints "the stage did not run" and computes the compiler's coverage
    on a degraded representation, that is, it charges the lifter for what
    a corrupted file did. ABSENCE is a legitimate outcome (named by
    `absent_side_indexes()`), CORRUPTION is not.

    The refusal is raised when the caller did NOT SET UP a ledger:
    `refusals={}` means "I will finish counting over an incomplete
    decompile and show the reason" — that is what `relift()` does — while
    a bare call turns red, because silently returning `None` is not
    allowed here.
    """

    def __init__(self, name: str, path: "pathlib.Path", cause: str) -> None:
        self.name, self.path, self.cause = name, path, cause
        super().__init__(f"{name} лежит рядом с разбором и НЕ ПРОЧЁЛСЯ "
                         f"({path}): {cause}")


def _unreadable(name: str, path: "pathlib.Path", cause: str,
                refusals: "dict | None") -> None:
    """Record the reason and return `None` — or turn red if there is nowhere to record it."""
    if refusals is None:
        raise SideIndexUnreadable(name, path, cause)
    refusals[name] = cause
    return None


def unreadable_side_indexes(directory: pathlib.Path,
                            names: "tuple[str, ...]") -> dict[str, str]:
    """Which of the PRESENT indexes fail to read, and why.

    The companion of `absent_side_indexes()` and its opposite: that one
    answers about absence, this one about corruption. Together they cover
    three outcomes with three different answers, not one `None` for all.

    🔴 THIS FUNCTION DOES NOT SPEAK ABOUT ABSENCE IN ITS OWN VOICE, IT
    ASKS THE COMPANION, and that is not a style choice. The first edition
    carried two of its own `if not <exists>` with a bare return — and
    `test_no_new_mute_source` turned red on them in that very run,
    justly: "there is no directory" and "there is no file" are already
    named by `absent_side_indexes()`, and a second answer about the same
    fact would diverge from the first at the very next edit. Here it is
    taken READY-MADE.
    """
    отсутствуют = absent_side_indexes(directory, names)
    if "" in отсутствуют:
        # There is no directory at all: there was NOTHING TO LOOK AT, and
        # an empty answer from here would be a fact about the machine
        # disguised as a fact about the files. The reason is already
        # named by the companion — it travels to the reader verbatim,
        # without paraphrase.
        return dict(отсутствуют)
    out: dict[str, str] = {}
    for name in names:
        if name in отсутствуют:
            continue
        _load_envelope(directory, name, refusals=out)
    return out


#: 🔴 THE NAMES OF THE INDEXES THE OFFLINE READER FEEDS TO THE LIFTER — IN
#: ONE SET. The key is the `lift.lift_document_detailed` parameter, the
#: value is the file name next to the decompile. An envelope
#: (`_load_envelope`) versus a bare dict is chosen by a third field: an
#: envelope has a schema version, and a decompile taken before the stage
#: must read as "there is no index", not as the stage's empty value.
_SIDE_INDEX_FEED: "tuple[tuple[str, str, bool], ...]" = (
    ("profile_index", "sketch.index.json", False),
    ("family_placement_index", "family_placement.index.json", True),
    ("wall_curve_index", "curve.index.json", False),
    ("curtain_index", "curtain.index.json", True),
    ("annotation_index", "annotation.index.json", True),
    ("tag_index", "tag.index.json", True),
    ("dimension_index", "dimension.index.json", True),
    ("mep_system_index", "mep_system.index.json", True),
    ("join_index", "join.index.json", True),
    ("group_index", "group.index.json", True),
)

#: The key under which a bare dict is placed in `_load_side_index`. Needed
#: only by the two inputs that have no envelope.
_SIDE_INDEX_BARE_KEY = {"profile_index": "sketch_index",
                        "family_placement_index": "family_placement_index",
                        "wall_curve_index": "curve_index"}


def side_indexes_for(directory: pathlib.Path, *,
                    refusals: "dict | None" = None) -> "dict[str, Any]":
    """ALL of a decompile's side indexes — IN ONE SET for all offline readers.

    🔴 THE LIST WAS HANDWRITTEN IN THREE PLACES AND DIVERGED (F-304,
    2026-08-30). Measured: `orchestrator.decompile` feeds the lifter TEN
    indexes, `relift_offline` — eight, the compilation gate — seven. The
    gate's comment claimed at the same time "ALL SEVEN side indexes,
    exactly as passed by `relift_offline.relift` and the live pipeline",
    and it named the cost of the error itself: "an index forgotten here
    does not fail the gate, it SILENTLY drops it onto a degraded
    representation".

    The reach of the miss, measured against the live corpus on 2026-08-30
    (81 decompiles with L0):
        group.index.json      present in 67 decompiles   <- almost the
                                                              whole corpus
        dimension.index.json  present in 10
        join.index.json       present in  7
    Sixty-seven buildings out of eighty-one were judged by the gate on a
    representation in which `create_group` operations could not have
    appeared at all.

    Adding the three names to the gate by hand would have been a FOURTH
    handwritten list, and it would have fallen behind by tomorrow. The
    set lives here, and completeness is held by a NUMBER, not by
    attention: the `состав_подачи_лифту_полон` agreement checks this
    function's keys against `lift_document_detailed`'s optional
    parameters.

    🔴 WHAT THIS FUNCTION DOES NOT DO. It does not parse the indexes into
    their types — the lifter needs `group_index` parsed
    (`parse_group_index`), and the caller does that: parsing pulls in
    dependencies the offline reader does not always need, while the set
    does not.
    """
    out: "dict[str, Any]" = {}
    for param, filename, as_envelope in _SIDE_INDEX_FEED:
        if as_envelope:
            value = _load_envelope(directory, filename, refusals=refusals)
            if value is None and param in _SIDE_INDEX_BARE_KEY:
                # No envelope — read as a bare dict with the same key used
                # before envelopes existed. The argument is recorded at
                # `family_placement`: a bare dict was losing `failures`.
                value = _load_side_index(
                    directory, filename, _SIDE_INDEX_BARE_KEY[param],
                    refusals=refusals)
        else:
            value = _load_side_index(
                directory, filename, _SIDE_INDEX_BARE_KEY[param],
                refusals=refusals)
        out[param] = value
    return out


def _load_side_index(directory: pathlib.Path, name: str, key: str, *,
                     refusals: "dict | None" = None) -> Any:
    """A side index, or None when that stage never ran for this document.

    Corruption is NOT this case: it goes into `refusals` or raises
    `SideIndexUnreadable` (RT-15, 2026-09-04)."""
    from kir.decompile.snapshot_io import (
        read_snapshot_text, snapshot_file_exists)

    path = directory / name
    if not snapshot_file_exists(path):
        return None
    try:
        # 🔴 `touch=False` — A DECISION, NOT A DEFAULT LEFT UNEXAMINED
        # (2026-08-19). By default `read_snapshot_text` writes
        # `.last_access` into the decompile directory, and the cleaner
        # decides what has gone cold by this mark. The question "who owns
        # the mark" is settled by MEASUREMENT, not taste: this module
        # lives in `tools/` and no module of `kukai/` imports it — only
        # tests. That is, every consumer here is an INSTRUMENT, and an
        # instrument that updates the mark keeps the decompile "warm" by
        # the mere fact of reading it, and thereby decides for the
        # cleaner. This is the observer's fingerprint: two of our
        # censuses are already poisoned by it — the viewer's scene cache
        # stopped hitting FOREVER, and the corpus dating declared 67 of
        # 76 runs fresher than they are.
        # Should a prod consumer appear, it will need the mark, and it
        # must say so through a parameter rather than silently inheriting
        # the default.
        payload = json.loads(read_snapshot_text(path, touch=False))
    except (OSError, ValueError) as exc:
        return _unreadable(name, path, f"{type(exc).__name__}: {exc}", refusals)
    if not isinstance(payload, dict):
        # It parsed, but it is not an object. Previously `None` stood
        # here too — a third entry into the same silence: content of a
        # foreign kind read as "there was no stage".
        return _unreadable(
            name, path,
            f"содержимое — {type(payload).__name__}, а не объект индекса",
            refusals)
    return payload.get(key, payload)


def _load_envelope(directory: pathlib.Path, name: str, *,
                   refusals: "dict | None" = None) -> Any:
    """The whole persistent index envelope (with schema and receipts).

    Corruption is NOT "there is no envelope": see `SideIndexUnreadable`
    (RT-15, 2026-09-04)."""
    from kir.decompile.snapshot_io import (
        read_snapshot_text, snapshot_file_exists)

    path = directory / name
    if not snapshot_file_exists(path):
        return None
    try:
        # 🔴 `touch=False` — A DECISION, NOT A DEFAULT LEFT UNEXAMINED
        # (2026-08-19). By default `read_snapshot_text` writes
        # `.last_access` into the decompile directory, and the cleaner
        # decides what has gone cold by this mark. The question "who owns
        # the mark" is settled by MEASUREMENT, not taste: this module
        # lives in `tools/` and no module of `kukai/` imports it — only
        # tests. That is, every consumer here is an INSTRUMENT, and an
        # instrument that updates the mark keeps the decompile "warm" by
        # the mere fact of reading it, and thereby decides for the
        # cleaner. This is the observer's fingerprint: two of our
        # censuses are already poisoned by it — the viewer's scene cache
        # stopped hitting FOREVER, and the corpus dating declared 67 of
        # 76 runs fresher than they are.
        # Should a prod consumer appear, it will need the mark, and it
        # must say so through a parameter rather than silently inheriting
        # the default.
        payload = json.loads(read_snapshot_text(path, touch=False))
    except (OSError, ValueError) as exc:
        return _unreadable(name, path, f"{type(exc).__name__}: {exc}", refusals)
    if not isinstance(payload, dict):
        return _unreadable(
            name, path,
            f"содержимое — {type(payload).__name__}, а не конверт индекса",
            refusals)
    return payload


_SIDE_INDEX_FILES = (
    ("curve", "curve.index.json"),
    ("curtain", "curtain.index.json"),
    ("sketch", "sketch.index.json"),
    ("family_placement", "family_placement.index.json"),
    ("group", "group.index.json"),
    # The annotation stage. The line was added TOGETHER with the stage,
    # not later: without it the instrument would show text notes as
    # atoms even though the live pipeline lifts them — exactly the
    # measurement blind spot that already cost us groups (task #34).
    ("annotation", "annotation.index.json"),
    ("mep_system", "mep_system.index.json"),
    # The TAG stage. It was absent here from the moment it appeared, and
    # because of that its receipts never made it into the slice breakdown
    # in a SINGLE coverage measurement: k2_ar_rd_v8 holds 317 refusals in
    # tag.index.json, while side_failures_by_stage printed only
    # curtain/family_placement/sketch.
    ("tag", "tag.index.json"),
    # The DIMENSION stage — together with the stage, not later, for
    # exactly the reason recorded a line above about tags.
    ("dimension", "dimension.index.json"),
)


def _side_receipts(directory: pathlib.Path, *,
                   refusals: "dict | None" = None) -> dict[str, Any]:
    """The aggregate of ``failures`` across all five side indexes present
    on disk.

    Read as RAW JSON, not a parsed object: the instrument must work even
    on a decompile taken with a different compiler version — otherwise it
    would stop answering "what was measured there" at exactly the moment
    that question is asked (after a schema change).
    The breakdown is COMPUTED BY THE SAME CODE as the live run
    (:func:`summarize_side_failures`), not by a second copy of it. A copy
    used to exist here, and it diverged from the original in exactly the
    spot this instrument is read for: both used to lump slices and
    definitions together into one number.
    """
    import types

    from kir.decompile.side_contract import (
        receipts_summary_ru, summarize_side_failures,
    )

    extractions: dict[str, Any] = {}
    for stage, name in _SIDE_INDEX_FILES:
        payload = _load_envelope(directory, name, refusals=refusals)
        if not isinstance(payload, dict):
            continue
        failures = payload.get("failures")
        if not isinstance(failures, list) or not failures:
            continue
        # Raw dicts, not parsed receipts: the file could have been taken
        # with a schema today's strict parser does not know, and in that
        # case answering "how much was measured" matters more than
        # refusing outright.
        extractions[stage] = types.SimpleNamespace(
            failures=tuple(f for f in failures if isinstance(f, dict)))
    summary = summarize_side_failures(extractions)
    summary["side_cuts_summary_ru"] = receipts_summary_ru(summary)
    return summary


class IncompleteSnapshot(RuntimeError):
    """The L0 stream is truncated: there is no footer, meaning the
    snapshot is UNFINISHED.

    A separate type, not a `ValueError`: "the file failed to parse" and
    "the file parsed but broke off mid-word" call for different moves.
    The first calls for fixing the layout, the second for re-running
    extraction.
    """


def load_document(directory: pathlib.Path, *, require_committed: bool = False):
    """Rebuild the frozen L0Document from L0.jsonl.

    The header record carries the document metadata; every later record
    carries one element.

    🔴 THE ONE-SIDEDNESS OF THE PREVIOUS CLAIM IS NAMED (F-303, 2026-08-30).
    This used to say «so a file this refuses is one the live pipeline
    would have refused too». Formally true and useless in the other
    direction: the live pipeline requires a COMMITTED footer
    (`extract.L0JSONLReader`), while this reader never asked for a footer
    AT ALL. Parity broke not where it was promised: what the live
    pipeline REJECTS, the gate ACCEPTED.

    Measured against the live corpus on 2026-08-30 — 81 decompiles with
    `L0.jsonl`:
        headers 81 · footers 77 · WITHOUT A FOOTER 4
        k2_ar_rd_v4          gate: 18489 elements  · canonical: REFUSAL
        k4_geom_wave_15aug   gate:   993 elements  · canonical: REFUSAL
        sklnk_eom_r26_v3     gate:  1937 elements  · canonical: REFUSAL
        mnvnk_atr_pd_b14_k3… gate:     0 elements  · canonical: REFUSAL
    Four real buildings sit in the corpus unfinished, and the gate
    reported success on them.

    🔴 THE REQUIREMENT IS SET BY WHOEVER JUDGES, NOT BY WHOEVER READS. The
    default remains LENIENT on purpose: re-lift instruments must be able
    to read broken decompiles — that is exactly how they fix them — and a
    reader that refuses to look at anything broken is useless at the very
    moment it is needed. `require_committed=True` is for whoever is
    passing JUDGMENT ON THE BUILDING: for them an incomplete snapshot
    gives "zero refusals", and that is a statement about OUR OWN READING
    dressed up as a statement about the compiler.
    """
    from kir.decompile.schema import L0Document, L0Element
    from kir.decompile.snapshot_io import open_snapshot

    path = directory / "L0.jsonl"
    header: dict[str, Any] | None = None
    elements: list[Any] = []
    # Category statuses are needed by the census (§18.1): a shortfall in
    # a category with status partial is a FAILED PAGE, not "the category
    # was read incompletely for an unknown reason". The distinction is
    # typed, and losing it offline means handing the instrument a less
    # precise reason than the one sitting in the very same file, one line
    # below.
    statuses: list[Any] = []
    #: Whether we saw a `footer` record. This reader used to simply
    #: ignore the `footer` kind, and so could not tell a fully-read
    #: stream apart from a truncated one.
    footer_seen = False
    with open_snapshot(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kind = row.get("record")
            if kind == "header":
                header = row["document"]
            elif kind == "element":
                elements.append(L0Element.from_dict(row["element"]))
            elif kind == "category_status":
                statuses.append(row["status"])
            elif kind == "footer":
                footer_seen = True
    if header is None:
        raise SystemExit(f"{path}: no header record — not a frozen L0 file")
    if require_committed and not footer_seen:
        raise IncompleteSnapshot(
            f"{path}: поток L0 не завершён футером — это НЕДОЧИТАННЫЙ слепок, "
            f"а не маленькое здание. Прочитано элементов: {len(elements)}; "
            f"канонический читатель (`extract.L0JSONLReader`) отвергает этот "
            f"же файл. СЛЕДУЮЩИЙ ХОД: доизвлечь разбор либо судить по другому")
    document = L0Document.from_dict({
        **header, "elements": [], "category_status": statuses})
    return document, tuple(elements)


def relift(directory: pathlib.Path) -> dict[str, Any]:
    from kir.decompile import lift
    import dataclasses

    document, elements = load_document(directory)
    document = dataclasses.replace(document, elements=elements)

    # §18.1: the denominator. As long as the instrument computed
    # percentages from the NUMBER OF ELEMENTS IN L0, it was measuring the
    # category table's sampling share, not the building's share, and it
    # stayed silent about what was never looked at at all. The census may
    # be absent from the decompile (taken before this wave) — in that
    # case it is printed as such, not replaced by a zero.
    from kir.decompile.census import reconcile_census
    balance = reconcile_census(document)

    # §18.2: the placement index is passed whole, as an ENVELOPE, not a
    # bare dict of rows. A bare dict was losing ``failures``, and the
    # lift could not name the refusal reason from the receipt — every
    # clipped element got the same «absent from the family placement side
    # index».
    # 🔴 A CORRUPTION LEDGER IS SET UP EXPLICITLY (2026-09-04, RT-15). The
    # report must finish counting even over a decompile with a broken
    # index — but has no right to pass its zeros off as "the stage did
    # not run": `side_indexes_unreadable` travels with the report and is
    # printed BEFORE the numbers, next to `side_indexes_absent`.
    unreadable: dict[str, str] = {}
    family_payload = _load_envelope(directory, "family_placement.index.json",
                                    refusals=unreadable)
    if family_payload is None:
        family_payload = _load_side_index(
            directory, "family_placement.index.json",
            "family_placement_index", refusals=unreadable)
    result = lift.lift_document_detailed(
        document,
        _load_side_index(directory, "sketch.index.json", "sketch_index",
                         refusals=unreadable),
        family_payload,
        wall_curve_index=_load_side_index(
            directory, "curve.index.json", "curve_index",
            refusals=unreadable),
        # The curtain wall index is passed as an ENVELOPE: it has a
        # schema version, and a decompile taken before the cell address
        # existed must read as "there is no address", not as "the cell is
        # at (0,0)".
        curtain_index=_load_envelope(directory, "curtain.index.json",
                                     refusals=unreadable),
        # The annotation index — also as an ENVELOPE: it has its own
        # schema version, and a snapshot taken before the stage must read
        # as "there is no index", that is, give the same
        # source_contract_gap verbatim as before.
        annotation_index=_load_envelope(directory, "annotation.index.json",
                                        refusals=unreadable),
        # The tag index — as an ENVELOPE, like the others. Forgetting it
        # here means measuring the compiler on a degraded representation:
        # a decompile WITH the stage would have given tags, while an
        # offline re-lift of the same decompile would show
        # source_contract_gap — and that would be charged to the lifter.
        tag_index=_load_envelope(directory, "tag.index.json",
                                 refusals=unreadable),
        # The dimension index — as an ENVELOPE, like the others.
        # Forgetting it here means measuring the compiler on a degraded
        # representation: a decompile WITH the stage would have given
        # dimensions, while an offline re-lift of the same decompile
        # would show source_contract_gap — and that would be charged to
        # the lifter.
        dimension_index=_load_envelope(directory, "dimension.index.json",
                                       refusals=unreadable),
        mep_system_index=_load_envelope(directory, "mep_system.index.json",
                                        refusals=unreadable),
    )

    # §18.2: side-index receipts — what "we looked and didn't finish
    # looking" means. Without them the coverage percentage is
    # indistinguishable from the skill percentage: a wall whose arc the
    # budget cut off rises as a chord and goes into the statistics as a
    # success (M5 of the 28.07 audit).
    receipts = _side_receipts(directory, refusals=unreadable)

    # A document's discipline is derived from the COMPOSITION of its
    # categories, not from the file name: the name lies easily (a training
    # copy, "detached", someone else's template), the composition does
    # not lie. This matters so that the coverage number always carries
    # with it WHAT IT WAS MEASURED ON — on 27.07 "coverage is stable
    # across buildings" was said based on two documents, both
    # architectural, and the claim collapsed on the very first non-AR
    # model.
    from kir.decompile.extract import _CATEGORY_SPECS
    _disc_of = {c.name: c.discipline for c in _CATEGORY_SPECS}
    disciplines: collections.Counter[str] = collections.Counter()
    for element in elements:
        disciplines[_disc_of.get(element.category, "shared")] += 1

    ops: collections.Counter[str] = collections.Counter()
    atoms: collections.Counter[str] = collections.Counter()
    atom_detail: collections.Counter[str] = collections.Counter()
    # Ops by the CATEGORY of the source element. Needed by whoever divides
    # ops into a denominator: the numerator and the denominator must be
    # about one class of content, and the class is determined by category,
    # not by the op's name (op names move every week). Measurement of
    # 10.08: without this breakdown `content_coverage` printed 100.07% on
    # `snowdon_plumb_v4`.
    category_of = {element.element_id: element.category for element in elements}
    ops_by_category: collections.Counter[str] = collections.Counter()
    # Nodes are plain L1 dicts: an op carries ``op_name``, an atom carries the
    # reason it could not become one.
    for node in getattr(result, "nodes", ()):
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "op":
            ops[str(node.get("op_name") or "?")] += 1
            ops_by_category[
                category_of.get(str(node.get("source_element_id")),
                                "no_category")] += 1
            continue
        # An atom's reason is a NESTED dict ({"code": ..., "detail": ...}), not
        # two sibling keys.  Reading it as siblings left ``atom_details`` empty
        # on every run ever made with this tool while ``atoms`` printed whole
        # stringified dicts — the detail is the only part that names the rule
        # that refused, so pooling reasons across models was impossible.
        raw = node.get("reason")
        if isinstance(raw, dict):
            code = raw.get("code") or raw.get("kind") or "?"
            detail = raw.get("detail") or raw.get("message")
        else:
            code = raw or node.get("code") or node.get("kind")
            detail = node.get("detail") or node.get("message")
        atoms[str(code)] += 1
        if detail:
            atom_detail[str(detail)[:120]] += 1

    total = sum(ops.values()) + sum(atoms.values())
    return {
        "directory": str(directory),
        "doc_name": document.doc_name,
        "disciplines": dict(disciplines.most_common()),
        # A document's discipline = the one whose NON-shared elements are
        # the most numerous in it. "shared" (levels, grids, generic
        # models) is excluded on purpose: it is present in all of them and
        # therefore distinguishes nothing.
        "discipline": (max(
            ((d, n) for d, n in disciplines.items() if d != "shared"),
            key=lambda item: item[1], default=("shared", 0))[0]),
        "revit_version": document.revit_version,
        "elements": len(elements),
        "lifted_nodes": total,
        "ops": dict(ops.most_common()),
        "ops_by_category": dict(ops_by_category.most_common()),
        "op_total": sum(ops.values()),
        "atoms": dict(atoms.most_common()),
        "atom_total": sum(atoms.values()),
        # No cap: a reason that is rare HERE may be the dominant one on the
        # next building, and truncating hides exactly that.
        "atom_details": dict(atom_detail.most_common()),
        "lifted_pct": round(100.0 * sum(ops.values()) / total, 2) if total else 0.0,
        # A generated child is not a gap: a parent family already creates it,
        # and lifting it individually would duplicate geometry.  Leaving those
        # in the denominator understates coverage by whatever share of the
        # building happens to be nested families — 0.1% on one document, 17% on
        # the next — so the honest figure is the only one comparable ACROSS
        # models, which is the only comparison that says anything.
        "generator_children": atoms.get("generator_child", 0),
        "honest_pct": (
            round(100.0 * sum(ops.values())
                  / (total - atoms.get("generator_child", 0)), 2)
            if total - atoms.get("generator_child", 0) > 0 else 0.0),
        # The two bases are printed side by side on purpose: "of what was
        # read" answers the question about the compiler, "of the
        # document" answers the question about the building. Substituting
        # one for the other is exactly the switch that §18.1 forbids.
        **balance.to_dict(),
        "census_summary_ru": balance.summary_ru(),
        "document_pct": balance.document_pct(sum(ops.values())),
        # Index corruption is a REPORT FIELD, not an stderr line: without
        # --json only someone watching the terminal would see it (the
        # same defect was already paid for once, at
        # `axes_census.skipped_snapshots`).
        "side_indexes_unreadable": dict(unreadable),
        **receipts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=pathlib.Path)
    parser.add_argument("--json", type=pathlib.Path, default=None,
                        help="also write the full report here")
    args = parser.parse_args(argv)

    # 🔴 THE CAUSE IS PRINTED BEFORE THE NUMBERS. A report taken without
    # half of the side indexes looks exactly like a report on a decompile
    # that never had those stages.
    _unreadable = unreadable_side_indexes(args.directory, _SIDE_INDEX_NAMES)
    # The key "" means "there is no directory" — the absence block below
    # already says this, and two voices about one fact are not needed
    # here.
    if _unreadable and "" not in _unreadable:
        print(f"🔴 БОКОВЫЕ ИНДЕКСЫ ЕСТЬ, НО НЕ ЧИТАЮТСЯ: {len(_unreadable)} — "
              f"их нули ниже НЕ означают «стадии не было»")
        for _name, _why in sorted(_unreadable.items()):
            print(f"   · {_name}: {_why}")
    _absent = absent_side_indexes(args.directory, _SIDE_INDEX_NAMES)
    if _absent:
        if "" in _absent:
            print(f"🔴 БОКОВЫЕ ИНДЕКСЫ НЕ ИСКАЛИСЬ: {_absent['']}")
        else:
            print(f"🔴 БОКОВЫХ ИНДЕКСОВ НЕТ: {len(_absent)} из "
                  f"{len(_SIDE_INDEX_NAMES)} — {', '.join(sorted(_absent))}")
            print("   их нули ниже означают «не читали», а не «в здании нет»")

    report = relift(args.directory)

    print(f"{report['doc_name']} (Revit {report['revit_version']})")
    # §18.1: the census line stands BEFORE the percentages — the
    # denominator is named before the numerator.
    print(f"  перепись:            {report['census_summary_ru']}")
    if report["census_present"]:
        # The WHOLE ``top`` is printed, not a slice of it: the remainder
        # is counted from the top-N boundary, and any shorter display
        # would drop rows into the gap between "shown" and "other".
        # Measurement: 5 shown rows at TOP_N=8 hid 193 elements that fell
        # into neither bucket.
        for row in report["unscanned_by_category"]["top"]:
            print(f"      {row['unscanned']:>8}  {row['category']}"
                  f"  ({row['reason']})")
        if report["unscanned_by_category"]["other_categories"]:
            print(f"      {report['unscanned_by_category']['other_elements']:>8}"
                  f"  прочие "
                  f"{report['unscanned_by_category']['other_categories']}"
                  " категорий")
        if not report["census_balanced"]:
            print(f"  ⚠ ТОЖДЕСТВО НЕ СХОДИТСЯ: "
                  f"{report['census_balance_errors']}")
    # §18.2: the receipts line stands between the census and the
    # percentages — "what wasn't looked at at all", "what was looked at
    # and not finished looking at", and only then the share.
    print(f"  квитанции срезов:    {report['side_cuts_summary_ru']}")
    if report["side_failures_by_stage"]:
        # A BREAKDOWN by stage is printed, not a single sum. While a sum
        # stood there, ``curtain 14343`` read as "curtain walls failed on
        # 14 thousand elements", even though there are 19 slices in it,
        # and 14,324 are "wall is not a curtain wall" answers, each of
        # which also has an index line of its own.
        cuts_by_stage = report.get("side_cuts_by_stage") or {}
        determined_by_stage = report.get("side_determinations_by_stage") or {}
        detail = ", ".join(
            f"{stage} {cuts_by_stage.get(stage, 0)}"
            f"+{determined_by_stage.get(stage, 0)}отв"
            for stage, _ in sorted(report["side_failures_by_stage"].items()))
        print(f"  квитанций в индексах: {report['side_failures_total']}"
              f"  (срезов+ответов: {detail})")
    print(f"  элементов в L0:      {report['elements']}")
    print(f"  поднято в опы:       {report['op_total']}  "
          f"({report['lifted_pct']}% от прочитанного"
          + (f", {report['document_pct']}% от документа)"
             if report["document_pct"] is not None
             else ", от документа — переписи нет)"))
    print(f"  осталось атомами:    {report['atom_total']}")
    if report["generator_children"]:
        print(f"  из них порождаемых:  {report['generator_children']}"
              f"  ⇒ честное покрытие {report['honest_pct']}%")
    print("\n  опы:")
    for op, count in report["ops"].items():
        print(f"    {count:>8}  {op}")
    if report["atoms"]:
        print("\n  атомы по причине:")
        for reason, count in report["atoms"].items():
            print(f"    {count:>8}  {reason}")
        print("\n  чаще всего:")
        for detail, count in list(report["atom_details"].items())[:8]:
            print(f"    {count:>8}  {detail}")

    if args.json is not None:
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nотчёт: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
