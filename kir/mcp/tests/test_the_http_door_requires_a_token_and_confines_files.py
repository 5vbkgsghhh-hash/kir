"""HTTP capabilities are checked through the real SDK, not just its wrapper."""
import asyncio
import errno
import os

import pytest

from kir.mcp import server
from kir.mcp.http_security import configured_token, remote_origin, OutputRoot, HTTPConfigurationError

TOKEN = b"test-only-token-not-a-secret-0123456789"


def test_http_without_a_token_refuses_before_listening(monkeypatch, capsys):
    monkeypatch.delenv("KIR_MCP_TOKEN", raising=False)
    monkeypatch.setattr(server, "_protocol_sdk_absent", lambda **_: None)
    assert server.main(["--http"]) == server.NOT_DONE
    assert "http_token_required" in capsys.readouterr().err


def test_remote_binding_needs_both_opt_in_and_a_tls_origin():
    with pytest.raises(HTTPConfigurationError, match="remote_bind_requires_opt_in"):
        remote_origin("0.0.0.0")
    for origin in (None, "http://bim.example", "https://user:secret@bim.example", "https://bim.example/path", "https://*.example"):
        with pytest.raises(HTTPConfigurationError, match="public_origin_invalid"):
            remote_origin("0.0.0.0", allow_remote=True, public_origin=origin)
    assert remote_origin("0.0.0.0", allow_remote=True, public_origin="https://bim.example") == "https://bim.example"
    # A TLS proxy can reach a loopback backend; remote mode must not force exposure.
    assert remote_origin("127.0.0.1", allow_remote=True, public_origin="https://bim.example") == "https://bim.example"


def test_token_file_and_environment_are_not_echoed(tmp_path, monkeypatch):
    token_file = tmp_path / "private-token"
    token_file.write_bytes(TOKEN + b"\n")
    token_file.chmod(0o600)
    assert configured_token(token_file) == TOKEN
    monkeypatch.setenv("KIR_MCP_TOKEN", TOKEN.decode())
    assert configured_token() == TOKEN
    if os.name == "posix":
        token_file.chmod(0o644)
        with pytest.raises(HTTPConfigurationError, match="token_file_permissions"):
            configured_token(token_file)
    monkeypatch.setenv("KIR_MCP_TOKEN", "short-but-private")
    with pytest.raises(HTTPConfigurationError) as error:
        configured_token()
    assert "short-but-private" not in str(error.value)


@pytest.mark.parametrize("headers,status", [({}, 401), ({"Authorization": "Bearer wrong"}, 401),
    ({"Authorization": "Bearer " + TOKEN.decode()}, 200),
    ({"Authorization": "Bearer " + TOKEN.decode(), "Host": "foreign.example"}, 421),
    ({"Authorization": "Bearer " + TOKEN.decode(), "Origin": "https://foreign.example"}, 403)])
def test_actual_sdk_http_auth_preserves_host_and_origin_guards(tmp_path, monkeypatch, headers, status):
    pytest.importorskip("mcp_types")
    from kir.mcp.tests.http_client import call
    called = []
    monkeypatch.setitem(server._DOORS, "kir_spec", lambda args: called.append(args) or {"ok": True})
    app = server.build_http_app(token=TOKEN, out_root=tmp_path)
    response = asyncio.run(call(app, "kir_spec", {"op": "create_level"}, headers=headers))
    assert response.status_code == status, response.text
    assert len(called) == (1 if status == 200 else 0)
    if status == 200:
        assert response.json()["result"]["structuredContent"]["ok"] is True


def test_duplicate_authorization_is_refused_before_the_tool(tmp_path, monkeypatch):
    pytest.importorskip("mcp_types")
    from kir.mcp.tests.http_client import call
    called = []
    monkeypatch.setitem(server._DOORS, "kir_spec", lambda args: called.append(args) or {"ok": True})
    app = server.build_http_app(token=TOKEN, out_root=tmp_path)
    response = asyncio.run(call(app, "kir_spec", {}, headers=[
        ("Authorization", "Bearer " + TOKEN.decode()), ("Authorization", "Bearer wrong")]))
    assert response.status_code == 401 and called == []


@pytest.mark.parametrize("base_url,status", [("http://bim.example", 403), ("https://bim.example", 200)])
def test_remote_profile_executes_only_behind_the_named_https_origin(tmp_path, base_url, status):
    pytest.importorskip("mcp_types")
    from kir.mcp.tests.http_client import call
    app = server.build_http_app(token=TOKEN, out_root=tmp_path, public_origin="https://bim.example")
    response = asyncio.run(call(app, "kir_spec", {"op": "create_level"}, base_url=base_url,
                                headers={"Authorization": "Bearer " + TOKEN.decode(), "Origin": "https://bim.example"}))
    assert response.status_code == status, response.text


def program():
    return {"ops": [{"op": "create_level", "id": "level", "elev_mm": 0, "name": "Level"}]}


def test_actual_http_compile_creates_inside_root_and_will_not_overwrite(tmp_path):
    pytest.importorskip("mcp_types")
    from kir.mcp.tests.http_client import call
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("positive protected output requires no-follow directory handles")
    headers = {"Authorization": "Bearer " + TOKEN.decode()}
    args = {"program": program(), "versions": ["2026"], "out_dir": "results"}
    first = asyncio.run(call(server.build_http_app(token=TOKEN, out_root=tmp_path), "kir_compile", args, headers=headers))
    assert first.status_code == 200, first.text
    body = first.json()["result"]["structuredContent"]
    assert body["ok"] is True, body
    assert body["wrote_nothing"] is False and body["native_model_effect"] == "none"
    assert body["filesystem_effect"] == "created"
    target = tmp_path / "results/kir_2026.cs"
    original = target.read_bytes()
    second = asyncio.run(call(server.build_http_app(token=TOKEN, out_root=tmp_path), "kir_compile", args, headers=headers))
    body = second.json()["result"]["structuredContent"]
    assert body["ok"] is False
    assert "output_exists" in body["per_version"]["2026"]["file_error"]
    assert target.read_bytes() == original


@pytest.mark.parametrize("versions", [["2025", "2026"], ["2026", "2026"]])
def test_later_file_failure_does_not_hide_the_earlier_output(tmp_path, versions):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("protected output requires no-follow directory handles")
    if versions[0] != versions[1]:
        (tmp_path / "kir_2026.cs").write_text("keep")
    result = server._compile({"program": program(), "versions": versions,
                              "out_dir": "."}, output_policy=OutputRoot(tmp_path))
    assert result["ok"] is False and result["wrote_nothing"] is False
    assert result["native_model_effect"] == "none"
    assert result["filesystem_effect"] == "partial_or_unknown"
    first = tmp_path / f"kir_{versions[0]}.cs"
    assert result["files_created"] == [str(first)]
    assert first.is_file()
    if versions[0] != versions[1]:
        assert (tmp_path / "kir_2026.cs").read_text() == "keep"


def test_file_policy_does_not_follow_directory_or_file_symlinks(tmp_path):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("protected output requires no-follow directory handles")
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    (outside / "existing.cs").write_text("keep")
    (root / "existing.cs").symlink_to(outside / "existing.cs")
    policy = OutputRoot(root)
    with pytest.raises(HTTPConfigurationError, match="output_write_refused"):
        policy.write(policy.directory("link"), "new.cs", "must not leave root")
    with pytest.raises(HTTPConfigurationError, match="output_exists"):
        policy.write(root, "existing.cs", "must not overwrite")
    with pytest.raises(HTTPConfigurationError, match="output_outside_root"):
        policy.directory("../outside")
    assert not (outside / "new.cs").exists()
    assert (outside / "existing.cs").read_text() == "keep"


def test_swapped_output_root_is_refused(tmp_path):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("protected output requires no-follow directory handles")
    root = tmp_path / "root"
    root.mkdir()
    policy = OutputRoot(root)
    root.rename(tmp_path / "old-root")
    root.mkdir()
    with pytest.raises(HTTPConfigurationError, match="output_root_changed"):
        policy.write(root, "new.cs", "wrong root")
    assert not (root / "new.cs").exists()


def test_stdio_compile_keeps_its_previous_path_and_overwrite_contract(tmp_path):
    target = tmp_path / "kir_2026.cs"
    target.write_text("old")
    result = server._compile({"program": program(), "versions": ["2026"], "out_dir": str(tmp_path)})
    assert result["ok"] is True
    assert target.read_text() != "old"


def test_without_directory_handles_only_http_file_output_is_refused(tmp_path, monkeypatch):
    policy = OutputRoot(tmp_path)
    monkeypatch.setattr(os, "supports_dir_fd", set())
    with pytest.raises(HTTPConfigurationError, match="output_platform_unsupported"):
        policy.write(tmp_path, "new.cs", "not safe")
    inline = server._compile({"program": program(), "versions": ["2026"]}, output_policy=policy)
    assert inline["ok"] is True and inline["per_version"]["2026"]["csharp"]


def test_disk_full_keeps_the_partial_file_and_reports_an_uncertain_effect(tmp_path, monkeypatch):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("protected output requires no-follow directory handles")
    original = os.fdopen

    class FullDisk:
        def __init__(self, *args, **kwargs):
            self.stream = original(*args, **kwargs)

        def __enter__(self):
            return self

        def write(self, text):
            self.stream.write(text[:20])
            self.stream.flush()
            raise OSError(errno.ENOSPC, "test disk full")

        def __exit__(self, *_):
            self.stream.close()

    monkeypatch.setattr(os, "fdopen", FullDisk)
    result = server._compile({"program": program(), "versions": ["2026"], "out_dir": "."},
                             output_policy=OutputRoot(tmp_path))
    assert result["ok"] is False and result["wrote_nothing"] is False
    assert result["filesystem_effect"] == "partial_or_unknown"
    assert result["per_version"]["2026"]["retry_safe"] is False
    assert len((tmp_path / "kir_2026.cs").read_text()) == 20
