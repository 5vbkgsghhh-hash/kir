"""Addressed reads scale without weakening immutable facts or ambiguity checks.

The counted operations measure the work, not a machine-specific time threshold.
Receipts are synthetic and use the real parser; no Revit or network is used.
"""
from dataclasses import FrozenInstanceError, replace
import json
import math
from time import perf_counter

import pytest

from kir import compiler
from kir.decompile import lineage
from kir.decompile.materialize import MaterializeResult, leaves_to_program
from kir.decompile.tests.test_lineage import _wall
from kir.diag import KirRefusal
from kir.open_model import ModelCatalogEntry, ModelCatalogPool, OpenModelProfileError
from kir import revit_observation as observations
from kir.tests.test_element_observation_scope import carriers
from kir.tests.test_revit_observation import case


def test_one_native_scope_answers_identities_without_decoding_other_elements(carriers, monkeypatch):
    make, target, context = carriers
    uids = [f"uid-{index}" for index in range(128)]
    observed = make(uids)
    before = observed.rows
    assert observed.target == target and observed.precondition is context
    assert observed.rows == before and observed.rows is not observed.rows
    before[uids[0]]["element_identity"]["element_id"] = 42
    with pytest.raises(TypeError):
        observed._indexed_rows[uids[0]] = "{}"
    with pytest.raises(FrozenInstanceError):
        observed.require_identity(uids[0]).element_id = 42
    monkeypatch.setattr(observations.json, "loads",
                        lambda *_: pytest.fail("an identity read decoded the scope"))
    for index, uid in enumerate(uids):
        assert observed.require_identity(uid).element_id == 10000 + index
    with pytest.raises(observations.ObservationRefusal, match="element_identity_unavailable"):
        observed.require_identity("not-observed")
    assert observed.precondition is context


def test_level_reads_decode_only_the_requested_row_and_remain_detached(case, monkeypatch):
    _, _, _, parse = case
    observed, same = parse(), parse()
    assert observed == same and hash(observed) == hash(same)
    expected = observed.rows["level-uid"]
    decoded_sizes = []
    original = json.loads

    def counted(value, *args, **kwargs):
        decoded_sizes.append(len(value))
        return original(value, *args, **kwargs)

    monkeypatch.setattr(observations.json, "loads", counted)
    first = observed.require_level("level-uid")
    first["level"]["project_elevation_mm"] = -1
    first["type_state"]["element_identity"]["version_guid"] = "b" * 32
    second = observed.require_level("level-uid")
    assert second == expected and first is not second
    assert list(second) == list(expected)
    assert len(decoded_sizes) == 2
    assert all(size < len(observed._rows_json) for size in decoded_sizes)
    assert observed.require_identity("level-uid").version_guid == "a" * 32
    with pytest.raises(observations.ObservationRefusal, match="level_observation_unavailable"):
        observed.require_level("protected-uid")
    with pytest.raises(observations.ObservationRefusal, match="level_observation_unavailable"):
        observed.require_level("not-observed")


class _ComparedId(int):
    comparisons = 0
    __hash__ = int.__hash__

    def __lt__(self, other):
        type(self).comparisons += 1
        return super().__lt__(other)

    def __eq__(self, other):
        type(self).comparisons += 1
        return super().__eq__(other)


@pytest.mark.parametrize("count", [128, 1000, 5000])
def test_catalog_lookup_halves_the_verified_pool_instead_of_scanning_it(count):
    entries = tuple(ModelCatalogEntry(_ComparedId(index), str(index))
                    for index in range(1, count + 1))
    pool = ModelCatalogPool("levels", entries, count, False)
    _ComparedId.comparisons = 0
    started = perf_counter()
    for index in range(1, count + 1):
        assert pool.entry(index) is entries[index - 1]
    assert pool.entry(count + 1) is None
    comparisons = _ComparedId.comparisons
    elapsed = perf_counter() - started
    assert comparisons <= (count + 1) * (math.ceil(math.log2(count)) + 2)
    print(f"catalog n={count} comparisons={comparisons} seconds={elapsed:.6f}")


def test_catalog_order_identity_and_legacy_unknown_queries_keep_their_contract():
    a, b = ModelCatalogEntry(1, "a"), ModelCatalogEntry(2, "b")
    for entries in ((b, a), (a, a)):
        with pytest.raises(OpenModelProfileError, match="sorted by unique ElementId"):
            ModelCatalogPool("levels", entries, 2, False)
    pool = ModelCatalogPool("levels", (a, b), 2, False)
    restored = ModelCatalogPool.from_dict(pool.to_dict())
    assert pool == restored and hash(pool) == hash(restored)
    assert replace(pool, entries=(a,), total_count=1).entry(2) is None
    assert pool.entry(1.0) is a and pool.entry(True) is a
    assert pool.entry("1") is None and pool.entry(None) is None
    assert ModelCatalogPool("levels", (), 0, False).entry(1) is None
    workset = ModelCatalogEntry(0, "default", id_space="workset")
    assert ModelCatalogPool("worksets", (workset,), 1, False).entry(0) is workset
    assert "_ids" not in pool.to_dict()


class _WireReads(dict):
    gets = 0

    def get(self, key, *args):
        type(self).gets += 1
        return super().get(key, *args)


class _PlannedReads(tuple):
    visits = 0

    def __iter__(self):
        for item in super().__iter__():
            type(self).visits += 1
            yield item


def _materialized(count):
    return leaves_to_program([_wall(str(100000 + index)) for index in range(count)],
                             chunk_target=count)


@pytest.mark.parametrize("count", [128, 1000, 5000])
def test_lineage_joins_each_wire_and_planned_operation_once(count, monkeypatch):
    result = _materialized(count)
    assert all(plan is not None for plan in result.plans)
    wire = result.programs
    for program in wire:
        program["ops"] = [_WireReads(op) for op in program["ops"]]
    # These wrappers only count reads; all fields and plan digests remain equal.
    monkeypatch.setattr(MaterializeResult, "programs", property(lambda _: wire))
    for plan in result.plans:
        object.__setattr__(plan, "ops", _PlannedReads(plan.ops))
    _WireReads.gets = _PlannedReads.visits = 0
    started = perf_counter()
    view = lineage.derive_lineage(result)
    elapsed = perf_counter() - started
    assert len(view.rows) == count
    assert [(row.source_element_id, row.kir_op_id) for row in view.rows] == [
        (record.source_id, record.op_id) for record in result.accounting.records]
    assert all(row.runtime_element_ids is None for row in view.rows)
    assert _WireReads.gets <= 2 * count
    assert _PlannedReads.visits <= count
    print(f"lineage n={count} wire_gets={_WireReads.gets} "
          f"plan_visits={_PlannedReads.visits} seconds={elapsed:.6f}")


@pytest.mark.parametrize("fault", ["wire_duplicate", "wire_missing", "plan_duplicate", "plan_missing"])
def test_lineage_index_does_not_turn_damaged_carriers_into_first_or_last_wins(fault):
    result = _materialized(1)
    op_id = result.accounting.records[0].op_id
    # Valid constructors already refuse duplicate IDs. Corrupt a retained carrier
    # deliberately to exercise the projection's existing second-line refusal.
    if fault.startswith("wire"):
        wire = result.programs
        wire[0]["ops"] = (wire[0]["ops"] * 2 if fault.endswith("duplicate") else [])
        object.__setattr__(result, "_programs_json", (json.dumps(wire[0]),))
        expected = f"materialization op {op_id} is not unique in wire"
    else:
        plan = result.plans[0]
        object.__setattr__(plan, "ops", plan.ops * 2 if fault.endswith("duplicate") else ())
        expected = f"plan does not preserve materialization op {op_id}"
    with pytest.raises(lineage.LineageError) as caught:
        lineage.derive_lineage(result)
    assert str(caught.value) == expected


class _ComparedAddress(str):
    comparisons = 0
    hashes = 0

    def __eq__(self, other):
        type(self).comparisons += 1
        return super().__eq__(other)

    def __hash__(self):
        type(self).hashes += 1
        return super().__hash__()


@pytest.mark.parametrize("count", [128, 1000, 5000])
def test_bad_phase_partition_is_explained_without_counting_each_id_again(count):
    ids = [_ComparedAddress(f"op_{index:05d}") for index in range(count)]
    phase_ids = ids[1:] + [ids[-1]]
    program = {"ops": [{"op": "create_level", "id": item, "elev_mm": 0} for item in ids],
               "phases": [{"index": 0, "name": "scope", "op_ids": phase_ids}]}
    _ComparedAddress.comparisons = _ComparedAddress.hashes = 0
    started = perf_counter()
    with pytest.raises(KirRefusal) as caught:
        compiler.split_phases(program)
    elapsed = perf_counter() - started
    diagnostic = caught.value.diagnostics[0]
    assert diagnostic.candidates == [ids[0]]
    assert f"не попали в план: {ids[0]}" in diagnostic.message_ru
    assert f"названы дважды: {ids[-1]}" in diagnostic.message_ru
    assert _ComparedAddress.comparisons <= 4 * count
    assert _ComparedAddress.hashes <= 12 * count
    print(f"phases n={count} comparisons={_ComparedAddress.comparisons} "
          f"hashes={_ComparedAddress.hashes} seconds={elapsed:.6f}")
