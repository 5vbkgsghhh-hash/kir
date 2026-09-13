"""THE COURSE CONSUMPTION INSTRUMENT: does the author read what we laid out
for them.

🔴 WHAT THIS FILE HOLDS AND WHY IT WAS SET UP BEFORE THE TEXT.
Measurement of 22.08.2026: `kir_witness.jsonl` (5372 lines) and
`kir_programs.jsonl` (488) carry `author_digest` — the SOURCE's signature —
and not one field of either corpus answers whether the author read the
course. 16 lessons across 42 264 characters, 8 recipes, a call-based
registry: built, laid out, and NEVER ONCE measured by consumption. Writing
yet another unverifiable layer of text on top of this would double the
unverifiable, so the instrument comes first.

THREE ENDS HELD HERE:
  1. the ledger arrives on BOTH sandbox outcomes — the one that built a
     program, and the exploratory one (`KIR-B013`), and the exploratory one
     is exactly the turn where the course gets read most often;
  2. the seam in `serving` writes EXACTLY ONE line per author run, and
     writes it EVEN on zero reads: zero is itself the main number being
     measured;
  3. FAIL CONTROL: the instrument is removed — the line must zero out, not
     stay the same. A green test over a dead instrument is greener than a
     live one.
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from kir import coverage_feed
from kir import course
from kir.sandbox import execute_author_script

ASKS = 'course("единица")\nspec("create_wall")\n'
BUILDS = 'course()\ncreate_level(name="L1", elev_mm=0)\nscore()\n'
SILENT = 'create_level(name="L1", elev_mm=0)\n'


def _reads(source: str):
    return execute_author_script(source)


def test_ledger_names_the_topic_and_counts_the_chars() -> None:
    """Topic and character count — what lets you actually DECIDE, not just "called/didn't call"."""
    result = _reads(ASKS)
    calls = {row["call"]: row for row in result.course_reads}
    assert set(calls) == {"course", "spec"}, result.course_reads
    assert calls["course"]["topic"] == "единица"
    assert calls["spec"]["topic"] == "create_wall"
    # Characters are counted BEFORE the print channel's ceiling: `stdout` truncates, not the course.
    assert calls["course"]["chars"] > 500
    assert calls["spec"]["chars"] > 500


def test_a_reconnaissance_turn_carries_the_ledger() -> None:
    """🔴 THE MAIN END. A turn that only ASKED is declared by the sandbox as
    refusal `KIR-B013` — and it never reaches `record_witness` BY
    CONSTRUCTION. A ledger that only arrives on success would measure course
    consumption everywhere except the place it is consumed the most."""
    result = _reads(ASKS)
    assert result.ok is False
    assert result.refusal.code == "KIR-B013"
    assert result.course_reads, "разведочный ход потерял ведомость"


def test_a_building_turn_carries_the_ledger_too() -> None:
    result = _reads(BUILDS)
    assert result.ok is True and len(result.ops) == 1
    assert {row["call"] for row in result.course_reads} == {"course", "score"}


def test_silence_is_an_empty_ledger_not_a_missing_one() -> None:
    """Zero reads is a LEGITIMATE and the most common outcome, and it must
    be visible as a zero, not as a missing field."""
    result = _reads(SILENT)
    assert result.ok is True
    assert result.course_reads == []
    assert "course_reads" not in result.as_dict()


def test_the_ledger_does_not_leak_into_the_script_namespace() -> None:
    """The author must not be able to write themselves extra reads: the
    seam puts `language.__all__` into the script, and there are no
    instrument names in it."""
    from kir.course import language
    for name in ("reads_ledger", "reset_reads", "MAX_READS", "_note_read"):
        assert name not in language.__all__


# ─────────────────────────────────────────────── seam: one line per run

def _run_seam(source: str, tmp_path: pathlib.Path, monkeypatch) -> list[dict]:
    from kir import serving
    feed = tmp_path / "kir_course_uptake.jsonl"
    monkeypatch.setenv("KIR_COURSE_UPTAKE_PATH", str(feed))
    asyncio.run(serving._authored_input({"program_py": source}))
    if not feed.exists():
        return []
    return [json.loads(line) for line in feed.read_text(encoding="utf-8").splitlines()]


def test_the_seam_writes_one_row_per_authoring_run(tmp_path, monkeypatch) -> None:
    rows = _run_seam(ASKS, tmp_path, monkeypatch)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["v"] == coverage_feed.COURSE_FEED_SCHEMA
    assert row["ok"] is False and row["code"] == "KIR-B013"
    assert row["calls"] == 2 and row["chars"] > 1000
    assert {r["call"] for r in row["reads"]} == {"course", "spec"}
    # The source's signature travels, the source itself — never.
    assert row["source_digest"]
    assert "source" not in row and "program_py" not in json.dumps(row)


def test_the_seam_writes_the_zero_too(tmp_path, monkeypatch) -> None:
    rows = _run_seam(SILENT, tmp_path, monkeypatch)
    assert len(rows) == 1
    assert rows[0]["calls"] == 0 and rows[0]["chars"] == 0
    assert rows[0]["reads"] == []
    assert rows[0]["ok"] is True and rows[0]["op_count"] == 1


def test_control_fail_no_instrument_no_ledger() -> None:
    """🔴 THE INSTRUMENT'S FAIL CONTROL. The mark is removed — the ledger
    must zero out.

    The measurement runs IN-PROCESS, not through the sandbox, and this is
    not a simplification: the course executes in a DIFFERENT process, and a
    substitution in the parent never reaches the child at all. A control
    placed there would be green by construction — exactly the form it is
    set up against.
    """
    course.reset_reads()
    course.course("единица")
    assert course.reads_ledger(), "прибор жив, а ведомость пуста"

    course.reset_reads()
    saved = course._note_read
    try:
        course._note_read = lambda call, topic=None: {"call": call, "chars": 0}
        course.course("единица")
        assert course.reads_ledger() == [], "прибор снят, а ведомость есть — она не оттуда"
    finally:
        course._note_read = saved
        course.reset_reads()


def test_control_fail_no_seam_no_row(tmp_path, monkeypatch) -> None:
    """🔴 THE SEAM'S FAIL CONTROL. The call is removed from the seam — the
    line must DISAPPEAR.

    This is the second end of the same claim: the first shows that the
    line's content comes from the instrument, the second that the line
    itself comes from the seam, and is not set up somewhere else.
    """
    from kir import coverage_feed as cf
    feed = tmp_path / "kir_course_uptake.jsonl"
    monkeypatch.setenv("KIR_COURSE_UPTAKE_PATH", str(feed))
    monkeypatch.setattr(cf, "record_course_uptake", lambda *a, **k: None)
    from kir import serving
    asyncio.run(serving._authored_input({"program_py": ASKS}))
    assert not feed.exists(), "строка пишется мимо шва — значит, шов не тот"


def test_the_sink_counts_its_own_silence(tmp_path, monkeypatch) -> None:
    """"Zero reads" and "the sink is switched off" are different facts (form 34)."""
    monkeypatch.setenv("KIR_COURSE_UPTAKE_PATH", "")
    monkeypatch.setattr(coverage_feed, "install_data_path", lambda *a, **k: None)
    before = dict(coverage_feed.COURSE_FEED_COUNTS)
    coverage_feed.record_course_uptake(_reads(SILENT))
    assert coverage_feed.COURSE_FEED_COUNTS["disabled"] == before["disabled"] + 1
