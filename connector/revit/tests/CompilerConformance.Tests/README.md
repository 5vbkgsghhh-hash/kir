# Actual Connector compiler conformance runner

This links the production `Compiler.cs`, `CodePolicy.cs` and protocol, rather
than duplicating policy checks in Python. Stdin is an array of CompilerRequest
objects with full wrapped C# source and reference paths. Stdout reports each
actual compile result, diagnostics, actual Revit assembly identities and emitted
assembly size. Positive Python cases use the public Connector preparation
wrapper, rather than a different test-local wrapper. It never executes
an emitted assembly or starts Revit. It is a test runner, not a public transport.

Run the paired Python tests with explicitly supplied, legitimately available
reference assemblies:

```bash
KIR_TEST_REVIT_REFS_ROOT=/path/to/revit/year-directories \
KIR_TEST_NET48_REFS=/path/to/net48/reference-assemblies \
KIR_TEST_NET8_REFS=/path/to/net8/reference-assemblies \
PYTHONPATH=. python -m pytest kir/tests/test_connector_compiler_conformance.py
```

Each Revit year directory must contain RevitAPI.dll and RevitAPIUI.dll. Tests
use net48 references for 2021–2024 and net8 for 2025–2026. Without these explicit
fixtures or the .NET SDK, they skip with a named reason. Reference DLLs are not
redistributed in this repository.

Passing this lane proves only the selected code/policy/API-reference cases.
The generated floor-hole section is explicitly refused by KIR on Revit 2021;
it is not counted as a successful native compilation for that year.
In particular, the legacy generated `expected_document` guard is a deliberately
tested incompatibility: its PathName read is still blocked. A Connector-native
consumer must bind the exact artifact to the system-owned context precondition;
The pure Python preparation seam now constructs those target/context-bound
requests, but neither it nor this runner implements transport or proves live
document correctness.
