"""Лифтер потолка читает параметр, которого захват никогда не кладёт.

`_lift_ceiling` берёт смещение из `CEILING_HEIGHTABOVELEVEL_PARAM`
(`lift.py:1787`). Экстрактор кладёт `FLOOR_HEIGHTABOVELEVEL_PARAM`
(`extract.py:772`) и никогда — потолочный. Ключа в строке L0 нет, `_finite`
возвращает None, `height_offset_mm` не ставится — и потолок поднимается на
отметке уровня. МОЛЧА: не отказом, а нулём, то есть худшим из двух исходов,
названных в ведомости захвата.

Собственный тест лифтера этого поймать не мог по построению —
`test_lift_arch.py:62` кладёт `element["params"]["CEILING_HEIGHTABOVELEVEL_
PARAM"]` руками. Контракт двух компонентов проверялся против ФИКСТУРЫ, а не
против того, что вторая сторона действительно производит; фикстура согласилась
с лифтером, потому что её писал тот же человек в тот же час.

Отсюда форма теста: он не про потолок. Он про то, что КАЖДОЕ имя
`BuiltInParameter`, которое лифтеры читают из `element.params`, произносится и
в эмитируемом C# захвата. Потолок — первый случай, который это правило ловит;
ценность правила в том, что оно поймает и следующий.
"""
import ast
import pathlib
import re
import unittest

_DECOMPILE = pathlib.Path(__file__).resolve().parents[1]
_LIFT = _DECOMPILE / "lift.py"
_EXTRACT = _DECOMPILE / "extract.py"

#: Имена параметров выглядят как BuiltInParameter: КАПС и подчёркивания.
#: Строгий отбор нужен, чтобы не принять за параметр обычный ключ словаря.
_BIP = re.compile(r"^[A-Z][A-Z0-9_]{4,}$")


def _params_read_by_lifters() -> set[str]:
    """Имена, которые лифтеры спрашивают у `element.params`.

    Разбор синтаксисом, а не регуляркой: вопрос «прочитано ли имя У params»,
    а не «встречается ли строка в файле» — упоминание в докстринге узлом
    `ast.Call` не является и стать им не может."""
    tree = ast.parse(_LIFT.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in ("get", "__getitem__"):
            continue
        owner = fn.value
        # ...element.params.get(NAME) / el.params.get(NAME)
        if not (isinstance(owner, ast.Attribute) and owner.attr == "params"):
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if _BIP.match(arg.value):
                found.add(arg.value)
    return found


def _params_named_by_capture() -> str:
    return _EXTRACT.read_text(encoding="utf-8")


class CaptureCoversWhatLiftersRead(unittest.TestCase):
    def test_lifters_read_at_least_one_parameter(self):
        """Иначе тест ниже проходит на пустоте."""
        self.assertGreaterEqual(len(_params_read_by_lifters()), 5)

    def test_ceiling_offset_is_captured(self):
        """Именованный случай — чтобы отказ сборки объяснял СЕБЯ."""
        self.assertIn("CEILING_HEIGHTABOVELEVEL_PARAM", _params_named_by_capture(),
                      "лифтер потолка читает CEILING_HEIGHTABOVELEVEL_PARAM, "
                      "а захват его не кладёт — каждый потолок поднимается на "
                      "отметке уровня молча")

    def test_every_parameter_a_lifter_reads_is_captured(self):
        capture = _params_named_by_capture()
        missing = sorted(n for n in _params_read_by_lifters() if n not in capture)
        self.assertEqual(missing, [],
                         "эти имена лифтеры спрашивают у L0, а экстрактор их "
                         "не произносит — значит ключа в строке не будет "
                         "никогда, и вместо отказа выйдет молчаливый ноль")


if __name__ == "__main__":
    unittest.main()
