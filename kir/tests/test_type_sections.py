"""THE sections WAVE: the snapshot carries the TYPE's geometry, and it makes it all the way to the shell.

What is held in place here, and why exactly this.

1. THE ABSENT STAYS ABSENT. A parse captured before this wave must
   yield THE SAME bytes and THE SAME fingerprint. A profile's `digest` is computed from
   `to_dict()` of each row, so `"section": null` would shift the fingerprint
   of every one of the 60+ parses saved on disk.
2. IDENTITY DOES NOT SIGN THE CONTENTS. `binding_digest` signs WHAT
   a row is, not what profile its type has; the cross-section does not enter into it.
3. THE PROGRAM GROUNDS IDENTICALLY. A snapshot with and without a cross-section must produce
   a byte-for-byte equal ground result and an equal `plan_digest`.
4. NOTHING IS GUESSED. A nominal size without a type table stays a nominal size; a tray
   gets no cross-section from nowhere; the reason for absence is ALWAYS named in words.
"""
from __future__ import annotations

import copy
import json
import unittest

from kir.clash import snapshot as clash_snapshot
from kir import clash_bundle as CB
from kir import ground
# 🔴 NAMES ARE TAKEN FROM THE MODULE AT CALL TIME, NOT AT IMPORT TIME (02.09.2026).
#
# Here stood `from kir.open_model import (ModelCatalogEntry,
# OpenModelProfile, OpenModelProfileError, TypeSection,
# prune_ground_snapshot)`, and this file was
# green ALONE and red IN COMPANY. The carrier of the leak is named by name and verified
# by execution: `kir/tests/test_open_model.py:890` calls `importlib.reload(om)`
# in a `finally`. The reload RE-EXECUTES the module inside the SAME dict, that is,
# it starts NEW class objects and a NEW refusal class, while what was imported by name
# holds onto the OLD ones. Hence two outcomes, both measured with a pair of files
# (`test_open_model.py test_type_sections.py` -> 4 failed, 57 passed, 1.05 s):
#
#   `assertRaises(OpenModelProfileError)` catches NOTHING — the validator throws
#       the NEW class (the module's functions see the updated dict), while the expectation
#       holds the OLD one; the refusal escapes outward as a test error;
#   `ModelCatalogEntry(section=TypeSection.from_dict(...))` stops matching
#       by `isinstance`: a row of the old class against the new one in the validator.
#
# This is a fact about the NEIGHBOR, not about this file's own subject, and the tree treats it in ONE
# way — asking the module for the name every time: this is already how
# `test_a_truncated_pool_says_so.py` (the same neighbor) and
# `test_a_refused_group_leaves_the_program_whole.py` (`reload(dsl)`) are written.
import kir.open_model as _om

_PLATE = {"kind": "plate", "source": "WallType.Width",
          "thickness_mm": 200.0, "uniform": True}


def _bare_snapshot() -> dict:
    return {
        "levels": [{"id": 1, "name": "L1"}],
        "wall_types": [{"id": 10, "name": "Стена 200"}],
        "floor_types": [{"id": 20, "name": "Плита 300"}],
        "__profile_schema_version": "open-model-profile/1",
        "__revit_version": "2026",
    }


def _rich_snapshot() -> dict:
    snap = _bare_snapshot()
    snap["levels"] = [{"id": 1, "name": "L1", "elevation_mm": 3000.0}]
    snap["wall_types"] = [{"id": 10, "name": "Стена 200", "section": _PLATE}]
    snap["floor_types"] = [{
        "id": 20, "name": "Плита 300",
        "section": {"kind": "plate", "thickness_mm": 300.0, "uniform": True,
                    "source": "HostObjAttributes.GetCompoundStructure().GetWidth"}}]
    return snap


class AbsentStaysAbsent(unittest.TestCase):

    def test_row_without_a_section_serialises_byte_for_byte(self):
        entry = _om.ModelCatalogEntry(element_id=10, name="Стена 200")
        row = entry.to_dict()
        self.assertNotIn("section", row)
        self.assertNotIn("elevation_mm", row)

    def test_profile_digest_does_not_move_for_a_legacy_snapshot(self):
        before = _om.OpenModelProfile.from_ground_snapshot(
            _bare_snapshot()).digest
        # the same snapshot, read by the code after the wave
        after = _om.OpenModelProfile.from_ground_snapshot(
            _bare_snapshot()).digest
        self.assertEqual(before, after)
        self.assertEqual(
            before,
            "" or _om.OpenModelProfile.from_ground_snapshot(
                json.loads(json.dumps(_bare_snapshot()))).digest)

    def test_a_section_changes_the_profile_digest_but_not_the_binding(self):
        """The PROFILE's fingerprint must move (it is a different document), while
        the row's `binding_digest` must not: it signs identity."""
        plain = _om.ModelCatalogEntry(element_id=10, name="Стена 200")
        with_section = _om.ModelCatalogEntry(
            element_id=10, name="Стена 200",
            section=_om.TypeSection.from_dict(_PLATE))
        self.assertEqual(plain.binding_digest, with_section.binding_digest)
        self.assertNotEqual(
            _om.OpenModelProfile.from_ground_snapshot(_bare_snapshot()).digest,
            _om.OpenModelProfile.from_ground_snapshot(_rich_snapshot()).digest)

    def test_ground_snapshot_round_trip_keeps_the_section(self):
        profile = _om.OpenModelProfile.from_ground_snapshot(_rich_snapshot())
        back = profile.to_ground_snapshot()
        self.assertEqual(back["wall_types"][0]["section"], _PLATE)
        self.assertEqual(back["levels"][0]["elevation_mm"], 3000.0)

    def test_grounding_is_identical_with_and_without_sections(self):
        """The cross-section does not participate in resolving selectors — and this must be
        PROVEN, not merely obvious: the snapshot feeds the plan, and the plan feeds the fingerprint."""
        program = {"ops": [{
            "op": "create_wall", "id": "w1",
            "p0_mm": [0.0, 0.0], "p1_mm": [5000.0, 0.0],
            "height_mm": 3000.0,
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "Стена 200"}}]}
        outs = []
        for snap in (_bare_snapshot(), _rich_snapshot()):
            grounded = ground.ground(copy.deepcopy(program["ops"]), snap)
            outs.append(json.dumps(grounded, ensure_ascii=False,
                                   sort_keys=True, default=str))
        self.assertEqual(outs[0], outs[1])


class TheRecordRefusesToBeSilent(unittest.TestCase):

    def test_non_uniform_section_must_name_its_blockers(self):
        with self.assertRaises(_om.OpenModelProfileError):
            _om.TypeSection(kind="plate", source="WallType.Width",
                            thickness_mm=200.0, uniform=False)

    def test_uniform_and_blocked_at_once_is_impossible(self):
        with self.assertRaises(_om.OpenModelProfileError):
            _om.TypeSection(kind="plate", source="WallType.Width",
                            thickness_mm=200.0, uniform=True,
                            blockers=("wall_sweeps",))

    def test_nominal_table_is_not_approximated(self):
        section = _om.TypeSection(
            kind="nominal_table", source="PipeSegment.GetSizes",
            sizes=((100.0, 114.3), (150.0, 168.3)))
        self.assertEqual(section.outer_for_nominal_mm(100.0), 114.3)
        self.assertEqual(section.outer_for_nominal_mm(100.4), 114.3)
        # 125 is NOT in the table — and there is nothing to approximate it with: neither 100 nor 150.
        self.assertIsNone(section.outer_for_nominal_mm(125.0))

    def test_sizes_must_be_sorted_by_unique_nominal(self):
        with self.assertRaises(_om.OpenModelProfileError):
            _om.TypeSection(kind="nominal_table", source="s",
                            sizes=((150.0, 168.3), (100.0, 114.3)))


class TheBundleReadsInsteadOfInventing(unittest.TestCase):

    def _pack(self, ops):
        return [{"ops": ops}]

    def test_without_a_snapshot_nothing_changes_and_the_reason_is_named(self):
        pack = self._pack([{
            "op": "create_floor", "id": "f1",
            "outline": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0]],
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "Плита 300"}}])
        geometry = CB.bundle_elements(pack)
        self.assertEqual(geometry.profiles, {})
        self.assertEqual(geometry.no_geometry, {"no_snapshot": 1})

    def test_a_slab_gets_a_body_once_the_type_carries_its_thickness(self):
        pack = self._pack([{
            "op": "create_floor", "id": "f1",
            "outline": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0]],
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "Плита 300"}}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        self.assertEqual(geometry.no_geometry, {})
        element = geometry.elements[0]
        # THE UNION of two interpretations: which way the body grows from the mark, the program
        # does not say, so the span is twice the plate's thickness — and this is NAMED in the code.
        self.assertEqual((element["z0_mm"], element["z1_mm"]), (2700.0, 3300.0))
        self.assertEqual(list(geometry.profiles), [element["element_id"]])

    def test_a_declared_wall_now_gets_a_body_and_the_blame_follows(self):
        """14.08: a wall declared as a whole gets a BODY, not a refusal.

        Previously a reverse ratchet stood here — "there is thickness, there is no body,
        `wall_prism_refused_by_containment_gate`". The containment lock (97
        violations out of 800) has NOT been re-measured and stays closed exactly where it was measuring:
        on a wall with a real footprint. A declared one has no footprint at all, and
        the band is admitted precisely there (`hulls.WALL_BAND_SCOPE`).

        More important than the band itself is that THE BLAME MOVED ALONG WITH IT: the census of "no
        geometry" is empty, because the reason is asked of `build_hull`, not
        of half of its condition. Had they drifted apart, they would have produced a receipt saying "DID NOT
        SEE" about an element that was, in fact, seen.
        """
        pack = self._pack([{
            "op": "create_wall", "id": "w1",
            "p0_mm": [0.0, 0.0], "p1_mm": [5000.0, 0.0], "height_mm": 3000.0,
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "Стена 200"}}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        self.assertEqual(geometry.no_geometry, {})
        self.assertEqual(geometry.elements[0]["prism"]["width_mm"], 200.0)

    def test_a_wall_whose_type_is_unknown_is_still_refused_by_name(self):
        """A FAIL CONTROL for the previous one: a refusal must remain possible.

        The test above is green even without the blame fix — it is enough for the body
        to get built. This one tells apart "the reason can still speak" from "the reason
        went silent forever": the type is not named, there is nowhere to get numbers from, and the census
        must call this by its own name.
        """
        pack = self._pack([{
            "op": "create_wall", "id": "w1",
            "p0_mm": [0.0, 0.0], "p1_mm": [5000.0, 0.0], "height_mm": 3000.0,
            "level": {"by": "name", "value": "L1"}}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        self.assertEqual(geometry.no_geometry, {"wall_type_not_declared": 1})

    def test_a_nominal_pipe_stays_nominal_without_a_type_table(self):
        pack = self._pack([{
            "op": "create_pipe", "id": "p1",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0],
            "diameter_mm": 100.0,
            "level": {"by": "name", "value": "L1"},
            "pipe_type": {"by": "name", "value": "Сталь"}}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        params = geometry.elements[0]["params"]
        self.assertEqual(params, {"RBS_PIPE_DIAMETER_PARAM": 100.0})
        self.assertEqual(geometry.no_geometry,
                         {"pipe_type_not_in_snapshot": 1})

    def test_the_type_table_turns_a_nominal_into_an_outer_diameter(self):
        snap = _rich_snapshot()
        snap["pipe_types"] = [{
            "id": 30, "name": "Сталь",
            "section": {"kind": "nominal_table",
                        "source": "PipeSegment.GetSizes",
                        "sizes": [[100.0, 114.3], [150.0, 168.3]]}}]
        pack = self._pack([{
            "op": "create_pipe", "id": "p1",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0],
            "diameter_mm": 100.0,
            "level": {"by": "name", "value": "L1"},
            "pipe_type": {"by": "name", "value": "Сталь"}}])
        geometry = CB.bundle_elements(pack, snapshot=snap)
        self.assertEqual(geometry.elements[0]["params"],
                         {"RBS_PIPE_DIAMETER_PARAM": 100.0,
                          "RBS_PIPE_OUTER_DIAMETER": 114.3})
        self.assertEqual(geometry.no_geometry, {})

    def test_a_cable_tray_without_a_complete_section_says_not_declared(self):
        """Without both dimensions, no rectangular cross-section is declared.

        The reason must point the author toward the operands, but the axis must not
        turn into a zero-value or an imagined clash shell.
        """
        pack = self._pack([{
            "op": "create_cable_tray", "id": "t1",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0],
            "level": {"by": "name", "value": "L1"},
            "tray_type": {"by": "name", "value": "Лестничный"}}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        self.assertEqual(
            geometry.no_geometry,
            {"create_cable_tray_section_not_declared": 1})
        self.assertNotIn("params", geometry.elements[0])
        clash = clash_snapshot.build_from_elements(
            geometry.elements, origin={"source": "test"})
        self.assertEqual(clash.records, [])

    def test_a_declared_cable_tray_section_stays_out_until_certified(self):
        """Width and height are expressed, but the containing shell is not proven.

        The clash layer gets no post-commit readback and has no physical
        containment certificate for its rectangular capsule. So the
        declared numbers are not passed to the hulls table either.
        """
        pack = self._pack([{
            "op": "create_cable_tray", "id": "t1",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0],
            "level": {"by": "name", "value": "L1"},
            "tray_type": {"by": "name", "value": "Лестничный"},
            "width_mm": 300.0, "height_mm": 100.0}])
        geometry = CB.bundle_elements(pack, snapshot=_rich_snapshot())
        self.assertEqual(
            geometry.no_geometry,
            {"create_cable_tray_geometry_not_certified": 1})
        self.assertNotIn("params", geometry.elements[0])
        clash = clash_snapshot.build_from_elements(
            geometry.elements, origin={"source": "test"})
        self.assertEqual(clash.records, [])


class NoOperationLeavesWithoutAVerdict(unittest.TestCase):
    """The law of the census, carried over to the batch: EVERY operation that creates a
    physical element leaves here either with geometry, or with a NAMED
    reason for its absence. A new registry operation whose body nobody
    thought about must bring down this test, rather than slip into the census silently.
    """

    def test_every_body_making_op_answers_with_geometry_or_a_reason(self):
        # WE ASK THE SAME AUTHORITY AS THE CODE (11.08.2026). Here stood
        # `sorted(CB.OP_CATEGORY)` — a shadow table, removed together with its debt
        # (`test_clash_coverage.OneTableForOneRelation`). The guard had not "weakened",
        # it was DEAD: an `AttributeError` fired before the first check, that
        # is, the completeness law had not run even once since the table was removed.
        silent: list[str] = []
        for name in CB.body_making_ops():
            op = {"op": name, "id": "x1"}
            geometry = CB.bundle_elements([{"ops": [op]}],
                                          snapshot=_rich_snapshot())
            if not geometry.elements:      # the operation creates no body at all
                continue
            element = geometry.elements[0]
            has_geometry = any(key in element for key in (
                "bbox_min_mm", "prism", "p0_mm"))
            if not has_geometry and not geometry.no_geometry:
                silent.append(name)
        self.assertEqual(silent, [], "операция уехала в перепись без причины")

    def test_an_unknown_new_op_is_named_rather_than_dropped(self):
        """A mutant: an operation this module has never parsed."""
        geometry = CB.bundle_elements(
            [{"ops": [{"op": "create_wall", "id": "w1"}]}],
            snapshot=_rich_snapshot())
        self.assertTrue(geometry.no_geometry,
                        "стена без оси уехала без единого слова")


class ThePrunerKeepsTheDifferenceBetweenEmptyAndAbsent(unittest.TestCase):

    def test_pruning_a_legacy_snapshot_yields_an_empty_dict(self):
        self.assertEqual(_om.prune_ground_snapshot(_bare_snapshot()), {})

    def test_pruning_keeps_only_what_a_body_needs(self):
        pruned = _om.prune_ground_snapshot(_rich_snapshot())
        self.assertEqual(sorted(pruned), ["floor_types", "levels", "wall_types"])
        self.assertEqual(pruned["wall_types"][0]["section"], _PLATE)
        self.assertNotIn("unique_id", pruned["wall_types"][0])

    def test_a_pruned_snapshot_still_feeds_the_bundle(self):
        pack = [{"ops": [{
            "op": "create_floor", "id": "f1",
            "outline": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0]],
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "Плита 300"}}]}]
        geometry = CB.bundle_elements(
            pack, snapshot=_om.prune_ground_snapshot(_rich_snapshot()))
        self.assertEqual(geometry.no_geometry, {})


if __name__ == "__main__":
    unittest.main()


# ── 🔴 F-079: ABSENCE IS NOT THE SAME AS INVALID (confirmed by execution on
# 04.09.2026) ──────────────────────────────────────────────────────────────
#
# `row.get("sizes") or ()` erased an invalid value BEFORE the type check, and the answer
# depended on FALSINESS, not on kind:
#
#     sizes=42   ->  named refusal «sizes must be a list»
#     sizes=0    ->  ACCEPTED as sizes=()
#     layers=0   ->  ACCEPTED as "no layers"
#     layers={}  ->  ACCEPTED as "no layers"
#
# The profile is evidence about the TYPE of the live document: "there are no layers" and "the layers
# could not be read" are different claims. On top of that, the declared witness `layer_count`
# was being ignored by the reader: a single layer with `layer_count: 999` was accepted and
# came out serialized as `1` in the loop.

_ЗДОРОВЫЙ = {"kind": "plate", "source": "WallType.Width",
             "thickness_mm": 200.0, "uniform": True}


def _сечение(**лишнее):
    from kir.open_model import TypeSection
    d = dict(_ЗДОРОВЫЙ); d.update(лишнее)
    return TypeSection.from_dict(d)


def test_отсутствие_остаётся_отсутствием():
    """No key present is a legitimate answer, "captured before the layers wave", and it must keep living."""
    s = _сечение()
    assert s.sizes == () and not s.layers


def test_ложное_неверное_значение_называется_как_и_истинное():
    """One field — one answer, regardless of the value's falsiness."""
    from kir.open_model import OpenModelProfileError
    for поле, значение in (("sizes", 0), ("sizes", 42), ("sizes", {}),
                           ("layers", 0), ("layers", {}), ("layers", 42),
                           ("blockers", 0)):
        try:
            _сечение(**{поле: значение})
        except OpenModelProfileError as e:
            assert f"{поле} must be a list" in str(e), (поле, значение, str(e))
        else:
            raise AssertionError(
                f"{поле}={значение!r} принято молча — стёрто вместо отказа")


def test_свидетель_числа_слоёв_проверяется():
    """Evidence that gets silently corrected stops being evidence."""
    from kir.open_model import OpenModelProfileError
    слои = [{"width_mm": 100.0, "function": "structure"}]
    общее = {"uniform": False, "blockers": ["layers"], "layers": слои}
    try:
        _сечение(**общее, layer_count=999)
    except OpenModelProfileError as e:
        assert "layer_count says 999" in str(e), str(e)
    else:
        raise AssertionError("противоречивый layer_count принят и переписан")
    # A CONTROL IN THE OTHER DIRECTION: an agreeing witness does not get in the way
    s = _сечение(**общее, layer_count=1)
    assert len(s.layers) == 1
