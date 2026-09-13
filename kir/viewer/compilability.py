"""A CONTINUOUS COMPILABILITY INDICATOR — and the full list of what it
does NOT see.

WHY. The engineer sits in the chat for three hours, the building lives in
the graph, and EXACTLY ONE compilation goes to Revit — at the very end.
Finding out in the third hour that the building doesn't compile means
losing three hours. Hence an estimate is needed that updates on every
program and costs close to nothing.

WHAT THIS COSTS (measurement 10.08.2026, prod venv, `compiler.plan_program`
on correct `create_wall` programs):

| ops in the program | time    |
|--------------------:|--------:|
|                    1 | 0.13 ms |
|                    5 | 0.44 ms |
|                   10 | 0.79 ms |
|                   20 | 1.48 ms |
|          300 (bulk)  | 21.2 ms |
|   refusal on budget | 0.04 ms |

That is, an author's program is checked in ONE AND A HALF MILLISECONDS,
and this is pure Python throughout: not a single network call, not a
single call to Roslyn, not a single call to Revit. The indicator can be
recomputed on every publish to the journal and go unnoticed in the turn's
budget.

────────────────────────────────────────────────────────────────────────────
WHAT THE INDICATOR CHECKS (measured, not assumed)
────────────────────────────────────────────────────────────────────────────
Everything `compiler.plan_program` does before emitting C#:

* parameter TYPES against the registry (`spec.OPS`) — `KIR-T001` and its
  relatives. Measured: `{"by":"name","name":"L1"}` instead of
  `{"by":"name","value":"L1"}` is caught here, not in Revit;
* BUDGETS. `MAX_OPS_PER_PROGRAM` for an AUTHOR program (on this tree
  **100**, measured 17.08.2026; the literal "20" here had gone stale and
  was removed) and `MAX_BULK_OPS` for a rebuild chunk — `KIR-L001`.
  Measured: 21 ops get refused in 0.04 ms, so does 301 in bulk mode;
* THE REFERENCE DAG: `ref` must point to an EARLIER op of the same
  program (`KIR-L003`). This is the very rule that makes a door without a
  host wall not "incomplete" but invalid;
* SOLO OPS: an operation that needs its own transaction (`KIR-L002`,
  `compiler.PLAN_SOLO_OP` — the staircase);
* the program's ENVELOPE: `ir_version` (`KIR-P004`), the shape of `ops`;
* THE CEILING AFTER MACROS: `MAX_VALIDATED_OPS`.

Plus — ONLY when a snapshot of the document's types sits in the session
journal (`SessionJournal.sections`, put there by
`plan_stream.remember_sections`) — SELECTOR GROUNDING: whether
`{"by":"name","value":"…"}` resolves to a real level/type of this
document. Without the snapshot, grounding is NOT CHECKED, and this is
stated by the field `grounding: "not_checked"`, not by silence.

────────────────────────────────────────────────────────────────────────────
WHAT THE INDICATOR DOES NOT CHECK — AND THIS IS PART OF ITS ANSWER, NOT A
FOOTNOTE
────────────────────────────────────────────────────────────────────────────
An indicator that stays silent about its own blindness is worse than
having none: a green light that doesn't know it never looked is exactly
the "a witness signs an axis it never read" defect that forced six checks
to be redone on 10.08. That's why the list travels in EVERY response, in
the `blind` field, and the viewer prints it next to the light.

1. **C# DOES NOT COMPILE.** The real gate runs through a live Roslyn
   service against real `RevitAPI.dll` files of six versions. There is no
   emission here at all. The class of refusals that slips past: `CS0117`,
   `CS0012`, `CS0136`, `CS0039` — and this is exactly how the tags stage
   died (`CS0012: ISet<>`).
2. **The six-version API surface is not consulted.** The arbiter is
   `data/api_surface/api_signatures_*.json`, captured by reflection off
   the DLLs. A program that is legal by types may call a member that
   doesn't exist in the target version.
3. **Assembly reference closure is not checked**
   (`bridge_reference_closure`): emitted C# referencing an assembly that
   isn't in the deployed plugin is invisible from here. This guard was not
   wired to anything from 09.08 to 10.08, and nobody noticed.
4. **Acceptance and the witness do not run.** "Will compile" ≠ "will
   build" ≠ "built what was asked for." The axis for which nobody promised
   to check is counted by `serving._unwitnessed_axes`, and it is not here.
5. **The translation certificate is not consulted**
   (`KUKAI_IR_TRANSLATION_CERT` isn't set at all in prod — measurement of
   prod flags, 10.08).
6. **Clashes are not searched for.** 67.7 s on the largest building; a
   full search on every change is impossible by construction.
7. **`design_check` does not run** — that is a judgment about the
   BUILDING, not about the program's text.
8. **The live document is not consulted.** A level or type may have
   disappeared in Revit between the publish and the button; offline, this
   is invisible.
9. **Order between programs is not checked.** Each program is judged
   SEPARATELY, because the program is the transaction. A batch where the
   second program relies on the result of the first is legal here, and
   that is correct, but "the whole batch is applicable to the current
   document" is not what is stated here.
10. **The budget does not carry over between programs.** Twenty programs
    of twenty ops each — all twenty are legal; this indicator does not
    ask "isn't that a lot for one turn."

────────────────────────────────────────────────────────────────────────────
A TRI-STATE, NOT A LIGHT BULB
────────────────────────────────────────────────────────────────────────────
By the same law as `hulls_coincide`, `Judged.proven`, and
`serving._unwitnessed_axes`: `ok` — all programs passed the named checks;
`refused` — there is a refusal, and it is named by code and text;
`unknown` — there was nothing to judge by (the registry didn't come up, no
journal). **`unknown` is NOT "everything is fine,"** and the viewer must
color it grey, not green.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = ("COMPILABILITY_SCHEMA", "BLIND", "Verdict", "check_programs",
           "check_session")

COMPILABILITY_SCHEMA = "kir-compilability/1"

#: The blindness list as DATA, not as prose: it travels in every response
#: and is printed by the viewer. The order goes from the most expensive
#: miss to the cheapest.
BLIND: tuple[str, ...] = (
    "C# не компилируется: живой Roslyn против настоящих RevitAPI.dll шести "
    "версий здесь не вызывается (CS0117/CS0012/CS0136/CS0039 проходят мимо)",
    "поверхность API по версиям не спрашивается (api_signatures_*.json)",
    "замыкание ссылок сборок не проверяется (bridge_reference_closure)",
    "приёмка и свидетель не запускаются: «скомпилируется» ≠ «построится»",
    "сертификат перевода не спрашивается",
    "клеши не ищутся (67.7 с на самом большом здании — непрерывно невозможно)",
    "design_check не запускается: это суждение о здании, а не о тексте",
    "живой документ не спрашивается: уровень или тип могли исчезнуть в Revit",
    "программы судятся ПООДИНОЧКЕ — применимость всей пачки к документу не "
    "проверяется",
    "бюджет опов не суммируется между программами",
)


@dataclass
class Verdict:
    """The indicator's response. `state` is a tri-state, `blind` is
    always complete."""

    state: str = "unknown"          # ok | refused | unknown
    programs: int = 0
    ops: int = 0
    checked: int = 0
    refusals: list[dict[str, Any]] = field(default_factory=list)
    grounding: str = "not_checked"  # ok | refused | not_checked
    grounding_note: str = ""
    reason: str = ""
    elapsed_ms: float = 0.0
    budgets: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPILABILITY_SCHEMA,
            "state": self.state,
            "state_ru": {"ok": "компилируется (в пределах названных проверок)",
                         "refused": "НЕ компилируется: есть названный отказ",
                         "unknown": "судить нечем — это НЕ «всё хорошо»"}[self.state],
            "programs": self.programs,
            "ops": self.ops,
            "checked_programs": self.checked,
            "refusals": self.refusals[:20],
            "refusals_total": len(self.refusals),
            "grounding": self.grounding,
            "grounding_note": self.grounding_note,
            "reason": self.reason,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "budgets": self.budgets,
            "blind": list(BLIND),
        }


def _budgets() -> dict[str, int]:
    from kir.compiler import (MAX_BULK_OPS, MAX_OPS_PER_PROGRAM,
                                   MAX_VALIDATED_OPS)
    return {"authored": MAX_OPS_PER_PROGRAM, "internal_bulk": MAX_BULK_OPS,
            "post_macro": MAX_VALIDATED_OPS}


def _as_program(item: Any) -> dict[str, Any] | None:
    """A program arrives in three shapes: an envelope, a list of ops, a
    `ProgramRecord`.

    The envelope is completed HERE, and only `ir_version`: the journal
    already stores expanded operations (`PlannedProgram.to_ops()`), and it
    does not store the IR version at all — that belongs to the envelope,
    not to the program. Completing anything else would mean judging
    something other than what will actually get built.
    """
    ops: Any
    if hasattr(item, "ops"):
        ops = list(item.ops)
    elif isinstance(item, Mapping):
        ops = list(item.get("ops") or ())
        if not ops:
            return None
        env = {k: v for k, v in item.items() if k != "ops"}
        env["ops"] = ops
        env.setdefault("ir_version", "1.0")
        return env
    elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
        ops = list(item)
    else:
        return None
    if not ops:
        return None
    return {"ir_version": "1.0", "ops": [dict(o) for o in ops
                                         if isinstance(o, Mapping)]}


def check_programs(programs: Sequence[Any], *, bulk: bool = False,
                   snapshot: Any = None) -> Verdict:
    """Judge a batch. Never raises an exception — the indicator has no
    right to cost the very turn it exists for."""
    started = time.perf_counter()
    verdict = Verdict()
    try:
        from kir import compiler
        from kir.diag import KirRefusal
        verdict.budgets = _budgets()
    except Exception as exc:  # noqa: BLE001 — the registry belongs to someone else
        verdict.state = "unknown"
        verdict.reason = f"компилятор не поднялся: {type(exc).__name__}"
        verdict.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return verdict

    envelopes = [env for env in (_as_program(p) for p in programs)
                 if env is not None]
    verdict.programs = len(envelopes)
    verdict.ops = sum(len(env["ops"]) for env in envelopes)
    if not envelopes:
        verdict.state = "unknown"
        verdict.reason = "в журнале нет ни одной программы"
        verdict.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return verdict

    planned: list[Any] = []
    for index, env in enumerate(envelopes):
        try:
            planned.append(compiler.plan_program(env, bulk=bulk))
            verdict.checked += 1
        except KirRefusal as refusal:
            verdict.refusals.append({
                "program": index,
                "ops": len(env["ops"]),
                # The COMPILER's diagnostic, word for word. Paraphrasing
                # it in our own words would mean setting up a second
                # source of truth about why the program doesn't compile.
                "text": str(refusal)[:400],
                "codes": sorted({d.code for d in getattr(refusal, "diagnostics", ())
                                 if getattr(d, "code", None)}),
            })
        except Exception as exc:  # noqa: BLE001 — an unexpected failure is still a failure
            verdict.refusals.append({
                "program": index, "ops": len(env["ops"]),
                "text": f"{type(exc).__name__}: {str(exc)[:300]}",
                "codes": [], "unexpected": True})

    verdict.state = "refused" if verdict.refusals else "ok"

    # ── GROUNDING, and only if there's something to ground against. A
    #    snapshot of the document's types is put into the journal by
    #    `plan_stream.remember_sections`; without it there's nothing for a
    #    `by=name` selector to be checked against, and pretending it was
    #    checked is not allowed.
    if snapshot:
        try:
            from kir import ground as _ground
            bad = 0
            for plan in planned:
                ops = plan.to_ops() if hasattr(plan, "to_ops") else plan
                try:
                    _ground.ground(list(ops), snapshot)
                except Exception:  # noqa: BLE001
                    bad += 1
            if not planned:
                # 🔴 "0 OUT OF 0 GROUNDED" IS NOT "ok" (found by the
                # coverage measurement on 30.08.2026). When the plan was
                # refused, `planned` is empty, the loop above performs NOT
                # A SINGLE check, yet the field declared `ok` with the
                # note "0 programs grounded." Going green having checked
                # nothing is the same kind of defect as F-326 below.
                verdict.grounding = "not_checked"
                verdict.grounding_note = (
                    "заземлять было нечего: ни одна программа не спланировалась, "
                    "селекторы by=name НЕ ПРОВЕРЕНЫ")
            else:
                verdict.grounding = "refused" if bad else "ok"
                verdict.grounding_note = (
                    f"{bad} из {len(planned)} программ не заземлились на снимок "
                    f"типов документа" if bad else
                    f"{len(planned)} программ заземлились на снимок "
                    f"типов документа")
        except Exception as exc:  # noqa: BLE001
            verdict.grounding = "not_checked"
            verdict.grounding_note = (
                f"грундинг не запустился: {type(exc).__name__} — селекторы НЕ "
                "проверены")
    else:
        verdict.grounding_note = (
            "снимка типов документа в журнале нет: сводятся ли селекторы "
            "by=name к реальным уровням и типам, НЕ ПРОВЕРЕНО")

    # 🔴 GROUNDING IS A NAMED CHECK, AND ITS REFUSAL MUST CHANGE THE
    # VERDICT (F-326, 29.08.2026). `state` was set BEFORE grounding and
    # was never revisited afterward: a program referencing a missing
    # level or type showed the main GREEN verdict "compiles," even though
    # a snapshot of its OWN document refutes it.
    #
    # COVERAGE MEASUREMENT 30.08.2026 across the corpus: 62 parses out of
    # 64 (11 buildings out of 12) gave `state=ok` with `grounding=refused`.
    # On `clash_final`, `ground` itself returns 441 diagnostics, the
    # first being KIR-G101 «levels: «Этаж 2» не найден», «wall_types:
    # «Типовой - 200мм» не найден».
    #
    # No new state is introduced: `refused` already means "there is a
    # NAMED refusal," and the grounding refusal is named and sits in
    # `grounding_note`.
    if verdict.grounding == "refused" and verdict.state == "ok":
        verdict.state = "refused"
    verdict.elapsed_ms = (time.perf_counter() - started) * 1000.0
    return verdict


def check_session(device_id: str | None, doc_key: str = "") -> dict[str, Any]:
    """The indicator for a LIVE session. Reads `kir.live.journal` and
    nothing else.

    There is deliberately no program storage of its own here: the session
    journal already is the building's source code, and a second instance
    of it would drift from the first silently.
    """
    try:
        from kir.live import journal as _journal
    except Exception as exc:  # noqa: BLE001
        return Verdict(state="unknown",
                       reason=f"журнал не поднялся: {type(exc).__name__}"
                       ).to_dict()
    session = _journal.get(_journal.key_for(device_id, doc_key))
    if session is None:
        return Verdict(state="unknown",
                       reason="сессии с таким ключом в журнале нет").to_dict()
    verdict = check_programs(list(session.records),
                             snapshot=getattr(session, "sections", None))
    out = verdict.to_dict()
    out["session"] = {"programs": len(session.records),
                      "next_seq": session.next_seq,
                      "evicted": session.programs_evicted}
    # EVICTION MUST BE NAMED. The journal is bounded in the number of
    # programs; an indicator that judged 200 programs out of 500 and said
    # "ok" would be lying by exactly the same omission that the preview
    # census was written against.
    if session.programs_evicted:
        out["reason"] = (
            f"судимы только программы, оставшиеся в журнале: "
            f"{session.programs_evicted} вытеснено и НЕ ПРОВЕРЕНО")
        # 🔴 THE CAUSE WAS THERE, AND THE STATE STAYED GREEN (F-327,
        # 29.08.2026). The comment above literally calls the verdict "ok"
        # over an incomplete batch a lie — and `state` was not touched by
        # it: the tail got planned, the indicator said "compiles," while a
        # bad program could sit in the evicted BEGINNING of the history.
        #
        # `unknown`, not `refused`: we did not find a refusal, we could
        # not LOOK. That is exactly what the state dictionary says —
        # "nothing to judge by, this is NOT 'everything is fine.'" A found
        # refusal is stronger than not knowing and is never downgraded: a
        # fact stays a fact.
        if out.get("state") == "ok":
            out["state"] = "unknown"
            out["state_ru"] = "судить нечем — это НЕ «всё хорошо»"
    return out
