"""ОТКАЗ ПРИБОРА — ТРЕТИЙ ИСХОД, И ЕГО НЕЛЬЗЯ СПУТАТЬ НИ С ЗЕЛЁНЫМ, НИ С КРАСНЫМ.

РЕШЕНИЕ ВЛАДЕЛЬЦА 16.08.2026, и вот чем оно куплено. В тот день ворота
`kir-evidence` впервые за 175 прогонов реально запустились (до этого файл не
разбирался GitHub'ом: `${{ runner.temp }}` стоял в `env:` уровня джоба). Первый
же честный прогон упал `exit 1` — и упал НЕ на компиляторе:

* `gate_runner`, нога «настоящий документ»: корпус машинно-локален, в чекаут не
  входит, на раннере его нет и быть не может;
* `scripts/kir_gap_compile_matrix.py`, строка `place_family`: каталогу пула
  `family_symbols` нужен ЖИВОЙ этап разведки (`--discover`), которого на разовой
  машине CI тоже нет.

Шесть ячеек из 156 роняли прогон по причине, которую CI устранить НЕ МОЖЕТ. А
ворота, красные ВСЕГДА, — не ворота: их красный перестают читать, и следующий
настоящий дефект уезжает в прод под тем же красным («красный по известной
причине прячет следующий»).

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ, И ПОЧЕМУ ИМЕННО ТАК:

1. отказ прибора НЕ считается дефектом (`fail_cells`) и не роняет прогон;
2. и при этом НЕ становится тихим зелёным: число отказавших строк печатается
   ВСЕГДА, включая ноль, а превышение бюджета `REFUSAL_BUDGET_ROWS` роняет
   прогон ОТДЕЛЬНЫМ текстом — про отказ прибора, а не про компилятор;
3. вырожденный исход «собрано 0, отказало всё» — НЕ зелёный: третий код
   возврата, по образцу `tools/build_client.py` (0 собрано · 1 дефект · 2 прибор
   не отработал).

🔴 ВХОД СТРОИТСЯ ПРОД-КОДОМ (форма 27). Тест зовёт настоящий `main()` с
настоящим офлайновым каталогом, а не собирает фикстуру руками. Сеть при этом не
нужна ВООБЩЕ: отказавшая строка отсеивается ДО обращения к Roslyn, поэтому
`--only place_family` исполняет ровно ту ветку, которая упала в CI, и ни одной
чужой.
"""
from __future__ import annotations

import io
import contextlib

import pytest

from kukai.ir import gate_runner
from scripts import kir_gap_compile_matrix as M

_REFUSING_ROW = "place_family"


def _run(argv: list[str]) -> tuple[int, str]:
    """Настоящий прогон прод-кода; возвращает (код возврата, весь вывод)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = M.main(argv)
    return rc, buf.getvalue()


def test_the_subject_still_refuses_offline():
    """ПРЕДПОСЫЛКА, ПРОВЕРЯЕМАЯ ЯВНО, А НЕ ПОДРАЗУМЕВАЕМАЯ.

    Если каталог пула однажды доразведают и строка начнёт собираться, все
    проверки ниже станут вакуумными — зелёными на предмете, которого больше
    нет. Тогда этот тест обязан покраснеть первым и сказать, что случилось,
    а не тихо охранять пустоту.
    """
    rows = M.resolved_rows("all", {_REFUSING_ROW})
    assert rows, f"строки «{_REFUSING_ROW}» нет в матрице — предмет исчез"
    name, program, why = rows[0]
    assert name == _REFUSING_ROW
    assert program is None, (
        f"«{_REFUSING_ROW}» теперь СОБИРАЕТСЯ офлайн — предпосылка этого файла "
        f"исчезла. Это хорошая новость, но проверки ниже стали вакуумными: "
        f"выбери другую отказывающую строку или сними файл.")
    assert "family_symbol" in str(why)


def test_instrument_refusal_is_not_a_defect():
    """ГЛАВНОЕ: отказ прибора не роняет прогон и не притворяется сборкой."""
    rc, out = _run(["--set", "all", "--only", _REFUSING_ROW])
    assert "ОТКАЗ ПРИБОРА" in out, out
    assert "НЕ СОБРАНО (дефект)       0" in out, (
        "отказ прибора попал в счётчик ДЕФЕКТОВ — это обвинение компилятора "
        f"в том, чего он не делал:\n{out}")
    assert rc != 1, f"отказ прибора прочитан как дефект (rc={rc}):\n{out}"


def test_refusal_beyond_budget_reddens_and_says_why():
    """ОБРАТНЫЙ ПОЛЮС: послабление не должно стать глушилкой.

    Без этой проверки «не роняем на отказе» вырождается в «не роняем никогда»,
    и рост того, чего мы НЕ ПРОВЕРЯЕМ, станет невидимым.
    """
    rc, out = _run(["--set", "all", "--only", _REFUSING_ROW,
                    "--max-refused-rows", "0"])
    assert rc == 1, f"бюджет отказов не сработал (rc={rc}):\n{out}"
    assert "КРАСНО ПО ОТКАЗАМ" in out, out
    assert "Компилятор здесь ни при чём" in out, (
        "прогон упал по отказу прибора, но текст не отличает это от дефекта "
        f"компилятора:\n{out}")


def test_nothing_compiled_at_all_is_not_green():
    """ВЫРОЖДЕННЫЙ ИСХОД: судить было нечего — значит не зелено.

    Именно этот случай канон называет «контроль, зелёный по построению»: ноль
    собранных ячеек и «ЗЕЛЕНО» в одной строке.
    """
    rc, out = _run(["--set", "all", "--only", _REFUSING_ROW])
    assert rc == 2, f"прогон без единой собранной ячейки объявлен зелёным (rc={rc})"
    assert "ОТКАЗ ПРИБОРА ЦЕЛИКОМ" in out, out
    assert "это НЕ зелёный" in out, out


def test_the_refusal_counter_is_total_including_zero():
    """Ноль ОБЯЗАН печататься: «строки нет» и «отказов нет» — разные факты.

    Предмет — `gate_runner.instrument_refusal_line`, вынесенный из обеих веток
    печати ноги «настоящий документ». Ветку с ЖИВЫМ корпусом офлайн исполнить
    нельзя (нужны и корпус, и Roslyn), поэтому проверяется ТОТАЛЬНОСТЬ
    помощника, а не факт его вызова — и это названная граница, а не умолчание.
    """
    zero = gate_runner.instrument_refusal_line(0)
    one = gate_runner.instrument_refusal_line(1, why="корпуса нет")
    for line in (zero, one):
        assert line.strip(), "помощник вернул пустую строку — ноль стал невидим"
        assert "ОТКАЗ ПРИБОРА" in line
    assert zero != one
    assert ": 0" in zero, zero
    assert "корпуса нет" in one, one


def test_the_budget_is_a_ratchet_not_a_blanket():
    """Бюджет обязан быть КОНЕЧНЫМ числом, иначе он ничего не держит."""
    assert isinstance(M.REFUSAL_BUDGET_ROWS, int)
    assert M.REFUSAL_BUDGET_ROWS >= 0
    assert M.REFUSAL_BUDGET_ROWS < 5, (
        "бюджет отказов вырос — это значит, что растёт объём НЕПРОВЕРЯЕМОГО. "
        "Поднимать его можно, но только вместе с записью, ЧТО именно перестало "
        "проверяться и почему это нельзя починить")


def test_refusal_ratchet_binds_identity_and_reason():
    """Один новый отказ не имеет права заменить один исчезнувший незаметно."""
    assert M.expected_instrument_refusal(
        "place_family", "family_symbol: нет поля placement")
    assert not M.expected_instrument_refusal(
        "create_wall", "family_symbol: нет поля placement")
    assert not M.expected_instrument_refusal(
        "place_family", "неожиданная ошибка каталога")
