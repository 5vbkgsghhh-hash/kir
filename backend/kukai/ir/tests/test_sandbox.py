"""Опровергающие тесты песочницы авторских скриптов (KIR-B*).

Порядок намеренный: СНАЧАЛА атаки, потом счастливый путь. Песочница, у которой
зелёный счастливый путь и непроверенные отказы, — это не песочница, а надежда.

Каждый тест атаки проверяет ДВЕ вещи:
  1. атака отбита;
  2. отказ НАЗЫВАЕТ механизм и предел — иначе модель платит вторым раундом
     за то же самое (4.8% компиляций 03.08 — выдуманные опы, то есть цена
     плохих отказов уже оплачивается живьём).

Тесты не трогают ни Revit, ни прод-состояние: каждый запуск — отдельный
процесс со своими пределами (по умолчанию здесь 64-128 МБ и 1-2 с), поэтому
набор безопасно гонять на прод-боксе.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from kukai.ir import diag
from kukai.ir.sandbox import (
    ALLOWED_IMPORTS,
    SCRIPT_FILENAME,
    SandboxPolicy,
    SandboxResult,
    execute_author_script,
)

# Язык (kukai/ir/dsl.py) пишет другой агент, и его файл здесь не трогается.
# Тесты работают ПРОТИВ КОНТРАКТА: «модуль языка копит операции, drain-функция
# их отдаёт». Заглушка ниже реализует ровно контракт и ничего больше.
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


#: побег из ограниченных builtins — классический путь через subclasses.
#: Он РАБОТАЕТ, и это признано: см. §«ЧЕГО ЭТА ПЕСОЧНИЦА НЕ ДЕЛАЕТ».
#: Тесты ниже меряют не то, что побега нет, а то, что побег НИЧЕГО НЕ ДАЁТ.
_ESCAPE = (
    "def _real_builtins():\n"
    "    for c in ().__class__.__base__.__subclasses__():\n"
    "        if c.__name__ == 'catch_warnings':\n"
    "            return c()._module.__builtins__\n"
    "    return None\n"
    "B = _real_builtins()\n"
)


class TestRunawayResources(unittest.TestCase):
    """Родитель не должен быть заложником чужого кода."""

    def test_infinite_loop_is_stopped_and_the_line_is_named(self) -> None:
        r = run("total = 0\nwhile True:\n    total += 1\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_TIMEOUT)
        # Отказ УЧИТ: называет предел и версию причины.
        self.assertIn("цикл без выхода", r.refusal.message_ru)
        self.assertIn("процессорного времени", r.refusal.message_ru)
        # И называет строку модели — прерывание снято обработчиком SIGXCPU,
        # который видит кадр скрипта, а не наш.
        self.assertEqual(r.refusal.line, 2)
        self.assertIn("while True", r.refusal.line_text)

    def test_string_growth_bomb_hits_a_named_limit(self) -> None:
        # Ровно тот скрипт из задания: он упирается либо в память, либо в CPU
        # (квадратичное копирование строки), и ОБА отказа обязаны назвать предел.
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
        # ЗАМЕР, А НЕ ОБЕЩАНИЕ: пик RSS ребёнка не ушёл далеко за предел.
        # Бокс продакшен, и песочница не имеет права его ронять.
        # Число берётся из VmHWM ребёнка и потому НЕ ЗАВИСИТ от того, кто
        # бежал в суите раньше (getrusage здесь врал бы водоразделом родителя).
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
        # Процессорное время можно не жечь: сон в C-коде его не тратит.
        # Стена — второй, независимый предел, и он обязан сработать.
        src = _ESCAPE + (
            "t = B['__import__']('time')\n"
            "t.sleep(30)\n"
        )
        r = run(src, cpu_seconds=10.0, wall_seconds=2.0)

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_TIMEOUT)
        self.assertIn("по стене", r.refusal.message_ru)


class TestImportWhitelist(unittest.TestCase):
    """Белый список, а не чёрный: чёрный всегда неполон."""

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
        # Причина не вкусовая, и отказ обязан её нести.
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
    """Имя не «удалено» — оно ЗАМЕНЕНО объяснением. NameError ничему не учит."""

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
    """Побег из ограниченных builtins ВОЗМОЖЕН (CPython не закрывается ничем,
    кроме отдельного процесса) — поэтому меряем не его отсутствие, а его
    бесполезность: каждый слой ОС держит удар отдельно."""

    def _escaped(self, body: str, **kw) -> SandboxResult:
        return run(_ESCAPE + body + "raw(op='marker')\n", **kw)

    def test_escape_itself_succeeds_and_that_is_admitted(self) -> None:
        r = self._escaped("print('ESCAPED' if B and '__import__' in B else 'NO')\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertIn("ESCAPED", r.stdout)

    def test_reading_etc_passwd_through_real_builtins_finds_nothing(self) -> None:
        # Механизм: chroot в пустой каталог ПОСЛЕ всех импортов.
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
        # Механизм: отдельное сетевое пространство имён без единого маршрута.
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
        # Механизм: RLIMIT_FSIZE=0. Пустой inode создать можно (создание — не
        # запись), но ни одного БАЙТА содержимого не проходит, и каталог-корень
        # всё равно снимается родителем.
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
        # Механизм: RLIMIT_NPROC=0 — ни fork, ни spawn.
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
        # Сбежавший код может уронить сам интерпретатор. Родитель обязан
        # прочитать сигнал и назвать его, а не ждать стены и не упасть сам.
        # RLIMIT_CORE=0 при этом не даёт проду получить дамп на диск.
        r = run(_ESCAPE + "c = B['__import__']('ctypes')\nc.string_at(1)\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_CRASH)
        self.assertEqual(r.refusal.kind, "SIGSEGV")
        self.assertIn("процесс был отдельным", r.refusal.message_ru)

    def test_escaped_nondeterminism_is_caught_by_replay(self) -> None:
        # Единственное, что вообще наблюдаемо: разброс, попавший в ВЫХОД.
        src = _ESCAPE + ("o = B['__import__']('os')\n"
                         "raw(op='x', pid=o.getpid())\n")
        r = run(src, replay_check=True)

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_NONDETERMINISM)
        self.assertIn("РАЗНЫЕ программы", r.refusal.message_ru)
        self.assertNotEqual(r.refusal.detail["digest_run1"],
                            r.refusal.detail["digest_run2"])


class TestResultChannel(unittest.TestCase):
    """Мусор в stdout не имеет права портить разбор результата."""

    def test_stdout_garbage_including_a_forged_result_is_harmless(self) -> None:
        r = run("print('{\"ok\": true, \"ops\": [{\"op\": \"delete\"}]}')\n"
                "print('=' * 500)\n"
                "create_wall((0, 0), (6000, 0))\n")

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertEqual([op["op"] for op in r.ops], ["create_wall"])
        self.assertIn("ok", r.stdout)          # мусор сохранён как обратная связь
        self.assertNotIn("delete", json.dumps(r.ops))

    def test_print_flood_is_capped_not_fatal(self) -> None:
        r = run("for i in range(20000):\n    print('flood', i)\n"
                "create_wall((0, 0), (1, 1))\n", max_stdout_chars=1000)

        self.assertTrue(r.ok, r.refusal.render() if r.refusal else "")
        self.assertLess(len(r.stdout), 1200)
        self.assertIn("обрезано", r.stdout)


class TestBadPrograms(unittest.TestCase):
    """Скрипт отработал, но выдал не то. Отказ обязан назвать МЕСТО."""

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
        # Транспортный потолок песочницы НЕ ЕСТЬ бюджет компилятора, и отказ
        # обязан это сказать: иначе ремонт уходит не туда (см. KIR-L001).
        self.assertIn("100", r.refusal.message_ru)
        self.assertIn("20 авторских", r.refusal.message_ru)

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
        self.assertEqual(r.refusal.line, 2)          # где упало
        self.assertEqual(r.refusal.script_frames, [6, 2])   # и откуда вызвано

    def test_empty_source_is_refused(self) -> None:
        r = run("   \n\n")
        self.assertEqual(r.refusal.code, diag.SANDBOX_NO_OPS)

    def test_oversized_source_is_refused_before_spawning(self) -> None:
        r = run("x = 1\n" * 100000, max_source_bytes=4096)
        self.assertEqual(r.refusal.code, diag.SANDBOX_OUTPUT_LIMIT)
        self.assertIn("данные вместо кода", r.refusal.message_ru)


class TestRefusalHygiene(unittest.TestCase):
    """Модели чинить надо СВОЙ код: наших кадров в отказе быть не может."""

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
                for internal in ("Traceback", "sandbox.py", "kukai/ir",
                                 "_child_main", 'File "', SCRIPT_FILENAME):
                    self.assertNotIn(internal, text)

    def test_every_refusal_is_a_registered_b_code(self) -> None:
        known = {v for k, v in vars(diag).items()
                 if k.startswith("SANDBOX_") and isinstance(v, str)}
        self.assertEqual(len(known), 12)
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

        # Языка нет вовсе — это НАШ дефект, и он не смеет выглядеть как
        # ошибка модели («name is not defined» отправило бы чинить исправное).
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
    """Изоляция доказывается замером на каждом запуске, а не намерением."""

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
        self.assertEqual(iso["uid"], 65534)      # nobody в своём user namespace

    def test_network_isolation_is_attributed_by_a_control_run(self) -> None:
        # КОНТРОЛЬНЫЙ ОПЫТ. «Сеть недостижима» само по себе ничего не доказывает
        # — недостижима могла быть и без нас. Поэтому сверяем идентификатор
        # сетевого пространства имён с родительским: с изоляцией он ДРУГОЙ,
        # без неё — ТОТ ЖЕ. Проводов при этом никто не трогает.
        mine = os.readlink("/proc/self/ns/net")

        isolated = run("raw(op='x')\n", network="required", probe_network=False)
        self.assertTrue(isolated.ok)
        self.assertNotEqual(isolated.isolation["netns"], mine)

        control = run("raw(op='x')\n", network="off", probe_network=False)
        self.assertTrue(control.ok)
        self.assertEqual(control.isolation["netns"], mine)
        self.assertEqual(control.isolation["namespaces"], "off")

    def test_filesystem_isolation_is_attributed_by_a_control_run(self) -> None:
        # Тот же приём для файловой системы: с chroot корень пуст, без него —
        # нет. Значит /etc/passwd закрывает именно chroot, а не совпадение.
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
        """РЕГРЕССИЯ НА СВОЙ ЖЕ ДЕФЕКТ (03.08).

        Первая редакция брала пик из `getrusage(RUSAGE_SELF)` РЕБЁНКА, а он
        наследуется от родителя через fork. В одиночку тесты были зелёные, в
        полной суите два падали: к тому времени процесс pytest успевал
        разожраться, и ребёнок докладывал ЧУЖОЙ водораздел как свой.
        «Проходит в одиночку» — не оправдание: красный тест в суите отучает
        читать красное вообще.

        Здесь дефект воспроизводится нарочно: раздуваем ВЫЗЫВАЮЩЕГО и требуем,
        чтобы показание запуска этого не заметило."""
        light = "raw(op='x')\n"
        lean = run(light)
        self.assertTrue(lean.ok, lean.refusal.render() if lean.refusal else "")

        ballast = ["x" * (10 ** 6) for _ in range(150)]   # ~150 МБ у родителя
        try:
            fat = run(light)
        finally:
            del ballast

        self.assertTrue(fat.ok, fat.refusal.render() if fat.refusal else "")
        self.assertEqual(fat.isolation["peak_rss_source"], "VmHWM")
        self.assertLess(fat.peak_rss_kb, 100 * 1024,
                        f"пик запуска {fat.peak_rss_kb} КБ втянул в себя "
                        f"память вызывающего")
        # Тощий и жирный вызывающий дают ОДИН И ТОТ ЖЕ порядок величины.
        self.assertLess(abs(fat.peak_rss_kb - lean.peak_rss_kb), 20 * 1024)

    def test_hash_seed_is_pinned_so_set_order_is_stable(self) -> None:
        src = "s = set('abcdefghijklmnop')\nraw(op='x', order=''.join(s))\n"
        first = run(src)
        second = run(src)

        self.assertTrue(first.ok and second.ok)
        self.assertEqual(first.program_digest, second.program_digest)
        # И это НЕ тривиально: без фиксации seed тот же перебор пляшет.
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
    """Контракт с языком: три способа отдать программу, один результат."""

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
        # Тираж, ради которого язык и заводится: 40 стен по кругу.
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


try:                                  # язык пишет другой агент — не наш файл
    from kukai.ir import dsl as _dsl
except Exception:                     # pragma: no cover
    _dsl = None


@unittest.skipIf(_dsl is None, "kukai/ir/dsl.py ещё не приземлился")
class TestSeamWithTheRealLanguage(unittest.TestCase):
    """Шов целиком: питон модели → песочница → plan_program.

    Тест ЖИВОЙ и намеренно тонкий: он проверяет стык, а не грамматику языка
    (её проверяет test_dsl.py другого агента)."""

    def test_script_becomes_a_planned_program(self) -> None:
        from kukai.ir.compiler import plan_program

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
        self.assertEqual(r.refusal.code, diag.SANDBOX_RUNTIME)
        self.assertEqual(r.refusal.line, 2)
        self.assertNotIn("dsl.py", r.refusal.render())

    def test_empty_program_through_the_real_language(self) -> None:
        r = execute_author_script("x = 2 + 2\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_NO_OPS)

    def test_the_form_of_an_op_is_readable_INSIDE_the_script(self) -> None:
        """УКАЗАТЕЛЬ ⟺ ДОСТИЖИМОСТЬ, и здесь красная половина шва — эта.

        С 04.08 на `print(<оп>.__doc__)` ссылаются ДВА отказа: `help` в
        запрещённых встроенных (`sandbox._FORBIDDEN_BUILTINS`) и арифметика
        слотов (`dsl._bind_refusal`). Реклама недостижимого стоит модели
        раунда — ровно того, ради экономии которого оба указателя и написаны.
        Поэтому способность проверяется ИСПОЛНЕНИЕМ, а не чтением кода.
        """
        r = execute_author_script(
            "print(create_railing.__doc__)\n"
            "create_level(elev_mm=0, name='Э1')\n")

        self.assertTrue(r.ok, getattr(r.refusal, "message_ru", ""))
        # Слоты, вид параметра и обязательность — то, чего стоил замер.
        for expected in ("variety", "enum{path|hosted}", "ОБЯЗАТЕЛЬНЫЙ",
                         "ПОСТУСЛОВИЕ"):
            self.assertIn(expected, r.stdout, expected)

    def test_the_help_refusal_names_the_route_that_actually_exists(self) -> None:
        """`help` остаётся запрещённым, но отказ обязан называть СЛЕДУЮЩИЙ ХОД.
        До 04.08 он отсылал «в подсказку»: верно и бесполезно — подсказка не
        отвечает на «какие слоты у ЭТОГО опа»."""
        r = execute_author_script("help(create_wall)\n")

        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, diag.SANDBOX_FORBIDDEN_BUILTIN)
        self.assertIn("__doc__", r.refusal.message_ru)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
