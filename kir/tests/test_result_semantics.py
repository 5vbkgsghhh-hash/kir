"""Typed result/effect registry and forward-reference regressions."""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"),
)

from kir import spec  # noqa: E402
from kir.compiler import compile_program  # noqa: E402
from kir.registry_base import (  # noqa: E402
    EffectKind,
    IdentityCardinality,
    ReferenceKind,
    ResultSpec,
)
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


class RegistryResultSemantics(unittest.TestCase):
    def test_every_op_has_a_closed_effect_and_result_contract(self):
        # 39 -> 41: wave/room (create_room_separator) and wave/opening in one
        # evening on 08-03. The number is a GUARD, not a fact: an op added
        # silently must fail this line and force the author to walk through
        # the whole list of contracts below.
        # 41 -> 42: wave/wall-foundation (create_wall_foundation, 08-09). The
        # guard fired, the list was walked: CREATE/RESULT_ELEMENT, writing,
        # a single entity with an id, a referenceable result.
        # 42 -> 47 (08-09): the electrical/flex/placeholder wave —
        # create_conduit, create_pipe_placeholder, create_duct_placeholder,
        # create_flex_duct, create_flex_pipe. THE NUMBER WAS RE-TAKEN AS
        # `len(spec.OPS)` ON THE MERGED TREE: both waves ran from 41, and
        # "46" from the electrical branch would have meant a silently lost
        # wall foundation.
        # 47 -> 48 (08-09): create_angular_dimension. The guard fired, and
        # the list was walked — RESULT_ELEMENT, EffectKind.CREATE,
        # writes_model=True, plus its own rows in acceptance
        # (OST_Dimensions), reverse_contract (CAPTURE_GAP: an arc annotation
        # has not a single entry in L0) and translation_cert (four
        # obligations, of which `value` is geometry).
        # 48 -> 52 (08-09): the loads and egress-path wave — create_point_load,
        # create_line_load, create_area_load, create_path_of_travel. The
        # guard fired, the list was walked for all four:
        # CREATE/RESULT_ELEMENT, writes_model=True, a single entity with an
        # id, a referenceable result; plus their own rows in
        # reverse_contract (all four are CAPTURE_GAP — L0 reads neither
        # loads nor egress-path lines at all) and in translation_cert.
        # 52 -> 54 (08-09): the framing wave — create_beam_system and
        # create_truss. The same list was walked for both:
        # CREATE/RESULT_ELEMENT, writes_model=True, a single referenceable
        # entity with an id; plus their own rows in acceptance (both blind
        # to the count of what they spawn — LayoutRule chooses the layout,
        # the truss family chooses the members), reverse_contract (both
        # CAPTURE_GAP: L0 carries the spawned beams and members but not the
        # system and truss that spawned them) and translation_cert (five and
        # six obligations respectively).
        # THE NUMBER WAS RE-TAKEN AS `len(spec.OPS)` AFTER THE MERGE: the
        # waves counted from 48 separately (52 and 50), and taking either
        # figure as-is would have LOWERED the ratchet exactly enough for the
        # loss of the other wave's ops to pass green.
        # 54 -> 57 (08-09): the site wave — create_topography,
        # create_building_pad, create_site_subregion. The site family was
        # entirely empty: the building stood in a void.
        # THE NUMBER WAS RE-TAKEN AS `len(spec.OPS)` AFTER THE MERGE. Three
        # waves named 52, 50, and 44, and each was right on its own branch —
        # the registry grew from ONE base by three independent hands in one
        # day.
        # 57 -> 59 (08-09): the applied-profile wave — create_wall_sweep and
        # create_slab_edge. The family was entirely empty: the registry
        # census found not a single operation creating a WallSweep,
        # SlabEdge, Fascia, or Gutter — meaning cornices, string courses,
        # rustication, and drip edges were expressed by NOTHING.
        # THE NUMBER WAS RE-TAKEN AS `len(spec.OPS)` ON THIS TREE, not added
        # to 57: exactly the same discipline the three paragraphs above
        # demand, and exactly what would have saved the three earlier waves
        # from their collisions.
        # 48 -> 51 (08-09): the datum wave — create_multi_segment_grid,
        # create_extrusion_roof, create_multistory_stairs. THE NUMBER WAS
        # RE-TAKEN AS `len(spec.OPS)` ON THIS TREE, not added to the
        # previous one: a neighboring wave could have landed the same day,
        # and "50" from the branch would have drowned it silently. The list
        # was walked for all three: EffectKind.CREATE, writes_model=True, a
        # single entity with an id (for the grid chain and the stair the
        # result is NOT referenceable — nobody has reason to reference
        # them), plus their own rows in acceptance, reverse_contract, and
        # translation_cert.
        # 62 -> 64 (08-09): the solids wave — create_solid_extrusion and
        # create_solid_revolve. The list was walked for both: RESULT_ELEMENT,
        # EffectKind.CREATE, writes_model=True, grounded=() (a DirectShape
        # has no type — same as create_directshape), plus their own rows in
        # acceptance (the shared DirectShape branch), reverse_contract
        # (CAPTURE_GAP: the built B-rep does not store the profile and
        # height it was written with) and translation_cert (five obligations
        # each, of which volume and end-face area are analytical).
        #
        # THIS IS ALSO WHERE THE RATCHET THAT WAS RED BEFORE THIS MERGE GETS
        # FIXED, and it is fixed by the very rule the paragraphs above are
        # shouting about. On the base (`c98f4c72`), this spot held TWO
        # `assertEqual`s BACK TO BACK — 59 and 51, both brought in by the
        # merge as "purely additive" — against an actual 62 operations in
        # the tree. Python executes the first one, so the suite failed on
        # "59 != 62," and it failed on the WRONG thing: the message talked
        # about the op count, while the defect was that two branches each
        # wrote their own figure and the text merge kept both. Exactly the
        # same class as duplicate keys in a dict: merging text is not
        # merging meaning, and it stays silent the same way. The assertion
        # is now ONE, and the number is re-taken as `len(spec.OPS)` on the
        # RECONCILED tree, not added to either branch: the solids wave wrote
        # "50" against its own base of 48.
        # 64 -> 65 (08-09): the detailing wave — create_filled_region, ONE
        # op. The guard was walked in full: CREATE/RESULT_ELEMENT,
        # writes_model=True, a single referenceable entity with an id; plus
        # its own rows in acceptance (the sum over
        # OST_FilledRegion/OST_MaskingRegion — a masking region is the same
        # class, differing only by TYPE), clash_bundle (no body: 2D view
        # graphics), reverse_contract (CAPTURE_GAP — extraction reads
        # neither of the two categories) and translation_cert (four
        # obligations, of which boundary is real geometry, not an echo). ONE
        # MORE WAVE DELIBERATELY DID NOT HAPPEN: the spot-elevation tag is
        # REJECTED with a named reason (an empty marker draws nothing, and
        # its views require ReferenceKind.VIEW — a language change), the
        # reason is recorded in the header of ops_annotation.py.
        # THE SIXTH TIME IN ONE DAY: the wave wrote "58" against its own
        # base of 57. Re-taken as `len(spec.OPS)` on the RECONCILED tree.
        # 65 -> 66 (2026-08-10): the reinforcement wave — create_area_reinforcement,
        # and it has all four rows: acceptance (BLIND for a named reason —
        # Revit chooses the number of bars, and the census cell is not
        # measured), clash_bundle (the body is real, the program carries no
        # bounding extent), reverse_contract (CAPTURE_GAP — extraction does
        # not open OST_AreaRein) and translation_cert (five obligations, of
        # which `bars_laid` is CONDITIONAL, because an empty array with
        # HostStructuralRebar turned off is the correct answer per
        # Autodesk's documentation).
        # EIGHT CANDIDATES ARE REJECTED WITH A NAMED REASON, and each is
        # measured by compiling; the reasons are recorded in the header of
        # ops_struct.py.
        # Re-taken as `len(spec.OPS)` by running on THIS tree.
        # 65 -> 66 (2026-08-10): the massing wave — create_face_wall. ONE
        # MORE WAVE DELIBERATELY DID NOT HAPPEN: six mass-form factories are
        # REJECTED with a named reason (they live only on
        # `doc.FamilyCreate`, and it is documented as throwing in a project
        # document), the reason is recorded in the header of ops_mass.py.
        # 67 -> 68 (2026-08-10): sketch-based stair landing.
        # CREATE/RESULT_UNREFERENCED_ELEMENT, writing, a solo op; acceptance,
        # clash, reverse, and certificate contracts added.
        # 68 -> 69 (2026-08-11): `create_space` (commit `1095cb13`). WHAT IS
        # AT FAULT HERE IS NOT THE CODE BUT THE RECORD ABOUT IT — the op
        # arrived FULLY EQUIPPED, verified on tree `aecf6cff`: the row in
        # `OP_RESULT_CATEGORIES` is there, the reverse contract is there,
        # the row in the refinement table is there, and the acceptance judge
        # is NOT blind to it (it is absent from `_OPS_BLIND`). Exactly this
        # ratchet line fell behind, and it held the suite red for a day.
        # AT THE OTHER END, the same op had fallen out of the closed clash
        # category table (`clash_bundle`) — together with
        # `create_curtain_grid_line` — and this was noticed only on 08-11,
        # when a dead guard was revived (`fix/kir-op-category-authority`,
        # `e986d24d`). One op, two independent accounting gaps, and one of
        # the guards was dead at the time: a closed list is worth exactly as
        # much as the check that it is still closed.
        # 69 -> 70 (2026-08-15): `create_stairs_run` — a second flight of an
        # already-standing stair, a solo op (its own `StairsEditScope`, like
        # the landing). Equipped by the wave, not after the fact: the
        # reverse contract is there (CAPTURE_GAP), the clash rows are there
        # (`OP_NO_BODY` + `_BLIND_OPS`, reason — `OST_StairsRuns` outside
        # `hulls.KIND_TABLE`), the category arithmetic balanced (66 writing,
        # 11 blind). It has NOT A SINGLE live run, and this is recorded in
        # `UNPROVEN` with a reason — the 08-15 incident, when
        # `create_stairs` blocked Revit's UI thread with a modal window; the
        # 6/6 gate and the golden do NOT substitute for this.
        # 70 -> 71 (2026-08-18): `join_elements` — the FIRST RELATION-op in
        # the registry. It creates no element: it joins the geometry of two
        # already-standing ones (`JoinGeometryUtils.JoinGeometry`). A direct
        # request from the owner on 08-17 — "so that the fact of being
        # joined is not lost but preserved."
        #
        # Equipped by the wave, not after the fact, and every guard is
        # verified by running: the reverse contract is there (`CAPTURE_GAP`
        # with a due date, and NOT `state_transition` — the relation is
        # directly readable via `GetJoinedElements`, capture just does not
        # read it yet); the refinement row is there, and the certificate
        # gives `proven=True` across six versions with zero vacuous;
        # `acceptance._OPS_WITHOUT_ELEMENTS` is topped up, the arithmetic in
        # `spec.py` is recalculated (66 -> 67 writing, mechanism 4: 4 -> 5);
        # C# is compiled by a live compile service across 2021-2026, six out
        # of six.
        #
        # WHAT IT LACKS IS STATED HERE, NOT DISCOVERED LATER: it has NOT A
        # SINGLE live Revit run, and it also lacks the reading half
        # (`decompile/` does not call `GetJoinedElements` even once yet).
        #
        # 🔴 BOTH HALVES OF THIS PARAGRAPH WENT STALE, AND HERE IS WHAT
        # REPLACES THEM (measured 2026-08-22). The reading half appeared on
        # THE SAME DAY as the record above: `39ebd521` introduces
        # `GetJoinedElements` at 07:03, and "zero occurrences" was written
        # at 07:19 — sixteen minutes, one session. Today capture reads ALL
        # THREE kinds, the lifter is written (`lift.lift_joins`), the
        # contract mode is `COMPOSED`.
        #
        # Live runs exist, and the witness corpus (`kir_witness.jsonl`)
        # names them by run: 08-18 — ×10, ROLLBACK; 08-22 — ×24, ×24, ×2,
        # all three COMMIT. But `ok=False` for all four: **the full chain
        # (commit AND witness AND acceptance) never happened even once**,
        # acceptance did not reconcile. This is the op's exact state — not
        # "never built" and not "proven," but a third thing.
        #
        # 🔴 AND WHAT WAS LIFTED NEVER REACHES THE PROGRAM: `orchestrator.decompile`
        # does not accept `join_index` at all, and
        # `lift_cache.serialize_lift_result` is assembled field by field by
        # hand and WILL SILENTLY DROP a new field. Both seams are named in
        # `_ENTRYPOINTS_NAMED_IN_ADVANCE`.
        # ══════════════════════════════════════════════════════════════════
        # 71 -> 78 (2026-08-21). THE NUMBER WAS CHANGED NOT BECAUSE THE TEST
        # WAS RED, BUT BECAUSE THE DIFFERENCE RECONCILED BY NAME. The
        # increment is EXACTLY SEVEN ops from two waves, and each one is
        # dated by `git log -S` against the registries, not recalled from
        # memory:
        #
        #     08-20  create_adaptive_component      11b6f87f
        #     08-20  create_solid_blend             11b6f87f
        #     08-20  create_surface                 11b6f87f
        #     08-20  create_solid_boolean           6961bb94
        #     08-20  create_solid_sweep             0d3aa772
        #     08-20  query_surface                  5b03cebe
        #     08-21  author_family                  ea65f9fd
        #
        # 71 + 7 = 78, no remainder. Had there been a remainder, an op that
        # entered the registry unnoticed would be sitting under the ratchet
        # — and that would be a finding, not an obstacle; the number sits
        # here exactly for this kind of check.
        #
        # 🔴 WHAT THIS FIX DOES NOT CLAIM. That all seven are equipped the
        # way `join_elements` above is. They are NOT equipped, and this is
        # measured the same day: six of the seven were not parsed into
        # `clash_bundle`, `acceptance`, or `spec.OP_RESULT_CATEGORIES` —
        # meaning they fell out of the closed tables SILENTLY. Part of this
        # is closed on 08-21, part remained a debt with an address
        # (`spec.py:1037` — a hardcoded list of four ops, into which the
        # 08-20 wave did not enter its own). The ratchet counts OPS, not
        # their completeness.
        # ══════════════════════════════════════════════════════════════════
        # 78 -> 82 (2026-08-24). The difference again reconciled BY NAME,
        # and each op is dated by `git log -S "name=\"<op>\""` against the
        # registries, not recalled from memory:
        #
        #     08-23  create_wall_type      41b4bbc5
        #     08-23  transfer_family       dbb9fa2e
        #     08-23  create_floor_plan     2fd5f4f2
        #     08-24  transfer_material     (this change)
        #
        # 78 + 4 = 82, no remainder.
        #
        # 🔴 AND THE EARLIER EDIT OF THIS SAME NUMBER TURNED OUT TO BE
        # PROPHETIC. The paragraph above warned: "the ratchet counts OPS,
        # not their completeness," and three ops from the 08-23 wave stood
        # for a day outside SEVEN closed tables — the clash receipt,
        # `acceptance`, the authority ledger, category accounting, the form
        # census, witness coverage, the reverse contract. They held 23 red
        # tests, nine of them neighbors in the receipt file, failing only
        # because each one assembles the receipt in full. Here they are all
        # closed together with the fourth.
        # ══════════════════════════════════════════════════════════════════
        # 82 -> 83 (2026-09-07). The difference reconciled BY NAME and by
        # one op, dated by `git log -S 'name="query_element_state"'` against
        # the `kir/ops_authoring.py` registry, not recalled from memory:
        #
        #     09-06  query_element_state   878947f
        #
        # 82 + 1 = 83, no remainder.
        #
        # 🔴 THE PIN WAS MOVED AFTER VERIFYING THE CONTRACT, NOT FOR THE
        # SAKE OF GREEN. Exactly what the loop below guards is DECLARED for
        # the new op, and this is measured: `effect=EffectKind.READ`,
        # `result` — a real `ResultSpec`, `writes_model=False` (consistent
        # with READ), the loop does not ask non-reading ops about
        # `identity_cardinality`. That is, the red `83 != 82` was a COUNT
        # lagging by one op, not a hole in the contract: before the fix,
        # `assertEqual` failed on the FIRST line and the loop over 83 ops
        # never ran EVEN ONCE — the test was only guarding its own number.
        #
        # 🔴 WHAT THIS FIX DOES NOT CLAIM (the same caveat as the previous
        # two). That the op is equipped: `query_element_state` is outside
        # `spec.OP_RESULT_CATEGORIES` — same as ALL SIX READ ops (0 of 6),
        # meaning this is a property of the kind, not a new hole. The
        # ratchet counts OPS, not their completeness.
        #
        # The README still says "82 operations" — the discrepancy has been
        # named to the owner and is not fixed here.
        # ══════════════════════════════════════════════════════════════════
        # ══════════════════════════════════════════════════════════════════
        # 83 -> 84 (13.09.2026). Разница сведена ПО ИМЕНИ и по одному опу:
        #
        #     09-13  query_level_plan   плановый след уровня пачкой
        #
        # 83 + 1 = 84, без остатка.
        #
        # 🔴 И ПРОРОЧЕСТВО АБЗАЦА ВЫШЕ СРАБОТАЛО СНОВА, только на этот раз В
        # ОБРАТНУЮ СТОРОНУ. Абзац предупреждал: «трещотка считает ОПЫ, а не их
        # полноту», — и в прошлый раз три опа сутки простояли вне семи закрытых
        # таблиц. Сегодня новый оп выпал ровно из одной (`clash_bundle.OP_NO_BODY`),
        # и его поймали НЕ ЭТОТ СЧЁТ, а два свойства: вето реестра
        # (`test_the_registry_owns_every_capability::test_a_reading_op_makes_no_body`,
        # заведённое 07.09 именно для этого) и закон закрытости таблицы. Оба
        # покраснели в том же прогоне, где оп появился, и назвали имя и причину.
        # То есть предупреждение абзаца выше остаётся верным: полноту стерегут
        # свойства, а это число стережёт только себя.
        #
        # 🔴 ЧЕГО ЭТА ПРАВКА НЕ УТВЕРЖДАЕТ (та же оговорка, что у трёх прошлых).
        # Что оп оснащён: `query_level_plan` вне `spec.OP_RESULT_CATEGORIES` —
        # как и ВСЕ СЕМЬ читающих (0 из 7), то есть это свойство рода, а не
        # новая дырка. Контракт, который стережёт цикл ниже, у опа объявлен и
        # проверен: `effect=EffectKind.READ`, `result` — настоящий `ResultSpec`,
        # `writes_model=False`.
        # ══════════════════════════════════════════════════════════════════
        self.assertEqual(len(spec.OPS), 84)
        for name, op in spec.OPS.items():
            with self.subTest(op=name):
                self.assertIsInstance(op.effect, EffectKind)
                self.assertIsInstance(op.result, ResultSpec)
                self.assertEqual(
                    op.writes_model,
                    op.effect is not EffectKind.READ,
                )
                if op.writes_model:
                    self.assertIsNot(
                        op.result.identity_cardinality,
                        IdentityCardinality.NONE,
                    )

    def test_plural_and_special_results_are_not_reference_producers(self):
        for name in (
            "create_pipe_system",
            "route_pipe_system",
            "route_duct_system",
            "create_stairs",
            "create_group",
            "create_curtain_grid_line",
        ):
            with self.subTest(op=name):
                self.assertFalse(spec.OPS[name].result.referenceable)

    def test_reference_result_kinds_are_closed(self):
        for name, op in spec.OPS.items():
            with self.subTest(op=name):
                kind = op.result.reference_kind
                self.assertTrue(kind is None or isinstance(kind, ReferenceKind))

    def test_same_spelling_can_have_different_typed_reference_contracts(self):
        def param(op_name: str, param_name: str):
            return next(
                item for item in spec.OPS[op_name].params
                if item.name == param_name)

        self.assertEqual(
            param("create_door", "host").ref_kinds,
            (ReferenceKind.WALL,),
        )
        self.assertEqual(
            param("place_family", "host").ref_kinds,
            (ReferenceKind.ELEMENT,),
        )
        self.assertEqual(param("create_railing", "host").ref_kinds, ())
        self.assertEqual(param("create_text", "in_view").ref_kinds, ())

    def test_wire_identity_is_validated_by_declared_cardinality(self):
        single = spec.OPS["create_wall"].result
        many = spec.OPS["create_pipe_system"].result
        deleted = spec.OPS["delete"].result

        self.assertTrue(single.identity_present({"id": "42"}))
        self.assertTrue(single.identity_present({"id": 42}))
        self.assertFalse(single.identity_present({"id": ""}))
        self.assertFalse(single.identity_present({"id": True}))
        self.assertTrue(many.identity_present({"segment_ids": ["42", 43]}))
        self.assertFalse(many.identity_present({"segment_ids": []}))
        self.assertTrue(deleted.identity_present({"deleted_id": "42"}))


class TypedForwardReferences(unittest.TestCase):
    def test_place_family_is_a_referenceable_single_element_result(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "place_family",
                    "id": "PF",
                    "xyz": [0, 0, 0],
                    "level": {"by": "element_id", "value": 42},
                    "symbol": {"by": "element_id", "value": 800},
                },
                {
                    "op": "set_param",
                    "id": "S",
                    "target": {"by": "ref", "value": "PF"},
                    "param": "Comments",
                    "value": "typed-result",
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("__tg_S = (Element)__el_PF", out.csharp)

    def test_load_family_is_referenceable_without_a_create_prefix(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "load_family",
                    "id": "LF",
                    "path": r"C:\families\chair.rfa",
                    "type_name": "Chair",
                },
                {
                    "op": "set_param",
                    "id": "S",
                    "target": {"by": "ref", "value": "LF"},
                    "param": "Comments",
                    "value": "loaded-by-kir",
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("FamilySymbol __el_LF", out.csharp)
        self.assertIn("__tg_S = (Element)__el_LF", out.csharp)

    def test_plural_network_result_cannot_be_used_as_one_element(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "create_pipe_system",
                    "id": "NET",
                    "level": {"by": "element_id", "value": 42},
                    "nodes": [
                        {"id": "a", "xyz_mm": [0, 0, 0]},
                        {"id": "b", "xyz_mm": [3000, 0, 0]},
                    ],
                    "segments": [{"from": "a", "to": "b"}],
                },
                {
                    "op": "set_param",
                    "id": "S",
                    "target": {"by": "ref", "value": "NET"},
                    "param": "Comments",
                    "value": "invalid",
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertFalse(out.ok)
        diagnostic = next(item for item in out.diagnostics
                          if item.code == "KIR-L003")
        self.assertEqual(diagnostic.op_id, "S")
        self.assertEqual(diagnostic.got, "NET")

    def test_wall_only_host_rejects_a_generic_element_result(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {
                    "op": "place_family",
                    "id": "PF",
                    "xyz": [0, 0, 0],
                    "level": {"by": "element_id", "value": 42},
                    "symbol": {"by": "element_id", "value": 800},
                },
                {
                    "op": "create_door",
                    "id": "D",
                    "host": {"by": "ref", "value": "PF"},
                    "offset_mm": 1000,
                    "symbol": {"by": "element_id", "value": 700},
                },
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertFalse(out.ok)
        diagnostic = next(item for item in out.diagnostics
                          if item.code == "KIR-L004")
        self.assertEqual(diagnostic.expected, ["wall"])
        self.assertEqual(diagnostic.got, "element")

    def test_generic_element_consumer_accepts_a_level_subtype(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {"op": "create_level", "id": "L", "elev_mm": 9000,
                 "name": "KIR typed level"},
                {"op": "set_param", "id": "S",
                 "target": {"by": "ref", "value": "L"},
                 "param": "Comments", "value": "typed-supertype"},
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [item.as_dict() for item in out.diagnostics])
        self.assertIn("__tg_S = (Element)__el_L", out.csharp)

    def test_nonreferenceable_view_parameter_rejects_ref_before_emit(self):
        program = {
            "ir_version": "1.0",
            "ops": [
                {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "element_id", "value": 42}},
                {"op": "create_text", "id": "T",
                 "in_view": {"by": "ref", "value": "W"},
                 "at": [10, 20], "content": "must refuse"},
            ],
        }

        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertFalse(out.ok)
        diagnostic = next(item for item in out.diagnostics
                          if item.field_name == "in_view")
        self.assertEqual(diagnostic.code, "KIR-T001")


if __name__ == "__main__":
    unittest.main()
