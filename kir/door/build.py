"""`kir_build(source)` — the ONLY door that changes the building.

🔴 THIS IS NOT A NEW RUNTIME. Every phase already existed and was already
proven; what is new is that they stopped being SEPARATE BUTTONS. Measured
13.09: the MCP door offered seven tools of which five were phases of one
act (`kir_author`, `kir_compile`, `kir_rehearse`, `kir_preview`,
`kir_write`), and the agent had to know the order. The environment knows the
order; the agent should not have to.

THE PHASES, IN ORDER, AND WHOSE WORK EACH ONE IS:

  1. sandbox     `kir/sandbox.py::execute_author_script` — the author's
                 python becomes IR. STRICT policy only (see below).
  2. rehearsal   `kir/rehearsal.py::rehearse` — what will NOT be checked.
                 UNCONDITIONAL: the agent does not know the word
                 "репетиция" and is not obliged to. Bought by a measurement
                 of 18-19.08: two of three big failures on a live tower were
                 not geometry errors but obligations that never ran, and
                 silence about it.
  3. compile     `kir/compiler.py::compile_program` per version from `ctx`.
                 The agent is not asked which Revit it is talking to — the
                 document knows.
  4. write       the executor PORT (`ctx.executor.execute`). Offline that is
                 S's `kir/project_pack.py::OfflineExecutor`, which says in
                 every answer that it is not Revit.
  5. receipt     words, addresses, what stayed unchecked, and `next`.

🔴 WHY THE STRICT PROFILE IS A REFUSAL AND NOT A DEFAULT. ОПР-17, measured:
in the WEAKENED profile the network is CONNECTED, `os.execv('/bin/echo')`
replaces the interpreter, and `execve` is absent from seccomp (`grep -n
execve kir/sandbox.py` -> 0). A door that executes somebody else's python
has no right to run weakened, and "no right" has to be a number, not a
comment. Gate G6.
"""
from __future__ import annotations

from typing import Any

from kir.door.registry import Ctx, Refusal

__all__ = ["kir_build", "is_strict_policy"]

#: The versions a program is compiled against when the document did not say.
#: Two, not one: "скомпилировалось" without a named version means nothing
#: (SPEC 11.2), and these two are the ones the live receipts of 13.09 were
#: taken on (ДОК-A1: Revit 2023; ДОК-B9: 2023 and 2026).
DEFAULT_VERSIONS = ("2023", "2026")


#: The sandbox's code for "no program, but the script ANSWERED" — the third
#: kind of turn. Taken from the carrier (`kir/diag.py::SANDBOX_RECON`), not
#: spelled as a literal: a literal would drift from `diag` silently.
try:
    from kir.diag import SANDBOX_RECON as _RECON_CODE
except Exception:  # noqa: BLE001 — an unreadable diag must not hide the kind
    _RECON_CODE = "KIR-B013"


def _recon(authored: Any) -> dict:
    """A reconnaissance turn: the agent asked the language and got an answer.

    `ok: True` with `built: False` — the two facts are independent, and
    conflating them is what made an answer look like a failure. `next` is
    `kir_build`: the agent now has what it asked for.

    `help_in_script` is surfaced for a reason of BUDGET: a `spec()` call inside
    the script costs nothing against the expert's `help_calls` ceiling (4, from
    M5), because it never went through `kir_read`. An expert charged twice for
    one question would spend its budget on arithmetic.
    """
    said = (getattr(authored, "stdout", "") or "").strip()
    reads = getattr(authored, "course_reads", None)
    return {"ok": True, "built": False, "recon": True, "wrote_nothing": True,
            "ops": 0,
            "words": (said if said else
                      "Скрипт ответил, но ничего не напечатал и программы не собрал."),
            "help_in_script": reads,
            "next": {"do": "kir_build"}}


def is_strict_policy(policy: Any) -> bool:
    """Doubt means NO. A policy we cannot read is not a policy we trust."""
    try:
        return (policy.filesystem_isolation is True
                and str(getattr(policy, "network", "")) == "required")
    except Exception:  # noqa: BLE001 — unreadable policy is not a strict one
        return False


def kir_build(args: dict, ctx: Ctx, *, policy: Any = None) -> dict:
    """Five phases, one call, one receipt. Never raises into the turn."""
    from kir.sandbox import DEFAULT_POLICY

    source = args.get("source")
    if not isinstance(source, str) or not source.strip():
        return Refusal("source_required",
                       "поле `source` обязано быть непустым питоном против `kir.dsl`",
                       next="kir_read").as_dict()

    effective = DEFAULT_POLICY if policy is None else policy
    if not is_strict_policy(effective):
        # BEFORE any execution: the refusal is about what would have run.
        return Refusal(
            "weak_sandbox",
            "дверь не исполняет исходник в ослабленном профиле песочницы: "
            "в нём сеть достижима и подмена интерпретатора не запрещена. "
            "Это условие двери, а не поломка твоей программы",
            next="question_to_lead" if ctx.role == "expert" else "ask_user",
        ).as_dict()

    # ── phase 1: the author's python becomes IR ──────────────────────────
    try:
        from kir.sandbox import execute_author_script
        authored = execute_author_script(source, policy=effective)
    except Exception as exc:  # noqa: BLE001 — a phase may not break the turn
        return Refusal("author_failed", f"песочница не отработала: {exc}",
                       next="kir_build").as_dict()
    if not authored.ok:
        r = authored.refusal
        code = getattr(r, "code", None)
        # 🔴 RECONNAISSANCE IS NOT A REFUSAL, AND THE TREE SAYS SO IN WORDS.
        # `kir/diag.py` about `KIR-B013`: "`refused` is no longer true, and no
        # `err` block is set — recon is not an error, it is an answer to the
        # question asked." The sandbox returns `ok=False` because there is no
        # program and no record evidence; that is NOT a fault.
        #
        # Found by a LIVE model, 13.09.2026 (S's M5 run through this door): the
        # door carried a non-refusal inside a refusal envelope. Not cosmetic —
        # asking the language FROM INSIDE THE SCRIPT is the cheapest move an
        # agent has (`spec("create_wall")`, answer in this same receipt's
        # stdout, no second trip), and this door was punishing it.
        if code == _RECON_CODE:
            return _recon(authored)
        out = Refusal(code if isinstance(code, str) and code else "author_failed",
                      getattr(r, "message_ru", str(r)), next="kir_build").as_dict()
        # The sandbox already points at the line in the MODEL's own source.
        # Keep it: a traceback the agent recognises is worth more than prose.
        out["line"] = getattr(r, "line", None)
        out["source_line"] = getattr(r, "line_text", None)
        return out
    program = authored.to_program()
    op_count = len(authored.ops)

    # ── phase 2: rehearsal, unconditional ────────────────────────────────
    unchecked = _rehearsal_words(program)

    # ── phase 3: compile per version ─────────────────────────────────────
    versions = tuple(ctx.versions or DEFAULT_VERSIONS)
    compiled: dict[str, bool] = {}
    diagnostics: list[str] = []
    for version in versions:
        ok, diags = _compile_one(program, version)
        compiled[version] = ok
        if not ok:
            diagnostics.extend(f"{version}: {d}" for d in diags[:5])
    if not all(compiled.values()):
        bad = ", ".join(v for v, ok in compiled.items() if not ok)
        out = Refusal("compile_failed",
                      f"программа не скомпилировалась под {bad} — "
                      f"в модель не ушло ничего",
                      next="kir_build").as_dict()
        out["diagnostics"] = diagnostics[:20]
        out["ops"] = op_count
        out["trace"] = _trace(program, ctx, "refused_pre_effect")
        return out

    # ── preview stops here, and says so ──────────────────────────────────
    if args.get("preview") is True:
        return {"ok": True, "built": False, "wrote_nothing": True,
                "ops": op_count,
                "words": (f"Показано человеку: {op_count} операций, "
                          f"компилируется под {', '.join(versions)}. "
                          f"В документ не записано ничего."),
                "unchecked": unchecked,
                "next": {"do": "show_preview" if ctx.role == "lead" else "kir_build"}}

    # ── phase 4: write through the executor PORT ─────────────────────────
    if ctx.executor is None:
        out = Refusal("no_executor",
                      "исполнителя нет: дверь не к чему подключить, "
                      "и потому ничего не записано",
                      next="question_to_lead" if ctx.role == "expert" else "ask_user",
                      ).as_dict()
        out["trace"] = _trace(program, ctx, "refused_pre_effect")
        return out
    try:
        answer = ctx.executor.execute(ctx.link_key, program)
    except Exception as exc:  # noqa: BLE001
        # 🔴 THE LOST ANSWER. The dispatch went out and we do not know its
        # outcome — that is `unknown`, not a failure, and it is exactly the
        # case ДОК-C4's twenty tests guard.
        out = Refusal("execute_failed", f"исполнитель отказал: {exc}",
                      next="kir_read").as_dict()
        out["trace"] = _trace(program, ctx, "unknown")
        return out

    # ── phase 5: receipt in WORDS ────────────────────────────────────────
    return _receipt(answer, program, op_count, versions, unchecked, ctx)


def _rehearsal_words(program: dict) -> str:
    """What nobody will check, as one sentence. Absence is also an answer and
    it is said out loud: silence here is exactly the defect the rehearsal was
    bought to close."""
    try:
        from kir.rehearsal import rehearse
        block = rehearse(program)
    except Exception as exc:  # noqa: BLE001
        return f"репетиция не отработала ({exc}) — считай, что не проверено НИЧЕГО"
    if not isinstance(block, dict) or not block:
        return "репетиция ничего не выделила: проверено будет всё заявленное"
    axes = block.get("unwitnessed") or block.get("axes") or []
    if not axes:
        return "репетиция ничего не выделила: проверено будет всё заявленное"
    return "этого никто не проверит: " + ", ".join(str(a) for a in list(axes)[:8])


def _compile_one(program: dict, version: str) -> tuple[bool, list[str]]:
    try:
        from kir.compiler import compile_program
        out = compile_program(program, revit_version=version)
    except Exception as exc:  # noqa: BLE001
        return False, [str(exc)]
    diags = [str(d) for d in (getattr(out, "diagnostics", None) or [])]
    return bool(getattr(out, "ok", False)), diags


#: The trace's schema. W puts THIS into the project store; the door does not
#: grow a store of its own — `kir/mcp/live.py` says why in its own header:
#: "the door has no store, and grows none, whose consistency it would have to
#: answer for."
TRACE_SCHEMA = "kir-door-write-trace/1"

#: The only three legal states, and `unknown` is one of them ON PURPOSE.
#: ДОК-A18: a door answered `started: true` twice and produced neither status
#: nor catalogue — the class «ложно-зелёная квитанция». A receipt must be able
#: to say "I do not know the outcome" and still be a receipt.
TRACE_STATES = ("committed", "unknown", "refused_pre_effect")


def _program_digest(program: dict) -> str:
    """One canonical hash of the program, from the carrier that already
    exists (`operations.protocol.canonical_payload_hash`) — a second hashing
    of the same fact is this file's named defect."""
    try:
        from kir.operations.protocol import canonical_payload_hash
        return canonical_payload_hash("kir_build", {"program": program})
    except Exception:  # noqa: BLE001
        import hashlib
        import json
        blob = json.dumps(program, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()


def _trace(program: dict, ctx: Any, state: str, *,
           resolved_by: str | None = None) -> dict:
    """The write's identity, DERIVED and never random.

    🔴 A RANDOM id GIVES A SECOND EFFECT ON REPEAT, and the product's bridge
    already says why it derives: "replaying the same accepted artifact can then
    reconcile or return unknown, never acquire a fresh random operation id and
    execute twice." Same law here, same carriers:
    `derive_action_id(turn_id, tool_call_id, tool_name)` →
    `derive_operation_id(action_id, method, payload_hash)`.

    🔴 THE PAIR «document fingerprint × program digest» TRAVELS IN THE
    RECEIPT, not only in a file. That is the pair `kir/mcp/live.py`'s
    `_blocking_records(records, fingerprint=…, digest=…)` searches by, so W can
    put the trace into the store without parsing somebody else's format.

    `attempt` and `resolved_by` are what make the migration of ДОК-C4's twenty
    tests CHECKABLE: they prove "handed back the SAME receipt" rather than
    "went out a second time".
    """
    if state not in TRACE_STATES:
        raise ValueError(f"unknown trace state {state!r}; known: {TRACE_STATES}")
    digest = _program_digest(program)
    fingerprint = str(getattr(ctx, "document_fingerprint", "") or "") or None
    return {"schema": TRACE_SCHEMA,
            "operation_id": _operation_id(digest, ctx),
            "document_fingerprint": fingerprint,
            "program_digest": digest,
            "state": state,
            "attempt": int(getattr(ctx, "attempt", 1) or 1),
            "resolved_by": resolved_by}


def _operation_id(digest: str, ctx: Any) -> str:
    """Derived from (turn, tool call, tool name, method, payload) — so the same
    program in the same turn yields the same id, and a repeat can reconcile."""
    try:
        from kir.operations.protocol import (derive_action_id,
                                             derive_operation_id)
        action = derive_action_id(str(getattr(ctx, "turn_id", "") or "door"),
                                 str(getattr(ctx, "tool_call_id", "") or "1"),
                                 "kir_build")
        return derive_operation_id(action, "kir_build", digest)
    except Exception:  # noqa: BLE001 — a derivation we cannot run is named
        import hashlib
        seed = f"door|{getattr(ctx, 'turn_id', '')}|{getattr(ctx, 'tool_call_id', '')}|{digest}"
        return hashlib.sha256(seed.encode()).hexdigest()


def _addresses_of(payload: dict) -> dict:
    """op id -> the identity the executor handed back.

    Reads `outputs` — the shape S's executor and the live receipt share
    (`live-20260913-slice-receipt.json`), so the same reader works against
    both and the door does not learn one shape offline and another live.
    """
    out: dict = {}
    rows = payload.get("outputs")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = row.get("output_id")
            ident = row.get("element_identity")
            uid = ident.get("unique_id") if isinstance(ident, dict) else None
            if isinstance(key, str) and isinstance(uid, str):
                out[key] = uid
    if out:
        return out
    fallback = payload.get("element_map") or payload.get("identities")
    return fallback if isinstance(fallback, dict) else {}


def _receipt(answer: Any, program: dict, op_count: int,
             versions: tuple[str, ...], unchecked: str, ctx: Ctx) -> dict:
    """The receipt the agent reads. Words first, addresses beside them.

    🔴 ADDRESSES ARE NAMED OR THEIR ABSENCE IS. The product's receipt already
    learned this the hard way and says it in words when the map fails to
    assemble ("адреса построенных элементов в этой квитанции НЕ НАЗВАНЫ — это
    не значит, что элементов нет"). Same law here: a missing map is a stated
    fact, not an empty dict.
    """
    payload = answer if isinstance(answer, dict) else {}
    ok = bool(payload.get("ok", True))
    addresses = _addresses_of(payload)
    created = payload.get("created")
    if not isinstance(created, int):
        created = len(addresses)
    # 🔴 A FAKE EXECUTOR MUST NOT PASS FOR A LIVE ONE. S's `OfflineExecutor`
    # stamps itself (`executor: "offline-fake"`) and keeps
    # `native_execution` out of its claims on purpose. The receipt repeats
    # that stamp in WORDS, because a receipt that reads the same live and
    # offline is how «ложно-зелёная квитанция» happened (ДОК-A18).
    native = str(payload.get("native_execution") or payload.get("executor") or "") or None

    if not ok:
        # The executor answered and said no. Whether the effect landed is
        # its business to state: only an explicit «ничего не записано»
        # earns `refused_pre_effect`; silence about it is `unknown`.
        pre_effect = (payload.get("wrote_nothing") is True
                      or str(payload.get("effect", "")) == "none")
        out = Refusal("execute_failed",
                      str(payload.get("message_ru")
                          or "исполнитель не подтвердил запись"),
                      next="kir_read").as_dict()
        out["ops"] = op_count
        out["trace"] = _trace(program, ctx,
                              "refused_pre_effect" if pre_effect else "unknown")
        return out

    words = (f"Построено: операций {op_count}, "
             f"выходов с адресом {created}. "
             f"Компилируется под {', '.join(versions)}.")
    if native and native not in ("ok", "native"):
        # The offline executor says this of itself, and the receipt repeats
        # it rather than letting a fake pass for a live one.
        words += f" 🔴 Настоящего Ревита не было, исполнитель: {native}."
    if not addresses:
        words += (" Адреса построенного в этой квитанции НЕ НАЗВАНЫ — "
                  "это не значит, что выходов нет.")

    return {"ok": True, "built": True, "ops": op_count,
            "trace": _trace(program, ctx, "committed", resolved_by="answer"),
            "receipt_digest": payload.get("receipt_digest"),
            "words": words,
            "addresses": addresses if isinstance(addresses, dict) else {},
            "unchecked": unchecked,
            "compiled": {v: True for v in versions},
            "next": None}
