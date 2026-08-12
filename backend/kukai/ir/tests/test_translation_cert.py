"""Property tests for the translation-validation certificate (translation_cert).

Convention follows the repo's dependency-free property style (hypothesis is not
in the prod venv): the corpus is the emitter scope-contract's own
``PROGRAMS × VERSIONS`` matrix — the same per-family corner cases that exercise
every optional branch (dim_type / tag leader / text width+leader / create_type
depth+material / floor holes / place_family flips / arc wall).  Every op goes
through the REAL pipeline (``_parse_and_check`` → ``ground`` → the emitter), so
the certificate is checked against genuine emission, never a mock.

Numbering matches TRANSLATION_VALIDATION_SPEC §6:
  C1 every write op × 6 versions -> proven
  C2 audit_registry_coverage() == () (table<->registry biection)
  C3 every write op in spec.OPS has an OpRefinementSpec
  C4 conditional witness present iff its param is present (no false, no missed)
  C5 MUTATION: excising one real check flips proven -> False at the right clause
  C6 determinism (same inputs -> identical certificate; cross-process stable)
  C7 certify_program == aggregate of per-op certificates
  C8 assert_refined fail-closed; certificate_enabled() default OFF
  C9 create_stairs (sole-op template) certifies proven on all 6 versions
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_cert_queue.jsonl"))

from kukai.ir import ground as ground_mod  # noqa: E402
from kukai.ir import spec  # noqa: E402
from kukai.ir.authoring import _EMITTERS  # noqa: E402
from kukai.ir.compiler import _parse_and_check  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.ir.tests.test_emitter_scope_contract import (  # noqa: E402
    PROGRAMS,
    VERSIONS,
)
from kukai.ir.translation_cert import (  # noqa: E402
    KIND_GEOMETRY,
    KIND_MATERIALIZE,
    KIND_PARAMETER,
    KIND_SEMANTIC,
    OpCertificate,
    ProgramCertificate,
    UnprovenRefinementError,
    _ensure_table,
    assert_refined,
    audit_registry_coverage,
    certificate_enabled,
    certify_op,
    certify_program,
)


def _grounded_programs():
    """Yield (program_name, version, grounded_ops) for the whole fixture matrix."""

    for pname, prog in PROGRAMS.items():
        min_ver = prog.get("__min_ver__", "2021")
        # Верхняя граница версии — та же симметрия, что в самом корпусе (см.
        # его шапку): у волны нагрузок ось версий смотрит в другую сторону,
        # и на 2024-2026 честный ответ — типизированный KIR-E003, а не C#.
        max_ver = prog.get("__max_ver__", VERSIONS[-1])
        prog = {k: v for k, v in prog.items()
                if k not in ("__min_ver__", "__max_ver__")}
        normed = _parse_and_check(prog)
        grounded = ground_mod.ground(normed, GROUND_SNAPSHOT)
        for ver in [v for v in VERSIONS if min_ver <= v <= max_ver]:
            yield pname, ver, grounded


_STAIRS_OP = {
    "op": "create_stairs", "id": "ST1",
    "p0_mm": [0, 0], "p1_mm": [3000, 0],
    "base_level": {"__grounded__": {"via": "id", "id": 42}},
    "top_level": {"__grounded__": {"via": "id", "id": 43}},
    "width_mm": 1200,
}


class RegistryCoverage(unittest.TestCase):
    def test_c2_table_matches_registry_exactly(self) -> None:
        self.assertEqual(audit_registry_coverage(), ())

    def test_c3_every_write_op_is_certifiable(self) -> None:
        table = _ensure_table()
        write_ops = {
            name for name, op_spec in spec.OPS.items()
            if op_spec.family in spec.WRITE_FAMILIES
        }
        missing = write_ops - set(table)
        self.assertEqual(
            missing, set(),
            f"write ops with no OpRefinementSpec: {sorted(missing)}")

    def test_c3_no_dangling_table_entry(self) -> None:
        table = _ensure_table()
        for name in table:
            self.assertTrue(
                name in spec.OPS,
                f"OpRefinementSpec {name!r} is not a registry op")


class RefinementProven(unittest.TestCase):
    def test_c1_every_op_every_version_is_proven(self) -> None:
        seen: set[str] = set()
        for pname, ver, grounded in _grounded_programs():
            for op in grounded:
                cert = certify_op(op, ver)
                seen.add(op["op"])
                with self.subTest(program=pname, ver=ver, op=op["op"]):
                    self.assertTrue(
                        cert.proven,
                        f"{op['op']} on {ver} unproven: {cert.gaps}")
        # Sanity: the fixtures really did cover the whole _EMITTERS table.
        table_ops = set(_EMITTERS)
        self.assertEqual(
            table_ops - seen, set(),
            "fixtures did not certify every _EMITTERS op")

    def test_c9_stairs_proven_on_every_version(self) -> None:
        for ver in VERSIONS:
            with self.subTest(ver=ver):
                cert = certify_op(_STAIRS_OP, ver)
                self.assertTrue(cert.proven, cert.gaps)

    def test_every_certificate_records_a_materialize_clause(self) -> None:
        for _pname, ver, grounded in _grounded_programs():
            for op in grounded:
                cert = certify_op(op, ver)
                kinds = {v.kind for v in cert.clauses}
                self.assertIn(KIND_MATERIALIZE, kinds, op["op"])


class ConditionalWitnesses(unittest.TestCase):
    """C4 — a conditional clause's witness appears iff its param is present."""

    def _cert_for(self, op: dict, ver: str = "2024") -> OpCertificate:
        normed = _parse_and_check(
            {"ir_version": "1.0", "intent": "t", "ops": [op],
             **({"allow_destructive": True} if op["op"] == "delete" else {})})
        grounded = ground_mod.ground(normed, GROUND_SNAPSHOT)
        return certify_op(grounded[0], ver)

    def _clause(self, cert: OpCertificate, needle: str):
        for verdict in cert.clauses:
            if needle in verdict.clause:
                return verdict
        raise AssertionError(f"no clause matching {needle!r} in {cert.op}")

    def test_pipe_diameter_conditional(self) -> None:
        base = {"op": "create_pipe", "id": "P", "p0_mm": [0, 0, 2700],
                "p1_mm": [3000, 0, 2700],
                "level": {"by": "element_id", "value": 42}}
        with_d = self._cert_for({**base, "diameter_mm": 50})
        without_d = self._cert_for(base)
        self.assertTrue(self._clause(with_d, "diameter").discharged)
        self.assertTrue(self._clause(with_d, "diameter").required)
        v = self._clause(without_d, "diameter")
        self.assertFalse(v.required)
        self.assertTrue(v.discharged)          # absent param -> witness absent
        self.assertIsNone(v.matched_marker)
        self.assertTrue(with_d.proven and without_d.proven)

    def test_place_family_flips_conditional(self) -> None:
        base = {"op": "place_family", "id": "T", "xyz": [2000, 2000, 0],
                "level": {"by": "element_id", "value": 42}}
        flipped = self._cert_for({
            **base, "rotation_deg": 90, "mirrored": False,
            "hand_flipped": True, "facing_flipped": True})
        plain = self._cert_for(base)
        for needle in ("mirrored", "hand flip", "facing flip", "rotation"):
            self.assertTrue(self._clause(flipped, needle).discharged, needle)
            self.assertTrue(self._clause(flipped, needle).required, needle)
            absent = self._clause(plain, needle)
            self.assertFalse(absent.required, needle)
            self.assertIsNone(absent.matched_marker, needle)
        self.assertTrue(flipped.proven and plain.proven)

    def test_wall_arc_conditional(self) -> None:
        base = {"op": "create_wall", "id": "W", "p0_mm": [325, 0],
                "p1_mm": [0, 325], "level": {"by": "element_id", "value": 42}}
        arced = self._cert_for({**base, "arc": {
            "curve_type": "Arc", "center_mm": [0.0, 0.0, 0.0],
            "radius_mm": 325.0, "x_axis": [1.0, 0.0, 0.0],
            "y_axis": [0.0, 1.0, 0.0], "start_angle_rad": 0.0,
            "end_angle_rad": 1.5707963267948966}})
        straight = self._cert_for({**base, "p1_mm": [6000, 0]})
        self.assertTrue(self._clause(arced, "arc curve").discharged)
        self.assertFalse(self._clause(straight, "arc curve").required)
        self.assertIsNone(self._clause(straight, "arc curve").matched_marker)

    def test_create_type_depth_material_conditional(self) -> None:
        base = {"op": "create_type", "id": "CT",
                "source_type": {"by": "element_id", "value": 500},
                "category": "structural", "new_name": "T1", "width_mm": 400.0}
        rich = self._cert_for({
            **base, "depth_mm": 600.0, "material": "Бетон B30"})
        lean = self._cert_for(base)
        for needle in ("depth param", "material holds"):
            self.assertTrue(self._clause(rich, needle).discharged, needle)
            self.assertFalse(self._clause(lean, needle).required, needle)
            self.assertIsNone(self._clause(lean, needle).matched_marker, needle)


class MutationCatches(unittest.TestCase):
    """C5 — the heart of the wave: excise a real check, proof must fail.

    We wrap the real emitter and surgically delete ONE structural witness from
    the emitted (create/post) blocks, then re-certify.  A certificate that
    still says "proven" would be useless; each mutation must flip proven to
    False at the corresponding clause.
    """

    def _mutate_and_certify(
        self, op: dict, ver: str, target_op: str,
        remove_from: str, needle: str,
    ) -> OpCertificate:
        import kukai.ir.translation_cert as tc

        real = _EMITTERS[target_op]

        def wrapped(o, v, stamp):
            d, c, p, r = real(o, v, stamp)
            if remove_from == "create":
                c = c.replace(needle, "// removed")
            elif isinstance(p, (list, tuple)):
                # Wave A2 model post: a verdictless check is unconstructible,
                # so the only expressible post mutation is dropping whole
                # checks — drop every check whose fragments contain the needle.
                p = [check for check in p
                     if needle not in (check.reader_cs + check.verdict_cs)]
            else:
                p = p.replace(needle, "// removed")
            return d, c, p, r

        original = _EMITTERS[target_op]
        _EMITTERS[target_op] = wrapped
        try:
            return tc.certify_op(op, ver)
        finally:
            _EMITTERS[target_op] = original

    def _grounded(self, prog_op: dict, destructive: bool = False) -> dict:
        body = {"ir_version": "1.0", "intent": "t", "ops": [prog_op]}
        if destructive:
            body["allow_destructive"] = True
        normed = _parse_and_check(body)
        return ground_mod.ground(normed, GROUND_SNAPSHOT)[0]

    def test_c5_wall_height_check_removed(self) -> None:
        op = self._grounded({
            "op": "create_wall", "id": "W", "p0_mm": [0, 0],
            "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42}})
        # sanity: unmutated is proven
        self.assertTrue(certify_op(op, "2024").proven)
        cert = self._mutate_and_certify(
            op, "2024", "create_wall", "post", "WALL_USER_HEIGHT_PARAM")
        self.assertFalse(cert.proven)
        self.assertTrue(
            any("height" in g and "unproven" in g for g in cert.gaps),
            cert.gaps)

    def test_c5_wall_materializer_removed(self) -> None:
        op = self._grounded({
            "op": "create_wall", "id": "W", "p0_mm": [0, 0],
            "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42}})
        cert = self._mutate_and_certify(
            op, "2024", "create_wall", "create", "Wall.Create")
        self.assertFalse(cert.proven)
        self.assertFalse(cert.materialized)

    def test_c5_materializer_name_in_block_comment_is_not_proof(self) -> None:
        import kukai.ir.translation_cert as tc

        op = self._grounded({
            "op": "create_wall", "id": "W", "p0_mm": [0, 0],
            "p1_mm": [6000, 0],
            "level": {"by": "element_id", "value": 42}})
        real = _EMITTERS["create_wall"]

        def comment_only(o, v, stamp):
            d, c, p, r = real(o, v, stamp)
            c = c.replace("Wall.Create", "/* Wall.Create */ __NoMaterializer")
            return d, c, p, r

        _EMITTERS["create_wall"] = comment_only
        try:
            cert = tc.certify_op(op, "2024")
        finally:
            _EMITTERS["create_wall"] = real
        self.assertFalse(cert.proven)
        self.assertFalse(cert.materialized)

    def test_c5_wall_refuse_removed(self) -> None:
        op = self._grounded({
            "op": "create_wall", "id": "W", "p0_mm": [0, 0],
            "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42}})
        cert = self._mutate_and_certify(
            op, "2024", "create_wall", "create", "__Refuse")
        self.assertFalse(cert.proven)
        self.assertFalse(cert.refusal_guarded)

    def test_c5_wall_level_check_removed(self) -> None:
        op = self._grounded({
            "op": "create_wall", "id": "W", "p0_mm": [0, 0],
            "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42}})
        cert = self._mutate_and_certify(
            op, "2024", "create_wall", "post", "WALL_BASE_CONSTRAINT")
        self.assertFalse(cert.proven)
        self.assertTrue(any("topology" in g for g in cert.gaps), cert.gaps)

    def test_c5_wall_endpoints_check_removed(self) -> None:
        op = self._grounded({
            "op": "create_wall", "id": "W", "p0_mm": [0, 0],
            "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42}})
        cert = self._mutate_and_certify(
            op, "2024", "create_wall", "post", ".Location as LocationCurve")
        self.assertFalse(cert.proven)
        self.assertTrue(any("geometry" in g for g in cert.gaps), cert.gaps)

    def test_c5_room_area_check_removed(self) -> None:
        op = self._grounded({
            "op": "create_room", "id": "R", "xy": [4000, 3000],
            "level": {"by": "element_id", "value": 42}})
        cert = self._mutate_and_certify(
            op, "2024", "create_room", "post", ".Area")
        self.assertFalse(cert.proven)
        self.assertTrue(any("semantic" in g for g in cert.gaps), cert.gaps)

    def test_c5_pipe_diameter_check_removed(self) -> None:
        op = self._grounded({
            "op": "create_pipe", "id": "P", "p0_mm": [0, 0, 2700],
            "p1_mm": [3000, 0, 2700], "level": {"by": "element_id", "value": 42},
            "diameter_mm": 50})
        cert = self._mutate_and_certify(
            op, "2024", "create_pipe", "post", "RBS_PIPE_DIAMETER_PARAM")
        self.assertFalse(cert.proven)
        self.assertTrue(any("parameter" in g for g in cert.gaps), cert.gaps)

    def test_c5_place_family_mirror_check_removed(self) -> None:
        op = self._grounded({
            "op": "place_family", "id": "T", "xyz": [2000, 2000, 0],
            "level": {"by": "element_id", "value": 42},
            "mirrored": True, "hand_flipped": True,
            "facing_flipped": False})
        # unmutated proven
        self.assertTrue(certify_op(op, "2024").proven)
        cert = self._mutate_and_certify(
            op, "2024", "place_family", "post", ".Mirrored != ")
        self.assertFalse(cert.proven)


class Determinism(unittest.TestCase):
    def test_c6_same_inputs_same_certificate(self) -> None:
        op = ground_mod.ground(
            _parse_and_check({"ir_version": "1.0", "intent": "t", "ops": [
                {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0],
                 "level": {"by": "element_id", "value": 42}}]}),
            GROUND_SNAPSHOT)[0]
        a = certify_op(op, "2024")
        b = certify_op(op, "2024")
        self.assertEqual(a, b)
        self.assertEqual(a.clauses, b.clauses)


class ProgramComposition(unittest.TestCase):
    def test_c7_program_is_aggregate_of_ops(self) -> None:
        for pname, ver, grounded in _grounded_programs():
            prog_cert = certify_program(grounded, ver)
            self.assertIsInstance(prog_cert, ProgramCertificate)
            per_op = tuple(certify_op(op, ver) for op in grounded)
            self.assertEqual(prog_cert.ops, per_op)
            self.assertEqual(
                prog_cert.proven, all(c.proven for c in per_op))
            with self.subTest(program=pname, ver=ver):
                self.assertTrue(prog_cert.proven, prog_cert.gaps)


class FailClosedAndFlag(unittest.TestCase):
    def test_c8_assert_refined_passes_on_proven(self) -> None:
        op = ground_mod.ground(
            _parse_and_check({"ir_version": "1.0", "intent": "t", "ops": [
                {"op": "create_grid", "id": "G", "p0_mm": [0, -1000],
                 "p1_mm": [0, 9000], "name": "А"}]}),
            GROUND_SNAPSHOT)[0]
        assert_refined(certify_op(op, "2024"))  # no raise

    def test_c8_assert_refined_raises_on_unproven(self) -> None:
        broken = OpCertificate(
            op="create_wall", version="2024", materialized=False,
            refusal_guarded=True, clauses=())
        with self.assertRaises(UnprovenRefinementError):
            assert_refined(broken)

    def test_c8_flag_default_off(self) -> None:
        previous = os.environ.pop("KUKAI_IR_TRANSLATION_CERT", None)
        try:
            self.assertFalse(certificate_enabled())
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_TRANSLATION_CERT"] = previous

    def test_c8_flag_opt_in(self) -> None:
        previous = os.environ.get("KUKAI_IR_TRANSLATION_CERT")
        os.environ["KUKAI_IR_TRANSLATION_CERT"] = "on"
        try:
            self.assertTrue(certificate_enabled())
        finally:
            if previous is None:
                del os.environ["KUKAI_IR_TRANSLATION_CERT"]
            else:
                os.environ["KUKAI_IR_TRANSLATION_CERT"] = previous

    def test_unknown_op_fails_closed(self) -> None:
        from kukai.ir.translation_cert import CertificateSchemaError
        with self.assertRaises(CertificateSchemaError):
            certify_op({"op": "query_count", "id": "Q", "kind": "wall"}, "2024")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
