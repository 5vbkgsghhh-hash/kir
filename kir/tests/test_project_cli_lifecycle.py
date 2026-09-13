"""Saved authoring lifecycle through real CLI boundaries, without native writes."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from kir import __main__ as cli
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision


ROOT = Path(__file__).resolve().parents[2]


def _call(args, source=""):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(sys, "stdin", io.StringIO(source))
            code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


def _fresh(args, source=""):
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-m", "kir", *args], input=source,
                            text=True, capture_output=True, cwd=ROOT, env=env, timeout=30)
    return result.returncode, result.stdout, result.stderr


def _project():
    return ProjectRevision("cli-history", [ModuleDefinition("m")], [ModuleInstance(
        "section-a", "m", {"level": {"op": "create_level", "name": "Base", "elev_mm": 0}})])


def _change(project, elevation):
    return project.replace_instance(ModuleInstance(
        "section-a", "m", {"level": {"op": "create_level", "name": "Base", "elev_mm": elevation}}),
        expected_revision=project.revision_id)


def _successful(result):
    code, output, error = result
    assert code == cli.ANSWERED, error
    return json.loads(output)


def test_history_survives_processes_and_an_old_retry_never_rewinds_head(tmp_path):
    database = str(tmp_path / "проект ?# history.sqlite")
    initial = _project()
    first = _change(initial, 3000)
    second = _change(first, 4200)
    created = _successful(_fresh(["project", "init", database, "-"], initial.dumps()))
    assert created["revision_id"] == initial.revision_id
    assert created["native_published"] is False
    for before, proposed in ((initial, first), (first, second)):
        receipt = _successful(_fresh([
            "project", "commit", database, "-", "--expected", before.revision_id,
        ], proposed.dumps()))
        assert receipt["inserted"] is True
        assert receipt["head_revision"] == proposed.revision_id
    retry = _successful(_fresh([
        "project", "commit", database, "-", "--expected", initial.revision_id,
    ], first.dumps()))
    assert retry["inserted"] is False
    assert retry["revision_id"] == first.revision_id
    assert retry["head_revision"] == second.revision_id
    head = _successful(_fresh(["project", "head", database]))
    assert head == second.to_dict()
    history = _successful(_fresh(["project", "history", database]))
    assert [item["revision_id"] for item in history["revisions"]] == [
        initial.revision_id, first.revision_id, second.revision_id]
    assert "ops" not in history["revisions"][0]


def test_stale_agent_proposal_is_refused_without_losing_the_winners_work(tmp_path):
    database = str(tmp_path / "project.sqlite")
    initial = _project()
    winner, stale = _change(initial, 3000), _change(initial, 5000)
    _successful(_call(["project", "init", database, "-"], initial.dumps()))
    _successful(_call(["project", "commit", database, "-", "--expected", initial.revision_id],
                      winner.dumps()))
    code, output, error = _fresh([
        "project", "commit", database, "-", "--expected", initial.revision_id,
    ], stale.dumps())
    assert code == cli.REFUSED and not output
    assert "сохранение отвергнуто" in error
    assert _successful(_call(["project", "head", database])) == winner.to_dict()
    assert len(_successful(_call(["project", "history", database]))["revisions"]) == 2


def test_checkout_and_read_commands_do_not_modify_the_database(tmp_path):
    database = tmp_path / "project.sqlite"
    initial = _project()
    changed = _change(initial, 3000)
    _successful(_call(["project", "init", str(database), "-"], initial.dumps()))
    _successful(_call(["project", "commit", str(database), "-", "--expected", initial.revision_id],
                      changed.dumps()))
    original_bytes = database.read_bytes()
    checked_out = _successful(_fresh(["project", "checkout", str(database), initial.revision_id]))
    assert checked_out == initial.to_dict()
    _successful(_fresh(["project", "history", str(database)]))
    assert _successful(_fresh(["project", "head", str(database)])) == changed.to_dict()
    assert database.read_bytes() == original_bytes


@pytest.mark.parametrize("action", ["head", "history", "checkout"])
def test_reading_missing_store_does_not_create_it(tmp_path, action):
    database = tmp_path / "missing.sqlite"
    args = ["project", action, str(database)]
    if action == "checkout":
        args.append("a" * 64)
    code, output, error = _call(args)
    assert code == cli.NOT_DONE and not output and error
    assert not database.exists()


@pytest.mark.parametrize("source", ["not JSON", "{}", "null"])
def test_malformed_initial_project_does_not_create_a_store(tmp_path, source):
    database = tmp_path / "new.sqlite"
    code, output, error = _call(["project", "init", str(database), "-"], source)
    assert code == cli.NOT_DONE and not output and error
    assert not database.exists()


def test_init_does_not_replace_an_existing_unrelated_file(tmp_path):
    database = tmp_path / "keep.txt"
    database.write_bytes(b"the user's existing file")
    code, output, error = _call(["project", "init", str(database), "-"], _project().dumps())
    assert code == cli.REFUSED and not output and error
    assert database.read_bytes() == b"the user's existing file"


def test_a_saved_draft_is_not_implicitly_validated_or_executed(tmp_path):
    database = str(tmp_path / "draft.sqlite")
    draft = ProjectRevision("draft", [ModuleDefinition("m")], [ModuleInstance(
        "i", "m", {"unresolved": {"op": "not_a_registered_operation"}})])
    receipt = _successful(_call(["project", "init", database, "-"], draft.dumps()))
    assert receipt["native_published"] is False
    loaded = _successful(_call(["project", "head", database]))
    assert loaded == draft.to_dict()
    assert _call(["project", "export", "-"], json.dumps(loaded))[0] == cli.REFUSED


def test_unknown_revision_is_a_read_failure_and_does_not_move_head(tmp_path):
    database = str(tmp_path / "project.sqlite")
    initial = _project()
    _successful(_call(["project", "init", database, "-"], initial.dumps()))
    code, output, error = _call(["project", "checkout", database, "a" * 64])
    assert code == cli.NOT_DONE and not output and error
    assert _successful(_call(["project", "head", database])) == initial.to_dict()


def test_diff_cli_names_addressed_changes_without_claiming_native_execution(tmp_path):
    from kir.project_diff import diff_projects

    initial = _project()
    changed = _change(initial, 3000)
    source_file = tmp_path / "before.json"
    source_file.write_text(initial.dumps(), encoding="utf-8")
    code, output, error = _fresh(["project", "diff", str(source_file), "-"], changed.dumps())
    assert code == cli.ANSWERED, error
    assert json.loads(output) == diff_projects(initial, changed).to_dict()
    assert "не исполнимый patch Revit" in error


def test_diff_rejects_two_stdin_inputs_instead_of_comparing_with_empty_input():
    code, output, error = _call(["project", "diff", "-", "-"], _project().dumps())
    assert code == cli.NOT_DONE and not output
    assert "одного stdin" in error


def test_diff_rejects_different_project_identities(tmp_path):
    first = _project()
    other = ProjectRevision("other", first.modules, first.instances)
    source_file = tmp_path / "before.json"
    source_file.write_text(first.dumps(), encoding="utf-8")
    code, output, error = _call(["project", "diff", str(source_file), "-"], other.dumps())
    assert code == cli.REFUSED and not output and error


def test_residential_example_saves_all_ancestors_not_just_the_latest_json(tmp_path):
    database = tmp_path / "residential.sqlite"
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    args = [sys.executable, str(ROOT / "examples" / "residential_project.py"),
            "--stage", "changed", "--store", str(database)]
    authored = subprocess.run(args, text=True, capture_output=True, cwd=ROOT,
                              env=env, timeout=30)
    assert authored.returncode == 0, authored.stderr
    selected = ProjectRevision.loads(authored.stdout)
    assert _successful(_fresh(["project", "head", str(database)])) == selected.to_dict()
    history = _successful(_fresh(["project", "history", str(database)]))["revisions"]
    assert len(history) == 3 and history[0]["parent_revision"] is None
    assert history[-1]["revision_id"] == selected.revision_id
    concept = _successful(_fresh(["project", "checkout", str(database), history[0]["revision_id"]]))
    assert len(ProjectRevision.from_dict(concept).to_program()["ops"]) == 3
    before = database.read_bytes()
    repeated = subprocess.run(args, text=True, capture_output=True, cwd=ROOT,
                              env=env, timeout=30)
    assert repeated.returncode == cli.NOT_DONE and not repeated.stdout
    assert database.read_bytes() == before


def test_example_history_failure_keeps_and_names_the_committed_prefix(tmp_path, monkeypatch, capsys):
    from examples import residential_project
    from kir.project_store import ProjectStore, StoreBusy

    def fail_commit(*args, **kwargs):
        raise StoreBusy("injected unavailable writer lock")

    monkeypatch.setattr(ProjectStore, "commit", fail_commit)
    database = tmp_path / "prefix.sqlite"
    with pytest.raises(SystemExit) as failed:
        residential_project.main(["--stage", "changed", "--store", str(database)])
    assert failed.value.code == cli.NOT_DONE
    captured = capsys.readouterr()
    assert not captured.out and "saved prefix may exist" in captured.err
    stored = ProjectStore.open(database)
    assert len(stored.history()) == 1
    assert len(stored.head().to_program()["ops"]) == 3
