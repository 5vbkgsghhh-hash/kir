# A Day of Measured Revit API Traps

*Fifteen findings that cost us live probes, as symptom → wrong hypothesis → measurement → rule.
Read the classification line on each one first: several are **our** bugs that Revit merely made easy
to write, and saying so is the point.*

*Written 2026-07-28, revised 2026-07-30. The fifteenth was added in revision, and it is the one that
changed how we work: a single documented sentence about a single property, which we had never read,
was silently destroying 96.77% of the groups and 100% of the rooms in every model we had ever
touched. It is also the reason for the postscript on habit four.*

---

## How to read this

Every item carries a **classification**:

- **documented** — the behaviour follows from the shipped API reference; we simply had not read it;
- **observed** — measured live, on the version and model stated, and not (yet) derivable from the
  documentation. An observation is not an API contract, and we do not present it as one;
- **our bug** — Revit behaved per contract; our compiler, extractor or witness was wrong.

Unless a line says otherwise, every live measurement below was taken on **2026-07-28**, against
**Revit 2023**, on a facade model of 30 443 elements, inside a transaction, on a device from the
installation's allow-list. Item 15 and the postscript are from **2026-07-29**, and their live
measurements were taken read-only, without transactions, on a different document — a set of real
working drawings for a residential complex of 59 storeys. Every number has a row in
`docs/articles/publication_manifest.json` (commit, date, instrument, artifact); probe payloads and
experiment sources ship with the release. Two habits produced most of these findings: we compile
every emitted body against reference assemblies for **six versions (2021–2026)** before it runs, and
every write ends in a witness that reads the built element back instead of confirming that a setter
ran.

---

### 1. `AUTO_PANEL` and `AUTO_PANEL_WALL` are two enum members with the *same* visible label

**Classification: documented (API surface) + our bug — we read the wrong one.**
**Symptom.** The host's default panel type came back `null` on **all 195 curtain hosts in this
model**, while cell addresses arrived fine (169 non-`(0,0)` addresses out of 311 cells).
**Wrong hypothesis.** "These curtain wall types carry no default panel" — which would have turned
311 cells into honest refusals for nothing.
**Measurement.** `RevitAPI.xml`, all six versions: `BuiltInParameter.AUTO_PANEL` and
`AUTO_PANEL_WALL` both carry the visible label **"Curtain Panel"**. On the curtain *wall* types in
this model the default panel lives on the `_WALL` variant; the unsuffixed one answered `null` on
every one of the 195 hosts. We do not claim that as an API-wide law — only as what 195 hosts
reported.
**Rule.** Read **both**, and record which one answered. Never let a null mean three things at once:
we now carry `default_panel_state: ok | none | unreadable | not_captured`, because "empty", "could
not read" and "our schema never captured it" have different consequences.

---

### 2. `CurtainGrid.ChangePanelType` (R2023) threw with an **empty** `Message`

**Classification: observed, narrow — one call, one version.**
**Symptom.** The call failed and our refusal read, in full: `ChangePanelType: `. An hour of guessing.
**Wrong hypothesis.** "The cell address is wrong."
**Measurement.** Grid *reading* had succeeded (the cell guard would have fired otherwise), so the
failure was in the write, and `Exception.Message` was empty. We report this as an observation about
this call on this version: without the raw payload we could not have excluded our own bridge losing
the text — which is exactly why the refusal now prints the exception type and everything around it.
**Rule.** A catch around a Revit call must print what distinguishes causes, because the exception may
print nothing:

```csharp
catch (Exception ex)
{
    string diag = ex.GetType().Name + ": " +
        (String.IsNullOrEmpty(ex.Message) ? "(empty Revit message)" : ex.Message);
    if (ex.InnerException != null) diag += " | inner " + ex.InnerException.GetType().Name;
    // panel class (GetPanelIds returns BOTH Panel and Wall), lock state, new type, host:
    diag += " | cell (u,v) panel " + panel.Id + " (" + panel.GetType().Name +
            "), unlocked=" + IsIn(grid.GetUnlockedPanelIds(), panel.Id);
}
```

With that in place, probes P6 and P7 returned the same line —
`InvalidOperationException: (empty Revit message) | cell (0,0) panel … (Panel), unlocked=NO`. P6 ran
against an **already existing** host, so the transaction was not the cause; P7 passed a `PanelType`
instead of a `WallType`, so the kind of type was not the cause. What was left was the lock.

---

### 3. Freshly generated curtain cells came back locked — and the verb that unlocks is `Element.Pinned = false`

**Classification: observed causality (before/after probe); the failure dictionary supplied only the hypothesis.**
**Symptom.** `unlocked=NO` on the cells generated by the host type in our R2023 sample.
**Wrong hypothesis.** "There is a `Lock` setter on the panel." There is not: across the 2021–2026
assemblies `Panel` exposes only `Lockable { get; }`, while `Lock { get; set; }` belongs to `Mullion`.
**Measurement.** Revit's own failure dictionary contains
`BuiltInFailures.CurtainWallFailures.TypePanelsFronNonRectCellsUnlocked` — *"Type-driven panels …
were UNLOCKED and left unchanged"* — which told us that unlocking is a routine Revit operation on
this class of panel, but **not** which verb performs it. Only the probe decided that:

| probe | lock state before | setter | call result |
|---|---|---|---|
| P6 / P7 | `unlocked=NO` | — | `InvalidOperationException`, empty message |
| P8 | `unlocked=NO` | `Element.Pinned = false` | `ChangePanelType` executed, post-conditions passed |

`Pinned` lives on `Element`, so one line unlocks a `Panel` and a cell that is a `Wall`.
**Rule.** Unlock only what is locked, and do not re-lock: in the original model all 53 replaced cells
were already unlocked, i.e. the author had done it by hand, so unlocking reproduces the authoring act
rather than inventing one. We do **not** claim that all type-driven panels are always pinned — we
claim it for the freshly generated cells we measured.

---

### 4. `ChangeTypeId` and `ChangePanelType` have **different** return contracts — and both matter

**Classification: documented (two separate contracts) + our bug — we merged them, then read the wrong element.**
**Symptom.** A type change "succeeds" and the read-back witness still sees the old type.
**Wrong hypothesis.** "`ChangeTypeId` returning `InvalidElementId` means it failed." That reading
would have broken the ordinary path.
**Measurement (assemblies' XML across six versions, plus live experiments E1–E4).**

- `Element.ChangeTypeId` returns `InvalidElementId` on the **normal, in-place** success; a real id is
  the documented rare case where Revit *replaced* the element; an incompatible type throws
  `ArgumentException`.
- `CurtainGrid.ChangePanelType` is a different contract: it returns the **modified or replacement
  panel element**, and for a `WallType` that element is a new one.
- E1–E4 then found the sting: `ChangePanelType` with a `WallType` silently builds a wall of the
  **host grid's** type, not the type you asked for. The cure is `ChangeTypeId` on the returned wall,
  where `-1` is the ordinary success. And `GetPanelIds()` **never** lists that wall occupant, even
  after commit, so a membership check against the panel list rejects a correct result; we replaced it
  with a spatial axis match (measured 0.0 mm; 50 mm tolerance kept for arcs).

**Rule.** Read the element that came back, never the reference you passed in — a witness re-reading
the old reference after a replacement is a witness of a dead element — and do not assume the returned
element carries the type you requested.

---

### 5. A curtain grid materialises on `Regenerate`; its auto-generated content fails *late*

**Classification: documented lifecycle + observed timing + our orchestration bug.**
**Symptom.** A curtain wall created by our own program had a type but behaved as if its cells were
half-real; separately, a 250-op chunk rolled back whole and took a rebuild with it.
**Measurement.** The stale-until-`Regenerate` lifecycle is documented; what we measured is where it
bites for curtain grids — reading the grid of a freshly created host worked, writing to it did not,
and one `doc.Regenerate()` before any grid work fixed it. Then the deferred half: on live facade
rebuild #3 six chunks committed (**1 226 elements**) and one isolated host (10006947) rolled back
with «Не удалось сформировать тип "ATR_Панель витража с решеткой …" [элементы: 11401364,
11402544]» — a grille family generated by the host *type*. Experiments E6/E7 narrowed it further:
Revit today does not form that grille type inside a **100 mm** cell, while the original survives
because existing elements are not re-formed. The lifter had lost nothing — we were asking for what
the model contains.
**Rule (ours, not Revit's).** `doc.Regenerate()` before any work with the grid — a half-materialised
grid can be neither read nor modified — and never wrap that regen in a try/catch, since a failed
regeneration means a corrupted document and the transaction owner must abort loudly. The lost chunk
was **our** orchestration bug: `SubTransaction.Commit` leaves changes "not permanently committed"
and posted errors are "delivered at the end of transaction", so per-op isolation cannot contain a
deferred failure. Such a host now gets a program of its own, and an isolated program's refusal is a
typed receipt instead of a dead run. That carve-out was written the same evening and was still
untested when this article was first drafted; it fired for real on 2026-07-29, in a full-model
rebuild where one 250-operation chunk was refused as a single typed receipt with Revit's verbatim
detail preserved — **and the run completed anyway**, through comparison and a clean cleanup, with the
refused operations left in the coverage denominator rather than quietly removed from it. Those two element ids only became readable after our
refusal-detail truncation went from 300/160 characters to 4 000: evidence must not be shorter than
the cause.

---

### 6. Mistakes we made reading `Wall.Create` and `WALL_KEY_REF_PARAM`

**Classification: our bug, both halves; the API is documented and consistent.**
**Symptom.** Walls sitting below their level; and a location-line rule the compiler wrote but could
not see.
**Wrong hypothesis.** Reading the 6th argument of
`Wall.Create(doc, curve, typeId, levelId, height, offset, flip, structural)` as a *plan* offset. It
is documented as the base offset from the level — vertical. The only trap is that "offset" reads as
planar when you are trying to run a wall's exterior face along a line.
**Measurement (the half worth having).** We measured `WALL_KEY_REF_PARAM` on **724 non-centred
walls** — 135 at ordinal 2, 442 at ordinal 3, 147 at ordinal 5 — by solid tessellation, sampling up
to 40 walls per ordinal for the face-distance control. Every sampled wall put its near face at
**−0.500000** and its far face at **+0.500000** of the type width, spread 1e−13, and setting the
ordinal moved neither axis nor body on any of the six ordinals we set. What the rule decides is
**which plane stays put when the thickness later changes**: under "Finish Face Exterior" a
200 → 400 mm type swap held the exterior face and slid the axis 100 mm to the new centre.
**Rule.** Do not "implement" location line by offsetting `p0/p1` — on this evidence you would inject
a half-thickness error into every non-centred wall.

---

### 7. `MirrorElements` on a hosted instance damaged elements outside its own op

**Classification: observed incident, scoped — a KIR safety ban, not a claim about the API.**
**Symptom.** Three doors refused with "mirror copy unavailable" — and three **different** doors, on a
different host, lost their geometry and ended up at `[0,0]` with no body.
**Wrong hypothesis.** "A per-op `SubTransaction` contains the damage."
**Measurement (2026-07-27, R2023, 178 ops, three runs on separate lanes).**
`ElementTransformUtils.MirrorElements` with `mirrorCopies: true`, on hosted door instances in walls.
Remove flips from all ops: 0 refusals, 0 violations, 0 breakages. Remove them only from the three
that refused: the breakage **moves to a fourth op**. Earlier rounds also saw a mirrored door survive
its own sub-transaction and then kill the final `Commit`.
**Rule.** KIR does not mirror hosted instances. Flips go through `flipHand`/`flipFacing` when
`CanFlip*` allows, and an unreachable flip is a **named postcondition violation**, never a silent
skip. We have not isolated which family and host combination triggers the collateral damage, so we
ban rather than explain.

---

### 8. MEP system membership merged at `Commit()`, not at `Regenerate()`

**Classification: observed (one R2023 probe) + two of our bugs.**
**Symptom.** "Segments span multiple systems" — every time, on a straight pipe run.
**Wrong hypotheses (two rounds).** First: "`Pipe.Create(systemTypeId, …)` leaves the segment with no
logical system, so call `NewPipingSystem` over the free connectors." Second: "`ConnectTo` never
merges membership."
**Measurement (2026-07-27).** A pipe emitted by our own op came back already carrying
`MEPSystem #21201145`, with **both** connectors reporting that system while `IsConnected == false`.
Our first bug follows: we called `NewPipingSystem` on connectors Revit had already used, hence
`Some of the input connectors have been used.` Our second bug was the witness — it demanded final
system identity *inside* the transaction. In this probe the two systems stayed distinct through
`doc.Regenerate()` and were merged after `Commit()` (two connected pipes came back both reporting
`#21201856`).
**Rule.** Do not construct the logical system, and do not assert final membership in-transaction:
check **connectivity** there (a BFS over the connector graph) and read system identity back after the
commit as a reported fact.

---

### 9. Our selector ignored `FamilyPlacementType`; the factory signalled failure with `null`

**Classification: documented return convention + our grounding bug.**
**Symptom.** A beam creation call returned `null`, with no exception and no message.
**Measurement (2026-07-27).** The documented contract allows `null` when creation does not succeed.
The symbol we passed had `Family.FamilyPlacementType == OneLevelBased` (point-placed) and we handed
it to a curve-driven overload: our type pool never filtered on placement type. On the model we swept,
all 36 framing families were `OneLevelBased`, which is also why the op had nothing to prove itself on.
**Rule.** Filter candidate symbols on `FamilyPlacementType` **before** emitting, and treat `null` as a
first-class refusal path — several Revit factory methods signal failure that way.
`[PENDING: we also observed a curve-plus-level placement collapsing a vertical segment to a point,
but have not isolated whether that follows from placement type, overload or curve orientation; no
claim until a placement-type × overload × orientation matrix exists]`

---

### 10. `Parameter.HasValue` does not imply a *resolvable* `ElementId`

**Classification: the API is consistent; our witness was wrong.**
**Symptom.** A correctly built beam was accused by its own level-binding witness, which compared `-1`
against the expected level id.
**Wrong hypothesis.** "`HasValue` is the test for 'this link points at something'."
**Measurement (live, on a beam, 2026-07-27).** `FAMILY_LEVEL_PARAM` reported
`HasValue = True, AsElementId() = -1`. That is coherent: `InvalidElementId` **is** an assigned value,
it simply does not resolve to an element.
**Rule.** When walking a chain of candidate parameters
(`FAMILY_BASE_LEVEL_PARAM → FAMILY_LEVEL_PARAM → SCHEDULE_LEVEL_PARAM → LEVEL_PARAM`), accept a link
only if it resolves:

```csharp
if (p == null || !p.HasValue || p.AsElementId() == null ||
    p.AsElementId() == ElementId.InvalidElementId) { /* try the next parameter */ }
```

---

### 11. `Panel.GetRefGridLines` takes `ref`, not `out` — and only `Panel` has it

**Classification: documented API surface + our extractor gap.**
**Symptom.** Code that reads a curtain cell's address compiles in your head and not in Roslyn.
**Measurement.** Against reference assemblies for all six versions, passing `out` gives **CS1620** on
every one; both references must be initialised before the call:

```csharp
ElementId uRef = ElementId.InvalidElementId;
ElementId vRef = ElementId.InvalidElementId;
panel.GetRefGridLines(ref uRef, ref vRef);   // ref, not out
```

**The second half is ours.** `GetRefGridLines` exists on `Panel` only, while
`CurtainGrid.GetPanelIds()` returns both `Panel` and `Wall` elements, and curtain-cell windows whose
family category is `OST_Windows` are not `Panel` at all (50 of them here). We previously called those
addresses unreadable "by construction". That was too strong: there is no *direct* Panel API for them,
but an address can in principle be derived from grid topology and spatial association — our own
emitter already does spatial matching for a wall occupant.
`[PENDING: whether the extractor can recover a cell address for non-Panel occupants; until then they
are typed atoms naming the reason, not a proven impossibility]`
**The rule that does hold.** Never address a cell by index into `GetPanelIds()`: Revit promises no
order, and ids differ in a rebuilt model.

---

### 12. A mullion cannot be *placed*; our lifter said it could

**Classification: our lifter bug, invited by the class hierarchy.**
**Symptom.** None — this looked *healthy*: 956 mullions on the facade model, all lifted, as
point-placed family instances with a host.
**Wrong hypothesis.** Our own heuristic: "a `Mullion` is a `FamilyInstance`, so `place_family` can
place it." It is a `FamilyInstance` by class, which is what made the heuristic convincing.
**Measurement.** `RevitAPI.xml`: the only creation path is
`CurtainGridLine.AddMullions(Curve, MullionType, oneSegmentOnly)`, applied **per grid segment**, and a
`Mullion` carries a `LocationCurve`, not a `LocationPoint`. A rebuilt curtain wall also generates
mullions from its own type rules.
**What we could and could not prove.** Of the 956, **317** sit on hosts with no cutting line at all —
provably generated by the type. The other **639** cannot be classified without capturing
`AUTO_MULLION_*` from the host type: they may be authored, they may be generated. Calling all 956
"duplicates" would have been a false claim in the opposite direction.
**Rule.** Before "supporting" an element class, check how Revit *creates* it, not what class it
reports. All 956 became typed atoms — unsafe to lift, reason recorded — and the facade coverage
figure fell from 95.0% to 55.8%.

**How the 639 resolved (2026-07-28 night).** Capturing the host type's `AUTO_MULLION_*` slots
settled it with two independent witnesses rather than one: `Mullion.Lock`, and the twelve
auto-mullion slots of the host type compared by `BuiltInParameter` id. Most of the population proved
type-driven; **about 34 mullions across three hosts stayed atoms because the two witnesses
disagreed**, which is the correct behaviour of having two. Honest lift coverage of that model went
**55.77% → 85.66%**.

That is a lift-side number and it comes with its own correction, which is the more useful half. A
**closure** check — do these children actually reappear when the model is rebuilt? — confirmed only
**417 of 1 556**. The cause was measured, not guessed: every rebuilt curtain host carried **zero**
interior grid lines while its type-driven parameters reproduced byte-identically. The missing
generator link was the **grid line itself**, which no creation operation existed for. One was written
the following morning and went green on live Revit; the same op then supplied all 122 grid-line
operations inside the single chunk that a later full-model rebuild refused, which is where that
story currently stands.

**A separate accounting of the same axis** (working-drawings model, 2026-07-29) shows why this class
of element is worth the trouble: of **21 192** curtain-family elements, **13 627 are generated by the
curtain itself** and need no operation at all, **5 167** lift to operations, and **2 398** are lost by
us — an honest 68.30% of the axis. All 2 398 reduce to two operations that do not exist:
`create_curtain_system` (1 431, of which 1 429 are cascade children of just two unliftable hosts) and
`CurtainGridLine.AddMullions` (856). They were deliberately **not** written when the gap was found:
no live Revit was available that day, and an operation that compiles but has never executed is
fake-ready.

---

### 13. `NewDimension` needs **geometric** references — and a fresh wall has none until you regenerate

**Classification: documented requirement + our bug, twice.**
**Symptom.** Live probe P11 refused with `references are not geometric references`; the six-version
compile gate had been perfectly happy.
**Wrong hypothesis.** "A `Reference(element)` is a reference."
**Measurement.** Experiment E5 proved the working recipe: `HostObjectUtils.GetSideFaces` for walls,
whose dimension read back **3 000.0 mm exactly**; the fallback is the first `PlanarFace` carrying a
`Reference` under `Options { ComputeReferences, View }`, otherwise a typed refusal. A second live
round added the timing half: a **freshly created wall has no harvestable faces before
`doc.Regenerate()`**. The dimension line's direction also had to come from the face normal in the
view plane — `RightDirection` was wrong for the ordinary case of two parallel walls.
**Rule.** Harvest faces, not elements; regenerate before harvesting; and let the witness gate only
what it can own — existence, topology and view are gated, while the measured value travels in the
receipt, because the number depends on which faces you chose.

---

### 14. `FootPrintRoof.set_SlopeAngle` — ratio, not radians `[PENDING]`

**Classification: observed once, and not yet to our own evidentiary standard.**
A 45° roof came back 5 221 mm tall where 45° needs 6 400 mm, which is consistent with Revit reading
the value **0.7854 as rise/run** (38.15°), with `400 / cos(38.15°) = 509 mm` of vertical thickness
accounting for the residual. We emit `tan(radians(deg))` on that basis and it has behaved since. But
this is **one undated probe, one value, and no read-back of `ROOF_SLOPE`**, so by our own rules it
stays pending until two independent values, a parameter read-back and a geometric residual exist.
`[PENDING: slope probe with date, two independent values, ROOF_SLOPE read-back, span/thickness/type]`

---

### 15. `LocationPoint.Rotation` is documented as unsupported for `Group` and `Room` — and one `try` turned that into a decade of missing data

**Classification: documented (in all six versions, in a file on our own disk) + our bug, twice, in
two different files.**

**Symptom, part one.** Group reading on a real set of working drawings returned 95 rows and **2 846
failures** — 96.77% of every group in the model. All 2 846 receipts carried one identical string:
`group read failed: InvalidOperationException`, with no call name and no Revit message. Two thousand
eight hundred and forty-six losses with **one** distinguishable sub-cause between them.

**Wrong hypothesis, and it was in a code comment.** The reason the bug was *written* survives in the
source: *"the observable bridge dialect, in which there is no angle, is a limitation of the BRIDGE,
not a contract; `LocationPoint` exposes `Rotation` directly, so it is honest to return both."* The
observation was accurate and the inference was backwards. The angle was missing from the dialect
because **that read does not exist for a group.**

**Measurement.** Not a probe — a *coincidence*, then a document. All 95 survivors were **nested**
groups: `group_id_parent` non-empty in 95 of 95, a location transform available in 0 of 95. A
perfect correlation between "survived" and "has no location point of its own" indicts one branch and
exonerates the type, name and membership reads on the line above. `RevitAPI.xml`, all six versions
2021–2026, `P:Autodesk.Revit.DB.LocationPoint.Rotation`:

> This property is not supported for some elements supporting LocationPoints, such as
> AssemblyInstances, **Groups**, ModelText, **Room**, and SpotDimensions.

…and it throws `InvalidOperationException`. The read sat inside a `try` that wrapped the *whole*
element, so every placed group threw and lost its entire row — always, in any model.

**Proof of the fix, live.** Read-only, no transactions, on the same document: **95 rows / 2 846
failures → 2 941 rows / 0 failures, in 1.7 seconds.** Group membership visible to us went from
**11 elements to 41 077**. The angle is now simply absent from the row rather than defaulted to
zero, which is the dialect the strict parser was already written for.

**Symptom, part two — the same member, a different file.** With the index of documented conditions
built (see the postscript), the same member was queried across our whole source. It was read the
same way in the *geometry* store — that is, on **every element of every model**, not just groups —
where it stood *before* three assignments inside one shared `catch`. So the throw took not only the
rotation but **the point itself**.

**Measurement.** Every persisted decompile run we have: **12 369 room rows and 566 area rows across
55 runs and four buildings — 100% of them `bbox_only`, with a null point.** Not one room in any model
had ever received its location. On the working-drawings model alone that is 2 442 rooms. The same
total signature as the groups: not a sampling issue, a law of our code.

A false invariant had grown on top of the bug, which is what made it durable. Strict parsing
*required* a rotation wherever there was point geometry — a rule written in the confidence that
rotation is always available — and that requirement forced emission to choose between "a point with
no angle" and "nothing". It chose nothing. Removing the invariant was part of the fix; the opposing
invariants (a point-less point, an angle on a curve) are still errors and still under test.

**Rule.** Three of them, and the third is the general one:

1. **Every optional read gets its own guard.** An extra that fails to read costs its own field and
   never the whole row. One `try` around a whole element converts a documented limitation on one
   property into total data loss.
2. **A receipt must carry the step and the platform's message** — `Group.Id`, `GroupType`,
   `GetMemberIds`, `Location…` — not just the exception class. 2 846 identical strings satisfy the
   letter of a receipt law and defeat its purpose.
3. **The observed dialect is data.** When a field is missing from what the platform hands you,
   *explain* it before you route around it. Every instinct says the absence is an artefact of your
   own plumbing. Sometimes the absence is the API telling you the truth.

---

## The pattern behind the fifteen

Count the classification lines — several items carry more than one label, so the three counts below
overlap and do not sum to fifteen. Listing the item numbers so the count is checkable rather than
asserted (the 2026-07-28 draft said "nine of the fourteen" and could not be reconciled against its
own text, which is the sort of thing this article is supposed to be too careful to do):

- **A defect of ours: eleven** — items 1, 4, 5, 6, 8, 9, 10, 11, 12, 13, 15.
- **Rests on documented behaviour we had not read: seven** — items 1, 4, 5, 9, 11, 13, 15.
- **An observation too narrow to call an API contract: six** — items 2, 3, 5, 7, 8, 14.

That distribution is the actual lesson: "Revit is weird" is usually a bug report about yourself. And
note which way item 15 pushed every count at once — it is documented, it is ours, and it was the most
expensive thing on the list.

Three habits produced almost all of them, and all three are cheap:

1. **Compile every emitted body against every Revit version you support, in CI.** `ref` vs `out`,
   `Floor.Create` vs `NewFloor`, 64-bit `ElementId` since 2024 — these belong in a build log, never in
   a live session with a user's model open. And note what a gate cannot see: it was perfectly green
   on the `NewDimension` call that could never work.
2. **Make the check read the result, not the call.** Nearly every item above was invisible to a test
   that verified "the setter ran": the slope was set, the mirror was called, the level parameter *had
   a value*, the panel type was changed, the mullions *were created*.

The third habit is the cheapest and we adopted it last: when a Revit call throws, print the state that
distinguishes causes — exception type, inner exception, the actual classes of the objects involved,
lock state, ids. Revit is allowed to hand you an empty string, and an hour of guessing costs more than
every diagnostic you will ever emit.

## Postscript: habit four, and why it took a 96.77% data loss to find

Every one of the fifteen findings above cost a live probe, an experiment, or a day. Item 15 cost
years of silently missing data. And the sentence that explained it had been sitting on our own disk
the entire time, shipped with the API, in a file we open every day for other reasons.

We did not ask, because there was nowhere to ask. So the fourth habit is a tool: **an index of
everything the vendor documents about how its API refuses**, built once and queried before hitting
the wall rather than after. Ours reads the six shipped reference XMLs — **35 516 members, 16 679
distinct documented conditions, 0 unparsed, about thirteen seconds to build** — and answers by
member, type, exception, phrase, version difference, or the wording itself, every quote carrying the
vendor's own file and line.

One design decision is the whole tool, and getting it wrong would have reproduced our blindness
exactly. The condition on `LocationPoint.Rotation` — the one that cost us the groups and the rooms —
is documented under a `<throws>` tag. **There are eight of those in the entire index.** The frequent
tag is `<exception>`: 10 307 in the 2023 assembly alone. An indexer reading only the common tag
would have reported a confident five-figure number, felt thorough, and walked straight past the
sentence that mattered.

The ranking is built from a signal the index supplies about itself: **how many members share the
wording.** "A non-optional argument was null" appears on 3 809 members — that is a house style, not
information. The sentence about `Rotation` appears on exactly one. What a vendor wrote once, it
wrote about something specific.

Two honest caveats, because a tool that audits our code is exactly the kind of thing that flatters
whoever built it:

- **It paid for itself twice on its first day** — it found the rooms bug described in item 15, and it
  caught a `Mesh`/`Abort` target-fallback pair in brand-new code that the six-version compile gate
  had certified **green 6 of 6**, while the documentation lists the supported combinations and that
  pair is not among them. A green gate on a combination the vendor excludes is precisely the class of
  error nothing else we own can catch.
- **Its first ranking was partly wrong, and fixing the tool mattered more than fixing the code.** Of
  105 flagged members, the top of the list did not survive review: **4 were false findings**, all
  from one cause — the tool asked "is there a `try`/`catch` here?", so a condition already discharged
  by our own source read as still open. It now evaluates *predicates* over the call site rather than
  keeping a list of exceptions, so changing `typeof(Wall)` to a runtime type brings the finding back
  by itself, with tests to prove it. Nothing is deleted; a discharged finding prints with its reason.
  Four of 105 moved, none were lost.

One number in that paragraph deserves its own warning, since this article is about not believing
numbers. **That count is a property of our working tree, not of the API**: re-running the same tool
on 2026-07-30 reports 109 rather than 105, because the code it reads has moved. Quote it with a
commit or not at all.

And the wave stopped at a place it could not honestly pass: fourteen unguarded `doc.Create.*` calls
that are documented to throw when the current document is a family document — not theoretical, since
our own product does work in the family editor, and a neighbouring module guards *every* template
with the same check. The fix breaks ~306 frozen byte-parity fingerprints, which is not an agent's
decision to make. It is written down and waiting, which is the correct end state for a finding you
cannot yet act on.

---

*Numbers in this article have rows in `docs/articles/publication_manifest.json` (commit, measurement
date, instrument, artifact). Probe payloads (P4–P11) and experiment sources (E1–E12) ship with the
release, so every finding here can be re-run against your own model — which is the only way an
observation ever becomes a contract.*
