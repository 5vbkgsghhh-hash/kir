"""design_check.py — вердикт о пригодности ЗАМЫСЛА, без Revit.

ЧТО ЭТО. Программа KIR (или разбор чужой модели) -> `SpatialModel` -> движок правил
HAB (`kukai/modeling/checker`) -> «квартира без окна / нет второго выхода / потолок ниже
нормы». Между «есть программа» и «есть вердикт» не запускается Revit.

=====================================================================================
ЭТО НЕ СИМУЛЯТОР REVIT. ЭТО ГЕОМЕТРИЧЕСКОЕ ЧТЕНИЕ ПРОГРАММЫ.
=====================================================================================

Разница не философская, и держится она ровно на одном правиле: **читаются числа,
которые представление УЖЕ СОДЕРЖИТ**, и не выводится ни одно, которое появилось бы
только в результате поведения Revit. У стены — концы. У перекрытия — контур. У двери —
хозяин и отступ вдоль него. Всё, что Revit ДОБАВИЛ БЫ от себя, объявлено вне области
поимённо (`OUT_OF_SCOPE` ниже) и не моделируется даже приблизительно.

Почему это важнее, чем звучит: известны как минимум ПЯТЬ мест, где симулятор соврал бы
на первом же здании, и все пять — наши собственные замеры, а не опасения. Компонент,
который не берётся предсказывать Revit, не может с ним разойтись; компонент, который
берётся, расходится молча и ровно там, где это дороже всего.

=====================================================================================
ДВА ИСТОЧНИКА, И ОНИ НЕ РАВНОЦЕННЫ
=====================================================================================

`ModelSource.PARSE`   — `SpatialModel` собран из `L0Document` (разбор). Независимое
                        чтение: вердикт судит здание.
`ModelSource.PROGRAM` — `SpatialModel` собран из ОПОВ (то, что программа объявляет).
                        Это САМОПРОВЕРКА: проверяется заявленное. Вердикт по программе
                        не является свидетельством о здании, и `BuildWitness.source`
                        несёт это различие в самом артефакте, а не подразумевает его.

`compare()` сводит два вердикта об ОДНОМ здании и называет расхождения ПОИМЁННО. Это и
есть карта того, чего чтение программы не видит, — а не список того, что мы надеемся,
что оно видит.

=====================================================================================
ГРАНИЦЫ ПОМЕЩЕНИЙ — ПЛАНАРНЫМ РАЗБИЕНИЕМ
=====================================================================================

`create_room` даёт ТОЧКУ, и больше ничего. Полигон помещения на пути PROGRAM считается
планарным разбиением отрезков стен уровня (`shapely.ops.polygonize`), а комната — это
грань разбиения, содержащая точку. Грань, в которую попали ДВЕ точки, не отдаётся
никому: разбиение их не разделило, и назвать одну из них комнатой значило бы угадать.

Комната, для которой полигон не сложился, честно уходит в НЕИЗМЕРИМЫЕ. Это не ошибка и
не выдумка: у чекера для этого есть `measured_room_ratio` и `unmeasured_room_ids`, и
вердикт NOT_EVALUATED с названной причиной — правильный ответ, а не отказ отвечать.

ЗАМЕР 2026-08-03 (K2, 59 этажей, 2442 помещения) — метод не теряет ничего, что стены
дают, и не выдумывает того, чего они не дают:

    разбиение вернуло полигон                         933 помещения
    ограничены ТОЛЬКО стенами (независимо, по L0)     936 помещений
    ограничены ещё и разделителями/колоннами         1217 помещений
    вообще без ограничивающих элементов               289 помещений

То есть 38% — это не удача и не потолок метода, это РОВНО та доля здания, которую в
принципе замыкают ОДНИ ТОЛЬКО СТЕНЫ. Остальное держится на разделителях помещений и
колоннах.

ПРАВЛЕНО ВЕЧЕРОМ 03.08, И ЭТО БЫЛО НЕ УТОЧНЕНИЕ, А ПРОВОД. Здесь стояло: «разделителя
помещений в языке KIR НЕТ ВОВСЕ», и из этого следовало, что в программе комната
замыкается стенами или никак. Утверждение протухло в тот же день: `create_room_separator`
написан и стоит в реестре (`spec.OPS`, замер мой: параметры `path` + `level`). До этой
правки разбиение всё равно строилось по одним `create_wall`, то есть язык уже умел
объявлять границу, а вердикт её не читал — и комната, открытая в коридор (четвёртой
стены у неё нет и быть не должно), не замыкалась ВООБЩЕ. Теперь отрезки разделителя
идут в разбиение наравне со стенами, но НЕ идут в `SpatialModel.walls`: правила о
стенах читают стены, и разделитель среди них был бы стеной нулевой толщины.

Путь ИЗ РАЗБОРА (`spatial_model_from_l0`) разделителей по-прежнему не читает: там их
надо поднимать из L0-категории, а это территория декомпилятора.

`PARTITION_CLOSE_TOL_MM` — единственный допуск в этом месте, и он назван. Осевые линии
стен в Revit сходятся не всегда точно; замер на K2: без допуска 11.3% помещений, при
100 мм — 37.8%, при 150 мм — 38.2% и уже 112 помещений теряются на общих гранях.
100 мм — колено кривой, а не круглое число.

=====================================================================================
ПРОФИЛЬ СТАДИИ
=====================================================================================

`HAB011` (геометрия лестницы) объявлен `mandatory` всегда, когда лестница есть. Ни один
разбор и ни одна программа не несут числа подступенков и глубины проступи — их нет в
замороженном L0 1.0 и нет в `create_stairs`. Без профиля ЛЮБОЕ здание с лестницей
читалось бы NOT_EVALUATED навсегда, а вердикт, который всегда один и тот же, — не
вердикт.

`DESIGN_STAGE` — профиль стадии замысла: те же правила, другой обязательный набор плюс
поимённо снятые. Он НАЗВАН в отчёте (`CoverageInfo.profile_name`) и в тексте вердикта:
«проверка стадии замысла: применимо N правил из M». Механизм — `Thresholds.profile`,
шов, который у чекера уже был.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

from kukai.modeling.checker.classify import classify_room
from kukai.modeling.checker.engine import run as run_checker
from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.report import format_text as format_check_report
from kukai.modeling.checker.spatial_model import (
    CheckReport,
    Door,
    Level,
    Room,
    RoomFunction,
    SpatialModel,
    Stair,
    Verdict,
    Wall,
    Window,
)
from kukai.modeling.checker.thresholds import StageProfile, Thresholds

_MM2_PER_M2 = 1_000_000.0


# ---------------------------------------------------------------------------------
# 1. ЧТО ОБЪЯВЛЕНО ВНЕ ОБЛАСТИ — поимённо, с замером, а не общей оговоркой
# ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class OutOfScope:
    """Одно поведение Revit, которое здесь НЕ моделируется — и почему."""

    name: str
    behaviour: str
    measured: str


#: Пять мест, где симулятор соврал бы сразу. Каждое — наш собственный замер. Список
#: печатается в вердикте: читатель обязан видеть границу до того, как поверит числу.
OUT_OF_SCOPE: tuple[OutOfScope, ...] = (
    OutOfScope(
        name="автосоединение стен",
        behaviour="Revit растягивает концы соединяемых стен на полтолщины партнёра; "
                  "длина и площадь помещения меняются ПОСЛЕ записи",
        measured="замер 21.07: +-100/125/150 мм на трёх типах стен",
    ),
    OutOfScope(
        name="опорный уровень балки",
        behaviour="`create_beam` берёт опорный уровень от ОТМЕТКИ КРИВОЙ, а не от "
                  "аргумента `level`",
        measured="замер 27.07",
    ),
    OutOfScope(
        name="высота стены при верхней привязке",
        behaviour="`WALL_USER_HEIGHT_PARAM` перестаёт быть истиной, когда стена "
                  "привязана к верхнему уровню; истина — пара top_level/top_offset",
        measured="замер 29.07; здесь высота считается по паре, а параметр берётся "
                 "только при отсутствии верхней привязки",
    ),
    OutOfScope(
        name="панель витража со стеновым типом",
        behaviour="`set_curtain_panel` со стеновым типом строит СТЕНУ вместо панели",
        measured="замер 28.07",
    ),
    OutOfScope(
        name="Railing.Create",
        behaviour="`Railing.Create(host)` возвращает КОЛЛЕКЦИЮ, а не один элемент",
        measured="замер 28.07",
    ),
)


# ---------------------------------------------------------------------------------
# 2. ПРОФИЛЬ СТАДИИ ЗАМЫСЛА
# ---------------------------------------------------------------------------------

#: Снятые правила: каждое снято потому, что стадия НЕ ВЫРАЖАЕТ его входов, и причина
#: названа входом, а не настроением. Снятое правило не выполняется вовсе — иначе его
#: находка была бы находкой о ПРЕДСТАВЛЕНИИ, неотличимой от находки о здании.
_DESIGN_SUSPENDED: dict[str, str] = {
    "HAB031": (
        "отношение остекления 1:8 требует ПЛОЩАДИ проёма. Программа задаёт окно типом "
        "(`create_window.symbol`), габарит живёт в семействе, и в снимке заземления "
        "пул `window_symbols` несёт `params: null` (замер 03.08) — сравнивать нечего"
    ),
    "HAB050": (
        "вертикальная неразрывность несущих требует признака «несущая» у стены. "
        "`create_wall` такого параметра не имеет (`spec.OPS`, замер 03.08), а L0 1.0 "
        "не несёт `WALL_STRUCTURAL_SIGNIFICANT` — на этой стадии судить нечем"
    ),
}

#: Обязательность: правило ВЫПОЛНЯЕТСЯ и говорит своё честное «проверить нечем», но
#: вето на вердикт не имеет — иначе вердикт был бы предрешён представлением.
_DESIGN_MANDATORY: dict[str, bool] = {
    "HAB011": False,
}

#: Названное умолчание — ОДНО, и оно закрыто инвариантом `StageProfile`: пока HAB031
#: снят, номинал не может дойти ни до одного сравнения с допуском, он отвечает
#: исключительно на вопрос «проём вообще есть?». Число выбрано как заведомо небольшое
#: одностворчатое окно; его величина ни на что не влияет, влияет только знак.
_DESIGN_NOMINAL_OPENING_M2 = 1.0

#: Правила, стоящие на ВЫВОДЕ КВАРТИРЫ (`graph.derive_apartments`). Снимаются ВСЕГДА,
#: и это не осторожность, а следствие замера.
_APARTMENT_ORACLE_RULES = ("HAB002", "HAB003", "HAB004", "HAB042")
_APARTMENT_ORACLE_REASON = (
    "правило стоит на выводе КВАРТИРЫ, а тот — на классификации имён помещений. "
    "Точность этого оракула ИЗМЕРЕНА 03.08 и разгромна: по составу жилища 0% "
    "(415 «квартир» из 469 — одна комната, ни в одной нет кухни), `core` не "
    "произведён ни разу за 52 дерева, precision mop/core 15.29%. Правило на оракуле "
    "с измеренной нулевой точностью обязано молчать, пока точность не измерена заново"
)

#: Предусловия: что должна была НАЙТИ деривация, чтобы правилу было о чём говорить.
#: Замер 03.08: без этой строки HAB010 обвинял 4 занятых уровня детсада и 8 уровней
#: snowdon в том, что они не спускаются к земле, которой проверка не нашла вовсе.
_DESIGN_PRECONDITIONS: dict[str, list[str]] = {
    "HAB001": ["building_entrance_known", "stair_landings_complete"],
    "HAB010": ["ground_level_known", "stair_landings_complete"],
    "HAB003": ["ground_level_known", "stair_landings_complete", "apartments_derived"],
}

#: Фильтры субъектов: правило говорит только о тех, у кого есть его вход.
_DESIGN_SUBJECT_INPUTS: dict[str, str] = {
    "HAB001": "room_polygon",
    "HAB020": "room_polygon",
    "HAB021": "room_polygon",
    "HAB030": "room_polygon",
    "HAB040": "room_polygon",
    "HAB022": "room_height",
    "HAB041": "door_adjacency",
}


def design_stage_profile(witness: BuildWitness) -> StageProfile:
    """Профиль стадии для КОНКРЕТНОГО представления этого здания.

    Профиль не универсален и не может быть универсальным: «входа нет» — утверждение о
    том, что удалось прочитать, а не о стадии вообще. Поэтому базовые снятия (площадь
    проёма, признак несущей, оракул квартиры) стоят всегда, а два — витражное
    остекление и отсутствие распознанных лестничных клеток — включаются ЗАМЕРОМ этого
    свидетеля и печатают свои числа в причине.

    Это НЕ флаг и НЕ подкрутка порога: снятое правило говорит в покрытии, ЧЕГО ему не
    хватило, а числовые допуски `Thresholds` остаются нетронутыми.
    """
    suspended = dict(_DESIGN_SUSPENDED)
    for rule_id in _APARTMENT_ORACLE_RULES:
        suspended[rule_id] = _APARTMENT_ORACLE_REASON

    windows = witness.counts.get("windows", 0)
    if witness.curtain_panels > windows:
        # Остекление выражено витражом, а `SpatialModel` витража не знает вовсе:
        # окон-элементов у здания просто нет, и «нет окна» было бы утверждением о
        # приёме моделирования, а не о комнате.
        suspended["HAB030"] = (
            f"остекление ВИТРАЖНОЕ: заполнений витража {witness.curtain_panels}, "
            f"окон-элементов {windows}. У `SpatialModel` понятия «витражное "
            f"остекление» нет, признака «стекло» у панели тоже нет (только имя типа) "
            f"— наличие естественного света проверить нечем")

    stairs = witness.counts.get("stairs", witness.inputs.get("stairs", 0))
    if not stairs:
        # Д-4, ЗАМЕР 03.08. При НУЛЕ лестниц HAB011 печатал свою захардкоженную
        # строку из `RULE_SPECS_V2`: «stairs present but none has measured
        # geometry». Она утверждает НАЛИЧИЕ ТОГО, ЧЕГО НЕТ, и утверждает уверенно
        # — модель читает её как «лестницы есть, но кривые» и идёт чинить
        # геометрию, которой не существует.
        #
        # Чинится здесь, а не в `engine.py`: там строка — поле спецификации
        # правила, и вычислять её по модели значило бы завести в движке второй
        # источник истины о предмете. Профиль стадии для этого и заведён:
        # правило, у которого НЕТ ПРЕДМЕТА, не выполняется вовсе и говорит в
        # покрытии, чего ему не хватило.
        suspended["HAB011"] = (
            "лестниц в представлении НЕТ ВОВСЕ: `create_stairs` не вызван ни "
            "разу (и ни одна лестница не поднялась из разбора). Правилу о "
            "геометрии лестницы не о чем высказываться — ни «прошло», ни «не "
            "прошло», ни «геометрия не измерена»")
    if stairs and witness.rooms_stair == 0 and witness.occupied_levels > 1:
        # Вертикальные рёбра графа строятся ТОЛЬКО через помещение с функцией
        # ЛЕСТНИЦА (`graph.build_graph` -> `_landing_room_on_level`). Ноль таких
        # помещений при живых лестницах означает, что граф РАЗВАЛЕН по этажам, и
        # всё, что читает связность между уровнями, обнаружит собственную слепоту.
        reason = (
            f"вертикальная связность графа строится только через помещение с функцией "
            f"ЛЕСТНИЦА; лестниц в модели {stairs}, занятых уровней "
            f"{witness.occupied_levels}, а помещений, распознанных как лестничная "
            f"клетка, — НОЛЬ (лексикон `classify.py` не знает принятых в этом проекте "
            f"имён). Граф развален по этажам, и «этаж висит» / «комната недостижима» "
            f"здесь — свойство словаря, а не здания")
        suspended["HAB001"] = reason
        suspended["HAB010"] = reason

    subject_inputs = {rule_id: name
                      for rule_id, name in _DESIGN_SUBJECT_INPUTS.items()
                      if rule_id not in suspended}
    preconditions = {rule_id: names
                     for rule_id, names in _DESIGN_PRECONDITIONS.items()
                     if rule_id not in suspended}
    return StageProfile(
        name="стадия замысла (KIR design intent)",
        note=(
            "Проверяется ЗАМЫСЕЛ. Правило, у которого нет входа, НЕ СРАБАТЫВАЕТ и "
            "говорит об этом в покрытии: снятое — целиком, отфильтрованное — по тем "
            "субъектам, у которых входа нет."
        ),
        suspended=suspended,
        mandatory=_DESIGN_MANDATORY,
        subject_inputs=subject_inputs,
        preconditions=preconditions,
        nominal_opening_area_m2=_DESIGN_NOMINAL_OPENING_M2,
    )


#: Базовый профиль — то, что снято при ЛЮБОМ представлении. Живые прогоны получают его
#: расширение из `design_stage_profile(witness)`; этот объект остаётся точкой отсчёта
#: и тем, что читают тесты про «профиль ничего не трогает сверх названного».
DESIGN_STAGE = StageProfile(
    name="стадия замысла (KIR design intent)",
    note=(
        "Проверяется ЗАМЫСЕЛ: связность, выходы, площади, высоты, наличие окна. "
        "Всё, что становится известно только после выбора семейств и узлов, снято "
        "поимённо."
    ),
    suspended={**_DESIGN_SUSPENDED,
               **{rule: _APARTMENT_ORACLE_REASON
                  for rule in _APARTMENT_ORACLE_RULES}},
    mandatory=_DESIGN_MANDATORY,
    subject_inputs={rule_id: name
                    for rule_id, name in _DESIGN_SUBJECT_INPUTS.items()
                    if rule_id not in (*_APARTMENT_ORACLE_RULES,
                                       *_DESIGN_SUSPENDED)},
    preconditions={rule_id: names
                   for rule_id, names in _DESIGN_PRECONDITIONS.items()
                   if rule_id not in (*_APARTMENT_ORACLE_RULES,
                                      *_DESIGN_SUSPENDED)},
    nominal_opening_area_m2=_DESIGN_NOMINAL_OPENING_M2,
)

#: Готовый объект для `run_checker(model, thr)`. Числовые допуски НЕ трогаются: профиль
#: меняет состав правил и охват субъектов, но не строгость ни одного из них.
DESIGN_STAGE_THRESHOLDS = Thresholds(profile=DESIGN_STAGE)


# ---------------------------------------------------------------------------------
# 3. ДОПУСКИ ЧТЕНИЯ — все в одном месте, каждый с замером
# ---------------------------------------------------------------------------------

#: На сколько продлевается каждый отрезок стены с обоих концов перед склейкой сети
#: (мм). Замер K2: 0 -> 11.3% помещений, 100 -> 37.8%, 150 -> 38.2% (и 112 помещений
#: уходят на общие грани), 400 -> 38.7% (335 на общих гранях). Колено — 100.
PARTITION_CLOSE_TOL_MM = 100.0

#: Насколько близко проём должен лежать к границе помещения/оболочки, чтобы считаться
#: его проёмом. Совпадает с `Thresholds.derive_join_tol_mm` намеренно: у чекера уже
#: есть этот допуск, и два разных числа для одного вопроса — способ разойтись молча.
OPENING_JOIN_TOL_MM = 300.0

#: Доля периметра, которая должна согласиться на одной высоте, чтобы высота помещения
#: считалась известной. Замер K2: 2126 помещений из 2152 согласны при 0.5.
HEIGHT_AGREEMENT_RATIO = 0.5

#: Округление высот стен перед голосованием (мм).
HEIGHT_BUCKET_MM = 10.0

#: Насколько ниже следующего уровня вправе кончиться ограждение, чтобы всё ещё
#: считаться доходящим до перекрытия (мм). Замер K2: у 11 863 стен из 15 255 верх
#: задан ПРИВЯЗКОЙ и приходится ровно на отметку уровня; 500 мм покрывают
#: отрицательный верхний отступ и толщину плиты, но не покрывают балюстраду 1530 мм
#: при шаге этажа 3100.
ENCLOSURE_REACH_TOL_MM = 500.0


# ---------------------------------------------------------------------------------
# 4. СВИДЕТЕЛЬ СБОРКИ
# ---------------------------------------------------------------------------------

class ModelSource(str, Enum):
    """Откуда взялся `SpatialModel`. Разница обязана быть видна в артефакте."""

    PARSE = "parse"       # из L0Document — НЕЗАВИСИМОЕ чтение
    PROGRAM = "program"   # из опов — САМОПРОВЕРКА (проверяется заявленное)

    @property
    def evidence(self) -> str:
        if self is ModelSource.PARSE:
            return ("НЕЗАВИСИМОЕ ЧТЕНИЕ: модель собрана из разбора (L0), вердикт "
                    "судит здание")
        return ("САМОПРОВЕРКА: модель собрана из ОПОВ ПРОГРАММЫ, вердикт судит "
                "ЗАЯВЛЕННОЕ, а не построенное")


@dataclass(frozen=True)
class BuildNote:
    """Один факт о сборке: что не удалось прочитать и почему."""

    code: str
    detail: str
    count: int = 1


@dataclass
class BuildWitness:
    """Что именно собрали, чего не собрали и по какой названной причине."""

    source: ModelSource
    building_id: str
    doc_name: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    rooms_total: int = 0
    rooms_measured: int = 0
    unmeasured_room_ids: list[str] = field(default_factory=list)
    unmeasured_reasons: Counter = field(default_factory=Counter)
    partition_faces: int = 0
    #: помещения, чью грань разбиения заняли несколько точек — отданы никому
    shared_face_room_ids: list[str] = field(default_factory=list)
    rooms_with_height: int = 0
    height_source: str = ""
    #: измерены ли габариты проёмов; False -> использован названный номинал профиля
    opening_size_measured: bool = False
    nominal_opening_area_m2: float | None = None
    #: сколько элементов КАЖДОГО рода несут измеренный вход правил — именно эти
    #: числа объясняют расхождения ворот, поэтому они снимаются, а не описываются
    inputs: dict[str, int] = field(default_factory=dict)
    #: категория L0 -> типизированные причины, по которым элементы НЕ стали опами
    #: (только для источника PROGRAM: у разбора атомов не бывает)
    lift_atoms: dict[str, Counter] = field(default_factory=dict)
    #: помещений, чьё ИМЯ распознано как лестничная клетка. Ноль при живых лестницах
    #: означает, что вертикальные рёбра графа не построятся ни при каких дверях
    rooms_stair: int = 0
    #: уровней, на которых есть хоть одно помещение
    occupied_levels: int = 0
    #: витражных заполнений в представлении: не окна (признака «стекло» нет), но
    #: и не ничто — без этого числа ложное «нет окна» на витражном фасаде нечем
    #: объяснить, а объяснение без числа — интонация
    curtain_panels: int = 0
    #: род элемента -> сколько ИМЕННО СБОРЩИК не смог положить в модель, и почему.
    #: Отдельно от `lift_atoms`: «оп не поднялся» и «оп поднялся, а сборщику не
    #: хватило» — разные адреса починки, и складывать их значит потерять адрес.
    dropped: dict[str, Counter] = field(default_factory=dict)
    notes: list[BuildNote] = field(default_factory=list)

    def drop(self, population: str, reason: str, count: int = 1) -> None:
        self.dropped.setdefault(population, Counter())[reason] += count

    def note(self, code: str, detail: str, count: int = 1) -> None:
        for index, existing in enumerate(self.notes):
            if existing.code == code and existing.detail == detail:
                self.notes[index] = BuildNote(code, detail, existing.count + count)
                return
        self.notes.append(BuildNote(code, detail, count))

    @property
    def measured_ratio(self) -> float:
        return self.rooms_measured / self.rooms_total if self.rooms_total else 0.0


# ---------------------------------------------------------------------------------
# 5. ГЕОМЕТРИЯ — планарное разбиение
# ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class _WallSeg:
    """Отрезок стены, каким его объявляет представление: концы, уровень, высота."""

    wall_id: str
    level_id: str
    p0: tuple[float, float]
    p1: tuple[float, float]
    height_mm: float
    height_known: bool

    @property
    def length(self) -> float:
        return math.dist(self.p0, self.p1)


def _extended(seg: _WallSeg, tol: float) -> LineString | None:
    dx, dy = seg.p1[0] - seg.p0[0], seg.p1[1] - seg.p0[1]
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return None
    ux, uy = dx / length, dy / length
    return LineString([
        (seg.p0[0] - ux * tol, seg.p0[1] - uy * tol),
        (seg.p1[0] + ux * tol, seg.p1[1] + uy * tol),
    ])


@dataclass(frozen=True)
class _Partition:
    """Планарное разбиение одного уровня: грани + исходные отрезки для их атрибуции."""

    faces: tuple[Polygon, ...]
    segs: tuple[_WallSeg, ...]
    _face_tree: Any = None
    _seg_tree: Any = None

    @classmethod
    def build(cls, segs: Sequence[_WallSeg], tol: float) -> "_Partition":
        lines = [ln for ln in (_extended(s, tol) for s in segs) if ln is not None]
        if not lines:
            return cls(faces=(), segs=tuple(segs))
        faces = tuple(polygonize(unary_union(lines)))
        return cls(
            faces=faces,
            segs=tuple(segs),
            _face_tree=STRtree(list(faces)) if faces else None,
            _seg_tree=(STRtree([LineString([s.p0, s.p1]) for s in segs])
                       if segs else None),
        )

    def face_containing(self, point: Point) -> int | None:
        if self._face_tree is None:
            return None
        for index in self._face_tree.query(point):
            if self.faces[index].contains(point):
                return int(index)
        return None

    def bounding_segments(self, face: Polygon, tol: float) -> list[_WallSeg]:
        """Отрезки, лежащие НА границе грани — те самые стены, что её замкнули."""
        if self._seg_tree is None:
            return []
        ring = LineString(face.exterior.coords).buffer(tol)
        out: list[_WallSeg] = []
        for index in self._seg_tree.query(ring):
            seg = self.segs[int(index)]
            piece = LineString([seg.p0, seg.p1]).intersection(ring)
            if getattr(piece, "length", 0.0) > tol:
                out.append(seg)
        return out


def _height_from_enclosure(segs: Iterable[_WallSeg], *,
                           base_z: float, next_level_z: float | None) -> float | None:
    """Высота помещения по стенам, которые его замкнули, или None.

    ДВА условия, и второе появилось от находки, а не от осторожности.

    1. Длинновзвешенное голосование: высота известна, только если на одной отметке
       сходится не меньше `HEIGHT_AGREEMENT_RATIO` периметра. Парапет в 5% периметра
       не объявляет комнату полуметровой, а разнобой честно остаётся неизвестностью.
    2. ОГРАЖДЕНИЕ — НЕ ПОТОЛОК. Стена определяет высоту помещения, только если она
       ДОХОДИТ ДО СЛЕДУЮЩЕГО УРОВНЯ. Замер 03.08 (K2): лестничный холл «ЛК 2.1 1»
       замкнут на 100% периметра стенами высотой 1530 мм — это балюстрада вокруг
       проёма лестницы, а не потолок; собственный размах помещения 3830 мм. Первая
       редакция принимала 1530 за высоту помещения и выдавала BLOCKING «потолок ниже
       2200» — обвинение, порождённое допущением сборщика, а не зданием.
       Уровня выше нет ⇒ проверить нечем ⇒ высота НЕИЗВЕСТНА.

    ЧТО ЭТО НЕ ЕСТЬ ДАЖЕ ПОСЛЕ ДВУХ УСЛОВИЙ: высота СТЕНЫ от основания до верха, а не
    чистая высота до потолка. Толщину пола и потолка программа не выражает, и разница
    — в НЕБЕЗОПАСНУЮ сторону (замер K2: стены 3100 мм против 3000 мм у прочтённого
    помещения).
    """
    votes: dict[float, float] = defaultdict(float)
    total = 0.0
    for seg in segs:
        if not seg.height_known or seg.height_mm <= 0.0:
            continue
        bucket = round(seg.height_mm / HEIGHT_BUCKET_MM) * HEIGHT_BUCKET_MM
        votes[bucket] += seg.length
        total += seg.length
    if total <= 0.0 or not votes:
        return None
    best, best_len = max(votes.items(), key=lambda item: item[1])
    if best_len / total < HEIGHT_AGREEMENT_RATIO:
        return None
    if next_level_z is None:
        return None
    if base_z + best < next_level_z - ENCLOSURE_REACH_TOL_MM:
        return None
    return float(best)


def _ring(poly: Polygon) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in poly.exterior.coords]


# ---------------------------------------------------------------------------------
# 6. СБОРКА ИЗ РАЗБОРА (L0Document) — путь А
# ---------------------------------------------------------------------------------

def _levels_from_l0(document: Any) -> tuple[list[Level], dict[str, float]]:
    ordered = sorted(document.levels, key=lambda lvl: lvl.elevation_mm)
    levels = [
        Level(id=lvl.id, name=lvl.name, elevation_mm=float(lvl.elevation_mm),
              index=index)
        for index, lvl in enumerate(ordered)
    ]
    return levels, {lvl.id: float(lvl.elevation_mm) for lvl in ordered}


def _wall_span(element: Any, elevations: Mapping[str, float]) -> tuple[float, float] | None:
    """Низ и верх стены — ПО ПАРЕ top_level/top_offset, когда она есть.

    Именно здесь живёт замер 29.07: при верхней привязке `WALL_USER_HEIGHT_PARAM`
    перестаёт быть истиной, и читать его первым значило бы предсказывать Revit.
    """
    level_id = getattr(element, "level_id", None)
    if level_id not in elevations:
        return None
    params = getattr(element, "params", None) or {}
    base = elevations[level_id] + float(params.get("WALL_BASE_OFFSET") or 0.0)
    top_level = params.get("WALL_HEIGHT_TYPE")
    if isinstance(top_level, str) and top_level in elevations:
        top = elevations[top_level] + float(params.get("WALL_TOP_OFFSET") or 0.0)
        return base, top
    height = params.get("WALL_USER_HEIGHT_PARAM")
    if height is None:
        return base, base
    return base, base + float(height)


def spatial_model_from_l0(
    document: Any,
    *,
    building_id: str | None = None,
    profile: StageProfile | None = DESIGN_STAGE,
) -> tuple[SpatialModel, BuildWitness]:
    """`SpatialModel` из разбора. Независимое чтение: вердикт судит здание.

    Границы помещений берутся ТАКИМИ, КАК ИХ ВЕРНУЛ REVIT (`RoomInfo.boundary_mm`) —
    разбор их уже содержит, и пересчитывать их разбиением значило бы выбросить
    прочитанное ради худшей копии. Разница с путём PROGRAM в этом месте и есть
    предмет ворот.
    """
    building = building_id or document.change_stamp
    witness = BuildWitness(source=ModelSource.PARSE, building_id=building,
                           doc_name=document.doc_name)
    levels, elevations = _levels_from_l0(document)
    known_levels = {lvl.id for lvl in levels}

    elements = getattr(document, "elements", ()) or ()
    by_category: dict[str, list[Any]] = defaultdict(list)
    for element in elements:
        by_category[element.category].append(element)
    by_id = {element.element_id: element for element in elements}

    # --- стены ---------------------------------------------------------------
    walls: list[Wall] = []
    wall_span: dict[str, tuple[float, float]] = {}
    for element in by_category.get("OST_Walls", ()):
        if element.p0_mm is None or element.p1_mm is None:
            witness.note("wall_no_curve",
                         "стена без LocationCurve в L0 — в план не попадает")
            witness.drop("walls", "нет LocationCurve в L0")
            continue
        if element.level_id not in known_levels:
            witness.note("wall_no_level", "стена ссылается на уровень вне документа")
            witness.drop("walls", "уровень вне документа")
            continue
        span = _wall_span(element, elevations)
        height = abs(span[1] - span[0]) if span else 0.0
        if span:
            wall_span[element.element_id] = span
        walls.append(Wall(
            id=element.element_id,
            level_id=element.level_id,
            curve=((float(element.p0_mm[0]), float(element.p0_mm[1])),
                   (float(element.p1_mm[0]), float(element.p1_mm[1]))),
            height_mm=max(height, 0.0),
            # Признака «несущая» в L0 1.0 нет — объявляем False и снимаем HAB050
            # профилем, а не тихо считаем все стены ненесущими за факт.
            is_structural=False,
        ))
    walls_by_id = {wall.id: wall for wall in walls}

    # --- помещения: полигон = то, что вернул Revit ----------------------------
    room_elements = {element.element_id: element
                     for element in by_category.get("OST_Rooms", ())}
    rooms: list[Room] = []
    room_polys: dict[str, Polygon] = {}
    rooms_by_level: dict[str, list[str]] = defaultdict(list)
    heights_known = 0
    for info in document.rooms:
        if info.level_id not in known_levels:
            witness.note("room_no_level", "помещение ссылается на уровень вне документа")
            witness.drop("rooms", "уровень вне документа")
            continue
        boundary = [(float(x), float(y)) for x, y in (info.boundary_mm or ())]
        poly = _polygon_or_none(boundary)
        if poly is None:
            witness.unmeasured_room_ids.append(info.id)
            witness.unmeasured_reasons["ring_degenerate"] += 1
        else:
            room_polys[info.id] = poly
        # Высота — вертикальный размах САМОГО помещения, как его вернул коллектор.
        height: float | None = None
        element = room_elements.get(info.id)
        if element is not None and element.bbox_min_mm and element.bbox_max_mm:
            span = float(element.bbox_max_mm[2]) - float(element.bbox_min_mm[2])
            if span > 0.0:
                height = span
                heights_known += 1
        rooms.append(Room(
            id=info.id,
            name=info.name,
            level_id=info.level_id,
            function=classify_room(info.name),
            area_m2=float(info.area_m2 or 0.0),
            height_mm=height,
            boundary=boundary,
            # has_window НЕ объявляется: Revit его не объявляет, объявили бы мы —
            # и HAB060 ловил бы наше собственное утверждение, а не модель.
            has_window=False,
            height_source="room_bbox" if height is not None else None,
        ))
        rooms_by_level[info.level_id].append(info.id)
    witness.rooms_total = len(rooms)
    witness.rooms_measured = len(room_polys)
    witness.rooms_with_height = heights_known
    witness.height_source = "вертикальный размах помещения (L0 bbox)"

    doors, windows = _openings(
        door_elements=by_category.get("OST_Doors", ()),
        window_elements=by_category.get("OST_Windows", ()),
        walls_by_id=walls_by_id,
        room_polys=room_polys,
        rooms_by_level=rooms_by_level,
        witness=witness,
        profile=profile,
        location_of=lambda e: _l0_point(e, witness),
        size_of=_size_from_instance_params,
        host_of=lambda e: e.host_id,
        id_of=lambda e: e.element_id,
        # Разбор объявляет уровень У САМОГО проёма; уровень хозяина остаётся
        # запасным. У программы такого поля нет вовсе — там только хозяин, и это
        # различие входов, а не разница трактовок.
        level_of=lambda e: e.level_id if e.level_id in known_levels else None,
    )

    stairs = _stairs_from_l0(by_category.get("OST_Stairs", ()), elevations, witness)

    # Витражное остекление СЧИТАЕТСЯ, но окном не объявляется: у панели витража нет
    # признака «стекло» — есть только имя типа, а решать по имени значит гадать.
    # Число нужно, чтобы оговорка про ложное «нет окна» несла цифру, а не интонацию.
    witness.curtain_panels = len(by_category.get("OST_CurtainWallPanels", ()))

    witness.counts = {
        "levels": len(levels), "rooms": len(rooms), "walls": len(walls),
        "doors": len(doors), "windows": len(windows), "stairs": len(stairs),
    }
    model = SpatialModel(building_id=building, levels=levels, rooms=rooms,
                         doors=doors, windows=windows, stairs=stairs, walls=walls)
    _fill_inputs(witness, model)
    return model, witness


def _l0_point(element: Any, witness: BuildWitness) -> tuple[float, float] | None:
    """Положение проёма из разбора: точка, а если её нет — ЦЕНТР ПРОЧИТАННОГО BBOX.

    Замер 03.08 (K2): все 49 окон башни сняты как `geom_kind: bbox_only` — точки у
    них нет вовсе. Без этого запасного хода путь разбора терял ВСЕ окна здания и
    сообщал «нет окна» о каждой жилой комнате, то есть терял ровно ту находку, ради
    которой затевался. Центр bbox — не догадка о Revit, а середина того самого
    ящика, который вернуло чтение; провенанс отмечается в свидетеле.
    """
    if element.p0_mm is not None:
        return float(element.p0_mm[0]), float(element.p0_mm[1])
    if element.bbox_min_mm is not None and element.bbox_max_mm is not None:
        witness.note("opening_from_bbox",
                     "положение проёма взято как центр bbox: точки в L0 нет "
                     "(geom_kind=bbox_only)")
        return ((float(element.bbox_min_mm[0]) + float(element.bbox_max_mm[0])) / 2.0,
                (float(element.bbox_min_mm[1]) + float(element.bbox_max_mm[1])) / 2.0)
    return None


def _size_from_instance_params(element: Any) -> tuple[float, float] | None:
    params = getattr(element, "params", None) or {}
    width = params.get("FAMILY_WIDTH_PARAM")
    height = params.get("FAMILY_HEIGHT_PARAM")
    if width is None or height is None:
        return None
    return float(width), float(height)


def _stairs_from_l0(elements: Iterable[Any], elevations: Mapping[str, float],
                    witness: BuildWitness) -> list[Stair]:
    """Лестницы из L0.

    `Element.Level` у лестницы пуст — коллектор кладёт None, а истина живёт в
    `STAIRS_BASE_LEVEL_PARAM`/`STAIRS_TOP_LEVEL_PARAM` (замер 03.08: из-за чтения
    `Element.Level` лестницы не доходили до семантической свёртки вовсе).
    """
    stairs: list[Stair] = []
    for element in elements:
        params = getattr(element, "params", None) or {}
        base = params.get("STAIRS_BASE_LEVEL_PARAM")
        top = params.get("STAIRS_TOP_LEVEL_PARAM")
        if not isinstance(base, str) or not isinstance(top, str):
            witness.note("stair_no_levels",
                         "у лестницы нет STAIRS_BASE/TOP_LEVEL_PARAM — пропущена")
            witness.drop("stairs", "нет STAIRS_BASE/TOP_LEVEL_PARAM")
            continue
        if base not in elevations or top not in elevations:
            witness.note("stair_level_absent",
                         "уровень лестницы отсутствует в документе — пропущена")
            witness.drop("stairs", "уровень лестницы вне документа")
            continue
        # ПЛАНА МАРША В L0 НЕТ, И BBOX ИМ НЕ ЯВЛЯЕТСЯ.
        #
        # Первая редакция клала сюда прямоугольник габаритной рамки. Рамка —
        # настоящее число чтения, но она не план марша: у повёрнутого или Г-образного
        # марша она описывает совсем другую фигуру, и HAB012 (неразрывность ядра)
        # начинал сравнивать не то, что называет. Замер 03.08 (K2, 89 лестниц):
        # 100 предупреждений «ядро разорвано» на башне, у которой ядро стоит на месте.
        # Пустой список означает «плана нет», и правило честно уходит в NOT_EVALUATED
        # вместо ста находок о нашей же подстановке.
        witness.note("stair_no_plan",
                     "плана марша в L0 нет (габаритная рамка им не является) — "
                     "HAB012 сравнивать нечего")
        stairs.append(Stair(
            id=element.element_id,
            base_level_id=base,
            top_level_id=top,
            base_z=elevations[base],
            top_z=elevations[top],
            # Ширина марша, число подступенков и глубина проступи в L0 1.0
            # отсутствуют. None — это «не измерено», а не 1200 мм из воздуха.
            run_width_mm=None,
            riser_count=None,
            tread_depth_mm=None,
            footprint=[],
            kind="element",
        ))
    return stairs


# ---------------------------------------------------------------------------------
# 7. СБОРКА ИЗ ПРОГРАММЫ (L1-опы) — путь Б
# ---------------------------------------------------------------------------------

def _ref_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        if value.get("by") == "name":
            return str(value.get("value"))
        if value.get("by") == "family_type":
            return str(value.get("type_name"))
    return None


def _ref_source_id(value: Any) -> str | None:
    if isinstance(value, Mapping) and "by" in value:
        got = value.get("_id")
        return str(got) if got else None
    return None


def _ref_node(value: Any) -> str | None:
    if isinstance(value, Mapping) and set(value) == {"ref"}:
        return str(value["ref"])
    return None


# ---------------------------------------------------------------------------------
# 7-БИС. ДВЕ ФОРМЫ ВХОДА — И ОТКАЗ, КОТОРЫЙ НАЗЫВАЕТ УВИДЕННУЮ
# ---------------------------------------------------------------------------------
#
# ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ РОД ОТКАЗА, А НЕ ПУСТАЯ МОДЕЛЬ. «Вход не той формы» и «в
# здании нет помещений» — РАЗНЫЕ утверждения, и второе врёт: оно говорит о здании
# то, чего не читало. Замер 03.08 на живом круге: 100 операций, 27 `create_room`,
# ответ «HAB000 — model has no rooms». Диагноз уводил модель добавлять помещения
# туда, где их уже двадцать семь, — то есть стоил раунд И портил программу.

#: Код отказа о форме входа вердикта. Отдельная буква намеренно: это не разбор
#: (`KIR-P*`) и не заземление (`KIR-G*`), а дверь ВЕРДИКТА.
PROGRAM_SHAPE = "KIR-V001"

#: Код отказа о КОНТРАКТЕ ПАЧКИ. Форма входа при нём верна — незаконно СОДЕРЖИМОЕ:
#: ссылка `{"by": "ref"}`, перешедшая границу программы. Ссылка живёт внутри
#: программы (её разрешает `KIR-L003` на плане), и между программами пачки её
#: разрешить нечем: вторая программа исполняется отдельной транзакцией, где id
#: первой уже не существует. Молча проигнорировать такую ссылку значило бы
#: судить не то здание, которое построится.
BUNDLE_CONTRACT = "KIR-V002"

#: Код отказа о НЕПОСТРОИМОСТИ. Форма входа верна, ссылки законны — а программу
#: КОМПИЛЯТОР НЕ ВОЗЬМЁТ. Замер 04.08, из-за которого код заведён: `check_ops`
#: судил пригодность программы, содержащей `create_stairs` рядом с соседями, и
#: печатал `ПРИГОДЕН`, тогда как `plan_program` ту же программу отвергал
#: `KIR-L002`. Модель получала ДВА зелёных света и стену: `preview()` рисовал,
#: `design_check()` благословлял, компилятор отказывал. Это ровно те «две
#: подписи у одного здания», против которых типизирован весь компилятор, — и
#: вердикт был одной из них.
#:
#: Третий код, а не расширение `KIR-V002`, по логике самого этого семейства:
#: «это не пачка», «пачка, но ссылка перешла границу» и «программа непостроима»
#: — ТРИ РАЗНЫЕ ПОЧИНКИ. Последнюю чинит автор программы, и чинит однозначно:
#: разбить на пачку и судить `check_bundle`.
#:
#: ЧЕГО ЭТА ДВЕРЬ НЕ ДЕЛАЕТ. Она не становится фронтендом компилятора и не
#: повторяет `plan_program`: тот отказывает и по причинам, к пригодности
#: отношения не имеющим (неизвестное поле, бюджет), и тащить их сюда значило бы
#: подменить вопрос «дом ли это» вопросом «компилируется ли». Проверяется ровно
#: тот закон ФОРМЫ, ради которого заведена пачка, — `spec.SOLO_OPS`.
PROGRAM_NOT_BUILDABLE = "KIR-V003"

_SHAPE_OPS = "ops"      # операции KIR: {"op": …, "id": …}, поля плоско
_SHAPE_L1 = "l1"        # узлы декомпилятора: {"kind": …, "op_name": …, "params": {…}}
_SHAPE_PROGRAM = "program"   # конверт программы: {"ops": [...]} — элемент ПАЧКИ

_SHAPE_RU = {
    _SHAPE_OPS: ('ОПЕРАЦИИ KIR — {"op": "create_wall", "id": …, поля плоско}; '
                 'ровно то, что отдаёт песочница (`SandboxResult.ops`)'),
    _SHAPE_L1: ('УЗЛЫ L1 декомпилятора — {"kind": "op", "op_name": …, '
                '"params": {…}, "source_element_id": …}'),
    _SHAPE_PROGRAM: ('ПРОГРАММА целиком — конверт {"ops": [...]}; '
                     'последовательность таких конвертов и есть ПАЧКА'),
}

#: Какая дверь принимает какую форму. Отказ обязан назвать не только увиденное,
#: но и место, куда надо было идти: отказ без адреса — это второй раунд.
_SHAPE_DOOR = {
    _SHAPE_OPS: "spatial_model_from_ops(...) / check_ops(...)",
    _SHAPE_L1: "spatial_model_from_program(...)",
    _SHAPE_PROGRAM: "check_bundle(...) / spatial_model_from_bundle(...)",
}

#: Приставка внутреннего идентификатора узла. Эти узлы НИКОГДА не покидают
#: `spatial_model_from_ops`: они живут ровно один вызов и не являются L1
#: декомпилятора (у того свой `stable_l1_id`). Приставка нужна лишь для того,
#: чтобы ссылка на узел (`{"ref": …}`) не совпала с идентификатором элемента.
_NODE_PREFIX = "kir::"


class VerdictInputError(ValueError):
    """Общий корень отказов ДВЕРИ ВЕРДИКТА: вход не годен, здание не читалось.

    Корень нужен ровно затем, чтобы у вызывающего была ОДНА точка перехвата на
    все отказы двери, а различала их БУКВА КОДА, а не класс. Иначе каждый новый
    род отказа этой двери тихо пролетал бы мимо старого `except` — и наружу
    вместо названной причины уходила бы трасса.
    """

    code = ""

    def __init__(self, message_ru: str, **detail: Any) -> None:
        super().__init__(message_ru)
        self.message_ru = message_ru
        self.detail = {k: v for k, v in detail.items() if v is not None}

    def render(self) -> str:
        return f"{self.code}: {self.message_ru}"


class ProgramShapeError(VerdictInputError):
    """Вход вердикта не той формы — сказанное ПРЯМО.

    Исключение, а не пустая модель, потому что пустая модель неотличима от
    честного «здание пустое», а разница между этими двумя ответами — это разница
    между «почини вызов» и «почини здание».
    """

    code = PROGRAM_SHAPE


class BundleContractError(VerdictInputError):
    """Форма входа ВЕРНА, а связь внутри пачки — незаконна.

    Отдельный код от `KIR-V001` намеренно: «это не пачка» и «это пачка, но
    ссылка в ней перешла границу программы» — РАЗНЫЕ починки. Первую чинит
    вызывающий, вторую — автор программы, и один код на двоих отправлял бы
    половину случаев не по адресу.
    """

    code = BUNDLE_CONTRACT


class ProgramNotBuildableError(VerdictInputError):
    """Форма верна, ссылки законны — а КОМПИЛЯТОР эту программу не возьмёт.

    Исключение, а не находка вердикта, и это различие несущее. Находка говорит
    «здание плохое» — её чинят, меняя здание. Здесь же здание может быть
    прекрасным: непостроима ПРОГРАММА как единица, и чинится это разбиением на
    пачку, а не проектированием. Смешать их значило бы отправить автора искать
    несуществующий изъян в замысле.
    """

    code = PROGRAM_NOT_BUILDABLE


def _unbuildable_solo(ops: Sequence[Any]) -> tuple[str, list[str]] | None:
    """Оп, владеющий собственной транзакцией, с соседями — или `None`.

    Источник истины один — `spec.SOLO_OPS`, тот же, по которому отказывают
    `plan_program` и `emit_program`. Свой список здесь стал бы четвёртым
    судьёй одного вопроса и разошёлся бы с остальными на первом же новом опе.
    """
    from kukai.ir import spec  # лениво: вердикт не тянет реестр ради импорта

    if len(ops) < 2:
        return None
    names = {o.get("op") for o in ops if isinstance(o, Mapping)}
    solo = sorted(n for n in names if n in spec.SOLO_OPS)
    if not solo:
        return None
    return solo[0], sorted(n for n in names if n and n not in spec.SOLO_OPS)


def _refuse_if_unbuildable(ops: Sequence[Any], *, where: str) -> None:
    found = _unbuildable_solo(ops)
    if found is None:
        return
    solo, neighbours = found
    raise ProgramNotBuildableError(
        f"{where}: `{solo}` обязан быть ЕДИНСТВЕННЫМ опом своей программы "
        f"(KIR-L002 — он владеет собственными транзакциями), а рядом с ним "
        f"здесь {len(ops) - 1} опов: {', '.join(neighbours[:6])}"
        + (" …" if len(neighbours) > 6 else "")
        + ". Компилятор такую программу НЕ ВОЗЬМЁТ, поэтому судить её "
          "пригодность значило бы выдать разрешение на непостроимое. "
          "СЛЕДУЮЩИЙ ХОД: разбей на ПАЧКУ — тело отдельно, "
          f"`{solo}` отдельной программой — и спроси "
          "`design_check([тело, лестница])`.")
    # ИМЯ ХОДА — ТО, ЧТО ЕСТЬ У МОДЕЛИ, А НЕ ТО, ЧТО ЕСТЬ У НАС. Первая
    # редакция отправляла в `check_bundle` — имя этой двери снаружи. Изнутри
    # песочницы его нет вовсе: `KIR-B006: NameError: name 'check_bundle' is
    # not defined` (замер 04.08). Отказ, называющий несуществующий ход, хуже
    # отказа без хода: он тратит ход модели на проверку нашей опечатки.
    # `course.design_check` пачку распознаёт сам (`_is_bundle`), поэтому
    # правильная форма изнутри — со списком программ.


def _shape_of(item: Any) -> str:
    """Что это за элемент — по КЛЮЧАМ, а не по надежде вызывающего.

    ПОРЯДОК ПРОВЕРОК — САМ ПО СЕБЕ УТВЕРЖДЕНИЕ, и до 04.08 он был неверным.
    `op` спрашивается ПЕРВЫМ, потому что это единственный ключ, который есть у
    каждой операции KIR и ни у одного узла L1 (у тех `kind`/`op_name`/`params`/
    `source_element_id`, ключа `op` нет ни у узла, ни у атома — `lift._op_node`
    / `lift._atom_node`). Обратный порядок ломался на плоском поле: у
    `query_count`/`query_list` СВОЙ параметр называется `kind`, и законная
    операция `{"op": "query_count", "id": …, "kind": "wall"}` объявлялась узлом
    L1 — `check_ops` отказывал KIR-V001 и посылал В ЧУЖУЮ ДВЕРЬ. Это ровно та
    ошибка, от которой предостерегает шапка этого раздела: отказ говорил о
    входе то, чего не читал, и уводил чинить не туда.
    """
    if not isinstance(item, Mapping):
        return ""
    if isinstance(item.get("op"), str):
        return _SHAPE_OPS
    # `kind` покрывает и `{"kind": "atom"}`: атомы — тоже L1, их сборщик считает.
    if "kind" in item or "op_name" in item:
        return _SHAPE_L1
    # Конверт программы. Спрашивается ПОСЛЕДНИМ: `ops` — самый слабый признак,
    # и уступать он обязан обоим предыдущим, а не наоборот.
    if isinstance(item.get("ops"), (list, tuple)):
        return _SHAPE_PROGRAM
    return ""


def _unwrap_program(program: Any) -> Sequence[Any]:
    """Голый список операций либо конверт `{"ops": [...]}` — обе формы законны.

    Песочница отдаёт список, конвейер компилятора — конверт. Требовать распаковки
    от вызывающего значило бы завести ТРЕТЬЮ форму там, где их и так две.
    """
    if isinstance(program, Mapping):
        if "ops" not in program:
            raise ProgramShapeError(
                f"это словарь без ключа `ops`: программа — это список операций "
                f"либо конверт {{'ops': [...]}}. Ключи, которые пришли: "
                f"{sorted(str(k) for k in program)[:12]}",
                keys=sorted(str(k) for k in program)[:12])
        program = program["ops"]
    if isinstance(program, (str, bytes)):
        raise ProgramShapeError(
            f"программа пришла как строка ({len(program)} символов), а нужен "
            f"СПИСОК операций. Строка — это не программа IR",
            got=type(program).__name__)
    if not isinstance(program, (list, tuple)):
        raise ProgramShapeError(
            f"программа пришла как {type(program).__name__}, а нужен список "
            f"операций", got=type(program).__name__)
    return program


def _require_shape(program: Any, want: str) -> list[Mapping[str, Any]]:
    """Список нужной формы либо отказ, называющий увиденную форму и её дверь."""
    items = _unwrap_program(program)
    if not items:
        raise ProgramShapeError(
            "программа пуста: ни одной операции. Пустая программа — это не "
            "«здание без помещений», это отсутствие входа", ops=0)
    for index, item in enumerate(items):
        got = _shape_of(item)
        if got == want:
            continue
        where = f"ops[{index}]"
        if got:
            raise ProgramShapeError(
                f"{where} — это {_SHAPE_RU[got]}, а эта дверь принимает "
                f"{_SHAPE_RU[want]}. Их принимает {_SHAPE_DOOR[got]}. "
                f"Это утверждение О ФОРМЕ ВХОДА, а не о здании: помещения, "
                f"стены и двери здесь ещё не читались вовсе",
                index=index, got=got, want=want)
        if isinstance(item, Mapping):
            raise ProgramShapeError(
                f"{where}: ни `op` (операция KIR), ни `kind`/`op_name` (узел L1) "
                f"— по ключам не видно, что это. Ключи: "
                f"{sorted(str(k) for k in item)[:12]}",
                index=index, keys=sorted(str(k) for k in item)[:12])
        raise ProgramShapeError(
            f"{where} — это {type(item).__name__}, а операция — это объект "
            f"с полем `op`", index=index, got=type(item).__name__)
    return list(items)


def _adapt_ref(value: Any, kinds: Mapping[str, str]) -> Any:
    """Ссылка KIR -> ссылка в форме, которую читает сборщик.

    Разбор идёт ПО РОДУ АДРЕСАТА, а не по имени поля, и это важно: сборщик
    разрешает уровень через `_ref_source_id` (нужен `_id`), а хозяина проёма —
    через `_ref_node` (нужен ОДИН ключ `ref`). Угадывание по имени поля
    (`host`/`target`) развалилось бы на первой же операции, у которой хозяин
    назван иначе.
    """
    if isinstance(value, Mapping):
        if value.get("by") == "ref":
            target = str(value.get("value"))
            kind = kinds.get(target)
            if kind == "create_level":
                # уровень: `resolve_level` -> `_ref_source_id` -> `_id`
                return {**value, "_id": target}
            if kind is not None:
                # всё остальное — ссылка на УЗЕЛ (хозяин проёма и т. п.)
                return {"ref": _NODE_PREFIX + target}
            # Адресат неизвестен: ссылка ведёт в никуда. Оставляем как есть —
            # она не разрешится ни одним из двух способов, и свидетель сборки
            # скажет об этом словами («уровень не разрешается по программе»).
            return dict(value)
        return {k: _adapt_ref(v, kinds) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_adapt_ref(v, kinds) for v in value]
    return value


def _ops_to_nodes(ops: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Операции KIR -> узлы, которые читает сборщик. ВНУТРЕННЕЕ преобразование.

    Ничего не выдумывает: `source_element_id` — это `id` самой операции, а не
    новый идентификатор, поэтому любая находка вердикта адресуется ТОЙ ЖЕ
    строкой, которую модель написала в скрипте.
    """
    kinds: dict[str, str] = {}
    ids: list[str] = []
    for index, op in enumerate(ops):
        raw = op.get("id")
        oid = str(raw) if raw not in (None, "") else f"#{index}"
        ids.append(oid)
        kinds[oid] = str(op.get("op"))
    nodes: list[dict[str, Any]] = []
    for index, op in enumerate(ops):
        oid = ids[index]
        params = {key: _adapt_ref(value, kinds)
                  for key, value in op.items() if key not in ("op", "id")}
        nodes.append({
            "kind": "op",
            "op_name": str(op["op"]),
            "_id": _NODE_PREFIX + oid,
            "params": params,
            "source_element_id": oid,
        })
    return nodes


def spatial_model_from_ops(
    program: Any,
    *,
    building_id: str,
    profile: StageProfile | None = DESIGN_STAGE,
    close_tol_mm: float = PARTITION_CLOSE_TOL_MM,
) -> tuple[SpatialModel, BuildWitness]:
    """`SpatialModel` из ОПЕРАЦИЙ KIR — наружная дверь вердикта.

    Принимает ровно то, что производит песочница (`SandboxResult.ops`) и что
    несёт поле `program` конвейера. Форма L1 остаётся внутренним делом
    декомпилятора: переходник живёт здесь и наружу не показывается.
    """
    ops = _require_shape(program, _SHAPE_OPS)
    # ЗАКОННОСТЬ ПРЕЖДЕ ПРИГОДНОСТИ. Дверь ОДНОЙ программы обязана отказать на
    # том, что компилятор не возьмёт: иначе `ПРИГОДЕН` выдаётся непостроимому,
    # и модель получает два зелёных света при одной стене (замер 04.08).
    # В пачке этот же набор опов ЗАКОНЕН — там закон проверяется по звеньям,
    # см. `spatial_model_from_bundle`.
    _refuse_if_unbuildable(ops, where="программа")
    return spatial_model_from_program(
        _ops_to_nodes(ops), building_id=building_id, profile=profile,
        close_tol_mm=close_tol_mm)


def check_ops(
    program: Any,
    *,
    building_id: str = "(программа KIR)",
    thresholds: Thresholds | None = None,
) -> DesignVerdict:
    """ОПЕРАЦИИ KIR -> вердикт, одним вызовом. Между ними не запускается Revit.

    Это САМОПРОВЕРКА (`ModelSource.PROGRAM`): судится ЗАЯВЛЕННОЕ программой, и
    `DesignVerdict.source` несёт это различие в самом артефакте.
    """
    model, witness = spatial_model_from_ops(program, building_id=building_id)
    return check_design(model, witness, thresholds=thresholds)


# ---------------------------------------------------------------------------------
# ПАЧКА ПРОГРАММ — ЕДИНИЦА ЗДАНИЯ
#
# ЗАЧЕМ ЭТА ДВЕРЬ ВООБЩЕ ЕСТЬ. Закон «крупное здание — ПАЧКА программ» в этом
# пакете уже был (`tool_doc.CONSTRAINTS`), и `KIR-L002` — его частный случай:
# `create_stairs` владеет собственными транзакциями (`StairsEditScope`), поэтому
# он ЕДИНСТВЕННЫЙ оп своей программы. А судил вердикт ОДНУ программу. Из двух
# верных правил складывалось третье, неверное: многоэтажное здание, выраженное
# одной программой, непригодно ПО ПОСТРОЕНИЮ — `HAB010` блокирует каждый занятый
# уровень без лестничной связи, `HAB001` разваливается следом, а лестницу в ту же
# программу положить нельзя. Замер 03-04.08 (4 прогона A/B, 2 модели, 20 ходов
# каждый): НИ ОДНОГО здания без блокирующих, у всех четырёх `лест 0`, три встали
# ровно на этой паре. Сильная модель нашла стену САМА и слепила лестницу из 12
# `create_floor` — вердикт честно прочитал `stairs 0` и заблокировал.
#
# Чинится здесь, а не в эмиттере: `KIR-L002` — факт Revit API, а не наша прихоть.
# Неверным был не запрет, а ЕДИНИЦА СУЖДЕНИЯ.
# ---------------------------------------------------------------------------------

#: Разделитель в квалифицированном идентификаторе операции пачки: `p1/wall3`.
_BUNDLE_SEP = "/"


def _bundle_oid(position: int, oid: str) -> str:
    """Идентификатор операции В МАСШТАБЕ ПАЧКИ: позиция программы + свой id.

    ПОЧЕМУ КВАЛИФИЦИРУЕМ ВСЕГДА, А НЕ ТОЛЬКО ПРИ СТОЛКНОВЕНИИ. `id` уникален
    ВНУТРИ программы — это контракт; между программами совпадение ЗАКОННО, и две
    программы, написанные независимо, обе назовут свою первую стену `wall1`.
    Квалификация по требованию дала бы плавающий адрес: одна и та же операция
    звалась бы `wall1` или `p2/wall1` в зависимости от того, что написано в
    СОСЕДНЕЙ программе. Находка вердикта — это адрес починки, и адрес обязан
    зависеть только от того, к чему он ведёт.
    """
    return f"p{position}{_BUNDLE_SEP}{oid}"


def _ref_targets(value: Any) -> list[str]:
    """Все адресаты `{"by": "ref"}` внутри значения, как угодно вложенные.

    Обход РОДОВОЙ, а не по именам полей, — той же причины, что у `_adapt_ref`:
    хозяин зовётся `host` у проёма, `target` у марки и `members` у группы, и
    список имён разошёлся бы со схемой на первой же новой операции.
    """
    if isinstance(value, Mapping):
        if value.get("by") == "ref":
            return [str(value.get("value"))]
        out: list[str] = []
        for item in value.values():
            out.extend(_ref_targets(item))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_ref_targets(item))
        return out
    return []


def _rewrite_refs(value: Any, rename: Mapping[str, str]) -> Any:
    """Переписать адресатов ссылок под квалифицированные идентификаторы."""
    if isinstance(value, Mapping):
        if value.get("by") == "ref":
            target = str(value.get("value"))
            if target in rename:
                return {**value, "value": rename[target]}
            return dict(value)
        return {key: _rewrite_refs(item, rename) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rewrite_refs(item, rename) for item in value]
    return value


def _require_bundle(bundle: Any) -> list[list[Mapping[str, Any]]]:
    """Последовательность ПРОГРАММ либо отказ, называющий увиденное и его дверь."""
    if isinstance(bundle, Mapping):
        if isinstance(bundle.get("ops"), (list, tuple)):
            raise ProgramShapeError(
                "это ОДНА программа, а дверь принимает ПАЧКУ — последовательность "
                "программ: [программа_тела, программа_лестницы]. Одну программу "
                f"судит {_SHAPE_DOOR[_SHAPE_OPS]}. Если здание правда одно"
                "этажное и лестница ему не нужна — идите туда",
                got=_SHAPE_PROGRAM)
        raise ProgramShapeError(
            "пачка пришла словарём без ключа `ops`: пачка — это СПИСОК программ. "
            f"Ключи, которые пришли: {sorted(str(k) for k in bundle)[:12]}",
            keys=sorted(str(k) for k in bundle)[:12])
    if isinstance(bundle, (str, bytes)):
        raise ProgramShapeError(
            f"пачка пришла как строка ({len(bundle)} символов), а нужен СПИСОК "
            "программ", got=type(bundle).__name__)
    if not isinstance(bundle, (list, tuple)):
        raise ProgramShapeError(
            f"пачка пришла как {type(bundle).__name__}, а нужен список программ",
            got=type(bundle).__name__)
    if not bundle:
        raise ProgramShapeError(
            "пачка пуста: ни одной программы. Пустая пачка — это не «здание без "
            "помещений», это отсутствие входа", programs=0)
    out: list[list[Mapping[str, Any]]] = []
    for index, item in enumerate(bundle):
        position = index + 1
        shape = _shape_of(item)
        # Элемент пачки — ПРОГРАММА. Операция и узел L1 здесь встречаются ровно
        # тогда, когда вызывающий подал программу ТУДА, где ждут пачку, — и
        # отказ обязан назвать это, а не разбирать операцию как программу.
        if shape in (_SHAPE_OPS, _SHAPE_L1):
            raise ProgramShapeError(
                f"пачка[{index}] — это {_SHAPE_RU[shape]}, а элемент пачки — это "
                f"ПРОГРАММА целиком ({_SHAPE_RU[_SHAPE_PROGRAM]}). Похоже, подан "
                f"СПИСОК ОПЕРАЦИЙ вместо списка программ: его принимает "
                f"{_SHAPE_DOOR[shape]}. Это утверждение О ФОРМЕ ВХОДА — стены и "
                f"помещения здесь ещё не читались",
                index=index, got=shape, want=_SHAPE_PROGRAM)
        try:
            ops = _require_shape(item, _SHAPE_OPS)
        except ProgramShapeError as exc:
            raise ProgramShapeError(
                f"пачка[{index}] (программа {position}): {exc.message_ru}",
                index=index, **exc.detail) from exc
        out.append(ops)
    return out


def _merge_bundle(
    programs: Sequence[Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str], list[int]]:
    """Пачка -> ОДИН список операций здания. Порядок пачки сохраняется.

    ПОРЯДОК ЗНАЧИМ, и поэтому слияние — конкатенация, а не объединение множеств:
    программы исполняются последовательно, и уровень, созданный первой,
    существует для второй. Именно на этом стоит лестничная программа — она
    адресует уровень ПО ИМЕНИ (`base_level` не принимает `ref`: `ref_kinds`
    пуст, замерено), и имя разрешается потому, что `create_level` первой
    программы лежит в этом же списке ВЫШЕ.

    Возвращает: операции, СТОЛКНУВШИЕСЯ идентификаторы, размеры программ.
    """
    own_ids: list[list[str]] = []
    for ops in programs:
        ids: list[str] = []
        for index, op in enumerate(ops):
            raw = op.get("id")
            # Та же подстановка, что и в `_ops_to_nodes`: иначе безымянная
            # операция получила бы здесь один адрес, а там другой.
            ids.append(str(raw) if raw not in (None, "") else f"#{index}")
        own_ids.append(ids)

    merged: list[dict[str, Any]] = []
    for position0, ops in enumerate(programs):
        position = position0 + 1
        ids = own_ids[position0]
        mine = set(ids)
        rename = {oid: _bundle_oid(position, oid) for oid in ids}
        for index, op in enumerate(ops):
            for target in _ref_targets(op):
                if target in mine:
                    continue
                elsewhere = [other + 1 for other, other_ids in enumerate(own_ids)
                             if other != position0 and target in set(other_ids)]
                if elsewhere:
                    raise BundleContractError(
                        f"программа {position}, операция `{ids[index]}`: ссылка "
                        f"{{\"by\": \"ref\"}} на `{target}` ведёт в программу "
                        f"{elsewhere[0]} этой же пачки. Ссылка живёт ВНУТРИ "
                        f"программы: соседняя программа — отдельная транзакция, "
                        f"и к её исполнению id `{target}` уже не существует. "
                        f"Адресуй по ИМЕНИ ({{\"by\": \"name\"}}) — имя переживает "
                        f"границу программы, ссылка нет",
                        program=position, op_id=ids[index], ref=target,
                        defined_in=elsewhere[0])
                # Адресат неизвестен ВСЕЙ пачке — это висячая ссылка, а не
                # нарушение закона пачки. О ней говорит свидетель сборки теми же
                # словами, что и для одиночной программы: складывать два разных
                # диагноза в один код значило бы потерять адрес починки.
            body = {key: value for key, value in op.items() if key != "id"}
            body = _rewrite_refs(body, rename)
            merged.append({**body, "id": rename[ids[index]]})

    seen: Counter = Counter()
    for ids in own_ids:
        seen.update(set(ids))
    collisions = sorted(oid for oid, count in seen.items() if count > 1)
    return merged, collisions, [len(ids) for ids in own_ids]


def spatial_model_from_bundle(
    bundle: Any,
    *,
    building_id: str,
    profile: StageProfile | None = DESIGN_STAGE,
    close_tol_mm: float = PARTITION_CLOSE_TOL_MM,
) -> tuple[SpatialModel, BuildWitness]:
    """`SpatialModel` из ПАЧКИ программ — здание, а не одна его программа."""
    programs = _require_bundle(bundle)
    # ЗАКОН ПРОВЕРЯЕТСЯ ПО ЗВЕНЬЯМ, А НЕ ПО ОБЪЕДИНЕНИЮ, и ровно в этом смысл
    # пачки: `create_stairs` рядом со стенами НЕЗАКОНЕН в одной программе и
    # СОВЕРШЕННО ЗАКОНЕН в пачке, где он — своё звено. Проверь мы слитый
    # список, пачка отказывала бы сама себе, то есть дверь запрещала бы
    # единственную форму, ради которой заведена.
    for index, program in enumerate(programs, start=1):
        _refuse_if_unbuildable(
            program.get("ops", ()) if isinstance(program, Mapping) else program,
            where=f"звено пачки p{index}")
    ops, collisions, sizes = _merge_bundle(programs)
    # Слитый список сюда идёт УЖЕ проверенным по звеньям — поэтому строим из
    # него напрямую, минуя дверь одной программы с её законом.
    model, witness = spatial_model_from_program(
        _ops_to_nodes(ops), building_id=building_id, profile=profile,
        close_tol_mm=close_tol_mm)
    witness.note("bundle",
                 f"пачка из {len(programs)} программ судится как ОДНО здание "
                 f"(операций по программам: {sizes}); идентификаторы операций "
                 f"квалифицированы позицией программы — `p1/wall3`",
                 len(programs))
    if collisions:
        # НАЗВАНО, а не разрешено молча в пользу последней программы: без этой
        # записи две разные стены с общим `wall1` слились бы в одну находку, и
        # читатель чинил бы не ту.
        witness.note("bundle_id_collision",
                     "идентификаторы, занятые более чем одной программой пачки "
                     f"(это ЗАКОННО — id уникален внутри программы): "
                     f"{', '.join(collisions[:12])}"
                     + (" …" if len(collisions) > 12 else "")
                     + ". Каждый развёрнут в свой `p<номер>/<id>`",
                     len(collisions))
    return model, witness


def check_bundle(
    bundle: Any,
    *,
    building_id: str = "(пачка программ KIR)",
    thresholds: Thresholds | None = None,
) -> DesignVerdict:
    """ПАЧКА программ KIR -> вердикт о ЗДАНИИ, одним вызовом.

    Единица здания — ПАЧКА, а не программа: тело отдельно, лестницы отдельно
    (`KIR-L002`). Эта дверь судит их ОБЪЕДИНЕНИЕ, поэтому `HAB010`/`HAB001`
    видят лестницу, которую по закону Revit нельзя было положить в тело.

    Род входа тот же, что у `check_ops`, — операции KIR; отличается ЕДИНИЦА.
    Это САМОПРОВЕРКА (`ModelSource.PROGRAM`): судится ЗАЯВЛЕННОЕ пачкой.
    """
    model, witness = spatial_model_from_bundle(bundle, building_id=building_id)
    return check_design(model, witness, thresholds=thresholds)


def spatial_model_from_program(
    nodes: Sequence[Mapping[str, Any]],
    *,
    building_id: str,
    profile: StageProfile | None = DESIGN_STAGE,
    close_tol_mm: float = PARTITION_CLOSE_TOL_MM,
    diagnostics: Sequence[Any] = (),
) -> tuple[SpatialModel, BuildWitness]:
    """`SpatialModel` из УЗЛОВ L1. Самопроверка: судится заявленное.

    ВХОД ЗДЕСЬ — ВНУТРЕННЯЯ ФОРМА ДЕКОМПИЛЯТОРА (`{"kind": "op", "op_name": …,
    "params": {…}, "source_element_id": …}`), а не операции KIR. Наружная дверь —
    :func:`spatial_model_from_ops` / :func:`check_ops`: они принимают ровно то, что
    отдаёт песочница, и переходник форм живёт ВНУТРИ этого модуля.

    Читаются ровно те числа, которые несут параметры опов. Ни одно поле не берётся из
    L0 в обход программы — иначе ворота сравнивали бы разбор с самим собой.

    `diagnostics` — необязательные `LiftDiagnostic` того же подъёма. Они не участвуют
    в сборке: они дают воротам ТИПИЗИРОВАННУЮ причину, по которой элемент не стал
    операцией, чтобы разницу населения объясняло `no_lifter`/`missing_geometry`,
    а не общая фраза.
    """
    # ФОРМА ПРОВЕРЯЕТСЯ ДО СБОРКИ, и это не педантизм. До 03.08 сюда можно было
    # передать операции KIR: ни у одного не было ключа `kind`, `ops` выходил
    # пустым, вырожденные ворота `_run_v2` печатали «HAB000 — model has no rooms»
    # — и это было НЕПРАВДОЙ при живых `create_room` в программе, врущей ровно в
    # ту сторону, в которую модель побежит чинить.
    nodes = _require_shape(nodes, _SHAPE_L1)
    witness = BuildWitness(source=ModelSource.PROGRAM, building_id=building_id)
    ops = [node for node in nodes if node.get("kind") == "op"]
    atoms = sum(1 for node in nodes if node.get("kind") == "atom")
    if atoms:
        witness.note("atoms",
                     "элементов, не ставших операциями (в программе их нет)", atoms)
    for diagnostic in diagnostics:
        category = getattr(diagnostic, "category", None)
        reason = getattr(diagnostic, "reason", None)
        if not category or reason is None:
            continue
        code = getattr(reason, "value", str(reason))
        witness.lift_atoms.setdefault(category, Counter())[code] += 1

    # --- уровни ---------------------------------------------------------------
    raw_levels: list[tuple[str, str, float]] = []
    for node in ops:
        if node["op_name"] != "create_level":
            continue
        params = node["params"]
        name = str(params.get("name") or f"level@{params['elev_mm']}")
        raw_levels.append((node["source_element_id"], name, float(params["elev_mm"])))
    raw_levels.sort(key=lambda item: item[2])
    levels = [Level(id=lid, name=name, elevation_mm=elev, index=index)
              for index, (lid, name, elev) in enumerate(raw_levels)]
    level_by_name = {name: lid for lid, name, _ in raw_levels}
    elevations = {lid: elev for lid, _, elev in raw_levels}

    def resolve_level(ref: Any) -> str | None:
        name = _ref_name(ref)
        if name is not None and name in level_by_name:
            return level_by_name[name]
        source = _ref_source_id(ref)
        if source is not None and source in elevations:
            return source
        return None

    # --- стены ----------------------------------------------------------------
    walls: list[Wall] = []
    segs_by_level: dict[str, list[_WallSeg]] = defaultdict(list)
    wall_node_to_id: dict[str, str] = {}
    for node in ops:
        if node["op_name"] != "create_wall":
            continue
        params = node["params"]
        level_id = resolve_level(params.get("level"))
        if level_id is None:
            witness.note("wall_level_unresolved",
                         "у стены уровень не разрешается по программе — в план не идёт")
            witness.drop("walls", "уровень не разрешается по программе")
            continue
        if params.get("arc"):
            # Дуговая стена: разбиение работает по отрезкам, хорда сузила бы
            # помещение молча. Стена в модель идёт (её видят HAB041/HAB042),
            # но в разбиение — нет.
            witness.note("wall_arc",
                         "дуговая стена: в планарное разбиение не включена (хорда "
                         "изменила бы площадь молча)")
        p0 = (float(params["p0_mm"][0]), float(params["p0_mm"][1]))
        p1 = (float(params["p1_mm"][0]), float(params["p1_mm"][1]))
        base = elevations[level_id] + float(params.get("base_offset_mm") or 0.0)
        top_ref = params.get("top_level")
        top_level_id = resolve_level(top_ref) if top_ref else None
        if top_level_id is not None:
            top = elevations[top_level_id] + float(params.get("top_offset_mm") or 0.0)
            height_known = True
        elif params.get("height_mm") is not None:
            top = base + float(params["height_mm"])
            height_known = True
        else:
            top, height_known = base, False
        wall_id = node["source_element_id"]
        wall_node_to_id[node["_id"]] = wall_id
        walls.append(Wall(id=wall_id, level_id=level_id, curve=(p0, p1),
                          height_mm=abs(top - base), is_structural=False))
        if not params.get("arc"):
            segs_by_level[level_id].append(_WallSeg(
                wall_id=wall_id, level_id=level_id, p0=p0, p1=p1,
                height_mm=abs(top - base), height_known=height_known))
    walls_by_id = {wall.id: wall for wall in walls}

    # --- разделители помещений: граница есть, стены нет ------------------------
    #
    # РАЗДЕЛИТЕЛЬ ЗАМЫКАЕТ ПОМЕЩЕНИЕ, НО НЕ ЯВЛЯЕТСЯ СТЕНОЙ, и обе половины этой
    # фразы несущие. Первая: комната, открытая в коридор, четвёртой стены не
    # имеет и иметь не должна — её границу держит `create_room_separator`, и
    # разбиение, построенное по одним `create_wall`, такую комнату не замыкает
    # ВООБЩЕ (замер: полигона нет, причина «not_enclosed_by_walls», дальше
    # каскадом «площадь 0» у HAB020 и «нет окна» у HAB030). Вторая: в
    # `SpatialModel.walls` разделитель не попадает — HAB041/HAB042/HAB050 читают
    # стены, и разделитель среди них был бы стеной нулевой толщины, которой
    # нельзя ни пробить проём, ни держать нагрузку.
    #
    # `height_known=False` — не заглушка, а факт: высоты у разделителя нет.
    # `_height_from_enclosure` такие отрезки ПРОПУСКАЕТ до счёта периметра,
    # поэтому голосование о высоте они не разбавляют (проверено тестом).
    for node in ops:
        if node["op_name"] != "create_room_separator":
            continue
        params = node["params"]
        level_id = resolve_level(params.get("level"))
        if level_id is None:
            witness.note("separator_level_unresolved",
                         "у разделителя помещений уровень не разрешается по "
                         "программе — в разбиение не идёт")
            witness.drop("room_separators", "уровень не разрешается по программе")
            continue
        path = params.get("path") or []
        if len(path) < 2:
            witness.note("separator_degenerate",
                         "разделитель помещений короче двух точек — границы нет")
            continue
        sep_id = node["source_element_id"]
        for index in range(len(path) - 1):
            p0 = (float(path[index][0]), float(path[index][1]))
            p1 = (float(path[index + 1][0]), float(path[index + 1][1]))
            segs_by_level[level_id].append(_WallSeg(
                # Приставка, чтобы отрезок разделителя нельзя было спутать с
                # адресом стены ни в одной находке.
                wall_id=f"separator::{sep_id}#{index}", level_id=level_id,
                p0=p0, p1=p1, height_mm=0.0, height_known=False))

    # --- помещения: планарное разбиение ---------------------------------------
    room_ops: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    unplaced = 0
    for node in ops:
        if node["op_name"] != "create_room":
            continue
        level_id = resolve_level(node["params"].get("level"))
        if level_id is None:
            unplaced += 1
            continue
        room_ops[level_id].append(node)
    if unplaced:
        witness.note("room_level_unresolved",
                     "у помещения уровень не разрешается по программе", unplaced)
        witness.drop("rooms", "уровень не разрешается по программе", unplaced)

    rooms: list[Room] = []
    room_polys: dict[str, Polygon] = {}
    rooms_by_level: dict[str, list[str]] = defaultdict(list)
    faces_total = 0
    heights_known = 0
    ordered_elevations = sorted(elevations.values())
    for level_id, level_rooms in room_ops.items():
        base_elev = elevations[level_id]
        next_level_z = next((z for z in ordered_elevations if z > base_elev), None)
        partition = _Partition.build(segs_by_level.get(level_id, ()), close_tol_mm)
        faces_total += len(partition.faces)
        claims: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        homeless: list[Mapping[str, Any]] = []
        for node in level_rooms:
            xy = node["params"]["xy"]
            face = partition.face_containing(Point(float(xy[0]), float(xy[1])))
            if face is None:
                homeless.append(node)
            else:
                claims[face].append(node)
        assigned: dict[str, tuple[Polygon, list[_WallSeg]]] = {}
        for face_index, claimants in claims.items():
            if len(claimants) > 1:
                # Грань, на которую претендуют несколько точек, не отдаётся никому:
                # разбиение их не разделило, и выбор был бы догадкой.
                #
                # ЗАПИСКА СЛЕДУЮЩЕЙ ВОЛНЕ (03.08). Канал наружу здесь ПЛОСКИЙ:
                # `shared_face_room_ids` — список идентификаторов без пар, и по
                # нему нельзя сказать, КТО с КЕМ поделил грань. Из-за этого
                # находка «Room X has no measurable boundary polygon» обвиняет
                # НЕВИНОВНУЮ комнату: виновата та, что упала в её же грань, а
                # назвать её нечем. Чинится формой канала, а не текстом
                # сообщения: канал должен носить `face -> [claimant ids]`
                # (например `witness.shared_faces: list[list[str]]`), и тогда
                # сообщение сможет назвать соседа поимённо. Здесь оставлено
                # как есть НАМЕРЕННО: смена формы канала трогает и читателей
                # свидетеля, и это отдельная работа, а не побочная правка.
                for node in claimants:
                    witness.shared_face_room_ids.append(node["source_element_id"])
                    witness.unmeasured_reasons["shared_face"] += 1
                homeless.extend(claimants)
                continue
            node = claimants[0]
            face = partition.faces[face_index]
            assigned[node["source_element_id"]] = (
                face, partition.bounding_segments(face, close_tol_mm))
        shared = set(witness.shared_face_room_ids)
        for node in homeless:
            if node["source_element_id"] not in shared:
                witness.unmeasured_reasons["not_enclosed_by_walls"] += 1
        for node in level_rooms:
            room_id = node["source_element_id"]
            name = str(node["params"].get("name") or "")
            got = assigned.get(room_id)
            if got is None:
                witness.unmeasured_room_ids.append(room_id)
                boundary: list[tuple[float, float]] = []
                area = 0.0
                height = None
            else:
                face, bounding = got
                room_polys[room_id] = face
                boundary = _ring(face)
                area = round(face.area / _MM2_PER_M2, 2)
                height = _height_from_enclosure(
                    bounding, base_z=elevations[level_id],
                    next_level_z=next_level_z)
                if height is not None:
                    heights_known += 1
            rooms.append(Room(
                id=room_id, name=name, level_id=level_id,
                function=classify_room(name),
                # Площадь = площадь ТОГО ЖЕ полигона: программа не объявляет площадь
                # отдельно, значит и расхождения объявленного с выведенным здесь
                # быть не может. HAB060 останется честным свидетелем неизмеримых.
                area_m2=area, height_mm=height, boundary=boundary,
                has_window=False,
                height_source="wall_enclosure" if height is not None else None,
            ))
            rooms_by_level[level_id].append(room_id)
    witness.rooms_total = len(rooms)
    witness.rooms_measured = len(room_polys)
    witness.partition_faces = faces_total
    witness.rooms_with_height = heights_known
    witness.height_source = ("длинновзвешенная высота замкнувших стен, ДОХОДЯЩИХ до "
                             "следующего уровня (БЕЗ толщин пола/потолка)")

    # --- проёмы ---------------------------------------------------------------
    def program_location(node: Mapping[str, Any]) -> tuple[float, float] | None:
        host_node = _ref_node(node["params"].get("host"))
        if host_node is None:
            return None
        wall_id = wall_node_to_id.get(host_node)
        wall = walls_by_id.get(wall_id) if wall_id else None
        if wall is None:
            return None
        (x0, y0), (x1, y1) = wall.curve
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length <= 0.0:
            return None
        offset = float(node["params"].get("offset_mm") or 0.0)
        return (x0 + dx / length * offset, y0 + dy / length * offset)

    def program_host(node: Mapping[str, Any]) -> str | None:
        host_node = _ref_node(node["params"].get("host"))
        return wall_node_to_id.get(host_node) if host_node else None

    doors, windows = _openings(
        door_elements=[n for n in ops if n["op_name"] == "create_door"],
        window_elements=[n for n in ops if n["op_name"] == "create_window"],
        walls_by_id=walls_by_id,
        room_polys=room_polys,
        rooms_by_level=rooms_by_level,
        witness=witness,
        profile=profile,
        location_of=program_location,
        # Габарит проёма программа НЕ выражает: `symbol` называет тип семейства,
        # размеры живут в семействе, а пул заземления несёт `params: null`.
        size_of=lambda node: None,
        host_of=program_host,
        id_of=lambda node: node["source_element_id"],
    )

    witness.curtain_panels = sum(1 for node in ops
                                 if node["op_name"] == "set_curtain_panel")

    # --- лестницы --------------------------------------------------------------
    stairs: list[Stair] = []
    for node in ops:
        if node["op_name"] != "create_stairs":
            continue
        params = node["params"]
        base_id = resolve_level(params.get("base_level"))
        top_id = resolve_level(params.get("top_level"))
        if base_id is None or top_id is None:
            witness.note("stair_level_unresolved",
                         "у лестницы уровень не разрешается по программе")
            witness.drop("stairs", "уровень не разрешается по программе")
            continue
        width = params.get("width_mm")
        footprint: list[tuple[float, float]] = []
        if width and params.get("p0_mm") is not None:
            p0 = (float(params["p0_mm"][0]), float(params["p0_mm"][1]))
            p1 = (float(params["p1_mm"][0]), float(params["p1_mm"][1]))
            band = LineString([p0, p1]).buffer(float(width) / 2.0, cap_style=2)
            if not band.is_empty:
                footprint = _ring(band)
        elif params.get("spiral") is not None:
            # ВИНТОВОЙ МАРШ (09.08): плана у него здесь НЕТ, и это названный
            # пробел, а не молчание. Полосу вокруг отрезка винт не описывает
            # вовсе — его след это кольцевой сектор, — и подставить сюда
            # прямую полосу значило бы дать HAB012 правдоподобно НЕВЕРНЫЙ
            # план. Пусто честнее: ровно так же ведёт себя марш без ширины.
            witness.note("stair_spiral_no_footprint",
                         "винтовой марш: `create_stairs.spiral` — кольцевой "
                         "сектор, полосой вокруг отрезка он не выражается, "
                         "и плана марша здесь нет")
        else:
            witness.note("stair_no_width",
                         "`create_stairs.width_mm` не задан — плана марша нет, "
                         "HAB012 сравнивать нечего")
        stairs.append(Stair(
            id=node["source_element_id"], base_level_id=base_id, top_level_id=top_id,
            base_z=elevations[base_id], top_z=elevations[top_id],
            run_width_mm=float(width) if width else None,
            riser_count=None, tread_depth_mm=None,
            footprint=footprint, kind="element",
        ))

    witness.counts = {
        "levels": len(levels), "rooms": len(rooms), "walls": len(walls),
        "doors": len(doors), "windows": len(windows), "stairs": len(stairs),
    }
    model = SpatialModel(building_id=building_id, levels=levels, rooms=rooms,
                         doors=doors, windows=windows, stairs=stairs, walls=walls)
    _fill_inputs(witness, model)
    return model, witness


# ---------------------------------------------------------------------------------
# 8. ПРОЁМЫ — общий код обоих путей (разные ЧИСЛА, одна геометрия)
# ---------------------------------------------------------------------------------

#: Ключ входа -> как он читается человеком. Ключи снимаются с ГОТОВОЙ модели
#: (`_fill_inputs`), а не описываются словами: расхождение ворот объясняется числом,
#: которое можно перепроверить, иначе объяснение — это догадка с интонацией факта.
_INPUT_RU: dict[str, str] = {
    "rooms": "помещений в модели",
    "rooms_measured": "помещений с полигоном",
    "rooms_with_height": "помещений с известной высотой",
    "rooms_classified": "помещений с распознанной функцией",
    "doors": "дверей",
    "doors_with_width": "дверей с известной шириной проёма",
    "doors_with_adjacency": "дверей, у которых нашлась хотя бы одна сторона",
    "windows": "окон",
    "windows_with_size": "окон с ИЗМЕРЕННЫМ габаритом",
    "windows_joined": "окон, привязанных к помещению",
    "walls": "стен",
    "structural_walls": "стен с признаком «несущая»",
    "levels": "уровней",
    "stairs": "лестниц",
    "stairs_with_footprint": "лестниц с планом марша",
    "stairs_with_geometry": "лестниц с полной геометрией (ширина+подступенки+проступь)",
    "rooms_stair": "помещений, распознанных как лестничная клетка",
    "occupied_levels": "уровней с помещениями",
    "curtain_panels": "витражных заполнений",
}

#: Что КАЖДОЕ правило читает из модели. Таблица снята с исходников правил
#: (`kukai/modeling/checker/rules/*.py`, чтение 03.08), а не с их названий: правило
#: HAB042, например, читает ширину двери, чего по имени «оболочка квартиры» не видно.
_RULE_INPUTS: dict[str, tuple[str, ...]] = {
    "HAB001": ("rooms", "doors_with_adjacency"),
    "HAB002": ("rooms", "doors_with_adjacency", "rooms_classified"),
    "HAB003": ("rooms", "doors_with_adjacency", "stairs", "rooms_classified"),
    "HAB004": ("rooms", "doors_with_adjacency", "rooms_classified"),
    "HAB010": ("levels", "stairs", "rooms_classified", "doors_with_adjacency"),
    "HAB011": ("stairs", "stairs_with_geometry"),
    "HAB012": ("stairs", "stairs_with_footprint"),
    "HAB020": ("rooms_measured", "rooms_classified"),
    "HAB021": ("rooms_measured", "rooms_classified"),
    "HAB022": ("rooms_with_height",),
    "HAB030": ("rooms_classified", "windows_joined", "windows_with_size"),
    "HAB031": ("rooms_classified", "windows_with_size"),
    "HAB040": ("rooms_measured",),
    "HAB041": ("doors", "doors_with_width", "doors_with_adjacency", "walls"),
    "HAB042": ("rooms_measured", "doors_with_width", "walls"),
    "HAB050": ("structural_walls",),
    "HAB060": ("rooms_measured", "windows_joined"),
    "HAB061": ("doors", "doors_with_adjacency"),
    "HAB062": ("rooms_classified", "rooms_measured"),
    "HAB063": ("rooms_measured", "levels"),
}

#: Вход правил -> население, разницу которого он наследует. Нужно, чтобы «классифицировано
#: на 5 меньше» не выглядело самостоятельным явлением, когда самих помещений на 13 меньше.
_INPUT_GOVERNED_BY: dict[str, str] = {
    "rooms_measured": "rooms",
    "rooms_with_height": "rooms",
    "rooms_classified": "rooms",
    "doors_with_width": "doors",
    "doors_with_adjacency": "doors",
    "windows_with_size": "windows",
    "windows_joined": "windows",
    "structural_walls": "walls",
    "stairs_with_footprint": "stairs",
    "stairs_with_geometry": "stairs",
}

#: Род элемента -> категория L0, из которой он поднимается. Нужна, чтобы разницу
#: населения объяснить ТИПИЗИРОВАННОЙ причиной лифта, а не общим местом.
_POPULATION_CATEGORY: dict[str, str] = {
    "curtain_panels": "OST_CurtainWallPanels",
    "rooms": "OST_Rooms",
    "doors": "OST_Doors",
    "windows": "OST_Windows",
    "walls": "OST_Walls",
    "levels": "OST_Levels",
    "stairs": "OST_Stairs",
}


def _fill_inputs(witness: BuildWitness, model: SpatialModel) -> None:
    """Снять с готовой модели все входы правил. Один проход, одно место."""
    witness.rooms_stair = sum(1 for r in model.rooms
                              if r.function is RoomFunction.ЛЕСТНИЦА)
    witness.occupied_levels = len({r.level_id for r in model.rooms})
    witness.inputs = {
        "levels": len(model.levels),
        "rooms": len(model.rooms),
        "rooms_measured": witness.rooms_measured,
        "rooms_with_height": sum(1 for r in model.rooms if r.height_mm is not None),
        "rooms_classified": sum(1 for r in model.rooms
                                if r.function is not RoomFunction.ПРОЧЕЕ),
        "doors": len(model.doors),
        "doors_with_width": sum(1 for d in model.doors if d.width_mm > 0.0),
        "doors_with_adjacency": sum(1 for d in model.doors
                                    if d.from_room_id or d.to_room_id),
        "windows": len(model.windows),
        "windows_with_size": sum(1 for w in model.windows
                                 if w.height_mm is not None and w.width_mm > 0.0),
        "windows_joined": sum(1 for w in model.windows if w.room_id),
        "walls": len(model.walls),
        "structural_walls": sum(1 for w in model.walls if w.is_structural),
        "stairs": len(model.stairs),
        "stairs_with_footprint": sum(1 for s in model.stairs if s.footprint),
        "stairs_with_geometry": sum(
            1 for s in model.stairs
            if s.run_width_mm is not None and s.riser_count is not None
            and s.tread_depth_mm is not None),
        "rooms_stair": witness.rooms_stair,
        "occupied_levels": witness.occupied_levels,
        "curtain_panels": witness.curtain_panels,
    }


def _polygon_or_none(boundary: Sequence[tuple[float, float]]) -> Polygon | None:
    if not boundary or len(boundary) < 3:
        return None
    poly = Polygon(boundary)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.geom_type == "MultiPolygon":
        if poly.is_empty:
            return None
        poly = max(poly.geoms, key=lambda g: g.area)
    if poly.is_empty or poly.area <= 0.0:
        return None
    return poly


#: НИЧЬЯ при выборе смежности проёма. Это НЕ порог и НЕ «мелкая разница».
#:
#: ЗАМЕР 10.08.2026 (прибор — сырой разбор `L0.jsonl`, корпус
#: `backend/backend/data/decompile`, машинно-локальный): зазор между ВТОРЫМ и
#: ТРЕТЬИМ кандидатом по расстоянию распадается НАДВОЕ и в полосе между
#: половинами нет ни одного наблюдения.
#:
#:     `демо-v3`      66 дверей со степенью >=3: зазор РОВНО 0.0 у 36 (54.5%),
#:                    у остальных 30 — от 145.702 до 204.951 мм
#:     `k2_ar_rd_v7`  34 двери: зазор 0.0 у НУЛЯ, у всех 34 — 115.242 либо
#:                    237.894 мм
#:
#: То есть различать надо ТОЧНОЕ равенство, а величина ниже защищает только от
#: шума двоичной арифметики и не решает НИЧЕГО. Поднимать её до «разумных»
#: миллиметров ЗАПРЕЩЕНО: это превратит защиту от шума в границу, заведённую
#: рассуждением, — главный класс дефекта этого кода. Пустая полоса
#: 0.0 … 115.242 мм измерена, а не назначена; если новое здание её заполнит,
#: правило обязано пересматриваться замером, а не подкруткой числа.
_ADJACENCY_TIE_EPS_MM: float = 1e-6


def _adjacent_pair(ranked: Sequence[tuple[float, str]],
                   witness: BuildWitness) -> tuple[str | None, str | None]:
    """Две комнаты, которые дверь РАЗДЕЛЯЕТ, — по геометрии либо никак.

    ЧТО ЗДЕСЬ ИСПРАВЛЕНО. Прежний код брал `near[0]`, `near[1]` из списка,
    отсортированного ПО ИДЕНТИФИКАТОРУ КОМНАТЫ. Когда точка касалась трёх и
    более помещений, пара выбиралась алфавитом — величиной, не имеющей
    отношения ни к геометрии, ни к зданию. Следствие сильнее, чем счёт
    попавших: ПЕРЕИМЕНОВАНИЕ КОМНАТ МЕНЯЛО СМЕЖНОСТЬ ЗДАНИЯ, НЕ МЕНЯЯ ЗДАНИЯ,
    а смежность идёт ребром в `checker/graph.py` и дальше в вывод квартир и в
    правила эвакуации.

    ПОЧЕМУ ОТКАЗ, А НЕ «ДВЕ БЛИЖАЙШИЕ». Замер показал, что на `демо-v3` в
    54.5% случаев второе место занято ВНИЧЬЮ (`d = [0.0, 150.0, 150.0]`):
    одна комната содержит точку, а две соседние стоят ровно на 150 мм. Взять
    «две ближайшие» здесь значит снова спросить алфавит, только тише. Поэтому
    пара объявляется, ТОЛЬКО если между вторым и третьим кандидатом есть
    зазор; иначе называется то, что известно, и молчится о том, что нет.

    ПОЧЕМУ ОТКАЗ БЕЗОПАСЕН ИМЕННО У ДВЕРИ. Ребро смежности неверной парой
    делает правило эвакуации НЕСПОСОБНЫМ ОТКАЗАТЬ — тот же дефект, из-за
    которого один узел OUTSIDE сваривал этажи через улицу и HAB010 не мог
    провалиться. Дверь без ребра — состояние, которое пакет уже умеет:
    `derive.py` снимает рёбра фантомных дверей (`exclude_door_ids`), а
    `_landing_room_on_level` при неоднозначных площадках возвращает None и
    НЕ СТРОИТ ребра. Здесь тот же выбор, тем же основанием.

    Порядок внутри пары (кто `from`, кто `to`) СЕМАНТИКИ НЕ НЕСЁТ: реальный
    экстрактор ставит FromRoom/ToRoom по развороту двери, а не по смыслу
    внутри/снаружи, и потребители читают пару как НЕУПОРЯДОЧЕННУЮ
    (`building_entrance_rooms` берёт любую непустую сторону, `build_graph`
    строит НЕОРИЕНТИРОВАННОЕ ребро). Инвариант — множество, а не слоты.
    """
    if not ranked:
        return None, None
    if len(ranked) == 1:
        return ranked[0][1], None
    if len(ranked) == 2:
        return ranked[0][1], ranked[1][1]
    if ranked[2][0] - ranked[1][0] > _ADJACENCY_TIE_EPS_MM:
        return ranked[0][1], ranked[1][1]
    if ranked[1][0] - ranked[0][0] > _ADJACENCY_TIE_EPS_MM:
        witness.note(
            "opening_second_side_undecidable",
            f"у двери первая сторона определена геометрией, а ВТОРАЯ занята "
            f"вничью ({len(ranked)} помещений в допуске, кандидаты на второе "
            f"место равноудалены): вторая сторона не объявлена, потому что "
            f"выбрать её можно было бы только по имени помещения")
        return ranked[0][1], None
    witness.note(
        "opening_sides_undecidable",
        f"у двери НИ ОДНА сторона не определяется геометрией: {len(ranked)} "
        f"помещений в допуске равноудалены. Стороны не объявлены — прежний код "
        f"брал две первые ПО АЛФАВИТУ идентификатора")
    return None, None


def _nearest_room(ranked: Sequence[tuple[float, str]],
                  witness: BuildWitness) -> str | None:
    """Помещение, которое окно освещает: БЛИЖАЙШЕЕ, а при ничьей — названное.

    ОТЛИЧИЕ ОТ ДВЕРИ НАМЕРЕННОЕ, И ВОТ ЕГО ОСНОВАНИЕ. У двери отказ снимает
    ребро и может лишь лишить правило зелёного света. У окна отказ снимает
    `room_id`, а на нём стоит HAB030 («в помещении нет окна»): отказаться
    значит ОБВИНИТЬ здание — ровно тот класс ложных BLOCKING, против которого
    в чекере v2 заведены `APARTMENT_MARKERS` и оговорки `_caveats`. Поэтому
    здесь выбор не снимается, а УТОЧНЯЕТСЯ до геометрического и НАЗЫВАЕТСЯ,
    когда геометрия молчит.

    ЗАМЕР 10.08, почему это не теория: `sob62_r23_v5` — 24 окна из 31 касаются
    ДВУХ помещений, и ВСЕ 24 стоят к ним РОВНО НА ОДНОМ расстоянии. То есть на
    этом здании выбор помещения у каждого неоднозначного окна делался
    алфавитом. Прочие здания корпуса неоднозначных окон не дают вовсе
    (`демо-v3` — 0, `k2_ar_rd_v7` — 0, `snowdon_plumb_v5` — 0).

    Смена семантики HAB030 на «окно МОЖЕТ освещать любое из N» — решение о
    продукте, а не механическая правка, и здесь оно не принимается.
    """
    if not ranked:
        return None
    if len(ranked) == 1:
        return ranked[0][1]
    if ranked[1][0] - ranked[0][0] > _ADJACENCY_TIE_EPS_MM:
        return ranked[0][1]
    witness.note(
        "window_room_undecidable",
        f"окно равноудалено от {len(ranked)} помещений: помещение выбрано ПО "
        f"ИМЕНИ, потому что геометрия их не различает. Число сказано, чтобы "
        f"HAB030 читался с этой поправкой, а не как факт о здании")
    return ranked[0][1]


def _openings(
    *,
    door_elements: Iterable[Any],
    window_elements: Iterable[Any],
    walls_by_id: Mapping[str, Wall],
    room_polys: Mapping[str, Polygon],
    rooms_by_level: Mapping[str, list[str]],
    witness: BuildWitness,
    profile: StageProfile | None,
    location_of,
    size_of,
    host_of,
    id_of,
    level_of=lambda element: None,
) -> tuple[list[Door], list[Window]]:
    """Двери и окна обоих путей.

    Смежность двери НЕ объявляется от себя: берутся помещения, чьи полигоны дверь
    ДЕЙСТВИТЕЛЬНО касается. Дверь, не коснувшаяся ни одного ИЗМЕРЕННОГО помещения,
    остаётся без сторон — и `derive.py` назовёт это «стороны неизмеримы», а не
    «фантомная дверь»: разница между «не смогли проверить» и «проверили и не сошлось»
    здесь стоит целого класса ложных обвинений.

    `is_exterior` тоже не объявляется: наружность выводит `derive.py` ПОЛОЖИТЕЛЬНЫМ
    членством в кольце оболочки. Объявить её здесь значило бы подсунуть чекеру ответ
    на вопрос, который он задаёт.
    """
    tol = OPENING_JOIN_TOL_MM
    level_of_wall = {wid: wall.level_id for wid, wall in walls_by_id.items()}
    trees: dict[str, tuple[list[str], STRtree]] = {}
    for level_id, room_ids in rooms_by_level.items():
        ids = [rid for rid in room_ids if rid in room_polys]
        if ids:
            trees[level_id] = (ids, STRtree([room_polys[rid] for rid in ids]))

    def touching(level_id: str, point: Point) -> list[tuple[float, str]]:
        """Комнаты, которых касается точка, РАНЖИРОВАННЫЕ ПО РАССТОЯНИЮ.

        Возвращается расстояние, а не один адрес: без него выбрать сторону
        можно только сортировкой строк, а лексикографический порядок
        идентификаторов не есть свойство постройки. Прежняя `sorted(out)`
        отдавала комнаты ПО АЛФАВИТУ, и `near[0]`/`near[1]` брали первые две.
        """
        got = trees.get(level_id)
        if got is None:
            return []
        ids, tree = got
        out: list[tuple[float, str]] = []
        for index in tree.query(point.buffer(tol)):
            rid = ids[int(index)]
            poly = room_polys[rid]
            if poly.contains(point):
                out.append((0.0, rid))
                continue
            distance = poly.exterior.distance(point)
            if distance <= tol:
                out.append((distance, rid))
        return sorted(out)

    doors: list[Door] = []
    for element in door_elements:
        host = host_of(element)
        level_id = level_of(element) or (level_of_wall.get(host) if host else None)
        location = location_of(element)
        if location is None:
            witness.note("door_no_geometry",
                         "у двери в представлении нет ни точки, ни рамки — положения "
                         "не существует, дверь пропущена")
            witness.drop("doors", "положения нет в представлении")
            continue
        if level_id is None:
            witness.note("door_no_level",
                         "у двери не разрешается уровень (ни свой, ни хозяина) — "
                         "пропущена")
            witness.drop("doors", "уровень не разрешается")
            continue
        size = size_of(element)
        first, second = _adjacent_pair(
            touching(level_id, Point(location)), witness)
        doors.append(Door(
            id=id_of(element), level_id=level_id, location=location,
            width_mm=float(size[0]) if size else 0.0,
            from_room_id=first,
            to_room_id=second,
            is_exterior=False,
            host_wall_id=host,
        ))

    nominal = profile.nominal_opening_area_m2 if profile is not None else None
    windows: list[Window] = []
    measured_any = False
    for element in window_elements:
        host = host_of(element)
        level_id = level_of(element) or (level_of_wall.get(host) if host else None)
        location = location_of(element)
        if location is None:
            # ЗАМЕР 03.08 (K2): 46 окон из 49 не несут в L0 НИ точки, ни годной
            # рамки — `geom_kind: bbox_only` с рамкой, которую отбраковал разбор
            # геометрии. Это не отказ сборщика и не дефект здания: чтение окна не
            # видело, и назвать это надо именно так.
            witness.note("window_no_geometry",
                         "у окна в представлении нет ни точки, ни годной рамки — "
                         "положения не существует, окно пропущено")
            witness.drop("windows", "положения нет в представлении")
            continue
        if level_id is None:
            witness.note("window_no_level",
                         "у окна не разрешается уровень (ни свой, ни хозяина) — "
                         "пропущено")
            witness.drop("windows", "уровень не разрешается")
            continue
        size = size_of(element)
        lit_room = _nearest_room(touching(level_id, Point(location)), witness)
        if size is not None:
            measured_any = True
            width, height = size
            area = round(width * height / _MM2_PER_M2, 2)
        else:
            # НАЗВАННОЕ УМОЛЧАНИЕ, а не выдумка: величина отвечает исключительно на
            # вопрос «проём вообще есть», и `StageProfile` запрещает объявлять её,
            # пока не сняты все правила, сравнивающие площадь остекления с допуском.
            width, height, area = 0.0, None, float(nominal or 0.0)
        windows.append(Window(
            id=id_of(element), level_id=level_id, host_wall_id=host,
            room_id=lit_room,
            width_mm=width, area_m2=area, height_mm=height, location=location,
        ))
    witness.opening_size_measured = measured_any
    if not measured_any and windows:
        witness.nominal_opening_area_m2 = nominal
        witness.note(
            "opening_size_unmeasured",
            "габарит проёма представление не выражает; для проверки НАЛИЧИЯ окна "
            f"принят названный номинал профиля {nominal} м², правило 1:8 (HAB031) снято",
            len(windows))
    return doors, windows


# ---------------------------------------------------------------------------------
# 9. ВЕРДИКТ
# ---------------------------------------------------------------------------------

class DesignCheckUnavailable(RuntimeError):
    """Чекер v2 выключен. Отказ, а не тихий откат на v1.

    Путь v1 не имеет ни трёхзначного вердикта, ни покрытия, ни геометрической
    предпроходки — «вердикт» с него был бы бинарным «прошло/не прошло» поверх
    непроверенных деклараций, и отличить его от настоящего было бы нечем.
    """


@dataclass(frozen=True)
class DesignVerdict:
    """Вердикт вместе с тем, ЧТО именно проверялось и откуда взялось."""

    source: ModelSource
    building_id: str
    report: CheckReport
    witness: BuildWitness
    profile: StageProfile | None

    @property
    def verdict(self) -> Verdict | None:
        return self.report.verdict

    @property
    def rules_applied(self) -> int:
        coverage = self.report.coverage
        return coverage.rules_evaluated if coverage else 0

    @property
    def rules_total(self) -> int:
        coverage = self.report.coverage
        return len(coverage.outcomes) if coverage else 0

    @property
    def rules_suspended(self) -> list[str]:
        if self.profile is None:
            return []
        return sorted(self.profile.suspended)


def check_design(
    model: SpatialModel,
    witness: BuildWitness,
    *,
    thresholds: Thresholds | None = None,
) -> DesignVerdict:
    """Прогнать движок правил и вернуть вердикт вместе со свидетелем сборки.

    По умолчанию профиль ВЫВОДИТСЯ из свидетеля (`design_stage_profile`): какие входы
    это представление даёт, такие правила и вправе высказываться. Явный `thresholds`
    перекрывает вывод — им пользуются тесты, которым нужен фиксированный набор.
    """
    if not checker_v2_enabled():
        raise DesignCheckUnavailable(
            "KUKAI_CHECKER_V2=1 не выставлен: путь v1 не даёт ни трёхзначного "
            "вердикта, ни покрытия, ни геометрической предпроходки — молча выдать "
            "его вместо вердикта стадии значило бы подменить утверждение")
    if thresholds is None:
        thresholds = Thresholds(profile=design_stage_profile(witness))
    report = run_checker(model, thresholds)
    return DesignVerdict(source=witness.source, building_id=witness.building_id,
                         report=report, witness=witness,
                         profile=thresholds.profile)


# ---------------------------------------------------------------------------------
# 10. ТЕКСТ, КОТОРЫЙ ЧИТАЕТ МОДЕЛЬ
# ---------------------------------------------------------------------------------

_VERDICT_RU = {
    Verdict.PASS: "ПРИГОДЕН",
    Verdict.FAIL: "НЕПРИГОДЕН",
    Verdict.NOT_EVALUATED: "НЕ ОЦЕНЕНО",
}


def verdict_headline_text(verdict: Verdict | None, *, evaluated: int,
                          total: int) -> str:
    """Заголовок вердикта. ЗАКОН: заголовок не имеет права быть сильнее тела.

    ДЕФЕКТ, ради которого эта функция существует. `Verdict.PASS` печатался словом
    ПРИГОДЕН и точка — при том что тело вердикта тут же перечисляло правила,
    которые не оценивались ВООБЩЕ (замер 03.08: 12 оценённых из 20; на программе
    с лестницей — 9 из 14, и среди неоценённых были достижимость от входа,
    спуск к земле, геометрия лестниц и высоты). Модель читает заголовок и уходит:
    заголовок — единственная строка, которую читают всегда.

    Третье значение НЕ выдумывается: `Verdict` остаётся трёхзначным, меняется
    только СИЛА СЛОВА в заголовке, и меняется она по числу, снятому с покрытия.
    """
    word = _VERDICT_RU.get(verdict, str(verdict))
    if verdict is Verdict.PASS and total and evaluated < total:
        return f"{word} ПО {evaluated} ПРАВИЛАМ ИЗ {total}, ОСТАЛЬНОЕ НЕ ОЦЕНЕНО"
    if verdict is Verdict.NOT_EVALUATED and total:
        return f"ИТОГ НЕ ОЦЕНЕН; ОЦЕНЕНО {evaluated} ПРАВИЛ ИЗ {total}"
    return word


def verdict_headline(verdict: "DesignVerdict") -> str:
    """Тот же заголовок, снятый с готового вердикта."""
    coverage = verdict.report.coverage
    return verdict_headline_text(
        verdict.report.verdict,
        evaluated=coverage.rules_evaluated if coverage else 0,
        total=len(coverage.outcomes) if coverage else 0)

#: Сколько символов одной находки показывать. Правило HAB001 складывает ВСЕ
#: недостижимые помещения в ОДНУ строку сообщения: на башне K2 это 24 000 символов,
#: которые вытеснили бы из окна модели весь остальной вердикт. Обрезается ХВОСТ и
#: называется длина отрезанного — иначе обрезка неотличима от того, что находок мало.
_MSG_CLIP = 260
_REFS_CLIP = 12


def _clip(text: str, limit: int = _MSG_CLIP) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (+{len(text) - limit} символов)"


def _clip_refs(refs: Sequence[str]) -> str:
    shown = ", ".join(refs[:_REFS_CLIP])
    if len(refs) <= _REFS_CLIP:
        return shown
    return f"{shown} … всего {len(refs)}"


def render_verdict(verdict: DesignVerdict, *, max_examples: int = 3) -> str:
    """Вердикт человеческим (и модельным) текстом.

    Порядок частей задан тем, в каком порядке их можно ЧЕСТНО читать: сначала
    источник (самопроверка это или чтение), затем профиль (по какому набору судили),
    затем покрытие (на что вообще смотрели), и только потом находки. Находка,
    прочитанная раньше покрытия, — это утверждение без знаменателя.
    """
    report = verdict.report
    coverage = report.coverage
    witness = verdict.witness
    lines: list[str] = []

    lines.append(f"═══ ВЕРДИКТ О ЗАМЫСЛЕ: {verdict_headline(verdict)} ═══")
    lines.append(f"здание: {witness.building_id}"
                 + (f"  ({witness.doc_name})" if witness.doc_name else ""))
    lines.append(f"источник: {verdict.source.evidence}")

    if verdict.profile is not None:
        evaluated = coverage.rules_evaluated if coverage else 0
        total = len(coverage.outcomes) if coverage else 0
        lines.append(f"профиль: {verdict.profile.name} — "
                     f"применимо {total - len(verdict.rules_suspended)} правил "
                     f"из {total}, оценено {evaluated}")
        # Правила, снятые ОДНОЙ И ТОЙ ЖЕ причиной, печатаются одной строкой: четыре
        # копии одного абзаца читаются как четыре разных повода, а повод один.
        by_reason: dict[str, list[str]] = defaultdict(list)
        for rule_id in verdict.rules_suspended:
            by_reason[verdict.profile.suspension_reason(rule_id)].append(rule_id)
        for reason, rule_ids in by_reason.items():
            lines.append(f"    снято {'/'.join(sorted(rule_ids))}: {reason}")
        partial = [o for o in (coverage.outcomes if coverage else [])
                   if o.excluded_subjects]
        for outcome in partial:
            lines.append(
                f"    не оценено {outcome.rule_id} на {outcome.excluded_subjects} "
                f"субъектах: {outcome.excluded_reason} "
                f"(высказалось о {outcome.n_subjects})")
        if witness.nominal_opening_area_m2 is not None:
            lines.append(f"    названное умолчание: габарит проёма не выражен, принят "
                         f"номинал {witness.nominal_opening_area_m2} м² ТОЛЬКО для "
                         f"проверки наличия окна")

    lines.append("")
    lines.append(f"что прочитано: " + ", ".join(
        f"{name} {count}" for name, count in sorted(witness.counts.items())))
    lines.append(
        f"полигон помещения получили {witness.rooms_measured} из "
        f"{witness.rooms_total} ({witness.measured_ratio:.0%}); "
        f"неизмеримых {len(witness.unmeasured_room_ids)}")
    for reason, count in witness.unmeasured_reasons.most_common():
        lines.append(f"    {count:>6}  {_UNMEASURED_RU.get(reason, reason)}")
    if witness.rooms_total:
        lines.append(f"высота известна у {witness.rooms_with_height} помещений — "
                     f"{witness.height_source}")

    if coverage is not None:
        lines.append("")
        lines.append(f"покрытие: классификация {coverage.classification_coverage:.0%}, "
                     f"измеримость {coverage.measured_room_ratio:.0%}")
        if coverage.mandatory_not_evaluated:
            lines.append("    ОБЯЗАТЕЛЬНЫЕ НЕ ОЦЕНЕНЫ: "
                         + ", ".join(coverage.mandatory_not_evaluated))
        for note in coverage.notes:
            # Заметки покрытия перечисляют ИДЕНТИФИКАТОРЫ всех задетых помещений —
            # на башне это тысячи; сама заметка важна, список из неё — нет.
            lines.append(f"    {_clip(note, 300)}")
        vacuous = [o for o in coverage.outcomes if o.status.value == "not_evaluated"]
        if vacuous:
            lines.append(f"    не оценено правил: {len(vacuous)}")
            # Причины, уже названные в блоке профиля, здесь не повторяются целиком:
            # отчёт, в котором один абзац стоит шесть раз, читают по диагонали.
            named_above = set(verdict.rules_suspended)
            for outcome in vacuous:
                if outcome.rule_id in named_above:
                    lines.append(f"      {outcome.rule_id}: снято профилем (см. выше)")
                else:
                    lines.append(f"      {outcome.rule_id}: {_clip(outcome.reason, 400)}")

    lines.append("")
    for label, bucket in (("БЛОКИРУЮЩИЕ", report.blocking),
                          ("ПРЕДУПРЕЖДЕНИЯ", report.warnings),
                          ("СПРАВОЧНО", report.info)):
        if not bucket:
            continue
        lines.append(f"{label}: {len(bucket)}")
        grouped: dict[str, list] = defaultdict(list)
        for violation in bucket:
            grouped[violation.rule_id].append(violation)
        for rule_id in sorted(grouped):
            found = grouped[rule_id]
            lines.append(f"  {rule_id} — {len(found)}")
            for violation in found[:max_examples]:
                lines.append(f"      {_clip(violation.msg)}")
                if violation.refs:
                    lines.append(f"        адреса: {_clip_refs(violation.refs)}")
            if len(found) > max_examples:
                lines.append(f"      … и ещё {len(found) - max_examples}")

    if witness.notes:
        lines.append("")
        lines.append("что не прочиталось:")
        for note in witness.notes:
            lines.append(f"  {note.count:>6}  {note.detail}")

    caveats = _caveats(witness)
    if caveats:
        lines.append("")
        lines.append("КАК ЧИТАТЬ ЭТИ НАХОДКИ:")
        for caveat in caveats:
            lines.append(f"  · {caveat}")

    lines.append("")
    lines.append("ВНЕ ОБЛАСТИ (не моделируется, поимённо):")
    for item in OUT_OF_SCOPE:
        lines.append(f"  · {item.name}: {item.behaviour} [{item.measured}]")
    return "\n".join(lines)


#: Потолок краткого вердикта. Канал песочницы — `MAX_STDOUT_CHARS` (4000), и он
#: ЕДИНСТВЕННЫЙ, по которому до модели доезжает хоть что-нибудь. Полный вердикт
#: весит 5-8 КБ: напечатанный в скрипт, он вытеснил бы и печать самой модели, и
#: собственный хвост. Число — вычет, а не круглая цифра: половина канала вердикту,
#: половина — плану и печати автора.
BRIEF_VERDICT_CAP = 1800


def render_verdict_brief(verdict: DesignVerdict, *,
                         limit: int = BRIEF_VERDICT_CAP) -> str:
    """Вердикт для УЗКОГО канала (песочница) — короче, но не слабее.

    Что выброшено по сравнению с `render_verdict`: примеры сверх первого, адреса
    элементов, список «вне области» и текст оговорок. Что НЕ выброшено ни при
    каких условиях: заголовок (тот же самый, символ в символ), источник
    (самопроверка), число прочитанного, ВСЕ блокирующие правила поимённо и
    перечень правил, которые не оценивались. Краткость, которая роняет одно из
    этого, превращает вердикт в его пересказ.
    """
    report = verdict.report
    coverage = report.coverage
    witness = verdict.witness
    lines: list[str] = [f"═══ ВЕРДИКТ О ЗАМЫСЛЕ: {verdict_headline(verdict)} ═══"]

    lines.append("источник: САМОПРОВЕРКА — судится ЗАЯВЛЕННОЕ программой, "
                 "а не построенное"
                 if verdict.source is ModelSource.PROGRAM else
                 "источник: независимое чтение разбора (L0)")
    if witness.counts:
        lines.append("прочитано: " + ", ".join(
            f"{name} {count}" for name, count in sorted(witness.counts.items())))
    if witness.rooms_total:
        lines.append(
            f"полигон помещения получили {witness.rooms_measured} из "
            f"{witness.rooms_total} ({witness.measured_ratio:.0%}), "
            f"высота известна у {witness.rooms_with_height}")
        for reason, count in witness.unmeasured_reasons.most_common(2):
            lines.append(f"    {count} — {_UNMEASURED_RU.get(reason, reason)}")

    for label, bucket in (("БЛОКИРУЮЩИЕ", report.blocking),
                          ("ПРЕДУПРЕЖДЕНИЯ", report.warnings)):
        if not bucket:
            continue
        grouped: dict[str, list] = defaultdict(list)
        for violation in bucket:
            grouped[violation.rule_id].append(violation)
        lines.append(f"{label} {len(bucket)}: " + ", ".join(
            f"{rule_id}×{len(found)}" for rule_id, found in sorted(grouped.items())))
        # ПЕРВЫЙ пример КАЖДОГО правила, а не первые примеры первого правила:
        # правило, о котором не сказано ни слова, читается как отсутствующее.
        for rule_id, found in sorted(grouped.items()):
            lines.append(f"  {rule_id}: {_clip(found[0].msg, 150)}")

    if coverage is not None:
        vacuous = [o for o in coverage.outcomes
                   if o.status.value == "not_evaluated"]
        if vacuous:
            lines.append(f"НЕ ОЦЕНЕНО правил {len(vacuous)} из "
                         f"{len(coverage.outcomes)}: "
                         + ", ".join(o.rule_id for o in vacuous))
            named = set(verdict.rules_suspended)
            for outcome in vacuous:
                if outcome.rule_id in named:
                    continue
                lines.append(f"  {outcome.rule_id}: {_clip(outcome.reason, 120)}")
            if named:
                lines.append(f"  снято профилем стадии: "
                             f"{', '.join(sorted(named))} (причины — "
                             f"в полном вердикте)")
        if coverage.mandatory_not_evaluated:
            lines.append("  ОБЯЗАТЕЛЬНЫЕ НЕ ОЦЕНЕНЫ: "
                         + ", ".join(coverage.mandatory_not_evaluated))

    text = "\n".join(lines)
    if len(text) > limit:
        # Обрезка НАЗЫВАЕТ СЕБЯ: молча укороченный вердикт неотличим от вердикта,
        # у которого находок меньше.
        cut = text[:limit].rsplit("\n", 1)[0]
        text = (f"{cut}\n… вердикт обрезан на {limit} символах "
                f"(+{len(text) - len(cut)}); полностью — `render_verdict()`")
    return text


def _caveats(witness: BuildWitness) -> list[str]:
    """Оговорки, которые ОБЯЗАНЫ стоять рядом с находками, а не в конце документа.

    Каждая описывает КАСКАД: одно неизмеренное свойство превращается в поток находок
    у нескольких правил сразу, и без этой строки поток читается как приговор зданию.
    """
    out: list[str] = []
    if witness.rooms_total and witness.rooms_measured < witness.rooms_total:
        missing = witness.rooms_total - witness.rooms_measured
        if witness.source is ModelSource.PROGRAM:
            out.append(
                f"{missing} помещений программа НЕ ЗАМЫКАЕТ стенами. У незамкнутого "
                f"помещения нет площади (её считает контур), поэтому HAB020 говорит "
                f"«площадь 0», HAB030 — «нет окна», HAB041/HAB061 — «дверь ни к чему "
                f"не примыкает». Это верные утверждения О ПРОГРАММЕ (Revit такое "
                f"помещение тоже вернёт незамкнутым), но НЕ приговор зданию: у "
                f"здания эти границы держат разделители помещений и колонны, "
                f"которых в языке KIR нет вовсе")
        else:
            out.append(
                f"{missing} помещений вернулись из чтения с ВЫРОЖДЕННЫМ контуром — "
                f"в Revit это неразмещённые помещения (площадь 0). Тот же каскад: "
                f"HAB020 «площадь 0», HAB030 «нет окна», HAB060 «границу не "
                f"проверить». Находка настоящая, но она о состоянии модели, а не о "
                f"замысле")
    if witness.source is ModelSource.PROGRAM and witness.rooms_with_height:
        out.append(
            "высота помещения на этом пути — высота ЗАМКНУВШИХ ЕГО СТЕН, от отметки "
            "основания до верха. Чистая высота до потолка МЕНЬШЕ на толщины пола и "
            "потолка, которых программа не выражает: замер K2 — 3100 мм по стенам "
            "против 3000 мм по прочтённому помещению. Ошибка в НЕБЕЗОПАСНУЮ сторону, "
            "и HAB022 на этом пути мягче, чем на разборе")
    if witness.nominal_opening_area_m2 is not None:
        out.append(
            "площадь остекления НЕ ИЗМЕРЕНА ни у одного окна: HAB030 отвечает только "
            "на вопрос «проём есть», а норма 1:8 (HAB031) снята профилем — окно "
            "размером с форточку здесь пройдёт")
    windows = witness.counts.get("windows", 0)
    if witness.curtain_panels > windows:
        out.append(
            f"ФАСАД ВИТРАЖНЫЙ: заполнений витража {witness.curtain_panels}, окон "
            f"как отдельных элементов {windows}. У `SpatialModel` понятия «витражное "
            f"остекление» НЕТ, а у панели нет признака «стекло» — есть только имя "
            f"типа, и решать по имени значит гадать. Поэтому HAB030 на таком здании "
            f"даёт ЛОЖНОЕ «нет окна» у комнат за витражом. Это не находка о здании, "
            f"это предел модели, и он один и тот же на обоих путях")
    return out


_UNMEASURED_RU = {
    "not_enclosed_by_walls": "точка помещения не попала ни в одну грань разбиения "
                             "(стены его не замыкают)",
    "shared_face": "на одну грань разбиения претендовало несколько помещений — "
                   "грань не отдана никому",
    "ring_degenerate": "контур помещения вырожден (<3 точек или нулевая площадь)",
}


# ---------------------------------------------------------------------------------
# 11. ВОРОТА: два пути, одно здание
# ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Divergence:
    """Одно расхождение между вердиктами двух путей — с НАЗВАННОЙ причиной."""

    kind: str
    subject: str
    parse: str
    program: str
    cause: str


#: Единственная строка, которую этот модуль вправе сказать, когда причина НЕ снялась
#: с замера. Она обязана быть заметнее любой правдоподобной формулировки: строка,
#: причина которой не установлена, — это находка, а не косметика.
UNATTRIBUTED = "ПРИЧИНА НЕ УСТАНОВЛЕНА — расхождение не сводится ни к одному входу"


def _input_delta(parse: BuildWitness, program: BuildWitness,
                 keys: Iterable[str]) -> str:
    """Какие ИЗ ЧИТАЕМЫХ ПРАВИЛОМ входов различаются, с числами обоих путей."""
    parts: list[str] = []
    for key in keys:
        a = parse.inputs.get(key)
        b = program.inputs.get(key)
        if a is None or b is None or a == b:
            continue
        parts.append(f"{_INPUT_RU.get(key, key)}: А={a} Б={b}")
    return "; ".join(parts)


def _population_cause(parse: BuildWitness, program: BuildWitness,
                      population: str) -> str:
    """Почему население одного рода разошлось: подъём и сборка НАЗЫВАЮТСЯ отдельно.

    Два разных адреса починки: `no_lifter` посылает писать операцию, а «сборщику не
    хватило хозяина» — чинить сборку. Слив их в одну фразу мы бы получили число без
    адреса, что уже стоило проекту одного неверного диагноза (AtomReason §1).
    """
    parts: list[str] = []
    category = _POPULATION_CATEGORY.get(population, "")
    reasons = program.lift_atoms.get(category) if category else None
    if reasons:
        detail = ", ".join(f"{code} x{count}"
                           for code, count in reasons.most_common(4))
        parts.append(f"подъём ({category}): {detail}")
    for label, witness in (("А", parse), ("Б", program)):
        dropped = witness.dropped.get(population)
        if dropped:
            detail = ", ".join(f"{why} x{count}"
                               for why, count in dropped.most_common(4))
            parts.append(f"сборка {label}: {detail}")
    return "; ".join(parts)


def compare(parse: DesignVerdict, program: DesignVerdict) -> list[Divergence]:
    """Свести два вердикта об ОДНОМ здании и назвать расхождения ПОИМЁННО.

    Причина каждой строки ВЫВОДИТСЯ из свидетелей сборки — из чисел, снятых с готовых
    моделей, и из типизированных причин лифта, — а не берётся из заранее написанного
    словаря. Словарь объяснял бы одинаково и настоящую разницу представлений, и
    свежую ошибку в этом самом файле; выведенная причина на второй молчит, и это
    молчание видно (`UNATTRIBUTED`).
    """
    out: list[Divergence] = []
    wa, wb = parse.witness, program.witness

    def add(kind: str, subject: str, a: Any, b: Any, cause: str) -> None:
        if str(a) == str(b):
            return
        out.append(Divergence(kind, subject, str(a), str(b), cause or UNATTRIBUTED))

    # --- вердикт: причина — то, что развело покрытие/находки -------------------
    verdict_cause = _input_delta(wa, wb, _INPUT_RU)
    add("вердикт", "verdict",
        _VERDICT_RU.get(parse.verdict, parse.verdict),
        _VERDICT_RU.get(program.verdict, program.verdict),
        verdict_cause)

    # --- профиль: два представления могут заслуживать РАЗНЫХ наборов правил -----
    # Если наборы разошлись, дальше сравниваются вердикты, вынесенные по разным
    # правилам, и молчать об этом нельзя: это не деталь, это условие сопоставимости.
    a_susp = sorted(parse.profile.suspended) if parse.profile else []
    b_susp = sorted(program.profile.suspended) if program.profile else []
    add("профиль", "снятые правила", ", ".join(a_susp) or "—",
        ", ".join(b_susp) or "—",
        "снятие выводится ИЗ ЗАМЕРА представления; разные наборы означают, что "
        "представления дают разные входы — сравнивать их вердикты можно только по "
        "общей части")

    # --- население: сколько элементов дошло до модели --------------------------
    for name in sorted(set(wa.counts) | set(wb.counts)):
        add("популяция", name, wa.counts.get(name, 0), wb.counts.get(name, 0),
            _population_cause(wa, wb, name))

    # --- входы правил: то, чем всё остальное объясняется ------------------------
    for key in sorted(set(wa.inputs) | set(wb.inputs)):
        a, b = wa.inputs.get(key, 0), wb.inputs.get(key, 0)
        if key in _POPULATION_CATEGORY and a != b:
            continue        # уже названо выше как население
        cause = ""
        if key == "rooms_measured":
            cause = (f"разбор несёт готовый контур Revit; программа замыкает "
                     f"помещение ТОЛЬКО стенами "
                     f"({', '.join(f'{r} x{c}' for r, c in wb.unmeasured_reasons.most_common())})")
        elif key == "rooms_with_height":
            cause = f"А: {wa.height_source}; Б: {wb.height_source}"
        elif key in ("windows_with_size", "doors_with_width"):
            cause = ("габарит проёма живёт в семействе: программа называет только "
                     "`symbol`, разбор несёт FAMILY_WIDTH/HEIGHT_PARAM инстанса")
        elif key in ("windows_joined", "doors_with_adjacency"):
            cause = ("привязка проёма к помещению требует полигона помещения — "
                     f"полигонов А={wa.inputs.get('rooms_measured')} "
                     f"Б={wb.inputs.get('rooms_measured')}")
        elif key == "curtain_panels":
            cause = _population_cause(wa, wb, "curtain_panels") or (
                "разбор считает элементы `OST_CurtainWallPanels`, программа — операции "
                "`set_curtain_panel`; разница = панели, не ставшие операцией")
        elif key == "rooms_stair":
            cause = ("наследует разницу населения «rooms» и один и тот же лексикон "
                     "`classify.py` — расхождение здесь означало бы разные имена, а "
                     "имена у обоих путей одни")
        elif key == "stairs_with_footprint":
            cause = ("план марша: у разбора он из bbox лестницы, у программы — "
                     "только из `create_stairs.width_mm`, который часто не задан")
        if not cause:
            # Последний честный ход перед `UNATTRIBUTED`: вход мог просто наследовать
            # разницу своей популяции. Если и она совпадает — причина НЕ установлена,
            # и это факт, а не повод сочинить формулировку.
            governing = _INPUT_GOVERNED_BY.get(key)
            if governing and wa.counts.get(governing) != wb.counts.get(governing):
                cause = (f"наследует разницу населения «{governing}»: "
                         f"А={wa.counts.get(governing)} Б={wb.counts.get(governing)}"
                         + (f" ({reason})"
                            if (reason := _population_cause(wa, wb, governing)) else ""))
        add("вход правил", key, a, b, cause)

    # --- правила: причина = различие ТЕХ ВХОДОВ, которые правило читает ---------
    parse_rows = {o.rule_id: o for o in (parse.report.coverage.outcomes
                                         if parse.report.coverage else [])}
    prog_rows = {o.rule_id: o for o in (program.report.coverage.outcomes
                                        if program.report.coverage else [])}
    for rule_id in sorted(set(parse_rows) | set(prog_rows)):
        a, b = parse_rows.get(rule_id), prog_rows.get(rule_id)
        a_txt = f"{a.status.value}({a.n_subjects})" if a else "—"
        b_txt = f"{b.status.value}({b.n_subjects})" if b else "—"
        add("правило", rule_id, a_txt, b_txt,
            _input_delta(wa, wb, _RULE_INPUTS.get(rule_id, ())))

    # --- находки: та же атрибуция по входам правила -----------------------------
    def counts(report: CheckReport) -> Counter:
        got: Counter = Counter()
        for bucket in (report.blocking, report.warnings, report.info):
            for violation in bucket:
                got[f"{violation.rule_id}/{violation.severity.value}"] += 1
        return got

    a_counts, b_counts = counts(parse.report), counts(program.report)
    for key in sorted(set(a_counts) | set(b_counts)):
        rule_id = key.split("/")[0]
        add("находки", key, a_counts.get(key, 0), b_counts.get(key, 0),
            _input_delta(wa, wb, _RULE_INPUTS.get(rule_id, ())))
    return out


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0


def compare_geometry(parse: SpatialModel, program: SpatialModel,
                     *, tol_mm: float = 1.0) -> list[Divergence]:
    """ПОЭЛЕМЕНТНОЕ сравнение геометрии двух путей — не счётчиков, а чисел.

    Возможно потому, что обе модели держат ОДНИ И ТЕ ЖЕ идентификаторы: путь
    программы наследует `source_element_id` того же разбора. Для программы, написанной
    человеком, такого соответствия нет, и тогда работают только агрегаты `compare()`.

    Смещение проёма раскладывается ВДОЛЬ и ПОПЕРЁК оси стены-хозяина отдельно — и это
    не украшение: язык выражает ровно одну из двух степеней свободы (`offset_mm` вдоль
    хозяина), поперечной у него нет. Одно общее «разошлось на 438 мм» смешало бы
    ошибку с границей выразимости; разложенное — показывает, что вдоль оси ошибка
    РОВНО НОЛЬ, а поперёк её и не могло не быть.
    """
    out: list[Divergence] = []

    walls_a = {wall.id: wall for wall in parse.walls}
    walls_b = {wall.id: wall for wall in program.walls}
    common = sorted(set(walls_a) & set(walls_b))
    if common:
        deltas = [max(math.dist(walls_a[i].curve[0], walls_b[i].curve[0]),
                      math.dist(walls_a[i].curve[1], walls_b[i].curve[1]))
                  for i in common]
        exact = sum(1 for value in deltas if value <= tol_mm)
        if exact != len(common):
            out.append(Divergence(
                "геометрия", "ось стены", f"{len(common)} общих",
                f"совпало {exact}, макс {max(deltas):.1f} мм",
                "оси стен читаются обоими путями из одних и тех же чисел — "
                "расхождение здесь означало бы дефект сборки, а не границу языка"))

    for label, a_items, b_items in (("положение двери", parse.doors, program.doors),
                                    ("положение окна", parse.windows, program.windows)):
        a_by_id = {item.id: item for item in a_items}
        b_by_id = {item.id: item for item in b_items}
        shared = sorted(set(a_by_id) & set(b_by_id))
        if not shared:
            continue
        along: list[float] = []
        across: list[float] = []
        for item_id in shared:
            ax, ay = a_by_id[item_id].location
            bx, by = b_by_id[item_id].location
            host = walls_a.get(a_by_id[item_id].host_wall_id or "")
            if host is None:
                continue
            (x0, y0), (x1, y1) = host.curve
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if length <= 0.0:
                continue
            ux, uy = dx / length, dy / length
            vx, vy = ax - bx, ay - by
            along.append(abs(vx * ux + vy * uy))
            across.append(abs(vx * -uy + vy * ux))
        if not along:
            continue
        exact_along = sum(1 for value in along if value <= tol_mm)
        exact_across = sum(1 for value in across if value <= tol_mm)
        out.append(Divergence(
            "геометрия", f"{label} — ВДОЛЬ оси хозяина", f"{len(along)} общих",
            f"совпало {exact_along}, макс {max(along):.2f} мм",
            "`offset_mm` — единственная степень свободы, которую язык здесь "
            "выражает; ноль означает, что восстановление точное"))
        if exact_across != len(across):
            out.append(Divergence(
                "геометрия", f"{label} — ПОПЕРЁК оси хозяина", f"{len(across)} общих",
                f"совпало {exact_across}, медиана расхождения "
                f"{_median([v for v in across if v > tol_mm]):.1f} мм, "
                f"макс {max(across):.1f} мм",
                "поперечного смещения у `create_door`/`create_window` НЕТ ВОВСЕ: "
                "программа кладёт проём на ось хозяина, а разбор несёт точку "
                "экземпляра как её хранит Revit — это граница языка, не ошибка"))

    rooms_a = {room.id: room for room in parse.rooms if room.boundary}
    rooms_b = {room.id: room for room in program.rooms if room.boundary}
    shared_rooms = sorted(set(rooms_a) & set(rooms_b))
    if shared_rooms:
        ious: list[float] = []
        ratios: list[float] = []
        for room_id in shared_rooms:
            pa = _polygon_or_none(rooms_a[room_id].boundary)
            pb = _polygon_or_none(rooms_b[room_id].boundary)
            if pa is None or pb is None:
                continue
            union = pa.union(pb).area
            if union > 0:
                ious.append(pa.intersection(pb).area / union)
            if pa.area > 0:
                ratios.append(pb.area / pa.area)
        if ious:
            out.append(Divergence(
                "геометрия", "контур помещения (IoU)",
                f"{len(rooms_a)} с контуром",
                f"{len(shared_rooms)} общих, IoU медиана {_median(ious):.3f}, "
                f"площадь Б/А медиана {_median(ratios):.3f}",
                "разбор несёт контур, вернувшийся из Revit; программа складывает "
                "его планарным разбиением осевых линий стен — совпадение показывает, "
                "насколько разбиение воспроизводит границу, а не насколько их много"))
    return out


def render_comparison(parse: DesignVerdict, program: DesignVerdict,
                      divergences: Sequence[Divergence]) -> str:
    """Таблица ворот. Совпало — путь от программы обоснован; разошлось — вот карта."""
    lines = [
        f"═══ ВОРОТА: одно здание, два пути — {parse.building_id} ═══",
        f"путь А (разбор):   {_VERDICT_RU.get(parse.verdict, parse.verdict)}",
        f"путь Б (программа): {_VERDICT_RU.get(program.verdict, program.verdict)}",
        "",
    ]
    if not divergences:
        lines.append("РАСХОЖДЕНИЙ НЕТ.")
        return "\n".join(lines)
    width = max(len(d.subject) for d in divergences)
    lines.append(f"расхождений: {len(divergences)}")
    lines.append("")
    current = ""
    for item in divergences:
        if item.kind != current:
            current = item.kind
            lines.append(f"— {current} —")
        lines.append(f"  {item.subject:<{width}}  А={item.parse:<22} "
                     f"Б={item.program:<22}")
        lines.append(f"  {'':<{width}}  причина: {item.cause}")
    return "\n".join(lines)


__all__ = [
    "BRIEF_VERDICT_CAP",
    "DESIGN_STAGE",
    "DESIGN_STAGE_THRESHOLDS",
    "PROGRAM_SHAPE",
    "BUNDLE_CONTRACT",
    "BuildNote",
    "BuildWitness",
    "BundleContractError",
    "VerdictInputError",
    "DesignCheckUnavailable",
    "DesignVerdict",
    "Divergence",
    "ModelSource",
    "OUT_OF_SCOPE",
    "OutOfScope",
    "PARTITION_CLOSE_TOL_MM",
    "PROGRAM_NOT_BUILDABLE",
    "ProgramNotBuildableError",
    "ProgramShapeError",
    "Verdict",
    "check_design",
    # НАРУЖНАЯ дверь вердикта: операции KIR, то есть выход песочницы.
    "check_ops",
    "spatial_model_from_ops",
    # Та же дверь, но ЕДИНИЦА — здание: пачка программ (тело + лестницы).
    "check_bundle",
    "spatial_model_from_bundle",
    "design_stage_profile",
    "compare",
    "compare_geometry",
    "format_check_report",
    "render_comparison",
    "render_verdict",
    "render_verdict_brief",
    "verdict_headline",
    "verdict_headline_text",
    "spatial_model_from_l0",
    # ВНУТРЕННЯЯ форма декомпилятора (узлы L1). Наружу идут `*_from_ops`.
    "spatial_model_from_program",
]
