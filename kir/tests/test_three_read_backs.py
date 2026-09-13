"""THREE REVERSED WIRES: the quantity was computed, was written — and nobody read it.

THE DEFECT THIS FILE GREW OUT OF (19.08.2026, live benchmark). Three
capabilities had been BUILT and stayed silent, because each one had no reader:

  * `translation_cert.REFINEMENT` knew which obligations WOULD NOT RUN for this
    program — and the model learned about it from a human a day later. The cost: 420
    columns at 2500 mm instead of 3600–4500 (the conditional obligation of the top binding
    was lifted by skipping `top_level`) and 540 out of 540 beams at z=0 despite
    «Этаж 5» being written (the beam's level is derived by Revit, the argument decides nothing);
  * `journal_store.replay()`/`read_events()` had been written, covered by tests, and
    WERE NEVER CALLED FROM ANYWHERE: events landed on disk with `fsync`, while the building
    vanished along with the process;
  * `created_ledger` had been written to since 17.08 (measured: 30 lines, 471 elements per day) and
    was read by no one — clause 9 of the NAKAZ, verbatim.

THE FORM OF THE CHECK IS MUTATION (discipline C5 of this house, the model being
`test_witness_vacuity`): the wire is RIPPED OUT, and the assertion MUST fail.
A test that stays green after its subject is deleted is checking nothing.

🔴 WHAT THESE TESTS PIN DOWN ESPECIALLY — DISTINCTIONS, NOT FACTS:
  * restored does NOT EQUAL verified: `dispatched` at the moment the
    process crashed means "there is no evidence", not "in flight", and
    `running_unknown` must be what arrives — otherwise the reader is invited to wait for an answer that
    will never come;
  * "in the journal" does NOT EQUAL "accepted": `created_ledger` is written BEFORE acceptance;
  * an empty rehearsal must SAY "nothing to do" rather than stay silent: silence
    is indistinguishable from "nothing was checked".
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kir import created_ledger as cl
from kir import serving
from kir.live import journal
from kir.live import journal_store


def _wall(top: bool) -> dict:
    op = {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
          "level": {"by": "name", "value": "Этаж 1"}}
    if top:
        op["top_level"] = {"by": "name", "value": "Этаж 2"}
    else:
        op["height_mm"] = 3000
    return {"ops": [op]}


class RehearsalReachesTheModel(unittest.TestCase):
    """E1.3 — the rehearsal arrives in the response, not just in the terminal."""

    def test_a_missing_top_level_is_named_loudly(self):
        block = serving._rehearsal_block(_wall(top=False))
        self.assertIsNotNone(block)
        gate = block["will_not_be_checked"]["gate"]
        self.assertTrue(gate, "пропуск top_level обязан быть НАЗВАН")
        self.assertTrue(all(g["because"] == "пропущено top_level" for g in gate))
        self.assertTrue(all(g["transfers"] for g in gate),
                        "обязано быть сказано, ЧТО берёт власть вместо программы")

    def test_a_wall_WITH_top_level_is_not_accused(self):
        """The mirror case: the obligation was lifted LEGITIMATELY, and lying about it is not allowed.

        The first edition of the instrument printed, for a wall WITH a binding, «вместо программы
        решает: верх задаётся числом» — text that is false exactly where
        everything is correct.
        """
        block = serving._rehearsal_block(_wall(top=True))
        self.assertEqual(block["will_not_be_checked"]["gate"], [])

    def test_an_empty_rehearsal_SAYS_so_instead_of_going_silent(self):
        note = serving._rehearsal_note_ru(serving._rehearsal_block(_wall(top=True)))
        self.assertIn("нечего", note)

    def test_the_group_is_walked_or_the_frame_is_invisible(self):
        """The entire framework of the benchmark's buildings lived inside `create_group.members`.

        🔴 THE NUMBERS WERE FIXED ON 30.08.2026 (F-354), AND THE OLD ONES WERE WRONG, not
        "outdated". Here stood `elements_total == 4` with the argument "1 group +
        3 placements" and `count == 3` with the argument "beams inside a group must
        be counted BY PLACEMENTS". It is precisely this argument that is refuted: a beam
        is counted by OCCURRENCES, and the occurrences are `1 + len(placements)`.

        The law is stated by three authorities of the tree, not by opinion:
          * the emitter — `authoring.py`, `want_instances = 1 + len(placements)`;
          * the parameter's kind — `authoring_validation.py`, «occurrence 0 is the
            members themselves, so an EMPTY list is legal»;
          * the 18.08 measurement — the template member materializes ON TOP OF the placements
            (59 duplicates across the building).

        So there are FOUR beams (the template occurrence plus three placements). The former
        four was the same undercount, pinned in a SECOND place: the test
        was written to fit the bug and therefore did not catch it.

        🔴 THE NUMBER WAS FIXED A SECOND TIME ON 31.08.2026 (`E-67`), 5 -> 8, and this is the
        very same undercount that the previous edition of THIS SAME text named and
        left open with the words "it is DIFFERENT, it is older than F-354, and I have no measurement
        for it". A measurement now exists, and it is corpus-wide: `group.index.json`
        across 93 directories (67 with an index: 15 raw + 52 compressed `.gz`), 11
        distinct buildings by fingerprint — the undercount affects 7 buildings out of 11 and
        amounts to 6912 group-elements.

        So groups too are FOUR, not one: `elements_total` = 4 (instances of the
        group) + 4 (beam occurrences) = EIGHT. The obligations did NOT
        move in the process — their multiplier is separate from the element count, and the guard
        `test_the_group_op_multiplicity_does_two_jobs` pins this down.
        """
        prog = {"ops": [{
            "op": "create_group", "id": "g", "name": "k",
            "members": [{"op": "create_beam", "id": "b",
                         "p0_mm": [0, 0, 0], "p1_mm": [6000, 0, 0],
                         "level": {"by": "name", "value": "Этаж 5"}}],
            "placements": [[0, 0], [6000, 0], [12000, 0]]}]}
        block = serving._rehearsal_block(prog)
        self.assertEqual(block["elements_total"], 8,
                         "4 экземпляра группы (определение плюс три "
                         "размещения) + 4 вхождения балки")
        overwritten = block["value_overwritten_by_revit"]
        self.assertEqual([d["param"] for d in overwritten], ["level"])
        self.assertEqual(overwritten[0]["count"], 4,
                         "балки внутри группы считаются по ВХОЖДЕНИЯМ: "
                         "want_instances = 1 + len(placements)")

    def test_mutation_the_stamper_torn_out_fails_this(self):
        """Rip out the wire — the assertion must fail."""
        original = serving._rehearsal_block
        try:
            serving._rehearsal_block = lambda program: None
            result = serving._stamp_rehearsal({"ok": True}, _wall(top=False))
            self.assertNotIn("rehearsal", result,
                             "без провода репетиции в ответе нет — и это ловится")
        finally:
            serving._rehearsal_block = original
        restored = serving._stamp_rehearsal({"ok": True}, _wall(top=False))
        self.assertIn("rehearsal", restored)
        self.assertIn("rehearsal_note_ru", restored)


class TheWiresAreActuallyConnected(unittest.TestCase):
    """A showroom that nobody calls is the same silence we are treating.

    🔴 THE HONEST LIMIT OF THIS CLASS, NAMED RATHER THAN HIDDEN. The tests below
    read the SOURCE of the door and require that a call be present. This proves that the wire
    IS IN THE TEXT, and does NOT prove that it fires on a live turn: "is the
    line there" and "does it happen" are different quantities, and in this house conflating them
    gets you hit. Full proof comes from a live turn through `/admin/kir/run`; here
    stands a cheap guard against SILENT DELETION, not a replacement for it.
    """

    #: How many WRITE-return points each door has. We count, rather than merely check
    #: presence: the chat door has two (the plan and the single program), and stripping the
    #: stamp off just ONE would have slipped past a simple `assertIn`. The number is a floor, not
    #: proof: it catches deletion, not substitution.
    _WRITING_RETURNS = {"handle_revit_ir": 2, "handle_revit_ir_bulk": 1}

    def test_both_doors_stamp_the_rehearsal(self):
        import inspect
        for door in (serving.handle_revit_ir, serving.handle_revit_ir_bulk):
            with self.subTest(door=door.__name__):
                src = inspect.getsource(door)
                want = self._WRITING_RETURNS[door.__name__]
                self.assertGreaterEqual(
                    src.count("_stamp_rehearsal("), want,
                    f"{door.__name__}: штамп репетиции снят хотя бы с одного "
                    f"пишущего возврата (ожидалось не меньше {want})")
                self.assertIn("_rehearse_only(", src,
                              f"{door.__name__} потеряла режим репетиции")

    def test_the_chat_door_offers_the_created_ledger(self):
        import inspect
        src = inspect.getsource(serving.handle_revit_ir)
        self.assertIn("_created_only(", src)

    def test_all_five_input_fields_are_declared_in_the_schema(self):
        """A capability nowhere written down does NOT EXIST for the model.

        This is not an abstraction: the Python geometry sat unused for a whole shift
        precisely because the tool's description denied it.
        """
        tools: list = []
        serving.inject_revit_ir_schema(tools)
        props = tools[0]["function"]["parameters"]["properties"]
        for field in ("program", "program_py", "example", "rehearse", "created"):
            with self.subTest(field=field):
                self.assertIn(field, props)
        # A description is required for SCALAR fields. `program` has none and should not
        # have one: it is an object whose meaning is carried by the tool's description and the
        # schema of operations inside it, and a string over the object would be a third carrier
        # of one idea. The requirement "a description for everything" was my own mistake, and
        # it is fixed here, rather than by bending the code to fit the test.
        for field in ("program_py", "example", "rehearse", "created"):
            with self.subTest(field=field):
                self.assertTrue(str(props[field].get("description") or "").strip(),
                                f"{field} без описания невидимо для модели")


class TheNoWriteModesTouchNothing(unittest.TestCase):
    """"Writes nothing" is a promise, and it is verified with an EXPLODING bridge.

    You cannot assert "there was no trip" by looking at a successful response: success is not
    proof of the absence of a call. So here the bridge throws an exception on
    any call, and a green test means EXACTLY one thing — it was never invoked, not once.
    """

    def setUp(self):
        # The KIR-mode gate checks the device and the turn flag; the subject of this
        # test is not the gate, but what is BEHIND it, so it is lifted explicitly and only
        # for the duration of the test.
        self._gate = serving.revit_ir_enabled
        serving.revit_ir_enabled = lambda: True

    def tearDown(self):
        serving.revit_ir_enabled = self._gate

    @staticmethod
    async def _explode(method, params):
        raise AssertionError(
            f"режим без записи позвал мост: {method} — это уже не репетиция")

    def _call(self, args):
        import asyncio
        return asyncio.run(serving.handle_revit_ir(
            args, None, self._explode, query_id="t-rehearse"))

    def test_rehearse_returns_without_the_bridge(self):
        out = self._call({"rehearse": True, "program": _wall(top=False)})
        self.assertTrue(out.get("wrote_nothing"))
        self.assertIn("rehearsal", out)
        self.assertIn("пропущено top_level", out["rehearsal_note_ru"])

    def test_created_returns_without_the_bridge(self):
        out = self._call({"created": True})
        self.assertTrue(out.get("wrote_nothing"))
        self.assertIn("created_ledger", out)
        self.assertIn("НЕ равно «принято»", out["created_ledger_note_ru"])


class SessionSurvivesTheProcess(unittest.TestCase):
    """E2.1 — the session is restored from disk, and the unknown is marked."""

    def _store(self, stages: list[str]) -> pathlib.Path:
        """A store made of real rows, not a stub.

        🔴 HERE STOOD `"schema": "x"`, AND THAT STOPPED WORKING ON 31.08.2026 —
        rightly so. The store's reader started refusing on an unknown schema LOUDLY
        (`refused=store_unreadable`, `строк неизвестной схемы N`) instead of
        silently losing someone else's rows. The stub passed precisely
        because nobody ever asked about the schema; five tests of this class were turning red for the wrong
        reason.

        The name is taken FROM THE MODULE, not as a literal: bumping the store's version must not
        silently break the fixture again. The tightening itself is guarded separately —
        `test_a_foreign_schema_refuses_LOUDLY_instead_of_restoring_zero`.
        """
        path = pathlib.Path(tempfile.mkdtemp()) / "kir_programs.jsonl"
        rows = []
        for i, stage in enumerate(stages, start=1):
            rows.append({"schema": journal_store.SCHEMA, "event": "program",
                         "ts": "t",
                         "device_id": "dev", "doc_key": "doc", "seq": i,
                         "stage": "planned",
                         "ops": [{"op": "create_wall", "id": f"w{i}"}]})
            rows.append({"schema": journal_store.SCHEMA, "event": "stage",
                         "device_id": "dev",
                         "doc_key": "doc", "seq": i, "stage": stage})
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                        encoding="utf-8")
        return path

    def setUp(self):
        self.key = journal.key_for("dev", "doc")
        journal.reset(self.key)

    def tearDown(self):
        journal.reset(self.key)

    def test_a_foreign_schema_refuses_LOUDLY_instead_of_restoring_zero(self):
        """The 31.08 tightening must have its own guard, otherwise it is accidental.

        "Loaded 0" without a reason is exactly that same indistinguishable zero: a store with
        foreign rows would look like an empty store. We check that the refusal is
        NAMED and carries a reason, rather than just a zero.
        """
        path = pathlib.Path(tempfile.mkdtemp()) / "kir_programs.jsonl"
        path.write_text(json.dumps(
            {"schema": "kir-journal-store/999", "event": "program", "ts": "t",
             "device_id": "dev", "doc_key": "doc", "seq": 1,
             "stage": "planned",
             "ops": [{"op": "create_wall", "id": "w1"}]}) + "\n",
            encoding="utf-8")
        census = journal.restore(self.key, path=path)
        self.assertEqual(census["restored"], 0)
        self.assertEqual(census.get("refused"), "store_unreadable",
                         "чужая схема обязана отказывать НАЗВАННО, а не "
                         "возвращать ноль, неотличимый от пустого склада")
        self.assertIn("схем", census.get("detail", ""),
                      "причина отказа обязана называть СХЕМУ, иначе читателю "
                      "нечего чинить")

    def test_accepted_comes_back_as_built(self):
        census = journal.restore(self.key, path=self._store(["accepted"]))
        self.assertEqual(census["restored"], 1)
        self.assertEqual([r.seq for r in journal.get(self.key).built()], [1])

    def test_dispatched_comes_back_as_UNKNOWN_never_as_built(self):
        """🔴 The main distinction of this file.

        `dispatched` in a live session means "in flight right now". After the process
        crashes, nothing is left in flight: Revit's answer is lost forever.
        Restoring the record as `dispatched` would mean offering the reader to wait for
        an answer that will never come.
        """
        census = journal.restore(self.key, path=self._store(["dispatched"]))
        self.assertEqual(census["outcome_unknown"], 1)
        self.assertEqual(census["reclassified"], 1)
        rec = journal.get(self.key).records[0]
        self.assertEqual(rec.stage, "running_unknown")
        self.assertFalse(rec.is_built, "неизвестный исход НЕ построен")
        self.assertEqual(journal.get(self.key).built(), [])

    def test_a_restored_record_says_it_came_from_disk(self):
        journal.restore(self.key, path=self._store(["accepted"]))
        self.assertTrue(journal.get(self.key).records[0].restored_from_disk)

    def test_a_live_session_is_never_overwritten(self):
        """Restoring on top of what was already lived through would double the building."""
        path = self._store(["accepted"])
        journal.restore(self.key, path=path)
        again = journal.restore(self.key, path=path)
        self.assertEqual(again["restored"], 0)
        self.assertEqual(again["refused"], "live_session_present")
        self.assertEqual(again["live_records"], 1)

    def test_could_not_look_is_not_nothing_there(self):
        """Law §18.2: a store's refusal must arrive with a reason, not with emptiness."""
        out = journal.restore(journal.key_for("nobody", "nowhere"),
                              path=pathlib.Path("/nonexistent/j.jsonl"))
        self.assertEqual(out["restored"], 0)
        self.assertEqual(out["refused"], "store_unreadable")
        self.assertTrue(out["detail"], "причина обязана быть названа")

    def test_the_census_names_the_file_it_actually_read(self):
        path = self._store(["accepted"])
        self.assertEqual(journal.restore(self.key, path=path)["path"], str(path))

    def test_mutation_no_stage_remap_means_a_lie(self):
        """Remove the stage map — and `dispatched` will come back as "in flight"."""
        original = dict(journal._RESTORE_STAGE_MAP)
        try:
            journal._RESTORE_STAGE_MAP.clear()
            journal.reset(self.key)
            journal.restore(self.key, path=self._store(["dispatched"]))
            self.assertEqual(journal.get(self.key).records[0].stage,
                             "dispatched",
                             "без карты ложь воспроизводится — тест её видит")
        finally:
            journal._RESTORE_STAGE_MAP.clear()
            journal._RESTORE_STAGE_MAP.update(original)


class TheCreatedLedgerIsReadable(unittest.TestCase):
    """E2.2 — the created-items journal is handed to a reader, and the scope is strict."""

    def _ledger(self, rows: list[dict]) -> pathlib.Path:
        path = pathlib.Path(tempfile.mkdtemp()) / "kir_created_ids.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                        encoding="utf-8")
        return path

    def test_only_my_device_comes_back(self):
        path = self._ledger([
            {"schema_version": cl.SCHEMA_VERSION, "ts": "t", "device_id": "mine",
             "doc_key": "d", "created": {"w1": ["101"]}, "created_count": 1},
            {"schema_version": cl.SCHEMA_VERSION, "ts": "t", "device_id": "other",
             "doc_key": "d", "created": {"w9": ["999"]}, "created_count": 1},
        ])
        got = cl.created_for_session("mine", path=path)
        self.assertEqual(got["created_count"], 1)
        self.assertEqual(len(got["rows"]), 1)
        self.assertNotIn("999", json.dumps(got["rows"]),
                         "чужая модель не имеет права приехать")

    def test_rows_without_a_device_are_counted_not_guessed(self):
        """A row with no binding was written before it was ever registered. Attributing it to someone
        would mean inventing ownership — and, on the fleet, handing out someone else's model."""
        path = self._ledger([
            {"schema_version": cl.SCHEMA_VERSION, "ts": "t",
             "created": {"w1": ["101"]}, "created_count": 1},
        ])
        got = cl.created_for_session("mine", path=path)
        self.assertEqual(got["rows"], ())
        self.assertEqual(got["unattributable"], 1,
                         "«их нет» и «есть, но не наши» обязаны различаться")

    def test_no_device_refuses_instead_of_answering_empty(self):
        got = cl.created_for_session("")
        self.assertTrue(got["refusal"])
        self.assertEqual(got["created_count"], 0)

    def test_in_the_ledger_is_never_read_as_accepted(self):
        """🔴 The write happens BEFORE acceptance — it is precisely this that declares failure in
        `KIR-A006`/`KIR-A007` even when the write DID take place."""
        path = self._ledger([
            {"schema_version": cl.SCHEMA_VERSION, "ts": "t", "device_id": "mine",
             "created": {"w1": ["101"]}, "created_count": 1}])
        self.assertTrue(cl.created_for_session("mine", path=path)["verdict_unknown"])

    def test_mutation_dropping_the_device_filter_leaks_the_fleet(self):
        """Remove the scope — and someone else's model arrives in the response."""
        rows = [
            {"schema_version": cl.SCHEMA_VERSION, "ts": "t", "device_id": "mine",
             "created": {"w1": ["101"]}, "created_count": 1},
            {"schema_version": cl.SCHEMA_VERSION, "ts": "t", "device_id": "other",
             "created": {"w9": ["999"]}, "created_count": 1},
        ]
        path = self._ledger(rows)
        scoped = cl.created_for_session("mine", path=path)
        unscoped, _ = cl.read_created(path)
        self.assertEqual(len(unscoped), 2, "в файле обе строки")
        self.assertEqual(len(scoped["rows"]), 1, "а в ответе — только своя")


if __name__ == "__main__":
    unittest.main()
