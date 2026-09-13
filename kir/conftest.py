"""Each test gets its own telemetry sink — one carrier for the whole
suite.

🔴 WHY THIS FILE WAS CREATED (02.09.2026), BY MEASUREMENT, NOT FOR
TIDINESS.

Before it, the refusal sink was set with
`os.environ.setdefault("KIR_REJECTIONS_PATH", …)` AT MODULE LEVEL — 103
times across 119 test files, each with its own file name
(`kir_test_queue.jsonl`, `kir_parity_queue.jsonl`, `kir_fw_queue.jsonl`,
…). Under pytest, `kir/tests/conftest.py` always wins, because conftest
loads FIRST: meaning all 103 of those writes are inert by construction,
and the whole suite shares ONE common sink.

And here is how that ended up on this machine. Measured 02.09:

    /tmp/kir_test_queue.jsonl   1425 lines, 522 KB, owned by root, 04:40
    write as the suite's user  ->  PermissionError

The file had accumulated across runs and ended up owned by root;
`coverage_feed` writes to it fail-open, so under an ordinary user the
feed silently writes NOTHING. This is form 34 of this tree, verbatim: "an
instrument that was not allowed to perform the action being measured
prints the cost of the action THAT NEVER HAPPENED and looks intact." Any
test asserting "a line was written" would be measuring the failure
instead of the subject, and any test counting lines would be counting
someone else's 1425.

WHAT IS DONE HERE. The sink becomes EACH TEST'S OWN (`tmp_path`), meaning
there is always somewhere to write, no accumulation happens, and there
are no foreign lines, by construction. The functional scope was not
chosen for elegance: a sink shared per class or per module would have
brought back coupling between tests at a smaller scale.

WHY ONE FILE, NOT THREE. The test trees live in `kir/tests`,
`kir/decompile/tests`, `kir/checker/tests`, `kir/clash/tests`,
`kir/viewer/tests`. Three copies of the fixture would have diverged on
the very first edit — a named defect of this tree. `kir/conftest.py`
sits above all five, and pytest picks it up for each of them.

WHAT THIS FIXTURE DOES NOT DO, stated aloud:
  * it does not cancel the module-level `setdefault` calls in the 119
    files. They become inert here too, but remain a safeguard when the
    module is imported WITHOUT pytest (`python -c "import
    kir.tests.test_x"`), where conftest doesn't load at all. Removing
    them is separate work: a mechanical edit of 119 files under four
    concurrent writers would have turned any measurement of them into a
    measurement of a MIXTURE;
  * it does not touch the flags (`KUKAI_CHECKER_V2` and kin). They have
    their own cost and their own readers, and are addressed separately;
  * it does not guard against leaks — that is `kir/tests/conftest.py`'s
    job, and it stays where it is written.

WHY THIS WORKS. Readers ask the environment AT CALL TIME, not at import:
`coverage_feed._feed_path()` reads `os.environ.get(_ENV)` inside the
function. Verified by execution, not by reading the code.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib

import pytest

#: The variable's name lives in ONE place — at the consumer, not as a
#: copy here.
from kir.coverage_feed import _ENV as _REJECTIONS_ENV  # noqa: E402


@pytest.fixture(autouse=True)
def _own_rejections_sink(tmp_path):
    """Every test gets its own sink file; there are no foreign lines, by
    construction.

    🔴 WITHOUT `monkeypatch`, AND THIS IS NOT A MATTER OF TASTE BUT A FIX
    FOR MY OWN REGRESSION (caught by a run on 02.09, missed the commit,
    caught afterward — the subject is named, not hidden). The first
    revision asked for `monkeypatch`, and that alone was enough to break
    SOMEONE ELSE'S guard: this fixture lives in a conftest ONE LEVEL
    ABOVE the leak guard `kir/tests/conftest.py`, meaning it comes up
    EARLIER than it — and along with it, the per-test shared
    `monkeypatch` instance comes up earlier too. It is torn down in
    reverse order, i.e. LATER than the guard gets to check the
    environment. A test that itself called
    `monkeypatch.setenv("KUKAI_CHECKER_V2", "0")` got accused of a leak
    by SOMEONE ELSE'S hand: `test_design_check` gave `35 passed` without
    this fixture and `35 passed, 1 error` with it.

    My own save-and-restore does not change fixture ordering at all: the
    `monkeypatch` instance stays wherever the test itself calls for it.
    """
    было = os.environ.get(_REJECTIONS_ENV)
    os.environ[_REJECTIONS_ENV] = os.fspath(tmp_path / "rejections.jsonl")
    try:
        yield
    finally:
        if было is None:
            os.environ.pop(_REJECTIONS_ENV, None)
        else:
            os.environ[_REJECTIONS_ENV] = было


# ══════════════════════════════════════════════════════════════════════════
# THE SECOND CARRIER OF THE LEAK: A PATCHED MODULE ATTRIBUTE, NOT AN ENVIRONMENT VARIABLE
# ══════════════════════════════════════════════════════════════════════════
#
# 🔴 WHY THIS IS HERE, MEASURED 02.09.2026, AND WHY IT DISPROVES THE
# HYPOTHESIS.
#
# This shift's assignment named "the other eight SINKS"
# (`KIR_WITNESS_PATH`, `KIR_COURSE_UPTAKE_PATH`, `KIR_CREATED_LEDGER_DIR`,
# …) as the cause of the four companywide reds and asked to extend the
# fixture upward to cover them. THE MEASUREMENT DISPROVED THIS: not one
# sink has anything to do with these reds. A probe that printed the
# environment diff before EVERY target test across a suite of 137 files
# found exactly three leaked names —
#
#     KUKAI_CHECKER_V2='1'                     (setUpClass `test_course.py`)
#     KUKAI_DECOMPILE_DATA='…/data/decompile'  (module import)
#     KIR_REJECTIONS_PATH -> /tmp/kir-anyquery-test-…/rejections.jsonl
#
# — and NOT ONE of the three is involved in the failure. The real
# carrier is a MODULE ATTRIBUTE:
#
#     serving._turn_device_id  ->  <MagicMock name='_turn_device_id'>
#
# and it returns `None`, because `mock.patch.object(serving,
# "_turn_device_id", return_value=serving.ADMIN_DEVICE)` takes
# `ADMIN_DEVICE` from an unset `KUKAI_ADMIN_DEVICES`, i.e. `None`.
#
# 🔴 THE MECHANISM IS NAMED IN FULL AND REPRODUCES IN 0.6 s. The
# producer is `kir/tests/test_building_verdict_in_the_receipt.py`, class
# `_Door`: its `setUp` calls `self._device.start()` FIRST, and only
# AFTERWARD `enter_kir_mode(self)`, which on this tree always gives a
# `skipTest` («порт «llm.turn_context» не поставлен этой средой»).
# unittest, on a failed `setUp`, does NOT CALL `tearDown` AT ALL —
# meaning `self._device.stop()` never happens, and the patch lives until
# the end of the PROCESS. A single standalone run of the file: `2
# passed, 11 skipped`, and the patch is already in place.
#
# This is a NAMED kind of this tree, and the tree has already written
# about it next door: `test_the_host_names_its_data_dirs.py` — «`addCleanup`,
# not `tearDown`: on a failed `setUp`, unittest does not call `tearDown`
# at all».
#
# WHAT BROKE FOR THE VICTIMS, BY THE NUMBER (a suite of 137 files, 4
# failed):
#     `_turn_device_id() -> None`  ->  a journal key of ('',
#         'K3_АР.rvt') instead of ('dev-1', 'K3_АР.rvt') — two
#         `test_document_identity…` tests;
#     the same `None` fails `is_admin_device`, the KIR gate stays closed
#         even with `KUKAI_KIR_TOOL=stage2` — two `test_created_ledger`
#         tests (`'gate' == 'gate'` and `0 != 1`).
#
# 🔴 WHY RESTORE, AND NOT REDDEN THE PRODUCER. The environment guard
# above reddens the producer, and that is the correct way to run things.
# Here it would have given 11 ERRORS on SKIPPED tests from someone
# else's plot, in this one file alone, and how many such files are in
# the suite is NOT MEASURED (a full run this shift wasn't mine to do).
# So the state is RESTORED, and the producer is NAMED BY NAME at the end
# of the run: silent hygiene is indistinguishable from its absence, and
# invented redness costs more than missing redness. The switch to a
# refusal is one line, and it is named below.
#
# BOUNDARIES, STATED ALOUD:
#   * ONE module is guarded — `kir.serving`. The list is closed and is
#     extended BY MEASUREMENT, not by guesswork: a guard that pretends
#     to be complete is worse than a missing one (the neighboring
#     conftest's argument, verbatim);
#   * only names that WERE PRESENT in the import snapshot are restored.
#     A name introduced later is not removed: lazy attributes have
#     legitimate authors;
#   * comparison is by IDENTITY (`is`), not by value: a patch is a
#     DIFFERENT object, while mutation of a shared object (a ContextVar,
#     a dict) is out of scope here and is visible to a different
#     instrument.
#: 🔴 THE IMPORT IS WRAPPED, AND THIS IS NOT OVER-CAUTION. `kir/conftest.py`
#: sits above FIVE test trees, and a bare import here would turn every
#: failure to load `serving` into a COLLECTION error for the whole suite
#: — including in the split gate's clean venv, where the subject under
#: test is something else entirely. When it can't, the guard stays
#: SILENT, and says so out loud in the run's header, rather than
#: pretending to be whole.
try:
    from kir import serving as _serving  # noqa: E402
except Exception as _exc:                                  # pragma: no cover
    _serving = None
    _SERVING_NOTE = (f"kir.serving не импортировался "
                     f"({type(_exc).__name__}): {_exc}")
else:
    _SERVING_NOTE = ""

#: The `kir.serving` namespace, as ASSEMBLED BY IMPORT, is captured here,
#: i.e. BEFORE the first test: conftest loads before any of them.
_SERVING_AS_IMPORTED: dict = (
    dict(vars(_serving)) if _serving is not None else {})

#: Who left what patched in which test. Printed at the end of the run.
ПОДМЕНЫ_ПЕРЕЖИВШИЕ_ТЕСТ: list = []

#: A sentinel for "the name is gone entirely": `None` would be a legitimate value here.
_НЕТ = object()

#: How many list lines to print. The count is printed IN FULL, always.
_ПОТОЛОК_ПЕЧАТИ = 50


@pytest.fixture(autouse=True)
def _serving_comes_back_as_the_import_built_it(request):
    """`kir.serving` arrives at EVERY test the way import assembled it.

    The fixture is automatic and sits ABOVE five test trees for the same
    reason as the refusal sink: the producers of patches live in both
    `kir/tests` and `kir/decompile/tests`, and three copies of the guard
    would have diverged on the very first edit.

    The check runs AFTER a test's `tearDown` (the fixture comes up before
    it and tears down after), so a legitimate `start()/stop()` pair never
    reaches it at all: by that moment it has already returned what it
    borrowed.
    """
    yield
    if _serving is None:
        return
    сейчас = vars(_serving)
    остались = [имя for имя, было in _SERVING_AS_IMPORTED.items()
                if сейчас.get(имя, _НЕТ) is not было]
    for имя in остались:
        setattr(_serving, имя, _SERVING_AS_IMPORTED[имя])
        ПОДМЕНЫ_ПЕРЕЖИВШИЕ_ТЕСТ.append((request.node.nodeid, имя))
    # 🔴 THE SWITCH TO THE "REDDEN THE PRODUCER" REGIME IS ONE LINE:
    #     if any remain: raise AssertionError(...)
    # Not enabled ON PURPOSE, for a reason stated in the header: the cost is not measured.


# ══════════════════════════════════════════════════════════════════════════
# THIRD DUTY: THE BOX LOCK IS MANDATORY HERE TOO (03.09.2026)
# ══════════════════════════════════════════════════════════════════════════
#
# 🔴 WHAT BOUGHT THIS. The box is shared, and there are two trees on it.
# The product has had a lock guard since 12.08.2026; KIR NEVER HAD ONE,
# and that is exactly the shape the neighboring conftest already lived
# through with the prod environment: a safeguard set up in one tree reads
# as "the question is closed" for both. Measured 03.09: THREE full runs
# at once drove swap to 100 % and killed someone else's run with an OOM.
#
# 🔴 THE DECISION DOES NOT LIVE HERE, AND THAT IS NOT A CONVENIENCE. It
# lives in the owner's tool (`tools/suite_lock.py`) as one pure function,
# `refusal(argv, env)`, and this conftest just CALLS it. Two copies of
# the rule would have diverged on the very first edit, and then two
# trees would be judging ONE box by different numbers.
#
# 🔴 WHY THE TOOL IS LOOKED UP BY A MARKER, NOT NAMED BY A PATH. An
# absolute path into the owner's tree inside an executable string makes
# the package fit for exactly one machine — this is FORBIDDEN by the
# guard `test_no_absolute_deployment_path_is_executable`, and rightly
# so: `kir` is published separately. The order of authorities is the
# same as `install_paths`'s: OPERATOR -> OWNER -> a lookup BY MARKER
# next to the checkout. Not found — the guard doesn't work, and says so
# OUT LOUD at the end of the run: a silent absence of the guard is
# indistinguishable from its presence, and that is the most expensive
# kind of silence in this tree.
#
# THE LOCK IS MACHINE-LOCAL BY CONSTRUCTION (a file in /tmp), so "no
# tool" is a legitimate state of someone else's machine, not a breakage.
_ОТ_ХОЗЯИНА = ("tools", "suite_lock.py")
_МАРКЕР_СОСЕДА = ("backend", *_ОТ_ХОЗЯИНА)

#: Why the guard was absent. An empty string means it was present.
_ЗАМОК_НЕ_НАЙДЕН = ""


def _читается(путь: pathlib.Path) -> bool:
    """The file exists AND can be read.

    🔴 `is_file()` RAISES INSTEAD OF ANSWERING "NO" — caught by the very
    first run on 03.09.2026: the neighboring checkout `/opt/kukai-canary`
    belongs to another user (drwxr-x---), and `stat` raised a
    `PermissionError`, bringing down the ENTIRE pytest collection
    (`INTERNALERROR`, rc=3). The box guard has no right to be the cause
    of a run crashing: a read failure is DATA, not an accident.
    """
    try:
        return путь.is_file() and os.access(путь, os.R_OK)
    except OSError:
        return False


def _кандидаты_замка():
    """Where to look for the tool — in descending order of authority, as with `install_paths`.

    OPERATOR -> OWNER -> a MARKER next to the checkout. SEVERAL
    candidates are returned, because a file's name is not yet a tool: on
    this machine `kukai-canary` sits nearby with its own copy, and the
    one to pick is WHICHEVER ONE ANSWERS.
    """
    названо = (os.environ.get("KUKAI_SUITE_LOCK_TOOL") or "").strip()
    if названо:
        yield pathlib.Path(названо), "названо KUKAI_SUITE_LOCK_TOOL"
        return                       # the operator said so — we stop guessing after that
    for имя in ("KIR_HOST_ROOT", "KUKAI_BACKEND_ROOT"):
        корень = (os.environ.get(имя) or "").strip()
        if корень:
            yield (pathlib.Path(корень).joinpath(*_ОТ_ХОЗЯИНА),
                   f"дерево хозяина названо {имя}")
    начало = pathlib.Path(__file__).resolve().parent
    for уровень in (начало, *начало.parents):
        yield уровень.joinpath(*_МАРКЕР_СОСЕДА), "маркер над пакетом"
        try:
            соседи = sorted(p for p in уровень.iterdir()
                            if not p.name.startswith("."))
        except OSError:
            continue
        for сосед in соседи[:64]:
            yield сосед.joinpath(*_МАРКЕР_СОСЕДА), "маркер у соседа по каталогу"


def _инструмент_замка():
    """(tool, how it was found) or (None, the reason it's absent).

    A candidate is accepted not by name but by its ABILITY TO ANSWER: it
    must have a `refusal`. An older copy (or someone else's, unreadable
    one) is silently skipped — otherwise the guard would be considered
    installed while actually staying silent.
    """
    пробовали = []
    for путь, откуда in _кандидаты_замка():
        if not _читается(путь):
            continue
        try:
            модуль = _загрузить_инструмент(путь)
        except Exception as ошибка:                        # noqa: BLE001
            пробовали.append(f"{путь} не грузится ({ошибка!r})")
            continue
        if модуль is not None and hasattr(модуль, "refusal"):
            return модуль, f"{путь} · {откуда}"
        пробовали.append(f"{путь} без `refusal` (копия постарше)")
    хвост = ("; отвергнуто: " + "; ".join(пробовали)) if пробовали else ""
    return None, (f"инструмента замка нет: не задан KUKAI_SUITE_LOCK_TOOL, не "
                  f"задан KIR_HOST_ROOT, и маркера `{'/'.join(_МАРКЕР_СОСЕДА)}`"
                  f" рядом с пакетом не найдено{хвост}")


def _загрузить_инструмент(путь: pathlib.Path):
    """Ask the TOOL, not reread its file with our own json."""
    spec = importlib.util.spec_from_file_location("_kir_suite_lock", путь)
    if spec is None or spec.loader is None:
        return None
    модуль = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(модуль)
    return модуль


def pytest_configure(config):
    """A WIDE RUN GOES THROUGH THE LOCK. A narrow one is not touched at all.

    In `configure`, not in collection: the answer is known BEFORE the
    test modules are imported, and importing 653 files is itself the
    first big spend of memory.
    """
    global _ЗАМОК_НЕ_НАЙДЕН
    if getattr(config.option, "collectonly", False):
        # Collection executes nothing: the lock exists because of
        # CONCURRENT EXECUTION. The same argument holds for the guard in
        # the owner's tree.
        return
    инструмент, откуда = _инструмент_замка()
    if инструмент is None:
        _ЗАМОК_НЕ_НАЙДЕН = откуда
        return
    try:
        вердикт = инструмент.refusal(
            list(getattr(getattr(config, "invocation_params", None), "args", ())
                 or []), os.environ)
        строка = инструмент.echo_line(os.environ)
    except Exception as ошибка:                            # noqa: BLE001
        # The tool exists but doesn't answer. That is NOT a reason to
        # refuse the run — but it's also not a reason to stay silent:
        # the guard's silence must be audible.
        _ЗАМОК_НЕ_НАЙДЕН = f"{откуда} не ответил: {ошибка!r}"
        return
    if строка:
        print(строка + f" · инструмент: {откуда}")
    if вердикт is not None:
        raise pytest.UsageError(вердикт[1])


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """State out loud what was restored and by WHOM it was left behind.

    Without this printout, the restoration would become exactly that
    silent hygiene: the next patch would be exactly as invisible as this
    one was before it was measured.
    """
    if _ЗАМОК_НЕ_НАЙДЕН:
        terminalreporter.write_sep("=", "сторож ЗАМКА БОКСА не работал")
        terminalreporter.write_line(f"  {_ЗАМОК_НЕ_НАЙДЕН}")
        terminalreporter.write_line(
            "  Прогон НЕ проверен на столкновение с чужим набором: если бокс "
            "общий, назови инструмент в KUKAI_SUITE_LOCK_TOOL.")
    if _SERVING_NOTE:
        terminalreporter.write_sep("=", "сторож подмен НЕ РАБОТАЛ")
        terminalreporter.write_line(f"  {_SERVING_NOTE}")
    if not ПОДМЕНЫ_ПЕРЕЖИВШИЕ_ТЕСТ:
        return
    terminalreporter.write_sep(
        "=", f"подмен в kir.serving пережило тест: "
             f"{len(ПОДМЕНЫ_ПЕРЕЖИВШИЕ_ТЕСТ)} (возвращены)")
    # A printing ceiling: a file that EVERY test leaks would flood the
    # run's tail and hide everything else. The total above is stated IN
    # FULL, so the ceiling hides nothing — it trims the list's length, not the count.
    for nodeid, имя in ПОДМЕНЫ_ПЕРЕЖИВШИЕ_ТЕСТ[:_ПОТОЛОК_ПЕЧАТИ]:
        terminalreporter.write_line(f"  serving.{имя} <- {nodeid}")
    остаток = len(ПОДМЕНЫ_ПЕРЕЖИВШИЕ_ТЕСТ) - _ПОТОЛОК_ПЕЧАТИ
    if остаток > 0:
        terminalreporter.write_line(f"  … и ещё {остаток}")
