"""MCP DOOR ASSUMPTIONS: it is WIDER than the product's, not a trimmed copy
of it.

The owner's word, 02.09.2026: «give MCP more assumptions, permissions, and
capabilities than base KIR has».

🔴 WHY THIS IS NOT "WEAKENING" BUT "NO LONGER INHERITING SOMEONE ELSE'S
CAUTION." The narrowness of the product door is paid for by the PRODUCT's
conditions: a general-purpose chat, other people's devices, a fleet of
installs where a model's mistake reaches an unknown human. The MCP door
has none of these conditions: it is set up by whoever decided to set it up
themselves, by their own hand, on their own Revit. Inheriting someone
else's caution would mean paying its price without getting its reason.

🔴 AND WHAT IS NOT TOUCHED BY THIS — NAMED BY NAME. Not one of the
relaxations below touches the sandbox's ISOLATION LAYERS: a separate
process, namespaces with a measured unreachability of the network, a
chroot into an empty root, RLIMIT_FSIZE=0 and RLIMIT_NPROC=0, a wall by
time, an exit screen. This is not something I am recording for the first
time: the header of `sandbox.author_geometry_libs_enabled` says verbatim
that the whitelist was never the boundary, and that the KERNEL and the OS
layers are what hold it. By extending the list of names, I extend
CONVENIENCE, not the attack surface.

What remains the boundary after every relaxation:
  * THE IR GATEWAY: the script's only way out is a list of operations, and
    it goes entirely through the compiler's typed check. Whatever the
    script gets up to, it comes out as a program, not as an action;
  * THE OS LAYERS listed above, every single one of them;
  * THE IRREVERSIBLE, SEPARATELY: writing to the model is the one thing
    that cannot be undone, and it is held not by "assumptions" but by a
    switch and confirmation. This is not a limit on capability, but a
    requirement of intent.
"""
from __future__ import annotations

import os
from kir import env  # noqa: E402  (a submodule with no dependencies — gives no cycle)
from typing import Any

#: 🔴 GEOMETRY FOR THE AUTHOR — ENABLED BY DEFAULT, UNLIKE THE PRODUCT.
#: `numpy` and `shapely` in the product sit behind the
#: `KUKAI_IR_AUTHOR_GEOMETRY_LIBS` flag, off by default. For this door the
#: default is the reverse, and here is the price of the old one: the
#: example `examples/tower_numpy.py` — a 60-storey tower, 100 lines of
#: python, 840 operations after expansion — CANNOT be written at all
#: without numpy. That is, the flag being off did not cut out a library,
#: it cut out a whole class of tasks: everything where a shape is computed
#: rather than enumerated.
GEOMETRY_LIBS_DEFAULT = True

#: 🔴 THE AUTHOR'S BUDGET IS RAISED, AND THIS IS THE ONE NUMBER THAT
#: ACTUALLY CUT. The OPERATION ceilings have long been generous (100,000
#: for a program, 400,000 for a script), while what cut was time and
#: memory: 5 s of CPU, 8 s of wall clock, 256 MB. A script computing a
#: shape with numpy across the whole building does not fit into them —
#: and the refusal would look like "the language cannot do this," though
#: it can.
CPU_SECONDS = 30.0
WALL_SECONDS = 60.0
MEMORY_MB = 1024

#: The scope of write confirmation. `off` — do not ask (DEFAULT),
#: `session` — once per building handle, `call` — on every write.
#:
#: 🔴 THE `off` DEFAULT IS THE OWNER'S WORD, 03.09.2026, BY A DIRECT
#: QUESTION AND A DIRECT ANSWER. I kept the default strict, with the
#: argument "confirmation is not permission"; the owner asked "can the
#: human just not confirm?" and, on the proposal to make `off` the
#: default, answered "yes." Recorded here, because this is the ONE place
#: where the decision is visible to whoever reads the code.
#:
#: 🔴 WHAT THIS LIFTS AND WHAT REMAINS — I NAME HONESTLY, NOT SOFTENED.
#: LIFTED: there is no human in the loop. A model that has a handle and
#: the switch raised changes the live model with one call, and no one
#: stands between it and the building.
#: THREE THINGS REMAIN, and each is checked on a live Revit:
#:   1. the `KIR_MCP_WRITE=on` switch — without it, refusal, measured
#:      87/87;
#:   2. checking the document's fingerprint BEFORE a write — the window
#:      was switched, the write will not go out (review found this, and
#:      without it consent would apply to a different building);
#:   3. the compiler: a program that does not compile for the document's
#:      version never reaches the transport.
#: The first of the three is the operator's; the other two are the
#: machine's. Not one of them replaces the human; they replace CHANCE, not
#: INTENT.
CONFIRM_FLAG = "KIR_MCP_CONFIRM"
CONFIRM_SCOPES = ("off", "session", "call")


def geometry_libs_enabled() -> bool:
    """The product flag is STRONGER than the door's default, but only in
    the direction of "turn on."

    A host that raised `KUKAI_IR_AUTHOR_GEOMETRY_LIBS` gets the same
    thing; a host that never touched it gets the libraries here and does
    not get them in the product — and that is exactly the difference in
    conditions this file was set up for.
    """
    raw = (env.get("KIR_MCP_GEOMETRY_LIBS") or "").strip().lower()
    if raw in {"0", "off", "no", "false"}:
        return False
    return GEOMETRY_LIBS_DEFAULT


def confirm_scope() -> str:
    raw = (env.get(CONFIRM_FLAG) or "").strip().lower()
    return raw if raw in CONFIRM_SCOPES else "off"


def author_policy() -> Any:
    """The sandbox policy FOR THIS DOOR. Assembled on every call.

    Not cached, for the same reason it is not cached in the product: a
    toggle that does not take effect immediately reads as the service
    disagreeing with itself.
    """
    from kir.sandbox import ALLOWED_IMPORTS, SandboxPolicy

    allowed = tuple(ALLOWED_IMPORTS)
    if geometry_libs_enabled():
        allowed = allowed + tuple(
            name for name in ("numpy", "shapely") if name not in allowed)
    return SandboxPolicy(
        cpu_seconds=CPU_SECONDS,
        wall_seconds=WALL_SECONDS,
        memory_mb=MEMORY_MB,
        allowed_imports=allowed,
    )


def latitudes() -> dict[str, Any]:
    """How this door is WIDER than the product's — shown, not taken on
    faith.

    Printed into the server's `instructions`: a model that knows its own
    allowances does not spend a turn probing what is already permitted.
    """
    from kir.sandbox import (DEFAULT_CPU_SECONDS, DEFAULT_MEMORY_MB,
                             DEFAULT_WALL_SECONDS)
    return {
        "geometry_libs": {
            "here": geometry_libs_enabled(), "product_default": False,
            "why": "без numpy не пишется целый род задач — форма, которую считают",
        },
        "cpu_seconds": {"here": CPU_SECONDS, "product": DEFAULT_CPU_SECONDS},
        "wall_seconds": {"here": WALL_SECONDS, "product": DEFAULT_WALL_SECONDS},
        "memory_mb": {"here": MEMORY_MB, "product": DEFAULT_MEMORY_MB},
        "device_allow_list": {"here": None, "product": "требуется",
                              "why": "дверь ставит себе тот, кто сам решил"},
        "kir_mode_flag": {"here": None, "product": "требуется",
                          "why": "у MCP нет понятия хода — спрашивать не о чем"},
        "confirm_scope": {"here": confirm_scope(), "options": list(CONFIRM_SCOPES)},
    }
