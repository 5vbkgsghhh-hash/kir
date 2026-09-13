# -*- coding: utf-8 -*-
"""Пресохранение документа владельцем — не подмена элемента.

🔴 ЧТО ЭТО ЗАКРЫВАЕТ. `Element.VersionGuid` (RevitAPI.xml 2023) живёт периодами
«between two saves, synchronize to central and reload latest», и документация в
том же абзаце говорит прямо: «in an opened document in-between saves or
synchronize actions, this version cannot be used to determine if any particular
element has changed».

Отсюда два отказа прибора, и до 13.09.2026 провод нёс оба:

* ВНУТРИ СЕССИИ версия не двигается на правке — страж не может сработать, когда
  должен. Подтверждено живьём на «Проект1» 13.09: правка параметра без
  сохранения, `version_guid_moved = false` при `identity_held = true`
  (`.work/prod-20260913/live-window/receipt-01-version-guid-*.json`).
* ЧЕРЕЗ СОХРАНЕНИЕ версия уходит вперёд у ВСЕХ элементов, не тронув ни одного —
  страж срабатывает, когда не должен. Обе половины отказывали одним кодом
  `identity_changed_since_read`, поэтому сохранение файла было неотличимо от
  подмены элемента, и повторная публикация отказывалась целиком, назвав
  изменение, которого не было.

Форма (слово ведущего 13.09.2026): `unique_id` — обязателен и единственное
сильное поле; `version_guid` — необязателен, «версия СОХРАНЁННОГО файла, не
свежесть»; сравнение версии — opt-in, по умолчанию выключено; свой код отказа.
Страж значения внутри сессии — `expected_current`, и только он.
"""
import pytest

from kir.emit_core import IDENTITY_VERSION_CODE

UID_A = "7ff4b512-b299-4d75-8107-62effd492f45-00042fe4"
UID_B = "7ff4b512-b299-4d75-8107-62effd492f45-00042fff"
GUID_A = "7ff4b512b2994d75810762effd492f45"
GUID_B = "0123456789abcdef0123456789abcdef"


def compiled(expected, **extra):
    """The real compiler, the real snapshot — no hand-built C#."""
    from kir import compile_program
    from kir.tests.fixtures import GROUND_SNAPSHOT

    op = {"op": "set_param", "id": "m", "param": "Комментарии", "value": "v",
          "target": {"by": "element_id", "value": 274502}, **extra}
    if expected is not None:
        op["expected_identity"] = expected
    return compile_program({"ops": [op]}, revit_version="2023",
                           snapshot=GROUND_SNAPSHOT, isolation="atomic")


# ── (а) в сессии правка без сохранения не даёт ложного «изменился» ──────────

def test_a_base_without_a_version_guards_identity_and_leaves_the_value_to_expected_current():
    """Личность стережётся, версия не упоминается вовсе."""
    result = compiled({"unique_id": UID_A})
    assert result.ok, result.diagnostics
    assert "identity_changed_since_read" in result.csharp
    assert 'VersionGuid' not in result.csharp, (
        "версии в базе нет — сравнивать нечего, и упоминать нечего")
    assert IDENTITY_VERSION_CODE not in result.csharp


def test_a_carried_version_is_not_compared_unless_the_op_asks():
    """🔴 ГЛАВНЫЙ ПИН (а). Квитанция НЕСЁТ версию — провод её НЕ сверяет.

    Это и есть разделение «носить» и «читать как страж»: правило «квитанция несёт
    то, что знал ПРОИЗВОДИТЕЛЬ» остаётся в силе, а вывод из неё больше не делается.
    """
    result = compiled({"unique_id": UID_A, "version_guid": GUID_A})
    assert result.ok, result.diagnostics
    assert result.csharp.count("identity_changed_since_read") == 1
    assert 'VersionGuid.ToString("N")' not in result.csharp, (
        "версия по умолчанию НЕ сверяется: внутри сессии она не двигается на "
        "правке, а после сохранения двигается без правки")
    assert IDENTITY_VERSION_CODE not in result.csharp
    # ...и страж значения на месте, потому что внутри сессии он единственный.
    assert "expected_current" not in result.csharp  # не заявлен этой опой
    assert "query_element_state" in result.csharp


def test_the_value_guard_is_the_one_that_works_in_session():
    """`expected_current` — то, что живьём сработало (§3 окна 13.09)."""
    result = compiled({"unique_id": UID_A, "version_guid": GUID_A},
                      expected_current="старое")
    assert result.ok, result.diagnostics
    assert "value_changed_since_read" in result.csharp
    assert 'VersionGuid.ToString("N")' not in result.csharp


# ── (б) другая версия при том же unique_id ─────────────────────────────────

def test_by_default_a_moved_version_is_not_a_refusal_at_all():
    """Сохранение владельца не порождает стража, которому нечего стеречь."""
    result = compiled({"unique_id": UID_A, "version_guid": GUID_B})
    assert result.ok, result.diagnostics
    assert GUID_B not in result.csharp, "несверяемая версия в код не попадает"
    assert IDENTITY_VERSION_CODE not in result.csharp


def test_with_opt_in_the_version_refuses_by_its_OWN_code_and_says_a_save_happened():
    """🔴 ГЛАВНЫЙ ПИН (б). Два стража, два кода, два разных следующих хода."""
    result = compiled({"unique_id": UID_A, "version_guid": GUID_A,
                       "compare_version": True})
    assert result.ok, result.diagnostics
    assert 'VersionGuid.ToString("N")' in result.csharp
    assert IDENTITY_VERSION_CODE in result.csharp
    # Версия НЕ переиспользует код личности: иначе сохранение снова читалось бы
    # как подмена, ради чего всё и делалось.
    assert result.csharp.count("identity_changed_since_read") == 1, (
        "личность — один раз; версия говорит СВОИМ кодом")
    assert "сохранением/синхронизацией" in result.csharp, (
        "отказ обязан назвать, что именно произошло")
    assert "перечитай элемент и повтори" in result.csharp


def test_control_asking_to_compare_nothing_is_refused_by_name():
    """Молчаливое «стража нет» опаснее отказа: автор думал, что он стоит."""
    result = compiled({"unique_id": UID_A, "compare_version": True})
    assert not result.ok
    text = " ".join(d.message_ru for d in result.diagnostics)
    assert "compare_version" in text and "version_guid" in text


# ── (в) другой unique_id — по-прежнему identity_changed_since_read ──────────

def test_a_different_unique_id_is_still_the_identity_refusal():
    """🔴 ГЛАВНЫЙ ПИН (в). Сильное поле не ослаблено ничем из вышесказанного."""
    result = compiled({"unique_id": UID_B})
    assert result.ok, result.diagnostics
    assert "identity_changed_since_read" in result.csharp
    assert UID_B in result.csharp
    assert IDENTITY_VERSION_CODE not in result.csharp
    assert "query_element_state" in result.csharp


def test_the_identity_half_is_present_in_every_accepted_shape():
    """Ни одна из трёх форм базы не оставляет личность без стража."""
    for base in ({"unique_id": UID_A},
                 {"unique_id": UID_A, "version_guid": GUID_A},
                 {"unique_id": UID_A, "version_guid": GUID_A, "compare_version": True}):
        result = compiled(base)
        assert result.ok, (base, result.diagnostics)
        assert result.csharp.count("identity_changed_since_read") == 1, base
        assert UID_A in result.csharp, base


def test_control_a_base_without_unique_id_is_refused():
    """Единственное сильное поле обязано быть."""
    result = compiled({"version_guid": GUID_A})
    assert not result.ok
    assert "unique_id" in " ".join(d.message_ru for d in result.diagnostics)
