"""THE DEFINITION OF THE MAIN METRIC — BY LAW, NOT BY THE AUTHOR'S MEMORY.

Over the 23–24.08 period, the mission metric's definition turned out to
be wrong FOUR times, and all four were found by a manual check BEFORE the
number was published. A manual check is not an instrument: the fifth time
it might not happen. Here each of the four forms is closed by a separate
FAIL control, and the fifth — found on 24.08 on tapes already recorded —
stands alongside them.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path("/opt/kukai-rebuild1/backend")
TOOLS = ROOT / "tools"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mm = _load("mission_metric")


def _r(n, **kw):
    base = {"n": n, "refused": False, "execution": "", "acceptance": "",
            "codes": [], "built": False, "changed": False}
    base.update(kw)
    return base


# ── KIND OF SPEECH ────────────────────────────────────────────────────────────────

def test_rollback_is_the_deepest_kind():
    """A rollback outranks any code: the real model did not accept what was written."""
    assert mm.speech_kind(_r(1, execution="rolled_back",
                             codes=["KIR-T001"])) == "свидетель"


def test_acceptance_is_heard_by_two_carriers_not_one():
    """🔴 THE FIFTH FORM (24.08). Acceptance refuses through TWO carriers:
    the `acceptance` field and the `KIR-A*` code. The instrument was
    asking only one field — and on every tape before the evening of 24.08
    (when the field was introduced), two acceptance turns read as "said
    nothing"."""
    by_field = _r(1, execution="committed", acceptance="rejected")
    by_code = _r(1, execution="committed", codes=["KIR-A006"])
    assert mm.speech_kind(by_field) == "приёмка"
    assert mm.speech_kind(by_code) == "приёмка"
    assert mm.spoke(by_field) and mm.spoke(by_code)


def test_recon_is_not_speech():
    """🔴 THE FOURTH FORM (24.08). `not_applicable` sits on a READING turn.
    The condition `acceptance != "accepted"` let it through, and every
    RECONNAISSANCE turn counted as testability speech: seven out of 15
    events in the first measurement were exactly this."""
    recon = _r(1, execution="read_completed", acceptance="not_applicable")
    assert mm.spoke(recon) is False
    assert mm.speech_kind(recon) == "нет"


def test_typechecker_is_counted_but_not_as_mission():
    """A type checker is speech, but NOT the mission's speech: any compiler gives it."""
    rd = _r(1, refused=True, codes=["KIR-T001"])
    assert mm.spoke(rd) is True
    assert mm.speech_kind(rd) == "тайпчекер"
    assert mm.is_deep(rd) is False


# ── EVENT ─────────────────────────────────────────────────────────────────

def test_rollback_then_fix_then_built_is_an_event():
    s = mm.score_task([
        _r(1, execution="rolled_back", codes=["KIR-X009"]),
        _r(2, execution="committed", changed=True, built=True),
    ])
    assert s["deep"] == 1
    assert [e["kind"] for e in s["events"]] == ["свидетель"]


def test_retreat_from_writing_is_not_an_event():
    """🔴 FAIL CONTROL. A refusal also "goes away" when the author STOPPED
    writing. There is such a turn on the 21.08 tape: grounding refused,
    the next turn shrank from four operations to a single READ. The
    definition "the outcome got better" was counting this as a win for
    testability."""
    s = mm.score_task([
        _r(1, refused=True, codes=["KIR-G101"]),
        _r(2, execution="read_completed", changed=True, built=False),
    ])
    assert s["deep"] == 1
    assert s["events"] == []


def test_repeat_after_refusal_is_not_an_event():
    """A repeat of the same program means the refusal was NOT involved."""
    s = mm.score_task([
        _r(1, execution="rolled_back", codes=["KIR-X009"]),
        _r(2, execution="committed", changed=False, built=True),
    ])
    assert s["events"] == []
    assert len(s["ambiguous"]) == 1


def test_unrecorded_change_is_not_silently_a_no():
    """🔴 "NOT RECORDED" ≠ "DID NOT CHANGE." Ten tapes from 21–24.08 store
    not the signal itself but its conjunction with the earlier speech
    condition; once the condition changed, there was nothing left to tell
    the two apart. Such turns must land in DISPUTED, not silently in
    "no"."""
    rd = {"n": 2, "execution": "committed", "built": True}
    s = mm.score_task([_r(1, execution="rolled_back"), rd])
    assert s["events"] == []
    assert len(s["ambiguous"]) == 1


def test_one_build_does_not_pay_for_two_refusals():
    """The window is closed by the next DEEP utterance: otherwise a
    single build would count for every refusal of the task at once, and
    the number would inflate on its own."""
    s = mm.score_task([
        _r(1, execution="rolled_back"),
        _r(2, execution="rolled_back", changed=True),
        _r(3, execution="committed", changed=True, built=True),
    ])
    assert s["deep"] == 2
    assert [e["round"] for e in s["events"]] == [2]


def test_typechecker_refusal_yields_no_mission_event():
    """🔴 FAIL CONTROL. The earlier single number lumped the type checker
    together with testability: 15 changes out of 20, 13 of them on types
    and Python."""
    s = mm.score_task([
        _r(1, refused=True, codes=["KIR-T001"]),
        _r(2, execution="committed", changed=True, built=True),
    ])
    assert s["opportunities"] == 1
    assert s["deep"] == 0
    assert s["events"] == []


# ── THE DEFINITION'S HOUSE IS ONE ────────────────────────────────────────────────────

def test_definition_lives_in_exactly_one_place():
    """🔴 A NAMED CLASS OF TREE DEFECT: a quantity DECLARED in one place
    and READ in another. The definition lived in `loop_meter` (writes),
    while the summary was computed in `author_loop_baseline` (reads);
    four fixes in one day would have reached the second instrument only
    through the author's memory."""
    for name in ("loop_meter", "author_loop_baseline"):
        src = (TOOLS / f"{name}.py").read_text(encoding="utf-8")
        # Prose about an enumeration is allowed to live — BRANCHING on it
        # is not. The first version banned the word itself and turned red
        # on a comment explaining WHY there is no branching here. A ban on
        # a word catches the wrong subject: the law is about where the
        # DECISION gets made.
        code_lines = [ln for ln in src.splitlines()
                      if "inconclusive" in ln and not ln.strip().startswith("#")]
        assert not code_lines, (
            f"{name}.py снова ВЕТВИТСЯ по перечислению отказов приёмки: "
            f"{code_lines[:2]} — решение обязано приниматься только в "
            f"mission_metric.py")
        assert "mission_metric" in src, (
            f"{name}.py перестал спрашивать дом определения")


def test_recon_code_is_not_a_sandbox_refusal():
    """🔴 THE SIXTH FORM (24.08, the new suite's first run). `KIR-B013` is
    a RECONNAISSANCE turn: the script executed, wrote nothing,
    `refused=False`. The `KIR-B*` branch recorded it as a sandbox event,
    that is, as a refusal — the same defect as `not_applicable` in
    acceptance a day earlier."""
    recon = _r(1, execution="not_started", acceptance="not_run",
               codes=["KIR-B013"])
    assert mm.speech_kind(recon) == "разведка"
    assert mm.spoke(recon) is False
    assert mm.is_deep(recon) is False


def test_a_real_sandbox_exception_is_still_a_refusal():
    """Control for the previous one: a genuine script exception
    (`KIR-B006`) must remain a sandbox event, otherwise the fix would eat
    an entire kind of speech."""
    boom = _r(1, refused=True, codes=["KIR-B006"])
    assert mm.speech_kind(boom) == "песочница"
    assert mm.spoke(boom) is True


def test_blind_acceptance_is_not_the_model_being_corrected():
    """🔴 THE SEVENTH FORM (24.08, caught by a probe BEFORE the runs).
    Acceptance is blind to `author_family` by construction:
    `partial_blind_scope`. The op returns `inconclusive` ALWAYS — with
    `execution=committed` and `witness=satisfied`. Counting this as
    testability speech would mean recording OUR OWN BLINDNESS as a mission
    event: every turn of the authoring family would produce a "deep event"
    out of thin air."""
    blind = _r(1, execution="committed", acceptance="inconclusive",
               codes=["KIR-A007"], acceptance_reason="partial_blind_scope")
    assert mm.speech_kind(blind) == "приёмка слепа"
    assert mm.spoke(blind) is True      # something was said
    assert mm.is_deep(blind) is False   # but not about the model's decision


def test_acceptance_that_disagreed_is_still_the_deepest_after_rollback():
    """Control for the previous one: `KIR-A006` — "reread and DID NOT
    AGREE" — must remain deep, otherwise the fix would eat the most
    valuable kind of speech."""
    said_no = _r(1, execution="committed", acceptance="rejected",
                 codes=["KIR-A006"])
    assert mm.speech_kind(said_no) == "приёмка"
    assert mm.is_deep(said_no) is True


def test_unread_acceptance_is_named_apart_from_blindness():
    """The third outcome: the reread did not happen. This is neither
    instrument blindness nor disagreement — and mixing it with either
    means treating the wrong thing."""
    unread = _r(1, execution="committed", acceptance="inconclusive",
                codes=["KIR-A007"], acceptance_reason="post_read_unavailable")
    assert mm.speech_kind(unread) == "приёмка не дочитала"
    assert mm.is_deep(unread) is False


def test_the_meter_records_the_acceptance_reason():
    """🔴 THE TAPE MUST CARRY THE REASON, OTHERWISE THE DISTINCTION IS
    UNVERIFIABLE AFTER THE FACT. Ten tapes from 21–24.08 already had to be
    recounted blind because of one unrecorded signal."""
    src = (TOOLS / "loop_meter.py").read_text(encoding="utf-8")
    assert '"acceptance_reason": acceptance_reason' in src


# ── 🔴 THE INSTRUMENT WAS REBUILDING THE CODE REGISTRY BY TRAVERSING
# NAMES (measured 04.09.2026) ──────
#
# `_known_codes` walked `dir(diag)` looking for string constants. Since
# 01.09 codes are introduced via `diag.register(...)` and are NOT
# REQUIRED to be a module-level constant, so the traversal saw 68 out of
# 107 — and the metric printed "CODES kir.diag DOES NOT KNOW: KIR-G101,
# KIR-G102, KIR-G104, KIR-M003, KIR-M006." All five are registered; two
# are emitted by prod dozens of times a day. A line sending someone to fix
# something ALREADY FIXED is worse than a missing one.

def test_известные_коды_это_таблица_целиком() -> None:
    from kir import diag
    from kir.instruments.decision_changes import _known_codes
    assert _known_codes() == frozenset(diag.CODES), (
        "реестр кодов пересобран обходом имён, а не спрошен у таблицы")


def test_живые_коды_заземления_признаны() -> None:
    """These are exactly the ones that were accused — the measurement was paid for by them."""
    from kir.instruments.decision_changes import _known_codes
    известные = _known_codes()
    невидимые = [к for к in ("KIR-G101", "KIR-G102", "KIR-G104",
                             "KIR-M003", "KIR-M006") if к not in известные]
    assert not невидимые, f"прибор не знает живых кодов: {невидимые}"


def test_обход_имён_остался_запасным_и_он_беднее() -> None:
    """A CONTROL IN THE OTHER DIRECTION: the fallback path does not
    invent codes beyond the table, but it also does not cover it —
    otherwise the substitution would mean nothing."""
    from kir import diag
    сканом = {v for v in (getattr(diag, n, None) for n in dir(diag))
              if isinstance(v, str) and v.startswith("KIR-") and len(v) == 8}
    таблица = frozenset(diag.CODES)
    assert сканом < таблица, (
        "обход имён обязан быть СТРОГИМ подмножеством таблицы: "
        f"скан {len(сканом)}, таблица {len(таблица)}")
