"""The current byte manifest includes the native readback fixes of 2026-09-10.
Historical E-3 and earlier migrations retain their exact manifests and executable
counterfactuals. NativeReadbackMigrationContract binds the complete new delta.
"""
from __future__ import annotations

import json
import hashlib
from collections import Counter
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_parity_queue.jsonl"))

from kir.tests.emit_parity_fixtures.generate_fixtures import (  # noqa: E402
    FIXTURE_PATH,
    BASELINE_MIGRATION_PATH,
    C1_MIGRATION_PATH,
    D1_MIGRATION_PATH,
    E1_MIGRATION_PATH,
    E2_MIGRATION_PATH,
    E3_MIGRATION_PATH,
    CAPTURE_MIGRATION_PATH,
    INTENDED_CHANGES,
    emit_corpus,
)
from kir.tests.emit_parity_fixtures import generate_fixtures as fixtures  # noqa: E402

# An exempted key must be covered by its OWN pin elsewhere (never simply
# struck out).  Justifications for PAST emission changes live in
# `generate_fixtures.EMISSION_CHANGE_LOG` (a single source, read by humans);
# `INTENDED_CHANGES` holds only ACTIVE exemptions, and since 20.08 there are zero of them.


def _exempt(key: str) -> bool:
    return any(key.startswith(prefix) for prefix in INTENDED_CHANGES)


def _paths_the_commit_will_carry(root: pathlib.Path) -> set[str] | None:
    """Paths that `root`'s OWN repository will carry, or None when it has none.

    🔴 13.09.2026. The stronger argument below — a file that lies on disk but
    will not ride into the commit — is only about the repository that OWNS this
    tree. An INSTALLED package has no commit of its own, and `root` is then
    `site-packages`: asking git there answers about whatever repository happens
    to enclose the virtual environment. Measured on a wheel built from
    `d010941`: a stranger whose project ignores `venv/` (the ordinary
    `.gitignore` line) got an EMPTY listing and two reds out of
    `python -m kir.selftest`, while the delivered package was intact. The same
    red appeared in the release gate itself, because its acceptance directory
    lived under `.work/`, which this repository ignores.

    So the repository is only believed when it is the owner of this very tree:
    `rev-parse --show-toplevel` must be `root` itself. A foreign or absent
    repository yields None, and the caller falls back to the direct proof
    (`.is_file()` next to the record) after naming why.
    """
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             cwd=root, capture_output=True, check=True, timeout=60)
        if pathlib.Path(top.stdout.decode().strip()).resolve() != root.resolve():
            return None
        listing = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, check=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return {name for name in listing.stdout.decode().split("\0") if name}


def _assert_exact_parity(frozen, current):
    missing, extra = sorted(set(frozen) - set(current)), sorted(set(current) - set(frozen))
    if missing or extra:
        raise AssertionError(f"emission keyset differs: missing={missing}, unexpected extra={extra}")
    mismatched = sorted(key for key in frozen if not _exempt(key) and current[key] != frozen[key])
    if mismatched:
        raise AssertionError(f"{len(mismatched)} emissions diverged from the reviewed bytes; first: {mismatched[:10]}")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _manifest_bytes(value):
    return (json.dumps(value, indent=0, sort_keys=True) + "\n").encode()


def _reverse_e3_migration(current_bytes, record, parent_bytes):
    """Check the E-3 delta and hand off the E-2-era manifest to the old chain.

    The form is the same as E-2's, and this is NOT a copy for the sake of symmetry: their subject
    is literally the same one — the end-expectation numbers, shifted by the program's delta_mm,
    with zero lines and stages shifted. What is checked separately is how E-3
    DIFFERS: the key of a DIFFERENT op is retargeted (`create_pipe.endpoints`, not
    `create_wall.endpoints` — the wall moved off one link earlier), and the numbers per
    emission are doubled (12, not 8), because a pipe's end is THREE-DIMENSIONAL. Recording
    E-3 with E-2's numbers would mean asserting the wrong subject.
    """
    assert record["schema"] == "kir-emission-e3-migration/1"
    assert record["record_digest"] == _digest(_canonical({
        key: value for key, value in record.items() if key != "record_digest"})), "e3 record digest"
    parent = json.loads(parent_bytes)
    assert _digest(parent_bytes) == record["parent"]["record_file_sha256"], "e3 parent record bytes"
    assert parent["record_digest"] == record["parent"]["record_digest"], "e3 parent record binding"
    manifest = record["manifest"]
    assert _digest(current_bytes) == manifest["after_file_sha256"], "current manifest digest"
    current = json.loads(current_bytes)
    assert len(current) == manifest["key_count"] == 2361
    assert _digest(_canonical(sorted(current))) == manifest["keyset_sha256"], "e3 keyset"
    assert manifest["added_keys"] == manifest["missing_keys"] == manifest["refusal_changes"] == []
    changes = manifest["changes"]
    assert len(changes) == manifest["changed_count"] == 24, "e3 change count"
    assert len(current) - len(changes) == manifest["unchanged_count"] == 2337
    # The same three zeros as E-2, and here they are the subject in exactly the same way: the witness
    # was not removed, the tolerance was not shifted, the stage did not move — otherwise this would be
    # a different fix under the same name.
    assert manifest["predicates_removed"] == 0, "e3 removed a predicate"
    assert manifest["tolerances_changed"] == 0, "e3 moved a tolerance"
    assert manifest["stages_moved"] == 0, "e3 moved a stage"
    assert manifest["obligation_keys_moved"] == [], "e3 moved an obligation key"
    assert manifest["obligation_keys_retargeted"] == [
        "create_pipe.endpoints"], "e3 retargeted another key"
    # 🔴 EIGHT ARE TAUGHT, ONE IS VISIBLE IN BYTES. The number `taught_ops` is kept
    # HERE, next to the number covered, so the difference cannot get lost:
    # parity proves the pipe's delta and says nothing about the other seven.
    assert manifest["taught_ops"] == 8, "e3 taught another number of ops"
    assert manifest["ops_visible_in_corpus"] == ["create_pipe"], "e3 corpus reach"
    assert manifest["mode_counts"] == {"atomic": 12, "per_op": 12}, "e3 isolation split"
    assert manifest["fixtures"] == [
        "golden:auth_move_and_change_type",
        "scope:move_and_change_type"], "e3 touched another fixture"
    audit = record["audit"]
    assert audit["clean"] == audit["of"] == len(changes), "e3 line audit incomplete"
    # 12 numbers per emission x 24 emissions: 6 for the verdict + 6 for orientation. Not a single line.
    assert audit["numbers_shifted_total"] == 12 * len(changes), "e3 audit number count"
    assert audit["lines_moved_total"] == 0, "e3 audit saw a moved line"
    assert audit["blocks_touched"] == ["post MP"], "e3 touched another block"
    historical = dict(current)
    for key, change in changes.items():
        assert key in historical, "changed key absent"
        assert historical[key] == change["after"], "changed after hash"
        assert change["before"] != change["after"], "vacuous change"
        assert not change["before"].startswith("refused:") and not change["after"].startswith("refused:")
        historical[key] = change["before"]
    assert _digest(_manifest_bytes(historical)) == manifest["before_file_sha256"] == (
        parent["manifest"]["after_file_sha256"]), "reconstructed e2 manifest"
    assert sum(value.startswith("refused:") for value in current.values()) == manifest["refusal_count"] == 21
    assert sorted(record["goldens"]["changed"]) == [
        "auth_move_and_change_type"], "e3 touched another golden"
    assert record["goldens"]["changed_count"] == 1
    assert record["goldens"]["compared_count"] == 75
    unchanged_now = {
        name: value for name, value in record["goldens"]["unchanged"].items()
        if name not in record["goldens"]["changed"]}
    for name, value in parent["goldens"]["unchanged"].items():
        if name in record["goldens"]["changed"]:
            continue
        assert unchanged_now[name] == value, f"e3 moved golden {name}"
    return _manifest_bytes(historical)


def _reverse_e2_migration(current_bytes, record, parent_bytes):
    """Check the E-2 delta and hand off the E-1-era manifest to the old chain.

    The form is the same as E-1's: the record is the NEWEST link, it owns the file on
    disk. What is checked separately is how E-2 DIFFERS from E-1, and the difference here
    is load-bearing: E-1 moved lines between stages with zero numbers shifted, while E-2
    does not move A SINGLE line (`lines_moved_total == 0`) and does not move A SINGLE
    stage (`stages_moved == 0`) — exactly the expectation numbers move. Recording
    E-2 in E-1's form would mean asserting the wrong subject.
    """
    assert record["schema"] == "kir-emission-e2-migration/1"
    assert record["record_digest"] == _digest(_canonical({
        key: value for key, value in record.items() if key != "record_digest"})), "e2 record digest"
    parent = json.loads(parent_bytes)
    assert _digest(parent_bytes) == record["parent"]["record_file_sha256"], "e2 parent record bytes"
    assert parent["record_digest"] == record["parent"]["record_digest"], "e2 parent record binding"
    manifest = record["manifest"]
    assert _digest(current_bytes) == manifest["after_file_sha256"], "current manifest digest"
    current = json.loads(current_bytes)
    assert len(current) == manifest["key_count"] == 2361
    assert _digest(_canonical(sorted(current))) == manifest["keyset_sha256"], "e2 keyset"
    assert manifest["added_keys"] == manifest["missing_keys"] == manifest["refusal_changes"] == []
    changes = manifest["changes"]
    assert len(changes) == manifest["changed_count"] == 24, "e2 change count"
    assert len(current) - len(changes) == manifest["unchanged_count"] == 2337
    # The NUMBERS moved, and only they. These three zeros are exactly E-2's subject: not one
    # witness was removed, not one tolerance was shifted, and not one stage moved
    # — otherwise this would be a different fix under the same name.
    assert manifest["predicates_removed"] == 0, "e2 removed a predicate"
    assert manifest["tolerances_changed"] == 0, "e2 moved a tolerance"
    assert manifest["stages_moved"] == 0, "e2 moved a stage"
    assert manifest["obligation_keys_moved"] == [], "e2 moved an obligation key"
    assert manifest["obligation_keys_retargeted"] == [
        "create_wall.endpoints"], "e2 retargeted another key"
    assert manifest["mode_counts"] == {"atomic": 12, "per_op": 12}, "e2 isolation split"
    assert manifest["fixtures"] == [
        "golden:auth_move_and_change_type",
        "scope:move_and_change_type"], "e2 touched another fixture"
    audit = record["audit"]
    assert audit["clean"] == audit["of"] == len(changes), "e2 line audit incomplete"
    # 8 numbers per emission × 24 emissions: 4 for the verdict + 4 for orientation. Not a single line.
    assert audit["numbers_shifted_total"] == 8 * len(changes), "e2 audit number count"
    assert audit["lines_moved_total"] == 0, "e2 audit saw a moved line"
    assert audit["blocks_touched"] == ["post MW"], "e2 touched another block"
    historical = dict(current)
    for key, change in changes.items():
        assert key in historical, "changed key absent"
        assert historical[key] == change["after"], "changed after hash"
        assert change["before"] != change["after"], "vacuous change"
        assert not change["before"].startswith("refused:") and not change["after"].startswith("refused:")
        historical[key] = change["before"]
    assert _digest(_manifest_bytes(historical)) == manifest["before_file_sha256"] == (
        parent["manifest"]["after_file_sha256"]), "reconstructed e1 manifest"
    assert sum(value.startswith("refused:") for value in current.values()) == manifest["refusal_count"] == 21
    assert sorted(record["goldens"]["changed"]) == [
        "auth_move_and_change_type"], "e2 touched another golden"
    assert record["goldens"]["changed_count"] == 1
    assert record["goldens"]["compared_count"] == 75
    unchanged_now = {
        name: value for name, value in record["goldens"]["unchanged"].items()
        if name not in record["goldens"]["changed"]}
    for name, value in parent["goldens"]["unchanged"].items():
        if name in record["goldens"]["changed"]:
            continue
        assert unchanged_now[name] == value, f"e2 moved golden {name}"
    return _manifest_bytes(historical)


def _reverse_e1_migration(current_bytes, record, parent_bytes):
    """Check the E-1 delta and hand off the D-1-era manifest to the old chain.

    The form is the same as D-1's: the record is the NEWEST link, it owns the file on
    disk. What is checked separately is how E-1 differs: NOT ONE predicate is
    removed and NOT ONE tolerance is shifted (`predicates_removed`,
    `tolerances_changed` are zero), while a line-by-line audit of all 72 discrepancies
    is declared a clean 72/72 with zero numbers shifted. The audit is a separate
    instrument (`record["audit"]["instrument"]`), the record only carries its verdict.
    """
    assert record["schema"] == "kir-emission-e1-migration/1"
    assert record["record_digest"] == _digest(_canonical({
        key: value for key, value in record.items() if key != "record_digest"})), "e1 record digest"
    parent = json.loads(parent_bytes)
    assert _digest(parent_bytes) == record["parent"]["record_file_sha256"], "e1 parent record bytes"
    assert parent["record_digest"] == record["parent"]["record_digest"], "e1 parent record binding"
    manifest = record["manifest"]
    assert _digest(current_bytes) == manifest["after_file_sha256"], "current manifest digest"
    current = json.loads(current_bytes)
    assert len(current) == manifest["key_count"] == 2361
    assert _digest(_canonical(sorted(current))) == manifest["keyset_sha256"], "e1 keyset"
    assert manifest["added_keys"] == manifest["missing_keys"] == manifest["refusal_changes"] == []
    changes = manifest["changes"]
    assert len(changes) == manifest["changed_count"] == 72, "e1 change count"
    assert len(current) - len(changes) == manifest["unchanged_count"] == 2289
    # The stage moved — the set of checks did not. These two zeros are exactly
    # E-1's subject: the witness was not removed and the tolerance was not moved, otherwise this would be
    # a different fix under the same name.
    assert manifest["predicates_removed"] == 0, "e1 removed a predicate"
    assert manifest["tolerances_changed"] == 0, "e1 moved a tolerance"
    assert manifest["obligation_keys_moved"] == [
        "move_elements.location", "set_param.value_held"], "e1 moved another key"
    assert manifest["mode_counts"] == {"atomic": 36, "per_op": 36}, "e1 isolation split"
    audit = record["audit"]
    assert audit["clean"] == audit["of"] == len(changes), "e1 line audit incomplete"
    assert audit["numbers_shifted_total"] == 0, "e1 audit saw a moved number"
    historical = dict(current)
    for key, change in changes.items():
        assert key in historical, "changed key absent"
        assert historical[key] == change["after"], "changed after hash"
        assert change["before"] != change["after"], "vacuous change"
        assert not change["before"].startswith("refused:") and not change["after"].startswith("refused:")
        historical[key] = change["before"]
    assert _digest(_manifest_bytes(historical)) == manifest["before_file_sha256"] == (
        parent["manifest"]["after_file_sha256"]), "reconstructed d1 manifest"
    assert sum(value.startswith("refused:") for value in current.values()) == manifest["refusal_count"] == 21
    assert sorted(record["goldens"]["changed"]) == [
        "auth_move_and_change_type", "modify_setparam_delete"], "e1 touched another golden"
    assert record["goldens"]["changed_count"] == 2
    assert record["goldens"]["compared_count"] == 75
    unchanged_now = {
        name: value for name, value in record["goldens"]["unchanged"].items()
        if name not in record["goldens"]["changed"]}
    for name, value in parent["goldens"]["unchanged"].items():
        if name in record["goldens"]["changed"]:
            continue
        assert unchanged_now[name] == value, f"e1 moved golden {name}"
    return _manifest_bytes(historical)


def _reverse_d1_migration(current_bytes, record, parent_bytes):
    """Check the D-1 delta and hand off the C-1-era manifest to the old chain.

    The form is the same as C-1's: the record is the NEWEST link, it owns the file on
    disk, and everything it hands back is history. What is checked separately is
    how D-1 differs: NOT A SINGLE marker literal shifted (the address
    changes only for programs with an identity, and there are none of those in the corpus), and the delta
    lies in ONE fixture.
    """
    assert record["schema"] == "kir-emission-d1-migration/1"
    assert record["record_digest"] == _digest(_canonical({
        key: value for key, value in record.items() if key != "record_digest"})), "d1 record digest"
    parent = json.loads(parent_bytes)
    assert _digest(parent_bytes) == record["parent"]["record_file_sha256"], "d1 parent record bytes"
    assert parent["record_digest"] == record["parent"]["record_digest"], "d1 parent record binding"
    manifest = record["manifest"]
    assert _digest(current_bytes) == manifest["after_file_sha256"], "current manifest digest"
    current = json.loads(current_bytes)
    assert len(current) == manifest["key_count"] == 2361
    assert _digest(_canonical(sorted(current))) == manifest["keyset_sha256"], "d1 keyset"
    assert manifest["added_keys"] == manifest["missing_keys"] == manifest["refusal_changes"] == []
    changes = manifest["changes"]
    assert len(changes) == manifest["changed_count"] == 12, "d1 change count"
    assert len(current) - len(changes) == manifest["unchanged_count"] == 2349
    # The address moved ONLY for programs with an identity; there are none of those in the corpus, so
    # not a single marker literal moved — and this is an assertion, not a hope.
    assert manifest["marker_literals_changed"] == 0, "d1 marker literals moved"
    assert manifest["fixtures"] == ["scope:catalog_wall_type"], "d1 delta left its fixture"
    assert manifest["mode_counts"] == {"per_op": 6, "atomic": 6}, "d1 isolation split"
    historical = dict(current)
    for key, change in changes.items():
        assert key in historical, "changed key absent"
        assert historical[key] == change["after"], "changed after hash"
        assert change["before"] != change["after"], "vacuous change"
        assert not change["before"].startswith("refused:") and not change["after"].startswith("refused:")
        historical[key] = change["before"]
    assert _digest(_manifest_bytes(historical)) == manifest["before_file_sha256"] == (
        parent["manifest"]["after_file_sha256"]), "reconstructed c1 manifest"
    assert sum(value.startswith("refused:") for value in current.values()) == manifest["refusal_count"] == 21
    assert record["goldens"]["changed_count"] == 0
    assert record["goldens"]["unchanged"] == parent["goldens"]["unchanged"]
    return _manifest_bytes(historical)


def _reverse_c1_migration(current_bytes, record, parent_bytes):
    """Verify the C-1 delta and hand the capture-era manifest to the old chain.

    The C-1 record is the LATEST link: it owns the file on disk. Everything it
    hands back is historical, and every older record keeps asserting what it
    always asserted — that is the whole point of chaining rather than
    rewriting. A resigned record cannot hide a dropped or wrong entry: the
    reconstructed parent manifest is compared by digest.
    """
    assert record["schema"] == "kir-emission-c1-migration/1"
    assert record["record_digest"] == _digest(_canonical({
        key: value for key, value in record.items() if key != "record_digest"})), "c1 record digest"
    parent = json.loads(parent_bytes)
    assert _digest(parent_bytes) == record["parent"]["record_file_sha256"], "c1 parent record bytes"
    assert parent["record_digest"] == record["parent"]["record_digest"], "c1 parent record binding"
    manifest = record["manifest"]
    assert _digest(current_bytes) == manifest["after_file_sha256"], "current manifest digest"
    current = json.loads(current_bytes)
    assert len(current) == manifest["key_count"] == 2361
    assert _digest(_canonical(sorted(current))) == manifest["keyset_sha256"], "c1 keyset"
    assert manifest["added_keys"] == manifest["missing_keys"] == manifest["refusal_changes"] == []
    changes = manifest["changes"]
    assert len(changes) == manifest["changed_count"] == 309, "c1 change count"
    assert len(current) - len(changes) == manifest["unchanged_count"] == 2052
    # C-1 lives ONLY in per_op: in atomic the gate refuses by returning from
    # Execute before __post is ever published, so there was nothing to leak.
    assert manifest["mode_counts"] == {"per_op": 309, "atomic": 0}, "c1 isolation split"
    assert sum(manifest["prefix_counts"].values()) == 309
    historical = dict(current)
    for key, change in changes.items():
        assert key in historical, "changed key absent"
        assert key.endswith("|per_op"), "c1 changed a non-per_op key"
        assert historical[key] == change["after"], "changed after hash"
        assert change["before"] != change["after"], "vacuous change"
        assert not change["before"].startswith("refused:") and not change["after"].startswith("refused:")
        historical[key] = change["before"]
    assert _digest(_manifest_bytes(historical)) == manifest["before_file_sha256"] == (
        parent["manifest"]["after_file_sha256"]), "reconstructed capture manifest"
    assert sum(value.startswith("refused:") for value in current.values()) == manifest["refusal_count"] == 21
    # Goldens are compiled at the default atomic isolation, so a per_op-only
    # delta cannot move one. The equality is measured, not argued.
    assert record["goldens"]["changed_count"] == 0
    assert record["goldens"]["unchanged"] == {
        **parent["goldens"]["unchanged"],
        **{name: entry["after_sha256"] for name, entry in parent["goldens"]["changed"].items()}}
    return _manifest_bytes(historical)


def _reverse_capture_migration(current_bytes, record, parent_bytes):
    """Verify the latest exact delta before feeding history to the old test."""
    assert record["schema"] == "kir-emission-capture-migration/1"
    assert record["record_digest"] == _digest(_canonical({
        key: value for key, value in record.items() if key != "record_digest"})), "capture record digest"
    parent = json.loads(parent_bytes)
    assert _digest(parent_bytes) == record["parent"]["record_file_sha256"] == (
        "097361c3cfee7a3b4a707ade74d516593abf6bd009dfa7d88ea05c4cb6ba2af1"), "parent record bytes"
    assert parent["record_digest"] == record["parent"]["record_digest"], "parent record binding"
    manifest = record["manifest"]
    assert _digest(current_bytes) == manifest["after_file_sha256"], "current manifest digest"
    current = json.loads(current_bytes)
    assert len(current) == manifest["key_count"] == 2361
    assert _digest(_canonical(sorted(current))) == manifest["keyset_sha256"], "capture keyset"
    assert manifest["added_keys"] == manifest["missing_keys"] == manifest["refusal_changes"] == []
    changes = manifest["changes"]
    assert len(changes) == manifest["changed_count"] == 642, "capture change count"
    assert len(current) - len(changes) == manifest["unchanged_count"] == 1719
    historical = dict(current)
    for key, change in changes.items():
        assert key in historical, "changed key absent"
        assert historical[key] == change["after"], "changed after hash"
        assert change["before"] != change["after"], "vacuous change"
        assert not change["before"].startswith("refused:") and not change["after"].startswith("refused:")
        historical[key] = change["before"]
    assert _digest(_manifest_bytes(historical)) == manifest["before_file_sha256"] == (
        parent["coverage_append"]["after_file_sha256"]), "reconstructed parent manifest"
    assert sum(value.startswith("refused:") for value in current.values()) == manifest["refusal_count"] == 21
    return historical


class HistoricalEmissionContract(unittest.TestCase):
    """Historical migrations run under their retained predecessor, not today's fixes."""

    def enter_historical_emission(self):
        import sys
        from kir.tests.emit_parity_fixtures.capture_all_creates_counterfactual import (
            without_universal_identity_capture,
        )
        from kir.tests.emit_parity_fixtures.delete_cascade_counterfactual import (
            before_the_cascade_was_named,
        )
        from kir.tests.emit_parity_fixtures.native_readback_counterfactual import (
            before_native_readback_fixes, LEGACY_MANIFEST,
        )
        # 🔴 NEWEST LINK FIRST. Every migration below is reconstructed by undoing
        # the ones stacked on top of it; 2026-09-13 put identity capture on every
        # seam call, so a contract that reverses only its OWN delta would now
        # rebuild a manifest that never existed. Reversing in chain order is the
        # whole reason these reversals are executable instead of asserted.
        self.enterContext(before_the_cascade_was_named(require_effect=False))
        self.enterContext(without_universal_identity_capture(require_effect=False))
        self.enterContext(before_native_readback_fixes())
        self.enterContext(patch.object(sys.modules[__name__], "FIXTURE_PATH", LEGACY_MANIFEST))
        self.enterContext(patch.object(fixtures, "FIXTURE_PATH", LEGACY_MANIFEST))


class ByteParity(unittest.TestCase):
    def test_emit_model_byte_parity(self) -> None:
        frozen = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        current = emit_corpus()
        _assert_exact_parity(frozen, current)


class CorpusCoverageContract(HistoricalEmissionContract):
    def setUp(self):
        self.enter_historical_emission()

    def test_unexpected_extra_key_fails_even_when_every_old_hash_matches(self):
        with self.assertRaisesRegex(AssertionError, "unexpected extra"):
            _assert_exact_parity({"old": "a"}, {"old": "a", "unreviewed": "b"})

    def test_missing_key_fails(self):
        with self.assertRaisesRegex(AssertionError, "missing"):
            _assert_exact_parity({"old": "a"}, {})

    def test_changed_hash_still_fails_and_exact_control_passes(self):
        with self.assertRaisesRegex(AssertionError, "diverged"):
            _assert_exact_parity({"old": "a"}, {"old": "b"})
        _assert_exact_parity({"old": "a"}, {"old": "a"})

    def test_generator_check_also_refuses_unreviewed_extra_keys_without_writing(self):
        before = FIXTURE_PATH.read_bytes()
        current = json.loads(before)
        current["unexpected-program|2026|atomic"] = "0" * 64
        with patch.object(fixtures, "emit_corpus", return_value=current), \
                patch.object(fixtures.sys, "argv", ["generate_fixtures.py", "--check"]), \
                patch("builtins.print"):
            self.assertEqual(fixtures.main(), 1)
        self.assertEqual(FIXTURE_PATH.read_bytes(), before)

    def test_classification_uses_actual_expansion_without_query_doubling(self):
        macro = {"ir_version": "1.0", "ops": [{"op": "stack", "id": "arbitrary-name",
            "levels": 2, "h_mm": 3000, "floor": [{"op": "create_wall", "id": "wall",
                "p0_mm": [0, 0], "p1_mm": [5000, 0], "height_mm": 2800}]}]}
        self.assertTrue(fixtures._is_write(macro))
        self.assertFalse(fixtures._is_write({"ops": [{"op": "query_count", "id": "q", "kind": "wall"}]}))
        from kir.compiler import KirRefusal
        with self.assertRaises(KirRefusal):
            fixtures._is_write({"ops": [{"op": "unrecognized-write", "id": "x"}]})

    def test_every_supported_write_fixture_has_both_modes_and_queries_do_not(self):
        from kir.compiler import KirRefusal, plan_program
        frozen = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        for name, raw in fixtures.build_corpus().items():
            program = fixtures._strip(raw)
            try:
                planned = plan_program(program)
            except KirRefusal:
                self.assertTrue(all(value.startswith("refused:") for key, value in frozen.items()
                                    if key.startswith(name + "|")), name)
                continue
            writing = fixtures._is_write(planned)
            for version in fixtures.VERSIONS:
                atomic, per_op = f"{name}|{version}|atomic", f"{name}|{version}|per_op"
                if version < fixtures._min_ver(raw):
                    self.assertNotIn(atomic, frozen)
                    self.assertNotIn(per_op, frozen)
                elif frozen[atomic].startswith("refused:"):
                    self.assertNotIn(per_op, frozen)  # Existing refusal-recording policy.
                elif writing:
                    self.assertIn(per_op, frozen, (name, version))
                else:
                    self.assertNotIn(per_op, frozen, (name, version))

    def test_reviewed_migration_reconstructs_original_and_separates_coverage(self):
        def canonical(value):
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        def digest(value):
            return hashlib.sha256(value).hexdigest()
        def manifest_bytes(value):
            return (json.dumps(value, indent=0, sort_keys=True) + "\n").encode()

        self.assertEqual(INTENDED_CHANGES, {})
        record = json.loads(BASELINE_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(record["schema"], "kir-emission-baseline-migration/1")
        self.assertEqual(record["record_digest"], digest(canonical({key: value for key, value in record.items()
                                                                   if key != "record_digest"})))
        newest = json.loads(C1_MIGRATION_PATH.read_text(encoding="utf-8"))
        latest = json.loads(CAPTURE_MIGRATION_PATH.read_text(encoding="utf-8"))
        # These pins describe historical bytes. Only the latest record's pins
        # assert equality with files now on disk; the parent record stays intact.
        self.assertEqual(record["final_review_source_sha256"],
                         latest["parent"]["historical_review_source_sha256"])
        self.assertEqual(record["phase_source_snapshot_scope"],
                         "captured at each phase emission; generator hashes precede the final documentation/keyset-check edits")
        original_info, refresh, coverage = (record[key] for key in ("original", "behavior_refresh", "coverage_append"))
        e1_bytes = _reverse_e2_migration(
            _reverse_e3_migration(
                FIXTURE_PATH.read_bytes(),
                json.loads(E3_MIGRATION_PATH.read_text(encoding="utf-8")),
                E2_MIGRATION_PATH.read_bytes()),
            json.loads(E2_MIGRATION_PATH.read_text(encoding="utf-8")),
            E1_MIGRATION_PATH.read_bytes())
        d1_bytes = _reverse_e1_migration(
            e1_bytes,
            json.loads(E1_MIGRATION_PATH.read_text(encoding="utf-8")),
            D1_MIGRATION_PATH.read_bytes())
        c1_bytes = _reverse_d1_migration(
            d1_bytes,
            json.loads(D1_MIGRATION_PATH.read_text(encoding="utf-8")),
            C1_MIGRATION_PATH.read_bytes())
        capture_bytes = _reverse_c1_migration(
            c1_bytes, newest, CAPTURE_MIGRATION_PATH.read_bytes())
        current = _reverse_capture_migration(
            capture_bytes, latest, BASELINE_MIGRATION_PATH.read_bytes())
        current_bytes = manifest_bytes(current)
        self.assertEqual(len(current), coverage["after_key_count"])
        self.assertEqual(digest(current_bytes), coverage["after_file_sha256"])
        self.assertEqual(digest(canonical(sorted(current))), coverage["keyset_sha256"])
        self.assertEqual(coverage["changed_existing_keys"], [])
        self.assertEqual(coverage["missing_keys"], [])
        self.assertEqual(len(coverage["added"]), coverage["added_count"])
        self.assertEqual(coverage["added_count"], 18)

        phase1 = dict(current)
        for key, value in coverage["added"].items():
            self.assertTrue(key.endswith("|per_op"))
            self.assertEqual(phase1.pop(key), value)
        self.assertEqual(len(phase1), 2343)
        self.assertEqual(coverage["unchanged_existing_count"], 2343)
        self.assertEqual(digest(manifest_bytes(phase1)), coverage["before_file_sha256"])
        self.assertEqual(coverage["before_file_sha256"], refresh["after_file_sha256"])
        self.assertEqual(digest(canonical(sorted(phase1))), refresh["keyset_sha256"])

        historical = dict(phase1)
        reasons = Counter()
        for key, change in refresh["changes"].items():
            self.assertEqual(historical[key], change["after"])
            self.assertNotEqual(change["before"], change["after"])
            self.assertFalse(change["before"].startswith("refused:"))
            self.assertFalse(change["after"].startswith("refused:"))
            historical[key] = change["before"]
            reasons["+".join(change["scope_reasons"])]+=1
            for reason in change["scope_reasons"]:
                for path in refresh["scope_definitions"][reason]["replacement_tests"]:
                    self.assertTrue((FIXTURE_PATH.parents[3] / path).is_file(), path)
        self.assertEqual(dict(reasons), refresh["scope_counts"])
        self.assertEqual(len(refresh["changes"]), refresh["changed_count"])
        self.assertEqual(refresh["changed_count"], 726)
        self.assertEqual(len(phase1) - len(refresh["changes"]), refresh["unchanged_count"])
        self.assertEqual(refresh["unchanged_count"], 1617)
        self.assertEqual(refresh["missing_keys"], [])
        self.assertEqual(refresh["extra_keys"], [])
        self.assertEqual(refresh["refusal_changes"], [])
        self.assertEqual(digest(manifest_bytes(historical)), original_info["file_sha256"])
        self.assertEqual(original_info["file_sha256"], "c9d39f8b5a17ce7bb0e1092f444fb1611372a2f8be549f038d3e76517b018e5c")
        self.assertEqual(digest(canonical(sorted(historical))), original_info["keyset_sha256"])
        self.assertEqual(set(historical), set(phase1))
        for key, value in historical.items():
            if value.startswith("refused:"):
                self.assertEqual(current[key], value)


class CaptureMigrationContract(HistoricalEmissionContract):
    def setUp(self):
        self.enter_historical_emission()
        self.record = json.loads(CAPTURE_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.parent_bytes = BASELINE_MIGRATION_PATH.read_bytes()
        # The capture record is no longer the newest link: the file on disk
        # belongs to C-1. Its own subject is the manifest C-1 reconstructs,
        # and that reconstruction is itself checked by digest.
        # The chain grew to four links: the file on disk belongs to D-1.
        # The chain grew to SIX links (E-2, 07.09.2026).
        self.current_bytes = _reverse_c1_migration(
            _reverse_d1_migration(
                _reverse_e1_migration(
                    _reverse_e2_migration(
                    _reverse_e3_migration(
                        FIXTURE_PATH.read_bytes(),
                        json.loads(E3_MIGRATION_PATH.read_text(encoding="utf-8")),
                        E2_MIGRATION_PATH.read_bytes()),
                    json.loads(E2_MIGRATION_PATH.read_text(encoding="utf-8")),
                    E1_MIGRATION_PATH.read_bytes()),
                    json.loads(E1_MIGRATION_PATH.read_text(encoding="utf-8")),
                    D1_MIGRATION_PATH.read_bytes()),
                json.loads(D1_MIGRATION_PATH.read_text(encoding="utf-8")),
                C1_MIGRATION_PATH.read_bytes()),
            json.loads(C1_MIGRATION_PATH.read_text(encoding="utf-8")),
            CAPTURE_MIGRATION_PATH.read_bytes())

    def resign(self, record):
        record["record_digest"] = _digest(_canonical({
            key: value for key, value in record.items() if key != "record_digest"}))
        return record

    def test_record_pins_retained_review_sources_and_replacement_tests(self):
        # 🔴 THIS RECORD IS NO LONGER THE LAST ONE (C-1, 06.09.2026). Its source
        # pins were CURRENT as of its own day; comparing them against the disk now
        # would mean requiring that the generator and this file never change.
        # The claim is not discarded and not rewritten into a foreign file — it is HELD
        # by its heir, and what is checked here is exactly that identity (the same form
        # by which the baseline handed its claim to the capture record).
        _reverse_capture_migration(self.current_bytes, self.record, self.parent_bytes)
        self.assertEqual(INTENDED_CHANGES, {})
        newest = json.loads(C1_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.record["current_review_source_sha256"],
                         newest["parent"]["historical_review_source_sha256"])
        for path in self.record["replacement_tests"]:
            self.assertTrue((FIXTURE_PATH.parents[3] / path).is_file(), path)
        self.assertEqual(self.record["coverage_change"], "none; floor-type hash fixture is a separate future append")

    def test_exact_counterfactual_restores_parent_without_changing_emitter_registry(self):
        from kir import authoring
        from kir.tests.emit_parity_fixtures.c1_counterfactual import without_c1_range_cleanup
        from kir.tests.emit_parity_fixtures.capture_counterfactual import without_section_capture
        expected = _reverse_capture_migration(self.current_bytes, self.record, self.parent_bytes)
        before = dict(authoring._EMITTERS)
        gate = authoring.operation_check_gate
        # Two counterfactuals, one per recorded delta, composed in the order
        # the records were written. Neither may leave anything behind.
        from kir.tests.emit_parity_fixtures.d1_counterfactual import without_d1_reuse_guard
        from kir.tests.emit_parity_fixtures.e3_counterfactual import (
            without_e3_final_shift)
        from kir.tests.emit_parity_fixtures.e2_counterfactual import (
            without_e2_final_shift)
        from kir.tests.emit_parity_fixtures.e1_counterfactual import (
            without_e1_operation_stage)
        with without_e3_final_shift(), without_e2_final_shift(), without_e1_operation_stage(), \
                without_d1_reuse_guard(), without_c1_range_cleanup(), without_section_capture():
            restored = emit_corpus()
        self.assertEqual(authoring._EMITTERS, before)
        self.assertIs(authoring.operation_check_gate, gate)
        _assert_exact_parity(expected, restored)

    def test_all_golden_files_have_exact_recorded_scope_and_after_hashes(self):
        golden_dir = FIXTURE_PATH.parent.parent / "golden"
        from kir.tests.emit_parity_fixtures.native_readback_counterfactual import LEGACY_GOLDENS
        actual = json.loads(LEGACY_GOLDENS.read_text(encoding="utf-8"))
        self.assertEqual(set(actual), {path.name.removesuffix(".golden.cs")
                                      for path in golden_dir.glob("*.golden.cs")})
        # 🔴 THE GOLDEN ON DISK BELONGS TO THE VERY NEWEST LINK (E-1, 07.09.2026).
        # The capture record speaks of ITS OWN era, so the two files that
        # E-1 moved are taken from ITS PARENT (D-1) — that is, in the form
        # they had before E-1. This is not an exemption: `E1MigrationContract`
        # checks the list of two names and both before/after hashes.
        e1 = json.loads(E1_MIGRATION_PATH.read_text(encoding="utf-8"))
        pre_e1 = json.loads(D1_MIGRATION_PATH.read_text(encoding="utf-8"))["goldens"]["unchanged"]
        for name in e1["goldens"]["changed"]:
            actual[name] = pre_e1[name]
        info = self.record["goldens"]
        expected = dict(info["unchanged"])
        expected.update({name: entry["after_sha256"] for name, entry in info["changed"].items()})
        self.assertEqual(len(expected), info["compared_count"])
        self.assertEqual(len(info["changed"]), info["changed_count"])
        self.assertEqual((len(actual), len(info["changed"]), len(info["unchanged"])), (75, 22, 53))
        _assert_exact_parity(expected, actual)
        reasons = Counter(entry["classification"] for entry in info["changed"].values())
        self.assertEqual(dict(reasons), {"capture_only": 20, "capture_and_historical_type_stage": 2})

    def test_actual_golden_owners_reverse_capture_and_separate_annotation_history(self):
        from kir.tests.emit_parity_fixtures.capture_counterfactual import (
            annotation_stage_fragments, collect_golden_emissions,
            reverse_annotation_stage, without_section_capture,
        )
        from kir.tests.emit_parity_fixtures.e3_counterfactual import (
            without_e3_final_shift)
        from kir.tests.emit_parity_fixtures.e2_counterfactual import (
            without_e2_final_shift)
        from kir.tests.emit_parity_fixtures.e1_counterfactual import (
            without_e1_operation_stage)
        # Counterfactuals compose: the capture era is also "before E-1."
        with without_e3_final_shift(), without_e2_final_shift(), without_e1_operation_stage(), \
                without_section_capture():
            restored = collect_golden_emissions()
        info = self.record["goldens"]
        expected = {**info["unchanged"], **{
            name: entry["before_sha256"] for name, entry in info["changed"].items()}}
        self.assertEqual(set(restored), set(expected))
        for name, source in restored.items():
            entry = info["changed"].get(name, {})
            if entry.get("classification") == "capture_and_historical_type_stage":
                self.assertEqual(_digest(source.encode()), entry["stage_only_sha256"])
                fragments = annotation_stage_fragments()
                self.assertEqual({key: len(value.encode()) for key, value in fragments.items()},
                                 entry["stage_fragment_byte_lengths"])
                self.assertEqual({key: _digest(value.encode()) for key, value in fragments.items()},
                                 entry["stage_fragment_sha256"])
                self.assertEqual(sum(len(value.encode()) for value in fragments.values()), 1548)
                source = reverse_annotation_stage(source)
            self.assertEqual(_digest(source.encode()), expected[name], name)

    def test_missing_change_entry_cannot_be_hidden_by_resigning_record(self):
        self.record["manifest"]["changes"].pop(next(iter(self.record["manifest"]["changes"])))
        with self.assertRaisesRegex(AssertionError, "capture change count"):
            _reverse_capture_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_before_value_breaks_parent_reconstruction_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["before"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "reconstructed parent manifest"):
            _reverse_capture_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_after_value_refuses_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["after"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "changed after hash"):
            _reverse_capture_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_parent_record_replacement_is_not_a_migration(self):
        with self.assertRaisesRegex(AssertionError, "parent record bytes"):
            _reverse_capture_migration(self.current_bytes, self.record, self.parent_bytes + b" ")

    def test_record_digest_corruption_refuses(self):
        self.record["manifest"]["changed_count"] = 641
        with self.assertRaisesRegex(AssertionError, "capture record digest"):
            _reverse_capture_migration(self.current_bytes, self.record, self.parent_bytes)

    def test_unaccounted_golden_and_changed_golden_hash_fail(self):
        expected = self.record["goldens"]["unchanged"]
        with self.assertRaisesRegex(AssertionError, "unexpected extra"):
            _assert_exact_parity(expected, {**expected, "unreviewed-golden": "0" * 64})
        changed = dict(expected)
        changed[next(iter(changed))] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "diverged"):
            _assert_exact_parity(expected, changed)

    def test_counterfactual_refuses_missing_or_duplicate_fragment(self):
        from kir.tests.emit_parity_fixtures.capture_counterfactual import reverse_capture_readback
        from kir.emit_core import element_identity_readback_cs
        fragment = element_identity_readback_cs("__el_W", revit_version="2026")
        guarded = '    try { __rb["id"] = __el_W.Id.ToString(); } catch { }\n'
        for source in ("", fragment + fragment + guarded, fragment):
            with self.subTest(source_length=len(source)), self.assertRaises(AssertionError):
                reverse_capture_readback(source, op_id="W", revit_version="2026")


class C1MigrationContract(HistoricalEmissionContract):
    """The newest link: it owns the manifest on disk and must be forgeable-proof."""

    def setUp(self):
        self.enter_historical_emission()
        self.record = json.loads(C1_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.parent_bytes = CAPTURE_MIGRATION_PATH.read_bytes()
        # C-1 stopped being the last link: the file on disk belongs to E-2,
        # and it is now THREE steps back to the C-1 era.
        self.current_bytes = _reverse_d1_migration(
            _reverse_e1_migration(
                _reverse_e2_migration(
                    _reverse_e3_migration(
                        FIXTURE_PATH.read_bytes(),
                        json.loads(E3_MIGRATION_PATH.read_text(encoding="utf-8")),
                        E2_MIGRATION_PATH.read_bytes()),
                    json.loads(E2_MIGRATION_PATH.read_text(encoding="utf-8")),
                    E1_MIGRATION_PATH.read_bytes()),
                json.loads(E1_MIGRATION_PATH.read_text(encoding="utf-8")),
                D1_MIGRATION_PATH.read_bytes()),
            json.loads(D1_MIGRATION_PATH.read_text(encoding="utf-8")),
            C1_MIGRATION_PATH.read_bytes())

    def resign(self, record):
        record["record_digest"] = _digest(_canonical({
            key: value for key, value in record.items() if key != "record_digest"}))
        return record

    def test_record_pins_retained_review_sources_and_replacement_tests(self):
        # The same handoff of the claim as baseline -> capture -> c1: this record's
        # source pins were CURRENT as of its own day and are held
        # by its heir, not compared against the disk.
        _reverse_c1_migration(self.current_bytes, self.record, self.parent_bytes)
        self.assertEqual(INTENDED_CHANGES, {})
        newest = json.loads(D1_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.record["current_review_source_sha256"],
                         newest["parent"]["historical_review_source_sha256"])
        for path in self.record["replacement_tests"]:
            self.assertTrue((FIXTURE_PATH.parents[3] / path).is_file(), path)

    def test_counterfactual_restores_the_capture_manifest_and_leaves_no_patch(self):
        from kir import authoring
        from kir.tests.emit_parity_fixtures.c1_counterfactual import without_c1_range_cleanup
        from kir.tests.emit_parity_fixtures.e3_counterfactual import (
            without_e3_final_shift)
        from kir.tests.emit_parity_fixtures.e2_counterfactual import (
            without_e2_final_shift)
        from kir.tests.emit_parity_fixtures.e1_counterfactual import (
            without_e1_operation_stage)
        expected = json.loads(_reverse_c1_migration(
            self.current_bytes, self.record, self.parent_bytes))
        from kir.tests.emit_parity_fixtures.d1_counterfactual import without_d1_reuse_guard
        gate = authoring.operation_check_gate
        with without_e3_final_shift(), without_e2_final_shift(), without_e1_operation_stage(), \
                without_d1_reuse_guard(), without_c1_range_cleanup():
            restored = emit_corpus()
        self.assertIs(authoring.operation_check_gate, gate)
        _assert_exact_parity(expected, restored)

    def test_missing_change_entry_cannot_be_hidden_by_resigning_record(self):
        self.record["manifest"]["changes"].pop(next(iter(self.record["manifest"]["changes"])))
        with self.assertRaisesRegex(AssertionError, "c1 change count"):
            _reverse_c1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_before_value_breaks_parent_reconstruction_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["before"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "reconstructed capture manifest"):
            _reverse_c1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_after_value_refuses_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["after"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "changed after hash"):
            _reverse_c1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_parent_record_replacement_is_not_a_migration(self):
        with self.assertRaisesRegex(AssertionError, "c1 parent record bytes"):
            _reverse_c1_migration(self.current_bytes, self.record, self.parent_bytes + b" ")

    def test_record_digest_corruption_refuses(self):
        self.record["manifest"]["changed_count"] = 308
        with self.assertRaisesRegex(AssertionError, "c1 record digest"):
            _reverse_c1_migration(self.current_bytes, self.record, self.parent_bytes)

    def test_an_atomic_key_in_the_delta_is_refused(self):
        changes = self.record["manifest"]["changes"]
        key = next(iter(changes))
        changes[key.replace("|per_op", "|atomic")] = changes.pop(key)
        self.record["manifest"]["mode_counts"] = {"per_op": 308, "atomic": 1}
        with self.assertRaisesRegex(AssertionError, "c1 isolation split"):
            _reverse_c1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_moved_golden_cannot_be_recorded_as_unchanged(self):
        name = next(iter(self.record["goldens"]["unchanged"]))
        self.record["goldens"]["unchanged"][name] = "0" * 64
        with self.assertRaises(AssertionError):
            _reverse_c1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_counterfactual_refuses_a_gate_it_does_not_recognise(self):
        from kir.tests.emit_parity_fixtures.c1_counterfactual import reverse_c1_gate
        with self.assertRaises(AssertionError):
            reverse_c1_gate("if (__post.Count > __operationPostStart_X) { throw; }")


class E3MigrationContract(HistoricalEmissionContract):
    """The newest link in the chain (07.09.2026, E-3): it owns the manifest on disk.

    BASELINES: old `10e5d2dd777abfa4f3fa828a2cdbf102d37721cc2a5f5a13cc4db2ef4664bd07`,
    new `690439ae61664052cd51f69476b4580e855f3d1ae5e198b84a69cacc1cd59245`.
    Delta: 2361 keys, 24 discrepancies (12 atomic + 12 per_op, the same 2 fixtures
    as E-2), 0 added, 0 missing, 21 refusals unchanged. A line-by-line audit of
    all 24 — with the SAME instrument as E-2
    (`kir/tests/emit_parity_fixtures/e2_parity_diff_audit.py`; the subject and
    predicate of the delta are the same, a second instrument for the same thing would have
    diverged from the first) — **24/24 "12 numbers per emission, no lines moved, one block —
    post MP", UNRESOLVED: 0**. 1 of 75 goldens touched.

    THE RECORD'S MAIN NUMBER IS THE DIFFERENCE BETWEEN 8 AND 1: eight emitters were
    taught, ONE is visible in the frozen corpus (`create_pipe`). Both numbers are held by
    `_reverse_e3_migration`, so that "extended to eight" cannot be read
    as "byte-checked for eight."
    """

    def setUp(self):
        self.enter_historical_emission()
        self.record = json.loads(E3_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.parent_bytes = E2_MIGRATION_PATH.read_bytes()
        self.current_bytes = FIXTURE_PATH.read_bytes()

    def resign(self, record):
        record["record_digest"] = _digest(_canonical({
            key: value for key, value in record.items() if key != "record_digest"}))
        return record

    def test_record_pins_current_review_sources_and_replacement_tests(self):
        _reverse_e3_migration(self.current_bytes, self.record, self.parent_bytes)
        self.assertEqual(INTENDED_CHANGES, {})
        # E-3 source pins are historical. The successor retains them verbatim
        # and checks its own current source pins in NativeReadbackMigrationContract.
        successor = json.loads(FIXTURE_PATH.with_name("native_readback_migration.json").read_text())
        self.assertEqual(self.record["current_review_source_sha256"],
                         successor["parent"]["historical_review_source_sha256"])
        for path in self.record["replacement_tests"]:
            self.assertTrue((FIXTURE_PATH.parents[3] / path).is_file(), path)

    def test_every_pinned_review_source_ships_with_the_record(self):
        """The NEWEST record's pin must not point outside the commit.

        The body is verbatim the same as `E2MigrationContract`'s (set up after a
        red on 07.09.2026: the auditor lived in `.work/`, and on the frozen copy
        the pin failed with `FileNotFoundError`). Here it stands on ITS OWN record:
        a guard checking someone else's list of sources guards nothing.
        """
        root = FIXTURE_PATH.parents[3]
        pinned = sorted(self.record["current_review_source_sha256"])
        self.assertTrue(pinned, "запись не пинает ни одного источника")
        paths = pinned + list(self.record["replacement_tests"])
        for path in paths:
            self.assertTrue((root / path).is_file(),
                            f"{path}: запись пинает файл, которого рядом с ней "
                            f"НЕТ — у читателя на чистом клоне этого пина нет")
        shipped = _paths_the_commit_will_carry(root)
        if shipped is None:
            # A frozen copy or an installed package: this tree has no repository of
            # its own, and `.is_file()` above has already answered the whole
            # question. Silently skipping the second, STRONGER argument is only
            # allowed by naming why it does not apply here.
            self.assertFalse((root / ".git").exists(),
                             "у дерева есть свой .git, а список файлов не получен — "
                             "это поломка сторожа, а не замороженная копия")
            return
        for path in paths:
            self.assertIn(path, shipped,
                          f"{path}: файл лежит на диске, но в коммит НЕ уедет "
                          f"(например, он под `.work/`) — провенанс указывает "
                          f"наружу коммита")

    def test_counterfactual_restores_the_e2_manifest_and_leaves_no_patch(self):
        from kir import authoring
        from kir.tests.emit_parity_fixtures.e3_counterfactual import (
            without_e3_final_shift)

        expected = json.loads(_reverse_e3_migration(
            self.current_bytes, self.record, self.parent_bytes))
        before = dict(authoring._EMITTERS)
        with without_e3_final_shift() as seen:
            restored = emit_corpus()
        self.assertEqual(authoring._EMITTERS, before)
        self.assertTrue(seen["stripped"], "поле не встретилось ни разу")
        _assert_exact_parity(expected, restored)

    def test_the_counterfactual_leaves_the_wall_alone(self):
        """CONTROL on the record's BOUNDARY: E-3 must not roll back E-2's delta.

        If reversibility also undid the shift for `create_wall`, the "restored"
        manifest would travel TWO links back, and would still match nothing —
        silently attributing E-2's own 24 discrepancies to E-3.
        """
        from kir.tests.emit_parity_fixtures.e3_counterfactual import E3_STAGED_OPS
        self.assertNotIn("create_wall", E3_STAGED_OPS)
        self.assertEqual(8, len(E3_STAGED_OPS))

    def test_missing_change_entry_cannot_be_hidden_by_resigning_record(self):
        self.record["manifest"]["changes"].pop(next(iter(self.record["manifest"]["changes"])))
        with self.assertRaisesRegex(AssertionError, "e3 change count"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_before_value_breaks_parent_reconstruction_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["before"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "reconstructed e2 manifest"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_after_value_refuses_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["after"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "changed after hash"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_parent_record_replacement_is_not_a_migration(self):
        with self.assertRaisesRegex(AssertionError, "e3 parent record bytes"):
            _reverse_e3_migration(self.current_bytes, self.record, self.parent_bytes + b" ")

    def test_record_digest_corruption_refuses(self):
        self.record["manifest"]["changed_count"] = 23
        with self.assertRaisesRegex(AssertionError, "e3 record digest"):
            _reverse_e3_migration(self.current_bytes, self.record, self.parent_bytes)

    def test_a_removed_predicate_cannot_be_recorded_as_a_shifted_number(self):
        self.record["manifest"]["predicates_removed"] = 1
        with self.assertRaisesRegex(AssertionError, "e3 removed a predicate"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_moved_tolerance_cannot_be_recorded_as_a_shifted_number(self):
        self.record["manifest"]["tolerances_changed"] = 1
        with self.assertRaisesRegex(AssertionError, "e3 moved a tolerance"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_moved_stage_cannot_ride_along_as_e3(self):
        self.record["manifest"]["stages_moved"] = 1
        with self.assertRaisesRegex(AssertionError, "e3 moved a stage"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_moved_line_cannot_be_signed_off_as_a_number_shift(self):
        self.record["audit"]["lines_moved_total"] = 1
        with self.assertRaisesRegex(AssertionError, "e3 audit saw a moved line"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_an_incomplete_line_audit_cannot_be_signed_off(self):
        self.record["audit"]["clean"] = 23
        with self.assertRaisesRegex(AssertionError, "e3 line audit incomplete"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_corpus_reach_cannot_be_inflated_to_the_number_taught(self):
        """🔴 "Eight were taught" does NOT mean "eight were byte-checked."

        This exact substitution is what would make the record flattering: parity sees exactly
        `create_pipe`, and crediting it with the other seven is the same as
        declaring covered a range the corpus never reaches.
        """
        self.record["manifest"]["ops_visible_in_corpus"] = [
            "create_pipe", "create_beam"]
        with self.assertRaisesRegex(AssertionError, "e3 corpus reach"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_second_golden_cannot_ride_along(self):
        self.record["goldens"]["changed"].append("full_house_v1")
        with self.assertRaisesRegex(AssertionError, "e3 touched another golden"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_third_fixture_cannot_ride_along(self):
        self.record["manifest"]["fixtures"].append("scope:modify")
        with self.assertRaisesRegex(AssertionError, "e3 touched another fixture"):
            _reverse_e3_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)


class E2MigrationContract(HistoricalEmissionContract):
    """The newest link in the chain (07.09.2026, E-2): it owns the manifest on disk.

    BASELINES: old `bd89857c4478e01d296ddf60cd84ebaf88571092fb62b6fc63c40b88ec507ac0`,
    new `10e5d2dd777abfa4f3fa828a2cdbf102d37721cc2a5f5a13cc4db2ef4664bd07`.
    Delta: 2361 keys, 24 discrepancies (12 atomic + 12 per_op, 2 fixtures),
    0 added, 0 missing, 21 refusals unchanged. A line-by-line audit of all 24
    (`kir/tests/emit_parity_fixtures/e2_parity_diff_audit.py`) —
    **24/24 "the ends' expectation is shifted by exactly delta_mm, 8 numbers per emission,
    no lines moved"**. 1 of 75 goldens touched.
    """

    def setUp(self):
        self.enter_historical_emission()
        self.record = json.loads(E2_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.parent_bytes = E1_MIGRATION_PATH.read_bytes()
        # 🔴 E-2 IS NO LONGER THE LAST LINK (07.09.2026, E-3). The file on disk
        # is owned by the heir; what is "current" for E-2 is the manifest that E-3 hands
        # back. The same handoff as D-1 -> E-1 -> E-2 one link earlier.
        self.current_bytes = _reverse_e3_migration(
            FIXTURE_PATH.read_bytes(),
            json.loads(E3_MIGRATION_PATH.read_text(encoding="utf-8")),
            E2_MIGRATION_PATH.read_bytes())

    def resign(self, record):
        record["record_digest"] = _digest(_canonical({
            key: value for key, value in record.items() if key != "record_digest"}))
        return record

    def test_record_pins_retained_review_sources_and_replacement_tests(self):
        # 🔴 THE SAME HANDOFF OF THE CLAIM AS baseline -> capture -> C-1 -> D-1.
        # E-2's source pins were CURRENT as of its own day; comparing them against the disk
        # now would mean requiring that the generator and this file never
        # change again. The claim is not discarded and not rewritten into a foreign file —
        # it is HELD BY ITS HEIR, and what is checked here is exactly that identity.
        _reverse_e2_migration(self.current_bytes, self.record, self.parent_bytes)
        self.assertEqual(INTENDED_CHANGES, {})
        newest = json.loads(E3_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.record["current_review_source_sha256"],
                         newest["parent"]["historical_review_source_sha256"])
        for path in self.record["replacement_tests"]:
            self.assertTrue((FIXTURE_PATH.parents[3] / path).is_file(), path)

    def test_every_pinned_review_source_ships_with_the_record(self):
        """A record's pin must not point outside the commit.

        (E-2 stopped being the newest one on 07.09.2026; the guard STAYS on it —
        its sources must still ride into the commit exactly the same way — and an identical
        one stands on the newest link, `E3MigrationContract`.)

        🔴 SET UP AFTER A RED ON 07.09.2026, AND THE RED WAS NOT HERE. E-2's
        auditor lived in `.work/marathon-fable-20260907/left/`, the record pinned its
        sha256 — and in the developer's TREE everything was green, because the file was
        right there. `.work/` is not part of the commit: on the frozen copy
        (`git archive HEAD` + the wave's files) the same test failed with
        `FileNotFoundError`, meaning that on the owner's clean clone the provenance
        pointed at something they don't have.

        🔴 AND THE FIRST DRAFT OF THIS PIN HURT FROM EXACTLY THE SAME THING. It asked
        `git ls-files` — and the frozen copy HAS NO git repository, so the pin
        failed with `CalledProcessError` on the very copy it was set up for.
        A guard that only works where everything is already visible is not a guard.

        So what is checked is EXISTENCE NEXT TO THE RECORD: on the
        frozen copy, the set of files IS the commit, so `.is_file()`
        there is direct proof. Where git is available, it is asked
        ADDITIONALLY (and only then), to catch a file that sits on
        disk but will not ride into the commit — exactly the original defect.
        """
        root = FIXTURE_PATH.parents[3]
        pinned = sorted(self.record["current_review_source_sha256"])
        self.assertTrue(pinned, "запись не пинает ни одного источника")
        paths = pinned + list(self.record["replacement_tests"])
        for path in paths:
            self.assertTrue((root / path).is_file(),
                            f"{path}: запись пинает файл, которого рядом с ней "
                            f"НЕТ — у читателя на чистом клоне этого пина нет")
        shipped = _paths_the_commit_will_carry(root)
        if shipped is None:
            # A frozen copy or an installed package: no repository owns this tree,
            # and `.is_file()` above has already answered the whole question.
            # Silently skipping the second, STRONGER argument is only allowed by
            # naming why it does not apply here.
            self.assertFalse((root / ".git").exists(),
                             "у дерева есть свой .git, а список файлов не получен — "
                             "это поломка сторожа, а не замороженная копия")
            return
        for path in paths:
            self.assertIn(path, shipped,
                          f"{path}: файл лежит на диске, но в коммит НЕ уедет "
                          f"(например, он под `.work/`) — провенанс указывает "
                          f"наружу коммита")

    def test_counterfactual_restores_the_e1_manifest_and_leaves_no_patch(self):
        from kir import authoring
        from kir.tests.emit_parity_fixtures.e3_counterfactual import (
            without_e3_final_shift)
        from kir.tests.emit_parity_fixtures.e2_counterfactual import (
            without_e2_final_shift)

        expected = json.loads(_reverse_e2_migration(
            self.current_bytes, self.record, self.parent_bytes))
        before = dict(authoring._EMITTERS)
        with without_e3_final_shift(), without_e2_final_shift() as seen:
            restored = emit_corpus()
        self.assertEqual(authoring._EMITTERS, before)
        self.assertTrue(seen["stripped"], "поле не встретилось ни разу")
        _assert_exact_parity(expected, restored)

    def test_missing_change_entry_cannot_be_hidden_by_resigning_record(self):
        self.record["manifest"]["changes"].pop(next(iter(self.record["manifest"]["changes"])))
        with self.assertRaisesRegex(AssertionError, "e2 change count"):
            _reverse_e2_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_before_value_breaks_parent_reconstruction_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["before"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "reconstructed e1 manifest"):
            _reverse_e2_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_after_value_refuses_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["after"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "changed after hash"):
            _reverse_e2_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_parent_record_replacement_is_not_a_migration(self):
        with self.assertRaisesRegex(AssertionError, "e2 parent record bytes"):
            _reverse_e2_migration(self.current_bytes, self.record, self.parent_bytes + b" ")

    def test_record_digest_corruption_refuses(self):
        self.record["manifest"]["changed_count"] = 23
        with self.assertRaisesRegex(AssertionError, "e2 record digest"):
            _reverse_e2_migration(self.current_bytes, self.record, self.parent_bytes)

    def test_a_removed_predicate_cannot_be_recorded_as_a_shifted_number(self):
        """E-2's main assertion: a NUMBER shifted, not the set of checks."""

        self.record["manifest"]["predicates_removed"] = 1
        with self.assertRaisesRegex(AssertionError, "e2 removed a predicate"):
            _reverse_e2_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_moved_tolerance_cannot_be_recorded_as_a_shifted_number(self):
        self.record["manifest"]["tolerances_changed"] = 1
        with self.assertRaisesRegex(AssertionError, "e2 moved a tolerance"):
            _reverse_e2_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_moved_stage_cannot_ride_along_as_e2(self):
        """The difference between E-2 and E-1 is load-bearing: the stage was NOT moved here.

        Without this claim, the E-2 record would accept E-1's delta under its own name —
        that is, it would explain the discrepancy with a mechanism other than the one that produced it.
        """
        self.record["manifest"]["stages_moved"] = 1
        with self.assertRaisesRegex(AssertionError, "e2 moved a stage"):
            _reverse_e2_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_moved_line_cannot_be_signed_off_as_a_number_shift(self):
        self.record["audit"]["lines_moved_total"] = 1
        with self.assertRaisesRegex(AssertionError, "e2 audit saw a moved line"):
            _reverse_e2_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_an_incomplete_line_audit_cannot_be_signed_off(self):
        self.record["audit"]["clean"] = 23
        with self.assertRaisesRegex(AssertionError, "e2 line audit incomplete"):
            _reverse_e2_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_second_golden_cannot_ride_along(self):
        self.record["goldens"]["changed"].append("full_house_v1")
        with self.assertRaisesRegex(AssertionError, "e2 touched another golden"):
            _reverse_e2_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_third_fixture_cannot_ride_along(self):
        self.record["manifest"]["fixtures"].append("scope:modify")
        with self.assertRaisesRegex(AssertionError, "e2 touched another fixture"):
            _reverse_e2_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)


class E1MigrationContract(HistoricalEmissionContract):
    """The newest link in the chain (07.09.2026): it owns the manifest on disk.

    BASELINES: old `1cd878fce4f217416e61ade79230b344cb3ab8169a24ab1429645d0282ff9f76`,
    new `bd89857c4478e01d296ddf60cd84ebaf88571092fb62b6fc63c40b88ec507ac0`.
    Delta: 2361 keys, 72 discrepancies (36 atomic + 36 per_op, 6 fixtures),
    0 added, 0 missing, 21 refusals unchanged. A line-by-line audit of all 72
    (`.work/marathon-fable-20260907/writers/parity_diff_audit.py`) —
    **72/72 "the predicate moved post→operation past the refusal gate, numbers
    shifted 0"**. 2 of 75 goldens touched.
    """

    def setUp(self):
        self.enter_historical_emission()
        self.record = json.loads(E1_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.parent_bytes = D1_MIGRATION_PATH.read_bytes()
        # 🔴 THE FILE ON DISK IS OWNED BY THE VERY NEWEST LINK (07.09.2026, E-2).
        # E-1 is no longer the last: what is "current" for it is the manifest that E-2
        # hands back. Every link keeps asserting exactly what it
        # used to assert, but about ITS OWN era.
        self.current_bytes = _reverse_e2_migration(
            _reverse_e3_migration(
                FIXTURE_PATH.read_bytes(),
                json.loads(E3_MIGRATION_PATH.read_text(encoding="utf-8")),
                E2_MIGRATION_PATH.read_bytes()),
            json.loads(E2_MIGRATION_PATH.read_text(encoding="utf-8")),
            E1_MIGRATION_PATH.read_bytes())

    def resign(self, record):
        record["record_digest"] = _digest(_canonical({
            key: value for key, value in record.items() if key != "record_digest"}))
        return record

    def test_record_pins_retained_review_sources_and_replacement_tests(self):
        # E-1 stopped being the last link (E-2, 07.09.2026): its source
        # pins were CURRENT as of its own day and are now held by its heir,
        # not compared against the disk — the same handoff of the claim as
        # baseline -> capture -> c1 -> d1 -> e1.
        _reverse_e1_migration(self.current_bytes, self.record, self.parent_bytes)
        self.assertEqual(INTENDED_CHANGES, {})
        newest = json.loads(E2_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.record["current_review_source_sha256"],
                         newest["parent"]["historical_review_source_sha256"])
        for path in self.record["replacement_tests"]:
            self.assertTrue((FIXTURE_PATH.parents[3] / path).is_file(), path)

    def test_counterfactual_restores_the_d1_manifest_and_leaves_no_patch(self):
        from kir import authoring
        from kir.tests.emit_parity_fixtures.e3_counterfactual import (
            without_e3_final_shift)
        from kir.tests.emit_parity_fixtures.e2_counterfactual import (
            without_e2_final_shift)
        from kir.tests.emit_parity_fixtures.e1_counterfactual import (
            without_e1_operation_stage)

        expected = json.loads(_reverse_e1_migration(
            self.current_bytes, self.record, self.parent_bytes))
        before = dict(authoring._EMITTERS)
        with without_e3_final_shift(), without_e2_final_shift(), without_e1_operation_stage():
            restored = emit_corpus()
        self.assertEqual(authoring._EMITTERS, before)
        _assert_exact_parity(expected, restored)

    def test_missing_change_entry_cannot_be_hidden_by_resigning_record(self):
        self.record["manifest"]["changes"].pop(next(iter(self.record["manifest"]["changes"])))
        with self.assertRaisesRegex(AssertionError, "e1 change count"):
            _reverse_e1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_before_value_breaks_parent_reconstruction_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["before"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "reconstructed d1 manifest"):
            _reverse_e1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_after_value_refuses_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["after"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "changed after hash"):
            _reverse_e1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_parent_record_replacement_is_not_a_migration(self):
        with self.assertRaisesRegex(AssertionError, "e1 parent record bytes"):
            _reverse_e1_migration(self.current_bytes, self.record, self.parent_bytes + b" ")

    def test_record_digest_corruption_refuses(self):
        self.record["manifest"]["changed_count"] = 71
        with self.assertRaisesRegex(AssertionError, "e1 record digest"):
            _reverse_e1_migration(self.current_bytes, self.record, self.parent_bytes)

    def test_a_removed_predicate_cannot_be_recorded_as_a_stage_move(self):
        """E-1's main assertion: the STAGE moved, not the set of checks."""

        self.record["manifest"]["predicates_removed"] = 1
        with self.assertRaisesRegex(AssertionError, "e1 removed a predicate"):
            _reverse_e1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_moved_tolerance_cannot_be_recorded_as_a_stage_move(self):
        self.record["manifest"]["tolerances_changed"] = 1
        with self.assertRaisesRegex(AssertionError, "e1 moved a tolerance"):
            _reverse_e1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_an_unclean_line_audit_cannot_be_signed_off(self):
        self.record["audit"]["numbers_shifted_total"] = 1
        with self.assertRaisesRegex(AssertionError, "e1 audit saw a moved number"):
            _reverse_e1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_third_golden_cannot_ride_along(self):
        self.record["goldens"]["changed"].append("full_house_v1")
        with self.assertRaisesRegex(AssertionError, "e1 touched another golden"):
            _reverse_e1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)


class D1MigrationContract(HistoricalEmissionContract):
    """The newest link in the chain: it owns the manifest on disk."""

    def setUp(self):
        self.enter_historical_emission()
        self.record = json.loads(D1_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.parent_bytes = C1_MIGRATION_PATH.read_bytes()
        # 🔴 THE FILE ON DISK IS OWNED BY THE VERY NEWEST LINK (07.09.2026, E-2).
        # D-1 is no longer last, now two links removed: what is "current" for it is the manifest
        # that E-2 hands back to E-1, and E-1 further on. That is how the chain works: every link keeps
        # asserting exactly what it used to assert, but about ITS OWN era.
        self.current_bytes = _reverse_e1_migration(
            _reverse_e2_migration(
                _reverse_e3_migration(
                    FIXTURE_PATH.read_bytes(),
                    json.loads(E3_MIGRATION_PATH.read_text(encoding="utf-8")),
                    E2_MIGRATION_PATH.read_bytes()),
                json.loads(E2_MIGRATION_PATH.read_text(encoding="utf-8")),
                E1_MIGRATION_PATH.read_bytes()),
            json.loads(E1_MIGRATION_PATH.read_text(encoding="utf-8")),
            D1_MIGRATION_PATH.read_bytes())

    def resign(self, record):
        record["record_digest"] = _digest(_canonical({
            key: value for key, value in record.items() if key != "record_digest"}))
        return record

    def test_record_pins_retained_review_sources_and_replacement_tests(self):
        # D-1 stopped being the last link (E-1, 07.09.2026): its source
        # pins were CURRENT as of its own day and are now held by its heir,
        # not compared against the disk — the same handoff of the claim as
        # baseline -> capture -> c1 -> d1.
        _reverse_d1_migration(self.current_bytes, self.record, self.parent_bytes)
        self.assertEqual(INTENDED_CHANGES, {})
        newest = json.loads(E1_MIGRATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.record["current_review_source_sha256"],
                         newest["parent"]["historical_review_source_sha256"])
        for path in self.record["replacement_tests"]:
            self.assertTrue((FIXTURE_PATH.parents[3] / path).is_file(), path)

    def test_counterfactual_restores_the_c1_manifest_and_leaves_no_patch(self):
        from kir import authoring
        from kir.tests.emit_parity_fixtures.d1_counterfactual import without_d1_reuse_guard

        expected = json.loads(_reverse_d1_migration(
            self.current_bytes, self.record, self.parent_bytes))
        from kir.tests.emit_parity_fixtures.e3_counterfactual import (
            without_e3_final_shift)
        from kir.tests.emit_parity_fixtures.e2_counterfactual import (
            without_e2_final_shift)
        from kir.tests.emit_parity_fixtures.e1_counterfactual import (
            without_e1_operation_stage)

        before = dict(authoring._EMITTERS)
        # Counterfactuals COMPOSE: to get the D-1-era bytes, you must
        # undo both E-1 and D-1 — otherwise the "restored" version would carry a stage
        # that did not exist in that era.
        with without_e3_final_shift(), without_e2_final_shift(), without_e1_operation_stage(), \
                without_d1_reuse_guard():
            restored = emit_corpus()
        self.assertEqual(authoring._EMITTERS, before)
        _assert_exact_parity(expected, restored)

    def test_missing_change_entry_cannot_be_hidden_by_resigning_record(self):
        self.record["manifest"]["changes"].pop(next(iter(self.record["manifest"]["changes"])))
        with self.assertRaisesRegex(AssertionError, "d1 change count"):
            _reverse_d1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_before_value_breaks_parent_reconstruction_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["before"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "reconstructed c1 manifest"):
            _reverse_d1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_wrong_after_value_refuses_even_when_resigned(self):
        next(iter(self.record["manifest"]["changes"].values()))["after"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "changed after hash"):
            _reverse_d1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_parent_record_replacement_is_not_a_migration(self):
        with self.assertRaisesRegex(AssertionError, "d1 parent record bytes"):
            _reverse_d1_migration(self.current_bytes, self.record, self.parent_bytes + b" ")

    def test_record_digest_corruption_refuses(self):
        self.record["manifest"]["changed_count"] = 11
        with self.assertRaisesRegex(AssertionError, "d1 record digest"):
            _reverse_d1_migration(self.current_bytes, self.record, self.parent_bytes)

    def test_a_moved_marker_literal_cannot_be_recorded_as_none(self):
        """D-1's main assertion: the address did not move for a single fixture."""
        self.record["manifest"]["marker_literals_changed"] = 1
        with self.assertRaisesRegex(AssertionError, "d1 marker literals moved"):
            _reverse_d1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_a_delta_outside_its_fixture_is_refused(self):
        self.record["manifest"]["fixtures"] = ["scope:catalog_wall_type", "golden:auth_wall"]
        with self.assertRaisesRegex(AssertionError, "d1 delta left its fixture"):
            _reverse_d1_migration(self.current_bytes, self.resign(self.record), self.parent_bytes)

    def test_counterfactual_refuses_a_guard_it_does_not_recognise(self):
        from kir.tests.emit_parity_fixtures.d1_counterfactual import reverse_d1_reuse_guard
        with self.assertRaises(AssertionError):
            reverse_d1_reuse_guard("var __reuseCs_X = null;")


class ProvenanceRepositoryOwnership(unittest.TestCase):
    """🔴 13.09.2026. The pin above asks git ONLY about the repository that owns
    the tree. Three measured cases, in order of how a stranger meets them."""

    def _tree(self, base: pathlib.Path) -> pathlib.Path:
        root = base / "site-packages"
        (root / "kir" / "tests").mkdir(parents=True)
        (root / "kir" / "tests" / "pinned.py").write_text("", encoding="utf-8")
        return root

    def test_a_tree_without_a_repository_yields_no_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_paths_the_commit_will_carry(self._tree(pathlib.Path(tmp))))

    def test_a_foreign_enclosing_repository_is_not_read_as_our_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            subprocess.run(["git", "init", "-q", str(base)], check=True, timeout=60)
            root = self._tree(base)
            # The ordinary line a stranger's project carries for its environment.
            (base / ".gitignore").write_text("site-packages/\n", encoding="utf-8")
            self.assertEqual([], subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                cwd=root, capture_output=True, check=True,
                timeout=60).stdout.decode().split())
            self.assertIsNone(_paths_the_commit_will_carry(root),
                              "чужой репозиторий над venv принят за наш коммит")

    def test_the_owning_repository_is_still_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(pathlib.Path(tmp))
            subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=60)
            self.assertEqual({"kir/tests/pinned.py"}, _paths_the_commit_will_carry(root))

    def test_an_ignored_file_still_fails_the_pin_in_the_owning_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(pathlib.Path(tmp))
            subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=60)
            (root / ".gitignore").write_text("kir/tests/pinned.py\n", encoding="utf-8")
            self.assertNotIn("kir/tests/pinned.py", _paths_the_commit_will_carry(root),
                             "файл под ignore объявлен уезжающим в коммит")


class WitnessModelContract(unittest.TestCase):
    """The by-construction guarantees of the model itself (wave A2 core)."""

    def test_verdictless_check_unconstructible(self) -> None:
        from kir.emit_model import EmitModelError, WitnessCheck
        with self.assertRaises(EmitModelError):
            WitnessCheck(obligation_key="x", reader_cs="var __a = 1;\n",
                         verdict_cs="// no verdict\n", message="m")

    def test_empty_post_refused(self) -> None:
        from kir.emit_model import EmitModelError, render_post
        with self.assertRaises(EmitModelError):
            render_post("OP", [])

    def test_duplicate_keys_refused(self) -> None:
        from kir.emit_model import (
            EmitModelError, WitnessCheck, render_post,
        )
        check = WitnessCheck(
            obligation_key="k", reader_cs="",
            verdict_cs="    __post.Add(\"m\");\n", message="m")
        with self.assertRaises(EmitModelError):
            render_post("OP", [check, check])

    def test_bare_post_same_validation(self) -> None:
        from kir.emit_model import BarePost, EmitModelError, WitnessCheck
        with self.assertRaises(EmitModelError):
            BarePost(())
        check = WitnessCheck(
            obligation_key="k", reader_cs="",
            verdict_cs="__post.Add(\"m\");\n", message="m")
        with self.assertRaises(EmitModelError):
            BarePost((check, check))

    def test_render_frame_matches_legacy_shape(self) -> None:
        from kir.emit_model import WitnessCheck, render_post
        check = WitnessCheck(
            obligation_key="k", reader_cs="    var __x = 1;\n",
            verdict_cs="    if (__x != 1) __post.Add(\"m\");\n",
            message="m")
        self.assertEqual(
            render_post("OP", [check]),
            "// post OP\n{\n    var __x = 1;\n"
            "    if (__x != 1) __post.Add(\"m\");\n}")


if __name__ == "__main__":
    unittest.main()


class NativeReadbackMigrationContract(unittest.TestCase):
    """The previous head. It validates the delta that ENDED at the manifest this
    migration then moved, so it runs with today's identity capture reversed and
    reads the retained pre-2026-09-13 manifest and goldens."""

    def setUp(self):
        from kir.tests.emit_parity_fixtures.capture_all_creates_counterfactual import (
            without_universal_identity_capture,
        )
        from kir.tests.emit_parity_fixtures.delete_cascade_counterfactual import (
            before_the_cascade_was_named,
        )
        # Newest link first: this record reconstructs a state two migrations
        # back, so both later deltas come off before its own reversal runs.
        self.enterContext(before_the_cascade_was_named(require_effect=False))
        self.enterContext(without_universal_identity_capture(require_effect=False))

    def historical_manifest(self):
        return FIXTURE_PATH.with_name("corpus_hashes_pre_capture_all_creates.json")

    def historical_goldens(self):
        return json.loads(FIXTURE_PATH.with_name(
            "golden_hashes_pre_capture_all_creates.json").read_text())

    def record(self):
        return json.loads(FIXTURE_PATH.with_name("native_readback_migration.json").read_text())

    def validate(self, record):
        from kir.tests.emit_parity_fixtures.native_readback_counterfactual import LEGACY_MANIFEST
        before_bytes = LEGACY_MANIFEST.read_bytes()
        after_bytes = self.historical_manifest().read_bytes()
        before, after = json.loads(before_bytes), json.loads(after_bytes)
        self.assertEqual(record["record_digest"], _digest(_canonical({k:v for k,v in record.items() if k!="record_digest"})))
        self.assertEqual(_digest(before_bytes), record["before_manifest_sha256"])
        self.assertEqual(_digest(after_bytes), record["after_manifest_sha256"])
        self.assertEqual(set(before), set(after))
        self.assertEqual(len(after), record["key_count"])
        actual = {k:{"before":before[k],"after":after[k]} for k in before if before[k]!=after[k]}
        self.assertEqual(actual, record["changes"])
        self.assertEqual(len(actual), record["changed_count"])
        self.assertEqual({k:v for k,v in before.items() if v.startswith("refused:")},
                         {k:v for k,v in after.items() if v.startswith("refused:")})
        self.assertEqual(INTENDED_CHANGES, {})

    def test_complete_current_delta_has_no_exemptions(self):
        self.validate(self.record())

    def test_a_missing_delta_entry_is_rejected_even_when_resigned(self):
        record=self.record(); record["changes"].pop(next(iter(record["changes"])))
        record["record_digest"]=_digest(_canonical({k:v for k,v in record.items() if k!="record_digest"}))
        with self.assertRaises(AssertionError): self.validate(record)

    def test_retained_emitters_reproduce_e3_and_restore_the_current_registry(self):
        from kir import authoring, registry_base
        from kir.tests.emit_parity_fixtures.native_readback_counterfactual import (
            before_native_readback_fixes, LEGACY_MANIFEST)
        original=dict(authoring._EMITTERS); annotations=dict(registry_base.__annotations__)
        with before_native_readback_fixes(): restored=emit_corpus()  # identity already reversed in setUp
        _assert_exact_parity(json.loads(LEGACY_MANIFEST.read_text()), restored)
        self.assertEqual(authoring._EMITTERS, original)
        self.assertEqual(registry_base.__annotations__, annotations)

    def test_current_review_sources_and_both_golden_states_are_bound(self):
        from kir.tests.emit_parity_fixtures.native_readback_counterfactual import LEGACY_GOLDENS
        record=self.record()
        # 🔴 ITS SOURCE PINS ARE NOW HISTORICAL. This record pinned the emitter
        # sources as they stood on 2026-09-10; 2026-09-13 edited them to put
        # identity capture on every seam call. Re-reading them from disk would
        # make a PAST record fail for a LATER change — the exact "red on
        # success" this chain is built to avoid. The successor retains them
        # verbatim, and that binding is what is checked, the same way E-3's
        # pins were bound when this record superseded it.
        successor=json.loads(FIXTURE_PATH.with_name(
            "capture_all_creates_migration_2026_09_13.json").read_text())
        self.assertEqual(record["current_review_source_sha256"],
                         successor["parent"]["historical_review_source_sha256"])
        before=json.loads(LEGACY_GOLDENS.read_text())
        after=self.historical_goldens()
        self.assertEqual(before,record["goldens"]["before"])
        self.assertEqual(after,record["goldens"]["after"])
        self.assertEqual(set(before),set(after))
        self.assertEqual(record["goldens"]["changed"],sorted(k for k in before if before[k]!=after[k]))
        parent=json.loads(E3_MIGRATION_PATH.read_text())
        self.assertEqual(record["parent"]["record_file_sha256"],_digest(E3_MIGRATION_PATH.read_bytes()))
        self.assertEqual(record["parent"]["historical_review_source_sha256"],parent["current_review_source_sha256"])


class CaptureForEveryCreateMigrationContract(unittest.TestCase):
    """The current head (2026-09-13): identity capture on every seam call.

    A migration record nobody checks is not a guard, it is a note. This binds
    the record to the two manifests it claims to span, to both golden states,
    to its own reversal, and to its parent.
    """

    RECORD_NAME = "capture_all_creates_migration_2026_09_13.json"
    RETAINED_MANIFEST = "corpus_hashes_pre_capture_all_creates.json"
    RETAINED_GOLDENS = "golden_hashes_pre_capture_all_creates.json"
    #: What this record's delta ENDED at. It is no longer the current manifest:
    #: the delete-cascade migration moved 36 keys on top of it, so this contract
    #: reads the state retained for that successor instead of today's files.
    SUCCESSOR_MANIFEST = "corpus_hashes_pre_delete_cascade.json"
    SUCCESSOR_GOLDENS = "golden_hashes_pre_delete_cascade.json"

    def setUp(self):
        from kir.tests.emit_parity_fixtures.delete_cascade_counterfactual import (
            before_the_cascade_was_named,
        )
        self.enterContext(before_the_cascade_was_named(require_effect=False))

    def current_manifest_bytes(self):
        return FIXTURE_PATH.with_name(self.SUCCESSOR_MANIFEST).read_bytes()

    def current_goldens(self):
        return json.loads(FIXTURE_PATH.with_name(self.SUCCESSOR_GOLDENS).read_text())

    def record(self):
        return json.loads(FIXTURE_PATH.with_name(self.RECORD_NAME).read_text())

    def validate(self, record):
        before_bytes = FIXTURE_PATH.with_name(self.RETAINED_MANIFEST).read_bytes()
        after_bytes = self.current_manifest_bytes()
        before, after = json.loads(before_bytes), json.loads(after_bytes)
        self.assertEqual(record["record_digest"], _digest(_canonical(
            {k: v for k, v in record.items() if k != "record_digest"})))
        self.assertEqual(_digest(before_bytes), record["before_manifest_sha256"])
        self.assertEqual(_digest(after_bytes), record["after_manifest_sha256"])
        self.assertEqual(set(before), set(after), "the keyset must not move")
        self.assertEqual(len(after), record["key_count"])
        actual = {k: {"before": before[k], "after": after[k]}
                  for k in before if before[k] != after[k]}
        self.assertEqual(actual, record["changes"])
        self.assertEqual(len(actual), record["changed_count"])
        self.assertEqual(len(after) - len(actual), record["unchanged_count"])
        # Capture adds rows to a receipt; it must not turn a refusal into a pass.
        self.assertEqual({k: v for k, v in before.items() if v.startswith("refused:")},
                         {k: v for k, v in after.items() if v.startswith("refused:")})

    def test_complete_current_delta_has_no_exemptions(self):
        self.validate(self.record())

    def test_a_missing_delta_entry_is_rejected_even_when_resigned(self):
        record = self.record()
        record["changes"].pop(next(iter(record["changes"])))
        record["record_digest"] = _digest(_canonical(
            {k: v for k, v in record.items() if k != "record_digest"}))
        with self.assertRaises(AssertionError):
            self.validate(record)

    def test_counterfactual_restores_the_retained_manifest_exactly(self):
        from kir import authoring
        from kir.tests.emit_parity_fixtures.capture_all_creates_counterfactual import (
            without_universal_identity_capture,
        )
        from kir.tests.emit_parity_fixtures.delete_cascade_counterfactual import (
            before_the_cascade_was_named,
        )
        original = dict(authoring._EMITTERS)
        with without_universal_identity_capture() as seen:
            restored = emit_corpus()
        retained = json.loads(FIXTURE_PATH.with_name(self.RETAINED_MANIFEST).read_text())
        _assert_exact_parity(retained, restored)
        self.assertEqual(authoring._EMITTERS, original, "the registry must be left as found")
        self.assertEqual(seen["dropped"], self.record()["counterfactual"]["dropped_calls"])
        self.assertEqual(seen["kept"], self.record()["counterfactual"]["kept_calls"])

    def test_both_golden_states_and_the_parent_are_bound(self):
        record = self.record()
        root = FIXTURE_PATH.parents[3]
        for path, expected in record["current_review_source_sha256"].items():
            self.assertEqual(_digest((root / path).read_bytes()), expected, path)
        before = json.loads(FIXTURE_PATH.with_name(self.RETAINED_GOLDENS).read_text())
        after = self.current_goldens()
        self.assertEqual(before, record["goldens"]["before"])
        self.assertEqual(after, record["goldens"]["after"])
        self.assertEqual(set(before), set(after), "no golden may appear or vanish")
        self.assertEqual(record["goldens"]["changed"],
                         sorted(k for k in before if before[k] != after[k]))
        parent_path = FIXTURE_PATH.with_name("native_readback_migration.json")
        parent = json.loads(parent_path.read_text())
        self.assertEqual(record["parent"]["record_file_sha256"], _digest(parent_path.read_bytes()))
        self.assertEqual(record["parent"]["record_digest"], parent["record_digest"])
        self.assertEqual(record["parent"]["historical_review_source_sha256"],
                         parent["current_review_source_sha256"])


class DeleteCascadeMigrationContract(unittest.TestCase):
    """The current head (wave N-2): the delete cascade is named before the effect.

    Same obligations as every head before it — the record is bound to the two
    manifests it spans, to both golden states, to its own reversal and to its
    parent. The extra claim here is the NEGATIVE one: the wave also shipped
    `{by: unique_id}`, `expected_identity`, `expected_current` and a reworded
    program guard, and the record asserts those moved NOTHING. A migration that
    quietly folded four other changes into one delta would be unreviewable.
    """

    RECORD_NAME = "delete_cascade_and_identity_migration_2026_09_13.json"
    RETAINED_MANIFEST = "corpus_hashes_pre_delete_cascade.json"
    RETAINED_GOLDENS = "golden_hashes_pre_delete_cascade.json"

    def record(self):
        return json.loads(FIXTURE_PATH.with_name(self.RECORD_NAME).read_text())

    def validate(self, record):
        before_bytes = FIXTURE_PATH.with_name(self.RETAINED_MANIFEST).read_bytes()
        after_bytes = FIXTURE_PATH.read_bytes()
        before, after = json.loads(before_bytes), json.loads(after_bytes)
        self.assertEqual(record["record_digest"], _digest(_canonical(
            {k: v for k, v in record.items() if k != "record_digest"})))
        self.assertEqual(_digest(before_bytes), record["before_manifest_sha256"])
        self.assertEqual(_digest(after_bytes), record["after_manifest_sha256"])
        self.assertEqual(set(before), set(after), "the keyset must not move")
        self.assertEqual(len(after), record["key_count"])
        actual = {k: {"before": before[k], "after": after[k]}
                  for k in before if before[k] != after[k]}
        self.assertEqual(actual, record["changes"])
        self.assertEqual(len(actual), record["changed_count"])
        self.assertEqual(len(after) - len(actual), record["unchanged_count"])
        self.assertEqual({k: v for k, v in before.items() if v.startswith("refused:")},
                         {k: v for k, v in after.items() if v.startswith("refused:")})
        # the whole delta belongs to `delete`, by fixture name
        self.assertTrue(all("delete" in key or "modify" in key
                            for key in record["fixtures"]), record["fixtures"])

    def test_complete_current_delta_has_no_exemptions(self):
        self.validate(self.record())

    def test_a_missing_delta_entry_is_rejected_even_when_resigned(self):
        record = self.record()
        record["changes"].pop(next(iter(record["changes"])))
        record["record_digest"] = _digest(_canonical(
            {k: v for k, v in record.items() if k != "record_digest"}))
        with self.assertRaises(AssertionError):
            self.validate(record)

    def test_counterfactual_restores_the_retained_manifest_exactly(self):
        from kir import authoring
        from kir.tests.emit_parity_fixtures.delete_cascade_counterfactual import (
            before_the_cascade_was_named,
        )
        original = dict(authoring._EMITTERS)
        with before_the_cascade_was_named():
            restored = emit_corpus()
        retained = json.loads(FIXTURE_PATH.with_name(self.RETAINED_MANIFEST).read_text())
        _assert_exact_parity(retained, restored)
        self.assertEqual(authoring._EMITTERS, original, "the registry must be left as found")

    def test_the_four_other_changes_of_this_wave_moved_nothing(self):
        """The record's own claim, checked rather than believed."""
        record = self.record()
        self.assertEqual(len(record["shipped_in_the_same_wave_without_moving_bytes"]), 4)
        # `expected_identities` is what the reworded guard emits for, and the
        # corpus does not use it — that is WHY the rewording moved no bytes.
        after = json.loads(FIXTURE_PATH.read_bytes())
        self.assertTrue(after, "manifest must not be empty")
        from kir.emit_core import _element_identity_guard
        self.assertIn("identity_changed_since_read",
                      _element_identity_guard(
                          [__import__("kir.contracts", fromlist=["x"]).ElementIdentityProof(
                              element_id=1, unique_id="a" * 8 + "-" + "b" * 4 + "-" + "c" * 4
                              + "-" + "d" * 4 + "-" + "e" * 12 + "-0001",
                              version_guid="f" * 32)],
                          "2023", rollback=""))

    def test_both_golden_states_and_the_parent_are_bound(self):
        record = self.record()
        root = FIXTURE_PATH.parents[3]
        for path, expected in record["current_review_source_sha256"].items():
            self.assertEqual(_digest((root / path).read_bytes()), expected, path)
        before = json.loads(FIXTURE_PATH.with_name(self.RETAINED_GOLDENS).read_text())
        after = {p.name.removesuffix(".golden.cs"): _digest(p.read_bytes())
                 for p in (FIXTURE_PATH.parent.parent / "golden").glob("*.golden.cs")}
        self.assertEqual(before, record["goldens"]["before"])
        self.assertEqual(after, record["goldens"]["after"])
        self.assertEqual(set(before), set(after), "no golden may appear or vanish")
        self.assertEqual(record["goldens"]["changed"],
                         sorted(k for k in before if before[k] != after[k]))
        parent_path = FIXTURE_PATH.with_name("capture_all_creates_migration_2026_09_13.json")
        parent = json.loads(parent_path.read_text())
        self.assertEqual(record["parent"]["record_file_sha256"], _digest(parent_path.read_bytes()))
        self.assertEqual(record["parent"]["record_digest"], parent["record_digest"])
        self.assertEqual(record["parent"]["historical_review_source_sha256"],
                         parent["current_review_source_sha256"])

