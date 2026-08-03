"""Tests for VersionSelector."""
from __future__ import annotations
import pytest

from kukai.modeling.resolver.version_selector import VersionSelector


class TestVersionSelector:
    def test_revit_2026(self):
        v = VersionSelector("2026")
        info = v.info()
        assert info.element_id_property == "Value"
        assert info.unit_api == "ForgeTypeId"
        assert info.dotnet == "net8.0"

    def test_revit_2024(self):
        v = VersionSelector("2024")
        info = v.info()
        assert info.element_id_property == "Value"
        assert info.unit_api == "ForgeTypeId"
        assert info.dotnet == "net48"

    def test_revit_2023(self):
        v = VersionSelector("2023")
        info = v.info()
        assert info.element_id_property == "IntegerValue"
        assert info.unit_api == "ForgeTypeId"

    def test_revit_2021_unit_api(self):
        v = VersionSelector("2021")
        info = v.info()
        assert info.unit_api == "DisplayUnitType"
        assert info.element_id_property == "IntegerValue"

    def test_unknown_version_raises(self):
        with pytest.raises(ValueError, match="unsupported"):
            VersionSelector("2030").info()
