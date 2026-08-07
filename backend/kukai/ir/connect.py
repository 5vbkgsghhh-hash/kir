"""KIR CONNECT — network-connectivity sublanguage (v2 invention, 2026-07-17).

THE PINNED DECISIONS (Sonnet waves tile ВК/ОВ/ЭОМ chains on these; see
KIR_CONNECT_SPEC.md). A network is a GRAPH — nodes + segment-edges — and
connectivity is an INVARIANT, not an afterthought: the compiler emits segments,
regenerates, then joins connectors and infers a JUNCTION KIND at each node
from its graph degree AND (at degree 2) the local geometry — exactly the way
v1 infers units.

FIX 2026-07-17 (live-semantic-test diagnosis): a degree-2 node used to always
get `NewElbowFitting`, even on a straight collinear run (angle ~=180 deg,
where physically the two segments just continue in the same line — a real
Revit riser+branch or a straight coupling, not a bend) and even where the
declared diameter changes across an otherwise-straight joint (needs a
reducer, not an elbow). `NewElbowFitting` legitimately throws
"failed to insert elbow" when asked to bend two connectors that are already
antiparallel/collinear — that's not a routing-preferences gap, it's asking
Revit to elbow a straight line. See KIR_CONNECT_SPEC.md §2 ("переход диаметра
на прямом стыке -> NewTransitionFitting") and the wiki
(data/wiki/pages/mep/duct-routing.md: "Отвод ставится только на повороте (два
неколлинеарных отрезка)"; fittings-and-connectors.md's verified "ConnectTo vs
NewTransitionFitting" recipe: SAME size/shape at a straight coaxial joint ->
`Connector.ConnectTo` directly, no fitting *element* at all — Revit has no
"union fitting" factory; NewUnionFitting does not exist in the Revit API).
`classify_junction` below is the pure (Python-testable, no C#/Revit needed)
decision function; `emit_fittings_cs` only turns its verdict into code.
Degree >= 3 is UNCONDITIONALLY a tee regardless of any pairwise collinearity
among its incident segments (the existing TEE fixture's A/T/B triple is
exactly antiparallel through T, yet T is degree 3 -> tee, never elbow/union —
geometry only disambiguates within degree 2).

This module is domain-agnostic: `graph_validate` and the emit helpers are
shared; a concrete op (create_pipe_system, and later duct/conduit) supplies
only the Create/Fitting API names. All laws that a Revit runtime taught us on
slabs (zero edge, disconnection) are lifted here to the T stage.

FIX 2026-07-17 ROUND 2 (second live re-test, post-fitting-classification-fix):
classify_junction's elbow/tee/transition/connect split made geometry+topology
green, but three NEW failures surfaced on a real multi-segment Revit network:

(A) "segments span multiple systems (semantic)" on the straight-through case.
SUPERSEDED 2026-07-27 BY DIRECT MEASUREMENT ON A LIVE REVIT 2023 — the round-2
fix described here was aimed at the wrong stage and made the ops unbuildable.
What it asserted, and what a live document actually reports:

  claimed: `Pipe.Create(systemTypeId, ...)` leaves the segment with no logical
           system (`MEPCurve.MEPSystem == null`) until something builds one;
  measured: the pipe emitted by our own `create_pipe` came back carrying
           `MEPSystem = «Канализация 1» #21201145`, and BOTH its connectors
           report that same system id while `IsConnected == false`.

  claimed: therefore one `NewPipingSystem` over all free connectors merges them;
  measured: it throws `Some of the input connectors have been used.` — because
           they already belong to the systems Revit auto-created above. All four
           graph ops (create_pipe_system / route_pipe_system / route_duct_system)
           failed live on exactly this, every time.

  claimed: `ConnectTo` never merges MEPSystem membership;
  measured: half true, and the half that matters was missed. Inside the
           transaction (even after `doc.Regenerate()`) the two systems stay
           distinct — that is the symptom round 2 saw. **After `Commit()` Revit
           merges them itself**: two pipes joined by `ConnectTo` and committed
           came back both reporting `#21201856 «Канализация 2»`.

So the logical system is not something the emitter must construct; it is
something Revit DERIVES from the physical connector graph at commit time. The
error was never in the construction, it was in checking a commit-time fact
inside the transaction. Consequently:

  * no `NewPipingSystem`/`NewMechanicalSystem` call is emitted at all;
  * the in-transaction semantic guarantee is the CONNECTIVITY witness
    (`emit_connectivity_witness_cs`, a BFS over the live connector graph) —
    which is the CONNECT signal the spec names, and which really is checkable
    before commit;
  * system identity is READ BACK AFTER the commit
    (`emit_system_readback_cs`) and reported as a fact, never forced.

That last move follows this package's own witness rule: a witness reads the
RESULT. Forcing membership so that an in-txn check passes is the inverse — it
proves the emitter called something, not that the model came out right.

(B) "NewTeeFitting: failed to insert tee" — unchanged from before this round.
Per revitapidocs.com (verified against the 2015 AND 2024 editions of the
NewElbowFitting reference — the Exceptions text is byte-identical across nine
years, so this is real API contract, not a stale artifact) elbow/tee
insertion legitimately throws when a pipe/duct type's routing preferences
have no fitting for the requested size, OR when the connector geometry
itself doesn't fit the fitting family's accepted range (a first-hand
practitioner report — an Autodesk Community "Tee fitting connectors" thread —
documents `NewTeeFitting` failing when the three connectors are off from
exact orthogonality by a fraction of a degree). Neither is a compiler
ordering bug: `doc.Regenerate()` already runs between segment creation and
the fitting calls (unchanged, still correct — verified against this same
ordering in the wiki's own compile-gated "Route MEP"/MEPM-017 recipes, NEITHER
of which has any Regenerate between Xxx.Create and NewElbowFitting/
NewTeeFitting either). What IS a real, fixable emitter gap: `NewTeeFitting`
takes its three connectors in a specific ROLE order (main1, main2, branch —
see the wiki's own MEPM-017 recipe and KIR_CONNECT_SPEC's own TEE fixture,
where the two collinear segments are listed first); the previous code passed
`cvars` in raw graph-edge order (whatever order `segments[]` happened to list
the three edges), which only accidentally matches the required role order
when the collinear pair happens to come first in the IR. `emit_fittings_cs`
now reorders a degree-3 node's three connectors so the two THAT ARE THEMSELVES
mutually most-collinear go first (main1, main2) and the odd one out goes last
(branch), regardless of authoring order — this cannot fix a genuine
routing-preferences gap (that stays a typed, in-txn-rollback refusal, by
design: this compiler's invariant is "build correctly or refuse honestly",
never "build a fragile guess"), but it does remove one real, provable class
of self-inflicted failure. The refusal message on every fitting catch now
also carries the incident angle/diameters, so a live re-test's error text
tells a human "insert failed at this angle/size" instead of a bare Revit
string — still the exact `__exf.Message` Revit itself returns (no invented
diagnosis), just with the geometric context a human would ask for next.

Both round-2 fixes are ADDITIVE to round 1: `classify_junction` and the
elbow/connect/transition branch selection are UNCHANGED (round-1 regression
tests keep passing unmodified).
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kukai.ir.diag import Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS, TYPE_GEOM_RELATION
from kukai.ir.emit_utils import (cs_line_comment_fragment,
                                 is_finite_number, refuse_stmt)
from kukai.ir.numeric_contracts import MODEL_COORD_LIMIT_MM

_EDGE_TOL = 1.0          # mm: shorter segment = runtime ShortCurveTolerance
_MAX_DEGREE = 3          # v2.0: tee is the max junction; 4-way = v2.1
_MIN_DIA, _MAX_DIA = 5.0, 2000.0
# A degree-2 node is COLLINEAR (straight run, not a bend) when the angle
# between its two incident segment directions (as seen FROM the node, i.e.
# node->other-endpoint for each side) is >= this threshold. 180 deg is a
# perfectly straight line; real authored graphs carry rounded mm coordinates,
# so a small tolerance band catches "meant to be straight" without also
# catching a genuine shallow-but-real bend (an actual duct/pipe turn is never
# authored within a few degrees of dead straight — routing elbows are
# discrete catalog angles: 90/45/30/... never ~178-180).
_COLLINEAR_ANGLE_DEG = 175.0
# Same-diameter tolerance for the "no size change" leg of a straight joint
# (mm) — protects against float noise in an authored/derived diameter
# rather than expecting bit-exact equality.
_SAME_DIA_TOL = 0.5


def _angle_deg(node, p_a, p_b) -> float:
    """Angle in degrees between the two rays node->p_a and node->p_b (3D).
    180.0 = perfectly straight (p_a, node, p_b collinear, node between them);
    small values = a sharp turn back on itself; ~90 = a right-angle bend.
    Degenerate (a ray with ~zero length — should not happen post
    graph_validate's _EDGE_TOL check, but this function must never raise on
    its own) returns 180.0 (collinear/no-turn) rather than divide-by-zero,
    since a length that graph_validate already accepted is by definition
    not near-zero for THIS node's edge; the guard is defense in depth only."""
    va = [p_a[k] - node[k] for k in range(3)]
    vb = [p_b[k] - node[k] for k in range(3)]
    la = math.sqrt(sum(c * c for c in va))
    lb = math.sqrt(sum(c * c for c in vb))
    if la < 1e-9 or lb < 1e-9:
        return 180.0
    dot = sum(va[k] * vb[k] for k in range(3)) / (la * lb)
    dot = max(-1.0, min(1.0, dot))  # clamp float noise before acos
    return math.degrees(math.acos(dot))


def classify_junction(degree: int, angle_deg: Optional[float],
                      dia_a: Optional[float], dia_b: Optional[float]) -> str:
    """Pure junction-kind decision (no C#, no Revit — property-testable in
    isolation). Returns one of:
      "elbow"      - degree 2, a genuine bend (angle_deg < _COLLINEAR_ANGLE_DEG)
                     -> NewElbowFitting (unchanged prior behavior for a REAL turn).
      "connect"    - degree 2, collinear, same (or unknown) diameter on both
                     sides -> Connector.ConnectTo directly, no fitting element
                     (a straight run has nothing to elbow; Revit's own
                     verified recipe for "same size, straight, coaxial" is
                     ConnectTo, not a fitting factory call).
      "transition" - degree 2, collinear, KNOWN and DIFFERENT diameters on
                     each side -> NewTransitionFitting (reducer) per
                     KIR_CONNECT_SPEC.md §2.
      "tee"        - degree 3, unconditionally, regardless of angle_deg
                     (matches the existing TEE fixture: an antiparallel pair
                     through a degree-3 node is still a tee, never elbow).
    degree < 2 must never reach here (emit_fittings_cs's own len(vars_here)<2
    skip); degree > 3 is already refused by graph_validate's degree cap, so
    this function only ever sees 2 or 3 — anything else is a caller bug, not
    a silently-guessed answer, hence the explicit ValueError rather than a
    fallback branch."""
    if degree == 3:
        return "tee"
    if degree != 2:
        raise ValueError(f"classify_junction: degree must be 2 or 3 (got {degree}); "
                         f"graph_validate's degree cap should have refused this earlier")
    if angle_deg is not None and angle_deg >= _COLLINEAR_ANGLE_DEG:
        if dia_a is not None and dia_b is not None and abs(dia_a - dia_b) > _SAME_DIA_TOL:
            return "transition"
        return "connect"
    return "elbow"


def _num(x) -> bool:
    return is_finite_number(x)


_COORD_LIMIT_MM = MODEL_COORD_LIMIT_MM


def _pt_ok(v) -> bool:
    return (isinstance(v, list) and len(v) == 3
            and all(_num(c) and abs(c) <= _COORD_LIMIT_MM for c in v))


def _dist3(a, b) -> float:
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(3)))


def graph_validate(op: dict, oid, diags: list, default_dia: Optional[float],
                   diameter_bounds: tuple[float, float] = (_MIN_DIA, _MAX_DIA)) -> Optional[dict]:
    """Static graph laws (SPEC CONNECT §typecheck). Returns
    {"nodes": {id: xyz}, "order": [id...], "edges": [(a,b,dia)],
     "degree": {id: n}} or None with typed diagnostics appended."""
    nodes_raw = op.get("nodes")
    if not isinstance(nodes_raw, list) or not (2 <= len(nodes_raw) <= 64):
        diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid, field_name="nodes",
                                got=nodes_raw, message_ru="nodes — 2..64 узлов"))
        return None
    nodes: dict[str, list] = {}
    order: list[str] = []
    for ni, n in enumerate(nodes_raw):
        if (not isinstance(n, dict)
                or set(n) != {"id", "xyz_mm"}
                or not isinstance(n.get("id"), str)
                or not (1 <= len(n["id"]) <= 64)
                or n["id"] != n["id"].strip()):
            diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid,
                                    field_name=f"nodes[{ni}]", got=n,
                                    message_ru=f"nodes[{ni}] — {{id, xyz_mm}}, "
                                               "id: 1..64 символа без крайних пробелов"))
            return None
        nid = n["id"]
        if nid in nodes:
            diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid,
                                    field_name=f"nodes[{ni}].id", got=nid,
                                    message_ru=f"дубликат узла '{nid}'"))
            return None
        if not _pt_ok(n.get("xyz_mm")):
            diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid,
                                    field_name=f"nodes[{ni}].xyz_mm", got=n.get("xyz_mm"),
                                    message_ru=f"узел '{nid}': xyz_mm — [x,y,z] мм"))
            return None
        nodes[nid] = [float(c) for c in n["xyz_mm"]]
        order.append(nid)

    segs_raw = op.get("segments")
    if not isinstance(segs_raw, list) or not (1 <= len(segs_raw) <= 128):
        diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid, field_name="segments",
                                got=segs_raw, message_ru="segments — 1..128 рёбер"))
        return None
    edges: list[tuple] = []
    seen_edges: set = set()
    degree: dict[str, int] = {nid: 0 for nid in nodes}
    adj: dict[str, list] = {nid: [] for nid in nodes}
    for si, seg in enumerate(segs_raw):
        if not isinstance(seg, dict) or set(seg) - {"from", "to", "diameter_mm"}:
            diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid,
                                    field_name=f"segments[{si}]", got=seg,
                                    message_ru=f"segments[{si}] — {{from, to, diameter_mm?}}"))
            return None
        a, b = seg.get("from"), seg.get("to")
        for end, lbl in ((a, "from"), (b, "to")):
            if not isinstance(end, str):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_id=oid,
                    field_name=f"segments[{si}].{lbl}", got=end,
                    expected="string node id",
                    message_ru=f"segments[{si}].{lbl} — строковый id узла"))
                return None
            if end not in nodes:
                diags.append(Diagnostic(
                    code="KIR-L003", op_id=oid, field_name=f"segments[{si}].{lbl}",
                    got=end, candidates=order,
                    message_ru=f"segments[{si}].{lbl} '{end}' — не объявленный узел"))
                return None
        if a == b:
            diags.append(Diagnostic(code=TYPE_GEOM_RELATION, op_id=oid,
                                    field_name=f"segments[{si}]", got=a,
                                    message_ru=f"segments[{si}]: петля (from==to)"))
            return None
        key = frozenset((a, b))
        if key in seen_edges:
            diags.append(Diagnostic(code=TYPE_GEOM_RELATION, op_id=oid,
                                    field_name=f"segments[{si}]",
                                    message_ru=f"segments[{si}]: дубликат ребра {a}-{b}"))
            return None
        seen_edges.add(key)
        if _dist3(nodes[a], nodes[b]) < _EDGE_TOL:
            diags.append(Diagnostic(code=TYPE_BOUNDS, op_id=oid,
                                    field_name=f"segments[{si}]",
                                    message_ru=f"segments[{si}]: нулевая длина (узлы совпали) — "
                                               f"в рантайме ShortCurveTolerance, ловим статически"))
            return None
        dia = seg.get("diameter_mm", default_dia)
        if dia is not None:
            min_dia, max_dia = diameter_bounds
            if not _num(dia) or not (min_dia <= dia <= max_dia):
                diags.append(Diagnostic(code=TYPE_BOUNDS, op_id=oid,
                                        field_name=f"segments[{si}].diameter_mm", got=dia,
                                        expected=f"{min_dia}..{max_dia}",
                                        message_ru=f"segments[{si}]: диаметр вне диапазона"))
                return None
            dia = float(dia)
        edges.append((a, b, dia))
        degree[a] += 1
        degree[b] += 1
        adj[a].append(b)
        adj[b].append(a)

    # degree cap (v2.0)
    for nid, deg in degree.items():
        if deg > _MAX_DEGREE:
            diags.append(Diagnostic(code=TYPE_GEOM_RELATION, op_id=oid,
                                    field_name="segments", got={nid: deg},
                                    message_ru=f"узел '{nid}': степень {deg} > {_MAX_DEGREE} "
                                               f"(крестовина — CONNECT v2.1)"))
            return None
    # connectivity: BFS from the first node reaches ALL nodes (no dangling)
    reached = {order[0]}
    frontier = [order[0]]
    while frontier:
        cur = frontier.pop()
        for nb in adj[cur]:
            if nb not in reached:
                reached.add(nb)
                frontier.append(nb)
    if len(reached) != len(nodes):
        orphans = [nid for nid in order if nid not in reached]
        diags.append(Diagnostic(code=TYPE_GEOM_RELATION, op_id=oid, field_name="segments",
                                got=orphans,
                                message_ru=f"несвязная сеть: узлы {orphans} недостижимы от '{order[0]}'"))
        return None
    return {"nodes": nodes, "order": order, "edges": edges, "degree": degree, "adj": adj}


# ── emit helpers (the template Sonnet clones; domain = the *_API names) ──────

def emit_segments_cs(graph: dict, seg_var, create_call, sys_var: str,
                     type_var: str, lvl_var: str, cs_pt, cs_str,
                     isolation: str = "atomic") -> tuple[str, list]:
    """Segment creation lines + list of (var, a, b, dia) for the witness/fitting
    stages. create_call(sys, type, lvl, p0cs, p1cs) -> the domain Create() C#."""
    lines = []
    seg_meta = []
    for i, (a, b, dia) in enumerate(graph["edges"]):
        var = f"{seg_var}_{i}"
        pa, pb = graph["nodes"][a], graph["nodes"][b]
        lines.append(f"var {var} = {create_call(sys_var, type_var, lvl_var, cs_pt(pa), cs_pt(pb))};")
        lines.append(f"if ({var} == null) {{ {refuse_stmt('seg-' + str(i), cs_str('создание сегмента вернуло null'), isolation)} }}")
        if dia is not None:
            lines.append(f"try {{ var __d{i} = {var}.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM); "
                         f"if (__d{i} != null && !__d{i}.IsReadOnly) __d{i}.Set(U({dia})); }} catch {{ }}")
        seg_meta.append((var, a, b, dia))
    return "\n".join(lines), seg_meta


def emit_system_readback_cs(seg_meta: list, oid, cs_str, results_var: str) -> str:
    """POST-COMMIT readback of the logical MEPSystem every segment ended up in.

    Replaces the round-2 `emit_system_merge_cs`, which called
    `doc.Create.NewPipingSystem`/`NewMechanicalSystem` INSIDE the transaction
    and made all four graph ops unbuildable — live Revit 2023 answered
    `Some of the input connectors have been used.` every single time, because
    `Pipe.Create(systemTypeId, ...)` has ALREADY put both connectors in an
    auto-created system (measured: `MEPSystem = «Канализация 1» #21201145`
    with `IsConnected == false`). See §A of the module docstring for the three
    measured facts that supersede the round-2 reasoning.

    Nothing is constructed here. Revit derives system membership from the
    physical connector graph at Commit, so this fragment runs AFTER the
    transaction and simply records what the document now says:

        segments        — how many segments the op created
        mep_system_ids  — the distinct MEPSystem ids they ended up in
        one_system      — whether that set has exactly one member

    A missing/plural system is reported, not forced: the in-transaction
    semantic guarantee is `emit_connectivity_witness_cs` (a BFS over the live
    connector graph — the CONNECT signal the spec actually names, and the one
    thing that IS knowable before commit)."""
    if len(seg_meta) < 1:
        return ""
    all_vars = ", ".join(v for v, _a, _b, _d in seg_meta)
    return "\n".join((
        f"// mep-system readback {cs_line_comment_fragment(oid)}: membership is "
        f"DERIVED by Revit at commit — read, never constructed (connect.py §A)",
        "{",
        "    var __sysIds = new List<string>();",
        f"    foreach (var __sg in new MEPCurve[] {{ {all_vars} }}) {{",
        "        if (__sg == null) continue;",
        "        try { var __ms = __sg.MEPSystem;",
        "               if (__ms != null && !__sysIds.Contains(__ms.Id.ToString()))",
        "                   __sysIds.Add(__ms.Id.ToString()); } catch { }",
        "    }",
        f"    var __sysRb = {results_var}[{cs_str(oid)}] as Dictionary<string, object>;",
        "    if (__sysRb != null) {",
        "        __sysRb[\"mep_system_ids\"] = __sysIds.ToArray();",
        f"        __sysRb[\"one_system\"] = (__sysIds.Count == 1);",
        "    }",
        "}",
    ))


def _dia_fmt(dia: Optional[float]) -> str:
    """Diameter for a refusal message: "?" for an undeclared diameter rather
    than Python's bare "None" leaking into a Russian-language error string."""
    return "?" if dia is None else str(round(dia, 1))


def _reorder_tee_mains_first(vars_here: list, xyz, nodes: dict) -> list:
    """FIX (round 2, §B): NewTeeFitting takes its three connectors in a
    specific ROLE order — (main1, main2, branch), per the wiki's own MEPM-017
    recipe and KIR_CONNECT_SPEC's TEE fixture, both of which list the
    mutually-collinear pair first. The previous code passed `vars_here` in
    raw graph-edge order (whatever order segments[] happened to declare the
    three edges), which only accidentally matched the required role order
    when the IR's authoring order happened to put the collinear pair first.
    This picks the pair of the three incident rays that is MOST mutually
    collinear (largest pairwise angle — closest to a straight main run) and
    returns [main1, main2, branch] regardless of authoring order. Does not
    change classify_junction's own tee-vs-elbow verdict (degree==3 is always
    "tee", unconditionally, per the module docstring) — this only fixes the
    ARGUMENT ORDER handed to NewTeeFitting once "tee" is already decided.

    vars_here entries are (var, other_NODE_ID, dia) — other_node_id is a
    string key into `nodes`, NOT a coordinate; _angle_deg needs the actual
    xyz_mm point, so this resolves each entry's other-node id through
    `nodes` before computing pairwise angles (a plain tuple-unpack of
    vars_here's raw entries into _angle_deg would TypeError on a string
    minus a float — caught by this module's own compile-gate tests)."""
    (v0, oid0, _d0), (v1, oid1, _d1), (v2, oid2, _d2) = vars_here
    others_xyz = (nodes[oid0], nodes[oid1], nodes[oid2])
    pairs = [(0, 1, 2), (0, 2, 1), (1, 2, 0)]
    best_pair, best_angle = pairs[0], -1.0
    for ia, ib, ic in pairs:
        ang = _angle_deg(xyz, others_xyz[ia], others_xyz[ib])
        if ang > best_angle:
            best_angle, best_pair = ang, (ia, ib, ic)
    ia, ib, ic = best_pair
    ordered = (vars_here[ia], vars_here[ib], vars_here[ic])
    return list(ordered)


def emit_fittings_cs(graph: dict, seg_meta: list, oid, cs_pt, cs_str,
                     isolation: str = "atomic") -> str:
    """At each node of degree>=2, connect the segment ends meeting there. The
    JUNCTION KIND (elbow / straight connect / transition / tee) is decided by
    `classify_junction` (degree + local angle + diameters), NOT hardcoded to
    elbow-or-tee by cardinality alone — see the module docstring for the
    live-semantic-test bug this fixes (elbow on a collinear straight run or
    a tee's own antiparallel pair used to throw "failed to insert elbow").
    Connectors are found by proximity to the node (a compile-time-known
    point). APIs (doc.Create.NewElbow/NewTee/NewTransitionFitting,
    Connector.ConnectTo) are stable 2021-2026 (verified against the
    compile-gated wiki recipes in data/wiki/pages/mep/).

    ROUND 2 (§B of the module docstring): a degree-3 node's three incident
    vars are now reordered (main1, main2, branch) by mutual collinearity
    before NewTeeFitting is called — see _reorder_tee_mains_first — and
    every fitting catch's refusal message now carries the incident
    angle/diameters, so a real Revit failure ("failed to insert
    elbow/tee" — a routing-preferences/geometry gap this compiler cannot
    fabricate a fitting around, per the module docstring's honesty
    invariant) reports WHERE it failed geometrically, not just Revit's own
    bare exception text."""
    # map node -> list of (var, other_node_id, dia) for each segment incident
    # to it (other_node_id/dia needed for classify_junction's angle+diameter
    # inputs; degree-2's two entries give the two rays FROM this node).
    incident: dict[str, list] = {nid: [] for nid in graph["nodes"]}
    for var, a, b, dia in seg_meta:
        incident[a].append((var, b, dia))
        incident[b].append((var, a, dia))
    lines = [
        "// fittings: connect segment ends by proximity to each junction node",
        "Func<Element, XYZ, Connector> __nearestFree = (Element __el, XYZ __p) =>",
        "{",
        "    ConnectorManager __cm = (__el is MEPCurve) ? ((MEPCurve)__el).ConnectorManager : null;",
        "    if (__cm == null) return null;",
        "    Connector __best = null; double __bd = double.MaxValue;",
        "    foreach (Connector __c in __cm.Connectors) {",
        "        if (__c.IsConnected) continue;",
        "        double __dd = __c.Origin.DistanceTo(__p);",
        "        if (__dd < __bd) { __bd = __dd; __best = __c; }",
        "    }",
        "    return __best;",
        "};",
    ]
    fitting_count = 0
    for nid, xyz in graph["nodes"].items():
        vars_here = incident[nid]
        degree = len(vars_here)
        if degree < 2:
            continue
        junction_index = fitting_count
        fitting_count += 1

        if degree == 3:
            kind = classify_junction(3, None, None, None)   # always "tee"
            # FIX round 2 §B: order (main1, main2, branch) by mutual
            # collinearity, not raw graph-edge/authoring order (see
            # _reorder_tee_mains_first docstring).
            vars_here = _reorder_tee_mains_first(vars_here, xyz, graph["nodes"])
            (_v0, other0, dia0), (_v1, other1, dia1), (_v2, other2, dia2) = vars_here
            angle = _angle_deg(xyz, graph["nodes"][other0], graph["nodes"][other1])
            dia_ctx = f"main {_dia_fmt(dia0)}/{_dia_fmt(dia1)}mm, branch {_dia_fmt(dia2)}mm"
        else:
            (_v0, other0, dia0), (_v1, other1, dia1) = vars_here
            angle = _angle_deg(xyz, graph["nodes"][other0], graph["nodes"][other1])
            kind = classify_junction(2, angle, dia0, dia1)
            dia_ctx = f"{_dia_fmt(dia0)}/{_dia_fmt(dia1)}mm"

        p = cs_pt(xyz)
        cvars = []
        for j, (sv, _other, _dia) in enumerate(vars_here):
            # Node ids are user data. They may contain punctuation or Unicode,
            # so they must never become part of a C# identifier. The stable
            # graph-order index is sufficient for local uniqueness.
            cvar = f"__cn_{junction_index}_{j}"
            lines.append(f"var {cvar} = __nearestFree({sv}, {p});")
            cvars.append(cvar)
        guard = " || ".join(f"{c} == null" for c in cvars)
        lines.append(f"if ({guard}) {{ {refuse_stmt(oid + ':' + nid, cs_str('нет свободного коннектора для фитинга'), isolation)} }}")

        # ROUND 2 §B: every fitting refusal now carries the incident
        # angle/diameters ALONGSIDE Revit's own __exf.Message (never
        # instead of it — the honesty invariant is "report what Revit said",
        # this only adds the geometric context a human reading the refusal
        # would ask for next: is this a routing-preferences gap at this
        # size, or a geometry/alignment gap at this angle).
        ctx = f" (angle={round(angle, 1)}deg, {dia_ctx})"
        if kind == "tee":
            lines.append(f"try {{ doc.Create.NewTeeFitting({cvars[0]}, {cvars[1]}, {cvars[2]}); }}")
            lines.append(f"catch (Exception __exf) {{ {refuse_stmt(oid + ':' + nid, f'\"NewTeeFitting: \" + __exf.Message + {cs_str(ctx)}', isolation)} }}")
        elif kind == "elbow":
            lines.append(f"try {{ doc.Create.NewElbowFitting({cvars[0]}, {cvars[1]}); }}")
            lines.append(f"catch (Exception __exf) {{ {refuse_stmt(oid + ':' + nid, f'\"NewElbowFitting: \" + __exf.Message + {cs_str(ctx)}', isolation)} }}")
        elif kind == "transition":
            lines.append(f"try {{ doc.Create.NewTransitionFitting({cvars[0]}, {cvars[1]}); }}")
            lines.append(f"catch (Exception __exf) {{ {refuse_stmt(oid + ':' + nid, f'\"NewTransitionFitting: \" + __exf.Message + {cs_str(ctx)}', isolation)} }}")
        else:  # "connect" — straight run, same/unknown diameter: no fitting
               # element at all, just join the two End connectors directly
               # (Revit has no "union fitting" factory — see module docstring).
            lines.append(f"try {{ {cvars[0]}.ConnectTo({cvars[1]}); }}")
            lines.append(f"catch (Exception __exf) {{ {refuse_stmt(oid + ':' + nid, f'\"ConnectTo: \" + __exf.Message + {cs_str(ctx)}', isolation)} }}")
    return "\n".join(lines)


def emit_connectivity_witness_cs(seg_meta: list, oid, cs_str) -> str:
    """topology_ok: BFS the live Connector graph from segment 0, count reached
    segments == N. This is the REAL connectivity (§witness), not the declared."""
    n = len(seg_meta)
    arr = ", ".join(v for v, _, _, _ in seg_meta)
    return (
        f"// connectivity witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __segs = new Element[] {{ {arr} }};\n"
        f"    var __ids = new HashSet<string>();\n"
        f"    foreach (var __e in __segs) __ids.Add(__e.Id.ToString());\n"
        f"    var __seen = new HashSet<string>();\n"
        # A List used as a stack, NOT Stack<T>. On .NET Framework 4.8
        # System.Collections.Generic.Stack<T> is declared in System.dll, which
        # is absent from the reference closure on part of the fleet — the same
        # CS1069 "forwarded to assembly 'System'" that killed Regex and
        # Stopwatch on 2026-08-04. List<T> is mscorlib and binds everywhere.
        # See tests/bridge_reference_closure.py (`deployed` profile).
        f"    var __stack = new List<Element>();\n"
        f"    __stack.Add(__segs[0]); __seen.Add(__segs[0].Id.ToString());\n"
        f"    while (__stack.Count > 0) {{\n"
        f"        var __cur = __stack[__stack.Count - 1];\n"
        f"        __stack.RemoveAt(__stack.Count - 1);\n"
        f"        ConnectorManager __cm = null;\n"
        f"        try {{ if (__cur is MEPCurve) __cm = ((MEPCurve)__cur).ConnectorManager;\n"
        f"               else if (__cur is FamilyInstance) __cm = ((FamilyInstance)__cur).MEPModel.ConnectorManager; }} catch {{ }}\n"
        f"        if (__cm == null) continue;\n"
        f"        foreach (Connector __c in __cm.Connectors) {{\n"
        f"            foreach (Connector __r in __c.AllRefs) {{\n"
        f"                var __owner = __r.Owner;\n"
        f"                if (__owner == null) continue;\n"
        f"                var __k = __owner.Id.ToString();\n"
        f"                if (!__seen.Contains(__k)) {{ __seen.Add(__k);\n"
        f"                    if (__ids.Contains(__k)) __stack.Add(__owner);\n"
        f"                    else __stack.Add(__owner); }}\n"
        f"            }}\n"
        f"        }}\n"
        f"    }}\n"
        f"    int __reachedSegs = 0;\n"
        f"    foreach (var __e in __segs) if (__seen.Contains(__e.Id.ToString())) __reachedSegs++;\n"
        f"    if (__reachedSegs < {n})\n"
        f"        __post.Add({cs_str(oid + ': network not fully connected (topology)')});\n"
        f"}}")
