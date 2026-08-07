"""KIR RELATE — АДРЕСАЦИЯ ОТ ОСЕЙ (подъязык АДРЕСА, а не новые операции).

Спека: ``RELATE_SPEC_2026-08-03.md``. Реестр операций НЕ РАСТЁТ: адрес — это
форма ЗНАЧЕНИЯ точечного параметра, ровно как ``region`` у CONTOUR.

ЧТО ЭТО. Точка в плане может быть записана двумя способами:

    [12000, 6000]                       — литерал, как было всегда
    {"at_grid": ["Б", "3"]}             — пересечение двух осей МОДЕЛИ
    {"at_grid": [{"grid": "Б", "offset_mm": 200, "toward": "В"}, "3"]}

Разрешается адрес на стадии GROUND (чистая функция от снапшота), в эмиттер
уходит литеральная точка. Тригонометрия — на компиляции; эмитируемая C# видит
только числа. Это ЗАКРЕПЛЁННОЕ РЕШЕНИЕ №1 подъязыка CONTOUR, из которого
RELATE вырос, и оно здесь не пересматривается.

────────────────────────────────────────────────────────────────────────────
ГРАММАТИКА — ЗАКРЫТАЯ. Три узла, композиции нет.
────────────────────────────────────────────────────────────────────────────

    <адрес-xy>   ::= { "at_grid": [ <линия>, <линия> ] }
    <адрес-xyz>  ::= { "at_grid": [ <линия>, <линия> ], "z_mm": <число> }

    <линия>      ::= <имя>                                    // краткая форма
                   | { "grid": <имя> }                        // то же, полно
                   | { "grid": <имя>, "offset_mm": <число>, "toward": <имя> }

Закрытость — МАШИННАЯ, а не на словах: разборщик не догадывается по полям, он
ищет НАБОР КЛЮЧЕЙ в реестрах :data:`ADDRESS_FORMS` / :data:`LINE_FORMS`.
Незнакомый набор — отказ, который ПЕЧАТАЕТ реестр. Новая форма выражения =
новая строка в реестре + её семантика в резолвере; догадаться разборщик не
может по построению.

Композиции нет и не будет: ни «середина между А и Б», ни «А плюс Б», ни
«параллельно А». Вычислителя здесь нет — резолвер это пересечение двух прямых
из снапшота, и ничего больше. Первый же бинарный оператор ломает SPEC 12.3
(тот же замок, что у ``macros._REF_RE``).

────────────────────────────────────────────────────────────────────────────
ТРИ ЛАТЕНТНЫХ ДЕФЕКТА ШИППЕД-МЕХАНИЗМА, КОТОРЫЕ ЭТОТ МОДУЛЬ ЧИНИТ
────────────────────────────────────────────────────────────────────────────

Адресация от осей существует с 17.07 в ``contour.resolve_anchor``. Обобщать её
надо было ПОЧИНИВ, иначе дефект фундамента отравил бы двадцать два новых
параметра вместо одного.

**Д1. МИРОВАЯ РАМКА ОТСТУПА.** Шиппед-форма ``{"at_grid": [...], "offset_mm":
[dx, dy]}`` смещает точку в МИРОВЫХ координатах. Замер по корпусу 03.08:
у ``sklnk_eom`` ВСЕ 57 осей идут под 156.1° и 66.1° — ни одна не совпадает с
мировой осью. Сказать там «200 мм от оси 25» мировым ``[dx,dy]`` нельзя вовсе:
автор обязан сам посчитать ``[200·cos66.1°, 200·sin66.1°]`` — ровно ту
арифметику, которую подъязык обязан снять. Мировая рамка — не упрощение, а
неснятый барьер.

    ЧИНИТСЯ: узлом ``{"grid": ..., "offset_mm": <число>, "toward": ...}``.
    Отступ — ЧИСЛО по перпендикуляру к САМОЙ ОСИ, направление читается ИЗ
    МОДЕЛИ (знак перпендикуляра, указывающего на прямую ``toward``).
    Мировая пара ``[dx,dy]`` остаётся ТОЛЬКО у ``region`` (см.
    :data:`LEGACY_ADDRESS_FORMS`) и в новых слотах ОТКАЗЫВАЕТ.

**Д2. ТИХИЙ ВЫБОР ПРИ СОВПАДЕНИИ ИМЁН.** ``contour.py:86`` строил
``{name: g for g in pool}`` — словарное включение оставляет ПОСЛЕДНЮЮ строку
при совпадении ключа, молча. Тот же род, что ``.FirstOrDefault()``, ради
запрета которого написано НАЗВАННОЕ УМОЛЧАНИЕ. Индекс Revit API не
документирует НИКАКОЙ гарантии уникальности ``Grid.Name`` (у типа ``Grid``
семь членов, ``Name`` наследуется от ``Element``).

    ЧИНИТСЯ: :data:`GRID_AMBIGUOUS` (KIR-G109) с ``{id, name}`` каждой оси.

**Д3. ОБУСЛОВЛЕННОСТЬ НЕ ПРОВЕРЯЛАСЬ.** ``_line_intersection`` отказывал
только при ``|den| < 1e-9`` — для двух 30-метровых осей это угол порядка
1e-15 рад. Пара «почти параллельных» осей давала точку, и точка эта — шум.

    ЧИНИТСЯ: :data:`MIN_GRID_ANGLE_DEG` (см. вывод у самой константы) и
    :data:`GRID_NO_INTERSECTION` (KIR-G110), который НАЗЫВАЕТ угол.

────────────────────────────────────────────────────────────────────────────
ЧЕГО ЭТОТ МОДУЛЬ НЕ ДОКАЗЫВАЕТ — ПРЯМЫМ ТЕКСТОМ
────────────────────────────────────────────────────────────────────────────

Адрес разрешается ПО СНАПШОТУ, снятому ДО транзакции. Между снимком и записью
ось может уехать (соавтор, Reload Latest, ре-линк) — и элемент встанет туда,
где оси уже нет, а весь пост пройдёт зелёным: свидетель опа сверяет элемент с
ЛИТЕРАЛОМ, который вывели мы же.

Это НЕ новая дыра: ровно с этим остатком ``at_grid`` шиппится в CONTOUR с
17.07. RELATE его НАСЛЕДУЕТ и не расширяет класс необещанного — ни одного
нового обязательства о ПОЛОЖЕНИИ здесь не появляется, меняется происхождение
числа, а не проверяемость (свидетели ``location_mm``/``endpoint_mm`` каждого
опа проверяют точку как проверяли).

Закрывается остаток свидетелем ``grid_anchor`` (спека §6) — отдельная волна:
он требует ``tolerances["grid_anchor_mm"]`` у двенадцати опов, строки в их
``post``, обязательств в ``translation_cert`` и адресных программ в
сертифицирующем корпусе (иначе ``test_tolerance_provenance`` L4/L5 краснеют
законно). Здесь он НЕ сделан, и это сказано, а не умолчано.
"""
from __future__ import annotations

import difflib
import math
from typing import Any, Optional

from kukai.ir.diag import Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS
from kukai.ir.emit_utils import is_finite_number
from kukai.ir.numeric_contracts import MODEL_COORD_LIMIT_MM

# ── коды отказа ──────────────────────────────────────────────────────────────
#
# Замер namespace 04.08 (греп ``KIR-[A-Z]\d+`` по ``kukai/``): блок G1xx занят
# G101..G104, G106, G107; G105 был у ``contour.GRID_ANCHOR_UNRESOLVED`` и
# РАСЩЕПЛЁН здесь на три кода — не из любви к номерам, а потому что «имя не
# найдено», «геометрии нет» и «пересечения нет» ведут к ТРЁМ РАЗНЫМ РЕМОНТАМ,
# а один код на три ремонта посылает автора наугад. Кодов ровно столько,
# сколько разных ремонтов.
GRID_NOT_FOUND = "KIR-G108"          # имени оси нет в пуле grids
GRID_AMBIGUOUS = "KIR-G109"          # несколько осей носят это имя (Д2)
GRID_NO_INTERSECTION = "KIR-G110"    # пара параллельна / угол < порога (Д3)
GRID_NO_GEOMETRY = "KIR-G111"        # ось есть, прямой геометрии нет (дуга)
GRID_TOWARD_INVALID = "KIR-G112"     # toward не годится в «сторону»

#: Пул осей пуст / снапшота нет — переиспользуются коды ground как есть
#: (ремонт другой: не «поправь имя», а «сначала построй оси»). Импортируются
#: лениво, чтобы ``relate`` не тянул ``ground`` (тот тянет ``spec``).
GROUND_EMPTY_POOL = "KIR-G104"

#: ПОРОГ ОБУСЛОВЛЕННОСТИ — ВЫВОД, а не вкус (Д3).
#:
#: Округление литерала в эмиссии ``round(x, 2)`` даёт 0.005 мм. Усиление
#: погрешности при пересечении под углом α равно ``1/sin(α)``:
#:
#:     α = 1°    -> 0.005 × 57.3  = 0.29 мм
#:     α = 0.1°  -> 0.005 × 573   = 2.87 мм
#:     α = 0.01° -> 0.005 × 5730  = 28.6 мм
#:
#: Порог выбран так, чтобы распространённая погрешность оставалась строго
#: МЕНЬШЕ МИЛЛИМЕТРА. Замер корпуса 03.08 (3346 непараллельных пар в 9
#: наборах осей) подтверждает, что он БЕСПЛАТЕН: минимальный наблюдённый
#: угол 7.5°, пар меньше 5° — ноль. Пересмотреть при первом же здании с
#: парой осей в диапазоне 1..7.5°.
#:
#: ОДНО ЧИСЛО, ДВА СМЫСЛА, и это не совпадение: «пара пересекается» и «пара
#: параллельна» обязаны быть ДОПОЛНЕНИЕМ друг друга, иначе нашлась бы пара,
#: которая ни туда ни сюда. Угол >= порога -> пересечение считаем; угол <
#: порога -> пара считается параллельной (и годится в ``toward``).
MIN_GRID_ANGLE_DEG = 1.0

#: Потолок отступа — та же граница, что у ``move_elements.delta_mm`` (100 м на
#: компоненту). Замеренный максимум смещения колонны от оси в корпусе —
#: 2125 мм, то есть потолок с запасом 47×.
MAX_OFFSET_MM = 100_000.0

#: Имя оси: 1..64 символа после trim. Верх — та же длина, что у ``macros``
#: для имени трека; ось с именем в 65 символов не встречалась ни в одном из
#: 9 наборов корпуса (максимум наблюдён 4 символа).
MAX_GRID_NAME_LEN = 64

#: Ниже этой длины у оси НЕТ НАПРАВЛЕНИЯ, и перпендикуляр не определён.
#: Совпадает с ``contour._EDGE_TOL`` — тем же порогом «нулевого ребра».
_MIN_GRID_LENGTH_MM = 1.0

#: Ниже этого расстояния две параллельные прямые СОВПАДАЮТ, и «в сторону»
#: не определено. Порядок величины — округление литерала (0.005 мм) × запас.
_MIN_TOWARD_DISTANCE_MM = 1.0


# ── ЗАКРЫТЫЕ РЕЕСТРЫ ФОРМ ────────────────────────────────────────────────────
#
# Разборщик НЕ ДОГАДЫВАЕТСЯ: он берёт ``frozenset(node)`` и ищет его здесь.
# Отсюда же берётся ТЕКСТ ОТКАЗА — то есть автор, промахнувшийся мимо
# грамматики, видит грамматику целиком, а не «неизвестное поле».

#: Формы узла <адрес>. Ключ — набор ключей объекта, значение — (dims, подпись).
ADDRESS_FORMS: dict[frozenset, tuple[int, str]] = {
    frozenset({"at_grid"}): (2, '{"at_grid": [<линия>, <линия>]}'),
    frozenset({"at_grid", "z_mm"}):
        (3, '{"at_grid": [<линия>, <линия>], "z_mm": <число>}'),
}

#: ЛЕГАСИ-ДВЕРЬ, открытая ИМЕНОВАННО и ровно одному потребителю — ``region``
#: подъязыка CONTOUR, где эта форма шиппится с 17.07 и стоит в голденах.
#: Это и есть Д1 в чистом виде; в новых слотах она ЗАКРЫТА, и отказ по ней
#: называет замену. Дверь закроется, когда ``region`` переедет на узловой
#: отступ — отдельная работа, которая двигает голдены.
LEGACY_ADDRESS_FORMS: dict[frozenset, tuple[int, str]] = {
    frozenset({"at_grid", "offset_mm"}):
        (2, '{"at_grid": [<линия>, <линия>], "offset_mm": [dx, dy]}  '
            '(мировая рамка, только region)'),
}

#: Формы узла <линия>. Краткая форма (голая строка) обрабатывается отдельно:
#: у неё нет ключей.
LINE_FORMS: dict[frozenset, str] = {
    frozenset({"grid"}): '{"grid": <имя>}',
    frozenset({"grid", "offset_mm", "toward"}):
        '{"grid": <имя>, "offset_mm": <число>, "toward": <имя>}',
}

#: ЕДИНСТВЕННОЕ ИСКЛЮЧЕНИЕ из правила «всякий pt_xy/pt_xyz адресуем».
#:
#: ``move_elements.delta_mm`` — СМЕЩЕНИЕ, а не положение: «сдвинь на
#: пересечение А и 3» не значит ничего. Он носит род ``pt_xyz`` только потому,
#: что переиспользует его форму в схеме (см. комментарий в
#: ``authoring_validation``), и это ровно тот случай, когда род говорит о
#: ФОРМЕ, а не о СМЫСЛЕ.
#:
#: Список ПРОВЕРЯЕМЫЙ: :func:`_lint` падает, если пара исчезла из реестра или
#: сменила род. Исключение, которое перестало на что-то указывать, — это
#: правило, которого никто не применяет.
ADDRESS_EXCLUDED: frozenset = frozenset({("move_elements", "delta_mm")})


def _lint() -> None:
    """Инварианты реестров форм — на импорте, как ``spec._lint_registry``."""
    for keys, (dims, _sig) in {**ADDRESS_FORMS, **LEGACY_ADDRESS_FORMS}.items():
        if "at_grid" not in keys or dims not in (2, 3):
            raise AssertionError(f"ADDRESS_FORMS: битая форма {sorted(keys)}")
    for keys in LINE_FORMS:
        if "grid" not in keys:
            raise AssertionError(f"LINE_FORMS: битая форма {sorted(keys)}")
    from kukai.ir import spec
    for op_name, param in ADDRESS_EXCLUDED:
        op_spec = spec.OPS.get(op_name)
        if op_spec is None:
            raise AssertionError(
                f"ADDRESS_EXCLUDED называет {op_name!r}, которого нет в "
                "реестре — исключение из правила про несуществующий оп")
        if not any(p.name == param and p.kind in ("pt_xy", "pt_xyz")
                   for p in op_spec.params):
            raise AssertionError(
                f"ADDRESS_EXCLUDED называет {op_name}.{param}, у которого "
                "нет точечного рода — исключение бьёт мимо")


def addressable_params(op_name: str) -> dict[str, int]:
    """``{имя параметра: размерность}`` — где у этого опа разрешён адрес.

    СУДЬЯ ОДИН: список НЕ ведётся здесь, он ВЫВОДИТСЯ из рода параметра в
    ``spec.OPS`` минус :data:`ADDRESS_EXCLUDED`. Свой список стал бы четвёртым
    и разошёлся бы на первом же новом опе — ровно это и произошло между
    спекой (13 ``pt_xyz`` на 03.08) и деревом (15 на 04.08: приехал
    ``create_opening``).
    """
    from kukai.ir import spec
    op_spec = spec.OPS.get(op_name)
    if op_spec is None:
        return {}
    return {p.name: (3 if p.kind == "pt_xyz" else 2)
            for p in op_spec.params
            if p.kind in ("pt_xy", "pt_xyz")
            and (op_name, p.name) not in ADDRESS_EXCLUDED}


def is_address(value: Any) -> bool:
    """Дешёвый классификатор: «это вообще адрес?».

    Намеренно ГРУБЫЙ — достаточно ключа ``at_grid``, чтобы отличить попытку
    адреса от литерала. Всё остальное говорит :func:`validate_address`, и
    говорит ТИПИЗИРОВАННЫМ ОТКАЗОМ, а не молчаливым «не адрес».
    """
    return isinstance(value, dict) and "at_grid" in value


def program_uses_address(op: Any) -> bool:
    """Есть ли в тексте опа адрес — по адресуемым параметрам, не по ``repr``.

    ``ground._needs_pool`` спрашивал ``"at_grid" in repr(op.get("contour"))``,
    то есть по СТРОКОВОМУ представлению одного поля одного опа. Здесь читаются
    реальные значения реальных параметров: подстрока в имени типа
    («Ось at_grid 2») больше не может ни включить, ни выключить чтение пула.
    """
    if not isinstance(op, dict):
        return False
    for param in addressable_params(str(op.get("op", ""))):
        if is_address(op.get(param)):
            return True
    return False


# ── плоская геометрия (вся тригонометрия — здесь, на компиляции) ─────────────

def _is_pt(v) -> bool:
    return (isinstance(v, list) and len(v) == 2
            and all(is_finite_number(c) for c in v))


def _unit(dx: float, dy: float) -> tuple:
    length = math.hypot(dx, dy)
    return (dx / length, dy / length)


def line_angle_deg(d1: tuple, d2: tuple) -> float:
    """Угол между ПРЯМЫМИ (не лучами) в градусах, 0..90.

    Через ``atan2(|cross|, |dot|)``, а не через ``acos(dot)``: у ``acos``
    производная на концах бесконечна, и именно на концах — при почти
    параллельных осях — этот угол и решает судьбу пары (Д3).
    """
    u1, u2 = _unit(*d1), _unit(*d2)
    cross = abs(u1[0] * u2[1] - u1[1] * u2[0])
    dot = abs(u1[0] * u2[0] + u1[1] * u2[1])
    return math.degrees(math.atan2(cross, dot))


def signed_offset_mm(p0, p1, q) -> float:
    """Знаковое расстояние от БЕСКОНЕЧНОЙ прямой (p0,p1) до точки q.

    Именно от бесконечной: оси — прямые, а не отрезки (``contour.py`` знает
    эту ловушку с 17.07), и колонна за краем НАРИСОВАННОЙ оси обязана мерить
    расстояние до прямой, а не до её конца.
    """
    ux, uy = _unit(p1[0] - p0[0], p1[1] - p0[1])
    return -uy * (q[0] - p0[0]) + ux * (q[1] - p0[1])


def _offset_line(p0, p1, distance: float) -> tuple:
    """Прямая, параллельная (p0,p1), на знаковом расстоянии ``distance``."""
    ux, uy = _unit(p1[0] - p0[0], p1[1] - p0[1])
    nx, ny = -uy, ux
    return ([p0[0] + nx * distance, p0[1] + ny * distance],
            [p1[0] + nx * distance, p1[1] + ny * distance])


def _canon_mm(value) -> float | int:
    """Канон координаты: округление до нанометра и ЦЕЛОЕ, если оно целое.

    Не косметика, а условие ворот В3 спеки: одна и та же программа, записанная
    адресами и литералами, обязана давать ПОБАЙТОВО одинаковую create-часть
    C#. Эмиттер печатает число как есть, поэтому `4000.0` дало бы `P(4000.0,
    ...)` там, где литерал `4000` даёт `P(4000, ...)` — и различие в байтах
    было бы не про геометрию, а про тип питоновского числа.

    Округление до 6 знаков (нанометр) — на четыре порядка ниже допуска
    свидетеля (5 мм) и на три ниже округления эмиссии (0.005 мм), то есть
    поглощается ими целиком; зато делает вывод устойчивым к последнему биту
    двоичной плавающей на разных машинах.
    """
    number = round(float(value), 6)
    integral = int(number)
    return integral if number == integral else number


def intersect(p0, p1, q0, q1) -> Optional[list]:
    """Пересечение двух БЕСКОНЕЧНЫХ прямых, или ``None`` при вырождении.

    Порог обусловленности проверяет ВЫЗЫВАЮЩИЙ (ему есть что сказать в
    отказе — имена осей и угол); здесь остаётся только защита от деления
    на ноль.
    """
    d1 = (p1[0] - p0[0], p1[1] - p0[1])
    d2 = (q1[0] - q0[0], q1[1] - q0[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-12:
        return None
    t = ((q0[0] - p0[0]) * d2[1] - (q0[1] - p0[1]) * d2[0]) / den
    return [p0[0] + t * d1[0], p0[1] + t * d1[1]]


# ── стадия VALIDATE: чистые функции от ТЕКСТА (снапшот не нужен) ─────────────

def _bad(diags, oid, field, message, *, code=TYPE_BAD_TYPE, got=None,
         expected=None, candidates=()) -> bool:
    diags.append(Diagnostic(
        code=code, op_id=oid, field_name=field, got=got, expected=expected,
        candidates=list(candidates), message_ru=message))
    return False


def _grid_name_ok(value: Any) -> bool:
    return (isinstance(value, str) and value.strip()
            and len(value.strip()) <= MAX_GRID_NAME_LEN)


def _validate_line(node: Any, oid, field: str, diags: list) -> bool:
    """Один узел <линия>: форма, границы, парность. Модель не нужна."""
    if isinstance(node, str):
        if not _grid_name_ok(node):
            return _bad(diags, oid, field,
                        f"{field}: имя оси — непустая строка 1..{MAX_GRID_NAME_LEN} "
                        f"символа после trim", got=node)
        return True
    if not isinstance(node, dict):
        return _bad(diags, oid, field,
                    f"{field}: линия — имя оси строкой либо один из объектов: "
                    + " | ".join(sorted(LINE_FORMS.values())), got=node)
    keys = frozenset(node)
    if keys not in LINE_FORMS:
        # Парность offset_mm/toward — САМАЯ вероятная промашка, и общий
        # «неизвестный набор полей» послал бы автора перечитывать грамматику
        # вместо того, чтобы дописать одно слово. Поэтому она называется
        # отдельно, ДО реестра форм.
        if keys == frozenset({"grid", "offset_mm"}):
            return _bad(diags, oid, field,
                        f"{field}: offset_mm без toward — сторона отступа не "
                        f"названа. Знакового соглашения в языке нет: "
                        f"направление p0->p1 у оси задаётся тем, как её "
                        f"нарисовали, автору невидимо и переворачивается "
                        f"правкой, не меняющей ни имени, ни положения. "
                        f"Допишите toward: имя ПАРАЛЛЕЛЬНОЙ соседней оси, в "
                        f"сторону которой идёт отступ", got=sorted(keys))
        if keys == frozenset({"grid", "toward"}):
            return _bad(diags, oid, field,
                        f"{field}: toward без offset_mm — отступать не на "
                        f"сколько. Нулевой отступ пишется как "
                        f'{{"grid": "{node.get("grid")}"}}', got=sorted(keys))
        return _bad(diags, oid, field,
                    f"{field}: неизвестная форма линии {sorted(keys)}. "
                    f"Грамматика ЗАКРЫТА, форм ровно три: <имя> | "
                    + " | ".join(sorted(LINE_FORMS.values())),
                    got=sorted(keys), candidates=sorted(LINE_FORMS.values()))
    if not _grid_name_ok(node.get("grid")):
        return _bad(diags, oid, field,
                    f"{field}.grid: имя оси — непустая строка "
                    f"1..{MAX_GRID_NAME_LEN} символа после trim",
                    got=node.get("grid"))
    if "offset_mm" not in keys:
        return True
    offset = node.get("offset_mm")
    if not is_finite_number(offset):
        return _bad(diags, oid, field,
                    f"{field}.offset_mm: отступ — ОДНО конечное число (мм) по "
                    f"перпендикуляру к оси «{node['grid'].strip()}». Пара "
                    f"[dx,dy] здесь не принимается: это мировая рамка, а у "
                    f"повёрнутого здания мировые оси не совпадают с осями "
                    f"сетки", got=offset)
    if abs(float(offset)) > MAX_OFFSET_MM:
        return _bad(diags, oid, field,
                    f"{field}.offset_mm: |отступ| не более {MAX_OFFSET_MM:.0f} мм",
                    code=TYPE_BOUNDS, got=offset,
                    expected=f"|x| <= {MAX_OFFSET_MM:.0f}")
    if float(offset) == 0.0:
        return _bad(diags, oid, field,
                    f"{field}.offset_mm: нулевой отступ пишется как "
                    f'{{"grid": "{node["grid"].strip()}"}} — двух записей '
                    f"одного смысла в языке нет", code=TYPE_BOUNDS, got=offset)
    if not _grid_name_ok(node.get("toward")):
        return _bad(diags, oid, field,
                    f"{field}.toward: имя соседней оси — непустая строка "
                    f"1..{MAX_GRID_NAME_LEN} символа после trim",
                    got=node.get("toward"))
    if node["grid"].strip() == node["toward"].strip():
        return _bad(diags, oid, field,
                    f"{field}.toward: «{node['toward'].strip()}» — это сама "
                    f"ось отступа. Сторона относительно самой себя не "
                    f"определена; назовите ПАРАЛЛЕЛЬНУЮ соседку",
                    got=node.get("toward"))
    return True


def validate_address(value: Any, oid, field: str, diags: list, *,
                     dims: int, allow_world_offset: bool = False) -> bool:
    """Статические законы адреса. Возвращает True, если разбирается.

    ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ: форма, границы, парность — всё, что есть чистая
    функция ОТ ТЕКСТА. Существование оси, однозначность имени, угол и сама
    точка доказываются от СНАПШОТА и живут в :func:`resolve_address`
    (стадия ground). Черта проходит ровно между «есть в тексте» и «есть в
    модели» — спека §4.1.
    """
    if not isinstance(value, dict):
        return _bad(diags, oid, field, f"{field}: адрес — объект", got=value)
    forms = dict(ADDRESS_FORMS)
    if allow_world_offset:
        forms.update(LEGACY_ADDRESS_FORMS)
    # Реестр сужается ДО размерности параметра, а не сверяется после. Разница
    # видна в отказе: «неизвестная форма» несёт подсказку про z_mm и про то,
    # ПОЧЕМУ он обязателен, а «форма даёт 2D, параметр 3D» — только диагноз.
    forms = {k: v for k, v in forms.items() if v[0] == dims}
    keys = frozenset(value)
    form = forms.get(keys)
    if form is None:
        hint = ""
        if not allow_world_offset and "offset_mm" in keys:
            hint = (' Мировой отступ [dx,dy] у адреса ЗАКРЫТ: у повёрнутого '
                    'здания мировые оси не совпадают с осями сетки. Отступ '
                    'называется У ЛИНИИ: '
                    '{"at_grid": [{"grid": "Б", "offset_mm": 200, '
                    '"toward": "В"}, "3"]}')
        if "z_mm" in keys and dims == 2:
            hint = (" Этот параметр плоский (pt_xy) — отметку держит уровень, "
                    "z_mm здесь лишний.")
        elif "z_mm" not in keys and dims == 3:
            hint = (" Этот параметр объёмный (pt_xyz), а у сетки осей нет Z: "
                    "отметку обязан назвать сам адрес — допишите z_mm. "
                    "Молча подставленный ноль поставил бы элемент на отметку "
                    "уровня вместо проектной, и свидетель принял бы это "
                    "(он сверяет с тем же нулём).")
        expected = next((sig for kk, (dd, sig) in forms.items()
                         if dd == dims), None)
        return _bad(diags, oid, field,
                    f"{field}: неизвестная форма адреса {sorted(keys)}. "
                    f"Грамматика ЗАКРЫТА; для этого параметра принимается "
                    f"{expected}.{hint}",
                    got=sorted(keys), expected=expected,
                    candidates=[sig for _d, sig in forms.values()])
    lines = value.get("at_grid")
    if not isinstance(lines, list) or len(lines) != 2:
        return _bad(diags, oid, field,
                    f"{field}.at_grid: РОВНО две линии — точка это их "
                    f"пересечение", got=lines)
    ok = True
    for index, node in enumerate(lines):
        if not _validate_line(node, oid, f"{field}.at_grid[{index}]", diags):
            ok = False
    if dims == 3:
        z = value.get("z_mm")
        if not is_finite_number(z):
            ok = _bad(diags, oid, f"{field}.z_mm",
                      f"{field}.z_mm: отметка — конечное число (мм)", got=z)
        else:
            if abs(float(z)) > MODEL_COORD_LIMIT_MM:
                ok = _bad(diags, oid, f"{field}.z_mm",
                          f"{field}.z_mm: |отметка| не более "
                          f"{MODEL_COORD_LIMIT_MM:.0f} мм",
                          code=TYPE_BOUNDS, got=z)
    if allow_world_offset and "offset_mm" in keys and not _is_pt(value["offset_mm"]):
        ok = _bad(diags, oid, f"{field}.offset_mm",
                  f"{field}.offset_mm: мировой отступ — [dx, dy]",
                  got=value.get("offset_mm"))
    return ok


# ── стадия GROUND: чистые функции от СНАПШОТА ───────────────────────────────

def _rows_named(name: str, pool: list) -> list:
    """ВСЕ строки пула с этим именем. Список, а не строка — в этом и Д2."""
    want = name.strip()
    return [row for row in (pool or [])
            if isinstance(row, dict) and str(row.get("name", "")).strip() == want]


def _nearest_names(name: str, pool: list) -> list:
    names = [str(row.get("name", "")) for row in (pool or [])
             if isinstance(row, dict)]
    return difflib.get_close_matches(name.strip(), names, n=5, cutoff=0.0)


def _parallel_neighbours(row: dict, pool: list) -> list:
    """Имена осей, ПАРАЛЛЕЛЬНЫХ данной и не совпадающих с ней.

    Ровно тот список, который годится в ``toward``. Пустой список — законный
    ответ, и он означает «эту ось нельзя отступить, у неё нет соседки»
    (замер: 35% осей ``k2_ar_rd`` — одиночки; при этом НИ ОДНА колонна
    корпуса не стоит со смещением от оси-одиночки).
    """
    base = _line_of(row)
    if base is None:
        return []
    (bp0, bp1) = base
    out = []
    for other in (pool or []):
        if not isinstance(other, dict) or other is row:
            continue
        line = _line_of(other)
        if line is None:
            continue
        if line_angle_deg((bp1[0] - bp0[0], bp1[1] - bp0[1]),
                          (line[1][0] - line[0][0],
                           line[1][1] - line[0][1])) >= MIN_GRID_ANGLE_DEG:
            continue
        if abs(signed_offset_mm(bp0, bp1, line[0])) < _MIN_TOWARD_DISTANCE_MM:
            continue
        out.append(str(other.get("name", "")))
    return sorted(set(out))


def _line_of(row: dict) -> Optional[tuple]:
    """(p0, p1) оси, если у неё есть ПРЯМАЯ геометрия ненулевой длины."""
    p0, p1 = row.get("p0_mm"), row.get("p1_mm")
    if not _is_pt(p0) or not _is_pt(p1):
        return None
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < _MIN_GRID_LENGTH_MM:
        return None
    return ([float(p0[0]), float(p0[1])], [float(p1[0]), float(p1[1])])


def _find_grid(name: str, pool: list, oid, field: str, diags: list, *,
               truncated: bool) -> Optional[dict]:
    """Одна ось по имени: G108 нет / G109 неоднозначно / G111 без геометрии."""
    want = name.strip()
    rows = _rows_named(want, pool)
    if not rows:
        # Обрезанный пул — по ОБРАЗЦУ ``ground._resolve_one``, а не новым
        # кодом: единственный ВИДИМЫЙ ничего не доказывает о невидимом
        # остатке. Нового кода нет, есть приписка к сообщению.
        note = ("; пул осей обрезан коллектором на 1000 — ось может "
                "существовать за срезом" if truncated else "")
        # ВТОРАЯ ПОЛОВИНА РЕМОНТА, и она стоит здесь, а не в прозе описания
        # инструмента: адресуются только оси ИЗ СНИМКА, снятого ДО программы,
        # поэтому ось, созданная этой же программой, «не найдена» совершенно
        # законно. Сказать это в курсе стоило бы токенов в КАЖДОМ запросе;
        # сказать здесь — только тому, кто на это наступил.
        _bad(diags, oid, field,
             f"{field}: оси «{want}» нет в модели{note}. Список осей: "
             f'{{"op": "query_list", "kind": "grid"}}. Если «{want}» создаётся '
             f"ЭТОЙ ЖЕ программой — адресовать её нельзя: адрес читает снимок, "
             f"снятый ДО программы. Это два хода: создать оси, перечитать "
             f"модель, строить",
             code=GRID_NOT_FOUND, got=want,
             candidates=_nearest_names(want, pool))
        return None
    if len(rows) > 1:
        # Д2. Имя оси И ЕСТЬ её идентичность в проектной культуре, поэтому
        # обхода «уточни через element_id» язык НЕ предлагает: он его не
        # принимает (спека §5.4). Обход честно назван и он вне грамматики.
        _bad(diags, oid, field,
             f"{field}: имя «{want}» носят {len(rows)} осей — выбрать за вас "
             f"нельзя. Осей по element_id язык не адресует (имя оси и есть её "
             f"идентичность): переименуйте одну из них либо задайте эту точку "
             f"литералом [x, y]",
             code=GRID_AMBIGUOUS, got=want,
             candidates=[{"id": r.get("id"), "name": r.get("name")}
                         for r in rows])
        return None
    row = rows[0]
    if _line_of(row) is None:
        is_curved = row.get("is_curved")
        why = (" (ось дуговая)" if is_curved is True else
               " (коллектор снимает только прямые: Grid.Curve as Line, "
               "дуговая ось приезжает без геометрии)")
        _bad(diags, oid, field,
             f"{field}: ось «{want}» есть в модели, но прямой геометрии у неё "
             f"нет{why}. Дуговая ось адресуется только литералом [x, y] — "
             f"другого пути нет",
             code=GRID_NO_GEOMETRY, got=want,
             candidates=[{"id": row.get("id"), "name": row.get("name"),
                          "is_curved": is_curved}])
        return None
    return row


def _resolve_line(node: Any, pool: list, oid, field: str, diags: list, *,
                  truncated: bool) -> Optional[dict]:
    """Узел <линия> -> {"line": (p0,p1), "grid": row, "offset_mm", "toward"}."""
    if isinstance(node, str):
        node = {"grid": node}
    name = str(node.get("grid", "")).strip()
    row = _find_grid(name, pool, oid, field, diags, truncated=truncated)
    if row is None:
        return None
    p0, p1 = _line_of(row)
    resolved = {"grid": {"id": row.get("id"), "name": str(row.get("name", ""))},
                "line": (p0, p1)}
    if "offset_mm" not in node:
        return resolved
    offset = float(node["offset_mm"])
    toward_name = str(node.get("toward", "")).strip()
    toward_row = _find_grid(toward_name, pool, oid, f"{field}.toward", diags,
                            truncated=truncated)
    if toward_row is None:
        return None
    t0, t1 = _line_of(toward_row)
    angle = line_angle_deg((p1[0] - p0[0], p1[1] - p0[1]),
                           (t1[0] - t0[0], t1[1] - t0[1]))
    neighbours = _parallel_neighbours(row, pool)
    # СЛЕДУЮЩИЙ ХОД, а не диагноз: список параллельных соседок — это ровно
    # те имена, которые здесь примут. Пустой список тоже ход, и он другой:
    # у оси-одиночки отступ не выражается ВООБЩЕ, и звать автора менять имя
    # значило бы послать его в тупик.
    move = (f"назовите одну из них: {neighbours}" if neighbours else
            "у этой оси нет ни одной параллельной соседки — отступ от неё "
            "не выражается, задайте эту точку литералом [x, y]")
    if angle >= MIN_GRID_ANGLE_DEG:
        _bad(diags, oid, field,
             f"{field}: ось «{toward_name}» не параллельна оси «{name}» "
             f"(угол {angle:.2f}°, порог параллельности {MIN_GRID_ANGLE_DEG}°) "
             f"— у ПЕРЕСЕКАЮЩЕЙ прямой стороны нет, «в сторону» не "
             f"определено. {move}",
             code=GRID_TOWARD_INVALID, got=toward_name, candidates=neighbours)
        return None
    # Сторона обязана быть однозначной НА ВСЁМ ПРОТЯЖЕНИИ нарисованной оси:
    # две прямые под 0.9° формально параллельны по нашему порогу, но всё же
    # пересекаются — если разные концы `toward` лежат по разные стороны, слово
    # «в сторону» не значит ничего, и молчать об этом нельзя.
    s0 = signed_offset_mm(p0, p1, t0)
    s1 = signed_offset_mm(p0, p1, t1)
    if abs(s0) < _MIN_TOWARD_DISTANCE_MM and abs(s1) < _MIN_TOWARD_DISTANCE_MM:
        _bad(diags, oid, field,
             f"{field}: оси «{toward_name}» и «{name}» лежат на одной прямой "
             f"(расстояние < {_MIN_TOWARD_DISTANCE_MM} мм) — стороны у них "
             f"общей нет. {move}",
             code=GRID_TOWARD_INVALID, got=toward_name, candidates=neighbours)
        return None
    if s0 * s1 < 0:
        _bad(diags, oid, field,
             f"{field}: концы оси «{toward_name}» лежат по РАЗНЫЕ стороны от "
             f"оси «{name}» — «в сторону» не определено. {move}",
             code=GRID_TOWARD_INVALID, got=toward_name, candidates=neighbours)
        return None
    side = 1.0 if (s0 + s1) >= 0 else -1.0
    resolved["line"] = _offset_line(p0, p1, side * offset)
    resolved["offset_mm"] = offset
    resolved["toward"] = {"id": toward_row.get("id"),
                          "name": str(toward_row.get("name", ""))}
    return resolved


def resolve_address(value: Any, grids_pool: list, oid, field: str, diags: list,
                    *, dims: int, truncated: bool = False,
                    allow_world_offset: bool = False,
                    receipt: Optional[list] = None) -> Optional[list]:
    """Адрес -> литеральная точка [x,y] (или [x,y,z]), либо ``None`` + отказы.

    Чистая функция от снапшота: ни моста, ни транзакции. Отказ, который можно
    выдать без Revit, обязан выдаваться без Revit.

    ``receipt`` — если передан список, в него кладётся запись КВИТАНЦИИ: что
    именно компилятор вывел из написанного автором (id и имя каждой оси,
    отступ, сторона, итоговая точка). Выбор, который некому предъявить,
    неотличим от ``.FirstOrDefault()`` в костюме.
    """
    if not validate_address(value, oid, field, diags, dims=dims,
                            allow_world_offset=allow_world_offset):
        return None
    if not grids_pool:
        _bad(diags, oid, field,
             f"{field}: в модели нет ни одной оси — адресовать не от чего. "
             f'Сначала постройте оси ({{"op": "create_grid", ...}} или макрос '
             f"grid_array), затем перечитайте модель",
             code=GROUND_EMPTY_POOL, got=None)
        return None
    lines = value["at_grid"]
    resolved = []
    for index, node in enumerate(lines):
        one = _resolve_line(node, grids_pool, oid, f"{field}.at_grid[{index}]",
                            diags, truncated=truncated)
        if one is None:
            return None
        resolved.append(one)
    (a0, a1), (b0, b1) = resolved[0]["line"], resolved[1]["line"]
    angle = line_angle_deg((a1[0] - a0[0], a1[1] - a0[1]),
                           (b1[0] - b0[0], b1[1] - b0[1]))
    name_a = resolved[0]["grid"]["name"]
    name_b = resolved[1]["grid"]["name"]
    if angle < MIN_GRID_ANGLE_DEG:
        # Д3. Порог — не вкус: при 0.1° усиление погрешности 573×, и точка,
        # которую мы бы вернули, была бы шумом, неотличимым от результата.
        _bad(diags, oid, field,
             f"{field}: оси «{name_a}» и «{name_b}» сходятся под {angle:.3f}° "
             f"(порог {MIN_GRID_ANGLE_DEG}°) — пересечение есть, но оно шум: "
             f"погрешность растёт как 1/sin(угла), здесь это ×"
             f"{1.0 / max(math.sin(math.radians(max(angle, 1e-6))), 1e-9):.0f}. "
             f"Возьмите другую пару осей либо задайте точку литералом [x, y]",
             code=GRID_NO_INTERSECTION,
             got=[name_a, name_b], expected=f">= {MIN_GRID_ANGLE_DEG}°")
        return None
    point = intersect(a0, a1, b0, b1)
    if point is None:                     # недостижимо при angle >= порога
        _bad(diags, oid, field,
             f"{field}: оси «{name_a}» и «{name_b}» не пересекаются",
             code=GRID_NO_INTERSECTION, got=[name_a, name_b])
        return None
    if allow_world_offset and _is_pt(value.get("offset_mm")):
        point = [point[0] + float(value["offset_mm"][0]),
                 point[1] + float(value["offset_mm"][1])]
    out = [_canon_mm(point[0]), _canon_mm(point[1])]
    if dims == 3:
        out.append(_canon_mm(value["z_mm"]))
    if receipt is not None:
        receipt.append({
            "op_id": oid, "param": field, "point_mm": list(out),
            "angle_deg": round(angle, 3),
            "lines": [{k: v for k, v in one.items() if k != "line"}
                      for one in resolved],
        })
    return out


def describe_receipt_ru(rows: list) -> list:
    """Квитанция адресов одной строкой на адрес — для ответа автору."""
    out = []
    for row in rows or []:
        parts = []
        for one in row.get("lines", ()):
            text = f"«{one['grid']['name']}» (id {one['grid']['id']})"
            if "offset_mm" in one:
                text += (f" + {one['offset_mm']:g} мм в сторону "
                         f"«{one['toward']['name']}»")
            parts.append(text)
        point = row.get("point_mm") or []
        coords = ", ".join(f"{c:g}" for c in point)
        out.append(f"{row.get('op_id')}.{row.get('param')}: "
                   f"{' × '.join(parts)} -> [{coords}]")
    return out


_lint()
