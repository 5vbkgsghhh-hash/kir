"""THE CACHE KEY MUST COVER EVERY INPUT CAPABLE OF TURNING THE ANSWER INTO
A REFUSAL.

REPRODUCED DEFECT (measurement of 11.08.2026, `/tmp/wiring/m_cachekey.py`,
one bundle of 40 ducts, flag on):

    KUKAI_IR_CLASH_MAX_PAIRS=8      -> status=over_cap, work=219
    KUKAI_IR_CLASH_MAX_PAIRS=100000 -> status=over_cap   <- THE CACHE RETURNED THE OLD
    cache cleared, same environment -> status=ok, pairs=219

The key was computed from `sha(pack)` + `sha(sections)` + `new_from` and
did NOT cover the four ceilings
(`KUKAI_IR_CLASH_MAX_{ELEMENTS,BODIES,OFFERS,PAIRS}`), even though each of
them is read AT CALL TIME and each decides between a real answer and the
refusal "THE CLASH CHECK WAS NOT PERFORMED… this is 'not looked at'."

THIS REFUTES THE CACHE'S OWN DOCSTRING, which promises, verbatim: "the key
is the sha of the bundle itself, so a miss between two flows costs an extra
count but cannot return SOMEONE ELSE'S answer." It did.

AND IT STRIKES EXACTLY WHERE A PERSON TRUSTS THE ANSWER MOST. A ceiling is
raised PRECISELY BECAUSE a large building was refused; the one who raised
it gets back a cached refusal and reads it as "still too large," even
though nothing was looked at the second time.

THE THIRD CASE OF ONE DEFECT IN THIS MODULE OVER THE MARATHON:
  * a ceiling named "number of BODIES" that actually compared the number
    of ELEMENTS;
  * a cache key without `new_from` — the same bundle with a different turn
    boundary;
  * a cache key without the ceilings — this one.
What they share is not a topic but a form: A MAGNITUDE THAT DOES NOT COVER
WHAT CHANGES THE ANSWER. That is why the list of inputs lives next to the
key and is held by a test: a fifth ceiling that gets added must FORCE a
decision, rather than quietly staying outside.
"""
from __future__ import annotations

import os
import unittest

from kir import clash_bundle as CB


def _ducts(n, step=60.0):
    return [{"op": "create_duct", "id": f"d{i}", "diameter_mm": 400.0,
             "p0_mm": [i * step, 0.0, 0.0], "p1_mm": [i * step, 6000.0, 0.0]}
            for i in range(n)]


class _Env:
    """The environment returned verbatim: a test that left a ceiling
    behind it would poison its neighbors."""

    NAMES = ("KUKAI_IR_CLASH", "KUKAI_IR_CLASH_MAX_ELEMENTS",
             "KUKAI_IR_CLASH_MAX_BODIES", "KUKAI_IR_CLASH_MAX_OFFERS",
             "KUKAI_IR_CLASH_MAX_PAIRS",
             # F-047: the fifth key input. A test that left it behind
             # would poison its neighbors — the same reason as for the
             # four above.
             "KUKAI_IR_CLASH_PROPOSAL_MS")

    def __enter__(self):
        self._saved = {n: os.environ.get(n) for n in self.NAMES}
        os.environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()
        CB.remember_turn_document("")
        return self

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        CB._CACHE.clear()
        # F-046: the TURN's document header is also state, and as of this
        # wave it enters the key. A test that left it behind would change
        # the keys of its neighbors — exactly the same trouble for which
        # the environment is restored.
        CB.remember_turn_document("")
        return False


class ARaisedCeilingIsAFreshQuestion(unittest.TestCase):
    """The core: a raised ceiling must give a NEW answer, not the old
    one."""

    def test_raising_the_pair_cap_stops_returning_the_refusal(self):
        pack = [{"ops": _ducts(40)}]
        with _Env():
            os.environ["KUKAI_IR_CLASH_MAX_PAIRS"] = "8"
            refused = CB._report(pack)
            os.environ["KUKAI_IR_CLASH_MAX_PAIRS"] = "100000"
            again = CB._report(pack)
        self.assertEqual(refused["status"], "over_cap", refused)
        self.assertEqual(again["status"], "ok",
                         "кэш вернул отказ на поднятом потолке")
        self.assertGreater(again["total_findings"], 0)

    def test_lowering_a_cap_stops_returning_the_answer(self):
        """And the reverse direction: a lowered ceiling must refuse,
        rather than return yesterday's success."""
        pack = [{"ops": _ducts(40)}]
        with _Env():
            ok = CB._report(pack)
            os.environ["KUKAI_IR_CLASH_MAX_PAIRS"] = "8"
            now = CB._report(pack)
        self.assertEqual(ok["status"], "ok", ok)
        self.assertEqual(now["status"], "over_cap", now)

    def test_every_cap_moves_the_key(self):
        """Not "some one of the ceilings," but EVERY ONE: a ceiling that
        does not move the key is exactly the one that will someday return
        someone else's answer.

        🔴 THE VARIABLE'S NAME IS TAKEN FROM THE READER ITSELF, NOT
        DERIVED FROM THE INPUT'S NAME (F-047, 29.08.2026). The test used
        to build it as `KUKAI_IR_CLASH_{name.upper()}` — that is, it
        relied on an AGREEMENT BETWEEN TWO NAMES that no one had
        promised. The fifth input, `proposal_budget_ms`, reads
        `KIR_CLASH_PROPOSAL_MS`; the guess would have missed, and the test
        would have declared a correctly-present input to be "not in the
        key." The same kind of defect as the finding itself: an
        instrument clinging to a name mask.

        🔴 AND THIS SAME MASK TURNED RED TODAY, 02.09.2026 — THE SAME
        FORM A THIRD TIME. The readers moved to the `kir.env` door and to
        `KIR_CLASH_*` names; the mask searched for `KUKAI_IR_CLASH` and
        found ZERO names among the five live inputs. The red was news of
        a fix, not of a regression (form 52): the mask guards the
        AGREEMENT of the name in the reader with the cache key, not the
        prefix.

        The `_Env` below is DELIBERATELY left on the FORMER names: it is
        itself the live proof that the running service's host environment
        still moves all five ceilings — through the double reading of
        `env.RENAMED`.
        """
        import ast
        import inspect
        pack = [{"ops": _ducts(6)}]
        with _Env():
            base = CB._cache_key(pack, None, None)
            for name, reader in CB.ANSWER_INPUTS:
                names = [n.value for n in ast.walk(ast.parse(
                             inspect.getsource(reader).strip()))
                         if isinstance(n, ast.Constant)
                         and isinstance(n.value, str)
                         and n.value.startswith("KIR_CLASH")]
                self.assertEqual(len(names), 1,
                                 f"{name}: читатель берёт не одну переменную "
                                 f"окружения, а {names}")
                var = names[0]
                os.environ[var] = "17"
                moved = CB._cache_key(pack, None, None)
                os.environ.pop(var, None)
                self.assertNotEqual(base, moved, f"{name} не входит в ключ")


class TheKeyShowsWhatWentIntoIt(unittest.TestCase):
    """THE FOUR CEILINGS ARE NOT SILENTLY FOLDED INTO ONE NUMBER. Folded
    into a sha, they would become invisible, and the next person to add a
    fifth would not know it had to go in there."""

    def test_the_key_names_every_input_it_covers(self):
        with _Env():
            key = CB._cache_key([{"ops": _ducts(3)}], None, 2)
        for name, _reader in CB.ANSWER_INPUTS:
            self.assertIn(name, key, f"{name} не виден в ключе")
        self.assertIn("new_from=2", key)
        self.assertIn("bundle=", key)

    def test_the_bundle_digest_is_still_a_digest(self):
        """The bundle is deliberately folded into a sha: it can run into
        thousands of operations. What must be VISIBLE are the SMALL
        inputs, not the whole input."""
        with _Env():
            key = CB._cache_key([{"ops": _ducts(3)}], None, None)
        self.assertNotIn("create_duct", key)
        self.assertLess(len(key), 400)

    def test_absent_and_present_sections_are_different_keys(self):
        with _Env():
            a = CB._cache_key([{"ops": _ducts(3)}], None, None)
            b = CB._cache_key([{"ops": _ducts(3)}], {"levels": []}, None)
        self.assertNotEqual(a, b)

    def test_absent_and_zero_new_from_are_different_keys(self):
        """"No boundary was named" and "the boundary is at the first
        program" give different answers (`none` versus
        `whole_bundle_new`), hence different keys too."""
        with _Env():
            a = CB._cache_key([{"ops": _ducts(3)}], None, None)
            b = CB._cache_key([{"ops": _ducts(3)}], None, 1)
        self.assertNotEqual(a, b)


class TheListOfInputsIsClosedAndForcesADecision(unittest.TestCase):
    """LOCK AGAINST A FIFTH CEILING. There is no default: a ceiling added
    to the module and not entered into `ANSWER_INPUTS` must fail THIS
    test, rather than someday hand the operator a cached refusal."""

    def test_every_ceiling_in_the_module_is_covered(self):
        ceilings = {name for name in dir(CB)
                    if name.startswith("_max_") and callable(getattr(CB, name))}
        # the input's name is the function's name without the leading
        # underscore
        covered = {f"_{name}" for name, _reader in CB.ANSWER_INPUTS}
        self.assertEqual(ceilings - covered, set(),
                         f"потолки вне ключа: {sorted(ceilings - covered)}")

    def test_each_entry_reads_the_live_value(self):
        """An input that reads something other than what the refusal
        itself reads is the same defect from the other side: the key
        would move, but the answer would not."""
        with _Env():
            os.environ["KUKAI_IR_CLASH_MAX_PAIRS"] = "123"
            live = dict((name, reader()) for name, reader in CB.ANSWER_INPUTS)
        self.assertEqual(live["max_pairs"], 123)

    def test_the_flag_itself_cannot_serve_a_cached_answer(self):
        """The flag does NOT enter the key, and this is not an omission:
        `bundle_clash_report` checks it BEFORE the cache and returns
        `None` without looking inside. Verified, not assumed."""
        pack = [{"ops": _ducts(6)}]
        with _Env():
            self.assertEqual(CB.bundle_clash_report(pack)["status"], "ok")
            os.environ.pop("KUKAI_IR_CLASH", None)
            self.assertIsNone(CB.bundle_clash_report(pack))


class TheKeyHoldsTheIdentityOfTheDocument(unittest.TestCase):
    """F-046: THE BUILDING'S IDENTITY IS RESOLVED LATER THAN THE KEY IS
    COMPUTED.

    `_report` takes the key on the very first line, while
    `resolve_run(...)` is called seventy lines below it — from the
    document header, `project_uid`, and the Revit version. None of the
    three entered the key, so `existing=none` meant "not asked yet," not
    "there is no source," and a bundle identical in appearance received
    document A's standing clashes in document B.

    THE MEASUREMENT that shows the defect (two decompiles of one corpus,
    a bundle of six ducts, identical byte for byte):
        document A             bodies 9,  pairs 33
        document B FROM CACHE  bodies 9,  pairs 33   <- the answer for a FOREIGN building
        document B w/o cache   bodies 13, pairs 57   <- its own
    """

    def _snap(self, uid, version):
        return {"levels": [{"id": "1", "name": "L1", "elevation_mm": 0.0}],
                "wall_types": [],
                "__document_fingerprint": {"project_uid": uid},
                "__revit_version": version}

    def test_two_documents_do_not_share_one_key(self):
        pack = [{"ops": _ducts(3)}]
        with _Env():
            CB.remember_turn_document("Dom A.rvt")
            a = CB._cache_key(pack, self._snap("UID-AAA", "2023"), None)
            CB.remember_turn_document("Dom B.rvt")
            b = CB._cache_key(pack, self._snap("UID-BBB", "2019"), None)
        self.assertNotEqual(a, b)

    def test_each_of_the_three_decides_on_its_own(self):
        """The three components are checked SEPARATELY: none is derived
        from the other two. Documents can share a name (the corpus has a
        group of 18), can share a version, can share a uid after a Save
        As."""
        pack = [{"ops": _ducts(3)}]
        base = ("Dom.rvt", "UID-AAA", "2023")
        others = {"только заголовок": ("Drugoi.rvt", "UID-AAA", "2023"),
                  "только project_uid": ("Dom.rvt", "UID-BBB", "2023"),
                  "только версия": ("Dom.rvt", "UID-AAA", "2019")}
        with _Env():
            CB.remember_turn_document(base[0])
            first = CB._cache_key(pack, self._snap(base[1], base[2]), None)
            for name, (title, uid, version) in others.items():
                with self.subTest(name=name):
                    CB.remember_turn_document(title)
                    other = CB._cache_key(pack, self._snap(uid, version), None)
                    self.assertNotEqual(first, other, name)

    def test_the_same_document_still_hits_the_cache(self):
        """🔴 THE SECOND OUTCOME, AND IT IS MANDATORY. A fix that mixed a
        timestamp or a counter into the key would pass the checks above —
        and the cache would stop ever hitting at all, silently, at the
        cost of speed alone. This is exactly the green, useless control
        that a rollback cannot catch."""
        pack = [{"ops": _ducts(3)}]
        snapshot = self._snap("UID-AAA", "2023")
        with _Env():
            CB.remember_turn_document("Dom A.rvt")
            first = CB._cache_key(pack, snapshot, None)
            second = CB._cache_key(pack, snapshot, None)
            self.assertEqual(first, second)
            CB.bundle_clash_report(pack, snapshot=snapshot)
            self.assertEqual(len(CB._CACHE), 1)
            CB.bundle_clash_report(pack, snapshot=snapshot)
            self.assertEqual(len(CB._CACHE), 1, "кэш перестал попадать")

    def test_an_unknown_identity_is_not_invented_to_be_different(self):
        """`_live_project_uid` declares: empty is a fact about OUR
        reading, not about the building, and "absence never turns into
        'identity did not match'." The key holds the same law. The cost
        is named in the code: such turns keep sharing the cache, and
        closing this is possible only with a mandatory fingerprint — a
        decision for the OWNER."""
        pack = [{"ops": _ducts(3)}]
        bare = {"levels": [{"id": "1", "name": "L1", "elevation_mm": 0.0}],
                "wall_types": []}
        with _Env():
            CB.remember_turn_document("")
            first = CB._cache_key(pack, bare, None)
            second = CB._cache_key(pack, dict(bare), None)
        self.assertEqual(first, second)

    def test_whatever_resolves_the_identity_is_in_the_key(self):
        """🔴 A LOCK ON THE LAW, NOT ON A LIST OF NAMES. The subject is not
        "these three values" but "WHAT RESOLVES IDENTITY." The test reads
        the very call to `resolve_run(...)` in `_report`, takes the
        functions its arguments are computed by, and requires each one in
        `_cache_key`'s source. A fourth argument added to the resolver
        will fail THIS test, rather than someday hand over someone else's
        building."""
        import ast
        import inspect
        report = ast.parse(inspect.getsource(CB._report))
        calls = [n for n in ast.walk(report)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", None) == "resolve_run"]
        self.assertEqual(len(calls), 1, "вызов resolve_run исчез — тест не туда")
        used: set[str] = set()
        for argument in list(calls[0].args) + [k.value for k in calls[0].keywords]:
            for node in ast.walk(argument):
                if isinstance(node, ast.Call):
                    name = (getattr(node.func, "id", None)
                            or getattr(node.func, "attr", None))
                    if name:
                        used.add(name)
        self.assertTrue(used, "доводы резолвера не разобраны — тест не туда")
        key_source = inspect.getsource(CB._cache_key)
        # Comments are stripped out: a guard that reads SOURCE would
        # otherwise count PROSE — the smith's own explanation of what is
        # not in the code.
        code = "\n".join(line.split("#", 1)[0]
                          for line in key_source.splitlines())
        for name in sorted(used):
            with self.subTest(name=name):
                self.assertIn(name + "(", code,
                              f"личность разрешается через {name}(), "
                              f"а ключ её не держит")


class TheLockGuardsTheKindNotTheName(unittest.TestCase):
    """F-047: THE LOCK WAS GUARDING THE `_max_*` NAME MASK.

    `_proposal_budget_ms` reads `KUKAI_IR_CLASH_PROPOSAL_MS`, sets the
    budget of the SECOND pass, and changes not the speed but the NUMBER IN
    THE TURN that the designer reads (median ×5.892, p90 ×56.667, maximum
    ×112 066.5 — a measurement of 600 findings from `sob62_r23_v5`); `0`
    switches the pass off entirely. It did not fit the `_max_*` mask and
    slipped past the lock without failing anything. An instrument that a
    rename can get around guards nothing.
    """

    #: A CLOSED LIST OF EXCEPTIONS — with a reason for EVERY row, not
    #: "haven't gotten to it yet." The form is taken from
    #: `KNOWN_RAW_READERS`.
    EXEMPT = {
        "clash_enabled":
            "флаг проверяется ДО кэша и возвращает None, не заглядывая "
            "внутрь; проверено соседним "
            "`test_the_flag_itself_cannot_serve_a_cached_answer`",
    }

    def test_every_environment_reader_is_in_the_key(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(CB))
        readers = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and n.value.startswith("KIR_CLASH")
                   for n in ast.walk(node)):
                readers.add(node.name)
        self.assertGreaterEqual(
            len(readers), 5,
            "разбор не нашёл читателей окружения — прибор смотрит не туда")
        covered = {f"_{name}" for name, _reader in CB.ANSWER_INPUTS}
        missing = readers - covered - set(self.EXEMPT)
        self.assertEqual(
            set(), missing,
            f"читают окружение и не в ключе: {sorted(missing)}")

    def test_the_budget_decides_a_key_of_its_own(self):
        pack = [{"ops": _ducts(3)}]
        with _Env():
            os.environ["KUKAI_IR_CLASH_PROPOSAL_MS"] = "0"
            off = CB._cache_key(pack, None, None)
            os.environ["KUKAI_IR_CLASH_PROPOSAL_MS"] = "250"
            on = CB._cache_key(pack, None, None)
            os.environ.pop("KUKAI_IR_CLASH_PROPOSAL_MS", None)
        self.assertNotEqual(off, on)


if __name__ == "__main__":
    unittest.main()
