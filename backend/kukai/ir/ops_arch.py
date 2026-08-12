"""ops_arch — АР-содержимое, которого у компилятора не было: потолки и
ограждения.

Registry module — см. REGISTRY_MODULES.md. Операции добавляются СЮДА, а не в
spec.py. Эмиттеры живут в arch_emit.py (парный файл, ровно как
ops_struct.py + struct_emit.py у волны каркаса); authoring.py получает лишь
импорт и две строки в _EMITTERS.

ЗАЧЕМ ВОЛНА. Полный слепок 13A-RD-AR-K2_v33 (башня 59 этажей, 55 293
элемента) показал: часть модели не выражается не из-за кривого лифтера, а
потому что ОПЕРАЦИИ НЕТ ВООБЩЕ. Карта причин лифта (коммит 9c63cc4e) назвала
шесть категорий, которые «не FamilyInstance и опа не имеют», и две из них —
Ceilings 81 и StairsRailing 203 — есть в КАЖДОМ архитектурном проекте. До
этой волны в реестре было 32 писателя и ни одного потолка.

ДВА ЗАМЕРА, ФОРМИРУЮЩИЕ ЭТИ ОПЫ (компиляция на :52412, 2021-2026, 29.07 —
имена API у нас проверяются компиляцией, а не памятью, см. extract.py про
_CATEGORY_SPECS):

  Ceiling.Create(doc, IList<CurveLoop>, typeId, levelId)  → 2022-2026, 5/6
      2021: CS0117 'Ceiling' does not contain a definition for 'Create'
  doc.Create.NewCeiling(...)                              → 0/6, НИ ОДНОЙ
      CS1061 'Document' does not contain a definition for 'NewCeiling'

Второй замер важнее первого: у потолка на Revit 2021 нет не «другой
перегрузки», а НИКАКОГО пути создания вообще. Поэтому ось версий здесь — не
развилка эмиссии (как у create_floor, где 2021 уходит на legacy NewFloor), а
типизированный отказ KIR-E003. Построить вместо потолка перекрытие «чтобы
ворота были зелёные» — ровно тот Гудхарт, который в этом доме стоил 96%
групп: «сделал что-то другое» читается снаружи как успех.

  Railing.Create(doc, CurveLoop, typeId, levelId)               → 6/6
  Railing.Create(doc, hostId, typeId, RailingPlacementPosition) → 6/6
  RailingPlacementPosition.Treads / .Stringer                   → 6/6
  RailingPlacementPosition.Left/.Right/.Landing/.Run/.None      → 0/6
  ElementTypeGroup.RailingType                                  → 0/6

У ограждения оси версий нет вовсе. Зато есть два ЗАМЕРЕННЫХ следствия:

1. Родов размещения ДВА, потому что в API две перегрузки: свободное
   ограждение по своему пути и ограждение, ПРИНАДЛЕЖАЩЕЕ лестнице/пандусу.
   На K2 второй род и есть вся популяция (OST_StairsRailing 203). Свести их
   к одному значило бы выдумать путь там, где источник даёт хозяина.
   Разделение сделано полем `variety` — тем же приёмом и тем же именем, что
   у create_foundation (реестр держит слово «kind» за словарём родов
   объектов Revit, см. NAMING NOTE в ops_struct.py).

2. У ограждения НЕТ типа по умолчанию в документе: ElementTypeGroup.
   RailingType не компилируется ни на одной версии, тогда как
   ElementTypeGroup.CeilingType компилируется на всех шести. Поэтому
   create_ceiling МОГ БЫ иметь ветку doc_default (как create_floor), а
   create_railing — не может ни при каком желании. Оба намеренно оставлены
   вне списка doc_default в ground.py: пропущенный `type` идёт по общему
   правилу «единственный в пуле, иначе типизированный вопрос». Для потолка
   это сознательный отказ от доступной поблажки — «тип по умолчанию» на
   чужом здании почти никогда не тот тип, который был в источнике, а
   молчаливая подмена типа неотличима от успеха.

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ (§18.1, «тихая потеря запрещена»):

* УКЛОН ПОТОЛКА. Перегрузка Ceiling.Create с (Line slopeArrow, double slope)
  компилируется (5/6, та же ось), но СЕМАНТИКА второго аргумента офлайн
  непроверяема: отношение подъёма к заложению или радианы — компилятор молчит
  об этом одинаково. Ставить параметр, единица измерения которого угадана,
  значит завести ровно ту ошибку, что уже стоила 96% групп («0 градусов
  вместо отсутствия угла»). Поэтому уклона в опе НЕТ, а лифтер обязан
  ОТКАЗАТЬ на наклонном потолке, а не выдать его плоским. Плоский потолок
  вместо наклонного — не приближение, а неправда.
* СМЕЩЕНИЕ ОГРАЖДЕНИЯ ОТ УРОВНЯ. Ни одно из пяти правдоподобных имён
  (STAIRS_RAILING_HEIGHT_OFFSET_PARAM, STAIRS_RAILING_BASE_OFFSET_PARAM,
  RAILING_HEIGHT_OFFSET, RAILING_SYSTEM_*_OFFSET_PARAM, ...) не существует
  ни на одной версии — замерено. Параметра, которого нет в API, в опе тоже
  нет; лифтер обязан отказать на ограждении со смещением, а не обнулить его.
  Смещение потолка, наоборот, ЕСТЬ: CEILING_HEIGHTABOVELEVEL_PARAM, 6/6.

CONTOUR У ПОТОЛКА (09.08.2026). У create_ceiling появился ВТОРОЙ вход формы —
необязательный `contour` рода `region`, то есть весь язык эскиза из
contour.py (rect/l/poly с малыми дугами, до 8 отверстий, точки-пересечения
осей). Три вещи, которые здесь важны и каждая проверена, а не предположена:

1. `outline`/`holes` ОСТАЛИСЬ и не изменились ни на байт. Обратный ход
   (decompile/lift.py::_lift_ceiling -> materialize) эмитирует именно их;
   замена разомкнула бы круг на каждом потолке каждого разобранного здания.
   Взаимное исключение — типизированный KIR-P007 в компиляторе, ровно как у
   place_family; схема «одно из двух» не выражает.
2. ДУГА — НЕ УКРАШЕНИЕ. Ломаная `outline` не может выразить закруглённый
   край: она даёт ДРУГУЮ форму, а не приближение. Это тот же класс, что
   «плоский потолок вместо наклонного» абзацем выше.
3. ОСЬ ВЕРСИЙ У КОНТУРНОЙ ВЕТКИ ТА ЖЕ, ЧТО У ПРЯМОЙ, И ЭТО ПЕРЕПРОВЕРЕНО
   09.08 по эталонным сборкам, а не по памяти: в
   revit_all_main_versions_api_x64/2021.0.0/.../RevitAPI.xml тип
   `T:Autodesk.Revit.DB.Ceiling` ЕСТЬ, а членов `M:...Ceiling.*` — НОЛЬ
   (в 2022 и 2026 там обе перегрузки `Ceiling.Create`); строки `NewCeiling`
   нет ни в одном из XML и ни в одном из RevitAPI.dll 2021/2022/2026.
   Значит у потолка на 2021 нет ни `IList<CurveLoop>`-пути, ни legacy-пути
   `CurveArray` — В ОТЛИЧИЕ от create_floor_by_contour, который на 2021
   уходит на doc.Create.NewFloor(CurveArray, ...). Поэтому контурная ветка
   потолка НЕ получает `emit_curvearray_cs`: на 2021 отказывает вся
   операция целиком (KIR-E003), до всякого разбора формы.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)

#: `create_railing.position` словами <-> члены RailingPlacementPosition.
#: ОДНА таблица на эмиттер и лифт, чтобы два направления не разъехались —
#: тот же приём, что WALL_LOCATION_LINE_ORDINALS у create_wall. Ровно два
#: члена, потому что замер даёт ровно два: .Left/.Right/.Landing/.Run/.None/
#: .Center не компилируются ни на одной из шести версий, хотя «левое/правое»
#: — первое, что приходит в голову и что написал бы человек по памяти.
RAILING_PLACEMENT_MEMBERS = {
    "treads": "Treads",
    "stringer": "Stringer",
}

OPS = [
    OpSpec(
            name="create_ceiling",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # РОВНО ОДНО ИЗ ДВУХ: `outline` (прямая ломаная) ЛИБО
                # `contour` (типизированный эскиз CONTOUR). Поэтому `outline`
                # перестал быть required НА УРОВНЕ СХЕМЫ: обязательность
                # стала ВЗАИМНОЙ, а взаимную схема выразить не может — она
                # живёт в компиляторе типизированным KIR-P007, тем же приёмом
                # и по той же причине, что у place_family (xyz против
                # p0_mm/p1_mm). Оба поля сразу неоднозначны («какое из двух
                # описаний формы истинно?»), ни одного — операция без формы;
                # угадать за автора значит построить не тот потолок молча.
                #
                # ЗАМЕНЫ НЕ ПРОИЗОШЛО, И ЭТО РЕШЕНИЕ, А НЕ ОСТОРОЖНОСТЬ:
                # обратный ход (decompile/materialize.py) эмитирует
                # `outline`/`holes`, и если бы прямые точки исчезли, круг
                # разомкнулся бы на каждом потолке каждого разобранного
                # здания.
                ParamSpec("outline", "pts"),   # >=3 [x,y] мм
                ParamSpec("holes", "pts_list"),
                # CONTOUR (v2.0, 17.07): rect/l/poly с малыми дугами, до 8
                # отверстий, точки — литералы или пересечения осей. Дуга в
                # плане потолка прямыми точками невыразима ВООБЩЕ: `outline`
                # — ломаная, и закруглённый край подвесного потолка под ней
                # становится многоугольником, то есть ДРУГОЙ формой, а не
                # приближением. Отверстия у региона свои, поэтому `holes`
                # вместе с `contour` — тоже KIR-P007: два описания проёмов
                # означали бы, что одно из них молча выброшено.
                ParamSpec("contour", "region"),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                ParamSpec("type", "sel"),
                # Смещение потолка от уровня — ЕДИНСТВЕННАЯ вертикальная
                # степень свободы, у которой есть замеренный BuiltInParameter
                # (CEILING_HEIGHTABOVELEVEL_PARAM, 6/6). Без default: нет
                # параметра — нет строки в C#, отсутствие остаётся
                # отсутствием, а не нулём.
                ParamSpec("height_offset_mm", "mm", min_val=-15_000,
                          max_val=15_000),
            ),
            capability=(("create", "element"),),
            # Точка с запятой РАЗДЕЛЯЕТ обязательства (translation_cert.py
            # бьёт post именно по ней и требует свидетеля на каждый кусок),
            # поэтому внутри скобок её быть не должно — иначе примечание про
            # 2021 превращается в отдельное «обещание без свидетеля».
            post=("ceiling exists on Revit 2022+ (на 2021 операция невозможна "
                  "по построению — типизированный отказ KIR-E003, пути "
                  "создания потолка в API нет ни на одной версии); "
                  "level binding == resolved level (topology); "
                  "bbox XY extents == outline or contour extents (±50mm, arc "
                  "extremes included, computed at compile time); "
                  "height offset param == height_offset_mm when given (±1mm)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("type", "ceiling_types", False)),
            tolerances={"bbox_mm": 50.0, "height_offset_mm": 1.0},
        ),
    OpSpec(
            name="create_railing",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # Род размещения — закрытое множество из ДВУХ перегрузок
                # Railing.Create, а не из вкусов. См. модульную шапку.
                ParamSpec("variety", "enum", required=True,
                          choices=("path", "hosted")),
                # variety="path": открытая ломаная 2..64 точек. Свой род
                # параметра, НЕ "pts": контур `pts` требует >=3 точек и
                # ненулевой площади, то есть по построению замкнут, а прямое
                # ограждение — это две точки и нулевая площадь.
                ParamSpec("path", "path"),
                ParamSpec("level", "sel",
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # variety="hosted": лестница/пандус-владелец. target_w — тот
                # же род ссылки, которым create_window адресует свою стену,
                # значит ссылка на create_stairs той же программы работает
                # без нового механизма.
                ParamSpec("host", "target_w"),
                ParamSpec("position", "enum",
                          choices=tuple(RAILING_PLACEMENT_MEMBERS)),
                ParamSpec("type", "sel"),
            ),
            capability=(("create", "element"),),
            # ОБЕЩАНО РОВНО ТО, ЧТО ПРОВЕРЯЕТСЯ. Прежняя редакция обещала
            # ещё и «type == resolved railing type», хотя свидетеля на тип
            # эмиттер не ставит (как и create_floor) — аудит сертификата это
            # поймал, и правильный ответ здесь снять обещание, а не подобрать
            # ему формулировку, проходящую сверку.
            post=("railing exists; "
                  "variety=path: базовый уровень == resolved level (topology) "
                  "и путь ограждения == path (±50mm по габариту, ОТКРЫТАЯ "
                  "ломаная — замыкающего сегмента не добавляется); "
                  "variety=hosted: КАЖДОЕ созданное ограждение принадлежит "
                  "запрошенному хосту (HasHost/HostId, topology)"),
            writes_model=True,
            grounded=(("level", "levels", False),
                      ("type", "railing_types", False)),
            tolerances={"bbox_mm": 50.0},
        ),
]
