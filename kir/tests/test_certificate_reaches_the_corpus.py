"""AN OBSERVATION MODE WITH NO JOURNAL IS INDISTINGUISHABLE FROM DISABLED.

🔴 WHY (2026-08-24, live measurement + corpus measurement).

`KUKAI_IR_TRANSLATION_CERT=record` was enabled on 08.24. The point of
`record` mode is not to refuse, but to ACCUMULATE A NUMBER: how many live
records the certificate would have refused, had it been switched to
`refuse`. The plan's decision to switch rested on exactly this number.

Measurement: the model's response carries the certificate verbatim —

    {"mode": "record", "revit_version": "2026", "ops": 1,
     "status": "proven", "duration_ms": 10.5, "refused": false}

while the corpus, across 3732 lines, contains **EXACTLY ZERO** records with
a certificate.

The number would NEVER have appeared, and the decision would have been made
by nerve instead of measurement. This is the SECOND instance of the same
shape in one day: a value is computed, reaches the model, and does not
reach the instrument that is supposed to measure us (the first was the
blind-acceptance diagnostic, `KIR-A007`).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from kir import witness_feed


def _записать(path, **over):
    kw = dict(program={"ops": [{"op": "create_wall", "id": "W1"}]},
              family="write", revit_version="2026", ok=True,
              witness={"geometry_ok": True}, duration_ms=12.0)
    kw.update(over)
    with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
        witness_feed.record_witness(**kw)


def _прочитать(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


ЖИВОЙ = {"mode": "record", "revit_version": "2026", "ops": 1,
         "status": "proven", "duration_ms": 10.537, "refused": False}


class СертификатЛожитсяВКорпус(unittest.TestCase):

    def test_живая_квитанция_записывается(self):
        """🔴 RED before the fix: the field did not exist at all."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            _записать(path, certificate=dict(ЖИВОЙ))
            row = _прочитать(path)[0]
            self.assertEqual(row["certificate"]["mode"], "record")
            self.assertEqual(row["certificate"]["status"], "proven")
            self.assertIs(row["certificate"]["refused"], False)
            self.assertEqual(row["certificate"]["ops"], 1)

    def test_отказ_сертификата_счётен(self):
        """This is exactly why the mode was enabled: to count how many it would have said no to."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            _записать(path, certificate={**ЖИВОЙ, "refused": True,
                                         "status": "refused"})
            row = _прочитать(path)[0]
            self.assertIs(row["certificate"]["refused"], True)

    def test_КОНТРОЛЬ_без_сертификата_поля_НЕТ(self):
        """A present-but-empty field would read as 'the certificate was empty'."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            _записать(path)
            self.assertNotIn("certificate", _прочитать(path)[0])


class СписокКлючейЗАКРЫТ(unittest.TestCase):

    def test_чужие_ключи_в_корпус_НЕ_едут(self):
        """🔴 Privacy: the list is closed HERE, not at the caller.

        Otherwise "record this too while we're at it" would slip through
        unnoticed — and the corpus is appended forever and lives in prod.
        """
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            _записать(path, certificate={**ЖИВОЙ,
                                         "op_names": ["create_wall"],
                                         "document": "Проект1",
                                         "diagnostics": ["всё плохо"]})
            cert = _прочитать(path)[0]["certificate"]
            self.assertEqual(set(cert), {"mode", "status", "refused", "ops",
                                         "duration_ms", "revit_version"})

    def test_не_словарь_игнорируется_молча_а_не_роняет_запись(self):
        """The corpus is fail-open: telemetry has no right to crash a turn."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            _записать(path, certificate="строка")
            self.assertNotIn("certificate", _прочитать(path)[0])


class ЖиваяДверьПередаётСертификат(unittest.TestCase):

    def test_обе_площадки_записи_несут_аргумент(self):
        """WIRING. Without it, the field would exist and stay empty —
        exactly the state being fixed here."""
        import inspect
        from kir import serving
        src = inspect.getsource(serving._handle_revit_ir_inner)
        self.assertEqual(src.count("certificate=certificate_receipt"), 2,
                         "обе площадки record_witness обязаны передавать "
                         "сертификат: refused-путь и committed-путь")


if __name__ == "__main__":
    unittest.main()
