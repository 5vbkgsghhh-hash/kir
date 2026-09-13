"""RU room-function lexicon (design §4). Tunable 'common sense' of naming.
Order matters: more specific keys first (checked as ordered WORD-START matches — see
``_matches_at_word_start``; until 18.08.2026 this was a bare substring match).

Used by the EXTRACTOR when it builds a SpatialModel from free-text Revit room names: it
calls classify_room(name, explicit=<stamped function, if any>) to set Room.function.
Under checker v2 (flags.checker_v2_enabled) the lexicon is EXTENDED (common RU names +
EN equivalents) and derive.py additionally uses classify_room to cross-check declared
functions: a room DECLARED 'прочее' whose NAME classifies to a real function is
upgraded, so 'Bedroom 1' can no longer bypass the habitability rules (roadmap probe E2).

KNOWN_NONHABITABLE names legitimately classify as ПРОЧЕЕ (балкон, лоджия, шахта…) and
are exempt from the HAB062 'unclassified habitable-sized room' warning — unknown ≠ known
non-habitable.

🔴 THIS LEXICON HAS THREE PRODUCERS, AND FOR ONE OF THEM THE INPUT IS ALWAYS EMPTY.
Measured 19.08.2026 against the decompile corpus, by name:

    design_check:742  spatial_model_from_l0      name from L0            🔴 ALWAYS EMPTY
    design_check:1799 spatial_model_from_program  name from the program   present
    checker/extractor:107 live Revit read         name from the document  present

The numbers: `k2_ar_rd_v15` — 2442 rooms, WITH A NAME **0**; `sob62_r23_v5` —
120, with a name 0; `snowdon_plumb_v5` — 54, with a name 0. All have
`params: {}`. That is, on the DECOMPILE PATH this lexicon classifies NOT A
SINGLE room, and every kind except OTHER is unreachable there by
construction.

WHAT FOLLOWS FROM THIS FOR THE READER, AND THIS IS NOT NITPICKING. Every
number about kinds of rooms ("215 corridors," "280 halls," "1087 singles")
describes an INPUT, not a building, and cannot be carried over between
inputs. The defect "a hall and an apartment's entryway fall into the same
kind" is REAL on live reading and on the program — and does not show up at
all on decompile, because there are no names there. Accordingly, a fix for
this defect is measured on the SAME input where it was removed; the
decompile corpus cannot confirm it either way.

The gap, moreover, is NAMED, not general: for `OST_Walls` the parameters
make it through (15,341 of 15,341), for `OST_Rooms` — 0 of 2442. So this is
a defect of room CAPTURE, and it belongs to the decompile path, not to this
dictionary.

🔴🔴 THIS LEXICON IS DECLARED INCOMPLETE, AND GROWING IT TO COMPLETENESS IS
FORBIDDEN. THE OWNER'S DECISION, 28.08.2026, verbatim:

    "I'm not sure we'll always land inside your dictionary, or that you can
    anticipate every word there is. I even think that approach is
    mistaken — assuming you'll anticipate everything. And if you decide to
    anticipate it, that's a pile of garbage in the code."

A MEASUREMENT THAT CONFIRMED THIS WITH A NUMBER (28.08.2026, 81 names in eight languages):

    v1, 19 keys      6/81      non-Russian languages   0/66
    v2, 52 keys     23/81      English 16/20, the other six languages 0/46

And here is what turned out to be inside the Russian misses — SEVEN OF
EIGHT ARE NOT TYPOS:

    «Спальни 2»    the key «спальня» is not a prefix of the word «спальни»   DECLENSION
    «спальная»     the same
    «Кор-р», «Комн. отдыха», «С.У.»                                          ABBREVIATIONS
    «Сан.узел»                                                               PUNCTUATION
    «Гостинная»                                                              SPELLING
    «Спльня»                                                                 and one typo

That is, the misses do not grow along a list of words but along ways of
writing, and cannot be closed off by a list in principle. The keys here are
inconsistent even among themselves: some are stems («кладов», «душев»,
«уборочн»), some are full forms («спальня», «гостиная», «комната»). This is
NOT a defect to fix: there is nothing to fix while the mechanism itself is
wrong.

WHAT MAKES THE INCOMPLETENESS SAFE — ONE PROPERTY INSTEAD OF AN ENDLESS
LIST: **an unrecognized name MUST SPEAK UP.** `ПРОЧЕЕ` is the claim
"non-habitable," and it quietly lifts every fitness rule; for a name we
simply didn't understand, that claim is FALSE. This property is guarded by
`checker/tests/test_a_foreign_name_is_unverifiable_not_exempt.py`; the A/B
measurement with its control is recorded there too.

WHERE TO GO INSTEAD OF GROWING THE DICTIONARY — three layers, none of them about words:

    forward path (the building is written by an LLM)   TYPE the function,
                                    don't guess it from the free-text string
                                    `create_room.name`
    decompile path (a foreign model)   name the function through a PORT
                                    (`kir/ports.py`), the host substitutes
                                    whatever it likes, up to and including an
                                    LLM; the answer is written as DATA with
                                    kind `function_source`, the judge reads
                                    what was recorded and stays deterministic
    what nobody understood         HAB062 + the coverage section: say so out loud

The lexicon itself stays — but as a FAST LANE that is ALLOWED to miss, not
as a mechanism. A key is added only if it closes a name OBSERVED on a live
model; a ratchet on the list's size stands in the same test and exists
precisely so this paragraph cannot be silently bypassed."""

import re

from kir.checker.flags import checker_v2_enabled
from kir.checker.spatial_model import RoomFunction

# Ordered: first key matching AT A WORD START wins. All keys lowercase.
LEXICON: list[tuple[str, RoomFunction]] = [
    ("лестничная клетка", RoomFunction.ЛЕСТНИЦА),
    ("лестница", RoomFunction.ЛЕСТНИЦА),
    # 🔴 ADDED 18.08.2026 TOGETHER WITH THE MATCHER CHANGE, AND ONLY THANKS
    # TO IT. This key could NOT have been introduced as a substring match: it
    # would have caught «ба-лк-он» ("balcony") and «по-лк-а» ("shelf")
    # (verified by execution, see `_matches_at_word_start`). The cost of its
    # absence, measured 18.08 on `k2_ar_rd_v15`: 85 rooms named «ЛК 2.1 /
    # ЛК 2.2» went into ПРОЧЕЕ — 85 of 140 unrecognized rooms in total — and
    # because of this, stairs did not link up with floors.
    ("лк", RoomFunction.ЛЕСТНИЦА),
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
    ("уборочн", RoomFunction.ТЕХ),          # utility closet room
    ("инвентар", RoomFunction.ТЕХ),
    ("гардероб", RoomFunction.ТЕХ),
    ("кладов", RoomFunction.ТЕХ),           # storage room / closet
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

#: 🔴 A SECOND LEXICON, AND ITS KIND IS DIFFERENT: THE FURNISHINGS NAME THE
#: FUNCTION, NOT THE AUTHOR.
#:
#: WHY IT WAS CREATED, measured 22.08.2026 (MNVNK). `ROOM_NAME` equals the
#: string «Помещение» for 1102 of 1102 rooms — the rooms are numbered but NOT
#: NAMED, and the name lexicon above classifies NOT A SINGLE one. Seven rules
#: stay silent: HAB020, HAB021, HAB030, HAB031 (not one function has a
#: threshold) and HAB002/003/004/042 (the apartment's derivation rests on
#: name classification). Yet the furnishings ARE THERE in the decompile:
#: 1112 `OST_PlumbingFixtures` and 1983 `OST_Furniture`, all with a point and
#: a level.
#:
#: 🔴 AND THIS IS A DERIVATION, NOT A WIRE-THROUGH. A function named by a
#: toilet fixture is NOT EQUAL to a function named by the author: the kind is
#: written into `Room.function_source` (`fixtures`), the kind dictionary is
#: `function_provenance`, and a rule based on a derived kind does not block.
#: Keeping both dictionaries in one file is deliberate: they are two answers
#: to one question, "what is this room called," and they must not drift
#: apart.
#:
#: WHAT DID NOT MAKE IT IN HERE, AND WHY — a boundary of the dictionary, not
#: an oversight. Of MNVNK's 23 furniture types, 8 are named: «Шкаф_2
#: фасада» (722 pcs.) stands in both the bedroom and the entryway; «Тумба»
#: is under the TV and in the bathroom alike; «500х400 мм» names nothing at
#: all; shower trays are named «Прямой_1200х900мм». A key that guesses is
#: worse than no key: it puts a guess into the measurement's own voice.
#: Ordering follows `LEXICON`: the first key that matches AT THE START OF A
#: WORD wins.
FIXTURE_LEXICON: list[tuple[str, RoomFunction]] = [
    # a wet point is the single most unambiguous marker in a residential building
    ("унитаз", RoomFunction.САНУЗЕЛ),
    ("биде", RoomFunction.САНУЗЕЛ),
    ("писсуар", RoomFunction.САНУЗЕЛ),
    ("ванна", RoomFunction.САНУЗЕЛ),
    ("душев", RoomFunction.САНУЗЕЛ),
    ("полотенцесушител", RoomFunction.САНУЗЕЛ),
    # 🔴 «раковина» ("sink") IS A BATHROOM, and that is a decision, not an
    # obvious fact: in this project the kitchen sink is modeled inside
    # «Кухонного фронта» ("Kitchen Front"), it does not stand as a separate
    # sink fixture. The marker is conflict-prone by construction, and
    # exactly because of that, the conflict IS COUNTED, not silently
    # resolved in favor of the first key.
    ("раковина", RoomFunction.САНУЗЕЛ),
    # kitchen
    ("кухня", RoomFunction.КУХНЯ),
    ("кухонн", RoomFunction.КУХНЯ),
    ("мойка", RoomFunction.КУХНЯ),
    ("варочн", RoomFunction.КУХНЯ),
    ("посудомоеч", RoomFunction.КУХНЯ),
    ("холодильник", RoomFunction.КУХНЯ),
    # living room
    ("двухспальная", RoomFunction.ЖИЛАЯ),
    ("полутораспальная", RoomFunction.ЖИЛАЯ),
    ("односпальн", RoomFunction.ЖИЛАЯ),
    ("кровать", RoomFunction.ЖИЛАЯ),
    ("диван", RoomFunction.ЖИЛАЯ),
    ("журнальн", RoomFunction.ЖИЛАЯ),
    ("рабочий стол", RoomFunction.ЖИЛАЯ),
]


def classify_by_fixtures(type_names) -> tuple[RoomFunction | None,
                                              tuple[RoomFunction, ...]]:
    """A room's function BY ITS FURNISHINGS: `(kind | None, all recognized kinds)`.

    TWO values are returned, not one, and this is load-bearing: the second
    tuple is the evidence by which the caller tells "one marker" apart from
    "several markers." On conflict the first element is `None`: the
    furnishings named two words, and there is NOTHING to choose between
    them with — taking the first would mean turning uncertainty into an
    answer. Measured on MNVNK: a conflict for 5 of the 291 rooms whose
    furnishings name anything at all (a toilet fixture and a kitchen front
    in the same boundary).

    Uses the same matcher as name-based classification
    (`_matches_at_word_start`): two neighboring decisions about ONE name,
    diverging in their comparison method, are our named defect (18.08.2026).
    """
    seen: list[RoomFunction] = []
    for name in type_names:
        low = (name or "").casefold()
        if not low:
            continue
        for key, func in FIXTURE_LEXICON:
            if _matches_at_word_start(low, key):
                if func not in seen:
                    seen.append(func)
                break
    if len(seen) == 1:
        return seen[0], tuple(seen)
    return None, tuple(seen)


#: Names that are legitimately ПРОЧЕЕ (non-habitable by design): they suppress the
#: HAB062 'unclassified habitable-sized room' warning but never gain thresholds.
KNOWN_NONHABITABLE: tuple[str, ...] = (
    "балкон", "лоджия", "терраса", "веранда", "шахта", "ниша", "приямок",
    "balcony", "loggia", "terrace", "shaft", "void",
)


def is_known_nonhabitable(name: str) -> bool:
    """True iff the room NAME marks a known non-habitable space (балкон/лоджия/…).

    Uses the same matcher as classification (18.08.2026): two neighboring
    decisions about ONE name, diverging in their comparison method, are our
    named defect. The change here was also verified against the corpus:
    44,684 names, ZERO discrepancies with the previous behavior.
    """
    low = name.casefold()
    return any(_matches_at_word_start(low, key) for key in KNOWN_NONHABITABLE)


#: A LETTER — a word boundary is defined BY IT, not by whitespace: the
#: names «ЛК 2.1» and «С/У 7» are cut by digits, dots, and slashes, and all
#: of these must count as a boundary.
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def _matches_at_word_start(low: str, key: str) -> bool:
    """Does ``key`` occur in ``low`` AT THE START OF A WORD (not just anywhere).

    🔴 WHY THIS REPLACED ``key in low`` ON 18.08.2026 — THE OWNER'S DECISION.

    A substring match doesn't allow a SHORT key: «лк» would intercept
    «балкон» ("balcony") and «полку» ("shelf"), so stairwells named «ЛК
    2.1» went entirely unrecognized. A word-start match lifts the ban:
    PREFIX keys keep working (the key «тех» catches «Техническое», the key
    «кладов» catches «кладовая» and «кладовка», because the WORD starts
    with the key), while a mid-word match no longer counts.

    What matters here is EXACTLY the start of the word, not equality to the
    whole word: had we split the name into words and compared them to the
    key in full, we would have killed prefix keys, multi-word keys
    («лестничная клетка»), and keys with a non-letter inside («с/у») all at
    once.

    THE COST OF THE CHANGE IS MEASURED, NOT ASSUMED. A run on 18.08 over the
    entire decompile corpus: **28 decompiles, 44,684 room names, 8453
    distinct — ZERO DISCREPANCIES WITH THE PREVIOUS MATCHER.** Not one of
    the 51 keys in either list relied on a mid-word match. That is, the
    change is safe not by reasoning but by the corpus.

    🔴 AND THIS IS A FACT ABOUT THE CORPUS, NOT ABOUT THE LEXICON. These
    buildings simply have no names like «Балкон» that collide with short
    keys. The value of the fix is not that it changed anything here (it
    changed nothing), but that it grants the RIGHT to introduce short keys
    anywhere. Verified by execution:

        «Балкон 1» key «лк»  substring YES · word-start NO
        «Полка 2»  key «лк»  substring YES · word-start NO
        «ЛК 2.1 3» key «лк»  substring YES · word-start YES

    As a side effect this also fixes the already-existing key «зал»: as a
    substring it caught «Вокзал» ("station") and «Спортзал» ("gym"), by
    word-start it does not. No such names turned up in the corpus, but the
    trap was real.
    """
    at = low.find(key)
    while at != -1:
        if at == 0 or not _LETTER.match(low[at - 1]):
            return True
        at = low.find(key, at + 1)
    return False


def classify_names_via_host(names) -> dict[str, RoomFunction]:
    """A THIRD ANSWER TO THE SAME QUESTION: the function is named by the HOST, not by our dictionary.

    The first two sit above and deliberately in this same file: the name
    (`LEXICON`) and the furnishings (`FIXTURE_LEXICON`). This one is for
    names neither of them knows: a foreign language, an abbreviation, a
    typo. There are three kinds of answers, and they must not drift apart,
    which is why they live together.

    Returns ONLY what the host actually named. With no provider — an empty
    dict, and that is a REGULAR answer (`ports.ask`), not a refusal: then
    everything works exactly as it did before the port existed, byte for
    byte.

    🔴 THREE THINGS THAT ARE DISCARDED HERE, AND WHY THAT IS NOT A LOSS.

    1. A value not in `RoomFunction`. A typo in a foreign answer has no
       right to become a room's function.
    2. A name we did not ask about. Otherwise the host could append rooms
       to the model that aren't actually in it.
    3. Any exception from the provider. A foreign failure has no right to
       bring down the building check — the same convention as the other
       optional ports in `serving.py`.

    None of the three cases produces silence: what's discarded remains
    UNCLASSIFIED, and the unclassified speaks up — HAB062 plus the coverage
    section name such rooms by name. This exact property is what makes the
    dictionary's incompleteness safe, so there is nothing to lose here.

    In a batch, not one at a time: 44,684 room names in the decompile
    corpus, 8453 distinct (measured 18.08.2026). Names are sorted — the
    same input gets the same request.
    """
    from kir import ports  # local: `ports` doesn't pull in anything, but there's no reason to load it
                           # for the sake of a lexicon that's used without ports either

    wanted = tuple(sorted({n for n in (x or "" for x in names) if n}))
    if not wanted:
        return {}
    host = ports.ask(ports.ROOM_CLASSIFIER)
    if host is None:
        return {}
    try:
        answer = host.classify_room_names(wanted)
    except Exception:
        return {}
    if not isinstance(answer, dict):
        return {}

    known = {f.value: f for f in RoomFunction}
    asked = set(wanted)
    out: dict[str, RoomFunction] = {}
    for name, value in answer.items():
        if name in asked and isinstance(value, str) and value in known:
            out[name] = known[value]
    return out


def unrecognised_names(names) -> tuple[str, ...]:
    """Names it makes sense to ask the host about: distinct and unrecognized.

    "Unrecognized" is not the same as `ПРОЧЕЕ`: the lexicon KNOWS «Балкон»
    ("balcony") as known non-habitable, and there is nothing to ask about it
    (`is_known_nonhabitable`). What needs asking is exactly what we stayed
    silent about.
    """
    return tuple(sorted({
        n for n in (x or "" for x in names)
        if n and classify_room(n) is RoomFunction.ПРОЧЕЕ and not is_known_nonhabitable(n)
    }))


def classify_room(name: str, explicit: RoomFunction | str | None = None) -> RoomFunction:
    """Prefer an explicit stamped function; else derive from name via LEXICON (extended
    under checker v2); else RoomFunction.ПРОЧЕЕ (design §4)."""
    if explicit is not None:
        return explicit if isinstance(explicit, RoomFunction) else RoomFunction(explicit)
    low = name.casefold()
    lexicon = LEXICON + LEXICON_V2_EXTENSION if checker_v2_enabled() else LEXICON
    for key, func in lexicon:
        if _matches_at_word_start(low, key):
            return func
    return RoomFunction.ПРОЧЕЕ
