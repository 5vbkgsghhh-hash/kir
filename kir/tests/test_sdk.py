"""The language's Python surface must BE THE LANGUAGE, not a retelling
of it.

The SDK is dangerous in exactly one way: it looks like the language
but is not one. Write a builder by hand, and it lives only until the
first registry edit, after which it lies in silence: it promises a
field that no longer exists, or stays silent about a new one, and the
program compiles and then fails at the user's end. So what is checked
here is not "is it convenient" but two properties:

* the builders are BORN from `spec.OPS` — every registry op has a
  function, its signature matches `ParamSpec` by names and by
  mandatoriness, and a new op automatically gets both the builder and
  this test;
* the SDK has not grown a semantics of its own — it cannot express
  anything the registry doesn't have, checks nothing itself, and
  hides no refusal.

Plus two demo examples: they must compile offline, otherwise
"fiction" in the report is a picture, not a fact.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import pathlib

import pytest

from kir import macros, sdk, spec
from kir.compiler import DEFAULTABLE, MAX_OPS_PER_PROGRAM
from kir.diag import Diagnostic
from kir.tests.fixtures import GROUND_SNAPSHOT

#: 🔴 THE EXAMPLES MOVED AT THE SPLIT (28.08.2026). It used to be
#: `parents[3] / "tools" / "design" / "examples"` — an address in the
#: owner's tree; after 27.08 the count gives `/opt`, and the path
#: `/opt/tools/design/examples` does not exist. The examples
#: themselves live at the package root, in `examples/`.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"

WRITE_OPS = sorted(n for n, o in spec.OPS.items() if o.writes_model)
ALL_OPS = sorted(spec.OPS)


# ── builders are born from the registry ─────────────────────────────────────

@pytest.mark.parametrize("name", ALL_OPS)
def test_every_op_of_the_registry_has_a_builder(name):
    """Parametrized by the registry, not by a list: a new op brings
    its own test along, and "forgot to add it to the SDK" stops being
    a possible state."""
    fn = getattr(sdk, name, None)
    assert callable(fn), f"нет билдера для {name}"
    assert fn.op_spec is spec.OPS[name], "билдер держит ЧУЖУЮ спецификацию"


@pytest.mark.parametrize("name", WRITE_OPS)
def test_every_write_op_builds_its_own_op_dict(name):
    """For every writing op, the builder is called with its mandatory
    fields and returns a dict for exactly that op."""
    ospec = spec.OPS[name]
    args = {p.name: _sample(p) for p in ospec.params if p.required}
    out = getattr(sdk, name)(**args)
    assert out["op"] == name
    assert set(out) - {"op", "id"} <= {p.name for p in ospec.params}
    for p in ospec.params:
        if p.required:
            assert p.name in out, f"{name}: обязательное {p.name} потерялось"


@pytest.mark.parametrize("name", ALL_OPS)
def test_the_signature_never_drifts_from_the_paramspec(name):
    """A drift guard. Names and mandatoriness come from `ParamSpec`,
    and only from there: a mismatch here means the Python is
    promising a different language."""
    ospec = spec.OPS[name]
    sig = inspect.signature(getattr(sdk, name))
    got = [p for p in sig.parameters if p != "id"]
    # The registry interleaves mandatory and optional parameters
    # (`create_floor`: outline, holes, level, ...), while Python does
    # not allow a parameter without a default to follow one with a
    # default. So what is compared is not the overall order but the
    # order WITHIN each group: renaming, a field appearing, and a
    # field disappearing are all caught the same way, and no order
    # Python cannot express is required of it.
    want = ([p.name for p in ospec.params if p.required]
            + [p.name for p in ospec.params if not p.required])
    assert got == want, f"{name}: набор/порядок полей"
    assert "id" in sig.parameters, f"{name}: у опа обязан быть адрес"

    required = {p.name for p in ospec.params if p.required}
    for pname, param in sig.parameters.items():
        if pname == "id":
            continue
        has_default = param.default is not inspect.Parameter.empty
        assert has_default is (pname not in required), \
            f"{name}.{pname}: обязательность разошлась с реестром"


@pytest.mark.parametrize("name", ALL_OPS)
def test_registry_defaults_are_the_python_defaults(name):
    """"Defaults from ParamSpec" — literally: the value is taken from
    the registry at import time, so it has nowhere to drift apart
    from."""
    sig = inspect.signature(getattr(sdk, name))
    for p in spec.OPS[name].params:
        if p.required or p.default is None:
            continue
        assert sig.parameters[p.name].default == p.default, p.name


def test_there_are_exactly_as_many_builders_as_ops():
    assert set(sdk.builders()) == set(spec.OPS)
    assert sdk.op_names(writes=True) == WRITE_OPS


#: A plausible value based on the parameter's kind — the test needs
#: FORM, not a meaningful building; meaning is checked by the compiler
#: in the tests below.
_SAMPLES: dict = {
    "pt_xy": [0.0, 0.0], "pt_xyz": [0.0, 0.0, 0.0], "pt_view2d": [0.0, 0.0],
    # 🔴 A DIRECTION SAMPLE IS NOT ZERO, AND THIS IS NOT NITPICKING.
    # For a point, a zero sample is legal ([0,0,0] is the origin); for
    # a direction it means "there is no ray," and the op will REFUSE
    # it. A unit vector along X is used instead: the kind carries a
    # ray, its length means nothing, but zero is forbidden.
    "dir_xyz": [1.0, 0.0, 0.0],
    "pts": [[0.0, 0.0], [1000.0, 0.0]],
    "pts_list": [[[0.0, 0.0], [1000.0, 0.0]]],
    # `path` (wave/arch) — an OPEN polyline: two points are legal, no
    # area is required. That is exactly how it differs from "pts"
    # above.
    "path": [[0.0, 0.0], [3000.0, 0.0]],
    # `path3` (wave/mep-electrical) — the same open polyline, but with
    # Z: a flexible conduit run goes from the floor to the ceiling,
    # and a two-dimensional sample isn't enough for it.
    "path3": [[0.0, 0.0, 3000.0], [3000.0, 0.0, 2700.0]],
    "mm": 1000.0, "num": 1000.0, "deg": 0.0, "int": 1, "bool": True,
    # 🔴 ОБРАЗЕЦ ЛИЧНОСТИ — НАСТОЯЩЕЙ ФОРМЫ, А НЕ ЗАГЛУШКА (13.09.2026). Вид
    # приехал с волной N-2 (`fc6ef65`) и остался без образца — то есть этот тест
    # стоял красным, а `identity` молча получал бы строку "x" и проходил проверку
    # формы. UniqueId Ревита — это `8-4-4-4-12` плюс суффикс элемента, и
    # `authoring_validation._UNIQUE_ID_FORM` отвергает всё иное; `version_guid` —
    # 32 шестнадцатеричных знака. Заглушка здесь означала бы, что вид проверен,
    # когда он не проверен ни разу.
    "identity": {"unique_id": "7ff4b512-b299-4d75-8107-62effd492f45-00042fe4",
                 "version_guid": "7ff4b512b2994d75810762effd492f45"},
    # `enum_list` — НЕПУСТОЙ список из `choices` параметра. Пустой был бы отказом,
    # а не образцом: «ни одного рода следа» — это не запрос, это опечатка.
    "enum_list": ["walls"],
    "str": "имя", "str_long": "текст",
    "sel": "Этаж 1", "target": 42, "target_w": 42,
    # `sel_list` (wave/datums) — the plural of the `sel` kind. A
    # sample of TWO DIFFERENT names is deliberate: one name wouldn't
    # distinguish a list from a lone selector, and two IDENTICAL ones
    # would run into the law "a repeat within a set is a refusal"
    # (authoring_validation), and the test would be catching the
    # wrong thing.
    "sel_list": ["Этаж 1", "Этаж 2"],
    "refs_w": [42, 43], "targets_w": [42, 43], "value": "значение",
    "vec3_mm": [100.0, 0.0, 0.0],
    "arc": {"curve_type": "Arc", "center_mm": [0, 0, 0], "radius_mm": 5000.0,
            "x_axis": [1, 0, 0], "y_axis": [0, 1, 0]},
    # `spiral` (09.08) — the spiral flight of create_stairs. The
    # sample must be LEGAL as a whole: the radius exceeds the
    # half-width of any allowed flight (width_mm <= 5000 =>
    # radius > 2500), the angle is in (0, 360].
    "spiral": {"center_mm": [0.0, 0.0], "radius_mm": 3000.0,
               "start_angle_deg": 0.0, "included_angle_deg": 180.0,
               "clockwise": False},
    "kind_enum": "wall", "filters": {}, "fields": ["id"],
    "enum": None,                      # taken from the parameter's own choices
    "region": {"outer": {"shape": "poly",
                         "points_mm": [[0, 0], [1000, 0], [1000, 1000]]}},
    "member_ops": [{"op": "create_level", "id": "m1", "elev_mm": 0}],
    "placements": [[0, 0, 0]],
    # The wall assembly, outside to inside. The sample is
    # SINGLE-LAYER and WITHOUT a material on purpose: a material is
    # resolved by name in the target document, and a sample with an
    # invented name would legitimately be refused, pointing the fix
    # at the wrong place — exactly the trap this sample is taken from
    # the parameter's own bounds, rather than from the kind in
    # general, to avoid.
    "wall_layers": [{"width_mm": 100.0, "function": "Structure"}],
    "graph_nodes": [{"id": "n1", "xyz_mm": [0, 0, 0]}],
    "graph_segments": [{"from": "n1", "to": "n2"}],
    "slopes": [{"edge": 0, "angle_deg": 30}],
    # `mesh` (wave/shape) — a tetrahedron: the smallest mesh that
    # passes ALL of the form's laws (connected, no degenerate faces,
    # no dangling vertices). The sample must be legal as a whole: this
    # test takes it merely as a value shape, but neighboring tests run
    # it through the compiler.
    "mesh": {"vertices_mm": [[0.0, 0.0, 0.0], [3000.0, 0.0, 0.0],
                             [1500.0, 2600.0, 0.0], [1500.0, 900.0, 2400.0]],
             "triangles": [[0, 1, 2], [0, 1, 3], [1, 2, 3], [0, 2, 3]]},
    # `surface` (wave/surface) — THE SAMPLE MUST BE LEGAL, not merely
    # a shape. The kind's invariants are linked: the point count is
    # exactly count_u × count_v, each knot vector's length is exactly
    # degree + count + 1, and the vector is clamped. A bilinear 2×2
    # patch of degree 1×1 is the smallest legal surface; taking a 4×4
    # patch of degree 3×3 would mean paying with sixteen points for
    # the same thing.
    "surface": {"degree_u": 1, "degree_v": 1, "count_u": 2, "count_v": 2,
                "knots_u": [0.0, 0.0, 1.0, 1.0],
                "knots_v": [0.0, 0.0, 1.0, 1.0],
                "control_points_mm": [[0.0, 0.0, 0.0], [0.0, 3000.0, 0.0],
                                      [3000.0, 0.0, 0.0], [3000.0, 3000.0, 800.0]]},
    # `solid_parts` (wave/boolean) — the operands of a boolean. The
    # sample must be legal AS A WHOLE for the same reason as the mesh
    # above: neighboring tests run it through the compiler. A sphere
    # of radius 2400 at the center of a 4000 cube of height 4000
    # INTERSECTS it and is NOT nested inside it — that is, it passes
    # both preconditions (KIR-B101/KIR-B102). A degenerate sample
    # would be refused at the grounding step, and someone else's test
    # would read that refusal as a breakage of its own subject.
    "solid_parts": [{"shape": "sphere", "center_mm": [2000.0, 2000.0, 4000.0],
                     "radius_mm": 2400.0}],
    # `plane` (wave/plane, 21.08.2026) — a sketch plane. The sample
    # must be legal AS A WHOLE for the same reason as the mesh and
    # the boolean operands: neighboring tests run it through the
    # compiler. Here it's a vertical XZ plane (the face of a wall
    # running along +X): normal -Y, the +u axis along world +X,
    # orthogonality exact. A horizontal sample would be DEGENERATE:
    # it coincides with today's behavior without a plane, and a test
    # on it would be green regardless of either half's value.
    "plane": {"origin_mm": [3000.0, 5000.0, 900.0],
              "normal": [0.0, -1.0, 0.0], "x_dir": [1.0, 0.0, 0.0]},
    # `pts_xyz` (wave/site) — a terrain point cloud. The sample must
    # be legal AS A WHOLE, just like the mesh above: neighboring
    # tests run it through the compiler. Hence four points here, no
    # pair of which coincides in plan (terrain has exactly one
    # elevation at any plan point) and which do not lie on one line
    # (a surface of zero area is a typed refusal).
    "pts_xyz": [[0.0, 0.0, 0.0], [10000.0, 0.0, 500.0],
                [10000.0, 8000.0, 900.0], [0.0, 8000.0, 200.0]],
}


#: Kinds whose sample is a NUMBER and therefore must fit within THIS
#: particular parameter's bounds, not merely have the right type.
_NUMERIC_KINDS = ("mm", "num", "int", "deg")


def _sample(p: spec.ParamSpec):
    """A value sample for THIS SPECIFIC parameter — legal as a whole,
    not merely by kind.

    Found by the solid wave on 09.08: the `num` kind's sample is
    1000.0, while `sweep_deg` lives in 1..360, and the corpus was
    getting a program the compiler legitimately refused (KIR-T002).
    The instrument, meanwhile, reported not "the operator has narrow
    bounds" but "the op does not build JSON the planner accepts,"
    that is, it pointed the fix at the WRONG PLACE. Cutting off at
    the parameter's own bounds fixes this for every future op, not
    just for one.
    """
    if p.kind == "enum":
        return (p.choices or ("x",))[0]
    value = _SAMPLES[p.kind]
    if p.kind in _NUMERIC_KINDS and None not in (p.min_val, p.max_val):
        clamped = min(max(float(value), float(p.min_val)), float(p.max_val))
        return int(clamped) if p.kind == "int" else clamped
    return value


def test_every_param_kind_of_the_registry_is_classified_by_the_sdk():
    """Found by this test on 28.07: a parallel wave brought in
    `move_elements` with the kinds `targets_w`/`vec3_mm`, and
    `targets` — a list of selectors — would have silently slipped
    past the coercion. An unknown kind breaks nothing (it passes
    through as is), and exactly for that reason it cannot be left
    unnoticed."""
    assert sdk.unclassified_kinds() == []


def test_every_param_kind_of_the_registry_has_a_sample():
    """Otherwise a new parameter kind would quietly get the string
    "x" and pass the form check, checking nothing at all: a test that
    cannot go unnoticed when the language is extended is better than
    a test that fools itself."""
    kinds = {p.kind for o in spec.OPS.values() for p in o.params}
    assert not sorted(kinds - set(_SAMPLES)), "новый вид параметра без образца"


# ── no new semantics ─────────────────────────────────────────────────────────

def test_the_sdk_cannot_name_an_op_the_registry_does_not_have():
    assert not hasattr(sdk, "create_teleporter")
    with pytest.raises(AttributeError):
        sdk.create_teleporter()  # noqa: B018


def test_an_unknown_field_is_refused_by_the_signature():
    """The refusal comes from the registry (via the signature), not
    from a check the SDK would have grown for itself."""
    with pytest.raises(TypeError):
        sdk.create_wall([0, 0], [1000, 0], "Этаж 1", nonexistent_field=1)


def test_a_missing_required_field_is_refused_by_the_signature():
    with pytest.raises(TypeError):
        sdk.create_wall([0, 0], [1000, 0])


def test_the_sdk_validates_nothing_that_the_compiler_validates():
    """A deliberately invalid program must reach the compiler and get
    ITS diagnostic. An SDK that refused earlier, in its own way, would
    be a second dialect."""
    p = sdk.program()
    p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1", height_mm=-5))
    out = p.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    assert out.ok is False
    assert out.diagnostics and isinstance(out.diagnostics[0], Diagnostic)
    assert out.diagnostics[0].code.startswith("KIR-")


def test_diagnostics_come_back_as_objects_not_text():
    """A script that fixes itself reads `code` and `candidates`, not
    parses the message."""
    p = sdk.program()
    p.add(sdk.create_wall([0, 0], [1000, 0], "нет такого уровня"))
    out = p.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    assert out.ok is False
    d = out.diagnostics[0]
    assert hasattr(d, "code") and hasattr(d, "candidates")


# ── ergonomics without semantics ─────────────────────────────────────────────

def test_selectors_accept_what_python_has_at_hand():
    assert sdk.sel("Этаж 1") == {"by": "name", "value": "Этаж 1"}
    assert sdk.sel(1679) == {"by": "element_id", "value": 1679}
    assert sdk.sel(sdk.Ref("L1")) == {"by": "ref", "value": "L1"}
    assert sdk.sel(sdk.DEFAULT) == {"by": "default"}
    assert sdk.sel({"by": "name", "value": "x"}) == {"by": "name", "value": "x"}
    assert sdk.sel("Стена", kind="wall")["kind"] == "wall"
    with pytest.raises(TypeError):
        sdk.sel(True)


def test_a_ref_from_add_wires_ops_together():
    """A door addresses its wall by a reference to the neighboring op
    — that is exactly the benefit of `add` returning a `Ref` instead of
    forcing you to hold an id in your head."""
    p = sdk.program()
    wall = p.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250"))
    door = p.add(sdk.create_door(host=wall, offset_mm=3000,
                                 symbol="Дверь 900x2100"))
    assert isinstance(wall, sdk.Ref) and isinstance(door, sdk.Ref)
    assert p.ops[1]["host"] == {"by": "ref", "value": wall.id}
    assert p.compile(version="2023", snapshot=GROUND_SNAPSHOT).ok


def test_numpy_values_survive_into_json():
    """Without this the connector doesn't work at all: the whole point
    is that coordinates are computed with numpy, and `np.float64` does
    not serialize."""
    np = pytest.importorskip("numpy")
    p = sdk.program()
    p.add(sdk.create_column(xy=np.array([1234.5, 6789.0]), level="Этаж 1"))
    text = p.to_json()
    assert "1234.5" in text
    assert json.loads(text)["ops"][0]["xy"] == [1234.5, 6789.0]


def test_auto_ids_are_deterministic_and_unique():
    p = sdk.program()
    for _ in range(3):
        p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1"))
    ids = [o["id"] for o in p.ops]
    assert ids == ["wall1", "wall2", "wall3"]
    assert len(set(ids)) == 3


def test_an_explicit_id_is_never_overwritten():
    p = sdk.program()
    p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1", id="мой"))
    assert p.ops[0]["id"] == "мой"


def test_omitted_optional_fields_do_not_appear():
    out = sdk.create_wall([0, 0], [1000, 0], "Этаж 1", type=sdk.OMIT)
    assert "type" not in out
    assert "arc" not in out


def test_by_macro_omits_a_field_the_macro_owns():
    """A seam between two correct rules: the registry requires
    `level`, `macros.py` forbids it inside `stack.floor`. The Python
    must let you say "the macro will assign this."""
    out = sdk.create_column(xy=[0, 0], level=sdk.BY_MACRO)
    assert "level" not in out


# ── the program ───────────────────────────────────────────────────────────────

def test_to_dict_is_exactly_the_compilers_json():
    p = sdk.program(intent="проба", defaults={"level": "Этаж 1"})
    p.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250"))
    d = p.to_dict()
    assert d["ir_version"] == spec.IR_VERSION
    assert set(d) <= {"ir_version", "intent", "allow_destructive", "ops", "defaults"}
    assert d["defaults"] == {"level": {"by": "name", "value": "Этаж 1"}}
    assert p.compile(version="2023", snapshot=GROUND_SNAPSHOT).ok


def test_envelope_defaults_only_carry_what_the_compiler_accepts():
    """The SDK does not extend the envelope: the list of defaults
    belongs to the compiler."""
    p = sdk.program(defaults={"nonsense": "x"})
    p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1"))
    out = p.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    assert out.ok is False
    assert any(d.field_name == "defaults" for d in out.diagnostics)
    assert set(DEFAULTABLE) == {"level", "symbol", "type", "top_level"}


def test_stats_tell_written_expanded_and_elements_apart():
    """Three numbers, not one: in one number, the very thing the
    language exists for dissolves."""
    p = sdk.program()
    with p.stack(levels=10, h_mm=3000) as floor:
        floor.add(sdk.create_column(xy=[0, 0], level=sdk.BY_MACRO,
                                    symbol="К 300x300"))
    st = p.stats()
    assert st["ops_written"] == 1
    assert st["ops_expanded"] == 20        # 10 levels + 10 columns
    assert st["elements"] == 10            # a level is not a model element


def test_a_program_is_one_program_not_a_whole_building():
    """A batch of programs is a property of the language, not an SDK
    shortcoming: 20 author ops before expansion, and the SDK does not
    hide this."""
    p = sdk.program()
    for _ in range(MAX_OPS_PER_PROGRAM + 1):
        p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1"))
    out = p.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    assert out.ok is False
    assert any(d.code == "KIR-L001" for d in out.diagnostics)


def test_compile_all_covers_every_shipped_version():
    p = sdk.program()
    p.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250"))
    got = p.compile_all(snapshot=GROUND_SNAPSHOT)
    assert set(got) == set(spec.REVIT_VERSIONS)
    assert all(out.ok for out in got.values())


def test_grid_array_reaches_the_macro_layer():
    p = sdk.program()
    p.grid_array(nx=4, ny=3, dx_mm=6000, dy_mm=4500, prefix_y="А")
    assert p.stats()["ops_expanded"] == 7
    assert p.compile(version="2023", snapshot=GROUND_SNAPSHOT).ok


def test_the_macro_field_names_do_not_drift():
    """Macros do not live in `spec.OPS`, so their fields are named
    here by hand — and exactly for that reason a guard is needed: the
    full set of fields must pass through expansion, rather than get a
    KIR-M001 "unknown macro field."""
    p = sdk.program()
    with p.stack(levels=2, h_mm=3000, base_elev_mm=0, name_prefix="Э",
                 transform=sdk.transform(scale_xy_top=[0.9, 0.9],
                                         twist_deg_total=10,
                                         offset_mm_top=[100, 0],
                                         pivot_mm=[0, 0])) as floor:
        floor.add(sdk.create_column(xy=[0, 0], level=sdk.BY_MACRO))
    p.grid_array(nx=2, ny=2, dx_mm=6000, dy_mm=6000, origin_mm=[0, 0],
                 margin_mm=1000, prefix_x="", prefix_y="А")
    expanded = macros.expand(list(p.ops))          # must not raise KirRefusal
    assert len(expanded) == 8


def test_the_stack_floor_is_a_separate_sink():
    """A floor cannot be accidentally passed off as a program op, and
    vice versa."""
    p = sdk.program()
    with p.stack(levels=2, h_mm=3000) as floor:
        floor.add(sdk.create_column(xy=[0, 0], level=sdk.BY_MACRO))
    p.add(sdk.create_level(elev_mm=9000, name="Тех"))
    assert len(p.ops) == 2
    assert p.ops[0]["op"] == "stack" and len(p.ops[0]["floor"]) == 1


# ── demo examples compile offline ────────────────────────────────────────────

def _load(name: str):
    spec_ = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", ["tower_numpy", "contour_shapely"])
def test_the_examples_compile_offline_on_every_version(name):
    """"Fiction" in the report must be a fact: the example builds
    programs, and every one of them is accepted by the compiler on all
    six versions, without a network and without Revit."""
    pytest.importorskip("numpy")
    if name == "contour_shapely":
        pytest.importorskip("shapely")
    mod = _load(name)
    programs = mod.build(mod.slab_outline()[0]) if name == "contour_shapely" \
        else mod.build()
    assert programs
    for p in programs:
        for version, out in p.compile_all(snapshot=GROUND_SNAPSHOT).items():
            assert out.ok, (name, version,
                            [d.code for d in out.diagnostics][:3])


@pytest.mark.parametrize("name", ["tower_numpy", "contour_shapely"])
def test_the_examples_stay_within_a_hundred_lines(name):
    text = (EXAMPLES / f"{name}.py").read_text("utf-8")
    assert len(text.splitlines()) <= 100


def test_the_tower_says_more_with_less():
    """The connector's point is in the ratio: the number of ops
    written must be MUCH SMALLER than the number of elements. If the
    ratio collapses, the example stops being an example."""
    mod = _load("tower_numpy")
    st = [p.stats() for p in mod.build()]
    written = sum(x["ops_written"] for x in st)
    elements = sum(x["elements"] for x in st)
    assert elements >= 50 * written, (written, elements)


def test_a_built_program_is_byte_identical_to_the_hand_written_json():
    """The strongest form of "no new semantics": the SDK produces
    EXACTLY the JSON one would write by hand — not its own wrapper,
    not its own order, not its own fields."""
    p = sdk.program(intent="стена")
    p.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250",
                          id="w1"))
    # 🔴 THE REGISTRY DEFAULT DOES NOT APPEAR HERE, AND THIS IS A
    # TIGHTENING, NOT A RELAXATION (02.09.2026). The line
    # `"height_mm": 3000.0` used to be here, pinning the old form. But
    # something written BY HAND carries no default — the course
    # forbids this in so many words ("Do not write in what is already
    # the default") — and writing in a default changes `plan_digest`
    # and erases the field's provenance (measurement 03.08, argument
    # at `registry_base.RegistryDefault`). That is, the previous
    # expected JSON was NOT "what one would write by hand," and the
    # test's own assertion contradicted its own docstring.
    assert p.to_dict() == {
        "ir_version": "1.0",
        "intent": "стена",
        "ops": [{"op": "create_wall", "id": "w1",
                 "p0_mm": [0, 0], "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "name", "value": "Кирпич 250"}}],
    }


def test_the_registry_default_is_shown_not_written_and_the_building_is_one():
    """The registry default is SHOWN in the signature and NOT WRITTEN
    INTO the JSON — and the building comes out the same either way.

    🔴 THE TEST WAS REWRITTEN ON 02.09.2026, AND THE PREVIOUS ONE WAS
    PINNING A DEFECT. It was called
    "...is_emitted_and_means_the_same_thing" and required the SDK to
    WRITE `height_mm` INTO the op. The second half of the name is
    wrong: the C# really is one and the same — the building is one —
    but the field's provenance and `plan_digest` are DIFFERENT, and
    every piece of evidence that follows hangs off the plan's
    signature. The 03.08 measurement is recorded at
    `registry_base.RegistryDefault`:

        omitted  -> FieldOrigin.REGISTRY_DEFAULT
        written  -> FieldOrigin.EXPLICIT

    The script door (`dsl.py`) had held this law since 03.08, while
    the `sdk.py` builders violated it, because the sentinel that
    carried it lived in `dsl` and was unreachable to the second front
    by construction (`dsl` imports `sdk`). The carrier has moved into
    the registry; what is pinned here is the PROPERTY, not the form.
    """
    из_sdk = sdk.program()
    из_sdk.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250"))
    руками = sdk.program()
    руками.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250",
                               height_mm=spec.OPS["create_wall"].params[3].default))

    # 1. NOT WRITTEN IN: an omission stays an omission.
    assert "height_mm" not in из_sdk.ops[0]
    # 2. SHOWN: the default is visible in the signature, there is
    # something for the author to read.
    import inspect
    показано = inspect.signature(sdk.create_wall).parameters["height_mm"].default
    assert показано == spec.OPS["create_wall"].params[3].default
    # 3. ONE BUILDING: the C# matches byte-for-byte.
    a = из_sdk.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    b = руками.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    assert a.ok and b.ok and a.csharp == b.csharp
    # 4. BUT THE EVIDENCE DIFFERS — exactly the quantity all of this
    # is for.
    assert (a.planned.ops[0].provenance.origin_for("height_mm")
            != b.planned.ops[0].provenance.origin_for("height_mm"))


def test_a_list_of_selectors_is_coerced_element_by_element():
    """`move_elements.targets` is a list of addresses; the Python must
    accept in it the same things as in a lone selector."""
    out = sdk.move_elements(targets=[42, sdk.Ref("w1")], delta_mm=[100, 0, 0])
    assert out["targets"] == [{"by": "element_id", "value": 42},
                              {"by": "ref", "value": "w1"}]
