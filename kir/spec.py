"""KIR registry AGGREGATOR — the single source of truth (SPEC §3).

OpSpec DEFINITIONS live in per-family modules (ops_authoring/ops_contour/
ops_connect/ops_mep/ops_struct/ops_annotation/ops_families) so that N
Sonnet waves add ops CONCURRENTLY without touching this file or each other
(the contention that took prod down once). This module imports them, builds the
aggregate OPS, and enforces registry invariants on the WHOLE — schema_gen,
grammar, capability-cells and the gate all still read from here. Shared types
and tables (OpSpec/ParamSpec/KindSpec, KINDS, FILTERS, DEFAULTS, vocab deltas,
WRITE_FAMILIES) live in registry_base.py and are re-exported here for
backward-compat (every existing `spec.X` access keeps working). See
REGISTRY_MODULES.md for how a wave adds an op.
"""
from __future__ import annotations

from functools import lru_cache as _lru_cache

# Re-export the shared base so `spec.KINDS`, `spec.OpSpec`, `spec.DEFAULTS`,
# `spec.WRITE_FAMILIES`, ... all keep resolving exactly as before.
from kir.registry_base import *  # noqa: F401,F403
from kir.registry_base import (  # explicit, for this module + linters
    EffectKind, IdentityCardinality, OpSpec, ResultSpec, IR_VERSION,
    ROUTE_ONLY_ACTIONS, BANNED_OBJECT_KIND_PLACEHOLDERS,
)

# Every registry module. A new family = a new ops_*.py added to THIS list only.
# A DARK MODULE, REMOVED 10.08.2026: `ops_doc`. It was the SEED of the
# annotation family (tag/dimension/text) and gave birth to it — it moved
# to `ops_annotation`, whose own docstring says exactly that: "annotation
# tirage beyond ops_doc seed." After the move, `ops_doc.OPS` stood as an
# EMPTY list since 17.07, while all the neighboring `ops_*` kept moving
# all through August. An empty module in the registry's import list is
# indistinguishable from a broken one: it registers nothing and says
# nothing about it. A seed that has sprouted is not kept next to the
# harvest.
from kir import (  # noqa: E402
    ops_authoring, ops_contour, ops_connect, ops_mep,
    ops_struct, ops_annotation, ops_families, ops_arch,
    ops_shape, ops_room, ops_opening, ops_analysis, ops_site, ops_sweep,
    ops_solid, ops_mass, ops_surface, ops_adaptive, ops_boolean,
)
# The gaps journal — the same primitive as the acceptance log and the
# dark modules: the line's shape is checked AT IMPORT, so an entry
# without a date, a deadline, and a reason physically cannot be created.
# `record_ratchet` imports neither the registry nor acceptance (checked:
# it has only datetime and typing), there is no cycle.
# NAMES WITHOUT ALIASES, AND THIS IS NOT STYLE. The journal ratchet finds
# declarations by SCANNING THE SOURCE for the pattern `NAME = Ledger(`
# (tests/test_record_ratchet.py). The first draft of this line imported
# `Ledger as _Ledger` — the journal was built, registered itself in
# `ALL_LEDGERS`, and WOULD HAVE GONE STALE SILENTLY: the scanner did not
# see it, and the test that catches this was failing at the time for an
# unrelated reason (an env leak in conftest). Exactly the seventh general
# form, catching its own author an hour after he wrote it.
from kir.record_ratchet import CLOSE_BY, STANDS, Entry, Ledger  # noqa: E402

_REGISTRY_MODULES = (
    ops_authoring, ops_contour, ops_connect, ops_mep,
    ops_struct, ops_annotation, ops_families, ops_arch,
    ops_shape, ops_room, ops_opening, ops_analysis, ops_site, ops_sweep,
    ops_solid, ops_mass, ops_surface, ops_adaptive, ops_boolean,
)

# Aggregate — duplicate op names across modules are a hard error (each op lives
# in exactly one ops_*.py; this is what makes concurrent-wave edits safe).
OPS: dict[str, OpSpec] = {}
for _mod in _REGISTRY_MODULES:
    for _op in _mod.OPS:
        if _op.name in OPS:
            raise AssertionError(
                f"duplicate op name {_op.name!r} across registry modules "
                f"(module {_mod.__name__}); each op must live in exactly one ops_*.py")
        OPS[_op.name] = _op


#: Ops that OWN THEIR TRANSACTION SCOPE and therefore must be the sole op of
#: their program (KIR-L002 / `diag.PLAN_SOLO_OP`).
#:
#: `create_stairs` drives `StairsEditScope`, which opens and commits its own
#: transactions; it cannot nest inside the shared program transaction, so a
#: neighbour in the same program is unbuildable BY REVIT, not by our taste.
#:
#: ONE TRUTH, FOUR READERS. Until 2026-08-04 this fact was spelled three times
#: in three places — a hardcoded `op["op"] == "create_stairs"` in the emitter
#: (`authoring.emit_program`), a private `_SOLO_OPS` in
#: `decompile/materialize.py`, and prose in `tool_doc`/`course`. The plan stage
#: knew it NOWHERE, so the refusal only existed AFTER grounding: the sandbox
#: assembled the program, `plan_program` accepted it, and the model met the wall
#: only on a live device (measured 04.08 — `plan_program` accepted
#: `[create_stairs, create_wall]` without a word). A fact stated in N places
#: drifts in N-1 of them; stated here it is read by plan, emit and materialize
#: alike.
#: `create_stairs_landing` (10.08.2026) — the SECOND resident of this set,
#: and it is here BY MEASUREMENT, not by symmetry. RevitAPI.xml writes for
#: `StairsLanding.CreateSketchedLanding`, verbatim and identically across
#: all six versions: `InvalidOperationException` — "The stairs element
#: represented by stairsId is not in an active StairsEditScope." A landing
#: needs the SAME edit scope as a run, and opening one on an
#: already-standing stairs is allowed by the single-argument
#: `StairsEditScope.Start(ElementId)` (measured by compilation 6/6,
#: 10.08). Hence: a landing is a separate PROGRAM, not a neighbor of a
#: run. The solo-op law is not weakened by a single byte here — on the
#: contrary, the second resident turns it into a general rule instead of
#: a special case of one name.
#: `create_stairs_run` (15.08.2026) — the THIRD resident, and it is here
#: BY MEASUREMENT, not by symmetry with the landing. RevitAPI.xml writes
#: for `StairsRun.CreateStraightRun`, verbatim and identically across all
#: six versions: `InvalidOperationException` — "The stairs element
#: represented by stairsId is not in an active StairsEditScope. New
#: components cannot be added to it." The same phrase as for
#: `CreateSketchedLanding`, and the same conclusion: a run needs an edit
#: scope, and Revit does not open two scopes at once ("there already is a
#: stairs edit mode active in the document"). So a second run is a
#: SEPARATE PROGRAM, and the inexpressibility of two stairs ops as
#: neighbors is REVIT's law, not our taste. Opening a scope on an
#: ALREADY-STANDING stairs is allowed by the single-argument
#: `StairsEditScope.Start(ElementId)` (6/6), the same one the landing
#: lives by.
#: 🔴 THE FOURTH RESIDENT, OF A DIFFERENT KIND (21.08.2026):
#: `author_family` owns not only transactions but a SECOND DOCUMENT. The
#: reason for solo status is the same in form and stricter in substance:
#: the family document is created from a template, lives inside the
#: program, and is closed with `Close(false)` before it ends — meaning
#: its elements do not outlive the program's boundary, and a neighbor in
#: the program could not reach them even in principle. The three stairs
#: ops are solo because Revit does not open two edit scopes; this one is
#: solo because you CANNOT wedge something in between the steps of
#: authoring — not because it would be inconvenient.
#: 🔴 THE FIFTH RESIDENT (23.08.2026): `transfer_family`. The reason for
#: solo status is a REVIT PROHIBITION, stated verbatim and identically
#: across all six versions. RevitAPI.xml for `Document.EditFamily`: "This
#: method may not be called if the document is currently modifiable (has
#: an open transaction)"; for `Document.LoadFamily(Document)`: "…when the
#: target document is modifiable (e.g. there is an uncommitted
#: transaction)." Both are InvalidOperationException. And the body of
#: every KIR program runs INSIDE `Transaction.Start()`, meaning an
#: ordinary op would hit the exception GUARANTEED, not occasionally. Like
#: `author_family`, it owns a second document; unlike it — someone
#: else's, and read-only.
SOLO_OPS: frozenset[str] = frozenset({
    "create_stairs", "create_stairs_landing", "create_stairs_run",
    "author_family", "transfer_family"})

#: THE UPPER LIMIT ON GROUP MEMBERSHIP SIZE — ONE CARRIER FOR THE
#: VALIDATOR AND THE LIFTER.
#:
#: 🔴 IT USED TO BE 200 AS A BARE LITERAL IN THREE PLACES OF ONE BLOCK,
#: AND THE REASON FOR THE NUMBER WAS RECORDED NOWHERE. Measurement of
#: 23.08.2026 on two production buildings of the MNVNK complex
#: (`group.index.json`, multi-instance definitions):
#:
#:     K6   definitions 71   median members 30   maximum 302
#:     K3   definitions 67   median members 28   maximum 318
#:     does not fit in 200: K6 — 7 definitions, K3 — 4
#:     does not fit in 500 or above: NONE
#:
#: 1000 was chosen by the owner on 23.08 and gives a threefold margin over
#: the measured maximum. The number is still CHOSEN, not derived — and
#: this is stated here so the next reader does not mistake it for a
#: measured one. It changes together with this note, not silently.
GROUP_MEMBERS_MAX: int = 1000

#: OPS WHOSE RESULT KIND IS `many`, BUT FOR A SPECIFIC CALL IS DETERMINED BY
#: SHAPE.
#:
#: The value is a predicate over the OPERATION'S DICTIONARY: "this call
#: gives exactly one element." It is not a relaxation but a refinement:
#: `identity_cardinality` describes the OP IN GENERAL, while group
#: membership decides the INSTANCE.
#:
#: `create_room_separator` is the sole resident, and it is let in here by
#: its own POSTCONDITION, not by our wish: "the number of segments created
#: is exactly one less than the number of points in path." A path of two
#: points ⇒ EXACTLY ONE segment, and this is an assertion the witness
#: already checks.
#:
#: MEASUREMENT OF 23.08.2026, what this cost: the lift always gives the
#: separator a polyline of EXACTLY two points (K6 1086 of 1086, K3 917 of
#: 917 — by the lifter's construction: one L0 element is one ModelCurve
#: with its own p0/p1). The closed declaration of `many` was cutting off
#: 31 K6 definitions and 27 K3 — the second-largest cause of group-lifter
#: refusal after atom members.
#:
#: The list is CLOSED and grows only together with a quote from the op's
#: postcondition.
GROUP_MEMBER_SHAPE_IS_ONE: dict = {
    "create_room_separator":
        lambda op: isinstance(op.get("path"), list) and len(op["path"]) == 2,
}


def group_member_yields_one(op_name: str, op: object = None) -> bool:
    """Whether this group member gives EXACTLY ONE element.

    🔴 ONE CARRIER FOR TWO CONSUMERS. The rule is asked by the validator
    (`member_ops`) and the lifter (`_group_member_eligible`), and if each
    carried its own copy, they would drift apart on the very first new op
    — a named defect shape of this tree.

    `op` is optional: without it, only the declared kind answers (this is
    how the lifter asks, when there is no operation dictionary yet). With
    the dictionary, the call's shape is additionally asked — see
    `GROUP_MEMBER_SHAPE_IS_ONE`.
    """
    ospec = OPS.get(op_name)
    if ospec is None:
        return False
    # 🔴 "ONE" IS A HOW MANY, NOT A WHAT (25.08.2026, an audit finding,
    # reproduced by a run: `av.validate` on a group with the member
    # `create_wall_type` gave ZERO diagnostics, and so did `plan_program`).
    #
    # The rule only answered about `identity_cardinality`. Of 82 ops, 61
    # passed into member status, and FIVE of them do not place a single
    # BUILDING element into the document: `create_wall_type`,
    # `create_type`, `create_floor_plan`, `load_family`,
    # `transfer_material`. A Revit group is a set of MODEL ELEMENTS; a
    # wall type and a floor plan are not placed into one, and a program
    # with such a member either refuses at runtime or places into the
    # group something other than what the author named.
    #
    # THE AUTHORITY IS `OPS_WITHOUT_ELEMENTS` IN THIS SAME FILE (moved
    # here 28.08.2026).
    #
    # 🔴 A LAZY IMPORT FROM THE ACCEPTANCE MODULE STOOD HERE, AND THE
    # FAILURE WAS SWALLOWED: `except ImportError: pass` under the argument
    # "the rule has no right to fail." The argument is correct, and the
    # remedy was wrong: on failure the op was silently deemed NOT
    # cataloged, and there was nothing left to tell "not cataloged" apart
    # from "there was no one to ask" — a zero assembled from a swallowed
    # failure. Now there is no one to ask: the list is its own, and there
    # is nowhere for a failure to come from.
    if op_name in OPS_WITHOUT_ELEMENTS:
        return False
    if ospec.result.identity_cardinality.value == "one":
        return True
    probe = GROUP_MEMBER_SHAPE_IS_ONE.get(op_name)
    if probe is None or op is None:
        return False
    try:
        return bool(probe(op))
    except Exception:                                        # noqa: BLE001
        return False

#: VERSION-FRAGILE PAIRS (op, FIELD) — A SEPARATE LIST, NOT RESIDENTS OF
#: `SOLO_OPS`.
#:
#: THE LIST'S KIND: **CLOSED, BUT NOT COMPLETE.** Derived from the run of
#: the `k2_ar_rd_v7` gate on 2026-08-13 (`tools/compile_gate_offline.py`,
#: 889 checks). It is complete RELATIVE TO THAT RUN and NOT complete
#: relative to the API: an op whose emission fails on a pair not named
#: here will travel in the shared chunk and carry its neighbors down with
#: it. The ratchet for this is `test_version_fragile_asks_the_emitter.py`.
#:
#: 🔴 EXTENDED ON 15.08.2026 BY FIVE PAIRS, AND THE SOURCE CHANGED. The
#: previous ratchet walked EXACTLY `authoring.py`, while the bodies of 32
#: of 63 emitters had moved into twelve `*_emit.py` satellites, leaving
#: four-line wrappers behind. The method was correct — ask for the place
#: of definition — but coverage became 6% of the new code: four places of
#: version-based refusal were invisible, three were named nowhere. The
#: ratchet now walks `authoring` AND the satellites, pinning the place to
#: the op BY THE CALL CHAIN (two of the four places sit in private
#: helpers, and `struct_emit` serves six ops — attributing the place to
#: the whole module would mean declaring five uninvolved ops fragile).
#:
#: THE COST OF THE EXTENSION IS MEASURED, NOT ASSUMED. The sole caller is
#: `decompile/materialize.py:1830` (chunk slicing). Four of the five ops
#: in `decompile/` are not mentioned EVEN ONCE, meaning the materializer
#: will not spawn them by construction; `create_foundation` is mentioned,
#: but across a corpus of 52 trees it occurs **0 times**. Bottom line: the
#: extension costs zero chunks on the measured data and caps the loss at
#: 249 neighbors wherever the op appears.
#:
#: WHY NOT IN `SOLO_OPS`. That list is a set of NAMES, and its
#: justification is its own: stairs edit scopes (`StairsEditScope`). Here
#: the reason is different — a missing API overload on an old version —
#: and the key is different: a FIELD, not a name. Measured 13.08 on the
#: tower: by field, 125 ops go solo; by name, 333. Merging the two kinds
#: into one predicate would mean losing a distinction that will be needed
#: on the very first non-version-related refusal.
#:
#: WHY AT ALL. An emission failure drops the whole PROGRAM, and the chunk
#: size (250) is assigned by us. Measured: THREE ops inexpressible on
#: Revit 2021 carried down 2 742 compatible ones with them — a ratio of
#: 1 : 914. Solo slicing returns them at a cost of ~125 additional
#: programs, that is, 22 recovered ops per program.
#:
#: AN HONEST CAVEAT: 81 of 125 are `create_ceiling`, and they will not
#: assemble on 2021 solo either way (`Ceiling.Create` is from 2022, there
#: is no legacy path on any of the six). The gain is not that the
#: ceilings get built, but that they stop dragging neighbors down.
#:
#: A `None` FIELD MEANS "the op is fragile as a whole, regardless of
#: parameters."
VERSION_FRAGILE: frozenset[tuple[str, str | None]] = frozenset({
    ("create_ceiling", None),
    ("create_floor", "holes"),
    ("create_floor_by_contour", "contour.holes"),
    # ── addendum 15.08.2026: `*_emit.py` satellites, found by a traversal, not by eye ──
    # THE SAME PAIR AS FOR THE FLOOR SLAB, AND THIS IS STATED IN THE
    # EMITTER ITSELF: `struct_emit._emit_foundation_slab` documents "the
    # SAME EMIT_UNSUPPORTED refusal create_floor gives for holes
    # pre-2022" (`Floor.Create` with openings — from 2022, `NewFloor` has
    # none). A foundation slab is exactly a structural floor by contour,
    # so the absence of this pair next to its two neighbors was a gap in
    # bookkeeping, not a decision (`struct_emit.py:227`).
    ("create_foundation", "holes"),
    # A REFUSAL ON FOUR VERSIONS OUT OF SIX (`ver < "2025"`,
    # `datum_emit.py:511`): the entire API of a multi-story run is typed
    # as `ISet<ElementId>`, and the plugin deployed across the fleet on
    # net48 does not link `System.dll` — the body will not compile AT THE
    # USER'S END (CS0012), even though it compiles for us. An op that
    # fails on 2/3 of supported versions is obligated to travel solo:
    # otherwise it drags a chunk down on each of the four.
    ("create_multistory_stairs", "levels"),
    # THE THREE STRUCTURAL LOADS ARE FRAGILE AS A WHOLE (field `None`),
    # not by parameter: `analysis_emit._version_guard` refuses with
    # `KIR-E003` when `ver > _FREE_LOAD_LAST_VER` ("2023"), that is, on
    # 2024/2025/2026 — HALF of the supported versions. There is no
    # emission fork by construction: the alternatives are to build the
    # load on a foreign host or to say nothing, and both read from the
    # outside as success. The field is `None`, because it is the version
    # that decides, not the parameter: the guard stands BEFORE parsing
    # anything at all.
    ("create_point_load", None),
    ("create_line_load", None),
    ("create_area_load", None),
})


def is_version_fragile(op_name: str, params: Mapping[str, Any] | None) -> bool:
    """Whether THIS op with THESE parameters is fragile — not "is the name
    in the list."

    The pair's key is a FIELD, so `create_floor` without `holes` travels
    in the shared chunk together with its 154 siblings, rather than going
    solo because of its name.
    """
    values = params or {}
    for name, field in VERSION_FRAGILE:
        if name != op_name:
            continue
        if field is None:
            return True
        node: Any = values
        for part in field.split("."):
            if not isinstance(node, Mapping):
                node = None
                break
            node = node.get(part)
        if node:
            return True
    return False

#: WHAT A REFERENCE LOOKS LIKE ONCE IT HAS CROSSED THE BUILD-PLAN PHASE
#: BOUNDARY.
#:
#:     {"by": "phase_result", "value": "<id of the producing op>", "phase": <N>}
#:
#: WHY THIS NAME LIVES HERE, AND NOT WHERE IT IS WRITTEN. The tag is
#: written by the annotator (`course.phase()`), but it is SUBSTITUTED by
#: the plan executor (`compiler.substitute_phase_results`, calls
#: `serving`), and the compiler has no right to import course: course
#: imports the compiler for the budget, and the reverse edge would close
#: a cycle. Writing the literal `"phase_result"` in both places would
#: mean creating that same second record of one fact, because of which
#: `SOLO_OPS` above drifted apart in two places out of three. Both see
#: the registry.
#:
#: WHY NOT `by=ref`. `ref` addresses an op of THIS SAME program and is
#: resolved before emission; by the time of the next phase, the produced
#: element is already committed by a SEPARATE transaction, and there is
#: no longer a reference to it within the program. The tag is an
#: obligation to substitute `{"by": "element_id"}`, not a selector shape:
#: reaching `plan_program` unsubstituted, it is obligated to refuse.
CROSS_PHASE_BY: str = "phase_result"


#: A CLOSED DICTIONARY OF PARAMETER KINDS — 34 kinds, exactly the ones
#: that stand in the registry.
#:
#: BEFORE 07.08.2026 IT DID NOT EXIST, and `ParamSpec.kind` was an
#: ordinary string: a typo in it failed nowhere. It cost more than it
#: looks like. In `authoring_validation`, parameter parsing is a chain of
#: `if/elif p.kind == ...`, and it had no tail; a parameter with an
#: unrecognized kind was checked by NOT A SINGLE branch and did not land
#: in `norm`, that is, it traveled onward as if the author had not
#: written it. A mandatory parameter silently turned into a missing one.
#:
#: THE RULE IS NOT NEW — ITS ENFORCEMENT IS. REGISTRY_MODULES.md already
#: calls a new parameter kind a "Fable-level" change (coordination, on a
#: par with a new snapshot pool and a new KIND), and this is exactly what
#: is recorded in the comment on `known_pools` below. Lint closed off
#: pools, but not kinds. Now it does: until a kind is named here, the
#: registry does not import at all.
#:
#: There are now three locks against a typo, and they are INDEPENDENT:
#: this one (on registry import), `schema_gen` (on schema assembly), and
#: `authoring_validation._assert_kind_dispatched` (on program parsing).
PARAM_KINDS: frozenset[str] = frozenset({
    # points, polylines, and curves
    "pt_xy", "pt_xyz", "pt_view2d", "pts", "pts_xyz", "pts_list",
    "path", "path3", "arc", "spiral", "region", "slopes", "mesh",
    # 🔴 A DIRECTION (21.08.2026) IS NOT A POINT, AND THE DIFFERENCE IS
    # MEASURED, NOT DECLARED. `ref_dir` used to live under the `pt_xyz`
    # kind, and running `decompile.program_source._shift` on a real value
    # gave:
    #
    #     ref_dir [-1, 0, 0]   ->   [-1001.0, -500.0, 0.0]
    #
    # That is, the direction picked up the local frame's origin and
    # stopped being unit length. No check would have failed: three
    # numbers remain three numbers. A plane already has protection
    # against this same defect shape (`program_source.FREE_KEYS`: "_shift
    # would have subtracted the local frame's origin from a DIRECTION"),
    # but it protects a KEY INSIDE a dict, while here the value sits as a
    # PARAMETER — there is no key, and there was nothing to protect.
    #
    # The kind carries a RAY: length means nothing, zero is forbidden,
    # there are no millimeters at all. That is why it is not, and must
    # not be, in `program_source.MM_KINDS` — that is exactly what fixes
    # the defect.
    "dir_xyz",
    # SURFACE next to MESH, and these are two different kinds, not a
    # refinement of one: a mesh is facets (triangles), a surface is
    # smooth NURBS. Merging them would mean setting up one kind for two
    # geometries with different laws, different witnesses, and different
    # cost (20.08.2026).
    "surface",
    # THE LIST OF PRIMITIVE OPERANDS for boolean (20.08.2026). Next to
    # `mesh` and `surface`, and NOT in place of them: a mesh has its own
    # topology, a surface its own smoothness, and here it is a
    # box/sphere/cylinder by numbers, whose sole purpose is to be born
    # and die inside a single op. None of the existing kinds describe
    # this: `pts*` carry no dimensions, `region` requires grounding and
    # yields ONE artifact per op, and `member_ops` makes every member a
    # real ELEMENT — exactly the opposite of what boolean needs.
    "solid_parts",
    # SKETCH PLANE (21.08.2026) — the profile's coordinate frame: origin,
    # normal, +u direction IN the plane. Next to `region`, not inside it,
    # and this is a decision: the contour STATES THE SHAPE in its own
    # (u, v), the plane STATES WHERE those (u, v) lie in the world.
    # Merging them would mean the same profile could not be placed twice
    # in different places, and that is exactly what the window family
    # does. The full analysis is in `plane.py`.
    "plane",
    # graphs
    "graph_nodes", "graph_segments",
    # numbers and scalars
    "mm", "deg", "num", "int", "bool",
    # strings and enumerations
    "str", "str_long", "enum", "value",
    # 🔴 МНОЖЕСТВЕННЫЙ ВЫБОР ИЗ ЗАКРЫТОГО СЛОВАРЯ (13.09.2026). Отличие от
    # `fields` — не в форме, а в том, ЧЬЁЙ словарь: `fields` жёстко прибит к
    # `LIST_FIELDS` в схеме (`schema_gen.py:451`), поэтому второй оп с такой же
    # формой и другим словарём получил бы ВЕРНУЮ проверку и ЛОЖНУЮ схему —
    # именно тот класс «построено и не соединено», который тут дороже всего.
    # Здесь словарь приходит из `choices` самого параметра, как у `enum`, а
    # значение — непустой список без повторов. Первый носитель:
    # `query_level_plan.include`.
    "enum_list",
    # 🔴 THE BASE A WRITE WAS PLANNED AGAINST (13.09.2026). `expected_identity`
    # carries {unique_id, version_guid} — what the author READ before deciding
    # to write. It is not an address (that is `target`): it is the claim "the
    # thing I am about to change is still the thing I looked at". Without it a
    # second edit computed from a stale read overwrites the first one silently,
    # which is the whole subject of T10.
    "identity",
    # selectors
    "sel", "sel_list", "target", "target_w", "refs_w",
    # composite operands
    "member_ops", "placements", "wall_layers",
    # query family only (parsed in `compiler._validate_op`)
    "fields", "filters", "kind_enum",
})


#: OPERAND KINDS FOR WHICH ONE OP GIVES MANY ELEMENTS. The registry is
#: their sole source, and this is not style but a fix for a bought
#: defect.
#:
#: WHAT IT COST (18.08.2026). The list lived in the INSTRUMENT
#: (`tools/capability_map.py`), and the compiler's canon asked it like
#: this:
#:
#:     plural = [...] if hasattr(spec, "PLURAL_KINDS") else []
#:     if not plural:
#:         try:    import capability_map as cm      # <- a bare import
#:         except Exception: plural = []            # <- AND THERE IT IS, THE ZERO
#:
#: `tools/` is not on `sys.path` when the instrument is called from
#: `backend/`, so the import ALWAYS failed, the failure was swallowed,
#: and the canon's generated block got **0** where the truth was **12**.
#: The ratchet, meanwhile, demanded that the zero be recorded and WOULD
#: HAVE TURNED GREEN ON IT. This is the form "zero of a value the
#: instrument does not compute here": the absence of an answer wore the
#: costume of an answer.
#:
#: The cure is mandate item 4, verbatim: a table obligated to agree with
#: the registry must BE the registry from a different angle. The
#: instrument already asked `spec.PLURAL_OPERAND_KINDS` first — now it
#: has something to answer with.
#:
#: 🔴 AND THIS IS NOT THE SAME THING AS `PLURAL_KINDS` IN
#: `tests/test_unpinned_plural_witnesses.py`; THE NAME MATCH WAS
#: COINCIDENTAL. Here the question is "how many ELEMENTS does one op
#: spawn" (a lever of the language); there it is "does the parameter's
#: content go through a HANDWRITTEN LOOP in the emitter" (does the golden
#: pin the loop's boundary). That is why there are four more kinds there
#: — `pts`, `slopes`, `sel_list`, `fields`: a roof contour is traversed
#: by a loop, but the roof comes out as ONE. The two sets are obligated
#: to DIFFER, and this is held by the test, not by memory: collapsing
#: them into one would be a regression, not a cleanup.
PLURAL_OPERAND_KINDS: frozenset[str] = frozenset({
    "member_ops",      # group membership
    "placements",      # list of placements
    "graph_nodes",     # graph nodes
    "graph_segments",  # graph edges
    "pts_list",        # list of contours
    "refs_w",          # multiple targets
    "filters",         # filter selection
})

#: Backward compatibility: the `capability_map` instrument has carried
#: this name since 09.08.
PLURAL_KINDS = PLURAL_OPERAND_KINDS

_unknown_plural = PLURAL_OPERAND_KINDS - PARAM_KINDS
if _unknown_plural:
    raise AssertionError(
        f"PLURAL_OPERAND_KINDS называет виды, которых нет в PARAM_KINDS: "
        f"{sorted(_unknown_plural)}. Опечатка здесь тиха вдвойне: она не "
        f"ломает ни одну программу и просто ЗАНИЖАЕТ рычаг языка в каноне")
del _unknown_plural


def _lint_registry() -> None:
    """Registry invariants, enforced at import on the AGGREGATE (RISK R10,
    bare-action ban 13.2, §16 placeholder ban)."""
    for name in SOLO_OPS:
        if name not in OPS:
            raise AssertionError(
                f"SOLO_OPS names {name!r}, which is not a registered op — "
                f"a solo rule about a nonexistent op is a rule nobody enforces")
    for op in OPS.values():
        if not isinstance(op.effect, EffectKind):
            raise AssertionError(f"{op.name}: effect must be typed")
        if not isinstance(op.result, ResultSpec):
            raise AssertionError(f"{op.name}: result must be typed")
        if op.family == "query" and op.writes_model:
            raise AssertionError(f"{op.name}: query family must not write")
        if op.family in ("authoring", "modify") and not op.writes_model:
            raise AssertionError(f"{op.name}: authoring op must declare writes_model")
        if op.writes_model == (op.effect is EffectKind.READ):
            raise AssertionError(
                f"{op.name}: writes_model and typed effect disagree")
        if (op.family == "query"
                and op.result.identity_cardinality
                is not IdentityCardinality.NONE):
            raise AssertionError(
                f"{op.name}: query result cannot claim write identity")
        if (op.writes_model
                and op.result.identity_cardinality
                is IdentityCardinality.NONE):
            raise AssertionError(
                f"{op.name}: write result needs identity evidence")
        for p in op.params:
            if p.kind not in PARAM_KINDS:
                raise AssertionError(
                    f"{op.name}.{p.name}: неизвестный вид параметра "
                    f"{p.kind!r}. Вид — не свободная строка: неназванный вид "
                    f"не разбирает ни одна ветвь `authoring_validation`, и "
                    f"параметр молча не доедет до `norm`. Назовите вид в "
                    f"`PARAM_KINDS` и заведите ему ветвь разбора")
        for action, object_kind in op.capability:
            if not action or not object_kind \
                    or object_kind in BANNED_OBJECT_KIND_PLACEHOLDERS \
                    or action in BANNED_OBJECT_KIND_PLACEHOLDERS:
                raise AssertionError(f"{op.name}: bare/placeholder capability cell "
                                     f"({action!r}×{object_kind!r}) — banned forever (§16)")
            if action in ROUTE_ONLY_ACTIONS:
                raise AssertionError(f"{op.name}: {action} is route-only, cannot own IR ops")
        known_pools = ("levels", "wall_types", "pipe_types", "piping_system_types",
                       "floor_types", "column_symbols_structural",
                       "column_symbols_architectural", "window_symbols",
                       "door_symbols", "family_symbols",
                       "roof_types", "duct_types", "duct_system_types",
                       "cable_tray_types", "grids",
                       # wave/struct (2026-07-17): create_beam/create_foundation.
                       # REGISTRY_MODULES.md calls a new snapshot pool a
                       # "Fable-level" change (new param-kind/pool/KIND =
                       # coordination) — flagged in the wave report as the one
                       # unavoidable shared touch this wave needed beyond its
                       # own ops_struct.py/struct_emit.py/test_struct.py.
                       "beam_types", "foundation_symbols",
                       # wave/arch (2026-07-29): create_ceiling/create_railing.
                       # TWO NEW POOLS, not a reuse of floor_types — and
                       # this is not pedantry: CeilingType and
                       # RailingType are different classes in Revit, and
                       # priming a ceiling from the floor pool would give
                       # a PLAUSIBLE but wrong type, that is, a silent
                       # substitution indistinguishable from success on
                       # the outside. A pool is a "Fable-level" change
                       # (REGISTRY_MODULES.md), because it drags the
                       # collector in open_model.py along with it; a
                       # reason not to add one out of laziness, not a
                       # reason not to add one when it is warranted.
                       "ceiling_types", "railing_types",
                       # wave/wall-foundation (2026-08-09):
                       # create_wall_foundation. The pool is assembled BY
                       # CLASS (WallFoundationType — a standalone
                       # ElementType class, compilation 6/6), not by
                       # category: OST_StructuralFoundation holds both
                       # point footings (FamilySymbol, the
                       # foundation_symbols pool) and strip types, while
                       # WallFoundation.Create accepts ONLY
                       # WallFoundationType — otherwise an
                       # ArgumentException "typeId is not a valid
                       # WallFoundationType id" (RevitAPI.xml). Reusing
                       # foundation_symbols would mean handing the
                       # emitter an id that the call is certain to
                       # reject.
                       "wall_foundation_types",
                       # wave/framing (2026-08-09): create_truss. ONE new
                       # pool for two operations, and this is measured: a
                       # framing system has no pool of its own at all —
                       # its `symbol` is an ordinary structural beam from
                       # `beam_types` (the same class, the same filter by
                       # placement type). But a truss type is a separate
                       # class, TrussType, and nothing else can be
                       # substituted for it: Truss.Create rejects a
                       # foreign id with an ArgumentException, and there
                       # is no default document type for a truss
                       # (ElementTypeGroup.TrussType does not compile on
                       # any of the six).
                       "truss_types",
                       # wave/mep-electrical (2026-08-09): create_conduit
                       # and two flexible ops. THREE NEW POOLS, and again
                       # not out of laziness about reuse: ConduitType,
                       # FlexDuctType, and FlexPipeType are standalone
                       # Revit classes, not subsets of
                       # cable_tray_types/duct_types/pipe_types. Grounding
                       # a flex duct on the rigid pool would mean handing
                       # the emitter a type that `FlexDuct.Create` rejects
                       # (`IsFlexDuctTypeId` — a separate API predicate),
                       # that is, swapping a typed refusal for a runtime
                       # exception inside the transaction.
                       "conduit_types", "flex_duct_types", "flex_pipe_types",
                       # wave/analysis (2026-08-09): structural loads.
                       # FOUR pools, and three of them are load types
                       # assembled BY CLASS
                       # (PointLoadType/LineLoadType/AreaLoadType —
                       # standalone ElementType classes, compilation 6/6).
                       # They cannot be collapsed into one:
                       # `PointLoad.Create` accepts only `PointLoadType`,
                       # and handing it a line-load type would mean
                       # replacing a typed refusal with a runtime
                       # exception inside the transaction.
                       #
                       # `load_cases` is a pool of INSTANCES, not types
                       # (like `levels` and `grids`), and it is mandatory
                       # for all three loads: the load case is the
                       # operation's professional substance, not
                       # decoration (see ops_analysis.py). The
                       # `load_natures` pool is deliberately ABSENT here:
                       # nature is the input of the CASE-creation
                       # operation, which is not in this wave, and a pool
                       # nothing is grounded on would be the first
                       # exception to the rule that "a pool exists for
                       # the sake of a selector."
                       "load_cases", "point_load_types", "line_load_types",
                       "area_load_types",
                       # wave/site (2026-08-09):
                       # create_topography(toposolid) and
                       # create_building_pad. TWO NEW POOLS, and both are
                       # a "Fable-level" change (they drag the collector
                       # in open_model.py along), which is why they are
                       # named in the wave report as the sole unavoidable
                       # common seam.
                       #
                       # For the topo-solid, the pool is the ONLY way to
                       # learn the list of types: ElementTypeGroup.
                       # ToposolidType does not exist on any of the six
                       # versions (measured), meaning it is impossible in
                       # principle to ask the document "what is the
                       # default solid" — exactly as with railing. For a
                       # building pad, a default, by contrast, DOES EXIST
                       # (ElementTypeGroup.BuildingPadType, 6/6), and the
                       # pool is needed for an explicit `by:name`.
                       "toposolid_types", "building_pad_types",
                       # wave/sweep (2026-08-09): create_wall_sweep and
                       # create_slab_edge. TWO NEW POOLS, and both are
                       # assembled differently BY MEASUREMENT, not by
                       # taste.
                       #
                       # `slab_edge_types` — BY CLASS (`SlabEdgeType` — a
                       # standalone ElementType class, compilation 6/6),
                       # exactly like `wall_foundation_types`:
                       # `NewSlabEdge` accepts ONLY `SlabEdgeType`, while
                       # `NewFascia`/`NewGutter` have their own classes,
                       # and one cannot be substituted for another
                       # (ArgumentException, RevitAPI.xml).
                       #
                       # `wall_sweep_types` — BY TWO CATEGORIES
                       # (OST_Cornices + OST_Reveals), and this is the
                       # only possible way: a `WallSweepType`-as-
                       # ElementType class DOES NOT EXIST in the API at
                       # all — `WallSweepType` is an ENUM {Sweep, Reveal}
                       # (measured), and the type itself lives as an
                       # ordinary ElementType in one of the two
                       # categories. The pool is therefore ONE for both
                       # cornices and reveals, and which enum value to
                       # pass is derived by the emitter from the category
                       # of the allowed type.
                       "wall_sweep_types", "slab_edge_types",
                       # wave/detail (2026-08-09): create_filled_region.
                       # THE POOL IS ASSEMBLED BY CLASS (FilledRegionType
                       # — an ElementType kind, compilation 6/6), not by
                       # category: OST_FilledRegion holds both the fills
                       # themselves and their types, while
                       # `FilledRegion.Create` accepts ONLY a fill-type id
                       # and checks this itself
                       # (`IsValidFilledRegionTypeId`, also 6/6). A
                       # document default DOES EXIST for it
                       # (`ElementTypeGroup.FilledRegionType`, 6/6), so
                       # the pool is needed not as the sole input but for
                       # an explicit `by:name` — a real project has
                       # dozens of fill types ("Concrete," "Soil,"
                       # "Insulation"), and they are not chosen blindly.
                       "filled_region_types",
                       # wave/reinforcement (2026-08-10):
                       # create_area_reinforcement. THREE POOLS, all BY
                       # CLASS (AreaReinforcementType / RebarBarType /
                       # RebarHookType — standalone ElementType classes,
                       # compilation 6/6), and none reduces to another:
                       # `AreaReinforcement.Create` checks EACH of the
                       # three arguments against its own class separately
                       # and throws ArgumentException on a foreign id
                       # (RevitAPI.xml). Collapsing them into one pool of
                       # "reinforcement types" would mean replacing a
                       # typed refusal with a runtime exception inside
                       # the transaction.
                       #
                       # `rebar_hook_types` is needed EXACTLY as a pool,
                       # even though omitting the hook is legitimate:
                       # omission means "no hooks," and the author must
                       # have the ability to NAME a hook by name —
                       # otherwise the only expressible reinforcement
                       # would be reinforcement without anchorage.
                       "area_reinforcement_types", "rebar_bar_types",
                       "rebar_hook_types")
        # 🔴 THE GUARD WAS READING HALF OF ITS OWN INPUT (24.08.2026, an
        # audit finding, confirmed against the places of definition).
        #
        # An op's pool name lives in TWO fields: the static `grounded`
        # and the table `grounded_pool_by_param`
        # (`registry_base.py:670`), by which `grounded_for(op)` selects
        # the pool BY THE PARAMETER'S VALUE — it is exactly this table
        # that execution (`ground.py`) and the static consumers
        # (`open_model.required_grounding_pools`) read. This loop was
        # only walking the first. `__post_init__` checks the table, but
        # only for naming GROUNDED FIELDS — the POOL names there are not
        # checked against anything.
        #
        # The cost: a typo in the table passes through silently,
        # `create_wall_type(host_kind="roof")` grounds into a
        # nonexistent pool, the snapshot brings back no such pool, and
        # the author gets `KIR-G101 "type not found"` — a refusal naming
        # the WRONG CAUSE, exactly the one this table was set up to
        # eliminate.
        пары = [(pname, pool) for pname, pool, _req in op.grounded]
        if op.grounded_pool_by_param is not None:
            _gname, gtable = op.grounded_pool_by_param
            for _value, pools in gtable.items():
                пары.extend(pools.items())
        for pname, pool in пары:
            variants = ([pool.format(category=c) for c in ("structural", "architectural")]
                        if "{category}" in pool else [pool])
            for v in variants:
                if v not in known_pools:
                    raise AssertionError(f"{op.name}.{pname}: unknown snapshot pool {v!r}")


_lint_registry()


def ops_by_object_kind(*, writes: bool | None = None) -> list[tuple[str, list[str]]]:
    """Op names grouped by the OBJECT KIND of their capability cells.

    NO TEXT THAT REACHES THE MODEL PRINTS THIS GROUPING ANY LONGER (09.08).
    Before that day, both the tool description and `course.spec()`
    printed it — meaning an internal registry field (`element`,
    `element/mep_system`, `category/element`) stood on the surface, and
    the author could not use it: nothing in the text explained why
    `create_wall` was separated from `create_floor`. Both readers moved
    to `ops_by_discipline`.

    THE ONLY REMAINING READER IS A NEGATIVE CONTROL
    (`test_tool_doc.test_the_op_list_is_grouped_by_discipline_not_by_a_
    compiler_field`): it takes the headers from here and requires that
    NONE of them appear in the description. The function is therefore
    not dead, but not functional either — it formulates a PROHIBITION,
    and deleting it would mean removing the guard that keeps the
    compiler field from returning to the surface in the next wave.

    `writes=True` — only ops that write to the model, `False` — only
    reading ones, `None` — all together. Group order: large groups
    first, then alphabetical.
    """
    groups: dict[str, list[str]] = {}
    for name, op in sorted(OPS.items()):
        if writes is not None and op.writes_model is not writes:
            continue
        key = "/".join(sorted({kind for _action, kind in op.capability}))
        groups.setdefault(key, []).append(name)
    return sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))


#: THE DISCIPLINE LABEL FOR PRINTING. This is a TRANSLATION, not a
#: second discipline dictionary: the keys are obligated to match
#: `registry_base.DISCIPLINES` character for character, and this is held
#: by a test, not a convention. Why translate at all: in the text, the
#: discipline stands as a group HEADING, meaning it is paid for on every
#: request, and "АР" against "architectural" is 2 characters against 13
#: on each of the six groups; and also, АР/КР/ОВ/ВК/ЭОМ are the very same
#: letters by which the extractor itself names disciplines when it
#: guesses a link's discipline from its name (`__Discipline`).
DISCIPLINE_RU: dict[str, str] = {
    "architectural": "АР (архитектура)",
    "structural": "КР (конструкции)",
    "mechanical": "ОВ (вентиляция)",
    "plumbing": "ВК (водоснабжение)",
    "electrical": "ЭОМ (электрика)",
    "shared": "общее",
}

#: Group order in the text is EXPLICIT and by discipline, not by group
#: size. The author plans "first АР, then КР, then the engineering
#: disciplines," and an order that jumps around depending on which wave
#: added the op reads as random.
DISCIPLINE_ORDER: tuple[str, ...] = (
    "architectural", "structural", "mechanical", "plumbing", "electrical",
    "shared",
)


@_lru_cache(maxsize=1)
def _category_disciplines() -> dict[str, str]:
    """The "BuiltInCategory -> discipline" table, ASSEMBLED, not
    hand-written.

    There is no second discipline dictionary in the package, and setting
    one up is forbidden (see `registry_base.DISCIPLINES`). So a
    category's discipline is taken from TWO carriers of that same
    dictionary, which already exist and are maintained for other work:

    * `registry_base.KINDS` — the query kind; its `collector_cs` names
      the BuiltInCategory right in the collector's text;
    * `decompile.extract._CATEGORY_SPECS` — the extraction table; its
      rows are exactly the categories the pipeline reads.

    A discrepancy between them is not "pick whichever is convenient" but
    an ERROR: one category cannot belong to two disciplines. So a
    conflict drops the assembly right here, rather than traveling
    silently into the text the model reads.

    The extractor's import is lazy: `spec` is pulled in by everyone,
    while `decompile.extract` drags in the L0 schema and reading helpers
    along with it.
    """
    import re as _re

    from kir.decompile.extract import _CATEGORY_SPECS

    table: dict[str, str] = {}

    def put(category: str, discipline: str, where: str) -> None:
        seen = table.setdefault(category, discipline)
        if seen != discipline:
            raise AssertionError(
                f"{category}: раздел разошёлся между носителями одного "
                f"словаря — {seen!r} против {discipline!r} ({where})")

    for kind in KINDS.values():
        for category in _re.findall(r"BuiltInCategory\.(OST_\w+)",
                                    kind.collector_cs):
            put(category, kind.discipline, f"KINDS[{kind.name!r}]")
    for cat in _CATEGORY_SPECS:
        put(cat.name, cat.discipline, "extract._CATEGORY_SPECS")
    return table


# ═════════════════════════════════════════════════════════════════════════
# THE READING SIDE LAGS BEHIND THE WRITING SIDE, AND THE LAG IS NOW CLOSED
#
# MEASUREMENT OF 12.08.2026. The registry's writing ops spawn 61 census
# categories; the carriers of the discipline dictionary
# (`KINDS[*].collector_cs` and `extract._CATEGORY_SPECS`) name 42 of
# them. The remaining 19 are below. The consequence is visible from the
# outside: 22 writing ops out of 65 get no discipline at all, and seven
# of them are KR (three loads, a truss, a framing system, area
# reinforcement, a strip foundation). An author of the KR discipline
# sees THREE operations in their list, while the other seven stand under
# the heading "discipline not derived."
#
# THIS IS THE SAME CLASS AS `query_types.pool`, JUST IN A DIFFERENT
# CURRENCY. There, KIR knows how to WRITE into six pools it does not
# know how to READ; here, it knows how to write into 19 categories that
# no reading carrier names. Both sides are lists that are maintained
# separately, and nothing forced them to agree. The remedy is the same
# one: the set the reading side is obligated to cover is DERIVED from
# the writing side, and every uncovered member is a NAMED refusal. There
# is no empty third option, and this is held by a test
# (`tests/test_write_side_read_side_parity.py`).
#
# WHAT THIS JOURNAL DOES NOT DO. It does not touch the ACCEPTANCE JUDGE:
# the judge knows the result category exactly for all three loads
# (`exact`, the upper and lower bounds are intact — checked by
# `derive_expectation` on programs already accepted by the gate 6/6). The
# third pillar of the cardinal invariant is NOT lost for them, and
# claiming otherwise would be a lie in the expensive direction. The
# judge's blindness is a separate, ALREADY closed accounting:
# `acceptance._OPS_BLIND` plus
# `tests/test_registry_category_accounting.py`, where the unnamed count
# is zero.
#
# WHY YOU CANNOT JUST ADD LINES TO THE EXTRACTION TABLE. A row there
# asserts that the pipeline READS that category. Adding one without the
# extractor would mean creating exactly the defect this journal exists
# to forbid: a value declared in one place and read in another, with
# nothing forcing them to agree.
# ═════════════════════════════════════════════════════════════════════════

#: Category -> why its discipline is not derived. The key is the
#: category, not the op: an op gets its discipline through its
#: categories, and the decision is made where the gap is real.
CATEGORIES_WITHOUT_DISCIPLINE = Ledger(
    "spec.CATEGORIES_WITHOUT_DISCIPLINE",
    {
        # ── Analytical loads: the pipeline has no analytical-model stage.
        # The acceptance judge knows the RESULT category exactly for all
        # three (it is set by the API class itself), so here there is
        # exactly one gap: there is no one to read them.
        # ── ROUTE PLACEHOLDERS: THE CATEGORIES APPEARED ON 03.09.2026,
        # AND THIS IS NOT A REGRESSION BUT A REFUTATION. Before that day,
        # the tree carried the argument "Revit does not give a
        # placeholder its own category; it stays in
        # OST_DuctCurves/OST_PipeCurves and differs only by the
        # IsPlaceholder bit." A live measurement removed it: the
        # categories are THEIR OWN, and both compile on 2021-2026. The
        # registry was fixed in the same move — and that is exactly why
        # two writing ops lost their discipline: the discipline
        # dictionary is assembled from the `KINDS` collectors, and the
        # placeholder collector goes BY CLASS with the `IsPlaceholder`
        # predicate, without naming the category in text.
        #
        # They cannot be added to the dictionary by hand: there is no
        # second discipline dictionary in the package, and setting one
        # up is forbidden (`_category_disciplines`). So the gap IS
        # NAMED here, and it will be closed by the move that gives
        # placeholders a row in the extraction table — today there is no
        # one to read them.
        "OST_PlaceHolderPipes": Entry(
            CLOSE_BY, "2026-09-03", "2026-10-03",
            "create_pipe_placeholder: категория своя (замер 03.09.2026, "
            "компилируется 2021-2026), но коллектор рода идёт по классу с "
            "предикатом IsPlaceholder и категорию текстом не называет; в "
            "таблице извлечения строки заготовок нет — читать их некому, "
            "поэтому раздел ВК этой категории вывести неоткуда"),
        "OST_PlaceHolderDucts": Entry(
            CLOSE_BY, "2026-09-03", "2026-10-03",
            "create_duct_placeholder: то же самое второй заготовкой; "
            "отдельная строка, потому что решение принимается по КАТЕГОРИИ, "
            "а не по стадии — тот же уклад, что у трёх нагрузок выше"),
        # ── Building pad and topography: the pipeline has no site stage
        # at all.
        "OST_Toposolid": Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "create_topography(toposolid): толща рельефа — ОТДЕЛЬНАЯ "
            "категория Revit, и сумма по двум скрыла бы ровно ту подмену, "
            "ради запрета которой у опа появилась разновидность"),
        "OST_Site": Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "create_directshape/solid_extrusion/solid_revolve с category="
            "site: DirectShape перепись ключует литералом 'DirectShape', а "
            "таблица извлечения не называет ни одной его категории"),
        # ── Profiles by host: the pipeline has no rounds stage.
        # ── Flat detailing: lives in a VIEW, and the parsers read the
        # model.
        # ── Stairs assembly: the table knows the run and the run's
        # railing, but not the container and not the landing.
        "OST_MultistoryStairs": Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "create_multistory_stairs: контейнер многоэтажной лестницы "
            "живёт в своей категории, а таблица извлечения знает только "
            "OST_Stairs — марш остаётся тем же элементом, которым был"),
        "OST_Railings": Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "create_railing: таблица знает ОГРАЖДЕНИЕ МАРША "
            "(OST_StairsRailing), но не самостоятельное ограждение; в 31 "
            "разборе OST_Railings не встретился ни разу — это замер "
            "читающей стороны, а не утверждение, что их не бывает"),
        # ── Openings and volumes.
        "OST_CeilingOpening": Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "create_opening(host_face): таблица знает проём в перекрытии, "
            "кровле и шахте, но не в потолке; в переписи восьми зданий он "
            "не встретился ни разу, а умеет его ОПЕРАЦИЯ"),
        "OST_Mass": Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "create_directshape/solid_extrusion/solid_revolve с category="
            "mass: та же дыра DirectShape, что и у site — перепись ключует "
            "литералом, а таблица извлечения не называет его категорий"),
        "OST_Entourage": Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "create_directshape/solid_extrusion/solid_revolve с category="
            "entourage: третья категория той же закрытой таблицы "
            "DIRECTSHAPE_CATEGORIES, и пробел у всех трёх один"),
    },
    instrument=(
        "tests/test_write_side_read_side_parity.py: множество категорий "
        "берётся у РЕЕСТРА (op_census_categories по пишущим опам), "
        "покрытие — у `_category_disciplines()`; строка журнала на "
        "категорию, которую носители уже называют, роняет тест как "
        "просроченная"))


# ═════════════════════════════════════════════════════════════════════════
# A `post` CLAUSE IS OBLIGATED TO NAME THE KIND OF ASSERTION IT IS
# CHECKED BY
#
# MEASUREMENT OF 21-22.08.2026, AND THE VERY FIRST NUMBER TURNED OUT TO
# BE ABOUT THE WRONG THING. The census (`tools/op_census.py:post_axes`)
# declared: 218 of 365 `post` clauses do not name an axis. The recount
# matched exactly (the criterion: a bracket made of exactly one axis
# word), but the CONCLUSION drawn from it did not follow: an axis clause
# has THREE carriers, and the prose is the only one of them that NO ONE
# reads.
#
#   1. `OpSpec.post` — this very prose. It has not a single consumer for
#      its bracket: `translation_cert.audit_registry_coverage` STRIKES
#      OUT the axis words entirely (they are in `filler`), comparing
#      clauses by the remaining words;
#   2. `translation_cert.Obligation.kind` — the machine kind. It is read
#      by `serving._unwitnessed_axes`, which uses it to decide whether
#      the OP promised anything at all along an axis;
#   3. the witness message text (`WitnessCheck.message`) — by the
#      substring `(geometry)`/`(topology)` in it,
#      `serving._axes_from_violations` sorts an ALREADY-OCCURRED
#      violation by axis; everything unmarked travels into semantics.
#
# SO STAMPING AN AXIS ON RETROACTIVELY WOULD BE A LIE OF A NEW FORM, and
# the cure is not to add a word. The label here is COPIED from carrier
# #2 — that very `Obligation.kind`, which the certificate already
# enforces (`certify_op` drops the program if the witness is missing or
# dead). Then the prose stops being decoration and becomes a SECOND,
# CROSS-CHECKED form of the machine fact: their equality is held by
# `kir/tests/test_post_clause_kind.py`.
#
# WHY THERE ARE SIX KINDS AND THREE AXES, AND THIS IS NOT SCOPE CREEP.
# The honest answer for the clause "the wall exists" is not "semantic"
# but "this is NOT an axis": it is checked by `materialize`. A label
# that says outright "not an axis" is exactly what turns silence into a
# named absence; a "semantic" label, put there just to fill in the
# column, would return exactly the green-by-construction result all of
# this was set up against.
#
# 🔴 WHAT THIS GUARD DOES NOT DO. It checks that a kind is NAMED, not
# that the witness ACTUALLY CHECKS it: only the certificate can do the
# latter, and it cannot be asked from here — `translation_cert` imports
# `spec`, not the other way around. The check "named kind ==
# `Obligation.kind`" therefore lives in a test, the same way journals
# have a deadline: see `record_ratchet` about the same boundary.
# ═════════════════════════════════════════════════════════════════════════
POST_CLAUSE_KINDS = ("geometry", "topology", "semantic",
                     "materialize", "parameter", "identity")

#: Clause -> why it will NOT get a kind until the named work is done. The
#: key is `"<op>::<distinguishing substring of the clause>"`, because the
#: decision is made on the CLAUSE, not on the op: `create_room` has one
#: clause waiting to be split and another describing emission order, and
#: a single string per op would glue two different gaps into one.
CLAUSES_WITHOUT_KIND = Ledger(
    "spec.CLAUSES_WITHOUT_KIND",
    {
        # ── The clause carries SEVERAL assertions of different kinds. One
        # label would not lie about only one of them — and would stay
        # silent about the rest.
        "create_tag::marked element == target": Entry(
            CLOSE_BY, "2026-08-22", "2026-09-21",
            "одна клауза держит ТРИ обязательства: марка существует "
            "(materialize), принадлежит in_view (topology) и связана с "
            "target (semantic). Любая одна метка умолчит про две; "
            "закрывается расщеплением клаузы на три, а не выбором ярлыка"),
        "create_room::room exists and has nonzero enclosed area": Entry(
            CLOSE_BY, "2026-08-22", "2026-09-21",
            "клауза держит два обязательства, и это признано в самой "
            "таблице: `Obligation.clause` у неё дословно «room exists and "
            "nonzero area (materialize / semantic)». Пока клауза одна, "
            "честного ярлыка у неё нет; закрывается расщеплением"),
        # ── The witness DOES EXIST, but the two carriers of the kind
        # disagree with each other. While they argue, a label in the
        # prose would silently pick a winner.
        "create_text::when leader_to given": Entry(
            CLOSE_BY, "2026-08-22", "2026-09-21",
            "обязательство `leader` объявлено семантикой, а сообщение "
            "свидетеля кончается на `(geometry)` — то есть нарушение выноски "
            "уедет на ГЕОМЕТРИЧЕСКУЮ ось, а `unwitnessed_axes` считает "
            "объявленной СЕМАНТИЧЕСКУЮ. Спор решается в `authoring.py` либо "
            "в таблице обязательств, не здесь"),
        # ── There is no witness at all, and the coverage audit does not
        # see this.
        "create_dimension::every ref visible in in_view": Entry(
            CLOSE_BY, "2026-08-22", "2026-09-21",
            "у клаузы НЕТ обязательства: эмиттер размера выдаёт свидетелей "
            "`in_view`/`references`/`value` и ни одного про ВИДИМОСТЬ "
            "ссылки. Аудит покрытия пропускает её по общим словам «ref» и "
            "«view» — та самая слабость сверки по подстроке, названная в "
            "шапке `audit_registry_coverage`. Снять живьём: отказывает ли "
            "Revit сам на невидимой ссылке"),
        # ── A promise about EMISSION ORDER, not about the state after
        # commit.
        "create_room::placed after doc.regenerate()": Entry(
            STANDS, "2026-08-22", "",
            "это правило ПЛАНА, а не постусловие: «помещение ставится после "
            "Regenerate, когда стены идут раньше» проверяемо на компиляции и "
            "не имеет наблюдаемого следа после коммита. Рода обязательства у "
            "него не будет никогда — стоячее решение, а не отложенная работа"),
    },
    instrument=(
        "kir/tests/test_post_clause_kind.py: строка журнала на клаузу, "
        "которая УЖЕ назвала род, роняет тест как просроченная; строка, "
        "чьей подстроки нет ни в одной клаузе своего опа, роняет тест как "
        "мёртвая"))

#: How many clauses are STILL unresolved — by op, measured 22.08.2026
#: (163 in total).
#:
#: THIS IS NOT A LIST OF EXCUSES, but a ratchet: DELIBERATELY, not a
#: single line here carries a reason. A line with a reason lives in
#: `CLAUSES_WITHOUT_KIND` above and is obligated to carry a date and a
#: deadline; here there is only a NUMBER, and the only thing it is
#: allowed to do is not grow. Mixing the two would mean passing off
#: "never got to it" as a decision made.
#:
#: 16 ops are resolved, and they make up an ENTIRE REAL building in full
#: (a decompile of MNVNK, 19 041 operations: create_wall 7845,
#: place_family 5340, create_tag 1285, create_door 1230,
#: create_room_separator 1086, create_text 809, create_dimension 667,
#: create_room 467, create_railing 86, create_beam 76, create_floor 58,
#: create_grid 31, create_level 30, create_roof 28, create_column 2,
#: create_ceiling 1). Not one of the ops listed below is in this
#: building.
CLAUSES_WITHOUT_KIND_BASELINE: dict[str, int] = {
    "author_family": 3,
    "change_type": 2,
    "create_angular_dimension": 1,
    "create_area_load": 3,
    "create_area_reinforcement": 4,
    "create_beam_system": 3,
    "create_building_pad": 3,
    "create_cable_tray": 4,
    "create_conduit": 2,
    "create_curtain_grid_line": 2,
    "create_directshape": 2,
    "create_duct": 3,
    "create_duct_placeholder": 2,
    "create_extrusion_roof": 2,
    "create_face_wall": 5,
    "create_flex_duct": 2,
    "create_flex_pipe": 2,
    "create_floor_by_contour": 3,
    "create_foundation": 5,
    "create_group": 3,
    "create_line_load": 3,
    "create_multi_segment_grid": 3,
    "create_multistory_stairs": 4,
    "create_opening": 4,
    "create_path_of_travel": 2,
    "create_pipe": 3,
    "create_pipe_placeholder": 2,
    "create_pipe_system": 2,
    "create_point_load": 4,
    "create_site_subregion": 2,
    "create_slab_edge": 2,
    "create_solid_blend": 1,
    "create_solid_boolean": 3,
    "create_solid_extrusion": 1,
    "create_solid_revolve": 1,
    "create_solid_sweep": 1,
    "create_space": 1,
    "create_stairs": 5,
    "create_stairs_landing": 5,
    "create_stairs_run": 3,
    "create_surface": 1,
    "create_topography": 3,
    "create_truss": 3,
    "create_type": 3,
    "create_wall_foundation": 2,
    "create_wall_sweep": 3,
    "create_window": 2,
    "delete": 2,
    "join_elements": 3,
    "load_family": 4,
    "move_elements": 4,
    "query_count": 2,
    "query_inspect": 1,
    "query_list": 2,
    "query_surface": 5,
    "query_types": 2,
    "route_duct_system": 5,
    "route_pipe_system": 4,
    "set_curtain_panel": 2,
    "set_param": 2,
}


def post_clause_kind(clause: str) -> str | None:
    """The kind named by the clause, or ``None``. ONE reader for the
    whole tree.

    The rule is written here exactly once: a kind is named if the clause
    has a bracket made of EXACTLY its name. A bracket like
    ``(geometry, -300mm floor)`` does NOT count as a kind — and this is
    not pedantry but the same criterion by which
    `serving._axes_from_violations` looks for an axis in a witness
    message: there too the substring is exact, and because of it three
    live messages end up on the wrong axis. A soft rule here and a
    strict one there would drift apart silently.
    """
    low = clause.lower()
    found = [k for k in POST_CLAUSE_KINDS if f"({k})" in low]
    if len(found) != 1:
        return None
    return found[0]


def post_clauses(op) -> list[str]:
    """The `post` clauses of one op. The separator is ";", same as the
    certificate.

    A separate function because this split already has three readers
    (`audit_registry_coverage`, the census, the guard below), and three
    separate `split(";")` calls are three rules that will drift apart.
    """
    return [c.strip() for c in (getattr(op, "post", "") or "").split(";")
            if c.strip()]


def clauses_without_kind() -> dict[str, list[str]]:
    """Op -> its clauses that have no kind and no line in the journal
    either.

    The lines of `CLAUSES_WITHOUT_KIND` are SUBTRACTED from here: for
    them a decision has been made and recorded, and counting them
    together with the unresolved ones would mean losing the difference
    between "decided not to set one" and "never got to it."
    """
    out: dict[str, list[str]] = {}
    for name, op in sorted(OPS.items()):
        for clause in post_clauses(op):
            if post_clause_kind(clause) is not None:
                continue
            low = clause.lower()
            if any(key.split("::", 1)[0] == name
                   and key.split("::", 1)[1] in low
                   for key in CLAUSES_WITHOUT_KIND):
                continue
            out.setdefault(name, []).append(clause)
    return out


def _lint_post_clause_kinds() -> None:
    """A ratchet on import: a new clause with no kind is NOT CREATED
    SILENTLY.

    TWO REFUSALS, AND THEY ARE DIFFERENT. Two labels on one clause is an
    ambiguity, and it is always forbidden. Growth in the number of
    clauses without a kind is forbidden PER OP: for an op in the
    baseline, the count can only fall; for an op outside it, the count
    is obligated to be zero. A total sum does not work as this guard: it
    would allow labeling one clause while unlabeling another.

    WHY THIS IS AN IMPORT-TIME CHECK, NOT A TEST. By the same law as the
    rest of `_lint_registry`: the registry is the sole carrier, and a
    typo in it does not break a single program, it just quietly drops a
    promise. The cost of an error here is asymmetric, and the fix costs
    one word in brackets, and that word is named right in the refusal
    itself.
    """
    for name, op in sorted(OPS.items()):
        for clause in post_clauses(op):
            low = clause.lower()
            found = [k for k in POST_CLAUSE_KINDS if f"({k})" in low]
            if len(found) > 1:
                raise AssertionError(
                    f"{name}: клауза post называет СРАЗУ {found} — род один "
                    f"на клаузу, иначе читатель не знает, что именно "
                    f"проверено: {clause[:90]!r}")
    unlabelled = clauses_without_kind()
    for name, clauses in sorted(unlabelled.items()):
        ceiling = CLAUSES_WITHOUT_KIND_BASELINE.get(name, 0)
        if len(clauses) <= ceiling:
            continue
        raise AssertionError(
            f"{name}: клауз post без названного рода {len(clauses)}, а "
            f"базовая линия 22.08.2026 разрешает {ceiling}. Счётчик "
            f"обязан УБЫВАТЬ. Допиши в клаузу скобку с родом из "
            f"POST_CLAUSE_KINDS — тем же, что стоит у её обязательства в "
            f"`translation_cert.REFINEMENT`; если рода честно нет, заведи "
            f"строку в `CLAUSES_WITHOUT_KIND` с причиной и сроком. "
            f"Без рода: {[c[:70] for c in clauses]}")


_lint_post_clause_kinds()


# ═════════════════════════════════════════════════════════════════════════
# AN OP'S RESULT CATEGORY — ONE ANSWER, AND IT IS HERE
#
# "Which category will Revit place this op's result into" is a question
# TO THE REGISTRY: it is about the operation, not about a specific
# building. Before 10.08.2026 there were two and a half answers:
# `acceptance._OP_CATEGORIES` (43 ops, tuples), `clash_bundle.OP_CATEGORY`
# (29 ops, strings) — and `op_census_categories` below, which asked the
# FIRST one, meaning the registry depended on the acceptance judge. That
# very fork is exactly the work that was being done twice.
#
# The table moved here IN FULL, together with its resolver: for five
# ops the category is decided by the op's own closed enum (`category`
# for the column and solid bodies, `variety` for the opening, the
# topography, the foundation), and a table without a resolver would
# answer incompletely. `acceptance` now reads from here.
#
# THERE IS NO LONGER A SECOND DICTIONARY (merged in `8ad465a0`). Before
# this, the text here read "`clash_bundle.OP_CATEGORY` remains a second
# dictionary: the file is occupied" and "there is exactly one
# discrepancy — `create_railing`." Both statements are stale, and the
# second was also WRONG at the time it was written: the merge found the
# tables had diverged in THREE ways, not one. The lesson is exactly the
# one this file keeps a single table for: while there are two answers,
# no one knows the number of discrepancies between them — it is
# ESTIMATED, and the estimate runs low.
#
# ABOUT "UNFILLED" OPS — ARITHMETIC, NOT A PROMISE (remeasured
# 11.08.2026, `tests/test_registry_category_accounting.py`, which also
# holds it going forward). Below are 44 rows for 73 writing ops, and the
# missing 29 are not a gap: EACH is named, but there are FIVE
# mechanisms, not three as the previous edition said:
#
#   1. a row in this table                                            44
#   2. a branch of the `op_result_categories` resolver below (the op's
#      own closed enum decides the category exactly)                  10
#   3. `acceptance._OPS_BLIND` — the census physically cannot see them,
#      each with a reason in words and a date                         13
#   4. `acceptance._OPS_WITHOUT_ELEMENTS` — they create no element       5
#   5. `acceptance._OP_DERIVED` + unfolding into MEMBERS — `create_group`:
#      Revit carries the group wrapper as its own bookkeeping, and the
#      expectation is built from the group's members                    1
#                                                                     ---
#                                                                      73
#
# 66 -> 67 (18.08.2026): `join_elements` went into mechanism 4. It does
# not create an element at all — it changes the RELATIONSHIP between two
# already-standing ones — and that is exactly the kind mechanism 4 was
# set up for.
#
# 🔴 67 -> 73 (21.08.2026), AND THE INCREASE MATCHED NAME BY NAME, NOT BY
# FITTING. The free-form wave of 20.08 introduced SIX ops and one query;
# the family-authoring wave of 21.08 added one more. A query does not
# write, so writing ops +6:
#
#   create_solid_blend · create_solid_sweep · create_surface ·
#   create_solid_boolean · create_adaptive_component      wave 20.08
#   author_family                                         wave 21.08
#   (query_surface — READS, does not count toward writing ops)
#
# And the breakdown by mechanism shifted by exactly them:
#   mechanism 2:  6 -> 10  four ops of the DirectShape family (blend,
#                sweep, surface, boolean). Since 21.08 the family list
#                is DERIVED at the registry (`_directshape_result_ops`),
#                rather than enumerated: the handwritten four stood for
#                TWO FULL DAYS not knowing about the new three, holding
#                five red tests in a row;
#   mechanism 3: 11 -> 13  `author_family` and `create_adaptive_component`.
#
# The sum of mechanisms is cross-checked by a test as a SEPARATE
# assertion, and it matches: 44 + 10 + 13 + 9 + 1 = 77.
#
# 24.08.2026: 73 -> 77 writing ops, mechanism 4 (`_OPS_WITHOUT_ELEMENTS`)
# 5 -> 9. The increase matched name by name and went entirely into one
# mechanism, because all four share one question and one answer:
# `create_wall_type`, `transfer_family`, `create_floor_plan` (wave
# 23.08) and `transfer_material` (24.08) place a CATALOG entry or a
# VIEW into the document — a description of future elements — not a
# building element. The instance census cannot see them by
# construction, exactly like `create_type` and `load_family`, which
# have stood in this mechanism from the start.
#
# 🔴 THREE OF THE FOUR STOOD OUTSIDE THE TABLES FOR A FULL DAY, and the
# cost is named as a number: 23 red tests across seven registry
# censuses rested on exactly them, and nine of them are neighbors in
# the clash receipt file, failing only because each one assembles the
# whole receipt. The debt was visible only under a full run of the
# suite, which dies from OOM on this box — that is, it was not visible.
#
# THE FIFTH MECHANISM WAS NOT NAMED AT ALL BY THE PREVIOUS EDITION, and
# its sum (43+10+4+7) added up to 64 only because both the addends and
# the total were taken on the same day and had drifted apart since.
# Hence the rule: this arithmetic is held by a TEST, not a paragraph.
# The paragraph explains WHY, the test answers HOW MANY.
#
# FILLING IN THE MISSING IS FORBIDDEN. Adding an op here whose cell the
# census does not observe means FORCING acceptance to wait for an
# increase it will never see — that is, rejecting an HONEST build. A
# blindness error is reversible (only the upper bound is lost); a
# fill-in error is not. That is exactly why `create_curtain_grid_line`
# and `create_wall_foundation` HAVE NO rows here and must not have any,
# until a measurement appears:
#   * `create_curtain_grid_line` — the grid line divides cells, and how
#     many mullioned panels result from it is decided by Revit (STANDS);
#   * `create_wall_foundation` — the strip-foundation cell is NOT
#     MEASURED: WallFoundation has not occurred in a single saved
#     decompile, and naming it by Revit's taxonomy is exactly the guess
#     that would sink a correct build (CLOSE_BY, closed by ONE live
#     run: the receipt already carries the Category.Id of the created
#     element).
# An absence here is NAMED there; these are different things.
# ═════════════════════════════════════════════════════════════════════════

#: WRITING OPS THAT ADD NOT A SINGLE ELEMENT TO THE CENSUS.
#:
#: 🔴 MOVED HERE FROM `acceptance` ON 28.08.2026, AND THIS IS NOT JUST
#: RESHUFFLING. The registry was asking for this list from the
#: ACCEPTANCE JUDGE — that is, from its own consumer — and the
#: architectural lock
#: (`test_one_answer_per_question::test_the_registry_no_longer_imports_its_own_consumer`)
#: was turning red on this, rightfully: the direction of dependency is
#: obligated to run the other way. There was a precedent right here,
#: nearby: the category table was moved in the same step, and
#: `acceptance._OP_CATEGORIES` became an alias, with identity held by
#: `assertIs`.
#:
#: THIS WAS NOT CURED WITH A SECOND LIST. A copy of the names would
#: drift from the original on the very first new op — a named defect of
#: this tree. So the object is ONE, and it lives at the registry;
#: acceptance looks at it.
#:
#: AND A SILENT FALLBACK DISAPPEARED ALONG WITH THE MOVE. A lazy import
#: stood in TWO places, and in one of them the failure was swallowed
#: (`except ImportError: pass`): the op was silently deemed NOT
#: cataloged, and there was nothing left to tell "not cataloged" apart
#: from "there was no one to ask" — a zero assembled from a swallowed
#: failure. Now there is no one to ask: the list is its own.
#:
#: ── WHY EACH NAME IS HERE, WITH DATES ───────────────────────────────────
#: `create_type`/`load_family` make TYPES, and the census §18.1 is
#: `WhereElementIsNotElementType()`; `set_param`/`move_elements` edit
#: something that already exists.
#:
#: `join_elements` (18.08.2026) — the op changes the RELATIONSHIP
#: between two already-standing elements. After it, the document has
#: exactly as many elements as before; expecting an increase from the
#: census would mean rejecting an HONEST build — the very same
#: irreversible fill-in error this file's header warns about.
OPS_WITHOUT_ELEMENTS: frozenset[str] = frozenset({
    "create_type", "load_family", "set_param", "move_elements",
    "join_elements",
    # ── FOUR CATALOG-AND-VIEW OPS, RESOLVED 24.08.2026 ─────────────────
    # The precedent is `create_type` and `load_family`, which have stood
    # here from the start: acceptance counts BUILDING ELEMENTS, while a
    # catalog entry places a DESCRIPTION of future elements into the
    # document. A wall type, a family, a material, and a floor plan are
    # real Revit elements, but none of them adds a wall or a floor to
    # the building; those appear via `create_wall`, `place_family`, and
    # their neighbors, where they get counted.
    #
    # Three of the four arrived on 23.08 and stood outside the table for
    # a full day: the law was turning red, and the whole classification
    # was silent along with it. The fourth — `transfer_material` (24.08)
    # — is closed in the same move, so the debt does not grow.
    "create_wall_type", "transfer_family", "transfer_material",
    "create_floor_plan",
})

#: OP → CENSUS KEYS ITS RESULT WILL LAND IN. A tuple longer than one
#: means "into one of them, and which one is not visible" (the sum is
#: cross-checked).
OP_RESULT_CATEGORIES: dict[str, tuple[str, ...]] = {
    "create_wall": ("OST_Walls",),
    "create_floor": ("OST_Floors",),
    "create_floor_by_contour": ("OST_Floors",),
    "create_roof": ("OST_Roofs",),
    "create_ceiling": ("OST_Ceilings",),
    "create_door": ("OST_Doors",),
    "create_window": ("OST_Windows",),
    "create_room": ("OST_Rooms",),
    "create_level": ("OST_Levels",),
    "create_grid": ("OST_Grids",),
    "create_extrusion_roof": ("OST_Roofs",),
    # A multistory stairs lives in ITS OWN category, not in OST_Stairs:
    # `MultistoryStairs.Create` creates a container, and the original
    # run remains the same element it was.
    "create_multistory_stairs": ("OST_MultistoryStairs",),
    "create_beam": ("OST_StructuralFraming",),
    "create_stairs": ("OST_Stairs",),
    # A landing lives in ITS OWN category and does NOT add a stairs: the
    # host is already standing in the model, and
    # `CreateSketchedLanding` hangs a component onto it. That is exactly
    # why there is one row here, not "OST_Stairs + OST_StairsLandings":
    # a second census cell would mean "this program built a stairs,"
    # and an honest success would read as an unordered, foreign create.
    "create_stairs_landing": ("OST_StairsLandings",),
    "create_pipe": ("OST_PipeCurves",),
    "create_duct": ("OST_DuctCurves",),
    "create_cable_tray": ("OST_CableTray",),
    # wave/mep-electrical (2026-08-09). The category is known EXACTLY
    # for all five: it is set by the API call itself
    # (Conduit/FlexDuct/FlexPipe — their own classes), not by a type
    # selector.
    #
    # 🔴🔴 CORRECTION 03.09.2026: A CONFIDENT STATEMENT STOOD HERE, THE
    # OPPOSITE OF THE TRUTH. Verbatim: "Revit does not give a
    # placeholder its own category; a `Pipe` stays a `Pipe`, differing
    # only by the `IsPlaceholder` bit." A LIVE MEASUREMENT (Revit 2026,
    # «Проект1», elements built by these same ops):
    #
    #     Pipe · IsPlaceholder=True -> BuiltInCategory OST_PlaceHolderPipes
    #                                  («Трубопровод по осевой»)
    #     Duct · IsPlaceholder=True -> BuiltInCategory OST_PlaceHolderDucts
    #                                  («Воздуховоды по осевой»)
    #
    # A deliberately nonexistent member in the same run gives CS0117,
    # meaning the instrument discriminates; both members compile on
    # 2021-2026 (live Roslyn :52412, six runs).
    #
    # THE COST OF THIS FALSEHOOD WAS NOT THEORETICAL. The independent
    # acceptance census was looking for the increase in OST_PipeCurves,
    # while the element landed in OST_PlaceHolderPipes, and both ops got
    # `KIR-A006` — "the write was committed, but an independent re-read
    # found a discrepancy." That is, the STRICTEST instrument in the
    # house was declaring a correctly built element defective. Worse
    # than the direct damage is this second effect: as long as A006
    # sits permanently on these ops, a REAL discrepancy on them will be
    # indistinguishable from the background.
    "create_conduit": ("OST_Conduit",),
    "create_pipe_placeholder": ("OST_PlaceHolderPipes",),
    "create_duct_placeholder": ("OST_PlaceHolderDucts",),
    "create_flex_duct": ("OST_FlexDuctCurves",),
    "create_flex_pipe": ("OST_FlexPipeCurves",),
    # wave/analysis (2026-08-09). The category is known EXACTLY for all
    # four — it is set by the API call itself
    # (PointLoad/LineLoad/AreaLoad/PathOfTravel — their own Revit
    # classes), not by a type selector. All four BuiltInCategory members
    # are checked by compilation on 2021-2026.
    #
    # HONESTLY, ABOUT THE EXTRA ELEMENT: a point load and a line load
    # author their own sketch plane (`SketchPlane.Create`), that is,
    # they create one more element in the document beyond the one
    # named. It will not show up in the "unexpected" report: the census
    # counts against a CLOSED set of expected categories, and
    # `SketchPlane` is not among them. This is a limitation of the
    # census, not a claim that the element does not exist — and it is
    # written here precisely so that the next person cross-checking
    # numbers on a live model knows in advance.
    "create_point_load": ("OST_PointLoads",),
    "create_line_load": ("OST_LineLoads",),
    "create_area_load": ("OST_AreaLoads",),
    "create_path_of_travel": ("OST_PathOfTravelLines",),
    "create_pipe_system": ("OST_PipeCurves",),
    "route_pipe_system": ("OST_PipeCurves",),
    "route_duct_system": ("OST_DuctCurves",),
    "create_text": ("OST_TextNotes",),
    # wave/detail (2026-08-09): filled region. A SUM OVER TWO KINDS, and
    # this is not caution but the railing precedent, verbatim:
    # `FilledRegion.Create` accepts a fill type, and a masking region in
    # Revit is ALSO a FilledRegion, distinguished only by its type
    # (`IsMasking` — an INSTANCE property, readable only AFTER
    # creation). Which project types are masking is not visible from
    # the program, so choosing a single category would mean betting on
    # a guess; the sum is correct regardless of the answer. Both
    # constants exist on all six versions (measured by compilation).
    "create_filled_region": ("OST_FilledRegion", "OST_MaskingRegion"),
    "create_dimension": ("OST_Dimensions",),
    "create_angular_dimension": ("OST_Dimensions",),
    # wave/room (2026-08-03): the category is known EXACTLY — it is set
    # by the `NewRoomBoundaryLines` call itself, not by a type selector
    # (the operation has no type at all).
    "create_room_separator": ("OST_RoomSeparationLines",),
    # wave/space (2026-08-10): an MEP space. The category is known
    # EXACTLY and there is exactly one — it is set by the
    # `doc.Create.NewSpace` call itself, whose return type
    # `Autodesk.Revit.DB.Mechanical.Space` is proven by the compiler
    # (CS0029 on all six versions), not by a type selector: the
    # operation has no type at all. A pair of keys is not needed here —
    # the operation has no choice between categories in any field.
    #
    # WHY THIS ROW EXISTS, RATHER THAN BEING DECLARED BLIND. Blindness
    # is obligated to be a MEASUREMENT, not caution, and here there is a
    # measurement on both sides. The live census
    # (`acceptance_live.scope_census_fragment`) keys the element by
    # `Enum.GetName(typeof(BuiltInCategory), Category.Id)` across the
    # whole `WhereElementIsNotElementType()`, meaning it has no closed
    # category table at all — the only question is whether Revit gives a
    # space this category. It does: 169 spaces from THREE buildings of
    # the corpus (Electrical 80, Plumbing 43, Architectural 46) are read
    # by extraction EXACTLY as OST_MEPSpaces, `expected == extracted`,
    # `state: complete`. The member `BuiltInCategory.OST_MEPSpaces`
    # itself exists on all six versions (measured by compilation
    # 10.08). An error in this direction would give
    # `category_shortfall` and would REJECT an honest build, which is
    # why the row rests on measurement alone.
    "create_space": ("OST_MEPSpaces",),
    # wave/site (2026-08-09): a building pad — the category is known
    # EXACTLY, it is set by the `BuildingPad.Create` call itself, not by
    # a type selector.
    "create_building_pad": ("OST_BuildingPad",),
    # Site sub-region: the created ELEMENT is its TopographySurface (the
    # SiteSubRegion itself is not an element — measured, CS0029), so the
    # census will see it in exactly the same place as ordinary
    # topography.
    "create_site_subregion": ("OST_Topography",),
    # wave/sweep (2026-08-09). SLAB EDGE — the category is known
    # EXACTLY: it is set by the `NewSlabEdge` call itself, not by a type
    # selector.
    "create_slab_edge": ("OST_EdgeSlab",),
    # WALL SWEEP — TWO categories, and this is not caution but the
    # API's design. `WallSweep.Create` builds EITHER a cornice or a
    # reveal, and this is decided by the CATEGORY OF THE ALLOWED TYPE
    # (OST_Cornices versus OST_Reveals) — the census does not see the
    # `WallSweepType` enum itself, because it only sees elements. The
    # sum over the two is correct for any answer; choosing one would
    # mean rejecting every correctly built reveal (or every cornice) as
    # "the wrong category" — exactly the same argument by which the
    # column and the railing stand here in pairs.
    "create_wall_sweep": ("OST_Cornices", "OST_Reveals"),
    # wave/mass (2026-08-10). WALL BY FACE — the category is known
    # EXACTLY and there is exactly one: `FaceWall` is not `Wall`
    # (measured, CS0029 on all six), but its category is the same
    # OST_Walls, and it is set by the `FaceWall.Create` call itself, not
    # by a type selector. A pair is not needed here: the operation has
    # no choice between categories in any field.
    "create_face_wall": ("OST_Walls",),
    # Column: the category is chosen by the op's own CLOSED enum, so it
    # is known exactly — see `_category_of_op`.
    "create_column": ("OST_StructuralColumns", "OST_Columns"),
    # Railing: ``OST_Railings`` has not occurred in a SINGLE one of 31
    # decompiles, but the lifter's table knows both, and the Revit
    # version could decide otherwise. The sum over the two is correct
    # for any answer; choosing one would mean betting on a guess where
    # there is nothing to bet on.
    "create_railing": ("OST_Railings", "OST_StairsRailing"),
    # Tag: the tag's kind is determined by the TARGET'S CATEGORY, and
    # the target is an id or a reference, meaning it cannot be read from
    # the program. A sum over the kinds the pipeline reads at all
    # (`tag_extract.TAG_CATEGORIES`).
    #
    # 🔴 THIS IS THE SECOND CARRIER OF THAT LIST, AND IT HAS ALREADY
    # DRIFTED (22.08.2026). Capture learned to take `OST_WindowTags` —
    # 660 tags on MNVNK, 3 545 across the corpus — while the copy stayed
    # at ten kinds, and the acceptance judge's result category for
    # `create_tag` did not contain a window tag.
    #
    # WHY THERE IS A LITERAL HERE INSTEAD OF DERIVING IT FROM
    # `TAG_CATEGORIES` — MEASUREMENT, NOT LAZINESS. A derivation was
    # written (a lazy import in `op_result_categories`, like the one for
    # `_directshape_result_ops`) and REMOVED: the table itself has
    # THREE readers, and two of them take it RAW, bypassing the
    # function — `acceptance._OP_CATEGORIES` (:456) and an enum in
    # `authoring.py:7636`. A row that leaves the table for the function
    # disappears for them entirely; both ratchets caught exactly that.
    # The correct move is to collapse the three readers into one, and
    # that is a SEPARATE wave, not a tail end of a fix about window
    # tags.
    #
    # Until then, the discrepancy is held by a GUARD:
    # `test_tag_result_categories_match_the_capture_table` requires
    # this literal and `TAG_CATEGORIES` to be equal.
    "create_tag": (
        "OST_AreaTags", "OST_DoorTags", "OST_FloorTags", "OST_MaterialTags",
        "OST_MechanicalEquipmentTags", "OST_MultiCategoryTags",
        "OST_RoomTags", "OST_StairsRailingTags", "OST_StructuralFramingTags",
        "OST_WallTags", "OST_WindowTags",
    ),
}


@_lru_cache(maxsize=1)
def _directshape_result_ops() -> frozenset[str]:
    """Ops whose result is a DirectShape in a category from the closed
    table.

    The trait is DERIVED, not named: the op has a `category` parameter,
    and its enum matches `ops_shape.DIRECTSHAPE_CATEGORIES` EXACTLY.
    There is no other way to land in DirectShape at the registry, and
    the table matching is exactly the property that makes the census
    unable to tell them apart.

    Cached — the registry does not change over the process's lifetime.
    Whoever substitutes `spec.OPS` is obligated to call
    `_directshape_result_ops.cache_clear()`.
    """
    from kir.ops_shape import DIRECTSHAPE_CATEGORIES

    table = set(DIRECTSHAPE_CATEGORIES)
    return frozenset(
        name for name, op_spec in OPS.items()
        for p in op_spec.params
        if p.name == "category" and set(p.choices or ()) == table)


def op_result_categories(op: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Census keys for the op's result; None means the category is
    unknown."""
    name = op.get("op")
    if name == "create_column":
        # A closed enum with a default — the category is known exactly.
        category = op.get("category", "structural")
        return (("OST_StructuralColumns",) if category == "structural"
                else ("OST_Columns",))
    if name in _directshape_result_ops():
        # ONE BRANCH FOR ALL OPS THAT PLACE THEIR RESULT INTO
        # DirectShape: to the census they are INDISTINGUISHABLE by
        # construction — the same closed category table, the same
        # element coming out. A branch of its own for each would mean
        # that many places where the key could drift apart.
        #
        # 🔴 THE LIST IS DERIVED AT THE REGISTRY, NOT ENUMERATED, AND
        # THIS IS A FIX (21.08.2026). FOUR names stood here by hand, and
        # the free-form wave of 20.08 introduced three more —
        # `create_solid_blend`, `create_solid_sweep`, `create_surface`
        # — with the same category enum and the same DirectShape,
        # without adding them to the list. The census counted their
        # result as an UNKNOWN category for TWO FULL DAYS, and this
        # held five red tests in a row.
        #
        # The handwritten list here was a second carrier of exactly the
        # knowledge already sitting in the registry: "this op has a
        # `category` parameter with the closed table
        # DIRECTSHAPE_CATEGORIES." An eighth op of the same shape will
        # land here BY ITSELF; it can no longer be forgotten, because
        # there is no longer a list to forget it from.
        #
        # TWO KEYS, AND THIS IS NOT OVER-CAUTION. Census §18.1 keys the
        # element by its BuiltInCategory, while extraction rows place
        # the literal "DirectShape" into a field (extract.py) — across
        # 31 decompiles, the key "DirectShape" never appears in the
        # census, while it does appear in the rows. The sum over the
        # two is correct regardless of the census source.
        from kir.ops_shape import DIRECTSHAPE_CATEGORIES
        built_in = DIRECTSHAPE_CATEGORIES.get(op.get("category"))
        if built_in is None:
            return None
        return tuple(sorted((built_in, "DirectShape")))
    if name == "create_opening":
        # AN OPENING IS OBLIGATED TO NAME ITS OWN CATEGORY, otherwise
        # one new operation would weaken L2 for the WHOLE program: an
        # op with an unknown category drops the upper bounds entirely
        # (on a real facade this has already cost 270 ops out of
        # 2 720).
        if op.get("variety") == "wall_rect":
            # The `NewOpening(Wall, XYZ, XYZ)` overload gives exactly
            # one kind.
            return ("OST_SWallRectOpening",)
        # variety="host_face": the kind is determined by the HOST'S
        # CATEGORY, and the host is an id or a reference, meaning it
        # cannot be read from the program. A sum over the three kinds
        # this overload is capable of at all ("Creates a new opening in
        # a roof, floor and ceiling" — the method's documentation, not a
        # guess about the model). A ceiling opening has not occurred in
        # the census of eight buildings even once; it is here because
        # the OPERATION is capable of it.
        return ("OST_FloorOpening", "OST_RoofOpening", "OST_CeilingOpening")
    if name == "create_topography":
        # The op's own closed enum, so the category is known EXACTLY,
        # and this matters more than convenience: a surface and a solid
        # are DIFFERENT categories, and a sum over two keys would hide
        # exactly the substitution the operation's variety was
        # introduced to forbid in the first place.
        return (("OST_Toposolid",) if op.get("variety") == "toposolid"
                else ("OST_Topography",))
    if name == "create_foundation":
        if op.get("variety") == "isolated":
            # The symbol is grounded by the foundation_symbols pool —
            # that is
            # FilteredElementCollector(...).OfCategory(OST_StructuralFoundation)
            # (open_model.py), so the category is known exactly.
            return ("OST_StructuralFoundation",)
        # variety="slab" is emitted via `Floor.Create` with a type from
        # the floor_types pool: whether it is a floor or a foundation
        # slab is decided by the TYPE, which the compiler does not see.
        return ("OST_Floors", "OST_StructuralFoundation")
    return OP_RESULT_CATEGORIES.get(name)



def op_census_categories(ospec: OpSpec) -> tuple[str, ...]:
    """ALL census categories the op's result could land in.

    Taken from `op_result_categories` ABOVE, in this same file. Before
    10.08 the answer was taken from the acceptance judge
    (`acceptance._category_of_op`) — the registry was asking the
    category from its own consumer; now the table lives here, and
    acceptance reads it from here.

    For some ops the category depends on the op's own CLOSED enum
    (`category` for the column and the mesh, `variety` for the opening,
    the topography, the foundation). The enum lives in the registry
    (`ParamSpec.choices`), so there is no guessing here — it is
    iterated over in full and the answers are combined: an op's
    discipline is obligated to hold for ANY allowed value, otherwise it
    is not the op's discipline.

    Empty means the judge does not know the category; today there are
    18 such ops out of 58, and almost all of them edit someone else's
    elements (`set_param`, `delete`, `move_elements`, `change_type`) or
    create not an element but a type/family.
    """
    from itertools import product

    axes = [[(p.name, choice) for choice in p.choices]
            for p in ospec.params
            if p.name in ("category", "variety") and p.choices]
    found: set[str] = set()
    for combo in (product(*axes) if axes else [()]):
        probe: dict[str, object] = {"op": ospec.name}
        probe.update(dict(combo))
        cats = op_result_categories(probe)
        if cats:
            found.update(cats)
    return tuple(sorted(found))


def op_disciplines(ospec: OpSpec) -> tuple[tuple[str, ...], str]:
    """The op's disciplines and — if a discipline CANNOT be derived —
    a reason in words.

    The full derivation chain: op -> census categories (the acceptance
    judge) -> discipline (carriers of `registry_base.DISCIPLINES`). Not
    a single step by hand: a new op's discipline appears on its own as
    soon as it gets a row at the judge, and there is nowhere to get it
    wrong from memory.

    Three outcomes, and each is named:

    * the categories are known and all lead to one or two disciplines
      -> those disciplines;
    * `shared` is among them -> ONLY `shared`: `shared` in this
      dictionary means "belongs to everyone," and duplicating such an
      op across disciplines would mean paying for it five times over;
    * it CANNOT be derived -> EMPTY plus a reason. Empty, not `shared`:
      the discipline dictionary states outright, about `shared`, that
      it means "belongs to everyone," and NOT "unknown" (`registry_base`,
      header of `DISCIPLINES`). Dumping the undecided cases in here
      would mean asserting, about `create_truss`, that it is shared by
      all disciplines — that is, replacing an accounting gap with a
      confident lie, exactly the class this whole package is written
      against.
    """
    # THE EFFECT RULE, AND IT ALSO COMES FROM THE REGISTRY. An op that
    # does not CREATE works on someone else's element — placed there by
    # someone else — and such an op has no discipline of its own by
    # construction: `set_param` edits a wall, a pipe, and a panel
    # alike. This is exactly what the dictionary calls `shared`
    # ("belongs to everyone"), not an accounting gap, which is why
    # there is no reason here and there should not be one.
    if ospec.effect is not EffectKind.CREATE:
        return ("shared",), ""
    # THE CATALOG RULE, AND IT IS THE SAME KIND AS THE EFFECT RULE
    # ABOVE (27.08.2026). An op that DOES CREATE, but places a CATALOG
    # ENTRY into the document rather than a BUILDING element — a type,
    # a family, a material, a view — has no discipline of its own, for
    # the same reason `set_param` does not: the entry is CONSUMED by
    # every discipline. A loaded family becomes a door for AR and a
    # fitting for VK; a material gets assigned to both a wall and a
    # duct; a floor plan is read by everyone. This is `shared` ("belongs
    # to everyone"), not an accounting gap.
    #
    # 🔴 THE AUTHORITY LIVES RIGHT HERE — `OPS_WITHOUT_ELEMENTS` (moved
    # here 28.08.2026). Before, the list was maintained at acceptance,
    # and the registry asked for it through a lazy import, that is,
    # from its OWN CONSUMER; the architectural lock was turning red on
    # this, rightfully. A second list of the same names still cannot be
    # set up — it would drift from the first on the very first new op —
    # so the object is ONE, and acceptance is left with just an alias
    # (identity held by `assertIs`, as with the neighboring category
    # table).
    #
    # Its failure mode left along with the import: there is no one left
    # to ask, meaning the "there was no one to ask" branch is no longer
    # here either — not because it was silenced, but because its
    # subject disappeared.
    if ospec.name in OPS_WITHOUT_ELEMENTS:
        return ("shared",), ""
    table = _category_disciplines()
    cats = op_census_categories(ospec)
    if not cats:
        return (), "судья приёмки не знает категории результата"
    known = {table[c] for c in cats if c in table}
    if not known:
        return (), ("категории " + ", ".join(cats)
                    + " не значатся ни у одного носителя словаря разделов")
    if "shared" in known:
        return ("shared",), ""
    return tuple(sorted(known)), ""


def ops_by_discipline(*, writes: bool | None = None
                      ) -> list[tuple[str, list[str]]]:
    """Op names grouped BY PROJECT DISCIPLINE.

    ONE grouping for two readers — exactly the same reason
    `ops_by_object_kind` lives here: the tool description prints it
    into the PROMPT (`tool_doc`), `course.spec()` prints it into the
    RECEIPT on request, and two copies would drift apart silently on
    the very first new op.

    WHY THIS IS BETTER THAN THE `capability` GROUPING THAT STOOD HERE
    BEFORE 09.08. That one printed an internal registry field:
    `element`, `element/mep_system`, `category/element: create_column,
    create_wall`, `room_space`. The author cannot use this — nothing in
    the text explains why `create_wall` is separated from
    `create_floor`, and the answer was that a compiler field had leaked
    onto the surface. WORK IS ORGANIZED BY DISCIPLINE, each with its
    own practitioner; regrouping the same names costs ZERO characters.

    An op with two disciplines (a column — AR and KR) is placed in
    BOTH: an author working in the KR discipline looks for what they
    can build, and the column's absence from their list is a loss, not
    a saving. The sum of the group lengths is therefore larger than the
    number of ops.

    Ops for which a discipline COULD NOT be derived do not land here at
    all — `ops_without_discipline()` returns them, and they must be
    printed under a separate heading. Mixing them with `shared` would
    be a lie (see `op_disciplines`).
    """
    groups: dict[str, list[str]] = {}
    for name, op in sorted(OPS.items()):
        if writes is not None and op.writes_model is not writes:
            continue
        for discipline in op_disciplines(op)[0]:
            groups.setdefault(discipline, []).append(name)
    return [(d, groups[d]) for d in DISCIPLINE_ORDER if d in groups]


def ops_without_discipline(*, writes: bool | None = None
                           ) -> list[tuple[str, str]]:
    """Ops for which a discipline cannot be derived — with a REASON for
    each.

    The counterpart to `ops_by_discipline`: together they cover the
    registry without remainder, and this is held by a test. An
    accounting gap named out loud gets closed; a gap dumped into
    `shared` lives forever and looks like a fact.
    """
    rows: list[tuple[str, str]] = []
    for name, op in sorted(OPS.items()):
        if writes is not None and op.writes_model is not writes:
            continue
        disciplines, why = op_disciplines(op)
        if not disciplines:
            rows.append((name, why))
    return rows


def export_capability_cells() -> list[dict]:
    """The cube s covered-by-IR feed (SPEC §3 / arbitration Q5)."""
    cells = []
    for op in OPS.values():
        for action, object_kind in op.capability:
            cells.append({
                "action": action,
                "object_kind": object_kind,
                "status": "covered-by-IR",
                "ir_op": op.name,
                "ir_version": IR_VERSION,
            })
    for action, route in ROUTE_ONLY_ACTIONS.items():
        cells.append({"action": action, "object_kind": "*",
                      "status": "route-only", "route": route})
    return cells
