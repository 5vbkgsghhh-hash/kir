"""Pure compiler/target/request preparation, not an executing transport stub."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from uuid import uuid4

import pytest

from kir import compile_program, plan_program
from kir import revit_connector as native


JOURNAL = "eeb83714-4c16-46a1-ad89-c08d4b6320fa"
INSTANCE = "c8a0f1c7-b597-4e76-8b1a-cd516c7d6a23"
OPERATION = "a7446949-0dc2-4f62-aade-de6e011b2029"
PROGRAM = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0, "name": "Ground"}]}


def target(version="2023"):
    return native.RuntimeTarget(JOURNAL, INSTANCE, version)


def credentials(runtime=None):
    return native.SessionCredentials(runtime or target(), str(uuid4()), "secret-session-credential")


def prepare(program=None, *, runtime=None, condition=None, operation=OPERATION):
    return native.prepare_execution(deepcopy(PROGRAM) if program is None else program,
        target=runtime or target(), precondition=condition or native.ContextPrecondition("opaque-document-A", 7),
        operation_id=operation)


def test_preparation_uses_exact_plan_full_source_and_target_year_without_legacy_guard():
    plan = plan_program(PROGRAM)
    artifact = prepare(plan)
    ordinary = compile_program(plan, revit_version="2023")
    assert artifact.planned is plan
    assert artifact.grounded.planned.plan_digest == plan.plan_digest
    assert artifact.source == native.wrap_connector_source(ordinary.csharp)
    assert artifact.source_sha256 == hashlib.sha256(artifact.source.encode()).hexdigest()
    assert "namespace Kir.Generated" in artifact.source
    assert "public static object Execute(Document doc, UIDocument uidoc)" in artifact.source
    assert "doc.PathName" not in artifact.source
    assert artifact.target.revit_version == "2023"
    assert "secret-session-credential" not in repr(artifact)
    assert "namespace Kir.Generated" not in repr(artifact)


def test_session_rotation_keeps_exact_operation_and_source_binding():
    artifact = prepare()
    before = artifact.binding_dict()
    first, second = credentials(), credentials()
    a = artifact.execute_request(first, request_id=str(uuid4()))
    b = artifact.execute_request(second, request_id=str(uuid4()))
    assert a["session_id"] != b["session_id"]
    assert a["protocol"] == "kir-revit-connector/4"
    for key in ("target", "operation_id", "source", "source_sha256", "precondition"):
        assert a[key] == b[key]
    assert artifact.binding_dict() == before
    assert "token" not in before and "session_id" not in before
    assert first.token not in repr(first)
    assert a["token"] == first.token


@pytest.mark.parametrize("field,value", [("journal_id", str(uuid4())),
                                        ("instance_id", str(uuid4())), ("revit_version", "2026")])
def test_foreign_runtime_cannot_receive_original_execution_or_receipt_lookup(field, value):
    artifact = prepare()
    foreign = credentials(replace(target(), **{field: value}))
    for request in (artifact.execute_request, artifact.receipt_request):
        with pytest.raises(native.ConnectorPreparationError, match="target_mismatch"):
            request(foreign, request_id=str(uuid4()))
    recovered = artifact.recovery_request(foreign, request_id=str(uuid4()))
    assert recovered["kind"] == "recover_receipt"
    assert recovered["target"] == foreign.target.to_dict()
    assert recovered["recovery_target"] == artifact.target.to_dict()
    assert recovered["operation_id"] == artifact.operation_id
    assert "source" not in recovered and "source_sha256" not in recovered


def test_exported_mutations_do_not_retarget_prepared_operation():
    artifact, auth = prepare(), credentials()
    source_hash = artifact.source_sha256
    request = artifact.execute_request(auth, request_id=str(uuid4()))
    request["target"]["journal_id"] = str(uuid4())
    request["precondition"]["revision"] = 999
    request["source"] = "forged source"
    binding = artifact.binding_dict()
    binding["target"]["instance_id"] = str(uuid4())
    again = artifact.execute_request(auth, request_id=str(uuid4()))
    assert again["target"] == target().to_dict()
    assert again["precondition"]["revision"] == 7
    assert again["source_sha256"] == source_hash
    assert again["source"] == artifact.source
    with pytest.raises(FrozenInstanceError):
        artifact.source = "modified"
    with pytest.raises(TypeError, match="prepare_execution"):
        native.PreparedExecution()


@pytest.mark.parametrize("view,selection", [(None, None), (0, ""), (-1, "a" * 64)])
def test_precondition_preserves_null_vs_empty_zero_and_exact_integer_bounds(view, selection):
    condition = native.ContextPrecondition(" doc-key ", (1 << 63) - 1, view, selection)
    artifact = prepare(condition=condition)
    request = artifact.execute_request(credentials(), request_id=str(uuid4()))
    assert request["precondition"] == {"document_key": " doc-key ", "revision": (1 << 63) - 1,
                                        "active_view_id": view, "selection_digest": selection}


@pytest.mark.parametrize("field,value", [("revision", None), ("revision", True), ("revision", -1),
    ("revision", 1.0), ("revision", 1 << 63), ("document_key", " "), ("document_key", "\ud800"),
    ("active_view_id", False), ("active_view_id", 1 << 63), ("selection_digest", []),
    ("selection_digest", "\ud800")])
def test_malformed_context_is_a_named_refusal(field, value):
    values = {"document_key": "A", "revision": 0, field: value}
    with pytest.raises(native.ConnectorPreparationError, match="invalid_input"):
        native.ContextPrecondition(**values)


@pytest.mark.parametrize("field,value", [("journal_id", "bad"), ("instance_id", ""),
    ("instance_id", "00000000-0000-0000-0000-000000000000"), ("revit_version", "2020"),
    ("revit_version", 2023), ("revit_version", [])])
def test_malformed_runtime_identity_is_a_named_refusal(field, value):
    with pytest.raises(native.ConnectorPreparationError):
        replace(target(), **{field: value})


def test_uuid_aliases_are_one_binding_and_program_mutation_cannot_rewrite_source():
    program = deepcopy(PROGRAM)
    artifact = prepare(program, runtime=native.RuntimeTarget(JOURNAL.upper(), INSTANCE.upper(), "2023"),
                       operation="{" + OPERATION.upper() + "}")
    program["ops"][0]["elev_mm"] = 2000
    assert artifact.operation_id == OPERATION and artifact.target == target()
    assert artifact.planned.to_ops()[0]["elev_mm"] == 0
    assert prepare(program).source_sha256 != artifact.source_sha256


def test_malformed_program_does_not_produce_an_execution_request():
    with pytest.raises(native.ConnectorPreparationError, match="compile_refused") as error:
        prepare({"ops": [{"op": "invented_native_api", "id": "bad"}]})
    assert error.value.diagnostics


def test_floor_hole_version_refusal_is_preserved_in_native_preparation():
    from examples.residential_project import concept, develop_section
    project = develop_section(concept())
    with pytest.raises(native.ConnectorPreparationError, match="compile_refused") as error:
        prepare(project.to_program(), runtime=target("2021"))
    assert any(d.code == "KIR-E003" for d in error.value.diagnostics)
    assert prepare(project.to_program(), runtime=target("2023")).planned


def test_prepared_plan_cannot_silently_change_its_bulk_policy():
    plan = plan_program(PROGRAM, bulk=True)
    with pytest.raises(native.ConnectorPreparationError, match="compile_refused") as error:
        prepare(plan)
    assert any(d.code == "KIR-L005" for d in error.value.diagnostics)
    artifact = native.prepare_execution(plan, target=target(), precondition=native.ContextPrecondition("A", 0),
                                        operation_id=OPERATION, bulk=True)
    assert artifact.planned is plan


def test_utf16_source_budget_counts_astral_characters_as_two(monkeypatch):
    artifact = prepare({"ops": [{**PROGRAM["ops"][0], "name": "Ground 😀😀"}]})
    assert len(artifact.source.encode("utf-16-le")) // 2 > len(artifact.source)
    monkeypatch.setattr(native, "MAX_SOURCE_CHARS", len(artifact.source))
    with pytest.raises(native.ConnectorPreparationError, match="source_budget_exceeded"):
        prepare({"ops": [{**PROGRAM["ops"][0], "name": "Ground 😀😀"}]})


def test_frame_budget_measures_actual_utf8_request_with_credentials(monkeypatch):
    artifact, auth = prepare(), credentials()
    request_id = str(uuid4())
    request = artifact.execute_request(auth, request_id=request_id)
    size = len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode())
    monkeypatch.setattr(native, "MAX_FRAME_BYTES", size)
    assert artifact.execute_request(auth, request_id=request_id) == request
    monkeypatch.setattr(native, "MAX_FRAME_BYTES", size - 1)
    with pytest.raises(native.ConnectorPreparationError, match="frame_budget_exceeded"):
        artifact.execute_request(auth, request_id=request_id)


@pytest.mark.parametrize("timeout", [True, 1.0, 0, -1, 300001])
def test_invalid_dispatch_budget_cannot_be_serialized(timeout):
    with pytest.raises(native.ConnectorPreparationError, match="invalid_input"):
        prepare().execute_request(credentials(), request_id=str(uuid4()), timeout_ms=timeout)


def test_an_op_that_needs_a_second_document_is_refused_by_name_before_anything_is_built():
    """The refusal happens here, not as a policy receipt from the other
    end of the wire.

    Standalone binds EXACTLY ONE document, and the `CodePolicy.cs` barrier
    does not even let generated code name a second one. Before this fix,
    preparing three such ops succeeded: the artifact was assembled, sent,
    and got back a diagnostic about `Application.Documents` — that is, the
    author was told about a Revit API member instead of their own op.
    """
    from kir import diag

    spec = diag.CODES[native.CONNECTOR_SECOND_DOCUMENT_UNAVAILABLE]
    assert spec.blame == "environment", "чинит не автор: второго документа нет у СРЕДЫ"
    assert spec.taxonomy == "KIR_PRECONDITION_UNMET", "отказ ДО отправки — эффекта не было"

    program = {"ops": [{"op": "transfer_material", "id": "MT1",
                        "source_document": "Каталог", "name": "Бетон М300"}]}
    with pytest.raises(native.ConnectorPreparationError) as refusal:
        prepare(program)
    assert refusal.value.code == native.CONNECTOR_SECOND_DOCUMENT_UNAVAILABLE
    assert "второго документа" in str(refusal.value)
    assert "transfer_material" in str(refusal.value), "назван ОП, а не член Revit API"

    # The list is closed and named explicitly: a silent extension will
    # break the pin.
    assert sorted(native.SECOND_DOCUMENT_OPS) == [
        "author_family", "transfer_family", "transfer_material"]

    # Anti-Goodhart: a gate that refuses everything would pass the check
    # above.
    ordinary = prepare()
    assert ordinary.source_sha256 and "create_level" not in native.SECOND_DOCUMENT_OPS

    # A defect-reversion control: with an empty list, the same op is
    # prepared again, meaning the pin guards the gate, not itself.
    saved = native.SECOND_DOCUMENT_OPS
    native.SECOND_DOCUMENT_OPS = frozenset()
    try:
        assert prepare(program).source_sha256
    finally:
        native.SECOND_DOCUMENT_OPS = saved
