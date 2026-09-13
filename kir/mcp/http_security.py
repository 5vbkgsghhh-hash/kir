"""Opt-in HTTP access and file-output capabilities; stdio is unaffected."""
from __future__ import annotations

import hmac
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

from kir import wire_json


class HTTPConfigurationError(ValueError):
    pass


def configured_token(token_file=None) -> bytes:
    """Never take a credential in argv or echo its contents in diagnostics."""
    if token_file:
        try:
            path = Path(token_file).expanduser()
            if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise HTTPConfigurationError("token_file_permissions: нужен файл с правами 0600")
            with path.open("rb") as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise HTTPConfigurationError("token_file_too_large: файл токена больше 4096 байт")
            token = raw.decode("ascii").strip()
        except (OSError, UnicodeError):
            raise HTTPConfigurationError("token_file_unreadable: файл токена не прочитан") from None
    else:
        token = os.environ.get("KIR_MCP_TOKEN", "")
    if not 32 <= len(token) <= 4096 or not token.isascii() or any(c.isspace() for c in token):
        raise HTTPConfigurationError(
            "http_token_required: задайте случайный токен (32–4096 ASCII-символов без пробелов) "
            "через --token-file или KIR_MCP_TOKEN; значение не передаётся в аргументах")
    return token.encode("ascii")


def remote_origin(host: str, *, allow_remote=False, public_origin=None) -> str | None:
    if host in {"127.0.0.1", "localhost", "::1"} and not public_origin:
        return None
    if not allow_remote:
        raise HTTPConfigurationError("remote_bind_requires_opt_in: сетевой --host требует --allow-remote")
    try:
        parsed = urlsplit(public_origin or "")
        port = parsed.port
    except ValueError:
        raise HTTPConfigurationError("public_origin_invalid: нужен точный https origin TLS-прокси") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or "*" in parsed.netloc or (port is not None and not 1 <= port <= 65535)):
        raise HTTPConfigurationError("public_origin_invalid: нужен --public-origin https://имя[:порт]")
    return "https://" + parsed.netloc


class BearerTokenMiddleware:
    @staticmethod
    def check(token: bytes) -> bytes:
        """The middleware's own acceptance rule, callable before any request arrives."""
        if type(token) is not bytes or not 32 <= len(token) <= 4096 or not token.isascii() or any(
                byte <= 32 or byte == 127 for byte in token):
            raise HTTPConfigurationError("http_token_required: нужен непустой случайный ASCII токен")
        return token

    def __init__(self, app, *, token: bytes, require_https=False):
        self.app, self.token, self.require_https = app, self.check(token), require_https

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = [value for key, value in scope.get("headers", ()) if key.lower() == b"authorization"]
        accepted = False
        if len(headers) == 1:
            scheme, separator, value = headers[0].partition(b" ")
            accepted = bool(separator and scheme.lower() == b"bearer"
                            and hmac.compare_digest(value, self.token))
        code = None
        if self.require_https and scope.get("scheme") != "https":
            status, code = 403, "https_required"
        elif not accepted:
            status, code = 401, "http_token_required"
        if code:
            raw = wire_json.encode({"error": code})
            await send({"type": "http.response.start", "status": status, "headers": [
                (b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode()),
                (b"cache-control", b"no-store"), (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": raw})
            return
        await self.app(scope, receive, send)


class OutputRoot:
    """HTTP writes use anchored directory handles and exclusive file creation.

    A platform lacking these primitives refuses file output, rather than claiming
    a resolve-then-open check closes symlink races. Inline output still works.
    """
    reports_effects = True  # HTTP results name filesystem effects; the stdio contract does not

    def __init__(self, root):
        try:
            self.root = Path(root).expanduser().resolve(strict=True)
            info = self.root.stat()
            if not stat.S_ISDIR(info.st_mode):
                raise OSError("not a directory")
            self.identity = (info.st_dev, info.st_ino)
        except OSError:
            raise HTTPConfigurationError("output_root_unavailable: --out-root должен быть существующим каталогом") from None

    def directory(self, value: str) -> Path:
        candidate = Path(value).expanduser()
        candidate = Path(os.path.abspath(candidate if candidate.is_absolute() else self.root / candidate))
        if not candidate.is_relative_to(self.root):
            raise HTTPConfigurationError("output_outside_root: out_dir вне разрешённого --out-root")
        return candidate

    def write(self, directory: Path, name: str, source: str) -> Path:
        if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
                or os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd):
            raise HTTPConfigurationError("output_platform_unsupported: нет безопасных directory-handle операций; используйте inline или stdio")
        fd = None
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            fd = os.open(self.root, flags)
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) != self.identity:
                raise HTTPConfigurationError("output_root_changed: каталог сменился после запуска сервера")
            for part in directory.relative_to(self.root).parts:
                try:
                    child = os.open(part, flags, dir_fd=fd)
                except FileNotFoundError:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                    child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=fd)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(source)
            return directory / name
        except FileExistsError:
            raise HTTPConfigurationError("output_exists: HTTP не перезаписывает файлы; выберите новый out_dir") from None
        except OSError:
            raise HTTPConfigurationError("output_write_refused: проверьте каталог/ссылки/права; уже созданные файлы не удалены") from None
        finally:
            if fd is not None:
                os.close(fd)
