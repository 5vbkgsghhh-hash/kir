"""`translation_cert.REFINEMENT` ПУСТ до первого обращения к аксессору.

КЛАСС ДЕФЕКТА: величина УТВЕРЖДАЕТСЯ в одном месте и ЧИТАЕТСЯ в другом, и
ничто не заставляет их совпасть. Здесь утверждение — экспортируемое имя
`REFINEMENT` в `__all__` и строка модульной докстроки «``REFINEMENT`` is the
machine form of the prose ``OpSpec.post``»; чтение — модульный словарь,
который на свежем интерпретаторе содержит НОЛЬ записей и наполняется лишь
как побочный эффект `_ensure_table()` (его зовут `certify_op`,
`certify_program`, `audit_registry_coverage`).

ЧЕМ ЭТО ПЛОХО ИМЕННО ЗДЕСЬ. Прямой читатель не получает ошибку — он получает
ПУСТО, то есть «обязательств нет», что неотличимо от «оп ничего не обещает».
Замер 11.08 на свежем процессе:

    from kukai.ir.translation_cert import REFINEMENT
    len(REFINEMENT)              -> 0
    REFINEMENT["create_wall"]    -> KeyError

Единственным прямым читателем в дереве был `tests/test_space.py` (волна
create_space, 10.08). Под `pytest-randomly`, который перемешивает порядок
НАМЕРЕННО, он проходил или падал в зависимости от того, вызвал ли кто-то
раньше `certify_op`. Тест исправлен на аксессор; этот файл держит сам капкан,
чтобы следующий не завёл второго такого читателя.

ПОЧЕМУ ПРОВЕРКА В ОТДЕЛЬНОМ ПРОЦЕССЕ. Состояние модуля глобально: очистить
его в этом процессе значило бы сломать соседние тесты при случайном порядке —
то есть чинить один экземпляр класса, заводя другой.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest


def _fresh(code: str) -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    env = dict(os.environ)
    env["PYTHONPATH"] = root
    env.setdefault("KIR_REJECTIONS_PATH", os.path.join(
        os.environ.get("TMPDIR", "/tmp"), "kir_lazy_probe.jsonl"))
    out = subprocess.run([sys.executable, "-c", textwrap.dedent(code)],
                         capture_output=True, text=True, cwd=root, env=env)
    return (out.stdout + out.stderr).strip()


class TheTableIsEmptyUntilTouched(unittest.TestCase):

    def test_a_bare_import_sees_no_obligations_at_all(self):
        """Не ошибка, а ПУСТО — и это хуже: «обязательств нет» неотличимо от
        «оп ничего не обещает»."""
        self.assertEqual(
            _fresh("""
                from kukai.ir.translation_cert import REFINEMENT
                print(len(REFINEMENT))
            """).splitlines()[-1], "0")

    def test_indexing_it_raises_rather_than_answering(self):
        self.assertIn("KeyError", _fresh("""
            from kukai.ir.translation_cert import REFINEMENT
            try:
                REFINEMENT["create_wall"]
                print("answered")
            except KeyError:
                print("KeyError")
        """).splitlines()[-1])

    def test_the_accessor_is_what_fills_it(self):
        last = _fresh("""
            from kukai.ir import translation_cert as tc
            before = len(tc.REFINEMENT)
            tc._ensure_table()
            print(before, len(tc.REFINEMENT))
        """).splitlines()[-1].split()
        self.assertEqual(last[0], "0")
        self.assertGreater(int(last[1]), 60)

    def test_no_test_in_the_tree_reads_the_bare_name(self):
        """Второго такого читателя быть не должно. Правило узкое: индексация
        или итерация ПО ИМЕНИ `REFINEMENT` без `_ensure_table()` рядом."""
        import pathlib
        import re
        here = pathlib.Path(__file__).resolve().parent
        offenders = []
        for path in sorted(here.rglob("test_*.py")):
            if path.name == pathlib.Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"\bREFINEMENT\s*\[", text):
                window = text[max(0, m.start() - 400):m.start()]
                if "_ensure_table()" not in window:
                    offenders.append("%s:%d" % (
                        path.name, text[:m.start()].count("\n") + 1))
        self.assertEqual(
            offenders, [],
            "читают REFINEMENT по голому имени (на свежем процессе он ПУСТ): "
            + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
