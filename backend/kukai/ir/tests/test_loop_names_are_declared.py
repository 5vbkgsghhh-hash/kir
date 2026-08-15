"""Каждое имя кольца, на которое ССЫЛАЕТСЯ эмитированный C#, должно быть ОБЪЯВЛЕНО.

**Это «объявлено здесь, прочитано там» в форме КЛОНА, и форма опаснее обычной:
код не расходится с документацией — он расходится САМ С СОБОЙ.** Петля проёма
живёт в восьми площадках шести модулей (`arch_emit` ×2, `authoring` ×3,
`site_emit`, `solid_emit`, `struct_emit`), и у части из них рядом стоит ВТОРОЙ,
независимый обход того же списка, собирающий имена ЗАНОВО:

    solid_emit.py:108   for hi, hole in enumerate(region["holes"]):
                            parts.append(emit_loop_cs(hole, f"__hl_{s}_{hi}"))
    solid_emit.py:115   names = [f"__ol_{s}"] + [f"__hl_{s}_{i}"
                                 for i in range(len(region["holes"]))]

Разойдись эти два — и эмитированный C# сошлётся на `__hl_`, которого никто не
объявил: CS0103 в лучшем случае, а в худшем ссылка на чужую петлю. Ровно две
границы `move_elements`, только в геометрии.

**На сегодня (12.08.2026) разойтись они НЕ МОГУТ, и это проверено чтением, а не
предположено:** обе функции получают один и тот же объект `region` на обеих
площадках вызова (405/416 и 544/565), между вызовами он только читается,
`region["holes"]` не мутируется нигде в модуле, и ни один из обходов не
фильтрует и не делает `continue`. Но безопасность по построению — это свойство
СЕГОДНЯШНЕГО кода, а не инвариант: `continue` для вырожденного проёма,
добавленный в один обход, ломает её молча.

Поэтому здесь не проза, а прибор. Он не разбирает эмиттеры — он читает то, что
они ВЫДАЛИ, и потому не зависит ни от идиомы цикла, ни от модуля, ни от того,
сколько там копий: **сравнивается множество объявленных имён с множеством
использованных, в каждом голдене.** Новая копия петли, написанная как угодно,
попадает под проверку автоматически.

Граница честная: корпус голденов — это НЕ все программы компилятора. Прибор
говорит «в замороженной эмиссии расхождения нет», а не «расхождение
невозможно».
"""

import pathlib
import re
import unittest

GOLDEN_DIR = pathlib.Path(__file__).resolve().parent / "golden"

#: ЛЮБОЕ объявление имени, а не только `CurveLoop`. Первая версия требовала
#: именно `CurveLoop` — и выдала двух «нарушителей», которых нет:
#: `__hl_D1` и `__hl_Win1` объявлены как `Level`, потому что **префикс `__hl_`
#: несёт в эмиттере ДВА разных смысла** — hole loop (`__hl_{s}_{hi}`,
#: `CurveLoop`) и host level (`__hl_{s}`, `Level`, `authoring.py:1876`).
#: Прибор сопоставлял по ФОРМЕ ИМЕНИ, то есть по соглашению вместо авторитета,
#: и тип объявления был как раз тем авторитетом, которого он не спросил.
DECLARED = re.compile(
    r"\b(?:CurveLoop|Level|ModelCurve|var)\s+(__(?:hl|ol)_[A-Za-z0-9_]+)\s*=")

#: Любое упоминание имени кольца в коде.
MENTIONED = re.compile(r"\b(__(?:hl|ol)_[A-Za-z0-9_]+)\b")


def _split(text: str) -> tuple[set[str], set[str]]:
    declared = set(DECLARED.findall(text))
    return declared, set(MENTIONED.findall(text)) - declared


class EveryLoopNameUsedIsDeclared(unittest.TestCase):

    def test_no_golden_references_an_undeclared_loop(self):
        checked = 0
        carrying = 0
        offenders = []
        for path in sorted(GOLDEN_DIR.glob("*.golden.cs")):
            text = path.read_text(encoding="utf-8")
            declared, dangling = _split(text)
            checked += 1
            if declared:
                carrying += 1
            if dangling:
                offenders.append(f"{path.name}: {sorted(dangling)}")
        self.assertGreater(checked, 40,
                           "голденов почти нет — сломан корень, а не код")
        # Знаменатель РЯДОМ с нулём: «0 висячих из 0 несущих кольца» и
        # «0 из 20» печатаются одинаково и значат противоположное.
        self.assertGreater(
            carrying, 5,
            f"кольца несут лишь {carrying} голденов из {checked} — прибор "
            "смотрит почти в пустоту, и его ноль ничего не стоит")
        self.assertEqual(
            offenders, [],
            "эмитированный C# ссылается на кольцо, которого не объявлял — "
            "два обхода одного списка разошлись:\n  " + "\n  ".join(offenders))

    def test_holes_are_numbered_without_a_gap(self):
        """Пропуск в нумерации — тот же разлад, но видимый до подстановки.

        `__hl_F1_0, __hl_F1_2` без `_1` означает, что объявляющий обход
        пропустил проём, а считающий — нет (или наоборот).
        """
        offenders = []
        for path in sorted(GOLDEN_DIR.glob("*.golden.cs")):
            declared, _ = _split(path.read_text(encoding="utf-8"))
            by_owner: dict[str, list[int]] = {}
            for name in declared:
                match = re.fullmatch(r"__hl_(.+)_(\d+)", name)
                if match:
                    by_owner.setdefault(match.group(1), []).append(
                        int(match.group(2)))
            for owner, indices in by_owner.items():
                indices.sort()
                if indices != list(range(len(indices))):
                    offenders.append(f"{path.name}: {owner} -> {indices}")
        self.assertEqual(
            offenders, [],
            "нумерация проёмов с пропуском:\n  " + "\n  ".join(offenders))

    def test_the_instrument_can_say_no(self):
        """Контроль-FAIL: подсунуть висячее имя и потребовать, чтобы нашлось.

        Без него «нарушителей нет» неотличимо от «регулярка ничего не ловит»
        — а обе регулярки здесь написаны по ИДИОМЕ эмиссии, то есть ровно по
        соглашению, а не по авторитету.
        """
        good = ("CurveLoop __ol_F1 = new CurveLoop();\n"
                "CurveLoop __hl_F1_0 = new CurveLoop();\n"
                "__loops_F1.Add(__ol_F1);\n__loops_F1.Add(__hl_F1_0);\n")
        declared, dangling = _split(good)
        self.assertEqual(declared, {"__ol_F1", "__hl_F1_0"})
        self.assertEqual(dangling, set(), "чистый образец не должен ловиться")

        bad = good + "__loops_F1.Add(__hl_F1_1);\n"
        _, dangling = _split(bad)
        self.assertEqual(
            dangling, {"__hl_F1_1"},
            "прибор обязан поймать ссылку на необъявленное кольцо")


if __name__ == "__main__":
    unittest.main()
