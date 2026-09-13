"""WHERE THE ROOM'S HEIGHT CAME FROM — and why a rule must ask this.

WHY THIS MODULE, BY MEASUREMENT 20.08.2026. `HAB022` (minimum ceiling height)
read `Room.height_mm` and did NOT ASK AT ALL about the value's provenance. On
the parsing path, this value is OUR OWN SUBSTITUTE: `design_check` took the
room bounding box's vertical span, because there was no real height in the
capture. That is, the rule was issuing a verdict on a number the author never
declared — and the only thing separating this from a silent lie was the
`height_source` field, which nobody read.

Since 20.08, the parser has something to judge by: `ROOM_UPPER_OFFSET` was
added to the capture (`f4c35e51`), and a live run showed the value is real —
1102 of 1102 rooms, 1081 of them nonzero, 0 failures
(`MNVNK_ATR_PD_B14_K6_AR_R2022`, Revit 2023). So the substitute stops being
the only path.

🔴 THE SUBSTITUTE IS NOT REMOVED, IT IS GIVEN A NAMED PRICE. Removing the
fallback path would mean that on older parses (where the parameter is
missing) we would get "height unknown" instead of an approximation — that is,
replacing inaccuracy with blindness. The distinction must be THREE-VALUED,
and collapsing it into two is exactly the defect this field was set up to
parse away:

    READ from the author    `authored`   may be judged strictly
    SUBSTITUTED by us        `derived`   may be judged, may NOT BLOCK
    nothing to judge by      `unknown`   the rule must stay silent, BY NAME

THIS LIST'S KIND: COMPLETE BY CONSTRUCTION ON THE PRODUCER SIDE, but its
matcher is an exact name, so an UNKNOWN NAME READS AS `unknown`, not as
`authored`. This is not caution: there are four producers (the L0 parser, the
live extractor, the wall path, the generator), they live in different files,
and a new source will appear before anyone remembers this dictionary.
Silently promoting an unfamiliar name to "read" is exactly the mistake that
must never be allowed here, not once.
"""
from __future__ import annotations

#: THE DISCRIMINATOR THAT SETTLES EVERY DISPUTE OVER MEMBERSHIP, AND IT IS
#: NOT "WAS IT DERIVED":
#:
#:     CAN WE POINT A FINGER AT A FIELD THE AUTHOR FILLED IN THEMSELVES?
#:
#: `wall_enclosure` IS DERIVED — a length-weighted height of the enclosing
#: walls — and yet it is `authored`: underneath it lies `create_wall.height_mm`,
#: written by the author, and the inference honestly REFUSES when the walls
#: do not reach the next level (a balustrade is not a ceiling). `room_bbox` is
#: also derived, but there is nothing to point at underneath it: the bounding
#: box is used because there was NO real height in the capture.
#:
#: 🔴 This line was written AFTER A MISTAKE, and it cost one red. The first
#: edit put `wall_enclosure` into `derived` on the grounds of "we computed
#: it" — and it suppressed a BLOCKING on a 2400 mm floor with 2100 mm walls.
#: What stopped me was not the red itself but the REASON recorded in someone
#: else's test next to the number: "the floor's step drops TOGETHER with the
#: walls on purpose." A bare `assert blocking` I would have fixed to suit
#: myself and moved on.
#:
#: READ FROM THE AUTHOR. Each input is a value backed by a field the author
#: filled in themselves.
AUTHORED: frozenset[str] = frozenset({
    # `design_check`, the parsing path: BuiltInParameter.ROOM_UPPER_OFFSET,
    # added to the capture 20.08.2026 and confirmed by a live run (1102 of
    # 1102).
    "room_upper_offset",
    # the live extractor: UpperLimit + LimitOffset − BaseOffset
    "bounded",
    # the live extractor: ROOM_HEIGHT / UnboundedHeight
    "param",
    # the generator / the program's author: the value is named in the input
    "declared",
    # the PROGRAM's path: a length-weighted height of the enclosing walls.
    # Derived — and yet read: underneath it is `create_wall.height_mm`,
    # written by the author.
    "wall_enclosure",
})

#: DERIVED BY US FROM GEOMETRY. The value is plausible and NOT DECLARED.
DERIVED: frozenset[str] = frozenset({
    # `design_check`, the parsing path: the room bounding box's vertical
    # span. The only input with NOTHING to point at underneath: the bounding
    # box is used because there was no real height in the capture.
    "room_bbox",
})

AUTHORED_KIND = "authored"
DERIVED_KIND = "derived"
UNKNOWN_KIND = "unknown"


def height_authority(source: str | None) -> str:
    """The value's kind by the name of its source. An unfamiliar name is
    `unknown`.

    The order of checks is load-bearing: the named sets first, and only then
    a fall-through into `unknown`. A reversed order ("if not derived, then
    authored") would silently turn every new source into a value declared by
    the author.
    """
    if source in AUTHORED:
        return AUTHORED_KIND
    if source in DERIVED:
        return DERIVED_KIND
    return UNKNOWN_KIND


def is_authored(source: str | None) -> bool:
    """Whether a STRICT verdict may stand on this value."""
    return height_authority(source) == AUTHORED_KIND


def describe(source: str | None) -> str:
    """A human-readable reason — for the violation's text and for `vacuous`."""
    kind = height_authority(source)
    if kind == AUTHORED_KIND:
        return f"высота прочитана у автора ({source})"
    if kind == DERIVED_KIND:
        return (f"высота ПОДСТАВЛЕНА нами ({source}): автор её не объявлял, "
                f"поэтому вердикт не может быть блокирующим")
    if source:
        return (f"источник высоты {source!r} этому словарю неизвестен — "
                f"величина считается неподтверждённой, пока источник не назван")
    return "высоты нет вовсе — судить нечем"
