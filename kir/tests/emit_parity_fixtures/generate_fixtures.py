"""Emit-parity fixture generator and explicitly reviewed reference baselines.

CURRENT PIN (2026-09-07, E-2): 2361 keys. The latest record is
e2_migration_2026_09_07.json: exactly 24 endpoint-expectation hash changes in
two fixtures (12 atomic + 12 per_op), 1 golden of 75, 0 added, 0 missing, 21
refusals as before — the final witness of a created wall now expects the place
the SAME PROGRAM legally moves it to. Its parent is e1_migration_2026_09_07.json.

PREVIOUS PIN (2026-09-06, D-1): 2361 keys. The latest record is
d1_migration_2026_09_06.json: exactly 12 create_wall_type reuse-guard hash
changes in one fixture, 0 golden files and 0 marker literals (no corpus
program carries a lineage). Its parent
c1_migration_2026_09_06.json holds 309 per_op gate-guard hash changes,
2052 unchanged values, 0 atomic keys, 0 of 75 golden files, no added or
missing keys and no changed refusal markers. Its parent
capture_migration_2026_09_06.json holds the 642 capture/readback changes,
and ITS parent baseline_migration_2026_09_06.json the earlier 726-of-2343
behavior refresh plus 18 macro-only per_op additions.
Reverse-chain tests reconstruct those historical manifests; current source
pins belong to the latest record, not a parent's historical source claims.
This is NOT native backward-compatibility proof. Exact keyset coverage and
the bounded capture/C-1 counterfactuals are checked by
test_emit_model_byte_parity.

HISTORICAL DESIGN ACCOUNT (the counts/commits below describe earlier waves):

Run ONCE against the PRE-refactor emitter (base prod-live 4e5cf13d) to freeze
the "old bytes" of the whole emission corpus; `test_emit_model_byte_parity`
then recomputes every emission against the frozen hashes after each migration
step.  ANY divergence fails the wave — "update the golden" is forbidden here.

Corpus (maximal EMITTER coverage, not just the gate):
  * test_golden.PROGRAMS               — every reviewed golden program;
  * test_emitter_scope_contract.PROGRAMS — the per-family corner fixtures that
    deliberately exercise every optional branch of all 26 emitters;
  * the gate runner's authoring programs (auth_wall/auth_mixed/auth_stack/
    auth_grid_array/auth_stairs/auth_native_group/mod_setparam_delete shapes),
    reassembled from the same committed sources;
  * seeded query PBT programs (test_pbt.gen_program, gate SEED) + all-kinds +
    query_types pools (query family: unaffected by the post refactor, kept as
    cheap insurance);
  * test_emission_guard_contract.PROGRAMS — the guard-site corpus (2026-07-28):
    line-tracing every emitter showed the corpus above never reached 11 of the
    105 op-local guard-sites, so a change inside one of them moved no frozen
    byte at all.  These programs close that hole (105/105 reached).

Modes: atomic AND per_op isolation for every write program (per_op rewrites
post gating — both paths must stay byte-identical), x all 6 Revit versions
(respecting each fixture's __min_ver__).

DECISION (документировано): fixtures are SHA-256 HASHES, not full files —
~1500 emissions x 10-30KB would be tens of MB of noise; hashes give the same
guarantee.  For debugging a mismatch, run this script with --dump DIR to write
the CURRENT emissions as files and diff against a pre-change --dump.

Determinism: seeded PRNG only, sorted keys, no clocks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import random
import sys
import tempfile

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_parity_queue.jsonl"))

from kir import ground as ground_mod  # noqa: E402
from kir import spec  # noqa: E402
from kir.authoring import emit_program  # noqa: E402
from kir.compiler import _parse_and_check, compile_program, plan_program  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kir.tests.test_emission_guard_contract import (  # noqa: E402
    PROGRAMS as GUARD_PROGRAMS,
)
from kir.tests.test_emitter_scope_contract import (  # noqa: E402
    PROGRAMS as SCOPE_PROGRAMS,
)
from kir.tests.test_golden import PROGRAMS as GOLDEN_PROGRAMS  # noqa: E402
from kir.tests.test_pbt import gen_program  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")
GATE_SEED = 62026
N_PBT = 25

FIXTURE_PATH = pathlib.Path(__file__).parent / "corpus_hashes.json"
BASELINE_MIGRATION_PATH = FIXTURE_PATH.with_name("baseline_migration_2026_09_06.json")
CAPTURE_MIGRATION_PATH = FIXTURE_PATH.with_name("capture_migration_2026_09_06.json")
C1_MIGRATION_PATH = FIXTURE_PATH.with_name("c1_migration_2026_09_06.json")
D1_MIGRATION_PATH = FIXTURE_PATH.with_name("d1_migration_2026_09_06.json")
E1_MIGRATION_PATH = FIXTURE_PATH.with_name("e1_migration_2026_09_07.json")
E2_MIGRATION_PATH = FIXTURE_PATH.with_name("e2_migration_2026_09_07.json")
E3_MIGRATION_PATH = FIXTURE_PATH.with_name("e3_migration_2026_09_07.json")

# 🔴 THERE ARE ZERO EXEMPTIONS RIGHT NOW, AND THIS IS NOT A LOSS OF HISTORY
# — READ BELOW.
#
# `INTENDED_CHANGES` exempts a key from comparison. The exemption is needed
# only while the key DIVERGES from the frozen one; after a refreeze it
# matches, and the entry stops permitting anything — but it KEEPS DISABLING
# the comparison. Measured 20.08.2026 right after a refreeze: of 81 entries,
# 80 are REDUNDANT, still carrying ZERO, and `query:all_kinds_` was not even
# covering a single key before that (the key schema changed, as its own text
# says). Leaving them would mean keeping eighty spots where the ratchet
# stays silent on a REAL discrepancy.
#
# So the texts moved into `EMISSION_CHANGE_LOG` — HUMANS read those, and
# that is where all the value is: every entry explains why the emission
# changed once (canon: what is retracted is NAMED as wrong, not erased — it
# carries the sample of the previous form). The mechanism is still in
# place: a new discrepancy is exempted by a new entry here, with a reason
# and its OWN replacement pin, as before.
INTENDED_CHANGES: dict[str, str] = {}

# History of emission changes. Does NOT participate in the comparison — see
# the block above.
EMISSION_CHANGE_LOG: dict[str, str] = {
    # ── 06.09.2026, NIGHT: D-1. 12 EMISSIONS, ONE FIXTURE, ONE FORM
    #
    # WHAT WAS BROKEN. The type-ownership marker is built from the program's
    # stamp, and the stamp was a SHA1 of the ENTIRE grounded program. So the
    # address of an untouched type was moved by a NEIGHBOR's edit: measured
    # — a neighboring wall's height going 3000→3100 gives
    # `kir:29d89dc8:WT1` → `kir:2f2eb590:WT1`, and republishing the same
    # residential complex was refused by the ownership guard. The guard was
    # right; the ADDRESS was wrong.
    #
    # WHAT IT BECAME. The envelope can carry the authoring program's stable
    # identity (`lineage`; on the Project path this is `project_id`, living
    # through all revisions). If it exists, the address is built from it; if
    # not, the previous hash BYTE FOR BYTE. So not a SINGLE marker literal
    # in the frozen corpus moved: no fixture carries an identity.
    #
    # AND THE SECOND THING, WITHOUT WHICH THE FIRST IS DANGEROUS. A stable
    # address by itself does not grant the right to overwrite an existing
    # type (the owner's word). Recreation at a matching address remains a
    # READ, and a discrepancy in composition became a NAMED refusal at the
    # operation stage — before a single consumer of the type. That is the
    # entire frozen diff.
    #
    # COUNT: 12 of 2361, all `scope:catalog_wall_type` (6 versions × 2
    # isolations), goldens 0 of 75, marker literals 0, keys added and
    # vanished 0. Replacement pin that can turn red:
    # `kir/tests/test_a_stable_address_is_not_permission.py` (20 checks,
    # including a control under the exact counterfactual). No exemptions
    # added.
    "06.09.2026 D-1 stable type address and reuse contract":
        ("Machine audit: d1_migration_2026_09_06.json. Exactly 12 keys of "
         "2361, one fixture, 0 goldens, 0 marker literals. The ownership "
         "address now comes from the authored program's stable lineage when "
         "the envelope carries one; a bare program is unchanged byte for "
         "byte. A matching address is read-only: a different composition is a "
         "named refusal at the operation stage. Updating an existing type is "
         "not implemented and is only named. No exemptions."),
    # ── 06.09.2026, EVENING: C-1. 309 EMISSIONS, ONE FORM, 399 LINES
    #
    # WHAT WAS BROKEN. `__post` is a list for THE WHOLE program, and in
    # `report` mode (and `per_op` forces it by construction) it travels
    # whole into `__results["postcondition_violations"]`. The operation-
    # stage gate was throwing a refusal, LEAVING its own lines in that
    # list: the op's SubTransaction rolled back, the element did not exist,
    # and its message kept being counted as a postcondition violation of
    # the COMMITTED program. The consumer
    # (`bridge_result.assess_write_result`) declared the whole record
    # VIOLATED — a false red on the valid part of a mass rebuild, and a
    # signal to the agent to fix something already rolled back.
    #
    # WHAT IT BECAME. The message is captured into a local variable BEFORE
    # deletion (`String.Join` materializes the lazy `Skip` immediately),
    # then EXACTLY the range for this op, `[__operationPostStart_s, Count)`,
    # is removed, and only then is the refusal thrown with the already-
    # captured message. Neighbors' lines sit BELOW the marker and are not
    # touched; the evidence is not lost — it travels into
    # `__results[oid]["refused"]` via `__KirOpRefusal`.
    #
    # THE COUNT MATCHED EXACTLY, AND WAS CHECKED TWICE BY DIFFERENT MEANS:
    #     per_op   309 / 921    ← exactly the emissions that have an
    #                             operation gate
    #     atomic     0 / 1419   ← there a refusal = `RollBack(); return
    #                             __Refuse`, i.e. an exit BEFORE
    #                             `if (__post.Count > 0)`; `__post` is not
    #                             published, no leak
    #     golden     0 / 75     ← goldens are compiled with atomic
    #     total    309, missing 0, extra 0, refusal markers 0
    # The "before/after" dump delta (2340 files) has EXACTLY ONE normalized
    # form and 399 changed lines — exactly as many as the gate blocks
    # counted by an independent corpus walk (399 of 399 `__post.Add` call
    # sites inside a SubTransaction body lie inside a gate block, 0
    # outside).
    #
    # A SECOND CARRIER, NOT IN THE CORPUS, IS NAMED, NOT SWALLOWED:
    # `disallow_wall_joins` writes to `__post` AFTER the gate (a de-join is
    # a record, not a throw, deliberately). This form is not frozen by any
    # key, and there the leak on a late refusal is closed by the
    # `__opPostStart_*` fence in `_wrap_create_per_op`; it does not affect
    # the frozen keys (empty `join_kill` -> the previous bytes).
    #
    # NO EXEMPTIONS (`INTENDED_CHANGES`) ADDED. Replacement pin that can
    # turn red: `kir/tests/test_a_refused_op_leaves_no_trace.py` (RED
    # before the fix on the `second_no_op` scenario, GREEN after), plus the
    # exact counterfactual `c1_counterfactual.without_c1_range_cleanup`,
    # with which the record restores the parent manifest BYTE FOR BYTE.
    #
    # WHAT IS NOT HERE: a live Revit, C# execution, or a Roslyn run under
    # this refreeze. The claim about the list's behavior is derived from
    # `List<string>` semantics and checked by a Python-side rig, not by
    # execution.
    "06.09.2026 C-1 per_op refusal range":
        ("Machine audit: c1_migration_2026_09_06.json. Exactly 309 per_op "
         "operation-stage gate guards of 2361 keys; 0 atomic keys, 0 golden "
         "files, no keyset movement, no refusal-marker change. A refused "
         "operation no longer leaves its message in the program-wide __post "
         "list that report mode publishes as postcondition_violations; the "
         "message is lifted into the refusal itself. Replacement pin: "
         "kir/tests/test_a_refused_op_leaves_no_trace.py. No exemptions."),
    "06.09.2026 reviewed foundation/type-assignment baseline":
        ("Machine audit: baseline_migration_2026_09_06.json. First refresh exactly "
         "726 reviewed-scope hashes of 2343, retaining 1617 and every refusal "
         "marker; then separately append macro-only per_op coverage. This is "
         "a reviewed current reference baseline, NOT proof of linewise legacy "
         "equivalence or native backward compatibility. No exemptions added. "
         "Replacement checks: created-element identity, type factory ownership/"
         "Length guards, consumer assignment runtime/API and witness staging. "
         "Exact keyset and reverse-migration checks prevent silent omissions."),
    # 31.08.2026: 1776 write emissions got a single typed carrier for
    # transaction status. Across all 68 reviewed goldens, the delta has
    # exactly three forms: the saved `RollBack()` result, that result's
    # field in a postcondition refusal, and the `Commit()` result's field in
    # a commit-refusal. No check and no operation was removed; the form is
    # held by CommitGateInvariants and two opposing serving tests for
    # typed/untyped rollback.
    "31.08.2026 typed transaction status":
        ("1776 write emissions: explicit RollBack/Commit status is carried "
         "by generated refusal payloads; pinned by CommitGateInvariants and "
         "HandlerOutcomes typed-vs-untyped rollback tests"),
    # ── 30.08.2026: 492 EMISSIONS, ONE FIX, THE COUNT MATCHED EXACTLY (S-07)
    #
    # 🔴 THE FREEZE STOOD RED FOR ONE COMMIT, AND THIS IS MY OWN LAPSE OF THE
    # SAME KIND WE ARE FIXING THIS ENTIRE MARATHON. In `9f8c9ba` I
    # regenerated three goldens and CHECKED THEIR DIFF BY NAME — but
    # `corpus_hashes.json` freezes the hashes of THOSE SAME goldens, i.e.
    # this is a SECOND CARRIER of the same knowledge, and it was left
    # unrefrozen. The ledger is fixed by THE SAME commit as the spot itself;
    # here the ledger is the hash file.
    #
    # WHAT EXACTLY CHANGED. `S-07`: the `pdf_underlay` predicate stopped
    # reading the EDITABLE type name (`__TypeNameOf(e).EndsWith(".pdf")`)
    # and now asks the source's KIND plus the path to the FILE ITSELF. For
    # this, a helper `__ImageTypeOf` was added to the preamble of query
    # programs, returning the whole `ImageType`.
    #
    # WHY THE NEW VERSION IS CORRECT: the user edits the type name, and
    # Revit itself appends page suffixes ("… .pdf - 1") and duplicate
    # suffixes ("… .pdf (2)") to it. Both forms were found in the live
    # corpus; the old predicate caught 2 underlays out of 21, i.e. it missed
    # 19 (90%). There is no "this is PDF" property in the API in any of the
    # six versions (checked against `RevitAPI.xml` 2021…2026), so
    # `Source != ImageTypeSource.Internal` and the `Path` extension are
    # asked instead.
    #
    # THE COUNT MATCHED, AND THIS IS CHECKED BY NUMBER, NOT BY ARGUMENT:
    #     query   324 / 324    ← the helper rides in the preamble of ALL
    #                             queries
    #     pbt     150 / 150    ← the same query corpus
    #     golden   18 / 837    ← EXACTLY three query goldens x 6 versions
    #     gate      0 /  96    ← untouched
    #     guard     0 /  96    ← untouched
    #     scope     0 / 822    ← untouched
    #     total   492, and 0 missing, 0 extra
    #
    # THE DELTA WAS READ BY EYE AND HAS EXACTLY ONE FORM: 15 helper lines on
    # every query emission; `pdf_underlay_count` has 17 — the same 15 plus
    # the predicate itself. Not one foreign line, not one check removed.
    # Checked against the emission assembled by the compiler from
    # `9f8c9ba^`.
    #
    # NO EXEMPTIONS (`INTENDED_CHANGES`) ADDED: the count matched, nothing
    # to hide. The replacement pin is written and can turn red —
    # `kir/tests/test_an_underlay_is_not_found_by_its_label.py`, six
    # assertions, a FAIL control run (returning the predicate by name -> 3
    # reds).
    # ── 27.08.2026: 24 EMISSIONS, ONE FIX, THE COUNT MATCHED EXACTLY
    #
    # 🔴 THE FREEZE STOOD RED FOR 18 COMMITS, AND THIS IS A FORM THIS SAME
    # JOURNAL HAS ALREADY NAMED. The last refreeze was `f58028cd`, 64
    # commits before HEAD, with the heading "three emission fixes moved a
    # SECOND freeze that nobody remembered." The curtain wall emission
    # changed in `2350024d` (18 commits back) — i.e. AFTER that refreeze,
    # and the second record was again left untouched. The form returned 46
    # commits later, on the same day. The chosen suite is declared bound to
    # be green ALWAYS, and the ledger of known reds is empty: meaning it was
    # not run this whole time. A net that is not cast catches nothing.
    #
    # THE CAUSE WAS LIFTED FROM GIT, NOT FROM THE TREE (otherwise a mixture
    # would have been described):
    #   2350024d^   0 diverged   — the freeze matched EXACTLY
    #   2350024d    24 diverged  — the curtain-grid axis fix
    #   8d124d8f    24 diverged  — the second curtain-wall fix added NOT ONE
    #
    # ONE FORM, 24 emissions — THE DIRECTION AXIS WAS NAMING THE WRONG
    # COORDINATE.
    #   `2350024d`: with the coordinate occupied, the `create_curtain_grid_line`
    #   refusal wrote «ПРИЧИНА НЕИЗВЕСТНА». The fix added a helper,
    #   `__KirGridOcc`, to the emission (+120 golden lines): it reads the
    #   existing grid lines, names the axis horizontal or vertical, and
    #   labels the coordinate BY AXIS, rather than one label for both; an
    #   unread distance is printed as a word and sorted last, rather than as
    #   «-1 мм».
    #
    # THE COUNT WAS CHECKED INDEPENDENTLY, NOT TAKEN ON FAITH. The corpus
    # has 240 programs; the op `create_curtain_grid_line` occurs in EXACTLY
    # two — `golden:auth_curtain_grid_lines` and `scope:curtain_grid_line` —
    # and EXACTLY those diverged: 2 × 6 versions × 2 isolations = 24, 4 per
    # version with not a single skew. The other 238 programs and 2289
    # previous keys stayed BYTE FOR BYTE.
    #
    # 🔴 CONFIRMATION OF NARROWNESS THAT CANNOT BE OBTAINED BY ARGUMENT:
    # neighboring curtain-wall programs DID NOT DIVERGE —
    # `golden:auth_curtain_cell_named_type` (carries `set_curtain_panel`),
    # `scope:curtain_cell`, `query:kind_curtain_mullion`,
    # `query:kind_curtain_panel`. One op was fixed, and its subject-matter
    # neighbors proved that by staying still.
    #
    # THE PIN IS IN PLACE AND GREEN: `test_golden.py` compares the same
    # bytes, and the golden `auth_curtain_grid_lines.golden.cs` was updated
    # ALONGSIDE the fix and read by a human. So the emission had been pinned
    # this whole time; only the second, cruder record of the same fact —
    # this one — had diverged.
    #
    # 🔴 THE FREEZE WAS ALSO ALREADY `part of range` ON TOP OF THAT. It held
    # 2313 keys, the corpus was returning 2325: TWELVE emissions arrived
    # afterward and were not compared against anything. All twelve are
    # `scope:room_upper_offset` (6 versions × 2 isolations), the new
    # room-height op from 26.08. We freeze with the FULL corpus (2325), and
    # they are named here by name, not silently swallowed. The same form
    # stood on 20.08 at the scale of 1078 out of 2159.
    #
    # WHAT WAS NOT DONE HERE — I NAME IT, NOT HIDE IT: a live Roslyn run on
    # 2021..2026 under this refreeze was NOT performed. The owner's decision
    # on 27.08 is to freeze on proof of stillness and narrowness, without
    # waiting for the gate. Past entries in this journal included the gate;
    # this one does not.
    #
    # No exemptions (`INTENDED_CHANGES`) added: the count matched, nothing
    # to hide.
    #
    # ── 25.08.2026, EVENING: THREE FIXES, 48 EMISSIONS, AND THE COUNT
    # MATCHED EXACTLY
    #
    # 48 discrepancies, and they break down into FOUR keys × 12 (six
    # versions × two isolations) — i.e. exactly three of today's emission
    # fixes:
    #
    #   golden:arch_railing_path  12 |  scope:arch_railing_path      12
    #   scope:catalog_wall_type   12 |  scope:join_new_to_existing   12
    #
    # THE COUNT WAS CHECKED INDEPENDENTLY, NOT TAKEN ON FAITH. The corpus
    # has 239 unique programs; our ops (`create_railing`, `create_wall_type`,
    # `join_elements`) occur in EXACTLY the ones listed, and the other 235
    # programs stayed BYTE FOR BYTE.
    #
    # 🔴 AND THE DECISIVE CONFIRMATION OF NARROWNESS THAT CANNOT BE OBTAINED
    # BY ARGUMENT: `arch_railing_hosted` DID NOT DIVERGE. Only the
    # `variety=path` branch (`_emit_railing_path`) was fixed, and the
    # neighboring branch of the same op proved that by staying still. Had
    # it diverged, the fix would have been wider than declared, and we
    # would have learned that only live.
    #
    # FORM 1, 24 emissions — THE RAILING'S BOUNDING-BOX OBLIGATION WAS
    # LIFTED.
    #   The witness compared the BODY's bounding box (posts, handrail)
    #   against the LINE of the authored path. Live: 3 built, 20 accused,
    #   140 accompanying operations died by rollback. Measured: y
    #   920975..921050 against the authored 921000..921000 — −25 and +50
    #   at a tolerance of 50.0, one side sitting EXACTLY on it, and 50 mm in
    #   internal feet is not a binary fraction: the witness was
    #   NON-DETERMINISTIC. The obligation was LIFTED, not stretched by
    #   tolerance; the path's ends are proven more precisely by the
    #   neighboring `path_points` (±1 mm versus ±50). Live afterward: 803 of
    #   803. Golden diff — exactly −8 lines, the bbox block.
    #
    # FORM 2, 12 emissions — THE AXIS OF THE WALL TYPE'S `layers` CLAUSE.
    #   The clause reads `CompoundStructureLayer.Width`/`Function` —
    #   geometry — but the witness's messages ended in «(re-read)» instead
    #   of «(geometry, re-read)», and `serving._axis_marked` did not find
    #   them. A geometry violation was sliding onto the semantic axis, while
    #   the geometric one stayed GREEN. The third carrier of this form (the
    #   first two were `create_wall.arc`, 22.08). Three message spots were
    #   changed, check behavior untouched.
    #
    # FORM 3, 12 emissions — A NAMED OUTCOME FOR `join_elements`.
    #   Revit carries «already joined» and «cannot be joined» as ONE
    #   `ArgumentException`, distinguishable only by text. The second is the
    #   op's MAIN case: joining what a PAST program built (measured 18.08:
    #   the join succeeds within the same transaction, but not after
    #   commit). It was drowning in a general catch, indistinguishable from
    #   an emission defect. Now the branch is named: «нет общей грани» — A
    #   FACT ABOUT THE PAIR, not an emission refusal; everything else keeps
    #   the previous text and preserves `ex.Message` verbatim.
    #
    # GATE: each of the three fixes was run through live Roslyn on
    # 2021..2026 — 6/6 for all three. No exemptions (`INTENDED_CHANGES`)
    # added: the count matched, and there is nothing to hide.
    #
    # ── 25.08.2026: FOUR FORMS, AND THREE OF THEM WERE RED BEFORE THIS FIX
    # 528 discrepancies against the freeze feb2b0d2 (24.08 12:03). They
    # split as follows:
    #
    #   492  level-read chain      |  36  red SINCE 24.08, not this fix
    #
    # THE SPLIT WAS OBTAINED BY A RUN, NOT BY ARGUMENT. The corpus was
    # emitted twice: with the OLD compiler preamble, restored from `git show
    # HEAD:…` into memory, and with the new one. With the old one, exactly
    # 36 diverge — so they are not ours. Vanished and new keys are ZERO in
    # both runs (2313 = 2313).
    #
    # FORM 1, 492 emissions — PROVEN BYTE FOR BYTE, not by eye.
    #   The query door had ITS OWN level-read chain over four
    #   BuiltInParameters against seven at the authority
    #   `revit_read_helpers`, and it branched on `!HasValue` instead of
    #   `__holdsLevel` (the parameter must be of ElementId kind). On a beam,
    #   the chain stopped at SCHEDULE_LEVEL_PARAM (HasValue=True,
    #   AsElementId=-1) and returned an empty string. Measured 03.08: 2367
    #   beams, 116 stairs, 21 railings with level_id=null — the query
    #   `where level_name=…` silently dropped all of them.
    #
    #   Proof: in EACH of the 492 current emissions the new block was
    #   replaced with the old one, taken verbatim from `git show
    #   HEAD:compiler.py`, and the sha256 matched the FROZEN one. 492 of 492
    #   matched, 0 did not. So the delta is exactly one substitution, with
    #   no other changes in them. Own pin:
    #   `test_level_read_chain.ТретийНосительЦепиУровняСнят`, was RED before
    #   the fix (two tests), green after.
    #
    # FORMS 2-4, 36 emissions — ALREADY-COMMITTED FIXES, red since 24.08.
    #   The delta was read as a diff against the tree extracted by `git
    #   archive` at the commit of the last freeze. 12 emissions each (6
    #   versions × 2 modes):
    #
    #   ×12  the roof and floor type is taken FROM THE DOCUMENT:
    #        `doc.GetElement(new ElementId(400))` -> `GetDefaultElementTypeId`
    #        (the OPS_WITH_DOC_DEFAULT_TYPE wave; pinned by its own tests)
    #   ×12  the `create_floor_plan` stamp moved under `if (__vpnew_FP1)`:
    #        the A5 ownership stamp is no longer placed on a view the op did
    #        NOT create (audit finding, ledger 2026-08-24e, item 9)
    #   ×12  `create_wall_type` no longer adopts someone else's type:
    #        instead of `FirstOrDefault(Name == …)`, the choice is ONLY
    #        among types carrying the `kir:` stamp, otherwise a typed
    #        refusal «создан не KIR» (blocking finding Ш1.1; pin —
    #        `test_families`)
    #
    # 🔴 AND THE MAIN THING THIS SAYS ABOUT US: the ratchet was red for A
    # WHOLE DAY and went unread, because it is not in `tools/gold_path.py`.
    # This is the second such case on 25.08 — the first was the reverse-
    # contracts ratchet, red since 24.08 12:03 for the same reason (the
    # decompile package does not run, due to OOM). An instrument nobody
    # RUNS equals one that does not exist.
    # ── 24.08.2026: TWO WITNESSES WERE PREDICTING BY A DIFFERENT LAW THAN
    # THEY WERE READING
    # 78 discrepancies against the freeze b5283555 (23.08), and they split:
    #
    #   66  caused by this fix      |  12  red SINCE 23.08, not ours
    #
    # The split was obtained not by argument but by running the corpus
    # TWICE — with the old half of both witnesses and with the new one
    # (2301 emissions each time, vanished and new keys ZERO). The delta was
    # read as a LINE-BY-LINE diff and has EXACTLY TWO forms:
    #
    #   54  sketch signature   `golden:auth_contour_*`, `scope:*` and
    #                          neighbors
    #   12  roof rise          `golden:roof_gable_slopes` x 6 versions x 2
    #                          isolations
    #
    # FORM 1 — VERTEX ORDER. `loops_payload_expected` was sorting the
    # ALREADY-FORMATTED STRINGS, while C# sorts the pairs
    # `__slv.Sort(__KirCanonCmp)` NUMERICALLY. The two halves matched
    # exactly up to the first vertex of a different DIGIT COUNT: «12000» is
    # lexicographically SMALLER than «8000», numerically LARGER. The very
    # first ring to reach Revit (0..6000 x 8000..12000) rolled back the
    # program with «sketch loops mismatch» on geometry that matched TO THE
    # MICRON. The previous pin
    # (`test_python_and_csharp_round_by_the_SAME_law`) pinned equality of
    # ROUNDING and never asked about ORDER — half the law with no guard.
    # Replacement pin: `test_python_and_csharp_ORDER_by_the_same_law`.
    #
    # FORM 2 — ROOF RISE. `_expected_roof_rise_mm` computed the rise as "the
    # distance from the ridge to the FAR vertex x tan", but opposing slopes
    # meet IN THE MIDDLE. A live-Revit measurement on 24.08 on a
    # 1335x1080 mm roof with three ridges at 16.699 degrees: 182.9 mm was
    # built, the witness demanded 307.8 — RED ON A CORRECT ROOF; 3 of 6
    # gable roofs were rolling back the entire K3 port (74 operations). The
    # prediction was replaced by the LOWER ENVELOPE. For the three
    # previously green ones the threshold did not move (272.6->262.2,
    # 166.8->166.7, 270.7->270.7), for the three red ones it settled below
    # the measurement; strictness stays intact — the threshold scales with
    # the tangent, and a roof at 38 degrees instead of 45 stays red (checked
    # by the pin). In the bytes you can see exactly this: «не менее 3290.9
    # мм» became «не менее 1645.4 мм» — EXACTLY HALVED, as predicted by two
    # opposing slopes meeting. Plus the verdict now PRINTS the measured
    # value: on a postcondition violation the transaction rolls back, and no
    # one will see the numbers. Replacement pin:
    # `RoofRiseIsTheLowerEnvelope`, five checks, including a halving control
    # and a strictness control.
    #
    # 🔴 12 KEYS THAT ARE RED FOR REASONS OTHER THAN US, AND THIS IS NAMED,
    # NOT SILENTLY ABSORBED. `scope:catalog_wall_type` x 6 versions x 2
    # isolations also diverges against the OLD half, i.e. it was already red
    # before this work. Commit b5283555 (23.08) fixed `authoring.py` AND
    # refroze the fixture in ONE move, and after it NOT A SINGLE commit
    # touched the emission (checked with `git log b5283555..HEAD --
    # authoring.py ops_families.py` — empty). So the freeze in that commit
    # fell behind its own fix. Here they are aligned together with the
    # rest; if something further is behind them, the next ratchet will show
    # it, not silence.
    #
    # 🔴 THE SECOND FREEZE OF THE SAME DAY — AN ADDITION OF KEYS, NOT A
    # DISCREPANCY. The fixture `scope:catalog_material` (12 keys: 6 versions
    # x 2 isolations) entered the corpus together with the `transfer_material`
    # op. Zero discrepancies: the previous keys matched byte for byte, only
    # new ones were added. The fixture was not set up "for completeness" —
    # the scope contract WOULD HAVE CAUGHT a defect the emitter stumbled on:
    # the helpers `__nm_`/`__col_` sat in the witness's `reader_cs` and did
    # not survive to the receipt (CS0103 on all six versions, both
    # isolations).
    # ── 22.08.2026: A MUTATION GREW A CIRCLE OF CONSEQUENCES ──────────────
    # 60 discrepancies, FIVE keys x 6 versions x 2 isolations:
    #     gate:mod_setparam_delete          delete
    #     golden:modify_setparam_delete     delete
    #     scope:modify                      delete
    #     golden:auth_move_and_change_type  move_elements
    #     scope:move_and_change_type        move_elements
    # The composition was checked by a corpus WALK, not by eye: of 236
    # programs, `move_elements`/`delete` carry exactly these five, and
    # exactly those diverged. Vanished and new keys are ZERO (frozen 2277,
    # current 2277).
    #
    # THE CAUSE. Both mutations' witness spoke ONLY about its own target,
    # while the mutation's effect lives in its NEIGHBORS. Measured 22.08
    # against the live `serving._witness_for_success`: of the registry's six
    # mutations, `move_elements` is the ONLY ONE whose `unwitnessed_axes` is
    # empty, i.e. the only one whose receipt claimed FULL coverage. The
    # claim was green BY CONSTRUCTION: the neighbor's axes are not in the
    # axis list at all, so nothing was counted as unchecked either.
    #
    # WHAT EXACTLY CHANGED IN THE BYTES — WORKED OUT BY DIFFING BOTH
    # REFERENCES LINE BY LINE (104 lines added, 1 removed, not one previous
    # emission line touched):
    #   delete        1 declaration line, `List<string> __delalso_*`; a
    #                 `try` body capturing the RETURN of `doc.Delete` —
    #                 `ICollection<ElementId>`, everything Revit deleted as
    #                 fully dependent on the target — was previously
    #                 discarded; 3 receipt fields
    #                 collateral_count/_ids/_capped. ZERO extra Revit
    #                 calls.
    #   move_elements 6 declaration lines; THREE identical neighbor
    #                 snapshots (one per target): HostObject.FindInserts,
    #                 JoinGeometryUtils.GetJoinedElements,
    #                 Element.GetDependentElements+Dimension.IsLocked; TWO
    #                 new post guards (`hosted_inserts`,
    #                 `locked_dimensions`, both marked `(topology)`); 6
    #                 receipt fields.
    #
    # WHAT THE API MEMBERS ARE BACKED BY: real reference assemblies
    # (`data/api_surface/api_signatures_20NN.json`, 6/6 on all four
    # members) + a trap index (`FindInserts` 0 traps,
    # `GetDependentElements` 0, `Dimension.IsLocked` 0, `GetJoinedElements`
    # 3 — all three wrapped) + a LIVE compile service: 36 of 36 checks
    # (3 programs x 2 isolations x 6 versions), zero refusals. The probe has
    # a NEGATIVE CONTROL: `ICollection<ElementId> x = doc.Regenerate();`
    # fails with CS0029 on all six, i.e. the 6/6 above are not degenerate.
    #
    # 🔴 A BOUNDARY THAT MUST NOT BE HUSHED UP: what was bought is
    # COMPILABILITY, not executability. That inserts survive a host
    # transfer, and that the author's lock survives it, was NOT checked live
    # EVEN ONCE (the wave had no Revit). This is exactly the class recorded
    # in CLAUDE.md: "6/6 in Roslyn means THE MEMBER EXISTS, not THE CALL
    # WILL WORK."
    #
    # THE REPLACEMENT PIN IS WRITTEN AND CAN TURN RED:
    # `test_mutation_neighbour_circle.py` — pins on both guards and on the
    # receipt fields, and a CONTROL MUTATION for each: the same predicate
    # the pin judges the live emitter by, applied to the list WITHOUT the
    # check, and it must fail.
    # ── 23.08.2026: THE REFUSAL PREPROCESSOR STOPPED CALLING A HUMAN ─────────
    "23.08.2026 failure preprocessor + два каталожных опа":
        "1764 расхождения из 2277 и 24 НОВЫХ ключа. Перезаморожено.\n"
        "\n"
        "ПРИЧИНА, И ОНА ПРИШЛА С ЭКРАНА ВЛАДЕЛЬЦА, А НЕ ИЗ ТЕСТА. Во время\n"
        "переноса здания Ревит показывал бесконечное модальное окно «оставить\n"
        "элементы присоединёнными или отсоединить»: жмёшь отмена — всё\n"
        "хорошо, жмёшь отсоединить — окно всплывает снова. Причина в ОДНОЙ\n"
        "строке `emit_utils.failure_preprocessor_cs`: на ОШИБКЕ препроцессор\n"
        "возвращал `FailureProcessingResult.Continue`, а `Continue` в Revit\n"
        "API И ЕСТЬ «показать диалог пользователю». То есть окно звали МЫ\n"
        "САМИ, у себя же в коде, и звали на каждый повтор. Теперь ошибка\n"
        "записывается ВСЕГДА и разрешается один раз, а неразрешённая идёт\n"
        "`ProceedWithRollBack`; `Continue` остался только там, где ошибок не\n"
        "было вовсе. Правка и её эталоны — коммит 4c014f5b.\n"
        "\n"
        "СОСТАВ ДЕЛЬТЫ ПРОВЕРЕН ОБХОДОМ, А НЕ ГЛАЗАМИ (2280 выгруженных\n"
        "эмиссий, примета `ProceedWithRollBack`):\n"
        "    разошлось 1764 — носителей препроцессора 1764, посторонних 0\n"
        "    совпало    513 — носителей среди них 0\n"
        "Разбиение ПОЛНОЕ в обе стороны: ни одна программа без препроцессора\n"
        "не тронута, ни одна с препроцессором не осталась прежней.\n"
        "\n"
        "24 НОВЫХ КЛЮЧА — это не расхождение, а прибавление корпуса:\n"
        "`scope:catalog_floor_plan` 12 и `scope:catalog_wall_type` 12 (6\n"
        "версий x 2 изоляции). Волна каталога 23.08 завела два опа, и оба\n"
        "вошли в корпус эмиссии. Свидетель типа стены в тот же день разрезан\n"
        "с одного ключа на ШЕСТЬ: таблица сертификата обещала пять\n"
        "обязательств поимённо, эмиттер отдавал один `compound_structure`, и\n"
        "`create_wall_type` был UNPROVEN на всех шести версиях.\n"
        "\n"
        "ЖИВЫЕ ВОРОТА НА ПРИБАВЛЕННОМ: 12 из 12 компилируются на своих\n"
        "версиях, отказов 0. Проба НЕ ВЫРОЖДЕНА — отрицательный контроль\n"
        "(`GetCompoundStructure` -> `GetCompoundStructureNope`) отказывает\n"
        "CS1061.\n"
        "\n"
        "🔴 И ПРО САМ ЗАМЕР. Первый прогон этой сверки был ЛОЖЬЮ ПРИБОРА\n"
        "дважды: приметой стояло `__vt_`, которая ловит чужие эмиссии (36\n"
        "файлов, среди них кровля), а код слался в службу НЕОБЁРНУТЫМ — и\n"
        "36 из 36 «отказов ворот» были про мою обёртку, а не про код. Обе\n"
        "колонки печатались уверенно. Числа выше сняты после починки прибора.",
    "22.08.2026 move_elements + delete":
        "круг последствий: FindInserts/GetDependentElements+IsLocked стали "
        "обязательствами, возврат doc.Delete и GetJoinedElements — фактами "
        "квитанции; до этого мутация утверждала полное покрытие, не задав "
        "про соседей ни одного вопроса",
    # ── 22.08.2026: A WALL ARC GOT AN AXIS MARKER ─────────────────────────
    # 24 discrepancies, ALL on one key, `golden:authoring_wall_arc`
    # (6 versions x 2 isolations x 2 corpora). Not a single other key was
    # touched — checked by a walk, not by eye.
    #
    # THE CAUSE. `serving._axes_from_violations` sorts a violation by the
    # MARKER IN THE STRING, and neither of the arc's two messages had a
    # marker AT ALL, so by the rule an unmarked one slides into SEMANTICS.
    # So an arc wall with the wrong center was reporting `geometry_ok:
    # True`, and it was some other axis that turned red. This is not
    # silence, it is a green ABOUT A BROKEN AXIS.
    #
    # WHAT EXACTLY CHANGED IN THE BYTES — WORKED OUT FROM THE GOLDEN DIFF,
    # TWO LINES:
    #     "WA: arc requested but wall is not an Arc"  -> ... " (geometry)"
    #     "WA: arc center/radius mismatch"            -> ... " (geometry)"
    # Not one check removed, not one foreign line.
    #
    # THE REPLACEMENT PIN IS WRITTEN AND CAN TURN RED:
    # `test_axis_marker_reaches_the_witness.py` — eight tests, and the last
    # one walks the LIVE emitter: every bracketed form of its string
    # literals must turn red on EXACTLY ONE axis, ITS OWN. Plus
    # `test_post_clause_kind` keeps `AXIS_ROUTING_DEFECTS` empty in BOTH
    # directions.
    #
    # THE COST THIS LIFTED, by number from the MNVNK decompile: `create_wall`
    # (arc) 7,845 + `place_family` (rotation) 5,340 + `create_column`
    # (rotation) 2 = 13,187 operations out of 19,041, 69% of the real
    # building. The other two routes were fixed on the READER side and did
    # not touch the emission bytes.
    # 🔴 AND 12 MORE KEYS WERE ADDED, NOT CHANGED: `scope:author_family_min`
    # (6 versions x 2 isolations). The `author_family` op was set up on
    # 21.08 and was NEVER caught by the ratchet — exactly the form the
    # test's own header warns about ("the registry grew; everything that
    # arrived afterward was freezing out of sight"). Now frozen. Vanished
    # keys ZERO.
    "22.08.2026 golden:authoring_wall_arc":
        "пометка (geometry) у обоих сообщений дуги; без неё нарушение "
        "геометрии краснило семантику",
    # ── 21.08.2026: DIRECTION BECAME ITS OWN GENUS ─────────────────────────
    # 36 discrepancies: `golden:place_family_placement_kinds`,
    # `scope:place_family_work_plane`, `scope:shape_solid_sweep`, 12 each
    # (6 versions x 2 isolations). ALL THREE and ONLY THEY carry `ref_dir`
    # — checked by a corpus walk, not by eye.
    #
    # THE CAUSE. `ref_dir` was declared as genus `pt_xyz`, i.e. a POINT, and
    # `decompile.program_source._shift` was subtracting the local frame's
    # origin from the direction: [-1, 0, 0] turned into [-1001, -500, 0]. A
    # genus `dir_xyz` was set up; its parsing normalizes the three numbers
    # to float, the way point parsing has long done.
    #
    # WHAT EXACTLY CHANGED IN THE BYTES — WORKED OUT FROM THE GOLDEN DIFF
    # (.golden.cs of `place_family_placement_kinds`, 6 lines):
    # `new XYZ(1, 0, 0)` became `new XYZ(1.0, 0.0, 0.0)`. In C# this is THE
    # SAME value of the same type; there is no semantic difference, and
    # there were no other differences in the diff.
    #
    # A BOUNDARY, NAMED HONESTLY: the other two programs have no
    # .golden.cs reference (they come from the coverage corpora), and their
    # bytes were not checked line by line — the conclusion was carried over
    # from the first one by the mark "same parameter, same parsing."

    # ── 20.08.2026: EXTRUSION-EMISSION DRIFT, REFROZEN ON 21.08 ────────────
    # 24 discrepancies: `golden:solid_extrusion_and_revolve` and
    # `scope:solid_extrusion_arc_holes`, 12 each. Not a single one carries a
    # direction (checked), they have nothing to do with the genus wave.
    #
    # 🔴 THIS DRIFT STOOD RED FOR A WHOLE DAY, AND HERE IS WHY IT IS
    # LEGITIMATE. The fixture was frozen by commit 3b8ec65b (20.08), and
    # after it THREE commits touched the body's emission, each accepted
    # work with its own measurement:
    #
    #   851e26f6  Sweep: offsetting the profile from the path, a law
    #             against Revit
    #   61b6136d  MIN_EXTENT_MM 100 -> 1: the limit was OURS, proven by a
    #             live Revit
    #   2d42ddda  The sketch plane became a genus OF THE LANGUAGE
    #
    # Not one commit of this session touched `solid_emit.py` — checked with
    # `git log 09d6342d..HEAD`.
    #
    # 🔴 A BOUNDARY THAT MUST NOT BE HUSHED UP: the refreeze here rests on
    # THREE NAMED COMMITS, not on a line-by-line review of the 24 keys —
    # I did not read their bytes. This is recorded precisely because
    # silence here would read as "reviewed."

    # ── 21.08.2026: THIRTY-FOUR KEYS, NEVER FROZEN AT ALL ─────────────────
    # The refreeze added 34 keys that had NEVER been in the fixture. This
    # is not a discrepancy — it is the ratchet's silence: it was not
    # looking at them, and its green asserted nothing about them.
    #
    #   auth_solid_boolean_prism_voids  12  the program was added to the
    #                                       corpus earlier, the fixture was
    #                                       not rebuilt
    #   auth_contour_spline             12  set up on 21.08 in the COVERAGE
    #   arch_ceiling_spline             10  corpus, to bring the dead number
    #                                       `spline_point_mm` to life (a
    #                                       ceiling has 10 of them, not 12:
    #                                       there is no ceiling in 2021)
    #
    # 🔴 A FORM WORTH REMEMBERING: "an instrument covering part of the
    # range," on the ratchet itself, for the second time now — the first is
    # recorded in its own header. A key that did not make it into the
    # fixture is indistinguishable from a key that matched.

    # ── 20.08.2026, night: the shell builder is asked WHAT it dislikes ────
    # 12 discrepancies, all in `scope:shape_surface_nurbs` (6 versions × 2
    # isolations). One line was added to the emission:
    # `AllowRemovalOfProblematicFaces()`.
    #
    # THIS IS NOT A RELAXATION, IT IS A QUESTION PUT TO REVIT. The
    # `Finish() -> Failure` refusal on a legitimate patch was not explained
    # by any computable measure of the input: position, orientation,
    # flatness, amplitude (sawtooth), print rounding, regularity, knot-
    # vector scale (×1/×10/×3000), and a single point's shift were all
    # measured out (seven probes, all refused the same way). With this
    # call, the builder said something for the first time:
    # `RemovedSomeFaces()` became `true` — it considers THE FACE ITSELF the
    # problem, not the edges, the loop, or the orientation.
    #
    # The technique is taken from the production Rhino.Inside.Revit
    # converter and confirmed by an Autodesk engineer on the forum as the
    # ONLY debugger of the cause available through the public API.
    #
    # THERE IS NO SILENT SUBSTITUTION BY CONSTRUCTION: we always have a
    # single face, removing it leaves an empty shell,
    # `IsResultAvailable()` stays `false`, the op refuses as before.
    # Checked live on both sides: the panel that was failing now refuses
    # (but with a diagnosis), the dome builds.

    # ── 20.08.2026, evening-2: the surface witness started GUARDING a throw
    # 12 discrepancies, ALL in one program (`scope:shape_surface_nurbs`, 6
    # versions × 2 isolations). Attribution is unambiguous by ownership:
    # the only edit to `surface_emit.py` after the previous freeze is
    # commit 5b03cebe.
    #
    # WHAT EXACTLY CHANGED AND WHY IT IS LOAD-BEARING:
    # `ExportUtils.GetNurbsSurfaceDataForSurface` THROWS on all six versions
    # («This surface type is not supported»), while the witness was
    # checking the result for `null` — i.e. execution would never even
    # reach the check. It would have fired exactly when Revit collapses the
    # face down to non-NURBS, and what it collapses was measured live the
    # same day (a saddle: 3x3/16 points came back as 1x1/4). The cost would
    # have been an `internal` instead of a named outcome.
    #
    # The second half of the same fix: sentinel "not measured" values
    # stopped riding into the receipt as A NUMBER. It used to be
    # `worst_control_point_mm: -304.8` — that is -1.0 in internal feet via
    # MM(), a plausible-looking number standing in for an absence.
    #
    # PINNED BY: `tests/test_surface_query.py` (16 checks) and eight
    # mutations, of which the removed `catch` and the restored sentinel
    # turn red.

    # ── 20.08.2026, evening: a bounding-box violation prints the MEASURED
    # VALUE ──────────────────────────────────────────────────────────────
    # 368 discrepancies out of 392, and this is ONE fix: the `bbox extents
    # mismatch` text now carries the value read alongside the authored one.
    # Every program whose op raises `bbox_extents_witness` is affected —
    # ceiling, topography, slab, roof, foundation, railing, contour slab,
    # slab edge, area reinforcement: 33 programs × 6 versions × 2
    # isolations.
    #
    # WHY THIS WAS NEEDED. On a postcondition violation the transaction
    # rolls back, no receipt with numbers gets assembled at all, and the
    # violation text remains the sole carrier of what was measured. Before
    # the fix it only named the expected value — i.e. the instrument stayed
    # silent exactly where it knew the answer. A live measurement on 20.08
    # (a slab with a wavy edge, Revit 2026), after the fix, said "got
    # 9705.3, expected 9426.0 at a tolerance of 50.0" and explained a 279 mm
    # gap in one pass, which previously would have taken three.
    #
    # ATTRIBUTION IS PROVEN BY A CONTROL, NOT BY READING: restoring ONLY
    # the previous bbox text (by swapping the function in the process's
    # memory, the tree untouched) gives 24 discrepancies instead of 392.
    # The remaining 24 are two programs
    # (`golden:auth_directshape_tower`, `scope:shape_directshape`), and they
    # are explained separately: `shape_emit` learned to read a closed shell
    # as a `Solid` and store the expected vertices in a float32 model —
    # that fix has its own two controls.
    #
    # WHAT PINS THE NEW TEXT: thirteen golden fixtures (the diff was read
    # line by line) and `test_spline_kind_survives_the_plan
    # ::test_the_bbox_violation_prints_what_it_MEASURED`.

    # ── Trimming a segment for a fitting insertion — legitimate (30.07) ───
    # A LIVE MEASUREMENT on the Snowdon Towers Sample Plumbing sample
    # (Revit 2026). The CONNECT witness required "the segment's end ==
    # the ordered node ±5 mm" at BOTH ends, and on a connected system this
    # could never be satisfied: Revit places a fitting at the node and
    # trims the neighboring segments to its face. A differentiating
    # experiment settled the question: a system of ONE segment passed (id
    # 1738981, one_system=true); of two, both ends of the joint were
    # violated; of three, all three. The topology (a connector BFS) passed
    # EVERYWHERE, i.e. the system assembled as connected, while the check
    # declared it wrong. This is exactly why three networking operations
    # never built anything across the whole history.
    #
    # The check moved from a BOX around the node to the SEGMENT'S AXIS: t
    # is how far it moved along, d is how far it drifted off the axis. A
    # free end (a degree-1 node) keeps the previous ±5 mm; a joined end is
    # allowed to retreat inward, but no farther than half the segment and
    # without leaving the line. The relaxation is granted along exactly one
    # degree of freedom; drifting off axis and overshooting outward remain
    # violations.
    #
    # A straight pipe and a straight duct are a system of one segment, they
    # go through the same witness, so their bytes shifted too under
    # UNCHANGED semantics (both ends free -> the same ±5 mm, just a round
    # tolerance instead of a cubic one).
    # Replacement pin: kir/tests/test_system_segment_trim.py — the
    # tolerance boundaries, and that the emission DISTINGUISHES the genus
    # of the ends.
    # A second fix on the SAME day in the same programs: the diameter
    # refusal was split into two cases. Before, "`__dp == null` or the
    # value diverged" was one condition, and a rectangular duct got
    # «diameter mismatch» — the model would go hunting for a number
    # instead of understanding that a rectangular cross-section simply HAS
    # NO diameter. There is no cross-section shape in the grounding pool,
    # nothing to refuse on at compile time, so the branches were split at
    # execution. Replacement pin: kir/tests/test_duct_diameter_shape.py.
    "guard:duct_straight": "подрезка под отвод + диагноз отсутствующего диаметра",
    "guard:pipe_straight_reducer": "подрезка под отвод: проверка в осях участка",
    "guard:pipe_straight_same_diameter": "подрезка под отвод: проверка в осях участка",
    # ── Curtain-wall cell: regen before the grid + evidence instead of an
    # empty message (28.07) ────────────────────────────────────────────
    # LIVE PROBES on the SOB6.2 facade (Revit 2023), two measurements in a
    # row:
    #   P1 — the curtain wall ALONE, at the exact coordinates of the
    #        failing chunk: ok, witness 3/3, ends matched. The wall is not
    #        at fault;
    #   P4 — the same wall + `set_curtain_panel` in ONE transaction:
    #        KIR-X003 and a refusal of exactly four words: «ChangePanelType:
    #        ». Revit threw with an EMPTY Message.
    # Two fixes, both structural:
    #   1. `doc.Regenerate()` before any work with the grid: panels and
    #      division lines are born from regeneration, not from a call to
    #      Wall.Create — the same class as "connectors are only readable
    #      after a regen" (CONNECT) and `Activate()+Regenerate()` in
    #      _symbol_res. The regen is NOT wrapped in a catch: per the
    #      assembly documentation, a failed regeneration means a corrupted
    #      document, and the transaction's owner must abort it, not stay
    #      silent;
    #   2. the ChangePanelType refusal names itself: the exception class,
    #      the inner exception, the panel's class and the new type's class
    #      (GetPanelIds, per the same documentation, returns both Panel and
    #      Wall), the host's id, the cell's address, and the unlocked flag
    #      (GetUnlockedPanelIds exists precisely because a locked panel
    #      cannot be changed).
    # Not one check added or removed; the witnesses are the same.
    # Replacement pin: kir/tests/test_curtain_panel_op.py —
    # TheGridIsRegeneratedBeforeItIsRead + TheFailureNamesItself.
    #   3. UNLOCKING the cell before changing its type. Probes P6 (a
    #      finished host) and P7 (a PanelType instead of a WallType)
    #      returned the SAME THING: «InvalidOperationException: (empty
    #      Revit message) … РАЗБЛОКИРОВАНА=НЕТ». P6 removed the
    #      transaction, P7 removed the type mismatch; the lock remained. A
    #      panel born from a host's type is, in Revit's terms, "type-driven"
    #      (BuiltInFailures.CurtainWallFailures.
    #      TypePanelsFronNonRectCellsUnlocked: «Type-driven panels … were
    #      UNLOCKED and left unchanged»). It is unlocked via Element.Pinned
    #      — Panel has no lock setter, Lock lives on Mullion. The panel is
    #      never locked back: 53 of the facade's raised cells are replaced,
    #      meaning in the original they were unlocked by hand. Replacement
    #      pin: TheTypeDrivenPanelIsUnlockedFirst.
    #   4. ELEMENT REPLACEMENT. Probe P8 (after unlocking): the exception
    #      was gone, the call executed, and the witness caught "the panel
    #      type in the cell does not equal the requested one" — it was
    #      reading the OLD cell. Per the assembly documentation,
    #      ChangePanelType returns «the modified panel element»; for a
    #      WALL type this is a NEW element. The witness now takes the
    #      occupant: the returned element if it is in this grid's panel
    #      list, otherwise the one re-read by address; the type is read
    #      from the model after Regenerate, not from the return value. The
    #      receipt carries both ids. Replacement pin:
    #      ChangingTheTypeReplacesTheElement.
    #   5. CHASING THE TYPE and SPATIAL BINDING. Direct experiments E1-E4 on
    #      a live host: (E1) ChangePanelType with a WALL type builds a wall
    #      of SOMEONE ELSE'S type — the host's division type — silently,
    #      with no exception; (E3) is cured by `ret.ChangeTypeId(type)`,
    #      whose return of -1 (InvalidElementId) is an ordinary success, not
    #      a refusal — the assembly documentation describes exactly this
    #      case as the ONLY one where a type change spawns a new element;
    #      (E2) the wall-occupant NEVER appears in GetPanelIds — not after
    #      Regenerate, not after Commit — so a membership check is always a
    #      false negative for it, and it is replaced by binding to the
    #      host's axis (measured at 0.0 mm, tolerance 50 mm for arcs).
    #      Replacement pin: TheRequestedTypeIsChasedNotAssumed +
    #      AWallOccupantIsBoundBySpaceNotByTheGridList.
    "scope:curtain_cell|":
        "витражная ветка: Regenerate перед чтением сетки, отпирание "
        "type-driven ячейки, говорящий отказ ChangePanelType, занявший "
        "ячейку как операнд свидетеля, догон типа через ChangeTypeId и "
        "привязка стены-занявшего к оси носителя "
        "(живые пробы П1/П4/П6/П7/П8 и эксперименты E1-E4, 28.07)",
    # ── The host was hoisted into the declaration scope (28.07) ───────────
    # `__pfh_` was declared with `var` INSIDE the operation block, while the
    # host witness reads it AFTER that block closes. In the atomic wrapper
    # the seam is invisible, in per-op it is visible: a live electrical
    # rebuild (9344 ops) failed with `CS0103: The name '__pfh_e1278883' does
    # not exist in the current context`, not a single element created.
    #
    # There is exactly one fix, and it is structural: the declaration moved
    # to where `__el_` had always lived, and the assignment stayed inside
    # the block. Not one check added or removed; the change touched 12
    # emissions — this golden across six versions × two isolations, and
    # nothing else.
    "golden:place_family_point_and_curve|":
        "объявление хоста `__pfh_` поднято в область объявлений: свидетель "
        "хоста живёт за пределами per-op блока (CS0103 на живом ЭОМ)",
    # ── A segment's diameter got ITS OWN witness key (27.07) ───────────────
    # `_network_obligations` accepted `diameter_bip` and NEVER USED it: the
    # certificate did not know about the diameter check, even though the
    # emitter was setting it. So removing the check from the emitter left
    # the certificate "proven" — exactly the hole the certificate was set
    # up to close.
    #
    # The cause runs deeper than a missing line: the end-point and diameter
    # witnesses were riding under ONE key, "endpoints", while obligations
    # are discharged by key. An obligation discharged by someone else's key
    # is indistinguishable from a missing one.
    #
    # The bytes only shifted position: it was formally checked that the set
    # of emission lines BEFORE and AFTER matches (8 and 4 lines
    # transposed, zero added, zero removed). Tolerance, messages, and the
    # BuiltInParameter are the same. The justification for these two keys
    # is grouped below with an earlier CONNECT change. Two declarations of
    # one key are dangerous: Python silently keeps the last one and loses
    # one of the reasons for the golden's permitted change.
    # ── Key scheme by kind: batches of 20 → one entry per kind (27.07) ─────
    # `query:all_kinds_NN` was numbered by offset in the list of all kinds,
    # so adding ANY kind reassembled the batches' composition and "walked"
    # the bytes of kinds the fix had nothing to do with. A live case: the
    # table grew 21 → 51 (structural/HVAC/plumbing/electrical sections that
    # were almost entirely missing from it), the emitter did not change by
    # a single byte — yet the ratchet showed 12 discrepancies. A key by the
    # kind's NAME (`query:kind_<name>`) makes the table's growth strictly
    # additive.
    #
    # That the emission did NOT change was checked separately and
    # concretely: the same 25 PBT programs, generated from the previous set
    # of 21 kinds, gave 150 byte-for-byte matches and 0 discrepancies on
    # the new code.
    #
    # A ratchet that clicks on a change to a neighboring table rather than
    # to the emission teaches people to stamp that very list without
    # looking — and stops catching what it was set up for. This is the
    # only reason to touch the scheme.
    "query:all_kinds_":
        "снятая схема ключей: пачки по 20 видов заменены записью на вид "
        "(query:kind_<name>), рост таблицы видов теперь аддитивен; эмиссия "
        "не менялась — 150/150 байт-в-байт на прежних PBT-программах",
    "gate:auth_native_group|":
        "create_group member-POSTs added by design (A2, pinned by the "
        "native_group golden)",
    "scope:native_group|":
        "same deliberate member-POSTs, scope-contract fixture of the same op",
    "golden:full_house_v1|":
        "place_family Z-фикс 2026-07-21: NewFamilyInstance трактует z точки "
        "как офсет над уровнем — эмитим z−Elevation (старые байты = живой "
        "double-count по z); pinned by full_house_v1 golden + "
        "PlaceFamilyLevelRelativeZ in test_authoring",
    "scope:full_house|":
        "same place_family Z-фикс, scope-contract fixture of the same corpus",
    # ── F5 v4 (2026-07-27): mirroring on a hosted instance is GONE ─────────
    # The v3.1 hybrid kept a mirror-COPY as a fallback when CanFlip*=false.
    # A live measurement on SOB6.2 (R2023, 178 neighborhood ops, three runs
    # on their own strips — artifacts/mirror_cause*.json) showed what it
    # cost: with the mirror, three ops refuse with «зеркальная копия
    # недоступна», AND AT THE SAME TIME three OTHER doors on a different
    # host lose their geometry — they end up at point [0,0] with no body at
    # all. With flips disabled everywhere: 0 refusals, 0 violations, 0
    # breakages. With flips disabled only for the three that failed: the
    # breakage moves to a fourth op. So MirrorElements(mirrorCopies=true)
    # on a hosted instance corrupts the document BEYOND its own op, and a
    # per-op SubTransaction does not contain that.
    #
    # Along with the mechanism, its limiter was removed too
    # (__kirLockedMirror_*, the _A5_LOCKED_MIRRORS_PER_HOST threshold, the
    # text about the cap): code guarding something that no longer exists
    # reads as guarding something that does. An unreachable flip now NAMES
    # the reason — the verdict reads CanFlip* from the live element.
    "golden:hosted_door_flips|":
        "F5 v4 2026-07-27: снята ветка mirror-COPY у hosted (живой замер: "
        "рушила ЧУЖИЕ двери), вердикты флипов дочитывают CanFlip* и называют "
        "причину; pinned by hosted_door_flips golden + "
        "F5EmitFlips.test_flip_locked_door_never_mirrors и LiftEmitRoundTrip "
        "в test_hosted_flips_wall_vertical",
    "scope:hosted_flips_wall_vertical|":
        "same F5 v4 изменение, scope-contract fixture of the same corpus",
    # ── CONNECT: the system is derived by Revit at commit, not built by us
    # Measured 27.07 on live Revit 2023 (connect.py §A): Pipe.Create with a
    # systemTypeId ALREADY places both connectors into an auto-created
    # system (MEPSystem=«Канализация 1» while IsConnected=false), so
    # doc.Create.NewPipingSystem/NewMechanicalSystem was answering «Some of
    # the input connectors have been used», and ALL FOUR graph ops never
    # built anything, not once. Yet after Commit, Revit merges the systems
    # itself (two pipes joined via ConnectTo both came back with
    # #21201856). The old bytes were pinning down a construction that did
    # not work: the factory call was removed, the "one system" check moved
    # from an in-transaction postcondition to a post-commit witness
    # (mep_system_ids/one_system), and connectivity (a BFS over the live
    # connector graph) remained the in-transaction guarantee.
    "golden:route_pipe_system_riser_branch|":
        "CONNECT: удалён NewPipingSystem, добавлен пост-коммитный readback; "
        "pinned by route_pipe_system_riser_branch golden + "
        "SystemMembershipMEP в test_mep. Сертификат: диаметр вынесен в свой "
        "свидетель (ключ diameter) сразу за концами; множество строк эмиссии "
        "не изменилось, только порядок",
    "golden:route_duct_system_tee|":
        "то же для ОВ (NewMechanicalSystem); pinned by route_duct_system_tee "
        "golden + SystemMembershipMEP в test_mep. Сертификат: то же "
        "вынесение диаметра в собственный ключ свидетеля",
    "scope:pipe_system|":
        "то же изменение у create_pipe_system; pinned by "
        "SystemMembershipIsDerivedNotForced в test_connect",
    "scope:route_pipe|":
        "то же изменение, scope-contract fixture route_pipe_system",
    "scope:route_duct|":
        "то же изменение, scope-contract fixture route_duct_system",
    # ── stairs no longer leave Revit stuck in a modal dialog ───────────────
    # Observed live on 27.07: create_stairs built the stairs, and the
    # bridge died on SIX consecutive calls afterward ("Execution was
    # cancelled before Revit started it") — to the user this reads as
    # "KUKAI froze after the stairs," permanently. The cause reproduces
    # offline: this is the only op with its own program template, and it
    # had none of SetFailuresPreprocessor, SetForcedModalHandling(false),
    # or warning removal — everything emit_program sets up for every
    # ordinary program. The old bytes were pinning down the hang.
    "gate:auth_stairs|":
        "лестничная транзакция получила обработчик отказов + подавление "
        "модальности, а её обработчик на StairsEditScope.Commit теперь тоже "
        "снимает предупреждения; pinned by StairsMustNotLeaveAModalDialog "
        "в test_hangs_and_lies",
    # ── beam_types no longer hands out what the op cannot use ──────────────
    # Measured 27.07: all 36 framing families of the real building are
    # FamilyPlacementType.OneLevelBased, while create_beam emits
    # NewFamilyInstance(Line, …), which returns null for a point-based
    # family. The fact is known at ground time ⇒ that is where it should
    # give an honest KIR-G104 «пусто в модели» instead of a runtime null.
    "query:types_all_pools|":
        "коллектор beam_types фильтрует по FamilyPlacementType "
        "(CurveDrivenStructural/CurveBased); pinned by "
        "BeamPoolMustNotOfferPointPlacedFamilies в test_hangs_and_lies",
    # ── two defects in the level witness, both measured by a live probe on
    # 27.07 ─────────────────────────────────────────────────────────────
    # (a) The step along the BIP chain was checking `HasValue`, and that is
    #     also true for InvalidElementId: on a beam, FAMILY_LEVEL_PARAM =
    #     HasValue:True / AsElementId:-1. The chain stopped at an EMPTY
    #     link and compared "-1" against the expected id, accusing the
    #     correct element. The step now requires a real ElementId — this
    #     changes the emission for every op whose witness walks the chain.
    # (b) For a beam, requiring level equality was simply NOT ALLOWED:
    #     Revit DERIVES the reference level from the curve's elevation.
    #     L_01 @ 0 mm was passed, the curve was at Z=3000 -> the binding
    #     went to L_01ДОО1_+2.500. The postcondition demanded something the
    #     API does not promise. It was replaced by a real invariant, "a
    #     reference level exists," plus reading the level obtained into the
    #     witness; the beam itself is pinned at both ends in 3D with a 5 mm
    #     tolerance.
    "golden:struct_beam|":
        "свидетель уровня балки: равенство заменено на существование + чтение "
        "reference_level в результат; pinned by "
        "BeamLevelWitnessMustReadTheParameterABeamActuallyHas (test_hangs_and_lies) "
        "и BeamCommitGateInvariants (test_struct)",
    "golden:struct_foundation_isolated|":
        "переход цепочки требует настоящий ElementId (дефект «а»)",
    "golden:struct_foundation_slab|":
        "то же (дефект «а»)",
    "scope:struct|":
        "то же, scope-contract fixture структурных опов",
    "scope:contour|":
        "то же, scope-contract fixture create_floor_by_contour",
    "scope:floor_holes|":
        "то же, scope-contract fixture create_floor с отверстиями",
    # ── a rollback must name its cause (a common footer for all authoring
    # programs) ────────────────────────────────────────────────────────
    # The whole building assembly died with "transaction commit status:
    # RolledBack" and said NOTHING further. Revit rolls back like that on
    # hitting an ERROR-level failure: __KirMainFailures was dismissing
    # warnings and deliberately not suppressing the error — but it also
    # was not recording it, so the cause was lost. A live probe on 27.07
    # showed that the text is available via FailuresAccessor
    # (GetSeverity + GetDescriptionText). A silent rollback is exactly the
    # mute outcome this compiler forbids, so the instrument is placed in a
    # COMMON footer: splitting the refusal policy into two is worse than
    # reissuing the corpus once. Every authoring program diverges, at
    # three spots: Seen.Clear() before the operations, error collection,
    # and the text in the refusal.
    "gate:auth_grid_array|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "gate:auth_mixed|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "gate:auth_stack|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "gate:auth_wall|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "gate:mod_setparam_delete|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:authoring_wall_arc|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:authoring_wall_pipe_grid|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:modify_setparam_delete|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:stack_two_storeys|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:wall_base_offset|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:wall_top_attached|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    # ── create_dimension: geometric references instead of element
    # references (28.07) ─────────────────────────────────────────────────
    # Live probe P11 (E5, FAS_R23, Revit 2023): «NewDimension: The
    # references are not geometric references» — ReferenceArray accepts
    # only geometric references (a face/edge), while the old emission was
    # placing `new Reference(element)`. The gate did not catch this (it
    # compiled 6/6); only a live Revit did. The fix (both parts
    # structural):
    #   1. on ref: Wall -> HostObjectUtils.GetSideFaces(Exterior)[0];
    #      otherwise (or if the host did not yield a face) -> a general
    #      fallback, geometry with Options{ComputeReferences=true, View=
    #      view}, the first PlanarFace with a non-empty Reference; nothing
    #      found -> a typed refusal;
    #   2. the dimension line: the direction is now taken from the normal
    #      of the FIRST resolved face (re-read via
    #      GetGeometryObjectFromReference), projected onto the view plane
    #      — E5 proved live that the line must run ACROSS the measured
    #      faces, not along a fixed View.RightDirection; RightDirection
    #      remains the fallback when the normal cannot be read. The guard
    #      "line_at reproduced (geometry)" was removed: the measured VALUE
    #      depends on which faces are chosen (Exterior/Interior), there is
    #      nothing to compare against — the value only goes into the
    #      receipt.
    # Replacement pin: DimensionLineOrientation in test_annotation.py.
    #
    # ── ADDED 28.07 (the same day): Regenerate before harvesting references
    # A live repeat of P11 AFTER the fix above failed with the SAME typed
    # refusal («refs[0]: у элемента нет геометрической ссылки для
    # размера»), but for a DIFFERENT reason: a freshly created wall has no
    # faces before a Regenerate — GetSideFaces is empty, the geometry
    # fallback is empty too (Element.Geometry needs regenerated geometry
    # just as much). Measured: between Wall.Create and GetSideFaces, in
    # the atomic assembly, a Regenerate was never emitted at all —
    # emit_program's auto-run ("v0 rule", walls_since_regen) only
    # regenerates before create_room. per_op follows the same law: neither
    # SubTransaction.Commit() nor Transaction.Commit() is documented as
    # regenerating (RevitAPI.xml is silent on this either way);
    # regeneration is always a separate, explicit Document.Regenerate().
    # The fix: an unconditional doc.Regenerate() as the first line of this
    # op's create block, WITHOUT a try/catch (the same law as
    # set_curtain_panel: a failed regeneration is a corrupted document,
    # the transaction must abort, not stay silent).
    "scope:annotation|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause "
        "в test_hangs_and_lies. ДОБАВЛЕНО 28.07: геометрические ссылки "
        "(GetSideFaces/geometry-фолбэк) + направление линии размера по нормали "
        "первой грани — pinned by DimensionLineOrientation. ДОБАВЛЕНО 28.07 "
        "(живой повтор П11): doc.Regenerate() перед добычей ссылок, atomic и "
        "per_op — pinned by test_regenerate_before_reference_extraction_"
        "atomic/_per_op/test_regenerate_is_not_wrapped_in_catch",
    "scope:annotation_explicit|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause "
        "в test_hangs_and_lies. ДОБАВЛЕНО 28.07: геометрические ссылки "
        "(GetSideFaces/geometry-фолбэк) + направление линии размера по нормали "
        "первой грани — pinned by DimensionLineOrientation. ДОБАВЛЕНО 28.07 "
        "(живой повтор П11): doc.Regenerate() перед добычей ссылок, atomic и "
        "per_op — pinned by test_regenerate_before_reference_extraction_"
        "atomic/_per_op/test_regenerate_is_not_wrapped_in_catch",
    "scope:arc_wall|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "scope:families|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "scope:mep_runs|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "scope:modify|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "scope:pipe_grid|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "scope:roof|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    # ── a single op's refusal became a TYPE, not "some exception" (28.07) ──
    # per_op isolation was choosing the refusal semantics by POST-
    # PROCESSING the emission: `create.replace("__t.RollBack(); return
    # __Refuse(", "throw __OpRefuse(")`. This was faith in the literal
    # exactness of a phrase typed by hand in 105 spots across four files:
    # an emitter that wrote the guard differently would silently keep the
    # semantics of the WHOLE program inside the SubTransaction — one op's
    # refusal was rolling back neighbors that had already been committed.
    # Measured on this branch before the fixes: all four ways of writing it
    # passed silently.
    #
    # The operation bodies DID NOT SHIFT BY A SINGLE BYTE — this is proven
    # by a law, not by a list of hashes: PerOpBodiesEqualTheRetiredRewrite
    # checks the per_op body of EVERY operation in the corpus against
    # `atomic.replace(...)` character by character. Only the per_op
    # program's SCAFFOLD diverged, and in exactly three spots: __OpRefuse
    # builds the sentinel type __KirOpRefusal instead of an
    # InvalidOperationException, it got its own catch branch (carrying the
    # Oid of the refused op), and an unexpected exception got the label
    # `internal` — the compiler's managed decision no longer gets confused
    # with a Revit API breakage. The atomic bytes did not move at all (549
    # emissions, zero discrepancies).
    #
    # The keys are listed BY NAME, not by program prefix: a prefix would
    # also have removed the same programs' atomic bytes from the ratchet —
    # i.e. it would have weakened it exactly where it must hold.
    "golden:native_group|2021|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "golden:native_group|2022|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "golden:native_group|2023|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "golden:native_group|2024|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "golden:native_group|2025|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "golden:native_group|2026|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2021|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2022|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2023|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2024|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2025|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2026|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2021|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2022|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2023|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2024|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2025|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2026|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    # ── the level guard no longer claims drift on ANY null cast (31.07) ────
    # KIR-X003 is the largest heap of live failures (22 of 41 base ops).
    # `_level_expr` was emitting ONE static message for
    # `doc.GetElement(id) as Level == null`: «уровень не найден (модель
    # изменилась после grounding)» — while `_translate_runtime`
    # (serving.py) decides "drift" OR "runtime refusal" by the substring
    # «после grounding» inside that very same message. The substring lives
    # in the guard ITSELF, so the check was a tautology: any null cast —
    # for ANY reason — read as "the model moved on," even though `as
    # Level` also returns null when the id exists but points to something
    # other than a Level.
    #
    # Live evidence (journalctl kukai-backend, 27.07, create_beam x16, two
    # runs ~74 min apart, one editor, one local file): X003 said «уровень
    # не найден (модель изменилась после grounding)» 130-460ms AFTER
    # ground_snapshot had just returned that very same level catalog.
    # Physically too little time for a manual model edit.
    #
    # The guard now reads `doc.GetElement(id)` into a SEPARATE variable
    # BEFORE the cast and distinguishes: raw == null -> the previous text
    # (drift, unchanged); raw != null -> «id уровня резолвится не в Level,
    # а в <Type> — причина (дрейф модели или неверный id) не определена
    # рантаймом». The second branch does NOT blame grounding: `ground.py`
    # documents `by: element_id` as an INTENTIONAL pass-through (type and
    # existence are re-checked ONLY here, at runtime — see the module's
    # docstring), so the wrong id could also have come from the caller's
    # side. The message names the OBSERVED fact and honestly refuses to
    # guess the cause — the same discipline
    # RefusalMessageMustNotInventACause already applied to "NewFamilyInstance
    # returned null" / "NewElbowFitting: failed to insert elbow," one layer
    # deeper (there `_translate_runtime` was guessing from Revit's raw
    # text; here it is the C# guard itself, guessing ahead of Revit).
    #
    # `_level_expr` is a shared helper (14 call sites: walls, beams,
    # columns, foundations, rooms, floors, ceilings, railings, groups,
    # place_family, MEP systems), so the bytes shifted everywhere the
    # `level` parameter resolves other than through `by: ref` (a ref never
    # passes through the guard at all). No check was added or removed —
    # only the refusal text, plus one extra declaration line
    # (`Element __lv_raw_*`).
    # Replacement pin: LevelGuardMustNotClaimDriftForAWrongType in
    # test_hangs_and_lies.py; goldens authoring_wall_pipe_grid,
    # authoring_wall_arc, route_pipe_system_riser_branch,
    # route_duct_system_tee, struct_beam, struct_foundation_isolated,
    # struct_foundation_slab, arch_ceiling, arch_railing_path,
    # place_family_point_and_curve, hosted_door_flips, wall_base_offset,
    # wall_top_attached, native_group (atomic), annotation_full_set,
    # annotation_explicit_types.
    "gate:auth_contour_default|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "gate:auth_contour_explicit|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "guard:column_vertical|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "guard:contour_typed|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "guard:floor_typed|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "guard:group_mixed_members|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "guard:roof_typed|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2021|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2022|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2023|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2024|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2025|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2026|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2021|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2022|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2023|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2024|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2025|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2026|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
}


def _exempt(key: str) -> bool:
    return any(key.startswith(prefix) for prefix in INTENDED_CHANGES)


def _gate_authoring_programs() -> dict[str, dict]:
    """The gate runner's authoring shapes, from the same committed sources."""

    from kir.tests.test_authoring import _prog, _wall

    programs: dict[str, dict] = {}
    programs["auth_wall"] = _prog([_wall()], intent="стена 6м")
    programs["auth_mixed"] = _prog([
        _wall(),
        _wall(oid="W2", p0_mm=[0, 4000], p1_mm=[6000, 4000],
              type={"by": "name", "value": "ЖБ 200"}, height_mm=2800),
        {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
         "p1_mm": [3000, 0, 2700], "level": {"by": "element_id", "value": 42},
         "diameter_mm": 50},
        {"op": "create_grid", "id": "G1", "p0_mm": [0, -1000],
         "p1_mm": [0, 9000], "name": "А"},
    ], intent="стены+труба+ось")
    programs["auth_stack"] = {
        "ir_version": "1.0", "intent": "стек 5 этажей",
        "ops": [{"op": "stack", "id": "sec", "levels": 5, "h_mm": 3000,
                 "floor": [
                     {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                      "p1_mm": [6000, 0], "height_mm": 2800},
                     {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
                      "p1_mm": [3000, 0, 2700], "diameter_mm": 50},
                 ]}]}
    programs["auth_grid_array"] = {
        "ir_version": "1.0", "intent": "сетка осей 4x3",
        "ops": [{"op": "grid_array", "id": "net", "nx": 4, "ny": 3,
                 "dx_mm": 6000, "dy_mm": 4500, "prefix_y": "А"}]}
    programs["auth_stairs"] = {
        "ir_version": "1.0", "intent": "лестничный марш",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "p0_mm": [0, 0], "p1_mm": [5000, 0],
                 "base_level": {"by": "element_id", "value": 42},
                 "top_level": {"by": "element_id", "value": 43},
                 "width_mm": 1200}]}
    # codex #9 (2026-07-29, tasks/b8f3v4r97.output сессии eeccfb91): the
    # ONLY non-exempt frozen coverage of create_floor_by_contour was
    # "guard:contour_typed" (explicit type, no offset) — the DEFAULT-type
    # branch existed only as "scope:contour", which INTENDED_CHANGES has
    # exempted since the 27.07 level-chain fix and never un-exempted, so
    # "the whole previous emission is proven byte-exact" was a claim
    # stronger than any enforced test. Own dict (this file's, not
    # SCOPE_PROGRAMS/GUARD_PROGRAMS) so it never collides with either
    # corpus and is NEVER exempt by construction — both type branches,
    # neither carries height_offset_mm (codex's own "БЕЗ offset").
    programs["auth_contour_default"] = {
        "ir_version": "1.0",
        "intent": "плита по контуру, тип по умолчанию, без смещения",
        "ops": [
            {"op": "create_floor_by_contour", "id": "FCD1",
             "contour": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [8000, 6000]}},
             "level": {"by": "name", "value": "Этаж 1"}},
        ]}
    programs["auth_contour_explicit"] = {
        "ir_version": "1.0",
        "intent": "плита по контуру, явный тип, без смещения",
        "ops": [
            {"op": "create_floor_by_contour", "id": "FCE1",
             "contour": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [8000, 6000]}},
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "Монолит 200"}},
        ]}

    def _grp_wall(oid, x0, y0, x1, y1):
        return {"op": "create_wall", "id": oid, "p0_mm": [x0, y0],
                "p1_mm": [x1, y1],
                "level": {"__grounded__": {"id": 42, "name": None,
                                           "via": "element_id"}},
                "height_mm": 3000.0,
                "type": {"__grounded__": {"id": None, "name": None,
                                          "via": "doc_default",
                                          "in_emit": "__doc_default__"}}}

    programs["auth_native_group"] = {
        "ir_version": "1.0",
        "intent": "типовой этаж как нативная группа",
        "ops": [{"op": "create_group", "id": "GRP1", "name": "Типовой этаж",
                 "members": [_grp_wall("W1", 30000, 23000, 36000, 23000),
                             _grp_wall("W2", 36000, 23000, 36000, 27000)],
                 "placements": [[0, 0, 6600], [0, 0, 13200]]}]}
    programs["mod_setparam_delete"] = {
        "ir_version": "1.0",
        "intent": "параметр + удаление", "allow_destructive": True,
        "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 12000, "name": "Тех"},
            {"op": "set_param", "id": "S1",
             "target": {"by": "ref", "value": "L1"},
             "param": "Комментарии", "value": "создан KIR"},
            {"op": "set_param", "id": "S2",
             "target": {"by": "element_id", "value": 7777},
             "param": "Комментарии", "value": "обработано KIR"},
            {"op": "delete", "id": "DEL1",
             "target": {"by": "element_id", "value": 8888}},
        ]}
    return programs


def build_corpus() -> dict[str, dict]:
    """(source-prefixed name) -> program.  Deterministic assembly order."""

    corpus: dict[str, dict] = {}
    for name, prog in GOLDEN_PROGRAMS.items():
        corpus[f"golden:{name}"] = prog
    for name, prog in SCOPE_PROGRAMS.items():
        corpus[f"scope:{name}"] = prog
    for name, prog in _gate_authoring_programs().items():
        corpus[f"gate:{name}"] = prog
    for name, prog in GUARD_PROGRAMS.items():
        corpus[f"guard:{name}"] = prog
    rng = random.Random(GATE_SEED)
    for i in range(N_PBT):
        corpus[f"pbt:{i:02d}"] = gen_program(rng)
    # ONE entry per kind, not batches of 20.
    #
    # Batches were numbered by offset, so adding a kind reassembled the
    # chunks' composition and "walked" the frozen bytes of kinds the fix
    # had nothing to do with (27.07: +30 kinds ⇒ 12 discrepancies in
    # all_kinds with an unchanged emitter). A key by the kind's NAME makes
    # the table's growth strictly additive: a new kind brings a new key and
    # moves not one of the old ones. A ratchet must click on a change to
    # the emission, not on a change to a neighboring table — otherwise
    # people stop reading it.
    for kind in sorted(spec.KINDS):
        corpus[f"query:kind_{kind}"] = {
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": "k0", "kind": kind}]}
    qt_pools = spec.OPS["query_types"].params[0].choices
    corpus["query:types_all_pools"] = {
        "ir_version": "1.0",
        "intent": "какие типы существуют в каждом закрытом пуле",
        "ops": [{"op": "query_types", "id": f"t{j}", "pool": p}
                for j, p in enumerate(qt_pools)]}
    return corpus


def _min_ver(prog: dict) -> str:
    return prog.get("__min_ver__", "2021")


#: HARNESS service keys that are not in the program's envelope: EVERY
#: reader of the corpus must strip them, or the schema will answer with
#: KIR-P003 "unknown field," and the program will never reach the emitter
#: at all.
#:
#: `__ver__` was added to this list during the 09.08 merge, and the cost of
#: its absence is telling. The loads wave set up a SECOND such key next to
#: the already-existing `__min_ver__` (its pin runs the other way: a free
#: load only lives on 2021-2023, i.e. it is a CEILING, not a floor, so it
#: cannot be renamed to `__min_ver__`) — and taught EXACTLY ONE reader,
#: `test_golden`, to strip it. There are three readers, though, and the
#: other two went silently blind:
#:   * `gate_runner` was returning KIR-P003 on all six versions;
#:   * this corpus was catching KirRefusal and doing `continue`, which
#:     meant three load ops NEVER REACHED THE EMITTER, not once — and the
#:     anti-Goodhart test
#:     `test_the_corpus_actually_reaches_a_guard_in_every_kind` showed 49
#:     kinds against 52 in `_EMITTERS`. This is exactly the case it was
#:     written for: a parity corpus would have looked clean, because it
#:     simply never reached three of the operations.
_HARNESS_KEYS = ("__min_ver__", "__ver__")


def _strip(prog: dict) -> dict:
    return {k: v for k, v in prog.items() if k not in _HARNESS_KEYS}


def _is_write(prog) -> bool:
    """Use expanded typed operations, not raw macro names or a fallback query.

    emit_corpus passes the already validated plan from compile_program, so no
    second macro interpretation or additional query emission is introduced.
    """
    planned = plan_program(prog)
    return any(operation.family.value in spec.WRITE_FAMILIES for operation in planned.ops)


def emit_corpus(dump_dir: pathlib.Path | None = None) -> dict[str, str]:
    """Return {key: sha256} over every (program, version, mode) emission."""

    corpus = build_corpus()
    hashes: dict[str, str] = {}
    for name in sorted(corpus):
        raw = corpus[name]
        prog = _strip(raw)
        for ver in VERSIONS:
            if ver < _min_ver(raw):
                continue
            out = compile_program(prog, revit_version=ver,
                                  snapshot=GROUND_SNAPSHOT)
            if not out.ok:
                # A version-gated typed refusal (e.g. floor holes on 2021) is
                # ITSELF part of parity: the refusal codes are frozen so the
                # refactor can neither un-refuse nor re-code them.
                codes = ",".join(sorted(d.code for d in out.diagnostics))
                hashes[f"{name}|{ver}|atomic"] = f"refused:{codes}"
                continue
            _record(hashes, dump_dir, f"{name}|{ver}|atomic", out.csharp)
            # per_op isolation for write programs (macro ops like stack /
            # grid_array expand during parse; stairs is sole-op template —
            # emit_program handles all of them).
            if _is_write(out.planned):
                normed = _parse_and_check(prog)
                grounded = ground_mod.ground(normed, GROUND_SNAPSHOT)
                intent = prog.get("intent", "")
                per_op_cs = emit_program(
                    grounded, ver, intent if isinstance(intent, str) else "",
                    isolation="per_op")
                _record(hashes, dump_dir, f"{name}|{ver}|per_op", per_op_cs)
    return hashes


def _record(hashes: dict[str, str], dump_dir: pathlib.Path | None,
            key: str, csharp: str) -> None:
    hashes[key] = hashlib.sha256(csharp.encode("utf-8")).hexdigest()
    if dump_dir is not None:
        safe = key.replace("|", "__").replace(":", "_").replace("/", "_")
        (dump_dir / f"{safe}.cs").write_text(csharp, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=pathlib.Path, default=None,
                        help="also write full emissions to this directory")
    parser.add_argument("--check", action="store_true",
                        help="compare against the frozen fixture instead of "
                             "writing it")
    args = parser.parse_args()
    if args.dump is not None:
        args.dump.mkdir(parents=True, exist_ok=True)
    hashes = emit_corpus(args.dump)
    if args.check:
        frozen = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        mismatched = sorted(
            key for key in frozen
            if not _exempt(key) and hashes.get(key) != frozen[key])
        missing = sorted(
            key for key in set(frozen) - set(hashes) if not _exempt(key))
        extra = sorted(set(hashes) - set(frozen))
        if mismatched or missing or extra:
            print(f"PARITY BROKEN: {len(mismatched)} mismatched, "
                  f"{len(missing)} missing, {len(extra)} extra")
            for key in mismatched[:20]:
                print("  mismatch:", key)
            return 1
        print(f"PARITY OK: {len(frozen)} emissions byte-identical; exact keyset")
        return 0
    FIXTURE_PATH.write_text(
        json.dumps(hashes, indent=0, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"froze {len(hashes)} emission hashes -> {FIXTURE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
