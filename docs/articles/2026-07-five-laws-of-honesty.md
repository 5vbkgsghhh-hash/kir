# Five Conservation Laws of Honesty for an AI Agent in CAD

*Five laws a Revit compiler now enforces mechanically, and the catch behind each one. Every number
here has a row in `publication_manifest.json` — commit, date, instrument, artifact — and anything
still in flight is marked `[PENDING: …]`.*

*Written 2026-07-28, revised 2026-07-30. The revision closes two `[PENDING]` markers with
measurements and adds three episodes from 29–30 July: the first document census, which took our best
coverage figure from 92.83% to 9.61%; a stage counter of 14 343 that turned out to be 19; and a
refusal path on which a failed write was being folded into the conversation as a success.*

---

## The setting

KIR is a typed intermediate representation for Revit. A language model plans; the compiler owns
correctness. It emits C# against real Revit reference assemblies for six versions (2021–2026),
runs it in a transaction on a live model, and reads the result back. Its permanent invariant:
**zero silently-wrong outcomes** — every call is either built-with-a-witness or a typed refusal
carrying a route.

That invariant was written down early, as prose. On **2026-07-28** two independent audit passes
found no hardcoding to our own buildings — and four places where prose had failed to compile:
the certificate counted geometry **proven** while the effect was dead; the "read only in part"
signal was lost before it reached disk; refusal lists were persisted and read by nobody; the
denominator of every coverage percentage was a *sample*. So honesty became arithmetic: five
conservation laws (spec §18), each with an enforcement mechanism — a lint, a CI fixture, or a
runtime identity. Breaking a law is a build or run failure, not a note to a reviewer. Each law
exists because something caught us.

---

## Law 1 — Census: count what you did not look at

> `|elements in document| = lifted_into_ops + atoms(typed) + not_read(typed:
> category_outside_table | budget_cut | workset_closed | page_refused)`, on any model, every
> run. The denominator of any coverage percentage is the whole left-hand side.

**The catch.** Extraction reads a *closed* table of categories — 47 at the time of this
measurement, 73 today. Everything outside it — topography, site, parking, landscaping, masses,
rebar, pipe and duct insulation — produced not one element, not one status row, not one refusal.
Our headline coverage (measured 2026-07-27 with `coverage_matrix.py`: 93.28% on a 1 383-element
R2023 model, 92.83% on a 90 758-element R2026 one) described **what we had looked at**: its
denominator is the categories the extractor reads, not the document. Both figures — and every
coverage percentage in this article — predate the census law and must be read that way. A
percentage with a self-selected denominator is not a weak metric; it is a different metric
wearing the name of the one you wanted.

**The mechanism.** One cheap full-model pass keyed by `BuiltInCategory` — no geometry, no
parameters, once per *category* rather than per element. Reconciliation is deliberately
**asymmetric**: an undercount *is* the `not_read` bucket, typed row by row; an overcount ("we
read more than the document holds") is refutable and always a defect, so it is a run-fatal
`census_balance_mismatch`, never a warning. The passport prints *categories in model X, read Y,
not read Z* before any percentage. Enforcement: a CI fixture holding a category outside the table
must produce non-zero `not_read` instead of a quiet 100%.

**The number it produced.** That `[PENDING]` closed on 2026-07-29, and it is the most useful figure
in this article. Censused on a real set of working drawings — a residential complex of 59 storeys,
R2023 — the document holds **310 558 elements across 112 categories**. Our table matched **24** of
those categories and read **55 293 elements: 17.80% of the document.** The remaining **255 265** are
now typed by category instead of invisible, and the four largest buckets are legitimate rather than
embarrassing (area-scheme boundaries 61 520, elements with no category 53 885, sketch lines 38 093,
automatic sketch dimensions 19 547).

And the coverage figure, on the denominator the law demands: **9.61%** — 29 848 typed operations out
of 310 558 elements. The same run, measured the old way, reports **53.98%**. The same compiler on
other models reported 92.83% and 93.28%.

None of those numbers is a lie and only one of them answers the question a person with a building
would ask. This is what the law is for: not to make the number smaller, but to make it *the number
of something*. The census also balanced — `census_balanced: true`, no overcount — which is the half
of the law that can actually fail loudly.

The follow-up is the honest anticlimax. On 2026-07-29 the reading table went from 54 categories to
73, admitting 60 587 elements of real working documentation — 13 905 dimensions, 11 585 room tags,
3 046 detail components, 2 697 text notes. Reading rises from 17.80% to a projected **37.31%**.
**Coverage stays at 9.61%**, exactly, because nothing lifts the new categories yet; the 60 587
become typed atoms and the atom count goes 25 445 → 86 032. A wave that makes the document twice as
visible and moves capability by zero is a good wave, and saying so in the same sentence is the whole
discipline. (The 37.31% is arithmetic over the census, not an observation — `[PENDING: live
confirmation that the 19 added categories return their census counts; the wave named its own risk,
13 905 dimensions in one probe under a 30-second timeout]`.)

---

## Law 2 — Receipt: every cut leaves a trace

> Any budget cut, timeout, unparsable row or unrecognised response shape must emit
> `{element_id, typed_reason}`. A stage answers `rows` **and** `failures`, both keys mandatory,
> and every requested id must leave a record — a row, a receipt, or both.

**The catch.** The measurement that produced the law, on a live decompile of a facade model
(R2023, 30 443 elements, 2026-07-28):

| stage            | requested | rows | receipts | **no trace** |
|------------------|----------:|-----:|---------:|-------------:|
| curve            | 1178      | 1178 | 0        | 0            |
| curtain          | 1178      | 1178 | 983      | 0            |
| sketch           | 55        | 55   | 5        | 0            |
| family_placement | 1799      | 1557 | 0        | **242**      |

Rows and receipts are not disjoint — a stage can return a row that itself carries a typed failure,
which is why curtain shows 1 178 rows *and* 983 receipts. The accounting question is the last
column: how many requested ids left no record of any kind.

Two hundred and forty-two elements walked out of a stage and were never mentioned again. All 242
were `OST_CurtainWallPanels` — a curtain panel that is a *wall* is not a `FamilyInstance`, so the
placement index had nothing to say. Downstream they became atoms reading *"element is absent from
the family placement side index"*: from outside, indistinguishable from a hole in the compiler's
capabilities. "We cannot build this" and "we did not look" had become unrecoverable from each
other.

**The mechanism.** A shared side-stage contract — eight typed reasons, a per-batch validator, and
an aggregator lifting totals into `run.json` and the passport by reason. Emitters have no mute
exits left, and one unparsable row becomes one receipt with an element id instead of killing the
run with "internal decompile error". The same wave found a *wrong* belief in that file —
`mirrored == hand XOR facing`, the only assertion not marked MEASURED, false for mirroring about
an arbitrary plane — and neither deleted nor trusted it but **demoted it to a receipt**. An
unproven belief that emits evidence when it fails is worth keeping; one that fails silently is
not.

The law then bit our own diagnostics. A live rebuild refusal arrived with an `[elements: …]` tail
from the failure preprocessor and was truncated twice on the way to disk — at 300 characters in
serving and 160 in the short form — so the diagnostician worked blind. With the limits raised to
4000, the next deferred failure named its culprits: `11401364, 11402544`, a grille family that a
curtain host type generates. **Evidence must never be shorter than the cause.**

### The sequel: a receipt can satisfy the law and still lie

Two days later the same law produced the most expensive number of the week, and the number was
wrong.

The stage counter for curtain-wall parsing on the working-drawings model read **14 343** — by a wide
margin the largest mass of parse failures anywhere in the reverse direction. A wave was scoped
against it; that is what a ranked list of failures is *for*. Before writing code, the wave checked
the artifact. **14 324 of the 14 343 were ordinary walls with no curtain grid — and every one of them
already had an index row saying precisely that** (`curtain_available: false`). The stage had
answered them cleanly. The receipt was restating that same clean answer as a second number, in the
column whose name means *failure*.

The real number of curtain failures was **19**.

Every letter of Law 2 had been obeyed. Each of those 14 324 elements left a record; each record
carried an element id and a reason. What the law had not said is that **a receipt for a
non-event is indistinguishable, when counted, from a receipt for a loss** — and counting is what
receipts are for. So the fix was not a smaller number but a second axis: a **cut** (we did not
finish looking: budget, exception, unparsable row, our own address and schema limits) is now a
different kind of thing from a **determination** (we looked, and this element does not have this
aspect). The classifier is deliberately self-critical — an ambiguous case is filed as a *cut*,
against our own interest — because the alternative is a category that flatters us by construction.
Untyped failures went **14 569 → 0**; cuts settled at **3 092**, determinations at **14 931**; the
stage line now reads *"curtain 19 cut / 14 324 answered"*.

Coverage did not move by a single point, and that was a requirement of the wave rather than an
outcome: field-by-field comparison against a clean tree at HEAD, no element reclassified to improve
a percentage. **The wave that discovers its own headline number was fiction is exactly the wave that
must not be allowed to bank a percentage.**

Two smaller findings from the same work are worth the space, both found by falsifying tests rather
than by reasoning. A typed receipt without an elapsed-time field could not be read back, so the
persistent index silently stopped parsing and the stage recomputed itself without saying so. And the
emitted C# merged two causes into one string — `element not found` and `element of the wrong class`
were the same sentence. A receipt that cannot be read back, and a reason that names two different
worlds, are both receipts in name only.

### The same law, from the other side: 2 846 receipts with one sentence between them

The counter-example arrived the same day and is the more painful of the two, because here the
receipts were real losses and still told us nothing.

Group reading on that model returned 95 rows and **2 846 failures**. All 2 846 carried one identical
string — *"group read failed: InvalidOperationException"* — with no call name and no Revit message.
Two thousand eight hundred and forty-six losses; **one** distinguishable sub-cause. The law was
satisfied and the diagnosis was impossible, which is how a bug survives for as long as this one did.

What broke the case open was a *coincidence* in the surviving rows, not the receipts: all 95
survivors were **nested** groups — `group_id_parent` non-empty in 95 of 95, a location transform
available in 0 of 95. A perfect correlation between "survived" and "has no location point" pointed
at one branch. Autodesk had documented the answer in all six versions: `LocationPoint.Rotation` "is
not supported for some elements supporting LocationPoints, such as AssemblyInstances, **Groups**,
ModelText, **Room**, and SpotDimensions", and throws. The read sat inside a `try` wrapping the whole
element, so every placed group threw and lost its entire row. **2 846 of 2 941 groups — 96.77% — in
every model, for as long as the code had existed.**

After the fix, a live read of the same document returned **2 941 rows and 0 failures in 1.7
seconds**, and group membership visible to us went from **11 elements to 41 077**.

The enforcement that followed is now the shape of the law rather than a patch: **every optional read
gets its own guard**, because an unread extra costs its own field and never the whole row; and a
receipt must carry the *step* — `Group.Id`, `GroupType`, `GetMemberIds`, `Location…` — plus the
platform's own message, not just an exception class name. The letter of Law 2 has been amended to
match: a receipt that cannot distinguish two causes is a count, and counts are not receipts.

---

## Law 3 — The witness signs the axis it actually reads

> A `geometry` obligation is discharged only by reading geometry; `topology` only by reading a
> relation; `semantic` only by reading a parameter or state. Reading a parameter ordinal does
> **not** discharge a geometric obligation.

**The catch, and the counter-catch.** The audit named `create_wall.location_line` the single
silent-wrong it could find: the op writes `WALL_KEY_REF_PARAM` ("wall centreline", "finish face
exterior", …), the plan offset is hardcoded `0.0`, and the witness signs `(geometry)`. The
prescribed fix was the obvious one — shift `p0/p1` along the plan normal by `factor × width`.

Then we measured it. Live Revit 2023, a 30 443-element facade model, everything inside a
transaction closed with `RollBack()`. Solid tessellation — real body edges, not bounding boxes —
on **724 genuinely non-centred walls** across ordinals 0, 2, 3 and 5 put every near face at
**−0.500000** and every far face at **+0.500000** of the wall's width, spread 1e−13. The
`LocationCurve` the API returns is **always the centre plane of the body**, under every ordinal;
setting the ordinal moves neither axis nor body. What the rule really decides is **which plane
stays put when the thickness later changes**: swap a 200 mm type for a 400 mm one under ordinal
2 and the exterior face holds while the axis slides 100 mm to the new centre.

So the prescribed fix would not have realised a missing effect — it would have *introduced* a
half-thickness error in 724 walls in that document alone (24 618 carry the rule in another), and
the lifter could not have compensated, because extraction never captures a wall's width at all.
**The lie was never in the geometry. It was in the label.** The op took the third path the law
itself allows: `kind=semantic`, with `post` saying in plain words that the rule is written and
does not move the body. The same day found a second hole: the certificate had **no obligation at
all** under the key `location_line`, so the witness could have been deleted outright and it would
still have said "proven".

Enforcement: `test_witness_axis_honesty.py` forbids a check signed `(geometry)` from resting
solely on reading back a parameter the emitter itself wrote; it failed on `location_line` before
the fix. The lesson, now spec §18.8: **an op-level prescription must rest on a measurement, not
on the auditor's model of the API — and the audit is not exempt from the rule it enforces.**

---

## Law 4 — Contagion: a partial read marks everything made from it

> Workset state is a mandatory L0 header field; `is_partial_read` rises into `run.json`, the
> passport and status; derived artifacts carry the mark; idempotence and rebuild **refuse** by
> default; a percentage computed on a partial read prints only with the mark.

**The catch.** Measured 2026-07-27 on a training model (R2026): the document was opened with
**17 of its 18 worksets closed**. `FilteredElementCollector` honestly returned what it could
see — **11 elements instead of 2016**. Every category status said `complete`, and the passport
would have reported high coverage. A silently-incomplete read is indistinguishable from a
complete one — exactly the outcome this compiler declares inexpressible on the writing side.

The C# measured the worksets, the parser parsed them, `is_partial_read` was implemented and
correct — but the header writer never wrote the three fields, and the flag had **zero
consumers**. Every part existed except the wire between them: the most expensive shape a bug can
take, because each part reviews as correct.

**The mechanism.** Three fields into the header and both constructors; the flag lifted into
`run.json` and the passport; the mark printed *before* the percentages; idempotence and rebuild
refusing with a typed `partial_read` plus a named carve-out that travels into the report. Note
which gate had been missing: it stood on the tool that **measures**, not on the one that
**writes**. And archives taken before this wave keep "no data" as "no data" — declaring them
partial retroactively would be the same lie pointed the other way.

---

## Law 5 — Delivery neutrality

> No device-id literals, absolute installation paths, domain names, or localised category and
> parameter names as the sole key of a rule in executable compiler code.

**The catch.** `serving.py` carried `ADMIN_DEVICE = "a6d7d143…"` and compared against it. That
literal gated the entire reverse path — decompile, rebuild, idempotence. For an outside developer
it was not "restricted", it was **unsatisfiable forever**, and the refusal never said what to
configure. The telemetry feed defaulted to this installation's absolute path: elsewhere, the first
compiler refusal would try to create `/opt/kukai-rebuild1/…`.

**The mechanism.** An installation allowlist (`KUKAI_ADMIN_DEVICES`; **set and empty = the live
path is off entirely**) with a refusal that names the variable; no telemetry path = feed silently
disabled; rules keyed on `BuiltInCategory` and `BuiltInParameter`, a localised name admissible
only as an *additional* key that refuses typed on a miss. Enforcement: `test_supply_neutrality.py`
plus a CI pattern lint (32-hex literals, `/opt`/`/root` outside test code, Cyrillic in rule keys).

This is a law of honesty rather than of packaging for one reason: a gate a stranger can never
satisfy is a silent "never works" — the same failure mode as a silently wrong answer, only slower
to find.

---

## The climax: laws 1 and 2 caught **us**

The facade model's coverage — on the pre-census denominator above — was 76.64%, and curtain panels
were the visible hole: 0 of 734 lifted. Mullions looked like the healthy part: **956 of them, all
lifted**, as point-placed `place_family` operations with a host. Closing the panel gap took the
facade to a headline **95.0%**.

Then census-and-receipt discipline was pointed at our own output, and the mullions turned out to be
our own classification bug. A `Mullion` *is* a `FamilyInstance` by class — which is what made the
heuristic "any family instance can be placed by `place_family`" look right — but the only way to
create one is `CurtainGridLine.AddMullions(Curve, MullionType)`, applied **along grid segments**;
a `Mullion` has a `LocationCurve`, not a point. A rebuilt curtain wall also generates mullions from
its own type rules. So each of the 956 was, at best, an operation we could not prove was safe to
replay.

Here is the part we could not shortcut. Of the 956, **317** sit on hosts with no cutting line at
all — provably generated by the type, and legitimately excluded from honest coverage as
`generator_child`. The other **639** cannot be classified either way until we capture
`AUTO_MULLION_*` from the host type: they may be authored, they may be generated, and we do not
know. Calling all 956 "duplicates" would have been a second false claim in the opposite direction.
All 956 were therefore removed from the lift as **typed atoms** naming the host and `AddMullions`
— unsafe-to-lift, reason recorded — and the facade figure fell from **95.0% to 55.8%**. That is a
correction, not a regression: the earlier number counted operations we could not stand behind.

Both of the `[PENDING]` markers this section carried on 2026-07-28 have since closed, and neither
closed simply.

**The mullion pending.** Capturing `AUTO_MULLION_*` did what it was supposed to: two independent
Revit witnesses — `Mullion.Lock` and the host type's twelve auto-mullion slots compared by
`BuiltInParameter` id — proved most of those mullions type-driven, generator children rose from 700
to 1 556, and the facade figure went **55.77% → 85.66%**. About 34 mullions across three hosts stayed
atoms because the two witnesses disagreed, which is the correct outcome of having two.

Then the same night measured **closure** — do those children actually come back when the model is
rebuilt? — against rebuild #8's own artifacts. Confirmed: **417 of 1 556.** 779 missing, 144 the
wrong type, 216 unmeasurable. So 85.66% is a *lift-side* number, honest about what we chose not to
lift and silent about whether the choice reproduces. The root cause was measured rather than
guessed: every rebuilt curtain host carried **zero** interior grid lines while its type-driven
parameters reproduced byte-identically — the missing generator link was the grid line itself. That
measurement put a `create_curtain_grid_line` operation in the registry the next morning, and it went
green on live Revit the same day.

**The rebuild pending.** Runs #4 and #5 each died one phase deeper than the last, and each failure
became a falsifying test before its fix. #6 completed end to end. #8 ran on a swept clean model.
And #11 is the one that matters here, because it is the run where the fail-soft carve-out **actually
fired**: a chunk of 250 operations was refused as a single typed receipt with Revit's verbatim
detail preserved, and *the run finished anyway* — through comparison, through a clean cleanup, with
the refused operations kept in the coverage denominator rather than quietly removed from it. The
trap that caused it has resisted twelve live experiments and remains unreproduced outside full-model
runs. It is now a visible receipt instead of a dead run, which is the entire ambition.

This was the second time in two days that a metric of ours was measuring something other than what
it claimed (the internal precedent is known here as "the 98% retraction"), and it was not the last:
within another two days a stage counter of 14 343 turned out to be 19, and a coverage figure of
92.83% turned out to be 9.61% once the denominator was a document. Which is the argument of this
article:

> **A metric that can catch itself is the only kind you can believe.** Every other kind is a
> metric you have not caught yet.

---

## The forbidden state, found in our own plumbing

One more, from 2026-07-30, because it is the failure this whole article exists to prevent and we
were carrying it ourselves.

The report was that KIR refuses *worse* than raw C#: an operator's live session produced a refusal
with no error code, no compiler codes and no repair suggestions, and the reading was "the model is
told it did not work, without a diagnosis". The measurement was right. The conclusion was wrong, and
the refutation matters more than the fix: the cause **did** reach the model, verbatim — the typed
code, the Russian text, the list of violated post-conditions — and it was never truncated on the
way, the refusal envelope being 470 characters against a 50 000 limit. Of the three symptoms, two
were correct behaviour: compiler codes are empty *by construction* when the template assembled and
the runtime refused, and repair suggestions are empty by design.

The real defect was underneath, and it was the forbidden state. The machine-readable half of the
refusal was never attached on the KIR path — the one function that stamps a typed cause was not
called even once — so the receipt read its code from the bridge's response, which a *structural*
refusal does not carry. And the detector that decides whether a tool call failed tested for a
boolean `error: true`, while KIR returns `{"ok": false, "error": "<string>"}`. **A failed write was
therefore folded into the conversation as a success.**

That is worse than the complaint that started the investigation. A loud refusal with a thin
diagnosis costs a round; a silent success costs the model's entire picture of the building, and
every subsequent operation is planned against a document that does not exist. The fix is one
interception point wrapping the whole entry, so that no refusal path can *physically* forget to
stamp its cause, and one shared predicate replacing two different detectors that disagreed.

The design question that came with it was answered against our own convenience. Should a KIR refusal
trigger an automatic LLM repair loop, as the C# arm does? **No** — and the reason is the reason KIR
exists. In the C# arm the model's own code failed, so asking the model to rewrite it is coherent. In
KIR the C# is generated by our compiler from a verified template; a language model repairing it
would paper over a *server* defect and destroy the property the whole system sells, because a
repaired template is no longer the one we verified. The model's artifact here is the program, and it
is repaired on the next turn by a refusal that names the operation, the field, and expected against
got. Repair exists — it is just observable.

## Why this generalises past Revit

Strip the CAD nouns and the five laws are obligations for any agent acting inside someone else's
expensive world:

1. **Census.** Put what you did not look at into the denominator.
2. **Receipt.** Every cut emits an identifier and a typed reason. Aggregate counts are not
   receipts; ids are.
3. **Witness axis.** Sign only the axis you actually read. "The setter ran" is not "the world
   moved".
4. **Contagion.** Anything derived from a partial input carries the mark, and irreversible
   actions refuse it by default.
5. **Neutrality.** Ship so a stranger can execute your gates. An unsatisfiable gate is a silent
   failure with good manners.

An agent triaging patients, reconciling ledgers or moving a robot arm has the same structural
problem as one modelling a building: **it is usually the only witness in the room**, and its
report on its own work is the channel through which everything else is decided. Prose obligations
drift, because prose does not fail a build. Arithmetic ones fail loudly, at the moment of the
mistake, in front of the person who made it.

None of the five laws made the compiler more capable. Two made the headline numbers worse on the day
they landed, and the census law later took our best coverage figure from 92.83% to 9.61% by the
simple act of counting the whole document. That is the point: honest numbers are the only ones
capability can be built on.

A closing note on the shape of these findings, because it is the most portable thing here. Of the
corrections in this article, exactly one was caught by a test. The rest were caught by *asking an
artifact a question the code had already answered* — reading the receipt file before scoping a wave,
correlating which rows survived, comparing the stage counter against the index it was supposedly
counting, and, in the end, building an index of the platform vendor's own documented refusals so
that the question always has somewhere to be asked. Sixteen thousand six hundred and seventy-nine of
those conditions were sitting on our own disk, shipped with the API, for the whole time the group
bug was eating 96.77% of every model.

---

*Every figure above is listed in `docs/articles/publication_manifest.json` with its commit, the
date it was measured, the instrument that produced it and the artifact it can be re-derived from.
Coverage percentages in this article predate the census law and carry its denominator caveat.*

## A sixth law, learned the expensive way: the seams must check themselves (2026-07-30)

Four defects surfaced in one day of live running. **None of them was in the language.** All four were
at seams:

* a new side stage exposed its rows as `text_notes` while the census reconciler asks for `records` —
  the run died on 26 elements with a perfectly working C# emitter behind it;
* the dry compile gate and the live path counted by different op budgets, so 26 chunks that compiled
  refused to execute;
* the offline measuring tool did not load a new index, so it reported as atoms what the live pipeline
  was lifting — the second time that exact blind spot cost us a number;
* the metadata body read the document's identity from the HOST while its elements came from a LINK,
  which would have written a foreign name into the snapshot header.

The pattern is not carelessness. It is that these contracts were **implicit** — knowledge living in one
function and in somebody's head. So the fix is not four fixes; it is making the contract explicit and
letting the build fail when the next one breaks it. One test now walks every registered stage and
demands it answer to `records`/`failures`; a stage registered without a declared contract fails the
suite in under a second, instead of failing on a live model forty minutes into a read.

The same day taught the operational half of it. A user complaint — "the server drops now and then" —
turned out to be measurable and constant: during a decompile, `/health` did not answer **twelve times
in a row, 25 seconds each**, while a minute earlier it answered in 2 ms. 62 chat sockets closed
abnormally in 12 hours across ten different devices. The process had not restarted in 14 hours and used
592 MB of a 4 GB limit; it was simply doing heavy synchronous work on the event loop, single-worker, and
was dead to everyone for the duration. "Now and then" meant "every time anyone runs a decompile".

For weeks that symptom had been attributed to the operator's network. **A plausible explanation is more
dangerous than an unexplained one** — nobody investigates the plausible.

## A seventh law, found by building the tool that finds it (2026-07-31)

The sixth law said the seams must check themselves. The night after writing it we
built the instrument that does — and it paid for itself within the hour by
finding the same defect a second time, in a place nobody had looked.

The story starts with a number that nobody read. A fresh snapshot of a 59-storey
tower reported **2 153 verification failures where the previous snapshot had
zero**. It had been sitting in the artifact for a day. Nobody read it because
everyone was looking at the coverage percentage, and coverage had gone up.

All 2 153 were rooms — and that was **100% of the rooms we lifted**. The cause
was three words in an argument list: `source_location_mm=None`, passed
explicitly, under a comment explaining that the snapshot format did not carry a
room's location. The comment was true when it was written. It stopped being true
the day the capture side started recording that location — and nothing anywhere
noticed, because the two halves had agreed by *comment*.

The consequence was not cosmetic. For a non-convex room — an L-shape, a
corridor — the centre derived from the boundary can lie **outside the room**. A
rebuilt room would be created in the neighbouring space, or not at all.
Connecting the capture took one line and moved the failures from 2 153 to 15.
The remaining fifteen are named, not written off: they are 4 m² bathrooms whose
real insertion point sits closer to the wall than an arbitrary margin allows —
which is our other named defect class, a bound authored by reasoning instead of
measurement.

So we built a ledger: for every field, who WRITES it into the snapshot and who
READS it back. Three lists, derived from the code by parsing it, not by grepping
it. The important list is the first one — captured, consumed by nobody.

It found the second case immediately. The ceiling lifter reads a parameter
called `CEILING_HEIGHTABOVELEVEL_PARAM`. The capture side's whitelist does not
contain that name at all — it has the *floor* equivalent, and nothing else.
And because that input is **optional**, there is no refusal: the key is missing,
the value is `None`, the parameter is simply not set, and the ceiling is rebuilt
at the elevation of its level. Silently. With full coverage. With a green
witness.

The unit test is green too, and this is the part worth sitting with: the test
writes that key into a synthetic element **by hand**. The lifter is tested. The
capture is tested. The contract between them is tested by nothing, and a test
that constructs its own input can never discover that the real input never
arrives.

**The seventh law: a contract between two components must be verified against
what the other component actually produces, never against a fixture that
describes what it ought to produce.** Every synthetic input is a small, sincere
lie about the world, and a suite made of them can be entirely green while the
product is entirely wrong.

The same night, a second instrument counted every numeric bound in the compiler —
258 of them. Twenty-seven were traceable to a measurement. A hundred and seventy
were simply asserted. And a third kind surfaced that nobody had thought to name:
**103 bounds are bare literals written straight into a comparison**, with no
name and no comment, invisible to any search for constants — and one of *those*
topped the harm ranking. Two of the assigned bounds reject not elements but
entire buildings; one misses on nine buildings out of nine, because it claims to
describe storey height while it actually measures the gap between level marks,
and a level in Revit is also a slab soffit, a parapet, a mezzanine.

The instrument also vindicated one bound we suspected. It rejects 227 rooms in
one model — and those 227 have boundaries that disagree with Revit's own area
figure by 43.9% at the median. The check is right; the defect is a layer above
it. **An audit that only ever confirms its own suspicion is not an audit**, and
this one earned its verdicts by occasionally returning the answer we did not
expect.

## An eighth law, from a day that found nothing where it looked (2026-07-31)

The release goal was blunt: every basic operation above 95% on a real building.
The corpus said `create_door` succeeded 44.8% of the time, `create_column`
55.6%, `create_wall` 71.3%. So we went to fix the operations.

There was nothing wrong with the operations.

The witness corpus recorded three things separately: which operations ran (by
NAME), which operations produced an element (by ID), and which postconditions
were violated (by ID). Nothing joined the first to the other two. A program that
built a wall and hung a door on it, where the door's flip state came back wrong,
was recorded as a failure — of *both*. The wall was fine. It was in the corpus,
built, witnessed, and blamed.

Fixing the join took one field. What it revealed took the rest of the day.

Two of the three defect classes we had set out to fix **were already fixed**. Ten
beam violations carry timestamps between 13:05 and 13:22 on one afternoon; the
commit that removed that mistaken witness landed at 13:23:40 — fifty-three
seconds after the last failure. The door's flip defect had been closed a week
earlier, twice. They were still in the corpus because an append-only journal
does not forget, and we had been reading it as a description of the present.

**The eighth law: a measurement that spans a change to the thing measured is
not a measurement.** A rate computed over the whole history of an append-only
log mixes behaviour before and after every repair, and it gets *worse* the
harder you work. It is a peculiar kind of dishonesty, because every individual
row in it is true. Only the sum lies. The tool now prints the corpus time span
on every run, so a month cannot be read as a today; a headline number comes from
one fresh run.

The third class was real, and it turned out to be a rule rather than a bug.
`height_mm` carries a registry default of 3000 mm. Validation fills that default
into the operation *before* the emitter sees it, so the emitter cannot
distinguish "the caller asked for exactly 3000" from "the caller said nothing,
because the top level decides the span". A facade wall between two storeys
naturally says nothing. The compiler then promised the built wall would measure
exactly 3000 mm, checked, found otherwise, and rolled back — every correctly
built wall on the facade.

**A default the caller never spoke is not a promise you may enforce.** Where the
emitter itself sets the value, witnessing it is fair: the promise is ours and we
keep it. Where Revit decides — a wall attached to a top level derives its height
from the level pair, whatever was passed at creation — the check demands
something nobody asked for. Twenty parameters in the registry carry defaults;
six are silently injected; the list is now closed by a test, so the seventh will
have to answer the question out loud.

The day's last number is the one worth ending on, because it reframes the goal.
To claim an operation is "above 95%" with 95% confidence takes **73 consecutive
successes** — sixty gives you 94.0%, a hundred gives 96.3%. Not one operation in
the corpus clears that bar; the strongest is a deletion primitive at 33 for 33,
which is 89.6%. So "every basic operation above 95%" was never mainly a repair
problem. It is an evidence problem, and evidence of that size is not gathered by
a campaign of small trials. It is gathered by rebuilding a building: one circle
through Autodesk's own shipped sample is 6,343 operation executions, each
carrying its own postcondition, each one a witness.

The instruments were wrong in three ways in a single day, and every one of them
made the product look worse than it was. That direction of error is the
comfortable one to discover. It is not the one to count on.
