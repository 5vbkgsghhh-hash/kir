"""Prompt injection detection and sanitization.

Normalizes Unicode (NFKC), strips zero-width characters,
replaces Cyrillic/Greek homoglyphs with ASCII equivalents,
then scans for injection/jailbreak/exfiltration/Revit-specific patterns.

Risk levels: safe (score < 2.0), suspicious (2.0-3.99), dangerous (>= 4.0).
Detection is advisory by default because additive heuristics can false-positive on
legitimate BIM requests.  Set ``KUKAI_PROMPT_GUARD=1`` to enforce blocking and
sanitization at the API boundary.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# --- Homoglyph mapping: Cyrillic/Greek look-alikes → ASCII ---
_HOMOGLYPHS: dict[str, str] = {
    "\u0430": "a",  # Cyrillic а → a
    "\u0435": "e",  # Cyrillic е → e
    "\u043e": "o",  # Cyrillic о → o
    "\u0440": "p",  # Cyrillic р → p
    "\u0441": "c",  # Cyrillic с → c
    "\u0443": "y",  # Cyrillic у → y
    "\u0445": "x",  # Cyrillic х → x
    "\u0456": "i",  # Cyrillic і → i
    "\u0458": "j",  # Cyrillic ј → j
    "\u0455": "s",  # Cyrillic ѕ → s
    "\u04bb": "h",  # Cyrillic һ → h
    "\u0501": "d",  # Cyrillic ԁ → d
    "\u03bd": "v",  # Greek ν → v
    "\u0391": "A",  # Greek Α → A
    "\u0392": "B",  # Greek Β → B
    "\u0395": "E",  # Greek Ε → E
    "\u0397": "H",  # Greek Η → H
    "\u0399": "I",  # Greek Ι → I
    "\u039a": "K",  # Greek Κ → K
    "\u039c": "M",  # Greek Μ → M
    "\u039d": "N",  # Greek Ν → N
    "\u039f": "O",  # Greek Ο → O
    "\u03a1": "P",  # Greek Ρ → P
    "\u03a4": "T",  # Greek Τ → T
    "\u03a7": "X",  # Greek Χ → X
    "\u0396": "Z",  # Greek Ζ → Z
}

# Zero-width characters to strip
_ZERO_WIDTH_CHARS = frozenset({
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\u2060",  # word joiner
    "\ufeff",  # BOM / zero-width no-break space
})


def _normalize_unicode(text: str) -> str:
    """Normalize text for pattern matching.

    1. NFKC normalization
    2. Strip zero-width characters
    3. Replace Cyrillic/Greek homoglyphs with ASCII equivalents

    This is critical: Russian users may accidentally or intentionally write
    'System.IO' with Cyrillic 'о', bypassing pattern-based security.
    """
    # NFKC normalization
    text = unicodedata.normalize("NFKC", text)

    # Strip zero-width characters
    text = "".join(ch for ch in text if ch not in _ZERO_WIDTH_CHARS)

    # Replace homoglyphs
    text = "".join(_HOMOGLYPHS.get(ch, ch) for ch in text)

    return text


# --- Pattern definitions ---

@dataclass
class _Pattern:
    """A detection pattern with weight and label."""
    regex: re.Pattern[str]
    weight: float
    label: str
    group: str


def _compile_patterns(
    patterns: list[tuple[str, float, str, str]],
    flags: int = re.IGNORECASE,
) -> list[_Pattern]:
    return [
        _Pattern(re.compile(p, flags), w, lbl, grp)
        for p, w, lbl, grp in patterns
    ]


# English injection patterns (checked against Latin-folded text)
_EN_PATTERNS = _compile_patterns([
    # Injection / jailbreak
    (r"ignore\s+(?:all\s+)?(?:previous\s+)?instructions?", 3.0, "ignore_instructions", "injection"),
    (r"forget\s+(?:all\s+)?(?:your\s+)?(?:instructions?|system\s+prompt|rules?|guidelines?)", 3.0, "forget_instructions", "injection"),
    (r"disregard\s+(?:all\s+)?prior", 3.0, "disregard_prior", "injection"),
    (r"you\s+are\s+now\b", 3.0, "you_are_now", "injection"),
    (r"\bact\s+as\b", 2.0, "act_as", "injection"),
    (r"\bswitch\s+to\b", 3.0, "switch_to", "injection"),
    (r"\bnew\s+role\b", 3.0, "new_role", "injection"),
    (r"\bDAN\s+mode\b", 3.0, "dan_mode", "injection"),
    (r"<\s*/?system\s*>", 3.0, "fake_system_tag", "injection"),
    (r"\[SYSTEM\]", 3.0, "fake_system_bracket", "injection"),
    (r"\[INST\]", 3.0, "fake_inst_bracket", "injection"),
    (r"\bjailbreak\b", 3.0, "jailbreak", "injection"),
    (r"bypass\s+safety", 3.0, "bypass_safety", "injection"),
    (r"ignore\s+restrictions?", 3.0, "ignore_restrictions", "injection"),
    (r"override\s+(?:your\s+)?(?:safety|guidelines|rules)", 3.0, "override_safety", "injection"),
    (r"pretend\s+(?:you\s+(?:are|have)|there\s+are)\s+no\s+(?:rules|restrictions|limits)", 3.0, "pretend_no_rules", "injection"),

    # Social engineering
    (r"don'?t\s+tell\s+the\s+user", 2.5, "dont_tell_user", "social"),
    (r"hide\s+this\s+from", 2.5, "hide_from", "social"),
    (r"\bsecretly\b", 2.5, "secretly", "social"),
    (r"keep\s+this\s+between\s+us", 2.5, "between_us", "social"),
    (r"pretend\s+that\b", 2.5, "pretend_that", "social"),
    (r"act\s+as\s+if\s+nothing", 2.5, "act_as_if", "social"),

    # Exfiltration — direct
    (r"show\s+(?:me\s+)?your\s+system\s+prompt", 3.5, "show_system_prompt", "exfiltration"),
    (r"what\s+are\s+your\s+instructions?", 3.5, "what_instructions", "exfiltration"),
    (r"print\s+(?:your\s+)?context", 3.5, "print_context", "exfiltration"),
    (r"read\s+\.env\b", 3.5, "read_env", "exfiltration"),
    (r"show\s+environment\s+variables?", 3.5, "show_env_vars", "exfiltration"),
    (r"\bAPI\s*key\b", 3.5, "api_key", "exfiltration"),
    (r"\bsecret\s*key\b", 3.5, "secret_key", "exfiltration"),
    (r"dump\s+your\b", 3.5, "dump_your", "exfiltration"),
    (r"export\s+config", 3.5, "export_config", "exfiltration"),
    (r"show\s+credentials?", 3.5, "show_credentials", "exfiltration"),

    # Exfiltration — indirect (rephrasing attacks)
    (r"(?:translate|convert)\s+(?:your\s+)?(?:instructions?|guidelines?|rules?|prompt)", 3.5, "translate_instructions", "exfiltration"),
    (r"(?:summarize|repeat|restate|paraphrase)\s+(?:your\s+)?(?:instructions?|guidelines?|rules?|system)", 3.5, "summarize_instructions", "exfiltration"),
    (r"(?:explain|describe)\s+(?:your|how\s+you)\s+(?:work|process|generat|operat|function|behav)", 3.0, "explain_how_you_work", "exfiltration"),
    (r"what\s+(?:do\s+you|is\s+your)\s+(?:base|use|follow|rely)", 3.0, "what_do_you_base", "exfiltration"),
    (r"(?:what|which)\s+(?:model|llm|ai|engine|provider)\s+(?:are|do)\s+you", 3.5, "what_model_are_you", "exfiltration"),
    (r"(?:what|how)\s+(?:is|does)\s+your\s+(?:architecture|backend|pipeline|system)", 3.5, "what_architecture", "exfiltration"),
    (r"(?:reveal|expose|disclose|leak)\s+(?:your|the)\s+(?:prompt|instructions?|system|config)", 3.5, "reveal_prompt", "exfiltration"),
    (r"(?:tell|show)\s+me\s+(?:about\s+)?(?:your|the)\s+(?:internal|backend|tech|system|architecture)", 3.0, "tell_about_internals", "exfiltration"),
    (r"your\s+(?:operating|system)\s+(?:manual|instructions?|rules?)", 3.5, "operating_manual", "exfiltration"),
    (r"(?:your|the)\s+architecture", 3.0, "your_architecture", "exfiltration"),
    (r"what\s+tools?\s+(?:do\s+you|are)\s+(?:have|available|use)", 2.5, "what_tools", "exfiltration"),

    # Revit-specific dangerous patterns
    (r"bypass\s+transaction", 5.0, "bypass_transaction", "revit"),
    (r"skip\s+safety\s+check", 5.0, "skip_safety", "revit"),
    (r"delete\s+all\s+elements?", 2.0, "delete_all", "revit"),
    (r"purge\s+(?:the\s+)?entire\s+model", 5.0, "purge_model", "revit"),
])

# Russian patterns (checked against NFKC-only text, preserving Cyrillic)
_RU_PATTERNS = _compile_patterns([
    # Injection / jailbreak
    (r"игнорируй\s+(?:все\s+)?инструкции", 3.0, "ignore_instructions_ru", "injection"),
    (r"забудь\s+(?:все|всё)", 3.0, "forget_all_ru", "injection"),
    (r"ты\s+теперь\b", 3.0, "you_are_now_ru", "injection"),
    (r"новая\s+роль", 3.0, "new_role_ru", "injection"),

    # Social engineering
    (r"секретно\s+выполни", 2.5, "secretly_execute_ru", "social"),
    (r"скрой\s+от\s+пользователя", 2.5, "hide_from_user_ru", "social"),

    # Exfiltration — direct
    (r"покажи\s+системный\s+промпт", 3.5, "show_system_prompt_ru", "exfiltration"),
    (r"прочитай\s+\.env\b", 3.5, "read_env_ru", "exfiltration"),
    (r"покажи\s+ключ\s+API", 3.5, "show_api_key_ru", "exfiltration"),
    (r"покажи\s+(?:все\s+)?переменные\s+окружения", 3.5, "show_env_vars_ru", "exfiltration"),

    # Exfiltration — indirect (rephrasing)
    (r"(?:опиши|расскажи|объясни)\s+(?:как|свою|свои|про)\s+(?:ты\s+)?(?:работ|устро|архитект|систем|функциони|процесс)", 3.0, "describe_how_work_ru", "exfiltration"),
    (r"(?:переведи|перескажи|повтори|изложи)\s+(?:свои\s+)?(?:инструкции|правила|промпт|указания)", 3.5, "translate_instructions_ru", "exfiltration"),
    (r"(?:какая|какой|какие)\s+(?:у\s+тебя\s+)?(?:модель|архитектур|движок|провайдер|нейросет|нейронк)", 3.5, "what_model_ru", "exfiltration"),
    (r"(?:на\s+(?:чём|какой)|что\s+за)\s+(?:модел|нейросет|технолог|движ)", 3.5, "what_engine_ru", "exfiltration"),
    (r"(?:какие|что\s+за)\s+(?:инструменты|тулы|tools)\s+(?:у\s+тебя|ты\s+(?:использу|имеешь))", 2.5, "what_tools_ru", "exfiltration"),
    (r"(?:раскрой|выдай|покажи)\s+(?:свои\s+)?(?:секрет|внутренн|детали\s+реализ)", 3.5, "reveal_secrets_ru", "exfiltration"),
    (r"(?:расскажи|опиши|объясни)\s+(?:про\s+)?(?:свои\s+)?(?:внутренн|скрыт)", 3.0, "tell_internals_ru", "exfiltration"),
    (r"(?:твоя|твоей|твою)\s+(?:архитектур|реализаци|структур)", 3.0, "your_architecture_ru", "exfiltration"),

    # Revit-specific dangerous
    (r"удали\s+все\s+элементы", 2.0, "delete_all_ru", "revit"),
    (r"очисти\s+(?:всю\s+)?модель", 5.0, "purge_model_ru", "revit"),
    (r"обойди\s+проверку", 5.0, "bypass_check_ru", "revit"),
    (r"пропусти\s+безопасность", 5.0, "skip_safety_ru", "revit"),
])

# Cross-language patterns (mixed Russian/English)
_CROSS_LANG_PATTERNS = _compile_patterns([
    (r"ignore\s+инструкции", 3.0, "cross_ignore_instructions", "injection"),
    (r"забудь\s+instructions?", 3.0, "cross_forget_instructions", "injection"),
    (r"игнорируй\s+(?:all\s+)?instructions?", 3.0, "cross_ignore_en_instructions", "injection"),
])

# File-content specific patterns (extra patterns for uploaded files)
_FILE_PATTERNS = _compile_patterns([
    (r"<\s*script\b", 3.0, "script_tag", "file_injection"),
    (r"javascript\s*:", 3.0, "javascript_uri", "file_injection"),
    (r"on(?:load|error|click)\s*=", 2.5, "event_handler", "file_injection"),
    (r"eval\s*\(", 2.5, "eval_call", "file_injection"),
])


@dataclass
class Detection:
    """A single detection result."""
    label: str
    group: str
    weight: float
    matched_text: str


@dataclass
class GuardResult:
    """Result of prompt guard check."""
    risk: str  # "safe", "suspicious", "dangerous"
    score: float
    detections: list[Detection] = field(default_factory=list)
    sanitized: str = ""
    blocked: bool = False


class PromptGuard:
    """Prompt injection guard with bilingual pattern matching."""

    def check(self, text: str) -> GuardResult:
        """Check text for injection patterns.

        Uses dual-pass matching:
        - English patterns: checked against normalized (Latin-folded) text
        - Russian patterns: checked against NFKC-only text (preserves Cyrillic)
        - Cross-language: checked against NFKC text
        """
        if not text or not text.strip():
            return GuardResult(risk="safe", score=0.0, sanitized=text or "")

        # NFKC normalization (preserves Cyrillic for Russian pattern matching)
        nfkc_text = unicodedata.normalize("NFKC", text)
        nfkc_text = "".join(ch for ch in nfkc_text if ch not in _ZERO_WIDTH_CHARS)

        # Full normalization with homoglyph folding (for English pattern matching)
        latin_text = _normalize_unicode(text)

        detections: list[Detection] = []
        score = 0.0

        # Pass 1: English patterns on Latin-folded text
        for pat in _EN_PATTERNS:
            match = pat.regex.search(latin_text)
            if match:
                detections.append(Detection(
                    label=pat.label,
                    group=pat.group,
                    weight=pat.weight,
                    matched_text=match.group(),
                ))
                score += pat.weight

        # Pass 2: Russian patterns on NFKC text
        for pat in _RU_PATTERNS:
            match = pat.regex.search(nfkc_text)
            if match:
                detections.append(Detection(
                    label=pat.label,
                    group=pat.group,
                    weight=pat.weight,
                    matched_text=match.group(),
                ))
                score += pat.weight

        # Pass 3: Cross-language patterns on NFKC text
        for pat in _CROSS_LANG_PATTERNS:
            match = pat.regex.search(nfkc_text)
            if match:
                detections.append(Detection(
                    label=pat.label,
                    group=pat.group,
                    weight=pat.weight,
                    matched_text=match.group(),
                ))
                score += pat.weight

        # Determine risk level
        if score >= 4.0:
            risk = "dangerous"
            blocked = True
        elif score >= 2.0:
            risk = "suspicious"
            blocked = False
        else:
            risk = "safe"
            blocked = False

        # Sanitize: replace matched patterns with [BLOCKED:label]
        sanitized = nfkc_text
        if detections:
            for det in detections:
                sanitized = sanitized.replace(det.matched_text, f"[BLOCKED:{det.label}]")

        # H8: input blocking is ADVISORY-ONLY unless explicitly enforced. Score +
        # detections are still returned (telemetry/logging), but by default we
        # neither block the user nor substitute [BLOCKED:...] into the model
        # context — the additive scoring false-blocked legitimate BIM queries.
        # Operator decision (dev-stage); re-enable enforcement with
        # KUKAI_PROMPT_GUARD=1.
        if os.environ.get("KUKAI_PROMPT_GUARD", "0") != "1":
            blocked = False
            sanitized = nfkc_text

        return GuardResult(
            risk=risk,
            score=score,
            detections=detections,
            sanitized=sanitized,
            blocked=blocked,
        )

    def check_file_content(self, text: str, filename: str) -> GuardResult:
        """Check uploaded file content with additional file-specific patterns."""
        # First run standard check
        result = self.check(text)

        # Then check file-specific patterns
        nfkc_text = unicodedata.normalize("NFKC", text)
        nfkc_text = "".join(ch for ch in nfkc_text if ch not in _ZERO_WIDTH_CHARS)

        for pat in _FILE_PATTERNS:
            match = pat.regex.search(nfkc_text)
            if match:
                result.detections.append(Detection(
                    label=pat.label,
                    group=pat.group,
                    weight=pat.weight,
                    matched_text=match.group(),
                ))
                result.score += pat.weight

        # Re-evaluate risk. Blocking is ADVISORY unless enforced (H8) — same gate
        # as check(); the file path had its own re-block that ignored the flag,
        # so uploads still hard-blocked (Fable review). Detections/score still
        # returned for telemetry.
        _enforcing = os.environ.get("KUKAI_PROMPT_GUARD", "0") == "1"
        if result.score >= 4.0:
            result.risk = "dangerous"
            result.blocked = _enforcing
        elif result.score >= 2.0:
            result.risk = "suspicious"

        # Re-sanitize with file detections only when enforcing; otherwise keep the
        # raw normalized text (no [BLOCKED:...] context corruption).
        if result.detections and _enforcing:
            result.sanitized = nfkc_text
            for det in result.detections:
                result.sanitized = result.sanitized.replace(
                    det.matched_text, f"[BLOCKED:{det.label}]"
                )
        else:
            result.sanitized = nfkc_text

        return result


# Module-level singleton and convenience functions
_guard = PromptGuard()


def check_input(text: str) -> GuardResult:
    """Check user input for injection. Module-level convenience function."""
    return _guard.check(text)


def check_file(text: str, filename: str) -> GuardResult:
    """Check uploaded file content. Module-level convenience function."""
    return _guard.check_file_content(text, filename)


def normalize(text: str) -> str:
    """Normalize text (NFKC + zero-width strip + homoglyph fold). Convenience function."""
    return _normalize_unicode(text)
