"""Bridge protocol models — matches BRIDGE_PROTOCOL.md and contract fixtures."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# --- JSON-RPC envelope ---

class BridgeRequest(BaseModel):
    """JSON-RPC 2.0 request to the bridge."""
    jsonrpc: str = "2.0"
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
    jsonrpc: str = "2.0"
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
    """
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
