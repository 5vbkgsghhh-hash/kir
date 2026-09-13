"""THE KIND OF A NESTED VALUE IS ASKED, NOT INFERRED FROM ITS APPEARANCE.

🔴 ONE CLASS, FOUR CARRIERS, FIVE CORRUPTIONS. Before 03.09.2026, the
role of a nested value was being guessed by shape in FOUR spots of
`program_source`:

    `_round_mm`   "a number inside a millimeter composite is itself
                   millimeters"
    `_shift`      "a list of 2-3 numbers is a world point"
    `_expr`       a reverse shift, repeating `_shift`'s guess
    `_origin`     a local frame's angle, sought by the same guess

Not one of them was asking the field's declared kind. This is canon form
7 ("convention is not authority"), and it bit THREE TIMES in a row
across three spellings: `normal`/`x_dir` on a plane (21.08) -> `ref_dir`
as a bare parameter (21.08) -> `x_axis`/`y_axis` inside an arc. The
`FREE_KEYS` guard was written against the FIRST spelling and stayed
silent by construction — form 54.

WHAT IS PINNED HERE, AND WHAT IT COST (a corpus of 56 decompiles, 82,451
operations, 320 with a composite value; measured 03.09.2026):

    arc.end_angle_rad     299 ops  -1.5707963267948744 -> -2.0  (-90° -> -114.6°)
    arc.start_angle_rad   287 ops   3.4732052114696415 ->  3.0  (199.0° -> 171.9°)
    arc.x_axis/y_axis     299 ops  the shift was subtracting the
                                    frame's origin from the DIRECTION
    arc.x_axis/y_axis     266 ops  rounding was zeroing out an axis
                                    component
    region.rotation_deg     0 ops  <- the NAMED defect F-090 was NOT
                                       encountered in the corpus

The last row is not a trifle: the class was named after its RAREST
member, while the most frequent one (an arc's radians on `create_wall`)
was entirely absent from the registry.

🔴 WHAT THIS FILE DOES NOT PROVE. It stands on inputs assembled by PROD
CODE (`contour.SHAPE_FORMS`, the canonical arc form from
`authoring_validation`), not on a live Revit: "prints correctly" is not
"builds in the model."
"""
from __future__ import annotations

import math

import pytest

from kir.decompile import program_source as ps

# ---------------------------------------------------------------------------
# INPUTS ARE BUILT BY PROD CODE, NOT MADE UP
# ---------------------------------------------------------------------------
#
# 🔴 THE REPRO FROM THE REGISTRY WAS UNSOUND, AND THAT IS WORTH SAYING
# HERE. Rows F-090 and F-091 were reproduced with the input
# `{"kind": "rect", "origin_mm": [...]}` — a shape that does NOT EXIST in
# the language: `contour.SHAPE_FORMS` declares the discriminator `shape`
# and the field `origin`, and `contour._validate_shape` rejects both a
# foreign discriminator and extra fields. The conclusion held up (the
# defect is alive on a legal input too), the grounds were bad. So the
# shape is taken FROM THE SHAPE REGISTRY, rather than rewritten here.

#: A non-zero frame. It needs to be asymmetric: at dx == dy, "carried
#: over correctly" and "everything shifted" are indistinguishable.
DX, DY = 1000.0, 500.0


def _rect(origin, size, rotation_deg):
    """A rectangular region of EXACTLY the shape the shape registry declares."""

    from kir import contour

    slots = {slot.name for slot in contour.SHAPE_FORMS["rect"]}
    assert slots == {"origin", "size_mm", "rotation_deg"}, (
        "реестр форм переехал: %s. Проба обязана следовать за ним, а не "
        "нести свою копию формы" % sorted(slots))
    value = {"shape": "rect", "origin": list(origin),
             "size_mm": list(size), "rotation_deg": rotation_deg}
    assert set(value) <= contour.shape_fields("rect")
    return value


def _canonical_arc():
    """A canonical arc of EXACTLY the composition the direct path requires.

    The composition is asked of `authoring_validation._validate_arc` —
    there it is declared as the `required` set, and that is the
    authority. The comment in `MM_KINDS`, which introduced the `arc`
    kind on 21.08, listed the composition `{center_mm, radius_mm, bulge,
    dir}` — a shape that does not exist in this tree, and that is
    exactly why no one protected `x_axis`/`y_axis`.
    """

    return {
        "curve_type": "Arc",
        "center_mm": [4500.0, 2000.0, 0.0],
        "radius_mm": 2500.0,
        "x_axis": [1.0, 0.0, 0.0],
        "y_axis": [0.0, 1.0, 0.0],
        "start_angle_rad": math.pi / 4,        # 45°
        "end_angle_rad": 3 * math.pi / 4,      # 135°
    }


def _floor(oid, origin, size, rotation_deg=0):
    return {"op": "create_floor_by_contour", "id": oid,
            "contour": _rect(origin, size, rotation_deg),
            "level": {"by": "element_id", "value": 1},
            "type": {"by": "element_id", "value": 2}}


# ---------------------------------------------------------------------------
# THE PROBE'S POWER AND ASYMMETRY ARE NAMED, NOT ASSUMED
# ---------------------------------------------------------------------------

def test_проба_не_вырождена_и_это_сказано_числом() -> None:
    """🔴 A CONTROL ON A DEGENERATE INPUT IS GREEN BY CONSTRUCTION (canon,
    form 18).

    For `_shift` there are THREE such degeneracies, and each one alone
    makes the probe meaningless:

      * a zero frame   — `_shift` returns on its first line, having
                          shifted nothing;
      * a square       — `size_mm == [a, a]` cannot tell "shifted along
                          X" from "shifted along Y," and `dx == dy`
                          cannot tell either apart from "not shifted";
      * a zero angle   — `rotation_deg == 0` rounds to 0 under ANY rule,
                          meaning F-090 is invisible on it.

    Named here are the values by which the probe avoids them. The
    assertion stands BEFORE the rest deliberately: if it fails, every
    green below it is a lie.
    """

    assert (DX, DY) != (0, 0), "нулевая рамка: `_shift` не дойдёт до тела"
    assert DX != DY, "dx == dy не отличит ось X от оси Y"

    rect = _rect([5000, 6000], [4000, 3000], 30.25)
    w, h = rect["size_mm"]
    assert w != h, "квадрат: перенос по X неотличим от переноса по Y"
    assert rect["rotation_deg"] % 1 != 0, (
        "целый угол округляется в себя любым правилом — F-090 на нём слеп")
    assert rect["origin"] != [0, 0], "нулевое начало сокращает сдвиг"

    arc = _canonical_arc()
    assert arc["start_angle_rad"] % 1 != 0 and arc["end_angle_rad"] % 1 != 0, (
        "целые радианы переживают округление в миллиметры — проба слепа")


# ---------------------------------------------------------------------------
# FIVE CORRUPTIONS OF ONE CLASS
# ---------------------------------------------------------------------------

def test_угол_области_переживает_округление() -> None:
    """F-090, the first half. `rotation_deg` is degrees, not millimeters."""

    kinds = ps.param_kinds()
    assert kinds[("create_floor_by_contour", "contour")] == "region", (
        "вид спрошен у реестра, а не предположен: без `region` проба ничего "
        "не округляет и зелена по построению")

    rect = _rect([5000, 6000], [4000, 3000], 30.25)
    got = ps._round_by_kind("create_floor_by_contour", "contour", rect, kinds)
    assert got["rotation_deg"] == 30.25, (
        "безразмерный угол округлён миллиметровым зерном: %r" % (got,))
    # And millimeters inside the same region MUST still round —
    # otherwise the green is bought by the rule having stopped working
    # at all.
    dirty = ps._round_by_kind(
        "create_floor_by_contour", "contour",
        _rect([5000.4, 6000.6], [4000.4, 3000.6], 30.25), kinds)
    assert dirty["origin"] == [5000.0, 6001.0], dirty
    assert dirty["size_mm"] == [4000.0, 3001.0], dirty


def test_размер_области_не_уезжает_в_локальную_рамку() -> None:
    """F-091. A gauge is millimeters, but NOT a position: the frame does not touch it."""

    rect = _rect([5000, 6000], [4000, 3000], 30.25)
    got = ps._shift(rect, DX, DY, "region")
    assert got["size_mm"] == [4000, 3000], (
        "перенос единицы изменил ГАБАРИТ, а не только место: %r" % (got,))
    assert got["origin"] == [5000 - DX, 6000 - DY], (
        "положение обязано сдвинуться — иначе зелёный куплен тем, что сдвиг "
        "выключился целиком: %r" % (got,))


def test_углы_дуги_в_радианах_не_округляются_миллиметром() -> None:
    """🔴 THE MOST FREQUENT MEMBER OF THE CLASS, and the registry had no
    row for it.

    A one-millimeter grain applied to radians is 57.3° — not rounding,
    but corruption. Across the corpus, 299 of 320 composite `create_wall`
    operations were touched.
    """

    kinds = ps.param_kinds()
    assert kinds[("create_wall", "arc")] == "arc"

    arc = _canonical_arc()
    got = ps._round_mm(arc, ps.COMPOUND)
    assert got["start_angle_rad"] == pytest.approx(math.pi / 4), (
        "π/4 (45°) округлён как миллиметры: %r" % (got["start_angle_rad"],))
    assert got["end_angle_rad"] == pytest.approx(3 * math.pi / 4), (
        "3π/4 (135°) округлён как миллиметры: %r" % (got["end_angle_rad"],))
    # The radius is REAL millimeters and must round.
    assert ps._round_mm(dict(arc, radius_mm=2500.4),
                        ps.COMPOUND)["radius_mm"] == 2500.0


def test_оси_дуги_не_получают_начало_локальной_рамки() -> None:
    """🔴 THE THIRD BITE OF ONE CLASS IN A THIRD SPELLING.

    `x_axis`/`y_axis` are unit directions. Subtracting the frame's
    origin from a direction means rotating the arc by an amount that
    depends on where the apartment happens to stand. The three numbers
    remain three numbers throughout, and nothing crashes.
    """

    arc = _canonical_arc()
    got = ps._shift(arc, DX, DY, "arc")
    assert got["x_axis"] == [1.0, 0.0, 0.0], (
        "направление получило начало рамки: %r" % (got["x_axis"],))
    assert got["y_axis"] == [0.0, 1.0, 0.0], (
        "направление получило начало рамки: %r" % (got["y_axis"],))
    assert got["radius_mm"] == 2500.0, "радиус — величина, а не положение"
    # The arc's center is a REAL world point, and it must shift.
    assert got["center_mm"] == [4500.0 - DX, 2000.0 - DY, 0.0], (
        "центр не сдвинулся — сдвиг выключился целиком: %r" % (got,))


def test_индексы_треугольников_не_считаются_точкой() -> None:
    """A mesh's topology is VERTEX INDICES, not coordinates."""

    mesh = {"vertices_mm": [[0.0, 0.0, 0.0], [3000.0, 0.0, 0.0],
                            [1500.0, 2600.0, 0.0]],
            "triangles": [[0, 1, 2]]}
    got = ps._shift(mesh, DX, DY, "mesh")
    assert got["triangles"] == [[0, 1, 2]], (
        "индексы вершин сдвинуты как мировая точка: %r" % (got["triangles"],))
    assert got["vertices_mm"][1] == [3000.0 - DX, -DY, 0.0], (
        "вершины обязаны сдвинуться: %r" % (got["vertices_mm"],))
    assert ps._round_mm(mesh, ps.COMPOUND)["triangles"] == [[0, 1, 2]], (
        "индексы вершин стали числами с плавающей точкой")


# ---------------------------------------------------------------------------
# THE FOURTH SPOT: THE FRAME'S ORIGIN
# ---------------------------------------------------------------------------

def test_начало_локальной_рамки_берётся_из_положения_а_не_из_габарита() -> None:
    """🔴 A THIRD CARRIER THAT IS IN NO ROW OF THE REGISTRY AT ALL.

    `_Printer._origin` was looking for a unit's minimal corner by the
    same "a list of 2-3 numbers is a point" guess, meaning it also
    treated `size_mm` as a candidate. Two slabs, (5000,6000)+[4000,3000]
    and (12000,9000)+[2000,7000], gave a frame origin of (2000, 3000) —
    a minimum over GAUGES. The frame was being taken from the size.
    """

    ops = [_floor("f1", [5000, 6000], [4000, 3000], 30.25),
           _floor("f2", [12000, 9000], [2000, 7000])]
    unit = ps.SourceUnit(kind="apartment", label="кв1",
                         op_ids=frozenset({"f1", "f2"}))
    text = ps.render_source([{"ops": ops}], level="L1",
                            units=[unit]).parts[0].text
    assert "unit_кв1(dx=5000, dy=6000)" in text, (
        "начало рамки — минимальный УГОЛ единицы (5000, 6000), а не минимум "
        "по габаритам:\n%s" % text)


def test_перенос_единицы_меняет_только_её_место() -> None:
    """🔴 THE VERY PROPERTY THE LOCAL FRAME WAS INTRODUCED FOR.

    A round-trip run does NOT catch this: it calls a unit with the same
    `dx`/`dy`, and the error CANCELS OUT (form 18 — green with no act of
    discrimination). So the unit is called at a DIFFERENT spot, and
    this is the only probe where the discrepancy can show up at all.
    """

    ops = [_floor("f1", [5000, 6000], [4000, 3000], 30.25),
           _floor("f2", [12000, 9000], [2000, 7000])]
    unit = ps.SourceUnit(kind="apartment", label="кв1",
                         op_ids=frozenset({"f1", "f2"}))
    text = ps.render_source([{"ops": ops}], level="L1",
                            units=[unit]).parts[0].text

    here = "unit_кв1(dx=5000, dy=6000)"
    assert here in text, text
    got = ps.execute_source(text.replace(here, "unit_кв1(dx=0, dy=0)"))
    assert not isinstance(got, str), got

    by_id = {op["id"]: op["contour"] for op in got["ops"]}
    assert by_id["f1"]["size_mm"] == [4000, 3000], (
        "перенос изменил габарит: %r" % (by_id["f1"],))
    assert by_id["f2"]["size_mm"] == [2000, 7000], (
        "перенос изменил габарит: %r" % (by_id["f2"],))
    assert by_id["f1"]["rotation_deg"] == 30.25, "перенос изменил угол"
    # And the PLACE must move by exactly the captured frame — otherwise
    # the probe is green because nothing changed at all.
    assert by_id["f1"]["origin"] == [0, 0], by_id["f1"]
    assert by_id["f2"]["origin"] == [7000, 3000], by_id["f2"]


# ---------------------------------------------------------------------------
# THE ROUND-TRIP ORACLE MUST BE ABLE TO SAY "NO"
# ---------------------------------------------------------------------------

def test_оракул_круга_умеет_сказать_нет_про_угол() -> None:
    """🔴 THE SECOND HALF OF F-090, AND IT COSTS MORE THAN THE FIRST.

    `canonical_op` canonicalizes BOTH sides of the comparison with the
    same `_round_by_kind` used for printing. As long as the rule was
    rounding `rotation_deg` to whole millimeters, a swapped angle was
    mutating BOTH sides at once, and the oracle could not turn red BY
    CONSTRUCTION — this is form 48 in its pure shape: a fixture made of
    a matched pair is green for any value of either side.

    Measured BEFORE the fix (03.09.2026), the blind band of ±0.5°:

        30.25 -> 30.0  matches      30.25 -> 31.0  sees it
        30.25 -> 30.4  matches      30.25 -> 45.0  sees it
        30.25 -> 30.5  matches

    Pinned here: the band is gone.
    """

    kinds = ps.param_kinds()
    src = [_floor("f1", [5000, 6000], [4000, 3000], 30.25)]

    assert ps.compare_ops(src, src, kinds).ok, (
        "оракул не сходится сам с собой — красный ниже ничего не значил бы")

    for bad in (30.0, 30.4, 30.5):
        got = [_floor("f1", [5000, 6000], [4000, 3000], bad)]
        verdict = ps.compare_ops(src, got, kinds)
        assert not verdict.ok, (
            "оракул круга СЛЕП к подмене угла 30.25 -> %s: обе стороны "
            "канонизируются одним неверным правилом" % bad)


def test_оракул_круга_умеет_сказать_нет_про_радианы() -> None:
    """The same blindness on an arc, and there it cost 299 operations of the corpus."""

    kinds = ps.param_kinds()

    def wall(arc):
        return {"op": "create_wall", "id": "w1",
                "p0_mm": [0, 0], "p1_mm": [5000, 0], "arc": arc,
                "height_mm": 3000,
                "level": {"by": "element_id", "value": 1},
                "type": {"by": "element_id", "value": 2}}

    src = [wall(_canonical_arc())]
    assert ps.compare_ops(src, src, kinds).ok

    # A swap the old rule was making ON ITS OWN: π/4 -> 1.0 rad.
    got = [wall(dict(_canonical_arc(), start_angle_rad=1.0))]
    assert not ps.compare_ops(src, got, kinds).ok, (
        "оракул слеп к подмене начального угла дуги на 12.3°")
    # And an axis zeroed out by rounding.
    got = [wall(dict(_canonical_arc(), x_axis=[0.0, 0.0, 0.0]))]
    assert not ps.compare_ops(src, got, kinds).ok, (
        "оракул слеп к обнулённой оси дуги")


# ---------------------------------------------------------------------------
# THE DENOMINATOR IS DERIVED, NOT HAND-WRITTEN
# ---------------------------------------------------------------------------

def test_закон_объявлен_для_каждого_ключа_из_порождённой_схемы() -> None:
    """🔴 THIS IS THE ACTUAL CURE FOR FORM 54, NOT JUST ANOTHER LIST.

    A guard written against a CLASS pins down the appearance of the
    FIRST case: `FREE_KEYS` knew `normal`/`x_dir` and did not know
    `x_axis`/`y_axis`, because the second bite arrived in a different
    spelling. The cure is not padding the list, but making the
    DENOMINATOR stop being hand-written.

    Here it is taken from the language's GENERATED schema
    (`schema_gen.program_schema()`) — the same artifact the model sees.
    A new nested key will appear in the schema on its own, and will
    turn red HERE, rather than being guessed at from the value's
    appearance.

    What remains HAND-WRITTEN is only the ROLE ("position" versus
    "magnitude"): it cannot be derived from the schema, where both are
    simply "an array of two numbers." Hand-written ON TOP OF a DERIVED
    denominator is honest; hand-written on top of hand-written is not.
    """

    from kir import schema_gen

    schema = schema_gen.program_schema()
    op_props: dict[str, dict] = {}

    def find_ops(node) -> None:
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict) and isinstance(props.get("op"), dict) \
                    and "const" in props["op"]:
                op_props[props["op"]["const"]] = props
            for value in node.values():
                find_ops(value)
        elif isinstance(node, list):
            for item in node:
                find_ops(item)

    find_ops(schema)
    assert op_props, "схема не разобрана — знаменатель не построен"

    def prop_names(node, acc: set) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                acc |= set(node["properties"])
            for value in node.values():
                prop_names(value, acc)
        elif isinstance(node, list):
            for item in node:
                prop_names(item, acc)

    reachable: set[str] = set()
    for (op_name, param), kind in ps.param_kinds().items():
        if kind not in (ps.MM_KINDS | ps.DEG_KINDS):
            continue
        sub = op_props.get(op_name, {}).get(param)
        if sub is not None:
            prop_names(sub, reachable)

    assert len(reachable) >= 30, (
        "знаменатель подозрительно мал (%d): скорее всего разбор схемы "
        "промахнулся, и зелёный ничего не значит" % len(reachable))
    missing = sorted(k for k in reachable if ps.key_law(k) is None)
    assert not missing, (
        "у %d вложенных ключей языка нет объявленного закона: %s. Пока закона "
        "нет, роль угадывается по облику значения — именной дефект этого "
        "модуля. Объяви каждый в `program_source.KEY_LAW`."
        % (len(missing), missing))


def test_необъявленный_ключ_есть_отказ_а_не_догадка() -> None:
    """THREE OUTCOMES, NOT TWO: this question has NO safe default.

    "Don't touch it" corrupts a position (a world point would stay a
    world point inside a function with a local frame — exactly the
    `arc.center_mm` defect of 21.08); "touch it" corrupts everything
    else. So the third outcome is a loud refusal with a named next move.

    The cost is measured, not estimated: across a corpus of 56
    decompiles / 82,451 operations, all 11 live nested keys are
    declared, refusals 0 out of 320.
    """

    op = _floor("f1", [5000, 6000], [4000, 3000], 30.25)
    op["contour"]["выдуманное_поле"] = [1.0, 2.0]
    result = ps.render_source([{"ops": [op]}])

    assert not result.ok, "необъявленный ключ проехал молча"
    causes = {r.cause for r in result.refusals}
    assert causes == {"undeclared_nested_key"}, (
        "отказ не тот, что заявлен: %s" % causes)
    assert "выдуманное_поле" in result.refusals[0].detail, (
        "отказ не назвал ключ: %s" % result.refusals[0].line())
    assert "KEY_LAW" in result.refusals[0].detail, "отказ не дал следующего хода"


def test_закон_и_виды_из_реестра_не_расходятся() -> None:
    """The lock sits ON THE IMPORT, here it is only named to the reader.

    A kind that lands in `MM_KINDS` with no law would once again start
    being guessed at from its appearance. So a divergence is not a red
    test, but a module that fails to build.
    """

    assert set(ps.KIND_LAW) == (ps.MM_KINDS | ps.DEG_KINDS)
    # The derived sets must BE the law seen from another angle, not a
    # second carrier of it: two lists of the same knowledge drift apart
    # at the very first edit.
    assert ps.MM_KEYS == frozenset(
        k for k, law in ps.KEY_LAW.items() if law == ps.POSITION)
    assert ps.FREE_KEYS == frozenset(
        k for k, law in ps.KEY_LAW.items() if law == ps.FREE)
    # The old six must survive the derivation: removing them would be a
    # silent expansion of what gets rounded and shifted.
    assert {"bulge", "edge", "u", "v", "normal", "x_dir"} <= ps.FREE_KEYS
