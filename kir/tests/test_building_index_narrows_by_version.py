"""The building index is not selected by document NAME alone.

🔴 WHAT BOUGHT THIS FILE, MEASUREMENT 2026-08-25.

`resolve_run` can narrow the choice three ways: by `project_uid`
(identity rank), by `revit_version`, and by title. The service called it
WITH TITLE ALONE:

    run, why, freshness = resolve_run(title)

The consequence reads straight out of `_identity_rank`: without `project_uid`
the rank is ZERO for every candidate, the version is never asked, and the
only remaining discriminator is the catalog's last-write time. Decompiles
with the same name, recorded in the same second, are picked essentially at
random.

THE COST. A script that branches on index data gets the index of SOMEONE
ELSE'S building, and the refusal arrives as "level not found" — the wrong
reason. The door's own docstring promises an outcome of "a decompile exists,
but for another document — discarded inside `resolve_run`," yet identity
rejection is unreachable at this call site, by construction.

WHAT IS FIXED HERE, AND WHAT IS NOT. The version is available: it lives in
the same `_session_contexts[ws_id]` that `document_name` is taken from, and
a neighboring function in the same file reads it exactly that way
(`chat_ws.py`). `project_uid` is not available for free — it needs a
fingerprint from `ground` — and that is named as a boundary, not left unsaid.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import unittest

from kir import serving


def _именованные(функция, имя_вызова: str) -> set[str] | None:
    """The call's keyword arguments — found by PARSING, not by substring.

    The regex `\\(([^)]*)\\)` stops at the first inner parenthesis;
    this lesson was bought that same day on `_upgrade_moves`.
    """
    дерево = ast.parse(textwrap.dedent(inspect.getsource(функция)))
    for узел in ast.walk(дерево):
        if not isinstance(узел, ast.Call):
            continue
        цель = узел.func
        имя = (цель.attr if isinstance(цель, ast.Attribute)
               else getattr(цель, "id", None))
        if имя == имя_вызова:
            return {kw.arg for kw in узел.keywords if kw.arg}
    return None


class ВыборРазбораСужаетсяВерсией(unittest.TestCase):

    def test_resolve_run_зовётся_с_версией(self):
        имена = _именованные(serving._building_index_for_turn, "resolve_run")
        self.assertIsNotNone(имена, "вызов resolve_run исчез — стенд не туда")
        self.assertIn(
            "revit_version", имена,
            f"выбор идёт по одному имени: {sorted(имена)}. Без версии ранг "
            f"личности равен нулю у всех, и решает время файла.")

    def test_контекст_хода_отдаёт_версию(self):
        источник = inspect.getsource(serving)
        self.assertIn(
            "revit_version", источник.split("def _turn_document_title")[0]
            + источник.split("def _turn_document_title")[-1][:4000],
            "версия не читается из контекста хода вовсе")

    def test_КОНТРОЛЬ_resolve_run_умеет_принять_версию(self):
        """The instrument is obligated to exist before it is targeted."""
        from kir.clash.existing import resolve_run
        параметры = inspect.signature(resolve_run).parameters
        self.assertIn("revit_version", параметры)
        self.assertEqual(параметры["revit_version"].default, "")

    def test_КОНТРОЛЬ_project_uid_остаётся_НЕДОСТУПЕН_и_назван(self):
        """The boundary is obligated to be named, not silenced: `project_uid`
        requires a fingerprint from `ground`, which does not exist at this seam."""
        док = inspect.getsource(serving._building_index_for_turn)
        self.assertIn("project_uid", док,
                      "недоступность project_uid нигде не названа — читатель "
                      "решит, что личность проверяется")


if __name__ == "__main__":
    unittest.main()
