"""THE SAME LAW, THREE MORE PLACES: the string "false" was truthy, `True` was a number.

THE LAW WAS ALREADY WRITTEN, AND THESE THREE PLACES BROKE IT. On
29.08.2026 a colleague closed findings F-239…F-243 and wrote the law into
`test_the_sdk_refuses_instead_of_coercing`: "there is no correct reading
of a string instead of a boolean", "a dictionary is not a mechanism",
"coercion swallows the refusal the contract was written for." The law was
put on ONE carrier — `kir/sdk.py`. A measurement on 04.09.2026 found
three more, and not one of them was covered by the law:

    dsl.envelope(allow_destructive='false')  ->  "allow_destructive": true
    CompileClient.check() on {"success": "false"}  ->  success='false' (truthy)
    TypeSection.from_dict({"sizes": [[True, 2]]})   ->  size 1.0 mm

One kind: TYPE COERCION INSTEAD OF REFUSAL. The difference between the
three is only in whose refusal the coercion swallowed.

──────────────────────────────────────────────────────────────────────────────
LD-01. `kir/dsl.py` — THE SECOND PYTHON FRONT THE LAW NEVER REACHED.

There are two Python fronts, and `dsl.py`'s header states this outright:
"HOW THIS MODULE DIFFERS FROM `sdk.py`". The difference is named in four
points, and not one of them is about the envelope's truthiness — that is,
the law should have landed on both. It landed on one.

🔴 AND HERE IT WAS MORE EXPENSIVE THAN AT `sdk`: IT SWALLOWED THE
COMPILER'S OWN REFUSAL. The compiler DOES have this law, and it is named
(`_parse_and_check_internal`, `KIR-T001`, «allow_destructive должен быть
true/false»). On a program assembled by `dsl`, it could never fire, not
once: `bool()` inside `build()` turned the string into a legal `true`
BEFORE the compiler ever saw it. The front did not let an invalid value
through — it MADE it valid, and precisely the value that PERMITS
demolition.

LD-02. `kir/compile_client.py` + `kir/compile_cache.py` — A LIE THAT GETS CACHED.

`success: bool` is an annotation, not a mechanism. An HTTP 200 with the
body `{"success": "false", "errors": [CS0246]}` reached the caller as
`CompileResult(success='false', errors=[CS0246])`: code that failed to
build, with its own error named in the very same response, read as
"compiled."

Worse than the cache alone: the cache LAUNDERED THE LIE. `_store` asked
about truthiness (`if not result.success`), not the verdict, and the
record landed in memory AND on disk; `_lookup` never checked memory (it
checked disk, not memory); `_payload_to_result` did `bool("false")`. The
second call returned `success=True` as a real boolean, indistinguishable
from an honest success. Measured: hits=1, one file on disk.

LD-03. `kir/open_model.py` — A QUANTITY NOBODY MEASURED.

`float(pair[0])` and `float(row_layer.get("width_mm"))`, with no guard
against `bool`. `float(True)` equals 1.0, so `sizes: [[true, 2]]` gave a
size of 1.0 mm, and a layer with `width_mm: true` gave a thickness of
1.0 mm.

🔴 WHY THE JUDGE, WHICH HAD A CHECK IN PLACE, DID NOT CATCH THIS.
`__post_init__` checks `isinstance(x, bool)` across all these fields —
and was powerless: it was already handed `1.0`, a legal positive number.
The coercion stood ABOVE the judge and stripped it of its subject. It
was only caught by accident, and only from one side: `sizes: [[1,
false]]` went red not as a `bool`, but because `float(False)` equals
zero, and zero is not positive. `True` passed, `False` was rejected —
the very same asymmetry in falseness already named in F-079 of this same
file.

Measured in passing, alongside: `layer_count: true` was accepted
SILENTLY. The condition `not isinstance(заявлено, bool)` did not reject
a boolean, it took it out of the check entirely — a declared witness
disappeared in exactly the way the check exists to catch.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from kir import dsl
from kir.compile_cache import CachedCompileClient
from kir.compile_client import CompileClient, CompileError, CompileResult
from kir.compiler import plan_program
from kir.diag import KirRefusal

# 🔴 THE NAMES OF `open_model` ARE TAKEN FROM THE MODULE AT CALL TIME, NOT
# AT IMPORT. `kir/tests/test_open_model.py:890` calls
# `importlib.reload(om)` in a `finally`, and this sets up NEW class
# objects, including the refusal class. A file that captured them by
# name is green ALONE and red IN COMPANY: `assertRaises` holds the OLD
# class, while the validator raises the NEW one. Paid for by a run, not
# by reasoning — `test_open_model.py` together with this file gave 8
# reds at 31 green when run alone. This tree cures it one way, and that
# way is already written at its neighbors (`test_type_sections.py`,
# `test_a_truncated_pool_says_so.py`).
#
# `dsl` is asked the same way and for the same reason (`test_dsl.py`
# calls `importlib.reload(dsl)`), which is why what is taken above is
# the MODULE, not `DslRefusal` by name.
import kir.open_model as _om


#: The words with which the author FORBIDS, and each of them is TRUE in Python.
_WORDS_THAT_FORBID = ("false", "no", "нет", "off", "0")


# ─────────────────────────────────────────────────────────── LD-01: language

class TheOtherPythonFrontEndObeysTheSameLaw(unittest.TestCase):
    """`kir/dsl.py`. The same envelope, the same field, the same law as `sdk`."""

    def setUp(self) -> None:
        dsl.reset()

    def tearDown(self) -> None:
        dsl.reset()

    @staticmethod
    def _one_op() -> None:
        dsl.create_level(elev_mm=0, name="Этаж 1")

    # ── the green outcome that must survive ───────────────────────────────
    def test_true_and_false_still_pass_through(self) -> None:
        """🔴 WITHOUT THIS THE CHECK WOULD BE "FIELD FORBIDDEN". The numbers were
        captured by execution before the fix and match byte-for-byte."""
        dsl.envelope(allow_destructive=True)
        self._one_op()
        self.assertIs(dsl.build()["allow_destructive"], True)
        dsl.reset()
        dsl.envelope(allow_destructive=False)
        self._one_op()
        self.assertIs(dsl.build()["allow_destructive"], False)

    def test_none_omits_the_field_exactly_as_before(self) -> None:
        dsl.envelope(allow_destructive=None)
        self._one_op()
        self.assertNotIn("allow_destructive", dsl.build())

    def test_a_program_untouched_by_the_field_is_byte_for_byte_the_same(self) -> None:
        """Apart from this field, the fix must not shift the envelope AT ALL."""
        dsl.envelope(intent="комната")
        self._one_op()
        self.assertEqual(
            dsl.build(),
            {"ir_version": dsl.spec.IR_VERSION, "intent": "комната",
             "ops": [{"op": "create_level", "id": "level1",
                      "elev_mm": 0, "name": "Этаж 1"}]})

    # ── the very defect ───────────────────────────────────────────────
    def test_the_word_that_forbids_does_not_enable(self) -> None:
        for word in _WORDS_THAT_FORBID:
            with self.subTest(word=word):
                self.assertTrue(bool(word),
                                "проба негодна: в питоне это слово ЛОЖНО")
                dsl.reset()
                with self.assertRaises(dsl.DslRefusal) as caught:
                    dsl.envelope(allow_destructive=word)
                self.assertEqual(caught.exception.diagnostics[0].field_name,
                                 "allow_destructive")

    def test_numbers_are_refused_too(self) -> None:
        """0 and 1 "would work" too — and that is also coercion: the contract is boolean.

        Before the fix, `allow_destructive=0` gave `false`, and `=1` gave `true`:
        the field behaved as numeric without being one."""
        for number in (0, 1, 0.0, 1.0):
            with self.subTest(number=number):
                dsl.reset()
                with self.assertRaises(dsl.DslRefusal):
                    dsl.envelope(allow_destructive=number)

    # ── all doors, not just one ───────────────────────────────────────────
    def test_every_door_into_the_envelope_refuses_not_only_the_first(self) -> None:
        """FOUR ENTRY POINTS, AND FIXING ONE WOULD LEAVE THE REST LYING.

        `Program(...)`, `dsl.program(...)`, `p.envelope(...)`, and assigning
        the field directly — before the fix, each of them turned the string into `true`.
        """
        with self.assertRaises(dsl.DslRefusal):
            dsl.Program(allow_destructive="false")
        with self.assertRaises(dsl.DslRefusal):
            dsl.program(allow_destructive="false")
        with self.assertRaises(dsl.DslRefusal):
            dsl.Program().envelope(allow_destructive="false")
        # THE FOURTH DOOR: the field is public, and direct assignment bypasses the first three.
        # It is guarded by `build()` — the very point where `bool(...)` stood.
        sneaky = dsl.Program()
        sneaky.allow_destructive = "false"
        with self.assertRaises(dsl.DslRefusal):
            sneaky.build()

    # ── whose refusal was being intercepted ───────────────────────────────
    def test_the_compilers_own_refusal_was_unreachable_through_this_front(self) -> None:
        """🔴 THE MOST COSTLY THING HERE. The compiler DID have the law; `bool()` made it
        unreachable, substituting the object under check with a legitimate `true`."""
        raw = {"ir_version": dsl.spec.IR_VERSION,
               "allow_destructive": "false",
               "ops": [{"op": "create_level", "id": "level1",
                        "elev_mm": 0, "name": "Этаж 1"}]}
        with self.assertRaises(KirRefusal) as caught:
            plan_program(raw, bulk=True)
        self.assertEqual(caught.exception.diagnostics[0].code, "KIR-T001")
        # And here is what the front end returned INSTEAD of this program — a legitimate `true`,
        # that is, PERMISSION to demolish, from the very word that forbids it.
        self.assertIs(bool("false"), True)

    def test_a_legitimately_destructive_program_still_plans(self) -> None:
        """🔴 GREEN OUTCOME ON THE SAME PATH: `True` makes it all the way to the plan."""
        dsl.envelope(allow_destructive=True)
        self._one_op()
        built = dsl.build()
        self.assertIs(built["allow_destructive"], True)
        plan_program(built, bulk=True)      # does not refuse


# ────────────────────────────────────────────────── LD-02: the service's verdict

def _client(body: object, status: int = 200) -> CompileClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    client = CompileClient(base_url="http://compile.invalid")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


class AnUnreadableCompileVerdictIsNoVerdict(unittest.TestCase):
    """`kir/compile_client.py`. `None` is already the existing word for "no
    answer", and it is fail-closed at the same time: `gate_runner` treats it as
    `compile-service-no-answer` and does NOT count the compilation."""

    @staticmethod
    def _check(body: object, status: int = 200):
        async def run():
            client = _client(body, status)
            try:
                return await client.check("код", "2026")
            finally:
                await client.close()
        return asyncio.run(run())

    def test_a_string_verdict_is_not_a_verdict(self) -> None:
        result = self._check({"success": "false",
                              "errors": [{"code": "CS0246", "message": "нет",
                                          "line": 1, "column": 1}]})
        self.assertIsNone(result)

    def test_the_word_true_is_refused_as_well_not_only_false(self) -> None:
        """THE SECOND HALF. Fixing only "false" would mean fixing the WORD, not
        the type: `"true"` is the same unrecognized answer, and there is nothing in it to trust."""
        self.assertIsNone(self._check({"success": "true", "errors": []}))

    def test_numbers_and_null_are_refused_too(self) -> None:
        for verdict in (0, 1, None, [], {}):
            with self.subTest(verdict=verdict):
                self.assertIsNone(
                    self._check({"success": verdict, "errors": []}))

    def test_a_missing_key_is_no_answer_rather_than_a_failed_compile(self) -> None:
        """The former default of `False` turned SILENCE INTO A VERDICT: an answer that
        said nothing declared someone else's code as failing to build — and without a single
        error in the list, that is, irrefutably."""
        self.assertIsNone(self._check({"errors": []}))

    def test_real_booleans_still_pass_through_both_ways(self) -> None:
        """🔴 GREEN OUTCOME. Without it the check would be "the service is down"."""
        good = self._check({"success": True, "errors": []})
        self.assertIsNotNone(good)
        self.assertIs(good.success, True)
        bad = self._check({"success": False,
                           "errors": [{"code": "CS0246", "message": "нет",
                                       "line": 7, "column": 3}]})
        self.assertIsNotNone(bad)
        self.assertIs(bad.success, False)
        self.assertEqual(bad.errors,
                         [CompileError(code="CS0246", message="нет",
                                       line=7, column=3)])

    def test_the_type_itself_refuses_so_no_other_door_can_lie(self) -> None:
        """The `success: bool` annotation became a mechanism: there are two doors (the
        service's answer and the cache record), and the law rests on the type, not on either one alone."""
        with self.assertRaises(TypeError) as caught:
            CompileResult(success="false")
        self.assertIn("success", str(caught.exception))
        self.assertIs(CompileResult(success=True).success, True)


class ACacheNeverKeepsWhatItCouldNotRead(unittest.TestCase):
    """`kir/compile_cache.py`. A cached falsehood outlives the error itself:
    on disk it survives both a restart of the service and the fixing of the cause."""

    _toolchain = "sha256:toolchain-фикстура"

    class _Fake:
        """Returns whatever it was given, bypassing the type check at the HTTP door."""

        def __init__(self, result) -> None:
            self._result = result
            self.calls = 0

        async def check(self, wrapped_code: str, revit_version: str):
            self.calls += 1
            return self._result

        async def health(self) -> bool:
            return True

        async def close(self) -> None:
            pass

        @property
        def available(self) -> bool:
            return True

    def test_an_unreadable_answer_reaches_neither_memory_nor_disk(self) -> None:
        """THE ENTIRE PATH, FROM THE HTTP BODY TO THE FILE ON DISK.

        Measurement before the fix on this same input: `hits=1`, one record in memory, one
        file on disk, and the second call returned `success=True` as a real boolean.
        """
        with TemporaryDirectory() as folder:
            live = _client({"success": "false",
                            "errors": [{"code": "CS0246", "message": "нет",
                                        "line": 1, "column": 1}]})
            cached = CachedCompileClient(
                live, enabled=True, toolchain_identity=self._toolchain,
                cache_dir=folder)
            try:
                self.assertIsNone(asyncio.run(cached.check("код", "2026")))
                self.assertIsNone(asyncio.run(cached.check("код", "2026")))
            finally:
                asyncio.run(cached.close())
            self.assertEqual(cached.hits, 0)
            self.assertEqual(len(cached._memory), 0)
            self.assertEqual(sorted(Path(folder).glob("*.json")), [])

    def test_the_store_gate_asks_for_the_verdict_not_for_truthiness(self) -> None:
        """THE CACHE ENTRY POINT, MEASURED SEPARATELY FROM THE EXIT.

        `CompileResult` can no longer even be constructed with an unrecognized `success`,
        so the object under test is fed in as a foreign object — exactly what the
        former `if not result.success` saw: the string "false" is truthy, and the record
        went off to disk.
        """
        from types import SimpleNamespace
        with TemporaryDirectory() as folder:
            cached = CachedCompileClient(
                self._Fake(None), enabled=True,
                toolchain_identity=self._toolchain, cache_dir=folder)
            cached._store("ключ", SimpleNamespace(success="false", errors=[]))
            self.assertEqual(len(cached._memory), 0)
            self.assertEqual(sorted(Path(folder).glob("*.json")), [])

    def test_a_poisoned_memory_entry_is_dropped_instead_of_reused(self) -> None:
        """🔴 THE OTHER END. `_disk_get` checked the record, `_lru_get` did NOT:
        the disk was locked, MEMORY WAS OPEN, and the poisoned record
        came out of memory precisely. I place it there by hand — the very same way
        the former `_store` used to place it."""
        cached = CachedCompileClient(
            self._Fake(CompileResult(success=True)), enabled=True,
            toolchain_identity=self._toolchain)
        cached._memory["ключ"] = {
            "schema": "compile-cache-entry/2",
            "toolchain_identity": self._toolchain,
            "success": "false",
            "errors": [],
        }
        self.assertIsNone(cached._lookup("ключ"))
        self.assertEqual(len(cached._memory), 0)

    def test_a_genuine_success_is_still_cached_and_reused(self) -> None:
        """🔴 GREEN OUTCOME. Without it the check would be "the cache is off"."""
        with TemporaryDirectory() as folder:
            fake = self._Fake(CompileResult(success=True))
            cached = CachedCompileClient(
                fake, enabled=True, toolchain_identity=self._toolchain,
                cache_dir=folder)
            first = asyncio.run(cached.check("код", "2026"))
            second = asyncio.run(cached.check("код", "2026"))
            self.assertIs(first.success, True)
            self.assertIs(second.success, True)
            self.assertEqual((cached.hits, cached.misses, fake.calls), (1, 1, 1))
            written = sorted(Path(folder).glob("*.json"))
            self.assertEqual(len(written), 1)
            self.assertIs(
                json.loads(written[0].read_text(encoding="utf-8"))["success"],
                True)

    def test_a_genuine_failure_is_still_never_cached(self) -> None:
        """The former law "only success gets cached" must survive verbatim."""
        with TemporaryDirectory() as folder:
            fake = self._Fake(CompileResult(
                success=False,
                errors=[CompileError(code="CS0246", message="нет",
                                     line=1, column=1)]))
            cached = CachedCompileClient(
                fake, enabled=True, toolchain_identity=self._toolchain,
                cache_dir=folder)
            asyncio.run(cached.check("код", "2026"))
            asyncio.run(cached.check("код", "2026"))
            self.assertEqual((cached.hits, fake.calls), (0, 2))
            self.assertEqual(sorted(Path(folder).glob("*.json")), [])


# ──────────────────────────────────────────────── LD-03: the profile millimeter

class AMillimetreIsNeverABoolean(unittest.TestCase):
    """`kir/open_model.py`, `TypeSection.from_dict`."""

    _TABLE = {"kind": "nominal_table", "source": "PipeSegment.GetSizes"}
    _PLATE = {"kind": "plate", "source": "WallType.Width", "uniform": True}

    def _refused(self, row: dict, needle: str) -> None:
        with self.assertRaises(_om.OpenModelProfileError) as caught:
            _om.TypeSection.from_dict(row)
        self.assertIn(needle, str(caught.exception))

    # ── dimensions ────────────────────────────────────────────────────────
    def test_a_boolean_nominal_is_refused_not_measured_as_one_millimetre(self) -> None:
        self._refused({**self._TABLE, "sizes": [[True, 2]]},
                      "type_section.sizes[0][0]")

    def test_the_second_half_of_the_pair_is_guarded_too(self) -> None:
        """`False` already turned red BEFORE the fix — but not as a `bool`, rather because
        `float(False)` equals zero. A check built on it would be a worthless green
        control: it gives itself away by nothing."""
        self.assertEqual(float(False), 0.0)
        self._refused({**self._TABLE, "sizes": [[1, False]]},
                      "type_section.sizes[0][1]")

    def test_a_string_number_is_refused_as_well(self) -> None:
        """The same kind: `float("200")` is coercion, not reading the evidence."""
        self._refused({**self._TABLE, "sizes": [["1", "2"]]},
                      "type_section.sizes[0][0]")

    def test_a_missing_number_gets_a_named_refusal_not_a_bare_typeerror(self) -> None:
        """Before the fix, a bare `TypeError` flew out here, BYPASSING the profile dict:
        `float() argument must be a string or a real number`. A refusal that
        names neither the field nor the file is useless to the profile's reader."""
        self._refused({**self._TABLE, "sizes": [[None, 2]]},
                      "type_section.sizes[0][0]")

    # ── layers ───────────────────────────────────────────────────────────
    def test_a_boolean_layer_width_is_refused(self) -> None:
        self._refused(
            {**self._PLATE,
             "layers": [{"width_mm": True, "function": "Structure"}]},
            "type_section.layers[0].width_mm")

    def test_a_string_layer_width_and_a_missing_one_are_refused_too(self) -> None:
        for width in ("200", None):
            with self.subTest(width=width):
                layer = {"function": "Structure"}
                if width is not None:
                    layer["width_mm"] = width
                self._refused({**self._PLATE, "layers": [layer]},
                              "type_section.layers[0].width_mm")

    # ── the declared witness ──────────────────────────────────────────
    def test_a_boolean_layer_count_is_refused_not_silently_skipped(self) -> None:
        """The condition `not isinstance(заявлено, bool)` PARDONED the boolean instead of
        rejecting it: the witness slipped out from under the comparison entirely."""
        self._refused(
            {**self._PLATE,
             "layers": [{"width_mm": 200, "function": "Structure"}],
             "layer_count": True},
            "type_section.layer_count must be an integer")

    def test_a_mismatching_layer_count_is_still_caught(self) -> None:
        """🔴 GREEN CONTROL IN REVERSE: the former comparison must survive."""
        self._refused(
            {**self._PLATE,
             "layers": [{"width_mm": 200, "function": "Structure"}],
             "layer_count": 999},
            "says 999")

    # ── the green outcome ──────────────────────────────────────────────────
    def test_an_honest_profile_reads_and_round_trips_unchanged(self) -> None:
        """🔴 WITHOUT THIS THE CHECK WOULD BE "PROFILE UNREADABLE". Integers in JSON
        are legitimate and must remain legitimate: the fix forbids `bool`, not
        `int`."""
        row = {**self._PLATE, "thickness_mm": 200,
               "layers": [{"width_mm": 150, "function": "Structure",
                           "material": "Кирпич"},
                          {"width_mm": 50.5, "function": "Finish1"}],
               "layer_count": 2}
        section = _om.TypeSection.from_dict(row)
        self.assertEqual(section.layers,
                         ((150.0, "Structure", "Кирпич"),
                          (50.5, "Finish1", None)))
        self.assertEqual(_om.TypeSection.from_dict(section.to_dict()).to_dict(),
                         section.to_dict())

        table = _om.TypeSection.from_dict({**self._TABLE, "sizes": [[15, 21.3],
                                                                [20, 26.9]]})
        self.assertEqual(table.sizes, ((15.0, 21.3), (20.0, 26.9)))


# ───────────────────────────────────────────────────────────── control

class TheCoercionWasRealNotHypothetical(unittest.TestCase):
    """A FAIL CONTROL IN THE FILE: to show that the coercion is ACTUALLY dangerous.

    Every assertion here is about Python, not about our code: if any
    one of them were false, there would be nothing to fix, and the whole file would be fiction.
    The executed FAIL control was captured separately — this same file on a FROZEN
    copy of the tree before the fix (`git archive HEAD` + `PYTHONPATH`=copy, so that
    the editable install of prod would not substitute the object; the object of measurement was verified via
    `kir.__file__`): 18 red nodes out of 31, with 31 green here. The ones that
    turn red are exactly the assertions about our three spots; three assertions of this
    class are green there too — they are about Python, not about us.
    """

    def test_every_word_that_forbids_is_true_in_python(self) -> None:
        for word in _WORDS_THAT_FORBID:
            with self.subTest(word=word):
                self.assertTrue(bool(word))

    def test_a_boolean_is_a_number_in_python(self) -> None:
        self.assertEqual(float(True), 1.0)
        self.assertEqual(float(False), 0.0)
        self.assertTrue(isinstance(True, int))

    def test_falsiness_is_why_only_half_the_defect_was_visible(self) -> None:
        """THE REASON, IN A NUMBER: `False` was rejected NOT by a check, but by the fact that zero is not
        positive. One field, two answers keyed on falsiness — that is not
        a check, but a coincidence (the same argument as for F-079)."""
        self.assertGreater(float(True), 0.0)
        self.assertEqual(float(False), 0.0)


if __name__ == "__main__":
    unittest.main()
