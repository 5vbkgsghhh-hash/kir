"""Guards `delta.content` against a confirmed live failure mode: a provider
serving a model (e.g. MiMo/xiaomi via one of its pinned OpenRouter backends)
fails to translate the model's OWN native function-calling syntax into the
structured `tool_calls` API field, so it leaks into plain streamed text
instead. Live-confirmed 2026-07-12: a real, well-formed roof-creation
`execute_revit_code` call came through as raw `<｜DSML｜tool_calls>...`
markup in `delta.content` — the user saw XML+C# dumped into chat, and
nothing was ever executed (the roof was never created).

Single reusable gate: `delta.content` reaches the user from more than one
place in client.py's streaming loops (the main tool-round loop and
`_forced_synthesis`) — write the detection once here, call it from both, so
a fix can't silently miss a call site.

Zero added latency by construction: no sleeps, no wall-clock waits. A
suspect buffer is capped by SIZE, not time — held tokens were already being
generated at the model's own pace regardless of this guard; buffering only
changes what gets displayed, never how fast tokens arrive.

Chunk-boundary safe: streamed deltas can split a trigger sequence across two
or more chunks (`<｜DS` then `ML｜invoke...`) — this is fed character by
character internally so a split trigger is never mistaken for plain text.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

# Seeds observed leaking live (the two-delimiter unicode/pipe family used by
# DSML), plus generic literal variants of the same family of special-token
# function-call delimiters other providers/models are known to use. Extend
# on EVIDENCE (a real leak seen in reasoning_traces.jsonl / journalctl) — do
# not pre-guess formats never actually observed.
_UNICODE_SEEDS = ("<｜", "<|")
_LITERAL_SEEDS = ("<tool_call", "<function_call", "[TOOL_CALLS")
_PROVISIONAL_CAP = 24  # a bare 2-char unicode seed is NOT enough on its own to confirm (too
# common a false-positive risk, e.g. pasted code with a "<|" pipe) — it must go on to complete
# the full open+name+close shape before confirming; this caps how long we'll wait for that.

# Anchored: only matches from the very start of the (provisional) buffer. The unicode family
# requires BOTH delimiters (open ... close) framing a short ASCII tag/param name before it
# counts as confirmed — a bare opening delimiter alone is never enough. The literal family is
# unambiguous once fully spelled out, so no closing requirement is needed for those.
_TRIGGER_RE = re.compile(
    r"^(?:<[｜|]\s*[A-Za-z0-9_.]{1,40}\s*[｜|]|<tool_call|<function_call|\[TOOL_CALLS\])"
)
_CLOSE_HINTS = ("</｜DSML｜tool_calls>", "</tool_call>", "</function_call>")
_MAX_BUFFER_CHARS = 8000  # generous — real tool payloads (e.g. a C# snippet) fit; caps a runaway hold


def _is_seed_prefix(s: str) -> bool:
    """True while `s` could still grow into a real trigger. Unicode seeds: once
    the opening delimiter has been seen, ANY length is still "waiting for the
    closer" (bounded by _PROVISIONAL_CAP, not by this check). Literal seeds:
    `s` must still be a strict prefix of the full literal."""
    if any(s.startswith(seed) for seed in _UNICODE_SEEDS):
        return True
    return any(seed.startswith(s) for seed in _LITERAL_SEEDS)


@dataclass
class LeakGuardState:
    """One instance per streaming response (one round), like tool_calls_accumulator."""
    holding: bool = False     # confirmed inside a leaked tool call, buffering until it closes
    buffer: str = ""          # confirmed-hold accumulator
    provisional: str = ""     # maybe-a-trigger accumulator, not yet confirmed either way


@dataclass
class GuardEvent:
    passthrough: str | None = None     # forward verbatim to the user
    resolved_call: dict | None = None  # {"name": str, "arguments": <json str>} — inject as a real tool call
    dropped: bool = False              # buffer gave up unresolved — nothing shown, caller should log it


def guard_delta(state: LeakGuardState, text: str) -> list[GuardEvent]:
    """Feed one `delta.content` fragment through the gate. Pure function of
    (state, text) — no I/O, no sleeps, safe to unit test without a live LLM.
    Returns an ordered list of events (usually one; can be several if a
    single chunk both closes a held buffer and contains trailing plain
    text, or contains more than one leaked call back to back)."""
    if not text:
        return []

    events: list[GuardEvent] = []
    passthrough_acc: list[str] = []

    def _flush_passthrough():
        if passthrough_acc:
            events.append(GuardEvent(passthrough="".join(passthrough_acc)))
            passthrough_acc.clear()

    for ch in text:
        if state.holding:
            state.buffer += ch
            if any(hint in state.buffer for hint in _CLOSE_HINTS):
                parsed = _try_parse_leak(state.buffer)
                state.holding = False
                state.buffer = ""
                _flush_passthrough()
                if parsed is not None:
                    events.append(GuardEvent(resolved_call=parsed))
                else:
                    events.append(GuardEvent(dropped=True))
            elif len(state.buffer) > _MAX_BUFFER_CHARS:
                state.holding = False
                state.buffer = ""
                _flush_passthrough()
                events.append(GuardEvent(dropped=True))
            continue

        # Fast path: not already provisional, and this char can't possibly
        # start any known seed (all seeds start with "<" or "[") — the
        # overwhelming majority of characters in a normal response. Skip the
        # regex/seed machinery entirely; this is the "zero added latency for
        # the normal case" guarantee, not just a claim.
        if not state.provisional and ch not in ("<", "["):
            passthrough_acc.append(ch)
            continue

        candidate = state.provisional + ch
        m = _TRIGGER_RE.match(candidate)
        if m and m.end() == len(candidate):
            state.holding = True
            state.buffer = candidate
            state.provisional = ""
            continue
        if len(candidate) <= _PROVISIONAL_CAP and _is_seed_prefix(candidate):
            state.provisional = candidate
            continue

        # False alarm (or provisional cap exceeded without matching): the
        # held-back provisional text was never a real trigger — flush it as
        # plain text, then re-evaluate this char fresh (it may itself start
        # a brand new seed).
        if state.provisional:
            passthrough_acc.append(state.provisional)
            state.provisional = ""
        if _is_seed_prefix(ch):
            state.provisional = ch
        else:
            passthrough_acc.append(ch)

    _flush_passthrough()
    return events


def _try_parse_leak(buf: str) -> dict | None:
    """Recover a {name, arguments} pair from a closed leaked-call buffer.
    Only the DSML shape observed live is implemented; unknown shapes fall
    through to `dropped` (safe: never shown raw, never guessed)."""
    name_m = re.search(r'invoke name="([^"]+)"', buf)
    if not name_m:
        return None
    param_m = re.search(
        r'parameter name="([^"]+)"[^>]*>(.*?)</[｜|][^｜|]*[｜|]parameter[｜|]?>',
        buf, re.DOTALL,
    )
    if not param_m:
        param_m = re.search(r'parameter name="([^"]+)"[^>]*>(.*?)(?:</[｜|]|$)', buf, re.DOTALL)
        if not param_m:
            return None
    param_name, param_value = param_m.group(1), param_m.group(2)
    return {"name": name_m.group(1), "arguments": json.dumps({param_name: param_value})}
