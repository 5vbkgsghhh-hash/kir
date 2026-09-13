# One explicitly addressed exchange with the standalone Connector

`kir.revit_transport.exchange(advertisement, request_bytes, client_path=..., timeout_ms=...)`
returns the raw bytes of one response. This is transport, not a check of a commit,
a readback, a BIM result, or a permission to retry a mutation.

## Python contract

Before the helper is launched, strict bounded JSON is checked, along with an exact
match of protocol, target, session, and token against the given advertisement, an
allowed kind/field set, the source SHA, and the advertisement's expiry. Process
selection remains explicit through the existing `DiscoveryCatalog.select`; the
method does not pick the first, the newest, or any other available runtime. The
advertisement and the PID do not prove an up-to-date document context.

The raw UTF-8 bytes are not re-serialized in .NET. The outer limit stays at 16 MiB:
both original 1501-op requests with Cyrillic/emoji pass a byte-for-byte comparison
on the server. The separate extended CompilerRequest profile is not used here.

An explicitly given absolute `client_path` must lead to a trusted executable. Its
authenticity, signature, and consistency with the package are not yet established
by this module. Token/source/request are passed only through stdin, never argv or
ordinary diagnostics. Python bounds stdout to 16 MiB, stderr to 4 KiB; exit 0 with
non-empty stderr is treated as a contradictory result, and malformed/duplicate/
multiple JSON responses are rejected. No payloads or unchecked stderr are ever
inserted into the exception text.

On exit 2, Python recognizes only the helper's exact five-field diagnostic schema
and a closed list of code/phase values. For example, `server_pid_mismatch` becomes
`pipe_client_server_pid_mismatch`, and `unsupported_platform` becomes
`pipe_client_unsupported_platform`. Arbitrary code/phase strings, unknown fields,
duplicate keys, wrong boolean types, or retry_permitted=true all fall back to a
generic refusal with no raw text inserted. This is a convenient naming of the
cause, not proof that the helper is telling the truth: delivery is always unknown,
may_retry is always False regardless of request_may_have_been_sent. The diagnostic
never overrides a timeout, an exceeded output budget, or an unconfirmed process
termination.

| Outcome | Meaning |
|---|---|
| validation/path/start failed before launch | `ConnectorTransportError.delivery = not_attempted`: this attempt never launched the helper. |
| An error, timeout, malformed stdout, or non-zero exit after launch | `delivery = unknown`, regardless of what the helper claims. |
| Child/I/O termination is not confirmed | `helper_cleanup_unconfirmed`, delivery unknown. |
| Bounded strict response bytes received at exit 0 | Only the transport finished; a context/write assessor is still needed. |

On every error `may_retry=False`. Even the absence of a new send does not prove
that the same operation UUID was never used before. After an undetermined outcome,
the original journal/receipt must be read; the UUID must not be changed and a
mutation must not be launched automatically. A transport exception is never
disguised as a ConnectorResponse.

Python supervises one helper, reads stdout/stderr in parallel with writing stdin,
applies one shared deadline, then kill/wait and a bounded check of I/O completion.
What is confirmed is the process's actual termination, not merely that kill was
called. Process creation at the OS level does not by itself have a guaranteedly
cancelable deadline. The contract does not cover hostile grandchildren or job
containment.

## .NET helper contract

`Kir.Revit.PipeClient exchange --pipe NAME --expected-server-pid PID --timeout-ms N`
reads one raw JSON from stdin up to EOF, with the same byte budget. On the
production path, a non-Windows system gets an explicit refusal; the test PID seam
is not a CLI flag.

It connects only to the local server `.` with `Asynchronous | CurrentUserOnly` and
the Anonymous impersonation level. After connecting and **before writing the
token/source**, the expected PID is checked; an unreachable check or a mismatch
closes the pipe. The PID is an additional check of the chosen local endpoint, not a
substitute for journal/instance/session/document binding, and not a hostile-same-
user sandbox.

One shared deadline covers stdin/connect/write/read/stdout, as far as the OS I/O
primitives allow it; an additional Python supervisor watches the helper. The client
reads exactly one framed response and closes the pipe BEFORE printing stdout.
There is no waiting on a server EOF/ReadToEnd: the server itself waits for the
client to close. There is neither a reconnect after a failed exchange, nor a
resend. The internal wait for pipe availability inside ConnectAsync is not a
mutation retry.

Exit 0 means transport success, even if the native response itself carries a
refusal. On error, stderr contains only the bounded diagnostic schema
`kir-pipe-client-diagnostic/1`: code, phase, request_may_have_been_sent, and
retry_permitted=false. Python never turns that last claim into proof of no effect.
Reads use `assess_connector_context_response`, writes use
`assess_connector_write_response` with the original artifact/request ID.

## What is confirmed by documentation, but not yet by Windows execution

Microsoft describes CurrentUserOnly as a check of the user and the elevation
level: [PipeOptions](https://learn.microsoft.com/en-us/dotnet/api/system.io.pipes.pipeoptions?view=net-10.0).
The actual .NET 8 client compares the owner SID in ValidateRemotePipeUser:
[.NET 8 source](https://raw.githubusercontent.com/dotnet/runtime/v8.0.0/src/libraries/System.IO.Pipes/src/System/IO/Pipes/NamedPipeClientStream.Windows.cs).

The PID API is documented by Microsoft:
[GetNamedPipeServerProcessId](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeserverprocessid).
Its parameter description mentions a handle from CreateNamedPipe, while the client
connects through a client handle. So the actual compatibility of this exact
P/Invoke with a Windows client handle remains a mandatory live check, not something
proven by compilation or a Linux fixture. Also not checked: Windows ACL/elevation,
interruption of real Windows I/O, and execution against simultaneously open Revit
instances.

The build/install scripts were not changed here. The client's mere existence does
not mean an accepted install of the paired release, or an automatically authorized
publication of the model.
