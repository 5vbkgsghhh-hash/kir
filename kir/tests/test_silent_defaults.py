"""A silently inserted default turns a postcondition into a requirement that
the caller never made.

WHERE THE RULE COMES FROM. On 29.07 two facade runs — 4 walls and 16 walls — rolled back
entirely with "height mismatch" on EVERY wall. The walls had been built correctly.
The diagnosis: `height_mm` carries a registry default of 3000 mm, `_validate_op` puts it
into the normalized op BEFORE the emitter, and the emitter can no longer tell "asked
for exactly 3000" apart from "stayed silent, because the height is decided by `top_level`". A facade
wall between two levels naturally omits `height_mm` — while the compiler
promised exactly 3000 and rolled back everything that measured otherwise.

THE RULE THAT FOLLOWS FROM THIS. A parameter with a silently inserted default
has exactly two legal positions:

  THE EMITTER SETS IT — then the postcondition is legal: we made the promise, and we are the ones
  who keep it. This is the case for `create_window.sill_mm`: the insertion point IS COMPUTED as
  `__hl.Elevation + U(sill)`, and the check verifies that same value. This was measured, not
  assumed — `authoring.py:2382` against `authoring.py:2532`;

  REVIT DECIDES IT — then a postcondition on the defaulted value demands something
  no one asked for. This is exactly the case of wall height with a tied top: Revit
  derives it from the pair of levels, not from what was passed into `Wall.Create`.

The distinction is not in the parameter's type or its kind — it is in WHO assigns the value
in the built element.

WHY THIS TEST EXISTS. It cannot check "does the emitter set it" — that is a judgment call.
It does something else: it keeps the list of silently inserted defaults CLOSED. A seventh one
will not appear unnoticed; to add it, someone will have to come here and answer the
question above in words. Measured on 31.07: six of twenty. The remaining fourteen
do NOT make it into the normalized op, and their postconditions therefore never fire
on the caller's silence — in particular all the flips (`mirrored`, `hand_flipped`,
`facing_flipped`) on `create_door`, `create_window` and `place_family`. The live
door refusals of 21.07 came from a caller who NAMED the flips — that is a different
defect, and the two should not be confused.
"""
import unittest

from kir import compiler, spec

# The minimally valid sample for every op that has parameters with a
# default. Not "typical", but exactly minimal: the default is inserted precisely
# when the caller stayed silent.
MINIMAL = {
    "create_column": {"op": "create_column", "id": "C", "xyz": [0, 0, 0],
                      "level": {"by": "name", "value": "L"},
                      "symbol": {"by": "name", "value": "S"}},
    "create_door": {"op": "create_door", "id": "D",
                    "host": {"by": "ref", "value": "W"}, "offset_mm": 1000},
    "create_floor": {"op": "create_floor", "id": "F", "p0_mm": [0, 0],
                     "p1_mm": [1000, 1000], "level": {"by": "name", "value": "L"}},
    "create_type": {"op": "create_type", "id": "T",
                    "base": {"by": "name", "value": "B"}, "name": "N",
                    "width_mm": 300, "depth_mm": 400},
    "create_wall": {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                    "p1_mm": [6000, 0], "level": {"by": "name", "value": "L"}},
    "create_window": {"op": "create_window", "id": "N",
                      "host": {"by": "ref", "value": "W"}, "offset_mm": 1000},
    "create_stairs_run": {"op": "create_stairs_run", "id": "RN",
                          "stairs": {"by": "element_id", "value": 4242},
                          "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0],
                          "base_elevation_mm": 1800.0},
    "author_family": {"op": "author_family", "id": "AF",
                      "family_name": "F", "type_name": "T",
                      "profile": {"outer": {"shape": "rect",
                                            "origin": [0, 0],
                                            "size_mm": [600, 400]}},
                      "height_mm": 800, "flex_param": "H"},
    "place_family": {"op": "place_family", "id": "P", "xyz": [0, 0, 0],
                     "level": {"by": "name", "value": "L"},
                     "symbol": {"by": "name", "value": "S"}},
    "query_list": {"op": "query_list", "id": "Q", "kind": "wall"},
    "query_element_state": {"op": "query_element_state", "id": "STATE",
                            "unique_id": "00112233-4455-6677-8899-aabbccddeeff-00000123"},
    # 24.08.2026, together with `host_kind`: the kind of the host type (wall|floor|roof|
    # ceiling). The sample DELIBERATELY stays silent about it — the rule checks exactly
    # a silent caller.
    "create_wall_type": {"op": "create_wall_type", "id": "WT",
                         "source_type": {"by": "name", "value": "S"},
                         "new_name": "N",
                         "layers": [{"width_mm": 80, "function": "Substrate"}]},
}

# Measured 31.07. Every line is a promise the compiler makes on behalf of the
# caller. The right-hand column answers the question "who assigns the value in
# the built element".
SILENTLY_INJECTED = {
    ("create_wall", "height_mm"),      # Revit, if the top is tied → witness
                                       # taken under `top_level` (29.07)
    ("create_window", "sill_mm"),      # emitter: the insertion point is computed from
                                       # the same value → the witness is legal
    ("create_column", "category"),     # a choice of overload, not a property of the element
    ("create_type", "category"),       # the same
    ("query_list", "fields"),          # a read, builds no elements
    ("query_list", "limit"),           # a read
    ("author_family", "template"),
    # 21.08.2026, THE EIGHTH TENANT. The file's rule demands an answer to WHO assigns
    # the value in the built element, and here the answer is NEITHER ONE NOR THE OTHER, but
    # a third: `template` is not a property of the element AT ALL. It is a choice of the .rft
    # FILE from which the family document is created — the same role as
    # `create_column.category` above ("a choice of overload, not a property of the element").
    #
    # The promise the op makes about the template is read in its `post`, and it is about
    # RESOLVING THE PATH, not about a value: «template resolved from
    # Application.FamilyTemplatePath at execute time — a missing template is a
    # typed refusal naming the directory». That is, what is witnessed is that the file
    # was found and that the refusal is named, not that the element holds 'generic_model'.
    #
    # 🔴 AND THE CONVERSE IS SAID OUT LOUD, SO THAT THE SILENCE IS NOT READ AS A PROMISE:
    # the CATEGORY of the built family comes FROM the .rft and is not set by the
    # program — this is a named absence right in the op's own receipt
    # (`unverified_ru`: «категория семейства пришла ИЗ ШАБЛОНА и нами не
    # задавалась»). There is therefore no postcondition on the category and there cannot be one:
    # we do not choose it, we choose the template.
    ("create_stairs_run", "justification"),
    # 15.08.2026. The file's rule demands an answer to WHO assigns the value in
    # the built element. Here — the EMITTER: the word goes into the C# as a member name
    # (`StairsRunJustification.Center`) directly as an argument to CreateStraightRun,
    # which means the promise is ours and witnessing it is legitimate. Revit decides
    # nothing here. And yet there is NO verdict on it: the binding travels into the receipt
    # as the `justification` field, not as an `__post.Add` line, because it cannot be read back
    # from StairsRun by any means — the postcondition would only confirm the FACT
    # OF THE CALL, i.e. the named defect of this tree.
    # 24.08.2026, THE NINTH TENANT. The answer to the file's question — "who assigns
    # the value in the built element" — is here the same THIRD answer as for
    # `create_column.category`: NEITHER ONE NOR THE OTHER. `host_kind` is not a property
    # of the built type at all; it selects the REVIT CLASS the result is cast
    # to (`WallType`/`FloorType`/`RoofType`/`CeilingType` —
    # `HOST_TYPE_CLASS`, the sole authority). A built `FloorType` has no
    # "host_kind" field, it simply IS a floor type.
    #
    # There is therefore no postcondition on it and there cannot be one — witnessing it
    # would mean confirming the FACT OF THE CALL. What is actually witnessed is named
    # alongside it, EACH along its own axis: the type name, the layer count, the thickness and function
    # of each layer, the layer material, the sum of thicknesses (for a wall, `WallType.Width`, for
    # the rest `CompoundStructure.GetWidth()` — their classes have NO `Width`
    # property, 0/6 on real builds).
    ("create_wall_type", "host_kind"),
}


def _defaulted_params():
    out = []
    for name, ospec in spec.OPS.items():
        for p in ospec.params:
            if getattr(p, "default", None) is not None:
                out.append((name, p.name))
    return out


def _normalise(op_name):
    sample = MINIMAL[op_name]
    diags = []
    norm = compiler._validate_op(dict(sample), 0, diags)
    return norm, diags


class SilentDefaults(unittest.TestCase):
    def test_element_state_default_is_read_policy_not_an_injected_bim_value(self):
        parameter = next(p for p in spec.OPS["query_element_state"].params
                         if p.name == "include_type_definition")
        self.assertIs(parameter.default, False)
        for supplied in ({}, {"include_type_definition": False}):
            norm = compiler._validate_op({**MINIMAL["query_element_state"], **supplied}, 0, [])
            self.assertIsNotNone(norm)
            self.assertNotIn("include_type_definition", norm)
        norm = compiler._validate_op({**MINIMAL["query_element_state"],
                                      "include_type_definition": True}, 0, [])
        self.assertIs(norm["include_type_definition"], True)

    def test_every_op_with_defaults_has_a_minimal_sample(self):
        """Otherwise the list is not fully closed, and a new op will slip past it."""
        missing = {op for op, _ in _defaulted_params()} - set(MINIMAL)
        self.assertEqual(missing, set(),
                         "у этих опов есть параметры с default, но нет "
                         "минимального образца — правило их не проверяет")

    def test_minimal_samples_actually_validate(self):
        for op_name in sorted({op for op, _ in _defaulted_params()}):
            with self.subTest(op=op_name):
                norm, diags = _normalise(op_name)
                self.assertIsNotNone(norm, f"образец {op_name} не прошёл "
                                           f"валидацию: {[d.code for d in diags]}")

    def test_injected_set_is_closed(self):
        """The list is closed on BOTH sides: a new silent default must
        come here for an answer, and one that disappears must not remain in the list."""
        injected = set()
        for op_name, param in _defaulted_params():
            norm, _ = _normalise(op_name)
            if norm is not None and param in norm:
                injected.add((op_name, param))
        self.assertEqual(injected, SILENTLY_INJECTED)

    def test_flips_stay_absent_when_the_caller_is_silent(self):
        """Pinned separately, because the live door refusals of 21.07 were read
        as "the default is to blame", when it has nothing to do with it: a silent caller gets
        no flips in the normalized op, and the postcondition never fires."""
        for op_name in ("create_door", "create_window", "place_family"):
            norm, _ = _normalise(op_name)
            for flip in ("mirrored", "hand_flipped", "facing_flipped"):
                with self.subTest(op=op_name, param=flip):
                    self.assertNotIn(flip, norm)

    def test_explicit_value_survives_normalisation(self):
        """The converse control: what the caller named is neither lost nor
        substituted — otherwise the rule above would be checking emptiness."""
        op = dict(MINIMAL["create_wall"], height_mm=2700.0)
        norm, _ = compiler._validate_op(op, 0, []), None
        self.assertEqual(norm["height_mm"], 2700.0)
        op = dict(MINIMAL["create_door"], mirrored=True)
        norm = compiler._validate_op(op, 0, [])
        self.assertIs(norm["mirrored"], True)


if __name__ == "__main__":
    unittest.main()
