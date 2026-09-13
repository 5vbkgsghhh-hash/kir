# Choosing among parallel Revit sessions

`kir.revit_discovery` is a read-only client layer for the runtime advertisement.
It reads only the explicitly chosen directory
`v4/discovery/{instance_id}/{session_id}.json`.
It does not connect to a NamedPipe, does not open documents, and does not
delete old files. Concurrent Revit 2023 and 2026 processes are different
targets; re-enabling the same process creates another session under the same
journal/instance.

```python
from datetime import datetime, timezone
from kir.revit_discovery import scan_discovery

catalog = scan_discovery(chosen_discovery_directory)
summaries = [entry.summary(now=datetime.now(timezone.utc))
             for entry in catalog.advertisements]

# target/session is chosen explicitly by the coordinator, not by the first
# entry or by mtime.
selected = catalog.select(target=chosen_target, session_id=chosen_session,
                          now=datetime.now(timezone.utc))
# selected.credentials holds the secret for a future authenticated transport.
# summaries, repr, and ordinary diagnostics do not hold the token.
```

`advertised_unexpired` only means comparing the advertisement time against an
explicitly supplied clock. It does not mean `connected`, `live`, the presence
of the right document, or permission to repeat an old operation. Even a
selected advertisement could go stale between the scan and the request. The
resulting native response must again match the target/session and the
original execution binding.

## Checked boundaries

- Exactly seven fields of the native `DiscoveryRecord`, closed target,
  canonical nonzero UUID, a supported year, a positive Int32 process ID.
- Strict UTF-8 JSON with no BOM, no duplicate keys, and no nonfinite scalars;
  file ≤64 KiB.
- `DateTime.ToString("O")` UTC format with seven fractional digits. The
  seventh digit is compared as a .NET tick and is not lost when converting to
  Python microseconds.
- Pipe names in the supported standalone App are local ASCII identifiers of
  length ≤256, with no path or remote computer name. This is not a universal
  parser for every valid Windows pipe name.
- The instance directory and the session filename must match the content.
- A corrupted/vanished neighbor produces a separate issue and does not hide
  legitimate records. The whole directory is not reported as complete once it
  exceeds 1024 entries (both directories and files are counted); the scan
  explicitly refuses.
- Expired files are kept and visible in diagnostics, but `select` rejects
  them. With several sessions, the newest one is not chosen automatically.

Known symlinks and nonstandard files are not read. This is not protection
against every TOCTOU filesystem substitution by the same OS account, and not
a Windows ACL check. File content can be forged; hashes are byte identity,
not a signature.

The first 26 Python controls use the real file structure and two targets, but
not Revit and not a connection. A separate actual .NET DTO
serialization→Python parser/selection has been added to the ProtocolReplay
harness; the result is recorded after the corresponding run. The PID in that
fixture is explicitly synthetic; it is not advertised by App bootstrap or by
live discovery.

Next: an authenticated one-shot transport and a verified context snapshot, an
explicit choice in the standalone UI, the Windows installation/ACL/live
matrix. Until then, having a parser/scanner does not mean KIR is ready to
publish into Revit.
