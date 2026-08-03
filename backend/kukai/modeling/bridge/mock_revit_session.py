"""MockRevitSession — passive recorder of Revit code execution (Round 1A).

Phase 3 originally shipped this as a *regex parser* that parsed C# placement
calls character-by-character (NewFamilyInstance, Transaction blocks, etc.).
That design was architecturally brittle: every persona contract tightening
(UnitUtils conversion, INV008 null-guard pre-resolution, namespace wrapping)
widened the gap between what the production StructuralSubagent emits and
what the mock could parse. The 2026-05-20 sandbox audit found all 12
production-style proposals failed with `"no NewFamilyInstance(...) match"`
even though Roslyn approved every one (see MANAGER_AUDIT.md Finding #1).

Round 1A pivot: the mock no longer parses C#. It is a passive *recorder*
that captures the call (code, hash, timestamp, task_brief if supplied) and
*synthesizes* a placed element from the task_brief's resolver-supplied
data (placement_point, family_symbol_id, level_id, category). Validation
of the C# itself is the job of upstream gates: invariants (L2.5), Roslyn
compile (L3), and — in Phase 5 — real Revit execution (L4). The mock's
job is to make L4 a trivial pass while still maintaining honest in-memory
session state that L5.5 + L6 can query.

What the mock still does:
  - Allocate deterministic element_ids (9000+)
  - Track placed elements + per-task id mapping (idempotent replay)
  - Extract `Mark` value via a tiny regex (defensible — single-token capture)
  - Synthesize property + geometry views via _SessionBackedModelQueryClient

What the mock no longer does:
  - Parse NewFamilyInstance / Transaction / XYZ literals
  - Validate symbol/level/category/structural_type cross-references
  - Reject placements for grid-bounds / unknown FamilySymbol id / etc.

For tests that need failure modes (duplicate Mark, missing family, unbound
level, mark-pairing mismatch), use the explicit error-injection knobs:
  - `set_next_failure(error_message)`
  - duplicate Mark is still rejected automatically (state-based check)
"""
from __future__ import annotations
import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Sequence

from kukai.modeling.bridge.model_query_client import (
    ElementGeometry, GridInfo, LevelInfo, ModelQueryClient,
)
from kukai.modeling.schemas.resolver import FamilySymbolCandidate
from kukai.modeling.schemas.tasks import TaskBrief


@dataclass
class PlacedElement:
    """One element the session believes is in the Revit document."""
    element_id: int
    category: str
    family_symbol_id: int
    level_id: int
    location_mm: tuple[float, float, float]
    parameters: dict[str, str] = field(default_factory=dict)
    placed_by_task_id: str | None = None


@dataclass(frozen=True)
class ExecutionRecord:
    """One execute_code(...) call captured by the passive recorder."""
    code: str
    code_len: int
    code_hash: str
    timestamp: float
    task_brief_task_id: str | None
    plan_task_id: str | None
    element_ids: tuple[int, ...]
    success: bool
    error: str | None


_DEFAULT_LEVELS: tuple[LevelInfo, ...] = (
    LevelInfo(level_id=1, name="L1", elevation_mm=0.0),
)
_DEFAULT_GRIDS: tuple[GridInfo, ...] = (
    GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
    GridInfo(grid_id=2, name="B", axis="horizontal", position_mm=6000.0),
    GridInfo(grid_id=3, name="1", axis="vertical", position_mm=0.0),
    GridInfo(grid_id=4, name="2", axis="vertical", position_mm=6000.0),
)


# Tiny single-token Mark extractor. Kept because it's defensible (one
# narrow string capture, not a full parse) and because L5.5 PropertyValidationGate
# and the duplicate-Mark detection both need the Mark value to do their jobs.
_RE_MARK_SET = re.compile(
    r'\.LookupParameter\s*\(\s*"Mark"\s*\)\s*\??\.\s*Set\s*\(\s*"(?P<mark>[^"]+)"\s*\)',
)


class MockRevitSession:
    """Passive recorder of Revit code execution.

    See module docstring for the architectural pivot rationale. Each
    `execute_code` call:
      1. Records the call (full code, hash, timestamp, task linkage).
      2. Allocates a fresh element_id.
      3. Synthesizes a PlacedElement from `task_brief` data (placement
         point, family_symbol_id, level_id, expected category).
      4. Extracts Mark from the code if present, else auto-generates one.
      5. Rejects with DuplicateMarkError when an existing element already
         holds that Mark (state-based check, no C# parsing).
      6. Returns {success, element_ids, duration_ms, error}.
    """

    def __init__(
        self,
        *,
        grids: Sequence[GridInfo] | None = None,
        levels: Sequence[LevelInfo] | None = None,
        families: Sequence[FamilySymbolCandidate] | None = None,
    ):
        # None → defaults; [] → deliberately empty (matches MockModelQueryClient convention)
        self._grids: list[GridInfo] = list(_DEFAULT_GRIDS) if grids is None else list(grids)
        self._levels: list[LevelInfo] = list(_DEFAULT_LEVELS) if levels is None else list(levels)
        self._families: list[FamilySymbolCandidate] = [] if families is None else list(families)
        self._placed: dict[int, PlacedElement] = {}
        self._next_element_id: int = 9000
        self._task_to_element_ids: dict[str, list[int]] = {}
        # Round 1A — passive-recorder additions.
        self._records: list[ExecutionRecord] = []
        # Forced-failure injection for tests that exercise failure paths.
        self._next_forced_failure: str | None = None
        # Runner-managed "current task" register so test harnesses can
        # supply brief data without changing the MockBridgeClient signature.
        self._current_task_brief: TaskBrief | None = None
        self._current_plan_task_id: str | None = None

    # ---- views ----

    @property
    def grids(self) -> list[GridInfo]: return list(self._grids)

    @property
    def levels(self) -> list[LevelInfo]: return list(self._levels)

    @property
    def families(self) -> list[FamilySymbolCandidate]: return list(self._families)

    def list_placed_elements(self) -> list[PlacedElement]:
        return [self._placed[eid] for eid in sorted(self._placed)]

    def get_element(self, element_id: int) -> PlacedElement | None:
        return self._placed.get(element_id)

    def execution_records(self) -> list[ExecutionRecord]:
        """All captured execute_code() calls, in order."""
        return list(self._records)

    # ---- runner-managed current task register ----

    def set_current_task(
        self,
        *,
        task_brief: TaskBrief | None = None,
        plan_task_id: str | None = None,
    ) -> None:
        """Register brief + plan_task_id for the next execute_code call.

        The runner / harness sets this before each Foreman.dispatch_task,
        so the bridge client passes through unchanged (matches the real
        WebSocketBridgeClient signature) while the session still receives
        the data it needs to synthesize placements.
        """
        self._current_task_brief = task_brief
        self._current_plan_task_id = plan_task_id

    def clear_current_task(self) -> None:
        self._current_task_brief = None
        self._current_plan_task_id = None

    # ---- failure injection ----

    def set_next_failure(self, error_message: str) -> None:
        """The next execute_code() call returns success=False with this error."""
        self._next_forced_failure = error_message

    # ---- internals ----

    def _allocate_element_id(self) -> int:
        eid = self._next_element_id
        self._next_element_id += 1
        return eid

    def _store(self, element: PlacedElement) -> None:
        self._placed[element.element_id] = element
        if element.placed_by_task_id is not None:
            self._task_to_element_ids.setdefault(
                element.placed_by_task_id, []).append(element.element_id)

    # ---- execute_code ----

    def execute_code(
        self,
        csharp_code: str,
        expected_count: int = 1,
        *,
        task_brief: TaskBrief | None = None,
        plan_task_id: str | None = None,
    ) -> dict:
        """Record the call and synthesize placements from task_brief data.

        Shape matches MockBridgeClient.execute_code:
            {success, element_ids, duration_ms, error}

        Arguments:
          csharp_code: the production C# (NOT parsed — just recorded + hashed)
          expected_count: how many elements the brief expects (used as the
            number of synthetic placements when the brief's
            expected_elements.count agrees, else clamps to expected_count)
          task_brief: optional override for the runner-managed current brief
          plan_task_id: optional override for the runner-managed current id
        """
        # Resolve the brief: explicit kwarg wins, else use the register.
        brief = task_brief if task_brief is not None else self._current_task_brief
        pt_id = plan_task_id if plan_task_id is not None else self._current_plan_task_id

        # Forced-failure injection (for tests that need a failure mode).
        if self._next_forced_failure is not None:
            err = self._next_forced_failure
            self._next_forced_failure = None
            self._records.append(self._make_record(
                csharp_code, brief, pt_id, element_ids=(), success=False, error=err))
            return _failure(err)

        # Determine placement count. Without a brief, fall back to expected_count.
        if brief is not None:
            placement_count = max(brief.expected_elements.count, 1)
        else:
            placement_count = max(expected_count, 1)

        # Pull synthesis data from the brief. Without one we synthesize
        # generic placeholders — keeps the legacy "any C# succeeds" smoke
        # tests green even when no brief flows in.
        if brief is not None:
            category = brief.expected_elements.category
            family_symbol_id = brief.family_symbol_id
            level_id = brief.level_id
            base_xyz = (
                brief.placement_point.x,
                brief.placement_point.y,
                brief.placement_point.z,
            )
            task_uuid = brief.task_id
        else:
            category = "OST_StructuralColumns"
            family_symbol_id = -1
            level_id = -1
            base_xyz = (0.0, 0.0, 0.0)
            task_uuid = None

        # Extract Mark values from the code (defensible single-token regex).
        marks_in_code = [m["mark"] for m in _RE_MARK_SET.finditer(csharp_code)]

        # Reject duplicates against existing session state.
        existing_marks = {
            el.parameters.get("Mark")
            for el in self._placed.values()
            if "Mark" in el.parameters
        }
        for mk in marks_in_code:
            if mk in existing_marks:
                err = f"DuplicateMarkError: Mark={mk!r} already exists in session"
                self._records.append(self._make_record(
                    csharp_code, brief, pt_id, element_ids=(), success=False, error=err))
                return _failure(err)
            # Same Mark twice in one code block.
            if marks_in_code.count(mk) > 1:
                err = f"DuplicateMarkError: Mark={mk!r} appears more than once in code"
                self._records.append(self._make_record(
                    csharp_code, brief, pt_id, element_ids=(), success=False, error=err))
                return _failure(err)

        # Synthesize element_ids and PlacedElement(s).
        new_ids: list[int] = []
        for i in range(placement_count):
            element_id = self._allocate_element_id()
            # Use the brief's placement_point for element i==0; for additional
            # synthetic elements (rare), offset by 1mm so distinct-location
            # invariants in tests don't collapse.
            if i == 0:
                xyz = base_xyz
            else:
                xyz = (base_xyz[0] + i, base_xyz[1], base_xyz[2])
            parameters: dict[str, str] = {}
            if i < len(marks_in_code):
                parameters["Mark"] = marks_in_code[i]
            else:
                parameters["Mark"] = f"AUTO-{element_id}"
            self._store(PlacedElement(
                element_id=element_id, category=category,
                family_symbol_id=family_symbol_id, level_id=level_id,
                location_mm=xyz, parameters=parameters,
                placed_by_task_id=task_uuid,
            ))
            new_ids.append(element_id)

        self._records.append(self._make_record(
            csharp_code, brief, pt_id,
            element_ids=tuple(new_ids), success=True, error=None,
        ))
        return {"success": True, "element_ids": new_ids,
                "duration_ms": 1, "error": None}

    def execute_code_for_task(
        self, csharp_code: str, *, task_id: str, expected_count: int = 1,
        task_brief: TaskBrief | None = None, plan_task_id: str | None = None,
    ) -> dict:
        """Idempotent per task_id: second call returns prior IDs without re-placing."""
        prior = self._task_to_element_ids.get(task_id)
        if prior is not None:
            return {"success": True, "element_ids": list(prior),
                    "duration_ms": 0, "error": None}
        result = self.execute_code(
            csharp_code, expected_count=expected_count,
            task_brief=task_brief, plan_task_id=plan_task_id,
        )
        if result["success"]:
            for eid in result["element_ids"]:
                el = self._placed[eid]
                # Tag the placed-by-task_id field so future calls find them.
                self._placed[eid] = PlacedElement(
                    element_id=el.element_id, category=el.category,
                    family_symbol_id=el.family_symbol_id, level_id=el.level_id,
                    location_mm=el.location_mm, parameters=el.parameters,
                    placed_by_task_id=task_id,
                )
                self._task_to_element_ids.setdefault(task_id, []).append(eid)
        return result

    def _make_record(
        self,
        code: str,
        brief: TaskBrief | None,
        plan_task_id: str | None,
        *,
        element_ids: tuple[int, ...],
        success: bool,
        error: str | None,
    ) -> ExecutionRecord:
        return ExecutionRecord(
            code=code,
            code_len=len(code),
            code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest()[:16],
            timestamp=time.time(),
            task_brief_task_id=brief.task_id if brief is not None else None,
            plan_task_id=plan_task_id,
            element_ids=element_ids,
            success=success,
            error=error,
        )

    def reset(self) -> None:
        """Clear placed elements + records but keep grids/levels/families."""
        self._placed.clear()
        self._task_to_element_ids.clear()
        self._records.clear()
        self._next_element_id = 9000
        self._next_forced_failure = None
        self._current_task_brief = None
        self._current_plan_task_id = None

    def get_query_client(self) -> ModelQueryClient:
        return _SessionBackedModelQueryClient(self)


class _SessionBackedModelQueryClient:
    """Thin adapter that satisfies the `ModelQueryClient` Protocol."""

    def __init__(self, session: "MockRevitSession"):
        self._session = session
        self.calls: list[str] = []

    async def query_families(self, category: str | None = None):
        self.calls.append(f"query_families(category={category!r})")
        if category is None:
            return list(self._session.families)
        return [f for f in self._session.families if f.category == category]

    async def query_levels(self):
        self.calls.append("query_levels()")
        return list(self._session.levels)

    async def query_grids(self):
        self.calls.append("query_grids()")
        return list(self._session.grids)

    async def query_parameter_info(self, family_symbol_id: int):
        self.calls.append(f"query_parameter_info({family_symbol_id})")
        return {}

    async def query_element_properties(self, element_id: int) -> dict[str, str]:
        """Synthesize element properties from PlacedElement data.

        Returns Level *name* (resolved via session._levels) so L5.5 gates
        comparing against brief.expected_elements.level_name (a NAME like
        "Level 1", not the numeric level_id) match without coercion.
        """
        self.calls.append(f"query_element_properties({element_id})")
        placed = self._session._placed.get(element_id)
        if placed is None:
            raise ValueError(f"element_id {element_id} not in session")
        # Resolve level_id → level_name for L5.5 gate compatibility.
        level_name = next(
            (l.name for l in self._session.levels if l.level_id == placed.level_id),
            str(placed.level_id),
        )
        props: dict[str, str] = {
            "Level": level_name,
            "FamilySymbolId": str(placed.family_symbol_id),
        }
        # Custom parameters (e.g. Mark="C-01") supersede the synthesized ones.
        props.update(placed.parameters)
        return props

    async def query_element_geometry(self, element_id: int) -> ElementGeometry:
        """Synthesize a tight bbox around PlacedElement.location_mm.

        Real Revit returns the element's geometric extent; the session only
        knows the placement point, so we emit a 1mm cube centered on that
        point. Sufficient for L6 GeometryGate coord_deviation checks; collision
        checks against synthetic bboxes are intentionally permissive (1mm
        cubes never collide unless coincident).
        """
        self.calls.append(f"query_element_geometry({element_id})")
        placed = self._session._placed.get(element_id)
        if placed is None:
            raise ValueError(f"element_id {element_id} not in session")
        x, y, z = placed.location_mm
        eps = 0.5  # ±0.5mm = 1mm cube
        return ElementGeometry(
            element_id=element_id,
            bounding_box_min_mm=(x - eps, y - eps, z - eps),
            bounding_box_max_mm=(x + eps, y + eps, z + eps),
            centroid_mm=(x, y, z),
            host_element_id=None,
            level_id=placed.level_id,
        )


def _failure(message: str) -> dict:
    return {"success": False, "element_ids": [], "duration_ms": 1, "error": message}
