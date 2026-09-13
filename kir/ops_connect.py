"""ops_connect — CONNECT sublanguage (network-graph systems).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

wave/mep (2026-07-17): route_pipe_system / route_duct_system tile the PROVEN
create_pipe_system graph pattern (KIR_CONNECT_SPEC.md — connectivity by
construction, fittings inferred from node degree) onto the full domestic-water/HVAC op
family. NOTE ON PLACEMENT (flagged): the wave brief said edit only
ops_mep.py, but these are network-SYSTEM ops (nodes+segments+one MEPSystem),
and REGISTRY_MODULES.md's own ops_mep.py entry is explicit that "SYSTEMS
go in ops_connect" — the same rule create_pipe_system already follows.
Filed here, not in ops_mep.py, to keep the module contract self-consistent;
called out again in the wave report so Fable can arbitrate if the file
split was intentional elsewhere.

SLOPE (flagged spec gap): the pinned graph model (SPEC §1) is nodes carrying
full xyz_mm — a node's Z already IS its elevation. A generative "slope_pct"
param that DERIVES Z from run length would be a second source of truth for
the same geometry — exactly the invented-graph-semantics class this wave was
told to avoid. Both route_* ops instead accept an optional per-segment
`slope_min_pct` (inside a segments[] entry) as a CHECKED postcondition: the
witness computes actual rise/run*100 from the two node elevations and
refuses (KIR-X004, in-txn rollback) if under the floor. Verifiable, not
generative — consistent with CONNECT's own geometry_ok philosophy ("real,
not declared"). KIR_CONNECT_SPEC.md's buildable model doesn't mention slope
at all (only my task brief + the superseded KIR_CONNECT_DRAFT.md do); this
is a genuine spec gap, not a pinned decision — flagged for Fable rather than
silently skipped OR silently invented as a Z-generator.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

OPS = [
    OpSpec(
            name="create_pipe_system",
            effect=EffectKind.CREATE,
            result=RESULT_NETWORK_SEGMENTS,
            family="authoring",
            params=(
                ParamSpec("nodes", "graph_nodes", required=True),
                ParamSpec("segments", "graph_segments", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("pipe_type", "sel"),
                ParamSpec("diameter_mm", "mm", min_val=5, max_val=2_000),
            ),
            capability=(("create", "mep_system"),),
            post=("each LocationCurve == its node pair ±5mm (geometry); "
                  "connector-graph BFS reaches every segment in-transaction "
                  "(topology — the CONNECT signal); the MEPSystem the segments "
                  "end up in is DERIVED by Revit at commit and read back into "
                  "the witness (mep_system_ids/one_system — reported, never forced)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "piping_system_types", False),
                      ("pipe_type", "pipe_types", False)),
            # 2026-08-03: the promised ±5 mm at the end, and the diameter
            # tolerance. The SAME numbers that stood as literals in
            # `_network_geometry_post` (`> 5` and `>0.5`); the same end
            # tolerance also sets the FLOOR FOR THE TRIM under a branch
            # take-off (`_segment_trim_bounds_mm`), so one tolerance has
            # exactly one home.
            tolerances={"endpoint_mm": 5.0, "diameter_mm": 0.5},
        ),
    # route_pipe_system — domestic water (water supply / drainage) network as a graph:
    # source -> route -> consumers, connectivity as an invariant. Same
    # nodes+segments shape and connect.graph_validate reuse as
    # create_pipe_system; adds the checked (not generative) slope
    # postcondition described in the module docstring above.
    OpSpec(
            name="route_pipe_system",
            effect=EffectKind.CREATE,
            result=RESULT_NETWORK_SEGMENTS,
            family="authoring",
            params=(
                ParamSpec("nodes", "graph_nodes", required=True),
                ParamSpec("segments", "graph_segments", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("pipe_type", "sel"),
                ParamSpec("diameter_mm", "mm", min_val=5, max_val=2_000),
                # segments[].slope_min_pct rides inside each segment dict
                # (alongside from/to/diameter_mm), not a top-level ParamSpec:
                # graph_nodes/graph_segments are cross-field-validated once at
                # ground (connect.graph_validate / this module's own
                # route_graph_validate wrapper) — a top-level param would
                # duplicate that single validation pass for no benefit.
            ),
            capability=(("create", "mep_system"),),
            # THE BOUNDARY BETWEEN AUTHORED AND DERIVED (2026-08-09) — this
            # boundary IS the contract. The op authors the GRAPH: nodes,
            # edges, level, diameter where the author named it, and the
            # slope floor where they named that. Everything else in the
            # Revit network Revit DERIVES itself, and not one derived value
            # is allowed to stand in the gate: a gate on a number nobody
            # wrote is a gate on someone else's decision.
            post=("AUTHORED, therefore gated — each LocationCurve == its node "
                  "pair ±5mm re-read from the built MEPCurve (geometry: "
                  "axis-decomposed, so a junction end may be shortened by a "
                  "fitting but never moved off the segment axis); one MEPCurve "
                  "per authored edge or a typed refusal (materialize); each "
                  "segment's RBS_START_LEVEL_PARAM == the resolved level, which "
                  "this emitter passes into Pipe.Create itself (topology); "
                  "segment diameter == diameter_mm ONLY where the author stated "
                  "one, never where the pipe type decides it (semantic); a "
                  "segment carrying slope_min_pct has |actual_slope_pct| >= "
                  "slope_min_pct or the program rolls back (KIR-X004, checked "
                  "not generated); connector-graph BFS reaches every segment "
                  "in-transaction (topology — the CONNECT signal); EMITTED BY THIS "
                  "OP FROM THE AUTHORED GRAPH and deliberately not gated — "
                  "elbows, tees and transitions are created by "
                  "connect.emit_fittings_cs ITSELF (doc.Create.NewElbowFitting "
                  "/ NewTeeFitting / NewTransitionFitting, or "
                  "Connector.ConnectTo where the run is straight and "
                  "same-diameter), one per node of degree >= 2, with the "
                  "junction kind chosen by connect.classify_junction from "
                  "degree, local angle and the two diameters (ВК). "
                  "Revit chooses only WHICH FAMILY fills the call, out of "
                  "the type's routing preferences — never WHETHER a fitting "
                  "appears. The count stays out of the gate because it "
                  "follows from graph topology the author wrote, not because "
                  "some other party invented it. COROLLARY, and the reason "
                  "this is now spelled out at length: a bare "
                  "create_pipe authors NO fitting and Revit generates none "
                  "for it, so a decompiled tree — which lifts one create_pipe "
                  "per curve and builds no graph at all — duplicates nothing "
                  "when it also lifts each OST_PipeFitting as an explicit "
                  "place_family (measured 10.08 on snowdon_plumb_v4 with "
                  "tools/relift_offline.py plus a direct L0 endpoint scan: 0 "
                  "of 32502 pipe and duct endpoints lie within 1mm of another "
                  "endpoint, 124 within 5mm, median gap to the nearest fitting "
                  "21.0mm, 26.7% of curves shorter than 100mm — bare MEPCurves "
                  "cannot connect and therefore cannot generate). NUMBERS "
                  "WITHDRAWN: this clause used to cite one live rebuild "
                  "producing 2652 pipe fittings and 152 accessories from ZERO "
                  "authored ones. 2652 and 152 are exactly the OST_PipeFitting "
                  "and OST_DuctFitting counts of the snowdon_plumb_v3 census "
                  "captured the same day (30.07), that model holds 126 "
                  "OST_PipeAccessory and not 152, and no emitter in this "
                  "package creates an accessory at all — so the provenance of "
                  "those numbers is unverified and the mechanism above is what "
                  "should be cited instead of them. MEPSystem membership "
                  "merges at Commit() "
                  "and not at doc.Regenerate(), which makes every "
                  "in-transaction membership check unsatisfiable by "
                  "construction: it is read back AFTER commit into "
                  "mep_system_ids/one_system and reported, never forced"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "piping_system_types", False),
                      ("pipe_type", "pipe_types", False)),
            # Same as create_pipe_system above. The SLOPE WITNESS (KIR-X004)
            # brings NO numbers of its own here: `post` promises an
            # INEQUALITY (|actual| >= slope_min_pct), not a ±tolerance;
            # `1e-6` there is a floating-point comparison epsilon, and
            # `__run < 1.0` is the discriminator for a vertical riser, for
            # which slope is not defined at all. These are parts of the
            # PREDICATE, not of its precision (see route_mep.py).
            tolerances={"endpoint_mm": 5.0, "diameter_mm": 0.5},
        ),
    # route_duct_system — an HVAC (ventilation) network as a graph. Mirrors
    # route_pipe_system over Duct.Create / duct BIPs (Mechanical domain);
    # same connect.graph_validate reuse, same fitting-by-degree inference.
    OpSpec(
            name="route_duct_system",
            effect=EffectKind.CREATE,
            result=RESULT_NETWORK_SEGMENTS,
            family="authoring",
            params=(
                ParamSpec("nodes", "graph_nodes", required=True),
                ParamSpec("segments", "graph_segments", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("system_type", "sel"),
                ParamSpec("duct_type", "sel"),
                ParamSpec("diameter_mm", "mm", min_val=50, max_val=3_000),
            ),
            capability=(("create", "mep_system"),),
            # The same boundary as route_pipe_system above, verbatim — with
            # the domain adjusted (Duct.Create, HVAC fittings).
            post=("AUTHORED, therefore gated — each LocationCurve == its node "
                  "pair ±5mm re-read from the built MEPCurve (geometry: "
                  "axis-decomposed, so a junction end may be shortened by a "
                  "fitting but never moved off the segment axis); one MEPCurve "
                  "per authored edge or a typed refusal (materialize); each "
                  "segment's RBS_START_LEVEL_PARAM == the resolved level, which "
                  "this emitter passes into Duct.Create itself (topology); "
                  "segment diameter == diameter_mm ONLY where the author stated "
                  "one, never where the duct type decides it (semantic — a duct "
                  "type's Shape decides whether a diameter applies at all); a "
                  "segment carrying slope_min_pct has |actual_slope_pct| >= "
                  "slope_min_pct or the program rolls back (KIR-X004, checked "
                  "not generated); connector-graph BFS reaches every segment "
                  "in-transaction (topology — the CONNECT signal); EMITTED BY THIS "
                  "OP FROM THE AUTHORED GRAPH and deliberately not gated — "
                  "elbows, tees and transitions are created by "
                  "connect.emit_fittings_cs ITSELF (doc.Create.NewElbowFitting "
                  "/ NewTeeFitting / NewTransitionFitting, or "
                  "Connector.ConnectTo where the run is straight and "
                  "same-diameter), one per node of degree >= 2, with the "
                  "junction kind chosen by connect.classify_junction from "
                  "degree, local angle and the two diameters (ОВ). "
                  "Revit chooses only WHICH FAMILY fills the call, out of "
                  "the type's routing preferences — never WHETHER a fitting "
                  "appears. The count stays out of the gate because it "
                  "follows from graph topology the author wrote, not because "
                  "some other party invented it. COROLLARY, and the reason "
                  "this is now spelled out at length: a bare "
                  "create_duct authors NO fitting and Revit generates none "
                  "for it, so a decompiled tree — which lifts one create_duct "
                  "per curve and builds no graph at all — duplicates nothing "
                  "when it also lifts each OST_DuctFitting as an explicit "
                  "place_family (measured 10.08 on snowdon_plumb_v4 with "
                  "tools/relift_offline.py plus a direct L0 endpoint scan: 0 "
                  "of 32502 pipe and duct endpoints lie within 1mm of another "
                  "endpoint, 124 within 5mm, median gap to the nearest fitting "
                  "21.0mm, 26.7% of curves shorter than 100mm — bare MEPCurves "
                  "cannot connect and therefore cannot generate). NUMBERS "
                  "WITHDRAWN: this clause used to cite one live rebuild "
                  "producing 2652 pipe fittings and 152 accessories from ZERO "
                  "authored ones. 2652 and 152 are exactly the OST_PipeFitting "
                  "and OST_DuctFitting counts of the snowdon_plumb_v3 census "
                  "captured the same day (30.07), that model holds 126 "
                  "OST_PipeAccessory and not 152, and no emitter in this "
                  "package creates an accessory at all — so the provenance of "
                  "those numbers is unverified and the mechanism above is what "
                  "should be cited instead of them. MEPSystem membership "
                  "merges at Commit() "
                  "and not at doc.Regenerate(), which makes every "
                  "in-transaction membership check unsatisfiable by "
                  "construction: it is read back AFTER commit into "
                  "mep_system_ids/one_system and reported, never forced"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "duct_system_types", False),
                      ("duct_type", "duct_types", False)),
            # Same as route_pipe_system above (the same caveat about slope).
            tolerances={"endpoint_mm": 5.0, "diameter_mm": 0.5},
        ),
]
