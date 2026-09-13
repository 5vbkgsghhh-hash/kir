"""THE AGREEMENT REGISTRY GUARDS ITSELF.

🔴 THE MAIN QUESTION OF THIS FILE IS NOT "IS IT GREEN," BUT "CAN IT TURN RED
AT ALL." A registry whose agreements are incapable of refusing is the most
expensive kind of green: it gives confidence and gives no protection. This
is a form of defect already on record with us ("a control on a degenerate
input is green by construction," 12.08.2026), and it was paid for here ONE
MORE TIME: the first edition of the `тело_объявляет_помощников` agreement
broke the material with a Cyrillic name, it did not fall under the calling
rule, and the agreement came out empty. The instrument said so itself, on
the very first run.

That is why, below, besides "does it hold on the live tree," every
agreement is also checked AGAINST A HISTORICAL DEFECT: the material
reproduces what happened on 20–21.08.2026, and the judge MUST refuse.
"""
from __future__ import annotations

import unittest

from kir import agreements as AG


class RegistryHoldsOnTheLiveTree(unittest.TestCase):

    def test_every_agreement_holds(self):
        for v in AG.check_all():
            with self.subTest(agreement=v.name):
                self.assertTrue(
                    v.holds,
                    f"согласие «{v.name}» РАЗОШЛОСЬ на живом дереве:\n  "
                    + "\n  ".join(v.detail))

    def test_every_agreement_can_actually_refuse(self):
        """Non-emptiness. The judge MUST refuse on broken material."""
        for v in AG.check_all():
            with self.subTest(agreement=v.name):
                self.assertTrue(
                    v.provable,
                    f"согласие «{v.name}» ПУСТОЕ: судья не отказал на "
                    f"нарочно сломанном материале — его зелёный не значит "
                    f"ничего")

    def test_every_agreement_was_bought_by_an_incident(self):
        """An agreement without an incident is a guess about the future, not protection.

        🔴 The traversal goes over `_registry_roster()`, not over
        `AGREEMENTS` (E-49, 30.08.2026): the guard of the road is itself
        just such an agreement, paid for by just such an incident, and a
        traversal over the tuple would never have asked it.
        """
        for a in AG._registry_roster():
            with self.subTest(agreement=a.name):
                self.assertTrue(a.why.strip(), "поле why пусто")
                self.assertRegex(
                    a.why, r"\d{2}\.\d{2}",
                    f"«{a.name}»: довод не называет ДАТЫ происшествия — "
                    f"значит, скорее всего, происшествия и не было")
                self.assertTrue(a.claim.strip(), "поле claim пусто")

    def test_named_absences_carry_a_reason(self):
        """An empty cell in the registry is named, and named WITH A REASON."""
        self.assertTrue(AG.NAMED_BUT_NOT_BUILT,
                        "список названного-и-незаведённого пуст — это либо "
                        "правда, либо тишина, и второе вероятнее")
        for name, why in AG.NAMED_BUT_NOT_BUILT:
            with self.subTest(absent=name):
                self.assertIn("Не заведено:", why,
                              "названо отсутствие без причины")


class TheRegistryGuardsItsOwnRoad(unittest.TestCase):
    """🔴 THE REGISTRY DID NOT GUARD ITS OWN ROAD (E-49, 30.08.2026).

    The three checks above BYPASS the registry. So an agreement removed
    from the tuple turned red nowhere: the list got shorter, the
    traversals are trivially green. Proven by mutation on the live tree —
    the `состав_подачи_лифту_полон` entry was cut out, its three bodies
    left IN PLACE:

        agreements in the registry: 9 · all hold: True · 31 passed, EXIT=0
        the only trace — 43 subtests became 40, and nobody expects this number

    An instrument written and never wired in — that is `E-7`, and a
    registry set up to catch EXACTLY THIS did not catch it IN ITSELF.
    """

    def test_the_road_guard_is_on_the_live_path(self):
        """The guard of the road itself MUST REACH the run.

        Otherwise it is exactly what it was set up against: an instrument
        written and not wired in. What is asked is the OUTPUT of
        `check_all` — that is, the path by which the 6/6 gate and all
        three checks above see the registry — not the presence of a
        constant in the module.
        """
        names = [v.name for v in AG.check_all()]
        self.assertIn(AG.REGISTRY_ROAD.name, names,
                      "сторож дороги построен и НЕ ДОЕЗЖАЕТ до check_all — "
                      "это ровно тот дефект, против которого он заведён")
        self.assertEqual(
            len(names), len(AG.AGREEMENTS) + 1,
            "прогон спрашивает не весь реестр: между AGREEMENTS и check_all "
            "потерялись согласия")

    def test_an_agreement_cut_from_the_tuple_is_caught(self):
        """THAT VERY SAME incident: the entry cut out, the bodies left in place.

        The material is forged, the tree is not touched — this is exactly
        why the agreement has three parts, not one.
        """
        material = AG._gather_registry_road()
        self.assertIn("_judge_lift_feed", material["built"],
                      "зонд не видит тел — подделывать нечего")
        material["wired"] = [n for n in material["wired"]
                             if n not in ("_judge_lift_feed",
                                          "_break_lift_feed")]
        bad = AG._judge_registry_road(material)
        self.assertTrue(bad, "судья не заметил согласия, выключенного одной "
                             "строкой в кортеже")
        self.assertIn("_judge_lift_feed", " ".join(bad),
                      "отказ обязан назвать ТЕЛО, иначе следующий пойдёт "
                      "искать его сам")

    def test_the_healthy_tree_is_accepted(self):
        """The second outcome. A guard that always turns red guards nothing."""
        self.assertEqual(AG._judge_registry_road(AG._gather_registry_road()),
                         [])

    def test_an_empty_walk_is_a_refusal_not_a_pass(self):
        """The denominator on its own line: an empty traversal is an answer
        ABOUT THE PROBE.

        Without this branch, "nothing was lost" would be green by
        construction — the same defect form that once had a neighboring
        agreement printing a verdict about an unread corpus.
        """
        bad = AG._judge_registry_road({"built": [], "wired": []})
        self.assertTrue(bad)
        self.assertIn("О ЗОНДЕ", bad[0])

    def test_an_exception_without_a_reason_is_refused(self):
        """An exception is a way to NAME a decision, not to bypass the instrument."""
        AG.BODIES_OFF_THE_REGISTRY["_judge_вымышленный"] = "потом"
        try:
            bad = AG._judge_registry_road(
                {"built": ["_judge_вымышленный"] * 20, "wired": []})
        finally:
            del AG.BODIES_OFF_THE_REGISTRY["_judge_вымышленный"]
        self.assertTrue(any("без довода" in s for s in bad), bad)

    def test_a_ghost_exception_is_refused(self):
        """The list moves in ONE direction: the line is removed by whoever fixed it.

        A permit for a body that has already reached the registry is a
        lie — and the quietest kind of lie at that: it stays silent
        exactly where there is nothing left to guard.
        """
        AG.BODIES_OFF_THE_REGISTRY["_judge_lift_feed"] = (
            "довод длиной более тридцати знаков, чтобы сработала другая ветка")
        try:
            bad = AG._judge_registry_road(AG._gather_registry_road())
        finally:
            del AG.BODIES_OFF_THE_REGISTRY["_judge_lift_feed"]
        self.assertTrue(any("вычеркни" in s for s in bad), bad)

    def test_the_exception_list_is_empty_and_that_is_not_silence(self):
        """Empty today — and it MUST remain empty without a recorded argument."""
        for name, why in AG.BODIES_OFF_THE_REGISTRY.items():
            with self.subTest(body=name):
                self.assertGreaterEqual(
                    len(str(why).strip()), 30,
                    "исключение без разбора — ярлык, а не знание")


class AnUndeliveredBodyIsNamedNotSwallowed(unittest.TestCase):
    """🔴 THE BUILDER SILENTLY SWALLOWED THE FAILURE, AND THE JUDGE JUDGED
    ONLY WHAT ARRIVED (E-50).

    `build_all` carries `except Exception: continue` and a second silent
    skip — `if revit_version is None: continue` on the versioned body.
    Both DROP the name from the result. The judge decompiled only what
    arrived and never once cross-checked against the `READ_BODY_ARGS`
    table: a body that stopped building fell out of BOTH halves of the
    question at once, and the agreement came out consistent — honestly,
    about what remained.

    Measured 30.08.2026 (by execution): traversing 20 builders,
    `READ_BODY_ARGS` gives 18, 2 fragments; `build_all` on each of the six
    versions returns 18 of 18, while WITHOUT a version it returns 17 of
    18, silently losing `build_tag_extract_cs`. That is, along the
    agreement's path the debt today is ZERO, and the guard is deliberately
    set up on that zero.
    """

    def test_the_live_ledger_is_complete_today(self):
        """The table and what arrived matched — and this is a NUMBER, not an impression."""
        from kir.decompile.read_bodies import READ_BODY_ARGS
        material = AG._gather_cs_bodies()
        absent = sorted(n for n in material
                        if n.startswith((AG._CS_UNCOVERED,
                                         AG._CS_UNDELIVERED)))
        self.assertEqual(absent, [], "объявленное не доехало до материала")
        self.assertEqual(
            len(material), len(READ_BODY_ARGS),
            "материал согласия и ведомость сборщика разошлись числом")

    def test_a_body_that_never_arrives_is_named_by_the_gather(self):
        """🔴 THE ROAD, NOT THE JUDGE: it is the REAL call that is intercepted.

        Checking the judge against a forged dictionary would prove that it
        IS ABLE to refuse, not that the loss REACHES it. There is a road
        between the table and the judge, and it is that road that must be
        guarded (the tenth form of a worthless control).

        The substitution is placed on the MODULE and is visible to the
        consumer only because `_gather_cs_bodies` takes the name INSIDE the
        function, not at import time; were it otherwise, the discriminator
        would honestly have printed "nothing changed".
        """
        from kir.decompile import read_bodies as RB
        real = RB.build_all
        calls = []

        def _swallowing(*args, **kwargs):
            calls.append(1)
            out = real(*args, **kwargs)
            out.pop("build_metadata_cs", None)
            return out

        RB.build_all = _swallowing
        try:
            material = AG._gather_cs_bodies()
        finally:
            RB.build_all = real
        self.assertEqual(len(calls), 1,
                         "замер не состоялся: подменённый сборщик не звался")
        self.assertIn(AG._CS_UNDELIVERED + "build_metadata_cs", material)
        bad = AG._judge_cs_bodies(material)
        self.assertTrue(
            any("build_metadata_cs" in s and "НЕ ДОЕХАЛ" in s for s in bad),
            bad)

    def test_an_undelivered_name_is_a_different_kind_than_an_uncovered_one(self):
        """The kinds do not merge: their next turn differs."""
        undelivered = AG._judge_cs_bodies({AG._CS_UNDELIVERED + "b": ""})
        uncovered = AG._judge_cs_bodies({AG._CS_UNCOVERED + "b": ""})
        self.assertTrue(undelivered)
        self.assertTrue(uncovered)
        self.assertNotEqual(undelivered, uncovered,
                            "«не назван» чинится записью в ведомость, «не "
                            "доехал» — разбором падения сборщика")

    def test_the_break_touches_a_real_body_and_not_an_absence(self):
        """Non-emptiness MUST be proven by the very branch it was set up for.

        The name of the absence refuses ON ITS OWN. Breaking it would give
        us a green `provable` for a different reason — a control run
        honestly and still empty.
        """
        material = {AG._CS_UNDELIVERED + "x": "",
                    "build_z_cs": "Func<int,int> __A = (__v) => __v;\n"}
        broken = AG._break_cs_bodies(dict(material))
        self.assertEqual(broken[AG._CS_UNDELIVERED + "x"], "",
                         "мутация тронула имя отсутствия, а не тело")
        self.assertNotEqual(broken["build_z_cs"], material["build_z_cs"],
                            "мутация не состоялась: тело не изменилось")
        self.assertTrue(AG._judge_cs_bodies(
            {"build_z_cs": broken["build_z_cs"]}),
            "судья не отказал на сломанном ТЕЛЕ")


class TheHistoricalDefectsAreCaught(unittest.TestCase):
    """Every agreement stands against THAT VERY SAME defect that paid for it."""

    def test_refusal_text_that_lies_about_its_own_threshold(self):
        """21.08: the threshold is 100 mm², the text says "< 0.01 m²" = 10,000 mm²."""
        material = [{"site": "исторический", "ladder": "area",
                     "threshold": 100.0,
                     "text": "outline: вырожденный контур (площадь < 0.01 м²)"}]
        bad = AG._judge_refusals(material)
        self.assertTrue(bad, "судья не заметил стократного расхождения")
        self.assertIn("100 раз", bad[0])

    def test_refusal_text_that_names_no_threshold_at_all(self):
        material = [{"site": "исторический", "ladder": "area",
                     "threshold": 100.0,
                     "text": "outline: вырожденный контур"}]
        self.assertTrue(AG._judge_refusals(material))

    def test_refusal_text_that_carries_its_threshold_is_accepted(self):
        material = [{"site": "верный", "ladder": "area", "threshold": 100.0,
                     "text": "outline: вырожденный контур — площадь ниже "
                             "100 мм²"}]
        self.assertEqual(AG._judge_refusals(material), [])

    def test_cs_body_calling_an_undeclared_helper(self):
        """20.08: __RouteSkips is called by shared helpers, only one of the two declares it."""
        body = ("Func<double, double> __MM = (__value) => __value * 304.8;\n"
                "if (__RouteSkips(__name)) return;\n"
                "__MM(1.0);\n")
        bad = AG._judge_cs_bodies({"build_reextract_cs": body})
        self.assertTrue(bad, "судья не заметил незаявленного помощника")
        self.assertIn("__RouteSkips", bad[0])

    def test_cs_body_declaring_what_it_calls_is_accepted(self):
        body = ("Func<string, bool> __RouteSkips = (__name) => false;\n"
                "if (__RouteSkips(__name)) return;\n")
        self.assertEqual(AG._judge_cs_bodies({"b": body}), [])

    def test_uncovered_read_body_is_a_refusal(self):
        self.assertTrue(AG._judge_cs_bodies({"!НЕПОКРЫТ:build_new_cs": ""}))

    def test_snapshot_reader_asking_about_gz_and_reading_bare(self):
        """21.08: five readers of the course — the check knows about .gz, the reading does not."""
        src = ("def read_lesson(path):\n"
               "    if not snapshot_file_exists(path):\n"
               "        return None\n"
               "    with open(path, encoding='utf-8') as fh:\n"
               "        return fh.read()\n")
        rows = AG.analyse_snapshot_source(src, "курс.py")
        self.assertEqual(rows[0]["collision"], ["path"])
        self.assertTrue(AG._judge_snapshot_readers(rows))

    def test_a_different_file_opened_bare_is_not_a_defect(self):
        """🔴 THE BOUNDARY PAID FOR BY A FALSE ALARM ON 22.08.

        `program_source.floor_source` reads the snapshot through
        `open_snapshot` and takes `passport.md`, which is never compressed,
        with a bare `open`. A crude rule called this a defect. A false
        alarm costs more than a miss: it kills trust in the entire registry.
        """
        src = ("import os\n"
               "def floor_source(run_dir, path):\n"
               "    if not snapshot_file_exists(path):\n"
               "        return None\n"
               "    with open_snapshot(path, 'rt') as fh:\n"
               "        tree = fh.read()\n"
               "    with open(os.path.join(run_dir, 'passport.md')) as fh:\n"
               "        return fh.read()\n")
        rows = AG.analyse_snapshot_source(src, "program_source.py")
        self.assertEqual(rows[0]["collision"], [])
        self.assertEqual(AG._judge_snapshot_readers(rows), [])

    def test_two_classifiers_diverging_on_shared_prose(self):
        """21.08: "cancelled before start" was known to one path out of two."""
        material = [{"prose": "Execution was cancelled before Revit started it",
                     "shared": True,
                     "expected": "ErrCode.TRANSPORT_CANCELLED",
                     "bridge": "ErrCode.RUNTIME_REVIT_EXCEPTION",
                     "execution": "ErrCode.TRANSPORT_CANCELLED"}]
        self.assertTrue(AG._judge_classifiers(material))

    def test_legal_divergence_is_not_reported(self):
        """"not connected" is a transport state; the execution path does not see it."""
        material = [{"prose": "Bridge not connected", "shared": False,
                     "why": "состояние транспорта ДО отправки",
                     "expected": "ErrCode.TRANSPORT_BRIDGE_DISCONNECTED",
                     "bridge": "ErrCode.TRANSPORT_BRIDGE_DISCONNECTED",
                     "execution": "ErrCode.RUNTIME_REVIT_EXCEPTION"}]
        self.assertEqual(AG._judge_classifiers(material), [])

    def test_new_twin_without_a_disposition_is_refused(self):
        """Ratchet: the old is not fixed, the new is not introduced silently."""
        bad = AG._judge_twins({"НОВЫЙ_ПОРОГ": {"a.py": 1.0, "b.py": 1.0}})
        self.assertTrue(bad)
        self.assertIn("TWIN_DISPOSITIONS", bad[0])

    def test_twin_declared_one_quantity_must_not_diverge(self):
        bad = AG._judge_twins({"MIN_EXTENT_MM": {"a.py": 1.0, "b.py": 100.0}})
        self.assertTrue(bad)
        self.assertIn("разошлись", bad[0])

    def test_a_constant_reaching_a_NEW_parameter_is_refused(self):
        """21.08: MIN_EXTENT is measured on the PROFILE side, applied to HEIGHT.

        It is enough for someone to set `min_val=THE_SAME_CONSTANT` on a new
        parameter, and the limit silently gains power over a quantity it was
        never asked about.
        """
        bad = AG._judge_scope(
            {"MIN_EXTENT_MM": {("height_mm", "min_val"),
                               ("новая_величина_мм", "min_val")}})
        self.assertTrue(bad)
        self.assertIn("новая_величина_мм", bad[0])
        self.assertIn("Мерено на:", bad[0],
                      "отказ обязан напомнить, НА ЧЁМ константа мерена — "
                      "иначе читатель пойдёт искать это сам")

    def test_an_undisposed_constant_is_refused(self):
        bad = AG._judge_scope({"НОВАЯ_КОНСТАНТА": {("x_mm", "max_val")}})
        self.assertTrue(bad)
        self.assertIn("CONSTANT_SCOPE", bad[0])

    def test_the_declared_scope_is_accepted(self):
        self.assertEqual(
            AG._judge_scope({"MIN_EXTENT_MM": {("height_mm", "min_val")}}), [])

    def test_every_scope_names_what_it_was_measured_on(self):
        """An aggregate without a measurement is a declaration, not knowledge."""
        for name, scope in AG.CONSTANT_SCOPE.items():
            with self.subTest(constant=name):
                self.assertTrue(scope.measured_on.strip())
                self.assertTrue(scope.governs, "область власти пуста")

    def test_twin_declared_namesakes_may_diverge(self):
        self.assertEqual(
            AG._judge_twins({"_CACHE_MAX": {"a.py": 8, "b.py": 2}}), [])

    # ── AGREEMENT 8: THE CONTRACT DOES NOT LIE ABOUT READING ──────────────────────────

    def test_a_contract_calling_capture_blind_while_capture_calls_it(self):
        """18.08: "zero occurrences" was written 16 minutes after the reading.

        🔴 THE DISPOSITION HAS TO BE REMOVED, AND THIS IS NOT A TRICK, IT IS
        THE POINT OF THE CHECK. Today this call is DECOMPILED, so the judge
        is legitimately silent. The test asks a different question: "what
        stands between us and the incident". The answer is exactly the line
        in `CALLED_MEMBER_DISPOSITIONS`, and it is verified by removing it,
        not by retelling it.
        """
        key = ("join_elements", "JoinGeometryUtils.GetJoinedElements")
        self.assertIn(key, AG.CALLED_MEMBER_DISPOSITIONS,
                      "вызов, который захват делает, обязан быть разобран")
        material = [{
            "op": "join_elements", "mode": "capture_gap",
            "member": key[1],
            "call_sites": ["kir/decompile/join_extract.py:823"],
        }]
        self.assertEqual(AG._judge_capture_claims(material), [],
                         "разобранный вызов обязан молчать")

        disposed = AG.CALLED_MEMBER_DISPOSITIONS.pop(key)
        try:
            bad = AG._judge_capture_claims(material)
        finally:
            AG.CALLED_MEMBER_DISPOSITIONS[key] = disposed
        self.assertTrue(bad, "судья не заметил лжи про чтение")
        self.assertIn("join_extract.py:823", bad[0],
                      "отказ обязан назвать МЕСТО вызова, иначе следующий "
                      "пойдёт искать его сам")

    def test_the_same_form_for_author_family(self):
        """21.08, a second incident of the same form."""
        material = [{
            "op": "author_family", "mode": "capture_gap",
            "member": "FamilyInstance.GetAssociatedFamilyParameter",
            "call_sites": ["kir/decompile/family_recipe.py:1987"],
        }]
        self.assertTrue(AG._judge_capture_claims(material))

    def test_a_disposed_member_is_accepted(self):
        """Ratchet: a decompiled call stays silent, a new one does not."""
        member = "ExtrusionRoof.GetProfile"
        self.assertIn(("create_extrusion_roof", member),
                      AG.CALLED_MEMBER_DISPOSITIONS)
        material = [{"op": "create_extrusion_roof", "mode": "capture_gap",
                     "member": member, "call_sites": ["x.py:1"]}]
        self.assertEqual(AG._judge_capture_claims(material), [])

    def test_a_member_capture_never_calls_is_not_a_defect(self):
        """A named absence MUST remain green.

        The cut order (`SwitchJoinOrder`) is NOT READ by the capture AT
        ALL, and the `join_elements` contract says so directly. An
        instrument that screams at a correct entry lives a week.
        """
        material = [{"op": "join_elements", "mode": "composed",
                     "member": "JoinGeometryUtils.SwitchJoinOrder",
                     "call_sites": []}]
        self.assertEqual(AG._judge_capture_claims(material), [])

    def test_empty_material_is_a_refusal_not_a_pass(self):
        self.assertTrue(AG._judge_capture_claims([]))

    def test_prose_is_not_a_call_and_emitted_cs_is(self):
        """🔴 THE BOUNDARY PAID FOR BY TWO FALSE ALARMS DURING CALIBRATION.

        Without a constraint on the RECEIVER, the rule counted the prose
        line `FlexDuct.Points (IList<XYZ>, 6/6)` as a call — it too has a
        dot, a name, and a parenthesis. In this tree the receiver of
        emitted C# is either our local `__что-то`, or the full name
        `Autodesk.…`, and this convention is upheld by agreement 2.
        """
        prose = {"lift.py": '"path": ("FlexDuct.Points (IList<XYZ>, 6/6)")'}
        self.assertEqual(AG.capture_call_sites("Points", prose), [])

        emitted = {"join_extract.py": (
            "\n\n"
            "Autodesk.Revit.DB.JoinGeometryUtils.GetJoinedElements(__s, __e);")}
        self.assertEqual(
            AG.capture_call_sites("GetJoinedElements", emitted),
            ["join_extract.py:3"])

        local = {"sketch_extract.py": "foreach (var __r in __st.GetStairsRuns()"}
        self.assertEqual(AG.capture_call_sites("GetStairsRuns", local),
                         ["sketch_extract.py:1"])

    def test_a_refusal_text_is_not_mistaken_for_a_call(self):
        """`"Stairs.GetStairsRuns failed: "` is refusal prose, not a call."""
        refusal = {"sketch_extract.py":
                   '__row["reason"] = "Stairs.GetStairsRuns failed: ";'}
        self.assertEqual(AG.capture_call_sites("GetStairsRuns", refusal), [])

    def test_every_disposition_says_what_is_still_unread(self):
        for key, why in AG.CALLED_MEMBER_DISPOSITIONS.items():
            with self.subTest(member=key):
                self.assertGreater(
                    len(why), 60,
                    "диспозиция без разбора — ярлык, а не знание")


class TheCorpusHasOneCarrier(unittest.TestCase):
    """The prose corpus lives in one place, and both askers take THAT ONE."""

    def test_agreement_and_test_read_the_same_corpus(self):
        from kir.envelope import SHARED_BRIDGE_PROSE
        from kir.tests import test_two_classifiers_agree as T
        self.assertIs(T.SHARED_PROSE, SHARED_BRIDGE_PROSE)

    def test_read_bodies_table_has_one_carrier(self):
        """The reading bodies' argument table is not a copy inside the gate."""
        import inspect

        from kir import gate_runner
        from kir.decompile.read_bodies import READ_BODY_ARGS
        src = inspect.getsource(gate_runner)
        self.assertIn("read_bodies", src,
                      "ворота обязаны БРАТЬ таблицу, а не держать свою")
        self.assertTrue(READ_BODY_ARGS)


if __name__ == "__main__":
    unittest.main()
