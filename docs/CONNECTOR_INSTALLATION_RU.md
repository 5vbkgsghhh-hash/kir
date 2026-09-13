# Recoverable pointer activation: Wave B

This slice changes only per-user installation files. It does not launch Revit,
does not touch the registry/Revit.exe.config, does not introduce AssemblyResolve, and
does not delete old releases. `LoadVerified=false` and the dependency binding
obligations from Wave A are preserved: manifest activation does not prove the
add-in loaded or had any BIM effect.

## Explicit installation

PowerShell 7.4+; the command is run only by the installation owner's decision:

```powershell
& ./connector/revit/scripts/install.ps1 -PackageDirectory 'C:/KIR/packages/2023/<id>' -ExpectedPackageId '<id>' -RevitVersion 2023 -ExpectedActiveManifestSha256 absent -AllowUnverifiedLoad
```

For an update, `absent` must be replaced with the SHA-256 of the actual previous
`.addin` bytes. The package ID is also mandatory: neither the most recent package
nor the first matching version is picked automatically. `AllowUnverifiedLoad` is a
separate explicit consent to a controlled-pilot load check; it does not make the
binding verified.

Standard paths:

- pointer: `%APPDATA%/Autodesk/Revit/Addins/<year>/Kir.Revit.Connector.addin`;
- releases: `%LOCALAPPDATA%/KIR/connector/releases/<year>/<package-id>`.

For tests or an explicitly given location, ManifestDirectory and ReleaseRoot are
available. The pointer cannot sit inside the immutable release tree, and install
destinations cannot write inside the source package. Symlink/reparse ancestors are
rejected; this is not universal protection against every hostile filesystem
race/Windows alias.

## Order and ownership

Before any writes, the expected package/year, the whole inventory/managed
dependency profile, the template, and the current pointer are checked. XML is read
with DTD forbidden; exactly the expected KIR Application entry with the known
ID/class/vendor and fields is accepted. The template must reference only
Kir.Revit.Connector.dll. A foreign manifest is not replaced even if the caller
passed its exact hash.

The lease is a reserved sibling `.Kir.Revit.Connector.install.lock` in the actual
pointer's directory. So different year/release-root overrides that address one file
do not get different locks. Other pointer directories are not locked globally.
Under the lease, the expected bytes and ownership are checked again.

The package is copied into a unique staging area, re-checked, and only then becomes
an immutable release. An existing addressed release is not overwritten. For the old
recognized baseline `KIR.Connector/Kir.Revit.Connector.dll`, only an explicit
migration by the expected hash is allowed; unknown custom DLL paths are not
adopted. Relocation between arbitrary previous release roots is not claimed.

Every new pointer gets an inert XML comment:
`kir-install/1 operation=<UUID> package=<SHA>`. This is the activation's identity,
not a runtime identity, a signature, or a document token. Even reinstalling the
same package gets different pointer bytes; an old rollback does not match a new
activation.

## Intent, switch, and an undetermined outcome

Under `ManifestDirectory/.kir-install/<UUID>/`, `intent.json`, `intent.sha256`, and
fixed `previous.manifest`/`next.manifest` are created when the corresponding side
exists. Links in the receipt cannot point to arbitrary absolute paths. Backup files
do not have a scannable `.addin` extension. The checksum and the XML refer to the
same captured bytes, not to a file re-read after the check.

File contents are written with WriteThrough/Flush(true) and checked before the
switch. This is an observed ordering/process-failure contract, not a portable
power-loss guarantee for directory entries. There is no attempt to pass off Linux
directory semantics as Windows proof.

`switch-attempted` and the in-memory uncertainty flag are set **before**
File.Replace/Move. An exception may follow after the pointer has changed. After the
switch, the actual hash is checked and the observation is saved separately. An API
error, a readback failure, or an acknowledgement failure in this window yields
`activation_unconfirmed` with the receipt's address and the observed state — with no
automatic rollback.

A failed staging/intent is kept for diagnostics. An incomplete receipt or a missing
marker permits neither a retry nor a guessed recovery.

## Inspect and rollback

```powershell
& ./connector/revit/scripts/install.ps1 -Inspect -ReceiptPath '<manifest-dir>/.kir-install/<uuid>/intent.json'
& ./connector/revit/scripts/install.ps1 -Rollback -ReceiptPath '<receipt>' -RevitVersion 2023 -ExpectedActiveManifestSha256 '<current-sha>' -AllowUnverifiedLoad
```

Inspect creates no directories or lease: it reads an existing operation under the
existing lease and compares the actual pointer against previous/next. An
observation is not a permission to run the operation again. A missing/corrupt state
requires explicit manual review, not automatic adoption of files.

The public switches must be true: `-Rollback:$false` and `-Inspect:$false` refuse
before dispatch, regardless of which PowerShell parameter set was picked. Inspect
separately checks the active package files and the year; matching pointer bytes do
not hide a missing DLL or a foreign package year. Rolling back a managed release
also requires the actual package year to match, not just the directory name and
hash.

Rollback accepts only the original installation receipt, checks its same-ledger
relationship, and requires the caller's expected current hash to match the recorded
next pointer and the actual bytes. After a different activation it refuses, without
rolling that one back. The exact previous bytes are restored. If there was no
pointer before, the current file is moved into a recoverable `removed.manifest`
rather than being replaced with empty XML. DLL/release directories are neither
deleted nor overwritten.

Legacy rollback restores only the pointer bytes, not the previous binaries, and is
no guarantee that the old add-in works. Restoring the exact previous bytes also
means content-CAS, not a global proof of the absence of ABA/history, or protection
from a writer that ignores the lease.

## Boundary of what is checked

Executable tests use real PowerShell/.NET filesystem APIs, separate processes,
effect-then-throw callbacks, process kill, and synthetic package/destination trees
under `/tmp`. No real APPDATA/Revit install is ever performed by them. Windows
ACL/file sharing, actual Revit manifest loading, dependency redirects, coexistence
with other add-ins, and power-loss durability remain live gates.

The author's and an independent full run both finished 37/0. A DTD fixture's
accuracy was then fixed: correct XML with an unused external entity is read
successfully by the control reader with DtdProcessing.Parse and XmlResolver=null,
but is rejected by production's Prohibit. The fixed targeted case separately
passed 1/0; the production code was not changed by this test fix. These numbers
must not be added up as 38 different scenarios or passed off as a Windows/Revit
qualification.
