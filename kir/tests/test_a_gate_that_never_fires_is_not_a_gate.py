"""A GATE THAT DOES NOT RUN IS NOT A GATE, IT IS A NAME.

🔴 WHY THIS FILE (04.09.2026). `.github/workflows/kir-evidence.yml` was
written for the KUKAI monorepo, where KIR lived in `backend/kukai/ir/`.
After the 27.08 split, the root became `kir/`, `tools/`, `connector/` —
but the `paths:` filters remained unchanged. Measured by parsing both
blocks against `git ls-files`:

    `pull_request` block   39 patterns, matching NO tree file at all: 35
    `push` block           36 patterns, not matching:                32
    a diff to `kir/compiler.py` triggers the gate:                   NO

That is, editing the compiler did not trigger the compiler's gate AT ALL,
and this violates the rule recorded in that very file by its own author:
"a rule that never runs on the change it guards is not a gate."

The second instrument of the same shape is the evidence manifest
`kir_evidence_manifest.py`. It signs the claim "the green runs pertain to
this tree," computing sha256 over its own set of paths. The number of
`kir/` paths in that set was ZERO, and this was verified not by reading but
by outcome: on a frozen copy of HEAD, a one-byte edit to
`kir/compiler.py` left the signed digest BYTE-FOR-BYTE THE SAME
(`115ac611c1237bc91b74ba91…` before and after). Only 4 files out of 1149
were covered.

Both blind spots were GREEN and, moreover, AGREED with each other: the
existing ratchet `test_ci_evidence_contract.py` requires the manifest's set
to be present in the workflow's `paths:` — and the requirement was
satisfied, because both described the same dead tree. Agreement between two
instruments about a nonexistent subject is exactly the form for which this
file was set up.

What is asked here is a PROPERTY, not an appearance: not "is the string
`kir/**` present in the list," but "does the gate run on a compiler edit
and stay silent on someone else's," "does a compiler edit move the signed
digest."
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/kir-evidence.yml"
MANIFEST = ROOT / ".github/scripts/kir_evidence_manifest.py"

#: The `.github` directory does NOT ride in the wheel (`WHEEL_KEEP.json`),
#: so a stranger who installed the package from the network does not have
#: these files, and there is nothing to assert about them. A skip WITH A
#: REASON, not a silent green.
if not WORKFLOW.is_file() or not MANIFEST.is_file():
    pytest.skip(
        f"улики CI живут в исходном дереве ({ROOT/'.github'}), в поставленном "
        f"пакете их нет — утверждать не о чем",
        allow_module_level=True)


# ── path matching per GitHub filter rules ─────────────────────────────────────
def _в_регексп(шаблон: str) -> re.Pattern[str]:
    """`**` crosses `/`, `*` and `?` do not. GitHub's rule, not ours."""
    куски, i = [], 0
    while i < len(шаблон):
        if шаблон.startswith("**", i):
            куски.append(".*")
            i += 2
        elif шаблон[i] == "*":
            куски.append("[^/]*")
            i += 1
        elif шаблон[i] == "?":
            куски.append("[^/]")
            i += 1
        else:
            куски.append(re.escape(шаблон[i]))
            i += 1
    return re.compile("^" + "".join(куски) + "$")


def _совпадает(шаблон: str, путь: str) -> bool:
    return bool(_в_регексп(шаблон).match(путь))


def _блоки_paths() -> list[list[str]]:
    """Both `paths:` lists — a custom parse, without pyyaml.

    🔴 WHY NOT `yaml.safe_load`: `pyyaml` is not declared as a package
    dependency (`pyproject.toml`), and a test pulling in an undeclared one
    would go red for a stranger for a reason unrelated to the subject.
    """
    блоки: list[list[str]] = []
    текущий: list[str] | None = None
    for строка in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if строка.strip() == "paths:":
            текущий = []
            блоки.append(текущий)
            continue
        if текущий is None:
            continue
        голая = строка.strip()
        if голая.startswith("#") or not голая:
            continue
        совпало = re.fullmatch(r"-\s+'([^']+)'", голая)
        if совпало:
            текущий.append(совпало.group(1))
        else:
            текущий = None
    return блоки


def _отслеживаемые() -> list[str]:
    return subprocess.check_output(
        ["git", "ls-files"], cwd=ROOT, text=True).split()


def _манифест():
    spec = importlib.util.spec_from_file_location(
        "kir_evidence_manifest_gate", MANIFEST)
    assert spec is not None and spec.loader is not None
    модуль = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(модуль)
    return модуль


# ── 1. the gate runs on the subject it exists to guard ───────────────────────
def test_a_change_to_the_compiler_fires_the_gate():
    блоки = _блоки_paths()
    assert len(блоки) == 2, (
        f"ожидались блоки pull_request и push: {len(блоки)}")
    for n, шаблоны in enumerate(блоки, 1):
        сработали = [ш for ш in шаблоны if _совпадает(ш, "kir/compiler.py")]
        assert сработали, (
            f"блок {n}: правка `kir/compiler.py` не запускает ворота "
            f"компилятора ни одним из {len(шаблоны)} шаблонов — это ровно "
            f"дефект 04.09.2026")


def test_a_foreign_path_does_not_fire_the_gate():
    """🔴 A CONTROL IN THE OTHER DIRECTION: a filter that catches everything is not a filter.

    Prose is not part of the set: of the six tests MENTIONING `docs/`, ZERO
    read it — all six mentions sit in docstrings (measured 04.09). An edit
    there does not move the run's outcome, so it must not burn CI minutes
    either.
    """
    for чужой in ("docs/x.md", "README.md", "KIR_PLAN.md", "LICENSE"):
        for n, шаблоны in enumerate(_блоки_paths(), 1):
            сработали = [ш for ш in шаблоны if _совпадает(ш, чужой)]
            assert not сработали, (
                f"блок {n}: `{чужой}` запускает ворота через {сработали}")


def test_no_declared_path_is_dead():
    """A pattern matching NO file in the tree at all is a dead layout.

    This exact instrument is what measures the defect: 35 of 39 and 32 of
    36 before the fix.
    """
    файлы = _отслеживаемые()
    for n, шаблоны in enumerate(_блоки_paths(), 1):
        мёртвые = [ш for ш in шаблоны
                   if not any(_совпадает(ш, f) for f in файлы)]
        assert not мёртвые, (
            f"блок {n}: шаблонов, которым не отвечает ни один отслеживаемый "
            f"файл, — {len(мёртвые)} из {len(шаблоны)}: {мёртвые}")


def test_both_trigger_blocks_carry_the_same_list():
    """One diff must decide the same way on a PR and on a push.

    A discrepancy ALREADY EXISTED and cost three patterns out of 39:
    `compiler_contract.py`, `compiler_contracts/**` and
    `tests/test_compiler_contract.py` were present only in `pull_request`.
    YAML anchors do not fix this — GitHub Actions does not support them —
    so it is fixed by a number.
    """
    первый, второй = _блоки_paths()
    assert первый == второй, (
        f"только в pull_request: {sorted(set(первый) - set(второй))}; "
        f"только в push: {sorted(set(второй) - set(первый))}")


# ── 2. a job that CAN ACTUALLY run to completion ──────────────────────────────
def _тело_работы(имя: str) -> str:
    """The job's text TOGETHER WITH the comment header right above it.

    The header is included on purpose: the declaration "this job is dead
    and why" is written as a comment ABOVE the job's key, and an instrument
    reading only the body would not see the declaration and would demand it
    be written a second time.
    """
    строки = WORKFLOW.read_text(encoding="utf-8").splitlines(keepends=True)
    ключ = next(i for i, с in enumerate(строки) if с.startswith(f"  {имя}:"))
    начало = ключ
    while начало > 0 and строки[начало - 1].startswith("  #"):
        начало -= 1
    конец = len(строки)
    for i in range(ключ + 1, len(строки)):
        if re.fullmatch(r"  [a-z][\w-]*:\n", строки[i]):
            конец = i
            break
    # the header of the next job belongs to IT, not to this one
    while конец - 1 > ключ and строки[конец - 1].startswith("  #"):
        конец -= 1
    return "".join(строки[начало:конец])


_ПУТЬ = re.compile(r"(?<![\w.$/@-])([A-Za-z0-9_][A-Za-z0-9_.-]*"
                   r"(?:/[A-Za-z0-9_.-]+)+)")
_ФАЙЛ = re.compile(r"(?<![\w.$/@-])([A-Za-z0-9_][A-Za-z0-9_.-]*"
                   r"\.(?:py|toml|txt|json|in|cfg))(?![\w.-])")


def _пути_работы(тело: str) -> set[str]:
    """The paths the job WALKS, taken from `run:` and `with:` lines.

    Comments are discarded ON PURPOSE: a path in a comment is NARRATION,
    and the canon (`test_the_package_does_not_know_the_host`) requires
    leaving it verbatim. An instrument that does not distinguish a route
    from a story about a route would demand erasing the evidence — this
    class of error has already been paid for in the tree.
    """
    строки = []
    for сырая in тело.splitlines():
        без_коммента = сырая.split("#", 1)[0]
        # 🔴 AN OUTPUT IS NOT AN INPUT. `--output
        # kir-evidence-provenance.json` and the `path:` on the upload name a
        # file that the job CREATES; requiring it to exist in the tree
        # would be asking the wrong question. The distinction is drawn by
        # the WAY IT IS MENTIONED, not by the file's name.
        if "--output" in сырая or re.match(r"\s*path:", без_коммента):
            continue
        строки.append(без_коммента)
    очищено = "\n".join(строки)
    найдено = set(_ПУТЬ.findall(очищено)) | set(_ФАЙЛ.findall(очищено))
    return {п for п in найдено
            if not п.startswith(("actions/", "http"))
            and "://" not in п}


def test_the_offline_job_names_no_path_that_is_not_there():
    """🔴 THE INSTRUMENT THAT WOULD HAVE CAUGHT `working-directory: backend`.

    The `backend` directory has not existed in this repository for a
    single day since the split, and the job entered it as its VERY FIRST
    action and installed dependencies from `requirements.txt`, which is
    also absent here. The instrument's question is not "is it written
    nicely," but "does what is named actually exist."
    """
    тело = _тело_работы("offline")
    assert "working-directory" not in тело, (
        "работа входит в каталог; в этом дереве корень репозитория и есть "
        "корень пакета")
    отсутствуют = sorted(п for п in _пути_работы(тело)
                         if not (ROOT / п).exists())
    assert not отсутствуют, (
        f"работа `offline` называет несуществующее: {отсутствуют}")


def test_the_provenance_job_names_no_path_that_is_not_there():
    тело = _тело_работы("provenance")
    отсутствуют = sorted(п for п in _пути_работы(тело)
                         if not (ROOT / п).exists())
    assert not отсутствуют, (
        f"работа `provenance` называет несуществующее: {отсутствуют}")


def test_the_six_version_job_uses_existing_standalone_compiler_inputs():
    """The old host-only job is replaced, not permanently excused by a comment."""
    тело = _тело_работы("generated-csharp-6x")
    assert "backend/" not in тело and "kukai.ir" not in тело
    for path in (".github/scripts/Kir.CI.References.csproj",
                 "connector/revit/tests/CompilerConformance.Tests/CompilerConformance.Tests.csproj",
                 "kir/tests/test_connector_compiler_conformance.py"):
        assert path in тело, path
        assert (ROOT / path).is_file(), path
    assert "revit_refs.require(versions)" in тело
    assert "continue-on-error" not in тело


# ── 3. the evidence signature stands under the tree the run is actually about ─
def test_the_signed_digest_covers_the_compiler():
    м = _манифест()
    пути = м.tracked_source_paths()
    assert пути, "множество улик пусто — подписывать нечего"
    свои = [п for п in пути if п.as_posix().startswith("kir/")]
    assert свои, (
        "в подписанном множестве НЕТ НИ ОДНОГО файла пакета — ровно состояние "
        "04.09, когда покрыто было 4 файла из 1149 и все четыре в `.github/`")
    assert Path("kir/compiler.py") in пути, "компилятор не покрыт подписью"


def test_no_manifest_entry_addresses_a_dead_layout():
    """A deliberately dead path is not listed in the evidence set.

    What is asked is a PROPERTY (does such a file exist), not an
    appearance (does the string start with `backend/`): a guard that knows
    yesterday's literal will not see tomorrow's.
    """
    м = _манифест()
    файлы = _отслеживаемые()
    мёртвые = [п for п in (*м.SOURCE_PREFIXES, *sorted(м.SOURCE_FILES))
               if not any(f == п or f.startswith(п) for f in файлы)]
    assert not мёртвые, f"множество улик адресует несуществующее: {мёртвые}"


def test_an_edit_to_the_compiler_moves_the_signed_digest(tmp_path):
    """🔴 FAIL CONTROL FOR THE SIGNATURE: the digest must MOVE.

    Measured on a frozen copy of HEAD (`git archive`) on 04.09: with the
    old set, a one-byte edit to `kir/compiler.py` left the digest THE SAME;
    with the current one, it moves it. Here the same assertion is executed
    without a copy of the tree: the same function is computed on two states
    of one file.
    """
    м = _манифест()
    (tmp_path / "kir").mkdir()
    цель = Path("kir/compiler.py")
    исходный, м.ROOT = м.ROOT, tmp_path
    try:
        (tmp_path / цель).write_text("ЭМИТТЕР A\n", encoding="utf-8")
        первый = м.source_tree_digest([цель])
        (tmp_path / цель).write_text("ЭМИТТЕР B\n", encoding="utf-8")
        второй = м.source_tree_digest([цель])
    finally:
        м.ROOT = исходный
    assert первый != второй, (
        "подпись не различает две разные версии компилятора — она стоит не "
        "под деревом, а под своим именем")


def test_the_matcher_itself_can_say_no():
    """🔴 WITHOUT THIS, THE WHOLE FILE IS A TAUTOLOGY.

    All the assertions above rest on `_совпадает`. A matcher that always
    answers "yes" would make "the gate runs" true by construction, and
    "an unrelated path does not trigger it" the only thing that could turn
    red. So the matcher itself is asked for BOTH answers, and the `*` vs
    `**` rule (a star does not cross `/`) as well: `docs/x.md` rests on it.
    """
    assert _совпадает("kir/**", "kir/compiler.py")
    assert _совпадает("kir/**", "kir/tests/a/b/c.py")
    assert not _совпадает("kir/**", "docs/x.md")
    assert not _совпадает("kir/*", "kir/tests/deep.py"), (
        "одиночная звезда обязана останавливаться на `/`")
    assert _совпадает("setup.py", "setup.py")
    assert not _совпадает("setup.py", "kir/setup.py")
