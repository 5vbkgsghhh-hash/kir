"""THE LIVE-WITNESS CORPUS — ONE DEFINITION OF "OP PROVEN" FOR THE
WHOLE TREE.

WHY THIS MODULE APPEARED ON 17.08.2026
---------------------------------------
The day before, `tool_doc` rendering learned to ask the corpus, so that
the `UNPROVEN` journal would stop lying to the model about what was
already built. The fix was right in intent and WRONG IN ITS MEASURE: it
treated a row with a nonzero `duration_ms` as proof, i.e.
**"the program reached Revit"**. The journal it was fixing distinguishes
these two facts in plain text, in its own comment:

    create_multi_segment_grid   4 lines · committed 4 · ok 0
    create_extrusion_roof       4 lines · committed 0 · ok 0

Re-measured against the tree's authority (`program_state`) on 17.08: of
65 ops that reached Revit, **four never committed even once** —
`create_extrusion_roof`, `create_face_wall`, `create_multistory_stairs`,
`create_slab_edge`. The journal carried an exact and useful reason for
all four ("the extrusion side is set by the normal Revit chose"), and
the rendering was TAKING that reason away from the model. This is
exactly the silently-wrong outcome the whole package is written against
— introduced by an honesty instrument.

The defect is named: a value is ASSERTED in one place
(`_live_proven_ops`) and READ in another (the unproven journal), and
nothing forced them to agree. It is not fixed by carefulness, but by
the definition becoming ONE and living where both consumers look.

THREE LEVELS, AND THEY MUST NOT BE CONFUSED
---------------------------------------------
1. **REACHED** (`reached`) — `duration_ms > 0`. Speaks about the
   CONNECTION to Revit and nothing more. Good for telling "the
   instrument did not exist" apart from "the instrument said zero", not
   good for removing a record from the journal.
2. **COMMITTED** (`program_state == "committed"`) — the transaction went
   through, or a read completed. THIS IS THE WORKING DEFINITION of "the
   op is built live", and it is exactly what the unproven journal reads.
3. **FULL CHAIN** (`ok is True`) — commit AND witness AND independent
   acceptance. Stronger than the second, but records must NOT be
   removed BY THIS ONE: `ok=false` with `execution=committed` is a
   legitimate state (the witness matched, independent acceptance came
   back `inconclusive`), and it means a built element.

AN INSTRUMENT REFUSAL IS A THIRD OUTCOME, NOT A ZERO
------------------------------------------------------
The corpus is machine-local and sits under mode 600, owned by the
service user. Without rights, opening it raises an exception, while
listing the directory gives an EMPTY list, not an error. That is why
`committed_ops()` returns an empty set EXACTLY AS A REFUSAL, and the
consumer must read the emptiness as "nothing to ask", not as "nothing
was proven". A silent zero here is the same lie, just pointed the other
way.
"""
from __future__ import annotations

import json
import os
from kir import env  # noqa: E402  (a dependency-free submodule — creates no import cycle)

#: The name of the environment variable by which the caller names a
#: DIFFERENT corpus. The prod corpus does not live in the dev tree, and
#: an instrument run without it will measure its own machine's
#: emptiness — silently and convincingly.
ENV_PATH = "KIR_WITNESS_PATH"

#: The default path is RELATIVE, because the corpus is written relative
#: to the service's working directory. An absolute literal has already
#: sat here once, and it led the instrument into someone else's tree.
DEFAULT_PATH = os.path.join("data", "telemetry", "kir_witness.jsonl")


def corpus_path() -> str:
    """The path to the corpus: the environment variable is STRONGER
    than the default."""
    return env.get(ENV_PATH) or DEFAULT_PATH


def ops_of(row: dict) -> set:
    """The row's operation names. A corpus row carries them in two
    forms — a bare name (old records) and a dict `{op, skel, id}` (new
    ones)."""
    out: set = set()
    for op in row.get("ops") or ():
        if isinstance(op, str):
            out.add(op)
        elif isinstance(op, dict) and op.get("op"):
            out.add(op["op"])
    return out


def reached(row: dict) -> bool:
    """The program REACHED Revit. Not to be confused with "was built" —
    see the header."""
    return (row.get("duration_ms") or 0) > 0


def program_state(row: dict) -> tuple[str, str]:
    """→ (program state, what proves it).

    🔴 THIS IS THE ONLY DEFINITION IN THE TREE. Before 17.08.2026 it
    lived in `tools/live_op_rates.py` and was unreachable from the
    package, so `tool_doc` set up its own, weaker one — and took four
    valid warnings away from the model. Moving it here is the fix:
    `live_op_rates` now imports from here.

    The closed v2 contract (`outcome`) is STRONGER than the `ok` flag,
    and this is not a stylistic choice: `ok=false` with
    `execution=committed` is a legitimate state (the witness matched,
    independent acceptance came back `inconclusive`), while `ok=false`
    with `execution=unconfirmed` is not-knowing, not a failure.
    Collapsing into `bool(ok)` confused both with a rollback."""
    outcome = row.get("outcome")
    if isinstance(outcome, dict) and outcome.get("execution"):
        execution = str(outcome["execution"])
        if execution in ("committed", "read_completed"):
            return "committed", f"outcome.execution={execution}"
        if execution == "unconfirmed":
            return "unconfirmed", "outcome.execution=unconfirmed"
        return "rolled_back", f"outcome.execution={execution}"
    if row.get("diag_code") == "KIR-X007":
        return "unconfirmed", "diag KIR-X007 (таймаут)"
    if row.get("ok"):
        return "committed", "ok=true"
    witness = row.get("witness")
    if isinstance(witness, dict) and witness.get("committed") is True:
        return "committed", "witness.committed=true"
    return "rolled_back", "ok=false"


def _rows(path: str):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:  # noqa: BLE001 — a broken row is not a verdict
                continue


#: A cache of the read corpus, keyed by (path, mtime, size).
#:
#: 🔴 MEASURED BEFORE SHIPPING, 17.08: `build_tool_description()` is
#: called from `serving.py:319` ON EVERY TURN, and reading the corpus
#: cost **52 ms** at a size of 3.5 MB. The corpus GROWS with every live
#: run — that is, the cost grows with n, and at 10 MB it is already
#: ~150 ms per turn. Our form 10: a cost invisible to any instrument
#: whose n equals three.
#:
#: THE KEY IS EXACTLY WHAT CHANGES THE ANSWER: path, mtime, size. Not
#: `last_access`: a timestamp written by the read itself would poison
#: the cache forever (this project has already paid for one of those —
#: the viewer silently stopped hitting the cache).
_CACHE: dict = {}


def tiers(path: str | None = None) -> dict:
    """Three sets of op names from a single pass over the corpus.

    → `{"reached": …, "committed": …, "full_chain": …, "rows": N}`, or
    `{}` — AN INSTRUMENT REFUSAL (no corpus / no rights). An empty dict
    and empty sets inside it are DIFFERENT answers, and the consumer
    must tell them apart.
    """
    path = path or corpus_path()
    try:
        stat = os.stat(path)
        key = (path, stat.st_mtime_ns, stat.st_size)
    except OSError:  # noqa: BLE001 — no corpus: nothing to ask, and this is a REFUSAL
        return {}
    got = _CACHE.get(key)
    if got is not None:
        return got

    reached_s: set = set()
    committed_s: set = set()
    full_s: set = set()
    count = 0
    try:
        for row in _rows(path):
            if not reached(row):
                continue
            count += 1
            names = ops_of(row)
            reached_s |= names
            state, _ = program_state(row)
            if state == "committed":
                committed_s |= names
            if row.get("ok") is True:
                full_s |= names
    except Exception:  # noqa: BLE001 — no corpus / no rights: nothing to ask
        return {}
    out = {"reached": frozenset(reached_s), "committed": frozenset(committed_s),
           "full_chain": frozenset(full_s), "rows": count, "path": path}
    # We hold ONE entry: there is one corpus per process, and the dict
    # has no reason to grow — otherwise the cache itself would become
    # the leak it was introduced to guard against.
    _CACHE.clear()
    _CACHE[key] = out
    return out


def committed_ops(path: str | None = None) -> frozenset:
    """Ops whose transaction went through live at least once (level 2).

    NOT for removing journal records — `proven_ops` is for that; why is
    explained there."""
    got = tiers(path)
    return got.get("committed") or frozenset()


def proven_ops(path: str | None = None) -> frozenset:
    """Ops with a FULL CHAIN, live (level 3), or EMPTY as an instrument
    refusal.

    🔴 THIS IS THE LEVEL BY WHICH RECORDS ARE REMOVED FROM THE UNPROVEN
    JOURNAL, AND THE CHOICE IS MEASURED, NOT PICKED OUT OF CAUTION.
    Level 2 (commit) separates 20 records from 13; the difference is
    SEVEN records, and all seven cast doubt on the WITNESS, not on
    whether it reached Revit:

        create_multi_segment_grid  "the transaction went through, the witness was not green"
        create_beam_system         "the number and spacing of beams is chosen by Revit"
        create_truss               "the truss shape is set by its family"
        create_wall_foundation     "the footing overhang was not measured"
        create_filled_region       "needs a run ON THE SECTION"
        create_duct_placeholder    "the placeholder carries no size bit"
        create_pipe_placeholder    same

    A passed transaction refutes none of these claims: it says "Revit
    did not refuse", while the record says "we did not check WHAT it
    built". Removing them on the strength of a commit would mean
    declaring something proven that nobody cross-checked — the
    silently-wrong outcome introduced by an honesty instrument.

    The cost asymmetry cements the same choice. An extra record costs
    the model turns; one removed on weak evidence costs a SILENTLY
    WRONG building. When in doubt, err on the side of an extra record.
    """
    got = tiers(path)
    return got.get("full_chain") or frozenset()
