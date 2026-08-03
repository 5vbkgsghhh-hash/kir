"""Every op that builds geometry must have a witness that can see geometry.

Three times in one night a postcondition passed over wrong geometry, and each
time for the same reason: the witness checked what the emitter had just set
rather than what the author had asked for.

* a wall's location line — compared an enum ordinal, while the wall body stood
  where it always had;
* a slanted column — demanded back a level parameter the emitter deliberately
  never wrote;
* a pitched roof — asked whether the roof had gained ANY height, and accepted
  one built at 38 degrees instead of 45.

A witness written in the same hour, by the same hand, as the emission it
guards inherits that emission's blind spots. The only obligation that does not
is one phrased against geometry Revit reports back independently: a location,
a curve endpoint, a bounding box, an elevation.

So this is a structural rule, not a review habit: an emitter that creates
geometry must reference at least one of those. The allowlist below is for ops
that genuinely create none, and every entry states why.
"""

from __future__ import annotations

import pathlib
import re
import unittest


_IR_DIR = pathlib.Path(__file__).resolve().parents[1]

#: Helpers whose whole purpose is a geometric obligation.
_GEOMETRY_HELPERS = ("endpoint_witness(", "bbox_extents_witness(")

#: Properties Revit computes from the model itself, so an emitter cannot
#: satisfy them merely by having written a parameter.
_GEOMETRY_READS = (
    "Location", "get_BoundingBox", "GetEndPoint", ".Point", "Origin",
    "FacingOrientation", "HandOrientation", ".Elevation",
)

#: Ops that create no geometry at all. Each entry is a claim that has to stay
#: true, not a way to silence the check.
_NO_GEOMETRY = {
    "_emit_create_type": "creates a TYPE; no instance exists to measure",
    "_emit_load_family": "loads a family file; places nothing",
    "_emit_setparam": "writes a parameter on an element it did not create",
    "_emit_delete": "removes elements; the absence is checked by count",
    "_emit_pipe_system": "declares a system; its segments carry the geometry",
    # set_curtain_panel carries no coordinate at all: host + cell address +
    # type. The cell's shape is cut by the host's curtain grid, which this op
    # neither creates nor moves — exactly set_param's position, one level up
    # (a TYPE instead of a value). The claim that has to stay true: the day
    # this op gains a coordinate (a grid line, an offset), this entry is false
    # and must go, because then a wrong shape could commit silently.
    "_emit_set_curtain_panel": "assigns a TYPE to an existing grid cell; the "
                               "op carries no coordinate and cuts no grid",
    # CLASH-починка (28.07): change_type is set_param's own exemption one
    # level up — a TYPE change on an element it did not create, no
    # coordinate anywhere in the op. Its witness (GetTypeId() re-read) is
    # semantic/identity, not geometric, on purpose: Element.ChangeTypeId
    # moves nothing (the rare new-element case is still the SAME location,
    # per RevitAPI.xml — a curtain-panel<->wall type swap, not a move). The
    # claim that has to stay true: the day this op gains a coordinate
    # (e.g. a re-host), this entry is false and must go.
    "_emit_change_type": "changes an element's TYPE; no coordinate — the "
                         "rare new-element case (RevitAPI.xml) still commits "
                         "the SAME location, so nothing here moves",
}


def _all_function_bodies() -> dict[str, str]:
    """Every top-level function in the IR package, keyed by bare name.

    Emitters delegate freely -- doors and windows to the hosted emitter, beams
    and foundations into struct_emit -- so an analysis that stops at
    authoring.py reports four false defects. It did, before this followed them.
    """
    out: dict[str, str] = {}
    for path in sorted(_IR_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        starts = [(m.group(1), m.start())
                  for m in re.finditer(r"^def (\w+)\(", src, re.M)]
        for i, (name, start) in enumerate(starts):
            end = starts[i + 1][1] if i + 1 < len(starts) else len(src)
            out.setdefault(name, src[start:end])
    return out


def _emitters() -> dict[str, str]:
    """The op emitters, taken from the dispatch table rather than from names.

    ``_emit_`` is not a reliable marker: compiler.py has ``_emit_collector``
    and ``_emit_row``, which build query C# and place nothing. Reading
    ``_EMITTERS`` asks the code which functions actually author elements.
    """
    table = (_IR_DIR / "authoring.py").read_text(encoding="utf-8")
    start = table.index("_EMITTERS = {")
    # Balanced scan: the table closes on the same line as its last entry, so
    # searching for a lone brace finds the wrong one -- or none at all.
    depth, end = 0, start
    for end in range(table.index("{", start), len(table)):
        if table[end] == "{":
            depth += 1
        elif table[end] == "}":
            depth -= 1
            if depth == 0:
                break
    names = set(re.findall(r":\s*(_emit_\w+)", table[start:end]))
    assert names, "the emitter dispatch table could not be read"
    bodies = _all_function_bodies()
    return {n: bodies[n] for n in sorted(names) if n in bodies}


#: ``return other(...)`` or ``return mod.other(...)`` and nothing else of
#: substance: the obligation lives in the callee.
_DELEGATION = re.compile(r"return\s+(?:\w+\.)?(\w+)\(", re.M)


def _has_geometric_witness(body: str, depth: int = 2) -> bool:
    if (any(h in body for h in _GEOMETRY_HELPERS)
            or any(t in body for t in _GEOMETRY_READS)):
        return True
    if depth <= 0:
        return False
    bodies = _all_function_bodies()
    return any(_has_geometric_witness(bodies[target], depth - 1)
               for target in _DELEGATION.findall(body)
               if target in bodies)


#: Known debt, frozen by name. These two route whole MEP runs -- many segments
#: and fittings from one polyline -- and verify none of it geometrically: a
#: pipe laid along the wrong path satisfies every postcondition they have.
#: Deliberately NOT fixed in the same hour it was found: the three geometric
#: hypotheses tested against live Revit tonight were all refuted, and MEP
#: routing has not been exercised live at all, so a witness written from
#: reading alone would very likely guard the wrong thing.
_KNOWN_NAKED = {
    "_emit_route_pipe_system",
    "_emit_route_duct_system",
}


class EveryGeometryOpIsWitnessedGeometrically(unittest.TestCase):
    def test_no_new_emitter_guards_only_what_it_set(self):
        naked = {name for name, body in _emitters().items()
                 if name not in _NO_GEOMETRY
                 and not _has_geometric_witness(body)}

        self.assertEqual(
            sorted(naked - _KNOWN_NAKED), [],
            "these emitters create geometry and no postcondition can see it, "
            "so a wrong shape commits silently: "
            + ", ".join(sorted(naked - _KNOWN_NAKED)))

    def test_the_debt_list_shrinks_and_never_goes_stale(self):
        # A ratchet: once an emitter earns a geometric witness its name has to
        # leave this list, or the list stops describing anything real.
        naked = {name for name, body in _emitters().items()
                 if name not in _NO_GEOMETRY
                 and not _has_geometric_witness(body)}

        self.assertEqual(
            sorted(_KNOWN_NAKED - naked), [],
            "these are listed as debt but are witnessed now — drop them: "
            + ", ".join(sorted(_KNOWN_NAKED - naked)))

    def test_the_allowlist_names_only_real_emitters(self):
        # An entry left behind after a rename would silently exempt nothing —
        # or worse, keep exempting an op that has since grown geometry.
        missing = sorted(set(_NO_GEOMETRY) - set(_emitters()))

        self.assertEqual(missing, [], f"allowlist names no such emitter: {missing}")

    def test_every_exemption_carries_a_reason(self):
        for name, reason in _NO_GEOMETRY.items():
            with self.subTest(emitter=name):
                self.assertGreater(
                    len(reason.split()), 3,
                    f"{name} is exempt without saying why")

    def test_the_detector_recognises_a_naked_emitter(self):
        # Guard the guard: if the token list stopped matching, the check above
        # would pass vacuously for every op forever.
        self.assertFalse(_has_geometric_witness(
            'checks = [WitnessCheck(verdict_cs="__el.get_Parameter(X)")]'))

    def test_the_detector_follows_one_delegation(self):
        # _emit_door is three lines long and hands everything to the hosted
        # emitter; treating it as naked was the detector's own first bug.
        self.assertTrue(_has_geometric_witness(
            "def _emit_door(op, ver, stamp):\n"
            "    return _emit_hosted(op, ver, stamp, 'door')\n"))

    def test_the_detector_accepts_each_geometric_form(self):
        for token in _GEOMETRY_HELPERS + _GEOMETRY_READS:
            with self.subTest(token=token):
                self.assertTrue(_has_geometric_witness(f"checks = [{token}]"))


if __name__ == "__main__":
    unittest.main()
