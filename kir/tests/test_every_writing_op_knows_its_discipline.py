"""EVERY writing operation's project discipline is either derived or NAMED as not derivable.

WHY THIS FILE EXISTS. Work in a design organization is organized BY
DISCIPLINE: one contractor for architecture, another for structural, another for each engineering
discipline. A discipline recorded in the registry lets you narrow both the tool's description and the
write permission — that is, it makes the boundary CHECKABLE rather than promised in a prompt. This
has been recorded in `registry_base.DISCIPLINES` since it first appeared; here it is
pinned with a number.

WHAT IS ACTUALLY GUARDED, AND IT IS NOT "EVERYONE HAS A DISCIPLINE." For some ops the
discipline CANNOT be derived, and that is a legitimate outcome: the result's category depends on the
snapshot (`place_family`), or the acceptance judge does not know the category. Requiring a discipline for
all of them would force the next person to dump the underivable ones into `shared`, and
`shared` in this dictionary means "belongs to everyone," not "unknown."

So what is guarded is a PAIR: `ops_by_discipline` and `ops_without_discipline` must
cover the registry with no leftover and no overlap, and EVERY line of the second must
carry its reason in words. A gap named out loud gets closed; a gap dumped
into `shared` lives forever and looks like a fact.
"""
from __future__ import annotations

import re
import unittest
from unittest import mock

from kir import spec
from kir.registry_base import DISCIPLINES


def _writing() -> list:
    return [o for o in spec.OPS.values() if o.writes_model]


class ПараПокрываетРеестрБезОстатка(unittest.TestCase):
    """Derived and underivable together are the ENTIRE registry, and nothing twice."""

    def test_covered_and_uncovered_partition_the_registry(self) -> None:
        covered = {name
                   for _d, names in spec.ops_by_discipline(writes=True)
                   for name in names}
        uncovered = {name for name, _why in spec.ops_without_discipline(writes=True)}
        everything = {o.name for o in _writing()}

        self.assertEqual(covered | uncovered, everything,
                         "пишущий оп потерялся между двумя списками")
        self.assertEqual(covered & uncovered, set(),
                         "оп стоит и в выведенных, и в невыведенных — "
                         "читатель получит два разных ответа на один вопрос")

    def test_every_uncovered_op_names_its_reason(self) -> None:
        for name, why in spec.ops_without_discipline(writes=True):
            with self.subTest(op=name):
                self.assertTrue(
                    why.strip(),
                    f"{name}: раздел не выведен и причина НЕ НАЗВАНА — "
                    "«слепо» без объяснения неотличимо от «забыли»")

    def test_every_named_discipline_is_from_the_closed_dictionary(self) -> None:
        for discipline, _names in spec.ops_by_discipline(writes=True):
            with self.subTest(discipline=discipline):
                self.assertIn(discipline, DISCIPLINES)


class КаталожныйОпОбщийПоАвторитетуПриёмки(unittest.TestCase):
    """An op that places a CATALOG entry rather than a building element is `shared`.

    The argument is the same as for `set_param`: ALL disciplines consume the entry. A loaded
    family becomes a door for architecture and a fitting for plumbing; a material gets assigned to both a wall and
    a duct.

    🔴 And the main thing pinned here: the list of such ops is NOT DUPLICATED. It lives
    in `acceptance._OPS_WITHOUT_ELEMENTS` with a reason and a date on every line, and it is
    queried from there. A second list of the same names would drift from the first on
    the very first new op.
    """

    def test_the_authority_is_acceptance_not_a_local_list(self) -> None:
        from kir.acceptance import _OPS_WITHOUT_ELEMENTS

        source = spec.op_disciplines.__doc__ or ""
        self.assertNotIn("create_wall_type", source,
                         "имя каталожного опа проросло в докстроку правила — "
                         "это второй носитель списка")

        creating = [n for n in _OPS_WITHOUT_ELEMENTS
                    if n in spec.OPS
                    and spec.OPS[n].effect is spec.EffectKind.CREATE]
        self.assertTrue(creating, "контроль вырожден: каталожных опов ноль")
        for name in creating:
            with self.subTest(op=name):
                self.assertEqual(spec.op_disciplines(spec.OPS[name]),
                                 (("shared",), ""),
                                 f"{name}: каталожный оп обязан быть shared")

    def test_a_catalogue_op_that_leaves_the_authority_stops_being_shared(self) -> None:
        """FAIL CONTROL: remove the name from the authority — `shared` must disappear."""
        # 🔴 THE SUBSTITUTION TARGETS THE AUTHORITY (28.08.2026). The list moved from
        # `acceptance` to `spec` — the registry stopped asking its own
        # consumer. A substitution left pointed at `acceptance` would affect
        # an ALIAS and not the subject: the control would turn green BY
        # CONSTRUCTION, meaning it would stop proving anything. Object
        # identity is checked separately (`test_the_authority_is_one_object`).
        victim = "create_wall_type"
        self.assertEqual(spec.op_disciplines(spec.OPS[victim])[0], ("shared",))

        thinner = frozenset(spec.OPS_WITHOUT_ELEMENTS) - {victim}
        with mock.patch.object(spec, "OPS_WITHOUT_ELEMENTS", thinner):
            got, why = spec.op_disciplines(spec.OPS[victim])
        self.assertEqual(got, (),
                         f"{victim} остался shared без авторитета — значит "
                         "правило спрашивает не его, а что-то своё")
        self.assertTrue(why.strip(), "потеряв авторитет, оп обязан назвать причину")


class КонтрольFAIL(unittest.TestCase):
    """The instrument must be able to say "no" — otherwise green means nothing."""

    @staticmethod
    def _without_category(category: str):
        """Both carriers of the discipline dictionary WITHOUT this category."""
        from kir.decompile import extract

        kinds = {n: k for n, k in spec.KINDS.items()
                 if not re.search(rf"BuiltInCategory\.{category}\b",
                                  k.collector_cs)}
        specs = [c for c in extract._CATEGORY_SPECS if c.name != category]
        return mock.patch.multiple(spec, KINDS=kinds), \
            mock.patch.object(extract, "_CATEGORY_SPECS", specs)

    def test_removing_the_carrier_moves_the_op_into_the_counter(self) -> None:
        """Remove the category from the carriers — the op must move into the underivable set."""
        victim, category = "create_wall", "OST_Walls"

        before = spec.op_disciplines(spec.OPS[victim])
        self.assertEqual(before, (("architectural",), ""),
                         "контроль вырожден: предмет уже не выведен")
        n_before = len(spec.ops_without_discipline(writes=True))

        p_kinds, p_specs = self._without_category(category)
        with p_kinds, p_specs:
            spec._category_disciplines.cache_clear()
            got, why = spec.op_disciplines(spec.OPS[victim])
            n_after = len(spec.ops_without_discipline(writes=True))
        spec._category_disciplines.cache_clear()

        self.assertEqual(got, (),
                         f"{victim} сохранил раздел без носителя — значит "
                         "раздел взят не из таблицы, а откуда-то ещё")
        self.assertIn("не значатся ни у одного носителя", why)
        self.assertGreater(n_after, n_before,
                           "счётчик не вырос — он не меряет свой предмет")

        self.assertEqual(spec.op_disciplines(spec.OPS[victim]), before,
                         "предмет не восстановился: кеш таблицы протёк "
                         "за границу контроля")

    def test_an_unknown_category_is_counted_not_silently_shared(self) -> None:
        """What is underivable is NOT dumped into `shared`: these are different assertions."""
        uncovered = {n for n, _w in spec.ops_without_discipline(writes=True)}
        self.assertTrue(uncovered, "контроль вырожден: невыведенных ноль")

        shared = dict(spec.ops_by_discipline(writes=True)).get("shared", [])
        self.assertEqual(uncovered & set(shared), set(),
                         "оп с невыведенным разделом объявлен общим — "
                         "пробел учёта подан как факт о продукте")


class СчётчикНеРастётМолча(unittest.TestCase):
    """Ratchet: the number of underivable ops is named here and must move down.

    An upper bound, not an equality: closing the debt is allowed, growing it —
    only together with this line.
    """

    #: Measured 27.08.2026, the `main` tree, after the catalog rule (it was 29).
    #:
    #: 🔴 23 -> 25 (03.09.2026), AND THIS IS GROWTH FROM KNOWLEDGE, NOT FROM ROT. A live
    #: measurement removed an argument that had stood in the tree: "Revit does not give a routing
    #: placeholder its own category, it stays in OST_DuctCurves/OST_PipeCurves." IT DOES
    #: give one — OST_PlaceHolderDucts and OST_PlaceHolderPipes, both compile on
    #: 2021-2026. The registry was corrected against the measurement, and this is exactly why two writing
    #: ops lost their discipline: the discipline dictionary is ASSEMBLED from collectors, and
    #: the placeholder's collector goes by a class with the `IsPlaceholder` predicate and
    #: never names the category as text.
    #:
    #: Adding them to the dictionary by hand would mean setting up a SECOND discipline
    #: dictionary, which is forbidden (`spec._category_disciplines`). So both
    #: categories are named in `spec.CATEGORIES_WITHOUT_DISCIPLINE` with a deadline of
    #: 03.10.2026, and the bar is raised HERE — in the same move, exactly as the
    #: docstring above requires.
    ПОТОЛОК = 25

    def test_the_debt_does_not_grow_silently(self) -> None:
        rows = spec.ops_without_discipline(writes=True)
        self.assertLessEqual(
            len(rows), self.ПОТОЛОК,
            "невыведенных разделов стало больше, чем записано в этом тесте.\n"
            "Это не повод поднять число: сперва спроси, у нового опа раздел "
            "НЕ ВЫВОДИТСЯ или его источник просто не назван.\n"
            + "\n".join(f"    {n}: {w}" for n, w in rows))


if __name__ == "__main__":
    unittest.main()
