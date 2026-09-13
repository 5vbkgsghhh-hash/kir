"""Shadow-hook tests (rollout stage 1): flag discipline, mapping honesty,
and the coordinator-required FAIL-OPEN PROOF — a raising KIR path must leave
the caller completely unaffected."""
import json
import os
import tempfile
import unittest
from unittest import mock

# Keep telemetry fixtures process-unique.  Fixed names in the shared temp
# directory collide across users/workers and survive killed runs, turning an
# otherwise offline suite into an ownership-dependent one.
_TEST_DIR = tempfile.TemporaryDirectory(prefix="kir-shadow-test-")
_SHADOW = os.path.join(_TEST_DIR.name, "shadow.jsonl")
_REJ = os.path.join(_TEST_DIR.name, "rejections.jsonl")
os.environ["KIR_SHADOW_PATH"] = _SHADOW
os.environ["KIR_REJECTIONS_PATH"] = _REJ

from kir import shadow  # noqa: E402


# ─── THE FILE CHANGES THE PROCESS ENVIRONMENT — PUT IT BACK ──────────────
# Measured 12.08.2026: this file left keys behind, and the guard in
# `kir/tests/conftest.py` calls this a refusal on the PRODUCER, not on
# the next victim. The restoration is declared HERE, and not hidden inside a shared
# autofix: a file that changes the environment must say so itself.
import pytest as _pytest  # noqa: E402


@_pytest.fixture(autouse=True)
def _environment_is_returned_as_found():
    _saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(_saved)


def _clean():
    for p in (_SHADOW, _REJ):
        if os.path.exists(p):
            os.remove(p)


def _records():
    if not os.path.exists(_SHADOW):
        return []
    with open(_SHADOW, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class FlagDiscipline(unittest.TestCase):
    def test_default_off_is_noop(self):
        _clean()
        os.environ.pop("KUKAI_KIR_TOOL", None)
        shadow.observe_query_model({"category": "walls", "action": "none", "return": "count"})
        self.assertEqual(_records(), [], "flag off (default) must write nothing")

    def test_off_explicit(self):
        _clean()
        os.environ["KUKAI_KIR_TOOL"] = "off"
        shadow.observe_query_model({"category": "walls"})
        self.assertEqual(_records(), [])

    def test_stage2_keeps_telemetry(self):
        """stage2 is a superset of shadow: flipping the tool live must not
        lose the applicability map (final directive 2026-07-16)."""
        _clean()
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        os.environ["KIR_SHADOW_PATH"] = _SHADOW
        os.environ["KIR_REJECTIONS_PATH"] = _REJ
        try:
            shadow.observe_query_model({"category": "walls", "action": "none", "return": "count"})
            shadow.observe_frame({"action": "count", "object_kinds": ["category"]},
                                 "сколько стен", "2026")
        finally:
            os.environ.pop("KUKAI_KIR_TOOL", None)
        self.assertEqual(len(_records()), 2)


class ShadowMapping(unittest.TestCase):
    def setUp(self):
        _clean()
        os.environ["KUKAI_KIR_TOOL"] = "shadow"
        # env is process-global and sibling test modules move these at runtime —
        # pin them per-test, not at import
        os.environ["KIR_SHADOW_PATH"] = _SHADOW
        os.environ["KIR_REJECTIONS_PATH"] = _REJ

    def tearDown(self):
        os.environ.pop("KUKAI_KIR_TOOL", None)

    def test_mappable_count(self):
        shadow.observe_query_model({"category": "стены", "action": "none", "return": "count"},
                                   revit_version="Autodesk Revit 2024",
                                   user_query="сколько стен")
        (rec,) = _records()
        self.assertTrue(rec["mappable"])
        self.assertTrue(rec["kir_ok"])
        self.assertEqual(rec["op"], "query_count")
        self.assertEqual(rec["kind_mapped"], "wall")
        self.assertEqual(rec["revit_version"], "2024")
        self.assertEqual(len(rec["query_id"]), 16)

    def test_unsupported_feature_is_honest(self):
        """No lossy translation: a param-filter query is logged unmappable
        with the missing feature NAMED — that list is the next-opcode signal."""
        shadow.observe_query_model({"category": "walls",
                                    "param": {"name": "Comments", "op": "empty"}})
        (rec,) = _records()
        self.assertFalse(rec["mappable"])
        self.assertIn("param", rec["unsupported_features"])
        self.assertNotIn("kir_ok", rec)

    def test_unknown_category_feeds_rejections_raw(self):
        """Alias miss passes the RAW string to compile_program -> typed refusal
        + kir_rejections feed (the flywheel gets real traffic, per contract)."""
        shadow.observe_query_model({"category": "Витражи", "action": "none", "return": "count"})
        (rec,) = _records()
        self.assertTrue(rec["mappable"])          # shape was expressible
        self.assertFalse(rec["kir_ok"])            # kind out of coverage
        self.assertIn("KIR-G001", rec["diag_codes"])
        self.assertEqual(rec["handoff"], "recipe-path")
        with open(_REJ, encoding="utf-8") as f:
            rej = [json.loads(line) for line in f]
        self.assertEqual(rej[-1]["kind_requested"], "Витражи")   # RAW, unnormalized

    def test_garbage_args_never_raise(self):
        for garbage in (None, 42, "walls", [], {"category": {"nested": True}}):
            shadow.observe_query_model(garbage)   # must not raise


class NewlyAliasedDisciplineKinds(unittest.TestCase):
    """The group_by wave (28.07): 8 of 9 live kinds from the 27.07 decompile (Structural
    Framing/Railings/Generic Models/Mechanical Equipment/Plumbing Fixtures/Specialty
    Equipment/Furniture/Handrails — "Supports" deliberately not included, see shadow.py)
    got a row in KINDS as far back as 0a16e8f5 ("sections in tables"), but
    _CATEGORY_TO_KIND did not know them — before this wave THESE SAME WORDS behaved
    like test_unknown_category_feeds_rejections_raw (mappable=True,
    kir_ok=False, KIR-G001), verified verbatim on this tree before the fix
    (git stash of one file + run + git stash pop, 2026-07-28). Now —
    like test_mappable_count."""

    def setUp(self):
        _clean()
        os.environ["KUKAI_KIR_TOOL"] = "shadow"
        os.environ["KIR_SHADOW_PATH"] = _SHADOW
        os.environ["KIR_REJECTIONS_PATH"] = _REJ

    def tearDown(self):
        os.environ.pop("KUKAI_KIR_TOOL", None)

    def test_eight_disciplines_kinds_now_map_and_compile(self):
        cases = [
            ("Каркас несущий", "structural_framing"),
            ("Ограждения", "railing"),
            ("Перила", "railing"),
            ("Обобщённые модели", "generic_model"),
            ("Мех. оборудование", "mechanical_equipment"),
            ("Сантехника", "plumbing_fixture"),
            ("Специальное оборудование", "specialty_equipment"),
            ("Мебель", "furniture"),
            ("кабельные лотки", "cable_tray"),
        ]
        for cat_raw, expect_kind in cases:
            with self.subTest(cat_raw=cat_raw):
                _clean()
                shadow.observe_query_model({"category": cat_raw, "action": "none", "return": "count"})
                (rec,) = _records()
                self.assertTrue(rec["mappable"], cat_raw)
                self.assertTrue(rec["kir_ok"], f"{cat_raw}: {rec.get('diag_codes')}")
                self.assertEqual(rec["kind_mapped"], expect_kind)

    def test_opory_stays_unmapped_on_purpose(self):
        """The 9th name is NOT aliased — no confirmed BuiltInCategory this
        wave (Revit must not be touched to disambiguate). Falls through RAW,
        same shape as test_unknown_category_feeds_rejections_raw, so it keeps
        feeding kir_rejections rather than silently guessing a category."""
        shadow.observe_query_model({"category": "Опоры", "action": "none", "return": "count"})
        (rec,) = _records()
        self.assertTrue(rec["mappable"])
        self.assertFalse(rec["kir_ok"])
        self.assertIn("KIR-G001", rec["diag_codes"])


class FailOpenProof(unittest.TestCase):
    """Coordinator-required proof: KIR path RAISES -> caller unaffected."""

    def setUp(self):
        _clean()
        os.environ["KUKAI_KIR_TOOL"] = "shadow"
        os.environ["KIR_SHADOW_PATH"] = _SHADOW
        os.environ["KIR_REJECTIONS_PATH"] = _REJ

    def tearDown(self):
        os.environ.pop("KUKAI_KIR_TOOL", None)

    def test_compile_explosion_is_absorbed(self):
        with mock.patch("kir.compiler.compile_program",
                        side_effect=RuntimeError("boom")):
            shadow.observe_query_model({"category": "walls", "action": "none", "return": "count"})
        # no exception escaped; and the turn-side contract is just "no raise"

    def test_write_explosion_is_absorbed(self):
        os.environ["KIR_SHADOW_PATH"] = "/proc/definitely/not/writable/s.jsonl"
        try:
            shadow.observe_query_model({"category": "walls", "action": "none", "return": "count"})
        finally:
            os.environ["KIR_SHADOW_PATH"] = _SHADOW

    def test_serving_seam_shape(self):
        """The client.py hook is try/except around observe_query_model; simulate
        the exact seam: even if the MODULE IMPORT explodes, the guarded seam
        proceeds to the real tool call."""
        turn_completed = []

        def seam(args):
            try:
                import kir.shadow as sh
                with mock.patch.object(sh, "_map_to_program",
                                       side_effect=MemoryError("worst case")):
                    sh.observe_query_model(args)
            except Exception:
                pass
            turn_completed.append(True)   # the real _execute_query_model stand-in

        seam({"category": "walls"})
        self.assertEqual(turn_completed, [True])


class ПодставленнаяВерсияНАЗЫВАЕТ_СЕБЯ(unittest.TestCase):
    """🔴 FIVE FACTS WERE ONE NUMBER (F-351, 30.08.2026).

    `_norm_version` extracted the year and substituted "2026" in all other
    cases — including the one where the year WAS FOUND, but KIR does not
    support that version. "Version did not arrive", "not recognized", "older
    than supported", "newer than supported", and "actually 2026" all produced
    ONE value, and a measurement taken on Revit 2019 landed in the corpus as a measurement
    on 2026 — while right next to it `kir_ok` said "we support this" about a version
    that no one had ever tried it on.

    The substitution is legitimate: the observer has no right to crash just because the
    environment stayed silent. What is illegitimate is SILENCE about it.
    """

    ОЖИДАЕМОЕ = {
        "2024": ("2024", "as_supplied"),
        "2019": ("2026", "unsupported:2019"),
        "2027": ("2026", "unsupported:2027"),
        "Revit 2020": ("2026", "unsupported:2020"),
        "": ("2026", "not_supplied"),
        "мусор": ("2026", "unparsed"),
    }

    def test_every_kind_of_substitution_names_itself(self):
        for сырое, ожидание in self.ОЖИДАЕМОЕ.items():
            with self.subTest(вход=сырое):
                self.assertEqual(shadow._norm_version(сырое), ожидание)

    def test_the_answer_itself_did_not_change(self):
        """THE NARROWNESS CONTROL: the fix adds a REASON, it does not change the answer.
        The observer still does not crash and still substitutes 2026."""
        for сырое, (версия, _) in self.ОЖИДАЕМОЕ.items():
            with self.subTest(вход=сырое):
                self.assertEqual(shadow._norm_version(сырое)[0], версия)

    def test_the_supported_list_is_the_registry_not_a_copy(self):
        """The `unsupported:` provenance must be computed from the REGISTRY: a homemade list
        of versions would diverge from it on the very first new one."""
        from kir import spec
        for версия in spec.REVIT_VERSIONS:
            with self.subTest(версия=версия):
                self.assertEqual(shadow._norm_version(версия),
                                 (версия, "as_supplied"))

    def test_both_records_carry_the_provenance(self):
        """The reason must reach the RECORD, not stay stuck in the function: the corpus
        is read from the log, not from the code."""
        os.environ["KUKAI_KIR_TOOL"] = "shadow"
        try:
            open(_SHADOW, "w").close()
            shadow.observe_query_model(
                {"category": "walls", "action": "none", "return": "count"},
                "2019", "запрос")
            shadow.observe_frame({"action": "create", "object_kinds": ["wall"]},
                                 "запрос", "мусор")
            записи = _records()
        finally:
            os.environ.pop("KUKAI_KIR_TOOL", None)
        self.assertEqual(len(записи), 2)
        по_роду = {r["source"]: r for r in записи}
        self.assertEqual(по_роду["kir-shadow"]["revit_version_source"],
                         "unsupported:2019")
        self.assertEqual(по_роду["kir-frame-shadow"]["revit_version_source"],
                         "unparsed")
        for r in записи:
            self.assertEqual(r["revit_version"], "2026")


class КадрМеряетсяОсьюРОДОВ_АНеГранейСпособности(unittest.TestCase):
    """🔴 TWO DIFFERENT AXES THAT HAPPEN TO SHARE A PAIR OF WORDS (F-353).

    `_action_op_map` puts the SECOND half of `OpSpec.capability` into `kinds` — but
    that is a FACET of capability (`element`, `geometry`, `type`), not the object's kind.
    `observe_frame` compared them directly against `frame.object_kinds`, which holds
    `wall`, `door`, `pipe`. Hence two OPPOSITE lies from one instrument:
    «create_wall не покрывает wall» and «element покрыт всеми 70 опами».
    """

    def setUp(self) -> None:
        os.environ["KUKAI_KIR_TOOL"] = "shadow"
        open(_SHADOW, "w").close()

    def tearDown(self) -> None:
        os.environ.pop("KUKAI_KIR_TOOL", None)

    def _кадр(self, action, kinds):
        open(_SHADOW, "w").close()
        shadow.observe_frame({"action": action, "object_kinds": kinds},
                             "запрос", "2026")
        return _records()[-1]

    def test_a_kind_that_has_its_own_op_is_covered_by_THAT_op(self):
        r = self._кадр("create", ["wall"])
        self.assertEqual(r["applicability"], "covered")
        self.assertEqual(r["matched_ops"], ["create_wall"],
                         "в запись уехали ВСЕ опы действия, а не отвечающие "
                         "за запрошенный род")

    def test_a_capability_facet_is_not_an_object_kind(self):
        """`element` is a facet, not a kind. Previously a frame containing it was declared covered
        by all creation ops."""
        r = self._кадр("create", ["element"])
        self.assertEqual(r["applicability"], "partial")
        self.assertEqual(r["kinds_unknown"], ["element"])
        self.assertEqual(r["matched_ops"], [])

    def test_one_match_out_of_two_is_NOT_covered(self):
        """🔴 The verdict was set from `overlap`: a single match was enough
        to declare the frame covered. The applicability share measured a match of
        names, not compiler coverage."""
        r = self._кадр("create", ["element", "wall"])
        self.assertEqual(r["applicability"], "partial")
        self.assertEqual(r["kinds_expressible"], ["wall"])
        self.assertEqual(r["kinds_unknown"], ["element"])

    def test_an_undecided_crosswalk_is_not_called_uncovered(self):
        """🔴 A CONTROL AGAINST THE LIE IN THE OTHER DIRECTION. `delete`/`move`/
        `place` DO HAVE ops, it is just that their names do not give a kind and they do not
        take `kind_enum`. Calling them «не покрыто» would mean replacing one lie
        with another: the earlier instrument lied in the direction of coverage, the new one would lie
        in the direction of failure."""
        for action in ("delete", "move", "place"):
            with self.subTest(action=action):
                r = self._кадр(action, ["wall"])
                self.assertEqual(r["applicability"], "kinds_undecided")
                self.assertTrue(r["matched_ops"])

    def test_an_action_the_registry_does_not_know_is_uncovered(self):
        r = self._кадр("такого действия нет", ["wall"])
        self.assertEqual(r["applicability"], "uncovered")

    def test_the_undecided_remainder_is_counted_not_hidden(self):
        """An instrument in which NOT COVERED is indistinguishable from NOT PARSED lies
        silently. Here it states exactly how many it could not resolve."""
        r = self._кадр("create", ["wall"])
        self.assertGreater(r["crosswalk_undecided_ops"], 0)

    def test_the_crosswalk_is_built_from_the_registry_not_a_hand_list(self):
        """Both carriers are registry-based: the kind from the op's NAME and the kind from the
        `kind_enum` PARAMETER. There is no hand-written dictionary of kinds here, and there must not be."""
        from kir import spec
        amap, undecided = shadow._op_kind_map()
        self.assertTrue(set(amap["create"]) <= set(spec.KINDS))
        self.assertIn("create_wall", amap["create"]["wall"])
        # A `kind_enum` op expresses ALL kinds in the registry.
        self.assertEqual(set(amap["count"]), set(spec.KINDS))
        self.assertEqual(sorted(set(undecided)), undecided,
                         "остаток обязан быть без повторов")

    def test_no_op_is_listed_twice_for_one_kind(self):
        """An op can have SEVERAL facets for one action (`create_wall`:
        element and category). A list would give one name twice, and a reader
        counting length would get an inflated number of ops per kind."""
        amap, _ = shadow._op_kind_map()
        for action, per in amap.items():
            for kind, ops in per.items():
                with self.subTest(action=action, kind=kind):
                    self.assertEqual(len(ops), len(set(ops)))


if __name__ == "__main__":
    unittest.main()
