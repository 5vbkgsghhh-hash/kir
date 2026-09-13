"""THE SHOWROOM'S CLIENT-FILE ADDRESS — ONE CARRIER FOR ALL INSTRUMENTS.

🔴 WHY A SEPARATE MODULE. Before 29.08.2026 the address was computed by
COUNTING DIRECTORY STEPS (`pathlib.Path(__file__).resolve().parents[4]`) in
three places at once. The count was correct for the
`backend/kukai/ir/viewer/tests` layout KIR was cut out of; in `/opt/kir` the
package sits two steps shallower, and the address FLEW PAST the root —
yielding `/opt/assets/viewer/scene-data.js`, which does not exist and never
will.

The miss was GREEN: it showed up as `skipTest`, not a refusal. Two splicing
instruments (`verify_merge.mjs`, `verify_partial.mjs`) had not run EVEN ONCE
since the split itself, and the suite kept reporting `223 passed` all the
while.

🔴 AND THIS FIX WAS ALREADY MADE ONCE, AND THE SPLIT ROLLED IT BACK.
`test_delta` recorded it as `own if own.exists() else prod` — but `own` was
computed by the SAME `parents[4]`, so `own.exists()` was ALWAYS false, and
the instrument went back to reading PROD, staying green and silent about it.
A single carrier is set up for exactly one reason: so there is no third
time.

🔴 MEASURED 29.08.2026, AND IT CHANGES WHAT THE FIX MEANS. In the KIR tree
there is NO `assets/viewer/scene-data.js` file AT ALL:

    find /opt/kir -name scene-data.js -not -path '*/build/*'   -> empty
    ls /opt/kir/assets                                          -> logo.png, logo.svg, …
    /opt/kukai-rebuild1/assets/viewer/scene-data.js             -> exists, 21 313 bytes

The showroom's client half lives in KUKAI, not in KIR. So "fix the address"
does NOT mean "the instrument will come alive from its own tree": it has no
file of its own today. It comes alive by a FALLBACK path — and the fallback
must be NAMED, or the instrument will again be judging a foreign copy and
saying nothing about it.
"""
from __future__ import annotations

import pathlib

#: KUKAI's prod is the fallback path. NOT the default address: KIR is
#: environment-agnostic, and it may depend on a neighboring tree only
#: BY NAME.
ПРОД = pathlib.Path("/opt/kukai-rebuild1/assets/viewer/scene-data.js")


def своё() -> pathlib.Path:
    """The address WITHIN ONE'S OWN tree — from the PACKAGE root, not by
    counting steps."""
    import kir
    return (pathlib.Path(kir.__file__).resolve().parent.parent
            / "assets" / "viewer" / "scene-data.js")


def scene_data_js() -> tuple[pathlib.Path | None, str]:
    """(path, where-from) or (None, reason). The reason is fit for
    `skipTest`.

    The second element is not decoration: "taken from one's own" and "taken
    from prod" are different facts, and an instrument that does not
    distinguish them is testifying about a foreign copy while posing as its
    own.
    """
    s = своё()
    if s.exists():
        return s, "своё дерево"
    if ПРОД.exists():
        return ПРОД, f"ЗАПАСНОЙ ПУТЬ — прод КУКАЯ ({ПРОД})"
    return None, f"нет ни {s}, ни {ПРОД}"
