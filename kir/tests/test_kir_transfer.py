"""THE RETURN GATE — "what was seen is what gets built," BY MEASUREMENT,
not by promise.

Two laws and one honesty are proven here:

  §1 THE FIRST LAW — exactly what was shown gets executed. The main test
     is not "it matched," but "THE SUBSTITUTION WAS REJECTED": a program
     the server never showed does not transfer, and the refusal names
     exactly what was missing.
  §2 THE SECOND LAW — the selection is closed under the forward-move
     graph. A door without its wall is grown out, what was added is
     NAMED, and the grown-out batch is NOT executed until its own
     signature is confirmed.
  §3 THE CENSUS reaches the person alongside the picture and is counted
     for what transfers, not for the sheet.
  §4 REACHABILITY of new code from the prod process — by instrument
     (`capability_graph`), not by grepping imports.

§1.1 is not a test but a preserved MEASUREMENT. It explains why the
transfer ticket is the program's signature, not the sheet's already
existing signature.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

from kir import env

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir.live import journal as J          # noqa: E402
from kir.live import plan_stream as S      # noqa: E402
from kir.live import showroom as SR        # noqa: E402
from kir.live import transfer as T         # noqa: E402

#: 🔴 TWO ROOTS INSTEAD OF ONE (28.08.2026). Before the split,
#: `parents[3]` was the install root, where both our code and `kukai/api`
#: sat side by side. After 27.08 the same count gives `/opt`: the graph
#: would traverse directory neighbors, and `kukai/api/chat_ws.py` would
#: be looked for at `/opt/kukai/…`, which does not exist.
BACKEND = Path(__file__).resolve().parents[2]        #: the root of OUR tree
#: the HOST's root — optional; without it, assertions about ITS files
#: are skipped
HOST_ROOT = Path(env.get("KIR_HOST_ROOT", "/opt/kukai-rebuild1/backend"))

KEY = ("dev", "")

LEVEL = {"op": "create_level", "id": "LV", "elev_mm": 0.0, "name": "Этаж 1"}
WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0.0, 0.0],
        "p1_mm": [6000.0, 0.0], "level": {"by": "ref", "value": "LV"}}
DOOR = {"op": "create_door", "id": "D3", "offset_mm": 3000.0,
        "host": {"by": "ref", "value": "W1"}}


def _pack(*programs):
    return [list(p) for p in programs]


class _Base(unittest.TestCase):

    def setUp(self):
        S.reset()
        SR.reset()

    def tearDown(self):
        S.reset()
        SR.reset()

    def shown(self, programs, context=(LEVEL,), level="Этаж 1"):
        entry = SR.show(KEY, level=level, programs=programs, context=context)
        self.assertIsNotNone(entry, "витрина обязана принять кодируемую пачку")
        return entry


# ─────────────────────────────────────────────────────────────────────────────
# §1. THE FIRST LAW: we look at and build ONE program
# ─────────────────────────────────────────────────────────────────────────────

class OneProgramTests(_Base):

    def test_sheet_digest_does_not_identify_the_program(self):
        """THE MEASUREMENT that made the PROGRAM's signature the ticket.

        `FloorPlan.content_digest` signs the picture — and must sign
        exactly that. But a wall's height and its type are not drawn on
        the plan, so three different programs give ONE sheet digest. Had
        we taken it as the ticket, the "build what I see" button would
        build a 4.2m brick wall under an ordinary-looking signature — a
        second signature for one building.
        """
        from kir.preview import build_program_preview

        def sheet(extra):
            program = {"ir_version": "1.0", "intent": "t",
                       "ops": [LEVEL, {**WALL, **extra}]}
            return build_program_preview(program).plan("Этаж 1").content_digest

        plain, tall = sheet({}), sheet({"height_mm": 4200.0})
        typed = sheet({"type_name": "Кирпич 380"})
        self.assertEqual(plain, tall, "лист их и не различает — это про лист")
        self.assertEqual(plain, typed)

        def program(extra):
            return SR.program_digest(
                (SR.canonical_program([LEVEL, {**WALL, **extra}]),),
                SR.canonical_program([]), "Этаж 1")

        self.assertNotEqual(program({}), program({"height_mm": 4200.0}))
        self.assertNotEqual(program({}), program({"type_name": "Кирпич 380"}))

    def test_frame_carries_the_program_signature(self):
        """The frame goes out to the person WITH A SIGNATURE, and the
        signature addresses the showroom."""
        sent: list[dict] = []

        async def scenario():
            async def transport(device_id, payload):
                sent.append(payload)
            S.bind_transport(transport)
            S.attach("dev")
            S.publish(device_id="dev", program={
                "ir_version": "1.0", "intent": "стена",
                "ops": [LEVEL, WALL]})
            await S.drain()

        asyncio.run(scenario())
        self.assertTrue(sent, "кадр обязан доехать")
        frame = sent[-1]
        self.assertTrue(frame["transferable"])
        self.assertEqual(len(frame["program_digest"]), 64)
        self.assertEqual(frame["program_count"], 1)
        self.assertEqual(frame["program_ops"], 2)
        # And the signature really does reach the BODY.
        body = T.redeem(KEY, frame["program_digest"])
        self.assertEqual(body, [[LEVEL, WALL]])

    def test_what_was_seen_is_what_is_built(self):
        """Signature equality — that IS the law, expressed as a value."""
        entry = self.shown(_pack([LEVEL, WALL, DOOR]))
        decision = T.authorize(KEY, digest=entry.digest)
        self.assertIs(decision.status, T.Status.READY)
        self.assertEqual(decision.transfer_digest, decision.requested_digest)
        self.assertEqual(T.redeem(KEY, decision.transfer_digest),
                         [[LEVEL, WALL, DOOR]])

    def test_substituted_program_is_refused_and_names_the_gap(self):
        """THE WAVE'S MAIN TEST. A substituted program does not transfer.

        The substitution here isn't "caught by comparison" — it is
        UNSPEAKABLE: the panel has no way to name a program the server
        never showed. A forgery's signature simply addresses nothing.
        """
        entry = self.shown(_pack([LEVEL, WALL]))
        tampered = dict(WALL, p1_mm=[60000.0, 0.0])          # 6m -> 60m
        forged = SR.program_digest(
            (SR.canonical_program([LEVEL, tampered]),),
            entry.context_json, entry.level)
        self.assertNotEqual(forged, entry.digest)

        decision = T.authorize(KEY, digest=forged)
        self.assertIs(decision.status, T.Status.REFUSED)
        self.assertIs(decision.refusal, T.Refusal.NOT_SHOWN)
        self.assertIn("не показывал", decision.refusal_ru)
        # The refusal NAMES what the server remembers — otherwise it is
        # useless.
        self.assertEqual(decision.diverged,
                         (f"Этаж 1={entry.digest[:16]}",))
        self.assertIsNone(T.redeem(KEY, forged), "тела у подделки нет")

    def test_store_corruption_is_typed_and_names_both_digests(self):
        """The second line of defense: the signature is recomputed FROM
        WHAT'S STORED before being issued."""
        entry = self.shown(_pack([LEVEL, WALL]))
        room = SR._ROOMS[KEY]                                # noqa: SLF001
        broken = SR.Shown(
            digest=entry.digest, level=entry.level, seq=entry.seq, ts=entry.ts,
            programs_json=(SR.canonical_program([LEVEL, dict(WALL, id="ПОДМЕНА")]),),
            context_json=entry.context_json, census=entry.census)
        room.frames[entry.digest] = broken

        decision = T.authorize(KEY, digest=entry.digest)
        self.assertIs(decision.refusal, T.Refusal.STORE_CORRUPT)
        self.assertEqual(len(decision.diverged), 2)
        self.assertIn("подписано", decision.diverged[0])
        self.assertIn("хранится", decision.diverged[1])
        self.assertIsNone(T.redeem(KEY, entry.digest),
                          "испорченный кадр не выдаётся исполнителю")

    def test_executor_body_never_arrives_from_the_panel(self):
        """STRUCTURALLY: the program body comes from the showroom, not
        from the message.

        Checked by an `ast` traversal, not by eye: the transfer handler
        in `chat_ws` has no right to read anything out of the incoming
        dict except the signature, the selection, and the confirmation
        flag. Let it read `ops` even once, and the law turns into a
        gentlemen's agreement.
        """
        chat_ws_src = HOST_ROOT / "kukai/api/chat_ws.py"
        if not chat_ws_src.is_file():
            self.skipTest(
                f"чат-дверь живёт у ХОЗЯИНА ({chat_ws_src}) — что именно она "
                f"читает из словаря, здесь непроверяемо. Корень: KIR_HOST_ROOT")
        source = chat_ws_src.read_text(encoding="utf-8")
        tree = ast.parse(source)
        handler = next(
            (node for node in ast.walk(tree)
             if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
             and node.name == "_handle_kir_transfer"), None)
        self.assertIsNotNone(handler, "обработчик переноса не найден")

        read: set[str] = set()
        for node in ast.walk(handler):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "data"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)):
                read.add(str(node.args[0].value))
            if (isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "data"
                    and isinstance(node.slice, ast.Constant)):
                read.add(str(node.slice.value))
        self.assertTrue(read, "обработчик обязан хоть что-то читать из data")
        self.assertEqual(
            read - {"digest", "selection", "confirm", "type"}, set(),
            f"из панели читается лишнее: {sorted(read)} — тело программы "
            f"обязано приходить ТОЛЬКО из витрины по подписи")


# ─────────────────────────────────────────────────────────────────────────────
# §2. THE SECOND LAW: the subset is closed under dependencies
# ─────────────────────────────────────────────────────────────────────────────

class ClosureTests(_Base):

    def test_door_alone_is_grown_to_its_host_and_the_growth_is_named(self):
        entry = self.shown(_pack([LEVEL, WALL, DOOR]))
        decision = T.authorize(KEY, digest=entry.digest, selection=["D3"])

        self.assertIs(decision.status, T.Status.NEEDS_CONFIRM)
        self.assertEqual([a.op_id for a in decision.added], ["LV", "W1"])
        by_id = {a.op_id: a for a in decision.added}
        self.assertEqual((by_id["W1"].needed_by, by_id["W1"].via), ("D3", "host"))
        self.assertEqual((by_id["LV"].needed_by, by_id["LV"].via), ("W1", "level"))
        self.assertIn("его требует «D3» (поле host)",
                      by_id["W1"].to_dict()["ru"])
        # The program's order is preserved: a ref must look BACKWARD.
        self.assertEqual([op["id"] for op in
                          T.redeem(KEY, decision.transfer_digest)[0]],
                         ["LV", "W1", "D3"])

    def test_grown_pack_needs_its_own_signature_before_it_can_be_built(self):
        """Growing-out is NOT executed silently: the grown batch has its
        own signature.

        The program is deliberately wider than the selection: the
        closure yields its OWN subset, and its signature must differ
        from the sheet's signature.
        """
        other = dict(WALL, id="W2", p0_mm=[0.0, 5000.0], p1_mm=[6000.0, 5000.0])
        entry = self.shown(_pack([LEVEL, WALL, DOOR, other]))
        grown = T.authorize(KEY, digest=entry.digest, selection=["D3"])
        self.assertIs(grown.status, T.Status.NEEDS_CONFIRM)
        self.assertNotEqual(grown.transfer_digest, grown.requested_digest)
        self.assertEqual([a.op_id for a in grown.added], ["LV", "W1"])

        # The second request carries the NEW signature — only then is
        # the status READY.
        confirmed = T.authorize(KEY, digest=grown.transfer_digest)
        self.assertIs(confirmed.status, T.Status.READY)
        self.assertEqual(confirmed.transfer_digest, grown.transfer_digest)
        self.assertEqual(confirmed.added, ())
        self.assertEqual([op["id"] for op in
                          T.redeem(KEY, confirmed.transfer_digest)[0]],
                         ["LV", "W1", "D3"])

    def test_growth_to_the_whole_program_still_asks_for_confirmation(self):
        """The closure grew to cover the WHOLE program — the signature
        matched the sheet, but what was added is still named, and the
        status is still `needs_confirm`.

        Otherwise "the signature is the same" would become a loophole:
        the person highlighted a door, and three operations got built,
        and nobody told them."""
        entry = self.shown(_pack([LEVEL, WALL, DOOR]))
        grown = T.authorize(KEY, digest=entry.digest, selection=["D3"])
        self.assertEqual(grown.transfer_digest, grown.requested_digest)
        self.assertIs(grown.status, T.Status.NEEDS_CONFIRM)
        self.assertEqual([a.op_id for a in grown.added], ["LV", "W1"])

    def test_selecting_a_wall_alone_grows_only_its_level(self):
        """There is no reverse edge: a wall doesn't need its door."""
        entry = self.shown(_pack([LEVEL, WALL, DOOR]))
        decision = T.authorize(KEY, digest=entry.digest, selection=["W1"])
        ids = [op["id"] for op in T.redeem(KEY, decision.transfer_digest)[0]]
        self.assertEqual(ids, ["LV", "W1"])
        self.assertNotIn("D3", ids)

    def test_closure_reads_the_registry_not_a_list_of_field_names(self):
        """PARITY WITH THE COMPILER across the WHOLE registry, not on a
        couple of examples.

        For every operation in the registry, a synthetic op is built
        where EVERY parameter capable of carrying a reference does carry
        one. `refs_of` must return exactly the fields that
        `compiler.py:610-619` would collect. A list of field names
        ("host", "level", "wall") would diverge from the registry on the
        very first new operation — and would diverge silently.
        """
        from kir import spec

        checked = 0
        for name, ospec in spec.OPS.items():
            op: dict = {"op": name, "id": "X"}
            expected: list[tuple[str, str]] = []
            for param in ospec.params:
                if not param.ref_kinds:
                    continue
                if param.kind in ("sel", "target_w"):
                    op[param.name] = {"by": "ref", "value": f"R_{param.name}"}
                    expected.append((param.name, f"R_{param.name}"))
                elif param.kind == "refs_w":
                    op[param.name] = [{"by": "ref", "value": f"R_{param.name}"}]
                    expected.append((f"{param.name}[0]", f"R_{param.name}"))
            if not expected:
                continue
            checked += 1
            self.assertEqual(sorted(T.refs_of(op)), sorted(expected),
                             f"{name}: рёбра разошлись с реестром")
        self.assertGreater(checked, 5,
                           "реестр обязан содержать ссылочные операции")

    def test_closure_does_not_cross_program_boundaries(self):
        """There are no `ref` edges BETWEEN programs in the batch — none
        are invented.

        THE BOUNDARY IS NAMED HONESTLY. A program whose `ref` points
        outward is invalid EVEN WITHOUT a selection — `compiler` rejects
        it with code KIR-L003. The closure neither pulls in such a
        reference nor "fixes" it: a second copy of the rule "where a ref
        may point" would diverge from the first. The compiler is the
        judge, and the preflight decision check shows its verdict
        OFFLINE — before the device.
        """
        entry = self.shown(_pack([LEVEL, WALL], [dict(LEVEL), DOOR]))
        decision = T.authorize(KEY, digest=entry.digest, selection=["D3"])
        body = T.redeem(KEY, decision.transfer_digest)
        self.assertEqual(len(body), 1, "программа без выделенного не едет")
        # W1 lives in a NEIGHBORING program: pulling it in here would
        # mean setting up an edge that doesn't exist in the language
        # (the compiler resolves a ref within a single one).
        self.assertEqual([op["id"] for op in body[0]], ["D3"])
        self.assertTrue(decision.preflight,
                        "висячий ref обязан быть назван ОФЛАЙН, а не на устройстве")
        self.assertTrue(any("KIR-L003" in line for line in decision.preflight),
                        decision.preflight)

    def test_empty_selection_is_a_named_refusal_not_a_silent_whole(self):
        entry = self.shown(_pack([LEVEL, WALL]))
        decision = T.authorize(KEY, digest=entry.digest, selection=[])
        self.assertIs(decision.refusal, T.Refusal.SELECTION_EMPTY)

    def test_selection_from_another_frame_is_refused_by_name(self):
        entry = self.shown(_pack([LEVEL, WALL]))
        decision = T.authorize(KEY, digest=entry.digest, selection=["D3", "W9"])
        self.assertIs(decision.refusal, T.Refusal.SELECTION_UNKNOWN)
        self.assertEqual(decision.diverged, ("D3", "W9"))

    def test_over_budget_programs_are_named_before_revit_is_touched(self):
        """A program's length is measured OFFLINE: finding this out on
        the device costs a round trip through the most expensive
        resource."""
        from kir.compiler import MAX_OPS_PER_PROGRAM
        many = [LEVEL] + [dict(WALL, id=f"W{i}") for i in range(MAX_OPS_PER_PROGRAM)]
        entry = self.shown(_pack(many))
        decision = T.authorize(KEY, digest=entry.digest)
        self.assertTrue(decision.over_budget)
        self.assertIn(str(MAX_OPS_PER_PROGRAM), decision.over_budget[0])


# ─────────────────────────────────────────────────────────────────────────────
# §3. THE CENSUS
# ─────────────────────────────────────────────────────────────────────────────

class CensusTests(_Base):

    def test_frame_carries_the_census_in_full_russian_lines(self):
        sent: list[dict] = []

        async def scenario():
            async def transport(device_id, payload):
                sent.append(payload)
            S.bind_transport(transport)
            S.attach("dev")
            S.publish(device_id="dev", program={
                "ir_version": "1.0", "intent": "перепись",
                # create_room is drawn as a point (an approximation), and
                # create_level isn't visible on the plan at all — both
                # lines must arrive as text.
                "ops": [LEVEL, WALL,
                        {"op": "create_room", "id": "R1", "xy_mm": [1000.0, 1000.0],
                         "level": {"by": "ref", "value": "LV"}}]})
            await S.drain()

        asyncio.run(scenario())
        frame = sent[-1]
        lines = frame["census_lines"]
        self.assertTrue(lines, "перепись обязана ехать рядом с картинкой")
        self.assertTrue(all(line["ru"] and line["ru"] != line["reason"]
                            for line in lines),
                        "каждая строка переписи обязана быть по-русски")
        groups = (len(frame["census"]["omitted"]) + len(frame["census"]["approx"])
                  + len(frame["census"]["anomalies"]))
        self.assertEqual(len(lines), groups, "перепись едет ЦЕЛИКОМ, без срезов")

    def test_decision_census_is_about_the_transfer_not_the_sheet(self):
        entry = self.shown(_pack([LEVEL, WALL, DOOR]))
        whole = T.authorize(KEY, digest=entry.digest)
        part = T.authorize(KEY, digest=entry.digest, selection=["W1"])
        self.assertGreater(whole.census["considered"], part.census["considered"],
                           "перепись решения обязана считать переносимое")

    def test_sheet_names_every_truncation_of_the_census(self):
        """A REFUTING MEASUREMENT (04.08, before the fix): the basement
        printed 5 of 7 approximation lines, 4 of 5 anomalies, and 4 of 6
        blind spots — and said nothing about it. A silent census is
        exactly the class of defect `PreviewCensus` was written to
        forbid in the first place."""
        from kir import preview as P

        census = P.PreviewCensus(
            considered=len(list(P.OmitReason)), drawn=0,
            omitted=tuple(P.OmissionGroup(reason=r, category=f"c{i}", count=1)
                          for i, r in enumerate(P.OmitReason)),
            approx=tuple(P.ApproxGroup(reason=r, count=1)
                         for r in P.ApproxReason),
            anomalies=tuple(P.AnomalyGroup(reason=r, count=1)
                            for r in P.AnomalyReason))
        # THE INSTRUMENT'S SHEET: a pin about the basement being
        # truncated, while the basement is now addressed to the
        # instrument (08.09 — the person keeps the drawing and one line).
        svg = P.render_svg(P.FloorPlan(
            source=P.PreviewSource.PROGRAM, doc_name="d", level_name="L1",
            level_elevation_mm=0.0, elements=(), census=census),
            audience="instrument")
        for what in ("строк(и) причин", "строк(и) приближений",
                     "строк(и) аномалий", "вид(а) слепоты"):
            self.assertIn(what, svg, f"урезание не названо: {what}")
        # And the full text is available to the recipient with no
        # truncation at all.
        self.assertEqual(len(P.census_lines(census)),
                         len(census.omitted) + len(census.approx)
                         + len(census.anomalies))


# ─────────────────────────────────────────────────────────────────────────────
# §4. REACHABILITY AND BOUNDARIES
# ─────────────────────────────────────────────────────────────────────────────

from kir.tests.host_entry_points import live_or_named_skip  # noqa: E402


def _graph():
    # The instrument moved INTO THE PACKAGE during the split — it no
    # longer needs `sys.path`.
    from kir.instruments import capability_graph  # noqa: WPS433

    return capability_graph.Graph(BACKEND)


def _live_or_skip(case, graph):
    """`graph.live()` — or a NAMED skip, if there's no one to ask.

    🔴 "Liveness" rests on the HOST's entry points, and those start at
    `kukai.main` — a PRODUCT unit. A standalone KIR has no such module,
    `reachable` honestly returns empty, and "the module is unreachable
    from the prod process — the code is dark" would read as a finding
    ABOUT THE MODULE. What's dead is not the module but the question:
    there is no prod process here at all.

    🔴 FIX 01.09.2026: the entry-point names are no longer in the
    package — the host names them through a port. The assertion
    "reachable from the PROD process" is a fact about the PRODUCT, so
    the test itself declares the configuration, not the language.
    """
    return live_or_named_skip(case, graph)


class ReachabilityTests(unittest.TestCase):

    def test_transfer_is_reachable_from_the_prod_process(self):
        """A FLAG ≠ REACHABILITY. We measure with an instrument, not by
        grepping imports."""
        live = _live_or_skip(self, _graph())
        for module in ("kir.live.showroom", "kir.live.transfer"):
            self.assertIn(module, live,
                          f"{module} не достижим из прод-процесса — код тёмный")

    def test_showroom_keeps_the_stream_one_way(self):
        """The showroom is filled by the RENDERER, so it must remain a
        sheet.

        Give it a path into the compiler, and the one-way flow proven by
        `test_live_plan_stream.py` would become false via `plan_stream`
        -> `showroom` -> …. The return lives in `transfer.py` FOR
        EXACTLY THIS REASON.
        """
        graph = _graph()
        module = graph.modules["kir.live.showroom"]
        edges = module.imports | module.dynamic_imports
        self.assertEqual([e for e in edges if e.startswith("kukai.")], [],
                         "витрина обязана быть stdlib-листом")

    def test_transfer_is_not_imported_by_the_drawing_path(self):
        graph = _graph()
        for name in ("kir.live.plan_stream", "kir.live.journal",
                     "kir.live.showroom"):
            module = graph.modules[name]
            self.assertNotIn("kir.live.transfer",
                             module.imports | module.dynamic_imports,
                             f"{name} не имеет права знать о возврате")


class BoundednessTests(_Base):

    def test_showroom_is_bounded_and_counts_what_it_forgot(self):
        os.environ["KUKAI_KIR_SHOWROOM_FRAMES"] = "3"
        try:
            digests = [self.shown(_pack([LEVEL, dict(WALL, id=f"W{i}")])).digest
                       for i in range(6)]
        finally:
            os.environ.pop("KUKAI_KIR_SHOWROOM_FRAMES", None)
        stats = SR.stats()
        self.assertEqual(stats["frames"], 3)
        self.assertEqual(stats["evicted"], 3)
        self.assertIsNone(T.redeem(KEY, digests[0]), "вытесненное не выдаётся")
        self.assertIsNotNone(T.redeem(KEY, digests[-1]))
        # And eviction does NOT become a silent substitution: the
        # refusal is typed.
        self.assertIs(T.authorize(KEY, digest=digests[0]).refusal,
                      T.Refusal.NOT_SHOWN)

    def test_disabled_transfer_refuses_by_name(self):
        entry = self.shown(_pack([LEVEL, WALL]))
        os.environ["KUKAI_KIR_TRANSFER"] = "0"
        try:
            self.assertIs(T.authorize(KEY, digest=entry.digest).refusal,
                          T.Refusal.DISABLED)
        finally:
            os.environ.pop("KUKAI_KIR_TRANSFER", None)

    def test_journal_and_stream_survive_a_broken_showroom(self):
        """The showroom breaks — construction doesn't notice, the frame
        still ships."""
        sent: list[dict] = []
        original = SR.show

        async def scenario():
            async def transport(device_id, payload):
                sent.append(payload)
            S.bind_transport(transport)
            S.attach("dev")
            SR.show = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("витрина"))
            try:
                S.publish(device_id="dev", program={
                    "ir_version": "1.0", "intent": "t", "ops": [LEVEL, WALL]})
                await S.drain()
            finally:
                SR.show = original

        asyncio.run(scenario())
        self.assertTrue(sent, "кадр обязан доехать и без витрины")
        self.assertFalse(sent[-1]["transferable"])
        self.assertIn("перенос недоступен", sent[-1]["transfer_blocked_ru"])
        self.assertEqual(S.stats()["showroom_errors"], 1)
        self.assertEqual(J.get(KEY).stats()["programs"], 1,
                         "журнал программ обязан остаться полным")


# ─────────────────────────────────────────────────────────────────────────────
# §5. THE FULL LOOP: frame -> panel -> door
# ─────────────────────────────────────────────────────────────────────────────

class RoundTripTests(_Base):
    """Through the REAL door, `chat_ws._handle_kir_transfer`, not around
    it.

    The `revit_ir` door is substituted: there is no live Revit, and what
    must be proved isn't "Revit built it," but "EXACTLY the operations
    the person saw reached Revit."
    """

    def _drive(self, messages, program):
        """Play back the frame, then feed the panel's messages to the
        door."""
        from kir import ports as _п
        try:
            chat_ws = _п.need(_п.SESSION_CONTEXTS)
        except _п.PortMissing as exc:                    # pragma: no cover
            # The window door is a HOST concept. Without a provider
            # there is nothing to play the frame back on, and that is a
            # SKIP with a cause, not a failure about our own subject.
            self.skipTest("дверь окна — у хоста: " + str(exc))
        from kir import serving

        sent: list[dict] = []
        handed: list[list[dict]] = []

        async def fake_send(ws, payload):
            sent.append(payload)

        async def fake_door(args, llm_client, bridge, query_id="", **_identity):
            handed.append(args["program"]["ops"])
            return {"ok": True, "created": len(args["program"]["ops"])}

        async def scenario():
            async def transport(device_id, payload):
                sent.append(payload)
            S.bind_transport(transport)
            S.attach("dev")
            S.publish(device_id="dev", program=program)
            await S.drain()
            for message in messages(sent):
                await chat_ws._handle_kir_transfer(   # noqa: SLF001
                    message, object(), ws_id="w", device_id="dev")

        old_send, old_door = chat_ws._send_json, serving.handle_revit_ir
        chat_ws._send_json = fake_send
        serving.handle_revit_ir = fake_door
        try:
            asyncio.run(scenario())
        finally:
            chat_ws._send_json = old_send
            serving.handle_revit_ir = old_door
        return sent, handed

    def test_what_the_panel_saw_is_byte_for_byte_what_reaches_the_door(self):
        program = {"ir_version": "1.0", "intent": "круг",
                   "ops": [LEVEL, WALL, DOOR]}
        sent, handed = self._drive(
            lambda s: [{"type": "kir_transfer",
                        "digest": s[-1]["program_digest"], "confirm": True}],
            program)
        frame = sent[0]
        self.assertTrue(frame["transferable"])
        self.assertEqual(handed, [[LEVEL, WALL, DOOR]],
                         "до двери обязаны доехать РОВНО показанные операции")
        result = [m for m in sent if m.get("type") == "kir_transfer_result"]
        self.assertTrue(result and result[-1]["ok"])

    def test_forged_digest_is_refused_and_the_door_is_never_called(self):
        """A REFUSAL ON SUBSTITUTION, by measurement, on the live path.

        The panel sends the signature of a program the server never
        showed (a wall stretched from 6m to 60m). The `revit_ir` door is
        never called, NOT ONCE.
        """
        program = {"ir_version": "1.0", "intent": "круг",
                   "ops": [LEVEL, WALL]}

        def messages(sent):
            forged = SR.program_digest(
                (SR.canonical_program([LEVEL, dict(WALL, p1_mm=[60000.0, 0.0])]),),
                SR.canonical_program([LEVEL]), "Этаж 1")
            return [{"type": "kir_transfer", "digest": forged, "confirm": True}]

        sent, handed = self._drive(messages, program)
        self.assertEqual(handed, [], "подделка не имеет права дойти до двери")
        decisions = [m for m in sent if m.get("type") == "kir_transfer_decision"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["status"], "refused")
        self.assertEqual(decisions[0]["refusal"], "not_shown")
        self.assertFalse(decisions[0]["executed"])
        self.assertFalse([m for m in sent
                          if m.get("type") == "kir_transfer_result"])

    def test_first_request_never_builds_even_with_confirm(self):
        """`confirm=true` on a GROWN batch does not build: we name what
        was added first, and only build against its own signature."""
        other = dict(WALL, id="W2", p0_mm=[0.0, 5000.0], p1_mm=[6000.0, 5000.0])
        program = {"ir_version": "1.0", "intent": "круг",
                   "ops": [LEVEL, WALL, DOOR, other]}
        sent, handed = self._drive(
            lambda s: [{"type": "kir_transfer",
                        "digest": s[-1]["program_digest"],
                        "selection": ["D3"], "confirm": True}],
            program)
        self.assertEqual(handed, [], "доращивание не строится с первого клика")
        decision = [m for m in sent
                    if m.get("type") == "kir_transfer_decision"][-1]
        self.assertEqual(decision["status"], "needs_confirm")
        self.assertEqual([a["id"] for a in decision["added"]], ["LV", "W1"])

    def test_confirming_the_grown_signature_builds_exactly_the_closure(self):
        other = dict(WALL, id="W2", p0_mm=[0.0, 5000.0], p1_mm=[6000.0, 5000.0])
        program = {"ir_version": "1.0", "intent": "круг",
                   "ops": [LEVEL, WALL, DOOR, other]}

        def messages(sent):
            grown = T.authorize(KEY, digest=sent[-1]["program_digest"],
                                selection=["D3"])
            return [{"type": "kir_transfer", "digest": grown.transfer_digest,
                     "confirm": True}]

        sent, handed = self._drive(messages, program)
        self.assertEqual(handed, [[LEVEL, WALL, DOOR]])
        self.assertNotIn("W2", [op["id"] for op in handed[0]])


if __name__ == "__main__":
    unittest.main()
