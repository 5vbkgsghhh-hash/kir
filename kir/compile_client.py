"""Client for the server-side Roslyn compile service."""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

from kir import env
from kir.registry_base import REVIT_VERSIONS

logger = logging.getLogger(__name__)

#: 🔴 DERIVED FROM THE AUTHORITY, NOT SPELLED OUT (01.09.2026). A
#: literal of the same six used to stand here, and
#: `test_revit_version_has_one_source` named it a copy of the
#: authority: the list of versions must live in ONE place
#: (`registry_base.REVIT_VERSIONS`), otherwise the two places would
#: drift apart on exactly the version we do not have — that is, on
#: someone else's machine, and silently.
_ALL_SHIPPED_REVIT_VERSIONS = frozenset(REVIT_VERSIONS)


def _resolve_required_revit_versions() -> "frozenset[str]":
    """Required Revit versions for the compile gate.

    The *required* subset is configurable via ``KUKAI_COMPILE_REQUIRED_VERSIONS``
    (comma-separated, e.g. ``"2025,2026"``), read by BOTH the C# gate
    (``RoslynCompiler.ResolveRequiredVersions``) and this Python readiness check.
    Unset/empty/malformed → the full shipped matrix (fail-closed: an empty
    required set would mean "require nothing").

    🔴 "MALFORMED" IS ABOUT ANY SINGLE ENTRY, NOT ABOUT THE WHOLE STRING
    (F-369, 30.08.2026). Before this date the body said something
    different from this very docstring: an entry that was not understood
    was silently DROPPED, and what remained was enough for the parse to
    count as successful. `"2025,2O26"` (a Latin O instead of a zero)
    produced `{2025}` — ONE version instead of six — meaning a typo in
    the environment variable SILENTLY NARROWED the required set and
    WEAKENED the compile gate instead of failing it. Not a single line
    said so. The intent was never in dispute: the origin commit
    `e9316b21` (22.07.2026, the KUKAI tree) is named "fail-closed" and
    promises "never empty => never fail-open"; only the body drifted
    from the prose. It is fixed in favor of the prose.

    An empty entry (`"2025,2026,"`, `"2025,,2026"`) does NOT count as
    garbage and drops nothing: C# strips it with
    `StringSplitOptions.RemoveEmptyEntries`, and here it is stripped the
    same way — otherwise a trailing comma would ruin a legitimate
    setting.

    🔴 ONE DISCREPANCY WITH C# — NAMED, ONE-DIRECTIONAL, AND SAFE.
    For a NON-EMPTY entry that is not a four-digit number, C# silently
    drops it and keeps the rest (`RoslynCompiler.cs`,
    `.Where(v => v.Length == 4 && v.All(char.IsDigit))`), while here it
    drops THE WHOLE parse into the full matrix and SOUNDS a warning.
    Python can, after this, demand MORE than C#, and never less, so the
    discrepancy cannot weaken the gate. The visible symptom of a typo:
    `health()` will return False on a `requiredVersions` mismatch,
    meaning the service will be declared NOT READY instead of silently
    accepting a narrowed set. The twin lives OUTSIDE KIR, in the KUKAI
    tree: `/opt/kukai-rebuild1/backend/compile-service/RoslynCompiler.cs`.
    """
    # 🔴 BOTH NAMES ARE READ, AND THIS WAS FOUND AS A DISCREPANCY BETWEEN
    # TWO TREES (01.09.2026). The published package read ONLY `KIR_…`,
    # this tree read ONLY `KUKAI_…`: one value, two names, and no place
    # read both. A person who narrowed the matrix on their own machine
    # got a different answer depending on where the package came from.
    # `env.get` asks for the new name first, then the old one — the
    # order carries meaning.
    #
    # 🔴 A BOUNDARY THAT MUST NOT BE PASSED OVER IN SILENCE: the C# twin
    # (`RoslynCompiler.ResolveRequiredVersions`, the KUKAI tree) reads
    # ONLY the old name. So with the NEW name set, Python will narrow
    # the matrix while the service will not, and `health()` will
    # declare the service NOT READY on a `requiredVersions` mismatch.
    # This is a loud refusal, not a silent acceptance of a narrowed set
    # — the same fail-closed side described below about the typo. Until
    # the twin learns the second name, set the narrowing with the OLD
    # name.
    raw = env.get("KIR_COMPILE_REQUIRED_VERSIONS")
    if not raw or not raw.strip():
        return _ALL_SHIPPED_REVIT_VERSIONS
    # Empty entries are dropped silently — this matches
    # `RemoveEmptyEntries` on the C# side. Non-empty but unrecognized
    # ones are NOT dropped silently: they are exactly the F-369 finding.
    named = [tok for tok in (part.strip() for part in raw.split(",")) if tok]
    parsed = {tok for tok in named if len(tok) == 4 and tok.isdigit()}
    rejected = [tok for tok in named if tok not in parsed]
    if rejected or not parsed:
        logger.warning(
            "KUKAI_COMPILE_REQUIRED_VERSIONS=%r: %s. The narrowing is REJECTED "
            "AS A WHOLE and the full shipped matrix %s stays required. An "
            "unreadable entry is never dropped in silence: a typo here would "
            "weaken the compile gate instead of failing it (F-369).",
            raw,
            ("unreadable entries: " + ", ".join(repr(t) for t in rejected))
            if rejected else "no non-empty entry at all",
            sorted(_ALL_SHIPPED_REVIT_VERSIONS))
        return _ALL_SHIPPED_REVIT_VERSIONS
    return frozenset(parsed)


_REQUIRED_REVIT_VERSIONS = _resolve_required_revit_versions()


@dataclass
class CompileError:
    code: str       # e.g. "CS0246"
    message: str    # e.g. "The type 'Foo' could not be found"
    line: int
    column: int


@dataclass
class CompileResult:
    """The compilation verdict. `success` is EXACTLY `True` or `False`.

    🔴 THE ANNOTATION CHECKED NOTHING (04.09.2026). `success: bool` is a
    hint to the type checker, not a mechanism: the string `"false"`,
    arriving from the service's response body, landed here as-is and
    was read as TRUE everywhere (`bool("false")` is true in Python).
    Measured before the fix, an HTTP 200 with the body
    `{"success": "false", "errors": [CS0246]}`:

        CompileResult(success='false', errors=[CompileError(code='CS0246', ...)])

    That is, code that FAILED TO COMPILE, with the ERROR NAMED IN THE
    SAME RESPONSE, was read as "compiled." `__post_init__` makes the
    declared type a carrier of the law, not a comment: there is now
    nothing to lie with, because such an object will not construct.

    The check stands ON THE TYPE, not only at the HTTP door, because
    there are two doors: the service's response and the cache record
    (`compile_cache._payload_to_result`), and the second is read
    LONGER than the first.
    """

    success: bool
    errors: list[CompileError] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.success is not True and self.success is not False:
            raise TypeError(
                f"CompileResult.success: ожидается True или False, получено "
                f"{self.success!r} ({type(self.success).__name__}). Приведения "
                f"здесь НЕТ намеренно: bool({self.success!r}) даёт "
                f"{bool(self.success)!r}, и ответ службы «false» строкой "
                f"объявил бы код СКОМПИЛИРОВАННЫМ")


class CompileClient:
    """Client for server-side Roslyn compile service."""

    def __init__(self, base_url: str = "http://localhost:52412", timeout: float = 15.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._available = False
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout))
        return self._client

    async def check(self, wrapped_code: str, revit_version: str) -> Optional[CompileResult]:
        """Compile code and return result. Returns None if service unavailable."""
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self._base_url}/compile",
                json={"code": wrapped_code, "revitVersion": revit_version},
            )
            if resp.status_code != 200:
                logger.warning("Compile service returned %d", resp.status_code)
                return None
            data = resp.json()
            # 🔴 A NON-BOOLEAN `success` IS AN ANSWER THAT CANNOT BE
            # TRUSTED (04.09.2026). `data.get("success", False)` used to
            # stand here directly in the constructor, and
            # `{"success": "false"}` reached the caller as true. The
            # service is ALIVE, but we did not understand what it said
            # — and this method already HAS a word for "no verdict":
            # `None`. It is also fail-closed: `gate_runner._compile_check`
            # treats `None` as `compile-service-no-answer` and does NOT
            # count the compilation as passed, whereas `success=False`
            # would be the assertion "the code does not compile," which
            # the service never made.
            #
            # A MISSING KEY IS THE SAME CASE, NOT "DID NOT COMPILE." The
            # previous default of `False` turned silence into a
            # VERDICT: a response that said nothing declared someone
            # else's code unbuildable — and without a single error in
            # the list, that is, irrefutably.
            verdict = data.get("success")
            if verdict is not True and verdict is not False:
                logger.warning(
                    "Compile service answered HTTP 200 with an unreadable "
                    "verdict: success=%r (%s). Treated as NO ANSWER, never as "
                    "a verdict — coercing it would have read as %r.",
                    verdict, type(verdict).__name__, bool(verdict))
                return None
            errors = [
                CompileError(
                    code=e.get("code", ""),
                    message=e.get("message", ""),
                    line=e.get("line", 0),
                    column=e.get("column", 0),
                )
                for e in data.get("errors", [])
            ]
            result = CompileResult(success=verdict, errors=errors)
            self._available = True
            return result
        except Exception as e:
            logger.debug("Compile service unavailable: %s", e)
            self._available = False
            return None

    async def health(self) -> bool:
        """Return true only for a complete six-version reference matrix.

        ``/health`` is deliberately a liveness endpoint and returns HTTP 200
        even when one or more Revit reference sets are absent.  Treating that
        response as gate readiness allowed a nominal ``6/6`` run to start on a
        partially provisioned service.  ``/ready`` is the compile service's
        fail-closed contract; validate its advertised matrix as well as its
        status so a malformed or stale deployment cannot be mistaken for the
        six-version gate.
        """
        try:
            client = await self._get_client()
            resp = await client.get(f"{self._base_url}/ready")
            if resp.status_code != 200:
                self._available = False
                return False
            data = resp.json()
            versions = data.get("versions")
            required = data.get("requiredVersions")
            missing = data.get("missingVersions")
            self._available = (
                data.get("status") == "ready"
                and isinstance(versions, list)
                and len(versions) == len(_REQUIRED_REVIT_VERSIONS)
                and all(isinstance(item, str) for item in versions)
                and set(versions) == _REQUIRED_REVIT_VERSIONS
                and isinstance(required, list)
                and len(required) == len(_REQUIRED_REVIT_VERSIONS)
                and all(isinstance(item, str) for item in required)
                and set(required) == _REQUIRED_REVIT_VERSIONS
                and missing == []
            )
            return self._available
        except Exception:
            self._available = False
            return False

    @property
    def available(self) -> bool:
        return self._available

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
