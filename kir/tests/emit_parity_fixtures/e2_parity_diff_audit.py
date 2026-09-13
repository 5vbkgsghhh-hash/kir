"""Line-by-line audit of the E-2 delta: EVERY discrepancy must be a shift of a
NUMBER by exactly delta_mm of the same program, and nothing else.

The practice is link E-1's (`.work/marathon-fable-20260907/writers/parity_diff_audit.py`),
but the predicate is DIFFERENT and this is named: E-1 moved LINES between
stages and required «numbers moved 0»; E-2 does not move a single line and
moves EXACTLY the endpoint-expectation numbers. Taking E-1's predicate here
would check the wrong subject.

The trap E-1 caught itself on (a naive digit count mistook `ME1` for a
number) is closed here by construction: the numbers are taken not from names
but from the position `MM(__eN.AXIS) - <NUMBER>` — that is a comparison
LITERAL, not a digit in a name.

🔴 LIVES IN THE TREE, NOT IN `.work/` — AND THIS WAS CAUGHT BY THE 2026-09-07
MEASUREMENT.
The first edition lived in `.work/marathon-fable-20260907/left/`, and the
record `e2_migration_2026_09_07.json` pinned its sha256 as the review
source. `.work/` DOES NOT GO INTO the commit: on a frozen copy of the tree
(`git archive HEAD` + the wave's files) `E2MigrationContract::test_record_pins_current_review_sources...`
failed with `FileNotFoundError`, meaning the pin was red on the owner's
clean clone. An instrument whose verdict a record pins must travel together
with it — otherwise the provenance points to something the reader does not
have. Our named form: «a shared file outside git is not a record».

    python3 -m kir.tests.emit_parity_fixtures.e2_parity_diff_audit \
        --old DIR --new DIR --keys keys.txt --delta 1000 0 500
"""
from __future__ import annotations

import argparse
import difflib
import pathlib
import re
import sys

# 🔴 THE INSTRUMENT CAUGHT ITSELF, AND THIS IS RECORDED, NOT PAPERED OVER.
# The first edition only knew the VERDICT lines (`MM(__e0.X) - <number>`) and
# gave 24 false «UNEXPLAINED» out of 24: the endpoint witness also checks
# ORIENTATION — which of the two ends counts as first — via the lines
# `MM(__a.X) - <number>` / `MM(__b.X) - ...`, and they carry the SAME
# authored p0, so they travel with the same shift. Skipping them would have
# declared a genuine patch unexplained. The exact same kind of miss as E-1's,
# where a naive digit count mistook `ME1` for a number.
EXPECT = re.compile(r"MM\(__(e0|e1|a|b)\.([XYZ])\)\s*-\s*(-?\d+(?:\.\d+)?)")


def _file(root: pathlib.Path, key: str) -> pathlib.Path:
    return root / (key.replace("|", "__").replace(":", "_").replace("/", "_") + ".cs")


def _block_of(cs: str, index: int) -> str:
    """The stage header under which line `index` lies."""
    head = None
    for i, line in enumerate(cs.splitlines()):
        m = re.match(r"^\s*//\s+(post|operation)\s+(\S+)\s*$", line)
        if m:
            head = f"{m.group(1)} {m.group(2)}"
        if i == index:
            return head or "(вне блока)"
    return "(вне блока)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", type=pathlib.Path, required=True)
    ap.add_argument("--new", type=pathlib.Path, required=True)
    ap.add_argument("--keys", type=pathlib.Path, required=True)
    ap.add_argument("--delta", type=float, nargs=3, required=True,
                    help="delta_mm программы: dx dy dz")
    args = ap.parse_args()
    delta = {"X": args.delta[0], "Y": args.delta[1], "Z": args.delta[2]}

    keys = [k.strip() for k in args.keys.read_text().splitlines() if k.strip()]
    ok = bad = 0
    unexplained: list[str] = []
    for key in keys:
        old = _file(args.old, key).read_text(encoding="utf-8").splitlines()
        new = _file(args.new, key).read_text(encoding="utf-8").splitlines()
        blocks = set()
        moved_numbers = 0
        trouble = []
        sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            if tag != "replace" or (i2 - i1) != (j2 - j1):
                trouble.append(f"{tag}: строк {i2-i1}->{j2-j1} (не замена)")
                continue
            for oi, nj in zip(range(i1, i2), range(j1, j2)):
                o, n = old[oi], new[nj]
                blocks.add(_block_of("\n".join(new), nj))
                # strip the expectation numbers and check each one
                po, pn = EXPECT.findall(o), EXPECT.findall(n)
                if not po or len(po) != len(pn):
                    trouble.append(f"строка без ожидания концов: {o.strip()[:70]!r}")
                    continue
                skeleton_o = EXPECT.sub("MM(__\\1.\\2) - ?", o)
                skeleton_n = EXPECT.sub("MM(__\\1.\\2) - ?", n)
                if skeleton_o != skeleton_n:
                    trouble.append("изменилось НЕ ТОЛЬКО число: "
                                   f"{skeleton_o.strip()[:60]!r}")
                    continue
                for (i_o, ax_o, v_o), (i_n, ax_n, v_n) in zip(po, pn):
                    if (i_o, ax_o) != (i_n, ax_n):
                        trouble.append("переставлены концы/оси")
                        continue
                    want = float(v_o) + delta[ax_o]
                    if abs(float(v_n) - want) > 1e-9:
                        trouble.append(
                            f"{i_o}.{ax_o}: {v_o} -> {v_n}, а сдвиг обещал {want}")
                        continue
                    moved_numbers += 1
        if trouble:
            bad += 1
            unexplained.append(f"{key}: " + "; ".join(trouble[:3]))
        else:
            ok += 1
        print(f"{'OK ' if not trouble else 'BAD'} {key}: чисел сдвинуто "
              f"{moved_numbers}, блоки {sorted(blocks)}")
    print(f"\nВЕРДИКТ: {ok}/{ok+bad} расхождений объяснены сдвигом delta_mm")
    for line in unexplained:
        print("  НЕ РАЗОБРАН:", line)
    print(f"НЕ РАЗОБРАН: {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
