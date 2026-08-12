from __future__ import annotations

import json
import os

from kukai.ir import coverage_feed, serving
from kukai.ir.diag import Diagnostic


def _read(path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_compile_rejection_has_distinct_identity_axes(tmp_path, monkeypatch):
    path = tmp_path / "rejections.jsonl"
    monkeypatch.setenv(coverage_feed._ENV, str(path))
    diagnostics = [
        Diagnostic(code="KIR-T001", op_index=index, op_id=f"W{index}",
                   message_ru=f"ошибка {index}")
        for index in range(3)
    ]

    coverage_feed.record_rejections(
        diagnostics,
        [{"op": "create_wall", "id": f"W{index}"} for index in range(3)],
        query_id="legacy-join-key",
        turn_id="turn-1",
        action_id="action-1",
        query_fingerprint="same-prompt-fingerprint",
        source_kind="chat",
    )

    rows = _read(path)
    assert len(rows) == 3
    assert len({row["attempt_id"] for row in rows}) == 1
    assert all(row["attempt_diagnostics"] == 3 for row in rows)
    assert all(row["stage"] == "compile" for row in rows)
    assert all(row["turn_id"] == "turn-1" for row in rows)
    assert all(row["action_id"] == "action-1" for row in rows)
    assert all(row["query_fingerprint"] == "same-prompt-fingerprint"
               for row in rows)
    assert all(row["source_kind"] == "chat" for row in rows)


def test_two_rejection_calls_with_same_prompt_are_distinct_attempts(
    tmp_path, monkeypatch,
):
    path = tmp_path / "rejections.jsonl"
    monkeypatch.setenv(coverage_feed._ENV, str(path))
    diagnostic = Diagnostic(code="KIR-L001", message_ru="слишком много опов")

    for turn_id in ("turn-1", "turn-2"):
        coverage_feed.record_rejections(
            [diagnostic], [], turn_id=turn_id,
            query_fingerprint="same-prompt", source_kind="chat")

    first, second = _read(path)
    assert first["attempt_id"] != second["attempt_id"]
    assert first["query_fingerprint"] == second["query_fingerprint"]
    assert {first["turn_id"], second["turn_id"]} == {"turn-1", "turn-2"}


def test_missing_caller_identity_is_explicit_not_invented(tmp_path, monkeypatch):
    path = tmp_path / "rejections.jsonl"
    monkeypatch.setenv(coverage_feed._ENV, str(path))

    coverage_feed.record_rejections(
        [Diagnostic(code="KIR-L001", message_ru="слишком много опов")], [])

    [row] = _read(path)
    assert row["attempt_id"]
    assert row["turn_id"] is None
    assert row["action_id"] is None
    assert row["query_fingerprint"] is None
    assert row["source_kind"] == "unknown"


def test_pre_effect_refusal_keeps_stage_and_diagnostic_context(
    tmp_path, monkeypatch,
):
    rejection_path = tmp_path / "rejections.jsonl"
    witness_path = tmp_path / "witness.jsonl"
    monkeypatch.setenv(coverage_feed._ENV, str(rejection_path))
    monkeypatch.setenv("KIR_WITNESS_PATH", str(witness_path))

    serving._record_pre_effect(
        "translation_certificate",
        [Diagnostic(
            code="KIR-R002", op_index=0, op_id="W1", field_name="geometry",
            message_ru="свидетель доказуемо не может сработать",
        ).as_dict()],
        [{"op": "create_wall", "id": "W1"}],
        query_id="legacy-join-key",
        turn_id="turn-1",
        action_id="action-1",
        query_fingerprint="prompt-fingerprint",
        source_kind="chat",
        revit_version="2026",
    )

    [row] = _read(rejection_path)
    assert row["stage"] == "translation_certificate"
    assert row["diag_code"] == "KIR-R002"
    assert row["op_id"] == "W1"
    assert row["op_requested"] == "create_wall"
    assert row["turn_id"] == "turn-1"
    assert row["action_id"] == "action-1"
    assert row["source_kind"] == "chat"
    assert not witness_path.exists()


def test_acceptance_pre_effect_refusal_uses_its_own_stage(
    tmp_path, monkeypatch,
):
    path = tmp_path / "rejections.jsonl"
    monkeypatch.setenv(coverage_feed._ENV, str(path))

    serving._record_pre_effect(
        "acceptance_prepare",
        [Diagnostic(code="KIR-A005", message_ru="приёмка не подготовлена")],
        [{"op": "create_wall", "id": "W1"}],
        source_kind="admin",
        revit_version="2023",
    )

    [row] = _read(path)
    assert row["stage"] == "acceptance_prepare"
    assert row["diag_code"] == "KIR-A005"
    assert row["source_kind"] == "admin"
