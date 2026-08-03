"""CLI над `kukai.design.coherence` — посмотреть связность прогона или программ.

Сама проверка живёт в пакете, потому что её вызывает боевой ход; здесь только
оболочка для рук.

    python tools/design/kir_coherence.py run.jsonl
    python tools/design/kir_coherence.py prog1.json prog2.json

Модуль остаётся и ИМЕНЕМ проверки для инструментов: `kir_dojo.spar()` зовёт
`kir_coherence.check(kir_coherence.flatten(...))` после каждой принятой
программы. Когда проверка переехала в пакет, эти три имени здесь исчезли — и
дожо падало AttributeError на первой же принятой программе, то есть не могло
дойти до записи прогона вообще. Поэтому API объявлен явно и объектами пакета:
две копии одной проверки разъедутся, ссылка — нет.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from kukai.design import coherence, parti  # noqa: E402

#: Программы прогона -> плоские элементы с геометрией плана (группы раскрыты).
flatten = coherence.flatten
#: Плоские элементы -> отчёт по парам элементов (колонна/плита, балка/колонна).
check = coherence.check
#: То же плюс план этажа и сверка со скелетом, если он объявлен.
full_check = coherence.full_check
#: Отчёт -> фразы, которые можно отдать модели.
gaps = coherence.gaps

__all__ = ["flatten", "check", "full_check", "gaps", "main"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help=".jsonl прогона или .json программы")
    a = ap.parse_args()
    programs: list = []
    for f in a.files:
        text = pathlib.Path(f).read_text("utf-8").strip()
        if f.endswith(".jsonl"):
            for line in text.splitlines():
                programs += json.loads(line).get("committed", [])
        else:
            d = json.loads(text)
            programs.append(d.get("program", d))
    skeleton = parti.from_programs(programs)
    rep = coherence.full_check(coherence.flatten(programs), skeleton)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print("\nСКЕЛЕТ:", "выведен из stack" if skeleton else "не объявлен")
    print("СВЯЗНОСТЬ:")
    problems = coherence.gaps(rep)
    for g in problems:
        print("  -", g)
    if not problems:
        print("  нарушений по проверяемым признакам нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
