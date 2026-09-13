"""CROSS-CHECKING PLAN AND VOLUME: two censuses of one building.

MEASURED 11.08.2026, the reason the module was written and the reason it
was DECIDED NOT TO RECONCILE the two censuses:

| decompile           | both   | plan only   | volume only   | neither |
|----------------------|-------:|------------:|--------------:|--------:|
| `sob62_fas_r23_v19` |  3 948 |         337 |            270 |     663 |
| `snowdon_plumb_v4`  | 26 203 |          55 |          5 701 |     226 |

Broken down by name, and all three classes of discrepancy turned out to
be LEGITIMATE:

  * datums, annotations, rooms, spaces — the plan draws them, there is
    no body;
  * vertical runs — 5 506 pipes and 195 ducts (21% of the building): the
    volume draws them as a capsule, the plan honestly declares
    `degenerate`, because a riser projects to a point;
  * walls with an axis but no bounding box — 291 out of 2 360 (12.3%):
    all 291 have no `bbox_*` in L0 and all 291 have an axis in
    `curve.index.json`. The plan draws a line labeled
    `thickness_unknown`; a shell must CONTAIN the body, and an axis
    without a thickness does not contain it.

A common denominator would force one of the two censuses to answer a
question that is not its own. That is why there is no third census
here, but a breakdown into four buckets, where the cause is given by
whichever census named it.
"""

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from kir.viewer import reconcile as R


class TheBucketsAreClosedAndBalance(unittest.TestCase):

    def test_every_bucket_has_a_russian_sentence(self):
        """A bucket without an explanation is a number with nothing to
        read it by."""
        for name in (R.Bucket.BOTH, R.Bucket.PLAN_ONLY, R.Bucket.SCENE_ONLY,
                     R.Bucket.NEITHER):
            self.assertTrue(R.BUCKET_RU.get(name, "").strip(), name)

    def test_the_law_is_checked_not_promised(self):
        """`объединение = оба + только_план + только_объём + ни_один`.
        An element that fell into none of the buckets is exactly the
        case the cross-check was written for."""
        result = R.Reconciliation(union=10, buckets={"both": 4, "plan_only": 3,
                                                     "scene_only": 2,
                                                     "neither": 1})
        self.assertTrue(result.balanced())
        result.buckets["neither"] = 0
        self.assertFalse(result.balanced())

    def test_an_unbalanced_reconciliation_says_so_in_its_payload(self):
        payload = R.Reconciliation(union=5, buckets={"both": 1}).to_dict()
        self.assertFalse(payload["balanced"])


class ItRefusesToInventPerElementReasons(unittest.TestCase):
    """`PreviewCensus` groups the omitted by (cause, category) and keeps
    up to five examples. So there is NO named plan-cause for the
    element, and assigning one by category would be a guess put on the
    element — and a guess on an element reads as a measurement."""

    def test_the_limitation_is_stated_in_the_payload(self):
        payload = R.Reconciliation(
            note="причины для `scene_only` даны РАСПРЕДЕЛЕНИЕМ").to_dict()
        self.assertIn("РАСПРЕДЕЛЕНИЕМ", payload["note"])

    def test_the_module_says_why_it_does_not_merge_the_censuses(self):
        payload = R.Reconciliation().to_dict()
        self.assertIn("НЕ СВОДЯТСЯ", payload["verdict_ru"])
        self.assertIn("знаменатель", payload["verdict_ru"])


class ItIsNotAThirdCensus(unittest.TestCase):
    """There is no tally of its own here: both censuses are published in
    full and side by side, so they can be read separately, not only as
    a sum."""

    def test_both_parent_censuses_ride_along(self):
        payload = R.Reconciliation(
            plan_census={"considered": 1}, scene_census={"eligible": 1}
        ).to_dict()
        self.assertIn("plan_census", payload)
        self.assertIn("scene_census", payload)

    def test_it_does_not_reimplement_either_census(self):
        import inspect
        source = inspect.getsource(R.reconcile_run)
        # The parents do the counting; this is only the breakdown.
        self.assertIn("preview_snapshot", source)
        self.assertIn("build_from_decompile", source)
        self.assertIn("building.census.to_dict()", source)
        self.assertIn("snap.census.as_dict()", source)


def scene_without_requested_analyses():
    """A real one-element L0 stream through the public run-name wrapper."""
    from kir.clash.tests.test_two_readers_of_one_format_must_agree import HEADER, ELEMENT, FOOTER
    from kir.viewer import scene as S

    with tempfile.TemporaryDirectory(prefix="kir-scene-absence-") as directory:
        root = pathlib.Path(directory)
        run = root / "one-wall"
        run.mkdir()
        (run / "L0.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in (HEADER, ELEMENT, FOOTER)), encoding="utf-8")
        with patch.dict("os.environ", {S.CORPUS_ENV: str(root)}):
            binary, response = S.scene_from_decompile(run.name)
        assert binary and response["census"]["totals"]["hulled"] == 1
        return response


class TheSceneAdmitsItDidNotAsk(unittest.TestCase):
    """A scene's silence about a discrepancy reads as "there are no
    discrepancies". The measurement says the opposite: on the facade,
    663 elements are shown by NEITHER screen."""

    def test_a_scene_publishes_that_reconciliation_was_not_requested(self):
        response = scene_without_requested_analyses()
        self.assertIs(response["reconcile"]["available"], False)
        self.assertTrue(response["reconcile"]["reason"])
        self.assertEqual(response["reconcile"]["endpoint"], "/api/viewer/reconcile")


class TheCostIsWhyItIsASeparateEntry(unittest.TestCase):
    """The cross-check builds BOTH censuses in full: 0.99 s facade, 4.9
    s engineering. Carrying this in the frame would mean putting back
    onto the scene the cost that deltas had just removed from it."""

    def test_it_is_not_called_from_the_scene_path(self):
        import inspect
        from kir.viewer import live_scene as L
        from kir.viewer import scene as S
        for module in (S, L):
            self.assertNotIn("reconcile_run", inspect.getsource(module))


# ═══════════════════════════════════════════════════════════════════════════
# LIVE CROSS-CHECK
# ═══════════════════════════════════════════════════════════════════════════

class TheLiveDivergenceIsOfADifferentNature(unittest.TestCase):
    """A decompile is looked at when the archive is opened; a live
    scene — for three hours.

    MEASURED 11.08.2026, 300 programs / 6 000 elements:

        snapshot PRESENT:  both 4 200, plan only 1 800
        snapshot ABSENT:   plan only 6 000, both 0     <- plan IS FULL, volume IS EMPTY

    The second line is exactly that outcome: both sides are honest on
    their own, the plan shows the whole building, the volume shows
    nothing, and nobody says that this is one building.
    """

    SNAPSHOT = {"levels": [{"id": 1, "name": "L1", "elevation_mm": 0.0}],
                "pipe_types": [{"id": 30, "name": "Сталь",
                                "section": {"kind": "nominal_table",
                                            "source": "PipeSegment.GetSizes",
                                            "sizes": [[100.0, 114.3]]}}]}

    def _session(self, with_snapshot):
        from kir.live import journal as _journal
        from kir.live import showroom as _showroom
        from kir.viewer import live_scene as L
        key = _journal.key_for("тест-сверка", "тест-док")
        _journal.reset(key)
        _showroom.forget(key)
        R.live_reset(key)
        if with_snapshot:
            _journal.remember_sections(key, self.SNAPSHOT)
        _journal.append(key, {"ops": [{"op": "create_level", "id": "lv",
                                       "name": "L1", "elev_mm": 0.0}]})
        _journal.append(key, {"ops": [
            {"op": "create_pipe", "id": "p0",
             "p0_mm": [0.0, 0.0, 2800.0], "p1_mm": [12000.0, 0.0, 2800.0],
             "diameter_mm": 100.0,
             "pipe_type": {"by": "name", "value": "Сталь"},
             "level": {"by": "name", "value": "L1"}}]})
        return L.scene_from_session("тест-сверка", "тест-док", 0)[1]

    def test_without_a_snapshot_the_plan_is_full_and_the_volume_is_empty(self):
        buckets = self._session(False)["reconcile"]["buckets"]
        self.assertEqual(buckets.get("both", 0), 0)
        self.assertGreater(buckets.get("plan_only", 0), 0)

    def test_with_a_snapshot_the_same_element_appears_in_both(self):
        buckets = self._session(True)["reconcile"]["buckets"]
        self.assertGreater(buckets.get("both", 0), 0)

    def test_the_plan_only_sentence_sends_the_operator_not_the_author(self):
        """Without a snapshot, the fix is made by the OPERATOR — by
        opening the model — not by the program's author. Sending the
        author to fix operands would mean sending them to the wrong
        place."""
        self.assertIn("ОПЕРАТОР", R.LIVE_BUCKET_RU[R.Bucket.PLAN_ONLY])

    def test_the_live_sentences_differ_from_the_decompile_ones(self):
        """The fourth bucket means something different in a live
        session: "the op is written, but the element is on neither
        screen"."""
        self.assertNotEqual(R.LIVE_BUCKET_RU[R.Bucket.NEITHER],
                            R.BUCKET_RU[R.Bucket.NEITHER])


class TheDenominatorIsEveryWrittenOperation(unittest.TestCase):
    """Otherwise the fourth bucket is empty BY CONSTRUCTION: an element
    that nobody created will not land in the union of "drawn and
    shelled".

    Measured on a five-op program: `neither` — 4 out of 5
    (`create_level`, `create_grid`, `create_room`, `set_param`)."""

    def test_an_op_that_makes_no_element_lands_in_neither(self):
        key = ("живая", "знаменатель")
        R.live_reset(key)
        out = R.live_frame(
            key, ops_by_id={"p1/sp": "set_param", "p1/w0": "create_wall"},
            drawn={"p1/w0"}, datums=set(), bodied=set(),
            refused={"p1/w0": "нет габарита"},
            no_body_ops={"set_param": 1}, whole=True)
        self.assertEqual(out["buckets"], {"neither": 1, "plan_only": 1})
        self.assertTrue(out["balanced"])

    def test_datums_count_as_drawn_by_the_plan(self):
        """`preview` keeps them as a separate list. Not looking there
        would mean declaring the axis invisible exactly where the plan
        shows it."""
        key = ("живая", "датумы")
        R.live_reset(key)
        out = R.live_frame(key, ops_by_id={"p1/g0": "create_grid"},
                           drawn=set(), datums={"p1/g0"}, bodied=set(),
                           refused={}, no_body_ops={"create_grid": 1},
                           whole=True)
        self.assertEqual(out["buckets"], {"plan_only": 1})

    def test_the_reason_for_a_bodiless_op_is_keyed_by_op_name(self):
        """`no_body` is keyed by the op's NAME, and "this op does not
        create a body" is a property of the operation, not of its
        instance. That is why this is not a guess."""
        key = ("живая", "причина")
        R.live_reset(key)
        out = R.live_frame(key, ops_by_id={"p1/sp": "set_param"},
                           drawn=set(), datums=set(), bodied=set(),
                           refused={}, no_body_ops={"set_param": 1},
                           whole=True)
        self.assertIn("set_param",
                      " ".join(out["by_reason"]["neither"].keys()))

    def test_plan_reasons_are_never_attributed_per_element(self):
        """An element the plan did not draw has NO named cause."""
        payload = R.live_frame(("живая", "план"), ops_by_id={},
                               drawn=set(), datums=set(), bodied=set(),
                               refused={}, no_body_ops={}, whole=True)
        self.assertIn("до пяти примеров", payload["plan_reason_ru"])


class AccumulationIsIdempotent(unittest.TestCase):
    """THE TEST REFUTING A DEFECT FOUND BY ITS OWN MEASUREMENT.

    The frame-cost measurement ran the same delta seven times (taking
    the minimum by time), and the accumulator summed it seven times
    over: 6 148 operations where there are 6 021. The panel repeats the
    request on retry, on a lost response, and with two tabs on one
    session.

    The inflated census CONVERGES WITH ITSELF — the buckets and the
    denominator grow together — so the convergence law does not catch it.
    """

    def _twice(self):
        key = ("живая", "повтор")
        R.live_reset(key)
        args = dict(ops_by_id={"p1/w0": "create_wall"}, drawn={"p1/w0"},
                    datums=set(), bodied=set(), refused={}, no_body_ops={})
        R.live_frame(key, whole=True, **args)
        return R.live_frame(key, whole=False, **args)

    def test_the_same_frame_twice_counts_once(self):
        out = self._twice()
        self.assertEqual(out["ops"], 1)
        self.assertEqual(sum(out["buckets"].values()), 1)

    def test_the_repeat_is_counted_and_named(self):
        """Silently letting a repeat through would mean hiding the fact
        that the panel is asking the same thing twice."""
        out = self._twice()
        self.assertEqual(out["repeats"], 1)
        self.assertTrue(out["repeats_ru"])

    def test_a_whole_scene_resets_the_accumulation(self):
        key = ("живая", "обнуление")
        R.live_reset(key)
        args = dict(ops_by_id={"p1/w0": "create_wall"}, drawn={"p1/w0"},
                    datums=set(), bodied=set(), refused={}, no_body_ops={})
        R.live_frame(key, whole=True, **args)
        out = R.live_frame(key, whole=True, **args)
        self.assertEqual(out["ops"], 1)
        self.assertEqual(out["repeats"], 0)


class TheLiveCostStaysOffTheFrame(unittest.TestCase):
    """Measured 11.08: the whole 800 ms with the cross-check versus
    787-791 without; the DELTA 2.0 ms with the cross-check versus
    1.9-2.0 without. The live cross-check travels in the frame precisely
    because both censuses are already built there; for a decompile it
    cost their sum (0.99 s and 4.9 s) and so it lives as a separate
    entry point."""

    def test_the_live_path_does_not_rebuild_either_census(self):
        import inspect
        source = inspect.getsource(R.live_frame)
        self.assertNotIn("preview_snapshot", source)
        self.assertNotIn("build_from_decompile", source)
        self.assertNotIn("build_program_preview", source)

    def test_context_datums_are_excluded_from_the_denominator(self):
        """Datums travel with EVERY delta and get a new address each
        time. Found by its own measurement: `neither` grew by one with
        every delta, and over a three-hour session would have
        accumulated hundreds of ghosts."""
        import inspect
        from kir.viewer import live_scene as L
        source = inspect.getsource(L.scene_from_programs)
        self.assertIn("context_ids", source)
        self.assertIn("oid not in context_ids", source)
