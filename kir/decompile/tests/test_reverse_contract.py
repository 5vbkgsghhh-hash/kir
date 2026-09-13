"""Executable coverage contract between the KIR forward and reverse axes."""
from __future__ import annotations

import ast
import inspect
import json
import textwrap
import unittest
from collections import Counter

from kir import spec
from kir.decompile import lift, materialize
from kir.reverse_contract import (
    REVERSE_CONTRACTS,
    REVERSE_CONTRACT_SCHEMA,
    ReverseContractError,
    ReverseMode,
    assert_composed_emission,
    assert_lift_emission,
    reverse_contract_report,
)


class ReverseContractTests(unittest.TestCase):
    def test_manifest_is_exhaustive_over_live_write_registry(self):
        write_ops = {
            name for name, op_spec in spec.OPS.items()
            if op_spec.family in spec.WRITE_FAMILIES
        }
        self.assertEqual(set(REVERSE_CONTRACTS), write_ops)
        # 35 -> 37 (03.08.2026): +create_room_separator (the separators wave)
        # and +create_opening (the openings wave). The number here is a LOCK, not
        # statistics: the manifest must grow together with the registry, not silently
        # lag behind it.
        # 37 -> 38 (09.08.2026): +create_wall_foundation, declared as
        # capture_gap — L0 does not carry WallFoundation.WallId, and the wall IS
        # the entire input of the operation. The number of direct lifts did NOT grow in this case,
        # and that is exactly what the lock must show.
        # 38 -> 43 (09.08.2026): the ЭОМ/flex/placeholder wave. Of the five, exactly
        # ONE (create_conduit) arrived with a real lifter; the remaining four
        # are declared capture_gap, and this is not a formality — placeholders in
        # L0 have no IsPlaceholder bit, flex elements have no point array.
        # THE NUMBER WAS RE-CAPTURED AS `len(REVERSE_CONTRACTS)` ON THE MERGED TREE: both
        # waves counted from 37, and "42" from the ЭОМ branch would have drowned the strip
        # foundation without failing a single test.
        # 43 -> 44 (09.08.2026): +create_angular_dimension, capture_gap. The lock
        # worked: for an angular dimension the capture gap is LARGER than
        # for a linear one — besides the owner view and References, one would also have to lift
        # the annotation arc, which is not present in L0 1.0 at all.
        # 44 -> 46 (09.08.2026): the framing wave — create_beam_system and
        # create_truss, both capture_gap. The number of direct lifts did NOT grow, and
        # this is exactly the demonstration the lock exists for: L0 reads
        # OST_StructuralFraming, meaning it sees the SPAWNED beams and members, not
        # the system and truss that spawned them. Lifting them one by one would be WORSE than
        # an atom — the object would disappear, and its layout would degenerate into a bunch of
        # coordinates that cannot be rebuilt.
        # 46 -> 50 (09.08.2026): the loads and evacuation-route wave — all four
        # capture_gap, because L0 does not read either loads or evacuation-route
        # lines at all. AND THIS LOCK TRIGGERED RIGHT AT THE MERGE: the framing
        # wave wrote "46" here, counting from 44 and not knowing about the loads —
        # the number, taken as-is, would have drowned all four operations of the ЭОМ wave,
        # without failing a single test. 50 was re-captured as `len(REVERSE_CONTRACTS)` on
        # the merged tree, exactly as the comment ten lines above requires.
        # 50 -> 53 (09.08.2026): the site wave — create_topography,
        # create_building_pad, create_site_subregion. All three CAPTURE_GAP, and
        # this is a MEASUREMENT, not caution: the extraction category table has neither
        # OST_Topography, nor OST_Toposolid, nor OST_BuildingPad — the pipeline does
        # not read them at all, so there is no L0 row to lift from.
        # 53 -> 55 (09.08.2026): the applied-profile wave — create_wall_sweep and
        # create_slab_edge. Both CAPTURE_GAP, and this is a MEASUREMENT by the same check: the
        # extraction category table has neither OST_Cornices, nor OST_Reveals, nor
        # OST_EdgeSlab. For the wall sweep, on top of the capture gap there is also a
        # part that is UNFIXABLE: its position cannot be recovered BY CONSTRUCTION,
        # because Autodesk documents it as a property of the TYPE, not
        # of the instance — so even a full capture would give only the host, the type, and the
        # orientation (see the contract's limitation).
        # 55 -> 58 (09.08.2026, MERGE). The datum wave gave three contracts:
        # a DECOMPOSED grid chain (links are lifted as create_grid, only
        # chain membership is lost), an extruded roof, and a multistory
        # stair — CAPTURE_GAP by MEASUREMENT (EXTRUSION_START/END and
        # ReferencePlane do not occur in decompile/ even once, MultistoryStairs
        # — not once in the whole package).
        #
        # AND THIS IS THE FOURTH TIME THIS NUMBER HAS BECOME A MERGE CONFLICT.
        # The history in the comments above names 40, 46, 50, 53, 55, 47 — and
        # each one was honestly measured on its own branch. Merging the text
        # left TWO `assertEqual` calls in a row, of which the first one failed.
        # The conclusion is not "check more carefully" but structural: the number branches together
        # with the registry, so it is taken by RUNNING `reverse_contract_report()`
        # on one's own tree, and what is recorded here is only the trace of the last measurement.
        # 58 -> 60 (09.08.2026): the solids wave — create_solid_extrusion and
        # create_solid_revolve, both CAPTURE_GAP. The gap here is DEEPER than for
        # the others: the element is read in full, but the built DirectShape
        # stores the B-rep, not the program that wrote it — two different
        # programs give a byte-for-byte identical element. The reverse pass requires
        # RECOGNIZING the shape, not one more capture field.
        # THE FIFTH TIME IN ONE DAY THIS NUMBER IS A CONFLICT: the solids wave wrote
        # "46" against its own base of 44. Re-captured as `len(REVERSE_CONTRACTS)` on
        # the MERGED tree, exactly as the paragraph above requires.
        # 60 -> 61 (09.08.2026): the detailing wave — create_filled_region,
        # CAPTURE_GAP. This is a MEASUREMENT against the extraction category table: neither
        # OST_FilledRegion nor OST_MaskingRegion is in it. The gap is DOUBLE, and
        # its second half is worth more than the first: even a read
        # `GetBoundaries()` is useless without the owner view's basis — a contour
        # lifted into world XY would mean a different place on every section.
        # THE SIXTH TIME IN ONE DAY: the wave wrote "54" against its own base of 53.
        # Re-captured as `len(REVERSE_CONTRACTS)` on the MERGED tree.
        # 61 -> 62 (10.08.2026): the reinforcement wave — create_area_reinforcement,
        # CAPTURE_GAP. A measurement, not a taxonomy: the OST_AreaRein category is not in
        # `extract._CATEGORY_SPECS` at all, meaning reading encounters neither
        # reinforcement systems nor their bars; and across 38 saved decompiles with a
        # census there are zero such elements. Re-captured as `len(REVERSE_CONTRACTS)`
        # by running on THIS tree, not added to a number from a foreign branch.
        # 61 -> 62 (10.08.2026): the mass wave — create_face_wall, CAPTURE_GAP.
        # The mode was chosen by MEASUREMENT, not by habit: extraction does read OST_Walls,
        # but `FaceWall` has no `LocationCurve` (CS0029 on all six versions — it is not
        # a `Wall`), and L0 carries neither the host nor the face normal by any field. So what needs
        # fixing is the CAPTURE, not the lifter, and the mode must say exactly this.
        # 63 -> 64 (10.08.2026): the stairs wave — create_stairs_landing,
        # CAPTURE_GAP. The mode was chosen by MEASUREMENT: the OST_StairsLandings category is not
        # in the extraction table, and the string `StairsLanding` does not occur in
        # a single `decompile/` file (grep 10.08). So what needs fixing is the CAPTURE, not
        # the lifter: `_lift_stairs` lifts the stair by its run and knows nothing at all
        # about landing components, so every landing of a decompiled building
        # is silently lost. Re-captured by running on THIS tree, not added to a
        # number from a foreign branch.
        # 64 -> 65 (10.08.2026): create_space is a named LIFTER_GAP.  The
        # writer exists, while reverse capture is not yet strong enough to
        # recreate it; omitting the op from this denominator hid that gap.
        # 65 -> 66 (15.08.2026): the second-run wave — create_stairs_run,
        # CAPTURE_GAP. The mode was NOT chosen by symmetry with the landing: the decision was already
        # made inside the module itself and stands there with a measurement — "L0 reads no
        # StairsRun at all: Stairs.GetStairsRuns() is called nowhere in
        # decompile/ and the run class is named nowhere either". That is,
        # what needs fixing is the CAPTURE, not the lifter, exactly as with the landing, but by
        # ITS OWN check, not because its neighbor is the same.
        # 66 -> 67 (18.08.2026): `join_elements` — the first RELATIONSHIP op.
        # CAPTURE_GAP, and the mode was chosen by ITS OWN check, not by its neighbors:
        # Revit stores the join explicitly and hands it back on direct request
        # (`JoinGeometryUtils.GetJoinedElements`, 6/6 versions), meaning the lift
        # is not impossible — it is simply NOT WRITTEN. Measurement 17.08: zero occurrences of
        # `GetJoinedElements` in all of `decompile/`. `state_transition` here
        # would have been a targeted deception — it would have sent the next person to prove
        # impossibility instead of doing capture work.
        #
        # 🔴 67 -> 73 (22.08.2026), AND THIS IS NOT A WAVE, IT IS DEBT. The number had stood at 67 since
        # 18.08 07:45, while the registry grew by SIX writing ops over 20–21.08:
        # create_surface · create_solid_blend · create_solid_boolean ·
        # create_solid_sweep · create_adaptive_component (all CAPTURE_GAP,
        # 20.08) and author_family (LIFTER_GAP, 21.08). That is, THESE TWO TESTS
        # WERE RED FOR TWO DAYS STRAIGHT and were read by no one — exactly the shape
        # for which agreement 7 was introduced: "a red that nobody sees
        # is silence." The lock was reset by RUNNING `reverse_contract_report()`
        # on this tree, not by adding up the waves' numbers.
        # 73 -> 75 (23.08.2026). TWO waves, and the first did NOT touch the literal:
        # `transfer_family` brought the count to 74 and left 73 here, meaning
        # the ratchet had already gone red before the wall-types wave (checked against the
        # HEAD version of the registry: 74 writing ops against the literal 73).
        # The second increment is `create_wall_type`. The number is corrected together with
        # the reason, not silently: the ratchet must tell the truth about
        # WHAT exactly grew.
        # 75 -> 76 (23.08.2026): create_floor_plan — see the growth
        # entry at `report["write_ops"]` below.
        # 76 -> 77 (24.08.2026): `transfer_material`, commit feb2b0d2 at 12:03.
        # 🔴 THE RED STOOD FOR A FULL DAY AND WAS INVISIBLE, AND THE REASON IS NAMED:
        # the `kir/decompile/tests/` package takes 7.6 GB altogether and is killed
        # by the kernel at 62 % (measured 25.08), so nobody reads its ratchets.
        # The instrument fired at the same hour as the growth; what failed was the METHOD
        # of reading it. The package runs only with `-k "not BulkFlag"`.
        self.assertEqual(len(REVERSE_CONTRACTS), 77)
        # 23 -> 24 (03.08.2026): create_railing moved from capture_gap to
        # direct. Railing-path capture has been traveling since 29.07, and k2_ar_rd_v9 carries
        # 31 rows of capture — the old wording "L0 has neither a railing
        # path nor …" stopped being true. The number here is exactly the lock
        # that keeps the manifest from rotting silently.
        # 25 -> 26 (09.08.2026): +create_conduit. The lifter was written by the same
        # wave as the op: the L0 row for a conduit is indistinguishable in shape from a cable tray
        # (a linear MEPCurve, the same ends, the same level, the same type), and
        # DIRECT can be declared here exactly because the lift exists.
        # 27 -> 29 (04.09.2026): create_pipe_placeholder and
        # create_duct_placeholder moved from capture_gap to direct.
        # The gap was closed FOUR DAYS BEFORE ITS DEADLINE (decided 09.08, deadline
        # 08.09) and closed with exactly what it promised: capture reads `Pipe.IsPlaceholder` /
        # `Duct.IsPlaceholder` (`extract._placeholder_reader_cs`, independent
        # of category), the bit travels as the `L0Element.is_placeholder` field, the lifter
        # splits it into two ops. This was the ONLY kind in the manifest whose
        # loss did not refuse but LIED: a placeholder was rebuilt as a full-fledged
        # pipe. The guarantee is BOUNDED, not FORM_EXACT: a snapshot from before 04.09 carries
        # no bit and behaves as before — the boundary is named in the manifest.
        # 29 -> 31 (04.09.2026, the same day): create_flex_duct and
        # create_flex_pipe. Capture reads `FlexDuct.Points`/`FlexPipe.Points` —
        # the PRIMARY quantity, not the ends of the Hermite spline that are
        # computed from it. The refusal did not disappear, it moved down from the level of the TABLE to the level of the
        # SNAPSHOT: a decompile without the key gives the same atom with the same text, and
        # a trace longer than 64 points refuses by name, because `path3`
        # cannot express it, and truncating would pass off a different trace as this one.
        # 31 -> 32 (04.09.2026, the third move of the same day): create_opening.
        # The boundary is readable (IsRectBoundary + BoundaryRect/BoundaryCurves,
        # all three 6/6, zero traps), the host has been readable since 09.08. The lift is PARTIAL and
        # declared as such: `variety=wall_rect` is inverted, while `host_face`
        # remains an atom, because the cut direction is present in NONE of the
        # seven members of `Opening` — this is not poverty of reading but the absence of a
        # witness. Exactly the shape of railings, where one kind out of two is inverted.
        # 32 -> 33 (04.09.2026, the fourth move of the same day): create_line_load
        # — the first closed out of eleven categories introduced into capture that same
        # day by the "silence becomes a refusal" wave. The old reason
        # ("OST_LineLoads is outside the extraction table") stopped being true at
        # the very hour the category entered it.
        # 34 -> 35 (04.09.2026, the sixth move): create_area_load — the third and
        # last kind of load. Five boundaries, and the last two are read in the
        # POST-CONDITION of the op itself: one loop, one elevation mark.
        # 33 -> 34 (04.09.2026, the fifth move of the same day): create_point_load
        # — the second kind of load. The boundaries are the same as for the linear one, and are taken by
        # ONE body: the op's post-condition promises exactly OrientTo == Project.
        self.assertEqual(
            sum(contract.direct_same_op_lift
                for contract in REVERSE_CONTRACTS.values()),
            35,
        )
        with self.assertRaises(TypeError):
            REVERSE_CONTRACTS["delete"] = REVERSE_CONTRACTS["create_wall"]  # type: ignore[index]

    def test_every_category_candidate_is_direct_or_an_explicit_capture_gap(self):
        for category, candidate in lift._CANDIDATES.items():
            with self.subTest(category=category, op=candidate.op):
                contract = REVERSE_CONTRACTS[candidate.op]
                self.assertIn(
                    contract.mode,
                    (ReverseMode.DIRECT, ReverseMode.CAPTURE_GAP),
                )
                if contract.mode is ReverseMode.DIRECT:
                    self.assertIn(candidate.lifter_name, contract.entrypoints)

    def test_every_declared_direct_entrypoint_exists_and_names_the_emitted_op(self):
        for op_name, contract in REVERSE_CONTRACTS.items():
            if contract.mode is not ReverseMode.DIRECT:
                continue
            for entrypoint in contract.entrypoints:
                with self.subTest(op=op_name, entrypoint=entrypoint):
                    function = getattr(lift, entrypoint)
                    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
                    string_literals = {
                        node.value
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                    }
                    self.assertIn(op_name, string_literals)

    def test_l1_emission_guard_agrees_with_the_manifest_on_every_op(self):
        """The guard must agree with the table — on EVERY record, without names.

        OP NAMES USED TO STAND HERE, AND THEY ROTTED (11.08.2026). The test enumerated
        `create_dimension` as "the last remaining capture_gap"; capturing
        dimension references (`a51e31c2`) moved it to bounded DIRECT, and the test
        turned red — not because the guard broke, but because the list of names
        was a COPY of the table, not a check against it. Replacing the name with
        `create_space` would fix the day and rot again the day
        `create_space` gets a lifter.

        That is why there is no longer a single op name here. The test derives its expectation
        from `REVERSE_CONTRACTS` at run time: mode `DIRECT` must
        be liftable, any other mode must refuse in a typed way. This is the first of our two
        remedies — ASK THE AUTHORITY instead of declaring what
        it holds — applied to a test.

        What the test STILL does not check, so that no one mistakes it for
        more: it checks the guard against the manifest, NOT the manifest against
        reality. That the mode is declared correctly is proven by the capture and the
        lifter, not by this function; behind the movement of the mode stands the counter lock
        above and the record in the file's history.

        GREEN ON THE FIRST RUN IS PROVEN BY A MUTATION, NOT ASSERTED
        (11.08.2026). Substituting `create_beam` from `direct` to `capture_gap` —
        and nothing else — fails exactly this test with "create_beam is declared
        capture_gap, but the guard let it through"; without the substitution there are zero failures. The test
        CAN fail.

        THE MUTANT'S BOUNDARY, because the manifest itself did not accept two out of three
        attempts, and that is a fact about it, not about the test: `direct` without an entry point
        cannot be constructed (`ValueError: direct reverse contract needs an
        entrypoint`), neither can `capture_gap` without `decided_on`/`due`
        (`record_ratchet`), and `REVERSE_CONTRACTS` itself is a `MappingProxyType`
        and does not accept writes. Faking a mode change had to be done by substituting the
        NAME in the test module. The manifest fails closed in both directions; the check
        here guards the seam between it and the guard, not its own
        grammar.
        """
        seen_modes: Counter[ReverseMode] = Counter()
        for op_name, contract in sorted(REVERSE_CONTRACTS.items()):
            seen_modes[contract.mode] += 1
            with self.subTest(op=op_name, mode=contract.mode.value):
                if contract.mode is ReverseMode.DIRECT:
                    self.assertEqual(
                        assert_lift_emission(op_name).op_name, op_name,
                        "объявленный DIRECT не поднимается")
                else:
                    with self.assertRaises(
                            ReverseContractError,
                            msg=(f"{op_name} объявлен {contract.mode.value}, "
                                 "а страж его пропустил")):
                        assert_lift_emission(op_name)

        # Both sides must be NON-EMPTY, otherwise a check that cannot
        # fail would look green: a manifest without a single DIRECT, or without
        # a single non-DIRECT, would pass the loop above silently.
        direct = seen_modes[ReverseMode.DIRECT]
        self.assertTrue(direct, "в манифесте не осталось ни одного DIRECT")
        self.assertTrue(sum(seen_modes.values()) - direct,
                        "в манифесте не осталось ни одного не-DIRECT")

    def test_composed_group_emission_has_a_checked_entrypoint(self):
        """Guards the GRAMMAR of a composite contract, and NOT reachability.

        THE NAME-STRING CHECK WAS REMOVED (11.08.2026). Here stood

            self.assertEqual(contract.entrypoints,
                             ("component_to_group_program",))

        and this confirmed the WRITING of the name, not the existence of what the name
        names. A measurement from the same day: `component_to_group_program` has ZERO
        non-test references, nobody at all calls its input `place_group_ops`
        (not even the tests), it itself returns None when
        `native_group` is off, and `tests/test_capability_map_wiring.py` separately
        asserts that this gate is dead. That is, the string matched, but there was no
        exit — the value was asserted in one place and read nowhere.

        WHAT IT WAS REPLACED WITH, so that no one restores it as a "missing
        check": `kir/tests/test_reverse_entrypoints_exist.py` checks
        REACHABILITY for every declared entry point (a call, the name used as a value,
        or a row in a dispatch table — but NOT its own `__all__` and not
        the contract's own text) and keeps a journal of entry points named in advance,
        which fails from BOTH sides: both when an advance-named point became
        reachable, and when an unreachable one appeared without a record.

        What remains here is what belongs to this file: a composite contract
        MUST name an entry point, and it must exist as a module
        attribute; and an op not declared composite must refuse.
        """
        contract = assert_composed_emission("create_group")
        self.assertTrue(contract.entrypoints,
                        "составной контракт обязан называть точку входа")
        # 🔴 THE ENTRY POINT DOES NOT HAVE A SINGLE HOST, AND THE HARD-CODED `materialize` HERE WAS
        # A COINCIDENCE, NOT A LAW. As long as there was one composite point
        # (`component_to_group_program`, the component-library bridge), the module
        # matched it as a side effect. Since 23.08.2026 `create_group` has
        # gained a SECOND one, and it lives in a fundamentally different place: `lift_groups`
        # — the reverse pass over groups of the READ BUILDING, and it has nowhere to live in
        # the materializer. What must be checked is the EXISTENCE of the name among the
        # declared hosts of the reverse pass, not registration in one file.
        hosts = (materialize, lift)
        for entry in contract.entrypoints:
            with self.subTest(entrypoint=entry):
                found = [h.__name__ for h in hosts
                         if callable(getattr(h, entry, None))]
                self.assertTrue(
                    found,
                    "%s: точка входа не существует ни в одном из хозяев "
                    "обратного хода (%s)"
                    % (entry, ", ".join(h.__name__ for h in hosts)))
                self.assertEqual(
                    len(found), 1,
                    "%s: имя определено в ДВУХ хозяевах (%s) — какой из них "
                    "исполняет контракт, неизвестно"
                    % (entry, ", ".join(found)))
        for op_name in ("create_wall", "delete", "load_family"):
            with self.subTest(op=op_name), self.assertRaises(
                    ReverseContractError):
                assert_composed_emission(op_name)

    def test_report_is_stable_json_and_exposes_honest_modes(self):
        report = reverse_contract_report()
        self.assertEqual(report["schema"], REVERSE_CONTRACT_SCHEMA)
        # 37 -> 38 (09.08.2026): create_wall_foundation, mode capture_gap.
        # 38 -> 43 (09.08.2026): five operations of the ЭОМ wave; direct grew by exactly
        # one (create_conduit), the remaining four are capture_gap.
        # 43 -> 44 (09.08.2026): create_angular_dimension, mode capture_gap;
        # direct does not grow — it has no lift.
        # 44 -> 46 (09.08.2026): create_beam_system and create_truss, both
        # capture_gap; direct does not grow — neither of them has a lift.
        # 46 -> 50 (09.08.2026): the loads and evacuation-route wave, all four
        # capture_gap. RE-CAPTURED as `reverse_contract_report()` on the merged tree:
        # both waves counted from 44 separately, and neither of their figures is correct.
        # 50 -> 53 (09.08.2026): three site operations, all CAPTURE_GAP;
        # direct does not grow. THREE waves named 50, 46, and 40 here — re-captured as
        # `reverse_contract_report()` on the merged tree.
        # 53 -> 55 (09.08.2026): create_wall_sweep and create_slab_edge, both
        # CAPTURE_GAP; direct does not grow — neither of them has a lift, and for the
        # wall sweep it will NEVER have one in full: Autodesk documents the
        # profile's position as a property of the TYPE, not of the instance,
        # so even a full capture would return only the host, the type, and the
        # orientation. RE-CAPTURED as `reverse_contract_report()` on this tree.
        # 44 -> 47 (09.08.2026): the datum wave. direct did NOT grow by
        # even one: the grid chain is declared DECOMPOSED (links are lifted
        # as create_grid, only chain membership is lost), while
        # the extruded roof and the multistory stair are CAPTURE_GAP
        # by MEASUREMENT: EXTRUSION_START/END and ReferencePlane do not
        # occur in decompile/ even once, MultistoryStairs — not
        # once in the whole package.
        # 58 -> 60 (09.08.2026): the solids wave, both ops CAPTURE_GAP; direct does not
        # grow — they have no lift. RE-CAPTURED as `reverse_contract_report()`
        # on the merged tree, not added to either branch.
        # 60 -> 61 (09.08.2026): create_filled_region, mode capture_gap;
        # direct does not grow — the fill has no lift and will not have one until
        # extraction starts reading BOTH the boundary AND the view basis.
        # 61 -> 62 (10.08.2026): area reinforcement, mode capture_gap;
        # direct does not grow — reinforcement has no lift and will not have one until
        # extraction opens the OST_AreaRein category at all.
        # 61 -> 62 (10.08.2026): create_face_wall, mode capture_gap;
        # direct does not grow — the face wall has no lift and will not have one until
        # extraction starts reading BOTH the host AND the normal of the parent face.
        # 63 -> 64 (10.08.2026): the stairs wave — create_stairs_landing,
        # CAPTURE_GAP. The mode was chosen by MEASUREMENT: the OST_StairsLandings category is not
        # in the extraction table, and the string `StairsLanding` does not occur in
        # a single `decompile/` file (grep 10.08). So what needs fixing is the CAPTURE, not
        # the lifter: `_lift_stairs` lifts the stair by its run and knows nothing at all
        # about landing components, so every landing of a decompiled building
        # is silently lost. Re-captured by running on THIS tree, not added to a
        # number from a foreign branch.
        # 65 -> 66 (15.08.2026): create_stairs_run, CAPTURE_GAP — the same
        # second-run wave. `direct_same_op_lifts` does NOT move: the run
        # has no lift, and that is exactly what its reason in the module says.
        # 66 -> 67 (18.08.2026): join_elements, CAPTURE_GAP.
        # `direct_same_op_lifts` does NOT move: the join has no lift.
        # 67 -> 73 (22.08.2026): the two-day debt, broken down by name above.
        # `direct_same_op_lifts` does NOT move here either, even though the join
        # GAINED a lifter (`lift.py:lift_joins`): its lift is COMPOSITE, and
        # `direct_same_op_lift` means the right to place an L1 NODE — a right
        # whose exercise would break the fold, because a relationship has no
        # element of its own. A number that does not move even with a lifter written —
        # that is exactly the check that modes do not confuse "the op is liftable" with "the op
        # is liftable as a node".
        # 75 -> 76 (23.08.2026): create_floor_plan, CAPTURE_GAP.
        # The mode was chosen NOT for poverty of the lifter, but for poverty of CAPTURE: parsing does
        # not read views at all — `OST_Views` is in no category table,
        # no side index carries `ViewPlan`/`GenLevel`.
        # `direct_same_op_lifts` does NOT move, and this is not a formality: the op
        # was introduced for the FORWARD pass — preparing the catalog of someone else's document,
        # like `create_wall_type` and `transfer_family`. A live run of building K3
        # stalled on 917 room separators: `create_level` does not create
        # a floor plan, and `NewRoomBoundaryLines` does not work without a view, and with one
        # transaction per program each separator dropped 250 operations along with it.
        # 76 -> 77 (24.08.2026): `transfer_material` — EXTERNAL_SOURCE.
        # A material carries no provenance of the document it came from, so
        # the op is NEVER lifted from an element, but is synthesized from the layer
        # material names that capture already reads. `direct_same_op_lifts`
        # does not move: it has no lift by construction, not by poverty.
        self.assertEqual(report["write_ops"], 77)
        # 27 -> 29 (04.09.2026): pipe and duct placeholders — the argument
        # lives entirely with the first lock above, here it's the same number by a different instrument.
        self.assertEqual(report["direct_same_op_lifts"], 35)
        self.assertEqual(
            report["modes"],
            {
                # 27 -> 29 (04.09.2026): pipe and duct placeholders.
                # The census of modes must move in OPPOSITE directions: however much arrived in
                # direct, that much left capture_gap, and a discrepancy between these
                # two numbers would mean an op was lost or counted twice.
                "direct": 35,
                # 1 -> 2: create_opening is declared capture_gap honestly — L0 1.0
                # carries neither Opening.Host nor the opening boundary, and DIRECT here
                # would promise a lift that does not exist.
                # 2 -> 3 (09.08): create_wall_foundation — the same honesty and
                # exactly the same reason: L0 has no link between the foundation and the wall.
                # 3 -> 7 (09.08): the ЭОМ wave. Placeholders (no
                # IsPlaceholder bit in L0 — today they are lifted as an ordinary
                # pipe/duct, meaning the loop rebuilds something that is NOT a placeholder) and
                # flex sections (in L0 just a pair of ends, while the shape lives in Points).
                # 7 -> 8 (09.08): create_angular_dimension, by the same
                # honesty.
                # 8 -> 10 (09.08): the framing wave — the beam system and the truss.
                # 10 -> 14 (09.08): the loads and evacuation-route wave. L0 reads
                # neither point/line/area loads, nor evacuation-route
                # lines — not one of the four categories is in the extraction table
                # at all, so the gap here covers the whole op, not just a
                # single field.
                # 14 -> 17 (09.08): three site operations. Their gap is DEEPER than
                # the opening's: for an opening the L0 row is at least readable, while
                # site categories are not opened by extraction at all, so "the stage
                # said nothing" does not even apply here — there is no stage.
                # 17 -> 19 (09.08): create_wall_sweep and create_slab_edge.
                # 19 -> 21 (09.08, MERGE): the extruded roof and the
                # multistory stair from the datum wave. Merging the text
                # left TWO `capture_gap` keys and two `decomposed`
                # keys in a row here — python silently takes the last one, so what failed was not
                # what had diverged. The keys were consolidated, the numbers were re-captured by running:
                # 26 + 21 + 4 + 1 + 4 + 1 + 1 = 58 writing operations.
                # 21 -> 23 (09.08, MERGE OF THE SOLIDS WAVE): extrusion and
                # revolve. AND HERE AGAIN ONE DICT AND TWO KEYS: the solids wave
                # wrote `capture_gap: 10` and `decomposed: 3` against its own
                # base, and merging the text would have placed them ALONGSIDE 21 and 4 in
                # one literal, and python would have silently kept the last one — that
                # is, the suite would have failed on something other than what diverged. The keys were consolidated
                # into ONE, the numbers were re-captured by running on this tree.
                # 23 -> 24 (09.08, MERGE): the fill. Its gap is closer to the opening's than
                # to the site's, but with its own second half: the boundary
                # CAN be read (`GetBoundaries()` is 6/6), but there is today nothing to
                # translate it into the owner view's axes in L0.
                # THE THIRD TIME ONE DICT AND TWO KEYS: the wave wrote
                # `capture_gap: 18` / `decomposed: 3` against its own base.
                # The keys were consolidated into ONE, the numbers were re-captured by running.
                # 24 -> 23 + lifter_gap 1 (09.08, MERGE with the host-capture
                # wave): `create_wall_foundation` LEFT the capture gaps,
                # because `WallFoundation.WallId` is now readable (6/6) —
                # "capture cannot do it" would have become a lie. The sum did not change,
                # what changed was the ADDRESS of the work: not teaching it to read, but writing the lifter.
                # 23 -> 24 (10.08): create_area_reinforcement. The gap here is
                # DEEPER than the opening's and of the same kind as the site's: extraction does
                # not open the OST_AreaRein category at all, so "the stage
                # stayed silent" does not even apply here — there is no stage.
                # 24 -> 25 (10.08, MERGE of the mass wave):
                # create_face_wall — a wall on a mass face. The same
                # kind of gap: extraction does not open the mass
                # category, so "the stage stayed silent" does not even
                # apply here — there is no stage.
                # 25 -> 26 (10.08, the stairs wave): create_stairs_landing.
                # The same kind of gap as for reinforcement and the face wall:
                # extraction does not open the OST_StairsLandings category at all,
                # so "the stage stayed silent" does not even apply here — there is
                # no stage. And for the landing this gap costs more than it seems:
                # the run IS readable, so the decompiled building looks
                # COMPLETE, having lost every intermediate landing.
                # create_dimension moved from capture_gap to bounded direct;
                # create_space entered separately as a named lifter gap.
                # 25 -> 26 (15.08.2026): create_stairs_run. The breakdown by
                # modes must move together with the total (66 above) — otherwise
                # the sum would match with a diverged composition, and that is exactly
                # shape 12: "the count matched, the names diverged".
                # 26 -> 27 (18.08.2026): join_elements — the join
                # is readable by a direct request, but capture does not read it.
                # 27 -> 32 (20.08.2026, DEBT): five ops of the free-form wave
                # — create_surface, create_solid_blend, create_solid_boolean,
                # create_solid_sweep, create_adaptive_component.
                # 32 -> 31 (22.08.2026): join_elements LEFT the capture
                # gaps into COMPOSED. The old reason ("nothing in decompile/
                # reads it yet: measured 2026-08-17, zero occurrences") WAS
                # A LIE ALREADY AT THE HOUR IT WAS WRITTEN: the read was introduced by 39ebd521 at 18.08
                # 07:03, the text was written by 518325f3 at 07:19. The sum did not change,
                # what changed was the ADDRESS of the work — and a guard was set up for this shape
                # (`kir/agreements.py`, agreement 8).
                # 31 -> 32 (23.08.2026): create_floor_plan. A CAPTURE
                # gap, not a lifter one: parsing does not read views at all.
                # 32 -> 30 (04.09.2026): exactly the same two ops, a countermove
                # to `direct` above.
                "capture_gap": 24,
                # 2 -> 3 (21.08.2026): author_family.
                # 3 -> 4 (23.08.2026): `create_wall_type`. The mode is LIFTER, not
                # capture, and this is a reversal on the same day: the composition of the wall's
                # layers STARTED being readable (40 types out of 44 on K1, 18 composite),
                # but no lifter produces the op — a type in someone else's document
                # is still named by hand.
                "lifter_gap": 4,
                "decomposed": 4,
                # 1 -> 2 (22.08.2026): join_elements. Composite, not direct,
                # and this is a MEASUREMENT of L1's structure, not caution: a relationship has no
                # element of its own, and a flat L1 is exactly one node per element.
                "composed": 2,
                "state_transition": 4,
                "pinned_existing": 1,
                # 1 -> 2 (23.08.2026): `transfer_family`. 🔴 THE NUMBER WAS OVERDUE
                # THROUGH NO FAULT OF THIS WAVE: the op was committed earlier and did not touch the literal,
                # so the ratchet had already gone red before the wall types (checked against the
                # HEAD version of the registry). It is fixed here because a silent
                # red costs more than someone else's authorship.
                # 2 -> 3 (24.08.2026): `transfer_material`. The third op
                # whose source is OUTSIDE the document being lifted: the material arrives
                # from a foreign file, like a family and like a loaded .rfa.
                "external_source": 3,
            },
        )
        self.assertEqual(
            [row["op"] for row in report["contracts"]],
            sorted(REVERSE_CONTRACTS),
        )
        self.assertEqual(
            json.dumps(report, ensure_ascii=False, sort_keys=True),
            json.dumps(reverse_contract_report(), ensure_ascii=False,
                       sort_keys=True),
        )
        self.assertEqual(
            Counter(row["mode"] for row in report["contracts"]),
            Counter(report["modes"]),
        )


if __name__ == "__main__":
    unittest.main()
