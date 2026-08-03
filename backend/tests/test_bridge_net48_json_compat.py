"""Static runtime-compatibility gate for Revit 2021-2024 JSON calls.

The net48 bridge shares one AppDomain with Revit and every other add-in.  A
preloaded older System.Text.Json can therefore win assembly binding even when
our OTA package contains the pinned closure.  Compiling JsonDocument.Parse
against a byte/ReadOnlyMemory overload caused live Revit 2023 execution to
finish and then lose its durable receipt.

This gate is intentionally source-wide: renaming the local byte variable must
not reopen the MissingMethodException class.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "src" / "Kukai.Revit.Bridge"
PROJECT = BRIDGE / "Kukai.Revit.Bridge.csproj"


def test_serialized_utf8_bytes_are_never_passed_to_json_document_parse() -> None:
    violations: list[str] = []
    for source in BRIDGE.rglob("*.cs"):
        text = source.read_text(encoding="utf-8")
        byte_vars = re.findall(
            r"(?:var|byte\s*\[\])\s+([A-Za-z_][A-Za-z0-9_]*)\s*="
            r"\s*JsonSerializer\.SerializeToUtf8Bytes\s*\(",
            text,
        )
        for variable in byte_vars:
            if re.search(
                rf"JsonDocument\.Parse\s*\(\s*{re.escape(variable)}\b",
                text,
            ):
                violations.append(f"{source.relative_to(ROOT)}:{variable}")

    assert not violations, (
        "net48-incompatible JsonDocument.Parse(byte[]) call(s): "
        + ", ".join(violations)
    )


def test_receipt_and_result_paths_use_lowest_common_denominator_helper() -> None:
    compat = (BRIDGE / "Compat" / "JsonCompat.cs").read_text(encoding="utf-8")
    journal = (BRIDGE / "Operations" / "OperationJournal.cs").read_text(
        encoding="utf-8"
    )
    window = (BRIDGE / "UI" / "ChatWindow.cs").read_text(encoding="utf-8")

    assert "JsonSerializer.Serialize(value, options)" in compat
    assert "JsonDocument.Parse(json)" in compat
    assert "JsonCompat.SerializeToDocument(value, options)" in journal
    assert "JsonCompat.SerializeToDocument(" in window


def test_net48_json_package_is_pinned_to_the_version_revit_2023_can_load() -> None:
    """6.0.0, not the later 6.0.x patch — measured, not preferred.

    Bumping to 6.0.10 (2026-07-26) made EVERY execute on Revit 2023 fail with
    `Метод не найден: JsonDocument.Parse(ReadOnlyMemory<Byte>, ...)`: Revit has
    already loaded its own System.Text.Json by the time the add-in resolves, so
    the reference must match what is in the process, and a "newer patch level"
    is exactly the wrong axis to optimise. 22 consecutive failed executes on the
    operator's machine before the revert. Whoever raises this again: run
    tools/client_smoke.py on a net48 Revit first."""
    project = PROJECT.read_text(encoding="utf-8")
    assert 'System.Text.Json" Version="6.0.0"' in project
    assert 'System.Text.Json" Version="6.0.10"' not in project
