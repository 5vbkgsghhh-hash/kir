"""МЕТОД ЦЕЛИКОМ: единица -> сборка -> этаж -> группа -> здание.

Оператор описал сеньорский метод так: «смоделировал панель стеклопакета с
импостами, создал из этого сборку, сделал по всему этажу, потом создал группу и
раскопировал по всему зданию». Здесь этот метод выполнен до конца — и по дороге
один его шаг ОПРОВЕРГНУТ ЗАМЕРОМ, что и есть самое ценное в примере.

ЧЕМ ЭТОТ ПРИМЕР ОТЛИЧАЕТСЯ ОТ СОСЕДЕЙ. `tower_numpy.py` и `contour_shapely.py`
написаны 29.07, до слоя языка: они собирают программу через `sdk` в этом же
процессе, с numpy и shapely, и модель их отправить НЕ МОЖЕТ (в песочнице нет ни
того, ни другого). Здесь скрипт — ровно тот текст, который уходит в поле
`program_py`, и он прогоняется НАСТОЯЩЕЙ песочницей: отдельный процесс, пустой
корень, ноль сети, двойной прогон со сверкой дайджеста. То есть пример не
показывает форму мысли, а проходит прод-путь.

ЧТО ОПРОВЕРГЛОСЬ. Шаг «панель с импостами -> сборка -> группа» невыполним и
НЕ НУЖЕН, и оба факта замерены:

  * невыполним — член группы не может ссылаться на соседа
    (`authoring_validation`, вид параметра `member_ops`), а линия разрезки
    адресует свой носитель именно ссылкой. Программа откажет типизированно;
  * не нужен — 92.0% импостов K2 и 92.1% импостов фасада СОБ6.2 рождает ТИП
    носителя (два независимых свидетеля Revit, `curtain_extract.
    CurtainWallRecord.mullion_state`). Отдельного опа у импоста нет вовсе.

Группой в настоящих зданиях становится КОМНАТНАЯ сборка: медиана тиражируемого
определения — 11 членов в K2 и 50 в ВК Snowdon; «Пилястра 16 этаж» 48 раз,
«Поручень типовой этаж» 41 раз. Поэтому ниже витраж собирается ТИПОМ, а группой
делается санузловый блок.

ТРЕТИЙ ЗАМЕР, НАЙДЕННЫЙ ПРОГОНОМ ЭТОГО ЖЕ ФАЙЛА. Член группы не может стоять на
уровне, который создаёт ЭТА ЖЕ программа: по ручке — KIR-T001 «член группы не
может содержать ref-селекторы», по ИМЕНИ того же уровня — KIR-G101 «не найден»
(снимок про него ещё не знает). Значит новый этаж и группа на нём — ДВЕ
программы, и здесь группы стоят на уровнях, которые в модели уже есть. Правило
уехало в course("единица") с обоими кодами отказа.

    backend/venv/bin/python tools/design/examples/method_group_and_repeat.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from kukai.ir import compiler, sandbox, spec                     # noqa: E402
from kukai.ir import course                                      # noqa: E402
from kukai.ir.ground import ground                               # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT              # noqa: E402

#: Политика прогона. `dsl_module` — шим курса: ровно тот состав имён, который
#: получит модель после шва (`course.SEAM`). `replay_check` включён, потому что
#: подпись исходника без сверки — обещание, а не доказательство.
POLICY = sandbox.SandboxPolicy(dsl_module="kukai.ir.course.language",
                               replay_check=True)

BAYS = 4          # секций вдоль фасада
FLOORS = 2        # этажей в программе; ровно столько уровней есть
                  # в модели — группа стоит только на СУЩЕСТВУЮЩЕМ
PITCH = 7500      # шаг секции, мм

#: РОВНО ТО, что уходит в поле `program_py`. Импорт разрешён только math /
#: itertools / functools; макросов здесь нет и быть не может.
SCRIPT = f'''
LVL_NAME = "Этаж %d"
WT = {{"by": "name", "value": "Кирпич 250"}}
CURTAIN = {{"by": "name", "value": "ЖБ 200"}}    # витражный тип из query_types
GLASS = {{"by": "name", "value": "Кирпич 250"}}  # тип ПАНЕЛИ, не стены
BAYS, FLOORS, PITCH, HH = {BAYS}, {FLOORS}, {PITCH}, 3300
CORE_W, CORE_D = 3000, 5000

envelope(intent="секции с витражным фасадом и типовым санузловым блоком")

def facade_bay(level, x):
    """ВИТРАЖ. Носитель несёт тип, тип рождает импосты и панель по умолчанию.
    Пишутся только носитель, линии разрезки и ОТЛИЧИЯ ячеек."""
    w = create_wall(p0_mm=(x, 0), p1_mm=(x + PITCH, 0), level=level,
                    type=CURTAIN, height_mm=HH)
    for i in range(1, 3):
        create_curtain_grid_line(host=w, direction="u",
                                 position_mm=(x + PITCH * i / 3.0, 0, 0))
    create_curtain_grid_line(host=w, direction="v",
                             position_mm=(x, 0, HH / 2.0))
    # только нижний ряд — глухой; остальные ячейки даёт ТИП носителя
    for u in range(1, 4):
        set_curtain_panel(host=w, u=u, v=1, panel_type=GLASS)
    return w

for f in range(FLOORS):
    lvl = create_level(elev_mm=f * HH, name=LVL_NAME % (f + 1))
    by_name = {{"by": "name", "value": LVL_NAME % (f + 1)}}

    # ЕДИНИЦА, КОТОРАЯ ПЕРЕЖИВАЕТ СКРИПТ: санузловый блок одной группой.
    # Внутри группы ссылок на соседей нет — уровень адресуется ПО ИМЕНИ.
    with unit("Блок санузла эт.%d" % (f + 1),
              placements=[(PITCH * i, 0) for i in range(1, BAYS)]):
        create_wall(p0_mm=(0, CORE_D), p1_mm=(CORE_W, CORE_D), level=by_name,
                    type=WT, height_mm=HH)
        create_wall(p0_mm=(CORE_W, CORE_D), p1_mm=(CORE_W, 0), level=by_name,
                    type=WT, height_mm=HH)

    # ОБОЛОЧКА: у каждой секции своя координата — это ЦИКЛ, а не группа.
    for i in range(BAYS):
        facade_bay(lvl, PITCH * i)
        create_room(xy=(PITCH * i + PITCH // 2, CORE_D + 2000), level=lvl,
                    name="Квартира %d-%d" % (f + 1, i + 1))

per_floor = len(kir.current()) // FLOORS
print("этажей в программе", FLOORS, "| опов", len(kir.current()),
      "| на этаж", per_floor,
      "| влезает этажей", kir.MAX_BULK_OPS // per_floor)
score()
'''


def main() -> int:
    result = sandbox.execute_author_script(SCRIPT, policy=POLICY)
    if not result.ok:
        print(result.refusal.render())
        return 1

    program = {"ir_version": spec.IR_VERSION,
               **{k: v for k, v in (result.envelope or {}).items()
                  if k != "ir_version"},
               "ops": result.ops}
    planned = compiler.plan_program(program, bulk=True)
    ground(planned.to_ops(), GROUND_SNAPSHOT)
    versions = [v for v in spec.REVIT_VERSIONS
                if getattr(compiler.compile_program(
                    program, revit_version=v, snapshot=GROUND_SNAPSHOT,
                    bulk=True), "ok", False)]

    got = course.measure(result.ops)
    lines = len([ln for ln in SCRIPT.strip().splitlines() if ln.strip()])
    print(f"{lines} строк питона -> {got['операций написано']} операций -> "
          f"{got['элементов объявлено']} объявленных элементов "
          f"({got['элементов на операцию']} на операцию)")
    print(f"группы: {got['определений групп']} определений, "
          f"{got['постановок групп']} постановок, "
          f"{got['копий на определение']} копий на определение; "
          f"{got['элементов внутри групп, %']}% элементов внутри групп")
    for name, (value, why) in course.BASELINE.items():
        print(f"  базовая линия «{name}»: {value} — {why}")
    print("производные (импосты, панели) НЕ посчитаны: сколько их родит Revit, "
          "из программы не видно. Замер по K2: 92.0% импостов даёт ТИП")
    print(f"песочница: {result.duration_s * 1000:.0f} мс, пик RSS "
          f"{result.peak_rss_kb} КБ, изоляция "
          f"{result.isolation.get('namespaces')} / "
          f"{result.isolation.get('filesystem')} / "
          f"сеть {result.isolation.get('network_probe')}")
    print(f"подпись исходника: {result.author_digest[:16]}…  "
          f"подпись программы: {result.program_digest[:16]}…  "
          f"сверка повтором: {result.isolation.get('replay_checked')}")
    print(f"компиляция: {len(versions)}/6 версий {versions}")
    print("--- печать скрипта, как её увидит модель ---")
    print(result.stdout.rstrip())
    return 0 if len(versions) == 6 else 1


if __name__ == "__main__":
    sys.exit(main())
