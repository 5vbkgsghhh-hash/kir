"""KIR from Python — the standard connector between python brains and the compiler's hands.

The model already knows numpy, shapely, and scipy. It knows the building
less well. The connector consists of treating geometry as everyone treats
it — python and its libraries — and building with what owns units, API
versions, and transactions:

    import numpy as np
    from kir import sdk

    p = sdk.program(intent="башня с талией")
    with p.stack(levels=10, h_mm=4000,
                 transform=sdk.transform(scale_xy_top=[0.8, 0.8],
                                         twist_deg_total=18)) as floor:
        for a in np.linspace(0, 2 * np.pi, 12, endpoint=False):
            floor.add(sdk.create_column(xy=[22000 * np.cos(a), 22000 * np.sin(a)],
                                        level=sdk.BY_MACRO, symbol="К 300x300"))
    out = p.compile(version="2023", snapshot=snap)

THE MAIN LAW of this module: NOT A SINGLE builder is written here. A
function for every op is born from `spec.OPS` at import time — names,
mandatoriness, and defaults are taken from `ParamSpec`. A hand-written
builder lives exactly until the first edit to the registry, after which it
lies silently: the signature promises a field that no longer exists, or
stays silent about one that appeared. Such a cost is impossible here by
construction — a new op gets a python function the very moment it lands in
the registry, and a test guards this.

The second law: NO NEW SEMANTICS. The SDK checks nothing itself — the truth
about correctness belongs to the compiler, and splitting it in two would
mean starting a second dialect of the language. Everything here beyond the
registry is ergonomics without semantics: `level="Этаж 1"` instead of
`{"by": "name", "value": "Этаж 1"}`, numpy numbers turned into ordinary
ones, automatic ids. Not one of these rules can express what is absent from
the registry, and not one can hide a refusal.
"""

from __future__ import annotations

import inspect
import json
from typing import Any, Iterable

from kir import geometry_values as geometry
from kir import macros, registry_base as _rb, spec
from kir import revit_version as _rv
from kir.compiler import compile_program

__all__ = [
    "OMIT", "DEFAULT", "BY_MACRO", "Ref", "ref", "sel", "transform",
    "Program", "Stack", "program", "builders", "op_names", "geometry",
]


class _Sentinel:
    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return self._name

    def __bool__(self) -> bool:
        return False


#: "The field is not set." Different from None: None is a valid value for
#: some fields, while omission means "let the compiler decide."
OMIT = _Sentinel("OMIT")

#: The selector `{"by": "default"}` — "the document's default type."
DEFAULT = _Sentinel("DEFAULT")

#: The same as OMIT, but at the call site it reads as a statement, not as
#: forgetfulness: `level=sdk.BY_MACRO`.
#:
#: The registry declares `level` mandatory (an op cannot be built without a
#: level), while `macros.py` refuses an op with a level INSIDE
#: `stack.floor` — there, the level is assigned by expansion. The two rules
#: are both correct and do not contradict each other, but at their seam the
#: python signature must let one say "this field will be assigned by the
#: macro." The SDK will not silently discard a supplied level: that would
#: hide a refusal the author would get from the compiler anyway.
BY_MACRO = OMIT


class Ref:
    """A reference to an op in the same program — `{"by": "ref", "value": id}`.

    Returned from `Program.add`, so a link between ops is written in python,
    not as manual string ids: `door = p.add(sdk.create_door(host=wall, ...))`.
    """

    __slots__ = ("id",)

    def __init__(self, id: str) -> None:  # noqa: A002 — the language's field is called id
        self.id = id

    def __repr__(self) -> str:
        return f"Ref({self.id!r})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Ref) and other.id == self.id

    def __hash__(self) -> int:
        return hash(("Ref", self.id))


def ref(x: Any) -> Ref:
    """A reference from anything recognizable: a `Ref`, an id string, an op's dict."""
    if isinstance(x, Ref):
        return x
    if isinstance(x, str):
        return Ref(x)
    if isinstance(x, dict) and isinstance(x.get("id"), str):
        return Ref(x["id"])
    raise TypeError(f"на что ссылка? {x!r}")


def _plain(v: Any) -> Any:
    """numpy/tuple/Ref -> whatever survives json.dumps.

    Without this the connector does not work at all: `np.float64` is not
    serializable, and the whole point is that coordinates are computed by
    numpy. The conversion is duck-typed — numpy is neither imported nor
    required here.
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


#: Parameter kinds that look like a selector in JSON. The classification
#: goes by `ParamSpec.kind`, not by op names — a new op with a selector gets
#: the same convenience silently.
SELECTOR_KINDS = frozenset({"sel", "target", "target_w"})

#: ...and the same thing as a list (`create_dimension.refs`,
#: `move_elements.targets`). `sel_list` (wave/datums) — the plural of kind
#: `sel` (`create_multistory_stairs.levels`): a CATALOG selector as a list,
#: which is why it is here and not in PLAIN_KINDS — otherwise the author
#: would lose the `by=name` convenience exactly where levels are named only
#: by name.
# 🔴 `targets_w` СНЯТ 13.09.2026: ТАКОГО ВИДА В РЕЕСТРЕ НЕТ.
# Найдено пином читателей, когда `sdk.py` был в него внесён: проверка «читатель
# не называет видов, которых в реестре нет» покраснела на `targets_w` и
# `vec3_mm`. Мёртвое имя в классификаторе ничего не ломает и именно поэтому
# опасно: `move_elements.targets` имеет вид `refs_w`, и пока рядом лежало
# похожее имя, любой читающий этот файл мог решить, что вид существует. Живой
# вид (`refs_w`) остаётся. Имя `targets_w` ещё несут `kir/dsl.py:432,476` и
# `kir/project_pack.py:51` — это файлы S, заявка ему оформлена.
SELECTOR_LIST_KINDS = frozenset({"refs_w", "sel_list"})


def unclassified_kinds() -> list[str]:
    """Registry parameter kinds the SDK knows nothing about.

    An unknown kind breaks nothing: it passes through `_plain` as is, and
    the author simply writes the selector as a dict by hand. But if it
    turns out to BE a selector after all, the convenience simply will not
    appear — and silence here is indistinguishable from "that's how it
    should be." So the list is exposed outward and there is a test on it: a
    new parameter kind must be deliberately assigned to one of the groups.
    """
    known = SELECTOR_KINDS | SELECTOR_LIST_KINDS | PLAIN_KINDS
    return sorted({p.kind for o in spec.OPS.values() for p in o.params} - known)


#: Everything else travels in JSON as is (numbers, points, enumerations,
#: nested objects like `arc` and `contour`).
PLAIN_KINDS = frozenset({
    "arc", "bool", "deg", "enum", "fields", "filters", "graph_nodes",
    "graph_segments", "int", "kind_enum", "member_ops", "mm", "num",
    # `wall_layers` (23.08.2026) — the WALL LAYER STACK outside to inside, a
    # list of {width_mm, function, material?}. Plain for the same reason as
    # `mesh` and `surface`: it is one value with an internal invariant (the
    # sum of thicknesses equals `WallType.Width` — checked on 38 out of 38
    # reproducible K1 types), and there is no selector convenience over it:
    # a material inside a layer is addressed by NAME, not a handle, because
    # it resolves in the TARGET document.
    "wall_layers",
    # `identity` (13.09.2026, форма входа опов раздела N, `fc6ef65`) — ОЖИДАЕМАЯ
    # личность элемента у мутирующего опа: `{unique_id, version_guid}` и ничего
    # больше (`kir/authoring_validation.py:1668` отказывает любому другому
    # составу). Plain по той же причине, что `wall_layers` и `mesh`: это ОДНО
    # значение с внутренним инвариантом, и селекторного удобства над ним нет —
    # оба поля берутся ДОСЛОВНО из квитанции создания или `query_element_state`,
    # а не адресуются по имени. Назначение осознанное: `unclassified_kinds()`
    # оставался красным с самого приезда вида (проверено на чистой копии
    # `git archive HEAD` — красный НЕ мой), потому что молчание тут неотличимо
    # от «так и надо».
    "identity",
    # `enum_list` (13.09.2026, `query_level_plan.include`) — множественный выбор
    # из закрытого словаря САМОГО параметра. Plain по той же причине, что
    # `fields` строкой выше: это список ИМЁН, а не адресов, и селекторного
    # удобства над ним нет — `by=name` над «walls» бессмысленно, потому что
    # «walls» не элемент модели, а род следа.
    "enum_list",
    # `surface` (wave/surface, 20.08.2026) — ONE surface value: degrees,
    # knot vectors, a grid of control points, optional weights. Plain for
    # the same reason as `mesh` and `solid_parts`: it is one value with an
    # internal invariant (the number of points = count_u × count_v, the
    # length of the knots = degree + count + 1), and there is no selector
    # convenience over it.
    #
    # 🔴 WITHOUT THIS LINE THE KIND WAS INTRODUCED IN THE REGISTRY AND
    # UNKNOWN TO THE AUTHORED SDK — that is, the op existed, but building it
    # through `dsl` was impossible. The `unclassified_kinds()` guard was
    # written exactly for this, and it went red; the red survived until the
    # night of 20.08, because the surface wave did not see it. A familiar
    # shape: a value's kind lives in SEVERAL places, and it gets introduced
    # in one.
    "surface",
    # `plane` (wave/plane, 21.08.2026) — a profile's coordinate frame:
    # origin, normal, +u direction. Plain for the same reason as `mesh` and
    # `solid_parts`: ONE value with an internal invariant (x_dir ⊥ normal),
    # and there is no selector convenience over it. A "plane from three
    # points" constructor could appear as a separate function — today it
    # does NOT EXIST, and that is named here, not passed over in silence.
    "plane",
    # `solid_parts` (wave/boolean) — a list of primitive operands of a
    # boolean. Plain for the same reason as `mesh`: it is ONE value with an
    # internal invariant, and the SDK cannot offer any convenience over it.
    "solid_parts",
    # `path` (wave/arch) — the open polyline of create_railing. Travels as
    # is, exactly like `pts`: it is geometry as a list of numbers, not a
    # selector, and the SDK cannot offer any convenience over it.
    "path",
    # `path3` (wave/mep-electrical) — the same polyline, but three-dimensional
    # (create_flex_duct / create_flex_pipe). Plain for the same reason.
    "path3",
    # `mesh` (wave/shape) — {vertices_mm, triangles} for create_directshape.
    # Also travels as is: it is ONE value with an internal invariant
    # (indices are meaningful only together with their vertex array), and
    # the SDK has nothing to break it down into conveniences with — the
    # shape's laws live in mesh.py and are checked by the compiler.
    "mesh",
    # `pts_xyz` (wave/site) — a terrain point cloud. Travels as is, exactly
    # like `pts`: geometry as a list of numbers, and the SDK has no
    # convenience to offer over it. `dir_xyz` (21.08.2026) — a DIRECTION,
    # not a point: length means nothing, zero is forbidden, there are no
    # millimeters at all. Travels as is, exactly like a point: the SDK has
    # no convenience to offer over three numbers, and the kind's laws live
    # in authoring_validation and are checked by the compiler.
    "dir_xyz",
    "placements", "pt_view2d", "pt_xy", "pt_xyz", "pts", "pts_list",
    "pts_xyz", "region",
    "slopes",
    # `spiral` (09.08) — {center_mm, radius_mm, start_angle_deg,
    # included_angle_deg, clockwise} for create_stairs. Travels as is,
    # exactly like `arc`: it is ONE value with its own internal law (the
    # radius and the flight width are linked), and the SDK has nothing to
    # break it down into conveniences with — the laws live in
    # authoring_validation and are checked by the compiler.
    "spiral",
    # `vec3_mm` снят там же и по той же причине: вида нет в реестре.
    "str", "str_long", "value",
})


def sel(value: Any, *, kind: str | None = None) -> dict:
    """A selector from a python value.

    A string -> by name, an integer -> by element_id, a `Ref` -> by
    reference, `DEFAULT` -> the document's default type, a ready-made dict
    -> as is. `kind` is needed where the language requires naming the
    element's kind together with its name (`set_param.target`). No
    checking: what is allowed for a given field is known by the compiler,
    and by the compiler alone.
    """
    # 🔴 `_plain` AS THE FIRST LINE, NOT IN THE NEIGHBORING `_coerce` BRANCH
    # (29.08.2026, audit finding F-243). The module's header promises that
    # numpy numbers become ordinary values; `_coerce` kept the promise for
    # NON-selector kinds and bypassed it for selector ones, calling `sel`
    # directly. The difference is visible only from the inside: `np.float64`
    # is a subclass of `float` and passed through BY ACCIDENT, while
    # `np.int64` is NOT a subclass of `int` and produced
    # `TypeError: not a selector`. A promise kept for one kind out of two is
    # worse than one never given: an author who took an id from a numpy
    # array cannot tell the two apart. Fixed here, not in `_coerce`: `sel`
    # is the module's PUBLIC name, and a fix in `_coerce` would have cured
    # the builders while leaving a direct call sick. And not through
    # `isinstance(v, np.integer)` — that would introduce a mandatory
    # dependency on numpy into the language, while `_plain` is already
    # duck-typed.
    value = _plain(value)
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
    """`stack.transform` — plan interpolation from the bottom to the top.

    The fields are named, because there are four of them and all are
    optional; they are checked by `macros._validate_transform`, not by this
    function.
    """
    got = {"scale_xy_top": scale_xy_top, "twist_deg_total": twist_deg_total,
           "offset_mm_top": offset_mm_top, "pivot_mm": pivot_mm}
    return {k: _plain(v) for k, v in got.items() if v is not OMIT}


# ─────────────────────────────────────────── builders born from the registry

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
    """A builder function from an op's spec. The one and only place where
    KIR python signatures appear at all."""
    P = inspect.Parameter
    params = [P(p.name, P.POSITIONAL_OR_KEYWORD) for p in ospec.params if p.required]
    # 🔴 THE REGISTRY'S DEFAULT IS SHOWN, BUT NOT WRITTEN IN (02.09.2026).
    # This used to say `default=p.default`, and `apply_defaults()` wrote the
    # value into the op BEFORE the compiler. Measured: `sdk.create_wall(...)`
    # without `height_mm` produced `FieldOrigin.EXPLICIT`, the same omission
    # via raw JSON — `REGISTRY_DEFAULT`. One and the same authorial intent,
    # a different provenance — DEPENDING ON THE DOOR; and a written-in
    # default additionally changes `plan_digest`, that is, the identity of
    # the program's proof. The scripted door (`dsl.py`) held this law with a
    # sentinel class since 03.08; now there is one shared carrier
    # (`registry_base.RegistryDefault`).
    params += [P(p.name, P.KEYWORD_ONLY,
                 default=(OMIT if p.default is None
                          else _rb.RegistryDefault(p.default)))
               for p in ospec.params if not p.required]
    # `id` is not a registry parameter, but every op accepts it: it is the
    # address by which neighbors refer to the op. If omitted, Program will
    # assign one.
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
            if value is OMIT or _rb.is_registry_default(value):
                continue
            out[name] = _coerce(by_name[name], value)
        return out

    builder.__name__ = ospec.name
    builder.__qualname__ = ospec.name
    builder.__signature__ = sig
    builder.__doc__ = _doc_for(ospec)
    builder.op_spec = ospec
    return builder


#: All builders, by op name. Assembled at import time from `spec.OPS` — and
#: so there are always exactly as many of them as there are ops in the
#: registry.
BUILDERS: dict[str, Any] = {name: _make_builder(ospec)
                            for name, ospec in sorted(spec.OPS.items())}
globals().update(BUILDERS)
__all__ += sorted(BUILDERS)


def builders() -> dict[str, Any]:
    """A copy of the builder table — for introspection and tests."""
    return dict(BUILDERS)


def op_names(*, writes: bool | None = None) -> list[str]:
    """The registry's op names; `writes=True` — only the ones that write to the model."""
    return sorted(n for n, o in spec.OPS.items()
                  if writes is None or o.writes_model is writes)


# ──────────────────────────────────────────────────────────────── program

class _OpSink:
    """The common part of a program and a stack floor: the list of ops and id issuance."""

    def __init__(self) -> None:
        self.ops: list[dict] = []
        self._seq: dict[str, int] = {}
        #: ALL ids already taken in this list — both explicit ones and ones
        #: issued by the counter. There is one counter per op kind, but the
        #: program's namespace is ONE (F-242): without this set an explicit
        #: `wall1` and an auto-`wall1` collided, and the compiler found out
        #: about it, not the author.
        self.used_ids: set[str] = set()

    def _next_id(self, op_name: str) -> str:
        n = self._seq.get(op_name, 0) + 1
        self._seq[op_name] = n
        return f"{op_name[7:] if op_name.startswith('create_') else op_name}{n}"

    def add(self, *ops: dict) -> Any:
        """Add ops, filling in missing ids. Returns a `Ref` (or a list of
        them), so a neighboring op refers to it via python, not a string."""
        made: list[Ref] = []
        for op in ops:
            if not isinstance(op, dict) or "op" not in op:
                raise TypeError(f"это не оп: {op!r}")
            oid = op.get("id")
            if not oid:
                # id right after `op`: a program is read by eye more often than by a parser.
                rest = {k: v for k, v in op.items() if k != "op"}
                oid = self._next_id(op["op"])
                op = {"op": op["op"], "id": oid, **rest}
            # 🔴 EVERY id IS CHECKED, NOT ONLY THE EXPLICIT ONE. Otherwise
            # the other half of the same collision would remain: an
            # auto-`wall1` FIRST, an explicit `wall1` SECOND — the order
            # reversed, the defect the same (F-242).
            _exactly_unused_id(oid, self.used_ids, "id")
            self.ops.append(op)
            made.append(Ref(op["id"]))
        return made[0] if len(made) == 1 else made

    def __len__(self) -> int:
        return len(self.ops)

    def __iter__(self):
        return iter(self.ops)


class Stack(_OpSink):
    """A typical floor of the `stack` macro, assembled as a context.

    Ops inside do NOT get a `level` — it is assigned by expansion, and
    `macros.py` refuses if it is set by hand. This is why the floor is kept
    separate from the program as its own object: an op with a level cannot
    be added to it by accident.
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


def _exactly_bool(value: Any, field: str) -> bool:
    """`True`/`False` and nothing else. Otherwise — a named refusal.

    🔴 IT USED TO SAY `bool(value)`, AND THAT ENABLED DEMOLITION WITH THE
    WORD "NO" (29.08.2026, audit finding F-239). `bool("false")` in python
    is TRUE — every non-empty string is truthy. That is, an author who
    wrote `allow_destructive="false"` got a program in which demolition WAS
    ALLOWED: the very word they used to forbid it turned it on.

    This is the easiest place of all to get it wrong: the envelope is
    written by hand, by a template, and from YAML/JSON, where "false"
    arrives as a string all the time. And the price of the mistake is an
    irreversible deletion in someone else's model.

    A refusal, not a coercion: "a string instead of a boolean" has no
    correct reading. Treating `"false"` as false would mean setting up a
    truth vocabulary of our own alongside python's, and the next string
    ("no", "0", "нет") would ask where it ends.
    """
    if value is True or value is False:
        return value
    raise TypeError(
        f"{field}: ожидается True или False, получено {value!r} "
        f"({type(value).__name__}). Приведения здесь НЕТ намеренно: "
        f"bool({value!r}) в питоне даёт "
        f"{bool(value)!r}, и строка «false» РАЗРЕШИЛА БЫ снос")


def _exactly_int(value: Any, field: str) -> int:
    """An integer and nothing else. Not `bool`, not a fraction, not a string.

    🔴 IT USED TO SAY `int(value)`, AND THAT BUILT THE WRONG BUILDING
    SILENTLY (29.08.2026, audit finding F-240). `int(2.5)` = 2,
    `int("3")` = 3, `int(True)` = 1 — and an author who asked for 2.5
    floors got two, learning nothing about it. The compiler DOES have an
    integer contract; the SDK intercepted its refusal with a coercion and
    handed back a program that is valid and wrong.

    `bool` is rejected by a separate line, because in python it is a
    SUBCLASS of `int`: `isinstance(True, int)` is true, and without this
    line `levels=True` would have built one floor.
    """
    if isinstance(value, bool):
        raise TypeError(
            f"{field}: ожидается целое, получено {value!r} (bool). "
            f"В питоне bool — подкласс int, и {value!r} молча стало бы "
            f"{int(value)}")
    if isinstance(value, int):
        return value
    raise TypeError(
        f"{field}: ожидается целое, получено {value!r} "
        f"({type(value).__name__}). Приведения здесь НЕТ намеренно: "
        f"int({value!r}) дало бы {_int_would_be(value)}, и здание вышло бы "
        f"НЕ ТЕМ, о котором просил автор")


def _exactly_unused_id(oid: str, used: set[str], field: str) -> str:
    """An id that this program does NOT YET HAVE. Otherwise — a named refusal.

    🔴 IT USED TO BE: an author's explicit id did not move or reserve the
    auto-id counter (29.08.2026, audit finding F-242). `create_wall(id='wall1')`
    plus a following `create_wall()` with no id gave BOTH `wall1` — and
    `wall1` is exactly the most natural name an author would write first.
    The refusal arrived later, from the compiler (`KIR-P006`), and pointed
    at the SECOND op, the one the author did not give an id to: the next
    move suggested by the refusal ("give THIS op a different id") was one
    the author could not carry out.

    A refusal, not "skip past what's taken": skipping past would have to be
    explained to an author who was counting walls by name, and they would
    get `wall3` where they expected `wall2`. Silently shifted numbering is
    the same substitution as `bool("false")`.

    A smart counter is no good here either: for `wall1` to move the
    `create_wall` counter, you would have to parse the NAME and derive the
    family from it, and that is a dictionary — `north-wall` is "wall" too,
    `wall1_копия` is not. One checkable property ("the id is not taken") is
    cheaper and complete.
    """
    if oid in used:
        raise ValueError(
            f"{field}: id {oid!r} уже занят в этой программе. Явный id и "
            f"авто-id делят ОДНО пространство имён: авто-счётчик выдаёт "
            f"{oid!r} по порядку и о вашем имени не знает. СЛЕДУЮЩИЙ ХОД: "
            f"назовите явный id иначе (например {oid}_0) либо не пишите его "
            f"вовсе")
    used.add(oid)
    return oid


def _int_would_be(value: Any) -> str:
    try:
        return repr(int(value))
    except Exception:                             # noqa: BLE001
        return "отказ"


class Program(_OpSink):
    """One KIR program: envelope, ops, compilation.

    A program is a unit, not the whole building: the limits are held by
    `compiler.MAX_OPS_PER_PROGRAM` (authored ops before expansion) and
    `MAX_VALIDATED_OPS` (after macros). 🔴 THE NUMBERS WERE REMOVED FROM
    HERE ON 20.08.2026: this used to say "20 and 320" against live values
    of 1000 and 22000 — an error of 50x and 69x. The name is exactly the
    address at which the value is asked for; repeating it next to the name
    means starting a second carrier, which drifts apart silently, so a
    tower is a BUNDLE of programs, just as in a live turn. This is visible
    here, not hidden: the counters are exposed outward, so the script can
    decide for itself when to open the next one.
    """

    def __init__(self, *, intent: str | None = None,
                 defaults: dict | None = None,
                 allow_destructive: bool | None = None,
                 lineage: str | None = None) -> None:
        super().__init__()
        self.intent = intent
        self.defaults = defaults
        self.allow_destructive = allow_destructive
        self.lineage = lineage

    def __enter__(self) -> "Program":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def add_geometry(self, value: Any, *, category: str, name: str,
                     id: str | None = None) -> Ref:  # noqa: A002
        """Materialize a geometry value through its existing KIR op.

        This is only a short authoring shorthand for the LLM. The choice of
        operation is made by the value's type, while its signature,
        validation, and witness are still determined by the
        registry/compiler. An unknown object is refused here, not turned
        into a DirectShape by default.
        """
        materialize = getattr(value, "materialize", None)
        if not callable(materialize):
            raise TypeError(
                "add_geometry ожидает sdk.geometry value с materialize()")
        return self.add(materialize(category=category, name=name, id=id))

    # ── macros ──────────────────────────────────────────────────────────
    def stack(self, *, levels: int, h_mm: Any = OMIT, base_elev_mm: Any = OMIT,
              name_prefix: Any = OMIT, transform: Any = OMIT,
              floor: Iterable[dict] | None = None, id: str | None = None
              ) -> Stack:
        """`stack` — a typical floor, repeated over height with plan interpolation.

        The fields are listed explicitly, because macros live not in
        `spec.OPS` but in `macros.py`; the same module checks them. A guard
        test runs the full set of fields through `macros.expand` — if the
        macro renames a field, the guard fails.
        """
        macro: dict[str, Any] = {"op": "stack",
                                 "levels": _exactly_int(levels, "levels")}
        # THE THIRD AND FOURTH SITES OF THE SAME COLLISION (F-242):
        # macro-builders write into `self.ops` BYPASSING `add`, and without
        # this line `stack(id="stack1")` plus `stack()` produced two
        # `stack1`s. Verified by execution before the fix.
        macro["id"] = _exactly_unused_id(id or self._next_id("stack"),
                                         self.used_ids, "id")
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
        """`grid_array` — a rectangular grid of axes."""
        macro: dict[str, Any] = {"op": "grid_array"}
        macro["id"] = _exactly_unused_id(id or self._next_id("grid_array"),
                                         self.used_ids, "id")
        for key, value in (("nx", nx), ("ny", ny), ("dx_mm", dx_mm),
                           ("dy_mm", dy_mm), ("origin_mm", origin_mm),
                           ("margin_mm", margin_mm), ("prefix_x", prefix_x),
                           ("prefix_y", prefix_y)):
            if value is not OMIT:
                macro[key] = _plain(value)
        self.ops.append(macro)
        return Ref(macro["id"])

    # ── output ───────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        """Exactly the JSON that the compiler and the bridge accept."""
        out: dict[str, Any] = {"ir_version": spec.IR_VERSION}
        if self.intent is not None:
            out["intent"] = self.intent
        if self.lineage is not None:
            # Invalid supplied values reach the compiler unchanged; no new validator.
            out["lineage"] = self.lineage
        if self.defaults is not None:
            out["defaults"] = {k: sel(v) for k, v in self.defaults.items()}
        if self.allow_destructive is not None:
            out["allow_destructive"] = _exactly_bool(
                self.allow_destructive, "allow_destructive")
        out["ops"] = list(self.ops)
        return out

    def to_json(self, **kw: Any) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kw)

    def compile(self, *, version: str = _rv.DEFAULT_VERSION,
                snapshot: Any = None, **kw: Any):
        """An offline compilation. No network, no Revit, diagnostics are
        returned as is — as `Diagnostic` python objects, not text: a script
        that repairs itself must read `code` and `candidates`, not parse a
        message.

        The default was `"2023"` until 13.08.2026 — the house's FOURTH
        answer to "the version was not stated," different from
        `compile_program`'s "2026" one floor below. One and the same
        question, two answers, one layer between them. Now both take
        `revit_version.DEFAULT_VERSION`.

        Version-dependent programs make up 12 out of 69 in the golden
        corpus, so choosing one version here is a decision, not a
        formality: if an answer is needed across all six, call
        `compile_all` — that is exactly what it is for."""
        return compile_program(self.to_dict(), revit_version=version,
                               snapshot=snapshot, **kw)

    def compile_all(self, *, versions: Iterable[str] = spec.REVIT_VERSIONS,
                    snapshot: Any = None, **kw: Any) -> dict[str, Any]:
        """All six Revit versions at once — per-version emission (SPEC
        11.2), and "it compiled" without a named version means nothing."""
        return {v: self.compile(version=v, snapshot=snapshot, **kw)
                for v in versions}

    # ── counters ─────────────────────────────────────────────────────────
    def expanded(self) -> list[dict]:
        """Ops after macro expansion — what the compiler will actually see.

        🔴 IT USED TO SAY `except Exception: return list(self.ops)`, AND
        THAT SUBSTITUTED THE UNEXPANDED INPUT EXACTLY WHERE `stats()` COUNTS
        "WHAT WILL ACTUALLY BE BUILT" (29.08.2026, audit finding F-241).
        `program().stack(levels=0)` printed
        `{'ops_written': 1, 'ops_expanded': 1, 'elements': 0}` — a set of
        numbers from which an author would conclude "the macro produced
        nothing," even though the macro REFUSED: `KIR-M001: stack.levels=0
        exceeds the MAX_STACK_LEVELS=40 ceiling`.

        The argument that stood here ("a macro that will refuse in the
        compiler too") is exactly half right: the compiler will refuse
        LATER, while the author gets the numbers NOW. And the docstring
        promised "what the compiler will actually see" — the one thing the
        substitution did not deliver.

        An error mark in the dict of numbers would have been the same
        trouble: a reader of `stats()` takes the three promised keys and
        does not look at a fourth — a silent VALUE instead of a silent
        refusal.
        """
        return macros.expand(list(self.ops))

    def stats(self) -> dict[str, int]:
        """`ops_written` — how many ops were written; `ops_expanded` — how
        many they expanded into; `elements` — how many elements will land
        in the model.

        Three numbers, not one: a single one would dissolve exactly what
        the language is for — the ability to say much with little.
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
            allow_destructive: bool | None = None,
            lineage: str | None = None) -> Program:
    """A new program; optional lineage is a stable address, not overwrite permission.

    None omits lineage. Other values are passed unchanged to compiler validation.
    """
    return Program(intent=intent, defaults=defaults,
                   allow_destructive=allow_destructive, lineage=lineage)
