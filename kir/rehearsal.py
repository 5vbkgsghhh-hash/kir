"""PROGRAM REHEARSAL: what WILL be checked, and what will NOT — before a
single run.

    PYTHONPATH=. venv/bin/python kir/kir_plan.py program.json
    PYTHONPATH=. venv/bin/python kir/kir_plan.py program.json --json

WHY, FROM A MEASUREMENT OF 18–19.08.2026 ON A LIVE BENCHMARK. One model
worked a shift on KIR in live Revit 2023 and built a terraced office
tower. Two of the three major failures are NOT geometry errors, but
obligations that DID NOT RUN, and silence about it:

    420 columns ended up at 2500 mm instead of 3600–4500. The
    `create_column` obligation «top constraint == resolved top_level» is
    CONDITIONAL: it is required ONLY IF the author passed `top_level`.
    The author omitted it — the witness stayed silent, acceptance passed
    it, three audits did not see it.

    540 out of 540 beams ended up at z=0 while «Этаж 5» was written down.
    The `create_beam` obligation reads, word for word: «опорный уровень
    СУЩЕСТВУЕТ; КАКОЙ — читается в свидетель» [the supporting level
    EXISTS; WHICH ONE is read from the witness]. That is, equality with
    the `level` argument is NEVER checked, and this has been recorded in
    the registry since 27.07 — in prose that the model does not read.

Both classes are DERIVABLE BEFORE the run from what is already lying in
the tree in machine-readable form: `translation_cert.REFINEMENT` (67
operations with obligations, each with an axis kind and a gate field) and
`translation_cert._NON_WITNESSABLE_CLAUSES` (14 operations with NAMED
absences of a witness and a reason for each). The instrument invents
nothing — it GLUES TOGETHER and prints what already exists, but sits where
the program's author does not look.

WHAT THIS INSTRUMENT DOES NOT DO, AND THIS IS NAMED, NOT FORGOTTEN:

  * it does NOT go into Revit and builds nothing. Not one run, not one
    write;
  * it does NOT check whether the geometry is correct. It answers "what
    will be checked", not "will the building come out right";
  * it does NOT see what Revit will silently overwrite. The
    `create_beam.level` case is caught because the obligation ITSELF
    admits its own incompleteness; a field that Revit ignores WITHOUT
    such an admission is invisible to the instrument. That is closed by
    declaring `authority` on the registry parameter, not here;
  * a gate field is looked up in the operation's body BY NAME. A value
    arriving from the `defaults` envelope is taken into account by the
    instrument; a value computed by a macro after expansion is not, and
    such operations are marked separately.

THE THREE REASONS FOR SILENCE ARE KEPT DISTINCT, because one word for
three different troubles is not a measurement. `ВОРОТА` is fixed by the
author with one line; `НАЗВАНО` is a project decision with a reason;
`ОСИ НЕТ` is a hole in the language, and it must be seen apart from the
first two.

WHERE EACH THING LIVES (19.08): the parsing lives HERE, in `kir/`.
`kir/kir_plan.py` is a thin printer on top of it, `serving.py` is the
tool's response. The showroom used to call the parsing from `tools/`,
i.e. AGAINST the tree's dependency direction (`tools/` → `kukai/`,
38 files). The fork refused to copy the logic as a second carrier — and
it was right: a second carrier of the same value is exactly the defect
that this very parsing exposes to the registry.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

from kir import spec, translation_cert as tc

#: ALL KINDS OF CORRECTNESS, NOT THREE. The first version counted the
#: absence of a geometry/semantic/topology obligation as a hole and
#: printed `set_param: geometry,semantic,topology` — that is, it declared
#: as a hole an operation that IS FULLY witnessed, only on the
#: `parameter` axis. The instrument lied to its own author in exactly the
#: form this whole package was written against: a zero for a quantity it
#: had not computed here. Recomputing across all five kinds gave ZERO
#: operations with no witness at all, and 12 with only one axis.
AXES = ("geometry", "semantic", "topology", "parameter", "identity")
#: The `materialize` kind is "did it get created at all", not an axis of correctness.
NOT_AN_AXIS = ("materialize",)


def _ops_of(program: dict) -> list[tuple[dict, int, int]]:
    """Envelope operations with TWO multiplicities: of ELEMENTS and of
    OBLIGATIONS.

    🔴 GROUPS ARE BYPASSED, AND THIS IS NOT A REFINEMENT. A measurement of
    19.08 on a real hand-built benchmark program (`t2_base.json`): 110
    top-level operations, and inside `create_group.members` —
    `create_column ×4` and `create_beam ×8`, which expand into **372
    placements**. The entire building frame lives there, and the first
    version of this instrument counted zero frame — that is, it was blind
    exactly where BOTH defects sat that it was written to catch.

    Macros (`stack`/`series`/`grid_array`) are NOT expanded: the compiler
    expands them BEFORE validation, and before expansion their fields do
    not belong to the instrument. They are printed as a separate row,
    rather than silently skipped.

    🔴 AND THE GROUP OP ITSELF IS COUNTED AS ONE ELEMENT, AND THAT IS
    MEASURED, NOT FORGOTTEN (30.08.2026). In the document, `create_group`
    is followed by `1 + len(placements)` GROUP INSTANCES — so says the
    emitter itself (`authoring.py`: «``__gt_<s>.Groups`` … == 1
    (definition) + placements»), while the row `out.append((item, 1))`
    below counts the op as ONE element.

    A COVERAGE MEASUREMENT ON THE REAL CORPUS (`group.index.json`; 93
    directories, an index exists for 67 = 15 raw + 52 COMPRESSED `.gz` —
    taking only `*/group.index.json` would cut off 52 decompiles by
    construction, `E-59`; distinct buildings by content fingerprint — 11,
    the remaining directories are versions of the same models):

        buildings the undercount touches                  7 of 11
        top-level group instances                          8230
        group types with more than one instance          649 of 1318
        UNDERCOUNTED group elements                        6912

    (nested groups — 1433 instances — are DELIBERATELY excluded from the
    count: in the language a nested group is a MEMBER of another group,
    not its placement.)

    🔴 AND YET ONE LINE DOES NOT FIX THIS. The number `mult` here does TWO
    jobs at once: it is both the ELEMENT COUNT (`elements_total`) and the
    OBLIGATION MULTIPLIER (`will_check`). For every other operation both
    jobs give the same number; for `create_group` they DIVERGE. Run on a
    group with one member and 35 offsets:

        report key                          now      naive fix
        elements_total                       37          72
        counts[create_group]                  1          36
        will_check[create_group·geometry]     1          36   <- CORRUPTION
        will_check[create_group·semantic]     2          72   <- CORRUPTION

    The corruption is a genuine corruption, not "a different number": the
    group's obligations are ALREADY quantified over placements BY THEIR
    OWN TEXT — «one placed group instance PER PLACEMENT OFFSET» and
    «every member of EVERY PLACEMENT stands where the definition member
    stands plus THAT PLACEMENT's delta» — while «GroupType Name matches
    name when given» applies to ONE GroupType and is never checked thirty-
    six times.

    And it is not only the printout for the human that gets corrupted.
    `will_check` is read by the HUMAN (`kir_plan.py:80`), while
    `optional_unused` goes to the MODEL (`serving.py:2807`, the sum of
    `obligations`). For a group WITHOUT a `name`, that same obligation
    becomes conditional-unmet, and the naive fix prints it 36 times
    instead of once: the sum the model sees goes 73 -> 108. That is, the
    naive fix would have repaired `elements_total` and corrupted BOTH of
    the instrument's outputs — for the human and for the model alike.

    ✅ FIXED ON 31.08.2026 EXACTLY THIS WAY: the two jobs are SEPARATED,
    and this is not a new design, but the NAMING of an already-existing
    conflation. The tuple became a triple `(op, elements, obligations)`;
    for every operation except the group both numbers are equal, so no
    other output of the instrument moved. For `create_group`, elements is
    `1 + len(placements)`, obligations is ONE set — their text is already
    quantified over placements BY ITS OWN WORDING, and multiplying it
    would mean quantifying twice.

        report key                        before   after   kind
        elements_total                       37      72   FIXED
        counts[create_group]                  1      36   FIXED
        will_check[create_group·geometry]     1       1   UNCHANGED
        will_check[create_group·semantic]     2       2   UNCHANGED
        optional_unused obligations sum      73      73   UNCHANGED

    The guard against a WRONG fix stays green and remains needed:
    `test_the_group_op_multiplicity_does_two_jobs` pins the invariant
    "the group's obligations do not scale with placements", not the
    element count, and so it did not forbid the correct fix.
    """
    out: list[tuple[dict, int, int]] = []
    for item in program.get("ops") or ():
        if not isinstance(item, dict):
            continue
        members = item.get("members")
        places = item.get("placements")
        # 🔴 ELEMENTS AND OBLIGATIONS DIVERGE ONLY HERE. In the document,
        # `create_group` is followed by `1 + len(placements)` instances,
        # while the GroupType has ONE set of obligations.
        n = 1 + len(places) if isinstance(places, list) else 1
        out.append((item, n if isinstance(members, list) else 1, 1))
        if not isinstance(members, list):
            continue
    # THE MEMBER'S MULTIPLICITY = 1 + len(placements), AND THIS IS NOT
    # ROUNDING. `create_group` materializes OCCURRENCE 0 — the members
    # themselves — and ON TOP of it one occurrence per offset. All three
    # authorities of the tree say so, not just one:
    #   * the emitter: `authoring.py`, `want_instances = 1 + len(placements)`;
    #   * the parameter's kind: `authoring_validation.py`, «occurrence 0
    #     is the members themselves, so an EMPTY list is legal»;
    #   * a measurement of 18.08: a template member ON TOP OF the
    #     placements, 59 duplicates per building.
    #
    # 🔴 BEFORE 30.08.2026 THIS USED TO SAY `len(places)` (an audit
    # finding, F-354). An empty list was counted CORRECTLY — as one — but
    # a non-empty one lost the template occurrence: seven members with
    # eleven offsets gave 77 instead of 84. The instrument was
    # undercounting EXACTLY the quantity it was written for, and
    # undercounting plausibly — by one per member, i.e. invisible to the
    # eye. Scope of the finding: 11 buildings, 1247 groups, 70 066
    # undercounted occurrences.
        for m in members:
            if isinstance(m, dict) and m.get("op"):
                # For a MEMBER both jobs give the same number: each
                # placement carries its own instance of the member, and
                # its own obligation.
                out.append((m, n, n))
    return out


def _present(op: dict, field: str | None, defaults: dict) -> bool:
    """Whether THIS operation has a value for the field — its own, or from the `defaults` envelope."""
    if not field:
        return False
    if op.get(field) is not None:
        return True
    scoped = defaults.get(op.get("op")) if isinstance(defaults, dict) else None
    if isinstance(scoped, dict) and scoped.get(field) is not None:
        return True
    return isinstance(defaults, dict) and defaults.get(field) is not None


def rehearse(program: dict) -> dict:
    table = tc._ensure_table()
    non_witnessable = tc._NON_WITNESSABLE_CLAUSES
    defaults = program.get("defaults") or {}
    ops = _ops_of(program)

    counts: collections.Counter = collections.Counter()
    for op, elements, _obligations in ops:
        counts[op.get("op")] += elements
    will: collections.Counter = collections.Counter()
    # TWO BUCKETS, NOT ONE. Omitting `arc` on a straight wall and omitting
    # `top_level` used to print identically, and the real signal drowned
    # in the noise of decorations. The distinguishing factor is the
    # declared field `ParamSpec.omission_transfers` — non-empty means
    # "power silently passes to another mechanism," and such a row goes
    # out LOUDLY.
    loud: dict[tuple[str, str, str, str], int] = collections.defaultdict(int)
    quiet: dict[tuple[str, str], int] = collections.defaultdict(int)
    derived: dict[tuple[str, str], int] = collections.defaultdict(int)
    unknown_ops: list[str] = []
    macro_ops: list[str] = []

    for op, _elements, mult in ops:
        name = op.get("op")
        if name in ("stack", "series", "grid_array"):
            macro_ops.append(name)
            continue
        op_spec = spec.OPS.get(name)
        ref = table.get(name)
        if ref is None:
            if op_spec is None:
                unknown_ops.append(str(name))
            else:
                unknown_ops.append(f"{name} (нет в REFINEMENT)")
            continue
        # Fields whose value Revit will overwrite: what is sent decides NOTHING.
        for ps in (op_spec.params if op_spec else ()):
            if ps.authority == "DERIVED_BY_REVIT" and _present(op, ps.name, defaults):
                derived[(name, ps.name)] += mult
        for ob in ref.obligations:
            if ob.kind in NOT_AN_AXIS:
                continue
            need = ob.param if ob.conditional else None
            unless = getattr(ob, "unless_param", None)
            # 🔴 TWO MIRROR CASES, AND ONLY ONE OF THEM IS A FINDING.
            # `omission_transfers` describes what takes over the power
            # when a field is OMITTED. For an obligation with
            # `unless_param`, everything is reversed: the field IS
            # PASSED, and the obligation is lifted LEGITIMATELY (for a
            # wall with `top_level`, the height is no longer a number, so
            # there is no point checking it as one). The first version
            # consulted `omission_transfers` in both cases and printed,
            # for a wall WITH the binding, "instead the program decides:
            # the top is given by a number" — a text that is false
            # precisely where everything is correct. The defect was found
            # by a neighboring stage; the same shape we scold the registry
            # for: one field read in two different senses.
            omitted = bool(need and not _present(op, need, defaults))
            passed_unless = bool(unless and _present(op, unless, defaults))
            if omitted:
                off_because = f"пропущено {need}"
            elif passed_unless:
                off_because = f"передано {unless}"
            else:
                will[(name, ob.kind)] += mult
                continue
            transfers = ""
            if omitted:
                for ps in (op_spec.params if op_spec else ()):
                    if ps.name == need:
                        transfers = ps.omission_transfers
                        break
            if transfers:
                loud[(name, ob.clause, off_because, transfers)] += mult
            else:
                quiet[(name, off_because)] += mult

    # OPERATIONS WITNESSED ON EXACTLY ONE AXIS. Not "axis X is missing" —
    # the instrument cannot draw that conclusion: to know whether an
    # operation WRITES along an axis, you must read the emitter, not the
    # obligations table. What the instrument knows for certain is how many
    # axes the operation has under watch; one axis on a writing operation
    # is a lead for investigation, not a verdict.
    thin_axes: dict[str, str] = {}
    for name in counts:
        ref = table.get(name)
        op_s = spec.OPS.get(name)
        if ref is None or op_s is None or not op_s.writes_model:
            continue
        have = {o.kind for o in ref.obligations if o.kind not in NOT_AN_AXIS}
        if len(have) == 1:
            thin_axes[name] = next(iter(have))

    named = {n: non_witnessable[n] for n in counts if n in non_witnessable}
    return {
        "ops_declared": len(ops),
        "elements_total": sum(counts.values()),
        "counts": dict(counts),
        "will_check": {f"{k[0]}·{k[1]}": v for k, v in sorted(will.items())},
        "authority_ignored": [{"op": k[0], "param": k[1], "count": v}
                              for k, v in sorted(derived.items(), key=lambda kv: -kv[1])],
        "authority_transfer": [
            {"op": k[0], "clause": k[1], "because": k[2], "transfers": k[3],
             "count": v}
            for k, v in sorted(loud.items(), key=lambda kv: -kv[1])],
        "optional_unused": [{"op": k[0], "because": k[1], "count": v}
                            for k, v in sorted(quiet.items(), key=lambda kv: -kv[1])],
        "named_absences": {n: [{"clause": c, "why": w} for c, w in v]
                           for n, v in named.items()},
        "thin_axes": thin_axes,
        "macro_ops": sorted(set(macro_ops)),
        "unwitnessed_ops": sorted(set(unknown_ops)),
    }


