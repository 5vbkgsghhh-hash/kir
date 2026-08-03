"""Каждый ``tol_key`` обязан разрешаться в реестре допусков.

``registry_base.py:149`` формулирует инвариант прямо: «spec.OPS[name].
tolerances[key] so each number lives in ONE place».  ``WitnessCheck.tol_key``
существует ровно затем, чтобы хранить ПРОВЕНАНС этого числа.

Дефект, который ловит этот модуль (арх-разбор 2026-07-25): ключ, на который
никто не отвечает.  Такой ``tol_key`` — не безобидная опечатка, а ЛОЖЬ о
происхождении: проверка заявляет, что допуск взят из реестра, тогда как число
захардкожено в эмитируемой C#-строке.  Правка допуска в реестре ничего не
меняет, а аудит «где живут допуски» получает неверный ответ.

Тест структурный, а не пример-ориентированный: он проверяет ВСЕ ключи разом,
поэтому закрывает класс дефекта, а не один его экземпляр.
"""

from __future__ import annotations

import pathlib
import re
import unittest

from kukai.ir import spec


_AUTHORING = pathlib.Path(__file__).resolve().parents[1] / "authoring.py"
_TOL_KEY_RE = re.compile(r'tol_key\s*=\s*"([^"]+)"')


def _used_tolerance_keys() -> set[str]:
    return set(_TOL_KEY_RE.findall(
        _AUTHORING.read_text(encoding="utf-8")))


def _defined_tolerance_keys() -> dict[str, list[str]]:
    defined: dict[str, list[str]] = {}
    for op_name, op_spec in spec.OPS.items():
        for key in (getattr(op_spec, "tolerances", None) or {}):
            defined.setdefault(key, []).append(op_name)
    return defined


class ToleranceKeysResolve(unittest.TestCase):
    def test_every_used_key_is_defined_somewhere(self) -> None:
        used = _used_tolerance_keys()
        self.assertTrue(used, "в authoring.py не нашлось ни одного tol_key — "
                              "регэксп устарел, тест перестал что-либо ловить")
        defined = _defined_tolerance_keys()
        dangling = sorted(key for key in used if key not in defined)
        self.assertEqual(
            dangling, [],
            "tol_key ссылается в пустоту: проверка заявляет допуск из реестра, "
            "а число захардкожено в эмитируемой C#")

    def test_no_orphan_tolerances(self) -> None:
        """Обратная сторона: допуск в реестре, которым никто не пользуется.

        Не ошибка корректности, но мёртвая запись создаёт впечатление, что
        число где-то работает.  Держим реестр честным в обе стороны.
        """

        used = _used_tolerance_keys()
        orphans = sorted(
            f"{key} ({', '.join(sorted(ops))})"
            for key, ops in _defined_tolerance_keys().items()
            if key not in used)
        self.assertEqual(
            orphans, [],
            "допуск определён в реестре, но ни одна проверка его не берёт")

    def test_tolerances_are_positive_finite_numbers(self) -> None:
        for op_name, op_spec in sorted(spec.OPS.items()):
            for key, value in (getattr(op_spec, "tolerances", None)
                               or {}).items():
                with self.subTest(op=op_name, key=key):
                    self.assertIsInstance(value, (int, float))
                    self.assertNotIsInstance(value, bool)
                    self.assertGreater(
                        float(value), 0.0,
                        "нулевой/отрицательный допуск делает проверку либо "
                        "невыполнимой, либо бессмысленной")


if __name__ == "__main__":
    unittest.main()
