# -*- coding: utf-8 -*-
"""A PATH TO THE GROUND HAS NO RIGHT TO LEAN ON A LANDING THAT NOBODY READ.

🔴 WHAT IS RED HERE, BY THE 07.09.2026 MEASUREMENT (a continuation of the wave
"an egress verdict may not stand on a guessed function"). That wave taught
HAB003/HAB010 to ask the REACHED landing for its provenance. What must be
asked is the PATH.

THE DISCRIMINATOR, REPRODUCED BY EXECUTION. A three-story building, the
landing of the MIDDLE floor L1 recognized by furnishing
(`function_source="fixtures"`):

    unverifiable_levels()          -> 1 level (L1)
    L1: a path to the ground exists,  by what was read — NO
    L2: a path to the ground exists,  by what was read — NO   <- NOT NAMED
    HAB010 coverage: EVALUATED(n=2, x=1)   building verdict: PASS

L2 reads as "connected to the ground by what was read," yet it has exactly
one way down — through a landing whose stair-ness was named by a toilet
fixture. The price over 14 runs (N=3..6 × a guessed landing on every
intermediate floor): 20 levels went UNNAMED, HAB003's apartments went UNNAMED
for 34 out of 34 — `unverifiable_apartments` looks only at the ground-level
landing and named NOT A SINGLE ONE across these 14 runs.

The engine's classification-coverage note does not catch this: it is
threshold-based (0.75), and one guessed landing does not move it. So the
building prints PASS.

🔴 THE SECOND RED ITEM, POINT (a). HAB010's `RuleSpec` counted ALL occupied
levels as subjects, while the rule's body `continue`s past the ground level on
its very first line. 17 out of 25 buildings in the fixture corpus are
single-story, and all 17 printed `EVALUATED(n=1), 0 violations` —
"judged and clean" about something it never judged.

The emptiness of a single-story building is of the SECOND kind
(`RuleSpec.vacuous_reason`): not "we did not ask," but "we asked, and the
building answered: there is nothing to hang from." The engine's carrier of
this distinction is `mandatory`, not `status` (the HAB011 precedent), so both
fields are fixed together: the coverage line tells the truth, and the
single-story verdict does not collapse.

🔴 THE THIRD AND FOURTH, POINT (b). HAB031 shared a counter with HAB030 and
printed `EVALUATED(n=2)` on `bad_open_envelope`, where its body examined ZERO
rooms (a discrepancy on 3 buildings out of 25, 80 versus 76). And HAB062 stayed
silent about a room whose function was named by furnishing: it leaves
`unclassified`, and "rules were applied" stays true about application and a
lie about authority.

Run: KIR_CHECKER_V2=1 pytest \
  kir/checker/tests/test_a_path_to_ground_may_not_lean_on_a_guessed_landing.py -q
"""
from __future__ import annotations

import copy

import networkx as nx
import pytest

from kir.checker import engine
from kir.checker.derive import derive
from kir.checker.fixtures import builders
from kir.checker.graph import build_graph, ground_level_ids, occupied_levels
from kir.checker.rules.connectivity import (
    unverifiable_apartments,
    unverifiable_levels,
)
from kir.checker.spatial_model import RoomFunction, SpatialModel
from kir.checker.thresholds import THRESHOLDS


@pytest.fixture(autouse=True)
def _v2(monkeypatch):
    """The lever is set FOR THE DURATION OF THE TEST: a `setenv` in the header leaked into other files."""
    monkeypatch.setenv("KIR_CHECKER_V2", "1")


def _угадать_площадку(d: dict, level_id: str) -> dict:
    d = copy.deepcopy(d)
    for r in d["rooms"]:
        if r["function"] == "лестница" and r["level_id"] == level_id:
            r["function_source"] = "fixtures"
    return d


def _разобрать(d: dict):
    m = SpatialModel.model_validate(d)
    dm, drep = derive(m, THRESHOLDS)
    g = build_graph(dm, exclude_door_ids=drep.dropped_door_ids)
    return m, dm, drep, g


# --------------------------------------------------------------- (c) a path, not a point

class ПутьКЗемлеСпрашиваетсяЦеликом:
    pass


class TestПромежуточнаяПлощадкаНазываетВСЕЭтажиНадНей:
    """L1 is guessed — so L2, whose only way down goes through it, is NOT confirmed either."""

    def test_hab010_называет_оба_уровня(self) -> None:
        _, dm, _, g = _разобрать(_угадать_площадку(
            builders.stacked_floors(3, stairs=True), "L1"))
        сколько, почему = unverifiable_levels(dm, g)
        assert сколько == 2, (
            f"названо {сколько} уровней вместо 2: у L2 единственный спуск идёт "
            f"через угаданную площадку L1. Причина: {почему!r}")
        assert "L2" in почему, f"L2 не назван поимённо: {почему!r}"

    def test_hab003_называет_квартиры_верхних_этажей(self) -> None:
        from kir.checker.graph import derive_apartments
        _, dm, _, g = _разобрать(_угадать_площадку(
            builders.stacked_floors(3, stairs=True), "L1"))
        apts = derive_apartments(dm, g)
        сколько, почему = unverifiable_apartments(dm, g, apts)
        assert сколько >= 2, (
            f"HAB003 назвал {сколько} квартир из >=2: выход у квартир L1 и L2 "
            f"подтверждается только угаданной площадкой. Причина: {почему!r}")

    def test_ребро_лестницы_несёт_провенанс(self) -> None:
        """Provenance is read ON THE EDGE, while the topology stays the same."""
        _, dm, drep, g = _разобрать(_угадать_площадку(
            builders.stacked_floors(3, stairs=True), "L1"))
        _, dm0, drep0, g0 = _разобрать(builders.stacked_floors(3, stairs=True))
        assert (g.number_of_nodes(), g.number_of_edges()) == (
            g0.number_of_nodes(), g0.number_of_edges()), (
            "пометка провенансом СМЕНИЛА топологию — этого делать нельзя")
        рёбра = [(a, b, d) for a, b, d in g.edges(data=True)
                 if d.get("kind") == "stair"]
        assert рёбра, "вертикальных рёбер нет вовсе — модель не о том"
        assert all("provenance" in d for _, _, d in рёбра), (
            f"на вертикальном ребре нет поля provenance: {рёбра[:2]}")
        угаданные = [(a, b) for a, b, d in рёбра if d["provenance"] != "read"]
        assert len(угаданные) == 2, (
            f"угаданной площадки L1 касаются два марша, помечено {len(угаданные)}")

    def test_контроль_все_площадки_прочитаны_молчание(self) -> None:
        """CONTROL: with not a single guess, the rule is obligated to STAY SILENT."""
        _, dm, _, g = _разобрать(builders.stacked_floors(3, stairs=True))
        assert unverifiable_levels(dm, g)[0] == 0
        from kir.checker.graph import derive_apartments
        assert unverifiable_apartments(dm, g, derive_apartments(dm, g))[0] == 0


# ------------------------------------------------------------------ (a) single-story building

class TestОдноэтажкаНеСудитсяHAB010:
    """Zero occupied NON-GROUND levels — nothing to judge, and this is a fact about the building."""

    def _покрытие(self, d: dict):
        rep = engine.run(SpatialModel.model_validate(d), THRESHOLDS)
        return rep, {o.rule_id: o for o in rep.coverage.outcomes}["HAB010"]

    def test_счётчик_не_считает_наземный_уровень(self) -> None:
        rep, o = self._покрытие(builders.make_good())
        assert o.n_subjects == 0, (
            f"HAB010 объявил {o.n_subjects} субъекта на ОДНОУРОВНЕВОМ здании, "
            f"а тело правила `continue`-ит наземный уровень первой строкой")
        assert o.status.value == "not_evaluated"

    def test_причина_называет_ИМЕННО_ЭТУ_пустоту(self) -> None:
        _, o = self._покрытие(builders.make_good())
        assert "одноуровнев" in o.reason or "наземн" in o.reason, (
            f"причина не различает «уровней нет вовсе» и «все уровни наземные»: "
            f"{o.reason!r}")

    def test_вердикт_одноэтажки_остаётся_PASS(self) -> None:
        """A known clean result must not dare become "unknown"."""
        rep, _ = self._покрытие(builders.make_good())
        assert rep.verdict.value == "pass", (
            f"эталон уехал в {rep.verdict.value}: правило, которому нечего "
            f"судить, обязано снимать с себя ОБЯЗАТЕЛЬНОСТЬ, а не вето́вать")

    def test_многоэтажка_считает_только_неназемные(self) -> None:
        _, o = self._покрытие(builders.stacked_floors(3, stairs=True))
        assert o.n_subjects == 2, f"занятых неназемных уровней 2, объявлено {o.n_subjects}"
        assert o.status.value == "evaluated"


# -------------------------------------------------------------------- (b) function

class TestHAB031СчитаетСвоюСовокупность:
    def test_счётчик_не_расходится_с_телом(self) -> None:
        rep = engine.run(
            SpatialModel.model_validate(builders.bad_open_envelope()), THRESHOLDS)
        o = {x.rule_id: x for x in rep.coverage.outcomes}["HAB031"]
        assert o.n_subjects == 0, (
            f"HAB031 объявил {o.n_subjects} субъекта, а тело рассмотрело НОЛЬ: "
            f"ни одна жилая/кухня этого здания не несёт измеренного остекления")
        assert o.status.value == "not_evaluated"

    def test_находка_называет_источник_функции(self) -> None:
        d = copy.deepcopy(builders.bad_low_daylight())
        for r in d["rooms"]:
            if r["function"] in ("жилая", "кухня"):
                r["function_source"] = "fixtures"
        rep = engine.run(SpatialModel.model_validate(d), THRESHOLDS)
        находки = [v for v in rep.info if v.rule_id == "HAB031"]
        assert находки, "HAB031 не сказал ни слова о заниженном остеклении"
        assert any("обстановки" in v.msg or "не называл" in v.msg for v in находки), (
            f"HAB031 судит норму по функции, которой автор не называл, и молчит "
            f"об источнике: {[v.msg for v in находки][:1]}")


class TestHAB062ГоворитОВыведеннойФункции:
    def _отчёт(self):
        d = copy.deepcopy(builders.make_good())
        for r in d["rooms"]:
            r["function_source"] = "fixtures"
        return engine.run(SpatialModel.model_validate(d), THRESHOLDS)

    def test_выведенная_функция_звучит(self) -> None:
        rep = self._отчёт()
        строки = [v for v in rep.warnings if v.rule_id == "HAB062"]
        assert строки, (
            "HAB062 молчит о здании, где функцию КАЖДОГО помещения назвала "
            "обстановка: из `unclassified` такая комната уходит, и молчание "
            "неотличимо от молчания о прочитанном здании")

    def test_строка_ОДНА_и_несёт_число(self) -> None:
        rep = self._отчёт()
        строки = [v for v in rep.warnings if v.rule_id == "HAB062"]
        assert len(строки) == 1, (
            f"HAB062 выдал {len(строки)} строк вместо одной сводной — на корпусе "
            f"это 236 находок из 276 комнат, читатель видит три")
        assert any(ch.isdigit() for ch in строки[0].msg), (
            f"сводная строка обязана нести ЧИСЛО: {строки[0].msg!r}")

    def test_контроль_прочитанное_здание_молчит(self) -> None:
        """FAIL CONTROL by mutation: the same fixture with an authored function — silent."""
        rep = engine.run(
            SpatialModel.model_validate(builders.make_good()), THRESHOLDS)
        assert not [v for v in rep.warnings if v.rule_id == "HAB062"], (
            "HAB062 заговорил о здании, где функцию назвал автор — прибор "
            "сработал бы на чём угодно")
