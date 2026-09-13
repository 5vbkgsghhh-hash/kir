"""Environment diagnostics preserve alias precedence and never reveal values."""
import json

from kir import env
from kir.__main__ import main


def test_alias_report_preserves_empty_new_value_and_does_not_change_environment(monkeypatch):
    key = "KIR_CHECKER_V2"
    former = env.RENAMED[key]
    monkeypatch.setenv(former, "legacy-private-value")
    monkeypatch.delenv(key, raising=False)
    row = next(row for row in env.describe() if row["name"] == key)
    assert row["source"] == "legacy" and row["value_state"] == "set"
    assert row["legacy_present"] is True and row["scope"] == "known_alias"
    monkeypatch.setenv(key, "")
    row = next(row for row in env.describe() if row["name"] == key)
    assert row["source"] == "new" and row["value_state"] == "empty"
    assert env.get(key) == ""
    monkeypatch.delenv(key)
    monkeypatch.delenv(former)
    row = next(row for row in env.describe() if row["name"] == key)
    assert row["source"] == row["value_state"] == "unset"


def test_present_names_without_aliases_are_not_claimed_as_registered_settings(monkeypatch):
    name = "KIR_DIAGNOSTIC_EXAMPLE_UNREGISTERED"
    monkeypatch.setenv(name, "private-even-without-secret-in-the-name")
    monkeypatch.setenv("KIR_DIAGNOSTIC_TOKEN", "token-private-value")
    monkeypatch.setenv("UNRELATED_TOKEN", "unrelated-private-value")
    rows = env.describe()
    indexed = {row["name"]: row for row in rows}
    assert indexed[name]["scope"] == "present_only"
    assert indexed[name]["former_name"] is None
    assert "UNRELATED_TOKEN" not in indexed
    assert name not in env.RENAMED
    encoded = json.dumps(rows)
    assert "private-even-without-secret-in-the-name" not in encoded
    assert "token-private-value" not in encoded
    assert "unrelated-private-value" not in encoded
    assert list(indexed) == sorted(indexed)


def test_cli_reports_only_names_and_sources_without_running_the_regular_doctor(monkeypatch, capsys):
    import kir.__main__ as cli

    def no_compile():
        raise AssertionError("--env must not compile or ask a live host")

    monkeypatch.setattr(cli, "_measure_offline_compile", no_compile)
    monkeypatch.setenv("KIR_DIAGNOSTIC_PASSWORD", "not-for-the-console")
    assert main(["doctor", "--env"]) == 0
    output = capsys.readouterr().out
    assert "KIR_DIAGNOSTIC_PASSWORD" in output
    assert "не полный реестр" in output
    assert "not-for-the-console" not in output
