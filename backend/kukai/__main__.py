"""Entry point: python -m kukai"""

import uvicorn

from kukai.config import get_settings


def main() -> None:
    settings = get_settings()
    host = settings.get_effective_host()
    uvicorn.run(
        "kukai.main:app",
        host=host,
        port=settings.port,
        reload=settings.debug,
        log_level="info" if not settings.debug else "debug",
    )


if __name__ == "__main__":
    main()
