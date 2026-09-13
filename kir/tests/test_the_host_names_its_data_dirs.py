"""THE OWNER NAMES THE DATA DIRECTORIES — BECAUSE THERE IS NO WAY TO DERIVE
THEM.

WHAT HAPPENED, BY A MEASUREMENT ON 28.08.2026. After the split,
`install_paths` climbs up from the package's location to the
`backend/kukai` marker; above `/opt/kir` no such directory exists, and
`install_root()` answers `None` ALWAYS. In the live service (pid 2951264,
brought up 27.08 12:17) this produced:

    run_root()   -> <install unnamed>/backend/data/decompile   exists False
    list_runs()  -> 0            on disk 81 decompiles with the L0 stream
    8 of 14 viewer routes        dead, and SILENTLY

🔴 AND WHY THE CURE IS A PORT, NOT A ROOT VARIABLE. A run from the same
day, both sides:

    KIR_INSTALL_ROOT=<backend>      decompile PRESENT · telemetry ABSENT
    KIR_INSTALL_ROOT=<repository>   decompile ABSENT   · telemetry PRESENT

The kinds sit under DIFFERENT roots, because the owner's decompile output
root (`serving._DECOMPILE_OUT_ROOT`) is a RELATIVE path resolved against
the service's working directory. No single root exists for anyone; so it
cannot be derived either by arithmetic or by a variable, and one must ask
whoever laid out the installation for the DIRECTORY OF THE KIND. This is
exactly what `ports.INSTALL_DATA` does.

WHAT IS GUARDED MOST STRICTLY HERE IS A NO-OP. The tree is installed into
the live service's venv as EDITABLE (`KIR_PLAN.md` §0.1): between saving a
file and `kukai-backend.service`, there is neither a build nor a release.
So a fix that adds a capability must be BYTE-FOR-BYTE UNDETECTABLE for as
long as nobody has installed the capability — and this is a condition of
the fix, not caution.

A DEGENERACY CONTROL EXISTS AND HAS BEEN RUN: `test_the_control_is_not_vacuous`
shows that the provider REALLY DOES change the answer. Without it the
suite would be green by construction — "None without the port, None with
the port" would read as "it works."

Run: PYTHONPATH=/opt/kir python3.12 -m pytest -q \
            kir/tests/test_the_host_names_its_data_dirs.py
"""
from __future__ import annotations

import importlib
import os
import pathlib
import unittest

from kir import install_paths as ip
from kir import ports

#: Two kinds under DIFFERENT roots — what no single common root can cover.
#: The directories are deliberately fictitious: the test has no right to
#: depend on the machine it runs on, still less to write into someone
#: else's installation.
СКЛАД = "/tmp/kir-probe-install/backend/backend/data/decompile"
ФИДЫ = "/tmp/kir-probe-install/backend/data/telemetry"


class _Хозяин:
    """A port provider. `answer` is what it returns, `raises` is what it
    throws."""

    def __init__(self, answer=None, raises: Exception | None = None):
        self.answer, self.raises = answer or {}, raises
        self.asked: list[str] = []

    def data_path(self, kind: str):
        self.asked.append(kind)
        if self.raises is not None:
            raise self.raises
        return self.answer.get(kind)


class _БезПорта(unittest.TestCase):
    """A shared cleanup: no test has the right to leave the port closed."""

    def setUp(self) -> None:
        self._env = os.environ.get(ip._INSTALL_ROOT_ENV)
        os.environ.pop(ip._INSTALL_ROOT_ENV, None)
        # `addCleanup`, not `tearDown`: when `setUp` is skipped, unittest
        # does not call `tearDown` at all, and the gate would have blamed
        # the NEXT test.
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        ports.unregister(ports.INSTALL_DATA)
        if self._env is None:
            os.environ.pop(ip._INSTALL_ROOT_ENV, None)
        else:
            os.environ[ip._INSTALL_ROOT_ENV] = self._env

    def _supply(self, host: _Хозяин) -> _Хозяин:
        ports.register(ports.INSTALL_DATA, lambda: host)
        return host


class ПортОбъявлен(_БезПорта):
    """`ALL_PORTS` is a CLOSED list: `register` throws on an unrecognized
    name."""

    def test_the_port_is_declared(self) -> None:
        self.assertIn(ports.INSTALL_DATA, ports.ALL_PORTS)

    def test_the_registry_accepts_it(self) -> None:
        host = self._supply(_Хозяин({"decompile": СКЛАД}))
        self.assertIn(ports.INSTALL_DATA, ports.supplied())
        self.assertIs(ports.need(ports.INSTALL_DATA), host)


class ХолостойХод(_БезПорта):
    """As long as the port is not closed, the module answers exactly what
    it used to answer."""

    def test_without_a_supplier_the_answer_is_unchanged(self) -> None:
        self.assertNotIn(ports.INSTALL_DATA, ports.supplied())
        # In this tree there is no marker above the package, so the answer
        # is an honest None. The assertion is written via `_derived_root`,
        # not a constant: on a tree where the marker IS present, the test
        # must remain correct.
        derived = ip._derived_root()
        ожидалось = (None if derived is None
                     else derived.joinpath("backend", "data", "telemetry", "x"))
        self.assertEqual(ip.install_data_path("telemetry", "x"), ожидалось)

    def test_the_refusal_names_the_variable_in_both_branches(self) -> None:
        """A reader must not have to guess which move is left to them."""
        if ip.install_root() is not None:
            self.skipTest("на этом дереве корень выводится — ветка не о нём")
        self.assertIn(ip._INSTALL_ROOT_ENV, ip.install_root_refusal() or "")
        self._supply(_Хозяин({"decompile": СКЛАД}))
        при_порте = ip.install_root_refusal() or ""
        self.assertIn(ip._INSTALL_ROOT_ENV, при_порте)
        self.assertIn("data.install_paths", при_порте)


class ПорядокАвторитетов(_БезПорта):
    """The operator → the owner → derivation by marker → None."""

    def test_the_operator_wins_over_the_host(self) -> None:
        host = self._supply(_Хозяин({"decompile": СКЛАД}))
        os.environ[ip._INSTALL_ROOT_ENV] = "/tmp/kir-operator-said-so"
        self.assertEqual(
            ip.install_data_path("decompile"),
            pathlib.Path("/tmp/kir-operator-said-so/backend/data/decompile"))
        self.assertEqual(host.asked, [],
                         "порт спрошен вопреки слову оператора")

    def test_the_host_wins_over_the_derived_marker(self) -> None:
        self._supply(_Хозяин({"decompile": СКЛАД}))
        self.assertEqual(ip.install_data_path("decompile"), pathlib.Path(СКЛАД))


class РодСпрашиваетсяПоОтдельности(_БезПорта):
    """THE MAIN PROPERTY: two kinds under different roots — and both are
    correct."""

    def test_two_kinds_live_under_different_roots(self) -> None:
        self._supply(_Хозяин({"decompile": СКЛАД, "telemetry": ФИДЫ}))
        self.assertEqual(ip.install_data_path("decompile"), pathlib.Path(СКЛАД))
        self.assertEqual(ip.install_data_path("telemetry", "kir_witness.jsonl"),
                         pathlib.Path(ФИДЫ) / "kir_witness.jsonl")
    def test_no_single_root_yields_both_kinds(self) -> None:
        """THE ARGUMENT FOR THE PORT, RECORDED AS A NUMBER, NOT AS PROSE.

        🔴 THE FIRST REVISION OF THIS ASSERTION WAS WRONG, AND THE GATE
        CAUGHT IT ON THE VERY FIRST RUN. It checked that the common
        ancestor of the two directories does NOT produce the store by the
        old formula — but it does produce it: the common ancestor here is
        `<...>/backend`, and `<...>/backend/backend/data/decompile` is
        exactly the store. The OTHER half needed checking: the root from
        which the old formula derives the STORE, and the root from which it
        derives the FEEDS, are DIFFERENT directories. Hence the
        impossibility of a single variable.
        """
        корень_склада = pathlib.Path(СКЛАД).parents[2]     # <root>/backend/data/X
        корень_фидов = pathlib.Path(ФИДЫ).parents[2]
        self.assertNotEqual(
            корень_склада, корень_фидов,
            "роды выводятся из ОДНОГО корня — тогда порт был бы не нужен")
        # And the flip side: each of these roots gives ITS OWN kind
        # correctly and the OTHER one — incorrectly. This is exactly what
        # was measured on the live machine.
        self.assertEqual(
            корень_склада.joinpath("backend", "data", "decompile"),
            pathlib.Path(СКЛАД))
        self.assertNotEqual(
            корень_склада.joinpath("backend", "data", "telemetry"),
            pathlib.Path(ФИДЫ))


class ТишинаОстаётсяТишиной(_БезПорта):
    """An owner who did not name the kind does not turn into a plausible
    path."""

    def test_an_unnamed_kind_is_none(self) -> None:
        self._supply(_Хозяин({"decompile": СКЛАД}))
        self.assertIsNone(ip.install_data_path("evidence"))

    def test_a_refusing_host_does_not_crash_the_caller(self) -> None:
        """Feeds fail-open by contract: a refusal from the owner must turn
        into silence, not an exception in the middle of someone else's
        turn."""
        self._supply(_Хозяин(raises=RuntimeError("хозяин не в духе")))
        self.assertIsNone(ip.install_data_path("telemetry", "x.jsonl"))

    def test_an_empty_answer_is_not_a_path(self) -> None:
        """An empty string is not a directory. `Path("")` would give `.`,
        that is, a WRITE INTO THE WORKING DIRECTORY OF WHOEVER RAN IT — the
        worst of the available wrongs."""
        self._supply(_Хозяин({"telemetry": ""}))
        self.assertIsNone(ip.install_data_path("telemetry", "x.jsonl"))


class КонтрольНеВырожден(_БезПорта):
    """Without this class, the suite would be green by construction."""

    def test_the_control_is_not_vacuous(self) -> None:
        без_порта = ip.install_data_path("decompile")
        self._supply(_Хозяин({"decompile": СКЛАД}))
        с_портом = ip.install_data_path("decompile")
        self.assertNotEqual(
            без_порта, с_портом,
            "поставщик не изменил ответа — тест ничего не проверяет")
        self.assertEqual(с_портом, pathlib.Path(СКЛАД))


class ПерезагрузкаМодуляНеЛомаетПорт(_БезПорта):
    """Neighboring suites do `importlib.reload(install_paths)` — the port
    registry lives in a different module and must survive this."""

    def test_reload_keeps_the_host_answer(self) -> None:
        self._supply(_Хозяин({"decompile": СКЛАД}))
        importlib.reload(ip)
        self.assertEqual(ip.install_data_path("decompile"), pathlib.Path(СКЛАД))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
