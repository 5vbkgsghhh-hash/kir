"""THE `program_py` COURSE — tests that keep it honest.

WHAT IS CHECKED HERE, AND WHY EXACTLY THIS.

1. NUMBERS ARE RECOMPUTED. Every measurement in the course is taken
   fresh from disk and checked against what is recorded. A stale
   measurement in the course is indistinguishable from a fabrication,
   and only a recomputation can tell them apart.
2. EXAMPLES ARE EXECUTED. Every recipe is run through a REAL sandbox (a
   separate process, chroot, zero network, `replay_check` — that is, a
   determinism check by measurement) and its output is compiled against
   SIX versions of Revit. An example that was never run is a promise.
3. THE NUMBERS SHOWN ARE A MEASUREMENT OF THIS RUN. `Recipe.ops`/
   `elements` are checked against what actually came out. The course has
   no right to promise one thing and build another.
4. THE SEAM IS EITHER WHOLE OR IT DOES NOT EXIST. The pointer in the
   tool's description promises names; the test requires that what is
   promised be REACHABLE from the sandbox. Half a seam is a red test,
   not a quiet round lost by the model.
5. THE TWO COURSES DO NOT OVERLAP. `skill.py` is about the `program`
   field and macros, this one is about `program_py`. An overlap is paid
   for twice and drifts apart at the very first edit.

THE COST OF THE SUITE. Eight sandbox runs at ~0.3 s each, plus six
emissions per recipe. This is the most expensive test in the package,
and deliberately so: a cheap check of the course would be checking the
text, not the work.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import unittest

from kir import compiler, dsl, sandbox, skill, spec
from kir import course as C
from kir.course import corpus, lessons, recipes
from kir.ground import ground
from kir.tests.fixtures import GROUND_SNAPSHOT

#: Recipes are executed with EXACTLY the set of names the model will get
#: after the seam: the language plus the course. Not one relaxation of
#: policy, except for `replay_check` — it tightens rather than loosens:
#: the script is run twice with a digest comparison.
POLICY = sandbox.SandboxPolicy(dsl_module="kir.course.language",
                               replay_check=True)


def _program(result: sandbox.SandboxResult) -> dict:
    envelope = dict(result.envelope or {})
    envelope.pop("ir_version", None)
    return {"ir_version": spec.IR_VERSION, **envelope, "ops": result.ops}


class _Run:
    """One recipe run. Cached per class: eight recipes × six versions is
    already noticeable time, and there is no reason to pay for it
    twice."""

    _cache: dict[str, sandbox.SandboxResult] = {}

    @classmethod
    def of(cls, name: str) -> sandbox.SandboxResult:
        if name not in cls._cache:
            cls._cache[name] = sandbox.execute_author_script(
                recipes.RECIPES[name].source, policy=POLICY)
        return cls._cache[name]


# ═════════════════════════════════════════════════════════════════════════
# 1. NUMBERS
# ═════════════════════════════════════════════════════════════════════════

class EveryNumberRecomputes(unittest.TestCase):

    def test_every_measurement_is_recomputed_from_the_corpus(self) -> None:
        """A measurement against its own source, for one building.

        The skip is declared BY NAME: "there is no decompile on this box"
        and "the decompile exists but is empty" are different facts, and
        confusing them costs more than not measuring at all.
        """
        missing = [b for b in corpus.BUILDINGS if not corpus.available(b)]
        if len(missing) == len(corpus.BUILDINGS):
            self.skipTest(f"корпуса нет на боксе: {corpus.DECOMPILE_ROOT}")
        drift = []
        for key, m in corpus.MEASUREMENTS.items():
            if m.recompute is None:
                continue
            try:
                got = m.recompute()
            except FileNotFoundError:
                continue                       # this building is not on this box
            if abs(got - m.value) > 0.051:
                # 🔴 A DISCREPANCY WITH NO REASON SENDS THE FIX TO THE
                # WRONG PLACE. "The number is stale" and "the index it is
                # computed from is not on this machine" both produce the
                # same "recomputed to 0", yet their next move differs: the
                # first is fixed in the table, the second on disk.
                why = None
                for _fname in ("group.index.json", "curtain.index.json"):
                    why = corpus.index_absent_reason(
                        m.source.split("/")[-2], _fname)
                    if why is not None:
                        break
                drift.append(
                    f"{key}: записано {m.value}, пересчёт {got}"
                    + (f" — {why}" if why else ""))
        self.assertEqual(drift, [], "замеры курса разошлись с корпусом")

    def test_the_derived_map_comes_from_acceptance_and_is_not_empty(self) -> None:
        """A second list of derived categories is not introduced: it is
        taken from acceptance, where it carries weight. Renaming
        `_OP_DERIVED` must break the course LOUDLY."""
        derived = corpus.derived_categories()
        self.assertGreater(len(derived), 10)
        for category, ops in derived.items():
            self.assertTrue(category.startswith("OST_"), category)
            for op_name in ops:
                self.assertIn(op_name, spec.OPS, f"{category} <- {op_name}")

    def test_no_derived_category_has_an_op_of_its_own(self) -> None:
        """The lesson "for free" stands on this: there is NOTHING that can
        write elements of derived categories. The assertion is checked
        against the registry's capability cells."""
        derived = set(corpus.derived_categories())
        claimed = {kind for op in spec.OPS.values() for _a, kind in op.capability}
        self.assertEqual(derived & claimed, set())

    def test_our_own_trace_still_shows_zero_group_uses(self) -> None:
        """The number the course was written for. Recomputed from live
        telemetry, if it exists on this box."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(C.__file__))))),
            "data", "telemetry", "kir_rejections.jsonl")
        if not os.path.exists(path) or not os.access(path, os.R_OK):
            self.skipTest("телеметрии отказов нет на этом боксе")
        import json
        ops = set()
        rows = 0
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                rows += 1
                ops.add((json.loads(line) or {}).get("op_requested"))
        # A LOCAL ARTIFACT — NOT THE CORPUS (09.08n). The test reads a
        # file by a path relative to the module, and worktree runs WRITE
        # to that same place unless `KIR_REJECTIONS_PATH` is set (that is
        # what `test_golden` does). As a result, five lines appended by a
        # neighboring test were being read as a 1,453-line production
        # corpus, and the assertion about the corpus was turning red from
        # a fact about the ENVIRONMENT.
        #
        # A skip here is more honest than a refusal for exactly the same
        # reason the file might not exist at all: what we are holding is
        # the WRONG file, not a bad answer. The threshold is named in a
        # line, not left to silence, so that "skipped" does not read as
        # "checked".
        if rows < corpus.LIVE_REJECTIONS_MEASURED:
            self.skipTest(
                f"на этом боксе {rows} строк отказов против замеренных "
                f"{corpus.LIVE_REJECTIONS_MEASURED} — это локальный артефакт "
                f"прогонов, а не корпус; утверждать по нему нечего")
        # 🔴 IT USED TO BE `assertNotIn("create_group", ops)` — A LITERAL
        # ZERO, and it went stale on 18.08.2026: the op appeared in the
        # refusals (64 lines, 63 in a single day). This test's class is
        # called `EveryNumberRecomputes`, and the assertion about zero was
        # the one thing in it that was NOT recomputed — it pinned the
        # OUTCOME of a measurement instead of the measurement itself.
        # Such a guard does not catch the subject moving, it only catches
        # the first move and stays red forever after.
        #
        # Now what is RECORDED is checked against what is MEASURED. If it
        # shifts again, it will turn red again, and the record will have
        # to be re-taken with a date, not have its threshold nudged. Zero
        # remains expressible: if the op disappears from the refusals,
        # the constant must become zero, otherwise the test is red.
        measured = sum(
            1 for line in open(path, encoding="utf-8") if line.strip()
            and (json.loads(line) or {}).get("op_requested") == "create_group")
        self.assertEqual(
            measured, corpus.GROUP_IN_LIVE_REJECTIONS,
            f"`create_group` в живых отказах: измерено {measured}, записано "
            f"{corpus.GROUP_IN_LIVE_REJECTIONS}. Запись обязана нести ЗАМЕР с "
            f"датой (corpus.py), а не пережившее свой факт число — курс "
            f"написан вокруг этой величины и печатает её МОДЕЛИ")


# ═════════════════════════════════════════════════════════════════════════
# 2-3. EXAMPLES ARE EXECUTED, AND NUMBERS ARE A MEASUREMENT
# ═════════════════════════════════════════════════════════════════════════

class EveryRecipeRuns(unittest.TestCase):

    def test_every_recipe_runs_in_the_real_sandbox(self) -> None:
        for name in recipes.ORDER:
            with self.subTest(recipe=name):
                result = _Run.of(name)
                self.assertTrue(
                    result.ok,
                    result.refusal and result.refusal.render())
                self.assertTrue(result.isolation.get("replay_checked"))

    def test_the_numbers_the_course_shows_are_the_numbers_it_produces(self) -> None:
        """What is shown and what is built cannot drift apart, by
        construction."""
        for name in recipes.ORDER:
            with self.subTest(recipe=name):
                item = recipes.RECIPES[name]
                got = C.measure(_Run.of(name).ops)
                self.assertEqual(got["операций написано"], item.ops)
                self.assertEqual(got["элементов объявлено"], item.elements)

    def test_every_recipe_compiles_on_all_six_revit_versions(self) -> None:
        """"The script ran" and "the program builds" are different
        assertions. Emission branches by version, hence six, not one."""
        for name in recipes.ORDER:
            with self.subTest(recipe=name):
                program = _program(_Run.of(name))
                planned = compiler.plan_program(program, bulk=True)
                ground(planned.to_ops(), GROUND_SNAPSHOT)   # raises on refusal
                for version in spec.REVIT_VERSIONS:
                    out = compiler.compile_program(
                        program, revit_version=version,
                        snapshot=GROUND_SNAPSHOT, bulk=True)
                    self.assertTrue(getattr(out, "ok", False),
                                    f"{name} не собрался под {version}")

    def test_every_program_of_a_recipe_compiles_not_only_the_last(self) -> None:
        """🔴 A RECIPE OF TWO PROGRAMS WAS ONLY HALF-CHECKED (measured
        03.09.2026).

        The sandbox hands back the LAST program of the script, so the
        neighboring check above was compiling only the body for
        "housing". The stairs are the first program, and are written that
        way per `KIR-L002` ("stairs own their own transactions"). The
        live door was answering it with `KIR-P007` "no run specified": a
        recipe that promises a verdict could not be built, and not a
        single test saw it — the subject of the check simply never
        arrived.

        The subject is obtained by TRUNCATING THE SOURCE at each
        successive `build()`: this is exactly what the script produces if
        stopped there. The extra run is needed only for recipes that
        leave something behind — and the outcome itself now says so
        (`SandboxResult.left_behind`).
        """
        for name in recipes.ORDER:
            итог = _Run.of(name)
            оставлено = list(getattr(итог, "left_behind", ()) or ())
            if not оставлено:
                continue
            # THE PROGRAM BOUNDARY IS `reset()`, NOT EVERY `build()`: the
            # first edition cut at `build()` and also caught the one
            # sitting inside `design_check([stairs, build()])` — that is,
            # it counted a read as a program. Measured: "2 programs, 1
            # left behind".
            строки = recipes.RECIPES[name].source.splitlines()
            границы = [i for i, l in enumerate(строки) if l.startswith("reset(")]
            self.assertEqual(
                len(границы), len(оставлено),
                f"{name}: границ `reset()` {len(границы)}, а оставленных "
                f"{len(оставлено)} — учёт и исходник разошлись")
            куски = ["\n".join(строки[:i]) + "\n" for i in границы]
            for i, префикс in enumerate(куски):
                with self.subTest(recipe=name, программа=i):
                    ранняя = sandbox.execute_author_script(префикс)
                    self.assertTrue(
                        ранняя.ok,
                        f"{name}: программа {i} не исполнилась: "
                        f"{ранняя.refusal and ранняя.refusal.render()}")
                    program = {"ir_version": "1.0",
                               "ops": [dict(op) for op in ранняя.ops]}
                    planned = compiler.plan_program(program, bulk=True)
                    ground(planned.to_ops(), GROUND_SNAPSHOT)
                    for version in spec.REVIT_VERSIONS:
                        out = compiler.compile_program(
                            program, revit_version=version,
                            snapshot=GROUND_SNAPSHOT, bulk=True)
                        self.assertTrue(
                            getattr(out, "ok", False),
                            f"{name}: программа {i} не собралась под {version}: "
                            f"{[d.code for d in (out.diagnostics or ())][:3]}")

    def test_the_pair_recipes_really_differ_in_form_not_in_result(self) -> None:
        """A "junior — senior" pair must give ONE result in different
        forms: a comparison in which both sides differ shows nothing. The
        exception is named — the floors cover a different number of
        levels, and this is recorded in `covers`."""
        for senior, junior in (("санузел", "санузел-джуниор"),):
            s, j = recipes.RECIPES[senior], recipes.RECIPES[junior]
            self.assertEqual(s.elements, j.elements)
            self.assertEqual(s.covers, j.covers)
            self.assertLess(s.ops, j.ops)

    def test_the_group_recipe_actually_produces_a_native_group(self) -> None:
        """The course's main op — in full, down to the grounding of its
        members.

        `create_group` was called 0 times across 51,574 raised
        operations, precisely because grounding never reached inside
        `members`. The test holds the fix in place: members are resolved
        BY NAME, like ordinary ops.
        """
        ops = _Run.of("санузел").ops
        self.assertEqual(len(ops), 1)
        group = ops[0]
        self.assertEqual(group["op"], "create_group")
        self.assertEqual(len(group["members"]), 3)
        self.assertEqual(len(group["placements"]), 5)
        self.assertEqual(group["name"], "Кабинка су")
        grounded = ground(
            compiler.plan_program(_program(_Run.of("санузел")),
                                  bulk=True).to_ops(),
            GROUND_SNAPSHOT)
        for member in grounded[0]["members"]:
            self.assertIn("__grounded__", member["level"])
            self.assertEqual(member["level"]["__grounded__"]["via"], "name")

    def test_a_ref_to_a_sibling_above_inside_a_group_is_LEGAL(self) -> None:
        """THE LAW WAS REWRITTEN ON 12.08.2026, and the old edition was
        NOT BROKEN.

        Before that day, the test pinned the opposite: any `ref` inside a
        group member was refused. It was doing its job honestly — the
        subject simply changed, and here is why it HAD to change:

        a door addresses its wall ONLY through `ref`, meaning "ref inside
        a member is forbidden" meant "a floor with walls AND doors cannot
        be assembled into a group AT ALL". And 41.1% of a real tower's
        elements live in groups (walls 94.9%, doors 91.4%), and a human
        models a 59-floor building exactly this way: assemble a floor,
        group it, place it 59 times. All that remained was enumeration,
        running into the 300-op cap.

        The old edition's own docstring named the cost: "a shown boundary
        that in fact holds teaches the model to fear a technique that
        works". Now it stands on the other side: the technique works, and
        it is THAT which must be shown.
        """
        script = ('LVL = {"by": "name", "value": "Этаж 1"}\n'
                  'with unit("Блок", placements=[(3000, 0), (6000, 0)]):\n'
                  '    w = create_wall(p0_mm=(0, 0), p1_mm=(5000, 0), '
                  'level=LVL, height_mm=3000)\n'
                  '    create_door(host=w, offset_mm=1500)\n'
                  '    create_window(host=w, offset_mm=3500, sill_mm=900)\n')
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        planned = compiler.plan_program(_program(result), bulk=True).to_ops()
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["op"], "create_group")
        self.assertEqual(len(planned[0]["members"]), 3)
        self.assertEqual(len(planned[0]["placements"]), 2)

    def test_a_ref_OUTSIDE_the_group_is_refused_and_names_the_next_move(self):
        """The first of TWO boundaries remaining after the law was
        rewritten.

        A group is a small program in its own namespace; a reference
        reaching out of it resolves against nothing, because the group is
        placed N times, while the addressee outside it is one.
        """
        script = ('LVL = {"by": "name", "value": "Этаж 1"}\n'
                  'outer = create_wall(p0_mm=(0, 0), p1_mm=(3000, 0), '
                  'level=LVL, height_mm=3000)\n'
                  'with unit("Блок", placements=[(3000, 0)]):\n'
                  '    create_door(host=outer, offset_mm=1500)\n')
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        with self.assertRaises(Exception) as caught:
            compiler.plan_program(_program(result), bulk=True)
        text = str(caught.exception)
        self.assertIn("KIR-T001", text)
        self.assertIn("НАРУЖУ", text)
        self.assertIn("element_id", text, "отказ обязан назвать СЛЕДУЮЩИЙ ХОД")

    def test_a_ref_FORWARD_inside_the_group_is_refused_and_says_why(self):
        """The second boundary — and it is checked with a JSON program
        DELIBERATELY.

        In Python a forward reference is INEXPRESSIBLE: the handle does
        not exist until the op is called. That is, this boundary cannot
        be probed with a script even in principle, and a test on a
        script would silently be checking a void. Programs are also
        submitted directly (`/admin/kir/run`), so the law must hold
        there too.
        """
        program = {
            "ir_version": spec.IR_VERSION,
            "intent": "дверь объявлена ВЫШЕ своей стены",
            "ops": [{"op": "create_group", "id": "G", "name": "Блок",
                     "placements": [[3000, 0]],
                     "members": [
                         {"op": "create_door", "id": "D",
                          "host": {"by": "ref", "value": "W"},
                          "offset_mm": 1500},
                         {"op": "create_wall", "id": "W",
                          "p0_mm": [0, 0], "p1_mm": [3000, 0],
                          "height_mm": 3000,
                          "level": {"by": "name", "value": "Этаж 1"}}]}]}
        with self.assertRaises(Exception) as caught:
            compiler.plan_program(program, bulk=True)
        text = str(caught.exception)
        self.assertIn("KIR-T001", text)
        self.assertIn("НИЖЕ", text)
        self.assertIn("выше", text, "отказ обязан назвать СЛЕДУЮЩИЙ ХОД")

    def test_a_group_member_cannot_stand_on_a_level_this_program_creates(self):
        """A NEGATIVE CONTROL for "two programs".

        Found by running the example, not by reasoning, and it stands
        here because the cost of not knowing is a wasted round. Both
        branches are closed, each with its own code: a level handle gets
        KIR-T001 at decompile time, the NAME of the same level gets
        KIR-G101 at grounding. Hence the lesson's rule: a new floor and
        the group on it are two programs.
        """
        by_handle = ('lvl = create_level(elev_mm=0, name="Новый")\n'
                     'with unit("Блок", placements=[(3000, 0)]):\n'
                     '    create_wall(p0_mm=(0, 0), p1_mm=(3000, 0), '
                     'level=lvl, height_mm=3000)\n')
        result = sandbox.execute_author_script(by_handle, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        with self.assertRaises(Exception) as caught:
            compiler.plan_program(_program(result), bulk=True)
        self.assertIn("KIR-T001", str(caught.exception))

        by_name = ('create_level(elev_mm=0, name="Новый")\n'
                   'with unit("Блок", placements=[(3000, 0)]):\n'
                   '    create_wall(p0_mm=(0, 0), p1_mm=(3000, 0), '
                   'level={"by": "name", "value": "Новый"}, height_mm=3000)\n')
        second = sandbox.execute_author_script(by_name, policy=POLICY)
        self.assertTrue(second.ok, second.refusal and second.refusal.render())
        planned = compiler.plan_program(_program(second), bulk=True)
        with self.assertRaises(Exception) as caught:
            ground(planned.to_ops(), GROUND_SNAPSHOT)
        self.assertIn("KIR-G101", str(caught.exception))

        # …and the lesson WARNS about this: a boundary known to the code
        # and unknown to the course is a round spent by the model on our
        # silence.
        text = lessons.lesson("единица")
        self.assertIn("KIR-T001", text)
        self.assertIn("KIR-G101", text)
        self.assertIn("ДВЕ ПРОГРАММЫ", text)

    def test_an_empty_unit_refuses_instead_of_making_an_empty_group(self) -> None:
        script = ('with unit("Пусто"):\n'
                  '    pass\n')
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertFalse(result.ok)
        self.assertIn("не собрал ни одной операции", result.refusal.message_ru)

    def test_the_unit_context_restores_the_outer_program(self) -> None:
        """A unit must not drag its neighbors along with it: whatever is
        written AFTER the block must land in the program, not in the
        group."""
        script = ('LVL = {"by": "name", "value": "Этаж 1"}\n'
                  'with unit("Блок", placements=[(3000, 0)]):\n'
                  '    create_wall(p0_mm=(0, 0), p1_mm=(3000, 0), level=LVL, '
                  'height_mm=3000)\n'
                  'create_room(xy=(1500, 1500), level=LVL, name="После")\n')
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual([op["op"] for op in result.ops],
                         ["create_group", "create_room"])


# ═════════════════════════════════════════════════════════════════════════
# 4. THE SEAM
# ═════════════════════════════════════════════════════════════════════════

class TheSeamIsWholeOrAbsent(unittest.TestCase):

    #: `phase` was added on 09.08 — the phase boundary lives in the same
    #: place as `unit`, and must be reachable from the PRODUCTION set of
    #: names. It is deliberately absent from `POINTER` (phase-by-phase
    #: execution does not exist yet), and the neighboring test holds
    #: exactly the pointer, not this list. `spec` arrived on the same
    #: date in a different wave: the list is the UNION of two waves, not
    #: a choice of one of them.
    # A CLOSED LIST, AND IT MUST DEMAND A DECISION. A new name in the
    # seam forces someone to come here by hand — that is the whole
    # point: a name silently injected into the sandbox is checked by NO
    # reachability guard at all.
    # `extrude`/`region` arrived with the expressiveness wave of
    # 19.08.2026. `sweep` was added on 19.08.2026 together with its
    # constructor. The list is hand-written and CLOSED deliberately: it
    # forces a decision to be made for every new name in the sandbox,
    # rather than inheriting it silently. It worked exactly that way —
    # it turned red on `sweep` in the very same pass the name appeared.
    # `offset`/`thicken` were added on 29.08.2026 together with the seam
    # being run through (an audit finding, F-293): `kir/curveops.py`
    # declared itself a set of AUTHOR's Python constructors and cited
    # the production sandbox as precedent, yet never placed the names
    # into the script's namespace — and the module's own host tests
    # were green, because they import `kir.curveops` DIRECTLY, meaning
    # they were checking arithmetic the author has no door to. Arriving
    # here by hand is not a way around the guard, but exactly the
    # trip-wire this list was closed to provide.
    #: THE SEAM'S FLOOR — A CLOSED LIST, BUT NOT A COMPLETE ONE, AND THE
    #: DIFFERENCE CARRIES WEIGHT.
    #: A SECOND LIST of the same names used to stand here, and it was
    #: obligated to match `C.SANDBOX_NAMES` — that is, exactly the form
    #: this tree catches in itself more often than any other: two
    #: records of one fact, tied together by nothing. Meanwhile the
    #: check `sorted(SANDBOX_NAMES) == sorted(NAMES)` is GREEN FOR ANY
    #: VALUE OF BOTH, as long as both are edited together (form 48), and
    #: turns red when only one is edited, saying nothing about the
    #: subject: on 01.09.2026 wiring in fifteen freeform-geometry names
    #: turned it red, and the red was saying "the lists diverged", not
    #: "the seam is broken".
    #:
    #: Now, a FLOOR: the names below must ALWAYS BE in the seam — the
    #: disappearance of any one of them turns it red by name. Additions
    #: remain free and are guarded more strictly than before: the live
    #: run below runs the ENTIRE seam through a real sandbox, meaning
    #: every NEW name must reach the child, not merely land in a
    #: dictionary. The old list did not provide that: it checked
    #: thirteen names, while the seam could carry any number of them.
    SEAM_FLOOR = ("course", "recipe", "unit", "phase", "score", "preview",
                  "design_check", "spec", "extrude", "region", "sweep",
                  "offset", "thicken",
                  # freeform geometry, run through on 01.09.2026
                  "loft", "blend", "revolve", "box", "sphere", "cylinder",
                  "prism", "move", "rotate", "mirror", "scale", "array",
                  "section", "faces", "by_property")

    @property
    def NAMES(self) -> tuple[str, ...]:
        """The WHOLE seam, asked of itself: a live run must cover
        everything."""
        return tuple(sorted(C.SANDBOX_NAMES))

    def test_the_course_names_are_reachable_through_the_shim(self) -> None:
        """The other half of the seam is checked LIVE before it is run
        through."""
        script = "\n".join(
            [f'print("{name}", callable({name}))' for name in self.NAMES]
            + ['query_count(kind="wall")'])
        result = sandbox.execute_author_script(script, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        for name in self.NAMES:
            self.assertIn(f"{name} True", result.stdout)

    def test_the_shim_still_drains_the_program(self) -> None:
        """`take_ops` is deliberately absent from `dsl.__all__`; the shim
        must import it BY NAME, otherwise the program would assemble
        while zero operations came out the other end — the quietest
        defect possible."""
        from kir.course import language
        self.assertTrue(callable(getattr(language, "take_ops", None)))
        result = sandbox.execute_author_script(
            'create_level(elev_mm=0, name="L")\n', policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(result.isolation["harvest"], "dsl.take_ops()")

    def test_the_pointer_and_reachability_are_one_thing(self) -> None:
        """THE SEAM'S MAIN TEST. The pointer promises names — so the
        names must be reachable FROM THE PRODUCTION policy, not only
        from the shim. As long as the seam has not been run through, the
        tool description has no pointer, and the assertion holds
        vacuously; afterward, both halves must stand together. Half a
        seam fails here, rather than silently costing the model a round.
        """
        from kir.tool_doc import build_tool_description
        advertised = "course()" in build_tool_description()
        probe = sandbox.execute_author_script(
            'print("есть" if "course" in dir() else "нет")\n'
            'query_count(kind="wall")\n')
        self.assertTrue(probe.ok, probe.refusal and probe.refusal.render())
        reachable = "есть" in probe.stdout
        self.assertEqual(
            advertised, reachable,
            "указатель курса и достижимость его имён разошлись: "
            f"в описании {'есть' if advertised else 'нет'}, "
            f"в песочнице {'есть' if reachable else 'нет'}")

    def test_the_spec_pointer_and_reachability_are_one_thing(self) -> None:
        """The same coin for `spec`, and it cost a day, 09.08.

        A capability the model cannot learn about from the description
        is dark BY CONSTRUCTION, and this is not theory: the language's
        docstrings (41,519 characters from the registry) were already
        being read with `print(<op>.__doc__)` before this wave — but
        that was said NOWHERE except in the text of one refusal. That is
        why the promise and its reachability are checked together, not
        apart.
        """
        from kir.tool_doc import build_tool_description
        advertised = "spec(" in build_tool_description()
        probe = sandbox.execute_author_script(
            'print("есть" if "spec" in dir() else "нет")\n'
            'query_count(kind="wall")\n')
        self.assertTrue(probe.ok, probe.refusal and probe.refusal.render())
        reachable = "есть" in probe.stdout
        self.assertEqual(
            advertised, reachable,
            "указатель на spec() и достижимость имени разошлись: "
            f"в описании {'есть' if advertised else 'нет'}, "
            f"в песочнице {'есть' if reachable else 'нет'}")

    def test_the_pointer_is_small_enough_to_hang_permanently(self) -> None:
        """The standing cost is named as a number. The description
        threshold is 30,000 characters.

        FIXED AFTER THE SEAM, and this is not a relaxation but a
        correction of DOUBLE COUNTING. The test was written when the
        pointer was NOT YET in the description, and it modeled "how much
        it would become if added": `len(description) + len(pointer)`.
        After `tool_doc._course_pointer()` inserted it in place of the
        line about `tools/design/examples/*`, the same arithmetic counts
        the pointer TWICE and declares an overrun where there is none
        (29,685 + 705 = 30,390 against the real 29,685).

        Both real assertions are preserved: the pointer is small on its
        own, and the description as a whole fits the threshold. Only the
        artifact of the moment the test was written is lost.
        """
        from kir.tool_doc import build_tool_description
        size = sum(len(line) + 1 for line in C.POINTER)
        self.assertLess(size, 700)
        description = build_tool_description()
        # The pointer must ALREADY be inside — otherwise the double
        # count would be correct, and the seam would be torn (this is
        # guarded by the neighboring reachability test).
        self.assertIn("course(", description)
        self.assertLess(len(description), 30_000)

        # 🔴 AND THIS IS NOT THE VALUE PRODUCTION ACTUALLY HANDS OUT. The
        # line above measures the description WITHOUT the geometry flag,
        # while in the service it is ON, and the whitelist prints into a
        # longer description. Measured 20.08.2026: 28,675 without the
        # flag versus 28,691 with it. Sixteen characters is a trifle,
        # but a guard measuring the wrong quantity is never a trifle: it
        # is our own named defect (declared in one place, read in
        # another), and the margin it would show would belong to
        # someone else. We take the WORST case — the one that actually
        # reaches the model.
        saved = os.environ.get(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG)
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"
        try:
            worst = build_tool_description()
        finally:
            if saved is None:
                os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)
            else:
                os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = saved
        self.assertGreaterEqual(len(worst), len(description),
                                "флаг обязан только ДОБАВЛЯТЬ имена в список")
        self.assertLess(len(worst), 30_000)

    def test_the_seam_is_described_and_names_real_places(self) -> None:
        self.assertEqual(len(C.SEAM), 2)
        for where, _what in C.SEAM:
            self.assertTrue(where.startswith("kir/"), where)
        # The seam's floor: a disappeared name is named by name, not
        # "the lists diverged".
        пропали = sorted(set(self.SEAM_FLOOR) - set(C.SANDBOX_NAMES))
        self.assertEqual(пропали, [], f"имена ушли из шва: {пропали}")
        for value in C.SANDBOX_NAMES.values():
            self.assertTrue(callable(value))


# ═════════════════════════════════════════════════════════════════════════
# 4b. `spec()` — A CONTRACT FROM THE REGISTRY, NOT A SECOND COPY OF IT
# ═════════════════════════════════════════════════════════════════════════

class TheRegistryLookupHasOneSource(unittest.TestCase):
    """A reference document is dangerous in exactly one way: it can
    become a second opinion.

    A document living next to code drifts apart from the code — in this
    repository that has been measured repeatedly (`_host_level_sill`
    declared a negative sill impossible while 140 negative ones existed
    in a live building). That is why the tests here check not "is it
    printed nicely" but ONE thing: that what gets printed is the
    REGISTRY.
    """

    def test_the_printed_contract_is_the_registry_docstring_verbatim(self) -> None:
        """A MECHANICAL GUARD AGAINST A SECOND COPY, across every op at
        once.

        The very first hand-written line of a contract — even a single
        tolerance typed in as a number — breaks this test: an op's
        docstring must enter the output VERBATIM.

        WHY "VERBATIM" BUT NO LONGER "IN FULL" (12.08.2026). Two
        registry contracts outgrew the print channel: `route_duct_system`
        at 3,967 characters and `route_pipe_system` at 3,904, against a
        cap of 3,300. The old edition demanded completeness and turned
        red on both — and underneath that red sat a live defect: the
        TAIL was being truncated, meaning the WITNESS'S PARAMETERS AND
        TOLERANCES were falling off the end, and the model was authoring
        the graph-op without ever seeing them. Verified through the same
        door the model uses: `execute_author_script`, under production
        policy, was handing back 3,300 characters with no mention of
        "Tolerances".

        Now the POSTCONDITION PROSE is shortened from within, while
        every section still gets through, so the check changed shape to
        match: verbatim matching of every section that arrives, plus a
        separate test that the excised part is named as an exact slice.
        This is not a relaxation — the old check could not tell "it fit"
        from "it fit with the tolerances cut off".
        """
        for name in sorted(spec.OPS):
            with self.subTest(op=name):
                printed = _printed(lambda: C.spec(name))
                doc = dsl.OP_FUNCTIONS[name].__doc__
                self.assertIn(dsl._call_head(spec.OPS[name]), printed)
                if doc in printed:
                    continue
                # The shortened case: both halves of the docstring are
                # VERBATIM, with a named excision between them. Not one
                # word is "our own". TWO WORDS, NOT ONE: since
                # 25.08.2026, for a contract with SHORT prose it is
                # excised WHOLESALE rather than shortened — otherwise a
                # scrap of a sentence would be left behind. The sections
                # get through in both outcomes, and that is exactly what
                # is checked.
                self.assertRegex(printed, r"ПРОЗА ПОСТУСЛОВИЯ (СОКРАЩЕНА|ВЫРЕЗАНА)",
                                 "докстрока не доехала и вырезка не названа")
                shown, _, tail = printed.partition("\n    […ПРОЗА")
                self.assertIn(doc[:200], shown)
                self.assertIn(doc[-200:], tail)

    def test_the_excision_recipe_returns_exactly_what_was_cut(self) -> None:
        """A PLAUSIBLE BUT OFFSET SLICE IS WORSE THAN NO ADVICE AT ALL.

        The advice counts indices WITHIN THE DOCSTRING, while the
        printed text carries OUR OWN heading: an error of exactly that
        length would produce a coherent, populated, and wrong chunk —
        exactly the plausible neighbor that does not look incomplete.
        That is why the splice is checked byte for byte.
        """
        import re
        cut = 0
        for name in sorted(spec.OPS):
            printed = _printed(lambda: C.spec(name))
            match = re.search(rf"print\({name}\.__doc__\[(\d+):(\d+)\]\)",
                              printed)
            if match is None:
                continue
            cut += 1
            start, stop = int(match.group(1)), int(match.group(2))
            doc = dsl.OP_FUNCTIONS[name].__doc__
            excised = doc[start:stop]
            with self.subTest(op=name):
                self.assertTrue(excised, "срез пуст — совет ведёт в никуда")
                self.assertNotIn(excised, printed,
                                 "вырезанное осталось в выводе: совет "
                                 "предлагает достать то, что и так приехало")
                self.assertIn(doc[:start][-120:], printed)
                self.assertIn(doc[stop:][:120], printed)
        self.assertEqual(
            cut, 3,
            "число сокращённых контрактов изменилось. Это не повод двигать "
            "число: перемерить длины (course._spec_parts) и решить, вырос ли "
            "контракт или сдвинулся потолок канала")
        # 🔴 THE NUMBER MOVED ON 25.08.2026 AFTER A MEASUREMENT, NOT BECAUSE
        # IT GOT IN THE WAY — exactly as the line above requires. A
        # registry-wide census at a 3 300 channel:
        #
        #     op                    text   prose   keep  outcome
        #     create_solid_blend    3541    477     14  was tail-trimming
        #     route_duct_system     3967   2850   1960  prose compression
        #     route_pipe_system     3904   2786   1959  prose compression
        #
        # Neither did the contract grow, nor did the ceiling move:
        # `create_solid_blend` overflowed the channel before too, but fell
        # into the TAIL-trimming branch and lost parameter boundaries. Now
        # its prose is cut out whole, the sections make it through, and it
        # legitimately joins this count as a third.
        # 🔴 REMEASURED ON 07.09.2026 WITH THE SAME INSTRUMENT. The count is
        # the same — THREE — but the numbers shifted from edits to the
        # registry's own docstrings:
        #
        #     op                  text   prose  without_prose  RESERVE   was
        #     create_solid_blend   3538    477       3061     18   3541
        #     route_pipe_system    3899   2786       1113   1966   3904
        #     route_duct_system    3962   2850       1112   1967   3967
        #
        # RESERVE — how many characters the contract can still hold WITHOUT
        # LOSING the tail; it is measured by binary search against the live
        # cutter in
        # `tests/test_an_overflowing_contract_keeps_its_tail.py` and is NOT
        # equal to `3300 - текст` (that estimate puts `create_solid_blend`
        # and `route_duct_system` in the reverse order). It was the number 18
        # that decided, on 07.09.2026, not to write the "WHAT THIS OP CANNOT
        # DO" block (a 321-character median) into the contract text: the
        # axes moved off into the MCP door's machine field.

    def test_every_section_of_the_contract_survives_the_channel(self) -> None:
        """THE GUARANTEE ALL OF THIS IS FOR: the sections ALL make it through.

        The ceiling is a property of the channel, and the guarantee is a
        property of the contract, and the run is the one obligated to hold
        the link between them. Otherwise "the contract was printed" would
        again come to mean "however much fit."
        """
        for name in sorted(spec.OPS):
            ospec = spec.OPS[name]
            with self.subTest(op=name):
                printed = _printed(lambda: C.spec(name))
                self.assertLessEqual(len(printed.rstrip("\n")), C.LESSON_CAP)
                self.assertIn("Параметры — из реестра", printed)
                self.assertIn("ПОСТУСЛОВИЕ", printed)
                if ospec.tolerances:
                    self.assertIn("Допуски свидетеля", printed,
                                  "допуски объявлены реестром, но не доехали")

    def test_one_contract_carries_every_part_the_pointer_promises(self) -> None:
        """The index promises six things — all six are checked on
        `create_wall`.

        Each one is taken from its own registry field, so a miss here means
        the printout stopped reading the registry, not that the text
        changed.
        """
        printed = _printed(lambda: C.spec("create_wall"))
        ospec = spec.OPS["create_wall"]
        self.assertIn("create_wall(p0_mm, p1_mm, level, *", printed)  # form
        self.assertIn("mm 1..100000", printed)                       # boundaries
        # 🔴 THERE USED TO BE TWO LITERALS, AND THE SECOND WENT STALE THE
        # SAME DAY AS ITS THREE TWINS IN `test_invariants` (23.08.2026). It
        # claimed "slot `type` of form `ref` DOES NOT EXIST" — true exactly
        # for as long as there was nothing to create a wall type with.
        # `create_wall_type` appeared, the `wall_types` pool became
        # creatable, and the printout honestly showed `ref(wall_type)`.
        #
        # The same fact lived in two files — a named invariant of the house
        # — and here it cost a neighboring session a red. The literal was
        # replaced by OUTPUT FROM THE REGISTRY: the test still catches "the
        # printout stopped reading the registry," but no longer catches "the
        # registry changed." The law of WHEN `ref` must be present lives in
        # one place — `test_invariants`.
        def sel_form(pname: str) -> str:
            pspec = next(x for x in ospec.params if x.name == pname)
            forms = "|".join(k.value for k in pspec.ref_kinds)
            return ("sel: name|element_id|default"
                    + (f"|ref({forms})" if forms else ""))

        self.assertIn(sel_form("level"), printed)
        self.assertIn(sel_form("type"), printed)
        # And both forms are DIFFERENT — otherwise the output above would
        # have passed, printing the same thing for both slots, while the
        # question was about PER-SLOT-NESS.
        self.assertNotEqual(sel_form("level"), sel_form("type"))
        self.assertIn("пулу «wall_types»", printed)                  # grounding
        self.assertIn(ospec.post, printed)                           # postcondition
        for key, value in ospec.tolerances.items():                  # tolerances
            self.assertIn(f"{key} = {value:g}", printed)

    def test_the_index_groups_the_registry_the_way_the_prompt_does(self) -> None:
        """The table of contents and the tool description read from ONE
        single ledger.

        Should they diverge, the model would read one registry composition
        in the prompt and a different one in the receipt; there would be
        nothing to notice it with, because both sides would look fine.
        """
        printed = _printed(C.spec)
        for discipline, names in spec.ops_by_discipline(writes=True):
            self.assertIn(f"  {spec.DISCIPLINE_RU[discipline]}: "
                          + ", ".join(names), printed)
        for name in spec.OPS:
            self.assertIn(name, printed)
        self.assertLess(len(printed), 2 * len("\n".join(sorted(spec.OPS))))

    def test_an_unknown_name_is_a_typed_miss_that_keeps_the_program(self) -> None:
        """`NameError` teaches nothing — the sandbox law (L6), the same one
        applies here.

        Checked THROUGH THE SANDBOX, not by a direct call: the point of the
        requirement is that what surfaces is a TYPED failure carrying the
        AUTHOR'S LINE NUMBER, not a Python traceback. This is visible only
        at the real seam.

        🔴 THE LAW WAS REFINED ON 25.08.2026, AND WHAT WAS REFINED IS THE
        MECHANICS, NOT THE PROPERTY. Before that date the failure WAS
        RAISED, and a raise takes down the whole turn — measured by a run:
        the script builds three walls, asks for help with one wrong letter,
        gets `ok=False` and ZERO operations. A question TO THE DOCUMENTATION
        wiped out the turn's entire program.

        The argument against this is written in two tests below
        (`test_a_handle_and_the_op_function_are_accepted_as_the_name`) and in
        the docstring of `_op_spec_of`: "dropping a turn over a help query
        because of the ARGUMENT'S FORM is a bad trade." The same trade
        applies to the NAME, only worse: a typo is more likely than a wrong
        form.

        THE VALUABLE PROPERTY IS FULLY PRESERVED and is checked here: the
        code, the author's line, the nearest names, not a single frame of
        ours, no guessing at all. What is gone is exactly the turn's
        mortality. `spec` prints and returns `None` — nothing further down
        the script is a value that could become wrong.
        """
        result = sandbox.execute_author_script(
            'create_level(elev_mm=0, name="L1")\n'
            'spec("create_wal")\n', policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual([op["op"] for op in result.ops], ["create_level"],
                         "программа обязана пережить вопрос к справке")
        printed = result.stdout
        self.assertIn("KIR-P002", printed)           # op name outside the registry
        self.assertIn("create_wall", printed)        # nearest one named
        self.assertIn("строка 2", printed)           # the AUTHOR's line
        self.assertNotIn("Traceback", printed)
        self.assertNotIn("kir", printed)        # not a single frame of ours
        # The failure is machine-distinguishable, not only by prose.
        self.assertEqual([(с["call"], с["code"]) for с in result.course_reads
                          if с.get("refused")], [("spec", "KIR-P002")])

    def test_a_handle_and_the_op_function_are_accepted_as_the_name(self) -> None:
        """The argument's form must not drop the turn.

        A refusal here takes down the ENTIRE turn — the program assembled up
        to this line will not make it out. Dropping it because the model
        wrote `spec(create_wall)` instead of `spec("create_wall")` is a bad
        trade, and both forms are unambiguous: the function carries an
        `op_spec`, the handle carries its op's name.
        """
        result = sandbox.execute_author_script(
            'spec(create_door)\n'
            'w = create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), '
            'level={"by": "name", "value": "Этаж 1"}, height_mm=3000)\n'
            'spec(w)\n', policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertIn("КОНТРАКТ «create_door»", result.stdout)
        self.assertIn("КОНТРАКТ «create_wall»", result.stdout)
        self.assertEqual([op["op"] for op in result.ops], ["create_wall"])

    def test_every_contract_fits_the_channel_with_room_for_the_author(self) -> None:
        """There is one channel for help and for the model's own printout.

        The threshold is `LESSON_CAP` (the sandbox ceiling minus the
        reserve), the same one lessons use: help that eats up the channel
        takes away exactly what the channel was set up for.
        """
        for name in sorted(spec.OPS):
            with self.subTest(op=name):
                printed = _printed(lambda: C.spec(name))
                self.assertLessEqual(len(printed.rstrip("\n")), C.LESSON_CAP)
        self.assertLessEqual(len(_printed(C.spec).rstrip("\n")), C.LESSON_CAP)

    def test_a_contract_too_long_to_fit_is_cut_LOUDLY_and_names_the_rest(self):
        """THE ONE BRANCH THE REGISTRY DOES NOT REACH TODAY — and therefore
        checked by a run with a LOWERED ceiling, not by reasoning.

        The longest contract in the registry is 2 392 characters against a
        3 300 ceiling, so the trim stands by just in case; at ~120 ops it
        will stop being a standby case, and the cost of a silent trim is
        higher than usual here: tolerances and the postcondition sit AT THE
        END, and a contract without tolerances is indistinguishable from one
        with them.

        There are exactly three assertions: it fit within the ceiling, it
        stated how much was lost, it named the verbatim line that hands back
        the TAIL WITHOUT A SEAM.
        """
        ospec = spec.OPS["create_wall"]
        head, doc = C._spec_parts(ospec)
        cut = C._within_channel(
            head + doc,
            lambda keep: f"print(create_wall.__doc__"
                         f"[{max(0, keep - len(head))}:])", cap=800)
        self.assertLessEqual(len(cut), 800)
        self.assertIn("ОБРЕЗАНО", cut)
        self.assertIn("НЕ КОНТРАКТ", cut)
        offset = int(re.search(r"__doc__\[(\d+):\]", cut).group(1))
        kept = cut[:cut.index("\n[ОБРЕЗАНО")]
        # A SEAM WITH NO GAP AND NO OVERLAP: what is printed plus the
        # promised tail reproduce the original contract byte for byte.
        # Advice that misses by one character costs the model exactly the
        # round it was written to save.
        self.assertEqual(kept + doc[offset:], head + doc)

    def test_a_script_that_never_asks_gets_a_byte_identical_program(self) -> None:
        """LAW: WHAT IS ABSENT STAYS ABSENT.

        A new name in the script's namespace has no right to change A SINGLE
        BYTE of the program belonging to a script that never called it.
        Checked two independent ways, because each one catches its own
        thing:

        1. THE SAME SCRIPT THROUGH BARE `kir.dsl`, where the name `spec`
           does not exist at all — against prod policy. Both the program and
           the source's signature must match.
        2. A SCRIPT WITH `spec()` CALLS INSERTED — against the same one
           without them. The signatures here are DELIBERATELY DIFFERENT (the
           source is different), but the program must match byte for byte:
           help puts nothing into the program.
        """
        script = ('LVL = {"by": "name", "value": "Этаж 1"}\n'
                  'for i in range(3):\n'
                  '    create_wall(p0_mm=(i * 6000, 0), '
                  'p1_mm=(i * 6000 + 6000, 0), level=LVL, height_mm=3000)\n')
        with_course = sandbox.execute_author_script(script, policy=POLICY)
        bare = sandbox.execute_author_script(
            script, policy=sandbox.SandboxPolicy(dsl_module="kir.dsl"))
        for result in (with_course, bare):
            self.assertTrue(result.ok,
                            result.refusal and result.refusal.render())
        self.assertEqual(json.dumps(bare.ops, ensure_ascii=False,
                                    sort_keys=True),
                         json.dumps(with_course.ops, ensure_ascii=False,
                                    sort_keys=True))
        self.assertEqual(bare.author_digest, with_course.author_digest)

        asking = sandbox.execute_author_script(
            'spec()\n' + script + 'spec("create_wall")\n', policy=POLICY)
        self.assertTrue(asking.ok, asking.refusal and asking.refusal.render())
        self.assertEqual(asking.ops, with_course.ops)
        self.assertNotEqual(asking.author_digest, with_course.author_digest)
        self.assertIn("КОНТРАКТ «create_wall»", asking.stdout)


def _printed(call) -> str:
    """What the course function printed. The channel to the model is `stdout`, and that is what we measure."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        call()
    return buffer.getvalue()


# ═════════════════════════════════════════════════════════════════════════
# 5. THE TWO COURSES DO NOT OVERLAP; THE TEXT FITS IN THE CHANNEL
# ═════════════════════════════════════════════════════════════════════════

class TheCourseFitsAndDoesNotRepeatItself(unittest.TestCase):

    def test_every_lesson_fits_the_sandbox_stdout(self) -> None:
        """The lesson must leave room for the model's own printout: `stdout`
        is trimmed at `MAX_STDOUT_CHARS`, and a course that eats up the
        feedback takes away exactly what the channel was set up for."""
        for name in lessons.ORDER:
            with self.subTest(lesson=name):
                text = lessons.lesson(name)
                self.assertLessEqual(len(text), C.LESSON_CAP)
                self.assertLess(len(text), sandbox.MAX_STDOUT_CHARS)
                # WIDTH IS MEASURED ON PROSE, NOT ON CODE, and this is a rule
                # of the course itself, not a concession for the new lesson:
                # `lessons._reflow` reflows paragraphs and DOES NOT TOUCH
                # anything that starts with indentation ("tables, code, and
                # lists"), because wrapping inside a literal makes it
                # uncopyable. The "decompiles" lesson is entirely programs,
                # and a line break inside JSON would break both copying and
                # the "shown = checked" ratchet.
                prose = [line for line in text.splitlines()
                         if not line.startswith(" ")]
                self.assertLessEqual(max(len(line) for line in prose), 88)

    def test_every_recipe_fits_the_sandbox_stdout(self) -> None:
        for name in recipes.ORDER:
            with self.subTest(recipe=name):
                self.assertLess(len(recipes.RECIPES[name].source),
                                sandbox.MAX_STDOUT_CHARS - 400)

    def test_the_index_names_every_lesson_and_every_recipe(self) -> None:
        index = lessons.index()
        for name in lessons.ORDER:
            self.assertIn(name, index)
        self.assertEqual(sorted(lessons.ORDER), sorted(lessons.LESSONS))
        self.assertEqual(sorted(recipes.ORDER), sorted(recipes.RECIPES))

    def test_an_unknown_topic_refuses_with_the_list_of_topics(self) -> None:
        """A refusal without a list is a second round: the model will not
        guess the spelling, it will try a synonym."""
        with self.assertRaises(KeyError) as caught:
            lessons.lesson("группировка")
        for name in lessons.ORDER:
            self.assertIn(name, str(caught.exception))

    def test_the_two_courses_do_not_overlap(self) -> None:
        """`skill.py` is about the `program` field and macros; this course
        is about `program_py`. Overlap gets paid for twice and diverges at
        the first edit. Measured by LONG shared phrases, not by words."""
        theirs = skill.build_skill_text()
        for name in lessons.ORDER:
            mine = lessons.lesson(name)
            sentences = [s.strip() for s in mine.replace("\n", " ").split(". ")
                         if len(s.strip()) > 60]
            for sentence in sentences:
                self.assertNotIn(sentence, theirs,
                                 f"урок «{name}» повторяет skill.py")

    def test_the_course_never_claims_a_macro_exists_in_the_script(self) -> None:
        """The most expensive possible lie this course could tell: macros
        are unreachable in the sandbox, and advice to use them would cost a
        round."""
        for name in recipes.ORDER:
            source = recipes.RECIPES[name].source
            for macro in ("stack(", "series(", "grid_array("):
                self.assertNotIn(macro, source, f"{name}: {macro}")


# ═════════════════════════════════════════════════════════════════════════
# ADOPTION METRIC
# ═════════════════════════════════════════════════════════════════════════

class TheExamplesAreNotPromises(unittest.TestCase):
    """An example from `tools/design/examples/` — an artifact just like a
    recipe.

    Its directory neighbors (`tower_numpy.py`, `contour_shapely.py`) were
    written before the sandbox and CANNOT be submitted by the model: they
    use numpy and shapely. The two new ones must pass the full prod path
    whole, or else they lie about their genre.
    """

    # 🔴 THE EXAMPLES MOVED DURING THE SPLIT (28.08.2026): four `dirname`
    # hops from the course module used to lead into the host's tree, to
    # `tools/design/examples`. After 27.08 the same arithmetic gives `/opt`.
    # The examples now live at the package root.
    ROOT = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(C.__file__)))),
        "examples")

    def _example(self, name: str):
        path = os.path.join(self.ROOT, name)
        if not os.path.exists(path):
            self.skipTest(f"примера нет на этом боксе: {path}")
        import importlib.util
        spec_ = importlib.util.spec_from_file_location(f"_ex_{name[:-3]}", path)
        module = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(module)
        return module

    def test_the_method_example_goes_the_whole_way(self) -> None:
        module = self._example("method_group_and_repeat.py")
        result = sandbox.execute_author_script(module.SCRIPT, policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        got = C.measure(result.ops)
        self.assertGreater(got["определений групп"], 0)
        self.assertGreater(got["элементов внутри групп, %"], 0)
        program = _program(result)
        ground(compiler.plan_program(program, bulk=True).to_ops(),
               GROUND_SNAPSHOT)
        for version in spec.REVIT_VERSIONS:
            out = compiler.compile_program(program, revit_version=version,
                                           snapshot=GROUND_SNAPSHOT, bulk=True)
            self.assertTrue(getattr(out, "ok", False), version)

    def test_the_baseline_example_recomputes_the_line(self) -> None:
        module = self._example("method_baseline.py")
        rows = module.per_building()
        self.assertEqual(len(rows), len(corpus.BUILDINGS))
        measured = [row for _title, row in rows if "пропуск" not in row]
        if not measured:
            self.skipTest("корпуса нет на боксе")
        self.assertTrue(any(row["копий на определение"] > 1 for row in measured))


class TheAdoptionMetric(unittest.TestCase):

    def test_the_baseline_comes_from_the_corpus_not_from_taste(self) -> None:
        for key, (value, why) in C.BASELINE.items():
            self.assertGreater(value, 0, key)
            self.assertGreater(len(why), 20, key)

    def test_the_metric_separates_the_two_forms_of_the_same_result(self) -> None:
        """THE METRIC'S MAIN CLAIM: it must distinguish forms that produce
        the SAME result. If it could not, there would be nothing to
        measure."""
        senior = C.measure(_Run.of("санузел").ops)
        junior = C.measure(_Run.of("санузел-джуниор").ops)
        self.assertEqual(senior["элементов объявлено"],
                         junior["элементов объявлено"])
        self.assertEqual(senior["элементов внутри групп, %"], 100.0)
        self.assertEqual(junior["элементов внутри групп, %"], 0.0)
        self.assertGreater(senior["элементов на операцию"],
                           junior["элементов на операцию"])

    def test_derived_elements_are_never_guessed_into_the_count(self) -> None:
        """A curtain wall declares exactly its own ops: how many mullions
        Revit will spawn is not visible from the program, and a number set
        "by eye" would be exactly the silent lie the acceptance check was
        built to forbid."""
        got = C.measure(_Run.of("витраж").ops)
        self.assertEqual(got["элементов объявлено"],
                         got["операций написано"])

    def test_ops_without_elements_are_taken_from_acceptance(self) -> None:
        from kir.acceptance import _OPS_WITHOUT_ELEMENTS
        for name in _OPS_WITHOUT_ELEMENTS:
            self.assertEqual(C._element_count({"op": name}), 0, name)


# ═════════════════════════════════════════════════════════════════════════
# 6. TWO LESSONS ENTERED BY LIVE MEASUREMENTS ON 22.08.2026 — ARE MEASUREMENTS, NOT PROSE
# ═════════════════════════════════════════════════════════════════════════

#: An apartment made of two windowless rooms — the INPUT on which the whole
#: "verdict" lesson was captured. The literal sits here, not in the lesson,
#: precisely because the lesson prints the NUMBERS from this run, and they
#: have nowhere to diverge: the numbers are checked below.
_FLAT_WALLS = ((0, 0), (8000, 0), (8000, 6000), (0, 6000))


def _flat_text(text: str) -> str:
    """A lesson with MERGED whitespace: `lessons._reflow` wraps at a width
    of 78, and a quote that lands on a line break would otherwise be
    searched for by layout rather than by content — the guard would be
    catching reflow instead of meaning."""
    return " ".join(text.split())


def _windowless_flat(level) -> list[dict]:
    """Two rooms, one partition, one door, not a single window."""
    ops: list[dict] = []
    if level is None:
        level = {"by": "ref", "value": "L1"}
        ops.append({"op": "create_level", "id": "L1", "elev_mm": 0,
                    "name": "Этаж 1"})
    edges = list(zip(_FLAT_WALLS, _FLAT_WALLS[1:] + _FLAT_WALLS[:1]))
    edges.append(((4000, 0), (4000, 6000)))
    for index, (p0, p1) in enumerate(edges):
        ops.append({"op": "create_wall", "id": f"w{index}",
                    "p0_mm": list(p0), "p1_mm": list(p1),
                    "height_mm": 3000, "level": dict(level)})
    ops.append({"op": "create_door", "id": "d1", "offset_mm": 3000,
                "host": {"by": "ref", "value": "w4"}})
    ops.append({"op": "create_room", "id": "r1", "xy": [2000, 3000],
                "level": dict(level), "name": "Гостиная"})
    ops.append({"op": "create_room", "id": "r2", "xy": [6000, 3000],
                "level": dict(level), "name": "Кухня"})
    return ops


class VerdictLessonIsTheVerdictItself(unittest.TestCase):
    """THE "VERDICT" LESSON'S NUMBERS ARE RUN OUTPUT, NOT A RETELLING.

    The lesson names 9 rules out of 20 that fired, 11 unassessed by name,
    and HAB000 «model has no rooms» at a level taken from someone else's
    `element_id`. All of this is a property of the LIVE judge, and it
    changes along with it: a rule that receives an input drops off the
    silent list, while the stage profile takes down and hands back its own
    six. A retelling would silently diverge from the judge and would teach
    the model to read the verdict off yesterday's map.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from unittest import mock
        cls._env = mock.patch.dict(os.environ, {"KUKAI_CHECKER_V2": "1"})
        cls._env.start()
        cls.lesson = _flat_text(lessons.lesson("вердикт"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._env.stop()

    def _check(self, ops):
        from kir import design_check as verdict
        return verdict.check_ops(ops, building_id="контроль урока")

    def test_the_windowless_flat_blocks_on_the_rule_the_lesson_quotes(self):
        got = self._check(_windowless_flat(None))
        blocking = {v.rule_id for v in got.report.blocking}
        warnings = {v.rule_id for v in got.report.warnings}
        self.assertEqual(blocking, {"HAB030"}, got.report.blocking)
        self.assertEqual(warnings, {"HAB030"}, got.report.warnings)
        self.assertIn("Гостиная", got.report.blocking[0].msg)
        self.assertIn("Кухня", got.report.warnings[0].msg)
        for quoted in ("HAB030", "Гостиная", "Кухня",
                       "не имеет наружного окна"):
            self.assertIn(quoted, self.lesson)

    def test_the_coverage_numbers_printed_by_the_lesson_are_the_real_ones(self):
        got = self._check(_windowless_flat(None))
        coverage = got.report.coverage
        silent = [o.rule_id for o in coverage.outcomes
                  if o.status.value == "not_evaluated"]
        self.assertEqual(coverage.rules_evaluated, 9)
        self.assertEqual(len(coverage.outcomes), 20)
        self.assertEqual(len(silent), 11)
        self.assertIn("9 правил из 20", self.lesson)
        self.assertIn("НЕ ОЦЕНЕНО правил 11 из 20", self.lesson)
        # The lesson names EVERY silent rule BY NAME: silence that is not
        # mentioned at all reads as the rule's absence.
        for rule_id in silent:
            self.assertIn(rule_id, self.lesson, rule_id)
        self.assertEqual(sorted(got.rules_suspended),
                         ["HAB003", "HAB004", "HAB011", "HAB031", "HAB042",
                          "HAB050"])

    def test_a_level_the_program_did_not_declare_drops_everything(self):
        """🔴 THE LESSON'S MAIN FACT, AND IT IS A NEGATIVE CONTROL.

        A reference to a MODEL level on the PROGRAM path is resolved by
        nothing: the witness discards the walls and rooms, and the verdict
        degenerates into HAB000. The advice "declare the level in the same
        program" rests on exactly this, and if the path ever learns to read
        the model, the lesson must go red rather than remain confident
        advice about a boundary that has vanished.
        """
        # BOTH FORMS, NOT ONE: the lesson says "both by id and by name," and
        # a control covering only half the range would be an instrument
        # covering half of its own claim. BY NAME, the PROGRAM path searches
        # among the names of its OWN `create_level` calls — a match with the
        # model level's name gives it nothing.
        for foreign in ({"by": "element_id", "value": 355},
                        {"by": "name", "value": "Этаж 1"}):
            with self.subTest(level=foreign):
                got = self._check(_windowless_flat(foreign))
                self.assertEqual({v.rule_id for v in got.report.blocking},
                                 {"HAB000"})
                self.assertEqual(got.report.coverage.rules_evaluated, 0)
                notes = {note.code: note.detail for note in got.witness.notes}
                self.assertIn("wall_level_unresolved", notes)
                self.assertIn("room_level_unresolved", notes)
        for quoted in ("model has no rooms", "0 ПРАВИЛ ИЗ 20",
                       "уровень не разрешается по программе"):
            self.assertIn(quoted, self.lesson, quoted)


class TheEditLessonPromisesOnlyWhatTheWitnessDeclares(unittest.TestCase):
    """THE "EDIT" LESSON STANDS ON TWO CLAIMS ABOUT THE LIVE REGISTRY.

    First: the example compiles. Second, and this is why the lesson was
    written: `unwitnessed_axes` on `move_elements` is EMPTY (all three axes
    are declared), yet the postcondition says not one word about ROOMS —
    that is, an empty dict is honest and still says nothing about the plan.
    Both halves are governed today by a neighboring wave (the clauses about
    an opening's host and about dimensions landed on 22.08), so we ask the
    registry rather than remember it.
    """

    def setUp(self) -> None:
        self.lesson = _flat_text(lessons.lesson("правка"))

    def test_the_shown_call_compiles(self) -> None:
        result = sandbox.execute_author_script(
            'walls = [{"by": "element_id", "value": 294076},\n'
            '         {"by": "element_id", "value": 294077}]\n'
            'move_elements(targets=walls, delta_mm=[500, 0, 0])\n',
            policy=POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        out = compiler.compile_program(_program(result))
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("move_elements(targets=walls, delta_mm=[500, 0, 0])",
                      self.lesson)

    # THE NEGATIVE CONTROL FOR THIS SAME EXAMPLE — a string `element_id` and
    # the hint "drop the quotes" — lives IN `test_skill.py`, next to the
    # playbook that promises it: the guard must go red for whoever edits the
    # text.

    def test_the_axes_are_declared_and_the_plan_is_still_unwitnessed(self):
        from kir import serving
        self.assertEqual(serving._unwitnessed_axes(["move_elements"]), {})
        post = spec.OPS["move_elements"].post.lower()
        for absent in ("room", "area"):
            self.assertNotIn(absent, post,
                             "постусловие заговорило о плане — урок «правка» "
                             "обязан это сказать, а не молчать")
        self.assertIn("`unwitnessed_axes` при этом ПУСТ", self.lesson)


class ИндексБезКоторогоЧислоНоль(unittest.TestCase):
    """🔴 "There are no groups in the building" and "there is no group index
    on the machine" are different facts.

    `group_index`/`curtain_index` return `{}` for a missing file, and that
    answer is correct: the lesson must assemble even over an incomplete
    decompile. But `{}` travels into the lesson's numbers as ZERO, and the
    course's numbers are read by the MODEL — and read as measurements of
    real buildings. A recorded zero where there simply was no index teaches
    it that groups and curtain walls go unused.

    A pair of controls: one that can name the cause, and one that can stay
    silent.
    """

    def test_a_missing_building_is_named_not_zeroed(self) -> None:
        why = corpus.index_absent_reason("нет-такого-здания",
                                         "group.index.json")
        self.assertIsNotNone(why)
        self.assertIn("нет-такого-здания", why)
        self.assertIn("МАШИНЕ", why,
                      "причина обязана сказать, что это факт о машине")

    def test_the_two_causes_are_not_one_text(self) -> None:
        """"There is no building" and "the building exists, there is no
        index" call for a DIFFERENT move: the first is to bring a decompile,
        the second is to capture the stage."""
        import tempfile, pathlib as _pl
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            here = _pl.Path(tmp)
            (here / "есть_здание").mkdir()
            (here / "есть_здание" / "L0.jsonl").write_text("{}", encoding="utf-8")
            with mock.patch.object(corpus, "DECOMPILE_ROOT", here):
                gone = corpus.index_absent_reason("нет_здания", "group.index.json")
                no_idx = corpus.index_absent_reason("есть_здание",
                                                    "group.index.json")
            self.assertIsNotNone(gone)
            self.assertIsNotNone(no_idx)
            self.assertNotEqual(gone, no_idx,
                                "один текст на две причины повторил бы дефект")
            self.assertIn("group.index.json", no_idx,
                          "вторая причина обязана назвать НЕДОСТАЮЩИЙ файл")


class НулиУрокаНазываютСебяЗаполнителем(unittest.TestCase):
    """🔴 "Wall thickness is 0 mm" and "we did not measure the thicknesses"
    used to print identically.

    `_q` returns (0,0,0) for a sample smaller than four — the answer is
    correct, the lesson must assemble even over an incomplete set. But the
    zeros travel in the SAME UNITS as real quartiles, and the lesson's
    numbers are read by the MODEL and taken as measurements of real
    buildings: it will repeat a zero floor height.

    A pair of controls: one that can name it, and one that can stay silent.
    """

    def test_an_empty_sample_and_a_short_one_differ(self) -> None:
        from kir.course import building as B
        empty = B.sample_too_small_reason([], "толщина стены")
        short = B.sample_too_small_reason([100.0, 200.0], "толщина стены")
        self.assertIsNotNone(empty)
        self.assertIsNotNone(short)
        self.assertNotEqual(
            empty, short,
            "«источник не читался» и «замеров мало» требуют разного хода: "
            "первое чинят на диске, второе — набором корпуса")
        self.assertIn("не мерили", empty)
        self.assertIn("2", short, "короткая выборка обязана назвать СВОЙ размер")

    def test_a_full_sample_says_nothing(self) -> None:
        """A positive control: an instrument that always complains is not
        guarding anything."""
        from kir.course import building as B
        self.assertIsNone(
            B.sample_too_small_reason([1.0, 2.0, 3.0, 4.0], "что угодно"))

    def test_missing_width_runs_are_named(self) -> None:
        from kir.course import building as B
        absent = B.missing_width_runs()
        self.assertIsInstance(absent, tuple)
        for run in absent:
            self.assertIn(run, B.WIDTH_RUNS,
                          "названный пропущенным обязан быть из списка, "
                          "иначе прибор жалуется на чужое")


if __name__ == "__main__":
    unittest.main()
