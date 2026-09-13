"""THE EXPRESSIBILITY CENSUS: what the author CAN say in Python, and what they CANNOT.

    PYTHONPATH=. venv/bin/python -m kir.course.expressiveness

WHY THIS FILE EXISTS. Owner's directive of 19.08.2026: "Python
expressiveness must be brought to the maximum of its capability and closed,
so we never come back to it again." "Closed" here carries this tree's strict
meaning: closed = verified by a control that TURNS RED. So what is needed is
not a list of what was done, but a CENSUS OF THE SUBJECT — and it must
declare its own kind.

THIS LIST'S KIND: **COMPLETE BY CONSTRUCTION.**
Membership is taken from an authority and cannot be missed: rows are set up
from `spec.PARAM_KINDS` — the registry's closed list of parameter kinds (38
as of 21.08.2026; it was 34 on the day this was recorded, 19.08). Ask the
authority yourself: `python -c "from kir import spec;
print(sorted(spec.PARAM_KINDS))"`. So the ABSENCE of a row means "no such
kind exists in the language", not "we don't know" — and a new kind in the
registry must turn `kir/tests/test_expressiveness_census.py` red, not come
into being silently.

WHY THE CENSUS UNIT IS A PARAMETER KIND, NOT AN OPERATION. All 71 of 71
operations are expressible, and WITHOUT any census at all: the `dsl` surface
is generated from `spec.OPS` by a factory, a new op becomes a function at
that same moment. Asking "is the operation expressible" is meaningless —
the answer is guaranteed by construction. The real question is different:
can the author OBTAIN THE VALUE the operation requires. A building does not
fail on op names, but on having nothing to specify a complex shape's slab
with. So the census runs over VALUE KINDS.

FOUR OUTCOMES, AND THEY DIFFER IN MEANING — one word for four different
troubles is not a measurement:

    NATIVE       Python builds the value itself: a number, a string, a list
                 of points. A constructor here would be harmful — an extra
                 name over `[x, y]`.
    CONSTRUCTOR  the value is structural, and there is a NAMED builder.
    LITERAL      the value is structural, written as a dict, and the dict's
                 shape is printed by help. This is NOT a hole: the shape is
                 derived from the registry (`spec(<op>)`), so it cannot go
                 stale.
    GAP          cannot be said. The CEILING's REASON and OWNER must be
                 named — whose file will have to be edited to close it.

🔴 EVERY ROW DECLARES ITS METHOD OF VERIFICATION, and this is not
decoration. `by execution` means a script that built a value of that kind
was run through a REAL sandbox; `by reading` means the conclusion was drawn
by reading the registry and was NOT confirmed by a run. Mixing them up
would mean passing off something read for something measured — a named
defect of this tree. ALL 38 kinds are verified by execution: every outcome
is backed by a script that went through a real sandbox under prod policy.
The last four (`surface`, `solid_parts`, `plane`, `dir_xyz`) were added in
the 20-21.08 waves, and 🔴 TWO OF THE FOUR STOOD WITHOUT A ROW —
`solid_parts` for two days. The census was honestly RED that whole time and
read by no one: completeness by construction protects against silence, but
not against an unread red. So "GAP 0" is a MEASUREMENT, not a claim; before
the recheck, 16 rows stood as `by reading`, and declaring an absence of
holes from them would have been a lie in the direction of "we covered
everything".

WHAT WAS CLOSED ON 19.08.2026, AND WHAT IT USED TO BE:

    mesh        before: the author wrote out a box by hand with 8 vertices
                and 12 index triples; a building made of shapes was not
                written at all
                after: `extrude(contour, height)` — the same mesh, zero
                lines of manual triangulation, and it CANNOT hand back a
                mesh the compiler would reject
    region      before: the author HAD planar booleans (shapely was live),
                but had nowhere to put the result — coordinates were
                rewritten by hand, holes got lost
                after: `region(polygon)` — the same figure becomes a REAL
                slab with a type and a row in the specification, not
                "geometry"
    member_ops  before: `create_group` could not be built from Python AT ALL
                (`KIR-B008: a value of type Handle`), that is, the
                language's main multiplier was available only to a
                hand-written `program`
                after: handles are legitimate members, an op is LIFTED OUT
                of the program into members. Measured: 353 characters of
                script -> 160 elements, 2.2 characters per element against
                24.5 for the marathon building
"""
from __future__ import annotations

from typing import Any

from kir import spec
# 🔴 CENSUS CEILINGS ARE COMPUTED, NOT TYPED IN BY HAND (F-316, 29.08.2026).
# The census declares itself a MEASUREMENT ("by execution" = a script run
# through a real sandbox), yet two of its ceilings were typed in by hand and
# drifted from the validator: `plane` — by A FACTOR OF 200, `wall_layers` —
# by two functions. The number 500,000 was not simply stale: the limit was
# raised by a MEASUREMENT IN LIVE REVIT (`plane.py:104-140`, a volume drift
# of 2.34e-04 mm3 per 100 km), while the census kept teaching the old one.
# Both modules are lightweight, there is no cycle: neither `plane` nor
# `registry_base` know about the course.
from kir import plane as _plane
from kir import registry_base as _rb
from kir.geom import MAX_HOLES, MAX_RING_POINTS, MIN_RING_POINTS

NATIVE = "NATIVE"
CONSTRUCTOR = "CONSTRUCTOR"
LITERAL = "LITERAL"
GAP = "GAP"
VERDICTS = (NATIVE, CONSTRUCTOR, LITERAL, GAP)

BY_RUN = "исполнением"
BY_READ = "разбором"


class Row:
    """One census row. Deliberately immutable."""

    __slots__ = ("verdict", "via", "checked_by", "note", "ceiling", "owner")

    def __init__(self, verdict: str, via: str, checked_by: str, note: str = "",
                 ceiling: str = "", owner: str = "") -> None:
        if verdict not in VERDICTS:
            raise ValueError(f"неизвестный исход {verdict!r}")
        if checked_by not in (BY_RUN, BY_READ):
            raise ValueError(f"неизвестный способ проверки {checked_by!r}")
        if verdict == GAP and not (note and owner):
            raise ValueError("GAP обязан нести ПРИЧИНУ и ВЛАДЕЛЬЦА потолка")
        self.verdict, self.via, self.checked_by = verdict, via, checked_by
        self.note, self.ceiling, self.owner = note, ceiling, owner


#: PARAMETER KIND -> how the author obtains a value of that kind.
#: The keys must match `spec.PARAM_KINDS` EXACTLY. A ratchet holds this.
CENSUS: dict[str, Row] = {
    # ── Python builds it itself ─────────────────────────────────────────
    "int": Row(NATIVE, "число", BY_RUN),
    "num": Row(NATIVE, "число", BY_RUN),
    "mm": Row(NATIVE, "число в мм", BY_RUN),
    "deg": Row(NATIVE, "число в градусах", BY_RUN),
    "str": Row(NATIVE, "строка", BY_RUN),
    "str_long": Row(NATIVE, "строка", BY_RUN),
    "bool": Row(NATIVE, "булево", BY_RUN),
    "value": Row(NATIVE, "число/строка/булево", BY_RUN,
                 note="значение параметра Revit: род решает сам параметр"),
    # 🔴 13.09.2026. Автор НЕ придумывает эти два поля и не может их вычислить:
    # оба приходят из `element_identity` квитанции создания либо из
    # `query_element_state`. Поэтому род NATIVE по форме (обычный словарь из
    # двух строк) и BY_READ по проверке: правильность значения решает не
    # исполнение питона, а то, читал ли автор элемент.
    "identity": Row(NATIVE, "{unique_id, version_guid} из квитанции", BY_READ,
                    note=("личность, КАКОЙ ОНА БЫЛА ПРОЧИТАНА: база правки. "
                          "Источник один — element_identity квитанции создания "
                          "или query_element_state; выдумать её нельзя")),
    "fields": Row(NATIVE, "список строк", BY_RUN),
    "enum_list": Row(NATIVE, "непустой список без повторов из choices параметра",
                     BY_RUN,
                     note=("множественный выбор из ЗАКРЫТОГО словаря, и словарь "
                           "берётся у самого параметра, а не у модуля — этим он "
                           "отличается от `fields`, прибитого к LIST_FIELDS. "
                           "Первый носитель: query_level_plan.include")),
    "pt_xy": Row(NATIVE, "[x, y]", BY_RUN),
    "pt_xyz": Row(NATIVE, "[x, y, z]", BY_RUN),
    # 21.08: DIRECTION. The shape is the same as a point's — three numbers
    # — and the KIND DIFFERS: a point is shifted into a local frame, a ray
    # must not be shifted. While `ref_dir` lived under the point kind, the
    # decompiler's printout turned [-1, 0, 0] into [-1001, -500, 0]. The
    # author, meanwhile, has nothing to build: a list of three numbers.
    "dir_xyz": Row(NATIVE, "[x, y, z] — ЛУЧ, не точка", BY_RUN,
                   ceiling="ноль запрещён; длина не значит ничего",
                   note="конструктора нет и не нужен: над тремя числами он "
                        "был бы лишним именем. Единица не требуется — Ревит "
                        "нормализует сам"),
    "pt_view2d": Row(NATIVE, "[u, v] в пространстве ВИДА", BY_RUN,
                     note="не координата модели — отсчёт от начала вида"),
    "pts": Row(NATIVE, "список [x, y]", BY_RUN),
    "pts_list": Row(NATIVE, "список колец", BY_RUN),
    "pts_xyz": Row(NATIVE, "список [x, y, z]", BY_RUN),
    "path": Row(NATIVE, "ломаная списком точек", BY_RUN),
    "path3": Row(NATIVE, "трёхмерная ломаная", BY_RUN),
    "placements": Row(NATIVE, "список [x, y]", BY_RUN,
                      note="места, куда ставится группа"),

    # ── there is a named constructor ────────────────────────────────────
    "sel": Row(CONSTRUCTOR, "строка | id | ручка | DEFAULT | family_type()",
               BY_RUN, note="четыре равные формы, программа у них побайтно одна"),
    "sel_list": Row(CONSTRUCTOR, "список тех же форм", BY_RUN),
    "target": Row(CONSTRUCTOR, "id | ручка", BY_RUN),
    "target_w": Row(CONSTRUCTOR, "id | ручка", BY_RUN,
                    note="by=name здесь НЕ принимается — цель правки адресуется точно"),
    "refs_w": Row(CONSTRUCTOR, "список целей", BY_RUN),
    # `sweep` has been named in `via` since 29.08 (F-293): it had lived in
    # the sandbox since 19.08 and was not listed in the census's promise —
    # the reachability guard derives names FROM `via`, and it does not
    # guard an unnamed name.
    "mesh": Row(CONSTRUCTOR, "extrude(контур, высота) | sweep(профиль, путь)",
                BY_RUN,
                ceiling="4096 вершин и 4096 треугольников",
                note="19.08: закрыт. Трёхмерных булевых нет ни в одной "
                     "библиотеке песочницы — плановые есть и работают"),
    "region": Row(CONSTRUCTOR,
                  "region(polygon) | offset(контур, d) | thicken(путь, w) | "
                  "словарь формы", BY_RUN,
                  ceiling=(f"кольцо {MIN_RING_POINTS}..{MAX_RING_POINTS} точки, "
                           f"дыр не более {MAX_HOLES}"),
                  note="19.08: закрыт мост из плановой булевы shapely. "
                       "29.08 (F-293): к тому же роду ведут ещё две двери — "
                       "смещение контура и полоса вокруг пути; до этого дня "
                       "они были построены и недостижимы"),
    "member_ops": Row(CONSTRUCTOR, "список ручек", BY_RUN,
                      note="19.08: закрыт. Ручка ИЗЫМАЕТ оп из программы в "
                           "члены; член не может ссылаться наружу группы"),

    # ── written as a dict, its shape printed by help ─────────────────────
    "enum": Row(LITERAL, "слово из закрытого словаря; spec(<оп>)", BY_RUN),
    "kind_enum": Row(LITERAL, "вид из 53; spec('query_count')", BY_RUN),
    "filters": Row(LITERAL, "список условий; spec('query_list')", BY_RUN),
    "arc": Row(LITERAL, "{bulge} либо {radius_mm, dir}", BY_RUN),
    "slopes": Row(LITERAL, "список {edge, angle}", BY_RUN),
    "spiral": Row(LITERAL, "{center_mm, radius_mm, sweep_deg}", BY_RUN),
    "graph_nodes": Row(LITERAL, "список {id, xyz}", BY_RUN),
    "graph_segments": Row(LITERAL, "список {from, to}", BY_RUN),
    # 23.08: THE WALL LAYER STACK-UP. Set up not "for completeness" but by
    # a number: the author's K3 apartment, sent to a clean "Project1", gave
    # 29 operations, of which 9 arrived, and TWELVE of the twenty blocked
    # ones were all apartment walls whose target has no type (0 of 185). A
    # wall type is not a symbol: its dimensions live in `CompoundStructure`,
    # not in parameters.
    #
    # There is deliberately NO constructor, as with `solid_parts`: a layer
    # is three numbers and two names, and building something over them
    # would be an extra name. A material is addressed by an EXACT name:
    # zero matches and more than one are different refusals, "the first one
    # found" is forbidden.
    "wall_layers": Row(LITERAL,
                       "список {width_mm, function, material?}; "
                       "spec('create_wall_type')", BY_RUN,
                       ceiling=(f"слоёв 1..{_rb.WALL_LAYERS_MAX}; толщина "
                                f"{_rb.WALL_LAYER_MIN_MM:.0f}.."
                                f"{_rb.WALL_LAYER_MAX_MM:.0f} мм; функций "
                                f"{len(_rb.WALL_LAYER_FUNCTIONS)} и словарь "
                                f"закрыт"),
                       note="23.08: построен живьём, 26 типов из 31 на K3. Не "
                            "строятся вертикально-составные и витражные — "
                            "предел РЕВИТА (CreateSimpleCompoundStructure), "
                            "названный отказом, а не наш"),
    # On 20.08 the kind was introduced, but no row was placed here: the
    # census stayed red for TWO DAYS and was only read on 22.08. The
    # boolean-op solid operand primitives are born and die within one op,
    # they never become elements.
    "solid_parts": Row(LITERAL,
                       "список {shape: box|sphere|cylinder|prism, center_mm, "
                       "…}; spec('create_solid_boolean')", BY_RUN,
                       ceiling="частей 2..8; формы ЧЕТЫРЕ и список закрыт",
                       note="конструктора НЕТ намеренно: части — это числа, а "
                            "не построение. Трёхмерных булевых в песочнице "
                            "нет ни в одной библиотеке, поэтому автор их и не "
                            "считает — он их ЗАКАЗЫВАЕТ, а считает Ревит"),
    # 20.08: a smooth NURBS surface. Alongside `mesh` and NOT instead of
    # it: a mesh is facets, a surface is smooth, they have different laws
    # and different witnesses. The input is CONTROL points, not
    # interpolation points, and this is decided by the lift side:
    # `geom_extract.__gxNurbsSurface` reads exactly those, otherwise the
    # loop would not close by construction.
    "surface": Row(LITERAL,
                   "{degree_u, degree_v, count_u, count_v, knots_u, knots_v, "
                   "control_points_mm[, weights]}", BY_RUN,
                   ceiling="степень 1..7, контрольных точек не более 4096 — "
                           "ОБА НАЗНАЧЕНЫ, не измерены",
                   note="конструктора НЕТ (в отличие от mesh.extrude): сетку "
                        "контрольных точек автор считает питоном сам. Порядок "
                        "точек u-major — НАЗВАННОЕ допущение, Autodesk его не "
                        "документирует, и первый живой прогон ответит на него "
                        "через свидетеля"),
    # 21.08: THE SKETCH PLANE. Introduced not "for generality" but by a
    # number: capturing family recipes rejected 73 shapes out of 283 with
    # the `sketch_plane_not_horizontal` code — the biggest refusal in the
    # capture. A WINDOW's or DOOR's shape lies on a wall face, and a planar
    # extrusion cannot say that.
    "plane": Row(LITERAL, "{origin_mm, normal, x_dir}", BY_RUN,
                 ceiling=(f"начало ±{_plane.PLANE_ORIGIN_ABS_MAX_MM:,.0f} мм"
                          .replace(",", " ")
                          + f"; |cos(x_dir, normal)| <= "
                            f"{_plane.ORTHOGONALITY_COS_TOL:g}"),
                 note="НЕОБЯЗАТЕЛЕН: без него профиль в мировой XY и ход по "
                      "+Z — сегодняшнее поведение байт-в-байт. Вместе с "
                      "base_z_mm НЕ принимается: base_z_mm и есть "
                      "горизонтальная плоскость. x_dir обязателен — иначе оси "
                      "В плоскости выбрал бы Revit, и поворот профиля не "
                      "заметил бы НИ ОДИН из трёх свидетелей"),
}


#: NAMED ABSENCES — what does NOT exist in the language, with a reason and an owner.
#:
#: This list's kind: **CLOSED, BUT NOT COMPLETE.** Empty here would mean "we
#: don't know", not "everything exists except what is listed". A row is set
#: up when an absence is NAMED, and it cannot be found automatically — it is
#: discovered when someone runs into it.
#:
#: 🔴 WHY WRITE DOWN AN ABSENCE AT ALL. An unnamed absence forces THE NEXT
#: PERSON to search for something that does not exist — costing them a turn,
#: and then another to make sure. Telling "an environment boundary" apart
#: from "our debt" carries weight: the first cannot and need not be closed,
#: the second is work that has an owner.
DECLARED_ABSENCES: dict[str, dict] = {
    "трёхмерные булевы": {
        "род": "ГРАНИЦА СРЕДЫ, не наш долг",
        "почему": (
            "в песочнице нет ни одной библиотеки, умеющей булевы над ТЕЛАМИ: "
            "shapely плоская по устройству, numpy — про массивы. Ни trimesh, "
            "ни manifold3d, ни open3d в venv не установлены"),
        "что вместо": (
            "ПЛАНОВЫЕ булевы есть и работают сегодня: посчитай фигуру shapely "
            "(`a.difference(b)`) и отдай её в extrude() либо region(). Для "
            "здания этого хватает: этаж, плита с шахтой, ядро с выемкой — "
            "призматические тела"),
        "владелец": "оператор среды (белый список песочницы)",
    },
    # ⛔ THE ENTRY "sweep — a solid along a path" WAS REMOVED ON
    # 19.08.2026: THE DEBT IS CLOSED, the `sweep(profile, path, up=)`
    # constructor has been built and injected into the sandbox.
    #
    # Removed, NOT marked closed, and these are different things. This list
    # describes what does NOT exist TODAY; a closed entry left in it is a
    # stale exception, and that is more dangerous than an honest gap: a
    # reader seeing "our debt, open" will not go looking for a name that is
    # already sitting in their namespace. History is kept by git and by
    # `mesh.sweep`'s own docstring, where exactly how the debt was closed is
    # recorded.
    #
    # What remains NOT closed, and is therefore named in the constructor's
    # docstring rather than here: corner rounding (there is no arc in the
    # language) and twisting the profile along the path. Those are BOUNDARIES
    # OF sweep ITSELF, not an absence of sweep, and the two must not be
    # confused.
}


def absences_text() -> str:
    lines = ["НАЗВАННЫЕ ОТСУТСТВИЯ (закрытый, но НЕ полный список):"]
    for name, row in DECLARED_ABSENCES.items():
        lines.append(f"  {name} — {row['род']}")
        lines.append(f"    почему: {row['почему']}")
        lines.append(f"    что вместо: {row['что вместо']}")
        lines.append(f"    владелец: {row['владелец']}")
    return "\n".join(lines)


def missing_rows() -> list[str]:
    """Registry kinds absent from the census. THERE MUST BE NONE."""
    return sorted(set(spec.PARAM_KINDS) - set(CENSUS))


def stray_rows() -> list[str]:
    """Census rows that no registry kind answers to."""
    return sorted(set(CENSUS) - set(spec.PARAM_KINDS))


def gaps() -> dict[str, Row]:
    """What CANNOT be said. Empty means no inexpressible kinds remain."""
    return {k: r for k, r in CENSUS.items() if r.verdict == GAP}


def tally() -> dict[str, int]:
    out = {v: 0 for v in VERDICTS}
    for row in CENSUS.values():
        out[row.verdict] += 1
    return out


def text() -> str:
    lines = ["ПЕРЕПИСЬ ВЫРАЗИМОГО — род значения -> чем автор его получает",
             f"род списка: ПОЛНЫЙ ПО ПОСТРОЕНИЮ (авторитет: spec.PARAM_KINDS, "
             f"{len(spec.PARAM_KINDS)} родов)", ""]
    for verdict in VERDICTS:
        rows = {k: r for k, r in CENSUS.items() if r.verdict == verdict}
        if not rows:
            lines.append(f"{verdict}: НЕТ НИ ОДНОГО")
            continue
        lines.append(f"{verdict} ({len(rows)}):")
        for name, row in sorted(rows.items()):
            tail = f"  [{row.checked_by}]"
            if row.ceiling:
                tail += f"  потолок: {row.ceiling}"
            lines.append(f"    {name:16s} {row.via}{tail}")
            if row.note:
                lines.append(f"    {'':16s} — {row.note}")
        lines.append("")
    counts = tally()
    lines.append(f"ИТОГО {sum(counts.values())} родов: "
                 + ", ".join(f"{k} {v}" for k, v in counts.items()))
    run = sum(1 for r in CENSUS.values() if r.checked_by == BY_RUN)
    rest = len(CENSUS) - run
    lines.append(f"проверено ИСПОЛНЕНИЕМ {run} из {len(CENSUS)}"
                 + (f"; остальные {rest} — разбором реестра, и это РАЗНЫЕ "
                    f"факты" if rest else " — каждый род прогнан через "
                    "настоящую песочницу"))
    if gaps():
        lines.append("🔴 НЕВЫРАЗИМО: " + ", ".join(sorted(gaps())))
    else:
        lines.append("НЕВЫРАЗИМЫХ РОДОВ НЕТ — ни одной строки GAP")
    lines.append("")
    lines.append(absences_text())
    return "\n".join(lines)


if __name__ == "__main__":       # pragma: no cover
    print(text())
