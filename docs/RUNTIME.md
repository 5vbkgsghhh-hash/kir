# Runtime, evidence and idempotency

The runtime layers define how a KIR program becomes an effect in a host model
without confusing a request, a completed transaction and a semantically correct
result.

## Execution states

KIR distinguishes pre-effect refusal, rollback, unknown-after-dispatch,
partial commit and full commit. In particular, a lost response after dispatch
is not safe to replay. A trusted late receipt may reconcile one bound operation
only when its identity and committed transaction status match.

Chunked programs are folded as a whole. If one chunk has already committed and
a later chunk cannot complete, the program is recorded as partial rather than
being reported as a full commit or a harmless failure.

## Witnesses and readback

An execution result and a semantic result are separate facts. The host should
return transaction state and a readback of relevant native facts; callers can
then evaluate postconditions and retain evidence. An unavailable witness stays
unknown rather than becoming a successful build.

## DirectShape promotion

Geometry-first authoring is useful for concept work and complex shapes. KIR
does not silently relabel such geometry as native BIM. Promotion requires a
separate native candidate plan, explicit approval, a committed transaction and
an independent readback bound to that exact candidate.
