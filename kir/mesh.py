"""KIR MESH — a triangular surface as a value of the language (wave of 29.07).

WHY. The registry has 32 operations, and all of them are building-centric:
levels, walls, rooms, contours. An arbitrary shape — a shell, a lattice, a
sculptural volume — the model cannot express AT ALL. This is a wall exactly
where the model's strength is greatest: it knows how to invent the geometry, but
had nothing to say it with.

WHAT THIS ACTUALLY IS, AND WHAT IS NOT HERE. A mesh is GEOMETRY WITHOUT BIM
MEANING. The resulting element has no type, no thickness/material layer
parameters, it will not appear in schedules as a wall or a floor, and a person
will not edit it by hand the way a wall is edited. This is a cost, not a flaw in
the implementation: that is exactly how DirectShape works in Revit. So the only
honest behavior for the operation is to say this itself, everywhere it is
visible (the spec's docstring, the decompile passport, the receipt to the user),
rather than staying silent and letting the result be called a "building".
"Generated a building" when what was generated is a mesh is exactly the lie this
whole compiler is written against.

LAWS OF SHAPE (all static, all a typed refusal, not one silent correction of the
input). A silent fix to the input has already cost this house 96.77% of the
groups ("0 instead of a missing value"), so here there is NO discarding of
degenerate triangles, no welding of vertices, no truncating the list at a limit:

  1. shape of the value: exactly {vertices_mm, triangles}, extra fields — refused;
  2. vertices: 3..MAX_VERTICES points [x,y,z] in mm, every coordinate finite;
  3. triangles: 1..MAX_TRIANGLES triples of INTEGER indices;
  4. an index outside the range of vertices — refused (not "wrap it modulo");
  5. a repeated index within a triangle — degenerate, refused;
  6. an edge shorter than _MIN_EDGE_MM, or an area smaller than _MIN_AREA_MM2 —
     refused (two different degeneracies: a thin needle is caught by the edge,
     three collinear points — by the area);
  7. two faces on the SAME SET OF points are TWO DIFFERENT kinds, and WINDING
     tells them apart (see "ABOUT THE SEAM" below): same winding — a DUPLICATE,
     always refused; opposite winding — a SEAM, refused under the authoring
     contract and ACCEPTED under the observational one;
  8. a vertex that no triangle references — refused: we would be building a
     different mesh than the one that was sent, and from the outside that is
     indistinguishable from success;
  9. a coordinate outside ±_COORD_MAX_MM — refused;
 10. the mesh is required to be CONNECTED (see below).

ABOUT THE SEAM — AND THIS IS SHAPE 49, BOUGHT HERE FOR THE SECOND TIME
(02.09.2026).

Two faces lying on the same points come in TWO DIFFERENT KINDS, and before
02.09.2026 the law saw only one, because a face's key was taken as
`tuple(sorted(...))`, which DISCARDED THE WINDING before the comparison:

  * THE SAME winding — a DUPLICATE. The same triangle twice: the surface is
    described twice over, and the volume and normal become ambiguous. Refused
    EVERYWHERE, under any contract;
  * OPPOSITE winding — a SEAM. This, and only this, is what the place where two
    CLOSED solids are welded together looks like: the shared plane arrives
    twice, each time facing outward from its own solid. This is not corruption,
    but the normal look of a weld.

MEASURED ON THE CORPUS 02.09.2026 (93 decompiles, 1137 meshes, 2048 load-bearing
elements): 78 pairs of matching faces, of which **78 opposite-winding and 0
same-winding**; the coordinates match bit for bit, the pairs share zero matching
vertex NUMBERS, and vertex repetition is exactly 4.02 per point across all 42
meshes. The bundle itself names the cause in the `degradations` field: "combined
multiple geometry parts through their exact Gm fallbacks" — welding several
solids into one, our own step. Remove one face from each pair, and 42 out of 42
meshes pass the law in full: the seam was the ONLY cause of refusal.

WHY THE DISCRIMINATOR IS WINDING, NOT THE PATH. What must be asked is the
PROPERTY, not the place where it first appeared (shape 54): "came from
decompile" is a fact about the CALLER, "opposite winding on matching points" is
a fact about the VALUE. A genuine duplicate is required to turn red on the
observational path too, and it does.

WHAT THE CONTRACT DECIDES, AND WHAT THE VALUE DECIDES. The kind is always read
from the value; the contract decides exactly one thing — whether a SEAM is
tolerated. The authoring contract is strict: `extrude` and `sweep` never produce
a seam at all (measured: 0 pairs for a box, a box with a hole, and a handrail),
so strictness there costs nothing and catches a genuine author error. The
observational contract ACCEPTS a seam: a foreign document's profile has no right
to be stricter than what Revit legitimately creates — strictness on the way in
is a refusal to do the WORK, not a defense against error.

WHAT REVIT ITSELF SAYS, AND THIS IS AN OFFLINE AUTHORITY, NOT A GUESS. The trap
index `data/api_traps/revit_api_traps.sqlite`, across all six versions:
`TessellatedShapeBuilder.AddFace` documents EXACTLY THREE exceptions — null, too
few loops/vertices, the set already closed; NOTHING about opposite-winding
pairs. But there is a named enum, `TessellatedBuildIssueType`, with a member
`EdgeTwiceUsedByFace`, and `TessellatedFace` documents that face data is set
ALWAYS, even when the input is invalid, and the builder checks it and REPAIRS it
where possible (`Build` is governed by a Target/Fallback pair, which includes
`Mesh`/`Salvage`). That is, for Revit this is a TYPED BUILD OUTCOME WITH REPAIR,
not an invalid input: our law was refusing EARLIER than Revit would ever see the
geometry.

WHAT THIS SECTION DOES NOT PROVE, STATED PLAINLY: there was no live Revit here.
That `Build` genuinely assembles a set with a seam is a conclusion from the
documentation, not a measurement. The condition for verification: one live run,
a DirectShape from a mesh with a seam, `TessellatedBuildIssue` recorded as a
number.

ABOUT CONNECTEDNESS — THIS IS AN API FACT, NOT TASTE. For
TessellatedShapeBuilder the unit of construction is called a connected face set:
OpenConnectedFaceSet/CloseConnectedFaceSet bound ONE connected component.
Folding two disconnected components into one such set is a violation of the
API's contract, and Revit's behavior there is undefined. So a disconnected mesh
here is a NAMED refusal, one that reports the number of components found and
says what to do (one operation per component), rather than a silent attempt to
build who-knows-what.

Connectedness is computed GEOMETRICALLY, not by indices, and this is essential.
A huge share of real meshes arrive as a "soup of triangles": each face has its
own three vertices, and by index such a mesh falls apart into N components even
though it is physically a single piece. Refusing it would mean refusing the most
ordinary input there is. So, for the CONNECTEDNESS CHECK, vertices that coincide
to within _WELD_TOL_MM are treated as one point — while the input itself is not
changed by one iota: the welding lives only inside the check and does not leak
outward.

NUMERIC LIMITS (measured 29.07, live compile service :52412, 2021 and 2026). The
vertex array is emitted ONCE plus an index array, so the source size grows
linearly and has no cliff:

    verts   tris    C# chars     2021      2026
       30      48         2 729     22ms      7ms
      840   1 600        49 453     26ms     28ms
     1 624   3 136        99 469     50ms     49ms
     3 280   6 400       208 153    111ms     92ms
     6 384  12 544       411 877    187ms    182ms

That is, Roslyn is NOT the bottleneck: ~33 characters and ~15 µs per triangle,
linear, with no cliff. The MAX_TRIANGLES=4096 limit was chosen from this
measurement with margin (≈135 KB of source, ≈65 ms of compilation — a third of
the heaviest case measured), and HONESTLY IS NOT the build-time limit inside a
live Revit: how long Revit takes to assemble 4096 faces inside a transaction is
not measured offline at all, and the bridge cuts execute off at 200s. This limit
is allowed to be LOWERED by the result of a live run and forbidden to be raised
silently.

_COORD_MAX_MM, unlike the face-count limit, is NOT BACKED BY A MEASUREMENT and is
honestly marked here as derived: Revit states it works within 20 miles
(32 186 880 mm) of the internal origin, and 10 km was taken with margin inside
that limit, not fitted to it.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kir.diag import (
    Diagnostic, KirRefusal, TYPE_BAD_TYPE, TYPE_BOUNDS, TYPE_GEOM_RELATION,
)
from kir.registry_base import COORD_LIMIT_MM
from kir.emit_utils import is_finite_number

#: The mesh fell apart into several pieces — see "ABOUT CONNECTEDNESS" above.
# M006, NOT M001 (10.08.2026): `KIR-M001` carried TWO names in two
# subsystems — `macros.MACRO_ERROR` (macro expansion) and this one. It was the
# mesh that drifted, not the macro: the macro side is pinned in tests by FIFTEEN
# literals, while this one is pinned by a single constant, so moving it here
# costs one line instead of fifteen. Not a single consumer in prod branches on
# `M001`.
MESH_DISCONNECTED = "KIR-M006"
#: A triangle references a vertex that doesn't exist.
MESH_INDEX_RANGE = "KIR-M002"
#: A degenerate triangle: a repeated index, a short edge, or zero area.
MESH_DEGENERATE = "KIR-M003"
#: A vertex that no triangle references.
MESH_UNUSED_VERTEX = "KIR-M004"
#: The same triple of vertices occurs twice.
MESH_DUPLICATE_FACE = "KIR-M005"

#: 🔴 RAISING IT TO 16384 WAS REQUESTED ON 02.09.2026 — REFUSED, AND HERE IS WHY.
#:
#: 1. THE HARM FROM THE OLD NUMBER EQUALS ZERO, AND THIS IS MEASURED. A census
#:    of 110 real families (283 shapes) gives NOT A SINGLE refusal on triangle
#:    count: all 37 refusals are `sweep_profile_is_family_symbol` 20,
#:    `sweep_path_unavailable` 6, `void_form_is_not_a_prism` 5,
#:    `profile_rejected_by_contour` 3, `profile_rings_not_a_region` 2,
#:    `sweep_path_not_expressible` 1. A mesh arrives via the AUTHORING path
#:    (`create_directshape`), not via a lift, and it is not in the corpus at
#:    all. A limit that rejects nothing has no reason to be raised: this is an
#:    invented gate in reverse.
#:
#: 2. WHAT THIS LIMIT ACTUALLY HOLDS IS STATED IN THIS SAME FILE'S HEADER, AND
#:    IT IS NOT ROSLYN. Compilation is measured up to 12 544 triangles and is
#:    linear (~33 characters and ~15 µs per triangle); what the limit actually
#:    holds is the BUILD TIME IN A LIVE REVIT inside a transaction, and that is
#:    not measured offline at all, while the bridge cuts `execute` off at 200s.
#:
#: 3. THE HEADER FORBIDS RAISING THIS NUMBER SILENTLY — verbatim: "allowed to
#:    be LOWERED by the result of a live run and forbidden to be raised
#:    silently." There was no live run available to me, so raising it would be
#:    exactly what is forbidden. The condition for lifting it is named: one
#:    live run with a mesh at 16 384 faces, with the build time recorded as a
#:    number.
MAX_VERTICES = 4096
MAX_TRIANGLES = 4096

#: An edge shorter than this counts as degenerate. Exactly the same value and
#: the same reason as _EDGE_TOL in contour.py: Revit's ShortCurveTolerance,
#: statically.
_MIN_EDGE_MM = 1.0
#: A smaller area — three collinear points with long edges.
_MIN_AREA_MM2 = 1.0
#: Vertices closer to each other than this are ONE point FOR THE CONNECTEDNESS
#: CHECK.
_WELD_TOL_MM = 0.1
#: See the header: derived from Revit's 20-mile limit, not measured.
#: 🔴 THE HOUSE VALUE, NOT A COPY. Measured 25.08.2026: this quantity had THREE
#: carriers and TWO values — 16 000 000 in `registry_base` (and in
#: `authoring_validation`, which reads the house value as of that same day)
#: versus 10 000 000 here and in its neighbor. A point at 12 000 000 mm was
#: legal for a wall and illegal here.
#:
#: Both smaller numbers are derived from "Revit states it works within 20
#: miles", the house value from "operating envelope ~16 km". NEITHER IS
#: MEASURED, so the dispute is settled by whatever doesn't break what already
#: works: the house value is WIDER, and no program currently accepted will
#: become rejected. When Revit's limit is MEASURED, ONE number will change.
#:
#: The previous comment here honestly said: "repeated as a value with an
#: explicit source, because they must not silently drift apart." They drifted.
_COORD_MAX_MM = COORD_LIMIT_MM


def _bad(diags: list, code: str, oid, field: str, message: str,
         got: Any = None) -> None:
    diags.append(Diagnostic(code=code, op_id=oid, field_name=field, got=got,
                            message_ru=message))


def _components(tris: list, weld: list) -> list:
    """Connected components by WELDED vertices (union-find).

    `weld[i]` is the number of the point that vertex i is assigned to. Returns
    a list of components, each one a list of triangle indices; the order is
    stable.
    """
    parent = list(range(len(tris)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # the first triangle encountered for each welded point — this is enough:
    # any two triangles sharing a point will end up in the same set through
    # it.
    first: dict[int, int] = {}
    for ti, tri in enumerate(tris):
        for idx in tri:
            w = weld[idx]
            if w in first:
                union(first[w], ti)
            else:
                first[w] = ti
    groups: dict[int, list] = {}
    for ti in range(len(tris)):
        groups.setdefault(find(ti), []).append(ti)
    return [groups[k] for k in sorted(groups)]


def _weld_map(verts: list) -> list:
    """The welded-point number for each vertex (for connectedness only).

    A grid with cell side _WELD_TOL_MM, plus a scan of the 27 neighboring
    cells: two points closer than the tolerance are guaranteed to land either
    in the same cell or in a neighboring one, so the outcome does not depend
    on exactly where a cell boundary happens to fall.

    🔴 THIS IS TRANSITIVE CLOSURE, NOT A ROLL-CALL AGAINST A CELL
    REPRESENTATIVE, and the difference cost a refusal on LEGITIMATE input.
    "Closer than the tolerance" is not an equivalence relation: at a
    tolerance of 0.1 mm, A=0, B=0.09 and C=0.18 are pairwise linked through B
    and not linked directly. The previous version put the FIRST point
    encountered into a cell and compared new points only against such
    representatives: B got welded to A but never became a representative
    itself, and C found no one — the chain broke in the middle. A mesh whose
    only bridge was such a chain got `KIR-M006` "falls apart into 2
    disconnected pieces" — that is, a refusal of correct input, not a pass of
    incorrect input. On top of that, the answer DEPENDED ON THE ORDER of the
    vertices (the same input reversed gave a different partition), and vertex
    order is not a property of the geometry.

    So here it is union-find across all neighbors, with the class root being
    the MINIMAL number in it: the partition comes out the same regardless of
    input order.

    THE COST IS MEASURED, NOT ESTIMATED (02.09.2026, prod venv, at 4096
    vertices — the MAX_VERTICES ceiling; "previous" is the retired version,
    run side by side in the same pass, not recalled from memory):

        input                                      new      previous
        26×26 grid soup, shared corners duplicated 0.009 s   0.017 s
        4096 vertices AT ONE POINT (exact)         0.004 s   0.014 s
        4096 DIFFERENT points inside one cell      2.694 s   0.011 s

    On ordinary input, the closure turned out TWICE AS CHEAP as the previous
    roll-call — this is paid for by collapsing exact duplicates before the
    union-find (in a soup, there are as many of them as there are faces at a
    point). The third row is the honest worst case and the file's only
    nonlinear check: 4096 DIFFERENT points inside a 0.1 mm cube. Such input
    always ends in a refusal (the minimum face edge, 1.0 mm, is an order of
    magnitude above the weld tolerance), and `validate_mesh` calls the weld
    AFTER all the cheap laws — so that these seconds are only ever paid by
    input that couldn't be rejected earlier.
    """
    n = len(verts)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # the root is the SMALLER number: that way the class's name does
            # not depend on the order in which its points arrived.
            parent[max(ra, rb)] = min(ra, rb)

    # Exact matches are collapsed before the grid: in a soup of triangles
    # there are as many of them as there are faces at a point, and there is no
    # reason to pay for them with pairwise comparison — they are known in
    # advance to be one point.
    same: dict[tuple, int] = {}
    unique: list = []
    for i, v in enumerate(verts):
        exact = (v[0], v[1], v[2])
        first = same.get(exact)
        if first is None:
            same[exact] = i
            unique.append(i)
        else:
            union(first, i)

    cells: dict[tuple, list] = {}
    for i in unique:
        v = verts[i]
        key = (int(math.floor(v[0] / _WELD_TOL_MM)),
               int(math.floor(v[1] / _WELD_TOL_MM)),
               int(math.floor(v[2] / _WELD_TOL_MM)))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for j in cells.get((key[0] + dx, key[1] + dy,
                                        key[2] + dz), ()):
                        if find(j) == find(i):
                            continue          # already one class — nothing to measure
                        w = verts[j]
                        if (abs(w[0] - v[0]) <= _WELD_TOL_MM
                                and abs(w[1] - v[1]) <= _WELD_TOL_MM
                                and abs(w[2] - v[2]) <= _WELD_TOL_MM):
                            union(i, j)
        cells.setdefault(key, []).append(i)
    return [find(i) for i in range(n)]


def _tri_metrics(a: list, b: list, c: list) -> tuple:
    """(minimum edge, area) of a triangle, in mm and mm²."""
    def d(p, q):
        return math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
                         + (p[2] - q[2]) ** 2)
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    area = 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
    return min(d(a, b), d(b, c), d(c, a)), area


def mesh_bbox(verts: list) -> tuple:
    """(xmin, ymin, zmin, xmax, ymax, zmax) в мм."""
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def validate_mesh(mesh: Any, oid, field: str, diags: list, *,
                  allow_seam_faces: bool = False) -> Optional[dict]:
    """A mesh value -> {"vertices_mm": [[x,y,z]...], "triangles": [[i,j,k]...]}.

    Returns None and RECORDS a diagnostic on any violation. Fixes nothing and
    discards nothing: the input is either accepted whole, or a refusal is
    named.

    `allow_seam_faces` is the ONE THING the caller's contract decides, and
    what it decides is not the KIND of value, but tolerance for one kind of it
    (see "ABOUT THE SEAM" in the header). The default is STRICT: the
    authoring path gets the previous law, naming nothing. The observational
    path (round trip, escrow) is required to pass True EXPLICITLY —
    otherwise a foreign document's profile would become stricter than what
    Revit legitimately creates.

    A genuine DUPLICATE (the same winding) is rejected regardless of the
    flag's value.
    """
    if not isinstance(mesh, dict) or set(mesh) != {"vertices_mm", "triangles"}:
        _bad(diags, TYPE_BAD_TYPE, oid, field,
             f"{field}: меш — {{vertices_mm: [[x,y,z], ...], "
             f"triangles: [[i,j,k], ...]}} и ничего кроме", got=mesh)
        return None

    raw_v = mesh["vertices_mm"]
    if not isinstance(raw_v, list) or not (3 <= len(raw_v) <= MAX_VERTICES):
        _bad(diags, TYPE_BOUNDS, oid, f"{field}.vertices_mm",
             f"{field}: vertices_mm — от 3 до {MAX_VERTICES} вершин "
             f"(предел замерен, см. шапку mesh.py)",
             got=(len(raw_v) if isinstance(raw_v, list) else raw_v))
        return None
    verts: list = []
    for vi, v in enumerate(raw_v):
        if not isinstance(v, list) or len(v) != 3 \
                or not all(is_finite_number(c) for c in v):
            _bad(diags, TYPE_BAD_TYPE, oid, f"{field}.vertices_mm[{vi}]",
                 f"{field}: вершина — [x,y,z] из трёх конечных чисел в мм",
                 got=v)
            return None
        if any(abs(float(c)) > _COORD_MAX_MM for c in v):
            _bad(diags, TYPE_BOUNDS, oid, f"{field}.vertices_mm[{vi}]",
                 f"{field}: координата вне ±{_COORD_MAX_MM:.0f} мм — это "
                 f"вне рабочего пространства Revit, а не «далеко»", got=v)
            return None
        verts.append([float(v[0]), float(v[1]), float(v[2])])

    raw_t = mesh["triangles"]
    if not isinstance(raw_t, list) or not (1 <= len(raw_t) <= MAX_TRIANGLES):
        _bad(diags, TYPE_BOUNDS, oid, f"{field}.triangles",
             f"{field}: triangles — от 1 до {MAX_TRIANGLES} треугольников "
             f"(предел замерен, см. шапку mesh.py)",
             got=(len(raw_t) if isinstance(raw_t, list) else raw_t))
        return None
    n = len(verts)
    tris: list = []
    for ti, t in enumerate(raw_t):
        if not isinstance(t, list) or len(t) != 3 \
                or any(isinstance(i, bool) or not isinstance(i, int) for i in t):
            _bad(diags, TYPE_BAD_TYPE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: треугольник — [i,j,k] из трёх ЦЕЛЫХ номеров вершин",
                 got=t)
            return None
        if any(not (0 <= i < n) for i in t):
            _bad(diags, MESH_INDEX_RANGE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: треугольник ссылается на вершину вне списка "
                 f"(вершин {n}, допустимы номера 0..{n - 1})", got=t)
            return None
        if len(set(t)) != 3:
            _bad(diags, MESH_DEGENERATE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: треугольник повторяет вершину — это отрезок, "
                 f"а не грань", got=t)
            return None
        edge, area = _tri_metrics(verts[t[0]], verts[t[1]], verts[t[2]])
        if edge < _MIN_EDGE_MM:
            _bad(diags, MESH_DEGENERATE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: ребро {edge:.4f} мм короче {_MIN_EDGE_MM} мм "
                 f"(ShortCurveTolerance Revit статически)", got=t)
            return None
        if area < _MIN_AREA_MM2:
            _bad(diags, MESH_DEGENERATE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: площадь {area:.4f} мм² — три точки лежат на одной "
                 f"прямой", got=t)
            return None
        tris.append([int(t[0]), int(t[1]), int(t[2])])

    used = {i for t in tris for i in t}
    missing = sorted(set(range(n)) - used)
    if missing:
        _bad(diags, MESH_UNUSED_VERTEX, oid, f"{field}.vertices_mm",
             f"{field}: вершины {missing[:8]}"
             f"{' и ещё ' + str(len(missing) - 8) if len(missing) > 8 else ''} "
             f"не участвуют ни в одном треугольнике — построен был бы не тот "
             f"меш, который прислан", got=len(missing))
        return None

    # 🔴 THE WELD IS COMPUTED ONCE AND SERVES TWO LAWS, NOT ONE. Before
    # 02.09.2026 the duplicate-face guard compared RAW VERTEX NUMBERS, while
    # the weld, which knows geometric identity, was computed a line further
    # down and only for connectedness. Soup-style export gives each face its
    # own vertices, so the same physical face would arrive twice under
    # different numbers and get ACCEPTED, while the same input written with
    # shared numbers got rejected: two answers to one question about
    # GEOMETRY.
    #
    # It stands here, not earlier in the loop, BECAUSE OF COST: the weld is
    # the file's only nonlinear check (measured in the `_weld_map` header:
    # 2.7 s at 4096 different points inside one cell versus 0.009 s on
    # ordinary soup), and all the cheap laws are required to have had their
    # chance to refuse before it runs.
    weld = _weld_map(verts)
    seen_faces: dict = {}
    for ti, t in enumerate(tris):
        # A face's key is its WELDED points, not vertex numbers. Degeneracy
        # is checked above deliberately: a triangle whose own vertices got
        # welded together is degenerate, and calling it a "duplicate face"
        # would send the author down the wrong path.
        ids = [weld[i] for i in t]
        points = tuple(sorted(ids))
        # 🔴 THE WINDING IS NOT DISCARDED. The canonical rotation is the
        # triple started from the smallest number. For two faces on the SAME
        # set of points, it matches exactly when their normals point the
        # same way: this is a fact of combinatorics, not a floating-point
        # measurement, and so it has neither a tolerance nor an "almost"
        # case.
        start = ids.index(min(ids))
        winding = tuple(ids[start:] + ids[:start])
        known = seen_faces.get(points)
        if known is None:
            seen_faces[points] = {winding: ti}
            continue
        prev = known.get(winding)
        if prev is not None:
            _bad(diags, MESH_DUPLICATE_FACE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: грань {ti} (вершины {t}) описывает те же три "
                 f"точки И ТУ ЖЕ обмотку, что грань {prev} (вершины "
                 f"{tris[prev]}) — сдвоенная грань, а не шов. Поверхность "
                 f"описана вдвое: объём и нормаль в этом месте двусмысленны. "
                 f"Вершины ближе {_WELD_TOL_MM} мм друг к другу считаются "
                 f"ОДНОЙ точкой, поэтому разные номера вершин ту же грань "
                 f"не делают другой",
                 got={"род": "дубль", "грань": t, "против": tris[prev]})
            return None
        if not allow_seam_faces:
            other = next(iter(known.values()))
            _bad(diags, MESH_DUPLICATE_FACE, oid, f"{field}.triangles[{ti}]",
                 f"{field}: грань {ti} (вершины {t}) лежит на тех же трёх "
                 f"точках, что грань {other} (вершины {tris[other]}), и "
                 f"обмотка у них ВСТРЕЧНАЯ — это ШОВ двух склеенных тел. "
                 f"Авторский контракт его не принимает: один DirectShape — "
                 f"одно тело, и склейку надо либо разнять на две операции, "
                 f"либо не описывать общую плоскость дважды. (Прочитанной из "
                 f"Ревита геометрии шов РАЗРЕШЁН — см. «ПРО ШОВ» в шапке "
                 f"mesh.py)",
                 got={"род": "шов", "грань": t, "против": tris[other]})
            return None
        known[winding] = ti

    comps = _components(tris, weld)
    if len(comps) != 1:
        _bad(diags, MESH_DISCONNECTED, oid, field,
             f"{field}: меш распадается на {len(comps)} несвязных кусков "
             f"(размеры {sorted((len(c) for c in comps), reverse=True)[:6]} "
             f"треугольников). Один DirectShape строится ОДНИМ связным "
             f"набором граней — отправь по операции на кусок",
             got=len(comps))
        return None

    return {"vertices_mm": verts, "triangles": tris}


# ─────────────────────────────────── CONSTRUCTOR: CONTOUR + HEIGHT -> MESH

#: The tolerance for checking "the triangles covered the contour exactly".
#: Relative, because a floor's area is 1e7…1e8 mm², and an absolute tolerance
#: means nothing there.
_COVER_REL_TOL = 1e-9

#: The coordinate rounding grid used when welding the CONSTRUCTOR's vertices.
#: This is NOT welding the input (there is none here, and there won't be):
#: the points are born right here, from a single contour, and either match
#: bit for bit or don't match at all. The rounding guards against the
#: triangulator returning the same vertex with a different last mantissa bit.
_VERTEX_KEY_NDIGITS = 6


def _ring_points(ring: Any, what: str) -> list:
    """A ring -> a list of (x, y) WITHOUT the closing repeat. A refusal
    instead of a fix."""
    pts: list = []
    for i, p in enumerate(ring or ()):
        if isinstance(p, dict):
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=None, field_name=f"{what}[{i}]",
                message_ru=(f"{what}: точка — [x, y] из двух чисел в мм, "
                         f"а не словарь"), got=p)])
        # 🔴 THE THIRD COORDINATE IS NAMED, NOT SILENTLY DROPPED. Before
        # 02.09.2026 this line read `x, y = float(p[0]), float(p[1])`, and a
        # ring at elevation 50 mm was accepted with the elevation lost — a
        # silent correction of the input, exactly the kind that has already
        # cost this house 96.77% of the groups. The contour is FLAT by
        # design: the height comes from `height_mm`, the direction from
        # `path`, and a nonzero Z in the ring means the author meant
        # something other than what would have been built.
        if isinstance(p, (list, tuple)) and len(p) > 2:
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=None, field_name=f"{what}[{i}]",
                message_ru=(f"{what}: точка несёт {len(p)} координаты, третья "
                         f"— {p[2]}. Кольцо здесь ПЛОСКОЕ: высоту задаёт "
                         f"height_mm у extrude и path у sweep, а уронить Z "
                         f"молча значило бы построить не то тело. Убери "
                         f"третью координату сам либо подними тело "
                         f"base_z_mm/путём"), got=list(p))])
        try:
            x, y = float(p[0]), float(p[1])
        except Exception:
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=None, field_name=f"{what}[{i}]",
                message_ru=f"{what}: точка — [x, y] из двух чисел в мм", got=p)])
        if not (is_finite_number(x) and is_finite_number(y)):
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=None, field_name=f"{what}[{i}]",
                message_ru=f"{what}: координата должна быть конечным числом",
                got=p)])
        pts.append((x, y))
    # A closing repeat is a legitimate ring shape (shapely writes it too), so
    # it is stripped, not refused. A repeat INSIDE the ring is a different
    # matter: that is a zero-length edge, and the mesh validator catches it
    # by name.
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=None, field_name=what,
            message_ru=(f"{what}: у кольца {len(pts)} различных точек, а контур "
                     f"начинается с трёх"), got=len(pts))])
    return pts


def _polygon_from_contour(contour: Any, field: str = "contour"):
    """An author's contour -> a shapely Polygon. FOUR shapes, all of them
    named.

    There is deliberately no fifth shape: a shape that cannot be written
    cannot be confused with another either (the same rule as the slot
    selector in `dsl.py`).
    """
    # 🔴 ALL OF THIS FUNCTION'S IMPORTS LIVE IN ONE PLACE, INCLUDING THE
    # REFUSAL PATH. `explain_validity` used to live further down, inside the
    # "contour is invalid" branch, and a live run on 19.08 showed the cost:
    # the happy path worked (`shapely` was warmed up), while the REFUSAL
    # crashed with `KIR-B004: импорт 'shapely.validation' запрещён` and
    # `blame: author` — that is, the message about self-intersection got
    # replaced by blaming the author for OUR OWN import. `import shapely`
    # does not pull in the submodule (measured: 35 submodules in
    # sys.modules, `validation` is not among them). The import on the
    # refusal path is required to stand in the same place as the import on
    # the success path.
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient
    from shapely.validation import explain_validity

    poly = None
    if hasattr(contour, "geom_type"):                      # 1. shapely
        kind = contour.geom_type
        if kind == "Polygon":
            # The same extra coordinate as for a raw ring, just arriving in a
            # different shape. Before 02.09.2026 a shapely polygon with Z was
            # not rejected anywhere and made it all the way to `pair(*p)`,
            # where it crashed with OUR OWN traceback: `TypeError: pair()
            # takes 2 positional arguments but 3 were given` — no code, no
            # field, and no next move. The same input is required to get the
            # same answer in both shapes.
            if getattr(contour, "has_z", False):
                zs = sorted({c[2] for c in contour.exterior.coords
                             if len(c) > 2})
                raise KirRefusal([Diagnostic(
                    code=TYPE_BAD_TYPE, op_id=None, field_name=f"{field}[0]",
                    message_ru=(
                        f"{field}: Polygon несёт третью координату "
                        f"(Z: {zs[:4]}). Кольцо здесь ПЛОСКОЕ: высоту задаёт "
                        f"height_mm у extrude и path у sweep. Сними Z сам — "
                        f"`shapely.force_2d(poly)`, — чтобы правка входа была "
                        f"ТВОЕЙ и видимой"),
                    got=zs[:8])])
            poly = contour
        elif kind == "MultiPolygon":
            raise KirRefusal([Diagnostic(
                code=MESH_DISCONNECTED, op_id=None, field_name=field,
                message_ru=(
                    f"контур распался на {len(contour.geoms)} несвязных куска "
                    f"— так возвращает булева операция shapely, когда разность "
                    f"разрезала фигуру. Один DirectShape строится ОДНИМ связным "
                    f"набором граней: выдави каждый кусок отдельно "
                    f"(`for piece in result.geoms: extrude(piece, h)`)"),
                got=len(contour.geoms))])
        else:
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=None, field_name=field,
                message_ru=(f"контур — Polygon, а пришёл {kind}. Линия и точка "
                         f"площади не имеют, выдавливать нечего"), got=kind)])
    elif isinstance(contour, dict):                        # 2. {outer, holes}
        unknown = set(contour) - {"outer", "holes"}
        if unknown:
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=None, field_name=field,
                message_ru=(f"контур-словарь знает только outer и holes, "
                         f"пришло лишнее: {sorted(unknown)}"),
                got=sorted(unknown))])
        outer = _ring_points(contour.get("outer"), f"{field}.outer")
        holes = [_ring_points(h, f"{field}.holes[{i}]")
                 for i, h in enumerate(contour.get("holes") or ())]
        poly = Polygon(outer, holes)
    elif isinstance(contour, (list, tuple)):               # 3./4. a ring or rings
        first = contour[0] if len(contour) else None
        nested = (isinstance(first, (list, tuple))
                  and len(first)
                  and isinstance(first[0], (list, tuple)))
        if nested:
            rings = [_ring_points(r, f"{field}[{i}]")
                     for i, r in enumerate(contour)]
            poly = Polygon(rings[0], rings[1:])
        else:
            poly = Polygon(_ring_points(contour, field))
    if poly is None:
        raise KirRefusal([Diagnostic(
            code=TYPE_BAD_TYPE, op_id=None, field_name=field,
            message_ru=("контур — список точек [[x,y], ...], список колец "
                     "[внешнее, дыра, ...], словарь {outer, holes} либо "
                     "shapely Polygon"), got=type(contour).__name__)])

    if not poly.is_valid:
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=None, field_name=field,
            message_ru=(f"контур не является правильным многоугольником: "
                     f"{explain_validity(poly)}. Починка формы здесь ЗАПРЕЩЕНА "
                     f"— тихая правка входа уже стоила этому дому 96.77 % "
                     f"групп; поправь контур сам либо позови "
                     f"`contour.buffer(0)` явно, чтобы правка была ТВОЕЙ"),
            got=explain_validity(poly))])
    if poly.area < _MIN_AREA_MM2:
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=None, field_name=field,
            message_ru=(f"площадь контура {poly.area:.4f} мм² меньше "
                     f"{_MIN_AREA_MM2} мм² — выдавливать нечего"),
            got=poly.area)])
    # Exterior counterclockwise, holes clockwise: that way walking the rings
    # gives the side faces ONE normal orientation with not a single branch
    # further down.
    return orient(poly, sign=1.0)


def _triangulate(poly: Any, field: str) -> list:
    """Triangles that covered the contour exactly — or a refusal.

    Extracted out of `extrude` on 19.08.2026, when `sweep` needed the same
    law. Not a copy: the coverage law is required to live in ONE place,
    otherwise two constructors would drift apart in tolerance, and drift
    silently. This is exactly how every hand-written list in this tree has
    ever drifted, and not a single generated one.

    🔴 THE TRIANGULATOR WAS CHOSEN BY MEASUREMENT, NOT BY NAME:
    `delaunay_triangles` — the closest neighbor by name — fills in holes and
    gives a 33% overcount WITHOUT A SINGLE COMPLAINT. So we call
    `constrained_delaunay_triangles` and CHECK the coverage: a triangulation
    that did not cover the contour is a refusal, not an approximation.
    """
    import shapely

    parts = shapely.constrained_delaunay_triangles(poly)
    faces = list(getattr(parts, "geoms", ()) or ())
    covered = sum(f.area for f in faces)
    if not faces or abs(covered - poly.area) > _COVER_REL_TOL * max(
            poly.area, 1.0):
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=None, field_name=field,
            message_ru=(
                f"триангуляция покрыла {covered:.3f} мм² при площади контура "
                f"{poly.area:.3f} мм² — расхождение {covered - poly.area:+.3f}. "
                f"Меш строился бы не по этому контуру, поэтому здесь отказ, а "
                f"не приближение"),
            got=covered - poly.area)])
    return faces


def extrude(contour: Any, height_mm: Any, *, base_z_mm: Any = 0.0) -> dict:
    """A CONTOUR EXTRUDED VERTICALLY — a ready-made value for
    `create_directshape.mesh`.

        prism = extrude([[0, 0], [6000, 0], [6000, 4000], [0, 4000]], 3000)
        create_directshape(mesh=prism, category="generic_model", name="Ядро")

    WHY IT EXISTS, BY MEASUREMENT. Before 19.08.2026, an author who needed an
    arbitrary shape had to spell it out by hand as VERTICES AND TRIANGLES: a
    box — 8 vertices and 12 index triples, with no way to check yourself
    before the run. A building made of such shapes simply does not get
    written.

    🔴 THE TRIANGULATOR HERE IS NOT OURS, AND IT WAS CHOSEN BY MEASUREMENT,
    NOT BY NAME: the closest neighbor by name fills in holes with a 33%
    overcount and not a single complaint. The measurement and the coverage
    check live IN ONE PLACE — `_triangulate`, shared with `sweep`.

    WHAT THIS CONSTRUCTOR DOES NOT DO:

    * It does NOT fix the contour. Self-intersection, a hole outside, zero
      area — a named refusal. Want `buffer(0)`? Write it yourself: correcting
      the input is required to be YOURS and visible;
    * It does NOT weld the input's vertices (the law in `mesh.py`) and does
      not discard degenerate triangles: the validator names them by name;
    * It does NOT do 3D booleans — there is no library for that in the
      sandbox at all (`shapely` is flat, `numpy` is about arrays). Planar
      booleans exist and work today: `extrude(a.difference(b), 3000)`,
      because a shapely Polygon is a legitimate contour shape. A result cut
      into pieces is refused by name, rather than being built as one mesh
      out of two solids;
    * It does NOT extrude at an angle and does NOT taper — only vertically.

    Returns `{"vertices_mm": [...], "triangles": [...]}` that has passed
    `validate_mesh` RIGHT HERE: the constructor cannot hand back a mesh that
    the compiler would reject, and that is a guarantee by construction, not
    one that was merely checked.
    """
    import shapely

    if isinstance(height_mm, bool) or not is_finite_number(height_mm):
        raise KirRefusal([Diagnostic(
            code=TYPE_BAD_TYPE, op_id=None, field_name="height_mm",
            message_ru="высота — конечное число в мм", got=height_mm)])
    height = float(height_mm)
    if height <= _MIN_EDGE_MM:
        raise KirRefusal([Diagnostic(
            code=TYPE_BOUNDS, op_id=None, field_name="height_mm",
            message_ru=(f"высота {height:g} мм не больше {_MIN_EDGE_MM} мм — "
                     f"выдавленное тело выродилось бы в плоскость. Вниз "
                     f"выдавливают отрицательным base_z_mm, а не высотой"),
            got=height)])
    if isinstance(base_z_mm, bool) or not is_finite_number(base_z_mm):
        raise KirRefusal([Diagnostic(
            code=TYPE_BAD_TYPE, op_id=None, field_name="base_z_mm",
            message_ru="отметка низа — конечное число в мм", got=base_z_mm)])
    base_z = float(base_z_mm)

    poly = _polygon_from_contour(contour)
    faces = _triangulate(poly, "contour")

    verts: list = []
    index: dict = {}

    def pair(x: float, y: float) -> tuple:
        """(bottom vertex number, top vertex number) for a plan point."""
        key = (round(x, _VERTEX_KEY_NDIGITS), round(y, _VERTEX_KEY_NDIGITS))
        got = index.get(key)
        if got is None:
            got = (len(verts), len(verts) + 1)
            verts.append([x, y, base_z])
            verts.append([x, y, base_z + height])
            index[key] = got
        return got

    tris: list = []
    for face in faces:
        ring = list(face.exterior.coords)[:-1]
        if len(ring) != 3:                       # belt: GEOS promises triples
            raise KirRefusal([Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=None, field_name="contour",
                message_ru=(f"триангулятор вернул грань на {len(ring)} вершин — "
                         f"это не треугольник, и молча принять её нельзя"),
                got=len(ring))])
        # 🔴 A TRIANGLE'S WINDING IS COMPUTED, NOT ASSUMED. The first version
        # CLAIMED that GEOS returns faces counterclockwise, and laid out the
        # caps on that assumption. Measured by volume: a 6×4×3 box gave
        # 24 000 000 000 mm³ instead of 72 000 000 000 — exactly a third,
        # because the top cap faced DOWNWARD. Our named class of defect: a
        # quantity is CLAIMED in one place and READ in another. The cure is
        # the same as always — ask the authority (the coordinates
        # themselves).
        area2 = ((ring[1][0] - ring[0][0]) * (ring[2][1] - ring[0][1])
                 - (ring[2][0] - ring[0][0]) * (ring[1][1] - ring[0][1]))
        ccw = ring if area2 > 0 else [ring[0], ring[2], ring[1]]
        (a0, a1), (b0, b1), (c0, c1) = (pair(*p) for p in ccw)
        tris.append([a0, c0, b0])                # bottom faces downward
        tris.append([a1, b1, c1])                # top faces upward

    for ring in [poly.exterior, *poly.interiors]:
        pts = list(ring.coords)[:-1]
        for i, p in enumerate(pts):
            q = pts[(i + 1) % len(pts)]
            (pb, pt), (qb, qt) = pair(*p), pair(*q)
            tris.append([pb, qb, qt])
            tris.append([pb, qt, pt])

    diags: list = []
    mesh = validate_mesh({"vertices_mm": verts, "triangles": tris},
                         None, "mesh", diags)
    if mesh is None:
        raise KirRefusal(diags)
    return mesh


# ─────────────────────────────────────────────────────────────────────────────
# SWEEP — A PROFILE CARRIED ALONG A PATH
# ─────────────────────────────────────────────────────────────────────────────

#: A miter leg must not travel along a segment farther than this fraction of
#: its length. 0.5 is NOT a tuned threshold but a boundary BY CONSTRUCTION: a
#: leg eats into the segment from both ends, at 0.5 two legs meet exactly at
#: a point, at anything larger they pass through each other and the solid
#: self-intersects. The number is derived, not measured, and is declared as
#: such.
_MITER_SPAN_FRACTION = 0.5

#: The sine of the angle between the tangent and the "up" axis, below which
#: the axis is unusable: the frame would degenerate into a point, not
#: "almost degenerate".
_UP_MIN_SIN = 1e-6

#: Below this length, the sum of the unit tangents is treated as zero — the
#: path reverses by 180°, and such an angle has no bisector at all.
_REVERSAL_TOL = 1e-9


def _v_sub(a, b): return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
def _v_add(a, b): return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
def _v_mul(a, k): return [a[0] * k, a[1] * k, a[2] * k]
def _v_dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _v_cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _v_len(a): return math.sqrt(_v_dot(a, a))


def _rodrigues(v, k, ang):
    """Rotates vector `v` around the unit axis `k` by the angle `ang`."""
    c, s = math.cos(ang), math.sin(ang)
    return _v_add(_v_add(_v_mul(v, c), _v_mul(_v_cross(k, v), s)),
                  _v_mul(k, _v_dot(k, v) * (1.0 - c)))


def _mesh_volume(verts: list, tris: list) -> float:
    """The volume of a closed surface via the divergence theorem.

    Not decoration: it catches an INVERTED winding that cannot be seen by
    eye in a list of indices. Measured 19.08.2026 on a box — a claimed (not
    computed) winding gave 24 000 000 000 mm³ instead of 72 000 000 000,
    exactly a third, because the top cap faced downward.

    🔴 THE ORIGIN USED IS THE SOLID'S OWN, NOT THE COORDINATE ORIGIN, AND
    THIS IS NOT DECORATION. A tetrahedron's term grows as the CUBE of the
    coordinate, while the answer stays small: at legitimate coordinates (the
    ±_COORD_MAX_MM limit), catastrophic cancellation sets in, and the volume
    verdict becomes a property of WHERE the solid stands, not what shape it
    is. Measured 02.09.2026, a 1.415×1.415 profile along a 100 mm path, true
    volume 200.2225 mm³:

        at the coordinate origin        200.2225     built
        shifted by 10 000 000 mm      -44466.307    KIR-T004 "not positive"
        the same, profile centered      7616.760      ACCEPTED, off by 38x

    The second row is a refusal of correct input, the third is worse: a
    wrong number that nobody argues with. The volume of a closed surface
    does not depend on the choice of origin AT ALL, so the shift is an
    identity, not a tolerance: it "smooths" nothing, and still hands back an
    inverted winding with a minus sign.
    """
    if not verts or not tris:
        return 0.0
    x0, y0, z0, x1, y1, z1 = mesh_bbox(verts)
    origin = [(x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0]
    total = 0.0
    for i, j, k in tris:
        a = _v_sub(verts[i], origin)
        b = _v_sub(verts[j], origin)
        c = _v_sub(verts[k], origin)
        total += _v_dot(a, _v_cross(b, c))
    return total / 6.0


def _path_points(path: Any, field: str) -> list:
    if not isinstance(path, (list, tuple)) or len(path) < 2:
        raise KirRefusal([Diagnostic(
            code=TYPE_BAD_TYPE, op_id=None, field_name=field,
            message_ru=("траектория — список из ДВУХ И БОЛЕЕ точек "
                        "[[x,y,z], ...]; двумерная точка [x,y] читается как "
                        "z=0. Одной точки мало: вести профиль некуда"),
            got=(len(path) if isinstance(path, (list, tuple))
                 else type(path).__name__))])
    pts: list = []
    for i, p in enumerate(path):
        if not isinstance(p, (list, tuple)) or len(p) not in (2, 3):
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=None, field_name=f"{field}[{i}]",
                message_ru="точка траектории — [x,y] либо [x,y,z] в мм",
                got=p)])
        if any(isinstance(c, bool) or not is_finite_number(c) for c in p):
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=None, field_name=f"{field}[{i}]",
                message_ru="координаты точки траектории — конечные числа в мм",
                got=p)])
        coords = [float(c) for c in p]
        if len(coords) == 2:
            coords.append(0.0)
        pts.append(coords)
    return pts


def sweep(profile: Any, path: Any, *, up: Any = None) -> dict:
    """A PROFILE CARRIED ALONG A POLYLINE — a ready-made value for
    `create_directshape.mesh`.

        rail = sweep([[-30, 0], [30, 0], [30, 60], [-30, 60]],
                     [[0, 0, 0], [4000, 0, 0], [4000, 0, 3000]])
        create_directshape(mesh=rail, category="generic_model", name="Поручень")

    WHY IT EXISTS. `extrude` carries a contour strictly vertically; anything
    that follows a PATH — a handrail along a stair flight, a cornice along a
    bent facade, a duct along a route — an author before 19.08.2026 had no
    way to say except by a hand-built mesh, and the census named this as OUR
    debt (unlike 3D booleans, which are not in the sandbox at all).

    HOW THE PROFILE IS READ. A flat contour in ITS OWN coordinates: `x` is to
    the right of the direction of travel, `y` is up. The profile is placed
    where you wrote it: you center it yourself, because "moving it for the
    author" is a silent correction of the input, and that is forbidden in
    this file.

    THE JOINT IS A MITER, and this is not decoration: at a turn the profile is
    cut by the BISECTOR, so the two segments meet with no gap and no overlap.
    Hence the one boundary you need to know: at a turn, the cross-section
    across the segment is wider than the profile by a factor of
    1/cos(half the angle) — that is how a miter works, and how a cornice is
    actually cut in the field.

    WHAT THIS CONSTRUCTOR DOES NOT DO:

    * It does NOT smooth the corner. The polyline stays a polyline; there is
      no arc, and there is no way to say a fillet radius;
    * It does NOT twist the profile along the path. The frame is transported
      in parallel (the minimum-length rotation from segment to segment), so
      the handrail does not twist on its own. There is no way to specify
      twist — the language has none;
    * It does NOT save you from self-intersection on a sharp turn: a miter
      leg that eats more than half of the neighboring segment is a NAMED
      refusal, not "somehow handled";
    * It does NOT fix the profile (write `buffer(0)` yourself) and does NOT
      weld the input's vertices — the `mesh.py` laws are the same as for
      `extrude`.

    🔴 WHAT IS CHECKED, AND WHAT IS ONLY NAMED. A straight path gives a
    volume of EXACTLY `area × length`, a planar miter gives `area × path
    length` for a centered profile; both quantities are pinned by a control.
    For a NON-PLANAR polyline no such equality exists and none can be
    promised: there, a miter joins two planes that do not lie in one, and the
    volume depends on the profile's shape. What still guards it there is the
    sign of the volume and `validate_mesh`, and that is less than an
    equality — stated plainly, not left unsaid.
    """
    # 🔴 THE FIELD NAME TRAVELS INTO CONTOUR PARSING, NOT HARD-CODED IN IT.
    # The author wrote `profile`, and a refusal naming `contour` would send
    # them off to fix a field they never wrote. The first version of `sweep`
    # did exactly that — caught by a run of refusals, not by reasoning.
    poly = _polygon_from_contour(profile, "profile")
    faces = _triangulate(poly, "profile")
    pts = _path_points(path, "path")

    dirs: list = []
    lens: list = []
    for i in range(len(pts) - 1):
        raw = _v_sub(pts[i + 1], pts[i])
        length = _v_len(raw)
        if length <= _MIN_EDGE_MM:
            raise KirRefusal([Diagnostic(
                code=TYPE_BOUNDS, op_id=None, field_name=f"path[{i + 1}]",
                message_ru=(f"звено {i}→{i + 1} длиной {length:g} мм не больше "
                            f"{_MIN_EDGE_MM} мм. Повторённая точка траектории "
                            f"выглядит как звено и звеном не является"),
                got=length)])
        dirs.append(_v_mul(raw, 1.0 / length))
        lens.append(length)

    for i in range(1, len(dirs)):
        if _v_len(_v_add(dirs[i - 1], dirs[i])) < _REVERSAL_TOL:
            raise KirRefusal([Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=None, field_name=f"path[{i}]",
                message_ru=(f"в точке {i} путь разворачивается НА 180°. У такого "
                            f"угла нет биссектрисы, значит нет и уса: тело "
                            f"наложилось бы само на себя"),
                got=i)])

    # ── the "up" axis: it defines which way is up for the profile, and is
    # required not to lie along the path
    if up is None:
        candidates, explicit = ([0.0, 0.0, 1.0], [0.0, 1.0, 0.0]), False
    else:
        if (not isinstance(up, (list, tuple)) or len(up) != 3
                or any(isinstance(c, bool) or not is_finite_number(c)
                       for c in up)):
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=None, field_name="up",
                message_ru="ось «вверх» — [x,y,z] из конечных чисел", got=up)])
        candidates, explicit = ([float(c) for c in up],), True

    w0 = None
    for cand in candidates:
        clen = _v_len(cand)
        if clen < _UP_MIN_SIN:
            continue
        unit_c = _v_mul(cand, 1.0 / clen)
        perp = _v_sub(unit_c, _v_mul(dirs[0], _v_dot(unit_c, dirs[0])))
        if _v_len(perp) >= _UP_MIN_SIN:
            w0 = _v_mul(perp, 1.0 / _v_len(perp))
            break
    if w0 is None:
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=None, field_name="up",
            message_ru=("ось «вверх» лежит вдоль первого звена пути — у профиля "
                        "не остаётся плоскости. Назови другую ось: она решает, "
                        "какая сторона профиля верх"),
            got=up if explicit else "по умолчанию Z, запасная Y")])
    # (U, W, d) is a right-handed triple: U = W × d, so U × W = d — the same
    # relationship `extrude` has between X, Y and Z, so the side faces'
    # winding further down is computed by exactly the same expression.
    frames = [(_v_cross(w0, dirs[0]), w0)]
    for i in range(1, len(dirs)):
        axis = _v_cross(dirs[i - 1], dirs[i])
        sin_a, cos_a = _v_len(axis), _v_dot(dirs[i - 1], dirs[i])
        u_prev, w_prev = frames[-1]
        if sin_a > 1e-12:
            k = _v_mul(axis, 1.0 / sin_a)
            ang = math.atan2(sin_a, cos_a)
            u_prev, w_prev = _rodrigues(u_prev, k, ang), _rodrigues(w_prev, k, ang)
        frames.append((u_prev, w_prev))

    # ── the profile's rings at each point of the path: one ring per joint,
    # otherwise a gap
    verts: list = []
    index: dict = {}

    def place(i: int, a: float, b: float) -> int:
        key = (i, round(a, _VERTEX_KEY_NDIGITS), round(b, _VERTEX_KEY_NDIGITS))
        got = index.get(key)
        if got is not None:
            return got
        seg = 0 if i == 0 else i - 1              # the incoming segment at this point
        u_ax, w_ax = frames[seg]
        offset = _v_add(_v_mul(u_ax, a), _v_mul(w_ax, b))
        shift = 0.0
        if 0 < i < len(pts) - 1:
            normal = _v_add(dirs[i - 1], dirs[i])
            normal = _v_mul(normal, 1.0 / _v_len(normal))
            shift = -_v_dot(offset, normal) / _v_dot(dirs[i - 1], normal)
            room = _MITER_SPAN_FRACTION * min(lens[i - 1], lens[i])
            if abs(shift) > room:
                raise KirRefusal([Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=None,
                    field_name=f"path[{i}]",
                    message_ru=(
                        f"ус митры в точке {i} уходит вдоль звена на "
                        f"{abs(shift):.1f} мм при запасе {room:.1f} мм "
                        f"(половина короткого соседнего звена). Тело наложилось "
                        f"бы само на себя: поворот слишком крут для такого "
                        f"профиля, либо звено слишком коротко. Разведи точки "
                        f"пути или сузь профиль"),
                    got=abs(shift))])
        point = _v_add(_v_add(pts[i], offset), _v_mul(dirs[seg], shift))
        got = len(verts)
        verts.append(point)
        index[key] = got
        return got

    tris: list = []
    last = len(pts) - 1

    # ── the caps. The winding is COMPUTED from the profile's coordinates,
    # not assumed: it was exactly this assumption that once made the
    # `extrude` box come out at a third of its volume.
    for face in faces:
        ring = list(face.exterior.coords)[:-1]
        if len(ring) != 3:
            raise KirRefusal([Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=None, field_name="profile",
                message_ru=(f"триангулятор вернул грань на {len(ring)} вершин — "
                            f"это не треугольник, и молча принять её нельзя"),
                got=len(ring))])
        area2 = ((ring[1][0] - ring[0][0]) * (ring[2][1] - ring[0][1])
                 - (ring[2][0] - ring[0][0]) * (ring[1][1] - ring[0][1]))
        ccw = ring if area2 > 0 else [ring[0], ring[2], ring[1]]
        a0, b0, c0 = (place(0, p[0], p[1]) for p in ccw)
        a1, b1, c1 = (place(last, p[0], p[1]) for p in ccw)
        tris.append([a0, c0, b0])                # the start faces BACKWARD along the path
        tris.append([a1, b1, c1])                # the end faces FORWARD

    # ── the sides: the same expression as in `extrude`, with the tangent in
    # place of Z
    loops = [list(poly.exterior.coords)[:-1]]
    loops += [list(r.coords)[:-1] for r in poly.interiors]
    for loop in loops:
        for i in range(last):
            for j, p in enumerate(loop):
                q = loop[(j + 1) % len(loop)]
                pb, qb = place(i, p[0], p[1]), place(i, q[0], q[1])
                pt, qt = place(i + 1, p[0], p[1]), place(i + 1, q[0], q[1])
                tris.append([pb, qb, qt])
                tris.append([pb, qt, pt])

    volume = _mesh_volume(verts, tris)
    if volume <= 0.0:
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=None, field_name="path",
            message_ru=(
                f"объём построенного тела {volume:.3f} мм³ — не положителен. "
                f"Это НАШ дефект, а не ваш вход: поверхность вывернулась или "
                f"замкнулась сама на себя. Отказ здесь честнее, чем отдать "
                f"тело, которое Revit примет и построит наизнанку"),
            got=volume)])

    diags: list = []
    mesh = validate_mesh({"vertices_mm": verts, "triangles": tris},
                         None, "mesh", diags)
    if mesh is None:
        raise KirRefusal(diags)
    return mesh
