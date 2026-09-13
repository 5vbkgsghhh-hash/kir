# Raw client: portable acceptance boundary

This project links the production PipeClient engine, raw Protocol framing,
ConnectorService, journal, context collector/schedulers and pipe host. It uses
the existing narrow Revit stubs. Windows directory ACL calls and the client PID
probe have explicitly named test seams; no production option bypasses PID checks.

```sh
dotnet run --project connector/revit/tests/PipeClient.Tests/PipeClient.Tests.csproj -c Release -p:NuGetAudit=false
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest kir/tests/test_revit_transport.py -q
```

These tests need local Unix sockets when run on Linux. A sandbox denying socket
bind/connect will fail the actual pipe cases; it is not a reason to silently skip
them or replace their I/O with mocks.

Seven native groups check byte-preserving bounded raw frames, wrong/unavailable
PID probes sending zero request bytes, one response followed by client close,
partial-response cancellation, absent pipe and the real production CLI's
non-Windows refusal. Python cases exercise strict prelaunch target/session/token
binding, explicit two-server selection, real helper failures/cleanup and exact
external SHA-256 for both original 1501-op Unicode requests.

The discovery→context→prepare→transport→bound-result case uses real pipe/helper
processes and production Service/Collector/Journal code. Its write receipt is
EXPLICITLY SEEDED by the fixture; no generated assembly or Revit mutation runs.
Successful result assessment in this case tests interoperability, not a building.

The test executable's exchange entrypoint injects PID inspection for portable
tests. The separately built production Kir.Revit.PipeClient refuses non-Windows
operation. CurrentUserOnly/elevation, GetNamedPipeServerProcessId on a connected
Windows client handle, Revit API behavior, Windows cancellation/cleanup and actual
simultaneous Revit 2023/2026 remain live gates. The fixture's PID absence check
uses Linux /proc and is not mislabelled Windows process evidence.

The Python diagnostic delta retains all original transport controls and adds
strict whitelist code/phase tests, both sent-flag values, adversarial secret
strings/duplicates/extra fields/invalid booleans/retry claims, inconsistent exit
codes and the actual production CLI's unsupported-platform diagnostic. The
expanded transport file passes 60 cases locally; none of these diagnostic hints
can grant retry permission or turn nonzero-exit stdout into a native response.
