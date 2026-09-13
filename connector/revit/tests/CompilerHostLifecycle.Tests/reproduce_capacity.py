"""Real KIR -> prepared source -> production-linked framing/child roundtrip.

Build CompilerHostLifecycle.Tests first. No Revit invocation or claim that the
large model meets native CodePolicy/BIM requirements: the child echoes a hash.
"""
import json
from pathlib import Path
import subprocess
from uuid import uuid4

from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution


def main() -> None:
    probe = Path(__file__).parent / "bin/Release/net8.0/CompilerHostLifecycle.Tests.dll"
    for label, value in (("cyrillic", "Ж" * 1000), ("astral", "😀" * 500)):
        target = RuntimeTarget(str(uuid4()), str(uuid4()), "2023")
        program = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}] + [
            {"op": "set_param", "id": f"P{index}", "target": {"by": "ref", "value": "L"},
             "param": "Comments", "value": value} for index in range(1500)]}
        artifact = prepare_execution(program, target=target, precondition=ContextPrecondition("doc", 0),
                                     operation_id=str(uuid4()))
        credentials = SessionCredentials(target, str(uuid4()), "token")
        request = artifact.execute_request(credentials, request_id=str(uuid4()))
        result = subprocess.run(["dotnet", str(probe), "--profile"], input=json.dumps({"source": artifact.source}),
                                text=True, capture_output=True, timeout=45, check=True)
        native = json.loads(result.stdout)
        source_units = len(artifact.source.encode("utf-16-le")) // 2
        external_bytes = len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode())
        assert len(artifact.planned.ops) == 1501
        assert source_units <= 6 * 1024 * 1024 and external_bytes <= 16 * 1024 * 1024
        assert native["payload_bytes"] > 16 * 1024 * 1024
        assert native["utf16_units"] == source_units and native["roundtrip_exact"] and native["child_exited"]
        print(json.dumps({"case": label, "ops": len(artifact.planned.ops), "source_utf16": source_units,
                          "external_utf8_bytes": external_bytes, "native": native}))


if __name__ == "__main__":
    main()
