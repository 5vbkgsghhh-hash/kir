"""The turn's document is chosen in ONE place. A second carrier blinds the instruments.

🔴 THE CASE THAT PAID FOR THIS FILE (25.08.2026). `_turn_document_context` was set up
as a pair "name + version" — and not by calling `_turn_document_title`, but by REPEATING
its body: the same `turn_document_title()`, the same `newest_first` traversal, the
same "the one that declared beats the traversal" rule. The outcome after a single day:

    document-selection carriers          2
    callers of `_turn_document_title`    0   (it stayed dead)
    blinded tests                        3   (they were substituting the dead function)

The live path worked — the copy was CORRECT. A correct copy is a postponement, not
soundness: such pairs drift apart silently, and not on the day they are set up.

WHY THIS IS EXPENSIVE EXACTLY HERE. The document choice decides WHICH BUILDING
the index for the author's script is assembled from. Getting it wrong means handing the model the
levels and grids of the WRONG building, and the refusal will arrive as «уровень не найден» — not the
real cause, and the author will go off to fix something that isn't broken. This very outcome was paid
for by the audit of 24.08 and is recorded verbatim in `_turn_document_title`'s docstring.

WHY GREP IS NOT A GUARD HERE. It would answer "both functions are in place" — and both
were in place. The question is not "do they exist" but "ARE THEY CONNECTED," and the only
thing that answers it is execution: swap the carrier out and see whether the swap gets through.
"""
from __future__ import annotations

import unittest

from kir import serving


class ВыборДокументаОдин(unittest.TestCase):

    def setUp(self) -> None:
        self._родной = serving._turn_document_title

    def tearDown(self) -> None:
        serving._turn_document_title = self._родной

    def test_контекст_берёт_имя_у_единственного_носителя(self) -> None:
        """Swapping the carrier must GET THROUGH to the pair.

        If it doesn't get through — the name is being chosen somewhere else, meaning there
        are two carriers again, and one of them will soon drift apart from the other.
        """
        serving._turn_document_title = lambda: "ПОДПИСЬ-НОСИТЕЛЯ-7788"
        имя, _версия = serving._turn_document_context()
        self.assertEqual(имя, "ПОДПИСЬ-НОСИТЕЛЯ-7788", msg=(
            "имя документа пришло НЕ от `_turn_document_title` — значит выбор "
            "документа снова живёт в двух местах. Именно так 25.08.2026 три "
            "теста ослепли, подменяя функцию, которую больше никто не звал"))

    def test_пустое_имя_даёт_пустую_пару(self) -> None:
        """CONTROL: the instrument must be able to tell presence from absence.

        Without this, the previous test would also go green on a carrier whose answer goes
        nowhere — a coincidental match would be enough.
        """
        serving._turn_document_title = lambda: ""
        self.assertEqual(serving._turn_document_context(), ("", ""))

    def test_версия_не_приезжает_от_чужого_имени(self) -> None:
        """A wrong document's version is worse than a missing one.

        The version is taken from the session whose name MATCHED the chosen one. If there is
        no match — the field is empty, not "whichever was found": the version of a foreign
        document is quieter than an absence, and therefore more dangerous.
        """
        serving._turn_document_title = lambda: "ДОКУМЕНТ-КОТОРОГО-НЕТ-9999"
        имя, версия = serving._turn_document_context()
        self.assertEqual(имя, "ДОКУМЕНТ-КОТОРОГО-НЕТ-9999")
        self.assertEqual(версия, "", "версия приехала не от того документа")

    def test_носитель_не_остался_без_вызывающих(self) -> None:
        """A dead carrier means blinded instruments, not just extra code.

        It is counted from the SOURCE of the whole package: a function nobody
        calls cannot turn red from any substitution, and every test that
        substitutes it is green by construction.
        """
        import ast
        from pathlib import Path

        # 🔴 THE DENOMINATOR OF THE WALK, MEASURED 02.09.2026: **318** package files outside
        # `test_*`. Without it, "a caller was found" and "the walk read three files and
        # stumbled on one" are indistinguishable: the mask, the root, or the filter drift
        # from the tree silently, and fewer found means fewer found defects.
        ФАЙЛОВ_ПАКЕТА_НЕ_МЕНЬШЕ = 250
        корень = Path(serving.__file__).resolve().parent
        зовут = []
        прочитано = 0
        for путь in sorted(корень.rglob("*.py")):
            if путь.name.startswith("test_"):
                continue
            дерево = ast.parse(путь.read_text(encoding="utf-8"))
            прочитано += 1
            for узел in ast.walk(дерево):
                if (isinstance(узел, ast.Call)
                        and isinstance(узел.func, ast.Name)
                        and узел.func.id == "_turn_document_title"):
                    зовут.append(f"{путь.name}:{узел.lineno}")
        self.assertGreaterEqual(
            прочитано, ФАЙЛОВ_ПАКЕТА_НЕ_МЕНЬШЕ,
            f"обход прочёл {прочитано} файлов при поле "
            f"{ФАЙЛОВ_ПАКЕТА_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 318). Это "
            f"заявление о ХОДОКЕ, а не о носителе")
        self.assertTrue(зовут, msg=(
            "`_turn_document_title` не зовёт НИКТО. Он и есть носитель выбора "
            "документа; без вызывающих он мёртв, а приборы, его подменяющие, "
            "слепы. Ровно это состояние и стоило трёх красных 25.08.2026"))


if __name__ == "__main__":
    unittest.main()
