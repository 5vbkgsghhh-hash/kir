# -*- coding: utf-8 -*-
"""SELF-CHECK IS FOR A FOREIGN CARRIER, NOT FOR ONE'S OWN BIRTH.

🔴 CONTRACT DECISION (2026-09-07, decision of the shift lead). The self-check
`GeometryMaterialization.__post_init__` asks: "does this plan describe THIS
program, and have the authored fields not been rewritten." The question makes
sense for a materialization that ARRIVED FROM A FOREIGN CARRIER — assembled
from saved parts, from another process, from someone else's hands. For one
born inside `_materialize` from these same addresses and this same
`plan_program`, there is nothing to compare but itself against itself.

The cost of the question was measured on 2000 bodies: canonicalizing the
whole program costs 2.4 s, and a SECOND `plan_program` costs 1.6 s on EVERY
analysis. A warm analysis went from 9.06 to 7.15 s.

THE EXEMPTION MUST BE ASKED FOR, NOT GRANTED SILENTLY: the `_born_here` flag
is not serialized, is set only by the producer, and defaults to `False`. The
pins below require both properties at once — the producer's exemption, and a
FULL check for anyone who assembled the materialization from data.
"""
from __future__ import annotations

import pytest

pytest.importorskip("OCP", reason="тела строятся настоящим OCCT")

from kir.geometry_materialization import (GeometryMaterialization,      # noqa: E402
                                          GeometryRefusal, materialize_project)
from kir.tests.test_geometry_materialization import capture, project_for  # noqa: E402


@pytest.fixture(scope="module")
def made():
    bundle = capture()
    project = project_for(bundle)
    return bundle, project, materialize_project(project, {bundle.digest: bundle}, bulk=True)


def test_only_the_producer_marks_its_own_birth(made):
    bundle, _project, born = made
    assert born._born_here is True, "производитель не пометил своё рождение"
    rebuilt = GeometryMaterialization(born.project, born.to_program(), born.planned,
                                      tuple(dict(row) for row in born.sources),
                                      born.selection)
    assert rebuilt._born_here is False, "признак рождения утёк на чужой носитель"
    assert rebuilt.to_dict() == born.to_dict(), "полная проверка изменила значение"


def test_a_swapped_row_on_a_foreign_carrier_still_fails_the_self_check(made):
    """🔴 CONTROL-FAIL: swapping ONE row of something assembled externally — a refusal."""
    _bundle, _project, born = made
    program = born.to_program()
    program["ops"][0]["name"] = "подменено"
    with pytest.raises(GeometryRefusal, match="materialization"):
        GeometryMaterialization(born.project, program, born.planned,
                                tuple(dict(row) for row in born.sources), born.selection)


def test_a_foreign_plan_for_this_program_still_fails_the_self_check(made):
    """A foreign plan for this program — the same refusal: the link between plan and program."""
    _bundle, _project, born = made
    stranger = capture(2000)
    other = materialize_project(project_for(stranger), {stranger.digest: stranger}, bulk=True)
    assert other.planned.plan_digest != born.planned.plan_digest, "план не стал чужим"
    with pytest.raises(GeometryRefusal, match="materialization"):
        GeometryMaterialization(born.project, born.to_program(), other.planned,
                                tuple(dict(row) for row in born.sources), born.selection)


def test_the_mark_never_reaches_serialized_form(made):
    """The flag does not travel outward: otherwise it would become a field of a foreign carrier."""
    _bundle, _project, born = made
    payload = born.to_dict()
    assert not any("born" in str(key) for key in payload), payload.keys()


def test_the_validity_gate_of_a_body_is_paid_once_per_bytes(made):
    """🔴 (1′) NUMBER: the body validity gate is paid once per BYTES, not per read.

    `read_body` calls `_measure` just for the REFUSAL (the result is
    discarded): on 2000 bodies this is 4.51 s out of 4.82 s, while the BRep
    parse itself is 0.31 s.
    """
    from kir import occt_geometry as OG

    bundle, _project, _born = made
    OG._VALIDATED_BODIES.discard(bundle.body_digest)
    calls = []
    original = OG._measure

    def counted(shape, k):
        calls.append(1)
        return original(shape, k)

    OG._measure = counted
    try:
        bundle.read_body()
        assert len(calls) == 1, "первое чтение не заплатило за ворота"
        bundle.read_body()
        bundle.read_body()
        assert len(calls) == 1, f"ворота заплачены {len(calls)} раз на одни байты"
        # `measure()` asks for the NUMBER, not the refusal: it is always computed.
        bundle.measure()
        assert len(calls) == 2, "measure() перестал считать — память ушла не туда"
    finally:
        OG._measure = original


def test_the_validity_gate_has_a_named_ceiling():
    from kir import occt_geometry as OG

    assert isinstance(OG._VALIDATED_BODIES_LIMIT, int) and OG._VALIDATED_BODIES_LIMIT > 0
