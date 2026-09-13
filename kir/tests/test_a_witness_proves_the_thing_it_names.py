"""FOUR WITNESSES WERE PROVING SOMETHING OTHER THAN WHAT THEY PROMISED
(04.09.2026).

The common shape of all four is our cardinal invariant, violated INSIDE THE
WITNESS ITSELF: an axis is signed that the witness did NOT READ. None of the
four was blind ENTIRELY — each turned red on a gross disturbance, and so
each survived unnoticed for exactly as long as nobody disturbed it IN THE
DIRECTION it was blind to.

    FC-19  the PATH signature lost ADJACENCY: `A-B-C-D` and `A-C-B-D` gave
           one signature (while shifting any point by 1 mm did change it);
    FC-07  a witness with the verdict IN A COMMENT was counted as existing,
           and the certificate was discharging the obligation BY KEY,
           citing verbatim "a witness cannot exist without `__post.Add`";
    FC-10  the ceiling witness lost openings ON THE `outline` BRANCH
           (it did account for them on the `region` branch), that is, it
           expected one ring for a ceiling it had itself built with two;
    FC-12  the registry promised ONE element, while `Railing.Create(host)`
           returns A COLLECTION, and the flight's second railing landed in
           NOT ONE cross-check.

EVERY EXPERIMENT HERE CAN TURN RED, AND THIS IS MEASURED ON A FROZEN COPY
`git archive HEAD` (49d81e5, PYTHONPATH=copy): **19 red summary lines** —
FC-19 two experiments and three subtests, FC-07 two and four, FC-10 one and
two, FC-12 five experiments; on the fixed tree, 0 red (22 experiments, 10
subtests).

🔴 TWELVE EXPERIMENTS ARE GREEN ON BOTH TREES, AND THIS IS NOT A WEAKNESS BUT
A CONDITION. These are controls: they ask about the INPUT, not the output of
the subject under test (the pair of paths really is indistinguishable under
the old law), or they guard OLD properties the fix had no right to remove (a
1 mm shift is visible, the path's end is watched, a ceiling with no openings
expects exactly one ring). A control read through the subject under test, on
broken code, says "the input is degenerate" instead of "the law is broken" —
the lesson is recorded in `test_sketch_loops_witness`.
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"),
)

from kir import spec  # noqa: E402
from kir.address import (  # noqa: E402
    created_identity_fields, element_addresses, receipt_map,
)
from kir.authoring import canon_unit, loops_payload_expected  # noqa: E402
from kir.compiler import compile_program  # noqa: E402
from kir.emit_model import EmitModelError, WitnessCheck, tolerance  # noqa: E402
from kir.registry_base import IdentityCardinality  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402

#: The one pair that catches FC-19. Its edge-endpoint multisets MATCH (this
#: is asserted below by a separate control, read from the INPUT), while the
#: paths differ. All previous path controls moved a vertex, and the
#: multiset moved right along with it; nobody had tried permuting the
#: vertices.
PATH_ABCD = [[0, 0], [3000, 9000], [8000, 0], [12000, 5000]]
PATH_ACBD = [[0, 0], [8000, 0], [3000, 9000], [12000, 5000]]

CEILING_OUTLINE = [[0, 0], [6000, 0], [6000, 6000], [0, 6000]]
CEILING_HOLE = [[2000, 2000], [4000, 2000], [4000, 4000], [2000, 4000]]
CEILING_HOLE_2 = [[4500, 500], [5500, 500], [5500, 1500], [4500, 1500]]

_SIG_RX = r'__slf_\w+ != "([^"]*)"'
_EXPECTED_N_RX = r"sketch loops mismatch, expected (\d+) loop"


def _compile(op, ver="2026"):
    out = compile_program({"ir_version": "1.0", "ops": [op]},
                          revit_version=ver, snapshot=GROUND_SNAPSHOT)
    assert out.ok, [d.message_ru for d in (out.diagnostics or [])][:1]
    return out.csharp


def _railing_cs(path):
    return _compile({"op": "create_railing", "id": "R1", "variety": "path",
                     "path": path,
                     "level": {"by": "name", "value": "Этаж 1"}})


def _railing_sig(path):
    return re.search(_SIG_RX, _railing_cs(path)).group(1)


def _ceiling_cs(outline, holes=None):
    op = {"op": "create_ceiling", "id": "C1", "outline": outline,
          "level": {"by": "name", "value": "Этаж 1"},
          "type": {"by": "name", "value": "Потолок подвесной 600x600"}}
    if holes:
        op["holes"] = holes
    return _compile(op)


class FC19_ThePathSignatureCarriesADJACENCY(unittest.TestCase):
    """A PATH IS AN ORDER, AND THE SIGNATURE MUST CARRY IT.

    The multiset of endpoints of all edges dumped into ONE ring is
    indifferent to any permutation of the interior vertices BY
    CONSTRUCTION: for `A-B-C-D` it is {A,B,B,C,C,D}, for `A-C-B-D` —
    {A,C,C,B,B,D}, and that is the same multiset. No sorting will tell them
    apart.
    """

    def test_the_control_says_the_OLD_law_could_not_tell_these_two_apart(self):
        """THE CONTROL IS COMPUTED FROM THE INPUT, NOT FROM THE OUTPUT OF THE
        SUBJECT UNDER TEST.

        Without this, the experiment below would only prove "two different
        polylines give different signatures" — a claim also true for a
        BROKEN witness on almost any pair. Here it is shown DIRECTLY that
        the old law (a shared bag of endpoints) had to coincide on this
        pair, meaning the pair genuinely discriminates.
        """
        g = float(getattr(tolerance("create_railing", "path_mm"), "value", 1.0))

        def old_law(path):
            pts = []
            for a, b in zip(path, path[1:]):
                pts.append((canon_unit(a[0], g), canon_unit(a[1], g)))
                pts.append((canon_unit(b[0], g), canon_unit(b[1], g)))
            return "|".join("%d,%d" % p for p in sorted(pts))

        self.assertEqual(
            old_law(PATH_ABCD), old_law(PATH_ACBD),
            "пара выродилась: прежний закон её РАЗЛИЧАЛ, и опыт ниже прошёл "
            "бы и на сломанном свидетеле")
        self.assertNotEqual(PATH_ABCD, PATH_ACBD)

    def test_two_paths_on_the_same_vertices_get_two_signatures(self):
        """FC-19 ITSELF. On the old code both signatures were

            0,0|3000,9000|3000,9000|8000,0|8000,0|12000,5000

        and both programs compiled with `ok=True` at zero diagnostics. The
        cost is the same as the 24.08 fix, but from the other side: the
        signature MATCHED for two DIFFERENT paths, meaning a railing built
        against the author's intent was signed off as green.
        """
        self.assertNotEqual(
            _railing_sig(PATH_ABCD), _railing_sig(PATH_ACBD),
            "перестановка внутренних вершин пути обязана менять подпись")

    def test_the_signature_still_moves_when_ONE_point_moves(self):
        """THE OLD PROPERTY IS NOT LOST. The witness was not blind
        altogether, and must not become blinder: shifting one point by 1 mm
        changes the signature.
        """
        moved = [list(p) for p in PATH_ABCD]
        moved[1] = [moved[1][0] + 1, moved[1][1]]
        self.assertNotEqual(_railing_sig(PATH_ABCD), _railing_sig(moved))

    def test_the_LAST_vertex_is_still_watched(self):
        """And a second old property: the path's end is watched (both ends
        of each curve are still taken, they simply lie within THEIR OWN
        edge).
        """
        pa = [[0, 0], [4000, 0], [4000, 2500]]
        pb = [[0, 0], [4000, 0], [4000, 2400]]
        self.assertNotEqual(_railing_sig(pa), _railing_sig(pb))

    def test_python_and_csharp_read_ONE_law_edge_by_edge(self):
        """BOTH HALVES ARE COMPUTED BY ONE HELPER, THERE IS NO SECOND
        CANONICALIZER.

        The Python side must be LITERALLY `loops_payload_expected` over the
        list of edges — the same one that computes the sketch's signature;
        the C# side must place EVERY curve into ITS OWN ring, otherwise the
        edges merge back into a bag. This exact seam (a ring fix that never
        reached the path) cost the 24.08 defect, and holding it must be a
        NUMERICAL experiment, not memory.
        """
        g = tolerance("create_railing", "path_mm")
        for path in (PATH_ABCD, PATH_ACBD, [[0, 0], [8000, 0], [12000, 0]],
                     [[0, 900], [0, 12000]]):
            with self.subTest(path=path):
                edges = [[(a[0], a[1]), (b[0], b[1])]
                         for a, b in zip(path, path[1:])]
                self.assertEqual(_railing_sig(path),
                                 loops_payload_expected(edges, g))
                # The order of endpoints WITHIN an edge is numeric (like
                # __KirCanonCmp), not lexicographic: "12000" < "8000" as a
                # string, but > as a number.
                for ring in _railing_sig(path).split(";"):
                    pairs = [tuple(int(n) for n in v.split(","))
                             for v in ring.split("|")]
                    self.assertEqual(pairs, sorted(pairs), ring)
                # The order OF EDGES relative to each other is string-based
                # (like StringComparer.Ordinal in `__slr.Sort`).
                rings = _railing_sig(path).split(";")
                self.assertEqual(rings, sorted(rings), _railing_sig(path))

    def test_the_emitted_csharp_builds_one_ring_PER_CURVE(self):
        """THE C# HALF IS PINNED SEPARATELY FROM THE PYTHON ONE.

        The signature equality above checks Python against Python. If C#
        assembles ONE ring for the whole path again, the two sides drift
        apart silently — exactly how the 24.08 defect lived. So here the
        generated text itself is read: `__slL_.Add(...)` must sit INSIDE the
        curve traversal.
        """
        cs = _railing_cs(PATH_ABCD)
        body = cs[cs.index("var __slP_R1 = __el_R1.GetPath();"):]
        body = body[:body.index("if (__slL_R1 != null)")]
        self.assertIn("foreach (Curve __slx_R1 in __slP_R1)", body)
        loop_at = body.index("foreach (Curve __slx_R1 in __slP_R1)")
        self.assertGreater(
            body.index("__slL_R1.Add(__slo_R1);"), loop_at,
            "кольцо добавляется ВНЕ обхода кривых — все рёбра снова в одном "
            "мешке, и порядок пути опять не доказывается")
        self.assertGreater(
            body.index("var __slo_R1 = new List<Curve>();"), loop_at,
            "список кольца объявлен ДО обхода — значит он один на весь путь")


class FC07_AVerdictInACommentIsNotAVerdict(unittest.TestCase):
    """"A WITNESS CANNOT EXIST WITHOUT `__post.Add`" MUST BE TRUE.

    On this assertion — verbatim, `translation_cert.certify_op`: "A
    WitnessCheck cannot exist without its __post.Add (unconstructible), so
    key-presence IS verdict-presence" — rests the certificate's ENTIRE model
    path: it gave up parsing the text and discharges the obligation BY KEY.
    """

    #: Exactly what this was measured with: a token inside a line comment.
    COMMENTED = '        // __post.Add("нет вердикта");\n'

    def test_a_real_verdict_still_constructs(self):
        check = WitnessCheck(
            obligation_key="k", reader_cs="    var __x = 1;\n",
            verdict_cs='    if (__x != 1) __post.Add("m");\n', message="m")
        self.assertEqual(check.obligation_key, "k")

    def test_the_measured_commented_verdict_is_refused(self):
        with self.assertRaises(EmitModelError) as caught:
            WitnessCheck(obligation_key="anchor", reader_cs="",
                         verdict_cs=self.COMMENTED, message="m", style="guard")
        self.assertIn("__post.Add", str(caught.exception))

    def test_every_form_of_non_code_is_refused(self):
        for verdict, what in (
            (self.COMMENTED, "строчный комментарий"),
            ('    /* __post.Add("нет"); */\n', "блочный комментарий"),
            ('    __log.Add("__post.Add(x)");\n', "строковый литерал"),
            ('    __log.Add(@"__post.Add(x)");\n', "verbatim-литерал"),
        ):
            with self.subTest(what=what):
                with self.assertRaises(EmitModelError):
                    WitnessCheck(obligation_key="k", reader_cs="",
                                 verdict_cs=verdict, message="m")

    def test_a_comment_NEXT_TO_a_real_verdict_does_not_refuse(self):
        """A CONTROL IN THE OTHER DIRECTION: the law forbids a
        verdict-in-a-comment, not a comment next to a verdict. Without this
        experiment the fix could refuse everything indiscriminately and
        look just as green.
        """
        check = WitnessCheck(
            obligation_key="k", reader_cs="",
            verdict_cs=('    // тут был __post.Add по старому имени\n'
                        '    if (__x) __post.Add("m");\n'),
            message="m")
        self.assertEqual(check.obligation_key, "k")

    def test_the_vacuity_analyser_never_narrowed_this_hole(self):
        """THE HOLE WAS NOT NARROWER THAN IT LOOKED, AND THIS IS A
        MEASUREMENT, NOT AN ARGUMENT.

        Next to it lives the notion `dead_keys` ("present but VACUOUS"), and
        it's natural to assume the commented-out verdict is caught BY IT. It
        is not: `analyze_witness_cs` answers the question "can I PROVE that
        THIS `__post.Add` is dead," and in stripped code there is NOT A
        SINGLE such witness site — `witness_site_census` gives (0, 0), zero
        finds, the key never lands in `dead_keys`, and the clause discharges.
        The instrument was right — about A DIFFERENT subject: it guards a
        verdict under impossible protection, not its absence. That's why it
        was the constructor that had to be closed instead.
        """
        from kir.translation_cert import (
            _code, analyze_witness_cs, witness_site_census,
        )
        stripped = _code(self.COMMENTED)
        self.assertNotIn("__post.Add", stripped)
        self.assertEqual(witness_site_census(stripped), (0, 0))
        self.assertEqual(analyze_witness_cs(stripped), ((), False))

    def test_the_law_has_exactly_one_carrier(self):
        """NO SECOND STRIPPER WAS SET UP. The constructor must query the
        same `translation_cert._code` the certificate uses to find its own
        markers: two state machines over one dialect will drift apart at
        the first edit, and that is a named defect of the house.
        """
        import inspect
        from kir import emit_model
        source = inspect.getsource(emit_model._verdict_code)
        self.assertIn("from kir.translation_cert import _code", source)


class FC10_TheCeilingWitnessCountsEVERYRing(unittest.TestCase):
    """THE WITNESS MUST EXPECT EXACTLY WHAT THE EMITTER BUILT.

    Both quantities are computed in ONE function from ONE input, so the
    experiment brings them together AS A NUMBER: rings in the signature
    against `__loops_.Add(` in the creation block. Such an equality can fail
    in BOTH directions — when the witness forgot a ring (FC-10), and when it
    invented an extra one.
    """

    @staticmethod
    def _rings_and_loops(outline, holes=None):
        cs = _ceiling_cs(outline, holes)
        sig = re.search(_SIG_RX, cs).group(1)
        promised = int(re.search(_EXPECTED_N_RX, cs).group(1))
        return sig.split(";"), promised, cs.count("__loops_C1.Add(")

    def test_a_ceiling_WITHOUT_holes_witnesses_exactly_one_ring(self):
        """A CONTROL IN THE OTHER DIRECTION: the equality is not bought by
        "there are always many rings." Without openings there must be
        exactly one ring.
        """
        rings, promised, built = self._rings_and_loops(CEILING_OUTLINE)
        self.assertEqual((len(rings), promised, built), (1, 1, 1))

    def test_the_outline_branch_witnesses_its_holes(self):
        """FC-10 ITSELF. On the old code: 2 rings were built, 1 was
        promised, the signature had 1 — a ceiling with an opening was built
        CORRECTLY, and the witness rolled the whole program back (`expected
        1 loop(s)`) and told the author the wrong error. The `region`
        branch had always accounted for the same openings.
        """
        for holes in ([CEILING_HOLE], [CEILING_HOLE, CEILING_HOLE_2]):
            with self.subTest(holes=len(holes)):
                rings, promised, built = self._rings_and_loops(
                    CEILING_OUTLINE, holes)
                self.assertEqual(built, 1 + len(holes))
                self.assertEqual(len(rings), built,
                                 "свидетель ждёт не столько колец, сколько "
                                 "эмиттер построил")
                self.assertEqual(promised, built)

    def test_the_hole_vertices_are_actually_in_the_signature(self):
        """The ring count would match even for an empty ring. Here the
        opening's VERTICES are asked for — otherwise "a ring exists" doesn't
        mean "the right one."
        """
        rings, _promised, _built = self._rings_and_loops(
            CEILING_OUTLINE, [CEILING_HOLE])
        g = spec.OPS["create_ceiling"].tolerances["sketch_mm"]
        wanted = "|".join(
            "%d,%d" % pair
            for pair in sorted((canon_unit(p[0], g), canon_unit(p[1], g))
                               for p in CEILING_HOLE))
        self.assertIn(wanted, rings)

    def test_both_input_shapes_obey_the_same_law(self):
        """ONE LAW FOR BOTH INPUT BRANCHES. The divergence between the
        `outline` and `region` branches WAS the defect: one accounted for
        openings, the other did not.
        """
        contour = {"outer": {"shape": "rect", "origin": [0, 0],
                             "size_mm": [6000, 6000]},
                   "holes": [{"shape": "rect", "origin": [2000, 2000],
                              "size_mm": [2000, 2000]}]}
        cs = _compile({"op": "create_ceiling", "id": "C1", "contour": contour,
                       "level": {"by": "name", "value": "Этаж 1"},
                       "type": {"by": "name",
                                "value": "Потолок подвесной 600x600"}})
        rings = re.search(_SIG_RX, cs).group(1).split(";")
        self.assertEqual(len(rings), cs.count("__loops_C1.Add("))
        self.assertEqual(len(rings), 2)


class FC12_TheRailingResultIsAsPluralAsTheAPI(unittest.TestCase):
    """THE REGISTRY PROMISED ONE ELEMENT, WHILE THE API RETURNS A
    COLLECTION.

    `Railing.Create(doc, hostId, typeId, position)` -> `ICollection<ElementId>`
    (measured by assignment to the declared type, 6/6), and the collection's
    meaning is physical: a flight gets a railing on BOTH sides at once.
    Acceptance KNEW this (`_expected_count` -> `AT_LEAST`), the registry did
    not.
    """

    def test_the_registry_declares_the_plural(self):
        result = spec.OPS["create_railing"].result
        self.assertIs(result.identity_cardinality, IdentityCardinality.MANY)
        self.assertEqual(result.identity_field, "railing_ids")
        # Referenceability is removed NOT out of taste: ResultSpec forbids it
        # for a plural result, and the handle now refuses with a NAMED
        # reason instead of silently binding to the first of the two.
        self.assertFalse(result.referenceable)

    def test_the_acceptance_table_already_knew_the_count_was_not_one(self):
        """THE MEASUREMENT THAT PICKED EXACTLY THIS ONE OF TWO LEGAL
        OUTCOMES.

        The second outcome — "the extras honestly refuse" — would have
        refused the ENTIRE population of the host branch (on K2 that's
        `OST_StairsRailing` 203 out of 203) and made this acceptance branch
        dead. The decision was made by the number, not by taste, and the
        number lives here.
        """
        from kir.acceptance import Certainty, _plural_count
        count, certainty, why = _plural_count(
            {"op": "create_railing", "id": "R1", "variety": "hosted"})
        self.assertEqual((count, certainty), (1, Certainty.AT_LEAST))
        self.assertIn("КОЛЛЕКЦИЮ", why)

    def test_the_identity_field_reaches_the_readers_that_ask_the_registry(self):
        """A FIELD THE REGISTRY NEVER DECLARED IS READ BY NO ONE.

        The old name was `created_ids` — exactly the GUESSED name that
        `test_address_bridge` holds an experiment for: "no op declares it."
        The list of created elements sat in the receipt and never reached
        either `element_addresses` or the registry of what was created.
        """
        from kir.created_ledger import created_keys
        self.assertIn("railing_ids", created_identity_fields())
        self.assertIn("railing_ids", created_keys())
        self.assertNotIn("created_ids", created_identity_fields())

    def test_BOTH_created_railings_get_an_address(self):
        """FC-12 ITSELF, AND THIS IS THE NUMBER: it was 1 address out of 2, now it's 2 out of 2."""
        ops = [{"op": "create_railing", "id": "R1", "variety": "hosted",
                "host": {"by": "element_id", "value": 777},
                "position": "treads"}]
        payload = {"R1": {"id": "101", "railing_ids": ["101", "102"],
                          "created_count": 2}}
        got = element_addresses(ops, payload)
        self.assertEqual([a.value for a in got["R1"]], ["101", "102"])
        self.assertEqual(receipt_map(ops, payload), {"R1": ["101", "102"]})

    def test_the_old_row_shape_can_still_FAIL(self):
        """FAIL CONTROL: the contract can turn red.

        A receipt in the OLD shape (only `id`, without the declared field)
        must read as an absence of identity, otherwise "addresses were
        found" proves nothing.
        """
        from kir.address import IdentityMissingError
        result = spec.OPS["create_railing"].result
        self.assertFalse(result.identity_present({"id": "101"}))
        self.assertFalse(result.identity_present({"railing_ids": []}))
        self.assertTrue(result.identity_present({"railing_ids": ["101"]}))
        ops = [{"op": "create_railing", "id": "R1", "variety": "hosted",
                "host": {"by": "element_id", "value": 777},
                "position": "treads"}]
        with self.assertRaises(IdentityMissingError):
            element_addresses(ops, {"R1": {"id": "101"}})

    def test_both_varieties_emit_the_declared_field(self):
        """BOTH BRANCHES, NOT JUST THE ONE THE FIX WAS FOR. A free-standing
        railing gets a list of exactly one id — and this is NOT a
        formality: the MANY contract has no `id` field at all, and without
        the receipt's row a path railing would lose its identity entirely.
        """
        path_cs = _railing_cs([[0, 0], [4000, 0]])
        self.assertIn('__rb["railing_ids"] = new string[] { '
                      '__el_R1.Id.ToString() };', path_cs)
        hosted_cs = _compile({"op": "create_railing", "id": "R1",
                              "variety": "hosted",
                              "host": {"by": "element_id", "value": 777},
                              "position": "treads"})
        self.assertIn('__rb["railing_ids"] = __ids_R1.Select('
                      '__i => __i.ToString()).ToArray();', hosted_cs)
        self.assertNotIn("created_ids", hosted_cs)


if __name__ == "__main__":
    unittest.main()
