"""Провод `journal`: разбор — РЕВИЗИЯ здания, а пересборка её читает.

Слой `journal` пролежал на складе 471 строкой и 22 тестами, и все 22
проверяли ЧТО он считает: цепочку хешей, откат, аудит, отказ на чужой
дельте.  Ни один не проверял, доходит ли до него хоть один живой вход, —
поэтому склад и не был виден изнутри тестов.  Этот файл проверяет ровно
второе, и только его.

Четыре закона, каждый заработан:

* **инертность** — при выключенном флаге разбор обязан положить на диск ТЕ
  ЖЕ артефакты с теми же байтами.  Ни `journal.json`, ни пустого `_journals/`:
  пустая история — это уже утверждение об истории, а выключенная способность
  не имеет права утверждать ничего;
* **истории двух зданий не смешиваются НИКОГДА** — ключ журнала несёт
  дайджест полного `doc_name`, потому что санитайзер склеил бы «А Б» и «А_Б»
  в один файл, а слитые истории двух домов читаются как один дом, который
  дважды перестроили целиком;
* **дырка в логе — отказ, а не пропуск** — дерево головной ревизии пропало,
  журнал не читается, дельта не применяется: всё это `ok:false`, и ни один
  случай не заводит журнал заново.  Журнал, в который однажды попала
  неправда, ХУЖЕ отсутствующего: выглядит он точно так же, как честный;
* **база из журнала предъявляется, а не подразумевается** — `@journal`
  разрешается в конкретный `base_doc_stamp`, и он едет в ответе.  Выбор,
  которого спрашивающий не видит, — это `.FirstOrDefault()` с хорошей
  репутацией.
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

from kukai.ir import serving  # noqa: E402
from kukai.ir.decompile import pipeline as pipe  # noqa: E402
from kukai.ir.decompile.journal import journal_enabled  # noqa: E402
from kukai.ir.decompile.journal_store import (  # noqa: E402
    LOG_DIRNAME,
    building_key,
    history_report,
    load_log,
    log_path,
    record_revision,
)
from kukai.ir.decompile.tests.fixtures_decompile import (  # noqa: E402
    make_element,
)
from kukai.ir.decompile.tests.test_merkle import _fold, _grid_building  # noqa: E402
from kukai.ir.decompile.tests.test_pipeline import (  # noqa: E402
    FakePipelineBridge,
    _mini_elements,
    _mini_metadata,
)

_FLAG = "KUKAI_IR_JOURNAL"

#: Артефакты, обязанные быть детерминированными (тот же список, что у
#: merkle-собрата: `run.json`/`status.json` несут время стадий, I4).
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
# Законы хранилища: проверяются на деревьях, без конвейера
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
        """Ровно то, чего у системы не было: связь двух чтений одного дома."""

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
        """Смысл лога: состояние на ревизии N восстанавливается из ЛОГА."""

        from kukai.ir.decompile.journal_store import journal_of
        from kukai.ir.decompile.rebuild import BuildingState

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
        """Опровергающий тест: без дайджеста это ОДИН файл на два здания."""

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
        """Самый дорогой из отказов: перезапись стёрла бы улику."""

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
        """Штамп можно переиспользовать; состояние головы — нельзя подменить.

        Каталог `v1` перезаписан ЧУЖИМ зданием. Дельта, посчитанная от него,
        была бы дельтой от базы, которой в истории не было, и T-APPLY на
        мультимножестве этого не заметил бы — заметит `commit_trees`.
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
# Живой разбор: `pipeline.run_decompile` ← `serving` ← `/admin/kir/decompile`
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
        """Главный тест волны: живой разбор ведёт историю здания сам."""

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
        """`ok:false` в квитанции — не то же самое, что отсутствие истории."""

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
# Живая пересборка читает журнал: `@journal` ← `/admin/kir/rebuild`
# ───────────────────────────────────────────────────────────────────────────


class RebuildReadsTheJournal(unittest.TestCase):
    """`base_doc_stamp='@journal'` ← `handle_revit_rebuild` ← маршрут."""

    def setUp(self) -> None:
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        os.environ.pop("KUKAI_IR_ATOM_ESCROW", None)
        self._dev = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._dev.start()
        self._tmp = TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._dev.stop()
        self._tmp.cleanup()
        for flag in (_FLAG, "KUKAI_IR_REBUILD", "KUKAI_KIR_DECOMPILE"):
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
        """Смысл провода: базу не помнит оператор — её помнит журнал."""

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
        """Ветка `@journal` не имеет права быть слабее явной базы."""

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
        """Разбор снят до включения журнала: «нет записи» ≠ «нет различий»."""

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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
