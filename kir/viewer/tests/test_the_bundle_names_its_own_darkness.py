"""THE NUMBER OF SKIPS IN THIS CATALOG — UNDER A RATCHET.

🔴 WHY A NUMBER, NOT A LIST OF NAMES. An instrument that can be gamed by
rewriting its FORM guards nothing: a list of names is gamed by renaming
the test. A number has nothing to game it with — it GROWS whenever an
instrument goes dark, regardless of what the darkened one was called.

🔴 WHY AT ALL. On 29.08.2026 the showroom suite reported `223 passed, 22
skipped`, and the twenty-two skips read as noise. Nineteen of them had
ONE cause: the instrument was looking for its subject at an address
that, after the KIR/KUKAI split, no longer exists (`parents[4]` was
computed for the `backend/kukai/ir/viewer/tests` layout). The miss was
GREEN — it was expressed as `skipTest`, not a failure, and a "green
suite" hid it. An instrument that only counts GREEN cannot catch this
by construction: fifteen darkened cache checks DO NOT CHANGE the count
of greens.

THE CEILING IS LIFTED BY A MEASUREMENT, NOT BY A WISH. Measured
29.08.2026 on `65182ad`:

    BEFORE the class-P5-B fixes    223 passed, 22 skipped
    AFTER                          232 passed, 13 skipped

Nine checks came out of the dark: two splices in `test_delta` (address)
and seven in `test_cache` (a tie to the corpus these classes don't
need). The remaining thirteen are LEGITIMATE and are named individually
in `ПОЧЕМУ_ТРИНАДЦАТЬ`.

🔴 THE CEILING GOES DOWN WITH A FIX AND DOES NOT GO UP WITHOUT A RECORD
HERE. Raising it just to "make it green" is exactly the trick this file
is written against.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import unittest

#: Measured 29.08.2026 on `65182ad`, taken from a run. See `ПОЧЕМУ_ТРИНАДЦАТЬ`.
ПОТОЛОК_ПРОПУСКОВ = 13

#: What the ceiling is made of. Not for arithmetic — for the reader who
#: sees red and needs to know what here is legitimate and what is debt.
ПОЧЕМУ_ТРИНАДЦАТЬ = """
  8  test_cache.py    два класса строят ключ ПО КАТАЛОГУ РАЗБОРА, третий берёт
                      сцену через `scene_from_decompile` — всем троим нужен
                      настоящий корпус, а он машинно-локален
  4  test_advice.py   та же причина: `scene.corpus_unreachable_reason()`
  1  test_push.py     порт «api.viewer» не поставлен этой средой — у хоста
"""

#: The catalog is treated as an EXPLICIT list: `build/lib/**` is a
#: second copy of the suite, and a directory walk would count it too.
ФАЙЛЫ = (
    "test_advice.py", "test_cache.py", "test_codec.py", "test_codec_mesh.py",
    "test_compilability.py", "test_delta.py", "test_graph.py",
    "test_history.py", "test_honesty.py", "test_live_scene.py",
    "test_live_scene_mesh.py", "test_mesh_client_parity.py", "test_push.py",
    "test_reconcile.py", "test_scene.py", "test_shown_transfer.py",
    "test_a_tail_is_signed_as_the_glued_scene.py",
    "test_the_signature_uses_the_published_string.py",
    # The ledger catches up with its own entries, 30.08.2026. Four shift
    # guards were not entered here by their own commits, and their
    # skips were INVISIBLE to the ratchet.
    "test_a_cache_entry_is_verified_not_measured.py",
    "test_a_frame_keeps_what_it_already_knew.py",
    "test_a_green_verdict_survives_every_named_check.py",
    "test_a_conditional_claim_is_not_a_certain_one.py",
    # The ledger catches up with its own entries, 06.09.2026. Nine files
    # sat in the catalog without being named, and their skips were
    # INVISIBLE to the ratchet. NINE were brought in by the Codex wave
    # (standalone display, reference surfaces, mesh-addition atomicity);
    # the tenth is mine, stage D (display of analysis findings). The
    # number "nine" is measured by sets, not copied from someone else's
    # note: `test_standalone_export.py` was not named in it, and adding
    # only eight would have left the ratchet red. The list is amended
    # DELIBERATELY and in one move, not one at a time: a partial
    # addition would leave the ratchet blind and look like a fix.
    "test_blend_preview.py",
    "test_standalone_export.py",
    "test_standalone_input.py",
    "test_standalone_project_status.py",
    "test_reference_surfaces.py",
    "test_reference_surface_export.py",
    "test_reference_surface_artifacts_adversarial.py",
    "test_mesh_visibility_independent_of_clash.py",
    "test_mesh_addition_is_atomic.py",
    "test_clash_findings_are_shown_with_their_limits.py",
    # The end-to-end analysis -> display pass, introduced 06.09.2026
    # together with address translation (acceptance, entry 6). My file.
    "test_the_analysis_reaches_the_display.py",
    # Display of the untranslated remainder and of decisions, introduced
    # 07.09.2026 (stage D2). My file; entered by its OWN commit, not by
    # a "catching-up" ledger entry — precisely so that 30.08 and 06.09
    # do not repeat a third time.
    "test_the_untranslated_remainder_reaches_the_screen.py",
    # 🔴 A FOURTH TIME, AND IT WAS CAUGHT NOT BY EYE. One revision
    # snapshot for reading, analysis, and the scene — the file arrived
    # in commit `84a0470` (wave 8, 08.09.2026) and was NOT entered here
    # by its own commit: the sets diverged by exactly this file, and
    # `test_список_накрывает_каталог` had been red since that hour. The
    # file brings no skips (`importorskip("OCP")` passes on this tree —
    # OCP is installed), so the ceiling of 13 stays the same number
    # rather than being raised "to match the fact".
    "test_a_scene_and_its_analysis_take_one_snapshot.py",
    # 🔴 REMOVED 13.09.2026 WITH THE BROWSER WINDOW, AND DELIBERATELY.
    # `test_inspector_uses_packaged_assets_by_default.py` measured where the
    # inspector found its asset bundle; the owner's word removed the window,
    # `kir/app/**`, `frontend/standalone/**` and `kir/viewer/assets.py`, so the
    # subject of those six checks no longer exists. They brought NO skips, so
    # the ceiling of 13 stays the same number: this edit removes a name, not a
    # darkness. The catalogue and the ceiling are edited in one move, as this
    # file demands, and the reason is written here rather than in a commit.
)


class НаборНазываетСвоюТемноту(unittest.TestCase):

    def test_пропусков_не_больше_потолка(self):
        """🔴 THE MEASUREMENT MUST ACTUALLY HAPPEN: the summary EXISTS
        and the return code is taken WITHOUT A PIPE.

        An empty output looks like zero skips — that is, like success.
        Therefore the absence of a summary here is a REFUSAL, not a
        zero.
        """
        свой = pathlib.Path(__file__).resolve()
        каталог = свой.parent
        отсутствуют = [f for f in ФАЙЛЫ if not (каталог / f).is_file()]
        self.assertFalse(отсутствуют,
                         f"файлы набора исчезли: {отсутствуют} — список правится "
                         f"ОСОЗНАННО, вместе с потолком")
        self.assertNotIn(свой.name, ФАЙЛЫ, "храповик не считает сам себя")

        корень = свой.parents[3]
        среда = dict(os.environ, PYTHONPATH=str(корень))
        итог = subprocess.run(
            [sys.executable, "-m", "pytest",
             *[str(каталог / f) for f in ФАЙЛЫ],
             "-q", "-p", "no:cacheprovider", "-p", "no:randomly",
             "--tb=no", "-rs"],
            cwd=str(корень), env=среда, capture_output=True, text=True,
            timeout=900)

        сводка = re.search(r"(\d+) passed(?:, (\d+) skipped)?", итог.stdout)
        self.assertIsNotNone(
            сводка, "СВОДКИ НЕТ — замер не состоялся, и это отказ, а не ноль.\n"
                    f"код возврата {итог.returncode}\n"
                    f"хвост: {итог.stdout[-800:]}\n{итог.stderr[-400:]}")
        зелёных = int(сводка.group(1))
        пропущено = int(сводка.group(2) or 0)

        self.assertGreater(зелёных, 0, "ноль зелёных — набор не исполнялся")
        self.assertLessEqual(
            пропущено, ПОТОЛОК_ПРОПУСКОВ,
            f"пропусков {пропущено} при потолке {ПОТОЛОК_ПРОПУСКОВ}: прибор "
            f"погас, и «зелёный набор» это прячет. Поднимать потолок ради "
            f"зелени ЗАПРЕЩЕНО — сперва разобрать, что именно погасло.\n"
            f"из чего сложился потолок:{ПОЧЕМУ_ТРИНАДЦАТЬ}")

    def test_список_накрывает_каталог(self):
        """🔴 A HOLE THAT I MYSELF PUNCHED BY ADDING A FILE (29.08.2026).

        The previous edition checked only one side: "the named file
        exists". The reverse side — "the existing file IS NAMED" — was
        not checked, and the ratchet would not have seen a new dark
        file in the catalog: its skips would not have made it into the
        count. What is checked are SETS, by name, not by a sum.
        """
        каталог = pathlib.Path(__file__).resolve().parent
        на_диске = {p.name for p in каталог.glob("test_*.py")}
        назван = set(ФАЙЛЫ) | {pathlib.Path(__file__).name}
        self.assertEqual(
            на_диске, назван,
            "список набора разошёлся с каталогом: файл, которого нет в "
            "`ФАЙЛЫ`, не считается — его пропуски невидимы храповику")

    def test_потолок_не_бессмысленно_высок(self):
        """THE SECOND HALF (rule 2): a ratchet with an "as many as you
        like" ceiling is always green and guards nothing. The ceiling
        must be smaller than the number of files in the suite —
        otherwise it constrains nothing."""
        self.assertLess(ПОТОЛОК_ПРОПУСКОВ, len(ФАЙЛЫ) * 3,
                        "потолок перестал что-либо ограничивать")
        self.assertTrue(ПОЧЕМУ_ТРИНАДЦАТЬ.strip(),
                        "потолок без разбора — число без причины")


if __name__ == "__main__":
    unittest.main()
