"""THE PLAN AND THE VERDICT — IN THE MODEL'S LANGUAGE, WITH NO HOLE TO THE
OUTSIDE.

Measured 03.08, a live loop over nine rounds. A model writing a script in the
sandbox got, from `preview()` and `design_check()`, a bare

    KIR-B006: NameError: name 'preview' is not defined

— and the WHOLE assembled program was discarded in the process: a sandbox
refusal returns zero operations, meaning the entire turn was lost. Vision had
been built (`preview.py` — 109 KB, `design_check.py` — 112 KB), but there was
no door from it into the model's language: the plan went out over the
websocket to the HUMAN's panel, and the verdict had no importer anywhere in
the whole tree except its own test.

WHAT IS HELD HERE, besides the seam itself:

1. THE SANDBOX BOUNDARY DID NOT MOVE. The two names are introduced by NARROW
   FUNCTIONS, not modules, and the heavy modules they call sit in the
   child's `sys.modules` — i.e. exactly where escaped code could reach them
   from. This is checked BY MEASUREMENT: the script still cannot import
   them, cannot open a file, cannot reach the network, and the root is still
   empty.
2. THE COST IS PAID ONLY BY WHOEVER CALLS. The verdict module costs +536 ms
   and +43 MB per run, and the script is executed TWICE (`replay_check`).
   Warmup decides BY SOURCE (`course.language.warm_for_source`), and a turn
   that never writes these names must stay the same price as before.
3. THE CALL DOES NOT TAKE THE PROGRAM AWAY. `take_ops()` is the sandbox's
   door; calling it from `preview()` would mean printing the plan and
   leaving the turn without a program, and silently at that: both the plan
   and the verdict would still print correctly.

Run: KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kir/tests/test_plan_and_verdict_in_the_sandbox.py -q
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir import sandbox  # noqa: E402

#: EXACTLY prod: `serving._sandbox_policy()` builds
#: `SandboxPolicy(replay_check=True)` and touches nothing else. The language
#: module is the policy's default.
POLICY = sandbox.SandboxPolicy(replay_check=True)


def setUpModule() -> None:
    """AN UNFIT ENVIRONMENT MUST SAY SO ABOUT ITSELF, NOT TURN RED WITH
    SOMEONE ELSE'S BLAME.

    🔴 OPENED 01.09.2026, AND THE COST IS NAMED. The sandbox child is spawned
    by `fork+exec` — a fresh interpreter — and it does NOT inherit
    `PYTHONPATH`. Under `PYTHONPATH=/opt/kir python3.12` (an interpreter
    that has the package not installed), the child's warmup cannot find our
    own modules, and this whole file gave `10 failed, 9 passed`. The same
    tree under the venv, where the package is installed, gives `19 passed`.

    These ten reds were read as a PRODUCT DEFECT and cost a whole
    investigation: "the judge never reaches the model in prod." It does
    reach it. The run was the wrong one. This file's header has named the
    correct command in prose from the very start — and that is exactly what
    proves prose does not hold: only a run must hold it.

    WHY A SKIP, NOT A RELAXATION. Not one assertion in the file is touched:
    where the environment is fit, they judge exactly as before. What changes
    is only that an environment where the measurement NEVER TOOK PLACE says
    so out loud — instead of a plausible-looking red about something else
    entirely.

    🔴 THE SIGNAL IS ASKED OF AN EXACT COPY OF THE CHILD, NOT GUESSED FROM
    THE RECEIPT. The first edition of this skip assumed the child lacked
    the package itself — and was REFUTED by its own probe: in that same
    child, `kir.preview` loads while `kir.design_check` does not. The real
    cause is measured, not inferred:

        python3.12 -s -B -c "import kir.design_check"
        ModuleNotFoundError: No module named 'shapely'
        kir/design_check.py:103  from shapely.geometry import ...

    The child runs with `-s` (user site is disabled ON PURPOSE), and the
    system interpreter keeps `shapely` exactly there. Under venv it sits in
    site-packages — which is why the same file gives `19 passed`.

    🔴 WHY THIS SIGNAL DOES NOT HIDE A REAL DEFECT. It asks about the
    DEPENDENCY, not about warmup. If the `design_check` line ever drops out
    of `_WARM_BY_NAME` again (it has been forgotten three times), the probe
    below will pass SUCCESSFULLY — the module imports on its own — there
    will be no skip, and the file will turn red, as it should. The skip
    fires exactly when there was no one to ask.
    """
    import subprocess          # local: needed only by this one probe
    probe = subprocess.run(
        [sys.executable, "-s", "-B", "-c", "import kir.design_check"],
        capture_output=True, text=True, timeout=120)
    if probe.returncode == 0:
        return
    why = (probe.stderr.strip().splitlines() or ["причина не напечатана"])[-1]
    raise unittest.SkipTest(
        "ЗАМЕР НЕ СОСТОЯЛСЯ, и это факт О СРЕДЕ, а не о продукте: точная "
        f"копия дочернего процесса песочницы ({sys.executable} -s -B) не "
        f"поднимает `kir.design_check` — {why}. Ребёнок идёт с `-s`, то есть "
        "БЕЗ пользовательского site, и зависимость, установленная туда, ему "
        "невидима. Гони этот файл интерпретатором, у которого зависимости "
        "лежат в его собственном site-packages: "
        "venv/bin/python3.12 -m pytest "
        "kir/tests/test_plan_and_verdict_in_the_sandbox.py -q")

#: A small but closed building: two rooms, a window, a door. It needs to be
#: closed specifically — on an unclosed one the verdict honestly does not
#: compute areas, and the test would then be measuring the absence of
#: geometry, not whether the verdict reaches.
HOUSE = '''
lvl = create_level(elev_mm=0, name="Этаж 1")
walls = []
for p0, p1 in [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
               ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
               ((4000, 0), (4000, 5000))]:
    walls.append(create_wall(p0_mm=p0, p1_mm=p1, level=lvl, height_mm=3000))
create_room(xy=(2000, 2500), level=lvl, name="Жилая комната")
create_room(xy=(6000, 2500), level=lvl, name="Кухня")
create_door(host=walls[4], offset_mm=2500)
create_window(host=walls[0], offset_mm=2000)
create_window(host=walls[2], offset_mm=2000)
'''


class ThePlanAndTheVerdictReachTheModel(unittest.TestCase):

    def test_both_names_are_callable_from_the_script(self) -> None:
        """The seam end to end: the name exists, the call goes through, the
        answer arrives IN THIS SAME TURN'S RECEIPT STDOUT, and the program
        still reaches through."""
        result = sandbox.execute_author_script(
            HOUSE + "preview()\ndesign_check()\n", policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(len(result.ops), 11)
        self.assertIn("ПЛАН ПРОГРАММЫ", result.stdout)
        self.assertIn("ВЕРДИКТ О ЗАМЫСЛЕ", result.stdout)

    def test_the_plan_names_what_it_did_not_draw(self) -> None:
        """A plan without a census is a picture. The census must reach
        alongside it."""
        result = sandbox.execute_author_script(HOUSE + "preview()\n",
                                               policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertIn("нарисовано", result.stdout)
        self.assertIn("план НЕ показывает", result.stdout)

    def test_the_verdict_sees_the_rooms_the_script_wrote(self) -> None:
        """THE KEY NUMBER. Before 03.08, the verdict on KIR operations
        answered "HAB000 — model has no rooms" with live `create_room`
        calls present: the shapes never matched, and the diagnosis lied
        about the building."""
        result = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                               policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertNotIn("HAB000", result.stdout)
        self.assertIn("rooms 2", result.stdout)
        self.assertIn("полигон помещения получили 2 из 2", result.stdout)

    def test_the_verdict_headline_is_not_stronger_than_its_body(self) -> None:
        """The heading is the one line that is always read."""
        result = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                               policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        head = next(line for line in result.stdout.splitlines()
                    if "ВЕРДИКТ О ЗАМЫСЛЕ" in line)
        if "ПРИГОДЕН" in head and "НЕПРИГОДЕН" not in head:
            self.assertIn("НЕ ОЦЕНЕНО", head, head)

    def test_calling_them_does_not_swallow_the_program(self) -> None:
        """`take_ops()` is the SANDBOX's door. Calling it from the course
        would mean printing the plan and leaving the turn without a
        program, and silently at that."""
        with_calls = sandbox.execute_author_script(
            HOUSE + "preview()\ndesign_check()\nscore()\n", policy=POLICY)
        without = sandbox.execute_author_script(HOUSE, policy=POLICY)
        self.assertTrue(with_calls.ok,
                        with_calls.refusal and with_calls.refusal.render())
        self.assertTrue(without.ok, without.refusal and without.refusal.render())
        self.assertEqual(with_calls.program_digest, without.program_digest,
                         "печать плана/вердикта изменила саму программу")

    def test_two_runs_of_the_same_script_agree(self) -> None:
        """`replay_check` is on in prod, and it catches OUTPUT
        nondeterminism. Heavy modules (numpy spins up an OpenBLAS thread
        pool) must not break it — otherwise the source signature would stop
        certifying anything."""
        result = sandbox.execute_author_script(
            HOUSE + "preview()\ndesign_check()\n", policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertTrue(result.isolation.get("replay_checked"))


class TheBoundaryDidNotMove(unittest.TestCase):
    """Bring in a capability — you owe a MEASUREMENT of whether you also
    brought in a hole."""

    def _refusal(self, script: str) -> sandbox.SandboxRefusal:
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertFalse(result.ok, f"скрипт прошёл, а не должен был: {script!r}")
        return result.refusal

    def test_the_warmed_modules_are_still_not_importable(self) -> None:
        """THE MOST IMPORTANT THING HERE. shapely/numpy/networkx now sit in
        the child's `sys.modules` — meaning an import would find them in the
        CACHE without ever asking the `sys.meta_path` guard. The cache does
        not save it: the allowlist sits on the script's
        `builtins.__import__` and checks the NAME, not presence.

        The script here calls the verdict FIRST (so the modules are
        certainly warmed) and only then attempts the import — otherwise the
        test would be measuring a ban on something that was never even in
        the process."""
        for module in ("numpy", "shapely", "networkx", "kukai"):
            with self.subTest(module=module):
                refusal = self._refusal(HOUSE + f"design_check()\n"
                                                f"import {module}\n")
                self.assertEqual(refusal.code, "KIR-B004")

    def test_the_injected_names_are_functions_and_not_modules(self) -> None:
        """A module in the script's namespace would hand over its whole
        namespace. The sandbox does not inject modules (`_child_main`), and
        what is introduced must be NARROW: two functions, and nothing
        else."""
        result = sandbox.execute_author_script(
            'print(type(preview).__name__, type(design_check).__name__)\n'
            'create_level(elev_mm=0, name="Э1")\n', policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertIn("function function", result.stdout)

    def test_files_are_still_unreachable(self) -> None:
        refusal = self._refusal('open("/etc/passwd")\n')
        self.assertEqual(refusal.code, "KIR-B005")

    def test_the_network_family_is_still_closed(self) -> None:
        refusal = self._refusal("import socket\n")
        self.assertEqual(refusal.code, "KIR-B004")
        self.assertIn("сети нет", refusal.message_ru)

    def test_isolation_holds_on_a_run_that_warmed_the_heavy_modules(self) -> None:
        """A measurement, not an intent: isolation is reported by EVERY
        run, and a warmed-up run must report the same thing."""
        result = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                               policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        isolation = result.isolation
        self.assertEqual(isolation["filesystem"], "chroot")
        self.assertTrue(str(isolation["namespaces"]).startswith("user"),
                        isolation["namespaces"])
        self.assertTrue(str(isolation["network_probe"]).startswith("unreachable"),
                        isolation["network_probe"])
        self.assertEqual(isolation["warmed"], ["kir.design_check"])


class TheBudgetIsNotEatenByOurOwnImports(unittest.TestCase):
    """`memory_mb` promises the SCRIPT that many megabytes ON TOP OF what is
    already used.

    A DEFECT found by this same run on 03.08 and fixed on the spot. The
    snapshot of used memory (`_self_vm_size`) was taken BEFORE warmup, so
    warmed numpy/shapely ate into the SCRIPT's budget — they reserve address
    space many times over what they occupy in RSS (a peak of 66 MB against a
    256 limit). A live program with 298 operations died with a MemoryError
    INSIDE `json.dumps` on the way out, and on the outside this showed up as
    "KIR-B012: result does not serialize" with `blame: sandbox` — i.e. the
    whole turn was lost, and at the wrong address.
    """

    def test_the_limit_grows_with_what_we_loaded(self) -> None:
        warm = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                             policy=POLICY)
        plain = sandbox.execute_author_script(HOUSE, policy=POLICY)
        for result in (warm, plain):
            self.assertTrue(result.ok,
                            result.refusal and result.refusal.render())
        self.assertGreater(
            warm.isolation["limits"]["RLIMIT_AS"],
            plain.isolation["limits"]["RLIMIT_AS"],
            "предел адресного пространства не вырос вместе с прогревом — "
            "значит бюджет скрипта съеден нашими же импортами")

    def test_a_big_program_still_survives_the_verdict(self) -> None:
        """A measurement, not arithmetic: 250 operations plus the verdict at
        the default budget."""
        script = (
            'lvl = create_level(elev_mm=0, name="Этаж 1")\n'
            'for i in range(60):\n'
            '    x = i * 4000\n'
            '    create_wall(p0_mm=(x, 0), p1_mm=(x, 4000), level=lvl, '
            'height_mm=3000)\n'
            '    create_wall(p0_mm=(x, 0), p1_mm=(x + 4000, 0), level=lvl, '
            'height_mm=3000)\n'
            '    create_wall(p0_mm=(x, 4000), p1_mm=(x + 4000, 4000), '
            'level=lvl, height_mm=3000)\n'
            '    create_room(xy=(x + 2000, 2000), level=lvl, '
            'name="Комната %d" % i)\n'
            'design_check()\n')
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertGreater(len(result.ops), 240)
        self.assertIn("ВЕРДИКТ О ЗАМЫСЛЕ", result.stdout)


class TheCostIsPaidOnlyByWhoAsks(unittest.TestCase):

    def test_a_script_that_never_names_them_warms_nothing(self) -> None:
        """Unconditional warmup would cost +1.1 s on EVERY turn against a
        121 ms happy path. The source decides, and this is not a heuristic:
        a name the model never wrote cannot be called by it — `globals`,
        `eval`, `exec`, and `__import__` are closed to the script."""
        result = sandbox.execute_author_script(
            'create_level(elev_mm=0, name="Этаж 1")\n', policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(result.isolation.get("warmed"), [])

    def test_the_hook_loads_exactly_what_the_name_needs(self) -> None:
        """The PLAN is warmed — we do not load the verdict, and vice versa.
        Otherwise the condition would be one shared toggle masquerading as
        precision."""
        plan_only = sandbox.execute_author_script(HOUSE + "preview()\n",
                                                  policy=POLICY)
        self.assertTrue(plan_only.ok,
                        plan_only.refusal and plan_only.refusal.render())
        self.assertEqual(plan_only.isolation.get("warmed"),
                         ["kir.preview"])


class TheBudgetRefusalSaysHowFarItGot(unittest.TestCase):
    """D-7. The course tells you to print totals at the end of the script —
    and when the bulk budget is exhausted the script is cut off at
    operation #301, and the print NEVER RUNS AT ALL: the receipt's `stdout`
    arrives empty. The model learns that it hit the wall but does not learn
    where to cut, and the next turn starts blind."""

    def test_the_refusal_carries_the_census_of_what_was_collected(self) -> None:
        """🔴 THE CEILING IS SUPPLIED BY THE TEST, NOT TAKEN FROM REAL LIFE
        (fix on 21.08).

        The earlier edition built 401 ops "deliberately over the budget" and
        expected a refusal at the 301st. The premise stopped holding once
        the budget was raised on 20.08 (`_DSL_OP_CEILING = MAX_BULK_OPS`,
        200,000 today), and on 21.08 chunking was wired into the door — a
        program that does not fit in a frame now goes out in slices, and it
        no longer NEEDS to be refused.

        The test's claim, though, has not gone anywhere and is still
        valuable: a budget refusal must CARRY THE CENSUS, because the print
        at the end of the script never runs and `stdout` arrives empty. That
        is exactly what is checked — against a small ceiling substituted for
        the duration of the test. Building two hundred thousand operations
        for the sake of the same claim would mean buying it at the price of
        a run that dies of memory (the neighboring `test_op_budget_seam`
        already showed this).
        """
        # Via the ENVIRONMENT, not by patching the constant: the script runs
        # in a separate process, and an edit in the parent never reaches the
        # child — the first edition of this fix tripped over exactly that.
        # The variable is passed to the child through
        # `sandbox.ENV_PASSTHROUGH`.
        was = os.environ.get("KUKAI_IR_DSL_OP_CEILING")
        os.environ["KUKAI_IR_DSL_OP_CEILING"] = "300"
        try:
            script = ('lvl = create_level(elev_mm=0, name="Э1")\n'
                      'for i in range(200):\n'
                      '    create_wall(p0_mm=(i * 100, 0), '
                      'p1_mm=(i * 100, 3000), level=lvl, height_mm=3000)\n'
                      '    create_room(xy=(i * 100 + 50, 1500), level=lvl, '
                      'name="К%d" % i)\n'
                      'print("итоги")\n')
            result = sandbox.execute_author_script(
                script, policy=sandbox.SandboxPolicy(replay_check=False))
        finally:
            if was is None:
                os.environ.pop("KUKAI_IR_DSL_OP_CEILING", None)
            else:
                os.environ["KUKAI_IR_DSL_OP_CEILING"] = was
        self.assertFalse(
            result.ok,
            "на потолке 300 программа из 401 опа обязана отказать")
        text = result.refusal.render()
        self.assertIn("KIR-L001", text)
        # The author's print really did not get through — otherwise there
        # would be no test.
        self.assertEqual(result.stdout, "")
        # …so the numbers must travel in the refusal itself.
        self.assertIn("СОБРАНО ДО ОТКАЗА: 300 операций", text)
        self.assertIn("create_wall 150", text)
        self.assertIn("create_room 149", text)


class TheOperatorSwitchReachesTheChild(unittest.TestCase):
    """The child's environment is assembled by us from scratch, then wiped
    entirely. A toggle that is not carried over reads, in the child, as "the
    operator turned it off" — and the verdict would answer "turn on what is
    already on"."""

    def test_checker_v2_is_visible_inside_the_sandbox(self) -> None:
        self.assertIn("KIR_CHECKER_V2", sandbox.ENV_PASSTHROUGH)
        result = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                               policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        # 🔴 THE SOUGHT STRING WAS UPDATED TOGETHER WITH THE REFUSAL ITSELF
        # (28.08.2026). "KUKAI_CHECKER_V2=1 is not set" used to stand here.
        # On that day the name moved, the refusal text started saying
        # `KIR_CHECKER_V2` — and the assertion became VACUOUS: the sought
        # string can never occur again, so `assertNotIn` can never turn red
        # under any circumstance. A guard that cannot turn red is worse than
        # a missing one: it occupies the post of a guard.
        self.assertNotIn("не выставлен", result.stdout)
        self.assertIn("ВЕРДИКТ О ЗАМЫСЛЕ", result.stdout)

    def test_both_halves_of_a_renamed_name_travel_to_the_child(self) -> None:
        """🔴 A RENAMED NAME TRAVELS WITH BOTH HALVES, OR NOT AT ALL.

        The child's environment is assembled from scratch. A parent that has
        the NEW name set but only carries over the old one hands the child a
        toggle sitting "off" — and the verdict answers "turn on what is
        already on". This is exactly the refusal that happened on 28.08,
        when the names moved and the flat carry-over list stayed the same.

        What is checked is not the list but the PROPERTY: every carried-over
        name that has a past carries that past along with it.
        """
        from kir import env

        carried = set(sandbox.ENV_PASSTHROUGH)
        for name in sandbox.ENV_PASSTHROUGH:
            legacy = env.RENAMED.get(name)
            if legacy is not None:
                self.assertIn(legacy, carried,
                              f"{name} переносится, а прежнее имя {legacy} — нет: "
                              f"среда, задавшая старое имя, потеряет его у ребёнка")

    def test_a_switched_off_checker_refuses_instead_of_falling_back(self) -> None:
        """Off means a refusal WITH A REASON, not a silent fallback to v1:
        v1 has neither a three-valued verdict nor coverage, and there would
        be nothing to tell it apart from the real thing."""
        was = os.environ.get("KUKAI_CHECKER_V2")
        os.environ["KUKAI_CHECKER_V2"] = "0"
        try:
            result = sandbox.execute_author_script(HOUSE + "design_check()\n",
                                                   policy=POLICY)
        finally:
            if was is None:
                os.environ.pop("KUKAI_CHECKER_V2", None)
            else:
                os.environ["KUKAI_CHECKER_V2"] = was
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertIn("ВЕРДИКТ НЕДОСТУПЕН", result.stdout)
        # The program is not lost in the process: an unreachable verdict is
        # not a broken turn.
        self.assertEqual(len(result.ops), 11)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
