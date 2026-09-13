"""WHERE THE WORD "HABITABLE" CAME FROM — and why a rule must ask this.

WHY THIS MODULE, BY MEASUREMENT 22.08.2026 (MNVNK, 1102 rooms). `ROOM_NAME`
equals the string "Помещение" for 1102 of 1102: rooms are NUMBERED but not
NAMED. Because of this, classification covers 0%, and seven rules fall
silent — HAB020, HAB021, HAB030, HAB031 (not a single function has a
threshold) and HAB002/003/004/042 (apartment derivation stands on name
classification and yields zero apartments).

A fallback ALREADY EXISTS in the parser: furnishing names a room's function.
A toilet, sink, and tub stand in a bathroom; a kitchen front and sink, in a
kitchen; a bed and sofa, in a habitable room. Same-day measurement over
`OST_PlumbingFixtures` / `OST_Furniture`: furnishing names the function for
286 of 473 measured rooms.

🔴 BUT THIS IS AN INFERENCE, NOT A WIRE, AND ITS KIND IS DIFFERENT. A room
whose function the author named and a room whose function we derived from a
toilet are DIFFERENT STATEMENTS:

  * the author might have put a toilet in a storage room, or might not have
    put one in a bathroom;
  * furnishing belongs to a STAGE and is entirely absent from an early-design
    project;
  * the signals conflict: measurement found 5 of 291 rooms where furnishing
    names two functions at once (a toilet next to a kitchen front — bathroom
    and kitchen in one outline). The inference's accuracy is therefore
    286 of 291 = 98.3%, and this is a NUMBER that must be printed next to the
    inference, not implied.

That is why a rule judging the AREA of a "habitable" room must know where the
word "habitable" came from, and has no right to issue a BLOCKING verdict on a
derived kind. The same law and the same technique as `height_provenance` and
`stair_provenance`:

    READ from the author    `authored`   may be judged strictly
    DERIVED by us            `derived`   may be judged, may NOT BLOCK
    nothing to judge by      `unknown`   the rule must stay silent, BY NAME

WHAT THIS KIND DOES NOT DO. It does not mute the rule and does not soften a
single threshold: a room with a derived function is STILL JUDGED, the finding
is still printed, and exactly one thing changes — it cannot VETO the verdict,
and it NAMES the reason.

THE LIST'S KIND: closed on the producer side, the matcher is an exact name,
and an UNKNOWN NAME READS AS `unknown`. There are four producers of room
function (the L0 parser, the live extractor, the program, `derive`'s
cross-check), they live in different files, and a new source will appear
before anyone remembers this dictionary.
"""
from __future__ import annotations

#: READ FROM THE AUTHOR. Behind each input is a word the project's author wrote.
AUTHORED: frozenset[str] = frozenset({
    # the function is set explicitly (`classify_room(name, explicit=...)`):
    # the live extractor with a tagged kind, the generator, the program's
    # author
    "explicit",
    # `derive`/`design_check`: the kind is derived from the room's NAME by
    # the `classify.py` lexicon. Derived — and yet read: underneath it is
    # `ROOM_NAME`, which the author wrote themselves
    "room_name",
    # the PROGRAM's path: `create_room.name`, named by the program's author
    "declared",
})

#: DERIVED BY US FROM AN INDIRECT SIGNAL. The author did not name the function.
DERIVED: frozenset[str] = frozenset({
    # `design_check`, the parsing path: the kind is named by the FURNISHING
    # standing inside the room's outline (`classify.classify_by_fixtures`)
    "fixtures",
    # 🔴 THE FUNCTION WAS NAMED BY THE HOST (port `ports.ROOM_CLASSIFIER`, set
    # up 28.08.2026), because our lexicon did not recognize the name: a
    # foreign language, an abbreviation, a typo. DERIVED, and the kind
    # decides here: under `room_name` lies a string the author wrote
    # themselves — under that name lies SOMEONE ELSE'S GUESS at what it
    # means. The guess can be very good (the host may be running an LLM) and
    # still has no right to a blocking verdict: the author did not name the
    # function.
    #
    # The judge's determinism stays intact through this: the port is called
    # ONCE, when the model is assembled, and the answer is WRITTEN into
    # `Room.function`. The judge reads what was written — it never goes to
    # the live guess, and the same model gives the same verdict.
    "host_classifier",
})

AUTHORED_KIND = "authored"
DERIVED_KIND = "derived"
UNKNOWN_KIND = "unknown"


def function_authority(source: str | None) -> str:
    """The function's kind by the name of its source. An unfamiliar name is
    `unknown`.

    The order of checks is load-bearing (see
    `height_provenance.height_authority`): a reversed order would silently
    promote every new source to "named by the author."
    """
    if source in AUTHORED:
        return AUTHORED_KIND
    if source in DERIVED:
        return DERIVED_KIND
    return UNKNOWN_KIND


def is_authored(source: str | None) -> bool:
    """Whether a STRICT verdict may stand on this function.

    🔴 `None` READS AS NOT-AUTHORED — but `None` can only be obtained by
    SETTING IT EXPLICITLY: the default of the `Room.function_source` field is
    `"declared"` (see the argument at the same place). A model assembled
    without this field carries the function named by its author in the input,
    and downgrading it would be dishonest in the other direction. An explicit
    `None` is set by exactly one producer — the L0 parser, when the room's
    name said NOTHING — and there it is the truth.
    """
    return function_authority(source) == AUTHORED_KIND


def describe(source: str | None) -> str:
    """A human-readable reason — for the violation's text and for `vacuous`."""
    kind = function_authority(source)
    if kind == AUTHORED_KIND:
        return f"функция помещения прочитана у автора ({source})"
    if kind == DERIVED_KIND:
        # 🔴 THERE HAVE BEEN TWO DERIVED KINDS SINCE 28.08.2026, AND THE
        # REASON MUST NAME ITS OWN. Until that day there was one branch, and
        # it printed "from furnishing (fixtures)" for any derived source. A
        # second source (`host_classifier`) would have made this text a LIE
        # in the voice of a measurement — our own named defect, "the
        # instrument is right, but about a different subject." The wording
        # for `fixtures` is left byte-for-byte: it has already shipped to
        # readers.
        if source == "host_classifier":
            return ("функция помещения названа ХОЗЯИНОМ (порт "
                    "design.room_classifier), потому что наш лексикон имени не "
                    "узнал: автор её не называл, это чужая догадка о значении "
                    "имени, поэтому вердикт не может быть блокирующим")
        return ("функция помещения ВЫВЕДЕНА нами из обстановки (fixtures): автор её "
                "не называл, признак косвенный, поэтому вердикт не может быть "
                "блокирующим")
    if source:
        return (f"источник функции {source!r} этому словарю неизвестен — род "
                f"считается неподтверждённым, пока источник не назван")
    return ("источник функции не назван (модель собрана до 22.08.2026 либо "
            "производителем, который его не проставляет)")
