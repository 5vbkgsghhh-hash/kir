"""RU room-function lexicon (design §4). Tunable 'common sense' of naming.
Order matters: more specific keys first (checked as ordered substring matches).

Used by the EXTRACTOR when it builds a SpatialModel from free-text Revit room names: it
calls classify_room(name, explicit=<stamped function, if any>) to set Room.function.
Under checker v2 (flags.checker_v2_enabled) the lexicon is EXTENDED (common RU names +
EN equivalents) and derive.py additionally uses classify_room to cross-check declared
functions: a room DECLARED 'прочее' whose NAME classifies to a real function is
upgraded, so 'Bedroom 1' can no longer bypass the habitability rules (roadmap probe E2).

KNOWN_NONHABITABLE names legitimately classify as ПРОЧЕЕ (балкон, лоджия, шахта…) and
are exempt from the HAB062 'unclassified habitable-sized room' warning — unknown ≠ known
non-habitable."""

from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.spatial_model import RoomFunction

# Ordered: first matching substring wins. All keys lowercase.
LEXICON: list[tuple[str, RoomFunction]] = [
    ("лестничная клетка", RoomFunction.ЛЕСТНИЦА),
    ("лестница", RoomFunction.ЛЕСТНИЦА),
    ("лифтовой холл", RoomFunction.ЛИФТ_ХОЛЛ),
    ("лифт", RoomFunction.ЛИФТ_ХОЛЛ),
    ("входная группа", RoomFunction.ВХОДНАЯ_ГРУППА),
    ("прихожая", RoomFunction.ПРИХОЖАЯ),
    ("коридор", RoomFunction.КОРИДОР),
    ("кухня-гостиная", RoomFunction.КУХНЯ),
    ("кухня", RoomFunction.КУХНЯ),
    ("санузел", RoomFunction.САНУЗЕЛ),
    ("ванная", RoomFunction.САНУЗЕЛ),
    ("с/у", RoomFunction.САНУЗЕЛ),
    ("туалет", RoomFunction.САНУЗЕЛ),
    ("спальня", RoomFunction.ЖИЛАЯ),
    ("гостиная", RoomFunction.ЖИЛАЯ),
    ("кабинет", RoomFunction.ЖИЛАЯ),
    ("жилая", RoomFunction.ЖИЛАЯ),
    ("тех", RoomFunction.ТЕХ),
]

# v2 extension (gated): common RU names the 19-entry lexicon missed + EN equivalents.
# Ordered like LEXICON (specific service names BEFORE the broad habitable words, so
# 'Комната уборочного инвентаря' hits ТЕХ before 'комната' can claim it); consulted
# AFTER the v1 list so v1 mappings keep priority.
LEXICON_V2_EXTENSION: list[tuple[str, RoomFunction]] = [
    # RU — wet / service (specific first)
    ("душевая", RoomFunction.САНУЗЕЛ),
    ("уборная", RoomFunction.САНУЗЕЛ),
    ("уборочн", RoomFunction.ТЕХ),          # комната уборочного инвентаря
    ("инвентар", RoomFunction.ТЕХ),
    ("гардероб", RoomFunction.ТЕХ),
    ("кладов", RoomFunction.ТЕХ),           # кладовая / кладовка
    ("постирочн", RoomFunction.ТЕХ),
    ("электрощитовая", RoomFunction.ТЕХ),
    ("венткамера", RoomFunction.ТЕХ),
    ("насосная", RoomFunction.ТЕХ),
    ("котельная", RoomFunction.ТЕХ),
    ("тамбур", RoomFunction.КОРИДОР),
    ("холл", RoomFunction.КОРИДОР),
    # RU — habitable (broad words last)
    ("детская", RoomFunction.ЖИЛАЯ),
    ("зал", RoomFunction.ЖИЛАЯ),
    ("комната", RoomFunction.ЖИЛАЯ),
    # EN equivalents (live models with English naming bypassed EVERYTHING before)
    ("stair", RoomFunction.ЛЕСТНИЦА),
    ("elevator", RoomFunction.ЛИФТ_ХОЛЛ),
    ("lift", RoomFunction.ЛИФТ_ХОЛЛ),
    ("entrance", RoomFunction.ВХОДНАЯ_ГРУППА),
    ("lobby", RoomFunction.ВХОДНАЯ_ГРУППА),
    ("corridor", RoomFunction.КОРИДОР),
    ("hallway", RoomFunction.КОРИДОР),
    ("bedroom", RoomFunction.ЖИЛАЯ),
    ("living", RoomFunction.ЖИЛАЯ),
    ("study", RoomFunction.ЖИЛАЯ),
    ("kitchen", RoomFunction.КУХНЯ),
    ("bathroom", RoomFunction.САНУЗЕЛ),
    ("toilet", RoomFunction.САНУЗЕЛ),
    ("wc", RoomFunction.САНУЗЕЛ),
    ("laundry", RoomFunction.ТЕХ),
    ("storage", RoomFunction.ТЕХ),
    ("closet", RoomFunction.ТЕХ),
]

#: Names that are legitimately ПРОЧЕЕ (non-habitable by design): they suppress the
#: HAB062 'unclassified habitable-sized room' warning but never gain thresholds.
KNOWN_NONHABITABLE: tuple[str, ...] = (
    "балкон", "лоджия", "терраса", "веранда", "шахта", "ниша", "приямок",
    "balcony", "loggia", "terrace", "shaft", "void",
)


def is_known_nonhabitable(name: str) -> bool:
    """True iff the room NAME marks a known non-habitable space (балкон/лоджия/…)."""
    low = name.casefold()
    return any(key in low for key in KNOWN_NONHABITABLE)


def classify_room(name: str, explicit: RoomFunction | str | None = None) -> RoomFunction:
    """Prefer an explicit stamped function; else derive from name via LEXICON (extended
    under checker v2); else RoomFunction.ПРОЧЕЕ (design §4)."""
    if explicit is not None:
        return explicit if isinstance(explicit, RoomFunction) else RoomFunction(explicit)
    low = name.casefold()
    lexicon = LEXICON + LEXICON_V2_EXTENSION if checker_v2_enabled() else LEXICON
    for key, func in lexicon:
        if key in low:
            return func
    return RoomFunction.ПРОЧЕЕ
