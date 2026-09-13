"""WHERE THE STAIR'S TOP LEVEL CAME FROM — and why the rule is obligated to ask this.

WHY THIS MODULE, BY THE 22.08.2026 MEASUREMENT (MNVNK, 33 944 elements).
`_stairs_from_l0` required `STAIRS_TOP_LEVEL_PARAM`, and the building returned
it empty for 24 stairs out of 24 — and ALL 24 were discarded. The price of the
discard is printed in the same run: with not a single stair, the precondition
`stair_landings_complete` turned out true VACUOUSLY, HAB010 accused 23 levels
out of 24 of "hanging with no connection to the ground," while HAB011/HAB012
stayed silent. That is, a claim about OUR OWN READING was printed as a claim
about the building.

The top is DERIVED: `STAIRS_BASE_LEVEL_PARAM` + `ACTUAL_NUM_RISERS` ×
`ACTUAL_RISER_HEIGHT`, and all three arrived 24 out of 24. The same day's
measurement: for 23 stairs out of 24 the derived elevation matches an existing
level's elevation TO WITHIN FLOATING-POINT NOISE (|Δ| < 1e-8 mm); for one (id
929851, a finishing stair up to the roof) the flight's top lands 600 mm ABOVE
the nearest level, and this is a fact about the building, not about the
derivation.

🔴 A DERIVED VALUE IS OBLIGATED TO NAME ITSELF AS DERIVED. The same law as with
`height_provenance`, and for the same reason: a rule that places a BLOCKING
verdict on a flight's slope is obligated to know that the numerator of that
slope was something WE COMPUTED, not read. The difference is observable, not
decorative — see `rules/vertical.check_hab011`.

    READ FROM the author   `authored`   the slope is an independent value, judge it strictly
    DERIVED by us           `derived`    can be judged, cannot be used to BLOCK
    nothing to judge by      `unknown`    the rule is obligated to stay silent, BY NAME

AND WHY A DERIVED TOP MAKES THE SLOPE NON-INDEPENDENT, even though every
individual number in it is real. `check_hab011` computes the rise as
`(top_z - base_z) / riser_count`. When the top is READ, this is a comparison
of TWO INDEPENDENT facts: the distance between levels and the riser count.
When the top is DERIVED from the riser count and the riser height, the same
formula returns exactly `ACTUAL_RISER_HEIGHT` — a real value, but one that
checks itself. The identity does not make it a lie; it strips the rule of the
right to call the verdict proven.

THE KIND OF THIS LIST: the same as `height_provenance` — closed on the
producers' side, but its matcher is an EXACT NAME, and AN UNKNOWN NAME READS
AS `unknown`, not as `authored`. `Stair` already has three producers (the L0
parse, the program path, derivation from composed room-stairs), and a new
source will appear before anyone remembers this dictionary.
"""
from __future__ import annotations

#: READ FROM THE AUTHOR: beneath the value lies a field that the author filled
#: in themself.
AUTHORED: frozenset[str] = frozenset({
    # `design_check`, the parse path: BuiltInParameter.STAIRS_TOP_LEVEL_PARAM.
    "stairs_top_level_param",
    # the PROGRAM path: `create_stairs.top_level`, named by the program's author.
    "declared",
})

#: DERIVED BY US. The value is plausible and was NOT DECLARED by the author.
DERIVED: frozenset[str] = frozenset({
    # `design_check`, the parse path: base + riser count × riser height, and
    # the derived elevation MATCHED an existing level's elevation (within
    # `STAIR_TOP_SNAP_TOL_MM`). The match is an argument in favor of the
    # derivation, not proof of authorship.
    "riser_run",
    # the same computation, but the derived elevation did NOT match any
    # level: the named top level is the NEAREST one, and the size of the
    # discrepancy is printed by the witness (`stair_top_off_level`).
    "riser_run_offlevel",
    # `graph`/`composition`: a vertical connection derived from composed
    # room-stairs. There is no actual stair element beneath it at all.
    "inferred_link",
})

AUTHORED_KIND = "authored"
DERIVED_KIND = "derived"
UNKNOWN_KIND = "unknown"


def top_level_authority(source: str | None) -> str:
    """The top elevation's kind, by the name of its source. An unfamiliar name — `unknown`.

    The order of checks is load-bearing, exactly as in
    `height_provenance.height_authority`: the named sets come first, and only
    then the fall-through to `unknown`. The reverse order would silently
    promote every new source to "read from the author."
    """
    if source in AUTHORED:
        return AUTHORED_KIND
    if source in DERIVED:
        return DERIVED_KIND
    return UNKNOWN_KIND


def is_authored(source: str | None) -> bool:
    """Whether a STRICT verdict can stand on this top elevation."""
    return top_level_authority(source) == AUTHORED_KIND


def describe(source: str | None) -> str:
    """The human-readable reason — for the violation text and for `vacuous`."""
    kind = top_level_authority(source)
    if kind == AUTHORED_KIND:
        return f"верхний уровень прочитан у автора ({source})"
    if kind == DERIVED_KIND:
        return (f"верхний уровень ВЫВЕДЕН нами ({source}): отметка посчитана как "
                f"база + число подступенков × высоту подступенка, поэтому подъём "
                f"марша возвращает ту же высоту подступенка и проверяет сам себя — "
                f"вердикт не может быть блокирующим")
    if source:
        return (f"источник верхнего уровня {source!r} этому словарю неизвестен — "
                f"величина считается неподтверждённой, пока источник не назван")
    return "верхнего уровня нет вовсе — судить нечем"
