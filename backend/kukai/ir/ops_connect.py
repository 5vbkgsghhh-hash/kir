"""ops_connect — CONNECT sublanguage (network-graph systems).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

wave/mep (2026-07-17): route_pipe_system / route_duct_system tile the PROVEN
create_pipe_system graph pattern (KIR_CONNECT_SPEC.md — connectivity by
construction, fittings inferred from node degree) onto the full ВК/ОВ op
family. NOTE ON PLACEMENT (flagged): the wave brief said edit only
ops_mep.py, but these are network-SYSTEM ops (nodes+segments+one MEPSystem),
and REGISTRY_MODULES.md's own ops_mep.py entry is explicit that "СИСТЕМЫ
идут в ops_connect" — the same rule create_pipe_system already follows.
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

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

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
        ),
    # route_pipe_system — ВК (water supply / drainage) network as a graph:
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
            post=("each LocationCurve == its node pair ±5mm (geometry); "
                  "connector-graph BFS reaches every segment in-transaction "
                  "(topology — the CONNECT signal); the MEPSystem the segments "
                  "end up in is DERIVED by Revit at commit and read back into "
                  "the witness (mep_system_ids/one_system — reported, never forced); a segment carrying "
                  "slope_min_pct has |actual_slope_pct| >= slope_min_pct or the "
                  "program rolls back (KIR-X004, checked not generated)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "piping_system_types", False),
                      ("pipe_type", "pipe_types", False)),
        ),
    # route_duct_system — ОВ (ventilation) network as a graph. Mirrors
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
            post=("each LocationCurve == its node pair ±5mm (geometry); "
                  "connector-graph BFS reaches every segment in-transaction "
                  "(topology — the CONNECT signal); the MEPSystem the segments "
                  "end up in is DERIVED by Revit at commit and read back into "
                  "the witness (mep_system_ids/one_system — reported, never forced); a segment carrying "
                  "slope_min_pct has |actual_slope_pct| >= slope_min_pct or the "
                  "program rolls back (KIR-X004, checked not generated)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("system_type", "duct_system_types", False),
                      ("duct_type", "duct_types", False)),
        ),
]
