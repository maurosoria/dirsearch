from __future__ import annotations

import re
from urllib.parse import quote, urlsplit


PROXY_AUTHENTICATION_REQUIRED = 407
_HTTP_STATUS_PATTERNS = (
    re.compile(
        r"(?:HTTP(?:/[0-9.]+)?|status(?: code)?|"
        r"tunnel(?: connection)? (?:failed|unsuccessful))"
        r"\s*:?\s*([1-5][0-9]{2})\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*([1-5][0-9]{2})(?:\s|$)"),
)


def add_proxy_authentication(proxy: str, credential: str | None) -> str:
    """Add percent-encoded configured credentials unless the proxy has userinfo."""
    if not credential or "@" in urlsplit(proxy).netloc:
        return proxy

    username, separator, password = credential.partition(":")
    userinfo = quote(username, safe="")
    if separator:
        userinfo += ":" + quote(password, safe="")

    return proxy.replace("://", f"://{userinfo}@", 1)


def proxy_error_status(error: BaseException | str) -> int | None:
    for message in _error_messages(error):
        for pattern in _HTTP_STATUS_PATTERNS:
            match = pattern.search(message)
            if match:
                return int(match.group(1))

    return None


def is_proxy_connect_rejection(error: BaseException | str) -> bool:
    return any(
        "tunnel error: unsuccessful" in message.lower()
        for message in _error_messages(error)
    )


def is_proxy_authentication_error(error: BaseException | str) -> bool:
    if proxy_error_status(error) == PROXY_AUTHENTICATION_REQUIRED:
        return True

    markers = (
        "proxy authentication required",
        "proxy authorization required",
        "socks error: credentials not accepted",
    )
    return any(
        marker in message.lower()
        for message in _error_messages(error)
        for marker in markers
    )


def _error_messages(error: BaseException | str):
    pending: list[BaseException | str] = [error]
    seen = set()

    while pending:
        current = pending.pop()
        if isinstance(current, BaseException):
            if id(current) in seen:
                continue
            seen.add(id(current))
            for attr in ("__cause__", "__context__"):
                chained = getattr(current, attr, None)
                if chained is not None:
                    pending.append(chained)

        yield str(current)


def format_proxy_error(error: BaseException | str) -> str:
    if is_proxy_authentication_error(error):
        return "Proxy authentication required"
    status = proxy_error_status(error)
    if status is not None:
        return f"Proxy connection failed with HTTP {status}"
    if is_proxy_connect_rejection(error):
        return "Proxy CONNECT request was rejected"
    return "Cannot establish the proxy connection"
