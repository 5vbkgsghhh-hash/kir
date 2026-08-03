"""Declarative ``create_element`` — the 8th operation on ``apply_revit_write``.

Closes the Cora gap (project-document element creation had NO declarative tool;
creation = model-written raw C# that the Evaluator can only call
``unverifiable``). Design of record: /root/kukai-fable-create-element-2026-07-04.md.

Server-side lowering, five stages:

    1. GROUND   — resolve level/type references against the live model via ONE
                  templated read-only collector round-trip; AMBIGUOUS/NOT_FOUND
                  → structured refusal with candidates. *No ungrounded C# is
                  ever emitted.*
    2. RENDER   — server-owned verified Jinja2 template (TemplateRegistry +
                  manifest arg validation, mm units, null-guards, rollback-on-
                  catch, inverse family-doc guard).
    3. STAMP    — correlation ``op_id`` written to ALL_MODEL_INSTANCE_COMMENTS
                  inside the same transaction (timeout-safe idempotency key).
    4. EXECUTE  — the existing transport: ``RevitExecutionPipeline
                  .run_declarative`` under KUKAI_EXEC_PIPELINE=1, else the bare
                  ``bridge_callback("execute", …)`` shot (legacy parity with
                  the other 7 apply_revit_write ops). No new bridge op.
    5. WITNESS  — post-commit read-back (in-template) + independent
                  ``probe_element_present`` round-trip + deterministic
                  ``kukai.will.evaluator`` verdict attached as a compact
                  ``witness`` block. A create becomes WITNESSED, not asserted.

Flag: ``KUKAI_CREATE_ELEMENT`` (env, read at call time — the KUKAI_EXEC_PIPELINE
convention). Default OFF ⇒ the op is absent from the tool schema entirely and
the handler falls through to the legacy unknown-operation branch: flag-off
turns are byte-identical.

v1 element types: level, grid, wall, floor, family_instance (point-placed),
plus ``dry_run``. The LIVE create path must be operator-validated on the
authorized device a6d7… before the flag is ever turned on in prod — nothing in
this module can be exercised against Revit from an unauthorized session.
"""

from __future__ import annotations

import logging
import math
import pathlib
import os
import re
import uuid
from typing import Any, Awaitable, Callable, Optional

from kukai.will.evaluator import Check, _as_int, evaluate_structural
from kukai.write.operations import _escape_csharp_string

logger = logging.getLogger(__name__)

BridgeCallback = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

# ─────────────────────────────────────────────────────────────────────────────
# Flag + constants
# ─────────────────────────────────────────────────────────────────────────────

CREATE_ELEMENT_FLAG = "KUKAI_CREATE_ELEMENT"

ELEMENT_TYPES = ("level", "grid", "wall", "floor", "family_instance")

STATUS_RESOLVED = "resolved"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_NOT_FOUND = "not_found"

# Derived server-side, never model-supplied (§2.2: the model cannot weaken its
# own postcondition). family_instance category comes from the RESOLVED symbol.
_STATIC_CATEGORY: dict[str, Optional[str]] = {
    "level": "OST_Levels",
    "grid": "OST_Grids",
    "wall": "OST_Walls",
    "floor": "OST_Floors",
    "family_instance": None,
}

_TEMPLATE_BY_TYPE = {
    "level": "create_level",
    "grid": "create_grid",
    "wall": "create_wall",
    "floor": "create_floor",
    "family_instance": "create_family_instance",
}

_OST_RE = re.compile(r"^OST_[A-Za-z0-9_]{1,64}$")

_GROUNDING_TIMEOUT_MS = 30_000
_CREATE_TIMEOUT_MS = 60_000
_CREATE_TIMEOUT_MS_FLOOR = 120_000

_LEVEL_ELEV_TOL_MM = 10.0
_LOCATION_TOL_MM = 10.0
_BBOX_TOL_MM = 50.0
_DIM_TOL_MM = 1.0
_MIN_SEGMENT_MM = 10.0
_MAX_PARAMS = 10
_MAX_CANDIDATES = 20
_MAX_POOL_CS = 100  # C#-side candidate cap per grounding read


def create_element_enabled() -> bool:
    """KUKAI_CREATE_ELEMENT=1 turns the op on (env read at call time —
    the KUKAI_EXEC_PIPELINE convention; deliberately not via kukai.config)."""
    return os.environ.get(CREATE_ELEMENT_FLAG, "0") == "1"


class CreateSpecError(ValueError):
    """A structurally invalid element spec (missing/nonsense geometry etc.)."""


# ─────────────────────────────────────────────────────────────────────────────
# Tool schema (single source of truth; kukai/llm/tools.py injects when flag ON)
# ─────────────────────────────────────────────────────────────────────────────

_DESCRIPTION_ADDENDUM = (
    " create_element: создать элемент модели (level/grid/wall/floor/"
    "family_instance) ДЕКЛАРАТИВНО — бэкенд сам заземляет уровень/тип по живой "
    "модели, исполняет проверенный шаблон и возвращает witness (read-back "
    "подтверждение). НАДЁЖНЕЕ execute_revit_code для создания. Если точный "
    "тип/уровень неизвестен — передай подсказки (name_contains и т.п.): бэкенд "
    "либо разрешит их, либо вернёт список кандидатов — НИКОГДА не выдумывай id."
)


def element_schema_property() -> dict[str, Any]:
    """The nested ``element`` request schema (design §2.2). Units: mm."""
    return {
        "type": "object",
        "description": (
            "Спецификация для operation=create_element. Бэкенд заземляет "
            "каждую ссылку (уровень, тип) по живой модели — не выдумывай id, "
            "которых не видел. Все единицы — миллиметры."
        ),
        "properties": {
            "element_type": {
                "type": "string",
                "enum": ["level", "grid", "wall", "floor", "family_instance"],
                "description": (
                    "Что создать. family_instance = любое точечное загружаемое "
                    "семейство (колонна, мебель, оборудование, обобщённая модель)."
                ),
            },
            "level": {
                "type": "object",
                "description": "Базовый уровень (id > name > elevation_mm).",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string",
                             "description": "Имя уровня как в модели, напр. 'Уровень 1'"},
                    "elevation_mm": {"type": "number",
                                     "description": "Fallback: ближайший уровень по отметке"},
                },
            },
            "type": {
                "type": "object",
                "description": (
                    "Тип/семейство (FamilySymbol / WallType / FloorType). "
                    "id — если уже известен из query_model/get_model_details; "
                    "иначе подсказки — бэкенд разрешит или вернёт кандидатов."
                ),
                "properties": {
                    "id": {"type": "integer"},
                    "name_contains": {"type": "array", "items": {"type": "string"}},
                    "family_contains": {"type": "array", "items": {"type": "string"}},
                    "dimensions_mm": {
                        "type": "object",
                        "description": "напр. {\"width\": 200} — точное совпадение ±1мм (стены)",
                    },
                },
            },
            "geometry": {
                "type": "object",
                "description": "РОВНО одно из point | line | profile (по element_type).",
                "properties": {
                    "point": {
                        "type": "object",
                        "description": "family_instance: точка вставки (z_mm по умолчанию = отметка уровня)",
                        "properties": {
                            "x_mm": {"type": "number"}, "y_mm": {"type": "number"},
                            "z_mm": {"type": "number"},
                            "rotation_deg": {"type": "number"},
                        },
                    },
                    "line": {
                        "type": "object",
                        "description": "wall/grid: отрезок в плане на уровне",
                        "properties": {
                            "start": {"type": "object",
                                      "properties": {"x_mm": {"type": "number"},
                                                     "y_mm": {"type": "number"}}},
                            "end": {"type": "object",
                                    "properties": {"x_mm": {"type": "number"},
                                                   "y_mm": {"type": "number"}}},
                        },
                    },
                    "profile": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                        "description": "floor: замкнутый полигон [[x_mm,y_mm],...] (≥3 точек)",
                    },
                },
            },
            "elevation_mm": {
                "type": "number",
                "description": "level only: отметка создаваемого уровня",
            },
            "name": {
                "type": "string",
                "description": "level/grid only: имя создаваемого элемента",
            },
            "params": {
                "type": "object",
                "description": (
                    "Параметры экземпляра после создания, напр. {\"Марка\": \"К-1\"}. "
                    "Каждый перечитывается и отчитывается verified/failed."
                ),
                "additionalProperties": {"type": ["string", "number"]},
            },
            "wall_height_mm": {
                "type": "number",
                "description": "wall only; по умолчанию — до следующего уровня выше",
            },
            "top_level": {
                "type": "object",
                "description": "wall: верхняя привязка (та же форма, что level)",
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "Разрешить ссылки + отрендерить план БЕЗ исполнения. Используй "
                    "для предпросмотра или при низкой уверенности в grounding."
                ),
            },
        },
        "required": ["element_type"],
    }


def inject_create_element_schema(tools: list[dict[str, Any]]) -> bool:
    """Mutate the per-call tool list: add the op + ``element`` property to
    apply_revit_write. Idempotent. Returns True when the tool was found."""
    for t in tools:
        fn = t.get("function") if isinstance(t, dict) else None
        if not isinstance(fn, dict) or fn.get("name") != "apply_revit_write":
            continue
        params = fn.setdefault("parameters", {})
        props = params.setdefault("properties", {})
        enum = props.get("operation", {}).get("enum")
        if isinstance(enum, list) and "create_element" not in enum:
            enum.append("create_element")
        if "element" not in props:
            props["element"] = element_schema_property()
        desc = fn.get("description") or ""
        if "create_element" not in desc:
            fn["description"] = desc + _DESCRIPTION_ADDENDUM
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers (pure, total)
# ─────────────────────────────────────────────────────────────────────────────

def _as_float(value: Any) -> Optional[float]:
    """Total float coercion: None/bool/non-numeric/non-finite → None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _unwrap(raw: Any, *keys: str) -> dict[str, Any]:
    """Bridge results usually ARE the C# dict; tolerate a {'result': {...}}
    envelope by unwrapping when the marker key lives one level down."""
    if not isinstance(raw, dict):
        return {}
    if any(k in raw for k in keys):
        return raw
    inner = raw.get("result")
    if isinstance(inner, dict) and any(k in inner for k in keys):
        return inner
    return raw


def _new_op_id() -> str:
    """Correlation stamp ``kukai:{turn_query_id}:{suffix}`` (§2.6)."""
    qid = None
    try:
        from kukai.rag import retrieval_health
        h = retrieval_health.current()
        qid = h.query_id if h is not None else None
    except Exception:  # noqa: BLE001 — ambient turn context is best-effort
        qid = None
    return f"kukai:{qid or 'noq'}:{uuid.uuid4().hex[:8]}"


def _invalid(message: str) -> dict[str, Any]:
    return {"error": True, "op": "create_element", "stage": "spec", "message": message}


def _refusal(which: str, r: dict[str, Any]) -> dict[str, Any]:
    """Grounding refusal (§2.3 stage 1): candidates instead of guessed C#."""
    return {
        "error": True,
        "op": "create_element",
        "stage": "grounding",
        "which": which,
        "status": r.get("status"),
        "candidates": r.get("candidates", []),
        "message": r.get("message", ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — grounding: read builder + pure resolvers (resolve or refuse)
# ─────────────────────────────────────────────────────────────────────────────

def build_grounding_code(
    element_type: str,
    type_spec: Optional[dict[str, Any]],
    category_token: Optional[str] = None,
) -> str:
    """ONE read-only C# collector: all levels + the type pool for the element
    type (WallType / FloorType / FamilySymbol). Needle prefilter + hard cap
    bound the payload; Python resolvers make the verdict. Version-safe id
    extraction (Id.ToString() — no .IntegerValue/.Value)."""
    spec = type_spec if isinstance(type_spec, dict) else {}
    needles: list[str] = []
    for key in ("name_contains", "family_contains"):
        v = spec.get(key)
        if isinstance(v, str):
            v = [v]
        if isinstance(v, (list, tuple)):
            needles += [str(x).strip().lower() for x in v if str(x).strip()]
    needles_cs = ", ".join(f'"{_escape_csharp_string(n)}"' for n in needles[:8])
    needles_decl = (
        f"var __needles = new string[] {{ {needles_cs} }};"
        if needles_cs else "var __needles = new string[0];"
    )

    lines: list[str] = []
    lines.append("var __res = new Dictionary<string, object>();")
    lines.append("var __levels = new List<Dictionary<string, object>>();")
    lines.append("try")
    lines.append("{")
    lines.append("    foreach (Level __l in new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().OrderBy(__x => __x.Elevation))")
    lines.append("    {")
    lines.append("        var __d = new Dictionary<string, object>();")
    lines.append('        try { __d["id"] = long.Parse(__l.Id.ToString()); } catch { continue; }')
    lines.append('        try { __d["name"] = __l.Name ?? ""; } catch { __d["name"] = ""; }')
    lines.append('        try { __d["elevation_mm"] = Math.Round(UnitUtils.ConvertFromInternalUnits(__l.Elevation, UnitTypeId.Millimeters), 1); } catch { }')
    lines.append("        __levels.Add(__d);")
    lines.append("    }")
    lines.append("}")
    lines.append("catch { }")
    lines.append('__res["levels"] = __levels;')
    lines.append(needles_decl)
    lines.append("var __types = new List<Dictionary<string, object>>();")
    lines.append("int __total = 0;")

    if element_type == "wall":
        collector = "new FilteredElementCollector(doc).OfClass(typeof(WallType)).Cast<WallType>()"
        loop_var, static_cat = "WallType __ty", '"OST_Walls"'
    elif element_type == "floor":
        collector = "new FilteredElementCollector(doc).OfClass(typeof(FloorType)).Cast<FloorType>()"
        loop_var, static_cat = "FloorType __ty", '"OST_Floors"'
    else:  # family_instance
        cat_filter = ""
        if category_token and _OST_RE.match(category_token):
            cat_filter = f".OfCategory(BuiltInCategory.{category_token})"
        collector = (
            "new FilteredElementCollector(doc)"
            f"{cat_filter}.OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>()"
        )
        loop_var, static_cat = "FamilySymbol __ty", "null"

    lines.append("try")
    lines.append("{")
    lines.append(f"    foreach ({loop_var} in {collector})")
    lines.append("    {")
    lines.append("        __total++;")
    lines.append('        string __nm = ""; try { __nm = __ty.Name ?? ""; } catch { }')
    lines.append('        string __fam = ""; try { __fam = __ty.FamilyName ?? ""; } catch { }')
    lines.append('        var __hay = (__nm + " " + __fam).ToLowerInvariant();')
    lines.append("        bool __match = true;")
    lines.append("        foreach (var __nd in __needles) { if (!__hay.Contains(__nd)) { __match = false; break; } }")
    lines.append(f"        if (!__match || __types.Count >= {_MAX_POOL_CS}) continue;")
    lines.append("        var __d = new Dictionary<string, object>();")
    lines.append('        try { __d["id"] = long.Parse(__ty.Id.ToString()); } catch { continue; }')
    lines.append('        __d["name"] = __nm;')
    lines.append('        __d["family"] = __fam;')
    if static_cat == "null":
        lines.append('        try { __d["category"] = (__ty.Category != null) ? __ty.Category.BuiltInCategory.ToString() : ""; } catch { __d["category"] = ""; }')
    else:
        lines.append(f'        __d["category"] = {static_cat};')
    if element_type == "wall":
        lines.append('        try { __d["kind"] = __ty.Kind.ToString(); } catch { }')
        lines.append('        try { __d["width_mm"] = Math.Round(UnitUtils.ConvertFromInternalUnits(__ty.Width, UnitTypeId.Millimeters), 1); } catch { }')
    lines.append("        __types.Add(__d);")
    lines.append("    }")
    lines.append("}")
    lines.append("catch { }")
    lines.append('__res["types"] = __types;')
    lines.append('__res["types_total"] = __total;')
    lines.append(f'__res["types_truncated"] = __types.Count >= {_MAX_POOL_CS};')
    lines.append("return __res;")
    return "\n".join(lines)


def resolve_level(spec: Optional[dict[str, Any]], levels: list[dict[str, Any]]) -> dict[str, Any]:
    """Level grounding verdict: id > exact name > unique substring >
    nearest-elevation-within-tolerance; else refuse with the ACTUAL level list."""
    pool = [l for l in levels if isinstance(l, dict)]

    def _ok(level: dict) -> dict[str, Any]:
        return {"status": STATUS_RESOLVED, "level": level, "candidates": [level], "message": ""}

    def _amb(cands: list[dict], note: str) -> dict[str, Any]:
        return {"status": STATUS_AMBIGUOUS, "level": None,
                "candidates": cands[:_MAX_CANDIDATES], "message": note}

    def _nf(note: str) -> dict[str, Any]:
        return {"status": STATUS_NOT_FOUND, "level": None,
                "candidates": pool[:_MAX_CANDIDATES], "message": note}

    if not pool:
        return _nf("в модели нет уровней")
    spec = spec if isinstance(spec, dict) else {}

    lid = _as_int(spec.get("id"))
    if lid is not None:
        for l in pool:
            if _as_int(l.get("id")) == lid:
                return _ok(l)
        return _nf(f"уровень id={lid} не найден в модели")

    name = spec.get("name")
    if isinstance(name, str) and name.strip():
        needle = name.strip().casefold()
        exact = [l for l in pool if str(l.get("name", "")).strip().casefold() == needle]
        if len(exact) == 1:
            return _ok(exact[0])
        if len(exact) > 1:
            return _amb(exact, f"несколько уровней с именем '{name}'")
        sub = [l for l in pool if needle in str(l.get("name", "")).casefold()]
        if len(sub) == 1:
            return _ok(sub[0])
        if len(sub) > 1:
            return _amb(sub, f"'{name}' совпадает с {len(sub)} уровнями — уточни")
        if _as_float(spec.get("elevation_mm")) is None:
            names = ", ".join(str(l.get("name", "?")) for l in pool[:10])
            return _nf(f"уровень '{name}' не найден; в модели: {names}")

    elev = _as_float(spec.get("elevation_mm"))
    if elev is not None:
        def _dist(l: dict) -> float:
            e = _as_float(l.get("elevation_mm"))
            return abs(e - elev) if e is not None else float("inf")
        best = min(pool, key=_dist)
        if _dist(best) <= _LEVEL_ELEV_TOL_MM:
            return _ok(best)
        return _nf(
            f"нет уровня на отметке {elev}мм (±{_LEVEL_ELEV_TOL_MM:g}мм); "
            f"ближайший: '{best.get('name')}' на {best.get('elevation_mm')}мм"
        )

    if len(pool) == 1:
        return _ok(pool[0])
    return _amb(pool, "укажи уровень: id, name или elevation_mm")


def _dims_match(entry: dict[str, Any], desired: dict[str, Any]) -> bool:
    dims: dict[str, Any] = {}
    if entry.get("width_mm") is not None:
        dims["width"] = entry["width_mm"]
    extra = entry.get("dimensions_mm")
    if isinstance(extra, dict):
        dims.update(extra)
    for k, v in desired.items():
        a = _as_float(dims.get(k))
        want = _as_float(v)
        if a is None or want is None or abs(a - want) > _DIM_TOL_MM:
            return False
    return True


def resolve_type(
    spec: Optional[dict[str, Any]],
    pool: list[dict[str, Any]],
    element_type: str,
) -> dict[str, Any]:
    """Type grounding verdict — the FamilyResolver logic (category pool →
    name/family/dims filters → RESOLVED iff exactly 1) ported onto the chat
    bridge pool. AMBIGUOUS/NOT_FOUND carry candidates for the model to pick."""
    cand = [t for t in pool if isinstance(t, dict)]

    def _ok(t: dict) -> dict[str, Any]:
        return {"status": STATUS_RESOLVED, "type": t, "candidates": [t], "message": ""}

    def _amb(cands: list[dict], note: str) -> dict[str, Any]:
        return {"status": STATUS_AMBIGUOUS, "type": None,
                "candidates": cands[:_MAX_CANDIDATES], "message": note}

    def _nf(note: str) -> dict[str, Any]:
        return {"status": STATUS_NOT_FOUND, "type": None,
                "candidates": cand[:_MAX_CANDIDATES], "message": note}

    if not cand:
        return _nf(f"в модели нет подходящих типов для {element_type}")
    spec = spec if isinstance(spec, dict) else {}

    tid = _as_int(spec.get("id"))
    if tid is not None:
        for t in cand:
            if _as_int(t.get("id")) == tid:
                return _ok(t)
        return _nf(f"тип id={tid} не найден в модели — не выдумывай id")

    filtered = list(cand)
    for key in ("name_contains", "family_contains"):
        v = spec.get(key)
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, (list, tuple)):
            continue
        for raw_needle in v:
            needle = str(raw_needle).strip().casefold()
            if not needle:
                continue
            if key == "family_contains":
                filtered = [t for t in filtered
                            if needle in str(t.get("family", "")).casefold()]
            else:
                filtered = [t for t in filtered
                            if needle in str(t.get("name", "")).casefold()
                            or needle in str(t.get("family", "")).casefold()]

    dims = spec.get("dimensions_mm")
    if isinstance(dims, dict) and dims:
        filtered = [t for t in filtered if _dims_match(t, dims)]

    has_hints = bool(
        (isinstance(spec.get("name_contains"), (list, tuple, str)) and spec.get("name_contains"))
        or (isinstance(spec.get("family_contains"), (list, tuple, str)) and spec.get("family_contains"))
        or (isinstance(dims, dict) and dims)
    )
    if len(filtered) == 1:
        return _ok(filtered[0])
    if len(filtered) > 1:
        note = (f"{len(filtered)} типов подходит — выбери id из candidates"
                if has_hints else "укажи тип: id или name_contains/family_contains")
        return _amb(filtered, note)
    return _nf("ни один тип не подходит под подсказки; см. candidates")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — render (verified templates via TemplateRegistry + manifests)
# ─────────────────────────────────────────────────────────────────────────────

_TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent / "templates"
_registry_singleton: Any = None


def _registry() -> Any:
    global _registry_singleton
    if _registry_singleton is None:
        from kukai.modeling.templated.registry import TemplateRegistry
        _registry_singleton = TemplateRegistry(_TEMPLATES_DIR)
    return _registry_singleton


# Args that land inside C# string literals — escaped HERE (single place), so
# no caller can forget. params_*_cs are pre-built quoted-literal fragments
# (escaped element-wise in _params_cs) and are deliberately NOT in this set.
_ESCAPED_STRING_ARGS = frozenset({"name", "op_id", "transaction_name"})


def render_create_code(element_type: str, template_args: dict[str, Any]) -> str:
    """Render the verified template for the element type (manifest-validated).
    String-literal args are C#-escaped here — injection-safe by construction."""
    name = _TEMPLATE_BY_TYPE.get(element_type)
    if name is None:
        raise CreateSpecError(f"element_type '{element_type}' не поддерживается")
    args = dict(template_args)
    for key in _ESCAPED_STRING_ARGS & set(args):
        args[key] = _escape_csharp_string(str(args[key]))
    return _registry().render(name, args)


def derive_wall_height_mm(
    element: dict[str, Any],
    base_level: dict[str, Any],
    levels: list[dict[str, Any]],
    top_level: Optional[dict[str, Any]],
) -> float:
    """Explicit wall_height_mm > top_level delta > next-level-above delta >
    3000mm default. Deterministic, from grounding data only."""
    explicit = _as_float(element.get("wall_height_mm"))
    if explicit is not None and explicit > 0:
        return float(explicit)
    base_e = _as_float(base_level.get("elevation_mm")) or 0.0
    if top_level is not None:
        top_e = _as_float(top_level.get("elevation_mm"))
        if top_e is not None and top_e > base_e:
            return float(top_e - base_e)
    above = [
        e for e in (
            _as_float(l.get("elevation_mm")) for l in levels if isinstance(l, dict)
        )
        if e is not None and e > base_e + 1.0
    ]
    if above:
        return float(min(above) - base_e)
    return 3000.0


def _finite(value: Any, what: str) -> float:
    f = _as_float(value)
    if f is None:
        raise CreateSpecError(f"{what}: нужно конечное число, получено {value!r}")
    return f


def _pt2(obj: Any, what: str) -> tuple[float, float]:
    if not isinstance(obj, dict):
        raise CreateSpecError(f"{what}: укажи {{x_mm, y_mm}}")
    return _finite(obj.get("x_mm"), f"{what}.x_mm"), _finite(obj.get("y_mm"), f"{what}.y_mm")


def _params_cs(element: dict[str, Any]) -> tuple[str, str]:
    params = element.get("params")
    if not isinstance(params, dict) or not params:
        return "", ""
    if len(params) > _MAX_PARAMS:
        raise CreateSpecError(f"слишком много params (макс {_MAX_PARAMS})")
    names, vals = [], []
    for k, v in params.items():
        names.append(f'"{_escape_csharp_string(str(k))}"')
        vals.append(f'"{_escape_csharp_string(str(v))}"')
    return ", ".join(names), ", ".join(vals)


def _build_template_args(
    element_type: str,
    element: dict[str, Any],
    level: Optional[dict[str, Any]],
    ltype: Optional[dict[str, Any]],
    levels: list[dict[str, Any]],
    op_id: str,
) -> dict[str, Any]:
    """Element spec + grounding → validated, injection-safe template args.
    Raises CreateSpecError on structurally invalid specs (refuse, never guess)."""
    names_cs, vals_cs = _params_cs(element)
    common = {
        "transaction_name": f"KUKI: создание {element_type}",
        "op_id": op_id,  # C#-escaped by render_create_code
        "params_names_cs": names_cs,
        "params_vals_cs": vals_cs,
    }
    geometry = element.get("geometry") if isinstance(element.get("geometry"), dict) else {}

    if element_type == "level":
        elev = _as_float(element.get("elevation_mm"))
        if elev is None:
            p = geometry.get("point")
            if isinstance(p, dict):
                elev = _as_float(p.get("z_mm"))
        if elev is None:
            raise CreateSpecError("для level укажи elevation_mm")
        return {**common, "elevation_mm": float(elev),
                "name": str(element.get("name") or "")}

    if element_type == "grid":
        line = geometry.get("line")
        if not isinstance(line, dict):
            raise CreateSpecError("для grid укажи geometry.line {start, end}")
        sx, sy = _pt2(line.get("start"), "line.start")
        ex, ey = _pt2(line.get("end"), "line.end")
        if math.hypot(ex - sx, ey - sy) < _MIN_SEGMENT_MM:
            raise CreateSpecError(f"отрезок оси короче {_MIN_SEGMENT_MM:g}мм")
        return {**common, "start_x_mm": sx, "start_y_mm": sy,
                "end_x_mm": ex, "end_y_mm": ey,
                "name": str(element.get("name") or "")}

    if element_type == "wall":
        assert level is not None and ltype is not None
        line = geometry.get("line")
        if not isinstance(line, dict):
            raise CreateSpecError("для wall укажи geometry.line {start, end}")
        sx, sy = _pt2(line.get("start"), "line.start")
        ex, ey = _pt2(line.get("end"), "line.end")
        if math.hypot(ex - sx, ey - sy) < _MIN_SEGMENT_MM:
            raise CreateSpecError(f"отрезок стены короче {_MIN_SEGMENT_MM:g}мм")
        top = element.get("top_level")
        top_resolved: Optional[dict[str, Any]] = None
        if isinstance(top, dict) and top:
            tr = resolve_level(top, levels)
            if tr["status"] != STATUS_RESOLVED:
                raise CreateSpecError(
                    f"top_level не разрешён ({tr['status']}): {tr.get('message', '')}")
            top_resolved = tr["level"]
        height = derive_wall_height_mm(element, level, levels, top_resolved)
        if not (0 < height <= 300_000):
            raise CreateSpecError(f"высота стены {height}мм вне допуска")
        return {**common,
                "wall_type_id": int(ltype["id"]), "level_id": int(level["id"]),
                "start_x_mm": sx, "start_y_mm": sy, "end_x_mm": ex, "end_y_mm": ey,
                "base_z_mm": float(_as_float(level.get("elevation_mm")) or 0.0),
                "height_mm": float(height)}

    if element_type == "floor":
        assert level is not None and ltype is not None
        profile = geometry.get("profile")
        if not isinstance(profile, (list, tuple)):
            raise CreateSpecError("для floor укажи geometry.profile [[x_mm,y_mm],...]")
        pts: list[tuple[float, float]] = []
        for i, row in enumerate(profile):
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                raise CreateSpecError(f"profile[{i}]: нужна пара [x_mm, y_mm]")
            pts.append((_finite(row[0], f"profile[{i}].x"), _finite(row[1], f"profile[{i}].y")))
        if len(pts) >= 2 and math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]) < 0.1:
            pts = pts[:-1]  # explicit closing point → implicit closure
        if len(pts) < 3:
            raise CreateSpecError("profile: нужен замкнутый полигон минимум из 3 точек")
        for i in range(len(pts)):
            j = (i + 1) % len(pts)
            if math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]) < _MIN_SEGMENT_MM:
                raise CreateSpecError(f"profile: сегмент {i}->{j} короче {_MIN_SEGMENT_MM:g}мм")
        profile_cs = ", ".join("{" + f"{x:.3f}, {y:.3f}" + "}" for x, y in pts)
        return {**common,
                "floor_type_id": int(ltype["id"]), "level_id": int(level["id"]),
                "base_z_mm": float(_as_float(level.get("elevation_mm")) or 0.0),
                "profile_cs": profile_cs}

    if element_type == "family_instance":
        assert level is not None and ltype is not None
        point = geometry.get("point")
        if not isinstance(point, dict):
            raise CreateSpecError("для family_instance укажи geometry.point {x_mm, y_mm}")
        x, y = _pt2(point, "point")
        z = _as_float(point.get("z_mm"))
        if z is None:
            z = _as_float(level.get("elevation_mm")) or 0.0
        rot = _as_float(point.get("rotation_deg")) or 0.0
        if not (-3600.0 <= rot <= 3600.0):
            raise CreateSpecError(f"rotation_deg {rot} вне допуска")
        structural = "Column" if ltype.get("category") == "OST_StructuralColumns" else "NonStructural"
        return {**common,
                "symbol_id": int(ltype["id"]), "level_id": int(level["id"]),
                "x_mm": float(x), "y_mm": float(y), "z_mm": float(z),
                "rotation_deg": float(rot), "structural_type": structural}

    raise CreateSpecError(f"element_type '{element_type}' не поддерживается")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5a — witness checks (pure) — fed into kukai.will.evaluator as
# extra_checks (source="read_back" ⇒ they GROUND the verdict; §2.4 Tier A)
# ─────────────────────────────────────────────────────────────────────────────

def derive_create_checks(
    element: dict[str, Any],
    grounding: dict[str, Any],
    result: Any,
) -> list[Check]:
    """Tier-A claim-vs-args checks for a create. Pure; never raises; missing
    witnesses → ok=None (absence-tolerance contract, evaluator.py:51-57)."""
    checks: list[Check] = []
    element = element if isinstance(element, dict) else {}
    grounding = grounding if isinstance(grounding, dict) else {}
    rd = _unwrap(result, "created_ids") if isinstance(result, dict) else {}
    readback = rd.get("readback") if isinstance(rd.get("readback"), dict) else {}
    expected = 1

    # -- claim.created_count (the create's core postcondition) --
    # When THIS check decides False, the rest of the read-back is untrusted:
    # it describes an element the result itself says was not (singly) created —
    # a lying/incoherent row must be a hard FAIL, never softened to partial by
    # its own healthy-looking echo fields (evaluator "impossible counts" iron).
    readback_trusted = True
    ids = rd.get("created_ids")
    if not isinstance(ids, (list, tuple)):
        checks.append(Check(
            kind="claim.created_count", expect=expected, observed=None, ok=None,
            source="read_back", detail="missing_created_ids"))
    else:
        n = len(ids)
        if n > expected:
            checks.append(Check(
                kind="claim.created_count", expect=expected, observed=n,
                ok=False, source="read_back", partial=False,
                detail="impossible_counts"))
            readback_trusted = False
        else:
            checks.append(Check(
                kind="claim.created_count", expect=expected, observed=n,
                ok=(n == expected), source="read_back"))
            if n != expected:
                readback_trusted = False
    if not readback_trusted:
        readback = {}

    # -- claim.category (grounded expectation vs post-commit truth) --
    exp_cat = grounding.get("expected_category")
    if exp_cat:
        obs_cat = readback.get("category")
        if isinstance(obs_cat, str) and obs_cat:
            checks.append(Check(
                kind="claim.category", expect=exp_cat, observed=obs_cat,
                ok=(obs_cat == exp_cat), source="read_back"))
        else:
            checks.append(Check(
                kind="claim.category", expect=exp_cat, observed=None, ok=None,
                source="read_back", detail="missing_readback"))

    # -- claim.level (args-space grounding vs read-back) --
    exp_lvl = _as_int(grounding.get("level_id"))
    if exp_lvl is not None:
        obs_lvl = _as_int(readback.get("level_id"))
        checks.append(Check(
            kind="claim.level", expect=exp_lvl, observed=obs_lvl,
            ok=(None if obs_lvl is None else obs_lvl == exp_lvl),
            source="read_back",
            detail=None if obs_lvl is not None else "missing_readback"))

    # -- claim.location (requested geometry vs Location re-read) --
    loc = _location_check(element, readback)
    if loc is not None:
        checks.append(loc)

    # -- claim.params_set (read-back-verified param count) --
    params = element.get("params") if isinstance(element.get("params"), dict) else {}
    if params:
        n_req = len(params)
        ps = (rd.get("params_set")
              if readback_trusted and isinstance(rd.get("params_set"), dict) else {})
        verified = _as_int(ps.get("verified"))
        if verified is None:
            checks.append(Check(
                kind="claim.params_set", expect=n_req, observed=None, ok=None,
                source="read_back", detail="missing_params_readback"))
        elif verified < 0 or verified > n_req:
            checks.append(Check(
                kind="claim.params_set", expect=n_req, observed=verified,
                ok=False, source="read_back", partial=False,
                detail="impossible_counts"))
        else:
            ok = verified == n_req
            checks.append(Check(
                kind="claim.params_set", expect=n_req, observed=verified,
                ok=ok, source="read_back", partial=(not ok) and verified > 0))

    return checks


def _arr_xy(value: Any) -> Optional[tuple[float, float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        x, y = _as_float(value[0]), _as_float(value[1])
        if x is not None and y is not None:
            return (x, y)
    return None


def _location_check(element: dict[str, Any], readback: dict[str, Any]) -> Optional[Check]:
    """claim.location: request-vs-readback geometry within tolerance. None when
    the request carries no comparable geometry (check not emitted)."""
    et = element.get("element_type")
    geometry = element.get("geometry") if isinstance(element.get("geometry"), dict) else {}
    geom_rb = readback.get("geometry_mm") if isinstance(readback.get("geometry_mm"), dict) else {}

    def _undecidable(expect: Any) -> Check:
        return Check(kind="claim.location", expect=expect, observed=None,
                     ok=None, source="read_back", detail="missing_readback")

    if et == "level":
        want = _as_float(element.get("elevation_mm"))
        if want is None:
            return None
        got = _as_float(readback.get("elevation_mm"))
        if got is None:
            return _undecidable({"elevation_mm": want})
        return Check(kind="claim.location", expect={"elevation_mm": want},
                     observed=got, ok=abs(got - want) <= _LOCATION_TOL_MM,
                     source="read_back")

    if et in ("wall", "grid"):
        line = geometry.get("line") if isinstance(geometry.get("line"), dict) else {}
        try:
            ws = _pt2(line.get("start"), "start")
            we = _pt2(line.get("end"), "end")
        except CreateSpecError:
            return None
        gs, ge = _arr_xy(geom_rb.get("start")), _arr_xy(geom_rb.get("end"))
        expect = {"start": list(ws), "end": list(we)}
        if gs is None or ge is None:
            return _undecidable(expect)

        def _d(a: tuple[float, float], b: tuple[float, float]) -> float:
            return math.hypot(a[0] - b[0], a[1] - b[1])

        deviation = min(max(_d(ws, gs), _d(we, ge)), max(_d(ws, ge), _d(we, gs)))
        return Check(kind="claim.location", expect=expect,
                     observed={"start": list(gs), "end": list(ge)},
                     ok=deviation <= _LOCATION_TOL_MM, source="read_back")

    if et == "family_instance":
        point = geometry.get("point") if isinstance(geometry.get("point"), dict) else {}
        wx, wy = _as_float(point.get("x_mm")), _as_float(point.get("y_mm"))
        if wx is None or wy is None:
            return None
        got = _arr_xy(geom_rb.get("point"))
        if got is None:
            return _undecidable({"point": [wx, wy]})
        dev = math.hypot(got[0] - wx, got[1] - wy)
        return Check(kind="claim.location", expect={"point": [wx, wy]},
                     observed={"point": list(got)},
                     ok=dev <= _LOCATION_TOL_MM, source="read_back")

    if et == "floor":
        profile = geometry.get("profile")
        if not isinstance(profile, (list, tuple)) or not profile:
            return None
        xs, ys = [], []
        for row in profile:
            p = _arr_xy(row)
            if p is None:
                return None
            xs.append(p[0]); ys.append(p[1])
        expect = {"bounds": [[min(xs), min(ys)], [max(xs), max(ys)]]}
        bbox = readback.get("bbox_mm") if isinstance(readback.get("bbox_mm"), dict) else {}
        bmin, bmax = _arr_xy(bbox.get("min")), _arr_xy(bbox.get("max"))
        if bmin is None or bmax is None:
            return _undecidable(expect)
        ok = (abs(bmin[0] - min(xs)) <= _BBOX_TOL_MM
              and abs(bmin[1] - min(ys)) <= _BBOX_TOL_MM
              and abs(bmax[0] - max(xs)) <= _BBOX_TOL_MM
              and abs(bmax[1] - max(ys)) <= _BBOX_TOL_MM)
        return Check(kind="claim.location", expect=expect,
                     observed={"bounds": [list(bmin), list(bmax)]},
                     ok=ok, source="read_back")

    return None


_CREATE_VIOLATION_BY_KIND = {
    "claim.created_count": "created_count_mismatch",
    "claim.category": "category_mismatch",
    "claim.level": "level_mismatch",
    "claim.location": "location_mismatch",
    "claim.params_set": "params_below_requested",
    "probe.element_present": "created_id_not_resolvable",
}


def collect_create_violations(checks: list[Check]) -> list[str]:
    """Stable violation tokens for failed create checks (order-stable, deduped)."""
    out: list[str] = []
    for c in checks:
        if c.ok is False:
            if c.detail == "impossible_counts":
                out.append("impossible_counts")
            token = _CREATE_VIOLATION_BY_KIND.get(c.kind)
            if token:
                out.append(token)
    return list(dict.fromkeys(out))


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5b — the independent probe (Tier B): inverse of delete's inspect_absent
# ─────────────────────────────────────────────────────────────────────────────

async def probe_element_present(element_id: Any, bridge_callback) -> Check:
    """After a successful create: does the created id resolve in a SEPARATE
    read-only round-trip? Reuses the verbs inspect builder + the Will probe
    runner (validated, time-capped, no 'attempt' key, never raises)."""
    try:
        from kukai.llm.verbs import build_inspect_code, perceive_inspect
        from kukai.will.probes import run_probe

        code = build_inspect_code(element_id)
        raw = await run_probe("element_present", code, bridge_callback)
        if raw is None:
            return Check(kind="probe.element_present", expect="present",
                         observed=None, ok=None, source="probe",
                         detail="probe_unavailable")
        shaped = perceive_inspect(raw)
        if shaped.get("error") == "not_found":
            return Check(kind="probe.element_present", expect="present",
                         observed="not_found", ok=False, source="probe")
        if shaped.get("error"):
            return Check(kind="probe.element_present", expect="present",
                         observed=shaped.get("error"), ok=None, source="probe",
                         detail="probe_inconclusive")
        return Check(kind="probe.element_present", expect="present",
                     observed={"id": shaped.get("id"),
                               "category": shaped.get("category")},
                     ok=True, source="probe")
    except Exception:  # noqa: BLE001 — probes never raise into the hot path
        logger.debug("probe_element_present failed (non-fatal)", exc_info=True)
        return Check(kind="probe.element_present", expect="present",
                     observed=None, ok=None, source="probe",
                     detail="probe_exception")


# ─────────────────────────────────────────────────────────────────────────────
# Timeout recovery (§2.6) — the op_id correlation stamp closes the
# TRANSPORT_TOOL_BUDGET_EXCEEDED "nothing to verify by" hole
# ─────────────────────────────────────────────────────────────────────────────

_UNCONFIRMED_ERR_CODES = frozenset({
    "transport.tool_budget_exceeded",
    "transport.bridge_timeout",
})
_UNCONFIRMED_MARKERS = ("timeout", "таймаут", "тайм-аут", "не подтвержд",
                        "бюджет", "budget")


def _is_unconfirmed(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("state") == "running_unconfirmed":
        return True
    err = result.get("err")
    if isinstance(err, dict) and err.get("code") in _UNCONFIRMED_ERR_CODES:
        return True
    if result.get("error"):
        msg = str(result.get("message", "")).lower()
        return any(m in msg for m in _UNCONFIRMED_MARKERS)
    return False


async def _recover_unconfirmed(
    llm_client: Any,
    bridge_callback,
    element_type: str,
    grounding: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    """ONE read-only recovery query by the op_id stamp: found → late-confirmed
    success (probe-grounded verdict); not found → honest 'not committed, safe
    to retry'. Never re-executes the create."""
    op_id = grounding.get("op_id", "")
    category = grounding.get("expected_category")
    datum_note = (
        " (датум-элементы могут не поддерживать метку Комментарии — проверь модель вручную)"
        if element_type in ("level", "grid") else ""
    )
    base = {"op": "create_element", "element_type": element_type, "op_id": op_id}

    if not category or not _OST_RE.match(category):
        return {**base, "error": True, "state": "unconfirmed",
                "message": ("Таймаут: результат не подтверждён и категория для "
                            "контрольного чтения неизвестна — проверь модель "
                            "вручную перед повтором.")}
    try:
        from kukai.write.operations import generate_create_recovery_code
        rcode = generate_create_recovery_code(op_id, category)
    except ValueError:
        return {**base, "error": True, "state": "unconfirmed",
                "message": "Таймаут: контрольное чтение не собралось — проверь модель вручную."}

    raw = await _dispatch(llm_client, bridge_callback, rcode, _GROUNDING_TIMEOUT_MS)
    raw = _unwrap(raw, "found")
    found = raw.get("found") if isinstance(raw, dict) else None

    if isinstance(found, list) and found:
        ids = [_as_int(f.get("id")) for f in found
               if isinstance(f, dict) and _as_int(f.get("id")) is not None]
        result: dict[str, Any] = {
            **base, "success": True, "recovered": True, "state": "late_confirmed",
            "created_ids": ids, "expected_count": 1,
            "message": ("Создание подтверждено контрольным чтением по метке "
                        "op_id (после таймаута)."),
        }
        if len(ids) > 1:
            result["message"] += f" ВНИМАНИЕ: найдено {len(ids)} элементов — проверь дубликаты."
        checks = [
            Check(kind="probe.element_present", expect="present",
                  observed=len(ids), ok=True, source="probe"),
            Check(kind="claim.created_count", expect=1, observed=len(ids),
                  ok=(len(ids) == 1), source="probe",
                  detail=None if len(ids) == 1 else "impossible_counts"),
        ]
        _attach_witness(result, args, checks, op_id, is_error=False)
        return result

    if isinstance(found, list):
        return {**base, "error": True, "state": "not_committed",
                "message": (f"Таймаут: элемент с меткой op_id не найден — создание "
                            f"НЕ закоммичено{datum_note}. Безопасно повторить запрос.")}

    return {**base, "error": True, "state": "unconfirmed",
            "message": ("Таймаут, и контрольное чтение не удалось — проверь "
                        "модель вручную перед повтором.")}


# ─────────────────────────────────────────────────────────────────────────────
# Transport + witness plumbing
# ─────────────────────────────────────────────────────────────────────────────

async def _dispatch(
    llm_client: Any,
    bridge_callback,
    code: str,
    timeout_ms: int,
    attempt: Optional[int] = None,
) -> dict[str, Any]:
    """The standard execute wire (same seam as apply_revit_write/family tools).
    Grounding/recovery reads carry NO 'attempt' key (probe convention — they
    must be excluded from LLM-initiated execute telemetry)."""
    params: dict[str, Any] = {"code": code, "timeout_ms": timeout_ms}
    if attempt is not None:
        params["attempt"] = attempt
    if bridge_callback:
        return await bridge_callback("execute", params)
    bridge = getattr(llm_client, "_bridge", None)
    if bridge:
        result = await bridge.execute(code, timeout_ms=timeout_ms)
        return result.model_dump()
    return {"error": True, "message": "Revit не подключён"}


def _attach_witness(
    result: dict[str, Any],
    args: dict[str, Any],
    checks: list[Check],
    op_id: str,
    *,
    is_error: bool,
) -> None:
    """Deterministic verdict (kukai.will.evaluator) → compact ``witness`` block
    on the tool result (§2.5.3). The model's 'готово' becomes quotable — and a
    fail verdict explicitly tells it NOT to claim success."""
    report = evaluate_structural(
        "apply_revit_write", args if isinstance(args, dict) else {}, result,
        is_error=is_error, extra_checks=checks or None)
    violations = list(dict.fromkeys(
        list(report.violations) + collect_create_violations(checks)))
    witness: dict[str, Any] = {
        "verdict": report.verdict,
        "score": round(report.score, 4),
        "checks_decided": sum(1 for c in report.checks if c.ok is not None),
        "violations": violations,
        "op_id": op_id,
    }
    # Embed the EVIDENCE (not just the folded verdict) so the shadow layer can
    # consume it through the trust registry (kukai/will/witness.py) instead of
    # blindly re-deriving — the read_back/probe checks are what ground the
    # eval_verdicts row. This dict is server-attached post-bridge (overwrite
    # below), so template/bridge output can never forge it.
    from kukai.will.witness import attach_checks
    attach_checks(witness, checks or [])
    if report.verdict in ("fail", "partial"):
        witness["note"] = (
            "Witness НЕ подтвердил создание полностью — НЕ сообщай пользователю "
            "об успехе; проверь модель (inspect/query_model) или повтори с уточнением."
        )
    result["witness"] = witness


def _category_token(args: dict[str, Any], element: dict[str, Any]) -> Optional[str]:
    """Optional BuiltInCategory pool filter for family_instance grounding,
    resolved through the canonical RU/EN alias map (never trusted raw)."""
    raw = args.get("category") or element.get("category") or ""
    if not isinstance(raw, str) or not raw.strip():
        return None
    token = raw.strip()
    if not _OST_RE.match(token):
        try:
            from kukai.write.router import resolve_category
            token = resolve_category(token) or ""
        except Exception:  # noqa: BLE001 — filter is an optimization only
            token = ""
    return token if token and _OST_RE.match(token) else None


# ─────────────────────────────────────────────────────────────────────────────
# The handler — ground → render → execute → witness → verdict
# ─────────────────────────────────────────────────────────────────────────────

async def execute_create_element(
    llm_client: Any,
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback] = None,
) -> dict[str, Any]:
    """apply_revit_write(operation="create_element") — the server-side lowering.

    ``llm_client`` is the LLMClient instance (only ``_bridge``/``_revit_version``
    are touched); ``bridge_callback`` is the standard execute wire.
    """
    if not create_element_enabled():
        # Defense-in-depth: the dispatcher already gates on the flag; if we are
        # reached anyway, refuse in the legacy unknown-op shape.
        return {"error": True, "message": "Неизвестная операция: create_element"}

    args = args if isinstance(args, dict) else {}
    element = args.get("element")
    if not isinstance(element, dict):
        return _invalid("element (объект-спецификация) обязателен для create_element")
    element_type = element.get("element_type")
    if element_type not in ELEMENT_TYPES:
        return _invalid(
            f"element_type '{element_type}' не поддерживается в v1; "
            f"доступны: {', '.join(ELEMENT_TYPES)}")
    dry_run = bool(element.get("dry_run"))

    from kukai.security.validation import validate_code_safety

    # ── Stage 1: GROUND (resolve or refuse — no ungrounded C#, ever) ────────
    grounding: dict[str, Any] = {
        "element_type": element_type,
        "expected_category": _STATIC_CATEGORY.get(element_type),
        "level_id": None,
        "type_id": None,
        "op_id": _new_op_id(),
    }
    level: Optional[dict[str, Any]] = None
    ltype: Optional[dict[str, Any]] = None
    levels: list[dict[str, Any]] = []

    if element_type in ("wall", "floor", "family_instance"):
        gcode = build_grounding_code(
            element_type, element.get("type"), _category_token(args, element))
        gv = validate_code_safety(gcode)
        if gv:
            return {"error": True, "op": "create_element", "stage": "grounding",
                    "message": "grounding: код не прошёл проверку безопасности",
                    "violations": gv}
        raw = await _dispatch(llm_client, bridge_callback, gcode, _GROUNDING_TIMEOUT_MS)
        raw = _unwrap(raw, "levels")
        if not isinstance(raw, dict) or raw.get("error") or "levels" not in raw:
            msg = raw.get("message") if isinstance(raw, dict) else str(raw)
            return {"error": True, "op": "create_element", "stage": "grounding",
                    "message": f"не удалось прочитать модель для grounding: {msg}"}
        levels = raw.get("levels") if isinstance(raw.get("levels"), list) else []
        pool = raw.get("types") if isinstance(raw.get("types"), list) else []

        lres = resolve_level(element.get("level"), levels)
        if lres["status"] != STATUS_RESOLVED:
            return _refusal("level", lres)
        tres = resolve_type(element.get("type"), pool, element_type)
        if tres["status"] != STATUS_RESOLVED:
            return _refusal("type", tres)
        level, ltype = lres["level"], tres["type"]
        grounding["level_id"] = _as_int(level.get("id"))
        grounding["type_id"] = _as_int(ltype.get("id"))
        if element_type == "family_instance":
            cat = ltype.get("category") or ""
            grounding["expected_category"] = cat if _OST_RE.match(str(cat)) else None
    # level/grid need no grounding read (no model references to resolve).

    # ── Stage 2: RENDER (verified template; manifest-validated args) ────────
    try:
        template_args = _build_template_args(
            element_type, element, level, ltype, levels, grounding["op_id"])
        code = render_create_code(element_type, template_args)
    except CreateSpecError as spec_exc:
        return _invalid(str(spec_exc))
    except Exception as render_exc:  # noqa: BLE001 — a render fault is a server bug
        logger.exception("create_element: render failed (server bug)")
        return {"error": True, "op": "create_element", "stage": "render",
                "message": f"внутренняя ошибка рендера шаблона: {render_exc}"}
    cv = validate_code_safety(code)
    if cv:
        return {"error": True, "op": "create_element", "stage": "render",
                "message": "Сгенерированный код не прошёл проверку безопасности",
                "violations": cv}

    if dry_run:
        return {
            "success": True, "dry_run": True,
            "op": "create_element", "element_type": element_type,
            "grounding": {"level": level, "type": ltype, "op_id": grounding["op_id"]},
            "plan": {"expected_count": 1,
                     "expected_category": grounding["expected_category"]},
            "code": code,
        }

    # ── Stage 4: EXECUTE (pipeline when KUKAI_EXEC_PIPELINE=1, else legacy) ─
    timeout_ms = _CREATE_TIMEOUT_MS_FLOOR if element_type == "floor" else _CREATE_TIMEOUT_MS
    record = None
    use_pipeline = False
    if bridge_callback is not None:
        try:
            from kukai.llm.revit_execution_pipeline import pipeline_enabled
            use_pipeline = pipeline_enabled()
        except Exception:  # noqa: BLE001 — pipeline availability is optional
            use_pipeline = False
    if use_pipeline:
        from kukai.llm.revit_execution_pipeline import RevitExecutionPipeline
        pipe = RevitExecutionPipeline.from_llm_client(llm_client, bridge_callback)
        record = await pipe.run_declarative(
            code, tool="apply_revit_write", op="create_element",
            args=args, timeout_ms=timeout_ms,
            derive_extra_checks=lambda res: derive_create_checks(element, grounding, res),
        )
        result: Any = record.to_tool_result()
    else:
        result = await _dispatch(llm_client, bridge_callback, code, timeout_ms, attempt=1)

    # ── Stage 5: WITNESS → verdict ───────────────────────────────────────────
    if (record is not None and record.state == "timeout_unconfirmed") or _is_unconfirmed(result):
        return await _recover_unconfirmed(
            llm_client, bridge_callback, element_type, grounding, args)

    if not isinstance(result, dict):
        return {"error": True, "op": "create_element",
                "message": f"неожиданный ответ моста: {result!r}"}
    result = _unwrap(result, "created_ids")

    is_error = bool(result.get("error"))
    checks = derive_create_checks(element, grounding, result)
    if not is_error and bridge_callback is not None:
        ids = result.get("created_ids")
        if isinstance(ids, (list, tuple)) and ids:
            checks.append(await probe_element_present(ids[0], bridge_callback))

    result.setdefault("op", "create_element")
    result.setdefault("element_type", element_type)
    # The server KNOWS which op_id it stamped — assert it over any template echo.
    result["op_id"] = grounding["op_id"]
    _attach_witness(result, args, checks, grounding["op_id"], is_error=is_error)
    return result
