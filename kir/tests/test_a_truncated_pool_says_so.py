"""A TRUNCATED POOL IS OBLIGATED TO SAY SO, NOT REPORT ITSELF AS COMPLETE (F-080).

🔴 WHAT IT USED TO BE. The collector takes `.ToWorksets().Take(1000)`, while
the total was reported as `__worksets.Count` — that is, the COUNT OF WHAT WAS
CAPTURED. After the slice it equals 1000 for any document with more worksets
than that, and the pool contract reads this as `total_count == len(entries)`,
i.e. "EVERYTHING was captured": `complete=true`, `truncated=false`. There
was no truncation flag at all.

GROUNDING AGAINST THE CORPUS IS A MEASUREMENT, NOT A HYPOTHESIS (2026-08-30,
corpus read-only): of 10 decompiles carrying a `worksets` pool, **SEVEN sit
at exactly 1000**:

    k2v33_join2 · k3_layers · mnvnk_k1_layers · mnvnk_k3_22aug ·
    mnvnk_k3_23aug · mnvnk_atr_pd_b14_k3 · mnvnk_atr_pd_b14_k6

Seven different documents on ONE round boundary is the signature of a cap,
not a coincidence. How many worksets there actually are, nobody knows: the
old code never counted that number, and it cannot be recovered after the fact.

🔴 A COST THE FIX DOES NOT HAVE. The package proposed a SECOND pass over the
collector and honestly named it as an unmeasured expense. It is not needed:
`FilteredWorksetCollector.ToWorksets()` returns an ALREADY MATERIALIZED
`IList<Workset>`, so `.Count` costs O(1), and the collector is walked exactly
once — the same as before the fix. The guard pins exactly that: there must
not be a second `new FilteredWorksetCollector` in the body.
"""
from __future__ import annotations

import pathlib
import re
import unittest

# 🔴 NAMES ARE TAKEN FROM THE MODULE AT CALL TIME, NOT AT IMPORT (2026-08-30).
# The neighbor `test_open_model.py:890` does `importlib.reload(open_model)`
# in `finally`, and this RECREATES the classes: a module that took
# `ModelCatalogPool` by name at import time holds a STALE class object after
# the neighbor's run, and `isinstance` in its own validator stops matching —
# `catalog_pool.entries must be a typed tuple` on a completely legal input.
# Caught by a run: the file is green ALONE (7 passed) and red IN A GROUP (4
# failed). This is a fact about the NEIGHBOR, not about the fix; it is cured
# by asking the module for the name every time.
import kir.open_model as _om

_ИСТОЧНИК = pathlib.Path(__file__).resolve().parents[1] / "open_model.py"


def _код_без_комментариев() -> str:
    """Comments are stripped: the law lives in the CODE.

    This technique was bought on S-01, where the guard went red on its OWN
    comment, which quoted the old form. Here too, a comment quotes
    `__worksets.Count`, explaining what no longer exists.
    """
    текст = _ИСТОЧНИК.read_text(encoding="utf-8")
    текст = re.sub(r"/\*.*?\*/", "", текст, flags=re.S)
    return re.sub(r"(?m)//.*$", "", текст)


def _пул(захвачено: int, всего, усечён: bool) -> _om.ModelCatalogPool:
    entries = tuple(
        _om.ModelCatalogEntry(element_id=i + 1, name=f"n{i}")
        for i in range(захвачено))
    return _om.ModelCatalogPool(name="worksets", entries=entries,
                                total_count=всего, truncated=усечён)


class УсечённыйПулГоворитОСебе(unittest.TestCase):

    def test_полное_число_считается_ДО_среза(self):
        код = _код_без_комментариев()
        self.assertIn("__worksetsTotal = __worksetsAll.Count", код,
                      "полное число снова берётся ПОСЛЕ среза — тогда оно "
                      "равно числу захваченного и лжёт на любом документе "
                      "свыше потолка")
        self.assertNotIn('__snap["worksets__total"] = __worksets.Count', код,
                         "число захваченного снова выдаётся за полное")

    def test_признак_усечения_эмитируется(self):
        код = _код_без_комментариев()
        self.assertIn('__snap["worksets__truncated"]', код,
                      "пул не может объявить себя усечённым: контракт "
                      "требует признак ЯВНО, а не выводит его сравнением")

    def test_второго_обхода_коллектора_нет(self):
        """THE SECOND HALF: the fix must not cost an extra pass."""
        код = _код_без_комментариев()
        self.assertEqual(код.count("new FilteredWorksetCollector(doc)"), 1,
                         "заведён второй обход коллектора — `ToWorksets()` "
                         "уже материализован, `.Count` стоит O(1)")

    def test_контракт_отвергает_ложь_о_полноте(self):
        """A pool where the total is GREATER than what was captured is obligated to call itself truncated."""
        with self.assertRaises(_om.OpenModelProfileError):
            _пул(захвачено=3, всего=5, усечён=False)

    def test_контракт_отвергает_ложное_усечение(self):
        """And conversely: a complete pool has no right to declare itself truncated.
        Without this half, "always truncated=true" would pass the previous case."""
        with self.assertRaises(_om.OpenModelProfileError):
            _пул(захвачено=3, всего=3, усечён=True)

    def test_честные_случаи_проходят(self):
        """Both legitimate outcomes: a complete pool and a named truncation."""
        self.assertTrue(_пул(3, 3, False).complete)
        срез = _пул(3, 9, True)
        self.assertFalse(срез.complete)
        self.assertEqual(срез.total_count, 9)

    def test_неизвестное_полное_число_остаётся_третьим_исходом(self):
        """`total_count=None` means "not measured," and that is NEITHER a lie NOR
        completeness. Old corpus snapshots carry exactly this, and they must
        not be rejected."""
        пул = _пул(3, None, False)
        self.assertIsNone(пул.total_count)
        self.assertFalse(пул.complete)


if __name__ == "__main__":
    unittest.main()
