"""BUILDING GRAPH STORAGE — `building_graph`'s only wire to the outside.

`building_graph.py` can do everything the graph can do: two node axes,
three edge modalities, the census law as a build precondition, a
bijection between address and L0. What it could NOT do — SURVIVE THE
PROCESS. Measured 19.08.2026 by grepping the module: no `open`, no
`json.dump`, no `write_text` — **not a single byte to disk**. The
graph was built in memory and died with the turn, and nobody built it
in prod: `graph_from_l0` was called ONLY from tests (checked by grep
across the whole tree), and `KUKAI_IR_BUILDING_GRAPH` was absent from
the live service.

🔴 THE SECOND HALF OF THE SAME GAP CLOSED ON 22.08.2026, AND IT LIVED
FOR THREE DAYS. A carrier appeared on 19.08 — but the carrier had NO
CALLER: measured 22.08 by grepping the tree, the single prod call of
`graph_from_l0` was in `tools/address_spine.py:172`, i.e. in a tool,
not in the pipeline. "Can survive the process" and "does survive" are
different facts, exactly like "written" and "wired in"; the day the
second one arrived is recorded below, in the boundaries.

The gap being closed is named briefly: **the building's state had no
carrier**. Without one there is no revision subscription, no pull
request, no external door — all three need "the state at moment N" to
exist as a value, not as a side effect of someone's process.

This module computes NOTHING new. `graph_from_l0` builds the graph,
`BuildingGraph.to_dict` prints the representation, `graph_from_dict`
verifies what was read — here there is only the path, the atomic
write, and transparency to gzip.

═══════════════════════════════════════════════════════════════════════════
WHY STORING NODES AND EDGES IS FINE, BUT CLASH EDGES ARE NOT — A MEASUREMENT, NOT TASTE
═══════════════════════════════════════════════════════════════════════════

The ratio of edges to nodes decides everything, and the two edge
kinds differ by an order of magnitude. Measured 19.08.2026 on this
tree:

    edge kind             building              nodes      edges  ratio
    stable (this one)     k2_ar_rd_v15         115 889     92 623   0.80
    stable (this one)     snowdon_plumb_v5      11 069      9 334   0.84
    stable (this one)     sob62_r23_v5           1 510      2 586   1.71
    CLASH FINDINGS         демо-v3               84 120    769 630   9.15

Clash edges on демо-v3 produced ONE 666 MB report at a peak RSS of
2.66 GB. The tower's graph, with THREE TIMES as many elements, is
50.1 MB at a peak of 894 MB. The difference is not in printing care,
but in the fact that a stable edge describes an ASSEMBLY (a door has
one host, an element has one level), while a clash edge describes a
PAIR, and there are quadratically many pairs.

Hence the shape, and it is held by the type system, not by
agreement: what is stored here are `building_graph.Relation` — ten
assembly relations, among which there is NO clash AT ALL. Clash
lives as a separate type in `graph_clash_query.py` and enters the
graph BY A SCOPED QUERY. A payload naming an unknown relation is
refused on read — this is pinned by a control, not merely promised
here.

═══════════════════════════════════════════════════════════════════════════
THE FILE NAME GOES AGAINST THE COMMON PATTERN, AND THIS IS NAMED
═══════════════════════════════════════════════════════════════════════════

A run's side indexes are called `<stage>.index.json`, geometry is
`geometry.bundle.json`. The graph is called `building_graph.json`,
and the difference is deliberate: a side index is the lifter's INPUT
(without it an element becomes an atom by construction), while the
graph is the OUTPUT, folding L0 and the side indexes into one state.
This package's canon has already paid for the opposite assumption: a
scanner looking for `<стадия>.index.json` declared zero for the
stage that writes a bundle — "a member breaking the naming pattern is
named differently FOR A REASON." This is that reason.

═══════════════════════════════════════════════════════════════════════════
BOUNDARIES THAT ARE NAMED, NOT HIDDEN
═══════════════════════════════════════════════════════════════════════════

* **THE ARTIFACT IS NOT SIGNED.** It sits next to the decompile and is
  protected by filesystem permissions, not cryptography. A
  substituted file reads as genuine — exactly the same boundary as
  `journal_store` ("a substituted delta is caught, where a
  substituted signature came from — no"). What is caught: the census.
  Corrupted content almost always trips `assert_balanced()`, because
  the node count and the row count stop matching;
* **TWO SCHEMA VERSIONS ARE READ, ONE IS WRITTEN.** `building-graph/2`
  is written — the form with a DERIVED observation fingerprint
  (`change_stamp` + `l0_sha256`). `building-graph/1` is also read: 76
  corpus decompiles live in it, and declaring them unreadable would
  mean losing the state of real buildings for the sake of a key that
  was never in them. Such an artifact honestly answers
  `fingerprint_status: absent`, and does NOT invent itself a date.
  Any third version is still a loud refusal, not an attempt to parse
  it;
* **THE FINGERPRINT IS COMPUTED FROM CONTENT, NOT FROM THE FILE'S
  BYTES.** The janitor compresses a cooled-down `L0.jsonl` into `.gz`;
  were we to hash the file, the building's identity would change from
  compression, an event unrelated to the building. So `l0_digest`
  reads through `open_snapshot`, and this NUMBER IS NOT EQUAL to
  `Capture.source_sha256`, which counts exactly the file's bytes. The
  two must not be checked against each other;
* **BUILT FROM RAW L0, NOT FROM `L0JSONLReader`.** This is what the
  `graph_from_l0` input requires ("from RAW L0: header + element
  rows"). The cost is named: the full container revalidation that the
  reader's `_records()` performs is NOT done here. The graph's census
  still balances independently — it counts what arrived;
* **WIRED INTO THE PIPELINE ON 22.08.2026, AND THE FLAG IS NOW ON BY
  DEFAULT.** The previous wording of this point said "not wired into
  the live pipeline… the flag awaits reconciliation with live Revit,"
  and that was true right up to the day the condition was met.
  `pipeline.run_decompile` calls `build_graph_for_run` +
  `write_graph` as a separate `building_graph` stage, after the
  journal and before `done`. The owner named the condition and it was
  checked: the graph assembled and the census balanced on **76 of 76
  corpus decompiles**, **0** refusals. A stage refusal does not bring
  the run down and does NOT stay silent — it lands in `state.errors`;
* **SOURCES SITTING NEARBY ARE READ ON THEIR OWN.**
  `build_graph_for_run` takes `link` records from the same L0 and
  `join.index.json` from the same directory if the caller stayed
  silent. The reason is not convenience: `graph_from_l0` without
  these inputs extinguishes WHOLE KINDS of edges (`hosted_in_link`,
  `joined_to`, `joined_at_end`), and a zero for them in the artifact
  on disk would freeze our blindness as a fact about the building. An
  explicit argument from the caller always outranks what was read.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from kir.decompile.building_graph import (
    GRAPH_ARTIFACT_SCHEMA,
    READABLE_GRAPH_SCHEMAS,
    BuildingGraph,
    GraphBuildError,
    ObservationFingerprint,
    graph_from_dict,
    graph_from_l0,
)
from kir.decompile.snapshot_io import (
    open_snapshot,
    snapshot_file_exists,
)

__all__ = [
    "GRAPH_ARTIFACT_NAME",
    "JOIN_INDEX_NAME",
    "l0_digest",
    "observation_fingerprint_for_run",
    "graph_path",
    "l0_path",
    "read_l0_raw",
    "read_l0_parts",
    "read_l0_parts_counted",
    "read_l0_parts_detailed",
    "L0Parts",
    "joins_on_disk",
    "build_graph_for_run",
    "write_graph",
    "load_graph",
]

#: The artifact's name in the run's directory. The difference from
#: `<stage>.index.json` is deliberate — the reasoning is in the module
#: header.
GRAPH_ARTIFACT_NAME = "building_graph.json"


def graph_path(run_dir: str | os.PathLike[str]) -> Path:
    return Path(run_dir) / GRAPH_ARTIFACT_NAME


def l0_path(run_dir: str | os.PathLike[str]) -> Path:
    return Path(run_dir) / "L0.jsonl"


def read_l0_raw(
    run_dir: str | os.PathLike[str],
) -> tuple[dict[str, Any], Iterator[Mapping[str, Any]]]:
    """The header and the ELEMENT ROWS of raw L0 — the `graph_from_l0` input.

    🔴 THE RECORD SHAPE IS A TRAP WRITTEN INTO THE CANON: an L0 row is
    `{"record": "element", "element": {...}}`, not the element itself.
    A reader that takes the whole record gets a dict with no
    `element_id` and zero nodes for a complete building.

    Goes through `open_snapshot`, so a cooled-down run compressed by
    the janitor (`L0.jsonl` -> `L0.jsonl.gz`) is read without a single
    change on the caller's side. A direct `open()` on such a run
    returns "file not found" — i.e. OUR blindness disguised as a fact
    about the corpus.
    """
    header, rows, _links = read_l0_parts(run_dir)
    return header, iter(rows)


def read_l0_parts(
    run_dir: str | os.PathLike[str],
) -> tuple[dict[str, Any], list[Mapping[str, Any]], list[str]]:
    """The header, the element rows, AND THE ADDRESSES OF `link` RECORDS
    of one decompile.

    🔴 THE THIRD PART WAS READ FROM THE SAME FILE AND THROWN AWAY.
    `read_l0_raw` took `document` and `element` and SILENTLY skipped
    `link`, and `graph_from_l0` without `link_ids` extinguishes an
    entire edge kind (`HOSTED_IN_LINK`) and records it in
    `sources_absent` as "no source was supplied." Yet the source was
    lying in that very line of that very file: measured 22.08.2026 —
    MNVNK has **5 `link` records** (K1 129 365 elements, K4 75 940, K2
    55 381, K5 60 616, plus the structural discipline), and the reader
    was already holding all five in its hands.
    """
    path = l0_path(run_dir)
    if not snapshot_file_exists(path):
        raise GraphBuildError(
            f"разбора нет: ни {path}, ни его сжатой пары — "
            "это факт о КОРПУСЕ, а не о здании")

    parts = read_l0_parts_detailed(run_dir)
    return parts.header, parts.rows, parts.links


def read_l0_parts_counted(
    run_dir: str | os.PathLike[str],
) -> tuple[dict[str, Any], list[Mapping[str, Any]], list[str], int]:
    """The same thing PLUS the count of rows nothing could read (F-057).

    Left as a four-part shape: it has callers that unpack it exactly
    that way, and lengthening the tuple would break them SILENTLY. The
    fifth and sixth parts live in :class:`L0Parts` — a shape that
    grows without breaking anything.
    """

    parts = read_l0_parts_detailed(run_dir)
    return parts.header, parts.rows, parts.links, parts.unreadable


@dataclass(frozen=True, slots=True)
class L0Parts:
    """The parsed snapshot AND THE HONESTY OF ITS READING, in one shape.

    🔴 A SHAPE, NOT A TUPLE, AND THIS IS PAID FOR BY WORKING PRACTICE.
    Every new honesty about the reading is one more part of the answer,
    and lengthening a tuple means breaking callers silently. A
    dataclass grows without breaking anything.
    """

    header: dict[str, Any]
    rows: list[Mapping[str, Any]]
    links: list[str]
    #: Rows nothing can read: not parseable as JSON, or not objects.
    unreadable: int
    #: The stream is CLOSED by the `stream_complete` footer — extraction
    #: ran to completion.
    committed: bool
    #: How many `link` records the footer ITSELF declared. `None` means
    #: there is no footer.
    footer_link_count: int | None

    @property
    def whole(self) -> bool:
        """Everything was read, and the stream itself confirms it.

        Three conditions, and none follows from the other two: the
        stream is closed by the footer · not a single row was lost ·
        the number of `link` records the footer declared MATCHED what
        was read. The last one is a second, independent witness:
        without it, "zero links" would rest on our count alone.
        """

        return (self.committed and self.unreadable == 0
                and (self.footer_link_count is None
                     or self.footer_link_count == len(self.links)))


def read_l0_parts_detailed(run_dir: str | os.PathLike[str]) -> L0Parts:
    """The header, the rows, the `link` addresses, AND THE HONESTY OF
    THE READING — in one pass.

    The argument about unreadable rows is in :meth:`L0Parts.unreadable`
    and in `NodeRefusal.ROW_UNREADABLE` (F-057). The argument about the
    footer is in :meth:`L0Parts.whole` and its sole consumer,
    :func:`build_graph_for_run` (F-056): "zero links" is only entitled
    to be said about a snapshot READ IN FULL.
    """

    path = l0_path(run_dir)
    if not snapshot_file_exists(path):
        raise GraphBuildError(
            f"разбора нет: ни {path}, ни его сжатой пары — "
            "это факт о КОРПУСЕ, а не о здании")

    header: dict[str, Any] = {}
    rows: list[Mapping[str, Any]] = []
    links: list[str] = []
    unreadable = 0
    committed = False
    footer_link_count: int | None = None
    with open_snapshot(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                # 🔴 THE FILE EXISTS, BUT NOTHING CAN READ IT — THIS IS A
                # REFUSAL, NOT A MISS (F-057). The row was in the
                # snapshot, so the census must see it; the census law
                # holds the balance, not input completeness, and it
                # cannot protect a row that never reached it.
                unreadable += 1
                continue
            if not isinstance(record, Mapping):
                unreadable += 1
                continue
            if not header and isinstance(record.get("document"), Mapping):
                header = dict(record["document"])
            element = record.get("element")
            if isinstance(element, Mapping):
                rows.append(element)
                continue
            link = record.get("link")
            if isinstance(link, Mapping):
                link_id = link.get("element_id")
                if isinstance(link_id, str) and link_id:
                    links.append(link_id)
                continue
            if record.get("record") == "footer":
                committed = record.get("stream_complete") is True
                declared = record.get("link_count")
                if isinstance(declared, int) and not isinstance(declared, bool):
                    footer_link_count = declared
    return L0Parts(header=header, rows=rows, links=links,
                   unreadable=unreadable, committed=committed,
                   footer_link_count=footer_link_count)


#: The join side index. One name for the whole package, and now the
#: ONLY one: 🔴 the previous second literal lived in
#: `graph_clash_query._join_index_on_disk`, and that function was
#: REMOVED by the 31.08.2026 wave — the query now goes through the
#: canonical graph, and the index is supplied by `build_graph_for_run`
#: below. The caveat "that module belongs to another wave and was not
#: touched" outlived the wave itself and became a GHOST: the muteness
#: ledger kept a record under a name that no longer exists. Caught by
#: its guard `test_the_ledger_holds_no_ghosts`, not by eye.
JOIN_INDEX_NAME = "join.index.json"


def joins_on_disk(run_dir: str | os.PathLike[str]) -> dict[str, Any] | None:
    """The run's join map, or `None` — THERE IS NO INDEX.

    🔴 READ BY THE PRODUCER, NOT BY HAND. `graph_from_l0` expects the
    INTERNAL map, while the file carries `{schema_version, join_index,
    failures}`. Decompile of 20.08.2026: feeding the whole file added
    not a single edge, and it looked like "no joints in the building."
    `JoinExtraction.from_json` will also LOUDLY refuse on a foreign
    schema instead of a quiet zero.
    """
    from kir.decompile.join_extract import JoinExtraction

    path = Path(run_dir) / JOIN_INDEX_NAME
    if not snapshot_file_exists(path):
        return None
    # `touch=False`: the instrument does not date what it measures —
    # the `.last_access` mark is left for the janitor to decide what
    # has cooled.
    with open_snapshot(path, "rt", encoding="utf-8", touch=False) as handle:
        return JoinExtraction.from_json(handle.read()).join_index


#: How many bytes the streaming digest reads at a time. A snapshot can
#: run to hundreds of megabytes, and it need not fit into memory whole.
_DIGEST_BLOCK = 1 << 20


def l0_digest(run_dir: str | os.PathLike[str]) -> str:
    """sha256 of the snapshot's CONTENT, not of the file's bytes on disk.

    🔴 THE DIFFERENCE DECIDES EVERYTHING, AND IT IS NOT A MATTER OF
    TASTE. Read through `open_snapshot`, i.e. a cooled-down run
    compressed by the janitor (`L0.jsonl` -> `L0.jsonl.gz`) gives THE
    SAME NUMBER as a hot one. Were we to hash the file's bytes, the
    building's fingerprint would change from COMPRESSION, an event
    unrelated to the building; a diff report would declare "an
    observation from a different revision" where nothing had changed
    at all.

    🔴 THIS IS THE SECOND CARRIER OF ONE LAW, AND IT IS NAMED. The
    algorithm belongs to `snapshot_io.digest_bytes` ("one place, so the
    algorithm does not drift apart"); here it is repeated AS A STREAM
    for memory's sake, and the equality of the two carriers is backed
    by a control, not a promise.
    """
    path = l0_path(run_dir)
    if not snapshot_file_exists(path):
        raise GraphBuildError(
            f"разбора нет: ни {path}, ни его сжатой пары — "
            "отпечатку наблюдения не из чего взяться")
    digest = hashlib.sha256()
    with open_snapshot(path, "rb") as handle:
        for block in iter(lambda: handle.read(_DIGEST_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def observation_fingerprint_for_run(
    run_dir: str | os.PathLike[str],
    header: Mapping[str, Any] | None = None,
) -> ObservationFingerprint | None:
    """The fingerprint of ONE run, or `None` — the snapshot is undated.

    `None` means exactly "the L0 header has no `change_stamp`," and
    nothing more. Substituting the directory name, `doc_name`, or the
    file's date here would pass OUR guess off as the observation date
    — the same class of defect as the `lineage` taken from the
    directory name, which this package has already paid for.
    """
    if header is None:
        header = read_l0_parts_detailed(run_dir).header
    stamp = header.get("change_stamp")
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    return ObservationFingerprint(change_stamp=stamp, l0_sha256=l0_digest(run_dir))


def build_graph_for_run(
    run_dir: str | os.PathLike[str],
    *,
    read_side_indexes: bool = True,
    **kwargs: Any,
) -> BuildingGraph:
    """The graph of ONE saved run. Neither Revit, nor the network, nor
    the recording.

    `read_side_indexes` — whether to read what is ALREADY LYING NEARBY
    (the `link` records of L0 itself, `join.index.json`). The default
    is ON, and this is not a convenience: a source lying on disk two
    steps away and left unread produces a zero in the artifact,
    indistinguishable from a fact about the building. An explicit
    caller argument always wins — what was read is substituted ONLY
    where the caller stayed silent.
    """
    parts = read_l0_parts_detailed(run_dir)
    if read_side_indexes:
        if "link_ids" not in kwargs:
            # 🔴 AN EMPTY LIST IS SUPPLIED ONLY FROM A SNAPSHOT READ IN
            # FULL (F-056). After the sentinel fix, an empty `link_ids`
            # is a SUPPLIED source, i.e. "there are no links in the
            # building," a fact about the BUILDING. Saying so about a
            # broken-off read would mean trading an honest refusal for
            # a FALSE FACT — i.e. swapping one wrong statement for
            # another, exactly what needed to be avoided.
            #
            # A non-empty list is always supplied: a `link` record
            # that was read is read regardless of whether the stream
            # was read to the end.
            #
            # MEASURED 30.08.2026 ON THE LIVE CORPUS (81 decompiles
            # with L0, read-only): 16 decompiles answer with zero
            # `link` records, and ALL 16 were read IN FULL
            # (`stream_complete` footer, the declared `link_count: 0`
            # matched, 0 unreadable rows). There are four broken-off
            # snapshots, and ALL FOUR have `link` records. So today the
            # two sets DO NOT OVERLAP, and the guard here is not for
            # today's corpus, but so they never overlap tomorrow.
            if parts.links or parts.whole:
                kwargs["link_ids"] = parts.links
        if kwargs.get("joins") is None:
            kwargs["joins"] = joins_on_disk(run_dir)
    # Unreadable rows travel as a NUMBER into the graph's census:
    # otherwise a corrupted snapshot yields a smaller building with a
    # balanced census (F-057).
    kwargs.setdefault("unreadable_rows", parts.unreadable)
    # 🔴 THE FINGERPRINT IS DERIVED HERE, NOT TAKEN ON FAITH. An
    # explicit caller argument wins — by the same law as `link_ids`
    # and `joins` — but the default is no longer "no fingerprint": the
    # snapshot's path is in our hands, and staying silent about the
    # observation date while holding it would force the consumer to
    # DECLARE what we could have MEASURED.
    if "observation" not in kwargs:
        kwargs["observation"] = observation_fingerprint_for_run(
            run_dir, parts.header)
    return graph_from_l0(parts.header, iter(parts.rows), **kwargs)


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Atomically and with fsync — the same technique as the building's
    journal.

    Half an artifact on disk is indistinguishable from a whole one by
    file name, and it reads as corrupted. `os.replace` makes the
    file's appearance indivisible: it is either the old one or the
    new one, there is no third state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False,
        prefix=path.name + ".", suffix=".tmp")
    try:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


def write_graph(run_dir: str | os.PathLike[str], graph: BuildingGraph) -> Path:
    """Put the graph next to the decompile. Returns the path written."""
    if not isinstance(graph, BuildingGraph):
        raise GraphBuildError("write_graph принимает BuildingGraph")
    path = graph_path(run_dir)
    _atomic_write_json(path, graph.to_dict())
    return path


def load_graph(run_dir: str | os.PathLike[str]) -> BuildingGraph | None:
    """The run's graph, or `None` — THERE IS NO ARTIFACT.

    🔴 `None` MEANS EXACTLY "the file does not exist," and nothing
    more. A corrupted file, a file of a foreign schema version, and a
    file with an unbalanced census all yield a REFUSAL, not `None`:
    otherwise "we didn't build it" and "we read a lie" would arrive as
    the same value, and that is exactly the class of defect this
    entire package is written against.
    """
    path = graph_path(run_dir)
    if not snapshot_file_exists(path):
        return None
    with open_snapshot(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise GraphBuildError(
            f"{path}: артефакт графа обязан быть объектом JSON")
    if payload.get("schema") not in READABLE_GRAPH_SCHEMAS:
        raise GraphBuildError(
            f"{path}: версия схемы {payload.get('schema')!r}, "
            f"читатель знает {GRAPH_ARTIFACT_SCHEMA!r}")
    return graph_from_dict(payload)
