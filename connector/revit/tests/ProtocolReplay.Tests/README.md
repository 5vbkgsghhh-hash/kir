# Actual protocol/service/journal replay fixture

Used by `kir/tests/test_connector_protocol_replay.py`. This links the production
v4 protocol framing, service, owner and journal, plus the existing headless Revit
stubs. It creates a temporary owned journal with explicitly seeded KIR result
evidence, then exercises exact retry, receipt lookup and historical recovery.
Responses are serialized by the actual `JsonFraming.Write` implementation and
checked by Python against the exact prepared artifact.

Two cases also serialize the production `DiscoveryRecord` DTO with the native
seven-fractional-digit UTC format. Python parses those bytes and selects the
exact target/session from separate discovery directories. The PID, credentials
and pipe address are synthetic: this is serialization compatibility, not an
actual live advertisement or connection.

Seven context cases additionally exercise the production context collector,
revision tracker, scheduler and service. Revit documents and API event dispatch
are explicitly stubbed. They check no-document captures, observed document flags,
two revision events, sorted selection digest and the Python context-to-compiler
boundary. The resulting source is never sent for execution. The current Python
fixture has seventeen cases in total.

It does not execute generated code, launch Revit, test named pipes, authenticate
a real OS channel, or prove that the seeded result occurred. Synthetic evidence
is deliberately named as such. Its purpose is checking real cross-language wire
contracts and replay routing, not substituting a fake successful execution.

The .NET SDK is optional; its absence is a named skip. No Revit reference DLLs
or running document are needed. Temporary journals are removed after each run.
