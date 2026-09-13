"""RECONCILING TWO CENSUSES OF ONE BUILDING — the plan's and the volume's.

`preview` keeps its own census of the sheet (`OmitReason`, `ApproxReason`,
`AnomalyReason`); the viewer keeps its own census of bodies (accuracy classes,
honesty axes, classes of bodilessness reasons). Both are internally
consistent. An engineer looks at them side by side and assumes it is one
building.

════════════════════════════════════════════════════════════════════════════
MEASURED 11.08.2026 — AND IT CANCELED THE TASK "MERGE THE CENSUSES INTO ONE"
════════════════════════════════════════════════════════════════════════════
`sob62_fas_r23_v19`: the plan draws 4 285 of 5 218; the volume gives a body to
4 218 of 5 001. Intersection 3 948, plan-only 337, volume-only 270.

`snowdon_plumb_v4`: the plan 26 258 of 32 185; the volume 31 904 of 32 063.
Intersection 26 203, plan-only 55, **volume-only 5 701**.

The discrepancies were examined by name, and all three classes turned out to
be LEGITIMATE — that is, the censuses answer DIFFERENT questions, not one
question two different ways:

1. **DATUMS, ANNOTATIONS, ROOMS, SPACES** — 217 on the facade, 122 on the
   engineering model. The plan draws them (an axis is needed on the plan),
   the volume declares `not_eligible` (they have no body). The questions
   differ: "is this visible on the slice" versus "does this have a body".

2. **VERTICAL RUNS** — 5 506 pipes and 195 ducts in `snowdon_plumb_v4`, that
   is, **21 % of the building**. The volume draws them as capsules, the plan
   honestly declares `degenerate`: a riser projects to a point, and there is
   nothing to draw it with on a slice. This is a property of the PROJECTION,
   not a loss.

3. **WALLS WITH AN AXIS BUT NO BOUNDING BOX** — 291 of 2 360 (12.3 %) on the
   facade. The measurement is exact: all 291 are missing `bbox_min_mm`/
   `bbox_max_mm` in L0, while the axis in `curve.index.json` exists for all
   291. The plan draws them as a line tagged `thickness_unknown`;
   `hulls.KIND_TABLE` allows a wall only `bbox` (the containment lock is not
   open — 97 violations across 800 real walls), so there will be no hull. And
   here too the questions differ: "can I draw a line" versus "can I BOUND a
   body". An axis with no thickness does not contain a wall, and a hull is
   required to contain one.

**CONCLUSION: THE CENSUSES SHOULD NOT BE MERGED, AND DOING SO WOULD BE A
LIE.** A common denominator would force one of them to answer the other's
question: either the plan would start counting risers as a loss, or the
volume would count datums that way. Both would end up lying for the sake of
agreement.

════════════════════════════════════════════════════════════════════════════
WHAT IS NEEDED INSTEAD, AND WHAT DOES NOT EXIST AT ALL TODAY
════════════════════════════════════════════════════════════════════════════
The DIFFERENCE needs to be NAMED. Today it is stated nowhere: the engineer
sees 291 walls on the plan that are not in the volume, and 5 506 pipes in the
volume that are not on the plan, and no screen reports that the other one is
showing something different.

This module is not a third census. It computes nothing on its own: it asks
both and sorts EVERY element into exactly one of four baskets, taking the
reason from whichever census named it. The convergence law is the same as for
both parents, and it is checked, not promised:

    union = both + plan_only + volume_only + neither

A discrepancy here is an error, not a warning: a reconciliation in which an
element lands in no basket at all hides exactly the case it was written for.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ("RECONCILE_SCHEMA", "Bucket", "Reconciliation", "reconcile_run")

RECONCILE_SCHEMA = "kir-viewer-reconcile/1"


class Bucket:
    """Four baskets. The list is closed: an element that lands in none of
    them is a silent drop, and the census must catch it."""

    BOTH = "both"
    PLAN_ONLY = "plan_only"
    SCENE_ONLY = "scene_only"
    NEITHER = "neither"


BUCKET_RU: dict[str, str] = {
    Bucket.BOTH: "видно и на плане, и в объёме",
    Bucket.PLAN_ONLY: ("нарисовано планом, тела в объёме НЕТ — на двух экранах "
                       "разное здание, и вот причина"),
    Bucket.SCENE_ONLY: ("есть тело в объёме, планом НЕ нарисовано — обычно "
                        "стояк (в срез проецируется точкой) или элемент без "
                        "этажа"),
    Bucket.NEITHER: "ни один экран этого не показывает",
}


@dataclass
class Reconciliation:
    """Sorting every element into exactly one basket, plus reasons and
    censuses."""

    run: str = ""
    buckets: dict[str, int] = field(default_factory=dict)
    #: Basket -> category -> how many. The category here is not decoration:
    #: 291 walls and 46 axes landed in `plan_only` for DIFFERENT reasons, and
    #: merging them into one number would mean hiding the one that is
    #: fixable.
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    #: Basket -> named reason -> how many. The reason is taken from whichever
    #: census named it: from the volume for `plan_only`, from the plan for
    #: `scene_only`.
    by_reason: dict[str, dict[str, int]] = field(default_factory=dict)
    examples: dict[str, list[str]] = field(default_factory=dict)
    plan_census: dict[str, Any] = field(default_factory=dict)
    scene_census: dict[str, Any] = field(default_factory=dict)
    union: int = 0
    elapsed_ms: float = 0.0
    note: str = ""

    def balanced(self) -> bool:
        """The RECONCILIATION's convergence. An element that lands in no
        basket is exactly the case the reconciliation was written for."""
        return sum(self.buckets.values()) == self.union

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RECONCILE_SCHEMA,
            "run": self.run,
            "union": self.union,
            "buckets": dict(sorted(self.buckets.items())),
            "bucket_ru": BUCKET_RU,
            "by_category": {k: dict(sorted(v.items(), key=lambda kv: -kv[1]))
                            for k, v in sorted(self.by_category.items())},
            "by_reason": {k: dict(sorted(v.items(), key=lambda kv: -kv[1]))
                          for k, v in sorted(self.by_reason.items())},
            "examples": {k: v[:5] for k, v in sorted(self.examples.items())},
            "plan_census": self.plan_census,
            "scene_census": self.scene_census,
            "balanced": self.balanced(),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "note": self.note,
            "verdict_ru": (
                "переписи НЕ СВОДЯТСЯ в одну намеренно: план отвечает «видно "
                "ли это на срезе», объём — «есть ли у этого тело». Общий "
                "знаменатель заставил бы одну из них считать потерей то, что "
                "потерей не является"),
        }


def reconcile_run(run: str) -> Reconciliation:
    """Reconcile the plan and the volume of one decompile. Reads both
    sources, has zero of its own.

    THE COST IS NAMED: BOTH censuses are built in full, so the
    reconciliation costs the sum of their costs (facade — 0.8 s plan + 0.3 s
    volume). That is why it lives as a SEPARATE endpoint and does not travel
    in every scene frame: the scene instead honestly says the reconciliation
    was not requested.
    """
    from kir.clash import snapshot as S
    from kir import preview as P
    from kir.viewer.scene import run_root

    started = time.perf_counter()
    base = run_root() / run
    if not base.exists():
        raise FileNotFoundError(f"разбора {run!r} нет в {run_root()}")

    building = P.preview_snapshot(base)
    plan_drawn: dict[str, str] = {}
    for sheet in building.plans:
        for element in tuple(sheet.elements) + tuple(sheet.datums):
            plan_drawn[str(element.element_id)] = element.category

    snap = S.build_from_decompile(base)
    scene_bodies = {record.source_id: record.category for record in snap.records}
    scene_refusal = {refusal.source_id: (refusal.reason or refusal.bucket)
                     for refusal in snap.refusals}
    scene_category = dict(scene_bodies)
    for refusal in snap.refusals:
        scene_category.setdefault(refusal.source_id, refusal.category)

    # PER-ELEMENT PLAN REASONS DO NOT BELONG TO IT. `PreviewCensus` groups
    # what was omitted by (reason, category) and keeps only up to five
    # examples, so there is nothing with which to say about a SPECIFIC
    # element "the plan omitted it for this reason". Attributing a reason to
    # it by category would be a guess dressed up as the element's own, and a
    # guess on an element reads as a measurement. So for `scene_only` a
    # DISTRIBUTION of plan reasons is published, and on the element itself
    # there is only the fact.
    plan_reason_totals: dict[str, int] = {}
    for group in building.census.omitted:
        key = f"{group.reason.value}/{group.category}"
        plan_reason_totals[key] = plan_reason_totals.get(key, 0) + group.count

    result = Reconciliation(run=run)
    union = set(plan_drawn) | set(scene_category)
    result.union = len(union)
    for element_id in union:
        in_plan = element_id in plan_drawn
        in_scene = element_id in scene_bodies
        bucket = (Bucket.BOTH if in_plan and in_scene
                  else Bucket.PLAN_ONLY if in_plan
                  else Bucket.SCENE_ONLY if in_scene
                  else Bucket.NEITHER)
        result.buckets[bucket] = result.buckets.get(bucket, 0) + 1
        category = plan_drawn.get(element_id) or scene_category.get(element_id, "?")
        cats = result.by_category.setdefault(bucket, {})
        cats[category] = cats.get(category, 0) + 1
        if bucket in (Bucket.PLAN_ONLY, Bucket.NEITHER):
            # The reason is given by the VOLUME: it refused by name, and
            # these are its own words.
            reason = scene_refusal.get(element_id, "объём про этот элемент молчит")
            reasons = result.by_reason.setdefault(bucket, {})
            reasons[reason] = reasons.get(reason, 0) + 1
        if len(result.examples.setdefault(bucket, [])) < 5:
            result.examples[bucket].append(element_id)

    # Plan reasons — as a DISTRIBUTION, not on the element (see above).
    result.by_reason[Bucket.SCENE_ONLY] = dict(plan_reason_totals)
    result.plan_census = building.census.to_dict()
    result.scene_census = snap.census.as_dict()
    result.note = (
        "причины для `scene_only` даны РАСПРЕДЕЛЕНИЕМ по всему листу: "
        "`PreviewCensus` группирует опущенное и хранит до пяти примеров, "
        "поэтому поимённой причины плана у элемента нет, и придумывать её "
        "нельзя")
    result.elapsed_ms = (time.perf_counter() - started) * 1000.0
    return result


# ═══════════════════════════════════════════════════════════════════════════
# LIVE-SESSION RECONCILIATION — a discrepancy the engineer looks at for THREE
# HOURS
# ═══════════════════════════════════════════════════════════════════════════
#
# The decompile is looked at when the archive is opened. The live scene is
# looked at for the whole session, and the discrepancy there is of A
# DIFFERENT NATURE: bodies depend on a snapshot of the open model's types,
# the plan does not.
#
# MEASURED 11.08.2026, 300 programs / 6 000 elements (14 pipes and 6 walls
# per program), through the same tract as the scene:
#
#     snapshot PRESENT: both 4 200, plan-only 1 800   (walls — the hull lock)
#     snapshot ABSENT:  plan-only 6 000, both 0       ← plan FULL, volume EMPTY
#
# The second line is exactly the outcome the whole marathon was untangling
# "the instrument was silent" from "there is no intersection" for: both
# sides are honest on their own, the plan shows the whole building, the
# volume shows nothing, and no one says this is the same building.
#
# THE DENOMINATOR OF THE LIVE RECONCILIATION IS ALL WRITTEN OPERATIONS, not
# the ones that produced something. Otherwise the fourth basket is empty BY
# CONSTRUCTION: an element that no one created will not land in the union of
# "drawn and hulled". Measured on a five-operation program: by the operation
# denominator, "neither" is 4 of 5 (`create_level`, `create_grid`,
# `create_room`, `set_param`).
#
# DATUMS COUNT AS DRAWN. `preview` keeps them in a separate list
# (`FloorPlan.datums`), and not looking there would mean declaring an axis
# invisible exactly where the plan shows it.
#
# COST. Both censuses in the live tract are ALREADY BUILT —
# `scene_from_programs` builds both `build_program_preview` and
# `bundle_elements` + `build_from_elements` in one call. What is left for the
# reconciliation is the sorting: measured at 5.5 ms on 6 000 elements against
# 213 ms for the bundle and 84 ms for the preview, which are paid anyway. On
# the DELTA path a frame builds only the new programs, so the sorting there
# is O(what's new). That is why the live reconciliation travels IN THE FRAME,
# not as a separate endpoint: for a decompile it cost the sum of two
# censuses, here it costs almost nothing.

LIVE_BUCKET_RU: dict[str, str] = {
    Bucket.BOTH: "видно и на плане, и в объёме",
    Bucket.PLAN_ONLY: ("нарисовано планом, тела НЕТ. Чаще всего это значит, что "
                       "нет снимка типов открытой модели: толщина стены и "
                       "диаметр трубы живут в ТИПЕ. Чинит ОПЕРАТОР — открыв "
                       "модель, — а не автор программы"),
    Bucket.SCENE_ONLY: ("тело есть, планом не нарисовано: обычно стояк "
                        "(в срез проецируется точкой) или элемент без этажа"),
    Bucket.NEITHER: ("операция написана, а элемента нет ни на одном экране: "
                     "либо она тела не создаёт вовсе (правка, датум, "
                     "помещение), либо его нечем построить"),
}


@dataclass
class _LiveTally:
    """Accumulation of baskets across a session's frames. A whole scene
    resets it, a tail accumulates.

    IDEMPOTENCE IS MANDATORY, AND THIS WAS FOUND BY ITS OWN MEASUREMENT. A
    measurement of frame cost ran THE SAME delta seven times in a row (to
    take the minimum time), and the accumulation added it up seven times:
    6 148 operations where there are 6 021. In real life this is not a
    contrived case — the panel repeats a request on retry, on a lost
    response, and with two tabs on one session.

    An inflated census CONVERGES WITH ITSELF (the baskets and the
    denominator grow together), so the convergence law does not catch it —
    exactly the shape of defect we have been hunting all through the
    marathon. It is fixed with a set of already-counted addresses: they are
    unique within a session by construction (`bundle_oid`), so a repeat is
    distinguishable from novelty exactly, not by guesswork.
    """

    buckets: dict[str, int] = field(default_factory=dict)
    by_reason: dict[str, dict[str, int]] = field(default_factory=dict)
    ops: int = 0
    frames: int = 0
    #: Addresses already counted into the baskets. The cost is about 60 KB
    #: per session of 6 000 elements; the cost of getting it wrong is a
    #: census that lies and converges.
    counted: set = field(default_factory=set)
    repeats: int = 0


_LIVE: dict[tuple[str, str], _LiveTally] = {}
#: We remember as many sessions as the showroom does: two different caps on
#: one and the same session would drift apart, and one of them would
#: silently stop working.
_LIVE_MAX = 8


def live_reset(key: tuple[str, str]) -> None:
    _LIVE[key] = _LiveTally()
    while len(_LIVE) > _LIVE_MAX:
        _LIVE.pop(next(iter(_LIVE)))


def live_frame(key: tuple[str, str], *, ops_by_id: dict, drawn: set,
               datums: set, bodied: set, refused: dict, no_body_ops: dict,
               whole: bool) -> dict[str, Any]:
    """Sort the elements of ONE frame and return the session's ACCUMULATED
    reconciliation.

    `whole=True` resets the accumulation: a whole scene replaces everything
    the panel had held before it — by the same law as the signature of what
    is shown.

    THE REASON IS TAKEN ONLY WHERE IT EXISTS, and these are different
    sources:

      * for an element the volume refused, the reason is NAMED — the hull
        builder named it (`refused`);
      * for an operation that created no element at all, the reason is tied
        to THE OPERATION'S NAME (`no_body` is keyed by name), and this is
        not a guess: "this op creates no body" is a property of the
        operation, not of its instance. And that is how it is labeled;
      * for an element the PLAN did not draw, there is NO named reason:
        `PreviewCensus` groups what was omitted and keeps up to five
        examples. Attributing it by category would be a guess dressed up as
        the element's own.
    """
    if whole or key not in _LIVE:
        live_reset(key)
    tally = _LIVE[key]
    shown_by_plan = drawn | datums
    for element_id, op_name in ops_by_id.items():
        if element_id in tally.counted:
            # A REPEAT IS NOT COUNTED, BUT IT IS NAMED. Skipping it silently
            # would mean hiding the fact that the panel is re-asking for the
            # same thing.
            tally.repeats += 1
            continue
        tally.counted.add(element_id)
        in_plan = element_id in shown_by_plan
        in_scene = element_id in bodied
        bucket = (Bucket.BOTH if in_plan and in_scene
                  else Bucket.PLAN_ONLY if in_plan
                  else Bucket.SCENE_ONLY if in_scene
                  else Bucket.NEITHER)
        tally.buckets[bucket] = tally.buckets.get(bucket, 0) + 1
        if bucket in (Bucket.PLAN_ONLY, Bucket.NEITHER):
            reason = refused.get(element_id)
            if reason is None and op_name in no_body_ops:
                reason = f"операция {op_name} тела не создаёт"
            tally.by_reason.setdefault(bucket, {})
            key_r = reason or "причина не названа ни одной переписью"
            tally.by_reason[bucket][key_r] = (
                tally.by_reason[bucket].get(key_r, 0) + 1)
    tally.ops = len(tally.counted)
    tally.frames += 1

    return {
        "schema": RECONCILE_SCHEMA,
        "source": "live",
        "available": True,
        "buckets": dict(sorted(tally.buckets.items())),
        "bucket_ru": LIVE_BUCKET_RU,
        "by_reason": {k: dict(sorted(v.items(), key=lambda kv: -kv[1])[:6])
                      for k, v in sorted(tally.by_reason.items())},
        "ops": tally.ops,
        "frames": tally.frames,
        "repeats": tally.repeats,
        "repeats_ru": ("адресов, пришедших повторно и НЕ посчитанных заново: "
                       "панель переспрашивает один и тот же срез"),
        # THE SAME CONVERGENCE LAW APPLIES. An operation that lands in no
        # basket is a silent drop, and the reconciliation must catch it, not
        # ride it out.
        "balanced": sum(tally.buckets.values()) == tally.ops,
        "denominator_ru": ("знаменатель — ВСЕ написанные операции, а не только "
                           "те, у кого что-то получилось: иначе четвёртая "
                           "корзина пуста по построению"),
        "plan_reason_ru": ("причин плана поимённо нет: `PreviewCensus` "
                           "группирует опущенное и хранит до пяти примеров"),
    }
