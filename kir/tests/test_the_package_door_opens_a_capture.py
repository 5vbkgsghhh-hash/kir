# -*- coding: utf-8 -*-
"""THE PACKAGE'S DOOR OPENS CAPTURE, AND OPENS IT WITH THE SAME LOCK.

🔴 WHAT EXACTLY IS GUARDED. On 07.09.2026 `kir/__main__.py` gained a
subcommand `capture` that FORWARDS the argv tail into the existing parser
`kir.decompile.capture_api`. The entire value of such wiring lies in the
word "the same": a second parser for the same flags would diverge from the
first SILENTLY — on a new flag, on a `choices` change, on `required` — and
a person whom the instructions promised "the exact same thing" would get a
refusal from one door that the other does not give.

So the question here is not "does `kir capture` work". The question is the
EQUALITY of two doors, and it is asked with real processes: in this
process half the package is already imported by the suite, and "the door
opened" is indistinguishable from "the module was already loaded".

  1. `demo` — the building is written, and the command ITSELF NAMES the
     element addresses. Not a single id here is typed by hand: a
     hardcoded `1002` in the test text would stay silent about a change to
     the demo, while one taken from its own output goes red.
  2. `read` — the answer from both doors is compared BYTE FOR BYTE. Not
     "both are valid", not "both are about the door": byte for byte. A
     mismatch in one key is already two carriers.
  3. `propose` — a permitted edit WRITES NOTHING. The guard is the sha256
     of EVERY file in the directory, before and after, not the
     directory's size and not mtime: a write of the same length would
     slip past both.
  4. THE REFUSAL STAYS A REFUSAL, AND ITS NUMBER IS 2. A stale `before`
     gives `EXIT_REFUSED` at `capture_api`, and the package's door must
     return THE SAME NUMBER, not its own ANSWERED/REFUSED: to report a
     different number for the same seam's refusal than the seam itself
     reports would mean setting up a second outcome dictionary. Along
     with the number, the CONSEQUENCE is also checked: the target
     directory is not created — a refusal leaves no half-finished work.

WHAT THIS FILE DOES NOT CLAIM: nothing about the correctness of
`capture_api` itself — its subject is guarded by the tests in
`kir/decompile/tests/`. Here there is one subject: TWO ROADS TO ONE DOOR
GIVE THE SAME THING.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TREE = Path(__file__).resolve().parents[2]

#: Refusal of `capture_api` (`EXIT_REFUSED`). It is ASKED FROM THE MODULE,
#: not written as a number: a literal `2` here would survive a change of
#: outcome and stay silent about it.
from kir.decompile.capture_api import EXIT_OK, EXIT_REFUSED  # noqa: E402

#: Two roads to one door. The first is a direct call to the module, the
#: second is the package's door; everything below runs against both and
#: cross-checks.
ЧЕРЕЗ_МОДУЛЬ = ["-m", "kir.decompile.capture_api"]
ЧЕРЕЗ_ПАКЕТ = ["-m", "kir", "capture"]


def _run(дорога: list[str], *argv: str) -> subprocess.CompletedProcess:
    """A real process. The environment is set explicitly, inheritance is not measured."""
    env = dict(os.environ)
    env.update(PYTHONPATH=str(TREE), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, *дорога, *argv], cwd=str(TREE),
                          capture_output=True, env=env, timeout=300)


def _слепок(каталог: Path) -> dict[str, str]:
    """sha256 of EVERY file under the directory — a byte-for-byte write guard.

    The directory's size and mtime would let through an edit of the same
    length; a per-name list of hashes lets through neither that, nor a new
    file, nor a vanished one.
    """
    return {str(путь.relative_to(каталог)):
            hashlib.sha256(путь.read_bytes()).hexdigest()
            for путь in sorted(каталог.rglob("*")) if путь.is_file()}


class ThePackageDoorOpensACapture(unittest.TestCase):

    def setUp(self) -> None:
        каталог = tempfile.TemporaryDirectory()
        self.addCleanup(каталог.cleanup)
        self.работа = Path(каталог.name)

    # ── 1. the building, and addresses from its own output ────────────────
    def _демо(self, дорога: list[str], имя: str) -> tuple[Path, dict]:
        цель = self.работа / имя
        proc = _run(дорога, "demo", "--out", str(цель))
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr[-2000:].decode("utf-8", "replace"))
        ответ = json.loads(proc.stdout)
        self.assertTrue(цель.is_dir(), "demo не написала каталог здания")
        # The addresses are printed by the COMMAND ITSELF — here they are only read.
        for ключ in ("door", "second_door", "floor", "wall"):
            self.assertIn(ключ, ответ, "demo не назвала адрес элемента")
        return цель, ответ

    def test_the_door_writes_a_building_and_names_its_elements(self) -> None:
        цель, ответ = self._демо(ЧЕРЕЗ_ПАКЕТ, "здание")
        self.assertEqual(ответ["capture"], str(цель))
        self.assertTrue(_слепок(цель), "каталог здания пуст")

    def test_both_roads_write_the_same_building(self) -> None:
        """One demo, not two: the snapshots of both directories match."""
        через_пакет, _ = self._демо(ЧЕРЕЗ_ПАКЕТ, "п")
        через_модуль, _ = self._демо(ЧЕРЕЗ_МОДУЛЬ, "м")
        self.assertEqual(_слепок(через_пакет), _слепок(через_модуль))

    # ── 2. read: BYTE-FOR-BYTE equality ─────────────────────────────────────
    def test_read_is_byte_for_byte_the_same_through_both_roads(self) -> None:
        цель, ответ = self._демо(ЧЕРЕЗ_ПАКЕТ, "здание")
        дверь = ответ["door"]
        пакетом = _run(ЧЕРЕЗ_ПАКЕТ, "read", "--capture", str(цель),
                       "--element", дверь)
        модулем = _run(ЧЕРЕЗ_МОДУЛЬ, "read", "--capture", str(цель),
                       "--element", дверь)
        self.assertEqual(пакетом.returncode, EXIT_OK, пакетом.stderr[-2000:].decode("utf-8", "replace"))
        self.assertEqual(модулем.returncode, EXIT_OK, модулем.stderr[-2000:].decode("utf-8", "replace"))
        # BYTE FOR BYTE, not "both are about the door": a mismatch in a key — already two carriers.
        self.assertEqual(пакетом.stdout, модулем.stdout)
        разбор = json.loads(пакетом.stdout)
        self.assertEqual(разбор["element_id"], дверь)
        self.assertEqual(разбор["category"], "OST_Doors")

    # ── 3. the preview WRITES NOTHING ────────────────────────────────────
    def test_propose_through_the_package_door_writes_nothing(self) -> None:
        цель, ответ = self._демо(ЧЕРЕЗ_ПАКЕТ, "здание")
        # 🔴 REVERSED 07.09.2026, AND THE OLD TEXT IS KEPT AS THE REASON, NOT
        # ERASED. WHAT USED TO HAPPEN: opening a snapshot placed an empty
        # marker `.last_access` (`kir.model.snapshot_io.LAST_ACCESS_MARKER`)
        # RIGHT INTO THE DIRECTORY ITSELF, which the snapshot janitor reads
        # as "this is still being visited". The OPEN ITSELF wrote it, and
        # `read` wrote it in exactly the same way as `propose`. That is why
        # this used to have "GROUND": one read BEFORE the measurement, so
        # the marker had time to appear, and the assertion
        # `assertIn(".last_access", before)`, so its absence would read as
        # "the snapshot is checking the wrong directory".
        #
        # WHY IT WAS REMOVED: by the owner's decision the access marker
        # moved to an EXTERNAL journal — `KIR_CACHE_HOME` /
        # `XDG_CACHE_HOME` / `~/.cache`, then
        # `kir/lift/<sha256 of the directory's realpath>`; see
        # `kir.model.snapshot_io.access_journal_dir` and the pins in
        # `kir/decompile/tests/test_snapshot_io.py`. REASON: reading has no
        # right to change what is being read — the capture directory is
        # declared "READ ONLY", and this one marker alone made the
        # `open_capture` docstring untrue.
        #
        # So the warm-up was not silently dropped, it BECAME UNNECESSARY:
        # there is nothing left to add inside the directory, and `before`
        # is taken right after `demo`. The change is the exact reverse of
        # the previous one, not a removal of the assertion: there must be
        # NO marker inside capture, neither before the preview nor after.
        до = _слепок(цель)
        self.assertNotIn(".last_access", до,
                         "метка доступа снова пишется ВНУТРЬ capture — "
                         "07.09.2026 она переехала во внешний журнал "
                         "(kir.model.snapshot_io.access_journal_dir)")
        proc = _run(ЧЕРЕЗ_ПАКЕТ, "propose", "--capture", str(цель),
                    "--element", ответ["door"],
                    "--patch", json.dumps({"offset_mm": 4000.0}))
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr[-2000:].decode("utf-8", "replace"))
        разбор = json.loads(proc.stdout)
        self.assertTrue(разбор["wrote_nothing"])
        self.assertTrue(разбор["proposals"][0]["admissible"],
                        "правка, объявленная допустимой, отвергнута")
        self.assertEqual(_слепок(цель), до, "предпросмотр тронул каталог")
        self.assertNotIn(".last_access", _слепок(цель),
                         "предпросмотр положил метку доступа внутрь capture")

    def test_propose_answers_identically_through_both_roads(self) -> None:
        цель, ответ = self._демо(ЧЕРЕЗ_ПАКЕТ, "здание")
        доводы = ("propose", "--capture", str(цель), "--element", ответ["door"],
                  "--patch", json.dumps({"offset_mm": 4000.0}))
        пакетом, модулем = _run(ЧЕРЕЗ_ПАКЕТ, *доводы), _run(ЧЕРЕЗ_МОДУЛЬ, *доводы)
        self.assertEqual(пакетом.returncode, модулем.returncode)
        self.assertEqual(пакетом.stdout, модулем.stdout)

    # ── 4. the refusal carries SOMEONE ELSE'S number, and leaves no half-finished work ──
    def _устаревший_before(self, дорога: list[str], имя: str,
                           здание: tuple[Path, dict] | None = None):
        цель, ответ = здание if здание is not None else self._демо(дорога, имя)
        новый = self.работа / (имя + "-out")
        правка = {"element_id": ответ["door"],
                  "change": {"offset_mm": 4000.0},
                  # A value that does not exist under the edit: the binding
                  # must notice that it moved away, and not land by address
                  # coincidence.
                  "before": {"offset_mm": 9999.0}}
        proc = _run(дорога, "apply", "--capture", str(цель),
                    "--edit", json.dumps(правка), "--out", str(новый))
        return proc, новый, цель

    def test_a_stale_before_refuses_with_code_two_and_writes_no_target(self):
        proc, новый, цель = self._устаревший_before(ЧЕРЕЗ_ПАКЕТ, "здание")
        self.assertEqual(proc.returncode, EXIT_REFUSED, proc.stderr[-2000:].decode("utf-8", "replace"))
        self.assertEqual(proc.returncode, 2, "число отказа сместилось")
        разбор = json.loads(proc.stdout)
        self.assertIsNone(разбор["saved"])
        self.assertEqual(разбор["applied"][0]["refusal"]["code"],
                         "edit_before_value_mismatch")
        # CONSEQUENCE of the refusal: no half-finished work remains, neither in the target nor in the source.
        self.assertFalse(новый.exists(), "отказ создал каталог цели")

    def test_the_refusal_is_identical_through_both_roads(self) -> None:
        """ONE building for both roads: two different captures would have
        given a different `lineage`, and a mismatch in the reports would
        have read as a mismatch between the doors."""
        здание = self._демо(ЧЕРЕЗ_ПАКЕТ, "здание")
        пакетом, _, _ = self._устаревший_before(ЧЕРЕЗ_ПАКЕТ, "п", здание)
        модулем, _, _ = self._устаревший_before(ЧЕРЕЗ_МОДУЛЬ, "м", здание)
        self.assertEqual(пакетом.returncode, модулем.returncode)
        self.assertEqual(пакетом.stdout, модулем.stdout)


if __name__ == "__main__":
    unittest.main()
