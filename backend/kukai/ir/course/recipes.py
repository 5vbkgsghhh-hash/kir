"""РАБОЧИЕ СКРИПТЫ — то, что можно скопировать, поправить числа и отправить.

ЗАКОН ЭТОГО ФАЙЛА: ПРИМЕР, КОТОРЫЙ НЕ ЗАПУСКАЛИ, — ЭТО ОБЕЩАНИЕ.
Каждый скрипт ниже прогоняется НАСТОЯЩЕЙ песочницей (`sandbox.
execute_author_script`, отдельный процесс, chroot, ноль сети) и его выход
компилируется `plan_program` + `ground` + `emit_program` на всех шести версиях
Revit. Числа `ops`/`elements` в `Recipe` — не оценка автора, а замер прогона:
`test_course.py` падает, если хоть одно разошлось.

ПАРЫ «ДЖУНИОР — СЕНЬОР». Половина рецептов существует парами: одна и та же
задача, один и тот же результат в элементах, разная ФОРМА. Разница обязана
читаться из чисел, а не из увещеваний, поэтому у каждой пары в
`Recipe.contrast` записано, что произойдёт ПРИ ПРАВКЕ — единственная величина,
в которой формы расходятся по-настоящему.

ЧЕГО ЗДЕСЬ НЕТ. Ни одного скрипта с numpy или shapely: в песочнице их нет и не
будет (недетерминизм ломает `author_digest`). Образцы из
`tools/design/examples/` написаны ДО песочницы и живут вне её — они показывают
форму мысли, а не то, что можно отправить.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Recipe:
    """Скрипт, его замеренные числа и то, чему он учит."""

    name: str
    title: str
    #: Исходник, готовый к отправке в поле `program_py`.
    source: str
    #: ЗАМЕР прогона: сколько операций скрипт положил в программу.
    ops: int
    #: ЗАМЕР: сколько элементов эти операции ОБЪЯВЛЯЮТ (производные не в счёт).
    elements: int
    #: ЧТО ИМЕННО покрывает скрипт. Пары сравнимы только при равном охвате, и
    #: «6 этажей против 2» — сравнение, которое вводит в заблуждение молча.
    covers: str = ""
    #: С чем сравнивать. Имя парного рецепта либо пусто.
    versus: str = ""
    #: Что случится при правке — величина, в которой формы расходятся.
    contrast: str = ""
    #: Уроки, которые этот скрипт показывает в работе.
    teaches: tuple[str, ...] = field(default_factory=tuple)

    @property
    def lines(self) -> int:
        return len([ln for ln in self.source.strip().splitlines() if ln.strip()])


# ═════════════════════════════════════════════════════════════════════════
# ЕДИНИЦА: сборка, которая ПЕРЕЖИВАЕТ скрипт
# ═════════════════════════════════════════════════════════════════════════

_CABIN_SENIOR = '''
# Кабинка санузла: собрать ОДИН раз, поставить по ряду, оставить ГРУППОЙ.
# В детском саду СОБ6.2 такая кабинка стоит 638 раз одним определением.
LVL = {"by": "name", "value": "Этаж 1"}
WT = {"by": "name", "value": "Кирпич 250"}
W, D, H = 1500, 1200, 2100          # ширина, глубина, высота перегородки
STEP, N = 1600, 6                   # шаг кабинок и сколько их в ряду

envelope(intent="ряд кабинок санузла")

# ЕДИНИЦА. Пишется ОДИН раз, в абсолютных координатах вхождения 0.
# placements — смещения ОСТАЛЬНЫХ вхождений; вхождение 0 это сами члены.
with unit("Кабинка су", placements=[(STEP * i, 0) for i in range(1, N)]):
    create_wall(p0_mm=(0, 0), p1_mm=(0, D), level=LVL, type=WT, height_mm=H)
    create_wall(p0_mm=(0, D), p1_mm=(W, D), level=LVL, type=WT, height_mm=H)
    create_wall(p0_mm=(W, D), p1_mm=(W, 0), level=LVL, type=WT, height_mm=H)

score()
'''

_CABIN_JUNIOR = '''
# Тот же ряд кабинок, но перечислением: N x 3 отдельных стены.
LVL = {"by": "name", "value": "Этаж 1"}
WT = {"by": "name", "value": "Кирпич 250"}
W, D, H = 1500, 1200, 2100
STEP, N = 1600, 6

envelope(intent="ряд кабинок санузла")
for i in range(N):
    x = STEP * i
    create_wall(p0_mm=(x, 0), p1_mm=(x, D), level=LVL, type=WT, height_mm=H)
    create_wall(p0_mm=(x, D), p1_mm=(x + W, D), level=LVL, type=WT, height_mm=H)
    create_wall(p0_mm=(x + W, D), p1_mm=(x + W, 0), level=LVL, type=WT,
                height_mm=H)

score()
'''

# ═════════════════════════════════════════════════════════════════════════
# ВИТРАЖ: три слоя, из которых пишутся два
# ═════════════════════════════════════════════════════════════════════════

_CURTAIN_SENIOR = '''
# Витраж. Тип НОСИТЕЛЯ рождает импосты и панель по умолчанию; пишутся только
# носитель, линии разрезки и ОТЛИЧИЯ ячеек. Замер K2: 92% импостов настоящей
# башни — type_driven, отдельного опа у импоста нет вовсе.
LVL = {"by": "name", "value": "Этаж 1"}
CURTAIN = {"by": "name", "value": "ЖБ 200"}   # ← ВИТРАЖНЫЙ тип из query_types
GLASS = {"by": "name", "value": "Кирпич 250"} # ← тип ПАНЕЛИ, не стены
L, H = 9000, 3300
COLS, ROWS = 6, 3

envelope(intent="витражная стена 9x3.3 м, сетка 6x3")

# СЛОЙ 1 — носитель. Тип здесь и есть главное решение задачи.
w = create_wall(p0_mm=(0, 0), p1_mm=(L, 0), level=LVL, type=CURTAIN,
                height_mm=H)

# СЛОЙ 2 — линии разрезки. host принимает element_id или РУЧКУ соседнего опа;
# формы by=name у слота цели записи нет вовсе.
for i in range(1, COLS):
    create_curtain_grid_line(host=w, direction="u",
                             position_mm=(L * i / COLS, 0, 0))
for j in range(1, ROWS):
    create_curtain_grid_line(host=w, direction="v",
                             position_mm=(0, 0, H * j / ROWS))

# СЛОЙ 3 — только ОТЛИЧИЯ. Нижний ряд глухой, остальное даёт тип носителя.
# У panel_type НЕТ правила по умолчанию: {"by":"default"} тут отказ.
for u in range(1, COLS + 1):
    set_curtain_panel(host=w, u=u, v=1, panel_type=GLASS)

print("написано опов:", len(kir.current()),
      "| ячеек", COLS * ROWS, "| импосты и панели рождает ТИП")
score()
'''

_CURTAIN_JUNIOR = '''
# Тот же витраж «в лоб»: каждая ячейка названа поимённо, будто панель надо
# ставить руками. Импост поставить нечем вовсе — опа нет, и это не пробел.
LVL = {"by": "name", "value": "Этаж 1"}
CURTAIN = {"by": "name", "value": "ЖБ 200"}
GLASS = {"by": "name", "value": "Кирпич 250"}
L, H = 9000, 3300
COLS, ROWS = 6, 3

envelope(intent="витражная стена 9x3.3 м, сетка 6x3")
w = create_wall(p0_mm=(0, 0), p1_mm=(L, 0), level=LVL, type=CURTAIN,
                height_mm=H)
for i in range(1, COLS):
    create_curtain_grid_line(host=w, direction="u",
                             position_mm=(L * i / COLS, 0, 0))
for j in range(1, ROWS):
    create_curtain_grid_line(host=w, direction="v",
                             position_mm=(0, 0, H * j / ROWS))
for u in range(1, COLS + 1):
    for v in range(1, ROWS + 1):
        set_curtain_panel(host=w, u=u, v=v, panel_type=GLASS)

score()
'''

# ═════════════════════════════════════════════════════════════════════════
# ЭТАЖ И ЗДАНИЕ: функция единицы, цикл размещения, ПАЧКА программ
# ═════════════════════════════════════════════════════════════════════════

_STOREY = '''
# Типовой этаж функцией, здание циклом. Замер: в демо-доме 64 уровня дают
# 23 различных набора типов — этаж там ГОТОВАЯ повторяющаяся единица.
# В K2 (башня) 58 уровней дают 41 набор: там повторяется не этаж, а его части.
import math

WT = {"by": "name", "value": "Кирпич 250"}
FT = {"by": "name", "value": "Монолит 200"}
A, B, HH = 18000, 12000, 3300
FLOORS = 6                          # этажей В ЭТОЙ программе, см. бюджет ниже

envelope(intent="жилой блок 18x12, %d типовых этажа" % FLOORS)

def storey(level, tag):
    """ЕДИНИЦА. Принимает РУЧКУ уровня и возвращает ручки своих стен.
    level обязателен у каждого опа: defaults конверта его НЕ заполнит."""
    box = [(0, 0), (A, 0), (A, B), (0, B)]
    walls = [create_wall(p0_mm=p, p1_mm=q, level=level, type=WT, height_mm=HH)
             for p, q in zip(box, box[1:] + box[:1])]
    create_floor(outline=box, level=level, type=FT)
    create_room(xy=(A // 2, B // 2), level=level, name="Квартира %s" % tag)
    create_door(host=walls[0], offset_mm=A // 2, sill_mm=0)
    create_window(host=walls[2], offset_mm=A // 2, sill_mm=900)
    return walls

for i in range(FLOORS):
    lvl = create_level(elev_mm=i * HH, name="Этаж %d" % (i + 1))
    storey(lvl, i + 1)

# БЮДЖЕТ СЧИТАЕТСЯ, А НЕ ВСПОМИНАЕТСЯ: опы на этаж берутся из самой
# программы, иначе число разъедется с первой же правкой функции.
budget = kir.MAX_BULK_OPS
per_storey = len(kir.current()) // FLOORS
print("этажей", FLOORS, "| опов", len(kir.current()), "из", budget,
      "| на этаж", per_storey)
print("влезает этажей в одну программу:", budget // per_storey,
      "| следующая программа начинается с этажа", FLOORS + 1)
score()
'''

_STOREY_JUNIOR = '''
# Тот же блок, но этаж переписан заново для каждого уровня: единица не
# названа, поэтому её негде поправить один раз.
WT = {"by": "name", "value": "Кирпич 250"}
FT = {"by": "name", "value": "Монолит 200"}
A, B, HH = 18000, 12000, 3300

envelope(intent="жилой блок 18x12, 6 типовых этажей")

l1 = create_level(elev_mm=0, name="Этаж 1")
w1 = create_wall(p0_mm=(0, 0), p1_mm=(A, 0), level=l1, type=WT, height_mm=HH)
create_wall(p0_mm=(A, 0), p1_mm=(A, B), level=l1, type=WT, height_mm=HH)
w3 = create_wall(p0_mm=(A, B), p1_mm=(0, B), level=l1, type=WT, height_mm=HH)
create_wall(p0_mm=(0, B), p1_mm=(0, 0), level=l1, type=WT, height_mm=HH)
create_floor(outline=[(0, 0), (A, 0), (A, B), (0, B)], level=l1, type=FT)
create_room(xy=(A // 2, B // 2), level=l1, name="Квартира 1")
create_door(host=w1, offset_mm=A // 2, sill_mm=0)
create_window(host=w3, offset_mm=A // 2, sill_mm=900)

l2 = create_level(elev_mm=HH, name="Этаж 2")
w1 = create_wall(p0_mm=(0, 0), p1_mm=(A, 0), level=l2, type=WT, height_mm=HH)
create_wall(p0_mm=(A, 0), p1_mm=(A, B), level=l2, type=WT, height_mm=HH)
w3 = create_wall(p0_mm=(A, B), p1_mm=(0, B), level=l2, type=WT, height_mm=HH)
create_wall(p0_mm=(0, B), p1_mm=(0, 0), level=l2, type=WT, height_mm=HH)
create_floor(outline=[(0, 0), (A, 0), (A, B), (0, B)], level=l2, type=FT)
create_room(xy=(A // 2, B // 2), level=l2, name="Квартира 2")
create_door(host=w1, offset_mm=A // 2, sill_mm=0)
create_window(host=w3, offset_mm=A // 2, sill_mm=900)

# …и так ещё четыре раза.
score()
'''

# ═════════════════════════════════════════════════════════════════════════
# ЗДАНИЕ ЦЕЛИКОМ: уровни + этаж + КОМНАТНАЯ единица группой
# ═════════════════════════════════════════════════════════════════════════

_BUILDING = '''
# Метод целиком: смоделировать единицу -> собрать этаж -> сделать группой ->
# тиражировать. Замер тиражируемого определения в корпусе: медиана 11 членов в
# K2 и 50 в ВК Snowdon — то есть группа это КОМНАТНАЯ сборка, не элемент и не
# этаж целиком.
LVL = {"by": "name", "value": "Этаж 1"}
WT = {"by": "name", "value": "Кирпич 250"}
CORE_W, CORE_D, HH = 3000, 5000, 3300
BAYS = 4                            # секций вдоль фасада
PITCH = 7500                        # шаг секции

envelope(intent="этаж: 4 секции с типовым санузловым блоком")

# 1. ЕДИНИЦА — санузловый блок. Одно определение, BAYS вхождений.
with unit("Блок санузла", placements=[(PITCH * i, 0) for i in range(1, BAYS)]):
    create_wall(p0_mm=(0, 0), p1_mm=(CORE_W, 0), level=LVL, type=WT,
                height_mm=HH)
    create_wall(p0_mm=(CORE_W, 0), p1_mm=(CORE_W, CORE_D), level=LVL, type=WT,
                height_mm=HH)
    create_wall(p0_mm=(CORE_W, CORE_D), p1_mm=(0, CORE_D), level=LVL, type=WT,
                height_mm=HH)

# 2. ОБОЛОЧКА этажа — она у каждой секции РАЗНАЯ по координате, но одинаковая
#    по составу: это цикл, а не группа.
for i in range(BAYS):
    x = PITCH * i
    w = create_wall(p0_mm=(x, 0), p1_mm=(x + PITCH, 0), level=LVL, type=WT,
                    height_mm=HH)
    create_window(host=w, offset_mm=PITCH // 2, sill_mm=900)
    create_room(xy=(x + PITCH // 2, CORE_D + 2000), level=LVL,
                name="Квартира %d" % (i + 1))

score()
'''

# ═════════════════════════════════════════════════════════════════════════
# СИЛУЭТ: питон считает, KIR строит, расхождение НАЗВАНО числом
# ═════════════════════════════════════════════════════════════════════════

_SILHOUETTE = '''
# Башня с талией. Профиль синусоидальный, программа строит ломаную — и
# расхождение приближения ПЕЧАТАЕТСЯ ЧИСЛОМ. Сказать «синус» и построить
# ломаную, не назвав расхождение, — молчаливо неверный ответ.
# Импорт разрешён ровно: math, itertools, functools.
import math

R, WAIST = 22000.0, 0.30            # радиус базы и ужатие в талии
STOREYS, H = 12, 4000.0             # этажей в ЭТОЙ программе и высота этажа
COLUMNS = 8
SYM = {"by": "name", "value": "К 300x300"}

envelope(intent="башня с талией, этажи 1..%d" % STOREYS)

def scale(t):
    """Талия: 1.0 у земли и на макушке, минимум посередине."""
    return 1.0 - WAIST * math.sin(math.pi * t)

def ring(radius, n):
    return [(round(radius * math.cos(2 * math.pi * k / n)),
             round(radius * math.sin(2 * math.pi * k / n))) for k in range(n)]

for i in range(STOREYS):
    t = i / float(STOREYS - 1)
    lvl = create_level(elev_mm=round(i * H), name="Этаж %d" % (i + 1))
    for xy in ring(R * scale(t), COLUMNS):
        create_column(xy=xy, level=lvl, symbol=SYM)

# ЧЕСТНОЕ ПРИБЛИЖЕНИЕ: чем ломаная по этажам расходится с настоящим синусом.
worst = 0.0
for k in range(201):
    t = k / 200.0
    seg = min(int(t * (STOREYS - 1)), STOREYS - 2)
    t0, t1 = seg / (STOREYS - 1.0), (seg + 1) / (STOREYS - 1.0)
    a = (t - t0) / (t1 - t0)
    worst = max(worst, abs(scale(t) - (scale(t0) * (1 - a) + scale(t1) * a)))
print("ломаная против синуса: %.0f мм по радиусу" % (worst * R))
print("этажей %d из 59: здание это ПАЧКА программ" % STOREYS)
score()
'''


RECIPES: dict[str, Recipe] = {r.name: r for r in (
    Recipe(
        name="санузел", title="повторяющаяся единица группой Revit",
        source=_CABIN_SENIOR, ops=1, elements=18, covers="6 кабинок",
        versus="санузел-джуниор",
        contrast="в модели ОДНО определение и 6 вхождений: человек правит одно "
                 "— меняются все шесть. В скрипте правка тоже одна",
        teaches=("единица",)),
    Recipe(
        name="санузел-джуниор", title="тот же ряд перечислением",
        source=_CABIN_JUNIOR, ops=18, elements=18, covers="6 кабинок",
        versus="санузел",
        contrast="в модели 18 несвязанных стен: человек правит 18 раз, и связи "
                 "между ними не существует вовсе. Скрипт при этом КОРОЧЕ",
        teaches=("единица", "форма")),
    Recipe(
        name="витраж", title="носитель, линии разрезки, отличия ячеек",
        source=_CURTAIN_SENIOR, ops=14, elements=14, covers="витраж 6x3 ячеек",
        versus="витраж-джуниор",
        contrast="назначено 6 ячеек из 18: остальные 12 даёт ТИП носителя. "
                 "Сменить остекление всего витража — правка ТИПА, не программы",
        teaches=("витраж", "даром")),
    Recipe(
        name="витраж-джуниор", title="каждая ячейка названа поимённо",
        source=_CURTAIN_JUNIOR, ops=26, elements=26, covers="витраж 6x3 ячеек",
        versus="витраж",
        contrast="назначены все 18 ячеек: 12 из них повторяют умолчание типа, "
                 "то есть это 12 лишних назначений и 12 правок при смене стекла",
        teaches=("витраж", "даром")),
    Recipe(
        name="этаж", title="этаж функцией, здание циклом, бюджет вслух",
        source=_STOREY, ops=54, elements=54, covers="6 этажей",
        versus="этаж-джуниор",
        contrast="единица НАЗВАНА функцией: правка окна — одна строка на все "
                 "этажи, число этажей — одно число",
        teaches=("этаж",)),
    Recipe(
        name="этаж-джуниор", title="этаж переписан для каждого уровня",
        source=_STOREY_JUNIOR, ops=18, elements=18, covers="2 этажа из 6",
        versus="этаж",
        contrast="ДВА этажа из шести уже стоят 26 строк: шесть будут ~62 при "
                 "тех же 54 операциях. Единицы нет — правка окна идёт по "
                 "строке на этаж, и два этажа разъезжаются незаметно",
        teaches=("этаж", "форма")),
    Recipe(
        name="здание", title="единица группой + оболочка циклом",
        source=_BUILDING, ops=13, elements=24, covers="этаж из 4 секций",
        contrast="группа там, где сборка повторяется ТОЖДЕСТВЕННО; цикл там, "
                 "где меняется координата. Смешивать не надо",
        teaches=("единица", "этаж")),
    Recipe(
        name="силуэт", title="питон считает форму, расхождение названо числом",
        source=_SILHOUETTE, ops=108, elements=108, covers="12 этажей из 59",
        contrast="приближение НАЗВАНО в мм: неназванное приближение — "
                 "молчаливо неверный ответ",
        teaches=("этаж", "границы")),
)}

#: Порядок в оглавлении: сперва метод, потом разобранный случай, потом форма.
ORDER: tuple[str, ...] = (
    "санузел", "санузел-джуниор", "витраж", "витраж-джуниор",
    "этаж", "этаж-джуниор", "здание", "силуэт")


__all__ = ["ORDER", "RECIPES", "Recipe"]
