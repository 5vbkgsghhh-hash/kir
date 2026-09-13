"""THE DOCUMENT'S CATALOG IN THE SCRIPT'S HANDS — enumeration becomes A
RULE.

THE MEASUREMENT THIS WAS DONE FOR (14.08.2026, `data/telemetry/
kir_rejections.jsonl`, 1558 lines = 314 authoring ATTEMPTS, 16.07–14.08):
"blindness to the catalog" — **29.9% of attempts**, the largest class of
refusals. Before this wave, the authoring script's namespace held 98
names, and NOT ONE read the document the script writes into: `spec()`
prints the registry, `course()` the course, `preview()` draws the
PROGRAM, `design_check()` judges that same program. The author had to
guess type, level, and grid names.

WHAT IS CHECKED HERE, AND WHAT IS NOT PROMISED.

What is checked is that the catalog ARRIVES and that enumeration turns
into a rule: `for lvl in model.levels()` instead of hand-listed floors.
This is precisely the shift of attention from the API to the geometry —
not "fewer refusals," which is only a consequence.

Building geometry is NOT promised: the grounding snapshot carries
CATALOGS and not a single wall or room (measured — `OfClass(typeof(Wall))`
and `OST_Rooms` appear in `open_model.py` ZERO times). "A room without a
window" is not answered by this object, and no method should hint that it
is.

THE FILE'S MAIN TEST IS NOT THE FIRST BUT THE LAST: authority remains
with grounding. The catalog is a snapshot at the moment of reading; if it
is stale, the program still re-grounds against a FRESH snapshot and
refuses. Without this test, the new capability would be a new way to
build something wrong, silently.
"""
from __future__ import annotations

import asyncio
import unittest

from kir import serving
from kir.compiler import compile_program
from kir.sandbox import ModelCatalog, execute_author_script, _model_pools

CATALOGUE = {
    "levels": [
        {"id": 1, "name": "Этаж 1", "elevation_mm": 0},
        {"id": 2, "name": "Этаж 2", "elevation_mm": 3000},
        {"id": 3, "name": "Этаж 3", "elevation_mm": 6000},
    ],
    "grids": [{"id": 7, "name": "А"}, {"id": 8, "name": "Б"}],
    "wall_types": [{"id": 40, "name": "Кирпич 380", "instances": 500},
                   {"id": 41, "name": "ГКЛ 100", "instances": 12}],
    # Internal fields: facts about the READ, not about the building. Must not be visible to the script.
    "__document_fingerprint": {"title": "Дом"},
    "levels__total": 3,
    "levels__truncated": True,
}

#: The very transition this is all for: the floor is NOT hand-listed but derived from the catalog.
RULE_SCRIPT = """
envelope(intent="по этажу на каждый уровень документа")
for lvl in model.levels():
    create_wall(p0_mm=[0, 0], p1_mm=[6000, 0],
                level=by_name(lvl["name"]), height_mm=3000)
"""


def test_the_script_writes_a_rule_over_the_real_levels():
    """Three levels in the document -> three walls, and not a single floor was hand-listed."""
    result = execute_author_script(RULE_SCRIPT, model=CATALOGUE)
    assert result.ok, result.refusal and result.refusal.as_dict()
    assert len(result.ops) == len(CATALOGUE["levels"]) == 3
    named = [op["level"]["value"] for op in result.ops]
    assert named == ["Этаж 1", "Этаж 2", "Этаж 3"], named


def test_without_a_catalogue_the_name_still_exists_and_says_why():
    """A missing name would read as "no such capability exists" — but it
    does.

    So `model` is placed ALWAYS, and an empty catalog answers with a
    named reason the model can read and use to fix its next turn.
    """
    result = execute_author_script(RULE_SCRIPT)
    assert not result.ok
    detail = result.refusal.as_dict()
    assert "каталог документа не подан" in str(detail), detail


def test_an_unknown_pool_names_what_did_arrive():
    """A silent empty list would mean "there are no types of this kind in the document"."""
    result = execute_author_script(
        'envelope(intent="x")\nmodel.types("двери")\n', model=CATALOGUE)
    assert not result.ok
    detail = str(result.refusal.as_dict())
    assert "двери" in detail and "wall_types" in detail, detail


def test_reading_facts_never_reach_the_script():
    """`__document_fingerprint` and `*__total` are about the READ, not
    about the building.

    A script branching on them would be branching on our internal
    plumbing, and its program would change depending on whether the
    collector truncated the pool.
    """
    result = execute_author_script(
        'envelope(intent="x")\nprint(sorted(model.pools()))\n'
        'create_level(elev_mm=0, name="Э")\n', model=CATALOGUE)
    assert result.ok, result.refusal and result.refusal.as_dict()
    assert result.stdout.strip() == "['grids', 'levels', 'wall_types']"


def test_the_catalogue_is_signed_separately_from_the_source():
    """A third signer: editing the script is distinguishable from the
    model drifting.

    The same argument as for the environment signature in the header of
    `sandbox`: without a separate signature, a single `author_digest`
    would certify DIFFERENT programs, and the reader would have no field
    at all to tell what changed — the text or the building.
    """
    one = execute_author_script(RULE_SCRIPT, model=CATALOGUE)
    fewer = {**CATALOGUE, "levels": CATALOGUE["levels"][:2]}
    two = execute_author_script(RULE_SCRIPT, model=fewer)
    assert one.author_digest == two.author_digest      # the text did not change
    assert one.model_digest != two.model_digest        # the building changed
    assert one.program_digest != two.program_digest    # and so did the program
    assert len(two.ops) == 2


def test_no_catalogue_means_no_signature_rather_than_an_empty_one():
    """An empty signature would read as "the catalog existed and turned out empty"."""
    assert execute_author_script(
        'envelope(intent="x")\ncreate_level(elev_mm=0, name="Э")\n'
    ).model_digest == ""


def test_the_catalogue_is_read_only():
    """A script that appended a line would sign a document that does not exist."""
    catalogue = ModelCatalog({"levels": [{"id": 1, "name": "Э"}]}, "d")
    rows = catalogue.levels()
    rows[0]["name"] = "подмена"
    assert catalogue.levels()[0]["name"] == "Э"


# ─────────────────────────────────────────────────────────────────────────
# THE LIVE PATH: the catalog reaches the script, and its signature reaches the receipt
# ─────────────────────────────────────────────────────────────────────────

class _Bridge:
    """A bridge that hands back exactly the catalog. Counts how many times it was asked."""

    def __init__(self, payload=CATALOGUE):
        self.payload = payload
        self.calls = 0


def _authored(args, bridge: _Bridge | None):
    """Drive the authoring door through, substituting ONE seam — the
    catalog fetcher.

    What gets substituted is neither the bridge nor the sandbox, but
    specifically `_document_catalogue`: it is exactly the new thing being
    checked here, and substituting a layer below would also measure the
    transport, which this test has nothing to do with.
    """
    original = serving._document_catalogue

    async def fake(llm_client, bridge_callback):
        if bridge is None:
            return None
        bridge.calls += 1
        return bridge.payload

    serving._document_catalogue = fake                      # type: ignore[assignment]
    try:
        return asyncio.run(serving._authored_input(args, object(), object()))
    finally:
        serving._document_catalogue = original              # type: ignore[assignment]


def test_the_catalogue_reaches_the_script_through_the_live_door():
    bridge = _Bridge()
    authored = _authored({"program_py": RULE_SCRIPT}, bridge)
    assert authored.refusal is None, authored.refusal
    assert len(authored.args["program"]["ops"]) == 3
    assert bridge.calls == 1
    assert authored.model_digest
    assert authored.receipt["model_digest"] == authored.model_digest


def test_a_json_program_pays_nothing_for_this():
    """The ordinary JSON path never comes through here — not a single extra trip to the bridge."""
    bridge = _Bridge()
    authored = _authored(
        {"program": {"ir_version": "1.0",
                     "ops": [{"op": "query_count", "id": "q", "kind": "wall"}]}},
        bridge)
    assert authored.refusal is None
    assert bridge.calls == 0
    assert authored.model_digest == ""


def test_a_silent_bridge_does_not_cancel_the_turn():
    """The catalog is a convenience. A failed auxiliary read does not cancel the turn."""
    authored = _authored(
        {"program_py": 'envelope(intent="x")\ncreate_level(elev_mm=0, name="Э")\n'},
        None)
    assert authored.refusal is None, authored.refusal
    assert authored.model_digest == ""


# ─────────────────────────────────────────────────────────────────────────
# THE MAIN POINT: AUTHORITY REMAINS WITH GROUNDING
# ─────────────────────────────────────────────────────────────────────────

def test_a_stale_catalogue_cannot_build_the_wrong_thing_through_a_selector():
    """The catalog is stale, the script named a level that is gone —
    grounding REFUSES.

    This is exactly the entry price for the new capability. The catalog
    is a snapshot at the moment of reading, not the live model; if a
    stale read reached the build, we would have created a new way to
    build something wrong SILENTLY — exactly what this whole package
    stands against.

    THE HONEST OTHER HALF, named here rather than hidden: what is
    protected is the SELECTOR, not the NUMBER. A script branching on
    `len(model.levels())` will produce a different program, and grounding
    will calmly ground it — because it is correct, just not the one the
    author would write today. The catalog must therefore be a fresh read,
    not a memory of a past turn.
    """
    result = execute_author_script(RULE_SCRIPT, model=CATALOGUE)
    assert result.ok and len(result.ops) == 3

    # The document has moved on: the third floor no longer exists.
    live = {"levels": CATALOGUE["levels"][:2],
            "wall_types": CATALOGUE["wall_types"]}
    out = compile_program({"ir_version": "1.0", "ops": result.ops},
                          snapshot=live, bulk=True)
    assert not out.ok
    codes = [d.code for d in out.diagnostics]
    assert "KIR-G101" in codes, [d.as_dict() for d in out.diagnostics]


def test_the_control_can_fail():
    """FAIL control: without the catalog, the rule cannot be written at
    all.

    An instrument that cannot fail certifies nothing: if the script
    assembled three walls even WITHOUT the catalog, the first test in
    this file would be measuring nothing.
    """
    assert not execute_author_script(RULE_SCRIPT).ok
    assert execute_author_script(RULE_SCRIPT, model=CATALOGUE).ok


# ═════════════════════════════════════════════════════════════════════════
# THREE OUTCOMES OF ONE QUESTION — and each must sound different (15.08.2026)
#
# FORM 11 ("one code for two outcomes"), found in this very file while
# reconciling the branch. `ModelCatalog.__init__` had `if kept:`, and
# `_model_pools` had the same filter on the input side, and a pool that
# ARRIVED EMPTY was discarded on a par with a pool that was never sent.
# Both then answered "no pool in this snapshot," and the second half of
# that phrase ("Sent: (catalog not supplied)") was FALSE: the catalog had
# been supplied.
#
# The distinction decides WHAT the author should do, and is therefore not
# cosmetic:
#
#   pool is empty       a fact ABOUT THE BUILDING — there are no types of
#                        this kind in the document. The correct answer is
#                        an empty tuple, and the author branches on it;
#   pool was not sent    a fact ABOUT US — we never asked. The correct
#                        answer is a REFUSAL, because "none" would be
#                        untrue here;
#   no catalog at all    an offline run. The correct answer is its own,
#                        a third refusal.
#
# The costliest case is the third one, for `levels()`: a Revit document
# without levels does not exist, and a silent empty tuple there would mean
# OUR OWN reading gap, while reading as a fact about the building.
# ═════════════════════════════════════════════════════════════════════════

_ONE_LEVEL = {"levels": [{"id": "8001", "name": "Этаж 1"}]}


class ThreeOutcomesOfOneQuestion(unittest.TestCase):

    def test_an_empty_pool_is_a_fact_about_the_building(self):
        """The pool arrived empty — this is an answer, not a refusal."""
        cat = ModelCatalog({**_ONE_LEVEL, "wall_types": []})
        self.assertEqual(cat.types("wall_types"), ())
        self.assertIn("wall_types", cat.pools())

    def test_a_pool_that_was_never_sent_refuses_and_says_whose_fault(self):
        """The pool was not sent — a refusal, and it names this as a fact about the READ."""
        cat = ModelCatalog(dict(_ONE_LEVEL))
        with self.assertRaises(KeyError) as caught:
            cat.types("wall_types")
        text = str(caught.exception)
        self.assertIn("НЕ ПРИСЛАЛИ", text)
        self.assertIn("levels", text)          # names what ARRIVED

    def test_an_absent_catalogue_is_its_own_third_answer(self):
        with self.assertRaises(RuntimeError):
            ModelCatalog(None).levels()

    def test_levels_never_answers_a_silent_empty_tuple(self):
        """The costliest case: a document with no levels does not exist."""
        with self.assertRaises(KeyError):
            ModelCatalog({"wall_types": [{"id": "9", "name": "К"}]}).levels()

    def test_the_intake_filter_does_not_undo_the_distinction(self):
        """BOTH ends, otherwise the instrument covers only part of the
        range.

        The catalog would distinguish three outcomes, while only two
        would actually arrive: the `_model_pools` filter sits EARLIER and
        drops an empty pool by itself.
        """
        pools = _model_pools({**_ONE_LEVEL, "wall_types": []})
        self.assertIn("wall_types", pools, "пустой пул срезан на входе")
        self.assertEqual(pools["wall_types"], [])

    def test_the_control_can_fail(self):
        """FAIL CONTROL: restoring `if kept:` must turn red.

        Without it, all five checks above are green by construction on
        any catalog where empty pools never occur.
        """
        as_before = {name: rows
                     for name, rows in {**_ONE_LEVEL, "wall_types": []}.items()
                     if rows}                                  # the earlier filter
        self.assertNotIn("wall_types", as_before)
        with self.assertRaises(KeyError):
            ModelCatalog(as_before).types("wall_types")


# ─────────────────────────────────────────────────────────────────────────
# A TRIP ONLY FOR WHAT THE SCRIPT ASKED FOR
#
# Measurement of 16.08.2026, prod log, `EXEC_PIPELINE_RECORD
# op=script_catalogue`: the trip for the catalog costs 3675 and 3262 ms
# and was being paid on EVERY `program_py` turn. Breakdown of the turn on
# that same day: model 84.6%, bridge and Revit 13.1%, our own Python
# 0.44% — meaning the extra trip was the second-largest chunk of the turn
# after waiting for the model.
#
# The check is reliable not by convenience: the catalog reaches the
# script by EXACTLY ONE route — a name in the namespace, and
# `globals`/`locals` are forbidden to the script as builtins. If it did
# not name it, it cannot read it.
# ─────────────────────────────────────────────────────────────────────────

_NO_CATALOGUE = """
envelope(intent="стена без единого вопроса к документу")
create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=by_name("Этаж 1"), height_mm=3000)
"""


def test_a_script_that_never_names_the_catalogue_pays_no_roundtrip():
    """THE WAVE'S HEADLINE NUMBER: there was 1 trip, now there are 0 — with the same result."""
    bridge = _Bridge()
    authored = _authored({"program_py": _NO_CATALOGUE}, bridge)
    assert authored.refusal is None, authored.refusal
    assert len(authored.args["program"]["ops"]) == 1
    assert bridge.calls == 0, "рейс за каталогом, которого скрипт не спрашивал"


def test_a_script_that_names_it_still_gets_it():
    """A control from the other side of the boundary: the capability was not taken away."""
    bridge = _Bridge()
    authored = _authored({"program_py": RULE_SCRIPT}, bridge)
    assert authored.refusal is None, authored.refusal
    assert bridge.calls == 1
    assert len(authored.args["program"]["ops"]) == 3
    assert authored.model_digest


def test_the_guess_errs_only_toward_the_extra_roundtrip():
    """The error is permitted in ONE direction only, and this is checked,
    not merely promised.

    A mention in a comment is not use of the catalog — yet the trip still
    gets paid. An extra trip is today's price; a skipped one would be a
    lost capability for an author who asked for it.
    """
    bridge = _Bridge()
    authored = _authored(
        {"program_py": '# про model тут только слово\n' + _NO_CATALOGUE},
        bridge)
    assert authored.refusal is None, authored.refusal
    assert bridge.calls == 1, "подстрока обязана ошибаться в сторону рейса"


def test_the_name_is_the_one_the_sandbox_actually_injects():
    """A RATCHET. Should the name in the sandbox be renamed, the trip
    would start being skipped SILENTLY, and the author would get an empty
    catalog without knowing why. The test holds the identity in place."""
    from kir import sandbox

    assert serving._CATALOGUE_NAME in sandbox.HOST_NAMES, (
        "имя каталога разошлось с пространством скрипта: %r против %s"
        % (serving._CATALOGUE_NAME, sorted(sandbox.HOST_NAMES)))
