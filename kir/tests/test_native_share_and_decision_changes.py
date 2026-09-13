"""TWO INSTRUMENTS MUST DISTINGUISH "CHEAP" FROM "NOT DONE."

Both instruments in this wave measure what nobody measured before
01.09.2026: the share of native BIM (what the free-geometry buildout is
closed by) and checkability's part in the model's solution (the
constitution's main metric). Both share one way to lie — printing zero where
there was no source — and these tests guard exactly against that.

🔴 HOW THESE TESTS DIFFER FROM CHECKING "THE INSTRUMENT WORKS." An author
checks what the instrument counts; what is asked here is **can it REFUSE to
count**. A zero assembled from honest refusals is this tree's named form,
and an instrument that cannot tell the difference is more harmful than one
that is missing.

The knowledge these tests were written for (each bought by the 01.09
analysis):

  * the operation's kind is DERIVED from two questions to the registry, and
    neither is enough alone: `create_filled_region` — geometry by
    `capability`, but a real element by category; `place_family` — no static
    categories, yet the most ordinary BIM element;
  * `DirectShape` IS in the lifter's table, so "category from
    `_CANDIDATES`" would have counted the geometry as native;
  * "native, but we do not lift it" is OUR reading gap, and merging it with
    geometry would mean charging our own blindness to the building's
    account.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kir import spec
from kir.instruments import decision_changes as dc
from kir.instruments import native_share as ns


class РодОперацииВыводится(unittest.TestCase):
    """The kind is derived from the registry, and it is cross-checked against the emitter's own admission."""

    def test_вывод_согласен_с_признанием_эмиттеров(self):
        self.assertEqual(ns.check_derivation(), [])

    def test_геометрических_операций_не_ноль_и_не_весь_реестр(self):
        derived = ns.geometry_only_ops()
        self.assertGreater(len(derived), 0)
        self.assertLess(len(derived), len(spec.OPS))

    def test_directshape_и_тела_выведены_геометрией(self):
        derived = ns.geometry_only_ops()
        for name in ("create_directshape", "create_solid_extrusion",
                     "create_solid_boolean", "create_surface"):
            self.assertIn(name, derived, name)

    def test_filled_region_НЕ_геометрия_хотя_capability_говорит_иначе(self):
        """Pitfall #1: one question to the registry is not enough.

        Its `capability` is exactly ('create','geometry'), but categories DO
        EXIST (`OST_FilledRegion`), and this is a real annotation element.
        """
        self.assertEqual(
            set(spec.OPS["create_filled_region"].capability),
            {("create", "geometry")})
        self.assertTrue(spec.op_result_categories({"op": "create_filled_region"}))
        self.assertNotIn("create_filled_region", ns.geometry_only_ops())

    def test_place_family_родной_хотя_категорий_нет(self):
        """Pitfall #2, the mirror case: there are no categories, yet the element is real."""
        self.assertIsNone(spec.op_result_categories({"op": "place_family"}))
        self.assertEqual(ns._op_kind("place_family"), "native")


class ДоляПоПрограмме(unittest.TestCase):
    """A control on inputs with an answer KNOWN IN ADVANCE, both sides."""

    def test_одни_родные_дают_сто_процентов(self):
        share = ns.share_of_program(
            {"ops": [{"op": "create_wall"}, {"op": "create_room"}]})
        self.assertEqual(share.share, 1.0)
        self.assertEqual(share.geometry_ops, 0)

    def test_одна_геометрия_даёт_ноль(self):
        share = ns.share_of_program(
            {"ops": [{"op": "create_directshape"}, {"op": "create_solid_extrusion"}]})
        self.assertEqual(share.share, 0.0)
        self.assertEqual(share.native_ops, 0)

    def test_чтение_в_долю_не_входит(self):
        """`query_*` creates nothing — neither into the numerator nor the denominator."""
        share = ns.share_of_program(
            {"ops": [{"op": "create_wall"}, {"op": "query_count"}]})
        self.assertEqual(share.decided, 1)
        self.assertEqual(share.other_ops, 1)
        self.assertEqual(share.share, 1.0)

    def test_программа_без_создающих_НЕ_ноль_а_неопределённость(self):
        """There was nothing to divide — and that is a DIFFERENT answer than "zero percent."""
        share = ns.share_of_program({"ops": [{"op": "query_count"}]})
        self.assertIsNone(share.share)

    def test_не_программа_отказ_а_не_ноль(self):
        with self.assertRaises(ns.NativeShareRefusal):
            ns.share_of_program({"intent": "здание"})

    def test_неизвестный_оп_отказ_а_не_тихий_пропуск(self):
        with self.assertRaises(ns.NativeShareRefusal):
            ns.share_of_program({"ops": [{"op": "create_teleporter"}]})


class ТриВедраПоРазбору(unittest.TestCase):
    def test_directshape_отделён_от_родного(self):
        share = ns.share_of_categories(
            {"OST_Walls": 10, ns.DIRECTSHAPE_PSEUDO_CATEGORY: 5})
        self.assertEqual(share.native_liftable, 10)
        self.assertEqual(share.geometry_no_meaning, 5)
        self.assertAlmostEqual(share.share, 10 / 15)

    def test_нечитаемая_категория_НЕ_записана_в_геометрию(self):
        """Our READING gap is a third bucket, not an absence of BIM meaning."""
        share = ns.share_of_categories({"OST_ЧегоМыНеЧитаем": 7})
        self.assertEqual(share.native_unlifted, 7)
        self.assertEqual(share.geometry_no_meaning, 0)
        self.assertEqual(share.share, 1.0)

    def test_пустая_перепись_НЕ_ноль_а_неопределённость(self):
        self.assertIsNone(ns.share_of_categories({}).share)

    def test_разбора_нет_отказ(self):
        with self.assertRaises(ns.NativeShareRefusal):
            ns.share_of_parse(pathlib.Path("/opt/kir/такого-разбора-нет"))

    def test_каталог_есть_переписи_нет_отказ(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ns.NativeShareRefusal):
                ns.share_of_parse(pathlib.Path(tmp))


class СчётчикОтказываетсяСчитать(unittest.TestCase):
    """The second instrument's main property — it does NOT print the mission's total."""

    def _feeds(self, tmp: str, rejections: list[dict], created: list[dict]):
        d = pathlib.Path(tmp)
        (d / "kir_rejections.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rejections), encoding="utf-8")
        (d / "kir_created_ids.jsonl").write_text(
            "\n".join(json.dumps(r) for r in created), encoding="utf-8")
        return d

    def test_фида_нет_отказ_а_не_ноль_событий(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(dc.FeedRefusal):
                dc.census(pathlib.Path(tmp))

    def test_окно_пусто_отказ_а_не_ноль_событий(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(tmp, [{"ts": "2026-01-01", "turn_id": "t",
                                   "diag_code": "KIR-G101"}], [])
            with self.assertRaises(dc.FeedRefusal):
                dc.census(d, since="2027-01-01")

    def test_считает_когда_источник_есть(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(
                tmp,
                [{"ts": "2026-01-01T00:00:00", "turn_id": "t1",
                  "diag_code": "KIR-G101", "attempt_id": "a1",
                  "op_id": "w1", "field_name": "level"},
                 {"ts": "2026-01-01T00:00:10", "turn_id": "t1",
                  "diag_code": "KIR-G102", "attempt_id": "a2",
                  "op_id": "w1", "field_name": "type"}],
                [{"ts": "2026-01-01T00:00:20", "turn_id": "t1",
                  "created_count": 3}])
            c = dc.census(d)
            self.assertEqual(c.turns_refused, 1)
            self.assertEqual(c.turns_refused_then_built, 1)
            self.assertEqual(c.deep_then_built, 1)      # KIR-G* — grounding
            self.assertEqual(c.attempts_pairs, 1)
            self.assertEqual(c.place_changed, 1)
            self.assertEqual(c.place_repeated, 0)

    def test_то_же_место_повторено_не_считается_изменением(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(
                tmp,
                [{"ts": "2026-01-01T00:00:00", "turn_id": "t1",
                  "diag_code": "KIR-G101", "attempt_id": "a1",
                  "op_id": "w1", "field_name": "level"},
                 {"ts": "2026-01-01T00:00:10", "turn_id": "t1",
                  "diag_code": "KIR-G101", "attempt_id": "a2",
                  "op_id": "w1", "field_name": "level"}],
                [])
            c = dc.census(d)
            self.assertEqual(c.place_changed, 0)
            self.assertEqual(c.place_repeated, 1)

    def test_поток_заземления_НЕ_выдаёт_себя_за_итог(self):
        """The previous edition pinned the phrase "MISSION TOTAL IS NOT
        PRINTED HERE" — that is, a STATEMENT, retracted on 02.09 together
        with the instrument's edit. What is pinned is a PROPERTY: the stream
        of refusals declares itself a capability, not an event, and names
        WHY it is not a total."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(tmp, [{"ts": "2026-01-01T00:00:00",
                                   "turn_id": "t1", "diag_code": "KIR-G101"}], [])
            text = dc.render(dc.census(d), d)
        self.assertIn("В ИТОГ МИССИИ НЕ ВХОДИТ", text)
        self.assertIn("plan_digest", text)
        self.assertIn("ВЕРХНЯЯ ГРАНИЦА", text)

    def test_разведка_не_глубокий_род(self):
        """`KIR-B013` carries a refusal code but is not a refusal."""
        unknown: set[str] = set()
        self.assertEqual(
            dc.speech_kind("KIR-B013", frozenset(), unknown), "разведка")
        self.assertNotIn("разведка", dc.DEEP_KINDS)

    def test_неизвестный_код_копится_а_не_молчит(self):
        unknown: set[str] = set()
        dc.speech_kind("KIR-Z999", frozenset({"KIR-G101"}), unknown)
        self.assertIn("KIR-Z999", unknown)


class ПриборНеПечатаетНольБезИсточника(unittest.TestCase):
    """Return code 2 means "the instrument DID NOT JUDGE" — this catalog's idiom."""

    def test_native_share_без_доводов_возвращает_два(self):
        self.assertEqual(ns.main([]), 2)

    def test_native_share_нет_файла_программы_возвращает_два(self):
        self.assertEqual(ns.main(["--program", "/opt/kir/нет-такого.json"]), 2)

    def test_decision_changes_нет_фидов_возвращает_два(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(dc.main(["--feeds", tmp]), 2)


class ЛентаСвидетеляЧитаетсяИСудитсяХозяйскимОпределением(unittest.TestCase):
    """The instrument asked for rights over three carriers and DID NOT READ
    two of them (E-97).

    Rights were granted on 02.09.2026, the promise "it will start counting
    without a single edit" turned out to be wrong about its own code, and
    the reading path was written in. These tests guard THREE things, and
    none of them follows from the other two: the carrier is read · the
    definition belongs to the owner · the total is NOT declared until there
    is a task boundary.
    """

    def _feeds(self, tmp: str, witness: list[dict],
               programs: list[dict] | None = None,
               evidence: bool = True) -> pathlib.Path:
        root = pathlib.Path(tmp)
        tele = root / "telemetry"
        tele.mkdir(parents=True, exist_ok=True)
        (tele / "kir_witness.jsonl").write_text(
            "\n".join(json.dumps(r) for r in witness), encoding="utf-8")
        (tele / "kir_programs.jsonl").write_text(
            "\n".join(json.dumps(r) for r in (programs or [])), encoding="utf-8")
        if evidence:
            ev = root / "evidence" / "kir_acceptance"
            ev.mkdir(parents=True, exist_ok=True)
            (ev / "one.jsonl").write_text("{}\n", encoding="utf-8")
        return tele

    @staticmethod
    def _round(ts: str, execution: str = "read_completed", *, plan: str = "",
               acceptance: str = "not_applicable", doc_key: str = "",
               reason: str | None = None) -> dict:
        row: dict = {"ts": ts, "plan_digest": plan, "ok": True,
                     "outcome": {"execution": execution,
                                 "acceptance": acceptance,
                                 "witness": "satisfied", "retry": "safe"}}
        if doc_key:
            row["doc_key"] = doc_key
        if reason is not None:
            row["acceptance_evidence"] = {"reason": reason}
        return row

    # ── the carrier is read, and each one refuses BY THE NAME OF ITS OWN subject ──

    def test_свидетеля_нет_отказ_называет_свидетеля(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(tmp, [self._round("2026-01-01T00:00:00")])
            (d / "kir_witness.jsonl").unlink()
            with self.assertRaises(dc.FeedRefusal) as caught:
                dc.mission(d)
        self.assertIn("kir_witness.jsonl", str(caught.exception))

    def test_программ_нет_отказ_называет_программы(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(tmp, [self._round("2026-01-01T00:00:00")])
            (d / "kir_programs.jsonl").unlink()
            with self.assertRaises(dc.FeedRefusal) as caught:
                dc.mission(d)
        self.assertIn("kir_programs.jsonl", str(caught.exception))

    def test_журнала_приёмки_нет_отказ_называет_журнал(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(tmp, [self._round("2026-01-01T00:00:00")],
                            evidence=False)
            with self.assertRaises(dc.FeedRefusal) as caught:
                dc.mission(d)
        self.assertIn("kir_acceptance", str(caught.exception))

    # ── the definition belongs to the owner: three branches, each checked separately ──

    def test_откат_свидетеля_это_глубокий_род(self):
        self.assertEqual(
            dc.speech_kind_row({"execution": "rolled_back"}), "свидетель")
        self.assertIn("свидетель", dc.DEEP_KINDS)

    def test_приёмка_отвергла_это_глубокий_род(self):
        self.assertEqual(
            dc.speech_kind_row({"acceptance": "rejected"}), "приёмка")

    def test_слепота_приёмки_НЕ_речь_проверяемости(self):
        """`partial_blind_scope` means "I do not know how to check this kind
        of op," not "the model is wrong." Counting one's own blindness as a
        verdict would mean recording it among the mission's events — the
        owner's own rule, bought by them on 24.08."""
        blind = dc.speech_kind_row({"acceptance": "inconclusive",
                                    "acceptance_reason": "partial_blind_scope"})
        self.assertEqual(blind, "приёмка слепа")
        self.assertNotIn(blind, dc.DEEP_KINDS)
        self.assertEqual(
            dc.speech_kind_row({"acceptance": "inconclusive"}),
            "приёмка не дочитала")

    def test_событие_требует_И_изменения_И_постройки(self):
        """A control both ways: without the change, the turn goes into DISPUTED."""
        deep = {"n": 1, "execution": "rolled_back"}
        built = {"n": 3, "built": True}
        с_изменением = dc.score_stream(
            [deep, {"n": 2, "changed": True}, built])
        без_изменения = dc.score_stream(
            [deep, {"n": 2, "changed": None}, built])
        self.assertEqual(len(с_изменением["events"]), 1)
        self.assertEqual(len(без_изменения["events"]), 0)
        self.assertEqual(len(без_изменения["ambiguous"]), 1)

    # ── the total is NOT declared until there is a task boundary ──

    def test_без_границы_задачи_итог_НЕ_объявлен(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(tmp, [
                self._round("2026-01-01T00:00:00", "rolled_back", plan="a"),
                self._round("2026-01-01T00:00:10", "committed", plan="b")])
            m = dc.mission(d)
        self.assertEqual(m.task_keys, 0)
        self.assertFalse(m.definition_holds)
        self.assertNotIn("СОБЫТИЙ МИССИИ", dc.render_mission(m))

    def test_с_границей_задачи_итог_объявлен(self):
        """🔴 THE CONTROL THAT MUST TURN RED AT REFUSAL: the same input plus
        a NAMED document — and the instrument starts judging. Without it,
        "did not judge" would be indistinguishable from "can only refuse."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(tmp, [
                self._round("2026-01-01T00:00:00", "rolled_back",
                            plan="a", doc_key="дом.rvt"),
                self._round("2026-01-01T00:00:10", "committed",
                            plan="b", doc_key="дом.rvt")])
            m = dc.mission(d)
        self.assertEqual(m.task_keys, 1)
        self.assertTrue(m.definition_holds)
        self.assertIn("СОБЫТИЙ МИССИИ", dc.render_mission(m))

    def test_порог_не_подбирается_под_ответ(self):
        """The first edition judged by the SHARE of discriminating power with
        a 1% threshold, and the threshold was invented — it let 1.2%
        through. The criterion is structural, and this is pinned: the share
        does not affect the decision."""
        m = dc.Mission(task_keys=0, upper_bound=1000, events=0)
        self.assertFalse(m.definition_holds)      # discriminating power 100%
        m2 = dc.Mission(task_keys=1, upper_bound=1000, events=1000)
        self.assertTrue(m2.definition_holds)      # discriminating power 0%

    def test_прибор_несёт_свой_контроль_внутри(self):
        """The upper bound is computed by the same code with a predicate
        that is ALWAYS true. If it equals the event count, the
        discriminator is inert — and this is visible from the output
        itself, not from someone else's run."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(tmp, [
                self._round("2026-01-01T00:00:00", "rolled_back", plan="a"),
                self._round("2026-01-01T00:00:10", "committed", plan="b")])
            m = dc.mission(d)
        self.assertGreaterEqual(m.upper_bound, m.events)
        self.assertEqual(m.discriminated, m.upper_bound - m.events)
        self.assertIn("РАЗЛИЧАЮЩАЯ СИЛА", dc.render_mission(m))

    def test_три_исхода_три_кода_возврата(self):
        """0 — judged · 2 — carrier not read · 3 — read, nothing to judge by.
        Merging 2 and 3 would erase the difference between "no rights" and
        "no task boundary," and the two are cured in opposite ways."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._feeds(tmp, [
                self._round("2026-01-01T00:00:00", "rolled_back", plan="a")])
            self.assertEqual(dc.main(["--feeds", str(d)]), 3)
            (d / "kir_witness.jsonl").unlink()
            self.assertEqual(dc.main(["--feeds", str(d)]), 2)


if __name__ == "__main__":
    unittest.main()
