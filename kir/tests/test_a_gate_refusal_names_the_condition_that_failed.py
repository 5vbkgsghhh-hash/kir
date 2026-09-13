"""ОТКАЗ ГЕЙТА НАЗЫВАЕТ УПАВШЕЕ УСЛОВИЕ, А НЕ ВСЕГДА ФЛАГ.

🔴 ЧЕМ КУПЛЕНО — ЖИВОЙ ХОД ВЛАДЕЛЬЦА 13.09.2026, 19:10:52→19:13:37Z («построй
коробку», ws `634acdb3`). Модель собрала программу из 7 опов, окно КИР её
показало, владелец нажал «Одобрить» — и перенос ответил:

    перенос: программа 1 из 2 — ОТКАЗ … revit_ir недоступен: режим не включён —
    KIR_TOOL=stage2 … перенос остановлен на первом отказе

Флаг при этом БЫЛ выставлен: в том же турне журнал пять раз печатает
`KIR gate open: revit_ir injected`. Упало другое условие — РЕЖИМ (путь переноса
не входил в него; лечится на стороне КУКАЯ). А текст отправил человека
выставлять уже выставленное.

ПРИЧИНА ТЕКСТА — ДВА ИМЕНИ ОДНОГО ФЛАГА. Гейт читает `env.get(_FLAG)` через
таблицу синонимов (`kir/env.py`: `"KIR_TOOL" → "KUKAI_KIR_TOOL"`), а этот текст
читал `os.environ.get(flag)` НАПРЯМУЮ. В проде выставлен `KUKAI_KIR_TOOL`,
поэтому текст видел `off` и ВСЕГДА уходил в ветвь флага. Замер 13.09:
`env.get("KIR_TOOL")` → `stage2`, `os.environ.get("KIR_TOOL")` → `off`.

Аудит H назвал это заранее — §1.6.2, ОТК-41/43: «если кто-то выставит НОВОЕ имя
без старого, гейт откроется, а журнал будет печатать off». Прибор, читающий не
тем именем, которым решает гейт, — наш именной дефект: величина, назвавшая
причину, не та, что приняла решение.
"""
from __future__ import annotations

import pytest

from kir import env, serving


@pytest.fixture
def чистое_окружение(monkeypatch):
    monkeypatch.delenv("KIR_TOOL", raising=False)
    monkeypatch.delenv("KUKAI_KIR_TOOL", raising=False)
    return monkeypatch


class _Режим:
    """Порт контекста хода: ровно один вопрос, на который гейт ждёт ответа."""

    def __init__(self, mode: bool) -> None:
        self._mode = mode

    def kir_mode_active(self) -> bool:
        return self._mode

    def kir_hold_active(self) -> bool:
        return False


def _с_режимом(monkeypatch, mode: bool) -> None:
    from kir import ports

    monkeypatch.setattr(ports, "need",
                        lambda name: _Режим(mode) if name == ports.TURN_CONTEXT
                        else pytest.fail(f"неожиданный порт {name}"))


def test_the_prod_variable_is_seen_and_the_flag_is_not_blamed(чистое_окружение):
    """🔴 РОВНО ЖИВОЙ СЛУЧАЙ: прод ставит `KUKAI_KIR_TOOL`, упал РЕЖИМ."""
    чистое_окружение.setenv("KUKAI_KIR_TOOL", "stage2")
    _с_режимом(чистое_окружение, False)
    текст = serving.admin_gate_message_ru("revit_ir")
    assert "KIR_TOOL=stage2" not in текст, (
        f"отказ винит выставленный флаг — человек пойдёт выставлять "
        f"выставленное: {текст!r}")
    assert "РЕЖИМ" in текст, текст
    assert "кнопкой КИР" in текст, "не назван способ включить режим"


def test_the_flag_is_blamed_only_when_it_really_is_off(чистое_окружение):
    """КОНТРОЛЬ-ПАРА: когда флаг ДЕЙСТВИТЕЛЬНО снят — его и называют. Без этого
    «не винит флаг» зеленело бы и на приборе, который не винит никого."""
    чистое_окружение.setenv("KUKAI_KIR_TOOL", "off")
    _с_режимом(чистое_окружение, True)
    текст = serving.admin_gate_message_ru("revit_ir")
    assert "stage2" in текст and serving._FLAG in текст, текст


def test_the_old_name_alone_still_works(чистое_окружение):
    """Старое имя без нового — тоже видно: таблица синонимов читает оба."""
    чистое_окружение.setenv("KIR_TOOL", "stage2")
    _с_режимом(чистое_окружение, False)
    assert "KIR_TOOL=stage2" not in serving.admin_gate_message_ru("revit_ir")


def test_the_refusal_reads_the_flag_the_way_the_gate_does(чистое_окружение):
    """Две величины, обязанные совпадать, утверждаются ВЫЗОВОМ обеих."""
    чистое_окружение.setenv("KUKAI_KIR_TOOL", "stage2")
    assert env.get(serving._FLAG, "off") == "stage2", "контроль негоден"
    _с_режимом(чистое_окружение, False)
    assert f"{serving._FLAG}=stage2" not in serving.admin_gate_message_ru("revit_ir")


def test_the_device_branch_is_reached_when_flag_and_mode_are_fine(чистое_окружение):
    """Третье условие называется третьим: порядок ветвей совпадает с гейтом."""
    чистое_окружение.setenv("KUKAI_KIR_TOOL", "stage2")
    чистое_окружение.setenv("KUKAI_ADMIN_DEVICES", "")
    _с_режимом(чистое_окружение, True)
    текст = serving.admin_gate_message_ru("revit_ir")
    assert "устройств" in текст, текст


def test_a_gate_without_a_mode_never_blames_the_mode(чистое_окружение):
    """`revit_decompile` стоит за флагом БЕЗ режима: его отказ не смеет
    называть режим (тот же файл уже совершал эту ошибку — см. докстроку)."""
    чистое_окружение.setenv("KUKAI_KIR_DECOMPILE", "stage2")
    чистое_окружение.setenv("KUKAI_ADMIN_DEVICES", "")
    текст = serving.admin_gate_message_ru("revit_decompile",
                                          flag="KIR_DECOMPILE",
                                          needs_mode=False)
    assert "РЕЖИМ" not in текст, текст
    assert "устройств" in текст, текст
