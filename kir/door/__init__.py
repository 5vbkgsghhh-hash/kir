"""THE DOOR: ONE REGISTRY, TWO ROLES, THREE HOSTS.

🔴 WHOSE PROGRAM THIS IS. `kir/door/` was named by a NEIGHBOURING session's
programme and then removed from that tree. This package is **OUR**
programme's — section H of `.work/prod-20260913/`, written against
`H-harness/STEP3_GATES.md` (G1..G9) and `H-harness/ONE_DOOR_BUILD_PLAN_RU.md`
step 3. If the neighbour's `kir/door/**` ever returns, the two must be
reconciled by name, not merged by hope.

WHY IT EXISTS, IN NUMBERS THAT WERE MEASURED 13.09.2026.

Four tool sets stood for one language: MCP 7 · panel 3 · CLI 9 · window 28
(audit H §1). An agent that learned one relearned the next. The building
tool in the room where DeepSeek SUCCEEDS costs 2 646 B
(`execute_revit_code`: 933 description + 1 713 schema); in the room where
it BROKE, `revit_ir` cost 111 984 B — **42.3x**. Seven turns through the
panel in KIR mode built **0 elements**; the same agents offline through
`kir.dsl` built 12/12, and a trio of Sonnets built 48 ops with no human at
all.

So the surface is not the problem's decoration, it IS the problem. This
package answers with three facts:

  1. ONE registry is the only carrier of a tool. Every host and every role
     is a PROJECTION of it (`registry.projection`). Adding a tool in one
     host and not the others stops being possible.
  2. The agent writes PYTHON against the SDK, not our JSON. Owner's word:
     "примеры программ — это плохо. Нужно только КИР СДК ему знать."
     Measured by S on 13.09: a section slice on task P01 — YES on the first
     attempt, 940 characters of prompt, 0 refusals; against 83 names plus
     help — YES on the second, 2 781 characters; **without help — zero on
     both tasks**, the model tries to invent the reference itself and never
     reaches a program.
  3. A role sees at most FOUR tools, and the lead sees no op name at all.
     Measured by S: a lead with the section map, 591 characters, handed out
     exactly one brief.

UNITS, AND THEY ARE NOT INTERCHANGEABLE. Everything that travels to a model
as a SURFACE (schemas, descriptions, the whole listing) is counted in UTF-8
**bytes**. Everything a model reads as TEXT (the list of names, one op's
help) is counted in **characters**. The old pin measured characters under
the name `SURFACE_MAX_BYTES`; with Russian prose that is a factor of two,
and a number whose unit is wrong is not a number.
"""
from __future__ import annotations

from kir.door.registry import (TOOLS, ROLES, Ctx, Refusal, call, names,
                               projection, tool)

__all__ = ["TOOLS", "ROLES", "Ctx", "Refusal", "call", "names", "projection",
           "tool"]
