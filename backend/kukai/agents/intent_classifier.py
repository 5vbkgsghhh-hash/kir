"""IntentClassifier — pre-flight tagging of user queries.

Runs first in the pre-flight parallel stage (alongside QueryReformulator and
RagReranker). Tags each query with structured metadata used by every
downstream agent:

  intent             — what the user wants to DO (11-way enum)
  complexity         — how hard the code is likely to be (5-way enum)
  domain             — which Revit discipline (7-way enum)
  primary_class_hint — best-guess principal API class (string|null)
  should_emit_code   — whether to run the code generator at all (bool)
  entities           — concrete things mentioned in the query (list)
  action             — OperationFrame verb (closed vocab, ADDITIVE + finer
                       than intent — see Stage 2 below)
  object_kinds       — OperationFrame object kinds this action targets
                       (closed vocab, list, 0+)
  capability_domain  — OperationFrame's capability-TOPIC domain (closed
                       16-way vocab, ADDITIVE, string|null — see "Stage 2b"
                       below; NOT a replacement for `domain` above)

The reranker uses (intent, domain, primary_class_hint) to bias top-5
selection; the code critic uses (intent, complexity) to scale how strict
to be; the orchestrator uses ``should_emit_code`` to short-circuit
conversational / vague queries before they ever hit RAG.

Capability-first RAG, Stage 2 (/root/kukai-rag-audit/CAPABILITY_FIRST_RAG.md
§2, §5, §6 step 2): ``action``/``object_kinds`` together are the
"OperationFrame" — the normalized (verb, object) pair that
``kukai.rag.retrieval``'s capability-resolve stage
(``KUKAI_RAG_CAPABILITY_RESOLVE``, default OFF) resolves against the
per-recipe ``capability`` signature in ``data/revit_api_db.json`` (Stage 1,
CAPABILITY_CATALOG.md). This is a STRUCTURAL lookup layered on top of the
existing intent (11-way, coarser) — it does not replace intent/complexity/
domain, which downstream routing/masking still consumes unchanged.

``action`` is a closed 28-verb vocabulary and ``object_kinds`` a closed
20-kind vocabulary — both read PROGRAMMATICALLY from the live corpus by
``kukai.agents.capability_vocab`` (never hardcoded here; a hardcoded list
would silently go stale the next time the catalog gains/renames an action).
Fail-open: if the LLM omits ``action`` (or returns one outside the closed
vocab), it is DERIVED from the already-validated ``intent`` via
``capability_vocab.derive_action_from_intent`` — this classifier must never
raise just because the newer, additive field is missing or wrong; the
established 5 fields keep working exactly as before.

Stage 2b (ADDITIVE, /root/kukai-rag-audit/ROUTER_CONTRACT_FIX_REPORT.md):
``capability_domain`` is a closed 16-way vocabulary — the capability-TOPIC
domain the Capability→Page Router (``/root/kukai-wiki/nav/capability_router.py``)
indexes wiki pages on (``architecture/mep/qc/views/sheets/annotation/
graphics/families/structure/data/geometry/coordination/worksharing/
electrical/site/general`` — read live from the same corpus via
``capability_vocab.capability_domain_vocab``). This is DISTINCT from the
7-way ``domain`` field above (Revit DISCIPLINE: ARCH/STR/MEP/VIEW/PROJECT/
FAMILY/OTHER) — the router's diagnosed gap was precisely that its exact/
relaxed-domain tiers could never fire off the 7-way field, since the two
vocabularies don't even share most values. `capability_domain` does NOT
replace `domain`; both are emitted and both are validated independently.
Fail-open, same discipline as `action`/`object_kinds`: a missing or
out-of-vocab `capability_domain` becomes ``None`` (never crash, and
NEVER lossily remapped from the 7-way `domain` — a remap was measured to
make routing accuracy WORSE, see the report §2 supplementary finding).

Output JSON contract (see prompts/intent_classifier.md):
  {
    "intent": "create|modify|filter|count|list|delete|schedule|tag|export|diagnose|converse",
    "complexity": "trivial|simple|composite|hard|vague",
    "domain": "ARCH|STR|MEP|VIEW|PROJECT|FAMILY|OTHER",
    "primary_class_hint": "<string|null>",
    "should_emit_code": <true|false>,
    "entities": [{"type": "<string>", "value": "<string>"}, ...],
    "action": "<closed-vocab verb>",
    "object_kinds": ["<closed-vocab kind>", ...],
    "capability_domain": "<closed-16way-vocab|null>"
  }
"""
from __future__ import annotations

from typing import Any

from .base import AgentBase, parse_json_block
from .capability_vocab import (
    action_vocab as _action_vocab,
    capability_domain_vocab as _capability_domain_vocab,
    derive_action_from_intent,
    object_kind_vocab as _object_kind_vocab,
)


_VALID_INTENTS = frozenset({
    "create", "modify", "filter", "count", "list",
    "delete", "schedule", "tag", "export", "diagnose", "converse",
})
_VALID_COMPLEXITY = frozenset({
    "trivial", "simple", "composite", "hard", "vague",
})
_VALID_DOMAINS = frozenset({
    "ARCH", "STR", "MEP", "VIEW", "PROJECT", "FAMILY", "OTHER",
})

_MAX_ENTITIES = 5
_MAX_OBJECT_KINDS = 6
_QUERY_MAX_CHARS = 800


class IntentClassifier(AgentBase):
    """Classify a user query into structured intent / complexity / domain metadata."""

    name = "intent_classifier"
    model = "gemini-3.5-flash"
    thinking_level = "medium"
    max_tokens = 64000  # no cap per Token budget policy
    timeout_s = 6.0     # pre-flight stage; must be fast
    prompt_file = "intent_classifier"

    def build_user_message(self, query: str) -> str:
        """Pass through the (trimmed) raw query — the prompt has all the structure."""
        return (query or "")[:_QUERY_MAX_CHARS].strip()

    def parse_response(self, text: str) -> dict[str, Any]:
        data = parse_json_block(text)
        if not isinstance(data, dict):
            raise ValueError(f"expected JSON object, got: {type(data).__name__}")

        intent = data.get("intent")
        if intent not in _VALID_INTENTS:
            raise ValueError(
                f"invalid intent {intent!r}; expected one of {sorted(_VALID_INTENTS)}"
            )

        complexity = data.get("complexity")
        if complexity not in _VALID_COMPLEXITY:
            raise ValueError(
                f"invalid complexity {complexity!r}; expected one of "
                f"{sorted(_VALID_COMPLEXITY)}"
            )

        domain = data.get("domain")
        if domain not in _VALID_DOMAINS:
            raise ValueError(
                f"invalid domain {domain!r}; expected one of {sorted(_VALID_DOMAINS)}"
            )

        primary_class_hint = data.get("primary_class_hint", None)
        if primary_class_hint is not None and not isinstance(primary_class_hint, str):
            raise ValueError(
                f"primary_class_hint must be string or null: {primary_class_hint!r}"
            )

        should_emit_code = data.get("should_emit_code", True)
        if not isinstance(should_emit_code, bool):
            raise ValueError(
                f"should_emit_code must be a JSON boolean: {should_emit_code!r}"
            )

        raw_entities = data.get("entities", []) or []
        if not isinstance(raw_entities, list):
            raise ValueError(f"entities must be a list: {raw_entities!r}")

        entities: list[dict[str, str]] = []
        for ent in raw_entities[:_MAX_ENTITIES]:
            if not isinstance(ent, dict):
                continue
            etype = ent.get("type")
            evalue = ent.get("value")
            if etype is None or evalue is None:
                continue
            entities.append({"type": str(etype), "value": str(evalue)})

        # OperationFrame (Stage 2, ADDITIVE + finer than `intent`): `action`
        # is a closed verb vocab, `object_kinds` a closed noun vocab, both
        # read live from the corpus (kukai.agents.capability_vocab). Neither
        # ever raises — a missing/invalid `action` is DERIVED from the
        # already-validated `intent` (fail-open, per the brief); an invalid
        # `object_kinds` entry is silently dropped rather than rejecting the
        # whole classification over a newer, additive field.
        raw_action = data.get("action")
        action = (
            raw_action.strip().lower()
            if isinstance(raw_action, str) and raw_action.strip()
            else ""
        )
        if action not in _action_vocab():
            action = derive_action_from_intent(intent)

        raw_object_kinds = data.get("object_kinds", []) or []
        if not isinstance(raw_object_kinds, list):
            raw_object_kinds = []
        valid_kinds = _object_kind_vocab()
        object_kinds: list[str] = []
        for kind in raw_object_kinds[:_MAX_OBJECT_KINDS]:
            if not isinstance(kind, str):
                continue
            kind_l = kind.strip().lower()
            if kind_l and kind_l in valid_kinds and kind_l not in object_kinds:
                object_kinds.append(kind_l)

        # capability_domain (Stage 2b, ADDITIVE): the 16-way capability-TOPIC
        # domain the router indexes on — see module docstring. Fail-open by
        # design: missing/blank/out-of-vocab -> None, NEVER raises, and NEVER
        # derived/remapped from the 7-way `domain` above (a remap was
        # measured to make routing WORSE — the classifier must emit this
        # natively or not at all). `object_kinds` and `capability_domain`
        # remain independently useful even when only one is present, per the
        # router's own domain-agnostic object-kind tier.
        raw_capability_domain = data.get("capability_domain")
        capability_domain: str | None = None
        if isinstance(raw_capability_domain, str):
            cd = raw_capability_domain.strip().lower()
            if cd and cd in _capability_domain_vocab():
                capability_domain = cd

        return {
            "intent": intent,
            "complexity": complexity,
            "domain": domain,
            "primary_class_hint": primary_class_hint,
            "should_emit_code": should_emit_code,
            "entities": entities,
            "action": action,
            "object_kinds": object_kinds,
            "capability_domain": capability_domain,
        }
