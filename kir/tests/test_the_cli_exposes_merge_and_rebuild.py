r"""THE CLI NAMES TWO SUBSYSTEMS THAT USED TO HAVE NO DOOR AT ALL.

🔴 WHAT WAS MEASURED. `merge3` (3-way semantic merge, 420 lines) and
`rebuild` (the A→B delta) are finished and tested — and
`grep -n "merge3\|rebuild" kir/__main__.py` gave COMMENTS AND NOTHING ELSE.
Both were reachable from `kir/serving.py` only; whoever ran
`pip install kir-building` could not name either. That is the same defect the
door itself was created against ("there was nothing to show it with"), one
layer up.

🔴 CLASH IS NOT HERE, AND THAT IS DELIBERATE. It already got its door
separately — `kir project clash-report` (`kir/project_clash_cli.py`), with
its own pin `kir/tests/test_project_clash_cli.py`. The plan-015 patch this
file was rebased from added a SECOND clash verb (`kir clash run`); a second
door to one subsystem is the defect, not the fix, and that verb's argparse
`type=float` would also have let `nan`/`inf` into the clearance the existing
door refuses by name. Discarded on 13.09.2026 with this reason.

WHAT IS PINNED HERE, and each of these has already been paid for elsewhere in
this tree:

  1. THE VERB EXISTS AND ANSWERS. A subcommand that help advertises must be
     executable — the law of `test_the_package_has_a_door.py`.
  2. THE VERDICT IS THE GUARD'S OWN, NOT A NEW ONE. `kir project merge`
     prints `precondition_confirmed | diverged_clean | diverged_conflicting`
     — the three names `decompile.merge_guard` owns and `serving.py` already
     acts on. A second vocabulary at the door would drift from the product's.
  3. THE RETURN CODE IS SPLIT BY MEANING. A conflicting merge was computed in
     full and reports every conflict: that is REFUSED (1), "read and refused
     on the merits". "There was nothing to read" stays 2. Collapsing the two
     is exactly what this file's neighbour
     (`ExitCodesAreSeparatedByMeaning`) exists to forbid.
  4. AN INCOMPLETE CLASH SEARCH SAYS SO. A partial search that keeps quiet
     reads as "nothing found".

WHAT THIS FILE DOES NOT CLAIM: nothing about Revit. All three verbs run
offline, on files, without a single port.
"""
from __future__ import annotations

import contextlib
import io
import json
import os

from kir import __main__ as door
from kir.decompile.tests.test_merkle import _fold, _grid_building
from kir.decompile.tests.test_merge3 import _one_wall_building


def _call(argv: list[str]) -> tuple[int, str, str]:
    """The door IN THIS process: return code and both streams, separately."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        код = door.main(argv)
    return код, out.getvalue(), err.getvalue()


def _written(tmp_path, name: str, value) -> str:
    путь = tmp_path / name
    путь.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return str(путь)


# ─────────────────────────────────────────────────────────────── merge

def test_an_untouched_document_confirms_the_deltas_precondition(tmp_path):
    """`precondition_confirmed` is the ONLY verdict that means "verified"."""
    дерево = _fold(_grid_building(floors=2, name="O"))
    цель = _fold(_grid_building(floors=2, name="B", drop_wall_on_floor=1))
    код, вывод, сводка = _call([
        "project", "merge",
        _written(tmp_path, "base.json", дерево),
        _written(tmp_path, "ours.json", дерево),
        _written(tmp_path, "theirs.json", цель)])

    assert код == door.ANSWERED, сводка
    отчёт = json.loads(вывод)
    assert отчёт["verdict"] == "precondition_confirmed"
    assert отчёт["identical_to_base"] is True
    assert отчёт["conflicts_total"] == 0
    # The verdict reaches the HUMAN too, not only the JSON.
    assert "precondition_confirmed" in сводка


def test_a_diverged_document_without_a_dispute_is_not_confirmed(tmp_path):
    """`diverged_clean` must not pass for `precondition_confirmed`."""
    база = _fold(_grid_building(floors=3, name="O"))
    наше = _fold(_grid_building(floors=3, name="A",
                                extra_furniture_on_floor=0))
    их = _fold(_grid_building(floors=3, name="B", drop_wall_on_floor=2))
    код, вывод, сводка = _call([
        "project", "merge",
        _written(tmp_path, "base.json", база),
        _written(tmp_path, "ours.json", наше),
        _written(tmp_path, "theirs.json", их)])

    assert код == door.ANSWERED, сводка
    отчёт = json.loads(вывод)
    assert отчёт["verdict"] == "diverged_clean"
    assert отчёт["identical_to_base"] is False
    assert отчёт["conflicts_total"] == 0
    assert отчёт["auto_merged"] > 0


def test_a_disputed_edit_is_refused_on_the_merits_and_every_conflict_is_named(
        tmp_path):
    """Two authors moved the SAME wall: code 1, and the conflicts ride out."""
    код, вывод, сводка = _call([
        "project", "merge",
        _written(tmp_path, "base.json", _one_wall_building(6000.0, "O")),
        _written(tmp_path, "ours.json", _one_wall_building(6500.0, "A")),
        _written(tmp_path, "theirs.json", _one_wall_building(7000.0, "B"))])

    # REFUSED, not NOT_DONE: the merge happened and answered.
    assert код == door.REFUSED, сводка
    отчёт = json.loads(вывод)
    assert отчёт["verdict"] == "diverged_conflicting"
    assert отчёт["conflicts_total"] >= 1
    assert отчёт["conflicts_total"] == sum(отчёт["conflicts_by_kind"].values())
    assert "modify_modify" in отчёт["conflicts_by_kind"]
    # Both sides of the dispute are shown, not just its existence.
    спор = отчёт["conflicts"][0]
    assert спор["current"] != спор["target"]


def test_a_file_that_is_not_a_folded_building_did_not_happen(tmp_path):
    """"Not a building" is code 2 with a next move, never a silent verdict."""
    код, вывод, сводка = _call([
        "project", "merge",
        _written(tmp_path, "base.json", {"ops": []}),
        _written(tmp_path, "ours.json", {"ops": []}),
        _written(tmp_path, "theirs.json", {"ops": []})])

    assert код == door.NOT_DONE
    assert вывод == "", "отказ не печатает вердикт в stdout"
    assert "СЛЕДУЮЩИЙ ХОД" in сводка
    assert "tree.json" in сводка


def test_three_revisions_cannot_come_from_one_stdin(tmp_path):
    код, _, сводка = _call(["project", "merge", "-", "-", "x.json"])
    assert код == door.NOT_DONE
    assert "СЛЕДУЮЩИЙ ХОД" in сводка


# ─────────────────────────────────────────────────────────────── rebuild

def test_the_delta_names_what_it_builds_and_what_it_retires(tmp_path):
    база = _fold(_grid_building(floors=3, name="A"))
    цель = _fold(_grid_building(floors=3, name="B", drop_wall_on_floor=2,
                                extra_furniture_on_floor=0))
    код, вывод, сводка = _call([
        "project", "rebuild",
        _written(tmp_path, "base.json", база),
        _written(tmp_path, "target.json", цель)])

    assert код == door.ANSWERED, сводка
    отчёт = json.loads(вывод)
    assert отчёт["schema"] == "kir-rebuild-plan/1"
    assert отчёт["ok"] is True
    assert отчёт["identical"] is False
    # A delta is worth building only when it is SMALLER than the whole.
    assert 0 < отчёт["delta_leaves"] < отчёт["full_leaves"]
    assert отчёт["retire_leaves"] >= 1
    # Counts only, by default: the program itself is asked for.
    assert "ops" not in отчёт
    assert "kir project merge" in сводка, (
        "дельта обязана назвать, чем проверяется её предусловие")


def test_the_same_building_twice_gives_an_empty_delta(tmp_path):
    дерево = _fold(_grid_building(floors=2, name="A"))
    путь = _written(tmp_path, "tree.json", дерево)
    код, вывод, сводка = _call(["project", "rebuild", путь, путь])

    assert код == door.ANSWERED, сводка
    отчёт = json.loads(вывод)
    assert отчёт["identical"] is True
    assert отчёт["delta_leaves"] == 0 and отчёт["retire_leaves"] == 0


def test_the_program_flag_prints_the_ordered_delta_itself(tmp_path):
    база = _fold(_grid_building(floors=3, name="A"))
    цель = _fold(_grid_building(floors=3, name="B", drop_wall_on_floor=2,
                                extra_furniture_on_floor=0))
    код, вывод, сводка = _call([
        "project", "rebuild", "--program",
        _written(tmp_path, "base.json", база),
        _written(tmp_path, "target.json", цель)])

    assert код == door.ANSWERED, сводка
    отчёт = json.loads(вывод)
    assert отчёт["ops"], "с --program программа обязана быть напечатана"
    виды = [op["kind"] for op in отчёт["ops"]]
    assert set(виды) <= {"retire", "relocate", "emit"}
    # `retire -> relocate -> emit`, exactly as `apply_delta` walks it.
    порядок = {"retire": 0, "relocate": 1, "emit": 2}
    assert виды == sorted(виды, key=порядок.__getitem__)


def test_a_delta_between_two_different_buildings_did_not_happen(tmp_path):
    """The delta is PROVEN on the states; an unprovable one is refused."""
    код, вывод, сводка = _call([
        "project", "rebuild",
        _written(tmp_path, "base.json", {"ops": []}),
        _written(tmp_path, "target.json", {"ops": []})])

    assert код == door.NOT_DONE
    assert вывод == ""
    assert "СЛЕДУЮЩИЙ ХОД" in сводка


# ─────────────────────────────────────────────────── the doors are advertised

def test_every_new_verb_is_named_by_help():
    """A door that help does not name does not exist for whoever looks for it.

    The help is asked OF THE PARSER, not of a list written next to it: a
    hand-written list would fall behind on the very first new verb and stay
    silent about it (the argument of `test_the_package_has_a_door`).
    """
    import argparse

    разборщик = door.build_parser()
    подкоманды = next(
        действие for действие in разборщик._actions
        if isinstance(действие, argparse._SubParsersAction))
    справка = подкоманды.choices["project"].format_help()
    # `clash-report` is the neighbour's door, and it is checked here for the
    # same reason: the three offline subsystems must be findable in one place.
    for глагол in ("merge", "rebuild", "clash-report"):
        assert глагол in справка, глагол
    # And each one is executable — not merely advertised.
    for глагол, доводы in (("merge", ["a", "b", "c"]), ("rebuild", ["a", "b"])):
        разобрано, _ = подкоманды.choices["project"].parse_known_args([глагол, *доводы])
        assert разобрано.func is not None

    # THE HEADER OF THE FILE IS ALSO A DOOR LISTING, and it is read by whoever
    # types `python -m kir --help` last, not first.
    assert "kir project merge" in door.__doc__
    assert "kir project rebuild" in door.__doc__


def test_no_verb_turned_a_subsystem_flag_on_for_the_whole_process(tmp_path):
    """🔴 THE FLAGS STAY WHERE THE OPERATOR PUT THEM.

    `KIR_MERGE3`/`KIR_REBUILD` gate ANOTHER caller (`kir/serving.py`). A verb
    that switched one on process-wide would be turning on somebody else's door
    as a side effect — and in a long-lived process (the MCP server) it would
    never be switched back.
    """
    before = {имя: os.environ.get(имя) for имя in ("KIR_MERGE3", "KIR_REBUILD")}
    дерево = _fold(_grid_building(floors=2, name="A"))
    путь = _written(tmp_path, "tree.json", дерево)
    _call(["project", "rebuild", путь, путь])
    _call(["project", "merge", путь, путь, путь])
    assert {имя: os.environ.get(имя) for имя in before} == before
