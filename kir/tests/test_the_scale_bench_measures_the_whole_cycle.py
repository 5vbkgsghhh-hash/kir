# -*- coding: utf-8 -*-
"""The scale instrument measures the WHOLE cycle, not a single read (mandate F10/Q02).

🔴 WHY THIS TEST EXISTS AT ALL. Before 07.09.2026, the scale measurement
lived OUTSIDE the repository
(`.work/audit-fable-20260906/geo-loop/acceptance/run.py`), so "10,000
bodies in 468 s" could neither be remeasured by another pair of hands, nor
be broken by a product change: the tree's gates never saw this number.
Here the scenario has moved INTO THE REPOSITORY and is guarded by a small
run: N=200, K=5.

What is checked here — and what is NOT checked here. What is checked is
the SHAPE of the report and its three premises: bodies participate, an
edit's latency does not grow with the edit's number, asset reads per edit
do not grow with the edit's number. The thresholds are taken FROM THE
07.09.2026 MEASUREMENT on this tree (see `docs/SCALE_RU.md`), with
margin. What is NOT checked is the absolute time: that is a property of
the box and the load, and a threshold on it would be a lie about a
different subject.

🔴 "O(1) READS PER EDIT" IS FALSE, AND THE TEST PINS THE MEASURED VALUE,
NOT THE DESIRED ONE. Measurement: one local edit (shifting ONE body)
reads **3·N asset rows** (N=200 -> 600–604 SELECTs) and makes **(2+k)·N
calls** to `_read_asset`, where k is the edit's number. Only the ROW
COUNT stays constant in k; the call count grows linearly. The pin is set
on what is true (the row count does not grow with k and does not exceed
4·N+64), and the growth in calls is named, with an address, in
`docs/SCALE_RU.md` — it is not this test's job to fix it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "tools" / "scale_bench.py"

BODIES = 200
EDITS = 5
#: The threshold from the 07.09.2026 measurement (tree f1e394e): asset rows
#: per edit 600, 601, 602, 603, 604 at N=200, i.e. 3·N + k. Margin — up to
#: 4·N + 64.
ROW_READS_CEILING = 4 * BODIES + 64
#: The ratio of the halves by edit latency: measured 1.11 at K=5. The
#: threshold 2.0 is exactly the one the mandate names ("does not grow by
#: more than 2×").
GROWTH_CEILING = 2.0

PHASES = ("build", "save", "analyze", "edits", "history", "reopen")


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    """A SINGLE run of the instrument on a small N. The test has no other source of numbers."""
    pytest.importorskip("OCP")
    work = tmp_path_factory.mktemp("scale-bench")
    out = work / "report.json"
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
           "TMPDIR": str(work)}
    done = subprocess.run(
        [sys.executable, str(BENCH), "--bodies", str(BODIES), "--edits", str(EDITS),
         "--out", str(out), "--tmp", str(work)],
        capture_output=True, text=True, timeout=1800, env=env, cwd=str(ROOT))
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    assert out.exists(), "отчёт не написан"
    # While the measurement is running, there must be nothing to read;
    # once it is ready, there must be no temp file left, or the next
    # reader will take a draft for the report.
    assert not Path(str(out) + ".partial").exists(), "черновик остался после готового отчёта"
    return json.loads(out.read_text(encoding="utf-8"))


def test_the_report_names_the_tree_python_and_every_phase(report):
    """A number with no subject is not a number: the report names the tree, Python, and every phase."""
    assert report["schema"] == "kir-scale-bench/1"
    assert report["состояние"] == "готов"
    assert report["bodies"] == BODIES and report["edits_planned"] == EDITS
    assert report["edits"]["count"] == EDITS  # ordered and done are different fields
    tree = report["tree"]
    # Provenance comes from git when it exists; on a copy of the tree
    # without `.git` (a frozen commit copy, an archive) the honest answer
    # is "unknown", not a made-up sha and not a red instrument (08.09.2026:
    # the copy broke this test, the tree did not).
    if (Path(__file__).resolve().parents[2] / ".git").exists():
        assert len(tree["head"]) == 40 and set(tree["head"]) <= set("0123456789abcdef")
    else:
        assert tree["head"] == "неизвестен", tree
    assert isinstance(tree["dirty"], bool) and isinstance(tree["dirty_files"], int)
    assert report["python"]["version"].startswith("3.")
    for phase in PHASES:
        assert phase in report, f"фаза не измерена: {phase}"
        assert "s" in report[phase] or "count" in report[phase] or "ready_s" in report[phase]
    assert report["peak_rss_mb"] > 0 and report["ru_maxrss_mb"] > 0


def test_every_body_carries_real_geometry(report):
    """A count of EXITS proves nothing: what is judged is the bodies and their participation (owner's finding 6)."""
    analyze = report["analyze"]
    assert analyze["bodies_declared"] == BODIES
    assert analyze["bodies_with_geometry"] == BODIES
    assert analyze["pairs_possible"] == BODIES * (BODIES - 1) // 2
    # The answer is known BEFORE the run: there are as many intersections as were seeded.
    assert analyze["seeded"] > 0
    assert analyze["intersections"] == analyze["seeded"]
    assert analyze["seed_found_all"] is True
    assert analyze["extra_intersections"] == 0
    assert report["ИТОГ"] == "ДА"


def test_edit_latency_does_not_grow_with_the_edit_number(report):
    """The edit's latency does not grow with the edit's number by more than double."""
    edits = report["edits"]
    assert edits["count"] == EDITS and len(edits["per_edit"]) == EDITS
    assert edits["growth_ratio_halves"] is not None
    assert edits["growth_ratio_halves"] <= GROWTH_CEILING, edits["per_edit"]
    # Every edit is TWO different numbers, and they are named separately:
    # the application (body recompute + proposal + acceptance) and the re-analysis.
    for row in edits["per_edit"]:
        assert row["apply_s"] > 0 and row["reanalyze_s"] > 0
        assert abs(row["total_s"] - (row["apply_s"] + row["reanalyze_s"])) < 0.01


def test_a_local_edit_reads_a_bounded_number_of_asset_rows(report):
    """Asset rows per edit — a ceiling from the measurement, and it does NOT grow with the edit's number."""
    rows = [row["asset_row_reads_apply"] for row in report["edits"]["per_edit"]]
    assert max(rows) <= ROW_READS_CEILING, rows
    assert max(rows) <= 1.5 * min(rows), rows


def test_a_local_edit_changes_nothing_it_did_not_touch(report):
    """A 5 mm shift at a 100 mm gap cannot start a finding: their count stays constant."""
    edits = report["edits"]
    assert edits["findings_baseline"] == report["analyze"]["findings"]
    assert edits["findings_stable"] is True
    assert report["history"]["revisions"] == EDITS + 3  # root, schema lift, scene, K edits
    assert report["reopen"]["findings"] == report["analyze"]["findings"]
    assert report["reopen"]["ready_s"] > 0
