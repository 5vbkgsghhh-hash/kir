# Coordinated Connector build: Wave A

The slice creates verifiable packages of the add-in + CompilerHost + PipeClient. It
does not install them and does not confirm loading into Revit. Switching the
manifest belongs to the separate Wave B: [the installation contract](CONNECTOR_INSTALLATION_RU.md).

## Running it, and the result

From PowerShell 7.4+ with the .NET 8 SDK installed:

```powershell
& ./connector/revit/scripts/build.ps1 -RevitVersion @('2023','2026') -Configuration Release -OutputRoot 'C:/KIR/packages'
```

By default, the reference DLLs are looked up in the corresponding directories of the
installed Revit. An explicit RevitInstallDirs hashtable and DotnetPath can be
passed. The name and major version of both RevitAPI/RevitAPIUI are checked from
managed metadata before the build, not by folder name. Reference DLLs are not
included in the package. Reading the metadata does not launch Revit and does not
use Assembly.Load.

Build creates a unique `.staging-*`, captures the sources of the four production
projects, Directory.Build.props, and the add-in template. It is exactly the copied
XML that is checked, so a later edit to the source file does not swap out the
snapshot already being checked. Unknown imports/tasks/includes, external
ProjectReferences, custom properties/control constructs, property functions, and
filesystem conditions are rejected by name. This is a limited supported project
profile, not a universal MSBuild interpreter or a sandbox against a hostile system
owner.

A captured global.json pins the chosen SDK. The Directory.Build.props/targets paths
are set explicitly inside the snapshot; targets is empty, and NuGet.Config contains
only the official nuget.org. A Directory.Build.targets from an ancestor of the
staging directory cannot be inherited unnoticed. Every helper and every Revit year
gets its own `--artifacts-path`, including obj and project.assets.json. One shared
fresh `-o` would not be enough for that isolation.

CompilerHost and PipeClient are published as self-contained win-x64 DIRECTORY
outputs, not as trimmed framework-dependent builds. All declared runtime assets are
copied. PathMap normalizes the staging paths; automatically stamping the old Git
HEAD into InformationalVersion is disabled. The source digest denotes the specific
captured bytes, not worktree cleanliness or trust in HEAD.

All native exit codes are checked immediately. No final package is published before
ALL requested builds and validation have succeeded. After that, each complete
directory is moved into `packages/<year>/<manifest-sha>`. An already-addressed
package is only checked, not overwritten. There is no shared filesystem transaction
across several years: a late I/O error may leave a previously published FULL
package in place, but no mixed versions inside it. A failed staging is kept; there
is no wholesale deletion of the output root.

## What the package checks

`package.json` contains the schema/year/configuration/protocol/product
version/SDK/source digest/runtime identifier and the exact paths, sizes, and
SHA-256 of every file. Protocol/version are taken from the captured owners, not
from a separate hand-set packaging version. The package ID is the SHA-256 of the
manifest bytes, not a signature of authenticity.

The reader refuses on duplicate/missing/unknown JSON fields, a BOM/malformed UTF-8,
extra/missing/changed files, traversal, ADS, Windows device names, case collisions,
and links/reparse points. MSBuild paths with ambiguous `;`, `%`, `,`, and other
control characters refuse rather than silently change the reference's or output's
target. The number/size of files and metadata are bounded; output cannot land back
inside the captured source tree.

For the helpers, the self-contained runtimeconfig, a consistent win-x64 runtime
pack, the app in the deps target, the mandatory runtime binaries, and every
declared runtime/native/resource asset are checked. An empty deps target is not
treated as proof of completeness. WindowsBase.dll is not cut by name alone from a
Core runtime helper: it can be a legitimate facade. Revit DLLs are forbidden in
every role, and stray desktop/runtime DLLs next to the add-in are checked
separately.

For the add-in, the real AssemblyRefs of every root managed DLL are read. An
unknown dependency must resolve to an included file with a matching name,
token/culture, and no lower version. There is no blanket exception for `System.*`.
The legacy CLR profile contains only the current, explicitly named
framework/facade identities; modern Core provider names are derived from the
verified runtime pack. Revit references must match the package year. WindowsDesktop
support or actual loader behavior is never guessed from the mere presence of a Core
facade.

## A candidate's presence does not prove assembly binding

A higher version is only a present candidate. A version mismatch produces
`BindingWarnings` with requester/dependency/expected/provided and
`requires_windows_loader_validation`. Build/reader explicitly return
`DependencyBindingVerified=false` and `LoadVerified=false`, even with an empty
list.

Three obligations were found in the actual 2023 package:

- Protocol requires System.Text.Json 8.0.0.0, and 8.0.0.5 is included;
- System.Memory and Tasks.Extensions require Unsafe 4.0.4.1, and 6.0.0.0 is
  included.

In the actual 2026 package there are two Core-provider differences: netstandard
2.0→2.1 and System.Memory 4.0.1.2→8.0. This is not a claim that a newer DLL is
automatically compatible. In .NET Framework the exact version is used by default;
changing that behavior requires host/configuration policy.
[Microsoft: assembly binding](https://learn.microsoft.com/en-us/dotnet/framework/deployment/how-the-runtime-locates-assemblies).
Nothing here edits Revit.exe.config or adds an AssemblyResolve hook.

The packages can be inspected and used for a separately authorized controlled
Windows loader check. They are not release-qualified before that check's results
are in. The package's existence, or a future successful install, does not mean
load success, BIM semantics, a transaction commit, or that the intent was carried
out.

## Evidence and the boundaries that remain

The earlier Debug/Release and native-exit defects were reproduced with a real
PowerShell against byte-identical copies of the scripts. An actual FileShare.None
caused a partial replacement of the old installer; a malformed manifest also
refused, after the overwrite had already happened. These original five-case traces
are kept separately and have not been rewritten.

The current author's synthetic strip: 38 passed. The actual SDK 8.0.423 built the
host/client with runtime 8.0.29 and add-ins against the Revit 2023/2026 refs with
no warnings/errors; the packages pass the structural/managed-reference checks with
explicit binding obligations. These numbers do not mean Windows or Revit execution.
Checking the ACL, loading through a real `.addin`, binding redirects/conflicts with
other add-ins, and a recoverable install remain separate Wave B/live work. Its
filesystem checks do not substitute for a Revit load.
