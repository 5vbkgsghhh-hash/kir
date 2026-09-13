"""SLIDER: a named program parameter that is moved WITHOUT REWRITING the
program.

WHY THIS WAS SET UP, AND IT IS NOT INPUT CONVENIENCE. A measurement on
20.08.2026 built a map of "what Grasshopper can do that we can't". Of the
INSTRUMENTAL items, exactly one remained — the slider. The author's Python
is stronger than the GH graph (loops, functions, recursion, its own data
structures), but there was nothing to nudge a number and watch.

🔴 THE MAIN VALUE — A DISTINCTION IN THE RECEIPT, NOT THE INPUT FORM.
Before the slider, "the author rewrote the definition" and "the caller
moved the knob" read as IDENTICAL: a different program with the same
source, or a different source — in both cases the only evidence is
`program_digest`, and what exactly happened cannot be reconstructed. Now a
pair of signatures answers this directly:

    author_digest THE SAME + params_digest DIFFERENT   -> the knob was moved
    author_digest DIFFERENT                            -> the definition was rewritten

This is the same technique already used for `model_digest` (a document
edit) and `building_digest` (a building edit): a signer appears whenever
one source LEGITIMATELY produces different programs. The slider is the
fourth case.

A BOUNDARY THAT MUST NOT BE VIOLATED. The sandbox executes the script
TWICE and cross-checks digests (`replay_check`): the signature of a
non-deterministic script certifies nothing. Parameters enter this
discipline rather than bypass it — both runs receive the SAME SET, so "the
same parameters -> the same program byte-for-byte" is checked by the
mechanism itself, not merely promised.
"""
from __future__ import annotations

import unittest

from kir.diag import SANDBOX_PARAM
from kir.sandbox import (SandboxPolicy, allowed_imports_for_env,
                              execute_author_script)

#: A source with TWO knobs of different kinds: a number decides
#: coordinates, an integer decides HOW MANY operations. The second matters
#: more: a knob that only changes numbers inside operations would not
#: distinguish a slider from substituting a constant.
SRC = '''
w = param("width_mm", 6000.0, min=3000.0, max=12000.0, doc="ширина пролёта")
n = param("bays", 3, min=1, max=8)
ops = [{"op": "create_wall", "id": f"W{i}",
        "p0_mm": [i * w, 0.0], "p1_mm": [(i + 1) * w, 0.0],
        "level": {"by": "default"}, "height_mm": 3000.0}
       for i in range(n)]
'''

_POLICY = SandboxPolicy(replay_check=True,
                        allowed_imports=allowed_imports_for_env())


def _run(source: str = SRC, params=None):
    return execute_author_script(source, policy=_POLICY, params=params)


class TheReceiptTellsTheTwoApart(unittest.TestCase):
    """This is exactly the class the slider was built for."""

    def test_moving_a_knob_keeps_the_author_signature_and_changes_the_params_one(self):
        default = _run()
        moved = _run(params={"width_mm": 9000.0, "bays": 5})
        self.assertTrue(default.ok and moved.ok,
                        "исходник не собрался на законных значениях")
        self.assertEqual(default.author_digest, moved.author_digest,
                         "исходник не менялся, а подпись автора уехала")
        self.assertNotEqual(default.params_digest, moved.params_digest,
                            "ручку двинули, а подпись параметров та же — "
                            "различить два события нечем")
        self.assertNotEqual(default.program_digest, moved.program_digest)

    def test_rewriting_the_source_changes_the_AUTHOR_signature(self):
        """NARROWNESS CONTROL: without it the first test proves only half.

        A signature that NEVER moves would also pass the check "the source
        did not change — the signature is the same".
        """
        rewritten = SRC.replace('min=3000.0', 'min=2000.0')
        self.assertNotEqual(_run().author_digest, _run(rewritten).author_digest)

    def test_a_knob_that_changes_NOTHING_is_still_recorded_as_moved(self):
        """A subtle but load-bearing case.

        The caller passed a value equal to the default: the program is
        byte-for-byte the same. `params_digest` MUST nonetheless differ
        from "nothing was passed" — these are different events. "The knob
        was untouched" and "the same value was set again" differ in
        intent, and the receipt must carry the intent.
        """
        untouched = _run()
        same_value = _run(params={"width_mm": 6000.0})
        self.assertEqual(untouched.program_digest, same_value.program_digest)
        self.assertNotEqual(untouched.params_digest, same_value.params_digest)


class TheKnobsAreDeclaredNotGuessed(unittest.TestCase):

    def test_the_manifest_carries_what_a_slider_needs_to_be_drawn(self):
        r = _run(params={"bays": 7})
        by_name = {p["name"]: p for p in r.params}
        self.assertEqual(sorted(by_name), ["bays", "width_mm"])
        self.assertEqual(by_name["bays"]["value"], 7)
        self.assertEqual(by_name["bays"]["default"], 3)
        self.assertFalse(by_name["bays"]["used_default"])
        self.assertEqual((by_name["bays"]["min"], by_name["bays"]["max"]), (1, 8))
        self.assertTrue(by_name["width_mm"]["used_default"])
        self.assertEqual(by_name["width_mm"]["doc"], "ширина пролёта")

    def test_the_knob_really_changes_the_program(self):
        """A slider that does not change the program is decoration.

        What is checked is the NUMBER of operations, not just the digest:
        a digest would differ even over a stray space.
        """
        self.assertEqual(len(_run().ops), 3)
        self.assertEqual(len(_run(params={"bays": 6}).ops), 6)


class TheRefusalsSayWhoseRepairItIs(unittest.TestCase):
    """Blame is named for EVERY refusal: fixing the script and fixing the call are different."""

    def _refusal(self, source=SRC, params=None):
        r = _run(source, params)
        self.assertFalse(r.ok, "ожидался отказ, а программа собралась")
        self.assertEqual(r.refusal.code, SANDBOX_PARAM)
        return r.refusal

    def test_an_unknown_name_is_refused_and_the_declared_ones_are_listed(self):
        """THE MOST EXPENSIVE OF ALL POSSIBLE OUTCOMES, if this stayed silent.

        A caller's typo would produce a program on defaults, signed as if
        it had been ordered: they are sure they moved the knob, but the old
        one got built.
        """
        d = self._refusal(params={"widht_mm": 9000.0})
        self.assertEqual(d.kind, "ParamUnknown")
        self.assertEqual(d.blame, "caller")
        self.assertIn("width_mm", d.message_ru)      # declared ones are named
        self.assertIn("СЛЕДУЮЩИЙ ХОД", d.message_ru)

    def test_a_value_outside_the_declared_bounds_is_refused(self):
        d = self._refusal(params={"width_mm": 99000.0})
        self.assertEqual((d.kind, d.blame), ("ParamAboveMax", "caller"))

    def test_a_value_of_the_wrong_kind_is_refused(self):
        d = self._refusal(params={"width_mm": "широко"})
        self.assertEqual((d.kind, d.blame), ("ParamKindMismatch", "caller"))

    def test_a_bool_is_NOT_a_number(self):
        """In Python, `True` is a subclass of int. Without an explicit
        check, the flag would slip through as one, and the "width" knob
        would accept `True` as 1 mm."""
        d = self._refusal(params={"width_mm": True})
        self.assertEqual(d.kind, "ParamKindMismatch")

    def test_a_list_cannot_be_a_knob(self):
        d = self._refusal('x = param("p", [1, 2])\nops = []\n')
        self.assertEqual((d.kind, d.blame), ("ParamValueKind", "author"))

    def test_two_declarations_of_one_knob_are_refused(self):
        d = self._refusal('a = param("p", 1)\nb = param("p", 2)\nops = []\n')
        self.assertEqual((d.kind, d.blame), ("ParamRedeclared", "author"))
        self.assertEqual(d.line, 2, "отказ обязан назвать СТРОКУ второго объявления")

    def test_a_default_outside_its_OWN_bounds_is_refused(self):
        """Otherwise a program with not a single parameter supplied would
        already be illegitimate, and only whoever moves the knob would
        find out."""
        d = self._refusal('a = param("p", 50, min=1, max=10)\nops = []\n')
        self.assertEqual(d.blame, "author")

    def test_the_same_declaration_twice_is_ALLOWED(self):
        """NARROWNESS CONTROL: `param` is called inside a loop and inside a
        function.

        Banning any repetition would break a legitimate form, and this
        would pass every check above.
        """
        r = _run('vals = [param("p", 2) for _ in range(3)]\n'
                 'ops = [{"op": "query_count", "id": "Q", "kind": "wall"}]\n')
        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertEqual(len(r.params), 1, "одна ручка объявлена трижды — "
                                           "в ведомости обязана быть одна")


class TheKnobObeysTheReplayDiscipline(unittest.TestCase):

    def test_the_same_params_give_a_byte_identical_program_twice(self):
        """`replay_check=True` already runs the script twice and cross-checks
        the digests.

        Green here means the parameters entered the discipline rather than
        bypassed it: had the parent fed them to only the first run, the
        second would have assembled the program on defaults, and that
        would have been a KIR-B010 refusal.
        """
        first = _run(params={"bays": 4})
        second = _run(params={"bays": 4})
        self.assertTrue(first.ok and second.ok)
        self.assertEqual(first.program_digest, second.program_digest)
        self.assertEqual(first.params_digest, second.params_digest)


if __name__ == "__main__":
    unittest.main()


class TheFrameSurvivesAParentOlderThanTheChild(unittest.TestCase):
    """🔴 A FORM BOUGHT BY A BROKEN PROD ON 20.08.2026.

    The rule "edits in the tree do not affect the service until a restart"
    HAS A HOLE EXACTLY IN THE SANDBOX. The parent lives in the service's
    memory and waits for deployment, while the CHILD is a fresh process
    that imports `kir.sandbox` FROM DISK on every launch. The sandbox
    deploys ITSELF, instantly, without anyone's decision.

    The measurement from that day: the service came up at 19:19,
    `sandbox.py` was edited at 20:25 — and the live `program_py` path
    started answering real users with «кадр stdin повреждён». It was not a
    test that broke but prod, and it was broken by a fix that, by all our
    rules, was supposed to wait for a restart.

    Hence the law: THE FRAME MUST SURVIVE A DESYNC. It has only one
    direction — the child is always the freshest, the parent is the same
    version or older — so it is enough for a new child to read an old
    parent's frame. This test is exactly that check: it assembles a frame
    BY HAND in the format predating the version marker and calls the
    child's REAL entry point.
    """

    def _run_legacy_frame(self, source: str) -> dict:
        """A frame WITHOUT a marker: two headers, as the parent wrote them before 20.08."""
        import json
        import os
        import subprocess
        import sys
        import tempfile

        from kir import sandbox as sb

        read_fd, write_fd = os.pipe()
        jail = tempfile.mkdtemp(prefix="kir_legacy_")
        env = {
            "PYTHONPATH": sb._backend_root(),
            "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
            "LC_ALL": "C.UTF-8", "TZ": "UTC", "PATH": "",
            "KIR_SANDBOX_CFG": json.dumps(_POLICY.child_config()),
            "KIR_SANDBOX_RESULT_FD": str(write_fd),
            "KIR_SANDBOX_JAIL": jail,
        }
        raw = source.encode("utf-8")
        frame = b"0\n0\n" + raw            # exactly the previous format
        chunks: list = []
        proc = subprocess.Popen(
            [sys.executable, "-s", "-B", "-c",
             "import kir.sandbox as _s; _s._child_main()"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, cwd=jail,
            pass_fds=(write_fd,), start_new_session=True, close_fds=True)
        try:
            proc.communicate(input=frame, timeout=60)
        finally:
            os.close(write_fd)
            while True:
                block = os.read(read_fd, 65536)
                if not block:
                    break
                chunks.append(block)
            os.close(read_fd)
        return json.loads(b"".join(chunks).decode("utf-8"))

    def test_a_frame_without_the_marker_still_runs(self):
        payload = self._run_legacy_frame(
            'ops = [{"op": "query_count", "id": "Q", "kind": "wall"}]\n')
        self.assertTrue(payload.get("ok"),
                        f"старый кадр не прочитан: {payload.get('refusal')}")
        self.assertEqual(len(payload.get("ops") or []), 1)

    def test_a_legacy_frame_declares_knobs_on_their_defaults(self):
        """The old parent does not send parameters — and this is NOT an
        error.

        Knobs must fall back to defaults rather than refuse: a program
        that is legitimate without parameters stays legitimate until the
        service is restarted.
        """
        payload = self._run_legacy_frame(
            'n = param("bays", 3, min=1, max=8)\n'
            'ops = [{"op": "query_count", "id": f"Q{i}", "kind": "wall"}\n'
            '       for i in range(n)]\n')
        self.assertTrue(payload.get("ok"),
                        f"ручка на старом кадре отказала: {payload.get('refusal')}")
        self.assertEqual(len(payload.get("ops") or []), 3)
        self.assertTrue(payload["params"][0]["used_default"])

    def test_a_frame_from_the_FUTURE_is_named_not_garbled(self):
        """The reverse direction cannot occur by construction — and
        therefore must be named, rather than arrive as «повреждённым
        кадром»."""
        import json
        import os
        import subprocess
        import sys
        import tempfile

        from kir import sandbox as sb
        read_fd, write_fd = os.pipe()
        jail = tempfile.mkdtemp(prefix="kir_future_")
        env = {"PYTHONPATH": sb._backend_root(), "PYTHONHASHSEED": "0",
               "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONNOUSERSITE": "1", "LC_ALL": "C.UTF-8", "TZ": "UTC",
               "PATH": "", "KIR_SANDBOX_CFG": json.dumps(_POLICY.child_config()),
               "KIR_SANDBOX_RESULT_FD": str(write_fd), "KIR_SANDBOX_JAIL": jail}
        chunks: list = []
        proc = subprocess.Popen(
            [sys.executable, "-s", "-B", "-c",
             "import kir.sandbox as _s; _s._child_main()"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, cwd=jail,
            pass_fds=(write_fd,), start_new_session=True, close_fds=True)
        try:
            proc.communicate(input=b"KIRFRAME9\n0\n0\n0\nops = []\n", timeout=60)
        finally:
            os.close(write_fd)
            while True:
                block = os.read(read_fd, 65536)
                if not block:
                    break
                chunks.append(block)
            os.close(read_fd)
        payload = json.loads(b"".join(chunks).decode("utf-8"))
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload["refusal"]["kind"], "FrameVersionAhead")
        self.assertEqual(payload["refusal"]["blame"], "sandbox")
