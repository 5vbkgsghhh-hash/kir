"""C-1: A RETRACTED OP LEAVES NO TRACE IN THE COMMON VIOLATIONS LIST.

What is being proven here, and by what — read this before trusting the
green.

``__post`` is the list of the ENTIRE program. In ``report`` mode (and
``per_op`` forces it by construction) it moves in its entirety into
``__results["postcondition_violations"]``. Before 06.09.2026 the operation
stage's gate threw its refusal while LEAVING its lines behind: the op's
SubTransaction was rolled back, the element was gone, but the message kept
being counted as a postcondition violation of the COMMITTED program, and
consumer D1 declared the whole record VIOLATED.

THE HONESTY BOUNDARY. Neither Revit nor C# is executed here. What is real:
the compiler (``compile_program``), the emitted text, and the consumer
(``bridge_result.assess_write_result``) against a real ``PlannedProgram``.
The rig in the middle REPLAYS the control flow READ OUT OF THE EMITTED TEXT
(whether the gate removes its own range; whether the program attaches
``__post`` to the result), and refuses if the emission's shape has changed,
instead of guessing.

THE PIN CAN TURN RED, AND THAT IS CHECKED RIGHT HERE: the same rig under the
exact counterfactual ``without_c1_range_cleanup`` (emission BEFORE the fix)
must show the leak. A pin that does not turn red when the defect returns
guards nothing.
"""
from __future__ import annotations

import re

import pytest

from kir import compile_program
from kir.authoring import emit_program
from kir.bridge_result import assess_write_result, expected_results
from kir.compiler import _parse_and_check
from kir import ground as ground_mod
from kir.tests.emit_parity_fixtures.c1_counterfactual import without_c1_range_cleanup
from kir.tests.fixtures import GROUND_SNAPSHOT

LEVEL = {"by": "element_id", "value": 42}
CHAIN = {
    "ir_version": "1.0",
    "intent": "c1",
    "ops": [
        {"op": "create_wall", "id": "made", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": LEVEL},
        {"op": "change_type", "id": "first", "target": {"by": "ref", "value": "made"},
         "type": {"by": "element_id", "value": 100}},
        {"op": "change_type", "id": "second", "target": {"by": "ref", "value": "made"},
         "type": {"by": "element_id", "value": 101}},
    ],
}
TWO_WALLS = {"ir_version": "1.0", "ops": [
    {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0], "level": LEVEL},
    {"op": "create_wall", "id": "W2", "p0_mm": [0, 0], "p1_mm": [0, 4000], "level": LEVEL},
]}
GROUP = {"ir_version": "1.0", "ops": [
    {"op": "create_group", "id": "GRP1", "name": "Типовой этаж",
     "placements": [[0, 0, 0], [8000, 0, 0]],
     "members": [
         {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0], "level": LEVEL},
         {"op": "create_wall", "id": "W2", "p0_mm": [0, 0], "p1_mm": [0, 4000], "level": LEVEL}]},
]}

_ST_START = re.compile(r"^\s*SubTransaction __st_(\w+) = null;")
_ST_CATCH = re.compile(r"^\s*catch \(__KirOpRefusal __orf_(\w+)\)")
_MARK = re.compile(r"int __operationPostStart_(\w+) = __post\.Count;")
_GATE = re.compile(r"if \(__post\.Count > __operationPostStart_(\w+)\)")
_ADD = re.compile(r'__post\.Add\("((?:[^"\\]|\\.)*)"\)')
_FENCE = re.compile(r"int __opPostStart_(\w+) = __post\.Count;")
_LATE = re.compile(r'catch \(Exception __ex_\w+\) \{ throw __OpRefuse\("([\w:]+)", "([^"]*)" \+ __ex_\w+\.Message\); \}')
_COMMIT = re.compile(r'throw __OpRefuse\("(\w+)", "subtransaction commit: " \+ __stCommit_\w+\.ToString\(\)\)')
_ATTACH = '__results["postcondition_violations"] = __post;'


def emit(program, version="2026", *, isolation="per_op", **kwargs):
    grounded = ground_mod.ground(_parse_and_check(program), GROUND_SNAPSHOT)
    return emit_program(grounded, version, program.get("intent", ""),
                        isolation=isolation, **kwargs)


def op_bodies(csharp):
    """{op_id: (fence_present, body_lines)} for every per-op SubTransaction."""
    lines, out, i = csharp.splitlines(), {}, 0
    while i < len(lines):
        match = _ST_START.match(lines[i])
        if not match:
            i += 1
            continue
        safe = match.group(1)
        fence = bool(i and _FENCE.search(lines[i - 1]) and
                     _FENCE.search(lines[i - 1]).group(1) == safe)
        j = i + 1
        while j < len(lines):
            closing = _ST_CATCH.match(lines[j])
            if closing and closing.group(1) == safe:
                break
            j += 1
        assert j < len(lines), f"no refusal catch for {safe}: emission shape changed"
        out[safe] = (fence, lines[i:j])
        i = j + 1
    return out


def gate_blocks(body):
    """[(marker, added literals, guard line)] for every gate inside one body."""
    blocks = []
    for k, line in enumerate(body):
        mark = _MARK.search(line)
        if not mark:
            continue
        safe = mark.group(1)
        end = None
        for k2 in range(k, len(body)):
            found = _GATE.search(body[k2])
            if found is not None and found.group(1) == safe:
                end = k2
                break
        assert end is not None, f"marker {safe} without its guard: emission shape changed"
        adds = [m.group(1) for line2 in body[k:end + 1] for m in _ADD.finditer(line2)]
        blocks.append((safe, adds, body[end]))
    return blocks


def replay(csharp, planned, *, failing_op=None, mode=None, seeded_post=()):
    """Replay the emitted per-op flow. Every branch is read out of the text."""
    expected, bodies = dict(expected_results(planned)), op_bodies(csharp)
    post, results, element = list(seeded_post), {}, 800
    for oid, spec in expected.items():
        fence, body = bodies[oid]
        fence_start, refused = len(post), None
        for safe, adds, guard in gate_blocks(body):
            if mode != "gate" or oid != failing_op:
                continue
            start = len(post)
            post.extend(adds)
            assert adds, "the gate under test adds nothing: fixture is vacuous"
            message = " ; ".join(post[start:])
            cleanup = (f"__post.RemoveRange(__operationPostStart_{safe}, "
                       f"__post.Count - __operationPostStart_{safe});")
            if cleanup in guard:
                del post[start:]
            refused = (safe, message)
            break
        if refused is None and oid == failing_op and mode in ("late", "commit"):
            pattern, text = (_LATE, "\n".join(body)) if mode == "late" else (_COMMIT, "\n".join(body))
            found = pattern.search(text)
            assert found is not None, f"{oid}: no {mode} refusal site in the emitted body"
            refused = (found.group(1),
                       found.group(2) + "Revit threw" if mode == "late"
                       else "subtransaction commit: RolledBack")
        if refused is not None:
            message = refused[1]
            if fence and len(post) > fence_start:
                message += (" | откачено вместе с операцией: "
                            + " ; ".join(post[fence_start:]))
                del post[fence_start:]
            results[oid] = {"refused": message, "refused_op_id": refused[0]}
            continue
        row = {}
        if spec.identity_field is not None:
            row[spec.identity_field] = str(element)
        element += 1
        results[oid] = row
    if _ATTACH in csharp and post:
        results["postcondition_violations"] = list(post)
    results["ok"] = True
    return results, post


def outcome(payload, planned):
    got = assess_write_result(payload, planned)
    return got.outcome.execution.value, got.outcome.witness.value


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_per_op_gate_lifts_its_message_before_dropping_only_its_own_range(version):
    out = compile_program(CHAIN, snapshot=GROUND_SNAPSHOT, revit_version=version,
                          isolation="per_op")
    assert out.ok, out.diagnostics
    for safe, _adds, guard in gate_blocks(op_bodies(out.csharp)["first"][1]):
        lift = guard.index(f"var __opRefusal_{safe} = String.Join")
        drop = guard.index(f"__post.RemoveRange(__operationPostStart_{safe},")
        throw = guard.index(f"throw __OpRefuse(")
        # The order IS the content of the fix: remove -> delete -> throw.
        assert lift < drop < throw, guard
        # Its own range, not "the whole list": 0 would wipe out its neighbors.
        assert f"__post.RemoveRange(__operationPostStart_{safe}, " \
               f"__post.Count - __operationPostStart_{safe});" in guard
        assert f"throw __OpRefuse(\"first\", __opRefusal_{safe});" in guard


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_atomic_keeps_the_legacy_guard_because_it_never_publishes_the_list(version):
    out = compile_program(CHAIN, snapshot=GROUND_SNAPSHOT, revit_version=version)
    assert out.ok, out.diagnostics
    assert "__post.RemoveRange(" not in out.csharp
    assert "__opRefusal_" not in out.csharp
    # A gate refusal inside atomic is an exit from Execute BEFORE the line that publishes the list.
    guard = next(line for line in out.csharp.splitlines()
                 if "if (__post.Count > __operationPostStart_first)" in line)
    assert "__t.RollBack(); return __Refuse(\"first\"," in guard
    assert out.csharp.index(guard) < out.csharp.index("if (__post.Count > 0)")


@pytest.mark.parametrize("program,kwargs", [
    (CHAIN, {}), (TWO_WALLS, {}), (GROUP, {}),
    (TWO_WALLS, {"disallow_wall_joins": True}),
])
def test_no_writer_to_the_shared_list_survives_a_rolled_back_operation(program, kwargs):
    """Every `__post.Add` inside a SubTransaction must lie within a range
    that someone removes: either the gate block (removes it itself), or the
    op's fence (its catch removes it). Otherwise a rolled-back op writes into
    someone else's receipt."""
    csharp = emit(program, isolation="per_op", **kwargs)
    unguarded = []
    for safe, (fence, body) in op_bodies(csharp).items():
        owned = set()
        for _marker, _adds, guard in gate_blocks(body):
            marker = _GATE.search(guard).group(1)
            assert (f"__post.RemoveRange(__operationPostStart_{marker}," in guard), guard
            start = next(k for k, line in enumerate(body)
                         if f"int __operationPostStart_{marker} = __post.Count;" in line)
            owned.update(range(start, body.index(guard) + 1))
        for k, line in enumerate(body):
            if "__post.Add(" in line and k not in owned and not fence:
                unguarded.append((safe, line.strip()))
    assert unguarded == [], unguarded


@pytest.mark.parametrize("version", ["2023", "2026"])
@pytest.mark.parametrize("mode", ["gate", "late", "commit"])
def test_a_refused_operation_never_makes_the_committed_program_violated(version, mode):
    out = compile_program(CHAIN, snapshot=GROUND_SNAPSHOT, revit_version=version,
                          isolation="per_op")
    payload, post = replay(out.csharp, out.planned, failing_op="first", mode=mode)
    assert post == [], post
    assert "postcondition_violations" not in payload
    # The evidence did not disappear — it moved into its own op's refusal.
    assert payload["first"]["refused"].strip()
    assert payload["first"]["refused_op_id"] in ("first", "GRP1__m__W1")
    # Neither VIOLATED (a false red on the correct part) nor SATISFIED (a
    # silent success on top of a refusal): the honest outcome is
    # committed/incomplete.
    assert outcome(payload, out.planned) == ("committed", "incomplete")


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_a_program_without_refusals_is_still_satisfied(version):
    out = compile_program(CHAIN, snapshot=GROUND_SNAPSHOT, revit_version=version,
                          isolation="per_op")
    payload, post = replay(out.csharp, out.planned)
    assert post == [] and outcome(payload, out.planned) == ("committed", "satisfied")


def test_a_neighbours_line_below_the_marker_is_not_removed():
    """Someone else's lines lie BELOW the marker and must survive a neighbor's refusal."""
    out = compile_program(CHAIN, snapshot=GROUND_SNAPSHOT, revit_version="2026",
                          isolation="per_op")
    neighbour = "made: посторонняя строка соседа"
    payload, post = replay(out.csharp, out.planned, failing_op="first", mode="gate",
                           seeded_post=[neighbour])
    assert post == [neighbour]
    assert payload["postcondition_violations"] == [neighbour]
    assert outcome(payload, out.planned) == ("committed", "violated")


def test_the_de_join_observation_of_a_rolled_back_wall_goes_into_its_refusal():
    """`disallow_wall_joins` writes into the common list AFTER the gate — the
    op's fence must remove this line on refusal and carry it into the
    refusal itself."""
    grounded = ground_mod.ground(_parse_and_check(TWO_WALLS), GROUND_SNAPSHOT)
    csharp = emit_program(grounded, "2026", "dj", isolation="per_op",
                          disallow_wall_joins=True)
    fence, body = op_bodies(csharp)["W2"]
    assert fence, "у опа с де-джойном нет забора __opPostStart_*"
    assert "__post.RemoveRange(__opPostStart_W2, __post.Count - __opPostStart_W2);" in csharp
    assert "откачено вместе с операцией" in csharp
    assert "__post.Add(" in "\n".join(body)


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_the_pin_goes_red_when_the_fix_is_reversed(version):
    """CONTROL. Under the exact counterfactual (emission BEFORE the fix) the
    same rig must show the leak — otherwise it guards nothing."""
    with without_c1_range_cleanup():
        out = compile_program(CHAIN, snapshot=GROUND_SNAPSHOT, revit_version=version,
                              isolation="per_op")
    payload, post = replay(out.csharp, out.planned, failing_op="first", mode="gate")
    assert post == ["first: type assignment mismatch or unavailable (operation)"]
    assert payload["postcondition_violations"] == post
    assert outcome(payload, out.planned) == ("committed", "violated")
