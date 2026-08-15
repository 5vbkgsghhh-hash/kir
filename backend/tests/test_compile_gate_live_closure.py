"""Ворота компиляции должны принимать КАЖДУЮ сборку из белого списка — проверка
на ЖИВОЙ службе, а не на исходниках.

ЗАЧЕМ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ — замер 13.08.2026.

`AdWindows` и `UIFramework` добавлены в оба компилятора 09.08 по прямой просьбе
оператора: агенту нужна лента Ревита. Клиент их получил. Серверные ворота — нет:
службу не пересобрали, и работающий бинарь остался от 22.07, на восемнадцать дней
старше правки. Четыре дня любой код с `Autodesk.Windows` умирал на предкомпиляции
с `CS0234`, а модель, увидев отказ, переписывала его в заглушку
«лента недоступна». Возможность существовала в исходнике, в тестах и в пакете
клиента — и не существовала там, где решается.

Соседний `test_assembly_whitelist_sync.py` всё это время был ЗЕЛЁНЫМ и остался бы
зелёным: он сравнивает два списка в ИСХОДНИКАХ. Против расхождения исходников он
работает, против расхождения исходника с артефактом — нет по построению.

Поэтому здесь проверяется единственное, что решает: живая служба на localhost
компилирует тип ИЗ КАЖДОЙ сборки списка. Ложный ноль тут невозможен — у пробы
есть оба контроля (см. ниже).

Отдельно про зонды: сначала наличие строки в бинаре я проверял `strings`, и он
давал НОЛЬ и до, и после починки — .NET хранит строки в UTF-16, а `strings` по
умолчанию ищет ASCII. Правильный ответ дал `strings -el` с контрольной строкой,
заведомо присутствующей в обоих бинарях. Мораль та же, что и у всего файла:
отрицательный результат сначала объясняется охватом прибора.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

GATE_URL = os.getenv("KUKAI_COMPILE_SERVICE_URL", "http://127.0.0.1:52412") + "/compile"

# Тип, живущий ИМЕННО в этой сборке. Подобраны замером по живой службе 13.08,
# а не по памяти: три правдоподобных кандидата на UIFramework
# (ExternalCommandDispatcher, ApplicationUI, RevitCommandExecutor) дали CS0234.
# Если тип переименуют в новой версии Ревита, тест покраснеет — и это верное
# поведение: значит поверхность изменилась и её надо пересмотреть осознанно.
ASSEMBLY_PROBES = {
    "RevitAPI": "Autodesk.Revit.DB.Wall",
    "RevitAPIUI": "Autodesk.Revit.UI.UIDocument",
    "AdWindows": "Autodesk.Windows.ComponentManager",
    "UIFramework": "UIFramework.RevitRibbonControl",
}

# Обе границы платформы: net48 (2021-2024, 43% замеренных ходов) и net8.
VERSIONS = ("2021", "2026")


def _compile(code: str, version: str) -> dict:
    body = json.dumps({"code": code, "revitVersion": version}).encode()
    req = urllib.request.Request(
        GATE_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _gate_alive() -> bool:
    try:
        return _compile("public class T { public static int R() { return 1; } }", "2026").get(
            "success"
        ) is True
    except (urllib.error.URLError, OSError, ValueError):
        return False


pytestmark = pytest.mark.skipif(
    not _gate_alive(),
    reason="служба компиляции не отвечает — проверять нечего (это факт о среде, не о коде)",
)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("assembly,type_name", sorted(ASSEMBLY_PROBES.items()))
def test_gate_accepts_every_whitelisted_assembly(assembly: str, type_name: str, version: str) -> None:
    """Живые ворота обязаны принимать тип из каждой сборки белого списка."""
    result = _compile(
        f"public class T {{ public static System.Type R() {{ return typeof({type_name}); }} }}",
        version,
    )
    assert result.get("success"), (
        f"Ворота НЕ знают сборку {assembly} на Ревите {version} "
        f"(проба: {type_name}). Почти наверняка службу не пересобрали после "
        f"правки списка ссылок — ровно случай 09.08→13.08. "
        f"Ошибки: {result.get('errors')}"
    )


def test_control_gate_still_compiles_ordinary_code() -> None:
    """КОНТРОЛЬ-PASS: если ворота вдруг принимают всё подряд, зелёный выше пуст."""
    assert _compile("public class T { public static int R() { return 2+2; } }", "2026")["success"]


def test_control_gate_still_rejects_broken_code() -> None:
    """КОНТРОЛЬ-FAIL: прибор обязан уметь краснеть.

    Без него «все сборки приняты» неотличимо от «ворота перестали проверять».
    """
    result = _compile('public class T { public static int R() { return "строка"; } }', "2026")
    assert not result.get("success"), "Ворота приняли заведомо битый код — они больше не ворота"
    assert any(e.get("code") == "CS0029" for e in result.get("errors") or [])


def test_control_probe_can_see_a_missing_assembly() -> None:
    """КОНТРОЛЬ ОХВАТА: проба обязана заметить ОТСУТСТВУЮЩУЮ сборку.

    Иначе зелёный по всем четырём сборкам может означать не «все на месте», а
    «проба не умеет находить пропажу» — та самая форма, где прибор врёт своему
    автору.
    """
    result = _compile(
        "public class T { public static System.Type R() { return typeof(Nowhere.Nothing.Missing); } }",
        "2026",
    )
    assert not result.get("success")
    assert any(e.get("code") == "CS0246" for e in result.get("errors") or []) or any(
        e.get("code") == "CS0234" for e in result.get("errors") or []
    )
