"""VersionSelector — Revit-version-specific API choices for code generation.

Per spec Section 5.3 + role-play audit finding: subagent must know which
ElementId property to use (IntegerValue vs Value), which unit API to use
(DisplayUnitType vs ForgeTypeId), and which .NET runtime targets.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class VersionInfo:
    revit_version: str
    dotnet: str                       # "net48" | "net8.0"
    element_id_property: str           # "IntegerValue" pre-2024 | "Value" 2024+
    unit_api: str                      # "DisplayUnitType" pre-2022 | "ForgeTypeId" 2022+


_TABLE: dict[str, VersionInfo] = {
    "2021": VersionInfo("2021", "net48", "IntegerValue", "DisplayUnitType"),
    "2022": VersionInfo("2022", "net48", "IntegerValue", "ForgeTypeId"),
    "2023": VersionInfo("2023", "net48", "IntegerValue", "ForgeTypeId"),
    "2024": VersionInfo("2024", "net48", "Value", "ForgeTypeId"),
    "2025": VersionInfo("2025", "net8.0", "Value", "ForgeTypeId"),
    "2026": VersionInfo("2026", "net8.0", "Value", "ForgeTypeId"),
}


class VersionSelector:
    def __init__(self, revit_version: str):
        self._version = revit_version

    def info(self) -> VersionInfo:
        try:
            return _TABLE[self._version]
        except KeyError as e:
            raise ValueError(f"unsupported revit_version={self._version!r}; known: {sorted(_TABLE)}") from e
