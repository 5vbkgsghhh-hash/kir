"""Refutation tests for the author-script sandbox (KIR-B*).

The order is deliberate: attacks FIRST, then the happy path. A sandbox
whose happy path is green and whose refusals are unchecked is not a
sandbox — it's a hope.

Each attack test checks TWO things:
  1. the attack is repelled;
  2. the refusal NAMES the mechanism and the limit — otherwise the model
     pays a second round for the same thing (4.8% of compilations on
     03.08 were invented ops, meaning the cost of bad refusals is
     already being paid for live).

The tests touch neither Revit nor prod state: every run is a separate
process with its own limits (64-128 MB and 1-2 s here by default), so the
suite is safe to run on the prod box.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from kir import diag
from kir.sandbox import (
    ALLOWED_IMPORTS,
    SCRIPT_FILENAME,
    SandboxPolicy,
    SandboxResult,
    execute_author_script,
)

# The language (kir/dsl.py) is written by another agent, and its file is
# not touched here. The tests work AGAINST THE CONTRACT: "the language
# module accumulates operations, a drain function hands them out." The
# stub below implements exactly the contract and nothing more.
_STUB_DSL = '''\
"""Заглушка языка: ровно контракт песочницы, ни грамма грамматики."""
_OPS = []


def create_wall(p0_mm, p1_mm, height_mm=3000, id=None):
    op = {"op": "create_wall", "p0_mm": list(p0_mm), "p1_mm": list(p1_mm),
          "height_mm": height_mm}
    if id is not None:
        op["id"] = id
    _OPS.append(op)
    return op


def raw(**kwargs):
    _OPS.append(dict(kwargs))
    return kwargs


def take_ops():
    out = list(_OPS)
    _OPS.clear()
    return out


__all__ = ["create_wall", "raw", "take_ops"]
'''

_TMPDIR = ""


def setUpModule() -> None:
    global _TMPDIR
    _TMPDIR = tempfile.mkdtemp(prefix="kir_sandbox_tests_")
    with open(os.path.join(_TMPDIR, "kir_stub_dsl.py"), "w", encoding="utf-8") as fh:
        fh.write(_STUB_DSL)


def tearDownModule() -> None:
    shutil.rmtree(_TMPDIR, ignore_errors=True)


def policy(**kw) -> SandboxPolicy:
    base = dict(dsl_module="kir_stub_dsl", extra_sys_path=(_TMPDIR,),
                cpu_seconds=1.0, wall_seconds=6.0, memory_mb=128)
    base.update(kw)
    return SandboxPolicy(**base)


def run(source: str, **kw) -> SandboxResult:
    return execute_author_script(source, policy=policy(**kw))


#: escape from restricted builtins — the classic path via subclasses.
#: It WORKS, and this is acknowledged: see the section "WHAT THIS
#: SANDBOX DOES NOT DO". The tests below measure not that there is no
#: escape, but that the escape GAINS NOTHING.
_ESCAPE = (
    "def _real_builtins():\n"
    "    for c in ().__class__.__base__.__subclasses__():\n"
    "        if c.__name__ == 'catch_warnings':\n"
    "            return c()._module.__builtins__\n"
    "    return None\n"
    "B = _real_builtins()\n"
)


class TestRunawayResources(unittest.TestCase):
    """The parent must not be held hostage by someone else's code."""

    def test_infinite_loop_is_stopped_and_the_line_is_named(self) -> None:
        r = run("total = 0\nwhile True:\n    total += 1\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_TIMEOUT)
        # The refusal TEACHES: it names the limit and the reason's
        # version.
        self.assertIn("цикл без выхода", r.refusal.message_ru)
        self.assertIn("процессорного времени", r.refusal.message_ru)
        # And names the model's line — the interrupt is caught by a
        # SIGXCPU handler that sees the script's frame, not ours.
        self.assertEqual(r.refusal.line, 2)
        self.assertIn("while True", r.refusal.line_text)

    def test_string_growth_bomb_hits_a_named_limit(self) -> None:
        # Exactly the script from the task: it runs into either memory or
        # CPU (quadratic string copying), and BOTH refusals must name the
        # limit.
        r = run("x = ''\nwhile True:\n    x += 'a' * 10**6\n",
                cpu_seconds=2.0, memory_mb=128)

        self.assertFalse(r.ok)
        self.assertIn(r.refusal.code,
                      (diag.SANDBOX_MEMORY, diag.SANDBOX_TIMEOUT))
        self.assertRegex(r.refusal.message_ru, r"(128 МБ|процессорного времени)")

    def test_memory_bomb_is_capped_and_the_box_survives(self) -> None:
        r = run("blob = []\nwhile True:\n    blob.append('a' * 10**6)\n",
                memory_mb=64)

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_MEMORY)
        self.assertIn("64 МБ", r.refusal.message_ru)
        self.assertEqual(r.refusal.line, 3)
        # A MEASUREMENT, NOT A PROMISE: the child's peak RSS did not run
        # far past the limit. The box is production, and the sandbox has
        # no right to bring it down.
        # The number is taken from the child's VmHWM and therefore does
        # NOT DEPEND on who ran earlier in the suite (`getrusage` here
        # would lie with the parent's watermark).
        self.assertEqual(r.isolation["peak_rss_source"], "VmHWM")
        self.assertLess(r.peak_rss_kb, 64 * 1024 + 40 * 1024,
                        f"пик RSS {r.peak_rss_kb} КБ при пределе 64 МБ")

    def test_recursion_without_a_base_case_is_typed_not_a_crash(self) -> None:
        r = run("def f(n):\n    return f(n + 1)\n\n\nf(0)\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_RUNTIME)
        self.assertEqual(r.refusal.kind, "RecursionError")
        self.assertEqual(r.refusal.line, 2)
        self.assertIn("базового случая", r.refusal.message_ru)

    def test_wall_clock_backstop_when_cpu_is_idle(self) -> None:
        # CPU time need not be burned: sleeping in C code doesn't spend
        # it. Wall-clock time is the second, independent limit, and it
        # must trigger.
        src = _ESCAPE + (
            "t = B['__import__']('time')\n"
            "t.sleep(30)\n"
        )
        r = run(src, cpu_seconds=10.0, wall_seconds=2.0)

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_TIMEOUT)
        self.assertIn("по стене", r.refusal.message_ru)


class TestImportWhitelist(unittest.TestCase):
    """A whitelist, not a blacklist: a blacklist is always incomplete."""

    def test_import_os_names_the_allowed_set(self) -> None:
        r = run("import os\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertEqual(r.refusal.line, 1)
        self.assertEqual(r.refusal.detail["module"], "os")
        for allowed in ALLOWED_IMPORTS:
            self.assertIn(allowed, r.refusal.message_ru)

    def test_dunder_import_goes_through_the_same_gate(self) -> None:
        r = run("os = __import__('os')\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertEqual(r.refusal.detail["module"], "os")

    def test_from_import_and_relative_import_are_refused(self) -> None:
        r = run("from subprocess import run\n")
        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertEqual(r.refusal.detail["module"], "subprocess")

    def test_random_refusal_explains_why_determinism_is_the_rule(self) -> None:
        r = run("import random\nx = random.random()\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        # The reason is not a matter of taste, and the refusal must
        # carry it.
        self.assertIn("НЕДЕТЕРМИНИЗМ", r.refusal.message_ru)
        self.assertIn("подпис", r.refusal.message_ru)

    def test_time_and_datetime_share_the_determinism_reason(self) -> None:
        for module in ("time", "datetime", "uuid", "secrets"):
            with self.subTest(module=module):
                r = run(f"import {module}\n")
                self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
                self.assertIn("НЕДЕТЕРМИНИЗМ", r.refusal.message_ru)

    def test_socket_refusal_names_the_network_namespace(self) -> None:
        r = run("import socket\ns = socket.socket()\ns.connect(('1.1.1.1', 80))\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertIn("сети нет", r.refusal.message_ru)

    def test_allowed_imports_actually_work(self) -> None:
        r = run("import math\nfrom itertools import product\nimport functools\n"
                "raw(op='x', v=round(math.pi, 3), n=len(list(product('ab', 'cd'))))\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertEqual(r.ops, [{"op": "x", "v": 3.142, "n": 4}])

    def test_importing_the_language_is_refused_with_the_right_advice(self) -> None:
        r = run("import kir_stub_dsl\n")

        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertIn("уже доступен без импорта", r.refusal.message_ru)


class TestForbiddenBuiltins(unittest.TestCase):
    """The name is not "deleted" — it is REPLACED by an explanation.
    `NameError` teaches nothing."""

    def test_open_is_refused_with_a_reason(self) -> None:
        r = run("f = open('/etc/passwd')\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_BUILTIN)
        self.assertEqual(r.refusal.detail["name"], "open")
        self.assertEqual(r.refusal.line, 1)
        self.assertIn("RLIMIT_FSIZE=0", r.refusal.message_ru)

    def test_file_write_attempt_is_refused_at_the_name(self) -> None:
        r = run("open('/tmp/kir_should_not_exist.txt', 'w').write('hi')\n")

        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_BUILTIN)
        self.assertFalse(os.path.exists("/tmp/kir_should_not_exist.txt"))

    def test_eval_exec_compile_are_refused_for_a_named_reason(self) -> None:
        for name, src in (("eval", "eval('1+1')"),
                          ("exec", "exec('x = 1')"),
                          ("compile", "compile('x', 'f', 'exec')")):
            with self.subTest(builtin=name):
                r = run(src + "\n")
                self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_BUILTIN)
                self.assertEqual(r.refusal.detail["name"], name)
                self.assertIn("подпис", r.refusal.message_ru)

    def test_id_is_refused_as_a_nondeterminism_source(self) -> None:
        r = run("raw(op='x', v=id(object()))\n")

        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_BUILTIN)
        self.assertIn("адрес объекта", r.refusal.message_ru)


class TestEscapeBuysNothing(unittest.TestCase):
    """Escaping restricted builtins IS POSSIBLE (CPython is not closed
    off by anything short of a separate process) — so what we measure is
    not its absence but its uselessness: every OS layer absorbs the hit
    on its own."""

    def _escaped(self, body: str, **kw) -> SandboxResult:
        return run(_ESCAPE + body + "raw(op='marker')\n", **kw)

    def test_escape_itself_succeeds_and_that_is_admitted(self) -> None:
        r = self._escaped("print('ESCAPED' if B and '__import__' in B else 'NO')\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertIn("ESCAPED", r.stdout)

    def test_reading_etc_passwd_through_real_builtins_finds_nothing(self) -> None:
        # Mechanism: chroot into an empty directory AFTER all imports.
        r = self._escaped(
            "try:\n"
            "    print('READ:' + B['open']('/etc/passwd').read()[:20])\n"
            "except BaseException as e:\n"
            "    print('BLOCKED:' + type(e).__name__)\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertIn("BLOCKED:FileNotFoundError", r.stdout)
        self.assertNotIn("READ:", r.stdout)

    def test_filesystem_is_empty_even_for_escaped_code(self) -> None:
        r = self._escaped("o = B['__import__']('os')\nprint('ROOT:', o.listdir('/'))\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertIn("ROOT: []", r.stdout)

    def test_network_is_unreachable_for_escaped_code(self) -> None:
        # Mechanism: a separate network namespace with not a single
        # route.
        r = self._escaped(
            "s = B['__import__']('socket')\n"
            "try:\n"
            "    c = s.socket(); c.settimeout(2.0); c.connect(('1.1.1.1', 80))\n"
            "    print('CONNECTED')\n"
            "except BaseException as e:\n"
            "    print('BLOCKED:%s:%s' % (type(e).__name__, getattr(e, 'errno', '')))\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertIn("BLOCKED:OSError:101", r.stdout)      # ENETUNREACH
        self.assertNotIn("CONNECTED", r.stdout)

    def test_file_content_cannot_be_written_even_by_escaped_code(self) -> None:
        # Mechanism: RLIMIT_FSIZE=0. An empty inode can be created
        # (creation is not writing), but not a single BYTE of content
        # gets through, and the root directory is removed by the parent
        # regardless.
        r = self._escaped(
            "o = B['__import__']('os')\n"
            "try:\n"
            "    fd = o.open('/escape.txt', o.O_WRONLY | o.O_CREAT)\n"
            "    o.write(fd, b'payload')\n"
            "    print('WROTE')\n"
            "except BaseException as e:\n"
            "    print('BLOCKED:%s:%s' % (type(e).__name__, getattr(e, 'errno', '')))\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertIn("BLOCKED:OSError:27", r.stdout)       # EFBIG
        self.assertNotIn("WROTE", r.stdout)

    def test_fork_and_subprocess_are_blocked_for_escaped_code(self) -> None:
        # Mechanism: RLIMIT_NPROC=0 — no fork, no spawn.
        r = self._escaped(
            "o = B['__import__']('os')\n"
            "try:\n"
            "    pid = o.fork()\n"
            "    print('FORKED')\n"
            "except BaseException as e:\n"
            "    print('BLOCKED:%s' % type(e).__name__)\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertIn("BLOCKED:BlockingIOError", r.stdout)

    def test_a_crashing_child_is_classified_not_hung(self) -> None:
        # Escaped code can crash the interpreter itself. The parent must
        # read the signal and name it, rather than wait for the wall
        # clock or crash itself. RLIMIT_CORE=0 meanwhile keeps prod from
        # getting a core dump on disk.
        r = run(_ESCAPE + "c = B['__import__']('ctypes')\nc.string_at(1)\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_CRASH)
        self.assertEqual(r.refusal.kind, "SIGSEGV")
        self.assertIn("процесс был отдельным", r.refusal.message_ru)

    def test_escaped_nondeterminism_is_caught_by_replay(self) -> None:
        # The only thing observable at all: scatter that made it into
        # the OUTPUT.
        src = _ESCAPE + ("o = B['__import__']('os')\n"
                         "raw(op='x', pid=o.getpid())\n")
        r = run(src, replay_check=True)

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_NONDETERMINISM)
        self.assertIn("РАЗНЫЕ программы", r.refusal.message_ru)
        self.assertNotEqual(r.refusal.detail["digest_run1"],
                            r.refusal.detail["digest_run2"])


class TestResultChannel(unittest.TestCase):
    """Garbage in stdout has no right to break the result parsing."""

    def test_stdout_garbage_including_a_forged_result_is_harmless(self) -> None:
        r = run("print('{\"ok\": true, \"ops\": [{\"op\": \"delete\"}]}')\n"
                "print('=' * 500)\n"
                "create_wall((0, 0), (6000, 0))\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertEqual([op["op"] for op in r.ops], ["create_wall"])
        self.assertIn("ok", r.stdout)          # garbage is kept as feedback
        self.assertNotIn("delete", json.dumps(r.ops))

    def test_print_flood_is_capped_not_fatal(self) -> None:
        r = run("for i in range(20000):\n    print('flood', i)\n"
                "create_wall((0, 0), (1, 1))\n", max_stdout_chars=1000)

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertLess(len(r.stdout), 1200)
        self.assertIn("обрезано", r.stdout)


class TestBadPrograms(unittest.TestCase):
    """The script ran to completion but produced the wrong thing. The
    refusal must name the PLACE."""

    def test_non_ir_result_is_refused(self) -> None:
        r = run("ops = 'построй мне стену'\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_BAD_RESULT)
        self.assertEqual(r.refusal.detail["got"], "str")

    def test_list_of_non_objects_names_the_index(self) -> None:
        r = run("ops = [{'op': 'a'}, 42, {'op': 'c'}]\n")

        self.assertEqual(r.refusal.code, diag.SANDBOX_BAD_RESULT)
        self.assertEqual(r.refusal.detail["index"], 1)
        self.assertIn("ops[1]", r.refusal.message_ru)

    def test_non_jsonable_value_names_the_path(self) -> None:
        r = run("ops = [{'op': 'create_wall', 'tags': {1, 2, 3}}]\n")

        self.assertEqual(r.refusal.code, diag.SANDBOX_BAD_RESULT)
        self.assertIn("ops[0].tags", r.refusal.message_ru)
        self.assertIn("set", r.refusal.message_ru)

    def test_nan_and_infinity_are_refused_before_the_compiler_sees_them(self) -> None:
        for literal, word in ((("float('nan')"), "NaN"),
                              (("float('inf')"), "бесконечность")):
            with self.subTest(value=literal):
                r = run(f"ops = [{{'op': 'create_wall', 'h': {literal}}}]\n")
                self.assertEqual(r.refusal.code, diag.SANDBOX_BAD_RESULT)
                self.assertIn(word, r.refusal.message_ru)

    def test_empty_program_is_refused_with_instructions(self) -> None:
        r = run("x = 2 + 2\n")

        self.assertEqual(r.refusal.code, diag.SANDBOX_NO_OPS)
        self.assertIn("ops", r.refusal.message_ru)

    def test_transport_cap_names_both_budgets(self) -> None:
        r = run("ops = [{'op': 'x', 'i': i} for i in range(300)]\n", max_ops=100)

        self.assertEqual(r.refusal.code, diag.SANDBOX_OUTPUT_LIMIT)
        # The sandbox's transport ceiling IS NOT the compiler's budget,
        # and the refusal must say so: otherwise the fix goes to the
        # wrong place (see KIR-L001).
        self.assertIn("100", r.refusal.message_ru)
        # 🔴 IT USED TO BE `assertIn("20 авторских", ...)` — the test WAS
        # PINNING A FALSEHOOD. The real author budget is 1000, not 20;
        # the refusal text is read by the model, which cuts the program
        # down by it, fifty times over. A guard that guards a wrong
        # number does not protect — it FORBIDS THE FIX: editing the
        # message would have turned it red, and so the message survived
        # even after the same numbers had already been removed from the
        # neighboring comment. Now we guard the LAW: the refusal must
        # point to the NAME of the limit, not state its value.
        self.assertIn("MAX_OPS_PER_PROGRAM", r.refusal.message_ru)
        self.assertNotIn("20 авторских", r.refusal.message_ru)

    def test_object_address_in_output_is_refused(self) -> None:
        r = run("class Marker:\n    pass\n\n\nraw(op='x', name=str(Marker()))\n")

        self.assertEqual(r.refusal.code, diag.SANDBOX_NONDETERMINISM)
        self.assertIn("адрес объекта", r.refusal.message_ru)

    def test_syntax_error_carries_the_line_and_its_text(self) -> None:
        r = run("for i in range(3)\n    create_wall((0, 0), (1, 1))\n")

        self.assertEqual(r.refusal.code, diag.SANDBOX_SYNTAX)
        self.assertEqual(r.refusal.line, 1)
        self.assertIn("for i in range(3)", r.refusal.line_text)

    def test_runtime_error_names_the_innermost_script_line(self) -> None:
        r = run("def helper(i):\n"
                "    return 100 / i\n"
                "\n"
                "\n"
                "for i in (2, 1, 0):\n"
                "    raw(op='x', v=helper(i))\n")

        self.assertEqual(r.refusal.code, diag.SANDBOX_RUNTIME)
        self.assertEqual(r.refusal.kind, "ZeroDivisionError")
        self.assertEqual(r.refusal.line, 2)          # where it failed
        self.assertEqual(r.refusal.script_frames, [6, 2])   # and where it was called from

    def test_empty_source_is_refused(self) -> None:
        r = run("   \n\n")
        self.assertEqual(r.refusal.code, diag.SANDBOX_NO_OPS)

    def test_oversized_source_is_refused_before_spawning(self) -> None:
        r = run("x = 1\n" * 100000, max_source_bytes=4096)
        self.assertEqual(r.refusal.code, diag.SANDBOX_OUTPUT_LIMIT)
        self.assertIn("данные вместо кода", r.refusal.message_ru)


class TestRefusalHygiene(unittest.TestCase):
    """What the model must fix is ITS OWN code: our own frames must never
    appear in the refusal."""

    def test_no_internal_frames_leak_into_any_refusal(self) -> None:
        sources = [
            "import os\n",
            "open('/etc/passwd')\n",
            "1 / 0\n",
            "ops = 'nope'\n",
            "def f():\n    return f()\nf()\n",
            "for i in range(3)\n    pass\n",
        ]
        for src in sources:
            with self.subTest(src=src.splitlines()[0]):
                r = run(src)
                self.assertFalse(r.ok)
                text = r.refusal.render() + json.dumps(
                    r.refusal.detail, ensure_ascii=False)
                for internal in ("Traceback", "sandbox.py", "kir",
                                 "_child_main", 'File "', SCRIPT_FILENAME):
                    self.assertNotIn(internal, text)

    def test_every_refusal_is_a_registered_b_code(self) -> None:
        known = {v for k, v in vars(diag).items()
                 if k.startswith("SANDBOX_") and isinstance(v, str)}
        # 12 -> 13 (18.08.2026): `SANDBOX_RECON` = `KIR-B013` was set up,
        # a third KIND OF ANSWER (a reconnaissance move), not a
        # thirteenth refusal. The number here is handwritten on purpose:
        # it IS the ratchet — new code must go red here and demand a
        # DECISION, rather than arrive silently.
        #
        # 13 -> 14 (20.08.2026): `SANDBOX_PARAM` = `KIR-B014`, a slider.
        # THE DECISION the ratchet demanded: a separate code, not
        # `KIR-B006` ("the script threw an exception"), because the
        # CALLER is more often at fault — it passed a name the author
        # never declared, or a value out of bounds — and its fix is
        # different: not editing the script, but fixing the parameter
        # set. Code that sends the fix to the wrong place is a named
        # defect of this tree. The address of the fix is carried by
        # every refusal's `blame`, by name.
        #
        # 14 -> 15 (25.08.2026): `SANDBOX_UNREAD` = `KIR-B015`, "asked
        # about something WE never read." THE DECISION the ratchet
        # demanded, with the same argument as B014, only measured:
        #
        #     probe                code      BLAME    what the PROSE said
        #     building not supplied  KIR-B006  author   «факт о НАШЕМ чтении»
        #     census                  KIR-B006  author   «факт о НАШЕМ чтении»
        #     building levels         KIR-B006  author   «факт о НАШЕМ чтении»
        #     catalog not supplied    KIR-B006  author   «спрашивать нечего»
        #     element by address      KIR-B006  author   «факт о НАШЕМ чтении»
        #     CONTROL 1/0             KIR-B006  author   division by zero
        #
        # Five gaps in OUR OWN reading were indistinguishable from `1/0`
        # — neither by code nor by blame — even though their own prose
        # said the opposite. The blame field lied on a CORRECT script,
        # and the model went off to rewrite it. A separate code, not
        # just `blame`: a machine cannot see a distinction carried by
        # prose alone, and the receipt is read by more than one eye.
        #
        # 15 -> 16 (02.09.2026): `SANDBOX_CAPABILITY_ABSENT` = `KIR-B016`,
        # "permitted, but NOT INSTALLED in this environment" (E-85). THE
        # DECISION the ratchet demanded, with the same argument as B015,
        # only MEASURED by a run of a real sandbox (a `/usr/bin/python3`
        # child without shapely, `shapely` on the whitelist):
        #
        #     probe                       code      BLAME    what the PROSE said
        #     import shapely.geometry     KIR-B004  author   «НЕ твоя строка»
        #     import shapely              KIR-B006  author   «No module named»
        #     CONTROL import socket       KIR-B004  author   «сети нет вовсе»
        #
        # THREE places produced a fact ABOUT THE ENVIRONMENT ("install
        # the package") with a code that blamed the AUTHOR,
        # indistinguishable from a genuine ban — and the worst part:
        # `KIR-B004` "import forbidden" was printed on the line where
        # the CALL stood, not the import (a lazy import inside OUR OWN
        # code). The prose, since 01.09, told the truth; the
        # machine-readable half did not.
        #
        # A separate code, not just `blame`: a machine cannot see a
        # distinction carried by prose alone. The control stayed
        # author-blamed — the real ban did not move.
        self.assertEqual(len(known), 16)
        for code in known:
            self.assertRegex(code, r"^KIR-B0\d\d$")
        for src in ("import os\n", "1/0\n", "ops = 5\n", "x = (\n"):
            r = run(src)
            self.assertIn(r.refusal.code, known)

    def test_refusal_projects_onto_the_compiler_diagnostic_envelope(self) -> None:
        r = run("import os\n")
        d = r.refusal.to_diagnostic()

        self.assertEqual(d.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertIn("строка 1", d.message_ru)
        self.assertIn("import os", d.message_ru)

    def test_blame_separates_our_defect_from_the_authors(self) -> None:
        author = run("import os\n")
        self.assertEqual(author.refusal.blame, "author")

        # There being no language at all is OUR OWN defect, and it must
        # not look like a mistake by the model ("name is not defined"
        # would send it off to fix something that isn't broken).
        ours = run("create_wall((0, 0), (1, 1))\n", dsl_module="no_such_dsl_module")
        self.assertEqual(ours.refusal.code, diag.SANDBOX_UNAVAILABLE)
        self.assertEqual(ours.refusal.blame, "sandbox")
        self.assertIn("не загрузился", ours.refusal.message_ru)

    def test_sandbox_never_raises_even_when_it_is_broken(self) -> None:
        r = execute_author_script(
            "raw(op='x')\n",
            policy=policy(python_exe="/nonexistent/python"))

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_UNAVAILABLE)
        self.assertEqual(r.refusal.blame, "sandbox")


class TestIsolationIsMeasured(unittest.TestCase):
    """Isolation is proven by measurement on every run, not by intent."""

    def test_every_run_reports_the_measured_isolation(self) -> None:
        r = run("raw(op='x')\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        iso = r.isolation
        self.assertEqual(iso["namespaces"], "user+mount+net")
        self.assertEqual(iso["filesystem"], "chroot")
        self.assertTrue(iso["network_probe"].startswith("unreachable"),
                        iso["network_probe"])
        self.assertEqual(iso["limits"]["RLIMIT_FSIZE"], 0)
        self.assertEqual(iso["limits"]["RLIMIT_NPROC"], 0)
        self.assertEqual(iso["limits"]["RLIMIT_CORE"], 0)
        self.assertEqual(iso["uid"], 65534)      # nobody in its own user namespace

    def test_network_isolation_is_attributed_by_a_control_run(self) -> None:
        # THE CONTROL EXPERIMENT. "The network is unreachable" proves
        # nothing by itself — it could be unreachable without us too. So
        # we compare the network namespace identifier against the
        # parent's: with isolation it is DIFFERENT, without it — THE
        # SAME. Nobody touches the wires in the process.
        mine = os.readlink("/proc/self/ns/net")

        isolated = run("raw(op='x')\n", network="required", probe_network=False)
        self.assertTrue(isolated.ok)
        self.assertNotEqual(isolated.isolation["netns"], mine)

        # No user namespace here also means no chroot capability. This is an
        # explicit unisolated negative control, not a filesystem fallback.
        control = run("raw(op='x')\n", network="off", probe_network=False,
                      filesystem_isolation=False)
        self.assertTrue(control.ok)
        self.assertEqual(control.isolation["netns"], mine)
        self.assertEqual(control.isolation["namespaces"], "off")

    def test_filesystem_isolation_is_attributed_by_a_control_run(self) -> None:
        # The same technique for the filesystem: with chroot the root is
        # empty, without it — it isn't. So it is chroot that closes off
        # /etc/passwd, not a coincidence.
        body = ("o = B['__import__']('os')\nprint('ROOT:', sorted(o.listdir('/'))[:3])\n"
                "raw(op='marker')\n")

        control = run(_ESCAPE + body, filesystem_isolation=False)
        self.assertTrue(control.ok, control.refusal.render() if control.refusal else "")
        self.assertNotIn("ROOT: []", control.stdout)
        self.assertEqual(control.isolation["filesystem"], "off")

        isolated = run(_ESCAPE + body, filesystem_isolation=True)
        self.assertTrue(isolated.ok)
        self.assertIn("ROOT: []", isolated.stdout)

    def test_peak_rss_belongs_to_this_run_and_not_to_the_caller(self) -> None:
        """A REGRESSION AGAINST ITS OWN DEFECT (03.08).

        The first edition took the peak from the CHILD's
        `getrusage(RUSAGE_SELF)`, which is inherited from the parent via
        fork. Standalone, the tests were green; in the full suite, two
        failed: by then the pytest process had bloated up, and the child
        reported SOMEONE ELSE's watermark as its own. "Passes standalone"
        is not an excuse: a red test in the suite trains people to stop
        reading red at all.

        Here the defect is reproduced on purpose: we bloat the CALLER
        and require that the run's reading not notice it."""
        light = "raw(op='x')\n"
        lean = run(light)
        self.assertTrue(lean.ok, lean.refusal.render() if lean.refusal else "")

        ballast = ["x" * (10 ** 6) for _ in range(150)]   # ~150 MB in the parent
        try:
            fat = run(light)
        finally:
            del ballast

        self.assertTrue(fat.ok, fat.refusal.render() if fat.refusal else "")
        self.assertEqual(fat.isolation["peak_rss_source"], "VmHWM")
        self.assertLess(fat.peak_rss_kb, 100 * 1024,
                        f"пик запуска {fat.peak_rss_kb} КБ втянул в себя "
                        f"память вызывающего")
        # A lean caller and a bloated one give THE SAME order of
        # magnitude.
        self.assertLess(abs(fat.peak_rss_kb - lean.peak_rss_kb), 20 * 1024)

    def test_hash_seed_is_pinned_so_set_order_is_stable(self) -> None:
        src = "s = set('abcdefghijklmnop')\nraw(op='x', order=''.join(s))\n"
        first = run(src)
        second = run(src)

        self.assertTrue(first.ok and second.ok)
        self.assertEqual(first.program_digest, second.program_digest)
        # And this is NOT trivial: without pinning the seed, the same
        # search jumps around.
        seen = set()
        for _ in range(6):
            out = subprocess.run(
                [sys.executable, "-c",
                 "print(''.join(set('abcdefghijklmnop')))"],
                capture_output=True, text=True,
                env={"PATH": os.environ.get("PATH", "")})
            seen.add(out.stdout.strip())
        self.assertGreater(len(seen), 1,
                           "без PYTHONHASHSEED порядок обязан плясать")

    def test_replay_check_accepts_a_deterministic_script(self) -> None:
        r = run("for i in range(4):\n"
                "    create_wall((0, i * 3000), (6000, i * 3000))\n",
                replay_check=True)

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertTrue(r.isolation["replay_checked"])
        self.assertEqual(len(r.ops), 4)


class TestHappyPath(unittest.TestCase):
    """The contract with the language: three ways to hand off a program,
    one result."""

    def test_language_drain_is_the_primary_route(self) -> None:
        r = run("for i in range(3):\n"
                "    create_wall((0, i * 3000), (6000, i * 3000), height_mm=2700)\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertEqual(len(r.ops), 3)
        self.assertEqual(r.ops[2],
                         {"op": "create_wall", "p0_mm": [0, 6000],
                          "p1_mm": [6000, 6000], "height_mm": 2700})
        self.assertEqual(r.isolation["harvest"], "dsl.take_ops()")
        self.assertEqual(len(r.author_digest), 64)
        self.assertEqual(len(r.program_digest), 64)

    def test_plain_list_of_dicts_also_works(self) -> None:
        r = run("ops = [{'op': 'create_grid', 'name': 'A'}]\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertEqual(r.isolation["harvest"], "ns.ops")

    def test_build_function_also_works(self) -> None:
        r = run("def build():\n    return [{'op': 'create_level', 'z_mm': 3000}]\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertEqual(r.ops[0]["z_mm"], 3000)
        self.assertEqual(r.isolation["harvest"], "build()")

    def test_envelope_fields_survive(self) -> None:
        r = run("ops = {'intent': 'коробка 6x6', 'ops': [{'op': 'create_wall'}]}\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertEqual(r.envelope["intent"], "коробка 6x6")
        self.assertEqual(len(r.ops), 1)

    def test_author_digest_signs_the_exact_source(self) -> None:
        import hashlib
        src = "raw(op='x')\n"
        r = run(src)
        self.assertEqual(r.author_digest,
                         hashlib.sha256(src.encode("utf-8")).hexdigest())

    def test_a_real_scripted_program_is_cheap(self) -> None:
        # The run count the language exists for: 40 walls in a circle.
        r = run("import math\n"
                "R = 12000\n"
                "N = 40\n"
                "pts = [(R * math.cos(2 * math.pi * i / N),\n"
                "        R * math.sin(2 * math.pi * i / N)) for i in range(N + 1)]\n"
                "for a, b in zip(pts, pts[1:]):\n"
                "    create_wall((round(a[0]), round(a[1])),\n"
                "                (round(b[0]), round(b[1])), height_mm=3300)\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertEqual(len(r.ops), 40)
        self.assertLess(r.duration_s, 3.0)
        self.assertLess(r.peak_rss_kb, 64 * 1024)

    def test_result_serialises_for_the_receipt(self) -> None:
        r = run("raw(op='x')\n")
        blob = json.dumps(r.as_dict(), ensure_ascii=False)

        self.assertIn("author_digest", blob)
        self.assertIn("isolation", blob)
        self.assertEqual(json.loads(blob)["op_count"], 1)


try:                                  # the language is written by another agent — not our file
    from kir import dsl as _dsl
except Exception:                     # pragma: no cover
    _dsl = None


@unittest.skipIf(_dsl is None, "kir/dsl.py ещё не приземлился")
class TestSeamWithTheRealLanguage(unittest.TestCase):
    """The whole seam: the model's python → sandbox → plan_program.

    The test is LIVE and deliberately thin: it checks the joint, not the
    language's grammar (that is checked by another agent's
    test_dsl.py)."""

    def test_script_becomes_a_planned_program(self) -> None:
        from kir.compiler import plan_program

        r = execute_author_script(
            "import math\n"
            "envelope(intent='кольцо стен на трёх этажах')\n"
            "for i in range(3):\n"
            "    lv = create_level(name='L%d' % (i + 1), elev_mm=i * 3300)\n"
            "    R = 12000 - i * 400\n"
            "    pts = [(round(R * math.cos(2 * math.pi * k / 12)),\n"
            "            round(R * math.sin(2 * math.pi * k / 12)))\n"
            "           for k in range(13)]\n"
            "    for a, b in zip(pts, pts[1:]):\n"
            "        create_wall(level=by_ref(lv), p0_mm=list(a), p1_mm=list(b),\n"
            "                    height_mm=3300)\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertEqual(len(r.ops), 39)
        self.assertEqual(r.envelope["intent"], "кольцо стен на трёх этажах")
        self.assertEqual(r.isolation["harvest"], "dsl.take_ops()")

        program = dict(r.envelope)
        program["ops"] = r.ops
        plan = plan_program(program, bulk=True)
        self.assertEqual(len(plan.ops), 39)

    def test_language_misuse_comes_back_as_a_typed_refusal_with_a_line(self) -> None:
        r = execute_author_script(
            "lv = create_level(name='L1', elev_mm=0)\n"
            "create_wall(level=by_ref(lv))\n")

        self.assertFalse(r.ok)
        # 🔴 THIS TEST'S NAME NAMED THE LAW, WHILE THE `assert` WAS
        # PINNING ITS VIOLATION. The test is called "comes back as a
        # TYPED refusal", yet it required `SANDBOX_RUNTIME` — the
        # generic code "the script threw an exception" — which has no
        # type at all. The language's real code was buried INSIDE THE
        # TEXT (`"DslRefusal: KIR-P005: …"`), and there was nothing to
        # branch on. Fixed on 25.08 together with the door itself:
        # `KirRefusal` got its own branch in `fail_from_exception`, as
        # required by `DslRefusal`'s docstring ("the caller — sandbox,
        # script, repair loop — has one single branch for handling all
        # of KIR's typed refusals").
        self.assertEqual(r.refusal.code, "KIR-P005")
        self.assertEqual(r.refusal.blame, "author")
        self.assertEqual(r.refusal.line, 2)
        self.assertNotIn("dsl.py", r.refusal.render())

    def test_empty_program_through_the_real_language(self) -> None:
        r = execute_author_script("x = 2 + 2\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_NO_OPS)

    def test_the_form_of_an_op_is_readable_INSIDE_the_script(self) -> None:
        """A POINTER ⟺ REACHABILITY, and here the red half of the seam
        is this one.

        Since 04.08, TWO refusals reference `print(<op>.__doc__)`:
        `help` among the forbidden builtins
        (`sandbox._FORBIDDEN_BUILTINS`) and the slot arithmetic
        (`dsl._bind_refusal`). Advertising something unreachable costs
        the model a round — exactly the round both pointers were
        written to save. So the capability is checked by EXECUTION, not
        by reading the code.
        """
        r = execute_author_script(
            "print(create_railing.__doc__)\n"
            "create_level(elev_mm=0, name='Э1')\n")

        self.assertTrue(r.ok, getattr(r.refusal, "message_ru", ""))
        # Slots, the parameter kind, and mandatoriness — what the
        # measurement was worth.
        for expected in ("variety", "enum{path|hosted}", "ОБЯЗАТЕЛЬНЫЙ",
                         "ПОСТУСЛОВИЕ"):
            self.assertIn(expected, r.stdout, expected)

    def test_the_help_refusal_names_the_route_that_actually_exists(self) -> None:
        """`help` remains forbidden, but the refusal must name the NEXT
        MOVE. Before 04.08 it pointed "to the hint": correct and
        useless — the hint does not answer "what slots does THIS op
        have"."""
        r = execute_author_script("help(create_wall)\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_BUILTIN)
        self.assertIn("__doc__", r.refusal.message_ru)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()


class ТипизированныйОтказЯзыкаДоезжаетДоАвтора(unittest.TestCase):
    """🔴 MEASUREMENT 25.08.2026: THE SCRIPT DOOR WAS DESTROYING THE
    REFUSAL'S CODE.

    `DslRefusal` inherits `KirRefusal` ON PURPOSE, and its docstring
    names the callers by name: "the caller (SANDBOX, script, repair
    loop) has one single branch for handling all of KIR's typed
    refusals." The sandbox was named and had no branch: a typed refusal
    fell into the `else` together with any script exception.

    A run, a program missing a mandatory slot:

        code       = 'KIR-B006'   ← «скрипт бросил исключение», вина СКРИПТА
        message_ru = 'DslRefusal: KIR-P005: … не задан ОБЯЗАТЕЛЬНЫЙ слот …'

    The real code is buried in the TEXT. `field_name`, `candidates`,
    `expected`, `got` don't make it through at all. Branching on the
    code — `skill.REFUSAL_PLAYBOOK`, the repair loop — does not work at
    this door, and the model fixes a correct script based on the hint
    "the script threw an exception."

    THE COST, BY THE CONSTITUTION. KIR's main user is an LLM, and the
    measure of any piece of work is how many times checkability changed
    its decision. A refusal you cannot branch on changes no decision.
    """

    @staticmethod
    def _отказ(скрипт: str):
        from kir.sandbox import execute_author_script
        итог = execute_author_script(скрипт)
        assert not итог.ok, "стенд негоден: программа не отказала"
        return итог.refusal

    def test_код_отказа_языка_доезжает_полем_а_не_текстом(self):
        отк = self._отказ("create_wall(id='w1', p0_mm=[0,0])\n")
        self.assertEqual(
            отк.code, "KIR-P005",
            f"код отказа языка подменён на {отк.code!r}: вина переложена "
            f"со СЛОТА на скрипт, и ветвиться по коду нечем")

    def test_дубль_идентификатора_несёт_свой_код(self):
        отк = self._отказ(
            "create_wall(id='w1', p0_mm=[0,0], p1_mm=[4000,0],"
            " height_mm=3000, level='Этаж 1')\n"
            "create_wall(id='w1', p0_mm=[0,0], p1_mm=[4000,0],"
            " height_mm=3000, level='Этаж 1')\n")
        self.assertEqual(отк.code, "KIR-P006")

    def test_поля_ремонта_доезжают(self):
        """A code without fields is half an answer: what needs fixing
        is the NAMED slot."""
        отк = self._отказ("create_wall(id='w1', p0_mm=[0,0])\n")
        self.assertTrue(
            отк.detail.get("field_name") or отк.detail.get("expected"),
            f"поля ремонта пусты: {отк.detail!r}")

    def test_вина_на_программе_а_не_на_скрипте(self):
        отк = self._отказ("create_wall(id='w1', p0_mm=[0,0])\n")
        self.assertEqual(отк.blame, "author")

    def test_КОНТРОЛЬ_настоящее_исключение_скрипта_остаётся_собой(self):
        """The instrument must DISTINGUISH. If everything became a
        language refusal, the door would stop telling a script error
        apart from a program refusal."""
        отк = self._отказ("raise ValueError('я сломал скрипт')\n")
        self.assertEqual(отк.code, "KIR-B006")
        self.assertEqual(отк.kind, "ValueError")

    def test_КОНТРОЛЬ_запрещённый_импорт_по_прежнему_свой(self):
        отк = self._отказ("import os\n")
        self.assertNotEqual(отк.code, "KIR-B006")
        self.assertEqual(отк.kind, "ForbiddenImport")
