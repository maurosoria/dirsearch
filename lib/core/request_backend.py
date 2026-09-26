from __future__ import annotations

from optparse import Values
from urllib.parse import urlparse


REQUEST_BACKENDS = ("python", "native")
NATIVE_AUTHENTICATION_TYPES = ("basic", "bearer", "digest", "jwt")
NATIVE_NTLM_AUTH_ERROR = (
    "--request-backend native does not support NTLM authentication yet; "
    "use the threaded or async engine"
)


def get_native_authentication_error(auth_type: str | None) -> str | None:
    if auth_type in NATIVE_AUTHENTICATION_TYPES:
        return None
    if auth_type == "ntlm":
        return NATIVE_NTLM_AUTH_ERROR
    return f"--request-backend native does not support {auth_type} authentication"


NATIVE_PROXY_SCHEMES = (
    "http",
    "https",
    "socks4",
    "socks4a",
    "socks5",
    "socks5h",
)
NATIVE_PROXY_SCHEME_ERROR = (
    "--request-backend native supports HTTP, HTTPS, SOCKS4, SOCKS4a, "
    "SOCKS5, and SOCKS5h proxies only"
)
NATIVE_SOCKS4_AUTH_ERROR = (
    "--request-backend native does not support SOCKS4 user IDs; "
    "use SOCKS5 or the threaded engine when proxy credentials are required"
)
CLIENT_CERTIFICATE_PAIR_ERROR = "--cert-file and --key-file must be used together"


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


def get_native_request_backend_error(opt: Values) -> str | None:
    if opt.async_mode:
        return "--request-backend native cannot be combined with --async"
    for proxy in opt.proxies:
        parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
        if parsed.scheme not in NATIVE_PROXY_SCHEMES:
            return NATIVE_PROXY_SCHEME_ERROR
        if parsed.scheme in ("socks4", "socks4a") and (
            opt.proxy_auth or parsed.username is not None
        ):
            return NATIVE_SOCKS4_AUTH_ERROR
    if (opt.auth or opt.auth_type) and (
        error := get_native_authentication_error(opt.auth_type)
    ):
        return error
    if bool(opt.cert_file) != bool(opt.key_file):
        return CLIENT_CERTIFICATE_PAIR_ERROR
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
