from __future__ import annotations

from dataclasses import fields, replace
import ast
import base64
import copy
import os
from pathlib import Path
import pickle
import subprocess
import sys
from types import FunctionType, SimpleNamespace

import pytest

from kukai.design_source.examples import make_tower_source
from kukai.design_source.kir_candidates import plan_kir_candidates
from kukai.design_source.materializer import materialize
from kukai.ir import design_source_admission as admission
from kukai.ir.design_source_admission import (
    EVIDENCE_MISMATCH,
    INTERNAL_REFUSED,
    KIR_GROUND_REFUSED,
    KIR_PLAN_REFUSED,
    NONCANONICAL_CANDIDATE_SET,
    STALE_CANDIDATE_BUILD,
    STATUS_ACCEPTED,
    STATUS_REFUSED,
    admit_kir_candidates,
)
from kukai.ir.diag import Diagnostic, KirRefusal


BACKEND = Path(__file__).resolve().parents[3]
REPOSITORY = BACKEND.parent


def _admit_with_member_stage_for_test(build, member_admitter):
    def receipt_factory(**values):
        return SimpleNamespace(
            **values,
            accepted=values["status"] == STATUS_ACCEPTED,
        )

    def refused_factory(**values):
        return admission._refused(
            receipt_factory=receipt_factory,
            **values,
        )

    return admission._admit_kir_candidates_core(
        build,
        None,
        canonical_hash=admission.canonical_digest,
        dry_planner=admission.plan_dry_lowering,
        candidate_planner=admission.plan_kir_candidates,
        candidate_verifier=admission._verify_candidate_against_build,
        member_admitter=member_admitter,
        refused_factory=refused_factory,
        receipt_factory=receipt_factory,
        design_error_codes=admission._design_error_codes,
        kir_error_codes=admission._kir_error_codes,
    )


def test_three_floor_pack_is_atomically_admitted_with_bound_evidence() -> None:
    build = materialize(make_tower_source(n_floors=3))
    candidates = plan_kir_candidates(build)

    first = admit_kir_candidates(build, candidates)
    second = admit_kir_candidates(build, candidates)

    assert first.status == STATUS_ACCEPTED
    assert first.accepted is True
    assert first.refusal is None
    assert first.evidence_lifetime == admission.EVIDENCE_LIFETIME
    assert first.build_digest == build.manifest.build_digest
    assert first.requested_candidate_set_digest == candidates.candidate_set_digest
    assert first.canonical_candidate_set_digest == candidates.candidate_set_digest
    assert first.member_count == len(first.members) == 3
    assert first.entity_count == 18
    assert first.total_authored_ops == 18
    assert first.total_planned_ops == 18
    assert first.total_grounded_ops == 18
    assert all(item.entity_count == 6 for item in first.members)
    assert all(item.resolution_count == 10 for item in first.members)
    assert first == second
    assert first.receipt_digest == second.receipt_digest


def test_pack_larger_than_expanded_member_cap_is_admitted_as_bounded_members() -> None:
    build = materialize(make_tower_source(n_floors=54))
    receipt = admit_kir_candidates(build)

    assert receipt.status == STATUS_ACCEPTED
    assert receipt.member_count == 54
    assert receipt.entity_count == 324
    assert receipt.total_authored_ops == 324
    assert receipt.total_planned_ops == 324
    assert receipt.total_grounded_ops == 324
    assert receipt.entity_count > receipt.expanded_limit
    assert all(item.authored_op_count == 6 <= receipt.authored_limit
               for item in receipt.members)
    assert all(item.planned_op_count == 6 <= receipt.expanded_limit
               for item in receipt.members)


def test_receipt_digest_is_stable_across_clean_interpreters() -> None:
    script = """
from kukai.design_source.examples import make_tower_source
from kukai.design_source.materializer import materialize
from kukai.ir.design_source_admission import admit_kir_candidates
print(admit_kir_candidates(materialize(make_tower_source(n_floors=3))).receipt_digest)
"""
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(BACKEND) if not existing else str(BACKEND) + os.pathsep + existing)

    def run() -> str:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPOSITORY,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    assert run() == run()


def test_candidate_from_another_build_is_stale_and_admits_nothing() -> None:
    first = materialize(make_tower_source(project_id="project_first"))
    second = materialize(make_tower_source(project_id="project_second"))
    stale = plan_kir_candidates(first)

    receipt = admit_kir_candidates(second, stale)

    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == STALE_CANDIDATE_BUILD
    assert receipt.members == ()
    assert receipt.member_count == receipt.entity_count == 0
    assert receipt.total_planned_ops == receipt.total_grounded_ops == 0


def test_coverage_complete_forged_metadata_is_not_canonical_admission() -> None:
    build = materialize(make_tower_source(n_floors=2))
    canonical = plan_kir_candidates(build)
    forged_member = replace(
        canonical.members[0], source_instance_id="instance_forged")
    forged = replace(
        canonical,
        members=(forged_member, *canonical.members[1:]),
    )
    assert forged.status == "COMPLETE"

    receipt = admit_kir_candidates(build, forged)

    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == NONCANONICAL_CANDIDATE_SET
    assert receipt.members == ()
    assert receipt.member_count == receipt.entity_count == 0


def test_source_fidelity_is_recomputed_instead_of_trusting_valid_program_shape() -> None:
    build = materialize(make_tower_source(n_floors=1))
    canonical = plan_kir_candidates(build)
    member = canonical.members[0]
    program = member.to_program()
    wall = next(op for op in program["ops"] if op["op"] == "create_wall")
    wall["p0_mm"][0] += 1
    altered_member = replace(member, program=program)
    altered = replace(canonical, members=(altered_member,))
    assert altered.status == "COMPLETE"

    receipt = admit_kir_candidates(build, altered)

    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == NONCANONICAL_CANDIDATE_SET
    assert receipt.members == ()


def test_real_current_kir_bounds_can_refuse_coverage_complete_candidates() -> None:
    build = materialize(make_tower_source(n_floors=1, height="100001"))
    candidates = plan_kir_candidates(build)
    assert candidates.status == "COMPLETE"

    receipt = admit_kir_candidates(build, candidates)

    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == KIR_PLAN_REFUSED
    assert receipt.refusal.stage == "plan"
    assert receipt.refusal.underlying_codes == ("KIR-T002",)
    assert receipt.members == ()
    assert receipt.member_count == receipt.entity_count == 0
    assert receipt.total_authored_ops == 0
    assert receipt.total_planned_ops == receipt.total_grounded_ops == 0


def test_ground_refusal_is_typed_and_pack_admission_remains_atomic(
) -> None:
    build = materialize(make_tower_source(n_floors=3))

    def refuse_ground(_planned):
        raise KirRefusal([Diagnostic(code="KIR-G999", message_ru="fixture refusal")])

    def member_admitter(member):
        return admission._member_receipt(
            member,
            _plan_stage=admission._EXECUTE_PLAN,
            _ground_stage=refuse_ground,
        )

    receipt = _admit_with_member_stage_for_test(build, member_admitter)

    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == KIR_GROUND_REFUSED
    assert receipt.refusal.stage == "ground"
    assert receipt.refusal.underlying_codes == ("KIR-G999",)
    assert receipt.members == ()
    assert receipt.member_count == receipt.entity_count == 0


def test_planner_result_census_mismatch_is_evidence_refusal(
) -> None:
    build = materialize(make_tower_source(n_floors=3))

    def mismatched_plan(program):
        planned = admission._EXECUTE_PLAN(program)
        return replace(
            planned,
            source_op_count=planned.source_op_count + 1,
            plan_digest="",
        )

    def member_admitter(member):
        return admission._member_receipt(
            member,
            _plan_stage=mismatched_plan,
            _ground_stage=admission._EXECUTE_GROUND,
        )

    receipt = _admit_with_member_stage_for_test(build, member_admitter)

    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == EVIDENCE_MISMATCH
    assert receipt.refusal.stage == "evidence"
    assert receipt.members == ()
    assert receipt.member_count == receipt.entity_count == 0
    assert receipt.total_planned_ops == receipt.total_grounded_ops == 0


def test_ordinary_planner_global_rebind_cannot_sanitize_invalid_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = materialize(make_tower_source(n_floors=1, height="100001"))
    real_plan_program = admission.plan_program
    profile_digest = admission.ADMISSION_PROFILE_DIGEST

    def sanitizing_plan(program, *, bulk=False):
        changed = {
            **program,
            "ops": [dict(op) for op in program["ops"]],
        }
        for op in changed["ops"]:
            if op.get("op") == "create_wall":
                op["height_mm"] = min(op["height_mm"], 100000)
        return real_plan_program(changed, bulk=bulk)

    monkeypatch.setattr(admission, "plan_program", sanitizing_plan)
    receipt = admit_kir_candidates(build)

    assert admission.ADMISSION_PROFILE_DIGEST == profile_digest
    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == INTERNAL_REFUSED
    assert receipt.members == ()


def test_new_global_cannot_shadow_any_sealed_absent_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = materialize(make_tower_source(n_floors=1))
    compiler_module = sys.modules[admission.plan_program.__module__]
    assert "len" not in vars(compiler_module)

    monkeypatch.setattr(compiler_module, "len", len, raising=False)
    receipt = admit_kir_candidates(build)

    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == INTERNAL_REFUSED
    assert receipt.refusal.stage == "evidence"
    assert receipt.members == ()


def test_referenced_candidate_class_method_globals_are_sealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = materialize(make_tower_source(n_floors=1))
    candidate_module = sys.modules[admission.KirCandidateMemberV0.__module__]
    real_thaw = candidate_module.thaw

    def replacement_thaw(value):
        return real_thaw(value)

    monkeypatch.setattr(candidate_module, "thaw", replacement_thaw)
    receipt = admit_kir_candidates(build)

    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == INTERNAL_REFUSED
    assert receipt.refusal.stage == "evidence"
    assert receipt.members == ()


def test_runtime_source_artifact_path_drift_refuses_before_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = materialize(make_tower_source(n_floors=1))
    original_path = admission.__file__
    assert isinstance(original_path, str)

    monkeypatch.setattr(admission, "__file__", original_path + ".drift")
    receipt = admit_kir_candidates(build)

    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == INTERNAL_REFUSED
    assert receipt.refusal.stage == "evidence"
    assert receipt.members == ()


def test_own_seam_canonical_digest_rebind_cannot_change_accepted_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = materialize(make_tower_source(n_floors=1))
    baseline = admit_kir_candidates(build)
    assert baseline.status == STATUS_ACCEPTED
    real_canonical_digest = admission.canonical_digest
    profile = admission.ADMISSION_PROFILE_DIGEST
    runtime = admission.RUNTIME_BINDINGS_DIGEST
    own_runtime = admission.OWN_RUNTIME_BINDINGS_DIGEST

    def divergent_digest(domain, value):
        digest = real_canonical_digest(domain, value)
        if domain in {"kir.candidate-program.v0", "kir.candidate-trace.v0"}:
            replacement = "0" if digest[-1] != "0" else "1"
            return digest[:-1] + replacement
        return digest

    monkeypatch.setattr(admission, "canonical_digest", divergent_digest)
    attacked = admit_kir_candidates(build)

    assert admission.ADMISSION_PROFILE_DIGEST == profile
    assert admission.RUNTIME_BINDINGS_DIGEST == runtime
    assert admission.OWN_RUNTIME_BINDINGS_DIGEST == own_runtime
    assert attacked.status == STATUS_REFUSED
    assert attacked.refusal is not None
    assert attacked.refusal.code == INTERNAL_REFUSED
    assert attacked.refusal.stage == "evidence"
    assert attacked.members == ()


def test_dynamic_authoring_import_resolution_is_exactly_sealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = materialize(make_tower_source(n_floors=1, height="100001"))
    ir_package = sys.modules["kukai.ir"]
    permissive = SimpleNamespace(
        validate=lambda op, _name, _index, _op_id, _diags: dict(op))

    monkeypatch.setattr(ir_package, "authoring", permissive)
    receipt = admit_kir_candidates(build)

    assert receipt.status == STATUS_REFUSED
    assert receipt.refusal is not None
    assert receipt.refusal.code == INTERNAL_REFUSED
    assert receipt.refusal.stage == "evidence"
    assert receipt.members == ()


def test_runtime_import_manifest_names_dynamic_authoring_resolution() -> None:
    assert ("kukai.ir", ("authoring",)) in admission.RUNTIME_IMPORT_MANIFEST
    assert (
        "kukai.ir.authoring_validation",
        ("reject_zero_length",),
    ) in admission.RUNTIME_IMPORT_MANIFEST
    assert ("kukai.ir.midend", ("GroundedProgram", "PlannedProgram")) in (
        admission.RUNTIME_IMPORT_MANIFEST)


def test_receipt_minter_is_not_extractable_or_reusable_for_forgery() -> None:
    admitted = admit_kir_candidates(
        materialize(make_tower_source(n_floors=1)))
    assert admitted.status == STATUS_ACCEPTED

    assert "_RECEIPT_CAPABILITY" not in vars(admission)
    assert "_RECEIPT_MINTER" not in vars(admission)
    assert "_make_receipt_minter" not in vars(admission)
    assert "_capability" not in vars(admission.KirAdmissionReceiptV0)
    assert all(
        not any(type(item) is object for item in (value.__defaults__ or ()))
        for value in vars(admission).values()
        if isinstance(value, FunctionType)
    )

    with pytest.raises(ValueError, match="no public constructor"):
        admission.KirAdmissionReceiptV0(
            status=admitted.status,
            build_digest=admitted.build_digest,
            requested_candidate_set_digest=admitted.requested_candidate_set_digest,
            canonical_partition_plan_digest=(
                admitted.canonical_partition_plan_digest),
            canonical_candidate_set_digest=admitted.canonical_candidate_set_digest,
            member_count=admitted.member_count,
            entity_count=admitted.entity_count,
            total_authored_ops=admitted.total_authored_ops,
            total_planned_ops=admitted.total_planned_ops,
            total_grounded_ops=admitted.total_grounded_ops,
            members=admitted.members,
            refusal=None,
            admission_profile_digest=admission.ADMISSION_PROFILE_DIGEST,
            runtime_bindings_digest=admission.RUNTIME_BINDINGS_DIGEST,
            own_runtime_bindings_digest=admission.OWN_RUNTIME_BINDINGS_DIGEST,
        )
    with pytest.raises(ValueError, match="no public constructor"):
        replace(
            admitted,
            build_digest="sha256:" + "0" * 64,
            canonical_candidate_set_digest="sha256:" + "1" * 64,
        )


def test_ephemeral_receipt_refuses_standard_copy_and_pickle_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admitted = admit_kir_candidates(
        materialize(make_tower_source(n_floors=1)))
    assert admitted.status == STATUS_ACCEPTED
    assert admitted.to_data()["status"] == STATUS_ACCEPTED
    assert not ({"from_data", "from_dict", "parse", "loads"} &
                set(vars(admission.KirAdmissionReceiptV0)))

    with pytest.raises(TypeError, match="cannot be copied or reconstructed"):
        copy.copy(admitted)
    with pytest.raises(TypeError, match="cannot be copied or reconstructed"):
        copy.deepcopy(admitted)
    with pytest.raises(TypeError, match="cannot be serialized or reconstructed"):
        admitted.__reduce__()
    with pytest.raises(TypeError, match="cannot be serialized or reconstructed"):
        admitted.__reduce_ex__(pickle.HIGHEST_PROTOCOL)

    legacy_state = [
        getattr(admitted, item.name)
        for item in fields(admitted)
    ]
    cross_process_payload: bytes | None = None

    for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
        with pytest.raises(
            TypeError, match="cannot be serialized or reconstructed"
        ):
            pickle.dumps(admitted, protocol=protocol)
        with monkeypatch.context() as legacy_pickle:
            legacy_pickle.setattr(
                admission.KirAdmissionReceiptV0,
                "__reduce__",
                object.__reduce__,
            )
            legacy_pickle.setattr(
                admission.KirAdmissionReceiptV0,
                "__reduce_ex__",
                object.__reduce_ex__,
            )
            legacy_pickle.setattr(
                admission.KirAdmissionReceiptV0,
                "__getstate__",
                lambda _receipt: legacy_state,
            )
            legacy_payload = pickle.dumps(admitted, protocol=protocol)
        if protocol == 0:
            cross_process_payload = legacy_payload
        with pytest.raises(
            (TypeError, ValueError), match="reconstructed|readback"
        ):
            pickle.loads(legacy_payload)

    assert cross_process_payload is not None
    encoded_payload = base64.b64encode(cross_process_payload).decode("ascii")
    script = """
import base64
import pickle
import sys
from kukai.ir import design_source_admission

try:
    pickle.loads(base64.b64decode(sys.argv[1].encode("ascii")))
except (TypeError, ValueError) as exc:
    if "reconstructed" not in str(exc) and "readback" not in str(exc):
        raise
else:
    raise AssertionError("legacy receipt unexpectedly reconstructed")
print("REFUSED")
"""
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(BACKEND) if not existing else str(BACKEND) + os.pathsep + existing)
    completed = subprocess.run(
        [sys.executable, "-c", script, encoded_payload],
        cwd=REPOSITORY,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "REFUSED"


def test_transitive_midend_digest_global_rebind_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = materialize(make_tower_source(n_floors=1))
    midend_module = sys.modules["kukai.ir.midend"]
    real_canonical_json = midend_module._canonical_json
    profile = admission.ADMISSION_PROFILE_DIGEST
    runtime = admission.RUNTIME_BINDINGS_DIGEST
    own_runtime = admission.OWN_RUNTIME_BINDINGS_DIGEST

    def divergent_canonical_json(value):
        return real_canonical_json(value) + " "

    monkeypatch.setattr(
        midend_module, "_canonical_json", divergent_canonical_json)
    attacked = admit_kir_candidates(build)

    assert admission.ADMISSION_PROFILE_DIGEST == profile
    assert admission.RUNTIME_BINDINGS_DIGEST == runtime
    assert admission.OWN_RUNTIME_BINDINGS_DIGEST == own_runtime
    assert attacked.status == STATUS_REFUSED
    assert attacked.refusal is not None
    assert attacked.refusal.code == INTERNAL_REFUSED
    assert attacked.refusal.stage == "evidence"
    assert attacked.members == ()


def test_referenced_hashlib_sha256_module_attribute_rebind_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = materialize(make_tower_source(n_floors=1))
    hashlib_module = sys.modules["hashlib"]
    real_sha256 = hashlib_module.sha256
    profile = admission.ADMISSION_PROFILE_DIGEST
    runtime = admission.RUNTIME_BINDINGS_DIGEST
    own_runtime = admission.OWN_RUNTIME_BINDINGS_DIGEST

    def divergent_sha256(data=b"", *args, **kwargs):
        return real_sha256(data + b"\0", *args, **kwargs)

    monkeypatch.setattr(hashlib_module, "sha256", divergent_sha256)
    attacked = admit_kir_candidates(build)

    assert ("hashlib", ("sha256",)) in (
        admission.RUNTIME_MODULE_ATTRIBUTE_MANIFEST)
    assert admission.ADMISSION_PROFILE_DIGEST == profile
    assert admission.RUNTIME_BINDINGS_DIGEST == runtime
    assert admission.OWN_RUNTIME_BINDINGS_DIGEST == own_runtime
    assert attacked.status == STATUS_REFUSED
    assert attacked.refusal is not None
    assert attacked.refusal.code == INTERNAL_REFUSED
    assert attacked.refusal.stage == "evidence"
    assert attacked.members == ()


def test_second_referenced_module_attribute_rebind_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = materialize(make_tower_source(n_floors=1))
    json_module = sys.modules["json"]
    real_dumps = json_module.dumps
    profile = admission.ADMISSION_PROFILE_DIGEST
    runtime = admission.RUNTIME_BINDINGS_DIGEST

    def divergent_dumps(value, *args, **kwargs):
        return real_dumps(value, *args, **kwargs) + " "

    monkeypatch.setattr(json_module, "dumps", divergent_dumps)
    attacked = admit_kir_candidates(build)

    assert ("json", ("dumps",)) in (
        admission.RUNTIME_MODULE_ATTRIBUTE_MANIFEST)
    assert admission.ADMISSION_PROFILE_DIGEST == profile
    assert admission.RUNTIME_BINDINGS_DIGEST == runtime
    assert attacked.status == STATUS_REFUSED
    assert attacked.refusal is not None
    assert attacked.refusal.code == INTERNAL_REFUSED
    assert attacked.refusal.stage == "evidence"
    assert attacked.members == ()


def test_local_import_alias_module_attribute_rebind_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = materialize(make_tower_source(n_floors=1))
    real_deepcopy = copy.deepcopy
    profile = admission.ADMISSION_PROFILE_DIGEST
    runtime = admission.RUNTIME_BINDINGS_DIGEST
    own_runtime = admission.OWN_RUNTIME_BINDINGS_DIGEST

    def divergent_deepcopy(value, memo=None, _nil=[]):
        return real_deepcopy(value, memo, _nil)

    monkeypatch.setattr(copy, "deepcopy", divergent_deepcopy)
    attacked = admit_kir_candidates(build)

    assert ("copy", ("deepcopy",)) in (
        admission.RUNTIME_MODULE_ATTRIBUTE_MANIFEST)
    assert admission.ADMISSION_PROFILE_DIGEST == profile
    assert admission.RUNTIME_BINDINGS_DIGEST == runtime
    assert admission.OWN_RUNTIME_BINDINGS_DIGEST == own_runtime
    assert attacked.status == STATUS_REFUSED
    assert attacked.refusal is not None
    assert attacked.refusal.code == INTERNAL_REFUSED
    assert attacked.refusal.stage == "evidence"
    assert attacked.members == ()


def test_required_member_evidence_digest_cannot_be_none() -> None:
    receipt = admit_kir_candidates(
        materialize(make_tower_source(n_floors=1)))
    assert receipt.status == STATUS_ACCEPTED
    with pytest.raises(ValueError, match="candidate_digest is required"):
        replace(receipt.members[0], candidate_digest=None)


def test_admission_seam_is_offline_and_unreachable_from_runtime_entrypoints() -> None:
    module_path = BACKEND / "kukai" / "ir" / "design_source_admission.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    forbidden_imports = (
        "kukai.api",
        "kukai.ir.serving",
        "kukai.live",
        "requests",
        "httpx",
        "socket",
        "subprocess",
    )
    imported: list[str] = []
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)
    assert not [name for name in imported if name.startswith(forbidden_imports)]
    assert not ({"compile_program", "lower_program", "emit_program", "dispatch"}
                & set(calls))

    entrypoints = (
        BACKEND / "kukai" / "main.py",
        BACKEND / "kukai" / "ir" / "serving.py",
        *(BACKEND / "kukai" / "api").glob("*.py"),
    )
    assert all(
        "design_source_admission" not in path.read_text(
            encoding="utf-8", errors="replace")
        for path in entrypoints
    )
