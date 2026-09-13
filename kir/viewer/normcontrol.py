"""A NORM-CONTROL THAT NAMES WHAT IT DID NOT CHECK.

WHY THIS MODULE EXISTS. Not a single norm-control in the industry says
"this is what I didn't look at" — it presents findings, and a rule's
silence reads as cleanliness. Here everything is built for the opposite:
20 `HAB` rules, each unevaluated one carrying a REASON
(`RuleOutcome.reason`), and a report across three axes
(`design_check.axis_report`), where silence is printed LOUDER than
findings.

🔴 AND NOT A SINGLE LIVE ROUTE WAS HANDING THIS OUT. Measurement
20.08.2026: `axis_report`/`render_axis_report` have **ZERO** prod
consumers — only tests and the offline instrument `tools/axes_duel.py`.
The viewer has twelve routes (scene, live scene, reconciliation, advice,
compilability, federation clash) and NOT ONE about the verdict. That is,
a person who opened a building could not ask it anything.

WHAT IS NOT REBUILT HERE, AND THIS IS THE FILE'S MAIN PROPERTY:

    reading the parse       decompile.extract.L0JSONLReader
    the building from L0    design_check.spatial_model_from_l0
                            (ModelSource.PARSE)
    the verdict             design_check.check_design
    the three axes          design_check.axis_report
    the text                design_check.render_axis_report /
                            render_verdict_brief
    the cache               viewer.cache (the same one, with the KIND in
                            the key)

There isn't a single judgment of its own about the building here: a rule
that stays silent must stay silent in the report too — conjuring a
finding out of it would mean substituting the subject of the
measurement.

THE PRICE IS NAMED AS A NUMBER BECAUSE IT DECIDES THE DESIGN (measurement
20.08, this box, python 3.12.13, `KUKAI_CHECKER_V2=1`):

    sob62_r23_v5     L0  1.4 MB   read 0.18 + model 0.05 + verdict 0.50 = 0.74 s
    13A-RD-AR-K2_v33 L0 97.9 MB   read 10.6 + model 1.05 + verdict 11.0 = 22.7 s
                                   peak RSS 324 MB

Twenty-three seconds is not a route. That's why the response goes into
the viewer's cache, and the key carries the KIND (`normcontrol`) and the
state of `KUKAI_CHECKER_V2`.

🔴 AND RIGHT HERE THE CONDITION IS NAMED WITHOUT WHICH THIS PROMISE IS
FALSE. The cache only makes the first user pay IF the cache directory is
writable by whoever is answering. Measurement 20.08:
`/tmp/kir-scene-cache` is owned by `root` (entries from 11.08), while the
waves and the service run as other users — `store` swallows a
`PermissionError` into the `errors` counter, and two calls in a row give
`miss`/`miss` with `stored=0`. The cache looks like it's working and
caches nothing. That's why the route distinguishes "not found" from
"couldn't store" with a header, rather than staying silent: otherwise the
next person will measure the route's price and get the price of a cache
that NEVER HAPPENED. The flag in the key isn't there for completeness: it
CHANGES THE ANSWER — on the v1 path an empty model reads as valid, on v2
the same thing gives `NOT_EVALUATED`. A key that doesn't cover what
changes the answer would hand back yesterday's verdict.

WHAT THIS MODULE DOES NOT DO:

* It does NOT go to Revit. What is judged is the PARSE — an independent
  reading, not what the program declares; the source's kind travels in
  the response as the `source` field;
* It does NOT decide what counts as a violation, and does not move any
  thresholds. It is a mirror;
* It does NOT hand back emptiness instead of a refusal. No catalog, no
  `L0.jsonl`, the verdict didn't come together — that is a NAMED refusal
  (`NormControlUnavailable`), not an empty report: an empty report reads
  as "no violations," and that is the worst of the available untruths.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from kir import env  # noqa: E402
import pathlib
import time
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("CACHE_KIND", "REPORT_SCHEMA", "NormControlUnavailable",
           "cache_extra", "report_for_run")

#: Response schema. If the form changes, the kind of key must change too, or
#: the panel will get yesterday's format for today's decompile.
REPORT_SCHEMA = "kir-normcontrol/1"

#: THE KIND OF RESPONSE in the cache key. Not "scene": the cache stores bytes,
#: and two consumers with identical inputs would get each other's body.
CACHE_KIND = "normcontrol"


class NormControlUnavailable(RuntimeError):
    """The report is NOT ASSEMBLED, and the reason is named.

    A separate type, not an empty report: "0 rules spoke up" and "there was no
    one to ask" are different facts, and the second wearing the first's
    costume reads as a building with no violations.
    """


def cache_extra() -> tuple[str, ...]:
    """What changes the RESPONSE and is not visible from the decompile
    catalog.

    Today this is exactly one value — the state of `KUKAI_CHECKER_V2`. It is
    not cosmetic: under v1 an empty model passes as valid (`passed =
    len(blocking) == 0`), under v2 the same gives `NOT_EVALUATED` and a
    blocking `HAB000`. Without it the cache would hand back a verdict taken by
    a different judge.

    Read LIVE, not at import time: an edit on the service must take effect
    from the next request, by the same rule as `checker.flags`.
    """
    # 🔴 THE KEY MUST READ THE SAME THING THE CHECKER ITSELF READS
    # (28.08.2026). Reading only the old name, the key would not change from
    # `KIR_CHECKER_V2`, and a person who turned on v2 under the new name would
    # get a CACHED response computed under v1 — the wrong verdict, looking
    # like the right one.
    return (f"checker_v2={env.get('KIR_CHECKER_V2', '')}",
            f"schema={REPORT_SCHEMA}")


def _document(run_dir: pathlib.Path):
    """The decompile document. Existence is asked of the INSTRUMENT, not of
    the name.

    🔴 THIS USED TO BE `l0.exists()`, AND COMPRESSION BROKE IT — measured
    20.08.2026, after the owner turned on corpus compression (36 files in 6
    decompiles)::

        clash_final   raw missing, compressed present -> REFUSAL «нет L0.jsonl»
        sob62_r23_v5  raw present                      -> ok, 10 of 20 rules

    The cleaner presses SIX names, and `L0.jsonl` is the first of them; the
    reader (`L0JSONLReader`) understands compressed, but the GUARD IN FRONT OF
    IT does not. Hence an outcome worse than silence: the refusal sounded
    convincingly honest («здание не открывалось») and was at the same time a
    LIE — the building is lying right there, under `.gz`. A convincing untruth
    costs more than silence precisely because no one double-checks it.

    The name `snapshot_file_exists` carries the same authority the cleaner
    presses by; a check of its own — "is there a .gz lying next to it" —
    would be a second carrier of the same rule and would drift apart from it
    on the seventh name.
    """
    from kir.decompile.snapshot_io import snapshot_file_exists

    l0 = run_dir / "L0.jsonl"
    if not snapshot_file_exists(l0):
        raise NormControlUnavailable(
            f"у разбора {run_dir.name!r} нет L0.jsonl — читать нечего. Это не "
            f"«нарушений нет»: здание не открывалось")
    from kir.decompile.extract import L0JSONLReader

    reader = L0JSONLReader(l0)
    return dataclasses.replace(reader.metadata(),
                               elements=tuple(reader.iter_elements()))


def _axis_rows(verdict: Any) -> list[dict[str, Any]]:
    """Three axes as DATA. An axis carries three numbers, not one.

    "0 violations" and "no rule passed judgment" look identical on a real
    building and mean the opposite, so `judged`, `violated` and `silent`
    travel SEPARATELY, and `silent` carries the reason for each one.
    """
    from kir.design_check import axis_report

    rows: list[dict[str, Any]] = []
    for row in axis_report(verdict):
        rows.append({
            "axis": row.axis,
            "judged": list(row.judged),
            "violated": list(row.violated),
            "silent": [{"rule_id": rule_id, "reason": reason}
                       for rule_id, reason in row.silent],
            "subjects": row.subjects,
            "withheld": row.withheld,
            "findings": row.findings,
        })
    return rows


def report_for_run(run: str, run_dir: pathlib.Path) -> dict[str, Any]:
    """Report on the decompile's BUILDING. Expensive; call through the cache.

    Returns a dict, not text: the panel draws, the human reads `text_ru`, and
    the machine takes the fields. Both are needed — and the text is truncated
    by construction, so the silence lives in the FIELDS, and the text only
    retells them for the eye.
    """
    from kir import design_check as dc

    started = time.perf_counter()
    document = _document(run_dir)
    read_ms = (time.perf_counter() - started) * 1000.0

    try:
        model, witness = dc.spatial_model_from_l0(document, building_id=run)
        model_ms = (time.perf_counter() - started) * 1000.0 - read_ms
        verdict = dc.check_design(model, witness=witness)
    except NormControlUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — a foreign judge; the refusal must NAME it
        raise NormControlUnavailable(
            f"вердикт о {run!r} не собрался: {type(exc).__name__}: {exc}"
        ) from None
    verdict_ms = (time.perf_counter() - started) * 1000.0 - read_ms - model_ms

    coverage = verdict.report.coverage
    outcomes = list(getattr(coverage, "outcomes", ()) or ()) if coverage else []
    suspended = sorted(verdict.rules_suspended or ())
    silent = sorted(
        ({"rule_id": o.rule_id,
          "reason": str(o.reason or "ПРИЧИНА НЕ НАЗВАНА")}
         for o in outcomes
         if o.status.value != "evaluated" and o.rule_id not in set(suspended)),
        key=lambda row: row["rule_id"])

    profile = verdict.profile
    suspended_rows = []
    for rule_id in suspended:
        reason = ""
        if profile is not None:
            try:
                reason = str(profile.suspension_reason(rule_id) or "")
            except Exception:  # noqa: BLE001 — the profile need not know every code
                reason = ""
        suspended_rows.append({"rule_id": rule_id,
                               "reason": reason or "причина не названа профилем"})

    return {
        "schema": REPORT_SCHEMA,
        "run": run,
        # THE KIND OF SOURCE, not decoration: "independent reading" and "the
        # program's self-check of what it declared" are different claims about
        # the same word "verdict".
        "source": verdict.source.value,
        "doc_name": getattr(witness, "doc_name", "") or "",
        "verdict": (verdict.report.verdict.value
                    if verdict.report.verdict is not None else ""),
        "counts": dict(witness.counts or {}),
        "rules_total": verdict.rules_total,
        "rules_evaluated": verdict.rules_applied,
        # TWO KINDS OF SILENCE, KEPT APART. What the stage removed cannot be
        # fixed; what starves for input carries THE ADDRESS OF THE WORK in its
        # reason. One field for both would mean handing the human a word
        # instead of a distinction.
        "rules_suspended": suspended_rows,
        "rules_silent": silent,
        "blocking": sorted({v.rule_id for v in verdict.report.blocking}),
        "warnings": sorted({v.rule_id for v in verdict.report.warnings}),
        "axes": _axis_rows(verdict),
        "text_ru": dc.render_axis_report(verdict),
        "verdict_ru": dc.render_verdict_brief(verdict),
        "timing_ms": {"read": round(read_ms, 1),
                      "model": round(model_ms, 1),
                      "verdict": round(verdict_ms, 1)},
    }


def report_bytes(run: str, run_dir: pathlib.Path) -> bytes:
    return json.dumps(report_for_run(run, run_dir),
                      ensure_ascii=False).encode("utf-8")
