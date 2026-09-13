"""KIR RELATE — ADDRESSING FROM GRIDS (an ADDRESS sub-language, not new operations).

Spec: ``RELATE_SPEC_2026-08-03.md``. The operation registry DOES NOT GROW: an
address is a FORM of a point parameter's VALUE, exactly like ``region`` for
CONTOUR.

WHAT THIS IS. A point in the plan can be written in two ways:

    [12000, 6000]                       — a literal, as always
    {"at_grid": ["Б", "3"]}             — the intersection of two MODEL grids
    {"at_grid": [{"grid": "Б", "offset_mm": 200, "toward": "В"}, "3"]}

The address is resolved at the GROUND stage (a pure function of the
snapshot); a literal point goes on to the emitter. Trigonometry happens at
compile time; the emitted C# sees only numbers. This is FIXED DECISION #1
of the CONTOUR sub-language, from which RELATE grew, and it is not
revisited here.

────────────────────────────────────────────────────────────────────────────
THE GRAMMAR IS CLOSED. Three nodes, no composition.
────────────────────────────────────────────────────────────────────────────

    <address-xy>   ::= { "at_grid": [ <line>, <line> ] }
    <address-xyz>  ::= { "at_grid": [ <line>, <line> ], "z_mm": <number> }

    <line>         ::= <name>                                   // short form
                     | { "grid": <name> }                       // same, full
                     | { "grid": <name>, "offset_mm": <number>, "toward": <name> }

Closedness is MACHINE-ENFORCED, not just stated: the parser does not guess
from the fields, it looks up the SET OF KEYS in the registries
:data:`ADDRESS_FORMS` / :data:`LINE_FORMS`. An unfamiliar set is a
refusal that the registry PRINTS. A new expression form = a new row in
the registry + its semantics in the resolver; the parser cannot guess by
construction.

There is no composition and there will not be: neither "the midpoint
between A and Б", nor "A plus Б", nor "parallel to A". There is no
evaluator here — the resolver is the intersection of two lines from the
snapshot, and nothing more. The very first binary operator breaks SPEC
12.3 (the same lock as ``macros._REF_RE``).

────────────────────────────────────────────────────────────────────────────
SECOND FAMILY OF NODES: ADDRESS FROM AN ELEMENT (09.08.2026)
────────────────────────────────────────────────────────────────────────────

    <address-xy>   ::= { "at_element": <selector>, "point": <point> }
    <address-xyz>  ::= { "at_element": <selector>, "point": <point>,
                         "z": <elevation> }
                     | { "at_element": <selector>, "point": <point>,
                         "z_mm": <number> }

    <selector>     ::= { "by": "ref", "value": "<id of an earlier op in the program>" }
    <point>        ::= "start" | "end" | "center"
    <elevation>    ::= "base" | "top" | "axis"

WHY. The ban on composition is about BINARY OPERATORS OVER GRID LINES,
and it says nothing about an address from an element. Yet the hole here
is exactly the same kind that ``at_grid`` closed: to place a beam on top
of a column, the model has to ADD the level's elevation to the top
offset and RE-DERIVE the column's plan — with numbers it wrote itself one
line above. That is precisely the class of arithmetic the address
sub-language exists to remove.

WHAT IS CLOSED HERE THE SAME WAY AS IN ``at_grid``. Three registries, and
the parser guesses from none of them: :data:`ELEMENT_ADDRESS_FORMS` (the
node's key set), :data:`PLAN_POINTS`/:data:`ELEVATIONS` (closed
dictionaries of names), and :data:`ELEMENT_GEOMETRY` — a TABLE OF
OPERATIONS whose elements have named geometry. An unfamiliar set, an
unfamiliar name, a missing table row — a refusal that PRINTS the
registry. There is no composition here either: a node takes EXACTLY ONE
selector, and expressing "the midpoint between A and Б" with it is
impossible by construction — the grammar has no second operand.

WHERE THE NUMBERS COME FROM — AND WHY ONLY ``by: ref``. From THE PROGRAM
ITSELF: the addressed element is created earlier in this same program,
and the author has ALREADY WRITTEN its plan, level, and offsets. This is
a pure function of the program's text plus the snapshot's ``levels`` pool
(the level's elevation) — that is, exactly the same discipline as
``at_grid``.

The other forms of the frozen dialect (``element_id``, ``name``,
``family_type``, ``phase_result``, the second stage of ``face``) are
REFUSED, and the reason is MEASURED, not derived: ``open_model.GROUND_SNAPSHOT_CS``
collects TYPE pools plus three instance pools — ``levels`` (id, name,
elevation_mm), ``load_cases`` (id, name), and ``grids`` (id, name,
p0_mm, p1_mm). There is not a single row about a MODEL wall, column, or
room in the snapshot: the compiler has NO geometry of an existing
element. Reading it in from the emitted C# would mean bringing
trigonometry back into Revit and killing the point's literalness; hence
an honest refusal here rather than half a mechanism (see
:data:`ELEMENT_SELECTOR_RU`).

WHAT DOES NOT EXIST AND WHY — BY NAME, in :data:`ELEMENT_REJECTED`. An
empty table row would send the author off to guess, so the refusal names
the reason specifically for the operation it was asked about.

────────────────────────────────────────────────────────────────────────────
THREE LATENT DEFECTS OF THE SHIPPED MECHANISM THAT THIS MODULE FIXES
────────────────────────────────────────────────────────────────────────────

Addressing from grids has existed since 17.07 in ``contour.resolve_anchor``.
Generalizing it had to mean FIXING it, otherwise a foundational defect
would have poisoned twenty-two new parameters instead of one.

**D1. THE WORLD FRAME OF THE OFFSET.** The shipped form
``{"at_grid": [...], "offset_mm": [dx, dy]}`` shifts the point in WORLD
coordinates. A corpus measurement of 03.08: in ``sklnk_eom`` ALL 57 grids
run at 156.1° and 66.1° — not one coincides with a world axis. There,
saying "200 mm from grid 25" with a world ``[dx,dy]`` is simply
impossible: the author has to compute
``[200·cos66.1°, 200·sin66.1°]`` themselves — exactly the arithmetic the
sub-language is supposed to remove. The world frame is not a
simplification, it is an unremoved barrier.

    FIXED BY: the node ``{"grid": ..., "offset_mm": <number>, "toward": ...}``.
    The offset is a NUMBER along the perpendicular to the GRID ITSELF, the
    direction is read FROM THE MODEL (the sign of the perpendicular
    pointing toward the ``toward`` line). The world pair ``[dx,dy]``
    remains ONLY for ``region`` (see :data:`LEGACY_ADDRESS_FORMS`) and is
    REFUSED in the new slots.

**D2. SILENT PICK ON A NAME COLLISION.** ``contour.py:86`` used to build
``{name: g for g in pool}`` — a dict comprehension silently keeps the
LAST row on a key collision. The same kind of thing as ``.FirstOrDefault()``,
against which the NAMED DEFAULT was written. The Revit API's index
documents NO guarantee whatsoever of ``Grid.Name`` uniqueness (the
``Grid`` type has seven members, ``Name`` is inherited from ``Element``).

    FIXED BY: :data:`GRID_AMBIGUOUS` (KIR-G109) with ``{id, name}`` for
    each grid.

**D3. CONDITIONING WAS NOT CHECKED.** ``_line_intersection`` used to
refuse only when ``|den| < 1e-9`` — for two 30-meter grids that is an
angle on the order of 1e-15 rad. A pair of "almost parallel" grids gave a
point, and that point is noise.

    FIXED BY: :data:`MIN_GRID_ANGLE_DEG` (see the derivation at the
    constant itself) and :data:`GRID_NO_INTERSECTION` (KIR-G110), which
    NAMES the angle.

────────────────────────────────────────────────────────────────────────────
WHAT THIS MODULE DOES NOT PROVE — IN PLAIN TEXT
────────────────────────────────────────────────────────────────────────────

An address is resolved AGAINST THE SNAPSHOT, taken BEFORE the transaction.
Between the snapshot and the write a grid can move (a co-author, Reload
Latest, a re-link) — and the element will land where the grid no longer
is, while the entire postcondition passes green: the op's witness checks
the element against the LITERAL that WE ourselves derived.

This is NOT a new hole: ``at_grid`` has shipped with exactly this
remainder in CONTOUR since 17.07. RELATE INHERITS it and does not expand
the class of the unpromised — not a single new obligation about POSITION
appears here, only the number's origin changes, not its verifiability
(the ``location_mm``/``endpoint_mm`` witnesses of each op check the point
exactly as before).

The remainder is closed by the ``grid_anchor`` witness (spec §6) — a
separate wave: it requires ``tolerances["grid_anchor_mm"]`` on twelve
ops, rows in their ``post``, obligations in ``translation_cert``, and
addressing programs in the certifying corpus (otherwise
``test_tolerance_provenance`` L4/L5 fail red, legitimately). It is NOT
done here, and that is stated, not left unsaid.
"""
from __future__ import annotations

import difflib
import math
from typing import Any, Optional

from kir.diag import Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS
from kir.emit_utils import is_finite_number
#: THE COORDINATE LIMIT IS TAKEN FROM THE AUTHORITY, NOT FROM THE EMITTER
#: (01.09.2026). This used to have a lazy `from kir.authoring_validation
#: import _COORD_LIMIT_MM` in two places, and that name is itself a plain
#: alias for `registry_base.COORD_LIMIT_MM`
#: (`authoring_validation.py:194`). The laziness was hiding not the cost
#: of the import, but a DECISION ABOUT LAYERING: through this edge the
#: value layer reached all the way to emission, and the live-plan renderer
#: — all the way to the compiler (measured by walking
#: `capability_graph`: 10 out of 15 resolvers). A reader must ask
#: whoever DECLARES the value; the alias at the emitter remains for its
#: own readers.
from kir.registry_base import COORD_LIMIT_MM as _COORD_LIMIT_MM

# ── refusal codes ────────────────────────────────────────────────────────────
#
# A namespace measurement of 04.08 (grepping ``KIR-[A-Z]\d+`` across
# ``kukai/``): the G1xx block is occupied by G101..G104, G106, G107; G105
# belonged to ``contour.GRID_ANCHOR_UNRESOLVED`` and is SPLIT here into
# three codes — not out of love for numbers, but because "name not
# found", "no geometry", and "no intersection" lead to THREE DIFFERENT
# REPAIRS, and one code for three repairs sends the author off to guess.
# There are exactly as many codes as there are distinct repairs.
GRID_NOT_FOUND = "KIR-G108"          # the grid's name is not in the grids pool
GRID_AMBIGUOUS = "KIR-G109"          # several grids carry this name (D2)
GRID_NO_INTERSECTION = "KIR-G110"    # the pair is parallel / angle < threshold (D3)
GRID_NO_GEOMETRY = "KIR-G111"        # the grid exists, but has no straight-line geometry (an arc)
GRID_TOWARD_INVALID = "KIR-G112"     # toward is not fit to be a "direction"

# ADDRESS FROM AN ELEMENT (09.08). The same law of "a code per repair, not
# per location": four codes, because there are four DIFFERENT next moves.
ELEMENT_REF_UNKNOWN = "KIR-G113"      # the reference is not to an earlier op of THIS program
ELEMENT_NOT_ADDRESSABLE = "KIR-G114"  # the elements of THIS operation have no address at all
ELEMENT_PART_INVALID = "KIR-G115"     # the operation is addressable, but NOT by this point/elevation
ELEMENT_CAPTURE_GAP = "KIR-G116"      # the level's elevation is not in the snapshot (a capture gap)

#: The grid pool is empty / there is no snapshot — the ground codes are
#: reused as-is (the repair is different: not "fix the name", but "build
#: the grids first"). Imported lazily so that ``relate`` does not pull in
#: ``ground`` (which pulls in ``spec``).
GROUND_EMPTY_POOL = "KIR-G104"

#: THE CONDITIONING THRESHOLD IS A DERIVATION, not a matter of taste (D3).
#:
#: Rounding the literal in emission, ``round(x, 2)``, gives 0.005 mm. The
#: amplification of error at an intersection angle α equals ``1/sin(α)``:
#:
#:     α = 1°    -> 0.005 × 57.3  = 0.29 mm
#:     α = 0.1°  -> 0.005 × 573   = 2.87 mm
#:     α = 0.01° -> 0.005 × 5730  = 28.6 mm
#:
#: The threshold is chosen so that the propagated error stays strictly
#: LESS THAN A MILLIMETER. A corpus measurement of 03.08 (3346 non-
#: parallel pairs across 9 grid sets) confirms it is FREE: the minimum
#: angle observed is 7.5°, pairs below 5° — zero. Revisit at the first
#: building with a grid pair in the 1..7.5° range.
#:
#: ONE NUMBER, TWO MEANINGS, and that is not a coincidence: "the pair
#: intersects" and "the pair is parallel" must be COMPLEMENTS of each
#: other, otherwise there would be a pair that is neither one nor the
#: other. Angle >= threshold -> counted as an intersection; angle <
#: threshold -> the pair is considered parallel (and fit for ``toward``).
MIN_GRID_ANGLE_DEG = 1.0

#: The offset ceiling is the same bound as ``move_elements.delta_mm``
#: (100 m per component). The measured maximum offset of a column from a
#: grid in the corpus is 2125 mm, i.e. the ceiling has a 47× margin.
MAX_OFFSET_MM = 100_000.0

#: Grid name: 1..64 characters after trim. The upper bound is the same
#: length as ``macros`` uses for a track name; a grid with a 65-character
#: name did not occur in any of the corpus's 9 sets (maximum observed: 4
#: characters).
MAX_GRID_NAME_LEN = 64

#: Below this length a grid HAS NO DIRECTION, and the perpendicular is
#: undefined. Matches ``contour._EDGE_TOL`` — the same "zero-edge"
#: threshold.
_MIN_GRID_LENGTH_MM = 1.0

#: Below this distance two parallel lines COINCIDE, and "toward" is
#: undefined. The order of magnitude is the literal's rounding (0.005 mm)
#: × a margin.
_MIN_TOWARD_DISTANCE_MM = 1.0


# ── CLOSED FORM REGISTRIES ───────────────────────────────────────────────────
#
# The parser does NOT GUESS: it takes ``frozenset(node)`` and looks it up
# here. This is also where the REFUSAL TEXT comes from — meaning an
# author who misses the grammar sees the whole grammar, not "unknown
# field".

#: Forms of the <address> node. The key is the object's set of keys, the value is (dims, label).
ADDRESS_FORMS: dict[frozenset, tuple[int, str]] = {
    frozenset({"at_grid"}): (2, '{"at_grid": [<линия>, <линия>]}'),
    frozenset({"at_grid", "z_mm"}):
        (3, '{"at_grid": [<линия>, <линия>], "z_mm": <число>}'),
}

#: A LEGACY DOOR, opened BY NAME and to exactly one consumer — ``region``
#: of the CONTOUR sub-language, where this form has shipped since 17.07
#: and sits in the goldens. This is D1 in pure form; in the new slots it
#: is CLOSED, and a refusal against it names the replacement. The door
#: will close once ``region`` moves to the node-based offset — a separate
#: piece of work that moves the goldens.
LEGACY_ADDRESS_FORMS: dict[frozenset, tuple[int, str]] = {
    frozenset({"at_grid", "offset_mm"}):
        (2, '{"at_grid": [<линия>, <линия>], "offset_mm": [dx, dy]}  '
            '(мировая рамка, только region)'),
}

#: Forms of the <line> node. The short form (a bare string) is handled
#: separately: it has no keys.
LINE_FORMS: dict[frozenset, str] = {
    frozenset({"grid"}): '{"grid": <имя>}',
    frozenset({"grid", "offset_mm", "toward"}):
        '{"grid": <имя>, "offset_mm": <число>, "toward": <имя>}',
}

#: Exceptions to the rule "every pt_xy/pt_xyz is addressable".
#:
#: ``move_elements.delta_mm`` is a SHIFT, not a position: "move to the
#: intersection of A and 3" means nothing. It carries the ``pt_xyz`` kind
#: only because it reuses its form in the schema (see the comment in
#: ``authoring_validation``), and this is exactly the case where the kind
#: speaks to FORM, not to MEANING.
#:
#: ``create_face_wall.face_normal`` is the DIRECTION of a face selection,
#: not a point. Allowing an address there would turn the grid
#: intersection into a normal vector and could silently pick a different
#: face. Found on the merged registry of 10.08: the new op inherited
#: addressability solely because of the shared ``pt_xyz`` kind.
#:
#: The list is CHECKED: :func:`_lint` fails if a pair disappears from the
#: registry or changes kind. An exception that has stopped pointing at
#: anything is a rule nobody enforces.
ADDRESS_EXCLUDED: frozenset = frozenset({
    # `move_elements.delta_mm` STAYS here, and that is a decision, not a
    # leftover. The value is a SHIFT: in millimeters (unlike a direction),
    # but it is not tied to a frame, and subtracting the local frame's
    # origin from it is equally wrong. MEASURED 21.08.2026: `_shift` turns
    # [1000, 500, 0] into [0, 0, 0]. A kind of its own (`delta_xyz`) was
    # DELIBERATELY NOT set up: `move_elements` is not mentioned in
    # `kir/decompile` even once, meaning this value never reaches `_shift`
    # at all. A kind for an unreachable path is code nobody will be able
    # to verify. This note is here in case the path appears: then a kind
    # is needed where ROUNDING in mm is YES but a frame shift is NO — i.e.
    # `MM_KINDS` will have to be split into "what we round" and "what we
    # shift", today it is one set.
    ("move_elements", "delta_mm"),
    # `create_face_wall.face_normal` was removed from here on 21.08.2026
    # by the same argument and in the same move as `place_family.ref_dir`:
    # a normal is a ray, not a position, and that is a property of the
    # KIND (`dir_xyz`), not of the exceptions list for addresses. Found by
    # MEASUREMENT, not by reading: the same `_shift` run that exposed
    # ref_dir showed the same thing here:
    # [-1, 0, 0] -> [-1001, -500, 0].
    # 🔴 `place_family.ref_dir` WAS REMOVED FROM HERE ON 21.08.2026, AND
    # THIS IS NOT A WEAKENING, BUT A FIX. It used to say: "the DIRECTION of
    # the reference on the work plane, not a position… millimeters in a
    # direction field are a different quantity." The argument is entirely
    # correct — and precisely for that reason it belongs to the KIND, not
    # to the exceptions list. The parameter now has the kind `dir_xyz`,
    # and addressability is derived from the kind (`addressable_params`),
    # meaning there is nothing left to exclude.
    #
    # While the knowledge lived HERE, it protected ONE question — "can an
    # address from grids be given" — and did not protect the neighboring
    # one: `decompile.program_source._shift` subtracted the local frame's
    # origin from the direction and turned [-1, 0, 0] into
    # [-1001, -500, 0]. One carrier does not stretch over two questions;
    # a kind stretches over both.
})


# ── REGISTRIES OF THE SECOND FAMILY: ADDRESS FROM AN ELEMENT ──────────────

#: Forms of the <address-from-element> node. The key is the object's set
#: of keys, the value is (dims, label). The same technique as
#: :data:`ADDRESS_FORMS`: the registry is narrowed DOWN TO the
#: parameter's dimensionality, so the refusal prints the form that fits
#: EXACTLY HERE, not the whole list.
ELEMENT_ADDRESS_FORMS: dict[frozenset, tuple[int, str]] = {
    frozenset({"at_element", "point"}):
        (2, '{"at_element": {"by": "ref", "value": "<id опа>"}, '
            '"point": "start|end|center"}'),
    frozenset({"at_element", "point", "z"}):
        (3, '{"at_element": {"by": "ref", "value": "<id опа>"}, '
            '"point": "start|end|center", "z": "base|top|axis"}'),
    frozenset({"at_element", "point", "z_mm"}):
        (3, '{"at_element": {"by": "ref", "value": "<id опа>"}, '
            '"point": "start|end|center", "z_mm": <число>}'),
}

#: PLAN stations. The dictionary is closed: a name not present here is a refusal with the list.
PLAN_POINTS: tuple[str, ...] = ("start", "end", "center")

#: Elevations. ``axis`` — the elevation of the STATION ITSELF for a
#: volumetric axis element (a beam, a pipe): it has no "bottom" and "top"
#: in the program, the section thickness lives in the TYPE, and the type
#: is resolved against the document. ``base``/``top`` — for elements
#: whose height the program sets by levels.
ELEVATIONS: tuple[str, ...] = ("base", "top", "axis")

#: THE ONLY stage-1 form this node accepts, and the text with which it
#: refuses everything else. A separate constant because the text is a
#: MEASUREMENT, and it must be readable next to the decision, not hidden
#: inside an f-string.
ELEMENT_SELECTOR_RU = (
    'адресуется только элемент, созданный ЭТОЙ ЖЕ программой: '
    '{"by": "ref", "value": "<id опа выше>"}. Существующий элемент модели '
    '(element_id / name / family_type / phase_result / face) адресовать '
    'нельзя, и это не забывчивость: снапшот ground несёт пулы ТИПОВ и три '
    'пула экземпляров — levels, load_cases, grids. Геометрии стены, колонны '
    'или помещения МОДЕЛИ в нём нет ни одной строки, а дочитывать её в '
    'эмитируемом C# запрещено — тогда точка перестала бы быть литералом и '
    'тригонометрия уехала бы в Revit. Задайте такую точку литералом [x, y]')

#: TABLE OF ADDRESSABLE GEOMETRY. A row means "this operation's element
#: has these named points and these elevations, and here is WHICH FIELDS
#: they are derived from."
#:
#: The table is EXPLICIT, not derived from the parameter kind, and that
#: is not laziness. The ``pt_xyz`` kind on
#: ``create_opening.p0_mm/p1_mm`` means TWO CORNERS of a rectangle, not
#: an axis; "start/end" there would read as the axis's endpoints and
#: would lie silently. The kind speaks to the FORM of the value, while
#: the table speaks to the MEANING of the element, and the second cannot
#: be derived from the first (the same argument as with
#: :data:`ADDRESS_EXCLUDED`).
#:
#: Every row cost reading the EMITTER, and here is what was read
#: (09.08.2026):
#:
#: * ``plan="axis"`` — the pair of points IS the element's axis. Verified
#:   against the creation call:
#:   ``Wall.Create(doc, Line.CreateBound(P(x0,y0,0), P(x1,y1,0)),…)``
#:   (``authoring.py``), ``Line.CreateBound(P(x0,y0,z0), P(x1,y1,z1))``
#:   for a beam (``struct_emit.emit_beam``),
#:   ``Pipe.Create/Duct.Create/CableTray.Create/
#:   Conduit.Create(…, P(x0,y0,z0), P(x1,y1,z1), …)``.
#: * ``dims=3`` on a row means the station's Z IS PRESENT IN THE PROGRAM
#:   ITSELF and is the model's ABSOLUTE elevation in mm. This is a
#:   MEASUREMENT, not a convention: all the listed calls pass z through
#:   ``P()`` (mm -> feet) WITHOUT subtracting ``Level.Elevation``. The one
#:   known exception (``place_family``, where the emitter writes
#:   ``U(z) - __lv.Elevation``) is not in the table and is named in
#:   :data:`ELEMENT_REJECTED`.
#: * ``base``/``top`` — only where the program sets BOTH elevations:
#:   ``base = level.elevation + base_offset_mm``,
#:   ``top  = top_level.elevation + top_offset_mm``.
#:   For a wall that is ``WALL_BASE_OFFSET`` and the pair
#:   ``WALL_HEIGHT_TYPE`` + ``WALL_TOP_OFFSET``; for a column —
#:   ``FAMILY_BASE_LEVEL_OFFSET`` and the pair
#:   ``FAMILY_TOP_LEVEL_PARAM`` + ``FAMILY_TOP_LEVEL_OFFSET`` (read
#:   directly in the sloped branch of ``authoring.py``:
#:   ``top_z = __ctl.Elevation + U(off)``). For a sloped column, the plan
#:   station also depends on the elevation: ``base`` takes ``xy``, ``top``
#:   takes ``top_xy``. A flat address and ``z_mm`` are refused for it:
#:   without picking an end of the axis there is no single plan point.
#:
#: WHY ``top`` REQUIRES ``top_level`` AND REFUSES WITHOUT IT. Without a
#: top binding, the wall's height arrives from the REGISTRY DEFAULT
#: (``height_mm`` = 3000 mm, substituted silently — a closed list,
#: ``tests/test_silent_defaults.py``), while a column's height comes from
#: a type size that is not in the program at all. Answering "top = bottom
#: + 3000" would mean passing off, as the author's own words, a default
#: they never uttered — exactly the defect that caused the height witness
#: to roll back CORRECTLY built facade walls (measurement of 29.07).
ELEMENT_GEOMETRY: dict[str, dict] = {
    "create_wall":       {"plan": "axis", "fields": ("p0_mm", "p1_mm"),
                          "dims": 2, "z": ("base", "top")},
    "create_grid":       {"plan": "axis", "fields": ("p0_mm", "p1_mm"),
                          "dims": 2, "z": ()},
    "create_column":     {"plan": "point", "fields": ("xy",),
                          "dims": 2, "z": ("base", "top")},
    "create_beam":       {"plan": "axis", "fields": ("p0_mm", "p1_mm"),
                          "dims": 3, "z": ("axis",)},
    "create_pipe":       {"plan": "axis", "fields": ("p0_mm", "p1_mm"),
                          "dims": 3, "z": ("axis",)},
    "create_duct":       {"plan": "axis", "fields": ("p0_mm", "p1_mm"),
                          "dims": 3, "z": ("axis",)},
    "create_conduit":    {"plan": "axis", "fields": ("p0_mm", "p1_mm"),
                          "dims": 3, "z": ("axis",)},
    "create_cable_tray": {"plan": "axis", "fields": ("p0_mm", "p1_mm"),
                          "dims": 3, "z": ("axis",)},
}

#: REJECTED BY NAME. The absence of a row in :data:`ELEMENT_GEOMETRY` is a
#: fact, not an explanation: an author who asked about a room must learn
#: WHY, otherwise they will try again the same way. An empty table of
#: reasons would turn a closed grammar into "unknown field".
ELEMENT_REJECTED: dict[str, str] = {
    "create_space": (
        "у пространства ОВК `xy` — это ТОЧКА ПОСЕВА для "
        "Document.NewSpace, тот же род аргумента, что у помещения строкой "
        "ниже: Revit ставит пространство в ту область, куда точка попала, и "
        "центр построенного объёма к ней отношения не имеет. Контура "
        "пространства в программе нет вовсе"),
    "create_room": (
        "у помещения `xy` — это ТОЧКА ПОСЕВА для Document.NewRoom, а не центр "
        "помещения: Revit ставит помещение в ту ячейку, куда точка попала, и "
        "центр построенного помещения к ней отношения не имеет. Назвать её "
        "«center» значило бы соврать. Контура помещения в программе нет вовсе"),
    "create_floor": (
        "форма перекрытия — МНОГОУГОЛЬНИК (`outline`), у него нет ни начала, "
        "ни конца, а «центр» многоугольника требует правила центроида, "
        "которого никто не мерил (у невыпуклого контура центр масс лежит вне "
        "плиты)"),
    "create_floor_by_contour": (
        "типизированный эскиз — тот же МНОГОУГОЛЬНИК, что и у create_floor, "
        "плюс дуговые рёбра: у него нет ни начала, ни конца, а «центр» требует "
        "правила центроида, которого никто не мерил"),
    "create_ceiling": (
        "форма потолка — МНОГОУГОЛЬНИК (outline либо типизированный эскиз), "
        "и довод тот же, что у create_floor: ни начала, ни конца, а центр "
        "невыпуклого контура лежит вне элемента"),
    "create_roof": (
        "форма кровли — МНОГОУГОЛЬНИК, и довод тот же, что у create_floor; "
        "вдобавок у скатной кровли отметка меняется вдоль контура, и одна "
        "«отметка элемента» её не описывает"),
    "create_extrusion_roof": (
        "`p0_mm`/`p1_mm` задают СЛЕД РАБОЧЕЙ ПЛОСКОСТИ на плане, а не ось "
        "и не границу построенной кровли. Тело задают профиль в координатах "
        "этой плоскости и границы выдавливания вдоль её нормали; назвать "
        "start/end точками элемента означало бы выдать служебную линию за "
        "геометрию кровли"),
    "create_opening": (
        "`p0_mm`/`p1_mm` у проёма — ДВА ПРОТИВОПОЛОЖНЫХ УГЛА прямоугольника, а "
        "не концы оси. Имена start/end читались бы как ось и врали бы молча"),
    "place_family": (
        "операция несёт ДВЕ формы сразу (точка `xyz` либо кривая `p0_mm`/"
        "`p1_mm`), и у точечной формы `xyz` — ТОЧКА ВСТАВКИ семейства, чьё "
        "отношение к видимому телу задаёт само семейство, а не программа. "
        "Вдобавок это единственная известная операция, у которой эмиттер "
        "пишет `U(z) - __lv.Elevation`, то есть кадр отсчёта Z у неё свой"),
    "create_stairs": (
        "`p0_mm`/`p1_mm` задают ОДИН прямой марш, а построенная лестница — это "
        "марши, площадки и ограждения, чьи концы Revit расставляет сам"),
    # A SECOND FLIGHT — its own reason, not "same as the staircase above".
    # For that one, Revit places the endpoints, because the element is
    # composite; here the element is single, but `p0_mm`/`p1_mm` is the
    # ORDERED axis of the flight, and Revit fits the built `StairsRun` to
    # the staircase's own rules (riser count, width, joining the landing).
    # Plus a measurement from the second-flight wave: nothing reads the
    # binding back FROM a built `StairsRun`, so there is nowhere to get an
    # "address of the built element" from here, even after construction.
    "create_stairs_run": (
        "`p0_mm`/`p1_mm` — ЗАКАЗАННАЯ ось марша, а построенный `StairsRun` "
        "Revit подгоняет под правила своей лестницы (подступенки, ширина, "
        "стык с площадкой); обратно из `StairsRun` привязка не читается"),
    "create_truss": (
        "`p0_mm`/`p1_mm` — линия ОПОРНОЙ КРИВОЙ фермы; положение поясов и "
        "раскосов задаёт семейство фермы, и «начало» построенного элемента с "
        "концом этой линии не совпадает"),
    "create_path_of_travel": (
        "путь эвакуации ПРОКЛАДЫВАЕТ REVIT: `p0_mm`/`p1_mm` — это запрос "
        "«откуда куда», а построенная линия огибает препятствия, и её концы "
        "программе неизвестны"),
    "create_point_load": (
        "нагрузка — не тело: адресоваться от точки её приложения можно, но "
        "надобности замером не подтверждено; строка откроется первым живым "
        "случаем, а не заранее"),
    "create_line_load": (
        "нагрузка — не тело: адресоваться от концов линии её приложения можно, "
        "но надобности замером не подтверждено; строка откроется первым живым "
        "случаем, а не заранее"),
    "create_pipe_placeholder": (
        "заготовка выражает ту же ось, что и труба, но её единственный смысл — "
        "быть ЗАМЕНЁННОЙ на настоящую трассу; адрес от временного элемента "
        "открывать без живого случая незачем"),
    "create_duct_placeholder": (
        "заготовка выражает ту же ось, что и воздуховод, но её единственный "
        "смысл — быть ЗАМЕНЁННОЙ на настоящую трассу; адрес от временного "
        "элемента открывать без живого случая незачем"),
    "create_foundation": (
        "`xy` есть только у рода `isolated`; у рода `slab` формы вообще "
        "другая, и одна строка таблицы описывала бы два разных элемента"),
    "create_curtain_grid_line": (
        "`position_mm` — точка НА ПОВЕРХНОСТИ витража, задающая, где резать "
        "сетку; построенная линия принадлежит носителю, и её концы задаёт он"),
    "create_solid_revolve": (
        "`axis_xy_mm` задаёт ВЕРТИКАЛЬНУЮ ОСЬ ВРАЩЕНИЯ, а не точку тела: "
        "профиль лежит справа от неё и после поворота может окружать пустую "
        "ось. Назвать эту координату center/start/end означало бы молча "
        "поставить следующий элемент на служебную ось вместо геометрии"),
    # 🔴 TWO OPS THAT STOOD UNPARSED (found 21.08.2026 by the guard
    # `ElementAddressRegistriesAreClosed`, both preexisting). A "silent
    # third bucket" is exactly the empty table row that leaves the author
    # guessing.
    "author_family": (
        "`place_at` — ТОЧКА ВСТАВКИ семейства, и довод здесь дословно тот же, "
        "что у `place_family` ниже: отношение точки вставки к видимому телу "
        "задаёт САМО СЕМЕЙСТВО, а не программа. У авторского семейства это "
        "вернее вдвойне — тело только что нарисовано программой в координатах "
        "документа СЕМЕЙСТВА, и где оно окажется относительно точки вставки, "
        "решает шаблон .rft. Назвать эту координату геометрией значило бы "
        "поставить следующий элемент на служебную точку вместо тела"),
    "create_solid_sweep": (
        "`anchor_uv_mm` — координата ВНУТРИ рамки профиля (u, v), а не точка "
        "модели: она говорит, каким местом профиль сидит на пути. Мировых "
        "миллиметров в ней нет вовсе, и адрес от осей, разрешаемый в модельные "
        "миллиметры, дал бы здесь число из другой системы координат — "
        "молчаливо и правдоподобно"),
    "create_face_wall": (
        "`face_normal` — НАПРАВЛЕНИЕ отбора грани носителя, а не положение. "
        "Саму точку или контур выбранной грани программа не несёт; превращать "
        "вектор нормали в адрес либо дочитывать геометрию в эмитируемом C# "
        "означало бы молчаливо выбрать другую точку или перенести вычисление "
        "из компилятора в Revit"),
}


def _lint() -> None:
    """Invariants of the form registries — checked at import time, like ``spec._lint_registry``."""
    for keys, (dims, _sig) in {**ADDRESS_FORMS, **LEGACY_ADDRESS_FORMS}.items():
        if "at_grid" not in keys or dims not in (2, 3):
            raise AssertionError(f"ADDRESS_FORMS: битая форма {sorted(keys)}")
    for keys in LINE_FORMS:
        if "grid" not in keys:
            raise AssertionError(f"LINE_FORMS: битая форма {sorted(keys)}")
    for keys, (dims, _sig) in ELEMENT_ADDRESS_FORMS.items():
        if "at_element" not in keys or dims not in (2, 3):
            raise AssertionError(
                f"ELEMENT_ADDRESS_FORMS: битая форма {sorted(keys)}")
    from kir import spec
    # THE ADDRESSABLE-GEOMETRY TABLE IS CHECKED AGAINST THE REGISTRY AT
    # IMPORT TIME. A row naming a nonexistent op or a field of the wrong
    # kind is a silently dead half of the grammar: the refusal would print
    # it as an available form, while the resolver would crash with a
    # KeyError on the very first attempt. The same lock as ADDRESS_EXCLUDED
    # below, and for the same reason.
    both = set(ELEMENT_GEOMETRY) & set(ELEMENT_REJECTED)
    if both:
        raise AssertionError(
            f"операция и разрешена, и отвергнута: {sorted(both)}")
    for op_name, row in ELEMENT_GEOMETRY.items():
        op_spec = spec.OPS.get(op_name)
        if op_spec is None:
            raise AssertionError(
                f"ELEMENT_GEOMETRY называет {op_name!r}, которого нет в реестре")
        if not op_spec.result.referenceable:
            raise AssertionError(
                f"ELEMENT_GEOMETRY: {op_name} не производит адресуемый "
                "результат — на него нельзя сослаться by=ref")
        if row["plan"] not in ("axis", "point"):
            raise AssertionError(f"ELEMENT_GEOMETRY: {op_name} — род плана?")
        if len(row["fields"]) != (2 if row["plan"] == "axis" else 1):
            raise AssertionError(
                f"ELEMENT_GEOMETRY: {op_name} — число полей не по роду плана")
        want_kind = "pt_xyz" if row["dims"] == 3 else "pt_xy"
        for field in row["fields"]:
            if not any(p.name == field and p.kind == want_kind
                       for p in op_spec.params):
                raise AssertionError(
                    f"ELEMENT_GEOMETRY: у {op_name} нет параметра {field} "
                    f"рода {want_kind}")
        for name in row["z"]:
            if name not in ELEVATIONS:
                raise AssertionError(
                    f"ELEMENT_GEOMETRY: {op_name} называет отметку {name!r} "
                    f"вне закрытого словаря {ELEVATIONS}")
        # "axis" means "the station's Z lies in the program itself," and
        # it lies there exactly when the station is three-dimensional. A
        # pair that diverges here would return a Z from nowhere.
        if ("axis" in row["z"]) != (row["dims"] == 3):
            raise AssertionError(
                f"ELEMENT_GEOMETRY: {op_name} — отметка axis есть только у "
                "трёхмерной станции, и наоборот")
        for name in ("base", "top"):
            if name in row["z"] and not any(
                    p.name == ("level" if name == "base" else "top_level")
                    for p in op_spec.params):
                raise AssertionError(
                    f"ELEMENT_GEOMETRY: {op_name} обещает отметку {name}, но "
                    "уровня, из которого её выводят, у операции нет")
    for op_name in ELEMENT_REJECTED:
        if op_name not in spec.OPS:
            raise AssertionError(
                f"ELEMENT_REJECTED называет {op_name!r}, которого нет в "
                "реестре — причина отказа про несуществующую операцию")
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
    """``{parameter name: dims}`` — where this op allows an address.

    THERE IS ONE JUDGE: the list is NOT maintained here, it is DERIVED
    from the parameter kind in ``spec.OPS`` minus :data:`ADDRESS_EXCLUDED`.
    A list of its own would become a fourth one and would drift apart at
    the very first new op — exactly what happened between the spec
    (13 ``pt_xyz`` as of 03.08) and the tree (15 as of 04.08:
    ``create_opening`` arrived).
    """
    from kir import spec
    op_spec = spec.OPS.get(op_name)
    if op_spec is None:
        return {}
    return {p.name: (3 if p.kind == "pt_xyz" else 2)
            for p in op_spec.params
            if p.kind in ("pt_xy", "pt_xyz")
            and (op_name, p.name) not in ADDRESS_EXCLUDED}


def is_address(value: Any) -> bool:
    """A cheap classifier: "is this even an address?".

    Deliberately CRUDE — a family marker key is enough to distinguish an
    address attempt from a literal. Everything else is said by
    :func:`validate_address`, and it says it with a TYPED REFUSAL, not a
    silent "not an address".

    TWO FAMILIES, ONE CLASSIFIER — and this is not generalization for its
    own sake. Every caller (``authoring_validation``, ``macros``,
    ``ground``) asks exactly one question: "literal or address?". Had we
    set up a second predicate, any caller that missed it would silently
    take the new node for a literal point — i.e. for a list of two
    numbers, which it is not.
    """
    return isinstance(value, dict) and (
        "at_grid" in value or "at_element" in value)


def is_element_address(value: Any) -> bool:
    """An address of the SECOND family — from an element, not from grids."""
    return isinstance(value, dict) and "at_element" in value


def program_uses_address(op: Any) -> bool:
    """Whether an op's text has an address — by addressable parameters,
    not by ``repr``.

    ``ground._needs_pool`` used to ask
    ``"at_grid" in repr(op.get("contour"))``, i.e. by the STRING
    representation of one field of one op. Here real values of real
    parameters are read: a substring in a type name («Ось at_grid 2») can
    no longer switch reading the pool on or off.
    """
    if not isinstance(op, dict):
        return False
    for param in addressable_params(str(op.get("op", ""))):
        if is_address(op.get(param)):
            return True
    return False


# ── flat geometry (all trigonometry happens here, at compile time) ─────────

def _is_pt(v) -> bool:
    return (isinstance(v, list) and len(v) == 2
            and all(is_finite_number(c) for c in v))


def _unit(dx: float, dy: float) -> tuple:
    length = math.hypot(dx, dy)
    return (dx / length, dy / length)


def line_angle_deg(d1: tuple, d2: tuple) -> float:
    """The angle between LINES (not rays), in degrees, 0..90.

    Via ``atan2(|cross|, |dot|)``, not via ``acos(dot)``: ``acos`` has an
    infinite derivative at the ends, and it is precisely at the ends —
    for almost-parallel grids — that this angle decides the pair's fate
    (D3).
    """
    u1, u2 = _unit(*d1), _unit(*d2)
    cross = abs(u1[0] * u2[1] - u1[1] * u2[0])
    dot = abs(u1[0] * u2[0] + u1[1] * u2[1])
    return math.degrees(math.atan2(cross, dot))


def signed_offset_mm(p0, p1, q) -> float:
    """Signed distance from the INFINITE line (p0,p1) to point q.

    Specifically from the infinite line: grids are lines, not segments
    (``contour.py`` has known this trap since 17.07), and a column
    beyond the edge of the DRAWN grid must measure the distance to the
    line, not to its endpoint.
    """
    ux, uy = _unit(p1[0] - p0[0], p1[1] - p0[1])
    return -uy * (q[0] - p0[0]) + ux * (q[1] - p0[1])


def _offset_line(p0, p1, distance: float) -> tuple:
    """A line parallel to (p0,p1), at signed distance ``distance``."""
    ux, uy = _unit(p1[0] - p0[0], p1[1] - p0[1])
    nx, ny = -uy, ux
    return ([p0[0] + nx * distance, p0[1] + ny * distance],
            [p1[0] + nx * distance, p1[1] + ny * distance])


def _canon_mm(value) -> float | int:
    """The coordinate canon: rounded to the nanometer, and an INTEGER if
    it is a whole number.

    Not cosmetics, but a condition of gate V3 of the spec: the same
    program, written with addresses and with literals, must give a
    BYTE-IDENTICAL create part of the C#. The emitter prints a number as
    it is, so `4000.0` would give `P(4000.0, ...)` where the literal
    `4000` gives `P(4000, ...)` — and a byte difference would be about
    the Python number's type, not about the geometry.

    Rounding to 6 digits (a nanometer) is four orders of magnitude below
    the witness's tolerance (5 mm) and three below emission's rounding
    (0.005 mm), meaning it is fully absorbed by them; but it makes the
    output stable against the last bit of binary floating point across
    different machines.
    """
    number = round(float(value), 6)
    integral = int(number)
    return integral if number == integral else number


def intersect(p0, p1, q0, q1) -> Optional[list]:
    """The intersection of two INFINITE lines, or ``None`` on degeneracy.

    The conditioning threshold is checked by the CALLER (it has something
    to say in the refusal — the grids' names and the angle); what remains
    here is only protection against division by zero.
    """
    d1 = (p1[0] - p0[0], p1[1] - p0[1])
    d2 = (q1[0] - q0[0], q1[1] - q0[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-12:
        return None
    t = ((q0[0] - p0[0]) * d2[1] - (q0[1] - p0[1]) * d2[0]) / den
    return [p0[0] + t * d1[0], p0[1] + t * d1[1]]


# ── VALIDATE stage: pure functions of the TEXT (no snapshot needed) ─────────

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
    """One <line> node: form, bounds, pairing. No model needed."""
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
        # The offset_mm/toward pairing is the MOST likely slip, and a
        # generic "unknown set of fields" would send the author off to
        # reread the grammar instead of just adding one word. That is why
        # it is named separately, BEFORE the form registry.
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


def _validate_element_address(value: dict, oid, field: str, diags: list, *,
                              dims: int) -> bool:
    """Static laws of an address FROM AN ELEMENT. A pure function of the
    text.

    The same line as with ``at_grid`` (spec §4.1): here what is proven is
    "present in the text" — the form, the closed dictionaries of names,
    the elevation bounds. "Present in the program" — the op's existence,
    its kind, whether it has a level — lives in
    :func:`resolve_element_address`, because that requires the program
    itself.
    """
    forms = {k: v for k, v in ELEMENT_ADDRESS_FORMS.items() if v[0] == dims}
    keys = frozenset(value)
    form = forms.get(keys)
    if form is None:
        hint = ""
        if "z" in keys and "z_mm" in keys:
            hint = (" Отметка названа ДВАЖДЫ: `z` берёт её у самого элемента, "
                    "`z_mm` задаёт числом. Одновременно — два разных ответа на "
                    "один вопрос, и выбирать за вас нельзя.")
        elif dims == 2 and ("z" in keys or "z_mm" in keys):
            hint = (" Этот параметр плоский (pt_xy) — отметку держит уровень, "
                    "отметка здесь лишняя.")
        elif dims == 3 and not ("z" in keys or "z_mm" in keys):
            hint = (" Этот параметр объёмный (pt_xyz): у станции плана отметки "
                    "нет, её обязан назвать сам адрес — допишите z (взять у "
                    "элемента) либо z_mm (числом). Молча подставленный ноль "
                    "поставил бы элемент на отметку нуля модели, и свидетель "
                    "принял бы это — он сверяет с тем же нулём.")
        expected = next((sig for _d, sig in forms.values()), None)
        return _bad(diags, oid, field,
                    f"{field}: неизвестная форма адреса от элемента "
                    f"{sorted(keys)}. Грамматика ЗАКРЫТА; для этого параметра "
                    f"принимается {expected}.{hint}",
                    got=sorted(keys), expected=expected,
                    candidates=[sig for _d, sig in forms.values()])
    sel = value.get("at_element")
    # The selector is checked HERE, not in ground: "by must be ref" is a
    # pure function of the text, and a refusal that can be issued without
    # the model must be issued without the model.
    if not isinstance(sel, dict) or set(sel) != {"by", "value"} \
            or sel.get("by") != "ref" or not isinstance(sel.get("value"), str) \
            or not sel["value"].strip():
        return _bad(diags, oid, f"{field}.at_element",
                    f"{field}.at_element: {ELEMENT_SELECTOR_RU}",
                    got=sel, expected='{"by": "ref", "value": "<id опа>"}')
    point = value.get("point")
    if point not in PLAN_POINTS:
        return _bad(diags, oid, f"{field}.point",
                    f"{field}.point: станция плана — одно из {list(PLAN_POINTS)}. "
                    f"Словарь ЗАКРЫТ; какие из них выражает конкретный элемент, "
                    f"скажет отказ при разрешении — это зависит от операции, "
                    f"которая его создаёт",
                    code=TYPE_BAD_TYPE, got=point, expected=list(PLAN_POINTS),
                    candidates=list(PLAN_POINTS))
    if "z" in value and value["z"] not in ELEVATIONS:
        return _bad(diags, oid, f"{field}.z",
                    f"{field}.z: отметка — одно из {list(ELEVATIONS)}. "
                    f"base/top — у элемента, чью высоту задают уровни "
                    f"(стена, колонна); axis — отметка самой станции у "
                    f"объёмной оси (балка, труба, воздуховод)",
                    code=TYPE_BAD_TYPE, got=value.get("z"),
                    expected=list(ELEVATIONS), candidates=list(ELEVATIONS))
    if "z_mm" in value:
        z = value["z_mm"]
        if not is_finite_number(z):
            return _bad(diags, oid, f"{field}.z_mm",
                        f"{field}.z_mm: отметка — конечное число (мм)", got=z)
        if abs(float(z)) > _COORD_LIMIT_MM:
            return _bad(diags, oid, f"{field}.z_mm",
                        f"{field}.z_mm: |отметка| не более "
                        f"{_COORD_LIMIT_MM:.0f} мм", code=TYPE_BOUNDS, got=z)
    return True


def validate_address(value: Any, oid, field: str, diags: list, *,
                     dims: int, allow_world_offset: bool = False) -> bool:
    """Static laws of an address. Returns True if it parses.

    WHAT IS PROVEN HERE: form, bounds, pairing — everything that is a
    pure function OF THE TEXT. A grid's existence, the uniqueness of its
    name, the angle, and the point itself are proven from the SNAPSHOT
    and live in :func:`resolve_address` (the ground stage). The line runs
    exactly between "present in the text" and "present in the model" —
    spec §4.1.
    """
    if not isinstance(value, dict):
        return _bad(diags, oid, field, f"{field}: адрес — объект", got=value)
    if "at_element" in value:
        return _validate_element_address(value, oid, field, diags, dims=dims)
    forms = dict(ADDRESS_FORMS)
    if allow_world_offset:
        forms.update(LEGACY_ADDRESS_FORMS)
    # The registry is narrowed DOWN TO the parameter's dimensionality,
    # rather than checked against it afterward. The difference shows in
    # the refusal: "unknown form" carries a hint about z_mm and about WHY
    # it is required, whereas "form gives 2D, parameter is 3D" is only a
    # diagnosis.
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
            if abs(float(z)) > _COORD_LIMIT_MM:
                ok = _bad(diags, oid, f"{field}.z_mm",
                          f"{field}.z_mm: |отметка| не более "
                          f"{_COORD_LIMIT_MM:.0f} мм", code=TYPE_BOUNDS, got=z)
    if allow_world_offset and "offset_mm" in keys and not _is_pt(value["offset_mm"]):
        ok = _bad(diags, oid, f"{field}.offset_mm",
                  f"{field}.offset_mm: мировой отступ — [dx, dy]",
                  got=value.get("offset_mm"))
    return ok


# ── GROUND stage: pure functions of the SNAPSHOT ────────────────────────────

def _rows_named(name: str, pool: list) -> list:
    """ALL pool rows with this name. A list, not a single row — that is exactly D2."""
    want = name.strip()
    return [row for row in (pool or [])
            if isinstance(row, dict) and str(row.get("name", "")).strip() == want]


def _nearest_names(name: str, pool: list) -> list:
    names = [str(row.get("name", "")) for row in (pool or [])
             if isinstance(row, dict)]
    return difflib.get_close_matches(name.strip(), names, n=5, cutoff=0.0)


def _parallel_neighbours(row: dict, pool: list) -> list:
    """Names of grids PARALLEL to the given one and not coinciding with
    it.

    Exactly the list that is fit for ``toward``. An empty list is a
    legitimate answer, and it means "this grid cannot be offset from, it
    has no neighbor" (measurement: 35% of ``k2_ar_rd``'s grids are
    loners; and yet NOT ONE column in the corpus stands offset from a
    lone grid).
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
    """(p0, p1) of the grid, if it has STRAIGHT-LINE geometry of nonzero length."""
    p0, p1 = row.get("p0_mm"), row.get("p1_mm")
    if not _is_pt(p0) or not _is_pt(p1):
        return None
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < _MIN_GRID_LENGTH_MM:
        return None
    return ([float(p0[0]), float(p0[1])], [float(p1[0]), float(p1[1])])


def _find_grid(name: str, pool: list, oid, field: str, diags: list, *,
               truncated: bool) -> Optional[dict]:
    """One grid by name: G108 not found / G109 ambiguous / G111 no geometry."""
    want = name.strip()
    rows = _rows_named(want, pool)
    if not rows:
        # A truncated pool — by the SAME PATTERN as ``ground._resolve_one``,
        # not new code: a single VISIBLE one proves nothing about the
        # invisible remainder. There is no new code, only an addendum to
        # the message.
        note = ("; пул осей обрезан коллектором на 1000 — ось может "
                "существовать за срезом" if truncated else "")
        # THE SECOND HALF OF THE FIX, and it stands here, not in the
        # instrument's prose description: only grids FROM THE SNAPSHOT,
        # taken BEFORE the program, are addressable, so a grid created by
        # this same program being "not found" is entirely legitimate.
        # Saying this in the course would cost tokens on EVERY request;
        # saying it here costs them only for whoever stepped on it.
        _bad(diags, oid, field,
             f"{field}: оси «{want}» нет в модели{note}. Список осей: "
             f'{{"op": "query_list", "kind": "grid"}}. Если «{want}» создаётся '
             f"ЭТОЙ ЖЕ программой, ПЕРЕСЕЧЕНИЕ с ней здесь невыразимо: "
             f"at_grid читает снимок, снятый ДО программы, — это два хода "
             f"(создать оси, перечитать модель, строить). Отдельные КОНЦЫ "
             f"такой оси адресуются другим узлом, читающим саму программу: "
             f'{{"at_element": {{"by": "ref", "value": "<id опа create_grid>"}}, '
             f'"point": "start|end|center"}}',
             code=GRID_NOT_FOUND, got=want,
             candidates=_nearest_names(want, pool))
        return None
    if len(rows) > 1:
        # D2. A grid's name IS ITS IDENTITY in project culture, so the
        # language does NOT offer a workaround of "disambiguate via
        # element_id": it does not accept one (spec §5.4). The workaround
        # is honestly named, and it is outside the grammar.
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
    if truncated:
        # 🔴 THE ONLY VISIBLE NAMESAKE IS NOT THE ONLY ONE (04.09.2026, an
        # audit finding, FC-25, reproduced by a run).
        #
        # The caveat about truncation stood in this file TWICE, and BOTH
        # times in the "no grid found" branch — there it is correct and
        # decides nothing: a refusal is a refusal either way. The
        # `len(rows) == 1` branch is the only one where truncation changes
        # the VERDICT, and it was exactly the one that asked no question:
        #
        #     pool [{1,"А"},{2,"1"}], truncated=True  -> grid «А» = id 1, diags 0
        #     CONTROL truncated=False                 -> id 1, and this is LEGITIMATE
        #
        # Twenty lines above it is written that the language does not
        # allow two grids with one name AT ALL ("a grid's name is its
        # identity"): with two VISIBLE namesakes a refusal stands here. So
        # beyond the truncation ceiling, a namesake turns a hard refusal
        # into A QUIETLY PICKED FOREIGN GRID — and the whole program
        # drifts by a grid step, showing nothing of it.
        #
        # THERE IS ONE PATTERN, AND THIS IS STATED WORD FOR WORD ABOVE:
        # `ground._resolve_one`. As of 04.09 it truly is one — the same
        # check now stands at `by=name` and at `by=family_type`
        # (`ground._refuse_sole_visible`).
        #
        # THE COST IS NAMED, NOT LEFT UNSAID, AND HERE IT IS HIGHER THAN
        # FOR THE CATALOG: a type has an exact workaround (`element_id`),
        # a grid has NONE — the grid language does not address by id
        # (spec §5.4). So on a model with more than 1000 grids, addressing
        # from grids closes entirely, leaving only the literal [x, y]. The
        # trade-off is accepted deliberately: "built in the wrong place,
        # and nobody said so" is an outcome this compiler forbids
        # categorically, while "a refusal with a named next move" is one
        # it is obligated to give.
        _bad(diags, oid, field,
             f"{field}: ось «{want}» в срезе одна, но пул осей обрезан "
             f"коллектором на 1000 — единственная ВИДИМАЯ ось с этим именем "
             f"не доказывает, что за срезом нет тезки, а двух осей с одним "
             f"именем язык не разрешает (имя оси и есть её идентичность). "
             f"Осей по element_id язык не адресует: задайте эту точку "
             f"литералом [x, y] либо уменьшите число осей в модели",
             code=GRID_AMBIGUOUS, got=want,
             candidates=[{"id": row.get("id"), "name": row.get("name")}])
        return None
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
    """The <line> node -> {"line": (p0,p1), "grid": row, "offset_mm", "toward"}."""
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
    # A NEXT MOVE, not a diagnosis: the list of parallel neighbors is
    # exactly the set of names that will be accepted here. An empty list
    # is also a move, and a different one: for a lone grid, an offset
    # cannot be expressed AT ALL, and calling on the author to change the
    # name would mean sending them into a dead end.
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
    # The side must be unambiguous ALONG THE ENTIRE LENGTH of the drawn
    # grid: two lines at 0.9° are formally parallel by our threshold, yet
    # they still intersect — if different ends of `toward` lie on
    # different sides, the word "toward" means nothing, and this cannot be
    # left unsaid.
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
    """An address -> a literal point [x,y] (or [x,y,z]), or ``None`` +
    refusals.

    A pure function of the snapshot: no bridge, no transaction. A refusal
    that can be issued without Revit must be issued without Revit.

    ``receipt`` — if a list is passed, a RECEIPT entry is placed into it:
    exactly what the compiler derived from what the author wrote (each
    grid's id and name, the offset, the side, the resulting point). A
    choice that nobody can be shown is indistinguishable from
    ``.FirstOrDefault()`` in a costume.
    """
    # THE FUNCTION MUST BE TOTAL. Since 09.08 `validate_address` accepts
    # TWO families of nodes, and without this line an address from an
    # element would pass the form check and then crash below on
    # `value["at_grid"]` — i.e. a typed refusal would be replaced by "an
    # internal compiler error". Exactly the trade-off that was found that
    # same night on the repeated law-checking site.
    if is_element_address(value):
        _bad(diags, oid, field,
             f"{field}: адрес от ЭЛЕМЕНТА разрешает "
             f"`resolve_element_address` — ему нужна программа, а не пул осей")
        return None
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
        # D3. The threshold is not a matter of taste: at 0.1° the error
        # amplification is 573×, and the point we would have returned
        # would be noise indistinguishable from a result.
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
    if point is None:                     # unreachable when angle >= threshold
        _bad(diags, oid, field,
             f"{field}: оси «{name_a}» и «{name_b}» не пересекаются",
             code=GRID_NO_INTERSECTION, got=[name_a, name_b])
        return None
    if allow_world_offset and _is_pt(value.get("offset_mm")):
        point = [point[0] + float(value["offset_mm"][0]),
                 point[1] + float(value["offset_mm"][1])]
    # 🔴 TWO ADMISSIBLE GRIDS GIVE A POINT THAT NOBODY RE-CHECKED
    # (04.09.2026, an audit finding, FC-26, reproduced by a run).
    #
    # Everything above checks the INPUT: the grid names were found,
    # geometry exists, the angle is not below `MIN_GRID_ANGLE_DEG`, the
    # grids' endpoints are coordinates within bounds (`validate_address`
    # only measures `z_mm`, while the endpoints arrive from the model
    # snapshot, i.e. are known to be within range). The checked input was
    # enough to COMPUTE a quantity that nobody asked about:
    #
    #     two grids at 1.1°, all endpoints within ±16,000,000,
    #     a parallel offset of 400,000 mm -> x = −20,832,269 mm (out of
    #                                       bounds, there was no refusal)
    #     CONTROL, offset of 100,000 mm  -> x = −5,208,067 mm  (within bounds)
    #
    # The angle threshold does NOT protect against this and cannot: it is
    # about CONDITIONING (error amplification as 1/sin), while the
    # question here is about DISTANCE. Two nearly-parallel grids meet
    # farther away the smaller the angle is, and at a legitimate 1.1°
    # they carry the point tens of kilometers from the origin — right
    # where `authoring_validation` would have rejected a literal.
    #
    # WHY THE CHECK STANDS AFTER THE WORLD OFFSET, NOT BEFORE. The legacy
    # form `offset_mm: [dx, dy]` moves an already-finished point, and it
    # is THE SAME quantity: two checking sites would mean two carriers of
    # one law. We measure what will REACH the emission — the only
    # question worth answering here.
    worst = max(point[0], point[1], key=abs)
    if abs(worst) > _COORD_LIMIT_MM:
        _bad(diags, oid, field,
             f"{field}: оси «{name_a}» и «{name_b}» законны, но сходятся под "
             f"{angle:.3f}° и пересекаются в "
             f"[{point[0]:.0f}, {point[1]:.0f}] мм — это вне рабочего охвата "
             f"модели (|координата| <= {_COORD_LIMIT_MM:.0f} мм, ~16 км от "
             f"начала координат), дальняя координата {worst:.0f}. Порог угла "
             f"{MIN_GRID_ANGLE_DEG}° сторожит ШУМ, а не ДАЛЬНОСТЬ: почти "
             f"параллельные оси сходятся тем дальше, чем меньше угол. "
             f"СЛЕДУЮЩИЙ ХОД: возьмите пару осей, пересекающихся внутри "
             f"здания, либо задайте эту точку литералом [x, y]",
             code=TYPE_BOUNDS, got=[point[0], point[1]],
             expected=f"|координата| <= {_COORD_LIMIT_MM:.0f} мм")
        return None
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


# ── stage GROUND: address from the ELEMENT (a pure function of the PROGRAM) ──────

def element_address_refs(op: Any) -> list:
    """``[(параметр, id опа-адресата)]`` — references hidden inside addresses.

    Exists for exactly ONE consumer — the DAG traversal in
    ``compiler.plan_program``, and this is not a convenience but a law
    recorded in the same place (the comment about the selector's second
    stage): edge traversal looks at the TOP level of the parameter's
    value, so a reference that moved one level deeper would become
    invisible to it — and «ref не указывает на более ранний оп» would stop
    firing SILENTLY. Exactly one place needs to teach this, and this is
    its entry point.
    """
    if not isinstance(op, dict):
        return []
    out = []
    for param in addressable_params(str(op.get("op", ""))):
        value = op.get(param)
        if not is_element_address(value):
            continue
        sel = value.get("at_element")
        if isinstance(sel, dict) and sel.get("by") == "ref" \
                and isinstance(sel.get("value"), str):
            out.append((param, sel["value"].strip()))
    return out


def _pt_of(value: Any, dims: int) -> Optional[list]:
    """A literal point of the required dimensionality, or None."""
    if (isinstance(value, list) and len(value) == dims
            and all(is_finite_number(c) for c in value)):
        return [float(c) for c in value]
    return None


def _level_elevation_mm(src: dict, param: str, program: dict, levels_pool: list,
                        oid, field: str, diags: list) -> Optional[float]:
    """The elevation of the level the addressed op referred to, in mm. Or
    None+refusal.

    TWO SOURCES, AND BOTH ARE HONEST. The model's level is a row of the
    snapshot's ``levels`` pool: the ``elevation_mm`` key arrived there with
    the section wave of 09.08 (before that, the wall emitter's comment
    stated plainly «отметки уровней компилятору недоступны — в снапшоте
    только id и имя», and that stopped being true). A level created by
    THIS SAME program is the ``elev_mm`` parameter of the ``create_level``
    operation — that is, a number the author wrote themselves.

    THE CAPTURE GAP IS NAMED, NOT WORKED AROUND. A pool row without
    ``elevation_mm`` (the old bridge, where the collector fell back to
    ``Level.Elevation``) is KIR-G116, not a default of zero: a substituted
    zero would place the element at the model's zero elevation and would
    pass the witness that checks against that same zero.
    """
    sel = src.get(param)
    if not isinstance(sel, dict) or not isinstance(sel.get("__grounded__"), dict):
        _bad(diags, oid, field,
             f"{field}: у опа «{src.get('id')}» ({src.get('op')}) нет "
             f"привязки «{param}», из которой выводится эта отметка. "
             f"СЛЕДУЮЩИЙ ХОД: допишите «{param}» у того опа либо назовите "
             f"отметку числом (z_mm)",
             code=ELEMENT_PART_INVALID, got=param)
        return None
    grounded = sel["__grounded__"]
    if grounded.get("via") == "ref":
        # The level is also built by this same program — the numbers live in it too.
        ref = str(grounded.get("ref", ""))
        level_op = program.get(ref)
        if not isinstance(level_op, dict) or level_op.get("op") != "create_level":
            _bad(diags, oid, field,
                 f"{field}: «{param}» опа «{src.get('id')}» ссылается на "
                 f"«{ref}», а отметку программа знает только у create_level",
                 code=ELEMENT_PART_INVALID, got=ref)
            return None
        elev = level_op.get("elev_mm")
        if not is_finite_number(elev):
            _bad(diags, oid, field,
                 f"{field}: у create_level «{ref}» нет числовой отметки "
                 f"elev_mm", code=ELEMENT_PART_INVALID, got=elev)
            return None
        return float(elev)
    level_id = grounded.get("id")
    if not isinstance(level_id, int) or isinstance(level_id, bool):
        _bad(diags, oid, field,
             f"{field}: «{param}» опа «{src.get('id')}» разрешён без "
             f"ElementId (via={grounded.get('via')!r}) — отметку такого уровня "
             f"компилятор не знает",
             code=ELEMENT_PART_INVALID, got=grounded.get("via"))
        return None
    row = next((r for r in (levels_pool or [])
                if isinstance(r, dict) and r.get("id") == level_id), None)
    if row is None:
        _bad(diags, oid, field,
             f"{field}: уровня id {level_id} нет в пуле levels снапшота — "
             f"отметку взять неоткуда. СЛЕДУЮЩИЙ ХОД: перечитайте модель",
             code=ELEMENT_CAPTURE_GAP, got=level_id)
        return None
    elev = row.get("elevation_mm")
    if not is_finite_number(elev):
        _bad(diags, oid, field,
             f"{field}: строка уровня «{row.get('name')}» (id {level_id}) "
             f"пришла БЕЗ elevation_mm — это пробел ЗАХВАТА, а не свойство "
             f"модели: ключ собирает open_model.GROUND_SNAPSHOT_CS. Пока его "
             f"нет, отметку задайте числом (z_mm)",
             code=ELEMENT_CAPTURE_GAP, got=row.get("elevation_mm"))
        return None
    return float(elev)


def _offset_mm(src: dict, param: str) -> float:
    """An offset the author MAY have left unnamed. Absence = zero, and
    this is a MEASUREMENT.

    Not a registry default: ``base_offset_mm``/``top_offset_mm`` has none
    (``default=None``), and when the value is absent the emitter either
    does not write the parameter at all (wall: the ``WALL_BASE_OFFSET``
    block is not emitted), or writes a literal ``0.0``
    (``WALL_TOP_OFFSET``, ``FAMILY_TOP_LEVEL_OFFSET``). That is, zero here
    is the element's built state, not our guess.
    """
    value = src.get(param)
    return float(value) if is_finite_number(value) else 0.0


def resolve_element_address(value: Any, program: dict, levels_pool: list,
                            oid, field: str, diags: list, *, dims: int,
                            receipt: Optional[list] = None) -> Optional[list]:
    """Address from an element -> a literal point, or ``None`` + refusals.

    ``program`` is the already GROUNDED ops that stand STRICTLY ABOVE the
    addressing one, by their id. A forward reference therefore cannot be
    found — and this is not a side effect of traversal order but the same
    law as ``by=ref`` in emission: only what has already been said can be
    addressed.

    A pure function: no bridge, no transaction. There is no trigonometry
    here at all — plan stations are the endpoints and midpoint of a
    segment, and elevations are sums of two numbers.
    """
    if not _validate_element_address(value, oid, field, diags, dims=dims):
        return None
    ref = str(value["at_element"]["value"]).strip()
    src = program.get(ref)
    if not isinstance(src, dict):
        _bad(diags, oid, field,
             f"{field}: «{ref}» — не оп, стоящий ВЫШЕ в этой программе. "
             f"Адрес читает числа, которые автор уже написал, поэтому "
             f"адресуемый оп обязан быть РАНЬШЕ адресующего (ссылка вперёд и "
             f"ссылка на чужую программу здесь одинаково невыразимы). "
             f"Доступны: {sorted(program)}",
             code=ELEMENT_REF_UNKNOWN, got=ref, candidates=sorted(program))
        return None
    op_name = str(src.get("op", ""))
    row = ELEMENT_GEOMETRY.get(op_name)
    if row is None:
        why = ELEMENT_REJECTED.get(op_name)
        # A REASON, NOT AN EMPTY TABLE ROW. An author who asked about a
        # room must learn EXACTLY WHAT cannot be expressed, otherwise they
        # will try again the same way.
        tail = (f" Причина: {why}." if why else
                " Операции нет ни среди адресуемых, ни среди названных "
                "исключений — значит вопрос про неё ещё никто не решал.")
        _bad(diags, oid, field,
             f"{field}: у элементов операции «{op_name}» адресуемой геометрии "
             f"нет.{tail} Адресуются: {sorted(ELEMENT_GEOMETRY)}. Задайте эту "
             f"точку литералом",
             code=ELEMENT_NOT_ADDRESSABLE, got=op_name,
             candidates=sorted(ELEMENT_GEOMETRY))
        return None
    point_name = value["point"]
    src_dims = row["dims"]
    # ── plan station ────────────────────────────────────────────────────
    if row["plan"] == "point":
        if point_name != "center":
            _bad(diags, oid, f"{field}.point",
                 f"{field}.point: элемент «{ref}» ({op_name}) задан ОДНОЙ "
                 f"точкой — у него нет ни начала, ни конца. Выражается "
                 f"только «center»",
                 code=ELEMENT_PART_INVALID, got=point_name,
                 expected="center", candidates=["center"])
            return None
        plan_field = row["fields"][0]
        if op_name == "create_column" and src.get("top_xy") is not None:
            # CURRENT-REGISTRY SEAM (10.08.2026). After `top_xy` appeared,
            # a column stopped having a single plan point: the axis's
            # lower and upper ends differ. The old table row silently
            # returned `xy` even at z=top — a correct elevation, a wrong
            # plan point, and both numbers would then pass the beam's own
            # witness.
            z_selector = value.get("z") if dims == 3 else None
            if z_selector not in ("base", "top"):
                _bad(diags, oid, field,
                     f"{field}: колонна «{ref}» наклонная (`top_xy` задан), "
                     f"поэтому одной плановой точки у неё нет. Адрес обязан "
                     f"выбрать конец оси через z=base либо z=top; плоский "
                     f"адрес и z_mm не определяют, брать xy или top_xy",
                     code=ELEMENT_PART_INVALID, got=z_selector,
                     expected="z=base|top", candidates=["base", "top"])
                return None
            plan_field = "top_xy" if z_selector == "top" else "xy"
        plan = _pt_of(src.get(plan_field), src_dims)
        if plan is None:
            _bad(diags, oid, field,
                 f"{field}: у опа «{ref}» точка «{plan_field}» не "
                 f"разрешена в числа — адресоваться не от чего",
                 code=ELEMENT_PART_INVALID, got=src.get(plan_field))
            return None
        station = plan
    else:
        p0 = _pt_of(src.get(row["fields"][0]), src_dims)
        p1 = _pt_of(src.get(row["fields"][1]), src_dims)
        if p0 is None or p1 is None:
            _bad(diags, oid, field,
                 f"{field}: у опа «{ref}» концы "
                 f"{row['fields'][0]}/{row['fields'][1]} не разрешены в "
                 f"числа — адресоваться не от чего",
                 code=ELEMENT_PART_INVALID,
                 got=[src.get(row["fields"][0]), src.get(row["fields"][1])])
            return None
        # ARC. The chord's midpoint is NOT the arc's midpoint, and
        # substituting it silently would miss more the more sharply the
        # wall curves. The endpoints, however, are honest:
        # `materialize._reconcile_arc_endpoints` derives p0/p1 of an arc
        # wall FROM THE ARC ITSELF.
        if point_name == "center" and src.get("arc") is not None:
            _bad(diags, oid, f"{field}.point",
                 f"{field}.point: у опа «{ref}» ось ДУГОВАЯ (задан arc), а "
                 f"«center» вернул бы середину ХОРДЫ — точку, лежащую вне "
                 f"элемента. Выражаются только start и end",
                 code=ELEMENT_PART_INVALID, got=point_name,
                 candidates=["start", "end"])
            return None
        station = (p0 if point_name == "start" else
                   p1 if point_name == "end" else
                   [(a + b) / 2.0 for a, b in zip(p0, p1)])
    out = [_canon_mm(station[0]), _canon_mm(station[1])]
    detail: dict = {"of": ref, "op": op_name, "point": point_name}
    # ── elevation ────────────────────────────────────────────────────────
    if dims == 3:
        if "z_mm" in value:
            out.append(_canon_mm(value["z_mm"]))
            detail["z"] = "z_mm"
        else:
            z_name = value["z"]
            if z_name not in row["z"]:
                legal = list(row["z"])
                move = (f"выражаются только {legal}" if legal else
                        "у этого элемента отметки в программе нет вовсе — "
                        "задайте её числом (z_mm)")
                extra = ""
                if z_name == "top" and "top" not in legal and "base" in legal:
                    # THE MOST LIKELY SLIP, and a generic «имя не из
                    # словаря» would send the author to reread the
                    # dictionary instead of adding one field to a
                    # DIFFERENT op.
                    extra = (" Верх выражается, только когда программа его "
                             "ПРИВЯЗЫВАЕТ: допишите top_level у опа "
                             f"«{ref}». Без привязки высота приезжает из "
                             "умолчания (у стены 3000 мм) либо из "
                             "типоразмера, и назвать её словами автора нельзя")
                _bad(diags, oid, f"{field}.z",
                     f"{field}.z: у элемента «{ref}» ({op_name}) отметка "
                     f"«{z_name}» не выражается — {move}.{extra}",
                     code=ELEMENT_PART_INVALID, got=z_name, candidates=legal)
                return None
            if z_name == "axis":
                out.append(_canon_mm(station[2]))
                detail["z"] = "axis"
            else:
                level_param = "level" if z_name == "base" else "top_level"
                if z_name == "top" and not isinstance(
                        src.get("top_level"), dict):
                    _bad(diags, oid, f"{field}.z",
                         f"{field}.z: у опа «{ref}» верх НЕ ПРИВЯЗАН "
                         f"(top_level не задан), поэтому верхней отметки в "
                         f"программе нет: высота приезжает из умолчания либо "
                         f"из типоразмера. СЛЕДУЮЩИЙ ХОД: допишите top_level "
                         f"у «{ref}» либо назовите отметку числом (z_mm)",
                         code=ELEMENT_PART_INVALID, got=None,
                         expected="top_level")
                    return None
                elevation = _level_elevation_mm(
                    src, level_param, program, levels_pool, oid, field, diags)
                if elevation is None:
                    return None
                offset = _offset_mm(
                    src, "base_offset_mm" if z_name == "base"
                    else "top_offset_mm")
                out.append(_canon_mm(elevation + offset))
                detail["z"] = z_name
                detail["z_detail"] = {"level_param": level_param,
                                      "elevation_mm": _canon_mm(elevation),
                                      "offset_mm": _canon_mm(offset)}
    if receipt is not None:
        receipt.append({"op_id": oid, "param": field, "point_mm": list(out),
                        "element": detail})
    return out


def describe_receipt_ru(rows: list) -> list:
    """A receipt of addresses, one line per address — for replying to the author."""
    out = []
    for row in rows or []:
        point = row.get("point_mm") or []
        coords = ", ".join(f"{c:g}" for c in point)
        element = row.get("element")
        if isinstance(element, dict):
            # The element-address receipt is printed ALWAYS, and in the
            # same line format as the address from grids: both answer one
            # question — «что компилятор вывел из написанного автором».
            # The elevation is named together with its ADDENDS, because
            # the arithmetic we took upon ourselves must be shown.
            text = (f"«{element.get('of')}» ({element.get('op')}) "
                    f"→ {element.get('point')}")
            z_detail = element.get("z_detail")
            if isinstance(z_detail, dict):
                # The sign is printed SEPARATELY from the number: «3300 + -400»
                # reads like a typo, and the receipt is read by a human who
                # must check the arithmetic by eye without stumbling over
                # the formatting.
                offset = float(z_detail.get("offset_mm") or 0.0)
                text += (f", отметка {element.get('z')} = "
                         f"{z_detail.get('elevation_mm'):g} "
                         f"{'+' if offset >= 0 else '−'} {abs(offset):g} мм")
            elif element.get("z"):
                text += f", отметка {element.get('z')}"
            out.append(f"{row.get('op_id')}.{row.get('param')}: "
                       f"{text} -> [{coords}]")
            continue
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
