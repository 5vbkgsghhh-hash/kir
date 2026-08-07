"""БАЗОВАЯ ЛИНИЯ ПЕРЕНЯТИЯ МЕТОДА — как выглядит НАСТОЯЩЕЕ здание.

Курс проверяется не красотой, а тем, перенят ли метод. Перенятие — не мнение
рецензента: у него есть три числа, и все три считаются и по разобранному
зданию, и по программе, которую написала модель. Здесь они сведены рядом.

ЧТО СЧИТАЕТСЯ.

  элементов на тип      сколько элементов приходится на одно ТИПОВОЕ решение.
                        Первый уровень повтора, работает всегда.
  копий на определение  сколько раз поставлено одно определение группы.
                        Единственный уровень, на котором повтор ПЕРЕЖИВАЕТ
                        скрипт и виден человеку, открывшему модель.
  доля в группах        какая часть модели лежит внутри групп. Считается по
                        членам, ВИДИМЫМ в L0, то есть это НИЖНЯЯ граница.

ПОЧЕМУ ЭТО НЕ ПОРОГ И НЕ ЦЕЛЬ. Цель по числу закрывается одной операцией —
замер `skill.GOOD_VS_BAD`: на задание «не менее 10 000 элементов» модель выдала
12 185 элементов, из них 12 020 колонн одной сеткой, поставленной 601 раз.
Базовая линия отвечает на другой вопрос: ПОХОЖЕ ЛИ ПОСТРОЕННОЕ НА ДОМ. Здание с
двенадцатью тысячами одиночных колонн и нулём групп не похоже ни на одно из
семи разобранных, и это проверяемый сигнал, а не вкусовщина.

ЧЕСТНАЯ ОГОВОРКА, БЕЗ КОТОРОЙ ЧИСЛО ВРЁТ. Разделы ведут себя по-разному, и это
не шум: в ЭОМ Snowdon и ЭОМ Сколково НОЛЬ определений групп на два здания —
там повтор выражают система и трасса. Сравнивать программу АР с базовой линией
АР осмысленно, программу ВК с ней — нет.

    backend/venv/bin/python tools/design/examples/method_baseline.py
    backend/venv/bin/python tools/design/examples/method_baseline.py prog.json
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from kukai.ir import course                                      # noqa: E402
from kukai.ir.course import corpus, recipes                      # noqa: E402


def per_building() -> list[tuple[str, dict]]:
    """Три числа по каждому зданию корпуса, пересчитанные с диска."""
    rows = []
    for building, title in corpus.BUILDINGS.items():
        if not corpus.available(building):
            rows.append((title, {"пропуск": "разбора нет на этом боксе"}))
            continue
        elements = corpus.count_elements(building)
        types = corpus.count_types(building)
        defs = corpus.group_definitions(building)
        places = corpus.top_level_instances(building)
        rows.append((title, {
            "элементов": elements,
            "элементов на тип": round(elements / max(1.0, types), 1),
            "определений групп": defs,
            "копий на определение": round(places / defs, 1) if defs else 0.0,
            "доля в группах, %": corpus.grouped_share(building),
            "медиана членов": corpus.reused_definition_size(building),
        }))
    return rows


def main() -> int:
    print("БАЗОВАЯ ЛИНИЯ: семь разобранных зданий, по одному разбору на здание")
    print("-" * 78)
    head = (f"{'здание':<34}{'эл-тов':>8}{'на тип':>8}{'опр.':>6}"
            f"{'копий':>7}{'в гр.%':>7}{'медиана':>8}")
    print(head)
    for title, row in per_building():
        if "пропуск" in row:
            print(f"{title:<34}  {row['пропуск']}")
            continue
        print(f"{title:<34}{row['элементов']:>8.0f}"
              f"{row['элементов на тип']:>8.1f}{row['определений групп']:>6.0f}"
              f"{row['копий на определение']:>7.1f}{row['доля в группах, %']:>7.1f}"
              f"{row['медиана членов']:>8.1f}")
    print()
    print("ЧТО ЗНАЧИТ «копий 0.0» ПРИ НЕНУЛЕВОМ ЧИСЛЕ ОПРЕДЕЛЕНИЙ: все вхождения")
    print("ВЛОЖЕНЫ в родительскую группу (`group_id_parent`), у них нет ни")
    print("origin, ни привязки к уровню — засчитывать их как самостоятельные")
    print("постановки значило бы завысить тираж. У детского сада так все 638")
    print("вхождений «Кабинка су_ДОО»: повтор настоящий, а замерить его тираж")
    print("этим индексом нечем, и мы говорим это вслух, а не подставляем число.")
    print()
    print("СВОДКА, КОТОРАЯ И ЕСТЬ ЛИНИЯ:")
    for name, (value, why) in course.BASELINE.items():
        print(f"  {name:<28} {value:<8} {why}")
    print()
    print("НАШ СЛЕД ДЛЯ СРАВНЕНИЯ: create_group вызван "
          f"{corpus.GROUP_USES_IN_LIFTED_OPS} раз на "
          f"{corpus.fmt(corpus.LIFTED_OPS_MEASURED)} поднятых операции и не "
          f"встречается ни разу\n  среди 25 опов в "
          f"{corpus.fmt(corpus.LIVE_REJECTIONS_MEASURED)} живых отказах.")
    print()

    if len(sys.argv) > 1:
        payload = json.loads(pathlib.Path(sys.argv[1]).read_text("utf-8"))
        ops = payload.get("ops") if isinstance(payload, dict) else payload
        print(f"ПРОГРАММА {sys.argv[1]}:")
        for key, value in course.measure(ops).items():
            print(f"  {key:<28} {value}")
        return 0

    print("РЕЦЕПТЫ КУРСА ПРОТИВ ЛИНИИ (числа — замер прогона песочницей):")
    print(f"  {'рецепт':<18}{'опов':>6}{'эл-тов':>8}{'на оп':>7}"
          f"{'опр.':>6}{'копий':>7}{'в гр.%':>8}")
    for name in recipes.ORDER:
        item = recipes.RECIPES[name]
        got = course.measure(_ops_of(item))
        print(f"  {name:<18}{got['операций написано']:>6}"
              f"{got['элементов объявлено']:>8}"
              f"{got['элементов на операцию']:>7}"
              f"{got['определений групп']:>6}"
              f"{got['копий на определение']:>7}"
              f"{got['элементов внутри групп, %']:>8}")
    return 0


def _ops_of(item) -> list:
    """Операции рецепта — из НАСТОЯЩЕГО прогона, а не из головы."""
    from kukai.ir import sandbox
    result = sandbox.execute_author_script(
        item.source,
        policy=sandbox.SandboxPolicy(dsl_module="kukai.ir.course.language"))
    if not result.ok:
        raise SystemExit(result.refusal.render())
    return result.ops


if __name__ == "__main__":
    sys.exit(main())
