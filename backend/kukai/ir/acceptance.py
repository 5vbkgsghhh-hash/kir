"""L2-приёмка: ожидание ВЫВОДИТСЯ из программы, вердикт считается из
ПОВТОРНОГО ЧТЕНИЯ модели.

ЦЕНА ОШИБКИ ЗДЕСЬ — НЕ БАГ, А ПОТЕРЯ СМЫСЛА ВСЕЙ ПЕТЛИ. 29.07 две модели
построили башню, посмотрели на собственный результат и написали «форма и
пропорции соответствуют задаче»; оператор про обе: «мусорная геометрия».
Днём раньше критерий «сдай 1в1» не проходил НИКОГДА. Болезнь одна: проверяет
тот же, кто строил, и порог лишь выбирает, в какую сторону соврёт петля.
Поэтому здесь нет ни одного суждения — только замер по предикату, который
никто не писал руками.

ПОЧЕМУ ОЖИДАНИЕ ВЫВОДИТСЯ, А НЕ ОБЪЯВЛЯЕТСЯ. Дизайн
(docs/2026-07-29-independent-acceptance-design.md, шаг 1) говорит «программа
объявляет ожидаемую дельту». Так конфликт интересов возвращается через чёрный
ход: автор объявит слабое ожидание, и приёмка снова не будет значить ничего.
Компилятор ТОЧНО ЗНАЕТ, что он скомпилировал, — сколько create_wall и на каком
уровне. Автор выражает замысел ОПЕРАЦИЯМИ; предикат следует из них сам, и
ослабить его нельзя, потому что его никто не пишет. Пред-регистрация выходит
по построению: ожидание существует до исполнения, потому что выводится из
программы, а не из результата. :func:`expectation_digest` даёт короткую
подпись — её можно записать в квитанцию ДО постройки и потом доказать, что
предикат не подправляли под результат.

ЦЕНА ВЫДУМАННОЙ ТОЧНОСТИ ВЫШЕ ЦЕНЫ ОТСУТСТВИЯ ПРОВЕРКИ. Ожидание «ровно N»
там, где N на самом деле неизвестно, валит ЧЕСТНЫЕ постройки, а чекер, который
врёт на честной постройке, отключают — и вместе с ним отключают те проверки,
которые работали. Поэтому каждый род вклада несёт свою степень уверенности
(:class:`Certainty`), и «не знаю» здесь — законный ответ, а не позор.

ЧТО ЗАМЕРЕНО, А НЕ ВСПОМНЕНО (31 сохранённый разбор, backend/data/decompile,
30.07 — числа проверяемы тем же обходом):

* уровень ДВЕРИ не равен уровню стены-хозяина в 76 случаях из 15 569
  (0.49%): дверь в стене L42 с базовым смещением 400 мм получает
  ``LEVEL_PARAM`` = «L42_+500». Вывести уровень двери из хозяина —
  правдоподобно и неверно; поэтому у двери и окна уровень НЕИЗВЕСТЕН;
* ``OST_Stairs``: 0 строк из 351 несут ``level_name``. Ожидание «лестница на
  уровне X» завалило бы каждую честную лестницу;
* ``create_beam``: Revit выводит опорный уровень из ОТМЕТКИ КРИВОЙ, а не из
  аргумента ``level`` (замер 27.07 записан в самом ``post`` опа: передан
  L_01@0 при кривой Z=3000 → привязка к L_01ДОО1_+2.500);
* ``Railing.Create(doc, hostId, typeId, position)`` возвращает КОЛЛЕКЦИЮ
  (arch_emit.py: у марша ограждение встаёт с двух сторон сразу) — один оп даёт
  1..N ограждений, значит «не менее 1», а не «ровно 1». Этого плеча нет в
  ``tools/capability_map.py``: там плечо ищется по роду параметра, а здесь оно
  в поведении Revit;
* фитинги: ``route_pipe_system`` строит РОВНО len(segments) труб (connect.py
  ``emit_segments_cs`` — одна строка Create на ребро), а 2 652 фитинга и 152
  единицы арматуры Snowdon сделал Revit сам при НУЛЕ авторских. Значит
  ``OST_PipeFitting`` — производная категория и не сверяется вовсе;
* производные категории существуют и у мирных опов: ``OST_SketchLines`` есть
  в 31 разборе из 31 (366 902 элемента), ``OST_StairsRuns``/``Landings``/
  ``RailingHandRail``/``RailingTopRail`` появляются сами вслед за лестницей и
  ограждением. Поэтому «в модели появилась категория, которой нет в
  ожидании» — СПРАВКА, а не отказ (см. :attr:`Verdict.unexpected`).

ЭТОТ МОДУЛЬ — ТОЛЬКО L2-СУДЬЯ. Живой correctness loop дополнительно
композирует его с ``acceptance_mutation``: exact-id ``set_param``,
``move_elements``, ``change_type`` и ``delete`` перечитываются отдельно, а их
``UniqueId``/``VersionGuid`` становятся стражами входа в транзакцию. Поэтому
ограничения ниже относятся именно к переписи создания, а не ко всему живому
acceptance-контуру.

ЧЕГО L2-ПЕРЕПИСЬ НЕ ЛОВИТ — И ЭТОТ СПИСОК ВАЖНЕЕ ПРЕДЫДУЩЕГО. Пропуск,
о котором знают, — известная граница; пропуск, о котором молчат, — та же
самая вчерашняя ложь, только в коде.

* ГЕОМЕТРИЮ НЕ СМОТРИТ ВООБЩЕ. Двенадцать стен нужной категории на нужном
  уровне, поставленные в мусорной геометрии, приёмку ПРОХОДЯТ. Это L3
  (габарит внутри объявленной области, совпадающие дубликаты, клеш-дельта), и
  здесь его нет намеренно;
* ТИП СОЗДАННОГО ЭЛЕМЕНТА НЕ СВЕРЯЕТСЯ. Стена не того типа — стена.
  Отдельный exact-id ``change_type`` проверяется mutation-судьёй, но это не
  доказывает тип результата любого create-опа;
* ПОДМЕНУ ВНУТРИ ОДНОЙ КЛЕТКИ ОХВАТА НЕ ВИДНО: снести чужую стену и
  поставить свою на том же уровне даёт ту же дельту;
* ЛИШНЕЕ В НЕОБЪЯВЛЕННОЙ КАТЕГОРИИ — только справка. Отказ там валил бы
  каждую честную постройку (см. про производные выше);
* ВЕРХНИЕ ГРАНИЦЫ СНИМАЮТСЯ ЦЕЛИКОМ, стоит программе содержать хоть один оп
  с неизвестной категорией. На настоящем фасаде это 270 опов из 2 720
  (``set_curtain_panel``, ``create_curtain_grid_line``, ``place_family``) —
  то есть дубликаты в таких программах не ловятся. Снимаются они и точечно:
  у категории, которая входит в две группы сразу (перекрытие и
  фундаментная плита), и у категории, которую в этой же программе кто-то
  порождает производно (ограждения при лестнице);
* ИМЕНА УРОВНЕЙ СРАВНИВАЮТСЯ ДОСЛОВНО (после обрезки пробелов). Переименовали
  уровень между двумя переписями — будет расхождение, которого нет;
* ДЕЛЬТУ СОЗДАНИЯ ОТ ЧУЖОЙ ПРАВКИ ОТЛИЧИТЬ НЕЧЕМ: если другой актор добавил
  элементы той же категории между двумя чтениями, они лягут в наш счёт.
  Exact-id мутации защищены ``VersionGuid`` внутри транзакции, A5 — своим
  revision guard; обычная category-census постройка такого атрибутора пока не
  имеет;
* САМА ЧИСТАЯ ФУНКЦИЯ НЕ ОТЛИЧАЕТ RECEIPT ОТ ПОВТОРНОГО ЧТЕНИЯ. В production
  это закрыто ``acceptance_probe`` + ``acceptance_runtime``: один независимый
  document-bound bridge-read, строгий wire parser, разные ``before/after``
  фазы. Автономный новый вызывающий обязан использовать тот же адаптер.

ГРАНИЦА МОДУЛЯ. Обе публичные функции ЧИСТЫЕ: ни Revit, ни сети, ни диска, ни
времени. Ожидание сериализуемо (:meth:`Expectation.to_dict`) и стабильно между
процессами: строки отсортированы, множества выведены в кортежи. Уровень L2 и
только он — габариты, дубликаты и клеш (L3) и скриншот (L4) сюда не заходят.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from kukai.ir import spec
from kukai.ir.diag import KirRefusal
from kukai.ir.midend import PlannedProgram


#: Уровень элемента, у которого его нет. НЕ None и не «неизвестно»: отсутствие
#: уровня — факт о переписи (марка, размер, лестница), и он обязан быть
#: счётным ключом, а не растворяться. Тот же приём, что ``NO_CATEGORY_KEY`` в
#: §18.1 (decompile/census.py).
LEVEL_NONE = ""


class Certainty(str, Enum):
    """Насколько твёрдо известна дельта строки ожидания."""

    #: Ровно столько. Единственная степень, при которой проверяется ВЕРХНЯЯ
    #: граница, то есть ловятся дубликаты.
    EXACT = "exact"
    #: Не менее столько. Верх открыт: Revit вправе добавить своё.
    AT_LEAST = "at_least"
    #: Ни числа, ни категории. Строка не проверяется вовсе и существует ради
    #: честности отчёта: «здесь мы слепы» обязано быть видно.
    UNKNOWN = "unknown"


class MismatchCode(str, Enum):
    """Что именно разошлось. «Примерно похоже» отсутствует намеренно."""

    #: В категории прибавилось МЕНЬШЕ, чем следует из программы.
    CATEGORY_SHORTFALL = "category_shortfall"
    #: Прибавилось БОЛЬШЕ (дубликаты; проверяется только при полной точности).
    CATEGORY_OVERSHOOT = "category_overshoot"
    #: На объявленном уровне меньше, чем объявлено, — «построил в другом
    #: месте». Ради этого класса L2 и существует.
    LEVEL_SHORTFALL = "level_shortfall"
    #: На уровне больше, чем туда могло попасть при любом раскладе
    #: «плавающих» строк.
    LEVEL_OVERSHOOT = "level_overshoot"


@dataclass(frozen=True, slots=True)
class BlindOp:
    """Оп, про который ожидание не может сказать ничего проверяемого.

    Существует, чтобы слепота была НАЗВАНА. Молчаливый пропуск такого опа —
    это чекер, который тем увереннее, чем меньше понимает.
    """

    op_id: str
    op_name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"op_id": self.op_id, "op": self.op_name, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ExpectedRow:
    """Одна строка ожидания: сколько прибавится, где и насколько твёрдо.

    ``categories`` — кортеж из одного или нескольких ключей переписи. Больше
    одного значит «элемент попадёт РОВНО В ОДНУ из них, а в какую — из
    программы не видно»: ограждение это ``OST_StairsRailing`` либо
    ``OST_Railings``, DirectShape в §18.1 ключуется своей BuiltInCategory, а в
    строках извлечения — литералом ``DirectShape``. Сверяется СУММА по группе;
    так проверка остаётся верной при любом варианте и не выдумывает того, чего
    компилятор не знает.

    ``level is None`` — «плавающая» строка: элементы точно будут, а на каком
    уровне — из программы не следует.
    """

    categories: tuple[str, ...]
    level: str | None
    count: int
    certainty: Certainty
    op_ids: tuple[str, ...]
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "categories": list(self.categories),
            "level": self.level,
            "count": self.count,
            "certainty": self.certainty.value,
            "op_ids": list(self.op_ids),
            "why": self.why,
        }


@dataclass(frozen=True, slots=True)
class Expectation:
    """Предикат приёмки, выведенный из программы.

    ``upper_bounds_valid=False`` означает, что в программе есть оп с
    НЕИЗВЕСТНОЙ категорией. Такой оп может добавить элементы в любую
    объявленную категорию, поэтому проверка дубликатов честно отключается.

    ``lower_bounds_valid=False`` сильнее: ``delete``/replacement-подобный оп
    может ВЫЧЕСТЬ элемент из той же клетки, куда create-оп его добавил. Net
    delta тогда меньше честно созданного количества, и L2 дал бы ложный
    shortfall после уже совершённого commit. В таком смешанном случае census
    не судит вовсе; exact mutation-судья продолжает работать, а composite
    evidence остаётся явно неполным.
    """

    rows: tuple[ExpectedRow, ...]
    derived_categories: tuple[str, ...]
    blind_ops: tuple[BlindOp, ...]
    upper_bounds_valid: bool
    op_count: int
    notes: tuple[str, ...] = ()

    @property
    def checkable(self) -> bool:
        """Есть ли хоть одна строка, которую можно провалить."""
        return (self.lower_bounds_valid
                and any(row.certainty is not Certainty.UNKNOWN
                        and row.count > 0 for row in self.rows))

    @property
    def lower_bounds_valid(self) -> bool:
        """Whether no blind operation can subtract a registered census cell."""

        return not any(op.op_name in _OPS_CAN_INVALIDATE_LOWER_BOUNDS
                       for op in self.blind_ops)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [row.to_dict() for row in self.rows],
            "derived_categories": list(self.derived_categories),
            "blind_ops": [op.to_dict() for op in self.blind_ops],
            "lower_bounds_valid": self.lower_bounds_valid,
            "upper_bounds_valid": self.upper_bounds_valid,
            "op_count": self.op_count,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class Mismatch:
    """Названное расхождение: что, где, сколько ждали, сколько получили."""

    code: MismatchCode
    categories: tuple[str, ...]
    level: str | None
    expected: int
    observed: int
    op_ids: tuple[str, ...]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "categories": list(self.categories),
            "level": self.level,
            "expected": self.expected,
            "observed": self.observed,
            "op_ids": list(self.op_ids),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class Verdict:
    """Итог сверки. ``accepted`` — единственное, что имеет силу.

    ``vacuous=True`` — приёмка НИЧЕГО НЕ ПРОВЕРИЛА (ожидание пустое или всё в
    нём неизвестно). Это состояние выведено в отдельное поле, потому что
    ``accepted=True`` при нулевой проверке — ровно тот «уверенный успех, за
    которым ничего нет», ради запрета которого написан весь модуль.

    ``unexpected`` — категории, где дельта есть, а в ожидании их нет. Это
    СПРАВКА, а не отказ: производных элементов Revit делает больше, чем
    авторских (366 902 ``OST_SketchLines`` на 31 разбор), и отказ здесь валил
    бы каждую честную постройку.
    """

    accepted: bool
    mismatches: tuple[Mismatch, ...]
    checked_groups: int
    unexpected: tuple[tuple[str, int], ...]
    upper_bounds_checked: bool
    blind_ops: tuple[BlindOp, ...]

    @property
    def vacuous(self) -> bool:
        return self.checked_groups == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "vacuous": self.vacuous,
            "mismatches": [m.to_dict() for m in self.mismatches],
            "checked_groups": self.checked_groups,
            "unexpected": [{"category": c, "delta": d}
                           for c, d in self.unexpected],
            "upper_bounds_checked": self.upper_bounds_checked,
            "blind_ops": [op.to_dict() for op in self.blind_ops],
        }

    def summary_ru(self) -> str:
        if self.vacuous:
            return ("приёмка НИЧЕГО не проверила: в ожидании нет ни одной "
                    "проверяемой строки")
        if self.accepted:
            tail = "" if self.upper_bounds_checked else \
                " (верхние границы не проверялись: в программе есть опы с "\
                "неизвестной категорией)"
            return (f"сошлось; проверено групп категорий: "
                    f"{self.checked_groups}{tail}")
        parts = "; ".join(m.detail for m in self.mismatches[:4])
        more = len(self.mismatches) - 4
        if more > 0:
            parts += f"; ещё {more}"
        return f"НЕ сошлось: {parts}"


# ── Таблицы: категория, уровень и плечо каждого опа ──────────────────────────
#
# Таблицы ЯВНЫЕ, а не выведенные из ``lift.LIFTER_TABLE``, хотя соблазн велик.
# Причина в направлении: таблица лифтера отвечает «какой оп ПОДНЯЛ БЫ элемент
# этой категории», а здесь нужен обратный вопрос «в какую категорию попадёт
# результат этого опа», и совпадают они не всегда (у ``create_column`` две
# категории на выбор, у ``create_foundation(slab)`` категория зависит от
# ТИПА, а половина реестра лифтера не имеет вовсе). Молчаливое наследование
# будущих строк лифтера дало бы ожидание, которого никто не проверял, —
# поэтому связь между таблицами держит ТЕСТ (``test_acceptance``), а не
# импорт.

#: Оп → ключи переписи, куда попадёт его результат. Кортеж длиннее одного =
#: «в одну из них, а в какую — не видно» (сверяется сумма).
_OP_CATEGORIES: Mapping[str, tuple[str, ...]] = {
    "create_wall": ("OST_Walls",),
    "create_floor": ("OST_Floors",),
    "create_floor_by_contour": ("OST_Floors",),
    "create_roof": ("OST_Roofs",),
    "create_ceiling": ("OST_Ceilings",),
    "create_door": ("OST_Doors",),
    "create_window": ("OST_Windows",),
    "create_room": ("OST_Rooms",),
    "create_level": ("OST_Levels",),
    "create_grid": ("OST_Grids",),
    "create_beam": ("OST_StructuralFraming",),
    "create_stairs": ("OST_Stairs",),
    "create_pipe": ("OST_PipeCurves",),
    "create_duct": ("OST_DuctCurves",),
    "create_cable_tray": ("OST_CableTray",),
    "create_pipe_system": ("OST_PipeCurves",),
    "route_pipe_system": ("OST_PipeCurves",),
    "route_duct_system": ("OST_DuctCurves",),
    "create_text": ("OST_TextNotes",),
    "create_dimension": ("OST_Dimensions",),
    # Колонна: категорию выбирает ЗАКРЫТОЕ перечисление самого опа, поэтому
    # она известна точно — см. _category_of_op.
    "create_column": ("OST_StructuralColumns", "OST_Columns"),
    # Ограждение: ``OST_Railings`` не встретился НИ В ОДНОМ из 31 разбора, но
    # таблица лифтера знает обе, и версия Revit могла бы решить иначе. Сумма
    # по двум верна при любом ответе; выбрать одну значило бы поставить на
    # догадку там, где ставить не на что.
    "create_railing": ("OST_Railings", "OST_StairsRailing"),
    # Марка: род марки определяет КАТЕГОРИЯ ЦЕЛИ, а цель — id или ссылка,
    # то есть из программы не читается. Сумма по десяти родам, которые вообще
    # читает конвейер (tag_extract.TAG_CATEGORIES).
    "create_tag": (
        "OST_AreaTags", "OST_DoorTags", "OST_FloorTags", "OST_MaterialTags",
        "OST_MechanicalEquipmentTags", "OST_MultiCategoryTags",
        "OST_RoomTags", "OST_StairsRailingTags", "OST_StructuralFramingTags",
        "OST_WallTags",
    ),
}

#: Производные категории: элементы, которые Revit делает САМ вслед за опом.
#: Не сверяются никогда и не попадают в справку «неожиданное».
_OP_DERIVED: Mapping[str, tuple[str, ...]] = {
    # Стена витражного типа сама рождает ячейки, панели и импосты; тип —
    # селектор, поэтому «витражная ли она» из программы не видно.
    "create_wall": ("OST_CurtainGridsWall", "OST_CurtainWallPanels",
                    "OST_CurtainWallMullions"),
    "create_floor": ("OST_SketchLines",),
    "create_floor_by_contour": ("OST_SketchLines",),
    "create_roof": ("OST_SketchLines",),
    "create_ceiling": ("OST_SketchLines",),
    "create_foundation": ("OST_SketchLines",),
    "create_stairs": ("OST_StairsRuns", "OST_StairsLandings",
                      "OST_StairsRailing", "OST_StairsRailingBaluster",
                      "OST_RailingHandRail", "OST_RailingTopRail",
                      "OST_SketchLines"),
    "create_railing": ("OST_StairsRailingBaluster", "OST_RailingHandRail",
                       "OST_RailingTopRail",
                       "OST_RailingRailPathExtensionLines"),
    # 2 652 фитинга и 152 единицы арматуры Snowdon при НУЛЕ авторских.
    "create_pipe_system": ("OST_PipeFitting", "OST_PipeAccessory"),
    "route_pipe_system": ("OST_PipeFitting", "OST_PipeAccessory"),
    "route_duct_system": ("OST_DuctFitting", "OST_DuctAccessory"),
    # Обёртка группы — бухгалтерия Revit: модельная или узловая, зависит от
    # состава членов. Считать её точно значило бы гадать.
    "create_group": ("OST_IOSModelGroups", "OST_IOSDetailGroups"),
    "create_curtain_grid_line": ("OST_CurtainWallMullions",
                                 "OST_CurtainWallPanels"),
}

#: Опы, у которых уровень результата РАВЕН разрешённому селектору ``level``.
#: Всё, чего здесь нет, «плавает» — и почти каждое отсутствие оплачено
#: замером (шапка модуля).
_LEVEL_FROM_PARAM: frozenset[str] = frozenset({
    "create_wall", "create_floor", "create_floor_by_contour", "create_roof",
    "create_ceiling", "create_column", "create_room", "create_pipe",
    "create_duct", "create_cable_tray", "create_foundation",
    "create_pipe_system", "route_pipe_system", "route_duct_system",
})

#: Пишущие опы, которые НЕ добавляют ни одного элемента в перепись.
#: ``create_type``/``load_family`` делают ТИПЫ, а перепись §18.1 — это
#: ``WhereElementIsNotElementType()``; ``set_param``/``move_elements`` правят
#: существующее.
_OPS_WITHOUT_ELEMENTS: frozenset[str] = frozenset({
    "create_type", "load_family", "set_param", "move_elements",
})

#: Опы, чью дельту нельзя ни назвать, ни ограничить снизу, — с причиной.
#: Причина попадает в отчёт дословно: «слепо» без объяснения неотличимо от
#: «забыли».
_OPS_BLIND: Mapping[str, str] = {
    "place_family": (
        "категория экземпляра = категория семейства, а семейство приходит "
        "селектором symbol — из программы она не читается"),
    "delete": (
        "цель адресуется id или ссылкой; какой категории элемент удалён, "
        "программа не говорит"),
    "change_type": (
        "смена типа обычно идёт НА МЕСТЕ, но документированный случай "
        "стена ↔ витражная панель создаёт НОВЫЙ элемент другой категории"),
    "set_curtain_panel": (
        "ChangePanelType при типе-стене строит стену вместо панели "
        "(замер 28.07) — дельта категорий не выводима"),
    "create_curtain_grid_line": (
        "линия разрезки делит ячейки: число панелей и импостов после неё "
        "определяет Revit"),
}

# These operations may delete or replace a pre-existing instance.  Because
# the current L2 wire predicate does not preregister the old category x level
# cell, their negative contribution cannot be separated from a create-op's
# positive contribution.  Purely additive unknown-category operations (for
# example place_family) only invalidate upper bounds and are not listed here.
_OPS_CAN_INVALIDATE_LOWER_BOUNDS: frozenset[str] = frozenset({
    "delete", "change_type", "set_curtain_panel",
    "create_curtain_grid_line",
})


def _level_from_selector(selector: Any,
                         level_names: Mapping[str, str],
                         level_names_by_id: Mapping[str, str]) -> str | None:
    """Имя уровня из селектора, либо None, если имени взять неоткуда.

    ``by=default`` даёт правило, а не имя; ``by=element_id`` даёт номер, и
    имя к нему находится ТОЛЬКО в справочнике модели. Подставить сюда что-то
    от себя — значит сверять не с тем уровнем и валить верную постройку.

    ЗАЧЕМ СПРАВОЧНИК ПО id. Без него ось уровней СЛЕПА ровно там, где она
    нужнее всего: материализатор пересборки пришпиливает уровень
    ``{"by": "element_id"}`` (режим ``same_document``), и на настоящем здании
    (sob62_fas_r23_v18, 11 программ, 2 720 опов) НИ ОДНА из 2 450 строк
    ожидания не получала уровня — то есть L2 вырождался в L1. Справочник —
    ДАННЫЕ О МОДЕЛИ (пул ``levels`` снимка), а не мнение автора программы:
    ослабить им предикат нельзя, а без него предиката просто нет.
    """
    if not isinstance(selector, dict):
        return None
    by = selector.get("by")
    value = selector.get("value")
    if by == "name" and isinstance(value, str) and value.strip():
        return value.strip()
    if by == "ref" and isinstance(value, str):
        return level_names.get(value.strip())
    if by == "element_id" and value is not None:
        return level_names_by_id.get(str(value))
    return None


def _category_of_op(op: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Ключи переписи для результата опа; None — категория неизвестна."""
    name = op.get("op")
    if name == "create_column":
        # Закрытое перечисление с умолчанием — категория известна точно.
        category = op.get("category", "structural")
        return (("OST_StructuralColumns",) if category == "structural"
                else ("OST_Columns",))
    if name == "create_directshape":
        # ДВА КЛЮЧА, И ЭТО НЕ ПЕРЕСТРАХОВКА. Перепись §18.1 ключует элемент
        # его BuiltInCategory, а строки извлечения кладут в поле литерал
        # "DirectShape" (extract.py) — в 31 разборе ключа "DirectShape" в
        # переписи нет ни разу, а в строках он есть. Сумма по двум верна при
        # любом источнике переписи.
        from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES
        built_in = DIRECTSHAPE_CATEGORIES.get(op.get("category"))
        if built_in is None:
            return None
        return tuple(sorted((built_in, "DirectShape")))
    if name == "create_foundation":
        if op.get("variety") == "isolated":
            # Символ грунтуется пулом foundation_symbols — это
            # FilteredElementCollector(...).OfCategory(OST_StructuralFoundation)
            # (open_model.py), значит категория известна точно.
            return ("OST_StructuralFoundation",)
        # variety="slab" эмитируется через Floor.Create с типом из пула
        # floor_types: перекрытие это или фундаментная плита — решает ТИП,
        # которого компилятор не видит.
        return ("OST_Floors", "OST_StructuralFoundation")
    return _OP_CATEGORIES.get(name)


def _plural_count(op: Mapping[str, Any]) -> tuple[int, Certainty, str]:
    """Сколько элементов даст оп: число, твёрдость и причина мягкости."""
    name = op.get("op")
    if name in ("create_pipe_system", "route_pipe_system",
                "route_duct_system"):
        segments = op.get("segments")
        if not isinstance(segments, Sequence) or isinstance(segments, str):
            return (0, Certainty.UNKNOWN, "segments не список")
        # Одно ребро — одна строка Create (connect.emit_segments_cs).
        return (len(segments), Certainty.EXACT,
                "одно ребро графа = один отрезок трубы/воздуховода")
    if name == "create_railing":
        if op.get("variety") == "hosted":
            return (1, Certainty.AT_LEAST,
                    "Railing.Create(host) возвращает КОЛЛЕКЦИЮ: у марша "
                    "ограждение встаёт с двух сторон сразу")
        return (1, Certainty.EXACT, "")
    return (1, Certainty.EXACT, "")


def _normalise_program(program: Any) -> tuple[list[dict], tuple[str, ...]]:
    """Consume the compiler's immutable plan; never re-plan accepted input.

    A raw envelope is supported for the standalone API, but it is converted by
    the public compiler mid-end exactly once.  Serving passes the
    ``CompileOutput.planned`` object, binding acceptance to the same payload
    that was emitted.  A bare list remains a compatibility input and is wrapped
    in the current IR envelope before planning.
    """
    if isinstance(program, PlannedProgram):
        return program.to_ops(), ()
    if isinstance(program, Mapping):
        envelope: Any = program
    elif isinstance(program, Sequence) and not isinstance(program, (str, bytes)):
        envelope = {"ir_version": spec.IR_VERSION, "ops": list(program)}
    else:
        return ([], ("программа не объект, не список и не PlannedProgram",))

    # Lazy import prevents acceptance from entering the package's compiler
    # import chain when it is used only to check an already registered digest.
    from kukai.ir.compiler import plan_program
    try:
        planned = plan_program(envelope)
    except KirRefusal as exc:
        codes = tuple(dict.fromkeys(diag.code for diag in exc.diagnostics))
        suffix = ",".join(codes) if codes else "без кода"
        return ([], (f"программа не прошла KIR plan: {suffix}",))
    except Exception as exc:  # defensive: acceptance must stay honest/fail-closed
        return ([], (f"KIR plan не построен: {exc.__class__.__name__}",))
    return planned.to_ops(), ()


def _contributions(ops: Iterable[Mapping[str, Any]],
                   level_names: dict[str, str],
                   level_names_by_id: Mapping[str, str],
                   *,
                   multiplier: int,
                   id_prefix: str,
                   rows: list[ExpectedRow],
                   blind: list[BlindOp],
                   derived: set[str]) -> None:
    """Разложить плоский список опов на строки ожидания (рекурсивно в группы)."""
    for op in ops:
        name = op.get("op")
        op_id = f"{id_prefix}{op.get('id') or name}"
        ospec = spec.OPS.get(name) if isinstance(name, str) else None
        if ospec is None or not ospec.writes_model:
            continue                    # query-опы модель не трогают

        # Уровни, объявленные ЭТОЙ ЖЕ программой, — единственный способ
        # узнать имя за ссылкой by=ref (так работает макрос stack).
        if name == "create_level":
            declared = op.get("name")
            own_id = op.get("id")
            if (isinstance(declared, str) and declared.strip()
                    and isinstance(own_id, str) and own_id.strip()):
                level_names[own_id.strip()] = declared.strip()

        derived.update(_OP_DERIVED.get(name, ()))

        if name in _OPS_WITHOUT_ELEMENTS:
            continue
        if name in _OPS_BLIND:
            blind.append(BlindOp(op_id, name, _OPS_BLIND[name]))
            continue

        if name == "create_group":
            members = op.get("members")
            placements = op.get("placements")
            if not isinstance(members, list) or not isinstance(placements, list):
                blind.append(BlindOp(op_id, name,
                                     "members/placements не списки"))
                continue
            # Занятие 0 — сами члены, каждое placement — ещё одно занятие.
            _contributions(
                [m for m in members if isinstance(m, Mapping)],
                dict(level_names), level_names_by_id,
                multiplier=multiplier * (1 + len(placements)),
                id_prefix=f"{op_id}/",
                rows=rows, blind=blind, derived=derived)
            continue

        categories = _category_of_op(op)
        if categories is None:
            blind.append(BlindOp(
                op_id, name,
                _OPS_BLIND.get(name, "категория результата не выводится")))
            continue

        count, certainty, why = _plural_count(op)
        level = (_level_from_selector(op.get("level"), level_names,
                                      level_names_by_id)
                 if name in _LEVEL_FROM_PARAM else None)
        if certainty is Certainty.UNKNOWN:
            blind.append(BlindOp(op_id, name, why))
            continue
        rows.append(ExpectedRow(
            categories=categories,
            level=level,
            count=count * multiplier,
            certainty=certainty,
            op_ids=(op_id,),
            why=why,
        ))


def _merge_rows(rows: Sequence[ExpectedRow]) -> tuple[ExpectedRow, ...]:
    """Свести строки к канону: одна строка на (категории, уровень, твёрдость).

    Порядок фиксирован сортировкой, а не порядком опов, — иначе одна и та же
    программа давала бы разные подписи, и пред-регистрация ничего бы не
    доказывала.
    """
    merged: dict[tuple[tuple[str, ...], str | None, str], list[Any]] = {}
    for row in rows:
        key = (row.categories, row.level, row.certainty.value)
        slot = merged.setdefault(key, [0, [], ""])
        slot[0] += row.count
        slot[1].extend(row.op_ids)
        if row.why and not slot[2]:
            slot[2] = row.why
    out = [
        ExpectedRow(categories=key[0], level=key[1], count=slot[0],
                    certainty=Certainty(key[2]),
                    op_ids=tuple(sorted(slot[1])), why=slot[2])
        for key, slot in merged.items()
    ]
    out.sort(key=lambda r: (r.categories, r.level or "", r.certainty.value))
    return tuple(out)


def derive_expectation(program: Any,
                       *,
                       level_names_by_id: Mapping[Any, str] | None = None,
                       ) -> Expectation:
    """Вывести предикат приёмки ИЗ ПРОГРАММЫ. Чистая функция.

    Предпочтительный вход — ``CompileOutput.planned``: тогда ожидание описывает
    буквально тот неизменяемый план, который был понижен в C#. Для автономного
    использования принимается и тот же конверт, что у ``compile_program``
    (либо голый список): он проходит публичный ``plan_program`` ровно один раз.

    ``level_names_by_id`` — ``ElementId`` уровня → его имя, из пула ``levels``
    снимка модели. Не передан — уровни, пришпиленные по id, останутся
    неизвестными, и приёмка честно выродится в проверку итогов по
    категориям. Замер: на пересборке настоящего здания (11 программ,
    2 720 опов) без справочника располагалось НОЛЬ строк из 2 450.

    Ничего не поднимает: программа, которую компилятор откажется принять,
    даёт пустое ожидание с записанной причиной — приёмке нечего проверять,
    и она обязана сказать это, а не притвориться успехом.
    """
    ops, notes = _normalise_program(program)
    by_id = {str(key): value.strip()
             for key, value in (level_names_by_id or {}).items()
             if isinstance(value, str) and value.strip()}
    rows: list[ExpectedRow] = []
    blind: list[BlindOp] = []
    derived: set[str] = set()
    level_names: dict[str, str] = {}
    _contributions(ops, level_names, by_id, multiplier=1, id_prefix="",
                   rows=rows, blind=blind, derived=derived)
    return Expectation(
        rows=_merge_rows(rows),
        derived_categories=tuple(sorted(derived)),
        blind_ops=tuple(blind),
        upper_bounds_valid=not blind,
        op_count=len(ops),
        notes=notes,
    )


def expectation_digest(expectation: Expectation) -> str:
    """Короткая подпись ожидания — доказательство пред-регистрации.

    Записанная в квитанцию ДО постройки, она делает подмену предиката после
    результата обнаружимой. Без неё «предикат объявлен заранее» — обещание,
    а обещания в этой петле уже подводили.
    """
    payload = json.dumps(expectation.to_dict(), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def expectation_categories(expectation: Expectation) -> tuple[str, ...]:
    """Return the exact category universe required by an L2 live read.

    Derived categories are intentionally absent: they are documented blind
    output, never acceptance predicates.  The returned tuple is canonical so
    the live request, pre-registration record, and post-read parser can bind
    the same scope byte-for-byte.
    """

    if not isinstance(expectation, Expectation):
        raise TypeError("category scope requires a typed Expectation")
    return tuple(sorted({
        category
        for row in expectation.rows
        for category in row.categories
    }))


# ── Перепись охвата и сверка ────────────────────────────────────────────────
#
# ФОРМАТ ВЗЯТ У §18.1 РОВНО НАСТОЛЬКО, НАСКОЛЬКО ОН ПОДХОДИТ, И НЕ ДАЛЬШЕ.
# ``decompile.census.reconcile_census`` сводит перепись документа с
# извлечённым, и её ключ — ОДНА ось, BuiltInCategory (``CensusEntry.key``):
# уровня в ней нет ни в записи, ни в проходе, который её снимает
# (``FilteredElementCollector(doc).WhereElementIsNotElementType()``, один
# полномодельный счёт). L2 по определению двумерен — «категория × уровень», —
# поэтому взять структуру §18.1 целиком нельзя: она не выражает охвата.
# Взято то, что выражает: ключ категории — та же строка BuiltInCategory,
# счёт — то же целое, а асимметрия недобора и перебора (§18.1: недобор —
# типизированная строка, перебор — ошибка) наследуется прямо в MismatchCode.
# Вторая ось берётся из ``L0Element.level_name``, которое читается ТЕМ ЖЕ
# конвейером и той же цепочкой BIP, что и уровень в пробах.

ScopeCensus = Mapping[tuple[str, str], int]


def scope_census_from_elements(elements: Iterable[Any]) -> dict[tuple[str, str], int]:
    """Перепись охвата из строк элементов: (категория, уровень) → сколько.

    Принимает что угодно с полями ``category``/``level_name`` (строки L0,
    строки пробы, простые словари). Уровень нормализуется обрезкой пробелов;
    его отсутствие даёт :data:`LEVEL_NONE`, а не пропуск строки — потерять
    элемент здесь значит недосчитать его в дельте и обвинить верную постройку.
    """
    counts: dict[tuple[str, str], int] = {}
    for element in elements:
        if isinstance(element, Mapping):
            category = element.get("category")
            level = element.get("level_name")
        else:
            category = getattr(element, "category", None)
            level = getattr(element, "level_name", None)
        if not isinstance(category, str) or not category:
            continue
        key = (category, level.strip() if isinstance(level, str) else LEVEL_NONE)
        counts[key] = counts.get(key, 0) + 1
    return counts


def census_delta(before: ScopeCensus, after: ScopeCensus) -> dict[tuple[str, str], int]:
    """Что прибавилось: ``after - before`` по объединению ключей.

    Ключ, которого не было ДО, — это ноль, а не пропуск: категория, впервые
    появившаяся в модели, обязана считаться целиком.
    """
    keys = set(before) | set(after)
    return {key: int(after.get(key, 0)) - int(before.get(key, 0))
            for key in keys}


def _observed_by_level(delta: Mapping[tuple[str, str], int],
                       categories: Sequence[str]) -> dict[str, int]:
    wanted = set(categories)
    out: dict[str, int] = {}
    for (category, level), value in delta.items():
        if category in wanted:
            out[level] = out.get(level, 0) + value
    return out


def _check_total(categories: tuple[str, ...],
                 rows: Sequence[ExpectedRow],
                 observed: Mapping[str, int],
                 exact_group: bool) -> list[Mismatch]:
    """Итог по группе категорий: не меньше объявленного, а при полной
    точности — и не больше."""
    lower = sum(row.count for row in rows
                if row.certainty is not Certainty.UNKNOWN)
    got = sum(observed.values())
    op_ids = tuple(sorted({oid for row in rows for oid in row.op_ids}))
    names = "/".join(categories)
    if got < lower:
        return [Mismatch(
            code=MismatchCode.CATEGORY_SHORTFALL, categories=categories,
            level=None, expected=lower, observed=got, op_ids=op_ids,
            detail=(f"{names}: программа даёт {lower} элементов, "
                    f"в модели прибавилось {got}"))]
    if exact_group and got > lower:
        return [Mismatch(
            code=MismatchCode.CATEGORY_OVERSHOOT, categories=categories,
            level=None, expected=lower, observed=got, op_ids=op_ids,
            detail=(f"{names}: программа даёт ровно {lower} элементов, "
                    f"в модели прибавилось {got}"))]
    return []


def _check_levels(categories: tuple[str, ...],
                  rows: Sequence[ExpectedRow],
                  observed: Mapping[str, int],
                  exact_group: bool) -> list[Mismatch]:
    """Разрез по уровням — то, ради чего L2 существует.

    Строка с известным уровнем даёт НИЖНЮЮ границу на этом уровне: её
    элементы обязаны оказаться там. Строки без уровня («плавающие») дают
    запас, который может лечь куда угодно, — на него и расширяется верхняя
    граница каждого уровня.
    """
    located: dict[str, int] = {}
    floating = 0
    for row in rows:
        if row.certainty is Certainty.UNKNOWN:
            continue
        if row.level is None:
            floating += row.count
        else:
            located[row.level] = located.get(row.level, 0) + row.count
    if not located:
        return []
    names = "/".join(categories)
    ops_at: dict[str, tuple[str, ...]] = {}
    for row in rows:
        if row.level is not None:
            ops_at[row.level] = ops_at.get(row.level, ()) + row.op_ids
    out: list[Mismatch] = []
    for level in sorted(set(located) | set(observed)):
        need = located.get(level, 0)
        got = observed.get(level, 0)
        shown = level or "(без уровня)"
        if got < need:
            out.append(Mismatch(
                code=MismatchCode.LEVEL_SHORTFALL, categories=categories,
                level=level, expected=need, observed=got,
                op_ids=tuple(sorted(set(ops_at.get(level, ())))),
                detail=(f"{names} на уровне «{shown}»: программа даёт {need}, "
                        f"в модели прибавилось {got}")))
        elif exact_group and got > need + floating:
            out.append(Mismatch(
                code=MismatchCode.LEVEL_OVERSHOOT, categories=categories,
                level=level, expected=need + floating, observed=got,
                op_ids=tuple(sorted(set(ops_at.get(level, ())))),
                detail=(f"{names} на уровне «{shown}»: туда могло попасть не "
                        f"более {need + floating}, прибавилось {got}")))
    return out


def check_acceptance(expectation: Expectation,
                     before: ScopeCensus,
                     after: ScopeCensus) -> Verdict:
    """Сверить ожидание с ПЕРЕЧИТАННОЙ переписью охвата. Чистая функция.

    ``before``/``after`` — счётчики (категория, уровень) → количество, снятые
    ДО и ПОСЛЕ постройки. Источник обязан быть ПОВТОРНЫМ ЧТЕНИЕМ модели, а не
    квитанцией постройки: квитанция говорит, что мы ПОПРОСИЛИ, перепись — что
    в модели ЕСТЬ, и расхождение этих двух и есть самая ценная находка (так
    30.07 вскрылось, что помещения всех моделей никогда не имели точки).
    Чистая функция отличить одно от другого не может; production-вызов обязан
    проходить через строгий ``acceptance_probe``/``acceptance_runtime``.
    """
    delta = census_delta(before, after)
    groups: dict[tuple[str, ...], list[ExpectedRow]] = {}
    if expectation.lower_bounds_valid:
        for row in expectation.rows:
            groups.setdefault(row.categories, []).append(row)

    # ВЕРХНЯЯ ГРАНИЦА ДОКАЗУЕМА НЕ ВЕЗДЕ, И ЭТО НЕ ОСТОРОЖНОСТЬ, А АРИФМЕТИКА.
    # Одна и та же категория может входить в ДВЕ группы сразу: create_floor
    # даёт («OST_Floors»), а create_foundation(variety=slab) — («OST_Floors»,
    # «OST_StructuralFoundation»), потому что плита это перекрытие либо
    # фундамент, решает тип. Дельта OST_Floors тогда учитывается в обеих
    # группах, и требование «не больше» соврало бы на ЧЕСТНОЙ постройке.
    # Тот же счёт с производными: лестница сама делает ограждения, и их
    # прибавка попала бы в счёт группы ограждений.
    group_count: dict[str, int] = {}
    for categories in groups:
        for category in categories:
            group_count[category] = group_count.get(category, 0) + 1
    derived_set = set(expectation.derived_categories)

    mismatches: list[Mismatch] = []
    checked = 0
    for categories, rows in sorted(groups.items()):
        if all(row.certainty is Certainty.UNKNOWN or row.count == 0
               for row in rows):
            continue
        exact_group = (expectation.upper_bounds_valid
                       and all(row.certainty is Certainty.EXACT
                               for row in rows)
                       and all(group_count[c] == 1 for c in categories)
                       and not (set(categories) & derived_set))
        observed = _observed_by_level(delta, categories)
        checked += 1
        mismatches.extend(_check_total(categories, rows, observed, exact_group))
        mismatches.extend(_check_levels(categories, rows, observed, exact_group))

    named = {category for row in expectation.rows for category in row.categories}
    named.update(expectation.derived_categories)
    unexpected = sorted(
        ((category, value) for category, value in _fold_by_category(delta).items()
         if category not in named and value),
        key=lambda item: (-item[1], item[0]))

    return Verdict(
        accepted=not mismatches,
        mismatches=tuple(mismatches),
        checked_groups=checked,
        unexpected=tuple(unexpected),
        upper_bounds_checked=(expectation.upper_bounds_valid
                              and expectation.lower_bounds_valid),
        blind_ops=expectation.blind_ops,
    )


def _fold_by_category(delta: Mapping[tuple[str, str], int]) -> dict[str, int]:
    """Свернуть дельту по категориям (уровень отброшен) — для справки."""
    out: dict[str, int] = {}
    for (category, _level), value in delta.items():
        out[category] = out.get(category, 0) + value
    return out


__all__ = [
    "LEVEL_NONE",
    "BlindOp",
    "Certainty",
    "ExpectedRow",
    "Expectation",
    "Mismatch",
    "MismatchCode",
    "ScopeCensus",
    "Verdict",
    "census_delta",
    "check_acceptance",
    "derive_expectation",
    "expectation_categories",
    "expectation_digest",
    "scope_census_from_elements",
]
