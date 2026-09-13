"""The floor-opening unit judges its loop against the floor's PROFILE before
any effect and against the floor's AREA after the commit — and undoes its own
edit when the two disagree.

Native witness (kir-live-20260909, BatchG1 `UnitFloorOutsideLoop`, 09.09.2026):
a 2×2 m loop placed OUTSIDE a 10×8 m floor. Revit added a second island,
80 → 84 m², and the unit answered `ok=true`, `state=committed_verified`,
`loop_added=true` — because it counted profile loops (+1) and nothing else.
The inner-loop control gave 80 → 76 m². Both ran the byte-identical unit
body of `cfcb305`.

No live Revit here. What IS checked: the plan's refusals, the structure of
the emitted C#, the EXACT emitted judgement executed by dotnet on plain
numbers (the same text Revit would run, minus the Revit calls that feed it),
and compilation of the whole unit against the real RevitAPI 2022–2026.
"""
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from kir.emit_transaction_unit import (
    AREA_DROP_RATIO_MAX, AREA_DROP_RATIO_MIN, LOOP_CLEARANCE_MM, TransactionUnitRefusal,
    plan_floor_sketch_opening, prepare_transaction_unit,
)
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials
from kir.tests.test_a_transaction_owning_unit_owns_its_own_transaction import (
    FLOOR_UID, bound, element_observation,
)
from kir.tests.test_type_creation_conformance import type_conformance_runner

_ = (bound, type_conformance_runner)   # fixtures, re-exported by import

FT = 304.8
#: The witness floor: 10 × 8 m at the origin, one outer loop.
FLOOR_MM = [(0.0, 0.0), (10000.0, 0.0), (10000.0, 8000.0), (0.0, 8000.0)]
INSIDE_MM = [(2000.0, 2000.0), (4000.0, 2000.0), (4000.0, 4000.0), (2000.0, 4000.0)]
OUTSIDE_MM = [(20000.0, 20000.0), (22000.0, 20000.0), (22000.0, 22000.0), (20000.0, 22000.0)]


def floor_plan(bound, loop_mm=INSIDE_MM, **kwargs):
    target, _auth, precondition = bound
    return plan_floor_sketch_opening(element_observation(bound), unique_id=FLOOR_UID,
                                     loop_mm=loop_mm, target=target, precondition=precondition,
                                     **kwargs)


def scope_for(version):
    target = RuntimeTarget(str(uuid4()), str(uuid4()), version)
    return target, SessionCredentials(target, str(uuid4()), "test-only"), ContextPrecondition("native-doc", 21)


# ───────────────────────────── the plan judges the loop ITSELF ──


def test_a_bow_tie_loop_is_refused_by_the_plan(bound):
    with pytest.raises(TransactionUnitRefusal) as error:
        floor_plan(bound, loop_mm=[(0.0, 0.0), (3000.0, 2000.0), (3000.0, 0.0), (0.0, 1000.0)])
    assert error.value.code == "invalid_sketch_loop" and "самопересекается" in str(error.value)


def test_a_symmetric_bow_tie_has_zero_signed_area_and_is_still_named_self_intersecting(bound):
    """Two equal lobes of opposite orientation sum to a signed area of ZERO;
    simplicity is judged first so the refusal names the crossing, not the area."""
    with pytest.raises(TransactionUnitRefusal) as error:
        floor_plan(bound, loop_mm=[(0.0, 0.0), (2000.0, 2000.0), (2000.0, 0.0), (0.0, 2000.0)])
    assert error.value.code == "invalid_sketch_loop" and "самопересекается" in str(error.value)


def test_a_collinear_loop_has_no_inside_and_is_refused(bound):
    """Three points on one line: the third edge runs back over the first two,
    so the fold-back check names it before the area check would."""
    with pytest.raises(TransactionUnitRefusal) as error:
        floor_plan(bound, loop_mm=[(0.0, 0.0), (1000.0, 0.0), (2000.0, 0.0)])
    assert error.value.code == "invalid_sketch_loop" and "складывается" in str(error.value)


def test_a_fold_back_spike_is_refused(bound):
    """Adjacent edges that run back over each other: distinct points, non-zero
    area, and still not a simple polygon."""
    with pytest.raises(TransactionUnitRefusal) as error:
        floor_plan(bound, loop_mm=[(0.0, 0.0), (3000.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0)])
    assert error.value.code == "invalid_sketch_loop"


def test_a_loop_touching_itself_at_a_vertex_is_refused(bound):
    """Non-adjacent edges meeting at a point (a pinched loop) — touching counts."""
    with pytest.raises(TransactionUnitRefusal) as error:
        floor_plan(bound, loop_mm=[(0.0, 0.0), (2000.0, 0.0), (1000.0, 1000.0),
                                   (2000.0, 2000.0), (0.0, 2000.0), (1000.0, 1000.0)])
    assert error.value.code == "invalid_sketch_loop"


def test_a_simple_loop_is_planned_with_its_area_and_the_units_acceptance_named(bound):
    plan = floor_plan(bound)
    assert plan.diff["loop_area_mm2"] == pytest.approx(4_000_000.0)
    assert plan.diff["unit_acceptance"] == {
        "before_effect": "loop_inside_one_outer_boundary_no_crossing_no_touching_no_existing_opening",
        "after_commit": "floor_area_dropped_by_loop_area_else_rolled_back"}
    claims = plan.to_dict()["claims"]
    assert claims["geometric_validity"] == "checked_by_unit_before_effect"
    assert claims["engineering_acceptance"] == "area_witnessed_by_unit_or_rolled_back"
    # What stays not established stays not established: nothing ran.
    assert claims["native_execution"] == "not_run" and claims["live_revit"] == "never_run"


def test_a_new_sketch_does_not_claim_an_opening(bound):
    """`allow_new_sketch`: there is no profile to hold the loop, so the plan
    says exactly that and the claims stay where they were."""
    plan = floor_plan(bound, allow_new_sketch=True)
    assert plan.diff["unit_acceptance"]["before_effect"] == "no_profile_to_check_against"
    claims = plan.to_dict()["claims"]
    assert claims["geometric_validity"] == "not_evaluated"
    assert claims["engineering_acceptance"] == "not_established"


# ───────────────────────────── the emitted unit's structure ──


def test_the_unit_refuses_on_the_profile_before_the_scope_opens_and_undoes_itself_after(bound):
    source = prepare_transaction_unit(floor_plan(bound), operation_id=str(uuid4())).source
    start = source.index("__scope.Start(__sketchId);")
    for code in ('"loop_self_intersecting"', '"sketch_plane_not_horizontal"', '"profile_unreadable"',
                 '"loop_outside_profile"', '"loop_crosses_profile"', '"loop_touches_profile"',
                 '"loop_encloses_existing_loop"', '"loop_inside_existing_opening"',
                 '"floor_area_unreadable"'):
        assert source.index(code) < start, code
    # The group is the unit's own, opened AFTER every pre-effect refusal.
    assert source.count("new TransactionGroup(doc,") == 1
    assert source.index('"observed_before"') < source.index("new TransactionGroup(doc,") < start
    # z comes from the plane, never from an assumption.
    assert "new XYZ(__v[0], __v[1], __z)" in source and "__plane0.Origin.Z" in source
    assert ", 0.0));" not in source
    # The after-witness: loops AND area, and the verdict rolls back on disagreement.
    committed = source.index('__receipt["state"] = "committed_unverified"')
    verified = source.index('__receipt["state"] = "committed_verified"')
    assimilate = source.index("__group.Assimilate();")
    assert committed < source.index("HOST_AREA_COMPUTED", committed) < assimilate < verified
    assert source.index("if (__good)") < assimilate < source.index('"opening_area_disagrees"')
    assert f"__ratio >= {AREA_DROP_RATIO_MIN!r} && __ratio <= {AREA_DROP_RATIO_MAX!r}" in source
    assert source.count('"rolled_back"') >= 4      # disagreement, identity, unreadable, exception
    assert "__KirUnitGroup.Abandon(__group, null)" in source
    assert repr(LOOP_CLEARANCE_MM / FT) in source


def test_a_new_sketch_reads_its_plane_inside_the_scope_and_records_area_without_judging(bound):
    source = prepare_transaction_unit(floor_plan(bound, allow_new_sketch=True),
                                      operation_id=str(uuid4())).source
    assert "__scope.StartWithNewSketch(__el.Id);" in source
    assert source.index("__scope.StartWithNewSketch") < source.index("Plane __plane1 = __plane.GetPlane();")
    assert '__receipt["area_judged"] = false;' in source and "bool __areaGood = true;" in source
    assert '"loop_outside_profile"' not in source


# ───────────────────────────── the judgement, EXECUTED ──


def _emitted_judgement(source: str) -> tuple[str, str]:
    """The `__KirLoop2D` class and the judgement block, cut from the emitted
    source by their own landmarks — not re-typed here."""
    helper = source[source.index("public static class __KirLoop2D"):
                    source.index("// The unit's own TransactionGroup")]
    judgement = source[source.index("var __depth = new int[__loops.Count];"):
                       source.index("// The area is the after-witness")]
    return helper, judgement


_SCENARIOS = {
    # name: (profile loops in mm, new loop in mm, expected refusal or None, expected host)
    "witness_inside": ([FLOOR_MM], INSIDE_MM, None, 0),
    "witness_outside": ([FLOOR_MM], OUTSIDE_MM, "loop_outside_profile", -1),
    "crossing_the_boundary": (
        [FLOOR_MM], [(8000.0, 2000.0), (12000.0, 2000.0), (12000.0, 4000.0), (8000.0, 4000.0)],
        "loop_crosses_profile", -1),
    "half_a_millimetre_from_the_edge": (
        [FLOOR_MM], [(0.5, 2000.0), (2000.0, 2000.0), (2000.0, 4000.0), (0.5, 4000.0)],
        "loop_touches_profile", -1),
    "inside_an_existing_opening": (
        [FLOOR_MM, INSIDE_MM], [(2500.0, 2500.0), (3500.0, 2500.0), (3500.0, 3500.0), (2500.0, 3500.0)],
        "loop_inside_existing_opening", -1),
    "around_an_existing_opening": (
        [FLOOR_MM, [(2500.0, 2500.0), (3500.0, 2500.0), (3500.0, 3500.0), (2500.0, 3500.0)]],
        INSIDE_MM, "loop_encloses_existing_loop", -1),
    "crossing_an_existing_opening": (
        [FLOOR_MM, INSIDE_MM], [(3000.0, 3000.0), (5000.0, 3000.0), (5000.0, 5000.0), (3000.0, 5000.0)],
        "loop_crosses_profile", -1),
    "second_island_is_its_own_host": (
        [FLOOR_MM, [(20000.0, 0.0), (30000.0, 0.0), (30000.0, 8000.0), (20000.0, 8000.0)]],
        [(22000.0, 2000.0), (25000.0, 2000.0), (25000.0, 5000.0), (22000.0, 5000.0)], None, 1),
    "spanning_two_islands": (
        [FLOOR_MM, [(20000.0, 0.0), (30000.0, 0.0), (30000.0, 8000.0), (20000.0, 8000.0)]],
        [(8000.0, 2000.0), (22000.0, 2000.0), (22000.0, 4000.0), (8000.0, 4000.0)],
        "loop_crosses_profile", -1),
    "island_inside_a_hole_is_the_host": (
        [[(0.0, 0.0), (30000.0, 0.0), (30000.0, 30000.0), (0.0, 30000.0)],
         [(5000.0, 5000.0), (25000.0, 5000.0), (25000.0, 25000.0), (5000.0, 25000.0)],
         [(10000.0, 10000.0), (20000.0, 10000.0), (20000.0, 20000.0), (10000.0, 20000.0)]],
        [(12000.0, 12000.0), (14000.0, 12000.0), (14000.0, 14000.0), (12000.0, 14000.0)], None, 2),
    "loop_in_the_hole_beside_the_island": (
        [[(0.0, 0.0), (30000.0, 0.0), (30000.0, 30000.0), (0.0, 30000.0)],
         [(5000.0, 5000.0), (25000.0, 5000.0), (25000.0, 25000.0), (5000.0, 25000.0)],
         [(10000.0, 10000.0), (20000.0, 10000.0), (20000.0, 20000.0), (10000.0, 20000.0)]],
        [(6000.0, 6000.0), (8000.0, 6000.0), (8000.0, 8000.0), (6000.0, 8000.0)],
        "loop_inside_existing_opening", -1),
    "triangle_inside": (
        [FLOOR_MM], [(1000.0, 1000.0), (3000.0, 1000.0), (2000.0, 2500.0)], None, 0),
}

_PROGRAM = """using System;
using System.Collections.Generic;
{helper}
public static class __Judge
{{
    public static Dictionary<string, object> Run(List<List<double[]>> __loops, List<double[]> __new)
    {{
        var __receipt = new Dictionary<string, object>();
{judgement}
        __receipt["host"] = __host;
        return __receipt;
    }}
}}
public static class Program
{{
    static List<double[]> Ring(string line)
    {{
        var ring = new List<double[]>();
        foreach (string pair in line.Split(' '))
        {{
            if (pair.Length == 0) continue;
            string[] xy = pair.Split(',');
            ring.Add(new double[] {{ double.Parse(xy[0], System.Globalization.CultureInfo.InvariantCulture),
                                     double.Parse(xy[1], System.Globalization.CultureInfo.InvariantCulture) }});
        }}
        return ring;
    }}
    public static void Main()
    {{
        string name = null;
        var loops = new List<List<double[]>>();
        List<double[]> fresh = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {{
            if (line.StartsWith("# ")) {{ name = line.Substring(2); loops = new List<List<double[]>>(); fresh = null; }}
            else if (line.StartsWith("L ")) loops.Add(Ring(line.Substring(2)));
            else if (line.StartsWith("N ")) fresh = Ring(line.Substring(2));
            else if (line == "!")
            {{
                var r = __Judge.Run(loops, fresh);
                object refusal; r.TryGetValue("refusal", out refusal);
                object host; if (!r.TryGetValue("host", out host)) host = -1;
                Console.WriteLine(name + "\\t" + (refusal == null ? "-" : refusal.ToString()) + "\\t" + host.ToString());
            }}
        }}
    }}
}}
"""

_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>disable</Nullable>
    <ImplicitUsings>disable</ImplicitUsings>
  </PropertyGroup>
</Project>
"""


@pytest.mark.skipif(shutil.which("dotnet") is None, reason="executing the emitted judgement needs the .NET host")
def test_the_emitted_judgement_executed_on_the_witness_and_its_neighbours(bound, tmp_path):
    """The judgement text is cut out of the emitted C# and RUN. Every scenario
    is in the witness's millimetres; the unit works in feet, so the test
    converts exactly the way the emitter does."""
    source = prepare_transaction_unit(floor_plan(bound), operation_id=str(uuid4())).source
    helper, judgement = _emitted_judgement(source)
    assert "__CLEARANCE__" not in judgement           # the literal was substituted
    (tmp_path / "judge.csproj").write_text(_CSPROJ, encoding="utf-8")
    (tmp_path / "Program.cs").write_text(_PROGRAM.format(helper=helper, judgement=judgement),
                                         encoding="utf-8")
    feed = []
    for name, (loops, fresh, _expected, _host) in _SCENARIOS.items():
        feed.append(f"# {name}")
        for loop in loops:
            feed.append("L " + " ".join(f"{x / FT!r},{y / FT!r}" for x, y in loop))
        feed.append("N " + " ".join(f"{x / FT!r},{y / FT!r}" for x, y in fresh))
        feed.append("!")
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
    result = subprocess.run(["dotnet", "run", "--project", str(tmp_path / "judge.csproj")],
                            input="\n".join(feed) + "\n", text=True, capture_output=True,
                            timeout=600, cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = {line.split("\t")[0]: line.split("\t")[1:] for line in result.stdout.splitlines() if "\t" in line}
    assert set(rows) == set(_SCENARIOS), rows
    for name, (_loops, _fresh, expected, host) in _SCENARIOS.items():
        refusal, seen_host = rows[name]
        assert refusal == (expected or "-"), (name, rows[name])
        assert int(seen_host) == host, (name, rows[name])


# ───────────────────────────── compilation against the REAL API ──


@pytest.mark.parametrize("version", ["2022", "2023", "2024", "2025", "2026"])
def test_the_rewritten_unit_compiles_against_every_supported_api(version, type_conformance_runner):
    scope = scope_for(version)
    plans = [floor_plan(scope)]
    if int(version) >= 2023:
        plans.append(floor_plan(scope, allow_new_sketch=True))
    sources = [prepare_transaction_unit(plan, operation_id=str(uuid4())).source for plan in plans]
    rows = type_conformance_runner(version, sources)
    for plan, row in zip(plans, rows, strict=True):
        assert row["ok"] is True, (version, plan.diff["allow_new_sketch"], row["diagnostics"])
        assert row["assembly_bytes"] > 0
