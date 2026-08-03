"""Optional Codex-subscription primary backend — isolated, flag-gated.

The whole scheme lives in this one file. It routes a chat turn to the operator's
OpenAI **Codex subscription** (served locally by CLIProxyAPI as an OpenAI-compatible
endpoint) INSTEAD of the default mimo model — but only for allow-listed devices,
under a per-user turn budget, and only while a circuit breaker says the proxy is
healthy. It is a PREMIUM TOP LAYER, never the floor.

Design invariants (why this file is safe to leave in prod at all times):

  * Master kill-switch: ``KUKAI_CODEXPROXY_ENABLED != "1"`` → :func:`enabled` is False →
    the single call site in ``client._litellm_response`` short-circuits BEFORE any
    work. Zero overhead, zero behaviour change. Flip the env, restart, gone.

  * Codex never becomes the floor. :func:`try_stream` returns ``None`` on ANY
    decline or failure (disabled, not allow-listed, over-budget, circuit open,
    missing key, request error) — the caller then falls through to the normal
    mimo primary + its full existing fallback cascade. mimo stays the floor for
    free; we do NOT touch the cascade in transport.py.

  * All state is process-local and fail-open. A bug here must never break a turn —
    worst case we decline and the turn goes to mimo.

  * Known limitation (shared with the agy/antigravity layers): we return the
    streaming response object; an error that happens *mid-stream* surfaces in the
    caller's iteration and is NOT re-routed to mimo. Connect-time errors (429,
    auth, 5xx, timeout) ARE caught here and fall through cleanly.

Config — all env, all hot (re-read per call, so a flip needs no code change):

  KUKAI_CODEXPROXY_ENABLED        "1" to arm the scheme (default: off)
  KUKAI_CODEXPROXY_URL      base URL of the local CLIProxyAPI (default 127.0.0.1:8317)
  KUKAI_CODEXPROXY_API_KEY        key CLIProxyAPI expects (per-deploy)
  KUKAI_CODEXPROXY_MODEL          model name to request (default gpt-5.6-terra)
  KUKAI_CODEXPROXY_REASONING_EFFORT  minimal|low|medium|high (default medium)
  KUKAI_CODEXPROXY_TIMEOUT        seconds (default 90)
  KUKAI_CODEXPROXY_ALLOW_DEVICES  comma-separated device ids allowed to use Codex,
                              or ``*`` for the whole fleet (Codex as the primary
                              model). Empty still means NOBODY — a forgotten env
                              var must not spill the fleet onto the subscription.
  KUKAI_CODEXPROXY_TURNS_PER_MIN  per-device fair share of the shared quota (default 6)
  KUKAI_CODEXPROXY_TURNS_PER_DAY  per-device daily cap (default 200)
  KUKAI_CODEXPROXY_TURNS_PER_DAY_PER_ACCOUNT
                              0 = off (default). When > 0, the FLEET may spend
                              ``alive_subscriptions × this`` turns a day, so
                              capacity follows the pool without editing env:
                              add an account and the ceiling rises by itself.
  KUKAI_CODEXPROXY_MGMT_KEY   local management key of the proxy — the only way
                              to learn how many subscriptions are in service.
  KUKAI_CODEXPROXY_ACT_NUDGE  "1" (default) → append an act-now system message so the
                              model calls tools instead of replying with a plan.
  KUKAI_CODEXPROXY_NO_FALLBACK  "1" → on a Codex ATTEMPT failure, surface the error
                                instead of falling to mimo (testing; default off).
                                Note: a not-eligible DECLINE (not allow-listed / over
                                budget / circuit open) still goes to mimo regardless.

To fully remove: delete this file and the marked block in client._litellm_response.
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from contextvars import ContextVar
from typing import Any, Optional

import litellm

from kukai.llm.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# ── shared-subscription health: one circuit for the whole proxy ──
# 3 consecutive errors (429 / auth / 5xx) → OPEN for 120s → EVERYONE falls to
# mimo, then a single HALF_OPEN probe re-tests. Escalating cooldown on repeat
# failure. This is what stops us from hammering a dead or rate-limited proxy.
_circuit = CircuitBreaker(failure_threshold=3, slow_threshold_s=30.0, cooldown_s=120.0)

# ── per-device turn budget (mirror of chat_ws.check_and_count_turn) ──
# Fair share of the ONE shared subscription: no single user may burn the whole
# quota. Counts ATTEMPTS (not the AI's tool rounds), process-local, fail-open.
_dev_turn_times: dict[str, deque] = {}   # device -> recent attempt monotonic ts (per-min window)
_dev_day: dict[str, list] = {}           # device -> [date_str, attempt_count]

# ── fleet-wide capacity, derived from the LIVE pool size ──
# Operator decision 2026-07-29: serve the fleet from a pool of Plus
# subscriptions. Adding an account must raise capacity BY ITSELF — a ceiling
# that has to be hand-edited in .env every time is a ceiling that will be wrong
# most days, and wrong in the expensive direction (either we leave paid quota
# unused, or we promise more than the pool can serve and every user finds out
# by stalling).
#
# So the daily fleet budget is ``alive_accounts × TURNS_PER_DAY_PER_ACCOUNT``.
# Log in a new account → the proxy picks it up incrementally (measured: "auth
# file changed (CREATE) … processing incrementally", no restart) → within one
# TTL the budget here grows too. An account dies → the budget shrinks and the
# overflow degrades to qwen instead of hammering a pool that cannot serve it.
#
# NEVER BLOCK THE LOOP. This runs inside the turn path of a SINGLE-worker
# uvicorn: a synchronous HTTP call here would stall every other user for its
# duration. The count is refreshed by a background task and only ever READ from
# cache; a cold or failed cache falls back to the static per-device caps, i.e.
# exactly today's behaviour.
_POOL_TTL_S = 60.0
_pool: dict[str, Any] = {"at": 0.0, "alive": None, "refreshing": False}
_fleet_day: list = ["", 0]               # [date_str, attempts by the whole fleet]


def enabled() -> bool:
    """Cheap master gate. False in prod by default → the call site is a no-op."""
    return os.environ.get("KUKAI_CODEXPROXY_ENABLED") == "1"


def _allow_devices() -> set[str]:
    return {d.strip() for d in os.environ.get("KUKAI_CODEXPROXY_ALLOW_DEVICES", "").split(",") if d.strip()}


def _device_allowed(device_id: Optional[str]) -> bool:
    """Разрешён ли Codex этому устройству.

    ``*`` в списке = весь флот (Codex как ОСНОВНАЯ модель, решение оператора
    29.07). Проверяется отдельной веткой, а не членством в множестве: иначе
    устройство с буквальным id ``*`` открывало бы дверь всем, и наоборот —
    хватило бы опечатки в списке, чтобы тихо раздать Codex всем.

    ПУСТОЙ список по-прежнему значит «никому», а не «всем». Это важно: забытая
    переменная окружения не должна выливать флот на подписку."""
    if not device_id:
        return False
    allow = _allow_devices()
    return "*" in allow or device_id in allow


# Dedicated per-turn device ContextVar for Codex routing. DELIBERATELY separate
# from KIR's turn_context._active_device_id — so arming Codex can NEVER shift KIR's
# device gate (KIR stays exactly as-is: off in normal chat). chat_ws.run_turn binds
# this once per turn from ctx.device_id.
_active_chat_device: ContextVar[Optional[str]] = ContextVar("_codex_active_chat_device", default=None)

# Per-TURN grant. The quota is a fair share of TURNS, but _should_route runs on
# every agentic ROUND — and an autonomous turn fires rounds seconds apart, so a
# 6/min allowance was exhausted mid-task and the rest of the turn silently fell to
# mimo (live 2026-07-26: two apply_revit_write rounds on Codex, then "per_minute",
# then mimo finished the job — half the work done by a different model with
# different conventions). Charge the turn once; later rounds ride the same grant.
# A MUTABLE dict on purpose: tool execution may run in a copied child context, so
# a plain ContextVar.set() there would not propagate back to the parent.
_turn_grant: ContextVar[Optional[dict]] = ContextVar("_codex_turn_grant", default=None)


def bind_turn_device(device_id: Optional[str]) -> None:
    """Bind THIS chat turn's device for routing. Called once per turn in run_turn.

    No explicit reset needed: one WS connection = one device, every turn rebinds
    before any Codex read, and asyncio copies the context per task — so a stale
    value is always overwritten by the current turn and never leaks across users."""
    _active_chat_device.set(device_id or None)
    _turn_grant.set({"granted": False})


def _device_id() -> Optional[str]:
    """This turn's chat device (bound by run_turn). None outside a bound turn."""
    return _active_chat_device.get()


def device_eligible() -> bool:
    """Is THIS turn's device allowed on the Codex route? Read-only — unlike
    :func:`_should_route` it spends no per-minute budget, so callers that merely
    need to know "is this an autonomous Codex session" (e.g. to widen the turn
    budget) can ask without stealing a slot from the actual call."""
    return bool(enabled() and _device_allowed(_device_id()))


#: model name -> monotonic ts until which we skip it. Process-local, fail-open.
_model_cold: dict[str, float] = {}


def _model_is_cold(model: str) -> bool:
    """Отказала ли эта модель совсем недавно.

    Держим СВОЙ короткий бан, потому что чужой мы не контролируем: прокси после
    отказа отвечает `auth_unavailable` минутами, а его ручки остывания
    (`transient-error-cooldown-seconds`, `disable-cooling`) на наших замерах
    29.07 не подействовали ни в одну сторону."""
    until = _model_cold.get(model)
    if until is None:
        return False
    if time.monotonic() >= until:
        _model_cold.pop(model, None)
        return False
    return True


def _mark_model_cold(model: str) -> None:
    """Отставить модель на короткий срок. Срок намеренно небольшой: смысл не в
    наказании, а в том, чтобы не платить целым ходом за проверку живости."""
    secs = _int_env("KUKAI_CODEXPROXY_MODEL_COOLDOWN_S", 120)
    if secs > 0:
        _model_cold[model] = time.monotonic() + secs


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:  # noqa: BLE001
        return default


def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


async def _refresh_pool() -> None:
    """Ask the proxy how many subscriptions are actually in service.

    Only ``codex-*`` auth files count: ``auth.json`` and other API-key entries
    are not subscriptions, and counting them would inflate the fleet budget
    beyond what the pool can serve."""
    try:
        import httpx

        key = os.environ.get("KUKAI_CODEXPROXY_MGMT_KEY", "")
        url = os.environ.get("KUKAI_CODEXPROXY_URL", "http://127.0.0.1:8317").rstrip("/")
        if not key:
            return
        async with httpx.AsyncClient(timeout=5.0) as cx:
            r = await cx.get(f"{url}/v0/management/auth-files",
                             headers={"Authorization": f"Bearer {key}"})
            r.raise_for_status()
            files = r.json().get("files") or []
        alive = sum(
            1 for f in files
            if str(f.get("name", "")).startswith("codex-")
            and not f.get("disabled") and not f.get("expired")
        )
        _pool["alive"] = alive
        logger.info("codex pool: %d subscription(s) in service", alive)
    except Exception:  # noqa: BLE001 — a health probe must never break a turn
        logger.debug("codex pool refresh failed", exc_info=True)
    finally:
        _pool["refreshing"] = False


def _pool_alive() -> Optional[int]:
    """Cached pool size. Schedules a background refresh when stale and returns
    immediately — the caller never waits on the network."""
    now = time.monotonic()
    if not _pool["refreshing"] and (now - float(_pool["at"]) > _POOL_TTL_S):
        # Stamp BEFORE scheduling: otherwise every concurrent turn in the same
        # second sees a stale timestamp and spawns its own refresh task.
        _pool["at"] = now
        _pool["refreshing"] = True
        try:
            import asyncio

            asyncio.get_running_loop().create_task(_refresh_pool())
        except RuntimeError:  # no loop (tests, sync callers) — stay with cache
            _pool["refreshing"] = False
    return _pool["alive"]


def _fleet_check() -> Optional[str]:
    """Has the WHOLE fleet spent the pool's daily capacity? READ-ONLY.

    Returns a reason when over (decline → qwen), else None. Split from the
    commit on purpose: charging here and then declining on a per-device limit
    would bill the pool for turns that never ran, and that error compounds —
    the fleet budget would drift down all day for everyone.

    Disabled (returns None immediately) unless ``TURNS_PER_DAY_PER_ACCOUNT`` is
    set, so behaviour is unchanged until the knob is turned on."""
    per_account = _int_env("KUKAI_CODEXPROXY_TURNS_PER_DAY_PER_ACCOUNT", 0)
    if per_account <= 0:
        return None
    alive = _pool_alive()
    if alive is None:
        return None          # cold cache — fall back to per-device caps only
    if alive <= 0:
        return "pool_empty"  # no subscription in service: do not even try
    if _fleet_day[0] != _today_utc():
        return None          # new day, counter resets on commit
    if _fleet_day[1] >= alive * per_account:
        return "fleet_daily_cap"
    return None


def _fleet_commit() -> None:
    """Charge one turn to the fleet. Called only after every gate said yes."""
    if _int_env("KUKAI_CODEXPROXY_TURNS_PER_DAY_PER_ACCOUNT", 0) <= 0:
        return
    d = _today_utc()
    if _fleet_day[0] != d:
        _fleet_day[0], _fleet_day[1] = d, 0
    _fleet_day[1] += 1


def _over_budget(device_id: str) -> Optional[str]:
    """Per-device fair share of the shared subscription. Returns a reason string
    when over a limit (decline), else None AND records the attempt. Fail-open."""
    try:
        d = _today_utc()
        slot = _dev_day.get(device_id)
        if slot is None or slot[0] != d:
            slot = [d, 0]
            _dev_day[device_id] = slot
        if slot[1] >= _int_env("KUKAI_CODEXPROXY_TURNS_PER_DAY", 200):
            return "daily_cap"
        now = time.monotonic()
        dq = _dev_turn_times.get(device_id)
        if dq is None:
            dq = deque()
            _dev_turn_times[device_id] = dq
        while dq and now - dq[0] > 60.0:
            dq.popleft()
        if len(dq) >= _int_env("KUKAI_CODEXPROXY_TURNS_PER_MIN", 6):
            return "per_minute"
        dq.append(now)
        slot[1] += 1
        # bound memory (rare prod-restart cleanup) — same guard as chat_ws
        if len(_dev_turn_times) > 5000:
            _dev_turn_times.clear()
        if len(_dev_day) > 20000:
            td = _today_utc()
            for k in [k for k, v in _dev_day.items() if v[0] != td]:
                _dev_day.pop(k, None)
        return None
    except Exception:  # noqa: BLE001 — a budget must never break a turn
        return None


def _should_route(device_id: Optional[str]) -> bool:
    """The gate: armed AND this device allow-listed AND circuit healthy AND under
    budget. Any 'no' → decline (caller uses mimo). Never raises.

    Order matters: circuit is checked BEFORE budget so that during a proxy outage
    we do NOT burn users' per-minute budgets on calls that would fail anyway."""
    if not enabled():
        return False
    if not device_id:
        logger.info("codex declined: no device bound this turn (→ mimo)")
        return False
    if not _device_allowed(device_id):
        logger.info("codex declined device=%s: not allow-listed (→ mimo)", device_id[:12])
        return False
    if _circuit.should_use_fallback():   # OPEN → proxy unhealthy, skip straight to mimo
        logger.warning("codex declined device=%s: circuit OPEN (proxy unhealthy) (→ mimo)", device_id[:12])
        return False
    grant = _turn_grant.get()
    if isinstance(grant, dict) and grant.get("granted"):
        return True  # this turn already paid — its remaining rounds are free
    fleet = _fleet_check()
    if fleet is not None:
        logger.info("codex declined device=%s: %s (→ mimo)", device_id[:12], fleet)
        return False
    reason = _over_budget(device_id)
    if reason is not None:
        logger.info("codex declined device=%s: %s (→ mimo)", device_id[:12], reason)
        return False
    _fleet_commit()
    if isinstance(grant, dict):
        grant["granted"] = True
    return True


async def try_stream(
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    tools: Optional[list[dict[str, Any]]],
    tool_choice: str,
    session_id: Optional[str],
    *,
    device_id: Optional[str] = None,
) -> Optional[Any]:
    """Attempt this turn on the Codex subscription.

    Returns the streaming response object on success, or ``None`` to tell the
    caller to fall through to the normal mimo path. NEVER raises — a Codex
    problem must degrade to mimo, not break the turn.
    """
    dev = device_id if device_id is not None else _device_id()
    if not _should_route(dev):
        return None

    url = os.environ.get("KUKAI_CODEXPROXY_URL", "http://127.0.0.1:8317").rstrip("/")
    key = os.environ.get("KUKAI_CODEXPROXY_API_KEY", "")
    model = os.environ.get("KUKAI_CODEXPROXY_MODEL", "gpt-5.6-terra")
    effort = os.environ.get("KUKAI_CODEXPROXY_REASONING_EFFORT", "medium").strip()
    timeout = float(_int_env("KUKAI_CODEXPROXY_TIMEOUT", 90))
    if not key:
        # Armed + allow-listed but not configured yet → silently defer to mimo.
        return None

    # OpenAI-compatible call, same shape as the antigravity/agy layers:
    # model=openai/<name> + api_base + api_key. drop_params lets litellm drop any
    # param the proxy rejects (e.g. reasoning models refusing temperature) instead
    # of raising — turning "unsupported param" into graceful degradation.
    # gpt-5.6-terra is a REASONING model: reasoning tokens count against max_tokens.
    # A tight cap (client default 4096) lets reasoning starve the answer → empty
    # content (the "empty response" guard fires). Give a generous floor so reasoning
    # AND content both fit — same lesson as the openrouter path (16-32k). Env-tunable.
    mt = max(int(max_tokens or 0), _int_env("KUKAI_CODEXPROXY_MAX_TOKENS", 32000))
    kwargs: dict[str, Any] = {
        "model": f"openai/{model}",
        "messages": messages,
        "max_tokens": mt,
        "temperature": temperature,
        # Streaming: see the block below. Overwritten there, kept here so the
        # dict shape stays obvious.
        "stream": False,
        "timeout": timeout,
        "drop_params": True,
        "api_base": f"{url}/v1",
        "api_key": key,
    }
    if effort:
        # Codex reasoning depth. drop_params guards if the endpoint rejects it.
        kwargs["reasoning_effort"] = effort

    # ── live streaming, restored 2026-07-29 ──
    # It was OFF since 26.07 for a measured reason: the proxy's Responses-API →
    # chat.completions translation dropped the function_call when the model
    # emitted an encrypted reasoning item first — the stream carried
    # finish_reason="tool_calls" with tool_calls=None, so the call was announced
    # and never delivered (prod: tool calls in 1 turn of 21; the same payload
    # non-streamed returned the call 5 of 5).
    #
    # The proxy has since been rebuilt (7.2.94, built 21.07). Re-measured today
    # against the live endpoint: 8 of 8 streamed turns delivered the tool call,
    # control group non-streamed 4 of 4 — the loss is gone. Streaming back on
    # buys three things the route was missing next to the OpenRouter path:
    # text appears as it is written instead of after the whole answer, reasoning
    # arrives live rather than as one block at the end, and the usage chunk lands
    # so Codex turns finally show up in token/cache telemetry (until now every
    # Codex turn was invisible there).
    #
    # ROLLED BACK the same day, and the rollback is the lesson. The 8/8 above was
    # measured on a payload I built by hand — and it did NOT carry the act-nudge
    # system message this route appends to every real turn. On the REAL payload
    # streaming returns an empty stream: no text, no tool call, three chunks
    # (reproduced at 1, 5 and 15 tools; the buffered path delivered the call every
    # time). It cost a whole live bench run on the operator's model: every Codex
    # turn came back empty, KUKAI fell to forced synthesis, and the answers read
    # "не удалось получить снимок" — which I first mis-read as Codex refusing to
    # act. It never refused; it was never asked.
    #
    # Hence default 0. Turning this on again requires re-measuring with the EXACT
    # production payload (KUKAI_CODEXPROXY_DUMP=1 writes it), not a hand-built one.
    stream_on = os.environ.get("KUKAI_CODEXPROXY_STREAM", "0") == "1"
    if stream_on:
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
    if os.environ.get("KUKAI_CODEXPROXY_ACT_NUDGE", "1") == "1":
        # Codex-family models read the G4 "plan first" directive (KUKAI_PLAN_ONE_SCRIPT)
        # as "reply with the plan", print "Сделаю в 3 шага: ..." and END the turn with
        # zero tool calls — the user sees an answer but nothing happens in Revit
        # (observed live 2026-07-26: 105-char reply, 0 executes). mimo instead keeps
        # the plan in reasoning and acts. Re-assert act-now for THIS route only, so
        # the shared prompt (and every mimo user) stays untouched.
        kwargs["messages"] = list(messages) + [{
            "role": "system",
            "content": (
                "ВАЖНО: не отвечай пользователю планом действий и не спрашивай "
                "подтверждения. Если задача требует чтения или изменения модели Revit — "
                "вызови нужный инструмент СРАЗУ в этом же ответе (план держи в "
                "рассуждении).\n"
                "ДОВОДИ ЗАДАЧУ ДО КОНЦА: выполни ВСЕ шаги в этом же ходу, вызывая "
                "инструменты один за другим. Не останавливайся и не отчитывайся, пока "
                "остаётся невыполненный шаг.\n"
                "ЕСЛИ ШАГ НЕ ПОЛУЧИЛСЯ: не пиши, что это невозможно — попробуй другой "
                "инструмент или другой способ. Отчитывайся текстом ТОЛЬКО когда все шаги "
                "реально выполнены."
            ),
        }]
    if session_id:
        # Sticky per-session pinning at the proxy (multi-account load balancing).
        kwargs["user"] = session_id

    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

    if os.environ.get("KUKAI_CODEXPROXY_DUMP") == "1":
        # Temporary forensics: persist the EXACT payload so a failing turn can be
        # replayed offline and bisected component-by-component. Off by default.
        try:
            import json as _json
            from pathlib import Path as _Path
            _d = _Path("/tmp/codex_dumps")
            _d.mkdir(exist_ok=True)
            _f = _d / f"turn_{int(time.time())}.json"
            _f.write_text(_json.dumps({
                "model": kwargs.get("model"),
                "reasoning_effort": kwargs.get("reasoning_effort"),
                "max_tokens": kwargs.get("max_tokens"),
                "tool_choice": kwargs.get("tool_choice"),
                "tools": [t.get("function", {}).get("name") for t in (kwargs.get("tools") or [])],
                "tools_full": kwargs.get("tools"),
                "messages": kwargs.get("messages"),
            }, ensure_ascii=False), encoding="utf-8")
            logger.info("codex dump written: %s (msgs=%d tools=%d)", _f,
                        len(kwargs.get("messages") or []), len(kwargs.get("tools") or []))
        except Exception:  # noqa: BLE001 — forensics must never break a turn
            logger.debug("codex dump failed", exc_info=True)

    # ── догон второй моделью ТОЙ ЖЕ подписки ──
    # Оператор 29.07 выбрал gpt-5.6-sol: на тяжёлых задачах он заметно сильнее.
    # Плата — скорость (замер: 17.0с против 2.1с у terra) и доступность: sol
    # популярна, и OpenAI периодически отвечает "server_is_overloaded". Замер в
    # такое окно: 0 успехов из 10, при том что terra в те же секунды давала 4 из 4.
    #
    # Без догона каждое такое окно роняло бы ход на qwen — то есть на модель
    # другого класса, с другими привычками, посреди задачи. Терять сильную
    # модель из-за чужого всплеска нагрузки незачем, когда та же подписка
    # прямо сейчас отдаёт terra.
    #
    # Порядок: sol → terra → (вернуть None) → qwen. Пустая переменная выключает
    # догон и возвращает прежнее поведение.
    fallback_model = os.environ.get("KUKAI_CODEXPROXY_MODEL_FALLBACK", "").strip()

    # Если основная модель только что отказала — не бить в неё снова. Прокси
    # держит СВОЙ бан (`auth_unavailable: no auth available`) минутами, и его
    # конфиг остывания нас не слушает: пробовали и малый таймаут, и полное
    # отключение — оба проигнорированы. Пока бан висит, каждый ход платил ~8
    # секунд за заведомо мёртвый вызов, прежде чем догнать на terra (замерено
    # живьём на работе оператора 29.07, ход за ходом). Свой счётчик надёжнее
    # чужого конфига.
    if fallback_model and _model_is_cold(model):
        logger.info("codex %s остывает у нас → сразу на %s", model, fallback_model)
        kwargs["model"] = f"openai/{fallback_model}"
        model = fallback_model

    start = time.time()
    try:
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as first_err:  # noqa: BLE001
            if not fallback_model or fallback_model == model:
                raise
            _mark_model_cold(model)
            logger.warning(
                "codex %s failed (%s) → догоняю на %s (той же подпиской)",
                model, str(first_err)[:110], fallback_model)
            kwargs["model"] = f"openai/{fallback_model}"
            response = await litellm.acompletion(**kwargs)
            model = fallback_model
        _circuit.record_success(time.time() - start)
        logger.info("LLM CALL: codex proxy OK (model=%s device=%s stream=%s)",
                    model, (dev or "?")[:12], stream_on)
        if stream_on:
            # A native stream: hand it straight to the caller's loop, which
            # already knows how to read content, tool_calls, reasoning_content
            # and the usage chunk — the same code path every mimo turn uses.
            # Nothing to re-emit, so none of the buffered logic below runs.
            return response
        msg = (response.choices or [None])[0]
        finish = getattr(msg, "finish_reason", None) if msg is not None else None
        m = getattr(msg, "message", None) if msg is not None else None
        content = (getattr(m, "content", None) or "") if m is not None else ""
        tool_calls = (getattr(m, "tool_calls", None) or []) if m is not None else []
        # The proxy DOES return the model's thinking (measured 29.07: message
        # carries `reasoning_content` alongside content and tool_calls). Until
        # now we dropped it on the floor, so a Codex turn showed no reasoning at
        # all while every mimo/qwen turn did — the route looked less capable
        # than it is. The caller's stream loop already reads
        # `delta.reasoning_content` (client.py:1308), so re-emitting it below is
        # all that was missing.
        reasoning = (getattr(m, "reasoning_content", None) or "") if m is not None else ""
        logger.info(
            "codex response: finish=%s tools=%s text=%d",
            finish, [getattr(getattr(t, "function", None), "name", "?") for t in tool_calls] or "-", len(content),
        )

        async def _as_stream():
            """Re-emit the complete response as the chunk sequence the caller's loop
            expects (delta.content → delta.tool_calls → finish_reason), so switching
            this route to non-streaming stays invisible to client.py."""
            from litellm.types.utils import (
                ChatCompletionDeltaToolCall,
                Delta,
                Function,
                ModelResponseStream,
                StreamingChoices,
            )

            def _chunk(delta: Delta, finish_reason=None) -> ModelResponseStream:
                return ModelResponseStream(
                    choices=[StreamingChoices(index=0, delta=delta, finish_reason=finish_reason)]
                )

            step = 240
            if reasoning:
                # Thinking first, then the answer — the order the UI expects
                # (reasoning_start → reasoning_chunk* → content). Chunked for
                # the same reason as content: one blob makes the panel jump.
                # HONEST LIMIT: this route is non-streaming (see above), so the
                # thinking has already finished by the time we emit it. It
                # paints fast rather than live — unlike the OpenRouter path,
                # where it arrives token by token as the model thinks.
                for k in range(0, len(reasoning), step):
                    yield _chunk(Delta(reasoning_content=reasoning[k:k + step]))
            if content:
                # Chunked so the UI still paints progressively instead of one blob.
                for k in range(0, len(content), step):
                    yield _chunk(Delta(content=content[k:k + step]))
            if tool_calls:
                deltas = []
                for idx, tc in enumerate(tool_calls):
                    fn = getattr(tc, "function", None)
                    deltas.append(ChatCompletionDeltaToolCall(
                        id=getattr(tc, "id", None) or f"codex_{idx}",
                        type="function",
                        index=idx,
                        function=Function(
                            name=getattr(fn, "name", "") or "",
                            arguments=getattr(fn, "arguments", "") or "",
                        ),
                    ))
                yield _chunk(Delta(tool_calls=deltas))
            yield _chunk(Delta(), finish_reason=finish or ("tool_calls" if tool_calls else "stop"))

        return _as_stream()
    except Exception as err:  # noqa: BLE001
        _circuit.record_failure(time.time() - start)
        if os.environ.get("KUKAI_CODEXPROXY_NO_FALLBACK") == "1":
            # Testing mode: surface the Codex error directly instead of the slow
            # mimo fallback (so a dumb test turn never silently burns mimo credits).
            logger.warning("codex proxy failed (%s); NO_FALLBACK → surfacing error (no mimo)", str(err)[:140])
            raise
        logger.warning("codex proxy failed (%s) → mimo fallback", str(err)[:140])
        return None


def side_call_kwargs() -> Optional[dict[str, Any]]:
    """Endpoint overlay for a NON-turn LLM call that belongs to a Codex turn.

    The C# repair loop is the case that forced this. On a Codex turn the code is
    written by gpt-5.6-terra but the repair call went to ``self._model`` (mimo,
    via OpenRouter) — a different, weaker brain repairing code it never wrote,
    behind the multi-provider fallback cascade. Prod 2026-07-27 measured two
    single-attempt repairs at 112.1s and 113.5s that both ended in "no code in
    response", with the breaker already OPEN; actual Revit execution in those
    turns was 12ms and 56ms. Across 621 executions the repair machinery burned
    55% of all execute wall-clock, and 19 multi-attempt runs (3%) accounted for
    439s of it. The proxy answers a 17k-token prompt in 2-5s.

    Returns None when this turn is not Codex-bound (caller keeps its own model).
    Deliberately uses :func:`device_eligible` — a side call belongs to a turn
    that already paid, so it must not spend a per-minute slot of its own.
    """
    if not device_eligible():
        return None
    if _circuit.should_use_fallback():
        return None
    key = os.environ.get("KUKAI_CODEXPROXY_API_KEY", "")
    if not key:
        return None
    url = os.environ.get("KUKAI_CODEXPROXY_URL", "http://127.0.0.1:8317").rstrip("/")
    model = os.environ.get("KUKAI_CODEXPROXY_MODEL", "gpt-5.6-terra")
    out: dict[str, Any] = {
        "model": f"openai/{model}",
        "api_base": f"{url}/v1",
        "api_key": key,
        "timeout": float(_int_env("KUKAI_CODEXPROXY_SIDE_TIMEOUT", 60)),
        "drop_params": True,
    }
    effort = os.environ.get("KUKAI_CODEXPROXY_REASONING_EFFORT", "medium").strip()
    if effort:
        out["reasoning_effort"] = effort
    return out


def _reset_for_test() -> None:
    """Clear all process-local state. Test-only helper (see tests/test_codex_route.py)."""
    _dev_turn_times.clear()
    _dev_day.clear()
    _circuit.reset()
    _active_chat_device.set(None)
    _fleet_day[0], _fleet_day[1] = "", 0
    _pool.update({"at": 0.0, "alive": None, "refreshing": False})
    _model_cold.clear()
    # The per-turn grant is process-local state too: leaving a granted dict in
    # the ContextVar made every later _should_route return True on the "this
    # turn already paid" short-circuit, so budget tests passed the cap.
    _turn_grant.set(None)
