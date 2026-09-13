"""Regression contract for fail-closed compiler panic reporting."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from unittest import mock

import pytest

from kir.compiler import compile_program, plan_program
from kir.open_model import (
    OPEN_MODEL_PROFILE_SCHEMA_VERSION,
    OpenModelProfile,
)


_SECRET = "private-payload-fragment-7d6f"
_REVIT_SECRET = "TOPSECRET123"
_LOGGER = "kir.compiler"


def _query_program() -> dict:
    return {
        "ir_version": "1.0",
        "ops": [{"op": "query_count", "id": "q", "kind": "wall"}],
    }


def _wall_program() -> dict:
    return {
        "ir_version": "1.0",
        "ops": [{
            "op": "create_wall",
            "id": "w",
            "p0_mm": [0, 0],
            "p1_mm": [5000, 0],
            "level": {"by": "name", "value": "L1"},
        }],
    }


def _empty_open_model_profile() -> OpenModelProfile:
    return OpenModelProfile(
        schema_version=OPEN_MODEL_PROFILE_SCHEMA_VERSION,
        document_fingerprint=None,
        revit_version="2026",
        revit_build=None,
        required_pools=(),
        pools=(),
    )


def _raise_at(stage: str):
    failure = RuntimeError(_SECRET)
    if stage == "plan":
        with mock.patch("kir.compiler.plan_program", side_effect=failure):
            return compile_program(
                {"ir_version": "1.0", "ops": [], "payload": _SECRET},
                query_id=_SECRET,
            )

    if stage == "target_profile":
        planned = plan_program(_query_program())
        with mock.patch(
            "kir.compiler.plan_program", return_value=planned
        ), mock.patch.object(type(planned), "to_ops", side_effect=failure):
            return compile_program(
                _query_program(), query_id=_SECRET)

    if stage == "emit_query":
        with mock.patch("kir.compiler.emit_for_version", side_effect=failure):
            return compile_program(
                _query_program(), query_id=_SECRET)

    program = _wall_program()
    # 🔴 A STAND-IN GROUNDER MUST RETURN SOMETHING GROUNDED (30.08.2026,
    # F-103). Here stood `plan_program(program).to_ops()` — that is, a plan
    # playing the role of a grounded program, with an author selector
    # `{by: name}`. `GroundedProgram` now rejects exactly this fake, and
    # the rig would have failed at the `ground` stage, never reaching the
    # one it is meant to check.
    #
    # The subject of these tests is the CORRELATION OF PANIC across
    # stages, not grounding; so the scaffolding must be honest rather than
    # weaken the check. We take the REAL grounding result on a snapshot
    # where the selector resolves.
    _ground_snapshot = {"levels": [{"id": 501, "name": "L1",
                                    "elevation_mm": 0}]}
    _real = compile_program(program, snapshot=_ground_snapshot)
    assert _real.grounded is not None, "лес не собрался: заземление не удалось"
    grounded = _real.grounded.to_ops()
    ground_patch = mock.patch(
        "kir.ground.ground", return_value=grounded)
    if stage == "ground":
        ground_patch = mock.patch(
            "kir.ground.ground", side_effect=failure)
        with ground_patch:
            return compile_program(
                program, snapshot={}, query_id=_SECRET)

    if stage == "open_model_preflight":
        profile = _empty_open_model_profile()
        with ground_patch, mock.patch(
            "kir.open_model.preflight_programs", side_effect=failure
        ):
            return compile_program(
                program,
                snapshot=profile.to_ground_snapshot(),
                open_model_profile=profile,
                query_id=_SECRET,
            )

    if stage == "emit_authoring":
        with ground_patch, mock.patch(
            "kir.authoring.emit_program", side_effect=failure
        ):
            return compile_program(
                program, snapshot={}, query_id=_SECRET)

    raise AssertionError(f"unknown test stage: {stage}")


@pytest.mark.parametrize("stage", [
    "plan",
    "target_profile",
    "ground",
    "open_model_preflight",
    "emit_authoring",
    "emit_query",
])
def test_panic_is_correlated_without_leaking_exception_or_payload(
    stage: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger=_LOGGER)

    out = _raise_at(stage)

    assert not out.ok
    assert len(out.diagnostics) == 1
    diagnostic = out.diagnostics[0]
    assert diagnostic.code == "KIR-P000"
    assert diagnostic.message_ru == "внутренняя ошибка компилятора"
    assert diagnostic.incident_id is not None
    assert len(diagnostic.incident_id) == 32
    int(diagnostic.incident_id, 16)
    assert diagnostic.as_dict() == {
        "code": "KIR-P000",
        "message_ru": "внутренняя ошибка компилятора",
        "incident_id": diagnostic.incident_id,
    }

    wire = json.dumps(out.as_dict(), ensure_ascii=False, sort_keys=True)
    records = [record for record in caplog.records if record.name == _LOGGER]
    assert len(records) == 1
    record = records[0]
    log_text = caplog.text

    assert _SECRET not in wire
    assert _SECRET not in log_text
    assert "RuntimeError" not in wire
    assert "RuntimeError" not in log_text
    assert "Traceback" not in log_text
    assert record.exc_info is None
    assert record.exc_text is None
    assert f"incident_id={diagnostic.incident_id}" in log_text
    assert f"stage={stage}" in log_text
    assert "revit_version=2026" in log_text
    assert "query_id_or_digest=sha256:" in log_text
    if stage == "plan":
        assert "plan_digest=-" in log_text
    else:
        assert re.search(r"plan_digest=[0-9a-f]{64}(?:\s|$)", log_text)
    assert "input_type=dict" in log_text


def test_caller_controlled_revit_version_is_hashed_in_panic_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger=_LOGGER)
    with mock.patch(
        "kir.compiler.plan_program", side_effect=RuntimeError(_SECRET)
    ):
        out = compile_program(_query_program(), revit_version=_REVIT_SECRET)

    wire = json.dumps(out.as_dict(), ensure_ascii=False, sort_keys=True)
    assert _REVIT_SECRET not in wire
    assert _REVIT_SECRET not in caplog.text
    assert "revit_version=sha256:" in caplog.text


@pytest.mark.parametrize(
    "revit_version", ("2021", "2022", "2023", "2024", "2025", "2026")
)
def test_supported_revit_version_is_readable_in_panic_log(
    revit_version: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger=_LOGGER)
    with mock.patch(
        "kir.compiler.plan_program", side_effect=RuntimeError(_SECRET)
    ):
        compile_program(_query_program(), revit_version=revit_version)

    assert f"revit_version={revit_version}" in caplog.text
    assert _SECRET not in caplog.text


@pytest.mark.parametrize(("program", "revit_version", "expected_sha256"), [
    (
        _query_program(),
        "2026",
        # PlannedProgram/3 additionally binds nested-operation contracts.
        # 25.08.2026: the query door had ITS OWN level-reading chain of
        # four BuiltInParameters against seven at the authority; the copy
        # was silently handing beams an empty level (measured 03.08: 2,367
        # beams, 116 stairs, 21 railings with level_id=null). The chain now
        # comes from `revit_read_helpers`, and the wire's bytes shifted by
        # exactly that. The neighboring «2099» case did NOT shift — there
        # the refusal is by version, there is no emission at all; that is
        # exactly the control proving that it was this and only this that
        # moved.
        #
        # 🔴 THE NUMBER WAS RE-MEASURED ON 01.09.2026, AND THE CAUSE WAS
        # FOUND, NOT FITTED. The golden stood red; verified on CLEAN copies
        # from git, with no working-tree edits (`git archive <sha> | tar
        # -x`, run with the production venv
        # `/opt/kukai-rebuild1/backend/venv/bin/python`):
        #
        #     8eda450 (27.08, the split)  c5549b89…  <- already NOT equal
        #                                                to the golden
        #     HEAD    (01.09)             ce593f0a…
        #
        # That is, it went stale TWICE, and the first shift predates the
        # split: the golden `16a0bd…` does not reproduce at either point.
        #
        # The second shift is identified by name. The difference in the
        # wire between 8eda450 and HEAD is EXACTLY one new helper in the
        # query preamble: `__ImageTypeOf` (S-07, 30.08.2026: an underlay
        # marker must ask the `Source` and `Path` kind, not the type name,
        # which Revit appends with page and copy suffixes). The helper
        # rides along in EVERY query program, so both the bytes and
        # `plan_digest` shifted (e017f0e5… -> fa057361…). Nothing else in
        # the wire changed: a `diff` of the two decompiles yields two
        # lines — `csharp` and `plan_digest`.
        #
        # The control is in place and holds: the «2099» case below is NOT
        # touched and stays green, meaning it was the emission that
        # shifted, not the serialization or the refusal.
        "ce593f0aae854b49fcfb8f5209a31ff1914ddf1a3e201db3f3cbb6436d108111",
    ),
    (
        _query_program(),
        "2099",
        "6a0c4904beffe90ed6c39ea820304eb60685939ad8e3481c498a62ee072c9e4f",
    ),
])
def test_nonpanic_wire_output_is_byte_compatible(
    program: dict,
    revit_version: str,
    expected_sha256: str,
) -> None:
    with mock.patch("kir.coverage_feed.record_rejections"):
        out = compile_program(program, revit_version=revit_version)
    wire = json.dumps(
        out.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    assert hashlib.sha256(wire).hexdigest() == expected_sha256
    assert b"incident_id" not in wire
