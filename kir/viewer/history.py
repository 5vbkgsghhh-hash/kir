"""BUILDING HISTORY: REVISIONS ALREADY RECORDED AND SHOWN TO NO ONE.

WHAT IS NOT REBUILT HERE, AND THIS IS THE FILE'S MAIN PROPERTY:

    the building journal   `decompile/journal.py` writes the chain since
                           09.08, format `kir-building-log/1`, events
                           chained by hash
    revision diff          `decompile/merkle_report.diff_report` — a
                           ready-made report
    tree reading            `viewer/pull_request._tree` — knows about
                           compression and refuses with a LIST of
                           neighbors, not with emptiness

There isn't a single computation of its own here: the module serializes
what has already been computed. A second reader of `tree.json` alongside
the first would drift from it on the first edit — that's why the loader
is IMPORTED, not rewritten.

🔴 WHY THIS APPEARED ON 28.08.2026. The canon calls `merkle · rebuild ·
journal · merge3` «системой контроля версий для зданий» and measures it:
replay is EXACT (18/18, 5/5, 3/3, 2/2 across four chains), the delta is
×6.05 smaller than a full rebuild. A measurement of the viewer client the
same day: the words `merkle`, `rebuild`, `history`, `revision` appear in
it **zero** times. The version system existed, and a person who opened a
building could not ask it anything.

WHAT IS ON DISK (measurement 28.08, live corpus): three chains in
`_journals/`, files of 0.3–10.9 MB. The weight comes from the fact that
an event carries STATE (a multiset of canonical ops), not just its hash.
That's why the light part (the revision list) is obtained with a cache
keyed on (path, mtime, size): parsing ten megabytes on every click is a
price that should not exist on screen.

WHAT THIS MODULE DOES NOT DO:

* It does NOT judge and does NOT build. Showing the diff between two
  revisions is not the same as offering a transition between them; the
  transition lives in `viewer/pull_request.py` and consults a guard
  (`merge_guard`) whose default policy is REFUSAL;
* It does NOT address elements. `merkle` is built as "pure shape, zero
  identity": the diff says "a subtree of this shape appeared," not "this
  particular wall appeared." Addressability is DELIBERATELY stripped —
  the offline T-APPLY proof rests on that — and substituting it here with
  a guess is not allowed;
* It does NOT hand back emptiness in place of a refusal. No journals, no
  tree, couldn't parse — that is a NAMED refusal (`HistoryUnavailable`):
  an empty feed reads as "there were no edits," and that is the worst of
  the available untruths.
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("HISTORY_SCHEMA", "DIFF_SCHEMA", "JOURNAL_DIR", "HistoryUnavailable",
           "chains", "chain_for_run", "diff_revisions")

HISTORY_SCHEMA = "kir-building-history/1"
DIFF_SCHEMA = "kir-building-history-diff/1"

#: Where the journals sit alongside the parses. The directory name is
#: part of the storage format (`journal_store`), not our own convention.
JOURNAL_DIR = "_journals"


class HistoryUnavailable(Exception):
    """History could not be assembled, and the reason is in the text."""


#: (path, mtime_ns, size) -> the light part of the journal. The key
#: carries mtime AND size: the journal is APPENDED TO, and a single
#: mtime at second granularity would miss two writes within the same
#: second.
#:
#: 🔴 SECOND GRANULARITY IS GONE, AND THIS IS NOT DECORATION (F-269, a
#: second instance of the same class, 30.08.2026). The argument above
#: NAMED the danger and left it resting on size: rewriting the journal TO
#: THE SAME SIZE within a second (an in-place line edit, not an append)
#: slipped past the key. `st_mtime_ns` removes exactly that half and
#: costs nothing: a corpus-wide measurement — 1 328 input files out of
#: 1 328 carry a non-zero fractional part of mtime.
_LIGHT: dict[tuple[str, int, int], dict[str, Any]] = {}


def _light(path: pathlib.Path,
           почему: dict[str, str] | None = None) -> dict[str, Any] | None:
    """The journal's header without events. `None` — and the REASON goes
    into `почему`.

    🔴 THE FIRST REVISION SWALLOWED THE REASON, AND THIS WAS CAUGHT ON THE
    VERY FIRST RUN. Journals sit as `-rw-------` owned by the service
    user; an instrument run by a different user got a `PermissionError`,
    returned `None` — and the overall refusal said "files exist, but not
    one of them carries a `revisions` field." That is, it named the WRONG
    reason: a reader would go off fixing the journal format instead of
    permissions. A refusal that names the wrong reason is more costly
    than none at all — it sends people to work in the wrong place.
    """
    почему = почему if почему is not None else {}
    try:
        stat = path.stat()
    except OSError as exc:
        почему[path.name] = f"{type(exc).__name__}: {exc.strerror or exc}"
        return None
    key = (str(path), stat.st_mtime_ns, int(stat.st_size))
    hit = _LIGHT.get(key)
    if hit is not None:
        return hit
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        почему[path.name] = (f"не прочитан: {type(exc).__name__}: "
                             f"{exc.strerror or exc}")
        return None
    except ValueError as exc:
        почему[path.name] = f"не разобрался как JSON: {exc}"
        return None
    if not isinstance(raw, dict) or "revisions" not in raw:
        почему[path.name] = "нет поля `revisions` — это не журнал здания"
        return None
    revisions = []
    for row in raw.get("revisions") or ():
        if not isinstance(row, dict):
            continue
        out_dir = str(row.get("out_dir") or "")
        revisions.append({
            "revision": row.get("revision"),
            "doc_stamp": row.get("doc_stamp") or "",
            # THE PARSE NAME, NOT THE PATH. The path is recorded as
            # RELATIVE and was resolved against the service's working
            # directory; dragging it onto the screen would mean showing a
            # person the layout of someone else's machine.
            "run": pathlib.PurePosixPath(out_dir).name if out_dir else "",
            "revit_version": row.get("revit_version") or "",
            "leaves": row.get("leaves"),
            "recorded_at": row.get("recorded_at") or "",
            "event_hash": row.get("event_hash") or "",
        })
    light = {
        "key": raw.get("key") or path.stem,
        "doc_name": raw.get("doc_name") or "",
        "journal_version": raw.get("journal_version") or "",
        "revisions": revisions,
        "bytes": int(stat.st_size),
    }
    _LIGHT.clear() if len(_LIGHT) > 32 else None
    _LIGHT[key] = light
    return light


def chains(root: pathlib.Path) -> list[dict[str, Any]]:
    """All revision chains of this installation, the freshest revision
    first in the feed."""
    folder = pathlib.Path(root) / JOURNAL_DIR
    if not folder.is_dir():
        raise HistoryUnavailable(
            f"журналов зданий нет: каталог {folder} не существует. История "
            "пишется при разборе, когда включён журнал; пустая лента и "
            "отсутствующий каталог — разные факты")
    out: list[dict[str, Any]] = []
    почему: dict[str, str] = {}
    for path in sorted(folder.glob("*.json")):
        light = _light(path, почему)
        if light is None:
            continue
        rows = sorted(light["revisions"],
                      key=lambda r: (r.get("recorded_at") or "",
                                     r.get("revision") or 0),
                      reverse=True)
        out.append({**light, "revisions": rows, "count": len(rows)})
    if not out:
        # THE REASON IS PER FILE, NOT ONE FOR ALL: "no permissions" and
        # "wrong format" are fixed by different people, and a shared
        # phrase would send both of them to the wrong place.
        разбор = "; ".join(f"{имя}: {текст}" for имя, текст in sorted(почему.items()))
        raise HistoryUnavailable(
            f"в {folder} не прочитан ни один журнал здания. "
            + (разбор or "каталог пуст"))
    # A file that failed to read does NOT DISAPPEAR from the response: a
    # feed that silently lost a building reads as "it never existed."
    if почему:
        out.append({"key": "", "doc_name": "", "revisions": [], "count": 0,
                    "unreadable": почему})
    return out


def chain_for_run(root: pathlib.Path, run: str) -> dict[str, Any] | None:
    """The chain that THIS parse participates in. `None` — the parse is
    outside history.

    `None` is legitimate here and means exactly itself: the parse was
    taken before the journal was turned on, or the building was parsed
    only once. Turning this into a refusal would mean accusing a
    perfectly sound parse.
    """
    for chain in chains(root):
        if any(r.get("run") == run for r in chain["revisions"]):
            return chain
    return None


def diff_revisions(root: pathlib.Path, a: str, b: str) -> dict[str, Any]:
    """The diff between two revisions of ONE building: what appeared,
    disappeared, changed.

    Computed by `merkle_report.diff_report`; here there is only addresses
    and a wrapper. Trees are read by `pull_request._tree` — the ONLY
    reader of `tree.json` in this package: a second one would drift from
    the first over compression, as has already happened.
    """
    from kir.viewer.pull_request import ProposalUnavailable, _tree

    try:
        tree_a, tree_b = _tree(pathlib.Path(root), a), _tree(pathlib.Path(root), b)
    except ProposalUnavailable as exc:
        raise HistoryUnavailable(str(exc)) from None

    from kir.decompile.merkle_report import diff_report

    report = diff_report(tree_a, tree_b, label_a=a, label_b=b)
    return {"schema": DIFF_SCHEMA, "a": a, "b": b, "diff": report}
