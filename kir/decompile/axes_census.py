"""THE SNAPSHOT'S STRUCTURAL CENSUS — a BIM model's repetition axes, counted
from the snapshot itself.

    venv/bin/python3.12 -m kir.decompile.axes_census k2_ar_rd_v9
    venv/bin/python3.12 -m kir.decompile.axes_census --all
    venv/bin/python3.12 -m kir.decompile.axes_census --all --json > census.json

WHY THIS FILE EXISTS (2026-08-04). The core map documents the STRUCTURE (how
many operations, how many views) and does not document the DATA. Because of
that, facts like "633 types across 115,880 elements" or "2,941 groups" had
to be dug up anew every time, and one such trip cost half a day. A report
with these numbers would go stale within a week and would lie
convincingly — because it would look like a measurement. So the numbers are
kept GENERATED: one launch line, one page of answer.

WHERE THIS FILE SHOULD LIVE. By genre this is ``tools/`` material (next to
``capability_map.py``, ``coverage_matrix.py``, ``bounds_audit.py``), not part
of the package: it exports nothing and is imported by no one. It sits here
only because ``tools/`` is not writable by the uid it was written under. It
moves with one ``mv`` command with nothing about it changing — it computes
its paths from its own location, and takes the snapshot root through
``--root``.

NOTHING IS EXECUTED AND NOTHING IS WRITTEN. Only saved run artifacts are
read: L0.jsonl, L0.checkpoint.json, group.index.json, status.json,
verify.json, tree.json, open_model.profile.json. Revit is not needed, prod
is not touched, and a snapshot still being written is tolerated (an
unfinished last line is skipped silently — otherwise the census could not
be taken from an extraction in progress).

WHY THE PROBE BUDGET IS COMPUTED BY PARSING THE EMITTER, NOT AS A CONSTANT.
The number of parameters extraction asks of EVERY element is the length of
the list of ``__Put*Param`` calls inside ``__PutParams`` in :mod:`extract`.
A constant here would go stale exactly like the report: the list grows with
every new parameter. So it is read out of the source on every census run
(:func:`probe_budget`), and if the emitter is renamed, the census will
honestly say "not counted" rather than lie with yesterday's number.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from kir.install_paths import install_data_path, install_root_refusal


def _snapshot_exists(path) -> bool:
    """Whether a snapshot exists — RAW OR COMPRESSED. Asks the prod helper.

    A bare check by the raw name declares a compressed decompile absent,
    and the corpus silently shrinks. Caught on 20.08.2026 by a control
    right after compression was turned on.
    """
    from kir.decompile.snapshot_io import snapshot_file_exists
    return snapshot_file_exists(path)

_HERE = Path(__file__).resolve()

#: 🔴 IT USED TO BE `_HERE.parent.parent.parent.parent` WITH A COMMENT
#: ".../backend/kir/decompile/axes_census.py -> .../backend" — correct
#: EXACTLY for that layout. After the split, four steps land on `/opt`, and
#: the snapshot root pointed at nothing. The comment, meanwhile, kept
#: describing a path that no longer existed: the prose outlived the
#: arithmetic, just as in `install_paths`, where the same shape cost six
#: telemetry feeds going silent.
#:
#: The root is now asked of the install authority, not counted out. `None`
#: is a legitimate answer (a bundled install has no import), and the
#: reason for the silence is named by
#: `install_paths.install_root_refusal()`.
DEFAULT_ROOT = install_data_path("decompile")

#: The emitter sits RIGHT NEXT to this module — needs no lift at all.
EMITTER = _HERE.parent / "extract.py"


# ── CENSUS BOUNDARIES ───────────────────────────────────────────────────────
#
# Part of the contract, not a caveat: an instrument that covers part of a
# range is more dangerous than a missing one — it looks like a measurement
# and stays silent exactly where it is blind.
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
 3. 🔴 МАСКА ТИПА — ОРАКУЛ, И ПРЕМИССА ПОД НИМ ОПРОВЕРГНУТА ЗАМЕРОМ 15.08.2026.
    В симуляции маска выводится по типу из наблюдённых значений, то есть
    задним числом. Живой протокол узнавал бы её, опросив первый экземпляр
    типа целиком; эта цена в симуляцию включена (2*T*B зондов). Равенство
    «маска первого экземпляра = маска типа» РАНЬШЕ СТОЯЛО ЗДЕСЬ КАК ПРИНЯТОЕ.
    Проверено на четырёх зданиях — НЕ ДЕРЖИТСЯ, и отказ идёт в ОПАСНУЮ
    сторону: у экземпляра бывает ключ, которого не было у первого, и живой
    протокол его НЕ СПРОСИТ — значение уедет из L0 молча.

        sob62_r23_v5      1 тип из 71,    7 ключей,  0.46 % элементов
        k2_ar_rd_v8       6 типов из 486, 2908 ключей, 1.27 % элементов
        snowdon_plumb_v3  0                                    —
        len_ar_me_r24_v1  0                                    —

    МЕХАНИЗМ, а не случайность: `WALL_HEIGHT_TYPE` (привязка верха) есть у 7
    экземпляров одного типа стены и отсутствует у 5 — потому что верх привязан
    к уровню не у всех. Существование параметра — свойство СОСТОЯНИЯ
    ЭКЗЕМПЛЯРА, а не типа, и никакой опрос первого экземпляра этого не даст.

    ПОЭТОМУ `probes_typefirst` и `probes_constfold` ниже — ВЕРХНЯЯ ГРАНИЦА
    выигрыша при ложной премиссе, а не достижимое число. Цитировать их как
    план работ нельзя. Расхождение печатается рядом (`mask_diverged_types`,
    `mask_lost_keys`), чтобы множитель нельзя было прочесть в отрыве от его
    цены.

 3b. МЁРТВАЯ ПАРА (категория, параметр) — ФАКТ О ПРОЕКТЕ, НЕ О СХЕМЕ РЕВИТА.
    Безопасная половина идеи — не спрашивать пару, которая у категории не
    отвечает никогда: корпусом 28 слепков это 94.3 % зондов и ×17.5. Но
    СТАТИЧЕСКИЙ список таких пар тоже неверен, и это замерено: по четырём
    зданиям живых пар в объединении 19, а общих всем — 4; шестнадцать раз
    пара мертва в одном доме и жива в другом (`OST_CurtainWallPanels`
    отсутствует у ЛЕНа, `STRUCTURAL_SECTION_*` не носят колонны башни).
    Список, снятый с одного проекта, на другом молча выбросит живые пары.
    Годен только набор, выученный ВНУТРИ прогона и записавший, на каком
    основании перестал спрашивать.
 3c. 🔴 НИ ОДИН СЛЕПОК КОРПУСА НЕ СНЯТ ТЕКУЩИМ ЭКСТРАКТОРОМ, И ПОТОМУ ВСЕ
    ДОЛИ НИЖЕ — ДОЛИ ОТ ПОДМНОЖЕСТВА (замер 25.08.2026, 81 слепок).
    Квитанции сечений расширялись дважды, и покрытие слепка выдаёт себя
    отношением `probes_measured / probes_now`:

        16 из 43 зондов  = 37 %    32 слепка
        29 из 43 зондов  = 68 %     5 слепков
        43 из 43 зондов  = 100 %    НИ ОДНОГО

    По корпусу: зондов 66 027 016, измеримо 26 781 271 — 41 %. Значит
    «мёртвых 91.8 %» есть 91.8 % ОТ ИЗМЕРИМОГО, и снятие ВСЕХ мёртвых зондов
    измеримого убирает 37 % всех зондов, то есть даёт ×1.6 НА ПРОГОНЕ, а не
    ×12. Разница между ×12.2 и ×1.6 — не спор, а РАЗНЫЕ ЗНАМЕНАТЕЛИ, и
    прочитать одно как другое здесь легче всего.

    И ВЕЛИЧИНА НЕСТАБИЛЬНА: по 37 слепкам с квитанциями доля мёртвых
    min 75.0 % · медиана 95.0 % · max 99.5 %; внутри ОДНОГО здания при ОДНОМ
    покрытии (`k2_ar_rd_v1..v15`, все 37 %) она гуляет 75.0 → 95.3 %.
    Одним числом эта величина не описывается.

    ПОПЫТКА ПРИПИСАТЬ РАЗНИЦУ ШИРИНЕ НАБОРА ЗОНДОВ ОПРОВЕРГНУТА КОНТРОЛЕМ:
    ни одно здание не встречается в двух полосах покрытия (`k2` весь на 37 %,
    `mnvnk` на 67-69 %, `sob62` на 26-33 %), то есть разница 94.4 % против
    81.1 % смешана со ЗДАНИЕМ и разделению этим корпусом не поддаётся.

    ЧТО ЭТО ЗНАЧИТ ДЛЯ ПЛАНА: размер выигрыша от мёртвых пар СЕГОДНЯ
    НЕИЗВЕСТЕН. Узнаётся он одним прогоном разбора текущим экстрактором —
    живым Ревитом, то есть решением владельца, а не ещё одним обходом
    сохранённого.

 3d. РЫЧАГ «ЛИШНИЙ doc.GetElement» ЗАКРЫТ 20.08.2026 И БОЛЬШЕ НЕ РЫЧАГ.
    Тип берётся один раз на элемент, не один раз на зонд; тем замером снято
    ~6.1 млн лишних поисков по корпусу. До 25.08 перепись печатала рядом с
    числом «— лишний doc.GetElement на каждом», то есть звала чинить
    закрытое. Число осталось, зов убран.

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


# ── PROBE BUDGET ────────────────────────────────────────────────────────────

def probe_budget(emitter: Path = EMITTER) -> tuple[int, dict[str, int]]:
    """How many ``__Put*Param`` calls there are per ONE element — from the source.

    On a parse failure returns ``(0, {})``: the census must say "not
    counted" rather than substitute a past number.
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


# ── READING ARTIFACTS ───────────────────────────────────────────────────────

#: 🔴 THE FOUR READERS BELOW GO THROUGH `snapshot_io`, NOT A BARE `path.open`
#: (21.08.2026). The cleanup list grew from six names to ten — it now
#: includes `passport.json`, `tree.json`, `verify.json`, and `named.json` —
#: but two of these readers were already blind to the OLD list: `_records`
#: reads `L0.jsonl`, `_load` reads `group.index.json`, and both had been
#: squeezed out by the cleanup from the very start. The
#: `test_snapshot_readers_know_gzip` guard did not see them for the reason
#: named there: the path arrives as a PARAMETER, and the matcher is
#: line-based.
#:
#: `touch=False` is mandatory: the census is an instrument, and it has no
#: right to date what it measures with the act of measuring it (the same
#: lesson has already been paid for twice — the viewer's scene cache and
#: the corpus census).
def _open(path: Path, mode: str = "rt", encoding: str | None = "utf-8"):
    from kir.decompile.snapshot_io import open_snapshot
    return open_snapshot(path, mode, encoding=encoding, touch=False)


def _records(path: Path) -> Iterator[dict[str, Any]]:
    with _open(path) as handle:
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
        with _open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _verify_summary(path: Path) -> dict[str, Any] | None:
    """A VERIFY summary without assembling a 20+ MB object.

    THE WHOLE FILE IS READ, AS A STREAM. The first version looked only at
    the first and last 4 MB — and on k2_ar_rd_v7/v8 (verify.json at 98 and
    96 MB) it silently returned "no summary", that is, it lost exactly the
    snapshot the census was written for. An error of exactly the kind the
    census declares among its own boundaries: an instrument covering part
    of a range is more dangerous than a missing one.
    """
    if not _snapshot_exists(path):
        return None
    pattern = re.compile(rb'"summary":\s*(\{[^{}]*\})')
    match = None
    with _open(path, "rb", None) as handle:
        # A 4 KiB overlap: the summary must not split across a chunk boundary.
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
    """A breakdown of L3 nodes by kind — via regex, to avoid building a 70
    MB object tree on a weak box."""
    if not _snapshot_exists(path):
        return None
    with _open(path, "rb", None) as handle:
        blob = handle.read()
    counts = collections.Counter(
        re.findall(rb'"kind":\s*"([a-z_]+)"', blob))
    return {key.decode(): value for key, value in counts.most_common(14)}


def artifact_absent_note(directory: Path, filename: str) -> str | None:
    """`None` if the decompile artifact is present; otherwise a string for the REPORT.

    🔴 A COMPANION to `_verify_summary` and `_tree_kinds`. Both return
    `None` for a missing file, and that answer is correct: the census must
    still assemble over an incomplete decompile.

    They used to be printed differently, and that was a defect. `verify` on
    `None` honestly said "no verify.json — the run did not reach
    reconciliation", while `tree_kinds` simply DID NOT PRINT A LINE: the
    reader saw a decompile with no L3 node kinds and could not tell "there
    is no tree" apart from "there is a tree, no kinds were found in it". A
    missing report line is the same silence as a missing number.

    One answer for both artifacts: they are asked BY FILE NAME, and their
    reason text shares the same meaning — "this stage is not on disk".
    """
    if _snapshot_exists(directory / filename):
        return None
    return (f"{filename} нет — стадия не снималась либо артефакт удалён; "
            f"пустота ниже означает «не читали», а не «в разборе нет»")


def _digest(payload: Any) -> str:
    return hashlib.sha1(repr(payload).encode()).hexdigest()[:12]


def skipped_snapshots(root: Path,
                      names: "Iterable[str]") -> list[dict[str, str]]:
    """Decompiles the census will NOT SEE, and why — by name.

    🔴 A COMPANION to `census()`. It returns `None` for "no L0.jsonl", and
    that answer is correct: the census must not be failed over one run.
    But `None` vanishes from the result without a trace, and "censused 3"
    becomes indistinguishable from "asked for ten, seven have no data". A
    denominator quietly shrunk by a missing source pushes ALL shares
    upward — the same shape as F-129.

    A separate function rather than a line inside `main`, for two reasons:
    it is called by `--json` and the text output THE SAME WAY (one answer,
    two readers), and it can be asked from a test without running the whole
    instrument.
    """
    out: list[dict[str, str]] = []
    for name in names:
        if _snapshot_exists(Path(root) / name / "L0.jsonl"):
            continue
        out.append({
            "snapshot": name,
            "why": (f"нет L0.jsonl в {Path(root) / name} — этот разбор в "
                    f"перепись НЕ ВОШЁЛ; его отсутствие есть факт о МАШИНЕ, "
                    f"а не о здании"),
        })
    return out


# ── CENSUS ──────────────────────────────────────────────────────────────────

def census(directory: Path, budget: int) -> dict[str, Any] | None:
    l0 = directory / "L0.jsonl"
    if not _snapshot_exists(l0):
        return None

    types: collections.Counter[str] = collections.Counter()
    label: dict[str, tuple[str, str]] = {}
    cat_elems: collections.Counter[str] = collections.Counter()
    cat_types: dict[str, set[str]] = collections.defaultdict(set)
    mask: dict[str, set[str]] = collections.defaultdict(set)
    # The mask of the FIRST instance of each type — exactly what a live
    # "type-first" protocol would learn. Kept separate from the union, because
    # the difference between them is precisely the cost of the premise (see BLIND_SPOTS item 3).
    first_mask: dict[str, frozenset[str]] = {}
    lost_keys = lost_instances = diverged_types = 0
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
            element_keys = frozenset((element.get("params") or {}).keys())
            known = first_mask.get(type_id)
            if known is None:
                first_mask[type_id] = element_keys
            else:
                missed = element_keys - known
                if missed:
                    # THIS instance has the key, and the first one did not.
                    # A protocol that learned the mask from the first will not ask it —
                    # the value will silently drop out of L0. This is a LOSS, not overspend.
                    lost_keys += len(missed)
                    lost_instances += 1
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

    # Simulation of the "type-first" protocol.
    #   now           — probe budget on EACH element, each falling back to the type;
    #   type-first    — the whole type + the whole first instance (2*budget per type),
    #                   after that only by this type's existence mask;
    #   +type-constants — in addition, parameters that do not vary within the type are dropped:
    #                   their value is read once from the type itself.
    probes_now = n_elements * budget
    probes_typefirst = probes_constfold = n_types * budget * 2
    for type_id, count in types.items():
        keys = mask[type_id]
        varying = sum(1 for key in keys if len(values[(type_id, key)]) > 1)
        probes_typefirst += max(0, count - 1) * len(keys)
        probes_constfold += max(0, count - 1) * varying
        if count >= 2 and first_mask.get(type_id, frozenset()) != keys:
            diverged_types += 1

    outcomes: collections.Counter[str] = collections.Counter()
    probes_measured = probes_dead = dead_pairs = live_pairs = reached_type = 0
    for row in receipts.values():
        total = sum(row[outcome] for outcome in SECTION_OUTCOMES)
        if not total:
            continue
        probes_measured += total
        for outcome in SECTION_OUTCOMES:
            outcomes[outcome] += row[outcome]
        # The probe reaches the type whenever the instance did not yield a value.
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
        # The cost of the premise the two numbers above rest on. Kept RIGHT NEXT TO
        # them deliberately: a multiplier read without it is a work plan
        # resting on a refuted equality.
        "mask_diverged_types": diverged_types,
        "mask_lost_keys": lost_keys,
        "mask_lost_instances": lost_instances,
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
        # The reason travels RIGHT NEXT TO the answer, not instead of it: `None` remains
        # `None`, but the missing report row now has an explanation.
        "tree_kinds_absent": artifact_absent_note(directory, "tree.json"),
        "verify_absent": artifact_absent_note(directory, "verify.json"),
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


# ── OUTPUT ───────────────────────────────────────────────────────────────────

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
        # The cost of the premise is printed FLUSH against the multiplier, in the same block:
        # the two numbers above are attainable only under the equality that the 15.08 measurement
        # refuted. The line stays silent only when there is nothing to lose.
        if row.get("mask_lost_keys"):
            print(f"   🔴 НО ПРЕМИССА ЛОЖНА ЗДЕСЬ: маска первого экземпляра != маска типа")
            print(f"      у {row['mask_diverged_types']} типов;"
                  f" молча потерялось бы {row['mask_lost_keys']} значений"
                  f" у {row['mask_lost_instances']} элементов"
                  f" ({_pct(row['mask_lost_instances'], row['elements'])})")
            print(f"      два числа выше — ВЕРХНЯЯ ГРАНИЦА, не план работ (BLIND_SPOTS п.3)")
        else:
            print(f"   премисса маски на ЭТОМ слепке не опровергнута"
                  f" ({row['mask_diverged_types']} расходящихся типов);"
                  f" на других опровергнута — см. BLIND_SPOTS п.3")
    if row["probes_measured"]:
        print(f"   ИЗМЕРЕНО КВИТАНЦИЯМИ (16 зондов из {row['probe_budget']}):")
        print(f"     опрошено .................. {row['probes_measured']}")
        for outcome in SECTION_OUTCOMES:
            value = row["outcomes"].get(outcome, 0)
            print(f"       {outcome:<16s}{value:>11d}   "
                  f"{_pct(value, row['probes_measured'])}")
        # 🔴 "THE EXTRA doc.GetElement ON EVERY ONE" REMOVED 25.08.2026 AS OUTDATED.
        # The instrument was advertising work DONE on 20.08: since that day the type is taken
        # ONCE PER ELEMENT (`extract.py`, "TYPE IS TAKEN ONCE PER
        # ELEMENT"), and the probe falling back to the type no longer costs a trip to the document.
        # That measurement removed ~6.1 million extra lookups across the corpus.
        # The line was calling to fix something already closed — the tree's named trap "already
        # built", bought into four times in one session.
        # The number REMAINS and remains useful: it says what share of probes
        # do not answer at the instance, i.e. how thin the output is.
        print(f"     дошло до ТИПА ............. {row['reached_type']}"
              f"   ({_pct(row['reached_type'], row['probes_measured'])})"
              f" — на экземпляре значения нет; тип уже разрешён (20.08)")
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
        print("   " + (row.get("verify_absent")
                       or "verify.json есть, но сверка пуста — "
                          "прогон не дошёл до неё"))
    if row["tree_kinds"]:
        print(f"   виды узлов L3 ............... {row['tree_kinds']}")
    elif row.get("tree_kinds_absent"):
        print(f"   виды узлов L3 ............... {row['tree_kinds_absent']}")
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
    # 🔴 `default=str(DEFAULT_ROOT)` WOULD PRINT THE STRING "None" when the installation
    # is not named — that is, it would substitute a PLAUSIBLE path for absence.
    # A plausible value is more dangerous than an empty one: no one argues with it (form 44).
    parser.add_argument("--root", default=(str(DEFAULT_ROOT) if DEFAULT_ROOT
                                           else None),
                        help="корень слепков")
    parser.add_argument("--json", action="store_true", help="машинный вывод")
    parser.add_argument("--full", action="store_true",
                        help="с --all печатать полную страницу на каждый слепок")
    args = parser.parse_args(argv)

    if args.root is None:
        print(f"корень слепков не назван: {install_root_refusal()}",
              file=sys.stderr)
        return 2
    root = Path(args.root)
    if not root.is_dir():
        print(f"нет корня слепков: {root}", file=sys.stderr)
        return 2

    names = (sorted(item.name for item in root.iterdir()
                    if _snapshot_exists(item / "L0.jsonl"))
             if args.all else args.snapshots)
    if not names:
        parser.print_help()
        return 2

    budget, breakdown = probe_budget()
    rows: list[dict[str, Any]] = []
    #: 🔴 SKIPPED PARSES GO INTO THE REPORT, NOT ONLY INTO stderr.
    #: `census` returns `None` for "no L0.jsonl", and that is the correct answer — the
    #: census must not be dropped over one run. But the omission was visible ONLY in
    #: text mode and ONLY in stderr: `--json` returned an array of three
    #: parses where ten were asked for, and "3 counted" became
    #: indistinguishable from "10 runs, seven have no data". A denominator that quietly
    #: shrank from a missing source pushes ALL shares upward.
    skipped = skipped_snapshots(root, names)
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
                   "blind_spots": BLIND_SPOTS, "snapshots": rows,
                   "asked": len(names), "skipped": skipped},
                  sys.stdout, ensure_ascii=False, indent=1, default=str)
        print()
        return 0

    if skipped:
        print(f"\n🔴 В ПЕРЕПИСЬ НЕ ВОШЛИ {len(skipped)} из {len(names)}: "
              f"{', '.join(s['snapshot'] for s in skipped)}")
        print("   их отсутствие — факт о МАШИНЕ; доли ниже сняты с "
              f"{len(rows)} разборов, а не с {len(names)}")
    if len(rows) > 1:
        render_summary(rows)
    print(f"\n{BLIND_SPOTS}")
    print(f"\nбюджет зондов прочитан из {EMITTER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
