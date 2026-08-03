"""ops_families — load_family / create_type ops (wave/families, 2026-07-17).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.
Emitters live in authoring.py's shared _EMITTERS dict (companion-file pattern
already established by create_floor_by_contour/create_pipe_system — the
CONTRACT's "эмиттеры не в ops_*.py, координируются отдельно").

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

Dimension/material params are set by GENERIC NAME lookup (LookupParameter),
never a guessed BuiltInParameter: a scan of the real RevitAPI.xml doc
comments turned up no universal COLUMN_WIDTH/COLUMN_DEPTH BIP — only
per-category ones (GENERIC_WIDTH, FAMILY_WIDTH_PARAM, DOOR_WIDTH, ...), and
the materials-finishes.md wiki page explicitly documents STRUCTURAL_MATERIAL_
PARAM as "присутствует, но тихо игнорируется" on non-structural host types —
exactly the silent-wrong-answer trap KIR exists to avoid. Family templates
name their rectangular dims differently (b/h is the common RU-template
convention; some use Width/Depth) — param_width_name/param_depth_name let
the caller override the default, and a not-found/read-only name is a typed
refusal (KIR-X999 at runtime), never a silent no-op.

load_family takes an EXPLICIT path — no standard-library-path guessing.
Revit's standard library layout is version- AND locale-dependent
(confirmed by the wiki's own FAM-034 recipe, which hardcodes a path and
tells the caller to edit it); inventing a path-resolution table here would
be exactly the mnimaya inzheneriya (мнимая инженерия) this program exists
to avoid. A future wave CAN add a `library_path` grounded pool (server-side
catalog of known install paths) — that is a new snapshot pool, Fable-level
per the CONTRACT, not invented in this file.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

OPS = [
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
        # Допуск ре-чтения width/depth.  Был захардкожен в эмитируемой C#
        # (`> 0.5`), при том что WitnessCheck заявлял `tol_key="param_mm"` —
        # ссылка в пустоту, то есть ложь о происхождении числа.  Теперь оно
        # живёт в ОДНОМ месте, как требует registry_base.
        tolerances={"param_mm": 0.5},
        post=("new FamilySymbol exists (Duplicate of source_type, or the "
              "SAME element re-used when new_name already names a type of "
              "the same Family — idempotent re-run, never a duplicate-name "
              "exception); width_mm/depth_mm held on param_width_name/"
              "param_depth_name post-commit (±0.5mm, re-read); material "
              "(if given) resolved by exact Material name and set via "
              "STRUCTURAL_MATERIAL_PARAM when the parameter exists and is "
              "writable on this family template — absent/read-only is a "
              "typed rollback refusal, NEVER a silent skip"),
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
]
