"""THE `LiftResult` FIELD THE CACHE DOES NOT KNOW ABOUT DISAPPEARS SILENTLY.

🔴 WHY THIS FILE EXISTS, MEASURED 22.08.2026. The joins lifter was written in
full (`lift.lift_joins`, 1 992 pairs on MNVNK) and COULD NOT REACH the
program. One of the two seams is here: `lift_cache.serialize_lift_result` is
assembled FIELD BY FIELD by hand, and it would drop a new field, leaving the
cached parse to come back without joins and without a single sign of loss.

This is a named class of defect in this tree: a value is asserted in one
place (the dataclass) and read in another (the serializer), and nothing
forces them to match. It is removed not by carefulness but by ASKING
whether they correspond — by reflection over the fields, not by eyeballing
a diff.

THE NON-EMPTINESS CONTROL HERE IS MANDATORY: a guard that cannot turn red
is indistinguishable from an absent one. That is why below there is a
check against a FORGED serializer that drops a field — and it is required
to catch it.
"""
from __future__ import annotations

import dataclasses
import unittest

from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import (
    GroupLift,
    GroupLiftReason,
    GroupRefusal,
    JoinLift,
    JoinLiftReason,
    JoinRefusal,
    LiftDiagnostic,
    LiftResult,
)
from kir.decompile.lift_cache import (
    deserialize_lift_result,
    serialize_lift_result,
)


def _full_result() -> LiftResult:
    """An instance in which EVERY field is non-empty and distinguishable."""
    return LiftResult(
        nodes=({"_id": "n1", "op_name": "create_wall",
                "source_element_id": "100", "kind": "op", "params": {}},),
        diagnostics=(LiftDiagnostic(
            source_element_id="200", category="OST_Walls",
            reason=AtomReason.MISSING_GEOMETRY, detail="нет кривой"),),
        joins=JoinLift(
            ops=({"op": "join_elements", "_id": "j1",
                  "first": {"ref": "n1"}, "second": {"ref": "n2"}},),
            refusals=(JoinRefusal(
                first="100", second="300",
                reason=JoinLiftReason.TARGET_STAYED_ATOM,
                detail="OST_Walls/missing_geometry"),),
            pairs_read=2,
            end_joins_read=872,
            walls_with_end_permission=17,
            end_states={"joined": 3, "not_read": 1, "free_end": 5},
            elements_not_read=("400", "401"),
        ),
        # 🔴 THE GROUPS ARE FILLED NOT FOR COMPLETENESS BUT SO THE GUARD IS
        # NOT GREEN BY CONSTRUCTION. A field left as `None` passes both the
        # key check and the round trip — meaning a new carrier was added
        # but not checked. Exactly the shape this whole file was written
        # for.
        groups=GroupLift(
            ops=({"op_name": "create_group",
                  "params": {"members": [{"ref": "n1"}],
                             "placements": [[0.0, 0.0, 3300.0]],
                             "name": "Фасад_ГБ под окнами_2+"},
                  "sources": ("100",)},),
            refusals=(GroupRefusal(
                group_type_id="g1", group_type_name="АР_Фасад_5 этаж_",
                reason=GroupLiftReason.MEMBER_COUNT_OVER_CEILING,
                detail="членов 410, а create_group.members принимает 200"),),
            definitions_read=177,
            instances_read=575,
            instances_covered=77,
            member_ops=522,
            ops_not_written_individually=756,
            composition_mismatches=4,
        ),
    )


class КаждоеПолеПереживаетКэш(unittest.TestCase):

    def test_у_каждого_поля_есть_свой_ключ_в_нагрузке(self):
        """Reflection over the dataclass — otherwise the guard would know
        the map, not the subject."""
        payload = serialize_lift_result(_full_result())
        for f in dataclasses.fields(LiftResult):
            with self.subTest(поле=f.name):
                self.assertIn(
                    f.name, payload,
                    f"поле {f.name!r} у `LiftResult` есть, а в нагрузке кэша "
                    "его НЕТ — кэшированный разбор потеряет его молча")

    def test_круг_возвращает_то_же_самое(self):
        """The key is not enough: the value must survive the round trip IN
        FULL."""
        before = _full_result()
        after = deserialize_lift_result(serialize_lift_result(before))
        self.assertEqual(after, before)

    def test_ОТСУТСТВИЕ_индекса_и_ПУСТЫЕ_соединения_различимы(self):
        """"The index was not supplied" and "it was supplied, there are no
        joins" are different facts.

        Collapsing them into one would mean recording OUR blindness as a
        fact about the building — the very shape for which the graph has
        `sources_absent`, and the cache has `unmeasured_relations`.
        """
        нет_индекса = LiftResult(nodes=(), diagnostics=(), joins=None)
        пусто = LiftResult(nodes=(), diagnostics=(), joins=JoinLift())
        self.assertIsNone(
            deserialize_lift_result(serialize_lift_result(нет_индекса)).joins)
        восстановлено = deserialize_lift_result(
            serialize_lift_result(пусто)).joins
        self.assertIsNotNone(восстановлено)
        self.assertEqual(восстановлено.pairs_read, 0)

    def test_ОТСУТСТВИЕ_индекса_и_ПУСТЫЕ_группы_различимы(self):
        """The same distinction for GROUPS, and at the same cost of error:
        an empty `GroupLift` means "asked, there are no groups," `None`
        means "did not ask."""
        нет = LiftResult(nodes=(), diagnostics=(), groups=None)
        пусто = LiftResult(nodes=(), diagnostics=(), groups=GroupLift())
        self.assertIsNone(
            deserialize_lift_result(serialize_lift_result(нет)).groups)
        назад = deserialize_lift_result(serialize_lift_result(пусто)).groups
        self.assertIsNotNone(назад)
        self.assertEqual(назад.definitions_read, 0)

    def test_версия_обёртки_поднята_вместе_с_формой(self):
        """A record of the old version does not carry the new field —
        reading it as one's own would mean returning "there are no joins"
        on a document where there are, and since 23.08.2026 also "there
        are no design units" where there are 177 of them.

        The literal here is DELIBERATE and is not a forgotten second
        carrier: it exists so the version CANNOT fail to be bumped when a
        field is added. The guard must turn red on every change of shape —
        that is exactly what makes it useful."""
        from kir.decompile.lift_cache import LIFT_CACHE_WRAPPER_VERSION
        self.assertEqual(LIFT_CACHE_WRAPPER_VERSION, "lift-cache/3")

    def test_СТОРОЖ_УМЕЕТ_ПОКРАСНЕТЬ(self):
        """FAIL CONTROL: a serializer that drops a field must be caught.

        Without this, the whole file is green by construction.
        """
        payload = serialize_lift_result(_full_result())
        payload.pop("joins")
        missing = [f.name for f in dataclasses.fields(LiftResult)
                   if f.name not in payload]
        self.assertEqual(missing, ["joins"],
                         "проверка полей обязана видеть потерю, иначе она "
                         "не проверка")


if __name__ == "__main__":
    unittest.main()
