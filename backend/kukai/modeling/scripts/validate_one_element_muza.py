#!/usr/bin/env python3
"""Validate the modeling framework end-to-end on the live 'Муза' Revit doc.

Modes:
  resolve  READ-ONLY: query Муза + Resolver.resolve one column intent (no LLM, no write).
  dry      resolve + DeepSeek generate + review + REAL compile, FAKE execute (no model write).
  full     resolve + generate + EXECUTE one column (count-gate). OPERATOR-GATED write.

Live reads/writes route through the allow-listed op_revit.py exec. The 'full' write
step is operator-gated by policy — the operator runs it; the assistant builds it.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys

sys.path.insert(0, "/tmp/modeling-audit/backend")

from kukai.modeling.bridge.bridge_model_query_client import BridgeModelQueryClient
from kukai.modeling.bridge.compile_client import HttpCompileClient
from kukai.modeling.bridge.write_bridge_adapter import WriteBridgeAdapter, WrappingCompileClient
from kukai.modeling.execution.gates import CompileGate, CountValidationGate, ExecuteGate
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.foreman import Foreman
from kukai.modeling.llm.deepseek_client import DeepSeekModelingClient
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.schemas.foreman import PhasePlan, PlanTask
from kukai.modeling.schemas.identifiers import deterministic_task_uuid
from kukai.modeling.schemas.resolver import FamilyHint, GridIntersectionSpec, ResolverIntent
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Phase, Tier
from kukai.modeling.state.projections.project_state import ProjectState
from kukai.modeling.subagent.skill_loader import SkillLoader
from kukai.modeling.subagent.structural import StructuralSubagent

VPY = "/opt/kukai-rebuild1/backend/venv/bin/python"
OP_REVIT = "/opt/kukai-rebuild1/scripts/op_revit.py"
DEVICE = "a6d7d14340bc599817ae7e6896182ca0"  # Муза, operator-authorized
REVIT_VERSION = "2026"
SKILL_PATH = "modeling/structure/columns/concrete-columns"  # SkillLoader appends .md
RAG = [("col1", "NewFamilyInstance column",
        "doc.Create.NewFamilyInstance(point, symbol, level, "
        "Autodesk.Revit.DB.Structure.StructuralType.Column)")]


# SAFETY (operator directive): the /admin/remote endpoint can reach OTHER users'
# LIVE Revit sessions on the same backend. This tool must NEVER touch any model but
# the operator-authorized one. Every command is addressed to ONE device_id (no
# broadcast), and we hard-fail before sending if the id is not on this allowlist.
AUTHORIZED_DEVICES = frozenset({"a6d7d14340bc599817ae7e6896182ca0"})  # Музе only


def _assert_authorized(device: str) -> None:
    if device not in AUTHORIZED_DEVICES:
        raise SystemExit(
            f"REFUSED: device {device!r} is not operator-authorized "
            f"(allowlist: {sorted(AUTHORIZED_DEVICES)}). This tool must never touch "
            "another user's live model."
        )


def make_exec_fn(device: str):
    _assert_authorized(device)

    async def exec_fn(code: str, timeout_ms: int):
        _assert_authorized(device)  # re-check on every call — defence in depth
        proc = await asyncio.create_subprocess_exec(
            VPY, OP_REVIT, "exec", device, "--timeout-ms", str(int(timeout_ms)), "--code", code,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        try:
            data = json.loads(out.decode(errors="ignore"))
        except Exception:
            return {"error": True, "message": out.decode(errors="ignore")[:300]}
        if data.get("status") != 200:
            return {"error": True, "message": json.dumps(data.get("body"))[:300]}
        return (data.get("body") or {}).get("result")
    return exec_fn


async def choose_intent(qc: BridgeModelQueryClient):
    levels = await qc.query_levels()
    grids = await qc.query_grids()
    fams = await qc.query_families("OST_StructuralColumns")
    horiz = [g for g in grids if g.axis == "horizontal"]   # supplies X
    vert = [g for g in grids if g.axis == "vertical"]       # supplies Y
    picked = {"n_levels": len(levels), "n_grids": len(grids), "n_struct_col_fams": len(fams),
              "n_horiz": len(horiz), "n_vert": len(vert)}
    if not levels or not fams or not horiz or not vert:
        return None, picked, fams
    fam = fams[0]
    picked.update({"level": levels[0].name, "grid_x": horiz[0].name, "grid_y": vert[0].name, "family": fam.name})
    intent = ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(category="OST_StructuralColumns", name_contains=[fam.name]),
        grid_intersection=GridIntersectionSpec(
            grid_x_name=horiz[0].name, grid_y_name=vert[0].name, level_name=levels[0].name),
        revit_version=REVIT_VERSION,
    )
    return intent, picked, fams


class DryRunBridge:
    """ExecuteGate bridge that does NOT write — returns fake ids so count-gate passes."""
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute_code(self, *, session_id: str, csharp_code: str, expected_count: int = 1):
        self.calls.append({"dry": True})
        return {"success": True, "element_ids": list(range(900000, 900000 + expected_count)),
                "error": None, "duration_ms": 0}


class CapturingCompile:
    """Records each compile (code, result) so a failed run can print real errors."""
    def __init__(self, inner) -> None:
        self._inner = inner
        self.history: list[tuple[str, dict]] = []

    @property
    def calls(self):
        return getattr(self._inner, "calls", [])

    async def compile(self, code, revit_version="2026"):
        res = await self._inner.compile(code, revit_version)
        self.history.append((code, res))
        return res

    async def health(self):
        return await self._inner.health()


_CAPTURE: CapturingCompile | None = None


def _build_foreman(qc, exec_fn, *, write: bool) -> Foreman:
    global _CAPTURE
    _CAPTURE = CapturingCompile(HttpCompileClient())  # capture wrapped code that actually compiled
    compile_client = WrappingCompileClient(_CAPTURE)
    bridge = WriteBridgeAdapter(exec_fn) if write else DryRunBridge()
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(bridge, session_id=DEVICE),
        count_gate=CountValidationGate(),
    )
    return Foreman(
        project_id=DEVICE, resolver=Resolver(qc),
        subagent=StructuralSubagent(DeepSeekModelingClient()),
        execution_queue=queue, skill_loader=SkillLoader(), rag_snippets=RAG,
        project_state_provider=lambda: ProjectState(),
    )


async def run(mode: str):
    qc = BridgeModelQueryClient(make_exec_fn(DEVICE), revit_version=REVIT_VERSION)
    intent, picked, fams = await choose_intent(qc)
    print("PICKED:", json.dumps(picked, ensure_ascii=False))
    if intent is None:
        print("ABORT: Муза lacks levels/grids/column-families for a column placement.")
        print("families sample:", [f.name for f in fams[:8]])
        return

    if mode == "resolve":
        out = await Resolver(qc).resolve(intent)
        print("RESOLVED:", out.family_resolution.value,
              "| symbol_id:", out.family_symbol_id,
              "| point_mm:", (round(out.placement_point.x, 1), round(out.placement_point.y, 1), round(out.placement_point.z, 1)),
              "| level_id:", out.level_id)
        print("notes:", out.notes)
        return

    # dry / full: single-task dispatch with FULL diagnostics
    from kukai.modeling.execution.invariants import check_proposal_invariants
    foreman = _build_foreman(qc, make_exec_fn(DEVICE), write=(mode == "full"))
    task = PlanTask(
        plan_task_id=deterministic_task_uuid(DEVICE, "structure", 1),
        intent=intent,
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2, skill_path=SKILL_PATH,
    )
    outcome = await foreman.dispatch_task(task, phase=Phase.STRUCTURE, task_seq=1)
    ro = outcome.resolver_output
    print("RESOLVED:", ro.family_resolution.value, "| symbol_id:", ro.family_symbol_id,
          "| point_mm:", (round(ro.placement_point.x, 1), round(ro.placement_point.y, 1), round(ro.placement_point.z, 1)),
          "| level_id:", ro.level_id)
    prop = outcome.code_proposal
    if prop is None:
        print("NO PROPOSAL — verdict:", outcome.review_verdict.summary)
        print("notes:", outcome.notes)
        return
    print("\n--- rag_citations:", [(c.snippet_id, c.api_called) for c in prop.rag_citations])
    viols = check_proposal_invariants(prop)
    print("--- invariants:", [(v.rule_id, v.severity, v.message[:70]) for v in viols] or "none")
    print("--- review.passed:", outcome.review_verdict.passed)
    for i in outcome.review_verdict.issues:
        print("    issue:", i.severity, i.category, (i.detail or "")[:90])
    er = outcome.execution_result
    if er is not None:
        print("--- execution_result: success=", er.success, "| stage=", er.failure_stage,
              "| err=", (er.error_message or "")[:160], "| ids=", er.element_ids)
    print("--- notes:", outcome.notes)
    if _CAPTURE and _CAPTURE.history:
        code, res = _CAPTURE.history[-1]
        ok = getattr(res, "success", None)
        print(f"\n--- last Roslyn compile: success={ok} ({len(_CAPTURE.history)} attempt(s)) ---")
        for e in (getattr(res, "errors", []) or [])[:12]:
            print("   ROSLYN:", getattr(e, "code", ""), "L%s" % getattr(e, "line", ""),
                  getattr(e, "message", "")[:110])
    print("\n--- generated C# (proposal body) ---")
    print(prop.csharp_code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["resolve", "dry", "full"])
    a = ap.parse_args()
    if a.mode == "full":
        print("NOTE: 'full' performs a LIVE write to Муза — operator-gated. Run intentionally.")
    asyncio.run(run(a.mode))


if __name__ == "__main__":
    main()
