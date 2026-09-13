"""THE AUTHOR'S LINE MAKES IT TO THE OPERATION — and disappears if the
sidecar is removed.

WHAT THIS GUARDS. On a script failure, the model has long received its
own line (`SandboxRefusal.line`/`script_frames`). A SUCCESSFULLY built op
did not have one, and this is exactly when a COMPILER refusal arrives:
Python ran fine, the program was assembled, and the forty-first operation
out of sixty fails. The model received `op_id` and had no idea which
line of ITS OWN code produced that op.

WHY THE CONTROL IS TWO-SIDED. A test that only checks for the presence
of a line is also green when the line is FAKED — and a plausible-looking
number is more dangerous than an absence, because nobody argues with it
(form 44). Hence the second half: remove the sidecar and require that
the provenance DISAPPEAR, rather than being filled in with someone
else's.
"""
from __future__ import annotations

import unittest

from kir import dsl, sandbox


def _run(source: str):
    return sandbox.execute_author_script(source)


class ПроисхождениеДоезжает(unittest.TestCase):

    def test_a_flat_loop_names_the_line_that_made_each_op(self):
        # The walls are born on line 3 (counting from one).
        source = (
            "for i in range(3):\n"
            "    create_wall(p0_mm=[0, i * 500], p1_mm=[4000, i * 500],\n"
            "                level='L01')\n"
        )
        result = _run(source)
        self.assertTrue(result.ok, msg=getattr(result.refusal, "message_ru", ""))
        self.assertEqual(len(result.ops), 3)
        self.assertTrue(result.lineage,
                        "происхождение пусто: сайдкар не доехал из ребёнка")
        for op in result.ops:
            oid = op["id"]
            self.assertIn(oid, result.lineage,
                          f"у операции {oid} нет строки автора")
            frames = result.lineage[oid]
            self.assertTrue(frames, f"пустая цепочка у {oid}")
            # `[-1]` is the INNERMOST frame, the same shape as
            # script_frames.
            self.assertEqual(frames[-1], 2,
                             f"{oid}: строка автора {frames[-1]}, а вызов на 2")

    def test_a_call_through_a_function_keeps_BOTH_ends_of_the_chain(self):
        """A chain, not a single line — or the author fixes the wrong
        spot.

        A call through the author's own function gives a line INSIDE the
        function; the call site lies OUTSIDE it, and the author needs
        both ends."""
        source = (
            "def row(y):\n"
            "    create_wall(p0_mm=[0, y], p1_mm=[4000, y], level='L01')\n"
            "\n"
            "row(0)\n"
        )
        result = _run(source)
        self.assertTrue(result.ok, msg=getattr(result.refusal, "message_ru", ""))
        frames = result.lineage[result.ops[0]["id"]]
        self.assertGreaterEqual(len(frames), 2,
                                f"цепочка схлопнулась в один конец: {frames}")
        self.assertEqual(frames[-1], 2, "внутренний конец — тело функции")
        self.assertEqual(frames[0], 4, "внешний конец — место вызова")

    def test_the_forty_first_op_of_sixty_is_addressable(self):
        """The exact case all this is for: it's not the first operation
        that fails."""
        source = (
            "for i in range(60):\n"
            "    create_wall(p0_mm=[0, i * 500], p1_mm=[4000, i * 500],\n"
            "                level='L01')\n"
        )
        result = _run(source)
        self.assertTrue(result.ok, msg=getattr(result.refusal, "message_ru", ""))
        self.assertEqual(len(result.ops), 60)
        oid = result.ops[40]["id"]
        self.assertIn(oid, result.lineage)
        self.assertEqual(result.lineage[oid][-1], 2)

    def test_calling_the_language_directly_has_no_author_line(self):
        """Outside the sandbox there IS NO provenance — and that is an
        honest answer, not a gap.

        Filling in a line from our own file here would mean blaming the
        author for code he never wrote."""
        dsl.reset()
        dsl.create_wall(p0_mm=[0, 0], p1_mm=[4000, 0], level="L01")
        program = dsl.current()
        self.assertEqual(program._lineage, {},
                         "язык, вызванный напрямую, выдумал строку автора")
        dsl.reset()


class КонтрольFAIL(unittest.TestCase):
    """Removing the sidecar must LOSE the line, not substitute someone
    else's."""

    def test_without_the_sidecar_the_lineage_is_absent_not_wrong(self):
        source = (
            "for i in range(3):\n"
            "    create_wall(p0_mm=[0, i * 500], p1_mm=[4000, i * 500],\n"
            "                level='L01')\n"
        )
        alive = _run(source)
        self.assertTrue(alive.ok)
        self.assertTrue(alive.lineage, "предусловие: с сайдкаром строка есть")

        # We remove EXACTLY the outward-facing door — the same move that
        # would remove it on a rollback of the fix. The child lives in a
        # different process, so we mute the parsing on the parent's
        # side: faking it on the child's side would require editing the
        # source, i.e. measuring a different tree.
        original = sandbox._result_from_payload

        def _blind(payload, policy):
            payload = dict(payload)
            payload.pop("lineage", None)
            return original(payload, policy)

        sandbox._result_from_payload = _blind
        try:
            blinded = _run(source)
        finally:
            sandbox._result_from_payload = original

        self.assertTrue(blinded.ok)
        self.assertEqual(blinded.lineage, {},
                         "сайдкар снят, а происхождение осталось — значит оно "
                         "берётся не оттуда, откуда объявлено")
        self.assertEqual(
            [op["id"] for op in blinded.ops], [op["id"] for op in alive.ops],
            "снятие происхождения изменило саму программу — сайдкар не сайдкар")


class ПятыйПодписантЕдет(unittest.TestCase):
    """`building_digest` was computed, stamped, and went nowhere."""

    def test_building_digest_reaches_the_receipt(self):
        source = "create_wall(p0_mm=[0, 0], p1_mm=[4000, 0], level='L01')\n"
        with_building = sandbox.execute_author_script(
            source, building={"levels": [{"id": 1, "name": "L01"}]})
        self.assertTrue(with_building.ok,
                        msg=getattr(with_building.refusal, "message_ru", ""))
        self.assertTrue(with_building.building_digest,
                        "подпись здания не посчиталась")
        self.assertIn("building_digest", with_building.as_dict(),
                      "подпись здания посчитана, стамплена и НЕ доехала")
        self.assertEqual(with_building.as_dict()["building_digest"],
                         with_building.building_digest)

    def test_without_a_building_the_key_is_absent_not_empty(self):
        """«No catalog was supplied» must look like a missing key."""
        source = "create_wall(p0_mm=[0, 0], p1_mm=[4000, 0], level='L01')\n"
        bare = sandbox.execute_author_script(source)
        self.assertTrue(bare.ok, msg=getattr(bare.refusal, "message_ru", ""))
        self.assertNotIn("building_digest", bare.as_dict())

    def test_a_different_building_moves_the_signature(self):
        """The signature must DISTINGUISH catalogs, or it certifies
        nothing."""
        source = "create_wall(p0_mm=[0, 0], p1_mm=[4000, 0], level='L01')\n"
        a = sandbox.execute_author_script(
            source, building={"levels": [{"id": 1, "name": "L01"}]})
        b = sandbox.execute_author_script(
            source, building={"levels": [{"id": 2, "name": "L02"}]})
        self.assertTrue(a.ok and b.ok)
        self.assertEqual(a.author_digest, b.author_digest,
                         "предусловие: исходник тот же")
        self.assertNotEqual(a.building_digest, b.building_digest,
                            "две РАЗНЫЕ модели дали одну подпись здания")


if __name__ == "__main__":
    unittest.main()
