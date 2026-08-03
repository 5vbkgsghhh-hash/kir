"""ops_struct — structural ops (beams/foundations/rebar). wave/struct
(2026-07-17): create_beam + create_foundation. Rebar stays STUB (out of this
wave's scope — see wave report).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

create_beam: FamilyInstance over a line, StructuralType.Beam — the same
NewFamilyInstance(Line, FamilySymbol, Level, StructuralType) overload the
gold SDK sample CreateBeamsColumnsBraces/CS/CreateBeamsColumnsBraces.cs
uses (PlaceBeam(), verified locally at
/root/27B/harvest/sdk_samples/snapshot/2025/Samples/CreateBeamsColumnsBraces/CS/CreateBeamsColumnsBraces.cs
lines 376-388: `Line line = Line.CreateBound(...); ... NewFamilyInstance(line,
beamType, topLevel, StructuralType.Beam);` with an IsActive/Activate() guard
— exactly authoring.py's existing _symbol_res() helper). Version-safe
2021-2026: same overload family create_column already relies on, only the
StructuralType enum member differs.

p0_mm/p1_mm are REQUIRED 3D (pt_xyz, like create_pipe) rather than 2D-plus-
level-elevation (like create_wall): a beam's two ends commonly sit at
DIFFERENT elevations (sloped beam / connecting columns whose tops differ),
so silently defaulting a missing Z to 0 (authoring._pt3's existing behavior
for a bare-2D point) would place a beam at absolute Z=0 while the resolved
level sits at its own elevation — a silent-wrong floating beam, exactly the
class of bug this project exists to kill. authoring.validate()'s dims-by-
name dispatch (`dims = (3,) if name in ("create_pipe", "create_duct",
"create_cable_tray") else (2, 3)`) is name-hardcoded to a tuple that does
NOT include create_beam; "create_beam" must be appended to that tuple for
the 3D requirement to actually be enforced (currently a (2,3) fallthrough
would silently accept a 2D point here too). This is a ONE-TOKEN additive
touch to a shared line in authoring.py, made alongside the _EMITTERS
registration (same file already gets touched per every prior wave's
precedent — see wave/mep's authoring.py diff) — flagged explicitly in the
wave report as a real, unavoidable shared-file dependency, not invented
scope-creep.

create_foundation: TWO real, distinct structural varieties, discriminated by
`variety` (NOT named "kind" — see naming note below):
  - variety="isolated" (столбчатый под колонну/точку): FamilyInstance placed
    at a point, StructuralType.Footing. Mirrors create_column's point-
    placement shape exactly (NewFamilyInstance(XYZ, FamilySymbol, Level,
    StructuralType)), enum member swapped Column->Footing. StructuralType.
    Footing verified as a REAL enum member via local SDK grep (BoundaryConditions/
    CS/{BoundaryConditionsData,Command}.cs read/filter it off existing
    instances — no local sample CREATES one, so the create-side call is
    confident-by-overload-analogy + enum-verified, not sample-verified;
    flagged in the wave report per the task's own escape hatch).
  - variety="slab" (ленточный/плитный — modeled as a structural mat/strip
    footing, i.e. a structural Floor by contour): this IS create_floor's
    existing structural=True path (create_floor's own post-condition already
    says "structural flag == requested (semantic)" — a foundation slab is
    that op with structural forced True). Reused, not duplicated: struct_emit.
    _emit_foundation_slab mirrors _emit_floor's 2022+/2021 structural path at
    the same fidelity (see struct_emit.py's module docstring for why it's a
    mirror, not a cross-import of a private function). No new C# geometry
    logic invented for this variant.
  - a true ribbon/grillage foundation (real ростверк geometry: varying
    width along a beam-like path, stepped sections) is NOT modeled: no
    confident single-call Revit API shape and no local gold sample to check
    against. FOUNDATION_UNSUPPORTED_KIND (struct_emit.py) is the typed
    refusal for any variety outside the closed {isolated, slab} enum — never
    a silent guess.

NAMING NOTE: the discriminator param is "variety", not "kind" — this
registry reserves "kind" as a vocabulary word for ParamSpec.kind=="kind_enum"
(the closed Revit-object-kind table wall/door/floor/.../other, SPEC 12.8),
and test_invariants.py's test_schema_generates_and_is_closed asserts BY
PROPERTY NAME that any op-schema field literally called "kind" carries
spec.KIND_ESCAPE in its enum — a real, deliberate safety invariant (every
closed-kind-enum must have an escape hatch so an unrecognized category never
silently guesses) enforced by name-match rather than by ParamSpec.kind value.
A param named "kind" holding {"isolated","slab"} (no escape value — this
wave has no honest escape/other bucket for foundation variety, unlike a
Revit-object-kind table) would collide with that invariant and is a correct
FAIL, not a test bug to route around by loosening the shared test. Renamed
instead — the honest fix.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

OPS = [
    OpSpec(
            name="create_beam",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # named "symbol" (not "type"): a beam is a FamilyInstance, so
                # its type-selector resolves to a FamilySymbol via the SAME
                # shared _symbol_res()/IsActive-Activate() helper create_column/
                # create_window/create_door/place_family already use (which
                # hardcodes the param key "symbol") — "type" is reserved in
                # this registry for ElementType-based ops (wall/floor/roof)
                # with different resolution semantics (doc-default support a
                # FamilySymbol selector doesn't have). Consistent naming, not
                # an arbitrary choice.
                ParamSpec("symbol", "sel"),        # omitted -> sole snapshot entry, else AMBIGUOUS
            ),
            capability=(("create", "element"),),
            post=("beam exists; LocationCurve endpoints == p0/p1 (±5mm, 3D) — "
                  "положение пришпилено целиком именно здесь; опорный уровень "
                  "СУЩЕСТВУЕТ (topology), но КАКОЙ — выводит Revit из отметки "
                  "кривой, а не из аргумента level: замерено 27.07, передан "
                  "L_01 @ 0 при кривой на Z=3000 -> привязка к L_01ДОО1_+2.500. "
                  "Полученный уровень читается в свидетель "
                  "(reference_level_id/reference_level), а не навязывается; "
                  "StructuralType == Beam (semantic, witness)"),
            writes_model=True,
            # 03.08: обещанные ±5 мм ЖИВУТ ЗДЕСЬ.  До этого `post` обещал
            # число, которого реестр назвать не мог, а эмиттер штамповал
            # tol_key="endpoint_mm" — ссылка в пустоту (дефект create_type
            # дословно).  Число ТО ЖЕ, что стояло литералом в struct_emit.
            tolerances={"endpoint_mm": 5.0},
            grounded=(("level", "levels", True), ("symbol", "beam_types", False)),
        ),
    OpSpec(
            name="create_foundation",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("variety", "enum", required=True,
                          choices=("isolated", "slab")),
                # isolated-only:
                ParamSpec("xy", "pt_xy"),
                ParamSpec("symbol", "sel"),         # omitted -> sole snapshot entry
                # slab-only (mirrors create_floor's own outline/holes/type):
                ParamSpec("outline", "pts"),
                ParamSpec("holes", "pts_list"),     # 2022+ only, same as create_floor
                ParamSpec("type", "sel"),           # omitted -> doc default floor type
                # shared:
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
            ),
            capability=(("create", "element"),),
            post=("variety=isolated: footing exists; LocationPoint == xy (±5mm); "
                  "base level == resolved level (topology, BIP chain); "
                  "StructuralType == Footing (semantic, witness). "
                  "variety=slab: structural floor exists; level binding == resolved "
                  "level (topology); bbox XY extents == outline extents (±50mm); "
                  "structural flag forced true (semantic) — this IS create_floor's "
                  "structural path, reused not duplicated. "
                  "any other variety value -> typed refusal (KIR-E004), never a guess"),
            writes_model=True,
            # 03.08: обе обещанные величины — по своей разновидности.
            # `location_mm` — точка отдельно стоящего башмака (±5 мм),
            # `bbox_mm` — габарит плиты (±50 мм, тот же ключ и то же число,
            # что у create_floor: плита фундамента ЕСТЬ структурное
            # перекрытие).  Числа те же, что стояли литералами.
            tolerances={"location_mm": 5.0, "bbox_mm": 50.0},
            grounded=(("level", "levels", True),
                      ("symbol", "foundation_symbols", False),
                      ("type", "floor_types", False)),
        ),
]
