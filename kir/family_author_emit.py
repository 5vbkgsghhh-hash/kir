"""FAMILY AUTHORING — THE LANGUAGE'S SECOND DOOR, NOT ITS EIGHTIETH OP.

WHAT IS NEW HERE, AND WHY THIS IS NOT JUST ANOTHER EMITTER.

All 77 ops of the language write INTO THE OPEN PROJECT. This shows not by
design intent but by the LETTER of the emission: `doc` is a free variable,
supplied by the bridge wrapper (`Execute(Document doc, UIDocument uidoc)`),
and every emitter writes it verbatim (`solid_emit._shell_cs`:
`DirectShape.CreateElement(doc, __cat)`). A family requires a SECOND
document: create it from a template, build shapes inside it, check it with a
witness THERE, save it, close it, load it into the project. The
`emit_program` pipeline can do NONE of these five steps — it has exactly one
transaction on exactly one document.

🔴 WHY `doc` CANNOT SIMPLY BE REBOUND TO THE FAMILY'S DOCUMENT.
The temptation is strong and expensive: swap one variable, and suddenly all
77 ops "know how to do families." But `DirectShape.IsValidCategoryId(cat,
doc)` will pass inside a family too, `DirectShape.CreateElement` will build,
the volume witness will agree — and we would get a DirectShape INSIDE THE
FAMILY. The form is the same, the meaning is just as much
(`bim_semantics: none`), and the receipt will NOT NOTICE this, because it
reads the element, not the document. A silently wrong answer, exactly the
kind the compiler exists to forbid. So the goal is not swapping a variable,
but a TEMPLATE OF ITS OWN FOR THE WHOLE PROGRAM, with a different document
and its own dictionary of forms.

THE FORM IS CHOSEN, NOT INVENTED. A door for "an op owns its own
transactions" already exists in the language: `spec.SOLO_OPS` +
`authoring._SOLO_PROGRAMS`, set up for `create_stairs` (`StairsEditScope`
opens and closes transactions itself). A family is the same class, one
degree stronger: it owns not only transactions but a SECOND DOCUMENT. Moving
into an existing door is cheaper and more honest than cutting an identical
one next to it.

WHY ONE OP, NOT FIVE. Creating the document, the shape, the parameter, the
association, saving, and loading are not five independent operations: not
one of them has meaning without the rest, and no foreign op CAN be wedged in
between them — a family's document does not survive the program's boundary
(after `Close`, all of its elements are dead). Five ops would declare, as
points of a program, things that are not points, and the very first program
of "create document; place wall; add parameter" would be syntactically legal
and impossible to execute. The unit of intent here is the WHOLE FAMILY.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 FLEXIBILITY IS AN OBLIGATION, AND IT IS MEASURED, NOT JUST WRITTEN DOWN.

A live run of the director on 21.08.2026 (Revit 2026, `Проект1`) bought four
refusals, and the third is this module's central fact:

    the `Высота_KIR` parameter was changed from 800 to 1600
    the volume stayed at 192 000 000 = 600 x 400 x 800

The parameter exists, the formula reads back correctly, the body does NOT
LISTEN to it. This passes ABSOLUTELY SILENTLY: `FamilyManager.Set` returns
without an error, `Formula` reads back, the family saves and loads. With the
association (`AssociateElementParameterToFamilyParameter` on
`BuiltInParameter.EXTRUSION_END_PARAM`), the same measurement gives

    volume at 800 mm    192 000 000
    volume at 1600 mm   384 000 000
    ratio                   2.0000

Hence the module's law: the witness does NOT check that the parameter was
written — it DOUBLES the parameter, regenerates, and demands a volume ratio
of 2.0000, then sets the value back. The check runs INSIDE the family's
document, INSIDE its transaction, BEFORE saving: an unassociated family is
rolled back and does not exist for a single second. "There is a handle, but
the body does not listen" is unconstructible here, not merely unlikely.

WHY A REFUSAL, NOT A NAMED ABSENCE. The author is obligated to name
`flex_param` — a `required` field. That is, they REQUESTED a flexible
family. Handing back a rigid one under that name would mean answering a
question that was not asked. Named absence is reserved for the axes we did
not promise (the profile plan, material, subcategory) — those are printed in
the receipt under the `unverified_ru` field.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

THE THREE REMAINING REFUSALS OF THE LIVE RUN — CLOSED HERE BY NAME:

  1. `FamilyManager.Set` -> «There is no current type». A NEW family has NO
     types at all. `if (fm.CurrentType == null) fm.NewType(...)` stands as
     the FIRST move after opening the transaction.
  2. `doc.Regenerate()` outside a transaction -> «Modification of the
     document is forbidden». All three regenerations of the measurement
     stand inside `__ft`.
  4. An unclosed family document hangs around in Revit's memory until the
     session ends. `Close(false)` stands in `finally`, meaning it runs on a
     refusal, on an exception, and on a `return` out of a `catch`.

API MEMBERS ARE TAKEN FROM THE `data/api_surface/` INDEX, NOT FROM MEMORY —
6/6 across 2021-2026:

    Application.NewFamilyDocument · FamilyTemplatePath              6/6
    Document.FamilyCreate · FamilyManager · IsFamilyDocument
             · LoadFamily · SaveAs · Close · PathName               6/6
    FamilyItemFactory.NewExtrusion                                  6/6
    FamilyManager.NewType · AddParameter · Set · CurrentType
             · AssociateElementParameterToFamilyParameter
             · CanElementParameterBeAssociated                      6/6
    Extrusion.EndOffset · StartOffset · BuiltInParameter
             .EXTRUSION_END_PARAM                                   6/6
    Creation.Document.NewFamilyInstance · FamilySymbol.Activate
             · Family.GetFamilySymbolIds · SaveAsOptions
             .OverwriteExistingFile · GeometryInstance
             .GetInstanceGeometry                                   6/6

🔴 TWO TRAPS FOUND BY THIS SAME INDEX AND BYPASSED HERE:

    FamilyManager.GetParameter        - + + + + +   ABSENT ON 2021
    FamilyManager.Parameter (indexer -> get_Parameter)    6/6

  The form `fm.GetParameter(name)`, used by the chat door
  (`llm/tool_handlers/family_tools.py:1729` calls `get_Parameter`), does not
  compile on 2021 in its modern spelling. Here the parameter's name is never
  read back at all: `AddParameter` RETURNS a `FamilyParameter`, and that
  object is held in a variable — there is not a single lookup by name.

    AddParameter(string, BuiltInParameterGroup, ParameterType, bool)  2021-2022
    AddParameter(string, ForgeTypeId,           ForgeTypeId,   bool)  2022-2026

  The two windows overlap only on 2022, meaning ONE spelling is NEVER enough
  for the whole range. This knowledge is not rediscovered — it was measured
  by the chat door on 10.07.2026 (`family_tools.py:341-366`, compiled
  against the real assemblies) and is only applied here to `ver`, which KIR
  already has on entry to emission. The constants have THEIR OWN windows,
  and those are narrower: `GroupTypeId.*` — 2022-2026,
  `BuiltInParameterGroup.PG_*` — 2021-2024, `SpecTypeId.Length` — all six.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from kir import contour as C
from kir.contracts import ElementIdentityProof
from kir.diag import Diagnostic, KirRefusal, TYPE_GEOM_RELATION
from kir.registry_base import FAMILY_TEMPLATES
from kir.emit_utils import (cs_identifier_fragment, cs_line_comment_fragment,
                                 cs_string_literal, failure_channel_reset_cs,
                                 failure_preprocessor_cs,
                                 failure_warnings_into_results_cs)

_cs = cs_string_literal


def _n(value: float) -> str:
    """A number into a C# literal WITHOUT losing significant digits — the
    same function and the same argument as in `solid_emit._n`: the witness
    compares the expected volume, and rounding "for prettiness" would become
    an error nobody derived.
    """
    return repr(float(value))


#: TEMPLATE KIND -> CANDIDATE FILE NAMES, IN TRY ORDER.
#:
#: 🔴 THE PATH IS NOT WRITTEN AS A LITERAL, NOT BY A SINGLE CHARACTER. The
#: directory is taken from Revit (`doc.Application.FamilyTemplatePath`) at
#: execution time, because it depends on the version, locale, and
#: installation settings — exactly the argument by which
#: `ops_families.load_family` requires an EXPLICIT path and refuses to guess
#: the standard library. Here there is nothing to guess: Revit has an
#: instrument that answers this question, and we ask it.
#:
#: TEMPLATE KINDS MOVED INTO THE REGISTRY ON 01.09.2026 — ONE CARRIER, JUST
#: LOWER DOWN. The list is read by TWO consumers: emission (candidate file
#: names) and the operation's declaration
#: (`ops_families.author_family.template.choices`). While the home was here,
#: the REGISTRY was pulling in the EMITTER on load, and through that edge
#: the live-plan drafter reached all the way to the compiler: a
#: `capability_graph` traversal gave 10 solvers out of 15 and 127 reachable
#: modules; after removing it — 0 and 48.
#: No copy was set up: `FAMILY_TEMPLATES` here is the same name from the
#: registry.

#: The volume-ratio tolerance is NOT ASSIGNED HERE AS A NUMBER. It is
#: derived from Revit's own `VertexTolerance` and our emission's quantum by
#: the same law as `solid_emit._derived_tolerances_cs`: δ = tol + quantum,
#: volume tolerance = δ · (the body's surface area). This law deliberately
#: has no second home.


def _safe(oid: str) -> str:
    return cs_identifier_fragment(oid)


def _param_add_cs(ver: str, name_cs: str) -> str:
    """`FamilyManager.AddParameter` in the spelling that exists on `ver`.

    This is VERSION_CONDITIONAL, not a preference: both spellings name
    members that do not exist on the other side of 2022
    (CS0103/CS0117/CS0122).
    """
    if str(ver) <= "2021":
        return (f"__fm_.AddParameter({name_cs}, "
                f"BuiltInParameterGroup.PG_GEOMETRY, "
                f"ParameterType.Length, false)")
    return (f"__fm_.AddParameter({name_cs}, "
            f"GroupTypeId.Geometry, SpecTypeId.Length, false)")


def axis_rect_or_reason(region: dict) -> tuple[tuple[float, float, float, float] | None,
                                                str | None]:
    """(bbox, None) if the profile is an AXIS-ALIGNED RECTANGLE; otherwise
    (None, reason).

    🔴 WHY SUCH NARROWNESS, AND WHY WIDENING IT WOULD BE A LIE. Parametric
    flexibility rests on `NewAlignment`: a profile edge is pinned to a
    reference plane, the plane drives a dimension, the dimension is tagged
    with a parameter. Alignment only holds for edges that LIE ON the plane.
    A round column has not a single edge lying on a vertical plane — the
    family would assemble, look parametric, and skew sideways at the very
    first parameter change. This is exactly the class of silent lie this
    whole op is written against, so here there is a REFUSAL naming the
    profile's kind, rather than "best-effort support."
    """
    if region.get("holes"):
        return None, (f"профиль несёт {len(region['holes'])} проём(ов): "
                      f"выравнивание держит только рёбра внешнего контура, "
                      f"проёмы за плоскостями не пойдут и семейство поехало "
                      f"бы вкось")
    outer = region["outer"]
    if len(outer) != 4:
        return None, (f"внешний контур из {len(outer)} рёбер, а плановая "
                      f"гибкость выведена для ЧЕТЫРЁХ: две вертикали "
                      f"прибиваются к плоскостям, две горизонтали свободны")
    if not C.edges_are_straight(outer):
        kinds = "дуги" if C.region_has_arc(region) else "сплайны"
        return None, (f"внешний контур несёт {kinds}: к опорной плоскости "
                      f"прибивается ПРЯМОЕ ребро, кривое на ней не лежит")
    xs = sorted({round(pt[0], 6) for e in outer for pt in (e[0], e[1])})
    ys = sorted({round(pt[1], 6) for e in outer for pt in (e[0], e[1])})
    if len(xs) != 2 or len(ys) != 2:
        return None, (f"контур не осевой: по X различных координат "
                      f"{len(xs)}, по Y — {len(ys)}, у осевого "
                      f"прямоугольника ровно по две. Повёрнутый "
                      f"прямоугольник сюда не годится: опорная плоскость "
                      f"строится вдоль Y, и повёрнутое ребро на ней не лежит")
    return (xs[0], ys[0], xs[1], ys[1]), None


def _plan_flex_cs(*, s: str, ver: str, name: str, bbox, height: float,
                  vol_w: float, vol_2w: float,
                  surf_w: float, surf_2w: float) -> str:
    """C# for plan flexibility: two reference planes, alignments, dimension, label.

    🔴 WHY THE PLAN FLEXES DIFFERENTLY FROM THE HEIGHT. Height has a
    ready-made form field (`BuiltInParameter.EXTRUSION_END_PARAM`), and
    binding a parameter to it is one call. The PLAN has NO such field AT
    ALL: extrusion width is not a property of the form but a consequence of
    the sketch. So the chain is longer and every link is mandatory:

        reference plane        a geometric object that can move
        NewAlignment            pins the sketch edge to the plane
        NewDimension            turns the distance between planes into an OBJECT
        Dimension.FamilyLabel   hands that object to the parameter

    Skip `NewAlignment` and the dimension will move the planes while the
    body stays put: exactly the handle that lies to the author, for the
    sake of forbidding which this whole op was written. So the number of
    alignments IS CHECKED (exactly two), not taken on faith, and acceptance
    is still bulky.

    THE MEASUREMENT THAT BOUGHT THIS CHAIN (live, Revit 2026, 21.08.2026):
    192 000 000 -> 384 000 000 on doubling the width, ratio 2.0000.
    """
    x0, y0, x1, y1 = bbox
    add = _param_add_cs(ver, _cs(name))
    # The planes are built ALONG Y and extend past the profile:
    # `NewReferencePlane` takes a segment, not an infinite line, and a plane
    # that is too short would not catch the edge during alignment.
    pad = max(1000.0, (y1 - y0))
    return f"""
        // ── ПЛАНОВАЯ ГИБКОСТЬ ──────────────────────────────────────────────
        View __pfView_{s} = null;
        foreach (View __pfCand_{s} in new FilteredElementCollector(__fam_{s})
            .OfClass(typeof(ViewPlan)))
            if (!__pfCand_{s}.IsTemplate) {{ __pfView_{s} = __pfCand_{s}; break; }}
        if (__pfView_{s} == null)
            throw new __KirFamilyRefusal({_cs(
                'в шаблоне семейства нет ПЛАНА, а опорная плоскость, '
                'выравнивание и размер строятся только в плоском виде. '
                'Плановая гибкость этим шаблоном недостижима')});

        ReferencePlane __pfPlnA_{s} = __fam_{s}.FamilyCreate.NewReferencePlane(
            new XYZ(U({_n(x0)}), U({_n(y0 - pad)}), 0.0),
            new XYZ(U({_n(x0)}), U({_n(y1 + pad)}), 0.0),
            new XYZ(0.0, 0.0, 1.0), __pfView_{s});
        ReferencePlane __pfPlnB_{s} = __fam_{s}.FamilyCreate.NewReferencePlane(
            new XYZ(U({_n(x1)}), U({_n(y0 - pad)}), 0.0),
            new XYZ(U({_n(x1)}), U({_n(y1 + pad)}), 0.0),
            new XYZ(0.0, 0.0, 1.0), __pfView_{s});
        if (__pfPlnA_{s} == null || __pfPlnB_{s} == null)
            throw new __KirFamilyRefusal({_cs('NewReferencePlane вернул null')});
        try {{
            __pfPlnA_{s}.Name = {_cs('KIR_' + name + '_начало')};
            __pfPlnB_{s}.Name = {_cs('KIR_' + name + '_конец')};
        }} catch (Exception) {{ /* имя плоскости — удобство, не закон */ }}
        __fam_{s}.Regenerate();

        // ВЫРАВНИВАНИЕ. Ребро ищется ПО КООРДИНАТЕ, а не по порядку в
        // CurveArray: порядок — соглашение Ревита, координата — факт.
        int __pfAligned_{s} = 0;
        foreach (CurveArray __pfArr_{s} in __ext_{s}.Sketch.Profile)
            foreach (Curve __pfCurve_{s} in __pfArr_{s})
            {{
                Line __pfLine_{s} = __pfCurve_{s} as Line;
                if (__pfLine_{s} == null || __pfCurve_{s}.Reference == null) continue;
                XYZ __pfQ0_{s} = __pfLine_{s}.GetEndPoint(0), __pfQ1_{s} = __pfLine_{s}.GetEndPoint(1);
                if (Math.Abs(__pfQ0_{s}.X - __pfQ1_{s}.X) > 1e-9) continue;
                ReferencePlane __pfTarget_{s} =
                    Math.Abs(MM(__pfQ0_{s}.X) - {_n(x0)}) < 0.01 ? __pfPlnA_{s}
                  : (Math.Abs(MM(__pfQ0_{s}.X) - {_n(x1)}) < 0.01 ? __pfPlnB_{s} : null);
                if (__pfTarget_{s} == null) continue;
                __fam_{s}.FamilyCreate.NewAlignment(
                    __pfView_{s}, __pfTarget_{s}.GetReference(), __pfCurve_{s}.Reference);
                __pfAligned_{s}++;
            }}
        if (__pfAligned_{s} != 2)
            throw new __KirFamilyRefusal(
                {_cs('к опорным плоскостям прибито ')} + __pfAligned_{s}.ToString()
                + {_cs(' рёбер вместо двух. Без обоих выравниваний параметр '
                       'двигал бы плоскости, а тело стояло бы на месте — '
                       'ручка, врущая автору')});
        __fam_{s}.Regenerate();

        FamilyParameter __pfParam_{s} = {add};
        if (__pfParam_{s} == null)
            throw new __KirFamilyRefusal({_cs('AddParameter вернул null для параметра «' + name + '»')});
        ReferenceArray __pfRefs_{s} = new ReferenceArray();
        __pfRefs_{s}.Append(__pfPlnA_{s}.GetReference());
        __pfRefs_{s}.Append(__pfPlnB_{s}.GetReference());
        Dimension __pfDim_{s} = __fam_{s}.FamilyCreate.NewDimension(
            __pfView_{s},
            Line.CreateBound(new XYZ(U({_n(x0)}), U({_n(y1 + pad * 0.5)}), 0.0),
                             new XYZ(U({_n(x1)}), U({_n(y1 + pad * 0.5)}), 0.0)),
            __pfRefs_{s});
        if (__pfDim_{s} == null)
            throw new __KirFamilyRefusal({_cs('NewDimension вернул null — размер между опорными плоскостями не построился')});
        __pfDim_{s}.FamilyLabel = __pfParam_{s};
        __fam_{s}.Regenerate();

        // ── ПРИЁМКА ПЛАНА: ТА ЖЕ, ЧТО У ВЫСОТЫ, И ТОЖЕ ОБЪЁМНАЯ ────────────
        double __pfVol1_{s} = __KirVol(__ext_{s});
        if (Math.Abs(__pfVol1_{s} - {_n(vol_w)}) > {_n(surf_w)} * __dt_{s})
            throw new __KirFamilyRefusal(
                {_cs('после привязки плана объём разошёлся с эталоном: ждали ' + _n(vol_w) + ' мм³, Ревит дал ')}
                + __pfVol1_{s}.ToString());
        __fm_.Set(__pfParam_{s}, U({_n((x1 - x0) * 2.0)}));
        __fam_{s}.Regenerate();
        double __pfVol2_{s} = __KirVol(__ext_{s});
        __pratio_{s} = __pfVol1_{s} == 0.0 ? 0.0 : __pfVol2_{s} / __pfVol1_{s};
        if (Math.Abs(__pfVol2_{s} - {_n(vol_2w)}) > {_n(surf_w)} * __dt_{s} + {_n(surf_2w)} * __dt_{s})
            throw new __KirFamilyRefusal(
                {_cs('ПЛАН НЕ СЛУШАЕТ ПАРАМЕТР «' + name + '». Удвоение ширины с '
                     + _n(x1 - x0) + ' на ' + _n((x1 - x0) * 2.0) + ' мм дало отношение объёмов ')}
                + __pratio_{s}.ToString() + {_cs(' вместо 2.0000 (было ')}
                + __pfVol1_{s}.ToString() + {_cs(' мм³, стало ')} + __pfVol2_{s}.ToString()
                + {_cs(' мм³). Плоскости, выравнивания и размер созданы, но тело за '
                       'ними не пошло')});
        __fm_.Set(__pfParam_{s}, U({_n(x1 - x0)}));
        __fam_{s}.Regenerate();
        double __pfVol3_{s} = __KirVol(__ext_{s});
        if (Math.Abs(__pfVol3_{s} - __pfVol1_{s}) > {_n(surf_w)} * __dt_{s})
            throw new __KirFamilyRefusal(
                {_cs('возврат параметра «' + name + '» не вернул объём: было ')}
                + __pfVol1_{s}.ToString() + {_cs(' мм³, стало ')} + __pfVol3_{s}.ToString()
                + {_cs(' мм³ — семейство уехало бы в проект не той ширины')});
"""


def _profile_cs(region: dict, s: str) -> str:
    """Profile as `CurveArrArray` — the shape `NewExtrusion` requires.

    The rings are built by `contour.emit_loop_cs` WITHOUT CHANGES, the same
    call used by `solid_emit._loops_cs`: the package's arc arithmetic lives
    in ONE place, and a second home for it would diverge from the first at
    the very first edit to the arc's sagitta. The `CurveLoop -> CurveArray`
    conversion is mechanical and carries no arithmetic of its own.
    """
    names = [f"__ol_{s}"] + [f"__hl_{s}_{i}" for i in range(len(region["holes"]))]
    parts = [C.emit_loop_cs(region["outer"], f"__ol_{s}")]
    for hi, hole in enumerate(region["holes"]):
        parts.append(C.emit_loop_cs(hole, f"__hl_{s}_{hi}"))
    parts.append(f"CurveArrArray __prof_{s} = new CurveArrArray();")
    for idx, nm in enumerate(names):
        parts.append(
            f"CurveArray __ca_{s}_{idx} = new CurveArray();\n"
            f"foreach (Curve __cv_{s}_{idx} in {nm}) "
            f"__ca_{s}_{idx}.Append(__cv_{s}_{idx});\n"
            f"__prof_{s}.Append(__ca_{s}_{idx});")
    return "\n".join(parts)


#: THE VOLUME READER IS ONE FOR BOTH DOCUMENTS, AND THIS IS A REQUIREMENT,
#: NOT A CONVENIENCE. On the left side of the comparison stands the volume
#: of the form IN THE FAMILY, on the right — the volume of the INSTANCE IN
#: THE PROJECT. Compute them with different arithmetic and the discrepancy
#: stops meaning anything. There is exactly one difference between the
#: documents: for the instance the geometry arrives wrapped in
#: `GeometryInstance`, so the traversal unwraps it (`GetInstanceGeometry`,
#: 6/6), while for the family's form the solids lie flat.
_VOLUME_READER_CS = """\
Func<Element, double> __KirVol = (Element __ve) =>
{
    double __vv = 0.0;
    if (__ve == null) return 0.0;
    Options __vo = new Options();
    __vo.ComputeReferences = false;
    __vo.DetailLevel = ViewDetailLevel.Fine;
    GeometryElement __vge = __ve.get_Geometry(__vo);
    if (__vge == null) return 0.0;
    foreach (GeometryObject __vg in __vge)
    {
        Solid __vs = __vg as Solid;
        if (__vs != null) { __vv += __vs.Volume; continue; }
        GeometryInstance __vi = __vg as GeometryInstance;
        if (__vi == null) continue;
        GeometryElement __vie = __vi.GetInstanceGeometry();
        if (__vie == null) continue;
        foreach (GeometryObject __vg2 in __vie)
        {
            Solid __vs2 = __vg2 as Solid;
            if (__vs2 != null) __vv += __vs2.Volume;
        }
    }
    return __vv * MM(MM(MM(1.0)));
};
"""

#: A REFUSAL INSIDE THE FAMILY DOCUMENT IS A TYPE, NOT "SOME EXCEPTION OR
#: OTHER". The same argument as for `authoring.__KirOpRefusal`: a Revit API
#: breakdown and OUR DECISION to refuse arrive in one `catch`, and as long
#: as they are indistinguishable, any accidental error gets recorded as a
#: deliberate refusal — meaning the report lies exactly where it is the
#: sole source of knowledge.
_FAMILY_REFUSAL_CLASS_CS = """\
private class __KirFamilyRefusal : Exception
{
    public readonly string Msg;
    public __KirFamilyRefusal(string __msg) : base(__msg) { Msg = __msg; }
}
"""


def emit_author_family_program(
        op: dict, ver: str, intent: str = "", *, stamp: str = "",
        stamp_scope: str = "", lineage: str = "",
        expected_document: Mapping[str, str] | None = None,
        expected_identities: Sequence[ElementIdentityProof] | None = None,
) -> str:
    """The whole family-authoring program. Solo: its own documents, its own transactions.

    THE STEP ORDER IS DERIVED FROM A REVIT PROHIBITION, NOT FROM TASTE: the
    family document's transaction CLOSES before the project's transaction
    opens, `SaveAs` sits between them (it is document-level and impossible
    inside a transaction), `Close(false)` follows right after it. At no
    point in the program are two transactions open at once.
    """
    from kir import authoring as _authoring

    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    height = float(op["height_mm"])
    fam_name = str(op["family_name"])
    type_name = str(op["type_name"])
    flex = str(op["flex_param"])
    plan_flex = op.get("flex_plan_param")
    plan_flex = str(plan_flex) if plan_flex else None
    template = str(op["template"])

    # 🔴 THE REFUSAL IS STATIC, AND THAT IS THE CHEAPEST OPTION FOR THE
    # AUTHOR. The profile's kind can be checked WITHOUT GOING INTO REVIT;
    # sending a round column into a live run just to have it refuse there
    # would cost the author a minute and occupy someone else's window for
    # an answer that was already known in advance.
    plan_bbox = None
    if plan_flex is not None:
        plan_bbox, plan_why = axis_rect_or_reason(region)
        if plan_why is not None:
            raise KirRefusal([Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=oid,
                field_name="flex_plan_param",
                got=plan_flex, expected="осевой прямоугольник без проёмов",
                message_ru=(
                    f"flex_plan_param: плановая гибкость не выводится для "
                    f"этого профиля — {plan_why}. Убери flex_plan_param "
                    f"(семейство останется гибким по ВЫСОТЕ) либо приведи "
                    f"профиль к осевому прямоугольнику без проёмов"))])
        if plan_flex == flex:
            raise KirRefusal([Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=oid,
                field_name="flex_plan_param",
                got=plan_flex, expected="имя, отличное от flex_param",
                message_ru=(
                    f"flex_plan_param и flex_param названы одинаково "
                    f"(«{flex}»). Один параметр не может гнуть и высоту, и "
                    f"план: Ревит принял бы второе связывание и молча "
                    f"потерял первое"))])
    save_dir = op.get("save_dir")
    place_at = op.get("place_at")

    # ── REFERENCE VALUES ARE COMPUTED HERE, IN CLOSED FORM ──────────────────
    # A prism over a flat region: V = A·h. Area A takes Green's integral
    # over the boundary with the exact circular-segment formula
    # (`contour.region_measures`), and openings are subtracted exactly. The
    # same derivation as in `create_solid_extrusion`, and THE SAME CALL —
    # there is no second area arithmetic in the package.
    m = C.region_measures(region)
    area = m["area_mm2"]
    perim = m["perimeter_mm"]
    vol_h = area * height
    vol_2h = area * height * 2.0
    surf_h = 2.0 * area + perim * height
    # THE PLAN'S REFERENCE VALUES ARE COMPUTED IN CLOSED FORM, just like the
    # height reference values: for an axis-aligned rectangle (and no other
    # kind is admitted here), doubling the width doubles the area EXACTLY,
    # with no numerics involved.
    if plan_bbox is not None:
        _pw = plan_bbox[2] - plan_bbox[0]
        _pd = plan_bbox[3] - plan_bbox[1]
        plan_vol_w = _pw * _pd * height
        plan_vol_2w = 2.0 * _pw * _pd * height
        plan_surf_w = 2.0 * (_pw * _pd) + 2.0 * (_pw + _pd) * height
        plan_surf_2w = (2.0 * (2.0 * _pw * _pd)
                        + 2.0 * (2.0 * _pw + _pd) * height)
    surf_2h = 2.0 * area + perim * height * 2.0
    min_feature_h = m["min_area_mm2"] * height

    cands = FAMILY_TEMPLATES[template]
    cand_cs = ", ".join(_cs(c) for c in cands)
    cand_text = " ; ".join(cands)

    txn_name = ("KIR: " + (intent or "авторство семейства"))[:80]
    stamp = stamp or ""

    # THE A5 GUARDS APPEAR TWICE, AS WITH THE STAIRS, AND FOR THE SAME
    # REASON. The first stands BEFORE any work (a cheap refusal, nothing
    # created yet), the second is inside the PROJECT's transaction, because
    # between the two checks the program has time to create the family
    # document and write the file, and the active document can change
    # during that interval. The second one has its own rollback: it also
    # deletes the .rfa via `__kept_`, which remains false.
    doc_guard = _authoring._document_binding_guard(
        expected_document, rollback="")
    pre_doc_guard = (doc_guard + "\n") if doc_guard else ""
    pre_identity_guard_raw = _authoring._element_identity_guard(
        expected_identities, ver, rollback="")
    pre_identity_guard = (
        (pre_identity_guard_raw + "\n") if pre_identity_guard_raw else "")
    txn_doc_guard_raw = _authoring._document_binding_guard(
        expected_document, rollback="__t.RollBack(); ")
    txn_doc_guard = (
        _indent(txn_doc_guard_raw, "        ") + "\n"
        if txn_doc_guard_raw else "")
    # THE SECOND GUARD HAS ITS OWN PREFIX — without it, CS0136 on all six
    # (measured on 21.08 both here and in `create_stairs`, where the same
    # form had stood unfixed since 09.08; the stairs' companions do carry
    # the prefix).
    txn_identity_guard_raw = _authoring._element_identity_guard(
        expected_identities, ver, rollback="__t.RollBack(); ",
        symbol_prefix="__kirFamilyTxnBinding")
    txn_identity_guard = (
        _indent(txn_identity_guard_raw, "        ") + "\n"
        if txn_identity_guard_raw else "")

    # ── 1. TEMPLATE: FIRST STEP, AND THE REFUSAL NAMES THE PATH ─────────────
    #
    # 🔴 THE ORDER IS NOT COSMETIC. The template is an ENVIRONMENT
    # DEPENDENCY, meaning the one cause of refusal the author cannot see in
    # their own program. Asked last, it would undo work already done; asked
    # first, it costs one `File.Exists` and names what to fix. The same
    # argument by which the version refusal in `compile_program` comes
    # BEFORE grounding.
    template_cs = f"""\
// 🔴 НУЛЕВОЙ ХОД: А ПРОЕКТ ЛИ ПЕРЕД НАМИ.
//
// `doc` — активный документ Ревита, и он МОЖЕТ БЫТЬ СЕМЕЙСТВОМ: пользователь
// открыл редактор семейств и оставил его активным. Тогда всё дальнейшее
// молча меняет смысл — `FilteredElementCollector(doc).OfClass(typeof(Family))`
// ищет ВЛОЖЕННЫЕ семейства, `LoadFamily` грузит вложенное, а
// `doc.Create.NewFamilyInstance` ставит вложенный экземпляр. Программа
// «сработала бы», построив не то, о чём просили, — тот самый тихий неверный
// ответ. Зеркальная проверка уже стоит у чат-двери
// (`family_tools.py`: `if (!doc.IsFamilyDocument) ...`), и здесь она
// обязана быть обратной по знаку.
if (doc.IsFamilyDocument)
    return __Refuse({_cs(oid)}, {_cs(
        'активный документ Ревита — СЕМЕЙСТВО, а не проект. author_family '
        'создаёт своё семейство и грузит его В ПРОЕКТ; здесь это дало бы '
        'вложенное семейство, то есть не то, о чём просили. Переключитесь на '
        'окно проекта и повторите')});
string __tplDir_{s} = null;
try {{ __tplDir_{s} = doc.Application.FamilyTemplatePath; }} catch {{ }}
if (string.IsNullOrEmpty(__tplDir_{s}))
    return __Refuse({_cs(oid)}, {_cs(
        'Ревит не сообщил каталог шаблонов семейств: '
        'Application.FamilyTemplatePath пуст. В этой установке путь шаблонов '
        'не настроен — задайте его в «Файл > Параметры > Расположение файлов '
        '> Файлы шаблонов семейств», иначе создать семейство нечем')});
if (!System.IO.Directory.Exists(__tplDir_{s}))
    return __Refuse({_cs(oid)}, {_cs(
        'каталог шаблонов семейств, названный самим Ревитом, не существует: ')}
        + __tplDir_{s});
string[] __cand_{s} = new string[] {{ {cand_cs} }};
string __tpl_{s} = null;
foreach (string __cn_{s} in __cand_{s})
{{
    string __cp_{s} = System.IO.Path.Combine(__tplDir_{s}, __cn_{s});
    if (System.IO.File.Exists(__cp_{s})) {{ __tpl_{s} = __cp_{s}; break; }}
}}
if (__tpl_{s} == null)
{{
    // ОТКАЗ НАЗЫВАЕТ ПУТЬ, ВСЕ ПРОБОВАННЫЕ ИМЕНА И ТО, ЧТО В КАТАЛОГЕ ЕСТЬ.
    // «Шаблон не найден» оставило бы автора ровно там, где он стоял;
    // список наличных .rft — это следующий ход, а имя локали видно сразу.
    string __have_{s} = "";
    try
    {{
        string[] __all_{s} = System.IO.Directory.GetFiles(
            __tplDir_{s}, "*.rft", System.IO.SearchOption.AllDirectories);
        var __nm_{s} = new List<string>();
        for (int __i_{s} = 0; __i_{s} < __all_{s}.Length && __i_{s} < 8; __i_{s}++)
            __nm_{s}.Add(System.IO.Path.GetFileName(__all_{s}[__i_{s}]));
        __have_{s} = " | .rft в каталоге: " + __all_{s}.Length
            + (__nm_{s}.Count > 0 ? " (" + String.Join(" ; ", __nm_{s}) + ")" : "");
    }}
    catch {{ __have_{s} = " | содержимое каталога прочитать не удалось"; }}
    return __Refuse({_cs(oid)}, {_cs(
        'шаблон семейства рода «' + template + '» не найден. Каталог: ')}
        + __tplDir_{s}
        + {_cs('; искали имена: ' + cand_text)}
        + __have_{s});
}}"""

    # ── 2. FAMILY NAME IN THE PROJECT: A TAKEN NAME IS AN EDIT, NOT A CREATE ─
    #
    # `LoadFamily` over an ALREADY LOADED family redefines its DEFINITION —
    # that is, it silently changes the geometry of every existing instance.
    # This is a model mutation under the name of creation, and its cost
    # rises with the number of instances; so the refusal names THEIR COUNT.
    collide_cs = f"""\
{{
    int __inst_{s}_n = 0;
    Family __old_{s} = null;
    var __fams_{s} = new FilteredElementCollector(doc).OfClass(typeof(Family));
    foreach (Element __fe_{s} in __fams_{s})
        if (__fe_{s}.Name == {_cs(fam_name)}) {{ __old_{s} = __fe_{s} as Family; break; }}
    if (__old_{s} != null)
    {{
        try
        {{
            var __oc_{s} = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilyInstance)).WhereElementIsNotElementType();
            foreach (Element __oe_{s} in __oc_{s})
            {{
                var __ofi_{s} = __oe_{s} as FamilyInstance;
                if (__ofi_{s} == null || __ofi_{s}.Symbol == null) continue;
                if (__ofi_{s}.Symbol.Family != null
                    && __ofi_{s}.Symbol.Family.Id.ToString() == __old_{s}.Id.ToString())
                    __inst_{s}_n++;
            }}
        }}
        catch {{ __inst_{s}_n = -1; }}
        return __Refuse({_cs(oid)}, {_cs(
            'в проекте уже есть семейство «' + fam_name + '»: загрузка '
            'переопределила бы его ОПРЕДЕЛЕНИЕ, то есть молча сменила бы '
            'геометрию у уже стоящих экземпляров. Это правка модели, а не '
            'создание. Экземпляров затронуло бы: ')}
            + (__inst_{s}_n < 0 ? "не удалось сосчитать" : __inst_{s}_n.ToString())
            + {_cs('. Дайте другое family_name либо удалите семейство вручную')});
    }}
}}"""

    # ── 3. WHERE THE .rfa GOES ───────────────────────────────────────────────
    #
    # THE PATH IS NEITHER GUESSED NOR MADE UP FROM A TEMP DIRECTORY. A
    # family that ends up in %TEMP% is lost by the user along with the
    # session, and the receipt would name a path that will not exist
    # tomorrow. Order: the author's explicit `save_dir` -> the PROJECT'S
    # OWN directory (`doc.PathName`, the environment's answer, not ours) ->
    # a REFUSAL naming both outcomes.
    dir_expr = _cs(str(save_dir)) if save_dir else "null"
    path_cs = f"""\
string __dir_{s} = {dir_expr};
if (string.IsNullOrEmpty(__dir_{s}))
{{
    string __pp_{s} = doc.PathName;
    if (!string.IsNullOrEmpty(__pp_{s}))
        __dir_{s} = System.IO.Path.GetDirectoryName(__pp_{s});
}}
if (string.IsNullOrEmpty(__dir_{s}))
    return __Refuse({_cs(oid)}, {_cs(
        'семейству некуда лечь: save_dir не задан, а проект не сохранён '
        '(Document.PathName пуст). Сохраните проект или задайте save_dir — '
        'во временный каталог KIR семейство не кладёт, потому что путь в '
        'квитанции обязан пережить сессию')});
if (!System.IO.Directory.Exists(__dir_{s}))
    return __Refuse({_cs(oid)}, {_cs('каталог для .rfa не существует: ')} + __dir_{s});
string __rfa_{s} = System.IO.Path.Combine(__dir_{s}, {_cs(fam_name + '.rfa')});
if (System.IO.File.Exists(__rfa_{s}))
    return __Refuse({_cs(oid)}, {_cs(
        'файл семейства уже существует, и перезаписывать чужой файл KIR не '
        'станет (SaveAsOptions.OverwriteExistingFile = false): ')} + __rfa_{s});"""

    # ── 4-6. FAMILY DOCUMENT: FORM, PARAMETER, BINDING, MEASUREMENT ─────────
    add_param_cs = _param_add_cs(ver, _cs(flex))
    axes_cs = _cs(flex) if plan_flex is None else f"{_cs(flex)}, {_cs(plan_flex)}"
    plan_receipt = "" if plan_bbox is None else f"""\
    __rb["flex_plan_param"] = {_cs(plan_flex)};
    __rb["flex_plan_bound_to"] = "ReferencePlane + NewAlignment + Dimension.FamilyLabel";
    __rb["plan_volume_ratio"] = __pratio_{s};
    __rb["plan_flex_proof_ru"] = {_cs(
        'ширина ' + _n(plan_bbox[2] - plan_bbox[0]) + ' -> '
        + _n((plan_bbox[2] - plan_bbox[0]) * 2.0) + ' мм внутри документа '
        'семейства дала объём ' + _n(plan_vol_w) + ' -> ' + _n(plan_vol_2w)
        + ' мм³; тело прибито к двум опорным плоскостям, расстояние между '
        'ними помечено параметром. Значение возвращено и объём сверен второй '
        'раз — иначе семейство уехало бы в проект не той ширины')};"""
    plan_unverified_cs = _cs(
        'план профиля ЖЁСТКИЙ: параметрична только высота. Ширина, длина и '
        'проёмы вшиты в эскиз и параметром не управляются — семейство '
        'растягивается вверх и не растягивается в плане'
    ) if plan_flex is None else _cs(
        'ГЛУБИНА профиля жёсткая: параметричны высота и ШИРИНА (ось X). '
        'Вторая сторона плана и проёмы вшиты в эскиз — семейство тянется '
        'вверх и вширь, но не вглубь')
    plan_block = "" if plan_bbox is None else _plan_flex_cs(
        s=s, ver=ver, name=plan_flex, bbox=plan_bbox, height=height,
        vol_w=plan_vol_w, vol_2w=plan_vol_2w,
        surf_w=plan_surf_w, surf_2w=plan_surf_2w)
    family_cs = f"""\
Document __fam_{s} = null;
try {{ __fam_{s} = doc.Application.NewFamilyDocument(__tpl_{s}); }}
catch (Exception __nfx_{s})
{{
    return __Refuse({_cs(oid)}, {_cs('NewFamilyDocument отказал на шаблоне ')}
        + __tpl_{s} + ": " + __nfx_{s}.Message);
}}
if (__fam_{s} == null)
    return __Refuse({_cs(oid)}, {_cs('NewFamilyDocument вернул null на шаблоне ')} + __tpl_{s});
try
{{
    // ШАБЛОН МОГ ОКАЗАТЬСЯ НЕ ТЕМ: имя файла — это соглашение, а
    // IsFamilyDocument — факт. Спрашиваем факт.
    if (!__fam_{s}.IsFamilyDocument)
        throw new __KirFamilyRefusal(
            {_cs('документ, созданный из шаблона, документом семейства НЕ является: ')} + __tpl_{s});
    using (Transaction __ft_{s} = new Transaction(__fam_{s}, {_cs(txn_name)}))
    {{
        if (__ft_{s}.Start() != TransactionStatus.Started)
            throw new __KirFamilyRefusal({_cs('транзакция документа семейства не стартовала')});
{failure_channel_reset_cs("__KirFamDocFailures", "        ")}\
        var __ffho_{s} = __ft_{s}.GetFailureHandlingOptions();
        __ffho_{s}.SetFailuresPreprocessor(new __KirFamDocFailures());
        __ffho_{s}.SetForcedModalHandling(false);
        __ffho_{s}.SetClearAfterRollback(true);
        __ft_{s}.SetFailureHandlingOptions(__ffho_{s});

        FamilyManager __fm_ = __fam_{s}.FamilyManager;
        if (__fm_ == null)
            throw new __KirFamilyRefusal({_cs('у документа семейства нет FamilyManager')});
        // 🔴 ОТКАЗ №1 ЖИВОГО ПРОГОНА 21.08: у НОВОГО семейства типов НЕТ, и
        // FamilyManager.Set бросает «There is no current type». Тип заводится
        // ПЕРВЫМ ходом, до любого Set.
        if (__fm_.CurrentType == null) __fm_.NewType({_cs(type_name)});
        if (__fm_.CurrentType == null)
            throw new __KirFamilyRefusal({_cs('NewType не создал текущий тип семейства')});

        Plane __pl_{s} = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero);
        SketchPlane __sp_{s} = SketchPlane.Create(__fam_{s}, __pl_{s});
{_indent(_profile_cs(region, s), "        ")}
        // 🔴 ЛОВУШКА, КУПЛЕННАЯ ПРОДОМ 22.05.2026, И ЗДЕСЬ ОНА НАЗЫВАЕТСЯ, А
        // НЕ ОБХОДИТСЯ. `FamilyCreate.NewExtrusion` бросает
        // `Autodesk.Revit.Exceptions.InvalidOperationException` («The attempted
        // operation is not permitted in this type of family») когда активный
        // вид документа семейства — ТРЁХМЕРНЫЙ: Ревит требует плоского вида
        // для эскизной геометрии. Наш документ создан `NewFamilyDocument` в
        // фоне и активного 3D-вида иметь не должен, но «не должен» — это не
        // замер, поэтому исход ловится и печатается вместе с ВИДОМ и
        // КАТЕГОРИЕЙ, то есть ровно тем, что решает следующий ход.
        //
        // 🔴 ОТКАЗ, А НЕ ОТСТУПЛЕНИЕ В DirectShape. Чат-дверь в этом месте
        // спасается `GeometryCreationUtilities.CreateExtrusionGeometry` и
        // честно пишет «Geometry is static (no parametric flex)». Для неё это
        // верно: там просили форму. Здесь просили ГИБКОЕ СЕМЕЙСТВО, и выдать
        // под этим именем неподвижный DirectShape значило бы ответить не на
        // заданный вопрос — то есть сделать ровно то, ради запрета чего
        // `author_family` и существует.
        Extrusion __ext_{s} = null;
        try
        {{
            __ext_{s} = __fam_{s}.FamilyCreate.NewExtrusion(
                true, __prof_{s}, __sp_{s}, U({_n(height)}));
        }}
        catch (Autodesk.Revit.Exceptions.InvalidOperationException __nex_{s})
        {{
            string __vk_{s} = "(нет)";
            string __fc_{s} = "(неизвестна)";
            try {{ var __av_{s} = __fam_{s}.ActiveView;
                  if (__av_{s} != null) __vk_{s} = __av_{s}.ViewType.ToString(); }} catch {{ }}
            try {{ var __of_{s} = __fam_{s}.OwnerFamily;
                  if (__of_{s} != null && __of_{s}.FamilyCategory != null)
                      __fc_{s} = __of_{s}.FamilyCategory.Name; }} catch {{ }}
            throw new __KirFamilyRefusal(
                {_cs('Ревит отверг FamilyCreate.NewExtrusion в этом документе семейства: ')}
                + __nex_{s}.Message
                + {_cs(' | активный вид семейства: ')} + __vk_{s}
                + {_cs(' | категория семейства (из шаблона): ')} + __fc_{s}
                + {_cs('. Замер прода 22.05.2026: этот отказ приходит, когда активный '
                       'вид ТРЁХМЕРНЫЙ — эскизная геометрия требует плоского вида. '
                       'Отступления в DirectShape здесь НЕТ намеренно: он не '
                       'параметричен, а просили гибкое семейство')});
        }}
        if (__ext_{s} == null)
            throw new __KirFamilyRefusal({_cs('FamilyCreate.NewExtrusion вернул null')});

        FamilyParameter __h_{s} = {add_param_cs};
        if (__h_{s} == null)
            throw new __KirFamilyRefusal({_cs('AddParameter вернул null для параметра «' + flex + '»')});
        // ЗНАЧЕНИЕ СТАВИТСЯ ДО СВЯЗЫВАНИЯ, И ЭТО НЕ ПОРЯДОК ПО ВКУСУ. Свежий
        // параметр длины стоит НУЛЁМ; связав его первым, мы перенесли бы ноль
        // в конец выдавливания и получили бы пустое тело внутри собственной
        // транзакции — отказ по причине, которую сами и создали.
        __fm_.Set(__h_{s}, U({_n(height)}));

        // 🔴 СВЯЗЫВАНИЕ. БЕЗ НЕГО ПАРАМЕТР — БЕСПОЛЕЗНАЯ РУЧКА, и это
        // ЗАМЕРЕНО (21.08.2026): 800 -> 1600 при несвязанном параметре
        // оставило объём 192 000 000 неизменным, без единого сообщения.
        Parameter __end_{s} = __ext_{s}.get_Parameter(BuiltInParameter.EXTRUSION_END_PARAM);
        if (__end_{s} == null)
            throw new __KirFamilyRefusal({_cs('у выдавливания нет параметра EXTRUSION_END_PARAM — связать высоту не с чем')});
        if (!__fm_.CanElementParameterBeAssociated(__end_{s}))
            throw new __KirFamilyRefusal({_cs('Ревит не допускает связывания конца выдавливания с параметром семейства в этом шаблоне')});
        __fm_.AssociateElementParameterToFamilyParameter(__end_{s}, __h_{s});
        // 🔴 ОТКАЗ №2 ЖИВОГО ПРОГОНА: Regenerate ВНЕ транзакции ->
        // «Modification of the document is forbidden». Все три регенерации
        // замера стоят внутри этой транзакции.
        __fam_{s}.Regenerate();

        // ── ДОПУСКИ ВЫВЕДЕНЫ, А НЕ НАЗНАЧЕНЫ ───────────────────────────────
        // δ = собственный VertexTolerance Ревита + квант нашей эмиссии;
        // допуск объёма = δ · (площадь поверхности тела). Тот же закон, что у
        // solid_emit._derived_tolerances_cs, и та же защита от ВАКУУМНОСТИ:
        // допуск, не меньший самой мелкой объявленной части профиля, означает
        // проверку, которая не могла бы провалиться, — а такой свидетель хуже
        // отсутствующего.
        __dt_{s} = MM(__fam_{s}.Application.VertexTolerance) + {_n(C.EMIT_COORD_QUANTUM_MM)};
        __tv1_{s} = {_n(surf_h)} * __dt_{s};
        __tv2_{s} = {_n(surf_2h)} * __dt_{s};
        if (__tv1_{s} >= {_n(min_feature_h)})
            throw new __KirFamilyRefusal({_cs(
                'допуск объёмного свидетеля не меньше самой мелкой объявленной '
                'части профиля — проверка гибкости не смогла бы провалиться; '
                'тело слишком тонкое или проём слишком мелкий для честной сверки')});

        // ── 🔴 ЗАМЕР ГИБКОСТИ. ЭТО И ЕСТЬ ПРИЁМКА, А НЕ ОТЧЁТ О НЕЙ ────────
        // Свидетель НЕ спрашивает «записался ли параметр» — он УДВАИВАЕТ его
        // и требует, чтобы тело послушалось. Несвязанное семейство здесь даёт
        // отношение 1.0 и откатывается, не прожив ни секунды.
        __v1_{s} = __KirVol(__ext_{s});
        if (__v1_{s} <= 0.0)
            throw new __KirFamilyRefusal({_cs('тело семейства не построилось: объём при заказанной высоте равен нулю')});
        if (Math.Abs(__v1_{s} - {_n(vol_h)}) > __tv1_{s})
            throw new __KirFamilyRefusal(
                {_cs('объём формы в семействе разошёлся с эталоном: ждали ' + _n(vol_h) + ' мм³, Ревит дал ')}
                + __v1_{s}.ToString() + {_cs(' мм³ при допуске ')} + __tv1_{s}.ToString());

        __fm_.Set(__h_{s}, U({_n(height * 2.0)}));
        __fam_{s}.Regenerate();
        __v2_{s} = __KirVol(__ext_{s});
        __ratio_{s} = __v1_{s} == 0.0 ? 0.0 : __v2_{s} / __v1_{s};
        if (Math.Abs(__v2_{s} - 2.0 * __v1_{s}) > __tv1_{s} + __tv2_{s})
            throw new __KirFamilyRefusal(
                {_cs('ТЕЛО НЕ СЛУШАЕТ ПАРАМЕТР «' + flex + '». Удвоение с '
                     + _n(height) + ' на ' + _n(height * 2.0) + ' мм дало отношение объёмов ')}
                + __ratio_{s}.ToString() + {_cs(' вместо 2.0000 (было ')}
                + __v1_{s}.ToString() + {_cs(' мм³, стало ')} + __v2_{s}.ToString()
                + {_cs(' мм³). Параметр создан и связан, но конец выдавливания им не '
                       'управляется. Семейство без гибкости KIR не выпускает: '
                       'параметр, которого тело не слышит, — это ручка, врущая автору')});

        // ЗНАЧЕНИЕ ВОЗВРАЩАЕТСЯ, И ВОЗВРАТ ТОЖЕ ПРОВЕРЯЕТСЯ. Семейство,
        // уехавшее в проект вдвое выше заказанного, было бы худшим исходом
        // этой проверки, чем её отсутствие.
        __fm_.Set(__h_{s}, U({_n(height)}));
        __fam_{s}.Regenerate();
        __v3_{s} = __KirVol(__ext_{s});
        if (Math.Abs(__v3_{s} - __v1_{s}) > __tv1_{s})
            throw new __KirFamilyRefusal(
                {_cs('возврат параметра «' + flex + '» к заказанному значению не вернул объём: было ')}
                + __v1_{s}.ToString() + {_cs(' мм³, стало ')} + __v3_{s}.ToString()
                + {_cs(' мм³ — семейство уехало бы в проект не той высоты')});
{plan_block}
        var __fcs_{s} = __ft_{s}.Commit();
        if (__fcs_{s} != TransactionStatus.Committed)
            throw new __KirFamilyRefusal(
                {_cs('транзакция документа семейства не закоммичена: ')} + __fcs_{s}.ToString()
                + (__KirFamDocFailures.Seen.Count > 0
                    ? " | Revit: " + String.Join(" ; ", __KirFamDocFailures.Seen) : ""));
    }}
    // SaveAs ДОКУМЕНТНОГО УРОВНЯ: внутри транзакции он невозможен, поэтому
    // стоит здесь, за закрытой транзакцией и до закрытия документа.
    SaveAsOptions __sao_{s} = new SaveAsOptions();
    __sao_{s}.OverwriteExistingFile = false;
    try {{ __fam_{s}.SaveAs(__rfa_{s}, __sao_{s}); }}
    catch (Exception __sx_{s})
    {{
        throw new __KirFamilyRefusal({_cs('SaveAs отказал на пути ')} + __rfa_{s}
            + ": " + __sx_{s}.Message);
    }}
    if (!System.IO.File.Exists(__rfa_{s}))
        throw new __KirFamilyRefusal({_cs('после SaveAs файла семейства на диске нет: ')} + __rfa_{s});
}}
catch (__KirFamilyRefusal __fr_{s})
{{
    return __Refuse({_cs(oid)}, __fr_{s}.Msg);
}}
finally
{{
    // 🔴 ОТКАЗ №4 ЖИВОГО ПРОГОНА: НЕЗАКРЫТЫЙ ДОКУМЕНТ СЕМЕЙСТВА ВИСИТ В
    // ПАМЯТИ РЕВИТА ДО КОНЦА СЕССИИ. finally отрабатывает и на успехе, и на
    // нашем отказе, и на чужом исключении, и на return из catch — то есть на
    // всех четырёх выходах, а не на том одном, о котором помнил автор.
    try {{ if (__fam_{s} != null && __fam_{s}.IsValidObject) __fam_{s}.Close(false); }}
    catch {{ }}
}}"""

    # ── 7. PROJECT: LOAD, ACTIVATE, INSTANCE ───────────────────────────────
    if place_at is None:
        place_cs = ""
        place_post = ""
    else:
        px, py = float(place_at[0]), float(place_at[1])
        pz = float(place_at[2]) if len(place_at) > 2 else 0.0
        place_cs = f"""\
        __inst_{s} = doc.Create.NewFamilyInstance(
            P({_n(px)}, {_n(py)}, {_n(pz)}), __sym_{s},
            Autodesk.Revit.DB.Structure.StructuralType.NonStructural);
        if (__inst_{s} == null)
        {{ __t.RollBack(); return __Refuse({_cs(oid)}, {_cs('NewFamilyInstance вернул null')}); }}
        doc.Regenerate();
        {_authoring._stamp_block(f"__inst_{s}", f"{stamp}:{oid}")}
"""
        # THE WITNESS IN THE PROJECT COMPARES AGAINST THE MEASUREMENT IN THE
        # FAMILY, NOT AGAINST OUR ARITHMETIC A SECOND TIME. The reference
        # value has already been checked against A·h inside the family; the
        # question here is DIFFERENT — did the "save -> close -> load ->
        # place" cycle carry the same geometry through. Comparing against
        # A·h would answer the first question twice and the second one not
        # at all.
        place_post = f"""\
        __iv_{s} = __KirVol(__inst_{s});
        if (Math.Abs(__iv_{s} - __v1_{s}) > __tv1_{s} + __tv2_{s})
            __post.Add({_cs(oid + ': объём поставленного экземпляра разошёлся с объёмом формы в семействе (geometry)')});
        if (__inst_{s}.Symbol == null
            || __inst_{s}.Symbol.Id.ToString() != __sym_{s}.Id.ToString())
            __post.Add({_cs(oid + ': экземпляр стоит не на том типоразмере (topology)')});
"""

    # 🔴 A FAILED PROGRAM LEAVES NO FILE BEHIND — THE ZERO-TRACE PROPERTY IS
    # CARRIED THROUGH TO DISK.
    #
    # For every other op, `__t.RollBack()` holds the "zero trace": the
    # rollback erases the created elements, and after a refusal the model
    # is byte-for-byte the same as before. Here the rollback is NOT
    # COMPLETE by construction — `SaveAs` has already written the .rfa, and
    # Revit has no transaction over the file system. A refusal at load time
    # would leave on disk a family that is absent from the model, and the
    # next run would get ITS OWN file back as "already exists" — that is, a
    # refusal explaining itself by its own previous refusal.
    #
    # The deletion is safe precisely because a refusal on an existing file
    # sits above it: if we got here, the .rfa was created by THIS program
    # and by no one else. `finally` covers every exit — a return from
    # inside, an exception, the ordinary path through — not just the single
    # one the author had in mind.
    project_cs = f"""\
bool __kept_{s} = false;
try
{{
using (Transaction __t = new Transaction(doc, {_cs(txn_name)}))
{{
    try
    {{
        var __startStatus = __t.Start();
        if (__startStatus != TransactionStatus.Started)
            return __Refuse({_cs(oid)}, "transaction start status: " + __startStatus.ToString());
{failure_channel_reset_cs("__KirFamFailures", "        ")}\
        var __fho = __t.GetFailureHandlingOptions();
        __fho.SetFailuresPreprocessor(new __KirFamFailures());
        __fho.SetForcedModalHandling(false);
        __fho.SetClearAfterRollback(true);
        __t.SetFailureHandlingOptions(__fho);
{txn_doc_guard}{txn_identity_guard}\
        bool __ok_{s} = false;
        try {{ __ok_{s} = doc.LoadFamily(__rfa_{s}, out __ff_{s}); }}
        catch (Exception __lx_{s})
        {{
            __t.RollBack();
            return __Refuse({_cs(oid)}, {_cs('LoadFamily отказал на файле ')} + __rfa_{s}
                + ": " + __lx_{s}.Message);
        }}
        if (!__ok_{s} || __ff_{s} == null)
        {{
            __t.RollBack();
            return __Refuse({_cs(oid)}, {_cs('LoadFamily вернул false — Ревит не принял только что написанный нами файл: ')} + __rfa_{s});
        }}
        ICollection<ElementId> __sids_{s} = __ff_{s}.GetFamilySymbolIds();
        if (__sids_{s} == null || __sids_{s}.Count == 0)
        {{
            __t.RollBack();
            return __Refuse({_cs(oid)}, {_cs('у загруженного семейства нет ни одного типоразмера')});
        }}
        // ТИП ИЩЕТСЯ ПО ИМЕНИ, КОТОРОЕ ДАЛ АВТОР. Взять «первый попавшийся»
        // значило бы вернуть в квитанции чужое имя как своё: шаблон приносит
        // собственные типы, и их порядок не документирован ни на одной версии.
        foreach (ElementId __sid_{s} in __sids_{s})
        {{
            var __cand2_{s} = doc.GetElement(__sid_{s}) as FamilySymbol;
            if (__cand2_{s} != null && __cand2_{s}.Name == {_cs(type_name)})
            {{ __sym_{s} = __cand2_{s}; break; }}
        }}
        if (__sym_{s} == null)
        {{
            __t.RollBack();
            return __Refuse({_cs(oid)}, {_cs('в загруженном семействе нет типоразмера «' + type_name + '» — тип, заведённый NewType, не доехал через SaveAs/LoadFamily')});
        }}
        if (!__sym_{s}.IsActive) {{ __sym_{s}.Activate(); doc.Regenerate(); }}
        if (!__sym_{s}.IsActive)
        {{
            __t.RollBack();
            return __Refuse({_cs(oid)}, {_cs('типоразмер не активировался — «главная ловушка» загрузки семейств')});
        }}
{place_cs}\
        // ── СВИДЕТЕЛЬ В ПРОЕКТЕ ─────────────────────────────────────────────
        if (__ff_{s}.Name != {_cs(fam_name)})
            __post.Add({_cs(oid + ': имя загруженного семейства не равно заказанному (semantic)')});
        if (__sym_{s}.Name != {_cs(type_name)})
            __post.Add({_cs(oid + ': имя типоразмера не равно заказанному (semantic)')});
{place_post}\
        if (__post.Count > 0)
        {{
            __t.RollBack();
            var __er = new Dictionary<string, object>();
            __er["error"] = "postconditions_violated";
            __er["violations"] = __post;
            return __er;
        }}
        var __commitStatus = __t.Commit();
        if (__commitStatus != TransactionStatus.Committed)
        {{
            try {{ if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack(); }} catch {{ }}
            var __refused = __Refuse({_cs(oid)}, "transaction commit status: " + __commitStatus.ToString()
                + (__KirFamFailures.Seen.Count > 0 ? " | Revit: " + String.Join(" ; ", __KirFamFailures.Seen) : ""));
            if (__KirFamFailures.Warned.Count > 0)
                __refused["revit_warnings"] = __KirFamFailures.Warned;
            return __refused;
        }}
        // ФАЙЛ ОСТАЁТСЯ ТОЛЬКО ЗДЕСЬ — после коммита, когда семейство В МОДЕЛИ
        // и Ревит помнит его путь. Любой другой выход стирает .rfa ниже.
        __kept_{s} = true;
    }}
    catch
    {{
        if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack();
        throw;
    }}
}}
}}
finally
{{
    if (!__kept_{s})
    {{
        try {{ if (System.IO.File.Exists(__rfa_{s})) System.IO.File.Delete(__rfa_{s}); }}
        catch {{ }}
    }}
}}"""

    # ── 8. RECEIPT ────────────────────────────────────────────────────────
    #
    # 🔴 THE OPPOSITE OF THE DirectShape RECEIPT, AND THIS IS THE WHOLE
    # POINT. There it reads `bim_semantics: none / human_editable: false /
    # schedulable_as_building_element: false`. Here — a real building
    # element. But none of these fields is set "because we're proud of
    # it": each is named together with WHAT PROVES IT, and whatever is not
    # confirmed is printed as `null` plus a reason — the same law as for
    # the volume of a twisted form ("zero where the unknown belongs is our
    # written form of a defect").
    placed = place_at is not None
    receipt_cs = f"""\
// witness {cs_line_comment_fragment(oid)}
{{
    var __rb = new Dictionary<string, object>();
    __rb["family_name"] = {_cs(fam_name)};
    __rb["type_name"] = {_cs(type_name)};
    __rb["template_kind"] = {_cs(template)};
    __rb["template_path"] = __tpl_{s};
    __rb["rfa_path"] = __rfa_{s};
    __rb["family_id"] = __ff_{s} == null ? null : __ff_{s}.Id.ToString();
    __rb["symbol_id"] = __sym_{s} == null ? null : __sym_{s}.Id.ToString();
    // `id` — ВСЕГДА ТИПОРАЗМЕР, и это решение, а не удобство. Оп выпускает
    // ОПРЕДЕЛЕНИЕ; экземпляр необязателен (`place_at`). Пусти сюда то одно,
    // то другое — и поле `id` квитанции стало бы двумя разными величинами под
    // одним именем, а именно на нём стоит `ResultSpec.identity_field`.
    __rb["id"] = __sym_{s} == null ? null : __sym_{s}.Id.ToString();
    __rb["instance_id"] = __inst_{s} == null ? null : __inst_{s}.Id.ToString();

    // ── ГИБКОСТЬ: ЧИСЛА, А НЕ ФЛАЖОК ───────────────────────────────────────
    __rb["flex_param"] = {_cs(flex)};
    __rb["flex_bound_to"] = "BuiltInParameter.EXTRUSION_END_PARAM";
{plan_receipt}
    __rb["volume_mm3_expected"] = {_n(vol_h)};
    __rb["volume_mm3_at_h"] = __v1_{s};
    __rb["volume_mm3_at_2h"] = __v2_{s};
    __rb["volume_mm3_restored"] = __v3_{s};
    __rb["volume_ratio"] = __ratio_{s};
    __rb["volume_tolerance_mm3"] = __tv1_{s};
    __rb["vertex_tolerance_mm"] = MM(doc.Application.VertexTolerance);
    __rb["flex_proof_ru"] = {_cs(
        'параметр удвоен внутри документа семейства, объём перемерян, значение '
        'возвращено; отношение обязано быть 2.0000, иначе программа откатывается')};

    // ── СМЫСЛ, И ЧЕМ ОН ДОКАЗАН ────────────────────────────────────────────
    __rb["bim_semantics"] = {_cs('generic_model_family' if placed else 'generic_model_family_type')};
    __rb["has_type"] = true;
    __rb["human_editable"] = true;
    __rb["human_editable_basis_ru"] = {_cs(
        'семейство лежит файлом .rfa и загружено типоразмером — правится в '
        'редакторе семейств Ревита, а высота меняется параметром')};
    __rb["schedulable_as_building_element"] = {'true' if placed else 'null'};
    {'' if placed else f'__rb["schedulable_unverified_ru"] = ' + _cs(
        'экземпляр не ставился (place_at не задан): в спецификацию попадает '
        'ЭКЗЕМПЛЯР, а не определение, поэтому подтвердить нечем') + ';'}
    __rb["instance_volume_mm3"] = {f'__iv_{s}' if placed else 'null'};

    // ── ЧТО НЕ ПРОВЕРЕНО. НАЗВАНО, А НЕ ЗАМОЛЧАНО ──────────────────────────
    __rb["flex_axes"] = new string[] {{ {axes_cs} }};
    __rb["unverified_ru"] = new string[] {{
        {plan_unverified_cs},
        {_cs('категория семейства пришла ИЗ ШАБЛОНА и нами не задавалась: '
             'какой род элемента получился, решает .rft, а не программа')},
        {_cs('материал, подкатегория и видимость по уровням детализации не '
             'задавались вовсе')},
        {_cs('привязки к уровню у экземпляра не запрашивалось и не проверялось: '
             'place_at — точка в мировых координатах, а какой уровень Ревит '
             'припишет экземпляру, здесь не читается')},
        {_cs('🔴 СУДЬЯ ПОСТРОЕННОГО ЭТУ ОПЕРАЦИЮ НЕ СУДИТ, и вот почему. '
             'Идентичность опа (`ResultSpec.identity_field`) — это `id`, а '
             '`id` здесь ТИПОРАЗМЕР: определение, которое в модели не стоит. '
             'Судья перечитывает то, что стоит, и честно отвечает '
             '`elements_read=0 · NOT_EVALUATED`. Экземпляр (`instance_id`) '
             'создан и в модели ЕСТЬ, но в `element_map` не попадает: '
             '`created_ledger.extract_created` собирает id по полям '
             'идентичности реестра, а второго поля у операции нет. Сделать '
             '`id` то типоразмером, то экземпляром нельзя — это одно имя для '
             'двух величин. Лечится тем, что `ResultSpec` научится называть '
             'НЕСКОЛЬКО созданных, либо тем, что постановка уедет в свой '
             '`place_family`. Замерено 21.08.2026 живым прогоном')}
    }};
    // Предупреждения Ревита, сказанные ПРО ДОКУМЕНТ СЕМЕЙСТВА. Отдельным
    // полем, а не в общей куче: они относятся к другому документу, и слитые
    // с проектными читались бы как претензия к модели.
    if (__KirFamDocFailures.Warned.Count > 0)
        __rb["family_doc_warnings"] = __KirFamDocFailures.Warned;
    __results[{_cs(oid)}] = __rb;
}}"""

    # ── DECLARATIONS ─────────────────────────────────────────────────────────
    decls = f"""\
Family __ff_{s} = null;
FamilySymbol __sym_{s} = null;
FamilyInstance __inst_{s} = null;
double __v1_{s} = 0.0;
double __v2_{s} = 0.0;
double __v3_{s} = 0.0;
double __iv_{s} = 0.0;
double __ratio_{s} = 0.0;
double __pratio_{s} = 0.0;
double __dt_{s} = 0.0;
double __tv1_{s} = 0.0;
double __tv2_{s} = 0.0;"""

    return _authoring._with_program_helpers(
        f"{_authoring._AUTH_PREAMBLE}\n"
        f"// author_family {cs_line_comment_fragment(oid)} — соло-программа: "
        f"ВТОРОЙ документ, свои транзакции, свидетель ВНУТРИ семейства\n"
        + _VOLUME_READER_CS
        + pre_doc_guard
        + pre_identity_guard
        + decls + "\n\n"
        + template_cs + "\n\n"
        + collide_cs + "\n\n"
        + path_cs + "\n\n"
        + family_cs + "\n\n"
        + project_cs + "\n\n"
        + receipt_cs + "\n\n"
        + failure_warnings_into_results_cs("__KirFamFailures")
        + "__results[\"ok\"] = true;\n"
        "return __results;\n"
        "}\n"
        + failure_preprocessor_cs("__KirFamFailures")
        # 🔴 TWO DOCUMENTS — TWO CHANNELS OF REVIT REFUSALS, AND THIS IS NOT
        # SYMMETRY FOR SYMMETRY'S SAKE. The channel is static; one shared
        # between the two transactions would mean that the reset before the
        # PROJECT's transaction WIPES everything Revit said about the
        # FAMILY — and the receipt would fall silent about exactly the half
        # of the work the language did not have before. Mixing them into
        # one list would be a second evil: the project's "transaction
        # commit status" message would end up quoting a warning said about
        # the other document.
        + failure_preprocessor_cs("__KirFamDocFailures")
        + _FAMILY_REFUSAL_CLASS_CS
        + "private static class __KirPad\n{")


def _indent(text: str, pad: str) -> str:
    return "\n".join(pad + ln if ln.strip() else ln for ln in text.splitlines())


__all__ = ["FAMILY_TEMPLATES", "emit_author_family_program"]
