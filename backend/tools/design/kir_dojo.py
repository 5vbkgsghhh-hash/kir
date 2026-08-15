"""A sparring ring for the model and the KIR compiler. No Revit in the room.

Every measurement we have of the model driving KIR came from live turns in the
operator's production model: slow, risky, and unrepeatable. Yet the half that
decides whether KIR is *drivable* needs no Revit at all — the compiler parses,
validates, grounds and refuses entirely offline, and its refusals are the same
bytes a live turn would see. So the whole authoring loop can be trained and
measured here:

    task -> model emits a program -> compile_program() judges it offline
         -> diagnostics go back verbatim -> model fixes -> repeat

What this is FOR is ergonomics, not correctness. The question is not "does the
compiler work" (the gate answers that) but "can a model that is good at 3D
actually pilot it" — how many programs a tower costs, which refusals it walks
into, and whether it recovers from them or thrashes. Those numbers move when we
change the schema, the idioms or the caps, and until now nothing measured them.

The commit stage is SIMULATED. A clean compile is reported as committed with
synthetic ids, because what is under test is authoring, not the bridge. Ops that
land are remembered across programs so multi-program builds (the >20-op case,
which is every interesting building) behave like a real session.

    python tools/kir_dojo.py --task eiffel --rounds 12
    python tools/kir_dojo.py --all --json runs/dojo-1.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from kukai.ir import macros  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.diag import KirRefusal  # noqa: E402
from kukai.ir.spec import OPS  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.ir.tool_doc import build_tool_description  # noqa: E402
from tools.design import kir_coherence  # noqa: E402

BACKEND = pathlib.Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------- the ground

#: The fixture is a flat, thin project. A model building a tower asks for beam
#: and column types that a real building has and the fixture does not, and would
#: spend its rounds fighting grounding instead of geometry. These extra pools are
#: additive: every fixture id is untouched, so a dojo refusal still means the
#: same thing a unit test's would.
EXTRA_POOLS: dict[str, list[dict]] = {
    "beam_types": [
        {"id": 1100, "name": "Балка 200x400"},
        {"id": 1110, "name": "М_Балка-Двутавр: 200x100"},
        {"id": 1111, "name": "Бетон-Балка прямоугольного сечения: 300 x 600"},
        {"id": 1112, "name": "Уголок 100x100x10"},
    ],
    "column_symbols_structural": [
        {"id": 500, "name": "К 300x300"},
        {"id": 510, "name": "Бетон-Квадратная колонна: 400 x 400"},
    ],
    "levels": [
        {"id": 42, "name": "Этаж 1"},
        {"id": 43, "name": "Этаж 2"},
        {"id": 44, "name": "Уровень 1"},
    ],
}


def ground_snapshot() -> dict:
    snap = {k: list(v) for k, v in GROUND_SNAPSHOT.items()}
    for pool, rows in EXTRA_POOLS.items():
        by_id = {r["id"]: r for r in snap.get(pool, [])}
        for r in rows:
            by_id[r["id"]] = r
        snap[pool] = list(by_id.values())
    return snap


#: What a building is made of, by discipline. A project is not a number — asked
#: for "≥10 000 elements" the model returned 12 185, of which 12 020 were
#: columns: one 20-column grid placed 601 times, no rooms, no doors, no windows,
#: no partitions. It met the target with the cheapest element that exists. So
#: the target is composition: each discipline must be PRESENT, and no single op
#: may carry the building.
DISCIPLINES: dict[str, tuple[str, ...]] = {
    "КР": ("create_column", "create_beam", "create_foundation", "create_floor",
           "create_floor_by_contour"),
    "АР": ("create_wall", "create_door", "create_window", "create_room",
           "create_stairs", "create_roof"),
}

#: Above this share of the whole model, one op type IS the model.
MAX_SHARE = 0.55


#: Every field a goal may carry, and the only fields anything reads. A goal is
#: the ONE thing standing between "the model said ГОТОВО" and "the task is done",
#: so a key nobody consumes is not a harmless typo: five of the seven tasks
#: shipped `min_ops`/`ops`, nothing read them, and an EMPTY run was reported as
#: having reached the goal. The schema is closed so that failure mode cannot
#: come back — an unknown key is a refusal at load, not silence at runtime.
GOAL_KEYS: tuple[str, ...] = (
    "min_elements",        # пол по числу созданных элементов
    "min_ops",             # тот же пол, как его пишут простые задачи
    "ops",                 # каждая названная операция обязана встретиться
    "must_have",           # то же самое для крупных брифов
    "min_per_discipline",  # пол по разделам; он же включает гейт доминирования
)


def _positive_int(goal: dict, key: str) -> None:
    v = goal.get(key)
    if v is None:
        return
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        raise ValueError(f"{key}: нужно положительное целое, а не {v!r}")


def validate_goal(goal: Any) -> dict[str, Any]:
    """A goal that cannot be read is a goal that cannot be failed.

    Checks the names AND the values: closed names alone catch `min_opz`, they do
    not catch `min_ops="сорок"` or an op name that no version of KIR has.
    """
    if not isinstance(goal, dict) or not goal:
        raise ValueError("цель пуста: такую закрывает прогон, который ничего не построил")
    unknown = sorted(set(goal) - set(GOAL_KEYS))
    if unknown:
        raise ValueError(
            f"в цели ключи, которые никто не читает: {unknown}. "
            f"Известные: {list(GOAL_KEYS)}")
    _positive_int(goal, "min_elements")
    _positive_int(goal, "min_ops")
    for key in ("ops", "must_have"):
        v = goal.get(key)
        if v is None:
            continue
        if isinstance(v, str) or not isinstance(v, (list, tuple)) or not v:
            raise ValueError(f"{key}: непустой список имён операций, а не {v!r}")
        for op in v:
            if op not in OPS:
                raise ValueError(f"{key}: в KIR нет операции {op!r}")
    mpd = goal.get("min_per_discipline")
    if mpd is not None:
        if not isinstance(mpd, dict) or not mpd:
            raise ValueError(f"min_per_discipline: непустое раздел→порог, а не {mpd!r}")
        for d in mpd:
            if d not in DISCIPLINES:
                raise ValueError(f"min_per_discipline: нет такого раздела: {d!r}")
            _positive_int(mpd, d)
    return goal


# ----------------------------------------------------------------- the tasks

class Task:
    def __init__(self, key: str, prompt: str, goal: dict[str, Any]):
        self.key, self.prompt, self.goal = key, prompt, validate_goal(goal)


TASKS: dict[str, Task] = {
    "eiffel": Task(
        "eiffel",
        "Построй Эйфелеву башню из балок: высота 300 м, квадратное основание "
        "125×125 м, четыре наклонённых внутрь ребра, горизонтальные пояса и "
        "диагональные раскосы между ними. Начало координат башни — точка "
        "(300000, 0). Строй, пока башня не будет собрана целиком.",
        {"min_ops": 40, "ops": ["create_beam"]},
    ),
    "frame": Task(
        "frame",
        "Собери каркас здания 30×18 м, 5 этажей по 3.3 м: колонны по сетке "
        "6×6 м, балки по периметру и по осям на каждом этаже.",
        {"min_ops": 60, "ops": ["create_column", "create_beam"]},
    ),
    "spiral": Task(
        "spiral",
        "Построй винтовую башню: 20 ярусов по 4 м, на каждом ярусе 8 колонн "
        "по окружности радиусом 12 м, каждый ярус повёрнут на 9° относительно "
        "предыдущего. Между ярусами — кольцевые балки.",
        {"min_ops": 60, "ops": ["create_column", "create_beam"]},
    ),
    "dome": Task(
        "dome",
        "Построй решётчатый купол радиусом 30 м из балок: 6 колец по широте и "
        "16 меридианов.",
        {"min_ops": 60, "ops": ["create_beam"]},
    ),
    "skyscraper": Task(
        "skyscraper",
        "Построй современный небоскрёб — ОДНУ башню делового центра: высота "
        "около 250 м, 60 этажей по 4 м, плита в плане примерно 45×45 м с "
        "сужением кверху. Нужен ПОЛНЫЙ проект, а не силуэт.\n\n"
        "КР: сваи/фундамент, ядро жёсткости в центре, колонны по периметру и "
        "по внутренней сетке на каждом этаже, балки перекрытий в двух "
        "направлениях, плиты перекрытий.\n"
        "АР: наружное остекление по всему периметру каждого этажа, внутренние "
        "перегородки и квартиры/офисы на типовом этаже, двери в каждое "
        "помещение, помещения (create_room), лестницы и лифтовые шахты в ядре, "
        "кровля.\n\n"
        "Масштаб обязателен: в настоящем таком здании десятки тысяч элементов. "
        "Но масштаб набирается СОСТАВОМ, а не одним элементом: башня из одних "
        "колонн — не проект. Инструмент после каждой программы возвращает "
        "состав модели по операциям и разделам и говорит, чего не хватает — "
        "работай по этому списку, пока он не опустеет. Начало координат (0,0).",
        {"min_elements": 10000,
         "min_per_discipline": {"КР": 3000, "АР": 3000},
         "must_have": ("create_column", "create_beam", "create_wall",
                       "create_door", "create_window", "create_room",
                       "create_floor_by_contour")},
    ),
    "moscowcity": Task(
        "moscowcity",
        "Построй башню уровня «Москва-Сити» — ОДНУ, но сложной формы, а не "
        "коробку. Ориентир: «Эволюшн» и соседние башни — эллиптический план, "
        "который заметно сужается кверху и ЗАКРУЧИВАЕТСЯ вокруг вертикальной "
        "оси; криволинейная стеклянная оболочка.\n\n"
        "Высота 250–300 м, 55–60 этажей по 4.5 м, план в основании примерно "
        "44×30 м.\n"
        "КР: свайное поле, ядро жёсткости, колонны по периметру эллипса и по "
        "внутреннему кольцу, балки перекрытий, плита на каждом этаже.\n"
        "АР: сплошное остекление по периметру каждого этажа, внутренние "
        "перегородки и помещения на типовом этаже, двери, кровля.\n\n"
        "Форма важнее количества, но количество тоже важно: настоящая такая "
        "башня — это десятки тысяч элементов, набранных РАЗНЫМИ элементами. "
        "Начало координат (0,0).",
        {"min_elements": 10000,
         "min_per_discipline": {"КР": 3000, "АР": 3000},
         "must_have": ("create_column", "create_beam", "create_wall",
                       "create_door", "create_room",
                       "create_floor_by_contour")},
    ),
    "house": Task(
        "house",
        "Построй двухэтажный дом 12×9 м: наружные стены, перекрытие между "
        "этажами, скатная кровля, входная дверь и по два окна на фасад.",
        {"min_ops": 20, "ops": ["create_wall", "create_floor"]},
    ),
}

# --------------------------------------------------------------- the sparring

SYSTEM = """Ты — инженер-моделировщик. Твой единственный инструмент — `revit_ir`:
типизированные операции над моделью Revit. Компилятор владеет единицами,
версиями API и транзакциями; он проверяет каждую программу и отказывает с
названной причиной.

Правила ринга:

* Строй ТОЛЬКО через `revit_ir`. Другого инструмента нет.
* Одна программа — не более 20 операций. Крупное собирается ПАЧКОЙ программ:
  вызывай инструмент столько раз, сколько нужно, пока объект не собран целиком.
* Отказ — это данные. В нём есть код, поле, ожидаемое значение и часто список
  кандидатов. Прочитай, исправь названное, повтори.
* Координаты — в миллиметрах, все геометрические расчёты делай сам и точно.
* Не описывай план текстом. Вызывай инструмент.
* Инструмент возвращает `total_in_model` — сколько элементов уже стоит. Пока
  это число далеко от масштаба настоящего здания, работа не закончена.
* Когда объект собран полностью — напиши "ГОТОВО" и сколько элементов вышло."""


#: The practice under test. Held OUT of SYSTEM on purpose: a practice baked into
#: the prompt cannot be measured, and the only claim worth making about one is
#: that it changes what the model builds. `--practice` puts it in, its absence
#: is the control arm.
PRACTICE_FILE = BACKEND / "kukai" / "design" / "practice.md"


def practice_text() -> str:
    if not PRACTICE_FILE.exists():
        raise SystemExit(f"нет файла практики: {PRACTICE_FILE}")
    return PRACTICE_FILE.read_text(encoding="utf-8")


def tool_defs() -> list[dict]:
    """Инструмент стенда — ТОЙ ЖЕ формы, что уезжает в прод.

    Стенд обязан спрашивать то же, что спрашивает продовый ход, иначе он мерит
    другой продукт. Открытый вопрос дедупликации («читает ли модель `$defs` так
    же хорошо, как плоскую схему») теперь разрешается ОДНОЙ переменной:
    `KUKAI_KIR_SCHEMA_DEDUP=0` даёт плоское плечо A, `=1` — свёрнутое плечо B,
    остальной прогон байт в байт одинаков.
    """
    from kukai.ir.schema_transport import program_schema_for_tool
    program, note = program_schema_for_tool()
    print(f"[стенд] {note}")
    return [{
        "type": "function",
        "function": {
            "name": "revit_ir",
            "description": build_tool_description(),
            "parameters": {
                "type": "object",
                "properties": {"program": program},
                "required": ["program"],
            },
        },
    }]


def _env(name: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name]
    envf = BACKEND / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return default


def call_model(messages: list[dict], tools: list[dict], *, timeout: int = 300) -> dict:
    url = _env("KUKAI_CODEXPROXY_URL", "http://127.0.0.1:8317").rstrip("/")
    body = json.dumps({
        "model": _env("KUKAI_CODEXPROXY_MODEL", "gpt-5.6-terra"),
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": int(_env("KUKAI_CODEXPROXY_MAX_TOKENS", "64000")),
    }, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{url}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_env('KUKAI_CODEXPROXY_API_KEY')}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _op_names(program: Any) -> list[str]:
    ops = program.get("ops") if isinstance(program, dict) else None
    return [o.get("op") for o in ops if isinstance(o, dict)] if isinstance(ops, list) else []


def composition(programs: Any) -> dict[str, Any]:
    """Per-op-type element counts plus the two facts that decide 'building or
    not': is every discipline represented, and does one type dominate."""
    by_op: dict[str, int] = {}
    for p in programs:
        for op, n in _per_op(p).items():
            by_op[op] = by_op.get(op, 0) + n
    total = sum(by_op.values())
    top = max(by_op.items(), key=lambda kv: kv[1], default=("", 0))
    present = {d: sum(by_op.get(o, 0) for o in ops)
               for d, ops in DISCIPLINES.items()}
    return {
        "total": total,
        "by_op": dict(sorted(by_op.items(), key=lambda kv: -kv[1])),
        "by_discipline": present,
        "dominant": {"op": top[0], "share": round(top[1] / total, 3) if total else 0},
        "kinds": len(by_op),
    }


def composition_verdict(comp: dict, goal: dict) -> tuple[bool, list[str]]:
    """(good_enough, what is missing) — the text goes back to the model.

    Every key of `goal` is read here and nowhere else; `validate_goal` refuses
    any other key, so "the goal says X" and "X is enforced" cannot drift apart.

    С 28.07 состав считается по РАСКРЫТЫМ макросам; числа прогонов до этой даты
    несравнимы (та же дисциплина, что у версий канона): здание, написанное через
    `stack`/`grid_array`, до этой даты засчитывалось как ноль элементов.
    """
    gaps: list[str] = []
    # `min_ops` is how the five small tasks spell the same floor `min_elements`
    # spells for the big ones. Both are measured in ELEMENTS, not in written
    # lines: `elements_in()` below explains why at length — one `create_group`
    # materialises up to 200×4096 elements, so a floor on lines would punish
    # exactly the idiom this dojo tells the model to use.
    floor = max(int(goal.get("min_elements", 0)), int(goal.get("min_ops", 0)))
    if comp["total"] < floor:
        gaps.append(f"элементов {comp['total']}, нужно не меньше {floor}")
    for d, need in (goal.get("min_per_discipline") or {}).items():
        have = comp["by_discipline"].get(d, 0)
        if have < need:
            gaps.append(f"{d}: {have} элементов, нужно не меньше {need}")
    for op in tuple(goal.get("must_have", ())) + tuple(goal.get("ops", ())):
        if not comp["by_op"].get(op):
            gaps.append(f"нет ни одного {op}")
    # Dominance is a defect only where the brief asked for several disciplines.
    # On eiffel and dome the brief asks for a lattice of BEAMS and nothing else,
    # so the share of `create_beam` is 100% by construction: the gate made those
    # two tasks unpassable in principle rather than measuring anything.
    if goal.get("min_per_discipline"):
        dom = comp["dominant"]
        if dom["share"] > MAX_SHARE:
            gaps.append(f"{dom['op']} — {dom['share'] * 100:.0f}% всей модели; "
                        f"это не проект, а один повторённый элемент")
    return (not gaps), gaps


def _no_goal_is_met_by_building_nothing() -> None:
    """The one property a goal must have, checked on the corpus at import.

    `validate_goal` can only see the shape of a goal; this sees its meaning. A
    task whose goal an empty run satisfies measures nothing at all, and that is
    not hypothetical — until 2026-07-28 five of the seven were exactly that.
    """
    empty = composition([])
    reachable = [k for k, t in TASKS.items()
                 if composition_verdict(empty, t.goal)[0]]
    if reachable:
        raise ValueError(f"эти задачи закрывает пустой прогон: {reachable}")


_no_goal_is_met_by_building_nothing()


#: Операции, которыми в KIR кладут горизонтальную опору.
SLAB_OPS: tuple[str, ...] = ("create_floor", "create_floor_by_contour",
                             "create_roof")

#: Каждый факт связности говорит о ПАРЕ элементов, и осмыслен он только там, где
#: бриф заказал вторую половину пары. Эйфелева башня — решётка из одних балок:
#: колонн в ней нет и не будет, поэтому «100% балок не доходят ни до одной
#: колонны» — это не дефект модели, это проверка, вышедшая за задание. Тот же
#: разбор, что у гейта доминирования: замер, невыполнимый в принципе, не
#: измеряет ничего и просто сжигает бюджет раундов.
COHERENCE_SCOPE: dict[str, tuple[str, ...]] = {
    "колонн_вне_плиты": SLAB_OPS,
    "стен_вне_плиты": SLAB_OPS,
    "балок_без_опоры": ("create_column",),
    "следование_форме": SLAB_OPS + ("create_column",),
}


def binding_coherence(rep: dict, goal: dict) -> tuple[list[str], list[str]]:
    """(что связность ЗАПРЕЩАЕТ, что она просто заметила).

    Меряется всё и всегда — сужается только право закрыть задачу. Отчёт целиком
    остаётся в записи прогона: снять замер и не дать его к делу — разные вещи,
    и вторая не должна стирать первую.
    """
    required = set(goal.get("ops", ())) | set(goal.get("must_have", ()))
    scoped = dict(rep)
    for key, needs in COHERENCE_SCOPE.items():
        if not any(op in required for op in needs):
            scoped[key] = None if key == "следование_форме" else 0
    binding = kir_coherence.gaps(scoped)
    noted = [g for g in kir_coherence.gaps(rep) if g not in binding]
    return binding, noted


#: Уровни и оси — базовые линии, а не состав здания. Без этого исключения
#: масштаб набирался бы самым дешёвым, что есть в KIR (`grid_array` — это
#: десятки «элементов» одной строкой), и заодно размывалась бы доля
#: доминирующего типа: оси не принадлежат ни одному разделу.
DATUM_OPS: tuple[str, ...] = ("create_level", "create_grid")


def _expanded_ops(program: Any) -> list[dict]:
    """Опы программы ПОСЛЕ раскрытия макросов — единственная точка раскрытия.

    `stack`/`grid_array` — не сахар, а способ сказать здание малым числом строк:
    одна строка `stack(levels=60, floor=[...])` — это шестьдесят этажей. Счётчик,
    читающий сырой `program["ops"]`, видит там ОДИН оп по имени `stack` и считает
    ноль, тогда как связность (`coherence.flatten`) раскрывает и видит здание —
    два замера одного прогона расходились на всё здание, и наказан был ровно тот
    приём, которому дожо само и учит.
    """
    ops = program.get("ops") if isinstance(program, dict) else program
    if not isinstance(ops, list):
        return []
    try:
        ops = macros.expand(ops)
    except KirRefusal:
        # Программу, которую компилятор принял, раскрывали успешно ещё до
        # подсчёта, так что сюда доходит только та, что до `judge()` не дошла
        # (черновик, тест). Она стоит нуля, а не падения всего прогона. Ловится
        # ровно отказ макроса: голый `except` превратил бы любой дефект
        # раскрытия в тихий ноль — в ту же самую находку, только необнаружимую.
        return []
    return [o for o in ops if isinstance(o, dict)]


def _per_op(program: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for o in _expanded_ops(program):
        name = o.get("op") or ""
        if name == "create_group":
            k = 1 + len(o.get("placements") or [])
            for m in o.get("members") or []:
                if isinstance(m, dict) and (m.get("op") or "").startswith("create_"):
                    out[m["op"]] = out.get(m["op"], 0) + k
        elif name.startswith("create_") and name not in DATUM_OPS:
            out[name] = out.get(name, 0) + 1
    return out


def elements_in(program: Any) -> int:
    """How many elements land in the model — NOT how many ops were written.

    Counting ops called a 200-member group placed 60 times "1 element" and
    reported a 12 000-element tower as a dozen. The gap is the whole point of
    the op: one program can author up to 200 × 4096 elements, measured — so a
    score that counts ops measures the author's typing, not the building. The
    same gap is what `stack` opens, and for the same reason it is counted the
    same way: through `_per_op`, on the EXPANDED ops. One expression, so the
    run's `elements` and its `composition.total` cannot drift apart.
    """
    return sum(_per_op(program).values())


def judge(program: Any, snapshot: dict, *, revit_version: str = "2026") -> dict:
    """Compile offline and answer in the shape the live handler answers.

    A clean compile also hands back the emitted `csharp`. The dojo itself never
    looks at it — it replaces this dict wholesale for accepted programs — but
    the mission bench must put the SAME emission through the SAME Roslyn the
    C#-arm faces, and re-compiling to get it would judge a second compilation
    instead of this one.

    `revit_version` is a parameter for the same reason: emission is per-version
    (SPEC 11.2), so a caller that compiles the result against one version's
    reference assemblies must be able to ask for THAT version's emission. The
    default is the dojo's own 2026 and no dojo behaviour moves.
    """
    try:
        out = compile_program(program, revit_version=revit_version,
                              snapshot=snapshot)
    except Exception as exc:  # noqa: BLE001 — compile_program swears it never raises
        return {"ok": False, "harness_error": f"{type(exc).__name__}: {exc}"}
    if not getattr(out, "ok", False):
        diags = [d.to_dict() if hasattr(d, "to_dict") else
                 {k: v for k, v in vars(d).items() if v is not None}
                 for d in (getattr(out, "diagnostics", None) or [])]
        return {"ok": False, "diagnostics": diags}
    # `CompileOutput.csharp`, not `.code`: the field never existed, and
    # `getattr` with a default reported every accepted program as 0 chars of
    # emitted C# — a metric that was silently constant.
    cs = getattr(out, "csharp", "") or ""
    return {"ok": True, "cs_chars": len(cs), "csharp": cs}


#: Two prompts, because the first look and the later ones ask different things.
#:
#: A single "сверься с задачей" prompt measurably does nothing: on 2026-07-27 the
#: model looked at a straight lattice cone three times and answered "ГОТОВО — 4
#: наклонные балки, 28 поясов, 48 раскосов" every time. It was not blind and it
#: was not lying — it was checking the drawing against its OWN plan, which the
#: drawing did match. The plan was the mediocre part, and nothing in the loop
#: ever put the plan on trial. So the first look forbids the verdict and demands
#: differences from the real thing instead; the model knows what an Eiffel Tower
#: looks like, it just was not asked.
FIRST_LOOK = (
    "Вот что у тебя получилось — три ортогональных вида, начерчено ПО ТВОИМ ЖЕ "
    "координатам, ничего не додумано.\n\n{report}\n\n"
    "НЕ подводи итог и не пиши ГОТОВО в этом ответе. Сравни картинку не со "
    "своим замыслом, а с тем, как объект из задачи выглядит НА САМОМ ДЕЛЕ. "
    "Назови минимум три конкретных отличия: силуэт и характер сужения, "
    "пропорции ярусов, узнаваемые части, которых нет. Затем исправь самое "
    "важное через `revit_ir` — достраивая, а не снося уже стоящее.")

LATER_LOOK = (
    "Так стало.\n\n{report}\n\n"
    "Стало ближе к настоящему объекту или нет? Если осталось что-то важное — "
    "доделай через `revit_ir`. Если объект действительно похож — напиши ГОТОВО "
    "и сколько элементов.")


def spar(task: Task, *, max_rounds: int, verbose: bool = True,
         look: bool = True, max_looks: int = 3, practice: bool = False,
         shots_dir: pathlib.Path | None = None) -> dict:
    snapshot = ground_snapshot()
    tools = tool_defs()
    system = SYSTEM if not practice else SYSTEM + "\n\n" + practice_text()
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": task.prompt}]
    rec: dict[str, Any] = {
        "task": task.key, "rounds": 0, "programs": 0, "accepted": 0,
        # Оба числа, а не одно: `ops_written` — сколько строк написано,
        # `ops_expanded` — сколько опов из них вышло. Одно число растворяет
        # умение сказать много малым: `ops=1` не отличить от пустой программы,
        # `ops=30` — от тридцати написанных строк.
        "refused": 0, "ops_written": 0, "ops_expanded": 0,
        "codes": {}, "ops_used": {},
        "no_call_rounds": 0, "harness_errors": 0, "said_done": False,
        "coherence_notes": [],
        "empty_replies": 0, "empty_detail": [], "elements": 0,
        "rejected_done": 0,
        "practice": practice,
        "looks": 0, "fixed_after_look": 0, "wall_s": 0.0, "transcript": [],
    }
    committed: list[Any] = []
    t0 = time.time()

    def coherence_now() -> tuple[dict, list[str], list[str]]:
        """Отчёт связности, что он запрещает и что просто заметил. Одна точка на
        три места вызова: три копии одного выражения расходятся ровно тогда,
        когда проверка меняется, а меняется она каждый раз, когда находится
        новый способ построить формально верную чепуху."""
        rep = kir_coherence.check(kir_coherence.flatten(committed))
        binding, noted = binding_coherence(rep, task.goal)
        return rep, binding, noted

    def show() -> bool:
        """Render what stands and hand it back. False if there is nothing yet."""
        from tools.design import kir_eye
        d = kir_eye.collect(committed)
        if not d.segments:
            return False
        png = kir_eye.render(d, title=task.key)
        rec["looks"] += 1
        if shots_dir is not None:
            shots_dir.mkdir(parents=True, exist_ok=True)
            (shots_dir / f"{task.key}-look{rec['looks']}.png").write_bytes(png)
        note = kir_eye.report(d)
        rec["transcript"].append({"look": rec["looks"], "report": note})
        if verbose:
            print(f"  👁  look{rec['looks']}: {note}", flush=True)
        # Only the CURRENT drawing stays an image. Older looks become their one
        # line of text: the model has already reacted to them, and every kept
        # picture is ~90KB of base64 riding along in every later request — the
        # cost that stopped the route answering.
        for m in messages:
            if m.get("role") == "user" and isinstance(m.get("content"), list):
                kept = [c for c in m["content"] if c.get("type") == "text"]
                if len(kept) != len(m["content"]):
                    m["content"] = (kept or [{"type": "text", "text": ""}])
        text = (FIRST_LOOK if rec["looks"] == 1 else LATER_LOOK).format(report=note)
        messages.append({"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "image_url",
             "image_url": {"url": kir_eye.data_url(png)}}]})
        return True

    # Rounds count what the model actually DID. A retried empty reply must not
    # eat the budget the task was given, so it advances `attempts`, not `rnd`.
    rnd, attempts = 0, 0
    while rnd < max_rounds and attempts < max_rounds * 3:
        attempts += 1
        try:
            resp = call_model(messages, tools)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            rec["transcript"].append({"round": rnd, "transport_error": str(exc)})
            break
        choice = (resp.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = msg.get("tool_calls") or []
        text = (msg.get("content") or "").strip()

        # An answer with neither text nor a call is not an answer. Appending it
        # — plus a "you didn't call anything" nudge — poisons the history: the
        # 2026-07-27 run alternated empty/real for its whole second half, so
        # half the rounds bought nothing and the look critique was never spoken.
        # Retry the SAME request instead of recording the hole.
        if not calls and not text:
            rec["empty_replies"] += 1
            usage = resp.get("usage") or {}
            rec["empty_detail"].append({
                "after_round": rnd,
                "finish": choice.get("finish_reason"),
                "native_finish": choice.get("native_finish_reason"),
                "prompt_tok": usage.get("prompt_tokens"),
                "out_tok": usage.get("completion_tokens"),
                "reason_tok": (usage.get("completion_tokens_details")
                               or {}).get("reasoning_tokens"),
                "msgs": len(messages),
            })
            continue

        rnd += 1
        rec["rounds"] = rnd
        messages.append({"role": "assistant",
                         "content": msg.get("content") or "",
                         "tool_calls": calls or None})
        if not calls:
            rec["no_call_rounds"] += 1
            if re.search(r"\bготово\b", text, re.I):
                rec["transcript"].append({"round": rnd, "done": text[:400]})
                # "Готово" is a CLAIM, and the claim is checked before it is
                # allowed to end anything. Left unchecked the model stops at a
                # concept — 179 elements, then 500 — because from inside, a
                # coherent massing feels finished. The composition target is
                # objective, so a claim that contradicts it is simply refused
                # and the shortfall handed back, for as many rounds as the
                # budget allows.
                ok_enough, gaps = composition_verdict(
                    composition(committed), task.goal)
                _, coh, _noted = coherence_now()
                gaps = gaps + coh
                ok_enough = ok_enough and not coh
                if not ok_enough:
                    rec["rejected_done"] += 1
                    if verbose:
                        print(f"  ✗ «готово» отклонено ({rec['rejected_done']}): "
                              f"{len(gaps)} пунктов не закрыто", flush=True)
                    messages.append({"role": "user", "content":
                        "Работа НЕ закончена. Это не концепция и не МВП — нужно "
                        "полноценное здание. Не закрыто:\n— "
                        + "\n— ".join(gaps)
                        + "\n\nПродолжай через `revit_ir`, пока список не "
                          "опустеет. Масштаб набирается группами: типовой "
                          "фрагмент в `members` (до 200 опов) и его повторы в "
                          "`placements` (до 4096) — это тысячи элементов одной "
                          "операцией. Не объявляй готовность снова, пока в "
                          "списке что-то есть."})
                    continue
                if look and rec["looks"] < max_looks and show():
                    continue
                rec["said_done"] = True
                break
            rec["transcript"].append({"round": rnd, "text_only": text[:400]})
            messages.append({"role": "user", "content":
                             "Ты не вызвал инструмент. Вызови `revit_ir` и "
                             "продолжай стройку."})
            continue

        for call in calls:
            rec["programs"] += 1
            fname = (call.get("function") or {}).get("name")
            raw = (call.get("function") or {}).get("arguments") or "{}"
            n_ops = n_expanded = 0
            try:
                args = json.loads(raw)
            except json.JSONDecodeError as exc:
                result = {"ok": False, "harness_error": f"нечитаемый JSON: {exc}"}
                rec["harness_errors"] += 1
            else:
                program = args.get("program", args)
                # `ops_used` — словарь АВТОРА: что он писал, включая `stack`.
                # Сколько из этого вышло опов, говорит `n_expanded`.
                names = _op_names(program)
                n_ops = len(names)
                n_expanded = len(_expanded_ops(program))
                for n in names:
                    rec["ops_used"][n] = rec["ops_used"].get(n, 0) + 1
                result = judge(program, snapshot) if fname == "revit_ir" else {
                    "ok": False, "harness_error": f"нет такого инструмента: {fname}"}
                if result.get("ok"):
                    rec["accepted"] += 1
                    rec["ops_written"] += n_ops
                    rec["ops_expanded"] += n_expanded
                    n_elems = elements_in(program)
                    rec["elements"] += n_elems
                    committed.append(program)
                    if rec["looks"]:
                        rec["fixed_after_look"] += n_elems
                    comp = composition(committed)
                    ok_enough, gaps = composition_verdict(comp, task.goal)
                    _, coh, _noted = coherence_now()
                    gaps = gaps + coh
                    ok_enough = ok_enough and not coh
                    result = {"status": "committed",
                              "created": n_elems,
                              "ops": n_ops,
                              "ops_expanded": n_expanded,
                              "модель_сейчас": {
                                  "всего": comp["total"],
                                  "по_операциям": comp["by_op"],
                                  "по_разделам": comp["by_discipline"]},
                              "чего_не_хватает": gaps or "ничего — состав и связность в порядке",
                              "работа_закончена": bool(ok_enough),
                              "note": "Программа принята и зафиксирована."}
                elif result.get("harness_error"):
                    rec["harness_errors"] += 1
                else:
                    rec["refused"] += 1
                    for d in result.get("diagnostics", []):
                        c = d.get("code", "?")
                        rec["codes"][c] = rec["codes"].get(c, 0) + 1

            rec["transcript"].append({"round": rnd, "ops": n_ops,
                                      "ops_expanded": n_expanded,
                                      "result": result})
            if verbose:
                head = ("OK" if result.get("status") == "committed"
                        else ",".join(d.get("code", "?") for d in
                                      result.get("diagnostics", [])[:3])
                        or result.get("harness_error", "ERR")[:60])
                print(f"  r{rnd}: ops={n_ops}→{n_expanded} "
                      f"эл={result.get('created', 0)} {head}", flush=True)
            messages.append({"role": "tool",
                             "tool_call_id": call.get("id", ""),
                             "content": json.dumps(result, ensure_ascii=False)})

    # A run that ended on the round budget never got looked at. Draw it anyway
    # so every session leaves a picture — the record is worth less without one.
    if look and shots_dir is not None and committed:
        from tools.design import kir_eye
        d = kir_eye.collect(committed)
        if d.segments:
            shots_dir.mkdir(parents=True, exist_ok=True)
            (shots_dir / f"{task.key}-final.png").write_bytes(
                kir_eye.render(d, title=f"{task.key} (итог)"))
            rec["final_report"] = kir_eye.report(d)

    rec["wall_s"] = round(time.time() - t0, 1)
    comp = composition(committed)
    rec["composition"] = comp
    ok, gaps_ = composition_verdict(comp, task.goal)
    rec["coherence"], coh, rec["coherence_notes"] = coherence_now()
    rec["reached_goal"], rec["gaps"] = (ok and not coh), gaps_ + coh
    # The accepted programs ARE the record: without them a session cannot be
    # re-drawn when the renderer improves, and cannot be replayed as a
    # (task -> program -> verdict) training pair.
    rec["committed"] = committed
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", action="append", choices=sorted(TASKS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--json", help="append one record per task here")
    ap.add_argument("--no-look", action="store_true",
                    help="skip the render-and-look loop (measures blind authoring)")
    ap.add_argument("--max-looks", type=int, default=3)
    ap.add_argument("--practice", action="store_true",
                    help="дать модели prompts/practice_bim.md (арм А/Б-опыта)")
    ap.add_argument("--shots", default="data/dojo_shots",
                    help="where the renders land")
    a = ap.parse_args()

    keys = sorted(TASKS) if a.all else (a.task or ["eiffel"])
    records = []
    for k in keys:
        print(f"\n=== {k} ===", flush=True)
        rec = spar(TASKS[k], max_rounds=a.rounds, look=not a.no_look,
                   max_looks=a.max_looks, practice=a.practice,
                   shots_dir=pathlib.Path(a.shots))
        records.append(rec)
        print(f"  состав: {rec.get('composition', {}).get('by_op')}")
        if rec.get("gaps"):
            print(f"  не хватает: {'; '.join(rec['gaps'])}")
        print(f"  отклонено «готово»: {rec['rejected_done']}")
        print(f"  → ЭЛЕМЕНТОВ={rec['elements']} "
              f"ops={rec['ops_written']}→{rec['ops_expanded']} "
              f"programs={rec['programs']} "
              f"ok={rec['accepted']} refused={rec['refused']} "
              f"looks={rec['looks']} after_look={rec['fixed_after_look']} "
              f"codes={rec['codes']} goal={rec['reached_goal']} "
              f"{rec['wall_s']}s", flush=True)
    if a.json:
        p = pathlib.Path(a.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"\nwrote {len(records)} → {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
