"""WHAT TO DO — resolution proposals, carried through to the screen in full.

The viewer shows the building, shows what we don't know about it, shows
what this turn contributed, and does not let you send to Revit what the
engineer never saw. One last link was missing: it showed the PROBLEM and
did not show the WAY OUT.

`kir/clash/resolve.py` computes the way out. This module READS it (not a
line is written in `clash`) and carries FOUR parts through to the screen,
none of which can be dropped.

════════════════════════════════════════════════════════════════════════════
MEASURED 11.08.2026 — TWO BUILDINGS, TWO OPPOSITE PROFILES
════════════════════════════════════════════════════════════════════════════

| | `sob62_fas_r23_v19` | `snowdon_plumb_v4` |
|---|---|---|
| shells | 4 218 | 31 904 |
| findings (detect) | 27 041 in 1.6s | 35 712 in 18.8s |
| of which overlaps | 19 239 | 35 633 |
| **cost per pair** | **29.1 ms** | **372.4 ms** |
| recommendations | `review` 286, `assembly_relation` 114 | `move` 300 |
| minimality | `minimal_over_searched_directions` 100 % | **`separating_only` 100 %** |
| certified | 400 of 400 | 300 of 300 |
| move is legal | 289 of 400 | 300 of 300 |
| distance | median 100 mm, max 1 517 | median 7.9 mm, max 57.1 |

TWO CONCLUSIONS, AND BOTH DECIDE THIS MODULE'S SHAPE.

**THE FIRST — COST.** 19 239 × 29.1 ms = **9.3 minutes**; 35 633 × 372.4 ms
= **3.7 hours**. This is not "expensive for a frame", it is expensive for
a single click. So proposals are computed ONLY on request, ONLY for a
named area, and ONLY up to a named ceiling, and the scene honestly says
that they were not computed. The same boundary already drawn twice: for
the live check the cost is zero and it rides in the frame, for the
decompile check the cost is in seconds and it is a separate entry point,
here the cost is in hours — and it is a separate entry point WITH A
CEILING.

**THE SECOND — MINIMALITY IS NOT DECORATION.** On the engineering building
ALL 300 of 300 proposals have `separating_only`: the exact path does not
apply to a capsule versus a union of parts, the move DOES SEPARATE and
this was verified by an actual move, but it is not declared minimal even
along its own direction. Showing "move the pipe by 7.9 mm" without this
caveat would mean passing off an estimate as the optimum — for 100% of
this building's proposals. That is why `minimality` and its explanation
ride with EVERY proposal, not in a help page.

════════════════════════════════════════════════════════════════════════════
FOUR PARTS, AND NONE REDUCES TO ANOTHER
════════════════════════════════════════════════════════════════════════════
1. **THE NUMBER** — the element, the direction, the distance. Given
   whenever the geometry gives it, regardless of the sides' classes.
2. **THE RECOMMENDATION** — `move` | `review` | `verify_duplicate` |
   `assembly_relation`. Four DIFFERENT actions; collapsing them into one
   word would mean saying "move it" where the real answer is "this is a
   joint, not a clash".
3. **MINIMALITY** — "the smallest among the directions searched" versus
   "it separates, but is not the smallest". It rides together with the
   number of directions searched and their origin:
   `minimal_over_searched_directions` without a denominator is a word
   without a number.
4. **CERTIFIED STATUS** — the postcondition was verified by an ACTUAL
   move, not merely asserted. An engineer being told to move a column is
   entitled to know whether the proposal was checked.

════════════════════════════════════════════════════════════════════════════
A FAILURE TO BUILD A PROPOSAL IS DISTINGUISHABLE FROM "NO NEED TO MOVE"
════════════════════════════════════════════════════════════════════════════
`resolve` returns two different refusals, and they must not be merged:

  * `not_overlapping` — the pair does not intersect. There is NO NEED to
    move it, and that is the answer;
  * `no_certified_direction` — the pair intersects, and we found no
    separating move. This is OUR OWN powerlessness, not a property of the
    building.

The first is green, the second is red, and on the screen they are
different words. No arrow is drawn in either case: showing a way out that
does not exist is worse than showing nothing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ("ADVICE_SCHEMA", "COST_PER_PAIR_MS", "DEFAULT_LIMIT", "MAX_LIMIT",
           "REFUSAL_RU", "Advice", "advise_run", "unavailable")

ADVICE_SCHEMA = "kir-viewer-advice/1"

#: The measured cost of one pair, ms. Published so that the ceiling is
#: justified by a number, not by taste.
#:
#: TWO MEASUREMENTS ON THE SAME BUILDING, AND THE SECOND OVERTURNED THE
#: FIRST CEILING. A random sample of `snowdon_plumb_v4` gave 372.4 ms per
#: pair, and the ceiling was set from it. But the area is chosen BY DEPTH
#: (computing the shallow ones first means computing the wrong thing), and
#: deep pairs cost more: the same sample, sorted by depth, gave **977.1
#: ms**. By choosing what matters most, we also choose the slowest — and a
#: ceiling computed from the average would have missed by a factor of 2.6.
COST_PER_PAIR_MS = {
    "sob62_fas_r23_v19": 16.6,          # 750 pairs, sorted by depth
    "snowdon_plumb_v4": 977.1,          # 150 pairs, sorted by depth
}

#: The worst measured cost. The ceiling is computed FROM IT, not from the
#: average: the area is chosen by depth, that is, deliberately from the
#: expensive end.
WORST_PAIR_MS = 977.1

#: How many seconds ONE CLICK is allowed to take. More than that, and a
#: button stops being a button.
PRESS_BUDGET_S = 60.0

#: The ceiling on pairs per request. Not a number pulled from thin air:
#: 60s / 977.1 ms = 61.
DEFAULT_LIMIT = 25
MAX_LIMIT = int(PRESS_BUDGET_S * 1000.0 / WORST_PAIR_MS)

REFUSAL_RU: dict[str, str] = {
    # NO NEED TO MOVE IT — this is an ANSWER, not powerlessness.
    "not_overlapping": ("пара не пересекается: двигать не надо. Это ОТВЕТ, а "
                        "не отказ. Замер 11.08: все 180 отказов на двух "
                        "зданиях — этот, и все до одного пришли от КАСАНИЙ"),
    # OUR OWN POWERLESSNESS — the pair intersects, and we found no move.
    "no_certified_direction": ("пара ПЕРЕСЕКАЕТСЯ, но разводящего хода не "
                               "найдено ни для одной стороны: ни одно "
                               "просмотренное направление не прошло проверку "
                               "переносом. Это наше бессилие, а не свойство "
                               "здания. НА ЭТОМ КОРПУСЕ НЕ НАБЛЮДАЛСЯ НИ РАЗУ "
                               "(0 из 720 предложений), и различие держится "
                               "именно поэтому: пустая названная причина "
                               "отличима от несуществующей"),
}

#: Which refusals mean "all is well" and which mean "we could not". The
#: list is closed: a new refusal not assigned to either side must be
#: caught by a test, rather than riding to the screen as neutral gray.
BENIGN_REFUSALS = frozenset({"not_overlapping"})


def unavailable(reason: str) -> dict[str, Any]:
    """There are no proposals — and WHY IS STATED. An empty list and an
    uncomputed list read the same only if you stay silent."""
    return {"schema": ADVICE_SCHEMA, "available": False, "reason": reason,
            "proposals": [], "considered": 0, "truncated": 0}


@dataclass
class Advice:
    run: str = ""
    proposals: list[dict] = field(default_factory=list)
    refusals: list[dict] = field(default_factory=list)
    overlaps_total: int = 0
    considered: int = 0
    truncated: int = 0
    by_recommendation: dict[str, int] = field(default_factory=dict)
    by_minimality: dict[str, int] = field(default_factory=dict)
    certified: int = 0
    legal: int = 0
    elapsed_ms: float = 0.0
    detect_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ADVICE_SCHEMA,
            "available": True,
            "run": self.run,
            "proposals": self.proposals,
            "refusals": self.refusals,
            "overlaps_total": self.overlaps_total,
            "considered": self.considered,
            # TRUNCATION IS NAMED WITH A NUMBER. A list of fifty proposals
            # and a list where fifty are out of nineteen thousand are
            # different things, and without this line the second reads as
            # the first.
            "truncated": self.truncated,
            "truncated_ru": (
                f"посчитаны {self.considered} пар из {self.overlaps_total}: "
                f"остальные {self.truncated} НЕ рассматривались — счёт одной "
                f"пары стоит 29–372 мс, и полное здание это часы"
                if self.truncated else ""),
            "by_recommendation": dict(sorted(self.by_recommendation.items())),
            "by_minimality": dict(sorted(self.by_minimality.items())),
            "certified": self.certified,
            "legal": self.legal,
            "certified_ru": ("ход проверен НАСТОЯЩИМ переносом и повторным "
                             "замером, а не заявлен"),
            "refusal_ru": REFUSAL_RU,
            "benign_refusals": sorted(BENIGN_REFUSALS),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "detect_ms": round(self.detect_ms, 1),
        }


def advise_run(run: str, *, limit: int = DEFAULT_LIMIT,
               element_id: str = "") -> Advice:
    """Proposals for a decompiled model: the area is either one element, or
    the deepest overlaps. Computes ONLY up to the ceiling and states how
    many were not computed.

    THE AREA IS MANDATORY BECAUSE OF COST, NOT TASTE. 19 239 façade
    overlaps at 29.1 ms — 9.3 minutes; 35 633 engineering overlaps at
    372.4 ms — 3.7 hours. So it is either "around this element" or "the
    deepest ones first".
    """
    from kir.clash import detect as D
    from kir.clash import resolve as RS
    from kir.clash import snapshot as S
    from kir.viewer.scene import run_root

    started = time.perf_counter()
    base = run_root() / run
    if not base.exists():
        raise FileNotFoundError(f"разбора {run!r} нет в {run_root()}")
    limit = max(1, min(int(limit), MAX_LIMIT))

    snap = S.build_from_decompile(base)
    t0 = time.perf_counter()
    report = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    detect_ms = (time.perf_counter() - t0) * 1000.0

    by_id = {record.source_id: record for record in snap.records}
    overlaps = [f for f in (report.get("findings") or [])
                if f.get("hull_relation") == "overlap"]
    if element_id:
        overlaps = [f for f in overlaps
                    if str((f.get("a") or {}).get("source_element_id")) == element_id
                    or str((f.get("b") or {}).get("source_element_id")) == element_id]
    # SORTED BY DEPTH, not by address: if only part can be computed, the
    # deepest ones must be computed. Sorting by address would choose the
    # area alphabetically, that is, by nothing at all.
    overlaps.sort(key=lambda f: -float(f.get("hull_overlap_depth_mm") or 0.0))

    advice = Advice(run=run, overlaps_total=len(overlaps), detect_ms=detect_ms)
    chosen = overlaps[:limit]
    advice.considered = len(chosen)
    advice.truncated = len(overlaps) - len(chosen)

    hood = RS.Neighbourhood(snap.records)
    for finding in chosen:
        a = by_id.get(str((finding.get("a") or {}).get("source_element_id")))
        b = by_id.get(str((finding.get("b") or {}).get("source_element_id")))
        if a is None or b is None:
            continue
        proposal = RS.propose(
            a, b, hood=hood, pair_kind=finding.get("pair_kind") or "interference",
            finding_id=finding.get("finding_id"),
            # 🔴 THE LAST CENTIMETER OF WIRE, 18.08.2026. This is exactly
            # where the label-based guess lived: the model path
            # (`clash_bundle` -> `clash_judgement`) had already been given
            # a declared host earlier, while THIS reader — the one the
            # DESIGNER sees — was calling `propose` without it and
            # dismissing findings via a 12-label-pair table. Measured on
            # two buildings: dismissals "without confirmation" went 62.2%
            # -> 27.1% and 83.3% -> 43.4%. Only `contradicts` (the data
            # OBJECTS) overturns the table; `absent` (the data STAYS
            # SILENT) leaves it untouched — the earlier "63.0% against the
            # data" was lumping these two different facts into one number.
            # It does not license a build: zero new "move it" directives
            # after the fix on both buildings — the pairs that came back
            # became `review`.
            hosted=snap.hosted)
        payload = proposal.as_dict()
        payload["depth_mm"] = round(
            float(finding.get("hull_overlap_depth_mm") or 0.0), 1)
        payload["pair_class"] = finding.get("pair_class")
        if proposal.chosen is None:
            # NO ARROW IS DRAWN. Showing a way out that does not exist is
            # worse than showing nothing; so the refusal rides into ITS OWN
            # list.
            payload["benign"] = proposal.refusal in BENIGN_REFUSALS
            payload["refusal_ru"] = REFUSAL_RU.get(
                proposal.refusal or "", "причина отказа не названа")
            advice.refusals.append(payload)
            continue
        # THE HUMAN-READABLE STRING IS TAKEN FROM THE RULE'S OWNER, not
        # assembled here: a home-grown wording would diverge from
        # `to_russian` at the very first verb refinement — and would
        # diverge silently.
        payload["ru"] = RS.to_russian(proposal)
        advice.proposals.append(payload)
        rec = proposal.recommendation
        advice.by_recommendation[rec] = advice.by_recommendation.get(rec, 0) + 1
        mini = proposal.chosen.minimality
        advice.by_minimality[mini] = advice.by_minimality.get(mini, 0) + 1
        advice.certified += int(bool(proposal.chosen.certified))
        advice.legal += int(bool(proposal.chosen.legal))

    advice.elapsed_ms = (time.perf_counter() - started) * 1000.0
    return advice
