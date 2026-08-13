from __future__ import annotations

from optparse import Values
from urllib.parse import urlparse


REQUEST_BACKENDS = ("python", "native")


def get_native_target_error(url: str) -> str | None:
    parsed = urlparse(url if "://" in url else f"//{url}")
    if parsed.username is not None:
        return (
            "--request-backend native does not support credentials embedded "
            "in target URLs yet"
        )

    return None


def get_native_request_backend_error(opt: Values) -> str | None:
    if opt.async_mode:
        return "--request-backend native cannot be combined with --async"
    if opt.http_method and opt.http_method.upper() != "GET":
        return "--request-backend native currently supports GET requests only"
    if opt.data or opt.data_file:
        return "--request-backend native does not support request bodies yet"
    if opt.tor:
        return "--request-backend native does not support Tor or SOCKS proxies yet"
    for proxy in opt.proxies:
        parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
        if parsed.scheme not in ("http", "https"):
            return "--request-backend native supports HTTP and HTTPS proxies only"
    if opt.auth or opt.auth_type:
        return "--request-backend native does not support authentication yet"
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
    for url in getattr(opt, "urls", ()):
        if error := get_native_target_error(url):
            return error

    return None
