# Read-only CLI Connector

Status: the read-only CLI transport slice is checked on the portable pipe harness: all
46 cases passed in the shared strip of 231 tests. An already-built helper was used,
without a dotnet build. The first earlier run was limited to 20 checks because of a sandbox
Permission denied in 19 pipe cases; this check has now been repeated with a short
TMPDIR inside .work. Two incorrect test expectations were fixed: a missing client
has owner-code `client_unavailable`, and the wrong_pid fixture without structured
diagnostics gives `helper_failed`. A structured diagnostic is checked separately.
This work does not confirm live Revit or Windows authentication.

## Commands

```text
python -m kir connector list --directory <discovery-directory>
python -m kir connector context --directory <discovery-directory> --journal-id <uuid> --instance-id <uuid> --revit-version 2023 --session-id <uuid> --client <absolute-path-to-Kir.Revit.PipeClient.exe>
```

The directory and the trusted executable are given explicitly. List does not connect to
the process: `liveness=not_probed`, an expired announcement is not deleted, problems are
shown only as codes. `catalog_complete=false` means an incomplete/faulty scan.
Even a full empty catalog does not prove the absence of every running Revit.

Context selects the exact target/session: no newest/first, no search by model name,
and no fallback to a neighboring process. It sends one context request, does not
compile, and does not call execute. The CLI does not install/enable the Connector,
does not change the model, and does not automatically retry a failed request.

To get an observed precondition, extend the command:

```text
--precondition --bind-view yes --bind-selection no
```

Both choices are mandatory with `--precondition`, and without it the bind flags are
forbidden; the contradiction refuses before I/O. `no` deliberately leaves the condition
null. A precondition is not a lease or a write permission. A full "document not open"
answer is acceptable for an ordinary context read, but not for a precondition.

The JSON explicitly contains `read_only=true`, `write_permission=false`, `may_retry=false`.
Only the selected summary/context fields and named errors are printed, never the
token, the raw response, or a credential-bearing request. Erroneous CLI values are
also not echoed back: the parser yields `invalid_connector_arguments`; `--help`
remains available. Do not pass credentials as the `--token` argument.

Exit 0 — list/full context read; 1 — refusal on choice/conditions/response;
2 — CLI syntax, unreachable read, or a transport error.

## Live pilot 2023/2026

1. Agree on the computer, the access method, and the test documents. This runbook
   is not a permission to install the add-in or open someone else's model.
2. After a separately agreed installation, the operator starts Revit and enables
   the Connector with the add-in's normal command. The CLI does not do this.
3. Run list with the actual discovery directory. Pick two different
   target/session pairs and run context for each one separately.
4. Cross-check the year, the target/session, and the expected test document. The
   name helps the human, but the technical document_key is taken only from the
   native response.
5. Save the sanitized CLI JSON, do not forward the raw discovery files with the token.
   A missing/expired/ambiguous/foreign response is not to be worked around by picking
   another process.
6. The first model mutation requires separate agreement and review after the
   read-only smoke test and the completion of the update workflow.

The client runs locally on Windows with NamedPipe. For another machine you separately
need a way to launch the client; the CLI does not create a remote network endpoint.
