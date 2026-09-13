"""ops_families — load_family / create_type ops (wave/families, 2026-07-17).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.
Emitters live in authoring.py's shared _EMITTERS dict (companion-file pattern
already established by create_floor_by_contour/create_pipe_system — the
CONTRACT's "emitters do not live in ops_*.py, they are coordinated separately").

SCOPE (flagged, not invented): create_type covers SYMBOL-based types only
(FamilySymbol duplication — structural/architectural columns, the exact
prod incident this wave fixes: RC columns coming in as steel because no
create_type existed). Wall/floor/roof TYPES are NOT symbols — their
dimensions live in CompoundStructure layers (SetLayers/IsValid/
SetCompoundStructure, see wiki materials-finishes.md/walls-openings.md),
a materially different and riskier mechanism (layer validity across
curtain/membrane/vertically-compound types). Extending create_type to
host-object types (WallType/FloorType/RoofType via HostObjAttributes.
Duplicate + GetCompoundStructure) is EXPLICITLY OUT OF SCOPE for this wave
— left for a follow-up that can gate it properly, not guessed here.

🔴 THIS FOLLOW-UP HAPPENED ON 2026-08-23 AND SITS BELOW, IN THIS SAME FILE:
`create_wall_type` — a separate op, not an extension of `create_type`. The
paragraph above is left VERBATIM, because it is correct as history and as an
argument: it named the mechanism (`CompoundStructure`), named the risk
(curtain/membrane/vertically-compound), and declined to guess. All three
predictions came true — of the 44 K1 wall types, six fail to build for
exactly the reasons named there.

Dimension/material params are set by GENERIC NAME lookup (LookupParameter),
never a guessed BuiltInParameter: a scan of the real RevitAPI.xml doc
comments turned up no universal COLUMN_WIDTH/COLUMN_DEPTH BIP — only
per-category ones (GENERIC_WIDTH, FAMILY_WIDTH_PARAM, DOOR_WIDTH, ...), and
the materials-finishes.md wiki page explicitly documents STRUCTURAL_MATERIAL_
PARAM as "present, but silently ignored" on non-structural host types —
exactly the silent-wrong-answer trap KIR exists to avoid. Family templates
name their rectangular dims differently (b/h is the common RU-template
convention; some use Width/Depth) — param_width_name/param_depth_name let
the caller override the default, and a not-found/read-only name is a typed
refusal (KIR-X999 at runtime), never a silent no-op.

load_family takes an EXPLICIT path — no standard-library-path guessing.
Revit's standard library layout is version- AND locale-dependent
(confirmed by the wiki's own FAM-034 recipe, which hardcodes a path and
tells the caller to edit it); inventing a path-resolution table here would
be exactly the make-believe engineering this program exists to avoid. A future wave CAN add a `library_path` grounded pool (server-side
catalog of known install paths) — that is a new snapshot pool, Fable-level
per the CONTRACT, not invented in this file.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

# ── FAMILY AUTHORING (2026-08-21) ──────────────────────────────────────────────
#
# 🔴 BEFORE THIS DAY, `NewFamilyDocument` WAS NEVER MENTIONED IN THE TREE, NOT
# ONCE (grep across all of `/opt/kukai-rebuild1/backend`, including .md and
# .cs — zero hits). About families, the language knew exactly four things,
# and all four were about SOMEONE ELSE'S work, done earlier: `load_family`
# (take from disk), `place_family` (place it), `create_type` (duplicate a
# type), `query_types` (ask about it). The language could not CREATE a
# family, and this was not a small hole.
#
# WHAT MEASURES IT. Everything KIR builds as free-form geometry is a
# `DirectShape`, and its own receipt says so plainly:
#
#     bim_semantics                    none
#     human_editable                   false
#     schedulable_as_building_element  false
#
# That is, not a building element: it will not appear in a schedule, cannot
# be edited by hand, and is neither a wall nor a window even if its volume
# matches to the cubic millimeter. Family authoring is the ONLY path from a
# `DirectShape` to real meaning for a shape that has no ready-made kind in
# Revit.
#
# WHY ONE OP, NOT FIVE (document, shape, parameter, binding, load). No
# foreign op can be wedged BETWEEN these steps: a family document does not
# survive the program's boundary — after `Close`, all of its elements are
# dead. Five ops would declare, as program points, things that are not
# program points, and the program "create the document; place the wall; add
# the parameter" would be legal by schema and unrealizable in substance. The
# unit of intent here is the whole family.
#
# WHERE EMISSION LIVES: `family_author_emit.py`, through `spec.SOLO_OPS` and
# `authoring._SOLO_PROGRAMS` — the very door set up for `create_stairs`, for
# an op that OWNS ITS OWN TRANSACTIONS. A family also owns a SECOND document,
# which makes it the same class, one notch stronger.

#: Height bounds are taken from the neighbor, not written here as a number:
#: on 2026-08-21 `ops_solid.MIN_EXTENT_MM` was already lowered from 100 to 1
#: by a live measurement, and a second copy of the number would not have
#: moved along with it (exactly the defect `family_recipe.py` found in
#: itself that same day).
from kir.ops_solid import MAX_EXTENT_MM, MIN_EXTENT_MM  # noqa: E402

#: Template kinds are taken from the REGISTRY, where they have lived since
#: 2026-09-01. A second list of kinds would drift from the first at the very
#: first new locale, so there is one carrier; taking it from the EMITTER
#: would mean the registry pulls in the emitter on load — a measured edge by
#: which the renderer used to reach into the compiler.
from kir.registry_base import FAMILY_TEMPLATES  # noqa: E402,F811

OPS = [
    OpSpec(
        name="author_family",
        effect=EffectKind.CREATE,
        # NOT `RESULT_FAMILY_SYMBOL`, EVEN THOUGH THE RESULT KIND ACTUALLY IS
        # ONE. `reference_kind` is the promise "a NEIGHBOR IN THE PROGRAM can
        # reference me," and a solo op has no neighbors by construction. A
        # promise nobody can consume is a lie about the language, even if a
        # harmless one.
        result=RESULT_UNREFERENCED_ELEMENT,
        family="authoring",
        params=(
            # THE AUTHOR GIVES THE FAMILY NAME, AND THIS IS REQUIRED. There
            # is nothing to derive it from: the shape has no name, the
            # profile has no name, and a generated "Family_1" would come
            # back in the receipt as a fact about the model and would land
            # in the schedule. The family name is the ONLY thing that
            # distinguishes it in the project browser.
            ParamSpec("family_name", "str", required=True, max_val=64),
            # THE TYPE NAME IS ALSO THE AUTHOR'S, AND ALSO REQUIRED. A new
            # family has NO types AT ALL (live refusal on 08-21:
            # `FamilyManager.Set` -> "There is no current type"), so we are
            # the ones creating the first type, and it must have a name — the
            # very one a human will see in the browser and in the schedule.
            #
            # 🔴 THE ABSENCE OF A DEFAULT HERE IS DELIBERATE, AND THIS IS A
            # MEASUREMENT, NOT TASTE. `ParamSpec.default` IS DEAD for the
            # `str` kind: `authoring_validation` reads the value as
            # `op.get(p.name)` WITHOUT a default (the `p.kind == "str"`
            # branch), unlike the `enum`/`int`/`num` branches, which use
            # `op.get(p.name, p.default)`. That is, a default declared here
            # would end up in the generated schema, the model would read it
            # as a promise — and would get a `KeyError` at emission.
            #
            # THE NUMBERS (measured 08-21 across the whole registry): 361
            # parameters, 23 of kind `str`, a default declared on TWO of
            # them — `create_type.param_width_name`='b' and
            # `param_depth_name`='h'. Both are dead, and both live as a
            # SECOND COPY in emission (`authoring.py:4428-4429`,
            # `op.get("param_width_name", "b")`), i.e. one law with two
            # homes. This cannot be fixed here (the file is spoken for), and
            # repeating it would mean buying the same shape of defect a
            # third time.
            ParamSpec("type_name", "str", required=True, max_val=64),
            # A TEMPLATE KIND, NOT A PATH. The path depends on the version,
            # the locale, and install settings; only the user's own machine
            # knows it, and it is asked there
            # (`Application.FamilyTemplatePath`). The list of kinds comes
            # from the emitter, where the candidate file names live.
            ParamSpec("template", "enum", default="generic_model",
                      choices=tuple(sorted(FAMILY_TEMPLATES))),
            # THE PROFILE is of the `region` kind, the same as
            # `create_solid_extrusion` uses. A format of its own for the
            # profile would become a second home for CONTOUR's laws (arcs,
            # openings, the strict interior), and would drift from it.
            ParamSpec("profile", "region", required=True),
            ParamSpec("height_mm", "mm", required=True,
                      min_val=MIN_EXTENT_MM, max_val=MAX_EXTENT_MM),
            # 🔴 FLEXIBILITY IS AN OBLIGATION, HENCE THE `required` FIELD.
            #
            # THE MEASUREMENT THAT BOUGHT THIS DECISION (2026-08-21, live
            # Revit 2026): the parameter `Высота_KIR` was changed from 800 to
            # 1600 — the volume stayed at 192,000,000 = 600 x 400 x 800. The
            # parameter exists, the formula reads backward, the solid does
            # NOT LISTEN to it, and all of this passes ABSOLUTELY SILENTLY.
            # With binding, the same measurement gives 192,000,000 ->
            # 384,000,000, a ratio of 2.0000.
            #
            # Hence: the author MUST name the parameter, and emission must
            # prove that the solid listens to it — by doubling it inside the
            # family document BEFORE saving. An optional field would mean
            # "a rigid family is fine too," and a rigid family is a
            # `DirectShape` with extra steps.
            # There is no default for the same reason as `type_name` above
            # (the default is dead for the `str` kind), and for its own
            # reason too: a human reads the handle's name in the type
            # properties, and «Высота_KIR» instead of «Высота» is our
            # footprint left silently in someone else's model.
            ParamSpec("flex_param", "str", required=True, max_val=64),
            # 🔴 THE SECOND AXIS OF FLEXIBILITY IS THE PLAN (2026-08-21). The
            # named limit of the first edition read: "the family stretches
            # upward and does not stretch in plan." People bend the plan not
            # with a parameter on the shape but with REFERENCE PLANES:
            # geometry is aligned to a plane, planes are dimensioned, the
            # dimension is labeled with a parameter.
            #
            # THE MEASUREMENT THAT BOUGHT THE FIELD (live, Revit 2026,
            # "Project1"): two `NewReferencePlane`, two `NewAlignment` on the
            # profile's vertical edges, a `NewDimension` between the planes,
            # and `Dimension.FamilyLabel = parameter` gave a volume of
            # 192,000,000 -> 384,000,000 when the width was doubled, a ratio
            # of 2.0000. All members 6/6.
            #
            # OPTIONAL, AND THIS IS NOT A CONCESSION. Flexibility along
            # HEIGHT must exist for every family (`flex_param` required);
            # the plan bends ONLY for an axis-aligned rectangle without
            # openings, and requiring it of a round column would mean
            # requiring the impossible. Emission REFUSES and names the
            # profile kind, rather than building "something similar":
            # aligning to a plane only holds the edges that actually lie on
            # it, and for a non-rectangular profile it would produce a
            # family that LOOKS parametric and bends incorrectly.
            ParamSpec("flex_plan_param", "str", max_val=64),
            # WHERE THE .rfa LANDS. OPTIONAL AND WITHOUT A DEFAULT: if
            # omitted, control passes to the PROJECT'S OWN directory, and if
            # the project is not saved — a refusal naming both ways out. The
            # family is never placed into a temp directory: the path in the
            # receipt must outlive the session.
            ParamSpec("save_dir", "str", max_val=200,
                      omission_transfers=(
                          "каталог .rfa решает Document.PathName проекта; "
                          "у несохранённого проекта — типизированный отказ")),
            # THE INSTANCE POINT. Omitting it means "release the
            # DEFINITION, without placing it," and this is a legitimate
            # outcome — but then the receipt must print
            # `schedulable_as_building_element: null` with a reason, not
            # `true`: it is the instance that lands in the schedule, not the
            # definition.
            #
            # THERE IS NO LEVEL HERE, AND THIS IS A NAMED ABSENCE, NOT A
            # FORGOTTEN FIELD. The lesson of `create_beam.level` (08-18: 540
            # of 540 beams at z=0 while "Floor 5" was written) — a required
            # field that decides nothing is worse than none at all. Which
            # level Revit will assign to an instance placed by a point has
            # NOT BEEN MEASURED here, so the field is not introduced, and the
            # receipt names this in `unverified_ru`.
            ParamSpec("place_at", "pt_xyz"),
        ),
        capability=(("create", "family"),),
        post=("template resolved from Application.FamilyTemplatePath at "
              "execute time — a missing template is a typed refusal naming "
              "the directory, every candidate filename tried and the .rft "
              "files actually present, never a bare not-found; "
              "family document created from that template and closed via "
              "Close(false) in a finally on every exit path; "
              "the body FLEXES: the family parameter is doubled inside the "
              "family document, the extrusion volume is re-read and the "
              "ratio must be 2.0 within a derived tolerance, then the value "
              "is restored and the volume re-checked — an unbound parameter "
              "rolls the whole program back and never reaches disk; "
              "loaded family name and symbol name equal what the author "
              "asked (semantic); "
              "the placed instance carries the volume measured inside the "
              "family document, and sits on the authored symbol, when "
              "place_at is given (geometry)"),
        writes_model=True,
        # EMPTY BY CONSTRUCTION: the family is created FROM A TEMPLATE, not
        # from an existing model element — there is nothing to ground. The
        # only outward look (whether the name is taken in the project) is
        # read at runtime, because the snapshot does not carry a census of
        # families.
        grounded=(),
        # EMPTY BY CONSTRUCTION: the volume tolerance here is a function of
        # the op's geometry and Revit's own VertexTolerance, not a registry
        # constant. The same argument and the same shape as
        # `create_solid_extrusion`.
        tolerances={},
    ),
    OpSpec(
        name="create_type",
        effect=EffectKind.CREATE,
        result=RESULT_FAMILY_SYMBOL,
        family="authoring",
        params=(
            ParamSpec("source_type", "sel", required=True),
            ParamSpec("category", "enum", default="structural",
                      choices=("structural", "architectural")),
            ParamSpec("new_name", "str", required=True),
            ParamSpec("width_mm", "mm", required=True, min_val=10, max_val=20_000),
            ParamSpec("depth_mm", "mm", min_val=10, max_val=20_000),
            # Family-template dimension parameter names vary (RU convention
            # b/h vs Width/Depth); override, never guess-and-silently-skip.
            ParamSpec("param_width_name", "str", default="b", max_val=128),
            ParamSpec("param_depth_name", "str", default="h", max_val=128),
            ParamSpec("material", "str", max_val=128),   # by-name; typed NOT_FOUND if absent in doc
        ),
        capability=(("create", "type"), ("create", "category")),
        # The width/depth re-read tolerance. Used to be hardcoded in the
        # emitted C# (`> 0.5`), while WitnessCheck declared
        # `tol_key="param_mm"` — a reference to nothing, i.e. a lie about
        # the number's origin. Now it lives in ONE place, as registry_base
        # requires.
        tolerances={"param_mm": 0.5},
        post=("new FamilySymbol exists, or the same element is read-only reused "
              "only when new_name names one type of the same Family with this "
              "exact creation marker (identity); "
              "foreign/ambiguous names refuse, existing drift is not repaired (semantic); "
              "named width/depth parameters must have observed Double storage and Length "
              "dimension before writing or read-only reuse (semantic); "
              "width_mm/depth_mm held on param_width_name/"
              "param_depth_name at pre-commit re-read, within 0.5mm (geometry); material "
              "(if given) resolved by a unique exact Material name and set on NEW types via "
              "STRUCTURAL_MATERIAL_PARAM when the parameter exists and is "
              "writable on this family template — absent/read-only is a "
              "typed rollback refusal, NEVER a silent skip (identity); new type ownership "
              "stamp must be written and read back (identity); existing type is not restamped (identity)"),
        writes_model=True,
        grounded=(("source_type", "column_symbols_{category}", True),),
    ),
    OpSpec(
        name="load_family",
        effect=EffectKind.CREATE,
        result=RESULT_FAMILY_SYMBOL,
        family="authoring",
        params=(
            ParamSpec("path", "str", required=True, max_val=260),   # MAX_PATH-safe cap
            ParamSpec("type_name", "str", max_val=128),   # given -> LoadFamilySymbol (ONE type); omitted -> LoadFamily (whole family, first symbol)
        ),
        capability=(("load", "family"), ("create", "family")),
        post=("path checked via File.Exists INSIDE the emitted C# at "
              "execute time on the Revit-bridge host (the only place that "
              "sees the user's filesystem — ground has no such access) — "
              "typed rollback+refusal on missing file, never a raw "
              "LoadFamily ArgumentException reaching the user; on success "
              "exactly one FamilySymbol is ACTIVE post-commit "
              "(symbol.Activate()+Regenerate, the "
              "'главная ловушка' from family-load-place.md); when the "
              "family/type was ALREADY loaded under the .rfa filename stem, "
              "the exact existing family/type is re-used and witnessed as "
              "already_loaded=true; a same-named type from another family "
              "is never substituted"),
        writes_model=True,
        grounded=(),
    ),
    # ── TRANSFERRING A FAMILY FROM DOCUMENT TO DOCUMENT (2026-08-23) ───
    #
    # 🔴 WHY NOT AN EXTENSION OF `load_family`, BUT A SEPARATE OP. The
    # neighbor above has a postcondition that says `File.Exists` — that is,
    # the FILE is part of its promise, not an implementation detail. Here
    # there is no file AT ALL: `EditFamily` hands back an in-memory family
    # document, and `LoadFamily(Document)` accepts it directly (both 6/6).
    # Adding "and if path was not given, then…" here would mean giving one
    # name two different postconditions — a shape this registry does not
    # hold.
    #
    # WHY IT IS NEEDED, IN NUMBERS. The `fresh_document` mode carries the
    # decompile off into a whole other document (K6: 68 of 68 programs, K3:
    # 54 of 54, `element_id` zero), and there is nothing there to receive
    # it: the authoring unit `АР_Квартира_1К` needs 11 families, and the
    # target "Project1" has ZERO of them — not even the family, let alone
    # the type (live query 08-23: 321 types, all template ones).
    #
    # THE PRECONDITION IS NAMED IN THE REFUSAL, NOT IMPLIED: both documents
    # must be open IN ONE Revit SESSION — `Application.Documents` lists only
    # that session's. This is not an implementation constraint, it is a
    # condition of the mechanism.
    OpSpec(
        name="transfer_family",
        effect=EffectKind.CREATE,
        result=RESULT_FAMILY_SYMBOL,
        family="authoring",
        params=(
            # The document is addressed by a TITLE SUBSTRING — exactly the
            # way the bridge selects it (`doc_contains`), and the model
            # already knows this idiom. `Title`, not `PathName`: an unsaved
            # document has an empty path. Zero matches and two matches are
            # DIFFERENT refusals, both printing the titles of open documents.
            ParamSpec("source_document", "str", required=True, max_val=260),
            # The family name is EXACT. A substring works for a document
            # title (which carries an extension and suffixes), but not for a
            # family: neighboring families in a project routinely differ
            # only by a suffix.
            ParamSpec("family_name", "str", required=True, max_val=128),
            ParamSpec("type_name", "str", max_val=128),
        ),
        capability=(("load", "family"), ("create", "family")),
        post=("семейство существует в ЦЕЛЕВОМ документе под запрошенным "
              "именем post-commit, перечитанное ИЗ МОДЕЛИ по своему Id, а не "
              "по эху вызова (materialize); его Name равно family_name, и "
              "одноимённое семейство из другого источника никогда не "
              "подставляется (identity); ровно один FamilySymbol АКТИВЕН "
              "post-commit — запрошенный type_name либо, когда он не дан, "
              "первый по порядку Ordinal (semantic); активный символ "
              "принадлежит именно перенесённому семейству (identity); при "
              "КОНФЛИКТЕ с уже существующим одноимённым семейством загрузка "
              "ПРЕРЫВАЕТСЯ Ревитом, и ни одно семейство целевого документа не "
              "заменяется молча (identity); штатный повтор узнаётся ДО вызова "
              "и отвечает already_present=true, переиспользуя РОВНО ТО "
              "семейство, что уже стоит в цели под этим именем (identity)"),
        writes_model=True,
        grounded=(),
    ),
    # ── MATERIAL FROM AN OPEN DOCUMENT (2026-08-24) ──────────────────
    #
    # 🔴 WHY IT IS NEEDED, IN NUMBERS. The K3 catalog of host types, sent
    # into a clean document on 08-24: 2 types out of 18 build, the rest are
    # missing 23 MATERIALS, and `create_wall_type` honestly refuses
    # ("transfer the materials before the type; substituting another one is
    # forbidden"). An op that creates or transfers a material did not exist
    # in the language AT ALL.
    #
    # 🔴 WHY A TRANSFER, NOT CREATION FROM VALUES. `Material.Create(doc,
    # name)` exists and compiles 6/6, and the temptation to assemble a
    # material from read-back fields (class, color, gloss) is strong. A
    # census of those same 23 K3 materials says why that would be A LIE:
    #
    #     appearance asset (AppearanceAsset)            21 of 23
    #     cut-pattern hatch                              12 of 23
    #     surface-pattern hatch                           8 of 23
    #     physical asset (StructuralAsset)                2 of 23
    #
    # An appearance asset is a separate render-library element, not
    # authorable from a program; hatches are their own
    # `FillPatternElement`s, absent in the target ("#Insulation - Type 4 -
    # Triangles"). A material assembled from values would arrive with the
    # right NAME and the right COLOR while losing the appearance for
    # twenty-one of twenty-three — exactly the shape we named that same day
    # for the wall-type catalog (32 types, zero materials: the generator
    # never wrote them at all, and "not in the target" became "that's what
    # was wanted"). `ElementTransformUtils.CopyElements` (6/6) carries the
    # node WITH ITS DEPENDENCIES.
    #
    # 🔴 WHY A SEPARATE OP, NOT A PARAMETER ON `transfer_family`. The same
    # three-mismatch argument that split `create_type` from
    # `create_wall_type`:
    #   * RESULT. There, a `FamilySymbol` and a reference to it; here, a
    #     `Material`, which today NO parameter of the language references —
    #     layers carry the name AS A STRING. Setting up a reference kind
    #     with no consumer would mean building a branch nothing can reach.
    #   * CONSTRUCTOR. There, `EditFamily` + `LoadFamily(Document)` and a
    #     SECOND document, opened and closed by us; here, a single
    #     `CopyElements` call inside an ordinary transaction, with the
    #     source only read.
    #   * WITNESS. There, the active symbol and its family membership; here,
    #     RE-READING BOTH SIDES: the target's fields are checked against the
    #     source's fields, because the op's promise is "as in the source,"
    #     not "as in the program."
    #
    # THE PRECONDITION IS NAMED IN THE REFUSAL, NOT IMPLIED: both documents
    # must be open IN ONE Revit SESSION — `Application.Documents` lists only
    # that session's. The same mechanism condition as `transfer_family`.
    OpSpec(
        name="transfer_material",
        effect=EffectKind.CREATE,
        result=RESULT_UNREFERENCED_ELEMENT,
        family="authoring",
        params=(
            # The document — by a TITLE SUBSTRING, as in `transfer_family`
            # and as the bridge selects it (`doc_contains`). Zero matches
            # and two — DIFFERENT refusals, both printing the titles of open
            # documents.
            ParamSpec("source_document", "str", required=True, max_val=260),
            # The material name is EXACT. Materials in a project routinely
            # differ only by a suffix ("Insulation_Extruded Polystyrene 150
            # mm" versus "...180 mm"), and a substring would carry off the
            # wrong one.
            ParamSpec("name", "str", required=True, max_val=128),
        ),
        capability=(("create", "material"),),
        post=("материал существует в ЦЕЛЕВОМ документе под запрошенным именем "
              "post-commit, перечитанный ИЗ МОДЕЛИ по своему Id, а не по эху "
              "вызова (materialize); его Name равно name (identity); "
              "MaterialClass и MaterialCategory равны исходным, прочитанным у "
              "ИСТОЧНИКА в том же прогоне (semantic); Color равен исходному по "
              "всем трём каналам (semantic); приложение внешнего вида "
              "ПРИСУТСТВУЕТ ровно тогда, когда оно есть у источника, и его имя "
              "совпадает — потеря внешнего вида при верном имени есть главный "
              "исход, ради которого этот оп не собирает материал по значениям "
              "(identity); имена штриховок поверхности и разреза совпадают с "
              "исходными, включая их отсутствие (identity); штатный повтор "
              "узнаётся ДО вызова и отвечает already_present=true, "
              "переиспользуя РОВНО ТОТ материал, что уже стоит в цели под этим "
              "именем, и НИКОГДА не подменяя его (identity); одноимённый "
              "материал целевого документа не заменяется и не дублируется "
              "(identity)"),
        writes_model=True,
        grounded=(),
    ),
    # ── A WALL TYPE WITH A GIVEN LAYER STACK (2026-08-23) ────────────
    #
    # 🔴 WHY A SEPARATE OP, NOT AN EXTENSION OF `create_type`. The answer was
    # written IN THIS SAME FILE on 2026-07-17, in the module header, and it
    # has not changed: "Wall/floor/roof TYPES are NOT symbols — their
    # dimensions live in CompoundStructure layers … EXPLICITLY OUT OF SCOPE
    # for this wave — left for a follow-up that can gate it properly, not
    # guessed here." This is that very follow-up.
    #
    # The argument is not convenience, but three mismatches:
    #   * RESULT. `create_type` gives `RESULT_FAMILY_SYMBOL`, and its
    #     emitter casts `as FamilySymbol`. A `WallType` is not a
    #     `FamilySymbol`; the shared `ElementType` ancestor is little help,
    #     because everything past it diverges.
    #   * CONSTRUCTOR. There, `Duplicate` + `Parameter.Set` by parameter
    #     NAME. Here, `Duplicate` + `GetCompoundStructure` + `SetLayers` +
    #     `SetCompoundStructure`, and `SetLayers` is documented as
    #     "Completely resets this CompoundStructure."
    #   * WITNESS. There, two numbers are re-read. Here, the LAYER STACK is
    #     re-read: the number of layers, the thickness and function of
    #     each, the sum against the total thickness.
    #
    # And above all, the cost of merging. A census of the registry on
    # 2026-08-23: of 51 parameter names shared by two or more ops, 25
    # DIVERGE. The worst divergences are not in bounds but in meaning:
    # `category` carries TWO different enumerations across 9 ops, `path`
    # carries THREE kinds across 6 (polyline, 3D polyline, file path).
    # Dragging layers into `create_type` would mean adding a twenty-sixth
    # name with two ontologies — exactly the disease we counted that same
    # day.
    #
    # WHY IT IS NEEDED, IN NUMBERS. The authored K3 apartment, sent into a
    # clean "Project1": 29 operations, 9 make it through, 20 are blocked —
    # and TWELVE of those are ALL the apartment's walls, which have no type
    # (0 of 185 in the target).
    #
    # WHAT REPRODUCES AND WHAT DOES NOT — THE K1 MEASUREMENT (44 wall
    # types):
    #   builds           38   and for ALL 38 the sum of layers equals the total thickness
    #   fails to build    6   4 with no structure · 3 Curtain · 2 vertically_compound
    #                         · 1 Stacked  (a type can carry more than one label)
    OpSpec(
        name="create_wall_type",
        effect=EffectKind.CREATE,
        result=RESULT_WALL_TYPE,
        result_by_param=("host_kind", {
            "wall": RESULT_WALL_TYPE,
            "floor": RESULT_FLOOR_TYPE,
            "roof": RESULT_ROOF_TYPE,
            "ceiling": RESULT_CEILING_TYPE,
        }),
        family="authoring",
        params=(
            # The source is required and NOT implied. `Duplicate` needs an
            # instance, and "take the default type" would silently bind the
            # result to the target document's own settings — a quantity
            # invisible in the program. What survives `SetLayers` is named
            # in post.
            ParamSpec("source_type", "sel", required=True),
            ParamSpec("new_name", "str", required=True, max_val=128),
            ParamSpec("layers", "wall_layers", required=True),
            # 🔴 THE HOST-TYPE KIND (2026-08-24). The op stopped being about
            # walls and became about the HOST TYPE — the shared ancestor
            # `HostObjAttributes` (verified by compilation, 6/6 across all
            # six versions: all four classes reduce to it with one array).
            #
            # WHY A PARAMETER, NOT THREE NEW OPS. There is one constructor
            # (`Duplicate` + `CreateSimpleCompoundStructure` +
            # `SetCompoundStructure`, 6/6 for each class) and one witness
            # (the layer stack). Three copies of one body would be our own
            # named defect: the quantity would live in several places, and
            # nothing would keep them in sync.
            #
            # WHY THE NAME `host_kind`, NOT `kind`. The name `kind` is
            # ALREADY taken in this registry by `kind_enum` on two ops. The
            # 08-23 census: of 51 parameter names shared by two or more ops,
            # 25 diverge, and the worst is one name with two ontologies. We
            # are not introducing a third.
            #
            # WHY THE DEFAULT `wall`, NOT `required=True`. Every program
            # already written must compile to the SAME BYTES: an omitted
            # parameter answers `wall`, and the wall branch in the emitter
            # stays word-for-word the same, right down to `WallType.Width`
            # in the witness (the other three classes have NO `Width`
            # property — 0/6 — and there `CompoundStructure.GetWidth()` is
            # read instead).
            #
            # HONESTLY ABOUT THE OP'S NAME: `create_wall_type(host_kind=
            # "floor")` reads badly, and this is a NAMED DEBT, not an
            # oversight. Renaming it to `create_host_type` costs the golden
            # samples, the journal, and every program already written; the
            # owner's decision was "would rather not have new ops," and the
            # name was left as it is.
            ParamSpec("host_kind", "enum", default="wall",
                      choices=("wall", "floor", "roof", "ceiling")),
        ),
        capability=(("create", "type"), ("create", "wall_type"),
                    ("create", "floor_type"), ("create", "roof_type"),
                    ("create", "ceiling_type")),
        # The layer-thickness re-read tolerance. It lives HERE because the
        # witness below references it: a declared `tol_key` must be true —
        # exactly the defect that was fixed for `create_type` ("a reference
        # to nothing").
        tolerances={"layer_mm": 0.5},
        post=("тип стены существует под именем new_name post-commit, "
              "перечитанный ИЗ МОДЕЛИ по своему Id, а не по эху вызова "
              "(materialize); его Name равно new_name, и одноимённый тип "
              "НИКОГДА не подменяется чужим — повтор только читает единственный "
              "тип с точным маркером этого запроса, не меняет его пирог и не "
              "исправляет drift (identity); новый тип требует записи/перечитывания маркера (identity); число слоёв "
              "перечитанного `GetCompoundStructure().GetLayers()` равно длине "
              "layers (semantic); толщина каждого слоя равна запрошенной "
              "±0.5 мм и функция каждого слоя равна запрошенной, слой в слой "
              "по порядку снаружи внутрь (geometry); `WallType.Width` равен "
              "сумме толщин слоёв ±0.5 мм — инвариант, проверенный на 38 из "
              "38 воспроизводимых типов K1 и ЛОЖНЫЙ у vertically_compound "
              "(два слоя по 80 мм при общей толщине 80), которые оп "
              "отказывает (geometry); у трёх остальных родов та же сумма "
              "перечитывается "
              "`CompoundStructure.GetWidth()`, потому что свойства `Width` у "
              "их классов НЕТ ВООБЩЕ (0/6 на настоящих сборках 2021-2026 при "
              "двух отрицательных контролях 0/6) (geometry); материал слоя разрешается ТОЧНЫМ "
              "именем — отсутствие или неоднозначность имени есть "
              "типизированный отказ с откатом, НИКОГДА не подстановка "
              "первого попавшегося и никогда не молчаливый пропуск "
              "(identity); слой БЕЗ ключа material создаётся с "
              "InvalidElementId — законное состояние Revit, а не наш пробел "
              "(identity); род источника обязан быть Basic — Curtain, Stacked "
              "и отсутствие CompoundStructure суть отказы, а не похожий тип "
              "(semantic); источник обязан быть ТОГО ЖЕ рода, что "
              "создаваемый тип (`Duplicate` — метод экземпляра), и потому "
              "заземляется в пул своего рода, а не всегда в `wall_types` "
              "(identity); у родов floor/roof/ceiling затвора «Basic» нет и "
              "быть не может — свойства `Kind` у их классов НЕТ (0/6), — и "
              "предполётом там служит наличие CompoundStructure у источника "
              "(semantic)"),
        writes_model=True,
        grounded=(("source_type", "wall_types", True),),
        # The source is of the SAME KIND as the type being created:
        # `Duplicate` is an instance method, and a roof type is born only
        # from a roof type.
        grounded_pool_by_param=("host_kind", {
            "wall": {"source_type": "wall_types"},
            "floor": {"source_type": "floor_types"},
            "roof": {"source_type": "roof_types"},
            "ceiling": {"source_type": "ceiling_types"},
        }),
    ),
]
