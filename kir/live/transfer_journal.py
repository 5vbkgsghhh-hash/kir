"""THE TRANSFER-ATTEMPT JOURNAL — an action without evidence is indistinguishable from "never tried".

THE MEASUREMENT THAT BOUGHT THIS FILE (16.08.2026). Transferring a KIR scene
to Revit is the ONLY path by which the model's intent becomes an actual
model. On that day the owner pressed the button several times, got refusals,
and retold them in his own words — while `transfer.py` logged ONLY
exceptions (`:371`, `:551`, `:594`). Transfer events in the prod log over the
day: **zero**. An hour was spent reconstructing from indirect evidence what
should have been sitting there as one line.

This is the project's named class of bug in its most expensive spot: **an
action without evidence is indistinguishable from "never tried"**, and the
cardinal invariant demands durable evidence even where the answer is a
refusal.

WHY ITS OWN CORPUS, NOT `kir_rejections.jsonl`. That corpus is a contract
with a CLOSED `reject_code` enum and a consumer that ranks gaps in the
compiler's COVERAGE. A transfer refusal is of a different kind: it is not
about the compiler being unable to do something, it is about the door not
letting it through. Mixing the two has already been paid for once and is
documented in `coverage_feed`'s docstring: 662 legitimate refusals out of
1469 went into the statistics as defects. No reason to pay twice — this
corpus is its own and NAMED.

WHY TO DISK AND WITH fsync. On 16.08 it turned out three times over that
state living in a prod process's memory is unreachable by either
investigation or an instrument: the scene journal cannot be read from
outside, there is no `/admin` route to it. A record that does not survive a
restart is evidence that does not exist.

WHY FAIL-OPEN, AND WHY THAT DOES NOT WEAKEN ANYTHING. A journal failure has
no right to kill a transfer: this is telemetry OF THE ACTION, not terminal
evidence OF WHAT WAS BUILT — `acceptance_journal` is responsible for the
latter, and it is exactly the one that must refuse. But the record is
written BEFORE the decision is returned, so a missing line means "the
process died between the decision and the write", not "the person never
pressed the button".
"""
from __future__ import annotations

import logging
import os
from kir import env  # noqa: E402  (dependency-free submodule — creates no ring)
import pathlib
import time
from typing import Any, Mapping, Optional, Sequence

from kir.install_paths import install_data_path

logger = logging.getLogger(__name__)

SCHEMA = "kir-transfer-journal/1"

#: Path override. As with the neighboring feeds: env ⇒ THIS install's data
#: directory ⇒ None ("off"). There is deliberately no hardcoded absolute
#: literal here — it has already once led to writing into someone else's
#: install (see `coverage_feed._DEFAULT`).
PATH_ENV = "KIR_TRANSFER_JOURNAL_PATH"

#: The doors transfers arrive from. A CLOSED enumeration: if a third one
#: appears, it must name itself here rather than arrive as an empty string.
DOOR_FRAME = "frame"     # `authorize` — a floor's frame or a selection
DOOR_SCENE = "scene"     # `authorize_scene` — the "transfer to Revit" button
DOORS = (DOOR_FRAME, DOOR_SCENE)


def journal_path() -> Optional[str]:
    """Where to write, or None — "the journal is off".

    None here means "we are not in our own install", not "write somewhere".
    """
    path = env.get(PATH_ENV)
    if path:
        return path
    owned = install_data_path("telemetry", "kir_transfer.jsonl")
    return str(owned) if owned is not None else None


def _row(decision: Any, *, key: Sequence[str], door: str,
         elapsed_ms: int, error: str) -> dict[str, Any]:
    """One journal line.

    Fields are taken from the decision ITSELF (`Decision.to_dict`), rather
    than retyped by hand: a second handwritten copy of the field set would
    drift apart from the first at the very next `Decision` refinement, and it
    would drift SILENTLY.
    """
    body: Mapping[str, Any] = {}
    if decision is not None:
        try:
            body = decision.to_dict()
        except Exception:  # noqa: BLE001 — the journal does not judge the decision's shape
            body = {}
    device = str(key[0]) if len(key) > 0 else ""
    doc = str(key[1]) if len(key) > 1 else ""
    row: dict[str, Any] = {
        "schema": SCHEMA,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00",
        "door": door,
        "device_id": device,
        "doc_key": doc,
        "elapsed_ms": int(elapsed_ms),
        # THE OUTCOME IS NAMED BY THREE DISTINGUISHABLE VALUES, not two:
        # "accepted", "refused with a code", and "the instrument crashed".
        # The third must not be read as the second.
        "status": str(body.get("status") or ("error" if error else "unknown")),
        "refusal": body.get("refusal"),
        "refusal_ru": body.get("refusal_ru") or "",
        "programs": int(body.get("programs") or 0),
        "ops": int(body.get("ops") or 0),
        "selected": int(body.get("selected") or 0),
        "level": body.get("level") or "",
        "requested_digest": body.get("requested_digest") or "",
        "transfer_digest": body.get("transfer_digest") or "",
        "stale": bool(body.get("stale")),
        "diverged": list(body.get("diverged") or ()),
        "over_budget": list(body.get("over_budget") or ()),
        "preflight": list(body.get("preflight") or ()),
    }
    if error:
        row["error"] = error
    return row


def record(decision: Any, *, key: Sequence[str], door: str,
           elapsed_ms: int, error: str = "") -> bool:
    """Record the attempt. Returns True if the line landed on disk.

    The return value is not decoration: without it, "the journal is off" and
    "the journal crashed" are indistinguishable to a control, and that is
    exactly the defect this file was written for.
    """
    if door not in DOORS:
        # A door outside the closed enumeration is a CALLER error, and it
        # must not be met with silence: a line with an empty door is useless
        # for counting.
        logger.warning("transfer journal: дверь %r вне %s", door, DOORS)
    path = journal_path()
    if not path:
        return False
    try:
        # 🔴 A SHARED PRIMITIVE, NOT ONE OF OUR OWN (18.08.2026). What stood
        # here was the tree's third instance of "append the line, fsync the
        # file, fsync the directory". There were three copies
        # (`created_ledger._write_line`, this one, and the new program
        # store), and all three had to agree on durability — our own named
        # defect. Now there is one primitive (`journal_store.append_line`),
        # and the second copy stays in `kir/created_ledger.py` DELIBERATELY:
        # that package is published under Apache-2.0 and has no right to
        # import product code.
        #
        # Behavior here has not changed in any way: fail-open, a bool
        # return, the directory gets created. What changed is the new
        # file's mode — `0600` instead of `umask`, and that is a
        # strengthening: the line carries `device_id` and a document key.
        from kir.live.journal_store import append_line
        append_line(pathlib.Path(path),
                    _row(decision, key=key, door=door,
                         elapsed_ms=elapsed_ms, error=error))
        return True
    except Exception:  # noqa: BLE001 — fail-open: the journal does not drop the product
        logger.warning("transfer journal write failed (fail-open)", exc_info=True)
        return False


__all__ = ["record", "journal_path", "SCHEMA", "PATH_ENV",
           "DOOR_FRAME", "DOOR_SCENE", "DOORS"]
