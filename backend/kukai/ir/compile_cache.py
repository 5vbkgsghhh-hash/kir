"""Sound, content-addressed cache for Roslyn compile verdicts.

The cache is deliberately conservative.  A C# compile verdict is a function of
the exact source text *and* the exact compiler/reference/analyzer toolchain.
Numeric literals are therefore never normalized: changing ``1`` to
``2147483648`` can change inferred types, overload selection, constant
conversion, overflow diagnostics, and other compile-time behaviour.

The wrapper is opt-in and fail-closed:

* enabling it requires an explicit, non-empty ``toolchain_identity``;
* the key covers exact UTF-8 source bytes, Revit version, toolchain identity,
  and this wrapper's schema version;
* only successful verdicts are cached;
* persistent entries are schema- and toolchain-checked before reuse;
* concurrent identical requests are coalesced into one backend call.

This cache can safely remove repeated *identical* Roslyn calls.  Higher hit
rates must come from a different architecture: versioned precompiled kernels
with typed runtime parameter packets, not from erasing semantic differences in
source code.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from kukai.compile_client import CompileClient, CompileError, CompileResult

logger = logging.getLogger(__name__)

# Bump whenever key semantics or the persisted payload changes.  Old entries
# then miss rather than being interpreted under a new contract.
COMPILE_CACHE_WRAPPER_VERSION = "compile-cache/2"
COMPILE_CACHE_ENTRY_SCHEMA = "compile-cache-entry/2"

_DEFAULT_LRU_CAPACITY = 512


def compile_cache_key(
    wrapped_code: str,
    revit_version: str,
    *,
    toolchain_identity: str,
    wrapper_version: str = COMPILE_CACHE_WRAPPER_VERSION,
) -> str:
    """Return the sound content address for one compile request.

    ``toolchain_identity`` must identify the deployed Roslyn compiler,
    compilation policy, analyzer set, and all framework/Revit reference
    assemblies.  Callers must obtain it from immutable release provenance; a
    friendly version label such as ``"latest"`` is not sufficient.
    """

    if not isinstance(toolchain_identity, str) or not toolchain_identity.strip():
        raise ValueError("toolchain_identity is required for compile caching")
    if not isinstance(wrapped_code, str):
        raise TypeError("wrapped_code must be str")
    if not isinstance(revit_version, str) or not revit_version:
        raise ValueError("revit_version is required")

    hasher = hashlib.sha256()
    # Length-prefix every field so no concatenation ambiguity can cross field
    # boundaries.  Hash exact source; no semantic-preserving assumption is made.
    for part in (
        wrapped_code,
        revit_version,
        toolchain_identity,
        wrapper_version,
    ):
        encoded = part.encode("utf-8")
        hasher.update(len(encoded).to_bytes(8, "big"))
        hasher.update(encoded)
    return hasher.hexdigest()


def _result_to_payload(
    result: CompileResult,
    *,
    toolchain_identity: str,
) -> dict:
    return {
        "schema": COMPILE_CACHE_ENTRY_SCHEMA,
        "toolchain_identity": toolchain_identity,
        "success": result.success,
        "errors": [
            {
                "code": error.code,
                "message": error.message,
                "line": error.line,
                "column": error.column,
            }
            for error in result.errors
        ],
    }


def _payload_to_result(payload: dict) -> CompileResult:
    errors = [
        CompileError(
            code=error.get("code", ""),
            message=error.get("message", ""),
            line=error.get("line", 0),
            column=error.get("column", 0),
        )
        for error in payload.get("errors", [])
        if isinstance(error, dict)
    ]
    return CompileResult(success=bool(payload.get("success", False)), errors=errors)


class CachedCompileClient:
    """Opt-in exact-code cache over :class:`CompileClient`.

    Parameters
    ----------
    client:
        Wrapped compile client.
    enabled:
        When false, every method is a transparent pass-through.
    toolchain_identity:
        Immutable digest/identity for compiler + policy + analyzers + all
        references.  Required whenever ``enabled`` is true.
    cache_dir:
        Optional persistent cache directory.  Entries are atomic and still
        bounded in memory by ``lru_capacity``.
    lru_capacity:
        Maximum in-memory entries.
    """

    def __init__(
        self,
        client: CompileClient,
        *,
        enabled: bool = False,
        toolchain_identity: Optional[str] = None,
        cache_dir: Optional[str | os.PathLike[str]] = None,
        lru_capacity: int = _DEFAULT_LRU_CAPACITY,
    ) -> None:
        if enabled and (
            not isinstance(toolchain_identity, str)
            or not toolchain_identity.strip()
        ):
            raise ValueError(
                "enabled compile cache requires an immutable toolchain_identity"
            )

        self._client = client
        self._enabled = bool(enabled)
        self._toolchain_identity = (
            toolchain_identity.strip() if isinstance(toolchain_identity, str) else ""
        )
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._lru_capacity = max(1, int(lru_capacity))
        self._memory: "OrderedDict[str, dict]" = OrderedDict()
        self._inflight: dict[
            str, "asyncio.Task[Optional[CompileResult]]"
        ] = {}

        # Lightweight observability for gates and future production metrics.
        self.hits = 0
        self.misses = 0
        self.coalesced = 0

        if self._enabled and self._cache_dir is not None:
            try:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:  # pragma: no cover - defensive
                logger.warning("compile cache dir unavailable (%s); memory-only", exc)
                self._cache_dir = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def available(self) -> bool:
        return self._client.available

    def _entry_path(self, key: str) -> Optional[Path]:
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"{key}.json"

    def _valid_payload(self, payload: object) -> bool:
        return (
            isinstance(payload, dict)
            and payload.get("schema") == COMPILE_CACHE_ENTRY_SCHEMA
            and payload.get("toolchain_identity") == self._toolchain_identity
            and payload.get("success") is True
            and isinstance(payload.get("errors"), list)
        )

    def _lru_get(self, key: str) -> Optional[dict]:
        payload = self._memory.get(key)
        if payload is not None:
            self._memory.move_to_end(key)
        return payload

    def _lru_put(self, key: str, payload: dict) -> None:
        self._memory[key] = payload
        self._memory.move_to_end(key)
        while len(self._memory) > self._lru_capacity:
            self._memory.popitem(last=False)

    def _disk_get(self, key: str) -> Optional[dict]:
        path = self._entry_path(key)
        if path is None or not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            logger.debug("compile cache read failed for %s: %s", key, exc)
            return None
        return payload if self._valid_payload(payload) else None

    def _disk_put(self, key: str, payload: dict) -> None:
        path = self._entry_path(key)
        if path is None:
            return

        temporary: Optional[Path] = None
        try:
            # A unique temporary name makes simultaneous backend processes
            # safe; os.replace is atomic on the cache filesystem.
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{key}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            logger.debug("compile cache write failed for %s: %s", key, exc)
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _lookup(self, key: str) -> Optional[dict]:
        payload = self._lru_get(key)
        if payload is not None:
            return payload
        payload = self._disk_get(key)
        if payload is not None:
            self._lru_put(key, payload)
        return payload

    def _store(self, key: str, result: CompileResult) -> None:
        # Failures and unavailable-service results are request-specific and
        # deliberately never cached.
        if not result.success:
            return
        payload = _result_to_payload(
            result,
            toolchain_identity=self._toolchain_identity,
        )
        self._lru_put(key, payload)
        self._disk_put(key, payload)

    async def _compile_and_store(
        self,
        key: str,
        wrapped_code: str,
        revit_version: str,
    ) -> Optional[CompileResult]:
        result = await self._client.check(wrapped_code, revit_version)
        if result is not None:
            self._store(key, result)
        return result

    def _clear_inflight(
        self,
        key: str,
        finished: "asyncio.Task[Optional[CompileResult]]",
    ) -> None:
        if self._inflight.get(key) is finished:
            self._inflight.pop(key, None)

    async def check(
        self,
        wrapped_code: str,
        revit_version: str,
    ) -> Optional[CompileResult]:
        """Return a cached success or delegate exactly once per exact request."""

        if not self._enabled:
            return await self._client.check(wrapped_code, revit_version)

        key = compile_cache_key(
            wrapped_code,
            revit_version,
            toolchain_identity=self._toolchain_identity,
        )
        cached = self._lookup(key)
        if cached is not None:
            self.hits += 1
            return _payload_to_result(cached)

        inflight = self._inflight.get(key)
        if inflight is not None:
            self.coalesced += 1
            # A cancelled waiter must not cancel the shared compile request.
            return await asyncio.shield(inflight)

        self.misses += 1
        task = asyncio.create_task(
            self._compile_and_store(key, wrapped_code, revit_version)
        )
        self._inflight[key] = task
        task.add_done_callback(
            lambda finished, cache_key=key: self._clear_inflight(
                cache_key, finished
            )
        )
        return await asyncio.shield(task)

    async def health(self) -> bool:
        return await self._client.health()

    async def close(self) -> None:
        # Do not cancel an accepted compile verdict during orderly shutdown.
        if self._inflight:
            await asyncio.gather(
                *tuple(self._inflight.values()),
                return_exceptions=True,
            )
        await self._client.close()


__all__ = [
    "COMPILE_CACHE_ENTRY_SCHEMA",
    "COMPILE_CACHE_WRAPPER_VERSION",
    "CachedCompileClient",
    "compile_cache_key",
]
