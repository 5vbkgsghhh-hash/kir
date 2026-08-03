"""LLM-adaptation layer — the 'vibe' half of the hybrid generator.

The typology skeleton (building.py) is the guaranteed-habitable base; this layer lets a free-text
INTENT reshape it while the checker keeps it correct: the LLM proposes a modified SpatialModel,
the checker validates it, and any BLOCKING violations are fed back until the building passes or the
budget runs out (generate → adapt → check → fix — vibecoding for buildings).

The LLM call is INJECTABLE (`complete=`), so the loop is unit-tested with a mock (no network);
the default `complete` uses the prod DeepSeek model via litellm.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable

from kukai.modeling.checker.engine import run
from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.spatial_model import SpatialModel, Verdict

MODEL = os.environ.get("KUKAI_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
_PROVIDER_PIN = {"provider": {"order": ["DeepInfra", "Novita", "AtlasCloud"], "allow_fallbacks": True}}

SYSTEM = (
    "You are a residential-building editor. You receive a building as a SpatialModel JSON "
    "(levels; rooms with boundary polygons in mm + function + apartment_id; doors with "
    "from_room_id/to_room_id; windows; stairs; walls) and an INTENT. Modify the JSON to satisfy "
    "the intent while keeping a VALID, HABITABLE building:\n"
    "- rooms on a level must not overlap; every room reachable from the entrance through doors;\n"
    "- each apartment keeps exactly one entrance into public circulation;\n"
    "- habitable (жилая) rooms need a window (has_window=true, window_area_m2>0);\n"
    "- min areas: жилая>=8, кухня>=5, санузел>=2.2 m²; ceiling height_mm>=2500; corridor width>=900mm;\n"
    "- stairs connect every level; keep ids unique and every reference valid.\n"
    "Return ONLY the complete modified SpatialModel JSON — no prose, no markdown fences."
)

# v2 prompt: the checker DERIVES every quantity from geometry, so the model is told the
# truth about what will be measured — and is NEVER instructed to set the scalar flags
# the rules read (the v1 prompt literally taught the LLM to self-certify with
# has_window=true; under v2 an unbacked scalar is a BLOCKING HAB060 lie).
SYSTEM_V2 = (
    "You are a residential-building editor. You receive a building as a SpatialModel JSON "
    "(levels; rooms with boundary polygons in mm + function + apartment_id; doors with "
    "location + from_room_id/to_room_id; windows with host_wall_id/width_mm/height_mm; "
    "stairs; walls with curve segments) and an INTENT. Modify the JSON to satisfy the "
    "intent while keeping a VALID, HABITABLE building.\n"
    "IMPORTANT — the checker verifies GEOMETRY, not declarations: room areas are "
    "recomputed from the boundary polygons; a door only connects rooms if its location "
    "lies on their shared boundary edge; a window only counts if its host wall lies on "
    "the room's exterior boundary on the building envelope. Declared scalars that "
    "disagree with the geometry are BLOCKING violations. So:\n"
    "- edit BOUNDARIES to change room sizes (area_m2 must equal the polygon area);\n"
    "- to light a room, add a real window hosted in a wall segment that lies on that "
    "room's envelope-exterior edge (give the window width_mm and height_mm);\n"
    "- place every door ON the shared edge of the two rooms it connects; building "
    "entrances sit on the envelope at ground level;\n"
    "- rooms on a level must not overlap; every room reachable from the entrance;\n"
    "- each apartment keeps exactly one entrance from public circulation;\n"
    "- min areas: жилая>=8, кухня>=5, санузел>=2.2 m²; ceiling height_mm>=2500; widths: "
    "corridor>=900mm, kitchen>=1700mm;\n"
    "- stairs connect every level; keep ids unique and every reference valid.\n"
    "Return ONLY the complete modified SpatialModel JSON — no prose, no markdown fences."
)


def _default_complete(messages: list[dict]) -> str:
    import litellm
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("KUKAI_LLM_API_KEY")
    kw = dict(model=MODEL, messages=messages, temperature=0.3, max_tokens=16000, timeout=180)
    if api_key:
        kw["api_key"] = api_key
    if str(MODEL).startswith("openrouter/"):
        kw["extra_body"] = _PROVIDER_PIN
    resp = litellm.completion(**kw)
    return resp.choices[0].message.content or ""


def _extract_json(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.I)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


@dataclass
class AdaptResult:
    model: dict
    passed: bool
    intent: str
    iterations: int
    history: list[str] = field(default_factory=list)
    #: adapt() verdicts are claims about the LLM's dict. Only the round-trip
    #: (generator/roundtrip.py) may certify a building for the real world.
    certified: bool = False


def adapt(model: dict, intent: str, *, max_iters: int = 4,
          complete: Callable[[list[dict]], str] | None = None) -> AdaptResult:
    """Adapt `model` to `intent` under the checker. Returns the best model reached and whether it
    passes. `complete(messages)->text` is the LLM (defaults to prod DeepSeek; inject a mock to test).
    """
    complete = complete or _default_complete
    messages = [
        {"role": "system", "content": SYSTEM_V2 if checker_v2_enabled() else SYSTEM},
        {"role": "user", "content": f"INTENT: {intent}\n\nSpatialModel:\n"
                                    f"{json.dumps(model, ensure_ascii=False)}"},
    ]
    history: list[str] = []
    best = model

    for it in range(max_iters):
        text = complete(messages)
        proposed = _extract_json(text)
        if proposed is None:
            history.append("unparseable")
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": "That was not valid JSON. Return ONLY the "
                                                      "complete SpatialModel JSON."}]
            continue
        try:
            validated = SpatialModel.model_validate(proposed)
        except Exception as e:
            history.append(f"schema-invalid: {str(e)[:80]}")
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"Invalid SpatialModel: {str(e)[:300]}. "
                                                      "Return the corrected complete JSON."}]
            continue
        best = proposed
        report = run(validated)
        if report.passed:
            history.append("passed")
            return AdaptResult(proposed, True, intent, it + 1, history)
        if report.blocking:
            viols = "; ".join(f"{v.rule_id}: {v.msg}" for v in report.blocking)
            history.append(f"blocking: {[v.rule_id for v in report.blocking]}")
            feedback = (f"The correctness checker found BLOCKING violations: {viols}. "
                        "Fix them and return the complete corrected SpatialModel JSON.")
        else:
            # v2 three-valued verdict: NOT_EVALUATED (vacuous mandatory rules /
            # unclassifiable rooms / unmeasurable geometry) must be repaired too —
            # unknown is not a pass and must not silently exhaust the budget.
            reasons: list[str] = []
            if report.coverage is not None:
                reasons += [f"{rid} could not be evaluated"
                            for rid in report.coverage.mandatory_not_evaluated]
                reasons += report.coverage.notes
            history.append(f"not_evaluated: {reasons[:3]}")
            feedback = ("The correctness checker could NOT evaluate the building: "
                        + "; ".join(reasons)
                        + ". Provide measurable boundary polygons and recognizable room "
                          "functions, then return the complete corrected SpatialModel JSON.")
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": feedback}]

    return AdaptResult(best, run(SpatialModel.model_validate(best)).passed, intent, max_iters, history)
