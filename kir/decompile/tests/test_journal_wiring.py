"""The `journal` wire: a decompile is a REVISION of the building, and a
rebuild reads it.

The `journal` layer had been sitting in storage for 471 lines and 22 tests,
and all 22 were checking WHAT it computes: the hash chain, rollback, audit,
refusal on a foreign delta. Not one was checking whether even a single live
input ever reaches it — which is why the storage was invisible from inside
the tests. This file checks exactly the second thing, and only that.

Four laws, each one earned:

* **inertness** — with the flag off, a decompile must put THE SAME artifacts
  on disk, byte for byte. Neither `journal.json` nor an empty `_journals/`:
  an empty history is already a claim about the history, and a disabled
  capability has no right to claim anything;
* **the histories of two buildings NEVER mix** — the journal key carries a
  digest of the full `doc_name`, because the sanitizer would fuse "А Б" and
  "А_Б" into one file, and the merged histories of two buildings would read
  as one building rebuilt twice, in full;
* **a hole in the log is a refusal, not a skip** — the head revision's tree
  is gone, the journal does not parse, the delta does not apply: all of
  these are `ok:false`, and not one case starts the journal over. A journal
  that once had an untruth land in it is WORSE than a missing one: it looks
  exactly like an honest one;
* **the base from the journal is presented, not implied** — `@journal`
  resolves to a specific `base_doc_stamp`, and it travels in the response. A
  choice the asker cannot see is `.FirstOrDefault()` with good PR.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import pathlib
import tempfile
import unittest
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_journal_wiring_queue.jsonl"))

from kir import serving  # noqa: E402
from kir.decompile import pipeline as pipe  # noqa: E402
from kir.decompile.journal import journal_enabled  # noqa: E402
from kir.decompile.journal_store import (  # noqa: E402
    LOG_DIRNAME,
    building_key,
    history_report,
    load_log,
    log_path,
    record_revision,
)
from kir.decompile.tests.fixtures_decompile import (  # noqa: E402
    make_element,
)
from kir.decompile.tests.test_merkle import _fold, _grid_building  # noqa: E402
from kir.decompile.tests.test_pipeline import (  # noqa: E402
    FakePipelineBridge,
    _mini_elements,
    _mini_metadata,
)

_FLAG = "KUKAI_IR_JOURNAL"

#: Artifacts required to be deterministic (the same list as the merkle
#: sibling's: `run.json`/`status.json` carry stage timings, I4).
_DETERMINISTIC = (
    "L0.jsonl", "tree.json", "named.json", "verify.json", "passport.json",
    "curve.index.json", "sketch.index.json", "curtain.index.json",
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _digests(directory: pathlib.Path) -> dict[str, str]:
    out = {}
    for name in _DETERMINISTIC:
        path = directory / name
        if path.is_file():
            out[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class _ShimLLM:
    _revit_version = "2026"

    async def _repair_code(self, *a: Any, **k: Any) -> None:
        return None


async def _never_bridge(method: str, params: dict) -> dict:  # pragma: no cover
    raise AssertionError("мост не смеет вызываться в сухом прогоне")


# ───────────────────────────────────────────────────────────────────────────
# Storage laws: checked on trees, without the pipeline
# ───────────────────────────────────────────────────────────────────────────


class StoreLaws(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _persist(self, stamp: str, tree) -> pathlib.Path:
        directory = self.root / stamp
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tree.json").write_text(
            json.dumps(tree), encoding="utf-8")
        return directory

    def _record(self, stamp: str, tree, *, doc_name: str = "дом") -> dict:
        directory = self._persist(stamp, tree)
        return record_revision(
            self.root, doc_name=doc_name, doc_stamp=stamp,
            out_dir=str(directory), tree=tree, revit_version="2026")

    def test_first_run_opens_the_log_with_a_base_revision(self) -> None:
        report = self._record("v1", _fold(_grid_building(floors=2)))
        self.assertTrue(report["ok"], msg=report)
        self.assertTrue(report["appended"])
        self.assertEqual(report["revision"], 0)
        self.assertEqual(report["kind"], "base")
        self.assertIsNone(report["previous_doc_stamp"],
                          "у первой ревизии не может быть предыдущей")
        self.assertTrue(log_path(self.root, "дом").is_file())

    def test_second_run_appends_a_delta_and_names_its_predecessor(
            self) -> None:
        """Exactly what the system did not have: a link between two readings
        of the same building."""

        self._record("v1", _fold(_grid_building(floors=3)))
        report = self._record(
            "v2", _fold(_grid_building(floors=3, extra_furniture_on_floor=1)))
        self.assertTrue(report["ok"], msg=report)
        self.assertTrue(report["appended"])
        self.assertEqual(report["revision"], 1)
        self.assertEqual(report["kind"], "delta")
        self.assertEqual(report["previous_doc_stamp"], "v1")
        self.assertGreater(report["delta"]["touched"], 0,
                           "здание правили, а дельта пустая — журнал пишет "
                           "не то, что произошло")
        self.assertGreater(report["delta"]["reused"],
                           report["delta"]["touched"])

    def test_history_replays_every_revision_it_recorded(self) -> None:
        """The meaning of the log: the state at revision N is recovered FROM
        THE LOG."""

        from kir.decompile.journal_store import journal_of
        from kir.decompile.rebuild import BuildingState

        trees = [
            _fold(_grid_building(floors=3)),
            _fold(_grid_building(floors=3, extra_furniture_on_floor=1)),
            _fold(_grid_building(floors=3, extra_furniture_on_floor=1,
                                 stretch_wall_on_floor=2)),
        ]
        for index, tree in enumerate(trees):
            self.assertTrue(self._record(f"v{index}", tree)["ok"])

        log = load_log(log_path(self.root, "дом"))
        journal = journal_of(log)
        for index, tree in enumerate(trees):
            self.assertEqual(
                journal.state_at(index), BuildingState.of_tree(tree),
                f"ревизия {index} восстановлена не в то состояние — журнал "
                "описывает не это здание")
        report = history_report(log)
        self.assertTrue(report["ok"])
        self.assertEqual(report["revisions_total"], 3)
        self.assertEqual(report["revisions"][0].get("delta"), None,
                         "у базовой ревизии дельты нет по построению")
        self.assertIn("delta", report["revisions"][2])

    def test_re_reading_the_same_stamp_appends_nothing(self) -> None:
        tree = _fold(_grid_building(floors=2))
        self._record("v1", tree)
        again = self._record("v1", copy.deepcopy(tree))
        self.assertTrue(again["ok"], msg=again)
        self.assertFalse(again["appended"])
        self.assertEqual(again["reason"], "already_head")
        self.assertEqual(again["revisions_total"], 1,
                         "перечитанный тот же штамп раздул историю событием, "
                         "которого не было")

    def test_two_documents_never_share_one_log(self) -> None:
        tree = _fold(_grid_building(floors=2))
        self._record("a", tree, doc_name="дом-А")
        self._record("b", tree, doc_name="дом-Б")
        self.assertTrue(log_path(self.root, "дом-А").is_file())
        self.assertTrue(log_path(self.root, "дом-Б").is_file())
        self.assertEqual(
            len(list((self.root / LOG_DIRNAME).glob("*.json"))), 2)

    def test_names_that_sanitize_alike_get_different_logs(self) -> None:
        """Refuting test: without the digest this is ONE file for two
        buildings."""

        self.assertNotEqual(building_key("К 2"), building_key("К_2"))
        tree = _fold(_grid_building(floors=2))
        self._record("a", tree, doc_name="К 2")
        self._record("b", tree, doc_name="К_2")
        self.assertEqual(
            len(list((self.root / LOG_DIRNAME).glob("*.json"))), 2,
            "две истории легли в один файл — санитайзер склеил имена, и "
            "здания перестали различаться")

    def test_a_tampered_log_refuses_instead_of_starting_a_new_one(
            self) -> None:
        """The most expensive of the refusals: an overwrite would erase the
        evidence."""

        self._record("v1", _fold(_grid_building(floors=2)))
        path = log_path(self.root, "дом")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["journal"]["events"][0]["event_hash"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        before = path.read_bytes()

        report = self._record(
            "v2", _fold(_grid_building(floors=3)))
        self.assertFalse(report["ok"], msg=report)
        self.assertEqual(report["reason"], "log_unreadable")
        self.assertFalse(report["appended"])
        self.assertEqual(path.read_bytes(), before,
                         "подделанный журнал переписан — свидетельство о "
                         "подделке уничтожено ровно тем, что его нашло")

    def test_a_missing_head_tree_is_a_refusal_not_a_silent_new_base(
            self) -> None:
        self._record("v1", _fold(_grid_building(floors=2)))
        (self.root / "v1" / "tree.json").unlink()
        path = log_path(self.root, "дом")
        before = path.read_bytes()

        report = self._record("v2", _fold(_grid_building(floors=3)))
        self.assertFalse(report["ok"], msg=report)
        self.assertEqual(report["reason"], "head_tree_missing")
        self.assertEqual(report["head_doc_stamp"], "v1")
        self.assertEqual(path.read_bytes(), before,
                         "лог тронут при отказе — дырка в append-only логе "
                         "должна быть видна, а не заглажена")

    def test_a_head_directory_overwritten_by_another_building_is_refused(
            self) -> None:
        """A stamp can be reused; the head's state cannot be swapped out.

        The `v1` directory has been overwritten by a FOREIGN building. A
        delta computed from it would be a delta from a base that was never
        in the history, and T-APPLY on the multiset would not notice this —
        `commit_trees` will.
        """

        self._record("v1", _fold(_grid_building(floors=2)))
        (self.root / "v1" / "tree.json").write_text(
            json.dumps(_fold(_grid_building(floors=5, id_base=90_000))),
            encoding="utf-8")

        report = self._record("v2", _fold(_grid_building(floors=3)))
        self.assertFalse(report["ok"], msg=report)
        self.assertEqual(report["reason"], "not_applicable_to_head")

    def test_a_refusal_is_not_an_empty_history(self) -> None:
        report = record_revision(
            self.root, doc_name="дом", doc_stamp="v1",
            out_dir=str(self.root / "v1"), tree={"kind": "building"})
        self.assertFalse(report["ok"])
        self.assertIn("error", report)
        self.assertFalse(report["appended"])


# ───────────────────────────────────────────────────────────────────────────
# Live decompile: `pipeline.run_decompile` ← `serving` ← `/admin/kir/decompile`
# ───────────────────────────────────────────────────────────────────────────


def _bridge(*, extra_wall: bool = False) -> FakePipelineBridge:
    elements = _mini_elements()
    if extra_wall:
        elements["OST_Walls"].append(
            make_element("OST_Walls", 1003, ordinal=2))
    return FakePipelineBridge(elements=elements, metadata=_mini_metadata())


def _decompile(out_dir: pathlib.Path, stamp: str, *,
               extra_wall: bool = False) -> Any:
    return _run(pipe.run_decompile(
        _bridge(extra_wall=extra_wall), out_dir=str(out_dir),
        change_stamp=stamp))


class InertWhenOff(unittest.TestCase):
    def test_flag_is_off_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FLAG, None)
            self.assertFalse(journal_enabled())

    def test_off_run_writes_no_journal_at_all(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FLAG, None)
            with TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                result = _decompile(root / "run1", "journal-off-v1")
                self.assertTrue(result.ok, msg=result.to_dict())
                self.assertFalse((root / "run1" / "journal.json").exists(),
                                 "выключенный флаг оставил квитанцию — "
                                 "отсутствующее обязано отсутствовать")
                self.assertFalse((root / LOG_DIRNAME).exists(),
                                 "выключенный флаг завёл каталог журналов")
                status = json.loads(
                    (root / "run1" / "status.json").read_text("utf-8"))
                self.assertNotIn(
                    "journal", status.get("timing", {}).get("stage_ms", {}),
                    "выключенная стадия попала в часы — значит исполнялась")

    def test_switching_the_flag_moves_no_byte_of_the_old_artifacts(
            self) -> None:
        with TemporaryDirectory() as tmp_off, TemporaryDirectory() as tmp_on:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(_FLAG, None)
                self.assertTrue(
                    _decompile(pathlib.Path(tmp_off) / "r", "j-v1").ok)
            with mock.patch.dict(os.environ, {_FLAG: "1"}):
                self.assertTrue(
                    _decompile(pathlib.Path(tmp_on) / "r", "j-v1").ok)
            off = _digests(pathlib.Path(tmp_off) / "r")
            on = _digests(pathlib.Path(tmp_on) / "r")
            self.assertTrue(off, "сравнивать нечего — прогон не дал артефактов")
            self.assertEqual(
                off, on,
                "включённый journal сдвинул байты уже существовавшего "
                "артефакта — это не приложение к разбору, а изменение разбора")
            self.assertTrue(
                (pathlib.Path(tmp_on) / "r" / "journal.json").is_file())


class LiveDecompileRecordsRevisions(unittest.TestCase):
    def test_two_runs_of_one_document_become_two_revisions(self) -> None:
        """The wave's main test: a live decompile keeps the building's
        history itself."""

        with mock.patch.dict(os.environ, {_FLAG: "1"}):
            with TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                self.assertTrue(_decompile(root / "v1", "journal-live-v1").ok)
                first = json.loads(
                    (root / "v1" / "journal.json").read_text("utf-8"))
                self.assertTrue(first["ok"], msg=first)
                self.assertEqual(first["revision"], 0)

                self.assertTrue(_decompile(
                    root / "v2", "journal-live-v2", extra_wall=True).ok)
                second = json.loads(
                    (root / "v2" / "journal.json").read_text("utf-8"))
                self.assertTrue(second["ok"], msg=second)
                self.assertEqual(second["revision"], 1)
                self.assertEqual(second["previous_doc_stamp"],
                                 "journal-live-v1")
                self.assertGreater(
                    second["delta"]["touched"], 0,
                    "стену добавили, а дельта пустая — журнал не видит правки")

                log = load_log(log_path(root, "pipeline-mini"))
                self.assertEqual(len(log["revisions"]), 2)
                self.assertTrue(history_report(log)["ok"])

    def test_the_receipt_of_a_refusal_is_written_too(self) -> None:
        """`ok:false` in the receipt is not the same thing as the absence of
        history."""

        with mock.patch.dict(os.environ, {_FLAG: "1"}):
            with TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                self.assertTrue(_decompile(root / "v1", "j-ref-v1").ok)
                (root / "v1" / "tree.json").unlink()
                result = _decompile(root / "v2", "j-ref-v2", extra_wall=True)
                self.assertTrue(result.ok,
                                "отказ журнала уронил разбор — приложение к "
                                "паспорту не имеет права ронять паспорт")
                receipt = json.loads(
                    (root / "v2" / "journal.json").read_text("utf-8"))
                self.assertFalse(receipt["ok"])
                self.assertEqual(receipt["reason"], "head_tree_missing")


# ───────────────────────────────────────────────────────────────────────────
# A live rebuild reads the journal: `@journal` ← `/admin/kir/rebuild`
# ───────────────────────────────────────────────────────────────────────────


class RebuildReadsTheJournal(unittest.TestCase):
    """`base_doc_stamp='@journal'` ← `handle_revit_rebuild` ← the route."""

    def setUp(self) -> None:
        # 🔴 BOTH GATE CONDITIONS ARE NOW OPENED (28.08.2026). Only the MODE
        # was being set here, while `serving.ADMIN_DEVICE` is not a constant:
        # it is derived from `KUKAI_ADMIN_DEVICES` at the moment of access and
        # equals `None` when the list is empty (the fallback was removed on
        # 15.08). The mock was handing back `None`, the gate was refusing, and
        # the refusal was blaming the MODE, which was in fact enabled.
        os.environ["KUKAI_ADMIN_DEVICES"] = "dev-набор"
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        os.environ.pop("KUKAI_IR_ATOM_ESCROW", None)
        self._dev = mock.patch.object(
            serving, "_turn_device_id", return_value="dev-набор")
        self._dev.start()
        self._tmp = TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._dev.stop()
        self._tmp.cleanup()
        for flag in (_FLAG, "KUKAI_IR_REBUILD", "KUKAI_KIR_DECOMPILE",
                     "KUKAI_ADMIN_DEVICES"):
            os.environ.pop(flag, None)

    def _persist(self, stamp: str, tree, *, doc_name: str = "дом") -> None:
        directory = self.root / stamp
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tree.json").write_text(
            json.dumps(tree), encoding="utf-8")
        (directory / "passport.json").write_text(
            json.dumps({"doc_name": doc_name}), encoding="utf-8")

    def _record(self, stamp: str, tree, *, doc_name: str = "дом") -> dict:
        self._persist(stamp, tree, doc_name=doc_name)
        return record_revision(
            self.root, doc_name=doc_name, doc_stamp=stamp,
            out_dir=str(self.root / stamp), tree=tree, revit_version="2026")

    def _out_dir(self, stamp: str) -> str:
        return str(self.root / stamp)

    def _rebuild(self, args: dict) -> dict:
        with mock.patch.object(serving, "_decompile_out_dir", self._out_dir):
            return _run(serving.handle_revit_rebuild(
                {"dry_run": True, **args}, _ShimLLM(), _never_bridge))

    def _two_revisions(self) -> None:
        self.assertTrue(self._record("v1", _fold(_grid_building(floors=3)))["ok"])
        self.assertTrue(self._record(
            "v2",
            _fold(_grid_building(floors=3, extra_furniture_on_floor=1))
        )["ok"])

    def test_the_resolved_base_is_named_in_the_answer(self) -> None:
        """The meaning of the wire: the operator does not remember the base —
        the journal remembers it."""

        self._two_revisions()
        with mock.patch.dict(
                os.environ, {_FLAG: "1", "KUKAI_IR_REBUILD": "1"}):
            result = self._rebuild(
                {"doc_stamp": "v2", "base_doc_stamp": "@journal"})
        self.assertTrue(result["ok"], msg=result)
        self.assertEqual(result["delta"]["base_doc_stamp"], "v1",
                         "разрешилось не в предыдущую ревизию")
        self.assertEqual(result["delta"]["base_source"], "journal",
                         "выбор сделан, но не предъявлен — по ответу нельзя "
                         "отличить журнальную базу от названной")
        self.assertLess(result["delta"]["delta_leaves"],
                        result["delta"]["full_leaves"])

    def test_the_journal_base_equals_the_named_one(self) -> None:
        """The `@journal` branch has no right to be weaker than an explicit
        base."""

        self._two_revisions()
        with mock.patch.dict(
                os.environ, {_FLAG: "1", "KUKAI_IR_REBUILD": "1"}):
            named = self._rebuild(
                {"doc_stamp": "v2", "base_doc_stamp": "v1"})
            resolved = self._rebuild(
                {"doc_stamp": "v2", "base_doc_stamp": "@journal"})
        self.assertEqual(named["chunks_total"], resolved["chunks_total"])
        self.assertEqual(named["delta"]["delta_leaves"],
                         resolved["delta"]["delta_leaves"])
        self.assertEqual(named["delta"]["base_source"], "named")

    def test_journal_base_with_the_journal_flag_off_is_refused_by_name(
            self) -> None:
        self._two_revisions()
        with mock.patch.dict(os.environ, {"KUKAI_IR_REBUILD": "1"},
                             clear=False):
            os.environ.pop(_FLAG, None)
            result = self._rebuild(
                {"doc_stamp": "v2", "base_doc_stamp": "@journal"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "journal_disabled")
        self.assertNotIn("chunks_total", result,
                         "отказ протащил за собой полную пересборку — просили "
                         "дельту, а построили бы здание целиком")

    def test_a_building_without_a_log_is_refused_not_rebuilt_whole(
            self) -> None:
        self._persist("v2", _fold(_grid_building(floors=3)))
        with mock.patch.dict(
                os.environ, {_FLAG: "1", "KUKAI_IR_REBUILD": "1"}):
            result = self._rebuild(
                {"doc_stamp": "v2", "base_doc_stamp": "@journal"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "journal_absent")
        self.assertNotIn("chunks_total", result)

    def test_the_first_revision_has_no_predecessor_and_says_so(self) -> None:
        self.assertTrue(self._record("v1", _fold(_grid_building(floors=3)))["ok"])
        with mock.patch.dict(
                os.environ, {_FLAG: "1", "KUKAI_IR_REBUILD": "1"}):
            result = self._rebuild(
                {"doc_stamp": "v1", "base_doc_stamp": "@journal"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "journal_no_previous")

    def test_a_run_outside_the_journal_is_refused(self) -> None:
        """The decompile was taken before the journal was enabled: "no
        record" ≠ "no differences"."""

        self._two_revisions()
        self._persist("v3", _fold(_grid_building(floors=4)))
        with mock.patch.dict(
                os.environ, {_FLAG: "1", "KUKAI_IR_REBUILD": "1"}):
            result = self._rebuild(
                {"doc_stamp": "v3", "base_doc_stamp": "@journal"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "journal_no_revision")

    def test_a_run_without_a_passport_is_refused(self) -> None:
        self._two_revisions()
        (self.root / "v2" / "passport.json").unlink()
        with mock.patch.dict(
                os.environ, {_FLAG: "1", "KUKAI_IR_REBUILD": "1"}):
            result = self._rebuild(
                {"doc_stamp": "v2", "base_doc_stamp": "@journal"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "journal_no_doc_name")

    def test_a_tampered_log_never_supplies_a_base(self) -> None:
        self._two_revisions()
        path = log_path(self.root, "дом")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["journal"]["events"][1]["event_hash"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch.dict(
                os.environ, {_FLAG: "1", "KUKAI_IR_REBUILD": "1"}):
            result = self._rebuild(
                {"doc_stamp": "v2", "base_doc_stamp": "@journal"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "journal_unreadable")


class ПотерянныйЖурналНеПутаетсяСПервымЧтением(unittest.TestCase):
    """🔴 "The building is being read for the first time" and "the journal is
    lost" both give revision 0.

    `load_log` returns `None` for EXACTLY "the file does not exist" —
    corruption raises `JournalError`, that distinction is already made. But
    `None` itself carries two meanings, and from inside the file they cannot
    be told apart: either the journal never existed, or it was wiped, the
    document was renamed, the wrong root was taken.

    From outside, they can be told apart: if the corpus holds decompiles of
    THE SAME building, yet there is no journal, "there are no revisions" is a
    claim about the MACHINE. The run's answer does not change (the history
    legitimately starts over), but suspicion travels along with it.
    """

    def test_a_first_read_stays_silent(self) -> None:
        """Positive control: a genuine first read stays silent."""
        from kir.decompile.journal_store import absent_log_may_hide_history
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                absent_log_may_hide_history(pathlib.Path(tmp), "Башня"),
                "в пустом корпусе «журнала нет» значит ровно «впервые»")

    def test_an_existing_run_of_the_same_building_is_named(self) -> None:
        from kir.decompile.journal_store import absent_log_may_hide_history
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            run = root / "run1"
            run.mkdir()
            (run / "passport.json").write_text(
                json.dumps({"doc_name": "Башня"}, ensure_ascii=False),
                encoding="utf-8")
            why = absent_log_may_hide_history(root, "Башня")
            self.assertIsNotNone(why, "разбор того же здания есть — молчать "
                                      "об утрате истории нельзя")
            self.assertIn("run1", why, "подозрение обязано назвать УЛИКУ")
            self.assertIsNone(
                absent_log_may_hide_history(root, "Другое здание"),
                "чужой разбор не повод подозревать утрату: прибор, "
                "подозревающий всегда, не сторожит")

    def test_a_gzipped_passport_is_seen_too(self) -> None:
        """🔴 A COMPRESSED PASSPORT IS THE MAIN CASE, NOT THE EDGE CASE.

        Measurement on the live corpus, 29.08.2026: 93 decompiles, 11 with
        `passport.json`, 45 with `passport.json.gz` — a bare
        `is_file("passport.json")` cannot SEE 82 of 93. The cleaner
        compresses side files in place, and the OLDER a decompile is, the
        more likely it is compressed.

        The first revision of this class checked only the RAW passport and
        was green by construction: it could not have caught the defect it
        was written for.
        """
        import gzip
        from kir.decompile.journal_store import absent_log_may_hide_history
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            run = root / "run_gz"
            run.mkdir()
            with gzip.open(str(run / "passport.json.gz"), "wt",
                           encoding="utf-8") as handle:
                json.dump({"doc_name": "Башня"}, handle, ensure_ascii=False)
            why = absent_log_may_hide_history(root, "Башня")
            self.assertIsNotNone(
                why, "сжатый паспорт обязан считаться уликой: иначе функция "
                     "даёт «впервые» на 82 разборах из 93")
            self.assertIn("run_gz", why)
            self.assertIsNone(
                absent_log_may_hide_history(root, "Другое"),
                "чужое здание уликой не становится и в сжатом виде")

    def test_service_directories_are_not_mistaken_for_runs(self) -> None:
        """`_journals` and other service directories are not decompiles, and
        mistaking them for evidence would mean suspecting a loss on an empty
        corpus."""
        from kir.decompile.journal_store import absent_log_may_hide_history
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "_journals").mkdir()
            (root / "_evidence").mkdir()
            self.assertIsNone(absent_log_may_hide_history(root, "Башня"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
