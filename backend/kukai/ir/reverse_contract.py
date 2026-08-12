"""Exhaustive typed contract between KIR forward and reverse directions.

The forward registry answers what can be executed.  A snapshot cannot invert
every execution: some final-state elements can be lifted to the same op, some
are reconstructed through simpler ops, and history/external artifacts are not
recoverable from a Revit document at all.  Before this manifest those outcomes
lived in unrelated lifter branches and prose; adding a write op required no
machine-readable reverse decision.

``REVERSE_CONTRACTS`` is exhaustive over every write op in ``spec.OPS``.  It
does not claim more than the reverse path proves: ``DIRECT`` means the lifter
may emit the same op for the supported/captured subset; every unsupported
source element remains a typed atom.  Other modes explicitly name why no such
same-op inverse exists and, where applicable, which simpler ops represent the
current state instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from kukai.ir import spec


REVERSE_CONTRACT_SCHEMA = "kir-reverse-contract/1"


class ReverseContractError(ValueError):
    """The reverse path attempted an operation outside its declared surface."""


class ReverseMode(str, Enum):
    DIRECT = "direct"
    CAPTURE_GAP = "capture_gap"
    # ЧТЕНИЕ ПРИНОСИТ ВСЁ, ЛИФТЕРА НЕТ (волна захвата хозяина, 09.08.2026).
    #
    # Заведено потому, что `capture_gap` стал ЛОЖЬЮ ровно для одной записи, а
    # не ради полноты словаря. Пока `WallFoundation.WallId` не читался,
    # «пробел захвата» был точен. Теперь читается — и оставить прежний режим
    # значило бы послать следующего чинить чтение, которое уже починено.
    # Разница адресная, та же, которой этот дом уже развёл `no_lifter` и
    # `source_contract_gap`: один режим отправляет работать в ЗАХВАТ, другой —
    # в ЛИФТЕР, и манифест существует ровно затем, чтобы этот адрес не врал.
    #
    # Гарантия у такой записи всё равно NONE: лифтера нет, значит подъёма нет.
    # Отличается она от `capture_gap` не силой обещания, а тем, ЧТО именно
    # осталось сделать.
    LIFTER_GAP = "lifter_gap"
    DECOMPOSED = "decomposed"
    COMPOSED = "composed"
    STATE_TRANSITION = "state_transition"
    PINNED_EXISTING = "pinned_existing"
    EXTERNAL_SOURCE = "external_source"


class ReverseGuarantee(str, Enum):
    FORM_EXACT = "form_exact"
    BOUNDED = "bounded"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ReverseContract:
    op_name: str
    mode: ReverseMode
    guarantee: ReverseGuarantee
    reason: str
    sources: tuple[str, ...] = ()
    entrypoints: tuple[str, ...] = ()
    representation_ops: tuple[str, ...] = ()
    limitation: str = ""
    #: ХРАПОВИК ПРОБЕЛОВ ЗАХВАТА (09.08.2026, `record_ratchet`). Только
    #: `capture_gap` — и это не экономия, а разница по сути: `direct`,
    #: `decomposed`, `state_transition`, `external_source` описывают, чем
    #: обратный ход ЯВЛЯЕТСЯ, а `capture_gap` — чего он ПОКА не умеет. Первое
    #: не устаревает, второе устаревает молча ровно в тот день, когда волна
    #: захвата начинает читать названное поле, и никто не приходит стереть
    #: строку. Дата решения и срок пересмотра стоят здесь затем, чтобы этот
    #: день кто-то заметил.
    decided_on: str = ""
    due: str = ""

    def __post_init__(self) -> None:
        if self.op_name not in spec.OPS:
            raise ValueError(f"unknown forward op {self.op_name!r}")
        if spec.OPS[self.op_name].family not in spec.WRITE_FAMILIES:
            raise ValueError(f"reverse contract on read op {self.op_name!r}")
        if not isinstance(self.mode, ReverseMode):
            raise TypeError("reverse mode must be typed")
        if not isinstance(self.guarantee, ReverseGuarantee):
            raise TypeError("reverse guarantee must be typed")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reverse contract needs a reason")
        for label, values in (
            ("sources", self.sources),
            ("entrypoints", self.entrypoints),
            ("representation_ops", self.representation_ops),
        ):
            if not isinstance(values, tuple):
                raise TypeError(f"{label} must be an immutable tuple")
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"{label} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{label} contains duplicates")
        if self.mode is ReverseMode.CAPTURE_GAP:
            # Форма проверяется ПРИ ИМПОРТЕ: пробел захвата без дня, в который
            # кто-то обязан ответить, — это «когда-нибудь», а не решение.
            for label, value in (("decided_on", self.decided_on),
                                 ("due", self.due)):
                try:
                    _date.fromisoformat(value)
                except ValueError:
                    raise ValueError(
                        f"capture_gap {self.op_name}: {label}={value!r} — не "
                        f"ISO-дата; пробел захвата обязан нести дату решения и "
                        f"срок пересмотра (kukai/ir/record_ratchet.py)"
                    ) from None
            if _date.fromisoformat(self.due) < _date.fromisoformat(
                    self.decided_on):
                raise ValueError(
                    f"capture_gap {self.op_name}: срок {self.due} раньше "
                    f"самого решения {self.decided_on}")
        elif self.decided_on or self.due:
            raise ValueError(
                f"{self.op_name}: дату и срок несёт только capture_gap — "
                f"остальные моды описывают, чем обратный ход ЯВЛЯЕТСЯ, а не "
                f"чего он пока не умеет")
        if self.mode is ReverseMode.DIRECT:
            if not self.entrypoints:
                raise ValueError("direct reverse contract needs an entrypoint")
            if self.guarantee is ReverseGuarantee.NONE:
                raise ValueError("direct reverse contract needs a guarantee")
        elif self.mode is ReverseMode.COMPOSED:
            if not self.entrypoints:
                raise ValueError("composed reverse contract needs an entrypoint")
        elif self.entrypoints:
            raise ValueError(
                "only direct/composed contracts declare emitting entrypoints")
        if (self.mode in (ReverseMode.DECOMPOSED, ReverseMode.COMPOSED)
                and not self.representation_ops):
            raise ValueError(
                f"{self.mode.value} contract needs representation ops")
        for representation in self.representation_ops:
            if representation not in spec.OPS:
                raise ValueError(
                    f"unknown representation op {representation!r}")
            if spec.OPS[representation].family not in spec.WRITE_FAMILIES:
                raise ValueError(
                    f"reverse representation is not a write op: "
                    f"{representation!r}")

    @property
    def direct_same_op_lift(self) -> bool:
        return self.mode is ReverseMode.DIRECT

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op_name,
            "mode": self.mode.value,
            "guarantee": self.guarantee.value,
            "direct_same_op_lift": self.direct_same_op_lift,
            "reason": self.reason,
            "sources": list(self.sources),
            "entrypoints": list(self.entrypoints),
            "representation_ops": list(self.representation_ops),
            "limitation": self.limitation,
            "decided_on": self.decided_on,
            "due": self.due,
        }


def _direct(
    op_name: str,
    *entrypoints: str,
    sources: tuple[str, ...],
    guarantee: ReverseGuarantee = ReverseGuarantee.FORM_EXACT,
    limitation: str = "",
) -> ReverseContract:
    return ReverseContract(
        op_name=op_name,
        mode=ReverseMode.DIRECT,
        guarantee=guarantee,
        reason=("captured current-state facts can produce the same typed op; "
                "unsupported signatures remain atoms"),
        sources=sources,
        entrypoints=tuple(entrypoints),
        limitation=limitation,
    )


_CONTRACTS = {
    # Same-op lift surface (23/35 write ops). These are subset guarantees: the
    # named entrypoint emits only after its own capture/shape checks pass.
    "create_wall": _direct(
        "create_wall", "_lift_wall", sources=("L0:OST_Walls", "side:wall_curve")),
    "create_floor": _direct(
        "create_floor", "_lift_floor", sources=("L0:OST_Floors", "side:sketch")),
    "create_floor_by_contour": _direct(
        "create_floor_by_contour", "_lift_floor_by_contour",
        sources=("L0:OST_Floors", "side:sketch")),
    "create_roof": _direct(
        "create_roof", "_lift_roof", sources=("L0:OST_Roofs", "side:sketch")),
    # wave/datums (09.08.2026). ПОЛОВИНА входа уже читается, и это ЗАМЕР, а не
    # оценка: `sketch_extract.__ExtrusionRoofLoops` зовёт
    # `ExtrusionRoof.GetProfile()` и кладёт профиль в тот же индекс, что и у
    # контурной кровли. Вторая половина не читается ВОВСЕ: ни
    # `EXTRUSION_START_PARAM`, ни `EXTRUSION_END_PARAM`, ни `ReferencePlane`
    # не встречаются НИ РАЗУ во всём `kukai/ir/decompile/` (grep, 09.08 — ноль
    # вхождений). Без них неизвестны ни глубина выдавливания, ни плоскость, в
    # которой лежит профиль, то есть три из семи входов опа.
    #
    # ПОЧЕМУ ЭТО НЕ DECOMPOSED. Заявить, что состояние представимо контурной
    # кровлей, значило бы обещать перестройку формой ДРУГОГО класса: у
    # выдавленной кровли профиль ВЕРТИКАЛЬНЫЙ и открытый, и его проекция на
    # план — отрезок нулевой площади, а не контур. Отказ честнее подмены.
    "create_extrusion_roof": ReverseContract(
        "create_extrusion_roof", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "the profile IS captured (sketch_extract calls "
        "ExtrusionRoof.GetProfile) but the extrusion range and the work "
        "plane are not: EXTRUSION_START_PARAM / EXTRUSION_END_PARAM / "
        "ReferencePlane appear nowhere in decompile/",
        sources=("L0:OST_Roofs", "side:sketch"),
        limitation=("capture must start reading the extrusion range and the "
                    "roof's work plane before a lifter is legal; until then "
                    "such a roof is a typed atom and is NEVER re-emitted as "
                    "a footprint roof — its profile is vertical and open, so "
                    "its plan projection has zero area"),
        decided_on="2026-08-09", due="2026-09-08"),
    "create_column": _direct(
        "create_column", "_lift_column",
        sources=("L0:OST_Columns", "L0:OST_StructuralColumns")),
    "create_beam": _direct(
        "create_beam", "_lift_beam", sources=("L0:OST_StructuralFraming",)),
    "create_foundation": _direct(
        "create_foundation", "_lift_foundation",
        sources=("L0:OST_StructuralFoundation", "side:sketch")),
    # wave/wall-foundation (09.08.2026). Операция ЕСТЬ, обратного хода НЕТ, и
    # это заявлено ЗДЕСЬ, а не подразумевается умолчанием. Причина ровно одна
    # и она про ЗАХВАТ, а не про лифтер: единственный обязательный вход
    # ленточного фундамента — ЕГО СТЕНА (WallFoundation.WallId), а L0 такой
    # связи не несёт вовсе. Категория при этом читается: OST_StructuralFoundation
    # уже в таблице извлечения, значит элемент будет ПРОЧИТАН и станет честным
    # атомом, а не пропадёт молча.
    #
    # ЗАМЕР, А НЕ ОЦЕНКА: ни в одном сохранённом на диске разборе нет ни
    # одного WallFoundation (grep по L0.jsonl всех разборов, 09.08), поэтому
    # объявить DIRECT значило бы обещать подъём, которого никто никогда не
    # видел. Закрывает пробел одна строка захвата (WallId), а не новый лифтер.
    # ПЕРЕВЕДЁН ИЗ capture_gap В lifter_gap 09.08.2026 — по ЗАМЕРУ, а не по
    # желанию, и в ту же ночь, когда прежняя запись была написана.
    #
    # Прежний текст обещал: «пока захват не читает WallFoundation.WallId,
    # такой элемент — типизованный атом, НИКОГДА не переизлучаемый молча как
    # столбчатый». Обещание было ВЕРНО и НЕ ОБЕСПЕЧЕНО: `_lift_foundation` при
    # `geom_kind is POINT` выдавал `create_foundation(variety="isolated")` без
    # единой проверки на класс элемента, а держалось всё на том, что у
    # `WallFoundation` нет `LocationPoint`. То есть на ПОВЕДЕНИИ REVIT, а не
    # на нашем инварианте — ровно тот класс, что тест, проходящий по фикстуре.
    #
    # Что изменилось. Захват читает хозяина у системных элементов одной
    # таблицей (`extract._HOST_READERS`) и пишет рядом с `host_id` ещё и
    # `host_source` — КЛАСС отношения; `WallFoundation.WallId` замерен
    # компиляцией на :52412 против настоящих сборок как 6/6. Лифтер теперь
    # отказывает по этому классу ДО разбора геометрии, поэтому обещание держит
    # КОД, а не совпадение (`lift._lift_foundation`,
    # `decompile/tests/test_host_capture_system_elements.py`).
    #
    # Почему НЕ direct: чтения теперь хватает (стена + тип), но лифтера нет, и
    # писать его вслепую нельзя — ни в одном из 67 сохранённых на диске
    # разборов нет НИ ОДНОГО WallFoundation (замер 09.08 по L0.jsonl всего
    # корпуса; всего 5 элементов OST_StructuralFoundation, у всех host пуст).
    # Объявить DIRECT значило бы обещать подъём, которого никто не видел.
    # wave/space (10.08.2026). Режим LIFTER_GAP, а НЕ CAPTURE_GAP, и это
    # адресный замер, а не оттенок: «пробел захвата» послал бы следующего
    # чинить чтение, которое уже работает. Извлечение читает
    # OST_MEPSpaces с самого заведения таблицы категорий
    # (`extract._CATEGORY_SPECS`), и на корпусе это подтверждено:
    # 44 разбора из 76 вообще смотрели эту категорию, 6 нашли элементы,
    # 169 пространств ТРЁХ зданий прочитаны с `expected == extracted` и
    # `state: complete`. Чего нет — строки в таблице кандидатов лифтера
    # (`lift.py` знает "OST_Rooms" и не знает "OST_MEPSpaces", grep 10.08),
    # поэтому все 126 элементов сегодня становятся атомами «операции не
    # существует» — и это перестало быть правдой ровно сейчас.
    #
    # ЛИФТЕР НЕ НАПИСАН ЭТОЙ ВОЛНОЙ НАМЕРЕННО: `decompile/**` — чужая
    # территория сессии. Гарантия NONE, потому что подъёма нет; режим
    # называет АДРЕС работы, а не её объём.
    #
    # ЧЕСТНЫЙ ОСТАТОК, КОТОРЫЙ БУДУЩИЙ ЛИФТЕР ОБЯЗАН ЗНАТЬ: в L0 у всех
    # 169 пространств `params` ПУСТ, а `type_id`/`type_name` — пустые
    # строки. То есть имени, номера и типа источник не несёт вовсе, и
    # (число исправлено 11.08: имя каталога было принято за имя
    # документа — `snowdon_plumb_v5` несёт `Snowdon Towers Sample
    # Architectural`, третье здание, а не пятую ревизию сантехники)
    # подъём в сегодняшнюю сигнатуру (точка + уровень) теряет ровно
    # ничего — но и обогатить оп из этого чтения нечем.
    "create_space": ReverseContract(
        "create_space", ReverseMode.LIFTER_GAP, ReverseGuarantee.NONE,
        "capture reads OST_MEPSpaces already (169 spaces over 3 buildings, "
        "expected == extracted, state complete); no lifter candidate maps "
        "that category to an op, so every space is still a typed atom",
        sources=("L0:OST_MEPSpaces",),
        limitation=("the source carries no name, number or type for a "
                    "space (params empty and type_id blank on all 126), "
                    "so a lifter can restore the point and the level and "
                    "nothing else")),
    "create_wall_foundation": ReverseContract(
        "create_wall_foundation", ReverseMode.LIFTER_GAP,
        ReverseGuarantee.NONE,
        "capture now reads WallFoundation.WallId (6/6) and records the class "
        "in host_source; no lifter emits the op yet, and no stored decompile "
        "contains a single WallFoundation to write one against",
        sources=("L0:OST_StructuralFoundation",),
        limitation=("such an element is a typed atom, never a silently "
                    "re-emitted isolated footing — enforced by "
                    "lift._lift_foundation on host_source, not by the absence "
                    "of a LocationPoint")),
    # wave/framing (09.08.2026). У обеих операций обратного хода НЕТ, и обе
    # причины — про ЗАХВАТ, а не про ненаписанный лифтер.
    #
    # Балочная система: L0 читает OST_StructuralFraming, то есть видит
    # ПОРОЖДЁННЫЕ балки, а не породившую их систему. Поднять их поштучно
    # create_beam'ом можно было бы — и это был бы ХУДШИЙ ответ, чем атом:
    # балочная система перестала бы существовать как объект, а её раскладка
    # (LayoutRule) выродилась бы в пачку зафиксированных координат, которую
    # нельзя перестроить. `BeamSystem.BeamBelongsTo(FamilyInstance)` даёт
    # ровно ту связь, которой захвату не хватает.
    "create_beam_system": ReverseContract(
        "create_beam_system", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 carries the generated beams, not the system that laid them, and "
        "no profile/direction/layout-rule record exists to lift",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_StructuralFraming",),
        limitation=("capture must read BeamSystem.Profile/Direction/Level and "
                    "BeamBelongsTo before a lifter is legal; until then the "
                    "system is a typed atom and its beams stay individual "
                    "create_beam leaves — never a silently re-derived layout")),
    # Ферма: та же форма пробела и та же честность. Стержни фермы читаются
    # как обычный несущий каркас, сама ферма — нет: ни базовой кривой, ни
    # плоскости эскиза, ни `Truss.Members` L0 не несёт. И снова поштучный
    # подъём стержней был бы не «частичным успехом», а потерей объекта.
    "create_truss": ReverseContract(
        "create_truss", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 carries no truss base curve, no sketch plane and no Members set — "
        "only the members themselves, which are not the truss",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_StructuralFraming",),
        limitation=("capture must read the truss LocationCurve, its "
                    "SketchPlane and TrussType before a lifter is legal; "
                    "until then the truss is a typed atom, never a pile of "
                    "loose beams pretending to be one")),
    # wave/reinforcement (10.08.2026). Пробел именно ЗАХВАТА, и он тотальный:
    # категории OST_AreaRein нет в таблице извлечения вовсе (grep по
    # `extract._CATEGORY_SPECS`), поэтому конвейер армирования не видит ни
    # одного элемента — ни системы, ни стержней. Это подтверждено и с другой
    # стороны: в 38 сохранённых разборах с переписью НОЛЬ элементов
    # OST_AreaRein, OST_PathRein, OST_Rebar, OST_FabricAreas и
    # OST_FabricReinforcement (замер 10.08 по census-записям всего корпуса).
    # Объявить что-либо сильнее значило бы обещать подъём того, чего чтение
    # даже не встречало.
    "create_area_reinforcement": ReverseContract(
        "create_area_reinforcement", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "the extraction table carries no OST_AreaRein category at all, so L0 "
        "never sees an area reinforcement system, its host, its major "
        "direction or its bar type — and no stored decompile contains one to "
        "write a lifter against",
        decided_on="2026-08-10", due="2026-09-09",
        sources=(),
        limitation=("capture must read AreaReinforcement.GetHostId/Direction/"
                    "GetTypeId and the bars' own type before a lifter is "
                    "legal; until then reinforcement is simply absent from "
                    "the reverse direction — never silently re-derived from "
                    "the bars that happen to be visible")),
    "create_door": _direct(
        "create_door", "_lift_door", sources=("L0:OST_Doors",)),
    "create_window": _direct(
        "create_window", "_lift_window", sources=("L0:OST_Windows",)),
    "create_room": _direct(
        "create_room", "_lift_room", sources=("L0:OST_Rooms", "L0:rooms")),
    "create_text": _direct(
        "create_text", "_lift_text", sources=("L0:OST_TextNotes", "side:annotation")),
    "create_tag": _direct(
        "create_tag", "_lift_tag", sources=("L0:tag-categories", "side:tag")),
    "create_level": _direct(
        "create_level", "_lift_level", sources=("L0:OST_Levels", "L0:levels")),
    "create_grid": _direct(
        "create_grid", "_lift_grid", sources=("L0:OST_Grids", "L0:grids")),
    # wave/datums (09.08.2026). Оси цепи ЧИТАЮТСЯ — каждая из них обычный
    # Grid и поднимается как `create_grid`. Не читается ПРИНАДЛЕЖНОСТЬ:
    # `MultiSegmentGrid.GetMultiSegementGridId(Grid)` не встречается ни в
    # одном файле пакета (grep по kukai/, 09.08 — ноль вхождений вне
    # forward-эмиссии этой волны), значит из снапшота нельзя узнать, что три
    # оси были одной цепью. Мода DECOMPOSED, а не CAPTURE_GAP: текущее
    # состояние ПРЕДСТАВИМО — тремя `create_grid`, — и здание перестраивается
    # верным по геометрии, теряя только группировку.
    "create_multi_segment_grid": ReverseContract(
        "create_multi_segment_grid", ReverseMode.DECOMPOSED,
        ReverseGuarantee.BOUNDED,
        "each segment IS a Grid and lifts as create_grid; only the chain "
        "MEMBERSHIP is unrecoverable — L0 never reads "
        "MultiSegmentGrid.GetMultiSegementGridId",
        sources=("L0:OST_Grids", "L0:grids"),
        representation_ops=("create_grid",),
        limitation=("the rebuilt document has the same axes as separate "
                    "grids, not one chain; capture must start reading the "
                    "owning MultiSegmentGrid id before a same-op lift is "
                    "legal")),
    "create_pipe": _direct(
        "create_pipe", "_lift_pipe", sources=("L0:OST_PipeCurves", "side:mep_system")),
    "create_duct": _direct(
        "create_duct", "_lift_duct", sources=("L0:OST_DuctCurves", "side:mep_system")),
    "create_cable_tray": _direct(
        "create_cable_tray", "_lift_cable_tray", sources=("L0:OST_CableTray",)),
    # wave/mep-electrical (2026-08-09). Короб инвертируется ПОЛНОСТЬЮ: в L0
    # его строка неотличима по форме от лотка (линейный MEPCurve, те же концы,
    # тот же уровень, тот же тип из каталога), и лифтер написан этой же
    # волной. Прямой оп не берёт диаметра, поэтому и терять на обратном ходе
    # нечего — форма замкнута.
    "create_conduit": _direct(
        "create_conduit", "_lift_conduit", sources=("L0:OST_Conduit",)),
    # wave/analysis (09.08.2026). Три нагрузки и путь эвакуации: операции
    # ЕСТЬ, обратного хода НЕТ, и это заявлено ЗДЕСЬ, а не подразумевается
    # умолчанием. Причина у всех четырёх одна и она про ЗАХВАТ: ни
    # OST_PointLoads / OST_LineLoads / OST_AreaLoads, ни OST_PathOfTravelLines
    # не входят в таблицу извлечения L0 вовсе, то есть чтение до этих
    # элементов не доходит. Разница между «стадия отказала на элементе» и
    # «стадия о нём не говорила» уже стоила этому пакету одного неверного
    # диагноза: absent index and empty index are different facts,
    # и повторять его умолчанием нельзя.
    #
    # ЧЕГО ИМЕННО НЕ ХВАТАЕТ, названо поимённо, чтобы следующая волна не
    # начинала с переписи: у нагрузок это `ForceVector`/`MomentVector`,
    # `LoadCaseId` и рабочая плоскость (по концам и типу нагрузку не
    # восстановить: те же концы дала бы любая нагрузка любой величины); у
    # пути эвакуации — `PathStart`/`PathEnd` и `OwnerViewId`. Пока их нет,
    # такой элемент обязан становиться типизированным атомом, а не молча
    # пропадать и не подменяться чем-то похожим.
    "create_point_load": ReverseContract(
        "create_point_load", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "L0 does not read structural loads at all: OST_PointLoads is outside "
        "the extraction table, so no record of the force vector, the moment "
        "vector or the load case exists to lift",
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("capture must start reading PointLoad.ForceVector/"
                    "MomentVector/Point and LoadBase.LoadCaseId before a "
                    "lifter is legal; a load's position alone says nothing "
                    "about the load")),
    "create_line_load": ReverseContract(
        "create_line_load", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "L0 does not read structural loads at all: OST_LineLoads is outside "
        "the extraction table, so neither the distributed force nor the load "
        "case is captured",
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("capture must start reading LineLoad.StartPoint/EndPoint/"
                    "ForceVector1 and LoadBase.LoadCaseId before a lifter is "
                    "legal; two endpoints alone describe a line, not a load")),
    "create_area_load": ReverseContract(
        "create_area_load", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "L0 does not read structural loads at all: OST_AreaLoads is outside "
        "the extraction table, and an area load's boundary lives in "
        "AreaLoad.GetLoops which capture never asks for",
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("capture must start reading AreaLoad.GetLoops/"
                    "ForceVector1 and LoadBase.LoadCaseId before a lifter is "
                    "legal; a bounding box would not determine the loops")),
    "create_path_of_travel": ReverseContract(
        "create_path_of_travel", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "L0 does not read path-of-travel lines, and the element's own "
        "geometry is DERIVED by Revit from the view's obstacles — only its "
        "two endpoints and its owner view are authored input",
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("capture must start reading PathOfTravel.PathStart/"
                    "PathEnd and OwnerViewId before a lifter is legal; "
                    "lifting the computed curves would re-author a route as "
                    "if it had been drawn by hand")),
    "create_stairs": _direct(
        "create_stairs", "_lift_stairs", sources=("L0:OST_Stairs", "side:stairs_path")),
    # ВОЛНА ЛЕСТНИЦ (10.08.2026). Площадка не читается НИКАК, и это пробел
    # ЗАХВАТА, а не лифтера: категория OST_StairsLandings отсутствует в
    # таблице извлечения, строка `StairsLanding` не встречается ни в одном
    # файле `decompile/` (grep 10.08), то есть читать нечего. `_lift_stairs`
    # поднимает ЛЕСТНИЦУ по её маршу и о компонентах-площадках не знает
    # вовсе, поэтому разобранное здание сегодня теряет каждую площадку
    # молча — ровно тот факт, который эта запись обязана держать на виду.
    #
    # ПОЧЕМУ НЕ DECOMPOSED. Представить площадку набором уже существующих
    # опов нечем: перекрытие по контуру дало бы ПЛИТУ, а не компонент
    # лестницы, — другой элемент, другая категория, другое поведение при
    # правке марша. Ложное представление здесь хуже честного пробела.
    "create_stairs_landing": ReverseContract(
        "create_stairs_landing", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 reads no StairsLanding at all — OST_StairsLandings is absent from "
        "the extraction table and the class is named nowhere in decompile/",
        sources=("L0:OST_Stairs",),
        limitation=("capture must start reading StairsLanding, its "
                    "GetFootprintBoundary and its BaseElevation before a "
                    "lifter is legal; until then every landing of a "
                    "decompiled building is lost silently, and the stairs "
                    "lifts as its run alone"),
        decided_on="2026-08-10", due="2026-09-09"),
    # 09.08.2026: у потолка ДВЕ ветки подъёма, и обе названы здесь поимённо.
    # `_lift_ceiling_by_contour` появился в тот же день, что и второй вход
    # формы прямого опа (`contour` рода `region`), и берёт ровно то, что
    # ломаная выразить не может, — дугу в плане. Захват при этом не менялся:
    # род сегмента и середина дуги лежат в боковом индексе эскизов с 29.07,
    # то есть это был единственный из трёх случаев, когда не хватало ИМЕННО
    # лифтера. Гарантия осталась BOUNDED, и это не забывчивость: контур
    # закрывает ПЛАН, а незакрытым остаётся уклон — третья координата, и её
    # в захвате по-прежнему нет.
    # wave/datums (09.08.2026). Многоэтажная лестница не читается НИКАК:
    # строка `MultistoryStairs` не встречается ни в одном файле пакета вне
    # прямой эмиссии этой волны (grep по kukai/, 09.08), а её категория
    # (OST_MultistoryStairs) отсутствует в таблице извлечения. То есть
    # проблема не в лифтере — читать нечего.
    #
    # ПОЧЕМУ НЕ DECOMPOSED ЧЕРЕЗ N ЛЕСТНИЦ. Составляющие марши в модели ЕСТЬ
    # и поднимаются как `create_stairs` — но обещать это здесь было бы
    # неправдой ДВАЖДЫ: закон пачки (`spec.SOLO_OPS`) запрещает нескольким
    # `create_stairs` ехать одной программой, поэтому «представление» вышло
    # бы не программой, а пачкой из N программ; и связь между маршами при
    # этом рвётся, то есть перестроенное здание теряет ровно то свойство,
    # ради которого оп заведён.
    "create_multistory_stairs": ReverseContract(
        "create_multistory_stairs", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 reads no MultistoryStairs at all — the category is absent from "
        "the extraction table and the class is named nowhere in decompile/",
        sources=("L0:OST_Stairs",),
        limitation=("capture must start reading MultistoryStairs and its "
                    "GetAllConnectedLevels before a lifter is legal; the "
                    "member runs themselves still lift as individual "
                    "create_stairs, which loses the multistory relation and "
                    "cannot be one program (SOLO_OPS)"),
        decided_on="2026-08-09", due="2026-09-08"),
    "create_ceiling": _direct(
        "create_ceiling", "_lift_ceiling", "_lift_ceiling_by_contour",
        sources=("L0:OST_Ceilings", "side:sketch"),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("frozen capture has no ceiling slope arrow; a captured "
                    "profile proves plan form but not native slope semantics, "
                    "and a sloped ceiling therefore lifts flat")),
    "create_directshape": _direct(
        "create_directshape", "_lift_directshape",
        sources=("L0:DirectShape", "geometry:mesh")),
    # wave/solid (09.08.2026). Обратного хода НЕТ, и причина про ЗАХВАТ, а не
    # про лифтер, — и она глубже, чем у ленточного фундамента.
    #
    # Тело в модели хранится B-rep'ом: гранями, рёбрами, поверхностями. Того,
    # ЧЕМ его построили — «прямоугольник 3×4 выдавлен на 2» против «тот же
    # объём вытянут иначе», — в построенном DirectShape нет НИГДЕ: обе
    # программы дают побайтово одинаковый элемент. Обратный ход поэтому не
    # «ещё не написан», он требует РАСПОЗНАВАНИЯ признаков (все боковые грани
    # плоские и вертикальные, два плоских торца с равными контурами ⇒ призма),
    # то есть отдельной задачи со своим свидетелем. Заявить DIRECT значило бы
    # обещать восстановление намерения из следа, который намерения не хранит.
    #
    # Элемент при этом НЕ ПРОПАДАЕТ: `_lift_directshape` читает те же
    # DirectShape и отдаёт их мешем (тесселяция граней) — форма сохранится,
    # параметричность нет. Это честная деградация, а не тишина.
    "create_solid_extrusion": ReverseContract(
        "create_solid_extrusion", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "a built DirectShape stores a B-rep, not the profile+height that "
        "authored it; two different programs yield the identical element",
        sources=("L0:DirectShape",),
        # ДАТА И СРОК ДОПИСАНЫ ПРИ СЛИЯНИИ 09.08, И ЭТО НЕ ФОРМАЛЬНОСТЬ.
        # База волны тел предшествует храповику записей, поэтому её строки
        # приехали ПРОСТЫМИ — и импорт отказал, а не промолчал: ровно то
        # поведение, ради которого храповик писался. Дата — день волны, срок —
        # тридцать дней, как у всех девятнадцати остальных пробелов захвата.
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("recovering the op needs SHAPE RECOGNITION over the "
                    "B-rep (planar vertical laterals + two congruent planar "
                    "caps ⇒ prism), which is its own wave with its own "
                    "witness; until then such an element lifts as a mesh "
                    "DirectShape — form kept, parametricity lost, never "
                    "silently dropped")),
    "create_solid_revolve": ReverseContract(
        "create_solid_revolve", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "a built DirectShape stores a B-rep, not the profile+axis+sweep that "
        "authored it",
        sources=("L0:DirectShape",),
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("recognising a solid of revolution additionally needs the "
                    "AXIS recovered from the cylindrical/conical faces; same "
                    "wave, same requirement — until then it lifts as a mesh "
                    "DirectShape")),
    # wave/mass (2026-08-10). ПРОБЕЛ ЗАХВАТА, А НЕ ПРОБЕЛ ЛИФТЕРА, и разница
    # адресная: чтение НЕ приносит всего. `FaceWall` живёт в OST_Walls, то
    # есть в перепись и в извлечение попадает, — но два определяющих поля
    # операции там отсутствуют по построению. Первое: у `FaceWall` НЕТ
    # `LocationCurve` (он не `Wall` — замерено, CS0029 на всех шести), значит
    # обычная строка стены с p0/p1 его описать не может вовсе. Второе:
    # носитель и НОРМАЛЬ ГРАНИ, по которым стена построена, в L0 не
    # захватываются ничем — `HostReference` у стены по грани не читается ни
    # одним полем нынешнего извлечения. Послать следующего в лифтер значило
    # бы послать его чинить то, что не сломано.
    "create_face_wall": ReverseContract(
        "create_face_wall", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 carries no host-face reference and no face normal for a wall "
        "built on a mass face, and a FaceWall has no LocationCurve to "
        "describe it the way an ordinary wall row does",
        sources=("L0:OST_Walls",),
        decided_on="2026-08-10", due="2026-09-09",
        limitation=("recovering the op needs the host mass id AND the model "
                    "normal of the parent face; until capture reads both, "
                    "such a wall lifts as an atom — never silently dropped")),
    "place_family": _direct(
        "place_family", "_lift_family_fallback",
        sources=("side:family_placement",)),
    "set_curtain_panel": _direct(
        "set_curtain_panel", "_lift_curtain_panel",
        sources=("L0:OST_CurtainWallPanels", "side:curtain")),
    "create_curtain_grid_line": _direct(
        "create_curtain_grid_line", "_grid_line_node",
        sources=("side:curtain_grid_line",)),
    # wave/room (2026-08-03). Инверсия ПОСЕГМЕНТНАЯ и потому точная: в L0
    # каждый OST_RoomSeparationLines — один ModelCurve со своими p0/p1 и
    # своим level_id, и лифт даёт ему ломаную ровно из двух точек (закон
    # «один L0-элемент → РОВНО ОДИН L1-узел» не позволил бы сшить соседние
    # линии в одну ломаную, да и сшивать их нечем: общей личности у них нет).
    # Гарантия BOUNDED, а не FORM_EXACT: дуговой разделитель не выражается
    # вовсе (у `path` дугового параметра нет — 14 из 2 313 на K2), а
    # разделитель, чья плоскость смещена от своего уровня, тоже остаётся
    # атомом, потому что смещения нет у самой операции (4 из 2 313).
    "create_room_separator": _direct(
        "create_room_separator", "_lift_room_separator",
        sources=("L0:OST_RoomSeparationLines",),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("an arc separator has no expressible parameter and a "
                    "chord would silently straighten it; a separator whose "
                    "plane is offset from its own level has no offset "
                    "parameter either — both stay typed atoms")),

    # wave/site (2026-08-09). Три операции площадки — CAPTURE_GAP, и это
    # ЗАМЕР, а не осторожность: в таблице категорий извлечения
    # (decompile/extract.py) нет ни OST_Topography, ни OST_Toposolid, ни
    # OST_BuildingPad, ни OST_Site — конвейер их НЕ ЧИТАЕТ вовсе. Объявить
    # DIRECT значило бы обещать подъём, для которого не собирается даже
    # строка L0; манифест существует ровно затем, чтобы такие обещания не
    # протухали молча. Разница между «стадия отказала» и «стадия не
    # говорила» здесь на стороне второго.
    "create_topography": ReverseContract(
        "create_topography", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction reads neither OST_Topography nor OST_Toposolid, so L0 "
        "carries no terrain points at all",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_Topography", "L0:OST_Toposolid"),
        limitation=("capture must start reading TopographySurface.GetPoints() "
                    "(and the toposolid's slab-shape vertices) before a "
                    "lifter is legal — a terrain re-emitted from its bounding "
                    "box would be a different landscape")),
    "create_building_pad": ReverseContract(
        "create_building_pad", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction does not read OST_BuildingPad, and the pad's sketch "
        "boundary is not captured anywhere",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_BuildingPad",),
        limitation=("capture must start reading BuildingPad.GetBoundary() and "
                    "its level before a lifter is legal")),
    # wave/sweep (2026-08-09). Обе операции — CAPTURE_GAP, и это ЗАМЕР тем же
    # способом, что у волны площадки: в таблице категорий извлечения
    # (decompile/extract.py) нет ни OST_Cornices, ни OST_Reveals, ни
    # OST_EdgeSlab — конвейер их НЕ ЧИТАЕТ вовсе. Объявить DIRECT значило бы
    # обещать подъём, для которого не собирается даже строка L0.
    "create_wall_sweep": ReverseContract(
        "create_wall_sweep", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction reads neither OST_Cornices nor OST_Reveals, so L0 carries "
        "no wall sweep at all",
        sources=("L0:OST_Cornices", "L0:OST_Reveals"),
        limitation=("capture must start reading WallSweep.GetHostIds() and "
                    "GetWallSweepInfo().IsVertical before a lifter is legal — "
                    "and note that the sweep's POSITION is unrecoverable by "
                    "construction, because Autodesk documents it as coming "
                    "from the type, not from the call, so a lifted sweep can "
                    "only ever name its host, its type and its orientation"),
        decided_on="2026-08-09", due="2026-09-08"),
    "create_slab_edge": ReverseContract(
        "create_slab_edge", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction does not read OST_EdgeSlab, and the host edges a slab "
        "edge runs along are not captured anywhere",
        sources=("L0:OST_EdgeSlab",),
        limitation=("capture must start reading the host and the swept edges "
                    "(HostedSweep.get_ReferenceCurve over the host's "
                    "perimeter) before a lifter is legal; re-emitting a slab "
                    "edge from its bounding box would put it on the wrong "
                    "edges"),
        decided_on="2026-08-09", due="2026-09-08"),
    "create_site_subregion": ReverseContract(
        "create_site_subregion", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction does not read the site categories, and a sub-region is "
        "indistinguishable from a plain topography surface in L0",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_Topography", "L0:OST_Site"),
        limitation=("capture must start reading "
                    "TopographySurface.IsSiteSubRegion and "
                    "SiteSubRegion.GetBoundary()/HostId; lifting a sub-region "
                    "as a plain surface would silently drop its host")),

    # The op exists, but current frozen capture lacks a mandatory source fact.
    # ЗАПИСЬ ПЕРЕВЕДЕНА ИЗ `capture_gap` В `direct` ВОЛНОЙ РАЗМЕРОВ, и это
    # ровно тот день, ради которого у `capture_gap` заведены `decided_on` и
    # `due` (см. храповик выше: «устаревает молча ровно в тот день, когда
    # волна захвата начинает читать названное поле, и никто не приходит
    # стереть строку»).
    #
    # Прежняя причина называла ДВА недостающих факта — «owner-view basis» и
    # «Dimension.References». Оба теперь читаются стадией `dimension`
    # (`decompile/dimension_extract.py`): базис вида тем же способом, что у
    # марок и примечаний, а `Dimension.References` -> `ReferenceArray` типом,
    # НАЗВАННЫМ компилятором на 2021/2023/2026, а не взятым из документации.
    #
    # ГАРАНТИЯ `BOUNDED`, А НЕ `FORM_EXACT`, И ЭТО ГЛАВНОЕ В ЭТОЙ ЗАПИСИ.
    # `refs` несёт ЭЛЕМЕНТЫ, а `NewDimension` требует ГЕОМЕТРИЧЕСКИХ ссылок;
    # КАКУЮ грань элемента взять, решает обход прямого хода
    # (`authoring._dim_geom_helpers_cs`), а не прочитанное. Значит пересобрать
    # размер МЕЖДУ ТЕМИ ЖЕ ЭЛЕМЕНТАМИ мы обещаем, а совпадение ЧИСЛА — нет:
    # размер до наружной грани стены и до её оси связывают ту же пару
    # элементов. Объявить здесь `FORM_EXACT` значило бы пообещать то, чего ни
    # один offline-замер подтвердить не может, — а мост отключён.
    "create_dimension": _direct(
        "create_dimension", "_lift_dimension",
        guarantee=ReverseGuarantee.BOUNDED,
        sources=("L0:OST_Dimensions", "side:dimension"),
        limitation=(
            "the rebuilt dimension binds the SAME ELEMENTS, but not "
            "necessarily the same FACES of them: Reference geometry is not "
            "captured, and the forward walk picks the face itself, so the "
            "measured VALUE may differ (the forward emitter gates that value "
            "itself). Non-linear shapes (Radial/Angular/...) stay atoms with "
            "unsupported_forward_signature")),
    # 09.08: у углового размера тот же самый разрыв захвата, и он ХУЖЕ на одну
    # величину — кроме вида и References восстановить пришлось бы ещё и дугу
    # (вершина + радиус + пара лучей), которой в замороженной строке L0 1.0 нет
    # ни в каком виде. Объявлено CAPTURE_GAP явно, а не подразумевается: этот
    # манифест затем и существует, чтобы обещание подъёма не протухало молча.
    "create_angular_dimension": ReverseContract(
        "create_angular_dimension", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 has no owner-view basis, Dimension.References or the annotation arc",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_Dimensions",),
        limitation="must extend annotation capture before a lifter is legal"),
    # wave/detail (09.08.2026). CAPTURE_GAP, и это ЗАМЕР по таблице категорий
    # извлечения (decompile/extract.py): ни OST_FilledRegion, ни
    # OST_MaskingRegion в ней НЕТ — конвейер заливок не читает вовсе, так что
    # «стадия отказала» тут даже не наступает, стадии нет. Разрыв к тому же
    # ДВОЙНОЙ: мало прочитать `GetBoundaries()`, надо ещё уметь перевести её
    # кривые в оси вида-владельца (Origin/Right/Up), иначе поднятый контур
    # окажется в мировых XY — то самое смешение пространств, которое прямой
    # ход отказывается выражать.
    "create_filled_region": ReverseContract(
        "create_filled_region", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "extraction reads neither OST_FilledRegion nor OST_MaskingRegion, so "
        "L0 carries no region boundary and no owner-view basis",
        sources=("L0:OST_FilledRegion", "L0:OST_MaskingRegion"),
        # ДАТА И СРОК ДОПИСАНЫ ПРИ СЛИЯНИИ 09.08 — второй раз за вечер и по
        # той же причине: база волны детализации предшествует храповику
        # записей, её `capture_gap` приехал ПРОСТЫМ, и импорт ОТКАЗАЛ, а не
        # промолчал. День волны, срок тридцать дней — как у всех остальных.
        decided_on="2026-08-09", due="2026-09-08",
        limitation=("capture must start reading FilledRegion.GetBoundaries() "
                    "AND the owner view's Origin/Right/Up before a lifter is "
                    "legal — a boundary re-emitted in world XY would be a "
                    "different place on every non-plan view")),
    # wave/opening (03.08.2026). Операция ЕСТЬ, обратного хода НЕТ, и это
    # заявлено здесь, а не подразумевается: замороженная строка L0 1.0 не
    # несёт НИ ОДНОГО обязательного входа проёма — ни Opening.Host (носитель),
    # ни Opening.BoundaryRect/BoundaryCurves (границу). Объявить DIRECT
    # значило бы обещать подъём, которого нет, а этот манифест существует
    # ровно затем, чтобы такие обещания не протухали молча.
    # ПОЛОВИНА ПРИЧИНЫ ЗАКРЫТА 09.08.2026 волной захвата хозяина, и текст
    # приведён в соответствие в тот же час: `Opening.Host` читается (замер
    # компиляцией 6/6, `extract._HOST_READERS`, `host_source="opening"`).
    # Режим остаётся capture_gap, потому что вторая половина входа — ГРАНИЦА
    # проёма (BoundaryRect / BoundaryCurves) — по-прежнему не читается ничем,
    # а без неё лифтер невозможен. Записывать «не несёт ни Opening.Host, ни
    # границы» после того, как первое стало неправдой, значит держать в
    # манифесте ровно то протухание, против которого он и заведён.
    "create_opening": ReverseContract(
        "create_opening", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "capture reads Opening.Host since 09.08 (host_source='opening'), but "
        "L0 still carries no opening boundary (BoundaryRect / BoundaryCurves)",
        sources=("L0:OST_SWallRectOpening", "L0:OST_FloorOpening",
                 "L0:OST_RoofOpening"),
        limitation=("capture must still read the boundary before a lifter is "
                    "legal; the shaft variety is additionally outside the "
                    "forward op itself"),
        decided_on="2026-08-09", due="2026-09-08"),
    # 03.08.2026: ПЕРЕВЕДЁН ИЗ capture_gap В direct, и повод — замер, а не
    # желание. Захват ограждений (``sketch_extract.RailingPathRecord``:
    # Railing.GetPath, HasHost/HostId, STAIRS_RAILING_BASE_LEVEL_PARAM) поехал
    # ещё 29.07 и снимает данные в проде; k2_ar_rd_v9 несёт 31 строку захвата,
    # из них 28 свободных ограждений с путём и базовым уровнем. То есть
    # прежняя формулировка «L0 has neither a railing path nor hosted placement
    # position» перестала быть правдой в первой своей половине — а манифест
    # существует ровно затем, чтобы такие утверждения не протухали молча.
    #
    # ВТОРАЯ ПОЛОВИНА ОСТАЛАСЬ ПРАВДОЙ ЦЕЛИКОМ, поэтому гарантия BOUNDED, а не
    # FORM_EXACT: ЛЕСТНИЧНОЕ ограждение не инвертируется вовсе — позиции
    # (Treads/Stringer) в API нет геттера ни на одной из шести версий.
    "create_railing": _direct(
        "create_railing", "_lift_railing",
        sources=("L0:OST_Railings", "L0:OST_StairsRailing", "side:sketch"),
        guarantee=ReverseGuarantee.BOUNDED,
        limitation=("only variety=path is inverted; a hosted railing stays an "
                    "atom because RailingPlacementPosition has no getter on "
                    "any shipped version, and re-emitting it as a free path "
                    "railing would silently drop its host")),

    # wave/mep-electrical (2026-08-09). Четыре операции ЕСТЬ, обратного хода
    # НЕТ, и причина у каждой пары своя — заявлена здесь, а не подразумевается.
    #
    # ЗАГОТОВКИ. Захват несёт трубу и воздуховод давно, но НЕ несёт бита
    # `IsPlaceholder`: в строке L0 заготовка и настоящий участок выглядят
    # одинаково. Следствие названо прямо, потому что оно уже действует:
    # заготовка в чужой модели СЕГОДНЯ поднимается как `create_pipe` /
    # `create_duct`, то есть круг пересобирает НЕ ЗАГОТОВКУ, а полноценный
    # участок. Это ограничение захвата, а не лифтера, и чинится оно одним
    # полем в L0 — но полем, которого там нет.
    "create_pipe_placeholder": ReverseContract(
        "create_pipe_placeholder", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 carries no Pipe.IsPlaceholder bit, so a placeholder run is "
        "indistinguishable from a real one in the capture",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_PipeCurves",),
        representation_ops=("create_pipe",),
        limitation=("a placeholder currently lifts as create_pipe — the "
                    "rebuild produces a REAL pipe; capture must start "
                    "reading IsPlaceholder before a lifter is legal")),
    "create_duct_placeholder": ReverseContract(
        "create_duct_placeholder", ReverseMode.CAPTURE_GAP,
        ReverseGuarantee.NONE,
        "L0 carries no Duct.IsPlaceholder bit, so a placeholder run is "
        "indistinguishable from a real one in the capture",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_DuctCurves",),
        representation_ops=("create_duct",),
        limitation=("a placeholder currently lifts as create_duct — the "
                    "rebuild produces a REAL duct; capture must start "
                    "reading IsPlaceholder before a lifter is legal")),
    # ГИБКИЕ. Здесь разрыв захвата ещё шире и он ГЕОМЕТРИЧЕСКИЙ: строка L0
    # знает пару концов кривой, а у гибкого участка форма живёт в
    # `FlexDuct.Points`/`FlexPipe.Points` — сплайн Эрмита через N точек.
    # Концы такой трассы не восстанавливают её: любая ломаная с теми же
    # концами дала бы ту же строку. Поэтому и мода capture_gap, и никакого
    # representation_ops: подменять гибкую подводку прямым участком между её
    # концами значило бы придумать геометрию, а не выразить недостающую.
    "create_flex_duct": ReverseContract(
        "create_flex_duct", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "L0 stores a two-point curve record; a flex run's shape is its "
        "FlexDuct.Points array, which capture does not read",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_FlexDuctCurves",),
        limitation=("capture must start reading FlexDuct.Points before a "
                    "lifter is legal; endpoints alone do not determine the "
                    "path")),
    "create_flex_pipe": ReverseContract(
        "create_flex_pipe", ReverseMode.CAPTURE_GAP, ReverseGuarantee.NONE,
        "L0 stores a two-point curve record; a flex run's shape is its "
        "FlexPipe.Points array, which capture does not read",
        decided_on="2026-08-09", due="2026-09-08",
        sources=("L0:OST_FlexPipeCurves",),
        limitation=("capture must start reading FlexPipe.Points before a "
                    "lifter is legal; endpoints alone do not determine the "
                    "path")),

    # Current-state reverse representations that are intentionally not the
    # same high-level op.
    "create_group": ReverseContract(
        "create_group", ReverseMode.COMPOSED, ReverseGuarantee.BOUNDED,
        "group relations fold member leaves; optional native-group bridge "
        "re-composes a create_group program",
        sources=("side:group",),
        entrypoints=("component_to_group_program",),
        representation_ops=("create_group",)),
    "create_pipe_system": ReverseContract(
        "create_pipe_system", ReverseMode.DECOMPOSED, ReverseGuarantee.BOUNDED,
        "snapshot stores physical segments; reverse emits elementary pipes",
        sources=("L0:OST_PipeCurves", "side:mep_system"),
        representation_ops=("create_pipe",),
        limitation="graph intent and auto-created fittings are not inverted"),
    "route_pipe_system": ReverseContract(
        "route_pipe_system", ReverseMode.DECOMPOSED, ReverseGuarantee.BOUNDED,
        "snapshot stores physical segments; reverse emits elementary pipes",
        sources=("L0:OST_PipeCurves", "side:mep_system"),
        representation_ops=("create_pipe",),
        limitation="routing intent and auto-created fittings are not inverted"),
    "route_duct_system": ReverseContract(
        "route_duct_system", ReverseMode.DECOMPOSED, ReverseGuarantee.BOUNDED,
        "snapshot stores physical segments; reverse emits elementary ducts",
        sources=("L0:OST_DuctCurves", "side:mep_system"),
        representation_ops=("create_duct",),
        limitation="routing intent and auto-created fittings are not inverted"),

    # Same-document rebuild pins existing definitions instead of pretending a
    # fresh-document inverse exists.
    "create_type": ReverseContract(
        "create_type", ReverseMode.PINNED_EXISTING, ReverseGuarantee.NONE,
        "same-document materialization references the existing type ElementId",
        sources=("L0:type references",),
        limitation="fresh-document type reconstruction is not implemented"),
    "load_family": ReverseContract(
        "load_family", ReverseMode.EXTERNAL_SOURCE, ReverseGuarantee.NONE,
        "a loaded Revit family does not retain a reproducible source RFA path",
        sources=("L0:family references",),
        limitation="an external artifact store is required for inversion"),

    # Final-state snapshots cannot recover which historical mutation produced
    # that state. Replaying these would duplicate or destroy effects.
    "change_type": ReverseContract(
        "change_type", ReverseMode.STATE_TRANSITION, ReverseGuarantee.NONE,
        "final state carries the current type, not a historical type change"),
    "set_param": ReverseContract(
        "set_param", ReverseMode.STATE_TRANSITION, ReverseGuarantee.NONE,
        "final state cannot distinguish an explicit set from original state"),
    "move_elements": ReverseContract(
        "move_elements", ReverseMode.STATE_TRANSITION, ReverseGuarantee.NONE,
        "final geometry carries no recoverable movement delta or target set"),
    "delete": ReverseContract(
        "delete", ReverseMode.STATE_TRANSITION, ReverseGuarantee.NONE,
        "deleted identities are absent from a final-state snapshot"),
}


def _validate_manifest(contracts: Mapping[str, ReverseContract]) -> None:
    write_ops = {
        name for name, op in spec.OPS.items()
        if op.family in spec.WRITE_FAMILIES
    }
    keys = set(contracts)
    if keys != write_ops:
        missing = sorted(write_ops - keys)
        extra = sorted(keys - write_ops)
        raise AssertionError(
            f"reverse manifest must cover every write op; missing={missing}, "
            f"extra={extra}")
    for name, contract in contracts.items():
        if contract.op_name != name:
            raise AssertionError(f"reverse manifest key mismatch for {name}")


_validate_manifest(_CONTRACTS)
REVERSE_CONTRACTS: Mapping[str, ReverseContract] = MappingProxyType(_CONTRACTS)


def assert_lift_emission(op_name: str) -> ReverseContract:
    """Guard a same-op L1 emission against the exhaustive manifest."""
    contract = REVERSE_CONTRACTS.get(op_name)
    if contract is None or not contract.direct_same_op_lift:
        mode = contract.mode.value if contract is not None else "undeclared"
        raise ReverseContractError(
            f"reverse lift may not emit {op_name!r} (mode={mode})")
    return contract


def assert_composed_emission(op_name: str) -> ReverseContract:
    """Guard a post-lift composed operation against the same manifest."""
    contract = REVERSE_CONTRACTS.get(op_name)
    if contract is None or contract.mode is not ReverseMode.COMPOSED:
        mode = contract.mode.value if contract is not None else "undeclared"
        raise ReverseContractError(
            f"reverse composition may not emit {op_name!r} (mode={mode})")
    return contract


def reverse_contract_report() -> dict[str, Any]:
    counts = {mode.value: 0 for mode in ReverseMode}
    for contract in REVERSE_CONTRACTS.values():
        counts[contract.mode.value] += 1
    return {
        "schema": REVERSE_CONTRACT_SCHEMA,
        "write_ops": len(REVERSE_CONTRACTS),
        "direct_same_op_lifts": sum(
            contract.direct_same_op_lift
            for contract in REVERSE_CONTRACTS.values()),
        "modes": counts,
        "contracts": [
            REVERSE_CONTRACTS[name].to_dict()
            for name in sorted(REVERSE_CONTRACTS)
        ],
    }
