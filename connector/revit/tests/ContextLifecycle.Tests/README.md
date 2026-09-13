# Context lifecycle and execution binding contract checks

This executable test project links the production tracker, collector, both
ExternalEvent schedulers, ConnectorService, engine, journal, CompilerHostClient,
protocol and compatibility sources. It does not copy their algorithms.
It uses no test-framework packages. Failed assertions return a nonzero exit code.

Run the headless checks from the repository root:

```sh
dotnet run --project connector/revit/tests/ContextLifecycle.Tests/ContextLifecycle.Tests.csproj --configuration Release
```

The stubs explicitly separate managed wrappers from a native identity and allow
different native documents to have the same hash. They also inject invalidity,
comparison failures and overflow. Manifest tests call the production private
method through reflection. Execution binding tests also compile a tiny generated
assembly with Roslyn and invoke it through the production queue and engine; its
only effect is an explicitly named stub counter, not a Revit transaction.
Commit/undo/redo tests inject the corresponding DocumentChanged notifications;
they do not test whether Revit emits those notifications.

The execution tests cover immutable queued inputs, exact/conflicting replay,
stale context, a denied queued duplicate, restart/legacy recovery, started-only
lookup, detached receipt data, invalid records and partial/full-write-then-throw
I/O failures against temporary real journal files. Service context, validation,
conflict and lookup routes execute production code. Positive CompilerHost
subprocess compilation and actual Windows NamedPipe transport are not exercised
by these tests. CompilerHostClient is linked, but its missing-host rejection is
the only compilation route tested here.

Framing controls call the production `JsonFraming.Read` with hand-built frames:
missing routing fields, duplicate/escape-equivalent keys and malformed UTF-8.
Journal controls inject actual invalid UTF-8 bytes into both copies of a document
key and construct BOM-marked UTF-16/UTF-32/UTF-8 files. They check refusal before
append, unchanged bytes, and exact recovery of valid Unicode as a positive
control. Wire, journal and owner metadata share the production `StrictJson`
boundary; no second test parser implements its policy.

The ownership slice additionally links `ConnectorTarget` and `JournalOwner`.
Its tests start separate .NET processes for distinct journal owners, competing
creators of one identity, exclusive recovery and process-kill lease release.
Recovery checks real metadata and reuses the journal parser; it exposes only
detached reads. Missing/incomplete/foreign metadata is refused without repair
or adoption. The lease file is retained and never used as a PID-based liveness
guess. The owner also refuses new appends through a previously returned journal
after disposal; cached detached reads are not a claim of current ownership.

The second ownership slice now binds every schema4 journal record and receipt to
the original target and checks it against the owner metadata. Tests include the
previously failing swap of a valid B journal into A's container, all target axes,
native year mismatch, session rotation, and historical recovery through service B
returning a receipt whose origin remains A. Schema0/3 archives cannot acquire a
target or receive new writes. The third ownership slice links the actual App,
ConnectorSession, discovery/pipe host and shared SessionAdmission. It tests
bootstrap year, stable owner through toggles, stale timers, bind/publication
failures, queued cancellation, start-vs-close, reentrant shutdown retaining a
lease and late work after owner disposal. No temporary unowned Service overload
remains. Two child processes run the actual App lifecycle and actual portable
NamedPipe host, including ping/routing, independent cleanup and process-kill
recovery. UI objects and Windows directory ACL calls are narrow stubs/seams;
the startup/publication/queue/lease algorithms themselves are production sources.
The portable process tests do not establish Windows ACL/NamedPipe behavior or
live simultaneous Revit 2023/2026 execution. No legacy global file is migrated.

Modern pipe tests exercise the .NET Unix implementation, including incomplete
frame shutdown (50 immediate-close attempts), blocked-response/EOF shutdown,
bounded I/O deadlines and reconnects. The async and sync framing APIs share the
same bytes, limit and strict decoder; the compiler host's synchronous API is
unchanged. The one-shot client closes after reading its frame, not after waiting
for server EOF. The handler-await interval has no idle-I/O timer. These tests do
not establish .NET Framework pipe behavior,
Windows ACL enforcement, Windows handle cleanup or Revit event timing. Windows
platform warnings are suppressed only for this portable linked harness, since its
Windows ACL methods are compiled but deliberately not executed. Native-reference
and full add-in builds do not use that suppression.

An optional compile-only mode removes all stubs and tests and references actual
Revit DLLs. Supply an installed/reference directory containing both RevitAPI.dll
and RevitAPIUI.dll, for example:

```sh
dotnet build connector/revit/tests/ContextLifecycle.Tests/ContextLifecycle.Tests.csproj --configuration Release -p:NativeReferenceCheck=true -p:RevitVersion=2023 -p:RevitReferenceDirectory=/path/to/revit/2023
```

This mode targets net48 for Revit 2021–2024 and net8.0-windows (with the Windows
Desktop reference pack) for modern checks. It checks the changed production API
surface, not the entire Windows
addin packaging or loader. Do not run the compile-only output as a test program.

Passing these checks is not a live Revit acceptance result. Remaining protocol,
journal, transport and native test requirements are recorded in
[CONNECTOR_RUNTIME_GAPS_RU.md](../../../../docs/CONNECTOR_RUNTIME_GAPS_RU.md).

Stage3 offline evidence (2026-09-05): independent repetition of an initial
99-case run exposed an incomplete-frame shutdown race (98/99). A separate
immediate-close probe reproduced it while the peer remained open; a 50ms delay
hid the interleaving. Cancellable frame/EOF I/O replaces reliance on Dispose
interrupting a synchronous read. The expanded local and independent runs pass
105 cases; the independent original immediate-close probe also passes 200/200
attempts. This accepts the portable slice, not Windows/native execution. Compile-only
checks against actual Revit 2021/2023/2026 references and full production Connector
builds for 2023/2026, all zero warnings/errors. The first full 2026 build exposed
three baseline MSB3277 reference-closure warnings (Microsoft.VisualBasic/WindowsBase).
Conditioning UseWPF/UseWindowsForms on net8.0-windows resolved them without warning
suppression or changes to net48. The modern resolved copy-local item is only
Kir.Revit.Protocol.dll; neither output contains RevitAPI/RevitAPIUI/WindowsBase
runtime DLLs. This checks build/reference closure, not installation, publishing
the separate self-contained compiler host or loading the add-in into Revit.
