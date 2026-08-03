"""System prompt assembly — base + versioned knowledge + model context."""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from kukai.bridge.models import ContextResult
from kukai.knowledge.mode import KnowledgeMode, knowledge_mode

logger = logging.getLogger(__name__)


# --- "is there a how-to to give?" ------------------------------------------
#
# Shared with kukai.llm.client (which asks the same question to decide whether
# the turn must produce an actual image before describing what it "sees").
# Lives here because client imports prompts, never the reverse.

LOOK_MARKERS: tuple[str, ...] = (
    "посмотри", "посмотрите", "взгляни", "глянь", "видишь", "видно ли",
    "как выглядит", "опиши вид", "покажи как выглядит", "оцени визуально",
    "на что похоже", "look at", "what do you see",
)

# Bare acknowledgements/fillers the operator actually sends between real
# instructions ("и", "?", "а щас", "ну"). They carry no task at all, yet each
# one pulled ~10k chars of recipe into the prompt.
_FILLER_MAX_CHARS = 12


def is_look_request(text: str) -> bool:
    """Is the user asking to LOOK at something (rather than to do something)?"""
    if not isinstance(text, str):
        return False
    low = text.strip().lower()
    return any(mark in low for mark in LOOK_MARKERS)


def no_howto_applies(text: str) -> bool:
    """True when a step-by-step recipe cannot help this message.

    Two cases only, both verified against the prod injection log: a request to
    LOOK (the answer comes from an image, not from an API sequence) and a filler
    with no task in it.
    """
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) <= _FILLER_MAX_CHARS and "?" not in stripped[:-1]:
        return True
    return is_look_request(stripped)


# --- Plan 013: layered cacheable prompt assembly --------------------------
#
# The model's system prompt is built from a dozen components of very different
# volatility. Today they are concatenated into a single ``messages[0]`` string,
# so the first per-query byte (Wiki, model context) invalidates the
# provider prompt cache for the WHOLE prefix — and, since the conversation
# history follows, for the whole turn. That re-bills a marathon turn's entire
# context every heartbeat.
#
# A component is tagged STABLE (deploy/session/document-stable → belongs in the
# cacheable ``messages[0]`` prefix) or PER_TURN (per-query/per-turn → belongs in
# a trailing system message AFTER the history, mimicking the four proven
# trailing-message sites already in client.py / chat_ws.py). The split is a pure
# reorder: ``AssembledPrompt.legacy`` reproduces today's byte-exact output, and
# ``stable``/``per_turn`` carry exactly the same component texts, just grouped.
#
# The ONE intentional byte-add (disclosed by design) is the detached
# passport-active-context header in the layered render — see the passport
# component build below. Legacy rendering keeps the passport unsplit so the
# byte-identity guarantee holds with the flag OFF.

STABLE = "stable"      # deploy/session/document-stable → messages[0]
PER_TURN = "per_turn"  # per-query/per-turn → trailing system message

# Header for the detached model-passport active-context tail when it is moved
# into the PER_TURN layer (the tail is separated from its document, so it needs
# a header). Kept here as a literal (mirrors model_passport._active_context's
# "### Активный контекст") to avoid an import cycle / cross-plan file edit.
ACTIVE_CONTEXT_HEADER = "### Активный контекст"


@dataclass
class PromptComponent:
    """One labelled section of the assembled system prompt.

    ``layer`` is STABLE or PER_TURN. ``legacy_text`` lets a component render
    differently in the legacy (unsplit) vs layered (split) paths WITHOUT
    changing content — used only by the passport, whose layered form adds the
    single disclosed detached-section header. When ``legacy_text`` is None the
    component renders identically in both paths.
    """
    name: str
    text: str
    layer: str  # STABLE | PER_TURN
    legacy_text: Optional[str] = None

    def render_legacy(self) -> str:
        return self.text if self.legacy_text is None else self.legacy_text


@dataclass
class AssembledPrompt:
    """An ordered list of prompt components with stable/per-turn projections."""
    components: list[PromptComponent] = field(default_factory=list)

    @property
    def legacy(self) -> str:
        """Original order, byte-identical to the pre-013 single-string prompt.

        Components whose legacy render is empty contribute nothing (matching the
        legacy code, which only ever appended non-empty parts) — this lets the
        passport be modelled as a STABLE core (carrying the full unsplit legacy
        text) plus a PER_TURN active-context component that is legacy-empty.
        """
        return "\n\n".join(
            t for c in self.components if (t := c.render_legacy())
        )

    @property
    def stable(self) -> str:
        """The deploy/session/document-stable cacheable prefix (messages[0])."""
        return "\n\n".join(c.text for c in self.components if c.layer == STABLE)

    @property
    def per_turn(self) -> str:
        """The per-query/per-turn tail (trailing system message after history)."""
        return "\n\n".join(c.text for c in self.components if c.layer == PER_TURN)

    def breakdown(self) -> dict[str, Any]:
        """Per-component token estimate + the stable-prefix churn watchdog hash.

        ``stable_sha1`` MUST NOT change across turns within one session — if it
        does, a per-turn fact leaked into a STABLE component and silently broke
        the cache win (the covenant in plan 013's maintenance notes).
        """
        comps = [
            {
                "name": c.name,
                "chars": len(c.text),
                "est_tokens": len(c.text) // 3,
                "layer": c.layer,
            }
            for c in self.components
        ]
        return {
            "components": comps,
            "stable_chars": len(self.stable),
            "per_turn_chars": len(self.per_turn),
            "stable_sha1": hashlib.sha1(self.stable.encode("utf-8")).hexdigest(),
        }


class PromptAssembler:
    """Build prompts from the immutable Wiki release and live model context."""

    def __init__(self, prompts_dir: Path):
        self._prompts_dir = prompts_dir
        self._cache: dict[str, str] = {}
        self._wiki_router: Optional[Any] = None

    def _load_prompt(self, name: str) -> str:
        """Load a prompt file, with caching."""
        if name in self._cache:
            return self._cache[name]
        path = self._prompts_dir / name
        if not path.exists():
            logger.warning("Prompt file not found: %s", path)
            return ""
        text = path.read_text(encoding="utf-8")
        self._cache[name] = text
        return text

    def _get_wiki_router(self) -> Any:
        """Lazy-load the production Wiki capability router."""
        if self._wiki_router is None:
            try:
                from kukai.rag.wiki_router import get_wiki_router
                self._wiki_router = get_wiki_router()
            except Exception:
                logger.exception("Wiki knowledge router is unavailable")
                self._wiki_router = False  # type: ignore[assignment]
        return self._wiki_router

    def reload(self) -> None:
        """Clear cache to pick up prompt file changes."""
        self._cache.clear()

    def build_system_prompt(
        self,
        context: Optional[ContextResult] = None,
        preferences: Optional[dict[str, Any]] = None,
        units: str = "metric",
        user_message: str = "",
        user_message_original: str = "",
        discovery_context: Optional[dict[str, Any]] = None,
        extension_profile: Optional[str] = None,
        active_extension: Optional[str] = None,
        model_passport: Optional[str] = None,
        skill_prompt: Optional[str] = None,
        skill_name: str = "",
        skip_enrichment: bool = False,
        wiki_frame_future: Optional[Any] = None,
    ) -> str:
        """Assemble the full system prompt (legacy single-string form).

        Thin wrapper over :meth:`build_prompt_components` that renders the
        components in their original order — byte-identical to the pre-plan-013
        output. External callers and tests that expect a single string keep
        using this; the layered (cacheable) path calls
        ``build_prompt_components(...).stable`` / ``.per_turn`` instead.
        """
        return self.build_prompt_components(
            context=context,
            preferences=preferences,
            units=units,
            user_message=user_message,
            user_message_original=user_message_original,
            discovery_context=discovery_context,
            extension_profile=extension_profile,
            active_extension=active_extension,
            model_passport=model_passport,
            skill_prompt=skill_prompt,
            skill_name=skill_name,
            skip_enrichment=skip_enrichment,
            wiki_frame_future=wiki_frame_future,
        ).legacy

    def build_prompt_components(
        self,
        context: Optional[ContextResult] = None,
        preferences: Optional[dict[str, Any]] = None,
        units: str = "metric",
        user_message: str = "",
        user_message_original: str = "",
        discovery_context: Optional[dict[str, Any]] = None,
        extension_profile: Optional[str] = None,
        active_extension: Optional[str] = None,
        model_passport: Optional[str] = None,
        skill_prompt: Optional[str] = None,
        skill_name: str = "",
        skip_enrichment: bool = False,
        wiki_frame_future: Optional[Any] = None,
    ) -> AssembledPrompt:
        """Assemble the system prompt as layered components (plan 013).

        Each section is tagged STABLE (cacheable prefix) or PER_TURN (trailing,
        per-query). ``.legacy`` reproduces today's byte-exact single string;
        ``.stable``/``.per_turn`` are the cacheable split. The ONLY content
        difference between legacy and the split is the single disclosed
        detached passport-active-context header (see the passport build).

        Args:
            context: Current Revit model context (from bridge)
            preferences: User preference dict
            units: "metric" or "imperial"
            user_message: Current message.
            user_message_original: Original user text used by Wiki routing.
            discovery_context: Discovery result dict from bridge with real parameter names
            extension_profile: Profile text from the active extension.
            active_extension: Active Wiki extension catalogue ID.
            model_passport: Pre-formatted Markdown passport of the model (~20K tokens)
            skill_prompt: Detailed skill prompt (~3K tokens) for multi-step workflows
            skill_name: Human-readable skill name for prompt section header
            wiki_frame_future: W1-A (2026-07-10, /root/kukai-rag-audit/
                SPEC_W1A_single_classify.md) — an optional
                ``concurrent.futures.Future`` that will resolve to an
                OperationFrame dict (or None) once client.py's pf2
                IntentClassifier pre-flight task finishes. SAFE new kwarg:
                default None, so every existing caller (and the wiki=off/
                shadow paths below) is byte-identical to before this kwarg
                existed. Only consumed in the wiki-router "on" branch, and
                only when a frame is actually needed — see that branch below.
        """
        parts: list[PromptComponent] = []

        # Detect family-editor mode early — it switches the base prompt AND the
        # Knowledge scope. When True, the prompt becomes laser-focused on
        # family-editor work (geometry creation, FamilyManager, subcategories)
        # and Wiki drops all project-only classes (Wall, Floor, Pipe, Schedule).
        is_family_editor = bool(context and getattr(context, "is_family_editor", False))

        # 1. Base system prompt
        # Phase 1 (revit-coder pilot): load slim orchestrator prompt instead
        # of full system_base.md when USE_REVIT_CODER=1. The orchestrator
        # prompt has no C# rules — those are now revit-coder's responsibility.
        # See docs/superpowers/specs/2026-05-01-revit-coder-integration-design.md
        #
        # Family-editor mode: load the dedicated slim prompt that is ~50%
        # the size of system_base.md and removes irrelevant sections
        # (Schedule/Excel rules, Linked Models, VOR pricing, building norms).
        from kukai.config import USE_REVIT_CODER
        if is_family_editor:
            base_filename = "system_base_family_editor.md"
        elif USE_REVIT_CODER:
            base_filename = "system_base_revit_coder.md"
        elif os.environ.get("KUKAI_TOOL_GUIDANCE_V2", "0") == "1":
            # Declarative-first tool-selection spine (categorical arsenal map):
            # execute_revit_code demoted to explicit last-resort, query_model /
            # apply_revit_write(create_element) surfaced as the front door, stale
            # tool names purged. Default OFF ⇒ base_filename stays system_base.md
            # ⇒ byte-identical legacy prompt. A/B'd against the 30:1 exec-overuse.
            base_filename = "system_base_v2.md"
        else:
            base_filename = "system_base.md"
        base = self._load_prompt(base_filename)
        if base:
            parts.append(PromptComponent("base", base, STABLE))

        # 2. Code generation guidelines (before Wiki so format rules come first)
        # In revit-coder mode: skipped — Gemini doesn't write C# itself.
        # In family-editor mode: skipped — family-editor prompt already carries
        # focused C# rules; project-doc code_generation.md adds noise and
        # references APIs unavailable in family doc.
        if not USE_REVIT_CODER and not is_family_editor:
            code_gen = self._load_prompt("code_generation.md")
            if code_gen:
                parts.append(PromptComponent("code_generation", code_gen, STABLE))

        # 2.2. Plan-in-reasoning + one-script directive (G4) — flag-gated, project
        # path only (where the N-round problem lives). Planning HELPS DeepSeek
        # (do NOT suppress it) — route it to reasoning and collapse N inspect→act
        # round-trips into ONE script, with facts gathered up front.
        if not USE_REVIT_CODER and not is_family_editor:
            try:
                from kukai.config import get_settings as _gs_g4
                _g4_on = _gs_g4().plan_one_script
            except Exception:
                _g4_on = False
            if _g4_on:
                parts.append(PromptComponent("g4_plan", (
                    "## Как выполнять задачи (важно для качества и скорости)\n"
                    "1. СНАЧАЛА продумай весь план в рассуждении (reasoning), а не в ответе "
                    "пользователю — план помогает качеству, не пропускай его.\n"
                    "2. Собери нужные факты ЗАРАНЕЕ: имена типов/параметров бери из паспорта "
                    "модели; для поиска/фильтра/подсчёта элементов вызывай `query_model` "
                    "(НЕ пиши discovery-C#).\n"
                    "3. Затем выполни задачу ОДНИМ полным скриптом `execute_revit_code`, "
                    "объединив ВСЕ шаги в один проход — не дроби на серию "
                    "«осмотр→действие→осмотр».\n"
                    "4. Отдельные раунды — только если результат шага реально нельзя "
                    "предсказать заранее."
                ), STABLE))

        # 2.5. Extension profile (before Wiki so its thinking framework comes first)
        # Cap at 3000 chars (~1000 tokens) to prevent prompt bloat
        if extension_profile:
            capped = extension_profile[:3000] if len(extension_profile) > 3000 else extension_profile
            parts.append(PromptComponent(
                "extension_profile", f"## Профиль специализации\n\n{capped}", STABLE,
            ))

        # Query-relevant extension entries used to be reachable only through
        # the retired vector index. Route them deterministically from the same
        # immutable release so all 185 curated entries remain available in
        # production without an embedding call or a broad context dump.
        if active_extension and (user_message_original or user_message):
            try:
                from kukai.knowledge.extensions import get_extension_context

                extension_context = get_extension_context(
                    active_extension,
                    user_message_original or user_message,
                )
                if extension_context:
                    parts.append(PromptComponent(
                        "extension_knowledge", extension_context, PER_TURN,
                    ))
            except Exception:
                logger.exception(
                    "Versioned extension routing failed for %s", active_extension,
                )

        # 2.6. Skill prompt (detailed workflow instructions for multi-step tasks, ~3000 tokens)
        # Skills are larger than extension profiles and contain full step-by-step workflows.
        if skill_prompt:
            capped = skill_prompt[:10000] if len(skill_prompt) > 10000 else skill_prompt
            parts.append(PromptComponent(
                "skill", f"## Активный навык: {skill_name}\n\n{capped}", STABLE,
            ))

        # 3. Revit knowledge. Wiki is the only automatic corpus. Normative
        # clauses are fetched only through the explicit ``lookup_norm`` tool;
        # prompt assembly never loads norm/API embeddings or a vector database.
        knowledge_context = ""
        _knowledge_mode = knowledge_mode()
        _knowledge_query = user_message_original or user_message
        _revit_version = (
            getattr(context.document, "revit_version", None) if context else None
        )
        _should_enrich = bool(_knowledge_query) and not skip_enrichment

        if _should_enrich and _knowledge_mode is KnowledgeMode.WIKI:
            try:
                router = self._get_wiki_router()
                if router and router is not False:
                    # Reuse the classifier already launched by the request
                    # pre-flight.  If it is absent/late, deterministic evidence
                    # routing is used; Wiki never starts a second hidden LLM call.
                    frame = None
                    if wiki_frame_future is not None:
                        try:
                            wait_s = max(0.0, min(
                                float(os.environ.get("KUKAI_WIKI_FRAME_WAIT_SECONDS", "6.0")),
                                6.0,
                            ))
                            frame = wiki_frame_future.result(timeout=wait_s)
                        except Exception:
                            frame = None
                    knowledge_context, telemetry = router.inject(
                        _knowledge_query,
                        revit_version=_revit_version,
                        frame=frame,
                        skip_llm_fallback=True,
                    )
                    # A recipe is a HOW-TO. When the user is not asking how to do
                    # anything, routing still returns its best-scoring page and
                    # ~10k chars ride in front of EVERY round of the turn.
                    # Measured on prod 2026-07-20..27: 188 injections, 758 377
                    # chars across 70 logged turns (avg 10 833). What it shipped:
                    # "и" → 10 995 chars on suppressing commit warnings; "?" →
                    # cable-tray sizing; "посмотри на модель, какая форма здания"
                    # → 11 148 chars on searching folders for IFC files; "а опиши
                    # что на кровле видишь" → cable-tray sizing again. The cause
                    # is upstream: the frame classifier labels these action=
                    # set_param / intent=modify, and the router then honestly
                    # returns the best set_param page in the corpus.
                    #
                    # Deliberately NOT gated on route_type. Measured: with a
                    # frame carrying domain=null NO page can earn the domain
                    # bonus, so every query degrades to relaxed_action — that
                    # tier holds the good hits too ("сколько стен по типам" →
                    # counting-elements). Gate on what is knowable here instead:
                    # whether a how-to can apply to this question at all.
                    if knowledge_context and no_howto_applies(_knowledge_query):
                        logger.info(
                            "WIKI_KNOWLEDGE dropped: pages=%s chars=%d "
                            "(look/trivial query — a recipe cannot apply)",
                            telemetry.get("routed_pages"), len(knowledge_context),
                        )
                        knowledge_context = ""
                    # KIR frame shadow (KUKAI_KIR_TOOL=shadow, default off):
                    # once-per-turn applicability probe, ABSOLUTE fail-open.
                    try:
                        from kukai.ir import shadow as _kir_shadow
                        _kir_shadow.observe_frame(
                            telemetry.get("frame") or frame,
                            user_query=_knowledge_query,
                            revit_version=_revit_version)
                    except Exception:  # noqa: BLE001 — never touches the turn
                        logger.debug("KIR frame shadow skipped", exc_info=True)
                    if knowledge_context:
                        logger.info(
                            "WIKI_KNOWLEDGE release=%s route=%s pages=%s recipe=%s "
                            "chars=%d latency_ms=%s frame=%s",
                            telemetry.get("release_id"), telemetry.get("route_type"),
                            telemetry.get("routed_pages"), telemetry.get("first_recipe"),
                            len(knowledge_context), telemetry.get("latency_ms"),
                            telemetry.get("frame_source"),
                        )
                    else:
                        logger.warning(
                            "WIKI_KNOWLEDGE empty; no legacy fallback: %s", telemetry,
                        )
            except Exception:
                # Startup validates the release, so this indicates a per-turn
                # software fault.  Preserve provenance: never switch to old RAG.
                logger.exception("Wiki knowledge injection failed; no legacy fallback")

        # Knowledge is per-query and therefore appended at the end so stable
        # prompt sections retain a long provider-cacheable prefix.

        # 4. Dynamic model context
        if context:
            # PER_TURN: model context (current view/selection/warnings) changes
            # every turn — it must not sit in the cacheable prefix.
            parts.append(PromptComponent(
                "model_context", self._format_context(context), PER_TURN,
            ))
            # Inject explicit Revit version guidance for code generation.
            # STABLE: the project's Revit version + API-NOTES are document-stable.
            ver = context.document.revit_version
            if ver:
                _vblock = (
                    f"## Версия Revit: {ver}\n"
                    f"- Используй API, совместимый с Revit {ver}\n"
                    f"- Если API изменился между версиями, выбирай вариант для {ver}"
                )
                _notes = self._api_notes(ver)
                if _notes:
                    _vblock += "\n\n" + _notes
                parts.append(PromptComponent("version_api_notes", _vblock, STABLE))

        # 4.5. Discovery context (real parameter names from Revit) — PER_TURN.
        if discovery_context:
            parts.append(PromptComponent(
                "discovery", self._format_discovery(discovery_context), PER_TURN,
            ))

        # 4.6. Model Passport (rich structured context ~20K tokens).
        # The passport body is document-stable EXCEPT its trailing "### Активный
        # контекст" section (current view + selection), which changes per turn.
        # Plan 013 splits it: the stable core stays in the cacheable prefix; the
        # volatile active-context tail moves to the PER_TURN trailing message.
        # The split is the ONE place layered output differs from legacy — by a
        # single disclosed detached-section header — so the core component
        # carries the full UNSPLIT passport as its legacy_text (byte-identity),
        # and the active-context component is legacy-empty.
        if model_passport:
            _passport_preamble = (
                "## Паспорт модели\n"
                "Используй эту информацию для генерации точного кода с первого раза.\n"
                "Если пользователь упоминает элементы, параметры или типы — "
                "проверь паспорт ПЕРЕД вызовом инструментов.\n\n"
                "---\n"
            )
            _full_passport = _passport_preamble + model_passport
            _idx = model_passport.rfind(ACTIVE_CONTEXT_HEADER)
            if _idx > 0:
                _core = model_passport[:_idx].rstrip()
                _tail = model_passport[_idx:]
                # STABLE core; legacy_text reproduces the full unsplit passport.
                parts.append(PromptComponent(
                    "passport_core", _passport_preamble + _core, STABLE,
                    legacy_text=_full_passport,
                ))
                # PER_TURN detached active context (needs its own header since it
                # is separated from the passport document). Legacy-empty: its
                # content already lives inside passport_core's legacy_text.
                parts.append(PromptComponent(
                    "passport_active",
                    "## Паспорт: активный контекст\n" + _tail,
                    PER_TURN,
                    legacy_text="",
                ))
            else:
                parts.append(PromptComponent("passport", _full_passport, STABLE))

        # 5. User preferences (stable)
        if preferences:
            parts.append(PromptComponent(
                "preferences", self._format_preferences(preferences, units), STABLE,
            ))

        # 6. Per-turn Wiki knowledge. A route miss stays empty; there is no
        # generic static dump and no fallback corpus with different provenance.
        if knowledge_context:
            parts.append(PromptComponent("wiki_knowledge", knowledge_context, PER_TURN))

        return AssembledPrompt(components=parts)

    def _api_notes(self, revit_version: Any) -> str:
        """Authoritative version-divergence API notes (G2) — front-loads the
        cross-version traps that cause most first-shot compile failures (F2/F5).
        Shows ONLY the rule for the project's version, not all of them.
        """
        try:
            y = int(str(revit_version)[:4])
        except (ValueError, TypeError):
            return ""
        if not y:
            return ""
        L = [f"## API-NOTES для Revit {y} (частые версионные ошибки — соблюдай ТОЧНО):"]
        # ElementId numeric accessor (audit F2/F5 — the #1 drift)
        if y <= 2023:
            L.append(f"- ElementId → `id.IntegerValue` (int). НЕ `id.Value` — это 2024+, на {y} даёт CS1061.")
        elif y >= 2026:
            L.append("- ElementId → `id.Value` (long). `IntegerValue` УДАЛЁН в 2026 (CS1061).")
        else:  # 2024–2025
            L.append("- ElementId → `id.Value` (long). `IntegerValue` ещё работает, но устарел.")
        # Units API
        if y == 2021:
            L.append("- Revit 2021 уже использует Forge units API: `UnitTypeId.*`, "
                     "`Definition.GetSpecTypeId()` и `Parameter.GetUnitTypeId()`. "
                     "`Definition.GetDataType()` появится только в 2022; "
                     "не откатывай новый код на `DisplayUnitType`.")
        else:
            L.append("- Единицы → ForgeTypeId: `UnitTypeId.*`, `SpecTypeId.*` (`DisplayUnitType` удалён в 2022).")
            L.append("- Тип/единица параметра: `Definition.GetDataType()` (ForgeTypeId). "
                     "`Definition.ParameterType` и `InternalDefinition.UnitType` УДАЛЕНЫ в 2022+ (CS1061).")
        # Toposolid
        if y <= 2023:
            L.append(f"- `Toposolid` НЕ существует в {y} (это 2024+) → используй `TopographySurface`.")
        # Anti-patterns observed live on real compound-write tasks (2026-06-06).
        # Version-independent; prevent at generation time.
        L.append("Частые галлюцинации API — НЕ делай так:")
        L.append("- Кастомные/общие параметры (ADSK_*, АХ_*, Ш_*, ЭФ_*, имена с пробелами/кириллицей) — это "
                 "НЕ `BuiltInParameter`. `BuiltInParameter.ADSK_...` НЕ существует (CS0117). Получи ВСЕ "
                 "совпадения через `el.GetParameters(\"ADSK_Размер_Длина\")` и пиши только при `Count == 1`; "
                 "`LookupParameter` зависит от локали/порядка и может выбрать чужой одноимённый параметр. "
                 "`BuiltInParameter.*` — только для штатных параметров Revit.")
        L.append("- Цель МУТАЦИИ существующего элемента должна иметь provenance: текущее выделение, "
                 "явный ElementId/уникальное имя из запроса или единственный подходящий кандидат. "
                 "Никогда не подменяй отсутствующую цель первым элементом коллектора "
                 "(`FirstElement`/слепой `FirstOrDefault`); при неоднозначности верни понятный отказ.")
        L.append("- Нет `doc.ProjectParameters` (CS1061). Параметры проекта и их привязки — через "
                 "`doc.ParameterBindings` (BindingMap; итератор `DefinitionBindingMapIterator`).")
        L.append("- ОТКРЫТЬ/показать вид пользователю: `uidoc.ActiveView = view` (или "
                 "`uidoc.RequestViewChange(view)`). `doc.ActiveView` НЕ выносит вид на экран (это DB-уровень) "
                 "— пользователь его не увидит.")
        # M4 — top first-shot compile offenders observed live (study 2026-06-07):
        # curated, model-agnostic C# hygiene that cut the CS-error/repair storms.
        L.append("- BuiltInCategory: НЕ выдумывай OST_*. НЕТ OST_Boilers / OST_Fans / "
                 "OST_HeatingDevices / OST_Pumps / OST_AirTerminals (CS0117). Мех.оборудование → "
                 "OST_MechanicalEquipment; сантехника → OST_PlumbingFixtures; воздуховоды → "
                 "OST_DuctCurves; трубы → OST_PipeCurves. Сомневаешься в имени enum — query_model/паспорт.")
        L.append("- `doc` и `uidoc` УЖЕ переданы в Execute(doc, uidoc). НЕ объявляй их заново "
                 "(`var doc = ...`) — это CS0136. Используй напрямую.")
        L.append("- Неоднозначность типов (CS0104): пиши ПОЛНОЕ имя `Autodesk.Revit.DB.Group`, "
                 "`Autodesk.Revit.DB.Color` — иначе конфликт с System.* (напр. Regex.Group).")
        L.append("- Room/RoomTag/Area — namespace `Autodesk.Revit.DB.Architecture`; Space — `.Mechanical`. "
                 "Без using → CS0246. Надёжнее собирать по категории (OST_Rooms) через FilteredElementCollector.")
        # Steer to the reliable discovery path
        L.append("- Не уверен в члене API/имени типа для этой версии — вызови `query_model` "
                 "(или сверься с паспортом), не угадывай.")
        return "\n".join(L)

    def _format_context(self, ctx: ContextResult) -> str:
        """Format model context into a prompt section."""
        # FAMILY EDITOR MODE — different shape: no project categories/levels/views.
        # The active doc IS a family doc; use FamilyCreate.* / FamilyManager.* APIs.
        if ctx.is_family_editor:
            lines = ["## Family Editor Context (ACTIVE)"]
            lines.append(
                "**`is_family_editor: true`** — Active document is a FAMILY (.rfa). "
                "Apply the **Family Editor Mode** rules from the system prompt."
            )
            lines.append(f"- Document: {ctx.document.name}")
            lines.append(f"- Revit version: {ctx.document.revit_version}")
            if ctx.family_category:
                lines.append(f"- Family category: {ctx.family_category}")
            if ctx.family_parameters:
                params_str = ", ".join(ctx.family_parameters[:50])
                lines.append(f"- Existing family parameters ({len(ctx.family_parameters)}): {params_str}")
            else:
                lines.append("- Existing family parameters: (none)")
            if ctx.family_reference_planes:
                planes_str = ", ".join(f'"{p}"' for p in ctx.family_reference_planes[:20])
                lines.append(f"- Existing reference planes ({len(ctx.family_reference_planes)}): {planes_str}")
            else:
                lines.append('- Existing reference planes: (none — fall back to Plane.CreateByNormalAndOrigin)')
            lines.append(f"- Units: {ctx.units}")
            lines.append(
                "\n**Reminder:** in this mode use `doc.FamilyCreate.NewExtrusion/NewBlend/...`, "
                "`doc.FamilyManager.AddParameter/NewType/Set`, `SketchPlane.Create(doc, plane)`. "
                "Do NOT use `doc.Create.NewWall/NewFamilyInstance` — those throw in family doc."
            )
            return "\n".join(lines)

        # PROJECT DOC — standard context block.
        lines = ["## Current Revit Model Context"]
        lines.append(f"- Document: {ctx.document.name}")
        lines.append(f"- Revit version: {ctx.document.revit_version}")

        if ctx.categories:
            lines.append("\n### Element Categories:")
            for cat in ctx.categories:
                lines.append(f"- {cat.name_ru} ({cat.name}): {cat.count} elements [BuiltInCategory.{cat.builtin}]")

        if ctx.levels:
            lines.append("\n### Levels:")
            for lvl in ctx.levels:
                lines.append(f"- {lvl.name}: elevation {lvl.elevation_m}m (ElementId: {lvl.id})")

        lines.append(f"\n### Current View: {ctx.current_view.name} ({ctx.current_view.type})")

        if ctx.selection.count > 0:
            lines.append(f"### Selected Elements: {ctx.selection.count} elements")
            lines.append(f"  - IDs: {ctx.selection.element_ids}")
            lines.append(f"  - Categories: {', '.join(ctx.selection.categories)}")

        lines.append(f"\n### Phase: {ctx.phase.name}")
        lines.append(f"### Units: {ctx.units}")
        # [rc6] warnings_count == -1 means "not collected at connect" (the
        # client no longer runs doc.GetWarnings() on the UI thread — it froze
        # Revit for minutes on heavy models). Omit the line rather than show
        # a lying 0/-1; the model_vitals probe fetches the real count on demand.
        if ctx.warnings_count >= 0:
            lines.append(f"### Warnings: {ctx.warnings_count}")

        return "\n".join(lines)

    def _format_discovery(self, discovery: dict[str, Any]) -> str:
        """Format discovered parameters into a prompt section."""
        category = discovery.get("category", "Unknown")
        params = discovery.get("parameters", [])
        if not params:
            return ""
        lines = [f"## Discovered Parameters for {category}"]
        lines.append("These are REAL parameter names from the current Revit model. Use them exactly as shown:")
        for p in params[:50]:  # Limit to 50 params
            name = p.get("name", "")
            storage_type = p.get("storage_type", p.get("type", ""))
            lines.append(f"- {name} ({storage_type})")
        return "\n".join(lines)

    def _format_preferences(self, prefs: dict[str, Any], units: str) -> str:
        """Format user preferences into a prompt section."""
        style = prefs.get("ai_style", "pragmatic")
        style_map = {
            "teaching": (
                "TEACHING MODE: Explain your reasoning step by step, like a mentor teaching a junior engineer. "
                "Show WHY, not just WHAT. Use numbered steps and concrete examples from Revit. "
                "If you execute code, explain what it does before and after. Do NOT use emoji."
            ),
            "pragmatic": (
                "PRAGMATIC MODE: Be concise and direct. No introductions, no filler. "
                "Give the result first, details only if asked. Short sentences. "
                "Maximum efficiency — the user is busy. Do NOT use emoji."
            ),
            "friendly": (
                "FRIENDLY MODE: Be warm, conversational and encouraging. "
                "Use simple language, explain complex things in everyday terms. "
                "Celebrate successes ('Отлично!', 'Готово!'). You may use emoji to be friendly 😊. "
                "Make the user feel supported."
            ),
            "expert": (
                "EXPERT MODE: Assume the user is a senior BIM engineer. "
                "Use precise technical terminology (BuiltInCategory, Family, Type, Instance). "
                "Reference specific Revit API concepts when relevant. Skip basic explanations. "
                "Be thorough and technically precise. Do NOT use emoji."
            ),
        }
        safety = prefs.get("safety_level", "normal")

        lines = ["## User Preferences"]
        lines.append(f"- Communication style: {style_map.get(style, style_map['pragmatic'])}")
        lines.append(f"- Units: {'Metric (mm, m, m\u00b2, m\u00b3)' if units == 'metric' else 'Imperial (feet, inches)'}")
        lines.append(f"- Safety level: {safety}")

        return "\n".join(lines)
