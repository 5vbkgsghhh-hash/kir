"""Hermeticity guard for keyless benchmark modes (plan 014).

An "offline" run must be incapable of spending money or silently flipping
legs live. Under the prod venv, ``import litellm`` (via ``kukai.llm.client``)
loads the prod .env into ``os.environ`` (dotenv walks up from litellm's own
file — proven empirically; see plan 014 "Current state" D). The guard runs
AFTER that import, pops the keys, and refuses when keys remain reachable
through .env files. ``load_dotenv(override=False)`` cannot resurrect popped
vars, so once we pop them they stay gone for the rest of the process.

Never prints key VALUES — only names. The refusal path exits 3 (a distinct
code the CLI / tests can assert on) and explains how to run cleanly.
"""

from __future__ import annotations

import sys

# Every env var that, if present, would let a leg spend money or go live.
KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "KUKAI_OPENAI_API_KEY",
    "KUKAI_EMBEDDING_API_KEY",
    "KUKAI_LLM_API_KEY",
    "KUKAI_LLM_FALLBACK_API_KEY",
    "KUKAI_LLM_GOOGLE_BACKUP_API_KEY",
    "KUKAI_LLM_GOOGLE_FALLBACK_API_KEY",
    "COHERE_API_KEY",
    "OPENROUTER_API_KEY",
)


def enforce_offline_hermeticity() -> dict:
    """Make the current process incapable of spending money.

    Order is load-bearing:
      ① import ``kukai.llm.client`` — forces litellm's one-time
         ``load_dotenv`` NOW (so any prod .env keys are already in env and
         get popped below; doing this after the pop would re-introduce them);
      ② pop every key-bearing env var;
      ③ ``get_settings.cache_clear()`` and re-read settings;
      ④ refuse (``SystemExit(3)``) if settings STILL see a key — that means a
         ``.env`` file is reachable from cwd / ``backend/.env`` and pydantic
         re-loaded it, so a "live" leg could still fire.

    Returns ``{"popped": [names], "refused": False}`` on success.
    """
    import os

    import kukai.llm.client  # noqa: F401 — force litellm's one-time load_dotenv NOW

    popped = [k for k in KEY_ENV_VARS if os.environ.pop(k, None)]

    from kukai.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    if s.embedding_api_key or s.openai_api_key or s.llm_api_key or s.llm_fallback_api_key:
        print(
            "offline/smoke mode refused: live API keys are reachable via a .env "
            "file (cwd or backend/.env). Run from a keyless directory, or use "
            "--live/--e2e --yes-spend for a consented live run.",
            file=sys.stderr,
        )
        raise SystemExit(3)
    return {"popped": popped, "refused": False}
