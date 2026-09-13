"""THE COMPOSITION OF A DERIVED APARTMENT — a measure that knows how to say NO.

WHY THIS MODULE, measured 20.08.2026. The quality of apartment derivation
was measured by COMPONENT COUNT and NUMBER OF SINGLES. Both quantities are
BLIND BY CONSTRUCTION, and this is shown not by argument but by an induced
fault: on the generator's reference case, repainting `ПРИХОЖАЯ` as
`КОРИДОР` (exactly what the lexicon does with the tower's «Холл») —

    components      20 -> 20     did not budge
    singles          0 ->  0     did not budge
    orphaned bathrooms 0 -> 20   ONLY THIS MEASURE NOTICED

A number that is the same under both outcomes measures nothing (form 14).
Hence the COMPOSITION measure: an apartment is not "a connected component"
but a dwelling, and the rooms that serve it must lie INSIDE it.

WHAT THIS IS NOT, AND WHY THE DISTINCTION IS LOAD-BEARING. Alongside it
lives the precondition `engine.PRECONDITIONS["apartments_are_dwellings"]` —
"the component has a kitchen OR a bathroom." It is BINARY and answers the
question "is this a dwelling at all"; it lets through an apartment with a
kitchenette and NO bathroom, because the disjunction is already satisfied.
The question here is different — "did we lose rooms that belong to it" —
and it gives a NUMBER with a denominator taken from the building itself.
There is no second carrier of one quantity here: the quantities are
different.

MEASURED ON TOWER `k2_ar_rd_v15` (2442 rooms, path `spatial_model_from_l0`):

    bathrooms in the building 467 · ORPHANED 366 (78.4%)
    apartments derived         808 · WITHOUT A BATHROOM 707 (87.5%)
    rooms outside any derivation at all 1258 of 2442 (51.5%)

The mechanism is named and verified: `RoomFunction.КОРИДОР` is declared
PUBLIC circulation (`graph.PUBLIC_CIRCULATION`), and the lexicon sends both
«Холл» (281) and «Коридор» (221) there — 502 nodes on the apartment side.
Cutting them out severs the connection between living rooms and the
bathroom, and an orphaned component with no apartment marker is discarded
whole (`derive_apartments`, branch `APARTMENT_MARKERS`).

🔴 THE MEASURE DOES NOT FIX THE DERIVATION AND DOES NOT PROPOSE A THRESHOLD.
It gives a number by which a fix can be ACCEPTED OR REJECTED — and that is
exactly what was missing: the earlier attempt (a per-node predicate) drove
singles down to 360 while gluing kitchens together, and both earlier
measures stayed silent about it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from kir.checker.spatial_model import RoomFunction, SpatialModel

#: Rooms that serve a DWELLING and are never freestanding: if such a room
#: did not land in any derived apartment, it is LOST, not "public." The
#: list is CLOSED AND NOT COMPLETE (the second kind per the canon's
#: catalog): a missing member means "we don't know," not "no such thing
#: exists." The bathroom comes first because its belonging to an apartment
#: is set by code, not by layout taste.
SERVICE_OF_A_DWELLING: frozenset[RoomFunction] = frozenset({
    RoomFunction.САНУЗЕЛ,
})

#: 🔴 EXACTLY ONE PER DWELLING. The invariant is pinned (`d9bca701`) and on
#: 20.08.2026 it turned out to be DECISIVE: on its own it killed three
#: topological definitions of publicness, each of which looked like a win
#: by the other numbers.
#:
#: The measurement for whose sake this constant became first-class. The
#: definition "a corridor is public if it TOUCHES the core," on tower
#: `k2_ar_rd_v15`:
#:
#:     singles           518 -> 300     looks like a win
#:     orphaned bathrooms 366 -> 39     looks like a BIG win
#:     KITCHENS > 1         0 -> 39     the definition is dead
#:     largest               5 -> 61 rooms
#:
#: The previous two measures would have called this a success. The
#: composition measure named the actual subject: the apartments didn't come
#: together, they fused. Counting this by hand with a `Counter` on the spot
#: would mean keeping a decisive quantity outside the instrument.
ONE_PER_DWELLING: frozenset[RoomFunction] = frozenset({RoomFunction.КУХНЯ})

#: How many names to put in the sample. The sample is for reading by eye;
#: the full list is deliberately not printed, otherwise the report would
#: grow longer than its subject (form 19).
_SAMPLE = 12


@dataclass(frozen=True)
class Rate:
    """A share that REFUSES to be computed on an empty denominator.

    "0 of 0" and "0 of 467" print almost identically and mean the opposite
    (form 4: on a negative result, the DENOMINATOR is read first).
    Therefore `share` here is `None`, not `0.0`, and the cause is named in
    words.
    """

    part: int
    whole: int

    @property
    def share(self) -> float | None:
        return None if self.whole == 0 else self.part / self.whole

    def render(self, what: str) -> str:
        if self.whole == 0:
            return f"{what}: НЕ ПОСЧИТАНО — в здании таких помещений нет вовсе"
        return f"{what}: {self.part} из {self.whole} ({100.0 * self.part / self.whole:.1f} %)"


@dataclass(frozen=True)
class CompositionReport:
    """The composition of the derivation as one subject. Everything is a countable quantity with a denominator.

    🔴 WHAT IS IN THE DENOMINATOR IS WRITTEN DOWN, NOT IMPLIED (20.08.2026).
    `rooms_total` is the rooms IN THE MODEL, and on different paths this is
    a DIFFERENT set:

        path PARSE (L0)   all rooms in the decompile header
        path LIVE (C#)    only PLACED ones: `extractor.cs` skips
                          `Area <= 1e-6`, and on the live document
                          MNVNK_ATR_PD_B14_K6 that is 629 of 1102 (57%)

    An unplaced room has neither area nor boundaries and does not enter the
    graph — excluding it is correct. What would be incorrect is NOT SAYING
    that it was excluded: "473 rooms" and "1102 rooms" are two different
    buildings under one name. That's why `rooms_unplaced` rides alongside,
    and `None` ("the source didn't report") is DIFFERENT from zero
    ("it reported, and there are none").
    """

    apartments: int
    rooms_total: int
    rooms_inside: int
    orphan_service: Rate
    apartments_without_service: Rate
    duplicate_service: Rate
    orphan_sample: tuple[str, ...] = field(default_factory=tuple)
    #: How many rooms did NOT MAKE IT into the model even before derivation.
    #: `None` means "the source doesn't report this," and that is NOT zero.
    rooms_unplaced: int | None = None

    @property
    def rooms_outside(self) -> int:
        return self.rooms_total - self.rooms_inside

    def render(self) -> str:
        unplaced = ("неразмещённых НЕ СООБЩЕНО источником"
                    if self.rooms_unplaced is None
                    else f"плюс {self.rooms_unplaced} неразмещённых ВНЕ модели")
        lines = [
            f"квартир выведено {self.apartments}; помещений {self.rooms_inside} "
            f"из {self.rooms_total} внутри, {self.rooms_outside} вне вывода "
            f"({unplaced})",
            "  " + self.orphan_service.render("обслуживающих помещений-СИРОТ"),
            "  " + self.apartments_without_service.render("квартир БЕЗ обслуживающего"),
            "  " + self.duplicate_service.render("квартир с БОЛЕЕ ЧЕМ ОДНИМ"),
        ]
        if self.orphan_sample:
            lines.append("  образец сирот: " + ", ".join(self.orphan_sample))
        return "\n".join(lines)


def composition_report(
    model: SpatialModel,
    apartments: Sequence,
    *,
    service: Iterable[RoomFunction] = SERVICE_OF_A_DWELLING,
    rooms_unplaced: int | None = None,
) -> CompositionReport:
    """A pure function: the composition of the derivation against the composition of the BUILDING.

    The denominator is taken from the building, not from us: how many
    bathrooms are in the model is a fact of the author's; how many
    apartments we derived is our own claim. The ratio of one to the other
    is exactly what can be accepted or rejected.

    THE MEASURE IS DELIBERATELY TWO-SIDED. Under-merging shows up as
    ORPHANS and as APARTMENTS WITH NO SERVICE ROOM; over-merging shows up
    as APARTMENTS WITH SEVERAL. A measure that only grows in one direction
    gets gamed by pushing it to absurdity in the other.
    """
    wanted = frozenset(service)
    func: Mapping[str, RoomFunction] = {r.id: r.function for r in model.rooms}
    service_rooms = [r for r in model.rooms if r.function in wanted]

    inside: set[str] = set()
    for apt in apartments:
        inside.update(apt.room_ids)

    orphans = [r for r in service_rooms if r.id not in inside]

    without = 0
    duplicated = 0
    for apt in apartments:
        n = sum(1 for rid in apt.room_ids if func.get(rid) in wanted)
        if n == 0:
            without += 1
        elif n > 1:
            duplicated += 1

    n_apts = len(apartments)
    return CompositionReport(
        apartments=n_apts,
        rooms_total=len(model.rooms),
        rooms_inside=len(inside & {r.id for r in model.rooms}),
        orphan_service=Rate(len(orphans), len(service_rooms)),
        apartments_without_service=Rate(without, n_apts),
        duplicate_service=Rate(duplicated, n_apts),
        orphan_sample=tuple(sorted(r.name for r in orphans)[:_SAMPLE]),
        rooms_unplaced=rooms_unplaced,
    )


def over_merge_report(model: SpatialModel, apartments: Sequence) -> CompositionReport:
    """Over-merging in one call: how many apartments carry MORE THAN ONE kitchen.

    The same instrument from a different angle (`service=ONE_PER_DWELLING`),
    not a second instance of it: read the `duplicate_service` field.

    WHY A SEPARATE NAME IF IT'S A PARAMETER. Because it answers a DIFFERENT
    question. `composition_report` asks "did we lose something belonging to
    the apartment" — under-merging. This one asks "did we glue two
    apartments into one" — over-merging. Both quantities are needed
    TOGETHER: on 20.08.2026 three topological definitions of publicness
    improved the first and failed the second, and by the first one alone
    all three would have shipped to prod as a win.
    """
    return composition_report(model, apartments, service=ONE_PER_DWELLING)
