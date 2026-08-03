"""KIR registry AGGREGATOR — the single source of truth (SPEC §3).

OpSpec DEFINITIONS live in per-family modules (ops_authoring/ops_contour/
ops_connect/ops_mep/ops_doc/ops_struct/ops_annotation/ops_families) so that N
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

# Re-export the shared base so `spec.KINDS`, `spec.OpSpec`, `spec.DEFAULTS`,
# `spec.WRITE_FAMILIES`, ... all keep resolving exactly as before.
from kukai.ir.registry_base import *  # noqa: F401,F403
from kukai.ir.registry_base import (  # explicit, for this module + linters
    EffectKind, IdentityCardinality, OpSpec, ResultSpec, IR_VERSION,
    ROUTE_ONLY_ACTIONS, BANNED_OBJECT_KIND_PLACEHOLDERS,
)

# Every registry module. A new family = a new ops_*.py added to THIS list only.
from kukai.ir import (  # noqa: E402
    ops_authoring, ops_contour, ops_connect, ops_mep,
    ops_doc, ops_struct, ops_annotation, ops_families, ops_arch,
    ops_shape,
)

_REGISTRY_MODULES = (
    ops_authoring, ops_contour, ops_connect, ops_mep,
    ops_doc, ops_struct, ops_annotation, ops_families, ops_arch,
    ops_shape,
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


def _lint_registry() -> None:
    """Registry invariants, enforced at import on the AGGREGATE (RISK R10,
    bare-action ban 13.2, §16 placeholder ban)."""
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
                       # ДВА НОВЫХ ПУЛА, а не переиспользование floor_types —
                       # и это не педантизм: CeilingType и RailingType в Revit
                       # разные классы, и грунтовка потолка по пулу перекрытий
                       # дала бы ПРАВДОПОДОБНЫЙ, но неверный тип, то есть
                       # тихую подмену, неотличимую снаружи от успеха. Пул —
                       # «Fable-level» изменение (REGISTRY_MODULES.md), потому
                       # что тянет за собой сборщик в open_model.py; лишний
                       # повод не заводить его от лени, а не повод не заводить
                       # его по делу.
                       "ceiling_types", "railing_types")
        for pname, pool, _req in op.grounded:
            variants = ([pool.format(category=c) for c in ("structural", "architectural")]
                        if "{category}" in pool else [pool])
            for v in variants:
                if v not in known_pools:
                    raise AssertionError(f"{op.name}.{pname}: unknown snapshot pool {v!r}")


_lint_registry()


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
