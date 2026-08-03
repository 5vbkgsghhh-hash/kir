"""Static file serving — serves kukai_chat_v5.html and assets.

Also serves /kukai_config.js that injects backend URL into the UI.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from kukai.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/kukai_config.js")
async def serve_config(request: Request) -> Response:
    """Serve JavaScript config that sets backend URL for the chat UI."""
    import json
    import re

    settings = get_settings()
    # Use the request's host for the backend URL so it works regardless of access method
    host = request.headers.get("host", f"{settings.host}:{settings.port}")
    # Sanitize host header — only allow valid hostname:port characters
    if not re.match(r'^[a-zA-Z0-9.\-:]+$', host):
        host = f"{settings.host}:{settings.port}"
    scheme = "https" if request.url.scheme == "https" else "http"
    backend_url = f"{scheme}://{host}"

    # Use json.dumps for safe JS string escaping
    js = f"""\
// Auto-generated KUKI configuration
window.__KUKAI_BACKEND = {json.dumps(backend_url)};
window.__KUKAI_API_KEY = '';
window.__KUKAI_DEVICE_ID = '';
"""
    return Response(content=js, media_type="application/javascript")


@router.get("/")
async def serve_index() -> HTMLResponse:
    """Serve the main chat UI."""
    settings = get_settings()
    static_dir = settings.get_static_dir()
    html_path = static_dir / "kukai_chat_v5.html"

    if not html_path.exists():
        return HTMLResponse(
            content="<h1>KUKI</h1><p>Chat UI not found. Place kukai_chat_v5.html in the project root.</p>",
            status_code=200,
        )

    html_content = html_path.read_text(encoding="utf-8")

    # Inject config script before closing </head>
    config_script = '<script src="/kukai_config.js"></script>'
    if config_script not in html_content:
        html_content = html_content.replace("</head>", f"{config_script}\n</head>")

    return HTMLResponse(
        content=html_content,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@router.get("/portal_config.js")
async def serve_portal_config(request: Request) -> Response:
    """Serve JavaScript config for PortalVOR UI (white-label)."""
    import json
    import re

    settings = get_settings()
    host = request.headers.get("host", f"{settings.host}:{settings.port}")
    if not re.match(r'^[a-zA-Z0-9.\-:]+$', host):
        host = f"{settings.host}:{settings.port}"
    scheme = "https" if request.url.scheme == "https" else "http"
    backend_url = f"{scheme}://{host}"

    js = f"""\
window.__PORTAL_BACKEND = {json.dumps(backend_url)};
window.__PORTAL_API_KEY = '';
"""
    return Response(content=js, media_type="application/javascript")


@router.get("/portal_vorhub.html")
async def serve_portal() -> HTMLResponse:
    """Serve the PortalVOR white-label UI."""
    settings = get_settings()
    static_dir = settings.get_static_dir()
    html_path = static_dir / "portal_vorhub.html"

    if not html_path.exists():
        return HTMLResponse(content="<h1>Not found</h1>", status_code=404)

    return HTMLResponse(
        content=html_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/docs/{filepath:path}")
async def serve_docs(filepath: str) -> FileResponse:
    """Serve docs files (architecture diagrams, etc.)."""
    from fastapi import HTTPException

    settings = get_settings()
    static_dir = settings.get_static_dir()
    docs_dir = static_dir / "docs"
    file_path = (docs_dir / filepath).resolve()

    if not str(file_path).startswith(str(docs_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Doc not found")

    return FileResponse(path=file_path)


@router.get("/assets/{filepath:path}")
async def serve_asset(filepath: str) -> FileResponse:
    """Serve static assets (fonts, icons, etc.)."""
    from fastapi import HTTPException

    settings = get_settings()
    static_dir = settings.get_static_dir()
    assets_dir = static_dir / "assets"
    file_path = (assets_dir / filepath).resolve()

    # Prevent path traversal — resolved path must be inside assets_dir
    if not str(file_path).startswith(str(assets_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")

    return FileResponse(path=file_path)
