# -*- coding: utf-8 -*-
"""A BOUNDARY NUMBER MUST BE ABOUT THE PRODUCT, NOT ABOUT OUR OWN SCRATCH FILES.

🔴 WHAT STARTED THIS FILE (2026-09-07). The `oss_boundary_walk()` walk went
over the whole repository and cut directories BY NAME. Measurement: 19,346
files total, of which inside `.work/` — 17,814 (**92.1%**), product — 1,532;
`venv` was in the name list, but `venv-clean` slipped past it, and vendored
`pip/_vendor` rode along in the walk whole. The `_OSS_WALK_FLOOR = 250`
threshold turned out to be overshot 77-fold — by garbage, meaning it had
stopped guarding: it would not go red even if the product collapsed to
three files.

But the CONSEQUENCE mattered more than the count. The NUMERATOR was also
inflated: of 16 non-test hits, 11 came from `.work/`, and the ONE genuine
finding was drowning among the false ones; in the test-file line, of 36
hits, 6 were product and 30 were tree copies and foreign venvs. **A leaky
denominator does not just inflate the number — it hides the genuine finding
inside the false ones.** The instrument was RIGHT, and its truth could not
be read.

🔴 THE PIN DOES NOT WRITE INTO THE REAL TREE. The first edition placed
probe files straight into `docs/` and `kir/tests/` — and hit permissions
(a root-owned tree), which was lucky: editing the tree WHILE a run is in
progress is exactly the ordering mistake this same shift had already made.
So the walk is aimed at a SYNTHETIC tree in a temporary directory, where
the seeding is known exactly.
"""
from __future__ import annotations

import subprocess

import pytest

from kir.instruments import canon_state as CS

#: A synthetic hex next to the word «admin» — a sample of a GENUINE finding.
#: Synthetic on purpose: a pin has no right to carry someone else's secret,
#: and it is caught by the same rule (`DEVICE_RE` outside `_DIGEST_CTX`) as a
#: real one. The real carrier (`docs/laws/KIR_MASTER_DESIGN.md:61`) has
#: already been replaced in the tree with a marker.
HEX = "0f" * 16
ADMIN_LINE = "- I6 Live только admin-устройство %s; kill-switch\n" % HEX


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """Synthetic tree: product times a tree copy in `.work/` times a foreign environment."""
    root = tmp_path / "repo"
    # PRODUCT: one non-test document and one test — one hit each.
    _write(root / "docs" / "LAW.md", ADMIN_LINE)
    _write(root / "kir" / "__init__.py", "")
    _write(root / "kir" / "tests" / "test_fixture.py", 'GUID = "%s"\n' % HEX)
    _write(root / "kir" / "clean.py", "# без литералов\n")
    # SCRATCH: a full copy of the product in the working directory — this is how the number got inflated.
    _write(root / ".work" / "frozen" / "docs" / "LAW.md", ADMIN_LINE)
    _write(root / ".work" / "frozen" / "kir" / "tests" / "test_fixture.py",
           'GUID = "%s"\n' % HEX)
    # A FOREIGN ENVIRONMENT under a name that is not in the name list.
    _write(root / "venv-clean" / "pyvenv.cfg", "home = /usr\n")
    _write(root / "venv-clean" / "lib" / "python3.12" / "site-packages" /
           "vendored" / "x.py", 'BAD = "%s"\n' % HEX)
    _write(root / ".gitignore", ".work/\nvenv-clean/\n")
    monkeypatch.setattr(CS, "REPO", str(root))
    monkeypatch.setattr(CS, "PKG", str(root / "kir"))
    return root


def _git(root, *args):
    return subprocess.run(("git", *args), cwd=str(root), capture_output=True,
                          text=True, timeout=30)


def test_scratch_and_environments_do_not_enter_the_product_number(tree):
    """The seeding is known exactly: two product hits, zero scratch hits."""
    _git(tree, "init", "-q")
    _git(tree, "config", "user.email", "pin@example.invalid")
    _git(tree, "config", "user.name", "pin")
    _git(tree, "add", "-A")

    walk = CS.oss_boundary_walk()
    assert walk["product_by"].startswith("git ls-files"), walk["product_by"]
    # 🔴 EXACTLY ONE ON EACH SIDE. The tree copy in `.work/` carries the same
    # two literals, the foreign environment a third; none should be counted.
    assert walk["hits_all"] == 1 and walk["files_all"] == ["docs/LAW.md"], walk
    assert walk["hits_tests"] == 1, walk
    assert walk["files_tests"] == ["kir/tests/test_fixture.py"], walk
    # The denominator is about the product too: copies and venvs do not enter it.
    # 🔴 THE NUMBER IS 6, NOT 4, AND THIS IS A PROPERTY OF THE INSTRUMENT WORTH NAMING:
    # `seen` is counted by BOTH walks — over `REPO` (4 files: `docs/LAW.md`,
    # `kir/__init__.py`, `kir/clean.py`, `kir/tests/test_fixture.py`) and over
    # `PKG` (the same `kir/*.py` minus tests, 2 more). That is, the package's
    # files land in the denominator TWICE. This makes the `_OSS_WALK_FLOOR`
    # threshold softer than it reads; I did not change the count here — that
    # would shift the canon's number once more, and the subject of this patch
    # is different. Named, not touched.
    assert walk["seen"] == 6, walk["seen"]
    assert walk["seen_scratch"] == 0, walk["seen_scratch"]


def test_the_same_tree_without_git_falls_back_to_the_path_and_says_so(tree):
    """git gave no answer — we divide by path, and this is NAMED, not silently substituted."""
    walk = CS.oss_boundary_walk()      # the repository is not initialized
    assert walk["product_by"] == "путь (git не ответил)", walk["product_by"]
    assert walk["hits_all"] == 1 and walk["hits_tests"] == 1, walk
    assert walk["seen"] == 6, walk["seen"]      # see the explanation above about the two walks


def test_a_placeholder_added_to_the_product_does_move_the_number(tree):
    """🔴 A CONTROL AGAINST TAUTOLOGY: a product file DOES MOVE THE NUMBER.

    Without this half, the pin would be satisfied by a walk that sees nothing.
    """
    before = CS.oss_boundary_walk()
    _write(tree / "docs" / "SECOND.md", ADMIN_LINE)
    after = CS.oss_boundary_walk()
    assert after["hits_all"] == before["hits_all"] + 1, (before, after)
    assert "docs/SECOND.md" in after["files_all"]

    _write(tree / "kir" / "tests" / "test_second.py", 'GUID = "%s"\n' % HEX)
    third = CS.oss_boundary_walk()
    assert third["hits_tests"] == before["hits_tests"] + 1, (before, third)


def test_a_copy_of_the_tree_in_scratch_does_not_move_the_number(tree):
    """One more copy in `.work/` — the number did not budge."""
    before = CS.oss_boundary_walk()
    _write(tree / ".work" / "second-copy" / "docs" / "LAW.md", ADMIN_LINE)
    _write(tree / ".work" / "second-copy" / "kir" / "tests" / "t.py",
           'GUID = "%s"\n' % HEX)
    after = CS.oss_boundary_walk()
    assert (after["hits_all"], after["hits_tests"], after["seen"]) == (
        before["hits_all"], before["hits_tests"], before["seen"]), (before, after)


def test_an_environment_is_recognised_by_its_marker_not_by_its_name(tree):
    """`venv` was caught by name, `venv-clean` slipped past. Now the marker is caught."""
    before = CS.oss_boundary_walk()
    other = tree / "tools-env"
    _write(other / "pyvenv.cfg", "home = /usr\n")
    _write(other / "lib" / "site-packages" / "y.py", 'BAD = "%s"\n' % HEX)
    after = CS.oss_boundary_walk()
    assert (after["hits_all"], after["hits_tests"], after["seen"]) == (
        before["hits_all"], before["hits_tests"], before["seen"]), (before, after)


def test_the_real_tree_reports_both_sides_and_says_how_it_divided():
    """On the REAL tree (read-only): both sides are printed separately."""
    walk = CS.oss_boundary_walk()
    assert walk["product_by"].startswith("git"), walk["product_by"]
    assert walk["seen"] > CS._OSS_WALK_FLOOR, walk["seen"]
    for key in ("seen_scratch", "scratch_all", "scratch_tests", "scratch_files"):
        assert key in walk, key
    rows = "\n".join(CS._oss_boundary())
    assert "СКРЭТЧЕ" in rows and "НЕтестовом" in rows
