# Clash engine

KIR's clash layer is a geometric and semantic query system over building
state. It is designed to report what it can establish, distinguish a candidate
from a proven relation, and never turn lack of coverage into a clear result.

## Structure

1. Snapshot and normalize source geometry with its provenance.
2. Use broad-phase spatial indexing to enumerate plausible pairs efficiently.
3. Run narrow geometric predicates and distance calculations.
4. Classify the relation and attach the evidence, precision and limitations.
5. Produce non-destructive resolution proposals; a host decides whether to
   apply them.

The broad-phase index is an optimisation only. It may over-approximate but is
not an oracle and cannot certify a clash or a clearance by itself.

## Rule verdicts

The habitability ruleset (HAB0xx) reads the same building graph and obeys the same
discipline: a rule that stays silent must say what it examined and who measured it.
Subject, measurement, source and what happens when a function was GUESSED rather than
read are documented per rule in [CHECKER_RULES_RU.md](CHECKER_RULES_RU.md).

## Building Graph relationship

Clash pairs are task-conditioned derived relations, not a permanent dense edge
layer inside the Building Graph. This avoids turning a large model into a
quadratic stored graph while preserving durable semantic relations such as
hosting and containment separately.

## Repair: the declared profile

Repair (`kir/project_fix.py`, strategy `raise_clear`) writes a revision to
history, so what it can and cannot move is a **declared list**, not a property
of whichever check happens to fail first. The list lives in
`kir/clash/repair_profile.py` and is read by `propose_fix` before anything else.

**Supported**

- `box_parameterised_body` — a body whose shape is a box
  `[[x,y,z],[x,y,z]]` in `instance.parameters[output.key]`.
- `free_segment_axis` — a FREE run segment: an axis `p0_mm`/`p1_mm`
  (`ops_mep.create_duct` and friends) with no connector graph, no
  `system_type` and no declared slope. The axis is translated by the same
  vector as the body, so its slope is preserved identically and the number is
  printed in the proposal's explanation.

**Not supported — refused by name, never shifted silently**

- `connectors_declared` — `nodes`/`segments` with `from`/`to`
  (`ops_connect.create_pipe_system` / `route_pipe_system` /
  `route_duct_system`): lifting one segment tears it off its neighbours and
  fittings.
- `system_membership` — `system_type` is declared: the route is what Revit
  derives `MEPSystem` from at commit.
- `slope_declared` — `segments[].slope_min_pct` (`kir/route_mep.py`, KIR-X004
  is a CHECKED postcondition): moving one end changes the slope and the
  program rolls back.
- `mep_category` — the element's category sits on the `mep` side of the closed
  table `kir.clash.hulls.KIND_TABLE` (pipe, duct, tray, conduit, fitting,
  insulation).
- `mep_axis_slope` — the element's axis is DECLARED with a slope (`p0_mm`/`p1_mm`
  differ in z). The refusal carries the slope itself, in percent
  (`repair_profile_unsupported:mep_axis_slope:4.99376`): lifting one end breaks
  KIR-X004, lifting both takes the run out of its system and tears its
  connectors. Inside the MEP branch the order is `slope_declared` (the checked
  floor) → `mep_axis_slope` (the declared axis) → `mep_category`.

Refusals carry the prefix `repair_profile_unsupported:<reason>`, the same shape
as `hull_type_unsupported:<T>` in `kir/clash/hulls.py`.

**What this profile does not claim.** It introduces no MEP model and no new
field name: it reads the words the KIR language already uses. Since 08.09.2026
those words reach a `ProjectRevision` from TWO carriers: `instance.parameters`
(a captured building — a mass with a box and a `metadata.source_category`) and
the output's OPERATION, translated by the single producer
`kir.geometry_materialization.mep_fields`. The producer covers exactly the 11
registry ops whose category sits on the `mep` side of `hulls.KIND_TABLE`, and
that equality is guarded by a test
(`kir/tests/test_an_authored_pipe_carries_its_system_and_connectors.py`), not
promised. Nothing is stored: the fields are derived from the operation on every
read, so the revision never holds a second copy of the same numbers. Capture
still produces none of them, and nothing here is claimed about a live Revit.

## Output discipline

The result carries scope, source identity, relation type, evidence and
limitations. A skipped, truncated or unsupported calculation is represented as
such; it is not reported as zero clashes. Resolution ranking is advisory and
does not mutate the model.
