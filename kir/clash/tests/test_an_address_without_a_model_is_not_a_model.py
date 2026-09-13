"""An address WITHOUT a separator does not carry a model name — and does not invent one (F-086).

WHAT IS PINNED DOWN HERE. `cross_model_pair_filter` is the
`cross_model_federation` scope, whose only question is "do the MODELS
interfere with each other". A model's name lives in the address
`<model>::<source id>`; the previous edition pulled it out as
`source_id.split("::", 1)[0]`, and a string's `split` WITHOUT a separator
returns the string itself. Ordinary Revit ids `100` and `101` therefore each
got THEIR OWN "model", and a pair inside a single building passed the filter
as cross-model.

THE NUMBER THIS IS MEASURED BY (2026-09-03, snapshot built by the production
code `snapshot.build_from_elements`, four walls, addresses exactly as a
decompile assigns them — `100`…`103`): the `cross_model_federation` scope was
handing back **6 findings out of 6** — exactly as many as
`all_physical_diagnostic`. That is, the coverage collapsed into "everything",
while the report called itself cross-model.

THE CARDINALITY WITHOUT WHICH THE CONTROL COULD NOT HAVE TURNED RED (shape
18). Clash is about PAIRS, and "zero findings" can be green by construction:
a single hull has no pairs at all, and non-intersecting ones have no findings
regardless of the filter. So every input here carries AT LEAST TWO
INTERSECTING bodies, and every zero is presented next to a run of THE SAME
snapshot under `any_physical_pair_filter`: the act of distinguishing is the
difference between two numbers on one input, not a single number.
"""

from __future__ import annotations

import dataclasses

from kir.clash import detect as D
from kir.clash import existing as E
from kir.clash import snapshot as S


def _snapshot(n: int = 4):
    """A snapshot built by production code. The addresses are exactly what a decompile assigns: without a model."""
    elements = [
        {"element_id": str(100 + i), "category": "OST_Walls",
         "bbox_min_mm": [i * 100.0, 0.0, 0.0],
         "bbox_max_mm": [i * 100.0 + 400.0, 400.0, 400.0],
         "level_id": "L1", "type_name": "t"}
        for i in range(n)]
    return S.build_from_elements(
        elements, origin={"run_dir": "f086", "l0_sha": "0"})


def _with_ids(snap, ids):
    records = tuple(dataclasses.replace(r, source_id=new)
                    for r, new in zip(snap.records, ids))
    return S.ClashGeometrySnapshot(
        records=records, census=snap.census, origin=snap.origin,
        refusals=snap.refusals)


def test_two_unprefixed_ids_are_not_two_models():
    """A pair INSIDE a single building must not pass the federation filter."""
    snap = _snapshot()
    assert [r.source_id for r in snap.records] == ["100", "101", "102", "103"]

    control = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    federated = D.detect(snap, pair_filter=D.cross_model_pair_filter)

    # The input IS CAPABLE of producing findings — otherwise the zero below would mean nothing.
    assert len(control["findings"]) == 6, control["search"]
    assert control["search"]["candidate_pairs"] == 6

    assert federated["search"]["candidate_pairs"] == 0
    assert federated["findings"] == [], (
        "адрес без разделителя выдал себя за имя модели: "
        f"{[f['finding_id'] for f in federated['findings']]}")


def test_a_federated_snapshot_still_finds_its_cross_model_pairs():
    """And the filter has not degenerated into "discard everything" — otherwise it is green by emptiness."""
    snap = _snapshot()
    snap = _with_ids(snap, [f"m{i % 2}::{r.source_id}"
                            for i, r in enumerate(snap.records)])

    report = D.detect(snap, pair_filter=D.cross_model_pair_filter)

    assert len(report["findings"]) == 4, report["search"]
    for finding in report["findings"]:
        key_a = D.model_key_of(finding["a"]["source_element_id"])
        key_b = D.model_key_of(finding["b"]["source_element_id"])
        assert key_a is not None and key_b is not None and key_a != key_b


def test_a_pair_with_one_addressless_side_is_not_cross_model():
    """An unknown side is not "another model", but the absence of an answer.

    Before the fix, this input gave FIVE findings, and one of them —
    `100~102` — was a pair of two addressless ones, that is, knowingly
    inside a single building.
    """
    snap = _snapshot()
    snap = _with_ids(snap, [r.source_id if i % 2 == 0 else f"m1::{r.source_id}"
                            for i, r in enumerate(snap.records)])

    control = D.detect(snap, pair_filter=D.any_physical_pair_filter)
    federated = D.detect(snap, pair_filter=D.cross_model_pair_filter)

    assert len(control["findings"]) == 6
    assert federated["findings"] == [], (
        "пара с безадресной стороной объявлена межмодельной: "
        f"{[f['finding_id'] for f in federated['findings']]}")


def test_the_skipped_addressless_hulls_are_named_in_the_report():
    """A zero from a missing address must differ from an honest zero."""
    snap = _snapshot()

    silent = D.detect(snap, pair_filter=D.cross_model_pair_filter)
    named = [n for n in silent["notes"] if "БЕЗ имени модели" in n]
    assert len(named) == 1, silent["notes"]
    assert "4 из 4" in named[0], named[0]

    # And the note is never vacuous: on a fully addressed snapshot it is absent.
    addressed = _with_ids(snap, [f"m{i % 2}::{r.source_id}"
                                 for i, r in enumerate(snap.records)])
    report = D.detect(addressed, pair_filter=D.cross_model_pair_filter)
    assert not [n for n in report["notes"] if "БЕЗ имени модели" in n]


def test_model_key_of_reads_the_separator_and_not_the_string():
    """A single law for parsing the address — separate from the pair, to keep it narrow."""
    assert D.model_key_of("101") is None
    assert D.model_key_of("") is None
    assert D.model_key_of("::101") is None, "пустое имя модели — не имя"
    assert D.model_key_of("m1::101") == "m1"
    assert D.model_key_of("m1::a::b") == "m1", "делит ПЕРВЫЙ разделитель"
    assert D.model_key_of(E.existing_source_id("5")) == E.EXISTING_SOURCE


def test_the_two_readers_of_the_source_address_agree():
    """One convention — one separator, and a discrepancy must turn red."""
    assert D.MODEL_SEPARATOR == E.SOURCE_SEPARATOR
    assert E.is_existing(E.existing_source_id("7"))
    assert not E.is_existing("7")
