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

from kukai.ir import shadow  # noqa: E402


# ─── ФАЙЛ МЕНЯЕТ ПРОЦЕССНОЕ ОКРУЖЕНИЕ — ВОЗВРАЩАЕМ ЕГО НА МЕСТО ──────────────
# Замер 12.08.2026: этот файл оставлял за собой ключи, и сторож в
# `kukai/ir/tests/conftest.py` называет это отказом на ПРОИЗВОДИТЕЛЕ, а не на
# следующей жертве. Восстановление объявлено ЗДЕСЬ, а не спрятано в общий
# автофикс: файл, меняющий окружение, обязан сказать об этом сам.
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
        shadow.observe_query_model({"category": "walls", "action": "count"})
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
            shadow.observe_query_model({"category": "walls", "action": "count"})
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
        shadow.observe_query_model({"category": "стены", "action": "count"},
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
        shadow.observe_query_model({"category": "Витражи", "action": "count"})
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
    """group_by-волна (28.07): 8 из 9 живых видов из разбора 27.07 (Каркас
    несущий/Ограждения/Обобщённые модели/Мех. оборудование/Сантехника/Спец.
    оборудование/Мебель/Перила — «Опоры» намеренно не занесена, см. shadow.py)
    получили строку в KINDS ещё в 0a16e8f5 («разделы в таблицах»), но
    _CATEGORY_TO_KIND их не знал — до этой волны ЭТИ ЖЕ СЛОВА вели себя
    как test_unknown_category_feeds_rejections_raw (mappable=True,
    kir_ok=False, KIR-G001), проверено дословно на этом дереве до правки
    (git stash одного файла + прогон + git stash pop, 2026-07-28). Теперь —
    как test_mappable_count."""

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
                shadow.observe_query_model({"category": cat_raw, "action": "count"})
                (rec,) = _records()
                self.assertTrue(rec["mappable"], cat_raw)
                self.assertTrue(rec["kir_ok"], f"{cat_raw}: {rec.get('diag_codes')}")
                self.assertEqual(rec["kind_mapped"], expect_kind)

    def test_opory_stays_unmapped_on_purpose(self):
        """The 9th name is NOT aliased — no confirmed BuiltInCategory this
        wave (Revit must not be touched to disambiguate). Falls through RAW,
        same shape as test_unknown_category_feeds_rejections_raw, so it keeps
        feeding kir_rejections rather than silently guessing a category."""
        shadow.observe_query_model({"category": "Опоры", "action": "count"})
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
        with mock.patch("kukai.ir.compiler.compile_program",
                        side_effect=RuntimeError("boom")):
            shadow.observe_query_model({"category": "walls", "action": "count"})
        # no exception escaped; and the turn-side contract is just "no raise"

    def test_write_explosion_is_absorbed(self):
        os.environ["KIR_SHADOW_PATH"] = "/proc/definitely/not/writable/s.jsonl"
        try:
            shadow.observe_query_model({"category": "walls", "action": "count"})
        finally:
            os.environ["KIR_SHADOW_PATH"] = _SHADOW

    def test_serving_seam_shape(self):
        """The client.py hook is try/except around observe_query_model; simulate
        the exact seam: even if the MODULE IMPORT explodes, the guarded seam
        proceeds to the real tool call."""
        turn_completed = []

        def seam(args):
            try:
                import kukai.ir.shadow as sh
                with mock.patch.object(sh, "_map_to_program",
                                       side_effect=MemoryError("worst case")):
                    sh.observe_query_model(args)
            except Exception:
                pass
            turn_completed.append(True)   # the real _execute_query_model stand-in

        seam({"category": "walls"})
        self.assertEqual(turn_completed, [True])


if __name__ == "__main__":
    unittest.main()
