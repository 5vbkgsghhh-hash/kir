"""Real SDK tools/list and author→compile agree with the public program envelope."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from kir.compiler import compile_program, plan_program
from kir import sdk
from kir.diag import SANDBOX_FORBIDDEN_IMPORT
from kir.mcp import server
from kir.mcp.tests.http_client import call
from kir.tests.test_a_stable_address_is_not_permission import WALL_TYPE, owners
from kir.tests.test_public_program_lineage import program
from kir.tests.test_tool_schema_resource_root import assert_local_refs_resolve


TOKEN = b"public-lineage-test-token-not-a-real-secret"


def app(tmp_path):
    pytest.importorskip("mcp_types", reason="optional MCP SDK is required for real wire checks")
    return server.build_http_app(token=TOKEN, out_root=tmp_path)


async def listed_tools(application):
    import httpx
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                     base_url="http://127.0.0.1:8765") as client:
            response = await client.post("/mcp", headers={
                "Authorization": "Bearer " + TOKEN.decode(), "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28",
                "mcp-method": "tools/list"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                    "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                        "io.modelcontextprotocol/clientInfo": {"name": "kir-lineage-test", "version": "1"}}}})
    assert response.status_code == 200
    return response.json()["result"]["tools"]


@pytest.mark.parametrize("dedup", ["0", "1"])
def test_whole_schema_from_actual_tools_list_resolves_every_ref_and_rejects_malformed_input(tmp_path, monkeypatch, dedup):
    monkeypatch.setenv("KIR_MCP_SCHEMA_DEDUP", dedup)
    tools = asyncio.run(listed_tools(app(tmp_path)))
    for tool in tools:
        Draft202012Validator.check_schema(tool["inputSchema"])
        assert_local_refs_resolve(tool["inputSchema"])
    schema = next(tool["inputSchema"] for tool in tools if tool["name"] == "kir_compile")
    validator = Draft202012Validator(schema)
    validator.validate({"program": program(), "versions": ["2023"]})
    validator.validate({"program": program("residential"), "versions": ["2023"]})
    for bad in (None, "", True, 1, "a b", "owner\n", "owner\r", "owner\u2028", "x" * 65):
        assert list(validator.iter_errors({"program": {**program(), "lineage": bad}}))
    for bad in ({}, {"program": []}, {"program": program(), "unexpected": True},
                {"program": {**program(), "unexpected": True}},
                {"program": {**program(), "ops": [{"op": "invented"}]}},
                {"program": program(), "versions": ["1900"]}):
        assert list(validator.iter_errors(bad))
    assert (assert_local_refs_resolve(schema) > 0) is (dedup == "1")
    assert asyncio.run(listed_tools(app(tmp_path))) == tools


async def invoke(tmp_path, name, arguments):
    response = await call(app(tmp_path), name, arguments,
        headers={"Authorization": "Bearer " + TOKEN.decode()})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result.get("isError", False) is False
    return result["structuredContent"]


@pytest.mark.parametrize("author", ["sdk_dict", "dsl"])
def test_sdk_dict_or_sandbox_dsl_http_compile_cli_and_typed_plan_emit_the_same_owner(tmp_path, author):
    arguments = {k: v for k, v in WALL_TYPE.items() if k != "op"}
    if author == "sdk_dict":
        # The external Python SDK produces JSON. Sandbox imports are intentionally
        # narrower: DSL names are injected, importing the kir package is forbidden.
        external = sdk.program(lineage="residential")
        external.add(sdk.create_wall_type(**arguments))
        source = f"result = {external.to_dict()!r}\n"
    else:
        source = "envelope(lineage='residential')\n" + f"create_wall_type(**{arguments!r})\n"
    authored = asyncio.run(invoke(tmp_path, "kir_author", {"program_py": source}))
    assert authored["ok"], authored
    assert authored["program"] == program("residential")
    if author == "dsl":
        assert isinstance(authored["authorship"]["lineage"], dict)
        assert authored["authorship"]["lineage"]["WT1"]
    compiled = asyncio.run(invoke(tmp_path, "kir_compile", {
        "program": authored["program"], "versions": ["2023", "2026"]}))
    assert compiled["ok"] and compiled["filesystem_effect"] == "none"
    for version in ("2023", "2026"):
        typed = compile_program(plan_program(authored["program"]), revit_version=version)
        direct = compile_program(authored["program"], revit_version=version)
        assert typed.ok and direct.ok
        csharp = compiled["per_version"][version]["csharp"]
        assert csharp == typed.csharp == direct.csharp
        assert owners(csharp) == ["kir:pae373ebf:WT1"]
    root = Path(__file__).resolve().parents[3]
    cli = subprocess.run([sys.executable, "-m", "kir", "build", "-", "--revit", "2023"],
        input=json.dumps(authored["program"]), text=True, capture_output=True, timeout=30,
        cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert cli.returncode == 0, cli.stderr
    assert cli.stdout.rstrip("\n") == compiled["per_version"]["2023"]["csharp"].rstrip("\n")


def test_sdk_dict_invalid_identity_is_not_dropped_by_sandbox_or_http(tmp_path):
    arguments = {k: v for k, v in WALL_TYPE.items() if k != "op"}
    external = sdk.program(lineage="owner\n")
    external.add(sdk.create_wall_type(**arguments))
    source = f"result = {external.to_dict()!r}\n"
    authored = asyncio.run(invoke(tmp_path, "kir_author", {"program_py": source}))
    assert authored["ok"] and authored["program"]["lineage"] == "owner\n"
    rejected = asyncio.run(invoke(tmp_path, "kir_compile", {
        "program": authored["program"], "versions": ["2023"]}))
    assert not rejected["ok"]
    assert "KIR-T001" in str(rejected["per_version"]["2023"]["diagnostics"])


def test_lineage_does_not_expand_the_sandbox_import_capability(tmp_path):
    refused = asyncio.run(invoke(tmp_path, "kir_author", {
        "program_py": "from kir import sdk\nresult = sdk.program(lineage='residential').to_dict()\n"}))
    assert not refused["ok"] and refused["err"]["code"] == SANDBOX_FORBIDDEN_IMPORT
