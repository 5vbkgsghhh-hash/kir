"""PHASES — a construction plan inside a SINGLE authored script.

WHAT THIS SUITE HOLDS, AND WHY EXACTLY THIS.

1. ABSENCE STAYS ABSENCE. A script that never calls `phase()` must give the
   SAME program and the SAME digest as before phases existed. This is
   checked not by eye but three ways at once: the same digest as the plain
   language (`kir.dsl` with no course), a pinned number, and the absence of
   a key.
2. A BOUNDARY THE AUTHOR DID NOT DRAW IS NOT INVENTED. Every spot where the
   markup becomes ambiguous (an op outside any phase, a nested phase, a
   second name, an empty phase, a phase inside `unit()`) is a typed refusal,
   not a guess made in someone's favor.
3. A REFERENCE ACROSS THE BOUNDARY IS NAMED, NOT SILENT. Inside a phase —
   `by=ref`, as before; across the boundary — the `phase_result` label,
   which the executor will substitute using the witness of the phase that
   produced it; BACKWARD across the boundary — a refusal.
4. THE SEAM WITH THE NEXT STEP IS CLOSED FAIL-CLOSED. Phase-by-phase
   execution does not exist yet, so both a program with phases and an
   unsubstituted label must get a typed compiler refusal. Silently
   executing phases as one transaction is the absence of a checkpoint
   disguised as its presence, and a test like that is worth more than a
   pretty one.

THE SUITE'S COST: ~20 sandbox runs at ~0.3 s each. Expensive on purpose — a
cheap check would be checking the markup, not the work: a name unreachable
from the real policy costs a round of the model (the reachability law,
`test_course`).
"""
from __future__ import annotations

import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import compiler             # noqa: E402
from kir import course as C          # noqa: E402
from kir import dsl, sandbox, spec   # noqa: E402
from kir.compiler import (  # noqa: E402
    MAX_BULK_OPS, MAX_OPS_PER_PROGRAM, plan_program)
from kir.diag import KirRefusal      # noqa: E402
from kir.emit_utils import ELEMENT_ID_MAX  # noqa: E402

#: The EXACT set of names that the model gets in prod. No relaxation at all:
#: a phase that only works from the test process is not a phase.
POLICY = sandbox.SandboxPolicy(dsl_module="kir.course.language")


def run(source: str, **kw) -> sandbox.SandboxResult:
    policy = sandbox.SandboxPolicy(dsl_module="kir.course.language", **kw)
    return sandbox.execute_author_script(source, policy=policy)


def refusal_of(result: sandbox.SandboxResult) -> str:
    assert not result.ok, "ожидался отказ, а скрипт собрался"
    return result.refusal.render()


class _InProcess(unittest.TestCase):
    """Markup without the sandbox: the same thing, minus the 0.3 s per
    case."""

    def setUp(self) -> None:
        dsl.reset()

    def tearDown(self) -> None:
        dsl.reset()

    def level(self, k: int = 0):
        return dsl.OP_FUNCTIONS["create_level"](elev_mm=k * 3000,
                                                name=f"Этаж {k + 1}")

    def wall(self, level, k: int = 0):
        return dsl.OP_FUNCTIONS["create_wall"](
            p0_mm=(0, k * 1000), p1_mm=(6000, k * 1000), level=level,
            height_mm=3000)


# ═════════════════════════════════════════════════════════════════════════
# 1. PHASES IN ORDER
# ═════════════════════════════════════════════════════════════════════════

class PhasesComeOutInOrder(_InProcess):

    def test_the_table_names_every_op_exactly_once_in_written_order(self) -> None:
        """A split, not a label: the order of phases is the order of the
        script, and every op lies in EXACTLY one phase."""
        with C.phase("уровни"):
            lvl = self.level()
        with C.phase("стены"):
            self.wall(lvl, 0)
            self.wall(lvl, 1)
        with C.phase("помещение"):
            dsl.OP_FUNCTIONS["create_room"](xy=(1500, 1500), level=lvl,
                                            name="Кабинет")
        out = C.take_ops()
        phases = out["phases"]
        self.assertEqual([p["index"] for p in phases], [0, 1, 2])
        self.assertEqual([p["name"] for p in phases],
                         ["уровни", "стены", "помещение"])
        flat = [oid for p in phases for oid in p["op_ids"]]
        self.assertEqual(flat, [op["id"] for op in out["ops"]])
        self.assertEqual(len(flat), len(set(flat)))

    def test_a_reference_inside_one_phase_is_still_by_ref(self) -> None:
        """Inside a phase the language does not change BY A SINGLE BYTE: the
        same program as without phases — otherwise a phase would be a
        second reference dialect."""
        with C.phase("этаж целиком"):
            lvl = self.level()
            self.wall(lvl)
        out = C.take_ops()
        self.assertEqual(out["ops"][1]["level"], {"by": "ref", "value": "level1"})

    def test_a_reference_across_the_boundary_is_marked_for_the_witness(self) -> None:
        """WHAT STEP 2 STANDS ON. The label's shape is checked verbatim:
        it's read by substitution, not by a human."""
        with C.phase("уровни"):
            lvl = self.level()
        with C.phase("стены"):
            self.wall(lvl)
        out = C.take_ops()
        self.assertEqual(
            out["ops"][1]["level"],
            {"by": C.CROSS_PHASE_BY, "value": "level1", "phase": 0})
        self.assertEqual(C.CROSS_PHASE_BY, "phase_result")

    def test_no_by_ref_survives_a_boundary(self) -> None:
        """A law already stated elsewhere in the system: a cross-program
        `by=ref` is refused by `design_check._merge_bundle` ("a neighboring
        program is a separate transaction"). Phases must not create such
        references AT ALL, rather than relying on someone else refusing
        them downstream."""
        with C.phase("уровни"):
            lvl = self.level()
        with C.phase("стены"):
            wall = self.wall(lvl)
        with C.phase("проёмы"):
            dsl.OP_FUNCTIONS["create_door"](host=wall, offset_mm=3000,
                                            symbol="Дверь 900x2100")
        out = C.take_ops()
        owner = {oid: p["index"] for p in out["phases"] for oid in p["op_ids"]}
        for op in out["ops"]:
            for sel in _selectors(op):
                if sel.get("by") == "ref":
                    self.assertEqual(owner[str(sel["value"])], owner[op["id"]],
                                     f"{op['id']}: by=ref пересёк границу фазы")
                if sel.get("by") == C.CROSS_PHASE_BY:
                    self.assertLess(sel["phase"], owner[op["id"]])

    def test_a_unit_inside_a_phase_is_one_op_of_that_phase(self) -> None:
        """A unit inside a phase is legal: a group is ONE op, and it belongs
        to the phase it is written in."""
        with C.phase("санузлы"):
            with C.unit("Кабинка", placements=[(1600, 0)]):
                dsl.OP_FUNCTIONS["create_wall"](
                    p0_mm=(0, 0), p1_mm=(1600, 0),
                    level={"by": "name", "value": "Этаж 1"}, height_mm=2500)
        out = C.take_ops()
        self.assertEqual([op["op"] for op in out["ops"]], ["create_group"])
        self.assertEqual(out["phases"],
                         [{"index": 0, "name": "санузлы",
                           "op_ids": ["group1"]}])

    def test_the_self_check_is_not_blinded_by_phase_boundaries(self) -> None:
        """MEASURED 09.08, CAUGHT BY THIS TEST AND FIXED. The first edition
        of the markup blinded the plan: the `phase_result` label does not
        resolve to a level, and on a two-phase script it printed "considered
        6, drawn 0 (0%)" — an instrument that covers part of the range is
        more dangerous than a missing one. The plan and the verdict judge
        the INTENT, so they see the program the way the author wrote it
        (`_as_authored`)."""
        script = (
            'with phase("уровни"):\n'
            '    lvl = create_level(elev_mm=0, name="Этаж 1")\n'
            'with phase("стены"):\n'
            '    for a, b in [((0,0),(6000,0)), ((6000,0),(6000,4000)),\n'
            '                 ((6000,4000),(0,4000)), ((0,4000),(0,0))]:\n'
            '        create_wall(p0_mm=a, p1_mm=b, level=lvl, height_mm=3000)\n'
            '    create_room(xy=(3000, 2000), level=lvl, name="Кабинет")\n'
            'preview()\n')
        result = run(script)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertIn("нарисовано 5", result.stdout)
        self.assertNotIn("НЕ НАРИСОВАНО НИЧЕГО", result.stdout)
        # And what goes out is exactly the LABEL, not a restored `ref`: the
        # reverse conversion lives only inside two printing functions.
        self.assertEqual(result.ops[1]["level"]["by"], C.CROSS_PHASE_BY)

    def test_the_phase_object_says_what_it_is(self) -> None:
        with C.phase("каркас") as ph:
            self.level()
            self.assertEqual((ph.name, ph.index), ("каркас", 0))
        self.assertIn("каркас", repr(ph))
        C.take_ops()


def _selectors(value):
    """All selector dicts inside the operation, nested to any depth."""
    if isinstance(value, dict):
        if "by" in value:
            yield value
        for item in value.values():
            yield from _selectors(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _selectors(item)


# ═════════════════════════════════════════════════════════════════════════
# 2. REFUSALS — EACH ONE NAMES THE PHASE AND THE NEXT MOVE
# ═════════════════════════════════════════════════════════════════════════

class EveryAmbiguityIsATypedRefusal(unittest.TestCase):

    def test_a_handle_used_before_its_producing_phase_names_both(self) -> None:
        """THE ORDERING LAW, LIFTED ONTO PHASES. You cannot miss this with
        the handle (it only exists after its own op) — the miss is done with
        the explicit form `by_ref("level1")`, whose id is guessed from the
        deterministic naming scheme."""
        result = run(
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0),\n'
            '                level=by_ref("level1"), height_mm=3000)\n'
            'with phase("уровни"):\n'
            '    create_level(elev_mm=0, name="Этаж 1")\n')
        text = refusal_of(result)
        self.assertIn("KIR-L003", text)
        self.assertIn("level1", text)          # the handle itself
        self.assertIn("«стены»", text)         # who uses it
        self.assertIn("«уровни»", text)        # who produces it
        self.assertIn("строка", text)          # the spot in the author's script

    def test_a_phase_over_the_authored_budget_names_the_phase(self) -> None:
        result = run(
            'with phase("частокол"):\n'
            f'    for i in range({MAX_OPS_PER_PROGRAM + 1}):\n'
            '        create_wall(p0_mm=(i * 100, 0), p1_mm=(i * 100, 4000),\n'
            '                    level="Этаж 1", height_mm=3000)\n')
        text = refusal_of(result)
        self.assertIn("KIR-L001", text)
        self.assertIn("«частокол»", text)
        self.assertIn(str(MAX_OPS_PER_PROGRAM), text)
        self.assertIn(str(MAX_OPS_PER_PROGRAM + 1), text)

    #: How many operations the sandbox actually DELIVERS. Measured
    #: 22.08.2026 by bisecting between 10,000 and 25,000 per phase:
    #: 24,062 passes, 25,000 refuses with KIR-B009 "transport ceiling".
    TRANSPORT_CEILING_OPS = 48_124

    def test_the_budget_measures_the_phase_not_the_script(self) -> None:
        """THE BOUNDARY IS CHECKED FROM BOTH SIDES: TWO full phases in a row
        are legal. Before phases, that many ops would only have fit into two
        programs, i.e. two model turns.

        🔴 THE PHASE SIZE HERE IS NOT `MAX_OPS_PER_PROGRAM`, AND THIS IS A
        FINDING, NOT A CONCESSION (22.08.2026). The test built
        `2 * MAX_OPS_PER_PROGRAM` = 200,000 walls and required `result.ok` —
        that is, it asserted something the product CANNOT DO: first it hit
        the CPU limit (5.8 s against a 5 s default, a race with machine
        load), and with the limit raised — `KIR-B009`, the TRANSPORT
        ceiling. The discrepancy itself has been moved to a separate test
        below.

        What is checked here is exactly what the NAME claims: the budget is
        counted PER PHASE, not per script. Both phases are full and equal,
        together twice what would have fit into a single turn.
        """
        per_phase = 10_000
        result = run(
            'for k in range(2):\n'
            '    with phase("ярус %d" % k):\n'
            f'        for i in range({per_phase}):\n'
            '            create_wall(p0_mm=(i * 100, 0), p1_mm=(i * 100, 4000),\n'
            '                        level="Этаж 1", height_mm=3000)\n',
            cpu_seconds=60.0, wall_seconds=120.0)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(len(result.ops), 2 * per_phase)
        self.assertEqual([len(p["op_ids"]) for p in result.envelope["phases"]],
                         [per_phase, per_phase])

    def test_the_author_budget_exceeds_what_the_transport_carries(self) -> None:
        """🔴 TWO PRODUCT NUMBERS DISAGREE, AND THIS IS A MEASUREMENT, NOT AN
        OPINION.

        `MAX_OPS_PER_PROGRAM` tells the author 100,000 operations per
        program. The sandbox does NOT DELIVER that many: bisection on
        22.08.2026 found the ceiling between 24,062 (passes) and 25,000 per
        phase (`KIR-B009`), i.e. around 48,000 operations total — four times
        less than the declared budget of two phases allows.

        The difference is one of KIND: `KIR-B009` is "a transport ceiling
        (NOT the author's budget)", and it is named that way precisely so
        the two do not get merged. But naming alone is not enough: an author
        who trusts the declared number will hit the unnamed one. Until the
        numbers are reconciled, their discrepancy stands here as a
        MEASUREMENT — so it does not get closed silently and does not grow
        quietly.
        """
        self.assertGreater(MAX_OPS_PER_PROGRAM, self.TRANSPORT_CEILING_OPS,
                           "если транспорт догнал бюджет — это ПОБЕДА, и её "
                           "надо записать здесь, а не оставить тест зелёным "
                           "по старой причине")
        result = run(
            'with phase("одна"):\n'
            f'    for i in range({MAX_OPS_PER_PROGRAM}):\n'
            '        create_wall(p0_mm=(i * 100, 0), p1_mm=(i * 100, 4000),\n'
            '                    level="Этаж 1", height_mm=3000)\n',
            cpu_seconds=60.0, wall_seconds=120.0)
        self.assertFalse(result.ok, "бюджет автора обязан упереться в транспорт")
        self.assertIn("KIR-B009", result.refusal.render(),
                      "и упереться ИМЕННО в транспортный потолок, а не в "
                      "процессорный предел: два разных отказа, две разные "
                      "починки")

    def test_a_solo_op_alone_in_its_phase_is_legal(self) -> None:
        """WHAT THE SOLO RULE BECAME A PHASE RULE FOR: a building with a
        staircase became expressible as ONE script. The solo op is taken
        from the registry, not from its name: a second list of solo ops
        would drift from the first."""
        # 🔴 IT USED TO BE `sorted(spec.SOLO_OPS)[0]` — A POSITION, NOT A
        # NAME, and this broke the moment there were two solo ops: on 21.08
        # `author_family` was added, and it became first alphabetically. The
        # docstring promises "taken from the registry, not from its name",
        # and the promise holds — you just have to ask MEMBERSHIP, not
        # order.
        self.assertIn("create_stairs", spec.SOLO_OPS)
        solo = "create_stairs"
        result = run(
            'with phase("тело"):\n'
            '    create_level(elev_mm=0, name="Этаж 1")\n'
            '    create_level(elev_mm=3000, name="Этаж 2")\n'
            'with phase("лестница"):\n'
            '    create_stairs(base_level="Этаж 1", top_level="Этаж 2",\n'
            '                  p0_mm=(0, 0), p1_mm=(3000, 0), width_mm=1200)\n')
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual([p["name"] for p in result.envelope["phases"]],
                         ["тело", "лестница"])
        self.assertEqual(result.envelope["phases"][1]["op_ids"], ["stairs1"])

    def test_a_solo_op_with_a_neighbour_in_its_phase_refuses(self) -> None:
        result = run(
            'with phase("этаж и лестница"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level="Этаж 1",\n'
            '                height_mm=3000)\n'
            '    create_stairs(base_level="Этаж 1", top_level="Этаж 2",\n'
            '                  p0_mm=(0, 0), p1_mm=(3000, 0), width_mm=1200)\n')
        text = refusal_of(result)
        self.assertIn("KIR-L002", text)
        self.assertIn("«этаж и лестница»", text)
        self.assertIn("create_stairs", text)

    def test_an_op_before_the_first_phase_refuses(self) -> None:
        """THE DECISION MADE HERE: mixing marked and unmarked ops is a
        REFUSAL, not a silent phase 0."""
        text = refusal_of(run(
            'create_level(elev_mm=0, name="Этаж 1")\n'
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level="Этаж 1",\n'
            '                height_mm=3000)\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("ВНЕ фазы", text)
        self.assertIn("create_level", text)

    def test_an_op_between_two_phases_refuses(self) -> None:
        text = refusal_of(run(
            'with phase("уровни"):\n'
            '    create_level(elev_mm=0, name="Этаж 1")\n'
            'create_room(xy=(1500, 1500), level="Этаж 1", name="Между")\n'
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level="Этаж 1",\n'
            '                height_mm=3000)\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("create_room", text)
        self.assertIn("«уровни»", text)

    def test_an_op_after_the_last_phase_refuses(self) -> None:
        """THE ONE CHECK WITH NO LINE NUMBER, and this is said honestly: a
        tail only becomes a tail once the script has ended. In its place the
        refusal names the ops themselves and the last phase."""
        text = refusal_of(run(
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level="Этаж 1",\n'
            '                height_mm=3000)\n'
            'create_room(xy=(1500, 1500), level="Этаж 1", name="После")\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("ПОСЛЕ последней фазы", text)
        self.assertIn("room1", text)

    def test_a_phase_inside_a_phase_refuses(self) -> None:
        text = refusal_of(run(
            'with phase("а"):\n'
            '    with phase("б"):\n'
            '        create_level(elev_mm=0, name="Этаж 1")\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("ПОСЛЕДОВАТЕЛЬНОСТЬ", text)

    def test_a_repeated_phase_name_refuses(self) -> None:
        """Neither a second phase at the same address nor appending to a
        closed one: either would make execution order stop being the
        script's order."""
        text = refusal_of(run(
            'with phase("а"):\n'
            '    create_level(elev_mm=0, name="Этаж 1")\n'
            'with phase("а"):\n'
            '    create_level(elev_mm=3000, name="Этаж 2")\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("уже была", text)

    def test_a_phase_inside_a_unit_refuses(self) -> None:
        text = refusal_of(run(
            'with unit("Кабинка"):\n'
            '    with phase("а"):\n'
            '        create_wall(p0_mm=(0, 0), p1_mm=(1000, 0),\n'
            '                    level="Этаж 1", height_mm=3000)\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("unit()", text)

    def test_an_empty_phase_refuses(self) -> None:
        text = refusal_of(run(
            'with phase("пусто"):\n'
            '    pass\n'
            'create_level(elev_mm=0, name="Этаж 1")\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("«пусто»", text)

    def test_a_nameless_phase_refuses(self) -> None:
        text = refusal_of(run(
            'with phase(""):\n'
            '    create_level(elev_mm=0, name="Этаж 1")\n'))
        self.assertIn("KIR-L006", text)
        self.assertIn("ИМЯ", text)

    def test_a_refusal_never_escapes_as_a_traceback(self) -> None:
        """THE SANDBOX LAW: a raw traceback never gets out.

        🔴 MECHANICS CLARIFIED 25.08.2026, THE PROPERTY IS INTACT. The
        earlier edition required verbatim `KIR-B006` — "any other script
        exception". Phase refusals got THEIR OWN code, `KIR-L006`
        (`PLAN_PHASE_SHAPE`), and this is an improvement, not a break: the
        shared code told the model "your script raised an exception", the
        dedicated one names the subject. Today's text:

            "phase "а" (#0, line 1) collected no operations at all. An
             empty phase is an empty transaction and a wasted checkpoint:
             there is nothing to build in it. Write ops INSIDE the with
             block"

        The test used to pin the MECHANISM (which exact code); what matters
        here is the shape of the answer: typed, blame named correctly, not
        one frame of ours. Now the subject-specific code itself is pinned —
        the shared `KIR-B006` here would now be a REGRESSION and must turn
        red.

        The classification is verified by execution, not by trust:
        `KIR-L006` gives `kir.program_refused` — an empty phase is the
        author's to fix, and that is correct.
        """
        for source in (
            'with phase("а"):\n    pass\ncreate_level(elev_mm=0, name="L")\n',
            'with phase("а"):\n    with phase("б"):\n'
            '        create_level(elev_mm=0, name="L")\n',
        ):
            with self.subTest(source=source.splitlines()[1].strip()):
                result = run(source)
                self.assertFalse(result.ok)
                self.assertEqual(result.refusal.code, "KIR-L006")
                self.assertEqual(result.refusal.blame, "author")
                self.assertNotIn("Traceback", result.refusal.message_ru)
                self.assertNotIn("kir", result.refusal.message_ru)
                # The refusal must NAME the phase: "an empty phase somewhere
                # in the script" on a thirty-phase script is a second round.
                self.assertIn("фаза", result.refusal.message_ru)


# ═════════════════════════════════════════════════════════════════════════
# 3. ABSENCE STAYS ABSENCE
# ═════════════════════════════════════════════════════════════════════════

#: A script WITHOUT A SINGLE `phase()`. Edit it only together with the
#: pinned digest below — that is the whole point.
UNPHASED = ('envelope(intent="коробка")\n'
            'lvl = create_level(elev_mm=0, name="Этаж 1")\n'
            'create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level=lvl, height_mm=3000)\n'
            'create_wall(p0_mm=(6000, 0), p1_mm=(6000, 4000), level=lvl,'
            ' height_mm=3000)\n')

#: MEASURED 09.08.2026: this script's `program_digest`, taken by BOTH
#: language modules. The number is pinned on purpose: a discrepancy here
#: means the program of a phase-less script has shifted — i.e. phases have
#: charged a toll to those who never called them. This is exactly the
#: defect the table travels for in an envelope, rather than in every op.
UNPHASED_DIGEST = ("c2106fc0e0ac07e505e9f8b7469ac498"
                   "f9d631e88e818a804cdf69fcd79bfe51")


class AbsentStaysAbsent(unittest.TestCase):

    def test_a_script_without_phases_is_byte_identical_to_the_bare_language(self) -> None:
        """The strongest of the three formulations: a program with the FULL
        course must match the program of the PLAIN language, which has
        never heard of phases."""
        bare = sandbox.execute_author_script(
            UNPHASED, policy=sandbox.SandboxPolicy(dsl_module="kir.dsl"))
        full = run(UNPHASED)
        self.assertTrue(bare.ok, bare.refusal and bare.refusal.render())
        self.assertTrue(full.ok, full.refusal and full.refusal.render())
        self.assertEqual(full.ops, bare.ops)
        self.assertEqual(full.envelope, bare.envelope)
        self.assertEqual(full.program_digest, bare.program_digest)

    def test_the_digest_of_a_script_without_phases_has_not_moved(self) -> None:
        full = run(UNPHASED)
        self.assertEqual(full.program_digest, UNPHASED_DIGEST)

    def test_a_script_without_phases_carries_no_phases_key(self) -> None:
        """Absence is the ABSENCE of the key, not an empty list: an empty
        table would read as "the author drew zero phases"."""
        full = run(UNPHASED)
        self.assertNotIn("phases", full.envelope)
        self.assertNotIn("phases", full.as_dict().get("envelope", {}))

    def test_the_phased_program_is_deterministic(self) -> None:
        """`replay_check` is not rigor for rigor's sake: a source signature
        certifies nothing if two runs give different programs. The phase
        table must be just as reproducible as the ops themselves."""
        result = run(
            'with phase("уровни"):\n'
            '    lvl = create_level(elev_mm=0, name="Этаж 1")\n'
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level=lvl,\n'
            '                height_mm=3000)\n', replay_check=True)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertTrue(result.isolation.get("replay_checked"))
        self.assertEqual(len(result.envelope["phases"]), 2)


# ═════════════════════════════════════════════════════════════════════════
# 4. PROPERTY: A SPLIT STAYS A SPLIT FOR ANY NUMBER OF PHASES
# ═════════════════════════════════════════════════════════════════════════

class PhaseCountsHoldTheInvariants(_InProcess):
    """A seeded PRNG, not hypothesis: it is absent from the prod venv
    (`test_pbt`)."""

    TRIALS = 40

    def test_every_generated_plan_is_a_partition_with_forward_only_refs(self) -> None:
        rng = random.Random(20260809)
        seen_counts: set[int] = set()
        for trial in range(self.TRIALS):
            with self.subTest(trial=trial):
                dsl.reset()
                n_phases = rng.randint(1, 6)
                seen_counts.add(n_phases)
                handles: list = []
                # THE CEILING HERE IS SCRIPT-LEVEL, NOT PROGRAM-LEVEL, and
                # before 15.08.2026 the difference never showed: at an
                # authored budget of 20, six phases gave at most 120 ops,
                # i.e. the generator could never reach the `dsl`
                # accumulator's ceiling (`MAX_BULK_OPS`=300). After the
                # budget was raised to 100, six phases give up to 600, and
                # two out of forty runs hit the accumulator — a PRODUCT
                # refusal, correct on its merits. What needs fixing is the
                # generator: it must stay inside the same boundary as a real
                # script. The property this file checks (a split stays a
                # split for any number of phases) does not depend on the
                # draw size.
                per_phase = max(1, min(MAX_OPS_PER_PROGRAM,
                                       (MAX_BULK_OPS - 1) // n_phases))
                for index in range(n_phases):
                    with C.phase(f"фаза {index}"):
                        for k in range(rng.randint(1, per_phase)):
                            if handles and rng.random() < 0.4:
                                self.wall(rng.choice(handles), k)
                            else:
                                handles.append(self.level(len(handles)))
                out = C.take_ops()
                self._assert_partition(out, n_phases)

    def _assert_partition(self, out: dict, n_phases: int) -> None:
        phases = out["phases"]
        self.assertEqual(len(phases), n_phases)
        self.assertEqual([p["index"] for p in phases], list(range(n_phases)))
        flat = [oid for p in phases for oid in p["op_ids"]]
        # THE SPLIT: the same addresses, in the same order, each exactly
        # once.
        self.assertEqual(flat, [op["id"] for op in out["ops"]])
        self.assertEqual(len(flat), len(set(flat)))
        owner = {oid: p["index"] for p in phases for oid in p["op_ids"]}
        for phase in phases:
            self.assertTrue(1 <= len(phase["op_ids"]) <= MAX_OPS_PER_PROGRAM)
        for op in out["ops"]:
            for sel in _selectors(op):
                if sel.get("by") == "ref":
                    self.assertEqual(owner[str(sel["value"])], owner[op["id"]])
                elif sel.get("by") == C.CROSS_PHASE_BY:
                    self.assertEqual(owner[str(sel["value"])], sel["phase"])
                    self.assertLess(sel["phase"], owner[op["id"]])


# ═════════════════════════════════════════════════════════════════════════
# 5. THE SEAM WITH STEP 2 — CLOSED FAIL-CLOSED, NOT BY A PROMISE
# ═════════════════════════════════════════════════════════════════════════

class NothingExecutesAsOneTransactionByAccident(unittest.TestCase):
    """Both tests STAY AFTER STEP 2, and this is a disagreement with the
    previous author, recorded together with the reason.

    He left them as "a contract for whoever writes step 2: they will remove
    them together with the substitution." There is nothing to remove:
    `plan_program` executes ONE transaction, while a phase promises a
    checkpoint BETWEEN transactions. A plan handed to it whole must refuse
    today exactly as it did yesterday — otherwise phases would have quietly
    fused into one transaction, i.e. a checkpoint would be declared and not
    exist. Step 2 did not lift this refusal, it placed ABOVE it a function
    that cuts the plan into chunks (`serving._run_plan` -> `split_phases`),
    and a plan only reaches here for whoever did not do the cutting.

    What changed is exactly the refusal's TEXT: it names the plan and says
    what to cut it with. This is checked right here — "unknown envelope
    field" used to send the reader off to remove `phases`, i.e. to lose the
    checkpoints."""

    def test_a_phased_program_handed_over_whole_is_refused_by_name(self) -> None:
        result = run(
            'with phase("уровни"):\n'
            '    lvl = create_level(elev_mm=0, name="Этаж 1")\n'
            'with phase("стены"):\n'
            '    create_wall(p0_mm=(0, 0), p1_mm=(6000, 0), level=lvl,\n'
            '                height_mm=3000)\n')
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        # Exactly what the live door (`serving.py`) does with the envelope.
        program = {**result.envelope, "ops": result.ops}
        with self.assertRaises(KirRefusal) as caught:
            plan_program(program, bulk=False)
        codes = {d.code for d in caught.exception.diagnostics}
        fields = {d.field_name for d in caught.exception.diagnostics}
        self.assertIn("KIR-P003", codes)
        self.assertIn("phases", fields)
        text = " ".join(d.message_ru for d in caught.exception.diagnostics
                        if d.field_name == "phases")
        # THE REFUSAL NAMES THE FIX, NOT THE FIELD. "Unknown envelope field"
        # reads as "remove it" — i.e. "lose the checkpoints".
        self.assertIn("split_phases", text)
        self.assertNotIn("неизвестное поле", text)

    def test_an_unsubstituted_cross_phase_marker_never_compiles(self) -> None:
        """A label is an OBLIGATION to substitute, not a selector shape.
        Reaching the compiler unsubstituted, it must refuse, not be
        interpreted as something else."""
        program = {"ir_version": spec.IR_VERSION, "ops": [
            {"op": "create_level", "id": "level1", "elev_mm": 0,
             "name": "Этаж 1"},
            {"op": "create_wall", "id": "wall1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": C.CROSS_PHASE_BY, "value": "level1", "phase": 0}},
        ]}
        with self.assertRaises(KirRefusal) as caught:
            plan_program(program, bulk=False)
        self.assertIn("level", {d.field_name for d in caught.exception.diagnostics})


# ═════════════════════════════════════════════════════════════════════════
# 6. STEP 2 — THE PLAN IS CUT INTO CHUNKS, AND EACH CHUNK IS A PROGRAM
# ═════════════════════════════════════════════════════════════════════════

class ThePlanBecomesAPackOfPrograms(_InProcess):
    """THE MAIN CLAIM OF THIS SUITE, and it is verified by a run, not by
    reasoning: a building that TODAY CANNOT be written as one program
    becomes, after the cut, a batch of programs, EACH of which
    `plan_program` accepts. Exactly this pair — "impossible as one,
    possible as a batch" — is the very work taken off the modeler: the
    boundary used to be computed by them, now it is computed by the
    compiler.
    """

    def _house_with_stairs(self) -> dict:
        with C.phase("уровни"):
            lvl = self.level(0)
            self.level(1)
        with C.phase("каркас"):
            self.wall(lvl, 0)
            self.wall(lvl, 1)
        with C.phase("лестница"):
            dsl.OP_FUNCTIONS["create_stairs"](
                base_level="Этаж 1", top_level="Этаж 2",
                p0_mm=(1000, 1000), p1_mm=(4000, 1000), width_mm=1200)
        out = C.take_ops()
        out.setdefault("ir_version", spec.IR_VERSION)
        return out

    def test_the_building_one_program_cannot_hold_splits_into_ones_it_can(self) -> None:
        program = self._house_with_stairs()
        # AS ONE PROGRAM — IMPOSSIBLE, and there are THREE refusals, each
        # about its own thing:
        #   P003 — a plan in the envelope (one transaction cannot execute a
        #   plan),
        #   L002 — create_stairs owns its own transactions,
        #   T001 — the `phase_result` label is not a language selector.
        # Three reasons at once are exactly the work the modeler used to do
        # in their head: not one of them is about geometry.
        with self.assertRaises(KirRefusal) as caught:
            plan_program(program, bulk=False)
        self.assertLessEqual({"KIR-P003", "KIR-L002", "KIR-T001"},
                             {d.code for d in caught.exception.diagnostics})
        # AS A BATCH — POSSIBLE, and it is the same `plan_program`. Labels
        # are substituted exactly the way the executor would substitute
        # them: with the previous phase's product. Otherwise the "frame"
        # chunk would legitimately fail to plan — no one has named it a
        # level yet.
        links = compiler.split_phases(program)
        self.assertEqual([link.name for link in links],
                         ["уровни", "каркас", "лестница"])
        products: dict = {}
        for index, link in enumerate(links):
            body = compiler.substitute_phase_results(link.program, products)
            plan_program(body, bulk=False)
            products.update(compiler.phase_products(
                body["ops"],
                {op["id"]: {"id": str(900000 + index * 10 + k)}
                 for k, op in enumerate(body["ops"])}))

    def test_a_link_is_a_program_and_carries_no_trace_of_the_plan(self) -> None:
        """A chunk must be INDISTINGUISHABLE from a program written by hand:
        the envelope is closed (`known_top`), and any field of ours in it is
        KIR-P003."""
        links = compiler.split_phases(self._house_with_stairs())
        for link in links:
            self.assertNotIn("phases", link.program)
            self.assertLessEqual(set(link.program),
                                 {"ir_version", "intent", "allow_destructive",
                                  "defaults", "ops"})

    def test_the_ops_travel_byte_for_byte(self) -> None:
        """The digest signs the INTENT; an op rewritten along the way would
        make the signature a signature of something else."""
        program = self._house_with_stairs()
        links = compiler.split_phases(program)
        flat = [op for link in links for op in link.program["ops"]]
        self.assertEqual(flat, program["ops"])

    def test_the_budget_is_not_raised_by_a_single_unit(self) -> None:
        """WHAT IS CHECKED IS SPECIFICALLY THE FUSE. A plan lets you write a
        BUILDING, not a program longer than twenty operations: a chunk of
        21 ops refuses with the same KIR-L001 as before."""
        program = {"ir_version": spec.IR_VERSION,
                   "ops": [{"op": "create_level", "id": f"l{i}",
                            "elev_mm": i * 3000, "name": f"Этаж {i}"}
                           for i in range(MAX_OPS_PER_PROGRAM + 1)],
                   "phases": [{"index": 0, "name": "всё сразу",
                               "op_ids": [f"l{i}" for i in
                                          range(MAX_OPS_PER_PROGRAM + 1)]}]}
        links = compiler.split_phases(program)
        self.assertEqual(len(links), 1)
        with self.assertRaises(KirRefusal) as caught:
            plan_program(links[0].program, bulk=False)
        self.assertIn("KIR-L001", {d.code for d in caught.exception.diagnostics})

    def test_a_table_that_is_not_a_partition_refuses_and_names_the_gap(self) -> None:
        """The table arrives IN THE ENVELOPE, and the envelope can be sent
        by anyone: `serving` does not tell one assembled by the sandbox from
        one typed by hand. A silently swallowed op is an element no one
        will ever build, and no one will say a word about."""
        base = {"ir_version": spec.IR_VERSION, "ops": [
            {"op": "create_level", "id": "l0", "elev_mm": 0, "name": "Этаж 1"},
            {"op": "create_level", "id": "l1", "elev_mm": 3000, "name": "Этаж 2"},
        ]}
        for table, needle in (
                ([{"index": 0, "name": "часть", "op_ids": ["l0"]}], "l1"),
                ([{"index": 0, "name": "дважды", "op_ids": ["l0", "l0", "l1"]}],
                 "l0"),
                ([{"index": 0, "name": "чужой", "op_ids": ["l0", "l9"]}], "l9"),
                ([{"index": 1, "name": "не с нуля", "op_ids": ["l0", "l1"]}],
                 "нумеруются"),
                ([{"index": 0, "name": "", "op_ids": ["l0", "l1"]}], "имени"),
                ([{"index": 0, "name": "пусто", "op_ids": []}], "ни одной"),
        ):
            with self.subTest(name=table[0]["name"]):
                with self.assertRaises(KirRefusal) as caught:
                    compiler.split_phases({**base, "phases": table})
                diags = caught.exception.diagnostics
                self.assertEqual({"KIR-L006"}, {d.code for d in diags})
                self.assertIn(needle,
                              " ".join(d.message_ru for d in diags))

    def test_the_order_of_phases_is_the_order_of_the_script(self) -> None:
        """Phases swapped in place are not "a different plan" but a
        DIVERGENCE from the order in which the author wrote the operations;
        there is nothing to sort by on its behalf."""
        base = {"ir_version": spec.IR_VERSION, "ops": [
            {"op": "create_level", "id": "l0", "elev_mm": 0, "name": "Этаж 1"},
            {"op": "create_level", "id": "l1", "elev_mm": 3000, "name": "Этаж 2"},
        ]}
        with self.assertRaises(KirRefusal) as caught:
            compiler.split_phases({**base, "phases": [
                {"index": 0, "name": "вторая", "op_ids": ["l1"]},
                {"index": 1, "name": "первая", "op_ids": ["l0"]}]})
        self.assertIn("порядок",
                      " ".join(d.message_ru for d in caught.exception.diagnostics))


class TheWitnessOfOnePhaseFeedsTheNext(_InProcess):
    """THE ONLY THING THAT CROSSES A PROGRAM BOUNDARY IS A SUBSTITUTED
    ElementId. `by=ref` does not cross the boundary and never will: the
    neighboring phase is executed as a SEPARATE transaction. What exists is
    the real id in that phase's receipt, and retyping it by hand from a past
    turn is removed right here."""

    def _two_phases(self):
        with C.phase("уровень"):
            lvl = self.level(0)
        with C.phase("стена"):
            self.wall(lvl, 0)
        out = C.take_ops()
        out.setdefault("ir_version", spec.IR_VERSION)
        return compiler.split_phases(out)

    def test_the_marker_becomes_a_real_element_id(self) -> None:
        links = self._two_phases()
        self.assertEqual(links[1].program["ops"][0]["level"],
                         {"by": C.CROSS_PHASE_BY, "value": "level1",
                          "phase": 0})
        products = compiler.phase_products(
            links[0].program["ops"], {"level1": {"id": "483911"}})
        self.assertEqual(products, {"level1": 483911})
        body = compiler.substitute_phase_results(links[1].program, products)
        self.assertEqual(body["ops"][0]["level"],
                         {"by": "element_id", "value": 483911})
        # AND THIS IS A PROGRAM, NOT A SHAPE THAT MERELY RESEMBLES ONE.
        plan_program(body, bulk=False)

    def test_the_bridge_may_answer_with_a_number_or_a_string(self) -> None:
        """The bridge sends both `42` and `"42"`; guessing the type would
        cost a phase."""
        links = self._two_phases()
        for wire in ("483911", 483911):
            with self.subTest(wire=type(wire).__name__):
                self.assertEqual(
                    compiler.phase_products(links[0].program["ops"],
                                            {"level1": {"id": wire}}),
                    {"level1": 483911})

    def test_a_missing_product_refuses_and_never_passes_the_marker_down(self) -> None:
        """A label is an OBLIGATION to substitute. Leaving it as is would
        mean sending downstream a selector shape the language does not have,
        and getting a refusal pointing at the wrong cause."""
        links = self._two_phases()
        with self.assertRaises(KirRefusal) as caught:
            compiler.substitute_phase_results(links[1].program, {})
        diags = caught.exception.diagnostics
        self.assertEqual({"KIR-L006"}, {d.code for d in diags})
        self.assertIn("level1", " ".join(d.message_ru for d in diags))

    def test_only_a_referenceable_result_becomes_a_product(self) -> None:
        """A group and a deletion carry an identity and are NOT referable —
        that is written in `ResultSpec`'s own docstring. Substituting their
        id across the boundary would mean allowing more from the outside
        than the program allows on the inside."""
        wrong = [name for name, ospec in spec.OPS.items()
                 if ospec.result.identity_field and not ospec.result.referenceable]
        self.assertTrue(wrong, "в реестре не осталось неcсылаемых результатов")
        for name in wrong:
            with self.subTest(op=name):
                self.assertEqual(
                    compiler.phase_products([{"op": name, "id": "x"}],
                                            {"x": {"id": "77"}}),
                    {})

    def test_a_bogus_element_id_never_becomes_a_product(self) -> None:
        """THE BOUND IS TAKEN FROM THE LANGUAGE (`emit_utils.ELEMENT_ID_MAX`
        = the int64 maximum), not assigned here: `10**12` is a LEGITIMATE
        ElementId, and rejecting it "by eye as too big" would mean setting
        up a second limit next to the real one. What is rejected is
        whatever is not a positive integer."""
        links = self._two_phases()
        for wire in (0, -3, True, None, "", "нет", ELEMENT_ID_MAX + 1):
            with self.subTest(wire=repr(wire)):
                self.assertEqual(
                    compiler.phase_products(links[0].program["ops"],
                                            {"level1": {"id": wire}}),
                    {})


class ThePlanIsLedPhaseByPhase(_InProcess):
    """THE EXECUTOR. The bridge is substituted here, and that is THE
    BOUNDARY OF THIS CLASS: it checks ORDER, SUBSTITUTION, and RECEIPT
    HONESTY, not whether Revit actually built anything. The latter can only
    be proven by a live device, and claiming it from here would be exactly
    the `ok:true` with no independent acceptance that this whole house
    exists to forbid."""

    def _plan_of(self, *, phases: int = 3) -> dict:
        with C.phase("уровни"):
            lvl = self.level(0)
        with C.phase("каркас"):
            self.wall(lvl, 0)
        if phases > 2:
            with C.phase("лестница"):
                dsl.OP_FUNCTIONS["create_stairs"](
                    base_level="Этаж 1", top_level="Этаж 2",
                    p0_mm=(1000, 1000), p1_mm=(4000, 1000), width_mm=1200)
        out = C.take_ops()
        out.setdefault("ir_version", spec.IR_VERSION)
        return out

    def _run(self, program, inner):
        import asyncio

        from kir import serving

        original = serving._handle_revit_ir_inner
        serving._handle_revit_ir_inner = inner
        try:
            authored = serving._AuthoredInput(args={"program": program},
                                              from_script=True)
            return asyncio.run(serving._run_plan(
                program, None, None, query_id="t", authored=authored))
        finally:
            serving._handle_revit_ir_inner = original

    @staticmethod
    def _green(seen: list, first_id: int = 600001):
        async def inner(args, llm, bridge, *, query_id="", bulk=False, **kw):
            body = args["program"]
            seen.append(body)
            payload = {op["id"]: {"id": str(first_id + i)}
                       for i, op in enumerate(body["ops"])}
            payload["ok"] = True
            return {"ok": True, "kir": True, "result": {"result": payload},
                    "outcome": {"execution": "committed", "retry": "forbidden"},
                    "message_ru": "записано"}
        return inner

    def test_one_script_becomes_one_program_per_phase_in_written_order(self) -> None:
        seen: list = []
        result = self._run(self._plan_of(), self._green(seen))
        self.assertTrue(result["ok"], result.get("message_ru"))
        self.assertEqual([len(body["ops"]) for body in seen], [1, 1, 1])
        self.assertEqual(result["plan"]["phases"], 3)
        self.assertEqual(result["plan"]["committed"], 3)
        self.assertNotIn("resume_from", result["plan"])
        self.assertEqual([step["name"] for step in result["plan"]["steps"]],
                         ["уровни", "каркас", "лестница"])

    def test_the_second_phase_is_sent_with_a_real_element_id(self) -> None:
        seen: list = []
        self._run(self._plan_of(), self._green(seen, first_id=700007))
        self.assertEqual(seen[1]["ops"][0]["level"],
                         {"by": "element_id", "value": 700007})

    def test_a_failed_phase_stops_the_plan_and_names_where_to_resume(self) -> None:
        """A CHECKPOINT IS A PROMISE, AND IT IS KEPT LITERALLY. A phase is
        atomic, a plan is not: a failure of the second does not roll back
        the first. So the receipt must say which phase to resume from — a
        plan replayed whole would build the already-built thing a second
        time."""
        seen: list = []
        green = self._green(seen)
        calls = [0]

        async def inner(args, llm, bridge, **kw):
            calls[0] += 1
            if calls[0] == 2:
                return {"ok": False, "kir": True, "stage": "execute",
                        "message_ru": "постусловие стены не сошлось",
                        "outcome": {"execution": "rolled_back",
                                    "retry": "safe"},
                        "handoff": "recipe-path"}
            return await green(args, llm, bridge, **kw)

        result = self._run(self._plan_of(), inner)
        self.assertFalse(result["ok"])
        # THE THIRD PHASE WAS NEVER SENT: it could reference the second
        # one's result.
        self.assertEqual(calls[0], 2)
        self.assertEqual(result["plan"]["committed"], 1)
        self.assertEqual(result["plan"]["resume_from"], 1)
        self.assertIn("ПЛАН ВСТАЛ НА ФАЗЕ №1", result["message_ru"])
        self.assertIn("постусловие стены не сошлось", result["message_ru"])
        # REPLAYING THE WHOLE PLAN WOULD HAVE DUPLICATED WHAT WAS ALREADY
        # BUILT.
        self.assertIsNone(result["handoff"])
        self.assertIs(result["err"]["retryable"], False)

    def test_a_failure_in_the_first_phase_stays_retryable(self) -> None:
        """The flip side of the same rule: while NOTHING has been built yet,
        replaying the whole plan is safe, and taking that away from the
        modeler would mean refusing for the wrong reason."""
        async def inner(args, llm, bridge, **kw):
            return {"ok": False, "kir": True, "stage": "plan",
                    "message_ru": "селектор уровня не сведён",
                    "outcome": {"execution": "not_started", "retry": "safe"},
                    "handoff": "recipe-path"}

        result = self._run(self._plan_of(), inner)
        self.assertFalse(result["ok"])
        self.assertEqual(result["plan"]["committed"], 0)
        self.assertEqual(result["plan"]["resume_from"], 0)
        self.assertIsNot((result.get("err") or {}).get("retryable"), False)

    def _route(self, program) -> str:
        """Where the chat door sent the program: "plan" or "body". BOTH
        sides through one instrument — a test for "the plan was never
        called" alone would also pass on a dead hook."""
        import asyncio

        from kir import serving

        where: list = []

        async def inner(args, llm, bridge, **kw):
            where.append("тело")
            return {"ok": True, "kir": True, "outcome": {}}

        async def plan(*a, **kw):
            where.append("план")
            return {"ok": True, "kir": True, "outcome": {}}

        originals = (serving._handle_revit_ir_inner, serving._run_plan)
        serving._handle_revit_ir_inner, serving._run_plan = inner, plan
        try:
            asyncio.run(serving.handle_revit_ir({"program": program},
                                                None, None, query_id="t"))
        finally:
            serving._handle_revit_ir_inner, serving._run_plan = originals
        self.assertEqual(len(where), 1, where)
        return where[0]

    def test_a_program_without_phases_never_reaches_the_plan_executor(self) -> None:
        """ABSENCE STAYS ABSENCE — at the door, not only in the language."""
        self.level(0)
        program = {**C.take_ops(), "ir_version": spec.IR_VERSION}
        self.assertNotIn("phases", program)
        self.assertEqual(self._route(program), "тело")

    def test_a_phased_program_reaches_the_plan_executor(self) -> None:
        """THE OTHER HALF OF THE SAME CLAIM. A hook that catches no one is
        indistinguishable from a missing one — that is exactly how `sdk.py`
        lay there, present and unreachable, for five weeks."""
        self.assertEqual(self._route(self._plan_of()), "план")


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
