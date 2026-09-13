# -*- coding: utf-8 -*-
"""THE SCENARIO IN FULL, AND EVERY STEP IS A REAL PROCESS.

The mandate's cycle (part 6): open → read the element and its relations →
edit the door → edit the available opening → show the diff and the
constraints → save → CLOSE THE PROCESS → continue with a second edit in a
NEW process → the export compiles.

🔴 WHY `subprocess`, AND NOT A FUNCTION CALL. "Survived closing the
process" is a property of DISK, not of memory: run in-process, the same
cycle stays green even with the save fully lost, because the nodes remain
in a live object. Here every step is a separate
`python -m kir.decompile.capture_api`, and nothing survives between steps
except the directory.

The building is synthetic (`capture_api demo`) and is built by the same
route as in the `docs/CAPTURE_OFFLINE_EDIT_RU.md` instructions: the
scenario must run WITHOUT KUKAI, without a corpus, and without Revit
running.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kir.decompile import capture_api as API

ROOT = Path(__file__).resolve().parents[3]
RING = [[2500.0, 2500.0], [5500.0, 2500.0], [5500.0, 5500.0], [2500.0, 5500.0]]


def _cli(*argv, expect: int = 0):
    """One scenario step — one process. Returns the parsed stdout."""
    child = subprocess.run(
        [sys.executable, "-m", "kir.decompile.capture_api", *argv],
        capture_output=True, text=True, timeout=900,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == expect, (argv, child.returncode, child.stderr[-800:])
    return json.loads(child.stdout)


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    return tmp_path_factory.mktemp("scenario")


def test_the_whole_scenario_survives_a_new_process(scene):
    capture = scene / "capture"
    made = _cli("demo", "--out", str(capture))
    assert made["capture"] == str(capture)

    # ── process 1: open and read the element together with its relations ──
    opened = _cli("open", "--capture", str(capture))
    assert opened["elements"] == 4 and opened["edits"] == 0
    assert opened["source_binding"]["source_version"]

    door = _cli("read", "--capture", str(capture), "--element", API.DEMO_DOOR)
    assert door["op_name"] == "create_door"
    assert door["host"]["element_id"] == API.DEMO_WALL
    assert door["editable_fields"] == ["offset_mm", "sill_mm", "symbol"]
    assert any(item["state"] != "represented" for item in door["fields"])

    # ── process 2: show the consequences, writing NOTHING ─────────────────
    preview = _cli("propose", "--capture", str(capture),
                   "--edit", json.dumps({"element_id": API.DEMO_DOOR,
                                         "change": {"offset_mm": 4000.0}}),
                   "--edit", json.dumps({"element_id": API.DEMO_FLOOR,
                                         "change": {"opening_index": 0,
                                                    "opening_contour_mm": RING}}))
    assert preview["wrote_nothing"] is True
    assert all(item["admissible"] for item in preview["proposals"])
    assert all(item["diff"] for item in preview["proposals"]), "diff обязан быть непустым"
    assert any(item["open_questions"] for item in preview["proposals"])
    assert not (capture / "capture_edits.jsonl").exists(), "просмотр записал журнал"

    # ── process 3: edit the door AND the opening, save ─────────────────────
    step1 = scene / "step1"
    applied = _cli("apply", "--capture", str(capture),
                   "--edit", json.dumps({"element_id": API.DEMO_DOOR,
                                         "change": {"offset_mm": 4000.0},
                                         "before": {"offset_mm": 3000.0}}),
                   "--edit", json.dumps({"element_id": API.DEMO_FLOOR,
                                         "change": {"opening_index": 0,
                                                    "opening_contour_mm": RING}}),
                   "--out", str(step1))
    assert applied["saved"] == str(step1) and applied["edits"] == 2
    assert all(item["refusal"] is None for item in applied["applied"])

    # ── process 4 (NEW): a second edit on top of what was saved ───────────
    step2 = scene / "step2"
    second = _cli("apply", "--capture", str(step1), "--element", API.DEMO_DOOR_2,
                  "--patch", json.dumps({"offset_mm": 8000.0}), "--out", str(step2))
    assert second["edits"] == 3, "новый процесс потерял историю прежних правок"

    # ── process 5: both prior edits are in place, not just the last one ───
    reread = _cli("read", "--capture", str(step2), "--element", API.DEMO_DOOR)
    assert reread["op_params"]["offset_mm"] == pytest.approx(4000.0)
    floor = _cli("read", "--capture", str(step2), "--element", API.DEMO_FLOOR)
    assert floor["op_params"]["holes"][0] == RING
    second_door = _cli("read", "--capture", str(step2), "--element", API.DEMO_DOOR_2)
    assert second_door["op_params"]["offset_mm"] == pytest.approx(8000.0)

    # ── process 6: the export COMPILES, and this is a number, not
    # "it worked" ──
    csharp = scene / "cs"
    exported = _cli("export", "--capture", str(step2), "--csharp-dir", str(csharp))
    assert exported["programs"] == 2 and exported["compiled"] == 2
    assert exported["refusals"] == []
    sources = sorted(csharp.iterdir())
    assert len(sources) == 2 and all(item.read_text(encoding="utf-8") for item in sources)
    # The edit made it through to emission: a silent loss would have
    # looked like success.
    assert "4000" in "".join(item.read_text(encoding="utf-8") for item in sources)


def test_the_scenario_refuses_a_stale_patch_in_a_new_process_and_saves_nothing(scene):
    """🔴 A REFUSAL WITHIN THE SCENARIO IS EXIT CODE 2 AND AN EMPTY TARGET,
    not a half-save."""
    capture = scene / "capture"
    target = scene / "never"
    payload = _cli("apply", "--capture", str(capture), "--element", API.DEMO_DOOR,
                   "--patch", json.dumps({"offset_mm": 4500.0}),
                   "--before", json.dumps({"offset_mm": 999.0}),
                   "--out", str(target), expect=2)
    assert payload["saved"] is None
    assert payload["applied"][0]["refusal"]["code"] == "edit_before_value_mismatch"
    assert not target.exists(), "отказавший шаг оставил после себя каталог"
