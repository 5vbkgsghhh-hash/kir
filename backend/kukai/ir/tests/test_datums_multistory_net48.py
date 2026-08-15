"""Граница многоэтажного марша по net48 — и она НЕ про Revit API.

Все члены `MultistoryStairs` существуют на всех шести версиях, и ворота
компилировали тело 6/6 ЗЕЛЁНЫМ. Отказ стоит по другой причине: весь API
многоэтажного марша типизирован `System.Collections.Generic.ISet<ElementId>`,
а замыкание ссылок РАЗВЁРНУТОГО плагина на net48 `ISet` не содержит —

    declared/net48   43 сборки, 3003 типа, ISet ЕСТЬ
    deployed/net48   42 сборки, 2007 типов, ISet НЕТ

и различаются они РОВНО ОДНОЙ сборкой: `System.dll`. Тело собиралось у нас и
падало бы у пользователя `CS0012`, не назвав виновного, — то есть
молчаливо-неверный исход, которого кардинальный инвариант не допускает.

ЧИНИТЬ В ИСХОДНИКЕ НЕЧЕГО. `CodeCompiler.cs` на HEAD уже держит `System` в
`allowedExactNames`, и его собственный комментарий называет `ISet<>` первым
примером того, что даёт `System.dll`. Расхождение — между HEAD и РАЗВЁРНУТЫМ
ДВОИЧНЫМ ФАЙЛОМ: флот бежит на старом плагине. Профиль `deployed` — честно
названная ИНФЕРЕНЦИЯ по трём живым отказам 04.08.2026, а не снимок машины.

ОТКАЗ ШИРЕ СВОЕЙ ПРИЧИНЫ, И ЭТО ОСОЗНАННО: обновлённому клиенту на 2021-2024
он ЛИШНИЙ. Но эмиттер не знает, какой двоичный файл у пользователя, а хвост
необновлённых замерен и непуст. «Отказ кому-то лишний» против «CS0012 кому-то
молча» кардинальный инвариант решает в одну сторону.

ISet-СВОБОДНОГО ПУТИ НЕТ, И ЭТО ЗАМЕР ПО ИНДЕКСУ ЛОВУШЕК, А НЕ ДОВОД:

    ConnectLevels(ISet<ElementId>)              все 6 версий
    DisconnectLevels(ISet<ElementId>)           все 6
    GetAllConnectedLevels() -> ISet             все 6
    GetAllStairsIds() -> ISet                   все 6
    GetStairsPlacementLevels(Stairs) -> ISet    все 6

Подключить уровни, не назвав `ISet`, нечем: единственный метод подключения
принимает его параметром. Поэтому отказ — не временная мера вместо обхода, а
единственный честный ответ до правки КЛИЕНТА.

УСЛОВИЕ СНЯТИЯ НАЗВАНО, ЧТОБЫ ОТКАЗ НЕ ПЕРЕЖИЛ СВОЮ ПРИЧИНУ. Строка уходит,
когда развёрнутый плагин начнёт ссылаться на `System.dll`. Судья — не память
и не этот файл, а живое замыкание: тест ниже СПРАШИВАЕТ его и краснеет, если
`ISet` там появился. Иначе отказ пережил бы починку и отнимал бы способность,
которая уже вернулась.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from kukai.ir.compiler import compile_program
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
from kukai.ir.tests.test_golden import PROGRAMS

#: Версии на net48 — там развёрнутый плагин не связывает `ISet`.
NET48_VERSIONS = ("2021", "2022", "2023", "2024")
#: Версии на net8 — там связывает, и оп законен.
NET8_VERSIONS = ("2025", "2026")

_PROGRAM = "datums_multistory_stairs"


def _compile(ver: str):
    prog = {k: v for k, v in PROGRAMS[_PROGRAM].items() if k != "__ver__"}
    return compile_program(prog, revit_version=ver, snapshot=GROUND_SNAPSHOT)


class TheBoundaryStandsWhereItWasMeasured(unittest.TestCase):

    def test_net48_refuses_with_a_typed_diagnostic(self):
        for ver in NET48_VERSIONS:
            with self.subTest(ver=ver):
                out = _compile(ver)
                self.assertFalse(out.ok, f"{ver}: тело собралось — отказ пропал")
                codes = {d.code for d in out.diagnostics}
                self.assertIn("KIR-E003", codes, f"{ver}: коды {codes}")

    def test_the_refusal_carries_the_route_and_not_only_the_ban(self):
        """Ошибка обязана называть МАРШРУТ, иначе она сообщает лишь запрет.

        Модель, прочитавшая «недоступно», не знает, что делать дальше; модель,
        прочитавшая «на 2025/2026 работает, на 2021-2024 — отдельная программа
        create_stairs на уровень», знает. Проверяются ОБА адреса маршрута,
        а не наличие слов вообще.
        """
        message = _compile("2021").diagnostics[0].message_ru
        for token in ("обновить плагин", "2025", "create_stairs",
                      "System.dll", "ISet"):
            with self.subTest(token=token):
                self.assertIn(token, message, f"в отказе нет «{token}»: {message}")

    def test_net8_still_emits_and_still_names_iset(self):
        """Контроль-PASS: граница не съела способность там, где она есть.

        Без этой половины отказ, расползшийся на все шесть версий, выглядел бы
        ровно как обычная работа границы.
        """
        for ver in NET8_VERSIONS:
            with self.subTest(ver=ver):
                out = _compile(ver)
                self.assertTrue(out.ok, f"{ver}: оп отказал там, где законен")
                self.assertIn("System.Collections.Generic.ISet", out.csharp,
                              f"{ver}: ISet исчез из эмиссии — тело изменилось, "
                              f"и причина отказа на net48 больше не та")

    def test_the_refusal_dies_with_its_cause(self):
        """Отказ обязан исчезнуть, когда клиент научится связывать `ISet`.

        Спрашивается ЖИВОЕ замыкание развёрнутого плагина, а не константа
        здесь: список `NET48_VERSIONS` — наше решение, а наличие `ISet` в
        клиенте — факт, и он может измениться без нас. День, когда факт
        изменится, обязан покраснеть здесь, а не пройти незамеченным.
        """
        tests_dir = Path(__file__).resolve().parents[3] / "tests"
        if not tests_dir.is_dir():          # чужое дерево — не молчим, говорим
            self.skipTest(f"нет каталога {tests_dir}: замыкание не спросить")
        if str(tests_dir) not in sys.path:
            sys.path.insert(0, str(tests_dir))
        try:
            import bridge_reference_closure as brc
        except ImportError as exc:          # прибора нет — это НЕ «находок нет»
            self.skipTest(f"замыкание не импортируется ({exc}) — прибор "
                          f"отсутствует, и это не подтверждение отказа")
        deployed = brc.type_index("net48", "deployed")
        self.assertNotIn(
            "System.Collections.Generic.ISet", deployed,
            "развёрнутый плагин теперь связывает ISet на net48 — причина "
            "отказа исчезла. Сними границу в datum_emit.emit_multistory_stairs "
            "и запись 'datums_multistory_stairs' из E003_EXPECTED_BELOW.")
        # контроль-FAIL зонда: в declared-профиле ISet ОБЯЗАН быть, иначе
        # индекс типов разучился отвечать и проверка выше вакуумна
        self.assertIn(
            "System.Collections.Generic.ISet",
            brc.type_index("net48", "declared"),
            "ISet не найден и в declared — сломан индекс типов, а не клиент")


if __name__ == "__main__":
    unittest.main()
