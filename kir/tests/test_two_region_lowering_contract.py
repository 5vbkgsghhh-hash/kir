"""AN OP WITH TWO PROFILES MUST BE EXPRESSIBLE — AND IT WAS UNCALLABLE.

THE MEASUREMENT OF 20.08.2026 THAT BOUGHT THIS FILE. `create_solid_blend` stood in the registry, in
the translation certificate's table, and in the emitter (`solid_emit.emit_solid_blend`
reads `__region_profile__` and `__region_profile_top__` by name) — and ANY
author's program using it died with `KIR-P000` on all six versions:

    ValueError: illegal grounding refinement at ops[B1].__region__:
                undeclared lowering field added

The op compiled, was listed as built, and was uncallable. This is the form "compilation
answers the question DOES IT EXIST, when what was asked was WILL IT RUN", raised one
level up: it was not a member of the API that existed, but an entire op.

🔴 KNOWLEDGE ABOUT REGIONS LIVED IN THREE PLACES, AND THEY WERE FIXED ONE AT A TIME.

    1. grounding                     which keys it PLACES (`ground.py`)
    2. `_recomputed_derived_artifact`  which keys it is LEGAL to add
    3. `_assert_payload_refinement`    which keys MUST be present

Fixing only (2) produced not green, but the NEXT refusal — «required
lowering artifacts missing: ['__region__']»: the named key was already being accepted, while
the generic one was still required. There were three carriers of one rule, and each stayed silent
about the existence of the others. Hence the law of this file: a fix that touches the kind of a
value must be checked AGAINST EVERY CARRIER separately, otherwise the green of
one is read as the green of the rule.

THE BOUNDARY HELD DELIBERATELY. For an op with ONE region, only the generic
`__region__` is legal; a named one is still illegal there. Otherwise one value would get
two legal addresses, and the next wave would pick either one — exactly the class
this defect grew out of in the first place.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_two_region_queue.jsonl"))

from kir import contour as contour_mod                      # noqa: E402
from kir import midend                                      # noqa: E402
from kir.compiler import compile_program                    # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT              # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

_LOW = {"outer": {"shape": "rect", "origin": [0.0, 0.0],
                  "size_mm": [2000.0, 2000.0]}}
_TOP = {"outer": {"shape": "rect", "origin": [400.0, 400.0],
                  "size_mm": [1200.0, 1200.0]}}


def _blend_program() -> dict:
    return {"ir_version": "1.0", "ops": [
        {"op": "create_solid_blend", "id": "B1", "category": "generic_model",
         "name": "пуфик", "height_mm": 900.0,
         "profile": _LOW, "profile_top": _TOP}]}


def _planned_blend() -> dict:
    return {"op": "create_solid_blend", "id": "B1",
            "category": "generic_model", "name": "пуфик",
            "height_mm": 900.0, "profile": _LOW, "profile_top": _TOP}


def _region(raw: dict) -> dict:
    diags: list = []
    out = contour_mod.validate_region(raw, [], "B1", "profile", diags)
    assert out is not None and not diags, diags
    return out


def _assert(planned: dict, grounded: dict) -> None:
    midend._assert_payload_refinement(
        planned, grounded, path="ops[B1]", grounded_by_id={},
        snapshot=GROUND_SNAPSHOT)


class TheOpIsCallableAtAll(unittest.TestCase):

    def test_an_authored_blend_compiles_on_every_version(self) -> None:
        """DIRECT EVIDENCE OF THE DEFECT: before the fix, this was KIR-P000 six times."""
        for ver in VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_blend_program(), revit_version=ver,
                                      snapshot=GROUND_SNAPSHOT)
                codes = [d.code for d in out.diagnostics]
                self.assertTrue(out.ok, f"{ver}: {codes}")

    def test_both_profiles_reach_the_grounded_op_under_their_own_names(self) -> None:
        """The generic key was losing everything except the last one, and the blend was building a degenerate
        body SILENTLY. Here both profiles must arrive DIFFERENT."""
        out = compile_program(_blend_program(), revit_version="2026",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        # `GroundedOp` stores the payload as canonical JSON and hands it out
        # only through `to_dict()` — deliberately, so that nobody edits
        # the grounded value in place.
        op = out.grounded.ops[0].to_dict()
        self.assertIn("__region_profile__", op)
        self.assertIn("__region_profile_top__", op)
        self.assertNotEqual(op["__region_profile__"],
                            op["__region_profile_top__"],
                            "низ и верх приехали одинаковыми — потеря профиля")


class EachCarrierOfTheRuleHasItsOwnControl(unittest.TestCase):
    """Three carriers — three controls. The green of one does NOT prove the rule."""

    def test_carrier_two_named_keys_are_legal_additions(self) -> None:
        g = dict(_planned_blend())
        g["__region_profile__"] = _region(_LOW)
        g["__region_profile_top__"] = _region(_TOP)
        _assert(_planned_blend(), g)          # it does not throw — that is exactly the check

    def test_carrier_two_control_an_INVENTED_region_name_is_still_illegal(self) -> None:
        """A CONTROL WITHOUT WHICH THE FIRST ONE IS WORTH NOTHING.

        An extension accepting ANY key of the form `__region_*__` would remove the
        protection entirely: grounding could again add a field out of nowhere.
        Legal are EXACTLY the names of this op's region parameters.
        """
        g = dict(_planned_blend())
        g["__region_profile__"] = _region(_LOW)
        g["__region_profile_top__"] = _region(_TOP)
        g["__region_выдумка__"] = _region(_LOW)
        with self.assertRaises(ValueError) as caught:
            _assert(_planned_blend(), g)
        self.assertIn("undeclared lowering field added", str(caught.exception))

    def test_carrier_three_a_missing_named_key_is_refused(self) -> None:
        """The second carrier: the list of REQUIRED artifacts.

        It is precisely this one that stayed unfixed while the first was already accepting the keys, and
        the refusal moved one line down instead of disappearing.
        """
        g = dict(_planned_blend())
        g["__region_profile__"] = _region(_LOW)
        with self.assertRaises(ValueError) as caught:
            _assert(_planned_blend(), g)
        self.assertIn("required lowering artifacts missing", str(caught.exception))

    def test_carrier_three_the_common_key_alone_no_longer_satisfies(self) -> None:
        """A generic `__region__` on an op with two profiles is exactly that silent
        loss. It must be INSUFFICIENT, not merely undesirable."""
        g = dict(_planned_blend())
        g["__region__"] = _region(_TOP)
        with self.assertRaises(ValueError):
            _assert(_planned_blend(), g)


class TheSingleRegionBoundaryHolds(unittest.TestCase):
    """For an op with ONE region, nothing has changed — and this is checked."""

    def _planned_floor(self) -> dict:
        return {"op": "create_floor_by_contour", "id": "F1",
                "level": {"__grounded__": {"id": 42, "name": "L1",
                                           "via": "element_id"}},
                "contour": _LOW}

    def test_one_region_still_travels_under_the_common_key(self) -> None:
        g = dict(self._planned_floor())
        g["__region__"] = _region(_LOW)
        midend._assert_payload_refinement(
            g and self._planned_floor(), g, path="ops[F1]",
            grounded_by_id={}, snapshot=GROUND_SNAPSHOT)

    def test_a_named_key_on_a_ONE_region_op_stays_illegal(self) -> None:
        """THE BOUNDARY. Two legal addresses for one value is exactly the
        class the defect grew out of; it must not be reopened."""
        g = dict(self._planned_floor())
        g["__region__"] = _region(_LOW)
        g["__region_contour__"] = _region(_LOW)
        with self.assertRaises(ValueError) as caught:
            midend._assert_payload_refinement(
                self._planned_floor(), g, path="ops[F1]",
                grounded_by_id={}, snapshot=GROUND_SNAPSHOT)
        self.assertIn("undeclared lowering field added", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
