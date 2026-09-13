# Checker rules: subject, measurement, source

This document answers one question for every rule: **what its silence stands
on**. A rule that stays silent is not asserting "the building is fine," it is
asserting "I looked and found nothing" — and that claim is obliged to name
WHAT exactly was looked at and by WHOM it was measured.

There are three states of a coverage row (`RuleOutcome`), and they are not
synonyms:

| state | meaning |
|---|---|
| `EVALUATED(n)` | the rule considered `n` subjects of its population |
| `NOT_EVALUATED` | there were no subjects — with a REASON naming the kind of emptiness |
| `excluded_subjects` | there were subjects, but nothing to judge them by — with a reason |

Emptiness comes in two kinds, and they are opposites: **"we did not ask"** — our
own hole; **"we asked, and the building answered NO"** — a fact about the
building. They must not be printed the same way, which is why `vacuous_reason`
is a function, not a string.

The kind of source for a room's function (`kir/checker/function_provenance.py`):

| kind | sources | what is allowed |
|---|---|---|
| read from the author | `explicit`, `room_name`, `declared` | judge strictly |
| derived by us | `fixtures`, `host_classifier` | judging is allowed, BLOCKING is not |
| unknown | everything else | the rule is obliged to stay silent, BY NAME |

---

## HAB010 — an occupied floor is connected to the ground

| | |
|---|---|
| **subject** | an occupied **NON-GROUND** level (`occupied_levels` minus `ground_level_ids`) |
| **measurement** | a path in the connectivity graph from the floor's stair landing to a landing at ground level; vertical transitions are given by `graph.build_graph` |
| **source** | the room function `лестница` (staircase) — it both picks the landing and places the edge |
| **on a guess** | the level moves from `n` into `excluded_subjects` with the code `function_guessed`; when ALL of them do — the row is `NOT_EVALUATED`, and the mandatory rule vetoes PASS |

**A single-storey building.** There are zero non-ground levels, so the rule has
nothing to judge, and the row honestly reads `NOT_EVALUATED(n=0)`. But the
emptiness here is of the **second kind**: a single-storey building cannot have
a dangling floor — that is a fact about the building, not a gap in reading. So
along with the counter, **mandatoriness** (`mandatory`) is also lifted, and the
building's verdict stays reachable. The precedent is HAB011, which is
mandatory only when stairs are present.

> Measured 07.09.2026: 17 of the 25 buildings in the fixture corpus are single-
> storey, and all 17 printed `EVALUATED(n=1), 0 violations` — a claim about work
> that never happened. Fixing the counter alone would have moved 9 of the 25
> verdicts to `NOT_EVALUATED`; the two fixes together moved **0 verdicts** and
> fixed **25 of 25 rows**.

**The path is asked about, not the point.** Provenance is not taken from the
landing that was reached, but from the whole road down: `graph.read_only_view`
strips out vertical transitions marked `provenance == "guessed"`, and the rule
asks about connectivity on that view. A horizontal connection through a door
does not depend on room function and remains.

> A distinguishing case: a three-storey building, where the **middle** floor's
> landing was identified by furnishing. The previous version named a single
> level (L1), whereas neither of the two has a read descent — the only road
> down from L2 runs through that same guessed landing. Cost across 14 runs
> (N=3..6, a guess on every intermediate floor): levels NOT named — **20**,
> apartments — **34 of 34**.

## HAB003 — an apartment has an exit

| | |
|---|---|
| **subject** | a derived apartment (`derive_apartments`) |
| **measurement** | a path from any room of the apartment to a stair landing at ground level; under v2 an exterior door at grade also counts |
| **source** | the same one: the `лестница` (staircase) function of the landings on the path |
| **on a guess** | the apartment moves into `excluded_subjects` (`function_guessed`); the finding is a WARNING, not BLOCKING: a guess does not quash the accusation, but it also does not grant a clean pass |

The engine's classification-coverage note does NOT catch this: it is threshold-
based (0.75), and one guessed landing does not move it — the building printed
PASS.

## HAB031 — glazing ratio

| | |
|---|---|
| **subject** | a residential room/kitchen **with measured glazing and a non-zero floor** (a room with no window at all is HAB030's subject, not this rule's) |
| **measurement** | `window_area_m2 / area_m2` against `thr.min_daylight_ratio` (1:8) |
| **source** | the room's function: the norm is applied to «жилой» (residential), and a sofa could be what named a room «жилой» |
| **on a guess** | the subject is **NOT excluded**: here a guess ADDS to the verdict rather than quashing it, and removing the subject would mean silencing the finding. There is also nothing to lower the severity of — the rule is already INFO. The finding NAMES the function's source, the way HAB030 does |

> The counter used to be shared with HAB030, while the bodies differ: by the
> counter, 80 subjects in the corpus, but the body considered 76.
> `bad_open_envelope` printed `EVALUATED(n=2)` with ZERO rooms actually
> considered. The rule now has its own counter, by its own filter (3 rows out
> of 25).

## HAB062 — a residential-sized room with no rules applied

| | |
|---|---|
| **subject** | the classification outcome for **every** parsed room (`drep.rooms`) |
| **measurement** | area against `thr.unclassified_min_area_m2` (4 m²) |
| **source** | `drep.unclassified_room_ids` — not identified; `drep.derived_function_room_ids` — identified, but NOT by the author |
| **on a guess** | a separate **summary** WARNING row: the number of rooms plus the first three names, the full list in `refs` |

Zero unidentified rooms is a **known clean result**, not the absence of a
measurement, which is why the rule's subject is every parsed room, not the
violations themselves; otherwise `NOT_EVALUATED` would print exactly when the
rule did its best work.

The rule's law reads in two halves: **unknown ≠ exempted** and **guessed ≠
read**. The second half was set up on 07.09.2026: a room whose function was
named by its furnishing leaves `unclassified`, and the silence was becoming
indistinguishable from silence about a properly read building.

> There is ONE row by measurement, not by taste: in the corpus, with a fully
> derived function, there are **236 of 276** such rooms, while the reader gets
> three examples per rule (`render_verdict`) or one (`render_verdict_brief`).

---

## Where this lives

| subject | file |
|---|---|
| populations, mandatoriness, the three states | `kir/checker/engine.py` (`RuleSpec`, `RULE_SPECS_V2`) |
| connectivity, landings, edge provenance | `kir/checker/graph.py` |
| HAB001–004, HAB010 | `kir/checker/rules/connectivity.py` |
| HAB030/031 | `kir/checker/rules/light.py` |
| HAB060–063 | `kir/checker/rules/consistency.py` |
| the kind of function source | `kir/checker/function_provenance.py` |
| this wave's probes | `kir/checker/tests/test_a_path_to_ground_may_not_lean_on_a_guessed_landing.py` |
