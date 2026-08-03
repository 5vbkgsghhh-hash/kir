"""First-launch setup endpoints — API key configuration.

In local mode, users need to provide their own LLM API key.
These endpoints allow the chat UI to check whether the backend
is configured and to save the API key to a .env file.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from kukai.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])


class SetupStatusResponse(BaseModel):
    configured: bool
    llm_model: str
    has_api_key: bool
    mode: str  # "local" or "remote"


class ConfigureRequest(BaseModel):
    llm_api_key: str
    llm_model: str = ""  # Optional: override default model


class ConfigureResponse(BaseModel):
    ok: bool
    detail: str = ""


def _get_env_file_path() -> Path:
    """Return path to the .env file.

    In installed mode (Program Files): %LOCALAPPDATA%/KUKI/.env
    In dev mode: backend/.env
    """
    backend_dir = Path(__file__).parent.parent.parent
    prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    if str(backend_dir).startswith(prog_files):
        local_app_data = os.environ.get(
            "LOCALAPPDATA",
            str(Path.home() / "AppData" / "Local"),
        )
        return Path(local_app_data) / "KUKI" / ".env"
    return backend_dir / ".env"



def _write_env_file(env_path: Path, values: dict[str, str]) -> None:
    """Write values to .env file, preserving comments and adding new keys."""
    lines: list[str] = []
    existing_keys: set[str] = set()

    # Read existing file preserving comments
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                lines.append(line)
                continue
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in values:
                    lines.append(f"{key}={values[key]}")
                    existing_keys.add(key)
                else:
                    lines.append(line)

    # Add new keys that weren't in the file
    for key, value in values.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@router.get("/status", response_model=SetupStatusResponse)
async def setup_status() -> SetupStatusResponse:
    """Check if the backend is configured (has API key)."""
    settings = get_settings()
    has_key = bool(settings.llm_api_key)
    return SetupStatusResponse(
        configured=has_key,
        llm_model=settings.llm_model,
        has_api_key=has_key,
        mode="remote" if settings.remote_mode else "local",
    )


@router.post("/configure", response_model=ConfigureResponse)
async def configure(request_body: ConfigureRequest, request: Request) -> ConfigureResponse:
    """Save API key and optional model to .env file.

    This endpoint is only available in local mode and only from localhost.
    After saving, the user must restart the backend for changes to take effect.
    """
    # Only allow from localhost
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            status_code=403,
            detail="Setup доступен только с localhost",
        )

    settings = get_settings()

    if settings.remote_mode:
        raise HTTPException(
            status_code=403,
            detail="Настройка недоступна в удалённом режиме",
        )

    api_key = request_body.llm_api_key.strip()
    if not api_key:
        return ConfigureResponse(ok=False, detail="API ключ не может быть пустым")

    # Basic validation — key should look like a real API key
    if len(api_key) < 10:
        return ConfigureResponse(ok=False, detail="API ключ слишком короткий")

    # Prepare values to save
    env_values = {"KUKAI_LLM_API_KEY": api_key}

    if request_body.llm_model:
        env_values["KUKAI_LLM_MODEL"] = request_body.llm_model

    # Save to .env file
    env_path = _get_env_file_path()
    try:
        _write_env_file(env_path, env_values)
        logger.info("API key saved to %s", env_path)
    except OSError as e:
        logger.error("Failed to save .env file: %s", e)
        return ConfigureResponse(
            ok=False,
            detail=f"Не удалось сохранить настройки: {e}",
        )

    # Also update the running process environment so a restart picks it up
    os.environ["KUKAI_LLM_API_KEY"] = api_key
    if request_body.llm_model:
        os.environ["KUKAI_LLM_MODEL"] = request_body.llm_model

    return ConfigureResponse(
        ok=True,
        detail="Настройки сохранены. Перезапустите KUKI для применения.",
    )
