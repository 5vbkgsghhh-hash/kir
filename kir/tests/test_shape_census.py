"""THE SHAPE CENSUS MUST BE AN INSTRUMENT, NOT A LIST — AND THIS IS VERIFIED BY EXECUTION.

An instrument that prints "one ring" because the author wrote the op's name into it is no
better than a hand-written table: it will not find the NEXT case. Hence, here:

1. COMPLETENESS BY CONSTRUCTION. Membership is taken from `spec.PARAM_KINDS`; a new kind in
   the registry that is not distributed across carriers must MAKE THE CENSUS FAIL, rather than start
   a silent line.
2. DERIVED, NOT DECLARED. The ring capacity must CHANGE in step with the registry:
   remove the hole operand from the op — the capacity must drop to one ring on its own.
3. 🔴 A BAN ON NAMES. The instrument's source is read and must not contain a single
   operation name. There is also a control on the ban itself: a forged source with
   a name must be caught, otherwise the ban is green by construction.
4. A FAIL CONTROL for every guard, and DULLNESS OF THE PROBE: an unrelated edit must NOT
   turn it red, otherwise a broad red means nothing.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import unittest


def _strip_prose(source: str) -> str:
    """Source WITHOUT docstrings: a name in explanatory prose does not decide, a name in code does.

    Without this, the guard would be catching its own explanation of why the instrument was written, and
    a red result would name the wrong trouble (a broad red is a sign of a dull probe).
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            body.pop(0)
            if not body:
                body.append(ast.Pass())
    return ast.unparse(ast.fix_missing_locations(tree))


class ShapeCensusIsAnInstrument(unittest.TestCase):

    def test_membership_comes_from_the_registry(self):
        from kir.course import shape
        self.assertEqual([], shape.unclassified_kinds(),
                         "род параметра реестра не разнесён по носителям формы")
        self.assertEqual([], shape.stray_kinds(),
                         "носитель ссылается на род, которого реестр не знает")

    def test_control_fail_new_registry_kind_breaks_the_census(self):
        """FAIL CONTROL: a new kind must make it fail, not pass silently."""
        from kir import spec
        from kir.course import shape
        original = spec.PARAM_KINDS
        try:
            spec.PARAM_KINDS = type(original)(list(original) + ["nurbs_cage"])
            self.assertEqual(["nurbs_cage"], shape.unclassified_kinds())
            with self.assertRaises(ValueError) as caught:
                shape.operands()
            self.assertIn("nurbs_cage", str(caught.exception))
        finally:
            spec.PARAM_KINDS = original
        self.assertEqual([], shape.unclassified_kinds(), "правка не откатилась")

    def test_the_probe_is_not_blunt(self):
        """DULLNESS: a kind that is already distributed must NOT turn it red."""
        from kir import spec
        from kir.course import shape
        original = spec.PARAM_KINDS
        try:
            spec.PARAM_KINDS = type(original)(
                [k for k in original if k != "mesh"] + ["mesh"])
            self.assertEqual([], shape.unclassified_kinds())
            shape.operands()
        finally:
            spec.PARAM_KINDS = original

    def test_capacity_is_derived_and_follows_the_registry(self):
        """Remove the hole operand from the op — the capacity must drop ON ITS OWN."""
        from kir import spec
        from kir.course import shape
        victim = next(name for name, cap in shape.ring_capacity().items()
                      if cap == shape.RING_AND_HOLES
                      and any(carrier == "кольца"
                              for _, _, carrier, _ in shape.operands()[name]))
        op = spec.OPS[victim]
        thinner = tuple(p for p in op.params
                        if p.kind not in ("pts_list", "region"))
        try:
            spec.OPS[victim] = dataclasses.replace(op, params=thinner)
            self.assertEqual(shape.ONE_RING, shape.ring_capacity()[victim],
                             "ёмкость не выведена из реестра, а объявлена")
        finally:
            spec.OPS[victim] = op
        self.assertEqual(shape.RING_AND_HOLES, shape.ring_capacity()[victim],
                         "правка не откатилась")

    def test_the_instrument_carries_no_op_name(self):
        """🔴 The main guard: the instrument does not know names and will therefore find the next case."""
        from kir import spec
        from kir.course import shape
        source = _strip_prose(inspect.getsource(shape))
        # 🔴 TWO DENOMINATORS, MEASURED 02.09.2026: the instrument's source WITHOUT PROSE
        # is **5976** characters (with prose — 14,335, and the first draft of this floor
        # used exactly that one: a floor of 8000 went red on the live tree because
        # it measured the wrong subject — the guard judges `_strip_prose`, not getsource);
        # the `spec.OPS` registry is **82** ops. The intersection of the two sets has TWO
        # ways to go empty, and both read as "no names": the instrument having drifted into
        # satellites, and the registry not having come up. The FAIL control below covers
        # only the second one (it presents `create_roof` to the registry) and says nothing
        # about the first.
        ЗНАКОВ_ПРИБОРА_НЕ_МЕНЬШЕ = 4500
        ОПОВ_В_РЕЕСТРЕ_НЕ_МЕНЬШЕ = 60
        self.assertGreaterEqual(
            len(source), ЗНАКОВ_ПРИБОРА_НЕ_МЕНЬШЕ,
            f"исходник прибора — {len(source)} знаков при поле "
            f"{ЗНАКОВ_ПРИБОРА_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 5976 без прозы): тела "
            f"уехали, и «имён операций нет» стало правдой ни о чём")
        self.assertGreaterEqual(
            len(spec.OPS), ОПОВ_В_РЕЕСТРЕ_НЕ_МЕНЬШЕ,
            f"реестр знает {len(spec.OPS)} опов при поле "
            f"{ОПОВ_В_РЕЕСТРЕ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 82): искать в "
            f"исходнике нечего, и запрет зелен по построению")
        named = sorted(name for name in spec.OPS if name in source)
        self.assertEqual([], named,
                         "в приборе завелось имя операции — он стал списком: "
                         + ", ".join(named))

    def test_control_fail_the_name_ban_can_redden(self):
        """FAIL control for the name ban: a forged source must be caught."""
        from kir import spec
        in_code = _strip_prose("cap = 'one' if op == 'create_roof' else ''\n")
        self.assertIn("create_roof", in_code,
                      "запрет имён ослеп: имя в КОДЕ обязано остаться видимым")
        in_prose = _strip_prose('"""про create_roof и его подошву."""\nx = 1\n')
        self.assertNotIn("create_roof", in_prose,
                         "сторож ловит объяснение вместо поведения — тупой зонд")
        self.assertEqual(
            ["create_roof"],
            sorted(n for n in spec.OPS if n in in_code))

    def test_it_finds_todays_case_unaided(self):
        """Today's case must fall out of the output, not be written in by hand."""
        from kir.course import shape
        self.assertEqual(shape.ONE_RING, shape.ring_capacity()["create_roof"])
        bounds = shape.declared_boundaries()["create_roof"]
        self.assertTrue(
            any("hole" in what for _, what in bounds),
            f"граница кровли по дырам не найдена: {bounds}")

    def test_the_boundary_axis_prints_its_own_blindness(self):
        """CLOSED-BUT-NOT-COMPLETE must carry the NUMBER of what is invisible, not a caveat."""
        from kir.course import shape
        _, total, silent = shape._lift_refusals()
        self.assertGreater(total, 0)
        self.assertGreater(silent, 0, "либо слепоты нет, либо её не считают")
        self.assertLess(silent, total, "видимых отказов не осталось вовсе")
        self.assertIn(f"{silent}", shape.text(),
                      "знаменатель слепоты не напечатан — читатель сочтёт список полным")


class ExpressivenessCensusMustBeAbleToSayUnverified(unittest.TestCase):
    """The neighboring census declares TWO verification methods but accepted only ONE.

    `if checked_by not in (BY_RUN, BY_RUN)` rejected `разбором` — that is,
    "34 of 34 by execution" was green BY CONSTRUCTION: the type accepted no other
    value. The named defect of this tree: a degenerate control.
    """

    def test_both_declared_modes_are_accepted(self):
        from kir.course import expressiveness as ex
        ex.Row(ex.NATIVE, "проба", ex.BY_READ)
        ex.Row(ex.NATIVE, "проба", ex.BY_RUN)

    def test_an_undeclared_mode_is_still_refused(self):
        from kir.course import expressiveness as ex
        with self.assertRaises(ValueError):
            ex.Row(ex.NATIVE, "проба", "по ощущению")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
