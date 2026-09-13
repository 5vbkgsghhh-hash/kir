"""THE CENSUS OF WHAT IS EXPRESSIBLE MUST COVER THE REGISTRY — AND TURN RED WHEN IT FALLS BEHIND.

The owner's directive of 19.08.2026: bring expressiveness up to the ceiling and
CLOSE IT. "Closed" in this tree means one thing: verified by a control that
turns red. A census without a ratchet is a list, and a list rots silently: this is exactly
how ALL of this tree's hand-written lists (`CREATED_KEYS`, `_STACKABLE`,
`KIND_TABLE`) drifted apart, and not a single generated one did.

What is guarded here:

1. COMPLETENESS BY CONSTRUCTION. The census's membership is taken from `spec.PARAM_KINDS`.
   A new parameter kind in the registry => no line for it => RED. Without this, a new kind
   would come into being inexpressible and stay silent, and the missing line would read as
   "no such thing exists."
2. A CONSTRUCTOR THAT IS PROMISED MUST BE REACHABLE BY THE AUTHOR. A promise in the
   census and a name in the script's namespace are two things that must agree, and
   nothing ties them together except this test.
3. A GAP WITHOUT A REASON AND AN OWNER IS INEXPRESSIBLE BY `Row`'s construction, and here this
   is checked by execution, not by trusting the constructor.
4. FAIL CONTROL: a guard that cannot turn red is worse than none at all.
"""
from __future__ import annotations

import unittest


class ПереписьВыразимогоПокрываетРеестр(unittest.TestCase):

    def test_every_registry_kind_has_a_row(self):
        from kir.course import expressiveness as ex
        missing = ex.missing_rows()
        assert not missing, (
            "род параметра есть в реестре и не назван в переписи: "
            f"{missing}. Значит автор может встретить значение, о котором "
            "перепись молчит, а молчание читается как «выразимо». Заведи "
            "строку в `course/expressiveness.py::CENSUS` с исходом и способом "
            "проверки")

    def test_no_row_without_a_registry_kind(self):
        from kir.course import expressiveness as ex
        stray = ex.stray_rows()
        assert not stray, (
            f"перепись описывает рода, которых в реестре нет: {stray}. "
            "Список объявлен ПОЛНЫМ ПО ПОСТРОЕНИЮ, а лишняя строка делает его "
            "вторым источником правды")

    def test_every_promised_constructor_is_reachable_by_the_author(self):
        """A promised name must live in the script's namespace.

        A capability the model has nowhere to read about does not exist for it; and a
        capability promised by the census but absent from the namespace is
        worse: it is a broken promise.
        """
        from kir.course import expressiveness as ex
        from kir.course.language import __all__ as reachable

        surface = set(reachable)
        promised = {
            "extrude": "mesh",
            "region": "region",
            "by_name": "sel",
            "by_element_id": "sel",
            "by_ref": "sel",
            "family_type": "sel",
            "disambiguate": "sel",
            "DEFAULT": "sel",
        }
        missing = sorted(n for n in promised if n not in surface)
        assert not missing, (
            f"перепись обещает конструкторы, которых нет в пространстве "
            f"скрипта: {missing}. Проверь `course.SANDBOX_NAMES` и "
            f"`dsl.__all__`")

    def test_a_gap_must_name_its_reason_and_its_owner(self):
        from kir.course import expressiveness as ex
        for name, row in ex.gaps().items():
            assert row.note, f"{name}: GAP без причины"
            assert row.owner, f"{name}: GAP без владельца потолка"

    def test_the_ratchet_can_actually_fail(self):
        """A FAIL CONTROL, and it is PRECISE: remove ONE line, expect ONE finding.

        A broad control here would be worse than a narrow one: "broke everything" and "the guard
        works" produce the same color, and what tells them apart is the SIZE of the finding.
        """
        from kir.course import expressiveness as ex

        assert not ex.missing_rows(), "перед контролем перепись обязана быть полна"
        victim = "mesh"
        saved = ex.CENSUS.pop(victim)
        try:
            found = ex.missing_rows()
            assert found == [victim], (
                f"снятие ОДНОЙ строки обязано дать РОВНО одну находку, "
                f"получено {found}")
        finally:
            ex.CENSUS[victim] = saved
        assert not ex.missing_rows(), "перепись не восстановлена"

    def test_the_denominator_is_not_zero(self):
        """A CONTROL ON THE DENOMINATOR: an empty registry would make the first test green
        by construction, and «zero gaps» would mean «nothing was looked at»."""
        from kir import spec
        from kir.course import expressiveness as ex
        assert len(spec.PARAM_KINDS) >= 30, (
            f"родов параметра всего {len(spec.PARAM_KINDS)} — почти наверняка "
            f"промах по авторитету, а не бедный реестр")
        assert len(ex.CENSUS) == len(spec.PARAM_KINDS)


if __name__ == "__main__":
    unittest.main()
