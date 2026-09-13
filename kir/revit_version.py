"""THE REVIT VERSION — ONE SOURCE, AND IT NEVER STAYS SILENT ABOUT WHAT IT
DID NOT KNOW.

Measured 2026-08-13, the development tree. One value was derived by SIX
independent places, and they answered differently:

    location                               don't know ->   outside 2021..2026 ->   asks spec
    ir/serving.py:2245, :4319              "2026"          passes through          no
    api/admin_kir.py:212,358,429,506,782   "2026"          passes through          no
    api/admin_kir.py:310,409,487           "2026" hardcoded   --                   no
    ir/shadow.py:106                       "2026"          "2026"                  YES
    llm/api_members.py:56                  "2024"          clamps to 2021..2026    no (literals)
    compiler.compile_program(...)          "2026" as the parameter default    --

Three different answers to "don't know" — 2026, 2024 and 0
(`write/create_element.py:340`). And exactly ONE of the six asked the
authority `spec.REVIT_VERSIONS` — `shadow`, which is declared observe-only
and has no effect on emission at all. **The only place that read the
authority was the only one whose answer decided nothing.**

WHY THIS IS NOT A TRIFLE, MEASURED ON THE GOLDEN CORPUS (69 programs, a
suite snapshot, `compile_program(prog, revit_version=v,
snapshot=GROUND_SNAPSHOT)`):

    OUTCOME depends on version    7 programs
    C# differs additionally on    5
    total version-dependent      12 of 69  (17%)

    arch_ceiling · arch_ceiling_contour · auth_contour_l ·
    struct_foundation_slab · struct_foundation_slab_two_holes   refuses on 2021
    site_topography_toposolid                                   refuses before 2024
    datums_multistory_stairs                                    refuses before 2025

By guessing "2026" on a 2021 device, we do NOT issue the typed refusal we
should have issued, and send Revit C# it will not compile. A
silently-wrong building does not result — the cardinal invariant holds.
What breaks is the DIAGNOSIS contract: the refusal comes from the wrong
place and names the wrong thing, and this house has already twice
diagnosed that as an "op defect".

AND MOST IMPORTANTLY, WHY NO LIVE RUN WILL EVER FIND THIS.
`/admin/kir/contexts` on the live service on 08-13 returns exactly one
device, and it reports `"2026"` — the bridge's real value, not the
default. **The default coincides with the truth on the one single device
where we check everything**, so a live program's green is a fact about a
sample of one, not about the code.

WHAT THIS MODULE DOES, AND WHAT IT DELIBERATELY DOES NOT DO. It does NOT
refuse on the unknown: `write/create_element.py:340` explains why it
cannot — `_revit_version` is empty in EVERY session that has never
reported an open document, and a guard that refuses on the unknown would
break all of them. The default stays. One thing changes: it stops being
SILENT. `Resolved.provenance` carries where the number came from, and the
caller must decide whether to write that into the receipt — but it can no
longer lie "we were told 2026" when nobody told us anything, without
writing that lie by hand.
"""
# 🔴 PROVENANCE WAS MOVED OUT OF THE DOCSTRING ON 2026-09-01 — THE DOOR
# AGAINST THE LOG. A module docstring is a PUBLIC DOOR: `help()` prints it
# to the reader of the published package, and our machine's address tells
# them nothing. The knowledge is not erased — it is here, in the log, where
# it belongs:
#     measurement tree 2026-08-13  /home/claude/kir-head/backend

from __future__ import annotations

import re
from typing import NamedTuple

from kir import spec

#: The default. One for the whole house, and it lives HERE, not as five
#: literals scattered across the tree.
DEFAULT_VERSION = "2026"

#: Where the number came from. A CLOSED list: a reason that is not here
#: must appear as a new value, not quietly merge with a neighbour.
REPORTED = "reported"          # the bridge named a version, and it is supported
DEFAULTED = "defaulted"        # nothing was said — the default was taken
UNSUPPORTED = "unsupported"    # named CLEARLY, but we do not support that version
UNPARSED = "unparsed"          # something was said, but no year is in it

PROVENANCES = (REPORTED, DEFAULTED, UNSUPPORTED, UNPARSED)

#: The cap on `raw` IN THE RECEIPT. The string comes from the bridge, i.e.
#: a foreign side, and receipts in this house live under a budget
#: (`verdict._VERDICT_TEXT_CAP`). Without a cap, one diagnostic field could
#: crowd out everything else — the same class of defect as "one half of
#: the text gets cut while the other keeps being appended to the same
#: field". The truncation is DECLARED with an ellipsis, not silent.
RAW_IN_RECEIPT_CAP = 64


class Resolved(NamedTuple):
    """The version PLUS its provenance. They must not be separated:
    `version` without `provenance` is exactly the value that diverged six
    times over."""

    version: str
    provenance: str
    raw: str

    @property
    def is_guess(self) -> bool:
        """True when the number did NOT come from the bridge. One field for
        the receipt."""
        return self.provenance != REPORTED

    def as_receipt(self) -> dict:
        """What must reach the reader if the version was guessed."""
        if not self.is_guess:
            return {"revit_version": self.version}
        raw = self.raw
        if len(raw) > RAW_IN_RECEIPT_CAP:
            raw = raw[:RAW_IN_RECEIPT_CAP] + "…"
        return {"revit_version": self.version,
                "revit_version_provenance": self.provenance,
                "revit_version_raw": raw}


def supported() -> tuple[str, ...]:
    """Ask `spec`, do not copy it. The list grows there — this follows
    automatically."""
    return tuple(spec.REVIT_VERSIONS)


def resolve(raw) -> Resolved:
    """Parse anything into (version, provenance).

    Never raises and never returns a version outside `supported()`: calling
    emitters are entitled to treat the value as valid. Everything we did not
    know is named in `provenance`.
    """
    text = "" if raw is None else str(raw)
    if not text.strip():
        return Resolved(DEFAULT_VERSION, DEFAULTED, text)
    match = re.search(r"20\d\d", text)
    if match is None:
        return Resolved(DEFAULT_VERSION, UNPARSED, text)
    year = match.group(0)
    if year in supported():
        return Resolved(year, REPORTED, text)
    # A CLEARLY named but unsupported version is NOT the same as silence,
    # and the two must not be merged into one word: a user's Revit 2019 is
    # a fact about the WORLD, while an empty string is a fact about our own
    # channel.
    return Resolved(DEFAULT_VERSION, UNSUPPORTED, text)
