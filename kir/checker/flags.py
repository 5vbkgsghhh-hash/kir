"""Feature flag for the geometry-first checker rebuild (checker v2).

Read DIRECTLY from the environment on every call (no import-time caching, no
kukai.config coupling): the operator flips `KIR_CHECKER_V2=1` on the service and the
very next check runs the v2 path — derivation pre-pass, three-valued verdict, coverage
section, declaration-consistency rules. Default OFF: the legacy (v1) checker behaviour
is bit-for-bit preserved so this can land in prod dark.

🔴 THIS PROMISE HAS HAD ONE NAMED EXCEPTION SINCE 18.08.2026, AND IT IS
RECORDED HERE, NOT ONLY WHERE IT WAS MADE. `graph.ground_level_ids` applies
the height band UNCONDITIONALLY: "ground" must mean the same thing regardless
of the lever, or a balcony door on the fortieth floor makes that floor
"ground," and egress rules judge nonsense (measurement on the tower: without
the band, 41 ground-levels; with it, 1).

On LIVE data the exception is inert, and this is verified by execution, not
inferred: the L0 path does not declare `is_exterior` at all (`design_check`
sets a literal False and says why), so under v1 the band has nothing to
filter — 0 of 2096 exterior doors on the tower. The answer changes only where
exteriority was DERIVED by `derive`, and that is called under v2.

🔴 THE SECOND NAMED EXCEPTION, 30.08.2026 (audit findings F-320, F-335).
`extractor._synthesize_stairs` builds connections between levels IDENTICALLY
under both levers: v1 and v2 diverge FURTHER DOWN — in flight dimensions and
in `kind` — but the CONNECTION ITSELF is shared. So two fixes change v1 too:

  * a connection is issued only between levels with ADJACENT and DIFFERENT
    `Level.index`. Before this, landings on L0 and L2 with no landing on L1
    produced `synth_L0_L2` — a stair through an UNSERVED floor, and two
    landings on one level produced `synth_L1_L1` with `base_z == top_z`, a
    stair from a level into itself;
  * the connection's identifier now includes the core key `(cx, cy)`, already
    computed by the grouping. Before this, two DIFFERENT cores on the same
    pair of floors got ONE id, and the graph merged them into a single node,
    connected to all four landings.

Why this is cheaper than the promise: both connections are a FABRICATED EXIT
FROM THE BUILDING. The first leads a floor to the ground through a level that
has no stair; the second goes from core A to core B, between which there is
no passage. Egress rules then judge nonsense, and the building looks SAFER
than it is — the same argument that made the height band above
unconditional.

Measured, not assumed (30.08, by execution): of 17 fixtures, the synthesis
takes part in ONE (`bad_floors_hidden_by_balcony_doors` — three consecutive
occupied levels with a landing on each), and there both connections are
PRESERVED, with only their names changing. The answer changes on a building
where landings are NOT marked on every floor: there HAB010 speaks by name for
the first time instead of staying silent — in the F-320 discriminator this is
the second finding, which does not exist today.

A rule for the future: the next exception to "bit-for-bit" must appear HERE
in the same commit as in the code. A promise living in one file, and its
violation in another, is our own named defect.

🔴 THE NAME CHANGED ON 28.08.2026, BUT THE BEHAVIOR DID NOT. `KIR_CHECKER_V2`
is read, and if it is unset, the former `KUKAI_CHECKER_V2` (`kir/env.py`). A
plain rename would have devalued the environment of running units at the very
moment the file landed on disk: the tree is installed in the service's venv
as EDITABLE, with no release in between. A NEWLY set name wins, even if it is
`0`.

Kept in its own module so every checker/generator module gates on ONE reviewable
switch instead of scattering os.environ reads.
"""
from __future__ import annotations

import os
from kir import env  # noqa: E402  (a dependency-free submodule — creates no cycle)


def checker_v2_enabled() -> bool:
    """True iff the geometry-first checker v2 path is switched on (env, read live).

    🔴 THE DEFAULT BECAME "ON" ON 01.09.2026, BY THE OWNER'S WORD, AND HERE IS
    WHAT THAT COST.

    The verdict of the measurement has stood in `KIR_PLAN.md` §10 since
    27.08.2026: on 17 apartments, v2 rejected TWO buildings known to be bad
    that v1 let through, and accepted NOT A SINGLE ONE that v1 rejected. There
    is no regression the other way. The cost is 6.5 ms -> 25.5 ms per
    apartment, i.e. 0.18% of the turn.

    Switching the default was refused then DELIBERATELY and for a valid
    reason: the tree is installed in the live service's venv as EDITABLE, and
    the fix would have shipped to prod that very second. The reason was
    RETIRED BY MEASUREMENT, not by boldness: the live service already judges
    by v2 — `KUKAI_CHECKER_V2=1` is set in the product's `.env` (the former
    name is still read, see `kir/env.py`). So switching the default does not
    move prod AT ALL; it moves exactly two things:

      * a stranger who installed the package from PyPI. They have no owner,
        and before this fix the judge stayed silent: the build path gave
        «ВЕРДИКТ НЕДОСТУПЕН» instead of «ПРИГОДЕН ПО 13 ПРАВИЛАМ ИЗ 20»
        (measurement 01.09 on 0.2.2 from the network);
      * our own test run, which before this fix walked a DEAD branch — one
        that neither prod nor a package reader has.

    It can still be switched off, and this is verified: `KIR_CHECKER_V2=0`
    (or the former name) brings back v1 entirely.

    🔴 THE "bit-for-bit preserved" PROMISE ABOVE APPLIES TO THE v1 BRANCH, NOT
    TO THE DEFAULT. The v1 branch is untouched down to the bit; what changed
    is which of the two is taken when the environment says nothing. The two
    named exceptions above concern what is shared between both branches and
    are unaffected by the default's change.
    """
    return env.get("KIR_CHECKER_V2", "1") == "1"
