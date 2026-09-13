"""A SLOPE-READING REFUSAL IS NOT COVERED UP BY A FALLBACK THAT IS BLIND TO
SLOPES (RV-20).

THE MEASUREMENT THIS FILE WAS BOUGHT WITH (04.09.2026). Exactly ONE path of
the emitted C# knows how to read roof slopes — `__FootPrintRoofLoops`;
`__DependentSketchLoops` does not carry them at all, and this is visible in
the code: only the first one populates the `slopes` key. The `__ProfileRow`
dispatcher went like this:

    __profile = __FootPrintRoofLoops(roof);          // handles slopes
    if (!ok) __profile = __DependentSketchLoops(…);  // carries no slopes
    if (ok)  { profile_available = true; slopes = …; reason = null; }

That is, for ANY reason the main path refused, control moved to the
fallback, and if the fallback succeeded, the line came out
`profile_available=true`, `slopes=null`, `reason=null`. Such a line is
BYTE-FOR-BYTE equal to the line for an honest flat roof (proven by F-075).
A sloped roof was being reassembled as a flat one, and NOT ONE line said
so.

The distinguishing signal sat in the same code: the main path's
`__profile["reason"]` carries the reason verbatim («roof slope read
failed: …», «roof profile contains null ModelCurve», «FootPrintRoof
.GetProfiles failed: …»). The fallback's success was erasing it.

THE REMEDY IS NOT NEW, IT WAS ALREADY DECLARED BY THIS SAME FILE. Twenty
lines above, F-076 treats a partial slope set fail-closed: "the contour is
declared UNAVAILABLE with a named reason, and the roof stays an honest
atom; a partial set is silently indistinguishable from a full one, while an
atom with a reason is always distinguishable". The fallback path was
bypassing this remedy, staying outside it.

🔴 WHAT THIS FILE IS NOT, AND THIS IS NAMED, NOT HIDDEN. The emitted body
executes ONLY in Revit: there is no live `get_SlopeAngle` failure here, and
there cannot be — bare KIR has no host port (the same argument is recorded
verbatim in `test_a_swallowed_read_failure_has_no_carrier`). What is
checked is the TEXT of the emission, and it is checked STRUCTURALLY: not a
literal, but the order of moves inside the `__ProfileRow` body — where the
exit sits and what it carries away with it. An instrument like this will
let through a rewrite of the form that preserves the behavior; a rewrite of
the behavior that preserves the form will get through none of the three
questions.

THE SECOND HALF, WHICH RUNS LIVE: the line that C# now emits is parsed by
this same module's Python, and here it is checked BY EXECUTION — a refusal
must reach `ProfileFailure` with its own reason, rather than turning into
an empty profile with no explanation.
"""
from __future__ import annotations

import unittest

from kir.decompile.sketch_extract import (
    SKETCH_EXTRACT_SCHEMA_VERSION,
    build_sketch_extract_cs,
    extract_sketch_profiles,
)


def mask_comments_and_strings(cs: str) -> str:
    """Text of the SAME LENGTH, with comments and literals replaced by
    spaces.

    Its own copy, not borrowed from a neighbor: an instrument whose
    denominator depends on someone else's test file turns red from someone
    else's edit and stays silent about its own subject. The length is
    preserved, so offsets remain offsets into the original text.
    """
    out = list(cs)
    index = 0
    length = len(cs)
    while index < length:
        pair = cs[index:index + 2]
        if pair == "//":
            while index < length and cs[index] != "\n":
                out[index] = " "
                index += 1
        elif pair == "/*":
            while index < length and cs[index:index + 2] != "*/":
                if cs[index] != "\n":
                    out[index] = " "
                index += 1
            for _ in range(2):
                if index < length:
                    out[index] = " "
                    index += 1
        elif cs[index] == '"':
            out[index] = " "
            index += 1
            while index < length and cs[index] != '"':
                if cs[index] == "\\":
                    out[index] = " "
                    index += 1
                    if index < length:
                        out[index] = " "
                        index += 1
                    continue
                if cs[index] != "\n":
                    out[index] = " "
                index += 1
            if index < length:
                out[index] = " "
                index += 1
        else:
            index += 1
    return "".join(out)


def profile_row_body(cs: str) -> tuple[str, str]:
    """The body of the `__ProfileRow` lambda by BRACKET MATCHING: masked and raw.

    Both are sliced by the SAME offsets, and this is legitimate precisely
    because the mask preserves length: a bracket found in the masked text
    sits at the same place in the raw one. The masked text answers questions
    about STRUCTURE (inside a literal there are no brackets or words for
    us), the raw text answers questions about NAMES.
    """
    masked = mask_comments_and_strings(cs)
    anchor = masked.index("__ProfileRow")
    start = masked.index("{", masked.index("=>", anchor))
    depth = 0
    for index in range(start, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return masked[start:index + 1], cs[start:index + 1]
    raise AssertionError("тело __ProfileRow не закрылось")


class ЗапаснойПутьНеВыдаётСебяЗаСкатный(unittest.TestCase):
    """The CAPABILITY axis: what the dispatcher must now do with a refusal."""

    def setUp(self) -> None:
        self.body, self.raw = profile_row_body(build_sketch_extract_cs(["1"]))
        self.primary = self.body.index("__FootPrintRoofLoops(")
        self.fallback = self.body.index("__DependentSketchLoops(", self.primary)
        self.between = self.body[self.primary:self.fallback]
        self.between_raw = self.raw[self.primary:self.fallback]

    def test_a_failed_pitch_read_LEAVES_the_row_before_any_fallback(self):
        """Between the slope reading and the blind fallback there must be an exit."""
        self.assertIn(
            "return __row;", self.between,
            "после отказа скатного пути управление доходит до "
            "__DependentSketchLoops — кровля снова пересоберётся плоской")

    def test_that_exit_is_taken_ON_FAILURE_and_not_unconditionally(self):
        """The exit must stand under the NEGATION of the flag, or it will
        kill valid cases too.

        The raw text is what gets asked: the key name `"ok"` lives inside a
        literal, and the mask blanks out literals — an instrument that
        asked the masked text about them would turn red on correct code
        (bought by the very first run).
        """
        guard = self.between_raw[:self.between_raw.index("return __row;")]
        self.assertIn('!((bool)__profile["ok"])', guard,
                      "выход из строки стоит не под отказом основного пути")

    def test_the_row_leaves_carrying_the_PRIMARY_reason(self):
        """It carries off the reason from the MAIN path, not a generic
        stub string.

        Without this line the atom would be honest and MUTE: the reader
        would learn that there is no contour, and would not learn that the
        roof's SLOPE failed to be read.
        """
        guard = self.between_raw[:self.between_raw.index("return __row;")]
        self.assertIn('__row["reason"]', guard)
        self.assertIn('__profile["reason"]', guard,
                      "причина обязана браться у отказавшего пути")

    def test_the_row_that_leaves_is_NOT_available(self):
        """Before the exit, `profile_available` never once became `true`.

        Otherwise the roof would have shipped as "available without a
        contour" — a shape that decompile rejects, meaning the refusal
        would have become a stage failure.
        """
        head = self.raw[:self.primary]
        self.assertIn('__row["profile_available"] = false;', head)
        self.assertNotIn('__row["profile_available"] = true;', head)


class ЧестныеПутиНеПострадали(unittest.TestCase):
    """The CONTROL without which the previous class proves nothing.

    An exit that always fires "fixes" things that were never broken. Here
    it is checked that both fallback paths stay ALIVE for the cases they
    were meant for: non-`FootPrintRoof` (floor, ceiling) and `ExtrusionRoof`.
    """

    def setUp(self) -> None:
        _masked, self.body = profile_row_body(build_sketch_extract_cs(["1"]))

    def test_the_dependent_sketch_path_is_still_reachable(self):
        self.assertIn("__profile = __DependentSketchLoops(__element);",
                      self.body)

    def test_the_extrusion_roof_path_is_still_reachable(self):
        self.assertIn("__ExtrusionRoofLoops(__extrusion)", self.body)

    def test_the_pitch_still_reaches_the_row_when_the_read_SUCCEEDS(self):
        self.assertIn('__row["slopes"] = __profile.ContainsKey("slopes")',
                      build_sketch_extract_cs(["1"]))


class ОтказДоезжаетДоЧитателя(unittest.TestCase):
    """The DELIVERY axis, and it is executed, not merely read: the string
    that C# now emits must become a NAMED refusal, not an empty profile."""

    def _payload(self, row: dict) -> dict:
        return {"schema_version": SKETCH_EXTRACT_SCHEMA_VERSION,
                "elements": [row], "failures": []}

    def test_the_refused_roof_is_an_atom_WITH_its_reason(self):
        reason = ("roof pitch path refused and no slope-blind fallback may "
                  "stand in for it: roof slope read failed: "
                  "InvalidOperationException")
        result = extract_sketch_profiles(self._payload({
            "element_id": "77", "category": "OST_Roofs",
            "profile_available": False, "loops": [], "slopes": None,
            "reason": reason, "stairs_run_paths": []}))
        self.assertEqual(len(result.records), 1)
        self.assertFalse(result.records[0].profile_available)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].element_id, "77")
        self.assertIn("slope", result.failures[0].reason)

    def test_the_shape_the_old_dispatcher_produced_is_still_REFUSED_loudly(self):
        """FAIL control in reverse: the string "available AND with a reason"
        is impossible.

        It is precisely this string that would have to say "the contour
        exists but the slope was not read," and decompile does not accept
        it — so the remedy is a refusal, not a half-available string.
        """
        from kir.decompile.sketch_extract import SketchPayloadError

        with self.assertRaises(SketchPayloadError):
            extract_sketch_profiles(self._payload({
                "element_id": "77", "category": "OST_Roofs",
                "profile_available": True,
                "loops": [{"points_mm": [[0, 0], [1000, 0], [1000, 1000]],
                           "curve_kinds": ["line", "line", "line"],
                           "arc_midpoints_mm": [None, None, None]}],
                "slopes": None, "reason": "roof slope read failed",
                "stairs_run_paths": []}))


if __name__ == "__main__":
    unittest.main()
