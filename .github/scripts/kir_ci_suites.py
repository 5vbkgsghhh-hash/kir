"""Partition pytest's collected KIR suite, without replacing it with a smoke gate."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
LANES = ("compiler-0", "compiler-1", "compiler-2", "compiler-3",
         "decompile", "product", "materialize")


def lane_for(relative_path: str) -> str:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "kir":
        raise ValueError(f"collected test is outside the KIR suite: {relative_path}")
    name = path.as_posix()
    if name == "kir/decompile/tests/test_materialize.py":
        return "materialize"
    if name.startswith("kir/tests/"):
        shard = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big") % 4
        return f"compiler-{shard}"
    if name.startswith("kir/decompile/"):
        return "decompile"
    return "product"


def paths_for_lane(lane: str, root: Path = ROOT) -> tuple[Path, ...]:
    """Choose test modules before pytest imports any other lane.

    Deselecting after collection is too late for module-level effects.  In the
    complete tree, collection of another lane can add ``kir/`` to ``sys.path``;
    the product lane then resolves the external ``mcp`` SDK as our own
    ``kir/mcp`` package.  A lane owns whole files, so selecting those files up
    front preserves the same partition without importing its neighbours.
    """
    if lane not in LANES:
        raise ValueError(f"unknown CI lane: {lane}")
    root = root.resolve()
    return tuple(
        path for path in sorted((root / "kir").rglob("test_*.py"))
        if lane_for(path.resolve().relative_to(root).as_posix()) == lane
    )


class LaneSelection:
    def __init__(self, lane: str, root: Path = ROOT):
        if lane not in LANES:
            raise ValueError(f"unknown CI lane: {lane}")
        self.lane = lane
        self.root = root.resolve()
        self.selected = 0

    def pytest_collection_modifyitems(self, config, items):
        kept, removed = [], []
        for item in items:
            relative = item.path.resolve().relative_to(self.root).as_posix()
            (kept if lane_for(relative) == self.lane else removed).append(item)
        self.selected = len(kept)
        print(f"KIR CI {self.lane}: {self.selected} of {len(items)} collected tests")
        config.hook.pytest_deselected(items=removed)
        items[:] = kept

    def pytest_sessionfinish(self, session, exitstatus):
        # A successful empty lane would certify that no obligation ran.
        if self.selected == 0 and exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.NO_TESTS_COLLECTED


def main(argv=None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=LANES)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--junitxml")
    args = parser.parse_args(argv)
    targets = paths_for_lane(args.lane, root)
    options = ["-q", "-p", "no:cacheprovider", "-p", "no:randomly",
               *[str(path) for path in targets]]
    if args.collect_only:
        options.append("--collect-only")
    if args.junitxml:
        options.append("--junitxml=" + args.junitxml)
    return int(pytest.main(options, plugins=[LaneSelection(args.lane, root)]))


if __name__ == "__main__":
    raise SystemExit(main())
