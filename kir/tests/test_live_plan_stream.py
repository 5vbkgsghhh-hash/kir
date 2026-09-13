"""THE LIVE-PLAN GATE IS DESTRUCTIVE, not confirmatory.

The main proof of this wave is not "a frame got drawn" but "the drawer
broke mid-run, and the build DID NOT NOTICE." That is why there are almost
no tests here that turn something on: almost every one of them BREAKS
something and shows, by a number, that the program journal stayed intact
and the caller was neither blocked nor handed an exception.

Sections:
  §1 one-directionality — by import traversal (`ast`), not by reading with
     the eye;
  §2 the tap's singleness — by traversing calls across the whole tree;
  §3 destructive scenarios (five of them);
  §4 boundedness and a long run;
  §5 honesty of the source.
"""
from __future__ import annotations

import ast
import asyncio
import gc
import os
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir.live import journal as J          # noqa: E402
from kir.live import journal_store as _JS  # noqa: E402
from kir.live import plan_stream as S      # noqa: E402

# 27.08.2026: `BACKEND` here means "the directory from which module paths
# are counted" — after the split this is the PACKAGE DIRECTORY, not its
# parent: names of the form `kir.live.journal` start with `kir`, so the
# path starts with `kir/` too.
BACKEND = Path(__file__).resolve().parents[2]

#: Modules that make decisions about compiling and writing. There must be
#: ZERO edges FROM here into them — neither direct nor through a chain.
COMPILER_DECIDERS = frozenset({
    "kir.compiler", "kir.ground", "kir.authoring",
    "kir.midend", "kir.emit_model", "kir.serving",
    "kir.sandbox", "kir.dsl", "kir.macros",
    "kir.authoring_validation", "kir.schema_gen",
    "kir.acceptance", "kir.acceptance_journal",
    "kir.gate_runner", "kir.witness_feed",
})

STREAM_MODULES = ("kir.live", "kir.live.journal", "kir.live.plan_stream")


def _graph():
    sys.path.insert(0, str(BACKEND / "tests"))
    try:
        from kir.instruments import capability_graph  # noqa: WPS433
        return capability_graph.Graph(BACKEND)
    finally:
        if sys.path and sys.path[0] == str(BACKEND / "tests"):
            sys.path.pop(0)


def _reach(graph, seeds, *, through_packages: bool) -> set[str]:
    """Import traversal. `through_packages=False` discards edges into
    packages' `__init__` — that is, it separates "the drawer CALLS the
    compiler" from "the drawer LIVES in a package whose `__init__` calls
    the compiler"."""
    seen: set[str] = set()
    stack = [s for s in seeds if s in graph.modules]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        mod = graph.modules.get(name)
        if mod is None:
            continue
        for edge in (mod.imports | mod.dynamic_imports):
            target = graph.modules.get(edge)
            if target is None:
                continue
            if not through_packages and target.path.name == "__init__.py":
                continue
            if edge not in seen:
                stack.append(edge)
    return seen


def _program(*ops, level_id="LV", level_name="Этаж 1", elev=0.0):
    return {"ir_version": "1.0", "intent": "поток",
            "ops": [{"op": "create_level", "id": level_id, "elev_mm": elev,
                     "name": level_name}, *ops]}


def _walls(n, *, level_id="LV", y=0.0, x0=0.0, tag=""):
    return [{"op": "create_wall", "id": f"W{tag}{i}",
             "p0_mm": [x0 + i * 4000.0, y], "p1_mm": [x0 + i * 4000.0, y + 6000.0],
             "level": {"by": "ref", "value": level_id}} for i in range(n)]


#: THE TAP BUDGET TOGETHER WITH DURABLE WRITING — THE OWNER'S DECISION OF
#: 18.08.2026.
#:
#: 🔴 THE PREVIOUS NUMBER WAS 0.002 (2 ms) AND STOOD AS A BARE LITERAL. It
#: correctly described a subject that no longer exists: the bar was set
#: BEFORE `publish` started writing every program to disk. The 18.08
#: measurement by substitution on 400 programs:
#:
#:     write OFF   0.430 ms/program   fivefold margin
#:     write ON    7.25–7.77 ms/program
#:
#: That is, the tap by itself fit the old budget fivefold, while writing
#: spent the entire margin. **The budget is not wrong — it is OLDER than
#: the subject.**
#:
#: THE FORK WAS THREE-WAY, AND THE OWNER CHOSE IT, NOT US:
#:   1. leave it red            — honest, but a permanently red test stops
#:                                 being an instrument (form 1), and on
#:                                 18.08 this cost twelve foreign machines;
#:   2. batch the fsync         — faster, but programs between flushes are
#:                                 lost if the machine crashes, and the
#:                                 module is written precisely against
#:                                 that;
#:   3. raise the bar with a reason — CHOSEN.
#:
#: WHY THIS IS NOT "FIX THE GUARD SO IT STOPS TURNING RED". Two reasons,
#: and the second matters more: (a) the subject grew, and the yardstick
#: must grow with it; (b) the tap's OWN cost is still under guard — it is
#: held by the neighboring `test_the_tap_itself_is_cheap_without_durable_storage`
#: at 0.43 ms, INDEPENDENTLY of the decision about the journal. Raising the
#: bar here does not leave the tap without a guard.
#:
#: THE NUMBER IS ASSIGNED, NOT DERIVED: 10 ms is the measured 7.8 plus a
#: margin for a slow disk. It is named as a constant, not a literal, so
#: that `bounds_audit` can see it and the next reader does not have to
#: guess where it came from.
_PUBLISH_WITH_JOURNAL_BUDGET_S = 0.010

#: 🔴 01.09.2026: THE ABSOLUTE BUDGET ABOVE HAS ROTTED A SECOND TIME, AND
#: RAISING IT A THIRD TIME WOULD MEAN BUYING THE SAME MISTAKE AGAIN.
#:
#: Measurement on the production venv (`/opt/kukai-rebuild1/backend/venv/bin/python`)
#: under the 2.08 load on 8 cores:
#:
#:     tap WITHOUT storage         0.139 ms/program   (own budget 0.43 — intact)
#:     ONE durable write           median 11.3 · 12.5 · 10.9 ms
#:                                 (three runs of 100, p95 16–19)
#:     tap WITH storage            13.317 ms/program
#:
#: That is, **the 10 ms budget is below the cost of a SINGLE `append_line`
#: on this disk**: it does two `fsync` calls (file AND directory), and
#: this is a property of the DISK, not of the code. An ideal implementation
#: would not pass this test. Meanwhile our own code got FASTER: 0.139
#: against the 0.43 budget, a threefold margin.
#:
#: THEREFORE THE YARDSTICK IS SWITCHED FROM AN ABSOLUTE TO ITS OWN SHARE.
#: The test now calibrates the disk with the SAME `append_line` into the
#: SAME directory and requires that OUR surcharge above the write fit
#: within the budget. If the disk gets slower, the test stays silent (that
#: is not about us); if our code gets more expensive, it turns red, and by
#: exactly the amount we control.
#:
#: 🔴 THAT THIS IS NOT A WEAKENING is proven by a FAIL control: injecting a
#: delay into `publish` turns the test red, removing it turns it green. The
#: absolute budget above is NOT REMOVED: it stays printed in the report as
#: a reference for what the whole program costs.
_PUBLISH_OWN_OVERHEAD_BUDGET_S = 0.004

#: How many writes to take for calibration. Median, not mean: `fsync` has
#: a long tail (p95 is twice the median), and the mean would describe the
#: tail.
_CALIBRATION_APPENDS = 40


class _Loop(unittest.TestCase):
    """Base: its own event loop, a clean stream, an attached panel."""

    def setUp(self):
        S.reset()
        self.sent: list[dict] = []
        self.send_failures = 0

        async def transport(device_id, payload):
            self.sent.append(payload)

        self.transport = transport

    def tearDown(self):
        S.reset()

    def run_async(self, coro):
        return asyncio.run(coro)

    async def _wired(self, device="dev"):
        S.bind_transport(self.transport)
        S.attach(device)


# ─────────────────────────────────────────────────────────────────────────────
# §1. ONE-DIRECTIONALITY
# ─────────────────────────────────────────────────────────────────────────────

class OneWayTests(unittest.TestCase):

    def test_no_reverse_edge_into_compiler(self):
        """There is no path from the drawer to the compiler — proven by
        `ast` traversal.

        The traversal follows the same edges as `capability_graph`:
        `import`, `from … import`, relative, LAZY ones inside functions,
        dynamic ones. Package `__init__` edges are dropped deliberately;
        the remainder is shown by the neighboring
        `test_the_only_package_edge_is_named`.

        🔴 THIS DOCSTRING EXPLAINED THE REMAINDER INCORRECTLY, AND THE COST
        IS NAMED AS A NUMBER (01.09.2026). It used to say: "`preview.py`
        lives inside `kir/`, so importing it executes `kir/__init__.py`,
        which imports the compiler — this is a fact of LOCATION." The test
        was RED at the time, and the truth turned out to be different: the
        path went AROUND the package `__init__`s, through the REGISTRY, and
        the traversal printed it in full —

            kir.compiler <- kir.ground <- kir.authoring <- kir.ops_site
                         <- kir.spec <- kir.preview <- kir.live.plan_stream

        that is, the drawer was querying the registry (legitimately), and
        the registry was pulling in the EMITTER — through four edges, each
        of which was a deliberate "single carrier" placed on the wrong
        floor:

            ops_site      -> authoring.EMIT_UNSUPPORTED      (refusal code)
            ops_boolean   -> solid_emit._plane_profile_box   (reference function)
            ops_families  -> family_author_emit.FAMILY_TEMPLATES (template families)
            relate        -> authoring_validation._COORD_LIMIT_MM (alias)

        None of them were copied: the carriers were moved BELOW both
        readers (the code — into `diag`, the reference function — into
        `kir.plane`, the template families and the coordinate limit — into
        `registry_base`). Measured by the same traversal before and after:
        deciders 10 -> 0, reachable modules 127 -> 48, the emission bytes
        (goldens and `test_emit_model_byte_parity`) did not move.
        """
        graph = _graph()
        reachable = _reach(graph, STREAM_MODULES, through_packages=False)
        leaked = sorted(reachable & COMPILER_DECIDERS)
        self.assertEqual(leaked, [], f"обратное ребро в компилятор: {leaked}")

    def test_the_only_package_edge_is_named(self):
        """The remainder is exhibited: the one remaining name is the
        package `kir` itself.

        The test holds it at EXACTLY ONE. Should a second way to reach the
        compiler appear, the test turns red, and that is exactly what it
        is written for.

        🔴 THE REMAINDER STOPPED BEING EXECUTION AND BECAME A NAME
        (02.09.2026), AND THE DIFFERENCE IS MEASURED, NOT DECLARED.
        Previously `kir/__init__.py` imported `compiler`, `midend`,
        `schema_gen`, `spec` with ordinary imports, and anyone touching
        anything at all inside the package EXECUTED the compiler's load:
        `import kir` loaded 38 modules. Now the public door opens on
        demand (PEP 562, `kir.__getattr__`), and the direct measurement
        is:

            import kir                       -> modules 1   (was 38)
            import kir.live.plan_stream      -> modules 5, deciders NONE AT ALL

        The edge REMAINED, and that is correct: the path into the compiler
        exists, it merely stopped executing on its own. The instrument
        sees it differently than before, and that too is named, not
        hidden:

            kir.imports          []                                  (was four)
            kir.dynamic_imports  compiler, midend, schema_gen, spec

        The names moved into STRING LITERALS of the `kir._PUBLIC`
        dictionary, and `capability_graph`, by construction, counts every
        dotted literal in a module that imports dynamically — that is, it
        answers CONSERVATIVELY. This is not a weakening: the neighboring
        test above requires ZERO deciders bypassing package `__init__`s and
        still holds, while `test_importing_the_stream_loads_no_decider`
        below asks the same quantity by EXECUTION, not by traversal.

        🔴 THE SIGNAL WAS CHANGED ON 01.09.2026: IT USED TO BE A PREFIX,
        NOW IT IS REACHABILITY. This used to read `e.startswith("kir")`,
        and before the split that meant exactly "an edge into the compiler
        package": the stream lived under `kukai.live`, the compiler under
        `kukai.ir`. After the 27.08 split the stream ITSELF moved under
        `kir`, and the same prefix started catching its own neighbors. The
        01.09 measurement showed nine edges instead of two, seven of them
        extra — `kir.env`, `kir.live`, `kir.live.journal`,
        `kir.live.journal_store`, `kir.live.showroom`, `kir.viewer`,
        `kir.viewer.push`.

        **This is not a weakening, and here is what proves it.** Each of
        the nine was asked for REACHABILITY to `COMPILER_DECIDERS` by the
        same traversal as the neighboring test. The answer: the seven
        extra ones have ZERO deciders, `kir` has 11, `kir.preview` has 10.
        That is, the expected set `{kir, kir.preview}` had been correct all
        along; it was the signal that lied, not the number. The new signal
        asks exactly what the heading says, and turns red precisely when a
        NEW way to reach the compiler appears.
        """
        graph = _graph()
        into_ir = set()
        for name in STREAM_MODULES:
            mod = graph.modules[name]
            for edge in mod.imports:
                if not edge.startswith("kir"):
                    continue
                # an edge counts as "into the compiler" only if the
                # compiler is reachable FROM IT; sharing a package-name
                # prefix is not an edge
                if _reach(graph, (edge,), through_packages=False) & COMPILER_DECIDERS:
                    into_ir.add(edge)
        # 🔴 THE REMAINDER SHRANK FROM TWO CARRIERS TO ONE (01.09.2026), AND
        # THIS RED WAS NEWS OF A FIX, NOT A REGRESSION (form 52). Before the
        # fix there were two "registry -> emission" edges: the package
        # `kir` itself (whose `__init__` imports the compiler) and
        # `kir.preview` — the drawer that queried the registry, which in
        # turn pulled in the emitter. The second one is gone: `_reach(("kir.preview",))`
        # now gives ZERO deciders (was 10).
        #
        # ONE remains, and it is named: `kir/__init__.py` pulls in the
        # compiler on package import. This is separate work (detaching
        # `__init__`), and until it is done, THIS test holds the remainder
        # at exactly one: a second way to reach it appearing will turn it
        # red, which is what it is written for.
        self.assertEqual(into_ir, {"kir"}, into_ir)

    def test_importing_the_stream_loads_no_decider(self):
        """BY EXECUTION, NOT BY TRAVERSAL: importing the stream loads no
        decider at all.

        Import traversal answers "does a path exist." What is being asked
        here is different — "does it execute" — and after detaching
        `kir/__init__` (02.09.2026) these two answers DIVERGED: the edge
        in the graph remained (the compiler's names live as string
        literals in `kir._PUBLIC`), while the loading stopped.

        A separate process is mandatory: in the current one the compiler
        is already imported by the suite itself, and the question "does it
        load" is here indistinguishable from "is it already loaded" —
        exactly the form this tree has paid for with its measurement
        window before.
        """
        code = ("import sys, kir.live.plan_stream;"
                "d={'kir.compiler','kir.ground','kir.authoring','kir.midend',"
                "'kir.emit_model','kir.serving','kir.sandbox','kir.dsl','kir.macros',"
                "'kir.authoring_validation','kir.schema_gen','kir.acceptance',"
                "'kir.acceptance_journal','kir.gate_runner','kir.witness_feed'};"
                "print(sorted(set(sys.modules)&d))")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env={"PYTHONPATH": str(BACKEND),
                                             "PATH": "/usr/bin:/bin"})
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertEqual(out.stdout.strip(), "[]",
                         f"импорт потока загрузил решателей: {out.stdout.strip()}")

    def test_preview_declares_no_edge_into_the_compiler(self):
        """`preview.py` is a leaf: at module level it pulls nothing from `kir`."""
        graph = _graph()
        mod = graph.modules["kir.preview"]
        self.assertEqual(mod.imports & COMPILER_DECIDERS, set())

    def test_journal_is_pure(self):
        """The journal knows neither the compiler, nor the web, nor the
        drawer.

        🔴 THE SIGNAL WAS CHANGED ON 01.09.2026 FOR THE SAME REASON AS THE
        NEIGHBOR ABOVE: before the split, `startswith("kir")` meant "the
        compiler", and after it also meant `kir.live.journal_store` (its
        own storage) and `kir.env` (environment variable names). The 01.09
        measurement: for both, reachability to `COMPILER_DECIDERS` is
        ZERO. The property named in the heading held all along; it was the
        signal that lied.

        Exactly the heading is being asked: compiler, web, drawer. The
        package `__init__` is excluded the same way as in
        `test_no_reverse_edge_into_compiler`, and for the same reason —
        it is a fact of the journal's LOCATION inside `kir/`, exhibited
        separately in `test_the_only_package_edge_is_named`.
        """
        graph = _graph()
        reachable = _reach(graph, ("kir.live.journal",), through_packages=False)
        foreign = reachable & (COMPILER_DECIDERS | {"kir.preview"})
        foreign |= {e for e in reachable if e.startswith(("kukai.api", "kukai.llm"))}
        self.assertEqual(foreign, set(), foreign)

    def test_stream_never_imports_the_web_layer(self):
        """The channel is INJECTED (`bind_transport`), not imported:
        otherwise `kir.live` would drag FastAPI into every offline run."""
        graph = _graph()
        mod = graph.modules["kir.live.plan_stream"]
        self.assertEqual({e for e in mod.imports if e.startswith("kukai.api")},
                         set())


# ─────────────────────────────────────────────────────────────────────────────
# §2. THE TAP'S SINGLENESS
# ─────────────────────────────────────────────────────────────────────────────

class SingleCraneTests(unittest.TestCase):

    def _publish_sites(self):
        sites = []
        # 🔴 TRAVERSAL BY PACKAGE, NOT BY `kukai` (28.08.2026). There is no
        # `kukai` directory after the 27.08 split, the traversal found ZERO
        # taps — and the assertion "exactly one tap" failed as "more than
        # one tap: []". A guard that looked nowhere said nothing about its
        # subject.
        for path in (BACKEND / "kir").rglob("*.py"):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "publish"
                        and isinstance(node.func.value, ast.Name)
                        and "plan_stream" in node.func.value.id):
                    sites.append((str(path.relative_to(BACKEND)), node.lineno))
        return sites

    def test_single_publish_call_site(self):
        """One tap, and this is a MACHINE-CHECKED assertion.

        There are four entry points into the authoring program — the chat
        `handle_revit_ir`, the admin `handle_revit_ir_bulk`, the scripted
        `program_py`, and the rebuild. Four taps would have drifted apart
        within a month: three callers independently forgot the rebuild
        policy on 07.21, and that is exactly why it became one function.
        Here the same rule is checked by traversal, not by memory.
        """
        sites = self._publish_sites()
        self.assertEqual(len(sites), 1, f"кранов больше одного: {sites}")
        self.assertEqual(sites[0][0], "kir/serving.py", sites)

    @staticmethod
    def _callers_of(tree, name: str) -> set:
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Call)
                            and isinstance(inner.func, ast.Name)
                            and inner.func.id == name):
                        found.add(node.name)
        return found

    def test_all_doors_funnel_through_the_injection_point(self):
        """Both live doors converge into the body where the interlock sits.

        08.09n: THE CONSTRUCTION PLAN ADDED A THIRD CALLER, and this is NOT
        a third door. `_run_plan` cuts a phased program into a batch and
        drives the links ONE AT A TIME through that same body — that is,
        it is a loop INSIDE the door, not a bypass of it. The difference
        matters for exactly the reason the neighboring one-tap test cares
        about: the policy cannot drift apart, because the policy still
        lives in one body and executes on every link.

        So the list was extended, but the guard was NOT weakened: a second
        assertion stands next to it — `_run_plan` must not gain an entry
        point of its own. If it is ever called directly from a route
        tomorrow, that will be the third door, and the test must then turn
        red. Silently extending the list every time it complains again is
        how such guards die.

        21.08: CHUNKING OF THE DIRECT MOVE ADDED A FOURTH CALLER, AND THIS
        IS NOT A FOURTH DOOR — exactly the same shape as `_run_plan`, and
        accepted on the same grounds, not "the list complained so I added
        an entry." `_drive_chunked_program` cuts a program THAT DOES NOT
        FIT IN THE BRIDGE'S FRAME into contiguous slices and drives them
        ONE AT A TIME through that same body: it is a loop INSIDE the
        door, not a bypass of it. The policy cannot drift apart because it
        still lives in one body and executes on every slice.

        And the extension was again made SAFE THE SAME WAY: the driver has
        no entry point of its own — it is reachable only from the body. If
        it is ever called directly from a route tomorrow, that will be the
        fourth door, and the test will turn red.
        """
        source = (BACKEND / "kir/serving.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertEqual(
            self._callers_of(tree, "_handle_revit_ir_inner"),
            {"handle_revit_ir", "handle_revit_ir_bulk", "_run_plan",
             "_drive_chunked_program"})
        # THIS is exactly what makes the extension safe: neither the plan
        # driver nor the chunk driver has an entry point of its own.
        self.assertEqual(self._callers_of(tree, "_run_plan"),
                         {"handle_revit_ir"})
        self.assertEqual(self._callers_of(tree, "_drive_chunked_program"),
                         {"_handle_revit_ir_inner"})

    def test_injection_is_write_only(self):
        """The interlock asks the midend for the program's family, not
        itself.

        The journal is the SOURCE CODE of the building. The 07.29 turn
        made 176 reads for 5 writes; if queries landed in the journal, the
        building's history would turn into noise. There is exactly ONE
        classifier — `_program_writes` — the same one the rest of the path
        uses.
        """
        source = (BACKEND / "kir/serving.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        guarded = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            calls = {inner.func.attr for inner in ast.walk(node)
                     if isinstance(inner, ast.Call)
                     and isinstance(inner.func, ast.Attribute)}
            names = {inner.func.id for inner in ast.walk(node.test)
                     if isinstance(inner, ast.Call)
                     and isinstance(inner.func, ast.Name)}
            if "publish" in calls and "_program_writes" in names:
                guarded = True
        self.assertTrue(guarded, "врезка не отфильтрована по семье программы")

    def test_injection_is_wrapped(self):
        """The interlock sits INSIDE `try/except Exception`. Structurally,
        not by eye: you cannot forget to apply the rule, though you can
        forget a line."""
        source = (BACKEND / "kir/serving.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        wrapped = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            has_call = any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "publish"
                for inner in ast.walk(node)
            )
            if not has_call:
                continue
            for handler in node.handlers:
                if (handler.type is None
                        or (isinstance(handler.type, ast.Name)
                            and handler.type.id == "Exception")):
                    wrapped = True
        self.assertTrue(wrapped, "врезка не обёрнута в except Exception")

    def test_publish_has_no_await(self):
        """THE TAP HAS NO WAIT — by construction, not by intent.

        There is not a single wait point in the body of `publish`, so the
        caller cannot be delayed by drawing even in theory. This is an
        assertion about the SHAPE of the function, and it is checked by
        shape.
        """
        source = (BACKEND / "kir/live/plan_stream.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = [n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "publish"]
        self.assertEqual(len(found), 1)
        self.assertFalse(
            any(isinstance(inner, (ast.Await, ast.AsyncFor, ast.AsyncWith))
                for inner in ast.walk(found[0])))


# ─────────────────────────────────────────────────────────────────────────────
# §3. DESTRUCTIVE SCENARIOS
# ─────────────────────────────────────────────────────────────────────────────

class DestructiveTests(_Loop):
    """"What was broken → what happened to the build." In every case — by
    a NUMBER."""

    PROGRAMS = 40

    async def _build_run(self, *, device="dev", bridge_s=0.001):
        """A run that plays out the build: publishing + waiting for the
        "bridge".

        Returns (how many programs were sent, how many seconds the run
        took).
        """
        started = time.perf_counter()
        for i in range(self.PROGRAMS):
            S.publish(device_id=device, doc_key="doc",
                      program=_program(*_walls(3, tag=f"{i}_", y=i * 500.0)),
                      source="chat")
            await asyncio.sleep(bridge_s)   # "the bridge executes the program"
        return self.PROGRAMS, time.perf_counter() - started

    def _journal_is_intact(self, expected):
        entry = J.get(("dev", "doc"))
        self.assertIsNotNone(entry, "журнал пуст — программы потеряны")
        self.assertEqual(len(entry.records) + entry.programs_evicted, expected)
        return entry

    # -- 1. exception inside the drawer --------------------------------
    def test_exploding_drawer_does_not_reach_the_build(self):
        async def scenario():
            await self._wired()
            S._render_frame = _boom          # the drawer is broken to DEATH
            sent, elapsed = await self._build_run()
            await S.drain(5.0)
            return sent, elapsed

        original = S._render_frame
        try:
            sent, elapsed = self.run_async(scenario())
        finally:
            S._render_frame = original
        entry = self._journal_is_intact(sent)
        st = S.stats()
        self.assertEqual(st["journaled"], sent, "программа потеряна")
        self.assertGreater(st["render_errors"], 0, "поломка не предъявлена числом")
        self.assertEqual(st["frames_sent"], 0)
        self.assertEqual(self.sent, [])
        # The build did not notice: the journal is full, not a single exception escaped.
        self.assertEqual(entry.ops_held, sum(r.op_count for r in entry.records))

    # -- 2. slow drawer (frames lag behind) --------------------------
    def test_slow_drawer_does_not_delay_the_build(self):
        slow = 0.05   # 50 ms per frame against a ~1 ms build step

        def crawl(ops, label, fresh=None):
            time.sleep(slow)
            return {"level": label, "assertion": "self_reported", "svg": "",
                    "census": {}, "meta": {}, "source": "program",
                    "assertion_ru": "ЗАЯВЛЕНО", "content_digest": ""}

        async def scenario():
            await self._wired()
            S._render_frame = crawl
            return await self._build_run()

        original = S._render_frame
        try:
            sent, elapsed = self.run_async(scenario())
        finally:
            S._render_frame = original
        self._journal_is_intact(sent)
        # The build made 40 steps of 1 ms each. Even if the drawer managed
        # to draw everything, that is 40 × 50 ms = 2 s; the run must
        # finish well before that, because frames collapse into each
        # other rather than waiting in a queue.
        self.assertLess(elapsed, 1.0, f"стройку задержали: {elapsed:.3f} с")
        self.assertEqual(S.stats()["journaled"], sent)

    # -- 3. queue overflow -------------------------------------------
    def test_queue_overflow_drops_frames_never_programs(self):
        def crawl(ops, label, fresh=None):
            time.sleep(0.02)
            return {"level": label, "assertion": "self_reported", "svg": "",
                    "census": {}, "meta": {}, "source": "program",
                    "assertion_ru": "ЗАЯВЛЕНО", "content_digest": ""}

        async def scenario():
            await self._wired()
            S._render_frame = crawl
            # Publishing in a BURST, without yielding to the loop even
            # once: the worker will not keep up, the queue must hit the
            # ceiling.
            for i in range(400):
                S.publish(device_id="dev", doc_key="doc",
                          program=_program(*_walls(2, tag=f"{i}_")),
                          source="chat")
            await S.drain(10.0)
            return 400

        original = S._render_frame
        os.environ["KUKAI_KIR_LIVE_PLAN_QUEUE"] = "4"
        try:
            sent = self.run_async(scenario())
        finally:
            S._render_frame = original
            os.environ.pop("KUKAI_KIR_LIVE_PLAN_QUEUE", None)
        st = S.stats()
        self.assertGreater(st["dropped_frames"], 0, "потолок очереди не сработал")
        self.assertLessEqual(st["queue_depth"], 4)
        self.assertEqual(st["journaled"], sent, "выброшен кадр — потеряна программа")
        entry = self._journal_is_intact(sent)
        # And most importantly: the discarded alarm did not leave the journal unread.
        self.assertEqual(entry.indexed_upto, entry.next_seq,
                         "работник не догнал журнал по курсору")

    # -- 4. the panel's socket dropped ---------------------------------------
    def test_dead_socket_does_not_stop_the_build(self):
        async def dead(device_id, payload):
            raise ConnectionResetError("панель отвалилась")

        async def scenario():
            S.bind_transport(dead)
            S.attach("dev")
            sent, _ = await self._build_run()
            await S.drain(5.0)
            return sent

        sent = self.run_async(scenario())
        self._journal_is_intact(sent)
        st = S.stats()
        self.assertGreater(st["send_errors"], 0)
        self.assertEqual(st["frames_sent"], 0)
        self.assertEqual(st["journaled"], sent)
        # The worker is alive: it kept drawing despite the dead socket.
        self.assertGreater(st["renders"], 0)

    def test_hanging_socket_does_not_stop_the_build(self):
        """The socket did not drop but HUNG — a worse case than a break."""
        async def hang(device_id, payload):
            await asyncio.sleep(30)

        async def scenario():
            S.bind_transport(hang)
            S.attach("dev")
            sent, elapsed = await self._build_run()
            return sent, elapsed

        os.environ["KUKAI_KIR_LIVE_PLAN_SEND_MS"] = "100"
        try:
            sent, elapsed = self.run_async(scenario())
        finally:
            os.environ.pop("KUKAI_KIR_LIVE_PLAN_SEND_MS", None)
        self._journal_is_intact(sent)
        self.assertLess(elapsed, 1.0, f"зависший сокет задержал стройку: {elapsed:.3f}")

    # -- 5. there is no panel at all -------------------------------------------------
    def test_no_panel_means_no_drawing_at_all(self):
        async def scenario():
            S.bind_transport(self.transport)     # the channel exists, there is no panel
            sent, _ = await self._build_run()
            await S.drain(2.0)
            return sent

        sent = self.run_async(scenario())
        self._journal_is_intact(sent)
        st = S.stats()
        self.assertEqual(st["renders"], 0, "рисовали без панели")
        self.assertEqual(st["queued"], 0, "будили работника без панели")
        self.assertEqual(st["skipped_no_panel"], sent)
        self.assertEqual(st["journaled"], sent, "журнал обязан жить без панели")

    def test_transport_never_bound(self):
        """The web layer never called `bind_transport` — the stream stays silent, the build proceeds."""
        async def scenario():
            S.attach("dev")          # the panel "exists", there is no channel
            sent, _ = await self._build_run()
            await S.drain(5.0)
            return sent

        sent = self.run_async(scenario())
        self._journal_is_intact(sent)
        self.assertEqual(S.stats()["frames_sent"], 0)

    # -- 6. the tap NEVER throws -----------------------------------------
    def test_publish_never_raises(self):
        """Even when the journal itself is broken — that is, the part that is primary."""
        original = J.append

        def poisoned(*a, **k):
            raise MemoryError("журнал отравлен")

        J.append = poisoned
        try:
            S.publish(device_id="dev", doc_key="doc", program=_program(*_walls(2)))
        finally:
            J.append = original
        # No exception at all. That is the whole test.

    def test_publish_outside_an_event_loop(self):
        """A scripted run with no loop: the journal is written, the worker never starts."""
        S.bind_transport(self.transport)
        S.attach("dev")
        S.publish(device_id="dev", doc_key="doc", program=_program(*_walls(2)))
        self.assertEqual(S.stats()["journaled"], 1)
        self.assertEqual(S.stats()["queue_depth"], 0)

    def test_disabled_flag_costs_nothing(self):
        os.environ["KUKAI_KIR_LIVE_PLAN"] = "0"
        try:
            S.publish(device_id="dev", doc_key="doc", program=_program(*_walls(2)))
        finally:
            os.environ.pop("KUKAI_KIR_LIVE_PLAN", None)
        self.assertEqual(S.stats()["journaled"], 0)
        self.assertEqual(J.stats()["programs"], 0)


# 🔴 ТРЕТИЙ ПАРАМЕТР У ВСЕХ ДУБЛЁРОВ `_render_frame` — НЕ УКРАШЕНИЕ
# (13.09.2026). Кадр теперь получает СВЕЖУЮ ПРОГРАММУ, чтобы подсветить на
# листе то, что человек только что попросил (`focus=`). Дублёр с прежними
# двумя параметрами бросает `TypeError`, а цикл кадра ловит любое исключение
# рисовальщика и идёт дальше (fail-open) — то есть тест не краснеет вызовом,
# он просто НЕ ВИДИТ НИ ОДНОГО КАДРА и утверждает пустоту. Замерено на этом
# файле: `test_only_the_changed_level_is_redrawn` и
# `test_levels_per_frame_is_capped` упали на пустых списках, а не на предмете.
def _boom(ops, label, fresh=None):
    raise RuntimeError("рисовальщик сломан")


# ─────────────────────────────────────────────────────────────────────────────
# §4. BOUNDEDNESS AND A LONG RUN
# ─────────────────────────────────────────────────────────────────────────────

class BoundednessTests(_Loop):

    def test_journal_is_capped_and_names_what_it_dropped(self):
        os.environ["KUKAI_KIR_JOURNAL_PROGRAMS"] = "16"
        try:
            for i in range(60):
                S.publish(device_id="dev", doc_key="doc",
                          program=_program(*_walls(2, tag=f"{i}_")))
            entry = J.get(("dev", "doc"))
            self.assertLessEqual(len(entry.records), 16)
            self.assertEqual(entry.programs_evicted, 60 - len(entry.records))
            # What was evicted is NAMED and goes onto the sheet, not silently forgotten.
            self.assertGreater(entry.summary()["programs_evicted"], 0)
        finally:
            os.environ.pop("KUKAI_KIR_JOURNAL_PROGRAMS", None)

    def test_sessions_are_capped(self):
        os.environ["KUKAI_KIR_JOURNAL_SESSIONS"] = "3"
        try:
            for i in range(12):
                S.publish(device_id=f"dev{i}", doc_key="doc",
                          program=_program(*_walls(2)))
            self.assertLessEqual(J.stats()["sessions"], 3)
        finally:
            os.environ.pop("KUKAI_KIR_JOURNAL_SESSIONS", None)

    def test_only_the_changed_level_is_redrawn(self):
        """The level THAT CHANGED is what gets drawn, not the whole
        building.

        Otherwise the union of all the session's programs gives quadratic
        work (measurement K2: 9.3 s for three floors).
        """
        drawn: list[str] = []
        original = S._render_frame

        def spy(ops, label, fresh=None):
            drawn.append(label)
            return original(ops, label, fresh)

        async def scenario():
            await self._wired()
            S._render_frame = spy
            for level in ("A", "B", "C"):
                S.publish(device_id="dev", doc_key="doc",
                          program=_program(*_walls(3, level_id=level),
                                           level_id=level, level_name=f"Этаж {level}"))
                await S.drain(5.0)
            # One more program covering ONLY floor B.
            drawn.clear()
            S.publish(device_id="dev", doc_key="doc",
                      program=_program(*_walls(2, level_id="B", tag="x", y=9000.0),
                                       level_id="B", level_name="Этаж B"))
            await S.drain(5.0)

        try:
            self.run_async(scenario())
        finally:
            S._render_frame = original
        self.assertEqual(set(drawn), {"Этаж B"},
                         f"перерисовали лишние этажи: {drawn}")

    def test_levels_per_frame_is_capped(self):
        os.environ["KUKAI_KIR_LIVE_PLAN_LEVELS"] = "2"
        drawn: list[str] = []
        original = S._render_frame

        def spy(ops, label, fresh=None):
            drawn.append(label)
            return {"level": label, "assertion": "self_reported", "svg": "",
                    "census": {}, "meta": {}, "source": "program",
                    "assertion_ru": "ЗАЯВЛЕНО", "content_digest": ""}

        async def scenario():
            await self._wired()
            S._render_frame = spy
            ops = []
            for level in ("A", "B", "C", "D", "E"):
                ops.append({"op": "create_level", "id": level, "elev_mm": 0,
                            "name": f"Этаж {level}"})
                ops.extend(_walls(2, level_id=level, tag=level))
            S.publish(device_id="dev", doc_key="doc", program={"ops": ops})
            await S.drain(5.0)

        try:
            self.run_async(scenario())
        finally:
            S._render_frame = original
            os.environ.pop("KUKAI_KIR_LIVE_PLAN_LEVELS", None)
        self.assertLessEqual(len(drawn), 2, drawn)
        self.assertTrue(self.sent)
        self.assertGreater(self.sent[-1]["levels_not_drawn"], 0,
                           "необрисованные этажи не названы")

    def test_long_run_memory_and_time(self):
        """A LONG RUN: hundreds of programs, memory and time — by a
        number.

        Prints the measurement so that it lands in the wave's report, not
        in an assertion.

        🔴 THE MEASUREMENT CONDITION IS SET HERE, NOT INHERITED FROM THE
        ENVIRONMENT (18.08). Before this fix, the journal's storage was
        taken by default — that is, `install_data_path("telemetry")`, the
        service's directory. Under the service's user, writes there
        succeed; under the SUITE's user, they do not: `append_line` raised
        `PermissionError`, `fail-open` swallowed it, and the test printed
        **2.528 ms/program**, which is not the cost of writing and not the
        cost of the tap, but the COST OF FAILURE. The same day's
        measurement with writable storage was **7.773**, meaning the
        earlier number understated by a factor of three.

        Hence the rule this is written out so carefully to establish: **an
        instrument whose cost depends on directory permissions must set
        the directory ITSELF.** Otherwise it measures its own environment
        while reporting on the subject.
        """
        programs = 400
        walls_each = 6
        _tmp = tempfile.TemporaryDirectory()
        self.addCleanup(_tmp.cleanup)
        os.environ[_JS.PATH_ENV] = str(Path(_tmp.name) / "journal.jsonl")
        self.addCleanup(lambda: os.environ.pop(_JS.PATH_ENV, None))

        async def scenario():
            await self._wired()
            t0 = time.perf_counter()
            for i in range(programs):
                S.publish(
                    device_id="dev", doc_key="doc",
                    program=_program(*_walls(walls_each, tag=f"{i}_",
                                             y=(i % 20) * 800.0)),
                    source="chat")
                if i % 25 == 0:
                    await asyncio.sleep(0)
            publish_s = time.perf_counter() - t0
            await S.drain(120.0)
            return publish_s, time.perf_counter() - t0

        gc.collect()
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[0]
        publish_s, total_s = self.run_async(scenario())
        peak_kb = (tracemalloc.get_traced_memory()[1] - base) / 1024.0
        tracemalloc.stop()

        entry = J.get(("dev", "doc"))
        st = S.stats()
        # Separately — the PURE cost of a frame, without racing the build
        # for the GIL. The difference between this and the average frame
        # time is the cost of coexistence.
        slice_ops, _dropped, _pack = S._slice_for(entry, "Этаж 1")
        t0 = time.perf_counter()
        S._render_frame(slice_ops, "Этаж 1")
        solo_ms = (time.perf_counter() - t0) * 1000.0
        print(f"\n[длинный прогон] программ={programs} "
              f"операций={entry.ops_held + entry.ops_evicted} "
              f"кран={publish_s * 1000:.1f} мс всего "
              f"({publish_s / programs * 1000:.3f} мс/программу) "
              f"прогон={total_s:.2f} с "
              f"кадров={st['frames_sent']} выброшено={st['dropped_frames']} "
              f"отрисовок={st['renders']} "
              f"среднее_время_кадра={st['render_ms_total'] / max(1, st['renders']):.1f} мс "
              f"кадр_без_гонки={solo_ms:.1f} мс (срез {len(slice_ops)} опов) "
              f"пик_памяти={peak_kb:.0f} КБ "
              f"вытеснено_программ={entry.programs_evicted}")

        # 🔴 DISK CALIBRATION — WITH THE SAME INSTRUMENT AND INTO THE SAME
        # DIRECTORY. Otherwise "the tap is expensive" would print the same
        # for an expensive tap and for a slow disk, and these are
        # different assertions: we control the first, not the second.
        # Median, not mean: the `fsync` tail is long.
        calib_path = Path(_tmp.name) / "calibration.jsonl"
        row = {"seq": 0, "op": "create_wall", "payload": "x" * 400}
        for _ in range(5):                       # warm-up, does not count
            _JS.append_line(calib_path, row)
        appends = []
        for _ in range(_CALIBRATION_APPENDS):
            t0 = time.perf_counter()
            _JS.append_line(calib_path, row)
            appends.append(time.perf_counter() - t0)
        appends.sort()
        disk_s = appends[len(appends) // 2]
        per_program_s = publish_s / programs
        overhead_s = per_program_s - disk_s
        print(f"[калибровка] запись медиана={disk_s * 1000:.3f} мс · "
              f"кран={per_program_s * 1000:.3f} мс · "
              f"НАША надбавка={overhead_s * 1000:.3f} мс "
              f"при бюджете {_PUBLISH_OWN_OVERHEAD_BUDGET_S * 1000:.0f} мс "
              f"(абсолют для справки: {_PUBLISH_WITH_JOURNAL_BUDGET_S * 1000:.0f} мс)")

        # The tap must be cheap by ITS OWN share: this is what it costs
        # the BUILD above and beyond the unavoidable cost of durability.
        self.assertLess(
            overhead_s, _PUBLISH_OWN_OVERHEAD_BUDGET_S,
            f"кран дорог СВОЕЙ долей: {overhead_s * 1000:.3f} мс/программу "
            f"сверх записи ({disk_s * 1000:.3f} мс) при бюджете "
            f"{_PUBLISH_OWN_OVERHEAD_BUDGET_S * 1000:.0f} мс. Диск здесь ни "
            f"при чём: он померен тем же `append_line` в тот же каталог")
        # Memory is bounded by the journal's ceiling, not by the number of programs.
        self.assertLess(peak_kb, 60_000, f"память выросла на {peak_kb:.0f} КБ")
        self.assertEqual(st["journaled"], programs)
        self.assertEqual(entry.indexed_upto, entry.next_seq)

    def test_the_tap_itself_is_cheap_without_durable_storage(self):
        """The tap's OWN cost — the one that does NOT depend on the
        decision about the journal.

        🔴 WHY A SEPARATE TEST NEXT TO THE NEIGHBOR THAT IS RED.
        The neighbor (`test_long_run_memory_and_time`) measures the tap
        TOGETHER with the disk write and is therefore honestly red today:
        the 18.08 measurement by substitution on 400 programs — write OFF
        0.430 ms/program, ON 2.528, meaning the durable journal adds
        ~2.1 ms against a budget of 2. This is NOT a break in the tap:
        `publish` by itself fit the budget fivefold, and the write spent
        the entire margin.

        🔴 THE DECISION WAS MADE BY THE OWNER ON 18.08.2026: we pay for
        durability, the neighbor's budget is raised from 2 to 10 ms with a
        named reason (`_PUBLISH_WITH_JOURNAL_BUDGET_S`). The neighbor is
        no longer red — and this is NOT "we fixed the guard so it stops
        turning red": the subject grew, the yardstick grew with it, and
        the tap's OWN cost stayed under guard HERE, independently of the
        journal. The earlier wording of this paragraph said "until the
        decision is made, the neighbor must stay red" — it went stale that
        same day, and leaving it would have meant keeping two carriers of
        one fact silently drifting apart.

        And THIS test holds what does not depend on the decision at all:
        **the tap itself, without storage, must be cheap**. If `publish`
        becomes expensive tomorrow, the neighbor will turn red on the same
        number, and the cause will no longer be distinguishable — this one
        separates the two quantities that are fused into one in the
        neighbor.

        🔴 ITS NUMBER SHOULD NOT BE COMPARED WITH THE NEIGHBOR'S DIRECTLY,
        AND THIS IS NOT NITPICKING. The neighbor runs `tracemalloc` (it
        needs the memory), this one does not, and allocation tracing costs
        an order of magnitude here: 0.049 ms without it against 0.430 ms
        with it, on the same disabled storage. The 0.002 s threshold is
        the same for both, but the MARGIN below it differs, and you cannot
        subtract one from the other. The comparable pair is only inside
        the neighbor: 0.430 OFF against 2.528 ON, both under tracing. The
        separation of the two quantities this test is written for would be
        devalued if it introduced a third one under the same name.
        """
        def tap_cost_ms(store_path: str) -> float:
            os.environ[_JS.PATH_ENV] = store_path
            try:
                programs = 400

                async def scenario():
                    await self._wired()
                    t0 = time.perf_counter()
                    for i in range(programs):
                        S.publish(device_id="dev", doc_key="doc",
                                  program=_program(*_walls(6, tag=f"{i}_",
                                                           y=(i % 20) * 800.0)),
                                  source="chat")
                        if i % 25 == 0:
                            await asyncio.sleep(0)
                    return time.perf_counter() - t0

                return self.run_async(scenario()) / programs * 1000.0
            finally:
                os.environ.pop(_JS.PATH_ENV, None)

        with tempfile.TemporaryDirectory() as tmp:
            writable = str(Path(tmp) / "journal.jsonl")
            off_ms = tap_cost_ms("")          # "" -> store_path() gives None
            on_ms = tap_cost_ms(writable)     # a REAL file, permissions are present
            rows = sum(1 for _ in open(writable, encoding="utf-8"))

        print(f"\n[кран без хранилища] ВЫКЛ {off_ms:.3f} · "
              f"ВКЛ {on_ms:.3f} мс/программу · строк записано {rows}")

        # 🔴 THE DISTINCTION FIRST, NOT LAST. Without it the test is green
        # BY CONSTRUCTION: the first version passed even WITH storage
        # ENABLED, because the default led to a directory without
        # permissions, the write failed, `fail-open` swallowed it — and
        # the instrument's failure read as cheapness. Caught by a control
        # on 18.08, not by reasoning.
        self.assertEqual(rows, 400,
                         "хранилище не записало 400 строк — значит арм «ВКЛ» "
                         "ничего не мерил, и зелёное ниже ничего не значит")
        self.assertGreater(on_ms, off_ms * 2,
                           f"арм с хранилищем не отличается от арма без него "
                           f"({on_ms:.3f} против {off_ms:.3f}) — прибор слеп "
                           f"к тому, что обязан различать")

        # And only now — the actual assertion about the tap.
        self.assertLess(off_ms, 2.0,
                        f"кран сам по себе дорог: {off_ms:.3f} мс/программу — "
                        f"это регресс ПОТОКА, а не цена журнала")

    def test_second_long_run_does_not_grow_the_first(self):
        """A leak is caught not by size but by the GROWTH between two runs."""
        def one_round():
            for i in range(200):
                S.publish(device_id="dev", doc_key="doc",
                          program=_program(*_walls(4, tag=f"{i}_")))
            return J.get(("dev", "doc")).ops_held

        os.environ["KUKAI_KIR_JOURNAL_PROGRAMS"] = "64"
        try:
            first = one_round()
            second = one_round()
            self.assertEqual(first, second,
                             "журнал растёт от прогона к прогону")
        finally:
            os.environ.pop("KUKAI_KIR_JOURNAL_PROGRAMS", None)


# ─────────────────────────────────────────────────────────────────────────────
# §5. HONESTY OF THE SOURCE
# ─────────────────────────────────────────────────────────────────────────────

class HonestyTests(_Loop):

    def _one_frame(self):
        async def scenario():
            await self._wired()
            S.publish(device_id="dev", doc_key="doc",
                      program=_program(*_walls(4)), source="chat")
            await S.drain(10.0)

        self.run_async(scenario())
        self.assertTrue(self.sent, "кадр не доехал")
        return self.sent[-1]

    def test_frame_names_its_source_as_declared(self):
        """The `preview` label reaches the panel WHOLE.

        Without it, in a month someone will say "I saw it, everything
        looked fine" — and we would end up with acceptance by eyeballing.
        """
        frame = self._one_frame()
        self.assertEqual(frame["assertion"], "self_reported")
        self.assertEqual(frame["source"], "program")
        # 🔴 THE PIN MOVED TOGETHER WITH ITS SUBJECT (08.09.2026). It
        # pinned the word "DECLARED" in the field that the window prints
        # as a badge ABOVE the picture — and the owner, having asked
        # "make a cube," read the instrument's vocabulary as the first
        # line instead of an answer to their question. The strength of the
        # assertion must arrive whole, and it does: in the instrument's
        # vocabulary via `assertion_instrument_ru`, in human wording via
        # `assertion_ru`.
        self.assertIn("ЗАЯВЛЕНО", frame["assertion_instrument_ru"])
        self.assertNotIn("ЗАЯВЛЕНО", frame["assertion_ru"])
        self.assertIn("по программе", frame["assertion_ru"])
        self.assertEqual(frame["stage"], "planned")

    def test_frame_carries_the_census(self):
        """The honesty census travels with the frame: "N of M drawn, this
        many not drawn for named reasons"."""
        frame = self._one_frame()
        census = frame["census"]
        self.assertIn("considered", census)
        self.assertIn("drawn", census)
        self.assertIn("omitted", census)
        self.assertEqual(census["considered"],
                         census["drawn"] + census["omitted_total"])
        self.assertIn("<svg", frame["svg"])

    def test_summary_never_says_built(self):
        """The summary says "DECLARED," and the word "built" is not in it.

        The journal fills up BEFORE the write, so Revit will still reject
        some of the programs. Calling this "built" would mean lying
        exactly at the spot the whole screen exists for.
        """
        frame = self._one_frame()
        summary = frame["summary"]
        self.assertEqual(summary["stage"], "planned")
        self.assertEqual(summary["assertion"], "self_reported")
        self.assertTrue(summary["title_ru"].startswith("ЗАЯВЛЕНО"),
                        summary["title_ru"])
        # "built" in the heading is permitted in exactly one form — a negation.
        self.assertIn("не «построено»", summary["title_ru"])
        self.assertGreater(summary["total"], 0)

    def test_summary_counts_levels_and_ops(self):
        frame = self._one_frame()
        summary = frame["summary"]
        self.assertEqual([row["level"] for row in summary["levels"]], ["Этаж 1"])
        self.assertEqual(summary["by_op"]["create_wall"], 4)
        self.assertEqual(summary["by_op"]["create_level"], 1)


class EndToEndTests(_Loop):
    """A frame built from the REAL compiler plan, not from a hand-written
    dictionary.

    Without this, every gate above would be measuring the stream against
    its own invention: what must be drawn is exactly what the midend
    passed down — with macros expanded and defaults filled in.
    """

    def test_frame_from_a_real_planned_program(self):
        from kir.compiler import plan_program
        planned = plan_program(_program(*_walls(5)))

        async def scenario():
            await self._wired()
            S.publish(device_id="dev", doc_key="doc", program=planned,
                      source="chat")
            await S.drain(10.0)

        self.run_async(scenario())
        self.assertTrue(self.sent, "кадр из настоящего плана не доехал")
        frame = self.sent[-1]
        self.assertEqual(frame["assertion"], "self_reported")
        self.assertIn("<svg", frame["svg"])
        # The journal holds the EXPANDED plan, not the author's text: the
        # plan's signature comes from the compiler and matches the one
        # recorded.
        record = J.get(("dev", "doc")).records[-1]
        self.assertEqual(record.plan_digest, planned.plan_digest)
        self.assertEqual(record.op_count, len(planned.to_ops()))
        self.assertEqual(frame["census"]["drawn"], 5)

    def test_macro_expanded_program_is_drawn_as_lowered(self):
        """`stack` is expanded BEFORE the journal — the sheet shows floors, not a macro."""
        from kir.compiler import plan_program
        floor = [{"op": "create_wall", "id": f"W{i}",
                  "p0_mm": [i * 4000.0, 0.0],
                  "p1_mm": [i * 4000.0, 6000.0]} for i in range(4)]
        program = {
            "ir_version": "1.0", "intent": "башня",
            "ops": [{"op": "stack", "id": "ST", "levels": 3, "h_mm": 3000,
                     "floor": floor}],
        }
        planned = plan_program(program)
        S.publish(device_id="dev", doc_key="doc", program=planned)
        record = J.get(("dev", "doc")).records[-1]
        # 3 floors × (create_level + 4 walls) = 15 operations.
        self.assertEqual(record.op_count, 15,
                         "в журнал лёг макрос, а не раскрытые операции")
        self.assertNotIn("stack", {op.get("op") for op in record.ops})

        async def scenario():
            await self._wired()
            S.publish(device_id="dev", doc_key="doc2", program=planned)
            await S.drain(10.0)

        self.run_async(scenario())
        # Three floors — and each one is named by its own sheet, not as a single "tower" chunk.
        levels = {row["level"] for row in self.sent[-1]["summary"]["levels"]}
        self.assertEqual(len(levels), 3, levels)


if __name__ == "__main__":
    unittest.main()
