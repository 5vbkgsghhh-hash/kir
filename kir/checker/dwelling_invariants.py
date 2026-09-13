"""WHAT MUST BE TRUE OF AN APARTMENT — and WHERE EACH ITEM IS KNOWN FROM.

WHY THIS MODULE (20.08.2026). Three topological definitions of publicness
died in a single evening, and what killed them was COMPOSITION, not topology:
"core touch" improved both prior measures (singles 518 → 300, orphans 366 →
39) and produced 39 apartments with two kitchens. Hence the reversal of the
task: stop guessing which nodes are public, and start searching for a
partition that SATISFIES the invariant.

The first pass is not an algorithm. Before partitioning, one must name WHAT
the invariant is, and for each, name its SOURCE. "Sounds reasonable" is not a
source — this rule is applied literally here, which is why below there is
also a list of what sounds reasonable and is NOT ENTERED into the registry.

🔴 THE MAIN CAVEAT, AND IT IS PRINTED BY THE INSTRUMENT, NOT KEPT IN THE
AUTHOR'S HEAD. There is no apartment oracle: `apartment_id` is not stamped on
a single one of the tower's 2442 rooms, `ROOM_DEPARTMENT` on the checked
document gives ONE group for 1102 rooms, zero groups with rooms, zones
without names or boundaries. So a partition satisfying the invariants is NOT
"the correct apartments." It is "apartments that do not contradict what we
know how to check." The difference between these two statements must appear
in the report, and it does (`VERDICT_BANNER`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from kir.checker.spatial_model import RoomFunction, SpatialModel

#: Printed ABOVE any output of this module. Not decoration: without it
#: "invariants satisfied" reads as "apartments were derived correctly," and
#: these are different statements — the second one we cannot prove at all.
VERDICT_BANNER = (
    "ОРАКУЛА КВАРТИРЫ НЕТ. Выполнение инвариантов значит «не противоречит "
    "тому, что мы умеем проверить», и НЕ значит «выведено верно»"
)

_SOURCE_KINDS = ("decision_fired", "rule", "definition")


@dataclass(frozen=True)
class Invariant:
    """A claim about the COMPOSITION of one component plus its provenance.

    `source_kind` is closed over three values, and none of them is "common
    sense":

        decision_fired  a decision that has ALREADY caught a defect on real data
        rule            an active checker rule with its own number
        definition      follows from the definition of the subject, not from observation
    """

    id: str
    statement: str
    source_kind: str
    source: str
    holds: Callable[[frozenset, Mapping[str, RoomFunction]], bool]

    def __post_init__(self) -> None:
        if self.source_kind not in _SOURCE_KINDS:
            raise ValueError(
                f"{self.id}: род источника {self.source_kind!r} не объявлен. "
                f"Допустимы {_SOURCE_KINDS}; «звучит разумно» источником не "
                f"является — на то и закрытый список")


def _count(ids: frozenset, func: Mapping[str, RoomFunction],
           what: RoomFunction) -> int:
    return sum(1 for rid in ids if func.get(rid) is what)


#: A CLOSED LIST, and it is "closed but not complete" (the second kind per the
#: canon's catalog): a missing member means "it has no source," NOT "no such
#: requirement exists." Candidates without a source are listed below by name.
INVARIANTS: tuple[Invariant, ...] = (
    Invariant(
        id="one_kitchen",
        #: 🔴 IT USED TO BE "EXACTLY one kitchen" WITH THE PREDICATE `<= 1`
        #: (fix 29.08.2026, audit finding F-356). The mismatch is real, but it
        #: is fixed by the DECLARATION, not the predicate, and here is why —
        #: by this very module's own argument.
        #:
        #: "Exactly one" = "no more than one" AND "at least one". The first
        #: half is exactly what was caught live twice. The second is a
        #: strengthening that the module CONSCIOUSLY refuses to make: the
        #: neighboring `at_least_one_bathroom` sits in `UNSOURCED_CANDIDATES`
        #: with the argument "the active DEFINITION of a dwelling is a kitchen
        #: OR a bathroom, i.e. a disjunction; the strengthening is not backed
        #: by a norm." The requirement "at least one kitchen" is the very same
        #: move, just from the other side of the disjunction, and it would
        #: contradict `is_a_dwelling`, whose source is measured on three
        #: inputs.
        #:
        #: The neighboring `one_prihozhaya`, under the same predicate `<= 1`,
        #: already says "no more than one" — that is, the correct wording
        #: already EXISTS in the file, and exactly one of the two lines had
        #: drifted.
        statement="в жилище не больше одной кухни; две кухни в компоненте — "
                  "две слитые квартиры",
        source_kind="decision_fired",
        source="d9bca701 — инвариант пришпилен; ловил дефект ДВАЖДЫ на живых "
               "данных: клика по разделителю дала «19 квартир с двумя и более "
               "кухнями», а предикат по узлу разложил 281 кухню по 106 "
               "компонентам. Проверяется БЕЗ оракула",
        holds=lambda ids, func: _count(ids, func, RoomFunction.КУХНЯ) <= 1,
    ),
    Invariant(
        id="one_prihozhaya",
        statement="в жилище не больше одной прихожей; две — квартира в квартире",
        source_kind="rule",
        source="HAB002, ветвь (c) (`rules/connectivity.py`): «a single private "
               "component holding >1 прихожая means multiple apartments are "
               "fused into one» — структурно, без опоры на штамп apartment_id",
        holds=lambda ids, func: _count(ids, func, RoomFunction.ПРИХОЖАЯ) <= 1,
    ),
    Invariant(
        id="is_a_dwelling",
        statement="жилище имеет кухню ЛИБО санузел; компонента без обоих — "
                  "артефакт вывода, а не квартира",
        source_kind="definition",
        source="engine.PRECONDITIONS['apartments_are_dwellings'] — ОПРЕДЕЛЕНИЕ "
               "жилища, а не подобранный порог. Замерено на трёх входах: "
               "эталон 0 не-жилищ из 20 · детсад 11 из 12 · башня 621 из 995",
        holds=lambda ids, func: bool(
            {RoomFunction.КУХНЯ, RoomFunction.САНУЗЕЛ}
            & {func[rid] for rid in ids if rid in func}),
    ),
)

#: 🔴 SOUNDS REASONABLE AND IS NOT ENTERED IN THE REGISTRY — NAMED, SO IT
#: CANNOT SLIP IN. I considered each item on this list and could not name a
#: source. The list exists because a silently absent requirement comes back a
#: week later as "obvious."
UNSOURCED_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("at_least_one_bathroom",
     "«в каждой квартире есть санузел». Действующее ОПРЕДЕЛЕНИЕ жилища — "
     "кухня ЛИБО санузел, то есть дизъюнкция; усиление до обязательного "
     "санузла нормой не подтверждено — ссылки на СП у меня нет, а выдумывать "
     "её нельзя. На башне 707 квартир из 808 без санузла: это то, что мы "
     "ХОТИМ починить, и оттого негодный вход в критерий приёмки"),
    ("exactly_one_entrance",
     "«ровно один вход из МОП» — HAB002, ветвь (b). Источник есть, но это "
     "утверждение о ГРАНИЦЕ, а не о СОСТАВЕ, и как ограничение разбиения оно "
     "круговое: вход определяется тем же разбиением, которое мы ищем"),
    ("at_least_one_kitchen",
     "«в каждой квартире есть кухня». Ровно та же форма, что "
     "`at_least_one_bathroom`, и отвергается тем же доводом: определение "
     "жилища — кухня ЛИБО санузел, дизъюнкция, и требовать обе половины "
     "значит переписать определение, а не проверить его. Внесено сюда "
     "29.08.2026 после того, как заявление `one_kitchen` обещало «РОВНО "
     "одну» при предикате `<= 1`: молча отсутствующее требование через "
     "неделю возвращается как «очевидное», и этот список ровно затем и есть"),
    ("apartment_size_range",
     "«в квартире от 2 до 8 комнат». Чистое мнение: ни замера, ни нормы. "
     "Именно такой порог и подогнал бы вывод под 995"),
)


@dataclass(frozen=True)
class Feasibility:
    """Whether apartments can be searched for in this building AT ALL.

    🔴 REFUSAL IS A FIRST-CLASS OUTCOME, NOT THE WORST PARTITION. A
    kindergarten is not housing, and the correct answer there is "there are no
    apartments here," not twelve office-"apartments." An instrument that
    always returns something produces confident nonsense on a non-residential
    building — and that is exactly what happens today (measurement:
    `sob62_r23_v5` yields 12 "apartments," of which 11 fail the dwelling
    definition).
    """

    searchable: bool
    reason: str
    kitchens: int
    bathrooms: int
    rooms: int

    def render(self) -> str:
        head = "искать можно" if self.searchable else "🔴 ИСКАТЬ НЕЧЕГО"
        return f"{head}: {self.reason} (комнат {self.rooms}, кухонь " \
               f"{self.kitchens}, санузлов {self.bathrooms})"


def feasibility(model: SpatialModel) -> Feasibility:
    """Refusal WITHOUT A THRESHOLD: a building with no kitchens and no
    bathrooms has no dwellings by construction.

    The condition is deliberately neither a ratio nor a count: a ratio would
    be a solution tailored to the building, whereas "not a single kitchen AND
    not a single bathroom" follows directly from the definition of a dwelling
    (`is_a_dwelling`). Weaker, and we would not refuse but count and print;
    stronger, and it would be fitting the data.
    """
    func = {r.id: r.function for r in model.rooms}
    kitchens = sum(1 for f in func.values() if f is RoomFunction.КУХНЯ)
    baths = sum(1 for f in func.values() if f is RoomFunction.САНУЗЕЛ)
    if not model.rooms:
        return Feasibility(False, "в модели нет ни одного помещения", 0, 0, 0)
    if kitchens == 0 and baths == 0:
        return Feasibility(
            False,
            "ни одной кухни и ни одного санузла — по определению жилища "
            "квартир здесь нет; всякое разбиение было бы вымыслом",
            kitchens, baths, len(model.rooms))
    return Feasibility(True, "жилищные помещения в здании есть",
                       kitchens, baths, len(model.rooms))


@dataclass(frozen=True)
class InvariantReport:
    """How many components violate each invariant. Always with a denominator."""

    components: int
    violations: dict[str, int] = field(default_factory=dict)
    feasible: Feasibility | None = None

    @property
    def clean(self) -> bool:
        return self.components > 0 and not any(self.violations.values())

    def render(self) -> str:
        lines = [VERDICT_BANNER]
        if self.feasible is not None:
            lines.append("  " + self.feasible.render())
        if not self.components:
            lines.append("  компонент нет — судить не о чем")
            return "\n".join(lines)
        for inv in INVARIANTS:
            n = self.violations.get(inv.id, 0)
            mark = "ok " if not n else "🔴 "
            lines.append(f"  {mark}{inv.id}: нарушают {n} из {self.components} "
                         f"[{inv.source_kind}]")
        return "\n".join(lines)


def check_invariants(model: SpatialModel,
                     components: Sequence) -> InvariantReport:
    """How many components violate each declared invariant.

    The input is ANY partition (today's, a candidate, a manual one): the
    instrument judges the result, not how it was obtained. This is exactly
    what made it possible to reject three definitions of publicness in one
    evening without touching prod.
    """
    func = {r.id: r.function for r in model.rooms}
    counts = {inv.id: 0 for inv in INVARIANTS}
    for component in components:
        ids = frozenset(getattr(component, "room_ids", component))
        for inv in INVARIANTS:
            if not inv.holds(ids, func):
                counts[inv.id] += 1
    return InvariantReport(components=len(components), violations=counts,
                           feasible=feasibility(model))
