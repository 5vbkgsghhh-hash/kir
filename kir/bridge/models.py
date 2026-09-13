"""Bridge protocol models — matches BRIDGE_PROTOCOL.md and contract fixtures."""

from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# --- JSON-RPC envelope ---

class BridgeRequest(BaseModel):
    """JSON-RPC 2.0 request to the bridge."""
    #: 🔴 NOT A FREE-FORM STRING (30.08.2026, F-350). The field is declared
    #: by the protocol, not by us: `Literal` makes this a PROPERTY, not a
    #: convention.
    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: str


class BridgeErrorData(BaseModel):
    """Error detail inside a JSON-RPC error response."""
    code: int
    message: str
    data: Optional[dict[str, Any]] = None


class BridgeResponse(BaseModel):
    """JSON-RPC 2.0 response from the bridge."""
    #: 🔴 NOT A FREE-FORM STRING (30.08.2026, audit finding F-350).
    #: Previously an envelope with `jsonrpc: "garbage"` passed parsing
    #: silently — meaning the model agreed to read as JSON-RPC something
    #: not declared as such.
    jsonrpc: Literal["2.0"] = "2.0"
    result: Optional[dict[str, Any]] = None
    error: Optional[BridgeErrorData] = None
    id: str

    @property
    def is_error(self) -> bool:
        return self.error is not None


class BridgeError(Exception):
    """Raised when the bridge returns a JSON-RPC error."""
    def __init__(self, code: int, message: str, data: Optional[dict[str, Any]] = None):
        self.code = code
        self.error_message = message
        self.data = data or {}
        super().__init__(f"Bridge error {code}: {message}")


# --- Ping ---

class PingResult(BaseModel):
    status: str
    revit_version: str
    revit_build: str
    document_name: Optional[str] = None
    document_path: Optional[str] = None
    has_document: bool
    bridge_version: str
    uptime_seconds: int


# --- Context ---

class CategoryInfo(BaseModel):
    name: str
    name_ru: str
    count: int
    builtin: str


class LevelInfo(BaseModel):
    name: str
    elevation_m: float
    id: int


class ViewInfo(BaseModel):
    name: str
    type: str
    id: int


class SelectionInfo(BaseModel):
    count: int
    element_ids: list[int]
    categories: list[str]


class PhaseInfo(BaseModel):
    name: str
    id: int


class DocumentInfo(BaseModel):
    name: str
    path: str
    revit_version: str


class ContextResult(BaseModel):
    document: DocumentInfo
    categories: list[CategoryInfo]
    levels: list[LevelInfo]
    current_view: ViewInfo
    selection: SelectionInfo
    phase: PhaseInfo
    units: str
    warnings_count: int

    # Family editor mode — populated by C# ContextCollector when doc.IsFamilyDocument is true.
    # Project-doc context leaves these at defaults (is_family_editor=False).
    is_family_editor: bool = False
    family_category: Optional[str] = None
    family_parameters: list[str] = Field(default_factory=list)
    family_reference_planes: list[str] = Field(default_factory=list)


# --- Family Passport (rich inspection of family document state) ---
# Returned by `family_inspect` bridge method. Read-only snapshot of the
# family doc — used by Gemini to know current parameters/types/solids/refs
# before generating tool calls. All dimensions in millimetres (converted
# from Revit's internal feet on the C# side).

class FamilyParameterInfo(BaseModel):
    name: str
    group: str = ""                # e.g. "Dimensions", "Constraints", "Identity"
    spec_type: str = ""            # e.g. "Length", "Area", "Boolean.YesNo"
    storage_type: str = ""         # "Double" | "Integer" | "String" | "ElementId" | "None"
    is_instance: bool = False
    is_shared: bool = False


class FamilyTypeInfo(BaseModel):
    name: str
    is_current: bool = False
    # Snapshot of this type's parameter values keyed by parameter name.
    # Values are normalised: Length params → millimetres; others → str.
    parameter_values: dict[str, Any] = Field(default_factory=dict)


class BoundingBoxMm(BaseModel):
    min_x_mm: float
    min_y_mm: float
    min_z_mm: float
    max_x_mm: float
    max_y_mm: float
    max_z_mm: float


class FamilySolidInfo(BaseModel):
    id: int                        # ElementId.Value
    kind: str                      # "Extrusion" | "Blend" | "Sweep" | "Revolution" | "SweptBlend" | "GeomCombination"
    is_solid: bool = True          # false = void
    subcategory: str = ""
    material_id: int = -1
    material_name: str = ""
    bbox: Optional[BoundingBoxMm] = None


class FamilyRefPlaneInfo(BaseModel):
    id: int
    name: str
    origin_mm: list[float] = Field(default_factory=list)   # [x, y, z]
    normal: list[float] = Field(default_factory=list)      # [nx, ny, nz]


class FamilyLabeledDimInfo(BaseModel):
    id: int                        # Dimension ElementId.Value
    refs: list[int] = Field(default_factory=list)  # element IDs referenced (ref planes or extrusion faces)
    linked_param: str = ""         # FamilyParameter name (empty if dim is not labeled)
    value_mm: Optional[float] = None  # current measured value, mm


class FamilyMaterialInfo(BaseModel):
    id: int
    name: str


class FamilyPassport(BaseModel):
    """Rich snapshot of a Revit family document — read-only inventory.

    Returned by the C# bridge `family_inspect` method. Each subquery on the
    C# side is independently try/catch'd, so partial passports are OK (the
    field defaults to empty/None rather than failing the whole call).

    🔴 A MARK OF A COMPLETED INSPECTION IS MANDATORY (29.08.2026, audit
    finding F-349). Before it, `FamilyPassport.model_validate({})` produced
    a FULL-FLEDGED passport of an empty family with `partial_failures ==
    []` — that is, "inspection ran, no failures, nothing inside." Three
    DIFFERENT facts — "no result arrived," "fields got lost to protocol
    drift," and "the family really is empty" — were ONE record, and an
    emptiness that cannot be told apart from a fact is a fabricated fact.

    The direction is set not by opinion but by THIS FILE'S OWN CONVENTION:
    three neighboring models (`ExecuteResult`, `ContextResult`,
    `PingResult`) refuse by name on an input of `{}`, and only this one
    accepted it silently.

    Defaults for FIELDS remain: a partial passport is legitimate, and the
    argument in the docstring above about independent try/catch holds — it
    is about the PART. What cannot be a default is the FACT of the
    inspection ITSELF.

    🔴 THE FIX HAS TWO ENDS, AND THE SECOND END IS NOT HERE. The C# side
    must start sending `"inspected": true`. Until it does,
    `family_inspect()` will ALWAYS refuse — and that is accepted knowingly:
    a measurement on 30.08.2026 established that `BridgeClient.family_inspect()`
    today has NOT A SINGLE live caller (neither in `kir/` nor in `kukai/`),
    and the C# bridge of this tree has no `family_inspect` handler either.
    So the cost of the fix today is ZERO, while after it is wired up the
    same fix would become risky and would be postponed yet again. The
    refusal here is loud and named, not silent and false.
    """
    #: Set ONLY by the side that actually went through the collectors.
    #: Absence -> ValidationError, like the three neighboring models in
    #: this file.
    inspected: bool = Field(
        description="C#-сторона обязана слать true: признак того, что осмотр "
                    "документа СОСТОЯЛСЯ. Отсутствие поля — не «пустое "
                    "семейство», а отсутствие осмотра (F-349)")

    category: str = ""                 # OwnerFamily.FamilyCategory.Name
    template_name: str = ""            # heuristic — derived from category + title if needed
    revit_version: str = ""

    parameters: list[FamilyParameterInfo] = Field(default_factory=list)
    types: list[FamilyTypeInfo] = Field(default_factory=list)
    solids: list[FamilySolidInfo] = Field(default_factory=list)
    reference_planes: list[FamilyRefPlaneInfo] = Field(default_factory=list)
    labeled_dimensions: list[FamilyLabeledDimInfo] = Field(default_factory=list)
    materials: list[FamilyMaterialInfo] = Field(default_factory=list)

    # Soft-failure diagnostics: if any subquery threw on the C# side,
    # the name is appended here so the LLM can degrade gracefully.
    partial_failures: list[str] = Field(default_factory=list)


# --- Execute ---

class ExecuteResult(BaseModel):
    success: bool
    output: Any = None
    output_type: Optional[str] = None
    execution_time_ms: int = 0
    transaction_status: Optional[str] = None


# --- Select ---

class SelectResult(BaseModel):
    selected_count: int
    invalid_ids: list[int] = Field(default_factory=list)


# --- Highlight ---

class HighlightColor(BaseModel):
    r: int
    g: int
    b: int


class HighlightResult(BaseModel):
    highlighted_count: int
    invalid_ids: list[int] = Field(default_factory=list)


# --- Export View ---

class ExportViewResult(BaseModel):
    success: bool
    file_path: str = ""
    format: str = ""
    width: int = 0
    height: int = 0


# --- Import CAD ---

class ImportCadResult(BaseModel):
    success: bool
    element_id: Optional[int] = None
    message: str = ""
