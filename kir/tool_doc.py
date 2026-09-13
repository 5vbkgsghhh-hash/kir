"""The prose half of the `revit_ir` tool: what the JSON Schema cannot say.

The schema (`schema_gen.program_schema`) is generated from the registry and is
complete — every op, parameter, bound and enum, ~23k tokens of it. What it
cannot express is the knowledge that only came from running programs against a
real Revit: which ops are PROVEN to build, which are known broken, in what
ORDER a selector has to be resolved, and the traps that cost a live round-trip
each.

Three rules govern this module, all learned the hard way in this package:

1. **The op inventory is GENERATED from `spec.OPS`.** A hand-written list is a
   promise to drift, and the drift is invisible: the tool description shipped
   until 2026-07-27 named 7 of the 28 writing ops, so a model reading it could
   not know KIR authors beams, ducts, groups, family types or annotations at
   all. `test_tool_doc.py` fails if any writing op is missing from the text.

2. **Every trap below is a MEASUREMENT, with its provenance.** This package has
   repeatedly asserted the opposite of the truth in confident prose (the CONNECT
   emitter's own docstring claimed pipe connectors were free — a live document
   said otherwise, and four ops were unbuildable because of it). Nothing goes in
   here that was reasoned rather than observed.

3. **A record is retired by the instrument that set it**, on the day the record
   itself names (`record_ratchet`). A measurement is not evidence forever, and
   this file has twice shipped a record that outlived its own truth — the note
   below names both.

`UNPROVEN` is deliberately part of the contract: telling the model an op is not
yet proven costs a line and saves a round-trip, and it is a debt counter — the
list is meant to shrink to empty.

A RECORD THAT OUTLIVED ITS OWN TRUTH IS THIS FILE'S OWN BREED OF DEFECT, AND IT
HAPPENED TWICE. `create_dimension` told the model "the op does not work" for a
week and a half after the fix (28.07 → 09.08). The `UNPROVEN_GAP` from 09.08
declared twelve ops unnamed — that same day's waves entered all twelve, and the
record stood until the 10.08 re-measurement. What lied was not the arithmetic
but the SHELF LIFE, and both times the record outlived the very measurement
that would have retired it. Hence rule 3 above — and it is about the
DEADLINE, not the arithmetic: the figures in both records were correct on the
day they were set.

THE THIRD CASE TURNED OUT TO BE OF A DIFFERENT KIND, AND IT COST MORE THAN THE
FIRST TWO (03.09.2026). `create_directshape` held HALF a record that had
outlived its own truth for twenty days ("the surface witness was rewritten on
09.08 and never checked live" — in fact 55 full chains after 09.08), and that
half was HIDING the second half, which was plain truth: a census of live
programs showed that all 63 live meshes topped out at TWELVE triangles, that
is, the branch "hundreds and thousands", which the record was warning about,
had never once seen a live Revit. Retiring the record on the strength of the
55 green rows would have amounted to declaring proven exactly what nobody had
tried. The lesson is not "re-read more often" but a COMPOUND one: a record can
have two halves with different shelf lives, and the number of green rows only
answers the half about the trace's presence. The second half is retired by a
sample that covers the branch — and it has now been retired by exactly that
(528 and 3968 triangles live, a full chain for both).
"""
from __future__ import annotations

import logging

from kir import sandbox, spec

logger = logging.getLogger(__name__)
from kir.geom import MAX_RING_POINTS, MIN_RING_POINTS
from kir.record_ratchet import CLOSE_BY, Entry, Ledger
from kir.skill import build_skill_text

#: One reason shared by TWO parametric bodies — see the comment on the first
#: of them. The body wave wrote it for THREE ops together with
#: `create_directshape`; at the 09.08 merge the mesh was dropped from it,
#: because it has a RE-MEASUREMENT (built live 3/3), while the shared row
#: asserted the opposite.
# 🔴 `_SOLID_UNPROVEN` REMOVED 15.08.2026 along with both records it served
# (`create_solid_extrusion`, `create_solid_revolve`): the corpus showed 7/7
# and 4/4 green live builds. The justification is at the removal site below.
#
# 🔴 CORRECTION 19.08.2026, AND IT IS ABOUT THE SAMPLE, NOT THE CONCLUSION.
# The retirement was made on a sample that DID NOT CONTAIN a partial sweep
# with an extremum in the middle of the arc. A bounding-box witness had stood
# on both solids since 09.08 (`75df94fc`), the tolerance was tight — meaning
# a 270° sector could not have passed green either on 15.08 or earlier: on
# 19.08 the very first such run rolled out the CORRECT body (volume matched
# to the fourth digit, the bounding box fell 0.7 mm short of the
# tessellation). What those 4 builds actually were cannot be recovered from
# the tree: `scripts/kir_live_matrix.py`, which the journal cites, never
# mentions `create_solid_revolve` or `sweep_deg` even once.
#
# The records were NOT RETURNED to the journal, and that is a decision, not
# an oversight: the defect was in the witness's TOLERANCE, it has been found
# and fixed (`solid_emit.TESSELLATION_INWARD_FRACTION`), and both operations
# were built live at 90/180/270/359/360° on 19.08 with a green witness and
# re-read on a separate run. Bringing back "never checked live" after it has
# been checked would introduce a second falsehood. What is inherited instead:
# GREEN ON A SAMPLE WHERE THE BRANCH IS DARK is not proof, and a record must
# be retired by a sample that covers the branches, not by their count.

#: Ops whose live behaviour is NOT established, with the reason. Verified
#: 2026-07-27 against SOB6.2 (Revit 2023) via scripts/kir_live_matrix.py; 26 of
#: the 28 writing ops built with a green witness. Shrink this list as they are
#: proven or fixed — never grow it by assumption.
#:
#: SINCE 09.08.2026 EVERY ROW IS DATED AND HAS A DEADLINE (`record_ratchet`),
#: and the reason is this file's most expensive record. `create_dimension`
#: told the model "the op does not work" from 27.07; the fix landed 28.07,
#: but the row stood until 09.08 — for a week and a half the model routed
#: around a working op, because re-reading the record was up to NO ONE and
#: NO TIME: it had no day on which someone was obligated to answer.
#:
#: THE INSTRUMENT BEHIND THIS JOURNAL IS NAMED AND IT IS NOT IN THE TREE: the
#: corpus of live witnesses `data/telemetry/kir_witness.jsonl`
#: (machine-local, in .gitignore). The row "the op was never checked live" is
#: refuted in exactly one way — a corpus row with a nonzero `duration_ms` for
#: this op, and by no reasoning whatsoever. This is exactly why a deadline is
#: mandatory here: only a person with access to the corpus can re-check it,
#: and a test in the tree cannot do that and must not pretend to.
#:
#: WHY min_reason=12, NOT 40 AS IN THE OTHER JOURNALS. The reason travels to
#: the MODEL on every request from here, and the tool description has a hard
#: ceiling of 30 000 characters (`test_tool_doc`), with under a thousand free
#: on HEAD. The full justifications live as comments above each row — they do
#: not count against the budget. The limit is NAMED, not hidden: it is a
#: cost, not carelessness.
_UNPROVEN_ENTRIES: dict[str, Entry] = {
    # wave/space (10.08.2026). The op was created TODAY, so "there are no
    # live rows" is not a corpus measurement but a CONSEQUENCE: the witness
    # corpus ends at 04.08 18:09, that is, six days before the op appeared.
    # Telling these two grounds apart is mandatory: "the instrument said
    # zero" and "the instrument did not exist yet" are different facts, and
    # the second is retired by exactly one live run, not by re-reading the
    # old corpus.
    #
    # WHAT EXACTLY A LIVE RUN WILL CLOSE is named point by point, because
    # this op has two offline-unresolvable questions, not a generic "was not
    # checked":
    #   1. whether `NewSpace(Level, UV)` can return an UNPLACED space — this
    #      decides whether the emitter's typed-refusal path is live or stands
    #      idle;
    #   2. whether `Space.Name` glues the name to the number, as measured for
    #      Room on 04.08 — this decides whether `name`/`number` can be taken
    #      in v2;
    #   3. whether the built space returns the OST_MEPSpaces category to a
    #      live census (in parsing — yes, 126 elements; in the ACTUAL BUILD
    #      never once checked);
    #   4. whether `GetBoundarySegments` returns a non-empty loop for a space
    #      that Revit considers closed. THIS IS THE MOST EXPENSIVE OF THE
    #      FOUR QUESTIONS, and is named for exactly that reason: the boundary
    #      witness is the only one in the op that reads a RELATIONSHIP, and
    #      the only one whose error costs a FALSE RED on a correct build (the
    #      other three err on the side of a miss). `create_room` has no such
    #      witness at all — there closure is proven only by area — so there
    #      is NO precedent this check can lean on.
    # Re-measurement of 15.08.2026 against the corpus: 5 live rows, committed
    # 1, ok 1 — "never once saw a live Revit" became false. The debt remains:
    # ONE green build is not a rate, it is a single observation, and the
    # Wilson lower bound at n=1 says nothing.
    "create_space": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "заведён 10.08; ворота 6/6, живьём 5 прогонов и ровно 1 зелёный — "
        "одного наблюдения мало, чтобы называть оп проверенным"),
    # 09.08. The earlier text — "does not work: the emitter feeds an element
    # reference" — described the state BEFORE 28.07 and outlived its own
    # truth by two weeks: the element reference was already gone by then, and
    # the wall dimensioned live (3000.0 mm). But exactly ONE shape was fixed
    # — the straight wall; the emitter wrapped everything else in a typed
    # refusal, because the geometry walk only knew the top-level `Solid`: for
    # families (column, beam, door, window, furniture) there is
    # `GeometryInstance`, for grids and levels — `Curve`. Both classes were
    # closed on 09.08, but live Revit has not yet seen EITHER of them.
    #
    # RE-CHECKED AGAINST THE CORPUS ON 09.08: 4 rows, one of them green —
    # 28.07 18:50:21 on Revit 2023. All of this is about WALLS; families and
    # grids arrived on 09.08, that is, after the corpus ended (04.08 18:09),
    # and nobody has seen them live. The record stands.
    # 🔴 RE-MEASURED 01.09.2026 AGAINST THE CORPUS, AND THE RECORD STANDS. The
    # `record_ratchet` ratchet went red: the 27.07 decision turned 36 days old
    # against `REVIEW_DAYS = 30`. The instrument named by this journal was
    # run (`tools/live_op_rates.py --corpus …/kir_witness.jsonl`, corpus under
    # 600 — read via sudo): 4061 rows out of 4061, `create_dimension` — 2 runs.
    #
    # SEVEN corpus rows for this op, and among them ones NEW against the
    # record:
    #     2026-07-27 12:03  ok=False  2023
    #     2026-07-28 18:05  ok=False  2023
    #     2026-07-28 18:35  ok=False  2023
    #     2026-07-28 18:50  ok=True   2023   ← the evidence the record was written on
    #     2026-08-22 13:20  ok=False  2026
    #     2026-08-26 13:11  ok=False  2026
    #     2026-08-26 13:12  ok=True   2026   ← GREEN, a month later than the record
    #
    # AND IT IS STILL NOT RETIRED, on the argument recorded below in this
    # same file (kind 3, above `_DISCHARGED_BY_ONE_GREEN_ROW`): **the corpus
    # is keyed by the NAME of the op, and a debt about a BRANCH cannot in
    # principle be refuted by it.** The 26.08 row proves that the op runs
    # live on 2026, and says NOTHING about which target it ran against: the
    # row carries no breakdown by target at all. The key is not entered into
    # `_DISCHARGED_BY_ONE_GREEN_ROW` — that set deliberately holds only one,
    # `create_angular_dimension`, whose reason is exhausted by the word
    # "added".
    #
    # The reason has been rewritten: the half about walls is no longer the
    # only piece of evidence.
    "create_dimension": Entry(
        CLOSE_BY, "2026-09-01", "2026-09-08",
        "живьём идёт на 2023 (28.07) и на 2026 (26.08, зелёная строка из 7); "
        "ветка семейств и осей с 09.08 по-прежнему не подтверждена — корпус "
        "ключуется именем опа и разбивки по мишени не несёт"),
    # 09.08. Written in the same wave; the API exists on all six versions
    # (measured by compilation), live Revit has never once seen it.
    # RE-CHECKED AGAINST THE CORPUS 09.08: ZERO rows. The record stands.
    #
    # 🔴 RE-MEASUREMENT 03.09.2026: ZERO BECAME ONE, AND IT IS THE ONLY ROW.
    # The corpus (4090 rows that made it through) knows exactly one for this
    # op, and it is a full chain: 2026-08-13 18:10:43, Revit 2026, 1408.3 ms,
    # committed · satisfied · accepted. The record's kind is the first one
    # ("never saw live Revit"), the key is declared retirable by one green
    # row — meaning the rendering has been subtracting it from the journal
    # since 17.08 on EVERY machine that reads the corpus: prod has not shown
    # this row to the model for three weeks, and it is only printed where
    # there is nobody to ask. This makes it only the second case of a record
    # that outlived its own truth, and it is honest by construction.
    #
    # WHY THE KEY IS NOT DELETED RIGHT HERE — NAMED, NOT LEFT UNSAID.
    # `create_angular_dimension` is the ONLY fixture of
    # `tests/test_unproven_is_discharged_only_by_its_own_kind.py`: three
    # checks require its presence in the journal on rollback and on a commit
    # with no witness, a fourth requires its absence on a full chain, a fifth
    # holds `_DISCHARGED_BY_ONE_GREEN_ROW ⊆ UNPROVEN`. Retiring it must travel
    # in ONE move together with replacing the fixture in that file; a move
    # made alone would have knocked down the guard that watches the
    # retirement rule itself. Only the reason is rewritten here — from a
    # promise ("added") to a measurement.
    "create_angular_dimension": Entry(
        CLOSE_BY, "2026-09-03", "2026-10-03",
        "живьём одна полная цепь — 13.08.2026, Revit 2026, 1408 мс; это одно "
        "наблюдение, а не ставка"),
    # THE RECORD WAS REWRITTEN ON 09.08, AND THE OLD ONE HAD BEEN A LIE FOR
    # TEN DAYS. It read "Roslyn gate green 6/6 …, but live Revit has not yet
    # seen this op even once" and had been entered on 29.07 (`d645e102`). The
    # evidence against it is the live-witness corpus, three rows, all green,
    # all on Revit 2026:
    #   2026-07-30T09:04:01.224  638.1 ms  ok=true
    #   2026-07-30T09:04:20.164  513.9 ms  ok=true
    #   2026-08-04T14:48:06.667  445.9 ms  ok=true, execution=committed,
    #                                      witness=satisfied, ACCEPTANCE=accepted
    # That is, it was refuted the VERY NEXT MORNING after being entered, and
    # it lived on until 09.08 — the whole time telling the model "do not rely
    # on this" about the one op of its own wave that had been carried through
    # to independent acceptance.
    #
    # WHAT REMAINED TRUE, AND WHY THE ROW WAS NOT DELETED BUT NARROWED: on
    # 09.08 (`9593e9cc`) this op's witness was rewritten wholesale — instead
    # of a face count it checks, inside the transaction, the entire SURFACE
    # of the built element against a pre-registered pre-image taken before
    # the effect. This witness has never once run live: the last live row is
    # 04.08, five days before it.
    # The old text also lied a second, smaller way: it promised a check of
    # "the number of faces", which no longer exists in the op.
    # 🔴 RETIRED 03.09.2026, AND RETIRED BY A SAMPLE THAT COVERED THE BRANCH,
    # NOT BY ITS COUNT.
    #
    # STEP 1 — THE INSTRUMENT NAMED IN THIS JOURNAL'S HEADER. The
    # `kir_witness.jsonl` corpus (4090 rows that made it through): the op has
    # 68 live rows and 60 full chains, 57 of them AFTER the witness was
    # rewritten on 09.08 — the first on 14.08 21:10 on Revit 2023, the last
    # on 03.09 on 2026. The half saying "the surface witness was never
    # checked live" had been false for twenty days.
    #
    # STEP 2 — AND IT MATTERS MORE THAN THE FIRST: THESE 57 ROWS COULD NOT BE
    # USED TO RETIRE IT. A census of live PROGRAMS (`kir_programs.jsonl`,
    # 2176 rows, 63 occurrences of the op with a mesh) before this move:
    # minimum 4 triangles, median 12, MAXIMUM 12 — 60 of the 63 meshes at
    # exactly 12. That is, every green chain was built on little cubes, and
    # the branch the record was warning about ("start with hundreds of
    # triangles, not thousands") had NEVER ONCE seen a live Revit. This is,
    # word for word, the 19.08 correction on the solids above: green on a
    # sample where the branch is dark is not proof.
    #
    # STEP 3 — THE BRANCH IS COVERED BY A RUN, NOT BY REASONING. Two live
    # UV-spheres in "Проект1" on Revit 2026, a full chain for both (committed
    # · satisfied · accepted), the surface witness green along all three axes:
    #      528 triangles ( 266 vertices) — 03.09 09:39:33, 558.7 ms
    #     3968 triangles (1986 vertices) — 03.09 09:39:47, 987.3 ms
    # The second sits right at the registry's ceiling (`mesh.MAX_TRIANGLES` =
    # 4096), meaning "thousands" was verified not by a mid-range sample but
    # by the EDGE of what is allowed.
    #
    # THE "NOT WITH THOUSANDS" ADVICE HAS BEEN REFUTED AND IS THEREFORE
    # CARRIED NOWHERE. Carrying forward something refuted would introduce a
    # second falsehood — the same argument by which the solids' records were
    # not brought back on 19.08. What remains true is stated by the registry
    # itself: the op's postcondition declares a surface check against the
    # `surface_canon_mm` tolerance, and it travels to the model in
    # `spec(create_directshape)`.
    # TRACE OF THE 09.08 MERGE. The datum wave wrote these records as PLAIN
    # ROWS — its base predated the ratchet — and the text merge produced
    # DUPLICATE keys: `create_angular_dimension` and `create_directshape`
    # arrived both as a dated record and as a plain row. Python keeps the
    # LAST one, meaning the row would have overwritten the dated record, and
    # for `create_directshape` it would also have overwritten the
    # re-measurement (the op was built live 3/3 — the earlier "never once
    # checked" had been a lie for ten days). The duplicates are removed, and
    # the wave's three own records have been brought into the journal's form.
    #
    # wave/datums, 09.08. All three were gathered by live Roslyn on six
    # versions, and none has seen a live Revit. Each one names EXACTLY the
    # property that is offline-unverifiable in principle, not a generic
    # "never checked".
    # 🔴 RE-MEASUREMENT 15.08.2026 BY THE INSTRUMENT NAMED IN THIS JOURNAL'S
    # HEADER (corpus `kir_witness.jsonl`, 1913 rows, a row with nonzero
    # `duration_ms`). All three MADE IT to Revit — meaning the words "never
    # checked live" were stale. But the records CANNOT be retired, and that
    # is the main point:
    #
    #     create_multi_segment_grid   4 rows · committed 4 · ok 0
    #     create_extrusion_roof       4 rows · committed 0 · ok 0
    #     create_multistory_stairs    2 rows · committed 0 · ok 0
    #
    # "Made it to Revit" and "built" are DIFFERENT facts, and the corpus
    # tells them apart. Retiring a row on `duration_ms` alone would mean
    # telling the model the op is verified when it has NEVER ONCE actually
    # gone through — that is, introducing into the model's contract exactly
    # the silently-wrong outcome this whole package is written against. So
    # the debt remains, and the wording becomes MORE PRECISE than before: it
    # now carries a number and distinguishes "never tried" from "tried and
    # failed". The second is stronger than the first, and more useful to the
    # model.
    "create_multi_segment_grid": Entry(
        CLOSE_BY, "2026-08-09", "2026-09-08",
        "ворота 6/6; живьём 4 прогона, транзакция прошла, свидетель зелёным "
        "не был ни разу — совпадение сегментов с заказанными не подтверждено"),
    "create_extrusion_roof": Entry(
        CLOSE_BY, "2026-08-09", "2026-09-08",
        "ворота 6/6; живьём 4 прогона, НИ ОДНОГО коммита: сторону "
        "выдавливания задаёт нормаль, выбранная Revit"),
    "create_multistory_stairs": Entry(
        CLOSE_BY, "2026-08-09", "2026-09-08",
        "ворота 6/6; живьём 2 прогона, НИ ОДНОГО коммита; на Revit до 2025 "
        "отказывает по построению (ISet на net48)"),
    # THE BODY WAVE, 09.08 — AND HERE IS EXACTLY THE MERGE TRAP THE RATCHET
    # WAS BUILT FOR. Its base predates `record_ratchet`, so it wrote these
    # records as PLAIN ROWS and, on top of that, keyed THREE ops under one
    # row, including `create_directshape`. Merging the text would have
    # produced a duplicate key, Python would have kept the LAST one — and the
    # plain row "never once checked live" would have overwritten the
    # RE-MEASUREMENT above: the op was built live 3/3 (30.07 twice, 04.08
    # with independent acceptance), and the earlier "not once" had been a lie
    # for ten days. So the shared reason stayed shared only for the TWO NEW
    # ops, while the mesh got its own dated, narrowed record.
    #
    # What the two bodies have in common, and why it is one row for both:
    # the Roslyn gate is green 6/6 in both isolations, live Revit has not
    # seen either one, and offline the same thing is unverifiable — with what
    # precision Revit computes from what was built (`Solid.Volume` per
    # RevitAPI.xml "may be slightly under/overestimated if curved surfaces
    # are present", and the size of this "slightly" is documented nowhere).
    # The witnesses are written against a LOUD discrepancy, and the receipt
    # carries the raw expectation/measurement pair: the first live run will
    # not estimate the residual, it will MEASURE it.
    # 🔴 BOTH RETIRED 15.08.2026 — THE JOURNAL SHRANK, AS PROMISED IN THE
    # HEADER.
    #
    # Re-measured by the instrument named in the header (corpus
    # `kir_witness.jsonl`, 1913 rows):
    #
    #     create_solid_extrusion   7 rows · committed 7 · ok 7
    #     create_solid_revolve     7 rows · committed 4 · ok 4
    #
    # Both did not just make it to Revit, they WERE BUILT with a green
    # witness — exactly what the retired wording demanded: "never once
    # checked live; the volume witness is written against a LOUD
    # discrepancy". The first live run, which was supposed to MEASURE the
    # residual `Solid.Volume`, took place and produced no discrepancy.
    #
    # The records are retired, not rewritten: the debt is closed, not
    # refined. This is the first shrinkage of this journal since 10.08, and
    # it was retired by a MEASUREMENT, not a decision. `_SOLID_UNPROVEN` was
    # removed along with them — a constant shared by two, left with no reader
    # at all, is the same stale record, just in a different currency.
    # wave/mass, 10.08. The signature and BOTH pre-flight checks were
    # measured by compilation 6/6, live Revit has never once seen this op.
    # Named is exactly what is offline-unverifiable: whether the built wall
    # fully covers the named face — none of the six RevitAPI.xml files say a
    # word about this, so equality of areas is NOT asserted, and the receipt
    # carries the raw pair.
    "create_face_wall": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "площадь стены и площадь грани не сверяются — только пара в квитанции"),
    # wave/wall-foundation, 09.08. The list grows by FACT, not by assumption
    # (see the rule above): the call signature was measured by compilation on
    # all six versions, but live Revit has never once seen this op, and two
    # things are offline-unverifiable in principle — which walls Revit even
    # agrees to underpin at all (there is NO pre-flight
    # `WallAllowsWallFoundation` in the API) and where the footing lands
    # relative to the wall. The wording is DELIBERATELY terse: the
    # description budget was exhausted (24 characters remained on HEAD), and
    # room for this row was freed by rewriting the `ref` idiom above, not by
    # raising the ceiling.
    # RE-CHECKED AGAINST THE CORPUS 09.08: ZERO rows. The record stands.
    "create_wall_foundation": Entry(
        CLOSE_BY, "2026-08-09", "2026-09-08",
        "геометрия не сторожится — свес подошвы не замерен"),
    # wave/framing, 09.08. Both signatures were measured by compilation 6/6,
    # live Revit has seen neither. Named is exactly what is
    # offline-unverifiable.
    #
    # THE SECTION HEADER ITSELF IS "NEVER CHECKED LIVE" (see
    # build_tool_description — "DO NOT RELY WITHOUT CHECKING"), so four
    # records were repeating it in their own words on EVERY request. The
    # framing wave freed room for its own two rows by removing this repeat
    # from its neighbors, rather than raising the ceiling (the same move as
    # the strip-foundation wave with the `ref` idiom); not a single fact was
    # lost in the process — `create_dimension` KEEPS its own caveat, because
    # it is about a partial check, not about its absence.
    # RE-CHECKED AGAINST THE CORPUS 09.08: ZERO rows for both. The records
    # stand.
    "create_beam_system": Entry(
        CLOSE_BY, "2026-08-09", "2026-09-08",
        "число и шаг балок выбирает Revit"),
    "create_truss": Entry(
        CLOSE_BY, "2026-08-09", "2026-09-08",
        "форму фермы задаёт её семейство"),
    # wave/reinforcement, 10.08. The signature was measured by compilation
    # 6/6, live Revit has never once seen it. Named is exactly what is
    # offline-unverifiable in principle: whether the bars appear is decided
    # by a DOCUMENT SETTING, not the program.
    "create_area_reinforcement": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "стержни появятся лишь при HostStructuralRebar"),
    # ═══ THE JOURNAL'S GAP CLOSED BY A MEASUREMENT, NOT A PROMISE (10.08.2026) ═══
    #
    # `_UNPROVEN_GAP` entered a row on 09.08 saying that the journal holds
    # the shape of rows that DO EXIST, and says nothing about the ones that
    # DO NOT. That day's measurement: 16 ops with zero live rows, four named.
    # The reason they were not entered right away was named honestly and was
    # true — the description had under a thousand characters left, and twelve
    # rows did not fit.
    #
    # AFTER THE SURFACE WAS SLICED INTO SECTIONS, THIS REASON FELL AWAY: the
    # reason travels into the op's docstring (`spec(<op>)`), while only the
    # NAME remains in the permanently loaded text. Re-measurement on 10.08 on
    # the reconciled tree, against the same corpus (`kir_witness.jsonl`, rows
    # with nonzero `duration_ms`): 63 writing ops, 26 with zero live rows, 11
    # had been named. Below are the fifteen remaining.
    #
    # Each row names what is offline-unverifiable SPECIFICALLY FOR IT. A
    # generic "gate 6/6, never checked live" would here be worse than
    # silence: it looks like a measurement while conveying only what is
    # already known about the whole list. The corpus ends at 04.08 18:09 —
    # anything that arrived on 09–10.08 physically could not have gotten
    # into it.
    "create_area_load": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "прилипнет ли нагрузка к заданному контуру — решает Revit"),
    "create_line_load": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "прилипнет ли нагрузка к заданной линии — решает Revit"),
    "create_point_load": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "прилипнет ли нагрузка к заданной точке — решает Revit"),
    "create_building_pad": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "вырез площадки в рельефе считает Revit, а не программа"),
    "create_site_subregion": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "подобласть делит поверхность родителя средствами Revit"),
    "create_topography": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "триангуляцию по точкам строит Revit — форма непредсказуема офлайн"),
    "create_conduit": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "торговый размер короба задаёт таблица документа, не оп"),
    "create_flex_duct": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "гибкую форму между узлами выбирает Revit; свидетель сверяет весь путь"),
    "create_flex_pipe": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "гибкую форму между узлами выбирает Revit; свидетель сверяет весь путь"),
    # 🔴 "NOT MEASURED" BECAME MEASURED ON 03.09.2026, AND THE ANSWER IS NO.
    # The live matrix (`scripts/kir_live_matrix.py --set gap`) was run in
    # "Проект1" on Revit 2026; the corpus for both placeholders at 09:42:
    #     create_duct_placeholder   7 rows · committed 6 · full chains 0
    #     create_pipe_placeholder   8 rows · committed 7 · full chains 0
    # EVERY one of the thirteen commits has a GREEN witness, and independent
    # acceptance REJECTS it (KIR-A006) — thirteen out of thirteen, from 13.08
    # to 03.09, without a single exception across two different documents.
    #
    # THIS IS A THIRD STATE, AND IT MUST NOT BE CONFUSED WITH EITHER
    # NEIGHBOR. Not "blind acceptance" (KIR-A007 — the census declares itself
    # NOT a judge, in which case the op goes to
    # `BUILT_BUT_ACCEPTANCE_BLIND`): here the census sees and hands down a
    # verdict. And not "under construction": the verdict is REJECTED.
    # Membership in the blind list would be a lie in a third direction, so
    # the records stay here, and the reason turns from "not measured" into a
    # number.
    # 🔴🔴 THE CAUSE OF THESE THIRTEEN WAS FOUND AND FIXED THE SAME DAY, AN
    # HOUR AFTER THE RECORD WAS WRITTEN (03.09.2026, commit `bc3a172`).
    # Neither Revit nor the op was doing the rejecting: `OP_RESULT_CATEGORIES`
    # named the ORDINARY category for the placeholders
    # (`OST_PipeCurves`/`OST_DuctCurves`), relying on the tree's confident and
    # WRONG claim that "Revit does not give a placeholder its own category".
    # It does: a live measurement gives `OST_PlaceHolderPipes` and
    # `OST_PlaceHolderDucts`. The census was looking for the addition in the
    # wrong place and honestly found zero — thirteen times in a row.
    #
    # LIVE COUNT UNDER BOTH MAPS at the placeholder level: old 0, new 1.
    #
    # THE RECORDS STILL STAND, AND THIS IS NOT CAUTION BUT THIS FILE'S LAW:
    # ONLY a full green chain retires a record, and there is not one yet. The
    # product service came up at 05:51 and is holding the OLD module (an
    # editable install), so `/admin/kir/run` will keep rejecting until the
    # worker restarts. The first run after the restart is what closes these
    # two records.
    #
    # 🔴 AND SEPARATELY — ABOUT THE DEADLINE. A record written at 09:42 and
    # refuted at 10:40 is exactly the kind of defect this file's records have
    # a RESPONSE DAY for: `create_dimension` told the model "the op does not
    # work" for a week and a half after the fix. Here the gap is under an
    # hour only because both pieces of work happened in the same shift.
    "create_duct_placeholder": Entry(
        CLOSE_BY, "2026-09-03", "2026-10-03",
        "приёмка ОТВЕРГАЛА каждый раз (KIR-A006): 6 коммитов, 0 полных цепей "
        "— 13.08…03.09. ПРИЧИНА НАЙДЕНА 03.09 и починена (`bc3a172`): перепись "
        "искала прибавку в OST_DuctCurves, элемент ложится в "
        "OST_PlaceHolderDucts. Ждёт зелёной цепи после перезапуска воркера"),
    "create_pipe_placeholder": Entry(
        CLOSE_BY, "2026-09-03", "2026-10-03",
        "приёмка ОТВЕРГАЛА каждый раз (KIR-A006): 7 коммитов, 0 полных цепей "
        "— 13.08…03.09. ПРИЧИНА НАЙДЕНА 03.09 и починена (`bc3a172`): перепись "
        "искала прибавку в OST_PipeCurves, элемент ложится в "
        "OST_PlaceHolderPipes. Ждёт зелёной цепи после перезапуска воркера"),
    "create_path_of_travel": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "маршрут прокладывает решатель Revit — длина и трасса от нас не зависят"),
    "create_filled_region": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "нужен прогон НА РАЗРЕЗЕ: на плане прошла бы и прежняя, неверная петля"),
    "create_wall_sweep": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "положение профиля Autodesk документирует как свойство ТИПА, не вызова"),
    "create_slab_edge": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "по каким кромкам хозяина пойдёт профиль, офлайн не узнать"),
    # wave/stairs-landing, 10.08. The signature, both witnesses, and the
    # single-argument `StairsEditScope.Start` were measured by compilation
    # 6/6; live Revit has never once seen the op. Hidden rounding is no
    # longer a guess: only elevations already a multiple of the riser are
    # allowed, and the post-scope witness is strict.
    # Re-measurement 15.08.2026: 1 live row, committed 1, ok 1 — "needs a
    # FIRST live run" has been fulfilled, and the wording became stale. The
    # debt is not retired: one run closes the question "does it run at all",
    # not "is it repeatable".
    "create_stairs_landing": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "живьём 1 прогон, зелёный; повторяемость scope и post-scope чтения "
        "контура на одном наблюдении не устанавливается"),
    # THE SECOND FLIGHT (15.08.2026). Assembled, gate 6/6, the golden is
    # compared — and it has NEVER ONCE BEEN CHECKED LIVE. The reason is
    # NAMED and it is not forgetfulness: on 15.08 `create_stairs`, on the
    # owner's real house, committed and blocked the Revit thread with a
    # MODAL WINDOW that nobody was there to click; the owner dismissed the
    # window by hand. The stairs incident, considered closed, is open for
    # this path, and a live run is forbidden by the owner's decision until it
    # is investigated.
    "create_stairs_run": Entry(
        CLOSE_BY, "2026-08-15", "2026-09-14",
        "живьём НЕ проверялся ни разу: живые прогоны лестничного пути "
        "остановлены после модального окна 15.08, заблокировавшего поток "
        "Ревита; ворота 6/6 и голден доказывают КОМПИЛЯЦИЮ, а не постройку"),
    # ═══ 24.08.2026: FOUR OPS THE MODEL WAS READING AS VERIFIED ═══
    #
    # Measured by the very instrument this file names itself
    # (`witness_corpus.proven_ops` — a FULL CHAIN: commit AND witness AND
    # acceptance), against a corpus of 3712 rows: registry of 82 ops, 57
    # proven, 29 named here, and NOT PROVEN AND NOT NAMED — 11. The eleven
    # split into two kinds, and they are treated DIFFERENTLY:
    #   · four NEVER ONCE BUILT — they are below;
    #   · seven ARE BUILT AND COMMITTED, but ACCEPTANCE is blind to them:
    #     join_elements 1363 commits, create_wall_type 91, create_floor_plan
    #     48, create_solid_blend 12, create_surface 8, author_family 8,
    #     create_solid_sweep 4. Calling them unproven would be a lie in the
    #     other direction, and a more expensive one: see `_UNPROVEN_GAP`.
    #
    # For all four, Revit's refusal is HONEST, typed, and names the next
    # move (KIR-X009 with detail). The defect is not in the ops, it is that
    # BEFORE the run the model did not know this and spent a turn on them.
    "create_adaptive_component": Entry(
        CLOSE_BY, "2026-08-24", "2026-09-23",
        "живьём НЕ построен: прогон 24.08 откатился — «типоразмер не "
        "адаптивный, нет точек размещения». Закроет load_family с "
        "АДАПТИВНЫМ семейством: в корпусе 280 332 экз. Adaptive нет"),
    "transfer_family": Entry(
        CLOSE_BY, "2026-08-24", "2026-09-23",
        "живьём НЕ построен: оба прогона 23.08 откатились — исходный "
        "документ не открыт в ТОЙ ЖЕ сессии. Перенос документ-в-документ: "
        "оба обязаны быть открыты РЯДОМ"),
    "transfer_material": Entry(
        CLOSE_BY, "2026-08-24", "2026-09-23",
        "живьём НЕ построен: прогон 24.08 откатился по причине "
        "transfer_family — исходный документ не открыт рядом"),
    # `query_surface` STOOD HERE FOR A FEW HOURS AND WAS RETIRED BY A
    # MEASUREMENT, NOT AN OPINION. Entered on 24.08 from the corpus ("zero
    # rows"), retired the same evening by the first live call in the
    # project's history: "Проект1", Revit 2026, face 1, the surface reads
    # back degree 3x3 / count 4x4 — exactly as declared, 9 samples, 487 ms, a
    # full chain. The record's kind was the first one ("has not seen live
    # Revit"), and that kind is retired by exactly one green row.
}

#: THIS JOURNAL'S GAP, NAMED OUT LOUD (re-measurement 10.08.2026).
#:
#: THE PREVIOUS RECORD WAS RETIRED BY A MEASUREMENT, NOT AN OPINION. Since
#: 09.08 this read "16 of the registry's 57 ops have no live rows, 4 are
#: named in UNPROVEN, the model reads twelve as verified." Re-measured on
#: 10.08 by the VERY SAME instrument the record names itself (set(spec.OPS)
#: against the op names in rows with nonzero duration_ms): the registry has
#: 68 ops, 64 writing; 37 have live rows, 27 do not — and ALL 27 are named in
#: UNPROVEN. The twelve listed by name were entered by that same day's
#: waves. The gap no longer exists; the record about it outlived its own
#: truth by a day — the second such case in this file, see the header.
#:
#: WHAT REMAINS IN ITS PLACE. The journal tells apart exactly two states: a
#: row exists / a row does not. But "exists" comes in different thicknesses,
#: and on that axis the journal is silent: eight writing ops have 1, 1, 1, 1,
#: 2, 2, 2, 2 live rows against 81 for create_wall, 375 for create_pipe, and
#: 411 for place_family. The model reads them as equally verified. This is
#: not silence but a THRESHOLD, and it is entered as a row with its own
#: deadline, rather than left to memory.
_UNPROVEN_GAP: dict[str, Entry] = {
    "живая_строка_не_значит_замер": Entry(
        CLOSE_BY, "2026-08-10", "2026-09-09",
        "перемер 10.08: 68 опов реестра, 64 пишущих; живые строки есть у 37, "
        "у 27 нет — и все 27 названы в UNPROVEN, молчащих больше нет. "
        "С create_space (10.08) знаменатель 69/65, непроверенных 28, назван "
        "и он — корпус НЕ перезапускался, у нового опа живых строк нет по "
        "построению (корпус закрыт 04.08). Осталось "
        "другое: журнал различает только «есть строка / нет строки», а у "
        "восьми опов она одна-две — create_floor_by_contour, create_foundation, "
        "create_grid, set_param по 1; create_ceiling, create_opening, "
        "create_room_separator, create_tag по 2 — против 81 у create_wall и "
        "411 у place_family. Закрывается порогом в грамматике журнала, не "
        "молчанием. С 11.08 у той же оси есть ВТОРАЯ половина, и она "
        "острее: журнал ключуется ОПОМ, а у опа бывают ВЕТКИ. У "
        "place_family 411 живых строк, но оба рода размещения, "
        "заведённые 11.08 (WorkPlaneBased, TwoLevelsBased), живого "
        "Revit не видели ни разу — и по имени опа это неотличимо от "
        "проверенного. Пометить place_family непроверенным было бы "
        "ложью в другую сторону: точечная ветка проверена 411 раз"),
    "построено_но_приёмка_слепа": Entry(
        CLOSE_BY, "2026-08-24", "2026-09-23",
        "замер 24.08 по корпусу 3712 строк: у семи опов есть КОММИТЫ и "
        "удовлетворённый свидетель, но приёмка не заключила НИ РАЗУ — "
        "join_elements 1363, create_wall_type 91, create_floor_plan 48, "
        "create_solid_blend 12, create_surface 8, author_family 8, "
        "create_solid_sweep 4. По закону proven_ops (полная цепь) они "
        "«не доказаны», в UNPROVEN их нет, и модель читает их проверенными. "
        "Ни то ни другое не верно: верное утверждение — «строится; "
        "независимая перепись слепа к нему ПО ПОСТРОЕНИЮ», и с 24.08 оно "
        "приходит модели в момент отказа (KIR-A007, поимённо и с причиной). "
        "Здесь остаётся ДО прогона: третьего состояния у журнала нет"),
    # 🔴 A BRANCH THAT USED TO BUILD AND STOPPED — THE FIRST SUCH CASE HERE
    # (03.09.2026). This journal's previous two records speak of a branch
    # that HAS NOT SEEN live Revit (`place_family`), and of blind acceptance.
    # This one is about a third thing: the branch DID BUILD live and is
    # rolling back today, and by the op's name alone this is indistinguishable
    # from anything else.
    #
    # Measurement: the live-matrix row `create_opening:host_face` was entered
    # on 04.08 (b850ec39) and gave a full chain that same day — 04.08
    # 14:48:02, committed · satisfied · accepted, the same three ops
    # (create_level + create_floor + create_opening). On 03.09 the same trio
    # rolled back THREE TIMES in a row (06:09:57, 08:53:26, 09:20:23), each
    # time KIR-X004 "postconditions violated", acceptance never started. A
    # neighboring branch of the same op (`variety=wall_rect`) was accepted in
    # those very minutes: 6 full chains out of 7 rows, the last on 03.09
    # 09:20:18 — five seconds before the host_face rollback.
    #
    # WHY IT IS NOT IN `UNPROVEN`. The key there is the op's NAME, and
    # `create_opening` is proven live: 13 rows, 9 commits, 8 full chains.
    # Calling it unproven would be a lie in the other direction — exactly
    # the one this journal was built against. The debt belongs to the
    # BRANCH, and today it can only be expressed here.
    "ветка_строилась_и_перестала": Entry(
        CLOSE_BY, "2026-09-03", "2026-10-03",
        "замер 03.09: create_opening variety=host_face дал полную цепь 04.08 "
        "и откатился 3 из 3 прогонов 03.09 (KIR-X004, постусловия нарушены), "
        "тогда как variety=wall_rect принят в те же минуты. Журнал ключуется "
        "ИМЕНЕМ опа и читает create_opening проверенным (8 полных цепей из 13 "
        "строк) — состояния «одна ветка уехала» у него нет, и модель узнаёт "
        "об этом только отказом"),
}

#: OPS THAT BUILD AND COMMIT, WHILE INDEPENDENT ACCEPTANCE IS BLIND TO THEM.
#:
#: 🔴 THE DECISION MUST BE A VALUE, NOT PROSE (24.08.2026). The kind is
#: named by the row `built_but_acceptance_blind` in `_UNPROVEN_GAP` above —
#: but an instrument cannot read prose, and `tools/unproven_completeness.py`
#: was counting these seven ops as SILENT, that is, demanding a decision
#: that had already been made. Exactly the same kind of defect as the
#: finding itself: a value declared in one place and read in another.
#:
#: WHAT MEMBERSHIP MEANS. The op HAS BUILT live and COMMITTED, but has not a
#: single full chain (commit AND witness AND acceptance), because
#: independent census is blind to it. Naming it in `UNPROVEN` would be a lie
#: in the other direction — `create_wall_type` has built 91 times.
#:
#: WHAT THIS IS NOT. Not a pardon and not a release: the reason for the
#: blindness for EACH op reaches the model at the moment of refusal
#: (`KIR-A007`, with the op's name and the reason) since 24.08. Here there is
#: only the fact that the decision has been MADE and the op is not
#: forgotten. The review deadline for the kind sits on the journal record,
#: not here.
#:
#: A NEW OP IN THIS STATE WILL NOT LAND HERE ON ITS OWN — the instrument
#: will print it as "no decision". That is exactly the point of this list:
#: it is closed and NOT COMPLETE.
BUILT_BUT_ACCEPTANCE_BLIND: frozenset = frozenset({
    "join_elements",        # 1363 commits
    "create_wall_type",     # 91
    "create_floor_plan",    # 48
    "author_family",        # 8
})
#: 🔴 THREE LEFT THIS LIST IN ONE EVENING, AND LEFT BY A MEASUREMENT.
#: `create_solid_blend`, `create_solid_sweep`, `create_surface` landed here
#: from the corpus: 12/12, 4/4 and 8/8 commits, and NOT ONE full chain. A
#: live window on 24.08 in an EMPTY "Проект1" gave all three
#: `committed · satisfied · ACCEPTED` on the first move.
#:
#: So the blindness was ENVIRONMENTAL, not "by construction": in a populated
#: document the census could not conclude, in an empty one it could.
#: Membership here means "by construction", and keeping them here would mean
#: declaring the instrument's boundary to be something that turned out to be
#: a property of the DOCUMENT. What found the difference was not reading the
#: corpus, but one live move: the corpus said "zero full chains" identically
#: in both cases.


def _live_proven_ops() -> frozenset:
    """Ops that BUILT live at least once, or EMPTY as an instrument refusal.

    🔴 AN EMPTY SET HERE MEANS "THERE IS NOTHING TO ASK", NOT "NOTHING HAS
    BEEN PROVEN". The difference carries weight: the corpus sits under mode
    600 owned by the service user, and listing the catalog without
    permission gives an EMPTY list, not an error — an honesty instrument
    would quietly answer "no evidence" where the truth is "I cannot see".
    So a consumer must read emptiness as an instrument refusal and print the
    whole journal, rather than treat it as closed.

    🔴 THE PREDICATE WAS FIXED ON 17.08.2026, AND THE BUG WAS MINE, A DAY
    OLD. The first version treated a row with nonzero `duration_ms` as proof
    — that is, "the program MADE IT to Revit". The journal it edits tells
    apart making it and building, in plain text, in its own comments, and
    the re-measurement confirmed this: of 65 ops that made it, FOUR never
    once committed (`create_extrusion_roof`, `create_face_wall`,
    `create_multistory_stairs`, `create_slab_edge`). The journal carried the
    exact reason for all four — and the rendering was TAKING it away from the
    model, introducing a silently-wrong outcome via an honesty instrument.

    The definition is now ONE for the whole tree and lives in
    `witness_corpus.proven_ops` — a FULL CHAIN (commit AND witness AND
    acceptance). A commit is not enough: seven journal records doubt
    specifically the WITNESS ("the transaction went through, the witness was
    never once green"), and a transaction going through does not refute
    them. The justification with the list of names is in the `proven_ops`
    docstring.
    """
    from kir import witness_corpus

    return witness_corpus.proven_ops()


#: RECORDS THAT ARE RETIRED BY ONE GREEN CORPUS ROW. A closed list, and its
#: KIND is declared here, because the kind determines what the key's absence
#: means: **CLOSED, BUT NOT COMPLETE — the key's absence means "DO NOT
#: RETIRE"**, not "we looked and decided there is nothing to retire".
#:
#: 🔴 WHY IT WAS ENTERED ON 17.08.2026, AND THIS IS A RETRACTION OF MY OWN
#: FIX FROM THE DAY BEFORE. The day before, the rendering learned to
#: subtract from the journal everything for which the corpus found a live
#: trace, and I reported that the journal had gone stale on 24 records.
#: Re-reading the RECORDS THEMSELVES (not their count) showed something
#: else: the journal is not a list of "the op has not seen live Revit". It
#: is a list of TYPED WARNINGS, and it holds at least four kinds, of which a
#: green row retires exactly ONE:
#:
#:   1. "has not seen live Revit" — retired by one full chain. THIS LIST;
#:   2. a warning about SEMANTICS ("Revit builds the triangulation from the
#:      points", "the document's schedule sets the duct's trade size") — a
#:      green build confirms it, it does not refute it;
#:   3. a debt about a BRANCH of the op ("walls live; families and grids not
#:      checked") — the corpus is keyed by the op's NAME and cannot in
#:      PRINCIPLE refute such a record. This hole is named in
#:      `_UNPROVEN_GAP` since 11.08;
#:   4. a debt about REPEATABILITY ("one green run is not a rate") —
#:      retired by a count of observations, not by the fact of existence.
#:
#: Of the 13 records the corpus "refuted", ONE belongs to kind 1. So
#: yesterday's fix would have taken twelve correct warnings away from the
#: model, and the reported figure of 24 is RETRACTED: the journal was almost
#: entirely right, I was the one who was wrong.
#:
#: The default was chosen by the asymmetry of cost: an extra record costs
#: the model turns, one retired on weak evidence costs a silently wrong
#: building.
_DISCHARGED_BY_ONE_GREEN_ROW: frozenset = frozenset({
    "create_angular_dimension",   # the reason in full: "added on 09.08"
})


def _unproven_minus_live_corpus() -> frozenset:
    """The journal MINUS what the corpus ACTUALLY refutes.

    What is subtracted is not "everything for which a trace was found", but
    the intersection of three conditions: the key is declared retirable by
    one green row (`_DISCHARGED_BY_ONE_GREEN_ROW`), the corpus was read, and
    it contains a FULL CHAIN for this op. Why each of the three is necessary
    — in the comment above the list and in `witness_corpus.proven_ops`.

    Without the corpus — the whole journal: an instrument refusal is not
    proof.
    """
    live = _live_proven_ops()
    if not live:
        return frozenset(UNPROVEN)
    discharged = live & _DISCHARGED_BY_ONE_GREEN_ROW
    return frozenset(n for n in UNPROVEN if n not in discharged)


#: THE JOURNAL. A consumer takes the reason as ONE piece of text via `.reason`.
UNPROVEN = Ledger(
    "tool_doc.UNPROVEN", _UNPROVEN_ENTRIES, min_reason=12,
    instrument=(
        "корпус живых свидетелей data/telemetry/kir_witness.jsonl "
        "(машинно-локальный): строка с ненулевым duration_ms по этому опу "
        "опровергает запись; tools/live_op_rates.py --corpus <путь>. "
        "КОРПУС ПОД РЕЖИМОМ 600 У ПОЛЬЗОВАТЕЛЯ СЛУЖБЫ: читать через sudo "
        "или сказать, что не смог, но НИКОГДА не сообщать ноль. Без прав "
        "перечисление каталога даёт ПУСТОЙ список, а не ошибку, и прибор "
        "честности тихо отвечает «улик нет» там, где правда «не вижу»"))

UNPROVEN_GAP = Ledger(
    "tool_doc.UNPROVEN_GAP", _UNPROVEN_GAP,
    instrument=(
        "тот же корпус: сверить set(spec.OPS) против имён опов в строках с "
        "ненулевым duration_ms — разность и есть непроверенные живьём опы"))

#: TRAPS OF A SINGLE OP — THE SAME KNOWLEDGE AT A ONE-TIME PRICE (09.08.2026).
#:
#: There is one selection rule and it is about the QUESTION, not the
#: length: `NOTES` answers what the model asks BEFORE choosing an
#: operation ("what do I build the shell with?", "how do I repeat the
#: panel?"), and is paid for on EVERY turn. Everything needed AFTER the op
#: has already been chosen — the shape of its arguments, its own
#: prohibitions, its envelope requirements — is paid for exactly on the turn
#: it is asked, because it arrives as the op's docstring (`dsl._docstring`,
#: also known as `spec(<оп>)`, also known as `print(<оп>.__doc__)`).
#:
#: THE PATTERN IS BORROWED, NOT INVENTED: this is exactly how the reason
#: "do not rely without checking" moved on 09.08 — the list of names stayed
#: in the description (needed BEFORE the choice), the reason moved into the
#: docstring (needed AFTER). This is the second half of the same move.
#:
#: WHAT DID NOT LAND HERE, AND WHY — this matters more than what did,
#: because the mechanical rule "names one op -> push it out" would have
#: lost knowledge:
#:   * "An existing element cannot be selected by description — only by id
#:     from `query_list`" names one op, but is NOT a trap of that op: its
#:     subject is addressing ANY existing element, and it is needed before
#:     the choice, not after. It stayed in `NOTES`;
#:   * "A repeating thing is assembled via `create_group(members,
#:     placements)`" also names one op and also stays: it is the answer to
#:     "how do I repeat", that is, the choice of operation, not its inner
#:     workings. Only the group's INNER WORKINGS moved out — member
#:     coordinates, the shape of `placements`, the `by: ref` RULE inside it
#:     (a backward reference is legal, forward and outward — a refusal).
OP_NOTES: dict[str, tuple[str, ...]] = {
    # The group's inner workings: how members are specified and HOW `by:
    # ref` works inside it. All of this is read once `create_group` has
    # ALREADY been chosen — the choice is made by the neighboring trap, left
    # in NOTES.
    #
    # 🔴 THIS NOTE WAS LYING TO THE MODEL, AND THE LIE WAS FOUND BY AN
    # EXTERNAL AUDIT ON 16.08.2026. The earlier version said "`by: ref`
    # inside a group does not work — a member cannot see its sibling ops".
    # The law says the opposite: `authoring_validation`, the
    # `p.kind == "member_ops"` branch, refuses ONLY an OUTWARD reference and
    # a FORWARD reference, while `seen_ids` is exactly "members declared
    # above", so a backward reference goes through. Measured by execution,
    # both poles: a wall→door group with `host: {by: ref}` gives `ok=True`
    # and emits the door on member `{oid}__m__W1`; the same pair in reverse
    # order — KIR-T001.
    #
    # THE COST OF THE LIE IS NOT COSMETIC, AND IT IS MEASURED RIGHT NEXT TO
    # THE LAW ITSELF (`authoring_validation`, 12.08.2026): a door addresses
    # its wall ONLY via `ref`, so the ban made a floor with walls AND doors
    # ungroupable BY CONSTRUCTION — while **41.1% of the elements of a real
    # tower live inside groups** (walls 94.9%, bearing columns 100%,
    # curtain-wall panels 99.3%, doors 91.4%). The remaining form was
    # enumeration, running into a ceiling of 300 against a real floor's
    # median of 796 ops. That is, the text was switching off the model's
    # main mechanism for structural compression of the building.
    #
    # WHY THE GUARD DID NOT CATCH THIS: `test_tool_doc` checked that the note
    # WAS PRESENT and not duplicated — that is, it would go red if the lie
    # were deleted, and could not go red from the lie itself. Closed
    # behaviorally: `create_group` has been entered into `_RULES` of the
    # `test_crossfield_rules_are_declared` ratchet, and a coverage CENSUS now
    # sits there too — a note asserting a ban must be either verified by a
    # run, or NAMED as unsupervised prose.
    "create_group": (
        "`create_group` собирает нативную группу Revit: члены задаются один "
        "раз в абсолютных координатах, `placements` — смещения остальных "
        "вхождений. Селекторы у членов обычные (by name / element_id), как в "
        "любом опе. `by: ref` внутри группы РАБОТАЕТ и адресует СОСЕДА ПО "
        "ГРУППЕ, объявленного ВЫШЕ: так дверь ссылается на свою стену, и "
        "только поэтому этаж со стенами и дверьми вообще группируется. Ссылка "
        "ВПЕРЁД (на члена, объявленного ниже) и ссылка НАРУЖУ группы — "
        "типизированный отказ. СЛЕДУЮЩИЙ ХОД: переставь адресуемого члена ВЫШЕ "
        "по списку `members`, а элемент вне группы адресуй через "
        "`element_id`.",),
    # The tail of the fill trap (the detailing wave, 09.08): both the
    # `at_grid` ban and the type choice are read once the op is ALREADY
    # chosen. The first is about a slot, the second about an argument;
    # neither helps decide whether a fill is needed at all.
    "create_filled_region": (
        "Адрес от осей (`at_grid`) внутри `contour` — типизированный отказ: "
        "ось живёт в модели, а контур заливки — в пространстве вида. Тип "
        "спрашивай `query_types(pool=\'filled_region_types\')`: умолчание "
        "документа существует, но выбирать им штриховку — то же, что "
        "жребием.",),
    # An envelope requirement. The question "is delete needed" is decided
    # without this row; the row is needed exactly by whoever has already
    # written delete.
    "delete": (
        "`delete` требует `allow_destructive: true` в конверте программы.",),
    # THE SECOND HALF OF THE NETWORK TRAP. The first ("a network is one op
    # for the whole run") stayed in NOTES: it is a CHOICE between a single
    # `create_pipe_system` and a scatter of `create_pipe`. The fitting
    # family requirement is read inside the op itself, when a turn is being
    # drawn — and it is about the TYPE, that is, about an argument.
    "create_pipe_system": (
        "Поворот трассы требует, чтобы у типа было семейство отвода, иначе "
        "отказ назовёт угол и диаметры.",),
    # The inner workings of the reinforcement: three facts that cannot be
    # derived from the schema, and all three are read once the op is
    # ALREADY chosen. The permanently loaded description does not pay for
    # them — they arrive only in `spec("create_area_reinforcement")`.
    "create_area_reinforcement": (
        "`hook_type` ПРОПУЩЕН = БЕЗ КРЮКОВ (значение самого Revit API), а не "
        "«возьми единственный из пула» — назови его явно, если анкеровка "
        "нужна. Носитель обязан быть перекрытием/плитой и нести армирование "
        "(несущий, бетон), иначе типизированный отказ назовёт починку. "
        "Стержни Revit создаёт только при включённой настройке документа "
        "HostStructuralRebar; их число и настройка едут в квитанции.",),
    # ═══════════════════════════════════════════════════════════════════════
    # CROSS-FIELD RULES (13.08.2026, audit of the language's axis). EVERY
    # RECORD HAS A PROVENANCE — THE REFUSAL SITE AND ITS CODE, and it is not
    # decoration:
    #
    # the registry declares the obligatoriness of ONE field
    # (`ParamSpec.required`) and cannot say "xyz OR p0_mm/p1_mm". Rules like
    # this live in hand-written branches of
    # `compiler._parse_and_check_internal` — and before this fix reached the
    # author through NOT A SINGLE channel: not the schema (`place_family` has
    # `required: ['op']`), not the tool description (the word `xyz` appears
    # zero times), not `spec(op)` (it printed all 14 parameters as
    # "optional", that is, it asserted the OPPOSITE of the rule). The author
    # learned of them only by refusal, a round trip for each.
    #
    # THE PROSE HERE IS A SECOND COPY OF THE RULE, AND THAT IS ACCEPTED
    # DELIBERATELY, while the registry has no field for it (an owner-level
    # decision). The price for the second copy is a ratchet, not a promise:
    # `tests/test_crossfield_rules_are_declared.py` requires that EVERY rule
    # here REFUSE with the named code on a violating program AND PASS a
    # legal one. A mismatch between the prose and the code fails the test,
    # rather than living for a week.
    #
    # WHAT IS NOT HERE. `create_opening`: measured on 13.08 — a program with
    # `variety="host_face"` and NO shape at all PASSES the plan, there is no
    # refusal at this stage. The `outline`/`contour` rule did not fire on
    # it, and writing prose about it would be a note from memory, not an
    # excerpt from the code.
    # ═══════════════════════════════════════════════════════════════════════
    # compiler.py:1186/1178 (KIR-P007) + compiler.py:1207/1212 (KIR-P005).
    # The only op in the registry for which not a single one of its 14
    # parameters is declared required (measured: 1 of 69).
    "place_family": (
        "ПОЛОЖЕНИЕ ЗАДАЁТСЯ РОВНО ОДНИМ ИЗ ДВУХ СПОСОБОВ, и от выбора зависит, "
        "что ещё обязательно: точка `xyz` — тогда нужен `level` (вызов Revit "
        "принимает уровень); кривая `p0_mm`+`p1_mm` — тогда нужен `host` "
        "(Revit ставит такое семейство по ссылке на грань хозяина и уровня не "
        "принимает вовсе). Ни одного из двух — отказ «не задано положение»; "
        "оба сразу — отказ «вместе они неоднозначны».",),
    # compiler.py:1060/1071 (KIR-P007). The pair `outline` (polyline) and
    # `contour` (CONTOUR sketch) is declared in the registry as two OPTIONAL
    # parameters — the registry cannot express "exactly one of the two".
    "create_ceiling": (
        "ФОРМА ЗАДАЁТСЯ РОВНО ОДНИМ ИЗ ДВУХ: `outline` — прямая ломаная из "
        f"{MIN_RING_POINTS}..{MAX_RING_POINTS} точек, `contour` — эскиз CONTOUR (rect/l/poly, дуги, "
        "отверстия). Ни одного — отказ «форма не задана»; оба сразу — отказ "
        "«форма задана дважды»: какое из двух описаний истинно, компилятор "
        "решать за автора не станет.",),
    # compiler.py:943 (KIR-T002). Measured 13.08: `top_xy` without
    # `top_level` is rejected, with it — accepted.
    "create_column": (
        "`top_xy` задаёт НАКЛОННУЮ колонну и требует `top_level` рядом: без "
        "верхней отметки верх наклонной колонны не определён, и угадывать её "
        "компилятор не станет. Вертикальной колонне `top_xy` не нужен.",),
    # compiler.py:1136/1124 (KIR-P007). The same kind of rule as the
    # ceiling, but a different subject: not the shape of the outline, but
    # the flight's geometry.
    "create_stairs": (
        "МАРШ ЗАДАЁТСЯ РОВНО ОДНИМ ИЗ ДВУХ: оба конца `p0_mm`+`p1_mm` — "
        "прямой марш, либо `spiral` — винтовой (center_mm, radius_mm, "
        "start_angle_deg, included_angle_deg, clockwise). Ни одного — отказ "
        "«марш не задан»; оба сразу — отказ «марш задан дважды».",),
    # compiler.py:545 (KIR-T002), a shared site `hosted_offset_check` for
    # both opening ops. The rule is CROSS-OP: it takes the length from the
    # host wall, that is, from a DIFFERENT op of the program — a per-file
    # validator cannot express it.
    "create_window": (
        "`offset_mm` отсчитывается ВДОЛЬ СТЕНЫ-ХОЗЯИНА от её начала, и отказ "
        "сравнивает его с ДЛИНОЙ этой стены: «offset 99000мм за пределами "
        "стены (5000мм)». Окно за краем стены невыразимо, а не молча "
        "сдвигается.",),
    "create_door": (
        "`offset_mm` отсчитывается ВДОЛЬ СТЕНЫ-ХОЗЯИНА от её начала, и отказ "
        "сравнивает его с ДЛИНОЙ этой стены: «offset 99000мм за пределами "
        "стены (5000мм)». Дверь за краем стены невыразима, а не молча "
        "сдвигается.",),
}

#: Constraints that do NOT stop the op from working, but that are better
#: known before the call: each one measured live.
CONSTRAINTS: tuple[str, ...] = (
    # THREE WAVES OF ONE DAY EDITED THIS ROW, and at the merge all three
    # moves were taken, because they do not conflict, they add up:
    #   * the strip-foundation wave compressed the phrase about the pool to
    #     save space;
    #   * the framing wave EXPANDED the fact — the curved-orientation family
    #     requirement applies to TWO operations (`create_beam` and
    #     `create_beam_system`: the second assigns the same symbol in
    #     `BeamType`);
    #   * the `spec()` wave pushed the second fact out of here entirely.
    # The framing wave's expansion was taken WITHOUT its caveat about the
    # reference level — that very caveat is exactly what the third wave
    # pushed out.
    "Каркас: `create_beam` и `create_beam_system` требуют "
    "КРИВООРИЕНТИРОВАННОГО семейства, пул `beam_types` отдаёт только такие и "
    "в проекте с точечным каркасом пуст — честное «не на чем», а не "
    "поломка.",
    # PUSHED OUT 09.08, NOT DELETED. This used to read "Revit derives the
    # beam's reference level from the curve's elevation, not from the
    # `level` argument; the resulting level is returned in the witness
    # (`reference_level`)" — 176 characters of permanent cost. This exact
    # fact sits in the op's POSTCONDITION (`spec.OPS['create_beam']
    # .post`, also `ops_struct.py`) and sits there MORE STRONGLY: with the
    # measurement's date and with two level names from it ("passed L_01 @ 0
    # with the curve at Z=3000 -> bound to L_01ДОО1_+2.500"). The
    # postcondition is printed by `spec("create_beam")` — that is, the fact
    # is not lost, it moved from a permanent cost to a one-time one, and at
    # the same time stopped being a second, dimmer copy of one record.
    # CHECKED AT THE 09.08 MERGE FOR ALL THREE OPS, not just the one beam:
    # the framing wave was extending the caveat to the truss, and the
    # push-out only works if the postcondition carries the fact for each
    # one. It does: `create_beam` (Revit derives the level from the curve's
    # elevation), `create_beam_system` ("BeamSystem.Level == resolved
    # level"), `create_truss` ("reference level link is REAL, and WHICH
    # level — travels in the receipt rather than being required"). `spec(<оп>)`
    # prints all three.
)

#: Idioms measured 2026-07-27 by giving the MODEL seven building tasks: from
#: the generated schema alone it authored a valid Eiffel Tower (57 ops), so the
#: ops themselves are legible. Every remaining failure was a rule that exists
#: only inside a diagnostic — unknowable up front — and two of them made the
#: model REFUSE tasks KIR can actually do. Authored in a parallel session and
#: preserved verbatim here except for the `ref` line, which was first corrected
#: against the live matrix (27.07) and then DISPLACED on 09.08, once
#: `course.spec()` began printing the accepted selector forms SLOT BY SLOT from
#: `ParamSpec.ref_kinds`. Its non-derivable half moved verbatim into
#: `skill.TECHNIQUES`, so this tuple is shorter without a single measurement
#: having left the description — see the comments at each removal site.
AUTHORING_IDIOMS: tuple[str, ...] = (
    "Толщина/ширина конструкции — это ТИП, а не параметр операции. Перекрытие "
    "200 мм = create_type(category='architectural', width_mm=200, "
    "source_type=…) и затем create_floor(type=<этот тип>). У "
    "create_floor/create_wall своего поля толщины НЕТ — это не значит, что "
    "задача невыполнима.",
    # Corrected against the live matrix 2026-07-27: `ref` is NOT level-only.
    # Checked live — a window by ref on its own wall, set_param and
    # create_tag by ref on their own element. The restriction concerns
    # specifically catalog selectors.
    # MERGE 04.08: a separate trap, "The host and the target are addressed
    # via ref — a window on a wall just created, a tag on an element just
    # created", stood FOURTEEN rows below and carried not a single fact
    # beyond this one: `host`/`target` are already named here, and named
    # together with a restriction that was not there at all. Two paragraphs
    # about one idea were being paid for on EVERY request; the example from
    # the second was carried over here in full, so nothing at all was lost.
    #
    # PUSHED OUT 09.08. The paragraph listed WHICH SLOTS have the `ref`
    # shape — and that is exactly what the registry carries in
    # `ParamSpec.ref_kinds` and what is now printed PER SLOT:
    # `spec("create_wall")` shows `level  sel:
    # name|element_id|default|ref(level)` next to `type  sel:
    # name|element_id|default`, that is, it answers the question more
    # precisely than the prose — about a SPECIFIC slot, not about their
    # genre. A list of slots would not have survived even ten new ops: it
    # would lie confidently, because it was written by hand.
    # THIS WAS CONFIRMED THE SAME DAY, AT THIS SAME MERGE: a parallel wave
    # was rewriting this very paragraph, because create_wall_foundation
    # brought a `wall` ref-parameter that was not in the list
    # (level/base_level/top_level, host, target, refs) — a model reading the
    # list as closed would have given up on "build a wall and a strip
    # footing under it", a task the compiler DOES CARRY OUT. The very same
    # list had gone stale within one wave; a per-slot printout from the
    # registry cannot go stale, so it is what was taken, not a hand-rewritten
    # list.
    # WHAT CANNOT BE DERIVED FROM THE REGISTRY WAS CARRIED OVER VERBATIM into
    # `skill.TECHNIQUES` ("ADDRESSING WITHIN A PROGRAM", the same request,
    # the same text): that ref lives only within a single program, and the
    # 27.07 live correction "for `type`/`symbol` ref does NOT work". Not one
    # measurement was deleted — `test_ref_rule_matches_the_compiler` holds
    # both halves after the move too.
    # TRIMMED 09.08 (by a second wave, and its trim was taken too): the
    # second half ("query_list with filters first") sits in the guide —
    # "`query_list` gives the ids of existing elements by filter" (READ THE
    # MODEL FIRST). What remains here is the BAN that is not in the guide.
    "Существующий элемент не выбрать описанием («южная стена») — только по id "
    "из `query_list`.",
    # THE CHOICE of a macro for the shape of a task moved to
    # `skill.SHAPE_OF_REPETITION` (30.07): that is a judgment call, not a
    # trap, and keeping it in two places means paying for it twice. What
    # remains here is only what cannot be derived from the schema — which
    # SHAPES are accepted under `transform` and what sets the curvature.
    "Под `stack.transform` криволинейный план — это "
    "`contour.outer.shape='poly'` с точками по эллипсу: rect и l там не "
    "принимаются, потому что не переносят поворот без потери смысла. Гнутые "
    "стены — поле `arc`, наклонные колонны — `top_xy` вместе с `top_level`, "
    "прочее наклонное — балкой.",
    # `defaults` against betting on the default, and the CHOICE of `series`
    # for a changing parameter moved to `skill.BEFORE_YOU_SEND` /
    # `skill.SHAPE_OF_REPETITION` (30.07) — both are judgment calls, not
    # traps. The track syntax ("$hw", "$hw@next", "-$hw") is not needed here
    # either: checked 30.07 — the schema itself describes `track`, `items`
    # and the `@next` suffix, and prose that duplicates the schema costs
    # tokens on every request and drifts from it at the very first edit.
    # PUSHED OUT 09.08 ENTIRELY, and TWO waves retired this trap
    # independently of each other — a coincidence that is itself an
    # argument. The trap "Points: for walls/columns/rooms — [x,y] in mm, for
    # beams, pipes and place_family — [x,y,z]. Sloped elements are made with
    # a beam" split into two halves, and neither was left homeless:
    #   * the enumeration of dimensionality by op is a KIND OF REGISTRY
    #     PARAMETER (`pt_xy` / `pt_xyz`), which `spec(<оп>)` prints PER SLOT
    #     and more precisely; written by hand, it would silently go stale
    #     with every new op, while the fact itself — "a flat point where a
    #     spatial one is expected is a refusal" — sits in
    #     `skill.TECHNIQUES` ("COORDINATES AND UNITS") in that same request.
    #     The ЭОМ wave added a LIVE argument to this: the enumeration would
    #     already be lying, because flexible runs have no point at all —
    #     they have a path;
    #   * the route "sloped — with a beam" is attached one row above, to the
    #     idiom where curved walls and sloped columns already stand: one
    #     idea — one place. It also CONTRADICTED that row: a sloped column
    #     is made as a column, via `top_xy` together with `top_level`
    #     (ops_authoring.py, ParamSpec("top_xy")).
    #
    # THE MEASUREMENT THIS WAS WRITTEN FOR (the ЭОМ wave, kept at the
    # merge): the tool text had run into its own ceiling. `test_tool_doc`
    # holds a line at 30 000 characters (~10 000 tokens of prose, measured
    # at 3.00 characters/token), and BEFORE this wave it held 29 976 — that
    # is, any next registry operation would have turned the gate red no
    # matter what it does. The figures in the test's own docstring (26 786
    # characters) had gone stale by ~3 300 characters. The module's rule
    # works exactly this way: the text must push itself out, not grow. This
    # very measurement is what decided the ORDER of the 09.08 merge: the
    # `spec()` wave went in FIRST, because it is the only one that frees
    # room rather than taking it.
    #
    # MERGE 09.08: the site wave was editing THIS SAME trap — not retiring
    # it, but APPENDING topography to it ("for beams, pipes, place_family
    # and topography — [x,y,z]"), and for the same reason as the ЭОМ wave:
    # an enumeration goes stale with every new op. That is an argument FOR
    # pushing it out, not for editing it, so the push-out was taken. The
    # site wave's unique fact was not lost in the process, and is NOT
    # rewritten as prose: "for topography, the Z of a point is GROUND
    # ELEVATION, not an offset from a level" sits in the op's postcondition
    # ("no level — elevation lives in each point's Z", `ops_site.py`), which
    # is printed by `spec("create_topography")`. Checked at the merge by
    # running it, not by reading it.

    # 🔴 THE NUMBERS IN THE NEXT FOUR ROWS ARE DEAD (flagged 20.08.2026, the
    # live ones: MAX_OPS_PER_PROGRAM 1000, MAX_BULK_OPS 10000 — asked from
    # `compiler`). Left in NOT by oversight: this is a record of the EVENT
    # of 27.07, and an event stays true forever — back then the model was
    # told 300, and it paid with a round trip.
    # The lesson about DIFFERENT budgets holds in full; what holds is not
    # the figures but the distinction.
    # 20, not 300: MAX_BULK_OPS=300 is the INTERNAL decompile/rebuild budget,
    # never the serving path. Told 300, the model sent a 24-op program and got
    # KIR-L001 (expected <=20, got 24) — the wrong number cost it a round and a
    # rewrite (measured 2026-07-27, Eiffel-tower run).
    # FIX 04.08: "no more than 20 operations (MAX_OPS_PER_PROGRAM). This is
    # small on purpose" was REMOVED from here — not because it is wrong, but
    # because it already sits twice in this same request: `_two_input_forms`
    # prints the ceiling by INTERPOLATION from `compiler.MAX_OPS_PER_PROGRAM`,
    # and `skill.CRAFT` prints it too, together with the measurement "210
    # refusals out of 586". Here the number was a LITERAL, that is, exactly
    # what this module forbids writing numbers as: let it drift from the
    # compiler and it would lie confidently. The trap's unique part (the
    # group arithmetic) was kept in full.
    "Повторяющееся собирается не перечислением, а через "
    "create_group(members, placements) — панель на 19 операций, поставленная в "
    # "A large building is a BATCH of programs" moved from here to the
    # `create_stairs` trap (04.08). There it sits next to the RULE that
    # FORCES this batching, together with the answer to "so how do I check
    # the whole thing" — here it had been a slogan with no address: the
    # model read it, agreed, and still wrote the building as one program,
    # because it knew neither what to split nor where to ask for a verdict.
    # Measurement 03–04.08: 4 A/B runs, 0 buildings with no blockers; a
    # strong model found the wall on its own and cobbled a staircase out of
    # 15 `create_floor` calls. The row was moved, not duplicated: paying
    # twice for one idea costs more than moving it to its cause.
    "40 мест, даёт 760 элементов одной программой.",
)

#: Traps observed while proving the ops against a live Revit (the live matrix,
#: scripts/kir_live_matrix.py). Each cost a round-trip to find.
NOTES: tuple[str, ...] = AUTHORING_IDIOMS + (
    # wave/sweep (09.08). A TRAP OF EXACTLY THIS KIND: it CANNOT be derived
    # from the schema (the field simply does not exist, and the model will
    # go looking for where to write the fascia's height), and this is a
    # documented Autodesk fact, not a decision of ours.
    "create_wall_sweep не принимает высоту и смещение, и это ограничение "
    "Revit, а не схемы: положение и профиль карниза/руста целиком задаёт "
    "загруженный ТИП («the values set in the WallSweepInfo are ignored» — "
    "RevitAPI.xml всех версий). Нужна другая отметка — нужен другой тип. "
    "create_slab_edge по той же причине обводит ВЕСЬ периметр названной "
    "стороны (side=top|bottom), а плита с отверстием отказывает: какое из "
    "колец обводить, назвать пока нечем.",
    # TRIMMED 09.08: the first phrase ("ask query_types first, then set the
    # selector") sits verbatim in the guide — "CHOOSING A TYPE AND FAMILY:
    # there is one reliable order — query_types, then a choice by
    # element_id". What remains here is what is not in the guide and cannot
    # be derived from anywhere: the MEASUREMENT itself and the refusal code.
    # What to do with KIR-G102 (the diagnostics already carry `candidates`)
    # is in `skill.REFUSAL_PLAYBOOK`: that is next-turn tactics, not a trap
    # of the op. What remains here is only what the guide does not say: a
    # second, narrower disambiguation path, usable when there is nowhere to
    # take an id from.
    "У неоднозначного селектора есть и второй путь уточнения — "
    "disambiguate_by={param, value}: принимается, только если после фильтра "
    "остаётся ровно один кандидат.",
    # WHY RIGHT HERE, AND NOT AS A SEPARATE ROW. A ban with no way out is a
    # dead end, and the measurement showed this: the model read "sibling =>
    # KIR-L002", agreed, wrote in the script "create_stairs must be alone" —
    # and cobbled a staircase out of 15 `create_floor` calls, because it did
    # not know WHERE else to put it. The rule, the method, and the point of
    # the check are one idea, and its cost is paid once.
    # THE SECOND HALF OF THE SAME HOLE, CLOSED ON 04.08. The channel had
    # been built and stayed silent: session programs piled up in the
    # journal, the batch went to the showroom and the executor, and the
    # MODEL was never told anywhere that it was building the building in
    # pieces and that someone judges that building as a whole. In the
    # 03–04.08 measurement the model mastered batching PRECISELY because the
    # test rig told it so; in prod there was no such row, and the model kept
    # writing the building as one program. The row sits here, not as a
    # separate trap, for the same reason "building = BATCH" moved here: the
    # rule, the method, the point of the check, and the feedback are one
    # idea, and its cost is paid once.
    # 10.08: the solo-ops became TWO, and the second half of the rule needs
    # a WAY OUT, not just a ban — exactly the lesson this paragraph was
    # written for (a model that read "sibling => KIR-L002" with no "where to
    # put it" cobbled a staircase out of 15 `create_floor` calls). The
    # landing goes in its OWN program onto the already-built staircase, and
    # the method is named directly: `stairs=element_id`.
    "`create_stairs` и `create_stairs_landing` — каждый единственный оп своей "
    "программы (StairsEditScope владеет "
    "собственными транзакциями; сосед => KIR-L002). Площадка — СЛЕДУЮЩАЯ "
    "программа по уже построенной лестнице: stairs={by:element_id}. "
    "Здание = ПАЧКА: тело "
    "отдельно, лестницы отдельно; уровень тела виден лестнице ПО ИМЕНИ "
    "(base_level=\"Этаж 1\", не ref). Программы сессии НАКАПЛИВАЮТСЯ в одно "
    "здание: вердикт о ПАЧКЕ сам приезжает в КВИТАНЦИИ пишущего хода "
    "(блок `building`); в скрипте — design_check([тело, лестница]). "
    "Многоэтажная — НЕ программа на этаж: марш один раз, затем "
    "`create_multistory_stairs(stairs, levels)`, оп обычный.",
    "У аннотаций (`create_dimension`/`create_tag`/`create_text`) точка — это "
    "ПРОСТРАНСТВО ВИДА: [u,v] мм от начала вида вдоль его осей, не координата "
    "модели. Трёхкомпонентная точка там — типизированный отказ.",
    # MERGED 09.08 FROM TWO TRAPS. This was one idea written down twice: the
    # SHAPE of the cross-section — both what tells apart types
    # indistinguishable by name and what decides whether `diameter_mm`
    # applies at all. They were read separately, and the model could take
    # "I'll ask element_id" from the first and still pick a rectangular
    # type. The room the merge freed went to three new ops in UNPROVEN,
    # rather than to raising the description's ceiling.
    "ФОРМА сечения воздуховода решает всё: `diameter_mm` выражает только "
    "КРУГЛОЕ (на прямоугольном постусловие поймает несовпадение и откатит), "
    "а три типа ОДНОГО здания назывались «По "
    "умолчанию» и различались лишь формой — by=name там законно "
    "отказывает KIR-G102.",
    # The detailing wave, 09.08. It sits RIGHT HERE, next to the rule above,
    # because a filled region is the only operation where what travels into
    # the view space is not a point but an ENTIRE OUTLINE, and the natural
    # reading "an outline like a floor's" leads to exactly the mistake Revit
    # will silently punish only on a section. That is, it is a trap about
    # the CHOICE between `create_floor_by_contour` and a filled region — and
    # so it stays in the permanently loaded text.
    #
    # TRIMMED AT THE MERGE, AND TRIMMED BY THE SAME RULE AS EVERYTHING ELSE
    # (09.08). The wave brought it in whole, and the tail — the `at_grid`
    # refusal and the advice to ask `query_types` — is needed once the op is
    # ALREADY chosen, and moved to `OP_NOTES["create_filled_region"]`, from
    # where it is printed by `spec("create_filled_region")`. The rule is
    # applied to the INCOMING wave deliberately: if new text enters on the
    # old terms, the discipline holds only until the next wave.
    "`create_filled_region` берёт `contour` в ПРОСТРАНСТВЕ ВИДА, а не в осях "
    "модели: та же грамматика форм, что у контурного пола, но точки — [u,v] "
    "мм от начала вида.",
    # The ЭОМ wave, 09.08. The one property of the new ops that is OFFLINE
    # UNMEASURABLE: whether Revit returns the flexible run's array of points
    # one-to-one. Autodesk documents that coincident points are DROPPED; the
    # compiler refuses those in advance, but whether Revit resamples the
    # rest is something nobody knows until there is a live run. The witness
    # is deliberately written LOUD (exactly as for create_directshape): the
    # first live run will show it.
    "`create_flex_duct`/`create_flex_pipe` берут `path` — 3D-ломаную, не пару "
    "концов; свидетель сверяет ВЕСЬ путь. Живьём не проверялись.",
    # PUSHED OUT 09.08, NOT DELETED: the fitting family requirement moved to
    # `OP_NOTES["create_pipe_system"]`, that is, into the op's own
    # docstring. What remains here is the reason this row sits in the
    # permanently loaded text — the CHOICE between a single network op and
    # a scatter of `create_pipe`; the fitting itself is read inside the
    # already-chosen op, while drawing a turn.
    "Сеть (`create_pipe_system`/`route_*`) — один оп на всю трассу: узлы плюс "
    "рёбра, связность по построению, фитинги выводятся из степени узла.",
    "`load_family` берёт ЯВНЫЙ путь к .rfa и сам проверяет наличие файла; путь "
    "угадывать нельзя. После загрузки пул типов наполняется — `create_type` "
    "дублирует типоразмер от загруженного символа.",
    # Until 2026-07-27 this idiom described something no caller could actually
    # do: `ground()` never recursed into `members`, so the emitter met a raw
    # selector and raised KeyError, reported as "члены должны быть pre-grounded
    # (element_id/…)" — advice that failed identically when followed. 0 uses in
    # 51 574 lifted ops. Members now ground like any other op.
    # PUSHED OUT ENTIRELY 09.08 into `OP_NOTES["create_group"]`. The
    # paragraph described the group's INNER WORKINGS (member coordinates,
    # the shape of `placements`, the ban on `by: ref` inside it), that is,
    # it answered a question that arises only AFTER the op is chosen. The
    # CHOICE itself is made by the trap above ("A repeating thing is
    # assembled not by enumeration but via create_group") — that one
    # stayed.
    #
    # THE MESH TRAP WAS RETIRED FROM HERE BY THE BODY WAVE, AND THAT IS
    # TAKEN (merge 09.08). Both sides were converging on the same thing:
    # this paragraph was retelling the honest label and the ban on
    # impersonation, while `skill.TECHNIQUES` ("FREE FORM") said the same
    # thing in its own words in the SAME request — the mechanical guard
    # (`test_course_and_notes_do_not_overlap`) did not see this, because it
    # looks for verbatim seven-word matches, and a paraphrase slips through
    # it.
    # CHECKED AT THE MERGE AGAINST THE TEXT OF THE RECONCILED TREE, not
    # against intent: the guide holds both "a person will not edit it like a
    # wall — only delete and rebuild", and "it has no walls/floors/
    # roofs/columns categories at all", and ceilings in its list of own
    # operations. The closed list of categories is additionally printed by
    # `spec("create_directshape")` straight from the registry.
    #
    # IN EXCHANGE THE WAVE BROUGHT A FACT THAT WAS NOWHERE ELSE, and it
    # stays here, because it is needed BEFORE the choice: a model that does
    # not know that x is the RADIUS for a revolve profile will write a plan
    # outline and get refused on the axis. The trap names TWO ops, that is,
    # it helps choose between them — by that same rule it did not move to
    # `OP_NOTES`.
    "У свободной формы своя система координат, и это не выводится из схемы: "
    "`create_solid_extrusion` выдавливает контур строго вдоль +Z, а у "
    "`create_solid_revolve` контур читается В ОСЕВЫХ координатах — x есть "
    "РАДИУС от оси (только >= 0), y — отметка вдоль неё; сама ось вертикальна "
    "и проходит через `axis_xy_mm`. Объём сверяется аналитически, поэтому "
    "тело тоньше собственного допуска — НАЗВАННЫЙ отказ, а не подпись.",
    # PUSHED OUT 09.08 into `OP_NOTES["delete"]`: the envelope requirement is
    # read once `delete` has already been written, not when deciding whether
    # to delete.
    # How to READ a refusal (including `handoff`) is in
    # `skill.READING_A_REFUSAL`: that is next-turn tactics, not a trap of a
    # specific op.
)


#: THE CHOICE OF INPUT FORM is the task's first decision, and it is made
#: BEFORE the model opens the operation's schema. That is why the text sits
#: at the start of the description rather than in a parameter field: a
#: field is read once the form has already been chosen.
#:
#: Numbers NOT as literals: `ALLOWED_IMPORTS`, `MAX_BULK_OPS`, and the
#: authoring budget are interpolated from their own sources — this package
#: has already paid a round trip for prose that drifted from the compiler
#: ("300" was said, the compiler held 20).
def _selector_forms_in_python() -> list[str]:
    """How the slot selector in `program_py` is filled — by three equal forms.

    **Measured 2026-08-12: the code was richer than the docs, and the model
    wrote using the most cumbersome of the available ways.** A slot accepts
    a bare string, a bare integer, a constructor, and a dict; all of them
    produce BYTE-FOR-BYTE the same node —
    `level="Этаж 1"`, `level=by_name("Этаж 1")` and
    `level={"by":"name","value":"Этаж 1"}` are indistinguishable in the
    assembled program. The docs named only the dict: twenty-five hand-written
    dict selectors in the rendered text against zero mentions of
    `by_name`/`by_element_id`/`by_default`/`family_type`. The bare form was
    not mentioned AT ALL.

    The same class of defect that closed `nameof` in the emitter: the drift
    is possible precisely because it CAN BE WRITTEN. A hand-dictated dict is
    the place where a typo in a key becomes a program; the constructor does
    not allow it, and the bare string does not even let you write a key.

    The text is ASSEMBLED FROM THE AUTHORITY, not rewritten alongside it:
    the hints are taken from `dsl._SELECTOR_HINTS` — the same dict the
    language uses to explain its own refusal (`_selector_error`). There is
    nothing here for the description and the behavior to drift over; add a
    new form to the language and it appears here on its own.
    """
    from kir import dsl
    hints = dsl._SELECTOR_HINTS
    return [
        "  СЛОТ-СЕЛЕКТОР (`level`, `type`, `host`, `symbol`, `target`) в "
        "скрипте заполняется ЧЕТЫРЬМЯ равными формами, и собранная программа у "
        "них побайтно одна: " + "; ".join(
            f"{hints[form]}" for form in ("name", "element_id", "default", "ref")
            if form in hints) + ". "
        "Пиши КОРОТКУЮ: `level=\"Этаж 1\"` вместо "
        "`level={\"by\":\"name\",\"value\":\"Этаж 1\"}` — ключ, который нельзя "
        "написать, нельзя и перепутать. Словарь оставь для формы `program`, "
        "где он и есть проводной вид.",
        "  Выбор типоразмера семейства — `family_type(category=..., "
        "family_name=..., type_name=...)`; сузить пул по параметру — "
        "`disambiguate(param, value)`; отдать выбор документу — `DEFAULT` "
        "(он же `by_default()`).",
        "  СПРОСИ, А НЕ ПОМНИ: `spec(\"create_wall\")` — поля и границы опа, "
        "`selector_forms(\"create_wall\", \"level\")` — какие формы принимает "
        "ИМЕННО этот слот, `op_names(writes=True)` — все пишущие опы реестра. "
        "Три функции одного рода; ответ приходит из реестра, а не из этой "
        "строки, и потому не устаревает.",
    ]


def _two_input_forms() -> list[str]:
    from kir.compiler import MAX_BULK_OPS, MAX_OPS_PER_PROGRAM
    # 19.08: USED TO BE A FROZEN CONSTANT. `ALLOWED_IMPORTS` does not know
    # about the operator flag `KUKAI_IR_AUTHOR_GEOMETRY_LIBS`, so the
    # description was telling the model a list of three modules while the
    # sandbox was letting five through. Measured 19.08: in prod the flag=1,
    # numpy 2.4.4 and shapely 2.1.2 make it through and are listed in the
    # receipt, while the model read "they don't exist" and never tried.
    allowed = ", ".join(sandbox.allowed_imports_for_env())
    return [
        "ДВЕ ФОРМЫ ВХОДА, РОВНО ОДНА ЗА ВЫЗОВ: `program` (операции) ЛИБО "
        "`program_py` (питон, который их порождает). Оба сразу или ни одного "
        "— типизированный отказ.",
        f"  • ПЕРЕЧИСЛЕНИЕ разнородного — `program`: пять стен, дверь, "
        f"помещение. Потолок {MAX_OPS_PER_PROGRAM} операций.",
        f"  • ПОВТОР, РАСЧЁТ, СИЛУЭТ, МНОГО ЭТАЖЕЙ — `program_py`. Авторская "
        f"вещь тут скрипт, а не его выход, поэтому выход меряется другим "
        f"бюджетом: до {MAX_BULK_OPS} операций. Признак выбора один — если "
        f"пишешь третью почти одинаковую операцию, меняя в ней число, это "
        f"скрипт.",
        "КАК УСТРОЕН `program_py`. Каждая операция реестра уже лежит в "
        "пространстве скрипта ФУНКЦИЕЙ с теми же именами и полями (язык "
        "импортировать не надо и нельзя). Вызов кладёт оп в программу и "
        "возвращает РУЧКУ — её передают как level/host/target, и ссылки "
        "сходятся по построению. Конверт — "
        "`envelope(intent=..., defaults=..., allow_destructive=...)`, но "
        "`defaults` заполняет только ОПУЩЕННОЕ поле, а обязательный аргумент "
        "(`level` и родня) питон опустить не даст — держи его в переменной и "
        "передавай каждому вызову. Программу забирают сами: ни `return`, ни "
        "печати JSON не нужно.",
        "  КАТАЛОГ ОТКРЫТОГО ДОКУМЕНТА СКРИПТУ ВИДЕН: `model.levels()`, "
        "`model.grids()`, `model.types(<пул>)` отдают строки {id, name, …} "
        "того документа, в который пишешь. Отсюда этаж пишется ПРАВИЛОМ "
        "(`for lvl in model.levels(): ...`), а тип называется по факту, а не "
        "наугад. Геометрии здания там нет — только каталоги; каталог, которого "
        "не подали, сам назовёт причину.",
        "  ПО ИМЕНИ ИЩИ `model.find(<пул>, <имя>)` И `model.level(<имя>)`, а не "
        "перебором со своим `next(..., None)`: опечатка тогда даёт None, ты "
        "дописываешь `or <число>` — и в программу уезжает НОЛЬ величины, "
        "которую никто не считал. Отказ вместо этого называет похожие имена. "
        "`model.level()` вдобавок везёт `indistinguishable_on_elevation`: если "
        "на той же отметке стоит ДРУГОЙ уровень, он назван — выбор между ними "
        "сделал бы не ты. Правило совпадения то же, что у заземления: точное, "
        "иначе единственное регистронезависимое, иначе отказ.",
        "  ОТМЕТКУ ИЗ КАТАЛОГА НЕ СРАВНИВАЙ ТОЧНЫМ РАВЕНСТВОМ: она приходит "
        "переводом из футов, и «Этаж 9» на 32700 читается как "
        "32699.999999999996. Сравнивай с допуском либо бери число как есть.",
        # 🔴 THIS PARAGRAPH WAS BOUGHT BY THE 17.08.2026 MEASUREMENT, AND IT
        # NAMES THE COST OF CHOOSING A FORM.
        #
        # The row above has stood here for a long time and tells the truth:
        # on the `program_py` path the catalog comes FREE. The measurement
        # showed that this is not enough — the model almost always chooses
        # JSON and pays for the catalog in turns:
        #
        #   `query` runs (recon) over 7 days of prod                487
        #   `script_catalogue` runs (catalog to the script)           9   = 1.8 %
        #   mentions of `program_py` in the journal over the same 7 days  9
        #
        #   from the witness corpus (2159 rows, 21.07–17.08):
        #   turns with `query_types`                                425
        #   of them PURE recon (nothing else in the program)        409 = 96.2 %
        #   the share of pure recon among ALL turns of the day IS GROWING:
        #     14.08 31.1 %  ·  15.08 45.8 %  ·  16.08 48.5 %  ·  17.08 64.8 %
        #
        # WHY IT IS GROWING — a mechanism, not a guess: the `query_types`
        # answer is a LIST, and `chat_helpers._summarize_tool_result` past
        # `KEEP_RECENT = 30` replaces EVERY list with "«<N элем. — свёрнуто>»".
        # A catalog just received gets erased from the history — and the
        # model asks again. The longer the session, the more frequent the
        # erasure.
        #
        # Hence the paragraph below: it does not persuade, it NAMES THE
        # COST. Knowing that the answer will be erased is the one thing the
        # model does not have on this path and cannot obtain on its own: it
        # cannot see its own history.
        #
        # 🔴 WHAT THIS PARAGRAPH DOES NOT DO, AND CANNOT. It does not put the
        # catalog somewhere the collapsing cannot reach. There is a place for
        # that — the tool description is reassembled on EVERY turn
        # (`client._inject_per_turn_tools` → `serving.inject_revit_ir_schema`)
        # and is not history — but there is no live catalog on this path:
        # assembling the description is SYNCHRONOUS and holds neither a
        # bridge nor a client. A run for the catalog costs 3262–3675 ms
        # (measured 16.08), and the tower's own catalog is 35 pools / 895
        # rows / 288 137 B ≈ 96 thousand tokens, of which 70% is held by ONE
        # `family_symbols` (67 thousand); the remaining 34 pools are 29
        # thousand. The split is named so that the next person who takes
        # this on sees the dose right away.
        # 🔴 REWRITTEN 17.08.2026 ON THE OWNER'S DIRECT CORRECTION. The
        # earlier text was titled "THE COST OF THE FORM" and told the model
        # that recon costs a whole turn. The owner removed this frame
        # verbatim: "reconnaissance is normal, better to think ten times and
        # do it once", and instructed not to raise the 64.8% as a defect.
        #
        # HE IS RIGHT, AND THE MEASUREMENT SUPPORTS THIS RATHER THAN REFUTING
        # IT. The figures above are correct; what was wrong was the
        # CONCLUSION drawn from them: 96.2% pure recon is not the model
        # being wasteful, it is a consequence of the catalog being ERASED
        # from its history. It asks again not out of curiosity but because
        # it FORGOT. Talking it out of doing recon would mean treating the
        # symptom and spoiling good behavior: the constitution explicitly
        # credits the model with the virtue of being able to "check
        # exhaustively".
        #
        # So what stands here is no longer a cost but a FACT the model
        # cannot obtain on its own: on this path the catalog is ALREADY IN
        # ITS HANDS. This is not a plea to save turns — it is a message that
        # a turn does not need to be spent.
        #
        # A neighboring session reached the same conclusion about this
        # paragraph independently, the same evening. The coincidence of two
        # approaches is itself an argument.
        "  КАТАЛОГ УЖЕ У ТЕБЯ: в `program_py` `model.types(<пул>)`, "
        "`model.levels()`, `model.grids()` отвечают БЕЗ рейса в Revit — они "
        "приехали вместе с ходом. Спрашивай столько, сколько нужно.",
        "  ЧТО УЖЕ СТОИТ — `building`: `.top() .levels() .find(cat=,lvl=)"
        " .found() .get(id)`; найденный id годен в `target`.",
        # THE SLIDER (20.08.2026). It sits next to `model`/`building`,
        # because it is the third name the sandbox places itself
        # (`sandbox.HOST_NAMES`), and because without it the model does not
        # know that a program can be REBUILT without being rewritten. A
        # capability with nowhere to read about it does not exist for the
        # model — this house has already paid for a door that could do more
        # than it said.
        "  ПОЛЗУНОК — `param(\"width_mm\", 6000.0, min=3000.0, max=12000.0)` "
        "возвращает ДЕЙСТВУЮЩЕЕ значение: умолчание либо поданное вызывающим "
        "в `params`. Объявление и использование — одна строка. Ручка это "
        "ЧИСЛО, СТРОКА или ФЛАГ (список ручкой не бывает); границы `min`/`max` "
        "и набор `choices` проверяются ДО эффекта. Квитанция несёт ведомость "
        "ручек и `params_digest`, и по ним впервые различимы «переписал "
        "определение» (другой `author_digest`) и «двинул ручку» (тот же "
        "`author_digest`, другой `params_digest`).",
        # TWO CAPABILITIES WITHOUT WHICH THE MODEL PICKS THE WRONG FORM —
        # and that is why they are here, not in the skill. The first changes
        # HOW the author declares intent; the second — how it refers to
        # what was built on the NEXT turn. The rest about them (examples,
        # predicate details) lives in the lesson and in `spec()`, which are
        # read on demand.
        "  ЗАМЫСЕЛ НАБОРА — `with unit(\"имя\", reads_as=\"continuous\"):`. "
        "Постусловие судит ОДИН оп; «эти стены — одна лента» сказать нечем. "
        "Единица объявляет прочтение, и находка приходит с адресом ТОЙ стены, "
        "что его ломает: другой тип, излом, дыра. Без `reads_as` единица тоже "
        "пишется — она остаётся адресом.",
        "  ССЫЛКА НА ПОСТРОЕННОЕ — `element_map` квитанции: `op_id -> "
        "element_id`. Следующим ходом адресуй `by:element_id`, не ищи имя.",
        f"  Импорт разрешён РОВНО: {allowed}. random/time/os "
        f"нет: недетерминизм запрещён жёстко, потому что исходник "
        f"подписывается в квитанции (`author_digest`), а подпись случайного "
        f"скрипта не удостоверяет ничего. Скрипт исполняется дважды и "
        f"дайджесты сверяются — разошлись, это отказ.",
        "  Макросов (`stack`/`series`/`grid_array`) в скрипте НЕТ: их работу "
        "делает сам питон — цикл, арифметика, список. Они остаются формой "
        "поля `program`.",
        # SHAPE AND MULTIPLIER (19.08.2026). These rows sit here, not in the
        # guide's index: the index is at its own ceiling and is paid for on
        # every request, while this is the `program_py` reference, where
        # `model.find`/`model.level` already live. The
        # `test_sandbox_names_are_declared` guard demands exactly this: a
        # name in the sandbox with no description is declared DARK, because
        # a capability with nowhere to read about it does not exist for the
        # model.
        "  ФОРМА, КОТОРУЮ НЕ ВЫРАЗИТЬ КОНТУРОМ: `extrude(контур, высота)` "
        "строит тело мешем — тот же результат, что 8 вершин и 12 троек "
        "индексов руками, но проверенный до рейса. Контур: список [[x,y]...], "
        "{outer, holes} либо shapely Polygon. Плановые булевы делай shapely "
        "(`a.difference(b)`) и корми результат сюда; трёхмерных булевых в "
        "песочнице нет ни в одной библиотеке. Разрезанный на куски результат "
        "— НАЗВАННЫЙ отказ, а не один меш из двух тел.",
        "  ФОРМА ПО ТРАЕКТОРИИ: `sweep(профиль, путь)` ведёт плоский профиль "
        "по ломаной — поручень вдоль марша, карниз по ломаному фасаду, короб "
        "по трассе; `extrude` так не умеет, он ведёт только по вертикали. У "
        "профиля свои координаты: x вправо от движения, y вверх, ставишь его "
        "ты. Стык считается УСОМ по биссектрисе, поэтому на повороте сечение "
        "шире профиля в 1/cos(полугла) — так и режут карниз. Крутой поворот, "
        "на котором тело наложилось бы само на себя, — НАЗВАННЫЙ отказ с "
        "числом. Дуги нет: ломаная остаётся ломаной.",
        "  ТА ЖЕ ФИГУРА НАСТОЯЩИМ BIM-ЭЛЕМЕНТОМ: `region(фигура)` даёт "
        "`contour` для перекрытия, потолка, площадки. Разница с мешем "
        "несущая: у меша нет ни типа, ни толщины, ни строки в спецификации, "
        f"и человек его не отредактирует. Кольцо {MIN_RING_POINTS}.."
        f"{MAX_RING_POINTS} точки — предел НЕ "
        "обходится прореживанием за тебя, огрубляй сам и печатай, на сколько.",
        "  ПОВТОР — `create_group(members=[ручки], placements=[[x,y], ...])`: "
        "ручки вызовов становятся членами, оп ИЗЫМАЕТСЯ из программы в "
        "группу. 4 стены в 40 мест = 160 элементов одной программой. Член "
        "группы адресует уровень ИМЕНЕМ (`level=\"Этаж 1\"`), а не ручкой: "
        "ссылаться наружу группы нельзя, и компилятор это назовёт.",
        *_selector_forms_in_python(),
        "  `print(...)` возвращается тебе в квитанции. Печатай ЧИСЛОМ то, что "
        "приблизил (расхождение ломаной с кривой): названное приближение "
        "честно, неназванное — молчаливо неверный ответ.",
        "  Ошибка скрипта — типизированный отказ KIR-B* с НОМЕРОМ СТРОКИ "
        "твоего скрипта и самой строкой. Revit при этом не трогали вовсе: "
        "песочница стоит до компилятора и до транзакции.",
        # The row about `tools/design/examples/*` was DELETED deliberately:
        # it was advertising scripts that will NOT RUN in the sandbox (they
        # use numpy and shapely, while the import whitelist is exactly
        # math/itertools/functools). A pointer to the guide takes its place
        # and leads where one can actually get to.
        *_course_pointer(),
    ]


def _course_pointer() -> tuple[str, ...]:
    """A pointer to the guide — and it MUST be paired with the reachability
    of names.

    The reachability law (`tests/capability_reachability`): a capability
    with no path to it from the real entry point does not exist. For the
    pointer this same coin has a flip side: a description promising names
    that are not in the sandbox hands the model a lost round trip. That is
    why the pair "pointer ⟺ names" is held by
    `test_the_pointer_and_reachability_are_one_thing`, with half the seam red.

    The import is lazy: `tool_doc` is called on every turn, and the guide
    package pulls in corpus measurements along with it. It cannot return
    empty — the seam would then come apart silently.
    """

    from kir.course import POINTER

    return tuple(POINTER)


def program_py_schema() -> dict:
    """The schema of the `program_py` field.

    DELIBERATELY ONE LINE. Everything that could be taught here already
    sits in the tool description (`_two_input_forms`), and the field
    description is paid for by the same tokens in the same request: a
    retelling here is exactly a second payment for one idea, and it will
    also drift from the original at the very first edit.
    `test_description_stays_small_next_to_the_schema`'s threshold measures
    ONLY the tool description, so a duplicate in the field is invisible to
    the test but visible to the bill.
    """
    return {
        "type": "string",
        "description": (
            "Питон, который ПОРОЖДАЕТ программу IR (см. «ДВЕ ФОРМЫ ВХОДА» в "
            "описании инструмента). Взаимоисключающее с `program`."),
    }


def example_schema() -> dict:
    """The schema of the `example` field — "show me a real building, I'll
    learn from it".

    🔴 WHY THIS FIELD EXISTS AT ALL, IN ONE MEASUREMENT (17.08.2026). A
    model starting from a blank page writes **11 operations per attempt**;
    a real residential tower's floor carries **1000**. It writes so little
    not because it is weak, but because it has never seen production, and
    production sits right here on our disk: 52 parses of ten documents. A
    capability with nowhere to read about it does NOT EXIST for the model,
    and the cost of that is measured by its neighbors: recon was eating 43%
    of turns precisely because the default stayed silent.

    One line, like `program_py`, and for the same reason: a retelling in
    the field description is a second payment for one idea.
    """
    return {
        "type": "string",
        "description": (
            "Запрос к корпусу настоящих проектов: «жилая башня», «детский "
            "сад», «фасад», имя документа. Возвращает ЭТАЖ настоящего здания "
            "исходником `program_py` — ничего не строит. Задаётся ОДИН, без "
            "`program`/`program_py`."),
    }


def rehearse_schema() -> dict:
    """The schema of the `rehearse` field — "say what will NOT be checked,
    and do not write it".

    🔴 WHY THE FIELD EXISTS, BY TWO MEASUREMENTS FROM THE 18–19.08.2026 LIVE
    BENCHMARK. Both major failures of the shift were not geometry bugs but
    obligations that DID NOT RUN, and the silence about it: 420 columns at
    2500 mm instead of 3600–4500 (the conditional top-binding obligation
    was discharged by skipping `top_level`), and 540 out of 540 beams at
    z=0 while "Floor 5" had been written (Revit derives the beam's level,
    the argument decides nothing). Both were DERIVABLE BEFORE writing the
    row.

    A capability with nowhere to read about it does not exist for the model
    — this same defect cost us a whole shift of Python geometry. That is
    why the field sits in the schema, not in someone's memory.

    One line, like `example` and `program_py`: a retelling in the field
    description is a second payment for one idea.
    """
    return {
        "type": "boolean",
        "description": (
            "Отрепетировать программу и НЕ ПИСАТЬ: вернуть, что будет проверено, "
            "а что нет — с разделением «пропущено поле» / «решение проекта» / "
            "«дыра языка». Ни рейса, ни транзакции. Задаётся ВМЕСТЕ с "
            "`program` либо `program_py`."),
    }


def created_schema() -> dict:
    """The schema of the `created` field — "show me what I have already
    created".

    🔴 WHY THE FIELD EXISTS. The registry of created elements has been
    written since 17.08.2026 and until 19.08 was read by NOBODY (measured
    17.08: 30 rows, 471 elements per day, zero consumers). Its cost is
    named by its own header: on 13.08 two elements were left in the
    owner's live model with no trace of their numbers, and only a MANUAL
    read of the document saved the day. Both hands of the 18.08 live
    benchmark independently asked for this door in their own words — one
    was keeping id bookkeeping by hand across dozens of files.
    """
    return {
        "type": "boolean",
        "description": (
            "Вернуть журнал СОЗДАННОГО этой сессией: `op_id -> element_id` по "
            "ходам. Ничего не пишет. 🔴 «в журнале» НЕ равно «принято» — запись "
            "идёт до приёмки. Задаётся ОДИН, без `program`/`program_py`."),
    }


#: Потолок краткого описания. Слово владельца 13.09.2026: «дипсик можем в
#: ревите строить. значит он должен это делать в КИР и делать это еще
#: успешнее» — то есть режим КИР не имеет права быть ТЯЖЕЛЕЕ обычного хода той
#: же модели. Замер того дня: у обычного хода `execute_revit_code` — описание
#: 931 знак и схема 1 701, всего **2 632**. У хода КИР — описание **29 874** и
#: схема (после свёртки в `$defs`) **61 591**. Тридцать пять раз больше на том
#: же мозге, и результат замерен: ход `530f4ed7` — 174 291 мс, 0 вызовов.
BRIEF_DESCRIPTION_LIMIT_CHARS = 2000


def build_tool_description_brief() -> str:
    """Короткая справка `revit_ir` для ЧАТ-двери: КОНТРАКТ, а не учебник.

    🔴 ЧЕМ КУПЛЕНО. Полное описание (`build_tool_description`, 29 874 знака)
    писалось для агента, который читает справочник целиком и потом работает.
    Замер 13.09.2026 на живом ходе владельца `530f4ed7` показал, что DeepSeek
    делает другое: он пересказывает справочник САМ СЕБЕ. Кассета рассуждения
    55 434 знака, четыре блока правил по **77 раз**, вызовов инструмента —
    **ноль**, текста человеку — **ноль**, 174 291 мс, стоп рукой владельца.

    🔴 ПРИМЕРОВ ПРОГРАММ ЗДЕСЬ НЕТ, И ЭТО СЛОВО ВЛАДЕЛЬЦА (13.09.2026):
    «примеры программ это плохо. нужно только КИР сдк ему знать». Первая
    редакция этой справки несла пять готовых программ; они сняты. Остаётся
    КОНТРАКТ: форма конверта, бюджет, ловушки, адрес полного контракта опа и
    адрес списка имён. Мой довод «модель с образцом подражает, без образца
    пересказывает правила» остаётся ГИПОТЕЗОЙ и проверяется замером раздела S
    (рука без справки против руки со справкой), а не решается здесь.

    ЧТО УЕХАЛО ПО АДРЕСУ, А НЕ ПРОПАЛО: полный контракт операции — `spec(<оп>)`
    внутри `program_py` (и `kir_spec` у MCP-двери); СПИСОК ИМЁН по разделам
    проекта — `spec()` без аргумента; корпус настоящих проектов — поле
    `example`; репетиция без записи — поле `rehearse`; журнал созданного этой
    сессией — поле `created`.

    ФОРМА КОНВЕРТА ПЕЧАТАЕТСЯ ИЗ СХЕМЫ, А НЕ ПИШЕТСЯ РЯДОМ: `ir_version`
    берётся у `spec.IR_VERSION`, число операций — у компилятора. Два носителя
    одного контракта разошлись бы на первой правке версии.

    ПОЛНОЕ ОПИСАНИЕ НЕ УДАЛЕНО: оно служит MCP-двери и прозе; оба текста
    порождаются из одного реестра операций, так что двух источников правды нет.
    """
    from kir.compiler import MAX_OPS_PER_PROGRAM

    пишущие = sum(1 for op in spec.OPS.values() if op.writes_model)
    читающие = sum(1 for op in spec.OPS.values() if not op.writes_model)
    текст = f"""Типизированная программа для Revit. Ты описываешь ЧТО построить; единицы, версии API, транзакции и проверку постусловий на живой модели берёт на себя компилятор. Молчаливо-неверный результат невыразим: что не проверено — названо в квитанции.

КОНВЕРТ ВХОДА, поле `program`: {{"ir_version": "{spec.IR_VERSION}", "intent": "<зачем это строится>", "ops": [{{"op": "<имя операции>", "id": "<твой id для ссылок>", ...}}]}}. Обязательны `ir_version` и `ops`; у каждой операции свои поля. Вторая форма входа — `program_py`: питон, который эти операции порождает (циклы, `spec(...)`). Одна форма за вызов.

Бюджет одной программы — {MAX_OPS_PER_PROGRAM} операций. Пишущих операций {пишущие}, читающих {читающие}.

ТРИ ЛОВУШКИ, КОТОРЫЕ СТОЯТ РЕЙСА В РЕВИТ:
• Тип конструкции — это ТИП, а не параметр: толщина стены живёт в типе, а не в операции. Возьми существующий тип через читающую операцию или создай тип отдельной операцией.
• Уровень обязателен почти везде: либо адресуй существующий `{{"by":"name","value":"<имя>"}}`, либо создай его в этой же программе.
• Своё адресуется ссылкой: то, что программа создаёт сама, берётся как `{{"by":"ref","value":"<id операции>"}}`, а не по имени.

ГДЕ ВЗЯТЬ ОСТАЛЬНОЕ (не угадывай — спроси): полный контракт операции — `spec("<имя>")` внутри `program_py`; СПИСОК ИМЁН по разделам проекта — `spec()` без аргумента; настоящий проект — поле `example`; проверить замысел без записи — поле `rehearse`; что уже создано этой сессией — поле `created`.

Не отвечай «не могу»: если задача кажется невыполнимой — она выполнима программой."""
    if len(текст) > BRIEF_DESCRIPTION_LIMIT_CHARS:
        # Потолок — прибор, а не пожелание: он краснеет у автора, а не у
        # владельца на живом ходу.
        logger.error("краткое описание revit_ir длиннее потолка: %d > %d",
                     len(текст), BRIEF_DESCRIPTION_LIMIT_CHARS)
    return текст


def build_tool_description() -> str:
    """The `revit_ir` description string, generated so it cannot go stale."""

    reading = sorted(n for n, op in spec.OPS.items() if not op.writes_model)
    lines = [
        "Типизированная IR-программа для Revit: компилятор владеет единицами, "
        "версиями API и транзакциями, а любое постусловие проверяется на живой "
        "модели ПОСЛЕ создания — молчаливо-неверный результат невыразим.",
        "",
    ]
    lines.extend(_two_input_forms())
    lines += [
        "",
        f"ЧИТАЮЩИЕ ({len(reading)}): " + ", ".join(reading) + ". "
        "`query_list` возвращает id элементов — для выделения передай их в "
        "show_elements. `query_types` перечисляет {id, name} закрытого пула типов.",
        "",
        # 🔴 CLOSED DICTIONARIES TRAVEL IN FULL, AND THIS WAS BOUGHT BY THE
        # 16.08.2026 MEASUREMENT.
        #
        # An overnight rig, 16 attempts across three nights: **95 of 221
        # files written by the subject build nothing at all — this is
        # RECON** (`spec()`, `pools`, `query_*`). Forty-three percent of the
        # work goes into figuring out names. The reason was right here: the
        # language presented itself by NAMES and did not present itself by
        # VALUES. In this description (27 548 characters) the word `kind` —
        # the required parameter of `query_count`/`query_list` — appeared
        # NOT ONCE, and of the 53 kinds in the closed table exactly ONE was
        # named as a separate word. The only channel to the values —
        # `spec()` — is rationed: one lookup per script, the printout cut
        # off at 4000 characters.
        #
        # The prod refusal corpus confirms the cost from the other side:
        # `KIR-G001 count.kind` is the top offender for failing to teach, 16
        # repeats of the same refusal within a SINGLE turn.
        #
        # THE COST OF THE FIX WAS MEASURED, NOT ESTIMATED: 27 548 -> 30 330
        # characters, **+2 782, that is +10.1%**, and the dictionaries cover
        # 53 of 53 kinds and 35 of 35 pools (it used to be 1 and 2). The
        # first draft of this comment wrote "~4%" AS AN ESTIMATE and was off
        # from the instrument by a factor of two and a half — a number set
        # by eye next to a measurable one is itself a named defect. The
        # trade is stated honestly: ten percent more description length
        # against forty-three percent of the work going into recon.
        #
        # GENERATED FROM THE REGISTRY, not written alongside it: a list
        # that must agree with the registry has to BE the registry seen
        # from a different angle.
        "ЗАКРЫТЫЕ СЛОВАРИ — ЭТИ ИМЕНА НЕЛЬЗЯ ВЫДУМЫВАТЬ, ДРУГИХ НЕТ:",
        f"  kind ({len(spec.KINDS)}) — что перечисляют query_count/query_list: "
        + ", ".join(sorted(spec.KINDS)) + ".",
        f"  pool ({len(spec.OPS['query_types'].params[0].choices)}) — каталог "
        "типов у query_types; имена НЕ равны видам (`wall` -> `wall_types`), "
        "весь список даёт `spec(\"query_types\")`, а ошибка в имени сразу "
        "возвращает ближайшее.",
        "",
        "ПИШУЩИЕ (" + str(sum(1 for op in spec.OPS.values() if op.writes_model))
        + "), ПО РАЗДЕЛАМ ПРОЕКТА:",
    ]
    # The grouping belongs to the registry, not here: the same summary is
    # printed by `course.spec()` into the receipt, and two independent
    # calculations would drift apart on the very first new op — silently,
    # because both sides would keep looking correct.
    #
    # BY SECTION, NOT BY `capability` (09.08). Before this day, an internal
    # registry field was printed here: `element`, `element/mep_system`,
    # `category/element: create_column, create_wall`, `room_space`. Read
    # through the EYES OF A USER of the description — and this is the first
    # thing that gets in the way: nothing in the text explains why
    # `create_wall` is separated from `create_floor`. The answer was that a
    # compiler-internal field had leaked onto the surface, while the work is
    # actually organized BY SECTION, each with its own executor. Regrouping
    # the same names costs ZERO characters, and its section is derived from
    # the data rather than set by hand: op -> census category (the
    # acceptance judge) -> section (the `registry_base.DISCIPLINES`
    # dictionary, there is no second one in the package).
    for discipline, names in spec.ops_by_discipline(writes=True):
        lines.append(f"  {spec.DISCIPLINE_RU[discipline]}: " + ", ".join(names))
    undecided = spec.ops_without_discipline(writes=True)
    if undecided:
        # AS ITS OWN HEADING, NOT INTO "shared". `shared` in the sections
        # dictionary means "belongs to everyone", and dumping the
        # un-derived ones there would amount to asserting that
        # `create_truss` is shared across all sections. A gap in the
        # accounting that is named out loud gets closed; one that is hidden
        # lives on.
        #
        # 🔴 THE ATTEMPT TO MOVE THE NAMES INTO `spec()` WAS ROLLED BACK ON
        # 15.08.2026, AND THE ROLLBACK MATTERS MORE THAN THE ATTEMPT. The
        # row costs 482 characters on every turn and matches BYTE FOR BYTE
        # what `spec()` prints — the saving looked free. It is not free:
        # `test_every_op_is_named` requires that EVERY op in the registry be
        # named in the permanently loaded text, and without this row 22 ops
        # disappeared from the model's field of view entirely. The ratchet
        # went red on the very first run.
        #
        # The lesson is general, not about this row: DUPLICATION BETWEEN AN
        # EXPENSIVE DOOR AND A CHEAP ONE IS NOT ALWAYS SURPLUS. Here the
        # expensive door carries COMPLETENESS ("the registry is closed, here
        # it all is"), and the cheap one carries DETAIL. Removing the copy
        # from the expensive one means dropping completeness, not saving
        # anything.
        lines.append("  РАЗДЕЛ НЕ ВЫВЕДЕН (оп от этого не хуже): "
                     + ", ".join(name for name, _why in undecided))
    if UNPROVEN:
        # THE NAME HERE, THE REASON IN `spec(op)` (09.08.2026). The model
        # must know that an op is unproven BEFORE it chooses it — so the
        # list stays in the permanently loaded text. The reason is needed
        # only once the op is already chosen, and it arrives as that same
        # op's docstring (`dsl._docstring`), that is, it is paid for exactly
        # on the turn it is asked about. The measurement that forced the
        # move: at 62 operations the description stood at 30 440 against a
        # ceiling of 30 000, and the ceiling equals the declared ~10 000
        # tokens of context and is forbidden to raise.
        lines.append("")
        # THE BODY WAVE'S MOVE HERE IS ABSORBED, NOT REJECTED (merge 09.08).
        # It was grouping the list BY REASON, so that one justification
        # would not be printed three times; once the reasons moved into the
        # docstring entirely, there was nothing left to print — grouping by
        # matching text would have remained code with no subject left to
        # act on. The wave's saving is captured in full and with room to
        # spare.
        # 🔴 THE JOURNAL ASKS THE CORPUS, NOT JUST ITSELF (17.08.2026).
        #
        # The owner's question: "you said 70 of 70, and now 29 are unproven
        # — from old memory?" A re-measurement of the witness corpus within
        # the same hour: **2131 records, 2040 made it to Revit, 65 of the
        # registry's 70 operations have a LIVE trace, five have none**. Yet
        # the journal was declaring 29 unproven, that is, **24 records had
        # outlived their own truth** and were telling the model "do not rely
        # on this" about things already built live: dimensions,
        # `DirectShape`, topography, flexible runs, the multistory staircase,
        # spaces, the extrusion roof, the truss, the apron.
        #
        # This is exactly the kind of defect this file's own docstring
        # already names twice ("a record that outlived its own truth"), and
        # both times before it was fixed BY HAND. Hands do not scale:
        # re-reading the journal can only be done by someone who has the
        # corpus, and the corpus is machine-local and under mode 600.
        #
        # So this is not a third manual cleanup but the REMOVAL OF THE
        # CAUSE: the rendering asks the corpus where it exists, and silently
        # leaves the journal as-is where it does not (an open-source
        # delivery, someone else's machine). The corpus being unreachable
        # does NOT mean "everything is proven" — it means "there is nothing
        # to ask", and then the full journal is printed, as before.
        shown = sorted(_unproven_minus_live_corpus())
        if shown:
            lines.append("НЕ ОПИРАЙСЯ БЕЗ ПРОВЕРКИ (причина — в spec(<оп>)):")
            lines.append("  " + ", ".join(shown))
    lines.append("")
    # THE ADDRESS OF WHAT WAS PUSHED OUT IS NAMED HERE, AND THIS IS NOT
    # DECORATION. Knowledge with no path to it from the permanently loaded
    # text is dark BY CONSTRUCTION — the same reachability law the pointer
    # to the guide lives by. The traps of a single op (`OP_NOTES`) moved
    # into the docstring; the door to them costs one line.
    # THE HEADING WAS TRIMMED ON 24.08 FOR THE SAKE OF FOUR NAMES IN THE
    # UNPROVEN LIST. Measurement: 44 characters of headroom remained under
    # the ceiling, four honest names cost 78. The ceiling is paid for on
    # EVERY call and is forbidden to raise (see the 09.08 argument above),
    # so a REDISTRIBUTION was taken, and taken from where the text explains
    # INNER WORKINGS rather than settling a choice of form: the shorter
    # wording says the same thing. Not a single paid-for trap was touched.
    lines.append("ЛОВУШКИ ВЫБОРА (замерены живьём; ловушка конкретного опа — "
                 "в spec(<оп>)):")
    lines.extend(f"  • {note}" for note in NOTES)
    lines.extend(f"  • {item}" for item in CONSTRAINTS)
    # Judgment calls live in their own module and their own block: NOTES
    # answers "what is non-obvious here", the skill answers "how to think".
    # The separation is mechanical, held by
    # test_skill.test_skill_and_notes_do_not_overlap.
    lines.append("")
    lines.append(build_skill_text())
    return "\n".join(lines)


__all__ = ["BUILT_BUT_ACCEPTANCE_BLIND", "CONSTRAINTS", "NOTES", "OP_NOTES", "UNPROVEN", "UNPROVEN_GAP",
           "build_tool_description", "example_schema", "program_py_schema"]
