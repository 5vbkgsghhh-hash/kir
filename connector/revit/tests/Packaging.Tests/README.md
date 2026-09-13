# Wave A: paired package build, not installation

Requires PowerShell 7.4+ and an installed stable .NET8 SDK. The checked-in build
and helper scripts explicitly refuse older PowerShell rather than failing later
on missing .NET methods. The acceptance run used isolated PowerShell7.6.5.

```powershell
pwsh -NoLogo -NoProfile -File connector/revit/tests/Packaging.Tests/Run.ps1
```

The runner builds a real native FakeDotnet process, emits minimal managed metadata
for fake API/root assemblies, and executes copies of the production build script
in fresh temporary directories. Fake output payloads are not Revit implementations
or working Windows executables. Source capture, exit-code handling, packaging,
strict validation and filesystem operations are production code, not copied logic.
Fixture artifacts are retained and their exact path is printed.

The build entrypoint now checks output-volume free space before creating output
or invoking tools, and before substantial build/copy phases. Its default reserve
is 6 GiB (`-MinimumFreeBytes` is an explicit operator policy, not a filesystem
quota or an estimate of arbitrary future input size). The synthetic Build-Case
explicitly requests a 1-byte reserve; it does not qualify production capacity.
`Space.Tests.ps1` checks the new boundary without creating fixture directories
or building anything. The historical 38-case acceptance predates this guard;
the full packaging lane has not been rerun during the disk-management pause.

The final local run has38 cases. They cover Debug/staleRelease separation, native
failures including the last requested year, separate artifacts paths, no partial
final package publication, missing runtime/root dependencies, captured-source
mutation, namespaced imports, unsupported root attributes/properties/functions,
filesystem build conditions, external project references, actual ancestor MSBuild
target isolation, Windows path aliases, links, hash/inventory corruption, empty
dependency targets, framework-dependent helper refusal and identical-package reuse.
The fake PE generator uses a deterministic content ID; a timestamp in that test
generator initially made the identical-package control fail and was fixed there.

Independent review also exercised the actual2023 package with System.Text.Json
removed and its inventory rehashed: it must refuse through managed-reference
closure, not pass merely because its new hashes are internally consistent.
Real PE metadata is inspected with PEReader; no Assembly.Load or PE execution.

An actual SDK build additionally created self-contained win-x64 helper directories
and add-ins against actual Revit2023/2026 reference DLLs. SDK8.0.423 and
runtime8.0.29 were used. Host/client/year-specific obj/restore artifacts are separate;
new dependency restores go to the staging cache, with the existing cache read as
a fallback and only official NuGet configured. Both add-in builds reported zero
warnings/errors. Final actual package IDs in this session:

- 2023: dc43c4c4bbe381c81786850536f2e4be26d9569df39f94f22d87ff069a85616b
- 2026: 67fad713e9bfed4ff0f21eb9f384f6dd08d7a755634d12e03cb491e725289a91

These are inspectable complete file sets, NOT release-qualified loader successes.
They report3/2 dependency-version obligations respectively and always retain
DependencyBindingVerified=false and LoadVerified=false. See
[packaging contract](../../../../docs/CONNECTOR_PACKAGING_RU.md).

Wave B has a separate Install.Tests.ps1 lane; the Wave A runner does not exercise
activation. No real APPDATA installation, Windows loader/ACL test, Revit process or
model mutation was performed. Synthetic Linux PowerShell evidence does not prove
Windows sharing, binding redirects, activation durability or installed behavior.

## Synthetic installer lane

```powershell
pwsh -NoLogo -NoProfile -File connector/revit/tests/Packaging.Tests/Install.Tests.ps1 -PackageRoot '<build-fixture>/debug/dist/packages'
```

Without PackageRoot, the runner first creates its own Wave A fixture. Install,
inspect and rollback always target explicit fresh temporary directories. The
native process controls hold the actual pointer lease across different year/root
overrides, run independent pointers concurrently and kill the test process before
or after switch. No production CLI flag bypasses expected identity or opt-in.
Test seams execute File.Replace/Move before injected exceptions, so a returned
error cannot be mistaken for proof that nothing changed. Legacy rollback compares
exact bytes while retaining the old dummy binary untouched.

These tests do not validate Windows/Revit installation. Full contract and limits:
[CONNECTOR_INSTALLATION_RU.md](../../../../docs/CONNECTOR_INSTALLATION_RU.md).

Wave B completed author and independent 37/0 runs. A subsequent fixture-only
DTD precision correction passed its targeted case: valid XML is accepted with
DtdProcessing.Parse/XmlResolver=null, while production Prohibit refuses it.
Use `-CaseFilter 'template dtd*'` for that control; the default filter runs all
cases. The targeted rerun is not an additional distinct scenario or a rerun of
the whole suite. Production code was unchanged by that test correction.
