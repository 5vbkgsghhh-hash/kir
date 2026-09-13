"""The package does not know a stranger's directory or a stranger's device by heart.

WHY THIS GUARD EXISTS. `kir` is published as a separate repository under
Apache-2.0. An absolute path into the owner's tree, or a raw identifier of
someone else's machine, in such a file is not a TODO, it is a leak (the
canon has said this in so many words since 09.08.2026), and on top of that
it is a ROUTE that exists on no machine but one: for an outside person the
code simply will not run.

🔴 THE DISTINCTION WITHOUT WHICH THE GUARD WOULD DESTROY EVIDENCE. A path in
text comes in two kinds, and they are treated oppositely:

    ROUTE          the code WALKS it (opens, launches, imports)
                   -> must ask the environment
    NARRATIVE      the path is NAMED in a comment as a fact or a
                   measurement witness -> must stay verbatim; it is a
                   record of where something was

Measured 27.08.2026 on `bafb3f6`: of 11 files with `/opt/kukai-rebuild1`
outside tests, FOUR were ROUTES, the other seven were narrative. The guard
below checks only routes and is deliberately blind to prose.

🔴 AND WHY SEARCH BY PROPERTY, NOT BY LITERAL. A guard that searches for a
known id finds exactly yesterday's leak: a second identifier, set up
tomorrow, does not exist for it. This is form 54 (a guard that pins the
shape of the first case), and it was paid for in this very tree today — a
probe brought in this morning searched for a literal, excluded itself from
the count, and printed 2 where there were 3 carriers. We ask for a
PROPERTY: 32 hexadecimal characters outside a digest's context.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import subprocess
import unittest

_PKG = pathlib.Path(__file__).resolve().parents[1]

#: Files where the 27.08 measurement found a ROUTE. The list is CLOSED AND
#: NOT COMPLETE: an empty cell means "no route was found here", not "there is none".
_ROUTE_FILES = (
    "checker/extractor.py",
    "clash/tools/wall_prism_gate.py",
    "clash/tools/bundle_containment_gate.py",
)

_HOST_ROOT = "/opt/kukai-rebuild1"

#: 32 hex characters in a row. Digests look the same, so a line where a
#: word about hashing stands next to it is not counted as a candidate —
#: otherwise the guard would go red on its own sha256 values and would get
#: disabled.
_HEX32 = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{32}(?![0-9a-fA-F])")
_DIGEST_CONTEXT = re.compile(r"sha256|sha1|md5|digest|дайджест|хеш|hash", re.I)


def _source(rel: str) -> str:
    return (_PKG / rel).read_text(encoding="utf-8")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Identities of the string nodes that ARE DOCSTRINGS."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.add(id(body[0].value))
    return out


def executable_strings(source: str) -> list[tuple[int, str]]:
    """String VALUES that the code actually takes into its own hands.

    🔴 WHY PARSING, NOT A `#` PREFIX. The first edition of this guard
    counted as a route anything not starting with a hash — and it went red
    on ITS OWN docstring, the one explaining what the previous edition of
    `_git` did. That is, a guard written against "a path in code" could not
    tell CODE apart from a STORY ABOUT CODE, and demanded that the evidence
    be erased.

    This is form 25 (a guard that names the shape measures the shape) on
    the guard itself, on its very first run. We ask for a PROPERTY: a
    string constant that is not a docstring is a value the code makes use
    of; a docstring and a comment are narrative.
    """
    tree = ast.parse(source)
    docs = _docstring_nodes(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs):
            out.append((getattr(node, "lineno", 0), node.value))
    return out


def _device_candidates(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        if _DIGEST_CONTEXT.search(line):
            continue
        out.extend(_HEX32.findall(line))
    return out


class МаршрутыНеЗнаютХозяина(unittest.TestCase):
    """Not a single package ROUTE addresses the owner's tree by a literal."""

    def test_no_route_file_carries_the_host_root(self) -> None:
        guilty = {rel: [f"{line}: {value[:80]}"
                        for line, value in executable_strings(_source(rel))
                        if _HOST_ROOT in value]
                  for rel in _ROUTE_FILES}
        guilty = {k: v for k, v in guilty.items() if v}
        self.assertEqual(
            guilty, {},
            "маршрут адресует дерево хозяина литералом — у чужого человека "
            f"этого пути нет:\n{guilty}")

    def test_no_route_file_carries_a_device_identifier(self) -> None:
        guilty = {rel: _device_candidates(_source(rel))
                  for rel in _ROUTE_FILES}
        guilty = {k: v for k, v in guilty.items() if v}
        self.assertEqual(
            guilty, {},
            "в маршруте лежит 32-hex вне контекста дайджеста — это похоже на "
            f"сырой идентификатор машины в публикуемом пакете:\n{guilty}")


class КаналОператораСпрашиваетОкружение(unittest.TestCase):
    """No variable — a LOUD named refusal, not a quiet stranger's path."""

    def setUp(self) -> None:
        from kir.checker import extractor
        self.ex = extractor
        self._saved = {k: os.environ.get(k) for k in
                       ("KIR_OP_PYTHON", "KIR_OP_SCRIPT", "KUKAI_ADMIN_DEVICES")}

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_without_the_variable_the_refusal_names_it(self) -> None:
        os.environ.pop("KIR_OP_PYTHON", None)
        os.environ.pop("KIR_OP_SCRIPT", None)
        os.environ["KUKAI_ADMIN_DEVICES"] = "dev-1"
        with self.assertRaises(self.ex.OperatorChannelMissing) as got:
            self.ex.run_extractor_cs("dev-1")
        self.assertIn("KIR_OP_PYTHON", str(got.exception))

    def test_the_refusal_is_a_runtime_error_so_old_handlers_still_catch(self) -> None:
        # A subclass on purpose: call sites already catch RuntimeError and
        # treat the failure as "could not be read". A split that changes
        # the behavior of existing branches is no longer a split.
        self.assertTrue(issubclass(self.ex.OperatorChannelMissing, RuntimeError))

    def test_the_channel_is_read_from_the_environment(self) -> None:
        os.environ["KIR_OP_PYTHON"] = "/tmp/py"
        os.environ["KIR_OP_SCRIPT"] = "/tmp/op.py"
        self.assertEqual(self.ex.operator_channel(), ("/tmp/py", "/tmp/op.py"))


class ДопускЕстьУСТАНОВКИ_АНеУФАЙЛА(unittest.TestCase):
    """The list of permitted devices is ONE per package, and it belongs to the configuration."""

    def setUp(self) -> None:
        # RETURN ALL THREE, not just the test's subject: the environment
        # guard (`kir/tests/conftest.py`) caught the first edition of this
        # class on two leftover keys — and it was right. A test that
        # leaves process state behind brings down its NEIGHBOR, and the
        # failure looks like the neighbor's fault.
        self._saved = {k: os.environ.get(k) for k in
                       ("KUKAI_ADMIN_DEVICES", "KIR_OP_PYTHON", "KIR_OP_SCRIPT")}
        from kir.checker import extractor
        self.ex = extractor

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_an_empty_list_is_CLOSED_not_open(self) -> None:
        # An access list that has become empty and therefore permits everything is worse than a leak.
        os.environ["KUKAI_ADMIN_DEVICES"] = ""
        os.environ["KIR_OP_PYTHON"] = "/tmp/py"
        os.environ["KIR_OP_SCRIPT"] = "/tmp/op.py"
        with self.assertRaises(PermissionError):
            self.ex.run_extractor_cs("dev-1")

    def test_the_unset_variable_is_CLOSED_too(self) -> None:
        os.environ.pop("KUKAI_ADMIN_DEVICES", None)
        os.environ["KIR_OP_PYTHON"] = "/tmp/py"
        os.environ["KIR_OP_SCRIPT"] = "/tmp/op.py"
        with self.assertRaises(PermissionError):
            self.ex.run_extractor_cs("whoever")

    def test_the_authority_is_the_one_serving_already_uses(self) -> None:
        """A second carrier of one rule is a named defect of this tree.

        `serving.admin_devices()` reads `KUKAI_ADMIN_DEVICES` and has had
        no fallback since 15.08.2026. The checker must ask IT, not set up
        its own set: otherwise the two lists would diverge on the very
        first device, and diverge silently.
        """
        self.assertNotIn("AUTHORIZED", _source("checker/extractor.py"))


class КореньУстановкиСчитаетсяОТПАКЕТА(unittest.TestCase):
    """`install_paths`, after the split, answered `None` ALWAYS — and silently."""

    def setUp(self) -> None:
        self._saved = os.environ.get("KIR_INSTALL_ROOT")

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop("KIR_INSTALL_ROOT", None)
        else:
            os.environ["KIR_INSTALL_ROOT"] = self._saved

    def test_the_environment_can_name_the_root(self) -> None:
        """Measured 27.08: `parents[3]` from `/opt/kir/kir/install_paths.py`
        gives `/`, the marker `backend/kukai` does not exist there, and
        EIGHT consumers silently fell into their own `None` policy: six
        telemetry feeds went silent (they are fail-open by contract),
        acceptance refused. Exactly the form on which the sandbox burned
        after the split (`f518b05`): the root was counted in STEPS UPWARD.
        """
        from kir import install_paths as ip
        import importlib
        with self.subTest("окружение называет корень"):
            os.environ["KIR_INSTALL_ROOT"] = "/tmp/kir-data-root-probe"
            importlib.reload(ip)
            self.assertEqual(ip.install_root(),
                             pathlib.Path("/tmp/kir-data-root-probe"))
            # The shape of the answer DOES NOT CHANGE: eight consumers rest
            # their policies on it, and `<root>/backend/data/...` remains
            # exactly what it was.
            self.assertEqual(
                ip.install_data_path("telemetry", "x.jsonl"),
                pathlib.Path(
                    "/tmp/kir-data-root-probe/backend/data/telemetry/x.jsonl"))
        with self.subTest("без окружения ответ ЧЕСТНЫЙ None, а не чужой путь"):
            os.environ.pop("KIR_INSTALL_ROOT", None)
            importlib.reload(ip)
            root = ip.install_root()
            self.assertTrue(root is None or root.is_dir(),
                            f"корень выдуман: {root}")

    def test_the_silence_can_be_asked_why(self) -> None:
        """Silence whose cause cannot be asked is indistinguishable from a
        disabled mode (form 50). The consumers' policy is NOT changed —
        the ability to ASK is added."""
        from kir import install_paths as ip
        import importlib
        os.environ.pop("KIR_INSTALL_ROOT", None)
        importlib.reload(ip)
        if ip.install_root() is None:
            self.assertIn("KIR_INSTALL_ROOT", ip.install_root_refusal() or "")


#: The floor for the number of files the walk MUST traverse. Measured
#: 02.09.2026: after skipping tests and `instruments/`, **278** files
#: remain. The floor is taken with margin: the subject is not the tree's
#: growth, but the LOSS OF THE SUBJECT. A module-level floor, rather than
#: a class-level one, is of the same form as `ФАЙЛОВ_НЕ_МЕНЬШЕ` at the
#: boundary guard.
ФАЙЛОВ_НЕ_МЕНЬШЕ = 200


class ВесьПакетПодГрепом(unittest.TestCase):
    """Control in the other direction: no routes remain anywhere, not only
    in the closed list above."""

    def test_no_executable_line_in_the_package_names_the_host_root(self) -> None:
        """🔴 THE DENOMINATOR IS DECLARED (02.09.2026), AND HERE IS EXACTLY WHY HERE.

        The claim is one-sided: `live == []`. A walk that lost its subject
        returns an empty list and reads as "no routes remain anywhere" —
        that is, as PROVEN SEPARABILITY. This is the most expensive kind
        of silence in the tree: it is what closes the measure «KIR стоит
        без КУКАЯ».

        The form was paid for twice on the same day: the satellite walk
        found 0 places instead of six and WENT RED, because it had a
        denominator; the emitter guard saw 35 names out of 72 and stayed
        green, because it checked only non-emptiness.
        """
        live: list[str] = []
        файлов = 0
        for path in sorted(_PKG.rglob("*.py")):
            rel = str(path.relative_to(_PKG))
            if "/tests/" in f"/{rel}" or rel.startswith("instruments/"):
                continue          # tests are their own subject; instruments is someone else's wave
            try:
                strings = executable_strings(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                # A file the instrument DID NOT PARSE is a named refusal,
                # not a footnote: a report taken while the unparsed list is
                # non-empty disqualifies itself (form 26).
                self.fail(f"не разобран {rel}: {exc}")
            файлов += 1
            live.extend(f"{rel}:{line}: {value[:70]}"
                        for line, value in strings if _HOST_ROOT in value)
        self.assertGreaterEqual(
            файлов, ФАЙЛОВ_НЕ_МЕНЬШЕ,
            f"обход прошёл {файлов} файлов при поле {ФАЙЛОВ_НЕ_МЕНЬШЕ} "
            "(замер 02.09.2026 — 278). Пустой список ниже был бы заявлением о "
            "ХОДОКЕ, а не об отделимости пакета")
        self.assertEqual(
            live, [],
            "исполняемая строка адресует дерево хозяина:\n" + "\n".join(live))


if __name__ == "__main__":
    unittest.main()
