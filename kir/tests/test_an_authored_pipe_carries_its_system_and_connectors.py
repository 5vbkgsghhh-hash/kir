# -*- coding: utf-8 -*-
"""M1: AN AUTHORED PIPE CARRIES ITS OWN SYSTEM AND ITS OWN ENDS, RATHER
THAN BEING SEEN AS A BLOCK.

🔴 WHAT WAS RED HERE, MEASURED ON 08.09.2026. `kir/clash/repair_profile.py`
knew how to refuse a run by name, but read ONLY `instance.parameters`. Yet
the authored program places the op's fields into the OUTPUT'S OPERATION
(`author_project` copies the payload into `NamedOutput.operation`), and so
a revision made with `create_duct` — a declared system and an axis with a
4.9937617% slope — gave `repair_profile.classify(...) is None`: the
profile treated the duct as a BLOCK, and `propose_fix` refused with
someone else's words, "this output's shape is parameterised otherwise",
that is, about PARAMETERIZATION where the question was about TYPE.

WHAT THESE TESTS MEASURE:
  (1) A CLOSED LIST: every registry op whose category lies on the `mep`
      side of the `kir.clash.hulls.KIND_TABLE` table is NAMED by the
      producer — and not a single name beyond the registry;
  (2) A THRESHOLD: the four authored ops each give NO FEWER THAN TWO MEP
      fields;
  (3) A NUMBER: for a run with a slope, the refusal carries THE SLOPE
      ITSELF, and the expectation is computed here by its own formula,
      rather than asked of the module under test;
  (4) A MUTATION FAIL CONTROL: disable the producer — and the profile sees
      a block again, meaning it is THIS producer that holds up the green;
  (5) DISCRIMINATING POWER: a horizontal run, a free mass segment, and a
      non-MEP op are judged DIFFERENTLY, not with one blanket "cannot".
"""
from __future__ import annotations

import math

import pytest

from kir.clash import repair_profile as RP
from kir.geometry_materialization import (MEP_AXIS_OPS, MEP_FIELD_OPS,
                                          MEP_GRAPH_OPS, MEP_PATH_OPS,
                                          mep_fields)

#: The duct axis of the same probe: three nonzero components, the slope is not round.
RUN = ([1000.0, 1000.0, 200.0], [5000.0, 1200.0, 400.0])

#: The plan's four authored ops, each exactly as the author writes it.
AUTHORED = {
    "create_pipe": {"op": "create_pipe", "p0_mm": RUN[0], "p1_mm": RUN[1],
                    "level": {"by": "name", "value": "L1"},
                    "system_type": {"by": "name", "value": "ХВС"},
                    "diameter_mm": 100.0},
    "create_duct": {"op": "create_duct", "p0_mm": RUN[0], "p1_mm": RUN[1],
                    "level": {"by": "name", "value": "L1"},
                    "system_type": {"by": "name", "value": "ОВ приточная"},
                    "diameter_mm": 200.0},
    "create_cable_tray": {"op": "create_cable_tray", "p0_mm": RUN[0], "p1_mm": RUN[1],
                          "level": {"by": "name", "value": "L1"},
                          "width_mm": 300.0, "height_mm": 100.0},
    "create_conduit": {"op": "create_conduit", "p0_mm": RUN[0], "p1_mm": RUN[1],
                       "level": {"by": "name", "value": "L1"}},
}


class _Output:
    """The revision's output: only what the profile reads."""

    def __init__(self, operation):
        self.operation = operation


class _Instance:
    """The revision instance: parameters and metadata, like `ModuleInstance`."""

    def __init__(self, parameters=None, metadata=None):
        self.parameters = dict(parameters or {})
        self.metadata = dict(metadata or {})


def _expected_pitch(axis) -> float:
    """The slope by ITS OWN formula: rise in z over horizontal length, in percent.

    It is computed here deliberately, rather than taken from
    `repair_profile.slope_pct`: otherwise the expectation and the subject
    would be one and the same code.
    """
    (x0, y0, z0), (x1, y1, z1) = axis
    return (z1 - z0) / math.hypot(x1 - x0, y1 - y0) * 100.0


# ─────────────────────────────── (1) THE CLOSED LIST ────────────────────────

def _registry_mep_ops() -> set[str]:
    from kir.clash.hulls import KIND_TABLE
    from kir.spec import OPS, op_result_categories

    names = {spec.name for spec in OPS} if not isinstance(OPS, dict) else set(OPS)
    found = set()
    for name in names:
        try:
            categories = op_result_categories({"op": name}) or ()
        except Exception:  # noqa: BLE001 — an op without a resolvable category is not MEP
            continue
        for category in categories:
            rule = KIND_TABLE.get(category)
            if rule is not None and rule.mvp_side == "mep":
                found.add(name)
    return found


def test_every_mep_op_of_the_registry_is_named_by_the_producer():
    """The producer's list is EXACTLY the registry's list: no holes, no inventions."""
    registry = _registry_mep_ops()
    named = set(MEP_FIELD_OPS)
    assert registry, "реестр не назвал ни одного MEP-опа — прибор мерит не то"
    assert not (registry - named), (
        f"оп реестра со стороной `mep` без производителя: {sorted(registry - named)}")
    assert not (named - registry), (
        f"производитель назвал то, чего реестр MEP не считает: {sorted(named - registry)}")
    # There is ONE list and it does not overlap itself: three families, one union.
    assert len(MEP_FIELD_OPS) == len(set(MEP_FIELD_OPS)) == len(registry)
    assert set(MEP_AXIS_OPS) | set(MEP_GRAPH_OPS) | set(MEP_PATH_OPS) == named


# ─────────────────────────────── (2) THE PLAN'S THRESHOLD ────────────────────

@pytest.mark.parametrize("имя", sorted(AUTHORED))
def test_four_authoring_ops_produce_at_least_two_mep_fields_each(имя):
    """THE "4 ops × 2 fields" THRESHOLD: each gives a category AND end connectors."""
    fields = mep_fields(AUTHORED[имя])
    assert len(fields) >= 2, (имя, fields)
    # THE CATEGORY comes from the registry, and it is on the `mep` side of the closed table.
    from kir.clash.hulls import KIND_TABLE

    rule = KIND_TABLE.get(fields["category"])
    assert rule is not None and rule.mvp_side == "mep", (имя, fields.get("category"))
    # THE ENDS are CONNECTORS, in the same words as the `ops_connect` graph.
    assert fields["nodes"] == {"p0": RUN[0], "p1": RUN[1]}, (имя, fields["nodes"])
    assert [(s["from"], s["to"]) for s in fields["segments"]] == [("p0", "p1")]
    assert fields["p0_mm"] == RUN[0] and fields["p1_mm"] == RUN[1]
    # The profile READS this as a connector graph — with the same instrument as before.
    assert RP._has_connector_graph(fields) is True


def test_the_system_is_produced_where_and_only_where_the_op_carries_it():
    """`system_type` appears for a pipe and a duct and does NOT appear for a tray.

    Discriminating power: the producer does not add fields on the author's behalf.
    """
    assert mep_fields(AUTHORED["create_pipe"])["system_type"] == "ХВС"
    assert mep_fields(AUTHORED["create_duct"])["system_type"] == "ОВ приточная"
    assert "system_type" not in mep_fields(AUTHORED["create_cable_tray"])
    assert "system_type" not in mep_fields(AUTHORED["create_conduit"])
    # An op WITHOUT a declared system (chosen by the snapshot's single
    # record) is still membership, and it is named by a word, not by silence.
    without = dict(AUTHORED["create_pipe"])
    without["system_type"] = {"by": "default"}
    assert mep_fields(without)["system_type"] == "default"


def test_the_producer_says_nothing_about_an_op_that_is_not_a_run():
    """CONTROL: a non-MEP op gives `{}` — an answer, not an omission."""
    for operation in ({"op": "create_directshape", "category": "mass", "name": "x"},
                      {"op": "create_wall", "p0_mm": [0.0, 0.0], "p1_mm": [1.0, 1.0]},
                      {"op": "create_level", "elev_mm": 0, "name": "L0"},
                      "не операция вовсе", None, {}):
        assert mep_fields(operation) == {}, operation


# ─────────────────────────── (3) THE SLOPE NUMBER IN THE REFUSAL ────────────

@pytest.mark.parametrize("имя", sorted(AUTHORED))
def test_a_sloped_authored_run_is_refused_by_name_with_its_slope_number(имя):
    """The refusal carries THE SLOPE ITSELF, and the expectation is computed by its own formula."""
    verdict = RP.classify(_Instance(), _Output(AUTHORED[имя]))
    assert verdict is not None, f"{имя}: авторская трасса прошла как глыба"
    ожидание = _expected_pitch(RUN)
    assert verdict[0] == f"repair_profile_unsupported:mep_axis_slope:{ожидание:.6g}", (
        имя, verdict[0], ожидание)
    # The number is not round and not zero — otherwise the probe would be guarding a coincidence.
    assert abs(ожидание - 4.993762) < 5e-7, ожидание
    assert f"{ожидание:.6g}" in verdict[1], verdict[1]


def test_a_graph_op_is_refused_with_the_declared_slope_floor_not_a_computed_one():
    """The graph's number is different and is taken from `segments[].slope_min_pct` (KIR-X004)."""
    operation = {"op": "route_duct_system",
                 "nodes": {"a": [0.0, 0.0, 0.0], "b": [4000.0, 0.0, 200.0]},
                 "segments": [{"from": "a", "to": "b", "slope_min_pct": 2.0}],
                 "level": {"by": "name", "value": "L1"},
                 "system_type": {"by": "name", "value": "К1"}}
    verdict = RP.classify(_Instance(), _Output(operation))
    assert verdict[0] == "repair_profile_unsupported:slope_declared:2.0", verdict[0]
    assert "OST_DuctCurves" in verdict[1], verdict[1]


def test_a_flex_run_is_refused_without_pretending_it_has_a_straight_axis():
    """A polyline does NOT get `p0_mm`/`p1_mm`: a chord is not an axis, and it has no slope.

    Otherwise the refusal would name a number the author never wrote.
    """
    operation = {"op": "create_flex_pipe",
                 "path": [[0.0, 0.0, 0.0], [1000.0, 0.0, 0.0], [1000.0, 1000.0, 300.0]],
                 "level": {"by": "name", "value": "L1"},
                 "system_type": {"by": "name", "value": "ВК"}}
    fields = mep_fields(operation)
    assert "p0_mm" not in fields and "p1_mm" not in fields, fields
    assert len(fields["segments"]) == 2 and len(fields["nodes"]) == 3
    verdict = RP.classify(_Instance(), _Output(operation))
    assert verdict[0] == "repair_profile_unsupported:mep_category:OST_FlexPipeCurves"


# ──────────────────── (4) FAIL CONTROL: DISABLE THE PRODUCER ────────────────

def test_without_the_producer_the_profile_sees_a_plain_mass_again(monkeypatch):
    """The plan's FAIL: remove the producer — and the pipe is a block again. IT is what holds up the red."""
    instance, output = _Instance(), _Output(AUTHORED["create_pipe"])
    assert RP.classify(instance, output) is not None, "зелёное не состоялось"

    monkeypatch.setattr("kir.geometry_materialization.mep_fields",
                        lambda operation: {})
    assert RP.classify(instance, output) is None, (
        "профиль отказал БЕЗ производителя — значит держало что-то другое")


# ─────────────────── (5) THE INSTRUMENT'S DISCRIMINATING POWER ──────────────

def test_a_level_authored_run_is_refused_by_its_category_not_by_a_number():
    """A horizontal pipe: there is NO slope, and the refusal speaks about the category."""
    operation = dict(AUTHORED["create_pipe"],
                     p0_mm=[1000.0, 1000.0, 200.0], p1_mm=[5000.0, 1200.0, 200.0])
    verdict = RP.classify(_Instance(), _Output(operation))
    assert verdict[0] == "repair_profile_unsupported:mep_category:OST_PipeCurves", verdict[0]


def test_a_vertical_authored_riser_names_its_category_and_no_slope():
    """A riser: there is no horizontal length, the slope is UNDEFINED — there is no number in the refusal."""
    operation = dict(AUTHORED["create_pipe"],
                     p0_mm=[1000.0, 1000.0, 0.0], p1_mm=[1000.0, 1000.0, 3000.0])
    verdict = RP.classify(_Instance(), _Output(operation))
    assert verdict[0] == "repair_profile_unsupported:mep_category:OST_PipeCurves", verdict[0]


def test_a_free_mass_segment_is_still_supported_after_the_producer_arrived():
    """A CONTROL AGAINST OVER-REFUSAL: a free mass segment MAY be raised.

    This is exactly the supported profile line (`free_segment_axis`) held
    up by the acceptance test
    `kir/clash/tests/test_a_repair_that_breaks_a_run_is_refused_by_name.py`.
    The producer says nothing about `create_directshape`, and so the
    verdict MUST remain unchanged.
    """
    output = _Output({"op": "create_directshape", "category": "mass", "name": "run"})
    instance = _Instance({"run": [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]],
                          "p0_mm": [1000.0, 1000.0, 200.0],
                          "p1_mm": [5000.0, 1200.0, 400.0], "diameter_mm": 200.0})
    assert RP.classify(instance, output) is None


def test_instance_parameters_outrank_the_operation_they_came_from():
    """The instance's parameters are STRONGER than what was produced: a fix has the last word.

    An axis that a repair has raised into the parameters MUST be read by
    the profile instead of the one declared in the operation: otherwise a
    single element would end up with two addresses.
    """
    output = _Output(AUTHORED["create_pipe"])
    поднятая = {"p0_mm": [1000.0, 1000.0, 1200.0], "p1_mm": [5000.0, 1200.0, 1400.0]}
    verdict = RP.classify(_Instance(поднятая), output)
    # The slope is the same (the transfer does not touch it), but it was
    # EXACTLY the raised axis that was read.
    assert verdict[0].startswith("repair_profile_unsupported:mep_axis_slope:")
    # And an axis declared HORIZONTAL in the parameters cancels the number from the operation.
    ровная = {"p0_mm": [1000.0, 1000.0, 200.0], "p1_mm": [5000.0, 1200.0, 200.0]}
    assert RP.classify(_Instance(ровная), output)[0] == \
        "repair_profile_unsupported:mep_category:OST_PipeCurves"


def test_a_declared_slope_floor_outranks_the_slope_of_the_same_axis():
    """ORDER INSIDE THE MEP BRANCH: the checked postcondition outranks the computed one.

    A single element can carry BOTH numbers: the KIR-X004 slope floor in
    the parameters, and the slope of the declared axis in the operation.
    The floor wins — the postcondition holds it, and it is exactly that
    postcondition that will roll back the program. Without this probe the
    order could be swapped, and no run would ever turn red.
    """
    output = _Output(AUTHORED["create_pipe"])
    instance = _Instance({"segments": [{"from": "a", "to": "b", "slope_min_pct": 1.5}]})
    assert RP.classify(instance, output)[0] == \
        "repair_profile_unsupported:slope_declared:1.5"


def test_the_slope_number_never_prints_a_nonzero_as_zero():
    """The comparison of z has NO invented threshold, and formatting does not eat the order of magnitude.

    A pipe declared with a rise of 1e-9 mm is a pipe WITH A SLOPE: the
    author wrote those numbers, and the instrument has no right to round
    them off to "horizontal".
    """
    operation = dict(AUTHORED["create_pipe"],
                     p0_mm=[0.0, 0.0, 0.0], p1_mm=[4000.0, 0.0, 1e-9])
    code = RP.classify(_Instance(), _Output(operation))[0]
    assert code.startswith("repair_profile_unsupported:mep_axis_slope:"), code
    напечатано = code.rsplit(":", 1)[1]
    assert float(напечатано) != 0.0, code
    assert float(напечатано) == pytest.approx(1e-9 / 4000.0 * 100.0, rel=1e-5)


# ─────────────── (6) A REAL REVISION, NOT A FORGED INSTANCE ─────────────────

def test_the_producer_survives_the_frozen_form_a_real_revision_stores():
    """🔴 A PROBE FOUND BY SELF-REVIEW ON 08.09.2026. The stub classes above
    hand back the operation as a LIVE dict, while the real `NamedOutput`
    FREEZES it (`kir.project._freeze`): a nested object -> `MappingProxyType`,
    a list -> `tuple`. The profile asks `isinstance(segs, list)` and
    `isinstance(seg, dict)`, and against a frozen graph both would answer
    "no": the KIR-X004 slope floor would disappear SILENTLY, and the
    refusal would fall back to `mep_category` — a name without a number.

    That is why the subject here is the REAL `NamedOutput`/`ModuleInstance`.
    """
    from kir.project import ModuleInstance, NamedOutput

    graph = NamedOutput("r", {"op": "route_duct_system",
                              "nodes": {"a": [0.0, 0.0, 0.0], "b": [4000.0, 0.0, 200.0]},
                              "segments": [{"from": "a", "to": "b", "slope_min_pct": 2.0}],
                              "level": {"by": "name", "value": "L1"},
                              "system_type": {"by": "name", "value": "К1"}})
    # First DEMONSTRATE the freezing, otherwise the probe would be guarding something that isn't there.
    assert not isinstance(graph.operation["segments"], list), graph.operation["segments"]
    assert not isinstance(graph.operation["segments"][0], dict)

    fields = mep_fields(graph.operation)
    assert isinstance(fields["segments"], list) and isinstance(fields["segments"][0], dict)
    assert isinstance(fields["nodes"], dict)
    assert RP.classify(ModuleInstance("r", "m", [graph]), graph)[0] == \
        "repair_profile_unsupported:slope_declared:2.0"

    # And the pipe by the same road: the axis from the frozen operation is read as a number.
    pipe = NamedOutput("p", AUTHORED["create_pipe"])
    assert RP.classify(ModuleInstance("p", "m", [pipe]), pipe)[0] == \
        f"repair_profile_unsupported:mep_axis_slope:{_expected_pitch(RUN):.6g}"


def test_the_new_reason_is_declared_in_the_profile_list():
    """The new refusal is CLAIMED as a list, like the other four."""
    assert "mep_axis_slope" in dict(RP.UNSUPPORTED)
    assert "mep_axis_slope" in RP.describe()
