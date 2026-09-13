"""Every file of the package must be READABLE BY THE SERVICE, not only by its author.

🔴 PAID FOR BY LIVE PROD ON 02.09.2026, while the owner was working in KIR
mode. The install is editable: the files of this tree ARE the service's
files, and the service runs under a DIFFERENT user (`kukai`) than the one
making the edits (`claude`).

Nine `.py` files, created on 31.08 under a strict umask, sat in mode
`-rw-------` next to neighbors at `-rw-rw-r--`. The live refusal:

    PermissionError: [Errno 13] Permission denied:
        '/opt/kir/kir/clash/spatial_index.py'
    kir.clash_bundle -> clash_judgement -> clash.detect -> clash.spatial_index
    75 hits over 41 seconds

🔴 WHY NOBODY SAW THIS, AND THIS IS THE MAIN POINT. What surfaced was ONE
line, `hosted index build failed`, at DEBUG level, while the service runs
with `--log-level info`, so the refusal was never printed at all. And the
previous process, started on 28.08, already held the module in memory —
it never re-read it. **THE DEFECT WAS WAITING FOR THE FIRST RESTART** and
surfaced exactly on it.

Hence the shape of the guard: what is asked is a PROPERTY ("can a
STRANGER read this"), not the shape of the first case (a file name, a
directory, a date). A new file under the same umask will go red here,
rather than at the owner's, on a real document.

FAIL CONTROL was run by hand when this was set up: `chmod 0600` on one
package file -> EXACTLY ONE red, naming that file; `chmod 0664` -> green.
"""
from __future__ import annotations

import pathlib
import unittest

ПАКЕТ = pathlib.Path(__file__).resolve().parent.parent


class ФайлыПакетаЧитаемыСлужбой(unittest.TestCase):

    def test_каждый_py_читается_посторонним(self) -> None:
        закрытые = sorted(
            p for p in ПАКЕТ.rglob("*.py")
            if not (p.stat().st_mode & 0o004))
        self.assertEqual(
            [], [str(p.relative_to(ПАКЕТ)) for p in закрытые],
            "эти файлы служба (иной пользователь) прочитать НЕ МОЖЕТ; "
            "установка редактируемая, значит это отказ В ПРОДЕ, а не гигиена")

    def test_знаменатель_не_пуст(self) -> None:
        """Otherwise green would mean "no files were found", not "all are readable"."""
        self.assertGreater(len(list(ПАКЕТ.rglob("*.py"))), 200)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
