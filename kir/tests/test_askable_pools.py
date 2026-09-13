"""A CATALOG YOU CANNOT QUERY IS A LOOP WITH NO WAY OUT.

The refuting measurement was written FIRST and taken on this tree on
14.08.2026:

    pools declared by the registry (`OpSpec.grounded` of writing ops)    35
    pools accepted by `query_types`                                     27
    ────────────────────────────────────────────────────────────────
    pools the catalog has nothing to ask                                 8

Eight: `ceiling_types`, `railing_types`, `toposolid_types`,
`building_pad_types`, `wall_foundation_types`, `area_reinforcement_types`,
`rebar_bar_types`, `rebar_hook_types`.

WHY THIS IS NOT "NOBODY GOT AROUND TO IT." For the railing and the
toposolid, a document default DOES NOT EXIST BY CONSTRUCTION:
`ElementTypeGroup` contains neither `RailingType` nor `ToposolidType` —
this is already measured and recorded in the registry itself (the site
wave, `ground.MOST_USED_POOLS`). So the author must name the type BY NAME,
has nowhere to learn the names, and no default exists. The only move left
is to guess and get `KIR-G101`/`KIR-G102` back later. A live witness from
the same day: the exam subject ran into `railing_types` and called it «two
sources of truth» — the instrument's schema declared the pool, the
validator rejected it.

THE LAW HELD HERE IS ONE, AND IT IS TWO-SIDED:

    pool a writing op is GROUNDED IN  ⟺  pool that can be QUERIED

Both sides are mandatory, and this is not symmetry for its own sake. Left
to right: the ability to build without the ability to learn the name is
exactly this loop. Right to left: a catalog entry with no matching op
promises the author a choice he will not be able to use.

WHAT THIS TEST DOES NOT CHECK, AND WHY. It does not judge whether the
collector is CORRECT: that is the job of the gate (`gate_runner`), which
compiles the emitted C# on six versions. What is checked here is
COMPOSITION — the one thing compilation cannot see: a missing line
compiles perfectly fine.
"""
from __future__ import annotations

import copy

import pytest

from kir import spec
from kir.compiler import _TYPE_POOL_COLLECTOR_CS


def _declared_pools() -> set[str]:
    """Pools for which the registry grounds at least one op.

    This is read FROM THE REGISTRY, not copied out as a list: a list would
    have drifted from the registry on the very first wave, and it would
    have drifted silently — exactly how these eight accumulated.
    """
    pools: set[str] = set()
    for op in spec.OPS.values():
        for _param, pool, _required in op.grounded:
            if "{category}" in pool:
                pools.update(pool.format(category=c)
                             for c in ("structural", "architectural"))
            else:
                pools.add(pool)
    return pools


def _askable_pools() -> set[str]:
    param = next(p for p in spec.OPS["query_types"].params if p.name == "pool")
    return set(param.choices)


def test_the_measurement_this_file_exists_for_is_not_vacuous():
    """Power control: the denominator is real, not empty.

    The check «all declared pools can be queried» passes trivially if the
    number of declared pools is zero. The number here exists so that the
    registry collapsing to empty reads as a failure, not as a success.
    """
    declared = _declared_pools()
    assert len(declared) >= 35, (
        f"реестр объявляет {len(declared)} пулов заземления — меньше, чем в "
        f"день написания этого теста (35). Если пулы законно убыли, опусти "
        f"число здесь ОСОЗНАННО; если нет — сломан обход `OpSpec.grounded`")


def test_every_pool_a_write_op_grounds_against_can_be_asked():
    """Left to right: we know how to build — we must also know how to
    learn the name."""
    unaskable = sorted(_declared_pools() - _askable_pools())
    assert not unaskable, (
        "пул объявлен реестром для заземления, но `query_types` его не "
        f"принимает: {unaskable}. Автор обязан назвать тип по имени, а узнать "
        "имена ему негде — и у части таких пулов документного умолчания нет "
        "по построению. Добавь пул в `query_types.pool.choices` и его "
        "коллектор в `compiler._TYPE_POOL_COLLECTOR_CS`, перенеся идиому из "
        "`open_model.GROUND_SNAPSHOT_CS`, где она уже проходит ворота")


def test_every_askable_pool_has_a_collector():
    """`_emit_op` fetches the collector with a bare `dict[key]`: a miss is
    a KIR-P000 panic.

    A compiler refusal carrying an `incident_id` instead of a named reason
    is the worst possible answer to a legitimate catalog request, and it
    costs a full round trip.
    """
    missing = sorted(_askable_pools() - set(_TYPE_POOL_COLLECTOR_CS))
    assert not missing, (
        f"`query_types` принимает пулы, для которых нет коллектора: {missing}. "
        "`_emit_op` обращается к таблице по ключу без запаса, то есть это "
        "KeyError -> KIR-P000 «внутренняя ошибка компилятора»")


def test_no_collector_promises_a_pool_nobody_can_ask():
    """Right to left: a catalog entry with no query is a promise made into
    the void."""
    dead = sorted(set(_TYPE_POOL_COLLECTOR_CS) - _askable_pools())
    assert not dead, (
        f"коллектор есть, а `query_types` пул не принимает: {dead}. Такая "
        "строка не достижима ни одним запросом и протухнет незамеченной")


def test_the_eight_pools_this_wave_added_are_present_by_name():
    """A named lock on that very eight.

    The general check above would fail even without names, but the names
    exist here so that an accidental removal of one pool reads as «the
    railing got deleted», not as «something drifted somewhere in the
    registry».
    """
    askable = _askable_pools()
    for pool in ("ceiling_types", "railing_types", "toposolid_types",
                 "building_pad_types", "wall_foundation_types",
                 "area_reinforcement_types", "rebar_bar_types",
                 "rebar_hook_types"):
        assert pool in askable, f"{pool}: каталог снова нельзя спросить"
        assert pool in _TYPE_POOL_COLLECTOR_CS, f"{pool}: коллектор пропал"


def test_the_toposolid_collector_names_no_version_dependent_type():
    """The toposolid is assembled by the CLR type's NAME, not by class,
    and this is a version measurement.

    `ToposolidType` appeared in 2024: on 2021/2022 referencing the name
    gives CS0246, on 2023 it gives CS0122 (the type exists but is
    internal). The workaround is taken verbatim from the snapshot, where
    it already holds across all six versions; a second, independent
    workaround for the same pitfall would have drifted from it on the
    first fix.
    """
    chain = _TYPE_POOL_COLLECTOR_CS["toposolid_types"]
    assert "typeof(ToposolidType)" not in chain, (
        "коллектор толщи назвал версионно-зависимый класс — это CS0246 на "
        "2021/2022 и CS0122 на 2023")
    assert "HostObjAttributes" in chain and "ToposolidType" in chain, (
        "коллектор толщи обязан фильтровать по ИМЕНИ CLR-типа у общего "
        "предка HostObjAttributes")


def test_the_check_itself_can_fail():
    """FAIL control: an instrument that cannot fail certifies nothing.

    The law of the house: every probe must have both a PASS control (the
    tests above) and a FAIL control. Here one pool is removed from a COPY
    of the table, and the check must notice it — otherwise the green
    result above means nothing.
    """
    askable = _askable_pools()
    crippled = copy.deepcopy(askable)
    crippled.discard("railing_types")
    assert sorted(_declared_pools() - crippled) == ["railing_types"], (
        "проверка не заметила отобранный пул — значит она не проверяет то, "
        "ради чего написана")

    collectors = dict(_TYPE_POOL_COLLECTOR_CS)
    collectors.pop("ceiling_types")
    assert sorted(askable - set(collectors)) == ["ceiling_types"], (
        "проверка коллекторов не заметила отобранную строку")


def test_the_new_pools_reach_emission_and_are_not_merely_declared():
    """Declared ≠ makes it through. A pool must produce C#, not just pass
    parsing.

    This is the other end of the seam: `choices` passes the value through
    the validator, while emission pulls the collector from a different
    table. The gap lived exactly between them.
    """
    from kir.compiler import compile_program

    for pool in ("railing_types", "ceiling_types", "toposolid_types"):
        out = compile_program(
            {"ir_version": spec.IR_VERSION,
             "ops": [{"op": "query_types", "id": "q1", "pool": pool}]},
            revit_version="2026")
        assert out.ok, (
            f"{pool}: компиляция запроса каталога отказала — "
            f"{[d.as_dict() for d in out.diagnostics]}")
        assert _TYPE_POOL_COLLECTOR_CS[pool] in out.csharp, (
            f"{pool}: коллектор не доехал до эмитированной C#")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
