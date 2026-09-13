# Bounded construction site: a state model

Module: `kir/construction/schedule.py`. Acceptance:
`kir/construction/tests/test_a_site_schedule_is_deterministic.py` (28) and
`kir/construction/tests/test_the_schedule_follows_the_trajectory_and_the_ground.py`
(24). The neighboring slice `kir/construction/site.py` computes TRAJECTORIES
and coverage zones; this one computes the SCHEDULE. No second geometry is
set up: `CraneEnvelope.from_tower_crane()` takes both the envelope and the
kinematics from the already-existing `TowerCrane`.

## What the model does

| subject | how it is expressed | number on the reference case |
|---|---|---|
| six panels, one crane, one crew, one zone | `SitePlan` | 6 / 1 / 1 / 1 |
| typed tasks `deliver → install → release` | `Task` | 18 tasks |
| dependencies (i+1 after installing i) | `Task.depends_on` | a chain of 6 links |
| occupancy: the crane during delivery, the crew during install | `Task.resources` | TC-1 3600 s, CREW-A 5400 s |
| zone — one panel at a time, from delivery to release | `zone_owner` | ZONE-1 9720 s |
| deterministic events | `ScheduleResult.events` | 48 events |
| total | `total_time_s` | **9720 s**, order P1…P6 |
| crane delay 1620→3600 | `Unavailability` | **11700 s** (+1980) |
| an intruder in the zone 2000→2500 | `Unavailability` | **10600 s** (+880) |
| pause and resume | `SiteSimulation.pause/resume` | the outcome is byte-identical to the continuous run |

The same input gives a byte-identical `ScheduleResult.to_json()` — this is
checked by comparing two runs, not by a promise.

`pause(t)` lays the `SiteState` out as DATA (it survives `json.dumps` and back).
`resume(state)` continues from that same event: panels installed before the
pause are not installed again.

A delay or an obstruction move the SCHEDULE, and the shift is visible in the
`task_started` event's reason (`unavailable:TC-1:crane_maintenance`), not only
in prose.

## The 07.09 seam: geometry stopped being only an input

Mandate F9: "the equipment's geometry is not limited to the load's point, once
its envelope is promised; a delay and an obstruction change the
schedule/result." Four places were stitched, and none of them turns on by
itself.

| subject | was | became | number |
|---|---|---|---|
| delivery duration | an INPUT, `deliver_s` | computed by `plan_tower_crane_lift()` from the crane's speeds | the same 6 panels: **9720 → 7534.663811 s**; deliveries 250.233…223.771 — six DIFFERENT numbers, not a constant |
| the number's origin | not named | the event field `duration_source` | `deliver` → `trajectory`, `install`/`release` → `declared` |
| an obstruction on the path | had no effect on the schedule | raises the wiring level | **7534.663811 → 7654.938258 s**, each of the 6 deliveries +20.046 s |
| zone | an identifier with capacity 1 | + a convex POLYGON in mm | a panel outside the polygon is a refusal, `panel_outside_zone` (P4) |
| an intruder | a time window with a resource name | a BODY: a polygon × `[z0,z1]` + a window; the zone is chosen by `signed_distance` | a body in the zone: **3790.988938 → 4690.988938 s**; the same body off to the side: 0, and stated as `intrusion_touches_no_zone:IN-2` |
| cranes and zones | one each | several; a panel takes the FIRST reaching crane, the chain is PER ZONE | two cranes + two zones: **6120 s**, deliveries P1 and P4 run in parallel over `[0, 600]` |
| one zone with two cranes | — | still ONE panel at a time | the same two cranes, one zone: **9720 s**, no overlap of deliveries, `[]` |

This only turns on by declaration: without `CraneEnvelope.kinematics` and
without a promised panel rigging (`pickup_mm`/`gross_load_kg`/`load_radius_mm`),
delivery stays an input number, and a zone without `footprint_mm` stays the
old identifier. So the reference plan above (9720 / 11700 / 10600 s) did not
shift by a single second.

A partial promise is not hidden, it is named in `reductions`:
`crane_kinematics_not_promised:TC-2`, `panel_lift_not_promised:P2`,
`zone_footprint_not_promised:ZONE-2`, `intrusion_touches_no_zone:IN-2`.

**A lift planner's refusal does not turn into time.** `unknown` (the
obstruction's envelope contains a body, but is not itself a body) is a
separate name, `lift_feasibility_unknown`, not a "maybe" passed off as "yes."
The refusal list grew from 6 to **10**: `lift_feasibility_unknown`,
`lift_path_blocked`, `panel_outside_zone`, `panel_over_capacity` were added.
Every name is raised as a LITERAL — a refusal through a variable is invisible
to the `ast` parse that checks the list's closedness, and the list would
silently stop guarding anything.

**The state's shape was raised to `kir-construction-schedule-state/2`.**
`zone_owner` used to be a string — true for exactly one zone; it became a
mapping `{zone: panel}`. A snapshot of the old shape refuses by name,
`state_does_not_match_plan`, rather than being reinterpreted. `state_at(t)`
now returns both `zone_owners` (every zone) and `zone_owner` (the owner of the
plan's MAIN zone).

## Reach: the envelope, not the load's point

If a panel's envelope is promised in the plan (`plan_half_extent_mm`), the
whole envelope is checked against the reach ring `min_radius_mm …
max_radius_mm` and the hook ceiling. A panel at a 19500 mm radius with a
half-extent of 1500 mm gives an outer radius of 21000 mm against a 20000 mm
reach — this is a **named refusal, `panel_out_of_reach`**, not a silent "it
lifted." The same point without a promised envelope passes, but the reduced
check is named in `ScheduleResult.reductions`
(`panel_extent_not_promised:P4`) — it is not hidden.

The closed refusal list is `REFUSAL_CODES` (10 names): `cyclic_dependency`,
`dependency_unknown_task`, `lift_feasibility_unknown`, `lift_path_blocked`,
`panel_out_of_reach`, `panel_outside_zone`, `panel_over_capacity`,
`schedule_deadlock`, `state_does_not_match_plan`, `state_is_inconsistent`. The
list is checked against the source by an `ast` parse in both directions, not
against the author's memory.

## What the 07.09 self-review closed

| probe | was | became |
|---|---|---|
| a pause at the exact moment of an event, at t=0 and at t=T (21 points) | green | now pinned by a test: event numbers form an unbroken run, the outcome is byte-identical to the continuous run |
| the order of panels in the input | undecided | **decision: the list order is an EXPLICIT part of the plan**; a reversed list gives a reversed queue with the same T; the order of keys in `to_dict`/`from_dict` affects nothing |
| a window in the middle of a started task | green | now pinned: there is no quiet third option, the task does not run "through" the window, it waits (the delivery starts at 500, T=10220) |
| a forged snapshot | **4 forgeries of 6 were accepted, 2 crashed with `KeyError`** | all 6 now refuse by name: `check_shape()` (structure) + checking the snapshot against its events and against the plan in `_load` |
| the closed refusal list | not checked | an `ast` test in both directions |
| zone occupancy | computed correctly, but the instrument could not tell ownership apart from the sum of tasks | a gap inside the panel was added (the crew's window): ownership 10320 versus 9720 by tasks |

Occupancy is a consequence of the input, not a constant: at different
durations the crane equals the sum of deliveries (2100), the crew equals the
sum of installs (4200), and the zone equals ownership.

**A zone is occupied by the PANEL, not by the task.** If installation is
delayed (the crew is busy), the zone stays with the panel the whole time, and
that shows up in the number, not only in prose.

## What the model does NOT claim

1. **This is not a construction-safety conclusion.** A passing scenario means
   the SCHEDULE is feasible for the given numbers, and nothing beyond that.
   The words "safety" and «безопасность» are deliberately absent from every
   output field; the test
   `test_the_output_carries_no_verdict_beyond_the_schedule` holds this
   property.
2. **Real workers are not modeled.** `Crew` is an anonymous resource with an
   identifier and a size. No names, no personal data, no accounting for a
   specific person's labor.
3. **There is no camera and no animation here.** `ScheduleResult.state_at(t)`
   returns the STATE at a point in time; an animation must follow this state,
   not replace it and not invent frames between events.
4. **The crane's body as an object is not checked** — there is no counterweight
   or counter-jib check, here or in `site.py`. Reach speaks only of the
   panel's planned envelope against the reach ring, and nothing else.
5. **Collisions between two cranes are not checked.** There is no crane body
   as an object, so there is nothing to check; several cranes are simply
   several independent schedule resources and nothing more.
6. **A panel's containment inside a zone by height is checked IN THE PLAN.**
   The module does not claim "the panel is inside the zone by height"; the
   zone's `[z0_mm, z1_mm]` extent is needed for the intruder's body.
7. **`duration_source="trajectory"` is the time of the LOAD'S PATH** by the
   declared speeds. Rigging, unrigging, and fine positioning are not part of
   it: they are absent from `site.py` too.
8. Collisions of a panel with the built structure, weather, deliveries, and
   cost are not part of the model.

## FAIL control (checked)

A one-line mutation, "remove the crane's occupancy" (dropping `plan.crane.id`
from the `deliver` task's resources), gives **3 red** out of 15: the crane's
load disappears, the crane disappears from the event's resources, and a crane
delay stops moving the total (9720 instead of 11700).

Self-review controls (every mutation reverted, the tree checked with `diff`):

| mutation | red out of 28 |
|---|---|
| panels are sorted by id (the input order is lost) | 1 |
| the window is checked by its start point, without duration | 2 |
| a name that nothing ever raises was added to `REFUSAL_CODES` | 1 |
| `check_shape()` disabled entirely | 2 |
| checking the snapshot against its events disabled | 1 |
| resuming loses the zone's owner | 3 |
| the zone is computed by the sum of tasks, not by ownership | 1 |

Two mutations did NOT turn red at first, and this was recognized as a defect
of the INSTRUMENT, not of the code: the "by tasks" zone count in the loop was
being overwritten further down (the control stood on a dead branch), and the
reference case with no gaps could not tell the two counts apart. The
instrument was strengthened, the control moved onto a live line.

### Controls for the 07.09 seam (every mutation reverted, the tree checked by md5)

| mutation | red out of 66 |
|---|---|
| the number's origin is always `declared` | 12 |
| the crane is assigned first, with no reach check | 9 |
| the chain is global again, not per zone | 3 |
| containment checks the install point, not the envelope | 2 |
| an intruder occupies the zone with no geometry | 1 |
| the trajectory's "maybe" is taken as a time | 1 |
| the snapshot is not checked against the events by zone owners | 1 |
| the kinematics is not checked against the declared envelope | 1 |

The last mutation gave **0 red** on the FIRST run of the controls: the
property "two truths about one crane are forbidden" was held by the code, but
was not guarded by any instrument. This is a defect of the instrument, not of
the code; the test
`test_kinematics_that_disagree_with_the_envelope_are_refused` was set up, and
now the mutation turns red.
