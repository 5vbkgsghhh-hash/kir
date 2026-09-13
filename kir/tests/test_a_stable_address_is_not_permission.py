"""D-1: A STABLE TYPE ADDRESS — AND WHAT IT DOES NOT GRANT.

The owner's word: "a stable address by itself does not grant the right to
overwrite an existing type." Two halves, checked separately:

  1. THE ADDRESS. The ownership marker used to be
     `kir:{sha1 of the whole grounded program}:{op_id}`. Measured before the
     fix: an edit to the height of a NEIGHBORING wall moved the address of an
     untouched type, and republishing the same project failed at the
     ownership guard. Now the address is taken from the STABLE IDENTITY of
     the author's program, if the envelope carries one; a bare program keeps
     the old behavior byte for byte.
  2. THE RIGHT. A matching address does NOT permit overwriting someone
     else's composition: re-creation remains a read, and a divergence is a
     NAMED refusal at the operation stage, before it ever reaches a single
     consumer of the type. Updating an existing type is not implemented and
     is only named in the refusal.

There is no Revit here: what is judged is the emitted text and the
compiler's typed refusals, not the model's behavior.
"""
from __future__ import annotations

import copy
import re

import pytest

from kir import compile_program
from kir.emit_core import _program_stamp, lineage_token, program_hash
from kir.tests.fixtures import GROUND_SNAPSHOT

WALL_TYPE = {"op": "create_wall_type", "id": "WT1", "new_name": "KIR 250",
             "source_type": {"by": "element_id", "value": 100},
             "layers": [{"width_mm": 250, "function": "Structure"}]}
WALL = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
        "height_mm": 3000, "level": {"by": "element_id", "value": 42},
        "type": {"by": "ref", "value": "WT1"}}
BASE = {"ir_version": "1.0", "ops": [WALL_TYPE, WALL]}


def emit(program, version="2026"):
    out = compile_program(program, revit_version=version, snapshot=GROUND_SNAPSHOT)
    assert out.ok, [d.as_dict() for d in out.diagnostics]
    return out.csharp


def owners(csharp):
    return sorted(set(re.findall(r'String\.Equals\(__owner_\w+, "(kir:[^"]+)"', csharp)))


# ── 1. THE ADDRESS ─────────────────────────────────────────────────────────

def test_a_neighbour_edit_no_longer_moves_the_address_of_an_untouched_type():
    """Defect D-1, verbatim: neighboring wall 3000 -> 3100."""
    with_lineage = dict(BASE, lineage="residential")
    moved = copy.deepcopy(with_lineage)
    moved["ops"][1]["height_mm"] = 3100
    assert owners(emit(with_lineage)) == owners(emit(moved))
    assert owners(emit(with_lineage)) == [f"kir:{lineage_token('residential')}:WT1"]


def test_an_added_neighbour_does_not_move_the_address_either():
    with_lineage = dict(BASE, lineage="residential")
    grown = copy.deepcopy(with_lineage)
    grown["ops"].append({"op": "create_wall", "id": "W2", "p0_mm": [0, 0],
                         "p1_mm": [0, 4000], "height_mm": 3000,
                         "level": {"by": "element_id", "value": 42},
                         "type": {"by": "ref", "value": "WT1"}})
    assert owners(emit(with_lineage)) == owners(emit(grown))


def test_two_projects_do_not_share_an_address():
    """The address must DISTINGUISH projects, otherwise it's not an address but a shared prefix."""
    a = owners(emit(dict(BASE, lineage="residential")))
    b = owners(emit(dict(BASE, lineage="office-tower")))
    assert a and b and a != b


def test_a_bare_program_keeps_the_previous_address_byte_for_byte():
    """There is nothing to weaken in something that has no stable name."""
    bare = emit(BASE)
    assert owners(bare) == [f"kir:{program_hash(compile_program(BASE, revit_version='2026', snapshot=GROUND_SNAPSHOT).grounded_ops)}:WT1"]
    moved = copy.deepcopy(BASE)
    moved["ops"][1]["height_mm"] = 3100
    assert owners(bare) != owners(emit(moved)), "прежнее поведение голой программы изменилось"


@pytest.mark.parametrize("bad", ["", " ", "a" * 65, "плохой", 7, None, {"x": 1}])
def test_a_malformed_lineage_is_a_typed_refusal_not_a_silent_fallback(bad):
    out = compile_program(dict(BASE, lineage=bad), revit_version="2026",
                          snapshot=GROUND_SNAPSHOT)
    assert not out.ok
    assert any(d.field_name == "lineage" for d in out.diagnostics)


def test_the_a5_scope_still_owns_its_run():
    """The internal run-time stamp is not swallowed by the address: it has its own role."""
    scope = "a5:111111111111:aaaaaaaaaaaaaaaa"
    assert _program_stamp([], scope, "residential") == \
        f"kir:{scope}:{lineage_token('residential')}"
    assert _program_stamp([], "", "residential") == f"kir:{lineage_token('residential')}"


def test_the_project_envelope_carries_its_lineage():
    """Identity travels FROM THE PROJECT, it is not made up by the compiler."""
    from kir.project_selection import selected_instance_program
    from examples.residential_project import concept

    project = concept()
    program = selected_instance_program(project, "tower-a")
    assert program["lineage"] == project.project_id


# ── 2. THE RIGHT ───────────────────────────────────────────────────────────

def test_reuse_refuses_a_different_composition_by_name():
    """The address matched — check the composition; a divergence is named, not a "postcondition"."""
    cs = emit(dict(BASE, lineage="residential"))
    assert "__reuseSame_WT1" in cs
    assert ("тип с этим адресом уже существует с другим составом; "
            "изменение существующего типа — отдельная операция") in cs


def test_the_reuse_guard_stands_before_any_consumer_of_the_type():
    """A refusal at the OP STAGE: otherwise neighboring walls are already built with the wrong type."""
    cs = emit(dict(BASE, lineage="residential"))
    assert cs.index("__reuseSame_WT1") < cs.index("// create_wall W1")


def test_reuse_writes_nothing_at_all():
    """The reuse branch does not call SetCompoundStructure at all."""
    cs = emit(dict(BASE, lineage="residential"))
    apply_at = cs.index("__el_WT1.SetCompoundStructure(")
    assert cs[:apply_at].rstrip().endswith("{") or "if (__dupd_WT1)" in cs[apply_at - 200:apply_at]


def test_the_reuse_guard_compares_count_width_function_and_material():
    cs = emit(dict(BASE, lineage="residential"))
    block = cs[cs.index("var __reuseCs_WT1"):cs.index("__el_WT1 = __twin_WT1;")]
    assert ".Count == __lay_WT1.Count" in block
    assert "Math.Abs(__reuseL_WT1[__ri_WT1].Width - __lay_WT1[__ri_WT1].Width)" in block
    assert ".Function != __lay_WT1[__ri_WT1].Function" in block
    assert ".MaterialId.Equals(__lay_WT1[__ri_WT1].MaterialId)" in block


def test_the_ownership_guard_is_not_weakened_by_the_stable_address():
    """The ownership guard is in place and still requires an EXACT marker."""
    cs = emit(dict(BASE, lineage="residential"))
    assert "одноимённый тип не принадлежит этому точному запросу" in cs
    assert 'StringComparison.Ordinal' in cs
    assert "одноимённый тип неоднозначен; создание не выбирает первый" in cs


def test_update_of_an_existing_type_is_not_implemented_and_says_so():
    """The update is not built — and the refusal names this, rather than staying silent."""
    cs = emit(dict(BASE, lineage="residential"))
    assert "изменение существующего типа — отдельная операция" in cs
    from kir import spec
    assert not any("update" in name and "type" in name for name in spec.OPS), \
        "появился оп обновления типа — перепиши этот пин вместе с ним"


def test_the_pin_goes_red_when_the_reuse_guard_is_reversed():
    """CONTROL: under the exact counterfactual (emission BEFORE the fix), there is no guard."""
    from kir.tests.emit_parity_fixtures.d1_counterfactual import without_d1_reuse_guard

    with without_d1_reuse_guard():
        cs = emit(dict(BASE, lineage="residential"))
    assert "__reuseSame_WT1" not in cs
    assert "тип с этим адресом уже существует с другим составом" not in cs
    # And the OWNERSHIP guard is still in place there too: the counterfactual removes exactly one thing.
    assert "одноимённый тип не принадлежит этому точному запросу" in cs
