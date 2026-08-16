"""КАРДИНАЛЬНЫЙ ИНВАРИАНТ ПРИШПИЛЕН: ``ok`` не бывает без заработанного зелёного.

🔴 ЗАЧЕМ ЭТОТ ФАЙЛ, ЗАМЕРОМ, А НЕ СООБРАЖЕНИЕМ.

Главное обещание продукта — «ноль молчаливо-неверных исходов»: запись зелена
только после подтверждённого коммита, удовлетворённого свидетеля, независимой
приёмки и несбрасываемой терминальной записи. Всё это сходится в ОДНОМ месте —
условии, решающем ``ok``.

Замер 15.08.2026: ``acceptance_session`` встречается в ``serving.py`` **37 раз**
и **НИ РАЗУ во всём дереве тестов** (греп по дереву вне модуля — ноль). То есть
конъюнкцию, на которой держится главное обещание, не проверяло НИЧТО. Побочное
следствие было хуже прямого: любой разрез ``_handle_revit_ir_inner`` (1125
строк, состояние в локалях) оказывался неверифицируем В ПРИНЦИПЕ — сломай он
связку молча, и об этом не сказал бы ни один прогон.

**Условие, у которого нет имени, невозможно пришпилить.** Поэтому 15.08 условие
получило имя — ``serving.green_is_earned`` — чистым вынесением, без изменения
поведения, и этот файл держит его с двух сторон:

* ПРЕДМЕТ — таблица истинности самого предиката;
* ПРОВОДКА — что живая дверь решает ``ok`` ИМЕННО ИМ, а не своей копией
  условия. Без второй половины первая сторожила бы функцию, которую можно
  обойти, не тронув ни одного теста.
"""
from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from kukai.ir import serving
from kukai.ir.outcome import AcceptanceState
from kukai.ir.tests.acceptance_fakes import PassingAcceptanceBridge
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
from kukai.llm.turn_context import kir_mode_active, publish_kir_mode

PROGRAM = {
    "ir_version": "1.0",
    "ops": [{
        "op": "create_wall",
        "id": "W1",
        "p0_mm": [0, 0],
        "p1_mm": [6000, 0],
        "level": {"by": "name", "value": "Этаж 1"},
    }],
}

#: Полный набор условий записи, при котором зелёное ЗАКОННО. Каждый тест ниже
#: гасит РОВНО ОДНО и требует, чтобы зелёное исчезло.
EARNED = dict(
    violations=None,
    family="write",
    has_acceptance_session=True,
    acceptance=AcceptanceState.ACCEPTED,
    journal_error=None,
)


class TestТаблицаИстинностиИнварианта:
    """Предмет: что именно утверждает условие."""

    def test_запись_зелена_когда_сошлось_всё(self):
        assert serving.green_is_earned(**EARNED) is True

    def test_БЕЗ_СЕССИИ_ПРИЁМКИ_ЗЕЛЁНОГО_НЕТ(self):
        """Тот самый член конъюнкции, который не проверял никто.

        Путь записи, забывший подготовить сессию, не становится успешным
        оттого, что переменная осталась ``None``."""
        assert serving.green_is_earned(
            **{**EARNED, "has_acceptance_session": False}) is False

    def test_приёмка_не_сказавшая_accepted_закрывает_зелёное(self):
        for state in (AcceptanceState.INCONCLUSIVE, AcceptanceState.REJECTED):
            assert serving.green_is_earned(
                **{**EARNED, "acceptance": state}) is False, state

    def test_незафсинканная_терминальная_запись_закрывает_зелёное(self):
        """Измеренная в памяти приёмка — не несбрасываемая улика."""
        assert serving.green_is_earned(
            **{**EARNED, "journal_error": "fsync failed"}) is False

    def test_нарушение_постусловия_закрывает_зелёное_и_у_чтения_тоже(self):
        assert serving.green_is_earned(
            **{**EARNED, "violations": ["height mismatch"]}) is False
        assert serving.green_is_earned(
            violations=["x"], family="query", has_acceptance_session=False,
            acceptance=AcceptanceState.NOT_APPLICABLE,
            journal_error=None) is False

    def test_чтение_зелено_без_приёмки_и_это_НЕ_послабление(self):
        """У чтения свой контракт; приёмка к нему не применяется вовсе."""
        assert serving.green_is_earned(
            violations=None, family="query", has_acceptance_session=False,
            acceptance=AcceptanceState.NOT_APPLICABLE,
            journal_error=None) is True


class TestКонтрольТаблицаУмеетРазличать:
    """🔴 Без этого класса таблица выше могла бы быть зелёной по построению.

    Форма 8: эксперимент, у которого один исход, не говорит ничего. Здесь
    ослабленный предикат (без члена о сессии) прогоняется по тем же входам и
    ОБЯЗАН разойтись с настоящим ровно на том, что таблица пришпиливает."""

    @staticmethod
    def _ослабленный(**kw) -> bool:
        if kw["violations"]:
            return False
        if kw["family"] == "query":
            return True
        return (kw["acceptance"] is AcceptanceState.ACCEPTED
                and kw["journal_error"] is None)

    def test_снятие_члена_о_сессии_меняет_ответ_на_пришпиленном_входе(self):
        вход = {**EARNED, "has_acceptance_session": False}
        assert serving.green_is_earned(**вход) is False
        assert self._ослабленный(**вход) is True, (
            "ослабленный предикат обязан ОТЛИЧАТЬСЯ, иначе таблица "
            "сторожит пустоту")

    def test_на_остальных_входах_они_совпадают(self):
        """Контроль сужен: расхождение обязано быть ровно в одном месте, а не
        везде. Широкое расхождение доказывало бы, что я сломал предикат, а не
        что таблица различает нужный член."""
        for вход in (EARNED,
                     {**EARNED, "journal_error": "io"},
                     {**EARNED, "violations": ["v"]}):
            assert serving.green_is_earned(**вход) == self._ослабленный(**вход)


@pytest.fixture
def живая_дверь(tmp_path, monkeypatch):
    observed = kir_mode_active()
    publish_kir_mode(True)
    monkeypatch.setenv("KUKAI_KIR_TOOL", "stage2")
    monkeypatch.setenv("KIR_ACCEPTANCE_EVIDENCE_DIR", str(tmp_path))
    client = mock.Mock()
    client._revit_version = "2026"
    try:
        with mock.patch.object(serving, "_turn_device_id",
                               return_value=serving.ADMIN_DEVICE):
            yield client
    finally:
        publish_kir_mode(observed)


def _прогнать(client):
    bridge = PassingAcceptanceBridge(PROGRAM)

    def execute(_code, op):
        if op == "ground_snapshot":
            return {"result": GROUND_SNAPSHOT}
        if op == "write":
            return {"result": {"ok": True, "W1": {"id": "9001"}}}
        raise AssertionError(op)

    async def fake_exec(_llm, _cb, code, op, _timeout):
        return bridge.dispatch(execute, code, op)

    with mock.patch.object(serving, "_run_declarative", side_effect=fake_exec):
        return asyncio.run(serving.handle_revit_ir(
            {"program": PROGRAM}, client, bridge_callback=None))


class TestЖиваяДверьРешаетИменноЭтимПредикатом:
    """Проводка. Без неё таблица сторожила бы функцию, которую можно обойти."""

    def test_проходящая_запись_зелена(self, живая_дверь):
        """КОНТРОЛЬ: без него тест ниже был бы зелен и на сломанной двери."""
        assert _прогнать(живая_дверь)["ok"] is True

    def test_подмена_предиката_гасит_зелёное_у_настоящей_двери(
            self, живая_дверь):
        """Та же проходящая запись, но предикат сказал «не заработано».

        Если ``ok`` перестанет решаться этой функцией — тест покраснеет, и
        именно это делает таблицу выше не декоративной."""
        with mock.patch.object(serving, "green_is_earned", return_value=False):
            результат = _прогнать(живая_дверь)
        assert результат["ok"] is False
