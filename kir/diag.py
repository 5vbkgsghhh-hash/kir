"""KIR diagnostics — the typed error contract (SPEC_V1 §6, §12.7).

Every stage failure is a Diagnostic, never a raw exception escaping to the
caller and never a raw Roslyn message: C# errors are translated back to the
originating IR op (SACTOR pattern) before a model or a user ever sees them.
Shape follows rustc --error-format=json: code, span (op_index/op_id), message,
optional machine-applicable suggestion.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Code namespaces (SPEC §6): P parse, G ground/kind, T typecheck, L plan/limits,
# E emit/version, C compile-gate, X execute, W witness.
PARSE_NOT_OBJECT = "KIR-P001"        # program is not a JSON object / ops not a list
PARSE_UNKNOWN_OP = "KIR-P002"        # op name not in registry
PARSE_UNKNOWN_FIELD = "KIR-P003"     # additionalProperties violation (fail-closed)
PARSE_BAD_VERSION = "KIR-P004"       # ir_version missing/unsupported
PARSE_MISSING_FIELD = "KIR-P005"     # required param absent
PARSE_DUP_ID = "KIR-P006"            # duplicate op id inside one program
# "one of two" cannot be expressed by a JSON schema (oneOf breaks
# additionalProperties fail-closed), so mutual exclusion of parameters is a
# separate typed refusal. The first carrier: place_family, which is placed
# EITHER at a point (xyz) OR along a curve (p0_mm/p1_mm) — in Revit these are
# two different overloads, and it cannot be guessed on the author's behalf.
PARSE_EXCLUSIVE_FIELDS = "KIR-P007"  # mutually exclusive params: both or neither given
GROUND_UNSUPPORTED_KIND = "KIR-G001" # KindEnum escape value / unknown kind -> recipe-path handoff
GROUND_BAD_SELECTOR = "KIR-G002"     # selector shape invalid
GROUND_MODEL_BINDING = "KIR-G107"    # exact open-model dependency proof failed
TYPE_BAD_TYPE = "KIR-T001"           # wrong JSON type for a param
TYPE_BOUNDS = "KIR-T002"             # numeric outside compiler-enforced bounds (§12.9)
TYPE_BAD_ENUM = "KIR-T003"           # value not in closed enum (non-kind enums)
PLAN_LIMIT = "KIR-L001"              # program/op budget exceeded
PLAN_SOLO_OP = "KIR-L002"            # op requires its own program (own transaction scope)
# THE SHAPE OF THE PHASE PLAN (`course.phase()`): the phase boundary is drawn
# by the script's author, and anything that makes such a boundary ambiguous is
# a typed refusal, not a guess. The free codes are packed tight: L003 (order
# of references) and L004 (kind of reference) sit as literals in
# compiler.py/connect.py/route_mep.py, L005 is for a bulk-policy mismatch.
# Hence L006, and it is CENTRAL, not a literal: there are seven phase-shape
# rules at once, and seven literals would drift apart at the first edit.
PLAN_PHASE_SHAPE = "KIR-L006"        # phase(): shape of the phase plan inside one script
PLAN_OP_CONTRACT = "KIR-L007"        # write op lacks a complete canonical lowering contract
EMIT_VERSION = "KIR-E001"            # op unsupported on a requested Revit version
#: 🔴 MOVED HERE 01.09.2026 FROM `authoring.py`, AND THIS IS NOT TIDYING, IT
#: IS A LAYER. The code was read by seven emitters and the REGISTRY
#: (`ops_site` via a lazy import from `authoring`), and this edge was pulling
#: the registry into emission, and through it — the live-plan drawer into the
#: compiler: a `capability_graph` measurement at `479c294` gives 10 of 15
#: resolvers reachable, red on `test_live_plan_stream::OneWayTests`. The
#: refusal code is the DISPATCHER's subject, not the emitter's; `authoring`
#: now RE-EXPORTS it, so not one of the seven emitters moved by a single
#: line.
EMIT_UNSUPPORTED = "KIR-E003"        # feature unsupported on this Revit version
# ONE THOUGHT — ONE CONSTANT (10.08.2026). The two codes below lived
# MULTIPLIED across emitters: `KIR-E007` was declared by FOUR modules
# (site/sweep/opening/mass), `KIR-E008` — by THREE
# (opening/struct/stairs_landing), each with its own name and its own
# literal. The thought behind them was one for all, and they would have
# drifted apart silently: fixing "where the enumeration is not supported"
# would have to happen in four places, and forgetting it — in one.
#
# ONLY THE CODE IS SHARED, NOT THE TEXT. `message_ru` is its own at every
# site and stays its own: the collision was ON THE WIRE (the consumer
# branches on the code), not in the prose, and one phrasing for four
# different fixes would be a fresh defect of the same kind.
EMIT_UNSUPPORTED_ENUM = "KIR-E007"   # closed-enum value this op/version does not implement
EMIT_CONTOUR_HOLES = "KIR-E008"      # contour carries holes; this op cannot express them
# The outline carries a SPLINE, and this op's witness does not check for a
# spline. Its own code, not E008: there, "the op does not express a hole" is
# about EMISSION; here, "the op does not prove the curve" is about the
# WITNESS, and the fixes are opposite (the hole needs to be removed from the
# outline, the curve needs to be taught to check). One code for two outcomes
# is the named defect of this tree, and setting it up as the ninth instance
# would be absurd.
EMIT_CONTOUR_SPLINE = "KIR-E010"     # contour carries a spline this op cannot witness
# 🔴 CODE E010, NOT E009, AND THIS IS THE FIX OF A COLLISION COMMITTED RIGHT
# ABOVE THIS LINE (21.08.2026). The comment above declares "one code for two
# outcomes is the named defect of this tree" — and the 20.08 wave promptly
# committed it: `KIR-E009` already carried `BEAM_SYSTEM_BAD_DIRECTION_EDGE`
# (`struct_emit.py`, 09.08). The author was looking at THIS file, saw a free
# ninth slot, and did not know that the code space is also being handed out
# from there: two independent dispatchers of one resource.
#
# The NEWCOMER moves, the older code stays: a message with `KIR-E009` may
# already have traveled into journals and into model memory, and renaming it
# would mean changing its meaning after the fact.
# CODE T004, NOT T003, AND THIS IS A COLLISION FIX (10.08.2026).
# `TYPE_GEOM_RELATION` shared the wire with `TYPE_BAD_ENUM` for twelve lines:
# two names, ONE code, and two incompatible fixes — "value outside the closed
# enumeration" versus "opening intersects the outline." A consumer branching
# on `T003` could not tell them apart, and this is not a hypothesis: the
# T001/T002/T003 series is a type check (type, bounds, enumeration), and the
# outline relation arrived later and took someone else's number.
#
# WHAT MOVED WAS THE GEOMETRY, NOT THE ENUMERATION, because the enumeration
# belongs to the series by construction. Cost: 16 literals in geometry tests
# (contour, connect, mep, site, struct, v11) against 3 for the enumeration —
# but cheaper would have been wrong. In prod NOBODY branches on `T003`
# (`serving` has no `KIR-T` arm at all, `skill.py` names T002 but not T003),
# so the move breaks nothing outside the tree.
TYPE_GEOM_RELATION = "KIR-T004"      # inter-contour geometry (hole vs outline, self-intersection)
# X-stage: runtime outcomes translated to typed codes (SACTOR, SPEC 12.7) —
# a raw Revit message never reaches the model untyped (v1.1, slab-saga fix).
X_SHORT_CURVE = "KIR-X001"           # ShortCurveTolerance / zero-length edge at runtime
X_LOOPS_INTERSECT = "KIR-X002"       # curve loops intersect (T004-caught; runtime backstop)
X_STALE = "KIR-X003"                 # stale_or_failed (model drifted post-ground)
X_POSTCONDITIONS = "KIR-X004"        # in-txn commit-gate rolled back on violations
X_TXN = "KIR-X005"                   # transaction failed to start/commit
X_DUPLICATE_NAME = "KIR-X006"        # name already in use (level/grid rename throw)
X_TIMEOUT = "KIR-X007"               # execution unconfirmed (timeout)
X_RECEIPT = "KIR-X008"               # execution receipt lacks the promised identity
# ─── X009: ONE CODE — ONE WORLD ───────────────────────────────────────────────
#
# `__Refuse` (authoring.py) marks EVERY typed refusal of an emitter with ONE
# transport marker, `stale_or_failed`, and `_translate_runtime` was translating
# that whole stream into X003 — a code whose own contract (the line above)
# promises EXACTLY model drift. So one code became two worlds: "the element
# vanished between grounding and execution" and "Revit refused to do it." Only
# the `detail` text told them apart, and `detail` was not being written into
# the witness corpus AT ALL — measured 09.08.2026 against `kir_witness.jsonl`:
# not one of the 1306 lines carries a field with the refusal message, so for
# the 38 live X003 lines the cause cannot be recovered by anything. The signal
# existed, and it was being thrown away.
#
# The distinguishing signal is the "after grounding" marker that the
# null-guards THEMSELVES write; it was already being computed in
# `_translate_runtime` and immediately lost in the choice of text. Now it
# chooses the CODE: X003 stays drift (as its contract promised), and
# everything else gets its own name.
#
# THIS IS NOT AN EXPANSION OF RESPONSIBILITY: X009 proves rollback exactly the
# same way X003 does (both forms of `refuse_stmt` contain a RollBack/throw
# before commit), so `serving._ROLLBACK_PROVEN_CODES` holds both, and "rolled
# back" is not weakened.
X_OP_REFUSED = "KIR-X009"            # typed runtime refusal by an emitter guard
X_UNCLASSIFIED = "KIR-X999"          # typed envelope for the rest; raw kept in detail
# Witness-stage distinction: unlike X004, this state is observed AFTER a
# successful commit in report/per-op mode.  Reusing X004 would claim rollback
# and make a repair retry look safe even though the model already changed.
W_POSTCONDITIONS_COMMITTED = "KIR-W004"

# ─── B: sandBox — execution of the AUTHORED SCRIPT (kir/sandbox.py) ────────
#
# WHY A NEW LETTER, NOT P/T/L. The stage precedes program parsing: at this
# point there is NO program YET, there is python that is writing it. The
# refusal is addressed to a different fix — the model fixes ITS OWN script,
# not an IR operation — and points at a source line, not an op_index. Mixing
# this with P (JSON parsing) would send the fix to the wrong place, exactly
# like mixing two budgets in KIR-L001. Letters occupied as of 03.08.2026
# (measured by grepping the repository): A C D E G L M P S T W X. B is free,
# and it reads: sandBox.
# RE-MEASURED 10.08.2026: letter C is FREED — its one code `KIR-C001`
# (`COMPILE_FAIL`) was never issued in all this time and has been retired,
# see below.
SANDBOX_SYNTAX = "KIR-B001"             # the source could not be parsed by Python
SANDBOX_TIMEOUT = "KIR-B002"            # did not finish: CPU time/wall clock
SANDBOX_MEMORY = "KIR-B003"             # memory limit exceeded (RLIMIT_AS)
SANDBOX_FORBIDDEN_IMPORT = "KIR-B004"   # import outside the whitelist
SANDBOX_FORBIDDEN_BUILTIN = "KIR-B005"  # open/eval/exec/id/... — with a reason
SANDBOX_RUNTIME = "KIR-B006"            # any other exception from the script
SANDBOX_NO_OPS = "KIR-B007"             # ran to completion, but produced no program
SANDBOX_BAD_RESULT = "KIR-B008"         # produced something not IR / not JSON-representable
SANDBOX_OUTPUT_LIMIT = "KIR-B009"       # transport ceiling (NOT the author's budget)
SANDBOX_NONDETERMINISM = "KIR-B010"     # object address in the output / different runs
SANDBOX_CRASH = "KIR-B011"              # the process died without saying anything
SANDBOX_UNAVAILABLE = "KIR-B012"        # OUR defect: isolation/language unavailable

#: 🔴 A THIRD KIND OF ANSWER, NOT A THIRTEENTH REFUSAL. The script ran to
#: completion, did not assemble a program — but it ANSWERED: it printed what
#: it was asked (`spec("create_wall")`, `print(model.levels())`). Before
#: 18.08.2026 this move got `KIR-B007` and rode into every metric as a
#: FAILURE.
#:
#: WHAT THIS COST TO BUY. Measurement 17.08: `KIR-B007` — 176 of 463 calls to
#: the language door, 38%, the top refusal with a fivefold lead. Re-measured
#: 18.08 against the night-stand corpus (627 scripts, run through a REAL
#: sandbox) — breakdown in `tests/test_recon_is_not_a_refusal.py`.
#:
#: THE DISTINGUISHER IS PRINTING, and it is verified by both halves, not just
#: declared: recon prints (stdout is non-empty), genuine emptiness stays
#: silent (`x = 1 + 1`, a bare comment — stdout is exactly 0). Both controls
#: stand in the test.
#:
#: WHY THIS IS NOT GREEN. `ok:true` in this tree is a state EARNED by
#: PRODUCING THE EVIDENCE of a record (`serving.green_is_earned`). Recon has
#: no record evidence and cannot have any, so `ok` remains false. What
#: changes is not greenness but the NAME: `refused` is no longer true, and no
#: `err` block is set — recon is not an error, it is an answer to the
#: question asked.
SANDBOX_RECON = "KIR-B013"              # no program, but the script ANSWERED: recon

#: 🔴 SLIDER: a named parameter of the program. A separate code, not B006,
#: and this is a decision. `KIR-B006` is "the script raised an exception,"
#: i.e. the fault of the script's author; here the fault more often lies with
#: the CALLER (supplied a name the author never declared, or a value outside
#: the declared bounds), and its fix is different: not to edit the script,
#: but to correct the parameter set. A code that sends the fix to the wrong
#: place is the named defect of this tree (see the KIR-L001 argument above).
SANDBOX_PARAM = "KIR-B014"              # parameter: name, kind, or bounds
#: 🔴 ASKED FOR SOMETHING WE DID NOT READ — AND THIS IS NOT THE AUTHOR'S
#: FAULT. Set up 25.08.2026 from a measurement: five questions about the
#: model and the building («индекс не подан», «каталог не подан») were
#: arriving as `KIR-B006` with `blame=author`, indistinguishable from `1/0`
#: — while the PROSE of those very refusals said verbatim "this is a fact
#: about OUR reading, not about the building." The model went off to rewrite
#: a correct script and could fix nothing.
#: A separate code, not just `blame`: a machine cannot see the difference
#: from prose alone.
SANDBOX_UNREAD = "KIR-B015"             # asked for something WE did not read

#: 🔴 ALLOWED, BUT NOT INSTALLED — AND THIS IS A FACT ABOUT THE ENVIRONMENT,
#: NOT ABOUT THE SCRIPT. Set up 02.09.2026 (E-85). The library is on the
#: whitelist, but THIS interpreter does not have it (or warm-up failed to
#: load the module before isolation and marked this in the receipt with the
#: `WARM_FAILED_MARK` tag). Until today both cases rode under the wrong code
#: `KIR-B004` "import forbidden" with the fault on the AUTHOR — on a line
#: that has no import at all, only a CALL:
#:
#:     KIR-B004: импорт 'kir.design_check' запрещён, язык уже доступен без
#:     импорта · blame='author', line=8   ← а в строке 8 стоит design_check(...)
#:
#: A separate code, not just `blame`: a machine cannot see the difference
#: from prose alone — the same reasoning `KIR-B015` was set up with. The fix
#: here is to INSTALL THE PACKAGE into the environment the run uses, and only
#: the environment can do that: the whitelist has nothing to do with it,
#: there is nothing to extend, the root is already on it.
SANDBOX_CAPABILITY_ABSENT = "KIR-B016"  # allowed, but not installed in this environment

# ─── R: Refinement — TRANSLATION CERTIFICATE (kir/translation_cert.py) ──────
#
# WHY A SEPARATE LETTER. The stage sits BETWEEN compilation and the first
# effect and judges not the author's program, but OUR OWN emission: is it
# proven that every promised postcondition has a witness, and that this
# witness IS CAPABLE of firing. Mixing it with C (the Roslyn gate rejected the
# C#) would send the fix to the code compiler instead of the witness emitter;
# mixing it with W (postcondition violated at execution) would be a lie that
# something was executed. Nothing was executed: there is no effect by
# construction, and the refusal here is ALWAYS before the write. Letters
# occupied as of 09.08.2026 (measured by grepping the repository): A B C D E G
# L M P S T V W X. R is free, and it reads: Refinement.
# RE-MEASURED 10.08.2026: C is free (the dead `KIR-C001` has been retired);
# occupied: A B D E G L M P S T V W X.
#
# THE FIX ADDRESS FOR ALL THREE IS OUR OWN CODE, NOT THE MODEL'S PROGRAM. The
# author cannot write a program in such a way that a witness comes alive: the
# witness is written by the emitter. That is why an R-refusal has no
# `handoff`: carrying such a record off to a free C# would mean executing it
# with no witness at all, i.e. amplifying exactly the defect it refused for.
CERT_UNPROVEN = "KIR-R001"   # the obligation is not discharged: there is NO witness
CERT_VACUOUS = "KIR-R002"    # a witness EXISTS and is provably unable to fire
CERT_UNCERTIFIABLE = "KIR-R003"  # THE INSTRUMENT STAYS SILENT (no OpRefinementSpec/failure) —
#                                  the record does NOT refuse under this code


# ═════════════════════════════════════════════════════════════════════════
# 🔴 ONE DISPATCHER OF CODES (01.09.2026). READ THIS BEFORE YOU SET UP A CODE.
#
# WHAT THIS COST TO BUY. An `ast` walk over the package's non-executed code
# (`codes_in_tree` below) gives **105** distinct codes: 51 declared here, 40
# as named constants in fourteen other modules, and **15 had NO name AT ALL**
# (`KIR-A001…A010`, `D001`, `L003`, `L005`, `P000`, and the reference kind
# `L004`) — they lived as bare literals in calls.
#
# 🔴 A COLLISION THE GUARD COULD NOT SEE BY CONSTRUCTION. `KIR-L004` carried
# TWO meanings: "ref points to an incompatible typed kind" (`compiler.py`, as
# a bare literal) and `SLOPE_TOO_SHALLOW` (`route_mep.py`). The old
# `code_collisions()` was searching for pairs "NAME = literal" and therefore
# saw EXACTLY ONE name — it printed `{}` on a tree where a collision existed.
# This is exactly our named form: the guard pinned down the SHAPE of the
# first case (two names, the 10.08 incident) instead of the PROPERTY ("a
# code has one meaning"), and the second bite arrived quieter.
#
# WHY THE SLOPE MOVED, NOT THE REFERENCE KIND. The same order as for
# `E009/E010`: the NEWCOMER moves. `route_mep` admitted in its own comment
# that it took the number «заодно с ad-hoc `KIR-L003`, а не заводя
# центральную константу»; the header of group L in this file has declared
# `L004` a reference kind from the very start. The slope gets the free
# `KIR-L008`.
#
# WHAT IS HERE AND WHAT IS NOT. The registry knows the code, the name, the
# home, the dispatcher, the fault, and the taxonomy. It does NOT own the
# constants: they remain in their own modules, and not one emitter moves
# here — the registry knows about them, not in place of them. The meaning of
# a code is NOT here either: it is recorded as a comment next to the constant
# itself, and a second carrier of it would be exactly the defect this whole
# file is written against.
# ═════════════════════════════════════════════════════════════════════════

#: BLAME IS THE ADDRESS OF THE FIX, NOT A REPROACH. The value answers one
#: question: BY WHOSE ACTION the refusal is lifted. Hence the closedness of
#: the list: a fifth value would mean a fifth actor, and there are four.
BLAME_AUTHOR = "author"            # rewrite the program or the script
BLAME_CALLER = "caller"            # fix the envelope, the parameters, the call policy
BLAME_ENVIRONMENT = "environment"  # change the document, the machine, the install, Revit
BLAME_OURS = "ours"                # fix KIR: the author can do nothing
BLAME_NOBODY = "none"              # this is not a refusal (recon): nothing to fix
BLAMES = frozenset({BLAME_AUTHOR, BLAME_CALLER, BLAME_ENVIRONMENT,
                    BLAME_OURS, BLAME_NOBODY})

#: 🔴 THE SANDBOX ALREADY HAD A BLAME DICTIONARY, AND A SECOND ONE MUST NOT
#: BE SET UP. `SandboxRefusal.blame` (kir/sandbox.py) has carried its five
#: values since 03.08, and `serving` branches on them
#: (`refusal.blame == "sandbox"`). This is not a new dictionary, it is a
#: TRANSLATION: for the sandbox, "sandbox" means, verbatim, "OUR defect"
#: (that is literally how it is written in `serving`), i.e. `ours`.
#: "unknown" is not subject to translation and yields `None` — this is a
#: NAMED loss, not a silent one: an unknown blame must look like the absence
#: of an answer, not like "nobody's fault."
SANDBOX_BLAME_TO_DIAG: dict[str, Optional[str]] = {
    "author": BLAME_AUTHOR,
    "caller": BLAME_CALLER,
    "sandbox": BLAME_OURS,
    #: 🔴 A SIXTH VALUE, SET UP TOGETHER WITH `KIR-B016` (02.09.2026).
    #: "The capability is absent IN THIS ENVIRONMENT" is neither our defect
    #: nor the author's mistake: the fix is installing the package, and that
    #: is done by whoever owns the environment. Recording this as `sandbox`
    #: (=`ours`) would promise a fix on our side where there is nothing for
    #: us to fix.
    "environment": BLAME_ENVIRONMENT,
    "none": BLAME_NOBODY,
    "unknown": None,
}

# ─── NAMES OF THE FIFTEEN CODES THAT LIVED AS BARE LITERALS ──────────────
#
# The constants are set up HERE, and the literals themselves in other
# modules are NOT TOUCHED: this is an additive edit, the wire does not move
# by a single byte. Our own (`compiler.py`, `connect.py`) are switched over
# to the names in this same commit.
INTERNAL_PANIC = "KIR-P000"                 # internal compiler error
PLAN_REF_ORDER = "KIR-L003"                 # ref/address does not point to an earlier op
PLAN_REF_KIND = "KIR-L004"                  # ref points to an incompatible result kind
PLAN_BULK_MISMATCH = "KIR-L005"             # bulk policy did not match the finished plan
PLAN_DESTRUCTIVE_UNCONFIRMED = "KIR-D001"   # delete without allow_destructive in the envelope
# L009 (07.09.2026): the host of a door/window was shifted along Z by THAT
# SAME program before the hosted op. The door point is measured from the
# level, not from the wall, and after a vertical shift of the host it
# becomes inexpressible — a refusal by name, not a guess.
PLAN_HOST_MOVED_VERTICALLY = "KIR-L009"     # the host of a hosted op was shifted along Z before it, in the same program
# L010 (07.09.2026): a reference to a target that THAT SAME program has
# already deleted (`delete X → move/change_type/delete X`). Live, this is a
# "stale id" after a round trip; at the plan stage the order of ops is
# known — the refusal happens here, by name.
PLAN_REF_DELETED = "KIR-L010"               # reference to a target deleted earlier in the same program
ACCEPT_CENSUS_BEFORE_UNAVAILABLE = "KIR-A001"   # independent census BEFORE the write is unavailable
ACCEPT_GROUND_MISMATCH = "KIR-A002"             # grounding context did not match the snapshot
ACCEPT_CENSUS_AFTER_UNAVAILABLE = "KIR-A003"    # census AFTER the write is unavailable
ACCEPT_NO_EXECUTABLE_ARTEFACT = "KIR-A004"      # the record has no executable artifact
ACCEPT_EVIDENCE_STORE_UNSET = "KIR-A005"        # the evidence store is not configured
ACCEPT_INDEPENDENT_REJECTED = "KIR-A006"        # independent acceptance did not agree
ACCEPT_UNCONFIRMED = "KIR-A007"                 # execution not confirmed
ACCEPT_DURABILITY_FAILED = "KIR-A008"           # the evidence did not land on disk
ACCEPT_PRECONDITION_UNMET = "KIR-A009"          # acceptance precondition not met
ACCEPT_ARTEFACT_UNBOUND = "KIR-A010"            # artifact not bound to the context


@dataclass(frozen=True)
class CodeSpec:
    """A registry row. `name`/`home` are the ADDRESS of the constant, not a
    copy of it."""
    code: str
    name: str
    home: str        # module where the constant sits (relative to the package)
    family: str      # the letter's dispatcher: who is entitled to set up a neighboring number
    blame: str       # by whose action the refusal is lifted
    #: THE OUTCOME OF THE CLOSED TAXONOMY (the name of an `envelope.ErrCode`
    #: member). Since 02.09.2026 the column does not DESCRIBE the owner, it
    #: DECIDES for it: `serving`'s `_classify_refusal` reads it instead of its
    #: six own tables.
    taxonomy: str


CODES: dict[str, CodeSpec] = {}
_NAMES: dict[str, str] = {}


#: THE OUTCOME THAT TELLS THE AUTHOR "FIX THE PROGRAM." A name, not an
#: object: it is recorded in the registry as a string, and checked against
#: `ErrCode` below.
_TAXONOMY_BLAMING_THE_AUTHOR = "KIR_PROGRAM_REFUSED"

#: 🔴 BLAME DOES NOT COMPUTE THE OUTCOME, BUT IT FORBIDS ONE. THIS IS A
#: MEASUREMENT, NOT CAUTION.
#:
#: The intent of stage 3.1 was phrased as "derive `ErrCode` FROM BLAME" and
#: retire the six handwritten tables `serving._KIR_*_TO_ERRCODE`. The first
#: half is REFUTED by a run on 02.09.2026 over 106 set-up codes:
#:
#:     blame author       -> 2 outcomes
#:     blame environment  -> 5 outcomes
#:     blame ours         -> 5 outcomes
#:     (blame, family)    -> 4 ambiguous pairs out of 37, 19 codes
#:
#: A function from blame does not exist, and this is not a gap in the
#: registry but TWO DIFFERENT AXES: blame answers "WHO fixes it," the
#: taxonomy answers "WHAT happened to the world" (nothing happened · rolled
#: back · wrote and violated · unknown). `KIR-X003` (drift) and `KIR-X007`
#: (silence) are both environment, and the difference between them is
#: "retry" versus "retrying is FORBIDDEN, the write may have landed."
#:
#: What blame DOES — it forbids one outcome: a refusal whose fix is not the
#: author's must not tell the author "fix the program." This is verifiable,
#: and it is verified here, at the single door, not by a guard laid over a
#: finished tree.
_BLAMES_THAT_MAY_NOT_BLAME_THE_AUTHOR = (BLAME_OURS, BLAME_ENVIRONMENT)


def register(code: str, *, name: str, home: str, family: str,
             blame: str, taxonomy: str) -> CodeSpec:
    """Register a code. THE SAME CODE OR THE SAME NAME TWICE — a refusal ON
    IMPORT.

    A guarantee by construction, not merely a checked one: a second
    dispatcher cannot appear unnoticed, because registration is the one
    door.
    """
    if blame not in BLAMES:
        raise AssertionError(f"{code}: вина {blame!r} вне закрытого списка {sorted(BLAMES)}")
    if (blame in _BLAMES_THAT_MAY_NOT_BLAME_THE_AUTHOR
            and taxonomy == _TAXONOMY_BLAMING_THE_AUTHOR):
        raise AssertionError(
            f"{code} ({name}): вина {blame!r} — ремонт НЕ У АВТОРА, а исход "
            f"{taxonomy} говорит модели «правь программу». Автор верной "
            f"программы получил бы приказ переписать её за чужой сбой. "
            f"Возьми исход, называющий правду: `KIR_PRECONDITION_UNMET` — "
            f"мир не в том состоянии (эффекта не было), `INTERNAL_UNHANDLED` "
            f"— наша поломка (повторять бессмысленно), `KIR_UNCONFIRMED` — "
            f"запись могла лечь")
    if code in CODES:
        raise AssertionError(
            f"{code}: код уже занят именем {CODES[code].name!r} ({CODES[code].home}). "
            f"Код на проводе обещает ОДИН ремонт; возьми свободный номер своей буквы")
    if name in _NAMES:
        raise AssertionError(
            f"{name}: имя уже носит {_NAMES[name]}. Одно имя — один код")
    spec = CodeSpec(code=code, name=name, home=home, family=family,
                    blame=blame, taxonomy=taxonomy)
    CODES[code] = spec
    _NAMES[name] = code
    return spec


#: code · constant name · home · dispatcher · blame · OUTCOME.
#:
#: 🔴 THE OUTCOME HERE IS A DECISION, NOT A DESCRIPTION (02.09.2026). Before
#: that day the column was retelling what six tables
#: `serving._KIR_*_TO_ERRCODE` do, and they agreed only because a guard
#: cross-checked them BY CALLING both: two quantities required to match. The
#: tables have been retired, the consumer reads from here (`taxonomy_of`),
#: and the guard `test_the_outcome_is_read_from_the_registrar` holds the
#: converse — that a second table has not been set up.
_ROWS: tuple[tuple[str, str, str, str, str, str], ...] = (
    # ── P: program parsing ──────────────────────────────────────────────
    # 🔴 WAS "KIR_PROGRAM_REFUSED", BECAME "INTERNAL_UNHANDLED" (02.09.2026).
    # The owner was dropping OUR OWN panic into "fix the program": it had no
    # `KIR-P` arm at all, and the code fell through to the letter's default.
    # The author of a correct program was given an order to rewrite it for
    # our failure, and `retryable=True` invited them to send the same
    # program again — and get the same panic. `internal.unhandled`
    # (retryable=False) tells the truth and matches the flat form of the
    # same fact: `_FLAT_ERROR_TO_ERRCODE["internal"]`.
    (INTERNAL_PANIC, "INTERNAL_PANIC", "diag.py", "parse", BLAME_OURS, "INTERNAL_UNHANDLED"),
    (PARSE_NOT_OBJECT, "PARSE_NOT_OBJECT", "diag.py", "parse", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PARSE_UNKNOWN_OP, "PARSE_UNKNOWN_OP", "diag.py", "parse", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PARSE_UNKNOWN_FIELD, "PARSE_UNKNOWN_FIELD", "diag.py", "parse", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PARSE_BAD_VERSION, "PARSE_BAD_VERSION", "diag.py", "parse", BLAME_CALLER, "KIR_PROGRAM_REFUSED"),
    (PARSE_MISSING_FIELD, "PARSE_MISSING_FIELD", "diag.py", "parse", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PARSE_DUP_ID, "PARSE_DUP_ID", "diag.py", "parse", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PARSE_EXCLUSIVE_FIELDS, "PARSE_EXCLUSIVE_FIELDS", "diag.py", "parse", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # ── G: grounding, axes, element address ───────────────────────────────
    (GROUND_UNSUPPORTED_KIND, "GROUND_UNSUPPORTED_KIND", "diag.py", "ground", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (GROUND_BAD_SELECTOR, "GROUND_BAD_SELECTOR", "diag.py", "ground", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-G101", "GROUND_NOT_FOUND", "ground.py", "ground", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-G102", "GROUND_AMBIGUOUS", "ground.py", "ground", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-G103", "GROUND_NO_SNAPSHOT", "ground.py", "ground", BLAME_CALLER, "KIR_PROGRAM_REFUSED"),
    ("KIR-G104", "GROUND_EMPTY_POOL", "ground.py", "ground", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-G106", "GROUND_BAD_SNAPSHOT", "ground.py", "ground", BLAME_CALLER, "KIR_PROGRAM_REFUSED"),
    # G107: proof of binding to the OPEN document did not check out — the
    # world is not in the state the program assumed. The flat form of the
    # same fact already says so: `_FLAT_ERROR_TO_ERRCODE["ground"]` and
    # `["open_model_preflight"]` — both `KIR_PRECONDITION_UNMET`.
    (GROUND_MODEL_BINDING, "GROUND_MODEL_BINDING", "diag.py", "ground", BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    ("KIR-G108", "GRID_NOT_FOUND", "relate.py", "grid", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-G109", "GRID_AMBIGUOUS", "relate.py", "grid", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-G110", "GRID_NO_INTERSECTION", "relate.py", "grid", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # G111: the grid in the DOCUMENT is an arc, it has no straight geometry.
    # The program is correct; what needs to change is the document, not it.
    ("KIR-G111", "GRID_NO_GEOMETRY", "relate.py", "grid", BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    ("KIR-G112", "GRID_TOWARD_INVALID", "relate.py", "grid", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-G113", "ELEMENT_REF_UNKNOWN", "relate.py", "element-ref", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-G114", "ELEMENT_NOT_ADDRESSABLE", "relate.py", "element-ref", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-G115", "ELEMENT_PART_INVALID", "relate.py", "element-ref", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # G116: the level elevation is not in the snapshot — a gap in OUR OWN
    # capture. The same kind as `SANDBOX_UNREAD` ("asked for something WE did
    # not read"), and the same outcome: the very same program will go through
    # without a single edit as soon as we read it.
    ("KIR-G116", "ELEMENT_CAPTURE_GAP", "relate.py", "element-ref", BLAME_OURS, "KIR_PRECONDITION_UNMET"),
    # ── T: types and bounds ────────────────────────────────────────────────
    (TYPE_BAD_TYPE, "TYPE_BAD_TYPE", "diag.py", "type", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (TYPE_BOUNDS, "TYPE_BOUNDS", "diag.py", "type", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (TYPE_BAD_ENUM, "TYPE_BAD_ENUM", "diag.py", "type", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (TYPE_GEOM_RELATION, "TYPE_GEOM_RELATION", "diag.py", "type", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # ── L: the program plan ────────────────────────────────────────────────
    (PLAN_LIMIT, "PLAN_LIMIT", "diag.py", "plan", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PLAN_SOLO_OP, "PLAN_SOLO_OP", "diag.py", "plan", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PLAN_REF_ORDER, "PLAN_REF_ORDER", "diag.py", "plan", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PLAN_REF_KIND, "PLAN_REF_KIND", "diag.py", "plan", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PLAN_BULK_MISMATCH, "PLAN_BULK_MISMATCH", "diag.py", "plan", BLAME_CALLER, "KIR_PROGRAM_REFUSED"),
    (PLAN_PHASE_SHAPE, "PLAN_PHASE_SHAPE", "diag.py", "plan", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # L007: a writing op has no complete lowering contract — WE are the ones
    # who write it.
    (PLAN_OP_CONTRACT, "PLAN_OP_CONTRACT", "diag.py", "plan", BLAME_OURS, "KIR_PRECONDITION_UNMET"),
    ("KIR-L008", "SLOPE_TOO_SHALLOW", "route_mep.py", "plan", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PLAN_HOST_MOVED_VERTICALLY, "PLAN_HOST_MOVED_VERTICALLY", "diag.py", "plan", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (PLAN_REF_DELETED, "PLAN_REF_DELETED", "diag.py", "plan", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # ── D: destructive operations ──────────────────────────────────────────
    (PLAN_DESTRUCTIVE_UNCONFIRMED, "PLAN_DESTRUCTIVE_UNCONFIRMED", "diag.py", "destructive", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # ── E: emission and versions ──────────────────────────────────────────────
    (EMIT_VERSION, "EMIT_VERSION", "diag.py", "emit", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # E002: the grounded id came FROM THE DOCUMENT and cannot be expressed on
    # this version of Revit. Neither the id nor the version is under the
    # author's control.
    ("KIR-E002", "EMIT_ID_RANGE", "authoring.py", "emit", BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    (EMIT_UNSUPPORTED, "EMIT_UNSUPPORTED", "diag.py", "emit", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-E004", "FOUNDATION_UNSUPPORTED_KIND", "struct_emit.py", "emit", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # E005: the EMISSION guard's contract is violated — the code is written
    # by the emitter, not the author. The same canon as `KIR-R*`: there is no
    # effect by construction, the refusal is before the write.
    ("KIR-E005", "EMIT_GUARD_CONTRACT", "authoring.py", "emit", BLAME_OURS, "KIR_PRECONDITION_UNMET"),
    ("KIR-E006", "RAILING_UNSUPPORTED_VARIETY", "arch_emit.py", "emit", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (EMIT_UNSUPPORTED_ENUM, "EMIT_UNSUPPORTED_ENUM", "diag.py", "emit", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (EMIT_CONTOUR_HOLES, "EMIT_CONTOUR_HOLES", "diag.py", "emit", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-E009", "BEAM_SYSTEM_BAD_DIRECTION_EDGE", "struct_emit.py", "emit", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (EMIT_CONTOUR_SPLINE, "EMIT_CONTOUR_SPLINE", "diag.py", "emit", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-E012", "ANALYSIS_ZERO_LOAD", "analysis_emit.py", "emit", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # ── B: the sandbox for the authored script ──────────────────────────────────
    #
    # THE ANSWER TO "RETRYABLE?" — AND IT IS NOT BY ANALOGY, IT IS FROM TWO
    # FACTS. (The reasoning moved here 02.09.2026 from the retired table
    # `serving._KIR_B_TO_ERRCODE`: this column decides now, so the reasoning
    # lives alongside it.)
    #
    # FACT ONE, THE DECISIVE ONE: NOTHING HAPPENED. The sandbox sits BEFORE
    # the compiler, BEFORE the bridge, and BEFORE any transaction; its one
    # output is a list of operations, and on a refusal there is none. So
    # there is nothing here for a ban on retrying to protect:
    # `retryable=false` in this system means exactly one thing — "the effect
    # may have happened, a retry would duplicate it." A script that fell on a
    # syntax error created not a single element, and the next attempt must
    # happen.
    #
    # FACT TWO: THE REFUSAL IS DETERMINISTIC. The same source will give the
    # same error — that is what `author_digest` stands on. That is why
    # `transient=false` for all of them: waiting and sending the same thing
    # again is pointless, what needs fixing is the SOURCE. This is exactly
    # the semantics of `kir.program_refused`, not `transport.*`: the refusal
    # code names a line of the script, i.e. the address of the fix.
    #
    # B002/B003 (stack and memory) are weighed separately and are
    # DELIBERATELY left as the author's: they look "floating," but their
    # cause is an endless loop or memory accumulation, i.e. a property of the
    # SCRIPT. Declaring them transient would mean advising the model to send
    # the same infinite loop again. B011 out of this trio was RETRACTED
    # 02.09.2026 — see its line below.
    (SANDBOX_SYNTAX, "SANDBOX_SYNTAX", "diag.py", "sandbox", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (SANDBOX_TIMEOUT, "SANDBOX_TIMEOUT", "diag.py", "sandbox", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (SANDBOX_MEMORY, "SANDBOX_MEMORY", "diag.py", "sandbox", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (SANDBOX_FORBIDDEN_IMPORT, "SANDBOX_FORBIDDEN_IMPORT", "diag.py", "sandbox", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (SANDBOX_FORBIDDEN_BUILTIN, "SANDBOX_FORBIDDEN_BUILTIN", "diag.py", "sandbox", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (SANDBOX_RUNTIME, "SANDBOX_RUNTIME", "diag.py", "sandbox", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (SANDBOX_NO_OPS, "SANDBOX_NO_OPS", "diag.py", "sandbox", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (SANDBOX_BAD_RESULT, "SANDBOX_BAD_RESULT", "diag.py", "sandbox", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (SANDBOX_OUTPUT_LIMIT, "SANDBOX_OUTPUT_LIMIT", "diag.py", "sandbox", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (SANDBOX_NONDETERMINISM, "SANDBOX_NONDETERMINISM", "diag.py", "sandbox", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # 🔴 B011: WAS "KIR_PROGRAM_REFUSED." The prose in `serving` filed it
    # under script properties alongside B002/B003 — but those carry the
    # blame `author`, while B011 carries `ours`, and it is issued with
    # `blame="unknown"`: "the process was killed by a signal and returned no
    # result." Its neighbor on the same shelf — B012 ("returned no result")
    # — is already `INTERNAL_UNHANDLED`; two neighboring silences must sound
    # the same, and there is no reason to make the author retry the same
    # thing.
    (SANDBOX_CRASH, "SANDBOX_CRASH", "diag.py", "sandbox", BLAME_OURS, "INTERNAL_UNHANDLED"),
    # B012 — OUR OWN defect (`blame="sandbox"`): the namespace was not
    # created, the language did not load, the child returned no result. The
    # model has nothing to fix, and telling it "retryable" would mean sending
    # it off to rewrite a CORRECT script. `internal.unhandled` (False, False)
    # tells the truth: retrying is pointless. What to do is said by the
    # refusal text: the same program can be sent through the `ops` field, the
    # execution path does not change because of this.
    (SANDBOX_UNAVAILABLE, "SANDBOX_UNAVAILABLE", "diag.py", "sandbox", BLAME_OURS, "INTERNAL_UNHANDLED"),
    # B013 — RECON, AND THIS LINE IS READ ONLY WHEN WE OURSELVES BROKE.
    # A recon move never reaches the taxonomy: `serving._stamp_refusal`
    # refuses to set `err` STRUCTURALLY, based on `res["recon"] is True`. So
    # the only world where this line gets read is one where the branch above
    # broke; hence this is OUR OWN defect here, not the author's refusal.
    #
    # 🔴 WHY THE LINE WAS SET UP ANYWAY, EVEN THOUGH THE 18.08 WAVE DID NOT
    # SET IT UP. Its reasoning: "adding it means setting up two quantities
    # that are required to match." Correct in form and wrong in fact, and
    # this is verified by EXECUTION: without the line, an unknown code gave
    # `KIR_PROGRAM_REFUSED` by default, i.e. EXACTLY the outcome the wave was
    # afraid of, and gave it SILENTLY. The absence of the line is not a
    # refusal, it is a quiet default; the line, set up, plus the loud record
    # in `serving._classify_refusal`, make "unreachable" audible.
    (SANDBOX_RECON, "SANDBOX_RECON", "diag.py", "sandbox", BLAME_NOBODY, "INTERNAL_UNHANDLED"),
    # B014 — A SLIDER, and the outcome here is a PROGRAM refusal, though the
    # fault more often lies with the CALLER. The outcome names the KIND of
    # error of the move, not the address of the fix: the address is carried
    # by the `blame` column ("caller" — fix the parameter set), and it
    # reaches the reader in full. Declaring the move an internal defect would
    # mean saying "this is our own breakage" where the program was rejected
    # LEGITIMATELY and for a named reason. It, and five others, are the
    # measured remainder `blame_taxonomy_debt`.
    (SANDBOX_PARAM, "SANDBOX_PARAM", "diag.py", "sandbox", BLAME_CALLER, "KIR_PROGRAM_REFUSED"),
    # B015 — the building index or the catalog was not supplied to THIS turn
    # (an offline run, or the plugin has not sent context yet). The script is
    # CORRECT, and "fix the program" would send the model off to rewrite
    # something that has no error in it.
    (SANDBOX_UNREAD, "SANDBOX_UNREAD", "diag.py", "sandbox", BLAME_OURS, "KIR_PRECONDITION_UNMET"),
    (SANDBOX_CAPABILITY_ABSENT, "SANDBOX_CAPABILITY_ABSENT", "diag.py", "sandbox", BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    # ── B1xx: boolean operations. A SEPARATE DISPATCHER OF THE SAME LETTER ──────
    # The hundred separates them from the sandbox deliberately: one letter,
    # two dispatchers, and the neighboring free number is DIFFERENT for each.
    ("KIR-B101", "BOOLEAN_DISJOINT", "ops_boolean.py", "boolean", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-B102", "BOOLEAN_NESTED", "ops_boolean.py", "boolean", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # ── M: macros and mesh ─────────────────────────────────────────────────
    ("KIR-M001", "MACRO_ERROR", "macros.py", "macro", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-M002", "MESH_INDEX_RANGE", "mesh.py", "mesh", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-M003", "MESH_DEGENERATE", "mesh.py", "mesh", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-M004", "MESH_UNUSED_VERTEX", "mesh.py", "mesh", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-M005", "MESH_DUPLICATE_FACE", "mesh.py", "mesh", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-M006", "MESH_DISCONNECTED", "mesh.py", "mesh", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # ── S: surface and passport. TWO DISPATCHERS OF ONE LETTER ──────────
    ("KIR-S001", "PASSPORT_NODE_NOT_FOUND", "decompile/passport.py", "passport", BLAME_CALLER, "KIR_PROGRAM_REFUSED"),
    ("KIR-S002", "SURFACE_KNOTS", "surface.py", "surface", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-S003", "SURFACE_CORNER", "surface.py", "surface", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-S004", "SURFACE_DEGENERATE", "surface.py", "surface", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # ── C: the standalone connector ──────────────────────────────────────────
    # The letter and the number were not picked at random: the registry
    # itself recorded on 10.08.2026 that C was FREED — the former `KIR-C001`
    # (COMPILE_FAIL) was never issued and was retired (see the notes at
    # SANDBOX_* and CERT_*). The number is reused deliberately: it breaks no
    # promise on the wire, because nobody ever heard the old promise.
    # 🔴 WHY A NEW CODE, NOT SOMEONE ELSE'S. The closest in meaning is
    # `KIR-B016` (SANDBOX_CAPABILITY_ABSENT): the same blame `environment`,
    # the same outcome, but its home is `sandbox.py`, and the code on the
    # wire promises the fix EXACTLY there. `KIR-E003` (EMIT_UNSUPPORTED),
    # meaning "the op is unavailable on this target," fits by sense, but its
    # blame is `author`, and the author of a correct program has nothing to
    # do with this: the second document does not exist for the ENVIRONMENT.
    # The outcome is `KIR_PRECONDITION_UNMET`, because the refusal happens
    # BEFORE sending: the world is not in the required state, and nothing has
    # gone to the model.
    ("KIR-C001", "CONNECTOR_SECOND_DOCUMENT_UNAVAILABLE", "revit_connector.py",
     "connector", BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    # ── V: the judge of intent ─────────────────────────────────────────────────
    ("KIR-V001", "PROGRAM_SHAPE", "design_check.py", "verify", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-V002", "BUNDLE_CONTRACT", "design_check.py", "verify", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-V003", "PROGRAM_NOT_BUILDABLE", "design_check.py", "verify", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    # ── K: chunking of a live turn ───────────────────────────────────────
    # K001/K002 — preconditions FIXABLE BY THE AUTHOR, and both reach the
    # model with a full instruction in `message_ru`. Retry safety is decided
    # NOT by the outcome, but by `outcome.retry`: for a partially built
    # program it is `forbidden`, and `serving._stamp_refusal` strips
    # `retryable` regardless of the code.
    # K003 — a chunk refused without naming a code: execution HAD BEGUN and
    # did not succeed.
    ("KIR-K001", "CHUNK_OP_TOO_BIG", "chunking.py", "chunk", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-K002", "KIR_CHUNK_BIND_FAILED", "serving.py", "chunk", BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    ("KIR-K003", "KIR_CHUNK_PARTIAL", "serving.py", "chunk", BLAME_ENVIRONMENT, "KIR_RUNTIME_REFUSED"),
    # ── A: acceptance. Blame here is ALMOST NEVER the author's ──────────────────
    #
    # TWO HALVES, AND THE BOUNDARY BETWEEN THEM IS A FACT ABOUT THE WORLD,
    # NOT ABOUT BLAME (the reasoning moved 02.09.2026 from the retired table
    # `serving._KIR_A_TO_ERRCODE`):
    #   · A001 A002 A005 A009 A010 — preconditions of INDEPENDENT READING and
    #     durability, checked BEFORE the effect: there was no write;
    #   · A003 A004 A007 A008 — the write has ALREADY happened or may have
    #     happened, and a retry would duplicate the construction, hence
    #     `KIR_UNCONFIRMED` (retryable=False): read the model back, don't
    #     send again.
    # The blame for all of them except A004/A010 is one and the same
    # (`environment`) — here is a clear demonstration that the outcome is not
    # derivable from the blame.
    (ACCEPT_CENSUS_BEFORE_UNAVAILABLE, "ACCEPT_CENSUS_BEFORE_UNAVAILABLE", "diag.py", "acceptance", BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    (ACCEPT_GROUND_MISMATCH, "ACCEPT_GROUND_MISMATCH", "diag.py", "acceptance", BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    (ACCEPT_CENSUS_AFTER_UNAVAILABLE, "ACCEPT_CENSUS_AFTER_UNAVAILABLE", "diag.py", "acceptance", BLAME_ENVIRONMENT, "KIR_UNCONFIRMED"),
    (ACCEPT_NO_EXECUTABLE_ARTEFACT, "ACCEPT_NO_EXECUTABLE_ARTEFACT", "diag.py", "acceptance", BLAME_OURS, "KIR_UNCONFIRMED"),
    (ACCEPT_EVIDENCE_STORE_UNSET, "ACCEPT_EVIDENCE_STORE_UNSET", "diag.py", "acceptance", BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    (ACCEPT_INDEPENDENT_REJECTED, "ACCEPT_INDEPENDENT_REJECTED", "diag.py", "acceptance", BLAME_ENVIRONMENT, "KIR_RUNTIME_REFUSED"),
    (ACCEPT_UNCONFIRMED, "ACCEPT_UNCONFIRMED", "diag.py", "acceptance", BLAME_ENVIRONMENT, "KIR_UNCONFIRMED"),
    (ACCEPT_DURABILITY_FAILED, "ACCEPT_DURABILITY_FAILED", "diag.py", "acceptance", BLAME_ENVIRONMENT, "KIR_UNCONFIRMED"),
    (ACCEPT_PRECONDITION_UNMET, "ACCEPT_PRECONDITION_UNMET", "diag.py", "acceptance", BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    (ACCEPT_ARTEFACT_UNBOUND, "ACCEPT_ARTEFACT_UNBOUND", "diag.py", "acceptance", BLAME_OURS, "KIR_PRECONDITION_UNMET"),
    # ── R: the translation certificate. Canon: the fix address for all three is OURS ───
    #
    # A PRECONDITION, NOT EXECUTION, AND THIS IS A REASON, NOT A HABIT. The
    # refusal is issued BETWEEN compilation and the first touch of the
    # bridge: there was no transaction, no acceptance snapshot, the model was
    # not touched. This is exactly the semantics of `KIR_PRECONDITION_UNMET`
    # — the world (in this case OUR OWN emission) is not in the state the
    # write assumed — and NOT `KIR_PROGRAM_REFUSED`: fixing the author's
    # program is pointless, the witness is written by the emitter, and the
    # very same program will pass tomorrow without a single edit, as soon as
    # we are fixed. This same reasoning closed E005, G116, and L007 on
    # 02.09.2026.
    #
    # R003 does not turn into a refusal (the instrument stays silent ⇒ we
    # skip it), but the code must still be classifiable: it rides in the
    # SUCCESS receipt.
    # ── R (continued): TRANSLATION-DEVIATION NUMBERS, `refine/deviation.py` ──
    #
    # The same letter is no accident: R reads "Refinement," and R001–R003 are
    # the translation certificate of one operation, while R004+ measure the
    # translation of a WHOLE shell into a set of elements. One subject, two
    # halves.
    #
    # 🔴 WHY NOT ONE OF THEM BLAMES THE AUTHOR, EXCEPT ONE. The author wrote a
    # correct program; the fact that `BRepAlgoAPI_Common` on a twisted loft
    # returns emptiness with `IsDone() == True` (measured 07.09.2026,
    # threshold 9°, all three example towers in the failure zone) is a
    # property of the KERNEL, and is not cured by editing the program. The
    # sole exception is `KIR-R015`: the floor outline is written by the
    # author, and self-intersection is fixed right there.
    #
    # The outcome for all of them is `KIR_PRECONDITION_UNMET`: the
    # measurement happens BEFORE any write, the model was not touched, a
    # retry with the same input will give the same result.
    ("KIR-R004", "DEVIATION_KERNEL_UNAVAILABLE", "refine/deviation.py", "deviation",
     BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    ("KIR-R005", "DEVIATION_BOOLEAN_NOT_DONE", "refine/deviation.py", "deviation",
     BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    ("KIR-R006", "DEVIATION_BOOLEAN_CONTRADICTS_WITNESS", "refine/deviation.py", "deviation",
     BLAME_ENVIRONMENT, "KIR_PRECONDITION_UNMET"),
    ("KIR-R007", "DEVIATION_SOURCE_HAS_NO_BODY", "refine/deviation.py", "deviation",
     BLAME_CALLER, "KIR_PRECONDITION_UNMET"),
    ("KIR-R008", "DEVIATION_DERIVED_HAS_NO_BODY", "refine/deviation.py", "deviation",
     BLAME_CALLER, "KIR_PRECONDITION_UNMET"),
    ("KIR-R009", "DEVIATION_DEGENERATE_BODY", "refine/deviation.py", "deviation",
     BLAME_CALLER, "KIR_PRECONDITION_UNMET"),
    ("KIR-R010", "DEVIATION_NULL_SHAPE", "refine/deviation.py", "deviation",
     BLAME_CALLER, "KIR_PRECONDITION_UNMET"),
    ("KIR-R011", "DEVIATION_MIRRORED_FRAME", "refine/deviation.py", "deviation",
     BLAME_CALLER, "KIR_PRECONDITION_UNMET"),
    ("KIR-R012", "DEVIATION_INVALID_FRAME", "refine/deviation.py", "deviation",
     BLAME_CALLER, "KIR_PRECONDITION_UNMET"),
    # R013 — THE CEILING OF OUR OWN INSTRUMENT, not a property of the input:
    # the mesh converges from below and non-monotonically (200/50/20 mm ->
    # 145.81/184.78/187.95 against an oracle of 190.3012), and "did not
    # converge" means "our instrument cannot do that much."
    ("KIR-R013", "DEVIATION_MAX_NOT_BOUNDED", "refine/deviation.py", "deviation",
     BLAME_OURS, "KIR_PRECONDITION_UNMET"),
    ("KIR-R014", "DEVIATION_BUDGET_EXHAUSTED", "refine/deviation.py", "deviation",
     BLAME_CALLER, "KIR_PRECONDITION_UNMET"),
    ("KIR-R015", "DEVIATION_PLAN_CONTOUR_UNUSABLE", "refine/deviation.py", "deviation",
     BLAME_AUTHOR, "KIR_PROGRAM_REFUSED"),
    (CERT_UNPROVEN, "CERT_UNPROVEN", "diag.py", "cert", BLAME_OURS, "KIR_PRECONDITION_UNMET"),
    (CERT_VACUOUS, "CERT_VACUOUS", "diag.py", "cert", BLAME_OURS, "KIR_PRECONDITION_UNMET"),
    (CERT_UNCERTIFIABLE, "CERT_UNCERTIFIABLE", "diag.py", "cert", BLAME_OURS, "KIR_PRECONDITION_UNMET"),
    # ── X: execution in Revit ───────────────────────────────────────────
    (X_SHORT_CURVE, "X_SHORT_CURVE", "diag.py", "execute", BLAME_AUTHOR, "KIR_RUNTIME_REFUSED"),
    (X_LOOPS_INTERSECT, "X_LOOPS_INTERSECT", "diag.py", "execute", BLAME_AUTHOR, "KIR_RUNTIME_REFUSED"),
    (X_STALE, "X_STALE", "diag.py", "execute", BLAME_ENVIRONMENT, "KIR_RUNTIME_REFUSED"),
    (X_POSTCONDITIONS, "X_POSTCONDITIONS", "diag.py", "execute", BLAME_ENVIRONMENT, "KIR_POSTCONDITION_VIOLATED"),
    (X_TXN, "X_TXN", "diag.py", "execute", BLAME_ENVIRONMENT, "KIR_RUNTIME_REFUSED"),
    (X_DUPLICATE_NAME, "X_DUPLICATE_NAME", "diag.py", "execute", BLAME_AUTHOR, "KIR_RUNTIME_REFUSED"),
    (X_TIMEOUT, "X_TIMEOUT", "diag.py", "execute", BLAME_ENVIRONMENT, "KIR_UNCONFIRMED"),
    (X_RECEIPT, "X_RECEIPT", "diag.py", "execute", BLAME_OURS, "KIR_RUNTIME_REFUSED"),
    (X_OP_REFUSED, "X_OP_REFUSED", "diag.py", "execute", BLAME_ENVIRONMENT, "KIR_RUNTIME_REFUSED"),
    (X_UNCLASSIFIED, "X_UNCLASSIFIED", "diag.py", "execute", BLAME_ENVIRONMENT, "KIR_RUNTIME_REFUSED"),
    # ── W: the witness after commit ───────────────────────────────────────
    (W_POSTCONDITIONS_COMMITTED, "W_POSTCONDITIONS_COMMITTED", "diag.py", "witness", BLAME_ENVIRONMENT, "KIR_POSTCONDITION_VIOLATED"),
)

for _row in _ROWS:
    register(_row[0], name=_row[1], home=_row[2], family=_row[3],
             blame=_row[4], taxonomy=_row[5])
del _row


def _lint_taxonomies() -> None:
    """THE OUTCOME IS A NAME FROM THE CLOSED TAXONOMY, AND THIS IS CHECKED ON
    IMPORT.

    Since 02.09.2026 the `taxonomy` column does not describe the owner, it
    DECIDES for it: `serving._classify_refusal` reads it instead of its six
    own tables. A typo in the name would become a refusal on a live turn —
    exactly where the refusal is being built so that the cause is not lost.
    We catch it here, once, on import.

    Importing `envelope` is cheap and safe: the module is clean (`re`,
    `enum`, `typing`) and pulls in neither the compiler, nor the bridge, nor
    KUKAY.
    """
    from kir.envelope import ErrCode
    unknown = sorted({spec.taxonomy for spec in CODES.values()
                      if spec.taxonomy not in ErrCode.__members__})
    if unknown:
        raise AssertionError(
            f"исход(ы) {unknown} нет в закрытой таксономии `ErrCode`: "
            f"допустимы {sorted(ErrCode.__members__)}")


_lint_taxonomies()


def spec_of(code: str) -> Optional[CodeSpec]:
    """A registry row, or `None`. `None` means «код не заведён», not «вины
    нет»."""
    return CODES.get(code)


def blame_of(code: str) -> Optional[str]:
    """By whose action the refusal is lifted. `None` for an unregistered
    code."""
    spec = CODES.get(code)
    return spec.blame if spec is not None else None


def taxonomy_of(code: str) -> Optional[str]:
    """The NAME of the closed-taxonomy outcome (`ErrCode`). `None` means the
    code is not set up.

    🔴 THE ONE CARRIER, NOT A SECOND ONE (02.09.2026). Before this day the
    outcome lived TWICE: here, as a description, and in six handwritten
    tables `serving._KIR_{X,W,A,K,R,B}_TO_ERRCODE`, as a decision. Two
    quantities required to match, and they agreed only because a guard
    cross-checked them by calling both. Now the consumer READS from here,
    instead of retelling it.

    `None` means «код не заведён», not «исхода нет»: lying in that direction
    is not allowed, and on `None` the consumer takes the named default for
    the letter.
    """
    spec = CODES.get(code)
    return spec.taxonomy if spec is not None else None


#: 🔴 DEBT THAT IS MEASURED, NOT DECLARED: CODES WHERE THE BLAME IS NOT THE
#: AUTHOR'S, YET THE OWNER TELLS THE MODEL "FIX THE PROGRAM."
#:
#: 🔴 EMPTY BY DEFAULT SINCE 02.09.2026, AND NOT BECAUSE ASKING HAS
#: STOPPED. Eight codes (`B011 E002 E005 G107 G111 G116 L007 P000`) got an
#: outcome that tells the truth, and `register()` now REFUSES such a row on
#: import. The function remains a measure: "zero" here is a run over 106
#: codes, not a promise, and it can ask about ANY blame.
#:
#: THE REMAINDER IS NAMED AS A NUMBER, NOT HIDDEN:
#: `blame_taxonomy_debt((BLAME_CALLER,))` gives SIX codes (`B014 G103 G106
#: L005 P004 S001`) where the CALLER fixes it (the envelope, the parameters,
#: the policy), yet the owner says "fix the program." They are left
#: untouched DELIBERATELY: `KIR_PROGRAM_REFUSED` does not lie about the
#: world for them (there was no effect, a retry is safe), and the fix
#: address is carried by the `blame` field. A separate outcome for the
#: caller would be `TOOL_INVALID_ARGS`, and moving there changes the door's
#: contract rather than fixing a defect. The decision belongs to the owner
#: of the measure.
def blame_taxonomy_debt(
        blames: tuple[str, ...] = (BLAME_OURS, BLAME_ENVIRONMENT)) -> tuple[str, ...]:
    """Codes whose fix is addressed NOT to the author, yet the owner answers
    «правь программу»."""
    return tuple(sorted(
        code for code, spec in CODES.items()
        if spec.blame in blames
        and spec.taxonomy == _TAXONOMY_BLAMING_THE_AUTHOR))


@dataclass
class Diagnostic:
    code: str
    message_ru: str
    op_index: Optional[int] = None
    op_id: Optional[str] = None
    field_name: Optional[str] = None
    expected: Optional[Any] = None
    got: Optional[Any] = None
    candidates: list = field(default_factory=list)
    # rustc-style suggestion: applicability is "machine-applicable" only when the
    # fix is provably safe to auto-apply; otherwise "maybe-incorrect".
    suggested_replacement: Optional[Any] = None
    applicability: Optional[str] = None
    # Opaque correlation token for an unexpected internal failure.  It is the
    # only panic detail exposed on the wire; server logs carry the same token
    # with bounded, non-payload metadata.
    incident_id: Optional[str] = None
    #: 🔴 BY WHOSE ACTION THE REFUSAL IS LIFTED. Filled in from the registry
    #: at construction; `None` means «код не заведён», not «вины нет» —
    #: lying in that direction is not allowed, and this is caught statically
    #: by `test_one_registrar_of_refusal_codes`. The field is last in the
    #: list DELIBERATELY: positional calls do not shift.
    blame: Optional[str] = None

    def __post_init__(self) -> None:
        # FAIL-OPEN AT RUNTIME, FAIL-CLOSED IN THE GUARD. A refusal that
        # crashes while a refusal is being constructed is the worst of
        # states: it eats the very cause it was created to carry. An
        # unregistered code stays silent here, and the test names it by file
        # and line BEFORE the code ever ships.
        if self.blame is None:
            self.blame = blame_of(self.code)

    def as_dict(self) -> dict:
        # 🔴 BLAME DOES NOT RIDE THE WIRE, AND THIS IS A DECISION, NOT AN
        # OVERSIGHT.
        #
        # The wire dictionary is pinned BYTE FOR BYTE (`test_grounded_program.py`,
        # "the test asserts that the wire dictionary DOES NOT GROW fields"),
        # and the tree is installed editable in the live service's venv: a
        # new field would ship to every consumer that very second, with no
        # one's decision behind it. Blame is available in-process —
        # `d.blame` and `diag.blame_of(code)` — and that is enough for the
        # one it was set up for: `serving`.
        #
        # 🔴 THAT WAVE HAPPENED ON 02.09.2026, AND THE WIRE STAYED THE SAME.
        # Six tables were retired, the outcome is read from the `taxonomy`
        # column, blame forbids the outcome "fix the program" at the
        # `register()` door. The field still does NOT ride the wire:
        # `blame` is the fix address INSIDE the process, and what ships
        # outward is what is derived from it (`err.code`), and the wire
        # dictionary remains pinned byte for byte.
        d = {k: v for k, v in asdict(self).items() if v not in (None, [])}
        d.pop("blame", None)
        return d


class KirRefusal(Exception):
    """Internal control-flow: carries diagnostics out of a stage. Never leaks —
    compile_program() catches it and returns a refused CompileOutput."""

    #: The EXPANDED list of ops that `op_index` of the diagnostics is
    #: assigned against.
    #:
    #: 🔴 SET UP 25.08.2026 FROM AN AUDIT FINDING. The seam against refusal
    #: muteness (`compiler._name_the_next_move_at_the_seam`) was reading the
    #: AUTHOR's field `program["ops"]`, while `op_index` is assigned against
    #: the list AFTER normalization and macro expansion. Two consequences,
    #: both measured:
    #:
    #:   · a single op (`ops` is a dict, the form legalized on 17.08):
    #:     `len()` gave the number of KEYS, the walk went over string keys,
    #:     enrichment did not fire for a SINGLE refusal of such a program;
    #:   · a program with a macro: `plan_program` gives 4 ops out of 1
    #:     authored one, diagnostics arrive with `op_index=2,3` and
    #:     `op_id='s1_L1_w'` — an index outside the bounds of the author's
    #:     list, and an id minted by expansion that never appears in the
    #:     author's envelope at all.
    #:
    #: The field is optional: whoever can supply it does, whoever cannot
    #: does not lie.
    expanded_ops: list | None = None

    def __init__(self, diags: list[Diagnostic]):
        # THE EXCEPTION TEXT CARRIES THE CAUSE, not its count.
        #
        # Measurement 03.08: a refusal of the LANGUAGE ITSELF (`dsl.py`
        # raises `DslRefusal` — a descendant of this class — on a duplicate
        # id, on a non-addressable handle, on an exhausted bulk budget)
        # leaves the sandbox via `str(exc)`, and the model was getting
        # «DslRefusal: 1 diagnostic(s)»: a place, no cause. Only text can
        # cross the process boundary, so the text must be substantive. The
        # codes and messages of the leading diagnostics stand here for
        # exactly that reason; the full list stays in `.diagnostics` and is
        # not lost for anyone who catches the exception whole.
        head = "; ".join(
            f"{d.code}: {d.message_ru}" if getattr(d, "message_ru", "")
            else str(getattr(d, "code", "")) for d in diags[:3])
        if len(diags) > 3:
            head += f" (и ещё {len(diags) - 3})"
        super().__init__(head or f"{len(diags)} diagnostic(s)")
        self.diagnostics = diags


# ═════════════════════════════════════════════════════════════════════════
# THE REFUSAL DICTIONARY IS CLOSED: ONE CODE — ONE NAME
#
# MEASUREMENT 10.08.2026: 89 distinct `KIR-*` codes in the package, 76 of
# them have a named constant, and SIX codes carried several DIFFERENT names
# each. The worst case lived right here: `KIR-T003` was both `TYPE_BAD_ENUM`
# and `TYPE_GEOM_RELATION` — in one file, twelve lines apart. A code on the
# wire is a promise to the consumer that there is one fix; two fixes under
# one code make branching on it impossible, and there was nothing to notice
# this with: there is no central code registry, and occupancy of LETTERS
# was tracked by a comment carrying the result of a manual grep.
#
# WHY THE LINT HERE CLOSES ONLY THIS FILE. There is no module that imports
# all the emitters, so on import `diag` sees only its own namespace — but it
# is exactly there that the worst collision happened, and it is exactly
# that which is now impossible. The cross-module half is closed by
# `test_diag_codes` via `code_collisions()` below: it reads the SOURCE
# FILES rather than importing the package, because importing the whole tree
# for the sake of a lint costs more than the lint itself.
# ═════════════════════════════════════════════════════════════════════════

#: CODES THAT DELIBERATELY HAVE SEVERAL NAMES — WITH A REASON, NOT BY
#: DEFAULT. This is NOT permission to breed synonyms: each line is a debt
#: with a named fix (one shared constant instead of several local ones), and
#: a new code cannot be added here without naming why the names do not
#: collapse into one.
CODES_WITH_KNOWN_ALIASES: dict[str, str] = {
    # EMPTY, AND THIS IS A MEASUREMENT, NOT AN UNFILLED GAP. On 10.08 this
    # held `KIR-E007` (four names) and `KIR-E008` (three); both have been
    # collapsed into `EMIT_UNSUPPORTED_ENUM` and `EMIT_CONTOUR_HOLES`, and
    # their entries were removed TOGETHER WITH the debt, not separately from
    # it. If a new code with two names appears, `code_collisions()` below
    # will show it — this list cannot stay silent.

}


def _lint_diag_codes() -> None:
    """ONE CODE — ONE NAME, within this file, on import."""
    seen: dict[str, str] = {}
    for name, value in globals().items():
        if not (name.isupper() and isinstance(value, str)
                and value.startswith("KIR-")):
            continue
        first = seen.get(value)
        if first is not None and first != name:
            raise AssertionError(
                f"{value}: код носят ДВА имени — {first!r} и {name!r}. "
                f"Код на проводе обещает потребителю ОДИН ремонт; два имени "
                f"под одним кодом делают ветвление по нему невозможным. "
                f"Дайте одному из них свободный номер своей буквы")
        seen[value] = name


_lint_diag_codes()


def codes_in_tree(root: str | None = None) -> tuple[
        dict[str, list[tuple[str, str, int]]], list[tuple[str, str, int]], list[tuple[str, str]]]:
    """All `KIR-*` codes of the package — via an `ast` walk, not a regular
    expression.

    Returns `(объявления, голые, неразобранные)`:

        объявления  `{код: [(имя, файл, строка)]}` — `ИМЯ = "KIR-…"`
        голые       `[(код, файл, строка)]` — a literal in any other
                    EXECUTABLE spot: a call argument, a dict element
        неразобранные `[(файл, причина)]`

    🔴 WHY `ast`, NOT A REGEX, AND THIS COST TO BUY. The old guard was
    searching for `^ИМЯ = "KIR-…"` and therefore saw ONLY declarations. A
    code handed to the wire as a bare literal (`Diagnostic(code="KIR-L004",
    …)`) did not exist for it — and `KIR-L004` carried two incompatible
    meanings for two months under a green guard. Form 54 of this tree: the
    guard pinned down the SHAPE of the first case (two NAMES, the 10.08
    incident) instead of the PROPERTY ("a code has one meaning").

    🔴 PROSE DOES NOT COUNT AS AN OCCURRENCE, AND THESE ARE TWO DIFFERENT
    MECHANISMS. `ast` does not see comments at all — a mention of a code in
    a comment cannot be mistaken for a declaration BY CONSTRUCTION.
    Docstrings are visible and are excluded by name: in this tree, codes are
    listed by the dozen in module headers, and counting them as declarations
    would drown the guard in noise.

    Tests are not read: a copy of the constant in a test is not a wire
    declaration.
    """
    import ast
    import os

    root = root or os.path.dirname(os.path.abspath(__file__))
    decls: dict[str, list[tuple[str, str, int]]] = {}
    bare: list[tuple[str, str, int]] = []
    unparsed: list[tuple[str, str]] = []

    def _is_code(v: Any) -> bool:
        return (isinstance(v, str) and v.startswith("KIR-") and len(v) >= 8
                and v[4].isalpha() and v[5:].isdigit())

    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "build", ".git")]
        if os.path.sep + "tests" in folder:
            continue
        for fname in sorted(files):
            if not fname.endswith(".py") or fname.startswith("test_"):
                continue
            path = os.path.join(folder, fname)
            rel = os.path.relpath(path, root)
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            try:
                tree = ast.parse(src)
            except SyntaxError as exc:      # A NAMED REFUSAL, not a footnote
                unparsed.append((rel, str(exc)))
                continue
            docs: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    body = getattr(node, "body", None) or []
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        docs.add(id(body[0].value))
            named: dict[int, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    targets, value = node.targets, node.value
                elif (isinstance(node, ast.AnnAssign)
                      and node.value is not None):
                    targets, value = [node.target], node.value
                else:
                    continue
                if isinstance(value, ast.Constant) and _is_code(value.value):
                    for t in targets:
                        if isinstance(t, ast.Name):
                            named[id(value)] = t.id
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and _is_code(node.value)):
                    continue
                if id(node) in docs:
                    continue
                if id(node) in named:
                    decls.setdefault(node.value, []).append(
                        (named[id(node)], rel, node.lineno))
                else:
                    bare.append((node.value, rel, node.lineno))
    return decls, bare, unparsed


def code_collisions(root: str | None = None) -> dict[str, list[str]]:
    """WHERE THE TREE DIVERGES FROM ITS OWN DISPATCHER. Empty means it
    agrees.

    What is being asked is the PROPERTY «у кода один распорядитель и один
    смысл», not the shape of a declaration, so all three forms of
    divergence are caught:

        · a code carries more than one NAME (the earlier form, the 10.08
          incident);
        · a code is NOT REGISTERED — meaning a second dispatcher has been
          set up;
        · the name in the tree diverged from the name in the registry (the
          constant was renamed, the registry stayed as it was).

    Known debts (`CODES_WITH_KNOWN_ALIASES`) are still excluded: they are
    named, not forgotten. A code under ONE name in two modules does not
    count as a collision — that is how `GROUND_EMPTY_POOL`
    (`ground`/`relate`) lives, and this is deliberate: `relate` does not
    pull in `ground`.
    """
    decls, bare, unparsed = codes_in_tree(root)
    out: dict[str, list[str]] = {}
    if unparsed:
        # A FILE THE INSTRUMENT COULD NOT PARSE IS A REFUSAL, NOT A
        # FOOTNOTE (form 26): the report disqualifies itself when this list
        # is non-empty.
        out["<НЕ РАЗОБРАНО>"] = [f"{rel}: {why}" for rel, why in unparsed]
    for code in sorted(set(decls) | {c for c, _, _ in bare}):
        if code in CODES_WITH_KNOWN_ALIASES:
            continue
        reasons: list[str] = []
        names = sorted({n for n, _, _ in decls.get(code, ())})
        if len(names) > 1:
            where = ", ".join(f"{n} ({f}:{ln})" for n, f, ln in sorted(decls[code]))
            reasons.append(f"код носят ДВА имени: {where}")
        spec = CODES.get(code)
        if spec is None:
            sites = sorted({f"{f}:{ln}" for n, f, ln in decls.get(code, ())}
                           | {f"{f}:{ln}" for c, f, ln in bare if c == code})
            reasons.append(
                "код НЕ ЗАРЕГИСТРИРОВАН у распорядителя (`kir/diag.register`), "
                f"а выдаётся из {', '.join(sites)}")
        elif names and names[0] != spec.name:
            reasons.append(
                f"имя в дереве {names[0]!r} разошлось с реестром {spec.name!r}")
        if reasons:
            out[code] = reasons
    return out
