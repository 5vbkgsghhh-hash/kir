# -*- coding: utf-8 -*-
"""Thirteen categories stopped being INVISIBLE (04.09.2026).

Each of them HAS an operation in the registry, and none was being
extracted: the element yielded no L0 row, no atom, no refusal. The
reassembled building stayed without terrain, without fills, without loads,
without cornices — and said nothing about it. The house's canon names this
kind directly: "a host comes up solid, L2 acceptance does not catch this by
construction, a quietly wrong result is indistinguishable from success from
the outside."

WHAT EXACTLY IS BEING LOCKED IN. Not the lift — it does not exist yet. What
is locked in is that silence became a REFUSAL, and the refusal became the
specification of the next reading wave: it names the operation, names every
missing input, and names the REVIT API MEMBER that would have to be
captured next. This is worse than a lifted operation and BETTER than
invisibility — the same-shaped precedent has stood at openings since 03.08.

WHY THIS IS NOT "GREEN BY CONSTRUCTION." The test does not ask "is there a
row in the table" — it LIFTS an element of every category and reads the
reason and the text. A table that has diverged from the behavior will turn
red here, not in someone else's shift.
"""
from __future__ import annotations

import unittest

from kir import spec
from kir.decompile.extract import EXTRACT_CATEGORIES
from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import (
    _L0_ALREADY_CARRIES,
    _L0_HAS_NO_SOURCE_FOR,
    _OPS_WITHOUT_L0_INPUTS,
    lift_document_detailed,
)
from kir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)
from kir.model.schema import (
    SUPPORTED_L0_DIALECTS,
    dialect_fingerprint,
    verify_dialect_ladder,
)

#: Exactly the thirteen added by this wave. The list is EXPLICIT, not
#: derived from the table: a derived one would agree with it under any
#: error in the table itself.
WAVE = (
    "OST_PointLoads", "OST_LineLoads", "OST_AreaLoads", "OST_AreaRein",
    "OST_Topography", "OST_BuildingPad", "OST_FilledRegion",
    "OST_MaskingRegion", "OST_Cornices", "OST_Reveals", "OST_EdgeSlab",
    "OST_StairsLandings", "OST_PathOfTravelLines",
)

#: ALREADY CLOSED by a lift, out of the wave, and therefore no longer
#: checked by the refusal test. The list is separate and explicit: silently
#: subtracting a category from the refusal check would let a future
#: breakage of the lift slip by unnoticed — it would fall back into
#: refusal, and the test would not notice.
LIFTED = ("OST_LineLoads", "OST_PointLoads", "OST_AreaLoads")
REFUSING = tuple(c for c in WAVE if c not in LIFTED)


def _lift_one(category):
    element = L0Element(
        element_id="800", category=category, category_ru="", type_id="1",
        type_name="Тип", level_id="10", level_name="Этаж 1",
        geom_kind=GeometryKind.POINT, p0_mm=(0.0, 0.0, 0.0), p1_mm=None,
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
        host_id=None, params={})
    document = L0Document(
        doc_name="wave", revit_version="2023", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "Этаж 1", 0.0),), grids=(), rooms=(),
        project_info=ProjectInfo(), elements=(element,))
    result = lift_document_detailed(document)
    return result.nodes[0], result.diagnostics[0]


class EveryNewCategoryIsCapturedAtAll(unittest.TestCase):

    def test_each_one_entered_the_extraction_table(self):
        for category in WAVE:
            with self.subTest(category=category):
                self.assertIn(
                    category, EXTRACT_CATEGORIES,
                    "категория вне таблицы съёма НЕ ДАЁТ НИ СТРОКИ: элемент "
                    "исчезает молча, и это тот самый дефект, ради которого "
                    "волна заведена")

    def test_the_table_grew_with_its_own_dialect_step(self):
        """The law of the file: a table with no stage is not read by its own reader."""

        verify_dialect_ladder(EXTRACT_CATEGORIES)
        newest = SUPPORTED_L0_DIALECTS[-1]
        self.assertEqual(newest.category_count, len(EXTRACT_CATEGORIES))
        self.assertEqual(
            newest.fingerprint, dialect_fingerprint(EXTRACT_CATEGORIES),
            "отпечаток обязан быть СНЯТ прибором с живой таблицы, а не "
            "переписан с чужого экрана")

    def test_the_previous_step_still_matches_its_own_prefix(self):
        """The append-only-to-the-tail law, checked, not merely declared."""

        previous = SUPPORTED_L0_DIALECTS[-2]
        self.assertEqual(
            previous.fingerprint,
            dialect_fingerprint(EXTRACT_CATEGORIES[:previous.category_count]),
            "рост таблицы обязан быть ДОПИСЬЮ: вставка в середину сдвинула "
            "бы адресацию возобновления у всех прежних слепков")


class EveryNewCategoryRefusesByName(unittest.TestCase):

    def test_it_becomes_an_atom_that_names_its_op_and_its_missing_inputs(self):
        for category in REFUSING:
            with self.subTest(category=category):
                node, diagnostic = _lift_one(category)
                self.assertEqual(node["kind"], "atom")
                self.assertIs(
                    diagnostic.reason, AtomReason.SOURCE_CONTRACT_GAP,
                    "no_lifter послал бы писать операцию, которая НАПИСАНА; "
                    "правда лежит в чтении")
                op_name = _OPS_WITHOUT_L0_INPUTS[category]
                detail = node["reason"]["detail"]
                self.assertIn(op_name, detail)
                for param in spec.OPS[op_name].params:
                    if param.required and param.name not in _L0_ALREADY_CARRIES:
                        self.assertIn(
                            param.name, detail,
                            "отказ обязан назвать КАЖДЫЙ недостающий вход: "
                            "он и есть спецификация следующей волны чтения")

    def test_no_refusal_says_the_source_was_not_named(self):
        """The quietest way to lie is to print a stub and move on."""

        for category in REFUSING:
            with self.subTest(category=category):
                node, _ = _lift_one(category)
                self.assertNotIn("источник не назван", node["reason"]["detail"])

    def test_the_only_never_is_told_apart_from_the_not_yet(self):
        """`create_slab_edge` is the only one for which a witness DOES NOT
        EXIST.

        Measured: `SlabEdge` and `SlabEdgeType` together have four members
        across all six versions, and none of them is the side. The refusal
        must say this OUT LOUD, otherwise the next person will search for
        an API member that does not exist, and will find their time spent
        for nothing.
        """

        node, _ = _lift_one("OST_EdgeSlab")
        self.assertIn("ГЕТТЕРА НЕТ", node["reason"]["detail"])
        # And for the remaining twelve there must be NO such verdict: they
        # have a witness found, and it is work, not an obstacle.
        for category in REFUSING:
            if category == "OST_EdgeSlab":
                continue
            with self.subTest(category=category):
                self.assertNotIn("ГЕТТЕРА НЕТ", _lift_one(category)[0]["reason"]["detail"])


def _load_node(**правка):
    """A line load, legal in everything except what is named in `правка`."""

    поля = dict(
        load_p0_mm=(0.0, 0.0, 3000.0), load_p1_mm=(6000.0, 0.0, 3000.0),
        load_case_id="42", load_case_name="Собственный вес",
        load_force_n_per_m=(0.0, 0.0, -1500.0), load_uniform=True,
        load_projected=False, load_hosted=False, load_reaction=False,
        load_orient_to="Project")
    поля.update(правка)
    element = L0Element(
        element_id="901", category="OST_LineLoads", category_ru="",
        type_id="7", type_name="Нагрузка", level_id="10", level_name="Этаж 1",
        geom_kind=GeometryKind.POINT, p0_mm=(0.0, 0.0, 0.0), p1_mm=None,
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
        host_id=None, params={}, **поля)
    document = L0Document(
        doc_name="wave", revit_version="2023", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "Этаж 1", 0.0),), grids=(), rooms=(),
        project_info=ProjectInfo(), elements=(element,))
    result = lift_document_detailed(document)
    return result.nodes[0], result.diagnostics[0]


class WhatTheWaveAlreadyClosedMustLiftNotRefuse(unittest.TestCase):
    """What is closed is checked by a LIFT, not by silence.

    Subtracting a category from the refusal check without checking it by a
    lift is the quietest way to lose a fix: it would fall back into
    refusal, and no probe would notice.
    """

    def test_a_uniform_line_load_becomes_its_op(self):
        from kir.decompile.lift import _CANDIDATES

        for category in LIFTED:
            with self.subTest(category=category):
                self.assertIn(
                    category, _CANDIDATES,
                    "закрытая категория обязана стоять в таблице подъёма")
                self.assertNotIn(
                    category, _OPS_WITHOUT_L0_INPUTS,
                    "и НЕ обязана оставаться в таблице отказа: два ответа на "
                    "одну категорию разошлись бы молча")

        element = L0Element(
            element_id="900", category="OST_LineLoads", category_ru="",
            type_id="7", type_name="Нагрузка", level_id="10",
            level_name="Этаж 1", geom_kind=GeometryKind.POINT,
            p0_mm=(0.0, 0.0, 0.0), p1_mm=None, rotation_deg=None,
            bbox_min_mm=None, bbox_max_mm=None, host_id=None, params={},
            load_p0_mm=(0.0, 0.0, 3000.0), load_p1_mm=(6000.0, 0.0, 3000.0),
            load_case_id="42", load_case_name="Собственный вес",
            load_force_n_per_m=(0.0, 0.0, -1500.0),
            load_uniform=True, load_projected=False,
            # The three fields of MEANING are mandatory here too: without
            # them the row falls into its own error window and refuses —
            # which is checked separately below. The "legal load" fixture
            # must be legal IN EVERYTHING, otherwise the probe turns red
            # about something other than what it claims.
            load_hosted=False, load_reaction=False, load_orient_to="Project")
        document = L0Document(
            doc_name="wave", revit_version="2023", units="mm",
            change_stamp="t", levels=(LevelInfo("10", "Этаж 1", 0.0),),
            grids=(), rooms=(), project_info=ProjectInfo(),
            elements=(element,))
        result = lift_document_detailed(document)
        node = result.nodes[0]
        self.assertEqual(node["op_name"], "create_line_load")
        self.assertEqual(node["params"]["load_case"]["value"],
                         "Собственный вес")

    def test_a_load_whose_MEANING_differs_refuses_by_name(self):
        """🔴 THREE BOUNDARIES FOUND AFTER MY OWN MISS.

        The first revision of the closure read only the ends, the vector,
        and the case from the load — exactly what the gap's reason named —
        and therefore SILENTLY reassembled a hosted load as free, a
        locally-oriented one as project, and a design-computed reaction as
        authored. The full member list of `LoadBase` was read a turn later,
        and it turned up three properties, 6/6 with zero traps, each of
        which changes MEANING at the same numbers.
        """

        случаи = (
            ({"load_reaction": True}, AtomReason.GENERATOR_CHILD, "РЕАКЦИЯ"),
            ({"load_hosted": True}, AtomReason.UNSUPPORTED_SIGNATURE, "IsHosted"),
            ({"load_orient_to": "WorkPlane"},
             AtomReason.UNSUPPORTED_SIGNATURE, "Project"),
        )
        for правка, причина, слово in случаи:
            with self.subTest(**правка):
                node, diagnostic = _load_node(**правка)
                self.assertEqual(node["kind"], "atom")
                self.assertIs(diagnostic.reason, причина)
                self.assertIn(слово, node["reason"]["detail"])

    def test_the_window_of_my_own_mistake_refuses_instead_of_guessing(self):
        """A row with ends but WITHOUT meaning comes from exactly one place.

        Before the capture wave, the category `OST_LineLoads` did not exist
        in the extraction at all. So such a row was taken by the window
        between the wave and the fix, where the coordinates were read and
        the meaning was not. "Behaving as before" here would mean repeating
        the error, not preserving history.
        """

        node, diagnostic = _load_node(load_hosted=None, load_reaction=None,
                                      load_orient_to=None)
        self.assertEqual(node["kind"], "atom")
        self.assertIs(diagnostic.reason, AtomReason.SOURCE_CONTRACT_GAP)
        self.assertIn("СМЫСЛА", node["reason"]["detail"])


class OneNameNowMeansTwoThings(unittest.TestCase):
    """The wave INTRODUCED the first name collision the pair exists for.

    Before it, `variety` occurred on a single op-with-refusal, and the
    fallback key was correct. Now there are two of them, and their sources
    are DIFFERENT. The probe takes exactly this case, not the shape of the
    table: the shape can be satisfied without telling anything apart.
    """

    def test_variety_resolves_to_its_own_op(self):
        from kir.decompile.lift import _source_gap_note

        opening = _source_gap_note("create_opening", "variety")
        topography = _source_gap_note("create_topography", "variety")
        self.assertIn("Opening.Host", opening)
        self.assertIn("Toposolid", topography)
        self.assertNotEqual(
            opening, topography,
            "один текст на два разных предмета — это отказ, посылающий "
            "читать не тот член API")

    def test_the_never_and_the_not_yet_do_not_share_a_wildcard(self):
        """`host` across three ops is three different getters, and one of them DOES NOT EXIST."""

        from kir.decompile.lift import _source_gap_note

        тексты = {оп: _source_gap_note(оп, "host") for оп in
                  ("create_wall_sweep", "create_slab_edge",
                   "create_area_reinforcement")}
        self.assertEqual(
            len(set(тексты.values())), 3,
            f"три носителя одного имени слились в один текст: {тексты}")


if __name__ == "__main__":
    unittest.main()
