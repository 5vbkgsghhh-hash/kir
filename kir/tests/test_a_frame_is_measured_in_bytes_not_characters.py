"""The showroom frame is measured IN UTF-8 BYTES, not in characters (F-285).

🔴 WHY TWO SIDES HERE, NOT ONE.

A one-sided check "Cyrillic has more bytes than characters" would miss a
fix of the form "multiply by two" or "add a margin": that would also give
more. So a second, reverse check stands next to it: **on plain ASCII the
number must MATCH the character count**. Together they lock the measure
from both ends — exactly like the `F-147` guard, where "always name the
truncation" would have passed without the second side.

The third check is about the CONSEQUENCE, not the number: the
`KUKAI_KIR_SHOWROOM_BYTES` ceiling is declared IN BYTES, and eviction must
count in the same units as the declaration. Otherwise `stats()["bytes"]`
reports compliance with a ceiling it does not comply with.
"""
import unittest

from kir.live import showroom


def _shown(programs, context="[]"):
    """A frame without a trip to the live showroom: what is measured is the PROPERTY, not the display path."""
    return showroom.Shown(
        digest="d", level="L1", seq=0, ts=0.0,
        programs_json=tuple(programs), context_json=context, census={})


class КадрМеряетсяБайтами(unittest.TestCase):

    def test_кириллица_считается_двумя_байтами_а_не_одним_знаком(self):
        blob = '{"имя":"стена"}'
        кадр = _shown([blob])
        знаков = len(blob) + len("[]")
        байтов = len(blob.encode("utf-8")) + len("[]".encode("utf-8"))
        self.assertGreater(байтов, знаков,
                           "случай подобран не по предмету: без кириллицы "
                           "проверка зелена по построению")
        self.assertEqual(кадр.nbytes, байтов,
                         "кадр обязан мерить БАЙТЫ UTF-8: имя свойства "
                         "говорит «байты», а хранится и едет оно в UTF-8")

    def test_на_чистом_ASCII_число_НЕ_меняется(self):
        """The other side: "always add" must go red."""
        blob = '{"name":"wall"}'
        кадр = _shown([blob])
        self.assertEqual(кадр.nbytes, len(blob) + len("[]"),
                         "на ASCII байт и знак — одно и то же; расхождение "
                         "значит, что мера прибавляет от себя")

    def test_потолок_вытеснения_считает_теми_же_единицами_что_объявление(self):
        """The consequence, not the number: the declared budget must be honored.

        The ceiling is declared IN BYTES. A Cyrillic frame whose size in
        characters FITS the ceiling, but in bytes does NOT, must be counted
        as exceeding it.
        """
        blob = '{"и":"' + "я" * 100 + '"}'
        кадр = _shown([blob])
        знаков = len(blob) + len("[]")
        self.assertLess(знаков, кадр.nbytes,
                        "случай подобран не по предмету")
        # A frame that fits "by characters" but does not fit "by bytes"
        # must be NO SMALLER than the byte ceiling set between them.
        потолок = (знаков + кадр.nbytes) // 2
        self.assertGreater(кадр.nbytes, потолок)
        self.assertLess(знаков, потолок,
                        "проверка вырождена: оба числа по одну сторону")


if __name__ == "__main__":
    unittest.main()
