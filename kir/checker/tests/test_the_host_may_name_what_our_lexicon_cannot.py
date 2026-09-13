"""WHAT OUR DICTIONARY DOES NOT KNOW IS NAMED BY THE HOST, AND THIS IS AN OUTPUT, NOT A WIRE.

WHY THE `ports.ROOM_CLASSIFIER` PORT, SET UP ON 28.08.2026. The product is
universal (the owner's own words): "anyone can download it and deploy it
themselves." That means room names will be in any language, with any
abbreviations and with typos. The same day's measurement, 81 names in eight
languages:

    v1, 19 keys      6/81      non-Russian languages  0/66
    v2, 52 keys     23/81      English 16/20, six languages  0/46

🔴 AND GROWING THE DICTIONARY IS FORBIDDEN — the owner's decision, in the same
place: "you can't anticipate every word, and if you decide to try, that's a
pile of garbage in the code." Seven out of eight Russian misses are not
typos but declensions, abbreviations, and punctuation: the misses grow by
ways of WRITING and are not closed off by a word list. So the lexicon is
declared incomplete (the ratchet is in the neighboring file), and the missing
piece is named by the HOST: with its own dictionary, a parameter of its own
template, an LLM. KIR does not choose with what — it only names what it
needs.

WHY THE JUDGE REMAINS DETERMINISTIC EVEN THOUGH AN LLM MAY STAND BEHIND THE
PORT. The port is called ONCE, at model assembly time, and the answer is
WRITTEN into `Room.function`. The judge reads what was written and never goes
back for a live guess: the same model gives the same verdict every time. The
answer's kind is `derived` (`function_provenance`), meaning a blocking
verdict cannot stand on it: the author never named the function.

WHAT IS GUARDED MOST STRICTLY HERE — A NO-OP RUN. This tree is installed in
the live production venv as EDITABLE (`KIR_PLAN.md` §0.1): there is neither a
build nor a release between saving a file and the running service. So a fix
that adds a capability is obligated to be BYTE-FOR-BYTE UNNOTICEABLE for as
long as nobody has hooked up the capability — and this is a condition of the
fix, not caution.

Run: pytest kir/checker/tests/test_the_host_may_name_what_our_lexicon_cannot.py -q
"""
from __future__ import annotations

import pytest

from kir import ports
from kir.checker import function_provenance as fp
from kir.checker.classify import (
    classify_names_via_host,
    classify_room,
    unrecognised_names,
)
from kir.checker.extractor import normalize
from kir.checker.flags import checker_v2_enabled
from kir.checker.spatial_model import RoomFunction

NAMES_DE = ("Schlafzimmer", "Wohnzimmer", "Küche", "Badezimmer", "Flur")

#: The answer that a host with its own country's dictionary (or with an LLM) would give.
GERMAN = {
    "Schlafzimmer": "жилая", "Wohnzimmer": "жилая", "Küche": "кухня",
    "Badezimmer": "санузел", "Flur": "прихожая",
}


class _Host:
    """The port's provider. `answer` — what it will return; `raises` — what it will throw."""

    def __init__(self, answer=None, raises: Exception | None = None):
        self.answer, self.raises = answer or {}, raises
        self.asked: tuple[str, ...] = ()

    def classify_room_names(self, names):
        self.asked = tuple(names)
        if self.raises is not None:
            raise self.raises
        return self.answer


@pytest.fixture
def host():
    """A provider that is REMOVED after the test.

    The port registry is global, and a provider left in place would leak
    into neighboring tests, where the port's absence is exactly what is
    being checked.
    """
    made: list[_Host] = []

    def install(answer=None, raises=None):
        h = _Host(answer, raises)
        ports.register(ports.ROOM_CLASSIFIER, lambda: h)
        made.append(h)
        return h

    yield install
    ports.unregister(ports.ROOM_CLASSIFIER)


def _raw(names=NAMES_DE) -> dict:
    return {
        "building_id": "DE",
        "levels": [{"id": "L0", "name": "EG", "elevation_mm": 0, "index": 0}],
        "rooms": [{"id": f"r{i}", "name": n, "number": str(i), "level_id": "L0",
                   "area_m2": 14.0, "height_mm": 2500.0, "boundary": []}
                  for i, n in enumerate(names)],
        "doors": [], "windows": [], "stairs": [],
    }


# ------------------------------------------------------- NO-OP RUN

def test_without_a_supplier_nothing_changes_at_all():
    """🔴 WITHOUT A PROVIDER — EXACTLY THE PRIOR BEHAVIOR, rule for rule.

    Before 28.08 the live read did exactly two things unconditionally:
    `function = classify_room(имя)` and `function_source = "room_name"`. This
    is exactly what is checked here — not "looks similar," but the very same
    expression it was written with.
    """
    assert ports.ROOM_CLASSIFIER in ports.missing(), (
        "поставщик протёк из соседнего теста — проверка стала бессмысленной")
    for room in normalize(_raw())["rooms"]:
        assert room["function"] == classify_room(room["name"]).value
        assert room["function_source"] == "room_name"


def test_the_helper_is_empty_without_a_supplier():
    assert classify_names_via_host(NAMES_DE) == {}


# ------------------------------------------------------- WORKING WITH THE HOST

def test_the_host_names_what_the_lexicon_could_not(host):
    """The host named it — the function is recorded, and its kind is `derived`, not `authored`."""
    h = host(GERMAN)
    rooms = {r["name"]: r for r in normalize(_raw())["rooms"]}

    assert rooms["Schlafzimmer"]["function"] == "жилая"
    assert rooms["Küche"]["function"] == "кухня"
    assert rooms["Flur"]["function"] == "прихожая"
    for r in rooms.values():
        assert r["function_source"] == "host_classifier"
        assert fp.function_authority(r["function_source"]) == fp.DERIVED_KIND
        assert not fp.is_authored(r["function_source"]), (
            "функция, названная хозяином, получила право на СТРОГИЙ вердикт — "
            "а автор её не называл")
    assert h.asked == tuple(sorted(NAMES_DE)), (
        f"спрошено не то и не в том порядке: {h.asked}")


def test_a_name_the_lexicon_knows_is_never_sent_to_the_host(host):
    """The host is asked ONLY about the unrecognized — and «Балкон» does not
    belong to the unrecognized.

    The lexicon KNOWS «Балкон» as reliably non-habitable
    (`is_known_nonhabitable`), and handing it over for renaming would mean
    giving the host the right to overturn our own knowledge.
    """
    h = host(GERMAN)
    normalize(_raw(("Спальня", "Балкон", "Küche")))
    assert h.asked == ("Küche",), f"спрошено лишнее: {h.asked}"


def test_the_hosts_answer_never_overrides_what_we_did_understand(host):
    """The host has no right to rename a room that we understood ourselves."""
    host({"Спальня": "тех", "Küche": "кухня"})
    rooms = {r["name"]: r for r in normalize(_raw(("Спальня", "Küche")))["rooms"]}
    assert rooms["Спальня"]["function"] == "жилая"
    assert rooms["Спальня"]["function_source"] == "room_name"


# ------------------------------------------------------- THREE REJECTIONS

@pytest.mark.parametrize("answer, raises, case", [
    ({"Küche": "кухонька"}, None, "значения нет в RoomFunction"),
    ({"Кухня": "кухня"}, None, "имя, которого не спрашивали"),
    (None, RuntimeError("хозяин упал"), "поставщик бросил исключение"),
])
def test_a_bad_answer_leaves_the_room_unclassified_and_therefore_loud(
        host, answer, raises, case):
    """🔴 THE REJECTED DOES NOT BECOME SILENCE — and that is the whole point.

    There are three ways to get an unusable answer, and all three end the
    same way: the room stays UNCLASSIFIED. And the unclassified sounds off —
    HAB062 and the coverage section name such rooms by name (neighboring
    file). This is exactly why rejecting here is safe: there is nothing left
    to lose silently.

    The reverse order would be a defect: letting someone else's typo into
    `RoomFunction`, or letting someone else's breakage bring down the
    building's check.
    """
    host(answer, raises)
    room = normalize(_raw(("Küche",)))["rooms"][0]
    assert room["function"] == RoomFunction.ПРОЧЕЕ.value, case
    assert room["function_source"] == "room_name", case


# ------------------------------------------------------- THE QUESTION'S BOUNDARY

def test_unrecognised_names_asks_only_about_what_we_stayed_silent_on():
    assert unrecognised_names(
        ["Schlafzimmer", "Спальня", "Балкон", "", None, "Küche", "Küche"]
    ) == ("Küche", "Schlafzimmer")


def test_the_port_is_declared_and_optional():
    """The port is declared in `ALL_PORTS` and is asked with `ask`, not `need`.

    `need` would throw `PortMissing` for anyone who has not supplied a
    classifier, that is, for everyone today. Absence here is a REGULAR
    answer.
    """
    assert ports.ROOM_CLASSIFIER in ports.ALL_PORTS
    assert ports.ask(ports.ROOM_CLASSIFIER) is None


def test_the_coverage_note_names_whose_derivation_it_is(host):
    """🔴 THE NOTE ABOUT DERIVED COVERAGE IS OBLIGATED TO NAME ITS OWN SOURCE.

    The existing law (`engine.py`, 22.08.2026) already refuses on its own to
    place a positive verdict on a classification that the author did not
    name — and the port got this for free, not a single line of rules was
    needed. But the note's text was written when there was only ONE derived
    kind, and it said «ВЫВЕДЕНА нами из обстановки» unconditionally. For a
    function named by the host, both words are wrong.

    This is the form "the instrument is right, but about a different
    subject": the note was not lying about the NUMBER, it was lying about the
    SOURCE — and a reader who was told «из обстановки» will go looking for
    toilet fixtures exactly where their own classifier was standing.
    """
    # 🔴 THE LEVER IS ASKED OF THE PRODUCT, NOT READ BY NAME (04.09.2026).
    # This used to say `os.environ.get("KUKAI_CHECKER_V2", "0") != "1"`, and
    # that is TWO misses in one line. First: the value has two names — the
    # new `KIR_CHECKER_V2` and the former `KUKAI_CHECKER_V2` (`kir/env.py`),
    # while ONLY the former was being read: an operator who turned v2 on
    # under the new name got skipped anyway. Second, and this one costs
    # more: the lever's default became "on" on 01.09.2026
    # (`checker_v2_enabled`), while here the default stayed `"0"` — meaning
    # that on a CLEAN environment the section was ALWAYS skipped, and this
    # is measured: `pytest <this file>` gave `1 skipped` (04.09), meaning the
    # assertions about the coverage note had not run a single time since
    # 01.09.
    #
    # What must be asked is the very same thing the judge asks: one door, one
    # default, and flipping the lever cannot drift apart from being skipped.
    if not checker_v2_enabled():
        pytest.skip("раздел покрытия существует только под checker v2 "
                    "(рычаг выключен: KIR_CHECKER_V2=0)")

    from kir.checker.engine import run as run_engine
    from kir.checker.spatial_model import SpatialModel

    host(GERMAN)
    report = run_engine(SpatialModel(**normalize(_raw())))
    derived_notes = [n for n in report.coverage.notes if "ВЫВЕДЕНА" in n]
    assert derived_notes, (
        f"функции названы хозяином у всех 5 помещений, а заметки о том, что "
        f"порог взят НЕ авторской классификацией, нет: {report.coverage.notes}")
    note = derived_notes[0]
    assert "host_classifier" in note, f"источник вывода не назван: {note}"
    assert "из обстановки" not in note, (
        f"заметка называет обстановку там, где выводил хозяин: {note}")
