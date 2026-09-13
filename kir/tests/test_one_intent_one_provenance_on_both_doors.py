"""A field's provenance does not depend on the DOOR: an omission through the
SDK and through raw JSON are the same intent and the same `FieldOrigin`.

🔴 BOUGHT ON 02.09.2026. The language has TWO fronts — the `sdk.py`
builders and the scripting door `dsl.py` — and their law is ONE: a registry
default is SHOWN in the signature and is NOT WRITTEN INTO the JSON (measured
03.08: writing it in erases the provenance and changes `plan_digest`, i.e.
the identity of the program's proof).

`dsl.py` held the law with a sentinel, `_RegistryDefault`, since 03.08.
`sdk.py` broke it, and not out of carelessness: the class lived IN
`dsl.py`, and `dsl` imports `sdk` — a reverse edge would have closed a
cycle, so the second front could not learn of the law BY CONSTRUCTION.
Measured discrepancy:

    sdk.create_wall(...) without height_mm  -> FieldOrigin.EXPLICIT
    the same omission via raw JSON          -> FieldOrigin.REGISTRY_DEFAULT

The carrier moved to the place where the default is defined
(`registry_base.RegistryDefault`, next to `ParamSpec.default`), and both
fronts call the SAME object.

THE DENOMINATOR IS NAMED: ops with a registry default — 11 of 82;
parameters with a default, 23. Of those, 8 are in `omission_transfers`, and
the overlap with the defaults is EXACTLY ZERO — meaning the loud rehearsal
report was NOT touched by this defect, and claiming otherwise would be an
exaggeration.
"""
from __future__ import annotations

import unittest

from kir import compiler, sdk, spec

SNAP = {"levels": [{"id": 311, "name": "L01"}],
        "wall_types": [{"id": 5011, "name": "K380"}],
        "floor_types": [{"id": 7011, "name": "F150"}]}
L = {"by": "name", "value": "L01"}

СЛУЧАИ = (
    ("create_wall", dict(level=L, type={"by": "name", "value": "K380"},
                         p0_mm=[0, 0], p1_mm=[6000, 0])),
    ("create_floor", dict(level=L, type={"by": "name", "value": "F150"},
                          outline=[[0, 0], [4000, 0], [4000, 3000], [0, 3000]])),
)


def _заглушка(p):
    if p.kind in ("int", "float", "number"):
        return 1
    if p.kind == "bool":
        return True
    if p.kind == "str":
        return "x"
    return {"by": "name", "value": "x"}


class ОдинПровенансНаОбеихДверях(unittest.TestCase):

    def test_sdk_не_вписывает_умолчание_НИ_В_ОДИН_оп(self) -> None:
        """The whole class, not a single case: a walk over THE ENTIRE registry."""
        вписано, проверено = [], 0
        for opname, s in spec.OPS.items():
            сdef = [p.name for p in s.params
                    if getattr(p, "default", None) is not None]
            if not сdef:
                continue
            строитель = getattr(sdk, opname, None)
            if строитель is None:
                continue
            kw = {p.name: _заглушка(p) for p in s.params if p.required}
            try:
                d = строитель(id="X", **kw)
            except Exception:            # an op that cannot be assembled with stubs
                continue
            d = d if isinstance(d, dict) else d.to_dict()
            проверено += 1
            лишние = [n for n in сdef if n in d]
            if лишние:
                вписано.append((opname, лишние))
        self.assertGreaterEqual(
            проверено, 5, "знаменатель пуст — зелёное значило бы «нечего было "
                          "проверять», а не «умолчания не вписываются»")
        self.assertEqual([], вписано)

    def test_обе_двери_дают_один_провенанс(self) -> None:
        сверено = 0
        for opname, kw in СЛУЧАИ:
            через_sdk = getattr(sdk, opname)(id="X1", **kw)
            через_sdk = (через_sdk if isinstance(через_sdk, dict)
                         else через_sdk.to_dict())
            сырой = dict(op=opname, id="X1", **kw)
            исходы = {}
            for метка, оп in (("sdk", через_sdk), ("json", сырой)):
                out = compiler.compile_program({"ops": [оп]},
                                               revit_version="2023",
                                               snapshot=SNAP, bulk=True)
                self.assertTrue(out.ok, f"{opname}/{метка}: программа не собралась")
                исходы[метка] = dict(out.planned.ops[0].provenance.field_origins)
            self.assertEqual(исходы["sdk"], исходы["json"],
                             f"{opname}: провенанс зависит от двери")
            сверено += len(исходы["sdk"])
        self.assertGreater(сверено, 0, "нечего было сверять")

    def test_носитель_один(self) -> None:
        """Otherwise the class is closed "for now," not by construction."""
        from kir import dsl, registry_base
        self.assertIs(dsl._RegistryDefault, registry_base.RegistryDefault)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
