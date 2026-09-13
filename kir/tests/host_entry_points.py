"""HOST ENTRY POINTS — for tests asserting facts about the PRODUCT.

🔴 WHY THIS FILE WAS CREATED, AND WHY EXACTLY HERE (01.09.2026).

Before this change, the product's deployment map was held by THE PACKAGE
ITSELF — `instruments/capability_graph.ENTRY_POINTS`, four literals naming
modules and systemd units. This violated the owner's law ("KIR is a
building language, environment-agnostic; the product is only ONE of the
environments") and was printed to EVERY reader of the package published to
PyPI under Apache-2.0. Now the host names them via the port
`ports.ENTRY_POINTS`, and they are not in the package.

But SEVERAL KIR tests assert properties of the HOST's configuration: "the
transfer module is reachable from the production process," "the judge has
a live caller." Such assertions are legitimate — and must declare,
THEMSELVES, the configuration they speak of. Hence this file.

🔴 WHY NOT IN `fixtures.py`, WHERE THE REST OF THE SHARED CODE LIVES.
`fixtures.py` RIDES IN THE WHEEL (it is in `WHEEL_KEEP.json`, pulled in by
the split gate suite's closure). Putting the names there would mean
bringing the leak back through the very door it was just removed from.
This file is NOT ENTERED in the distribution whitelist and therefore does
not ship — checked by that same `WHEEL_KEEP.json`.

🔴 WHY ONE FILE, NOT FOUR COPIES. `ENTRY_POINTS` had FOUR places standing
on it (canon, transfer, intent receipt, clash receipt). Spreading the
literals across them would mean setting up four maps of the product
instead of one — worse than the original: they would drift apart silently.
"""
from __future__ import annotations

import contextlib

from kir import ports

#: Checked against `/etc/systemd/system` on 03.08.2026; it lives here
#: because it is a fact ABOUT THE PRODUCT, not about the language. Updated
#: together with the host's layout.
HOST_ENTRY_POINTS: dict[str, str] = {
    "kukai.main":         "kukai-backend.service — uvicorn kukai.main:app (:52411)",
    "tools.codex_pool":   "kukai-codex-pool.service/.timer",
    "tools.money_watch":  "kukai-money.service/.timer",
    "tools.release_sync": "kukai-release-sync.service/.timer",
}


@contextlib.contextmanager
def host_declares_entry_points(names: dict[str, str] | None = None):
    """For the duration of this block, the host declared its entry points.

    Removal in `finally` is LOAD-BEARING: a provider leaking into a
    neighboring test would make "port not supplied" unverifiable — and it
    is exactly this kind that the guards further down the tree watch for.
    """
    ports.register(ports.ENTRY_POINTS, lambda: dict(
        HOST_ENTRY_POINTS if names is None else names))
    try:
        yield
    finally:
        ports.unregister(ports.ENTRY_POINTS)


def live_or_named_skip(case, graph):
    """`graph.live()` — or a NAMED skip, if there is no one to ask.

    It is not the module that is dead, but the QUESTION: in a standalone
    KIR there is no production process at all, and "module unreachable"
    would read as a finding ABOUT THE MODULE. A silently passed check reads
    as passed, so the skip names the reason.
    """
    if not any(name in graph.modules for name in HOST_ENTRY_POINTS):
        case.skipTest(
            "ни одной точки входа ХОЗЯИНА в этом дереве нет "
            f"({', '.join(sorted(HOST_ENTRY_POINTS))}) — достижимость из "
            "прод-процесса здесь непроверяема")
    with host_declares_entry_points():
        return graph.live()
