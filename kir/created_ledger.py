"""A durable trace of what was CREATED: the id of every element,
regardless of `ok`.

WHY. On 13.08.2026 a live run produced two elements that remained in the
operator's model without a single trace of their numbers. The outcome was
`execution: committed` with `ok: false` (`KIR-A006`/`KIR-A007`: the write
went through, independent acceptance diverged or did not complete) — that
is, Revit built, and the program declared failure. What followed was a
search for the ids across THREE server records:

    the witness (`kir_witness.jsonl`)  the verdict `op_outcomes: {"MS1": "created"}`
    the acceptance journal             digests, `run_id`, `sequence`
    refusals (`kir_rejections.jsonl`)  codes, fields, candidates

**The number is in none of them.** The receipt lived exclusively in the
body of the HTTP response, and parsing that body was the only place the
ids existed at all. That time, a MANUAL reading of the model saved the
day; on a fleet of thirteen devices nobody reads manually, and something
created-and-named-nowhere is trash left in SOMEONE ELSE'S model, without a
trace.

WHAT THIS MODULE DOES AND DOES NOT DO. It writes a line for EVERY turn
that reached execution, and does so IMMEDIATELY after the bridge's
response — before acceptance runs, because it is precisely acceptance
that declares failure under those two codes. It does NOT clean anything up
and does not decide what to do with the trace: cleanup based on such a
list is a separate decision carrying a separate risk (`created_ledger`
reports that the element exists; whether it still belongs to us is a
question for the document). First, the trace must stop being lost.

WHAT IS READ IS THE PAYLOAD, NOT THE PROGRAM. The difference is decisive
and is itself the control: a rolled-back program must leave a line with an
EMPTY list, not with the list of declared ops. A list of what we INTENDED
to create would, on a rollback, coincide in appearance with the list of
what was actually created, and would turn the registry into a generator of
false traces — our own named class: a quantity declared in one place is
read from another, and nothing forces them to agree.

A BOUNDARY THAT MUST NOT BE PASSED OVER IN SILENCE. The registry knows
exactly what REACHED the server. If the bridge broke off before the
response, the outcome is typed `unconfirmed`, and the numbers do not exist
anywhere except in Revit itself — this module does not close that case and
does not pretend to close it. It closes a different one, and a measurably
frequent one: the response arrived, the elements were created, and the
turn declared failure.

A FAILURE OF THE REGISTRY ITSELF HAS NO RIGHT TO CANCEL THE RECORD. A
successful write to Revit does not become unsuccessful because we failed
to record a line about it. But silence is not allowed either: a failure is
written to the neighboring file `*.errors.jsonl` and to the ERROR-level
log. There is no silent degradation here — there is a named place to look.
"""

from __future__ import annotations

import json
import logging
import os
from kir import env  # noqa: E402  (a submodule with no dependencies — creates no cycle)
import pathlib
from typing import Any, Mapping, Sequence

from kir.install_paths import install_data_path

logger = logging.getLogger(__name__)

LEDGER_DIR_ENV = "KIR_CREATED_LEDGER_DIR"
SCHEMA_VERSION = "kir-created-ledger/1"

def created_keys() -> tuple[str, ...]:
    """The result-row keys carrying EXACTLY what was created. COMPLETE BY
    CONSTRUCTION.

    🔴 USED TO BE A HANDWRITTEN TUPLE AND LOST FOUR OPERATIONS (measured
    15.08.2026). It held `("id", "ids", "created_ids")`, declared "closed
    and admittedly incomplete". A measurement against the registry showed
    two things at once:

    * `ids` and `created_ids` are declared by NOT A SINGLE op — two dead
      lines, guessed from the look of the name rather than asked of the
      authority;
    * `segment_ids` is the identity field of FOUR creating ops
      (`create_pipe_system`, `create_room_separator`, `route_duct_system`,
      `route_pipe_system`), and it was not in the tuple. **Their created
      elements left no trace in the registry at all** — exactly the loss
      this module was written to forbid. In the live corpus (1913 lines
      as of 15.08) there are **28** such turns.

    Now the keys are DERIVED from the registry
    (`address.created_identity_fields`): the `ResultSpec.identity_field`
    fields of every op with `EffectKind.CREATE`. A new creating op lands
    here on its own; it cannot be forgotten, because there is no longer a
    list to forget it from. The list's kind changed from "closed but
    incomplete" to **complete by construction**, and these are different
    things: there an empty string meant "we don't know", here it means
    "the registry has no such field".
    """

    from kir.address import created_identity_fields

    return created_identity_fields()


#: The fields by which a turn REPORTS THE REPLACEMENT of an element, and
#: the field carrying the replacement's id. A CLOSED LIST, closed by the
#: emission, not by taste: today replacement is declared by exactly three
#: places — `authoring._emit_change_type` (`new_element_created`+`id`),
#: the curtain wall cell (`panel_replaced`+`returned_panel_id`), and the
#: transaction unit (`replacement_element_id`).
REPLACEMENT_BIRTH_FIELDS: tuple[tuple[str, str], ...] = (
    ("new_element_created", "id"),
    ("panel_replaced", "returned_panel_id"),
)

#: A field that by itself carries the replacement's id: a non-empty value
#: is itself the fact.
REPLACEMENT_ID_FIELDS: tuple[str, ...] = ("replacement_element_id",)


def replacement_born_ids(row: Mapping[str, Any]) -> list[str]:
    """ids of elements BORN FROM A REPLACEMENT during a NON-creating op.

    🔴 WHY THIS EXISTS AT ALL (measured 07.09.2026). `Element.ChangeTypeId`
    is documented by the assemblies: "In rare cases, applying a change in
    type will result in a new element being created... In this situation
    the new element id is returned. Also, this element becomes invalid."
    That is, `change_type` is `EffectKind.MUTATE`, yet in a rare case it
    LEAVES A NEW ELEMENT IN SOMEONE ELSE'S MODEL. The registry, meanwhile,
    has dropped all MUTATE entirely since 29.08 (finding F-297, and it is
    correct: `set_param` leaves nothing behind). The intersection of these
    two truths is exactly the loss the registry was written to forbid: the
    element exists, and there is no trace of its number anywhere.

    WHY NOT "BRING BACK ALL MUTATE". Because F-297 would come back too:
    `set_param` would again record someone else's existing element into
    the turn's ownership. What is asked here is not the op's kind, but the
    fact of replacement AS DECLARED BY THE TURN ITSELF — a field the
    emission writes and which, on an ordinary success, equals
    `false`/`null`. A silent line still means "left nothing behind".

    WHAT IS READ IS THE BRIDGE'S RESPONSE, NOT THE PROGRAM — by the same
    law as everything else in this module: a rolled-back turn returns a
    line without the flag and stays empty.
    """

    ids: list[str] = []
    for flag, field_name in REPLACEMENT_BIRTH_FIELDS:
        if row.get(flag) is not True:
            continue
        value = row.get(field_name)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            ids.append(str(value))
    for field_name in REPLACEMENT_ID_FIELDS:
        value = row.get(field_name)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            ids.append(str(value))
    return list(dict.fromkeys(ids))


def not_created_keys() -> dict[str, str]:
    """Identity fields that do NOT carry a created element — each with a
    reason.

    `deleted_id` is excluded not by oversight: a deleted element is
    already gone from the model, there is nothing to track. `moved_ids` is
    excluded for the same reason from the other side: the element existed
    before the turn. The registry answers "what did I leave behind", not
    "what did I touch". Previously only the first was named, the second
    fell out silently.
    """

    from kir.address import identity_field_reasons

    return identity_field_reasons()


def ledger_path() -> pathlib.Path | None:
    """The registry file, or ``None`` — an install with no writable root.

    An explicitly empty value of the variable DISABLES the registry: a
    deployment must be able to say this on purpose, rather than through
    the absence of a directory.
    """

    named = env.get(LEDGER_DIR_ENV)
    if named is not None:
        configured = named.strip()
        if not configured:
            return None
        return pathlib.Path(configured) / "kir_created_ids.jsonl"
    root = install_data_path("telemetry")
    if root is None:
        return None
    return root / "kir_created_ids.jsonl"


def extract_created(
    payload: Any,
    *,
    op_kinds: Mapping[str, str] | None = None,
) -> dict[str, list[str]]:
    """The id of what was created, by op identifier, FROM THE BRIDGE'S
    RESPONSE.

    An empty dict is a legitimate, meaningful answer: it means "the turn
    reached execution and created nothing", which on a rollback is the
    truth. That is exactly why the line is always written, not only when
    the list is non-empty: "no line" and "a line with an empty list" are
    different facts, and the first is indistinguishable from "the registry
    was not working".

    🔴 `op_kinds` — A MAP "op id -> OP NAME", AND THIS IS THE ONLY THING
    TAKEN FROM THE PROGRAM (29.08.2026, audit finding F-297).

    The scanner used to take the UNION of identity field names across all
    creating ops, and did not ask what KIND ITS OWN operation was. The
    field `id` is a legitimate identity field for 59 creating ops AND for
    `change_type`, which is MUTATE: the field belongs to BOTH sets.
    Because of this, `set_param`, `change_type`, `set_curtain_panel` —
    operations on an ALREADY EXISTING element — were being recorded into
    the turn's ownership, even though the registry declares itself the
    answer to "what did I LEAVE BEHIND".

    The answer had ALREADY BEEN WRITTEN in a neighboring function, for the
    other half of the question: `address.identity_field_reasons` found
    this intersection and subtracted it while building the PARTITION —
    while the scanner kept working off the union.

    🔴 IDENTIFIERS STILL COME ONLY FROM THE BRIDGE'S RESPONSE. The program
    says what KIND the operation was, and does NOT say what it created.
    The distinction is not cosmetic: taking the declared ops from the
    program would mean recording as created something that was rolled
    back. On a rollback a creating op returns an empty line, and the
    registry stays empty just the same.

    `None` — no map was given (a legacy call, a registry test, a foreign
    bridge). Then the kind is not asked, and the behavior is the PRIOR one,
    byte for byte: an extra line is better than a lost id of a live
    element.
    """

    out: dict[str, list[str]] = {}
    if not isinstance(payload, Mapping):
        return out
    keys = created_keys()
    for oid, row in payload.items():
        if not isinstance(row, Mapping):
            continue
        if op_kinds is not None:
            from kir import spec
            from kir.registry_base import EffectKind
            op_name = op_kinds.get(str(oid))
            op = spec.OPS.get(op_name) if op_name else None
            # 🔴 THE KIND IS ASKED OF THE REGISTRY, NOT GUESSED FROM THE
            # FIELD NAME. An unknown op is NOT discarded: the registry
            # could have fallen behind the bridge, and losing the id of a
            # live element is worse than recording an extra one.
            if op is not None and op.effect is not EffectKind.CREATE:
                born = replacement_born_ids(row)
                if born:
                    out[str(oid)] = born
                continue
        ids: list[str] = []
        for key in keys:
            v = row.get(key)
            if isinstance(v, (str, int)) and not isinstance(v, bool):
                ids.append(str(v))
            elif isinstance(v, Sequence) and not isinstance(v, (str, bytes)):
                ids.extend(str(x) for x in v)
        if ids:
            out[str(oid)] = ids
    return out


def read_created(path: pathlib.Path | None = None, *,
                 since: str = "", limit: int | None = None
                 ) -> tuple[tuple[dict[str, Any], ...], str]:
    """Read the registry back: `(rows, refusal)`. The FIRST reader of the
    module.

    🔴 THE RETURN IS A PAIR, AND THIS WAS BOUGHT BY THE VERY FIRST RUN
    (17.08.2026). The first edition returned only rows and wrote the
    reason to the log: the registry sits with 600 permissions, the reader
    got `Permission denied` and returned an empty tuple — meaning
    **"could not look" and "nothing was created" became indistinguishable
    TO THE CALLER**, exactly the ailment this module was written to cure.
    The law of §18.2 of this package says the same thing in one line:
    `rows + failures`, both keys mandatory. An empty refusal is the only
    way to say "looked, it's empty there".

    🔴 WHY THIS FUNCTION ONLY APPEARED ON 17.08.2026. Before it, the
    module's entire public surface was PRODUCING (`created_keys`,
    `not_created_keys`, `ledger_path`, `extract_created`,
    `record_created`) — the registry was written and read by NOBODY.
    Measured that day on the live file: **30 rows, 471 created elements**
    in a single day, and not one consumer anywhere in the tree.

    This is exactly item 9 of the NAKAZ ("the model felt nothing of what
    it touched: the `op_id → element_id` map is guaranteed and consumed by
    nobody"), and the cost is named by the module's own header: on 13.08
    two elements remained in the owner's model without a trace of their
    numbers, and a MANUAL reading of the document saved the day.

    WHAT THIS FUNCTION DOES NOT SAY. It answers "what did we CREATE", not
    "what EXISTS now": only the document knows whether the element still
    belongs to us. Confusing the two means passing off the journal as
    Revit's state — the very kind of error the whole package is a cure
    for.

    `since` — a timestamp prefix (`"2026-08-17"`), compared as a string:
    ISO-8601 timestamps in UTC are lexicographically ordered by
    construction. A broken line is SKIPPED and counted: a file corrupted
    at one record has no right to hide the rest.
    """

    target = path if path is not None else ledger_path()
    out: list[dict[str, Any]] = []
    if target is None:
        return (), "реестр выключен: записываемого корня у установки нет"
    if not target.exists():
        return (), f"файла реестра нет: {target}"
    broken = 0
    try:
        with target.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001 — a broken line is DATA
                    broken += 1
                    continue
                if not isinstance(row, Mapping):
                    broken += 1
                    continue
                if since and str(row.get("ts") or "") < since:
                    continue
                out.append(dict(row))
    except OSError as exc:
        logger.error("created_ledger: реестр не прочитать (%s): %s",
                     target, exc)
        return (), f"реестр не прочитать ({type(exc).__name__}): {exc}"
    if broken:
        logger.warning("created_ledger: пропущено битых строк: %d", broken)
    if limit is not None and limit >= 0:
        out = out[-limit:]
    refusal = (f"пропущено битых строк: {broken}" if broken else "")
    return tuple(out), refusal


def created_index(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """`op_id -> element_id` — THE VERY map the registry was written for.

    An op that created SEVERAL elements gives the first id, and this is
    NAMED: the map answers "where to look", not "how many came out". The
    full list sits in the row itself (`row["created"][oid]`), and it
    doesn't go anywhere.

    A later row OVERWRITES an earlier one: an op's id is unique within one
    program but repeats across turns, and a fresher answer is more useful
    than an old one.
    """

    index: dict[str, str] = {}
    for row in rows:
        created = row.get("created")
        if not isinstance(created, Mapping):
            continue
        for oid, ids in created.items():
            if isinstance(ids, Sequence) and not isinstance(ids, (str, bytes)):
                first = next((str(x) for x in ids), "")
                if first:
                    index[str(oid)] = first
    return index


def _write_line(path: pathlib.Path, row: Mapping[str, Any]) -> None:
    """Append and COMMIT to disk: fsync the file and the directory.

    Without fsync on the directory, the line survives a process crash but
    not a machine crash — and the registry exists precisely for the cases
    where something broke off.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        # 🔴 `os.write` IS ENTITLED TO WRITE LESS AND NOT RAISE (30.08.2026,
        # audit finding F-300). A discarded return value meant a
        # TRUNCATED line passed as written: `record_created` returned an
        # ordinary row, no error file appeared, the log stayed silent —
        # and the next reader would count the record as corrupted. A
        # module written precisely against losing the trace of created
        # elements was losing the trace and reporting success; silent
        # degradation was present here, it just did not travel through an
        # exception.
        #
        # We append IN A LOOP until done, rather than "check once": a
        # short write is legitimate and can repeat.
        data = line.encode("utf-8")
        written = 0
        while written < len(data):
            n = os.write(fd, data[written:])
            if n <= 0:
                raise OSError(
                    f"короткая запись в реестр: ушло {written} из "
                    f"{len(data)} байт, запись прервана")
            written += n
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def record_created(
    payload: Any,
    *,
    op_kinds: Mapping[str, str] | None = None,
    query_id: str = "",
    turn_id: str = "",
    action_id: str = "",
    revit_version: str = "",
    plan_digest: str = "",
    family: str = "",
    ts: str = "",
    device_id: str = "",
    doc_key: str = "",
) -> dict[str, Any] | None:
    """Record what was created. Never raises; returns the row that was
    written.

    A return of ``None`` means EXACTLY ONE THING: the registry is off, or
    the install does not own a writable root. A failed write returns the
    row and puts the reason into a neighboring file — so that "we did not
    write" and "we failed to write" do not look the same.
    """

    created = extract_created(
        payload.get("result", payload) if isinstance(payload, Mapping)
        else payload,
        op_kinds=op_kinds)
    if not ts:
        # The timestamp is set by the REGISTRY, not by the caller: for a
        # row whose date comes from outside, the date is a property of the
        # caller, not of the event. The parameter remains for the sake of
        # tests that need a reproducible row.
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    row: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "query_id": query_id,
        "turn_id": turn_id,
        "action_id": action_id,
        "revit_version": revit_version,
        "plan_digest": plan_digest,
        "family": family,
        # 🔴 THE SESSION BINDING, SET UP 19.08.2026. Before it, a row
        # carried only `query_id`/`turn_id`/`action_id`, meaning the
        # registry was SHARED ACROSS THE FLEET and UNATTRIBUTABLE: on
        # thirteen devices, handing it to a reader would mean leaking ids
        # from SOMEONE ELSE'S documents. That is exactly why it had no
        # reader — not "forgotten", but "not allowed".
        #
        # Rows written BEFORE this fix carry no binding and are never
        # found by it. This is not a loss but honesty: attributing them to
        # some device would mean inventing ownership.
        "device_id": str(device_id or ""),
        "doc_key": str(doc_key or ""),
        # DID WE KNOW THE KIND OF OPERATIONS WHEN WE WROTE THIS ROW
        # (F-297). Without this field, a row written off the UNION of
        # identity fields is indistinguishable from a row written BY KIND —
        # and they mean different things: the first may hold the ids of
        # elements the turn did not create.
        "op_kinds_known": op_kinds is not None,
        "created": created,
        "created_count": sum(len(v) for v in created.values()),
    }
    path = ledger_path()
    if path is None:
        return None
    try:
        _write_line(path, row)
    except Exception as exc:  # noqa: BLE001 — the write to Revit has already happened
        logger.error("created_ledger: строку не записать (%s): %s",
                     path, exc)
        try:
            _write_line(path.with_suffix(".errors.jsonl"),
                        {"schema_version": SCHEMA_VERSION, "ts": ts,
                         "query_id": query_id, "error": str(exc)[:300],
                         "created_count": row["created_count"]})
        except Exception:  # noqa: BLE001 — there is nothing more to do
            logger.exception("created_ledger: и файл ошибок недоступен")
    return row


def created_for_session(device_id: str, doc_key: str = "", *,
                        path: pathlib.Path | None = None,
                        limit: int = 200) -> dict[str, Any]:
    """What THIS session CREATED — the reader-agent's one and only door.

    🔴 WHY. The registry has been written since 17.08 (that day's
    measurement: 30 rows, 471 elements in a day) and **was read by
    nobody**. This is item 9 of the NAKAZ, literally: the
    `op_id -> element_id` map is guaranteed and consumed by nobody. The
    cost is named by the module's own header: on 13.08 two elements
    remained in the owner's live model without a trace of their numbers,
    and a MANUAL reading of the document saved the day. Both hands of the
    18.08 live benchmark independently asked for this door in their own
    words — one of them was keeping id bookkeeping by hand across dozens
    of local files.

    🔴 THE SCOPE IS STRICT, AND THIS IS NOT CAUTION. A row without
    `device_id` belongs to nobody: it was written before the binding was
    set up, and attributing it to the caller would mean inventing
    ownership, and on a fleet — leaking someone else's model. Such rows
    are NOT returned and are counted separately (`unattributable`), so
    that "they don't exist" and "they exist, but aren't ours" are not
    indistinguishable.

    🔴 "IN THE JOURNAL" DOES NOT EQUAL "ACCEPTED", and the reader must see
    the difference. `record_created` writes IMMEDIATELY after the
    bridge's response — BEFORE acceptance, because it is precisely
    acceptance that declares failure under `KIR-A006`/`KIR-A007` when the
    write has already happened. So an id here means "Revit built this",
    not "the program accepted this", and `verdict_unknown` is always
    present in the answer.

    🔴 A THIRD EMPTINESS, AND IT IS NOT THE SAME AS THE FIRST TWO
    (29.08.2026, audit finding F-299). When the document IS SPECIFIED, a
    row of this device with an EMPTY `doc_key` is neither "someone else's"
    nor "not ours": it is ours, but written before the document key was
    set up, and nobody knows which building it belongs to. Attributing it
    to the active document would mean inventing ownership — exactly what
    `unattributable` above refuses to do. So such rows are NOT returned and
    are counted SEPARATELY (`unscoped`), otherwise the fix that narrowed
    the answer to a document would silently zero it out for everyone who
    created anything BEFORE that fix, and the loss would be
    indistinguishable from emptiness.

    🔴 A THIRD KIND OF ANSWER: "THERE ARE ROWS AND THERE IS A WARNING"
    (F-298). `refusal` is non-empty in TWO different cases, and they must
    not be confused:

        NO rows  + refusal  ->  could not look (registry off, no file,
                                unreadable)
        rows EXIST + refusal ->  looked, but not at everything: broken
                                rows were skipped and COUNTED

    The second case is `read_created`'s intent, not a failure, and zeroing
    the answer because of it would let one corrupted byte hide the whole
    journal. They are told apart by STRUCTURE (whether the tuple is
    empty), not by the text of the refusal.

    Returns `{rows, created_count, unattributable, unscoped, refusal,
    verdict_unknown}`. The law of §18.2 — "could not look" and "there is
    nothing" must be distinguished; here a third is added to them: "did
    not look at everything".
    """
    want_dev = str(device_id or "")
    if not want_dev:
        return {"rows": (), "created_count": 0, "unattributable": 0,
                "unscoped": 0,
                "refusal": ("устройство не названо: реестр общий на флот, и "
                            "без привязки ответ был бы чужим"),
                "verdict_unknown": True}
    rows, refusal = read_created(path)
    # 🔴 "COULD NOT LOOK" AND "LOOKED, BUT NOT AT EVERYTHING" ARE
    # DIFFERENT FACTS (30.08.2026, audit finding F-298). `read_created`
    # DELIBERATELY returns valid rows TOGETHER with a non-empty refusal
    # when it has skipped broken ones: "a file corrupted at one record has
    # no right to hide the rest" — its own docstring. Here that intent was
    # being undone: ANY non-empty refusal zeroed out the answer, and one
    # corrupted byte at the end of the file hid the entire journal
    # (measured on the module: 471 elements in a day).
    #
    # We tell them apart by STRUCTURE, not by text: genuine refusals
    # (registry off, no file, unreadable) arrive with an EMPTY tuple; a
    # warning about skipped rows arrives with a non-empty one.
    if refusal and not rows:
        return {"rows": (), "created_count": 0, "unattributable": 0,
                "unscoped": 0,
                "refusal": refusal, "verdict_unknown": True}
    want_doc = str(doc_key or "")
    mine: list[dict[str, Any]] = []
    unattributable = 0
    unscoped = 0
    for row in rows:
        dev = str(row.get("device_id") or "")
        if not dev:
            unattributable += 1
            continue
        if dev != want_dev:
            continue
        if want_doc:
            row_doc = str(row.get("doc_key") or "")
            if not row_doc:
                # 🔴 THE THIRD EMPTINESS (F-299): the row is OURS, but
                # which building it is about is unknown. We do not return
                # it and do NOT stay silent.
                unscoped += 1
                continue
            if row_doc != want_doc:
                continue
        mine.append(dict(row))
    mine = mine[-limit:] if limit and limit > 0 else mine
    return {
        "rows": tuple(mine),
        "created_count": sum(int(r.get("created_count") or 0) for r in mine),
        "unattributable": unattributable,
        "unscoped": unscoped,
        # The warning reaches the reader TOGETHER with the rows: they must
        # be able to learn from the answer ITSELF that part of the journal
        # did not parse (F-298).
        "refusal": refusal,
        # Present ALWAYS and on purpose: a field that only shows up
        # sometimes gets read by the reader as a sign of trouble.
        "verdict_unknown": True,
    }


__all__ = ["LEDGER_DIR_ENV", "SCHEMA_VERSION", "REPLACEMENT_BIRTH_FIELDS",
           "REPLACEMENT_ID_FIELDS", "created_for_session", "created_index",
           "created_keys", "read_created", "replacement_born_ids",
           "extract_created", "ledger_path", "not_created_keys",
           "record_created"]
