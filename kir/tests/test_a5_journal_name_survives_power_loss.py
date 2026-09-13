"""THE JOURNAL'S NAME MUST SURVIVE A POWER LOSS, NOT JUST ITS CONTENT.

🔴 WHAT IS PINNED HERE AND WHY IT WAS NOT ENOUGH (F-153, 2026-09-03).

`A5Journal.create` used to fsync the journal file and the `a5_runs`
directory — and stopped there. But on POSIX **a directory's name entry
lives in its PARENT**: for the name `a5_runs` to survive a power loss,
`out_dir` must be fsynced, and for the name of `out_dir` itself to survive,
its parent must be too.

When `out_dir` already existed, there is no hole: whoever created it
fsynced its name. The hole is exactly where `mkdir(parents=True)` created
the chain ITSELF, and that is the ordinary case of A5's first run in a
fresh output directory. Then after a crash the idempotence journal
disappears ENTIRELY — along with any trace that the turn ever happened —
and the retry builds a second time what was already built.

WHY THE TEST LOOKS AT `fsync` AND NOT AT THE FILE SYSTEM. The real control
would be an actual power cut, and there is none here. So what is pinned is
the OBSERVABLE trace of intent: which directory descriptors reached
`os.fsync`. That is weaker than «survives», and is named as weaker: the
test proves that we ASK the kernel to fsync the right names, not that the
kernel fsynced them.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest import mock

from kir.a5_recovery import A5Journal

# 🔴 THE INPUT IS TAKEN FROM THE AUTHORITY, NOT REWRITTEN FROM SCRATCH.
# `prepared_proof` is not a dict eyeballed into shape: `RunId` requires 16
# hex digits, `document_fingerprint` must be an object, and this file's
# first two editions went red NOT FROM A DEFECT but from their own unfit
# input — red that is not about the subject pins nothing. A homegrown copy
# of the builder would become a second carrier obligated to stay in sync.
from kir.tests.test_a5_recovery import RUN_ID, _prepared


def _журнал_в_свежем_дереве(корень: pathlib.Path):
    """Create the journal the way the first run does: the chain does not exist yet.

    The input is built via the prod path (`A5Journal.create`), not a
    handwritten fixture: a handwritten input once REFUTED a defect that it
    was itself unable to reproduce.
    """
    out_dir = корень / "вывод" / "прогон-1"
    fsynced: list[str] = []
    настоящий_fsync = os.fsync
    настоящий_open = os.open

    открытые: dict[int, str] = {}

    def шпион_open(path, flags, *a, **kw):
        fd = настоящий_open(path, flags, *a, **kw)
        открытые[fd] = str(path)
        return fd

    def шпион_fsync(fd):
        if fd in открытые:
            fsynced.append(открытые[fd])
        return настоящий_fsync(fd)

    with mock.patch.object(os, "open", шпион_open), \
            mock.patch.object(os, "fsync", шпион_fsync):
        A5Journal.create(
            out_dir,
            run_id=RUN_ID,
            prepared_proof=_prepared(),
        )
    return out_dir, fsynced


class ИмяЖурналаЗакрепляется(unittest.TestCase):

    def test_каждый_созданный_нами_каталог_закреплён_у_своего_родителя(self):
        """The F-153 hole, verbatim: `a5_runs` is fsynced, but its PARENT is not."""
        with tempfile.TemporaryDirectory() as d:
            корень = pathlib.Path(d)
            out_dir, fsynced = _журнал_в_свежем_дереве(корень)

            # Directories created BY THIS CALL: each one's name entry lives
            # in its parent, so the parent must be fsynced.
            созданные = [out_dir / "a5_runs", out_dir, out_dir.parent]
            родители = {str(p.parent) for p in созданные}
            закреплены = set(fsynced)

            не_закреплены = sorted(родители - закреплены)
            self.assertEqual(
                не_закреплены, [],
                "имя каталога не переживёт сбой: его родитель не закреплён.\n"
                f"  закреплено: {sorted(закреплены)}\n"
                f"  требовалось: {sorted(родители)}")

    def test_знаменатель_не_пуст_иначе_зелёное_куплено_слепотой(self):
        """A control in the other direction: does the spy see anything at all?

        Zero intercepted `fsync` calls would make the test above green by
        construction — an empty set subtracts without a remainder. Zero here
        means «the instrument went blind», not «everything is fsynced».
        """
        with tempfile.TemporaryDirectory() as d:
            _, fsynced = _журнал_в_свежем_дереве(pathlib.Path(d))
            self.assertGreater(
                len(fsynced), 0,
                "шпион не перехватил НИ ОДНОГО fsync — знаменатель пуст, "
                "и зелёный соседнего теста ничего не значит")

    def test_существовавший_каталог_лишнего_закрепления_не_требует(self):
        """Boundary: where we did not create the chain, there is no hole and no work.

        Without this side, the fix would read as «always fsync the whole
        path», which is extra I/O on every turn — and the rule would become
        wider than the measured defect.
        """
        with tempfile.TemporaryDirectory() as d:
            корень = pathlib.Path(d)
            out_dir = корень / "уже-есть"
            out_dir.mkdir(parents=True)

            fsynced: list[str] = []
            настоящий_fsync, настоящий_open = os.fsync, os.open
            открытые: dict[int, str] = {}

            def шпион_open(path, flags, *a, **kw):
                fd = настоящий_open(path, flags, *a, **kw)
                открытые[fd] = str(path)
                return fd

            def шпион_fsync(fd):
                if fd in открытые:
                    fsynced.append(открытые[fd])
                return настоящий_fsync(fd)

            with mock.patch.object(os, "open", шпион_open), \
                    mock.patch.object(os, "fsync", шпион_fsync):
                A5Journal.create(
                    out_dir,
                    run_id=RUN_ID,
                    prepared_proof=_prepared(),
                )

            # We did not create `out_dir` — fsyncing its parent is not our job.
            self.assertNotIn(
                str(корень), fsynced,
                "закреплён родитель каталога, которого мы не создавали — "
                "правило шире измеренного дефекта")


if __name__ == "__main__":
    unittest.main()
