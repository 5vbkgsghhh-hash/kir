"""Identity-guard forwarding, not native identity capture or freshness proof."""
from dataclasses import replace
from hashlib import sha256

import pytest

from kir import compile_program
from kir.contracts import ElementIdentityProof
from kir.emit_core import MODEL_BINDING_GUARD_VERSION
from kir import revit_connector as native
from kir.saved_execution import SavedExecutionRecord
from kir.tests.test_revit_connector_preparation import OPERATION, target


MUTATION = {"ops": [{"op": "set_param", "id": "edit", "param": "Comments",
                     "target": {"by": "element_id", "value": 700}, "value": "reviewed"}]}
PROOF = ElementIdentityProof(700, "original-element-700", "a" * 32)
CONDITION = native.ContextPrecondition("observed-document", 17)


def prepare(identities, *, version="2023", program=MUTATION):
    return native.prepare_execution(program, target=target(version), precondition=CONDITION,
                                    operation_id=OPERATION, expected_identities=identities)


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_existing_guard_is_in_exact_source_before_mutation_and_inside_transaction(version):
    artifact = prepare([PROOF], version=version)
    compiled = compile_program(MUTATION, revit_version=version, expected_identities=(PROOF,))
    assert compiled.ok, compiled.diagnostics
    assert artifact.source == native.wrap_connector_source(compiled.csharp)
    assert artifact.source_sha256 == sha256(artifact.source.encode()).hexdigest()
    assert artifact.precondition is CONDITION  # no fresh-context substitution
    assert artifact.source.index("__t.Start()") < artifact.source.index(PROOF.unique_id)
    assert artifact.source.index(PROOF.unique_id) < artifact.source.index("// set_param edit")
    assert "__t.RollBack(); return __Refuse" in artifact.source
    # 🔴 THE GUARD IS NAMED BY ITS OWN MARKER, NOT BY `VersionGuid` (13.09.2026).
    # This line used to assert the version capture as a stand-in for "the guard
    # is here"; the version half is now opt-in and absent by default, so the
    # stand-in stopped meaning anything. What the test is actually about — an
    # identity guard, inside the transaction, before the mutation — is asserted
    # directly above and here.
    assert MODEL_BINDING_GUARD_VERSION in artifact.source
    assert "identity_changed_since_read" in artifact.source
    assert 'VersionGuid.ToString("N")' not in artifact.source.split("// set_param edit")[0]
    assert "doc.PathName" not in artifact.source


def test_preparation_freezes_caller_sequence_before_forwarding(monkeypatch):
    identities = [PROOF]
    actual_compile = native.compile_program
    observed = []

    def compile_and_change_caller(*args, **kwargs):
        observed.append(kwargs["expected_identities"])
        identities.clear()
        return actual_compile(*args, **kwargs)

    monkeypatch.setattr(native, "compile_program", compile_and_change_caller)
    artifact = prepare(identities)
    assert observed == [(PROOF,)]
    assert not identities
    assert PROOF.unique_id in artifact.source
    assert artifact.expected_identities == (PROOF,)


@pytest.mark.parametrize("identities", ["bad", b"bad", {}, 1, True, [PROOF.to_dict()], [None]])
def test_invalid_guard_carrier_is_refused_before_compilation(identities, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid guard carrier reached compiler")

    monkeypatch.setattr(native, "compile_program", unexpected)
    with pytest.raises(native.ConnectorPreparationError, match="invalid_identities"):
        prepare(identities)


def test_conflicting_identities_do_not_get_a_prepared_artifact():
    with pytest.raises(native.ConnectorPreparationError, match="compile_refused"):
        prepare([PROOF, replace(PROOF, unique_id="replacement-element-700")])


def test_duplicate_and_reordered_guards_keep_existing_compiler_canonicalization():
    other = ElementIdentityProof(701, "protected-element-701", "b" * 32)
    assert prepare([PROOF, other, PROOF]).source == prepare([other, PROOF]).source


@pytest.mark.parametrize("identities", [(PROOF,), ()])
def test_query_cannot_silently_ignore_explicit_identity_guards(identities):
    query = {"ops": [{"op": "query_inspect", "id": "read",
                       "target": {"by": "element_id", "value": 700}}]}
    with pytest.raises(native.ConnectorPreparationError, match="identity_guard_requires_write"):
        prepare(identities, program=query)
    assert prepare(None, program=query).planned.family.value == "query"


def test_default_and_empty_write_guards_preserve_ordinary_source():
    ordinary = native.prepare_execution(MUTATION, target=target(), precondition=CONDITION,
                                        operation_id=OPERATION)
    assert prepare(None).source == prepare(()).source == ordinary.source
    assert ordinary.source_sha256 != prepare([PROOF]).source_sha256
    assert ordinary.expected_identities == ()


def test_retaining_guard_inputs_does_not_rewrite_existing_archive_wire():
    from kir.saved_execution import _capture
    from kir.tests.test_revit_connector_preparation import prepare as original_fixture

    # Captured before adding PreparedExecution.expected_identities. This is
    # storage compatibility, not evidence that native source was executed.
    assert sha256(_capture(original_fixture())).hexdigest() == "26344194ae90e87be276649e4f9d21c0929fa5a35dfee90742d5023add809f14"


def test_archive_retains_exact_guard_and_refuses_another_identity(tmp_path):
    original = prepare([PROOF])
    SavedExecutionRecord.create_new(tmp_path / "execution.sqlite", original)
    loaded = SavedExecutionRecord.load(tmp_path / "execution.sqlite")
    loaded.require_matches(original)
    changed = prepare([replace(PROOF, unique_id="another-element")])
    assert changed.planned.plan_digest == original.planned.plan_digest
    assert changed.source_sha256 != original.source_sha256
    with pytest.raises(ValueError):
        loaded.require_matches(changed)
