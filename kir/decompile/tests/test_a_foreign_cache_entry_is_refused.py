"""A FOREIGN CACHE ENTRY IS A MISS WITH A NAMED REASON, NOT AN EMPTY BUILDING.

`F-260` (P0) and `F-250` (P1) are two ends of ONE missing question:
"did our serializer even write this file?" There was no answer, so a
foreign object was either mistaken for an answer, or dropped the run.

**F-260.** `serialize_lift_result` always writes four keys (`joins`/`groups`
may carry `None` as a VALUE, but the key is present — this is written down
in the serializer itself). `deserialize_lift_result` required none of them:
each was fetched via `.get(..., default)`. So `{}` was a legitimate record
with ALL fields at their defaults — "the building is empty AND joins were
not asked about AND groups were not asked about" — the most plausible shape
a complete read failure can take. The path is LIVE: the pipeline calls the
wrapper with `enabled=True` unconditionally.

RUN BEFORE THE FIX: a fresh decompile gives 1 node; substituting `{}` under
the correct name gives "HIT: nodes = 0," and there was nothing to ask about
the reason.

**F-250.** The recovery branch caught `(KeyError, ValueError)`. Legitimate
JSON `{"nodes": null}` raised `TypeError` and dropped the ENTIRE decompile —
even though law R-3 of this same file allows the cache to cost a
RECOMPUTATION and forbids giving a wrong answer; it says nothing at all
about "dropping the run."

🔴 A THIRD KIND OF FAILURE FOUND BY EXECUTION, NOT BY READING THE PACKAGE.
The package named two names. On inspection a third turned up: `joins`/
`groups` arriving as a list or a number reach `.get(...)` and raise
`AttributeError` — the same corruption under a name that neither the old
branch nor the branch fixed per the package caught. Here it is NAMED in the
prologue (a refusal carrying the field's name), while the branch stands as
a belt: the law "the cache must not drop the run" must not rest on the
prologue's completeness.

MEASUREMENT OF THE LIVE CORPUS 30.08.2026 (read-only): 65 cache entries,
`wrapper` is absent from ALL of them, and at least one of the four keys is
missing from all 65. So the marking is not "for the future" — today's disk
does not match it at all, and each such entry will be recomputed exactly
once.

Run:
    /opt/kir-audit/suite-venv/venv/bin/python -m pytest \
        kir/decompile/tests/test_a_foreign_cache_entry_is_refused.py -q
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kir.decompile.lift_cache import (
    LIFT_CACHE_WRAPPER_VERSION,
    _entry_path,
    cached_lift_document_detailed,
    deserialize_lift_result,
    lift_cache_key,
    lift_cache_refusals,
    serialize_lift_result,
)
from kir.decompile.lift import LiftResult
from kir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)


def _document() -> L0Document:
    wall = L0Element(
        element_id="100", category="OST_Walls", category_ru="Стены",
        type_id="7", type_name="W200", level_id="10", level_name="L1",
        geom_kind=GeometryKind.CURVE, p0_mm=(0., 0., 0.),
        p1_mm=(5000., 0., 0.), rotation_deg=None,
        bbox_min_mm=(0., -100., 0.), bbox_max_mm=(5000., 100., 3000.),
        host_id=None, params={"WALL_USER_HEIGHT_PARAM": 3000.0})
    return L0Document(
        doc_name="lc", revit_version="2024", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "L1", 0.0),), grids=(), rooms=(),
        project_info=ProjectInfo(), elements=(wall,))


#: Corruptions that, BEFORE the fix, were either mistaken for an answer or
#: dropped the run. Each one is legitimate JSON: they cannot be mistaken
#: for "the file got corrupted," and that is the whole point.
def _plants() -> dict[str, object]:
    honest = serialize_lift_result(LiftResult(nodes=(), diagnostics=()))
    no_wrapper = dict(honest)
    no_wrapper.pop("wrapper")
    return {
        "пустой объект": {},
        "без отметки обёртки": no_wrapper,
        "чужая отметка": {**honest, "wrapper": "lift-cache/999"},
        "нет ключа joins": {k: v for k, v in honest.items() if k != "joins"},
        "nodes = null": {**honest, "nodes": None},
        "diagnostics = null": {**honest, "diagnostics": None},
        "diagnostics строкой": {**honest, "diagnostics": ["не запись"]},
        "joins списком": {**honest, "joins": ["не запись"]},
        "groups числом": {**honest, "groups": 7},
        "запись — список": ["целиком не объект"],
    }


class AForeignEntryNeverBecomesAnAnswer(unittest.TestCase):
    """F-260: a substituted record must yield a RECOMPUTATION, not an empty
    building."""

    def test_every_plant_yields_the_real_building_and_a_named_reason(self):
        document = _document()
        fresh = cached_lift_document_detailed(document, None, None,
                                              enabled=False)
        self.assertEqual(len(fresh.nodes), 1, "фикстура вырождена")
        key = lift_cache_key(document, None, None)
        for name, plant in _plants().items():
            with self.subTest(порча=name), TemporaryDirectory() as tmp:
                cache = Path(tmp)
                _entry_path(cache, key).write_text(
                    json.dumps(plant, ensure_ascii=False), encoding="utf-8")
                hit = cached_lift_document_detailed(
                    document, None, None, enabled=True, cache_dir=str(cache))
                self.assertEqual(
                    len(hit.nodes), len(fresh.nodes),
                    "чужая запись отдана за ответ: здание уменьшилось молча")
                self.assertEqual(hit, fresh)
                reasons = lift_cache_refusals(cache)
                self.assertTrue(
                    reasons and reasons[0],
                    "запись отвергнута БЕЗ причины: спросить не у чего")


class ACacheNeverBringsDownTheRun(unittest.TestCase):
    """F-250: the worst legitimate cache outcome is a recomputation, not a
    run failure."""

    def test_no_plant_escapes_as_an_exception(self):
        document = _document()
        key = lift_cache_key(document, None, None)
        for name, plant in _plants().items():
            with self.subTest(порча=name), TemporaryDirectory() as tmp:
                cache = Path(tmp)
                _entry_path(cache, key).write_text(
                    json.dumps(plant, ensure_ascii=False), encoding="utf-8")
                try:
                    cached_lift_document_detailed(
                        document, None, None, enabled=True,
                        cache_dir=str(cache))
                except Exception as exc:  # noqa: BLE001 — this is the subject under test
                    self.fail(f"кэш уронил разбор на {name!r}: "
                              f"{type(exc).__name__}: {exc}")

    def test_the_three_kinds_are_named_separately(self):
        """The three kinds of failure are distinguishable, and the third is
        not derived from the first two."""
        honest = serialize_lift_result(LiftResult(nodes=(), diagnostics=()))
        with self.assertRaises(ValueError) as missing:
            deserialize_lift_result(
                {k: v for k, v in honest.items() if k != "groups"})
        self.assertIn("missing groups", str(missing.exception))
        with self.assertRaises(ValueError) as shape:
            deserialize_lift_result({**honest, "joins": ["не запись"]})
        self.assertIn("not a mapping or null", str(shape.exception))
        with self.assertRaises(TypeError):
            deserialize_lift_result({**honest, "diagnostics": ["строка"]})


class TheHonestCacheDoesNotMove(unittest.TestCase):
    """🔴 THE SECOND OUTCOME. A check where the substituted record and the
    honest one behave identically guards nothing: it would be green even
    on an empty cache."""

    def test_a_real_entry_is_still_a_hit_and_round_trips(self):
        document = _document()
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)
            first = cached_lift_document_detailed(
                document, None, None, enabled=True, cache_dir=str(cache))
            entries = sorted(p.name for p in cache.glob("*.json"))
            self.assertEqual(len(entries), 1, "запись не легла на диск")
            second = cached_lift_document_detailed(
                document, None, None, enabled=True, cache_dir=str(cache))
            self.assertEqual(second, first)
            self.assertEqual(len(second.nodes), 1)
            self.assertEqual(
                lift_cache_refusals(cache), (),
                "честная запись попала в журнал отказов")

    def test_the_entry_carries_the_wrapper_mark(self):
        payload = serialize_lift_result(LiftResult(nodes=(), diagnostics=()))
        self.assertEqual(payload["wrapper"], LIFT_CACHE_WRAPPER_VERSION)
        self.assertEqual(deserialize_lift_result(payload),
                         LiftResult(nodes=(), diagnostics=()))


class TheLedgerIsAskableAndNeverThrows(unittest.TestCase):
    """A guard capable of dropping the run costs more than the defect it
    guards against."""

    def test_an_absent_cache_dir_is_empty_not_an_error(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(lift_cache_refusals(Path(tmp) / "нет"), ())

    def test_a_damaged_ledger_line_is_counted_not_dropped(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "unusable.jsonl").write_text(
                '{"key": "a", "reason": "первая"}\nне json\n',
                encoding="utf-8")
            self.assertEqual(
                lift_cache_refusals(cache),
                ("первая", "unparsable ledger line"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
