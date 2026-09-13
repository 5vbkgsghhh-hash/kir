"""THE SHAPE-CAPABILITY CENSUS: what geometry an op can accept, and where its boundary lies.

    PYTHONPATH=. venv/bin/python -m kir.course.shape

WHY THIS FILE EXISTS. On 20.08.2026 the question "can ``create_roof``
express a footprint with a hole" was settled by a live probe in someone
else's Revit and half an hour of corpus census work. The neighbouring
census — `expressiveness` — did not ask that question and CANNOT ask it: its
unit is the KIND OF VALUE, while the question was about SHAPE CAPABILITY.
The axes differ, and the second one is exactly the one the project exists
for: the measure of all the work is how much MORE COMPLEX a building the
model is able to describe. There is no second carrier here: over there it is
"how the author obtains a value", here it is "what geometry an op accepts
and what it does not".

THIS LIST IS OF TWO DIFFERENT KINDS, AND THEY MUST NOT BE MIXED:

  1. THE CAPABILITY AXIS — **COMPLETE BY CONSTRUCTION.** Membership is taken
     from `spec.OPS`: ALL operations and ALL their parameters are iterated.
     A missing row means "no such shape operand exists in the language", not
     "we don't know". A new parameter kind in the registry, if not sorted
     into a carrier below, fails the census with a refusal — it cannot come
     into being silently.

  2. THE BOUNDARY AXIS — **CLOSED, BUT NOT COMPLETE.** The boundary is drawn
     from two authorities: the witness's named absences
     (`translation_cert._NON_WITNESSABLE_CLAUSES`) and lift-side refusals
     (`_refuse(...)` in `lift.py`). The second source is visible only to the
     extent that a refusal ITSELF names the op in its text: as of this
     writing, 113 of 130 refusals do not name an op, and the census must
     print that number, not hide it. So the absence of a boundary for an op
     means "we did not find it", NOT "it does not exist".

🔴 THERE IS NOT ONE OPERATION NAME IN HERE. This is not a style choice, it
is a validity condition: a hand-written table drifts from the registry —
every hand-written list in this tree has drifted, and not one generated one
has. `kir/tests/test_shape_census.py` guards this by execution: it reads
this file's OWN SOURCE and turns red if an op's name has crept into it. An
instrument that prints "one ring" because the author wrote in a name is not
an instrument.
"""
from __future__ import annotations

import ast
import re
import functools
import inspect

from kir import contour, spec, translation_cert

#: SHAPE CARRIER -> registry parameter kinds that carry it.
#: ALL kinds from `spec.PARAM_KINDS` are sorted in; an unrecognized kind is a
#: refusal, see `unclassified_kinds()`. Key `None` — kinds that carry no shape at all.
CARRIERS: dict[str | None, tuple[str, ...]] = {
    "кольцо": ("pts",),
    "кольца": ("pts_list",),
    "область": ("region",),
    "путь": ("path", "path3"),
    "точка": ("pt_xy", "pt_xyz", "pt_view2d"),
    "облако точек": ("pts_xyz",),
    "меш": ("mesh",),
    # 20.08: a SMOOTH `поверхность` (surface) is its own carrier, not a kind
    # of `меш` (mesh). A mesh carries FACETS and closes volume with
    # triangles; a surface carries a grid of CONTROL points with degrees and
    # knots, does not close rings and does not take part in ring capacity.
    # Merging them into one carrier would tell the census they share one law
    # and one witness — but they have different ones.
    "поверхность": ("surface",),
    "правка кривой": ("arc", "spiral", "slopes"),
    # ── 21.08.2026: THREE CARRIERS, AND ALL THREE WERE LATE ─────────────
    #
    # 🔴 THEY WERE LATE NOT BECAUSE THEY WERE FORGOTTEN, BUT BECAUSE THERE
    # WAS NO ONE TO ASK. Op membership here is derived from the registry and
    # cannot be missed — but kind membership is maintained by this very
    # hand, and three waves in a row brought in a kind and never looked in
    # here: `solid_parts` (20.08), `plane` (21.08), `dir_xyz` (21.08). The
    # census honestly turned red for each one, and each time it turned red
    # AFTER the wave, not during it. See the fork's report: the same miss
    # repeated across five registries at once.
    #
    # WHY EACH IS ITS OWN CARRIER, NOT `None`. The `None` key means "carries
    # no shape AT ALL", and that is where `mm`, `deg`, `enum` live — amounts
    # and words. All three below carry a STRUCTURAL geometric operand, and
    # there is a precedent right next to them: `pt_xyz` — also three numbers
    # — is carrier `точка` (point), not `None`. Hiding them in `None` would
    # mean the census answering "what geometry does an op accept" stays
    # silent about the geometry the op accepts.
    #
    # None of the three closes a ring, so they are absent from `_CLOSED` and
    # do not change ring capacity.
    #
    # `тела-операнды` (SOLID OPERANDS): a box/sphere/cylinder/prism by
    # numbers. This is a SHAPE, and moreover the only shape of its
    # operation; alongside `меш` and `поверхность`, and NOT in place of
    # them — a mesh has facets, a surface has smoothness, here there are
    # primitives that are born and die within one op.
    "тела-операнды": ("solid_parts",),
    # `плоскость отсчёта` (REFERENCE PLANE): origin, normal, +u direction.
    # Carries no shape of its own and yet CHANGES geometry — it decides
    # WHERE a contour's (u, v) lie. It is exactly what made 73 family shapes
    # out of 283 expressible that used to be rejected by the
    # `sketch_plane_not_horizontal` code: a window's shape lies on a wall
    # face, and a planar extrusion cannot say that.
    "плоскость отсчёта": ("plane",),
    # `направление` (DIRECTION): a ray. Length means nothing, zero is
    # forbidden, there are no millimetres. It is used to pick a carrier's
    # face and, with the same value, to set a profile's reference along a
    # path.
    "направление": ("dir_xyz",),
    "места посадки": ("placements",),
    "граф": ("graph_nodes", "graph_segments"),
    # 🔴 `wall_layers` WAS SORTED HERE ON 24.08.2026, AND THIS IS A
    # DECISION, NOT AN OVERSIGHT. The kind arrived on 23.08 with
    # `create_wall_type` and failed the census for a day — exactly the
    # refusal the axis was declared complete-by-construction for.
    #
    # The reasoning. This file's axis is WHAT GEOMETRY AN OP ACCEPTS:
    # rings, points, a reference plane, a direction, solid operands, a
    # graph. A layer stack-up carries none of these: it is a LIST OF
    # THICKNESSES with a function and a material, that is, a plural of kind
    # `mm`, which sits in that same bucket. It closes no ring, names no
    # point; a wall's axis line is set by `create_wall`, and the type only
    # decides how thick it is.
    #
    # WHAT THIS ENTRY DOES NOT CLAIM: that layer thickness is not geometry
    # AT ALL. In `create_wall_type`'s postcondition it sits exactly on the
    # geometry axis and is re-read layer by layer. The axes differ: over
    # there — "what the witness must measure", here — "what shape the
    # author is able to DRAW".
    # `identity` — НОСИТЕЛЬ ЗДЕСЬ ЕСТЬ, И ОН НЕ ФОРМА (13.09.2026). Пара
    # {unique_id, version_guid} — это КВИТАНЦИЯ ЧТЕНИЯ: она говорит, ЧТО автор
    # видел перед тем, как решил писать. Она не число и не ссылка на элемент
    # документа: сослаться на элемент — дело `target`/`sel`, а это утверждение
    # о ПРОШЛОМ состоянии того же элемента. Кольца не замыкает, точки не
    # называет, нарисовать по ней нечего — поэтому носителя формы у неё нет.
    # `enum_list` — НОСИТЕЛЯ ФОРМЫ НЕТ, по той же причине, что у `enum` и
    # `fields` рядом (13.09.2026). Это множественный ВЫБОР из закрытого словаря
    # («какие рода следов включить»): ни точки, ни кольца, ни ссылки на элемент —
    # рисовать по нему нечего. Что он ОТБИРАЕТ формы у других — не делает его
    # формой, как `filters` не становится геометрией от того, что сужает выборку.
    None: ("bool", "deg", "enum", "enum_list", "fields", "filters", "identity",
           "int", "kind_enum",
           "member_ops", "mm", "num", "refs_w", "sel", "sel_list", "str",
           "str_long", "target", "target_w", "value", "wall_layers"),
}

#: Carriers that DO close a ring. Ring capacity is counted only by these.
_CLOSED = ("кольцо", "кольца", "область")

ONE_RING = "одно кольцо"
RING_AND_HOLES = "внешнее + дыры"
NOT_A_SKETCH = "форма не кольцевая"


def _kind_to_carrier() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for carrier, kinds in CARRIERS.items():
        for kind in kinds:
            out[kind] = carrier
    return out


def unclassified_kinds() -> list[str]:
    """Registry kinds not sorted into carriers. THERE MUST BE NONE."""
    return sorted(set(spec.PARAM_KINDS) - set(_kind_to_carrier()))


def stray_kinds() -> list[str]:
    """Kinds sorted in here that the registry does not know."""
    return sorted(set(_kind_to_carrier()) - set(spec.PARAM_KINDS))


def operands() -> dict[str, tuple[tuple[str, str, str, bool], ...]]:
    """OP -> ((parameter, kind, carrier, required), ...) across all registry ops.

    Complete by construction: `spec.OPS` is iterated in full, so an op with
    no shape operands is legitimately absent here, not by oversight.
    """
    missing = unclassified_kinds()
    if missing:
        raise ValueError(
            "род параметра не разнесён по носителям формы: "
            + ", ".join(missing)
            + ". Пока он не разнесён, перепись НЕ ЗНАЕТ, форма это или нет, и "
              "молчать об этом значит выдать незнание за отсутствие")
    table = _kind_to_carrier()
    out: dict[str, tuple[tuple[str, str, str, bool], ...]] = {}
    for name, op in spec.OPS.items():
        rows = tuple(
            (p.name, p.kind, table[p.kind], bool(p.required))
            for p in op.params if table[p.kind] is not None)
        if rows:
            out[name] = rows
    return out


def ring_capacity() -> dict[str, str]:
    """OP -> how many rings it accepts. Derived from carriers, not declared."""
    out: dict[str, str] = {}
    for name, rows in operands().items():
        carriers = {carrier for _, _, carrier, _ in rows}
        if "область" in carriers or {"кольцо", "кольца"} <= carriers:
            out[name] = RING_AND_HOLES
        elif "кольцо" in carriers or "кольца" in carriers:
            out[name] = ONE_RING
        else:
            out[name] = NOT_A_SKETCH
    return out


@functools.lru_cache(maxsize=1)
def _lift_refusals() -> tuple[dict[str, tuple[tuple[str, str], ...]], int, int]:
    """Lift-side refusals that THEMSELVES name an op. Plus the denominator of silence."""
    from kir.decompile import lift

    source = inspect.getsource(lift)
    tree = ast.parse(source)
    names = set(spec.OPS)
    found: dict[str, set[tuple[str, str]]] = {}
    total = silent = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (getattr(func, "id", None) or getattr(func, "attr", None)) != "_refuse":
            continue
        total += 1
        reason = ""
        texts: list[str] = []
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.Attribute):
                reason = arg.attr
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                texts.append(arg.value)
            elif isinstance(arg, ast.JoinedStr):
                texts.append("".join(
                    v.value for v in arg.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)))
        hit = False
        for text in texts:
            for op in names:
                # 🔴 A NAME BOUNDARY, NOT A SUBSTRING (F-341, 29.08.2026).
                # Registry names are NESTED inside one another: `create_room`
                # ⊂ `create_room_separator`, `create_wall` ⊂
                # `create_wall_foundation`. A substring match attributed a
                # refusal about a ROOM SEPARATOR to `create_room`, and a
                # refusal about a strip foundation to `create_wall`.
                # Measurement before the fix: 3 false attributions out of 36
                # ops, and for `create_room` BOTH rows that came from here
                # were false.
                #
                # The cost lies in what the census declares itself to be:
                # "boundary axis: CLOSED, BUT NOT COMPLETE" — that is, a
                # derived piece of evidence the reader must trust, printed
                # to the author with a ⛔ mark. A missing entry and an entry
                # that is ENTIRELY SOMEONE ELSE'S are not the same thing:
                # the first reads as "no boundaries declared", the second as
                # "here are the boundaries".
                #
                # `(?<!\w)…(?!\w)`, not `\b`. 🔴 SAYING IT PLAINLY: for THIS
                # registry's names, `\b` would give the same result —
                # verified by measurement, all checks stay green. `_` is a
                # word character, so the word boundary between `create_room`
                # and `create_room_separator` does not fire there either,
                # and `\b` tells them apart too. The stricter form was taken
                # for one reason: `\b` depends on whether the name's OUTER
                # character is a word character — on a name starting or
                # ending in a non-letter, it would silently change meaning.
                # No registry name is affected by this today, so the payoff
                # here is ZERO; this is written down so the next person does
                # not go looking for a measurement that does not exist.
                if re.search(rf"(?<!\w){re.escape(op)}(?!\w)", text):
                    found.setdefault(op, set()).add((reason, " ".join(text.split())))
                    hit = True
        if not hit:
            silent += 1
    return ({k: tuple(sorted(v)) for k, v in found.items()}, total, silent)


def declared_boundaries() -> dict[str, tuple[tuple[str, str], ...]]:
    """OP -> ((source, what exactly), ...). CLOSED, BUT NOT COMPLETE — see the module docstring."""
    out: dict[str, list[tuple[str, str]]] = {}
    for op, clauses in translation_cert._NON_WITNESSABLE_CLAUSES.items():
        for clause, why in clauses:
            out.setdefault(op, []).append(
                ("свидетель молчит", f"{clause}: {' '.join(why.split())}"))
    refusals, _, _ = _lift_refusals()
    for op, rows in refusals.items():
        for reason, text in rows:
            out.setdefault(op, []).append((f"обратный ход {reason}", text))
    return {k: tuple(v) for k, v in sorted(out.items())}


def tally() -> dict[str, int]:
    caps = ring_capacity()
    out = {ONE_RING: 0, RING_AND_HOLES: 0, NOT_A_SKETCH: 0}
    for value in caps.values():
        out[value] += 1
    return out


def text() -> str:
    ops = operands()
    caps = ring_capacity()
    bounds = declared_boundaries()
    _, total, silent = _lift_refusals()
    lines = [
        "ПЕРЕПИСЬ СПОСОБНОСТЕЙ ФОРМЫ — оп -> какую геометрию принимает",
        f"ось способности: ПОЛНАЯ ПО ПОСТРОЕНИЮ (авторитет: spec.OPS, "
        f"{len(spec.OPS)} операций, из них с формой {len(ops)})",
        f"ось границы: ЗАКРЫТАЯ, НО НЕ ПОЛНАЯ (отказов обратного хода {total}, "
        f"из них оп НЕ НАЗЫВАЮТ {silent} — эта часть переписи НЕ ВИДНА)",
        f"формы одного кольца: {', '.join(sorted(contour.SHAPE_FORMS))}",
        "",
    ]
    for capacity in (ONE_RING, RING_AND_HOLES, NOT_A_SKETCH):
        rows = sorted(k for k, v in caps.items() if v == capacity)
        lines.append(f"{capacity} ({len(rows)}):")
        for name in rows:
            carried = ", ".join(
                f"{param}:{carrier}" + ("" if required else "?")
                for param, _, carrier, required in ops[name])
            lines.append(f"    {name:28s} {carried}")
            for origin, what in bounds.get(name, ()):
                lines.append(f"    {'':28s} ⛔ [{origin}] {what[:96]}")
        lines.append("")
    counts = tally()
    lines.append("ИТОГО " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
    lines.append(f"опов с ОБЪЯВЛЕННОЙ границей: {len(bounds)}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    print(text())
