"""BUILDING HANDLES: state between calls where there are no sessions.

The 2026-07-28 spec removed sessions and `Mcp-Session-Id`; cross-call state
now lives in HANDLES, issued by the server and passed as an ordinary tool
argument. This is not a workaround for the absence of sessions but a
better design: before the handle, choosing a document was IMPLICIT, and
the product already paid for it — the admin door looked for the Revit
window by name enumeration and once, with two windows open, picked up
SOMEONE ELSE'S title, from which the building index is assembled. The
handle makes the choice explicit: whoever holds it can see exactly WHAT
they opened.

🔴 WHAT A HANDLE CARRIES AND WHY EXACTLY THAT.
  * `document` — the document's title, AS THE OWNER NAMED IT, not as we
    guessed it;
  * `revit_version` — the version emission will target; "it compiled"
    without a named version means nothing (SPEC 11.2);
  * `fingerprint` — the document's fingerprint at the moment of issue. A
    handle that has outlived its document is a plausible untruth: it looks
    working and addresses something that no longer exists. The fingerprint
    lets a mismatch be noticed instead of writing blind;
  * `issued_at` + `ttl_s` — the lifetime. A handle without a lifetime
    outlives the truth about the document; this is the same kind of
    defect as a record without an expiry date in `tool_doc` (there it cost
    a week and a half of bypassing a working op).

🔴 THE REGISTRY IS IN THE PROCESS'S MEMORY, AND THIS IS NAMED, NOT PASSED
OVER IN SILENCE. A server restart kills handles. This is more honest than
surviving a restart: the document could have been changed by anyone in
that time, and a surviving handle would assert the opposite. A refusal of
"this handle is unfamiliar to this server" is cheaper than writing to the
wrong place.
"""
from __future__ import annotations

import os
from kir import env  # noqa: E402  (a submodule with no dependencies — gives no cycle)
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

#: The handle's lifetime. Half an hour is not "roughly," but an upper
#: estimate of how long a Revit document stays untouched with a human who
#: is WAITING for the model's answer. The operator may narrow it; there is
#: no sense in widening it — an expired handle is reissued with one call,
#: while a stale one writes to the wrong place silently.
DEFAULT_TTL_S = 1800

_PREFIX = "bld_"


class HandleError(Exception):
    """The handle is not valid. The text names WHY and what to do next."""


@dataclass(frozen=True)
class Building:
    handle: str
    document: str
    revit_version: str
    fingerprint: str
    issued_at: float
    ttl_s: int = DEFAULT_TTL_S
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def expires_at(self) -> float:
        return self.issued_at + self.ttl_s

    def alive(self, now: float | None = None) -> bool:
        return (now or time.time()) < self.expires_at

    def as_dict(self) -> dict[str, Any]:
        return {"building": self.handle, "document": self.document,
                "revit_version": self.revit_version,
                "fingerprint": self.fingerprint,
                "expires_in_s": max(0, int(self.expires_at - time.time()))}


_REGISTRY: dict[str, Building] = {}


def ttl_s() -> int:
    raw = (env.get("KIR_MCP_HANDLE_TTL_S") or "").strip()
    if raw.isdigit() and 0 < int(raw) <= 86400:
        return int(raw)
    return DEFAULT_TTL_S


def issue(*, document: str, revit_version: str, fingerprint: str,
          extra: dict[str, Any] | None = None) -> Building:
    """Issue a handle. The name is UNPREDICTABLE (`secrets`), and this is
    not ceremony.

    A handle is the address of a live document. A predictable name (a
    counter, a hash of the title) would allow addressing someone else's
    building without opening it — and the door on the other side writes.
    """
    handle = _PREFIX + secrets.token_hex(8)
    b = Building(handle=handle, document=document, revit_version=revit_version,
                 fingerprint=fingerprint, issued_at=time.time(), ttl_s=ttl_s(),
                 extra=dict(extra or {}))
    _REGISTRY[handle] = b
    return b


def resolve(handle: Any) -> Building:
    """A handle or a NAMED refusal. Three different "no"s do not merge into one."""
    if not isinstance(handle, str) or not handle.startswith(_PREFIX):
        raise HandleError(
            "поле `building` обязано быть ручкой, выданной `kir_open` "
            f"(вид «{_PREFIX}…»); следующий ход — позови `kir_open`")
    b = _REGISTRY.get(handle)
    if b is None:
        raise HandleError(
            "эта ручка незнакома серверу: её выдал другой процесс либо сервер "
            "перезапускался. Ручки живут в памяти процесса НАРОЧНО — пережившая "
            "перезапуск адресовала бы документ, о котором ничего не знает. "
            "Следующий ход — `kir_open` заново")
    if not b.alive():
        _REGISTRY.pop(handle, None)
        raise HandleError(
            f"ручка истекла (срок {b.ttl_s} с): документ мог измениться кем "
            f"угодно, и писать по ней значило бы писать вслепую. "
            f"Следующий ход — `kir_open` заново")
    return b


def forget(handle: str) -> None:
    _REGISTRY.pop(handle, None)


def count() -> int:
    """How many handles the process holds — for the gate and for the report, not for the logic."""
    return len(_REGISTRY)


def _reset_for_tests() -> None:
    _REGISTRY.clear()
