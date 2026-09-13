"""query_count/query_list do not count everything the writer knows how to
build.

THE TRIGGER: a live finding from the KIR marathon on 25.08.2026, the
"REGISTRY" block. In Revit, 80 columns were built (`create_column`), all
80 were read back by the judge, but `query_count(kind="column")` refused
with `KIR-G001`.

ANALYZED, AND THIS REFUTES THE INITIAL READING. A column is NOT a hole:
`registry_base.KINDS` knows both `column_structural` AND
`column_architectural` (create_column picks the category via the closed
`category` field, structural/architectural — registry_base.py:120-126),
and `compiler._check_kind` already answers SPECIFICALLY:

    неизвестный kind 'column' — вид уточняется: column_architectural |
    column_structural. Общего вида «column» нет намеренно: выбрать за
    автора нельзя

(compiler.py:508-513, `_kind_hint`, the "family" branch). This is a
BOUNDARY, not an omission: there is no generic `column` kind for the same
reason there is none for `create_wall_sweep` (Cornices/Reveals) — the
category is decided by a field of the program, and guessing it in the
author's place is deliberately forbidden.

🔴 WHY THE LIVE REFUSAL LOOKED GENERIC, RATHER THAN LIKE THIS TEXT.
`serving.py:4767` overwrites the `message_ru` of ANY refusal that carries
`out.handoff` (and `handoff` is set for EVERY `KIR-G001`,
compiler.py:2859-2862) with one template, «запрос вне покрытия KIR —
выполни обычным инструментом», without reading the diagnostic's specific
text. The specifics stay in `diagnostics[0].message_ru` (the response
body carries it), but the top level loses it. This is a defect of the
SERVICE LAYER, not the registry — `serving.py` is outside the
spec.py/registry_base.py/ops_*.py block, and is not fixed here, only
recorded with its address.

THE REAL HOLE IS WIDER, AND IT IS SOMEWHERE ELSE. For a number of writing
ops the result category is KNOWN EXACTLY (a line in
`spec.OP_RESULT_CATEGORIES`, or the answer from
`spec.op_result_categories()`), while `registry_base.KINDS` has NO kind
for it AT ALL — it can be built, but there is nothing to count it with,
and `_kind_hint` cannot even show a neighbor (such a category has not a
single name with a shared prefix in the kinds table), meaning the
refusal comes out WORSE than the column's: the full list of 53 names
with not a single hint.

THE BASELINE IS NAMED, NOT FILLED IN — symmetrically to the
`OP_RESULT_CATEGORIES` discipline (spec.py, the paragraph "ЗАПОЛНЯТЬ
НЕДОСТАЮЩЕЕ ЗАПРЕЩЕНО"). Writing a `KindSpec` in here by hand, without
checking with a live Revit that the collector actually assembles the
category that way (versions 2021-2026, ImportInstance vs. class,
IsPlaceholder-like traps — see the history of `duct_placeholder`/
`pipe_placeholder`, registry_base.py:203-217), is exactly the kind of
handwritten list that in this tree ALWAYS goes out of sync (project
memory: "Handwritten lists have gone out of sync EVERY TIME; generated
ones, NOT ONE"). So the test holds the NUMBER and the NAMES of the
measured hole, rather than an imagined fix: the hole's growth must be
VISIBLE, not quiet.

WHAT THIS TEST DOES NOT REQUIRE. It does not require that every known
category have a line in `KINDS` — filling it in without measurement is
more dangerous than blindness (a false `column_structural`-like kind on
a category that Revit assembles differently would give a `query_count`
that silently counts the wrong thing). It requires that the hole be
NAMED: the list below is a measured boundary, and expanding it without a
word in this file is a silent regression.
"""
import re
import unittest

from kir import registry_base as rb
from kir import spec

#: Probes: the same varieties that `op_result_categories()` distinguishes
#: (see test_registry_category_accounting.py._VARIETY_PROBES) plus the
#: DirectShape categories — the only op with an open category choice over
#: a closed enumeration from the shape module.
_VARIETY_PROBES = (
    {}, {"variety": "wall_rect"}, {"variety": "host_face"},
    {"variety": "isolated"}, {"variety": "slab"},
    {"variety": "surface"}, {"variety": "toposolid"},
    {"category": "structural"}, {"category": "architectural"},
)


def _directshape_category_probes():
    from kir.ops_shape import DIRECTSHAPE_CATEGORIES
    return [{"category": k} for k in DIRECTSHAPE_CATEGORIES]


def _writing_ops():
    return {name for name, op in spec.OPS.items() if op.writes_model}


def _op_categories(name):
    """All the REAL BuiltInCategory values an op is able to name across
    any probe (the sum). The `OST_` filter is deliberate:
    `op_result_categories()` sometimes returns a second, NON-category
    census key — for example the literal `"DirectShape"` (spec.py, the
    comment at `_directshape_result_
    ops`: "ДВА КЛЮЧА... сумма верна при любом источнике"). Such a key
    cannot have a kind in `KINDS` by definition — `KindSpec.collector_cs`
    filters REVIT ELEMENTS, not the census's source string — and its
    absence among the kinds is not a fact about the counter but a fact
    about different questions."""
    cats = set(spec.OP_RESULT_CATEGORIES.get(name, ()))
    for probe in _VARIETY_PROBES + tuple(_directshape_category_probes()):
        op = dict(probe)
        op["op"] = name
        try:
            got = spec.op_result_categories(op)
        except Exception:
            continue
        if got:
            cats.update(got)
    return {c for c in cats if c.startswith("OST_")}


#: A category that KINDS collects via OfClass(typeof(X)), not via
#: OfCategory(BuiltInCategory...) — a fact about the Revit API
#: (Wall/Floor/Level/Grid/ViewSheet each has exactly one native
#: category), not a guess.
_CLASS_IMPLIES_CATEGORY = {
    "Wall": "OST_Walls",
    "Floor": "OST_Floors",
    "Level": "OST_Levels",
    "Grid": "OST_Grids",
    "ViewSheet": "OST_Sheets",
}


#: 🔴 CLASS PLUS PREDICATE — A THIRD WAY TO LEARN THE CATEGORY, and it was
#: set up on 03.09.2026 by measurement, not by reasoning. A pipe
#: placeholder has the same class as a real one (`Pipe`), and the class
#: alone cannot derive the category: it depends on the BIT. Live Revit
#: 2026, «Проект1», elements built by the ops themselves:
#:
#:     Pipe · IsPlaceholder=True -> OST_PlaceHolderPipes («Трубопровод по осевой»)
#:     Duct · IsPlaceholder=True -> OST_PlaceHolderDucts («Воздуховоды по осевой»)
#:
#: Both members compile on 2021-2026 (live Roslyn :52412), a deliberately
#: nonexistent member in the same run gives CS0117 — the instrument tells
#: the difference. The class-based and category-based collectors gave ONE
#: matching set on the live model (4 and 4).
#:
#: WHY HERE, AND NOT IN THE COLLECTOR ITSELF: adding the category to
#: `collector_cs` means changing EMISSION — 12 discrepancies against
#: byte parity just so the instrument can see it. Knowledge about the
#: category belongs to whoever is asking.
_CLASS_AND_PREDICATE_IMPLY_CATEGORY = (
    ("Autodesk.Revit.DB.Plumbing.Pipe", "IsPlaceholder", "OST_PlaceHolderPipes"),
    ("Autodesk.Revit.DB.Mechanical.Duct", "IsPlaceholder", "OST_PlaceHolderDucts"),
)


def _kind_categories():
    """kind -> the set of BuiltInCategory values it actually collects."""
    result = {}
    for name, ks in rb.KINDS.items():
        text = ks.collector_cs + (ks.where_cs or "")
        cats = set(re.findall(r"BuiltInCategory\.(OST_\w+)", text))
        for cls in re.findall(r"typeof\(([\w.]+)\)", ks.collector_cs):
            mapped = _CLASS_IMPLIES_CATEGORY.get(cls)
            if mapped:
                cats.add(mapped)
        for cls_name, predicate, cat in _CLASS_AND_PREDICATE_IMPLY_CATEGORY:
            if cls_name in ks.collector_cs and predicate in (ks.where_cs or ""):
                cats.add(cat)
        result[name] = cats
    return result


#: `create_railing` is a PAIR of categories (`spec.py`, the comment at
#: `"create_railing"`): `OST_Railings` did not occur in ANY of 31
#: parses, but the table holds both, because a Revit version could
#: decide otherwise, and this is ALREADY a justified, named risk of the
#: registry — not a new finding of this test. The `railing` kind covers
#: the second, live half (`OST_StairsRailing`). It is skipped here
#: explicitly, so as not to duplicate a justification already sitting in
#: the registry.
_ALREADY_JUSTIFIED_ELSEWHERE = {"OST_Railings"}


def _uncounted_categories():
    """(category, {ops that build it}) for categories with no kind in KINDS."""
    kind_cats = _kind_categories()
    covered = {c for cats in kind_cats.values() for c in cats}
    covered |= _ALREADY_JUSTIFIED_ELSEWHERE
    by_category: dict[str, set] = {}
    for name in sorted(_writing_ops()):
        for cat in _op_categories(name):
            if cat not in covered:
                by_category.setdefault(cat, set()).add(name)
    return by_category


#: MEASURED on 25.08.2026 on this tree (prod-live). 35 categories across
#: 25 writing ops (11 categories are the marks of a single
#: `create_tag`; 3 categories are mass/site/entourage from
#: `DIRECTSHAPE_CATEGORIES`, which
#: `generic_model`/`furniture`/`specialty_equipment` do not cover, each
#: shared across the seven ops of the DirectShape family,
#: `_DIRECTSHAPE_FAMILY_OPS`).
#: `OST_Railings` is NOT included here: `create_railing` is already
#: covered by the `railing` kind through `OST_StairsRailing`, and the
#: pair's second category is justified in the registry itself (spec.py,
#: the comment at `"create_railing"`) — this is not a new finding but an
#: already accepted risk.
#: Seven ops share ONE table, `DIRECTSHAPE_CATEGORIES` (ops_shape.py) —
#: any of them builds mass/site/entourage through the same `category`
#: parameter.
_DIRECTSHAPE_FAMILY_OPS = {
    "create_directshape", "create_solid_blend", "create_solid_boolean",
    "create_solid_extrusion", "create_solid_revolve", "create_solid_sweep",
    "create_surface",
}

_KNOWN_UNCOUNTED = {
    "OST_AreaLoads": {"create_area_load"},
    "OST_AreaTags": {"create_tag"},
    "OST_BuildingPad": {"create_building_pad"},
    "OST_CeilingOpening": {"create_opening"},
    "OST_Cornices": {"create_wall_sweep"},
    "OST_Dimensions": {"create_angular_dimension", "create_dimension"},
    "OST_DoorTags": {"create_tag"},
    "OST_EdgeSlab": {"create_slab_edge"},
    "OST_Entourage": _DIRECTSHAPE_FAMILY_OPS,
    "OST_FilledRegion": {"create_filled_region"},
    "OST_FloorOpening": {"create_opening"},
    "OST_FloorTags": {"create_tag"},
    "OST_LineLoads": {"create_line_load"},
    "OST_Mass": _DIRECTSHAPE_FAMILY_OPS,
    "OST_MaskingRegion": {"create_filled_region"},
    "OST_MaterialTags": {"create_tag"},
    "OST_MechanicalEquipmentTags": {"create_tag"},
    "OST_MultiCategoryTags": {"create_tag"},
    "OST_MultistoryStairs": {"create_multistory_stairs"},
    "OST_PathOfTravelLines": {"create_path_of_travel"},
    "OST_PointLoads": {"create_point_load"},
    "OST_Reveals": {"create_wall_sweep"},
    "OST_RoofOpening": {"create_opening"},
    "OST_RoomSeparationLines": {"create_room_separator"},
    "OST_RoomTags": {"create_tag"},
    "OST_Site": _DIRECTSHAPE_FAMILY_OPS,
    "OST_StairsLandings": {"create_stairs_landing"},
    "OST_StairsRailingTags": {"create_tag"},
    "OST_StructuralFramingTags": {"create_tag"},
    "OST_SWallRectOpening": {"create_opening"},
    "OST_TextNotes": {"create_text"},
    "OST_Topography": {"create_site_subregion", "create_topography"},
    "OST_Toposolid": {"create_topography"},
    "OST_WallTags": {"create_tag"},
    "OST_WindowTags": {"create_tag"},
}


class QueryCountCoversWhatItCanNameExactly(unittest.TestCase):

    def test_column_itself_is_not_a_gap(self):
        """A column is a boundary, not a hole: both kinds are in the
        table, and the refusal on the generic name names both neighbors
        in Russian."""
        self.assertIn("column_structural", rb.KINDS)
        self.assertIn("column_architectural", rb.KINDS)
        from kir import compiler
        diags = []
        norm = compiler._validate_op(
            {"op": "query_count", "id": "q1", "kind": "column"}, 0, diags)
        self.assertIsNone(norm.get("kind"))
        self.assertEqual(len(diags), 1)
        msg = diags[0].message_ru
        self.assertIn("column_structural", msg)
        self.assertIn("column_architectural", msg)
        self.assertIn("намеренно", msg)

    def test_the_uncounted_gap_matches_the_measured_baseline(self):
        """If this set GREW — someone set up a writing op with a known
        category and did not set up a kind for it. If IT SHRANK — a kind
        was added, and the line(s) need to be removed from here with a
        reference to the measurement that confirmed the kind (not just
        "test updated")."""
        measured = _uncounted_categories()
        self.assertEqual(
            measured, _KNOWN_UNCOUNTED,
            "дыра между OP_RESULT_CATEGORIES/op_result_categories() и "
            "registry_base.KINDS разъехалась с измеренной 25.08.2026: "
            "новые категории без рода — %s; закрытые без обновления baseline"
            " — %s" % (
                {k: sorted(v) for k, v in measured.items()
                 if k not in _KNOWN_UNCOUNTED},
                {k: sorted(v) for k, v in _KNOWN_UNCOUNTED.items()
                 if k not in measured},
            ))

    def test_baseline_only_names_writing_ops(self):
        writing = _writing_ops()
        stray = {op for ops in _KNOWN_UNCOUNTED.values() for op in ops
                 if op not in writing}
        self.assertEqual(stray, set(),
                         "baseline называет опы, которых нет среди "
                         "пишущих: %s" % sorted(stray))
