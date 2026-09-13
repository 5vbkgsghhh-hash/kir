"""ОТКАЗ ПРОДУКТОВОЙ ДВЕРИ НАЗЫВАЕТ ПРИЧИНУ И СЛЕДУЮЩИЙ ХОД, КОТОРЫЙ ЕСТЬ.

🔴 ЧЕМ КУПЛЕНО — ЖИВЫМ ХОДОМ ВЛАДЕЛЬЦА 13.09.2026, 17:14:34→17:18:03Z
(`.work/prod-20260913/K-panel/REPORT.md` §8–9). Ход в режиме КИР «огороди
электрощитовую» кончился 0 элементов, и обе квитанции отказа, ДОСЛОВНО:

    stage=author_script  handoff: null   next_ru: ОТСУТСТВУЕТ
      message_ru = «KIR-B015: каталог документа не подан этому запуску…
                    строка 1: print("LEVELS:", [l for l in model.levels()])»
    err=kir.precondition_unmet   next_ru: ОТСУТСТВУЕТ
      message_ru = «мост вернул ошибку при получении снапшота модели»

Две беды в одном месте: (1) следующего хода нет ни у одной — конституция
требует от отказа ПРИЧИНУ И ХОД; (2) с 13.09 панель Ревита печатает
`message_ru` верхнего уровня ЧЕЛОВЕКУ, и в чат уехали код прибора и СТРОКА
ИСХОДНИКА — та же свалка, на которую владелец ругался 08.09.

ЧТО ЭТОТ ПРИБОР СТОРОЖИТ, ТРЕМЯ АКТАМИ РАЗЛИЧЕНИЯ ПОРОЗНЬ:
  1. у человека на поверхности — суть, а код и строка исходника остались
     прибору, в `diagnostics`;
  2. следующий ход назван У ВСЯКОГО отказа;
  3. назван ход, КОТОРЫЙ ЕСТЬ: палитра режима КИР закрыта тремя именами, и
     отказ по вине СРЕДЫ обязан звать `ask_user`, а не «поправь программу» —
     иначе агент получает ход, которого он сделать не может.
"""
from __future__ import annotations

import pytest

from kir import serving
from kir.sandbox import SandboxRefusal

#: Палитра режима КИР — закрытый список продукта
#: (`kukai/llm/tool_masking.py:253`). Живой замер того же хода:
#: `KIR gate open: … панель режима = ['ask_user', 'revit_ir']`.
ПАЛИТРА = ("revit_ir", "revit_ir_bulk", "ask_user")


def _refusal(blame: str, code: str = "KIR-B015") -> SandboxRefusal:
    return SandboxRefusal(
        code=code,
        message_ru=("каталог документа не подан этому запуску: спрашивать "
                    "нечего. Имена типов и уровней надо называть явно"),
        kind="ПробелЧтения",
        blame=blame,
        line=1,
        line_text='print("LEVELS:", [l for l in model.levels()])',
        script_frames=[1],
    )


def test_the_human_layer_carries_no_code_and_no_source_line():
    out = serving._script_refusal_result(_refusal("author"), {})
    человеку = out["message_ru"]
    assert "KIR-B015" not in человеку, f"код прибора уехал человеку: {человеку!r}"
    assert "print(" not in человеку, f"строка исходника уехала человеку: {человеку!r}"
    assert "строка 1" not in человеку, человеку
    assert "каталог документа не подан" in человеку, "суть отказа потеряна"


def test_the_author_layer_keeps_the_code_and_the_line():
    """КОНТРОЛЬ-ПАРА: суть наверх — не значит «место выбросить». Прибор,
    зелёный оттого, что пропало И ТО И ДРУГОЕ, сторожил бы потерю."""
    out = serving._script_refusal_result(_refusal("author"), {})
    ведущая = out["diagnostics"][0]
    assert "KIR-B015" in ведущая["message_ru"], "код пропал и у прибора тоже"
    assert ведущая["script_line"] == 1
    assert ведущая["script_line_text"] == 'print("LEVELS:", [l for l in model.levels()])'
    assert ведущая["blame"] == "author"


@pytest.mark.parametrize("blame", ["author", "caller", "environment", "ours", "sandbox"])
def test_every_refusal_of_the_author_stage_names_a_next_move(blame):
    out = serving._script_refusal_result(_refusal(blame), {})
    ход = str(out.get("next_ru") or "").strip()
    assert ход, f"отказ по вине {blame!r} не назвал следующего хода"
    assert any("`" + имя + "`" in ход for имя in ПАЛИТРА), (
        f"назван ход вне палитры режима КИР {ПАЛИТРА}: {ход!r}")


def test_the_environment_is_not_told_to_rewrite_the_program():
    """🔴 АКТ РАЗЛИЧЕНИЯ, БЕЗ КОТОРОГО ОСТАЛЬНОЕ ЗЕЛЕНЕЕТ НИ ЗА ЧТО.

    Отказ по вине СРЕДЫ (мост молчит, документ не тот, Revit занят) автор не
    чинит ничем: у него в палитре нет ни одного инструмента, меняющего среду.
    Единственный ход, который у него ЕСТЬ, — сказать человеку. Умолчание
    «поправь программу» вернуло бы через заднюю дверь ровно тот запрет, который
    реестр отказов (`diag.register`) держит по построению.
    """
    среда = serving._script_refusal_result(_refusal("environment"), {})["next_ru"]
    автор = serving._script_refusal_result(_refusal("author"), {})["next_ru"]
    assert "`ask_user`" in среда, среда
    assert "поправь программу" not in среда, среда
    assert "поправь программу" in автор, автор
    assert среда != автор, "вина среды и вина автора получили один и тот же ход"


def test_the_ground_refusal_of_the_live_turn_now_names_a_move():
    """Квитанция №3 живого хода 17:07:55Z — дословно её вход."""
    out = serving._typed_error("ground", "мост вернул ошибку при получении "
                                         "снапшота модели")
    assert out["ok"] is False
    assert out["message_ru"] == "мост вернул ошибку при получении снапшота модели"
    ход = str(out.get("next_ru") or "").strip()
    assert ход, "отказ `ground` по-прежнему называет только причину"
    assert "`ask_user`" in ход, ход
    # Исполнение не начиналось — и об этом сказано, иначе агент не знает,
    # безопасен ли повтор.
    assert out["outcome"]["retry"] == "safe"
    assert "повтор" in ход.lower(), ход


def test_a_branch_that_knows_its_own_move_keeps_it():
    """Умолчание не затирает ветку, которая знает ход точнее: дефект песочницы
    посылает не к `ask_user`, а во ВТОРУЮ ФОРМУ ВХОДА той же двери."""
    out = serving._script_refusal_result(_refusal("sandbox"), {})
    assert "`program`" in out["next_ru"], out["next_ru"]
    assert "песочниц" in out["next_ru"], out["next_ru"]
