"""WORKING SCRIPTS — things you can copy, fix the numbers in, and send.

THE LAW OF THIS FILE: AN EXAMPLE THAT WAS NEVER RUN IS A PROMISE.
Every script below is run through the REAL sandbox (`sandbox.
execute_author_script`, a separate process, chroot, zero network), and its
output is compiled with `plan_program` + `ground` + `emit_program` on all
six Revit versions. The `ops`/`elements` numbers in `Recipe` are not the
author's estimate but a measurement of the run: `test_course.py` fails if
even one has diverged.

"JUNIOR — SENIOR" PAIRS. Half the recipes exist as pairs: the same task,
the same result in elements, a different SHAPE. The difference must be
readable from the numbers, not from exhortation, so for each pair
`Recipe.contrast` records what will happen ON EDITING — the one quantity
where the shapes genuinely diverge.

WHAT IS NOT HERE. Not a single script with numpy or shapely: the sandbox
does not have them and never will (nondeterminism breaks `author_digest`).
The samples in `tools/design/examples/` were written BEFORE the sandbox
and live outside it — they show a shape of thought, not something you can
send.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Recipe:
    """A script, its measured numbers, and what it teaches."""

    name: str
    title: str
    #: Source ready to be sent in the `program_py` field.
    source: str
    #: MEASUREMENT of the run: how many operations the script put into the
    #: program.
    ops: int
    #: MEASUREMENT: how many elements these operations DECLARE (derived
    #: ones do not count).
    elements: int
    #: WHAT EXACTLY the script covers. Pairs are only comparable at equal
    #: scope, and "6 floors against 2" is a comparison that misleads
    #: silently.
    covers: str = ""
    #: What to compare against. The name of the paired recipe, or empty.
    versus: str = ""
    #: What happens on editing — the quantity where the shapes diverge.
    contrast: str = ""
    #: The lessons this script demonstrates in action.
    teaches: tuple[str, ...] = field(default_factory=tuple)

    @property
    def lines(self) -> int:
        return len([ln for ln in self.source.strip().splitlines() if ln.strip()])


# ═════════════════════════════════════════════════════════════════════════
# UNIT: an assembly that OUTLIVES the script
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
# CURTAIN WALL: three layers, of which two are authored
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
# FLOOR AND BUILDING: a unit function, a placement loop, a BATCH of programs
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
# THE WHOLE BUILDING: levels + floor + a ROOM unit as a group
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
# SILHOUETTE: python computes, KIR builds, the discrepancy is NAMED by a number
# ═════════════════════════════════════════════════════════════════════════

_SILHOUETTE = '''
# Башня с талией. Профиль синусоидальный, программа строит ломаную — и
# расхождение приближения ПЕЧАТАЕТСЯ ЧИСЛОМ. Сказать «синус» и построить
# ломаную, не назвав расхождение, — молчаливо неверный ответ.
# Белый список импортов перечисляет сам отказ KIR-B004 — здесь нужен math.
import math

R, WAIST = 22000.0, 0.30            # радиус базы и ужатие в талии
STOREYS, H = 12, 4000.0             # этажей в ЭТОЙ программе и высота этажа
# ОДИН ЭТАЖ — НЕ БАШНЯ. Талия это РАЗНИЦА между этажами, у одного её нет, и
# делить на STOREYS-1 нечем. Край назван ЗДЕСЬ, потому что рецепт написан,
# чтобы его КОПИРОВАЛИ и меняли числа: край, о котором молчит сам скрипт,
# автор находит ZeroDivisionError'ом — отказом без причины и без следующего
# хода, за то, что поставил единицу туда, куда рецепт сам зовёт ставить
# числа. (Аудит 29.08.2026, F-305.)
# raise, а не assert: assert исчезает под -O, и скрипт, переставший проверять
# себя от флага интерпретатора, — тот самый молчаливый род.
if STOREYS < 2:
    raise ValueError("силуэт нужен минимум ДВУМ этажам: талия — это разница "
                     "между ними. Для одного этажа берите recipe('этаж')")
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
# ВТОРОЙ КРАЙ ТОГО ЖЕ РОДА, И ОН ТИШЕ ПЕРВОГО. При STOREYS=2 расхождение
# 6600 мм на радиусе 22 000 — почти треть радиуса, — и печаталось оно ТЕМ ЖЕ
# спокойным тоном, что и 67 мм при двенадцати. Автор получал «башню с
# талией», у которой талии нет, и число об этом читал как справочное.
# 5 % — НАЗНАЧЕНО, не измерено, и сказано это вслух: величина, при которой
# ломаная перестаёт читаться глазом как кривая. Важно не само число, а то,
# что порог НАЗВАН и стоит рядом со своим замером.
if worst > 0.05:
    print("  ^ это больше 5% радиуса: этажей мало, «талии» на такой ломаной "
          "НЕТ. Увеличьте STOREYS либо не называйте это силуэтом.")
print("этажей %d из 59: здание это ПАЧКА программ" % STOREYS)
score()
'''


# ═════════════════════════════════════════════════════════════════════════
# HOUSING THE JUDGE UNDERTAKES TO JUDGE
# ═════════════════════════════════════════════════════════════════════════

#: 🔴 WHY THIS RECIPE WAS SET UP (31.08.2026, finding `E-75`).
#: Not one recipe in the course carried through to a program the judge
#: actually EVALUATES. On the "building", `design_check` printed «ОЦЕНЕНО 0
#: ПРАВИЛ ИЗ 20» and the blocking `HAB000: model has no rooms`. The judge,
#: for its part, behaved impeccably: it named the cause and the NEXT MOVE,
#: and the move worked — but the road "built -> the judge said YES" did
#: not have a SINGLE instance in the delivery. Here it does.
#:
#: The target was named as a NUMBER BEFORE the fix and did not move
#: afterward: 2 -> at least 12 rules out of 20. 13 were achieved, and the
#: remaining seven are named by name:
#:   HAB003, HAB004, HAB031, HAB042, HAB050  are taken off by the STAGE
#:       PROFILE — they are not evaluated by construction on a concept
#:       program;
#:   HAB011, HAB012  require a BUILT element: `create_stairs_run`
#:       addresses its target only by the `element_id` of an
#:       already-created staircase, and the self-check runs without Revit.
#:       Unreachable here, not forgotten.
#: In other words, 13 is not "however many came out", but the CEILING of
#: the self-check.
_JUDGED_DWELLING = '''
# Судимое жильё: программа, на которую судья отвечает ПРИГОДЕН, а не «не оценено».
# Дом — ПАЧКА программ: лестница владеет своими транзакциями и живёт отдельной
# программой (KIR-L002), поэтому здесь их две, и вердикт берётся у пачки целиком.
L1 = {"by": "name", "value": "Этаж 1"}
L2 = {"by": "name", "value": "Этаж 2"}
WT = {"by": "name", "value": "Кирпич 250"}
W, D, H = 9000, 8000, 3000
XS, YS = 6000, 4000              # оси внутренних стен

# 1. ЛЕСТНИЦА — отдельной программой, ПЕРВОЙ. Марш задаётся ЗДЕСЬ: без него
# живая дверь отвечает KIR-P007 («марш не задан»), а самопроверка молчит —
# рецепт обещал вердикт программой, которую нельзя построить (замер 03.09.2026).
envelope(intent="судимое жильё: лестница")
create_stairs(base_level=L1, top_level=L2,
              p0_mm=[XS + 1500, YS + 1000], p1_mm=[XS + 1500, D - 1000])
stairs = build()

# 2. ТЕЛО — второй, чтобы числа рецепта описывали ЖИЛЬЁ, а не лестницу.
reset(intent="судимое жильё: два уровня, четыре помещения")
create_level(name="Этаж 1", elev_mm=0)
create_level(name="Этаж 2", elev_mm=H)

def box(pts, level):
    return [create_wall(p0_mm=pts[i], p1_mm=pts[(i + 1) % len(pts)],
                        level=level, type=WT, height_mm=H)
            for i in range(len(pts))]

outer = [(0, 0), (W, 0), (W, D), (0, D)]
south, east, north, west = box(outer, L1)
spine = create_wall(p0_mm=(XS, 0), p1_mm=(XS, D), level=L1, type=WT, height_mm=H)
belt = create_wall(p0_mm=(0, YS), p1_mm=(W, YS), level=L1, type=WT, height_mm=H)
create_floor_by_contour(contour={"outer": {"shape": "poly", "points_mm": outer}},
                        level=L1)

# Вход ведёт в ОБЩУЮ ЗОНУ, квартира примыкает к ней ОДНОЙ дверью: два входа в
# общую зону судья считает ошибкой замысла (HAB002), и это правило жилья.
create_door(host=east, offset_mm=6000, sill_mm=0)
create_door(host=spine, offset_mm=6000, sill_mm=0)
create_door(host=belt, offset_mm=3000, sill_mm=0)
create_door(host=spine, offset_mm=2000, sill_mm=0)

# Жилой комнате и кухне наружное окно ОБЯЗАТЕЛЬНО (HAB030).
create_window(host=north, offset_mm=W - 3000, sill_mm=900)
create_window(host=south, offset_mm=5000, sill_mm=900)

# Высота помещения задаётся ЯВНО: без неё Ревит ставит своё умолчание
# 8 футов (2438 мм), и судья ПОСТРОЕННОГО отвечает HAB022 «ниже минимума
# 2500» — при стенах в 3000. Замер на живом Ревите 03.09.2026.
create_room(xy=(XS // 2, (YS + D) // 2), level=L1, name="Комната",
            upper_offset_mm=H)
create_room(xy=(XS // 2, YS // 2), level=L1, name="Кухня",
            upper_offset_mm=H)
create_room(xy=((XS + W) // 2, YS // 2), level=L1, name="Санузел",
            upper_offset_mm=H)
create_room(xy=((XS + W) // 2, (YS + D) // 2), level=L1,
            name="Лестничная клетка", upper_offset_mm=H)

# Второй уровень: лестница обслуживает его, значит помещение с функцией
# «лестница» обязано быть и здесь, иначе HAB001/HAB010 не оценятся вовсе.
up = [(XS, YS), (W, YS), (W, D), (XS, D)]
box(up, L2)
create_floor_by_contour(contour={"outer": {"shape": "poly", "points_mm": up}},
                        level=L2)
create_room(xy=((XS + W) // 2, (YS + D) // 2), level=L2,
            name="Лестничная клетка", upper_offset_mm=H)

design_check([stairs, build()])
score()
'''

_SHELL = '''
envelope(intent="оболочка: башня со сужением, этажи её сечениями")

низ  = region([[0, 0], [24000, 0], [24000, 16000], [0, 16000]])
верх = region([[4000, 3000], [20000, 3000], [20000, 13000], [4000, 13000]])
башня = loft([(низ, 0), (верх, 36000)], name="оболочка")

for i, z in enumerate((6000, 18000, 30000)):
    create_floor_by_contour(contour=section(башня, z),
                            level=create_level(elev_mm=z, name=f"Этаж {i + 1}"))

юг = [f for f in faces(башня) if f["facing"] == "south"][0]
print("южная грань", round(юг["area_mm2"] / 1e6, 1), "м², нормаль", юг["normal"])
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
        name="жильё", title="программа, на которую судья отвечает ПРИГОДЕН",
        source=_JUDGED_DWELLING, ops=25, elements=25,
        covers="два уровня, четыре помещения, вердикт 13 правил из 20",
        contrast="дом — ПАЧКА программ, а не одна: лестница владеет своими "
                 "транзакциями (KIR-L002) и живёт отдельной программой, "
                 "поэтому вердикт берётся у `design_check([лестница, тело])`. "
                 "Одной программой судья отказывает КОДОМ KIR-V003, а не "
                 "молчанием",
        teaches=("вердикт", "место", "отказы")),
    Recipe(
        name="силуэт", title="питон считает форму, расхождение названо числом",
        source=_SILHOUETTE, ops=108, elements=108, covers="12 этажей из 59",
        contrast="приближение НАЗВАНО в мм: неназванное приближение — "
                 "молчаливо неверный ответ",
        teaches=("этаж", "границы")),
    Recipe(
        name="оболочка", title="форма сначала, БИМ-смысл из её сечений",
        source=_SHELL, ops=7, elements=7, covers="башня со сужением, 3 этажа",
        contrast="этажи НЕ выписаны координатами: они СЕЧЕНИЯ оболочки на "
                 "отметке. Сдвинул верхний профиль — переехали все три, и "
                 "переехали согласованно. Перечислением это три независимые "
                 "правки, которые расходятся молча",
        teaches=("геометрия", "форма")),
)}

#: Order in the table of contents: method first, then the worked case,
#: then form.
ORDER: tuple[str, ...] = (
    "санузел", "санузел-джуниор", "витраж", "витраж-джуниор",
    "этаж", "этаж-джуниор", "здание", "жильё", "силуэт", "оболочка")


__all__ = ["ORDER", "RECIPES", "Recipe"]
