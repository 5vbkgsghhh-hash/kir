"""THE LIVE HALF OF THE DOOR: open a building and write into it.

Stage 4 of the plan, the part that HAS a gate without a live Revit. What
is built here and what is NOT is named before the code, because "built"
without an instrument is an intention, not a stage.

BUILT AND VERIFIABLE TODAY:
  * HANDLES instead of sessions (`handles.py`) — choosing a document
    became explicit;
  * A WRITE GATE, fail-closed: without an explicit `KIR_MCP_WRITE=on` the
    write door refuses, and the refusal names both the flag and the
    reason;
  * HUMAN CONFIRMATION via MRTR (`resultType: "input_required"`): the
    first write call writes nothing, and returns a confirmation request;
    the client repeats the call with the answer. State rides in
    `requestState`, not in the server's memory — exactly as the sessionless
    core of 2026-07-28 requires;
  * A TRANSPORT SEAM (`ports.MCP_REVIT`): no provider — a NAMED refusal
    with the port's name, not silence and not a guess.

🔴 WHAT IS NOT HERE, AND THIS IS A CORRECTION TO MY OWN PROMISE
(02.09.2026). I promised to build the **Tasks** extension
(`io.modelcontextprotocol/tasks`) and am NOT building it. Two reasons,
both measured, not merely felt:
  1. the SDK does not carry it — in `mcp` 2.1.1 there is not one mention
     of `tasks/get`, except for an example in `extension.py`'s docstring.
     So this is not "turn it on," it is "write the whole extension";
  2. and most of all: THERE IS NOTHING TO MEASURE IT WITH. Tasks' value is
     in a write that runs for minutes (the K3 transfer: 55 programs,
     12,127 operations, 3 s → 250 s → refusal). Against a mock that answers
     instantly, I would build a mechanism that never reddens — that is, an
     invented gate, and those cost more in this house than a missing one.
     I will build it once there is a live Revit and a real duration.
For now the write is synchronous and bounded by a timeout, and this is
NAMED in the door's description, not hidden.

🔴 THE PRODUCT'S GATE IS NOT CARRIED OVER HERE, AND THIS IS NOT AN
OVERSIGHT. `revit_ir_enabled()` requires "an explicit KIR mode on the
turn"; MCP has no turn at all, and the `TURN_CONTEXT` port is never asked
here. In place of the lifted condition — TWO of our own, both visible: an
environment switch and human confirmation on every write. The operator's
decision of 13.08 is not overturned by this but replaced by a named pair;
the final word is the owner's.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from kir import env  # noqa: E402  (a submodule with no dependencies — gives no cycle)
from typing import Any

from kir import ports
from kir.mcp import policy as _policy

#: The write switch. FAIL-CLOSED: any value other than `on` means "no."
#: The list of admitted values is NOT extended ("1", "true", "yes"): a
#: door with many ways to open opens by accident.
WRITE_FLAG = "KIR_MCP_WRITE"

#: The ceiling for one round trip. Not "generous," but an upper estimate
#: for a synchronous write: anything longer is Tasks' subject, not the
#: timeout's (see the header).
WRITE_TIMEOUT_MS = 120_000
READ_TIMEOUT_MS = 30_000

#: The key by which the door asks the server for confirmation.
#: `server.py` translates it into `InputRequiredResult`; the door itself
#: knows nothing of the SDK (the boundary law).
INPUT_REQUIRED = "__input_required__"


def write_enabled() -> bool:
    return (env.get(WRITE_FLAG) or "").strip() == "on"


#: 🔴 У ЭТОЙ ДВЕРИ НЕТ ИНСТРУМЕНТА ЧТЕНИЯ, И ОТКАЗ ОБЯЗАН ЭТО ЗНАТЬ.
#:
#: Р1.2, аудит H §3 (13.09.2026): пять отказов этого файла велели агенту
#: «прочитай модель» — ход, которого у него НЕТ. Палитра двери — семь
#: инструментов (`author, spec, compile, rehearse, open, write, preview`,
#: `kir/mcp/surface.py:279-441`), и ни один не рассказывает, что в документе;
#: `kir_open` отдаёт заголовок, версию и отпечаток, а `kir_write` отказывает
#: программе-запросу словами «query не отправлен» (:676). Конституция требует
#: от отказа причину И СЛЕДУЮЩИЙ ХОД; ход, названный несуществующим
#: инструментом, стоит ровно столько же, сколько молчание, — замерено на живом
#: человеке 13.09: `STREAM LOOP: рассуждение зациклилось (5 повторов)`.
#:
#: 🔴 ПОЧЕМУ ОДНА КОНСТАНТА, А НЕ ПЯТЬ ПРАВОК. Пять мест, обязанных говорить
#: одно и то же о палитре, — это пять мест, где живёт одно решение; они уже
#: разошлись однажды, и разойдутся снова в N-1 из них. Появится `kir_query`
#: (H §5, «четвёртая правка») — здесь меняется одна строка, и её меняют все
#: пятеро разом.
NO_READER_RU = (
    "прочитать модель сам ты не можешь: в палитре этой двери "
    "(`author, spec, compile, rehearse, open, write, preview`) инструмента "
    "чтения нет. Смотрит документ ЧЕЛОВЕК — спроси его")


def _refusal(code: str, message_ru: str, **extra: Any) -> dict:
    body = {"ok": False, "kir": True, "wrote_nothing": True,
            "err": {"code": code, "message_ru": message_ru}}
    body.update(extra)
    return body


def _transport() -> Any:
    """A transport provider, or a NAMED refusal with the port's name."""
    return ports.need(ports.MCP_REVIT)


def program_digest(program: Any) -> str:
    """A program's signature — by its CANONICAL form, not by the argument's
    text.

    Otherwise reordering the keys in the JSON would give a different
    signature for the same program, and human confirmation would stop
    relating to what it had confirmed.
    """
    blob = json.dumps(program, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# kir_open
# ─────────────────────────────────────────────────────────────────────────────

def _fingerprint(row: Any) -> str:
    """The document's fingerprint. ONE method for issuing the handle and
    for checking it before a write: two methods would drift apart, and the
    check would become an identity turned inside out — an eternal mismatch
    or an eternal match."""
    r = row if isinstance(row, dict) else {}
    raw = f"{r.get('title') or ''}\x00{r.get('version') or ''}\x00{r.get('path') or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


#: A reading probe: the document's title, version, and fingerprint. The
#: body is deliberately minimal — a round trip for what was asked, and
#: nothing more.
#
# 🔴 THE FORM WAS BOUGHT BY A LIVE REVIT ON 02.09.2026, NOT WRITTEN FROM
# MEMORY. `Result = new {...}` used to stand here — and the very first
# real round trip returned `CS0118: 'Result' is a type but is used like a
# variable`. The body rides inside
# `public static object Execute(Document doc, UIDocument uidoc)`, that is,
# it must RETURN, not assign, and the document already sits in `doc`.
# A probe never executed even once is an assumption in the shape of code.
_PROBE_CS = """
var d = doc;
return new { title = d.Title, version = d.Application.VersionNumber, path = d.PathName ?? "" };
""".strip()


async def open_building(args: dict) -> dict:
    """`kir_open` — ask the host WHAT is open, and issue a handle."""
    from kir.mcp import handles

    try:
        transport = _transport()
    except ports.PortMissing as exc:
        return _refusal(
            "no_transport", str(exc),
            next_ru=("этот сервер стоит ОФЛАЙН: пиши программы `kir_author`, "
                     "проверяй `kir_rehearse`/`kir_preview`, получай C# "
                     "`kir_compile` — записи не будет, пока хозяин не поставит "
                     "порт «mcp.revit»"))
    try:
        answer = await transport.read(_PROBE_CS, timeout_ms=READ_TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001 — a transport failure is not a crash of the door
        return _refusal("transport", f"{type(exc).__name__}: {exc}",
                        next_ru="проверь, что Ревит открыт и мост поднят")

    row = answer if isinstance(answer, dict) else {}
    title = str(row.get("title") or "").strip()
    version = str(row.get("version") or "").strip()
    if not title or not version:
        return _refusal(
            "empty_probe",
            "хост ответил без заголовка документа или версии — открывать нечего",
            got=row,
            next_ru="открой документ в Ревите и позови `kir_open` заново")

    fingerprint = _fingerprint(row)
    building = handles.issue(document=title, revit_version=version,
                             fingerprint=fingerprint)
    body = {"ok": True, "kir": True, "wrote_nothing": True}
    body.update(building.as_dict())
    body["write_enabled"] = write_enabled()
    body["next_ru"] = (
        "ручка выдана. Передавай её полем `building` в `kir_write`; "
        + ("запись включена — каждый вызов потребует подтверждения человеком"
           if write_enabled() else
           f"запись ВЫКЛЮЧЕНА: хозяин не выставил {WRITE_FLAG}=on, и это "
           f"умолчание, а не поломка"))
    return body


# ─────────────────────────────────────────────────────────────────────────────
# kir_write
# ─────────────────────────────────────────────────────────────────────────────

def write_summary(program: Any) -> dict:
    """What THIS program will do to the model — by the REGISTRY, not by an
    op's name.

    🔴 BOUGHT BY REVIEW ON 02.09.2026. `op.startswith("create_")` used to
    be counted here — and that is exactly the instrument that is "right
    about a different subject": of the registry's 82 ops, `delete`,
    `move_elements`, `set_param`, `change_type`, `join_elements`, and kin
    do not fit under it. A program of 500 deletions showed the human "0
    elements" on the ONE screen before the one irreversible action in the
    system. It now counts by kind from the registry, and kinds are NAMED
    by name: "delete×500" is a different statement than "500 operations."
    """
    from kir import spec

    kinds: dict[str, int] = {}
    writing = 0
    for op in (program.get("ops") or []) if isinstance(program, dict) else []:
        name = str(op.get("op") or "") if isinstance(op, dict) else ""
        ospec = spec.OPS.get(name)
        if ospec is None:
            continue
        if ospec.family in spec.WRITE_FAMILIES:
            writing += 1
            kinds[name] = kinds.get(name, 0) + 1
    top = sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
    return {"writing_ops": writing,
            "ops_total": len(program.get("ops") or []) if isinstance(program, dict) else 0,
            "kinds": dict(top),
            "kinds_ru": ", ".join(f"{n}×{c}" for n, c in top) or "нет пишущих"}


#: The key of an unresolved dispatch in the handle's `extra` — E6.
#:
#: 🔴 WHAT THIS CLOSES AND WHAT IT DOES NOT (06.09.2026, E6/F4 audit).
#: Measured before the fix, through the public door: `kir_write` ->
#: transport accepted the program and lost the response -> the same
#: `kir_write` -> `writes=2, ok=True`. A second ELEMENT in the model, and
#: not one carrier that would notice it.
#:
#: WHY NOT operation_id WITH A LOOKUP, AS IN STANDALONE. Checked by
#: EXECUTION, not by reading (`.work/…/fix-C1-E6/probe_e6.py`, section
#: `stored_route_reachability`): `standalone_publish.publish_stored_project`
#: — the route where a lost response gives executes=1 — requires THREE
#: things, none of which this door has:
#:   * a `ProjectStore` with a CREATE schema (MCP has no store at all: its
#:     own handles live in the process's memory ON PURPOSE, see
#:     `handles.py`);
#:   * `GeometryMaterialization` over a `ProjectRevision` — that is, a
#:     PROJECT; `kir_write` accepts a bare program, and inventing a
#:     project around it would mean fabricating authorship that never
#:     existed;
#:   * `DiscoveryAdvertisement` + a client path — the connector's transport
#:     over a named channel. The `ports.McpRevitPort` port carries EXACTLY
#:     two methods, `read` and `write`, with no operation identity and no
#:     receipt lookup; adding them would mean changing the contract with
#:     EVERY owner of the door.
#: Hence the owner's second answer was chosen — "an explicit refusal of the
#: unsafe write path" — but the refusal is TARGETED: not every write is
#: unsafe, only the one that goes out while the outcome of the previous one
#: on THIS SAME document is unknown. Turning the door off entirely would
#: cost more than the defect itself and would take away legitimate first
#: writes.
#:
#: WHERE THE MARKER LIVES AND WHY THERE. In the handle's `extra` — that is,
#: in the same place and with the same lifetime as all the rest of this
#: door's state. No new schema, no new file, and no new environment
#: variable is introduced ON PURPOSE: a door that has grown a store must
#: answer for its consistency, and there is nothing to pay for that with —
#: there is no live Revit here.
#: The check runs by the DOCUMENT'S FINGERPRINT across ALL live handles,
#: not just the one presented: otherwise `kir_open` would issue a new
#: handle and bypass the marker with one call — a bypass that would cost
#: exactly the same second element.
#:
#: 🔴 A BOUNDARY I NAME, RATHER THAN PASS OVER IN SILENCE: the marker lives
#: exactly as long as the process does. It has nothing to survive a server
#: restart with — but neither does the handle: after a restart
#: `handles.resolve` refuses ("handle unfamiliar to the server"), so a
#: BLIND repeat of the same write never reaches it at all. Exactly one
#: remainder stays unclosed: a human calls `kir_open` again AFTER the
#: restart and sends the same program. Closing it honestly is possible
#: only with operation identity in the port's contract (a lookup by
#: operation_id) — that is a change to `ports.py` and to every owner, and
#: it is named, not done quietly.
UNRESOLVED = "unresolved_write"

#: Where the door keeps UNRESOLVED dispatches. The operator names the
#: directory themselves — the same shape as the acceptance journal's
#: (`KIR_ACCEPTANCE_EVIDENCE_DIR`), and for the same reason: "an
#: unmeasured record is never a fallback."
PENDING_DIR_ENV = "KIR_MCP_PENDING_DIR"

#: The record's schema. One, flat, versioned — a file, not a database:
#: the door has no store, and grows none, whose consistency it would have
#: to answer for.
PENDING_SCHEMA = "kir-mcp-pending-write/1"


class PendingStoreError(Exception):
    """The store of unresolved dispatches is unreachable or corrupted."""


def user_data_dir():
    """KIR's data directory for the USER — outside any host.

    🔴 WHY NOT `install_data_path` (round 3 acceptance, reservation 1).
    That authority finds a directory only via `KIR_INSTALL_ROOT`, a host
    port, or the `backend/kukai` marker above the package, and that gave
    TWO wrong outcomes at once:
      * an ordinary install from PyPI has no root at all — and the write
        door refused by default even with `KIR_MCP_WRITE=on`. The owner's
        measure is "a stranger installs it and builds," and the door
        demanded a setup they know nothing about;
      * on a host install, the KIR door's record would land INSIDE
        KUKAI's tree. There are three projects, each with its own root;
        putting the language's data into the product's tree erases the
        boundary the owner drew in words.
    Hence a user data directory of its own, and `install_data_path` is
    never asked for THIS record at all.

    The shape is taken from the platform, not invented: `XDG_DATA_HOME`
    (Linux/macOS, `~/.local/share` by default) and `%LOCALAPPDATA%`
    (Windows). Permissions `0700` — the file holds program signatures and
    the author's document titles.
    """
    import pathlib

    if os.name == "nt":
        base = (env.get("LOCALAPPDATA") or "").strip()
        if not base:
            raise PendingStoreError(
                "у этой учётной записи не задан %LOCALAPPDATA%")
        return pathlib.Path(base) / "kir" / "mcp"
    named = (env.get("XDG_DATA_HOME") or "").strip()
    if named:
        return pathlib.Path(named) / "kir" / "mcp"
    home = (env.get("HOME") or "").strip()
    if not home:
        raise PendingStoreError("у этой учётной записи не задан $HOME")
    return pathlib.Path(home) / ".local" / "share" / "kir" / "mcp"


def pending_path():
    """The file of unresolved dispatches. Two authorities, and NEITHER is
    the host's.

    THE OPERATOR (`KIR_MCP_PENDING_DIR`) → the user's data directory
    (`user_data_dir`). There is no third way; `None` is no longer
    returned — "nothing to address it with" became a refusal with a named
    reason, not silence.
    """
    import pathlib

    named = (env.get(PENDING_DIR_ENV) or "").strip()
    if named:
        return pathlib.Path(named) / "pending_writes.json"
    return user_data_dir() / "pending_writes.json"


def ensure_store_dir(path) -> None:
    """Create the write directory with 0700 permissions and MAKE SURE it
    can actually be written to.

    The check happens EARLY — at the gate, before asking the human: asking
    for consent to a write that will not go through anyway would waste the
    decision. And it verifies writability BY DOING IT (creates and removes
    a probe file), not by permissions in `stat`: a read-only mounted
    volume, a full quota, and a directory owned by someone else all pass
    `stat`.
    """

    directory = path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        probe = directory / (".probe-%d" % os.getpid())
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("")
        probe.unlink()
    except OSError as exc:
        raise PendingStoreError(
            f"каталог неразрешённых отправок недоступен для записи "
            f"({directory}): {exc}")


def _pending_load(path) -> dict:
    """Records from the file. A corrupted file is a REFUSAL, not "no
    records."

    Reading garbage as emptiness would open the door for exactly the case
    it is closed against: the file is damaged — the outcome of the past
    dispatch is unknown ALL THE MORE.
    """
    if not path.exists():
        return {}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PendingStoreError(f"файл неразрешённых отправок не читается: {exc}")
    if not isinstance(body, dict) or body.get("schema") != PENDING_SCHEMA:
        raise PendingStoreError(
            f"файл неразрешённых отправок не той схемы (ожидалась {PENDING_SCHEMA})")
    records = body.get("records")
    if not isinstance(records, dict) or not all(
            isinstance(key, str) and isinstance(value, dict) for key, value in records.items()):
        raise PendingStoreError("состав файла неразрешённых отправок повреждён")
    return records


def _pending_save(path, records: dict) -> None:
    """Write the whole thing, via atomic replacement, with an explicit
    `fsync`.

    Without `fsync` a "durable write" is just a label: what grants the
    promise of surviving a restart is not `write()`, but reaching the
    disk.
    """

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps({"schema": PENDING_SCHEMA, "records": records},
                          ensure_ascii=False, sort_keys=True, indent=1)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(blob + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        raise PendingStoreError(f"неразрешённую отправку не записать: {exc}")


def _blocking_records(records: dict, *, fingerprint: str, digest: str) -> dict:
    """Records blocking THIS write.

    A match on TWO keys, not one, and this is exactly the hole that a
    durable write closes: the document's fingerprint
    (`title\\0version\\0path`) changes on a rename and on `Save As`, while
    a program's signature does not. Asking only the fingerprint would mean
    letting through a repeat of the same program after a rename; only the
    signature — letting through ANY other program into a document with an
    unknown state.
    """
    return {oid: rec for oid, rec in records.items()
            if rec.get("fingerprint") == fingerprint or rec.get("program_digest") == digest}


def _unresolved_write(fingerprint: str, *, digest: str | None = None) -> dict | None:
    """An unresolved dispatch for this document (or this program), or
    ``None``.

    A corrupted/unreachable store raises `PendingStoreError` — the door
    must refuse, rather than silently decide there are no records.
    """
    path = pending_path()
    ensure_store_dir(path)
    records = _pending_load(path)
    blocking = _blocking_records(records, fingerprint=fingerprint,
                                 digest=digest if digest is not None else "\0none")
    if not blocking:
        return None
    oid = sorted(blocking)[0]
    return dict(blocking[oid], operation_id=oid)


def _clear_unresolved(fingerprint: str, *, digest: str | None = None,
                      operation_id: str | None = None) -> None:
    """Clear records: one by operation name, or all those blocking this write."""
    path = pending_path()
    records = _pending_load(path)
    if operation_id is not None:
        drop = {operation_id} & set(records)
    else:
        drop = set(_blocking_records(
            records, fingerprint=fingerprint,
            digest=digest if digest is not None else "\0none"))
    if not drop:
        return
    for oid in drop:
        records.pop(oid, None)
    _pending_save(path, records)


def _writer_takes_operation_id(writer) -> bool:
    """Whether the host has NAMED-DISPATCH capability — by signature, not
    by a caught throw.

    A throw is indistinguishable from the write itself failing: learning
    the capability from an exception, the door would record "the host
    cannot" in a case where it can, and refused.
    """
    import inspect

    try:
        parameters = inspect.signature(writer).parameters
    except (TypeError, ValueError):
        return False
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return True
    found = parameters.get("operation_id")
    return found is not None and found.kind in (
        inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)


async def _resolve_by_lookup(transport: Any, mark: dict, planned: Any, *,
                             digest: str, building: Any) -> tuple[str, dict | None]:
    """Ask the runtime how the unresolved operation ended.

    Three outcomes, and they are DIFFERENT, so they do not collapse into a
    boolean:
      * ``("unresolved", None)`` — no capability, the runtime threw,
        answered with unknown, or with the receipt of SOMEONE ELSE'S
        program. The question to the human remains;
      * ``("proceed", None)`` — the runtime PROVED the operation never
        started (`lookup` returned ``None``): there was no write, the
        marker is cleared, writing is allowed;
      * ``("answer", body)`` — the operation took place, its outcome is
        NAMED. We hand back the first dispatch's receipt and do NOT make a
        second one — exactly what operation identity was introduced for.

    A receipt is read by OUR plan only if it is THE SAME program: otherwise
    there is nothing to classify it by, and "I don't know" is more honest
    than an invented verdict.
    """
    lookup = getattr(transport, "lookup", None)
    if not callable(lookup):
        return "unresolved", None
    operation_id = str(mark.get("operation_id") or "")
    if not operation_id:
        return "unresolved", None
    if str(mark.get("program_digest") or "") != digest:
        return "unresolved", None
    try:
        receipt = await lookup(operation_id)
    except Exception:  # noqa: BLE001 — a throw from the host = "still unknown"
        return "unresolved", None
    if receipt is None:
        # The port's contract: `None` is allowed ONLY when "did not start" is proven.
        _clear_unresolved(building.fingerprint, operation_id=operation_id)
        return "proceed", None

    from kir import bridge_result as _bridge
    from kir.outcome import ExecutionState

    assessment = _bridge.assess_write_result(receipt, planned)
    if assessment.outcome.execution is ExecutionState.UNCONFIRMED:
        return "unresolved", None
    _clear_unresolved(building.fingerprint, operation_id=operation_id)
    common = {
        "building": building.handle, "document": building.document,
        "revit_version": building.revit_version,
        "program_digest": digest, "receipt": receipt,
        "operation_id": operation_id,
        "outcome": assessment.outcome.to_dict(), "intent_verified": False,
        "recovered": True,
    }
    if assessment.ok:
        return "answer", {
            "ok": True, "kir": True, "wrote_nothing": False,
            "success_scope": "execution_contract", **common,
            "next_ru": ("исход предыдущей отправки восстановлен по её имени; "
                        "второй записи не было")}
    return "answer", _refusal(
        "execution_incomplete",
        "исход предыдущей отправки восстановлен по её имени и НЕ является успехом",
        wrote_nothing=False, **common,
        next_ru=("исправь расхождения новым планом по названным полям "
                 "квитанции (`diagnostics`, `violations`, `outcome`): " + NO_READER_RU))


def _unresolved_request(building: Any, mark: dict, digest: str) -> dict:
    """The question about an UNKNOWN outcome is not "apply this?" but "did
    you check?"

    It is asked ALWAYS, including with `KIR_MCP_CONFIRM=off`: the operator
    lifted the "should this be written" question, and this question is a
    different one — "is it known what has already been written." Merging
    them would mean setting up one answer for two different decisions.
    """
    same = str(mark.get("program_digest") or "") == digest
    return {
        INPUT_REQUIRED: {
            "message": (
                f"В «{building.document}» уже уходила запись "
                f"{str(mark.get('program_digest') or '—')[:12]} "
                f"(операция {str(mark.get('operation_id') or '—')[:8]}), "
                f"и её исход НЕИЗВЕСТЕН: транспорт отказал ПОСЛЕ отправки. "
                + ("Сейчас пришла ТА ЖЕ программа — повтор вслепую удвоит то, "
                   "что могло примениться. " if same else
                   "Сейчас пришла другая программа, но состояние документа "
                   "неизвестно и ей. ")
                + "Прочитай модель (query-запросом или в самом Ревите). "
                  "Подтверди только если посмотрел: ответ снимает отметку, "
                  "и запись пойдёт обычным ходом. Отказ не пишет ничего."),
            "schema": {
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "title": "Исход предыдущей записи проверен",
                        "description": ("Отказ ничего не пишет и отметку не "
                                        "снимает."),
                    },
                },
                "required": ["confirm"],
            },
            # The answer is tied to the OPERATION'S NAME, not to the
            # program's signature: the operation is what has an unknown
            # outcome, and it is exactly that which must be resolved.
            "state": {"building": building.handle, "digest": digest,
                      "fingerprint": building.fingerprint,
                      "unresolved": mark.get("operation_id")},
        },
    }


def _confirm_request(building: Any, program: Any, digest: str,
                     stats: dict) -> dict:
    """A confirmation request. The human must see WHAT, not «apply this?»."""
    return {
        INPUT_REQUIRED: {
            "message": (
                f"Записать в «{building.document}» (Revit {building.revit_version}): "
                f"{stats['kinds_ru']} — всего {stats['writing_ops']} пишущих "
                f"операций из {stats['ops_total']}. "
                f"Подпись программы {digest[:12]}."),
            "schema": {
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "title": "Записать в модель",
                        "description": ("Отказ ничего не пишет и не считается "
                                        "ошибкой."),
                    },
                },
                "required": ["confirm"],
            },
            "state": {"building": building.handle, "digest": digest},
        },
    }


async def write_program(args: dict, *, confirmed: bool | None = None,
                        state: dict | None = None) -> dict:
    """`kir_write` — write a program into the open document.

    TWO MOVES BY CONSTRUCTION: the first writes nothing and returns a
    confirmation request; the second arrives with the human's answer.
    Consent is checked by the program's SIGNATURE: one thing was
    confirmed, and a different one arrived — refusal, not writing
    "something similar."
    """
    if confirmed is not None and type(confirmed) is not bool:
        return _refusal("confirmation_type", "подтверждение должно быть boolean, не строкой или числом",
                        effect="none", next_ru="передайте true или false; запись ещё не вызывалась")
    from kir.compiler import compile_program
    from kir.mcp import handles
    from kir.outcome import ExecutionState, execution_unconfirmed

    if not write_enabled():
        return _refusal(
            "write_off",
            f"запись выключена: переменная {WRITE_FLAG} не равна «on». "
            f"Это УМОЛЧАНИЕ, а не поломка — дверь, у которой много способов "
            f"открыться, открывается случайно",
            next_ru="офлайн-путь открыт целиком: `kir_compile` отдаёт C#, "
                    "который можно применить самому")
    try:
        transport = _transport()
    except ports.PortMissing as exc:
        return _refusal("no_transport", str(exc))
    try:
        building = handles.resolve(args.get("building"))
    except handles.HandleError as exc:
        return _refusal("handle", str(exc))

    program = args.get("program")
    if not isinstance(program, dict):
        return _refusal("form", "поле `program` обязано быть объектом программы",
                        next_ru="возьми программу у `kir_author`")

    digest = program_digest(program)
    out = compile_program(program, revit_version=building.revit_version)
    if not out.ok:
        return _refusal(
            "compile",
            "программа не скомпилировалась под версию документа "
            f"{building.revit_version} — в модель не ушло ничего",
            diagnostics=[str(d) for d in (out.diagnostics or [])][:20],
            handoff=out.handoff)

    if out.planned is None or out.planned.family.value != "write":
        return _refusal("write_family_required",
                        "kir_write принимает только типизированный план записи; query не отправлен")

    # 🔴 E6. THE SECOND DISPATCH DOES NOT GO OUT WHILE THE FIRST ONE'S
    # OUTCOME IS UNKNOWN. Stands BEFORE confirmation and before any round
    # trip outward: asking for consent to a write that will not go out
    # anyway would waste the human's decision. The argument and the
    # boundaries are at `UNRESOLVED`.
    #
    # No store — NO WRITE AT ALL, and so no promise that "a repeat will not
    # duplicate." The door refuses PRE-EFFECT and names THREE ways to
    # provide one: the same shape as the acceptance journal's ("an
    # unmeasured record is never a fallback").
    try:
        unresolved = _unresolved_write(building.fingerprint, digest=digest)
    except PendingStoreError as exc:
        return _refusal(
            "pending_store", f"{exc}",
            next_ru=("по умолчанию дверь держит эту запись в каталоге данных "
                     "пользователя (`$XDG_DATA_HOME/kir/mcp`, иначе "
                     "`~/.local/share/kir/mcp`; на Windows "
                     "`%LOCALAPPDATA%\\kir\\mcp`). Дай туда права либо "
                     "назови свой каталог: `KIR_MCP_PENDING_DIR=<путь>`. Без "
                     "него дверь не может обещать, что повтор после потери "
                     "ответа не удвоит запись, и потому не пишет"))
    if unresolved is not None:
        # A host that can ASK the runtime lifts the question without a human.
        verdict, recovered = await _resolve_by_lookup(
            transport, unresolved, out.planned, digest=digest, building=building)
        if verdict == "answer":
            return recovered
        if verdict == "proceed":
            unresolved = None
    if unresolved is not None:
        answer = state if isinstance(state, dict) else {}
        addressed = (answer.get("unresolved") == unresolved.get("operation_id")
                     and answer.get("fingerprint") == building.fingerprint)
        if not addressed:
            return _unresolved_request(building, unresolved, digest)
        if not confirmed:
            # 🔴 ОТКАЗ НАЗЫВАЛ ХОД, КОТОРОГО У АГЕНТА НЕТ (Р1.2, аудит H §3,
            # 13.09.2026). Здесь стояло «прочитай модель и позови `kir_write`
            # снова». Читать модель этой двери НЕЧЕМ: её палитра — семь
            # инструментов (`author, spec, compile, rehearse, open, write,
            # preview`, `kir/mcp/surface.py`), и ни один не рассказывает, что в
            # документе; `kir_open` отдаёт заголовок, версию и отпечаток, а сам
            # `kir_write` отказывает программе-запросу словами «query не
            # отправлен» (:676). Конституция требует от отказа две вещи —
            # причину И СЛЕДУЮЩИЙ ХОД; ход, названный несуществующим
            # инструментом, стоил ровно того же, что и молчание: агент либо
            # угадывает, либо зацикливается (замер на живом человеке 13.09:
            # `STREAM LOOP: рассуждение зациклилось (5 повторов)`).
            #
            # ЧТО НАЗВАНО ВМЕСТО. Ходов здесь ровно два, и оба существуют:
            # (1) ПОВТОРИТЬ `kir_write` — дверь заново поднимет вопрос человеку
            #     (`_unresolved_request`, :552), а человек ДОКУМЕНТ ВИДИТ и
            #     ответом снимет отметку;
            # (2) ответить на тот же вопрос `confirm: true` тем же `state` —
            #     это единственное, что отметку снимает (:722).
            # Отсутствие чтения названо вслух: молчать о нём значило бы
            # оставить агента искать несуществующую дверь.
            return {"ok": True, "kir": True, "wrote_nothing": True,
                    "declined": True,
                    "message_ru": ("исход предыдущей записи так и не проверен — "
                                   "в модель не ушло ничего"),
                    "next_ru": ("позови `kir_write` с той же программой ещё "
                                "раз: дверь снова спросит человека, а он "
                                "документ видит. Отметку снимает только ответ "
                                "`confirm: true` на этот вопрос — с тем же "
                                "`state`. " + NO_READER_RU)}
        # The answer cleared EXACTLY this marker. Consent to the write
        # itself is a separate question, and it is asked anew:
        # confirming "I checked" is not confirming "write it."
        _clear_unresolved(building.fingerprint,
                          operation_id=unresolved.get("operation_id"))
        confirmed, state = None, None

    scope = _policy.confirm_scope()
    # `off` — the operator lifted the question; `session` — consent is
    # held by the HANDLE, that is, for one document and for its lifetime,
    # not "forever."
    if confirmed is None and scope == "off":
        confirmed, state = True, {"building": building.handle, "digest": digest}
    elif confirmed is None and scope == "session" and building.extra.get("confirmed"):
        confirmed, state = True, {"building": building.handle, "digest": digest}
    if confirmed is None:
        return _confirm_request(building, program, digest,
                                write_summary(program))

    if not confirmed:
        return {"ok": True, "kir": True, "wrote_nothing": True,
                "declined": True,
                "message_ru": "человек отказал — в модель не ушло ничего",
                "next_ru": "поправь программу и позови `kir_write` снова"}

    # 🔴 CONSENT IS TIED TO THE PROGRAM, NOT TO THE CALL. Otherwise what
    # would end up confirmed is the DOOR, not what rides through it: a
    # client could repeat the call with a different program and the same
    # consent.
    # 🔴 `state` COMES FROM `json.loads` OF A FOREIGN STRING and can be
    # anything at all (review 02.09.2026): on `requestState = "[1]"` the
    # earlier text called `.get` on a list, caught an AttributeError, and
    # turned a CLEAN REFUSAL into "the server crashed." We coerce it to a
    # dict ONCE, before any reading.
    known = state if isinstance(state, dict) else {}
    stored = str(known.get("digest") or "—")
    if stored != digest:
        return _refusal(
            "confirmation_mismatch",
            "подтверждение относится к ДРУГОЙ программе: подпись согласия "
            # Both halves are cut the same way: a reader cannot compare
            # 64 characters against 12, and comparison is the whole point
            # of the message.
            f"{stored[:12]}… против {digest[:12]}…",
            next_ru="позови `kir_write` заново и подтверди ту программу, "
                    "которую действительно хочешь записать")
    if known.get("building") != building.handle:
        return _refusal(
            "confirmation_mismatch",
            "подтверждение относится к другому зданию",
            next_ru="позови `kir_write` заново для нужной ручки")

    # 🔴 CHECKING THE DOCUMENT BEFORE A WRITE. BOUGHT BY REVIEW ON
    # 02.09.2026, AND IT WAS A VIOLATION OF ITS OWN PROMISE: the header of
    # `handles.py` says the fingerprint was introduced "to let a mismatch
    # be noticed instead of writing blind" — and `write_program` never
    # once looked at it. The scenario was reproduced by execution: a human
    # opened "A.rvt", got a handle, switched the window to "B.rvt",
    # confirmed the caption "Write to A.rvt" — and the elements landed in
    # B.rvt.
    #
    # This house has already paid for the same shape before: the admin
    # door looked for the Revit window by enumeration and, with two
    # windows open, picked up SOMEONE ELSE'S title. Then the cost was a
    # read; here it is a write.
    #
    # AN EXTRA ROUND TRIP HERE IS CHEAPER THAN WRITING TO THE WRONG PLACE,
    # and this is not a matter of taste: a read is reversible, a write is
    # not.
    try:
        now = await transport.read(_PROBE_CS, timeout_ms=READ_TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001
        return _refusal("transport", f"{type(exc).__name__}: {exc}",
                        next_ru="сверка документа не состоялась — записи не было")
    current = _fingerprint(now)
    if current != building.fingerprint:
        title_now = (now or {}).get("title") if isinstance(now, dict) else None
        return _refusal(
            "document_changed",
            f"документ под ручкой сменился: подтверждали «{building.document}», "
            f"сейчас открыт «{title_now or 'неизвестно'}». В модель не ушло ничего",
            expected=building.fingerprint, got=current,
            next_ru="позови `kir_open` заново и подтверди запись для того "
                    "документа, который открыт сейчас")

    if scope == "session":
        building.extra["confirmed"] = True
    # 🔴 EVERYTHING THAT CAN FAIL BEFORE DISPATCH FAILS BEFORE THE
    # MARKER IS SET (review 06.09.2026, b1). The marker used to be set
    # first, and only then `transport.write` was read — with a provider
    # lacking that method, the door got an `AttributeError` AFTER the
    # marker was set, and the document stayed "unknown" because of a
    # dispatch that never happened. The method is fetched HERE: not
    # found — an honest refusal and no marker at all.
    writer = getattr(transport, "write", None)
    if not callable(writer):
        return _refusal(
            "no_transport",
            "поставщик транспорта не умеет писать: у него нет метода `write`",
            next_ru="это чтение-только среда; офлайн-путь открыт целиком")
    # The capability is asked by SIGNATURE, and once — before any dispatch.
    takes_operation_id = _writer_takes_operation_id(writer)
    # 🔴 THE RACE WINDOW IS CLOSED HERE, NOT BY HOPE (review 06.09.2026,
    # b3). Between the marker check above and this line there is an
    # `await` (the document check), meaning the event loop is entitled to
    # let a SECOND call in here. We reread the marker and set our own in
    # ONE synchronous chunk: between this check and the assignment there
    # is not a single `await`, so two dispatches to one document are
    # unconstructible, not merely "unlikely."
    # THE MARKER IS SET BEFORE DISPATCH, NOT AFTER A FAILURE. Setting it
    # in `except` would mean relying on our living to reach `except`: task
    # cancellation, `KeyboardInterrupt`, a process crash between the
    # dispatch and the handler — and the write went out with no trace
    # left. The write is durable and reaches the disk (`fsync`), so it
    # survives a server restart too.
    operation_id = str(uuid.uuid4())
    try:
        store = pending_path()
        records = _pending_load(store)
        racing = _blocking_records(records, fingerprint=building.fingerprint,
                                   digest=digest)
        if racing:
            return _refusal(
                "previous_write_unresolved",
                "в этот документ уже уходит запись, исход которой ещё не известен",
                next_ru="дождись её исхода и позови `kir_write` снова")
        records[operation_id] = {
            "operation_id": operation_id,
            "program_digest": digest,
            "fingerprint": building.fingerprint,
            "document": building.document,
            "csharp_sha256": hashlib.sha256(out.csharp.encode("utf-8")).hexdigest(),
            "ts": time.time(),
            "operation_id_sent": takes_operation_id,
        }
        _pending_save(store, records)
    except PendingStoreError as exc:
        return _refusal("pending_store", f"{exc}",
                        next_ru="назови каталог `KIR_MCP_PENDING_DIR` и повтори")
    try:
        receipt = (await writer(out.csharp, timeout_ms=WRITE_TIMEOUT_MS,
                                operation_id=operation_id)
                   if takes_operation_id
                   else await writer(out.csharp, timeout_ms=WRITE_TIMEOUT_MS))
    except Exception as exc:  # noqa: BLE001
        # The marker is NOT cleared: the outcome is unknown, and the next
        # write to this document must first ask the human (E6).
        return _refusal(
            "transport", f"{type(exc).__name__}: {exc}",
            wrote_nothing=False,
            outcome=execution_unconfirmed().to_dict(), intent_verified=False,
            next_ru=("исход НЕИЗВЕСТЕН: транспорт отказал после отправки, и "
                     "повтор вслепую удвоил бы то, что могло примениться. "
                     "Повтор через эту дверь и не уйдёт, пока исход не "
                     "подтверждён: следующий `kir_write` сам поднимет вопрос "
                     "«исход проверен?», и снимет отметку только ответ "
                     "`confirm: true`. " + NO_READER_RU))
    # Execution evidence is not independent acceptance. The common parser
    # checks every typed result and never infers rollback from an error name.
    from kir import bridge_result as _bridge

    assessment = _bridge.assess_write_result(receipt, out.planned)
    outcome = assessment.outcome
    # 🔴 AN ANSWER ARRIVED — THAT DOES NOT YET MEAN THE OUTCOME IS
    # KNOWN (review 06.09.2026, b2). The marker used to be cleared by the
    # MERE FACT of a return, and the `running_unknown` receipt — the one
    # that plainly says "I don't know" — opened the door to a second
    # dispatch: measured as `writes=2`. The marker is cleared exactly when
    # the outcome is NAMED: committed, rolled_back, not_started, or
    # read_completed. `unconfirmed` leaves it standing — the same case as
    # a lost response, only one that arrived as a word.
    if outcome.execution is not ExecutionState.UNCONFIRMED:
        try:
            _clear_unresolved(building.fingerprint, operation_id=operation_id)
        except PendingStoreError:
            # The outcome IS KNOWN, but clearing the record failed: the
            # next write will ask the human one extra time. Of two evils,
            # the reversible one was chosen.
            pass
    common = {
        "building": building.handle, "document": building.document,
        "revit_version": building.revit_version,
        "program_digest": digest, "receipt": receipt,
        "outcome": outcome.to_dict(), "intent_verified": False,
    }
    if assessment.ok:
        return {"ok": True, "kir": True, "wrote_nothing": False,
                "success_scope": "execution_contract", **common,
                "next_ru": "исполнение подтверждено; независимая проверка замысла ещё не выполнена"}

    failure = _bridge.extract_error(receipt)
    layer = failure["layer"] if failure is not None else {}
    marker = str(failure["error"]) if failure is not None else "результат неполон"
    detail = str(layer.get("message") or layer.get("message_ru") or
                 layer.get("violations") or assessment.violations or
                 (assessment.diagnostic or {}).get("detail") or "")[:400]
    rolled_back = outcome.execution is ExecutionState.ROLLED_BACK
    if rolled_back:
        suffix = "; транзакция откатена по явной квитанции"
        next_ru = "поправь программу по отказу; повтор допустим после подтверждённого отката"
    elif outcome.committed:
        suffix = "; commit подтверждён, но результат не принят"
        next_ru = ("исправь расхождения новым планом по названным "
                   "`violations`; повтор ЭТОЙ записи запрещён. " + NO_READER_RU)
    else:
        suffix = "; исход НЕИЗВЕСТЕН, откат не подтверждён"
        next_ru = ("не повторяй вслепую — это удвоит то, что могло "
                   "примениться: следующий `kir_write` сам поднимет вопрос "
                   "«исход проверен?», и снимет отметку только ответ "
                   "`confirm: true`. " + NO_READER_RU)
    return _refusal(
        "write_refused" if failure is not None and not _bridge.is_unconfirmed(receipt)
        else "execution_unknown" if not outcome.committed else "execution_incomplete",
        f"{marker}: {detail}{suffix}", wrote_nothing=rolled_back,
        diagnostics=[assessment.diagnostic] if assessment.diagnostic else [],
        violations=list(assessment.violations), next_ru=next_ru, **common)
