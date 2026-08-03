"""Template manifest schemas.

Per spec Section 7.2. Each Jinja2 template (`*.cs.j2`) ships with a
`.manifest.yaml` sidecar declaring required parameters with types and
bounds. Manifest validation happens before render, so we never produce
C# from invalid inputs.
"""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class ManifestValidationError(ValueError):
    """Raised when args fail to validate against a ManifestSpec."""


class ManifestParameter(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    type: Literal["string", "int", "float", "bool", "list"]
    required: bool = True
    min: float | int | None = None
    max: float | int | None = None
    description: str | None = None


class ManifestSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    template: str = Field(..., description="filename of .cs.j2 template")
    parameters: list[ManifestParameter]
    expected_category: str = Field(..., description="BuiltInCategory name, used by gate L5")
    expected_count: int = Field(..., ge=0, description="elements this template creates per render")
    description: str | None = None

    def validate_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Validate `args` against this manifest. Raises on issue, returns args on success."""
        param_names = {p.name for p in self.parameters}

        # Reject extras
        for k in args:
            if k not in param_names:
                raise ManifestValidationError(f"unexpected parameter '{k}'")

        for p in self.parameters:
            present = p.name in args
            if not present:
                if p.required:
                    raise ManifestValidationError(f"missing required parameter '{p.name}'")
                continue
            v = args[p.name]
            self._check_type(p, v)
            self._check_range(p, v)
        return args

    @staticmethod
    def _check_type(p: ManifestParameter, v: Any) -> None:
        ok: bool
        if p.type == "string":
            ok = isinstance(v, str)
        elif p.type == "int":
            # bool is a subclass of int — explicitly reject
            ok = isinstance(v, int) and not isinstance(v, bool)
        elif p.type == "float":
            # int permitted (numeric tower)
            ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        elif p.type == "bool":
            ok = isinstance(v, bool)
        elif p.type == "list":
            ok = isinstance(v, list)
        else:
            ok = False
        if not ok:
            raise ManifestValidationError(
                f"type mismatch for '{p.name}': expected {p.type}, got {type(v).__name__}"
            )

    @staticmethod
    def _check_range(p: ManifestParameter, v: Any) -> None:
        if p.type not in ("int", "float"):
            return
        if p.min is not None and v < p.min:
            raise ManifestValidationError(
                f"value for '{p.name}' out of range: {v} < min={p.min}"
            )
        if p.max is not None and v > p.max:
            raise ManifestValidationError(
                f"value for '{p.name}' out of range: {v} > max={p.max}"
            )
