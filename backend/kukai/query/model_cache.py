"""Wave 1a — content-addressed model cache with freshness.

Model-derived data (the material/function glossary `type_meta`, the health `vitals`,
and later the relationship graph) is expensive to fetch (a live bridge query) and is
reused turn-to-turn, so it is cached per document. The OLD cache keyed by raw
`document_name` had two faults:
  1. CROSS-TENANT LEAK — an empty name (unsaved model / family editor) or two users
     with the same filename ("Корпус1.rvt") shared one cache slot, so one user's
     glossary/vitals leaked into another's passport.
  2. STALENESS — slots were never invalidated, so an edited model kept serving old data.

Both are fixed by making the key a CONTENT FINGERPRINT (`world_version`): element/level/
family/param counts + document path + name. Consequences:
  • Two genuinely different models → different fingerprints → never collide (even with an
    empty or identical name). The leak is closed.
  • The same model opened by two users/connections → the same fingerprint → correct shared
    reuse (it is literally the same building; the data is model-state, not tenant-state).
  • An edit that changes the model → new fingerprint → the stale slot is bypassed and the
    data recomputed. This is poll-based freshness — no Revit DocumentChanged hook needed;
    `world_version` is recomputed each turn from the (freshly pushed / re-requested) context.

This is the substrate the verb layer (Wave 1c) and graph passport (Wave 1d) read from.
"""
from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
import uuid

logger = logging.getLogger(__name__)

# fingerprint -> {kind: value}. Bounded LRU-ish (insertion-ordered eviction).
_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_MAX_FINGERPRINTS = 256
# (fingerprint, kind) -> Future resolved for waiters. The owner computes; on
# owner failure waiters receive None (fail-open) while the owner sees the error.
_INFLIGHT: dict[tuple[str, str], asyncio.Future[Any]] = {}

_DISK_SCHEMA = 1
_DEFAULT_TTL_S = 24 * 60 * 60
_DEFAULT_MAX_FILES = 512
_DEFAULT_MAX_BYTES = 8 * 1024 * 1024


def _persistence_enabled() -> bool:
    """Whether the census cache is also kept on disk. Default ON.

    This used to be gated on KUKAI_PERCEPTION_WARM — but that flag ALSO arms the
    connect-time bridge warm (chat_ws._launch_perception_warm), a fire-and-forget
    roundtrip .env deliberately keeps off ("bridge is fragile"). So persistence
    was off as collateral damage and the census lived only in process memory:
    every backend restart wiped it and every active user re-paid a FULL census on
    their next turn — measured 151 s on a 262k-element model (the 2026-07-26
    fleet median of 32 s/turn was mostly restart-induced misses; quiet days sat at
    1 s). The disk cache is bounded (512 files / 8 MiB / 24 h TTL) and keyed by the
    content fingerprint, so a hit after a restart is exactly as correct as one
    before it — nothing about staleness changes, only who pays the 151 s again.

    Kill-switch: KUKAI_CENSUS_DISK_CACHE=0.
    """
    return os.getenv("KUKAI_CENSUS_DISK_CACHE", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(float(os.getenv(name, str(default)))), maximum))
    except (TypeError, ValueError):
        return default


def _safe_component(value: str) -> bool:
    text = str(value or "")
    return bool(text) and len(text) <= 128 and all(
        ch.isalnum() or ch in {"-", "_"} for ch in text
    )


def _cache_dir() -> Path:
    configured = os.getenv("KUKAI_MODEL_CACHE_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "model_cache"


def _disk_path(fingerprint: str, kind: str) -> Optional[Path]:
    if not _safe_component(fingerprint) or not _safe_component(kind):
        return None
    return _cache_dir() / f"{fingerprint}.{kind}.json"


def _remember(fingerprint: str, kind: str, value: Any) -> None:
    _CACHE.setdefault(fingerprint, {})[kind] = value
    _CACHE.move_to_end(fingerprint)
    while len(_CACHE) > _MAX_FINGERPRINTS:
        _CACHE.popitem(last=False)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except (OSError, TypeError):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def _read_disk(fingerprint: str, kind: str) -> Any:
    path = _disk_path(fingerprint, kind)
    if path is None or not path.is_file():
        return None
    try:
        max_bytes = _bounded_env_int(
            "KUKAI_MODEL_CACHE_MAX_BYTES", _DEFAULT_MAX_BYTES, 1024, 64 * 1024 * 1024
        )
        if path.stat().st_size > max_bytes:
            raise ValueError("cache entry exceeds size cap")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cache envelope is not an object")
        if payload.get("fingerprint") != fingerprint or payload.get("kind") != kind:
            raise ValueError("cache identity mismatch")
        saved_at = float(payload.get("saved_at", 0.0))
        ttl = _bounded_env_int(
            "KUKAI_MODEL_CACHE_TTL_S", _DEFAULT_TTL_S, 0, 30 * 24 * 60 * 60
        )
        if saved_at <= 0 or time.time() - saved_at > ttl:
            raise ValueError("cache entry expired")
        value = payload.get("value")
        if not value:
            raise ValueError("falsy cache value")
        return value
    except Exception:
        # Corrupt, poisoned, expired, or incompatible entries must never keep
        # failing every turn; remove only this content-addressed slot.
        _unlink_quietly(path)
        return None


def _prune_disk(directory: Path) -> None:
    maximum = _bounded_env_int(
        "KUKAI_MODEL_CACHE_MAX_FILES", _DEFAULT_MAX_FILES, 1, 10_000
    )
    try:
        files = [p for p in directory.glob("*.json") if p.is_file()]
        if len(files) <= maximum:
            return
        files.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
        for stale in files[: len(files) - maximum]:
            _unlink_quietly(stale)
    except OSError:
        logger.debug("model-cache disk prune failed", exc_info=True)


def _write_disk(fingerprint: str, kind: str, value: Any) -> None:
    path = _disk_path(fingerprint, kind)
    if path is None:
        return
    temp: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": _DISK_SCHEMA,
            "fingerprint": fingerprint,
            "kind": kind,
            "saved_at": time.time(),
            "value": value,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        max_bytes = _bounded_env_int(
            "KUKAI_MODEL_CACHE_MAX_BYTES", _DEFAULT_MAX_BYTES, 1024, 64 * 1024 * 1024
        )
        if len(encoded) > max_bytes:
            return
        temp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
        with temp.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        _prune_disk(path.parent)
    except Exception:
        logger.debug("model-cache disk write failed", exc_info=True)
    finally:
        if temp is not None:
            _unlink_quietly(temp)


def world_version(basic_ctx: dict[str, Any], detailed: Optional[dict[str, Any]] = None) -> str:
    """A cheap content fingerprint of the model's current state — the cache key AND the
    freshness token. Derived from coarse counts (which move when the model is edited) plus
    document identity (so two different models with equal counts still differ)."""
    bc = basic_ctx or {}
    det = detailed if isinstance(detailed, dict) else (bc.get("detailed") or {})
    cats = bc.get("categories") or []
    elem_total = sum(c.get("count", 0) for c in cats if isinstance(c, dict))
    key = (
        bc.get("document_path") or "",
        bc.get("document_name") or "",
        elem_total,
        len(bc.get("levels") or []),
        det.get("family_count", 0) if isinstance(det, dict) else 0,
        det.get("param_count", 0) if isinstance(det, dict) else 0,
        bc.get("revit_version") or "",
    )
    return hashlib.md5(repr(key).encode("utf-8")).hexdigest()[:16]


async def get_or_compute(
    fingerprint: str,
    kind: str,
    compute: Callable[[], Awaitable[Any]],
) -> Any:
    """Return cached ``kind`` for this fingerprint, else ``await compute()`` and cache a
    truthy result. ``compute`` is a zero-arg coroutine function (e.g. the bridge query).
    A falsy/None result is not cached (so a transient failure retries next turn)."""
    slot = _CACHE.get(fingerprint)
    if slot is not None and kind in slot:
        _CACHE.move_to_end(fingerprint)  # mark recently used
        return slot[kind]
    if not _persistence_enabled():
        value = await compute()
        if value:
            _remember(fingerprint, kind, value)
        return value

    key = (fingerprint, kind)
    inflight = _INFLIGHT.get(key)
    if inflight is not None:
        try:
            return await asyncio.shield(inflight)
        except asyncio.CancelledError:
            raise
        except Exception:
            return None

    loop = asyncio.get_running_loop()
    completion: asyncio.Future[Any] = loop.create_future()
    _INFLIGHT[key] = completion
    try:
        # Entries are strictly size-capped and local. Keep the operation inline:
        # some production/container runtimes intentionally disable thread creation,
        # where asyncio.to_thread would leave perception requests hanging forever.
        disk_value = _read_disk(fingerprint, kind)
        if disk_value:
            _remember(fingerprint, kind, disk_value)
            completion.set_result(disk_value)
            return disk_value

        value = await compute()
        if value:
            _remember(fingerprint, kind, value)
            _write_disk(fingerprint, kind, value)
        completion.set_result(value)
        return value
    except BaseException:
        # Only the owner receives the original failure. Joined perception warmers
        # fail open and the next turn may recompute after the registry drains.
        if not completion.done():
            completion.set_result(None)
        raise
    finally:
        _INFLIGHT.pop(key, None)


def peek(fingerprint: str, kind: str) -> Any:
    """Non-computing read (None if absent). For tests / introspection."""
    slot = _CACHE.get(fingerprint)
    return slot.get(kind) if slot else None


def clear() -> None:
    """Drop all cached entries (tests / manual invalidation)."""
    _CACHE.clear()


# ── Write invalidation (ModelGraph v2, flag KUKAI_GESTALT_V2) ────────────────
# The content fingerprint catches USER edits only via coarse counts: a KUKAI
# write that keeps counts unchanged (set parameter, move, rename, override)
# leaves the fingerprint — and thus the cached graph/vitals/type_meta — stale
# forever. These hooks close that hole: a successful write through the bridge
# drops the model's slot so the NEXT turn recomputes from live Revit. Trigger
# priority: the change-witness manifest when present (authoritative: real
# added/modified/deleted counts, KUKAI_CHANGE_WITNESS + Step-4 DLL), else the
# shared write-marker heuristic on the executed code (same detector the loop
# policy and timeout estimator already use).

# Fallback markers when kukai.llm.loop_policy is unimportable (keep in sync).
_FALLBACK_WRITE_MARKERS = ("Transaction", ".Set(", ".Delete(", "Create.",
                           "NewFamilyInstance", "ElementTransformUtils.")


def _code_is_write(code: str) -> bool:
    """Reuse the existing write-detection scaffolding (no new classifier)."""
    try:
        from kukai.llm.loop_policy import _WRITE_PATTERNS as _markers
    except Exception:  # noqa: BLE001 — layering/fallback safety
        _markers = _FALLBACK_WRITE_MARKERS
    return any(p in code for p in _markers)


def invalidate_fingerprint(fingerprint: str) -> int:
    """Drop every cached kind for this fingerprint. Returns how many kinds were
    dropped (0 when the slot didn't exist). Safe on unknown fingerprints."""
    slot = _CACHE.pop(fingerprint, None)
    dropped = len(slot) if slot else 0
    # Delete persisted kinds too, even when the feature flag was just disabled:
    # otherwise stale data can resurrect when persistence is re-enabled.
    if _safe_component(fingerprint):
        try:
            for path in _cache_dir().glob(f"{fingerprint}.*.json"):
                _unlink_quietly(path)
        except OSError:
            logger.debug("model-cache disk invalidation failed", exc_info=True)
    return dropped


def invalidate_after_write(
    basic_ctx: dict[str, Any],
    detailed: Optional[dict[str, Any]] = None,
    *,
    code: str = "",
    changes: Optional[dict[str, Any]] = None,
    method: str = "execute",
) -> int:
    """Staleness hook, called from the bridge success path after each execute.

    UNCONDITIONAL since A6 (2026-07-13) — the census is the always-on perception
    path. Fail-open: never raises, returns the number of cache kinds dropped.

    ``changes`` — the change-witness manifest for this request when available.
    It is AUTHORITATIVE: >0 changes ⇒ invalidate; ==0 ⇒ keep the cache even if
    the code *looked* like a write (nothing actually changed). Without a
    manifest the write-marker heuristic on ``code`` decides.
    """
    try:
        # A6 (2026-07-13): UNCONDITIONAL. The census passport is THE perception
        # path now (no flag), so a stale-after-write cache is always a
        # correctness bug — the old gestalt/v3/snapshot flag gate retired with
        # the legacy execs. Witness/marker logic below still decides WHETHER a
        # write actually happened.
        if method not in ("execute", "apply"):
            return 0
        n_changes: Optional[int] = None
        if isinstance(changes, dict):
            n_changes = sum(
                len(v) for v in (changes.get(k) for k in ("added", "modified", "deleted"))
                if isinstance(v, (list, tuple))
            )
        if n_changes is not None:
            if n_changes == 0:
                return 0  # witnessed: nothing changed — cache stays valid
        elif not _code_is_write(str(code or "")):
            return 0  # no witness → read-shaped code keeps the cache
        fp = world_version(basic_ctx or {}, detailed)
        dropped = invalidate_fingerprint(fp)
        # The snapshot-passport census is keyed under world_version(basic_ctx, {})
        # — a DIFFERENT fingerprint whenever the pushed `detailed` carries
        # family/param counts. Drop that slot too, or a write that keeps counts
        # unchanged serves a STALE census passport for the model's cache lifetime
        # (found at A1 review, 2026-07-12).
        fp_census = world_version(basic_ctx or {}, {})
        if fp_census != fp:
            dropped += invalidate_fingerprint(fp_census)
        if dropped:
            if n_changes:
                logger.info("graph invalidated: %d changes (witness; fp=%s, %d kinds dropped)",
                            n_changes, fp, dropped)
            else:
                logger.info("graph invalidated after write (code markers; fp=%s, %d kinds dropped)",
                            fp, dropped)
        return dropped
    except Exception:  # noqa: BLE001 — invalidation must never break a turn
        logger.debug("invalidate_after_write failed (fail-open)", exc_info=True)
        return 0
