"""Shared HTTP boundary checks for credential-bearing GraphOS clients."""
from __future__ import annotations

from urllib.parse import urlsplit


class WorkerError(RuntimeError):
    """Worker failure that callers can report without exposing upstream details."""


def validate_api_url(value: str) -> str:
    """Require TLS outside exact loopback hosts; do not resolve or contact a host."""
    if (not isinstance(value, str) or not value or "\\" in value
            or "?" in value or "#" in value
            or any(character.isspace() or ord(character) < 32 or ord(character) == 127
                   for character in value)):
        raise ValueError("API URL must not contain whitespace, controls, query, fragment or backslash")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("API URL has an invalid host or port") from None
    if (parsed.scheme not in {"http", "https"} or not host
            or parsed.username is not None or parsed.password is not None
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("API URL must use HTTP(S), a valid host/port and no embedded credentials")
    if parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote API connections require HTTPS; plaintext HTTP is limited to exact loopback hosts")
    return value
