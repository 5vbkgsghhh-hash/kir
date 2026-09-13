"""The ceiling lifter reads a parameter that capture never writes.

`_lift_ceiling` takes the offset from `CEILING_HEIGHTABOVELEVEL_PARAM`
(`lift.py:1787`). The extractor writes `FLOOR_HEIGHTABOVELEVEL_PARAM`
(`extract.py:772`) and never the ceiling one. The key is absent from the
L0 row, `_finite` returns `None`, `height_offset_mm` is not set — and the
ceiling comes up at the level's elevation. SILENTLY: not as a refusal but
as a zero — the worse of the two outcomes named in the capture ledger.

The lifter's own test could not catch this by construction —
`test_lift_arch.py:62` sets
`element["params"]["CEILING_HEIGHTABOVELEVEL_PARAM"]` by hand. The
contract between the two components was checked against a FIXTURE, not
against what the other side actually produces; the fixture agreed with
the lifter because the same person wrote both within the same hour.

Hence this test's shape: it is not about the ceiling. It is about every
`BuiltInParameter` NAME that lifters read from `element.params` also
being spoken by the capture's emitted C#. The ceiling is the first case
this rule catches; the rule's value is that it will catch the next one
too.
"""
import ast
import pathlib
import re
import unittest

_DECOMPILE = pathlib.Path(__file__).resolve().parents[1]
_LIFT = _DECOMPILE / "lift.py"
_EXTRACT = _DECOMPILE / "extract.py"

#: Parameter names look like BuiltInParameter: CAPS and underscores.
#: Strict filtering is needed so an ordinary dict key is not mistaken for
#: a parameter.
_BIP = re.compile(r"^[A-Z][A-Z0-9_]{4,}$")


def _params_read_by_lifters() -> set[str]:
    """The names lifters ask of `element.params`.

    Parsed by syntax, not by regex: the question is "was the name read
    FROM params," not "does the string occur in the file" — a mention in
    a docstring is not an `ast.Call` node and cannot become one."""
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
        """Otherwise the test below passes on emptiness."""
        self.assertGreaterEqual(len(_params_read_by_lifters()), 5)

    def test_ceiling_offset_is_captured(self):
        """A named case — so that a build failure explains ITSELF."""
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
