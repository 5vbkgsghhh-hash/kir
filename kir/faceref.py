"""THE REFERENCE THAT REVIT RESOLVES: a named FACE of an element.

WHAT KIND OF LAYER THIS IS AND WHY IT IS SEPARATE
--------------------------------------------------
The frozen KIR reference dialect answers exactly one question — "WHICH
ELEMENT" — and answers it with FOUR forms, each of which is resolved BEFORE
the C# reaches Revit:

    {"by": "name",         "value": ...}   -> `ground.py`, against a model snapshot
    {"by": "element_id",   "value": ...}   -> already resolved, this already is the id
    {"by": "ref",          "value": <op>}  -> by the compiler, into a C# variable
    {"by": "phase_result", "value": <op>,
                           "phase": N}     -> by the executor, between programs
                                             (`course.CROSS_PHASE_BY`, 09.08)

None of them can name a FACE: a face has no `ElementId`, it is not an
`Element`, and before execution it does not exist as an addressable thing.
The same structural dead end blocked `Electrical.Wire.Create` (branch
`feat/kir-mep`, `e4fe53b8`: «`Connector` is not an `Element`… the frozen KIR
reference dialect cannot name it AT ALL») and holds up the entire chapter on
conceptual masses: `FaceWall.Create` and `NewCurtainSystem2` require the face
of a real `FamilyInstance` mass, and a typed program has nothing to name that
face with.

THE FORM IS A WRAPPER, NOT A FIFTH `by`
----------------------------------------
    {"by": "face", "of": <element selector>, "predicate": {...}}

`of` carries the WHOLE selector of the existing dialect, not a bare op id.
This is this file's CENTRAL decision, and it is derived from `phase_result`,
not invented alongside it.

This is an argument from measurement, not taste. References are found by
GENERIC traversals over the whole structure: `design_check._ref_targets` and
`course._mark_cross_phase` descend into any nested dict and look for
`by == "ref"`. Had we written `{"of": "M1"}` as a bare string, both
traversals would have walked right past it, and a reference to an element's
face from a PAST phase would have stayed a `by=ref` on an op that no longer
exists by that point: exactly the refusal `_merge_bundle` phrases as «a
neighboring program is a separate transaction, and by the time it executes
the id no longer exists». With a nested selector, the same traversals find
the reference THEMSELVES, and phases with faces compose without a single
edit to `course/__init__.py`. Verified by a test
(`test_faceref.py::CoherenceWithFrozenDialectTests`), not by argument.

This is also where you can read WHAT KIND OF GRAMMAR this is: not a fifth
form in one list, but a SECOND STAGE. Stage 1 answers "which element" (the
four forms above), stage 2 answers "which part of that element" and ALWAYS
contains exactly one stage-1 selector. The frozen dialect stays frozen: every
consumer of it sees the same four forms, just one level deeper.

WHERE IT IS RESOLVED, AND WHAT CHANGES IF THIS MOVES
------------------------------------------------------
TODAY: by inline C# that this file emits. So the resolver's text enters the
program, and therefore the `program_digest` — the receipt signs the
resolver's behavior BY CONSTRUCTION.

IF IT MOVES INTO A SHIPPED DLL — the signature would break exactly the way
`author_digest` would break without an environment signature
(`sandbox.environment_signature`, branch `feat/kir-kernel`, `ad06eeb8`): one
digest would certify DIFFERENT behaviors after a library update, and the
receipt would have no field to distinguish a program edit from runtime
drift. THAT IS WHY THE ORDER IS FIXED BY THE LEAD: the receipt first signs
this DLL's version and digest, and only then does the code move there. This
DLL is NOT implemented here — the condition is named here.

THIS FILE'S LAW: A DESCRIPTION FILTERS, IT DOES NOT PICK
-----------------------------------------------------------
`Solid.Faces` has NO documented order (this is already recorded in
`authoring._dim_geom_helpers_cs`), so any "take the first match" is a
meaningless number and `.FirstOrDefault()` under a different name. A live
measurement on 02.08 on Snowdon: the C# arm silently took 1 door type OUT OF
62 and built it.

Here the predicate is a FILTER, and what decides is the CARDINALITY of the
set:

    exactly 1 candidate  -> bind
    0 candidates         -> a typed refusal with a named next move
    >= 2 candidates      -> a typed refusal, WITH THE COUNT of candidates

Cardinality does not depend on iteration order — so `Solid.Faces`'s
undocumented order stops affecting the result AT ALL. That is the whole
trick.

TOLERANCES: NOT A SINGLE ONE OF OUR OWN
------------------------------------------
Parallelism of normals is checked by Revit's OWN test —
`XYZ.CrossProduct(...).IsZeroLength()`, the same one already used by
`_dim_geom_helpers_cs` («Revit's OWN zero-length test so no threshold is
invented here»). Co-direction — by the sign of `DotProduct`. Degeneracy of a
given vector — by that same `IsZeroLength()`, AT RUNTIME. Not a single
number is assigned here.

A DIRECT CONSEQUENCE, NAMED OUT LOUD: the `normal` predicate is EXACT, not
"closest." A face rotated by one degree will not fit and will produce a "no
candidate" refusal. This is DELIBERATE: "closest by angle" requires an
ANGULAR TOLERANCE that nobody has measured, and an assigned tolerance is the
very same defect class as `create_door.sill_mm min_val=0`.

API SIGNATURES WERE TAKEN FROM REFERENCE ASSEMBLIES (measured 09.08, live
Roslyn :52412, one line per candidate, `data/revit_api_db.json` was not
consulted):

    HostObjectUtils.GetSideFaces(HostObject, ShellLayerType)   2021..2026  6/6
    HostObjectUtils.GetTopFaces(HostObject)                    2021..2026  6/6
    HostObjectUtils.GetBottomFaces(HostObject)                 2021..2026  6/6
    Element.GetGeometryObjectFromReference(Reference)          2021..2026  6/6
    GeometryInstance.GetSymbolGeometry() + .Transform          2021..2026  6/6
    PlanarFace.FaceNormal / .Reference                         2021..2026  6/6
    XYZ.IsZeroLength/CrossProduct/DotProduct/Normalize         2021..2026  6/6
    Reference.ConvertToStableRepresentation(Document)          2021..2026  6/6

So there is NO version branch in the emission: all six versions get the same
C#, and this is a MEASURED FACT, not a hope.
"""
from __future__ import annotations

import os
from kir import env  # noqa: E402  (a dependency-free submodule — creates no cycle)
from typing import Any

from kir.diag import (
    Diagnostic, GROUND_BAD_SELECTOR, TYPE_BAD_ENUM, TYPE_BAD_TYPE,
)
from kir.emit_utils import is_finite_number

#: The second kind of selector. Lives ALONGSIDE the four stage-1 forms, not
#: among them: see "THE FORM IS A WRAPPER, NOT A FIFTH `by`" in the module's
#: docstring.
BY_FACE = "face"

#: The operator flag's name — HERE ONLY FOR READING FROM OUTSIDE (tests,
#: documentation). In the `face_ref_enabled` gate itself it is written as a
#: LITERAL, and that is not duplication by oversight: the owner's inventory
#: tool searches for flags by regex over TEXT, and a call through the
#: constant will NOT BE SEEN by it — the flag would become invisible, that
#: is, sitting in the store by construction. That the two copies stay in
#: sync is held by a test, not by an agreement.
#:
#: 🔴 THE REGEX FORM HERE USED TO BE `os.getenv("NAME")`, AND THAT ARGUMENT
#: OUTLIVED ITS OWN CAUSE (02.09.2026). The owner's inventory tool
#: (`backend/tools/capability_manifest.py::environment_census`) walks the
#: `kukai/ir` and `kukai/live` roots; after the 27.08 split, NEITHER
#: directory exists:
#:
#:     ls -d /opt/kukai-rebuild1/backend/kukai/{ir,live} -> No such file
#:
#: That is, the instrument the call form was kept for has not read this file
#: since the split, while the test kept guarding the SHAPE. The name moved
#: to `KIR_*` (the old one is read by the gate), and the test asks the same
#: pair — in the new form.
FACE_REF_FLAG = "KIR_FACE_REF"

#: The sides that Revit itself NAMES. This is not geometry that we compute —
#: these are names from `HostObjectUtils`, so they have no tolerance and
#: cannot have one.
SIDES: tuple[str, ...] = ("exterior", "interior", "top", "bottom")

#: The predicate's keys. More than one is a CONJUNCTION (AND), and this is
#: the only named next move when the "several candidates" refusal happens.
PREDICATE_KEYS: tuple[str, ...] = ("side", "normal")


def face_ref_enabled() -> bool:
    """The operator flag: whether the selector's SECOND STAGE (a face) is
    allowed.

    OFF BY DEFAULT. While off, it is obligated to be indistinguishable from
    the form not existing at all: a stage-2 selector gets a typed refusal at
    parse time, and the emission of programs WITHOUT such selectors is
    obligated to be byte-identical
    (`test_faceref.py::FlagOffIsAbsentTests`).
    """
    return env.get("KIR_FACE_REF", "").strip().lower() in (
        "1", "true", "yes", "on")


def is_face_sel(value: Any) -> bool:
    """Whether a value looks like a face selector — STRUCTURALLY, before any
    validation.

    Needed separately from `validate_face_sel`, because the caller must tell
    "this is not a face" (let the ordinary branch sort it out) apart from
    "this is a face, but a malformed one" (a typed refusal ABOUT THE FACE).
    Merging these two answers would mean answering "the selector must be
    element_id|ref" to a typo in the predicate — a diagnosis that sends the
    repair to the wrong place.
    """
    return isinstance(value, dict) and value.get("by") == BY_FACE


def inner_selector(sel: dict) -> Any:
    """The STAGE 1 selector inside a face selector — the part that
    addresses the element."""
    return sel.get("of")


def validate_face_sel(sel: dict, *, oid: str, field: str, i: int | None,
                      inner_ok, diags: list) -> dict | None:
    """Validate the shape of a face selector. Return the NORMALIZED form or
    None.

    `inner_ok` — the caller's predicate for the STAGE 1 selector: this file
    does not know, and should not know, which forms are lawful for a
    particular parameter (`refs_w` takes element_id|ref, `sel` would also
    take name/default). Asking the caller about this is the only way not to
    set up a second source of truth about the frozen dialect here.

    REFUSALS ARE SEPARATE, NOT GLUED INTO ONE. A measurement on 02.08 (nine
    notes longer than the limit, all nine reported «content — непустая
    строка») calls for the same discipline here: a message naming the wrong
    refusal is more expensive than no message at all.
    """
    where = field if i is None else f"{field}[{i}]"
    allowed = {"by", "of", "predicate"}
    extra = set(sel) - allowed
    if extra:
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_id=oid, field_name=where,
            expected=sorted(allowed), got=sorted(extra),
            message_ru=(
                f"{where}: у селектора грани нет полей {sorted(extra)}. "
                f"Форма ровно одна: "
                f'{{"by": "face", "of": <селектор элемента>, '
                f'"predicate": {{...}}}}')))
        return None

    inner = sel.get("of")
    if not inner_ok(inner):
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_id=oid, field_name=f"{where}.of",
            expected='{"by": "element_id"|"ref", "value": ...}', got=inner,
            message_ru=(
                f"{where}.of: грань принадлежит ЭЛЕМЕНТУ, и элемент "
                f"называется обычным селектором — тем же, что и везде. "
                f"СЛЕДУЮЩИЙ ХОД: подставь сюда селектор, законный для этого "
                f"параметра")))
        return None

    pred = sel.get("predicate")
    if not isinstance(pred, dict):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{where}.predicate",
            expected="объект", got=pred,
            message_ru=(
                f"{where}.predicate: описание грани обязательно — селектор "
                f"грани БЕЗ описания адресует все грани сразу, то есть не "
                f"адресует ни одной")))
        return None

    unknown = set(pred) - set(PREDICATE_KEYS)
    if unknown:
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_id=oid, field_name=f"{where}.predicate",
            expected=list(PREDICATE_KEYS), got=sorted(unknown),
            message_ru=(
                f"{where}.predicate: неизвестные ключи {sorted(unknown)}. "
                f"Описание грани знает {list(PREDICATE_KEYS)}; несколько "
                f"ключей сразу — это И (конъюнкция)")))
        return None

    if not pred:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{where}.predicate",
            expected=f"хотя бы один из {list(PREDICATE_KEYS)}", got=pred,
            message_ru=(
                f"{where}.predicate пуст. Описание, которому отвечает КАЖДАЯ "
                f"грань, — не имя грани, а `.FirstOrDefault()` в другой "
                f"одежде. СЛЕДУЮЩИЙ ХОД: назови side или normal")))
        return None

    out: dict[str, Any] = {}
    if "side" in pred:
        side = pred["side"]
        if side not in SIDES:
            diags.append(Diagnostic(
                code=TYPE_BAD_ENUM, op_id=oid,
                field_name=f"{where}.predicate.side",
                expected=list(SIDES), got=side, candidates=list(SIDES),
                message_ru=(
                    f"{where}.predicate.side: сторону НАЗЫВАЕТ САМ Revit "
                    f"(`HostObjectUtils`), и список закрыт: {list(SIDES)}")))
            return None
        out["side"] = side
    if "normal" in pred:
        vec = pred["normal"]
        # A numeric check on SHAPE ONLY. A vector's degeneracy is resolved
        # AT RUNTIME by Revit's own `XYZ.IsZeroLength()`: assigning a
        # "minimum length" here would mean inventing a tolerance, and the
        # only real threshold belongs to Revit, askable only at execution.
        #
        # 🔴 A NUMBER'S FINITENESS IS NOT A TOLERANCE, AND THE ARGUMENT ABOVE
        # DOES NOT COVER IT (04.09.2026). The argument about LENGTH still
        # holds: there is still no lower length threshold here, and none is
        # being set up. But `isinstance(x, (int, float))` let `10**400`
        # through — a lawful JSON integer that does not even have a length
        # yet: one line below, `float(x)` raised an `OverflowError` OUTWARD,
        # past all diagnostics (measured — the control `[1,0,0]` was
        # accepted). The question "will the number even reach Revit as a
        # double" stands BEFORE the question "how long is the vector," and
        # it cannot be asked at execution: there will be no execution — the
        # compiler has already crashed. The form used already exists,
        # `emit_utils.is_finite_number` — the same one used by `plane._vec3`
        # and the tree's other numeric boundaries.
        if (not isinstance(vec, (list, tuple)) or len(vec) != 3
                or any(not is_finite_number(x) for x in vec)):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid,
                field_name=f"{where}.predicate.normal",
                expected="[x, y, z] — три конечных числа", got=vec,
                message_ru=(
                    f"{where}.predicate.normal — направление внешней нормали "
                    f"грани в координатах МОДЕЛИ, три КОНЕЧНЫХ числа. Длина не "
                    f"важна: вектор нормируется в Revit — но число, которое не "
                    f"представимо double, до Revit не доедет вовсе")))
            return None
        out["normal"] = [float(x) for x in vec]

    return {"by": BY_FACE, "of": inner, "predicate": out}


# ══════════════════════════════════════════════════════════════════════════
# EMISSION: RESOLVING A DESCRIPTION INTO A REFERENCE, INSIDE REVIT
# ══════════════════════════════════════════════════════════════════════════

#: How a side named by Revit turns into a `HostObjectUtils` call. A table,
#: not an `if`-ladder: the list of sides is closed and lives in `SIDES`, and
#: two places knowing it separately would diverge on the very first edit.
_SIDE_CALL: dict = {
    "exterior": "HostObjectUtils.GetSideFaces({ho}, ShellLayerType.Exterior)",
    "interior": "HostObjectUtils.GetSideFaces({ho}, ShellLayerType.Interior)",
    "top": "HostObjectUtils.GetTopFaces({ho})",
    "bottom": "HostObjectUtils.GetBottomFaces({ho})",
}


def walk_helpers_cs(s: str) -> str:
    """Local functions for a SINGLE op: geometry traversal and candidate
    selection.

    As local functions, not unrolled text: the traversal is RECURSIVE
    (nested families are a `GeometryInstance` inside a `GeometryInstance`),
    and it is needed once per EACH reference. They ship into `decl`, not
    `create`: `per_op` isolation wraps every create in its own scope, and a
    name declared inside it dies at the closing brace (the scope contract).

    A TRAP THAT COMPILES 6/6 AND REFUSES LIVE — not rediscovered here, but
    taken from branch `feat/kir-annotation` (`9c5c7492`), where it cost a
    third live refusal. The obvious `GetInstanceGeometry()` is documented by
    RevitAPI.xml as a COPY, whose references are «not suitable for creating
    new Revit elements referencing the original element (for example,
    dimensioning)» — exactly the kind of reference Revit throws on. Only
    `GetSymbolGeometry()` WITHOUT an argument works. Its coordinates are
    symbol-space, so the NORMAL is carried back into the model via
    `GeometryInstance.Transform` (composition — meaning nested families work
    too). The reference is taken from one accessor and the coordinates from
    another — that is the whole trick.

    THE TRAVERSAL DOES NOT STOP AT THE FIRST HIT, and this is what
    distinguishes it from the size traversal. That one SEARCHES for a fit
    face and is entitled to stop; this one COUNTS how many faces satisfy the
    description, because the decision is made by the cardinality of the set.
    An early exit would turn "there are two of them" into "took the first
    one" — exactly the silently-wrong behavior this form exists to forbid.
    """
    return f"""void __faceKeep_{s}(Element __fkEl, IList<Reference> __fkSrc, XYZ __fkWant,
    List<Reference> __fkOut)
{{
    if (__fkSrc == null) return;
    foreach (Reference __fkR in __fkSrc)
    {{
        if (__fkR == null) continue;
        if (__fkWant == null) {{ __fkOut.Add(__fkR); continue; }}
        PlanarFace __fkPf = null;
        try {{ __fkPf = __fkEl.GetGeometryObjectFromReference(__fkR) as PlanarFace; }}
        catch {{ }}
        if (__fkPf == null) continue;
        XYZ __fkN = __fkPf.FaceNormal;
        if (__fkN.IsZeroLength()) continue;
        __fkN = __fkN.Normalize();
        if (!__fkN.CrossProduct(__fkWant).IsZeroLength()) continue;
        if (__fkN.DotProduct(__fkWant) <= 0) continue;
        __fkOut.Add(__fkR);
    }}
}}
void __faceWalk_{s}(GeometryElement __fwGe, Transform __fwTf, XYZ __fwWant,
    List<Reference> __fwOut)
{{
    if (__fwGe == null) return;
    foreach (GeometryObject __fwGo in __fwGe)
    {{
        Solid __fwSol = __fwGo as Solid;
        if (__fwSol != null)
        {{
            foreach (Face __fwFc in __fwSol.Faces)
            {{
                PlanarFace __fwPf = __fwFc as PlanarFace;
                if (__fwPf == null || __fwPf.Reference == null) continue;
                XYZ __fwN = __fwTf.OfVector(__fwPf.FaceNormal);
                if (__fwN.IsZeroLength()) continue;
                __fwN = __fwN.Normalize();
                if (__fwWant != null && !__fwN.CrossProduct(__fwWant).IsZeroLength()) continue;
                if (__fwWant != null && __fwN.DotProduct(__fwWant) <= 0) continue;
                __fwOut.Add(__fwPf.Reference);
            }}
            continue;
        }}
        GeometryInstance __fwGi = __fwGo as GeometryInstance;
        if (__fwGi != null)
            __faceWalk_{s}(__fwGi.GetSymbolGeometry(), __fwTf.Multiply(__fwGi.Transform),
                __fwWant, __fwOut);
    }}
}}"""


def resolve_cs(sel: dict, *, s: str, i: int, elem_var: str, out_var: str,
               oid: str, label: str, isolation: str, view_var: str | None,
               refuse_stmt, cs_literal,
               next_move_zero: str | None = None,
               next_move_many: str | None = None,
               normal_field: str = "predicate.normal") -> str:
    """C# that binds `out_var` to the SINGLE face satisfying the
    description.

    `refuse_stmt`/`cs_literal` arrive as parameters, not by import: a
    refusal has ONE owner (`emit_utils.refuse_stmt`), and this file is
    obligated to ask for the form, not print it itself (otherwise `per_op`
    would silently gain the semantics of the whole program — a defect
    closed on 28.07 and guarded by KIR-E005).

    THREE OUTCOMES, AND NOT A SINGLE SILENT ONE: exactly one candidate — we
    bind; zero — a refusal; more than one — a refusal NAMING THE COUNT. The
    compiler does not choose for the author: a live paired measurement on
    02.08 on Snowdon showed the cost of choosing — the C# arm silently took
    1 door type out of 62 and built it.

    `next_move_zero` / `next_move_many` — the NEXT MOVE in the caller's own
    words. Set up by the mass wave (10.08) and NOT for taste: this file's
    own text refers to `predicate.side` and `predicate.normal`, that is, to
    the SELECTOR'S SECOND-STAGE dict. An operation that takes a face's
    direction as an ordinary parameter (`create_face_wall.face_normal`, the
    way `create_slab_edge` takes `side`) has no such fields at all — and a
    refusal sending the author to edit a field that does not exist is more
    expensive than no refusal at all. This is exactly the law this file has
    already applied to itself ("REFUSALS ARE SEPARATE, NOT GLUED INTO ONE"),
    just one stage higher up.

    `normal_field` — for the same reason and the same spot: the name of the
    field where the author wrote the vector. For a selector this is
    `predicate.normal`; for an operation with an ordinary parameter, it is
    that parameter's name, and the refusal is obligated to name THE THING
    the author edits.

    The defaults give WORD-FOR-WORD the previous text, so `create_dimension`'s
    emission is byte-identical — extending the helper has no right to move
    programs that already called it.
    """
    pred = sel["predicate"]
    human = describe_predicate_ru(pred)
    cand = f"__fc_{s}_{i}"
    want = f"__fw_{s}_{i}"
    lines = [f"List<Reference> {cand} = new List<Reference>();"]

    if "normal" in pred:
        x, y, z = pred["normal"]
        lines.append(f"XYZ {want} = new XYZ({x!r}, {y!r}, {z!r});")
        # Degeneracy is decided by Revit's own test, at runtime. Assigning
        # a threshold here would mean inventing a tolerance; only Revit
        # knows the real threshold.
        lines.append(
            f"if ({want}.IsZeroLength()) {{ "
            + refuse_stmt(oid, cs_literal(
                f"{label}: {normal_field} — вырожденный вектор (Revit "
                f"считает его нулевым). СЛЕДУЮЩИЙ ХОД: задай направление "
                f"нормали ненулевым вектором"), isolation) + " }")
        lines.append(f"{want} = {want}.Normalize();")
    else:
        lines.append(f"XYZ {want} = null;")

    if "side" in pred:
        ho = f"__fh_{s}_{i}"
        src = f"__fs_{s}_{i}"
        call = _SIDE_CALL[pred["side"]].format(ho=ho)
        lines.append(f"HostObject {ho} = {elem_var} as HostObject;")
        lines.append(
            f"if ({ho} == null) {{ "
            + refuse_stmt(oid, cs_literal(
                f"{label}: сторона «{pred['side']}» — имя, которое даёт САМ "
                f"Revit (HostObjectUtils), и оно есть только у HostObject "
                f"(стена, перекрытие, кровля, потолок). Этот элемент — ")
            + f" + __ClassName({elem_var}) + " + cs_literal(
                ". СЛЕДУЮЩИЙ ХОД: опиши грань нормалью "
                "(predicate.normal)"), isolation) + " }")
        lines.append(f"IList<Reference> {src} = null;")
        lines.append(f"try {{ {src} = {call}; }} catch {{ }}")
        lines.append(f"__faceKeep_{s}({elem_var}, {src}, {want}, {cand});")
    else:
        opt = f"__fo_{s}_{i}"
        ge = f"__fg_{s}_{i}"
        lines.append(f"Options {opt} = new Options();")
        lines.append(f"{opt}.ComputeReferences = true;")
        # Without this, the geometry of a base line (grids, levels,
        # reference planes) does not appear AT ALL — measured by the
        # annotations branch: every grid was refusing before 09.08 for
        # exactly this reason.
        lines.append(f"{opt}.IncludeNonVisibleObjects = true;")
        if view_var:
            lines.append(f"{opt}.View = {view_var};")
        lines.append(f"GeometryElement {ge} = null;")
        lines.append(f"try {{ {ge} = {elem_var}.get_Geometry({opt}); }} catch {{ }}")
        lines.append(
            f"__faceWalk_{s}({ge}, Transform.Identity, {want}, {cand});")

    lines.append(
        f"if ({cand}.Count == 0) {{ "
        + refuse_stmt(oid, cs_literal(
            f"{label}: у элемента нет грани, отвечающей описанию ({human}). "
            f"Описание ТОЧНОЕ: грань берётся, только если её нормаль строго "
            f"параллельна и сонаправлена заданной (проверка родным "
            f"XYZ.IsZeroLength на векторном произведении) — «почти "
            f"параллельна» не считается, потому что углового допуска никто "
            f"не мерил. "
            + (next_move_zero or
               "СЛЕДУЮЩИЙ ХОД: проверь направление нормали в координатах "
               "МОДЕЛИ, либо назови сторону (predicate.side)")),
            isolation) + " }")
    lines.append(
        f"if ({cand}.Count > 1) {{ "
        + refuse_stmt(
            oid,
            # «отвечает не одна грань, а N» rather than «отвечает N граней»:
            # Russian numerals agree with the noun's case, and a
            # template-glued form lies for 2, 3, and 4. A human reads the
            # refusal.
            cs_literal(f"{label}: описанию ({human}) отвечает не одна грань, а ")
            + f" + {cand}.Count.ToString() + "
            + cs_literal(
                ". Компилятор НЕ выбирает за автора: порядок граней "
                "в теле не документирован, поэтому «первая подходящая» — "
                "число без смысла. "
                + (next_move_many or
                   "СЛЕДУЮЩИЙ ХОД: сузь описание — добавь predicate.normal "
                   "рядом с predicate.side (или наоборот)")),
            isolation) + " }")
    lines.append(f"{out_var} = {cand}[0];")
    return "\n".join(lines)


def describe_predicate_ru(pred: dict) -> str:
    """A face's description in HUMAN words — for the refusal's text.

    The refusal is obligated to repeat the description verbatim: "face not
    found" without a description sends the author back to reread their own
    program, and that is exactly the cost a typed refusal exists to avoid.
    """
    parts = []
    if "side" in pred:
        parts.append(f"сторона «{pred['side']}»")
    if "normal" in pred:
        x, y, z = pred["normal"]
        parts.append(f"нормаль [{x:g}, {y:g}, {z:g}]")
    return " и ".join(parts)
