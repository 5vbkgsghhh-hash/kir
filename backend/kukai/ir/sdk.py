"""KIR из Python — штатный разъём между питон-мозгами и руками компилятора.

Модель уже умеет numpy, shapely и scipy. Здание она умеет хуже. Разъём в том,
чтобы считать геометрию тем, чем её считают все — питоном и его библиотеками, —
а строить тем, что владеет единицами, версиями API и транзакциями:

    import numpy as np
    from kukai.ir import sdk

    p = sdk.program(intent="башня с талией")
    with p.stack(levels=10, h_mm=4000,
                 transform=sdk.transform(scale_xy_top=[0.8, 0.8],
                                         twist_deg_total=18)) as floor:
        for a in np.linspace(0, 2 * np.pi, 12, endpoint=False):
            floor.add(sdk.create_column(xy=[22000 * np.cos(a), 22000 * np.sin(a)],
                                        level=sdk.BY_MACRO, symbol="К 300x300"))
    out = p.compile(version="2023", snapshot=snap)

ГЛАВНЫЙ ЗАКОН этого модуля: билдеров здесь НЕ НАПИСАНО НИ ОДНОГО. Функция на
каждый оп рождается из `spec.OPS` на импорте — имена, обязательность и
умолчания берутся из `ParamSpec`. Рукописный билдер живёт ровно до первой
правки реестра, после чего врёт молча: сигнатура обещает поле, которого больше
нет, или молчит о появившемся. Здесь такой расход невозможен по конструкции —
новый оп получает питон-функцию в тот же момент, когда попадает в реестр, и
тест это стережёт.

Второй закон: НИКАКОЙ НОВОЙ СЕМАНТИКИ. SDK ничего не проверяет сам — правда о
корректности принадлежит компилятору, и раздвоить её значит завести второй
диалект языка. Всё, что здесь есть сверх реестра, — эргономика без семантики:
`level="Этаж 1"` вместо `{"by": "name", "value": "Этаж 1"}`, numpy-числа в
обычные, автоматические id. Ни одно из этих правил не может выразить того, чего
нет в реестре, и ни одно не может скрыть отказ.
"""

from __future__ import annotations

import inspect
import json
from typing import Any, Iterable

from kukai.ir import macros, spec
from kukai.ir.compiler import compile_program

__all__ = [
    "OMIT", "DEFAULT", "BY_MACRO", "Ref", "ref", "sel", "transform",
    "Program", "Stack", "program", "builders", "op_names",
]


class _Sentinel:
    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return self._name

    def __bool__(self) -> bool:
        return False


#: «Поле не задано». Отличается от None: None — законное значение для части
#: полей, а пропуск означает «пусть решает компилятор».
OMIT = _Sentinel("OMIT")

#: Селектор `{"by": "default"}` — «тип по умолчанию документа».
DEFAULT = _Sentinel("DEFAULT")

#: То же, что OMIT, но на месте вызова читается как утверждение, а не как
#: забывчивость: `level=sdk.BY_MACRO`.
#:
#: Реестр объявляет `level` обязательным (оп без уровня не построить), а
#: `macros.py` отказывает опу с уровнем ВНУТРИ `stack.floor` — уровень там
#: назначает экспансия. Два правила верны и не противоречат друг другу, но на
#: их шве питон-сигнатура обязана дать сказать «это поле назначит макрос».
#: Молча выкидывать заданный уровень SDK не станет: это спрятало бы отказ,
#: который автор всё равно получит от компилятора.
BY_MACRO = OMIT


class Ref:
    """Ссылка на оп той же программы — `{"by": "ref", "value": id}`.

    Возвращается из `Program.add`, поэтому связь между опами пишется питоном, а
    не строковыми id вручную: `door = p.add(sdk.create_door(host=wall, ...))`.
    """

    __slots__ = ("id",)

    def __init__(self, id: str) -> None:  # noqa: A002 — поле языка зовётся id
        self.id = id

    def __repr__(self) -> str:
        return f"Ref({self.id!r})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Ref) and other.id == self.id

    def __hash__(self) -> int:
        return hash(("Ref", self.id))


def ref(x: Any) -> Ref:
    """Ссылка из чего угодно узнаваемого: `Ref`, id-строки, словаря опа."""
    if isinstance(x, Ref):
        return x
    if isinstance(x, str):
        return Ref(x)
    if isinstance(x, dict) and isinstance(x.get("id"), str):
        return Ref(x["id"])
    raise TypeError(f"на что ссылка? {x!r}")


def _plain(v: Any) -> Any:
    """numpy/tuple/Ref -> то, что переживает json.dumps.

    Без этого разъём не работает вовсе: `np.float64` не сериализуется, а вся
    затея в том, чтобы координаты считались numpy. Преобразование утиное —
    numpy здесь не импортируется и не требуется.
    """
    if isinstance(v, Ref):
        return {"by": "ref", "value": v.id}
    if isinstance(v, (str, bool, int, float)) or v is None:
        return v
    if hasattr(v, "tolist") and not isinstance(v, (list, tuple)):
        return _plain(v.tolist())
    if hasattr(v, "item") and not isinstance(v, (list, tuple, dict)):
        try:
            return _plain(v.item())
        except (ValueError, AttributeError):
            pass
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


#: Виды параметров, которые в JSON выглядят как селектор. Классификация идёт по
#: `ParamSpec.kind`, а не по именам опов, — новый оп с селектором получает то же
#: удобство молча.
SELECTOR_KINDS = frozenset({"sel", "target", "target_w"})

#: ...и то же самое списком (`create_dimension.refs`, `move_elements.targets`).
SELECTOR_LIST_KINDS = frozenset({"refs_w", "targets_w"})


def unclassified_kinds() -> list[str]:
    """Виды параметров реестра, о которых SDK ничего не знает.

    Неизвестный вид не ломает ничего: он проходит через `_plain` как есть, и
    автор просто пишет селектор словарём руками. Но если это ВСЁ-ТАКИ селектор,
    удобство молча не появится — а молчание здесь неотличимо от «так и надо».
    Поэтому список отдаётся наружу и на него есть тест: новый вид параметра
    обязан быть осознанно отнесён к одной из групп.
    """
    known = SELECTOR_KINDS | SELECTOR_LIST_KINDS | PLAIN_KINDS
    return sorted({p.kind for o in spec.OPS.values() for p in o.params} - known)


#: Всё остальное едет в JSON как есть (числа, точки, перечисления, вложенные
#: объекты вроде `arc` и `contour`).
PLAIN_KINDS = frozenset({
    "arc", "bool", "deg", "enum", "fields", "filters", "graph_nodes",
    "graph_segments", "int", "kind_enum", "member_ops", "mm", "num",
    # `path` (wave/arch) — открытая ломаная create_railing. Едет как есть,
    # ровно как `pts`: это геометрия списком чисел, а не селектор, и никакого
    # удобства над ней SDK предложить не может.
    "path",
    # `mesh` (wave/shape) — {vertices_mm, triangles} у create_directshape.
    # Тоже едет как есть: это ОДНО значение с внутренним инвариантом (индексы
    # осмысленны только вместе со своим вершинным массивом), и разбирать его
    # на удобства SDK нечем — законы формы живут в mesh.py и проверяются
    # компилятором.
    "mesh",
    "placements", "pt_view2d", "pt_xy", "pt_xyz", "pts", "pts_list", "region",
    "slopes", "str", "str_long", "value", "vec3_mm",
})


def sel(value: Any, *, kind: str | None = None) -> dict:
    """Селектор из питон-значения.

    Строка -> по имени, целое -> по element_id, `Ref` -> по ссылке, `DEFAULT` ->
    тип документа по умолчанию, готовый словарь -> как есть. `kind` нужен там,
    где язык требует назвать вид элемента вместе с именем (`set_param.target`).
    Никакой проверки: что из этого допустимо в конкретном поле, знает
    компилятор, и знает он один.
    """
    if isinstance(value, dict):
        return value
    if value is DEFAULT:
        return {"by": "default"}
    if isinstance(value, Ref):
        return {"by": "ref", "value": value.id}
    if isinstance(value, bool):
        raise TypeError(f"селектор из bool? {value!r}")
    if isinstance(value, int):
        return {"by": "element_id", "value": int(value)}
    if isinstance(value, str):
        out = {"by": "name", "value": value}
        if kind is not None:
            out["kind"] = kind
        return out
    raise TypeError(f"не селектор: {value!r}")


def transform(*, scale_xy_top: Any = OMIT, twist_deg_total: Any = OMIT,
              offset_mm_top: Any = OMIT, pivot_mm: Any = OMIT) -> dict:
    """`stack.transform` — интерполяция плана от низа к верху.

    Поля именованные, потому что их четыре и все необязательные; проверяет их
    `macros._validate_transform`, а не эта функция.
    """
    got = {"scale_xy_top": scale_xy_top, "twist_deg_total": twist_deg_total,
           "offset_mm_top": offset_mm_top, "pivot_mm": pivot_mm}
    return {k: _plain(v) for k, v in got.items() if v is not OMIT}


# ─────────────────────────────────────────── билдеры, рождённые из реестра

def _coerce(p: spec.ParamSpec, value: Any) -> Any:
    if p.kind in SELECTOR_KINDS:
        return sel(value)
    if p.kind in SELECTOR_LIST_KINDS and isinstance(value, (list, tuple)):
        return [sel(v) for v in value]
    return _plain(value)


def _doc_for(ospec: spec.OpSpec) -> str:
    lines = [f"`{ospec.name}` — {ospec.family}"
             f"{', пишет в модель' if ospec.writes_model else ''}.", ""]
    if ospec.post:
        lines += [f"Постусловие: {ospec.post}", ""]
    lines.append("Параметры (из реестра, не из этого файла):")
    for p in ospec.params:
        bits = [p.kind]
        if p.required:
            bits.append("обязательный")
        if p.default is not None:
            bits.append(f"умолчание {p.default!r}")
        if p.choices:
            bits.append(f"из {list(p.choices)}")
        lines.append(f"  {p.name} — {', '.join(bits)}")
    grounded = [n for n, _pool, _r in ospec.grounded]
    if grounded:
        lines += ["", f"Заземляются по снапшоту: {grounded}."]
    return "\n".join(lines)


def _make_builder(ospec: spec.OpSpec):
    """Функция-билдер по спецификации опа. Единственное место, где вообще
    появляются питон-сигнатуры KIR."""
    P = inspect.Parameter
    params = [P(p.name, P.POSITIONAL_OR_KEYWORD) for p in ospec.params if p.required]
    params += [P(p.name, P.KEYWORD_ONLY,
                 default=(OMIT if p.default is None else p.default))
               for p in ospec.params if not p.required]
    # `id` — не параметр реестра, но принимает его каждый оп: это адрес, по
    # которому на оп ссылаются соседи. Пропущенный проставит Program.
    params.append(P("id", P.KEYWORD_ONLY, default=OMIT))
    sig = inspect.Signature(params)
    by_name = {p.name: p for p in ospec.params}

    def builder(*args: Any, **kwargs: Any) -> dict:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        out: dict[str, Any] = {"op": ospec.name}
        oid = bound.arguments.pop("id")
        if oid is not OMIT:
            out["id"] = oid
        for name, value in bound.arguments.items():
            if value is OMIT:
                continue
            out[name] = _coerce(by_name[name], value)
        return out

    builder.__name__ = ospec.name
    builder.__qualname__ = ospec.name
    builder.__signature__ = sig
    builder.__doc__ = _doc_for(ospec)
    builder.op_spec = ospec
    return builder


#: Все билдеры, по имени опа. Собираются на импорте из `spec.OPS` — и потому
#: их ровно столько, сколько опов в реестре, всегда.
BUILDERS: dict[str, Any] = {name: _make_builder(ospec)
                            for name, ospec in sorted(spec.OPS.items())}
globals().update(BUILDERS)
__all__ += sorted(BUILDERS)


def builders() -> dict[str, Any]:
    """Копия таблицы билдеров — для интроспекции и тестов."""
    return dict(BUILDERS)


def op_names(*, writes: bool | None = None) -> list[str]:
    """Имена опов реестра; `writes=True` — только те, что пишут в модель."""
    return sorted(n for n, o in spec.OPS.items()
                  if writes is None or o.writes_model is writes)


# ──────────────────────────────────────────────────────────────── программа

class _OpSink:
    """Общая часть программы и этажа стека: список опов и раздача id."""

    def __init__(self) -> None:
        self.ops: list[dict] = []
        self._seq: dict[str, int] = {}

    def _next_id(self, op_name: str) -> str:
        n = self._seq.get(op_name, 0) + 1
        self._seq[op_name] = n
        return f"{op_name[7:] if op_name.startswith('create_') else op_name}{n}"

    def add(self, *ops: dict) -> Any:
        """Добавить опы, проставив пропущенные id. Возвращает `Ref` (или их
        список), чтобы соседний оп ссылался питоном, а не строкой."""
        made: list[Ref] = []
        for op in ops:
            if not isinstance(op, dict) or "op" not in op:
                raise TypeError(f"это не оп: {op!r}")
            if not op.get("id"):
                # id сразу за `op`: программу читают глазами чаще, чем парсером.
                rest = {k: v for k, v in op.items() if k != "op"}
                op = {"op": op["op"], "id": self._next_id(op["op"]), **rest}
            self.ops.append(op)
            made.append(Ref(op["id"]))
        return made[0] if len(made) == 1 else made

    def __len__(self) -> int:
        return len(self.ops)

    def __iter__(self):
        return iter(self.ops)


class Stack(_OpSink):
    """Типовой этаж макроса `stack`, собираемый как контекст.

    Опы внутри НЕ получают `level` — его назначает экспансия, и `macros.py`
    отказывает, если задать его руками. Поэтому этаж и отделён от программы
    отдельным объектом: в него нельзя случайно добавить оп с уровнем.
    """

    def __init__(self, macro: dict) -> None:
        super().__init__()
        self.macro = macro
        macro["floor"] = self.ops

    def __enter__(self) -> "Stack":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    @property
    def ref(self) -> Ref:
        return Ref(self.macro["id"])


class Program(_OpSink):
    """Одна программа KIR: конверт, опы, компиляция.

    Программа — единица, а не всё здание: язык держит 20 авторских опов до
    экспансии и 320 после (`compiler.MAX_OPS_PER_PROGRAM` / `MAX_VALIDATED_OPS`),
    так что башня — это ПАЧКА программ, как и в живом ходе. Здесь это видно, а
    не спрятано: счётчики отдаются наружу, чтобы скрипт сам решал, когда
    открыть следующую.
    """

    def __init__(self, *, intent: str | None = None,
                 defaults: dict | None = None,
                 allow_destructive: bool | None = None) -> None:
        super().__init__()
        self.intent = intent
        self.defaults = defaults
        self.allow_destructive = allow_destructive

    def __enter__(self) -> "Program":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    # ── макросы ──────────────────────────────────────────────────────────
    def stack(self, *, levels: int, h_mm: Any = OMIT, base_elev_mm: Any = OMIT,
              name_prefix: Any = OMIT, transform: Any = OMIT,
              floor: Iterable[dict] | None = None, id: str | None = None
              ) -> Stack:
        """`stack` — типовой этаж, повторённый по высоте с интерполяцией плана.

        Поля перечислены явно, потому что макросы живут не в `spec.OPS`, а в
        `macros.py`; проверяет их он же. Тест-страж гоняет полный набор полей
        через `macros.expand` — если макрос переименует поле, страж падает.
        """
        macro: dict[str, Any] = {"op": "stack", "levels": int(levels)}
        macro["id"] = id or self._next_id("stack")
        for key, value in (("h_mm", h_mm), ("base_elev_mm", base_elev_mm),
                           ("name_prefix", name_prefix), ("transform", transform)):
            if value is not OMIT:
                macro[key] = _plain(value)
        self.ops.append(macro)
        st = Stack(macro)
        if floor:
            st.add(*floor)
        return st

    def grid_array(self, *, nx: Any = OMIT, ny: Any = OMIT, dx_mm: Any = OMIT,
                   dy_mm: Any = OMIT, origin_mm: Any = OMIT,
                   margin_mm: Any = OMIT, prefix_x: Any = OMIT,
                   prefix_y: Any = OMIT, id: str | None = None) -> Ref:
        """`grid_array` — прямоугольная сетка осей."""
        macro: dict[str, Any] = {"op": "grid_array"}
        macro["id"] = id or self._next_id("grid_array")
        for key, value in (("nx", nx), ("ny", ny), ("dx_mm", dx_mm),
                           ("dy_mm", dy_mm), ("origin_mm", origin_mm),
                           ("margin_mm", margin_mm), ("prefix_x", prefix_x),
                           ("prefix_y", prefix_y)):
            if value is not OMIT:
                macro[key] = _plain(value)
        self.ops.append(macro)
        return Ref(macro["id"])

    # ── выход ────────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        """Ровно тот JSON, который принимает компилятор и мост."""
        out: dict[str, Any] = {"ir_version": spec.IR_VERSION}
        if self.intent is not None:
            out["intent"] = self.intent
        if self.defaults is not None:
            out["defaults"] = {k: sel(v) for k, v in self.defaults.items()}
        if self.allow_destructive is not None:
            out["allow_destructive"] = bool(self.allow_destructive)
        out["ops"] = list(self.ops)
        return out

    def to_json(self, **kw: Any) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kw)

    def compile(self, *, version: str = "2023", snapshot: Any = None, **kw: Any):
        """Офлайн-компиляция. Сети нет, Revit нет, диагностики отдаются как
        есть — питон-объектами `Diagnostic`, а не текстом: скрипт, который
        чинит сам себя, должен читать `code` и `candidates`, а не парсить
        сообщение."""
        return compile_program(self.to_dict(), revit_version=version,
                               snapshot=snapshot, **kw)

    def compile_all(self, *, versions: Iterable[str] = spec.REVIT_VERSIONS,
                    snapshot: Any = None, **kw: Any) -> dict[str, Any]:
        """Все шесть версий Revit разом — эмиссия per-version (SPEC 11.2), и
        «скомпилировалось» без названной версии ничего не значит."""
        return {v: self.compile(version=v, snapshot=snapshot, **kw)
                for v in versions}

    # ── счётчики ─────────────────────────────────────────────────────────
    def expanded(self) -> list[dict]:
        """Опы после раскрытия макросов — то, что реально увидит компилятор."""
        try:
            return macros.expand(list(self.ops))
        except Exception:  # noqa: BLE001 — макрос, который откажет и в компиляторе
            return list(self.ops)

    def stats(self) -> dict[str, int]:
        """`ops_written` — сколько опов написано; `ops_expanded` — во сколько
        они развернулись; `elements` — сколько элементов встанет в модель.

        Три числа, а не одно: в одном растворяется ровно то, ради чего язык и
        нужен — умение сказать много малым.
        """
        exp = self.expanded()
        elements = 0
        for o in exp:
            name = o.get("op") or ""
            if name == "create_group":
                elements += len(o.get("members") or []) * (
                    1 + len(o.get("placements") or []))
            elif name.startswith("create_") and name != "create_level":
                elements += 1
        return {"ops_written": len(self.ops), "ops_expanded": len(exp),
                "elements": elements}


def program(*, intent: str | None = None, defaults: dict | None = None,
            allow_destructive: bool | None = None) -> Program:
    """Новая программа. Конверт (`intent`, `defaults`, `allow_destructive`) —
    те же поля, что у JSON, других нет."""
    return Program(intent=intent, defaults=defaults,
                   allow_destructive=allow_destructive)
