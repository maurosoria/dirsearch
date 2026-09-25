from __future__ import annotations

from optparse import Values
from urllib.parse import urlparse


REQUEST_BACKENDS = ("python", "native")
NATIVE_PREEMPTIVE_AUTH_TYPES = ("basic", "bearer", "jwt")
NATIVE_CHALLENGE_AUTH_ERROR = (
    "--request-backend native supports Basic and Bearer/JWT authentication "
    "only; use the threaded or async engine for Digest/NTLM"
)


def get_async_request_backend_error(opt: Values) -> str | None:
    if not opt.async_mode:
        return None

    for proxy in opt.proxies:
        parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
        if parsed.scheme in ("socks4", "socks4a"):
            return (
                "--async supports SOCKS5 proxies only; use the threaded "
                "engine for SOCKS4"
            )

    return None


def get_native_authentication_error(auth_type: str | None) -> str | None:
    if auth_type in NATIVE_PREEMPTIVE_AUTH_TYPES:
        return None
    return NATIVE_CHALLENGE_AUTH_ERROR


def get_native_request_backend_error(opt: Values) -> str | None:
    if opt.async_mode:
        return "--request-backend native cannot be combined with --async"
    if opt.tor:
        return "--request-backend native does not support Tor or SOCKS proxies yet"
    for proxy in opt.proxies:
        parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
        if parsed.scheme not in ("http", "https"):
            return "--request-backend native supports HTTP and HTTPS proxies only"
    if (opt.auth or opt.auth_type) and (
        error := get_native_authentication_error(opt.auth_type)
    ):
        return error
    if opt.cert_file or opt.key_file:
        return "--request-backend native does not support client certificates yet"
    if opt.random_agents:
        return "--request-backend native does not support --random-agent yet"
    if opt.network_interface:
        return "--request-backend native does not support --interface yet"
    if opt.ip:
        return "--request-backend native does not support --ip yet"
    if opt.max_rate:
        return "--request-backend native does not support --max-rate yet"
    if opt.delay:
        return "--request-backend native does not support --delay yet"
    return None
