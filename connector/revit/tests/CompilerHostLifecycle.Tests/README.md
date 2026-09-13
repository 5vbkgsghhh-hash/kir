# Compiler-host capacity and child lifecycle

This executable links the actual Protocol helpers, Connector's CompilerHostClient,
and CompilerHost Program/Compiler/CodePolicy. It starts separate local children
for failure injection. It is not a Revit simulator, nor a claim that a successful
fixture child's bytes are a valid PE or a BIM implementation.

```sh
dotnet run --project connector/revit/tests/CompilerHostLifecycle.Tests/CompilerHostLifecycle.Tests.csproj --configuration Release -p:NuGetAudit=false
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python connector/revit/tests/CompilerHostLifecycle.Tests/reproduce_capacity.py
```

The Python command needs KIR dependencies. Two real 1501-op programs go through
planning, source preparation and the production-linked client. Both original
Cyrillic/astral controls yield 4,931,737 UTF-16 source units, 8,273,651 external
UTF-8 bytes and 21,507,610 internal JSON bytes. The child's exact source hash and
terminated PID are checked. This proves forwarding capacity, not successful
native compilation/execution of those large buildings.

The internal request profile retains six Mi UTF-16 source units despite escaping.
References are limited separately to 256 paths, 32768 UTF-16 units per path and
one MiB for the actually serialized list. Fixed envelope overhead has a four-KiB
allowance; the complete frame must fit the separate internal cap. Prepared bytes
are private and source/reference snapshots detached before validation/serialization.
Unpaired surrogates, unknown/missing fields, duplicates, null lists and excess
sizes refuse explicitly. Default external and compiler-response framing stay 16 MiB.

Nineteen top-level cases group missing/startup-failing hosts, reference exceptions,
blocked stdin/stdout, lingering children, cancellation, four-MiB stderr floods,
malformed/truncated/oversized/duplicate/trailing stdout, contradictory exit codes,
invalid Base64 and rejection without diagnostics. PID inspection precedes fixture
cleanup. Real host Program also reads an expanded frame and reaches its actual
missing-Revit-reference refusal; no Revit API is invoked.

The child-exchange deadline is independent of I/O cancellation support. Cleanup
kills a still-running child, confirms exit and observes outstanding I/O tasks.
Stderr retention is capped at 64 KiB, but draining continues. Unconfirmed cleanup
returns `compiler_cleanup_unconfirmed`, not a claim of termination. This does not
prove Windows/.NET Framework cleanup, unkillable OS failure behavior, executable
authenticity, grandchildren/job containment or arbitrary-code isolation.
Preparation is size-bounded but outside the child deadline; OS Process.Start
itself has no cancellation API.
