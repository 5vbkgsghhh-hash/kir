"""LLM transport: provider pinning, fallback chains, ProviderChain rotation
(extracted from client.py).

Pure relocation (2026-07-04 client.py decomposition, Step 3): every body below
was moved byte-identical from its former ``kukai/llm/client.py`` definition —
including the first parameter, deliberately still named ``self``: it is the
``LLMClient`` instance, and ``LLMClient`` rebinds each function as a plain
class attribute so they remain the SAME (un)bound methods for callers, tests,
and instance-level stubbing.

Post-relocation hardening (2026-07-04, F1+F2): ``_get_provider_chain`` and
``_call_llm_with_provider_chain`` were amended — the rotation loop now records
outcomes through ``chain.begin_request()`` (request-fault vs provider-fault
attribution, F1) and passes response durations into ``record_success`` (per-
provider SLOW demotion, F2). See ``kukai/llm/provider_chain.py`` module
docstring for the design. Everything else remains as relocated. ALL transport state stays ON the client instance exactly as before
(``self._circuit_breaker``, ``self._provider_chain``, ``self._fallback_*``,
``self._antigravity_*``, ``self._google_*``, ``self._timeout``); this module
owns no mutable state. The ``_OR_PROVIDER`` pin lives here and is rebound as
the ``LLMClient._OR_PROVIDER`` class attribute (same dict object).

The semaphore wrapper ``_call_llm_with_fallback`` stays on ``LLMClient`` — it
is the seam tests stub. ``_litellm_response`` / ``_get_streaming_response``
also stay on the client: they are request assembly, not transport.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, AsyncIterator, Callable, Optional

import litellm

from kukai import audit_trace

logger = logging.getLogger(__name__)


class _GeminiFallbackIterator:
    """Async iterator that wraps Gemini stream and falls back to litellm on error.

    If the Gemini stream raises an exception (rate limit, timeout, etc.),
    transparently switches to the litellm fallback without the caller knowing.
    """

    def __init__(self, gemini_iter: AsyncIterator, fallback_fn: Callable, on_fallback: Optional[Callable] = None):
        self._gemini_iter = gemini_iter
        self._fallback_fn = fallback_fn
        self._fallback_iter: Optional[AsyncIterator] = None
        self._switched = False
        self._yielded_count = 0  # Track how many chunks we've yielded from Gemini
        self._on_fallback = on_fallback  # Called when switching to fallback

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._switched and self._fallback_iter is not None:
            return await self._fallback_iter.__anext__()

        try:
            chunk = await self._gemini_iter.__anext__()
            self._yielded_count += 1
            return chunk
        except StopAsyncIteration:
            raise
        except Exception as e:
            if self._switched:
                raise  # Already on fallback, propagate error
            self._switched = True
            if self._on_fallback:
                self._on_fallback()
            # Only fallback if no chunks were yielded yet (avoid duplicate text)
            if self._yielded_count > 0:
                logger.warning("Gemini failed mid-stream after %d chunks (%s), cannot fallback safely", self._yielded_count, e)
                raise  # Let stream_chat's error handler deal with it
            logger.warning("Gemini failed before first chunk (%s), switching to OpenRouter", e)
            self._fallback_iter = await self._fallback_fn()
            return await self._fallback_iter.__anext__()


# Reliable OpenRouter providers for deepseek-v4-flash. allow_fallbacks=False
# is REQUIRED — with True, OpenRouter still routed ~90% to Baidu (Chinese/
# null/length-truncated garbage). Pinned on EVERY openrouter call.
# 2026-07-06: after a fleet-wide 429 storm on deepseek-v4-flash. Root cause was
# DeepInfra stuck in a false DOWN (chain quarantine) → Fireworks became the first
# live leg → 429. Fresh restart clears the false DOWN; DeepInfra first serves fine.
# Added Novita (historically served real KUKAI turns). Kept ONLY providers proven
# to accept our FULL request shape (17 tools + 65k max_tokens + thinking params);
# newer resellers (AtlasCloud/Baidu/Alibaba) 400 "invalid request params" on the
# real request despite passing a toy probe — excluded. Fireworks last (429-prone
# but format-OK, emergency only). Model LOCKED to deepseek-v4-flash per operator —
# this fixes ROUTING, not the model.
_OR_PROVIDER = {"order": ["DeepInfra", "Novita", "Parasail", "GMICloud",
                          "Fireworks"], "allow_fallbacks": False}


def provider_for_openrouter_model(model: str, deepseek_pool: dict[str, Any]) -> dict[str, Any]:
    """The provider pin for an openrouter model. Model-aware (2026-07-07): deepseek
    uses its proven DeepInfra pool; other models (xiaomi/mimo-v2.5) use their native
    endpoint (Xiaomi). Pinning deepseek's providers on a non-deepseek model 404s
    "No endpoints found" — this is the single source of truth for that mapping."""
    if "deepseek" in str(model):
        return deepseek_pool
    # qwen3.x: served by ONE provider (Alibaba, checked against the endpoints API
    # 2026-07-29). The MiMo pool below with allow_fallbacks=False would 404 every
    # call with "No endpoints found" — the exact failure this function's docstring
    # warns about, in the other direction. Fallbacks stay ON because a single
    # endpoint has no rotation to fall back to inside the pin.
    if "qwen" in str(model):
        return {"order": ["Alibaba"], "allow_fallbacks": True}
    # xiaomi/mimo-v2.5: exclude Xiaomi (441-blocks our account, 2026-07-12) AND
    # DeepInfra ($2/Mtok output + ~20 tps slow-stream, dropped 2026-07-12). Rotate
    # over the cheap $0.28/Mtok endpoints whose health flaps: DigitalOcean →
    # Parasail → Venice. Aux calls must keep max_tokens <= 16384 (DigitalOcean ctx
    # 32000) or that endpoint is filtered out; aux calls are short + non-fatal.
    return {"order": ["DigitalOcean", "Parasail", "Venice"], "allow_fallbacks": False}


def _reasoning_max_tokens() -> int | None:
    """KUKAI_LLM_REASONING_MAX_TOKENS (default 8000): cap reasoning-model
    thinking via OpenRouter's unified `reasoning.max_tokens` control. Root
    cause of the 2026-07-18 "агент не отвечает" incident: MiMo v2.5 reasons
    60–211s unbounded on the heavy system prompt while the OpenRouter API
    itself answers in ~1s. 0 or negative disables the cap. Read per call
    (same pattern as KUKAI_STREAM_USAGE) so ops can tune without a restart."""
    raw = os.environ.get("KUKAI_LLM_REASONING_MAX_TOKENS", "8000").strip()
    try:
        value = int(raw)
    except ValueError:
        return 8000
    return value if value > 0 else None


def _pin_openrouter(self, kwargs: dict[str, Any]) -> None:
    """Force OpenRouter routing onto reliable providers (off Baidu). No-op
    for non-openrouter models; preserves any existing extra_body keys.
    Model-aware: an aux call (translate/repair/VOR) on a non-deepseek primary
    must NOT inherit deepseek's providers, or it 404s "No endpoints found"."""
    model = str(kwargs.get("model", ""))
    if model.startswith("openrouter/"):
        kwargs.setdefault("extra_body", {}).setdefault(
            "provider", provider_for_openrouter_model(model, self._OR_PROVIDER)
        )
        # Scoped to MiMo (the incident model) on purpose: the fallback tiers
        # (deepseek 32k-headroom, nemotron drop=[reasoning_effort]) have their
        # own tuned reasoning behavior and must stay byte-identical.
        cap = _reasoning_max_tokens()
        if cap is not None and "mimo" in model:
            # setdefault: an explicit caller-set reasoning config always wins.
            kwargs["extra_body"].setdefault("reasoning", {"max_tokens": cap})


# ── Step 9: flag-gated resilient ProviderChain (KUKAI_PROVIDER_CHAIN) ────
# Root cause fixed here: on 2026-07-03 the static _OR_PROVIDER pin rotted
# (Novita 404 "No endpoints", AtlasCloud 400 "invalid params") and the
# legacy fallback collapsed onto the SAME dead pin → "ИИ-сервис недоступен".
# With KUKAI_PROVIDER_CHAIN=1 the pin becomes a per-provider health chain
# that rotates around dead providers and self-heals. With the flag OFF
# (prod default) NONE of the methods below run.

def _provider_chain_enabled() -> bool:
    """Flag gate for the Step 9 ProviderChain. Read per call (same pattern
    as KUKAI_STREAM_USAGE) so ops can flip it via the service environment;
    default OFF keeps the legacy path byte-identical."""
    return os.environ.get("KUKAI_PROVIDER_CHAIN", "0") == "1"


def _fallback_tiers_enabled() -> bool:
    """KUKAI_FALLBACK_TIERS_ENABLED (default OFF): run the multi-tier MODEL
    waterfall (deepseek→nemotron×2) on the LEGACY fallback path too — i.e. on
    the path prod actually uses while KUKAI_PROVIDER_CHAIN is OFF. Decouples
    model-fallback (valuable, proven live 2026-07-07) from provider-rotation
    (moot for the single-provider MiMo primary). Default OFF keeps the legacy
    single deepseek hop byte-identical."""
    return os.environ.get("KUKAI_FALLBACK_TIERS_ENABLED", "0") == "1"


def _chain_env_flag(name: str) -> bool:
    """Default-ON sub-flag: only an explicit '0' disables the behavior."""
    return os.environ.get(name, "1") != "0"


def _chain_env_float(name: str, default: float) -> float:
    """Ops-tunable numeric knob; any unparsable value falls back to default."""
    raw = os.environ.get(name, "")
    try:
        return float(raw) if raw.strip() else default
    except (TypeError, ValueError):
        return default


def _get_provider_chain(self):
    """Build the ProviderChain on first use (flag ON only). Candidates come
    from the same _OR_PROVIDER pin the legacy path uses — one source of
    truth for the provider set; no new config surface.

    F1/F2 hardening knobs (read once, at first flag-ON OpenRouter call):
      KUKAI_CHAIN_REQUEST_FAULT_GUARD=0  kill-switch: revert to pre-F1
                                         immediate per-provider punishment
      KUKAI_CHAIN_SLOW_DEMOTE=0          kill-switch: disable SLOW demotion
      KUKAI_CHAIN_SLOW_THRESHOLD_S       SLOW threshold (default 60s — prod
                                         median is ~38s; only pathological
                                         ~200s providers should trip)
      KUKAI_CHAIN_SLOW_DEMOTE_S          demotion TTL (default 300s)
    Both behaviors default ON: F1 only changes the corroborated request-fault
    case (where cooling providers was wrong) and F2 only reorders live
    providers (never removes) — strict resilience improvements."""
    if self._provider_chain is None:
        from kukai.llm.provider_chain import ProviderChain
        self._provider_chain = ProviderChain(
            self._OR_PROVIDER["order"],
            request_fault_guard=_chain_env_flag("KUKAI_CHAIN_REQUEST_FAULT_GUARD"),
            slow_demote=_chain_env_flag("KUKAI_CHAIN_SLOW_DEMOTE"),
            slow_threshold_s=_chain_env_float("KUKAI_CHAIN_SLOW_THRESHOLD_S", 60.0),
            slow_demote_s=_chain_env_float("KUKAI_CHAIN_SLOW_DEMOTE_S", 300.0),
        )
    return self._provider_chain


def provider_chain_health(self) -> dict[str, Any]:
    """Cheap per-provider breaker snapshot (state / last_error_class /
    cooldown_remaining_s). Empty dict until the chain exists (flag ON +
    first OpenRouter call). Safe to surface via /health/deep later."""
    chain = self._provider_chain
    return chain.health() if chain is not None else {}


def _response_provider(response: Any) -> Optional[str]:
    """Best-effort extraction of the OpenRouter provider that served a
    response (OpenRouter includes ``provider`` in the completion body; litellm
    may or may not surface it). Used to credit a desperation-attempt success
    back to the exact provider so an all-DOWN chain can genuinely self-heal
    instead of staying stuck until cooldowns expire. Never raises; returns
    None when the response does not name its provider."""
    try:
        value = getattr(response, "provider", None)
        if value is None and isinstance(response, dict):
            value = response.get("provider")
        if isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:
        pass
    return None


def _parse_fallback_tiers() -> list[dict[str, Any]]:
    """Parse KUKAI_FALLBACK_TIERS (JSON list of {model,key,providers?,drop?,
    max_tokens?,timeout?}). Absent/blank/malformed ⇒ [] (legacy path, byte-
    identical). Never raises — a bad config must degrade, not break the turn."""
    raw = os.environ.get("KUKAI_FALLBACK_TIERS", "").strip()
    if not raw:
        return []
    try:
        import json as _json
        val = _json.loads(raw)
        if isinstance(val, list):
            return [t for t in val if isinstance(t, dict)]
    except Exception:
        logger.warning("KUKAI_FALLBACK_TIERS is not valid JSON — ignoring")
    return []


def failed_model_for_tiers(kwargs: dict[str, Any]) -> str:
    """The model string of the primary that just exhausted (so a tier on the
    exact same model+no-provider-change is skipped)."""
    return str(kwargs.get("model", ""))


async def _call_llm_with_provider_chain(self, kwargs: dict[str, Any]) -> Any:
    """Step 9 primary path (KUKAI_PROVIDER_CHAIN=1): per-provider rotation.

    Resolves the live provider order from the chain (candidates minus DOWN
    cooldown, SLOW providers demoted last — F2) and tries them ONE per
    attempt — a single-provider pin makes every failure attributable to an
    exact provider, which is what feeds the per-provider breakers.
    allow_fallbacks stays False on every attempt (never spray to unpinned
    providers — Baidu-garbage lesson, 2026-06-04). If ALL candidates are in
    DOWN cooldown, one "desperation" attempt with the FULL candidate set is
    made so stale breaker state can never self-DoS the service. On
    exhaustion, descends to the collapsed fallback
    (_do_fallback_call_chained) — never the dead legacy layers.

    F1: outcomes are recorded through ``chain.begin_request()`` — a
    per-request scope that stages 400/422-style failures carrying no
    provider-specific marker and attributes them at end of rotation (same
    suspect failure on ≥2 providers with no success anywhere ⇒ the REQUEST
    was at fault ⇒ no provider is cooled). This stops one bricked session
    (e.g. an orphaned tool call) from poisoning every provider for every
    tenant. ``scope.close()`` runs in a ``finally`` so attribution is
    resolved even if the rotation is cancelled mid-flight.
    """
    chain = self._get_provider_chain()
    scope = chain.begin_request()
    live = chain.live_order()
    if live:
        attempts: list[tuple[list[str], bool]] = [([p], False) for p in live]
    else:
        logger.warning(
            "ProviderChain: ALL providers in DOWN cooldown — desperation "
            "attempt with full candidate set %s", chain.full_order(),
        )
        attempts = [(chain.full_order(), True)]

    cb = self._circuit_breaker
    last_error: Optional[Exception] = None
    overall_start = time.time()
    try:
        for providers, is_desperation in attempts:
            call_kwargs = {**kwargs}
            extra_body = dict(call_kwargs.get("extra_body") or {})
            extra_body["provider"] = {"order": list(providers), "allow_fallbacks": False}
            call_kwargs["extra_body"] = extra_body
            logger.info(
                "LLM CALL: litellm provider-chain, model=%s, providers=%s",
                call_kwargs.get("model", "?"), ",".join(providers),
            )
            # Budget meter parity with the legacy primary path: every real
            # OpenRouter attempt is recorded (no-op outside audit sessions).
            audit_trace.trace(audit_trace.current_session(), "deepseek_call",
                              {"model": call_kwargs.get("model"), "where": "primary",
                               "providers": list(providers)})
            start = time.time()
            try:
                response = await asyncio.wait_for(
                    litellm.acompletion(**call_kwargs),
                    timeout=self._timeout,
                )
                duration = time.time() - start
                if not is_desperation:
                    # Success resolves the F1 scope (staged suspects were
                    # provider faults after all) and feeds the F2 slow window.
                    scope.record_success(providers[0], duration)
                else:
                    # Desperation succeeded with the full set — credit the
                    # exact provider when the response names it, so the
                    # all-DOWN state can heal without waiting out cooldowns.
                    served = _response_provider(response)
                    if served:
                        chain.record_success(served, duration)
                cb.record_success(duration)
                # Envelope capture parity with the legacy primary path
                # (flag-gated KUKAI_CAPTURE_ENVELOPES, never raises).
                try:
                    from kukai.llm.envelope_capture import capture as _capture_envelope
                    _capture_envelope(
                        call_kwargs.get("model"), call_kwargs.get("messages"),
                        call_kwargs.get("tools"),
                        {k: call_kwargs.get(k) for k in ("max_tokens", "temperature", "reasoning_effort")},
                        response,
                    )
                except Exception:
                    pass
                return response
            except (asyncio.TimeoutError, Exception) as err:
                last_error = err
                if not is_desperation:
                    scope.record_failure(providers[0], err)
                logger.warning(
                    "ProviderChain: attempt via %s failed (%s: %s)",
                    ",".join(providers), type(err).__name__, str(err)[:100],
                )
    finally:
        # Idempotent: a success path already resolved the scope; on
        # exhaustion (or cancellation) this attributes any staged suspects.
        scope.close()

    # The whole rotation failed. Record ONE failure into the global breaker
    # (per-attempt recording would multi-count a single user request), then
    # descend to the collapsed fallback.
    cb.record_failure(time.time() - overall_start)
    return await self._do_fallback_call_chained(kwargs, last_error)


async def _run_fallback_tiers(
    self, kwargs: dict[str, Any], last_error: Optional[Exception]
) -> tuple[Any, Optional[Exception], bool]:
    """Multi-tier MODEL fallback waterfall (KUKAI_FALLBACK_TIERS).

    ONE correct tier implementation shared by BOTH fallback paths so model-
    fallback is decoupled from provider-rotation: the flag-ON chained path
    (_do_fallback_call_chained) and the legacy prod path (_do_fallback_call,
    gated by KUKAI_FALLBACK_TIERS_ENABLED) call this same routine.

    Operator strategy: paid deepseek (key MAIN, the primary that just failed) →
    paid deepseek (key SECONDARY) → free nemotron-ultra (own Nvidia quota). The
    429 on deepseek-v4-flash is UPSTREAM (provider-scoped), so a second key on
    the SAME model rarely helps — the real escape is the DIFFERENT model
    (nemotron). Each tier is a distinct (model, api_key, provider-pool); the
    first success returns. Config is JSON in KUKAI_FALLBACK_TIERS (keys live in
    .env only, never git). ``drop`` strips params the tier's model rejects
    (e.g. reasoning_effort for nemotron).

    Returns (response, last_error, tiers_present):
      * (response, last_error, True)  — a tier succeeded;
      * (None, last_error, True)      — tiers configured but ALL failed
                                        (caller decides: raise vs. fall through);
      * (None, last_error, False)     — no tiers configured (caller continues).
    """
    tiers = _parse_fallback_tiers()
    if not tiers:
        return None, last_error, False
    for _ti, tier in enumerate(tiers):
        t_model = str(tier.get("model") or "").strip()
        t_key = str(tier.get("key") or "").strip()
        if not t_model or not t_key:
            continue
        if t_model == failed_model_for_tiers(kwargs) and not tier.get("providers"):
            # never re-hit the exact pin that just failed with nothing changed
            continue
        tk = {**kwargs}
        tk["model"] = t_model
        tk["api_key"] = t_key
        tk["timeout"] = float(tier.get("timeout") or self._fallback_timeout)
        # Let litellm silently drop params a tier's model rejects (parity with
        # the primary call, client.py) — a cross-model fallback must never die
        # on UnsupportedParamsError (e.g. reasoning on nemotron).
        tk["drop_params"] = True
        for _p in ("api_base", "vertex_project", "vertex_location",
                   "thinking_config", "thinking"):
            tk.pop(_p, None)
        for _d in (tier.get("drop") or []):
            tk.pop(_d, None)
        if isinstance(tier.get("max_tokens"), int):
            tk["max_tokens"] = tier["max_tokens"]
        # deepseek needs its 32k reasoning headroom back even when the primary
        # (e.g. MiMo) capped max_tokens low — else reasoning starves the answer.
        if "deepseek" in t_model:
            tk["max_tokens"] = max(tk.get("max_tokens") or 0, 32768)
        if t_model.startswith("openrouter/"):
            eb = dict(tk.get("extra_body") or {})
            # The MiMo reasoning cap (_pin_openrouter) must not leak into
            # fallback models via this extra_body copy — deepseek relies on
            # its 32k headroom above, nemotron rejects reasoning knobs. Pop
            # ONLY the exact injected shape: caller-set reasoning configs are
            # a preserved contract (test_reasoning_param_provider_isolation).
            _cap = _reasoning_max_tokens()
            if _cap is not None and eb.get("reasoning") == {"max_tokens": _cap}:
                eb.pop("reasoning")
            if tier.get("providers"):
                eb["provider"] = {"order": list(tier["providers"]),
                                  "allow_fallbacks": False}
            else:
                # single-source model (e.g. nemotron on Nvidia): let OpenRouter
                # pick — a hard pin to a 1-provider model needlessly 404s.
                eb.pop("provider", None)
            tk["extra_body"] = eb
        else:
            tk.pop("extra_body", None)
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(**tk), timeout=tk["timeout"],
            )
            logger.info("Fallback tier %d succeeded — model=%s", _ti + 1, t_model)
            return response, last_error, True
        except Exception as err:  # noqa: BLE001
            logger.warning("Fallback tier %d (%s) failed: %s: %s",
                           _ti + 1, t_model, type(err).__name__, str(err)[:120])
            last_error = err
    return None, last_error, True


async def _do_fallback_call_chained(
    self, kwargs: dict[str, Any], last_error: Optional[Exception]
) -> Any:
    """Step 9 collapsed fallback (KUKAI_PROVIDER_CHAIN=1 only).

    Replaces the legacy _do_fallback_call when the flag is ON:
      * Antigravity Pro proxy (if configured) — kept: genuinely independent
        infrastructure and quota.
      * The Google AIza layers are SKIPPED — all Google creds are
        purged/dead; retrying them is theatre that adds latency mid-outage.
      * Genuine last-ditch: KUKAI_EMERGENCY_MODEL (default: the configured
        fallback model), optionally pinned to KUKAI_EMERGENCY_PROVIDERS
        (comma-separated OpenRouter provider names). Attempted ONLY when it
        differs from what just failed — a different model, or the same
        model on a distinct provider subset. Re-hitting the exact failed
        pin is the 2026-07-03 collapse mode and is refused; the ORIGINAL
        error is raised instead so upstream sees the real cause.
    """
    # --- Antigravity Pro proxy (independent infrastructure) ---
    if self._antigravity_url and self._antigravity_api_key:
        try:
            ag_kwargs = {**kwargs}
            # Strip Vertex/OpenRouter/Anthropic-specific params for the
            # OpenAI-compat endpoint (same hygiene as the legacy layer).
            ag_kwargs.pop("api_base", None)
            ag_kwargs.pop("vertex_project", None)
            ag_kwargs.pop("vertex_location", None)
            ag_kwargs.pop("thinking_config", None)
            ag_kwargs.pop("thinking", None)
            ag_kwargs.pop("extra_body", None)
            ag_kwargs["model"] = f"openai/{self._antigravity_model}"
            ag_kwargs["api_base"] = f"{self._antigravity_url}/v1"
            ag_kwargs["api_key"] = self._antigravity_api_key
            ag_kwargs["timeout"] = self._antigravity_timeout
            response = await asyncio.wait_for(
                litellm.acompletion(**ag_kwargs),
                timeout=self._antigravity_timeout,
            )
            logger.info(
                "ProviderChain fallback: Antigravity Pro proxy succeeded — model %s",
                self._antigravity_model,
            )
            return response
        except Exception as err:
            logger.warning(
                "ProviderChain fallback: Antigravity proxy failed (%s)",
                str(err)[:120],
            )
            last_error = err

    # --- Multi-tier fallback chain (KUKAI_FALLBACK_TIERS, 2026-07-06) ---------
    # Shared waterfall (extracted 2026-07-10 as _run_fallback_tiers so the legacy
    # prod path can use the SAME implementation). Semantics preserved: tiers
    # present ⇒ a success returns, else the terminal raise below; tiers absent ⇒
    # fall through to the genuine last-ditch. Byte-identical to the prior inline loop.
    _tier_resp, last_error, _tiers_present = await _run_fallback_tiers(
        self, kwargs, last_error)
    if _tier_resp is not None:
        return _tier_resp
    if _tiers_present and last_error:
        raise last_error

    # --- Genuine last-ditch (never the pin that just failed) ---
    emergency_model = (
        os.environ.get("KUKAI_EMERGENCY_MODEL", "").strip() or self._fallback_model
    )
    emergency_providers = [
        p.strip()
        for p in os.environ.get("KUKAI_EMERGENCY_PROVIDERS", "").split(",")
        if p.strip()
    ]
    failed_model = str(kwargs.get("model", ""))
    if emergency_model and (emergency_model != failed_model or emergency_providers):
        em_kwargs = {**kwargs}
        em_kwargs["model"] = emergency_model
        if self._fallback_api_key:
            em_kwargs["api_key"] = self._fallback_api_key
        em_kwargs["timeout"] = self._fallback_timeout
        # Same param hygiene as the legacy emergency layer: provider-
        # specific knobs must not cross provider boundaries.
        em_kwargs.pop("api_base", None)
        em_kwargs.pop("vertex_project", None)
        em_kwargs.pop("vertex_location", None)
        em_kwargs.pop("thinking_config", None)
        em_kwargs.pop("thinking", None)
        if emergency_model.startswith("openrouter/"):
            extra_body = dict(em_kwargs.get("extra_body") or {})
            extra_body["provider"] = {
                "order": emergency_providers or self._get_provider_chain().full_order(),
                "allow_fallbacks": False,
            }
            em_kwargs["extra_body"] = extra_body
        else:
            em_kwargs.pop("extra_body", None)
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(**em_kwargs),
                timeout=self._fallback_timeout,
            )
            logger.info(
                "ProviderChain fallback: emergency succeeded — model %s, providers=%s",
                emergency_model, emergency_providers or "(candidate set)",
            )
            return response
        except Exception as err:
            logger.error(
                "ProviderChain fallback: emergency failed: %s", str(err)[:200]
            )
            last_error = err
    elif emergency_model:
        logger.error(
            "ProviderChain fallback: NO genuine last-ditch — emergency model equals "
            "the exhausted primary (%s) and no KUKAI_EMERGENCY_PROVIDERS configured; "
            "refusing to re-hit the failed pin", failed_model,
        )

    if last_error:
        raise last_error
    raise RuntimeError("ProviderChain fallback exhausted: no provider configured")


async def _call_llm_with_fallback_inner(self, **kwargs: Any) -> Any:
    """Inner implementation — called under semaphore."""
    # Step 9 (KUKAI_PROVIDER_CHAIN=1, default OFF): resilient per-provider
    # rotation for OpenRouter primaries. With the flag OFF this branch is
    # inert and the legacy path below runs unchanged (prod state).
    if (
        self._provider_chain_enabled()
        and str(kwargs.get("model", "")).startswith("openrouter/")
        and self._OR_PROVIDER.get("order")
    ):
        return await self._call_llm_with_provider_chain(kwargs)
    cb = self._circuit_breaker
    # Centralized provider pin: covers primary chat, _simple_completion,
    # _repair_code, chat_completion (all route through here).
    self._pin_openrouter(kwargs)

    # If circuit breaker is OPEN — skip primary entirely
    if cb.should_use_fallback() and self._fallback_model:
        logger.info("Circuit breaker OPEN — routing to fallback: %s", self._fallback_model)
        return await self._do_fallback_call(kwargs)

    # If HALF_OPEN — this is a probe request
    if cb.allow_probe():
        logger.info("Circuit breaker HALF_OPEN — probing primary: %s", kwargs.get("model", "?"))

    # Try primary model
    start = time.time()
    logger.info("LLM CALL: litellm, model=%s", kwargs.get("model", "?"))
    # Budget meter: every real OpenRouter/DeepSeek primary call is recorded.
    # This is the authoritative source for the ≤50 audit-budget auto-stop.
    # No-op for non-audit sessions and for non-openrouter (e.g. gemini) calls.
    if str(kwargs.get("model", "")).startswith("openrouter/"):
        audit_trace.trace(audit_trace.current_session(), "deepseek_call",
                          {"model": kwargs.get("model"), "where": "primary"})
    try:
        response = await asyncio.wait_for(
            litellm.acompletion(**kwargs),
            timeout=self._timeout,
        )
        cb.record_success(time.time() - start)
        # Wave 2 — capture the request envelope for offline shadow-replay + cache
        # measurement (flag-gated KUKAI_CAPTURE_ENVELOPES, sampled, PII-aware, never raises).
        try:
            from kukai.llm.envelope_capture import capture as _capture_envelope
            _capture_envelope(
                kwargs.get("model"), kwargs.get("messages"), kwargs.get("tools"),
                {k: kwargs.get(k) for k in ("max_tokens", "temperature", "reasoning_effort")},
                response,
            )
        except Exception:
            pass
        return response
    except (asyncio.TimeoutError, Exception) as primary_error:
        cb.record_failure(time.time() - start)
        if not self._fallback_model:
            raise
        logger.warning(
            "Primary LLM failed (%s: %s), trying fallback %s...",
            type(primary_error).__name__,
            str(primary_error)[:100],
            self._fallback_model,
        )

    return await self._do_fallback_call(kwargs)


def _strip_images(messages: Any) -> tuple[Any, int]:
    """Убрать изображения из переписки, оставив текст.

    ЗАЧЕМ. 29.07, живой ход оператора: он приложил скриншот, Codex в тот момент
    был недоступен (цепь разомкнута), ход поехал на qwen — и умер целиком:
    ``No endpoints found that support image input`` (404), раунд 17 из 200.

    Не всякая модель каскада умеет смотреть. Ответить без картинки хуже, чем с
    картинкой, но несравнимо лучше, чем не ответить вовсе: человек видит ответ
    и может переспросить, а не пустоту после четверти часа работы.

    Возвращает (сообщения, сколько картинок снято). Исходный список не портим —
    он ещё нужен основному маршруту, если тот оживёт.
    """
    if not isinstance(messages, list):
        return messages, 0
    out, dropped = [], 0
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, list):
            out.append(m)
            continue
        kept = [p for p in content
                if not (isinstance(p, dict) and p.get("type") == "image_url")]
        dropped += len(content) - len(kept)
        if len(kept) == len(content):
            out.append(m)
            continue
        # Схлопываем в обычный текст: часть моделей не принимает даже список
        # из одного текстового куска.
        text = " ".join(p.get("text", "") for p in kept
                        if isinstance(p, dict) and p.get("type") == "text").strip()
        out.append({**m, "content": text or "[изображение не поддерживается этой моделью]"})
    return out, dropped


async def _do_fallback_call(self, kwargs: dict[str, Any]) -> Any:
    """Execute LLM call using a 3-level fallback chain:

    Layer 2: AIza key #1 (KUKAI_LLM_GOOGLE_BACKUP_API_KEY) via gemini/* model
             — free Google AI Studio quota, independent from Vertex.
             Routed through WARP proxy (HTTPS_PROXY env var, set in systemd).
    Layer 3: AIza key #2 (KUKAI_LLM_GOOGLE_FALLBACK_API_KEY) via gemini/*
             — second free Google AI Studio quota, different account.
    Layer 4 (emergency): self._fallback_model (e.g.
             openrouter/deepseek/deepseek-v4-flash) — different model,
             cheap, only triggered when ALL Gemini pools are exhausted.
             Quality may be lower (DeepSeek doesn't know Revit API as well)
             but keeps the service responding under extreme load.

    CRITICAL: Layers 2 and 3 use ``gemini/<model>`` prefix instead of
    ``vertex_ai/<model>``. This is what makes litellm actually USE the
    AIza key. With ``vertex_ai/*`` prefix, litellm silently ignores the
    api_key and falls back to GOOGLE_APPLICATION_CREDENTIALS service
    account → same Vertex quota → theatrical fallback. The prefix swap
    is the difference between real fallback and fake fallback.

    The ``last_resort_*`` config fields are no longer used; the chain is
    intentionally short and explicit.
    """
    # Картинка переживает не всякую ступень каскада (замер 29.07: qwen отвечает
    # 404 "No endpoints found that support image input" и роняет ход целиком).
    # Снимаем изображения ПЕРЕД запасными моделями: ответ без картинки лучше,
    # чем отсутствие ответа.
    _msgs, _dropped = _strip_images(kwargs.get("messages"))
    if _dropped:
        kwargs = {**kwargs, "messages": _msgs}
        logger.warning("фолбэк: снято изображений %d — запасная модель их не принимает", _dropped)

    last_error: Optional[Exception] = None

    def _aistudio_kwargs(api_key: str) -> dict[str, Any]:
        """Build litellm kwargs for a Google AI Studio call."""
        k = {**kwargs}
        k["model"] = self._google_aistudio_model
        k["api_key"] = api_key
        k["timeout"] = self._fallback_timeout
        # Remove any Vertex-specific config that would confuse the
        # gemini/ provider.
        k.pop("api_base", None)
        k.pop("vertex_project", None)
        k.pop("vertex_location", None)
        # OpenRouter-only reasoning control — invalid for the gemini/ provider.
        k.pop("extra_body", None)
        # Anthropic-style reasoning param — gemini/ uses thinking_config, not this.
        k.pop("thinking", None)
        return k

    # --- Layer 1.5: Antigravity Pro proxy (paid subscription, OpenAI-compat) ---
    # User's CH-hosted proxy with Google AI Pro subscription. Tried FIRST in
    # fallback chain because Pro quota is much larger than free AI Studio.
    # +400-700ms overhead from KZ->CF->CH->Google routing, but worth it for
    # quota. Uses OpenAI-compatible endpoint at antigravity proxy.
    if self._antigravity_url and self._antigravity_api_key:
        try:
            ag_kwargs = {**kwargs}
            # Strip Vertex-specific params for OpenAI-compat endpoint
            ag_kwargs.pop("api_base", None)
            ag_kwargs.pop("vertex_project", None)
            ag_kwargs.pop("vertex_location", None)
            ag_kwargs.pop("thinking_config", None)
            # Anthropic-style reasoning param — invalid for the OpenAI-compat proxy.
            ag_kwargs.pop("thinking", None)
            # OpenRouter-only reasoning control — strip for the OpenAI-compat proxy.
            ag_kwargs.pop("extra_body", None)
            # OpenAI-compatible: model=openai/<name>, base_url, api_key
            ag_kwargs["model"] = f"openai/{self._antigravity_model}"
            ag_kwargs["api_base"] = f"{self._antigravity_url}/v1"
            ag_kwargs["api_key"] = self._antigravity_api_key
            ag_kwargs["timeout"] = self._antigravity_timeout
            response = await asyncio.wait_for(
                litellm.acompletion(**ag_kwargs),
                timeout=self._antigravity_timeout,
            )
            logger.info(
                "Antigravity Pro proxy succeeded — model %s",
                self._antigravity_model,
            )
            return response
        except Exception as err:
            logger.warning(
                "Antigravity Pro proxy failed (%s), trying AIza backup...",
                str(err)[:120],
            )
            last_error = err

    # --- Layer 2: AIza key #1 (backup) via Google AI Studio ---
    if (
        self._google_aistudio_model
        and self._google_backup_api_key
        and self._google_backup_api_key != self._api_key
    ):
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(**_aistudio_kwargs(self._google_backup_api_key)),
                timeout=self._fallback_timeout,
            )
            logger.info(
                "Google AI Studio backup (key #1) succeeded — model %s",
                self._google_aistudio_model,
            )
            return response
        except Exception as err:
            logger.warning(
                "Google AI Studio backup (key #1) failed (%s), trying fallback...",
                str(err)[:120],
            )
            last_error = err

    # --- Layer 3: AIza key #2 (fallback) via Google AI Studio ---
    if (
        self._google_aistudio_model
        and self._google_fallback_api_key
        and self._google_fallback_api_key != self._api_key
        and self._google_fallback_api_key != self._google_backup_api_key
    ):
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(**_aistudio_kwargs(self._google_fallback_api_key)),
                timeout=self._fallback_timeout,
            )
            logger.info(
                "Google AI Studio fallback (key #2) succeeded — model %s",
                self._google_aistudio_model,
            )
            return response
        except Exception as err:
            logger.warning(
                "Google AI Studio fallback (key #2) failed (%s), trying emergency...",
                str(err)[:120],
            )
            last_error = err

    # --- Layer 3.5: Extra AIza keys (sequential cascade) ---
    # Each extra key is an independent Google AI Studio account, ~15 RPM
    # quota. We try them one by one until one succeeds. Order matters
    # (first key wins on cold path). Skipped if model not gemini/-able.
    if self._google_aistudio_model and self._google_extra_api_keys:
        for idx, extra_key in enumerate(self._google_extra_api_keys, start=3):
            try:
                response = await asyncio.wait_for(
                    litellm.acompletion(**_aistudio_kwargs(extra_key)),
                    timeout=self._fallback_timeout,
                )
                logger.info(
                    "Google AI Studio extra (key #%d) succeeded — model %s",
                    idx, self._google_aistudio_model,
                )
                return response
            except Exception as err:
                logger.warning(
                    "Google AI Studio extra (key #%d) failed (%s), trying next...",
                    idx, str(err)[:120],
                )
                last_error = err

    # --- Multi-tier MODEL waterfall (KUKAI_FALLBACK_TIERS_ENABLED, 2026-07-10) ---
    # Decouples model-fallback (deepseek→nemotron×2) from the provider-rotation
    # flag (KUKAI_PROVIDER_CHAIN). Prod runs THIS legacy path (chain flag OFF);
    # without this block the only backstop is the single deepseek hop below, so a
    # correlated deepseek 429 (observed live 2026-07-07) hard-fails to
    # "ИИ-сервис недоступен". The nemotron tiers (own Nvidia quota) are the real
    # safety net. Default OFF = byte-identical single-hop. On tier success returns;
    # on tier-exhaustion falls THROUGH to the legacy single-hop below — a DISTINCT
    # deepseek key/quota (KUKAI_LLM_FALLBACK_API_KEY), a genuine extra attempt.
    if _fallback_tiers_enabled():
        _tier_resp, last_error, _present = await _run_fallback_tiers(
            self, kwargs, last_error)
        if _tier_resp is not None:
            return _tier_resp

    # --- Layer 4 (emergency): OpenRouter DeepSeek (different model!) ---
    # This is the LAST resort. DeepSeek doesn't know Revit API as well
    # as Gemini, so code quality drops. But it keeps the service alive
    # when all Gemini pools are simultaneously dead/rate-limited.
    if self._fallback_model:
        emergency_kwargs = {**kwargs}
        emergency_kwargs["model"] = self._fallback_model
        if self._fallback_api_key:
            emergency_kwargs["api_key"] = self._fallback_api_key
        emergency_kwargs["timeout"] = self._fallback_timeout
        emergency_kwargs.pop("api_base", None)
        emergency_kwargs.pop("vertex_project", None)
        emergency_kwargs.pop("vertex_location", None)
        emergency_kwargs.pop("thinking_config", None)
        # Anthropic-style reasoning param — rejected by the emergency
        # provider (OpenRouter); strip so the fallback can't inherit the
        # param that already killed the primary.
        emergency_kwargs.pop("thinking", None)
        # deepseek fallback needs its 32k reasoning headroom back if the primary
        # (e.g. MiMo) capped max_tokens low (client.py model-aware cap).
        if "deepseek" in str(self._fallback_model):
            emergency_kwargs["max_tokens"] = max(emergency_kwargs.get("max_tokens") or 0, 32768)
        # extra_body carries the PRIMARY model's provider pin (client.py:605 — e.g.
        # MiMo → {"order":["Xiaomi"]}). Inherited unchanged onto the emergency model
        # (deepseek) it 404s "No endpoints found" (Xiaomi doesn't serve deepseek) — the
        # leak that turned this last-resort backstop into a DEAD END once primary≠fallback
        # (MiMo became primary 2026-07-06 → this is the live root of "ИИ-сервис недоступен").
        # Rebuild the pin for the emergency model via the single source of truth; keep the
        # other extra_body keys (reasoning) intact.
        _eb = dict(emergency_kwargs.get("extra_body") or {})
        _eb["provider"] = provider_for_openrouter_model(self._fallback_model, _OR_PROVIDER)
        emergency_kwargs["extra_body"] = _eb
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(**emergency_kwargs),
                timeout=self._fallback_timeout,
            )
            logger.info(
                "Emergency fallback succeeded — model %s",
                self._fallback_model,
            )
            return response
        except Exception as err:
            logger.error("Emergency fallback also failed: %s", str(err)[:200])
            last_error = err

    if last_error:
        raise last_error
    raise RuntimeError("Fallback chain exhausted: no provider configured")
