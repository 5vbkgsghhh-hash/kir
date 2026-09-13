# -*- coding: utf-8 -*-
"""THE DECLARED FIX PROFILE: what `raise_clear` IS ABLE to move, and what
it is NOT.

🔴 WHY THIS MODULE, BY MEASUREMENT OF 07.09.2026.
`kir.project_fix.propose_fix` reads the word `operation` EXACTLY ONCE — to
copy the old operation into the new `NamedOutput` (`project_fix.py:196`).
Neither `op`, nor `category`, nor a single element parameter is asked by
the lift strategy AT ALL. So for it a pipe, a duct, and a mass blob are the
same body with a box in its parameters, and the only thing that stops a
pipe from being lifted today is the ABSENCE of a box on it (`_box_of ->
None`, the refusal "this output's shape is parameterised otherwise").

THIS IS A REFUSAL ABOUT A DIFFERENT SUBJECT, and its cost is that very
same, our own named one. It speaks of PARAMETERIZATION, while the question
was about the TYPE: for an element that arrives with a box (a duct
decompiled from a capture, or one issued by `create_directshape`-as-mass),
the check will pass, and a lift along z will silently:
  * TEAR APART the CONNECTORS — neighboring segments and fittings will stay
    in place (`kir/clash/resolve.py:169-188` knows `RIDES_WITH_RUN`, but
    this path does not read it);
  * REMOVE the element from its SYSTEM — `system_type` is declared, and
    Revit derives membership on commit (`ops_connect.py`, post
    `mep_system_ids/one_system`);
  * BREAK THE SLOPE, if the lift is applied to one end of a run and not to
    both: `segments[].slope_min_pct` is a quantity CHECKED by a
    postcondition (`kir/route_mep.py:70`, `KIR-X004`), and the program
    rolls back when it does not hold.

Hence the profile is DECLARED here as a list, rather than implied by code.

🔴 WHAT THIS MODULE DOES NOT ASSERT. It does not introduce its own MEP
model or a single new field name: it reads WORDS OF THE KIR LANGUAGE
ITSELF —
  `p0_mm`/`p1_mm`   the axis of a single element (`ops_mep.py:130`,
                    `create_duct`, `create_cable_tray`, `create_conduit`,
                    stock elements);
  `nodes`/`segments` the run graph (`ops_connect.py:45`,
                    `create_pipe_system`, `route_pipe_system`,
                    `route_duct_system`);
  `segments[].slope_min_pct`  the slope floor
                    (`route_mep.extract_slope_requirements`);
  `system_type`     system membership (`ops_mep.py:134`,
                    `ops_connect.py:48`);
  `category`        the Revit category -> `kir.clash.hulls.KIND_TABLE`,
                    where the `mep` side is already declared as a closed
                    list.

🔴 WHERE THESE WORDS COME FROM IN A REVISION (08.09.2026). The profile
reads TWO carriers, and both belong to the revision itself:
  * `instance.parameters` — this is how fields arrive from CAPTURING an
    existing building (a decompiled duct: a mass with a box and
    `metadata.source_category`);
  * the output's OPERATION via the producer
    `kir.geometry_materialization.mep_fields` — this is how fields arrive
    from the AUTHORING program: `create_pipe`/`create_duct`/
    `create_cable_tray`/`create_conduit` (and stock elements, graphs,
    flexible runs — 11 registry ops in total) carry the axis, the system,
    and the slope IN THE OPERATION ITSELF, and `author_project` puts it
    into `NamedOutput.operation` verbatim.
Before 08.09.2026 ONLY the first carrier was read, and so an authored pipe
was passing the profile as a BLOB: a probe measurement — a revision with
`create_duct` (a declared system, an axis with a slope of 4.9937617 %) was
giving `classify(...) is None`, and `propose_fix` was refusing in SOMEONE
ELSE'S words, about parameterization instead of type. Declaring the
boundary also turned into A MEASUREMENT REPORT on an authored building;
nothing is asserted about live Revit, as before.
"""
from __future__ import annotations

from collections.abc import Mapping

#: What the `raise_clear` lift IS ABLE to move. Each row is a checkable
#: condition.
SUPPORTED: tuple[tuple[str, str], ...] = (
    ("box_parameterised_body",
     "тело, чья форма задана коробкой [[x,y,z],[x,y,z]] в "
     "`instance.parameters[output.key]`"),
    ("free_segment_axis",
     "СВОБОДНЫЙ отрезок трассы: ось `p0_mm`/`p1_mm` без графа коннекторов, без "
     "`system_type` и без `slope_min_pct`. Ось сдвигается ТЕМ ЖЕ мировым "
     "вектором, что и коробка, поэтому уклон сохраняется тождественно"),
)

#: What the lift is NOT ABLE to do, and why the refusal is named rather
#: than a silent shift.
UNSUPPORTED: tuple[tuple[str, str], ...] = (
    ("connectors_declared",
     "у элемента объявлен граф коннекторов (`nodes`/`segments` с `from`/`to`): "
     "подъём одного сегмента оторвёт его от соседей и от фитингов"),
    ("system_membership",
     "элемент объявлен членом системы (`system_type`): подъём меняет трассу, "
     "по которой Revit выводит `MEPSystem` при коммите"),
    ("slope_declared",
     "объявлен пол уклона (`segments[].slope_min_pct`, KIR-X004): подъём одного "
     "конца меняет уклон, и постусловие откатит программу"),
    ("mep_axis_slope",
     "ось MEP-элемента ОБЪЯВЛЕНА С УКЛОНОМ — концы `p0_mm`/`p1_mm` расходятся "
     "по z: у трассы с уклоном подъём одного конца ломает KIR-X004, а подъём "
     "обоих уводит из системы и рвёт коннекторы. Отказ несёт САМО ЧИСЛО "
     "уклона в процентах, чтобы читателю не пришлось мерить заново"),
    ("mep_category",
     "категория элемента лежит на стороне `mep` закрытой таблицы "
     "`kir.clash.hulls.KIND_TABLE` (труба, воздуховод, лоток, короб, фитинг, "
     "изоляция): у трассы есть связи, которых `raise_clear` не видит"),
)

#: The prefix of a named refusal. The same technique as
#: `hull_type_unsupported:<T>` in `kir/clash/hulls.py` and the closed
#: `REFUSALS` in `kir/clash/exact.py`.
REFUSAL_PREFIX = "repair_profile_unsupported"

#: The word `category` in an op -> a BuiltInCategory member. One table for
#: the whole of KIR.
def _builtin_category(word) -> str | None:
    if not isinstance(word, str) or not word:
        return None
    if word.startswith("OST_"):
        return word
    from kir.ops_shape import DIRECTSHAPE_CATEGORIES

    return DIRECTSHAPE_CATEGORIES.get(word)


def _is_mep_category(word) -> str | None:
    """A category on the `mep` side of the closed hull table — or None."""
    from kir.clash.hulls import KIND_TABLE

    member = _builtin_category(word)
    if member is None:
        return None
    rule = KIND_TABLE.get(member)
    return member if rule is not None and rule.mvp_side == "mep" else None


# 🔴 THE FORM IN WHICH THE REVISION STORES THE DATA IS READ, NOT THE ONE
# THAT IS CONVENIENT TO WRITE IN A TEST (measurement of 08.09.2026).
# `kir.project._freeze` turns a nested object into a `MappingProxyType`,
# and a list into a `tuple`; `ModuleInstance` also freezes `parameters`.
# The checks below were asking for EXACTLY `list` and EXACTLY `dict`, and
# so on a REAL instance they saw neither the graph nor the slope floor:
#     _segments(inst.parameters)          -> []      (it was a `tuple`)
#     _declared_slope(inst.parameters)    -> None    (the floor of 2.0 was
#                                                      lost)
#     _has_connector_graph(inst.parameters) -> False (the 2-node graph was
#                                                      lost)
# The refusal for a run with a system fell from `slope_declared:2.0` to
# `system_membership:'ОВ приточная'` — a name with no number; and for a run
# WITHOUT a system and WITHOUT an MEP category the profile would have said
# "supported", i.e. a SILENT SHIFT in exactly the place this module was
# introduced for. The defect was not caught because the probe was matching
# a substring in the FULL text of the refusal, and `describe()`, with all
# the names glued together at once, is spliced in there.
def _segments(parameters) -> list:
    segs = parameters.get("segments")
    return list(segs) if isinstance(segs, (list, tuple)) else []


def _has_connector_graph(parameters) -> bool:
    """A run graph: `nodes` OR at least one segment with `from`/`to`."""
    nodes = parameters.get("nodes")
    if isinstance(nodes, (list, tuple, Mapping)) and nodes:
        return True
    return any(isinstance(seg, Mapping) and ("from" in seg or "to" in seg)
               for seg in _segments(parameters))


def _declared_slope(parameters):
    """The slope floor declared by the author. Read with the SAME words as
    in `route_mep.extract_slope_requirements`, and so does not introduce a
    second name."""
    for seg in _segments(parameters):
        if isinstance(seg, Mapping) and "slope_min_pct" in seg:
            return seg["slope_min_pct"]
    return parameters.get("slope_min_pct")


def axis_of(parameters):
    """The axis of a single element, `(p0, p1)`, or None. The words are
    from `ops_mep`."""
    p0, p1 = parameters.get("p0_mm"), parameters.get("p1_mm")
    for point in (p0, p1):
        if not (isinstance(point, (list, tuple)) and len(point) == 3
                and all(isinstance(v, (int, float)) for v in point)):
            return None
    return ([float(v) for v in p0], [float(v) for v in p1])


def slope_pct(axis) -> float | None:
    """The axis slope in percent: the rise along z over the horizontal
    length.

    A vertical riser has no horizontal length, and it has NO slope — None
    is returned, not infinity and not zero. Zero would read as "there is no
    slope", i.e. as an assertion about the run instead of a refusal to
    measure.
    """
    if axis is None:
        return None
    (x0, y0, z0), (x1, y1, z1) = axis
    run = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if run <= 0.0:
        return None
    return (z1 - z0) / run * 100.0


def authored_fields(output) -> dict:
    """The MEP fields carried by the output's OPERATION. A second carrier,
    not a second law.

    There is one producer, and it lives in
    `kir.geometry_materialization.mep_fields`: here there is only the seam.
    The import is lazy for the same reason as `hulls` above — the profile
    must be readable without a single heavy module.

    🔴 AN IMPORT FAILURE IS NOT SWALLOWED. A `try/except -> {}` used to
    stand here and has been removed: it would have returned exactly the
    defect this seam was introduced for — the profile would silently see
    the pipe as a blob again. A broken import is a broken tree, and it must
    scream, not hand out a permit.
    """
    from kir.geometry_materialization import mep_fields

    return mep_fields(getattr(output, "operation", {}) or {})


def _mep_member(*words) -> str | None:
    """The first category on the `mep` side of the closed table — or
    None."""
    for word in words:
        member = _is_mep_category(word)
        if member is not None:
            return member
    return None


def classify(instance, output) -> tuple[str, str] | None:
    """`None` — the profile is supported. Otherwise `(refusal code, human
    reason)`.

    The order of checks is load-bearing: first the named MEP signs, and
    only then "supported". The reverse order ("if there is a box, then it
    is allowed") is exactly the mistake this module was introduced for.

    🔴 BOTH REVISION CARRIERS ARE READ: the instance parameters (capture)
    AND the output's operation via the producer (authoring). The parameters
    are STRONGER than the produced one: an edit placed into the parameters
    is the last word about the instance, while the operation speaks of what
    it was declared as.

    🔴 WITHIN THE MEP BRANCH THE NUMBER COMES AHEAD OF THE CATEGORY NAME.
    For a run declared with a slope, the refusal must name THE SLOPE
    ITSELF: `mep_category` would say "this is a duct" where the question
    asked was "by how much is it inclined". For an element WITHOUT a
    slope, the order is unchanged, and hence the old refusals are
    unchanged.
    """
    parameters = dict(getattr(instance, "parameters", {}) or {})
    operation = dict(getattr(output, "operation", {}) or {})
    metadata = dict(getattr(instance, "metadata", {}) or {})
    produced = authored_fields(output)
    # The instance parameters are stronger than the produced one: see the
    # docstring.
    fields = {**produced, **parameters}

    member = _mep_member(produced.get("category"), operation.get("category"),
                         metadata.get("category"), metadata.get("source_category"),
                         parameters.get("category"))
    if member is not None:
        slope = _declared_slope(fields)
        if slope is not None:
            return _slope_refusal(slope, member)
        pitch = _axis_pitch(fields)
        if pitch is not None:
            # 🔴 FORMAT `g`, NOT `f`, AND THIS IS NOT COSMETIC. `:.6f`
            # prints 2.5e-14 as "0.000000", i.e. the refusal about the
            # slope would be saying that there is no slope. Six SIGNIFICANT
            # digits do not turn a non-zero number into zero at any order
            # of magnitude.
            return (f"{REFUSAL_PREFIX}:mep_axis_slope:{pitch:.6g}",
                    f"ось элемента категории {member} объявлена с уклоном "
                    f"{pitch:.6g} % (концы `p0_mm`/`p1_mm` расходятся по z): "
                    f"подъём одного конца ломает уклон (KIR-X004), подъём "
                    f"обоих уводит трассу из системы и рвёт коннекторы")
        return (f"{REFUSAL_PREFIX}:mep_category:{member}",
                f"категория {member} лежит на стороне `mep` таблицы "
                f"`kir.clash.hulls.KIND_TABLE`: у трассы есть коннекторы, "
                f"система и уклон, которых подъём по z не видит")
    slope = _declared_slope(fields)
    if slope is not None:
        return _slope_refusal(slope, None)
    if _has_connector_graph(fields):
        return (f"{REFUSAL_PREFIX}:connectors_declared",
                "объявлен граф коннекторов (`nodes`/`segments` с `from`/`to`): "
                "подъём одного сегмента оторвёт его от соседей и фитингов")
    system = fields.get("system_type")
    if system:
        return (f"{REFUSAL_PREFIX}:system_membership:{system}",
                f"элемент объявлен членом системы (system_type={system!r}): "
                f"подъём меняет трассу, по которой Revit выводит MEPSystem")
    return None


def _slope_refusal(slope, member) -> tuple[str, str]:
    return (f"{REFUSAL_PREFIX}:slope_declared:{slope}",
            f"объявлен пол уклона slope_min_pct={slope} (KIR-X004, "
            f"`kir/route_mep.py`)"
            + (f" у элемента категории {member}" if member else "")
            + ": подъём меняет уклон, и постусловие "
              "откатит программу — двигать такую трассу надо целиком")


def _axis_pitch(fields):
    """The slope of the DECLARED axis, if the ends diverge in z — otherwise
    None.

    No threshold is INVENTED here, and none is needed: the very numbers
    the author wrote are compared. Equal z — the element is declared
    horizontal, and it has no slope; a riser (`slope_pct is None`) also has
    no slope, and it is the category that speaks of it, not an invented
    infinity.
    """
    axis = axis_of(fields)
    if axis is None or axis[0][2] == axis[1][2]:
        return None
    return slope_pct(axis)


def describe() -> str:
    """The profile's declaration in one line — for a refusal, a report,
    and a document."""
    return ("поддержано: "
            + "; ".join(f"{name} — {why}" for name, why in SUPPORTED)
            + " | НЕ поддержано: "
            + "; ".join(f"{name} — {why}" for name, why in UNSUPPORTED))


__all__ = ["SUPPORTED", "UNSUPPORTED", "REFUSAL_PREFIX", "classify", "axis_of",
           "authored_fields", "slope_pct", "describe"]
