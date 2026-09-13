"""Typed witness staging without a scheduler, native API, or C# rewriting."""
from dataclasses import FrozenInstanceError, replace

import pytest

from kir.emit_model import (BarePost, EmitModelError, WitnessCheck, post_to_string,
                            render_post, render_staged_post, tolerance)


def check(key="k", *, stage="final"):
    return WitnessCheck(key, f"    var __value_{key} = Read();\n",
        f'    if (!__value_{key}) __post.Add("{key}");\n', key, stage=stage)


@pytest.mark.parametrize("bare", [False, True])
def test_default_final_stage_is_byte_identical_to_legacy_rendering(bare):
    value = check()
    assert value.stage == "final"
    post = BarePost((value,)) if bare else [value]
    expected = '// post OP\n' + ('' if bare else '{\n') + value.reader_cs + value.verdict_cs + ('' if bare else '}')
    assert post_to_string("OP", post) == expected
    assert render_staged_post("OP", post) == ("", expected)
    if not bare:
        assert render_post("OP", post) == expected


def test_old_positional_constructor_remains_compatible_and_stage_is_semantic():
    old = WitnessCheck("k", "", '__post.Add("k");\n', "k", None, "guard")
    assert old.stage == "final"
    operation = replace(old, stage="operation")
    assert operation != old and operation.render() == old.render()
    with pytest.raises(FrozenInstanceError):
        operation.stage = "final"


@pytest.mark.parametrize("bare", [False, True])
def test_sole_operation_check_has_no_fabricated_final_witness(bare):
    value = check(stage="operation")
    post = BarePost((value,)) if bare else (value,)
    operation, final = render_staged_post("OP", post)
    expected = '// operation OP\n' + ('' if bare else '{\n') + value.render() + ('' if bare else '}')
    assert operation == expected and final == ""
    assert operation.count("__post.Add") == 1


@pytest.mark.parametrize("bare", [False, True])
def test_mixed_stages_preserve_order_fragments_and_global_key_uniqueness(bare):
    checks = [check("o1", stage="operation"), check("f1"), check("o2", stage="operation"), check("f2")]
    post = BarePost(tuple(checks)) if bare else checks
    operation, final = render_staged_post("OP", post)
    assert operation.index("__value_o1") < operation.index("__value_o2")
    assert final.index("__value_f1") < final.index("__value_f2")
    assert "__value_f1" not in operation and "__value_o1" not in final
    assert all(value.render() in (operation if value.stage == "operation" else final) for value in checks)
    assert len(checks) == 4 and [value.stage for value in checks] == ["operation", "final", "operation", "final"]


@pytest.mark.parametrize("container", [list, tuple, lambda values: BarePost(tuple(values))])
def test_legacy_post_api_refuses_operation_stage_instead_of_silently_delaying_it(container):
    post = container([check("op", stage="operation"), check("final")])
    with pytest.raises(EmitModelError, match="render_staged_post"):
        post_to_string("OP", post)
    if not isinstance(post, BarePost):
        with pytest.raises(EmitModelError, match="render_staged_post"):
            render_post("OP", post)


@pytest.mark.parametrize("stage", [None, "create", "post", "OPERATION", True, [], {}])
def test_unknown_stages_are_not_normalized_or_assigned_a_default(stage):
    with pytest.raises(EmitModelError, match="unknown stage"):
        check(stage=stage)


@pytest.mark.parametrize("stages", [("final", "final"), ("operation", "operation"), ("final", "operation")])
def test_duplicate_keys_refuse_even_across_distinct_stages(stages):
    checks = [check("same", stage=stage) for stage in stages]
    with pytest.raises(EmitModelError, match="duplicate obligation_key"):
        render_staged_post("OP", checks)
    with pytest.raises(EmitModelError, match="duplicate obligation_key"):
        BarePost(tuple(checks))


@pytest.mark.parametrize("empty", [[], ()])
def test_no_stage_can_legitimize_an_empty_unwitnessed_operation(empty):
    for renderer in (render_post, post_to_string, render_staged_post):
        with pytest.raises(EmitModelError, match="no witness checks"):
            renderer("OP", empty)
    with pytest.raises(EmitModelError, match="no witness checks"):
        BarePost(empty)


@pytest.mark.parametrize("malformed", [None, "__post.Add(\"fake\");", {"checks": []}, ["check"]])
def test_staged_renderer_does_not_open_a_raw_string_or_untyped_carrier_door(malformed):
    with pytest.raises(EmitModelError):
        render_staged_post("OP", malformed)


@pytest.mark.parametrize("verdict", ["", "// __post.Add(\"fake\");", 'var text = "__post.Add";'])
def test_operation_stage_keeps_the_existing_executable_verdict_requirement(verdict):
    with pytest.raises(EmitModelError):
        WitnessCheck("operation", "Read();", verdict, "missing executable verdict", stage="operation")


def test_operation_stage_keeps_minted_tolerance_provenance():
    tol = tolerance("create_wall", "endpoint_mm")
    with pytest.raises(EmitModelError):
        WitnessCheck("k", "", 'if (value > 5.0) __post.Add("k");', "k", tol=tol, stage="operation")
    value = WitnessCheck("k", "", f'if (value > {tol}) __post.Add("k");', "k", tol=tol, stage="operation")
    assert value.tol_key == "endpoint_mm"
    assert str(tol) in render_staged_post("OP", [value])[0]


def test_rendering_rechecks_stage_and_collection_if_a_frozen_object_was_tampered_with():
    value = check()
    object.__setattr__(value, "stage", "silently-final")
    with pytest.raises(EmitModelError, match="unknown stage"):
        render_staged_post("OP", [value])
    bare = BarePost((check(),))
    object.__setattr__(bare, "checks", ())
    with pytest.raises(EmitModelError, match="no witness checks"):
        render_staged_post("OP", bare)


def test_existing_final_only_level_emitter_keeps_its_exact_post_bytes():
    from kir.authoring import _EMITTERS
    _, _, post, _ = _EMITTERS["create_level"]({"op": "create_level", "id": "L", "elev_mm": 1200}, "2026", "kir:control")
    assert all(value.stage == "final" for value in post)
    legacy = post_to_string("L", post)
    assert render_staged_post("L", post) == ("", legacy)
