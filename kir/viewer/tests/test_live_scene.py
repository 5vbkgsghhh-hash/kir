"""The live scene: what is DECLARED, but has not yet gone to Revit.

The tests hold facts, each of which was found by a measurement on
11.08.2026, not derived by reasoning. Two of them are tests refuting
defects found after the code already "worked".
"""

import json
import struct
import unittest

from kir.viewer import honesty as H
from kir.viewer import live_scene as L

#: A type snapshot of the OPEN model in exactly the form the ground
#: stage writes it (`kir/tests/test_type_sections.py`). The form is
#: taken from there, not invented: our own form would check our own
#: parsing of our own fiction.
SNAPSHOT = {
    "levels": [{"id": 1, "name": "L1", "elevation_mm": 0.0}],
    "pipe_types": [{"id": 30, "name": "Сталь",
                    "section": {"kind": "nominal_table",
                                "source": "PipeSegment.GetSizes",
                                "sizes": [[100.0, 114.3]]}}],
}


def _pipe(oid, y=0.0):
    return {"op": "create_pipe", "id": oid,
            "p0_mm": [0.0, y, 2800.0], "p1_mm": [12000.0, y, 2800.0],
            "diameter_mm": 100.0,
            "pipe_type": {"by": "name", "value": "Сталь"},
            "level": {"by": "name", "value": "L1"}}


def _header(blob):
    head_len = struct.unpack_from("<I", blob, 8)[0]
    return json.loads(blob[12:12 + head_len].decode("utf-8"))


def _live_meta():
    return L.scene_from_programs([{"ops": [_pipe("p0")]}], snapshot=None)[1]


class QualificationIsDoneExactlyOnce(unittest.TestCase):
    """THE TEST REFUTING THE 11.08 DEFECT.

    `bundle_elements` qualifies addresses ITSELF (`bundle_oid` ->
    `p1/w0`), while `preview` does not qualify them at all. As long as
    the batch was fed to both already qualified, bodies arrived under
    `p1/p1/w0`, did not match the outlines, and EVERY element with a
    body was drawn TWICE: as a body and as a ghost. Measured: the census
    showed 13 elements where there are 8.
    """

    def test_an_element_with_a_body_is_not_also_drawn_as_a_ghost(self):
        pack = [{"ops": [_pipe("p0"), _pipe("p1", 1000.0)]}]
        blob, meta = L.scene_from_programs(pack, snapshot=SNAPSHOT)
        header = _header(blob)
        self.assertEqual(header["elements"], meta["honesty"]["total"])
        self.assertEqual(meta["bodies"], 2)
        self.assertEqual(header["elements"], 2)
        self.assertEqual(meta["honesty"]["by_fidelity"].get("no_body", 0), 0)

    def test_the_same_op_id_in_two_programs_gets_two_addresses(self):
        """`id` is unique WITHIN a program; a match between programs is
        legal. Without qualification, two pipes would collapse into
        one."""
        pack = [{"ops": [_pipe("p0")]}, {"ops": [_pipe("p0")]}]
        blob, meta = L.scene_from_programs(pack, snapshot=SNAPSHOT)
        self.assertEqual(_header(blob)["elements"], 2)
        self.assertEqual(meta["id_collisions"], 0)

    def test_refs_survive_qualification(self):
        """A `ref` under `KIR-L003` points only inside its own program,
        so a matching prefix on the target and the reference preserves
        the link. If it did not, a door would lose its host and end up
        in the census."""
        pack = [[{"op": "create_level", "id": "lv", "name": "L1",
                  "elev_mm": 0.0},
                 {"op": "create_wall", "id": "w0", "p0_mm": [0.0, 0.0],
                  "p1_mm": [12000.0, 0.0], "height_mm": 3200.0,
                  "level": {"by": "ref", "value": "lv"}}]]
        wall = L._qualify(pack)[0][1]
        self.assertEqual(wall["id"], "p1/w0")
        self.assertEqual(wall["level"], {"by": "ref", "value": "p1/lv"})


class BodiesNeedTheLiveModel(unittest.TestCase):
    """THE MEASUREMENT THAT DEFINES THE WHOLE SCREEN: without a snapshot
    of the open model there are no bodies.

    Wall thickness and pipe outer diameter live in the TYPE. Measured on
    11.08: a batch of six walls and a pipe gives 0 bodies out of 7, all
    seven are `needs_live_model`. The lead re-measured the same at
    scale: `snowdon_plumb_v4` — 905 bodies without a snapshot versus
    16 247 out of 16 257 (99.94%) with a snapshot. So body coverage is
    decided NOT by wiring, but by the presence of a snapshot, and the
    screen must say so.
    """

    def test_without_a_snapshot_there_are_no_bodies_at_all(self):
        pack = [{"ops": [_pipe("p0"), _pipe("p1", 1000.0)]}]
        _, meta = L.scene_from_programs(pack, snapshot=None)
        self.assertEqual(meta["bodies"], 0)
        self.assertGreater(meta["bodies_declared"], 0)
        self.assertIn("needs_live_model", meta["blind_by_class"])

    def test_with_a_snapshot_the_same_pack_gets_bodies(self):
        pack = [{"ops": [_pipe("p0"), _pipe("p1", 1000.0)]}]
        _, meta = L.scene_from_programs(pack, snapshot=SNAPSHOT)
        self.assertEqual(meta["bodies"], 2)
        self.assertNotIn("needs_live_model", meta["blind_by_class"])

    def test_the_absence_of_a_snapshot_is_stated_in_words(self):
        """Silence here would read as "the building is like this". It is
        not — we simply did not open the model.

        14.08.2026: the test held on to the WORD "NO" in the prose, not
        to the fact. When the binary `sections` was split into three
        states, the prose became more precise ("the snapshot was NOT
        REQUESTED" instead of "there is no snapshot") — and the test
        went red on an IMPROVEMENT. A pin on a substring of prose is not
        an instrument: it goes red from a text edit and stays silent
        about a meaning substitution. We hold on to the state.
        """
        _, meta = L.scene_from_programs([{"ops": [_pipe("p0")]}], snapshot=None)
        self.assertFalse(meta["sections_present"])
        self.assertEqual(meta["sections_state"], "absent")
        self.assertTrue(meta["sections_ru"].strip())

    def test_no_snapshot_and_an_empty_snapshot_are_different_facts(self):
        """THE TEST REFUTING THE THREE STATES.

        `bool(sections)` collapsed "grounding did not arrive" and
        "asked, there are no sections in the document" into one answer.
        These are different facts: the first is about our own path, the
        second is about the document, and different people fix them.
        FAIL control: bring back `bool()` — both calls will give the
        same result, and the test will go red.
        """
        _, absent = L.scene_from_programs([{"ops": [_pipe("p0")]}],
                                          snapshot=None)
        _, empty = L.scene_from_programs([{"ops": [_pipe("p0")]}], snapshot={})
        self.assertEqual(absent["sections_state"], "absent")
        self.assertEqual(empty["sections_state"], "empty")
        self.assertNotEqual(absent["sections_ru"], empty["sections_ru"])
        # AND BOTH SAY THE SAME THING ABOUT BODIES: there won't be any.
        # A different explanation must not turn into a different
        # promise.
        self.assertFalse(absent["sections_present"])
        self.assertFalse(empty["sections_present"])

    def test_a_bodiless_element_is_a_ghost_and_not_a_disappearance(self):
        """A missing element is indistinguishable from a nonexistent
        one. That is why it is drawn as a plan outline and marked
        `no_body`."""
        _, meta = L.scene_from_programs([{"ops": [_pipe("p0")]}], snapshot=None)
        self.assertEqual(meta["honesty"]["by_fidelity"].get("no_body"), 1)
        self.assertTrue(meta["honesty"]["balanced"])


class ADeclaredWallReachesTheScreenWithABody(unittest.TestCase):
    """THE OWNER'S SYMPTOM FROM 14.08, IN FULL AND AT HIS OWN LEVEL.

    He wrote "build a wall" in the KIR window, the path went all the way
    through — and the scene stayed empty. The cause lived two modules
    away from here: the wall was not allowed to build a body from the
    declared strip, and a declared wall has no bounding box BY
    CONSTRUCTION, so the choice was "strip versus nothing".

    The tests in `clash/tests/test_prism_source.py` hold this fix right
    at the shell itself. This one holds it WHERE THE OWNER LOOKS: the
    fix's radius is the import graph, not the file, and half of today's
    misses were exactly this — checking the function, not the path.
    """

    WALL_SNAPSHOT = {
        "levels": [{"id": 1, "name": "L1", "elevation_mm": 0.0}],
        "wall_types": [{"id": 40, "name": "Типовой - 200мм",
                        "section": {"kind": "plate", "thickness_mm": 200.0,
                                    "uniform": True, "blockers": [],
                                    "source": "type"}}],
    }

    def _wall(self, named=True):
        op = {"op": "create_wall", "id": "w0",
              "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [6000.0, 0.0, 0.0],
              "height_mm": 3000.0,
              "level": {"by": "name", "value": "L1"}}
        if named:
            op["type"] = {"by": "name", "value": "Типовой - 200мм"}
        return op

    def test_the_wall_has_a_body_on_the_screen(self):
        _, meta = L.scene_from_programs([{"ops": [self._wall()]}],
                                        snapshot=self.WALL_SNAPSHOT)
        self.assertEqual(meta["bodies"], 1)
        self.assertEqual(meta["blind_by_class"], {})

    def test_a_wall_without_a_named_type_still_says_why(self):
        """FAIL CONTROL: the screen must be able to say "no body, and
        here is why".

        Without it, the previous test would not distinguish "the body
        was built" from "the reason went silent". This is exactly the
        OWNER'S FIRST CASE — the type was not named — and it must stay
        named.
        """
        _, meta = L.scene_from_programs([{"ops": [self._wall(named=False)]}],
                                        snapshot=self.WALL_SNAPSHOT)
        self.assertEqual(meta["bodies"], 0)
        self.assertIn("not_declared_by_program", meta["blind_by_class"])


class WhyThereIsNoBodyIsNamed(unittest.TestCase):

    def test_classes_come_from_the_owner_of_the_table(self):
        """The class is computed by `clash_bundle`, not by a copy here:
        six lines of a local implementation would silently drift from
        the original."""
        from kir import clash_bundle as CB
        _, meta = L.scene_from_programs([{"ops": [_pipe("p0")]}], snapshot=None)
        self.assertTrue(set(meta["blind_by_class"]) <=
                        set(CB.BLIND_CLASS_RU) | {"unclassified"})
        self.assertEqual(meta["blind_class_ru"], dict(CB.BLIND_CLASS_RU))

    def test_each_class_ships_with_the_sentence_that_says_who_fixes_it(self):
        """"No body" without a cause is useless; with a cause it is an
        instruction of what to do, and the addressee differs by class:
        the operand is fixed by the AUTHOR, the snapshot by the ground
        stage, the content lock by `kir/clash`."""
        for name, text in _live_meta()["blind_class_ru"].items():
            self.assertTrue(text.strip(), name)

    def test_a_hole_in_the_foreign_table_is_shown_not_swallowed(self):
        """A cause without a class goes into `unclassified` and is
        printed: otherwise a hole in the table would read as the
        absence of a problem."""
        self.assertIn("blind_unclassified", _live_meta())

    def test_the_scope_of_the_class_is_admitted(self):
        """`BundleGeometry` computes causes AS A BATCH. Assigning a
        class to an element would be a guess put on the element, and a
        guess on an element reads as a measurement."""
        self.assertIn("ПАЧКОЙ", _live_meta()["blind_scope_ru"])


class JournalFactsReachTheScreen(unittest.TestCase):
    """THE TEST REFUTING THE SECOND 11.08 DEFECT.

    The journal note was appended to `meta` AFTER `builder.finish(meta)`.
    The header lives INSIDE the scene bytes, so program eviction and a
    missing snapshot reached the server and never reached the screen.
    The warning existed and stayed silent.
    """

    def test_the_journal_note_is_inside_the_encoded_header(self):
        blob, _ = L.scene_from_programs(
            [{"ops": [_pipe("p0")]}], snapshot=SNAPSHOT,
            journal={"evicted": 7, "truncated_ru": "семь вытеснено"})
        header = _header(blob)
        self.assertIsNotNone(header.get("journal"))
        self.assertEqual(header["journal"]["evicted"], 7)

    def test_no_journal_is_null_rather_than_a_missing_key(self):
        self.assertIsNone(
            _header(L.scene_from_programs([{"ops": [_pipe("p0")]}])[0])["journal"])


class HeightIsNeverInvented(unittest.TestCase):

    def test_a_missing_height_gets_a_conspicuous_stub_and_a_name(self):
        """A plausible number is worse than a missing one: 2500 mm would
        hide among the real walls, 100 mm is visible right away."""
        self.assertEqual(L.FALLBACK_HEIGHT_MM, 100.0)
        pack = [[{"op": "create_level", "id": "lv", "name": "L1",
                  "elev_mm": 0.0},
                 {"op": "create_wall", "id": "w0", "p0_mm": [0.0, 0.0],
                  "p1_mm": [12000.0, 0.0],
                  "level": {"by": "ref", "value": "lv"}}]]
        _, meta = L.scene_from_programs(pack)
        self.assertGreaterEqual(meta["height_unknown"], 1)
        self.assertIn("НЕ их высота", meta["height_unknown_ru"])


class AxesRideOnEveryElement(unittest.TestCase):

    def test_the_tally_matches_the_buffer_byte_for_byte(self):
        """A summary that has drifted from the buffer is a signature
        under something unread."""
        blob, meta = L.scene_from_programs(
            [{"ops": [_pipe("p0"), _pipe("p1", 1000.0)]}], snapshot=SNAPSHOT)
        header = _header(blob)
        span = next(b for b in header["buffers"] if b["name"] == "elem_axes")
        base = 12 + struct.unpack_from("<I", blob, 8)[0]
        raw = struct.unpack_from(f"<{span['length']}B", blob,
                                 base + span["offset"])
        tally = {}
        for byte in raw:
            tally[str(byte)] = tally.get(str(byte), 0) + 1
        self.assertEqual(tally, meta["axes_tally"])

    def test_an_element_without_an_op_is_unjudgeable_not_clean(self):
        self.assertEqual(H.axes_byte(None), H.AXES_UNJUDGEABLE)
        self.assertNotEqual(H.AXES_UNJUDGEABLE, 0)


class UnprovenOpsAreDistinguishable(unittest.TestCase):

    def test_an_element_built_by_an_unproven_op_is_marked(self):
        """`tool_doc.UNPROVEN` — 30 entries as of 11.08.2026. An element
        built by an unproven op must be distinguishable: "the gate
        assembles it" and "it was built live" are different claims."""
        from kir.tool_doc import UNPROVEN
        self.assertIn("create_conduit", UNPROVEN)
        pack = [{"ops": [{"op": "create_conduit", "id": "c0",
                          "p0_mm": [0.0, 0.0, 2800.0],
                          "p1_mm": [12000.0, 0.0, 2800.0],
                          "diameter_mm": 50.0,
                          "level": {"by": "name", "value": "L1"}}]}]
        _, meta = L.scene_from_programs(pack, snapshot=SNAPSHOT)
        self.assertEqual(meta["honesty"]["by_trust"].get("op_unproven"), 1)


class ACursorSliceIsATailNotABuilding(unittest.TestCase):
    """THE THIRD 11.08 DEFECT, AND IT IS MINE TOO.

    `/api/viewer/live?since=N` returned a scene assembled ONLY from
    programs past the cursor, and in form it was indistinguishable from
    a whole building: the header carried `elements`, the census
    converged, the picture was drawn. Measured on a journal of two
    programs: `since=1` gave a building of ONE element, `since=2` gave
    an EMPTY building, and both looked sound.

    There is no scene delta: `scene_from_programs` can only build the
    whole. So a tail must be CALLED a tail — at the root of the header,
    not only in the journal note.
    """

    def _session(self):
        from kir.live import journal as journal_mod
        key = journal_mod.key_for("тест-устройство", "тест-док")
        journal_mod.reset(key)
        journal_mod.append(key, {"ops": [
            {"op": "create_level", "id": "lv", "name": "L1", "elev_mm": 0.0}]})
        journal_mod.append(key, {"ops": [_pipe("p0")]})
        return "тест-устройство", "тест-док"

    def _base(self, device, doc):
        """The base signature that the client must return together with
        the cursor.

        14.08.2026: the three tests below called
        `scene_from_session(..., since>0)` WITHOUT it and failed on
        `StaleBase`. The refusal is correct — it appeared after the
        tests and protects against gluing a tail onto someone else's
        base; the tests were stale. The signature is asked from the same
        journal, not invented here: a second source would silently
        drift from the first.
        """
        from kir.live import journal as journal_mod
        session = journal_mod.get(journal_mod.key_for(device, doc))
        return L.base_digest(list(getattr(session, "datums", ()) or ()),
                             getattr(session, "sections", None),
                             getattr(session, "programs_evicted", 0))

    def test_a_tail_without_the_base_signature_is_refused_by_name(self):
        """FAIL CONTROL for the three tests below: without a base
        signature the delta must REFUSE, not assemble. Otherwise the
        tail would glue onto someone else's building, and both would
        look sound."""
        device, doc = self._session()
        with self.assertRaises(L.StaleBase):
            L.scene_from_session(device, doc, 1)

    def test_since_zero_is_not_partial(self):
        device, doc = self._session()
        blob, _ = L.scene_from_session(device, doc, 0)
        self.assertFalse(_header(blob)["partial"])

    def test_a_positive_cursor_is_marked_partial_in_the_root_header(self):
        device, doc = self._session()
        blob, _ = L.scene_from_session(device, doc, 1, self._base(device, doc))
        header = _header(blob)
        self.assertTrue(header["partial"])
        self.assertIn("ХВОСТ", header["partial_ru"])

    def test_an_empty_tail_is_still_marked_rather_than_looking_like_a_void(self):
        """`since` past the end of the journal gives ZERO elements. An
        empty building and a building that was not shown must read
        differently."""
        device, doc = self._session()
        blob, meta = L.scene_from_session(device, doc, 99, self._base(device, doc))
        self.assertEqual(meta["honesty"]["total"], 0)
        self.assertTrue(_header(blob)["partial"])

    def test_the_note_says_how_many_of_how_many(self):
        device, doc = self._session()
        _, meta = L.scene_from_session(device, doc, 1, self._base(device, doc))
        self.assertEqual(meta["journal"]["since"], 1)
        self.assertEqual(meta["journal"]["returned"], 1)
        self.assertEqual(meta["journal"]["held"], 2)
