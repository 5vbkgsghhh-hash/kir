"""The trace of what was created must survive a turn's failure — and must
NOT invent traces.

THE BAR (formulated by the director): a run killed midway leaves on disk a
complete list of ids for everything that managed to get created.

FAIL CONTROL. The proposed approach — cutting the bridge mid-batch —
measures the ENVIRONMENT and requires the operator's live Revit, and the
cut is not reproducible. Here the control is different and tells apart the
same thing:

    PASS    the `committed` outcome with `ok: false` — the line contains
            EXACTLY what was created; this is the very case that lost two
            elements
    FAIL-1  a rollback — the line exists, the list is EMPTY; "no line" and
            "empty list" must be told apart, or the registry's silence is
            indistinguishable from the truth
    FAIL-2  if the PROGRAM is read instead of the PAYLOAD, FAIL-1 must go
            red; the test plants this mutation itself and requires redness

The third one is the real guard: the list of declared ops on a rollback
looks like a list of what was created, and that is exactly how the
registry would turn into a generator of false traces — our named defect
class in a new place.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from kir import created_ledger, witness_feed


class TheLedgerReadsThePayloadAndNotTheProgram(unittest.TestCase):

    #: The bridge's response as it arrives on `KIR-A006`/`KIR-A007`: the
    #: elements were created, `ok` is false. The shape is taken from a live
    #: response on 13.08, not invented.
    COMMITTED = {"result": {"MS1": {"id": "12511351"},
                            "FR1": {"id": "12511358"},
                            "ok": True}}
    #: A rollback: the op lines exist, the numbers do not.
    ROLLED_BACK = {"result": {"SR1": {"refused": True}, "ok": False}}

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self._prev = os.environ.get(created_ledger.LEDGER_DIR_ENV)
        os.environ[created_ledger.LEDGER_DIR_ENV] = self._dir.name

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop(created_ledger.LEDGER_DIR_ENV, None)
        else:
            os.environ[created_ledger.LEDGER_DIR_ENV] = self._prev
        self._dir.cleanup()

    def _rows(self) -> list[dict]:
        p = pathlib.Path(self._dir.name) / "kir_created_ids.jsonl"
        if not p.exists():
            return []
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
                if x.strip()]

    # ------------------------------------------------------------------ PASS
    def test_committed_with_ok_false_still_records_every_id(self) -> None:
        """EXACTLY that case: the record happened, the turn declared failure."""
        created_ledger.record_created(self.COMMITTED, query_id="q1")
        rows = self._rows()
        self.assertEqual(len(rows), 1, "строка обязана быть ровно одна")
        self.assertEqual(rows[0]["created"],
                         {"MS1": ["12511351"], "FR1": ["12511358"]})
        self.assertEqual(rows[0]["created_count"], 2)

    def test_the_ledger_never_consults_ok(self) -> None:
        """`ok` in the result line plays no part in the decision.

        The same payload with `ok: False` must produce the SAME record —
        otherwise the registry would inherit exactly the signal that made
        ids get lost in the first place.
        """
        payload = json.loads(json.dumps(self.COMMITTED))
        payload["result"]["ok"] = False
        created_ledger.record_created(payload, query_id="q2")
        self.assertEqual(self._rows()[0]["created"],
                         {"MS1": ["12511351"], "FR1": ["12511358"]})

    # ---------------------------------------------------------------- FAIL-1
    def test_a_rollback_leaves_a_row_with_an_empty_list(self) -> None:
        """Neither more nor less: the line exists, nothing was created.

        "No line" would mean "the registry wasn't working," and telling
        the two apart afterward would be impossible.
        """
        created_ledger.record_created(self.ROLLED_BACK, query_id="q3")
        rows = self._rows()
        self.assertEqual(len(rows), 1, "откат обязан оставить строку")
        self.assertEqual(rows[0]["created"], {})
        self.assertEqual(rows[0]["created_count"], 0)

    def test_deleted_is_not_created(self) -> None:
        """`deleted_id` is not a trace: what was deleted no longer exists
        in the model."""
        created_ledger.record_created(
            {"result": {"D1": {"deleted_id": "12511351"}, "ok": True}},
            query_id="q4")
        self.assertEqual(self._rows()[0]["created"], {})

    # ---------------------------------------------------------------- FAIL-2
    def test_reading_the_program_instead_of_the_payload_reddens_the_rollback(
            self) -> None:
        """THE MUTATION THIS FILE MUST CATCH.

        We swap the extraction for "take the declared ops." On success
        there is almost no difference — and that is what makes the swap
        dangerous. What tells it apart is exactly a rollback: the declared
        set is non-empty, nothing was created.

        The control checks that the previous test FAILS under the
        mutation, not that the mutation merely "changes something": a wide
        red is the mark of a blunt probe.
        """
        real = created_ledger.extract_created

        def _reads_the_program(payload, **_kw):
            # The defect in its pure form: op names instead of element
            # numbers. `**_kw` is there so the swap accepts `op_kinds`
            # (F-297) and the mutation stays a mutation of EXTRACTION,
            # rather than failing on the signature: a TypeError red would
            # prove the wrong thing.
            if not isinstance(payload, dict):
                return {}
            return {str(k): [str(k)] for k in payload if k != "ok"}

        created_ledger.extract_created = _reads_the_program
        try:
            created_ledger.record_created(self.ROLLED_BACK, query_id="mut")
            mutated = self._rows()[0]["created"]
        finally:
            created_ledger.extract_created = real

        self.assertNotEqual(
            mutated, {},
            "мутация обязана дать ложный след — иначе контроль не различает")
        self.assertEqual(
            sorted(mutated), ["SR1"],
            "мутация обязана назвать ИМЕНА опов, а не номера элементов")

    # ------------------------------------------------------------ disabling
    def test_an_explicitly_empty_variable_disables_the_ledger(self) -> None:
        """Switching it off must be possible ON PURPOSE, not by the
        directory's absence."""
        os.environ[created_ledger.LEDGER_DIR_ENV] = ""
        self.assertIsNone(created_ledger.record_created(self.COMMITTED))
        self.assertEqual(self._rows(), [])

    def test_a_failure_to_write_never_raises(self) -> None:
        """A successful write to Revit does not become a failure because of
        the registry."""
        os.environ[created_ledger.LEDGER_DIR_ENV] = "/proc/нет-такого/пути"
        row = created_ledger.record_created(self.COMMITTED, query_id="q5")
        self.assertIsNotNone(row, "строка обязана вернуться даже при отказе")
        self.assertEqual(row["created_count"], 2)


class ЧастичныйИсходНеВыдаётсяЗаПолный(unittest.TestCase):
    """🔴 TWO ENDS OF ONE CLASS (F-298 + F-300, 30.08.2026).

    READING: `read_created` DELIBERATELY returns valid lines TOGETHER with
    a non-empty refusal when it skipped broken ones — "a file corrupted at
    one record has no right to hide the rest." The reader's single door
    canceled that intent: ANY non-empty refusal zeroed out the response,
    and one corrupted byte at the end of the file hid the entire journal
    (measured on the module: 471 elements in a day).

    WRITING: `os.write` is allowed to write LESS than requested and return
    the count — a legitimate outcome, no exception is ever raised for it.
    The return value was discarded, so a truncated line passed as written:
    `record_created` returned an ordinary line, no error file appeared, the
    log stayed silent, and the next reader treated the record as broken. A
    module written against losing the trace lost the trace and reported
    success.
    """

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self._env = mock.patch.dict(
            os.environ, {created_ledger.LEDGER_DIR_ENV: self.dir})
        self._env.start()
        self.addCleanup(self._env.stop)

    def _пишем(self, oid, eid):
        return created_ledger.record_created(
            {"result": {oid: {"id": eid}}}, query_id="q", turn_id="t",
            action_id="a", revit_version="2026", family="authoring",
            device_id="DEV-1", doc_key="Д", plan_digest="")

    # ---------------------------------------------------------------- F-298
    def test_one_broken_line_does_not_hide_the_whole_journal(self):
        self._пишем("W1", "1001")
        self._пишем("W2", "1002")
        путь = created_ledger.ledger_path()
        with open(путь, "a", encoding="utf-8") as fh:
            fh.write('{"битая строка\n')
        got = created_ledger.created_for_session("DEV-1", "Д", path=путь)
        self.assertEqual(len(got["rows"]), 2,
                         "одна битая строка спрятала годные")
        self.assertEqual(got["created_count"], 2)
        self.assertTrue(got["refusal"],
                        "предупреждение обязано доехать ВМЕСТЕ со строками")

    def test_a_real_refusal_still_empties_the_answer(self):
        """A NARROWNESS CONTROL. A genuine refusal (there ARE NO lines)
        must still zero out the response — otherwise we would trade one
        lie for another."""
        got = created_ledger.created_for_session(
            "DEV-1", "Д", path=pathlib.Path(self.dir) / "нет-такого.jsonl")
        self.assertEqual(got["rows"], ())
        self.assertTrue(got["refusal"])

    def test_the_two_kinds_are_told_apart_by_structure_not_by_text(self):
        """The distinction is taken from STRUCTURE (whether the tuple is
        empty), not from parsing the refusal's text: a substring is
        exactly a label standing in for the subject."""
        self._пишем("W1", "1001")
        путь = created_ledger.ledger_path()
        with open(путь, "a", encoding="utf-8") as fh:
            fh.write('{"битая\n')
        частично = created_ledger.created_for_session("DEV-1", "Д", path=путь)
        отказ = created_ledger.created_for_session(
            "DEV-1", "Д", path=pathlib.Path(self.dir) / "нет.jsonl")
        self.assertTrue(частично["rows"] and частично["refusal"])
        self.assertTrue(not отказ["rows"] and отказ["refusal"])

    # ---------------------------------------------------------------- F-300
    def test_a_short_write_does_not_leave_a_torn_line(self):
        """`os.write` returns half and does NOT raise — a legitimate outcome."""
        настоящий = os.write

        def половина(fd, data):
            return (настоящий(fd, data[:max(1, len(data) // 2)])
                    if len(data) > 40 else настоящий(fd, data))

        with mock.patch.object(os, "write", половина):
            self._пишем("W1", "1001")
        rows, refusal = created_ledger.read_created(
            created_ledger.ledger_path())
        self.assertEqual(len(rows), 1, "короткая запись порвала строку")
        self.assertEqual(refusal, "")

    def test_a_write_that_stalls_is_named_not_swallowed(self):
        """But if the write GOT STUCK (returned 0) — that is already a
        failure, and it must be NAMED: a silent corruption turns into a
        named one."""
        настоящий = os.write
        счёт = {"n": 0}

        def застряла(fd, data):
            счёт["n"] += 1
            if len(data) > 40 and счёт["n"] == 1:
                return настоящий(fd, data[:20])
            if len(data) > 20:
                return 0
            return настоящий(fd, data)

        with self.assertLogs("kir.created_ledger", level="ERROR") as поймано:
            with mock.patch.object(os, "write", застряла):
                строка = self._пишем("W1", "1001")
        self.assertIsNotNone(строка,
                             "отказ реестра не имеет права отменить запись")
        текст = "\n".join(поймано.output)
        self.assertIn("короткая запись в реестр", текст)
        self.assertIn("из", текст, "в отказе нет чисел: сколько ушло из скольких")


class ДверьСозданногоЗАКРЫТАВОРОТАМИ(unittest.TestCase):
    """🔴 THE "WHAT DID I CREATE" MODE RETURNED DATA WITH THE GATE CLOSED (F-013).

    The door's body (`_handle_revit_ir_inner`) NEVER REACHES this mode — it
    returns earlier, same as `example`. The tree caught exactly this defect
    on 17.08 and closed it for the sample, naming the cause outright:
    "'won't reach the door' is a claim about the CALLERS, not about the
    door." The `created` mode was set up later and repeated the hole word
    for word.

    A coverage measurement on the live registry (1990 lines, 44 086
    elements): up to 200 lines / 165 elements belonging to the CALLER'S OWN
    device were being returned.
    """

    class _Ход:
        def __init__(self, режим): self.режим = режим
        def get_active_device_id(self): return "DEV-1"
        def turn_document_title(self): return ""
        def kir_mode_active(self): return self.режим

    def _вызов(self, режим, args):
        """🔴 THE GATE HAS THREE CONDITIONS, AND THE RIG MUST SET ALL THREE.
        `revit_ir_enabled()` asks for the `KIR_TOOL=stage2` flag, the KIR
        mode marker on the turn, AND the device's clearance. The first
        edition of this rig set only one of the three conditions, and its
        "open gate" was actually closed — meaning the narrowness control
        checked nothing. Caught by a run."""
        import asyncio
        from unittest import mock
        from kir import ports, serving
        ports.register(ports.TURN_CONTEXT, lambda: self._Ход(режим))
        self.addCleanup(ports.unregister, ports.TURN_CONTEXT)
        среда = {"KUKAI_KIR_TOOL": "stage2" if режим else "off",
                 "KUKAI_ADMIN_DEVICES": "DEV-1" if режим else ""}
        with mock.patch.dict(os.environ, среда):
            return asyncio.run(serving.handle_revit_ir(args, None, None,
                                                       query_id="q"))

    def test_created_is_refused_by_the_gate_like_example(self):
        for args in ({"created": True}, {"example": "жилая башня"}):
            with self.subTest(режим=next(iter(args))):
                ответ = self._вызов(False, args)
                self.assertEqual(ответ.get("error"), "gate")
                self.assertFalse(ответ.get("ok"))

    def test_no_ledger_rows_escape_a_closed_gate(self):
        """The subject is NOT the refusal code but the DATA: registry lines
        have no right to leak out with the gate closed.

        🔴 A LINE IS PUT INTO THE REGISTRY FIRST, AND THAT IS NOT CEREMONY.
        The first edition checked emptiness against an EMPTY registry —
        meaning it was green by construction and did not go red under the
        "remove the gate" mutation. Nothing to carry out means nothing to
        prove.
        """
        import tempfile
        from unittest import mock
        каталог = tempfile.mkdtemp()
        with mock.patch.dict(os.environ,
                             {created_ledger.LEDGER_DIR_ENV: каталог}):
            строка = created_ledger.record_created(
                {"result": {"W1": {"id": "1001"}}}, query_id="q", turn_id="t",
                action_id="a", revit_version="2026", family="authoring",
                device_id="DEV-1", doc_key="", plan_digest="")
            self.assertIsNotNone(строка, "стенд не записал строку — проверять нечего")
            # A rig control: with the gate OPEN the line IS VISIBLE.
            открыто = self._вызов(True, {"created": True})
            self.assertEqual(
                len((открыто.get("created_ledger") or {}).get("rows", ())), 1,
                "стенд не показывает строку даже при открытых воротах — "
                "проверка ниже была бы пуста")
            закрыто = self._вызов(False, {"created": True})
        self.assertEqual(
            len((закрыто.get("created_ledger") or {}).get("rows", ())), 0)

    def test_the_gate_is_the_only_thing_that_changed(self):
        """A NARROWNESS CONTROL: with the gate OPEN the mode must work as
        before — otherwise we would trade the hole for a refusal on a
        legitimate input."""
        ответ = self._вызов(True, {"created": True})
        self.assertNotEqual(ответ.get("error"), "gate")
        self.assertIn("created_ledger", ответ)


class ЖивойПисательПередаётВсё(unittest.TestCase):
    """🔴 THE SUBJECT IS THE CALL SITES, NOT THE FUNCTION'S CAPABILITY.

    Twice in one shift the registry was able to do something the live
    writer never gave it: `doc_key` (F-299, two programs of DIFFERENT
    buildings landed in one response) and `op_kinds` (F-297, operations on
    an existing element got recorded as belonging to the turn). Both times
    the function was not at fault — the ARGUMENT never made it through.

    Checking that "`record_created(op_kinds=...)` works" is useless: it is
    green even without the fix. What must be checked is that the door
    PASSES IT THROUGH, and a live path can't be run without Revit — so the
    calls themselves become the subject.
    """

    #: The arguments without which a registry line lies to the reader.
    #: The list is closed and every entry was paid for by a finding.
    ОБЯЗАТЕЛЬНЫЕ = ("device_id", "doc_key", "op_kinds")

    def _вызовы(self):
        import ast as _ast
        import pathlib as _pathlib
        import kir as _kir
        корень = _pathlib.Path(_kir.__file__).resolve().parent
        найдено = []
        for путь in sorted(корень.rglob("*.py")):
            if "tests" in путь.parts or путь.name.startswith("test_"):
                continue
            try:
                дерево = _ast.parse(путь.read_text(encoding="utf-8"))
            except (SyntaxError, OSError):
                continue
            for узел in _ast.walk(дерево):
                if not isinstance(узел, _ast.Call):
                    continue
                f = узел.func
                имя = (f.attr if isinstance(f, _ast.Attribute)
                       else getattr(f, "id", None))
                if имя == "record_created":
                    найдено.append((
                        путь.relative_to(корень.parent).as_posix(),
                        узел.lineno,
                        {k.arg for k in узел.keywords if k.arg}))
        return найдено

    def test_the_probe_finds_the_live_writer_at_all(self):
        """A degeneracy control: an empty sample is green by construction,
        and then all the checks below mean nothing."""
        self.assertTrue(self._вызовы(),
                        "проба не нашла НИ ОДНОГО живого вызова "
                        "record_created — она сломана")

    def test_every_live_writer_passes_the_binding_arguments(self):
        for файл, строка, ключи in self._вызовы():
            for арг in self.ОБЯЗАТЕЛЬНЫЕ:
                with self.subTest(где=f"{файл}:{строка}", аргумент=арг):
                    self.assertIn(
                        арг, ключи,
                        f"{файл}:{строка} не передаёт {арг!r} — строка реестра "
                        f"будет описывать не то, что произошло")


class TheTwoPlacesThatDecideCreatedAgree(unittest.TestCase):
    """The registry and the witness decide "was it created" using the SAME
    keys.

    Should they diverge, two places would start answering one question
    differently, and that is exactly our defect class: a value is named in
    one place, read in another, and nothing forces them to agree. Both
    places now ask ONE authority — the op registry — so both completeness
    and agreement get pinned.
    """

    def test_witness_and_ledger_use_the_same_created_keys(self) -> None:
        """Both places decide "was it created" using ONE authority — the
        registry.

        🔴 THE PREVIOUS EDITION OF THIS TEST COULD NOT GO RED (captured
        15.08.2026). It checked `'"id"' in inspect.getsource(witness_feed)`
        — the string `"id"` is bound to appear in a seven-hundred-line
        module — and then iterated over a ONE-element tuple, checking `"id"
        in CREATED_KEYS`, which is a constant. The test stood green exactly
        when the two places diverged on `segment_ids`: the registry lost
        four creating ops, while the witness tagged them `other`. A guard
        that cannot say "no" is worse than none at all: it creates
        confidence and gives no protection.

        Here BEHAVIOR is checked on the result line, not the presence of a
        substring in the source.

        🔴 AND THE SECOND EDITION WAS ALSO A VACUUM — caught by mutation,
        not by reasoning. It iterated over `created_identity_fields()`,
        that is, IT ASKED THE VERY VALUE IT WAS CHECKING: swap that
        function for the old hand-written tuple, and the test stays green,
        because it honestly compares the swapped against the swapped. A
        test's authority must be INDEPENDENT of its subject, so the
        expectation is taken from `spec.OPS` directly.
        """

        from kir.registry_base import EffectKind
        from kir import spec

        expected = {op.result.identity_field for op in spec.OPS.values()
                    if op.effect is EffectKind.CREATE and op.result.identity_field}
        self.assertTrue(expected, "реестр не дал ни одного созидающего поля")
        self.assertEqual(
            set(created_ledger.created_keys()), expected,
            "ключи реестра следов разошлись с реестром ОПЕРАЦИЙ")

        for field in sorted(expected):
            value = 4242 if field == "id" else [4242]
            self.assertTrue(
                created_ledger.extract_created({"o1": {field: value}}),
                f"реестр следов не считает {field!r} созданным, а реестр опов — да")
            self.assertEqual(
                witness_feed.outcome_label({field: value}), "created",
                f"свидетель не считает {field!r} созданным, а реестр опов — да")

    def test_the_two_places_DIVERGE_once_the_ledger_knows_the_op_kind(self):
        """🔴 THE DISCREPANCY WAS ENTERED EXPLICITLY, NOT DISCOVERED BY A
        FAILURE (F-297).

        The trace registry learned to ask for the operation's KIND
        (`op_kinds`), while the witness did not: `outcome_label` tags ONE
        line with no context of the turn, and there is no way to give it a
        kind without separate work. So on operations ON AN EXISTING element
        (`set_param`, `change_type`) the two places answer differently, and
        this is a KNOWN, named discrepancy, not a new instance of our
        defect class.

        This test exists so that the discrepancy is RECORDED and measured:
        if the witness learns the kind tomorrow, this test will go red and
        will need to be removed — along with this paragraph.
        """
        from kir.registry_base import EffectKind
        from kir import spec

        мутирующие = sorted(
            name for name, op in spec.OPS.items()
            if op.effect is not EffectKind.CREATE
            and op.result.identity_field in set(created_ledger.created_keys()))
        self.assertTrue(
            мутирующие,
            "не осталось ни одного НЕсозидающего опа с созидающим полем — "
            "предмет расхождения исчез, тест надо снять")

        имя = мутирующие[0]
        поле = spec.OPS[имя].result.identity_field
        строка = {"o1": {поле: 4242}}

        # The registry WITHOUT the map — as before: counts it as created.
        self.assertTrue(created_ledger.extract_created(строка))
        # The registry WITH the map — knows the kind and stays silent.
        self.assertEqual(
            created_ledger.extract_created(строка, op_kinds={"o1": имя}), {})
        # The witness does not know the kind and still tags it created.
        self.assertEqual(witness_feed.outcome_label({поле: 4242}), "created")

    def test_the_agreement_check_can_actually_fail(self) -> None:
        """A FAIL control for the check, and it is verified by MUTATION,
        not by hope.

        A field the registry doesn't know about is not "created" — that's
        one. And two: putting back the hand-written tuple, as it was
        before 15.08, must make the check GO RED. Without the second half,
        the first only proves that garbage doesn't get through.
        """

        self.assertFalse(created_ledger.extract_created({"o1": {"нет_такого": 7}}))
        self.assertEqual(witness_feed.outcome_label({"нет_такого": 7}), "other")

        from kir import address
        real = address.created_identity_fields
        address.created_identity_fields = lambda: ("id", "ids", "created_ids")
        try:
            with self.assertRaises(AssertionError):
                self.test_witness_and_ledger_use_the_same_created_keys()
        finally:
            address.created_identity_fields = real

    def test_moved_is_not_created_and_that_is_a_decision(self) -> None:
        """`moved_ids` is excluded BY NAME, not silently dropped from the
        tuple."""

        self.assertIn("moved_ids", created_ledger.not_created_keys())
        self.assertNotIn("moved_ids", created_ledger.created_keys())
        self.assertFalse(created_ledger.extract_created({"m1": {"moved_ids": [1]}}))
        self.assertEqual(witness_feed.outcome_label({"moved_ids": [1]}), "other")

    def test_the_ledger_is_wired_into_the_write_path(self) -> None:
        """A module that arrives unwired is our most prevalent defect.

        What gets pinned is the CALL in `serving`, not the file's
        existence: something built and called by nobody is
        indistinguishable from something absent.
        """
        import inspect

        from kir import serving
        src = inspect.getsource(serving._handle_revit_ir_inner)
        self.assertIn("created_ledger", src)
        self.assertIn("record_created", src)
        self.assertLess(
            src.index("record_created"), src.index("record_witness"),
            "след созданного обязан писаться РАНЬШЕ, чем работает приёмка")
