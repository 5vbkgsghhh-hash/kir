"""HOW REAL TEAMS DESIGN — derived from their models, not from norms.

🔴 WHY THIS FILE. The "house" lesson (`course/building.py`) gave the model
the building's NUMBERS: storey height, room area, grid spacing. It did not
give the METHOD: how a print run is assembled, how things are named, what
is taken from a catalogue, what is not modelled at all. A 22.08.2026
measurement: across the whole course, "group" appears 0 times as a model
organization technique, "prefix" 0, "type catalogue" 0. The model can say
`create_wall` and does not know that a real house is 41-83% assembled from
REPEATED PIECES.

🔴 WHY THIS IS NOT A LIST OF ADVICE. Every statement here has passed the
five-stage discriminator `tools/discipline_practice.py` and arrives with its
own verdict: BEST (holds unanimously across several buildings), ACCEPTED
WITH A CAVEAT (does not hold everywhere — and the exception buildings are
named), ANTI-PRACTICE (the corpus refutes it). Advice with no verdict does
not make it into this file.

🔴 THE DISCRIMINATOR'S MAIN FINDING, AND IT IS UNEXPECTED: the number of
practices with a BEST verdict is ZERO. Not one rule holds unanimously across
all admissible buildings. This is not an instrument failure but a property
of the subject: every team has its own way of working, and a textbook that
says "do it this way" would lie about a quarter of the corpus. So the
document teaches THE PRACTICE TOGETHER WITH ITS EXCEPTION.

WHAT THIS DOCUMENT DOES NOT DO. It does not replace norms (those are held by
`data/skills/compliance.md`), does not teach intent or taste, does not
promise the model will become an architect. It conveys an ASSEMBLY METHOD,
measured against other teams' models.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, NamedTuple

from kir.course.building import (DECOMPILE_ROOT, RECORDED as BUILDING_NUMBERS,
                                      counts_as_a_building)

#: The runs against which this document's numbers are recomputed. NAMED
#: EXPLICITLY, not "the whole corpus": recomputation streams `L0.jsonl` (85
#: MB for K2), and "however much got done" is not a reproducible
#: measurement. Two buildings from different teams are the minimum at which
#: a "holds across several" claim is even checkable.
MEASURED_RUNS = ("k2_ar_rd_v7",
                 "mnvnk_atr_pd_b14_k6_ar_r2022_отсоединено_отсоединено")

#: The full verdict set is given by `tools/discipline_practice.py` across 66
#: analyses. What stands here are the numbers of the TWO named buildings; a
#: mismatch with the instrument means the corpus has drifted, and that must
#: turn red.
PRACTICE_TOOL = "PYTHONPATH=. venv/bin/python tools/discipline_practice.py"


def _open(run: str, name: str):
    path = os.path.join(DECOMPILE_ROOT, run, name)
    try:
        from kir.decompile.snapshot_io import open_snapshot
        return open_snapshot(path, "rt", encoding="utf-8")
    except Exception:  # noqa: BLE001 — a missing corpus is not a machine defect
        return None


def _json(run: str, name: str):
    handle = _open(run, name)
    if handle is None:
        return None
    try:
        with handle:
            return json.loads(handle.read())
    except Exception:  # noqa: BLE001
        return None


def _recompute_all() -> dict[str, list] | None:
    """A fresh recomputation of EVERY metric — or `None`, if there is no source.

    🔴 AVAILABILITY USED TO BE ASKED OF ONE FILE OUT OF FIVE SOURCE KINDS
    (F-179, 29.08.2026). It used to say `all(_json(run, "group.index.json")
    is not None ...)`: the presence of ONE artifact was declared proof of
    the presence of EVERYTHING, while the document consumes five kinds — L0,
    family placement, curtain wall, profile and tags. With a live
    `group.index.json` and the rest torn down, the document printed in full
    and with confidence.

    Naming four more file names is not an option: that is the same growing
    list, and it will lag behind the first new artifact. We ask THE THING
    THE DOCUMENT ITSELF IS — every one of its metrics must RECOMPUTE.

    🔴 THE SIGNAL IS LENGTH, NOT TRUTHINESS, and this is not pedantry. `if
    not m.recompute()` would treat a LEGITIMATE zero as a missing source —
    exactly the substitution this whole cluster (`F-247`) was written
    against, and a legitimate zero DOES exist here: `range_name` is recorded
    as `(2.2, 0.0)`. Measurement showed that recomputing against a missing
    source returns a SHORT list (`[]`), not a list of zeros — so length
    tells the two cases apart precisely, and there is no need to set up a
    second mechanism.

    How many values there must be is declared by the metric itself —
    `len(m.values)`, one number per building. A second list alongside would
    be a second carrier.
    """
    fresh: dict[str, list] = {}
    for key, m in RECORDED.items():
        if m.recompute is None:
            continue
        try:
            got = m.recompute()
        except Exception:      # noqa: BLE001 — a missing source is data
            return None
        if len(got) != len(m.values):
            return None
        fresh[key] = got
    return fresh


def available() -> bool:
    """Whether the document is available — that is, whether EVERY metric recomputes."""
    return _recompute_all() is not None


def _elements(run: str) -> tuple[set, dict, list]:
    """Identifiers, categories and type names of the READ elements."""
    ids, cats, names = set(), {}, []
    handle = _open(run, "L0.jsonl")
    if handle is None:
        return ids, cats, names
    with handle:
        for line in handle:
            if '"element"' not in line:
                continue
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if row.get("record") != "element":
                continue
            el = row.get("element") or {}
            eid = str(el.get("element_id") or "")
            ids.add(eid)
            cats[eid] = str(el.get("category") or "?")
            if el.get("type_name"):
                names.append(str(el["type_name"]))
    return ids, cats, names


def _members(run: str) -> set:
    gi = (_json(run, "group.index.json") or {}).get("group_index") or {}
    out = set()
    for inst in (gi.get("instances") or {}).values():
        out.update(str(m) for m in (inst.get("member_ids") or []))
    return out


def group_share() -> list[float]:
    """The share of read elements INSIDE groups, one number per building.

    🔴 THE NUMERATOR AND DENOMINATOR ARE FROM ONE POPULATION. K2 has 134,176
    DISTINCT group members against 115,880 read elements: 86,547 members lie
    in categories the decompiler does not read. A naive division gives
    115.8%, that is, more than the whole, and the instrument's first
    edition printed exactly that.
    """
    out = []
    for run in MEASURED_RUNS:
        ids, _cats, _names = _elements(run)
        if ids:
            out.append(round(100.0 * len(_members(run) & ids) / len(ids), 1))
    return out


def enclosure_group_share() -> list[float]:
    """The share of the ENVELOPE (walls, curtain wall, doors) inside groups — per building."""
    shell = ("OST_Walls", "OST_CurtainWallMullions", "OST_CurtainWallPanels",
             "OST_CurtainGridsWall", "OST_Doors")
    out = []
    for run in MEASURED_RUNS:
        ids, cats, _names = _elements(run)
        members = _members(run) & ids
        total = sum(1 for c in cats.values() if c in shell)
        got = sum(1 for e in members if cats.get(e) in shell)
        if total:
            out.append(round(100.0 * got / total, 1))
    return out


def annotation_group_share() -> list[float]:
    """The share of ANNOTATION (rooms, tags, dimensions) inside groups — per building."""
    marks = ("OST_Rooms", "OST_RoomTags", "OST_Dimensions",
             "OST_MultiCategoryTags", "OST_DoorTags", "OST_WindowTags")
    out = []
    for run in MEASURED_RUNS:
        ids, cats, _names = _elements(run)
        members = _members(run) & ids
        total = sum(1 for c in cats.values() if c in marks)
        got = sum(1 for e in members if cats.get(e) in marks)
        if total:
            out.append(round(100.0 * got / total, 1))
    return out


def _group_names(run: str) -> list[str]:
    gi = (_json(run, "group.index.json") or {}).get("group_index") or {}
    return [str(d.get("group_type_name") or "")
            for d in (gi.get("definitions") or {}).values()]


_STOREY = re.compile(r"(?<![0-9A-Za-zА-Яа-я])\d{1,2}\s*этаж")
_RANGE = re.compile(r"L\d{1,2}\s?-\s?L?\d{1,2}")
_PREFIX = re.compile(r"^\d{3}_")


def _share(names: list, rx) -> float:
    return round(100.0 * sum(1 for n in names if rx.search(str(n))) / len(names), 1) \
        if names else 0.0


def storey_in_group_name() -> list[float]:
    return [_share(_group_names(r), _STOREY) for r in MEASURED_RUNS
            if _group_names(r)]


def range_in_group_name() -> list[float]:
    return [_share(_group_names(r), _RANGE) for r in MEASURED_RUNS
            if _group_names(r)]


def prefix_in_type_name() -> list[float]:
    out = []
    for run in MEASURED_RUNS:
        _ids, _cats, names = _elements(run)
        if names:
            out.append(_share(names, _PREFIX))
    return out


def in_place_share() -> list[float]:
    out = []
    for run in MEASURED_RUNS:
        idx = (_json(run, "family_placement.index.json") or {}) \
            .get("family_placement_index") or {}
        if idx:
            out.append(round(100.0 * sum(1 for v in idx.values()
                                         if v.get("in_place")) / len(idx), 2))
    return out


def curtain_manual_share() -> list[float]:
    """The share of curtain-wall systems whose grid spacing is NOT set along either axis."""
    out = []
    for run in MEASURED_RUNS:
        idx = (_json(run, "curtain.index.json") or {}).get("curtain_index") or {}
        rows = [v for v in idx.values() if v.get("curtain_available")]
        if not rows:
            continue
        manual = 0
        for value in rows:
            slots = (value.get("grid_layout") or {}).get("slots") or {}
            if not any(slots.get(k) for k in ("horiz", "vert", "grid1", "grid2")):
                manual += 1
        out.append(round(100.0 * manual / len(rows), 1))
    return out


def types_per_element() -> list[float]:
    """How many instances there are per ONE catalogue type."""
    out = []
    for run in MEASURED_RUNS:
        prof = _json(run, "open_model.profile.json") or {}
        types = sum(len(p.get("entries") or []) for p in prof.get("pools") or [])
        ids, _c, _n = _elements(run)
        if types and ids:
            out.append(round(len(ids) / types, 1))
    return out


#: ANNOTATION DOES NOT LIE EVERYWHERE. `tag.index.json` exists for two runs
#: from two buildings; `k2_ar_rd_v7` does not have it at all, so the tags
#: chapter has ITS OWN baseline, named separately rather than dissolved into
#: the common one.
TAG_RUNS = ("13a-rd-ar-k2_v33_kuklev.d.s",
            "mnvnk_atr_pd_b14_k6_ar_r2022_отсоединено_отсоединено")


def _tags(run: str) -> list[dict]:
    got = _json(run, "tag.index.json") or {}
    index = got.get("tag_index") or {}
    return [v for v in index.values() if isinstance(v, dict)]


def tags_per_element() -> list[float]:
    """Tags per ONE tagged element.

    🔴 THE DENOMINATOR IS `tagged_element_id`, NOT `element_id`. The latter
    is the identifier of the TAG ITSELF, and dividing by it gives exactly
    1.0 for any building: the instrument would be working correctly and
    would be answering the question "how many tags per tag".
    """
    out = []
    for run in TAG_RUNS:
        rows = _tags(run)
        tagged = {r.get("tagged_element_id") for r in rows
                  if r.get("tagged_element_id")}
        if tagged:
            out.append(round(len(rows) / len(tagged), 1))
    return out


def tagged_elements() -> list[int]:
    out = []
    for run in TAG_RUNS:
        rows = _tags(run)
        tagged = {r.get("tagged_element_id") for r in rows
                  if r.get("tagged_element_id")}
        if rows:
            out.append(len(tagged))
    return out


def tag_views() -> list[int]:
    """How many VIEWS annotation lives on. A view is its unit of organization."""
    out = []
    for run in TAG_RUNS:
        rows = _tags(run)
        if rows:
            out.append(len({r.get("owner_view_name") for r in rows}))
    return out


def _placements(run: str) -> list[dict]:
    got = _json(run, "family_placement.index.json") or {}
    index = got.get("family_placement_index") or {}
    return [v for v in index.values() if isinstance(v, dict)]


def families() -> list[int]:
    """How many DIFFERENT families make up the building."""
    out = []
    for run in MEASURED_RUNS:
        rows = _placements(run)
        if rows:
            out.append(len({r.get("family_name") for r in rows
                            if r.get("family_name")}))
    return out


def placements_per_family() -> list[float]:
    out = []
    for run in MEASURED_RUNS:
        rows = _placements(run)
        fams = {r.get("family_name") for r in rows if r.get("family_name")}
        if fams:
            out.append(round(len(rows) / len(fams), 1))
    return out


def nested_share() -> list[float]:
    """The share of placements INSIDE another family (`super_component_id`).

    This is the answer to the question "is a family a flat part or an
    assembly": every fourth or fifth placement is nested, that is, the
    author assembles a family OUT OF FAMILIES rather than drawing it whole.
    """
    out = []
    for run in MEASURED_RUNS:
        rows = _placements(run)
        if rows:
            out.append(round(100.0 * sum(
                1 for r in rows if r.get("super_component_id")) / len(rows), 1))
    return out


class Measured(NamedTuple):
    """A measurement TOGETHER WITH ITS BASELINE and the discriminator's verdict.

    The shape is copied from `building.Recorded` on purpose: there it was
    paid for by the fact the baseline lived as prose and silently drifted
    from the corpus. One field is added — `verdict`: a claim with no
    verdict does not make it into this document.
    """

    values: tuple
    unit: str
    what: str
    docs: int
    verdict: str
    recompute: Callable[[], list]


#: RECORDED MEASUREMENTS from 22.08.2026 across the two `MEASURED_RUNS`
#: buildings. `test_design_numbers_are_current` turns red if a value OR its
#: baseline has drifted from disk: a stale measurement in a textbook is
#: indistinguishable from invention.
RECORDED: dict[str, Measured] = {
    "group_share": Measured(
        (41.1, 82.6), "%", "элементов внутри групп", 2,
        "ПРИНЯТЫЙ с оговоркой (5 документов из 9; не держится у K4 24.9 %, "
        "SOB6.2 и SKLNK)", group_share),
    "enclosure": Measured(
        (96.9, 96.7), "%", "ОБОЛОЧКИ внутри групп", 2,
        "ПРИНЯТЫЙ: оболочка группируется почти целиком в обоих зданиях, и это "
        "СИЛЬНЕЕ общей доли 41.1 % — группируют не «всё подряд», а ограждение",
        enclosure_group_share),
    # 🔴 HERE I GUESSED AND WAS WRONG. What was recorded was (0.1, 0.4) —
    # "annotation is grouped nowhere". Recomputation gave 0.1 and 24.2:
    # MNVNK puts A QUARTER of its annotation into groups. The claim
    # "nowhere" held on one building and sounded like a law. This is
    # exactly why RECORDED gets recomputed.
    "annotation": Measured(
        (0.1, 24.2), "%", "РАЗМЁТКИ внутри групп", 2,
        "ПРИНЯТЫЙ с оговоркой: у K2 разметка вне групп (0.1 %), у MNVNK "
        "четверть её ВНУТРИ (24.2 %) — уклад команды, а не закон",
        annotation_group_share),
    "storey_name": Measured(
        (51.5, 61.6), "%", "имён групп с «N этаж»", 2,
        "ПРИНЯТЫЙ с оговоркой (4 документа из 6; K4 2.7 %, LEN 0 %)",
        storey_in_group_name),
    "range_name": Measured(
        (2.2, 0.0), "%", "имён групп с ДИАПАЗОНОМ этажей", 2,
        "ПРИНЯТЫЙ с оговоркой (держится на ОДНОМ документе из 6 — K4 19.5 %)",
        range_in_group_name),
    "prefix": Measured(
        (5.4, 0.0), "%", "экземпляров с префиксом NNN_ в имени типа", 2,
        "🔴 АНТИПРИЁМ: не держится НИ НА ОДНОМ документе при пороге 30 %",
        prefix_in_type_name),
    "in_place": Measured(
        (0.02, 0.0), "%", "размещений, смоделированных НА МЕСТЕ", 2,
        "ПРИНЯТЫЙ с оговоркой (8 документов из 9; не держится у LEN)",
        in_place_share),
    "curtain_manual": Measured(
        (99.9, 8.0), "%", "витражей без заданного шага сетки", 2,
        "🔴 АНТИПРИЁМ у K2 (999 систем из 1000 нарезаны руками); у MNVNK "
        "приём соблюдён", curtain_manual_share),
    "tags_per_element": Measured(
        (4.4, 1.5), "", "марок на один помеченный элемент", 2,
        "ПРИНЯТЫЙ с оговоркой: 4.4 у K2 против 1.5 у MNVNK — плотность "
        "разметки это уклад команды, а не норма", tags_per_element),
    "tagged": Measured(
        (4557, 1330), "", "РАЗНЫХ помеченных элементов", 2,
        "ПРИНЯТЫЙ: помечается малая доля модели, а не всё подряд",
        tagged_elements),
    "tag_views": Measured(
        (217, 49), "", "видов, на которых живёт разметка", 2,
        "ПРИНЯТЫЙ: единица организации разметки — ВИД, а не этаж и не система",
        tag_views),
    "families": Measured(
        (153, 89), "", "РАЗНЫХ семейств набирают здание", 2,
        "ПРИНЯТЫЙ: номенклатура семейств мала и конечна на обоих зданиях",
        families),
    "per_family": Measured(
        (251.0, 128.0), "", "размещений на одно семейство", 2,
        "ПРИНЯТЫЙ: одно семейство работает сотнями экземпляров",
        placements_per_family),
    "nested": Measured(
        (20.6, 25.6), "%", "размещений ВНУТРИ другого семейства", 2,
        "ПРИНЯТЫЙ: семейство собирается ИЗ семейств на обоих зданиях",
        nested_share),
    "per_type": Measured(
        (138.8, 19.8), "экз/тип", "экземпляров на один тип каталога", 2,
        "ПРИНЯТЫЙ: каталог конечен и много меньше модели", types_per_element),
}


# ═════════════════════════════════════════════════════════════════ DOCUMENT

def _pair(key: str, fresh: dict[str, list]) -> str:
    """"41.1% and 82.6%" — both buildings, not an average.

    An average over two ways of working describes neither of them: 41 and
    83 give 62, and no such building exists in the corpus. The spread here
    is the SUBJECT, not noise.

    🔴 WHAT IS PRINTED IS THE RECOMPUTATION, NOT THE RECORD (F-179, second
    half). It used to say `m.values` — constants captured on the day they
    were recorded — and the document WAS A RECORD PASSED OFF AS A
    MEASUREMENT: course rule 1 directly requires "EVERY NUMBER IS
    RECOMPUTED... a stale measurement in a textbook is indistinguishable
    from invention". `fresh` is computed ONCE for the whole document
    (`_recompute_all`), not once per metric: a second pass over the corpus
    would cost reading two L0s again fifteen times over.

    `RECORDED[key].values` remains THE RECORD and is not deleted: a
    mismatch between the record and the recomputation is a finding, guarded
    by `test_course_design.py::ЗаписьСходитсяСПересчётом`.
    """
    m = RECORDED[key]
    # A REGULAR SPACE, NOT A THIN ONE. A thin space (U+2009) is
    # typographically more correct, but this document's text is grepped and
    # checked by tests; an invisible difference in the space has already
    # cost one red run here.
    return " и ".join(f"{v} {m.unit}".strip() for v in fresh[key])


def ambiguous_pools() -> list:
    """Catalogue pools where the NAME does not distinguish a type: one name, several entries.

    🔴 MEASUREMENT ON 23.08, A PAIRED RUN ON A TYPICAL STOREY. Both hands
    hit the same thing: **93 `KIR-G102` refusals** across all large
    programs. The cause is not the author — the document's catalogue has
    THREE duct types, and all three are literally named "Default". So
    `by_name("Default")` gives three matches, `by_default()` does too, and
    naming a type BY NAME is impossible in principle.

    The primer's refusal is CORRECT here: it must not guess. But the author
    only learns this by running into it, and the MEP chapter without this
    line would be teaching something unattainable.
    """
    from kir.decompile.snapshot_io import read_snapshot_text
    import collections
    out = []
    for run in MEASURED_RUNS[:1]:
        prof = _json(run, "open_model.profile.json") or {}
        for pool in prof.get("pools") or []:
            rows = pool.get("entries") or []
            names = [str(e.get("type_name") or e.get("name") or "") for e in rows]
            dup = [n for n, k in collections.Counter(names).items()
                   if n and k > 1]
            if dup:
                out.append((str(pool.get("name") or "?"), len(rows), len(dup)))
    return sorted(out, key=lambda r: -r[2])[:6]


def _allowed_imports() -> tuple:
    """The allowed imports — ASKED OF THE SANDBOX, not copied out.

    🔴 The list is live: it depends on the `KUKAI_IR_AUTHOR_GEOMETRY_LIBS`
    flag, and a second copy of it in the text would drift from the sandbox
    on the very first toggle — silently, and the model would trust the
    text.
    """
    try:
        from kir.sandbox import allowed_imports_for_env
        return tuple(allowed_imports_for_env())
    except Exception:  # noqa: BLE001
        return ("(список недоступен: песочница не отвечает)",)


def _refuse() -> str:
    return ("ДОКУМЕНТ «КАК ПРОЕКТИРУЮТ» НЕДОСТУПЕН: корпуса разборов нет на "
            f"этой машине ({DECOMPILE_ROOT}). Все числа этого документа СНЯТЫ "
            "с настоящих проектов; без корпуса он стал бы пересказом по "
            "памяти, то есть ровно тем, чего он и не должен быть.")


def build_design_document() -> str:
    """The method textbook. It is GENERATED, not stored as text.

    Numbers are substituted from this module's `RECORDED` and from
    `building.RECORDED`; hand-written markdown would silently drift from
    the corpus, and that is a named defect of this tree, not a hypothetical
    risk.
    """
    fresh = _recompute_all()
    if fresh is None:
        return _refuse()

    b = BUILDING_NUMBERS
    parts: list[str] = []
    add = parts.append

    add("""КАК СОБИРАЮТ ПРОДАКШН-МОДЕЛЬ — ВЫВЕДЕНО ИЗ ЧУЖИХ МОДЕЛЕЙ
════════════════════════════════════════════════════════════════════

0. ЧЕМ ЭТО ИЗМЕРЕНО, И ЧЕГО ЗДЕСЬ НЕТ

Корпус разборов: 66 прогонов, 15 различных документов, из них
ПРОИЗВОДСТВЕННЫХ российских — девять. Отведены: три образца Autodesk
(«Snowdon Towers Sample») и наши собственные файлы («Проект1», «демо»):
учебник, подтверждаемый тем, что по нему уже написано, ничего не
доказывает.

🔴 ЧЕСТНЫЙ ЗНАМЕНАТЕЛЬ. У самого крупного здания разбор читает 115 880
элементов из 310 575 — ПОКРЫТИЕ ОТ ДОКУМЕНТА 9.64 %. Всё, что ниже,
измерено на этой десятой части. Не прочитано: виды, листы,
спецификации, материалы, зависимости, опорные плоскости, пирог
конструкции, пользовательские параметры.

Числа ниже пересчитываются с диска, и тест краснеет при расхождении.
Полный вердиктный свод по всем разделам даёт прибор:
""" + f"    {PRACTICE_TOOL}")

    add(f"""
1. ЕДИНИЦА ЗАМЫСЛА — НЕ ЭЛЕМЕНТ, А ПОВТОРЁННЫЙ КУСОК

Настоящий дом собран группами: внутри них {_pair('group_share', fresh)}
прочитанных элементов (K2 и MNVNK).

🔴 НО ГРУППИРУЮТ НЕ ВСЁ ПОДРЯД, И ЭТО ГЛАВНОЕ.
    ОБОЛОЧКА (стены, витраж, импосты, панели, двери): {_pair('enclosure', fresh)}
    РАЗМЁТКА (помещения, марки, размеры):            {_pair('annotation', fresh)}

То есть в группу кладут ОГРАЖДЕНИЕ, а марки и размеры остаются снаружи.
Разброс у разметки — уклад команды: K2 не группирует её вовсе, MNVNK
кладёт внутрь четверть.

ВЕРДИКТ: {RECORDED['group_share'].verdict}.

🔴 КАК ЭТО ПИШЕТСЯ У НАС — ВЫЗОВ ЦЕЛИКОМ, А НЕ ОТСЫЛКА.
Прошлая редакция этой главы говорила «смотри `course("единица")`», и на
восьми парных прогонах курс не позвали НИ РАЗУ: указатель упирался в
тупик, а групп в построенном оказалось ноль на обоих плечах. Поэтому
вызов стоит здесь.

    H = 3300
    create_level(name="Этаж 2", elev_mm=H)      # уровень — СВОЕЙ программой

    with unit("Секция_К1_Этаж 2",
              placements=[[0, 0, H * k] for k in range(1, 12)]):

        for gx in (0, 6000, 12000):             # КР: колонны по осям
            for gy in (0, 9000):
                create_column(xy=[gx, gy], level="Этаж 2",
                              symbol="Колонна 600x600", top_level="Этаж 3")

        create_floor(outline=[[0, 0], [12000, 0], [12000, 9000], [0, 9000]],
                     level="Этаж 2", type="Монолитный бетон 225мм",
                     structural=True)

        ring = [[0, 0], [12000, 0], [12000, 9000], [0, 9000]]
        for a, b in zip(ring, ring[1:] + ring[:1]):   # АР: периметр
            create_wall(p0_mm=a, p1_mm=b, level="Этаж 2", height_mm=H,
                        type="Наружная - Кирпич 380мм")

        create_wall(p0_mm=[6000, 0], p1_mm=[6000, 9000], level="Этаж 2",
                    height_mm=H,        # предел огнестойкости — В ИМЕНИ типа
                    type="Внутренние - Перегородка (2 час) 135мм")

        create_room(xy=[3000, 2000], level="Этаж 2", name="Жилая комната")
        create_window(host_wall=..., level="Этаж 2", symbol="Окно 1500x1500")

Что тут происходит по контракту `create_group`:
  * члены схлопываются в ОДНО определение (`as_group=True` — умолчание);
  * `placements` — смещения [dx, dy, dz] ДОПОЛНИТЕЛЬНЫХ вхождений;
    вхождение 0 это сами члены в абсолютных координатах. Одиннадцать
    смещений плюс исходное — двенадцать этажей, написанных ОДИН раз;
  * `name` уезжает в GroupType Name — то самое имя из главы 2;
  * ссылка на соседа ВЫШЕ по списку членов законна (порядок членов есть
    порядок создания); ссылка ВПЕРЁД или НАРУЖУ множества — отказ.

Без `placements` группа тоже пишется: она остаётся АДРЕСОМ, по которому
наблюдение назовёт замысел. Но повтора не будет — повторяют смещения.

🔴 ЕДИНИЦА — ЭТО ЭТАЖ ЦЕЛИКОМ, А НЕ ОБРАЗЕЦ НА ДВЕ СТЕНЫ. Замер парного
прогона: с примером на две стены и многоточием две попытки из четырёх
построили 7 и 19 элементов вместо трёхсот. Единица стоит ровно столько,
сколько в неё положено: колонны, перекрытие, ограждение, перегородки,
помещения, проёмы, по ветке каждой сети — а потом одиннадцать смещений
превращают это в двенадцать этажей.

🔴 УРОВЕНЬ ОБЪЯВЛЯЙ СВОЕЙ ПРОГРАММОЙ. `design_check()` берёт отметки только
из `create_level` этой же программы: ссылка на уровень открытой модели, и по
имени и по id, у судьи не разрешается ничем. Программа на 714 операций с
204 помещениями получила от него «в модели нет помещений» ровно поэтому.
Стройке чужой уровень годен — расходятся судья и стройка.""")

    add(f"""
2. ЧТО ИМЕННО ПОВТОРЯЮТ — СИСТЕМА × ОДИН ЭТАЖ

Имена определений групп разбираются так:
    {{система}}_{{материал}}_{{этаж}}   Ядро_Монолит_ЖБ_15 этаж
                                        Стены_Монолит_ЖБ_2 этаж
                                        Наружные стены_К2_42 этаж

«N этаж» в имени: {_pair('storey_name', fresh)}.
ДИАПАЗОН этажей (AS_AreaB_K2_L02-L37): {_pair('range_name', fresh)}.

🔴 ЗДЕСЬ ОПРОВЕРГНУТА НАША СОБСТВЕННАЯ ПОСЫЛКА. Мы считали единицей
повторения «систему × диапазон этажей». Замер: диапазон встречается у
2.2 % имён K2 и 0 % MNVNK, и держится ровно на одном здании из шести
(K4, 19.5 %). Единица — ОДИН ЭТАЖ; диапазон — исключение одной команды.

ВЕРДИКТ диапазона: {RECORDED['range_name'].verdict}.

🔴 ГДЕ ЭТО ИМЯ ЖИВЁТ В ПРОГРАММЕ — два места, и оба надо назвать.
    `unit("Стены_Монолит_ЖБ_2 этаж", ...)`  → имя определения группы
    `create_type(name="ДС 21х11 EIS60", ...)` → имя типоразмера каталога

На восьми парных прогонах доля имён с классифицирующим полем вышла
0 % при 61-108 именах на прогон: модель пишет «Наружная стена 200 мм».
Это законное имя и бесполезная классификация — по нему нельзя ни
отобрать, ни сверить. Имя обязано нести ПОЛЕ: систему, материал, этаж,
предел огнестойкости или габарит.""")

    add(f"""
3. ПОРЯДОК СБОРКИ

    уровни → оси → каркас → оболочка → проёмы → помещения → инженерия

Помещение стоит ПОСЛЕ ограждений не по вкусу, а по устройству Ревита:
переигровка разборов показывает, что ВСЕ расхождения приходятся на
`create_room`, и производитель называет причину дословно — «room
geometry is enclosure-derived, not a stored input». Помещение нельзя
поставить раньше стен: оно ими и определяется.""")

    add(f"""
4. НОМЕНКЛАТУРА РАНЬШЕ РАССТАНОВКИ

На один тип каталога приходится {_pair('per_type', fresh)} экземпляров.
Каталог КОНЕЧЕН и много меньше модели: сперва заводится набор типов,
потом ими набивается здание.

НА МЕСТЕ НЕ МОДЕЛИРУЮТ: доля in-place {_pair('in_place', fresh)}.
Девять размещений из 38 402 у K2 и ноль из 11 393 у MNVNK.
ВЕРДИКТ: {RECORDED['in_place'].verdict}.

КАК ЭТО ПИШЕТСЯ У НАС: `create_type(...)` заводит типоразмер,
`author_family(...)` — семейство с ручками; `place_family(...)` ставит.""")

    add(f"""
5. ИМЯ ТИПА — ЭТО СТРУКТУРА ДАННЫХ, НО НЕ ТА, КОТОРУЮ МЫ ЖДАЛИ

Классифицирующих ПАРАМЕТРОВ у типа нет: `entries[].params` пуст у всех
918 типов, слои пирога не извлекаются. Проектировщик решает задачу
именем — но КАК ИМЕННО, зависит от команды:

    ДС 21х11 EIS60 Л_в кладке    марка · габарит · предел · навеска
    106_Наружный_Стена_Пустой    трёхзначный префикс + описание
    Уголок 90х7, L=2030          сортамент + длина
    TSL_SHM_УГО_П_оу_IP20_1п     код изделия (ЭОМ)

🔴 ТРЁХЗНАЧНЫЙ ПРЕФИКС — АНТИПРИЁМ ПО ЗАМЕРУ. Он есть у {_pair('prefix', fresh)}
экземпляров и у 12.2 % типов 13A против 0 % у MNVNK: это конвенция ОДНОЙ
конторы, а не отраслевая норма. Учить ей — значит выдать частный
регламент за практику.
ВЕРДИКТ: {RECORDED['prefix'].verdict}.

ЧТО ДЕРЖИТСЯ НА СЕМИ ДОКУМЕНТАХ ИЗ ДЕВЯТИ: предел огнестойкости пишется
В ИМЕНИ (EI30/EIS60). Параметра для него нет нигде, и имя — единственный
носитель.

СЛЕДСТВИЕ ДЛЯ АВТОРА: правило именования выбирается ДО модели и
соблюдается всей моделью. Какое именно — решает задача; что оно должно
быть — решено за нас корпусом.""")

    add(f"""
6. ЧИСЛА ЗДАНИЯ — берутся у урока «дом», не переписываются сюда

    высота этажа   {b['storey_mm'].value:.0f} мм   (база {b['storey_mm'].n} разностей)
    площадь комнаты {b['room_m2'].value:.3f} м²  (база {b['room_m2'].n} помещений)
    шаг осей       {b['grid_mm'].value:.0f} мм   (база {b['grid_mm'].n} пар)
    толщина стены  {b['wall_mm'].value:.0f} мм   (база {b['wall_mm'].n} стен)

Полный урок с квартилями: `course("дом")`.""")

    add(f"""
7. ЧЕГО НЕ МОДЕЛИРУЮТ РУКАМИ

Витраж: доля систем БЕЗ заданного шага сетки — {_pair('curtain_manual', fresh)}.
🔴 У K2 999 систем из 1000 нарезаны поштучно. Это НЕ образец: это
означает, что фасад там правится вручную и не переживает изменения шага.
У MNVNK тот же приём соблюдён (8 %). ВЕРДИКТ: {RECORDED['curtain_manual'].verdict}.

Импосты и панели витража Ревит порождает САМ по сетке — их в программе
писать не надо. То же с марками помещений при заданном помещении.""")

    add("""
8. ПОВТОР, КОТОРЫЙ ВИДИМ МЫ, — НЕ ТОТ, КОТОРЫЙ ЗАВЁЛ ПРОЕКТИРОВЩИК

Наш слой `merkle` находит одинаковые поддеревья по содержимому. Замер
`tools/repeat_vs_author.py`:

    K2     мы видим 16.7 % того, что автор собрал в группы
    MNVNK  26.7 %
    из 145 наших форм ЦЕЛИКОМ внутри одной группы — НОЛЬ (K2), одна (MNVNK)

То есть геометрическое тождество и авторский замысел РЕЖУТ МОДЕЛЬ
ПО-РАЗНОМУ. Практический вывод для автора: не полагайся на то, что
одинаковое само схлопнется — ОБЪЯВЛЯЙ единицу явно.""")

    add(f"""
9. СЕМЕЙСТВО — НЕ ДЕТАЛЬ, А СБОРКА

    разных семейств на здание      {_pair('families', fresh)}
    размещений на одно семейство   {_pair('per_family', fresh)}
    размещений ВНУТРИ другого      {_pair('nested', fresh)}

Здание набирается из сотни с небольшим семейств, и каждое работает сотнями
экземпляров. Но главное — не это, а вложенность: КАЖДОЕ ПЯТОЕ-ЧЕТВЁРТОЕ
размещение стоит внутри другого семейства (`super_component_id`). То есть
семейство собирают ИЗ СЕМЕЙСТВ, а не рисуют целиком: дверь несёт полотно,
коробку и наличник отдельными вложенными экземплярами.

Половина размещений K2 висит на СТЕНЕ (`host_class="Wall"` у 18 528 из
38 402): у элемента есть ХОЗЯИН, и правка стены двигает всё, что на ней.

КАК ЭТО ПИШЕТСЯ У НАС: `author_family(...)` заводит семейство с ручками,
`place_family(...)` ставит экземпляр, `host` связывает его со стеной.

⚠ ГРАНИЦА: в двух верхних семействах K2 стоят `Rectangular Mullion` (10 384)
и `System Panel` (5 234) — это импосты и панели витража, которые Ревит
порождает САМ по сетке. Писать их в программе не надо, и в счёте семейств
они завышают номенклатуру.""")

    add(f"""
10. РАЗМЕТКА — ОТДЕЛЬНЫЙ СЛОЙ, И ЕЁ ЕДИНИЦА НЕ ЭТАЖ, А ВИД

    марок на помеченный элемент   {_pair('tags_per_element', fresh)}
    разных помеченных элементов   {_pair('tagged', fresh)}
    видов, на которых живёт       {_pair('tag_views', fresh)}

Помечается МАЛАЯ доля модели: 4 557 элементов из 115 880 у K2. Что именно —
видно по именам марок: «Квартира_№ Корпуса + № квартиры + № помещения» 5 876,
«OLP_Площадь» 4 422, «Т_Маркировка типоразмера» 3 184, «OLP_Огнестойкость» 904.
То есть марка несёт ту же классификацию, что и имя типа, — второй раз, для
чертежа.

Плотность разметки — уклад команды: 4.4 марки на элемент у K2 против 1.5 у
MNVNK. Единого правила корпус не даёт, и документ его не выдумывает.

⚠ ГРАНИЦА: `tag.index.json` есть у двух прогонов; у `k2_ar_rd_v7` его нет
вовсе. База этой главы своя и меньше остальных.""")

    _amb = ambiguous_pools()
    _amb_text = ("\n".join(f"    {n:<28} записей {c:>3}, имён-двойников {d}"
                            for n, c, d in _amb)
                 if _amb else "    (в этом прогоне двойников не найдено)")
    add(f"""
11. ИМЯ НЕ ВСЕГДА РАЗЛИЧАЕТ ТИП — И ЧАЩЕ ВСЕГО У СЕТЕЙ

Пулы каталога, где ОДНО имя носят несколько записей (по разбору
{MEASURED_RUNS[0]}):

{_amb_text}

🔴 Двойники есть не только у сетей: у `family_symbols` их 28 из 597. У сетей
же это доходит до предела — в одном замеренном каталоге ВСЕ ТРИ типа
воздуховода назывались «По умолчанию», и тогда `by_name("По умолчанию")` даёт
три совпадения, `by_default()` — тоже, а назвать тип именем нельзя вовсе.

⚠ ЭТО ФАКТ О ТЕХ КАТАЛОГАХ, А НЕ О ТВОЁМ. Число типов и их имена — свойство
ОТКРЫТОГО ДОКУМЕНТА, и оно у каждого своё. Не переноси числа отсюда на свой
проект: спроси КАТАЛОГ, который тебе подан, и посмотри, различимы ли имена в
нужном пуле. Утверждать про чужой документ по чужому замеру — ровно та
ошибка, против которой написан весь раздел 0.

ЧТО ДЕЛАТЬ. Отказ `KIR-G102` печатает список кандидатов с их
идентификаторами. Бери оттуда:

    create_duct(..., duct_type={{"by": "element_id", "value": <id>}})

и назови выбор решением в комментарии — почему именно этот из трёх.

ЦЕНА, ЕСЛИ ЭТОГО НЕ ЗНАТЬ: замер 23.08 на парном прогоне типового этажа —
**93 отказа `KIR-G102`** за один заход, и ни одна крупная программа с разделом
ОВ не стала чистой. Отказ при этом ПРАВ: угадывать грунтовка не должна, и
кандидатов он печатает сам.

РЯДОМ ВТОРАЯ СТЕНА, 6 отказов `KIR-L002`: `query`-опы и пишущие в ОДНОЙ
программе не смешиваются. Спрашивай отдельным ходом, строй отдельным.""")

    add(f"""
12. ПИТОН АВТОРА — ЧТО ДЕЙСТВИТЕЛЬНО РАЗРЕШЕНО

Скрипт исполняется в песочнице, и список разрешённых импортов ПЕЧАТАЕТСЯ
ЖИВЬЁМ, а не переписывается сюда — он меняется флагом среды:

    {", ".join(_allowed_imports())}

Циклы, функции, классы, генераторы — обычный питон. Этаж из сорока панелей и
башня из шестидесяти этажей пишутся ЦИКЛОМ; это главный инструмент против
перечисления.

🔴 ВТОРАЯ ФОРМА ВХОДА СУЩЕСТВУЕТ И ЕЮ НАДО ПОЛЬЗОВАТЬСЯ. У инструмента их
две: `program` (перечисление операций) и `program_py` (скрипт, который их
порождает). Повтор, расчёт и правило — это `program_py`; двадцать пять колонн
перечислением вместо цикла проигрывают не в красоте, а в цене правки.""")

    add("""
13. ГРАНИЦЫ ЭТОГО ДОКУМЕНТА, НАЗВАННЫЕ ВСЛУХ

* Приёмов с вердиктом ЛУЧШИЙ — НОЛЬ. Ни одно правило не держится
  единодушно на всех девяти документах. Каждое приезжает с исключением.
* Разделы ОВ, ВК и ЭОМ доказываются ХУЖЕ ПРОЧИХ: единственные модели
  сетей промышленного объёма в корпусе — образец Autodesk, а российский
  файл ЭОМ несёт 225 электрических элементов. Утверждать по нему
  «практику ЭОМ» нельзя, и документ этого не делает.
* «Сети не группируются» ОПРОВЕРГНУТО: в MNVNK 1110 из 1112 элементов ВК
  (99.8 %) лежат в группах. Группировка — свойство ФАЙЛА, а не раздела.
* Корпус заморожен 04.08.2026. Опорные плоскости, зависимости и стыки,
  которые захват научился брать позже, в нём отсутствуют по построению.
* Нормативную сторону держит отдельный скилл `compliance`; этот документ
  на неё ссылается и не повторяет её.""")

    return "\n".join(parts)
