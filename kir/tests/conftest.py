"""A test that leaves global state behind names itself.

WHY THIS BELONGS HERE, NOT IN THE FOUR PATCHED-UP CALL SITES. Fixing the
victim hides the producer: the next leak will be exactly as invisible as
these four were before the measurement. The guard shifts the failure onto
whoever mutated.

WHAT THIS GUARD DOES NOT PROVE is named here, because a plausible and WRONG
cause was circulating nearby. It was believed the suite suffered an
"ordering epidemic": 82 failures without `-p no:randomly` versus 12 with it.
A measurement on 12.08.2026 refuted this — `pytest-randomly` is NOT INSTALLED
in the venv (`pip show` → "Package(s) not found"), so `-p no:randomly`
disables nothing, and the collection order with and without the flag is
BYTE FOR BYTE identical. The order here is deterministic on its own. So this
file was set up NOT for an ordering epidemic, but for the specific measured
defect below — and must not be cited as its cure.

The guard shifts the failure ONTO THE PRODUCER. A test that changed
`os.environ` and did not restore it fails itself — with the key's name and
the value left behind, because "a test leaked state" is a complaint, while
"this test left `KIR_REJECTIONS_PATH=/tmp/…` pointing at a removed tmpdir" is
a work order.

WHAT IS GUARDED AND WHY EXACTLY THIS. `os.environ` is not the only shared
process state, but it is the only one that SWITCHES PRODUCTION BEHAVIOR from
a test: `coverage_feed._DEFAULT is None` means "the feed is OFF," so a leaked
`KIR_REJECTIONS_PATH` does not just redirect the sink, it TURNS IT ON for
everything that runs afterward — and the refusal arm `compile_program`, the
suite's most-walked path, reads it. Module-level tables and caches are
deliberately excluded: they have no single shared address, and a guard that
pretended to be complete would be worse than none at all.

A BOUNDARY, stated out loud: the guard sees state AFTER the test, so a
mutation inside a test that the test itself restores is invisible to it —
and rightly so, it bothers no one. Nor does it catch a leak that happened at
module IMPORT time: by the time the first test runs, it is already part of
the baseline. Such spots are visible to a different instrument — an AST walk
over bare mutations.
"""
from __future__ import annotations

import hashlib
import os
import tempfile

import pytest

# ─── PROD `.env` MUST NOT DECIDE WHAT THIS SUITE CHECKS ──────────────────────
#
# WHAT HAPPENS WITHOUT THIS BLOCK (measured 12.08.2026). Any test whose
# import chain reaches `kukai.llm.client` pulls in litellm, and litellm
# calls `load_dotenv()` once, ON IMPORT. python-dotenv searches for the file
# by walking up FROM LITELLM'S OWN FILE, and litellm sits inside the shared
# venv within the prod tree — so the search lands on
# `/opt/kukai-rebuild1/backend/.env` and pours **129 keys of live
# configuration** into the process: `KUKAI_KIR_TOOL=stage2`,
# `KUKAI_TRUTH_GATE=enforce`, `KUKAI_WEAK_SANDBOX=1` — and live credentials.
#
# THIS IS NOT A PROPERTY OF THIS TREE. In the working tree where this was
# written, there is NO `.env` FILE AT ALL, and the keys still arrive: the
# venv is shared and sits inside prod. The very rule "the interpreter only
# from the prod venv," which keeps us honest about `shapely`, is what feeds
# live configuration into any checkout. Switching to another tree does not
# help — there is nowhere to stand on this box where this would not happen.
#
# WHY THE NEIGHBORING CONFTEST IS NOT A GOOD MODEL. `backend/tests/conftest.py`
# is described in the canon as "force-overrides the production .env to safe
# local defaults," but what it actually does is different: it monkeypatches
# FIVE settings (`KUKAI_AUTH_ENABLED`, `KUKAI_REMOTE_MODE`, `KUKAI_HOST`,
# `KUKAI_DEBUG`, `KUKAI_CORS_ORIGINS`) plus rewrites the DB address to
# `kukai_test`. Five keys out of 129. Copying it would mean leaving ~124 and
# both sets of credentials in place and getting a green fix that closes
# nothing.
#
# THE MECHANISM IS TAKEN FROM `kukai/rag/benchmark/hermeticity.py`, NOT
# INVENTED. There it is proven empirically and its order is LOAD-BEARING:
# first force the import so the one-time load happens, and only then push
# it out — `load_dotenv(override=False)` does not resurrect what was pushed
# out. The reverse order does not work at all.
#
# PROVENANCE BY OBSERVATION, NOT BY PATH. We do not read `.env` and do not
# know where it is: we snapshot the environment BEFORE the forced import,
# force it, and remove exactly what appeared, restoring exactly what
# changed. Such a signal cannot be fooled by the wrong path, and it does not
# touch what the developer set in their own shell themselves. Filter by
# provenance, not by appearance.
#
# NAMES, NEVER VALUES — a rule from the same module: among what gets pushed
# out there is an admin token and an API key.
_ENV_BEFORE_LITELLM = dict(os.environ)

try:
    import kukai.llm.client  # noqa: F401 — forcing the one-time load_dotenv NOW
except Exception as _exc:                                  # pragma: no cover
    # The import may not have happened (missing dependency, broken module).
    # This is NOT a reason to silently carry on: then the load will happen
    # later, from the very first test, and the snapshot will be useless. We
    # say so out loud rather than pretend to be clean.
    INJECTED_BY_DOTENV: tuple[str, ...] = ()
    DOTENV_NEUTRALISED = False
    _DOTENV_NOTE = f"litellm не импортировался ({type(_exc).__name__}): {_exc}"
else:
    _after = os.environ
    _appeared = [k for k in _after if k not in _ENV_BEFORE_LITELLM]
    _changed = {k: v for k, v in _ENV_BEFORE_LITELLM.items()
                if k in _after and _after[k] != v}
    for _k in _appeared:
        del os.environ[_k]
    os.environ.update(_changed)
    INJECTED_BY_DOTENV = tuple(sorted(_appeared))
    DOTENV_NEUTRALISED = True
    _DOTENV_NOTE = (
        f"убрано {len(_appeared)} ключей, восстановлено {len(_changed)}"
        if (_appeared or _changed) else "прод-.env не дотянулся: убирать нечего")


def pytest_report_header(config):
    """State in the run's header exactly what was done to the environment.

    Silent hygiene is indistinguishable from its absence: if this block ever
    stops firing, the header will change, and that will be noticed sooner
    than strange green tests.
    """
    return f"prod .env: {_DOTENV_NOTE}"


#: 🔴 THE REJECTIONS FEED IS DIVERTED TO A TEMP FILE ONCE, HERE (28.08.2026).
#:
#: Three test modules (`test_serving`, `test_faceref`, `test_v11_regressions`)
#: were doing this themselves — `os.environ.setdefault(...)` AT MODULE
#: LEVEL, and doing it correctly: without the diversion, `coverage_feed`
#: would take the real path on import and the suite would write into the
#: live corpus.
#:
#: But a module is imported the moment it is first touched — and it can be
#: touched by a LAZY import inside someone else's test. Then the
#: environment edit happens IN THE MIDDLE OF that test, and the guard below
#: accuses of the leak whoever merely happened to be nearby. This was paid
#: for twice on 28.08: `test_revit_warnings…` and
#: `test_plural_operand_authority`, and both times the red was not about
#: their own subject.
#:
#: `conftest` loads BEFORE the first test and before the first environment
#: snapshot, so doing the same thing here is harmless. The modules' own
#: `setdefault` is left in place: it becomes a no-op, but keeps protecting
#: them when run standalone without `conftest`.
os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

#: Keys that are allowed to change during a run — THE LIST IS CLOSED.
#: Empty, and this is a measurement, not an unfilled gap: as of 12.08.2026
#: not a single `kir/tests` test has a legitimate reason to leave a variable
#: behind. A new line here must arrive with a reason, or the guard will turn
#: into a place where inconvenient failures get dumped.
ALLOWED_TO_CHANGE: frozenset[str] = frozenset()

#: Variables set not by the test, but by the runner itself or an imported
#: library. They have nothing to do with test order.
#:
#: `PYTEST_CURRENT_TEST` — THE INSTRUMENT'S OWN NOISE, and it nearly cost the
#: entire finding. Pytest maintains this variable itself and changes it from
#: `(setup)` to `(teardown)` exactly between the snapshot and the check, so
#: the guard's first version turned red on EVERY test that has no
#: restoration of its own — i.e. almost the whole suite — and passed that
#: off as leaks. An instrument written to catch someone else's state first
#: caught its own.
_LIBRARY_NOISE: frozenset[str] = frozenset({
    "LITELLM_LOCAL_MODEL_COST_MAP",
    "PYTEST_CURRENT_TEST",
})


def _snapshot() -> dict[str, str]:
    return dict(os.environ)


def _облик(значение: str) -> str:
    """THE SHAPE of a value without the value itself: length and a short
    digest.

    🔴 VALUES ARE NOT PRINTED HERE, AND THIS WAS PAID FOR BY A RUN ON
    01.09.2026. The first edition printed `{key}={value!r}`, and on the full
    suite the guard dumped the product environment's contents into the
    report — including an admin token and a device identifier. A report
    travels into logs, into summaries, and into other people's hands.

    This is a NAMED form of this tree's own, and the canon already carries
    it on another guard: an instrument written against a leak BECAME ITS
    CARRIER. There, the first edition searched for the literal id and
    printed that same one; here, it printed the value it caught. One genus,
    two places.

    Exactly two things are needed for triage: THE NAME and WHETHER the
    value changed. The digest answers the second without giving up the
    first; the length catches the "became empty" case. The secret itself is
    NEVER needed to fix the test.
    """
    if значение == "":
        return "пусто"
    d = hashlib.sha256(значение.encode("utf-8", "replace")).hexdigest()[:8]
    return f"{len(значение)} знак(ов), sha256/8 {d}"


def _describe(before: dict[str, str], after: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for key in sorted(after.keys() - before.keys()):
        if key in ALLOWED_TO_CHANGE or key in _LIBRARY_NOISE:
            continue
        lines.append(f"  ПОСТАВЛЕНА {key} ({_облик(after[key])})")
    for key in sorted(before.keys() - after.keys()):
        if key in ALLOWED_TO_CHANGE or key in _LIBRARY_NOISE:
            continue
        lines.append(f"  УДАЛЕНА    {key} (было {_облик(before[key])})")
    for key in sorted(before.keys() & after.keys()):
        if before[key] == after[key]:
            continue
        if key in ALLOWED_TO_CHANGE or key in _LIBRARY_NOISE:
            continue
        lines.append(
            f"  ИЗМЕНЕНА   {key}: {_облик(before[key])} -> {_облик(after[key])}")
    return lines


@pytest.fixture(autouse=True)
def _environment_is_returned_as_found(request):
    before = _snapshot()
    yield
    changes = _describe(before, _snapshot())
    if not changes:
        return
    raise AssertionError(
        f"тест оставил за собой окружение процесса — следующий тест увидит "
        f"чужое состояние, и его падение будет выглядеть его собственным:\n"
        + "\n".join(changes)
        + "\n\nВернуть на место: `monkeypatch.setenv/delenv`, "
          "`mock.patch.dict(os.environ, ...)` или `try/finally`. "
          "Если ключ обязан пережить тест — назвать его в "
          "`ALLOWED_TO_CHANGE` этого conftest с причиной."
    )
