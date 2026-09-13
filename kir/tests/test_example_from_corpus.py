"""A CORPUS SAMPLE — `revit_ir`'s second mode: show without building anything.

WHY THIS MODE EXISTS AT ALL, IN ONE MEASUREMENT (17.08.2026)
=========================================================
A model starting from a blank sheet writes **11 operations per attempt**; a real floor of a residential
tower carries **1000**. It writes little not because it is weak: given a real
floor, it spent 433 s parsing the unit layout and found three defects in someone else's
production project. It writes little because it had never seen production.

🔴 AND THE MAIN THING PINNED HERE: THE SAMPLE RIDES IN THE RECEIPT, NOT IN THE SANDBOX.
The first draft placed it into the script as a third object alongside `model` and `building`
— and that is wrong BY CONSTRUCTION: the script runs in a SEPARATE PROCESS and
hands operations outward, meaning **the model never sees its variables**. Handing
the sample to the script means handing it to nobody: the same model writes the script that
has not read the sample yet. The only channel to the model is the receipt, and the test for this
comes first.

THREE OUTCOMES, AND NOT ONE IS EMPTY: a sample · "several fit" (name them, don't
choose) · a refusal that names the DICTIONARY you can index into.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from kir import serving
from kir.decompile import program_source as ps
from kir.tests.gate_fixture import enter_kir_mode


def _restore_env(key: str, value: str | None) -> None:
    """Return WHAT WAS FOUND, including its absence (a form paid for on 17.08)."""
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


def _leaf(index: int) -> dict:
    """An L1 sheet of the same shape as the one lying in the real corpus tree.

    The shape is taken from `sob62_r23_v5` (`fold.iter_l1_leaves`), not invented: a test that
    assembles its input by hand guards the fixture, not the product (form 27).
    """
    return {
        "_id": "leaf%04d" % index,
        "anchor_mm": None,
        "kind": "op",
        "level_name": "L1",
        "op_name": "create_wall",
        "params": {"p0_mm": [0.0, float(index) * 1000.0, 0.0],
                   "p1_mm": [6000.0, float(index) * 1000.0, 0.0],
                   "level": {"by": "element_id", "value": "500", "_id": "500"},
                   "height_mm": 2800.0},
        "source_element_id": str(900_000 + index),
        "type_name": "Стена 200",
    }


def _floor(level: str, elevation: float, count: int) -> dict:
    return {
        "kind": "group", "node_id": "floor_%s" % level, "label": level,
        "macro": {"type": "floor", "level_name": level,
                  "elevation_mm": elevation, "semantic_mode": "zones"},
        "payload": None, "members": [], "facts": {}, "verdict": None,
        "children": [{"kind": "leaf", "node_id": "n%s_%d" % (level, i),
                      "payload": _leaf(i), "children": [], "members": [],
                      "facts": {}, "macro": None, "label": "", "verdict": None}
                     for i in range(count)],
    }


CARD = ("# KIR Passport — Дом образцовый\n\n"
        "- Revit: 2023\n"
        "- change_stamp: `demo_v1`\n"
        "- gestalt: Здание, 3 этажа. Назначение: жилое.\n"
        "- элементов: 12\n")


class CorpusFixture(unittest.TestCase):
    """A corpus of a single decompile — TWO floors, and this is not decoration.

    The rule "take the fullest floor" is indistinguishable, on a SINGLE floor, from "take
    whatever comes first": a control on a degenerate input is green by construction.
    Here there are two floors, and they have different fullness.
    """

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="kir-example-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = os.path.join(self.root, "demo_v1")
        os.makedirs(self.run_dir)
        tree = {"kind": "root", "node_id": "root", "label": "", "macro": None,
                "payload": None, "members": [], "facts": {}, "verdict": None,
                "children": [_floor("L1", 0.0, 2), _floor("L2", 3300.0, 5)]}
        with open(os.path.join(self.run_dir, "tree.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(tree, handle, ensure_ascii=False)
        with open(os.path.join(self.run_dir, "passport.md"), "w",
                  encoding="utf-8") as handle:
            handle.write(CARD)


class TheFloorChoiceIsPresented(CorpusFixture):
    def test_the_fullest_floor_wins_and_the_losers_are_named(self):
        got = ps.floor_source(self.run_dir)
        self.assertEqual(got["level"], "L2", got)
        self.assertEqual(got["leaves"], 5)
        self.assertEqual(got["rule"], "самый полный этаж разбора")
        self.assertEqual([r["level"] for r in got["runners_up"]], ["L1"])
        self.assertEqual(got["levels_total"], 2)

    def test_a_named_level_overrides_and_says_so(self):
        got = ps.floor_source(self.run_dir, level="L1")
        self.assertEqual(got["level"], "L1")
        self.assertEqual(got["rule"], "назван вызывающим")

    def test_an_unknown_level_refuses_and_lists_what_there_is(self):
        got = ps.floor_source(self.run_dir, level="L99")
        self.assertIn("refused", got)
        self.assertIn("L1", got["refused"])
        self.assertIn("L2", got["refused"])

    def test_the_document_name_comes_from_the_card_not_from_passport_json(self):
        """`passport.json` carries the entire tree, up to 206 MB; the card is 2 KB.

        Neighbors paid 17.2 s FOR EVERY CALL to this door for the sake of one
        string field. The first draft read the first 4 KB of `passport.json` and
        silently returned an EMPTY name — the header does not fit there.
        """
        self.assertEqual(ps.floor_source(self.run_dir)["document"],
                         "Дом образцовый")


class NothingIsPrintedSilently(CorpusFixture):
    def test_the_count_is_stated_and_it_adds_up(self):
        got = ps.floor_source(self.run_dir)
        self.assertEqual(got["ops_printed"], got["ops_total"])
        self.assertTrue(got["complete"])
        self.assertIn("ПОЛНО", got["report_ru"])

    def test_a_truncated_sample_says_how_much_was_cut(self):
        got = ps.floor_source(self.run_dir, cap_bytes=200)
        self.assertFalse(got["complete"])
        self.assertGreater(got["truncated_bytes"], 0)
        self.assertIn("НЕ напечатан", got["truncation_ru"])
        self.assertEqual(len(got["source"].encode("utf-8")), 200)

    def test_a_run_without_a_tree_refuses_by_name(self):
        empty = os.path.join(self.root, "no_tree")
        os.makedirs(empty)
        got = ps.floor_source(empty)
        self.assertIn("tree.json", got["refused"])


class TheSampleReachesTheModelNotTheSandbox(CorpusFixture):
    """🔴 THE FILE'S MOST IMPORTANT TEST, AND IT IS ABOUT THE CHANNEL, NOT THE CONTENT."""

    def setUp(self) -> None:
        # 🔴 THE GATE IS OPENED EXPLICITLY, AND THIS IS A 17.08.2026 FIX FROM A MEASUREMENT.
        # The first draft called the door WITHOUT the gate's three conditions — and was green,
        # because the sample path returned ABOVE the check. That is, the test did not
        # forget to open the gate: it was not on this path at all. Measurement: with an empty
        # `KUKAI_ADMIN_DEVICES`, a call to `program` was refused by the gate, while a call to
        # `example` handed back the source of someone else's production building.
        super().setUp()
        prev_flag = os.environ.get("KUKAI_KIR_TOOL")
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self.addCleanup(_restore_env, "KUKAI_KIR_TOOL", prev_flag)
        device = mock.patch.object(serving, "_turn_device_id",
                                   return_value=serving.ADMIN_DEVICE)
        device.start()
        self.addCleanup(device.stop)
        enter_kir_mode(self)

    def _call(self, **args):
        # 🔴 WHAT IS RESTORED IS WHAT WAS FOUND, NOT DELETING ONE'S OWN (17.08.2026).
        # The first draft set the key and then removed it with `os.environ.pop(...)` —
        # that is, it DELETED it even in cases where it had existed before the test. On this
        # machine it exists and points at a real corpus, so in the
        # wide run my test wiped it out for ALL the tests that followed: **18
        # reds in other people's files**, each one looking like its own.
        # It was not I who caught this, but this tree's environment guard (`conftest.py:172`),
        # which named the key and its previous value by name.
        #
        # The form is already recorded in the canon for a different case: a `finally` that
        # restores ITS OWN MEMORY instead of the FOUND value.
        # `mock.patch.dict` returns exactly what was there before — including
        # the key's absence.
        patched = mock.patch.dict(os.environ,
                                  {"KUKAI_DECOMPILE_DATA": self.root})
        patched.start()
        self.addCleanup(patched.stop)
        return asyncio.run(serving.handle_revit_ir(args, None, None))

    def test_the_source_lands_in_the_receipt(self):
        got = self._call(example="образцовый")
        self.assertTrue(got.get("ok"), got.get("message_ru"))
        self.assertTrue(got["example"])
        self.assertIn("create_wall", got["program_py"])
        self.assertEqual(got["ops_printed"], got["ops_total"])
        # The move builds NOTHING: no bridge, no program, no witness.
        self.assertNotIn("witness", got)
        self.assertNotIn("outcome", got)

    def test_a_shut_gate_refuses_the_sample_and_names_no_building(self):
        """A CONTROL for `setUp`: with the gate CLOSED, the sample is not handed over.

        Without this test, opening the gate in `setUp` would be a ritual: green would
        stay green whether the gate was open or closed — green with no act of
        discrimination (form 18). Here the gate is closed, and the call must
        refuse, naming not a single building and handing back not a single line of source.
        """
        with mock.patch.object(serving, "revit_ir_enabled", return_value=False):
            got = self._call(example="образцовый")
        self.assertFalse(got["ok"], got)
        self.assertEqual(got.get("error"), "gate", got)
        for leaked in ("program_py", "example", "ops_printed"):
            self.assertNotIn(leaked, got, leaked)

    def test_the_sample_survives_the_script_first_switch(self):
        """A SEAM WITH A NEIGHBORING LINE: the `KUKAI_KIR_SCRIPT_FIRST` switch collapses
        the `program` schema's ANNOUNCEMENT, and the sample must survive both of its positions.

        There is no real overlap — the sample hands back the parsed floor as
        SOURCE in `program_py`, that is, in exactly the form the switch is pushing
        toward; it has no need at all for `program`'s expanded signatures. But "no need" is a
        line of reasoning, and the test exists here because a plain merge of two lines, where the
        condition is not expressed in the text, stops nothing (canon form 16). Measurement of 17.08
        against the prod environment: the tool description was
        100 542 B with the switch OFF and 49 945 B with it ON, the set of properties the
        same in both cases.
        """
        patched = mock.patch.dict(os.environ,
                                  {"KUKAI_KIR_SCRIPT_FIRST": "1"})
        patched.start()
        self.addCleanup(patched.stop)

        tools: list = []
        serving.inject_revit_ir_schema(tools)
        props = tools[0]["function"]["parameters"]["properties"]
        self.assertIn("example", props, sorted(props))

        got = self._call(example="образцовый")
        self.assertTrue(got.get("ok"), got.get("message_ru"))
        self.assertIn("create_wall", got["program_py"])

    def test_a_sample_call_with_a_program_is_NOT_a_sample_call(self):
        """`example` TOGETHER with a program would mean two intentions at once.

        Silently picking one would mean deciding for the caller. Such a call
        goes down the ordinary path and is refused by form — rather than losing half of itself.
        """
        self.assertFalse(serving._example_only(
            {"example": "образцовый", "program": {"ops": []}}))
        self.assertFalse(serving._example_only(
            {"example": "образцовый", "program_py": "pass"}))
        self.assertTrue(serving._example_only({"example": "образцовый"}))
        self.assertFalse(serving._example_only({"example": "   "}))

    def test_nothing_found_names_the_vocabulary_to_hit(self):
        got = self._call(example="космодром")
        self.assertFalse(got["ok"])
        self.assertTrue(got["refused"])
        # A refusal that gives no next move is, to an LLM, the same as silence.
        self.assertTrue(len(got["message_ru"]) > 60, got["message_ru"])

    def test_the_capability_is_declared_in_the_tool_schema(self):
        """A capability the model has nowhere to read about does NOT EXIST for it.

        This is exactly how `sdk.py` sat for five weeks: 493 lines, unreachable,
        because they had no door and no text.
        """
        from kir.tool_doc import example_schema

        schema = example_schema()
        self.assertEqual(schema["type"], "string")
        self.assertIn("program_py", schema["description"])


if __name__ == "__main__":
    unittest.main()
