"""Audit-fix regression pack (2026-07-20): F2 query level chain, F3 cert
verdict-span, F7 truncated snapshot pools, F8 level-name braces, F10 dup-id
code, F12 coordinate bound."""
import unittest

from kukai.ir import authoring, ground as ground_mod, serving, translation_cert as tc
from kukai.ir.compiler import compile_program, _parse_and_check
from kukai.ir.diag import KirRefusal
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


def _wall_prog(**wall_extra):
    return {"ir_version": "1.0", "ops": [dict(
        {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "height_mm": 3000, "level": {"by": "element_id", "value": 42}},
        **wall_extra)]}


class QueryLevelChain(unittest.TestCase):
    def test_level_name_reader_mirrors_extractor_bip_chain(self):
        out = compile_program(
            {"ir_version": "1.0", "ops": [
                {"op": "query_count", "id": "q", "kind": "stair",
                 "where": {"level_name": "Этаж 1"}}]},
            revit_version="2026")
        self.assertTrue(out.ok)
        for bip in ("WALL_BASE_CONSTRAINT", "LEVEL_PARAM",
                    "SCHEDULE_LEVEL_PARAM", "FAMILY_LEVEL_PARAM"):
            self.assertIn(bip, out.csharp)


class CertVerdictSpan(unittest.TestCase):
    WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
            "p1_mm": [6000, 0], "height_mm": 3000.0,
            "level": {"__grounded__": {"id": 42, "name": "L1",
                                       "via": "element_id"}},
            "type": {"__grounded__": {"id": 901, "name": "T",
                                      "via": "element_id"}}}

    def _without_checks(self, drop_keys):
        """Wave A2 adversary: create_wall is model-certified now, so 'delete
        the verdict line but keep the reader marker' is UNCONSTRUCTIBLE (a
        WitnessCheck refuses to exist without its __post.Add).  The only
        expressible mutation is dropping whole checks from the list — which
        the cert catches by KEY."""
        orig = authoring._EMITTERS["create_wall"]

        def broken(op, ver, stamp):
            d, c, p, r = orig(op, ver, stamp)
            p = [check for check in p if check.obligation_key not in drop_keys]
            return d, c, p, r

        authoring._EMITTERS["create_wall"] = broken
        try:
            return tc.certify_op(self.WALL, "2026")
        finally:
            authoring._EMITTERS["create_wall"] = orig

    def test_baseline_proven(self):
        self.assertTrue(tc.certify_op(self.WALL, "2026").proven)

    def test_dropped_check_is_caught_by_key(self):
        # A2 flip of the old F3 adversary: removing the endpoint check (the
        # ONLY way to lose its verdict now) is caught by key absence.
        cert = self._without_checks({"endpoints"})
        self.assertFalse(cert.proven)
        self.assertTrue(any("endpoints" in g for g in cert.gaps))

    def test_verdictless_check_is_unconstructible(self):
        # The A2 kill of the span residual: a check whose verdict was deleted
        # cannot even be BUILT — EmitModelError at construction.  The old
        # characterization test asserted the residual PASSED; inverted here:
        # the "reader survived, verdict gone" state is dead by construction.
        from kukai.ir.emit_model import EmitModelError, WitnessCheck
        with self.assertRaises(EmitModelError):
            WitnessCheck(
                obligation_key="endpoints",
                reader_cs="    var __lc = __el_W1.Location as LocationCurve;\n",
                verdict_cs="    // verdict deleted\n",
                message="endpoints mismatch (geometry)")

    def test_height_check_dropped_is_caught(self):
        cert = self._without_checks({"height"})
        self.assertFalse(cert.proven)

    def test_registry_coverage_still_clean(self):
        self.assertEqual(tc.audit_registry_coverage(), ())


class TruncatedPools(unittest.TestCase):
    def _snap(self, **extra):
        snap = {key: list(value) if isinstance(value, list) else value
                for key, value in GROUND_SNAPSHOT.items()}
        snap.update(extra)
        return snap

    def test_default_on_truncated_pool_refused(self):
        snap = self._snap(pipe_types=[{"id": 5, "name": "PT"}],
                          pipe_types__truncated=True,
                          piping_system_types=[{"id": 6, "name": "ST"}])
        prog = {"ir_version": "1.0", "ops": [
            {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 0],
             "p1_mm": [3000, 0, 0], "level": {"by": "element_id", "value": 42}}]}
        with self.assertRaises(KirRefusal) as ctx:
            ground_mod.ground(_parse_and_check(prog), snap)
        text = " ".join(d.message_ru for d in ctx.exception.diagnostics)
        self.assertIn("обрезан", text)

    def test_name_not_found_mentions_truncation(self):
        snap = self._snap(wall_types=[{"id": 9, "name": "ЖБ 200"}],
                          wall_types__truncated=True)
        prog = _wall_prog(type={"by": "name", "value": "Несуществующий"})
        with self.assertRaises(KirRefusal) as ctx:
            ground_mod.ground(_parse_and_check(prog), snap)
        text = " ".join(d.message_ru for d in ctx.exception.diagnostics)
        self.assertIn("обрезан", text)

    def test_exact_name_match_in_slice_still_resolves(self):
        snap = self._snap(wall_types=[{"id": 9, "name": "ЖБ 200"}],
                          wall_types__truncated=True)
        prog = _wall_prog(type={"by": "name", "value": "ЖБ 200"})
        grounded = ground_mod.ground(_parse_and_check(prog), snap)
        self.assertEqual(grounded[0]["type"]["__grounded__"]["id"], 9)


class LevelNameBraces(unittest.TestCase):
    def test_double_brace_name_survives_into_post_check(self):
        out = compile_program(
            {"ir_version": "1.0", "ops": [
                {"op": "create_level", "id": "L", "elev_mm": 0,
                 "name": "A}}B"}]},
            revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertIn('__el_L.Name != "A}}B"', out.csharp)
        self.assertNotIn('"A}B"', out.csharp)


class DupIdCode(unittest.TestCase):
    def test_duplicate_op_id_has_its_own_code(self):
        out = compile_program(
            {"ir_version": "1.0", "ops": [
                {"op": "create_level", "id": "L", "elev_mm": 0},
                {"op": "create_level", "id": "L", "elev_mm": 3000}]},
            revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P006", [d.code for d in out.diagnostics])


class CoordinateBound(unittest.TestCase):
    def test_ten_km_plus_coordinate_refused_statically(self):
        out = compile_program(_wall_prog(p0_mm=[1e12, 0]),
                              revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_edge_of_bound_accepted(self):
        out = compile_program(
            _wall_prog(p0_mm=[9_999_000, 0], p1_mm=[9_990_000, 0]),
            revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)


class MultilineOpId(unittest.TestCase):
    def test_query_id_line_terminators_stay_inside_comment(self):
        oid = "q\r\n\x85\u2028\u2029return null;"
        out = compile_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": oid, "kind": "wall"}],
        })

        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn(
            r"// query_count q\r\n\u0085\u2028\u2029return null;",
            out.csharp)
        self.assertNotIn("// query_count " + oid, out.csharp)

    def test_authoring_id_newline_is_data_not_csharp(self):
        oid = "W1\nreturn null; //"
        program = _wall_prog()
        program["ops"][0]["id"] = oid
        out = compile_program(program, snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn(r"// create_wall W1\nreturn null; //", out.csharp)
        self.assertIn(r"// post W1\nreturn null; //", out.csharp)
        self.assertIn(r"// witness W1\nreturn null; //", out.csharp)
        self.assertNotIn("// create_wall " + oid, out.csharp)


class AdminArgumentStrictness(unittest.IsolatedAsyncioTestCase):
    async def test_idempotence_route_does_not_coerce_string_false(self):
        from fastapi import HTTPException
        from kukai.api import admin_kir

        with self.assertRaises(HTTPException) as caught:
            await admin_kir.idempotence({
                "doc_stamp": "docA", "dry_run": "false",
                "whole_model": True,
            })
        self.assertEqual(caught.exception.status_code, 422)


class CleanupStampsCensus(unittest.IsolatedAsyncioTestCase):
    """Task #69: cancellation-as-a-feature for regular (non-A5) programs.

    ``/admin/kir/cleanup_stamps`` gained ``expected_count`` — the caller's
    build receipt tells the route how many elements the program actually
    created; the route compares it against how many the sweep found still
    carrying the stamp and returns an explicit verdict rather than a bare
    count the reader has to interpret alone.
    """

    async def test_expected_count_rejects_non_integer_string(self):
        from fastapi import HTTPException
        from kukai.api import admin_kir

        with self.assertRaises(HTTPException) as caught:
            await admin_kir.cleanup_stamps({
                "stamp_prefix": "kir:1a2b3c4d:", "expected_count": "3",
            })
        self.assertEqual(caught.exception.status_code, 422)

    async def test_expected_count_rejects_negative(self):
        from fastapi import HTTPException
        from kukai.api import admin_kir

        with self.assertRaises(HTTPException) as caught:
            await admin_kir.cleanup_stamps({
                "stamp_prefix": "kir:1a2b3c4d:", "expected_count": -1,
            })
        self.assertEqual(caught.exception.status_code, 422)

    async def test_expected_count_rejects_bool(self):
        # bool is a subclass of int in Python; must not slip through.
        from fastapi import HTTPException
        from kukai.api import admin_kir

        with self.assertRaises(HTTPException) as caught:
            await admin_kir.cleanup_stamps({
                "stamp_prefix": "kir:1a2b3c4d:", "expected_count": True,
            })
        self.assertEqual(caught.exception.status_code, 422)

    # ── envelope shapes ──────────────────────────────────────────────────
    # `serving._a5_sweep_payload`/`_a5_payload` unwrap up to three levels of
    # a `{"result": {...}}` nesting — the same reader the pre-existing A5
    # `_sweep`/`_preview` runners (serving.py ~3222-3262) already use on the
    # identical `_run_declarative` output. `_reconcile_stamp_census` must go
    # through that reader, not a second hand-rolled `.get("found")": a
    # census that silently reports "unreadable" on a perfectly good nested
    # sweep is worse than no census — exactly the silent-zero outcome the
    # task was written against. FLAT is what a completely unwrapped bridge
    # result looks like; NESTED is the one-level-under-"result" shape.
    #
    # Both built via `serving.build_sweep_payload` — the ONE builder for
    # this wire shape (task #69, 31.07 postmortem: this exact envelope was
    # independently hand-typed, and independently wrong, in four places —
    # see that function's docstring). Hand-typing it here again would be
    # the fifth.
    FLAT_SWEEP = serving.build_sweep_payload(
        prefix="kir:1a2b3c4d:",
        found_ids=["1001", "1002", "1003"],
        deleted_ids=["1001", "1002", "1003"],
        preview=False, commit_status="Committed")
    NESTED_SWEEP = serving.build_sweep_payload(
        prefix="kir:1a2b3c4d:",
        found_ids=["1001", "1002", "1003"],
        deleted_ids=["1001", "1002", "1003"],
        preview=False, commit_status="Committed", wrap_result=True)

    def test_census_unwraps_a_nested_bridge_envelope(self):
        # Disproving test for the review defect: reading `.get("found")`
        # straight off the envelope (the pre-fix code) finds nothing on the
        # nested shape and reports "unreadable" even though the sweep is
        # perfectly consistent (found==expected, remaining==0). Pinned here
        # so a regression to the naive reader fails loudly.
        from kukai.api.admin_kir import _reconcile_stamp_census

        naive_found = self.NESTED_SWEEP.get("found")  # what the old code read
        self.assertIsNone(
            naive_found,
            "sanity: the naive top-level read must in fact miss the nested "
            "payload, or this test is not exercising the bug")

        out = _reconcile_stamp_census(
            3, self.NESTED_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertEqual(out["found_count"], 3)
        self.assertTrue(out["reconciled"])
        self.assertNotIn("не смог прочитать", out["verdict"])

    def test_census_reads_a_flat_bridge_envelope_too(self):
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            3, self.FLAT_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertEqual(out["found_count"], 3)
        self.assertTrue(out["reconciled"])

    def test_census_refuses_a_payload_bound_to_another_prefix(self):
        # Protection _a5_sweep_payload adds over a bare unwrap: a census
        # must never be reconciled against a DIFFERENT sweep's numbers.
        # A5JournalError becomes a named verdict, not a route-level 500.
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            3, self.NESTED_SWEEP, stamp_prefix="kir:deadbeef:", delete=True)
        self.assertFalse(out["reconciled"])
        self.assertIsNone(out["found_count"])
        self.assertIn("перепись невозможна", out["verdict"])

    # ── census facts (built vs found) ───────────────────────────────────
    def test_census_reconciles_when_counts_match(self):
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            3, self.FLAT_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertTrue(out["reconciled"])
        self.assertTrue(out["census_matched"])

    def test_census_names_the_fail_open_stamp_write_on_undercount(self):
        # found < expected: some created element never got its stamp
        # (authoring._stamp_block's non-A5 branch is try/catch — a
        # read-only Comments parameter silently drops the write). Sweep
        # itself is internally consistent (found==deleted, remaining==0) —
        # only the CENSUS half of the verdict should complain.
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            5, self.FLAT_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertFalse(out["reconciled"])
        self.assertFalse(out["census_matched"])
        self.assertTrue(out["cleanup_complete"])
        self.assertIn("не хватает", out["verdict"])

    def test_census_names_the_repeat_run_case_on_overcount(self):
        # found > expected: same program-hash prefix already present from
        # an earlier run (kir:<hash8> does not distinguish run instances).
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            2, self.FLAT_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertFalse(out["reconciled"])
        self.assertFalse(out["census_matched"])
        self.assertIn("больше", out["verdict"])

    def test_census_without_expected_count_is_explicit_not_silent(self):
        # Optional field omitted: must say "not checked", never look like a
        # silent pass — but cleanup_complete (delete=true) is still a known,
        # independently reportable fact.
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            None, self.FLAT_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertIsNone(out["census_matched"])
        self.assertTrue(out["cleanup_complete"])
        self.assertTrue(out["reconciled"])  # nothing KNOWN failed
        self.assertIn("не передан", out["verdict"])

    def test_census_handles_unreadable_sweep_result(self):
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            3, {"error": "document_mismatch"},
            stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertFalse(out["reconciled"])
        self.assertIsNone(out["found_count"])
        self.assertIn("перепись невозможна", out["verdict"])

    # ── preview vs delete must not be blended ───────────────────────────
    def test_preview_never_claims_cleanup_is_complete(self):
        # delete=False: nothing was removed, so "everything is gone" must
        # never be assertable — cleanup_complete stays None, not True.
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            3, self.FLAT_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=False)
        self.assertIsNone(out["cleanup_complete"])
        self.assertTrue(out["census_matched"])
        self.assertIn("предпросмотр", out["verdict"])

    def test_delete_leftover_remainder_is_named_not_absorbed_into_gap(self):
        # census matches (built count == found count) but the delete
        # transaction left elements behind (remaining > 0): this is its OWN
        # fact and must surface even though the built-vs-found comparison
        # alone would say "matched".
        from kukai.api.admin_kir import _reconcile_stamp_census

        partial = dict(self.FLAT_SWEEP)
        partial.update(deleted=2, deleted_ids=["1001", "1002"],
                        remaining=1, remaining_ids=["1003"])
        out = _reconcile_stamp_census(
            3, partial, stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertTrue(out["census_matched"])
        self.assertFalse(out["cleanup_complete"])
        self.assertFalse(out["reconciled"])
        self.assertIn("осталось", out["verdict"])

    # ── types: found, counted, NEVER deleted (lead's decision, task #69) ──
    # create_type stamps its FamilySymbol on ALL_MODEL_TYPE_COMMENTS, a
    # parameter WhereElementIsNotElementType() structurally never reaches
    # (measured: kukai/ir/serving.py's _ORPHAN_SWEEP_TEMPLATE runs a SEPARATE
    # WhereElementIsElementType() census for exactly that reason). Deleting a
    # type would delete every instance of it, including ones this program
    # never built — so a found type is reported, with its id and name, and
    # is never a delete candidate, ever, regardless of `delete`.
    TYPE_SWEEP = serving.build_sweep_payload(
        prefix="kir:1a2b3c4d:",
        found_ids=["1001", "1002", "1003", "1004"],
        deleted_ids=["1001", "1002", "1003", "1004"],
        types_found_ids=["2001"], types_found_names=["ЖБ 400x400"],
        preview=False, commit_status="Committed")

    def test_types_are_counted_into_the_built_found_comparison(self):
        # Built 5 (4 instances + 1 type); found matches exactly once types
        # are added into the total — this is the fix for the false
        # "not enough found" the census used to report on any program that
        # used create_type before types got their own scan.
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            5, self.TYPE_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertTrue(out["census_matched"])
        self.assertEqual(out["types_found_count"], 1)
        self.assertEqual(out["types_found"], [{"id": "2001", "name": "ЖБ 400x400"}])

    def test_types_are_never_reported_as_deleted_even_with_delete_true(self):
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            5, self.TYPE_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=True)
        # cleanup_complete is about INSTANCES only (remaining==0); a type
        # sitting there un-deleted must not turn this into "incomplete".
        self.assertTrue(out["cleanup_complete"])
        self.assertTrue(out["reconciled"])

    def test_types_note_states_the_boundary_up_front(self):
        # The reason must be IN the answer, not something the caller has to
        # infer from a number — and must appear even when delete=false.
        from kukai.api.admin_kir import _reconcile_stamp_census

        for delete in (True, False):
            with self.subTest(delete=delete):
                out = _reconcile_stamp_census(
                    5, self.TYPE_SWEEP, stamp_prefix="kir:1a2b3c4d:",
                    delete=delete)
                self.assertIsNotNone(out["types_note"])
                self.assertIn("удаляет ВСЕ его экземпляры", out["types_note"])
                self.assertIn("2001", out["verdict"])
                self.assertIn("ЖБ 400x400", out["verdict"])

    def test_no_types_found_means_no_types_note(self):
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            3, self.FLAT_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertEqual(out["types_found_count"], 0)
        self.assertEqual(out["types_found"], [])
        self.assertIsNone(out["types_note"])

    def test_undercount_wording_is_generic_not_a_single_guessed_cause(self):
        # Task #69 lead review: the "probable cause" text must name the
        # CATEGORIES of cause and say the runtime cannot distinguish them —
        # not present one hypothesis (e.g. read-only Comments) as if it
        # were the diagnosis.
        from kukai.api.admin_kir import _reconcile_stamp_census

        out = _reconcile_stamp_census(
            5, self.FLAT_SWEEP, stamp_prefix="kir:1a2b3c4d:", delete=True)
        self.assertIn("не определяет", out["verdict"])
        self.assertIn("не различает", out["verdict"])


class SweepPayloadBuilder(unittest.TestCase):
    """Task #69, 31.07 postmortem: the sweep envelope was hand-typed in at
    least four test/mock locations, and three same-day incidents were the
    same disease — a stale schema-version literal, and two places dropping
    the v3 ``types_found*`` triple. ``serving.build_sweep_payload`` is the
    ONE builder now; every mock site in this tree calls it instead of
    re-typing the contract. This class is the required disproving pair: the
    builder's default output must be ACCEPTED by the validator, and a
    deliberately incomplete build from the SAME builder must be REJECTED —
    a builder proven only on the happy path is just a convenient way to
    write something untrue.
    """

    def test_default_build_is_accepted_by_the_validator(self):
        payload = serving.build_sweep_payload(
            prefix="kir:1a2b3c4d:", found_ids=["1001", "1002"],
            deleted_ids=["1001", "1002"])
        accepted = serving._a5_sweep_payload(
            payload, stamp_prefix="kir:1a2b3c4d:")
        self.assertEqual(accepted["found"], 2)
        self.assertEqual(accepted["types_found"], 0)

    def test_wrapped_build_with_types_is_accepted_by_the_validator(self):
        payload = serving.build_sweep_payload(
            prefix="kir:1a2b3c4d:", found_ids=["1001"],
            deleted_ids=["1001"], types_found_ids=["2001"],
            types_found_names=["ЖБ 400x400"], preview=False,
            commit_status="Committed", wrap_result=True)
        accepted = serving._a5_sweep_payload(
            payload, stamp_prefix="kir:1a2b3c4d:")
        self.assertEqual(accepted["types_found"], 1)
        self.assertEqual(accepted["types_found_names"], ["ЖБ 400x400"])

    def test_build_with_a_field_omitted_is_rejected(self):
        # The disproving half: a payload built from the SAME source of
        # truth, minus one required field, must fail the same way a
        # hand-typed incomplete dict would — proving the builder cannot
        # silently paper over a real contract violation.
        payload = serving.build_sweep_payload(
            prefix="kir:1a2b3c4d:", found_ids=["1001"],
            omit=["types_found"])
        self.assertNotIn("types_found", payload)
        with self.assertRaises(serving.A5JournalError):
            serving._a5_sweep_payload(payload, stamp_prefix="kir:1a2b3c4d:")

    def test_build_with_a_stale_schema_version_is_rejected(self):
        # Reproduces the exact class of bug the lead fixed by hand in
        # test_rebuilt_phase_coverage.py: a caller who overrides
        # schema_version with a stale literal must still be caught.
        payload = serving.build_sweep_payload(
            prefix="kir:1a2b3c4d:", found_ids=["1001"],
            schema_version="a5-stamp-sweep/2")
        with self.assertRaises(serving.A5JournalError):
            serving._a5_sweep_payload(payload, stamp_prefix="kir:1a2b3c4d:")

    def test_build_bound_to_a_different_prefix_is_rejected(self):
        payload = serving.build_sweep_payload(
            prefix="kir:1a2b3c4d:", found_ids=["1001"])
        with self.assertRaises(serving.A5JournalError):
            serving._a5_sweep_payload(payload, stamp_prefix="kir:deadbeef:")

    def test_counts_are_derived_not_independently_typable(self):
        # A caller cannot hand a mismatched count/id-list pair the way an
        # ad-hoc dict literal could — the builder derives the count itself.
        payload = serving.build_sweep_payload(
            prefix="kir:1a2b3c4d:", found_ids=["1001", "1002", "1003"])
        self.assertEqual(payload["found"], 3)


class GroupMemberHardening(unittest.TestCase):
    def _member_wall(self, oid="W1"):
        return {"op": "create_wall", "id": oid, "p0_mm": [0, 0],
                "p1_mm": [6000, 0], "height_mm": 3000.0,
                "level": {"__grounded__": {"id": 42, "name": None,
                                           "via": "element_id"}},
                "type": {"__grounded__": {"id": None, "name": None,
                                          "via": "doc_default",
                                          "in_emit": "__doc_default__"}}}

    def test_raw_ungrounded_member_now_grounds(self):
        """A member written the way a caller CAN write it is grounded and built.

        This assertion used to be `assertFalse(out.ok)` — the raw member was
        refused, and the refusal told the author "члены должны быть pre-grounded
        (element_id/абсолютные координаты)". That advice was impossible to
        follow: `{"by": "element_id"}` failed identically, because the emitter
        wants the INTERNAL `{"__grounded__": ...}` shape and `ground()` never
        recursed into `members`. So the op was unreachable for anyone but the
        rebuild bridge, which explains its 0 uses in 51 574 lifted ops.

        What the test was really protecting — never leaking KIR-P000 for a
        member shape — is asserted below and still holds. The old assertion was
        pinning a gap, not a guarantee.
        """
        member = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                  "p1_mm": [6000, 0], "height_mm": 3000.0,
                  "level": {"by": "element_id", "value": 42}}
        out = compile_program(
            {"ir_version": "1.0", "ops": [
                {"op": "create_group", "id": "G", "members": [member],
                 "placements": [[0, 0, 3000]]}]},
            revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

    def test_member_by_name_grounds_against_the_snapshot(self):
        member = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                  "p1_mm": [6000, 0], "height_mm": 3000.0,
                  "level": {"by": "name", "value": "Этаж 1"}}
        out = compile_program(
            {"ir_version": "1.0", "ops": [
                {"op": "create_group", "id": "G", "members": [member],
                 "placements": [[0, 0, 3000]]}]},
            revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

    def test_unresolvable_member_is_typed_and_names_the_member(self):
        """Never KIR-P000 — and the refusal must be addressable. An op index
        into a nested list is not something the author can act on, so the
        member is named by ITS id and the candidates come along."""
        member = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                  "p1_mm": [6000, 0], "height_mm": 3000.0,
                  "level": {"by": "name", "value": "Такого уровня нет"}}
        out = compile_program(
            {"ir_version": "1.0", "ops": [
                {"op": "create_group", "id": "G", "members": [member],
                 "placements": [[0, 0, 3000]]}]},
            revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        codes = [d.code for d in out.diagnostics]
        self.assertNotIn("KIR-P000", codes)
        d = out.diagnostics[0]
        self.assertEqual(d.op_id, "G")
        self.assertEqual(d.field_name, "members[W1].level")
        self.assertTrue(d.candidates)

    def test_pre_grounded_members_are_passed_through_untouched(self):
        """The rebuild bridge's own members must not be re-resolved — same
        bytes in, same bytes out."""
        import copy

        from kukai.ir.ground import ground

        member = self._member_wall()
        op = {"op": "create_group", "id": "G", "members": [member],
              "placements": [[0, 0, 3000]]}
        before = copy.deepcopy(op["members"])
        out = ground([copy.deepcopy(op)], GROUND_SNAPSHOT)
        self.assertEqual(out[0]["members"], before)

    def test_member_with_ref_selector_refused(self):
        member = self._member_wall()
        member["level"] = {"__grounded__": {"via": "ref", "ref": "L1"}}
        out = compile_program(
            {"ir_version": "1.0", "ops": [
                {"op": "create_group", "id": "G", "members": [member],
                 "placements": []}]},
            revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)

    def test_member_readbacks_present(self):
        out = compile_program(
            {"ir_version": "1.0", "ops": [
                {"op": "create_group", "id": "G",
                 "members": [self._member_wall()],
                 "placements": [[0, 0, 3000]]}]},
            revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("// witness G__m__W1", out.csharp)


if __name__ == "__main__":
    unittest.main()
