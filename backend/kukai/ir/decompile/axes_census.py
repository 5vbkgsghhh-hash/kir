"""СТРУКТУРНАЯ ПЕРЕПИСЬ СЛЕПКА — оси повторения BIM-модели, посчитанные из
самого слепка.

    venv/bin/python3.12 -m kukai.ir.decompile.axes_census k2_ar_rd_v9
    venv/bin/python3.12 -m kukai.ir.decompile.axes_census --all
    venv/bin/python3.12 -m kukai.ir.decompile.axes_census --all --json > census.json

ЗАЧЕМ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ (2026-08-04). Карта ядра документирует УСТРОЙСТВО
(сколько операций, сколько видов) и не документирует ДАННЫЕ. Из-за этого факты
вида «633 типа на 115 880 элементов» или «2941 группа» приходилось добывать
заново каждый раз, и один такой заход стоил половины дня. Отчёт с этими
числами протух бы за неделю и врал бы убедительно — потому что выглядел бы
замером. Поэтому числа оставлены ПОРОЖДАЕМЫМИ: одна строка запуска — одна
страница ответа.

ГДЕ ЭТОТ ФАЙЛ ДОЛЖЕН ЛЕЖАТЬ. По жанру это ``tools/`` (рядом с
``capability_map.py``, ``coverage_matrix.py``, ``bounds_audit.py``), а не часть
пакета: он ничего не экспортирует и никем не импортируется. Положен сюда
только потому, что ``tools/`` не пишется тем uid, под которым его писали.
Переносится одной командой ``mv``, ничего в нём от этого не поменяется —
пути он вычисляет от собственного расположения, а корень слепков принимает
через ``--root``.

НИЧЕГО НЕ ИСПОЛНЯЕТСЯ И НИЧЕГО НЕ ПИШЕТСЯ. Читаются только сохранённые
артефакты прогона: L0.jsonl, L0.checkpoint.json, group.index.json, status.json,
verify.json, tree.json, open_model.profile.json. Revit не нужен, прод не
трогается, слепок в процессе записи переносится (недописанная последняя строка
пропускается молча — иначе перепись нельзя было бы снять с идущего
извлечения).

ПОЧЕМУ БЮДЖЕТ ЗОНДОВ СЧИТАЕТСЯ ПАРСИНГОМ ЭМИТТЕРА, А НЕ КОНСТАНТОЙ. Число
параметров, которые извлечение спрашивает у КАЖДОГО элемента, — это длина
списка вызовов ``__Put*Param`` внутри ``__PutParams`` в :mod:`extract`.
Константа здесь протухла бы ровно так же, как отчёт: список растёт при каждом
новом параметре. Поэтому он вычитывается из исходника на каждом прогоне
переписи (:func:`probe_budget`), и если эмиттер переименуют — перепись честно
скажет «не посчитано», а не соврёт вчерашним числом.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

_HERE = Path(__file__).resolve()
# .../backend/kukai/ir/decompile/axes_census.py -> .../backend
_BACKEND = _HERE.parent.parent.parent.parent
DEFAULT_ROOT = _BACKEND / "backend" / "data" / "decompile"
EMITTER = _HERE.parent / "extract.py"


# ── ГРАНИЦЫ ПЕРЕПИСИ ────────────────────────────────────────────────────────
#
# Часть контракта, а не оговорка: прибор, покрывающий часть диапазона, опаснее
# отсутствующего — он выглядит замером и молчит там, где слеп.
BLIND_SPOTS = """\
ЧЕГО ЭТА ПЕРЕПИСЬ НЕ ВИДИТ ПО ПОСТРОЕНИЮ

 1. ВРЕМЯ. Считаются ЧТЕНИЯ (зонды параметров, подъёмы типа, элементы), а не
    секунды. Перевод чтений в секунды здесь НЕВОЗМОЖЕН: во всех сохранённых
    артефактах поэлементный `elapsed_ms` равен null. Долю времени, которую
    занимают чтения, обязан назвать отдельный прибор на живом Revit; без него
    любой множитель отсюда — множитель ЧТЕНИЙ, а не времени.
 2. СУЩЕСТВОВАНИЕ ПАРАМЕТРА ОТДЕЛЬНО ОТ ЕГО ЗНАЧЕНИЯ. L0 несёт только
    значения. Различают эти два состояния лишь квитанции сечений (16 зондов
    из бюджета). Для остальных перепись принимает «значение есть» за
    «параметр есть» — это ДОПУЩЕНИЕ. Основание: во всех просмотренных
    слепках `no_value` = 0, то есть «параметр есть, значения нет» на этих
    моделях не встретилось ни разу. На модели, где встретится, симуляция
    «сначала тип» будет ЗАНИЖАТЬ число нужных зондов.
 3. МАСКА ТИПА — ОРАКУЛ. В симуляции маска существования выводится по типу из
    наблюдённых значений, то есть задним числом. Живой протокол узнавал бы её,
    опросив первый экземпляр каждого типа целиком; эта цена в симуляцию
    ВКЛЮЧЕНА (2*T*B зондов), но равенство «маска первого экземпляра = маска
    типа» здесь не доказано, а принято.
 4. СВЯЗАННЫЕ ФАЙЛЫ. Видна только сводка связи (имя, загружена ли):
    содержимое связанных документов извлечение не читает вовсе. «Сколько
    элементов в связях» — вопрос не к слепку.
 5. КАТЕГОРИИ ВНЕ ТАБЛИЦЫ. `census_total` — перепись документа, `элементов
    прочитано` — обход EXTRACT_CATEGORIES. Разница НЕ является потерей: часть
    категорий не читается намеренно.
 6. ПОВТОР ПО ЭТАЖАМ — НЕОБХОДИМОЕ условие, не достаточное. Совпадение
    мультимножества (категория, тип) не означает совпадения координат.
    Читать по нему меньше можно только с проверкой геометрии.
 7. НЕТ АРТЕФАКТА — НЕТ СТРОКИ. Прогон, оборвавшийся до стадии, не даёт её
    чисел, и перепись пишет «нет», а не ноль."""


SECTION_OUTCOMES = ("instance_hit", "type_hit", "not_applicable",
                    "no_value", "wrong_storage", "exception")


# ── БЮДЖЕТ ЗОНДОВ ───────────────────────────────────────────────────────────

def probe_budget(emitter: Path = EMITTER) -> tuple[int, dict[str, int]]:
    """Сколько ``__Put*Param`` приходится на ОДИН элемент — по исходнику.

    При неудаче парсинга возвращает ``(0, {})``: перепись обязана сказать
    «не посчитано», а не подставить прошлое число.
    """
    try:
        source = emitter.read_text(encoding="utf-8")
        start = source.index("__PutParams = (__e, __row)")
        end = source.index('__row["params"] = __params;', start)
    except (OSError, ValueError):
        return 0, {}
    counts = collections.Counter(
        re.findall(r"__Put(\w+?)Param\(__e,", source[start:end]))
    return sum(counts.values()), {f"__Put{k}Param": v for k, v in counts.items()}


# ── ЧТЕНИЕ АРТЕФАКТОВ ───────────────────────────────────────────────────────

def _records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def _load(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _verify_summary(path: Path) -> dict[str, Any] | None:
    """Сводка VERIFY без сборки объекта на 20+ МБ.

    ЧИТАЕТСЯ ВЕСЬ ФАЙЛ, ПОТОКОМ. Первая версия смотрела только первые и
    последние 4 МБ — и на k2_ar_rd_v7/v8 (verify.json 98 и 96 МБ) молча
    возвращала «нет сводки», то есть теряла ровно тот слепок, ради которого
    перепись писалась. Ошибка ровно того рода, который перепись объявляет в
    своих границах: прибор, покрывающий часть диапазона, опаснее
    отсутствующего.
    """
    if not path.exists():
        return None
    pattern = re.compile(rb'"summary":\s*(\{[^{}]*\})')
    match = None
    with path.open("rb") as handle:
        # Перекрытие в 4 КиБ: сводка не должна разорваться на границе кусков.
        overlap = b""
        while True:
            chunk = handle.read(8_000_000)
            if not chunk:
                break
            match = pattern.search(overlap + chunk)
            if match is not None:
                break
            overlap = chunk[-4096:]
    if match is None:
        return None
    try:
        summary = json.loads(match.group(1))
    except ValueError:
        return None
    return {key: summary.get(key) for key in (
        "total_leaves", "op_count", "atom_count", "lift_coverage",
        "compression_ratio")}


def _tree_kinds(path: Path) -> dict[str, int] | None:
    """Разбивка узлов L3 по виду — регуляркой, чтобы не строить объектное
    дерево на 70 МБ на слабой коробке."""
    if not path.exists():
        return None
    counts = collections.Counter(
        re.findall(rb'"kind":\s*"([a-z_]+)"', path.read_bytes()))
    return {key.decode(): value for key, value in counts.most_common(14)}


def _digest(payload: Any) -> str:
    return hashlib.sha1(repr(payload).encode()).hexdigest()[:12]


# ── ПЕРЕПИСЬ ────────────────────────────────────────────────────────────────

def census(directory: Path, budget: int) -> dict[str, Any] | None:
    l0 = directory / "L0.jsonl"
    if not l0.exists():
        return None

    types: collections.Counter[str] = collections.Counter()
    label: dict[str, tuple[str, str]] = {}
    cat_elems: collections.Counter[str] = collections.Counter()
    cat_types: dict[str, set[str]] = collections.defaultdict(set)
    mask: dict[str, set[str]] = collections.defaultdict(set)
    values: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    level_sig: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    geom_kind: collections.Counter[str] = collections.Counter()
    phases: collections.Counter[str] = collections.Counter()
    options: collections.Counter[str] = collections.Counter()
    worksets: collections.Counter[str] = collections.Counter()
    receipts: dict[tuple[str, str], collections.Counter] = \
        collections.defaultdict(collections.Counter)
    element_ids: set[str] = set()
    links: list[dict[str, Any]] = []
    document: dict[str, Any] | None = None
    n_elements = n_params = n_hosted = 0

    for record in _records(l0):
        kind = record.get("record")
        if kind == "element":
            element = record["element"]
            n_elements += 1
            element_ids.add(element.get("element_id") or "")
            type_id = element.get("type_id") or "<no-type>"
            types[type_id] += 1
            label.setdefault(type_id, (element.get("category") or "?",
                                       element.get("type_name") or ""))
            category = element.get("category") or "?"
            cat_elems[category] += 1
            cat_types[category].add(type_id)
            level = element.get("level_name") or "<без уровня>"
            level_sig[level][(category, type_id)] += 1
            geom_kind[element.get("geom_kind") or "?"] += 1
            if element.get("host_id"):
                n_hosted += 1
            for field, sink in (("phase_created", phases),
                                ("design_option", options),
                                ("workset", worksets)):
                reference = element.get(field)
                if reference:
                    sink[reference.get("name") or ""] += 1
            for key, value in (element.get("params") or {}).items():
                n_params += 1
                mask[type_id].add(key)
                bucket = values[(type_id, key)]
                if len(bucket) < 4:
                    bucket.add(repr(value))
        elif kind == "link":
            links.append(record["link"])
        elif kind == "document":
            document = record["document"]
        elif kind == "category_status":
            status = record["status"]
            category = status.get("category") or "?"
            for row in (status.get("section_receipts") or []):
                sink = receipts[(category, row.get("parameter") or "?")]
                for outcome in SECTION_OUTCOMES:
                    sink[outcome] += int(row.get(outcome) or 0)

    n_types = len(types)

    # Симуляция протокола «сначала тип».
    #   сейчас        — budget зондов на КАЖДОМ элементе, каждый с падением на тип;
    #   тип-первый    — тип целиком + первый экземпляр целиком (2*budget на тип),
    #                   дальше только по маске существования этого типа;
    #   +тип-константы— вдобавок снимаются параметры, не меняющиеся внутри типа:
    #                   их значение читается один раз с самого типа.
    probes_now = n_elements * budget
    probes_typefirst = probes_constfold = n_types * budget * 2
    for type_id, count in types.items():
        keys = mask[type_id]
        varying = sum(1 for key in keys if len(values[(type_id, key)]) > 1)
        probes_typefirst += max(0, count - 1) * len(keys)
        probes_constfold += max(0, count - 1) * varying

    outcomes: collections.Counter[str] = collections.Counter()
    probes_measured = probes_dead = dead_pairs = live_pairs = reached_type = 0
    for row in receipts.values():
        total = sum(row[outcome] for outcome in SECTION_OUTCOMES)
        if not total:
            continue
        probes_measured += total
        for outcome in SECTION_OUTCOMES:
            outcomes[outcome] += row[outcome]
        # Зонд доходит до типа всегда, когда экземпляр не дал значения.
        reached_type += row["not_applicable"] + row["no_value"] + row["type_hit"]
        if row["not_applicable"] == total:
            probes_dead += total
            dead_pairs += 1
        else:
            live_pairs += 1

    groups = _group_axis(directory, element_ids, n_elements)

    levels = {name: counter for name, counter in level_sig.items()
              if name != "<без уровня>"}
    on_levels = sum(sum(counter.values()) for counter in levels.values())

    def repeat(signature: Callable[[collections.Counter], str]) -> dict[str, Any]:
        buckets: dict[str, list[str]] = collections.defaultdict(list)
        for name, counter in levels.items():
            buckets[signature(counter)].append(name)
        duplicates = [names for names in buckets.values() if len(names) > 1]
        elements = sum(sum(levels[name].values())
                       for names in duplicates for name in names[1:])
        widest = max(duplicates, key=len, default=[])
        return {"classes": len(duplicates),
                "redundant_levels": sum(len(n) - 1 for n in duplicates),
                "elements": elements,
                "pct": 100.0 * elements / on_levels if on_levels else 0.0,
                "widest": sorted(widest)[:8]}

    checkpoint = _load(directory / "L0.checkpoint.json") or {}
    status = _load(directory / "status.json") or {}
    profile = _load(directory / "open_model.profile.json") or {}

    return {
        "name": directory.name,
        "title": (profile.get("document_fingerprint") or {}).get("title"),
        "revit_version": profile.get("revit_version"),
        "dialect": checkpoint.get("dialect"),
        "stage": status.get("stage"),
        "elements": n_elements,
        "types": n_types,
        "ratio": n_elements / n_types if n_types else 0.0,
        "top_types": [(count,) + label[t] for t, count in types.most_common(8)],
        "categories": len(cat_elems),
        "top_categories": [(name, count, len(cat_types[name]))
                           for name, count in cat_elems.most_common(10)],
        "params_written": n_params,
        "probe_budget": budget,
        "probes_now": probes_now,
        "probes_typefirst": probes_typefirst,
        "probes_constfold": probes_constfold,
        "probes_measured": probes_measured,
        "probes_dead": probes_dead,
        "dead_pairs": dead_pairs,
        "live_pairs": live_pairs,
        "reached_type": reached_type,
        "outcomes": dict(outcomes),
        "groups": groups,
        "levels": len(levels),
        "elements_on_levels": on_levels,
        "elements_without_level": n_elements - on_levels,
        "repeat_exact": repeat(lambda c: _digest(sorted(c.items()))),
        "repeat_loose": repeat(lambda c: _digest(sorted(set(c)))),
        "geom_kind": dict(geom_kind),
        "hosted": n_hosted,
        "phases": dict(phases.most_common(5)),
        "design_options": dict(options.most_common(5)),
        "worksets": len(worksets),
        "links": [{"name": link.get("name"), "loaded": link.get("loaded")}
                  for link in links],
        "census_total": status.get("census_total"),
        "unscanned": status.get("unscanned_elements"),
        "worksets_closed": status.get("worksets_closed"),
        "slo_violations": status.get("slo_violations"),
        "verify": _verify_summary(directory / "verify.json"),
        "tree_kinds": _tree_kinds(directory / "tree.json"),
        "document_census": bool(document),
    }


def _group_axis(directory: Path, element_ids: set[str],
                n_elements: int) -> dict[str, Any] | None:
    raw = _load(directory / "group.index.json")
    if not raw or "group_index" not in raw:
        return None
    index = raw["group_index"]
    instances = index.get("instances") or {}
    definitions = index.get("definitions") or {}
    members: set[str] = set()
    slots = 0
    repeat_slots = 0
    for definition in definitions.values():
        reference = definition.get("reference_instance_id")
        for instance_id in (definition.get("instance_ids") or []):
            if instance_id == reference:
                continue
            ids = (instances.get(instance_id) or {}).get("member_ids") or []
            repeat_slots += sum(1 for i in ids if i in element_ids)
    for group in instances.values():
        ids = group.get("member_ids") or []
        slots += len(ids)
        members.update(ids)
    covered = len(members & element_ids)
    return {
        "instances": len(instances),
        "definitions": len(definitions),
        "ratio": len(instances) / len(definitions) if definitions else 0.0,
        "member_slots": slots,
        "unique_members": len(members),
        "members_in_l0": covered,
        "members_in_l0_pct": 100.0 * covered / n_elements if n_elements else 0.0,
        "repeat_slots_in_l0": repeat_slots,
        "composition_mismatches": len(index.get("composition_mismatches") or []),
        "failures": len(raw.get("failures") or []),
    }


# ── ВЫВОД ───────────────────────────────────────────────────────────────────

def _pct(part: float, whole: float) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "—"


def render(row: dict[str, Any], breakdown: dict[str, int]) -> None:
    print(f"\n{'=' * 78}")
    print(f"СЛЕПОК {row['name']}   модель: {row.get('title') or '—'}"
          f"   Revit {row.get('revit_version') or '—'}"
          f"   диалект {row.get('dialect') or '—'}"
          f"   стадия: {row.get('stage') or '—'}")
    print("=" * 78)

    print("\n1. ТИП / ЭКЗЕМПЛЯР")
    print(f"   элементов прочитано ......... {row['elements']}")
    print(f"   уникальных типов ............ {row['types']}")
    print(f"   отношение ................... {row['ratio']:.1f}x"
          f"  (столько раз в среднем перечитывается одно определение)")
    print(f"   категорий ................... {row['categories']}")
    for count, category, type_name in row["top_types"][:5]:
        print(f"     {count:>7d}  {category:<28s} {type_name[:34]}")

    print(f"\n2. ЗОНДЫ ПАРАМЕТРОВ   (бюджет эмиттера: {row['probe_budget']} на элемент)")
    if not row["probe_budget"]:
        print("   НЕ ПОСЧИТАНО: эмиттер не распарсился (переименовали __PutParams?)")
    else:
        print(f"     " + ", ".join(f"{k}×{v}" for k, v in sorted(breakdown.items())))
        print(f"   зондов сейчас ............... {row['probes_now']}")
        print(f"   значений дошло до L0 ........ {row['params_written']}"
              f"   (выход {_pct(row['params_written'], row['probes_now'])})")
        print(f"   протокол «сначала тип» ...... {row['probes_typefirst']}"
              f"   ({row['probes_now'] / max(1, row['probes_typefirst']):.1f}x меньше)")
        print(f"   + снятие тип-констант ....... {row['probes_constfold']}"
              f"   ({row['probes_now'] / max(1, row['probes_constfold']):.1f}x меньше)")
    if row["probes_measured"]:
        print(f"   ИЗМЕРЕНО КВИТАНЦИЯМИ (16 зондов из {row['probe_budget']}):")
        print(f"     опрошено .................. {row['probes_measured']}")
        for outcome in SECTION_OUTCOMES:
            value = row["outcomes"].get(outcome, 0)
            print(f"       {outcome:<16s}{value:>11d}   "
                  f"{_pct(value, row['probes_measured'])}")
        print(f"     дошло до ТИПА ............. {row['reached_type']}"
              f"   ({_pct(row['reached_type'], row['probes_measured'])})"
              f" — лишний doc.GetElement на каждом")
        print(f"     МЁРТВЫХ (параметра нет у всей категории)  {row['probes_dead']}"
              f"   ({_pct(row['probes_dead'], row['probes_measured'])})"
              f" в {row['dead_pairs']} парах (категория,параметр);"
              f" живых пар {row['live_pairs']}")
    else:
        print("   квитанций нет (слепок снят до квитанций сечений)")

    print("\n3. ГРУППЫ REVIT")
    groups = row["groups"]
    if groups is None:
        print("   нет group.index.json")
    elif not groups["instances"]:
        print(f"   групп в модели нет   (отказов чтения: {groups['failures']})")
    else:
        print(f"   размещений .................. {groups['instances']}")
        print(f"   определений ................. {groups['definitions']}"
              f"   ({groups['ratio']:.1f}x)")
        print(f"   членов всего ................ {groups['unique_members']}")
        print(f"   из них ЧИТАЕМ мы ............ {groups['members_in_l0']}"
              f"   ({groups['members_in_l0_pct']:.1f}% слепка)")
        print(f"   повторных членов в слепке ... {groups['repeat_slots_in_l0']}"
              f"   (покрыто «определение + N трансформов»)")
        print(f"   расхождений состава ......... {groups['composition_mismatches']}"
              f"   отказов чтения: {groups['failures']}")

    print("\n4. ПОВТОР ПО ЭТАЖАМ   (НЕОБХОДИМОЕ условие, не достаточное)")
    print(f"   уровней с элементами ........ {row['levels']}")
    print(f"   элементов на уровнях ........ {row['elements_on_levels']}"
          f"   без уровня: {row['elements_without_level']}")
    for title, block in (("точный (кат,тип,кратность)", row["repeat_exact"]),
                         ("мягкий (только набор кат,тип)", row["repeat_loose"])):
        print(f"   {title:<31s} лишних уровней {block['redundant_levels']:>3d},"
              f" элементов в них {block['elements']:>7d} ({block['pct']:.1f}%)")
        if block["widest"]:
            print(f"       {' / '.join(block['widest'])}")

    print("\n5. ПРОЧИЕ ОСИ")
    print(f"   связей ...................... {len(row['links'])}"
          f"   (содержимое связей не читается вовсе)")
    print(f"   фазы ........................ {row['phases'] or 'нет'}")
    print(f"   варианты проектирования ..... {row['design_options'] or 'нет'}")
    print(f"   рабочих наборов ............. {row['worksets']}"
          f"   закрыто при чтении: {row['worksets_closed']}")
    print(f"   геометрия ................... {row['geom_kind']}")
    print(f"   элементов с хостом .......... {row['hosted']}")

    print("\n6. ЧТО ЧИТАЕМ И ВО ЧТО ЭТО ПРЕВРАЩАЕТСЯ")
    print(f"   элементов в модели .......... {row.get('census_total') or '—'}")
    print(f"   прочитано ................... {row['elements']}"
          f"   не сканировано: {row.get('unscanned') or '—'}")
    verify = row["verify"]
    if verify:
        leaves = verify.get("total_leaves") or 0
        print(f"   листьев L1 .................. {leaves}"
              f"   поднято в операции: {verify.get('op_count')}"
              f" ({verify.get('lift_coverage', 0):.1f}%)"
              f"   атомов: {verify.get('atom_count')}"
              f" ({_pct(verify.get('atom_count') or 0, leaves)})")
        print(f"   узлов L3 / листьев .......... "
              f"{verify.get('compression_ratio', 0):.3f}"
              f"   (>1 значит дерево БОЛЬШЕ входа — сжатия нет)")
    else:
        print("   verify.json нет — прогон не дошёл до сверки")
    if row["tree_kinds"]:
        print(f"   виды узлов L3 ............... {row['tree_kinds']}")
    print(f"   нарушений SLO вызова ........ {row.get('slo_violations') or '—'}")


def render_summary(rows: list[dict[str, Any]]) -> None:
    print(f"\n{'=' * 128}")
    print("СВОДКА")
    print("=" * 128)
    print(f"{'слепок':<26s}{'элем':>8s}{'типов':>7s}{'N/T':>8s}{'зондов':>11s}"
          f"{'тип-первый':>12s}{'выигрыш':>9s}{'групп':>7s}{'покрыто%':>10s}"
          f"{'этажи%':>8s}{'атомов%':>9s}")
    print("-" * 128)
    for row in rows:
        groups = row["groups"] or {}
        verify = row["verify"] or {}
        leaves = verify.get("total_leaves") or 0
        atoms = verify.get("atom_count") or 0
        print(f"{row['name']:<26s}{row['elements']:>8d}{row['types']:>7d}"
              f"{row['ratio']:>8.1f}{row['probes_now']:>11d}"
              f"{row['probes_typefirst']:>12d}"
              f"{row['probes_now'] / max(1, row['probes_typefirst']):>8.1f}x"
              f"{groups.get('instances', 0):>7d}"
              f"{groups.get('members_in_l0_pct', 0.0):>9.1f}%"
              f"{row['repeat_exact']['pct']:>7.1f}%"
              f"{100.0 * atoms / leaves if leaves else 0.0:>8.1f}%")
    print("-" * 128)
    now = sum(row["probes_now"] for row in rows)
    typefirst = sum(row["probes_typefirst"] for row in rows)
    constfold = sum(row["probes_constfold"] for row in rows)
    print(f"ИТОГО зондов по {len(rows)} слепкам: сейчас {now};"
          f" «сначала тип» {typefirst} ({now / max(1, typefirst):.1f}x);"
          f" + снятие тип-констант {constfold} ({now / max(1, constfold):.1f}x)")
    print("Множители относятся к ЧТЕНИЯМ, не к секундам — см. границу 1.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="axes_census",
        description="Структурная перепись слепка DECOMPILE: оси повторения в числах.")
    parser.add_argument("snapshots", nargs="*", help="имена слепков в data/decompile")
    parser.add_argument("--all", action="store_true", help="все слепки, сводкой")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="корень слепков")
    parser.add_argument("--json", action="store_true", help="машинный вывод")
    parser.add_argument("--full", action="store_true",
                        help="с --all печатать полную страницу на каждый слепок")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"нет корня слепков: {root}", file=sys.stderr)
        return 2

    names = (sorted(item.name for item in root.iterdir()
                    if (item / "L0.jsonl").exists())
             if args.all else args.snapshots)
    if not names:
        parser.print_help()
        return 2

    budget, breakdown = probe_budget()
    rows: list[dict[str, Any]] = []
    for name in names:
        row = census(root / name, budget)
        if row is None:
            if not args.json:
                print(f"пропуск {name}: нет L0.jsonl", file=sys.stderr)
            continue
        rows.append(row)
        if not args.json and (args.full or not args.all):
            render(row, breakdown)

    if args.json:
        json.dump({"probe_budget": budget, "probe_breakdown": breakdown,
                   "blind_spots": BLIND_SPOTS, "snapshots": rows},
                  sys.stdout, ensure_ascii=False, indent=1, default=str)
        print()
        return 0

    if len(rows) > 1:
        render_summary(rows)
    print(f"\n{BLIND_SPOTS}")
    print(f"\nбюджет зондов прочитан из {EMITTER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
