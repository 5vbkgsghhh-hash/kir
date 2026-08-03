"""Vision critic — the AGENT'S EYES (2026-07-07).

The chat model (deepseek-v4-flash) is text-only — it literally cannot see the
Revit result it just produced. This module gives the agent eyes: after a write,
the server navigates the live view to the result, screenshots it, and sends the
image to a SEPARATE vision model acting as a technical QA inspector. The vision
model returns a STRUCTURED verdict (created? placed right? anomalies?) which
flows back to the chat model as text — closing the build→SEE→critique→fix loop.

Design decisions (all evidence-based, 2026-07-07):
  * Model = `qwen/qwen2.5-vl-72b-instruct` (empirically: reads architectural 3D
    correctly, names anomalies, ~3.6s, served by non-Google providers — the
    operator's «не пользуемся гуглом» rules out Gemini). Overridable via
    KUKAI_VISION_MODEL.
  * The vision model is an INSPECTOR, not a describer — a tight system prompt
    with a checklist + strict JSON verdict, so the output is actionable
    ("балкон внутрь, без ограждения → переделать"), not prose.
  * Flag-gated (KUKAI_VISION_CRITIC, default OFF ⇒ inert). Fail-open: any error
    returns None and the turn proceeds exactly as before.
  * Deepseek stays the BRAIN; this is only the EYES. They talk in text.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import litellm

# Eyes chain: primary is xiaomi/mimo-v2.5 — empirically reads architectural 3D
# and names anomalies as well as qwen, but ~8× cheaper ($0.105/$0.280 vs
# $0.80/$1.00 per Mtok), multimodal (text/image/video), served by Xiaomi's own
# endpoint. qwen2.5-vl-72b is the fallback (proven, distinct provider) so a
# blank/429 from one eye is covered by the other. Override the whole chain via
# KUKAI_VISION_MODEL (comma-separated) or KUKAI_VISION_MODELS.
DEFAULT_VISION_MODEL = "openrouter/xiaomi/mimo-v2.5"
_FALLBACK_VISION_MODELS = ["openrouter/qwen/qwen2.5-vl-72b-instruct"]

# The inspector's brief. It receives the user's INTENT + the screenshot and must
# judge the RESULT against the intent — an engineering acceptance check, not art
# criticism. Strict JSON so the verdict is machine- and model-actionable.
_CRITIC_SYSTEM = (
    "Ты — ГЛАЗА для текстовой ИИ-модели, которая полностью СЛЕПА и не видит это "
    "изображение. Твоё описание — её ЕДИНСТВЕННЫЙ канал восприятия: по нему она "
    "должна суметь рассуждать о сцене и принимать инженерные решения так, будто "
    "увидела кадр сама. Поэтому описывай МАКСИМАЛЬНО полно, точно и пространственно "
    "— как будто подробно рассказываешь слепому инженеру, что перед ним: что за "
    "объект/здание, форма и геометрия, что где расположено и относительно чего "
    "(снаружи/внутри/сверху/сбоку/примыкает/висит), пропорции и масштаб, материалы "
    "и остекление, все видимые элементы (стены, перекрытия, колонны, витраж, "
    "балконы, ограждения, оборудование, кровля) и их состояние. Не упускай ничего "
    "существенного, но без воды.\n\n"
    "Одновременно ты — технический контролёр BIM-модели Autodesk Revit. На вход: "
    "НАМЕРЕНИЕ пользователя (что ИИ должен был сделать) и 3D-скриншот модели ПОСЛЕ "
    "действия ИИ, наведённый на результат. Твоя вторая задача — инженерная приёмка: "
    "сверить результат с намерением и найти дефекты. Ты НЕ художник — оценивай "
    "соответствие заданию и корректность, а не красоту.\n\n"
    "Проверь по чек-листу: (1) созданы ли требуемые элементы; (2) размещение — "
    "снаружи/внутри/в воздухе/сквозь стену; (3) форма и пропорции разумны; "
    "(4) все части задания на месте (например ограждение у балкона); "
    "(5) видимые аномалии — примитивы-заглушки, дубли, мусор, элементы не на месте.\n\n"
    "Ответь СТРОГО одним JSON-объектом, без markdown-ограждения:\n"
    "{\"сцена\": \"максимально подробное текстовое описание всего кадра для слепой "
    "текстовой модели — пространственно и предметно, 3-6 фраз\", "
    "\"выполнено\": true|false, \"размещение\": \"верно|внутрь|в_воздухе|сквозь|неясно\", "
    "\"недостающее\": [\"...\"], \"аномалии\": [\"...\"], \"вердикт\": \"ок|переделать|неясно\", "
    "\"комментарий\": \"одна короткая инженерная фраза\"}"
)


def vision_critic_enabled() -> bool:
    """KUKAI_VISION_CRITIC=1 turns the eyes on (read at call time)."""
    return os.environ.get("KUKAI_VISION_CRITIC", "0") == "1"


def _vision_chain() -> list[str]:
    """Ordered eyes chain: env override (comma-sep) or mimo→qwen default."""
    raw = (os.environ.get("KUKAI_VISION_MODELS", "")
           or os.environ.get("KUKAI_VISION_MODEL", "")).strip()
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    return [DEFAULT_VISION_MODEL, *_FALLBACK_VISION_MODELS]


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    """Pull the first JSON object out of the model's reply (tolerant of ```json
    fences / leading prose). Returns None if nothing parses."""
    if not text:
        return None
    s = text.strip()
    # strip a leading ```json / ``` fence if present
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    # find the outermost {...}
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b == -1 or b <= a:
        return None
    try:
        obj = json.loads(s[a:b + 1])
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


async def critique(
    intent: str,
    image_base64: str,
    api_key: Optional[str] = None,
    timeout_s: float = 30.0,
) -> Optional[dict[str, Any]]:
    """Send the intent + screenshot to the vision inspector; return its parsed
    verdict dict (see _CRITIC_SYSTEM schema) or None on any failure (fail-open).

    `image_base64` is the raw base64 PNG (no data: prefix needed — added here).
    """
    if not image_base64 or not intent:
        return None
    b64 = image_base64.split(",", 1)[1] if image_base64.startswith("data:") else image_base64
    messages = [
        {"role": "system", "content": _CRITIC_SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": f"НАМЕРЕНИЕ пользователя: {intent}\n\nОцени результат на скриншоте."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
        ]},
    ]
    # Try each eye in the chain: first one that returns a parseable verdict wins.
    # A blank content (mimo occasionally returns empty) or an error falls through
    # to the next eye — same resilience idea as the text provider chain.
    for _model in _vision_chain():
        kwargs: dict[str, Any] = {
            "model": _model,
            "messages": messages,
            "max_tokens": 400,
            "temperature": 0.1,
            "timeout": timeout_s,
            "drop_params": True,  # vision models vary in params — never die on one
        }
        # Route the eyes at an OpenAI-compatible endpoint of our own when asked —
        # e.g. the local Codex-subscription proxy, so looking at the model costs
        # subscription quota instead of OpenRouter credits (and the eye is then the
        # same multimodal family as the brain). Unset ⇒ unchanged OpenRouter path.
        _v_base = os.environ.get("KUKAI_VISION_API_BASE", "").strip()
        _v_key = os.environ.get("KUKAI_VISION_API_KEY", "").strip()
        if _v_base:
            kwargs["api_base"] = _v_base
        if _v_key:
            kwargs["api_key"] = _v_key
        elif api_key:
            kwargs["api_key"] = api_key
        try:
            resp = await litellm.acompletion(**kwargs)
            content = resp.choices[0].message.content or ""
            verdict = _extract_json(content)
            if verdict is not None:
                return verdict
            # empty/unparseable → try the next eye
        except Exception:  # noqa: BLE001 — best-effort; try the next eye
            continue
    return None


def format_verdict_for_user(verdict: dict[str, Any]) -> str:
    """One-line human summary of the inspector's verdict for the chat panel."""
    if not isinstance(verdict, dict):
        return ""
    v = str(verdict.get("вердикт") or "").lower()
    icon = {"ок": "✅", "переделать": "⚠️", "неясно": "❓"}.get(v, "👁")
    parts = [str(verdict.get("комментарий") or "").strip()]
    miss = verdict.get("недостающее") or []
    anom = verdict.get("аномалии") or []
    if miss:
        parts.append("не хватает: " + ", ".join(map(str, miss[:3])))
    if anom:
        parts.append("аномалии: " + ", ".join(map(str, anom[:3])))
    body = " · ".join(p for p in parts if p)
    return f"{icon} Проверка глазами: {body}"


def format_verdict_for_model(verdict: dict[str, Any]) -> str:
    """Compact text the chat model reads as feedback to decide on a fix."""
    if not isinstance(verdict, dict):
        return ""
    return "ВИЗУАЛЬНАЯ ПРОВЕРКА РЕЗУЛЬТАТА (независимая vision-модель): " + json.dumps(
        verdict, ensure_ascii=False)
