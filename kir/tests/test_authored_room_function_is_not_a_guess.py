"""A FUNCTION THE AUTHOR NAMED MUST NOT BE GUESSED AT.

WHY THE `create_room.function` FIELD, SET UP ON 28.08.2026. Before it,
on the FORWARD turn a room's kind was derived from a lexicon applied to
the free-form string `name` — even when the program is written by an
LLM that knows perfectly well it is building a bedroom. A measurement
from the same day: 81 names in eight languages, the lexicon recognizes
23 of 81, six of the eight languages get zero. And the owner's decision:
do NOT grow the dictionary toward completeness, "you can't foresee every
word, and if you decide to try, that's a pile of junk in the code."

Hence the fork, and both of its branches were built the same day:

    the BACKWARD turn (a foreign model)  names are foreign -> ask the
                                          HOST (`ports.ROOM_CLASSIFIER`),
                                          kind `derived`
    the FORWARD turn (the LLM writes)    the author knows the answer ->
                                          let him STATE it, kind
                                          `explicit`, nothing to guess at
                                          all

🔴 WHY THIS FIELD DOES NOT TRAVEL INTO REVIT — A DECISION, NOT AN
OVERSIGHT. There is no typed function slot for a room in Revit:
`ROOM_OCCUPANCY` does not appear in the captured API signatures at all,
and `ROOM_DEPARTMENT` is a free-form string ALREADY CLAIMED for a
different purpose (it is where `apartment_id` is read from, and a live
measurement gives it just ONE group across 1102 rooms). Writing the
function there would mean colliding two different subjects in one
parameter and breaking apartment inference. So the kind lives in the KIR
model — and that is why the cost of the fix is measured in "hours," not
"days": emission is not touched at all.

WHAT THE FIX DID NOT REQUIRE, AND THIS IS A MEASUREMENT, NOT AN
IMPRESSION. Not a single new line in the validator, the schema, or the
author's Python: the `enum` kind ALREADY EXISTS in the registry (27
parameters across 23 ops), the model case is `create_wall.location_line`,
and the `KIR-T001` refusal prints the whole dictionary by itself. Not a
single character in the tool description: `build_tool_description` does
not print op parameters at all, so the 30,000 ceiling was never the
deciding number here (measured: 29,964 -> 29,964, a control on a dummy
OP gives +14, so the instrument is alive).

Run: pytest kir/tests/test_authored_room_function_is_not_a_guess.py -q
"""
from __future__ import annotations

from kir import spec
from kir.authoring_validation import validate
from kir.checker.spatial_model import RoomFunction
from kir.design_check import spatial_model_from_ops

_SQUARE = [(0, 0), (5000, 0), (5000, 4000), (0, 4000)]


def _program(function: str | None) -> list[dict]:
    """A single room in a closed contour. The ONE difference is whether
    the function was named."""
    ops: list[dict] = [{"op": "create_level", "id": "L1", "elev_mm": 0, "name": "L1"}]
    for i, (a, b) in enumerate(zip(_SQUARE, _SQUARE[1:] + _SQUARE[:1])):
        ops.append({"op": "create_wall", "id": f"w{i}",
                    "p0_mm": [a[0], a[1]], "p1_mm": [b[0], b[1]],
                    "level": {"by": "ref", "value": "L1"}, "height_mm": 3000})
    room = {"op": "create_room", "id": "r0", "xy": [2500, 2000],
            "level": {"by": "ref", "value": "L1"},
            # The name is DELIBERATELY German: the lexicon does not know
            # it, so it is visible that it's the declared function that
            # changes the outcome, not a name coincidence.
            "name": "Schlafzimmer", "upper_offset_mm": 2700}
    if function is not None:
        room["function"] = function
    ops.append(room)
    return ops


def _room(function: str | None):
    model, _ = spatial_model_from_ops(_program(function), building_id="AB")
    assert len(model.rooms) == 1, "контур не собрался — сравнивать нечего"
    return model.rooms[0]


# ------------------------------------------------------ TWO DICTIONARIES OF ONE SUBJECT

def test_the_registry_vocabulary_never_drifts_from_RoomFunction():
    """🔴 THE REGISTRY'S DICTIONARY AND `RoomFunction` — ONE SUBJECT, TWO
    PLACES.

    The op registry has no right to import the validator (they are
    different layers), so the list of values is spelled out by hand in
    `ops_authoring.py`. Two lists drifting apart over ONE subject is our
    own named defect, and this equality — not attentiveness — is what
    guards against it.
    """
    param = {p.name: p for p in spec.OPS["create_room"].params}["function"]
    assert param.kind == "enum"
    assert not param.required, "функция ОБЯЗАТЕЛЬНОЙ быть не может: программы, " \
                               "написанные до 28.08, не перестают быть законными"
    assert tuple(param.choices) == tuple(f.value for f in RoomFunction)


# ------------------------------------------------------ WHAT THE DECLARATION CHANGES

def test_a_declared_function_wins_over_the_guess_and_says_so():
    """🔴 THE MAIN MEASUREMENT: the declaration CHANGES THE OUTCOME, or
    the fix would have been for show only.

    The name "Schlafzimmer" is unknown to the lexicon, so without a
    declaration the room falls into `OTHER` — and `OTHER` silently
    lifts every suitability rule. With the declaration it is
    RESIDENTIAL, and its kind is `explicit`.
    """
    guessed, declared = _room(None), _room("жилая")
    assert guessed.function is RoomFunction.ПРОЧЕЕ
    assert declared.function is RoomFunction.ЖИЛАЯ
    assert guessed.function_source == "declared"
    assert declared.function_source == "explicit"


def test_declared_and_explicit_are_both_authored_but_not_the_same_word():
    """`declared` and `explicit` are both author-sourced — and yet they
    are DIFFERENT claims.

    Under `declared` lies OUR OWN guess at the meaning of a word the
    author wrote. Under `explicit` lies nothing but the author's own
    answer. Erasing this distinction would mean losing the one place
    that shows whether we were guessing or not.
    """
    from kir.checker import function_provenance as fp

    assert fp.is_authored("declared") and fp.is_authored("explicit")
    assert "declared" != "explicit"
    assert fp.AUTHORED >= {"declared", "explicit"}


def test_a_program_without_the_field_behaves_exactly_as_before():
    """The field is optional: a program written before 28.08 is judged
    exactly as it always was.

    A condition of the fix, not a convenience: this tree is installed
    in the live prod venv as editable (`KIR_PLAN.md` §0.1).
    """
    room = _room(None)
    from kir.checker.classify import classify_room

    assert room.function is classify_room(room.name)
    assert room.function_source == "declared"


# ------------------------------------------------------ REFUSAL

def test_an_unknown_function_is_refused_by_name_with_the_whole_vocabulary():
    """An invalid value is a `KIR-T001` refusal, and it PRINTS the whole
    dictionary.

    This cost not a single new line in the validator: the `enum` kind
    already existed in the registry, and its refusal already knows how
    to name the allowed values by itself.
    """
    diags: list = []
    validate({"op": "create_room", "id": "r0", "xy": [0, 0],
              "level": {"by": "ref", "value": "L1"},
              "name": "X", "function": "кладовка"},
             "create_room", 0, "r0", diags)
    assert [d.code for d in diags] == ["KIR-T001"], diags
    text = diags[0].message_ru
    assert "function" in text
    assert "жилая" in text and "санузел" in text


def test_a_valid_function_is_accepted_without_a_word():
    diags: list = []
    validate({"op": "create_room", "id": "r0", "xy": [0, 0],
              "level": {"by": "ref", "value": "L1"},
              "name": "X", "function": "санузел"},
             "create_room", 0, "r0", diags)
    assert diags == []
