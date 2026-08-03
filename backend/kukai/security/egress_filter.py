"""Egress filter (KUKAI_EGRESS_FILTER) — deterministic scrub of KUKAI internals from
USER-FACING text.

The system prompt tells the model never to reveal its model/provider/architecture
(prompts/system_base.md:7-19) — but that is ADVISORY: a jailbreak, an injected file,
or a raw error string echoed back can leak it anyway (verified: today user-facing text
is NOT scrubbed at all — the _send_json funnel forwards verbatim). This module is the
ENFORCED guarantee: a code-level scrub at the outbound funnel, so secrecy stops being a
polite request to the model and becomes a property of the system.

Mode (KUKAI_EGRESS_FILTER): "0"/off (default, no-op — byte-identical) | "shadow" (report
what WOULD be scrubbed, do NOT alter the text) | "1"/on (redact). Shadow-first so we can
size false positives on real traffic before enforcing.

Scope note (streaming): applied per-chunk at the funnel, this reliably catches single
TOKEN leaks (model/provider names, architecture nouns) even mid-stream. Multi-chunk code
BLOCKS that span several stream_chunks are a known v2 gap (needs a buffering filter);
complete strings (error/tool-result/final messages) are fully covered.
"""
from __future__ import annotations

import os
import re

# ── what to scrub (deliberately NARROW to avoid mangling legitimate BIM/Revit prose) ──

# Model/provider identity — never legitimate for the assistant to utter.
_IDENTITY = re.compile(
    r"\b(gemini|vertex\s*ai|vertex|deepseek|open\s*router|xiaomi|mimo|nemotron|nvidia|"
    r"anthropic|claude|openai|gpt-?\d?(?:\.\d)?|\bllm\b)\b",
    re.IGNORECASE,
)

# Backend architecture NOUNS — internal-only. NOT generic words ("Revit", "C#", "мост"/
# "bridge", "модель" stay — those are legitimate BIM vocabulary and scrubbing them would
# mangle real answers; see the sweep's over-scrub note).
_ARCH = re.compile(
    r"\b(roslyn|external\s*event|revitexecutionpipeline|providerchain|turnledger|"
    r"compile-service|webview2|json-?rpc)\b",
    re.IGNORECASE,
)

# RAG only as a standalone all-caps token (avoid matching inside unrelated words).
_RAG = re.compile(r"\bRAG\b")

# Absolute server/client paths that could ride inside a leaked exception string.
_PATHS = re.compile(r"(?:/opt/[\w./-]+|[A-Za-z]:\\Users\\[\w\\.\- ]+)")

_PATTERNS = (_IDENTITY, _ARCH, _RAG, _PATHS)
_REDACTION = "…"


def egress_mode() -> str:
    v = (os.environ.get("KUKAI_EGRESS_FILTER", "0") or "0").strip().lower()
    if v in ("1", "on", "enforce", "true"):
        return "on"
    if v == "shadow":
        return "shadow"
    return "off"


def scrub_text(text: str) -> tuple[str, list[str]]:
    """Return (scrubbed_text, hits). ``hits`` are the internal tokens found (verbatim),
    used for shadow-mode sizing. When nothing matches, returns the text unchanged and []."""
    if not isinstance(text, str) or not text:
        return text, []
    hits: list[str] = []

    def _repl(m: "re.Match[str]") -> str:
        hits.append(m.group(0))
        return _REDACTION

    out = text
    for pat in _PATTERNS:
        out = pat.sub(_repl, out)
    return out, hits


# Which fields of an outbound WS payload carry user-visible text.
_TEXT_FIELDS = ("text", "error", "message")


def scrub_payload(data: dict) -> tuple[dict, list[str]]:
    """Scrub the user-visible text fields of an outbound WS payload. Returns (payload,
    hits). In callers, shadow mode uses only ``hits`` (payload discarded); on mode sends
    the returned payload. Non-text payloads pass through untouched (hits empty)."""
    if not isinstance(data, dict):
        return data, []
    hits: list[str] = []
    out = data
    for field in _TEXT_FIELDS:
        val = data.get(field)
        if isinstance(val, str) and val:
            scrubbed, h = scrub_text(val)
            if h:
                hits.extend(h)
                if out is data:
                    out = dict(data)
                out[field] = scrubbed
    # result.message (bridge/tool result echoed to the user)
    res = data.get("result")
    if isinstance(res, dict) and isinstance(res.get("message"), str) and res["message"]:
        scrubbed, h = scrub_text(res["message"])
        if h:
            hits.extend(h)
            if out is data:
                out = dict(data)
            out["result"] = {**res, "message": scrubbed}
    return out, hits
