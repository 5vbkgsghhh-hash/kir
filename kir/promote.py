"""PROMOTING A SHAPE INTO BIM: the author writes the shape, the environment hangs meaning on it.

    shell = loft([(bottom, 0), (top, 30000)])
    for f in faces(shell, facing="up"):
        promote(f, level=floor)          # a horizontal slab -> a floor

WHY, AND THIS IS A MEASUREMENT, NOT TASTE
------------------------------------------
Owner's word, 01.09.2026: "an LLM does much better in three.js than in Revit;
I want a tool that, like Rhino and three.js, can build beautiful objects, but
they will be BIM-oriented." Why Revit produces shacks is measured: of 82
registry operations **47 require a catalog from a snapshot** (a type by NAME
the author does not know), **32 require a level**, **12 — a host**; the
language's reference costs **43,030 tokens** against **519** for raw C#; in
the live corpus **121 turns** went into RECON instead of building.

The `kir.course.rhino` vocabulary removed the first half: a shape can now be
written. This module removes the second: the shape gains BIM meaning, and it
gains it AFTER the shape, from the shape itself, not from the question "so
what do you call the type here."

WHAT IS DELIBERATELY NOT HERE
------------------------------
* **There is no layout solver.** Owner's word, 02.09: "an infinite number of
  BIM models exists, I don't want a solver producing a limited number of
  layouts." Nothing is LAID OUT here: the author chooses the shape, the
  environment only reads what was already written and names its kind.
* **There are no new refusal codes** (owner's word, 27.08: "no more reasons
  are needed for now"). Promotion does not refuse — it either raises the
  kind, or honestly leaves the shape as geometry and NAMES exactly what it
  did not become.
* **Nothing is built "by face."** Roslyn measurement 6/6: out of the whole
  "by face" family, only one `FaceWall.Create` exists; floors and roofs by
  face do NOT exist (0 of 6). So promotion targets NATIVE operations
  (`create_wall`, `create_floor_by_contour`, `create_roof`, `create_column`),
  not surface-based constructors.

🔴 THE MAIN THING THIS MODULE MUST NOT DO: SILENTLY CHANGE A DIMENSION
------------------------------------------------------------------------
A wall's thickness in Revit is a property of the TYPE, not of the command:
`Wall.Create` takes a `wallTypeId`, and the wall comes out with THAT TYPE's
thickness. So a 380 mm strip, promoted into a wall of type «Кирпич 250»,
becomes a 250 mm wall — the shape changes SILENTLY, and that is exactly what
promotion has no right to do. The same holds for a column, whose section
belongs entirely to its type-size.

Hence the module's law: **a quantity that the SHAPE determines must either
enter the TYPE SELECTION, or be NAMED as having been ceded to the type.**
Both paths are open:

    promote(f, level=lv, type_param="Толщина")   # the type is looked up by the shape's thickness
    promote(f, level=lv, type=my_type)           # the author named the type themselves
    promote(f, level=lv)                         # default type, and the report
                                                 # carries `dimension_from_type`

The thickness parameter's name is NOT GUESSED and is not hard-coded as a
list: on a Russian install it is «Толщина», on an English one `Width`, and a
name dictionary is exactly the approach the owner rejected on 28.08 ("you
can't foresee every word... a pile of junk in the code"). The name is given
by the author or the host, once per document.

WHAT IS READ FROM THE SHAPE, AND WHAT IS NOT
-----------------------------------------------
What is read: the slab's orientation, its thickness, extents, contour,
slope, elevations. All of this is a fact of the MESH, and none of it depends
on the document or the locale.

The level is not extracted from the shape: the author either references a
declared level, or allows the nearest one below to be chosen within the
current program. The actual elevation is needed to compute offsets. An
unknown live selector stays unresolved, rather than being given a made-up
elevation of 0.

The result is the author's native candidate, NOT an executed and verified
BIM. Geometric classification does not prove the shape's intended purpose.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kir import dsl as _dsl
from kir import spec as _spec
from kir.course import rhino as _rhino
from kir.instruments.native_share import geometry_only_ops as _geometry_only_ops
from kir.ops_shape import IMPERSONATION_ROUTES

# ⚠️ THE LAYER'S DIRECTION IS NAMED, NOT HIDDEN: production asks the
# INSTRUMENT. The carrier of "what counts as geometry with no BIM meaning" is
# derived in `native_share` from the registry by TWO questions (the
# capability is exactly `create/geometry` AND there is no result category)
# and is covered by its own test. A second such derivation HERE would
# diverge from the first on the day the rule gets fixed in only one of the
# two places. The naive "capability == create/geometry" is also wrong, and
# this is measured: 14 operations fit it, among them
# `create_floor_by_contour` — a REAL floor.
#
# 🔴 THE IMPORT IS SPECIFICALLY MODULE-LEVEL, AND THIS WAS PAID FOR BY THE
# 02.09.2026 RUN. A lazy import inside `unpromoted` survives to the call
# ONLY outside the sandbox: inside the child, the import guard hits
# `kir.instruments` and — worse — blames the AUTHOR, on their
# `design_check()` line:
#     KIR-B004 импорт 'kir.instruments' запрещён … blame='author', line=8
# The author of a correct program would get a refusal for our lazy import.
# The cost of the module-level import is measured: `kir.promote` pulls in
# 166 modules, with the instrument, 170.


#: The cosine at which a normal is counted as vertical or horizontal. The
#: same quantum `rhino._facing` uses to name a cardinal direction: two laws
#: about "is this flat" would diverge on the very first sloped slab.
_AXIS_COS = 0.999

#: The ceiling on slab thickness, above which a shape stops being a slab.
#: The number is ASSIGNED, not measured, and is therefore named here rather
#: than hidden in a condition: 600 mm is the top of common load-bearing
#: thicknesses (a 380 wall, a 250 slab, a 500 solid). Thicker than that is no
#: longer a "slab" but a volume, and promoting it into a wall would mean
#: selling a confidence the shape does not have.
MAX_SLAB_MM = 600.0

#: How many times the length must exceed the thickness for a vertical slab
#: to read as a WALL rather than a column. Also assigned: at a ratio of 1, a
#: post square in plan is indistinguishable from a piece of wall, and any
#: choice would be a coin flip.
WALL_SLENDERNESS = 3.0

#: The largest plan extent at which a vertical body can be a column. 1.2 m
#: is the top of common sections; wider is a pylon or a wall.
MAX_COLUMN_PLAN_MM = 1200.0

#: The tolerance with which a SHAPE's thickness looks up its TYPE in the
#: catalog. 🔴 This is a tolerance for the NUMBER'S REPRESENTATION, NOT FOR
#: A DIMENSION, and the value is taken from measurement, not convenience
#: (02.09.2026):
#:
#:   the shape's side    is EXACT. A 380 mm strip gives exactly 380.0, both
#:                        axis-aligned and rotated by 1°, 17°, 30°, 45°:
#:                        `rhino.faces` rounds the thickness to 1e-6 mm.
#:   the catalog's side  is NOT MEASURED HERE: there is no live document in
#:                        the tree. Revit stores lengths in feet, and 250 mm
#:                        comes back through the bridge as
#:                        250.00000000000003 — a discrepancy on the order of
#:                        1e-14 mm.
#:
#: Hence 1e-6: it absorbs the representation and absorbs NOT A SINGLE real
#: dimension. A tolerance of one millimeter would silently accept a type
#: that is off by a millimeter — exactly what the whole module is written to
#: forbid. The author may name their own tolerance, but by default the
#: module does not buy convenience with dimension.
TYPE_MATCH_TOL_MM = 1e-6

#: The CLOSED list of reasons a shape stayed a shape. These are NOT refusal
#: codes: promotion rejects nothing, it names what the shape did not
#: become. The list is closed so a report's reader can rely on it, and it is
#: NOT COMPLETE: a new kind of shape will bring a new reason, and it will
#: have to be added here — visibly, not silently.
REASONS: dict[str, str] = {
    "no_mesh": "у формы нет меша: спрашивать её грани нечем",
    "no_cap_pair": ("у формы нет пары встречных граней равной площади — это не "
                    "плита; толщину читать не с чего"),
    "too_thick": ("толщина {t:.0f} мм больше {max:.0f} мм: это объём, а не "
                  "плита, и род его формой не определяется"),
    # ONE reason for ONE outcome, and it names BOTH halves of the truth. A
    # second one used to stand next to it — about the plan extent — and
    # there was NO INPUT that could ever reach it: the order of checks handed
    # this case here instead. A reason no one can ever reach is a promise,
    # not a rule; caught by the closed-list guard in
    # `test_promotion_of_a_shape.py`.
    "not_slender": ("вертикальная плита {l:.0f} x {t:.0f} мм: длина меньше "
                    "{k:g} толщин — стеной это не читается, а габарит в плане "
                    "{w:.0f} мм больше {max:.0f} мм — и колонной тоже"),
    "column_needs_symbol": ("сечение колонны целиком принадлежит ТИПОРАЗМЕРУ, "
                            "а не форме: без `symbol=` продвижение поменяло бы "
                            "сечение молча. Назови типоразмер"),
    "ring_not_planar": "граница грани не замкнулась кольцом — контур брать не с чего",
    "axis_not_recoverable": ("ось полосы не восстанавливается однозначно: "
                             "проекция грани в план не легла отрезком"),
    "form_is_spoken_for": ("операции этой формы уже изъяты из программы — её "
                           "забрала группа. Продвинуть значило бы построить и "
                           "группу, и элемент на одном месте"),
    # ── the level, when the author did not name one ──────────────────────────
    "no_level_in_program": ("уровень не назван, и взять его неоткуда: в "
                            "программе нет ни одного `create_level`. Объяви "
                            "уровень этой же программой либо передай "
                            "`level=` сам"),
    "no_level_below": ("тело стоит на отметке {z:.0f} мм, а все уровни "
                       "программы ВЫШЕ ({уровни}). Ставить элемент на уровень "
                       "над ним значило бы молча поменять его отметку"),
    "level_is_ambiguous": ("на отметке {e:.0f} мм объявлено {n} уровня — какой "
                           "из них имел в виду автор, форма не говорит. "
                           "Передай `level=` сам"),
    "level_elevation_unknown": ("отметка выбранного уровня неизвестна в этой "
                                "программе: сохранить Z через смещение нельзя. "
                                "Передай ссылку на объявленный create_level; "
                                "отметка существующего уровня требует grounding"),
    "placement_out_of_bounds": ("{field}={value:g} мм вне контракта {op} "
                                "[{low:g}, {high:g}]. Выбери объявленный уровень "
                                "ближе к телу; исходная геометрия сохранена"),
    "roof_placement_unresolved": ("наклонная форма — кандидат кровли, но "
                                  "размещение её граней относительно footprint, "
                                  "уровня и толщины типа ещё не определено; "
                                  "исходная геометрия сохранена"),
}

#: The tolerance for comparing elevations when choosing a level. Not
#: hand-picked: it is the same quantum used to compare millimeters when
#: choosing a type (`TYPE_MATCH_TOL_MM`), and two tolerances of the same tree
#: have no reason to diverge.
LEVEL_PICK_TOL_MM = 1e-6


class PromotionError(ValueError):
    """An input promotion cannot use (not a refusal of the language)."""


def _fmt(key: str, **kw: Any) -> str:
    return REASONS[key].format(**kw)


def _stay(shape: Any, key: str, measured: dict, **kw: Any) -> dict:
    """The shape stays a shape, and the reason is NAMED."""
    return {"ops": list(_own_ops(shape)), "native": False, "role": None,
            "status": "geometry_only", "verified": False,
            "reason_key": key, "reason": _fmt(key, **kw), "measured": measured,
            "dimension_from_type": None, "retracted": 0}


def _own_ops(shape: Any) -> list:
    """The operations that build the shape today (the carrier `loft`/`prism`)."""
    if isinstance(shape, dict):
        ops = shape.get("ops")
        if isinstance(ops, list):
            return ops
    return []


def _retract(shape: Any) -> tuple[bool, int]:
    """RETRACT from the program the operations by which the shape stood as GEOMETRY.

    🔴 PROMOTION REPLACES, IT DOES NOT ADD, and this was paid for by the
    02.09.2026 run: a scene of three shapes produced **6 operations** (3
    `create_solid_blend` + 3 native) and a native share of **50%** instead of
    100%. That is, the building came out built TWICE — as a body and as a
    wall in the same place — and no native-share gate would have told such a
    model apart from an honest one: the share counts the kinds of
    operations, not whether they sit on top of each other.

    The door is `Program.take`, the very same one a group uses to take its
    members (`dsl._coerce_members`), and it is not taken blindly: an address
    is not freed on retraction, so two different operations can never become
    indistinguishable in the receipt. If even one address is already gone
    from the program, someone else has already taken the shape, and then
    NOTHING is retracted: half a retraction is worse than zero.
    """
    own = _own_ops(shape)
    if not own:
        return True, 0
    адреса = [h.id for h in own if isinstance(h, _dsl.Handle)]
    if len(адреса) != len(own):
        return False, 0
    prog = _dsl.current()
    живые = {op.get("id") for op in prog.ops}
    if not all(a in живые for a in адреса):
        return False, 0
    for a in адреса:
        prog.take(a)
    return True, len(адреса)


def _native(shape: Any, ctor: Any, kw: dict, *, role: str, measured: dict,
            отдано: Optional[dict] = None, dry: bool = False,
            native_op: Optional[str] = None) -> dict:
    """The native branch's only exit: FIRST retract the shape, then place it.

    The order is exactly this. The reverse order would leave both operations
    in the program at the exact moment retraction fails, and the report
    would call that a success.

    🔴 BUT THE ORDER IS NOT ENOUGH — ATOMICITY IS NEEDED (LD-07, 04.09.2026).
    There was no `try` between the retraction and the constructor, and a
    constructor failure left a THIRD state: the shape already gone, the
    native operation not yet there. Measurement: level `level1`, a loft,
    `promote(..., id='level1')` — before the call the program has
    `create_level` and `create_solid_blend`; after the `KIR-P006` failure
    only ONE `create_level` remains. The author got a refusal and lost what
    they had written.

    Swapping the branch's order around is the WRONG fix: it brings back
    exactly the state the order was chosen to forbid. The fix is a
    ROLLBACK. Retraction is already atomic on its own (`_retract` checks ALL
    addresses before taking the first one, and takes nothing on a miss), so
    what was left to fix was the other half: a snapshot of the operation
    order before retraction, and restoring it on any constructor failure.

    The snapshot is `list(prog.ops)`: its own LIST, the same dicts.
    Restoring with `prog.ops[:] = snapshot` brings back both the order and
    everything the constructor managed to append before failing. Addresses
    are NOT freed in the process (`Program.take` keeps them in `_ids` on
    purpose) — reissuing an id that was already taken once would make two
    different operations indistinguishable in the receipt.

    The constructor's failure travels upward as its OWN error, not swapped
    for `_stay`: this module introduces no new refusal codes (owner's word,
    27.08), and an "address collision" is `KIR-P006`, not "the shape did not
    become a wall." Exactly one thing changes: by the time the failure
    reaches the author, the program is intact.

    🔴 `dry` IS NOT A SECOND LAW, IT IS THE SAME ONE. A dry run answers the
    question "what would this shape BECOME," and answers it with the same
    analysis actual promotion uses: there is one fork, and it stands HERE,
    after the kind is already determined. A separate "analysis for the
    judge" would diverge from promotion on the day the rule gets fixed in
    only one of the two places — and the judge would start promising
    something other than what `promote` does.
    """
    if dry:
        return {"ops": list(_own_ops(shape)), "native": True, "role": role,
                "status": "geometry_candidate", "verified": False,
                "reason": None, "measured": measured,
                "dimension_from_type": отдано, "retracted": 0}
    # Placement must be expressible before the original shape is retracted.
    # Read limits from the native operation's registry, not a second table.
    if native_op is not None:
        for param in _spec.OPS[native_op].params:
            if param.name not in ("base_offset_mm", "top_offset_mm",
                                  "height_offset_mm", "height_mm"):
                continue
            value = kw.get(param.name)
            if value is None:
                continue
            if ((param.min_val is not None and value < param.min_val)
                    or (param.max_val is not None and value > param.max_val)):
                return _stay(shape, "placement_out_of_bounds", measured,
                             op=native_op, field=param.name, value=value,
                             low=param.min_val if param.min_val is not None else -math.inf,
                             high=param.max_val if param.max_val is not None else math.inf)
    prog = _dsl.current()
    снимок = list(prog.ops)
    ok, снято = _retract(shape)
    if not ok:
        return _stay(shape, "form_is_spoken_for", measured)
    try:
        поставлено = ctor(**kw)
    except BaseException:
        # EITHER IT PROMOTED ENTIRELY, OR THE PROGRAM IS UNTOUCHED. What is
        # caught is `BaseException`, not `Exception`: an interruption in the
        # middle of the replacement would leave the same hole, and the
        # `raise` below silences no one.
        prog.ops[:] = снимок
        raise
    return {"ops": [поставлено], "native": True, "role": role, "reason": None,
            "status": "authored_candidate", "verified": False,
            "measured": measured, "dimension_from_type": отдано,
            "retracted": снято}


def _declared_levels() -> list[dict]:
    """Only current, top-level definitions with an actual finite elevation."""
    return [op for op in _dsl.current().ops
            if isinstance(op, dict) and op.get("op") == "create_level"
            and isinstance(op.get("elev_mm"), (int, float))
            and not isinstance(op["elev_mm"], bool)
            and math.isfinite(op["elev_mm"])]


def _resolve_level(level: Any) -> tuple[Any, Optional[float]]:
    """Resolve authored level identity, never guess a live selector's elevation.

    Names become refs to the definition whose elevation was read. Handles
    retain a payload (not program ownership); reject contradictory stale data.
    """
    levels = _declared_levels()
    if isinstance(level, _dsl.Handle):
        matches = [op for op in levels if op.get("id") == level.id
                   and level.op == "create_level"
                   and all(op.get(key) == value for key, value in level._node.items())]
    else:
        sel = {"by": "name", "value": level} if isinstance(level, str) else level
        if not isinstance(sel, dict) or set(sel) != {"by", "value"}:
            return level, None
        field = {"ref": "id", "name": "name"}.get(sel.get("by"))
        if field is None:
            return level, None
        matches = [op for op in levels if op.get(field) == sel.get("value")]
    if len(matches) != 1:
        return level, None
    op = matches[0]
    return {"by": "ref", "value": op["id"]}, float(op["elev_mm"])


def _level_from_program(z_low: float) -> tuple[Any, Optional[str], dict]:
    """A LEVEL THE AUTHOR HAS ALREADY DECLARED — chosen by the body's elevation.

    🔴 THIS IS NOT A SOLVER, AND THE BOUNDARY HERE IS EXACT. Owner's word,
    02.09: "I don't want a solver producing a limited number of layouts."
    Nothing is laid out and nothing is invented here: the level taken is one
    the author WROTE THEMSELVES, and it is chosen by one measurable rule —
    the nearest one BELOW the body's bottom. If no level is declared, the
    environment refuses and says why.

    WHY. Of the registry's 82 operations, **32 require a level**, and a
    shape has no level and nowhere to get one from — that is half of the
    measured reason Revit produces shacks. The other half (a type by name
    from a snapshot) is removed by choosing the type from a value; this one
    closes the first half.

    WHY `{"by": "ref"}`, AND NOT A NEW KIND OF SELECTOR. A `{"by":
    "elevation"}` selector was built and then removed on 02.09: it requires
    the agreement of seven boundaries (grammar, grounding, fold
    canonicalization, the reverse pass...), and
    `midend._valid_grounded_selector` dropped it into `KIR-P000` on a
    SUCCESSFUL path. A reference, on the other hand, is exactly what an
    AUTHOR'S HANDLE turns into: proven by execution,
    `create_wall(level=handle)` places `{"by": "ref", "value": "level1"}`
    into the slot byte-for-byte. So no new grammar is introduced here AT
    ALL, and not one of the seven boundaries moves.

    Returns `(селектор | None, ключ_причины | None, добавка_в_measured)`.
    """
    # The program's top level, without descending into groups:
    # `create_group` TAKES members out of the program (`Program.take`), and a
    # level that has moved into a group is no longer the same subject —
    # referencing a group member from outside is not allowed.
    уровни = _declared_levels()
    if not уровни:
        return None, "no_level_in_program", {}

    def отметка(op: dict) -> float:
        return float(op["elev_mm"])

    ниже = [op for op in уровни if отметка(op) <= z_low + LEVEL_PICK_TOL_MM]
    if not ниже:
        отметки = ", ".join(f"{отметка(o):.0f}" for o in sorted(уровни, key=отметка))
        return None, "no_level_below", {"отметка_низа_мм": round(z_low, 3),
                                        "отметки_уровней_мм": отметки}
    высшая = max(отметка(o) for o in ниже)
    выбор = [o for o in ниже if abs(отметка(o) - высшая) <= LEVEL_PICK_TOL_MM]
    if len(выбор) != 1:
        return None, "level_is_ambiguous", {"отметка_мм": round(высшая, 3),
                                            "уровней_на_отметке": len(выбор)}
    op = выбор[0]
    # WHAT EXACTLY WAS CHOSEN GOES INTO THE REPORT, ALWAYS. A choice the
    # author only learns about from the finished building is a silent change
    # to their design.
    return ({"by": "ref", "value": op["id"]}, None,
            {"уровень": {"id": op.get("id"), "имя": op.get("name"),
                         "отметка_мм": отметка(op),
                         "как": "выбран средой: ближайший СНИЗУ к низу тела"}})


def _plan_ring(ring: list) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in ring]


def _extent(values) -> tuple[float, float]:
    return (min(values), max(values)) if values else (0.0, 0.0)


def _cap_pair(fs: list[dict]) -> Optional[dict]:
    """The largest face that has a MATCHING counter-face of the same area.

    The thickness is given by `rhino.faces`, and it already refuses to name
    it as a number when there is more than one matching face (form 44: an
    uncomputed value is printed as a word). Here that refusal is simply read.
    """
    годные = [f for f in fs if isinstance(f.get("thickness_mm"), (int, float))]
    return max(годные, key=lambda f: f["area_mm2"]) if годные else None


def _segment_of(ring_xy: list[tuple[float, float]]) -> Optional[tuple]:
    """The segment a vertical face's projection onto the plan lands on.

    A vertical face projects onto a SEGMENT: it has two distinct points in
    plan, and every other point lies between them. If that is not so, the
    face is not a flat vertical strip, and the wall's axis is not
    recovered; returning "approximately" would put the wall in the wrong
    place.
    """
    if len(ring_xy) < 2:
        return None
    a = ring_xy[0]
    b = max(ring_xy, key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2)
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L <= 0.0:
        return None
    ux, uy = dx / L, dy / L
    for p in ring_xy:
        поперёк = abs(-(p[0] - a[0]) * uy + (p[1] - a[1]) * ux)
        if поперёк > 1e-6:
            return None
    return (a, b, L, (ux, uy))


def _type_selector(type: Any, type_param: Optional[str], value_mm: float,
                   tol_mm: float) -> tuple[Any, Optional[dict]]:
    """A type selector and the NAMED ceding of a dimension to the type.

    Three outcomes, and the dimension is NOT CEDED in exactly one: when it
    is the very thing being looked up.

        type_param="Толщина"   the SHAPE's thickness picks the type   -> not ceded
        type=my_type            the author named the type              -> CEDED
        neither of the two       the default decides the type           -> CEDED

    🔴 The second outcome used to be considered safe, and that was WRONG: a
    type named by the author decides the thickness exactly the same way a
    default does. The author named a NAME, not a dimension, and no one
    checked whether the name matches the shape. Paid for by the catalog
    fixture: in `kir.tests.fixtures.GROUND_SNAPSHOT` the only column
    type-size is «К 300x300», and a 400x400 shape would silently drift into
    300x300, indistinguishable in the report from an honest match.

    This is not turned into a refusal — a default and a named type are both
    legitimate paths of the language — but it is not left silent either: the
    dimension travels into the report as a field.
    """
    if type_param:
        return (_dsl.by_default(disambiguate_by={
            "param": type_param, "value": value_mm, "tol_mm": tol_mm}), None)
    if type is not None:
        return type, {"толщина_мм": round(value_mm, 3),
                      "как": "тип назван автором, толщина типа не проверена"}
    return None, {"толщина_мм": round(value_mm, 3),
                  "как": "тип по умолчанию, толщину решит он"}


def promote(shape: Any, *, level: Any = None, type: Any = None,
            type_param: Optional[str] = None, symbol: Any = None,
            tol_mm: float = TYPE_MATCH_TOL_MM, id: Optional[str] = None,
            role: Optional[str] = None, dry_run: bool = False) -> dict:
    """A shape -> a NATIVE BIM operation, or the shape honestly kept, with a named reason.

    Returns a carrier, not an operation: `ops` are placed into the program,
    the remaining fields are read by the author and printed by
    self-verification.

        {"ops": [...],           the shape's operations — ALREADY in the
                                 program (every language call lands there on
                                 its own); the field exists so the author can
                                 reference them
         "native": bool,         a native branch was found (a compatibility
                                 field, NOT a readback)
         "status": str,          geometry_only / geometry_candidate (dry) /
                                 authored_candidate (the operation is recorded)
         "verified": False,      this helper neither executes nor reads Revit
         "role": "walls"|...,    the kind, from the `IMPERSONATION_ROUTES` table
         "reason": str|None,     what the shape did NOT become, if it did not
         "measured": {...},      what was read from the shape: thickness, extent, slope
         "dimension_from_type": dict|None,    WHAT was ceded to the type
                                 unverified ({"толщина_мм": 200.0, "как":
                                 "…"}); None means the shape's own dimension
                                 picked the type
         "retracted": int}       how many geometry operations were RETRACTED from the program

    `role` is NOT GUESSED by name and is not taken from a hint: it is
    derived from the geometry. The `role` argument exists for exactly one
    case — a column whose section belongs to its type-size (see
    `column_needs_symbol`).

    `level` is OPTIONAL. If not named, the environment takes the level the
    author declared THEMSELVES, the one nearest BELOW the body's bottom
    (`_level_from_program`), and RECORDS the choice in
    `measured["уровень"]`. If there is no level at all in the program, that
    is a named refusal, not a guess.

    Recording a candidate needs the actual elevation of the declared level.
    An unknown live selector does not mean a zero elevation: the shape is
    preserved. A wall keeps its bottom/height, a column keeps its bottom and
    top bindings. For a floor the anchor is the TOP of the source slab; its
    bottom depends on the explicitly chosen type.

    `dry_run=True` carries the analysis through to the end and does NOTHING:
    no operation is placed, no geometry is retracted, no level is asked
    for. The door for this is `classify`; there is no need to call `promote`
    with the flag by hand.
    """
    try:
        fs = _rhino.faces(shape)
    except Exception:                       # noqa: BLE001 — a refusal of the shape's, not ours
        return _stay(shape, "no_mesh", {})
    cap = _cap_pair(fs)
    if cap is None:
        return _stay(shape, "no_cap_pair", {"граней": len(fs)})

    t = float(cap["thickness_mm"])
    n = cap["normal"]
    nz = abs(float(n[2]))
    ring = cap.get("ring_mm") or []
    if len(ring) < 3:
        return _stay(shape, "ring_not_planar", {"толщина_мм": t})
    zs = [float(p[2]) for p in ring]
    z0, z1 = _extent(zs)
    plan = _plan_ring(ring)
    xs, ys = [p[0] for p in plan], [p[1] for p in plan]
    ширина = max(max(xs) - min(xs), max(ys) - min(ys))
    measured: dict[str, Any] = {"толщина_мм": round(t, 3),
                                "отметки_кольца_мм": [round(z0, 3), round(z1, 3)],
                                "нормаль": list(n)}
    mesh = _rhino._mesh_of(shape, "shape")
    body_z0, body_z1 = _extent([
        float(mesh["vertices_mm"][index][2])
        for tri in mesh["triangles"] for index in tri])
    measured["отметки_тела_мм"] = [body_z0, body_z1]

    # ONE THICKNESS CHECK FOR THREE ROADS. Before 02.09.2026 there were
    # THREE, and two of them were dead by construction: the first let a
    # horizontal slab through (`nz > _AXIS_COS`), the second caught it in the
    # floor branch, the third stood at the roof — where a thick body never
    # arrived at all, because the first one had already claimed it. Checks
    # with the same outcome and the same `measured` were merged into one;
    # after the merge both former checks are unreachable BY CONSTRUCTION, not
    # "by the tests": this one returns for ANY t > MAX_SLAB_MM.
    if t > MAX_SLAB_MM:
        return _stay(shape, "too_thick", measured, t=t, max=MAX_SLAB_MM)

    # ── THE LEVEL. If the author named one, we take it; if not, we choose
    # by the body's elevation among the ones they declared THEMSELVES. A dry
    # run does not ask for the level: it answers about the SHAPE, and the
    # program's state has no bearing on its answer.
    if level is None and not dry_run:
        level, ключ_уровня, добавка = _level_from_program(body_z0)
        measured.update(добавка)
        if ключ_уровня:
            return _stay(shape, ключ_уровня, measured,
                         z=body_z0, уровни=добавка.get("отметки_уровней_мм", ""),
                         e=добавка.get("отметка_мм", 0.0),
                         n=добавка.get("уровней_на_отметке", 0))
    level_z = None
    if not dry_run:
        level, level_z = _resolve_level(level)
        if level_z is None:
            return _stay(shape, "level_elevation_unknown", measured)
        measured["placement"] = {"level_elevation_mm": level_z,
                                  "source_z_mm": [body_z0, body_z1]}

    # ── THE SLAB LIES FLAT: a floor
    if nz >= _AXIS_COS:
        poly = cap.get("poly")
        if not poly:
            return _stay(shape, "ring_not_planar", measured)
        sel, отдано = _type_selector(type, type_param, t, tol_mm)
        # For a floor, `contour` is a REGION `{outer, holes?}`, while `faces`
        # hands back a ring in `poly` form. The wrapper is taken from the
        # dictionary helper (`rhino._as_region`) rather than written a second
        # time here: the rule for "what counts as a region" must live in ONE
        # place, or holes would get lost on exactly one of the two roads.
        # Paid for by the refusal `KIR-T001 contour: регион — {outer:
        # форма...}` on the very first end-to-end run, 02.09.2026.
        kw: dict[str, Any] = {"contour": _rhino._as_region(poly, "contour"),
                              "level": level}
        if not dry_run:
            # Revit's floor offset locates the TOP, while a shape's lowest cap
            # is its bottom. Type thickness may move the bottom, not this top.
            kw["height_offset_mm"] = round(body_z1 - level_z, 6)
            measured["placement"].update(anchor="top", bottom="depends_on_type_thickness")
        if sel is not None:
            kw["type"] = sel
        if id:
            kw["id"] = id
        return _native(shape, _dsl.create_floor_by_contour, kw, role="floors", dry=dry_run,
                       measured=measured, отдано=отдано, native_op="create_floor_by_contour")

    # ── THE SLAB STANDS: a wall or a column
    if nz <= 1.0 - _AXIS_COS:
        отрезок = _segment_of(plan)
        if отрезок is None:
            return _stay(shape, "axis_not_recoverable", measured)
        a, b, L, (ux, uy) = отрезок
        measured["длина_мм"] = round(L, 3)
        # HALF-THICKNESS INWARD FROM THE BODY — ONE law for two rules. A
        # face is a SIDE of the body; `create_wall` takes the AXIS line,
        # `create_column` takes the CENTER, and both sit half a thickness
        # away from the face. The inward direction is against the normal,
        # because `rhino.faces`'s normal points outward. A second instance
        # of this same law cost exactly the mistake it was found by: a
        # column's center was taken from the FACE and ended up half a
        # thickness off — 400x400 at x0=8000 gave 8000.0 instead of 8200.0.
        сдвиг = (-float(n[0]) * t / 2.0, -float(n[1]) * t / 2.0)
        # The plan extent belongs to the BODY, not to the face: the face is
        # vertical, its projection onto the plan is a segment, and a
        # "width" taken from it loses the thickness.
        ширина = max(L, t)
        if L >= WALL_SLENDERNESS * t:
            sel, отдано = _type_selector(type, type_param, t, tol_mm)
            kw = {"p0_mm": [round(a[0] + сдвиг[0], 6), round(a[1] + сдвиг[1], 6)],
                  "p1_mm": [round(b[0] + сдвиг[0], 6), round(b[1] + сдвиг[1], 6)],
                  "height_mm": round(body_z1 - body_z0, 6), "level": level}
            if not dry_run:
                kw["base_offset_mm"] = round(body_z0 - level_z, 6)
                measured["placement"]["anchor"] = "base_and_height"
            if sel is not None:
                kw["type"] = sel
            if id:
                kw["id"] = id
            return _native(shape, _dsl.create_wall, kw, role="walls", dry=dry_run,
                           measured=measured, отдано=отдано, native_op="create_wall")
        if ширина > MAX_COLUMN_PLAN_MM:
            return _stay(shape, "not_slender", measured, l=L, t=t,
                         k=WALL_SLENDERNESS, w=ширина, max=MAX_COLUMN_PLAN_MM)
        if symbol is None:
            return _stay(shape, "column_needs_symbol", measured)
        cx = (a[0] + b[0]) / 2.0 + сдвиг[0]
        cy = (a[1] + b[1]) / 2.0 + сдвиг[1]
        kw = {"xy": [round(cx, 6), round(cy, 6)], "level": level,
              "symbol": symbol}
        if not dry_run:
            # A separate authored upper level is preferred when unambiguous.
            # Otherwise the known base level plus an explicit top offset
            # expresses the same absolute top; the symbol's default never does.
            top, top_reason, _ = _level_from_program(body_z1)
            if top_reason is None:
                top, top_z = _resolve_level(top)
            else:
                top, top_z = level, level_z
            kw.update(base_offset_mm=round(body_z0 - level_z, 6),
                      top_level=top, top_offset_mm=round(body_z1 - top_z, 6))
            measured["placement"].update(anchor="base_and_top",
                                         top_level_elevation_mm=top_z)
        if id:
            kw["id"] = id
        # FOR A COLUMN, THE WHOLE SECTION IS CEDED TO THE TYPE, and this must
        # be named: `NewFamilyInstance` places a type-size, and the section
        # belongs to it entirely. There is no "the dimension picked the
        # type" branch here as there is for thickness: a section is TWO
        # numbers, and grounding has no lookup by a pair.
        return _native(shape, _dsl.create_column, kw, role="columns", dry=dry_run,
                       measured=measured, native_op="create_column",
                       отдано={"сечение_мм": [round(L, 3), round(t, 3)],
                               "как": "типоразмер назван автором, его сечение "
                                      "не проверено"})

    # ── THE SLAB IS SLOPED: a roof (thickness already checked above, one check for all)
    уклон = round(math.degrees(math.acos(min(1.0, nz))), 6)
    measured["уклон_град"] = уклон
    if not dry_run:
        return _stay(shape, "roof_placement_unresolved", measured)
    outline: list[float] = []
    for x, y in plan:
        outline.extend([round(x, 6), round(y, 6)])
    # The slope is hung on the LOWEST edge of the contour, and that edge is
    # computed, not chosen: `FootPrintRoof` raises the roof FROM the edge
    # that is given the slope. The wrong edge, and the roof goes the other
    # way — exactly the plausible-but-wrong outcome the slope-list length
    # check in `authoring_validation` guards against.
    рёбра = [(i, (zs[i] + zs[(i + 1) % len(zs)]) / 2.0) for i in range(len(zs))]
    нижнее = min(рёбра, key=lambda e: e[1])[0]
    slopes = [None] * len(plan)
    slopes[нижнее] = уклон
    kw = {"outline": outline, "level": level, "slopes": slopes}
    if type is not None:
        kw["type"] = type
    if id:
        kw["id"] = id
    return _native(shape, _dsl.create_roof, kw, role="roofs", dry=dry_run,
                   measured=measured)


def native_route(role: str) -> str:
    """What honestly makes this kind — from the same table the mesh refusal reads."""
    return IMPERSONATION_ROUTES[role]


# ─────────────────────────────────────────── READING WHAT WAS ALREADY WRITTEN

def classify(shape: Any, **kw: Any) -> dict:
    """A geometric native hypothesis, without changing the program or the shape.

    Classification uses `promote`'s geometric rules, but does not resolve
    the level, does not check the expressibility of placement, and does not
    call Revit. `status=geometry_candidate`, `verified=False`, `retracted=0`
    do not promise that a subsequent `promote` will pass the placement
    checks. For example, a sloped slab can be a roof candidate while not yet
    having a native placement.
    """
    kw.setdefault("level", None)
    return promote(shape, dry_run=True, **kw)


def unpromoted(ops: Any) -> list[dict]:
    """WHAT STAYED GEOMETRY IN THE PROGRAM, AND WHAT IT WOULD HAVE BECOME.

    The input is a list of operations, the output is one record per body
    with no BIM meaning:

        {"op": name, "id": address,
         "role": kind | None,        what it would become after `promote`
         "reason": reason | None,    what it would NOT become, if it would not
         "reason_key": key|None,     the same reason as a KEY, for counting
         "measured": {...},          what was read from the shape
         "unreadable": string|None}  why the shape was not read AT ALL

    🔴 `unreadable` IS NOT AN OMISSION, AND THAT IS THE WHOLE POINT OF THE
    FIELD. The body of `create_solid_revolve` was not built by us as a mesh,
    and saying "it would have become a wall" about it would mean telling a
    tale. A silent omission would make the report more confident the less
    the environment can actually do — exactly the direction of dishonesty
    this tree has already paid for with the `design_check` text about
    HAB010.

    DESCENDING INTO GROUP MEMBERS is mandatory: in a real building, 82.6% of
    operations live inside groups, and a top-level-only walk would go blind
    on exactly the buildings that matter. The same shape is closed in the
    tree at `_hab000_names_the_real_cause`.
    """
    только_геометрия = _geometry_only_ops()
    out: list[dict] = []

    def _обойти(items: Any) -> None:
        for op in items or []:
            if not isinstance(op, dict):
                continue
            name = op.get("op")
            if name == "create_group":
                _обойти(op.get("members"))
                continue
            if name not in только_геометрия:
                continue
            shape = _rhino._shape_from_op(op)
            if shape is None:
                out.append({
                    "op": name, "id": op.get("id"), "role": None,
                    "reason": None, "reason_key": None, "measured": {},
                    "unreadable": (f"тело рода `{name}` среда мешем не строила "
                                   f"— читать его форму нечем, и род её здесь "
                                   f"не называется")})
                continue
            итог = classify(shape)
            out.append({"op": name, "id": op.get("id"), "role": итог["role"],
                        "reason": итог["reason"],
                        # A KEY alongside the text: the receipt gets trimmed
                        # first, and counting findings by text would mean
                        # counting by wording. The same law by which
                        # self-verification places rule CODES, not their
                        # messages.
                        "reason_key": итог.get("reason_key"),
                        "measured": итог["measured"], "unreadable": None})

    _обойти(ops)
    return out
