from __future__ import annotations

from optparse import Values


REQUEST_BACKENDS = ("python", "native")


def get_native_request_backend_error(opt: Values) -> str | None:
    if opt.async_mode:
        return "--request-backend native cannot be combined with --async"
    if opt.http_method and opt.http_method.upper() != "GET":
        return "--request-backend native currently supports GET requests only"
    if opt.data or opt.data_file:
        return "--request-backend native does not support request bodies yet"
    if opt.proxies or opt.proxies_file or opt.tor:
        return "--request-backend native does not support proxies yet"
    if opt.proxy_auth:
        return "--request-backend native does not support proxy authentication yet"
    if opt.replay_proxy:
        return "--request-backend native does not support --replay-proxy yet"
    if opt.auth or opt.auth_type:
        return "--request-backend native does not support authentication yet"
    if opt.cert_file or opt.key_file:
        return "--request-backend native does not support client certificates yet"
    if opt.random_agents:
        return "--request-backend native does not support --random-agent yet"
    if opt.network_interface:
        return "--request-backend native does not support --interface yet"
    if opt.max_rate:
        return "--request-backend native does not support --max-rate yet"
    if opt.delay:
        return "--request-backend native does not support --delay yet"
    if opt.follow_redirects:
        return "--request-backend native does not support --follow-redirects yet"

    return None
