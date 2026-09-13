"""A NAME IN A FOREIGN LANGUAGE MAKES A ROOM UNVERIFIABLE, NOT EXEMPT.

WHY THIS FILE, IN THE OWNER'S WORDS OF 28.08.2026: the product is universal,
"anyone can download it and deploy it themselves." That means rooms will be
named in any language, with any abbreviations and with typos, and they are
under no obligation to land in our lexicon.

🔴 AND FROM THIS FOLLOWS THE MAIN DECISION THAT THIS FILE GUARDS. Growing the
dictionary to completeness is a losing game: "you can't anticipate every
word, and if you decide to try, that's a pile of garbage in the code" (owner,
28.08). So the lexicon is DECLARED INCOMPLETE, and what makes it safe is not
completeness but exactly one property: **an unrecognized name is obligated to
sound off.** There is one property — and so it is verifiable, unlike an
endless list of words.

THE MEASUREMENT FOR WHOSE SAKE THIS FILE WAS CREATED (28.08.2026, A/B with a
control). One and the same model, the ONLY difference being the language of
the names: «Спальня/Гостиная/Кухня/Ванная/Прихожая» against
«Schlafzimmer/Wohnzimmer/Küche/Badezimmer/Flur».

    v1 (default)     DISAPPEARED  HAB030 ×3 «жилая/кухня без наружного окна»
                                   — a real finding, dropped silently
                      APPEARED    HAB004 blocking «Apartment has no прихожая»
                                   — yet the human NAMED the entry hall, it is
                                   «Flur»
                      SAID        nothing: no coverage section exists under v1

    v2                WITHDRAWN   HAB003 ×4 + HAB030 ×3 — nothing to judge by,
                                   not judged
                      SAID        HAB062 ×5 plus a note «покрытие классификации
                                   0 % ниже порога 75 %… правила жилья НЕ БЫЛИ
                                   применены осмысленно»

🔴 THE CONTROL HERE IS LOAD-BEARING, AND WITHOUT IT THE MEASUREMENT WOULD BE A
LIE. The first run gave "17 blockers for the German one" — and Russian names
on the same model give 16: the model is degenerate (no doors, no stairs), and
almost all of this is a property of the model, not of the language. Only the
DIFFERENCE between two runs that differ in one feature tells the truth.

WHAT EXACTLY IS BEING FIXED HERE IS A LAW, NOT A BEHAVIOR. v2's behavior, as
of the day this was written, already satisfies the law (20 coverage rules,
NOT_EVALUATED without a reason — zero). So the test fixes nothing; it takes
away the right to silently lose this property when the lexicon, the stages, or
the rules move on.

WHY THERE IS NOT A SINGLE ASSERTION HERE ABOUT v1. It would have fixed a
DEFECT in place: a test requiring that the finding be lost silently would turn
red on the day that it stops being lost. The v1 measurement is recorded above
as evidence — and remains evidence.

Run: KUKAI_CHECKER_V2=1 pytest \
    kir/checker/tests/test_a_foreign_name_is_unverifiable_not_exempt.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir.checker.classify import classify_room  # noqa: E402
from kir.checker.engine import run as run_engine  # noqa: E402
from kir.checker.spatial_model import (  # noqa: E402
    Level,
    Room,
    RoomFunction,
    Severity,
    SpatialModel,
)

#: One and the same building, named twice. The only difference is the language.
NAMES_RU = ("Спальня", "Гостиная", "Кухня", "Ванная", "Прихожая")
NAMES_DE = ("Schlafzimmer", "Wohnzimmer", "Küche", "Badezimmer", "Flur")


def _model(names: tuple[str, ...]) -> SpatialModel:
    """A model where EVERYTHING is identical except the names: the A/B control.

    `function_source=None` is the honest kind for a path where the name said
    nothing (see `design_check._name_function_source`): «ПРОЧЕЕ, потому что
    автор написал Балкон» and «ПРОЧЕЕ, потому что мы не поняли» are different
    claims.
    """
    return SpatialModel(
        building_id="AB",
        levels=[Level(id="L0", name="EG", elevation_mm=0, index=0)],
        rooms=[Room(id=f"r{i}", name=n, level_id="L0", function=classify_room(n),
                    area_m2=14.0, height_mm=2500, has_window=False,
                    window_area_m2=0.0, function_source=None)
               for i, n in enumerate(names)],
    )


def _fired(report) -> set[str]:
    return {v.rule_id for v in
            list(report.blocking) + list(report.warnings) + list(report.info)}


def test_the_lexicon_really_does_not_know_these_names():
    """The control's control: German names really are not recognized, Russian ones are.

    Without this check the whole file could turn green by construction on the
    day someone adds German keys to the lexicon: the tests below would keep
    passing while checking nothing anymore. The form "a degenerate input is
    green by construction" is our own named defect.
    """
    assert all(classify_room(n) is not RoomFunction.ПРОЧЕЕ for n in NAMES_RU)
    assert all(classify_room(n) is RoomFunction.ПРОЧЕЕ for n in NAMES_DE), (
        "немецкие имена стали опознаваться — переписать контроль на язык, "
        "которого лексикон не знает, иначе файл зелен по построению")


def test_a_rule_silenced_only_by_the_language_of_names_is_named_in_coverage():
    """🔴 THE FILE'S MAIN LAW: a rule that fell silent is obligated to be NAMED.

    A rule that fired on the Russian model and did not fire on the very same
    German one fell silent not because of the building but because of our own
    failure to understand the name. Such a rule is obligated to sit in the
    coverage section as NOT_EVALUATED and to NAME the reason. Silence without
    a reason is indistinguishable from "no violations" — and that is exactly
    what approval of a building nobody checked looks like.
    """
    ru, de = run_engine(_model(NAMES_RU)), run_engine(_model(NAMES_DE))
    silenced = _fired(ru) - _fired(de)
    assert silenced, ("ни одно правило не замолчало — контроль перестал "
                      "различать два прогона, проверять больше нечего")

    outcomes = {o.rule_id: o for o in de.coverage.outcomes}
    for rule_id in sorted(silenced):
        outcome = outcomes.get(rule_id)
        assert outcome is not None, (
            f"{rule_id} замолчало от смены языка и НЕ НАЗВАНО в покрытии вовсе")
        assert outcome.status.value != "evaluated", (
            f"{rule_id} не дало ни одной находки, но покрытие считает его "
            f"применённым — это и есть тихое одобрение")
        assert (outcome.reason or "").strip(), (
            f"{rule_id} названо не применённым БЕЗ ПРИЧИНЫ: читатель не узнает, "
            f"что виновато имя, а не здание")


def test_no_unevaluated_rule_anywhere_lacks_a_reason():
    """The same requirement, but for the WHOLE report, not just the diff of two.

    The difference between two runs catches the rules we thought to compare.
    This is all the rest.
    """
    report = run_engine(_model(NAMES_DE))
    mute = [o.rule_id for o in report.coverage.outcomes
            if o.status.value != "evaluated" and not (o.reason or "").strip()]
    assert not mute, f"правила не применены и молчат о причине: {mute}"


def test_an_unrecognised_habitable_room_is_flagged_not_exempted():
    """HAB062 on EVERY unrecognized room of habitable size, plus the coverage note.

    `ПРОЧЕЕ` is the claim "not habitable," and it silently switches off the
    habitability rules. For a room whose name we simply did not understand,
    this claim is false, and its price is the fitness check being dropped
    entirely. So an unrecognized name is obligated to yield a finding, and
    coverage must name, by name, whom it failed to judge.
    """
    report = run_engine(_model(NAMES_DE))
    flagged = {r for v in report.warnings if v.rule_id == "HAB062" for r in v.refs}
    assert flagged == {f"r{i}" for i in range(len(NAMES_DE))}, (
        f"HAB062 назвал не всех непонятых: {sorted(flagged)}")
    assert all(v.severity is Severity.WARNING
               for v in report.warnings if v.rule_id == "HAB062"), (
        "HAB062 обязано ПРЕДУПРЕЖДАТЬ, а не блокировать: непонятое нами имя — "
        "наша неполнота, а не порок здания")

    coverage = report.coverage
    assert coverage.classification_coverage == 0.0
    assert sorted(coverage.unclassified_room_ids) == [f"r{i}" for i in range(5)]
    assert any("classification coverage" in n for n in coverage.notes), (
        f"покрытие 0 %, а заметки об этом нет: {coverage.notes}")


# ------------------------------------------------------------------ ratchet

#: The lexicon's size on the day of the FREEZE (28.08.2026). The numbers are
#: not "current" — they are a DECISION, and they are only allowed to change
#: together with a justification.
FROZEN_LEXICON_SIZE = 19
FROZEN_V2_EXTENSION_SIZE = 33


def test_the_lexicon_is_frozen_and_growing_it_needs_an_argument():
    """🔴 RATCHET ON DICTIONARY GROWTH — THE OWNER'S DECISION OF 28.08.2026.

    "You can't anticipate every word, and if you decide to try, then that's a
    pile of garbage in the code." The same day's measurement: 81 names in
    eight languages, 6/81 recognized under v1 and 23/81 under v2, six
    languages out of eight — zero. And seven out of eight Russian misses are
    not typos but declensions, abbreviations, and punctuation: a word list
    does not cover what grows by ways of WRITING.

    So incompleteness here is DECLARED, and what makes it safe is the single
    property — "an unrecognized name sounds off" — that the tests above
    guard.

    WHY A NUMBER, AND NOT JUST A PARAGRAPH IN THE DOCSTRING. A paragraph is
    bypassed silently: the next session will "help" by topping up German keys,
    and nobody will notice, because nothing will turn red. A number forces the
    justification to be spoken aloud.

    WHAT TO DO IF THIS TEST TURNS RED. Do not fix the number. First answer
    whether the new key closes a NAME OBSERVED on a live model (then it is
    legitimate — fix the number together with the justification), or whether
    it was written "just in case" (then it is exactly the garbage the ratchet
    stands against). The general move is not a key but a classifier port: see
    the header of `classify.py`.
    """
    from kir.checker import classify

    assert len(classify.LEXICON) == FROZEN_LEXICON_SIZE, (
        f"основной лексикон вырос до {len(classify.LEXICON)} ключей "
        f"(заморожен на {FROZEN_LEXICON_SIZE}) — прочитай докстринг этого теста")
    assert len(classify.LEXICON_V2_EXTENSION) == FROZEN_V2_EXTENSION_SIZE, (
        f"расширение v2 выросло до {len(classify.LEXICON_V2_EXTENSION)} ключей "
        f"(заморожено на {FROZEN_V2_EXTENSION_SIZE}) — прочитай докстринг")
