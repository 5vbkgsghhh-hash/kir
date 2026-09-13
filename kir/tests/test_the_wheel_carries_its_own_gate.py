"""THE WHEEL CARRIES ITS OWN GATE — OTHERWISE "KIR stands without KUKAI" IS UNVERIFIABLE BY WHOEVER INSTALLED IT.

🔴 WHY THIS WAS SET UP (01.09.2026), AND THE NUMBER THAT PAID FOR IT.

`gate_manifest.json` says, verbatim, that the suite runs «ВНУТРИ чистого
venv без КУКАЯ», and the paths are «относительно УСТАНОВЛЕННОГО пакета».
A measurement on a wheel built from this tree gave two numbers, and they
did not agree:

    suite files that reached the install     15 of 15   (`WHEEL_KEEP.json` works)
    the manifest reached it                  NO         (it sat at the REPOSITORY ROOT)

That is, an outside person had the suite, but no list of "what to run".
The instrument existed and could not be produced. The manifest was moved
into the package; this guard holds the link between three places, none of
which knows about the other two:

    manifest    WHAT must be run
    wheel.keep  WHAT travels into the wheel  (`build_support.wheel` trims tests)
    package     WHAT is actually on disk

If they diverge, the wheel ships either with a suite nothing can name, or
with a name nothing can open. Both outcomes are silent: the suite simply
never runs for whoever never sees this test.

🔴 WHAT THIS GUARD DOES NOT DO. It does NOT run the suite (that is
`python -m kir.selftest`) and does NOT claim the suite is green. It
answers the prior question: "is there a WHAT and a WITH-WHAT to run, for
whoever installed the package."
"""
from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import tomllib

import pytest

from kir import selftest

#: The package root — from `kir.__file__`, the same way the self-test gets it.
_ROOT = selftest.package_root()

#: The repository root. It is ABSENT from the install, and that is legal:
#: `pyproject.toml` stays in the tree. Checks that need it are SKIPPED
#: WITH A REASON, not silently made green — a silent skip is
#: indistinguishable from a passed check.
_REPO = _ROOT.parent
_KEEP_PATH = _REPO / "pyproject.toml"


def _keep() -> set[str]:
    return set(tomllib.loads(_KEEP_PATH.read_text(encoding="utf-8"))["tool"]["kir"]["wheel"]["keep"])


@pytest.mark.skipif(not (_REPO / "tools/installed_matches_revision.py").is_file(),
                    reason="archive comparison tool is source-checkout only")
def test_archive_reader_accepts_both_layouts_but_not_a_broken_new_one(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "kir_layout_archive_reader", _REPO / "tools/installed_matches_revision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "pyproject.toml"
    legacy = tmp_path / "WHEEL_KEEP.json"
    legacy.write_text('["kir/tests/old.py"]', encoding="utf-8")
    project.write_text('[project]\nname = "kir-building"\n', encoding="utf-8")
    assert module._wheel_keep(tmp_path) == {"kir/tests/old.py"}
    project.write_text('[tool.kir.wheel]\nkeep = ["kir/tests/new.py"]\n', encoding="utf-8")
    assert module._wheel_keep(tmp_path) == {"kir/tests/new.py"}
    project.write_text('[tool.kir.wheel]\n', encoding="utf-8")
    with pytest.raises(KeyError):
        module._wheel_keep(tmp_path)


@pytest.mark.skipif(not (_REPO / "examples/kir.project.json").is_file(),
                    reason="repository-viewer demo is source-checkout only")
def test_demo_manifest_entry_is_relative_to_its_new_directory():
    manifest = _REPO / "examples/kir.project.json"
    config = json.loads(manifest.read_text(encoding="utf-8"))
    entry = manifest.parent / config["entry"]
    assert entry.is_file()
    assert json.loads(entry.read_text(encoding="utf-8"))["ops"]


@pytest.mark.skipif(not (_REPO / "kir/tests/test_the_final_result_holds_from_an_installed_package.py").is_file(),
                    reason="full installed walkthrough is source-checkout only")
def test_installed_walkthrough_reads_geometry_from_the_packaged_extra(tmp_path):
    path = _REPO / "kir/tests/test_the_final_result_holds_from_an_installed_package.py"
    spec = importlib.util.spec_from_file_location("kir_installed_walkthrough_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "pyproject.toml"
    project.write_text('[project.optional-dependencies]\ngeometry = ["provider==1.2"]\n',
                       encoding="utf-8")
    assert module._geometry_requirements(tmp_path) == ["provider==1.2"]
    project.write_text('[project.optional-dependencies]\ngeometry = []\n', encoding="utf-8")
    with pytest.raises(AssertionError, match="geometry extra"):
        module._geometry_requirements(tmp_path)

    venv = tmp_path / "accepted-environment"
    library = venv / "lib/python3.12/site-packages"
    observed = {"prefix": str(venv), "purelib": str(library), "platlib": str(library),
                "file": str(library / "kir/__init__.py"), "tree_on_path": [],
                "kukai_importable": False, "version": "test"}
    module._assert_installed_origin(observed, str(venv))
    for changed in ({"prefix": str(tmp_path / "foreign")},
                    {"file": str(tmp_path / "foreign/site-packages/kir/__init__.py")},
                    {"purelib": str(tmp_path / "foreign/site-packages")},
                    {"kukai_importable": True}):
        with pytest.raises(AssertionError):
            module._assert_installed_origin({**observed, **changed}, str(venv))
    module._require_new_environment(venv)
    venv.mkdir()
    sentinel = venv / "must-not-change"
    sentinel.write_text("existing environment", encoding="utf-8")
    with pytest.raises(AssertionError, match="new environment path"):
        module._require_new_environment(venv)
    assert sentinel.read_text(encoding="utf-8") == "existing environment"


@pytest.mark.skipif(not (_REPO / "kir/tests/test_the_final_result_holds_from_an_installed_package.py").is_file(),
                    reason="full installed walkthrough is source-checkout only")
def test_installed_harness_keeps_partial_results_when_later_stage_fails(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from kir.tests import test_the_final_result_holds_from_an_installed_package as harness

    def fail(work, src, dist, steps):
        steps.update(stage="inspector", complex={"returncode": 0}, capture={"returncode": 0})
        raise AssertionError("inspector refused")

    monkeypatch.setattr(harness, "_prepare_installed", fail)
    with pytest.raises(AssertionError, match="inspector refused"):
        harness.installed.__wrapped__(SimpleNamespace(mktemp=lambda _: tmp_path))
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["failed_stage"] == "inspector"
    assert result["exception_type"] == "AssertionError"
    assert result["complex"]["returncode"] == result["capture"]["returncode"] == 0


#: 🔴 13.09.2026. A check stood here that the installed E2E's app probe reaped
#: its child process when the HTTP call after startup failed. The probe started
#: `python -m kir.app`; the browser window was removed by the owner's word, the
#: probe went with it, and so did this control over it.


#: 🔴 THE DENOMINATOR OF BOTH WALKS, MEASURED 02.09.2026: the suite's
#: ledger holds **15** names (`WHEEL_KEEP.json` holds 33). Both tests
#: below are one-sided: `lost == []` is true both when everything is
#: named and when there is NOTHING to name. An empty ledger is exactly
#: the refusal that this same file describes elsewhere as "the build
#: prints as zero reds"; the denominator sits right inside the read
#: itself, so no future reader of the ledger ever gets it empty and
#: silent.
_ИМЁН_НАБОРА_НЕ_МЕНЬШЕ = 12


def _manifest_names() -> list[str]:
    names, refusal = selftest.read_manifest(_ROOT)
    assert refusal is None, refusal
    assert len(names) >= _ИМЁН_НАБОРА_НЕ_МЕНЬШЕ, (
        f"ведомость назвала {len(names)} файлов при поле "
        f"{_ИМЁН_НАБОРА_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 15). Это заявление о "
        f"ХОДОКЕ: `lost == []` у обоих читателей ниже истинно и тогда, когда "
        f"называть просто нечего")
    return names


needs_repo = pytest.mark.skipif(
    not _KEEP_PATH.is_file(),
    reason=f"pyproject.toml недоступен ({_KEEP_PATH}) — это УСТАНОВКА, а не "
           "дерево; отбор состава колеса здесь не проверяется")


def test_the_manifest_lives_inside_the_package():
    """The manifest is PART of the package, or it never reaches whoever installs it.

    What is checked is its presence EXACTLY in the package directory, not
    "somewhere nearby": at the repository root it sat for a year and
    never once traveled into the wheel.
    """
    assert (_ROOT / selftest.MANIFEST_NAME).is_file(), (
        f"манифеста нет в пакете: {_ROOT / selftest.MANIFEST_NAME}. "
        "Набор ворот перестал быть предъявимым чужому человеку.")


def test_every_named_file_is_on_disk():
    """Every name in the manifest opens. A name with no file is a riddle, not a suite."""
    names = _manifest_names()
    gone = selftest.missing(_ROOT, names)
    assert gone == [], f"манифест называет файлы, которых нет в пакете: {gone}"


@needs_repo
def test_every_named_file_survives_the_wheel_pruner():
    """Suite ⊆ wheel.keep: what must run must also travel.

    🔴 DERIVED FROM TWO AUTHORITIES, NOT RETYPED AS A LIST. A list of
    names written out here by hand would be a third carrier of the same
    quantity and would silently diverge from both — a named defect of
    this tree.
    """
    keep = _keep()
    names = [f"kir/{n}" for n in _manifest_names()]
    lost = [n for n in names if n not in keep]
    assert lost == [], (
        "файл набора не назван в tool.kir.wheel.keep — `PrunedBuildPy` вырежет его "
        f"из колеса, и самотест у чужого человека откажет: {lost}")


@needs_repo
def test_the_pruner_keeps_what_the_named_files_import():
    """First-order closure: `conftest`, `__init__`, and their own helpers.

    Without them pytest will not even COLLECT the suite — and a
    collection failure prints as "no tests were collected", that is, as
    zero reds. What is checked is a PROPERTY ("this is imported by the
    suite"), not the shape of names.
    """
    keep = _keep()
    names = _manifest_names()
    need: set[str] = set()
    for rel in names:
        d = pathlib.Path(rel).parent
        for sibling in ("conftest.py", "__init__.py"):
            if (_ROOT / d / sibling).is_file():
                need.add(f"kir/{d}/{sibling}")
        tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mod = None
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
            elif isinstance(node, ast.Import):
                mod = node.names[0].name
            if not mod or not mod.startswith("kir."):
                continue
            cand = _REPO / (mod.replace(".", "/") + ".py")
            if cand.is_file():
                rel_cand = str(cand.relative_to(_REPO))
                if "tests/" in rel_cand or pathlib.Path(rel_cand).name.startswith("test_"):
                    need.add(rel_cand)
    lost = sorted(n for n in need if n not in keep)
    assert lost == [], (
        "набор импортирует тестовый файл, который не уезжает в колесо — "
        f"сборка набора у чужого человека упадёт: {lost}")


@needs_repo
def test_removing_native_readback_helper_breaks_the_installed_suite_contract(monkeypatch):
    """Reproduce the partial merge: the parity test arrived without its wheel helper."""
    helper = "kir/tests/emit_parity_fixtures/native_readback_counterfactual.py"
    keep = _keep()
    assert helper in keep
    test_the_pruner_keeps_what_the_named_files_import()
    monkeypatch.setitem(globals(), "_keep", lambda: keep - {helper})
    with pytest.raises(AssertionError, match="native_readback_counterfactual"):
        test_the_pruner_keeps_what_the_named_files_import()


def test_an_absent_manifest_is_a_named_refusal_not_an_empty_green(tmp_path):
    """🔴 CONTROL: there is no such thing as an empty green.

    Zero suite files must read as "there is no one to ask", not as
    "there are no reds". Checked by execution on an empty directory, not
    by argument.
    """
    names, refusal = selftest.read_manifest(tmp_path)
    assert names == []
    assert refusal is not None and "манифеста набора нет" in refusal
    assert "СЛЕДУЮЩИЙ ХОД" in refusal, "отказ обязан называть следующий ход"


def test_the_outcomes_are_three_and_distinct():
    """"Not judged" does not reduce to "judged and found": three outcomes, three numbers."""
    assert selftest.JUDGED_GREEN == 0
    assert selftest.JUDGED_RED == 1
    assert selftest.NOT_JUDGED == 2
    assert len({selftest.JUDGED_GREEN, selftest.JUDGED_RED,
                selftest.NOT_JUDGED}) == 3
